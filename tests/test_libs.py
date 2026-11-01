# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The node libraries: every node instantiates; molecules, MSMS, viewer, picking."""
import os

from common import DATA, check, eq, net, outdir

from wewos.engine import Network, get_library

PDB = os.path.join(DATA, '1crn.pdb')


def _all_nodes(libname):
    lib = get_library(libname)
    n = Network('all')
    n.runOnNewData.value = False
    for cat, entries in lib.libraryDescr.items():
        for e in entries:
            n.addNode(lib.instantiate(label=e['label']))
    return n


def test_every_node_instantiates():
    for name in ('Standard', '3D Visualization', 'Molecules', 'SymServer', 'Volume', 'Imaging',
                 'MatPlotLib'):
        n = _all_nodes(name)
        check(len(n.nodes) > 5, name)


def test_spheres_scene_delta():
    vz = get_library('3D Visualization')
    v, s = vz.instantiate(label='Viewer'), vz.instantiate(label='Spheres')
    n = net(v, s)
    s.inputPortByName['radius'].widget.set(2.0, run=False)
    n.connectNodes(s, v, 'spheres', 'geometries')
    seq = n.bus.seq
    n.run(n.rootNodes)
    evs = [e for e in n.bus.since(seq)['events'] if e['kind'] == 'scene']
    check(evs and evs[-1]['changed'][0]['name'] == 'Spheres')
    g = v.geomsJSON()[0]
    eq(g['type'], 'spheres')
    eq(g['radius'], 2.0)
    # disconnecting removes it from the scene
    seq = n.bus.seq
    n.deleteConnections(list(v.inputPorts[0].connections))
    evs = [e for e in n.bus.since(seq)['events'] if e['kind'] == 'scene']
    check(evs and evs[-1]['removed'] == ['Spheres'])


def test_molecule_select_cpk():
    mk = get_library('Molecules')
    rd, sel, cpk = mk.instantiate(label='Read Molecule'), mk.instantiate(label='Select'), \
        mk.instantiate(label='CPK')
    n = net(rd, sel, cpk)
    rd.inputPorts[0].widget.set(PDB, run=False)
    sel.inputPortByName['selectionString'].widget.set('chain A and resnum 1 to 10', run=False)
    n.connectNodes(rd, sel, 'mol', 'nodes')
    n.connectNodes(sel, cpk, 'selection', 'atoms')
    n.run(n.rootNodes)
    eq(cpk.status, 'done')
    resnums = {int(l[22:26]) for l in cpk.geom.pdb.splitlines() if l.startswith('ATOM')}
    eq(resnums, set(range(1, 11)))
    eq(len(cpk.geom.atomIndices), sel.outputPortByName['numAtoms'].data)


def test_msms_surface():
    mk = get_library('Molecules')
    rd, ms = mk.instantiate(label='Read Molecule'), mk.instantiate(label='MSMS')
    n = net(rd, ms)
    rd.inputPorts[0].widget.set(PDB, run=False)
    n.connectNodes(rd, ms, 'mol', 'atoms')
    n.run(n.rootNodes)
    eq(ms.status, 'done')
    v = ms.outputPortByName['vertices'].data
    f = ms.outputPortByName['faces'].data
    check(len(v) > 1000 and len(f) > 2000 and f.max() < len(v))


def test_pick_runs_downstream():
    mk, vz = get_library('Molecules'), get_library('3D Visualization')
    rd, cpk, v, pa = (mk.instantiate(label='Read Molecule'), mk.instantiate(label='CPK'),
                      vz.instantiate(label='Viewer'), mk.instantiate(label='Picked Atom'))
    n = net(rd, cpk, v, pa)
    rd.inputPorts[0].widget.set(PDB, run=False)
    n.connectNodes(rd, cpk, 'mol', 'atoms')
    n.connectNodes(cpk, v, 'spheres', 'geometries')
    n.connectNodes(v, pa, 'lastPick', 'pick')
    n.run(n.rootNodes)
    v.picked({'geom': 'CPK', 'atom': {'index': 1}})
    eq(pa.outputPortByName['label'].data, 'A:THR1:CA')


def test_symserv_icosahedral_matrices():
    import numpy
    sym = get_library('SymServer')
    ic = sym.instantiate(label='Icosahedral1')
    n = net(ic)
    n.run(n.rootNodes)
    mats = numpy.array(ic.outputPorts[0].data)
    eq(mats.shape, (60, 4, 4))
    for m in mats:                          # proper rotations about the origin
        r = m[:3, :3]
        check(numpy.allclose(r @ r.T, numpy.identity(3), atol=1e-4))
        check(abs(numpy.linalg.det(r) - 1) < 1e-4)
        check(numpy.allclose(m[:3, 3], 0, atol=1e-4))
    # the 60 rotations are distinct
    keys = {tuple(numpy.round(m[:3, :3], 3).ravel()) for m in mats}
    eq(len(keys), 60)


