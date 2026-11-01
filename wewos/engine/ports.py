# Ported to Python 3 from MGLTools NetworkEditor/ports.py
# Original: Michel Sanner, Daniel Stoffler (TSRI). Port: Michel Sanner, PhD (c) 2026.
"""Input and output ports: data validation, casting and new-data flags.

The data logic (getParentPortData, getData, outputData, hasNewData,
releaseData) is the original's; icons, balloons and Tk editors are gone.
"""
import warnings

from .datatypes import TYPES, AnyArrayType, AnyType
from .widgets import WidgetProxy, jsonable

NO_DATA = 'no data yet'


def _is_nodata(d):
    return isinstance(d, str) and d == NO_DATA


class PortsDescr(list):
    """List of dicts describing a node's ports (node.inputPortsDescr ...)."""

    def __init__(self, node):
        list.__init__(self)
        self._node = node

    def append(self, *args, **kw):
        if len(args) == 1:
            if isinstance(args[0], dict):
                kw = dict(args[0])
            else:
                raise ValueError('expected dictionary got %r' % (args,))
        elif len(args) > 1:
            raise ValueError('bad argument for PortsDescr %r' % (args,))
        assert 'name' in kw
        kw.setdefault('datatype', 'None')
        for p in self:
            if p['name'] == kw['name']:
                warnings.warn('port name %s already used in node %s'
                              % (kw['name'], self._node.name))
                return
        list.append(self, kw)


InputPortsDescr = OutputPortsDescr = PortsDescr


class Port(object):
    """Base class for input and output ports."""

    def __init__(self, name, node, datatype='None', balloon=None, width=None,
                 height=None, beforeConnect=None, afterConnect=None,
                 beforeDisconnect=None, afterDisconnect=None,
                 hasHiddenConnections=False, shape=None, color=None,
                 originalDatatype=None, vector=None):
        self.name = name
        self.node = node
        self.connections = []
        self.datatypeObject = None
        self.originalDatatype = originalDatatype if originalDatatype is not None else datatype
        self.balloon = balloon
        self.widget = None
        self._id = None
        self.data = NO_DATA
        self.visible = True
        self.callbacks = {'beforeConnect': (None, None), 'afterConnect': (None, None),
                          'beforeDisconnect': (None, None), 'afterDisconnect': (None, None)}
        self.setCallback(beforeConnect, 'beforeConnect')
        self.setCallback(afterConnect, 'afterConnect')
        self.setCallback(beforeDisconnect, 'beforeDisconnect')
        self.setCallback(afterDisconnect, 'afterDisconnect')
        self.setDataType(datatype, tagModified=False)
        # kept for code that reads them
        self.dataView = None
        self.objectBrowser = None

    @property
    def network(self):
        return self.node.network

    @property
    def editor(self):
        return self.node.getEditor()

    def getEditor(self):
        return self.node.getEditor()

    def setCallback(self, code, key):
        self.callbacks[key] = (self.node.evalString(code) if code else None, code)

    def getDatatypeObjectFromDatatype(self, datatype):
        if datatype is None:
            datatype = 'None'
        if isinstance(datatype, str):
            return TYPES.getType(datatype)
        if isinstance(datatype, (AnyType, AnyArrayType)):
            return datatype
        if isinstance(datatype, type):
            return TYPES.getTypeFromClass(datatype)
        return TYPES.getTypeFromClass(None)

    def setDataType(self, datatype, tagModified=True, makeOriginal=False):
        self.datatypeObject = self.getDatatypeObjectFromDatatype(datatype)
        if makeOriginal:
            self.originalDatatype = datatype
        net = self.node.network
        if net is not None and (self in self.node.inputPorts
                                or self in self.node.outputPorts):
            net.emit('port_type', node=self.node.id, port=self.name,
                     io='in' if isinstance(self, InputPort) else 'out',
                     datatype=self.datatypeObject['name'])

    def configure(self, **kw):
        for k, v in kw.items():
            if k == 'datatype':
                self.setDataType(v)
            elif k == 'name':
                old = self.name
                self.name = v
                byname = (self.node.inputPortByName if isinstance(self, InputPort)
                          else self.node.outputPortByName)
                if old in byname:
                    byname[v] = byname.pop(old)
            elif k in self.callbacks:
                self.setCallback(v, k)
            else:
                setattr(self, k, v)

    def getDataStr(self, maxLen=None):
        s = repr(self.data)
        if maxLen and len(s) > maxLen:
            s = s[:maxLen] + '...'
        return s

    def __repr__(self):
        return '<%s %s.%s>' % (self.__class__.__name__,
                               getattr(self.node, 'name', '?'), self.name)

    # Tk-era methods node code may call
    def clearDataView(self):
        pass

    def updateDataView(self):
        pass

    def deleteIcon(self):
        pass

    def createIcon(self, *a, **k):
        pass


