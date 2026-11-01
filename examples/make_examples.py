# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Builds the example networks (examples/*.wnet.json).

    bin/wewos-python examples/make_examples.py      # or the adcpsuite python

Each example reads files relative to its network folder (data/...); the server
copies examples/data/ there when an example is opened (File > Open an example).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from wewos.engine import Network, fileio, get_library  # noqa: E402

STD, VIZ, MOL, SYM, VOL, IMG, MPL = (get_library(n) for n in (
    'Standard', '3D Visualization', 'Molecules', 'SymServer', 'Volume', 'Imaging', 'MatPlotLib'))


def node(net, lib, label, x, y, **widgets):
    n = lib.instantiate(label=label)
    net.addNode(n, x, y)
    for k, v in widgets.items():
        n.inputPortByName[k].widget.set(v, run=False)
    return n


def new(name):
    n = Network(name)
    n.runOnNewData.value = False
    return n


def save(net, name):
    net.runOnNewData.value = True
    path = os.path.join(HERE, name + '.wnet.json')
    fileio.save(net, path)
    print('wrote', path)


def crambin_surface():
    n = new('crambin surface')
    rd = node(n, MOL, 'Read Molecule', 30, 40, filename='data/1crn.pdb')
    sel = node(n, MOL, 'Select', 330, 30, selectionString='resname CYS')
    st = node(n, MOL, 'Sticks', 630, 30)
    ca = node(n, MOL, 'Cartoon', 330, 190)
    ms = node(n, MOL, 'MSMS', 330, 330, colorBy='element', opacity=0.6)
    v = node(n, VIZ, 'Viewer', 700, 300)
    n.connectNodes(rd, sel, 'mol', 'nodes')
    n.connectNodes(sel, st, 'selection', 'atoms')
    n.connectNodes(rd, ca, 'mol', 'atoms')
    n.connectNodes(rd, ms, 'mol', 'atoms')
    for g, p in ((st, 'sticks'), (ca, 'cartoon'), (ms, 'surface')):
        n.connectNodes(g, v, p, 'geometries')
    save(n, 'crambin_surface')


def iterate_squares():
    n = new('iterate squares')
    r = node(n, STD, 'range', 30, 40, toInd=10)
    it = node(n, STD, 'iterate', 260, 40)
    g = node(n, STD, 'Generic', 520, 40)
    g.rename('square')
    g.addInputPort(name='x', datatype='None')
    g.addOutputPort(name='y', datatype='None')
    g.setFunction("def doit(self, x):\n    self.outputData(y=x * x)\n")
    acc = node(n, STD, 'accum', 720, 40)
    pr = node(n, STD, 'print', 940, 60)
    n.connectNodes(r, it, 'data', 'listToLoopOver')
    n.connectNodes(it, g, 'oneItem', 'x')
    n.connectNodes(g, acc, 'y', 'data')
    n.connectNodes(it, acc, 'begin', 'begin')
    n.connectNodes(it, acc, 'end', 'output')
    n.connectNodes(acc, pr, 'listOfValues', 'in1')
    save(n, 'iterate_squares')


def pick_residue():
    n = new('pick a residue')
    rd = node(n, MOL, 'Read Molecule', 30, 40, filename='data/1crn.pdb')
    ln = node(n, MOL, 'Lines', 330, 40)
    v = node(n, VIZ, 'Viewer', 640, 120)
    pa = node(n, MOL, 'Picked Atom', 330, 300)
    st = node(n, MOL, 'Sticks', 600, 330, colorBy='orange')
    pr = node(n, STD, 'print', 640, 520)
    n.connectNodes(rd, ln, 'mol', 'atoms')
    n.connectNodes(ln, v, 'lines', 'geometries')
    n.connectNodes(v, pa, 'lastPick', 'pick')
    n.connectNodes(pa, st, 'residue', 'atoms')
    n.connectNodes(st, v, 'sticks', 'geometries')
    n.connectNodes(pa, pr, 'label', 'in1')
    save(n, 'pick_residue')


def spheres_colormap():
    n = new('spheres and a color map')
    ev = node(n, STD, 'eval', 30, 40)
    ev.inputPorts[0].widget.set("[[i, (i * 7) % 13 - 6, (i * 3) % 11 - 5] for i in range(-12, 13)]",
                                run=False)
    sp = node(n, VIZ, 'Spheres', 520, 40, radius=0.8)
    ix = node(n, STD, 'Generic', 260, 200)
    ix.rename('x values')
    ix.addInputPort(name='coords', datatype='None')
    ix.addOutputPort(name='values', datatype='None')
    ix.setFunction("def doit(self, coords):\n    self.outputData(values=[c[0] for c in coords])\n")
    cm = node(n, VIZ, 'Color Map', 260, 330, ramp='rainbow')
    ax = node(n, VIZ, 'axis', 520, 330)
    v = node(n, VIZ, 'Viewer', 800, 200)
    n.connectNodes(ev, sp, 0, 'coords')
    n.connectNodes(ev, ix, 0, 'coords')
    n.connectNodes(ix, cm, 'values', 'values')
    n.connectNodes(cm, sp, 'colors', 'colors')
    n.connectNodes(sp, v, 'spheres', 'geometries')
    n.connectNodes(ax, v, 'axis', 'geometries')
    save(n, 'spheres_colormap')


