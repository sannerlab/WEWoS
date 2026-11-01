# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""One open network: its editing operations, its runs and its folder.

The server holds the network; the page only draws it. Every operation
returns plain JSON and every change also goes out as an event (see
engine/events.py), which is how the page stays in step, including with
changes a running node makes (widget values, scene updates, printed lines).

Each session has a folder <outdir>/<name>_<stamp>_<sid6>/ holding uploads,
saved networks and an autosave of the current network.
"""
import contextlib
import datetime
import os
import re
import threading
import time

from . import compat
from .engine import Editor, Network, Runner, fileio, get_library
from .engine.events import captured
from .engine.macros import MacroInputNode, MacroNode, MacroOutputNode
from .engine.widgets import jsonable


class Refused(Exception):
    """A request the session will not carry out; the message says why."""


GRAPH_OPS = {'add', 'delete', 'connect', 'disconnect', 'paste', 'make_macro', 'explode_macro',
             'rename', 'set_code', 'unbind', 'rebind', 'add_port', 'delete_port'}

# widgets the "add port" form offers, by port type
PORT_WIDGETS = {'float': 'NEThumbWheel', 'int': 'NEThumbWheel', 'boolean': 'NECheckButton',
                'string': 'NEEntry'}


def _safe(name, default='network'):
    name = re.sub(r'[^A-Za-z0-9_.-]+', '_', name or '').strip('._')
    return name[:60] or default


class Session(object):

    def __init__(self, sid, outdir, name='network'):
        self.id = sid
        self.created = datetime.datetime.now().isoformat(timespec='seconds')
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.folder = os.path.join(outdir, '%s_%s_%s' % (_safe(name), stamp, sid[:6]))
        os.makedirs(os.path.join(self.folder, 'uploads'), exist_ok=True)
        self.lock = threading.RLock()
        self.namespace = {'__name__': '__wewos__'}
        self.net = Network(name, Editor(), workdir=self.folder)
        self.runner = Runner(wrap=self._job_context)
        self.net.runner = self.runner
        self.saved_path = None
        self.clipboard = None

    # ---- run context ---------------------------------------------------------------
    @contextlib.contextmanager
    def _job_context(self):
        """Around every run on the worker thread: printed output goes to the
        page's log, eval/assign nodes use this session's namespace."""
        compat.set_namespace(self.namespace)
        with captured(lambda text: self.net.emit('log', text=text)):
            try:
                yield
            finally:
                compat.set_namespace(None)

    @contextlib.contextmanager
    def _edit_context(self):
        with self.lock, captured(lambda text: self.net.emit('log', text=text)):
            compat.set_namespace(self.namespace)
            try:
                yield
            finally:
                compat.set_namespace(None)

    # ---- lookups ---------------------------------------------------------------------
    def node(self, nid):
        n = self.net.nodesById.get(nid or '')
        if n is None:
            raise Refused('no node %r in this network' % nid)
        return n

    def network(self, netid):
        if netid in (None, '', 'main'):
            return self.net
        n = self.node(netid)
        if not isinstance(n, MacroNode):
            raise Refused('%s is not a macro' % n.name)
        return n.macroNetwork

    def connection(self, cid):
        for net in self._all_networks():
            for c in net.connections:
                if c.id == cid:
                    return net, c
        raise Refused('no connection %r' % cid)

    def _all_networks(self):
        out = [self.net]
        for n in self.net.allNodes():
            if isinstance(n, MacroNode):
                out.append(n.macroNetwork)
        return out

    # ---- state -----------------------------------------------------------------------
    def info(self):
        return {'session': self.id, 'name': self.net.name, 'folder': self.folder,
                'created': self.created, 'saved': self.saved_path}

    def state(self):
        d = self.info()
        d['seq'] = self.net.bus.seq
        d['networks'] = {net.netid: net.describe() for net in self._all_networks()}
        d['execStatus'] = self.net.execStatus
        from .engine.library import loaded
        d['libraries'] = sorted(lib.name for lib in loaded())
        d['runOnNewData'] = bool(self.net.runOnNewData.value)
        return d

    def events(self, since, timeout=20.0):
        return self.net.bus.since(since, timeout)

    # ---- editing -----------------------------------------------------------------------
    def edit(self, op, a):
        if op in GRAPH_OPS and self.runner.running():
            raise Refused('the network is running; stop it before changing it')
        fn = getattr(self, '_op_' + op, None)
        if fn is None:
            raise Refused('unknown edit %r' % op)
        with self._edit_context():
            try:
                out = fn(a) or {}
            except (ValueError, SyntaxError, KeyError) as e:
                raise Refused(str(e))
        if op not in ('get_code', 'port_data', 'copy', 'viewer_state', 'viewer_geoms',
                      'viewer_snapshot', 'image_data'):
            self.autosave()
        out['seq'] = self.net.bus.seq
        return out

    def _op_add(self, a):
        net = self.network(a.get('net'))
        lib = get_library(a['lib'])
        node = lib.instantiate(cls=a.get('cls'), label=a.get('label'))
        x, y = (a.get('pos') or [40, 40])[:2]
        net.addNode(node, float(x), float(y))
        return {'node': node.describe()}

    def _op_delete(self, a):
        for cid in a.get('conns') or []:
            try:
                net, c = self.connection(cid)
            except Refused:
                continue
            net.deleteConnections([c])
        for nid in a.get('nodes') or []:
            n = self.net.nodesById.get(nid)
            if n is None or isinstance(n, (MacroInputNode, MacroOutputNode)):
                continue
            n.network.deleteNodes([n])
        return {}

    def _op_move(self, a):
        for nid, pos in (a.get('nodes') or {}).items():
            n = self.net.nodesById.get(nid)
            if n is not None:
                n.move(float(pos[0]), float(pos[1]))
        return {}

    def _op_arrange(self, a):
        from wewos.engine.layout import arrange
        arrange(self.network(a.get('net')))
        return {}

    def _op_connect(self, a):
        n1, p1 = a['from']
        n2, p2 = a['to']
        node1, node2 = self.node(n1), self.node(n2)
        if node1.network is not node2.network:
            raise Refused('nodes in different networks cannot be connected')
        net = node1.network
        if p1 == 'trigger' or p2 == 'runNode':
            c = net.specialConnectNodes(node1, node2, 'trigger', 'runNode')
        else:
            c = net.connectNodes(node1, node2, p1, p2, blocking=a.get('blocking'))
        return {'conn': c.describe()}

    def _op_disconnect(self, a):
        net, c = self.connection(a['conn'])
        net.deleteConnections([c])
        return {}

    def _op_set_widget(self, a):
        n = self.node(a['node'])
        p = n.inputPortByName.get(a['port'])
        if p is None or p.widget is None:
            raise Refused('port %s of %s has no widget' % (a['port'], n.name))
        p.widget.set(a.get('value'), run=bool(a.get('run', True)))
        return {'value': jsonable(p.widget.get())}

    def _op_widget_opts(self, a):
        n = self.node(a['node'])
        p = n.inputPortByName.get(a['port'])
        if p is None or p.widget is None:
            raise Refused('port %s of %s has no widget' % (a['port'], n.name))
        opts = dict(a.get('opts') or {})
        if 'master' in opts and opts['master'] not in ('node', 'ParamPanel'):
            raise Refused('a widget goes in the node or in its parameter panel')
        p.widget.configure(**opts)
        return {}

    def _op_unbind(self, a):
        n = self.node(a['node'])
        n.inputPortByName[a['port']].unbindWidget()
        self.net.emit('ports', node=n.id, ports=n.describe_ports())
        return {}

    def _op_rebind(self, a):
        n = self.node(a['node'])
        p = n.inputPortByName[a['port']]
        if p.parents:
            raise Refused('disconnect the port first')
        p.rebindWidget(run=False)
        self.net.emit('ports', node=n.id, ports=n.describe_ports())
        return {}

    def _op_rename(self, a):
        n = self.node(a['node'])
        name = (a.get('name') or '').strip()
        if not name:
            raise Refused('a node needs a name')
        n.rename(name)
        return {}

    def _op_get_code(self, a):
        n = self.node(a['node'])
        return {'code': n.sourceCode, 'modified': n.codeModified,
                'readOnly': bool(n.readOnly), 'name': n.name}

    def _op_set_code(self, a):
        n = self.node(a['node'])
        if n.readOnly and not a.get('force'):
            raise Refused('%s is read only' % n.name)
        try:
            n.setFunction(a['code'])
        except SyntaxError as e:
            raise Refused('line %s: %s' % (e.lineno, e.msg))
        return {}

    def _op_add_port(self, a):
        """Add an input or output port to a node (Vision's port editor); the
        compute function's arguments follow the input ports."""
        n = self.node(a['node'])
        if isinstance(n, (MacroNode, MacroInputNode, MacroOutputNode)):
            raise Refused('macro ports are made by connecting to the "new" port inside the macro')
        name = (a.get('name') or '').strip()
        if not name.isidentifier():
            raise Refused('a port name must be a Python identifier (it becomes an argument)')
        datatype = a.get('datatype') or 'None'
        if a.get('io') == 'out':
            if name in n.outputPortByName:
                raise Refused('%s already has an output %s' % (n.name, name))
            n.addOutputPort(name=name, datatype=datatype)
        else:
            if name in n.inputPortByName:
                raise Refused('%s already has an input %s' % (n.name, name))
            if a.get('widget'):
                w = PORT_WIDGETS.get(datatype, 'NEEntry')
                d = {'class': w, 'master': 'node', 'labelCfg': {'text': name}}
                if datatype == 'int':
                    d['type'] = 'int'
                n.widgetDescr[name] = d
            n.addInputPort(name=name, datatype=datatype, required=bool(a.get('required', True)))
        return {}

    def _op_delete_port(self, a):
        n = self.node(a['node'])
        p = (n.outputPortByName if a.get('io') == 'out' else n.inputPortByName).get(a['port'])
        if p is None:
            raise Refused('no port %s' % a['port'])
        n.deletePort(p)
        return {}

    def _op_freeze(self, a):
        n = self.node(a['node'])
        n.frozen = bool(a.get('frozen', not n.frozen))
        self.net.emit('node_frozen', node=n.id, frozen=n.frozen)
        return {}

    def _op_port_data(self, a):
        n = self.node(a['node'])
        io = a.get('io', 'out')
        ports = n.outputPortByName if io == 'out' else n.inputPortByName
        p = ports.get(a['port'])
        if p is None:
            raise Refused('no port %s' % a['port'])
        d = p.data
        try:
            import numpy
            if isinstance(d, numpy.ndarray):
                s = 'array %s %s\n%s' % (d.dtype, d.shape, numpy.array2string(d, threshold=200))
            else:
                s = repr(d)
        except Exception as e:
            s = '<%s>' % e
        if len(s) > 20000:
            s = s[:20000] + '\n... (%d characters)' % len(s)
        return {'text': s, 'type': type(d).__name__}

    def _op_copy(self, a):
        nodes = [self.node(i) for i in a.get('nodes') or []]
        ids = {n.id for n in nodes}
        entries = [fileio.node_entry(n) for n in nodes
                   if not isinstance(n, (MacroInputNode, MacroOutputNode))]
        conns = []
        for n in nodes:
            for c in n.getOutConnections():
                if c.port2.node.id in ids:
                    conns.append({'from': [c.port1.node.id, c.port1.name],
                                  'to': [c.port2.node.id, c.port2.name],
                                  'blocking': c.blocking})
        self.clipboard = {'nodes': entries, 'connections': conns}
        return {'copied': len(entries)}

    def _op_paste(self, a):
        if not self.clipboard:
            raise Refused('nothing was copied')
        net = self.network(a.get('net'))
        dx, dy = (a.get('offset') or [30, 30])[:2]
        d = {'nodes': [], 'connections': self.clipboard['connections']}
        for e in self.clipboard['nodes']:
            e = dict(e)
            e['pos'] = [e['pos'][0] + dx, e['pos'][1] + dy]
            d['nodes'].append(e)
        report = []
        ids = fileio.build(net, d, report)
        return {'nodes': [n.id for n in ids.values()], 'report': report}

    def _op_make_macro(self, a):
        """Group nodes into a new macro node: connections crossing the group
        boundary become macro ports."""
        nodes = [self.node(i) for i in a.get('nodes') or []]
        if not nodes:
            raise Refused('select nodes to group')
        net = nodes[0].network
        if any(n.network is not net for n in nodes):
            raise Refused('the nodes are not in the same network')
        if any(isinstance(n, (MacroInputNode, MacroOutputNode)) for n in nodes):
            raise Refused("a macro's input and output nodes cannot be grouped")
        group = set(id(n) for n in nodes)
        inner = {'nodes': [fileio.node_entry(n) for n in nodes], 'connections': []}
        incoming, outgoing = [], []
        for n in nodes:
            for c in n.getInConnections():
                if id(c.port1.node) in group:
                    inner['connections'].append({'from': [c.port1.node.id, c.port1.name],
                                                 'to': [n.id, c.port2.name],
                                                 'blocking': c.blocking})
                else:
                    incoming.append((c.port1.node, c.port1.name, n.id, c.port2.name, c.blocking))
            for c in n.getOutConnections():
                if id(c.port2.node) not in group:
                    outgoing.append((n.id, c.port1.name, c.port2.node, c.port2.name, c.blocking))
        cx = sum(n.posx for n in nodes) / len(nodes)
        cy = sum(n.posy for n in nodes) / len(nodes)
        minx = min(n.posx for n in nodes)
        miny = min(n.posy for n in nodes)
        for e in inner['nodes']:
            e['pos'] = [e['pos'][0] - minx + 40, e['pos'][1] - miny + 90]
        name = (a.get('name') or 'macro').strip() or 'macro'
        net.deleteNodes(nodes)
        macro = MacroNode(name)
        net.addNode(macro, cx, cy)
        mnet = macro.macroNetwork
        mnet.opNode.move(200, max(e['pos'][1] for e in inner['nodes']) + 110)
        report = []
        ids = fileio.build(mnet, inner, report)
        inport = {}
        for (src, sport, nid, pname, blocking) in incoming:
            key = (nid, pname)
            if key not in inport:
                c = mnet.connectNodes(mnet.ipNode, ids[nid], 0, pname)
                inport[key] = macro.inputPorts[-1].name
            net.connectNodes(src, macro, sport, inport[key], blocking=blocking)
        outport = {}
        for (nid, pname, dst, dport, blocking) in outgoing:
            key = (nid, pname)
            if key not in outport:
                mnet.connectNodes(ids[nid], mnet.opNode, pname, 0)
                outport[key] = macro.outputPorts[-1].name
            net.connectNodes(macro, dst, outport[key], dport, blocking=blocking)
        self.net.emit('network_added', network=mnet.describe())
        return {'node': macro.id, 'report': report}

    # ---- 3D viewers ----------------------------------------------------------------
    def _viewer(self, nid):
        n = self.node(nid)
        if not hasattr(n, 'sceneState'):
            raise Refused('%s is not a viewer' % n.name)
        return n

    def _op_viewer_state(self, a):
        return self._viewer(a['node']).sceneState()

    def _op_viewer_geoms(self, a):
        return {'geoms': self._viewer(a['node']).geomsJSON(a.get('names'))}

    def _op_viewer_snapshot(self, a):
        self._viewer(a['node']).snapshotReceived(a.get('request'), a.get('png') or '')
        return {}

    def _op_image_data(self, a):
        n = self.node(a['node'])
        if not hasattr(n, 'imageData'):
            raise Refused('%s does not show images' % n.name)
        return n.imageData()

    def _op_viewer_view(self, a):
        self._viewer(a['node']).setView(a.get('view'))
        return {}

    def _op_explode_macro(self, a):
        """Replace a macro node by the nodes inside it (Vision's "expand"):
        its inner connections are kept, and every connection that went
        through one of the macro's ports is remade directly between the
        outer node and the inner node(s) behind that port."""
        macro = self.node(a['node'])
        if not isinstance(macro, MacroNode):
            raise Refused('%s is not a macro' % macro.name)
        net = macro.network
        mnet = macro.macroNetwork
        ip, op = mnet.ipNode, mnet.opNode
        inner = [n for n in mnet.nodes if n is not ip and n is not op]
        # what is behind each macro port
        targets, sources = {}, {}
        for c in mnet.connections:
            if c.port1.node is ip and c.port1.number >= 1:
                mp = macro.inputPorts[c.port1.number - 1].name
                targets.setdefault(mp, []).append((c.port2.node.id, c.port2.name, c.blocking))
            elif c.port2.node is op and c.port2.number >= 1:
                mp = macro.outputPorts[c.port2.number - 1].name
                sources.setdefault(mp, []).append((c.port1.node.id, c.port1.name))
        incoming = [(c.port1.node, c.port1.name, c.port2.name, c.blocking)
                    for c in macro.getInConnections() if c.port2 in macro.inputPorts]
        outgoing = [(c.port1.name, c.port2.node, c.port2.name, c.blocking)
                    for c in macro.getOutConnections() if c.port1 in macro.outputPorts]
        ids = {id(n) for n in inner}
        d = {'nodes': [fileio.node_entry(n) for n in inner], 'connections': []}
        for n in inner:
            for c in n.getOutConnections():
                if id(c.port2.node) in ids:
                    sp = c.port1 in n.specialOutputPorts
                    d['connections'].append({'from': [n.id, c.port1.name],
                                             'to': [c.port2.node.id, c.port2.name],
                                             'blocking': c.blocking, 'special': sp})
        # place the inner nodes where the macro was, keeping their layout
        if inner:
            x0 = min(n.posx for n in inner)
            y0 = min(n.posy for n in inner)
            for e in d['nodes']:
                e['pos'] = [e['pos'][0] - x0 + macro.posx, e['pos'][1] - y0 + macro.posy]
        net.deleteNodes([macro])
        report = []
        new = fileio.build(net, d, report)
        for (src, sport, mport, blocking) in incoming:
            for (tid, tport, tb) in targets.get(mport, []):
                try:
                    net.connectNodes(src, new[tid], sport, tport, blocking=blocking and tb)
                except ValueError as e:
                    report.append('%s.%s -> %s: %s' % (src.name, sport, tport, e))
        for (mport, dst, dport, blocking) in outgoing:
            for (sid, sport) in sources.get(mport, []):
                try:
                    net.connectNodes(new[sid], dst, sport, dport, blocking=blocking)
                except ValueError as e:
                    report.append('%s -> %s.%s: %s' % (sport, dst.name, dport, e))
        if report:
            self.net.emit('log', text=''.join('explode %s: %s\n' % (macro.name, r)
                                              for r in report))
        return {'nodes': [n.id for n in new.values()], 'report': report}

    def _op_run_on_new_data(self, a):
        self.net.runOnNewData.value = bool(a.get('value'))
        self.net.emit('run_on_new_data', value=self.net.runOnNewData.value)
        return {}

    def _op_rename_network(self, a):
        name = (a.get('name') or '').strip()
        if name:
            self.net.name = name
            self.net.emit('network_renamed', name=name)
        return {}

    # ---- running -------------------------------------------------------------------------
    def run(self, mode, nid=None, netid=None):
        net = self.network(netid)
        if mode == 'run':
            net.run()
        elif mode == 'hardrun':
            net.run(list(net.rootNodes))
        elif mode == 'run_node':
            n = self.node(nid)
            n.forceExecution = 1
            if isinstance(n, MacroNode):
                n.macroNetwork.forceExecution = 1
            n.network.run([n])
        elif mode == 'stop':
            self.net.stop()
        elif mode == 'pause':
            self.net.pause()
        elif mode == 'resume':
            self.net.resume()
        else:
            raise Refused('unknown run mode %r' % mode)
        return {'execStatus': self.net.execStatus, 'seq': self.net.bus.seq}

    # ---- files ------------------------------------------------------------------------------
    def autosave(self):
        try:
            fileio.save(self.net, os.path.join(self.folder, 'autosave.wnet.json'))
        except Exception as e:
            self.net.emit('log', text='autosave failed: %s\n' % e)

    def save(self, name=None):
        name = _safe(name or self.net.name)
        if not name.endswith('.wnet.json'):
            name += '.wnet.json'
        path = os.path.join(self.folder, name)
        with self.lock:
            fileio.save(self.net, path)
        self.saved_path = path
        self.net.emit('saved', file=name)
        return {'file': name, 'path': path}

    def load(self, data, name=None):
        """Build a saved network (dict) into this (empty) session."""
        with self._edit_context():
            report = fileio.from_dict(self.net, data)
        if name:
            self.net.filename = None
        self.autosave()
        return report

    def upload(self, name, data):
        name = _safe(os.path.basename(name or 'upload'), 'upload')
        path = os.path.join(self.folder, 'uploads', name)
        with open(path, 'wb') as fh:
            fh.write(data)
        return {'path': path, 'name': name, 'size': len(data)}

    def file_path(self, name):
        """A file of this session folder (for downloads)."""
        name = name or ''
        full = os.path.abspath(os.path.join(self.folder, name))
        if not full.startswith(os.path.abspath(self.folder) + os.sep) or not os.path.isfile(full):
            raise Refused('no file %r in this session' % name)
        return full


def list_dir(path, base):
    """Files and folders of a directory for the file browser widget."""
    path = os.path.abspath(os.path.expanduser(path or base))
    if not os.path.isdir(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise Refused('no folder %s' % path)
    entries = []
    try:
        names = sorted(os.listdir(path), key=lambda s: s.lower())
    except OSError as e:
        raise Refused(str(e))
    for n in names:
        if n.startswith('.'):
            continue
        full = os.path.join(path, n)
        try:
            st = os.stat(full)
        except OSError:
            continue
        entries.append({'name': n, 'dir': os.path.isdir(full),
                        'size': st.st_size, 'mtime': int(st.st_mtime)})
    return {'path': path, 'parent': os.path.dirname(path), 'entries': entries,
            'session': base}
