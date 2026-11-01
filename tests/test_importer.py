# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Importing Vision *_net.py networks (tests/data holds a few real ones)."""
import os

from common import DATA, check, eq

from wewos.engine import Network, fileio
from wewos.legacy import importer, py2to3


def _load(name):
    data, report = importer.import_file(os.path.join(DATA, name))
    net = Network('imported')
    problems = fileio.from_dict(net, data)
    return net, data, report, problems


def test_cpk_net_maps_completely():
    net, data, report, problems = _load('cpk_net.py')
    eq(problems, [])
    eq(report.unmapped, [])
    eq(sorted(n.__class__.__name__ for n in net.nodes), ['AtomsAsCPK', 'ReadMolecule', 'Viewer'])
    eq(len(net.connections), 2)
    rd = [n for n in net.nodes if n.name == 'Read Molecule'][0]
    eq(rd.inputPortByName['filename'].widget.get(), 'cv.pdb')


def test_unsupported_nodes_become_placeholders():
    src = ('from NoSuchPackage.Nodes import mylib\n'
           'from NoSuchPackage.Nodes import Thing\n'
           'from Vision.StandardNodes import stdlib\n'
           'from Vision.StandardNodes import Pass\n'
           't = Thing(constrkw={}, name="thing", library=mylib)\n'
           'masterNet.addNode(t, 10, 10)\n'
           'p = Pass(constrkw={}, name="Pass", library=stdlib)\n'
           'masterNet.addNode(p, 10, 80)\n'
           'masterNet.connectNodes(t, p, "out", "in1", blocking=True)\n')
    data, report = importer.import_source(src, 'x_net.py')
    net = Network('imported')
    eq(fileio.from_dict(net, data), [])
    eq(len(report.unmapped), 1)
    eq([n.__class__.__name__ for n in net.nodes], ['UnsupportedNode', 'Pass'])
    eq(len(net.connections), 1)


def test_coraliso_imports_with_volume():
    net, data, report, problems = _load('coralIso_net.py')
    eq(problems, [])
    eq(report.unmapped, [])
    m = [n for n in net.nodes if n.__class__.__name__ == 'UT_Iso'][0]
    iso = m.macroNetwork.nodes[2]
    check(abs(iso.inputPortByName['isovalue'].widget.get() - 11.954) < 1e-3)


def test_generic_nodes_keep_ports_and_code():
    net, data, report, problems = _load('send-multiple-sin-packet_net.py')
    eq(problems, [])
    pp = [n for n in net.nodes if n.name == 'Packet Packer'][0]
    eq([p.name for p in pp.inputPorts], ['audio_data', 'data_sync_index', 'signal_amplitude'])
    eq([p.name for p in pp.outputPorts], ['out0'])
    check(pp.codeModified and 'def doit(self, audio_data' in pp.sourceCode)
    check('Packet Packer' in report.code)
    compile(pp.sourceCode, 'x', 'exec')        # converted to Python 3


def test_standard_network_runs_after_import():
    net, data, report, problems = _load('loop_net.py')
    eq(problems, [])
    w = [n for n in net.nodes if n.name == 'while'][0]
    eq(w.inputPortByName['condition'].widget.get(), 'val1==0.0')


def test_import_never_executes_the_file():
    src = ('import os\nos.system("touch SHOULD_NOT_EXIST")\n'
           'from Vision.StandardNodes import stdlib\n'
           'from Vision.StandardNodes import Pass\n'
           'p = Pass(constrkw={}, name="Pass", library=stdlib)\n'
           'masterNet.addNode(p, 10, 10)\n')
    data, report = importer.import_source(src, 'evil_net.py')
    check(not os.path.exists('SHOULD_NOT_EXIST'))
    eq(len(data['network']['nodes']), 1)


def test_py2_code_strings_converted():
    code = "def doit(self, x):\n\tprint x\n\tif d.has_key('a'): apply(f, (1,))\n"
    new, changed = py2to3.convert_code(code)
    check(changed)
    compile(new, 'x', 'exec')
    check("'a' in d" in new and 'print(x)' in new, new)