class InputPort(Port):

    def __init__(self, name, node, datatype=None, required=True, balloon=None,
                 width=None, height=None, singleConnection=True,
                 beforeConnect=None, afterConnect=None, beforeDisconnect=None,
                 afterDisconnect=None, shape=None, color=None, cast=True,
                 originalDatatype=None, _previousWidgetDescr=None,
                 defaultValue=None, vector=(0, 1)):
        self.number = None
        self.parents = []
        self.widget = None
        self._missingDims = None
        self._cast = bool(cast)
        self._previousWidgetDescr = None
        self.widgetInMacro = {}
        Port.__init__(self, name, node, datatype=datatype, balloon=balloon,
                      width=width, height=height, beforeConnect=beforeConnect,
                      afterConnect=afterConnect, beforeDisconnect=beforeDisconnect,
                      afterDisconnect=afterDisconnect, shape=shape, color=color,
                      originalDatatype=originalDatatype, vector=vector)
        self.number = len(node.inputPorts)
        self.defaultValue = defaultValue
        self.required = required
        self.singleConnection = singleConnection
        self._newdata = False
        self._validationStatus = 'unchecked'

    # ---- new data flags ------------------------------------------------------
    def hasNewData(self):
        if self.widget:
            return self.widget._newdata
        return self._newdata

    def hasNewValidData(self):
        if self.widget:
            return self.widget._newdata
        if _is_nodata(self.data):
            return False
        return self._newdata

    def releaseData(self):
        if self.widget:
            self.widget._newdata = False
            self.widget.lastUsedValue = self.widget.get()
        else:
            self._newdata = False

    # ---- widgets ---------------------------------------------------------------
    def createWidget(self, rescale=1, descr=None):
        if descr:
            self.node.widgetDescr[self.name] = descr
        else:
            descr = self.node.widgetDescr.get(self.name, None)
        if descr is None:
            return
        descr = dict(descr)
        descr.pop('_modified', None)
        self.widget = WidgetProxy(self, descr)
        net = self.node.network
        if net is not None and self.connections:
            net.deleteConnections(list(self.connections))
        return self.widget

    def unbindWidget(self, force=False):
        if self.widget is None:
            return
        if self.widget.lockedOnPort and not force:
            raise ValueError('the widget on port %s cannot be unbound' % self.name)
        d = self.widget.getDescr()
        d['initialValue'] = self.widget.get()
        self._previousWidgetDescr = d
        self.widget = None
        self.node.widgetDescr.pop(self.name, None)
        net = self.node.network
        if net is not None:
            net.emit('widget', node=self.node.id, port=self.name, widget=None)

    def rebindWidget(self, run=True):
        if self._previousWidgetDescr and not self.parents:
            self.createWidget(descr=self._previousWidgetDescr)
            self._previousWidgetDescr = None
            net = self.node.network
            if net is not None:
                net.emit('widget', node=self.node.id, port=self.name,
                         widget=self.widget.spec())
                if run and net.runOnNewData.value is True:
                    self.node.schedule()

    def deleteWidget(self):
        d = None
        if self.widget is not None:
            d = self.widget.getDescr()
        self.widget = None
        self.node.widgetDescr.pop(self.name, None)
        return d

    # ---- data ------------------------------------------------------------------
    def badDataOnInputPort(self, parent):
        self._validationStatus = 'invalid'
        warnings.warn('Running node: %s\nBad Data on port: %s\ncoming from port: %s %s'
                      % (self.node.name, self.name, parent.node.name, parent.name))
        return False, None

    def getParentPortData(self, parent):
        """Validate (or cast) the data of one parent port; returns (ok, data)."""
        data = parent.data
        for conn in self.connections:
            if conn.port1 is parent:
                theConnection = conn
                break
        else:
            raise AssertionError('connection not found')
        if theConnection.blocking is True and _is_nodata(data):
            return False, data
        elif self.datatypeObject is None:
            self._validationStatus = 'valid'
            return True, data
        elif self._validationStatus == 'valid':
            return True, parent.data
        elif self._validationStatus == 'invalid':
            return False, parent.data
        elif self._validationStatus == 'missingDims':
            data = parent.data
            for i in range(self._missingDims):
                data = [data]
            return True, data
        # 'unchecked'
        if data is None:
            return True, data
        typeObj = self.datatypeObject
        if isinstance(typeObj, AnyType):
            if typeObj.validate(data):
                self._validationStatus = 'valid'
                return True, data
            if not self._cast:
                return self.badDataOnInputPort(parent)
            try:
                if len(data) == 1:
                    d0 = data[0]
                    if typeObj.validate(d0):
                        return True, d0
            except Exception:
                pass
            ok, castdata = typeObj.cast(data)
            if ok:
                return True, castdata
            return self.badDataOnInputPort(parent)

        # AnyArrayType
        ok, lArray = typeObj.validate(data)
        if typeObj['datashape'] is None:
            if ok is True:
                self._validationStatus = 'valid'
                return True, data
            if not self._cast:
                return self.badDataOnInputPort(parent)
            ok, castdata = typeObj.cast(data)
            if ok is True:
                self._validationStatus = 'unchecked'
                return True, castdata
            try:
                if len(data) == 1:
                    d0 = data[0]
                    ok, v = typeObj.validate(d0)
                    if ok:
                        return True, d0
                    ok, castdata = typeObj.cast(d0)
                    if ok is True:
                        self._validationStatus = 'unchecked'
                        return True, castdata
                return self.badDataOnInputPort(parent)
            except Exception:
                return self.badDataOnInputPort(parent)

        if ok is False:
            if not self._cast:
                return self.badDataOnInputPort(parent)
            ok, lArray = typeObj.cast(data)
            if ok is False:
                return self.badDataOnInputPort(parent)
            self._validationStatus = 'casted'

        status, lArray = typeObj.validateDims(lArray)
        if status is True:
            if self._validationStatus == 'casted':
                self._validationStatus = 'unchecked'
                return True, lArray
            self._validationStatus = 'valid'
            return True, data
        elif status is False:
            return self.badDataOnInputPort(parent)
        else:
            if self._validationStatus == 'casted':
                self._validationStatus = 'unchecked'
            else:
                self._validationStatus = 'missingDims'
            self._missingDims = status
            for i in range(status):
                data = [data]
            return True, data

    def getData(self):
        """The data for the compute function, or 'Stop' when bad or missing.

        1 - valid parent data is returned
        2 - invalid data returns 'Stop'
        3 - no data from the parent: 'Stop' if required, else 'no data yet'
        """
        if len(self.parents):
            if self.singleConnection is True:
                ok, allData = self.getParentPortData(self.parents[0])
                if ok is False:
                    if _is_nodata(allData):
                        if self.required is True:
                            self.data = NO_DATA
                            return 'Stop'
                    else:
                        self.data = NO_DATA
                        return 'Stop'
            else:
                allData = []
                for parentPort in self.parents:
                    ok, data = self.getParentPortData(parentPort)
                    if ok is True:
                        allData.append(data)
                if len(allData) == 0:
                    if self.required is True:
                        self.data = NO_DATA
                        return 'Stop'
                    allData = NO_DATA
                elif len(self.parents) == 1 and self.singleConnection == 'auto':
                    allData = allData[0]
        else:
            if self.widget:
                allData = self.widget.get()
            elif self.required is False:
                allData = self.defaultValue
            else:
                self.data = NO_DATA
                return 'Stop'

        if _is_nodata(allData):
            if self.required:
                self.data = NO_DATA
                return 'Stop'
        self.data = allData
        return allData

    def describe(self):
        return {'name': self.name, 'number': self.number,
                'datatype': self.datatypeObject['name'],
                'required': bool(self.required),
                'single': jsonable(self.singleConnection),
                'balloon': self.balloon,
                'widget': self.widget.spec() if self.widget else None,
                'unbound': self._previousWidgetDescr is not None}


