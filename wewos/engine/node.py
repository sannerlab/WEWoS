# Ported to Python 3 from MGLTools NetworkEditor/items.py and itemBase.py
# Original: Michel Sanner, Daniel Stoffler (TSRI). Port: Michel Sanner, PhD (c) 2026.
"""Nodes and connections.

A node class declares its ports in inputPortsDescr/outputPortsDescr, its
widgets in widgetDescr and its compute function as source code passed to
setFunction(); exactly the API of Vision's NetworkNode, so library nodes port
mechanically. run()/computeFunction() keep the original semantics: a node runs
when forced or when an input has new data; any input returning 'Stop' stops
it; a None return means 'Go'.
"""
import inspect
import os
import sys
import threading
import time
import traceback
import warnings

from .ports import (InputPort, OutputPort, PortsDescr, RunNodeInputPort,
                    TriggerOutputPort, NO_DATA, _is_nodata)
from .widgets import jsonable


def uniq(objects):
    out = []
    for o in objects:
        if o not in out:
            out.append(o)
    return out


class Editor(object):
    """What nodes reach through getEditor(): there is no Tk editor, so the
    flags tell node code to take its no-GUI paths."""
    hasGUI = False
    verbose = False
    flashNodesWhenRun = False
    createBlockingConnections = True
    withThreads = False
    colorNodeByLibrary = False

    def __init__(self):
        from .datatypes import TYPES
        self.typeManager = TYPES
        self.currentNetwork = None
        self.networks = {}

    def dispatchEvent(self, event):
        pass

    def addNetwork(self, net):
        self.networks[net.name] = net

    def deleteNetwork(self, net):
        self.networks.pop(net.name, None)

    def getNodeLib(self, libName, package=None, version=None):
        from .library import get_library
        try:
            return get_library(libName, package), ''
        except Exception as e:
            return None, str(e)

    def update_idletasks(self):
        pass

    def update(self):
        pass


