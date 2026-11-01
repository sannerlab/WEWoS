# Ported to Python 3 from MGLTools NetworkEditor/net.py
# Original: Michel Sanner, Daniel Stoffler (TSRI). Port: Michel Sanner, PhD (c) 2026.
"""A network of nodes and its scheduler.

Scheduling is the original's:
  * tagSubtree marks every node reachable from the roots through blocking
    connections;
  * widthFirstChildren builds a breadth-first list in which a node is added
    only once all of its tagged blocking parents are in the list; children of
    scheduling nodes (iterate, while, macros...) are left to those nodes;
  * runNodes runs the list in order; a node returning 'Stop' removes its
    descendants from the list.

run(roots=None) is a "soft run" of the root nodes (nodes with new data run);
run(roots) is a "hard run" forcing execution of roots and their subtrees.

Differences from the original: no canvas or undo; recursion in the traversals
is replaced by loops; each runNodes call works on its own queue; when the
network has a runner (the server's background thread), run() hands the work
to it; every change is reported to the page as an event.
"""
import threading
import time
import traceback

from .events import EventBus
from .node import Editor, NetworkConnection, NetworkNode
from .ports import NO_DATA, RunChildrenInputPort, RunNodeInputPort


class _Flag(object):
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, v):
        self.value = v


