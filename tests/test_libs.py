# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The node libraries: every node instantiates; molecules, MSMS, viewer, picking."""
import os

from common import DATA, check, eq, net, outdir, requires

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


@requires('MolKit2')
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


@requires('MolKit2', 'mslib')
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


@requires('MolKit2')
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



@requires('MolKit2', 'matplotlib')
def test_contacts_example_pick_drives_the_analysis():
    """examples/contacts: clicking the inhibitor of 1HSG runs the Python node
    that finds the residues within the cutoff; they become sticks, labels, a
    bar plot and contacts.csv; turning the cutoff dial runs it again."""
    import json
    import shutil
    from wewos.engine import Network, fileio
    ex = os.path.join(os.path.dirname(DATA), '..', 'examples')
    d = outdir('contacts')
    shutil.copytree(os.path.join(ex, 'data'), os.path.join(d, 'data'))
    n = Network('contacts', workdir=d)
    with open(os.path.join(ex, 'contacts.wnet.json')) as fh:
        eq(fileio.from_dict(n, json.load(fh)), [])
    n.run(list(n.rootNodes))
    node = {x.name: x for x in n.nodes}
    node['Viewer'].picked({'geom': 'Sticks', 'atom': {'index': 0}})     # an MK1 atom
    eq(node['Picked Atom'].outputPortByName['label'].data.split(':')[1][:3], 'MK1')
    eq({x.name: x.status for x in n.allNodes() if x.status != 'done'}, {})
    names = node['residues near the pick'].outputPortByName['names'].data
    eq(names[:2], ['ASP25 B', 'ASP25 A'])          # the catalytic aspartates
    eq(len(names), 26)
    with open(os.path.join(d, 'contacts.csv')) as fh:
        rows = fh.read().splitlines()
    eq(rows[:2], ['residue,min_distance_A', 'ASP25 B,2.63'])
    node['cutoff'].inputPorts[0].widget.set(3.0)
    eq(node['residues near the pick'].outputPortByName['names'].data, ['ASP25 B', 'ASP25 A'])


@requires('MolKit2')
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


@requires('UTpackages')
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


@requires('MolKit2', 'UTpackages')
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


def test_viewer_renderer_and_molstar_settings():
    from wewos.engine import fileio
    vz = get_library('3D Visualization')
    v = vz.instantiate(label='Viewer')
    n = net(v)
    eq(v.sceneState()['renderer'], '3dmol')                  # the default
    eq(v.getStateForSaving(), {})
    seq = n.bus.seq
    v.setRenderer('molstar')
    evs = [e for e in n.bus.since(seq)['events'] if e['kind'] == 'viewer']
    eq((evs[-1]['op'], evs[-1]['renderer']), ('renderer', 'molstar'))
    try:
        v.setRenderer('jmol')
        check(False, 'an unknown renderer was accepted')
    except ValueError as e:
        check('jmol' in str(e))
    v.setView([1, 2, 3], '3dmol')
    v.setView({'mode': 'perspective', 'radius': 30}, 'molstar')
    v.setMolstarSettings({'postprocessing': {'shadow': {'name': 'on', 'params': {'steps': 1}}}})
    st = v.sceneState()
    eq(st['camera'], [1, 2, 3])
    eq(st['cameras']['molstar']['radius'], 30)
    eq(st['molstar']['postprocessing']['shadow']['name'], 'on')
    # saved with the network
    n2 = Network('copy')
    fileio.from_dict(n2, fileio.to_dict(n))
    v2 = n2.nodes[0]
    eq((v2.renderer, v2.camera, v2.cameras, v2.molstarCanvas),
       (v.renderer, v.camera, v.cameras, v.molstarCanvas))
    # a viewer saved before there was a renderer choice opens in 3Dmol
    v2.setStateFromSaving({'camera': [4, 5, 6]})
    eq((v2.renderer, v2.camera, v2.cameras, v2.molstarCanvas), ('3dmol', [4, 5, 6], {}, None))


