# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Turn the data on a node's output port into plain values that can be
compared between Vision (Python 2.7, MGLTools 1.5.7) and WEWoS (Python 3).

This file runs under both Pythons: no f-strings, no Python 3 only syntax.

canon(obj) gives a flat dict {subkey: value}, where a value is a number, a
string, a numpy array, or ('obj', type name) for data that is not compared
(widgets, viewers, file handles...). Subkey '' is the value itself.
"""
import numpy

try:
    STR = (str, unicode)          # noqa: F821  (Python 2)
except NameError:
    STR = (str,)

MAXLIST = 200          # list elements kept one by one when they are not numbers
MAXSTR = 20000


def _arr(a):
    a = numpy.asarray(a)
    if a.dtype.kind in 'biuf':
        return numpy.array(a, dtype='float64')
    return None


def _image(obj):
    """A PIL image as an RGB(A) array."""
    im = obj
    mode = 'RGBA' if obj.mode in ('RGBA', 'LA', 'P') else 'RGB'
    if obj.mode != mode:
        im = obj.convert(mode)
    getb = getattr(im, 'tobytes', None) or getattr(im, 'tostring')
    w, h = im.size
    return numpy.frombuffer(getb(), dtype='uint8').reshape(h, w, len(mode)).astype('float64')


def _sorted(arrays):
    """Arrays in an order that does not depend on the order matplotlib made
    its artists in (it changed between versions)."""
    def key(a):
        return (a.shape, tuple(numpy.round(a.reshape(-1)[:8], 6)))
    return sorted(arrays, key=key)


def _axes(ax):
    out = {}
    lines = []
    for l in ax.get_lines():
        try:
            lines.append(numpy.array(l.get_xydata(), 'float64'))
        except Exception:
            pass
    for i, a in enumerate(_sorted(lines)):
        out['line%d' % i] = a
    out['npatches'] = float(len(ax.patches))
    hs = []
    for p in ax.patches:
        try:
            hs.append(p.get_height())
        except Exception:
            pass
    if hs:
        out['patch_heights'] = numpy.array(hs, 'float64')
    offs = []
    for c in ax.collections:
        try:
            off = numpy.array(c.get_offsets(), 'float64')
            if off.size:
                offs.append(off)
        except Exception:
            pass
    for i, a in enumerate(_sorted(offs)):
        out['coll%d' % i] = a
    return out


def _is_image(obj):
    return hasattr(obj, 'mode') and hasattr(obj, 'size') and hasattr(obj, 'convert') \
        and (hasattr(obj, 'tobytes') or hasattr(obj, 'tostring'))


def canon(obj, depth=0):
    out = {}
    if obj is None:
        return out
    if isinstance(obj, bool):
        out[''] = float(obj)
        return out
    if isinstance(obj, (int, float, numpy.integer, numpy.floating)):
        out[''] = float(obj)
        return out
    try:
        long_ = long                 # noqa: F821
        if isinstance(obj, long_):
            out[''] = float(obj)
            return out
    except NameError:
        pass
    if isinstance(obj, STR):
        out[''] = obj[:MAXSTR]
        return out
    if isinstance(obj, numpy.ndarray):
        a = _arr(obj)
        out[''] = a if a is not None else ('obj', 'ndarray-' + obj.dtype.kind)
        return out
    name = obj.__class__.__name__
    if _is_image(obj):
        out[''] = _image(obj)
        return out
    if hasattr(obj, 'get_lines') and hasattr(obj, 'patches'):          # matplotlib Axes
        for k, v in _axes(obj).items():
            out[k] = v
        return out
    if name == 'Figure' and hasattr(obj, 'get_axes'):                    # matplotlib Figure
        for i, ax in enumerate(obj.get_axes()):
            for k, v in _axes(ax).items():
                out['ax%d.%s' % (i, k)] = v
        return out
    if name == 'MolRep':           # WEWoS: a molecule the page draws (no vertices here)
        return {'': ('obj', name)}
    if hasattr(obj, 'getVertices') and callable(obj.getVertices):        # a geometry
        try:
            v = _arr(obj.getVertices())
            if v is not None:
                out['vertices'] = v.reshape(-1, 3) if v.size % 3 == 0 else v
        except Exception:
            pass
        if hasattr(obj, 'getFaces'):
            try:
                f = _arr(obj.getFaces())
                if f is not None and f.size:
                    out['faces'] = f
            except Exception:
                pass
        return out or {'': ('obj', name)}
    if hasattr(obj, 'allAtoms'):                                          # MolKit molecule
        try:
            out['coords'] = _arr(obj.allAtoms.coords)
            return out
        except Exception:
            pass
    if hasattr(obj, '_ag') and hasattr(obj._ag, 'getCoords'):            # MolKit2 molecule
        try:
            out['coords'] = _arr(obj._ag.getCoords())
            return out
        except Exception:
            pass
    if hasattr(obj, 'getCoords') and callable(obj.getCoords):            # MolKit2 selection
        try:
            out['coords'] = _arr(obj.getCoords())
            return out
        except Exception:
            pass
    if hasattr(obj, 'coords') and name.endswith('Set'):                   # MolKit node set
        try:
            out['coords'] = _arr(obj.coords)
            return out
        except Exception:
            pass
    if isinstance(obj, dict):
        if depth > 3:
            return {'': ('obj', 'dict')}
        for k in sorted(obj.keys(), key=lambda x: repr(x))[:MAXLIST]:
            for kk, vv in canon(obj[k], depth + 1).items():
                out[('%s.%s' % (k, kk)) if kk else str(k)] = vv
        return out
    if isinstance(obj, (list, tuple)):
        if len(obj) == 0:
            out[''] = numpy.zeros((0,), 'float64')
            return out
        try:
            a = numpy.array(obj)
            if a.dtype.kind in 'biuf' and a.size <= 5000000:
                out[''] = a.astype('float64')
                return out
        except Exception:
            pass
        if depth > 3:
            return {'': ('obj', name)}
        out['len'] = float(len(obj))
        for i, x in enumerate(obj[:MAXLIST]):
            for kk, vv in canon(x, depth + 1).items():
                out[('%d.%s' % (i, kk)) if kk else str(i)] = vv
        return out
    return {'': ('obj', name)}


def walk(net, prefix=''):
    """(path, node) for every node of a network, macros included; names that
    repeat get #2, #3..."""
    seen = {}
    for n in list(net.nodes):
        base = prefix + n.name
        seen[base] = seen.get(base, 0) + 1
        path = base if seen[base] == 1 else '%s#%d' % (base, seen[base])
        yield path, n
        mn = getattr(n, 'macroNetwork', None)
        if mn is not None:
            for x in walk(mn, path + '/'):
                yield x