def _left_to_right(net, loops_ok=False):
    """Links go from left to right (but loop-closing ones) and nodes do not overlap."""
    from wewos.engine.layout import node_geometry
    geo = {id(n): node_geometry(n.describe()) for n in net.nodes}
    for c in net.connections:
        a, b = c.port1.node, c.port2.node
        if loops_ok and not c.blocking:
            continue
        check(a.posx + geo[id(a)]['w'] < b.posx, '%s is not left of %s' % (a.name, b.name))
    for i, a in enumerate(net.nodes):
        for b in net.nodes[i + 1:]:
            ga, gb = geo[id(a)], geo[id(b)]
            check(not (a.posx < b.posx + gb['w'] and b.posx < a.posx + ga['w'] and
                       a.posy < b.posy + gb['h'] and b.posy < a.posy + ga['h']),
                  '%s overlaps %s' % (a.name, b.name))


def test_icos_macro_matrices_reach_the_cpk_macro():
    # Vision's CPK Macro exposed its spheres' instanceMatrices as a macro port
    net, data, report, problems = _load('icos_net.py')
    eq(problems, [])
    cpk = [n for n in net.nodes if n.name == 'CPK Macro'][0]
    eq([c.port1.node.name for c in cpk.inputPortByName['instanceMatrices'].connections],
       ['Icosahedral1'])
    eq([c.port1.node.name for c in cpk.inputPortByName['atoms'].connections], ['Read Molecule'])


def test_imported_networks_and_library_macros_flow_left_to_right():
    net, data, report, problems = _load('icos_net.py')
    eq(data['network']['layout'], 'vision')
    _left_to_right(net)
    ic = [n for n in net.nodes if n.name == 'Icosahedral1'][0]
    _left_to_right(ic.macroNetwork)
    m = ic.macroNetwork
    check(m.ipNode.posx <= min(n.posx for n in m.nodes))      # in the first column
    check(m.opNode.posx > max(n.posx for n in m.nodes if n is not m.opNode))
    net, data, report, problems = _load('loop_net.py')
    _left_to_right(net, loops_ok=True)
    # saving drops the flag: the positions are WEWoS's from then on
    check('layout' not in fileio.to_dict(net)['network'])


def test_old_code_none_tests_pil_imports_and_signatures():
    from wewos.legacy.importer import fit_signature
    new, changed = py2to3.convert_code(
        'def doit(self, x, y):\n    import Image\n    if x==None or y != None:  # x==None\n'
        '        s = "a == None"\n')
    check(changed)
    check('from PIL import Image' in new)
    check('if x is None or y is not None:  # x==None' in new)       # comments and strings kept
    check('"a == None"' in new)
    # an older Eval code takes fewer arguments than the node has ports
    eq(fit_signature('def doit(self, command, in1):\n    return 1\n', ['command', 'importString', 'in1']),
       'def doit(self, command, importString, in1):\n    return 1\n')
    code = 'def doit(self, a, zz):\n    pass\n'                       # not a subset: kept as is
    eq(fit_signature(code, ['a', 'b']), code)


def test_matplotlib_classic_nodes_and_old_port_names():
    from wewos.legacy import classmap
    eq(classmap.lookup('Vision.matplotlibNodes', 'ScatterClassicNE')[:2], ('MatPlotLib', 'ScatterNE'))
    eq(classmap.lookup('Vision.matplotlibNodes', 'Spy2NE')[:2], ('MatPlotLib', 'SpyNE'))
    lib, cls, inmap, outmap = classmap.lookup('Vision.matplotlibNodes', 'TablePlotNE')
    eq(classmap.map_port(inmap, 'rowlabels'), 'rowLabels')