class Network(object):

    def __init__(self, name='Noname', editor=None, workdir=None):
        self.name = name
        self.nodes = []
        self.rootNodes = []
        self.connections = []
        self.runOnNewData = _Flag(True)
        self.forceExecution = 0
        self.debug = False
        self.afterRunCb = None
        self.filename = None
        self.canvas = None
        self.userPanels = {}
        self.selectedNodes = []
        self.selectedConnections = []
        self.lastExecutedNodes = []
        self.RunLock = threading.Lock()
        self._editor = editor or Editor()
        self._execStatus = 'waiting'
        self._statusCond = threading.Condition()
        self._workdir = workdir
        self.runner = None          # set by the server: runs work in a thread
        self._stopRequested = False
        self.bus = EventBus()
        self._ids = 0
        self.nodesById = {}         # every node of this network and its macros

    # ---- identity / events -------------------------------------------------------
    @property
    def root(self):
        return self

    @property
    def netid(self):
        return 'main'

    def getEditor(self):
        return self.root._editor

    def getTypeManager(self):
        from .datatypes import TYPES
        return TYPES

    @property
    def editor(self):
        return self.getEditor()

    def emit(self, kind, **data):
        data['net'] = self.netid
        return self.root.bus.emit(kind, **data)

    def new_id(self, prefix='n'):
        r = self.root
        r._ids += 1
        return '%s%d' % (prefix, r._ids)

    def workdir(self):
        r = self.root
        if r.filename:
            import os
            return os.path.dirname(os.path.abspath(r.filename))
        return r._workdir

    # ---- exec status (shared by a network and its macros) ---------------------
    @property
    def execStatus(self):
        return self.root._execStatus

    @execStatus.setter
    def execStatus(self, v):
        r = self.root
        with r._statusCond:
            changed = r._execStatus != v
            r._execStatus = v
            r._statusCond.notify_all()
        if changed:
            r.bus.emit('exec_status', net='main', status=v)

    def start(self):
        self.execStatus = 'running'

    def stop(self):
        self.root._stopRequested = True
        self.execStatus = 'stop'
        for n in self.allNodes():
            try:
                n.onStoppingExecution()
            except Exception:
                traceback.print_exc()

    def pause(self):
        if self.execStatus == 'running':
            self.execStatus = 'pause'

    def resume(self):
        if self.execStatus == 'pause':
            self.execStatus = 'running'

    def togglePause(self, event=None):
        if self.execStatus == 'pause':
            self.resume()
        else:
            self.pause()

    def getExecStatus(self):
        return self.execStatus

    def checkExecStatus(self):
        """1 when execution must stop; blocks while paused."""
        r = self.root
        with r._statusCond:
            while r._execStatus == 'pause':
                r._statusCond.wait(0.5)
            return 1 if r._execStatus == 'stop' else 0

    # ---- nodes -------------------------------------------------------------------
    def allNodes(self):
        """The nodes of this network and, recursively, of its macros."""
        out = []
        for n in self.nodes:
            out.append(n)
            if n.isMacro():
                out.extend(n.macroNetwork.allNodes())
        return out

    def addNode(self, node, posx=None, posy=None, tagModified=False, undo=1):
        if node.network is not None:
            raise ValueError('node %s already belongs to network %s'
                             % (node.name, node.network.name))
        node.posx = 10 if posx is None else posx
        node.posy = (30 * len(self.nodes) + 10) if posy is None else posy
        node.id = self.new_id()
        node.beforeAddingToNetwork(self)
        self.nodes.append(node)
        node.network = self
        self.root.nodesById[node.id] = node
        node.createPorts()
        self.rootNodes.append(node)
        node.afterAddingToNetwork()
        self.emit('node_added', node=node.describe())
        from .macros import MacroNode, MacroInputNode
        if (self.runOnNewData.value is True and len(node.inputPorts) == 0
                and not isinstance(node, (MacroNode, MacroInputNode))):
            node.forceExecution = 1
            self.run([node])
        return node

    def deleteNodes(self, nodes, undo=1):
        for node in list(nodes):
            if node not in self.nodes:
                continue
            self.deleteConnections(node.getConnections(), schedule=False)
            node.beforeRemovingFromNetwork()
            if node in self.rootNodes:
                self.rootNodes.remove(node)
            if node in self.selectedNodes:
                self.selectedNodes.remove(node)
            self.nodes.remove(node)
            for n in ([node] + (node.macroNetwork.allNodes() if node.isMacro() else [])):
                self.root.nodesById.pop(n.id, None)
            self.emit('node_deleted', node=node.id)
            node.network = None

    def moveSubGraph(self, nodes, dx, dy, absolute=False, tagModified=True):
        for n in nodes:
            n.move(dx, dy, absolute=absolute)
            self.emit('node_moved', node=n.id, pos=[n.posx, n.posy])

    def getNodeByName(self, name):
        return [n for n in self.nodes if n.name == name]

    # ---- connections ---------------------------------------------------------------
    def connectNodes(self, node1, node2, portNode1=0, portNode2=0, mode='angles',
                     name=None, blocking=None, undo=1, doNotSchedule=False,
                     doNotCb=False, **kw):
        """Connect an output port of node1 to an input port of node2 (ports by
        index or name). Connecting to port 0 ('new') of a macro's input or
        output node creates a matching port on the macro, as in Vision."""
        from .macros import MacroInputNode, MacroOutputNode
        if isinstance(portNode2, str):
            ip = node2.inputPortByName.get(portNode2)
            if ip is None:
                special = node2.getSpecialInputPortByName(portNode2)
                if special is not None:
                    return self.specialConnectNodes(node1, node2, portNode1, portNode2,
                                                    blocking=blocking)
                raise ValueError('node %s has no input port %s' % (node2.name, portNode2))
        else:
            ip = node2.inputPorts[portNode2]
        if isinstance(portNode1, str):
            op = node1.outputPortByName.get(portNode1)
            if op is None:
                special = node1.getSpecialOutputPortByName(portNode1)
                if special is not None:
                    return self.specialConnectNodes(node1, node2, portNode1, portNode2,
                                                    blocking=blocking)
                raise ValueError('node %s has no output port %s' % (node1.name, portNode1))
        else:
            op = node1.outputPorts[portNode1]
        if node1 is node2:
            raise ValueError('a node cannot be connected to itself')
        for c in op.connections:
            if c.port2 is ip:
                raise ValueError('these ports are already connected')
        if ip.singleConnection is True and len(ip.parents) > 0:
            raise ValueError('port %s of %s takes a single connection'
                             % (ip.name, node2.name))
        if ip.widget is not None:
            ip.unbindWidget()       # raises when the widget is locked on its port
        if blocking is None:
            # event outputs (a viewer's lastPick) feed back into the network:
            # their connections do not make the child wait for the parent
            blocking = (False if getattr(op, 'nonBlockingByDefault', False)
                        else self.getEditor().createBlockingConnections)
        if blocking and (node1 is node2 or node1.ischild(node2)):
            # node1 is already downstream of node2: a blocking connection
            # would close a loop in which each node waits for the other and
            # none runs. Data still flows through a non-blocking one.
            blocking = False
            print('%s -> %s closes a loop: the connection is non blocking'
                  % (node1.name, node2.name))

        if isinstance(node1, MacroInputNode) and isinstance(node2, MacroOutputNode):
            raise ValueError("a macro's input node cannot feed its output node")

        for p in (op, ip):
            cb = p.callbacks['beforeConnect'][0]
            if cb is not None:
                cb(p, op, ip)

        if isinstance(node1, MacroInputNode) and op.number == 0:
            op = self._newMacroInputPort(node1, node2, ip)
        elif isinstance(node2, MacroOutputNode) and ip.number == 0:
            ip = self._newMacroOutputPort(node1, node2, op)

        if node2.isRootNode and blocking is True:
            if node2 in self.rootNodes:
                self.rootNodes.remove(node2)
            node2.isRootNode = 0

        if ip.datatypeObject['name'] == 'None' and ip.singleConnection:
            if op.datatypeObject['name'] != 'None':
                ip.setDataType(op.datatypeObject, tagModified=False)

        conn = NetworkConnection(op, ip, mode, name, blocking)
        conn.network = self
        conn.id = self.new_id('c')
        self.connections.append(conn)
        if not doNotCb:
            for p in (op, ip):
                cb = p.callbacks['afterConnect'][0]
                if cb is not None:
                    newconn = cb(p, conn)
                    if isinstance(newconn, NetworkConnection):
                        conn = newconn
        ip._newdata = True
        self.emit('connected', conn=conn.describe())
        if self.runOnNewData.value is True and not doNotSchedule:
            if not (isinstance(conn.port1.data, str) and conn.port1.data == NO_DATA):
                node2.schedule()
        return conn

    def _newMacroInputPort(self, ipNode, node2, ip):
        macroNode = ipNode.macroNode
        pdescr = dict(node2.inputPortsDescr[ip.number]) \
            if ip.number < len(node2.inputPortsDescr) else {'name': ip.name}
        name = node2.name.replace(' ', '_') + '_' + pdescr['name']
        names = [d['name'] for d in macroNode.inputPortsDescr]
        if name in names:
            name = name + '_%d' % len(ipNode.outputPorts)
        ipdescr = {k: v for k, v in pdescr.items()
                   if k not in ('beforeConnect', 'afterConnect', 'beforeDisconnect',
                                'afterDisconnect', 'inputPortClass', 'updateSignature')}
        ipdescr['name'] = name
        ipdescr['singleConnection'] = True
        ipdescr.setdefault('datatype', ip.datatypeObject['name'])
        macroNode.inputPortsDescr.append(dict(ipdescr))
        p2 = macroNode.addInputPort(**ipdescr)
        p2._newdata = 1
        p1 = ipNode.addOutputPort(name=name, datatype=ipdescr.get('datatype', 'None'))
        p1._macroDynamic = True
        return p1

    def _newMacroOutputPort(self, node1, opNode, op):
        macroNode = opNode.macroNode
        pdescr = dict(node1.outputPortsDescr[op.number]) \
            if op.number < len(node1.outputPortsDescr) else {'name': op.name}
        name = node1.name.replace(' ', '_') + '_' + pdescr['name']
        names = [d['name'] for d in macroNode.outputPortsDescr]
        if name in names:
            name = name + '_%d' % len(opNode.inputPorts)
        opdescr = {k: v for k, v in pdescr.items()
                   if k not in ('beforeConnect', 'afterConnect', 'beforeDisconnect',
                                'afterDisconnect', 'outputPortClass', 'updateSignature')}
        opdescr['name'] = name
        opdescr.setdefault('datatype', op.datatypeObject['name'])
        macroNode.outputPortsDescr.append(dict(opdescr))
        macroNode.addOutputPort(**opdescr)
        p1 = opNode.addInputPort(name=name, required=False, singleConnection='auto',
                                 datatype=opdescr.get('datatype', 'None'))
        p1._macroDynamic = True
        return p1

    def specialConnectNodes(self, node1, node2, portNode1=0, portNode2=0,
                            mode='angles', name=None, blocking=None, undo=1, **kw):
        """Connect node1's trigger output to node2's runNode input."""
        op = (node1.getSpecialOutputPortByName(portNode1) if isinstance(portNode1, str)
              else node1.specialOutputPorts[portNode1])
        ip = (node2.getSpecialInputPortByName(portNode2) if isinstance(portNode2, str)
              else node2.specialInputPorts[portNode2])
        if op is None or ip is None:
            raise ValueError('no such special port')
        if blocking is None:
            blocking = True
        conn = NetworkConnection(op, ip, mode, name, blocking)
        conn.network = self
        conn.id = self.new_id('c')
        self.connections.append(conn)
        if blocking and node2 in self.rootNodes:
            self.rootNodes.remove(node2)
            node2.isRootNode = 0
        self.emit('connected', conn=conn.describe())
        return conn

    def deleteConnections(self, connections, undo=1, schedule=True):
        for c in list(connections):
            port1, port2 = c.port1, c.port2
            if port1 is None or port2 is None:
                continue
            node2 = port2.node
            for p in (port2, port1):
                cb = p.callbacks['beforeDisconnect'][0]
                if cb is not None:
                    cb(p, c)
            self.deleteConnectionsNoCB(c)
            if hasattr(port2, 'originalDatatype') and \
                    port2.datatypeObject['name'] != port2.originalDatatype:
                port2.setDataType(port2.originalDatatype, tagModified=False)
            for p in (port2, port1):
                cb = p.callbacks['afterDisconnect'][0]
                if cb is not None:
                    cb(p, port1, port2)
            port2._newdata = True
            if getattr(port2, '_previousWidgetDescr', None) and not port2.parents \
                    and port2 in node2.inputPorts:
                port2.rebindWidget(run=False)
            if schedule and self.runOnNewData.value is True and node2.network is self \
                    and port2 in node2.inputPorts:
                node2.schedule()

    def deleteConnectionsNoCB(self, c, undo=1):
        if hasattr(c.port2, '_validationStatus'):
            c.port2._validationStatus = 'unchecked'
        if c in self.connections:
            self.connections.remove(c)
        node2 = c.port2.node
        c.port1.children.remove(c.port2)
        c.port1.connections.remove(c)
        c.port1.node.children.remove(node2)
        c.port2.parents.remove(c.port1)
        c.port2.connections.remove(c)
        node2.parents.remove(c.port1.node)
        c.port2.data = None
        c.port2._newdata = False
        self.emit('disconnected', conn=c.id)
        c.port1 = None
        c.port2 = None
        if node2.network is self:
            node2.ensureRootNode()

    def deleteConnection(self, node1, port1, node2, port2):
        if isinstance(port1, str):
            port1 = node1.outputPortByName[port1]
        if isinstance(port2, str):
            port2 = node2.inputPortByName[port2]
        for c in port1.connections:
            if c.port2 is port2:
                self.deleteConnections([c])
                return

    # ---- scheduling (the original algorithm) ----------------------------------------
    def tagSubtree(self, node, val):
        stack = [node]
        while stack:
            n = stack.pop()
            for conn in n.getOutConnections():
                node2 = conn.port2.node
                if not node2.widthFirstTag and conn.blocking is True:
                    node2.widthFirstTag = val
                    stack.append(node2)

    def setChildrenOutputToNoDataYet(self, node):
        """Reset the outputs downstream of a scheduling node (and, through a
        macro's output node, of the macro's children)."""
        from .macros import MacroOutputNode
        seen = set()
        stack = [node]
        while stack:
            n = stack.pop()
            for conn in n.getOutConnections():
                node2 = conn.port2.node
                for op in node2.outputPorts:
                    op.outputData(NO_DATA)
                if conn.blocking is True:
                    nxt = node2.macroNode if isinstance(node2, MacroOutputNode) else node2
                    if id(nxt) not in seen:
                        seen.add(id(nxt))
                        stack.append(nxt)

    def widthFirstChildren(self, nodeIndex, allNodes):
        while nodeIndex < len(allNodes):
            node = allNodes[nodeIndex]
            nodeIndex += 1
            if node.isSchedulingNode is True:
                continue
            for conn in node.getOutConnections():
                node2 = conn.port2.node
                if node2.widthFirstTag and (self.runOnNewData.value is True
                                            or node2.forceExecution) \
                        and not node2.frozen:
                    append = 1
                    if isinstance(conn.port2, (RunChildrenInputPort, RunNodeInputPort)):
                        append = 0
                        node2.forceExecution = 1
                    else:
                        for conn3 in node2.getInConnections():
                            if conn3.blocking:
                                node3 = conn3.port1.node
                                if node3.widthFirstTag:
                                    append = 0
                                    break
                                elif node3.isSchedulingNode is True and node3 in allNodes:
                                    append = 0
                                    break
                    if append:
                        allNodes.append(node2)
                        node2.widthFirstTag = 0
                    else:
                        for p in node2.specialOutputPorts:
                            for ip in p.children:
                                node3 = ip.node
                                ok = 1
                                for conn4 in node3.getInConnections():
                                    if conn4.port1.node.widthFirstTag:
                                        ok = 0
                                        break
                                if ok:
                                    allNodes.append(node3)
                                    node3.widthFirstTag = 0

    def getAllNodes(self, roots):
        """All the nodes under roots, in the order they will run."""
        if len(roots) == 0:
            return []
        for node in roots:
            node.widthFirstTag = 0
        for node in roots:
            self.tagSubtree(node, 1)
        allNodes = [n for n in roots if not n.widthFirstTag]
        if allNodes:
            self.widthFirstChildren(0, allNodes)
        sched = [n for n in allNodes if n.isSchedulingNode is True]
        others = [n for n in allNodes if n.isSchedulingNode is not True]
        allNodes = others + sched
        for node in self.nodes:
            node.widthFirstTag = 0
        return allNodes

    def getSubRunNodes(self, roots=None):
        if roots is None:
            roots = self.rootNodes
            for r in roots:
                r.forceExecution = 1
        if len(roots) == 0:
            return []
        return self.getAllNodes(roots)

    def hardrun(self):
        self.run(roots=list(self.rootNodes))

    def softrun(self):
        self.run()

    def run(self, roots=None):
        """Soft run (roots=None) or hard run of roots and their subtrees."""
        r = self.root
        if r.runner is not None and not r.runner.in_worker():
            r.runner.submit(self, roots)
            return
        if not self.RunLock.acquire(False):
            return                     # already running: as in Vision
        try:
            saved = self.runOnNewData.value
            self.runOnNewData.value = True
            if roots is None:
                roots = list(self.rootNodes)
            else:
                self.forceExecution = 1
            if len(roots) == 0:
                return
            top = self.execStatus not in ('running', 'pause')
            if top:
                self.start()
            allNodes = self.getAllNodes(roots)
            if len(allNodes):
                self.runNodes(allNodes)
                self.endOfRun(self)
            self.forceExecution = 0
            self.runOnNewData.value = saved
            if top:
                self.execStatus = 'waiting'
        finally:
            self.RunLock.release()

    def endOfRun(self, net):
        for n in self.nodes:
            if hasattr(n, 'restoreStatesFirstRun'):
                n.restoreStatesFirstRun()
                del n.restoreStatesFirstRun

    def runNodes(self, allNodes, resetList=True):
        """Run a list of nodes in the caller's thread; False if one failed."""
        queue = list(allNodes)
        allOK = True
        if resetList:
            self.lastExecutedNodes = []
        dead = set()            # nodes that stopped, or were dropped because of them
        try:
            while queue:
                node = queue.pop(0)
                if self.checkExecStatus():
                    break
                t0 = time.time()
                status = node.run(debug=self.debug)
                self.lastExecutedNodes.append([node, t0, time.time()])
                if isinstance(status, str) and status.lower() == 'stop':
                    allOK = False
                    queue = self._prune(queue, node, dead)
                elif status == 0:
                    allOK = False
                    break
        except KeyboardInterrupt:
            self.stop()
        except Exception:
            print('*** ERROR during execution')
            traceback.print_exc()
            allOK = False
        if self.afterRunCb:
            self.afterRunCb(self)
        return allOK

    @staticmethod
    def _prune(queue, stopped, dead):
        """Drop from the queue the nodes that a stopped node starves: those
        whose blocking parents have all stopped or been dropped. A node that
        still has a parent with data (a viewer fed by several geometries)
        runs, and its ports decide what to do with the missing data."""
        dead.add(stopped)
        changed = True
        while changed:
            changed = False
            for n in list(queue):
                parents = [c.port1.node for c in n.getInConnections() if c.blocking is True]
                if parents and all(p in dead for p in parents):
                    queue.remove(n)
                    dead.add(n)
                    changed = True
        return queue

    def waitForCompletion(self, timeout=None):
        r = self.root
        if r.runner is not None:
            return r.runner.wait(timeout)
        return True

    def resetWidgetValues(self):
        for n in self.nodes:
            for p in n.inputPorts:
                if p.widget is not None:
                    p.widget.set(p.widget.initialValue, run=False)

    # ---- description ---------------------------------------------------------------
    def describe(self):
        return {'id': self.netid, 'name': self.name,
                'nodes': [n.describe() for n in self.nodes],
                'connections': [c.describe() for c in self.connections],
                'execStatus': self.execStatus}


