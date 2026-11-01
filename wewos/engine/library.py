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
    'Volume': ('wewos.libs.volume', 'vollib'),
    'Imaging': ('wewos.libs.imaging', 'imagelib'),
    'MatPlotLib': ('wewos.libs.mpl', 'matplotliblib'),
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


# libraries added by the user (a module name or a .py file on the server)
USER = {}          # name -> {'module': ...} or {'file': ...}
_errors = {}       # name -> why it could not be loaded


def _import_file(path):
    """Import a .py file as a module (its folder goes on sys.path, so it can
    import modules next to it)."""
    import importlib.util
    import os
    import sys
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise ValueError('no file %s' % path)
    folder = os.path.dirname(path)
    if folder not in sys.path:
        sys.path.append(folder)
    modname = 'wewos_user_' + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def _libraries_in(mod):
    return [v for v in vars(mod).values() if isinstance(v, NodeLibrary)]


def get_library(name, module=None):
    """The library called name, loading its module on first use (a library
    can be named by its name, e.g. 'Standard', or its variable, 'stdlib')."""
    if name in _loaded:
        return _loaded[name]
    var = None
    if name in LIBRARIES:
        module, var = LIBRARIES[name]
    elif name in USER:
        return load_user(name, **USER[name])[0]
    else:
        for libname, (mod, v) in LIBRARIES.items():
            if v == name:
                return get_library(libname)
        if module is None:
            raise ValueError('no node library %r' % name)
    try:
        mod = importlib.import_module(module)
    except Exception as e:
        _errors[name] = '%s: %s' % (type(e).__name__, e)
        raise
    lib = getattr(mod, var, None) if var else None
    if lib is None:
        libs = _libraries_in(mod)
        lib = libs[0] if libs else None
    if lib is None:
        raise ValueError('module %s defines no NodeLibrary' % module)
    lib.modName = module
    lib.varName = var
    _loaded[name] = lib
    _loaded[lib.name] = lib
    _errors.pop(name, None)
    return lib


def load_user(name=None, module=None, file=None):
    """Load a library module of the user's (by module name or file path);
    every NodeLibrary it defines is registered. Returns those libraries."""
    if file:
        mod = _import_file(file)
        src = {'file': file}
    elif module:
        mod = importlib.import_module(module)
        src = {'module': module}
    else:
        raise ValueError('give a module name or a file')
    libs = _libraries_in(mod)
    if not libs:
        raise ValueError('%s defines no NodeLibrary' % (file or module))
    for lib in libs:
        lib.modName = mod.__name__
        _loaded[lib.name] = lib
        USER[lib.name] = src
        _errors.pop(lib.name, None)
    if name and name not in _loaded:
        _loaded[name] = libs[0]
    return libs


def loaded():
    """The libraries loaded so far, each once, in the order they were loaded."""
    out = []
    for lib in _loaded.values():
        if lib not in out:
            out.append(lib)
    return out


def known():
    """Every library the server can offer, loaded or not."""
    names = list(LIBRARIES) + [n for n in USER if n not in LIBRARIES]
    for lib in loaded():
        if lib.name not in names:
            names.append(lib.name)
    out = []
    for n in names:
        lib = _loaded.get(n)
        if n in USER:
            source = USER[n]
        elif n in LIBRARIES:
            source = {'module': LIBRARIES[n][0]}
        else:
            source = {'module': getattr(lib, 'modName', None)}
        out.append({'name': n, 'loaded': lib is not None,
                    'builtin': n in LIBRARIES, 'source': source,
                    'nodes': sum(len(v) for v in lib.libraryDescr.values()) if lib else None,
                    'doc': lib.doc if lib else '', 'error': _errors.get(n)})
    return out


def available():
    """[(name, error or None)] for every library the server offers (this
    loads them all: used by checks and tests)."""
    out = []
    for name in list(LIBRARIES) + list(USER):
        try:
            get_library(name)
            out.append((name, None))
        except Exception as e:
            out.append((name, '%s: %s' % (type(e).__name__, e)))
    return out


def catalog():
    """The loaded libraries, for the palette, and the port types and widgets."""
    from .widgets import WIDGETS
    return {'libraries': [lib.describe() for lib in loaded()], 'known': known(),
            'types': TYPES.describe(),
            'widgets': {k: v['kind'] for k, v in WIDGETS.items()}}
