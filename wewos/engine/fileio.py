# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Saving and loading networks as JSON (*.wnet.json).

Vision saved a network as a Python script that rebuilt it. This format is
data:

  {"format": "wewos-net", "version": 1, "libraries": [...],
   "network": {"nodes": [...], "connections": [...]}}

A node entry holds its library, class (and palette label), name, position,
widget values, widget options that differ from the class's, the ports whose
widget was unbound, its compute function only when the user edited it, and
for a macro built by the user, its sub-network. Connections name their ports.
Inside a macro, connections from the macro's input node (or to its output
node) give the port's index: they are replayed in order through port 0
('new'), which recreates the macro's ports as Vision did.
"""
import copy
import json
import os

from .library import get_library
from .macros import MacroInputNode, MacroNode, MacroOutputNode
from .node import NetworkNode
from .widgets import jsonable

FORMAT = 'wewos-net'
VERSION = 1


class UnsupportedNode(NetworkNode):
    """Stands in for a node whose library or class is not available (for
    instance a node from an MGLTools library that was not ported). It keeps
    the original ports, name and code so the network still opens and shows
    what is missing; it does not run."""

    def __init__(self, name='unsupported', origin=None, inputs=None, outputs=None,
                 code=None, **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.origin = origin or {}
        self.originalCode = code
        for p in inputs or []:
            d = dict(p)
            d.setdefault('datatype', 'None')
            d.setdefault('singleConnection', False)   # the original's rule is unknown
            d['required'] = False
            self.inputPortsDescr.append(**_port_kw(d))
        for p in outputs or []:
            d = dict(p)
            d.setdefault('datatype', 'None')
            self.outputPortsDescr.append(**_port_kw(d))
        self.setFunction("def doit(self, *args):\n"
                         "    print('node %s is not available here (%s); it did not run'"
                         " % (self.name, self.origin.get('class', '?')))\n"
                         "    return 'Stop'\n", tagModified=False)

    def describe(self):
        d = NetworkNode.describe(self)
        d['unsupported'] = self.origin
        return d


def _port_kw(d):
    keep = ('name', 'datatype', 'required', 'singleConnection', 'balloon', 'defaultValue')
    return {k: d[k] for k in keep if k in d}


BUILTIN = {'MacroNode': MacroNode, 'UnsupportedNode': UnsupportedNode}

_default_cache = {}


def _defaults(node):
    """Widget options and source code of a fresh node of the same kind, to
    save only what the user changed."""
    key = (node.library.name if node.library else None, node.__class__.__name__,
           getattr(node, 'paletteLabel', None))
    if key not in _default_cache:
        try:
            if node.library is not None:
                fresh = node.library.instantiate(cls=node.__class__.__name__,
                                                 label=getattr(node, 'paletteLabel', None))
            else:
                fresh = node.__class__()
            wd = copy.deepcopy({k: {kk: vv for kk, vv in v.items() if kk != 'initialValue'}
                                for k, v in fresh.widgetDescr.items()})
            _default_cache[key] = (wd, fresh.sourceCode,
                                   [d['name'] for d in fresh.inputPortsDescr],
                                   [d['name'] for d in fresh.outputPortsDescr])
        except Exception:
            _default_cache[key] = ({}, None, None, None)
    return _default_cache[key]


_PORT_KEYS = ('name', 'datatype', 'required', 'singleConnection', 'balloon', 'defaultValue',
              'cast')


def _port_descr(p, io):
    d = {'name': p.name, 'datatype': p.datatypeObject['name']}
    if io == 'in':
        d.update(required=bool(p.required), singleConnection=jsonable(p.singleConnection))
        if p.defaultValue is not None:
            d['defaultValue'] = jsonable(p.defaultValue)
        if p.widget is not None:
            d['widget'] = jsonable(p.widget.getDescr())
        elif p._previousWidgetDescr:
            d['unboundWidget'] = jsonable(p._previousWidgetDescr)
    if p.balloon:
        d['balloon'] = p.balloon
    return d


# ---- save -------------------------------------------------------------------------
def node_entry(node):
    lib = node.library
    e = {'id': node.id, 'name': node.name, 'cls': node.__class__.__name__,
         'lib': lib.name if lib is not None else '__builtin__',
         'pos': [round(node.posx, 1), round(node.posy, 1)]}
    label = getattr(node, 'paletteLabel', None)
    if label:
        e['label'] = label
    if node.constrkw:
        e['constrkw'] = jsonable(node.constrkw)
    wdefaults, codeDefault, inNames, outNames = _defaults(node)
    if inNames is not None and not isinstance(node, (MacroNode, UnsupportedNode)):
        added_in = [_port_descr(p, 'in') for p in node.inputPorts if p.name not in inNames]
        added_out = [_port_descr(p, 'out') for p in node.outputPorts if p.name not in outNames]
        deleted = [n for n in inNames if n not in node.inputPortByName] + \
                  [n for n in outNames if n not in node.outputPortByName]
        if added_in or added_out:
            e['addPorts'] = {'in': added_in, 'out': added_out}
        if deleted:
            e['deletePorts'] = deleted
    widgets, opts, unbound = {}, {}, []
    for p in node.inputPorts:
        w = p.widget
        if w is not None:
            widgets[p.name] = jsonable(w.get())
            base = wdefaults.get(p.name, {})
            diff = {}
            for k, v in w.getDescr().items():
                if k in ('initialValue', 'class', 'labelCfg'):
                    continue
                if k not in base or jsonable(base[k]) != jsonable(v):
                    if k == 'master' and base.get('master', 'ParamPanel') == v:
                        continue
                    diff[k] = jsonable(v)
            if diff:
                opts[p.name] = diff
        elif p._previousWidgetDescr is not None:
            unbound.append(p.name)
    if widgets:
        e['widgets'] = widgets
    if opts:
        e['widgetOpts'] = opts
    if unbound:
        e['unbound'] = unbound
    if node.codeModified and node.sourceCode != codeDefault:
        e['code'] = node.sourceCode
    if node.frozen:
        e['frozen'] = True
    if isinstance(node, UnsupportedNode):
        e['unsupported'] = {'origin': node.origin, 'code': node.originalCode,
                            'inputs': [{'name': p.name, 'datatype': p.datatypeObject['name']}
                                       for p in node.inputPorts],
                            'outputs': [{'name': p.name, 'datatype': p.datatypeObject['name']}
                                        for p in node.outputPorts]}
    if isinstance(node, MacroNode):
        if node.__class__ is MacroNode:
            e['macro'] = network_dict(node.macroNetwork)
        else:
            # a library macro rebuilds its inside; keep its inner widget values
            inner = {}
            for i, n in enumerate(node.macroNetwork.nodes):
                vals = {p.name: jsonable(p.widget.get()) for p in n.inputPorts if p.widget}
                if vals:
                    inner[str(i)] = vals
            if inner:
                e['innerWidgets'] = inner
    if hasattr(node, 'getStateForSaving'):
        st = node.getStateForSaving()
        if st:
            e['state'] = jsonable(st)
    return e


def network_dict(net):
    from .macros import MacroNetwork
    nodes = []
    for n in net.nodes:
        if isinstance(n, (MacroInputNode, MacroOutputNode)):
            nodes.append({'id': n.id, 'special': 'ipNode' if isinstance(n, MacroInputNode)
                          else 'opNode', 'pos': [n.posx, n.posy]})
        else:
            nodes.append(node_entry(n))
    conns = []
    for c in net.connections:
        p1, p2 = c.port1, c.port2
        d = {'from': [p1.node.id, p1.name], 'to': [p2.node.id, p2.name],
             'blocking': bool(c.blocking)}
        if p1 in p1.node.specialOutputPorts or p2 in p2.node.specialInputPorts:
            d['special'] = True
        if isinstance(p1.node, MacroInputNode):
            d['from'] = [p1.node.id, p1.number]
        if isinstance(p2.node, MacroOutputNode):
            d['to'] = [p2.node.id, p2.number]
        conns.append(d)
    d = {'name': net.name, 'nodes': nodes, 'connections': conns}
    if not isinstance(net, MacroNetwork):
        d['runOnNewData'] = bool(net.runOnNewData.value)
    return d


def libraries_used(net, acc=None):
    acc = acc if acc is not None else []
    for n in net.nodes:
        if n.library is not None and n.library.name not in acc:
            acc.append(n.library.name)
        if isinstance(n, MacroNode):
            libraries_used(n.macroNetwork, acc)
    return acc


def to_dict(net):
    from wewos import __version__
    return {'format': FORMAT, 'version': VERSION, 'wewos': __version__,
            'libraries': libraries_used(net), 'network': network_dict(net)}


def _newer(saved, current):
    """True when version string saved is later than current ('0.2.0' > '0.1.0')."""
    def key(v):
        return tuple(int(x) if x.isdigit() else 0 for x in str(v).split('.'))
    try:
        return key(saved) > key(current)
    except Exception:
        return False


def save(net, path):
    d = to_dict(net)
    tmp = path + '.part'
    with open(tmp, 'w') as fh:
        json.dump(d, fh, indent=1)
    os.replace(tmp, path)
    return d


# ---- load -------------------------------------------------------------------------
def make_node(e):
    """A node from a saved entry; an UnsupportedNode when its library or class
    cannot be found (the reason is kept in node.loadError)."""
    lib, cls = e.get('lib'), e.get('cls')
    name = e.get('name') or cls
    err = None
    if 'unsupported' in e:
        u = e['unsupported']
        return UnsupportedNode(name=name, origin=u.get('origin'), inputs=u.get('inputs'),
                               outputs=u.get('outputs'), code=u.get('code'))
    if lib == '__builtin__' or lib is None:
        klass = BUILTIN.get(cls)
        if klass is not None:
            node = klass(name=name)
            node.codeModified = False
            return node
        err = 'no built-in node %s' % cls
    else:
        try:
            library = get_library(lib)
            try:
                return library.instantiate(cls=cls, label=e.get('label'), name=name,
                                           constrkw=e.get('constrkw'))
            except ValueError as x:
                err = str(x)
        except Exception as x:
            err = 'library %s: %s' % (lib, x)
    n = UnsupportedNode(name=name, origin={'library': lib, 'class': cls, 'reason': err})
    n.loadError = err
    return n


def build(net, d, report=None):
    """Add the nodes and connections of a network dict to net (an empty
    network, or a macro's network that has only its input and output nodes).
    Returns {old id: node}."""
    report = report if report is not None else []
    ids = {}
    saved = net.runOnNewData.value
    net.runOnNewData.value = False
    try:
        for e in d.get('nodes', []):
            sp = e.get('special')
            if sp:
                node = net.ipNode if sp == 'ipNode' else net.opNode
                node.move(*e.get('pos', [node.posx, node.posy]))
                ids[e['id']] = node
                continue
            node = make_node(e)
            if getattr(node, 'loadError', None):
                report.append('%s: %s' % (e.get('name'), node.loadError))
            x, y = e.get('pos', [None, None])
            net.addNode(node, x, y)
            ids[e['id']] = node
            _restore_node(node, e, report)
        _connect(net, d.get('connections', []), ids, report)
        if d.get('layout') == 'vision':
            # imported from Vision: positions made for its top-down drawing
            from .layout import arrange
            arrange(net, source='vision', emit=False)
    finally:
        net.runOnNewData.value = saved
    return ids


def _restore_node(node, e, report):
    # ports first: widgets, code and connections refer to them
    keepSig = bool(e.get('code'))
    for pname in e.get('deletePorts') or []:
        node.deletePortByName(pname, updateSignature=not keepSig)
    added = e.get('addPorts') or {}
    for d in added.get('out') or []:
        kw = {k: d[k] for k in ('name', 'datatype', 'balloon') if k in d}
        if kw.get('name') not in node.outputPortByName:
            node.addOutputPort(**kw)
    for d in added.get('in') or []:
        if d.get('name') in node.inputPortByName:
            continue
        kw = {k: d[k] for k in _PORT_KEYS if k in d}
        if d.get('widget'):
            node.widgetDescr[d['name']] = dict(d['widget'])
        node.addInputPort(updateSignature=not keepSig, **kw)
        if keepSig and d.get('widget'):
            node.inputPortByName[d['name']].createWidget()
        if d.get('unboundWidget'):
            node.inputPortByName[d['name']]._previousWidgetDescr = dict(d['unboundWidget'])
    for pname, opts in (e.get('widgetOpts') or {}).items():
        p = node.inputPortByName.get(pname)
        if p is not None and p.widget is not None:
            p.widget.configure(**opts)
    for pname, v in (e.get('widgets') or {}).items():
        p = node.inputPortByName.get(pname)
        if p is not None and p.widget is not None:
            p.widget.set(v, run=False)
    for pname in e.get('unbound') or []:
        p = node.inputPortByName.get(pname)
        if p is not None and p.widget is not None and not p.widget.lockedOnPort:
            p.unbindWidget()
    if e.get('code'):
        try:
            node.setFunction(e['code'])
        except SyntaxError as x:
            report.append('%s: saved code does not compile (%s); kept the library code'
                          % (node.name, x))
    if e.get('frozen'):
        node.frozen = True
    if 'macro' in e and isinstance(node, MacroNode):
        build(node.macroNetwork, e['macro'], report)
    if 'innerWidgets' in e and isinstance(node, MacroNode):
        inner = node.macroNetwork.nodes
        for i, vals in e['innerWidgets'].items():
            i = int(i)
            if i < len(inner):
                for pname, v in vals.items():
                    p = inner[i].inputPortByName.get(pname)
                    if p is not None and p.widget is not None:
                        p.widget.set(v, run=False)
    if 'state' in e and hasattr(node, 'setStateFromSaving'):
        try:
            node.setStateFromSaving(e['state'])
        except Exception as x:
            report.append('%s: state not restored (%s)' % (node.name, x))


def _connect(net, conns, ids, report):
    created_in = {}     # ipNode output port index (saved) -> port now
    created_out = {}

    def key(c):
        # replay macro port creation in port order
        f, t = c['from'], c['to']
        return (0 if isinstance(f[1], int) or isinstance(t[1], int) else 1,
                f[1] if isinstance(f[1], int) else 0, t[1] if isinstance(t[1], int) else 0)

    for c in sorted(conns, key=key):
        n1, n2 = ids.get(c['from'][0]), ids.get(c['to'][0])
        if n1 is None or n2 is None:
            report.append('connection %s -> %s: node missing' % (c['from'], c['to']))
            continue
        p1, p2 = c['from'][1], c['to'][1]
        try:
            if c.get('special'):
                net.specialConnectNodes(n1, n2, p1, p2, blocking=c.get('blocking', True))
                continue
            if isinstance(n1, MacroInputNode) and isinstance(p1, int):
                if p1 in created_in:
                    p1 = created_in[p1]
                else:
                    conn = net.connectNodes(n1, n2, 0, p2, blocking=c.get('blocking', True))
                    created_in[c['from'][1]] = conn.port1.name
                    continue
            if isinstance(n2, MacroOutputNode) and isinstance(p2, int):
                if p2 in created_out:
                    p2 = created_out[p2]
                else:
                    conn = net.connectNodes(n1, n2, p1, 0, blocking=c.get('blocking', True))
                    created_out[c['to'][1]] = conn.port2.name
                    continue
            net.connectNodes(n1, n2, p1, p2, blocking=c.get('blocking', True))
        except Exception as x:
            report.append('connection %s.%s -> %s.%s: %s'
                          % (n1.name, c['from'][1], n2.name, c['to'][1], x))


def from_dict(net, data):
    """Build a saved network into net. Returns the list of problems met."""
    if data.get('format') != FORMAT:
        raise ValueError('not a %s file' % FORMAT)
    report = []
    from wewos import __version__
    if data.get('wewos') and _newer(data['wewos'], __version__):
        report.append('saved by WEWoS %s, a later version than this one (%s): '
                      'some of it may not load' % (data['wewos'], __version__))
    d = data['network']
    if d.get('name'):
        net.name = d['name']
    build(net, d, report)
    if 'runOnNewData' in d:
        net.runOnNewData.value = bool(d['runOnNewData'])
    return report


def load(net, path):
    with open(path) as fh:
        data = json.load(fh)
    report = from_dict(net, data)
    net.filename = os.path.abspath(path)
    return report