def test_symserv_helix_instances_a_molecule():
    import numpy
    sym, mk, vz = get_library('SymServer'), get_library('Molecules'), get_library('3D Visualization')
    rd, hx, ca, v = (mk.instantiate(label='Read Molecule'), sym.instantiate(label='Helix'),
                     mk.instantiate(label='Cartoon'), vz.instantiate(label='Viewer'))
    n = net(rd, hx, ca, v)
    rd.inputPorts[0].widget.set(PDB, run=False)
    for k, val in (('vector', [0, 0, 1]), ('angle', 30.), ('hrise', 12.), ('copies', 5)):
        hx.inputPortByName[k].widget.set(val, run=False)
    n.connectNodes(rd, ca, 'mol', 'atoms')
    n.connectNodes(hx, ca, 'outMatrices', 'instanceMatrices')
    n.connectNodes(ca, v, 'cartoon', 'geometries')
    n.run(n.rootNodes)
    g = v.geomsJSON()[0]
    eq(len(g['instances']), 5)
    m2 = numpy.array(g['instances'][2]).reshape(4, 4)
    check(abs(m2[2, 3] - 24.0) < 1e-3, m2)   # two rises along z


def test_import_maps_symserv_nodes():
    from wewos.legacy import importer
    src = ('from symserv.VisionInterface.SymservNodes import symlib\n'
           'from symserv.VisionInterface.SymservNodes import Sym5FoldNE\n'
           'n = Sym5FoldNE(constrkw={}, name="5-fold", library=symlib)\n'
           'masterNet.addNode(n, 10, 10)\n'
           'n.inputPortByName["vector"].widget.set([0.0, 0.0, 1.0], run=False)\n')
    data, report = importer.import_source(src, 'sym_net.py')
    eq(report.unmapped, [])
    e = data['network']['nodes'][0]
    eq((e['lib'], e['cls']), ('SymServer', 'Sym5FoldNE'))


MRC = os.path.join(DATA, 'nwv1.mrc')


def test_volume_read_isocontour_slice_box():
    vol, vz = get_library('Volume'), get_library('3D Visualization')
    rd, iso, sl, bb, v = (vol.instantiate(label='ReadAnyMap'), vol.instantiate(label='UTiso'),
                          vol.instantiate(label='OrthoSlice'), vol.instantiate(label='GridBB'),
                          vz.instantiate(label='Viewer'))
    n = net(rd, iso, sl, bb, v)
    rd.inputPorts[0].widget.set(MRC, run=False)
    n.connectNodes(rd, iso, 'grid', 'UT-Isocontour_grid3D')
    n.connectNodes(rd, sl, 'grid', 'grid')
    n.connectNodes(rd, bb, 'grid', 'grid')
    for g, p in ((iso, 'IndexedPolygons_indexedPolygons'), (sl, 'OrthoSlice'), (bb, 'Grid3DBB')):
        n.connectNodes(g, v, p, 'geometries')
    n.run(n.rootNodes)
    check(all(x.status == 'done' for x in n.allNodes()), {x.name: x.status for x in n.allNodes()})
    shapes = {g['name']: (g['type'], g['vertices']['shape'][0]) for g in v.geomsJSON()}
    eq(shapes['IndexedPolygons'][0], 'mesh')
    check(shapes['IndexedPolygons'][1] > 1000)
    eq(shapes['OrthoSlice'], ('mesh', 21 * 22))     # one vertex per grid point of z=0
    eq(shapes['GridBB'], ('lines', 8))
    isoN = iso.macroNetwork.nodes[2]
    w = isoN.inputPortByName['isovalue'].widget
    check(w.options['min'] < 1.0 < w.options['max'])
    isoN.calculateSignatures()
    eq(len(w.options['signatures']), 4)


def test_volume_coarse_molecular_surface():
    vol, mk = get_library('Volume'), get_library('Molecules')
    rd, cm = mk.instantiate(label='Read Molecule'), vol.instantiate(label='CoarseMolSurf')
    n = net(rd, cm)
    rd.inputPorts[0].widget.set(PDB, run=False)
    n.connectNodes(rd, cm, 'mol', cm.inputPorts[0].name)
    n.run(n.rootNodes)
    g = cm.outputPorts[0].data
    check(len(g.vertices) > 1000 and len(g.faces) > 2000, g)


