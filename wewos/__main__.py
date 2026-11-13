# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Command line: python -m wewos serve | run | import | check | test (bin/wewos wraps it)."""
import argparse
import os
import sys

DEFAULT_OUTDIR = os.environ.get('WEWOS_OUTDIR', '~/wewos_runs')


def main(argv=None):
    from . import APP, APP_LONG, COPYRIGHT, __version__
    p = argparse.ArgumentParser(
        prog='wewos', formatter_class=argparse.RawDescriptionHelpFormatter,
        description='%s %s: %s' % (APP, __version__, APP_LONG),
        epilog='examples:\n'
               '  wewos serve                       start on port 8767 and print the URL\n'
               '  wewos run net.wnet.json           run a network without a browser\n'
               '  wewos run net.wnet.json --set Dial.dial=3.5\n'
               '  wewos import old_net.py -o new.wnet.json   convert a Vision network\n'
               '  wewos check                       what is missing\n'
               '  wewos test -k engine              run part of the test suite\n\n'
               + COPYRIGHT)
    p.add_argument('--version', action='version', version='%s %s' % (APP, __version__))
    sub = p.add_subparsers(dest='cmd')
    s = sub.add_parser('serve', help='start the web page (prints its URL)')
    s.add_argument('--host', default='127.0.0.1',
                   help='address to bind (default 127.0.0.1: this machine only)')
    s.add_argument('--port', type=int, default=8767, help='0 picks a free port')
    s.add_argument('--base-path', default=os.environ.get('WEWOS_BASE_PATH', ''),
                   help='also serve under this path prefix (behind a proxy)')
    s.add_argument('--outdir', default=DEFAULT_OUTDIR,
                   help='where each network keeps its folder (default %(default)s)')
    s.add_argument('--isolation', default='unrestricted',
                   choices=['unrestricted', 'readonly', 'sandboxed'],
                   help='the least isolation of every network, for a server others use: '
                        'readonly (reads your files, writes its folder) or sandboxed (sees '
                        'only its folder); needs Linux and bubblewrap (default: networks you '
                        'open from files are isolated as you choose, the others are not)')
    r = sub.add_parser('run', help='run a saved network without a browser')
    r.add_argument('network')
    r.add_argument('--set', action='append', default=[], metavar='NODE.PORT=VALUE',
                   help='set a widget before running (value read as Python literal)')
    r.add_argument('--soft', action='store_true',
                   help='soft run (only nodes with new data) instead of a full run')
    i = sub.add_parser('import', help='convert a Vision *_net.py to a .wnet.json')
    i.add_argument('network')
    i.add_argument('-o', '--output')
    sub.add_parser('check', help='report what is missing')
    t = sub.add_parser('test', help='run the test suite (tests/run_tests.py)')
    t.add_argument('-k', default='', help='only tests whose name contains this')
    a = p.parse_args(argv)

    if a.cmd == 'test':
        import subprocess
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        runner = os.path.join(here, 'tests', 'run_tests.py')
        return subprocess.call([sys.executable, runner] + (['-k', a.k] if a.k else []))
    if a.cmd == 'check':
        from . import env
        miss = env.check()
        print('%s is ready' % APP if not miss else 'missing: %s' % '; '.join(miss))
        return 1 if miss else 0
    if a.cmd == 'run':
        return _run(a)
    if a.cmd == 'import':
        import json
        from .legacy import importer
        with open(a.network, 'rb') as fh:
            raw = fh.read()
        data, report = importer.import_source(raw.decode('utf-8', 'replace'), a.network)
        out = a.output or (a.network[:-len('_net.py')] if a.network.endswith('_net.py')
                           else os.path.splitext(a.network)[0]) + '.wnet.json'
        with open(out, 'w') as fh:
            json.dump(data, fh, indent=1)
        print(report.text())
        print('wrote %s' % out)
        return 0
    if a.cmd != 'serve':
        p.print_help()
        return 2
    if os.path.realpath(os.path.expanduser(a.outdir)).startswith('/tmp'):
        p.error('--outdir must not be under /tmp; it is wiped')
    from .server import clean_base_path, serve
    try:
        base = clean_base_path(a.base_path)
    except ValueError as e:
        p.error(str(e))
    try:
        serve(a.host, a.port, a.outdir, base, a.isolation)
    except RuntimeError as e:
        p.error(str(e))
    return 0


def _run(a):
    import ast
    from .engine import Network, fileio
    net = Network('cli')
    report = fileio.load(net, a.network)
    for line in report:
        print('warning: %s' % line)
    for item in a.set:
        target, _, value = item.partition('=')
        nname, _, pname = target.rpartition('.')
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            pass
        nodes = [n for n in net.allNodes() if n.name == nname]
        if not nodes:
            print('no node named %r' % nname)
            return 2
        port = nodes[0].inputPortByName.get(pname)
        if port is None or port.widget is None:
            print('node %s has no widget on port %r' % (nname, pname))
            return 2
        port.widget.set(value, run=False)
    if a.soft:
        net.run()
    else:
        net.run(list(net.rootNodes))
    failed = [n for n in net.allNodes() if n.status == 'error']
    for n in failed:
        print('node %s failed:\n%s' % (n.name, n.lastError))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
