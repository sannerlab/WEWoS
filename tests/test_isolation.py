# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Networks from other people, run in a confined worker (wewos/isolation.py).

A canary folder in the home directory stands for the user's files: a
sandboxed network must not see it, a read-only one may read it but not write
it, and neither may reach the network unless allowed. Code that runs when a
network is opened must run inside the sandbox too.
"""
import json
import os
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
import zipfile
import io

from common import ROOT, Skip, check, eq, outdir

from wewos import isolation
from wewos.engine.events import EventBus


def _need_bwrap():
    ok, why = isolation.available()
    if not ok:
        raise Skip(why)


def _app(name, minimum='unrestricted'):
    from wewos.server import App
    return App(outdir('iso_' + name), minimum)


def _close(app):
    for s in list(app.sessions.values()):
        if isinstance(s, isolation.IsolatedSession):
            s.kill()


class Canary(object):
    """A folder of the user's (in the home directory, outside every sandbox bind)."""

    def __enter__(self):
        self.path = os.path.join(os.path.expanduser('~'), '.wewos_test_canary_%d' % os.getpid())
        os.makedirs(self.path, exist_ok=True)
        with open(os.path.join(self.path, 'secret.txt'), 'w') as fh:
            fh.write('secret')
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.path, ignore_errors=True)


def _generic(s, code):
    """A Generic node with this compute function; returns its id."""
    from wewos.session import Refused
    nid = s.edit('add', {'lib': 'Standard', 'label': 'Generic', 'pos': [40, 40]})['node']['id']
    for _ in range(100):                 # a new node runs once: wait for that run to end
        try:
            s.edit('set_code', {'node': nid, 'code': code})
            return nid
        except Refused:
            time.sleep(0.1)
    raise AssertionError('the new node did not finish its first run')


def _wait_file(path, seconds=90):
    t = time.time() + seconds
    while time.time() < t:
        if os.path.isfile(path) and os.path.getsize(path):
            time.sleep(0.1)
            return
        time.sleep(0.1)
    raise AssertionError('%s did not appear' % path)


def _wait_idle(s, seconds=120):
    time.sleep(0.3)
    t = time.time() + seconds
    while time.time() < t:
        if s.summary()['status'] == 'waiting':
            return
        time.sleep(0.2)
    raise AssertionError('the network did not finish')


PROBE = '''def doit(self):
    import json, os, socket
    r = {}
    try:
        r['read'] = open(%(canary)r + '/secret.txt').read()
    except Exception as e:
        r['read'] = 'ERR ' + type(e).__name__
    try:
        open(%(canary)r + '/written.txt', 'w').write('x')
        r['write'] = 'ok'
    except Exception as e:
        r['write'] = 'ERR ' + type(e).__name__
    try:
        socket.create_connection(('127.0.0.1', %(port)d), timeout=3).close()
        r['net'] = 'ok'
    except Exception as e:
        r['net'] = 'ERR ' + type(e).__name__
    r['home'] = os.path.expanduser('~')
    open('probe.json', 'w').write(json.dumps(r))
'''


def test_levels_confine_files_and_network():
    _need_bwrap()
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    app = _app('levels')
    results = {}
    try:
        with Canary() as c:
            for level, internet in (('sandboxed', False), ('readonly', False),
                                    ('readonly', True), ('unrestricted', True)):
                s = app.new('probe', level, internet)
                nid = _generic(s, PROBE % {'canary': c.path, 'port': port})
                s.run('run_node', nid)
                _wait_file(os.path.join(s.folder, 'probe.json'))
                with open(os.path.join(s.folder, 'probe.json')) as fh:
                    results[(level, internet)] = json.load(fh)
                if os.path.exists(os.path.join(c.path, 'written.txt')):
                    os.remove(os.path.join(c.path, 'written.txt'))
    finally:
        _close(app)
        srv.close()
    sb, ro, ron, un = (results[k] for k in (('sandboxed', False), ('readonly', False),
                                            ('readonly', True), ('unrestricted', True)))
    check(sb['read'].startswith('ERR') and sb['write'].startswith('ERR')
          and sb['net'].startswith('ERR'), sb)
    check(ro['read'] == 'secret' and ro['write'].startswith('ERR')
          and ro['net'].startswith('ERR'), ro)
    check(ron['read'] == 'secret' and ron['write'].startswith('ERR') and ron['net'] == 'ok', ron)
    check(un['read'] == 'secret' and un['write'] == 'ok' and un['net'] == 'ok', un)
    check(sb['home'].endswith('/.wewos'), sb)


