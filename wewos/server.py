# Author: Michel Sanner, PhD. Copyright (c) 2026. Server pattern adapted from ADapt and
# ADCP_docking (BSD 3-Clause); see THIRD_PARTY_NOTICES.md.
"""The web server: standard library only, bound to localhost, a random token
in the URL, JSON under /api/*, bundled static files.

Node code runs in this process with the user's rights, as it did in Vision;
the token keeps other users of the machine out, and nothing is reachable from
other machines unless --host says so (use an SSH tunnel instead).

Routes
  GET  /                        the page
  GET  api/status               version, environment, libraries that failed to load
  GET  api/libraries            loaded libraries (palette), all known ones, types, widgets
  POST api/library {name | module | file}   load a library (a user module or file)
  POST api/library_startup {name, on}       load it when the server starts
  GET  api/sessions             open networks
  GET  api/session?s=           one network, in full
  GET  api/events?s=&since=N    events after N (long poll, up to 25 s)
  GET  api/files?s=&dir=        a folder listing for file widgets
  GET  api/examples             the example networks
  POST api/example {name, level?, internet?, grants?}   an example as a new network
  GET  api/download?s=&file=    a file of the session folder
  POST api/new {name}           a new empty network
  POST api/open?name=           a saved .wnet.json (raw body) as a new network
  POST api/import?name=         a Vision *_net.py (raw body) as a new network
  POST api/upload?s=&name=      a file (raw body) into the session's uploads/
  POST api/edit {s, op, ...}    an edit (add, connect, set_widget, ...)
  POST api/run {s, mode, node}  run, hardrun, run_node, stop, pause, resume
  POST api/save {s, name}       save the network in the session folder
  POST api/pick {s, node, ...}  a click in a 3D viewer
  GET  api/settings             the isolation preferences, and whether isolation works here
  POST api/settings {open_level, internet}   remember them (settings.json)
  POST api/isolation {s, level, internet, grants}   reopen a network at another level

api/open and api/import take level=sandboxed|readonly|unrestricted, internet=0|1 and
grant=<folder> (repeated) in the query: a network from someone else runs in its own
confined process (wewos/isolation.py). api/run mode=kill (Force stop) restarts such a
network from its last autosave.
"""
import io
import json
import os
import secrets
import threading
import traceback
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import APP, APP_LONG, __version__, env, isolation, page
from .session import Refused, Session, make_folder, open_in_folder

MAX_BODY = 4 << 20
MAX_UPLOAD = 512 << 20

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'examples')
# titles of the example folders (examples/<folder>/)
EXAMPLE_GROUPS = {'tutorial': 'Vision tutorial (MGLTools 1.5.3)',
                  'vision': 'Vision examples (MGLTools)',
                  'vision_matplotlib': 'Vision matplotlib examples (MGLTools)'}
DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs')
STATIC_TYPES = {'.js': 'application/javascript', '.css': 'text/css', '.txt': 'text/plain',
                '.json': 'application/json',
                '.svg': 'image/svg+xml', '.png': 'image/png'}
DOC_TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.png': 'image/png'}


