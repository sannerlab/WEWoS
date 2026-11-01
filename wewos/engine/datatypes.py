# Ported to Python 3 from MGLTools NetworkEditor/datatypes.py
# Original: Michel Sanner, Daniel Stoffler (TSRI, 2001); revision Guillaume Vareille.
# Port: Michel Sanner, PhD. Copyright (c) 2026.
"""Port data types.

AnyArrayType describes single values or arrays of a given shape; a datashape
'(0,3)' is a list of 3-vectors whose leading dimension is optional. AnyType is
the older, shape-less family (list, dict, vector...). The TypeManager maps
type names (and on-the-fly shaped synonyms such as 'float(0,3)') to instances.

Changes from the Python 2 original: UserDict comes from collections, the
Tk-only 'tkcolor' type validates CSS-like color strings instead of asking Tk,
and every type can describe itself as JSON for the browser (`describe`).
"""
import array
import warnings
from collections import UserDict

import numpy


class AnyArrayType(dict):
    """Base class for types of ports handling single values or arrays.

    name      : key in the type manager, e.g. 'float' or 'float(0,3)'
    datashape : '(d1,d2,...)' each dimension 0 (any, leading 0s optional),
                x, >x, <x, >=x, <=x
    klass     : class of the elementary datum (used for type propagation)
    """

    def __init__(self, name='None', datashape=None, klass=None, dataDescr=None,
                 color=None, shape='diamond', width=None, height=None):
        self['name'] = name
        self['datashape'] = datashape
        self['class'] = klass
        self['dataDescr'] = dataDescr
        self['color'] = color if color is not None else 'white'
        if shape is None:
            shape = self._shape(datashape)
        self['shape'] = shape
        self['width'] = width if width is not None else 12
        if height is None:
            height = self['width'] if shape in ('circle', 'square') else 8
        self['height'] = height

        self.dimensionTest = []
        if datashape is None:
            self.lenDimensionTest = 0
        else:
            for dimlim in datashape[1:-1].split(','):
                dimlim = dimlim.strip()
                if dimlim.isdigit():
                    if int(dimlim) != 0:
                        n = int(dimlim)
                        self.dimensionTest.append(lambda x, n=n: x == n)
                    else:
                        self.dimensionTest.append(None)
                else:
                    strg = ''
                    for c in dimlim:
                        strg += ('x ' + c) if c in '<>' else c
                    self.dimensionTest.append(eval('lambda x: %s' % strg))
            self.lenDimensionTest = len(self.dimensionTest)

    # dict subclasses compare by content; keep that (TypeManager relies on it)
    __hash__ = None

    def validateDims(self, data):
        """data is a numpy array. Returns (True, data) when the shape passes,
        (False, data) when it fails, (n, data) when n optional leading
        dimensions were missing (data is reshaped to include them)."""
        missing = self.lenDimensionTest - len(data.shape)
        for i in range(missing):
            data.shape = (1,) + data.shape
        for dim, f in zip(data.shape, self.dimensionTest):
            if f is not None and not f(dim):
                return False, data
        if missing > 0:
            return missing, data
        return True, data

    def _shape(self, datashape):
        if datashape is not None:
            dims = datashape[1:-1].split(',')
            n = len(dims) * 2 - 1
            if dims[0] == '0':
                n -= 1
            return n
        return 0

    def cast(self, data):
        return False, None

    def validate(self, data):
        if self['class'] is None:
            return True, data
        if self['datashape'] is None:
            if isinstance(data, self['class']):
                return True, data
            return False, None
        try:
            arr = numpy.array(data)
            a0 = arr.ravel()[0]
            while hasattr(a0, 'shape'):
                a0 = a0.ravel()[0]
            if isinstance(a0, self['class']):
                return True, arr
            return False, None
        except Exception:
            return False, None

    def describe(self):
        return {'name': self['name'], 'color': self['color'], 'shape': self['shape'],
                'datashape': self['datashape'], 'descr': self['dataDescr']}


class AnyType(UserDict):
    """Older shape-less type; validate() returns a boolean."""

    def __init__(self, name='Old None', color='white', shape='diamond',
                 width=12, height=8, klass=None, dataDescr=None):
        UserDict.__init__(self)
        self.data['name'] = name
        self.data['dataDescr'] = dataDescr
        self.data['shape'] = shape
        self.data['width'] = width
        self.data['height'] = height
        self.data['color'] = color
        self.data['class'] = klass
        self.data['datashape'] = None

    def cast(self, data):
        return False, None

    def validate(self, data):
        return True

    def describe(self):
        return {'name': self['name'], 'color': self['color'], 'shape': self['shape'],
                'datashape': None, 'descr': self.get('dataDescr')}