class OutputPort(Port):

    def __init__(self, name, node, datatype='None', balloon=None, width=None,
                 height=None, beforeConnect=None, afterConnect=None,
                 beforeDisconnect=None, afterDisconnect=None, shape=None,
                 color=None, vector=(0, -1)):
        self.number = None
        self.children = []
        Port.__init__(self, name, node, datatype, balloon, width, height,
                      beforeConnect, afterConnect, beforeDisconnect, afterDisconnect,
                      shape=shape, color=color, vector=vector)
        self.number = len(node.outputPorts)

    def setDataType(self, datatype, tagModified=True, makeOriginal=False):
        Port.setDataType(self, datatype, tagModified=tagModified, makeOriginal=makeOriginal)
        for c in self.connections:
            p = c.port2
            typename = p.datatypeObject['name']
            if typename == 'None' or typename != p.originalDatatype:
                p.setDataType(datatype, tagModified=tagModified)

    def outputData(self, data):
        self.data = data
        for c in self.connections:
            p = c.port2
            p._newdata = True
            p._validationStatus = 'unchecked'
            p._missingDims = None
            p.node.newData = 1

    def resetData(self):
        self.data = None
        for c in self.connections:
            c.port2._newdata = False

    def describe(self):
        return {'name': self.name, 'number': self.number,
                'datatype': self.datatypeObject['name'], 'balloon': self.balloon}


