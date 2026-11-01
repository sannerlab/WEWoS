# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""One-way import of Vision networks (*_net.py) into the WEWoS format.

Vision saved a network as a Python 2 script that rebuilt it. This module
does not run that script. It converts it to Python 3 syntax (lib2to3, so it
can be parsed), then walks its syntax tree with a small interpreter that
understands what the generated files do:

  * loading libraries: `from Vision.StandardNodes import stdlib`,
    `lib, msg = masterNet.getEditor().getNodeLib('vizlib', 'DejaVu...')`;
  * creating nodes: `X(constrkw={}, name=..., library=lib)` or
    `lib.nodeClassFromName['X'](...)`, then `masterNet.addNode(node, x, y)`;
  * widget values: `node.inputPortByName['p'].widget.set(v, run=False)`;
  * edited code: `node.configure(function=code)`;
  * user macros: `MacroNode(name=...)`, their `macroNetwork.addNode` and
    `connectNodes(... "new" ...)` on the macro's input and output nodes;
  * connections: `masterNet.connectNodes(n1, n2, "out", "in", blocking=...)`.

Everything else (viewer camera states, Tk menu entries, the code run when the
file was executed as a program) is recognized as not needed and skipped.
Nothing in the file is executed, so importing a network cannot run its code.

Nodes are mapped to WEWoS libraries through classmap.py; a node with no
counterpart becomes an UnsupportedNode keeping its name, ports seen in the
file, and code. The returned report lists what was mapped, what was not,
and which edited compute functions were converted to Python 3.
"""
import ast
import os
import re

from . import classmap, py2to3


class Report(object):
    def __init__(self, name):
        self.name = name
        self.nodes = 0
        self.connections = 0
        self.unmapped = []
        self.code = []
        self.warnings = []

    def as_dict(self):
        return {'file': self.name, 'nodes': self.nodes, 'connections': self.connections,
                'unmapped': self.unmapped, 'code': self.code, 'warnings': self.warnings}

    def text(self):
        lines = ['%s: %d nodes, %d connections' % (self.name, self.nodes, self.connections)]
        for u in self.unmapped:
            lines.append('  not available here: %s' % u)
        for c in self.code:
            lines.append('  edited code converted to Python 3: %s' % c)
        for w in self.warnings:
            lines.append('  %s' % w)
        return '\n'.join(lines)


# ---- recorded objects ---------------------------------------------------------------------
class Rec(object):
    """Anything the file touches that is not needed: absorbs attributes,
    items and calls."""

    def __init__(self, what='?'):
        self._what = what

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Rec('%s.%s' % (self._what, name))

    def __getitem__(self, k):
        return Rec('%s[%r]' % (self._what, k))

    def __call__(self, *a, **k):
        return Rec('%s()' % self._what)

    def __bool__(self):
        return True

    def __iter__(self):
        return iter(())


class LibSym(object):
    """A Vision node library named in the file."""

    def __init__(self, name, module):
        self.name = name
        self.module = module
        self.nodeClassFromName = _ClassTable(self)


class _ClassTable(object):
    def __init__(self, lib):
        self.lib = lib

    def __getitem__(self, cls):
        return ClassSym(self.lib.module, cls, self.lib)

    def get(self, cls, default=None):
        return self[cls]


class ModuleSym(object):
    def __init__(self, module):
        self.module = module

    def get(self, name):
        if self.module == 'NetworkEditor.macros' and name == 'MacroNode':
            return ClassSym(self.module, 'MacroNode', None)
        if name.endswith('lib') or name in ('vollib', 'molkitlib', 'vizlib', 'stdlib'):
            return LibSym(name, self.module)
        return ClassSym(self.module, name, None)


class ClassSym(object):
    def __init__(self, module, cls, lib):
        self.module = module
        self.cls = cls
        self.lib = lib

    def __call__(self, *args, **kw):
        lib = kw.get('library')
        if isinstance(lib, LibSym):
            self.lib = lib
        return NodeRec(self, kw.get('name') or self.cls, kw.get('constrkw') or {})


class NodeRec(object):
    def __init__(self, sym, name, constrkw):
        self.sym = sym
        self.name = name
        self.constrkw = constrkw
        self.pos = None
        self.net = None
        self.widgets = {}
        self.widgetsByIndex = {}
        self.code = None
        self.frozen = False
        self.special = None           # 'ipNode' / 'opNode' inside a user macro
        self.inner = {}               # library macro inner nodes by index
        self.innerChanges = []        # nodes or connections added/deleted inside a library macro
        self.ports_seen_in = set()
        self.ports_seen_out = set()
        self.added_in = []            # addInputPort(...) calls (user-added ports)
        self.added_out = []
        self.deleted = []
        self.widgetOpts = {}
        self.unbound = set()
        self.macroNetwork = NetRec(self) if sym and sym.cls == 'MacroNode' and \
            sym.module == 'NetworkEditor.macros' else _InnerNodes(self)
        self.inputPortByName = _Ports(self, 'name')
        self.inputPorts = _Ports(self, 'index')
        self.outputPorts = Rec('outputPorts')

    def configure(self, *a, **kw):
        if 'function' in kw:
            self.code = kw['function']
        if 'frozen' in kw:
            self.frozen = bool(kw['frozen'])
        if kw.get('name'):
            self.name = kw['name']

    def setFunction(self, code, *a, **k):
        self.code = code

    def addInputPort(self, *a, **kw):
        if a and isinstance(a[0], str):
            kw.setdefault('name', a[0])
        d = {k: kw[k] for k in ('name', 'datatype', 'required', 'singleConnection', 'balloon',
                                'defaultValue', 'cast') if k in kw}
        if isinstance(kw.get('_previousWidgetDescr'), dict):
            d['unboundWidget'] = _clean_widget(kw['_previousWidgetDescr'])
        if d.get('name'):
            self.added_in.append(d)
        return _Port(self, d.get('name'), 'name')

    def addOutputPort(self, *a, **kw):
        if a and isinstance(a[0], str):
            kw.setdefault('name', a[0])
        d = {k: kw[k] for k in ('name', 'datatype', 'balloon') if k in kw}
        if d.get('name'):
            self.added_out.append(d)
        return Rec('port')

    def deletePort(self, port, *a, **k):
        if isinstance(port, _Port) and isinstance(port.key, str):
            self.deleted.append(port.key)

    def move(self, x, y, *a, **k):
        self.pos = (x, y)

    def toggleFrozen_cb(self, *a, **k):
        self.frozen = not self.frozen

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Rec('%s.%s' % (self.name, name))


class _InnerNodes(object):
    """`libraryMacro.macroNetwork.nodes[i]`: settings inside a library macro."""

    def __init__(self, node):
        self.node = node
        self.nodes = self

    def __getitem__(self, i):
        if i not in self.node.inner:
            self.node.inner[i] = NodeRec(None, 'inner %s' % i, {})
        return self.node.inner[i]

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if name in ('addNode', 'connectNodes', 'deleteConnection', 'deleteNodes'):
            def change(*a, **k):
                self.node.innerChanges.append(name)
                return Rec('macroNetwork.%s()' % name)
            return change
        return Rec('macroNetwork.%s' % name)


class _Ports(object):
    def __init__(self, node, by):
        self.node = node
        self.by = by

    def __getitem__(self, k):
        return _Port(self.node, k, self.by)


class _Port(object):
    def __init__(self, node, key, by):
        self.node = node
        self.key = key
        self.by = by
        self.widget = _Widget(self)

    def configure(self, *a, **k):
        pass

    def unbindWidget(self, *a, **k):
        if self.by == 'name':
            self.node.unbound.add(self.key)

    def rebindWidget(self, *a, **k):
        if self.by == 'name':
            self.node.unbound.discard(self.key)

    def createWidget(self, *a, **kw):
        descr = kw.get('descr') or (a[0] if a and isinstance(a[0], dict) else None)
        if isinstance(descr, dict) and self.by == 'name':
            for d in self.node.added_in:
                if d.get('name') == self.key:
                    d['widget'] = _clean_widget(descr)
                    d.pop('unboundWidget', None)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Rec('port.%s' % name)


def _clean_widget(descr):
    keep = {}
    for k, v in descr.items():
        if k in ('labelGridCfg', 'widgetGridCfg', 'widgetPlacerCfg', 'NEwidgetPosition'):
            continue
        if isinstance(v, (str, int, float, bool, list, tuple, dict)) or v is None:
            keep[k] = v
    return keep


class _Widget(object):
    def __init__(self, port):
        self.port = port

    def set(self, value, run=True, *a, **k):
        p = self.port
        if p.by == 'name':
            p.node.widgets[p.key] = value
        else:
            p.node.widgetsByIndex[p.key] = value

    def configure(self, *a, **kw):
        p = self.port
        if p.by == 'name':
            p.node.widgetOpts.setdefault(p.key, {}).update(
                {k: v for k, v in kw.items() if isinstance(v, (str, int, float, bool, list, tuple))})

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Rec('widget.%s' % name)


class Editor(object):
    def __init__(self, imp):
        self.imp = imp

    def getNodeLib(self, name, module=None, version=None):
        return (LibSym(name, module or name), '')

    def addLibraryInstance(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Rec('editor.%s' % name)


class NetRec(object):
    """masterNet, or the network of a user macro."""

    def __init__(self, macro=None):
        self.macro = macro
        self.nodes = []
        self.connections = []
        self.ipNode = self.opNode = None
        if macro is not None:
            self.ipNode = NodeRec(None, 'input Ports', {})
            self.ipNode.special = 'ipNode'
            self.ipNode.net = self
            self.opNode = NodeRec(None, 'output Ports', {})
            self.opNode.special = 'opNode'
            self.opNode.net = self
        self.runOnNewData = Rec('runOnNewData')

    def getEditor(self):
        return EDITOR

    def addNode(self, node, x=None, y=None, *a, **k):
        if not isinstance(node, NodeRec):
            return
        node.pos = (x, y)
        node.net = self
        if node not in self.nodes:
            self.nodes.append(node)

    def connectNodes(self, n1, n2, p1=0, p2=0, *a, **kw):
        if isinstance(n1, NodeRec) and isinstance(n2, NodeRec):
            self.connections.append((n1, n2, p1, p2, kw.get('blocking', True), False))
        return Rec('connection')

    def specialConnectNodes(self, n1, n2, p1=0, p2=0, *a, **kw):
        if isinstance(n1, NodeRec) and isinstance(n2, NodeRec):
            self.connections.append((n1, n2, 'trigger', 'runNode', kw.get('blocking', True), True))
        return Rec('connection')

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return Rec('net.%s' % name)


EDITOR = Editor(None)


# ---- the interpreter ----------------------------------------------------------------------------
class _Skip(Exception):
    pass


class Interp(object):
    """Evaluates the statements of a generated network file against the
    recording objects above. Unknown constructs evaluate to Rec()."""

    def __init__(self, report):
        self.report = report
        self.master = NetRec()
        self.env = {'masterNet': self.master, 'None': None, 'True': True, 'False': False,
                    '__name__': 'wewos_import', '__file__': 'network.py'}

    # statements
    def run(self, body):
        for st in body:
            try:
                self.stmt(st)
            except _Skip:
                pass
            except Exception as e:
                self.report.warnings.append('line %s skipped (%s: %s)'
                                            % (getattr(st, 'lineno', '?'), type(e).__name__, e))

    def stmt(self, st):
        if isinstance(st, ast.Expr):
            self.expr(st.value)
        elif isinstance(st, ast.Assign):
            v = self.expr(st.value)
            for t in st.targets:
                self.assign(t, v)
        elif isinstance(st, ast.Try):
            self.run(st.body)
            self.run(st.orelse)
            self.run(st.finalbody)
        elif isinstance(st, ast.If):
            if self._is_main_test(st.test):
                return              # code run when the file was a program
            if self.truth(st.test):
                self.run(st.body)
            else:
                self.run(st.orelse)
        elif isinstance(st, ast.With):
            self.run(st.body)
        elif isinstance(st, ast.ImportFrom):
            mod = st.module or ''
            for a in st.names:
                if a.name == '*':
                    continue
                self.env[a.asname or a.name] = ModuleSym(mod).get(a.name)
        elif isinstance(st, ast.Import):
            for a in st.names:
                self.env[(a.asname or a.name).split('.')[0]] = Rec(a.name)
        # FunctionDef (viewer state restorers), Raise, Pass, Delete...: not needed

    def _is_main_test(self, test):
        return any(isinstance(n, ast.Name) and n.id == '__name__' for n in ast.walk(test))

    def assign(self, t, v):
        if isinstance(t, ast.Name):
            self.env[t.id] = v
        elif isinstance(t, (ast.Tuple, ast.List)):
            vals = list(v) if isinstance(v, (tuple, list)) else [Rec()] * len(t.elts)
            for tt, vv in zip(t.elts, vals):
                self.assign(tt, vv)
        # attribute / item targets: settings of objects we do not keep

    def truth(self, e):
        try:
            return bool(self.expr(e))
        except Exception:
            return True

    # expressions
    def expr(self, e):
        try:
            return ast.literal_eval(e)
        except Exception:
            pass
        if isinstance(e, ast.Name):
            return self.env.get(e.id, Rec(e.id))
        if isinstance(e, ast.Attribute):
            obj = self.expr(e.value)
            return getattr(obj, e.attr, Rec(e.attr))
        if isinstance(e, ast.Subscript):
            obj = self.expr(e.value)
            idx = e.slice.value if isinstance(e.slice, ast.Index) else e.slice
            k = self.expr(idx)
            try:
                return obj[k]
            except Exception:
                return Rec('item')
        if isinstance(e, ast.Call):
            f = self.expr(e.func)
            args = []
            for a in e.args:
                if isinstance(a, ast.Starred):
                    v = self.expr(a.value)
                    args.extend(v if isinstance(v, (list, tuple)) else [])
                else:
                    args.append(self.expr(a))
            kw = {}
            for k in e.keywords:
                if k.arg is None:
                    v = self.expr(k.value)
                    if isinstance(v, dict):
                        kw.update(v)
                else:
                    kw[k.arg] = self.expr(k.value)
            if callable(f):
                return f(*args, **kw)
            return Rec('call')
        if isinstance(e, (ast.Tuple, ast.List)):
            vals = [self.expr(x) for x in e.elts]
            return tuple(vals) if isinstance(e, ast.Tuple) else vals
        if isinstance(e, ast.Dict):
            return {self.expr(k): self.expr(v) for k, v in zip(e.keys, e.values) if k is not None}
        if isinstance(e, ast.BoolOp):
            vals = [self.truth(v) for v in e.values]
            return all(vals) if isinstance(e.op, ast.And) else any(vals)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            return not self.truth(e.operand)
        if isinstance(e, ast.Compare) and len(e.ops) == 1:
            a, b = self.expr(e.left), self.expr(e.comparators[0])
            op = e.ops[0]
            if isinstance(op, ast.Is):
                return a is b
            if isinstance(op, ast.IsNot):
                return a is not b
            if isinstance(op, ast.Eq):
                return a == b
            if isinstance(op, ast.NotEq):
                return a != b
            return True
        if isinstance(e, ast.BinOp):
            a, b = self.expr(e.left), self.expr(e.right)
            try:
                if isinstance(e.op, ast.Add):
                    return a + b
                if isinstance(e.op, ast.Mod):
                    return a % b
            except Exception:
                pass
            return Rec('binop')
        return Rec(type(e).__name__)


# ---- conversion to the WEWoS format ------------------------------------------------------------
def import_source(src, filename='network_net.py'):
    """(network dict in the .wnet.json format, Report) for a Vision network."""
    name = os.path.basename(filename or 'network_net.py')
    report = Report(name)
    try:
        py3 = py2to3.convert(src, name)
    except Exception as e:
        raise ValueError('%s is not a Vision network file Python can read (%s)' % (name, e))
    tree = ast.parse(py3)
    it = Interp(report)
    it.run(tree.body)
    if not it.master.nodes:
        raise ValueError('%s defines no nodes; is it a Vision network (*_net.py)?' % name)
    ids = {}
    _note_ports(it.master)
    netd = _network(it.master, ids, report)
    _apply_saved_opacity(netd, _saved_opacities(tree))
    stem = name[:-len('_net.py')] if name.endswith('_net.py') else os.path.splitext(name)[0]
    netd['name'] = stem
    libs = sorted({e['lib'] for e in _all_entries(netd) if e.get('lib') not in (None, '__builtin__')})
    return {'format': 'wewos-net', 'version': 1, 'libraries': libs, 'network': netd,
            'importedFrom': name}, report


def _saved_opacities(tree):
    """The opacity and color of the viewer objects, from the functions in
    which Vision saved a viewer's state (loadSavedStates_<viewer>):
    {object name: opacity} and {object name: [r, g, b]} (a single diffuse
    color; per-vertex colors come from the network)."""
    out, colors = {}, {}

    def walk(body, ctx):
        for st in body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                v, name = st.value, st.targets[0].id
                if isinstance(v, ast.Dict):
                    ctx['state'] = v
                elif isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and \
                        v.func.attr == 'FindObjectByName' and v.args and isinstance(v.args[0], ast.Str):
                    ctx['vars'][name] = v.args[0].s.split('|')[-1]
            elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
                f = st.value.func
                # obj.materials[GL.GL_FRONT].Set(**state) (the back material is not what one sees)
                if isinstance(f, ast.Attribute) and f.attr == 'Set' and isinstance(f.value, ast.Subscript) \
                        and isinstance(f.value.value, ast.Attribute) and f.value.value.attr == 'materials' \
                        and isinstance(f.value.value.value, ast.Name) and ctx.get('state') is not None \
                        and 'BACK' not in ast.dump(f.value.slice).split('GL_FRONT_AND_BACK')[0]:
                    obj = ctx['vars'].get(f.value.value.value.id)
                    for k, val in zip(ctx['state'].keys, ctx['state'].values):
                        if obj and isinstance(k, ast.Str) and k.s == 'opacity':
                            try:
                                o = ast.literal_eval(val)
                                out[obj] = float(o[0] if isinstance(o, (list, tuple)) else o)
                            except (ValueError, TypeError, IndexError):
                                pass
                        elif obj and isinstance(k, ast.Str) and k.s == 'diffuse':
                            try:
                                d = ast.literal_eval(val)
                                if len(d) == 1 and len(d[0]) >= 3:
                                    colors[obj] = [round(float(x), 4) for x in d[0][:3]]
                            except (ValueError, TypeError, IndexError):
                                pass
            for field in ('body', 'orelse', 'finalbody'):
                if isinstance(getattr(st, field, None), list):
                    walk(getattr(st, field), ctx)

    for st in tree.body:
        if isinstance(st, ast.FunctionDef) and st.name.startswith('loadSavedStates_'):
            walk(st.body, {'vars': {}, 'state': None})
    return out, colors


def _apply_saved_opacity(netd, saved):
    """Give a geometry node the opacity and color its object had in the viewer."""
    opacities, colors = saved
    if not opacities and not colors:
        return
    from wewos.engine import get_library
    from wewos.libs.viz3d import GeometryNode
    for e in _all_entries(netd):
        if e.get('special') or not e.get('lib') or e.get('lib') == '__builtin__':
            continue
        w = e.get('widgets') or {}
        for key in (w.get('name'), w.get('geoms'), e.get('name')):
            if e['lib'] == '3D Visualization' and key and key in opacities and opacities[key] < 1 \
                    and 'opacity' in _port_names(e['lib'], e['cls'])[0]:
                w['opacity'] = round(opacities[key], 3)
                e['widgets'] = w
                break
        try:
            klass = get_library(e['lib']).nodeClassFromName.get(e.get('cls'))
        except Exception:
            klass = None
        if klass is not None and issubclass(klass, GeometryNode):
            for key in (w.get('name'), w.get('geoms'), e.get('name')):
                if key and key in colors:
                    e.setdefault('state', {}).setdefault('geomState', {})['color'] = colors[key]
                    break


def _all_entries(netd):
    for e in netd['nodes']:
        yield e
        if 'macro' in e:
            for x in _all_entries(e['macro']):
                yield x


def _network(net, ids, report):
    nodes, conns = [], []
    maps = {}            # NodeRec -> (inmap, outmap)
    if net.macro is not None:
        for sp in (net.ipNode, net.opNode):
            ids[id(sp)] = 'n%d' % (len(ids) + 1)
            nodes.append({'id': ids[id(sp)], 'special': sp.special,
                          'pos': list(sp.pos) if sp.pos else ([200, 20] if sp.special == 'ipNode'
                                                               else [200, 280])})
    for n in net.nodes:
        ids[id(n)] = 'n%d' % (len(ids) + 1)
        e, inmap, outmap = _node_entry(n, ids, report)
        maps[id(n)] = (inmap, outmap)
        nodes.append(e)
        report.nodes += 1
    # macro input/output node ports, created by connections to 'new'
    ip_names, op_names = [], []
    renamed = ({}, {})   # Vision's name of a macro port -> ours, when an inner port was renamed
    for (n1, n2, p1, p2, blocking, special) in net.connections:
        if id(n1) not in ids or id(n2) not in ids:
            report.warnings.append('connection %s -> %s: a node was not created'
                                   % (n1.name, n2.name))
            continue
        a = [ids[id(n1)], p1]
        b = [ids[id(n2)], p2]
        if special:
            conns.append({'from': a, 'to': b, 'blocking': bool(blocking), 'special': True})
            report.connections += 1
            continue
        if n1.special == 'ipNode':
            if p1 in ('new', 0):
                pname = n2.name.replace(' ', '_') + '_' + str(_mapped(maps, n2, p2, 'in'))
                ip_names.append(pname)
                renamed[0][n2.name.replace(' ', '_') + '_' + str(p2)] = pname
                a[1] = len(ip_names)
            else:
                a[1] = ip_names.index(p1) + 1 if p1 in ip_names else p1
        else:
            a[1] = _mapped(maps, n1, p1, 'out')
        if n2.special == 'opNode':
            if p2 in ('new', 0):
                pname = n1.name.replace(' ', '_') + '_' + str(_mapped(maps, n1, p1, 'out'))
                op_names.append(pname)
                renamed[1][n1.name.replace(' ', '_') + '_' + str(p1)] = pname
                b[1] = len(op_names)
            else:
                b[1] = op_names.index(p2) + 1 if p2 in op_names else p2
        else:
            b[1] = _mapped(maps, n2, p2, 'in')
        conns.append({'from': a, 'to': b, 'blocking': bool(blocking)})
        report.connections += 1
    # Vision drew data flowing down; WEWoS lays the network out again on loading
    out = {'nodes': nodes, 'connections': conns, 'layout': 'vision'}
    if net.macro is not None:
        out['_renamed'] = tuple({k: v for k, v in r.items() if k != v} for r in renamed)
    return out


def localize_code(code):
    """Imports of MGLTools packages that WEWoS bundles, pointed at its copies
    (a grid made with another Volume package would not be a Grid3D here)."""
    import re
    code = re.sub(r'\bfrom Volume\.', 'from wewos.volcore.', code)
    for m in ('rotax', 'transformation', 'crystal', 'stats', 'VectorModule', 'TensorModule'):
        code = code.replace('from mglutil.math.%s import' % m, 'from wewos.mglmath.%s import' % m)
    return code


def _mapped(maps, node, port, io):
    m = maps.get(id(node))
    if m is None or not isinstance(port, str):
        return port
    return classmap.map_port(m[0] if io == 'in' else m[1], port)


def _node_entry(n, ids, report):
    sym = n.sym
    pos = list(n.pos) if n.pos and None not in n.pos else [20, 20 + 40 * len(ids)]
    e = {'id': ids[id(n)], 'name': n.name, 'pos': pos}
    inmap, outmap = {}, {}
    if sym.cls == 'MacroNode' and sym.module == 'NetworkEditor.macros':
        e.update(lib='__builtin__', cls='MacroNode')
        e['macro'] = _network(n.macroNetwork, ids, report)
        # its ports are named after the inner ports: follow their renames
        inmap, outmap = e['macro'].pop('_renamed', ({}, {}))
        return e, inmap, outmap
    target = classmap.lookup(sym.module, sym.cls, sym.lib.name if sym.lib else None)
    code = None
    if n.code:
        code, _ = py2to3.convert_code(n.code)
    if target is None:
        origin = {'module': sym.module, 'class': sym.cls,
                  'library': sym.lib.name if sym.lib else None}
        report.unmapped.append('%s (%s.%s)' % (n.name, sym.module, sym.cls))
        e.update(lib='__builtin__', cls='UnsupportedNode',
                 unsupported={'origin': origin, 'code': code and localize_code(code),
                              'inputs': [{'name': p} for p in sorted(
                                  n.ports_seen_in | {d['name'] for d in n.added_in})],
                              'outputs': [{'name': p} for p in sorted(
                                  n.ports_seen_out | {d['name'] for d in n.added_out})]})
        return e, inmap, outmap
    lib, cls, inmap, outmap = target
    if '*' in inmap or '*' in outmap:
        ins, outs = _port_names(lib, cls)
        inmap = dict(inmap, **{'**ports': ins}) if '*' in inmap else inmap
        outmap = dict(outmap, **{'**ports': outs}) if '*' in outmap else outmap
    e.update(lib=lib, cls=cls)
    if n.added_in or n.added_out:
        e['addPorts'] = {'in': n.added_in, 'out': n.added_out}
    if n.deleted:
        e['deletePorts'] = [classmap.map_port(inmap, x) for x in n.deleted]
    if n.widgetOpts:
        e['widgetOpts'] = {classmap.map_port(inmap, k): v for k, v in n.widgetOpts.items()}
    if n.unbound:
        e['unbound'] = sorted(classmap.map_port(inmap, k) for k in n.unbound)
    if n.widgets:
        e['widgets'] = {classmap.map_port(inmap, k): v for k, v in n.widgets.items()
                        if '*' not in inmap or k in inmap}
        known = set(_port_names(lib, cls)[0]) | {d['name'] for d in n.added_in}
        gone = sorted(k for k in e['widgets'] if known and k not in known)
        if gone:
            report.warnings.append('%s: settings of %s not kept (no such input here)'
                                   % (n.name, ', '.join(gone)))
            for k in gone:
                del e['widgets'][k]
    if n.widgetsByIndex:
        report.warnings.append('%s: widget values given by port number were not imported'
                               % n.name)
    if n.innerChanges:
        kinds = {'addNode': 'added nodes', 'connectNodes': 'added connections',
                 'deleteConnection': 'deleted connections', 'deleteNodes': 'deleted nodes'}
        report.warnings.append('%s: changes made inside the library macro %s (%s) were not '
                               'imported; it is the library\'s macro' % (n.name, sym.cls, ', '.join(
                                   kinds[k] for k in sorted(set(n.innerChanges)))))
    if n.inner:
        from wewos.engine import get_library
        from wewos.engine.macros import MacroNode
        klass = get_library(lib).nodeClassFromName.get(cls)
        if cls == sym.cls and klass is not None and issubclass(klass, MacroNode):
            # the same library macro: its inner nodes are in the same order
            inner = {str(i): {classmap.map_port({}, k): v for k, v in r.widgets.items()}
                     for i, r in n.inner.items() if r.widgets}
            if inner:
                e['innerWidgets'] = inner
        else:
            report.warnings.append('%s: settings inside the library macro %s were not imported'
                                   % (n.name, sym.cls))
    if code:
        same = lib == 'Standard' or (cls == sym.cls and classmap.family(
            sym.module, sym.lib.name if sym.lib else None) in classmap.SAME_NAMES)
        if same:
            ports = [p for p in _port_names(lib, cls)[0] + [d['name'] for d in n.added_in]
                     if p not in n.deleted]
            e['code'] = localize_code(fit_signature(code, ports))
            report.code.append(n.name)
        else:
            report.warnings.append('%s: its edited code was written for %s and was not kept'
                                   % (n.name, sym.module))
    if n.frozen:
        e['frozen'] = True
    return e, inmap, outmap


_PORTS = {}


def _port_names(lib, cls):
    """(input port names, output port names) of a WEWoS node class."""
    if (lib, cls) not in _PORTS:
        try:
            from wewos.engine import get_library
            n = get_library(lib).instantiate(cls=cls)
            _PORTS[lib, cls] = ([d['name'] for d in n.inputPortsDescr],
                                [d['name'] for d in n.outputPortsDescr])
        except Exception:
            _PORTS[lib, cls] = ([], [])
    return _PORTS[lib, cls]


def fit_signature(code, ports):
    """Node code saved by an older Vision may take fewer arguments than the
    node now has ports (Eval gained importString): its doit is given all the
    ports, by name, as the engine passes one argument per port."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    fn = next((x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'doit'), None)
    if fn is None or fn.args.vararg or not fn.body:
        return code
    args = [a.arg for a in fn.args.args][1:]
    if not ports or args == ports or not set(args) <= set(ports):
        return code
    lines = code.split('\n')
    start, end = fn.lineno - 1, fn.body[0].lineno - 1
    if end <= start:
        return code
    header = '\n'.join(lines[start:end])
    m = re.match(r'(\s*)def\s+doit\s*\(.*?\)\s*:', header, re.S)
    if m is None:
        return code
    lines[start:end] = [m.group(1) + 'def doit(self, %s):' % ', '.join(ports) + header[m.end():]]
    return '\n'.join(lines)


def _note_ports(net):
    """Record the port names each node is connected through (they become
    the ports of placeholder nodes)."""
    for (n1, n2, p1, p2, b, special) in net.connections:
        if special:
            continue
        if isinstance(p1, str) and p1 != 'new':
            n1.ports_seen_out.add(p1)
        if isinstance(p2, str) and p2 != 'new':
            n2.ports_seen_in.add(p2)
    for n in net.nodes:
        for k in n.widgets:
            n.ports_seen_in.add(k)
        if isinstance(n.macroNetwork, NetRec):
            _note_ports(n.macroNetwork)


def import_file(path):
    with open(path, 'rb') as fh:
        raw = fh.read()
    return import_source(raw.decode('utf-8', 'replace'), path)