class FloatType(AnyArrayType):
    def __init__(self, name='float', datashape=None, color='green',
                 shape='circle', width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape,
                              width=width, height=height, klass=float,
                              datashape=datashape)

    def validate(self, data):
        if self['datashape'] is None:
            if isinstance(data, float):
                return True, data
            return False, None
        try:
            return True, numpy.array(data, 'f')
        except Exception:
            return False, None

    def cast(self, data):
        if self['datashape'] is None:
            if isinstance(data, float):
                return True, data
            try:
                return True, float(data)
            except Exception:
                return False, data
        try:
            return True, numpy.array(data).astype('f')
        except Exception:
            return False, None


class IntType(AnyArrayType):
    def __init__(self, name='int', datashape=None, color='yellow',
                 shape='circle', width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape,
                              width=width, height=height, klass=int,
                              datashape=datashape)

    def validate(self, data):
        if self['datashape'] is None:
            if isinstance(data, (int, numpy.integer)) and not isinstance(data, bool):
                return True, data
            return False, None
        try:
            return True, numpy.array(data, 'i')
        except Exception:
            return False, None

    def cast(self, data):
        if self['datashape'] is None:
            if isinstance(data, int):
                return True, data
            try:
                return True, int(data)
            except Exception:
                return False, data
        try:
            return True, numpy.array(data).astype('i')
        except Exception:
            return False, None


class BooleanType(AnyArrayType):
    def __init__(self, name='boolean', datashape=None, color='yellow',
                 shape='rect', width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape,
                              width=width, height=height, klass=bool,
                              datashape=datashape)

    def validate(self, data):
        if self['datashape'] is None:
            if type(data) is bool:
                return True, data
            return False, None
        try:
            return True, numpy.array(data, 'B')
        except Exception:
            return False, None

    def cast(self, data):
        if self['datashape'] is None:
            if type(data) is bool:
                return True, data
            try:
                return True, bool(data)
            except Exception:
                return False, data
        try:
            return True, numpy.array(data).astype('B')
        except Exception:
            return False, None


class StringType(AnyArrayType):
    def __init__(self, name='string', datashape=None, color='white',
                 shape='oval', width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape,
                              width=width, height=height, klass=str,
                              datashape=datashape)

    def validate(self, data):
        if self['datashape'] is None:
            if type(data) is str:
                return True, data
            return False, None
        try:
            return True, numpy.array(data, 'O')
        except Exception:
            return False, None

    def cast(self, data):
        if self['datashape'] is None:
            if type(data) is str:
                return True, data
            try:
                return True, str(data)
            except Exception:
                return False, data
        try:
            return True, numpy.array(data).astype('O')
        except Exception:
            return False, None


def _anytype(name, color, shape, klass, width=12, height=12):
    t = AnyType(name=name, color=color, shape=shape, width=width, height=height,
                klass=klass)
    return t


class ListType(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'list', 'cyan', 'oval', 12, 12, list)

    def validate(self, data):
        return type(data) is list

    def cast(self, data):
        try:
            if isinstance(data, str):
                try:
                    import ast
                    lData = ast.literal_eval(data)
                except Exception:
                    lData = data
            else:
                lData = data
            try:
                lData = list(lData)
            except Exception:
                lData = [lData]
            return True, lData
        except Exception:
            return False, data


class TupleType(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'tuple', 'cyan', 'oval', 12, 12, tuple)

    def validate(self, data):
        return type(data) is tuple

    def cast(self, data):
        try:
            return True, tuple(data)
        except Exception:
            return False, data


class DictType(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'dict', 'cyan', 'oval', 12, 12, dict)

    def validate(self, data):
        return type(data) is dict


class ArrayType(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'array', 'cyan', 'oval', 12, 12, array.array)

    def validate(self, data):
        return isinstance(data, array.array)


class NumericArrayType(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'NumericArray', 'orange', 'pentagon', 12, 8,
                         numpy.ndarray)

    def validate(self, data):
        return isinstance(data, numpy.ndarray)

    def cast(self, data):
        try:
            return True, numpy.array(data)
        except Exception:
            return False, data


class VectorType(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'vector', 'cyan', 'oval', 12, 12, None)

    def validate(self, data):
        if isinstance(data, str):
            return False
        try:
            len(data)
            return True
        except Exception:
            return False

    def cast(self, data):
        if isinstance(data, str):
            return True, (data,)
        return False, None


class TriggerOut(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'triggerOut', 'orange', 'square', 12, 8)
        del self.data['class']


class TriggerIn(AnyType):
    def __init__(self):
        AnyType.__init__(self, 'triggerIn', 'orange', 'square', 12, 8)
        del self.data['class']


class TkColorType(AnyType):
    """'tkcolor' kept for old networks: a color name or #rrggbb string."""

    def __init__(self):
        AnyType.__init__(self, 'tkcolor', 'orange', 'square', 12, 8)
        del self.data['class']

    def validate(self, data):
        return isinstance(data, str) and len(data) > 0


