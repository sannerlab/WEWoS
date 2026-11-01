# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Builds examples/vision/ and examples/vision_matplotlib/ from the examples
that came with MGLTools Vision (Vision/doc/Examples): each *_net.py is
imported (wewos.legacy.importer), laid out from left to right, saved as
.wnet.json, and the data files it reads are copied next to it.

    bin/wewos-python examples/make_vision_examples.py [--check] [VISION_EXAMPLES_DIR]

--check runs every network (in a temporary folder holding its data) and
reports the nodes that did not run.

Changes from the originals:
- the "Lena" photograph (lena.jpg) is not redistributed: lena_net.py
  (here "image filters") and Figimage read image.jpg, a picture made with
  WEWoS (a Mol* rendering of the poliovirus capsid example);
- Quiver: its ReadTable nodes split the comma-separated data files on commas.
The ViPEr paper's figure 1 (ViPErPaper-fig1_net.py, "viper figure1": crambin's
MSMS surface, transparent, over its atoms scaled by a dial and colored by x,
and the picture of the viewer filtered) needs a page showing its viewer for
Grab Image. Left out: the NBCR screening network (Pmv, AutoDock web
services), ImageFigure (a DejaVu textured quad), and Legend_net_1,
Log_semixy_net and Contour_Filled_net (copies of other examples, two of them
reading files that are not there).
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import matplotlib  # noqa: E402
matplotlib.use('Agg')

from wewos.engine import Network, fileio  # noqa: E402
from wewos.legacy.importer import import_file  # noqa: E402

SOURCE = ('/export/people/sanner/dev/MakeInstallers/buildrc-1-5-7/sharedpackages/'
          'VisionDIST/Vision/doc/Examples')
SKIP = {'ImageFigure_net.py', 'Legend_net_1.py', 'Log_semixy_net.py', 'Contour_Filled_net.py'}
# Vision example -> (group folder, example name)
TOP = {'cpk_net.py': 'cpk', 'icos_net.py': 'icos', 'lena_net.py': 'image_filters',
       'ViPErPaper-fig1_net.py': 'viper_figure1'}
IMAGE = {'lena.jpg': 'image.jpg', 'Data/lena.jpg': 'Data/image.jpg'}
TITLES = {'viper_figure1': 'ViPEr paper figure 1'}


def _entries(netd):
    for e in netd['nodes']:
        yield e
        if 'macro' in e:
            yield from _entries(e['macro'])


def patch(name, data):
    for e in _entries(data['network']):
        w = e.get('widgets') or {}
        for k, v in list(w.items()):
            if isinstance(v, str) and v in IMAGE:
                w[k] = IMAGE[v]
        if name == 'Quiver_net.py' and e.get('cls') == 'ReadTable':
            w['sep'] = ','
            e['widgets'] = w
    return data


def files_read(data):
    """The relative file names a network's widgets give."""
    out = set()
    for e in _entries(data['network']):
        for v in (e.get('widgets') or {}).values():
            if isinstance(v, str) and '.' in v and not os.path.isabs(v) and '\n' not in v \
                    and len(v) < 200 and os.path.splitext(v)[1].lower() in (
                        '.pdb', '.dat', '.jpg', '.txt', '.csv'):
                out.add(v)
    return out


def convert(src, group, name, check):
    data = patch(os.path.basename(src), import_file(src)[0])
    out_dir = os.path.join(HERE, group)
    os.makedirs(out_dir, exist_ok=True)
    srcdir = os.path.dirname(src)
    for f in sorted(files_read(data)):
        dst = os.path.join(out_dir, f)
        if os.path.exists(dst):
            continue
        if os.path.exists(os.path.join(srcdir, f)) and f not in IMAGE.values():
            os.makedirs(os.path.dirname(dst) or out_dir, exist_ok=True)
            shutil.copy(os.path.join(srcdir, f), dst)
        elif f not in IMAGE.values():
            print('   %s: %s is not there' % (name, f))
    net = Network(name)
    problems = fileio.from_dict(net, data)       # lays the Vision layout out again
    net.name = TITLES.get(name, name.replace('_', ' '))
    fileio.save(net, os.path.join(out_dir, name + '.wnet.json'))
    msg = '%-26s %2d nodes' % (group + '/' + name, len(net.allNodes()))
    if problems:
        msg += '  load: ' + '; '.join(problems)
    if check:
        msg += '  ' + run(os.path.join(out_dir, name + '.wnet.json'), out_dir)
    print(msg)


def run(path, group_dir):
    """Run a saved example in a copy of its group's data; '' when all ran."""
    import json
    tmp = tempfile.mkdtemp(prefix='wewos-ex-')
    try:
        for f in os.listdir(group_dir):
            if not f.endswith('.wnet.json'):
                p = os.path.join(group_dir, f)
                (shutil.copytree if os.path.isdir(p) else shutil.copy)(p, os.path.join(tmp, f))
        with open(path) as fh:
            data = json.load(fh)
        from wewos.libs.viz3d import Viewer
        net = Network('check', workdir=tmp)
        buf = io.StringIO()
        saved, Viewer.snapshotTimeout = Viewer.snapshotTimeout, 0.2   # no page here
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                fileio.from_dict(net, data)
                net.run(list(net.rootNodes))
        finally:
            Viewer.snapshotTimeout = saved
        # Grab Image needs a page showing the viewer: it and what follows it do not count
        page = set()
        todo = [n for n in net.allNodes() if n.__class__.__name__ == 'GetFrontBuffer']
        while todo:
            n = todo.pop()
            if id(n) not in page:
                page.add(id(n))
                todo += [c.port2.node for p in n.outputPorts for c in p.connections]
        bad = ['%s (%s)' % (n.name, n.status) for n in net.allNodes()
               if n.status != 'done' and id(n) not in page]
        return ('ran' if not bad else 'NOT RUN: ' + ', '.join(bad)) + \
            (' (Grab Image needs the page)' if page else '')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    check = '--check' in argv
    args = [a for a in argv if a != '--check']
    source = args[0] if args else SOURCE
    for f, name in TOP.items():
        convert(os.path.join(source, f), 'vision', name, check)
    mpl = os.path.join(source, 'matplotlib')
    for f in sorted(os.listdir(mpl)):
        if f.endswith('_net.py') and f not in SKIP:
            convert(os.path.join(mpl, f), 'vision_matplotlib', f[:-len('_net.py')], check)


if __name__ == '__main__':
    main(sys.argv[1:])