class App(object):
    def __init__(self, outdir, minimum='unrestricted'):
        self.outdir = os.path.abspath(os.path.expanduser(outdir))
        os.makedirs(self.outdir, exist_ok=True)
        self.token = secrets.token_urlsafe(18)
        self.sessions = {}
        self._lock = threading.Lock()
        # the least isolation any network gets (wewos serve --isolation)
        self.minimum = isolation.check_level(minimum)
        if self.minimum != 'unrestricted' and not isolation.available()[0]:
            raise RuntimeError(isolation.available()[1])
        self.libconf_path = os.path.join(self.outdir, 'libraries.json')
        self.libconf = self._read_libconf()
        self.settings_path = os.path.join(self.outdir, 'settings.json')
        self.settings = self._read_settings()
        self._startup_libraries()
        self._nodeinfo = {}            # (library, label) -> node_info()

    # ---- isolation preferences (settings.json) -----------------------------------------
    def _read_settings(self):
        try:
            with open(self.settings_path) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            d = {}
        if d.get('open_level') not in isolation.LEVELS:
            d['open_level'] = 'sandboxed'          # files from others: isolated by default
        d['internet'] = bool(d.get('internet', False))
        return d

    def get_settings(self):
        ok, why = isolation.available()
        return dict(self.settings, available=ok, reason=why, minimum=self.minimum,
                    levels=isolation.LABELS)

    def set_settings(self, body):
        if 'open_level' in body:
            self.settings['open_level'] = isolation.check_level(body['open_level'])
        if 'internet' in body:
            self.settings['internet'] = bool(body['internet'])
        tmp = self.settings_path + '.part'
        with open(tmp, 'w') as fh:
            json.dump(self.settings, fh, indent=1)
        os.replace(tmp, self.settings_path)
        return self.get_settings()

    def _level(self, level):
        """The level a network will run at: the one asked for (default: the
        preference for opened files), never below the server's minimum."""
        level = isolation.stricter(isolation.check_level(level or 'unrestricted'), self.minimum)
        if level != 'unrestricted':
            ok, why = isolation.available()
            if not ok:
                raise Refused(why)
        return level

    @staticmethod
    def _grants(grants):
        out = []
        for g in grants or ():
            g = os.path.abspath(os.path.expanduser(g))
            if not os.path.isdir(g):
                raise Refused('cannot grant %s: no such folder' % g)
            out.append(g)
        return out

    # ---- libraries: loaded on demand, as in Vision ---------------------------------------
    def _read_libconf(self):
        try:
            with open(self.libconf_path) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            d = {}
        d.setdefault('startup', ['Standard'])
        d.setdefault('user', {})
        return d

    def _write_libconf(self):
        tmp = self.libconf_path + '.part'
        with open(tmp, 'w') as fh:
            json.dump(self.libconf, fh, indent=1)
        os.replace(tmp, self.libconf_path)

    def _startup_libraries(self):
        from .engine import library
        library.USER.update(self.libconf['user'])
        for name in ['Standard'] + [n for n in self.libconf['startup'] if n != 'Standard']:
            try:
                library.get_library(name)
            except Exception as e:
                print('library %s did not load: %s' % (name, e), flush=True)

    def status(self):
        from .engine.library import known
        return {'version': __version__, 'app': APP, 'outdir': self.outdir,
                'missing': env.check(), 'environment': env.provenance(),
                'libraries': known(), 'isolation': self.get_settings()}

    def libraries(self):
        from .engine.library import catalog
        d = catalog()
        for k in d['known']:
            k['startup'] = k['name'] in self.libconf['startup']
        return d

    def node_info(self, lib, label):
        """How a palette node looks before it is added (its label, color and
        ports, with the widgets shown in the node): the page draws it while
        it is dragged from the library to the network."""
        key = (lib, label)
        d = self._nodeinfo.get(key)
        if d is None:
            from .engine.library import get_library
            from .engine.network import Network
            net = Network('palette')            # a node gets its ports in a network
            net.runOnNewData.value = False
            try:
                node = get_library(lib).instantiate(label=label)
                net.addNode(node, 0, 0)
            except Exception as e:
                raise Refused('no node %r in %s: %s: %s' % (label, lib, type(e).__name__, e))
            d = node.describe()
            try:
                net.deleteNodes([node])
            except Exception:
                pass
            for k in ('id', 'pos', 'status', 'doc'):
                d.pop(k, None)
            d['label'] = d.get('label') or label
            self._nodeinfo[key] = d
        return d

    def load_library(self, body):
        """Load a library by name, or a module / .py file of the user's
        (remembered in libraries.json for the next sessions)."""
        from .engine import library
        self._nodeinfo.clear()
        if (body.get('module') or body.get('file')) and self.minimum != 'unrestricted':
            raise Refused('this server isolates every network (--isolation %s): it does not '
                          'load Python modules or files into itself' % self.minimum)
        if body.get('module') or body.get('file'):
            src = {k: body[k].strip() for k in ('module', 'file') if body.get(k)}
            try:
                libs = library.load_user(**src)
            except Exception as e:
                raise Refused('could not load %s: %s: %s'
                              % (src.get('file') or src.get('module'), type(e).__name__, e))
            for lib in libs:
                self.libconf['user'][lib.name] = src
            self._write_libconf()
        else:
            try:
                library.get_library(body.get('name') or '')
            except Exception as e:
                raise Refused('could not load library %s: %s: %s'
                              % (body.get('name'), type(e).__name__, e))
        return self.libraries()

    def library_startup(self, body):
        name, on = body.get('name'), bool(body.get('on'))
        st = [n for n in self.libconf['startup'] if n != name]
        if on:
            st.append(name)
        self.libconf['startup'] = st
        self._write_libconf()
        return self.libraries()

    def new(self, name='network', level='unrestricted', internet=False, grants=(), prepare=None):
        """A new network: in this process, or isolated in a worker. prepare(folder)
        puts files in its folder before any of its code can run."""
        level = self._level(level)
        grants = self._grants(grants) if level == 'sandboxed' else []
        sid = secrets.token_hex(8)
        name = name or 'network'
        folder = make_folder(self.outdir, name, sid)
        if prepare is not None:
            prepare(folder)
        if level == 'unrestricted':
            s = Session(sid, self.outdir, name, folder=folder)
        else:
            s = isolation.IsolatedSession(sid, folder, name, level, internet, grants,
                                          startup=self.libconf['startup'],
                                          user_libraries=self.libconf['user'])
        with self._lock:
            self.sessions[sid] = s
        return s

    def new_state(self, name):
        return self.new(name, self.minimum).state()

    def open(self, name, raw, level=None, internet=None, grants=()):
        try:
            data = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise Refused('%s is not a network file (JSON)' % name)
        if not isinstance(data, dict):
            raise Refused('%s is not a network file' % name)
        stem = os.path.basename(name or 'network').split('.')[0]
        s = self.new(data.get('network', {}).get('name') or stem,
                     level or self.settings['open_level'],
                     self.settings['internet'] if internet is None else internet, grants)
        report = s.load(data)
        d = s.state()
        d['report'] = report
        return d

    def set_isolation(self, sid, level, internet=False, grants=()):
        """Reopen an open network at another isolation level, from its autosave."""
        old = self.session(sid)
        level = self._level(level)
        grants = self._grants(grants) if level == 'sandboxed' else []
        info = old.info()
        try:
            old.autosave()
        except Exception:
            pass                     # a stopped worker: its last autosave is on disk
        if isinstance(old, isolation.IsolatedSession):
            old.kill()
        else:
            try:
                old.net.stop()
            except Exception:
                pass
        if level == 'unrestricted':
            s = Session(sid, self.outdir, info['name'], folder=old.folder)
            try:
                with open_in_folder(old.folder, 'autosave.wnet.json') as fh:
                    data = json.loads(fh.read().decode('utf-8'))
            except (Refused, ValueError):
                data = None
            report = s.load(data) if data else ['no autosave: the network starts empty']
        else:
            s = isolation.IsolatedSession(sid, old.folder, info['name'], level, internet, grants,
                                          startup=self.libconf['startup'],
                                          user_libraries=self.libconf['user'],
                                          created=info.get('created'), restore=True)
            report = s.report
        s.created = info.get('created') or s.created
        with self._lock:
            self.sessions[sid] = s
        d = s.state()
        d['report'] = report
        return d

    def import_legacy(self, name, raw, level=None, internet=None, grants=()):
        from .legacy import importer
        try:
            src = raw.decode('utf-8')
        except UnicodeDecodeError:
            src = raw.decode('latin-1')
        data, report = importer.import_source(src, name)
        stem = os.path.basename(name or 'network')
        for suffix in ('_net.py', '.py'):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        def keep_original(folder):
            with open(os.path.join(folder, 'uploads', os.path.basename(name or 'net.py')),
                      'wb') as fh:
                fh.write(raw)
        s = self.new(stem, level or self.settings['open_level'],
                     self.settings['internet'] if internet is None else internet, grants,
                     prepare=keep_original)
        load_report = s.load(data)
        d = s.state()
        d['report'] = report.as_dict()
        d['report']['load'] = load_report
        return d

    def examples(self):
        """The example networks: examples/*.wnet.json, then one group per
        sub-folder holding networks (examples/vision/...)."""
        out = []
        if not os.path.isdir(EXAMPLES):
            return {'examples': out}
        groups = [('', 'WEWoS')] + [
            (d, EXAMPLE_GROUPS.get(d, d)) for d in sorted(os.listdir(EXAMPLES))
            if os.path.isdir(os.path.join(EXAMPLES, d)) and d != 'data'
            and any(f.endswith('.wnet.json') for f in os.listdir(os.path.join(EXAMPLES, d)))]
        for sub, title in groups:
            folder = os.path.join(EXAMPLES, sub)
            for f in sorted(os.listdir(folder), key=str.lower):
                if f.endswith('.wnet.json'):
                    try:
                        with open(os.path.join(folder, f)) as fh:
                            d = json.load(fh)
                        out.append({'file': sub + '/' + f if sub else f, 'group': title,
                                    'name': d['network'].get('name') or f,
                                    'nodes': len(d['network'].get('nodes', []))})
                    except (OSError, ValueError, KeyError):
                        pass
        return {'examples': out}

    def example(self, name, level=None, internet=None, grants=()):
        """Open an example as a new network; its data files are copied to
        the network's folder (examples read data/... relative to it). It runs
        at the level asked for; unrestricted when none is given (the examples
        come with WEWoS), never below the server's minimum."""
        import shutil
        names = {e['file'] for e in self.examples()['examples']}
        if name not in names:
            raise Refused('no example %r' % name)
        with open(os.path.join(EXAMPLES, name)) as fh:
            data = json.load(fh)
        sub = os.path.dirname(name)

        def copy_data(dest):
            if not sub:
                src = os.path.join(EXAMPLES, 'data')
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(dest, 'data'))
            else:
                # a group's examples read the files next to them (cv.pdb, Data/...)
                folder = os.path.join(EXAMPLES, sub)
                for f in os.listdir(folder):
                    p = os.path.join(folder, f)
                    if f.endswith('.wnet.json'):
                        continue
                    if os.path.isdir(p):
                        shutil.copytree(p, os.path.join(dest, f))
                    else:
                        shutil.copy(p, os.path.join(dest, f))
        s = self.new(data['network'].get('name') or os.path.basename(name).split('.')[0],
                     level or self.minimum,
                     self.settings['internet'] if internet is None else internet, grants,
                     prepare=copy_data)
        report = s.load(data)
        d = s.state()
        d['report'] = report
        return d

    def list_sessions(self):
        with self._lock:
            ss = list(self.sessions.values())
        out = [s.summary() for s in ss]
        return {'sessions': sorted(out, key=lambda d: d['created'], reverse=True)}

    def session(self, sid):
        s = self.sessions.get(sid or '')
        if s is None:
            raise Refused('no such network; it was closed or the server restarted')
        return s


