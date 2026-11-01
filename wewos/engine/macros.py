# Ported to Python 3 from MGLTools NetworkEditor/macros.py
# Original: Michel Sanner, Daniel Stoffler (TSRI). Port: Michel Sanner, PhD (c) 2026.
"""Macro nodes: a node holding a sub-network.

The macro network has an input node (whose outputs mirror the macro's
inputs) and an output node (whose inputs feed the macro's outputs).
Connecting to port 0 ('new') of either creates the matching macro port
(Network.connectNodes). The compute functions are the original's, in Python 3.
"""
from itertools import zip_longest

from .network import Network
from .node import NetworkNode


class MacroNetwork(Network):

    def __init__(self, macroNode, name='Noname'):
        Network.__init__(self, name)
        self.macroNode = macroNode
        self._originalNodes = []
        self._originalConnections = []

    @property
    def root(self):
        net = self.macroNode.network
        return net.root if net is not None else self

    @property
    def netid(self):
        return self.macroNode.id or 'macro?'

    def getEditor(self):
        net = self.macroNode.network
        return net.getEditor() if net is not None else self._editor

    def workdir(self):
        r = self.root
        return Network.workdir(r) if r is not self else self._workdir

    def run(self, roots=None):
        Network.run(self, roots)

    def describe(self):
        d = Network.describe(self)
        d['macroNode'] = self.macroNode.id
        d['parent'] = self.macroNode.network.netid if self.macroNode.network else None
        return d


class MacroBase(object):
    def getPortName(self, port):
        return '%s_%d_%s_%d' % (self.name.replace(' ', '_'), id(self), port.name, port._id)

    def updateCode(self, port='ip', action=None, tagModified=True, **kw):
        pass


_MACRO_CODE = """def doit(self, *args):
    if self.network.forceExecution:
        self.macroNetwork.forceExecution = self.network.forceExecution
    macroIp = self.macroNetwork.ipNode
    kw = {}
    for p, data in zip(self.inputPorts, args):
        if self.macroNetwork.forceExecution or p.hasNewValidData():
            macroIp.newData = 1
            kw[macroIp.outputPorts[p.number + 1].name] = data
    if not macroIp.newData and not self.macroNetwork.forceExecution:
        return
    macroIp.outputData(**kw)
    if not self.hasRun or self.macroNetwork.forceExecution:
        roots = self.macroNetwork.rootNodes[:]
        self.hasRun = 1
    else:
        roots = []
        for n in self.macroNetwork.rootNodes:
            if self.macroNetwork.forceExecution:
                n.forceExecution = 1
                roots.append(n)
            elif n.newData:
                roots.append(n)
    if len(roots):
        subRunNodes = self.macroNetwork.getSubRunNodes(roots=roots)
        macroIp.outputData(**kw)
        self.macroNetwork.runNodes(subRunNodes)
    macroIp.newData = 0
    self.macroNetwork.forceExecution = 0
"""


class MacroNode(MacroBase, NetworkNode):
    """A node whose computation is a sub-network (self.macroNetwork)."""

    def __init__(self, name='NoName', sourceCode=None, originalClass=None,
                 constrkw=None, library=None, progbar=0,
                 macroNetworkClass=MacroNetwork, **kw):
        NetworkNode.__init__(self, name, sourceCode, originalClass, constrkw,
                             library, progbar, **kw)
        self.expanded = 0
        self.isSchedulingNode = True
        self.hasRun = 0
        self.macroNetwork = macroNetworkClass(self, self.name)
        self.macroNetwork.ipNode = MacroInputNode(self, 'input Ports')
        self.macroNetwork.opNode = MacroOutputNode(self, 'output Ports')
        self.setFunction(_MACRO_CODE, tagModified=False)
        self.codeModified = False

    def isMacro(self):
        return True

    def schedule_cb(self, event=None):
        self.macroNetwork.forceExecution = 1
        NetworkNode.schedule_cb(self)

    def beforeAddingToNetwork(self, network):
        self.macroNetwork.runOnNewData = network.runOnNewData

    def afterAddingToNetwork(self):
        net = self.macroNetwork
        saved = net.runOnNewData.value
        net.runOnNewData.value = False
        try:
            if net.ipNode.network is None:
                net.addNode(net.ipNode, 200, 20)
            if net.opNode.network is None:
                net.addNode(net.opNode, 200, 280)
        finally:
            net.runOnNewData.value = saved

    def afterBuildingMacroNetwork(self):
        pass

    def beforeRemovingFromNetwork(self):
        pass

    def rename(self, name, tagModified=True):
        NetworkNode.rename(self, name, tagModified)
        self.macroNetwork.name = name

    def getRootMacro(self):
        result = [self]
        parent = self
        while isinstance(parent.network, MacroNetwork):
            parent = parent.network.macroNode
            result.append(parent)
        return result[::-1]

    def expand(self, event=None):
        self.expanded = 1

    def shrink(self, event=None):
        self.expanded = 0

    def describe(self):
        d = NetworkNode.describe(self)
        d['macroNet'] = self.id
        return d


class MacroInputNode(MacroBase, NetworkNode):
    """Inside a macro: outputs the data arriving on the macro's inputs."""

    def __init__(self, macroNode=None, name='NoName', sourceCode=None,
                 originalClass=None, constrkw=None, library=None, progbar=0, **kw):
        self.macroNode = macroNode
        NetworkNode.__init__(self, name, None, None, **kw)
        self.isSchedulingNode = True
        self.outputPortsDescr.append({'name': 'new', 'balloon': 'Add new input port'})
        self.readOnly = 1
        code = """def doit(self, *args):
    portsWithNewData = []
    for ip, op in zip(self.macroNode.inputPorts, self.outputPorts[1:]):
        if self.network.forceExecution or ip.hasNewValidData():
            portsWithNewData.append(op)
    self.scheduleChildren(portsWithNewData)
"""
        self.setFunction(code, tagModified=False)


class MacroOutputNode(MacroBase, NetworkNode):
    """Inside a macro: sends its inputs to the macro's outputs, then
    schedules the macro's children."""

    def __init__(self, macroNode=None, name='NoName', sourceCode=None,
                 originalClass=None, constrkw=None, library=None, progbar=0, **kw):
        self.macroNode = macroNode
        NetworkNode.__init__(self, name, None, None, **kw)
        self.inputPortsDescr.append({'name': 'new', 'required': False,
                                     'balloon': 'Add new output port'})
        self.readOnly = 1
        code = """def doit(self, *args):
    forceExecution = self.network.forceExecution
    for op, ip in zip(self.macroNode.outputPorts, self.inputPorts[1:]):
        if len(ip.connections) == 1:
            op.outputData(ip.getData())
        else:
            op.outputData(self.flatten(ip.getData()))
        self.network.forceExecution = 0
        self.macroNode.network.forceExecution = forceExecution
    portsWithNewData = []
    for op, ip in zip(self.macroNode.outputPorts, self.inputPorts[1:]):
        if ip.hasNewValidData():
            portsWithNewData.append(op)
    self.macroNode.scheduleChildren(portsWithNewData)
"""
        self.setFunction(code, tagModified=False)

    def flatten(self, data):
        if isinstance(data, list):
            flat = []
            for d in data:
                if isinstance(d, list):
                    flat.extend(d)
                else:
                    return data
            return flat
        return data
