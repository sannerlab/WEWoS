# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Running a network in its own confined process, for networks from other people.

A network file is a program: opening it runs its nodes' edited code, and
running it runs every node, some of which evaluate their widget values as
Python. A network the user does not trust therefore runs in a worker process
(wewos/worker.py) confined by the operating system, at one of three levels:

  sandboxed     its code sees only its own folder (read-write), the Python
                environment and the system libraries (read-only), and the
                folders the user grants (read-only)
  readonly      its code can read every file the user can, and write only
                its own folder
  unrestricted  no worker: the network runs in the server, as it always did

The confinement:
  Linux   bubblewrap: the worker has its own process, IPC, user and network
          namespaces and sees only the files of its level (bind mounts)
  macOS   sandbox-exec, with a profile written for the level (macos_profile):
          what the worker may read and write, and whether it may use the
          network
In both, no internet unless allowed for that network (Fetch PDB still works:
the server downloads the checked PDB id for it), memory and file size limits,
and the worker ends with the server. The server and the worker talk over two
pipes (wewos/ipc.py), which no network rule affects. The server passes the
page's requests on (IsolatedSession has the Session methods the server uses)
and never follows a path the worker could have planted in its folder.
"""
import base64
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

from .ipc import Channel, ChannelClosed, Pipes, RemoteError

LEVELS = ('sandboxed', 'readonly', 'unrestricted')
STRICTNESS = {'unrestricted': 0, 'readonly': 1, 'sandboxed': 2}
LABELS = {'sandboxed': 'Sandboxed: sees only its own folder',
          'readonly': 'Read-only: reads your files, writes only its own folder',
          'unrestricted': 'Unrestricted: runs with your rights'}
CALL_TIMEOUT = 600.0           # a call the network does not answer (stuck in its code)
START_TIMEOUT = 180.0          # importing the libraries and opening the network
UPLOAD_PIECE = 8 << 20
FILE_LIMIT = 4 << 30           # the largest file the network may write
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_EXEC = '/usr/bin/sandbox-exec'
# what a sandboxed network may read on macOS besides its environment: the
# system, its libraries, fonts and time zones, and Homebrew's prefixes
MACOS_SYSTEM = ('/System', '/usr/lib', '/usr/libexec', '/usr/share', '/usr/bin', '/bin',
                '/usr/sbin', '/sbin', '/private/etc', '/private/var/db/timezone',
                '/private/var/db/dyld', '/Library/Fonts', '/Library/Frameworks',
                '/opt/homebrew', '/usr/local')
_probe = None


class WorkerError(Exception):
    """A failure inside the worker; carries the worker's traceback."""

    def __init__(self, message, trace=None):
        Exception.__init__(self, message)
        self.remote_trace = trace


def check_level(level):
    level = (level or '').strip().lower().replace('-', '')
    if level not in LEVELS:
        raise ValueError('isolation level must be one of %s, not %r' % (', '.join(LEVELS), level))
    return level


def stricter(a, b):
    return a if STRICTNESS[a] >= STRICTNESS[b] else b


def available():
    """(True, '') when networks can be isolated here, else (False, why)."""
    global _probe
    if _probe is None:
        if sys.platform.startswith('linux'):
            _probe = _probe_linux()
        elif sys.platform == 'darwin':
            _probe = _probe_macos()
        else:
            _probe = (False, 'isolating a network needs Linux (bubblewrap) or macOS '
                             '(sandbox-exec); this server runs on %s' % sys.platform)
    return _probe