def test_code_run_at_open_stays_in_the_sandbox():
    """Opening a file runs its nodes' saved code (top-level statements too) and
    constrkw sourceCode: in an isolated network, inside the sandbox."""
    _need_bwrap()
    app = _app('atopen')
    try:
        with Canary() as c:
            plain = app.new('template', 'unrestricted')
            nid = _generic(plain, 'def doit(self):\n    pass\n')
            plain.save('template')
            with open(os.path.join(plain.folder, 'template.wnet.json')) as fh:
                data = json.load(fh)
            e = [x for x in data['network']['nodes'] if x['id'] == nid][0]
            e['code'] = ('import os\n'
                         'open("at_open.txt", "w").write(os.getcwd())\n'
                         'try:\n    open(%r + "/at_open.txt", "w").write("x")\n'
                         'except Exception as e:\n    open("blocked.txt", "w").write(type(e).__name__)\n'
                         'def doit(self):\n    pass\n' % c.path)
            e2 = dict(e, id=e['id'] + 'b', name='second')
            e2.pop('code')
            e2['constrkw'] = {'sourceCode': 'open("constrkw.txt", "w").write("ran")\n'
                                            'def doit(self):\n    pass\n'}
            data['network']['nodes'].append(e2)
            raw = json.dumps(data).encode()
            d = app.open('evil.wnet.json', raw, 'sandboxed', False)
            s = app.session(d['session'])
            check(isinstance(s, isolation.IsolatedSession))
            eq(open(os.path.join(s.folder, 'at_open.txt')).read(), s.folder)
            check(open(os.path.join(s.folder, 'blocked.txt')).read() in
                  ('FileNotFoundError', 'PermissionError', 'OSError'))
            check(os.path.isfile(os.path.join(s.folder, 'constrkw.txt')))
            check(not os.path.exists(os.path.join(c.path, 'at_open.txt')))
            check(not os.path.exists(os.path.join(os.getcwd(), 'constrkw.txt')))
    finally:
        _close(app)


def test_downloads_do_not_follow_planted_links():
    _need_bwrap()
    from wewos.server import build
    httpd = build('127.0.0.1', 0, outdir('iso_links'))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d' % httpd.server_address[1]
    tok = httpd.app.token
    try:
        with Canary() as c:
            s = httpd.app.new('links', 'sandboxed')
            nid = _generic(s, ('def doit(self):\n    import os\n'
                               '    os.symlink(%(c)r + "/secret.txt", "link.txt")\n'
                               '    os.makedirs("d", exist_ok=True)\n'
                               '    os.symlink(%(c)r, "d/dirlink")\n'
                               '    open("ok.txt", "w").write("fine")\n') % {'c': c.path})
            s.run('run_node', nid)
            _wait_file(os.path.join(s.folder, 'ok.txt'))

            def get(q):
                try:
                    with urllib.request.urlopen(base + '/api/download?s=%s&t=%s%s'
                                                % (s.id, tok, q)) as r:
                        return r.status, r.read()
                except urllib.error.HTTPError as e:
                    return e.code, e.read()
            eq(get('&file=ok.txt'), (200, b'fine'))
            eq(get('&file=link.txt')[0], 400)
            eq(get('&file=d/dirlink/secret.txt')[0], 400)
            st, body = get('')
            eq(st, 200)
            names = zipfile.ZipFile(io.BytesIO(body)).namelist()
            check('ok.txt' in names and 'link.txt' not in names, names)
            check(not any('secret' in n for n in names), names)
    finally:
        _close(httpd.app)
        httpd.shutdown()


