# Ported to Python 3 from MGLTools Vision/VPE.py (NodeLibrary, getNodeLib)
# Original: Michel Sanner, Daniel Stoffler (TSRI). Port: Michel Sanner, PhD (c) 2026.
"""Node libraries.

A library module creates a NodeLibrary and adds node classes to it under a
category (`stdlib.addNode(ThumbWheelNE, 'ThumbWheel', 'Input')`). LIBRARIES
lists the libraries the server offers; get_library() imports one on first use
and registers its types and widgets.
"""
import importlib
import inspect

from .datatypes import TYPES, AnyArrayType, AnyType
from .widgets import register_widget

# name the page and saved networks use -> (module, variable)
LIBRARIES = {
    'Standard': ('wewos.libs.standard', 'stdlib'),
    '3D Visualization': ('wewos.libs.viz3d', 'vizlib'),
    'Molecules': ('wewos.libs.molecules', 'molkitlib'),
    'SymServer': ('wewos.libs.symserv', 'symlib'),
}

_loaded = {}


class NodeLibrary(object):
    """A set of node classes, grouped by category."""

    def __init__(self, name, color='#bbbbbb', mode='readOnly', fillColor=None,
                 outlineColor=None, version='', compatibleWith=None, doc=''):
        self.name = name
        self.color = color
        self.mode = mode
        self.version = version
        self.compatibleWith = compatibleWith or []
        self.doc = doc
        self.modName = None
        self.varName = None
        self.typesTable = []
        self.synonymsTable = []
        self.widgets = []
        self.libraryDescr = {}        # {category: [entry, ...]}
        self.nodes = []
        self.nodeClassFromName = {}   # class name -> class
        self.entries = {}             # label -> entry

    def addType(self, datatype):
        assert isinstance(datatype, (AnyType, AnyArrayType))
        self.typesTable.append(datatype)
        TYPES.addType(datatype)

    def addSynonym(self, synonymName, existingTypeName=None, datashape=None,
                   color=None, shape=None, width=None, height=None):
        d = {'synonymName': synonymName, 'existingTypeName': existingTypeName,
             'datashape': datashape, 'color': color, 'shape': shape,
             'width': width, 'height': height}
        self.synonymsTable.append(d)
        if synonymName.split('(')[0] not in TYPES.portTypeInstances or '(' in synonymName:
            TYPES.addSynonymDict(dict(d))

    def addWidget(self, name, kind='json', vtype='any', defaults=None):
        """Register a widget class by name (the page draws it by its kind)."""
        if not isinstance(name, str):
            name = name.__name__
        register_widget(name, kind, vtype, defaults)
        self.widgets.append(name)

    def addNode(self, nodeClass, name, category, args=None, kw=None, sourceCode=None):
        kw = dict(kw or {})
        entry = {'cls': nodeClass, 'label': name, 'category': category,
                 'args': args or (), 'kw': kw}
        self.libraryDescr.setdefault(category, []).append(entry)
        self.entries[name] = entry
        if nodeClass not in self.nodes:
            self.nodes.append(nodeClass)
        self.nodeClassFromName[nodeClass.__name__] = nodeClass

    def entry(self, label=None, cls=None):
        if label is not None and label in self.entries:
            return self.entries[label]
        for e in self.entries.values():
            if e['cls'].__name__ == cls:
                return e
        return None

    def instantiate(self, cls=None, label=None, name=None, constrkw=None):
        """A new node from this library, by class name or palette label."""
        e = self.entry(label, cls)
        if e is None:
            klass = self.nodeClassFromName.get(cls)
            if klass is None:
                raise ValueError('library %s has no node %s' % (self.name, label or cls))
            e = {'cls': klass, 'label': cls, 'kw': {}, 'args': ()}
        kw = dict(e['kw'])
        kw.update(constrkw or {})
        if name:
            kw['name'] = name
        elif 'name' not in kw:
            kw['name'] = e['label']
        kw['library'] = self
        node = e['cls'](*e['args'], **kw)
        node.codeModified = False       # the library's own code
        node.constrkw = dict(constrkw or {})
        node.paletteLabel = e['label']
        return node

    def describe(self):
        cats = []
        for cat, entries in self.libraryDescr.items():
            cats.append({'name': cat, 'nodes': [
                {'label': e['label'], 'cls': e['cls'].__name__,
                 'doc': (inspect.getdoc(e['cls']) or '').split('\n\n')[0][:400]}
                for e in entries]})
        return {'name': self.name, 'color': self.color, 'doc': self.doc,
                'categories': cats}


def get_library(name, module=None):
    """The library called name (loading its module on first use). A module
    path, when given, is used if the name is not in LIBRARIES."""
    if name in _loaded:
        return _loaded[name]
    if name in LIBRARIES:
        module, var = LIBRARIES[name]
    else:
        for libname, (mod, var) in LIBRARIES.items():
            if var == name:
                return get_library(libname)
        if module is None:
            raise ValueError('no node library %r' % name)
        var = None
    mod = importlib.import_module(module)
    lib = None
    if var is not None:
        lib = getattr(mod, var, None)
    if lib is None:
        for v in vars(mod).values():
            if isinstance(v, NodeLibrary):
                lib = v
                break
    if lib is None:
        raise ValueError('module %s defines no NodeLibrary' % module)
    lib.modName = module
    lib.varName = var
    _loaded[name] = lib
    _loaded[lib.name] = lib
    return lib


def available():
    """[(name, error or None)] for every library the server offers."""
    out = []
    for name in LIBRARIES:
        try:
            get_library(name)
            out.append((name, None))
        except Exception as e:
            out.append((name, '%s: %s' % (type(e).__name__, e)))
    return out


def catalog():
    libs = []
    for name, err in available():
        if err:
            libs.append({'name': name, 'error': err, 'categories': []})
        else:
            libs.append(get_library(name).describe())
    from .widgets import WIDGETS
    return {'libraries': libs, 'types': TYPES.describe(),
            'widgets': {k: v['kind'] for k, v in WIDGETS.items()}}
