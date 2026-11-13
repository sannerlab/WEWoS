# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Editing operations of a session (what the page asks the server to do)."""
import json
import os
import secrets

from common import ROOT, check, eq, outdir

from wewos.session import Session


def _session(name='t'):
    s = Session(secrets.token_hex(8), outdir('sessions'), name)
    s.net.runner = None          # run in the caller's thread
    return s


def _example(s, name):
    with open(os.path.join(ROOT, 'examples', name)) as fh:
        data = json.load(fh)
    import shutil
    shutil.copytree(os.path.join(ROOT, 'examples', 'data'), os.path.join(s.folder, 'data'))
    eq(s.load(data), [])


def _viewer(s):
    return [n for n in s.net.nodes if n.name == 'Viewer'][0]


def test_explode_library_macro_keeps_the_result():
    s = _session()
    _example(s, 'icosahedral_spheres.wnet.json')
    s.run('hardrun')
    before = _viewer(s).geomsJSON()[0]['centers']['shape']
    eq(before, [180, 3])
    ic = [n for n in s.net.nodes if n.name == 'Icosahedral1'][0]
    out = s.edit('explode_macro', {'node': ic.id})
    eq(out['report'], [])
    check(ic not in s.net.nodes)
    names = sorted(n.name for n in s.net.nodes)
    check('Merge' in names and '5-fold' in names, names)
    s.run('hardrun')
    eq(_viewer(s).geomsJSON()[0]['centers']['shape'], [180, 3])


def test_group_then_explode_round_trip():
    s = _session()
    _example(s, 'iterate_squares.wnet.json')
    s.run('hardrun')
    acc = [n for n in s.net.nodes if n.name == 'accum'][0]
    want = list(acc.outputPorts[0].data)
    eq(want, [0, 1, 4, 9, 16, 25, 36, 49, 64, 81])
    ids = [n.id for n in s.net.nodes if n.name in ('iterate', 'square')]
    m = s.edit('make_macro', {'nodes': ids, 'name': 'loop'})['node']
    s.run('hardrun')
    acc = [n for n in s.net.nodes if n.name == 'accum'][0]
    eq(list(acc.outputPorts[0].data), want)
    s.edit('explode_macro', {'node': m})
    eq(sorted(n.name for n in s.net.nodes), ['accum', 'iterate', 'print', 'range', 'square'])
    s.run('hardrun')
    acc = [n for n in s.net.nodes if n.name == 'accum'][0]
    eq(list(acc.outputPorts[0].data), want)


def test_arrange_lays_out_the_network():
    s = _session()
    _example(s, 'iterate_squares.wnet.json')
    for i, n in enumerate(s.net.nodes):
        n.move(10, 10)                       # all on top of each other
    s.edit('arrange', {})
    pos = {(n.posx, n.posy) for n in s.net.nodes}
    eq(len(pos), len(s.net.nodes))
    for c in s.net.connections:
        if c.blocking:
            check(c.port1.node.posx < c.port2.node.posx)


def test_viewer_rendering_edit():
    s = _session()
    _example(s, 'icosahedral_spheres.wnet.json')
    v = _viewer(s)
    out = s.edit('viewer_rendering', {'node': v.id, 'rendering': {'outline': False, 'fogStart': 0.0}})
    eq(out['rendering']['outline'], False)
    eq(v.sceneState()['rendering']['fogStart'], 0.0)


def test_viewer_renderer_edit():
    s = _session()
    _example(s, 'icosahedral_spheres.wnet.json')
    v = _viewer(s)
    eq(s.edit('viewer_renderer', {'node': v.id, 'renderer': 'molstar'})['renderer'], 'molstar')
    s.edit('viewer_view', {'node': v.id, 'view': {'radius': 12}, 'renderer': 'molstar'})
    out = s.edit('viewer_rendering', {'node': v.id, 'molstar': {'cameraFog': {'name': 'off', 'params': {}}}})
    eq(out['molstar']['cameraFog']['name'], 'off')
    st = v.sceneState()
    eq((st['renderer'], st['cameras']['molstar']), ('molstar', {'radius': 12}))
    try:
        s.edit('viewer_renderer', {'node': v.id, 'renderer': 'pymol'})
        check(False, 'an unknown renderer was accepted')
    except Exception as e:
        check('pymol' in str(e))


def test_view_change_is_a_redraw():
    """Moving the view on the page fires the Viewer's redraw output, as
    DejaVu's redraws did in Vision: One Redraw then triggers its node."""
    from wewos.engine import get_library
    s = _session()
    vz, std = get_library('3D Visualization'), get_library('Standard')
    v, one, pr = vz.instantiate(label='Viewer'), vz.instantiate(label='One Redraw'), std.instantiate(label='Pass')
    for i, n in enumerate((v, one, pr)):
        s.net.addNode(n, 40 + 200 * i, 40)
    s.net.connectNodes(v, one, 'redraw', 'trigger')
    s.net.connectNodes(v, pr, 'viewer', 'in1')
    s.net.specialConnectNodes(one, pr, 'trigger', 'runNode')
    s.run('hardrun')
    runs = lambda since: [e for e in s.net.bus.since(since)['events']
                          if e['kind'] == 'node_status' and e.get('node') == pr.id and e.get('status') == 'done']
    seq = s.net.bus.seq
    eq(s.edit('viewer_view', {'node': v.id, 'view': [1, 2], 'redraw': True})['redraw'], True)
    check(runs(seq), 'Pass did not run after the view moved')
    seq = s.net.bus.seq
    s.edit('viewer_view', {'node': v.id, 'view': [3, 4]})          # saving the view only
    eq(runs(seq), [])