class NetworkNode(object):
    """A node of a network (NetworkEditor's NetworkNodeBase + NetworkNode)."""

    def __init__(self, name='NoName', sourceCode=None, originalClass=None,
                 constrkw=None, library=None, progbar=0, **kw):
        self.name = name
        self.id = None
        self.network = None
        self.originalClass = originalClass or self.__class__
        self.library = library
        self.options = kw
        self.constrkw = constrkw if constrkw is not None else {}
        self.readOnly = False
        self.newData = 0
        self.widthFirstTag = 0
        self.isRootNode = 1
        self.forceExecution = 0
        self.isSchedulingNode = False
        self.frozen = False
        self.hasProgBar = progbar
        self.posx = 0
        self.posy = 0
        self.inputPorts = []
        self.outputPorts = []
        self.inputPortByName = {}
        self.outputPortByName = {}
        self._inputPortsID = 0
        self._outputPortsID = 0
        self.specialInputPorts = []
        self.specialOutputPorts = []
        self.specialPortsVisible = False
        self.children = []
        self.parents = []
        self.inputPortsDescr = PortsDescr(self)
        self.outputPortsDescr = PortsDescr(self)
        self.widgetDescr = {}
        self.runLock = threading.RLock()
        self.selected = 0
        self.status = 'idle'
        self.lastError = None
        self.lastRunTime = None
        self.objEditor = None
        self.paramPanel = _ParamPanel(self)
        self.iconMaster = None
        self.dynamicComputeFunction = None
        self.sourceCode = None
        self.codeModified = False
        if not sourceCode:
            sourceCode = "def doit(self):\n    pass\n"
        self.setFunction(sourceCode, tagModified=False)

    # ---- helpers the original exposed ------------------------------------------
    def getEditor(self):
        net = self.network
        if net is None:
            return _DEFAULT_EDITOR
        return net.getEditor()

    @property
    def editor(self):
        return self.getEditor()

    @property
    def vEditor(self):
        ed = self.getEditor()
        return lambda: ed

    def isMacro(self):
        return False

    def beforeAddingToNetwork(self, network):
        pass

    def afterAddingToNetwork(self):
        pass

    def beforeRemovingFromNetwork(self):
        pass

    def onStoppingExecution(self):
        pass

    def getInputPortByName(self, name):
        return self.inputPortByName.get(name)

    def getOutputPortByName(self, name):
        return self.outputPortByName.get(name)

    def getOutputPortByType(self, type, name=None):
        for p in self.outputPorts:
            if p.datatypeObject['name'] == type and (name is None or p.name == name):
                return p

    def getSpecialInputPortByName(self, name):
        for p in self.specialInputPorts:
            if p.name == name:
                return p

    def getSpecialOutputPortByName(self, name):
        for p in self.specialOutputPorts:
            if p.name == name:
                return p

    def getInConnections(self):
        out = []
        for p in self.inputPorts + self.specialInputPorts:
            out.extend(p.connections)
        return out

    def getOutConnections(self):
        out = []
        for p in self.outputPorts + self.specialOutputPorts:
            out.extend(p.connections)
        return out

    def getConnections(self):
        return self.getInConnections() + self.getOutConnections()

    def getWidgetByName(self, name):
        p = self.inputPortByName.get(name)
        return p.widget if p is not None else None

    def ischild(self, node):
        """True if self is downstream of node through blocking connections."""
        seen = set()
        stack = [self]
        while stack:
            n = stack.pop()
            for c in n.getInConnections():
                if c.blocking is True:
                    n2 = c.port1.node
                    if n2 is node:
                        return True
                    if id(n2) not in seen:
                        seen.add(id(n2))
                        stack.append(n2)
        return False

    def ensureRootNode(self):
        net = self.network
        ins = self.getInConnections()
        if len(ins) == 0 or not any(c.blocking is True for c in ins):
            self.isRootNode = 1
            if self not in net.rootNodes:
                net.rootNodes.append(self)
        else:
            self.isRootNode = 0
            if self in net.rootNodes:
                net.rootNodes.remove(self)

    def refreshInputPortData(self):
        return {p.name: p.getData() for p in self.inputPorts}

    def rename(self, name, tagModified=True):
        self.name = name
        if self.network is not None:
            self.network.emit('node_renamed', node=self.id, name=name)

    def displayName(self, displayedName, tagModified=True):
        """Show a label instead of the name on the node (Vision's eval node
        shows its expression); the name itself does not change."""
        displayedName = (displayedName or '').replace("'", '').replace('"', '')
        if displayedName and displayedName != getattr(self, 'label', None):
            self.label = displayedName
            if self.network is not None:
                self.network.emit('node_label', node=self.id, label=displayedName)

    def move(self, dx, dy, absolute=True, tagModified=True):
        if absolute:
            self.posx, self.posy = dx, dy
        else:
            self.posx += dx
            self.posy += dy

    def configure(self, **kw):
        if 'function' in kw:
            self.setFunction(kw.pop('function'))
        if 'name' in kw:
            self.rename(kw.pop('name'))
        if 'frozen' in kw:
            self.frozen = bool(kw.pop('frozen'))
        for k, v in kw.items():
            setattr(self, k, v)

    def toggleFrozen_cb(self, event=None):
        self.frozen = not self.frozen

    def freeze(self):
        self.frozen = True

    def unfreeze(self):
        self.frozen = False

    def setProgressBar(self, percent):
        if self.network is not None:
            self.network.emit('progress', node=self.id, value=float(percent))

    # Tk-era no-ops node code calls
    def autoResize(self, *a, **k):
        pass

    autoResizeX = autoResizeY = autoResize

    def updateCode(self, port='ip', action=None, tagModified=True, **kw):
        pass

    def setColor(self, *a, **k):
        pass

    def toggleNodeExpand_cb(self, *a, **k):
        pass

    def isExpanded(self):
        return True

    def showInNodeWidgets(self, *a, **k):
        pass

    def hideInNodeWidgets(self, *a, **k):
        pass

    def setModifiedTag(self):
        pass

    def _setModified(self, v):
        pass

    # ---- ports -----------------------------------------------------------------
    def addInputPort(self, name=None, updateSignature=True,
                     _previousWidgetDescr=None, **kw):
        defaults = {'balloon': None, 'required': True, 'datatype': 'None',
                    'width': None, 'height': None, 'singleConnection': True,
                    'beforeConnect': None, 'afterConnect': None,
                    'beforeDisconnect': None, 'afterDisconnect': None,
                    'shape': None, 'color': None, 'cast': True,
                    'originalDatatype': None, 'defaultValue': None,
                    'inputPortClass': InputPort}
        defaults.update(kw)
        kw = defaults
        number = len(self.inputPorts)
        if name is None:
            name = 'in' + str(number)
        names = [p.name for p in self.inputPorts]
        if name in names:
            i = number
            while name + str(i) in names:
                i += 1
            name = name + str(i)
        klass = kw.pop('inputPortClass', InputPort) or InputPort
        kw.pop('updateSignature', None)
        ip = klass(name, self, **kw)
        self.inputPorts.append(ip)
        ip.number = len(self.inputPorts) - 1
        if not any(d['name'] == name for d in self.inputPortsDescr):
            self.inputPortsDescr.append({'name': name, 'datatype': kw['datatype'],
                                         'required': kw['required'],
                                         'balloon': kw['balloon'],
                                         'singleConnection': kw['singleConnection']})
        if _previousWidgetDescr is not None:
            ip._previousWidgetDescr = _previousWidgetDescr
        ip._id = self._inputPortsID
        self._inputPortsID += 1
        self.inputPortByName[name] = ip
        if self.network is not None and updateSignature:
            # a port added after the node was built (by the user, or a macro port)
            ip.createWidget()
            self._updateSignature()
            self.network.emit('ports', node=self.id, ports=self.describe_ports())
        return ip

    def addOutputPort(self, name=None, updateSignature=True, **kw):
        defaults = {'datatype': 'None', 'width': None, 'height': None,
                    'balloon': None, 'beforeConnect': None, 'afterConnect': None,
                    'beforeDisconnect': None, 'afterDisconnect': None,
                    'shape': None, 'color': None}
        defaults.update(kw)
        kw = defaults
        number = len(self.outputPorts)
        if name is None:
            name = 'out' + str(number)
        names = [p.name for p in self.outputPorts]
        if name in names:
            i = number
            while name + str(i) in names:
                i += 1
            name = name + str(i)
        klass = kw.pop('outputPortClass', OutputPort) or OutputPort
        kw.pop('updateSignature', None)
        kw.pop('inputPortClass', None)
        op = klass(name, self, **kw)
        self.outputPorts.append(op)
        op.number = len(self.outputPorts) - 1
        if not any(d['name'] == name for d in self.outputPortsDescr):
            self.outputPortsDescr.append({'name': name, 'datatype': kw['datatype'],
                                          'balloon': kw['balloon']})
        op._id = self._outputPortsID
        self._outputPortsID += 1
        self.outputPortByName[name] = op
        if self.network is not None and updateSignature:
            self.network.emit('ports', node=self.id, ports=self.describe_ports())
        return op

    def deletePort(self, p, resize=True, updateSignature=True):
        net = self.network
        if net is not None and p.connections:
            net.deleteConnections(list(p.connections))
        if p in self.inputPorts:
            self.inputPorts.remove(p)
            self.inputPortByName.pop(p.name, None)
            for i, q in enumerate(self.inputPorts):
                q.number = i
            for d in list(self.inputPortsDescr):
                if d['name'] == p.name:
                    self.inputPortsDescr.remove(d)
        elif p in self.outputPorts:
            self.outputPorts.remove(p)
            self.outputPortByName.pop(p.name, None)
            for i, q in enumerate(self.outputPorts):
                q.number = i
            for d in list(self.outputPortsDescr):
                if d['name'] == p.name:
                    self.outputPortsDescr.remove(d)
        if updateSignature and p not in self.outputPorts:
            self._updateSignature()
        if net is not None:
            net.emit('ports', node=self.id, ports=self.describe_ports())

    def _updateSignature(self):
        """Make the compute function's arguments the input ports, in order,
        as Vision's updateCode did when ports were added or removed. Functions
        taking *args (macro nodes) are left alone."""
        import re
        src = self.sourceCode or ''
        m = re.search(r'def\s+(\w+)\s*\(([^)]*)\)\s*:', src)
        if not m or '*' in m.group(2):
            return
        args = ', '.join(['self'] + [p.name for p in self.inputPorts])
        new = src[:m.start(2)] + args + src[m.end(2):]
        if new != src:
            try:
                self.setFunction(new, tagModified=self.codeModified)
            except SyntaxError:
                pass

    def deletePortByName(self, portName, resize=True, updateSignature=True):
        p = self.inputPortByName.get(portName) or self.outputPortByName.get(portName)
        if p is not None:
            self.deletePort(p, resize, updateSignature)

    def addSpecialPorts(self):
        self.specialInputPorts.append(RunNodeInputPort(self))
        self.specialOutputPorts.append(TriggerOutputPort(self))

    def createPorts(self):
        for kw in list(self.outputPortsDescr):
            kw = dict(kw)
            kw['updateSignature'] = False
            self.addOutputPort(**kw)
        for kw in list(self.inputPortsDescr):
            kw = dict(kw)
            kw['updateSignature'] = False
            ip = self.addInputPort(**kw)
            ip.createWidget()
        self.addSpecialPorts()

    # ---- code ------------------------------------------------------------------
    def evalString(self, code):
        """Compile source code for a node function or port callback. The code
        runs with the node class's module as its global scope, as in Vision."""
        if not code:
            return None
        if callable(code):
            return code
        mod = sys.modules.get(self.__class__.__module__)
        d = mod.__dict__ if mod is not None else {}
        obj = compile(code, '<%s %s>' % (self.__class__.__name__, self.name), 'exec')
        ns = {}
        exec(obj, d, ns)
        funcs = [v for v in ns.values() if inspect.isfunction(v)]
        if not funcs:
            return None
        # the last function defined, as the original took co_names[-1]
        for name in reversed(obj.co_names):
            if name in ns and inspect.isfunction(ns[name]):
                return ns[name]
        return funcs[-1]

    def setFunction(self, source, tagModified=True):
        """Set the compute function from its source code (raises SyntaxError
        when it does not compile, leaving the previous function in place)."""
        func = self.evalString(source)
        self.sourceCode = source
        self.dynamicComputeFunction = func
        if tagModified:
            self.codeModified = True
            if self.network is not None:
                self.network.emit('node_code', node=self.id, modified=True)

    def getSourceCode(self):
        return self.sourceCode

    # ---- execution -------------------------------------------------------------
    def outputData(self, **kw):
        for p in self.outputPorts:
            if p.name in kw:
                p.outputData(kw.pop(p.name))
        for k in kw:
            warnings.warn('WARNING: port %s not found in node %s' % (k, self.name))

    def scheduleChildren(self, portList=None):
        """Run the children of this node in the caller's thread; all children,
        or only those connected to the ports in portList."""
        net = self.network
        if portList is None:
            for n in self.children:
                n.forceExecution = 1
            allNodes = net.getAllNodes(uniq(self.children))
        else:
            children = []
            for p in portList:
                children.extend(x.node for x in p.children)
            for n in children:
                n.forceExecution = 1
            allNodes = net.getAllNodes(uniq(children))
        if len(allNodes):
            net.runNodes(allNodes, resetList=False)

    def schedule_cb(self, event=None):
        self.forceExecution = 1
        self.schedule()

    def schedule(self):
        """Run the subtree under this node (through the network's runner)."""
        self.network.run([self])

    def _set_status(self, status, **extra):
        self.status = status
        if self.network is not None:
            self.network.emit('node_status', node=self.id, status=status, **extra)

    def run(self, force=0, debug=False):
        """Run this node: returns 1 when it ran or had nothing to do, 'Stop'
        or 'stop' when it stopped, as in Vision."""
        from .macros import MacroInputNode, MacroOutputNode, MacroNode
        if force or self.forceExecution:
            self.forceExecution = 1
        elif self.frozen:
            return
        net = self.network
        with self.runLock:
            if (self.forceExecution == 0 and net.forceExecution == 0
                    and not isinstance(self, (MacroInputNode, MacroOutputNode))
                    and len(self.inputPorts) > 0):
                if not any(p.hasNewData() for p in self.inputPorts):
                    return 1
            self.forceExecution = 1
            if isinstance(self, MacroNode) and not self.hasRun:
                self.macroNetwork.forceExecution = 1
            if not isinstance(self, MacroInputNode):
                for op in self.outputPorts:
                    op.outputData(NO_DATA)
                if self.isSchedulingNode:
                    net.setChildrenOutputToNoDataYet(self)
            t0 = time.time()
            self._set_status('running')
            try:
                stat = self.computeFunction()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.forceExecution = 0
                tb = traceback.format_exc()
                self.lastError = tb
                print('*** ERROR while executing node: %s\n%s' % (self.name, tb), end='')
                self._set_status('error', error='%s: %s' % (type(e).__name__, e),
                                 trace=tb, time=time.time() - t0)
                return 'stop'
            self.lastRunTime = time.time() - t0
            if net.execStatus != 'stop':
                self.forceExecution = 0
            self._set_status('stopped' if stat in ('Stop', 'stop') else 'done',
                             time=self.lastRunTime)
        if stat == 'Go':
            if len(self.specialOutputPorts) and len(self.specialOutputPorts[0].children):
                self.scheduleChildren(portList=[self.specialOutputPorts[0]])
        if stat is None:
            return 1
        return stat

    def computeFunction(self):
        if not self.dynamicComputeFunction:
            return 'Stop'
        args = [self]
        newData = 0
        for port in self.inputPorts:
            if port.hasNewData():
                newData = 1
            data = port.getData()
            if isinstance(data, str) and data.lower() == 'stop':
                return 'Stop'
            args.append(data)
        stat = 'Stop'
        net = self.network
        if newData or self.forceExecution or (net and net.forceExecution):
            wd = net.workdir() if net is not None else None
            if wd:
                with _CWD_LOCK:
                    cwd = os.getcwd()
                    try:
                        os.chdir(wd)
                        stat = self.dynamicComputeFunction(*args)
                    finally:
                        os.chdir(cwd)
            else:
                stat = self.dynamicComputeFunction(*args)
            if stat is None:
                stat = 'Go'
            for p in self.inputPorts:
                p.releaseData()
        return stat

    # ---- description for the page ------------------------------------------------
    def describe_ports(self):
        return {'in': [p.describe() for p in self.inputPorts],
                'out': [p.describe() for p in self.outputPorts]}

    def describe(self):
        lib = self.library
        d = {'id': self.id, 'name': self.name, 'cls': self.__class__.__name__,
             'lib': lib.name if lib is not None else None,
             'color': lib.color if lib is not None else None,
             'pos': [self.posx, self.posy], 'frozen': self.frozen,
             'macro': self.isMacro(), 'status': self.status,
             'codeModified': self.codeModified, 'progbar': bool(self.hasProgBar),
             'doc': inspect.getdoc(self.__class__) or '',
             'readOnly': bool(self.readOnly), 'label': getattr(self, 'label', None)}
        d.update(self.describe_ports())
        return d


