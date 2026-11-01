# Author: Michel Sanner, PhD. Copyright (c) 2026.
# Replaces MGLTools DejaVu/VisionInterface (DejaVuNodes.py, GeometryNodes.py).
"""3D Visualization: geometry nodes and the Viewer node.

Geometry nodes build wewos.geom objects (no OpenGL). Their ports keep the
names of DejaVu's nodes (coords, indices, colors, radius, name,
instanceMatrices, geomOptions, parent) so imported networks connect the same
way. The Viewer node keeps the scene on the server and tells the page what
changed ('scene' events with names and versions); the page fetches the
geometry and draws it with 3Dmol.js. A click in the 3D view comes back to the
Viewer node, which outputs it on lastPick and runs the nodes connected there.
"""
import numpy

from wewos import geom as G
from wewos.engine import NetworkNode, NodeLibrary
from wewos.engine.datatypes import AnyType


class GeomType(AnyType):
    """'geom': a geometry, or a list of them."""

    def __init__(self, name='geom', datashape=None, color='#a855f7', shape='rect',
                 width=None, height=None):
        AnyType.__init__(self, name=name, color=color, shape=shape, klass=G.Geom)

    def validate(self, data):
        if isinstance(data, G.Geom):
            return True
        return isinstance(data, (list, tuple)) and all(isinstance(g, G.Geom) for g in data)

    def cast(self, data):
        return False, data


class ViewerType(AnyType):
    def __init__(self, name='viewer', datashape=None, color='#7c3aed', shape='square',
                 width=None, height=None):
        AnyType.__init__(self, name=name, color=color, shape=shape, klass=None)