def _probe_linux():
    if shutil.which('bwrap') is None:
        return (False, 'isolating a network needs bubblewrap (bwrap), which is not '
                       'installed; on Debian or Ubuntu: apt install bubblewrap')
    try:
        r = subprocess.run(['bwrap', '--unshare-all', '--ro-bind', '/', '/', '--dev', '/dev',
                            '--proc', '/proc', '--die-with-parent', 'true'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        ok, why = r.returncode == 0, r.stdout.decode('utf-8', 'replace').strip()
    except (OSError, subprocess.SubprocessError) as e:
        ok, why = False, str(e)
    return (True, '') if ok else (
        False, 'bubblewrap cannot create a sandbox here (%s); unprivileged user '
               'namespaces may be disabled' % (why or 'it failed'))


def _probe_macos():
    """sandbox-exec with the real profile of a sandboxed network: Python,
    numpy and the worker must start under it."""
    if not os.path.exists(SANDBOX_EXEC):
        return (False, 'isolating a network needs %s, which this macOS does not have' % SANDBOX_EXEC)
    folder = tempfile.mkdtemp(prefix='wewos-probe-')
    try:
        _prepare_home(folder)
        args, env, kw = command('sandboxed', False, folder, None, None)
        args = args[:args.index(sys.executable)] + [
            sys.executable, '-c', 'import numpy, wewos.worker, wewos.session; print("sandbox ok")']
        r = subprocess.run(args, env=env, cwd=folder, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=120)
        out = r.stdout.decode('utf-8', 'replace').strip()
        if r.returncode == 0 and out.endswith('sandbox ok'):
            return (True, '')
        return (False, 'sandbox-exec could not run WEWoS under its profile: %s'
                       % (out.splitlines()[-1] if out else 'exit code %s' % r.returncode))
    except (OSError, subprocess.SubprocessError) as e:
        return (False, 'sandbox-exec failed: %s' % e)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def memory_limit():
    """Three quarters of the machine's memory."""
    try:
        return int(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') * 0.75)
    except (ValueError, OSError, AttributeError):
        return None


def _real(p):
    return os.path.realpath(os.path.abspath(os.path.expanduser(p)))


def _inside(p, roots):
    return any(p == r or p.startswith(r.rstrip('/') + '/') for r in roots)


def read_only_paths(user_libraries=None):
    """What a sandboxed network must read to run: the Python environment, the
    WEWoS code, the folders on the module search path, and the files of the
    user's own node libraries."""
    home = _real('~')
    cwd = _real(os.getcwd())
    paths = []
    for p in [sys.prefix, sys.base_prefix, sys.exec_prefix, REPO] + list(sys.path) + \
            os.environ.get('LD_LIBRARY_PATH', '').split(':'):
        if not p or not os.path.exists(p):
            continue
        p = _real(p)
        # never the user's home or a folder above it, nor the folder the server
        # was started from (python -m puts it on the path)
        if p == '/' or home == p or home.startswith(p.rstrip('/') + '/') or (p == cwd and p != REPO):
            continue
        paths.append(p)
    for src in (user_libraries or {}).values():
        f = (src or {}).get('file')
        if f and os.path.exists(os.path.expanduser(f)):
            paths.append(os.path.dirname(_real(f)))
    out = []
    for p in sorted(set(paths), key=len):
        if not _inside(p, out) and not _inside(p, ['/usr', '/etc']):
            out.append(p)
    return out


def environment(level, folder):
    """The worker's environment variables: no secret of the server's, its home
    and temporary files inside its folder."""
    folder = _real(folder)
    home = os.path.join(folder, '.wewos')
    env = {'PATH': os.pathsep.join([os.path.join(sys.prefix, 'bin'), '/usr/bin', '/bin']),
           'PYTHONPATH': REPO, 'PYTHONNOUSERSITE': '1', 'PYTHONIOENCODING': 'utf-8',
           'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'HOME': home,
           'TMPDIR': '/tmp' if sys.platform.startswith('linux') else os.path.join(home, 'tmp'),
           'MPLCONFIGDIR': os.path.join(home, 'matplotlib'), 'MPLBACKEND': 'Agg',
           'WEWOS_ISOLATION': level}
    for k in ('LD_LIBRARY_PATH', 'ADS_ROOT', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def worker_args(rfd, wfd):
    args = [sys.executable, '-m', 'wewos.worker', '--rfd', str(rfd), '--wfd', str(wfd),
            '--filesize', str(FILE_LIMIT)]
    mem = memory_limit()
    if mem:
        args += ['--memory', str(mem)]
    return args


def command(level, internet, folder, rfd, wfd, grants=(), user_libraries=None):
    """(args, env, popen keywords) that start a worker reading the server's
    calls on rfd and answering on wfd."""
    if sys.platform == 'darwin':
        profile = macos_profile(level, internet, folder, grants, user_libraries)
        return ([SANDBOX_EXEC, '-p', profile] + worker_args(rfd, wfd),
                environment(level, folder), {'cwd': _real(folder), 'start_new_session': True})
    return bwrap_command(level, internet, folder, rfd, wfd, grants, user_libraries), None, {}


def bwrap_command(level, internet, folder, rfd, wfd, grants=(), user_libraries=None):
    """The bwrap command line of a worker (Linux)."""
    folder = _real(folder)
    args = ['bwrap', '--unshare-all']
    if internet:
        args.append('--share-net')
    args += ['--die-with-parent', '--new-session']
    # mounts in order: the system, then a private /proc, /dev and /tmp, then
    # what lies on top of them (an environment kept under /tmp stays visible)
    if level == 'readonly':
        args += ['--ro-bind', '/', '/']
    else:
        for d in ('/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64', '/libx32', '/etc'):
            if os.path.islink(d):
                args += ['--symlink', os.readlink(d), d]
            elif os.path.isdir(d):
                args += ['--ro-bind', d, d]
        if internet:
            # name resolution: /etc/resolv.conf points there on systemd systems
            args += ['--ro-bind-try', '/run/systemd/resolve', '/run/systemd/resolve']
    args += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    above = read_only_paths(user_libraries)
    if level == 'readonly':
        above = [p for p in above if _inside(p, ['/tmp', '/dev', '/proc'])]
    else:
        above += [_real(g) for g in grants or () if os.path.exists(_real(g))]
    for p in above:
        args += ['--ro-bind', p, p]
    args += ['--bind', folder, folder, '--chdir', folder]
    args.append('--clearenv')
    for k, v in sorted(environment(level, folder).items()):
        args += ['--setenv', k, v]
    return args + worker_args(rfd, wfd)


def _sb(path):
    """A path as a string of the sandbox profile language."""
    return '"%s"' % path.replace('\\', '\\\\').replace('"', '\\"')


def macos_profile(level, internet, folder, grants=(), user_libraries=None):
    """The sandbox-exec profile (SBPL) of a worker (macOS). Everything is denied
    but what Python needs to run, the files of the level, and the network when
    it is allowed. Paths are real paths: /tmp and /var are /private/... there."""
    folder = _real(folder)
    rules = [
        '(version 1)',
        '(deny default)',
        '(allow process-fork)',
        '(allow process-exec*)',                 # what it starts keeps this profile
        '(allow signal (target self))',
        '(allow sysctl-read)',
        '(allow file-read-metadata)',            # stat, so that paths resolve; not contents
        '(allow ipc-posix-shm*)',
        '(allow ipc-posix-sem*)',
        '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo")'
        ' (global-name "com.apple.system.notification_center")'
        ' (global-name "com.apple.system.logger")'
        ' (global-name "com.apple.CoreServices.coreservicesd")'
        ' (global-name "com.apple.fonts") (global-name "com.apple.FontObjectsServer"))',
        '(allow file-read* file-write-data file-ioctl (literal "/dev/null") (literal "/dev/zero")'
        ' (literal "/dev/dtracehelper") (literal "/dev/tty"))',
        '(allow file-read* (literal "/dev/random") (literal "/dev/urandom"))',
    ]
    if level == 'readonly':
        rules.append('(allow file-read*)')
    else:
        roots = [p for p in MACOS_SYSTEM if os.path.exists(p)] + read_only_paths(user_libraries) + \
                [_real(g) for g in grants or () if os.path.exists(_real(g))]
        seen = []
        for p in roots:
            p = _real(p)
            if p not in seen:
                seen.append(p)
        rules.append('(allow file-read*\n  %s)' % '\n  '.join('(subpath %s)' % _sb(p) for p in seen))
    rules.append('(allow file-read* file-write* (subpath %s))' % _sb(folder))
    if internet:
        rules += ['(allow system-socket)', '(allow network-outbound)',
                  '(allow mach-lookup (global-name "com.apple.dnssd.service")'
                  ' (global-name "com.apple.SystemConfiguration.configd")'
                  ' (global-name "com.apple.SystemConfiguration.DNSConfiguration")'
                  ' (global-name "com.apple.trustd") (global-name "com.apple.trustd.agent"))']
    return '\n'.join(rules) + '\n'


class _Launcher(object):
    """Starts the workers from one thread that lives as long as the server.

    bwrap --die-with-parent kills the sandbox when the *thread* that started
    it ends (PR_SET_PDEATHSIG), and the server answers each request on a
    thread of its own: a worker started there would die with its request."""

    def __init__(self):
        import queue
        self.jobs = queue.Queue()
        threading.Thread(target=self._loop, name='worker-launcher', daemon=True).start()

    def _loop(self):
        while True:
            fn, box, done = self.jobs.get()
            try:
                box['out'] = fn()
            except BaseException as e:                   # noqa: B902 - handed back
                box['error'] = e
            done.set()

    def run(self, fn):
        box, done = {}, threading.Event()
        self.jobs.put((fn, box, done))
        done.wait()
        if 'error' in box:
            raise box['error']
        return box['out']


_launcher = None
_launcher_lock = threading.Lock()


def launch(fn):
    global _launcher
    with _launcher_lock:
        if _launcher is None:
            _launcher = _Launcher()
    return _launcher.run(fn)


def _prepare_home(folder):
    """The worker's home: inside its folder. Matplotlib's font list is copied
    there, so the first plot does not rebuild it."""
    home = os.path.join(folder, '.wewos')
    mpl = os.path.join(home, 'matplotlib')
    if os.path.islink(home) or os.path.islink(mpl):
        return                       # planted by the network: leave it alone
    os.makedirs(mpl, exist_ok=True)
    os.makedirs(os.path.join(home, 'tmp'), exist_ok=True)     # TMPDIR on macOS
    src = os.environ.get('MPLCONFIGDIR') or os.path.expanduser('~/.cache/matplotlib')
    if not os.path.isdir(src):
        src = os.path.expanduser('~/.matplotlib')                 # macOS
    try:
        for f in os.listdir(src):
            if f.startswith('fontlist') and f.endswith('.json'):
                dst = os.path.join(mpl, f)
                if not os.path.lexists(dst):
                    shutil.copyfile(os.path.join(src, f), dst)
    except OSError:
        pass


class IsolatedSession(object):
    """A network run by a confined worker; has the Session methods the
    server calls."""

    def __init__(self, sid, folder, name, level, internet=False, grants=(),
                 startup=('Standard',), user_libraries=None, created=None, restore=False):
        import datetime
        self.id = sid
        self.folder = folder
        self.name = name
        self.created = created or datetime.datetime.now().isoformat(timespec='seconds')
        self.isolation = {'level': check_level(level), 'internet': bool(internet),
                          'grants': [_real(g) for g in grants or ()]}
        self.startup = list(startup)
        self.user_libraries = dict(user_libraries or {})
        self.proc = None
        self.chan = None
        self._lock = threading.Lock()
        self._start(restore)

    # ---- the worker process -----------------------------------------------------------
    def _start(self, restore):
        ok, why = available()
        if not ok:
            raise RuntimeError(why)
        first = not os.path.exists(os.path.join(self.folder, '.wewos'))
        if first:
            _prepare_home(self.folder)
        # two pipes: the server's calls go down one, the answers come up the other
        down_r, down_w = os.pipe()
        up_r, up_w = os.pipe()
        args, env, kw = command(self.isolation['level'], self.isolation['internet'], self.folder,
                                down_r, up_w, self.isolation['grants'], self.user_libraries)
        try:
            self.proc = launch(lambda: subprocess.Popen(
                args, pass_fds=(down_r, up_w), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, close_fds=True, env=env, **kw))
        finally:
            os.close(down_r)
            os.close(up_w)
        threading.Thread(target=self._output, args=(self.proc,), daemon=True).start()
        self.chan = Channel(Pipes(up_r, down_w), self._service)
        try:
            d = self._call('init', {
                'sid': self.id, 'folder': self.folder, 'name': self.name, 'created': self.created,
                'isolation': self.isolation, 'startup': self.startup,
                'user': self.user_libraries, 'restore': restore}, timeout=START_TIMEOUT)
        except Exception:
            self.kill()
            raise
        self.report = d.get('report') or []
        return d

    def _output(self, proc):
        """What the worker prints outside a node run goes to the server's log."""
        for line in iter(proc.stdout.readline, b''):
            text = line.decode('utf-8', 'replace').rstrip()[:500]
            print('[network %s] %s' % (self.id[:6], text), flush=True)

    def _service(self, name, a):
        """The calls the worker makes to the server."""
        if name == 'fetch_pdb':
            from . import fetch
            return base64.b64encode(fetch.download(a.get('id'))).decode('ascii')
        raise ValueError('the server offers no %r to networks' % name)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None and self.chan is not None \
            and self.chan.closed is None

    def kill(self):
        p = self.proc
        if p is not None and p.poll() is None:
            if sys.platform == 'darwin':
                try:
                    os.killpg(p.pid, signal.SIGKILL)     # the worker and what it started
                except OSError:
                    p.kill()
            else:
                p.kill()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                pass
        if self.chan is not None:
            self.chan.close()

    def restart(self):
        """Force stop: end the worker and start a new one from the autosave."""
        with self._lock:
            self.kill()
            self._start(restore=True)
        return {'execStatus': 'waiting', 'seq': 0, 'restarted': True}

    def _call(self, name, args=None, timeout=CALL_TIMEOUT):
        from .session import Refused
        try:
            return self.chan.call(name, args, timeout)
        except RemoteError as e:
            if e.kind == 'refused':
                raise Refused(e.message)
            if e.kind == 'value':
                raise ValueError(e.message)
            raise WorkerError(e.message, e.trace)
        except ChannelClosed:
            code = self.proc.poll() if self.proc is not None else None
            raise Refused('the sandbox of this network has stopped%s; Force stop restarts it '
                          'from its last autosave' % (' (exit code %s)' % code if code is not None
                                                      else ''))
        except TimeoutError:
            raise Refused('the network did not answer within %d s; Force stop restarts it '
                          'from its last autosave' % timeout)

    # ---- what the server calls -----------------------------------------------------------
    def info(self):
        try:
            return self._call('info', timeout=10)
        except Exception:
            return self._local()

    def _local(self):
        return {'session': self.id, 'name': self.name, 'folder': self.folder,
                'created': self.created, 'saved': None, 'isolation': dict(self.isolation)}

    def summary(self):
        try:
            return self._call('summary', timeout=10)
        except Exception:
            return dict(self._local(), nodes=0, status='stopped')

    def state(self):
        return self._call('state')

    def load(self, data):
        return self._call('load', {'data': data})

    def events(self, since, timeout=20.0):
        return self._call('events', {'since': since, 'timeout': timeout}, timeout=timeout + 15)

    def edit(self, op, body):
        return self._call('edit', {'op': op, 'body': body})

    def run(self, mode, node=None, net=None):
        if mode == 'kill':
            return self.restart()
        return self._call('run', {'mode': mode, 'node': node, 'net': net})

    def save(self, name=None):
        return self._call('save', {'name': name})

    def autosave(self):
        return self._call('autosave')

    def pick(self, body):
        return self._call('pick', {'body': body})

    def files(self, path):
        return self._call('files', {'path': path})

    def upload(self, name, data):
        out = None
        for offset in range(0, max(len(data), 1), UPLOAD_PIECE):
            piece = data[offset:offset + UPLOAD_PIECE]
            out = self._call('upload_part', {'name': name, 'offset': offset,
                                             'data': base64.b64encode(piece).decode('ascii')})
        return out
