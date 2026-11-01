# Author: Michel Sanner, PhD. Copyright (c) 2026.
# Replaces the Tk widgets of MGLTools NetworkEditor/widgets.py.
"""Port widgets as data.

In Vision a port could be bound to a Tk widget (thumbwheel, entry, combobox...).
Here the server keeps a WidgetProxy holding the widget's class name, its
options and its value; the browser draws it from `spec()`. The proxy keeps the
methods node code calls on widgets (set, get, configure, getDescr), so
`self.inputPorts[0].widget.configure(min=0)` in a doit still works and the
change reaches the page as a 'widget' event.
"""
import copy

# kind: how the page draws it. vtype: how values are coerced on set().
# defaults: options the page needs when a node's widgetDescr omits them.
WIDGETS = {
    'NEThumbWheel': {'kind': 'number', 'vtype': 'number',
                     'defaults': {'type': 'float', 'min': None, 'max': None,
                                  'increment': 0.0, 'oneTurn': 360.0, 'precision': 2,
                                  'initialValue': 0.0}},
    'NEDial': {'kind': 'number', 'vtype': 'number',
               'defaults': {'type': 'float', 'min': None, 'max': None,
                            'increment': 0.0, 'oneTurn': 360.0, 'precision': 2,
                            'initialValue': 0.0}},
    'NEEntry': {'kind': 'entry', 'vtype': 'str', 'defaults': {'initialValue': ''}},
    'NEEntryNotScheduling': {'kind': 'entry', 'vtype': 'str',
                             'defaults': {'initialValue': ''}},
    'NEEntryField': {'kind': 'entry', 'vtype': 'dtype', 'defaults': {'initialValue': ''}},
    'NEEntryWithFileBrowser': {'kind': 'file', 'vtype': 'str',
                               'defaults': {'initialValue': '', 'filetypes': [],
                                            'title': 'Select file'}},
    'NEEntryWithFileSaver': {'kind': 'filesave', 'vtype': 'str',
                             'defaults': {'initialValue': '', 'filetypes': [],
                                          'title': 'Save as'}},
    'NEEntryWithDirectoryBrowser': {'kind': 'dir', 'vtype': 'str',
                                    'defaults': {'initialValue': '',
                                                 'title': 'Select directory'}},
    'NECheckButton': {'kind': 'checkbox', 'vtype': 'int01', 'defaults': {'initialValue': 0}},
    'NEButton': {'kind': 'button', 'vtype': 'any', 'defaults': {'initialValue': None}},
    'NEComboBox': {'kind': 'combo', 'vtype': 'any',
                   'defaults': {'choices': [], 'fixedChoices': 0, 'autoList': False,
                                'initialValue': None}},
    'NEScrolledText': {'kind': 'text', 'vtype': 'str', 'defaults': {'initialValue': ''}},
    'NEVectorGUI': {'kind': 'vector', 'vtype': 'vector',
                    'defaults': {'initialValue': [1.0, 0.0, 0.0]}},
    'NEVectEntry': {'kind': 'vector', 'vtype': 'vector',
                    'defaults': {'initialValue': [0.0, 0.0, 0.0]}},
    'NEXYZGUI': {'kind': 'vector', 'vtype': 'vector',
                 'defaults': {'initialValue': [0.0, 0.0, 0.0]}},
    # symserv's translation along 3 axes: 3 lengths, then the 3 axes
    'NEXYZVectGUI': {'kind': 'xyzvect', 'vtype': 'xyzvect',
                     'defaults': {'initialValue': None, 'vectX': '1 0 0',
                                  'vectY': '0 1 0', 'vectZ': '0 0 1'}},
    'NEMultiCheckButtons': {'kind': 'multicheck', 'vtype': 'any',
                            'defaults': {'initialValue': None, 'choices': []}},
    # Volume's contour spectrum: a number with the isocontour signatures
    # (area, volume, gradient... as functions of the isovalue) drawn above it
    'NEContourSpectrum': {'kind': 'number', 'vtype': 'number',
                          'defaults': {'type': 'float', 'min': None, 'max': None,
                                       'precision': 3, 'initialValue': 0.0}},
    'NEColorEditor': {'kind': 'color', 'vtype': 'color',
                      'defaults': {'initialValue': [1.0, 1.0, 1.0]}},
    'NEColorWheel': {'kind': 'color', 'vtype': 'color',
                     'defaults': {'initialValue': [1.0, 1.0, 1.0]}},
}