BIOMT_PDB = """REMARK 350 BIOMOLECULE: 1
REMARK 350 APPLY THE FOLLOWING TO CHAINS: A, B
REMARK 350   BIOMT1   1  1.000000  0.000000  0.000000        0.00000
REMARK 350   BIOMT2   1  0.000000  1.000000  0.000000        0.00000
REMARK 350   BIOMT3   1  0.000000  0.000000  1.000000        0.00000
REMARK 350   BIOMT1   2 -1.000000  0.000000  0.000000       10.00000
REMARK 350   BIOMT2   2  0.000000 -1.000000  0.000000        0.00000
REMARK 350   BIOMT3   2  0.000000  0.000000  1.000000        0.00000
REMARK 350 BIOMOLECULE: 2
REMARK 350 APPLY THE FOLLOWING TO CHAINS: A
REMARK 350   BIOMT1   1  1.000000  0.000000  0.000000        0.00000
REMARK 350   BIOMT2   1  0.000000  1.000000  0.000000        0.00000
REMARK 350   BIOMT3   1  0.000000  0.000000  1.000000        0.00000
"""


@requires('MolKit2', 'UTpackages')
def test_assembly_matrices_and_surface_copies():
    import base64
    import numpy
    from wewos.libs.molecules import biomt_matrices
    path = os.path.join(outdir('biomt'), 'biomt.pdb')
    with open(path, 'w') as fh:
        fh.write(BIOMT_PDB)
    mats, chains = biomt_matrices(path)
    eq((len(mats), chains), (2, ['A', 'B']))
    check(numpy.allclose(mats[1][0], [-1, 0, 0, 10]))
    eq(len(biomt_matrices(path, 2)[0]), 1)
    # the node, from a file name; then CoarseMolSurf copies its surface
    mk, vol, vz = (get_library(x) for x in ('Molecules', 'Volume', '3D Visualization'))
    am, rd = mk.instantiate(label='Assembly Matrices'), mk.instantiate(label='Read Molecule')
    cm, v = vol.instantiate(cls='CoarseMolSurf'), vz.instantiate(label='Viewer')
    ev = get_library('Standard').instantiate(label='eval')
    n = net(ev, am, rd, cm, v)
    ev.inputPorts[0].widget.set(repr(path), run=False)          # the file name
    n.connectNodes(ev, am, 'result', 'mol')
    rd.inputPortByName['filename'].widget.set(os.path.join(DATA, '1crn.pdb'), run=False)
    eq([p.name for p in cm.inputPorts], ['UT_Blur_molFrag', 'IndexedPolygons_instanceMatrices'])
    check(not cm.inputPorts[1].required)
    n.connectNodes(rd, cm, 'mol', cm.inputPorts[0].name)
    n.connectNodes(am, cm, 'matrices', cm.inputPorts[1].name)
    n.connectNodes(cm, v, cm.outputPorts[0].name, 'geometries')
    n.run(n.rootNodes)
    g = v.geomsJSON()[0]
    eq(g['type'], 'mesh')
    eq(len(g['instances']), 2)                        # sent once, with its copies
    nv = len(base64.b64decode(g['vertices']['b64'])) // 12
    eq(nv, len(base64.b64decode(g['normals']['b64'])) // 12)
    check(nv > 100)
    eq(g['instances'][1][3], 10.0)                    # row-major, translation last column
    # without matrices the macro still runs, and draws one surface
    n.deleteConnections(list(cm.inputPorts[1].connections))
    n.run([rd])
    check('instances' not in v.geomsJSON()[0])


def test_capsid_example_loads():
    import json
    with open(os.path.join(os.path.dirname(DATA), '..', 'examples', 'capsid_surface.wnet.json')) as fh:
        d = json.load(fh)
    n = Network('capsid')
    from wewos.engine import fileio
    eq(fileio.from_dict(n, d), [])
    cm = [x for x in n.nodes if x.__class__.__name__ == 'CoarseMolSurf'][0]
    eq([c.port1.node.name for c in cm.inputPorts[1].connections], ['Assembly Matrices'])
    v = [x for x in n.nodes if x.__class__.__name__ == 'Viewer'][0]
    eq(v.renderer, 'molstar')
    blur = [x for x in cm.macroNetwork.nodes if x.name == 'UT Blur'][0]
    eq(blur.inputPortByName['Xdim'].widget.get(), 48)


def test_vision_examples_run():
    """Every example converted from MGLTools Vision runs (each in a copy of
    its group's data); see examples/make_vision_examples.py."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(DATA), '..', 'examples'))
    import make_vision_examples as mve
    here = os.path.join(os.path.dirname(DATA), '..', 'examples')
    n = 0
    molecules = _imports('MolKit2', 'mslib')
    for group in ('vision', 'vision_matplotlib'):
        folder = os.path.join(here, group)
        for f in sorted(os.listdir(folder)):
            if f.endswith('.wnet.json'):
                if not molecules and 'Molecules' in _libraries(os.path.join(folder, f)):
                    continue        # MolKit2 and mslib come with the ADCP environment
                res = mve.run(os.path.join(folder, f), folder)
                check(res.startswith('ran'), (f, res))
                n += 1
    check(n >= (45 if molecules else 43), n)


def _imports(*modules):
    import importlib
    try:
        for m in modules:
            importlib.import_module(m)
        return True
    except Exception:
        return False


def _libraries(path):
    import json
    with open(path) as fh:
        return json.load(fh).get('libraries', [])


@requires('MolKit2', 'mslib')
def test_viper_figure_nodes():
    """The nodes the ViPEr paper's figure 1 needs: MolKit radii, property
    expressions, MSMS with radii and its triangles, CPK with radii and colors,
    a color map, and One Redraw firing the node on its trigger."""
    import numpy
    mk, vz, std = (get_library(x) for x in ('Molecules', '3D Visualization', 'Standard'))
    rd, ar, ap, ax = (mk.instantiate(label=x) for x in ('Read Molecule', 'Assign Radii',
                                                         'Extract Atom Property', 'Extract Atom Property'))
    ms, tri = mk.instantiate(label='MSMS'), mk.instantiate(label='MSMS triang.')
    cpk, poly, cm = mk.instantiate(label='CPK'), vz.instantiate(label='IndPolygons'), vz.instantiate(label='Color Map')
    v, one, pr = vz.instantiate(label='Viewer'), vz.instantiate(label='One Redraw'), std.instantiate(label='Pass')
    n = net(rd, ar, ap, ax, ms, tri, cpk, poly, cm, v, one, pr)
    rd.inputPortByName['filename'].widget.set(os.path.join(DATA, '1crn.pdb'), run=False)
    ap.inputPortByName['propertyName'].widget.set('radius', run=False)
    ax.inputPortByName['propertyName'].widget.set('coords[0]', run=False)
    for a, b, p1, p2 in ((rd, ar, 'mol', 'atoms'), (ar, ap, 'atoms', 'atoms'), (ar, ax, 'atoms', 'atoms'),
                         (ar, ms, 'atoms', 'atoms'), (ap, ms, 'propertyValues', 'radii'),
                         (ms, tri, 'surface', 'MSMS'), (tri, poly, 'vertices', 'coords'),
                         (tri, poly, 'indices', 'indices'), (tri, poly, 'vnormals', 'vnormals'),
                         (ax, cm, 'propertyValues', 'values'), (ar, cpk, 'atoms', 'atoms'),
                         (ap, cpk, 'propertyValues', 'radii'), (cm, cpk, 'colors', 'colors'),
                         (cpk, v, 'spheres', 'geometries'), (poly, v, 'indexedPolygons', 'geometries'),
                         (v, one, 'redraw', 'trigger')):
        n.connectNodes(a, b, p1, p2)
    n.specialConnectNodes(one, pr, 'trigger', 'runNode')
    n.run(n.rootNodes)
    bad = [(x.name, x.status) for x in n.nodes if x.status != 'done' and x is not pr]
    eq(bad, [])
    # MolKit's united radii (MSMS's table): N 1.70, CA 2.00, C 1.74 for crambin's first residue
    r = ar.outputPortByName['radii'].data
    check(numpy.allclose(r[:3], [1.70, 2.00, 1.74]), r[:4])
    x = ax.outputPortByName['propertyValues'].data
    eq(len(x), 327)
    g = {d['name']: d for d in v.geomsJSON()}
    eq(g['CPK']['type'], 'spheres')                      # radii given: spheres of those radii
    check('radii' in g['CPK'] and 'colors' in g['CPK'])
    check(any(d['type'] == 'mesh' for d in g.values()), list(g))
    # One Redraw's trigger ran Pass (which stops: nothing feeds its input); never run, it would be idle
    check(pr.status in ('done', 'stopped'), pr.status)


def test_colormaps_vision_files_and_mapping():
    import numpy
    from wewos import colormaps
    from wewos.libs.viz3d import colormap
    # a Vision colormap file, with numpy arrays as MGLTools wrote them; never run
    text = ("from DejaVu.colorMap import ColorMap\nfrom numpy import array\n"
            "cm = ColorMap('bw')\n"
            "cfg = {'name': 'bw', 'ramp': array([[0., 0., 1., 1.], [1., 1., 1., 1.], [1., 0., 0., 1.]], 'f'),"
            " 'mini': 0.0, 'maxi': 10.0}\n"
            "apply( cm.configure, (), cfg)\nimport os; os.remove('/nonexistent')\n")
    cm = colormaps.read_vision(text)
    eq((cm['name'], len(cm['ramp']), cm['mini'], cm['maxi']), ('bw', 3, 0.0, 10.0))
    eq(colormaps.read_vision(colormaps.write_vision(cm)), cm)          # round trip
    # the ramp's own range is used unless mini/maxi are given
    eq(colormap([0, 5, 10], cm).round(3).tolist(), [[0, 0, 1], [1, 1, 1], [1, 0, 0]])
    eq(colormap([5], cm, mini=5, maxi=15).round(3).tolist(), [[0, 0, 1]])
    # transparency gives RGBA colors; presets and plain lists still work
    c = colormap([0, 1], {'ramp': [[1, 0, 0, .25], [0, 0, 1, 1]]})
    eq(c.shape, (2, 4)); check(abs(c[0, 3] - .25) < 1e-6)
    eq(colormap([0, 1], 'grey').tolist(), [[0, 0, 0], [1, 1, 1]])
    eq(colormap([0, 1], [[1, 0, 0], [0, 1, 0]]).tolist(), [[1, 0, 0], [0, 1, 0]])
    # a widget value is cleaned (Vision's value carries widget settings too)
    eq(colormaps.normalize({'ramp': [[2, -1, 0.5]], 'mini': 'x', 'labelGridCfg': {}, 'name': 3}),
       {'ramp': [[1.0, 0.0, 0.5, 1.0]], 'mini': None, 'name': '3'})
    try:
        colormaps.read_vision('x = 1\n')
        check(False, 'not a colormap file, but read')
    except ValueError:
        pass


def test_color_map_node_takes_an_edited_ramp():
    vz, std = get_library('3D Visualization'), get_library('Standard')
    ev, cm = std.instantiate(label='eval'), vz.instantiate(label='Color Map')
    n = net(ev, cm)
    ev.inputPorts[0].widget.set('[0, 10]', run=False)
    n.connectNodes(ev, cm, 'result', 'values')
    eq(cm.inputPortByName['ramp'].widget.spec()['kind'], 'colormap')
    cm.inputPortByName['ramp'].widget.set({'ramp': [[0, 1, 0, 1], [1, 0, 1, 1]], 'name': 'gm'}, run=False)
    n.run(n.rootNodes)
    eq(cm.outputPortByName['colors'].data.tolist(), [[0, 1, 0], [1, 0, 1]])


def test_color_map_table_ramp_is_looked_up_as_in_vision():
    """A ramp given as a table (Vision's color maps) maps a value to entry
    int((v - mini) * n / (maxi - mini)), as DejaVu's ColorMap.Map did; a
    preset name stays a smooth ramp."""
    from wewos.libs.viz3d import colormap
    ramp = {'ramp': [[i / 15., 0, 0, 1] for i in range(16)]}
    c = colormap([0.0, 0.03, 0.5, 0.99, 1.0], ramp, 0.0, 1.0)
    eq([round(float(x), 4) for x in c[:, 0]], [0.0, 0.0, round(8 / 15., 4), 1.0, 1.0])
    eq(round(float(colormap([0.5], 'grey', 0, 1)[0, 0]), 3), 0.5)


def test_color_map_legend():
    from wewos.engine import fileio
    vz, std = get_library('3D Visualization'), get_library('Standard')
    ev, cm, v = std.instantiate(label='eval'), vz.instantiate(label='Color Map'), vz.instantiate(label='Viewer')
    n = net(ev, cm, v)
    ev.inputPorts[0].widget.set('[2, 5, 9]', run=False)
    n.connectNodes(ev, cm, 'result', 'values')
    n.connectNodes(cm, v, 'legend', 'geometries')
    cm.inputPortByName['ramp'].widget.set({'ramp': [[0, 0, 1, 1], [1, 0, 0, 1]], 'name': 'temp', 'maxi': 20}, run=False)
    n.run(n.rootNodes)
    g = v.geomsJSON()[0]
    eq((g['type'], g['title'], g['mini'], g['maxi'], len(g['ramp'])), ('legend', 'temp', 2.0, 20.0, 2))
    # its place and look are kept by the viewer, with the network
    v.setLegend(g['name'], {'x': 0.1, 'y': 0.8, 'vertical': False, 'labels': 3, 'junk': 1})
    eq(v.legends[g['name']], {'x': 0.1, 'y': 0.8, 'vertical': False, 'labels': 3})
    n2 = Network('copy')
    fileio.from_dict(n2, fileio.to_dict(n))
    v2 = [x for x in n2.nodes if x.__class__.__name__ == 'Viewer'][0]
    eq(v2.legends, v.legends)
    v.setLegend(g['name'], None)
    eq(v.legends, {})


def test_geometry_state_color_and_theme_lines():
    # a color kept with the network is set first; colors given to the node win
    from wewos import geom as G
    from wewos.engine import get_library
    viz = get_library('3D Visualization')
    net = Network('t')
    net.runOnNewData.value = False
    s = viz.instantiate(label='Spheres')
    net.addNode(s, 0, 0)
    s.setStateFromSaving({'geomState': {'color': [1.0, 0.5, 0.0]}})
    s.update({'vertices': [[0., 0., 0.]]})
    eq(list(s.geom.color), [1.0, 0.5, 0.0])
    s.update({'vertices': [[0., 0., 0.]], 'colors': [[0., 0., 1.]]})
    eq(list(s.geom.color), [0.0, 0.0, 1.0])
    eq(s.getStateForSaving(), {'geomState': {'color': [1.0, 0.5, 0.0]}})
    # lines given no color are drawn in the page's theme color
    ln = G.IndexedPolylines('box', vertices=[[0., 0., 0.], [1., 0., 0.]], faces=[[0, 1]])
    check(ln.to_json().get('defaultColor') is True)
    ln.Set(colors=[[1., 0., 0.]])
    check('defaultColor' not in ln.to_json())


def test_filter_image_waits_for_a_filter():
    from PIL import Image
    from wewos.engine import get_library
    net = Network('t')
    net.runOnNewData.value = False
    f = get_library('Imaging').instantiate(label='Filter Image')
    net.addNode(f, 0, 0)
    stat = f.dynamicComputeFunction(f, Image.new('RGB', (8, 8)), None)       # no filter yet: nothing, no error
    check(stat is None)
    f.dynamicComputeFunction(f, Image.new('RGB', (8, 8)), 'CONTOUR')
    eq(f.outputPortByName['image'].data.size, (8, 8))


def test_palette_carries_full_node_documentation_for_search():
    # the palette searches node docs too: the first paragraph is the
    # tooltip, the whole docstring (when longer) is sent for the search
    from wewos.engine import get_library
    d = get_library('Standard').describe()
    nodes = {n['label']: n for c in d['categories'] for n in c['nodes']}
    fl = nodes['Filelist']
    check('wildcards' in fl['fullDoc'].lower() and len(fl['fullDoc']) > len(fl['doc']))
    check(all('fullDoc' not in n or len(n['fullDoc']) > len(n['doc']) for n in nodes.values()))