class _ParamPanel(object):
    """Stand-in for the Tk parameter panel some node code touches."""

    def __init__(self, node):
        self.node = node
        self.visible = False
        self.widgetFrame = None

    def run(self, *a, **k):
        self.node.schedule()

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def toggleShow(self, *a):
        self.visible = not self.visible


# a process-wide lock: chdir is global to the process
_CWD_LOCK = threading.RLock()
_DEFAULT_EDITOR = Editor()


class NetworkConnection(object):
    """A connection from an output port (port1) to an input port (port2).

    blocking=True: the child waits for the parent and is not a root node;
    blocking=False: data flows but adds no scheduling dependency."""

    def __init__(self, port1, port2, mode='straight', name=None, blocking=None,
                 smooth=False, splitratio=None, hidden=False, **kw):
        if name is None:
            name = '%s(%s)_%s(%s)' % (port1.node.name, port1.name,
                                      port2.node.name, port2.name)
        self.name = name
        self.hidden = hidden
        self.port1 = port1
        self.port2 = port2
        port1.children.append(port2)
        port1.connections.append(self)
        port1.node.children.append(port2.node)
        port2.parents.append(port1)
        port2.connections.append(self)
        port2.node.parents.append(port1.node)
        self.blocking = True if blocking is None else blocking
        self.mode = mode
        self.network = None
        self.id = None
        self.selected = 0

    def describe(self):
        p1, p2 = self.port1, self.port2
        special1 = p1 in p1.node.specialOutputPorts
        special2 = p2 in p2.node.specialInputPorts
        return {'id': self.id, 'from': [p1.node.id, p1.name], 'to': [p2.node.id, p2.name],
                'blocking': bool(self.blocking), 'special': special1 or special2,
                'datatype': p1.datatypeObject['name']}

    # Tk-era no-ops
    def updatePosition(self):
        pass

    def configure(self, **kw):
        if 'blocking' in kw:
            self.blocking = kw['blocking']


