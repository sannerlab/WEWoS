# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Builds examples/tutorial/ from the Vision tutorial of MGLTools 1.5.3
(Vision/doc/Tutorial, Michel Sanner and Guillaume Vareille, 2008), the
networks the documentation's tutorials use (docs/src/tut-*.html).

    bin/wewos-python examples/make_tutorial_examples.py [--check] [TUTORIAL_DIR]

The tutorial's data (the cartoonMovie images, 2plv.pdb, nomegav1AS.pdb,
ct_head.rawiv, lig.ccp4, nwv2.ccp4) is copied next to the networks; the
server copies it to a network's folder when one of them is opened. The
tutorial's saved networks are imported (wewos.legacy.importer) and laid out
from left to right; cartoon1b gets the tutorial's edit of Filelist's code
(values.sort(), which its saved network does not have). Three networks are
written here instead:
- start: an empty network, to build the tutorials in a folder that has the data;
- dial and print: the tutorial's first network (it was not saved);
- mol2plv: the poliovirus backbone colored by x and drawn 60 times with the
  icosahedral matrices. The tutorial's mol2plv_net.py changed the insides of
  two library macros (Lines Macro, Icosahedral1), which the importer does not
  carry over; WEWoS's Lines node takes colors and instance matrices on its
  own inputs, so the network is written with them.