class Runner(object):
    """Runs network work on one background thread, one request at a time.
    Requests that arrive while a run is in progress are queued (a later soft
    run of the same network replaces an earlier queued one)."""

    def __init__(self, wrap=None):
        self.queue = []
        self.cond = threading.Condition()
        self.thread = None
        self.busy = False
        self.wrap = wrap            # context manager factory around each job
        self._tls = threading.local()

    def in_worker(self):
        return getattr(self._tls, 'worker', False)

    def submit(self, net, roots):
        with self.cond:
            job = (net, None if roots is None else list(roots))
            if job not in self.queue:
                self.queue.append(job)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, daemon=True)
                self.thread.start()
            self.cond.notify_all()

    def _loop(self):
        self._tls.worker = True
        while True:
            with self.cond:
                if not self.queue:
                    self.busy = False
                    self.cond.notify_all()
                    self.thread = None
                    return
                net, roots = self.queue.pop(0)
                self.busy = True
            try:
                if self.wrap is not None:
                    with self.wrap():
                        net.run(roots)
                else:
                    net.run(roots)
            except Exception:
                traceback.print_exc()
            finally:
                r = net.root
                if r._stopRequested:
                    # drop what was queued before the stop
                    with self.cond:
                        self.queue = []
                    r._stopRequested = False
                    r.execStatus = 'waiting'

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.time() + timeout
        with self.cond:
            while self.busy or self.queue:
                left = None if deadline is None else deadline - time.time()
                if left is not None and left <= 0:
                    return False
                self.cond.wait(left if left is not None else 0.5)
        return True

    def running(self):
        with self.cond:
            return self.busy or bool(self.queue)
