# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Geometry without OpenGL: what DejaVu geometries were to Vision nodes.

A Geom holds arrays (vertices, faces, colors, radii...) and drawing options;
the Viewer node sends it to the page as JSON (arrays as base64 float32 /
int32) and viewer3d.js draws it with 3Dmol.js. Geometries keep DejaVu's
Set(**kw) with its keyword names (vertices, faces, materials, vnormals,
radii, visible, instanceMatrices...), so node code written for DejaVu keeps
working, and compute nodes (surfaces, curvature...) pass these objects around.

Instance matrices are applied here, on the server: each instance becomes a
transformed copy of the vertices.
"""
import base64
import itertools

import numpy

_ids = itertools.count(1)

DEFAULT_COLOR = (0.8, 0.8, 0.8)


def b64(arr, dtype='f4'):
    a = numpy.ascontiguousarray(numpy.asarray(arr, dtype='<' + dtype))
    return {'b64': base64.b64encode(a.tobytes()).decode('ascii'), 'dtype': dtype,
            'shape': list(a.shape)}


def _rgb(c):
    """A color as a list of 3 floats in [0,1] (accepts 0-255 ints, names, #hex)."""
    if c is None:
        return None
    if isinstance(c, str):
        named = {'red': (1, 0, 0), 'green': (0, 1, 0), 'blue': (0, 0, 1), 'white': (1, 1, 1),
                 'black': (0, 0, 0), 'yellow': (1, 1, 0), 'cyan': (0, 1, 1),
                 'magenta': (1, 0, 1), 'orange': (1, .5, 0), 'grey': (.5, .5, .5),
                 'gray': (.5, .5, .5)}
        if c.startswith('#') and len(c) == 7:
            return [int(c[i:i + 2], 16) / 255. for i in (1, 3, 5)]
        return list(named.get(c.lower(), DEFAULT_COLOR))
    a = numpy.asarray(c, 'f').ravel()[:3]
    if a.max() > 1.0:
        a = a / 255.
    return [float(x) for x in a]


def _colors(c, n):
    """None, one color for all, or one color per item (n x 3 array)."""
    if c is None:
        return None, None
    a = numpy.asarray(c, 'f')
    if a.ndim == 1 or (a.ndim == 2 and a.shape[0] == 1):
        return _rgb(a.ravel()), None
    a = a[:, :3]
    if a.max() > 1.0:
        a = a / 255.
    if n and len(a) != n:
        if len(a) == 1:
            return _rgb(a[0]), None
        a = numpy.resize(a, (n, 3))
    return None, a


class Geom(object):
    """Base class: a named, possibly nested, piece of geometry."""
    kind = 'geom'

    def __init__(self, name=None, vertices=None, **kw):
        self.name = name or '%s%d' % (self.kind, next(_ids))
        self.parent = None
        self.children = []
        self.vertices = numpy.zeros((0, 3), 'f')
        self.color = list(DEFAULT_COLOR)
        self.colors = None
        self.opacity = 1.0
        self.visible = True
        self.pickable = True
        self.instanceMatrices = None
        self.version = 0
        self.options = {}
        if vertices is not None:
            kw['vertices'] = vertices
        self.Set(**kw)

    # ---- DejaVu-style configuration ------------------------------------------------
    def Set(self, redo=None, **kw):
        if 'vertices' in kw and kw['vertices'] is not None:
            v = numpy.asarray(kw.pop('vertices'), 'f')
            self.vertices = v.reshape(-1, 3) if v.size else numpy.zeros((0, 3), 'f')
        for key in ('materials', 'colors', 'color'):
            if key in kw:
                c = kw.pop(key)
                if c is not None:
                    one, many = _colors(c, len(self.vertices))
                    if one is not None:
                        self.color, self.colors = one, None
                    else:
                        self.colors = many
        if 'visible' in kw:
            self.visible = bool(kw.pop('visible'))
        if 'opacity' in kw:
            self.opacity = float(kw.pop('opacity'))
        if 'transparent' in kw:
            t = kw.pop('transparent')
            if t and self.opacity == 1.0:
                self.opacity = 0.5
        if 'instanceMatrices' in kw:
            m = kw.pop('instanceMatrices')
            self.instanceMatrices = None if m is None else numpy.asarray(m, 'f').reshape(-1, 4, 4)
        if 'name' in kw and kw['name']:
            self.name = kw.pop('name')
        if 'pickable' in kw:
            self.pickable = bool(kw.pop('pickable'))
        self._set(kw)
        # DejaVu options with no meaning here are kept, not refused
        for k in ('inheritMaterial', 'quality', 'frontPolyMode', 'backPolyMode', 'culling',
                  'shading', 'lighting', 'stippleLines', 'inheritLineWidth', 'protected',
                  'lineWidth', 'pointWidth', 'outline', 'blendFunctions', 'redo', 'tagModified',
                  'inheritBackPolyMode', 'inheritFrontPolyMode', 'inheritShading'):
            if k in kw:
                self.options[k] = kw.pop(k)
        self.options.update(kw)
        self.version += 1
        return self

    def _set(self, kw):
        pass

    def getVertices(self):
        return self.vertices

    def add(self, child):
        if child.parent is not None and child in child.parent.children:
            child.parent.children.remove(child)
        child.parent = self
        self.children.append(child)
        self.version += 1

    def fullName(self):
        names = [self.name]
        p = self.parent
        while p is not None:
            names.append(p.name)
            p = p.parent
        return '|'.join(reversed(names))

    def flatten(self):
        """This geometry and all its descendants."""
        out = [self]
        for c in self.children:
            out.extend(c.flatten())
        return out

    # ---- JSON for the page ------------------------------------------------------------
    def _instances(self, v):
        """v (n x 3) repeated once per instance matrix, transformed."""
        m = self.instanceMatrices
        if m is None or len(m) == 0:
            return v
        hv = numpy.hstack([v, numpy.ones((len(v), 1), 'f')])
        return numpy.vstack([(hv @ mi.T)[:, :3] for mi in m])

    def _ninst(self):
        return 1 if self.instanceMatrices is None or len(self.instanceMatrices) == 0 \
            else len(self.instanceMatrices)

    def _color_json(self, d, n, ninst=None):
        d['color'] = self.color
        if self.colors is not None:
            c = numpy.asarray(self.colors, 'f')
            k = self._ninst() if ninst is None else ninst
            if k > 1:
                c = numpy.tile(c, (k, 1))
            d['colors'] = b64(c[:n] if len(c) >= n else numpy.resize(c, (n, 3)))

    def to_json(self):
        d = {'name': self.fullName(), 'type': self.kind, 'visible': self.visible,
             'opacity': self.opacity, 'pickable': self.pickable, 'version': self.version}
        self._json(d)
        return d

    def _json(self, d):
        pass

    def __repr__(self):
        return '<%s %s %d vertices>' % (self.__class__.__name__, self.name, len(self.vertices))


class GeomContainer(Geom):
    """A named group; draws nothing itself."""
    kind = 'container'


class Spheres(Geom):
    kind = 'spheres'

    def __init__(self, name=None, vertices=None, radii=1.0, **kw):
        self.radii = 1.0
        kw['radii'] = radii
        Geom.__init__(self, name, vertices, **kw)

    def _set(self, kw):
        for k in ('radii', 'radius'):
            if k in kw:
                r = kw.pop(k)
                if r is None:
                    continue
                a = numpy.asarray(r, 'f').ravel()
                self.radii = float(a[0]) if a.size == 1 else a

    def _json(self, d):
        v = self._instances(self.vertices)
        d['centers'] = b64(v)
        if isinstance(self.radii, numpy.ndarray):
            r = numpy.tile(numpy.resize(self.radii, len(self.vertices)), self._ninst())
            d['radii'] = b64(r)
        else:
            d['radius'] = self.radii
        self._color_json(d, len(v))


class Points(Spheres):
    """Points drawn as small spheres (3Dmol has no point sprites)."""
    kind = 'spheres'

    def __init__(self, name=None, vertices=None, size=3, **kw):
        Spheres.__init__(self, name, vertices, radii=0.08 * max(1, size) / 3., **kw)


class Cylinders(Geom):
    """Cylinders between pairs of vertices (faces: index pairs or polylines)."""
    kind = 'cylinders'

    def __init__(self, name=None, vertices=None, faces=None, radii=1.0, **kw):
        self.faces = numpy.zeros((0, 2), 'i')
        self.radii = 1.0
        self.arrows = False
        kw['faces'] = faces
        kw['radii'] = radii
        Geom.__init__(self, name, vertices, **kw)

    def _set(self, kw):
        if 'faces' in kw:
            f = kw.pop('faces')
            if f is not None:
                self.faces = _segments(f)
        for k in ('radii', 'radius'):
            if k in kw:
                r = kw.pop(k)
                if r is not None:
                    a = numpy.asarray(r, 'f').ravel()
                    self.radii = float(a[0]) if a.size == 1 else a
        if 'arrows' in kw:
            self.arrows = bool(kw.pop('arrows'))

    def _json(self, d):
        v = self.vertices
        f = self.faces
        if len(f) == 0 and len(v) > 1:
            f = numpy.array([[i, i + 1] for i in range(len(v) - 1)], 'i')
        if len(f):
            starts, ends = v[f[:, 0]], v[f[:, 1]]
        else:
            starts, ends = v[:0], v[:0]
        d['starts'] = b64(self._instances(starts))
        d['ends'] = b64(self._instances(ends))
        if isinstance(self.radii, numpy.ndarray):
            r = numpy.resize(self.radii, len(v))[f[:, 0]] if len(f) else self.radii[:0]
            d['radii'] = b64(numpy.tile(r, self._ninst()))
        else:
            d['radius'] = self.radii
        d['arrows'] = self.arrows
        n = len(starts) * self._ninst()
        if self.colors is not None:
            c = numpy.asarray(self.colors, 'f')
            c = numpy.resize(c, (len(v), 3))[f[:, 0]] if len(f) else c[:0]
            d['color'] = self.color
            d['colors'] = b64(numpy.tile(c, (self._ninst(), 1))[:n])
        else:
            d['color'] = self.color


def _segments(faces):
    """Index pairs from pairs or polylines (each polyline -> consecutive pairs)."""
    out = []
    for f in faces:
        f = list(numpy.asarray(f).ravel())
        for a, b in zip(f[:-1], f[1:]):
            if a >= 0 and b >= 0:
                out.append((int(a), int(b)))
    return numpy.array(out, 'i').reshape(-1, 2)


class IndexedPolylines(Geom):
    kind = 'lines'

    def __init__(self, name=None, vertices=None, faces=None, **kw):
        self.faces = numpy.zeros((0, 2), 'i')
        kw['faces'] = faces
        Geom.__init__(self, name, vertices, **kw)

    def _set(self, kw):
        if 'faces' in kw:
            f = kw.pop('faces')
            if f is not None:
                self.faces = _segments(f)
        kw.pop('vnormals', None)

    def _json(self, d):
        v = self.vertices
        f = self.faces
        if len(f) == 0 and len(v) > 1:
            f = numpy.array([[i, i + 1] for i in range(len(v) - 1)], 'i')
        n = len(v)
        allv = self._instances(v)
        allf = numpy.vstack([f + i * n for i in range(self._ninst())]) if len(f) else f
        d['vertices'] = b64(allv)
        d['segments'] = b64(allf, 'i4')
        self._color_json(d, len(allv))


class IndexedPolygons(Geom):
    """A triangle mesh (quads and larger polygons are split into triangles)."""
    kind = 'mesh'

    def __init__(self, name=None, vertices=None, faces=None, vnormals=None, **kw):
        self.faces = numpy.zeros((0, 3), 'i')
        self.vnormals = None
        self.wireframe = False
        kw['faces'] = faces
        if vnormals is not None:
            kw['vnormals'] = vnormals
        Geom.__init__(self, name, vertices, **kw)

    def _set(self, kw):
        if 'faces' in kw:
            f = kw.pop('faces')
            if f is not None:
                self.faces = triangles(f)
                self.vnormals = None
        if 'vnormals' in kw:
            n = kw.pop('vnormals')
            self.vnormals = None if n is None else numpy.asarray(n, 'f').reshape(-1, 3)
        if 'wireframe' in kw:
            self.wireframe = bool(kw.pop('wireframe'))
        if 'frontPolyMode' in kw and str(kw['frontPolyMode']).lower() in ('line', 'gl_line'):
            self.wireframe = True

    def getFaces(self):
        return self.faces

    def getVNormals(self):
        if self.vnormals is None or len(self.vnormals) != len(self.vertices):
            self.vnormals = vertex_normals(self.vertices, self.faces)
        return self.vnormals

    def _json(self, d):
        # the mesh once, with its instance matrices (row-major, translation in
        # the last column): the page makes the copies (Mol* instances them on
        # the graphics card), so 60 copies of a surface do not weigh 60 times
        v, f = self.vertices, self.faces
        d['vertices'] = b64(v)
        d['faces'] = b64(f, 'i4')
        d['normals'] = b64(self.getVNormals())
        d['wireframe'] = self.wireframe
        if self.instanceMatrices is not None and len(self.instanceMatrices):
            d['instances'] = [[float(x) for x in m.ravel()] for m in self.instanceMatrices]
        self._color_json(d, len(v), ninst=1)


def triangles(faces):
    """n x 3 triangle indices from triangles, quads or polygons (fan split);
    negative indices (padding) are dropped."""
    a = numpy.asarray(faces)
    if a.dtype != object and a.ndim == 2 and a.shape[1] == 3:
        return a.astype('i')
    out = []
    for f in faces:
        f = [int(x) for x in numpy.asarray(f).ravel() if x >= 0]
        for i in range(1, len(f) - 1):
            out.append((f[0], f[i], f[i + 1]))
    return numpy.array(out, 'i').reshape(-1, 3)


def vertex_normals(v, f):
    v = numpy.asarray(v, 'f')
    n = numpy.zeros_like(v)
    if len(f) == 0 or len(v) == 0:
        return n
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    fn = numpy.cross(b - a, c - a)
    for k in range(3):
        numpy.add.at(n, f[:, k], fn)
    ln = numpy.linalg.norm(n, axis=1)
    ln[ln == 0] = 1
    return n / ln[:, None]


class Labels(Geom):
    kind = 'labels'

    def __init__(self, name=None, vertices=None, labels=None, fontSize=14, **kw):
        self.labels = []
        self.fontSize = fontSize
        kw['labels'] = labels
        Geom.__init__(self, name, vertices, **kw)

    def _set(self, kw):
        if 'labels' in kw:
            l = kw.pop('labels')
            if l is not None:
                self.labels = [str(x) for x in l]
        if 'fontSize' in kw:
            self.fontSize = kw.pop('fontSize')

    def _json(self, d):
        v = self._instances(self.vertices)
        d['positions'] = b64(v)
        n = len(self.vertices)
        labels = self.labels if len(self.labels) >= n else \
            self.labels + [str(i) for i in range(len(self.labels), n)]
        d['labels'] = labels[:n] * self._ninst()
        d['fontSize'] = self.fontSize
        self._color_json(d, len(v))


GlfLabels = Labels


def Box(name=None, center=(0, 0, 0), sides=(1, 1, 1), **kw):
    """A box as 12 lines."""
    c = numpy.asarray(center, 'f')
    s = numpy.asarray(sides, 'f') / 2.
    corners = numpy.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], 'f') * s + c
    edges = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    g = IndexedPolylines(name or 'box', vertices=corners, faces=edges, **kw)
    return g