def test_fetch_pdb_goes_through_the_server():
    _need_bwrap()
    from wewos import fetch
    asked = []

    def fake(code, timeout=30):
        code = fetch.check_code(code)
        asked.append(code)
        return ('HEADER    FAKE ENTRY %s\n' % code).encode() + b'REMARK\n' * 60

    real, fetch.download = fetch.download, fake
    app = _app('fetch')
    try:
        s = app.new('fetch', 'sandboxed', False)
        nid = _generic(s, '''def doit(self):
    import json
    from wewos import fetch
    path, url, cached = fetch.fetch('1hsg', '_rcsb')
    r = {'head': open(path).read().splitlines()[0]}
    try:
        fetch.remote('../../etc/passwd')
        r['bad'] = 'fetched'
    except Exception as e:
        r['bad'] = str(e)
    open('fetched.json', 'w').write(json.dumps(r))
''')
        s.run('run_node', nid)
        _wait_file(os.path.join(s.folder, 'fetched.json'))
        with open(os.path.join(s.folder, 'fetched.json')) as fh:
            r = json.load(fh)
    finally:
        fetch.download = real
        _close(app)
    eq(r['head'], 'HEADER    FAKE ENTRY 1HSG')
    eq(asked, ['1HSG'])
    check('is not a PDB id' in r['bad'], r)


def test_force_stop_restarts_from_the_autosave():
    _need_bwrap()
    app = _app('kill')
    try:
        s = app.new('loop', 'sandboxed')
        nid = _generic(s, 'def doit(self):\n    while True:\n        pass\n')
        s.run('run_node', nid)
        time.sleep(1.0)
        s.run('stop')
        time.sleep(1.5)
        eq(s.summary()['status'], 'stop')            # asked to stop, still in the loop
        out = s.run('kill')
        check(out.get('restarted'), out)
        st = s.state()
        eq(st['execStatus'], 'waiting')
        check(nid in {n['id'] for n in st['networks']['main']['nodes']}, st)
        ev = s.events(10 ** 6, 0.1)                  # a client that saw the old worker
        check(ev.get('reset'), ev)
    finally:
        _close(app)


def test_same_results_as_unrestricted():
    _need_bwrap()
    app = _app('same')
    out = {}
    try:
        for name in ('spheres_colormap.wnet.json', 'plots.wnet.json'):
            with open(os.path.join(ROOT, 'examples', name)) as fh:
                data = json.load(fh)
            for level in ('unrestricted', 'sandboxed'):
                s = app.new(name, level, prepare=lambda f: shutil.copytree(
                    os.path.join(ROOT, 'examples', 'data'), os.path.join(f, 'data')))
                eq(s.load(data), [])
                s.run('hardrun')
                _wait_idle(s)
                st = s.state()
                ports = {}
                for n in st['networks']['main']['nodes']:
                    check(n.get('status') != 'error', n)
                    if n['name'].startswith('Rand'):
                        continue                 # random numbers, not seeded
                    for p in n.get('out') or []:
                        d = s.edit('port_data', {'node': n['id'], 'io': 'out', 'port': p['name']})
                        # objects print with their address; compare the rest
                        ports[(n['name'], p['name'])] = (d['type'], d['text'] if 'object at 0x'
                                                         not in d['text'] else '')
                out[(name, level)] = ports
    finally:
        _close(app)
    for name in ('spheres_colormap.wnet.json', 'plots.wnet.json'):
        check(out[(name, 'unrestricted')], name)
        eq(out[(name, 'sandboxed')], out[(name, 'unrestricted')], name)


def test_change_isolation_of_an_open_network():
    _need_bwrap()
    app = _app('change')
    try:
        s = app.new('n', 'unrestricted')
        nid = _generic(s, 'def doit(self):\n    pass\n')
        d = app.set_isolation(s.id, 'sandboxed', False)
        eq(d['isolation']['level'], 'sandboxed')
        check(nid in {n['id'] for n in d['networks']['main']['nodes']}, d)
        check(isinstance(app.session(s.id), isolation.IsolatedSession))
        d = app.set_isolation(s.id, 'unrestricted')
        eq(d['isolation']['level'], 'unrestricted')
        check(nid in {n['id'] for n in d['networks']['main']['nodes']}, d)
    finally:
        _close(app)


def test_settings_persist_and_the_server_minimum():
    _need_bwrap()
    a = _app('settings')
    eq(a.get_settings()['open_level'], 'sandboxed')     # files from others: isolated
    a.set_settings({'open_level': 'readonly', 'internet': True})
    b = _app('settings')
    eq((b.settings['open_level'], b.settings['internet']), ('readonly', True))
    strict = _app('strict', minimum='sandboxed')
    try:
        d = strict.example('spheres_colormap.wnet.json')
        eq(d['isolation']['level'], 'sandboxed')
        s = strict.new('x', 'unrestricted')
        eq(s.info()['isolation']['level'], 'sandboxed')
        from wewos.session import Refused
        try:
            strict.load_library({'file': os.path.join(ROOT, 'wewos', 'libs', 'standard.py')})
            raise AssertionError('a server that isolates every network loaded a file')
        except Refused:
            pass
    finally:
        _close(strict)