class SpecialInputPort(Port):
    def __init__(self, name, node, datatype='triggerIn', balloon=None,
                 width=8, height=8, vector=(-1, 0)):
        self.number = len(node.specialInputPorts)
        self.parents = []
        self.widget = None
        Port.__init__(self, name, node, datatype, balloon, width, height, vector=vector)
        self.required = False
        self._newdata = False
        self._validationStatus = 'unchecked'

    def hasNewData(self):
        return False

    def releaseData(self):
        pass


class RunNodeInputPort(SpecialInputPort):
    def __init__(self, node, datatype='triggerIn', vector=(-1, 0)):
        SpecialInputPort.__init__(self, 'runNode', node, datatype,
                                  balloon='trigger this node', vector=vector)


class RunChildrenInputPort(SpecialInputPort):
    def __init__(self, node, datatype=None, vector=(-1, 0)):
        SpecialInputPort.__init__(self, 'runChildren', node, datatype,
                                  balloon="trigger this node's children", vector=vector)


class SpecialOutputPort(Port):
    def __init__(self, name, node, datatype='None', balloon=None, width=8,
                 height=8, vector=(1, 0)):
        self.children = []
        Port.__init__(self, name, node, datatype, balloon, width, height, vector=vector)
        self.number = len(node.specialOutputPorts)

    def outputData(self, data):
        self.data = data


class TriggerOutputPort(SpecialOutputPort):
    def __init__(self, node, vector=(1, 0)):
        SpecialOutputPort.__init__(self, 'trigger', node, 'triggerOut',
                                   balloon='trigger nodes connected to this port',
                                   vector=vector)