def Axis(name=None, center=(0, 0, 0), length=10.0, radius=0.3):
    """Three arrows: x red, y green, z blue."""
    c = numpy.asarray(center, 'f')
    v = numpy.vstack([c, c + (length, 0, 0), c, c + (0, length, 0), c, c + (0, 0, length)])
    g = Cylinders(name or 'axis', vertices=v, faces=[(0, 1), (2, 3), (4, 5)], radii=radius,
                  colors=[(1, 0, 0), (1, 0, 0), (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 0, 1)],
                  arrows=True)
    return g


class ColorMapLegend(Geom):
    """The legend of a color map, drawn by the viewer over its 3D view (as
    DejaVu's ColorMapLegend): the ramp, the range of values it spans, a title
    (the color map's name) and, when the color map has them, its labels. Its
    place and look (orientation, number of labels, size, frame) are set in
    the viewer and kept by the Viewer node."""
    kind = 'legend'

    def __init__(self, name=None, ramp=None, mini=0.0, maxi=1.0, title='', labels=None, **kw):
        self.ramp, self.mini, self.maxi = ramp if ramp is not None else [], mini, maxi
        self.title, self.labels = title, labels
        Geom.__init__(self, name, **kw)

    def _set(self, kw):
        for k in ('ramp', 'mini', 'maxi', 'title', 'labels'):
            if k in kw:
                setattr(self, k, kw.pop(k))

    def _json(self, d):
        d['ramp'] = [[round(float(x), 4) for x in c] for c in numpy.asarray(self.ramp, 'f').tolist()]
        d['mini'], d['maxi'] = float(self.mini), float(self.maxi)
        d['title'] = self.title or ''
        if self.labels:
            d['labels'] = [str(x) for x in self.labels]


