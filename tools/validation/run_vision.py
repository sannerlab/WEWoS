# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Run one Vision network (*_net.py) in MGLTools Vision without its editor
(NoGuiExec, as the file's own '-w' option does) and dump every output port
with canon.py. Python 2.7, MGLTools 1.5.7:

    $MGL/bin/pythonsh run_vision.py <net_py> <workdir> <out_base>
"""
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import canon  # noqa: E402


def _nodata(d):
    return isinstance(d, str) and d == 'no data yet'


def _settle(net):
    """Let Tk process what the run scheduled (viewer redraws)."""
    try:
        import Tkinter
        root = Tkinter._default_root
        for _ in range(20):
            if root is not None:
                root.update()
            time.sleep(0.05)
    except Exception:
        pass


def _exec(code, ns):
    exec(code, ns)


def main(src, workdir, out_base):
    os.chdir(workdir)
    sys.path.insert(0, os.path.dirname(os.path.abspath(src)))
    res = {'stage': 'build', 'seconds': {}}
    if os.environ.get('DISPLAY'):
        # Vision's editor, hidden, on the (virtual) display: viewers, color
        # maps and geometry nodes need it
        from Vision import launchVisionToRunNetworkAsApplication
        masterNet = launchVisionToRunNetworkAsApplication(splash=False)
        res['mode'] = 'editor'
    else:
        from Vision.VPE import NoGuiExec
        from NetworkEditor.net import Network
        ed = NoGuiExec()
        masterNet = Network('validate')
        ed.addNetwork(masterNet)
        res['mode'] = 'nogui'
    os.chdir(workdir)          # Vision's start-up may change it
    import random
    import numpy
    random.seed(0)
    numpy.random.seed(0)      # the same random numbers on both sides
    ns = {'__name__': 'vision_validate', 'masterNet': masterNet, '__file__': src}
    t = time.time()
    try:
        # statement by statement: the end of a saved file restores viewer
        # states, which needs Vision's editor; the nodes are built before
        import ast
        with open(src) as fh:
            tree = ast.parse(fh.read(), src)
        errors = []
        for stmt in tree.body:
            code = compile(ast.Module(body=[stmt]), src, 'exec')
            try:
                _exec(code, ns)
            except Exception:
                errors.append('line %d: %s' % (stmt.lineno, traceback.format_exc().strip().splitlines()[-1]))
        res['build_errors'] = errors
        res['seconds']['build'] = time.time() - t
        res['stage'] = 'run'
        t = time.time()
        # as if the file sat in the folder with its data, as Vision expects
        masterNet.filename = os.path.join(workdir, os.path.basename(src))
        os.chdir(workdir)
        res['cwd'] = os.getcwd()
        masterNet.run()
        _settle(masterNet)
        res['seconds']['run'] = time.time() - t
        res['stage'] = 'ran'
    except BaseException:
        res['exception'] = traceback.format_exc()[-3000:]
    canon.dump(masterNet, _nodata, out_base, {'vision': res})


if __name__ == '__main__':
    main(*sys.argv[1:4])
    sys.stdout.flush()
    os._exit(0)          # Vision may leave threads (viewers, communicators) behind
