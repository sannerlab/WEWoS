# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Color maps: a ramp of RGBA colors, with an optional value range.

A color map value (the Color Map node's ramp input, edited by the page's
colormap widget) is either a preset name ('rgb', 'rwb', 'grey', 'rainbow'), a
list of colors, or a dict {'ramp': [[r, g, b, a], ...], 'mini', 'maxi', 'name'}
(Vision's NEColorMap value has the same keys).

Vision's colormap files (DejaVu ColorMap.write, e.g. MGLTools'
ViewerFramework/ColorMaps/rgb256_map.py) are Python:

    from DejaVu.colorMap import ColorMap
    cm = ColorMap(name='rgb256')
    cfg = {'name': 'rgb256', 'ramp': [[0., 0., 1., 1.], ...], 'mini': 0., 'maxi': 10.}
    apply( cm.configure, (), cfg)

read_vision() takes the cfg dict from the syntax tree (array(...) read as its
list) without running the file; write_vision() writes this form, which Vision
reads back.
"""
import ast
import math

KEYS = ('ramp', 'mini', 'maxi', 'name', 'labels')


def _num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def normalize(value):
    """A clean color map value: a preset name, or a dict holding a ramp of
    [r, g, b, a] in 0..1 (and mini, maxi, name, labels when given)."""
    if value is None or isinstance(value, str):
        return value or 'rgb'
    if isinstance(value, dict):
        out = {}
        if value.get('ramp') is not None:
            out['ramp'] = _ramp(value['ramp'])
        for k in ('mini', 'maxi'):
            if k in value:
                out[k] = _num(value[k])
        if value.get('name') is not None:
            out['name'] = str(value['name'])
        if isinstance(value.get('labels'), (list, tuple)):
            out['labels'] = [str(x) for x in value['labels']]
        if 'ramp' not in out:
            return 'rgb'
        return out
    return {'ramp': _ramp(value)}                 # a list of colors


def _ramp(r):
    out = []
    for c in list(r):
        c = [(_num(x) if _num(x) is not None else 0.) for x in list(c)[:4]]
        if len(c) == 3:
            c.append(1.)
        if len(c) == 4:
            out.append([round(min(1., max(0., x)), 5) for x in c])
    return out


def _literal(node):
    """ast.literal_eval, reading array(x, ...) as x (numpy arrays in Vision's files)."""
    if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)) and \
            (getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)) in ('array', 'asarray') \
            and node.args:
        return _literal(node.args[0])
    if isinstance(node, ast.Dict):
        return {_literal(k): _literal(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(e) for e in node.elts]
    return ast.literal_eval(node)


def read_vision(text):
    """The color map of a Vision colormap file (its source text)."""
    tree = ast.parse(text)
    cfg, name = None, None
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            if st.targets[0].id == 'cfg' and isinstance(st.value, ast.Dict):
                cfg = _literal(st.value)
            elif isinstance(st.value, ast.Call) and getattr(st.value.func, 'id', '') == 'ColorMap':
                args = [a for a in st.value.args if isinstance(a, ast.Str)]
                kws = [k.value for k in st.value.keywords if k.arg == 'name' and isinstance(k.value, ast.Str)]
                if args or kws:
                    name = (args or kws)[0].s
    if not isinstance(cfg, dict) or 'ramp' not in cfg:
        raise ValueError('not a Vision colormap file (no cfg = {... "ramp": ...})')
    cm = normalize(cfg)
    if name and 'name' not in cm:
        cm['name'] = name
    return cm


def write_vision(cm):
    """The text of a Vision colormap file for the color map cm."""
    cm = normalize(cm)
    if isinstance(cm, str):
        raise ValueError('a preset (%s) has no ramp to write' % cm)
    name = cm.get('name') or 'cmap'
    cfg = {'name': name, 'ramp': cm['ramp']}
    if cm.get('mini') is not None and cm.get('maxi') is not None and cm['maxi'] > cm['mini']:
        cfg['mini'], cfg['maxi'] = cm['mini'], cm['maxi']
    if cm.get('labels'):
        cfg['labels'] = cm['labels']
    return ('from DejaVu.colorMap import ColorMap\n'
            'cm = ColorMap(name=%r)\n'
            'cfg = %r\n'
            'apply( cm.configure, (), cfg)\n' % (name, cfg))