Left out: the networks driving PMV (hemoglobin, msmsGen, runningsurface:
PMV is not ported) and cartoon2c, cartoon4, cartoon5 (variants of the
others; cartoon2c's user panel is not ported).

--check runs every network in a temporary folder holding the data and
reports the nodes that did not run.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import matplotlib  # noqa: E402
matplotlib.use('Agg')

from wewos.engine import Network, fileio, get_library  # noqa: E402
from wewos.legacy.importer import import_file  # noqa: E402
from make_vision_examples import run  # noqa: E402

SOURCE = ('/export/people/sanner/dev/MakeInstallers/buildrc-1-5-7/sharedpackages/'
          'VisionDIST/Vision/doc/Tutorial')
OUT = os.path.join(HERE, 'tutorial')
DATA = ['cartoon/cartoonMovie', 'mol2plv/2plv.pdb', 'blurgausian/nomegav1AS.pdb',
        'headandslice/ct_head.rawiv', 'isorad/lig.ccp4', 'regioncapsid/nwv2.ccp4']
# file name (sets the order in the Examples dialog), tutorial network, title
IMPORTED = [
    ('02_cartoon0', 'cartoon/cartoon0_net.py', 'cartoon0: an image viewer'),
    ('03_cartoon0b', 'cartoon/cartoon0b_net.py', 'cartoon0b: a file name from a dial'),
    ('04_cartoon1', 'cartoon/cartoon1_net.py', 'cartoon1: iterate over a range'),
    ('05_cartoon1b', 'cartoon/cartoon1b_net.py', 'cartoon1b: iterate over a file list'),
    ('06_cartoon3', 'cartoon/cartoon3_net.py', 'cartoon3: sort the list with call method'),
    ('07_cartoon2', 'cartoon/cartoon2_net.py', 'cartoon2: a thumbwheel indexes the list'),
    ('08_cartoon2b', 'cartoon/cartoon2b_net.py', 'cartoon2b: the indexMax macro'),
    ('10_icoscage', 'icoscage/icoscage_net.py', 'icoscage: an icosahedral cage'),
    ('11_blurgaussian', 'blurgausian/blurgaussian_net.py', 'blurgaussian: a molecule blurred into a map'),
    ('12_headandslice', 'headandslice/headandslice_net.py', 'headandslice: a CT scan, isosurface and slices'),
    ('13_isorad', 'isorad/isorad_net.py', 'isorad: an isosurface colored by radius'),
    ('14_regioncapsid', 'regioncapsid/regioncapsid_net.py', 'regioncapsid: a capsid map cut open'),
]


def _entries(netd):
    for e in netd['nodes']:
        yield e
        if 'macro' in e:
            yield from _entries(e['macro'])


def patch(data):
    """A path left from the tutorial author's machine."""
    for e in _entries(data['network']):
        w = e.get('widgets') or {}
        for k, v in list(w.items()):
            if isinstance(v, str) and v.startswith('/home/') and 'crnCartoon' in v:
                w[k] = 'cartoonMovie/' + os.path.basename(v)
    return data


def save(net, fname, title, check):
    net.name = title
    net.runOnNewData.value = True
    path = os.path.join(OUT, fname + '.wnet.json')
    fileio.save(net, path)
    msg = '%-18s %2d nodes' % (fname, len(net.allNodes()))
    if check and net.allNodes():
        msg += '  ' + run(path, OUT)
    print(msg)


def imported(src, fname, title, check):
    data = patch(import_file(src)[0])
    net = Network(title)
    problems = fileio.from_dict(net, data)       # lays the Vision layout out again
    if problems:
        print('   %s: %s' % (fname, '; '.join(problems)))
    if fname in EDITS:
        EDITS[fname](net)
    save(net, fname, title, check)


def sort_in_code(net):
    """cartoon1b: the tutorial sorts the file list in Filelist's code (its
    saved network does not have the edit)."""
    fl = [n for n in net.allNodes() if n.name == 'Filelist'][0]
    old = 'values = glob.glob(match_str)\n'
    assert old in fl.sourceCode
    fl.setFunction(fl.sourceCode.replace(old, old + '        values.sort()\n'))


EDITS = {'05_cartoon1b': sort_in_code}


def node(net, lib, label, x, y, **widgets):
    n = get_library(lib).instantiate(label=label)
    net.addNode(n, x, y)
    for k, v in widgets.items():
        n.inputPortByName[k].widget.set(v, run=False)
    return n


def new(name):
    n = Network(name)
    n.runOnNewData.value = False
    return n


def dial_print(check):
    n = new('dial and print')
    d = node(n, 'Standard', 'Dial', 40, 40)
    p = node(n, 'Standard', 'print', 330, 60)
    n.connectNodes(d, p, 'value', 'in1')
    save(n, '01_dial_print', 'dial and print', check)


def mol2plv(check):
    n = new('mol2plv')
    rd = node(n, 'Molecules', 'Read Molecule', 30, 40, filename='2plv.pdb')
    sel = node(n, 'Molecules', 'Select', 300, 40, selectionString='name CA C N')
    prop = node(n, 'Molecules', 'Extract Atom Property', 560, 160, propertyName='coords[0]')
    cm = node(n, '3D Visualization', 'Color Map', 820, 160)
    ico = node(n, 'SymServer', 'Icosahedral1', 820, 330)
    ln = node(n, 'Molecules', 'Lines', 1100, 40)
    v = node(n, '3D Visualization', 'Viewer', 1360, 120)
    n.connectNodes(rd, sel, 'mol', 'nodes')
    n.connectNodes(sel, ln, 'selection', 'atoms')
    n.connectNodes(sel, prop, 'selection', 'atoms')
    n.connectNodes(prop, cm, 'propertyValues', 'values')
    n.connectNodes(cm, ln, 'colors', 'colors')
    n.connectNodes(ico, ln, 'Merge_outMatrices', 'instanceMatrices')
    n.connectNodes(ln, v, 'lines', 'geometries')
    n.connectNodes(cm, v, 'legend', 'geometries')
    save(n, '09_mol2plv', 'mol2plv: poliovirus with icosahedral symmetry', check)


def main(argv):
    check = '--check' in argv
    args = [a for a in argv if a != '--check']
    source = args[0] if args else SOURCE
    os.makedirs(OUT, exist_ok=True)
    for f in DATA:
        src, dst = os.path.join(source, f), os.path.join(OUT, os.path.basename(f))
        if os.path.isdir(src):
            if not os.path.isdir(dst):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('CVS'))
        elif not os.path.exists(dst):
            shutil.copy(src, dst)
    save(new('start'), '00_start', 'start here (an empty network with the tutorial data)', False)
    dial_print(check)
    for fname, src, title in IMPORTED:
        imported(os.path.join(source, src), fname, title, check)
    mol2plv(check)


if __name__ == '__main__':
    main(sys.argv[1:])