class GeometryNode(NetworkNode):
    """Base class: keeps one geometry object and updates it on each run.

    Subclasses declare their own ports, then call self._commonPorts(); their
    doit builds keyword arguments for geom.Set and calls self.update(kw, ...)."""
    geomClass = G.Geom
    outName = 'geom'

    def __init__(self, name='geometry', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.geom = None
        # options kept with the network and set on the geometry before the
        # inputs (Vision kept them in the viewer's saved state, e.g. a color)
        self.geomState = {}

    def getStateForSaving(self):
        return {'geomState': dict(self.geomState)} if self.geomState else {}

    def setStateFromSaving(self, state):
        self.geomState = dict((state or {}).get('geomState') or {})

    def _commonPorts(self):
        ip = self.inputPortsDescr
        ip.append(datatype='string', required=False, name='name')
        ip.append(datatype='instancemat(0)', required=False, name='instanceMatrices',
                  singleConnection=False)
        ip.append(datatype='dict', required=False, name='geomOptions')
        ip.append(datatype='geom', required=False, name='parent')
        self.outputPortsDescr.append(datatype='geom', name=self.outName)

    def makeGeom(self, name):
        return self.geomClass(name)

    def getGeom(self, name=None):
        if self.geom is None:
            self.geom = self.makeGeom(name or self.name.replace(' ', '_'))
        elif name and name != self.geom.name:
            self.geom.Set(name=name)
        return self.geom

    def update(self, kw, name=None, instanceMatrices=None, geomOptions=None, parent=None):
        g = self.getGeom(name)
        kw = {k: v for k, v in kw.items() if v is not None}
        if self.geomState:
            st = dict(self.geomState)
            if any(k in kw or k in (geomOptions or {}) for k in ('colors', 'color', 'materials')):
                for k in ('colors', 'color', 'materials'):
                    st.pop(k, None)
            kw = dict(st, **kw)
        if instanceMatrices is not None:
            kw['instanceMatrices'] = G.instance_list(instanceMatrices)
        if geomOptions:
            kw.update(geomOptions)
        g.Set(**kw)
        if parent is not None and isinstance(parent, G.Geom) and g.parent is not parent:
            parent.add(g)
        self.outputData(**{self.outName: g})
        return g


class Spheres(GeometryNode):
    """Spheres centered on coords, with one radius or one per sphere."""
    geomClass = G.Spheres
    outName = 'spheres'

    def __init__(self, name='spheres', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='coord3(0)', name='coords', required=False, defaultValue=((0, 0, 0),))
        ip.append(datatype='colorfloat3or4(0)', name='colors', required=False)
        ip.append(datatype='float(0)', name='radius', required=False, defaultValue=1.)
        self.widgetDescr['radius'] = {'class': 'NEThumbWheel', 'master': 'node',
                                      'initialValue': 1.0, 'min': 0.0, 'oneTurn': 5.,
                                      'labelCfg': {'text': 'radius'}}
        self._commonPorts()
        self.setFunction("""def doit(self, coords, colors, radius, name, instanceMatrices, geomOptions, parent):
    self.update({'vertices': coords, 'materials': colors, 'radii': radius},
                name, instanceMatrices, geomOptions, parent)
""")


class Points(Spheres):
    """Points (drawn as small spheres)."""

    def __init__(self, name='points', **kw):
        Spheres.__init__(self, name, **kw)
        self.widgetDescr['radius']['initialValue'] = 0.1


class Cylinders(GeometryNode):
    """Cylinders joining pairs of coords (indices: pairs, or polylines)."""
    geomClass = G.Cylinders
    outName = 'cylinders'

    def __init__(self, name='cylinders', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='coord3(0)', name='coords', required=False,
                  defaultValue=((0, 0, 0), (10, 0, 0)))
        ip.append(datatype='None', name='indices', required=False, defaultValue=((0, 1),))
        ip.append(datatype='colorfloat3or4(0)', name='colors', required=False)
        ip.append(datatype='float(0)', name='radius', required=False, defaultValue=1.)
        self.widgetDescr['radius'] = {'class': 'NEThumbWheel', 'master': 'node',
                                      'initialValue': 0.3, 'min': 0.0, 'oneTurn': 2.,
                                      'labelCfg': {'text': 'radius'}}
        self._commonPorts()
        self.setFunction("""def doit(self, coords, indices, colors, radius, name, instanceMatrices, geomOptions, parent):
    self.update({'vertices': coords, 'faces': indices, 'materials': colors, 'radii': radius},
                name, instanceMatrices, geomOptions, parent)
""")


class IndexedPolylines(GeometryNode):
    """Lines: index pairs, or polylines, into coords."""
    geomClass = G.IndexedPolylines
    outName = 'indexedPolylines'

    def __init__(self, name='indexedPolylines', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='coord3(0)', name='coords')
        ip.append(datatype='None', name='indices', required=False)
        ip.append(datatype='colorfloat3or4(0)', required=False, name='colors')
        self._commonPorts()
        self.setFunction("""def doit(self, coords, indices, colors, name, instanceMatrices, geomOptions, parent):
    self.update({'vertices': coords, 'faces': indices, 'materials': colors},
                name, instanceMatrices, geomOptions, parent)
""")


class IndexedPolygons(GeometryNode):
    """A mesh: triangles (or polygons) indexing coords; optional normals and
    per-vertex colors."""
    geomClass = G.IndexedPolygons
    outName = 'indexedPolygons'

    def __init__(self, name='indexedPolygons', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='coord3(0)', name='coords')
        ip.append(datatype='None', name='indices')
        ip.append(datatype='normal3(0)', required=False, name='vnormals')
        ip.append(datatype='colorfloat3or4(0)', required=False, name='colors')
        ip.append(datatype='float', required=False, name='opacity')
        self.widgetDescr['opacity'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                       'initialValue': 1.0, 'min': 0.0, 'max': 1.0,
                                       'oneTurn': 1., 'labelCfg': {'text': 'opacity'}}
        self._commonPorts()
        self.setFunction("""def doit(self, coords, indices, vnormals, colors, opacity, name, instanceMatrices, geomOptions, parent):
    self.update({'vertices': coords, 'faces': indices, 'vnormals': vnormals,
                 'materials': colors, 'opacity': opacity},
                name, instanceMatrices, geomOptions, parent)
""")


class Labels(GeometryNode):
    """Text labels at coords."""
    geomClass = G.Labels
    outName = 'glflabels'

    def __init__(self, name='labels', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='coord3(0)', name='coords', required=False, defaultValue=((0, 0, 0),))
        ip.append(datatype='None', name='labels', required=False)
        ip.append(datatype='colorfloat3or4(0)', name='colors', required=False)
        ip.append(datatype='int', name='fontSize', required=False)
        self.widgetDescr['fontSize'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                        'type': 'int', 'initialValue': 14, 'min': 6, 'max': 64,
                                        'labelCfg': {'text': 'font size'}}
        self._commonPorts()
        self.setFunction("""def doit(self, coords, labels, colors, fontSize, name, instanceMatrices, geomOptions, parent):
    if isinstance(labels, str):
        labels = [labels]
    self.update({'vertices': coords, 'labels': labels, 'materials': colors, 'fontSize': fontSize},
                name, instanceMatrices, geomOptions, parent)
""")


class BoxNE(GeometryNode):
    """A box (12 lines) from its center and side lengths."""
    outName = 'box'

    def __init__(self, name='box', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        for n, v in (('centerx', 0.), ('centery', 0.), ('centerz', 0.),
                     ('lengthx', 10.), ('lengthy', 10.), ('lengthz', 10.)):
            ip.append(datatype='float', required=False, name=n)
            self.widgetDescr[n] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                   'initialValue': v, 'oneTurn': 10., 'labelCfg': {'text': n}}
        ip.append(datatype='colorfloat3or4(0)', name='colors', required=False)
        self._commonPorts()
        self.setFunction("""def doit(self, centerx, centery, centerz, lengthx, lengthy, lengthz, colors, name, instanceMatrices, geomOptions, parent):
    b = G.Box('tmp', (centerx, centery, centerz), (lengthx, lengthy, lengthz))
    self.update({'vertices': b.vertices, 'faces': b.faces, 'materials': colors},
                name, instanceMatrices, geomOptions, parent)
""")

    def makeGeom(self, name):
        return G.IndexedPolylines(name)


class AxisNE(GeometryNode):
    """x, y and z arrows (red, green, blue)."""
    outName = 'axis'

    def __init__(self, name='axis', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='coord3', name='center', required=False, defaultValue=(0., 0., 0.))
        ip.append(datatype='float', name='length', required=False)
        ip.append(datatype='float', name='radius', required=False)
        self.widgetDescr['length'] = {'class': 'NEThumbWheel', 'master': 'node',
                                      'initialValue': 10., 'min': 0., 'oneTurn': 20.,
                                      'labelCfg': {'text': 'length'}}
        self.widgetDescr['radius'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                      'initialValue': 0.3, 'min': 0., 'oneTurn': 2.,
                                      'labelCfg': {'text': 'radius'}}
        self._commonPorts()
        self.setFunction("""def doit(self, center, length, radius, name, instanceMatrices, geomOptions, parent):
    a = G.Axis('tmp', center, length, radius)
    self.update({'vertices': a.vertices, 'faces': a.faces, 'radii': radius,
                 'materials': a.colors, 'arrows': True},
                name, instanceMatrices, geomOptions, parent)
""")

    def makeGeom(self, name):
        return G.Cylinders(name)


class GeomContainer(GeometryNode):
    """Groups geometries under one name (children connected on geoms)."""
    geomClass = G.GeomContainer
    outName = 'geomContainer'

    def __init__(self, name='group', **kw):
        GeometryNode.__init__(self, name, **kw)
        self.inputPortsDescr.append(datatype='geom', name='geoms', required=False,
                                    singleConnection=False)
        self._commonPorts()
        self.setFunction("""def doit(self, geoms, name, instanceMatrices, geomOptions, parent):
    g = self.getGeom(name)
    for c in list(g.children):
        c.parent = None
    g.children = []
    for c in G.flatten(geoms or []):
        if c.parent is None or c.parent is g:
            g.add(c)
    self.update({}, name, instanceMatrices, geomOptions, parent)
""")


class GeomOptions(NetworkNode):
    """Set options on a geometry (DejaVu Set keywords, e.g.
{'opacity': 0.5, 'visible': True, 'wireframe': True, 'colors': (1, 0, 0)}).

The options are set on the geometry given to the geom input, which is passed
on; they are also sent out as a dict (the geomOptions output, as in Vision),
for the geomOptions input of a geometry node."""

    def __init__(self, name='Set Geom Options', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='geom', name='geom', required=False)
        self.inputPortsDescr.append(datatype='None', name='geomOptions', required=False)
        self.widgetDescr['geomOptions'] = {'class': 'NEEntry', 'master': 'node',
                                           'initialValue': "{'opacity': 1.0}",
                                           'labelCfg': {'text': 'options'}}
        self.outputPortsDescr.append(datatype='geom', name='geom')
        self.outputPortsDescr.append(datatype='dict', name='geomOptions')
        self.setFunction("""def doit(self, geom, geomOptions):
    import ast
    opts = ast.literal_eval(geomOptions) if isinstance(geomOptions, str) else geomOptions
    opts = dict(opts or {})
    if geom is not None:
        for g in G.flatten(geom):
            g.Set(**opts)
        self.outputData(geom=geom)
    self.outputData(geomOptions=opts)
""")


class OneRedraw(NetworkNode):
    """Runs when the viewer has redrawn (connect the Viewer's redraw output to
its trigger input) and then fires its trigger output (the special port under
the node): connect that to the runNode input of the node to run after a
redraw, e.g. Grab Image (Vision's One Redraw)."""

    def __init__(self, name='One Redraw', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='viewer', name='viewer', required=False)
        self.inputPortsDescr.append(datatype='None', name='trigger', required=False)
        self.setFunction("""def doit(self, viewer, trigger):
    pass
""")


class ColorMap(NetworkNode):
    """Colors for a list of values: values between mini and maxi are mapped
through a color ramp. The ramp is edited in the node's parameter panel, as in
Vision: draw its red, green, blue (or hue, saturation, value/luminance) and
opacity as curves with the mouse (left button: freehand, right button: a
straight line), start from a preset (rgb, rwb, grey, rainbow and MGLTools'
color maps), give it a min and max, undo, and read or write Vision colormap
files. mini and maxi, when connected, override the ramp's own range; without
either, the range of the values is used. The colors have an alpha when the
ramp has some transparency. Connect the legend output to a Viewer to show
the color bar and its range over the 3D view (drag it there to move it,
right-click it for its orientation, labels and size)."""

    def __init__(self, name='Color Map', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None', name='values')
        ip.append(datatype='None', name='ramp', required=False)
        ip.append(datatype='float', name='mini', required=False)
        ip.append(datatype='float', name='maxi', required=False)
        self.widgetDescr['ramp'] = {'class': 'NEColorMap', 'master': 'node', 'initialValue': 'rgb',
                                    'labelCfg': {'text': 'ramp'}}
        self.outputPortsDescr.append(datatype='colorfloat3or4(0)', name='colors')
        self.outputPortsDescr.append(datatype='geom', name='legend')
        self.legend = None
        self.setFunction("""def doit(self, values, ramp, mini, maxi):
    self.outputData(colors=colormap(values, ramp, mini, maxi), legend=self.makeLegend(values, ramp, mini, maxi))
""")

    def makeLegend(self, values, ramp, mini, maxi):
        """The legend geometry: the ramp and the range actually used."""
        from wewos.colormaps import normalize
        cols, rlo, rhi = ramp_of(ramp)
        v = numpy.asarray(values if values is not None else [], 'f').ravel()
        lo = mini if mini is not None else (rlo if rlo is not None else (float(v.min()) if v.size else 0.))
        hi = maxi if maxi is not None else (rhi if rhi is not None else (float(v.max()) if v.size else 1.))
        cm = normalize(ramp)
        title = cm if isinstance(cm, str) else (cm.get('name') or '')
        labels = None if isinstance(cm, str) else cm.get('labels')
        name = self.name.replace(' ', '_') + '_legend'
        if self.legend is None:
            self.legend = G.ColorMapLegend(name)
        self.legend.Set(name=name, ramp=cols, mini=lo, maxi=hi, title=title, labels=labels)
        return self.legend


_RAMPS = {
    'rgb': [(0, 0, 1), (0, 1, 1), (0, 1, 0), (1, 1, 0), (1, 0, 0)],
    'rwb': [(1, 0, 0), (1, 1, 1), (0, 0, 1)],
    'grey': [(0, 0, 0), (1, 1, 1)],
    'rainbow': [(.5, 0, 1), (0, 0, 1), (0, 1, 1), (0, 1, 0), (1, 1, 0), (1, .5, 0), (1, 0, 0)],
}


def ramp_of(ramp):
    """(n x 4 RGBA colors, mini, maxi) of a color map value: a preset name, a
    list of colors, or a dict {'ramp', 'mini', 'maxi'} (wewos.colormaps)."""
    from wewos.colormaps import normalize
    cm = normalize(ramp)
    if isinstance(cm, str):
        cols, lo, hi = _RAMPS.get(cm, _RAMPS['rgb']), None, None
    else:
        cols, lo, hi = cm.get('ramp') or _RAMPS['rgb'], cm.get('mini'), cm.get('maxi')
    c = numpy.asarray(cols, 'f').reshape(-1, numpy.shape(cols)[-1])
    if c.shape[1] == 3:
        c = numpy.hstack([c, numpy.ones((len(c), 1), 'f')])
    if len(c) == 1:
        c = numpy.vstack([c, c])
    return c[:, :4], lo, hi


def colormap(values, ramp='rgb', mini=None, maxi=None):
    """Colors (n x 3, or n x 4 when the ramp has transparency) for values,
    between mini and maxi (given, else the ramp's range, else the values')."""
    v = numpy.asarray(values, 'f').ravel()
    cols, rlo, rhi = ramp_of(ramp)
    if v.size == 0:
        return numpy.zeros((0, 3), 'f')
    lo = mini if mini is not None else (rlo if rlo is not None else float(v.min()))
    hi = maxi if maxi is not None else (rhi if rhi is not None else float(v.max()))
    t = numpy.clip((v - lo) / (hi - lo if hi != lo else 1.), 0, 1)
    x = t * (len(cols) - 1)
    i = numpy.minimum(x.astype(int), len(cols) - 2)
    f = (x - i)[:, None]
    out = cols[i] * (1 - f) + cols[i + 1] * f
    return out if (cols[:, 3] < 1).any() else out[:, :3]


class ReadMesh(NetworkNode):
    """Read a mesh from an OBJ, OFF or MSMS .vert/.face file pair; outputs
vertices, faces and normals for an IndexedPolygons node."""

    def __init__(self, name='Read Mesh', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.widgetDescr['filename'] = {'class': 'NEEntryWithFileBrowser', 'master': 'node',
                                        'filetypes': [('mesh', '*.obj *.off *.vert *.face')],
                                        'labelCfg': {'text': 'file'}}
        self.outputPortsDescr.append(datatype='coord3(0)', name='coords')
        self.outputPortsDescr.append(datatype='None', name='indices')
        self.outputPortsDescr.append(datatype='normal3(0)', name='vnormals')
        self.setFunction("""def doit(self, filename):
    v, f, n = read_mesh(filename)
    self.outputData(coords=v, indices=f, vnormals=n)
""")


def read_mesh(filename):
    import os
    base, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext in ('.vert', '.face'):
        v, n = [], []
        with open(base + '.vert') as fh:
            for line in fh:
                if line.startswith('#'):
                    continue
                w = line.split()
                if len(w) >= 6:
                    try:
                        v.append([float(x) for x in w[:3]])
                        n.append([float(x) for x in w[3:6]])
                    except ValueError:
                        pass
        f = []
        with open(base + '.face') as fh:
            for line in fh:
                if line.startswith('#'):
                    continue
                w = line.split()
                if len(w) >= 3:
                    try:
                        f.append([int(x) - 1 for x in w[:3]])
                    except ValueError:
                        pass
        return numpy.array(v, 'f'), numpy.array(f, 'i'), numpy.array(n, 'f')
    if ext == '.off':
        with open(filename) as fh:
            words = [l.split() for l in fh if l.strip() and not l.startswith('#')]
        nv, nf = int(words[1][0]), int(words[1][1])
        v = numpy.array([[float(x) for x in w[:3]] for w in words[2:2 + nv]], 'f')
        f = [[int(x) for x in w[1:1 + int(w[0])]] for w in words[2 + nv:2 + nv + nf]]
        tri = G.triangles(f)
        return v, tri, G.vertex_normals(v, tri)
    # OBJ
    v, f = [], []
    with open(filename) as fh:
        for line in fh:
            w = line.split()
            if not w:
                continue
            if w[0] == 'v':
                v.append([float(x) for x in w[1:4]])
            elif w[0] == 'f':
                f.append([int(x.split('/')[0]) - 1 for x in w[1:]])
    v = numpy.array(v, 'f')
    tri = G.triangles(f)
    return v, tri, G.vertex_normals(v, tri)


# how a viewer draws: silhouette edges (width in pixels) and fog (depth cueing:
# from fogStart to fogEnd, in fractions of the scene's depth, 0 = its front,
# 1 = its back; things fade into the background color)
RENDERING = {'outline': True, 'outlineWidth': 2.0, 'outlineColor': '#000000',
             'fog': True, 'fogStart': 0.3, 'fogEnd': 1.3}

# the page's renderers: 3Dmol.js (the default) and Mol*
RENDERERS = ('3dmol', 'molstar')


class Viewer(NetworkNode):
    """A 3D viewer (3Dmol.js or Mol*, in the row of panels under the network).

Connect geometries (or lists of them) to 'geometries'. Click a sphere, a
cylinder, a mesh or an atom: lastPick outputs a dict describing it
({'geom': name, 'object': the geometry, 'atom': {...} for molecules}) and the
nodes connected to lastPick run. The redraw output fires when the scene
changes and when the view is moved with the mouse (every 300 ms during a
drag, as DejaVu's redraws did): a One Redraw -> Grab Image chain follows the
view.

The viewer draws with 3Dmol.js or Mol* (the menu in its header, or
viewer.setRenderer('molstar') from code); the choice is saved with the
network. 3Dmol's silhouettes and fog are set with the viewer's \u25d0 button,
or with viewer.setRendering(outline=True, outlineWidth=2,
outlineColor='#000000', fog=True, fogStart=0.3, fogEnd=1.3) (fog from 30% to
130% of the scene's depth). Mol*'s rendering settings (ambient occlusion,
shadows, depth of field, illumination...) are set in its viewport, and are
saved too."""

    def __init__(self, name='Viewer', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.sent = {}
        self.geoms = {}
        self.camera = None
        self.background = None
        self.rendering = dict(RENDERING)
        self.renderer = RENDERERS[0]
        self.cameras = {}           # renderer -> its camera (3Dmol's is self.camera)
        self.molstarCanvas = None   # Mol*'s rendering settings, when changed
        self.legends = {}           # color map legend name -> place and look on the page
        self.inputPortsDescr.append(name='geometries', datatype='geom', required=False,
                                    singleConnection=False)
        self.outputPortsDescr.append(datatype='None', name='lastPick')
        self.outputPortsDescr.append(datatype='viewer', name='viewer')
        self.outputPortsDescr.append(datatype='None', name='redraw')
        self.setFunction("""def doit(self, geometries):
    self.updateScene(geometries)
    self.outputData(viewer=self, redraw=1)
""")

    def updateScene(self, geometries):
        geoms = [g for g in G.flatten(geometries if geometries is not None else [])
                 if g.kind != 'container']
        # one name per geometry object: two geometries with the same name
        # (two isocontour macros...) get "name (2)" instead of replacing
        # each other, and keep their name from run to run
        if not hasattr(self, '_keys'):
            self._keys = {}
        live = {id(g) for g in geoms}
        self._keys = {k: v for k, v in self._keys.items() if k in live}
        new = {}
        for g in geoms:
            key = self._keys.get(id(g))
            if key is None or key.split(' (')[0] != g.fullName():
                base = key = g.fullName()
                taken = set(self._keys.values())
                k = 2
                while key in taken:
                    key = '%s (%d)' % (base, k)
                    k += 1
                self._keys[id(g)] = key
            new[key] = g
        changed = []
        for name, g in new.items():
            key = (id(g), g.version)
            if self.sent.get(name) != key:
                changed.append({'name': name, 'version': g.version})
            self.sent[name] = key
        removed = [n for n in list(self.sent) if n not in new]
        for n in removed:
            del self.sent[n]
        self.geoms = new
        if (changed or removed) and self.network is not None:
            self.network.emit('scene', viewer=self.id, changed=changed, removed=removed)

    # ---- called by the session for the page ---------------------------------------------
    def geomsJSON(self, names=None):
        out = []
        for name, g in self.geoms.items():
            if names is None or name in names:
                d = g.to_json()
                d['name'] = name
                out.append(d)
        return out

    def sceneState(self):
        return {'viewer': self.id, 'name': self.name, 'geoms': self.geomsJSON(),
                'camera': self.camera, 'background': self.background,
                'rendering': dict(self.rendering), 'renderer': self.renderer,
                'cameras': dict(self.cameras), 'molstar': self.molstarCanvas,
                'legends': dict(self.legends)}

    def setView(self, view, renderer='3dmol'):
        if renderer in (None, '3dmol'):
            self.camera = view
        elif renderer in RENDERERS:
            self.cameras[renderer] = view
        else:
            raise ValueError('unknown renderer %r (one of %s)' % (renderer, ', '.join(RENDERERS)))

    def setLegend(self, name, opts):
        """Place and look of a color map legend on the page: x, y (its corner,
        in fractions of the view), vertical, labels (how many numbers), size,
        title, frame. None forgets them (the legend goes back to its corner)."""
        if opts is None:
            self.legends.pop(name, None)
        elif isinstance(opts, dict):
            keep = {'x', 'y', 'vertical', 'labels', 'size', 'title', 'frame'}
            self.legends[name] = {k: v for k, v in opts.items() if k in keep}
        else:
            raise ValueError('legend settings are a dict')

    def setRenderer(self, renderer):
        """Draw with '3dmol' or 'molstar'."""
        if renderer not in RENDERERS:
            raise ValueError('unknown renderer %r (one of %s)' % (renderer, ', '.join(RENDERERS)))
        self.renderer = renderer
        if self.network is not None:
            self.network.emit('viewer', op='renderer', node=self.id, renderer=renderer)

    def setMolstarSettings(self, settings):
        """Mol*'s rendering settings (its canvas3d props: postprocessing,
        cameraFog, illumination...), as the page reads them; None for the
        defaults."""
        if settings is not None and not isinstance(settings, dict):
            raise ValueError('Mol* settings are a dict')
        self.molstarCanvas = settings
        if self.network is not None:
            self.network.emit('viewer', op='canvas', node=self.id, molstar=settings)

    def setRendering(self, **kw):
        """Silhouettes and fog (see RENDERING for the options)."""
        for k, v in kw.items():
            if k not in RENDERING:
                raise ValueError('unknown rendering option %r (options: %s)'
                                 % (k, ', '.join(sorted(RENDERING))))
            default = RENDERING[k]
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, float):
                v = float(v)
            else:
                v = str(v)
            self.rendering[k] = v
        if self.network is not None:
            self.network.emit('viewer', op='rendering', node=self.id,
                              rendering=dict(self.rendering))

    snapshotTimeout = 15.0      # seconds to wait for the page's picture

    def snapshot(self, timeout=None):
        """The picture this viewer shows on the page, as a PIL image. The
        page draws the viewer, so it is asked for it ('snapshot_request');
        it answers through the session (snapshotReceived)."""
        import base64
        import io
        import itertools
        import threading
        from PIL import Image
        if not hasattr(self, '_snaps'):
            self._snaps, self._snapIds = {}, itertools.count(1)
        rid = '%s-%d' % (self.id, next(self._snapIds))
        done = threading.Event()
        self._snaps[rid] = [done, None]
        self.network.emit('snapshot_request', viewer=self.id, request=rid)
        if not done.wait(self.snapshotTimeout if timeout is None else timeout):
            self._snaps.pop(rid, None)
            raise RuntimeError('no page sent the picture of viewer %s: open the page with '
                               'this network, with the viewer showing' % self.name)
        png = self._snaps.pop(rid)[1]
        data = base64.b64decode(png.split(',', 1)[1])
        return Image.open(io.BytesIO(data)).convert('RGBA')

    def snapshotReceived(self, rid, png):
        entry = getattr(self, '_snaps', {}).get(rid)
        if entry is not None and entry[1] is None:
            entry[1] = png
            entry[0].set()

    def viewChanged(self):
        """The view moved on the page (rotation, zoom...: a redraw in DejaVu):
        the nodes connected to the redraw output run, as in Vision (e.g. One
        Redraw -> Grab Image follows the view). Runs asked for while one is
        going on are merged by the runner."""
        p = self.outputPortByName['redraw']
        children = [c.node for c in p.children]
        if not children or self.network is None:
            return False
        self.outputData(redraw=1)
        for c in children:
            c.forceExecution = 1
        self.network.run(children)
        return True

    def picked(self, body):
        d = {'geom': body.get('geom'), 'object': self.geoms.get(body.get('geom'))}
        for k in ('atom', 'index', 'position'):
            if body.get(k) is not None:
                d[k] = body[k]
        obj = d['object']
        if obj is not None and d.get('atom') is not None and getattr(obj, 'mol', None) is not None:
            idx = d['atom'].get('index')
            ids = getattr(obj, 'atomIndices', None)
            if idx is not None and ids is not None and 0 <= idx < len(ids):
                d['atomIndex'] = int(ids[idx])
        self.network.emit('pick', node=self.id, geom=d['geom'], atom=body.get('atom'))
        self.outputData(lastPick=d)
        p = self.outputPortByName['lastPick']
        children = [c.node for c in p.children]
        for c in children:
            c.forceExecution = 1
        if children:
            self.network.run(children)

    def getStateForSaving(self):
        st = {}
        if self.camera:
            st['camera'] = self.camera
        if self.background:
            st['background'] = self.background
        if self.rendering != RENDERING:
            st['rendering'] = dict(self.rendering)
        if self.renderer != RENDERERS[0]:
            st['renderer'] = self.renderer
        if self.cameras:
            st['cameras'] = dict(self.cameras)
        if self.molstarCanvas:
            st['molstar'] = self.molstarCanvas
        if self.legends:
            st['legends'] = dict(self.legends)
        return st

    def setStateFromSaving(self, st):
        self.camera = st.get('camera')
        self.background = st.get('background')
        self.renderer = st.get('renderer') if st.get('renderer') in RENDERERS else RENDERERS[0]
        self.cameras = {k: v for k, v in (st.get('cameras') or {}).items() if k in RENDERERS}
        self.molstarCanvas = st.get('molstar') or None
        self.legends = dict(st.get('legends') or {})
        self.rendering = dict(RENDERING)
        self.rendering.update({k: v for k, v in (st.get('rendering') or {}).items()
                               if k in RENDERING})

    def afterAddingToNetwork(self):
        # a pick is an event fed back into the network: connections from
        # lastPick are non blocking unless asked otherwise
        self.outputPortByName['lastPick'].nonBlockingByDefault = True
        self.network.emit('viewer', op='add', node=self.id, name=self.name)

    def describe(self):
        d = NetworkNode.describe(self)
        d['viewer'] = True
        return d


vizlib = NodeLibrary('3D Visualization', '#B48EDA',
                     doc='Geometry nodes and a 3D viewer (3Dmol.js), replacing DejaVu')
vizlib.addType(GeomType())
vizlib.addType(ViewerType())

vizlib.addNode(Viewer, 'Viewer', 'Output')
vizlib.addNode(Spheres, 'Spheres', 'Geometry')
vizlib.addNode(Points, 'points', 'Geometry')
vizlib.addNode(Cylinders, 'Cylinders', 'Geometry')
vizlib.addNode(IndexedPolylines, 'IndPolylines', 'Geometry')
vizlib.addNode(IndexedPolygons, 'IndPolygons', 'Geometry')
vizlib.addNode(Labels, 'GlfLabels', 'Geometry')
vizlib.addNode(BoxNE, 'box', 'Geometry')
vizlib.addNode(AxisNE, 'axis', 'Geometry')
vizlib.addNode(GeomContainer, 'GeomContainer', 'Geometry')
vizlib.addNode(GeomOptions, 'Set Geom Options', 'Input')
vizlib.addNode(ReadMesh, 'Read Mesh', 'Input')
vizlib.addNode(ColorMap, 'Color Map', 'Mapper')
vizlib.addNode(OneRedraw, 'One Redraw', 'Output')