def test_event_bus_resets_a_client_from_the_future():
    bus = EventBus()
    bus.emit('x')
    check(bus.since(5, 0).get('reset'))
    check(not bus.since(0, 0).get('reset'))


def test_molecules_and_surfaces_in_the_sandbox():
    """MolKit2, prody and MSMS load and run in a sandboxed worker."""
    _need_bwrap()
    from common import requires

    @requires('MolKit2', 'mslib')
    def body():
        app = _app('molecules')
        try:
            for name in ('contacts.wnet.json', 'crambin_surface.wnet.json'):
                path = os.path.join(ROOT, 'examples', name)
                if not os.path.isfile(path):
                    continue
                with open(path) as fh:
                    data = json.load(fh)
                s = app.new(name, 'sandboxed', prepare=lambda f: shutil.copytree(
                    os.path.join(ROOT, 'examples', 'data'), os.path.join(f, 'data')))
                eq(s.load(data), [])
                s.run('hardrun')
                _wait_idle(s)
                bad = [n['name'] for n in s.state()['networks']['main']['nodes']
                       if n.get('status') == 'error']
                eq(bad, [], name)
        finally:
            _close(app)
    body()


def test_an_example_opens_at_the_level_asked_for():
    _need_bwrap()
    app = _app('example_level')
    try:
        d = app.example('spheres_colormap.wnet.json')            # none asked: unrestricted
        eq(d['isolation']['level'], 'unrestricted')
        d = app.example('spheres_colormap.wnet.json', 'sandboxed', False)
        eq((d['isolation']['level'], d['isolation']['internet']), ('sandboxed', False))
        s = app.session(d['session'])
        check(isinstance(s, isolation.IsolatedSession))
        check(os.path.isdir(os.path.join(s.folder, 'data')))     # its data came along
    finally:
        _close(app)


def test_macos_profile_for_each_level():
    """The sandbox-exec profile (macOS), checked as text here: it runs only on
    a Mac, where available() also starts Python and the worker under it."""
    import sys
    import tempfile
    folder = os.path.realpath(tempfile.mkdtemp(prefix='wewos-prof-', dir=outdir('macos')))
    grant = os.path.realpath(outdir('macos_grant'))
    sb = isolation.macos_profile('sandboxed', False, folder, [grant])
    ro = isolation.macos_profile('readonly', False, folder)
    net = isolation.macos_profile('readonly', True, folder)
    for p in (sb, ro, net):
        eq(p.count('('), p.count(')'))
        check(p.startswith('(version 1)\n(deny default)\n'), p[:40])
        check('(allow file-read* file-write* (subpath "%s"))' % folder in p, p)
        check('(allow file-write*)' not in p and 'file-write* (subpath "/' + '"' not in p)
    check('(allow file-read*)' not in sb, 'a sandboxed network must not read everything')
    check('(subpath "%s")' % grant in sb, sb)
    import re
    roots = re.findall(r'\(subpath "([^"]+)"\)', sb)
    prefix = os.path.realpath(sys.prefix)
    check(any(prefix == r or prefix.startswith(r + '/') for r in roots), 'the environment must be readable')
    check('(allow file-read*)' in ro)
    check('network-outbound' not in sb and 'network-outbound' not in ro and 'system-socket' not in ro)
    check('(allow network-outbound)' in net and '(allow system-socket)' in net)
    home = os.path.realpath(os.path.expanduser('~'))
    check('(subpath "%s")' % home not in sb, 'the home folder must not be readable')
    # the command line and environment a Mac would use
    real = sys.platform
    try:
        sys.platform = 'darwin'
        args, env, kw = isolation.command('sandboxed', False, folder, 7, 9)
    finally:
        sys.platform = real
    eq(args[:2], [isolation.SANDBOX_EXEC, '-p'])
    check(args[3:7] == [sys.executable, '-m', 'wewos.worker', '--rfd'] and '9' in args, args[3:])
    eq((env['HOME'], env['TMPDIR']), (folder + '/.wewos', folder + '/.wewos/tmp'))
    check(kw.get('start_new_session') and kw.get('cwd') == folder, kw)
    check('SSH_AUTH_SOCK' not in env and 'DISPLAY' not in env, env)