class MolRep(Geom):
    """A molecule drawn by 3Dmol.js itself: its atoms as PDB text and the
    representations to show (cartoon, stick, sphere, line, surface...).

    styles: [[selection, style], ...] applied in order (3Dmol selection and
    style specs, e.g. [{'chain': 'A'}, {'cartoon': {'color': 'spectrum'}}]);
    surfaces: [{'type': 'VDW'|'SAS'|'MS', 'opacity': .8, 'color': ..., 'sel': {...}}];
    atomColors: optional per-atom colors (n x 3) overriding style colors.
    mol and indices keep the Python molecule and its atoms for picking."""
    kind = 'mol'

    def __init__(self, name=None, pdb='', styles=None, surfaces=None, mol=None,
                 atomColors=None, **kw):
        self.pdb = pdb
        self.styles = styles or [[{}, {'stick': {}}]]
        self.surfaces = surfaces or []
        self.mol = mol
        self.atomColors = atomColors
        self.atomIndices = None
        Geom.__init__(self, name, **kw)

    def _set(self, kw):
        for k in ('pdb', 'styles', 'surfaces', 'mol', 'atomColors', 'atomIndices'):
            if k in kw:
                setattr(self, k, kw.pop(k))

    def __repr__(self):
        n = len(self.atomIndices) if self.atomIndices is not None else self.pdb.count('\nATOM') + self.pdb.count('\nHETATM')
        reps = sorted({k for sel, st in self.styles for k in st}) + \
            ['surface %s' % s.get('type', 'VDW') for s in self.surfaces]
        return '<MolRep %s: %d atoms, drawn as %s>' % (self.name, n, ', '.join(reps) or 'nothing')

    def _json(self, d):
        d['format'] = 'pdb'
        d['data'] = self.pdb
        d['styles'] = self.styles
        d['surfaces'] = self.surfaces
        if self.instanceMatrices is not None and len(self.instanceMatrices):
            # one copy of the molecule per matrix (row-major 4x4, translation in
            # the last column, as symserv and DejaVu's instanceMatrices)
            d['instances'] = [[float(x) for x in m.ravel()] for m in self.instanceMatrices]
        if self.atomColors is not None:
            d['atomColors'] = b64(numpy.asarray(self.atomColors, 'f')[:, :3])


def instance_list(m):
    """4x4 matrices from what an instanceMatrices port receives: None, one
    matrix, a list of them, or (from several connections) a list of lists."""
    if m is None or (isinstance(m, str)):
        return None
    out = []
    def walk(x):
        if x is None or isinstance(x, str):      # an unconnected input (e.g. of a macro)
            return
        a = numpy.asarray(x, 'f')
        if a.shape == (4, 4):
            out.append(a)
        elif a.ndim == 3 and a.shape[1:] == (4, 4):
            out.extend(list(a))
        else:
            for y in x:
                walk(y)
    walk(m)
    return out or None


def flatten(objs):
    """Geometries from a value arriving on a geometry port: a geom, a list
    of geoms, nested lists; containers bring their descendants."""
    out = []
    if objs is None:
        return out
    if isinstance(objs, Geom):
        return objs.flatten()
    if isinstance(objs, (list, tuple)):
        for o in objs:
            for g in flatten(o):
                if g not in out:
                    out.append(g)
    return out
