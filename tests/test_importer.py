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


def test_saved_viewer_color_goes_to_the_geometry_node():
    # Vision kept an object's diffuse color in the viewer's saved state
    src = ('from DejaVu.VisionInterface.DejaVuNodes import vizlib\n'
           'from DejaVu.VisionInterface.GeometryNodes import Spheres\n'
           's = Spheres(constrkw={}, name="cageVertices", library=vizlib)\n'
           'masterNet.addNode(s, 10, 10)\n'
           'def loadSavedStates_Viewer_1(self=None, event=None):\n'
           '    obj = self.vi.FindObjectByName("root|cageVertices")\n'
           '    if obj:\n'
           '        state = {"opacity": [1.0], "diffuse": [[1.0, 0.42, 0.69, 1.0]]}\n'
           '        apply(obj.materials[GL.GL_FRONT].Set, (), state)\n')
    data, report = importer.import_source(src, 'x_net.py')
    e = data['network']['nodes'][0]
    eq(e['state'], {'geomState': {'color': [1.0, 0.42, 0.69]}})
    net = Network('imported')
    eq(fileio.from_dict(net, data), [])
    n = net.nodes[0]
    eq(n.geomState, {'color': [1.0, 0.42, 0.69]})
    eq(n.getStateForSaving(), {'geomState': {'color': [1.0, 0.42, 0.69]}})


def test_user_macro_port_follows_a_renamed_inner_port():
    # ColorMapNE's mappedColors is colors here: the macro port named after it follows
    src = ('from NetworkEditor.macros import MacroNode\n'
           'from DejaVu.VisionInterface.DejaVuNodes import vizlib, ColorMapNE\n'
           'from DejaVu.VisionInterface.GeometryNodes import IndexedPolygonsNE\n'
           'm = MacroNode(name="radialColoring")\n'
           'masterNet.addNode(m, 10, 10)\n'
           'c = ColorMapNE(constrkw={}, name="Color Map", library=vizlib)\n'
           'm.macroNetwork.addNode(c, 10, 10)\n'
           'op = m.macroNetwork.opNode\n'
           'm.macroNetwork.connectNodes(c, op, "mappedColors", "new", blocking=True)\n'
           'p = IndexedPolygonsNE(constrkw={}, name="surf", library=vizlib)\n'
           'masterNet.addNode(p, 200, 10)\n'
           'masterNet.connectNodes(m, p, "Color_Map_mappedColors", "colors", blocking=True)\n')
    data, report = importer.import_source(src, 'x_net.py')
    net = Network('imported')
    eq(fileio.from_dict(net, data), [])
    eq([(c.port1.name, c.port2.name) for c in net.connections], [('Color_Map_colors', 'colors')])


def test_changes_inside_a_library_macro_are_reported():
    src = ('from symserv.VisionInterface.SymservNodes import symlib, Icos1, SymTransNE\n'
           'from MolKit.VisionInterface.MolKitNodes import molkitlib, LinesMacro\n'
           'i = Icos1(constrkw={}, name="Icosahedral1", library=symlib)\n'
           'masterNet.addNode(i, 10, 10)\n'
           't = SymTransNE(constrkw={}, name="Translate", library=symlib)\n'
           'i.macroNetwork.addNode(t, 10, 10)\n'
           'i.macroNetwork.deleteConnection(i.macroNetwork.nodes[2], "outMatrices", i.macroNetwork.nodes[3], "matrices")\n'
           'l = LinesMacro(constrkw={}, name="Lines Macro", library=molkitlib)\n'
           'masterNet.addNode(l, 10, 90)\n'
           'masterNet.connectNodes(i, l, "Merge_outMatrices", "IndexedPolylines_parent", blocking=True)\n')
    data, report = importer.import_source(src, 'x_net.py')
    check(any('Icosahedral1' in w and 'added nodes' in w and 'deleted connections' in w
              for w in report.warnings))
    # a geometry parent port is not the Lines node's atoms: not connected, reported on loading
    c = data['network']['connections'][0]
    eq(c['to'][1], 'IndexedPolylines_parent')
    net = Network('imported')
    probs = fileio.from_dict(net, data)
    check(len(probs) == 1 and 'IndexedPolylines_parent' in probs[0])


def test_vision_geom_options_node_sends_a_dict():
    # Vision's Set Geom Options outputs a dict for a geometry's geomOptions input
    src = ('from DejaVu.VisionInterface.DejaVuNodes import vizlib, GeomOptions\n'
           'from DejaVu.VisionInterface.GeometryNodes import IndexedPolygonsNE\n'
           'o = GeomOptions(constrkw={}, name="Set Geom Options", library=vizlib)\n'
           'masterNet.addNode(o, 10, 10)\n'
           'o.inputPortByName["geomOptions"].widget.set({"frontPolyMode": "line"}, run=False)\n'
           'p = IndexedPolygonsNE(constrkw={}, name="surf", library=vizlib)\n'
           'masterNet.addNode(p, 200, 10)\n'
           'masterNet.connectNodes(o, p, "geomOptions", "geomOptions", blocking=True)\n')
    data, report = importer.import_source(src, 'x_net.py')
    net = Network('imported')
    eq(fileio.from_dict(net, data), [])
    o = net.nodes[0]
    net.run([o])
    eq(o.outputPortByName['geomOptions'].data, {'frontPolyMode': 'line'})
    eq(o.status, 'done')                     # no geometry given: only the dict goes out
