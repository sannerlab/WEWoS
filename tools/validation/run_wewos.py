# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Import one Vision network (*_net.py), open it and run it in WEWoS without a
page, then dump every output port (see canon.py) and each node's outcome.

    python run_wewos.py <net_py> <workdir> <out_base>

validate.py runs this inside a sandbox; workdir holds copies of the files
the network reads, and is its folder.
"""
import contextlib
import io
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import canon  # noqa: E402


def descendants(starts):
    """Nodes reached from starts along connections, into and out of macros."""
    seen, todo = set(), list(starts)
    while todo:
        n = todo.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        for p in n.outputPorts:
            for c in p.connections:
                todo.append(c.port2.node)
        for c in getattr(n, 'specialOutputPorts', []):
            for cc in getattr(c, 'connections', []):
                todo.append(cc.port2.node)
        mn = getattr(n, 'macroNetwork', None)
        if mn is not None:                      # data enters the macro
            todo.extend(x for x in mn.nodes if x.__class__.__name__ == 'MacroInputNode')
        net = n.network
        mnode = getattr(net, 'macroNode', None) if net is not None else None
        if mnode is not None and n.__class__.__name__ == 'MacroOutputNode':
            todo.append(mnode)                  # data leaves the macro
    return seen


def main(src, workdir, out_base):
    os.chdir(workdir)
    import random
    import numpy
    random.seed(0)
    numpy.random.seed(0)      # the same random numbers on both sides
    res = {'stage': 'import', 'seconds': {}}
    net = None
    log = io.StringIO()
    t = time.time()
    try:
        from wewos.engine import Network, fileio
        from wewos.engine.ports import _is_nodata
        from wewos.legacy.importer import import_file
        from wewos.libs.viz3d import Viewer
        data, report = import_file(src)
        res['import_report'] = report.as_dict()
        res['seconds']['import'] = time.time() - t
        res['stage'] = 'load'
        t = time.time()
        net = Network('validate', workdir=workdir)
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            res['load_problems'] = [str(x) for x in (fileio.from_dict(net, data) or [])]
        res['seconds']['load'] = time.time() - t
        open(out_base + '.opened', 'w').close()     # opened, whatever the run does
        res['stage'] = 'run'
        t = time.time()
        Viewer.snapshotTimeout = 0.2              # Grab Image: no page here
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            net.run(list(net.rootNodes))
        res['seconds']['run'] = time.time() - t
        res['stage'] = 'ran'
    except Exception:
        res['exception'] = traceback.format_exc()[-3000:]
    if net is None:
        canon.dump(_Empty(), lambda d: False, out_base, {'wewos': res})
        return
    from wewos.engine.fileio import UnsupportedNode
    from wewos.engine.ports import _is_nodata
    nodes = list(canon.walk(net))
    holders = [n for _, n in nodes if isinstance(n, UnsupportedNode)]
    below = descendants(holders)
    page = descendants([n for _, n in nodes if n.__class__.__name__ == 'GetFrontBuffer'])
    out = {}
    for path, n in nodes:
        e = {'status': n.status, 'cls': n.__class__.__name__}
        if isinstance(n, UnsupportedNode):
            e['placeholder'] = n.origin
        if id(n) in below:
            e['below_placeholder'] = True
        if id(n) in page:
            e['needs_page'] = True
        if n.lastError:
            e['error'] = str(n.lastError)[-1500:]
        out[path] = e
    res['nodes'] = out
    res['log'] = log.getvalue()[-6000:]
    canon.dump(net, _is_nodata, out_base, {'wewos': res})


class _Empty(object):
    nodes = []


if __name__ == '__main__':
    main(*sys.argv[1:4])