# options that only placed Tk widgets; dropped from the spec sent to the page
# ('size' is a widget's size in pixels, e.g. NEVectorGUI's 'size': 100)
_TK_ONLY = {'width', 'height', 'size', 'wheelPad', 'canvasCfg', 'wheelLabCfg', 'widgetGridCfg',
            'labelGridCfg', 'NEwidgetPosition', 'widgetPlacerCfg', 'orient',
            'callback', 'command', 'lockedOnPort'}


def register_widget(name, kind, vtype='any', defaults=None):
    """Libraries add widget classes here (NodeLibrary.addWidget)."""
    WIDGETS[name] = {'kind': kind, 'vtype': vtype, 'defaults': dict(defaults or {})}


def jsonable(v):
    """A value the page can show and send back: Python types become names,
    numpy arrays lists, anything else its repr."""
    import numpy
    if v is None or isinstance(v, (bool, int, float, str)):
        if isinstance(v, float) and v != v:
            return None
        return v
    if isinstance(v, type):
        return v.__name__
    if isinstance(v, numpy.generic):
        return v.item()
    if isinstance(v, numpy.ndarray):
        return v.tolist() if v.size <= 10000 else repr(v)
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    return repr(v)


class WidgetProxy(object):
    """Server side stand-in for a NetworkEditor PortWidget."""

    def __init__(self, port, descr):
        descr = dict(descr)
        self.port = port
        self.name = port.name
        self.className = descr.pop('class', 'NEEntry')
        if not isinstance(self.className, str):
            self.className = getattr(self.className, '__name__', 'NEEntry')
        info = WIDGETS.get(self.className)
        self.known = info is not None
        if info is None:
            info = {'kind': 'json', 'vtype': 'any', 'defaults': {}}
        self.kind = info['kind']
        self.vtype = info['vtype']
        self.master = descr.pop('master', 'ParamPanel')
        self.lockedOnPort = bool(descr.get('lockedOnPort', False))
        labelCfg = descr.pop('labelCfg', None) or {}
        self.label = labelCfg.get('text', '') if isinstance(labelCfg, dict) else ''
        self.labelCfg = labelCfg
        self.options = copy.deepcopy(info['defaults'])
        self.options.update(descr)
        self.initialValue = self.options.pop('initialValue', None)
        self._value = None
        self._newdata = False
        self.lastUsedValue = None
        self.widget = self          # old code reached the Tk widget as .widget
        self._quiet = True
        self.set(self.initialValue, run=False)   # leaves _newdata True, as Vision did
        self._quiet = False

    # ---- the PortWidget API used by node code -----------------------------
    @property
    def inNode(self):
        return self.master == 'node'

    def _coerce(self, value):
        vt = self.vtype
        o = self.options
        if value is None and vt != 'xyzvect':
            if vt == 'number':
                return 0 if o.get('type') == 'int' else 0.0
            if vt == 'int01':
                return 0
            if vt == 'str':
                return ''
            return value
        if vt == 'number':
            t = o.get('type', 'float')
            if isinstance(t, type):
                t = t.__name__
            try:
                v = int(round(float(value))) if t == 'int' else float(value)
            except (TypeError, ValueError):
                v = 0 if t == 'int' else 0.0
            mn, mx = o.get('min'), o.get('max')
            if mn is not None and v < mn:
                v = type(v)(mn)
            if mx is not None and v > mx:
                v = type(v)(mx)
            return v
        if vt == 'int01':
            if isinstance(value, str):
                return 0 if value.strip().lower() in ('', '0', 'false', 'no', 'off') else 1
            return 1 if value else 0
        if vt == 'str':
            return value if isinstance(value, str) else str(value)
        if vt == 'dtype':
            dt = o.get('dtype', str)
            if isinstance(dt, str):
                dt = {'int': int, 'float': float, 'str': str, 'string': str}.get(dt, str)
            try:
                return dt(value)
            except (TypeError, ValueError):
                return value
        if vt == 'vector':
            if isinstance(value, str):
                value = [x for x in value.replace(',', ' ').split() if x]
            try:
                return [float(x) for x in value]
            except (TypeError, ValueError):
                return value
        if vt == 'xyzvect':
            def axis(v):
                if isinstance(v, str):
                    v = v.replace(',', ' ').split()
                return [float(x) for x in list(v)[:3]]
            if value is None:
                return [0.0, 0.0, 0.0] + [axis(o.get(k, d)) for k, d in
                                          (('vectX', '1 0 0'), ('vectY', '0 1 0'),
                                           ('vectZ', '0 0 1'))]
            v = list(value)
            return [float(x) for x in v[:3]] + [axis(a) for a in v[3:6]]
        if vt == 'color':
            if isinstance(value, str) and value.startswith('#') and len(value) == 7:
                return [int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
            return list(value) if not isinstance(value, str) else value
        return value

    def set(self, value, run=True):
        if self.kind == 'multicheck':
            value = self._multicheck_value(value)
        self._value = self._coerce(value)
        self._newdata = True
        if not self._quiet:
            self._emit()
        if run:
            # a button (or multicheck panel) with its own command calls it
            cmd = self.options.get('command') or self.options.get('callback')
            if callable(cmd) and self.kind in ('button', 'multicheck'):
                cmd()
            else:
                self.scheduleNode()

    # ---- Pmw/Tk widget methods node code calls through widget.widget ---------
    def setlist(self, items):
        self.configure(choices=list(items))

    def setentry(self, text):
        self.set(text, run=False)

    def curselection(self):
        choices = self.options.get('choices') or []
        try:
            return (choices.index(self._value),)
        except ValueError:
            return (0,) if choices else ()

    def invoke(self):
        self.set(self._value, run=True)

    def rebuild(self, valueList):
        """NEMultiCheckButtons: new buttons from a list of names or
        (name,) / (name, {'value': 0|1}) entries."""
        items = []
        for v in valueList or []:
            if isinstance(v, (list, tuple)):
                name = str(v[0])
                on = 1 if (len(v) > 1 and isinstance(v[1], dict) and v[1].get('value')) else 0
            else:
                name, on = str(v), 0
            items.append([name, on])
        self.options['choices'] = [n for n, o in items]
        self._value = items
        self._emit()

    def _multicheck_value(self, value):
        if value is None:
            value = self.options.get('valueList') or []
            if value:
                self.rebuild(value)
                return self._value
            return []
        if isinstance(value, dict):        # {name: 0|1} from the page
            names = self.options.get('choices') or list(value)
            return [[n, 1 if value.get(n) else 0] for n in names]
        return [[str(v[0]), 1 if v[1] else 0] for v in value]

    def get(self):
        if self.kind == 'combo' and isinstance(self._value, list):
            return self._value
        return self._value

    def getDataForSaving(self):
        return self.get()

    def scheduleNode(self):
        node = self.port.node
        net = node.network
        if net is None:
            return
        if net.runOnNewData.value is True:
            node.schedule()

    def configure(self, rebuild=True, **kw):
        changed = False
        for k, v in kw.items():
            if k == 'master':
                self.master = v
            elif k == 'labelCfg':
                self.labelCfg = v
                if isinstance(v, dict):
                    self.label = v.get('text', self.label)
            elif k == 'initialValue':
                self.initialValue = v
            elif k == 'choices' and self.kind == 'combo':
                self.options['choices'] = list(v)
            else:
                self.options[k] = v
            changed = True
        if changed:
            if self.vtype == 'number' and self._value is not None:
                self._value = self._coerce(self._value)
            self._emit()

    def setChoices(self, choices):            # Pmw ComboBox method name
        self.configure(choices=choices)

    # thumbwheel / contour spectrum methods node code calls through .widget
    def setMin(self, v):
        self.configure(min=None if v is None else float(v))

    def setMax(self, v):
        self.configure(max=None if v is None else float(v))

    def setValue(self, v):
        self.set(v, run=False)

    def setSignatures(self, signatures):
        """Isocontour signatures (objects with nval, getFx, getFy, as made by
        UTisocontour): kept as curves of at most 200 points for the page."""
        import numpy
        curves = []
        for sig in signatures or []:
            try:
                n = int(sig.nval)
                x = numpy.zeros((n,), 'f')
                y = numpy.zeros((n,), 'f')
                sig.getFx(x)
                sig.getFy(y)
            except Exception:
                x, y = numpy.asarray(sig[0], 'f'), numpy.asarray(sig[1], 'f')
            step = max(1, len(x) // 200)
            curves.append({'x': [float(v) for v in x[::step]],
                           'y': [float(v) for v in y[::step]]})
        self.configure(signatures=curves)

    def getDescr(self):
        d = {'class': self.className, 'master': self.master,
             'initialValue': self.get()}
        if self.labelCfg:
            d['labelCfg'] = self.labelCfg
        d.update(self.options)
        return d

    def spec(self):
        """What the page needs to draw this widget."""
        opts = {k: jsonable(v) for k, v in self.options.items() if k not in _TK_ONLY}
        return {'class': self.className, 'kind': self.kind, 'master': self.master,
                'label': self.label, 'value': jsonable(self.get()), 'options': opts,
                'known': self.known, 'locked': self.lockedOnPort}

    def _emit(self):
        node = self.port.node
        net = node.network
        if net is not None:
            net.emit('widget', node=node.id, port=self.port.name, widget=self.spec())

    # Tk-era calls that may appear in node code; harmless here
    def update(self):
        pass

    def update_idletasks(self):
        pass