class FunctionNode(NetworkNode):
    """A node exposing a Python callable: positional arguments become input
    ports, named arguments get widgets chosen from their default value."""

    def __init__(self, functionOrString=None, importString=None,
                 posArgsNames=None, namedArgs=None, **kw):
        kw.setdefault('name', getattr(functionOrString, '__name__', 'function'))
        NetworkNode.__init__(self, **kw)
        self.importString = importString
        func = functionOrString
        if isinstance(func, str):
            ns = {}
            if importString:
                exec(importString, ns)
            func = eval(func, ns)
        self.function = func
        posArgsNames = list(posArgsNames or [])
        namedArgs = dict(namedArgs or {})
        if func is not None and not posArgsNames and not namedArgs:
            try:
                sig = inspect.signature(func)
                for p in sig.parameters.values():
                    if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                        continue
                    if p.default is p.empty:
                        posArgsNames.append(p.name)
                    else:
                        namedArgs[p.name] = p.default
            except (TypeError, ValueError):
                pass
        for n in posArgsNames:
            self.inputPortsDescr.append(datatype='None', name=n)
        for n, v in namedArgs.items():
            self.inputPortsDescr.append(datatype='None', name=n, required=False,
                                        defaultValue=v)
            if isinstance(v, bool):
                self.widgetDescr[n] = {'class': 'NECheckButton', 'master': 'ParamPanel',
                                       'initialValue': int(v), 'labelCfg': {'text': n}}
            elif isinstance(v, (int, float)):
                self.widgetDescr[n] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                       'type': 'int' if isinstance(v, int) else 'float',
                                       'initialValue': v, 'labelCfg': {'text': n}}
            elif isinstance(v, str):
                self.widgetDescr[n] = {'class': 'NEEntry', 'master': 'ParamPanel',
                                       'initialValue': v, 'labelCfg': {'text': n}}
        self.outputPortsDescr.append(datatype='None', name='result')
        self._posArgs = posArgsNames
        self._named = list(namedArgs)
        args = ', '.join(posArgsNames + list(namedArgs))
        code = ('def doit(self%s):\n' % (', ' + args if args else '') +
                '    kw = dict(zip(self._named, [%s]))\n' % ', '.join(self._named) +
                '    result = self.function(%s**kw)\n'
                % (''.join(a + ', ' for a in posArgsNames)) +
                '    self.outputData(result=result)\n')
        self.setFunction(code, tagModified=False)
