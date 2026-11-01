
# ---------------------------------------------------------------------------------------
# WEWoS: matplotlib figures drawn off screen (Agg) and shown in panels of the page
# ---------------------------------------------------------------------------------------
import io
from matplotlib.backends.backend_agg import FigureCanvasAgg


class WebCanvas(FigureCanvasAgg):
    """A node's figure canvas: drawn off screen, and every draw() shows the
    figure in a panel of the page (Vision opened a Tk window per node)."""

    def __init__(self, figure, node):
        FigureCanvasAgg.__init__(self, figure)
        self.node = weakref.ref(node)

    def draw(self, *args, **kw):
        FigureCanvasAgg.draw(self)
        node = self.node()
        if node is not None:
            node.figureDrawn()


def figure_rgba(fig):
    """The RGBA pixels of a figure (drawn with Agg; the figure's own canvas
    when it has an Agg one, so the figure is not re-parented)."""
    canvas = fig.canvas
    if not isinstance(canvas, FigureCanvasAgg):
        canvas = FigureCanvasAgg(fig)
    FigureCanvasAgg.draw(canvas)
    return numpy.asarray(canvas.buffer_rgba())


def compose(fig, plots, nbRows=None, nbColumns=None):
    """Fill fig with the figures of the given Axes, one cell each. Vision moved
    the Axes of plotting nodes into the Figure node's figure; matplotlib 3 no
    longer allows an Axes in two figures, so the cells show the plots'
    pictures."""
    fig.clear()
    plots = [p for p in (plots or []) if p is not None]
    n = len(plots)
    if n == 0:
        return fig
    rows = max(1, int(nbRows or 1))
    cols = max(1, int(nbColumns or 1))
    if rows * cols < n:
        cols = int(math.ceil(n / float(rows)))
    seen = []
    for i, ax in enumerate(plots):
        src = getattr(ax, 'figure', None)
        if src is None or src in seen:
            continue
        seen.append(src)
        cell = fig.add_subplot(rows, cols, len(seen))
        cell.imshow(figure_rgba(src))
        cell.set_axis_off()
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1, wspace=0.02, hspace=0.02)
    return fig