class TypeManager(object):
    """Registry of port type instances.

    portTypeInstances: name (+datashape) -> type instance
    reverseLookUp    : class -> type instance (for type propagation)
    """

    def __init__(self):
        self.portTypeInstances = {}
        self.reverseLookUp = {}
        self.addType(AnyArrayType())
        self.addType(FloatType())
        self.addType(IntType())
        self.addType(BooleanType())
        self.addType(StringType())
        self.portTypeInstances['str'] = self.portTypeInstances['string']

        self.addSynonym('coord2', 'float', '(2)', color='green', shape='oval')
        self.addSynonym('coord3', 'float', '(3)', color='green', shape='rect')
        self.addSynonym('normal3', 'float', '(3)', color='blue', shape='rect')
        self.addSynonym('colorfloat3or4', 'float', '(>=3 and <=4)',
                        color='orange', shape='rect')
        self.addSynonym('instancemat', 'float', '(4,4)', color='cyan', shape='rect')
        self.addSynonym('indice2', 'int', '(2)', color='purple', shape='rect')
        self.addSynonym('indice2+', 'int', '(>=2)', color='purple', shape='rect')
        self.addSynonym('indice3or4', 'int', '(>=3 and <=4)', color='purple',
                        shape='rect')
        self.addSynonym('2Darray', 'float', '(>0,>0)', color='cyan')
        self.addSynonym('object', existingTypeName='None')
        self.addSynonym('colorRGB', existingTypeName='colorfloat3or4')
        self.addSynonym('colorsRGB', existingTypeName='colorRGB', datashape='(0)')
        self.addSynonym('coordinates3D', existingTypeName='coord3', datashape='(0)')
        self.addSynonym('faceIndices', existingTypeName='indice3or4', datashape='(0)')
        self.addSynonym('normals3D', existingTypeName='normal3', datashape='(0)')

        self.addType(AnyType())
        self.addType(DictType())
        self.addType(ListType())
        self.addType(TkColorType())
        self.addType(TupleType())
        self.addType(ArrayType())
        self.addType(NumericArrayType())
        self.addType(VectorType())
        self.addType(TriggerIn())
        self.addType(TriggerOut())

    def addSynonym(self, synonymName, existingTypeName=None, datashape=None,
                   color=None, shape=None, width=None, height=None):
        if existingTypeName is None:
            assert datashape is None
            parts = synonymName.split('(')
            existingTypeName = parts[0]
            if len(parts) == 2:
                datashape = '(' + parts[1]
        basic = self.portTypeInstances[existingTypeName]
        inner = basic['datashape']
        if inner is not None:
            if datashape is None:
                datashape = inner
            else:
                inner = inner.split('(')[1]
                datashape = datashape.split(')')[0] + ',' + inner
        if color is None:
            color = basic['color']
        if shape is None:
            shape = basic['shape']
        if width is None:
            width = basic['width']
        if height is None:
            height = width if shape in ('circle', 'square') else 2 * width // 3
        inst = basic.__class__(name=synonymName, datashape=datashape, color=color,
                               shape=shape, width=width, height=height)
        self.addType(inst)

    def addSynonymDict(self, d):
        self.addSynonym(d['synonymName'], existingTypeName=d.get('existingTypeName'),
                        datashape=d.get('datashape'), color=d.get('color'),
                        shape=d.get('shape'), width=d.get('width'),
                        height=d.get('height'))

    def addType(self, inst):
        if not isinstance(inst, (AnyType, AnyArrayType)):
            raise RuntimeError('bad dtypeinstance argument')
        base = inst['name'].split('(')[0]
        if inst['datashape'] is not None:
            storage = inst['name']
        else:
            storage = base
        if storage in self.portTypeInstances:
            old = self.portTypeInstances[storage]
            same = (type(old) is type(inst)) and (
                (old.data == inst.data) if isinstance(inst, AnyType) else (old == inst))
            if not same:
                warnings.warn('datatype %s already registered differently' % storage)
            return
        self.portTypeInstances[storage] = inst
        if 'class' in inst:
            k = inst['class']
            try:
                if k not in self.reverseLookUp:
                    self.reverseLookUp[k] = inst
            except TypeError:
                pass

    def getType(self, fullName):
        parts = fullName.split('(')
        typename = parts[0]
        datashape = None
        if len(parts) == 2:
            datashape = '(' + parts[1]
        if typename not in self.portTypeInstances:
            warnings.warn('base datatype %s not found in types table' % typename)
            return self.portTypeInstances['None']
        if fullName not in self.portTypeInstances:
            self.addSynonym(fullName, typename, datashape)
        return self.portTypeInstances[fullName]

    def getTypeFromClass(self, klass):
        try:
            return self.reverseLookUp.get(klass, self.reverseLookUp.get(None))
        except TypeError:
            return self.reverseLookUp.get(None)

    def get(self, key, default=None):
        return self.portTypeInstances.get(key, default)

    def describe(self):
        return {k: v.describe() for k, v in self.portTypeInstances.items()}


# one type manager for the process; libraries extend it when they load
TYPES = TypeManager()
