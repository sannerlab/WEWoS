# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The node libraries: every node instantiates; molecules, MSMS, viewer, picking."""
import os

from common import DATA, check, eq, net

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
    for name in ('Standard', '3D Visualization', 'Molecules', 'SymServer'):
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