def dump(net, is_nodata, out_base, extra=None):
    """Write out_base.json (scalars, strings, node classes) and out_base.npz
    (arrays) for every output port of every node."""
    import json
    values, arrays, nodes = {}, {}, {}
    for path, n in walk(net):
        nodes[path] = {'class': n.__class__.__name__, 'module': n.__class__.__module__,
                       'outputs': [p.name for p in n.outputPorts]}
        for p in n.outputPorts:
            d = getattr(p, 'data', None)
            if d is None or is_nodata(d):
                continue
            try:
                c = canon(d)
            except Exception as e:
                c = {'': ('obj', 'canon failed: %s' % e)}
            for k, v in c.items():
                key = '%s|%s%s' % (path, p.name, ('|' + k) if k else '')
                if isinstance(v, numpy.ndarray):
                    arrays[key] = v
                elif isinstance(v, tuple):
                    values[key] = {'obj': v[1]}
                else:
                    values[key] = v
    meta = {'nodes': nodes, 'values': values, 'arrays': sorted(arrays.keys())}
    if extra:
        meta.update(extra)
    with open(out_base + '.json', 'w') as fh:
        json.dump(meta, fh)
    if arrays:
        names = sorted(arrays.keys())
        numpy.savez_compressed(out_base + '.npz', **dict(('a%d' % i, arrays[k]) for i, k in enumerate(names)))
