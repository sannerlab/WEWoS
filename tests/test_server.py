# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The HTTP layer, end to end on a real socket (the ADapt pattern)."""
import json
import os
import threading
import urllib.error
import urllib.request

from common import DATA, check, eq, outdir


def _server():
    from wewos.server import build
    httpd = build('127.0.0.1', 0, outdir('server'))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, 'http://127.0.0.1:%d' % httpd.server_address[1], httpd.app.token


def _get(url, raw=False):
    with urllib.request.urlopen(url) as r:
        body = r.read()
        return (r.status, body) if raw else json.loads(body.decode())


def _post(url, obj=None, data=None):
    body = data if data is not None else json.dumps(obj or {}).encode()
    req = urllib.request.Request(url, data=body, method='POST')
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def _code(url, data=None):
    try:
        req = urllib.request.Request(url, data=data, method='POST' if data is not None else 'GET')
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_token_is_required():
    httpd, base, tok = _server()
    try:
        check(_code(base + '/') == 403)
        check(_code(base + '/api/status') == 403)
        check(_code(base + '/api/new', b'{}') == 403)
        check(_code(base + '/?t=wrong') == 403)
        st, body = _get(base + '/?t=' + tok, raw=True)
        check(st == 200 and b'3Dmol-min.js' in body and b'editor.js' in body)
        check(_code(base + '/static/app.js') == 200)
        check(_code(base + '/static/../server.py') == 404)
    finally:
        httpd.shutdown()


def test_build_run_save_open():
    httpd, base, tok = _server()
    t = '?t=' + tok
    try:
        libs = _get(base + '/api/libraries' + t)
        check({'Standard', '3D Visualization', 'Molecules', 'SymServer', 'Volume', 'Imaging'}
              <= {k['name'] for k in libs['known']}, libs['known'])
        check('Standard' in {l['name'] for l in libs['libraries']})
        s = _post(base + '/api/new' + t, {'name': 'demo'})
        sid = s['session']
        ed = lambda op, **a: _post(base + '/api/edit' + t, dict(a, s=sid, op=op))
        r = ed('add', lib='Standard', label='range', pos=[0, 0])['node']['id']
        it = ed('add', lib='Standard', label='iterate', pos=[200, 0])['node']['id']
        acc = ed('add', lib='Standard', label='accum', pos=[400, 0])['node']['id']
        ed('set_widget', node=r, port='toInd', value=3, run=False)
        for a, b in (((r, 'data'), (it, 'listToLoopOver')), ((it, 'oneItem'), (acc, 'data')),
                     ((it, 'begin'), (acc, 'begin')), ((it, 'end'), (acc, 'output'))):
            c = ed('connect', **{'from': list(a), 'to': list(b)})
            check('conn' in c, c)
        bad = ed('connect', **{'from': [r, 'data'], 'to': [it, 'listToLoopOver']})
        check('error' in bad)
        seq = _get(base + '/api/session?s=%s&t=%s' % (sid, tok))['seq']
        _post(base + '/api/run' + t, {'s': sid, 'mode': 'hardrun'})
        app = httpd.app
        check(app.sessions[sid].runner.wait(20))
        evs = _get(base + '/api/events?s=%s&since=%d&timeout=1&t=%s' % (sid, seq, tok))
        done = {e['node'] for e in evs['events'] if e['kind'] == 'node_status' and e['status'] == 'done'}
        check({r, it, acc} <= done, evs)
        acc_node = app.sessions[sid].node(acc)
        eq(acc_node.outputPorts[0].data, [0, 1, 2])
        # save, download, reopen as a new network
        sv = _post(base + '/api/save' + t, {'s': sid, 'name': 'demo'})
        st, body = _get(base + '/api/download?s=%s&file=%s&t=%s' % (sid, sv['file'], tok), raw=True)
        check(st == 200 and b'wewos-net' in body)
        o = _post(base + '/api/open?name=demo.wnet.json&t=' + tok, data=body)
        eq(len(o['networks']['main']['nodes']), 3)
        eq(o['report'], [])
    finally:
        httpd.shutdown()


def test_import_endpoint_and_code_edit():
    httpd, base, tok = _server()
    t = '?t=' + tok
    try:
        with open(os.path.join(DATA, 'cpk_net.py'), 'rb') as fh:
            raw = fh.read()
        d = _post(base + '/api/import?name=cpk_net.py&t=' + tok, data=raw)
        check('session' in d, d)
        eq(len(d['networks']['main']['nodes']), 3)
        eq(d['report']['unmapped'], [])
        sid = d['session']
        rd = [n for n in d['networks']['main']['nodes'] if n['cls'] == 'ReadMolecule'][0]['id']
        bad = _post(base + '/api/edit' + t, {'s': sid, 'op': 'set_code', 'node': rd,
                                             'code': 'def doit(self, filename)\n  pass\n'})
        check('error' in bad and 'line' in bad['error'], bad)
        ok = _post(base + '/api/edit' + t, {'s': sid, 'op': 'set_code', 'node': rd,
                                            'code': 'def doit(self, filename):\n    pass\n'})
        check('error' not in ok, ok)
    finally:
        httpd.shutdown()


def test_libraries_on_demand_and_user_library():
    httpd, base, tok = _server()
    t = '?t=' + tok
    try:
        r = _post(base + '/api/library' + t, {'name': 'SymServer'})
        check('SymServer' in {l['name'] for l in r['libraries']}, r)
        # a library of the user's, from a file
        path = os.path.join(outdir('userlib'), 'mynodes.py')
        with open(path, 'w') as fh:
            fh.write("from wewos.engine import NetworkNode, NodeLibrary\n"
                     "class Double(NetworkNode):\n"
                     "    def __init__(self, name='double', **kw):\n"
                     "        kw['name'] = name\n"
                     "        NetworkNode.__init__(self, **kw)\n"
                     "        self.inputPortsDescr.append(datatype='float', name='x')\n"
                     "        self.outputPortsDescr.append(datatype='float', name='y')\n"
                     "        self.setFunction('def doit(self, x):\\n    self.outputData(y=2 * x)\\n')\n"
                     "mylib = NodeLibrary('My nodes', '#888888')\n"
                     "mylib.addNode(Double, 'double', 'Math')\n")
        r = _post(base + '/api/library' + t, {'file': path})
        check('My nodes' in {l['name'] for l in r['libraries']}, r)
        conf = json.load(open(httpd.app.libconf_path))
        check('My nodes' in conf['user'])
        r = _post(base + '/api/library_startup' + t, {'name': 'SymServer', 'on': True})
        check([k for k in r['known'] if k['name'] == 'SymServer'][0]['startup'])
        s = _post(base + '/api/new' + t, {'name': 'u'})
        d = _post(base + '/api/edit' + t, {'s': s['session'], 'op': 'add', 'lib': 'My nodes',
                                           'label': 'double', 'pos': [0, 0]})
        check('node' in d, d)
    finally:
        httpd.shutdown()