def test_saved_viewer_opacity_and_unknown_settings():
    src = ('from DejaVu.VisionInterface.DejaVuNodes import vizlib\n'
           'from DejaVu.VisionInterface.GeometryNodes import IndexedPolygonsNE\n'
           'from DejaVu.VisionInterface.DejaVuNodes import ColorMapNE\n'
           'p = IndexedPolygonsNE(constrkw={}, name="surf", library=vizlib)\n'
           'masterNet.addNode(p, 10, 10)\n'
           'p.inputPortByName["geoms"].widget.set("surf", run=False)\n'
           'c = ColorMapNE(constrkw={}, name="Color Map", library=vizlib)\n'
           'masterNet.addNode(c, 10, 90)\n'
           'c.inputPortByName["colorMap"].widget.set({"mini": 0}, run=False)\n'
           'c.inputPortByName["filename"].widget.set("my_map.py", run=False)\n'
           'def loadSavedStates_Viewer_1(self=None, event=None):\n'
           '    obj = self.vi.FindObjectByName("root|surf")\n'
           '    if obj:\n'
           '        state = {"opacity": [0.5], "shininess": [50.0]}\n'
           '        apply(obj.materials[GL.GL_FRONT].Set, (), state)\n'
           '        state = {"opacity": [1.0]}\n'
           '        apply(obj.materials[GL.GL_BACK].Set, (), state)\n')
    data, report = importer.import_source(src, 'x_net.py')
    nodes = {e['name']: e for e in data['network']['nodes']}
    eq(nodes['surf']['widgets']['opacity'], 0.5)           # the front material
    eq((nodes['Color Map']['lib'], nodes['Color Map']['cls']), ('3D Visualization', 'ColorMap'))
    check('ramp' in nodes['Color Map']['widgets'])                    # the color map is kept
    check('filename' not in nodes['Color Map']['widgets'])            # no such input here
    check(any('filename' in w for w in report.warnings))


def test_vision_color_map_keeps_its_ramp():
    src = ('from DejaVu.VisionInterface.DejaVuNodes import vizlib\n'
           'from DejaVu.VisionInterface.DejaVuNodes import ColorMapNE\n'
           'c = ColorMapNE(constrkw={}, name="Color Map", library=vizlib)\n'
           'masterNet.addNode(c, 10, 90)\n'
           'c.inputPortByName["colorMap"].widget.set({"mini": -3.0, "maxi": 24.0, "name": "cmap", '
           '"labelGridCfg": {"row": 1}, "ramp": [[0., 0., 1., 1.], [1., 0., 0., 1.]]}, run=False)\n')
    data, report = importer.import_source(src, 'x_net.py')
    w = data['network']['nodes'][0]['widgets']['ramp']
    eq((w['mini'], w['maxi'], len(w['ramp'])), (-3.0, 24.0, 2))
    net = Network('imported')
    eq(fileio.from_dict(net, data), [])
    eq(net.nodes[0].inputPortByName['ramp'].widget.get(),
       {'ramp': [[0.0, 0.0, 1.0, 1.0], [1.0, 0.0, 0.0, 1.0]], 'mini': -3.0, 'maxi': 24.0, 'name': 'cmap'})


def test_vision_color_map_legend_connects_to_the_viewer():
    src = ('from DejaVu.VisionInterface.DejaVuNodes import vizlib\n'
           'from DejaVu.VisionInterface.DejaVuNodes import ColorMapNE, Viewer\n'
           'c = ColorMapNE(constrkw={}, name="Color Map", library=vizlib)\n'
           'masterNet.addNode(c, 10, 10)\n'
           'v = Viewer(constrkw={}, name="Viewer", library=vizlib)\n'
           'masterNet.addNode(v, 10, 90)\n'
           'masterNet.connectNodes(c, v, "legend", "geometries", blocking=True)\n')
    data, report = importer.import_source(src, 'x_net.py')
    net = Network('imported')
    eq(fileio.from_dict(net, data), [])
    eq([(c.port1.name, c.port2.name) for c in net.connections], [('legend', 'geometries')])
