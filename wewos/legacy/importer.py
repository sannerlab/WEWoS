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
    stem = name[:-len('_net.py')] if name.endswith('_net.py') else os.path.splitext(name)[0]
    netd['name'] = stem
    libs = sorted({e['lib'] for e in _all_entries(netd) if e.get('lib') not in (None, '__builtin__')})
    return {'format': 'wewos-net', 'version': 1, 'libraries': libs, 'network': netd,
            'importedFrom': name}, report


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
                a[1] = len(ip_names)
            else:
                a[1] = ip_names.index(p1) + 1 if p1 in ip_names else p1
        else:
            a[1] = _mapped(maps, n1, p1, 'out')
        if n2.special == 'opNode':
            if p2 in ('new', 0):
                pname = n1.name.replace(' ', '_') + '_' + str(_mapped(maps, n1, p1, 'out'))
                op_names.append(pname)
                b[1] = len(op_names)
            else:
                b[1] = op_names.index(p2) + 1 if p2 in op_names else p2
        else:
            b[1] = _mapped(maps, n2, p2, 'in')
        conns.append({'from': a, 'to': b, 'blocking': bool(blocking)})
        report.connections += 1
    return {'nodes': nodes, 'connections': conns}


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
                 unsupported={'origin': origin, 'code': code,
                              'inputs': [{'name': p} for p in sorted(
                                  n.ports_seen_in | {d['name'] for d in n.added_in})],
                              'outputs': [{'name': p} for p in sorted(
                                  n.ports_seen_out | {d['name'] for d in n.added_out})]})
        return e, inmap, outmap
    lib, cls, inmap, outmap = target
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
    if n.widgetsByIndex:
        report.warnings.append('%s: widget values given by port number were not imported'
                               % n.name)
    if n.inner:
        report.warnings.append('%s: settings inside the library macro %s were not imported'
                               % (n.name, sym.cls))
    if code:
        if lib == 'Standard':
            e['code'] = code
            report.code.append(n.name)
        else:
            report.warnings.append('%s: its edited code was written for %s and was not kept'
                                   % (n.name, sym.module))
    if n.frozen:
        e['frozen'] = True
    return e, inmap, outmap


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