def test_colormap_file_edit():
    s = _session()
    cm = {'ramp': [[0, 0, 1, 1], [1, 0, 0, 0.5]], 'mini': 1.0, 'maxi': 2.0, 'name': 'mine'}
    out = s.edit('colormap_file', {'action': 'write', 'path': 'mine', 'colorMap': cm})
    check(out['path'].endswith('mine_map.py') and os.path.isfile(out['path']))
    back = s.edit('colormap_file', {'action': 'read', 'path': 'mine_map.py'})['colorMap']
    eq(back, {'ramp': [[0.0, 0.0, 1.0, 1.0], [1.0, 0.0, 0.0, 0.5]], 'mini': 1.0, 'maxi': 2.0, 'name': 'mine'})


def test_viewer_legend_edit():
    s = _session()
    _example(s, 'spheres_colormap.wnet.json')
    s.run('hardrun')
    v = _viewer(s)
    name = [g['name'] for g in v.geomsJSON() if g['type'] == 'legend'][0]
    out = s.edit('viewer_legend', {'node': v.id, 'name': name, 'opts': {'x': 0.5, 'y': 0.5, 'size': 1.5}})
    eq(out['legends'][name], {'x': 0.5, 'y': 0.5, 'size': 1.5})
    eq(v.sceneState()['legends'][name]['size'], 1.5)


def test_file_browser_relative_folder_is_in_the_network_folder():
    # a widget's relative file name (cartoonMovie/x.png) is in the network's
    # folder: the file browser opens there, not in the server's directory
    from wewos.session import list_dir
    base = outdir('filebrowser')
    os.makedirs(os.path.join(base, 'cartoonMovie'), exist_ok=True)
    open(os.path.join(base, 'cartoonMovie', 'frame0.png'), 'w').close()
    d = list_dir('cartoonMovie', base)
    eq(d['path'], os.path.join(os.path.abspath(base), 'cartoonMovie'))
    eq([e['name'] for e in d['entries']], ['frame0.png'])
    d = list_dir('cartoonMovie/frame0.png', base)          # a file: its folder
    eq(d['path'], os.path.join(os.path.abspath(base), 'cartoonMovie'))
    eq(list_dir('', base)['path'], os.path.abspath(base))


def test_long_port_names_and_widgets_keep_nodes_narrow():
    """Long port names are shown short (the full name is the tooltip), and a
    widget in a node is as wide as its kind needs (static/editor.js mirrors
    wewos/engine/layout.py; a browser check compared both on the examples)."""
    from wewos.engine.layout import node_geometry, short_name, short_names, widget_width
    eq(short_name('indexedPolygons_instanceMatrices'), 'instMat')
    eq(short_name('Merge_outMatrices'), 'outMatrices')
    eq(short_name('transformation_matrix_list'), 'matrix_list')
    eq(short_name('geomOptions'), 'geomOptions')                     # short names stay
    eq(short_names(['indexedPolygons_instanceMatrices', 'spheres_instanceMatrices']),
       {'indexedPolygons_instanceMatrices': 'indPolInstMat',
        'spheres_instanceMatrices': 'spheresInstMat'})               # never two alike
    eq(widget_width({'kind': 'number', 'value': 1, 'options': {'type': 'int', 'min': 1}}), 52)
    eq(widget_width({'kind': 'entry', 'value': '2plv'}), 16 + 4 * 6.6)
    eq(widget_width({'kind': 'number', 'value': 1, 'options': {'nodeWidth': 120}}), 120)
    eq(widget_width({'kind': 'checkbox'}), 18)
    check(widget_width({'kind': 'combo', 'options': {'choices': ['a', 'bb']}}) == 60)
    s = _session()
    _example(s, 'capsid_surface.wnet.json')
    ms = [n for n in s.net.nodes if n.name == 'CoarseMolSurf'][0]
    check(node_geometry(ms.describe())['w'] < 200, node_geometry(ms.describe()))


def test_a_widget_width_chosen_by_the_user_is_saved():
    from wewos.engine import Network, fileio
    from wewos.engine.layout import node_geometry
    s = _session()
    _example(s, 'capsid_surface.wnet.json')
    fetch = [n for n in s.net.nodes if n.name == 'Fetch PDB'][0]
    w0 = node_geometry(fetch.describe())['w']
    s.edit('widget_opts', {'node': fetch.id, 'port': 'pdbId', 'opts': {'nodeWidth': 160}})
    check(node_geometry(fetch.describe())['w'] > w0)
    n2 = Network('reopened')
    fileio.from_dict(n2, fileio.to_dict(s.net))
    f2 = [n for n in n2.nodes if n.name == 'Fetch PDB'][0]
    eq(f2.inputPortByName['pdbId'].widget.options.get('nodeWidth'), 160)
    s.edit('widget_opts', {'node': fetch.id, 'port': 'pdbId', 'opts': {'nodeWidth': None}})
    eq(node_geometry(fetch.describe())['w'], w0)                     # automatic again