class Handler(BaseHTTPRequestHandler):
    server_version = '%s/%s' % (APP, __version__)
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    # ---- plumbing --------------------------------------------------------------------
    def _send(self, obj, code=200, ctype='application/json', headers=()):
        body = (obj if isinstance(obj, bytes)
                else json.dumps(obj).encode() if ctype == 'application/json'
                else obj.encode())
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if not isinstance(obj, bytes) else ''))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _auth(self, q):
        return secrets.compare_digest(
            q.get('t', [''])[0] or self.headers.get('X-Token', ''), self.server.app.token)

    def _raw(self, limit):
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return b''
        if n > limit:
            raise Refused('the request is larger than %d MB' % (limit >> 20))
        return self.rfile.read(n)

    def _json(self):
        raw = self._raw(MAX_BODY)
        try:
            return json.loads(raw.decode()) if raw else {}
        except ValueError:
            raise Refused('the request body is not JSON')

    def _run(self, fn):
        try:
            return self._send(fn())
        except Refused as e:
            return self._send({'error': str(e)}, 400)
        except ValueError as e:
            return self._send({'error': str(e)}, 400)
        except Exception as e:
            return self._send({'error': '%s: %s' % (type(e).__name__, e),
                               'trace': getattr(e, 'remote_trace', None) or traceback.format_exc()},
                              500)

    def _url(self):
        u = urllib.parse.urlparse(self.path)
        base = getattr(self.server, 'base_path', '')
        if base:
            if u.path == base:
                loc = base + '/' + ('?' + u.query if u.query else '')
                self.send_response(301)
                self.send_header('Location', loc)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return None
            if u.path.startswith(base + '/'):
                u = u._replace(path=u.path[len(base):])
        return u

    # ---- GET -------------------------------------------------------------------------
    def do_GET(self):
        u = self._url()
        if u is None:
            return
        q = urllib.parse.parse_qs(u.query)
        app = self.server.app
        if u.path.startswith('/static/'):
            return self._static(u.path)
        if u.path == '/docs' or u.path.startswith('/docs/'):
            return self._docs(u.path)
        if not self._auth(q):
            if u.path == '/':
                return self._send('open the URL this tool printed; it carries the token',
                                  403, 'text/plain')
            return self._send({'error': 'bad or missing token'}, 403)
        g = lambda k, d=None: q.get(k, [d])[0]
        if u.path == '/':
            nonce = secrets.token_urlsafe(16)
            return self._send(page.render(nonce), 200, 'text/html', headers=[
                ('Content-Security-Policy', page.csp(nonce)),
                ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY')])
        if u.path == '/api/status':
            return self._run(app.status)
        if u.path == '/api/libraries':
            return self._run(app.libraries)
        if u.path == '/api/nodeinfo':
            return self._run(lambda: app.node_info(g('lib'), g('label')))
        if u.path == '/api/sessions':
            return self._run(app.list_sessions)
        if u.path == '/api/session':
            return self._run(lambda: app.session(g('s')).state())
        if u.path == '/api/events':
            timeout = min(float(g('timeout', '25') or 25), 25.0)
            return self._run(lambda: app.session(g('s')).events(g('since', '0'), timeout))
        if u.path == '/api/examples':
            return self._run(app.examples)
        if u.path == '/api/files':
            return self._run(lambda: app.session(g('s')).files(g('dir')))
        if u.path == '/api/settings':
            return self._run(app.get_settings)
        if u.path == '/api/download':
            return self._download(app, g('s'), g('file'))
        return self._send({'error': 'no such endpoint'}, 404)

    def _static(self, path):
        name = os.path.basename(path)
        full = os.path.join(STATIC, name)
        ext = os.path.splitext(name)[1]
        if os.path.dirname(os.path.abspath(full)) != os.path.abspath(STATIC) \
                or not os.path.isfile(full) or ext not in STATIC_TYPES:
            return self._send({'error': 'no such file'}, 404)
        # a precompressed copy (molstar.js.gz) when the browser takes gzip
        gz = full + '.gz'
        zipped = 'gzip' in (self.headers.get('Accept-Encoding') or '') and os.path.isfile(gz)
        with open(gz if zipped else full, 'rb') as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header('Content-Type', STATIC_TYPES[ext])
        if zipped:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Vary', 'Accept-Encoding')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers()
        self.wfile.write(body)

    def _docs(self, path):
        rel = path[len('/docs'):].lstrip('/') or 'index.html'
        parts = rel.split('/')
        ok = (len(parts) == 1 and parts[0].endswith(('.html', '.css'))) or \
             (len(parts) == 2 and parts[0] == 'img' and parts[1].endswith('.png'))
        full = os.path.abspath(os.path.join(DOCS, *parts))
        if not ok or not full.startswith(os.path.abspath(DOCS) + os.sep) \
                or '..' in parts or not os.path.isfile(full):
            return self._send({'error': 'no such page'}, 404)
        with open(full, 'rb') as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header('Content-Type', DOC_TYPES[os.path.splitext(full)[1]])
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=600')
        self.end_headers()
        self.wfile.write(body)

    def _download(self, app, sid, name):
        """A file of a network's folder, or the whole folder as a zip. Symbolic
        links are never followed: an isolated network may have planted them."""
        try:
            s = app.session(sid)
            if not name:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                    for root, dirs, files in os.walk(s.folder):
                        dirs[:] = [d for d in dirs if d != '.wewos']   # the worker's home
                        for f in files:
                            rel = os.path.relpath(os.path.join(root, f), s.folder)
                            try:
                                with open_in_folder(s.folder, rel) as fh:
                                    z.writestr(rel, fh.read())
                            except Refused:
                                continue                 # a link, or not a regular file
                return self._send(buf.getvalue(), 200, 'application/zip', headers=[
                    ('Content-Disposition', 'attachment; filename="%s.zip"'
                     % os.path.basename(s.folder))])
            with open_in_folder(s.folder, name) as fh:
                body = fh.read()
        except (Refused, ValueError) as e:
            return self._send({'error': str(e)}, 400)
        ctype = 'application/json' if name.endswith('.json') else 'application/octet-stream'
        return self._send(body, 200, ctype, headers=[
            ('Content-Disposition', 'attachment; filename="%s"' % os.path.basename(name))])

    # ---- POST ------------------------------------------------------------------------
    def do_POST(self):
        u = self._url()
        if u is None:
            return
        q = urllib.parse.parse_qs(u.query)
        if not self._auth(q):
            return self._send({'error': 'bad or missing token'}, 403)
        app = self.server.app
        g = lambda k, d='': q.get(k, [d])[0]
        iso = lambda: dict(level=g('level') or None,
                           internet=None if g('internet') == '' else g('internet') in ('1', 'true'),
                           grants=q.get('grant', []))
        if u.path == '/api/open':
            return self._run(lambda: app.open(g('name'), self._raw(MAX_UPLOAD), **iso()))
        if u.path == '/api/import':
            return self._run(lambda: app.import_legacy(g('name'), self._raw(MAX_UPLOAD), **iso()))
        if u.path == '/api/upload':
            return self._run(lambda: app.session(g('s')).upload(g('name'),
                                                                 self._raw(MAX_UPLOAD)))
        try:
            body = self._json()
        except Refused as e:
            return self._send({'error': str(e)}, 400)
        s = lambda: app.session(body.get('s'))
        routes = {
            '/api/new': lambda: app.new_state(body.get('name')),
            '/api/example': lambda: app.example(body.get('name'), body.get('level'),
                                                body.get('internet'), body.get('grants') or ()),
            '/api/library': lambda: app.load_library(body),
            '/api/library_startup': lambda: app.library_startup(body),
            '/api/edit': lambda: s().edit(body.get('op'), body),
            '/api/run': lambda: s().run(body.get('mode'), body.get('node'), body.get('net')),
            '/api/save': lambda: s().save(body.get('name')),
            '/api/pick': lambda: s().pick(body),
            '/api/settings': lambda: app.set_settings(body),
            '/api/isolation': lambda: app.set_isolation(body.get('s'), body.get('level'),
                                                        bool(body.get('internet')),
                                                        body.get('grants') or ()),
        }
        fn = routes.get(u.path)
        if fn is None:
            return self._send({'error': 'no such endpoint'}, 404)
        return self._run(fn)


def clean_base_path(base):
    base = (base or '').strip().strip('/')
    if not base:
        return ''
    if not all(part and part not in ('.', '..') for part in base.split('/')):
        raise ValueError('bad base path %r' % base)
    return '/' + base


def build(host='127.0.0.1', port=8767, outdir='~/wewos_runs', base_path='',
          minimum='unrestricted'):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.app = App(outdir, minimum)
    httpd.base_path = clean_base_path(base_path)
    return httpd


def serve(host='127.0.0.1', port=8767, outdir='~/wewos_runs', base_path='',
          minimum='unrestricted'):
    httpd = build(host, port, outdir, base_path, minimum)
    bound = httpd.server_address[1]
    url = 'http://%s:%d%s/?t=%s' % (host, bound, httpd.base_path, httpd.app.token)
    print('%s %s (%s) is at\n\n    %s\n' % (APP, __version__, APP_LONG, url), flush=True)
    print('networks are kept in %s' % httpd.app.outdir, flush=True)
    ok, why = isolation.available()
    print('networks from others: %s' % (
        'every network is isolated (%s)' % minimum if minimum != 'unrestricted'
        else 'isolated when opened (bubblewrap)' if ok else 'cannot be isolated: %s' % why),
        flush=True)
    miss = env.check()
    if miss:
        print('\nmissing (some libraries will not load): %s' % '; '.join(miss), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n%s stopped' % APP)