def test_imaging_read_filter_show():
    img = get_library('Imaging')
    rd, fl, inv, sh = (img.instantiate(label='Read Image'), img.instantiate(label='Filter Image'),
                       img.instantiate(label='Invert Image'), img.instantiate(label='Show Image'))
    n = net(rd, fl, inv, sh)
    rd.inputPorts[0].widget.set(os.path.join(DATA, 'gradient.png'), run=False)
    fl.inputPortByName['filter'].widget.set('EMBOSS', run=False)
    n.connectNodes(rd, fl, 'image', 'image')
    n.connectNodes(fl, inv, 'image', 'image')
    n.connectNodes(inv, sh, 'image', 'image')
    seq = n.bus.seq
    n.run(n.rootNodes)
    check(all(x.status == 'done' for x in n.nodes), {x.name: x.status for x in n.nodes})
    check(any(e['kind'] == 'image' for e in n.bus.since(seq)['events']))
    d = sh.imageData()
    eq(d['size'], [96, 64])
    check(d['png'].startswith('data:image/png;base64,'))


def test_matplotlib_plots_figure_and_save():
    L = get_library('MatPlotLib')
    sin, rnd, plot, hist, fig, save = (L.instantiate(label=x) for x in (
        'SinFunc', 'RandNormDist', 'Plot', 'Histogram', 'Figure', 'SaveFig'))
    n = net(sin, rnd, plot, hist, fig, save)
    n.connectNodes(sin, plot, 'x', 'x')
    n.connectNodes(sin, plot, 'y', 'y')
    n.connectNodes(rnd, hist, 'data', 'values')
    n.connectNodes(plot, fig, 'plot', 'plots')
    n.connectNodes(hist, fig, hist.outputPorts[0].name, 'plots')
    n.connectNodes(fig, save, 'figure', 'figure')
    path = os.path.join(outdir('mpl'), 'figure.png')
    save.inputPortByName['fname'].widget.set(path, run=False)
    seq = n.bus.seq
    n.run(n.rootNodes)
    check(all(x.status == 'done' for x in n.nodes), {x.name: x.status for x in n.nodes})
    shown = {e['node'] for e in n.bus.since(seq)['events'] if e['kind'] == 'image'}
    check({plot.id, hist.id, fig.id} <= shown, shown)
    eq(len(fig.figure.axes), 2)
    check(os.path.getsize(path) > 1000)
    d = plot.imageData()
    check(d['png'].startswith('data:image/png;base64,') and d['size'][0] > 100)


def test_matplotlib_multiplot_and_colorbar():
    L = get_library('MatPlotLib')
    sin, plot, scat, multi, mesh, biv, cont, cb = (L.instantiate(label=x) for x in (
        'SinFunc', 'Plot', 'Scatter', 'MultiPlot', 'MeshGrid', 'BivariateNormal', 'Contour',
        'ColorBar'))
    n = net(sin, plot, scat, multi, mesh, biv, cont, cb)
    c = n.connectNodes
    c(sin, plot, 'x', 'x'); c(sin, plot, 'y', 'y')
    c(sin, scat, 'x', 'x'); c(sin, scat, 'y', 'y')
    c(plot, multi, 'plot', 'multiplot'); c(scat, multi, scat.outputPorts[0].name, 'multiplot')
    c(sin, mesh, 'x', 'x'); c(sin, mesh, 'x', 'y')
    c(mesh, biv, 'X', 'arraylist1'); c(mesh, biv, 'Y', 'arraylist2')
    c(biv, cont, biv.outputPorts[0].name, 'arraylistz')
    c(cont, cb, 'axes', 'plot'); c(cont, cb, 'contour', 'current_image')
    n.run(n.rootNodes)
    check(all(x.status == 'done' for x in n.nodes), {x.name: x.status for x in n.nodes})
    eq(len(multi.axes.lines), 1)
    eq(len(multi.axes.collections), 1)
    eq(len(cont.figure.axes), 2)              # the plot and its color bar


def test_viewer_silhouettes_and_fog():
    from wewos.engine import fileio
    from wewos.libs.viz3d import RENDERING
    vz = get_library('3D Visualization')
    v = vz.instantiate(label='Viewer')
    n = net(v)
    eq(v.sceneState()['rendering'], RENDERING)           # on by default
    check(RENDERING['outline'] and RENDERING['fog'])
    eq(v.getStateForSaving(), {})                         # defaults are not saved
    seq = n.bus.seq
    v.setRendering(fog=False, outlineWidth=3, fogEnd='1.5')
    evs = [e for e in n.bus.since(seq)['events'] if e['kind'] == 'viewer']
    eq(evs[-1]['op'], 'rendering')
    eq(evs[-1]['rendering']['fog'], False)
    eq(v.rendering['outlineWidth'], 3.0)
    eq(v.rendering['fogEnd'], 1.5)
    try:
        v.setRendering(shadows=True)
        check(False, 'an unknown option was accepted')
    except ValueError as e:
        check('shadows' in str(e))
    # saved with the network
    n2 = Network('copy')
    fileio.from_dict(n2, fileio.to_dict(n))
    v2 = n2.nodes[0]
    eq(v2.rendering, v.rendering)
