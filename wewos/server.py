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
  POST api/example {name}       an example as a new network
  GET  api/download?s=&file=    a file of the session folder
  POST api/new {name}           a new empty network
  POST api/open?name=           a saved .wnet.json (raw body) as a new network
  POST api/import?name=         a Vision *_net.py (raw body) as a new network
  POST api/upload?s=&name=      a file (raw body) into the session's uploads/
  POST api/edit {s, op, ...}    an edit (add, connect, set_widget, ...)
  POST api/run {s, mode, node}  run, hardrun, run_node, stop, pause, resume
  POST api/save {s, name}       save the network in the session folder
  POST api/pick {s, node, ...}  a click in a 3D viewer
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

from . import APP, APP_LONG, __version__, env, page
from .session import Refused, Session, list_dir

MAX_BODY = 4 << 20
MAX_UPLOAD = 512 << 20

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'examples')
DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs')
STATIC_TYPES = {'.js': 'application/javascript', '.css': 'text/css', '.txt': 'text/plain',
                '.svg': 'image/svg+xml', '.png': 'image/png'}
DOC_TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.png': 'image/png'}


class App(object):
    def __init__(self, outdir):
        self.outdir = os.path.abspath(os.path.expanduser(outdir))
        os.makedirs(self.outdir, exist_ok=True)
        self.token = secrets.token_urlsafe(18)
        self.sessions = {}
        self._lock = threading.Lock()
        self.libconf_path = os.path.join(self.outdir, 'libraries.json')
        self.libconf = self._read_libconf()
        self._startup_libraries()

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
                'libraries': known()}

    def libraries(self):
        from .engine.library import catalog
        d = catalog()
        for k in d['known']:
            k['startup'] = k['name'] in self.libconf['startup']
        return d

    def load_library(self, body):
        """Load a library by name, or a module / .py file of the user's
        (remembered in libraries.json for the next sessions)."""
        from .engine import library
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

    def new(self, name='network'):
        sid = secrets.token_hex(8)
        s = Session(sid, self.outdir, name or 'network')
        with self._lock:
            self.sessions[sid] = s
        return s

    def new_state(self, name):
        return self.new(name).state()

    def open(self, name, raw):
        try:
            data = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise Refused('%s is not a network file (JSON)' % name)
        stem = os.path.basename(name or 'network').split('.')[0]
        s = self.new(data.get('network', {}).get('name') or stem)
        report = s.load(data)
        d = s.state()
        d['report'] = report
        return d

    def import_legacy(self, name, raw):
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
        s = self.new(stem)
        with open(os.path.join(s.folder, 'uploads', os.path.basename(name or 'net.py')),
                  'wb') as fh:
            fh.write(raw)
        load_report = s.load(data)
        d = s.state()
        d['report'] = report.as_dict()
        d['report']['load'] = load_report
        return d

    def examples(self):
        out = []
        for f in sorted(os.listdir(EXAMPLES)) if os.path.isdir(EXAMPLES) else []:
            if f.endswith('.wnet.json'):
                try:
                    with open(os.path.join(EXAMPLES, f)) as fh:
                        d = json.load(fh)
                    out.append({'file': f, 'name': d['network'].get('name') or f,
                                'nodes': len(d['network'].get('nodes', []))})
                except (OSError, ValueError, KeyError):
                    pass
        return {'examples': out}

    def example(self, name):
        """Open an example as a new network; its data files are copied to
        the network's folder (examples read data/... relative to it)."""
        import shutil
        names = {e['file'] for e in self.examples()['examples']}
        if name not in names:
            raise Refused('no example %r' % name)
        with open(os.path.join(EXAMPLES, name)) as fh:
            data = json.load(fh)
        s = self.new(data['network'].get('name') or name.split('.')[0])
        src = os.path.join(EXAMPLES, 'data')
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(s.folder, 'data'))
        report = s.load(data)
        d = s.state()
        d['report'] = report
        return d

    def list_sessions(self):
        with self._lock:
            ss = list(self.sessions.values())
        out = [dict(s.info(), nodes=len(s.net.nodes), status=s.net.execStatus) for s in ss]
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
                               'trace': traceback.format_exc()}, 500)

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
            return self._send(page.render(), 200, 'text/html')
        if u.path == '/api/status':
            return self._run(app.status)
        if u.path == '/api/libraries':
            return self._run(app.libraries)
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
            return self._run(lambda: list_dir(g('dir'), app.session(g('s')).folder))
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
        with open(full, 'rb') as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header('Content-Type', STATIC_TYPES[ext])
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
        try:
            s = app.session(sid)
            if not name:
                # the whole session folder as a zip
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                    for root, dirs, files in os.walk(s.folder):
                        for f in files:
                            p = os.path.join(root, f)
                            z.write(p, os.path.relpath(p, s.folder))
                return self._send(buf.getvalue(), 200, 'application/zip', headers=[
                    ('Content-Disposition', 'attachment; filename="%s.zip"'
                     % os.path.basename(s.folder))])
            path = s.file_path(name)
        except (Refused, ValueError) as e:
            return self._send({'error': str(e)}, 400)
        with open(path, 'rb') as fh:
            body = fh.read()
        ctype = 'application/json' if path.endswith('.json') else 'application/octet-stream'
        return self._send(body, 200, ctype, headers=[
            ('Content-Disposition', 'attachment; filename="%s"' % os.path.basename(path))])

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
        if u.path == '/api/open':
            return self._run(lambda: app.open(g('name'), self._raw(MAX_UPLOAD)))
        if u.path == '/api/import':
            return self._run(lambda: app.import_legacy(g('name'), self._raw(MAX_UPLOAD)))
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
            '/api/example': lambda: app.example(body.get('name')),
            '/api/library': lambda: app.load_library(body),
            '/api/library_startup': lambda: app.library_startup(body),
            '/api/edit': lambda: s().edit(body.get('op'), body),
            '/api/run': lambda: s().run(body.get('mode'), body.get('node'), body.get('net')),
            '/api/save': lambda: s().save(body.get('name')),
            '/api/pick': lambda: _pick(s(), body),
        }
        fn = routes.get(u.path)
        if fn is None:
            return self._send({'error': 'no such endpoint'}, 404)
        return self._run(fn)


def _pick(s, body):
    n = s.node(body.get('node'))
    if not hasattr(n, 'picked'):
        raise Refused('%s is not a viewer' % n.name)
    with s._edit_context():
        n.picked(body)
    return {'seq': s.net.bus.seq}


def clean_base_path(base):
    base = (base or '').strip().strip('/')
    if not base:
        return ''
    if not all(part and part not in ('.', '..') for part in base.split('/')):
        raise ValueError('bad base path %r' % base)
    return '/' + base


def build(host='127.0.0.1', port=8767, outdir='~/wewos_runs', base_path=''):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.app = App(outdir)
    httpd.base_path = clean_base_path(base_path)
    return httpd


def serve(host='127.0.0.1', port=8767, outdir='~/wewos_runs', base_path=''):
    httpd = build(host, port, outdir, base_path)
    bound = httpd.server_address[1]
    url = 'http://%s:%d%s/?t=%s' % (host, bound, httpd.base_path, httpd.app.token)
    print('%s %s (%s) is at\n\n    %s\n' % (APP, __version__, APP_LONG, url), flush=True)
    print('networks are kept in %s' % httpd.app.outdir, flush=True)
    miss = env.check()
    if miss:
        print('\nmissing (some libraries will not load): %s' % '; '.join(miss), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n%s stopped' % APP)