def helical_crambin():
    n = new('helical crambin')
    rd = node(n, MOL, 'Read Molecule', 30, 40, filename='data/1crn.pdb')
    hx = node(n, SYM, 'Helix', 30, 200, vector=[0., 0., 1.], point=[-15., -15., 0.],
              angle=30., hrise=12., copies=12)
    ca = node(n, MOL, 'Cartoon', 380, 60, colorBy='secondary structure')
    v = node(n, VIZ, 'Viewer', 700, 120)
    n.connectNodes(rd, ca, 'mol', 'atoms')
    n.connectNodes(hx, ca, 'outMatrices', 'instanceMatrices')
    n.connectNodes(ca, v, 'cartoon', 'geometries')
    save(n, 'helical_crambin')


def icosahedral_spheres():
    n = new('icosahedral spheres')
    ic = node(n, SYM, 'Icosahedral1', 30, 200)
    sp = node(n, VIZ, 'Spheres', 330, 40, radius=3.0)
    sp.inputPortByName['coords'].defaultValue = ((5., 3., 20.), (-4., 2., 21.))
    ev = node(n, STD, 'eval', 30, 40)
    ev.inputPorts[0].widget.set('[[5., 3., 20.], [-4., 2., 21.], [0., -5., 21.]]', run=False)
    v = node(n, VIZ, 'Viewer', 650, 120)
    n.connectNodes(ev, sp, 'result', 'coords')
    n.connectNodes(ic, sp, ic.outputPorts[0].name, 'instanceMatrices')
    n.connectNodes(sp, v, 'spheres', 'geometries')
    save(n, 'icosahedral_spheres')


def map_isosurface():
    n = new('map isosurface')
    rd = node(n, VOL, 'ReadAnyMap', 30, 60, filename='data/nwv1.mrc')
    iso = node(n, VOL, 'UTiso', 330, 30)
    sl = node(n, VOL, 'OrthoSlice', 330, 140, sliceNumber=12, opacity=0.8)
    bb = node(n, VOL, 'GridBB', 330, 420)
    st = node(n, VOL, 'VolumeStats', 30, 260)
    v = node(n, VIZ, 'Viewer', 700, 160)
    n.connectNodes(rd, iso, 'grid', 'UT-Isocontour_grid3D')
    n.connectNodes(rd, sl, 'grid', 'grid')
    n.connectNodes(rd, bb, 'grid', 'grid')
    n.connectNodes(rd, st, 'grid', st.inputPorts[0].name)
    n.connectNodes(iso, v, 'IndexedPolygons_indexedPolygons', 'geometries')
    n.connectNodes(sl, v, 'OrthoSlice', 'geometries')
    n.connectNodes(bb, v, 'Grid3DBB', 'geometries')
    save(n, 'map_isosurface')


def viewer_snapshot():
    n = new('viewer snapshot')
    rd = node(n, MOL, 'Read Molecule', 30, 40, filename='data/1crn.pdb')
    ca = node(n, MOL, 'Cartoon', 320, 40)
    v = node(n, VIZ, 'Viewer', 620, 60)
    gr = node(n, IMG, 'Grab Image', 620, 240)
    fl = node(n, IMG, 'Filter Image', 860, 240, filter='CONTOUR')
    sh = node(n, IMG, 'Show Image', 860, 380)
    n.connectNodes(rd, ca, 'mol', 'atoms')
    n.connectNodes(ca, v, 'cartoon', 'geometries')
    n.connectNodes(v, gr, 'viewer', 'viewer')
    n.connectNodes(gr, fl, 'image', 'image')
    n.connectNodes(fl, sh, 'image', 'image')
    save(n, 'viewer_snapshot')


def plots():
    n = new('plots')
    sin = node(n, MPL, 'SinFunc', 30, 40)
    rnd = node(n, MPL, 'RandNormDist', 30, 300)
    da = node(n, MPL, 'Draw Area', 30, 150)
    da.inputPortByName['title'].widget.set('sin(x)', run=False)
    pl = node(n, MPL, 'Plot', 330, 40, color='blue')
    hi = node(n, MPL, 'Histogram', 330, 300)
    fig = node(n, MPL, 'Figure', 660, 160, nbColumns=2, width=10.0, height=4.0)
    n.connectNodes(sin, pl, 'x', 'x')
    n.connectNodes(sin, pl, 'y', 'y')
    n.connectNodes(da, pl, da.outputPorts[0].name, 'drawAreaDef')
    n.connectNodes(rnd, hi, 'data', 'values')
    n.connectNodes(pl, fig, 'plot', 'plots')
    n.connectNodes(hi, fig, hi.outputPorts[0].name, 'plots')
    save(n, 'plots')


if __name__ == '__main__':
    crambin_surface()
    iterate_squares()
    pick_residue()
    spheres_colormap()
    helical_crambin()
    icosahedral_spheres()
    map_isosurface()
    viewer_snapshot()
    plots()
