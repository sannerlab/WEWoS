# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The process that holds one isolated network (see wewos/isolation.py).

    python -m wewos.worker --rfd R --wfd W

It is started by the server inside a sandbox (bubblewrap on Linux,
sandbox-exec on macOS), reads the server's calls on the pipe R and answers on
the pipe W (wewos/ipc.py), with an ordinary Session: the
network, its runs and its events live here, and the server only passes the
page's requests on. Its limits (memory, file size) are set before any code of
the network runs, and cannot be raised again from inside.
"""
import argparse
import base64
import json
import os
import sys

try:
    import resource              # not on Windows: the Job object limits the worker there
except ImportError:
    resource = None
import threading

SESSION = None
CHANNEL = None
_ready = threading.Event()

# the Session methods the server may call, and how
METHODS = {
    'state': lambda s, a: s.state(),
    'info': lambda s, a: s.info(),
    'summary': lambda s, a: s.summary(),
    'load': lambda s, a: s.load(a['data']),
    'events': lambda s, a: s.events(a.get('since', 0), float(a.get('timeout', 20))),
    'edit': lambda s, a: s.edit(a.get('op'), a.get('body') or {}),
    'run': lambda s, a: s.run(a.get('mode'), a.get('node'), a.get('net')),
    'save': lambda s, a: s.save(a.get('name')),
    'pick': lambda s, a: s.pick(a.get('body') or {}),
    'files': lambda s, a: s.files(a.get('path')),
    'autosave': lambda s, a: s.autosave() or {},
}


def limit(memory, filesize):
    """Lower both the soft and the hard limits: the network cannot raise them.
    A limit the system does not take (macOS and the address space) is skipped."""
    if resource is None:
        return
    for res, value in ((resource.RLIMIT_AS, memory), (resource.RLIMIT_FSIZE, filesize),
                       (resource.RLIMIT_CORE, 0)):
        if value is None:
            continue
        try:
            soft, hard = resource.getrlimit(res)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            resource.setrlimit(res, (value, value))
        except (ValueError, OSError):
            pass


def watch_parent():
    """End when the server ends. Its pipe closing ends the worker already; this
    also covers a server killed while the worker's main thread is busy."""
    import time
    first = os.getppid()
    while True:
        time.sleep(2)
        if os.getppid() != first:
            os._exit(0)


def init(a):
    """Build the session: the server's libraries, then the network's folder;
    a restarted worker reloads the network from its autosave."""
    global SESSION
    from wewos.engine import library
    library.USER.update(a.get('user') or {})
    for name in ['Standard'] + [n for n in a.get('startup') or [] if n != 'Standard']:
        try:
            library.get_library(name)
        except Exception as e:
            print('library %s did not load: %s' % (name, e), flush=True)
    from wewos import fetch
    if not a['isolation'].get('internet'):
        fetch.remote = lambda code: base64.b64decode(
            CHANNEL.call('fetch_pdb', {'id': code}, timeout=fetch.TIMEOUT + 15))
    from wewos.session import Session
    s = Session(a['sid'], os.path.dirname(a['folder']), a.get('name') or 'network',
                folder=a['folder'])
    s.created = a.get('created') or s.created
    s.isolation = dict(a['isolation'])
    report = []
    if a.get('restore'):
        path = os.path.join(s.folder, 'autosave.wnet.json')
        if os.path.isfile(path):
            with open(path) as fh:
                data = json.load(fh)
            report = s.load(data)
            s.net.emit('log', text='the network was restarted from its last autosave\n')
    SESSION = s
    _ready.set()
    return dict(s.info(), report=report)


def upload_part(a):
    """A piece of an uploaded file, written in uploads/ (the server sends a
    large file in pieces)."""
    from wewos.session import _safe
    name = _safe(os.path.basename(a.get('name') or 'upload'), 'upload')
    path = os.path.join(SESSION.folder, 'uploads', name)
    with open(path, 'wb' if not a.get('offset') else 'ab') as fh:
        fh.write(base64.b64decode(a.get('data') or ''))
    return {'path': path, 'name': name, 'size': os.path.getsize(path)}


def handle(name, a):
    if name == 'init':
        return init(a)
    if name == 'ping':
        return {'pid': os.getpid()}
    if not _ready.wait(600):
        raise RuntimeError('the network was not set up')
    if name == 'upload_part':
        return upload_part(a)
    fn = METHODS.get(name)
    if fn is None:
        from wewos.session import Refused
        raise Refused('unknown call %r' % name)
    return fn(SESSION, a)


def main(argv=None):
    global CHANNEL
    p = argparse.ArgumentParser(prog='wewos.worker')
    p.add_argument('--rfd', type=int, required=True, help='pipe of the server\'s calls')
    p.add_argument('--wfd', type=int, required=True, help='pipe of the answers')
    p.add_argument('--memory', type=int, default=None, help='address space limit, bytes')
    p.add_argument('--filesize', type=int, default=None, help='largest file, bytes')
    a = p.parse_args(argv)
    limit(a.memory, a.filesize)
    from wewos.ipc import Channel, Pipes
    done = threading.Event()
    threading.Thread(target=watch_parent, daemon=True).start()
    rfd, wfd = a.rfd, a.wfd
    if os.name == 'nt':                      # Windows: the server passed the pipes' handles
        import msvcrt
        rfd, wfd = msvcrt.open_osfhandle(rfd, os.O_RDONLY), msvcrt.open_osfhandle(wfd, 0)
    CHANNEL = Channel(Pipes(rfd, wfd), handle, on_close=lambda reason: done.set())
    done.wait()
    os._exit(0)              # run threads of the network end with the process


if __name__ == '__main__':
    sys.exit(main())