class MPLBaseNE(NetworkNode):
    """Base class for nodes wrapping matplotlib objects. A node with a
figure shows it in a panel of the page each time it is drawn."""

    def __init__(self, name='MPLBase', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.figure = None      # matplotlib Figure of this node
        self.axes = None        # matplotlib Axes
        self.canvas = None
        self.imageVersion = 0
        self.ownsMaster = False

    # ---- the page ---------------------------------------------------------------
    def figureDrawn(self):
        self.imageVersion += 1
        if self.network is not None and self.figure is not None:
            w, h = self.figure.get_size_inches() * self.figure.dpi
            self.network.emit('image', node=self.id, name=self.name,
                              version=self.imageVersion, size=[int(w), int(h)])

    def imageData(self):
        if self.figure is None or self.imageVersion == 0:
            return {'png': None}
        from PIL import Image
        import base64
        rgba = figure_rgba(self.figure)
        im = Image.fromarray(rgba, 'RGBA')
        buf = io.BytesIO()
        im.save(buf, 'PNG')
        return {'png': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii'),
                'size': list(im.size), 'mode': 'RGBA', 'version': self.imageVersion}

    def describe(self):
        d = NetworkNode.describe(self)
        if isinstance(self.canvas, WebCanvas):
            d['imageViewer'] = True
        return d

    # ---- axes options (the Draw Area and Set Matplotlib Options nodes) -----------------
    def setDrawArea(self, kw):
        """Apply a dict of options to self.axes (Vision's keys, matplotlib 3)."""
        ax = self.axes
        if ax is None or not kw:
            return
        fig = ax.figure
        if 'left' in kw:
            ax.set_position([kw['left'], kw['bottom'], kw['width'], kw['height']])
        if 'frameon' in kw:
            ax.set_frame_on(bool(kw['frameon']))
        for key, fn in (('title', ax.set_title), ('xlabel', ax.set_xlabel),
                        ('ylabel', ax.set_ylabel)):
            if key in kw and isinstance(kw[key], str):
                fn(kw[key])
        for key, fn in (('xlimit', ax.set_xlim), ('ylimit', ax.set_ylim)):
            if kw.get(key):
                v = kw[key]
                fn(eval(v) if isinstance(v, str) else v)
        if 'xticklabels' in kw and not kw['xticklabels']:
            ax.set_xticklabels([])
        if 'yticklabels' in kw and not kw['yticklabels']:
            ax.set_yticklabels([])
        if 'axison' in kw:
            ax.set_axis_on() if kw['axison'] else ax.set_axis_off()
        if 'autoscaleon' in kw:
            ax.set_autoscale_on(bool(kw['autoscaleon']))
        if 'adjustable' in kw:
            ax.set_adjustable(kw['adjustable'])
        if 'aspect' in kw:
            ax.set_aspect(kw['aspect'])
        if 'anchor' in kw:
            ax.set_anchor(kw['anchor'])
        if 'axisbelow' in kw:
            ax.set_axisbelow(kw['axisbelow'] == 1)
        if kw.get('gridOn') == 1:
            ax.grid(True, color=kw.get('gridcolor', rcParams['grid.color']),
                    linestyle=kw.get('gridlinestyle', rcParams['grid.linestyle']),
                    linewidth=kw.get('gridlinewidth', rcParams['grid.linewidth']),
                    which=kw.get('whichgrid', 'major'))
        elif 'gridOn' in kw:
            ax.grid(False)
        if 'facecolor' in kw:
            ax.set_facecolor(kw['facecolor'])
        if 'edgecolor' in kw:
            for s in ax.spines.values():
                s.set_edgecolor(kw['edgecolor'])
        if 'linewidth' in kw:
            for s in ax.spines.values():
                s.set_linewidth(float(kw['linewidth']))
        for axis, name in ((ax.xaxis, 'xtick'), (ax.yaxis, 'ytick')):
            labels = axis.get_ticklabels()
            if name + '.color' in kw:
                for t in labels:
                    t.set_color(kw[name + '.color'])
            if name + '.labelrotation' in kw:
                for t in labels:
                    t.set_rotation(float(kw[name + '.labelrotation']))
            if name + '.labelsize' in kw:
                for t in labels:
                    t.set_size(float(kw[name + '.labelsize']))
            for which in ('major', 'minor'):
                if '%s.%s.pad' % (name, which) in kw:
                    axis.set_tick_params(which=which, pad=kw['%s.%s.pad' % (name, which)])
                if '%s.%s.size' % (name, which) in kw:
                    axis.set_tick_params(which=which, size=kw['%s.%s.size' % (name, which)])
            if name + '.direction' in kw:
                axis.set_tick_params(direction=kw[name + '.direction'])
        ticklines = ax.get_xticklines() + ax.get_yticklines()
        for key in ('markeredgewidth', 'markeredgecolor', 'markerfacecolor'):
            if key in kw:
                for l in ticklines:
                    getattr(l, 'set_' + key)(kw[key])
        for key, fn in (('figpatch_linewidth', fig.patch.set_linewidth),
                        ('figpatch_facecolor', fig.patch.set_facecolor),
                        ('figpatch_edgecolor', fig.patch.set_edgecolor),
                        ('figpatch_antialiased', fig.patch.set_antialiased)):
            if key in kw:
                fn(kw[key])
        for t in kw.get('text') or []:
            if isinstance(t, dict):
                ax.text(x=t['posx'], y=t['posy'], s=t['textlabel'],
                        horizontalalignment=t.get('horizontalalignment', 'center'),
                        verticalalignment=t.get('verticalalignment', 'center'),
                        rotation=t.get('rotation', 0), transform=ax.transAxes)
        props = {'color': 'text.color', 'fontstyle': 'text.fontstyle',
                 'variant': 'text.fontvariant', 'weight': 'text.fontweight',
                 'size': 'text.fontsize'}
        for prop, key in props.items():
            for k in (key, key.replace('text.', 'Font.')):
                if k in kw:
                    for t in ax.texts:
                        t.set(**{prop: kw[k]})
        for k in ('text.fontangle', 'Font.fontangle'):
            if k in kw:
                for t in ax.texts:
                    t.set_fontstyle(kw[k])
        if 'Font.fontfamily' in kw:
            for t in ax.texts:
                t.set_family(kw['Font.fontfamily'])
        if 'text.usetex' in kw:
            rcParams['text.usetex'] = kw['text.usetex']
        if 'legendlabel' in kw:
            labels = kw['legendlabel'].split(',') if ',' in kw['legendlabel'] \
                else [kw['legendlabel']]
            opts = {}
            for key, opt in (('legend.numpoints', 'numpoints'), ('legend.borderpad', 'borderpad'),
                             ('legend.markerscale', 'markerscale'),
                             ('legend.labelspacing', 'labelspacing'),
                             ('legend.handlelength', 'handlelength'),
                             ('legend.handletextpad', 'handletextpad'),
                             ('legend.borderaxespad', 'borderaxespad'),
                             ('legend.shadow', 'shadow')):
                if key in kw:
                    opts[opt] = kw[key]
            loc = kw.get('legendlocation', 'best')
            ax.legend(labels, loc=locations.get(loc, loc), **opts)
            if 'legend.fontsize' in kw:
                setp(ax.get_legend().get_texts(), fontsize=kw['legend.fontsize'])

    def setDrawAreaDef(self, drawAreaDef):
        """Merge the dicts from the drawAreaDef port and apply them."""
        merged = {}
        for d in drawAreaDef or []:
            if isinstance(d, dict):
                merged.update(d)
        self.setDrawArea(merged)

    def beforeRemovingFromNetwork(self):
        NetworkNode.beforeRemovingFromNetwork(self)
        if self.figure is not None:
            self.figure.clear()

    def onlyDataChanged(self, data):
        """True if only the first port (the data) has new data."""
        ports = self.inputPorts
        if not ports[0].hasNewValidData():
            return False
        for p in self.inputPorts[1:]:
            if p.hasNewValidData():
                return False
        return True


class MPLPlottingNode(MPLBaseNE):
    """Base class for plotting nodes: each has its own figure with one Axes,
shown in a panel of the page, and outputs the Axes."""

    def afterAddingToNetwork(self):
        self.figure = Figure(figsize=(6.4, 4.8), dpi=80)
        self.axes = self.figure.add_subplot(111)
        self.axes.node = weakref.ref(self)
        self.canvas = WebCanvas(self.figure, self)

    codeBeforeDisconnect = """def beforeDisconnect(self, c):
    node = c.port2.node
    node.axes.clear()
    node.canvas.draw()
"""


class MPLFigureNE(MPLBaseNE):
    """A figure holding the plots connected to 'plots' in a grid of nbRows x
nbColumns cells (each cell shows the picture of one plot: matplotlib 3 does
not allow an Axes in two figures), with control over its size, resolution
and colors. It is shown in a panel of the page.

Input:
    plots     - Matplotlib Axes objects (from plotting nodes)
    width, height - size in inches
    dpi       - resolution
    facecolor, edgecolor - colors of the figure's background and border
    nbRows, nbColumns - the grid
    frameon   - draw the figure's frame
Output:
    figure:  the matplotlib Figure
"""

    def afterAddingToNetwork(self):
        self.figure = Figure()
        self.canvas = WebCanvas(self.figure, self)

    def __init__(self, name='Figure2', **kw):
        kw['name'] = name
        MPLBaseNE.__init__(self, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='MPLAxes', required=False, name='plots', singleConnection=False)
        ip.append(datatype='float', required=False, name='width')
        ip.append(datatype='float', required=False, name='height')
        ip.append(datatype='float', required=False, name='linewidth', defaultValue=1)
        ip.append(datatype='int', required=False, name='dpi')
        ip.append(datatype='colorRGB', required=False, name='facecolor')
        ip.append(datatype='colorRGB', required=False, name='edgecolor')
        ip.append(datatype='None', required=False, name='master')
        ip.append(datatype='int', required=False, name='nbRows')
        ip.append(datatype='int', required=False, name='nbColumns')
        ip.append(datatype='boolean', required=False, name='frameon', defaultValue=True)
        ip.append(datatype='boolean', required=False, name='hold', defaultValue=False)
        ip.append(datatype='boolean', required=False, name='toolbar')
        ip.append(datatype='None', required=False, name='packOpts')
        self.outputPortsDescr.append(datatype='MPLFigure', name='figure')
        wd = self.widgetDescr
        wd['width'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'oneTurn': 2,
                       'type': 'float', 'initialValue': 8.125, 'min': 1.0,
                       'labelCfg': {'text': 'width in inches'}}
        wd['height'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'oneTurn': 2,
                        'type': 'float', 'initialValue': 6.125, 'min': 1.0,
                        'labelCfg': {'text': 'height in inches'}}
        wd['linewidth'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'oneTurn': 2,
                           'type': 'int', 'initialValue': 1, 'labelCfg': {'text': 'linewidth'}}
        wd['dpi'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'oneTurn': 10,
                     'type': 'int', 'initialValue': 80, 'min': 10, 'labelCfg': {'text': 'DPI'}}
        wd['nbRows'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'oneTurn': 10,
                        'type': 'int', 'initialValue': 1, 'min': 1, 'labelCfg': {'text': 'nb. rows'}}
        wd['nbColumns'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'oneTurn': 10,
                           'type': 'int', 'initialValue': 1, 'min': 1,
                           'labelCfg': {'text': 'nb. col'}}
        wd['frameon'] = {'class': 'NECheckButton', 'master': 'ParamPanel', 'initialValue': 1,
                         'labelCfg': {'text': 'frame'}}
        self.setFunction("""def doit(self, plots, width, height, linewidth, dpi, facecolor,
edgecolor, master, nbRows, nbColumns, frameon, hold, toolbar, packOpts):
    figure = compose(self.figure, plots, nbRows, nbColumns)
    if width is not None or height is not None:
        w, h = figure.get_size_inches()
        figure.set_size_inches(width or w, height or h)
    if dpi:
        figure.set_dpi(dpi)
    if facecolor is not None:
        figure.set_facecolor(facecolor)
    if edgecolor is not None:
        figure.set_edgecolor(edgecolor)
    figure.patch.set_linewidth(linewidth or 0)
    figure.set_frameon(bool(frameon))
    self.canvas.draw()
    self.outputData(figure=figure)
""")


class MPLImageNE(MPLBaseNE):
    """Draw the plots connected to 'plots' into an image (PIL), e.g. to save
it or to combine it with other images in the Imaging library.

Input:
    plots     - Matplotlib Axes objects
    width, height - size in inches;  dpi - resolution
    facecolor, edgecolor; alphaFace, alphaEdge - colors and their opacity
Output:
    image: a PIL image
"""

    def afterAddingToNetwork(self):
        self.figure = Figure()
        self.canvas = FigureCanvasAgg(self.figure)

    def __init__(self, name='imageFigure', **kw):
        kw['name'] = name
        MPLBaseNE.__init__(self, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='MPLAxes', required=False, name='plots', singleConnection=False)
        ip.append(datatype='float', required=False, name='width')
        ip.append(datatype='float', required=False, name='height')
        ip.append(datatype='int', required=False, name='dpi')
        ip.append(datatype='colorsRGB', required=False, name='facecolor')
        ip.append(datatype='colorsRGB', required=False, name='edgecolor')
        ip.append(datatype='float', required=False, name='alphaFace', defaultValue=0.5)
        ip.append(datatype='float', required=False, name='alphaEdge', defaultValue=0.5)
        ip.append(datatype='boolean', required=False, name='frameon', defaultValue=True)
        ip.append(datatype='boolean', required=False, name='hold', defaultValue=False)
        self.outputPortsDescr.append(datatype='image', name='image')
        wd = self.widgetDescr
        wd['width'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'initialValue': 6.4,
                       'min': 1.0, 'labelCfg': {'text': 'width in inches'}}
        wd['height'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'initialValue': 4.8,
                        'min': 1.0, 'labelCfg': {'text': 'height in inches'}}
        wd['dpi'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'type': 'int',
                     'initialValue': 80, 'min': 10, 'labelCfg': {'text': 'DPI'}}
        wd['alphaFace'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'initialValue': 0.5,
                           'min': 0.0, 'max': 1.0, 'labelCfg': {'text': 'alpha Face'}}
        wd['alphaEdge'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel', 'initialValue': 0.5,
                           'min': 0.0, 'max': 1.0, 'labelCfg': {'text': 'alphaEdge'}}
        wd['frameon'] = {'class': 'NECheckButton', 'master': 'ParamPanel', 'initialValue': 1,
                         'labelCfg': {'text': 'frame'}}
        self.setFunction("""def doit(self, plots, width, height, dpi, facecolor, edgecolor,
alphaFace, alphaEdge, frameon, hold):
    from PIL import Image
    figure = compose(self.figure, plots)
    if width is not None or height is not None:
        w, h = figure.get_size_inches()
        figure.set_size_inches(width or w, height or h)
    if dpi:
        figure.set_dpi(dpi)
    if facecolor is not None:
        figure.patch.set_facecolor(facecolor)
    if edgecolor is not None:
        figure.patch.set_edgecolor(edgecolor)
    figure.patch.set_alpha(alphaFace)
    figure.set_frameon(bool(frameon))
    self.outputData(image=Image.fromarray(figure_rgba(figure), 'RGBA'))
""")


class MatPlotLibOptions(NetworkNode):
    """Options for plots, as a Python dict (the keys of the Draw Area node and
of Vision's options panel), e.g.
  {'gridOn': 1, 'gridcolor': 'grey', 'gridlinestyle': ':',
   'facecolor': '#f8f8ff', 'xtick.labelsize': 8, 'ytick.labelsize': 8,
   'legendlabel': 'data,fit', 'legendlocation': 'upper right'}
Connect it to the drawAreaDef port of plotting nodes.
"""

    def __init__(self, name='Set Matplotlib Options', canvas=None, **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(name='matplotlibOptions', datatype='None')
        self.widgetDescr['matplotlibOptions'] = {
            'class': 'NEScrolledText', 'master': 'ParamPanel', 'lockedOnPort': True,
            'initialValue': "{'gridOn': 1}", 'labelCfg': {'text': 'options (dict)'}}
        self.outputPortsDescr.append(datatype='dict', name='matplotlibOptions')
        self.setFunction("""def doit(self, matplotlibOptions):
    import ast
    opts = matplotlibOptions
    if isinstance(opts, str):
        opts = ast.literal_eval(opts.strip() or '{}')
    if not isinstance(opts, dict):
        raise ValueError('the options must be a dict')
    self.outputData(matplotlibOptions=opts)
""")


def copy_artists(src, dst):
    """Draw the lines, patches and point sets of Axes src into Axes dst.
    Vision's MultiPlot moved them; in matplotlib 3 an artist belongs to one
    Axes, so they are copied."""
    from matplotlib.patches import PathPatch
    from matplotlib.collections import PathCollection
    for l in src.lines:
        dst.plot(l.get_xdata(), l.get_ydata(), color=l.get_color(),
                 linestyle=l.get_linestyle(), linewidth=l.get_linewidth(),
                 marker=l.get_marker(), markersize=l.get_markersize(), label=l.get_label())
    for p in src.patches:
        path = p.get_path().transformed(p.get_patch_transform())
        dst.add_patch(PathPatch(path, facecolor=p.get_facecolor(), edgecolor=p.get_edgecolor(),
                                linewidth=p.get_linewidth(), alpha=p.get_alpha()))
    for c in src.collections:
        if isinstance(c, PathCollection):
            xy = c.get_offsets()
            if len(xy):
                dst.scatter(xy[:, 0], xy[:, 1], s=c.get_sizes(), c=c.get_facecolors(),
                            edgecolors=c.get_edgecolors(), alpha=c.get_alpha())
        else:
            try:
                import copy
                c2 = copy.copy(c)
                c2._axes = None
                c2.figure = None
                dst.add_collection(c2)
            except Exception:
                pass
