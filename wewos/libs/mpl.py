# Ported to Python 3 from MGLTools Vision/matplotlibNodes.py
# Original: Michel Sanner, Daniel Stoffler, Sowjanya Karnati (TSRI).
# Port: Michel Sanner, PhD. Copyright (c) 2026.
"""MatPlotLib: 2D plots (plot, scatter, histogram, bar, pie, contour, pcolor,
error bars, box plots, spectra...) with matplotlib.

Each plotting node draws in its own figure; the figure is drawn off screen
(Agg) and shown in a panel of the page each time it changes (Vision opened a
Tk window per node). The plotting nodes are converted mechanically
(wewos.legacy.py2to3); the base classes are rewritten for matplotlib 3: the
draw-area options use today's matplotlib API, and the Figure and
ImageFigure nodes compose their plots' pictures, as an Axes can no longer be
moved to another figure. Set Matplotlib Options takes its options as a dict
written in its panel (Vision's Tk options panel is not ported).
"""
import re

# latest working version of matplotlib is 0.87.7 using numpy 1.0.3
# latest working version of matplotlib is 0.87.6 using Numeric 23.8
# (matplotlib 0.87.7 has a small bug using Numeric 23.8)
# there are multiple bugs in matplotlib when using Numeric 24.2

#TODO:
# - add and verify controls such as size, labels, legends etc
# - maybe encapsulate all these common options into a single node
# - alpha values per axis
# - use axes rather than subplot
#

try:
    import matplotlib
except:
    import warnings
    import sys
    if sys.platform == 'linux2':
        warnings.warn("""to use matplotlib, you need first to install openssl
the mgltools 32 bit linux binaries need openssl version 0.9.7
the mgltools 64 bit linux binaries need openssl version 0.9.8
you can have both openssl versions (0.9.7 and 0.9.8) installed on your computer.
""", stacklevel=2)
        
import types
import weakref
import math, os, sys

from numpy import array
from matplotlib.colors import cnames
from matplotlib.lines import Line2D,lineStyles,TICKLEFT, TICKRIGHT, TICKUP, TICKDOWN
#from matplotlib.transforms import Value
from matplotlib import rcParams

#mplversion = int(matplotlib.__version__.split(".")[2])
mplversion = [int(x) for x in re.findall(r"\d+", matplotlib.__version__)[:3]]
import re
#print "mplversion:", mplversion


"""
This module implements Vision nodes exposing matplotlib functionatility.

MPLBaseNE:
---------
The class provides a base class for all nodes exposing matplotlib functionality

its purpose is to to create the attributes described below and implement
methods shared by all nodes.

Attributes:
    self.figure = None:  # node's figure object
    # This attribute always points to the matplotlib Figure object which has
    # a FigureCanvasTkAgg object in its .canvas attribute

    # self.canvas FigureCanvasTkAgg

    self.axes = None
    # This attribute points to the matplotlib Axes instance used by this node

    self.axes.figure # figure in which the axes is currently drawn

Methods:        
    def createFigure(self, master=None, width=None, height=None, dpi=None,
                     facecolor=None, edgecolor=None, frameon=None,
                     packOpts=None, toolbar=True):

    # This method is used by all nodes if they need to create a Figure object
    # from the matplotlib library and a FigureCanvasTkAgg object for this
    # figure.

    def setFigure(self, figure):
    # This method place the node's axes object into the right Figure
           

    def beforeRemovingFromNetwork(self):
    # this method is called when a node is deleted from a network.  Its job is
    # to delete FigureCanvasTkAgg and Axes when appropriate.
    

MPLFigure:
-----------
The MPLFigure node allows the creation of a plotting area in which one
or more Axes can be added, where an Axes is a 2D graphical representation
of a data set (i.e. 2D plot).  A 'master' can be apecified to embed the figure
in other panels.  This node provides control over parameter that apply to the
MPLFigure such, width, height, dpi, etc.


Plotting Node:
-------------
Plotting nodes such as Histogram, Plot, Scatter, Pie, etc. take adtasets and
render them as 2D plots.  They alwas own the axes.
If the data to be rendered is the only input to these nodes, they will create
a default Figure, add a default Plot2D to this figure, and draw the data in
this default 2D plot.
"""

from wewos.engine import NetworkNode, NodeLibrary
from wewos.engine.datatypes import AnyArrayType

# make sure Tk is used as a backend
matplotlib.use('Agg', force=True)     # figures are drawn off screen

from matplotlib.figure import Figure
from matplotlib.axes import Axes, Subplot #, PolarSubplot, PolarAxes
from matplotlib.pylab import *
import numpy
from matplotlib.artist import setp
from matplotlib.colors import colorConverter


def _get_cmap(name=None, lut=None):
    """cm.get_cmap, which matplotlib 3.9 removed."""
    get = getattr(cm, 'get_cmap', None)
    if get is not None:
        return get(name, lut)
    import matplotlib as _mpl
    c = _mpl.colormaps[name if name is not None else rcParams['image.cmap']]
    return c.resampled(lut) if lut is not None else c


_MPLV = tuple(int(x) for x in matplotlib.__version__.split('.')[:2])
_PAPERTYPE = _MPLV < (3, 9)        # savefig's papertype: removed in 3.9


def _hold_kw(hold):
    """contour's hold= (Vision's networks give it): removed in matplotlib 3.0."""
    return {'hold': hold} if _MPLV < (3, 0) else {}


def _filled_kw():
    """colorbar's filled=True: removed in newer matplotlib."""
    import inspect
    from matplotlib.colorbar import Colorbar
    try:
        ok = 'filled' in inspect.signature(Colorbar.__init__).parameters
    except (TypeError, ValueError):
        ok = False
    return {'filled': True} if ok else {}
from numpy import sum, asarray, linspace

# ---- Vision.colours and Vision.posnegFill (ported) ----
"""
Some simple functions to generate colours.
"""


def pastel(colour, weight=2.4):
    """ Convert colour into a nice pastel shade"""
    rgb = asarray(colorConverter.to_rgb(colour))
    # scale colour 
    maxc = max(rgb)
    if maxc < 1.0 and maxc > 0:
        # scale colour
        scale = 1.0 / maxc
        rgb = rgb * scale
    # now decrease saturation
    total = sum(rgb)
    slack = 0
    for x in rgb:
        slack += 1.0 - x

    # want to increase weight from total to weight
    # pick x s.t.  slack * x == weight - total
    # x = (weight - total) / slack
    x = (weight - total) / slack

    rgb = [c + (x * (1.0-c)) for c in rgb]

    return rgb

def get_colours(n):
    """ Return n pastel colours. """
    base = asarray([[1,0,0], [0,1,0], [0,0,1]])

    if n <= 3:
        return base[0:n]

    # how many new colours to we need to insert between
    # red and green and between green and blue?
    needed = (((n - 3) + 1) / 2, (n - 3) / 2)

    colours = []
    for start in (0, 1):
        for x in linspace(0, 1, needed[start]+2):
            colours.append((base[start] * (1.0 - x)) +
                           (base[start+1] * x))

    return [pastel(c) for c in colours[0:n]]



def findZero(i,x,y1,y2):
     im1 = i-1
     m1 = (y1[i] - y1[im1])/(x[i] - x[im1])
     m2 = (y2[i] - y2[im1])/(x[i] - x[im1])
     b1 = y1[im1] - m1*x[im1]
     b2 = y2[im1] - m2*x[im1]
     xZero = (b1 - b2)/(m2 - m1)
     yZero = m1*xZero + b1
     return (xZero, yZero)

def posNegFill(x,y1,y2):
      diff = y2 - y1
      pos = []
      neg = []
      xx1 = [x[0]]
      xx2 = [x[0]]
      yy1 = [y1[0]]
      yy2 = [y2[0]]
      oldSign = (diff[0] < 0 )
      npts = x.shape[0]
      for i in range(1,npts):
          newSign = (diff[i] < 0)
          if newSign != oldSign:
              xz,yz = findZero(i,x,y1,y2)
              xx1.append(xz)
              yy1.append(yz)
              xx2.reverse()
              xx1.extend(xx2)
              yy2.reverse()
              yy1.extend(yy2)
              if oldSign:
                  neg.append( (xx1,yy1) )
              else:
                  pos.append( (xx1,yy1) )
              xx1 = [xz,x[i]]
              xx2 = [xz,x[i]]
              yy1 = [yz,y1[i]]
              yy2 = [yz,y2[i]]
              oldSign = newSign
          else:
              xx1.append( x[i])
              xx2.append( x[i])
              yy1.append(y1[i])
              yy2.append(y2[i])
              if i == npts-1:
                  xx2.reverse()
                  xx1.extend(xx2)
                  yy2.reverse()
                  yy1.extend(yy2)
                  if oldSign :
                      neg.append( (xx1,yy1) )
                  else:
                      pos.append( (xx1,yy1) )
      return pos,neg
##
##  QUESTIONS
##  Does this have to be Tk specific or could I use FigureCanvasAgg
##  !FigureCanvasAgg is OK

##  Should I use FigureManagerBase rather than FigureCanvasAgg ?
##  ! FigureCanvas Agg is OK

##  how to destroy a figure ?
##  ! seems to work

##  figure should have a set_dpi method
##  ! use figure.dpi.set() for now but might become API later

##  how to remove the tool bar ?
##  ! John added a note about this

##  What option in a Figure can beset without destroying the Figure
##    and which ones are constructor only options ?
##  ! nothing should require rebuilding a Figure

##  Why does add_axes return the axis that already exists if the values for
##    building the Axes object are the same ? either this has to change or
##    adding an instance of an Axes should be fixed (prefered)
##  !John made a note to add an argument to matplotlib

##  Pie seems to have a problem when shadow is on !
##  !Find out the problem, because shadows are on even when check button is off
##  !for ce aspect ratio to square

##  Plot lineStyle, color, linewidth etc should be set by a set node that uses
##    introspection on the patch? to find otu what can be set ??
## !Use ObjectInspector

## why is figimage not an axes method ?
## !use imshow

from numpy import iterable
try:
    from matplotlib.dates import DayLocator, HourLocator, \
         drange, date2num
    from pytz import timezone
except:
    pass

try:
    from pytz import common_timezones
except:
    common_timezones=[]
#global variables
locations={'best' : 0,
          'upper right'  : 1, 
          'upper left'   : 2,
          'lower left'   : 3,
          'lower right'  : 4,
          'right'        : 5,
          'center left'  : 6,
          'center right' : 7,
          'lower center' : 8,
          'upper center' : 9,
          'center'       : 10,}
colors={
        'blue' : 'b',
        'green' : 'g',
        'red' : 'r',
        'cyan' : 'c',
        'magenta' :'m',
        'yellow' :'y',
        'black': 'k',
        'white' : 'w',
        }          

markers= {
                'square'         :  's',
                'circle'	 :  'o',
                'triangle up'    :  '^',
                'triangle right' :  '>',
                'triangle down'  :  'v',
                'triangle left'  :  '<',
                'diamond'	 :  'd',
                'pentagram'	 :  'p',
                'hexagon'	 :  'h',
                'octagon'	 :  '8',
                }
 
cmaps=['autumn','bone', 'cool','copper','flag','gray','hot','hsv','jet','pink', 'prism', 'spring', 'summer', 'winter']

def get_styles():
    styles={}
    for ls in list(Line2D._lineStyles.keys()):
        styles[Line2D._lineStyles[ls][6:]]=ls
    for ls in list(Line2D.markers.keys()):
        styles[Line2D.markers[ls]]=ls
        #these styles are not recognized
        if 'steps' in styles:
            del styles['steps']
        for s in  list(styles.keys()):
            if s =="nothing":
                del styles['nothing']
            if s[:4]=='tick':
                del styles[s]
    return styles           


        ## if kwargs.has_key('force'):
        ##     force = kwargs['force']
        ##     del kwargs['force']
        ## else:
        ##     force = False

        ## if iterable(args[0]):
        ##     key = tuple(args[0]), tuple(kwargs.items())
        ## else:
        ##     key = args[0], tuple(kwargs.items())            
            
        ## ## if not force and self._seen.has_key(key):
        ## ##     ax = self._seen[key]
        ## ##     self.sca(ax)
        ## ##     return ax

        ## if not force:
        ##     ax = self._axstack.get(key)
        ##     if ax is not None:
        ##         self.sca(ax)
        ##         return ax

        ## if not len(args): return        
        ## if isinstance(args[0], Axes):
        ##     a = args[0]
        ##     # this is too early, if done here bbox is 0->1
        ##     #a.set_figure(self)
        ##     a.figure = self
        ## else:
        ##     rect = args[0]
        ##     #ispolar = popd(kwargs, 'polar', False)
        ##     ispolar = kwargs.get('polar', False)
        ##     if ispolar != False:
        ##         del kwargs['polar']
        ##     if ispolar:
        ##         a = PolarAxes(self, rect, **kwargs)
        ##     else:
        ##         a = Axes(self, rect, **kwargs)            

        ## ## self.axes.append(a)
        ## ## self._axstack.push(a)
        ## ## self.sca(a)
        ## ## self._seen[key] = a
        ## ##self._axstack.add(key, a)
        ## self._axstack.push(a)
        ## self.sca(a)
        ## return a




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








class MPLDrawAreaNE(NetworkNode):
    """Class for configuring the axes.
    The following options can be set.
    left,bottom,width,height ----allows to set the position of the axes.
    frame on/off --- allows to on or off frame
    hold on/off --- allows to on or off hold.When hold is True, subsequent plot commands will be added to
                    the current axes.  When hold is False, the current axes and figure will be cleared on
                    the next plot command
    title --- allows to set title of the figure
    xlabel  ---allows to set xlabel of the figure
    ylabel ---allows to set ylabel of the figure
    xlimit --- set autoscale off before setting xlimit.
    y limit --- set autoscale off before setting  ylimit.
    xticklabels on/off --- allows to on or off  xticklabels
    yticklabels on/off --- allows to on or off  yticklabels
    axis on/off        --- allows to on or off  axis
    autoscale on/off ---   when on sets default axes limits ,when off sets limit from xlimit and ylimit  entries.
    """

    def __init__(self, name='Draw Area', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='float', required=False, name='left', defaultValue=.1)
        ip.append(datatype='float', required=False, name='bottom', defaultValue=.1)
        ip.append(datatype='float', required=False, name='width', defaultValue=.8)
        ip.append(datatype='float', required=False, name='height', defaultValue=.8)
        ip.append(datatype='boolean', required=False, name='frameon', defaultValue=True)
        ip.append(datatype='boolean', required=False, name='hold', defaultValue=False)
        ip.append(datatype='string', required=False, name='title', defaultValue='Figure')
        ip.append(datatype='string', required=False, name='xlabel', defaultValue='X')
        ip.append(datatype='string', required=False, name='ylabel', defaultValue='Y')
        ip.append(datatype='string', required=False, name='xlimit', defaultValue='')
        ip.append(datatype='string', required=False, name='ylimit', defaultValue='')
        ip.append(datatype='boolean', required=False, name='xticklabels', defaultValue=True)
        ip.append(datatype='boolean', required=False, name='yticklabels', defaultValue=True)
        ip.append(datatype='boolean', required=False, name='axison', defaultValue=True)
        ip.append(datatype='boolean', required=False, name='autoscaleon', defaultValue=True)
        self.widgetDescr['left'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':1., 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':0.1,
            'labelCfg':{'text':'left (0. to 1.)'} }

        self.widgetDescr['bottom'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':1., 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':0.1,
            'labelCfg':{'text':'bottom (0. to 1.)'} }

        self.widgetDescr['width'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':1., 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':0.8,
            'labelCfg':{'text':'width (0. to 1.)'} }

        self.widgetDescr['height'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':1., 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':0.8,
            'labelCfg':{'text':'height (0. to 1.0)'} }

        self.widgetDescr['frameon'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelGridCfg':{'sticky':'w'},
            'initialValue':1, 'labelCfg':{'text':'frame'} }

        self.widgetDescr['hold'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelGridCfg':{'sticky':'w'},
            'initialValue':0, 'labelCfg':{'text':'hold'} }

        self.widgetDescr['title'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'title'},'labelGridCfg':{'sticky':'w'},
            'initialValue':'Figure:'}

        self.widgetDescr['xlabel'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'X label'},'labelGridCfg':{'sticky':'w'},
            'initialValue':'X'}

        self.widgetDescr['ylabel'] = {
            'class':'NEEntry', 'master':'ParamPanel','labelGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'Y label'},
            'initialValue':'Y'}

        self.widgetDescr['xlimit'] = {
            'class':'NEEntry', 'master':'ParamPanel','labelGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'X limit'},
            'initialValue':''}

        self.widgetDescr['ylimit'] = {
            'class':'NEEntry', 'master':'ParamPanel','labelGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'Y limit'},
            'initialValue':''}
            
        self.widgetDescr['xticklabels'] = {
         'class':'NECheckButton', 'master':'ParamPanel','labelGridCfg':{'sticky':'w'},
            'initialValue':1, 'labelCfg':{'text':'xticklabels'} }   

        self.widgetDescr['yticklabels'] = {
        'class':'NECheckButton', 'master':'ParamPanel','labelGridCfg':{'sticky':'w'},'labelGridCfg':{'sticky':'w'},
            'initialValue':1, 'labelCfg':{'text':'yticklabels'} }
            
            
        self.widgetDescr['axison'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1, 'labelCfg':{'text':'axis on'} }
        self.widgetDescr['autoscaleon'] = {
            'class':'NECheckButton', 'master':'ParamPanel','labelGridCfg':{'sticky':'w'},
            'initialValue':1, 'labelCfg':{'text':'autoscale on'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLDrawArea', name='drawAreaDef')
        
        code = """def doit(self, left, bottom, width, height, frameon, hold, title,
xlabel, ylabel, xlimit, ylimit, xticklabels, yticklabels, axison, autoscaleon):

    kw = {'left':left, 'bottom':bottom, 'width':width, 'height':height,
    'frameon':frameon, 'hold':hold, 'title':title, 'xlabel':xlabel,
    'ylabel':ylabel, 'axison':axison, 'xticklabels': xticklabels,'yticklabels': yticklabels,'xlimit':xlimit,'ylimit':ylimit,'autoscaleon':autoscaleon}
    
    self.outputData(drawAreaDef=kw)
"""
        self.setFunction(code)


class MPLMergeTextNE(NetworkNode):
    """Class for writting multiple labels in the axes.Takes input from Text
    nodes.
    """
    def __init__(self, name='MergeText', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='MPLDrawArea', required=False,name='textlist',singleConnection=False)
        op = self.outputPortsDescr
        op.append(datatype='MPLDrawArea', name='drawAreaDef')
        code = """def doit(self,textlist):
    kw={'text':textlist}
    self.outputData(drawAreaDef=kw)
"""
        self.setFunction(code)
        
        
########################################################################
####
####    PLOTTING NODES
####
########################################################################

class FillNE(MPLPlottingNode):
    """plots filled polygons. 
x  - list of x vertices
y  - list of y vertices
fillcolor - color 
"""
    
    def __init__(self, name='Fill', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string', required=False, name='fillcolor', defaultValue='w')
        ip.append(datatype='MPLDrawArea', required=False,name='drawAreaDef',singleConnection=False)
        self.widgetDescr['fillcolor'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'white',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'fillcolor:'}}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype='None', name='fig') 
        code = """def doit(self, x, y, fillcolor, drawAreaDef):
    self.axes.clear()
    ax=self.axes
    p=ax.fill(x,y,fillcolor)
    self.setDrawAreaDef(drawAreaDef)
    self.canvas.draw()    
    self.outputData(axes=self.axes,fig=p)
"""
        self.setFunction(code)

class PolarAxesNE(MPLPlottingNode):
    """ This node  plots on PolarAxes 
Input:
    y          - sequence of values
    x          - None; sequence of values
Adjustable parameters:
    grid --grid on or off(default is on)
    gridcolor --color of the grid
    gridlinewidth --linewidth of the grid 
    gridlinestyle --gridlinestyle
    xtickcolor -- color of xtick
    ytickcolor -- color of ytick
    xticksize --size of xtick
    yticksize --size of ytick
"""
    def __init__(self, name='PolarAxes', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ## self.styles={}
        ## for ls in Line2D._lineStyles.keys():
        ##    self.styles[Line2D._lineStyles[ls][6:]]=ls
        ## for ls in Line2D.markers.keys():
        ##    self.styles[Line2D.markers[ls][6:]]=ls
        ##     #these styles are not recognized
        ## #del self.styles['steps']
        ## for s in  self.styles.keys():
           
        ##    if s =="nothing":
        ##        del self.styles['nothing']
        ##    if s[:4]=='tick':
        ##        del self.styles[s]
        self.styles = get_styles()
        self.colors = colors
        ip = self.inputPortsDescr
        #ip.append(datatype='MPLAxes', required=False, name='p',
                  #singleConnection=True)#,beforeDisconnect=codeBeforeDisconnect)
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',  name='x',beforeDisconnect=self.codeBeforeDisconnect) 
        ip.append(datatype='string', required=False, name='lineStyle', defaultValue='solid')
        ip.append(datatype='None', required=False, name='color', defaultValue='black')
        ip.append(datatype='boolean', required=False, name='grid', defaultValue=1)
        ip.append(datatype='str', required=False, name='gridlineStyle', defaultValue='--')
        ip.append(datatype='str', required=False, name='gridcolor', defaultValue='gray')
        ip.append(datatype='float', required=False, name='gridlinewidth', defaultValue=1)
        ip.append(datatype='str', required=False, name='axisbg', defaultValue='white')
        ip.append(datatype='str', required=False, name='xtickcolor', defaultValue='black')
        ip.append(datatype='str', required=False, name='ytickcolor', defaultValue='black')
        ip.append(datatype='float', required=False, name='xticksize', defaultValue=12)
        ip.append(datatype='float', required=False, name='yticksize', defaultValue=12)
        ip.append(datatype='MPLDrawArea', required=False,name='drawAreaDef',singleConnection=False)
        self.widgetDescr['grid'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1, 'labelCfg':{'text':'grid'} ,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},}
        self.widgetDescr['lineStyle'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.styles.keys()),
            'fixedChoices':True,
            'initialValue':'solid',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'line style:'}}
        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.colors.keys()),
            'fixedChoices':True,
            'initialValue':'black',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'color:'}}
        self.widgetDescr['gridlineStyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(lineStyles.keys()),
            'fixedChoices':True,
            'initialValue':'--',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'gridlinestyle:'}}  
        self.widgetDescr['gridcolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'gray',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'gridcolor:'}}    
        self.widgetDescr['gridlinewidth'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'float',
            'wheelPad':2, 'initialValue':1,
            'labelCfg':{'text':'gridlinewidth'},
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'}}
        self.widgetDescr['axisbg'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'white',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'axisbg:'}}
        self.widgetDescr['xtickcolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'black',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'xtickcolor:'}}
        self.widgetDescr['ytickcolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'black',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'ytickcolor:'}}    
        self.widgetDescr['xticksize'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'float',
            'wheelPad':2, 'initialValue':12,
            'labelCfg':{'text':'xticksize'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'} }
        self.widgetDescr['yticksize'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'float',
            'wheelPad':2, 'initialValue':12,
            'labelCfg':{'text':'yticksize'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLFigure', name='figure')
        code = """def doit(self, y, x, lineStyle, color, grid, gridlineStyle,
gridcolor, gridlinewidth, axisbg, xtickcolor, ytickcolor, xticksize, yticksize, drawAreaDef):
        
        self.figure.clear()
        self.setDrawAreaDef(drawAreaDef)
        if grid==1:
            matplotlib.rc('grid',color=gridcolor,linewidth=gridlinewidth,linestyle=gridlineStyle) 
        matplotlib.rc('xtick',color=xtickcolor,labelsize=xticksize)
        matplotlib.rc('ytick',color=ytickcolor,labelsize=yticksize)
        colorChar = self.colors[color]
        lineStyleChar = self.styles[lineStyle]
        new_axes=self.figure.add_axes(self.axes.get_position(),polar=True,facecolor=axisbg)        
        self.axes=new_axes
        self.axes.plot(x, y, colorChar+lineStyleChar)  
        if grid!=1:
                new_axes.grid(grid)
        self.canvas.draw()
        self.outputData(figure=self.figure)
"""
        self.setFunction(code)



class StemNE(MPLPlottingNode):
    """A stem plot plots vertical lines (using linefmt) at each x location
from the baseline to y, and places a marker there using markerfmt.  A
horizontal line at 0 is is plotted using basefmt
input: list of x values 
Return value is (markerline, stemlines, baseline) .
"""    
    def __init__(self, name='Stem', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list',required=True, name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',required=True, name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string',required=False,name='stemlinestyle', defaultValue='--')
        ip.append(datatype='string',required=False,name='stemlinecolor', defaultValue='b')
        ip.append(datatype='string',required=False,name='markerstyle', defaultValue='o')
        ip.append(datatype='string',required=False,name='markerfacecolor', defaultValue='b')
        ip.append(datatype='string',required=False,name='baselinecolor', defaultValue='b')
        ip.append(datatype='string',required=False,name='baselinestyle', defaultValue='-')
        ip.append(datatype='MPLDrawArea', required=False,name='drawAreaDef',singleConnection=False)
        self.widgetDescr['stemlinestyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['-.','--','-',':'],
            'fixedChoices':True,
            'initialValue':'--',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'stemlinestyle:'}}
        self.widgetDescr['stemlinecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()),
            'fixedChoices':True,
            'initialValue':'b',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'stemlinecolor:'}}
        markers = list(Line2D.markers.keys())
        if None in markers: markers.remove(None)
        self.widgetDescr['markerstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':markers,
            'fixedChoices':True,
            'initialValue': 'o',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'markerstyle:'}}
        self.widgetDescr['markerfacecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()),
            'fixedChoices':True,
            'initialValue':'k',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'markerfacecolor:'}}
        self.widgetDescr['baselinestyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['-.','--','-',':'],
            'fixedChoices':True,
            'initialValue':'-',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'baselinestyle:'}}
        self.widgetDescr['baselinecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()),
            'fixedChoices':True,
            'initialValue':'k',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'baselinecolor:'}}
                
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='stem')
        code = """def doit(self, x, y, stemlinestyle, stemlinecolor, markerstyle,
markerfacecolor, baselinecolor, baselinestyle, drawAreaDef):
    self.axes.clear()
    linefmt=stemlinecolor+stemlinestyle
    markerfmt=markerfacecolor+markerstyle
    basefmt= baselinecolor+baselinestyle
    markerline, stemlines, baseline = self.axes.stem(x, y, linefmt=linefmt, markerfmt=markerfmt, basefmt=basefmt )
    self.setDrawAreaDef(drawAreaDef)
    self.canvas.draw()
    self.outputData(stem=self.axes)
"""
        self.setFunction(code)
       
class MultiPlotNE(MPLPlottingNode):
    """This node allows to plot multiple plots on same axes
input: axes instances
    """        
    def __init__(self, name='MultiPlot', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='MPLAxes', required=True, name='multiplot', singleConnection=False,beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef', singleConnection=False)   
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='multiplot')          
        code = """def doit(self, plots, drawAreaDef):
    self.axes.clear()
    ax = self.axes
    for p in plots:
        copy_artists(p, ax)
    ax.autoscale_view()
    self.setDrawAreaDef(drawAreaDef)
    self.canvas.draw()
    self.outputData(multiplot=self.axes)
"""
        self.setFunction(code)
        
class TablePlotNE(MPLPlottingNode):
    """Adds a table to the current axes and plots bars.  
input:
cellText - list of values
rowLabels - list of labels
rowColours - list of colors
colLabels  - list of labels
colColours - list of colors
location - location where the table to be placed.
""" 
    def __init__(self, name='TablePlot', **kw):
        """
        TABLE(cellText=None, cellColours=None,
              cellLoc='right', colWidths=None,
              rowLabels=None, rowColours=None, rowLoc='left',
              colLabels=None, colColours=None, colLoc='center',
              loc='bottom', bbox=None):

        Adds a table to the current axes and plots bars.  
        """
        kw['name'] = name
        locs=list(locations.keys())
        locs.append("bottom")
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list',required=True, name='values',singleConnection="auto",beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',required=True, name='rowLabels',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',required=True, name='colLabels',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',required=False, name='rowColors')
        ip.append(datatype='list',required=False, name='colColors')
        ip.append(datatype='string',required=False, name='location', defaultValue='bottom')
        ip.append(datatype='MPLDrawArea',required=False,name='drawAreaDef',singleConnection=False)
        self.widgetDescr['location'] = {
        'class':'NEComboBox', 'master':'node',
            'choices':locs,
            'fixedChoices':True,
            'initialValue':'bottom',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'Location:'}}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')

        code = """def doit(self, values, rowLabels, colLabels, rowColors,
colColors, location, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    #self.axes.set_position([0.2, 0.2, 0.7, 0.6])
    data=[]
    nd=[]
    for val in values :
        for v in val:
            nd.append(float(v))
        data.append(nd)
        nd=[]
    #rcolours = get_colours(len(colLabels))
    rows = len(data)
    ind = arange(len(colLabels)) + 0.3  # the x locations for the groups
    cellText = []
    width = 0.4     # the width of the bars
    yoff = array([0.0] * len(colLabels)) # the bottom values for stacked bar chart
    for row in range(rows):
        self.axes.bar(ind, data[row], width, bottom=yoff,
                      color=rowColors[row] if rowColors else None)
        yoff = yoff + data[row]
        cellText.append(['%1.1f' % x for x in yoff])
    the_table = self.axes.table(cellText=cellText,
                  rowLabels=rowLabels,
                  rowColours=rowColors,
                  colColours=colColors,
                  colLabels=colLabels,
                  loc=location)
    if location=="bottom":
        self.axes.set_xticks([])
        self.axes.set_xticklabels([])
    self.canvas.draw()
    self.outputData(plot=self.axes)
"""
        self.setFunction(code)
        
class HistogramNE(MPLPlottingNode):
    """This nodes takes a list of values and builds a histogram using matplotlib
http://matplotlib.sourceforge.net/matplotlib.pylab.html#-hist

Compute the histogram of x.  bins is either an integer number of
bins or a sequence giving the bins.  x are the data to be binned.
 
The return values is (n, bins, patches)
 
If normed is true, the first element of the return tuple will be the
counts normalized to form a probability distribtion, ie,
n/(len(x)*dbin)
        
Addition kwargs: hold = [True|False] overrides default hold state

Input:
    values:    sequence of values
    bins=10:   number of dequence giving the gins
    normed=0   normalize

Output:
    plot       Matplotlib Axes object
"""    
    def __init__(self, name='Histogram', **kw):
        kw['name'] = name

        MPLPlottingNode.__init__(*(self,), **kw)
        self.colors=cnames
        ip = self.inputPortsDescr
        ip.append(datatype='None', name='values',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None', required=False, name='bins', defaultValue=10)
        ip.append(datatype='boolean', required=False, name='normed', defaultValue=False)
        ip.append(datatype='float', required=False, name='patch_antialiased', defaultValue=1)
        ip.append(datatype='float', required=False, name='patch_linewidth', defaultValue=1)
        ip.append(datatype='string', required=False, name='patch_edgecolor', defaultValue='black')
        ip.append(datatype='string', required=False, name='patch_facecolor', defaultValue='blue')
        ip.append(datatype='MPLDrawArea',required=False,name='drawAreaDef',singleConnection=False)
        self.widgetDescr['bins'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':10, 'type':'int', 'wheelPad':2,
            'initialValue':10,
            'labelCfg':{'text':'# of bins'} }

        self.widgetDescr['normed'] = {
            'class':'NECheckButton', 'master':'node',
            'initialValue':1, 'labelCfg':{'text':'normalize'},
            }
        self.widgetDescr['patch_linewidth'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'int',
            'wheelPad':2, 'initialValue':1,
            'labelCfg':{'text':'linewidth'} }
        self.widgetDescr['patch_antialiased'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'antialiased:'},
            'initialValue':1,}
        self.widgetDescr['patch_edgecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(self.colors.keys()),
            'fixedChoices':True,
            'initialValue':'black',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'edgecolor:'}}
        self.widgetDescr['patch_facecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(self.colors.keys()),
            'fixedChoices':True,
            'initialValue':'blue',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'facecolor:'}}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')

        code = """def doit(self, values, bins, normed, patch_antialiased,
patch_linewidth, patch_edgecolor, patch_facecolor, drawAreaDef):
    self.axes.clear()
    n, bins, patches = self.axes.hist(numpy.ravel(values) if numpy.ndim(values) > 1 else values,
                   bins=bins, density=bool(normed))
    self.setDrawAreaDef(drawAreaDef)
    if self.axes.patches:
        for p in self.axes.patches:
            p.set_linewidth(patch_linewidth)
            p.set_edgecolor(patch_edgecolor)
            p.set_facecolor(patch_facecolor)
            p.set_antialiased(patch_antialiased)
    self.canvas.draw()
    self.outputData(plot=self.axes)
"""
        self.setFunction(code)

#Plot Nodes

class PlotNE(MPLPlottingNode):
    """This nodes takes two lists of values and plots the the second against the first.

Input:
    y          - sequence of values
    x          - None; sequence of values
    figure     - None; MPLFigure object object into which to place the drawing

Output:
    plot       Matplotlib Axes object
    line:   - line
"""
    
    def __init__(self, name='Plot', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        self.styles=get_styles()
        self.colors=colors        
        self.joinstyles = getattr(Line2D, 'validJoin', ('miter', 'round', 'bevel'))
        self.capstyles = getattr(Line2D, 'validCap', ('butt', 'round', 'projecting')) 
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', required=False, name='x')
        ip.append(datatype='string', required=False, name='lineStyle', defaultValue='solid')
        ip.append(datatype='None', required=False, name='color', defaultValue='black')
        ip.append(datatype='boolean', required=False, name='line_antialiased', defaultValue=1)
        ip.append(datatype='float', required=False, name='line_linewidth', defaultValue=1)
        ip.append(datatype='string', required=False, name='solid_joinstyle', defaultValue='miter')
        ip.append(datatype='string', required=False, name='solid_capstyle', defaultValue='projecting')
        ip.append(datatype='string', required=False, name='dash_capstyle', defaultValue='butt')
        ip.append(datatype='string', required=False, name='dash_joinstyle', defaultValue='miter')
        ip.append(datatype='MPLDrawArea', required=False,name='drawAreaDef',singleConnection=False)
        
        self.widgetDescr['lineStyle'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.styles.keys()),
            'fixedChoices':True,
            'initialValue':'solid',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'line style:'}}

        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.colors.keys()),
            'fixedChoices':True,
            'initialValue':'black',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'color:'}}
            
        self.widgetDescr['dash_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'butt',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash_capstyle:'}}
        self.widgetDescr['dash_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash _joinstyle:'}}
        self.widgetDescr['solid_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'projecting',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_capstyle:'}}
        self.widgetDescr['solid_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_joinstyle:'}}
        self.widgetDescr['line_linewidth'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'int',
            'wheelPad':2, 'initialValue':1,
            'labelCfg':{'text':'linewidth'} }
        
        self.widgetDescr['line_antialiased'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'antialiased:'},
            'initialValue':1,}        
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        
        code = """def doit(self, y, x, lineStyle, color, line_antialiased,
line_linewidth, solid_joinstyle, solid_capstyle, dash_capstyle, dash_joinstyle,
drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    colorChar = self.colors[color]
    lineStyleChar = self.styles[lineStyle]
    if x is None:
        l = self.axes.plot(y, colorChar+lineStyleChar)
    else:
        l = self.axes.plot(x, y, colorChar+lineStyleChar)
    #line properties
    if  self.axes.lines:
        for l in self.axes.lines:
            l.set_linewidth(line_linewidth)
            l.set_antialiased(line_antialiased)
            l.set_solid_joinstyle(solid_joinstyle)
            l.set_solid_capstyle(solid_capstyle)
            l.set_dash_capstyle(dash_capstyle)
            l.set_dash_joinstyle(dash_joinstyle)
            
    self.canvas.draw()
    self.outputData(plot=self.axes)
"""
        self.setFunction(code)

class PlotDateNE(MPLPlottingNode):
    """This nodes takes two lists of values and plots the the second against the first.

Input:
    y          - sequence of dates
    x          - sequence of dates
optional arguements:    
    lineStyle  - line style
    color      - color of the line
                 (lineStyle+colorchar --fmt)
    tz         - timezone
    xdate      - is True, the x-axis will be labeled with dates
    ydate      - is True, the y-axis will be labeled with dates  
Output:
    plot       Matplotlib Axes object
    line:   - line
pytz is required.
checks for pytz module and returns if not
"""   
    def __init__(self, name='PlotDate', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        self.styles=get_styles()
        self.colors=colors        
        self.joinstyles = getattr(Line2D, 'validJoin', ('miter', 'round', 'bevel'))
        timezones=common_timezones
        self.capstyles = getattr(Line2D, 'validCap', ('butt', 'round', 'projecting')) 
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string', required=False, name='lineStyle', defaultValue='solid')
        ip.append(datatype='None', required=False, name='color', defaultValue='black')
        ip.append(datatype='string', required=False, name='tz', defaultValue='US/PACIFIC')
        ip.append(datatype='boolean', required=False, name='xdate', defaultValue=True)
        ip.append(datatype='boolean', required=False, name='ydate', defaultValue=False)
        ip.append(datatype='boolean', required=False, name='line_antialiased', defaultValue=1)
        ip.append(datatype='float', required=False, name='line_linewidth', defaultValue=1)
        ip.append(datatype='string', required=False, name='solid_joinstyle', defaultValue='miter')
        ip.append(datatype='string', required=False, name='solid_capstyle', defaultValue='projecting')
        ip.append(datatype='string', required=False, name='dash_capstyle', defaultValue='butt')
        ip.append(datatype='string', required=False, name='dash_joinstyle', defaultValue='miter')
        ip.append(datatype='MPLDrawArea', required=False,name='drawAreaDef',singleConnection=False)
        
        self.widgetDescr['lineStyle'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.styles.keys()),
            'fixedChoices':True,
            'initialValue':'circle',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'line style:'}}

        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.colors.keys()),
            'fixedChoices':True,
            'initialValue':'blue',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'color:'}}
            
        self.widgetDescr['tz'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':timezones,
            'fixedChoices':True,
            'initialValue':'US/PACIFIC',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'timezone:'}}
            
        self.widgetDescr['xdate'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'xdate:'},
            'initialValue':1,}
        
        self.widgetDescr['ydate'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'ydate:'},
            'initialValue':0,}
            
        self.widgetDescr['dash_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'butt',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash_capstyle:'}}
        self.widgetDescr['dash_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash _joinstyle:'}}
        self.widgetDescr['solid_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'projecting',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_capstyle:'}}
        self.widgetDescr['solid_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_joinstyle:'}}
        self.widgetDescr['line_linewidth'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'int',
            'wheelPad':2, 'initialValue':1,
            'labelCfg':{'text':'linewidth'} }
        
        self.widgetDescr['line_antialiased'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'antialiased:'},
            'initialValue':1,}        
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        
        code = """def doit(self, y, x, lineStyle, color, tz, xdate, ydate,
line_antialiased, line_linewidth, solid_joinstyle, solid_capstyle, dash_capstyle,
dash_joinstyle, drawAreaDef):
    try:
       from pytz import common_timezones
    except:
       print("Could not import pytz ")
       return
    self.axes.clear() 
    self.setDrawAreaDef(drawAreaDef)
    colorChar = self.colors[color]
    lineStyleChar = self.styles[lineStyle]
    rcParams['timezone'] = tz
    tz=timezone(tz)
    fmt= colorChar+lineStyleChar
    l = self.axes.plot_date(x, y, fmt=colorChar+lineStyleChar, tz=tz, xdate= xdate,ydate= ydate)
    #line properties 
    if  self.axes.lines:
        for l in self.axes.lines:
            l.set_linewidth(line_linewidth)
            l.set_antialiased(line_antialiased)
            l.set_solid_joinstyle(solid_joinstyle)
            l.set_solid_capstyle(solid_capstyle)
            l.set_dash_capstyle(dash_capstyle)
            l.set_dash_joinstyle(dash_joinstyle)
            
    self.canvas.draw()
    self.outputData(plot=self.axes)
"""
        self.setFunction(code)

class PieNE(MPLPlottingNode):
    """plots a pie diagram for a list of numbers.  The size of each wedge
will be the fraction x/sumnumbers).

Input:
    fractions - sequence of values
    labels    - None; sequence of labels (has to match length of factions
    explode   - None; float or sequence of values which specifies the
                fraction of the radius to offset that wedge.
                if a single float is given the list is generated automatically
    shadow    - True; if True, will draw a shadow beneath the pie.
    format    - None; fromat string used to label the wedges with their
                numeric value
Output:
    plot      - Matplotlib Axes object
    patches   - sequence of matplotlib.patches.Wedge
    texts     - list of the label Text instances
    autotextsline - list of text instances for the numeric labels (only if
                    format is not None
"""
    
    def __init__(self, name='Pie', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='list', name='fractions',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', required=False, name='labels')
        ip.append(datatype='None', required=False, name='explode')
        ip.append(datatype='boolean', required=False, name='shadow')
        ip.append(datatype='string', required=False, name='format')
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)

        self.widgetDescr['explode'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':10, 'type':'float', 
            'initialValue':0.05, 'wheelPad':2,
            'labelCfg':{'text':'explode'} }

        self.widgetDescr['shadow'] = {
            'class':'NECheckButton', 'master':'node',
            'initialValue':1, 'labelCfg':{'text':'shadow'}}

        self.widgetDescr['format'] = {
            'class':'NEEntry', 'master':'node',
            'labelCfg':{'text':'format:'},
            'initialValue':'%1.1f%%'}
        
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        op.append(datatype='None', name='patches')
        op.append(datatype='None', name='texts')
        op.append(datatype='None', name='autotextsline')
        
        code = """def doit(self, fractions, labels, shadow, explode, format,
drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    if isinstance(explode, float) or isinstance(explode, int):
        explode = [explode]*len(fractions)
    res = self.axes.pie(fractions, explode=explode, labels=labels,
                  autopct=format, shadow=shadow)
    if format is None:
        patches, texts = res
        autotextsline = None
    else:
        patches, texts, autotextsline = res
    self.canvas.draw()

    self.outputData(plot=self.axes, patches=patches, texts=texts, autotextsline=autotextsline)
"""
        self.setFunction(code)
        
#Spy Nodes

class SpyNE(MPLPlottingNode):
    """Plots the sparsity pattern of the matrix Z using plot markers.
input:
    Z - matrix
optional arguements:
    marker - marker
    markersize -markersize    
    The line handles are returned
"""

    def __init__(self, name='Spy', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None',name = 'Z',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string', required=False, name='marker', defaultValue='s')
        ip.append(datatype='None', required=False, name='markersize', defaultValue=10)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['marker'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(markers.values()),
            'fixedChoices':True,
            'initialValue':'s',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'markers:'}}
        self.widgetDescr['markersize'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':10, 'type':'float', 
            'initialValue':10.0, 'wheelPad':2,
            'labelCfg':{'text':'size'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        code = """def doit(self, Z, marker, markersize, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    l=self.axes.spy(Z,marker=marker,markersize=markersize)
    self.canvas.draw()    
    self.outputData(plot=self.axes)
"""
        self.setFunction(code)

class Spy2NE(MPLPlottingNode):
    """SPY2 plots the sparsity pattern of the matrix Z as an image
input:
    Z - matrix
The image instance is returned
"""
    def __init__(self, name='Spy2', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None',name = 'Z',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        op.append(datatype='None', name='image')
        code = """def doit(self, Z, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    im=self.axes.spy2(Z)
    self.canvas.draw()
    self.outputData(plot=self.axes,image=im)
"""
        self.setFunction(code)
        
class VlineNE(MPLPlottingNode):
    """Plots vertical lines at each x from ymin to ymax.  ymin or ymax can be
scalars or len(x) numpy arrays.  If they are scalars, then the
respective values are constant, else the heights of the lines are
determined by ymin and ymax
x - array
ymin or ymax can be scalars or len(x) numpy arrays
color+marker - fmt is a plot format string, eg 'g--'
Returns a list of lines that were added
"""    
    def __init__(self, name='Vline', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list',name = 'x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',name = 'ymin',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list',name = 'ymax',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string', required=False, name='color', defaultValue='k')
        ip.append(datatype='string', required=False, name='linestyle', defaultValue='-')
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(colors.values()),
            'fixedChoices':True,
            'initialValue':'k',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'color:'}}
        
        self.widgetDescr['linestyle'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':['solid','dashed','dashdot','dotted'],
            'fixedChoices':True,
            'initialValue':'solid',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'linestyle:'}}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        op.append(datatype='None', name='lines')
        code = """def doit(self, x, ymin, ymax, color, linestyle, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    lines=self.axes.vlines(x, ymin, ymax, color=color, linestyle=linestyle )
    self.canvas.draw()
    self.outputData(plot=self.axes,lines=lines)
"""
        self.setFunction(code) 

            
#Scatter Nodes
from math import fabs

class ScatterNE(MPLPlottingNode):
    """plots a scatter diagram for two lists of numbers.

Input:
    x         - sequence of values
    y         - sequence of values
    s         - None; sequence of values for size in area
    c         - None, string or sequence of colors
    marker    - 'circle', marker

Output:
    plot       Matplotlib Axes object
    patches   - matplotlib.collections.RegularPolyCollection instance
"""
    def getPointInBin(self, data, sortind, x, eps):
        #dichotomous search for indices of values in data within x+-eps
        if len(sortind)>2:
            if data[sortind[0]]==x: return data, [sortind[0]]
            elif data[sortind[-1]]==x: return data, [sortind[-1]]
            elif len(sortind)==2: return data, sortind
            else:
                mid = len(sortind)/2
                if fabs(data[sortind[mid]]-x)<eps:
                    if fabs(data[sortind[0]]-x)<eps:
                        return data, sortind[:mid]
                    elif fabs(data[sortind[-1]]-x)<eps:
                        return data, sortind[mid:]

                if data[sortind[mid]]>x:
                    data, sortind = self.getPointInBin(data, sortind[:mid],
                                                       x, eps)
                elif data[sortind[mid]]<x:
                    data, sortind = self.getPointInBin(data, sortind[mid:],
                                                       x, eps)
        return data, sortind


    def on_click(self, event):
        # get the x and y pixel coords
        if event.inaxes:
            d1 = self.inputPorts[0].getData()
            d2 = self.inputPorts[1].getData()

            mini = min(d1)
            maxi = max(d1)
            epsx = (maxi-mini)/200.
            import numpy
            d1s = numpy.argsort(d1, 0)
            
            x, y = event.xdata, event.ydata
            dum, v1 = self.getPointInBin(d1, d1s, x, epsx)
            mini = min(d2)
            maxi = max(d2)
            epsy = (maxi-mini)/200.
            result = []
            for v in v1:
                if fabs(x - d1[v])<epsx and fabs(y - d2[v])<epsy:
                    result.append(v)
                #print v,  x - d1[v], epsx, y - d2[v], epsy

            if len(result):
                print('point:', result, x, d1[result[0]], y, d2[result[0]])
                self.outputData(pick=result)
                self.scheduleChildren([self.outputPorts[2]])
                return result
            else:
                print("NO POINT")
                return None


    def afterAddingToNetwork(self):
        MPLPlottingNode.afterAddingToNetwork(self)
        self.figure.canvas.mpl_connect('button_press_event', self.on_click)


    def __init__(self, name='Scatter', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)

        self.cutoff = 10.0
        self.joinstyles = getattr(Line2D, 'validJoin', ('miter', 'round', 'bevel'))
        self.capstyles = getattr(Line2D, 'validCap', ('butt', 'round', 'projecting'))
        self.colors = colors
        self.markers = markers 
        self.widgetDescr['s'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':10, 'type':'float', 
            'initialValue':1.0, 'wheelPad':2,
            'labelCfg':{'text':'size'} }

        self.widgetDescr['c'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.colors.values()),
            'fixedChoices':True,
            'initialValue':'k',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'color:'}}
        

        self.widgetDescr['marker'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.markers.keys()),
            'fixedChoices':True,
            'initialValue':'circle',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'markers:'}}
         
        self.widgetDescr['dash_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'butt',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash_capstyle:'}}

        self.widgetDescr['dash_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash _joinstyle:'}}

        self.widgetDescr['solid_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'projecting',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_capstyle:'}}

        self.widgetDescr['solid_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_joinstyle:'}}
        
        self.widgetDescr['linewidth'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'int',
            'wheelPad':2, 'initialValue':1,
            'labelCfg':{'text':'linewidth'} }
               
        self.widgetDescr['line_antialiased'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'antialiased:'},
            'initialValue':1,}
        
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None', required=False, name='s')
        ip.append(datatype='None', required=False, name='c', defaultValue='k')
        ip.append(datatype='string', required=False, name='marker', defaultValue='circle')
        ip.append(datatype='string', required=False, name='solid_joinstyle', defaultValue='miter')
        ip.append(datatype='string', required=False, name='solid_capstyle', defaultValue='projecting')
        ip.append(datatype='string', required=False, name='dash_capstyle', defaultValue='butt')
        ip.append(datatype='string', required=False, name='dash_joinstyle', defaultValue='miter')
        ip.append(datatype='MPLDrawArea', required=False,name='drawAreaDef',singleConnection=False) 
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        op.append(datatype='None', name='patches')
        op.append(datatype='int', name='pick')
        
        code = """def doit(self, x, y, s, c, marker, solid_joinstyle,
solid_capstyle, dash_capstyle, dash_joinstyle, drawAreaDef):
    kw={'solid_joinstyle':solid_joinstyle,'solid_capstyle':solid_capstyle,'dash_capstyle':dash_capstyle,'dash_joinstyle':dash_joinstyle}
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    if marker in self.markers:
        marker = self.markers[marker]
    res = self.axes.scatter( x, y, s, c, marker)
    #collections properties
    if  self.axes.lines:
        for c in self.axes.collections:
            c.set_solid_joinstyle(solid_joinstyle)
            c.set_solid_capstyle(solid_capstyle)
            c.set_dash_capstyle(dash_capstyle)
            c.set_dash_joinstyle(dash_joinstyle)
    self.canvas.draw()
    self.outputData(plot=self.axes, patches=res)
"""
        self.setFunction(code)


class ScatterClassicNE(MPLPlottingNode):
    """plots a scatter diagram for two lists of numbers.

Input:
    x         - sequence of values
    y         - sequence of values
    s         - None; sequence of values for size in area
    c         - None, string or sequence of colors
    
Output:
    plot       Matplotlib Axes object
    patches   - matplotlib.collections.RegularPolyCollection instance
"""
    
    def __init__(self, name='ScatterClassic', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        
        self.joinstyles = getattr(Line2D, 'validJoin', ('miter', 'round', 'bevel'))
        self.capstyles = getattr(Line2D, 'validCap', ('butt', 'round', 'projecting'))
        self.colors=colors
        self.markers =markers 
        self.widgetDescr['s'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':10, 'type':'float', 
            'initialValue':1.0, 'wheelPad':2,
            'labelCfg':{'text':'size'} }

        self.widgetDescr['c'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':list(self.colors.values()),
            'fixedChoices':True,
            'initialValue':'k',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'color:'}}
        

        self.widgetDescr['dash_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'butt',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash_capstyle:'}}
        self.widgetDescr['dash_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'dash _joinstyle:'}}
        self.widgetDescr['solid_capstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.capstyles,
            'fixedChoices':True,
            'initialValue':'projecting',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_capstyle:'}}
        self.widgetDescr['solid_joinstyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':self.joinstyles,
            'fixedChoices':True,
            'initialValue':'miter',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'solid_joinstyle:'}}
        
        self.widgetDescr['linewidth'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':60, 'height':21, 'oneTurn':2, 'type':'int',
            'wheelPad':2, 'initialValue':1,
            'labelCfg':{'text':'linewidth'} }
               
        self.widgetDescr['line_antialiased'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'antialiased:'},
            'initialValue':1,}
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None', required=False, name='s')
        ip.append(datatype='None', required=False, name='c')
        ip.append(datatype='string', required=False, name='solid_joinstyle', defaultValue='miter')
        ip.append(datatype='string', required=False, name='solid_capstyle', defaultValue='projecting')
        ip.append(datatype='string', required=False, name='dash_capstyle', defaultValue='butt')
        ip.append(datatype='string', required=False, name='dash_joinstyle', defaultValue='miter')
        ip.append(datatype='MPLDrawArea', required=False,name='drawAreaDef',singleConnection=False) 
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        op.append(datatype='None', name='patches')
        code = """def doit(self, x, y, s, c, solid_joinstyle, solid_capstyle,
dash_capstyle, dash_joinstyle, drawAreaDef):
    kw={'solid_joinstyle':solid_joinstyle,'solid_capstyle':solid_capstyle,'dash_capstyle':dash_capstyle,'dash_joinstyle':dash_joinstyle}
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    res = self.axes.scatter_classic( x, y, s, c)
    #collections properties
    if  self.axes.lines:
        for c in self.axes.collections:
            c.set_solid_joinstyle(solid_joinstyle)
            c.set_solid_capstyle(solid_capstyle)
            c.set_dash_capstyle(dash_capstyle)
            c.set_dash_joinstyle(dash_joinstyle)
    self.canvas.draw()
    self.outputData(plot=self.axes, patches=res)
"""
        self.setFunction(code)
        
class FigImageNE(MPLPlottingNode):
    """plots an image from a 2d array fo data

Input:
    data        - 2D array of data

Output:
    plot       Matplotlib Axes object
    image     - image.FigureImage instance 
"""
    
    def __init__(self, name='Figimage', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None', name='data',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string',required=False, name='cmap', defaultValue='jet')
        ip.append(datatype='string',required=False, name='imaspect', defaultValue='equal')
        ip.append(datatype='string',required=False, name='interpolation', defaultValue='bilinear')
        ip.append(datatype='string',required=False, name='origin', defaultValue='upper')
        ip.append(datatype='None', required=False, name='alpha', defaultValue=1.)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        imaspects=['auto', 'equal']
        interpolations =['nearest', 'bilinear', 'bicubic', 'spline16', 'spline36', 'hanning', 'hamming', 'hermite', 'kaiser', 'quadric','catrom', 'gaussian', 'bessel', 'mitchell', 'sinc','lanczos', 'blackman']
        self.widgetDescr['cmap'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':cmaps,
            'fixedChoices':True,
            'initialValue':'jet',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'cmap:'}}
        self.widgetDescr['imaspect'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':imaspects,
            'fixedChoices':True,
            'initialValue':'equal',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'aspect:'}}  
        self.widgetDescr['interpolation'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':interpolations,
            'fixedChoices':True,
            'initialValue':'bilinear',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'interpolation:'}}
        self.widgetDescr['origin'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['upper','lower',],
            'fixedChoices':True,
            'initialValue':'upper',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'origin:'}}
        self.widgetDescr['alpha'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':1, 'type':'float', 
            'initialValue':1.0, 'wheelPad':2, 
            'labelCfg':{'text':'alpha'} }
            
            
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='plot')
        op.append(datatype='None', name='image')
        
        code = """def doit(self, data, cmap, imaspect, interpolation, origin,
alpha, drawAreaDef):
    kw={'cmap':cmap,'imaspect':imaspect,'interpolation':interpolation,'origin':origin,'alpha':alpha}
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    self.setDrawArea(kw)
    im = self.axes.imshow(data)
    #image properties
    cmp=_get_cmap(cmap)
    im.set_cmap(cmp)
    im.set_interpolation(interpolation)
    im.set_alpha(alpha)
    im.origin=origin
    self.axes.set_aspect(imaspect)
    self.canvas.draw()
    self.outputData(plot=self.axes, image=im)
"""
        self.setFunction(code)


#PSEUDO COLOR PLOTS

class PcolorMeshNE(MPLPlottingNode):
    """This class is for making a pseudocolor plot.
input: 
    arraylistx      - array
    arraylisty      - array
    arraylistz      - may be a masked array
optional arguements:
    cmap    - cm.jet : a cm Colormap instance from matplotlib.cm.
            defaults to cm.jet
    shading - 'flat' : or 'faceted'.  If 'faceted', a black grid is
            drawn around each rectangle; if 'flat', edge colors are same as
            face colors
    alpha   - blending value
    PCOLORMESH(Z) - make a pseudocolor plot of matrix Z
    PCOLORMESH(X, Y, Z) - a pseudo color plot of Z on the matrices X and Y
    Return value is a matplotlib.collections.PatchCollection
        object
"""
    def __init__(self, name='PcolorMesh', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)   
        ip = self.inputPortsDescr
        ip.append(datatype='None', required=False,name='arraylistx')
        ip.append(datatype='None', required=False,name='arraylisty')
        ip.append(datatype='None', name='arraylistz',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string',required=False,  name='cmap', defaultValue='jet')
        ip.append(datatype='string',required=False,  name='shading', defaultValue='faceted')
        ip.append(datatype='float',required=False,  name='alpha', defaultValue=1.)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['cmap'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':cmaps,
            'fixedChoices':True,
            'initialValue':'jet',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'cmap:'}}
        self.widgetDescr['shading'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['flat','faceted'],
            'fixedChoices':True,
            'initialValue':'faceted',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'shading:'}}
        self.widgetDescr['alpha'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float', 
            'initialValue':1.0, 'wheelPad':2, 
            'labelCfg':{'text':'alpha'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype='None', name='patches')
        
        code = """def doit(self, x, y, z, cmap, shading, alpha, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    #pseudo color plot of Z
    Qz=z
    cmap = _get_cmap(cmap)
    if x is None or y is None:
        C=self.axes.pcolormesh(Qz,cmap=cmap,shading=shading,alpha=alpha)
    else:
        #a pseudo color plot of Z on the matrices X and Y
        Qx,Qy=array(x),array(y)
        C=self.axes.pcolormesh(Qx,Qy,Qz,cmap=cmap,shading=shading,alpha=alpha)
    
    self.canvas.draw()
    self.outputData(axes=self.axes,patches=C)
"""
        self.setFunction(code)

class PcolorNE(MPLPlottingNode):
    """This class is for making a pseudocolor plot.
input: 
    arraylistx      - may be a array
    arraylisty      - may be a array
    arraylistz      - may be a masked array
optional arguements:
    cmap    - cm.jet : a cm Colormap instance from matplotlib.cm.
            defaults to cm.jet
    shading - 'flat' : or 'faceted'.  If 'faceted', a black grid is
            drawn around each rectangle; if 'flat', edge colors are same as
            face colors
    alpha   - blending value
    PCOLOR(Z) - make a pseudocolor plot of matrix Z
    PCOLOR(X, Y, Z) - a pseudo color plot of Z on the matrices X and Y
    Return value is a matplotlib.collections.PatchCollection
        object
"""
    def __init__(self, name='Pcolor', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)   
        ip = self.inputPortsDescr
        ip.append(datatype='None', required=False,name='arraylistx')
        ip.append(datatype='None', required=False,name='arraylisty')
        ip.append(datatype='None', name='arraylistz',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string',required=False,  name='cmap', defaultValue='jet')
        ip.append(datatype='string',required=False,  name='shading', defaultValue='faceted')
        ip.append(datatype='float',required=False,  name='alpha', defaultValue=1.)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['cmap'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':cmaps,
            'fixedChoices':True,
            'initialValue':'jet',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'cmap:'}}
        self.widgetDescr['shading'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['flat','faceted'],
            'fixedChoices':True,
            'initialValue':'faceted',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'shading:'}}
        self.widgetDescr['alpha'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float', 
            'initialValue':1.0, 'wheelPad':2, 
            'labelCfg':{'text':'alpha'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype='None', name='patches')
        
        code = """def doit(self, x, y, z, cmap, shading, alpha, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    #pseudo color plot of Z
    Qz=z
    cmap = _get_cmap(cmap)
    if x is None or y is None:
        C=self.axes.pcolor(Qz,cmap=cmap,shading=shading,alpha=alpha)
    else:
        #a pseudo color plot of Z on the matrices X and Y
        Qx,Qy=array(x),array(y)
        C=self.axes.pcolor(Qx,Qy,Qz,cmap=cmap,shading=shading,alpha=alpha)
    
    self.canvas.draw()
    self.outputData(axes=self.axes,patches=C)
"""
        self.setFunction(code)
        
class PcolorClassicNE(MPLPlottingNode):
    """This class is for making a pseudocolor plot.
input: 
    arraylistx      - array
    arraylisty      - array
    arraylistz      - may be a masked array
optional arguements:
    cmap    - cm.jet : a cm Colormap instance from matplotlib.cm.
            defaults to cm.jet
    shading - 'flat' : or 'faceted'.  If 'faceted', a black grid is
            drawn around each rectangle; if 'flat', edge colors are same as
            face colors
    alpha   - blending value
    PCOLOR_CLASSIC(Z) - make a pseudocolor plot of matrix Z
    PCOLOR_CLASSIC(X, Y, Z) - a pseudo color plot of Z on the matrices X and Y
    Return value is a matplotlib.collections.PatchCollection
        object
"""
    def __init__(self, name='PcolorClassic', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)   
        ip = self.inputPortsDescr
        ip.append(datatype='None', required=False,name='arraylistx')
        ip.append(datatype='None', required=False,name='arraylisty')
        ip.append(datatype='None', name='arraylistz',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string',required=False,  name='cmap', defaultValue='jet')
        ip.append(datatype='string',required=False,  name='shading', defaultValue='faceted')
        ip.append(datatype='float',required=False,  name='alpha', defaultValue=.75)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['cmap'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':cmaps,
            'fixedChoices':True,
            'initialValue':'jet',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'cmap:'}}
        self.widgetDescr['shading'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['flat','faceted'],
            'fixedChoices':True,
            'initialValue':'faceted',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'shading:'}}
        self.widgetDescr['alpha'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float', 
            'initialValue':0.75, 'wheelPad':2, 
            'labelCfg':{'text':'alpha'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype='None', name='patches')
        
        code = """def doit(self, x, y, z, cmap, shading, alpha, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    #pseudo color plot of Z
    Qz=z
    cmap = _get_cmap(cmap)
    if x is None or y is None:
        C=self.axes.pcolor_classic(Qz,cmap=cmap,shading=shading,alpha=alpha)
    else:
        #a pseudo color plot of Z on the matrices X and Y
        Qx,Qy=array(x),array(y)
        C=self.axes.pcolor_classic(Qx,Qy,Qz,cmap=cmap,shading=shading,alpha=alpha)
    
    self.canvas.draw()
    self.outputData(axes=self.axes,patches=C)
"""
        self.setFunction(code)
        
class ContourNE(MPLPlottingNode):
    """contour and contourf draw contour lines and filled contours.
input:
    arraylistx      :array 
    arraylisty      :array
    arraylistz      :array
optional arguements:
    length_colors   : no of colors required to color contour
    cmap            :a cm Colormap instance from matplotlib.cm.
    origin          :'upper'|'lower'|'image'|None.
    linewidth       :linewidth
    hold:
    contour(Z) make a contour plot of n arrayZ
    contour(X,Y,Z) X,Y specify the (x,y) coordinates of the surface
    
"""
    
    def __init__(self, name='Contour', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None', required=False, name='arraylistx')
        ip.append(datatype='None', required=False,name='arraylisty')
        ip.append(datatype='None', name='arraylistz',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string', required=False,  name='contour', defaultValue='default')
        ip.append(datatype='int', required=False, name='length_colors')
        ip.append(datatype='string', required=False, name='cmap', defaultValue='jet')
        ip.append(datatype='string', required=False, name='colors', defaultValue='black')
        ip.append(datatype='string', required=False, name='origin', defaultValue='upper')
        ip.append(datatype='int', required=False, name='linewidth', defaultValue=1)
        ip.append(datatype='boolean', required=False, name='hold', defaultValue=0)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['contour'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':['default','filledcontour'],
            'fixedChoices':True,
            'initialValue':'default',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'contour:'}}
        self.widgetDescr['length_colors'] = {
            'class':'NEEntry', 'master':'node',
            'labelCfg':{'text':'no. of colors:'},
            'initialValue':10}
        self.widgetDescr['cmap'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':cmaps,
            'fixedChoices':True,
            'initialValue':'jet',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'cmap:'}}
        self.widgetDescr['colors'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'black',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'colors:'}}
        self.widgetDescr['linewidth'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':4, 'type':'int', 
                'initialValue':1, 'wheelPad':2,
            'labelCfg':{'text':'linewidth'} }    
        self.widgetDescr['origin'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['upper','lower','image',None],
            'fixedChoices':True,
            'initialValue':'upper',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'origin:'}}
        
        self.widgetDescr['hold'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'hold'},
            'initialValue':0,}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype='None', name='contour')
        code = """def doit(self, arraylistx, arraylisty, arraylistz, contour,
length_colors, cmapval, colors, origin, linewidth, hold, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)            
    axes_list=self.axes.figure.axes
    if len(axes_list):
        for i in axes_list:
          if not isinstance(i,Subplot):
            self.axes.figure.delaxes(i)
    import numpy
    #Z=10.0*(numpy.array(z2) - numpy.array(z1))
    Z=arraylistz
    if length_colors:
        cmap = _get_cmap(cmapval,int(length_colors))
    else:
        cmap=eval("cm.%s" %cmapval)
    if arraylistx is None or arraylisty is None:
        #contour plot of an array Z
        if contour=='default':    
            CS=self.axes.contour(Z,cmap=cmap,linewidths=linewidth,origin=origin,**_hold_kw(hold))
            self.axes.clabel(CS,inline=1)
        else:
            CS=self.axes.contourf(numpy.array(Z),cmap=cmap,origin=origin)
    else:
        #(x,y) coordinates of the surface
        X=numpy.array(arraylistx)
        Y=numpy.array(arraylisty)
        if contour=='default':
            CS=self.axes.contour(X,Y,Z,cmap=cmap,linewidths=linewidth,origin=origin,**_hold_kw(hold)) 
            self.axes.clabel(CS,inline=1)    
        else:
            CS=self.axes.contourf(X,Y,numpy.array(Z),cmap=cmap,origin=origin)
    self.canvas.draw()
    self.outputData(axes=self.axes,contour=CS)
"""
        self.setFunction(code)
        
class SpecgramNE(MPLPlottingNode):
    """plots a spectrogram of data in arraylistx.
NFFT    -   Data are split into NFFT length segements 
Fs      -   samplingFrequency
cmap    -   colormap
nOverlap-   the amount of overlap of each segment.
Returns  im
im is a matplotlib.image.AxesImage    
""" 
    def __init__(self, name='Specgram', **kw):
       
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='arraylistx',singleConnection='auto',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='int', name='NFFT', defaultValue=256)
        ip.append(datatype='int', name='Fs', defaultValue=2)
        ip.append(datatype='string', required=False, name='cmap')
        ip.append(datatype='int', name='nOverlap', defaultValue=128)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['NFFT'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'NFFT (powOf 2):'},'width':10,
            'type':'int',
            'initialValue':256}
            
        self.widgetDescr['Fs'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':2,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'Fs'} }
        self.widgetDescr['cmap'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':cmaps,
            'fixedChoices':True,
            'initialValue':'jet',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'cmap:'}}
        self.widgetDescr['nOverlap'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'nOverlap:'},'width':10,
            'type':'int','labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'initialValue':0}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype=None,name='image')
        code="""def doit(self, x, NFFT, Fs, cmapval, nOverlap, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    cmap=eval("cm.%s" %cmapval)
    Pxx, freqs, bins, im=self.axes.specgram(x, NFFT=int(NFFT), Fs=Fs,cmap=cmap,noverlap=int(nOverlap))
    self.canvas.draw()
    self.outputData(axes=self.axes,image=im)
"""
        self.setFunction(code)

class CSDNE(MPLPlottingNode):
    """plots a cross spectral density of data in arraylistx,arraylisty.
NFFT    -   Data are split into NFFT length segements 
Fs      -   samplingFrequency
nOverlap-   the amount of overlap of each segment.
"""
    def __init__(self, name='CSD', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype=None, name='arraylistx',singleConnection='auto',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype=None, name='arraylisty',singleConnection='auto',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='int', name='NFFT', defaultValue=256)
        ip.append(datatype='int', name='Fs', defaultValue=2)
        ip.append(datatype='int', name='nOverlap', defaultValue=128)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['NFFT'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'NFFT (powOf 2):'},'width':10,
            'type':'int',
            'initialValue':256}
            
        self.widgetDescr['Fs'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':2,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'Fs'} }
        
        self.widgetDescr['nOverlap'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'nOverlap:'},'width':10,
            'type':'int','labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'initialValue':0}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        code="""def doit(self, arraylistx, arraylisty, NFFT, Fs, nOverlap,
drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    Pxx, freqs=self.axes.csd(arraylistx,arraylisty, NFFT=int(NFFT), Fs=Fs,noverlap=int(nOverlap))
    self.canvas.draw()
    self.outputData(axes=self.axes)
"""
        self.setFunction(code)
       
class PSDNE(MPLPlottingNode):
    """plots a cross spectral density of data in arraylistx.
NFFT    -   Data are split into NFFT length segements 
Fs      -   samplingFrequency
nOverlap-   the amount of overlap of each segment.
"""
    def __init__(self, name='PSD', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype=None, name='arraylistx',singleConnection='auto',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='int', required=False,name='NFFT', defaultValue=256)
        ip.append(datatype='int', required=False,name='Fs', defaultValue=2)
        ip.append(datatype='int', required=False,name='nOverlap', defaultValue=0)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['NFFT'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'NFFT (powOf 2):'},'width':10,
            'type':'int',
            'initialValue':256}
            
        self.widgetDescr['Fs'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':2,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'Fs'}}
        
        self.widgetDescr['nOverlap'] = {
            'class':'NEEntry', 'master':'ParamPanel',
            'labelCfg':{'text':'nOverlap:'},'width':10,
            'type':'int','labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'initialValue':0}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        code="""def doit(self, x, NFFT, Fs, nOverlap, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    self.axes.psd(x,NFFT=int(NFFT), Fs=Fs,noverlap=int(nOverlap))
    self.canvas.draw()
    self.outputData(axes=self.axes)
"""
        self.setFunction(code)
        
class LogCurveNE(MPLPlottingNode):
    """This node is to make a loglog plot with log scaling on the x and y axis.
input:
x      - list
y      - list
basex  - base of the x logarithm
basey  - base of the y logarithm
"""
       
    def __init__(self, name='LogCurve', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='string',required=False, name='logCurve', defaultValue='log')
        ip.append(datatype='float',required=False, name='basex', defaultValue=10)
        ip.append(datatype='float',required=False, name='basey', defaultValue=10)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['logCurve'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':['logbasex','logbasey'],
            'fixedChoices':True,
            'initialValue':'logbasex',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'logCurve:'}}
        self.widgetDescr['basex'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':10,
            'labelCfg':{'text':'basex'} }
        self.widgetDescr['basey'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':10,
            'labelCfg':{'text':'basey'} }    
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        code="""def doit(self, x, y, logCurve, basex, basey, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    if logCurve=="logbasex":
        log_curve=self.axes.loglog(x,y,base=basex)
    else:
        log_curve=self.axes.loglog( x,y,base=basey)
    
    self.canvas.draw()
    self.outputData(axes=self.axes)
"""
        self.setFunction(code)
        
class SemilogxNE(MPLPlottingNode):
    """This node is to make a semilog plot with log scaling on the xaxis.
input:
    x      - list
    basex  - base of the x logarithm
    """
       
    def __init__(self, name='Semilogx', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='float',required=False, name='basex', defaultValue=10)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['basex'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':10,
            'labelCfg':{'text':'basex'} }
            
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        code="""def doit(self, x, y, basex, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    self.axes.semilogx(x,y,base=basex)
    self.canvas.draw()
    self.outputData(axes=self.axes)
"""
        self.setFunction(code)
        
class SemilogyNE(MPLPlottingNode):
    """This node is to make a semilog plot with log scaling on the y axis.
input:
    y      - list
    basey  - base of the y logarithm
    """
       
    def __init__(self, name='Semilogy', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='x',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='float',required=False, name='basey', defaultValue=10)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['basey'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':10,
            'labelCfg':{'text':'basey'} }
            
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        code="""def doit(self, x, y, basey, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    self.axes.semilogy(x,y,base=basey)
    self.canvas.draw()
    self.outputData(axes=self.axes)
"""
        self.setFunction(code)

class BoxPlotNE(MPLPlottingNode):
    """ To plot a box and whisker plot for each column of x.
The box extends from the lower to upper quartile values
of the data, with a line at the median.  The whiskers
extend from the box to show the range of the data.  Flier
points are those past the end of the whiskers.
input:
        x       -       Numeric array
optional arguements:
        notch   -       notch = 0 (default) produces a rectangular box plot.
                        notch = 1 will produce a notched box plot
        sym     -       (default 'b+') is the default symbol for flier points.
                        Enter an empty string ('') if you dont want to show fliers.
        vert    -       vert = 1 (default) makes the boxes vertical.
                        vert = 0 makes horizontal boxes.  This seems goofy, but
                        thats how Matlab did it.
        whis    -       (default 1.5) defines the length of the whiskers as
                        a function of the inner quartile range.  They extend to the
                        most extreme data point within ( whis*(75%-25%) ) data range.
        positions-      (default 1,2,...,n) sets the horizontal positions of
                        the boxes. The ticks and limits are automatically set to match
                        the positions.
        widths    -     either a scalar or a vector and sets the width of
                        each box. The default is 0.5, or 0.15*(distance between extreme
                        positions) if that is smaller.
        
Returns a list of the lines added
"""
    def __init__(self, name='BoxPlot', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list', name='x',singleConnection='auto',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='list', required=False, name='positions')
        ip.append(datatype=None, required=False, name='widths', defaultValue=.15)
        ip.append(datatype='boolean', required=False, name='notch', defaultValue=0)
        ip.append(datatype='boolean', required=False, name='vert', defaultValue=0)
        ip.append(datatype='string', required=False, name='color', defaultValue='b')
        ip.append(datatype='string', required=False, name='linestyle', defaultValue='-')
        ip.append(datatype='float', required=False, name='whis', defaultValue=1.5)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['notch'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'notch:'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'initialValue':0,}
        self.widgetDescr['vert'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'vert:'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'initialValue':0,}
        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'color:'}}
        self.widgetDescr['linestyle'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(get_styles().values()),
            'fixedChoices':True,
            'initialValue':'-',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'linestyle:'}}
        self.widgetDescr['whis'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':1.5,'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'whis'} }    
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype=None, name='lines')
        code="""def doit(self, x, positions, widths, notch, vert, color, linestyle,
whis, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    sym=color+linestyle
    ll=self.axes.boxplot(x,notch=notch, sym=sym, vert=vert, whis=whis,positions=positions,widths=widths)
    self.canvas.draw()
    self.outputData(axes=self.axes,lines=ll) 
"""
        self.setFunction(code)


class BarNE(MPLPlottingNode):
    """Plots a horizontal bar plot with rectangles bounded by
left, left+width, bottom, bottom+height  (left, right, bottom and top edges)
bottom, width, height, and left can be either scalars or sequences
input:
     height      -   the heights (thicknesses) of the bars
    left        -   the x coordinates of the left edges of the bars
    
Optional arguments:
    bottom      -   can be either scalars or sequences
    width       -   can be either scalars or sequences
    color       -    specifies the colors of the bars
    edgecolor   -    specifies the colors of the bar edges
    xerr        -    if not None, will be used to generate errorbars
                    on the bar chart
    yerr        -    if not None, will be used to generate errorbars
                    on the bar chart
    ecolor      -   specifies the color of any errorbar
    capsize     -       determines the length in points of the error bar caps
    align       - 'edge' | 'center'
                  'edge' aligns the horizontal bars by their bottom edges in bottom, while
                  'center' interprets these values as the y coordinates of the bar centers.
Return value is a list of Rectangle patch instances
"""
    def __init__(self, name='Bar', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None',  name='left',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None',  name='height',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None', required=False,name='bottom', defaultValue=0)    
        ip.append(datatype='None', required=False,name='width', defaultValue=.8)
        ip.append(datatype='None', required=False, name='xerr')    
        ip.append(datatype='None', required=False, name='yerr')
        ip.append(datatype='string', required=False, name='color', defaultValue='b')
        ip.append(datatype='string', required=False, name='edgecolor', defaultValue='b')
        ip.append(datatype='string', required=False, name='ecolor', defaultValue='b')
        ip.append(datatype='int', required=False, name='capsize', defaultValue=3)
        ip.append(datatype='list', required=False, name='align', defaultValue='edge')
        ip.append(datatype='list', required=False, name='orientation', defaultValue='vertical')
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
            
        self.widgetDescr['align'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['edge','center'], 
            'fixedChoices':True,
            'initialValue':'edge',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'align:'}}
        self.widgetDescr['orientation'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['vertical','horizontal'], 
            'fixedChoices':True,
            'initialValue':'vertical',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'orientation:'}}
        self.widgetDescr['edgecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'edgecolor:'}}
        self.widgetDescr['ecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'ecolor:'}}
        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'color:'}}
        self.widgetDescr['capsize'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':3,'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'capsize'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype=None, name='patches')
        code="""def doit(self, left, height, bottom, width, xerr, yerr, color,
edgecolor, ecolor, capsize, align, orientation, drawAreaDef):        
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    patches=self.axes.bar(left,height,bottom=bottom, width=width, 
             color=color, edgecolor=edgecolor, xerr=xerr, yerr=yerr, ecolor=ecolor, capsize=capsize,
             align=align,orientation=orientation)        
    self.canvas.draw()
    self.outputData(axes=self.axes,patches=patches) 
"""
        self.setFunction(code)


class BarHNE(MPLPlottingNode):
    """Plots a horizontal bar plot with rectangles bounded by
left, left+width, bottom, bottom+height  (left, right, bottom and top edges)
bottom, width, height, and left can be either scalars or sequences
input:
    bottom      -   can be either scalars or sequences
    width       -   can be either scalars or sequences
Optional arguments:
    height      -   the heights (thicknesses) of the bars
    left        -   the x coordinates of the left edges of the bars
    color       -    specifies the colors of the bars
    edgecolor   -    specifies the colors of the bar edges
    xerr        -    if not None, will be used to generate errorbars
                    on the bar chart
    yerr        -    if not None, will be used to generate errorbars
                    on the bar chart
    ecolor      -   specifies the color of any errorbar
    capsize     -       determines the length in points of the error bar caps
    align       - 'edge' | 'center'
                  'edge' aligns the horizontal bars by their bottom edges in bottom, while
                  'center' interprets these values as the y coordinates of the bar centers.
Return value is a list of Rectangle patch instances
"""
    def __init__(self, name='BarH', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None', name='bottom',beforeDisconnect=self.codeBeforeDisconnect)    
        ip.append(datatype='None', name='width',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None', required=False, name='height', defaultValue=.8)
        ip.append(datatype='None', required=False, name='left', defaultValue=0)
        ip.append(datatype='None', required=False, name='xerr')    
        ip.append(datatype='None', required=False, name='yerr')
        ip.append(datatype='string', required=False, name='color', defaultValue='b')
        ip.append(datatype='string', required=False, name='edgecolor', defaultValue='b')
        ip.append(datatype='string', required=False, name='ecolor', defaultValue='b')
        ip.append(datatype='int', required=False, name='capsize', defaultValue=3)
        ip.append(datatype='list', required=False, name='align', defaultValue='edge')
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
            
        self.widgetDescr['align'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['edge','center'], 
            'fixedChoices':True,
            'initialValue':'edge',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'align:'}}
        self.widgetDescr['edgecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'edgecolor:'}}
        self.widgetDescr['ecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'ecolor:'}}
        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'color:'}}
        self.widgetDescr['capsize'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':3,'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'capsize'} }
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        op.append(datatype=None, name='patches')
        code="""def doit(self, bottom, width, height, left, xerr, yerr, color,
edgecolor, ecolor, capsize, align, drawAreaDef):        
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    patches=self.axes.barh(bottom, width, height=height, left=left,
             color=color, edgecolor=edgecolor, xerr=xerr, yerr=yerr, ecolor=ecolor, capsize=capsize,
             align=align)        
    self.canvas.draw()
    self.outputData(axes=self.axes,patches=patches) 
"""
        self.setFunction(code)

class QuiverNE(MPLPlottingNode):
    """Makes a vector plot (U, V) with arrows on a grid (X, Y) 
If X and Y are not specified, U and V must be 2D arrays.  Equally spaced
X and Y grids are then generated using the meshgrid command.
color  -color 
S      -used to scale the vectors.Use S=0 to disable automatic scaling.
        If S!=0, vectors are scaled to fit within the grid and then are multiplied by S.
pivot  -'mid','tip' etc
units  - 'inches','width','x','y'
width  - a scalar that controls the width of the arrows
"""
    def __init__(self, name='Quiver', **kw):
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        
        ip.append(datatype='None', name='u',beforeDisconnect=self.codeBeforeDisconnect)    
        ip.append(datatype='None', name='v',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None', required=False,name='x')    
        ip.append(datatype='None', required=False,name='y')
        ip.append(datatype='None', required=False, name='color')
        ip.append(datatype='float', required=False, name='S', defaultValue=.2)
        ip.append(datatype='float', required=False, name='width', defaultValue=1.)
        ip.append(datatype='string', required=False, name='pivot', defaultValue='tip')
        ip.append(datatype='string', required=False, name='units', defaultValue='inches')
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['color'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'color:'}}
        self.widgetDescr['S'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1,
            'type':'float','precision':3,
            'wheelPad':2, 'initialValue':0.20,'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'S'} }
        self.widgetDescr['width'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1,
            'type':'float','precision':3,
            'wheelPad':2, 'initialValue':0.002,'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'width'} }
        
        self.widgetDescr['pivot'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['tip','mid'], 
            'fixedChoices':True,
            'initialValue':'tip',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'pivot:'}}
        self.widgetDescr['units'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['inches','width','x','y'], 
            'fixedChoices':True,
            'initialValue':'width',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'units:'}}    
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')    
        code="""def doit(self, u, v, x, y, color, S, width, pivot, units, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    if x is not None:
        self.axes.quiver(x,y,u,v,S,pivot=pivot,color=color,width=width,units=units)
    else:
        self.axes.quiver(u,v,S,color=color,width=width,units=units)
    self.canvas.draw()
    self.outputData(axes=self.axes) 
"""
        self.setFunction(code)
    
        
class ErrorBarNE(MPLPlottingNode):
    """Plot x versus y with error deltas in yerr and xerr.
Vertical errorbars are plotted if yerr is not None
Horizontal errorbars are plotted if xerr is not None.
input:
    x       -       scalar or sequence of vectors
    y       -       scalar or sequence of vectors
    xerr    -       scalar or sequence of vectors, plots a single error bar at x, y.,default is None
    yerr    -       scalar or sequence of vectors, plots a single error bar at x, y.,default is None
    
optional arguements:
    controlmarkers - controls errorbar markers(with props: markerfacecolor, markeredgecolor, markersize and
                  markeredgewith)
    fmt      -   plot format symbol for y.  if fmt is None, just
                 plot the errorbars with no line symbols.  This can be useful
                 for creating a bar plot with errorbars
    ecolor   -   a matplotlib color arg which gives the color the
                 errorbar lines; if None, use the marker color.
    capsize  -   the size of the error bar caps in points
    barsabove-   if True, will plot the errorbars above the plot symbols
                 default is below
"""
    def __init__(self, name='ErrorBar', **kw):
        
        kw['name'] = name
        MPLPlottingNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None', name='x',beforeDisconnect=self.codeBeforeDisconnect)    
        ip.append(datatype='None', name='y',beforeDisconnect=self.codeBeforeDisconnect)
        ip.append(datatype='None', required=False, name='xerr')    
        ip.append(datatype='None', required=False, name='yerr')
        ip.append(datatype='string', required=False, name='format', defaultValue='b-')
        ip.append(datatype='string', required=False, name='ecolor', defaultValue='b')
        ip.append(datatype='int', required=False, name='capsize', defaultValue=3)
        ip.append(datatype='boolean', required=False, name='barsabove', defaultValue=0)
        ip.append(datatype='boolean', required=False, name='controlmarkers', defaultValue=0)
        ip.append(datatype='MPLDrawArea', required=False, name='drawAreaDef',singleConnection=False)
        self.widgetDescr['format'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(get_styles().values()),
            'fixedChoices':True,
            'initialValue':'-',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'format:'}}
        
        self.widgetDescr['ecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(colors.values()), 
            'fixedChoices':True,
            'initialValue':'b',          
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'ecolor:'}}
        self.widgetDescr['capsize'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':1, 'type':'float',
            'wheelPad':2, 'initialValue':3,'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'capsize'} }    
        self.widgetDescr['barsabove'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'labelCfg':{'text':'barsabove:'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'initialValue':0,}    
        self.widgetDescr['controlmarkers'] = {
            'class':'NECheckButton', 'master':'node',
            'labelCfg':{'text':'barsabove:'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'initialValue':0,}
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        code="""def doit(self, x, y, xerr, yerr, format, ecolor, capsize,
barsabove, controlmarkers, drawAreaDef):
    self.axes.clear()
    self.setDrawAreaDef(drawAreaDef)
    fmt=ecolor+format
    if controlmarkers == 0:
        self.axes.errorbar(x,y,xerr=xerr,yerr=yerr,fmt=fmt,ecolor=ecolor,capsize=capsize,barsabove=barsabove)
    else:
        def set_markerparams(dAD):
            if 'marker' in dAD:
                marker = dAD['marker']
            else:
                marker = 'solid'
            if 'markerfacecolor' in dAD:   
                markerfacecolor = dAD['markerfacecolor']
            else:
                markerfacecolor = 'blue'
            if 'markeredgecolor' in dAD: 
                markeredgecolor = dAD['markeredgecolor']
            else:
                markeredgecolor = 'blue'
            if 'markersize' in dAD:
                markersize = dAD['markersize']  
            else:
                markersize = 6
            if 'makeredgewidth' in dAD:
                makeredgewidth = dAD['makeredgewidth']
            else:
                makeredgewidth = 0.5
            return marker,markerfacecolor,markeredgecolor,markersize,makeredgewidth
        if drawAreaDef:
            markerdict={}
            if len(drawAreaDef) == 1 and type(drawAreaDef[0])==dict:
                for d in list(drawAreaDef[0].keys()):
                    if d[:6]=="marker":
                        markerdict[d]=drawAreaDef[0][d]
            if len(drawAreaDef)>1:
                for dAD in drawAreaDef:
                    if type(dAD) == dict:
                        for d in list(dAD.keys()):
                            if d[:6]=="marker":
                                markerdict[d]=dAD[d]
                
        if markerdict!={}:          
            marker,markerfacecolor,markeredgecolor,markersize,makeredgewidth=set_markerparams(markerdict)
            self.axes.errorbar(x, y, xerr=xerr,yerr=yerr, marker=marker,
                           mfc=markerfacecolor, mec=markeredgecolor, ms=markersize, mew=makeredgewidth)
    self.canvas.draw()
    self.outputData(axes=self.axes) 
"""
        self.setFunction(code)
        
        
        
###########################################################################
#
# Nodes generating data for demos
#
###########################################################################

class RandNormDist(NetworkNode):
    """
Outputs values describing a randomized normal distribution

Input:
    mu    - 
    sigma - 
    dpi   - number of value points

Output:
    data:  list of values
    mu    - 
    sigma - 
"""
    def __init__(self, name='RandNormDist', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='float', name='mu')
        ip.append(datatype='float', name='sigma')
        ip.append(datatype='int', name='npts')
   
        self.widgetDescr['mu'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':2, 'type':'float',
            'wheelPad':2, 'initialValue':100,
            'labelCfg':{'text':'mu'} }

        self.widgetDescr['sigma'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':2, 'type':'float',
            'wheelPad':2, 'initialValue':15,
            'labelCfg':{'text':'sigma'} }

        self.widgetDescr['npts'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':1000, 'type':'int',
            'wheelPad':2, 'initialValue':10000,
            'labelCfg':{'text':'nb. points'} }

        op = self.outputPortsDescr
        op.append(datatype='list', name='data')
        op.append(datatype='float', name='mu')
        op.append(datatype='float', name='sigma')

        code = """def doit(self, mu, sigma, npts):
    from numpy.random import randn
    self.outputData( data=mu+sigma*randn(npts), mu=mu, sigma=sigma )
"""
        self.setFunction(code)



class SinFunc(NetworkNode):
    """
Outputs values describing a sinusoidal function.

Input:
    start  -  first x value 
    end    -  last x value
    step   -  step size

Output:
    x:  list x values
    y = list of y values
"""
    def __init__(self, name='SinFunc', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='float', name='x0')
        ip.append(datatype='float', name='x1')
        ip.append(datatype='float', name='step')
   
        self.widgetDescr['x0'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':10., 'type':'float',
            'wheelPad':2, 'initialValue':0.,
            'labelCfg':{'text':'x0'} }

        self.widgetDescr['x1'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':10., 'type':'float',
            'wheelPad':2, 'initialValue':3.,
            'labelCfg':{'text':'x1'} }

        self.widgetDescr['step'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':10., 'type':'float',
            'wheelPad':2, 'initialValue':0.01,
            'labelCfg':{'text':'nb. points'} }

        op = self.outputPortsDescr
        op.append(datatype='list', name='x')
        op.append(datatype='list', name='y')

        code = """def doit(self, x0, x1, step):
    import numpy
    x = numpy.arange(x0, x1, step)
    y = numpy.sin(2*numpy.pi*x)
   
    self.outputData( x=x, y=y)
"""
        self.setFunction(code)



class SinFuncSerie(NetworkNode):
    """
Outputs a list of y values of a sinusoidal function

Input:

Output:
    x:  list y values
"""
    def __init__(self, name='SinFuncSerie', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

##         ip = self.inputPortsDescr
##         ip.append(datatype='float', name='x0')
##         ip.append(datatype='float', name='x1')
##         ip.append(datatype='float', name='step')
   
##         self.widgetDescr['x0'] = {
##             'class':'NEThumbWheel','master':'node',
##             'width':75, 'height':21, 'oneTurn':10., 'type':'float',
##             'wheelPad':2, 'initialValue':0.,
##             'labelCfg':{'text':'x0'} }

##         self.widgetDescr['x1'] = {
##             'class':'NEThumbWheel','master':'node',
##             'width':75, 'height':21, 'oneTurn':10., 'type':'float',
##             'wheelPad':2, 'initialValue':3.,
##             'labelCfg':{'text':'x1'} }

## 
##        self.widgetDescr['step'] = {
##             'class':'NEThumbWheel','master':'ParamPanel',
##             'width':75, 'height':21, 'oneTurn':10., 'type':'float',
##             'wheelPad':2, 'initialValue':0.01,
##             'labelCfg':{'text':'nb. points'} }

        op = self.outputPortsDescr
        op.append(datatype='list', name='X')

        code = """def doit(self):
    import numpy
    ind = numpy.arange(60)

    x_tmp=[]
    for i in range(100):
        x_tmp.append(numpy.sin((ind+i)*numpy.pi/15.0))

    X=numpy.array(x_tmp)

    self.outputData(X=X)
"""
        self.setFunction(code)






class LegendNE(NetworkNode):
    """This nodes takes two lists of values and plots the the second against the first.

Input:
    labels          - sequence of strings
    loc          -  'best' : 0,
                    'upper right'  : 1, (default)
                    'upper left'   : 2,
                    'lower left'   : 3,
                    'lower right'  : 4,
                    'right'        : 5,
                    'center left'  : 6,
                    'center right' : 7,
                    'lower center' : 8,
                    'upper center' : 9,
                    'center'       : 10,

                    If none of these are suitable, loc can be a 2-tuple giving x,y  in axes coords, ie,
                  loc = 0, 1 is left top
                   loc = 0.5, 0.5 is center, center
    lines     - sequence of lines
Output:
    legend       Matplotlib Axes object
    
"""
    def __init__(self, name='Legend', **kw):
        kw['name'] = name
        
        NetworkNode.__init__(*(self,), **kw)
        codeBeforeDisconnect = """def beforeDisconnect(self, c):
    
    node1 = c.port1.node
    node2 = c.port2.node
    node1.figure.delaxes(node1.axes)
    node1.figure.add_axes(node1.axes)
"""
        ip = self.inputPortsDescr
        ip.append(datatype='list',required=True, name='label')
        ip.append(datatype='string',required=False, name='location', defaultValue='upper right')
        self.widgetDescr['label'] = {
            'class':'NEEntry', 'master':'node',
            'labelCfg':{'text':'Label:'},
            'initialValue':''}    

        self.widgetDescr['location'] = {
        'class':'NEComboBox', 'master':'node',
            'choices':list(locations.keys()),
            'fixedChoices':True,
            'initialValue':'upper right',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'Location:'}}
            
        op = self.outputPortsDescr
        op.append(datatype='MPLDrawArea', name='drawAreaDef')
        code = """def doit(self, label, location):
        kw={ 'legendlabel':label,'legendlocation':location}
        self.outputData(drawAreaDef=kw) 
"""
        self.setFunction(code)

       
class ColorBarNE(NetworkNode):
    """Class for drawing color bar
input :
    plot          - axes instance
    current_image -image instance
    extend        -  both,neither,min or max.If not 'neither', make pointed end(s) for
                     out-of-range values.  These are set for a given colormap using the
                    colormap set_under and set_over methods.
    orientation    - horizontal or vertical
    spacing        -uniform or proportional.Uniform spacing gives each discrete color the same                      space;proportional makes the space proportional to the data interval.
    shrink         -fraction by which to shrink the colorbar
"""

    def __init__(self, name='ColorBar', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='MPLAxes', required=True, name='plot')
        ip.append(datatype='None', required=True, name='current_image')
        ip.append(datatype='string', required=False, name='extend', defaultValue='neither')
        ip.append(datatype='float', required=False, name='orientation', defaultValue='vertical')
        ip.append(datatype='string', required=False, name='spacing', defaultValue='uniform')
        ip.append(datatype='float', required=False, name='shrink', defaultValue=1.)
        self.widgetDescr['shrink'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':2, 'type':'float',
            'wheelPad':2, 'initialValue':1.0,'min':0.0,'max':1.0,
            'labelCfg':{'text':'shrink'} }
        self.widgetDescr['extend'] = {
        'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['both','neither','min','max'],
            'fixedChoices':True,
            'initialValue':'neither',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'extend:'}} 
        self.widgetDescr['orientation'] = {
        'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['vertical','horizontal'],
            'fixedChoices':True,
            'initialValue':'vertical',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'orientation:'}}
        self.widgetDescr['spacing'] = {
        'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['uniform',' proportional'],
            'fixedChoices':True,
            'initialValue':'uniform',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'spacing:'}}  
        op = self.outputPortsDescr
        op.append(datatype='MPLAxes', name='axes')
        code = """def doit(self, plot, current_image, extend, orientation, spacing, shrink):
    axes_list=plot.figure.axes
    if len(axes_list):
        pos=plot.figure.axes[0].get_position()
        for i in axes_list:
          if not isinstance(i,Subplot):
            plot.figure.delaxes(i)
    if current_image is not None:
         pl=plot.figure.colorbar(current_image,cmap=current_image.cmap,shrink=shrink,extend=extend,orientation=orientation,spacing=spacing,**_filled_kw())  
         if orientation=="vertical":
            plot.figure.axes[0].set_position([0.125, 0.1, 0.62, 0.8])
            if shrink>=1.0:
                pl.ax.set_position([0.785, 0.1, 0.03, 0.8])
            else:
                pl.ax.set_position([0.785,pl.ax.get_position().bounds[1],0.03,pl.ax.get_position().bounds[-1]])
                
         else:
            plot.figure.axes[0].set_position([0.125, 0.34, 0.62, 0.56])
            if shrink>=1.0:
                pl.ax.set_position([0.125, 0.18, 0.62, 0.04])
            else:
                pl.ax.set_position([pl.ax.get_position().bounds[0],0.18,pl.ax.get_position().bounds[2],0.04])
         plot.figure.canvas.draw()
    else:
        plot.figure.canvas.delete(pl)
        
    self.outputData(axes=pl)
"""   
    
        self.setFunction(code)

class Text(NetworkNode):
    """Class for writting text in the axes
posx:        x coordinate
posy:        y coordinate
textlabel:   label name
rotation:    angle to be rotated
horizontal alignment: ['center', 'right', 'left']
vertical alignment:   ['center', 'right', 'left']
"""
    def __init__(self, name='Text', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        ip = self.inputPortsDescr
        ip.append(datatype='float', required=False, name='posx', defaultValue=.1)
        ip.append(datatype='float', required=False, name='posy', defaultValue=.1)
        ip.append(datatype='string', required=False, name='textlabel', defaultValue='')
        ip.append(datatype='string', required=False, name='rotation', defaultValue=0)
        ip.append(datatype='string', required=False, name='horizontalalignment', defaultValue='center')
        ip.append(datatype='string', required=False, name='verticalalignment', defaultValue='center')
        self.widgetDescr['posx'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':1., 'type':'float',
            'wheelPad':2, 'initialValue':0.1,
            'labelCfg':{'text':'posx'} }

        self.widgetDescr['posy'] = {
            'class':'NEThumbWheel','master':'node',
            'width':75, 'height':21, 'oneTurn':1., 'type':'float',
            'wheelPad':2, 'initialValue':0.1,
            'labelCfg':{'text':'posy'} }

        self.widgetDescr['textlabel'] = {
            'class':'NEEntry', 'master':'node',
            'labelCfg':{'text':'text'},
            'initialValue':''}
        
        self.widgetDescr['rotation'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':75, 'height':21, 'oneTurn':10, 'type':'float',
            'wheelPad':2, 'initialValue':0,
            'labelCfg':{'text':'rotation'} }
            
        self.widgetDescr['horizontalalignment'] = {
        'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['center', 'right', 'left'],
            'fixedChoices':True,
            'initialValue':'center',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'horizontalalignment:'}}
        self.widgetDescr['verticalalignment'] = {
        'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['top', 'bottom', 'center'],
            'fixedChoices':True,
            'initialValue':'center',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'verticalalignment:'}}    
                
        op = self.outputPortsDescr
        op.append(datatype='MPLDrawArea', name='drawAreaDef')

        code = """def doit(self, posx, posy, textlabel, rotation, horizontalalignment, verticalalignment):

    kw = {'posx':posx, 'posy':posy, 'textlabel':textlabel, 'horizontalalignment':horizontalalignment, 'verticalalignment':verticalalignment,'rotation':rotation}
    
    self.outputData(drawAreaDef=kw)
"""
        self.setFunction(code)
        
class SaveFig(NetworkNode):
    """Save the current figure.
fname - the filename to save the current figure to.  The
            output formats supported depend on the backend being
            used.  and are deduced by the extension to fname.
            Possibilities are eps, jpeg, pdf, png, ps, svg.  fname
            can also be a file or file-like object - cairo backend
            only.  dpi - is the resolution in dots per inch.  If
            None it will default to the value savefig.dpi in the
            matplotlibrc file
facecolor and edgecolor are the colors of the figure rectangle
orientation - either 'landscape' or 'portrait' 
papertype   - is one of 'letter', 'legal', 'executive', 'ledger', 'a0' through 
                  'a10', or 'b0' through 'b10' - only supported for postscript output
format      - one of 'pdf', 'png', 'ps', 'svg'. It is used to specify the
                  output when fname is a file or file-like object - cairo
                  backend only.
"""
    def __init__(self, name='saveFig', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='MPLFigure', required=False, name='figure')    
        ip.append(datatype=None, required=False, name='fname')
        ip.append(datatype=None, required=False, name='dpi', defaultValue=80)
        ip.append(datatype=None, required=False, name='facecolor', defaultValue='w')
        ip.append(datatype=None, required=False, name='edgecolor', defaultValue='w')
        ip.append(datatype=None, required=False, name='orientation', defaultValue='portrait')
        ip.append(datatype=None, required=False, name='papertype')
        ip.append(datatype=None, required=False, name='format')
        
        self.widgetDescr['fname'] = {
            'class':'NEEntry', 'master':'node',
            'labelCfg':{'text': 'filename:'},
            'initialValue':''}
            
        self.widgetDescr['dpi'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':2, 'type':'int',
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':80,
            'labelCfg':{'text':'dpi'} }
            
        self.widgetDescr['facecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'w',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'facecolor:'}}
        
        self.widgetDescr['edgecolor'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':list(cnames.keys()),
            'fixedChoices':True,
            'initialValue':'w',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'edgecolor:'}}
            
        self.widgetDescr['orientation'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['landscape','portrait'],
            'fixedChoices':True,
            'initialValue':'portrait',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'orientation:'}}
        
        self.widgetDescr['papertype'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['letter', 'legal', 'executive', 'ledger','a0','a1','a2','a3','a4','a5','a6','a7','a8','a9','a10','b0','b1','b2','b3','b4','b5','b6','b7','b8','b9','b10',None],
            'fixedChoices':True,
            'initialValue':'None',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'papertype:'}}
            
        self.widgetDescr['format'] = {
            'class':'NEComboBox', 'master':'ParamPanel',
            'choices':['pdf', 'png', 'ps', 'svg',None],
            'fixedChoices':True,
            'initialValue':'None',
            'entryfield_entry_width':7,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'format:'}} 
            
        code = """def doit(self, figure, fname, dpi, facecolor, edgecolor,
orientation, papertype, format):
    if figure:
        if format in (None, '', 'None', 'none'):
            format = None
        kw = {'papertype': papertype} if papertype and _PAPERTYPE else {}
        figure.savefig(fname, dpi=dpi, facecolor=facecolor, edgecolor=edgecolor,
                       orientation=orientation, format=format, **kw)
"""
        self.setFunction(code)
        
    
class MeshGrid(NetworkNode):
    """This class converts vectors x, y with lengths Nx=len(x) and Ny=len(y) to  X, Y and returns them.
where X and Y are (Ny, Nx) shaped arrays with the elements of x
and y repeated to fill the matrix
    """
    def __init__(self, name='MeshGrid', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='list',required=False, name='x')
        ip.append(datatype='list',required=False, name='y')
        op = self.outputPortsDescr
        op.append(datatype='None', name='X')
        op.append(datatype='None', name='Y')
        code = """def doit(self,x,y):
    X,Y=meshgrid(x, y)        
    self.outputData(X=X,Y=Y)
"""
        self.setFunction(code)    

def bivariate_normal(X, Y, sigmax=1.0, sigmay=1.0, mux=0.0, muy=0.0, sigmaxy=0.0):
    """Bivariate Gaussian distribution for equal shape X, Y (as the former
    matplotlib.mlab.bivariate_normal)."""
    Xmu = X - mux
    Ymu = Y - muy
    rho = sigmaxy / (sigmax * sigmay)
    z = Xmu ** 2 / sigmax ** 2 + Ymu ** 2 / sigmay ** 2 - 2 * rho * Xmu * Ymu / (sigmax * sigmay)
    denom = 2 * numpy.pi * sigmax * sigmay * numpy.sqrt(1 - rho ** 2)
    return numpy.exp(-z / (2 * (1 - rho ** 2))) / denom


class BivariateNormal(NetworkNode):
    """Bivariate gaussan distribution for equal shape X, Y"""
    def __init__(self, name='BivariateNormal', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='None', name='arraylist1')
        ip.append(datatype='None', name='arraylist2')
        ip.append(datatype='float', required=False, name='sigmax', defaultValue=1.)
        ip.append(datatype='float', required=False, name='sigmay', defaultValue=1.)
        ip.append(datatype='float', required=False, name='mux', defaultValue=0.)
        ip.append(datatype='float', required=False, name='muy', defaultValue=0.)
        ip.append(datatype='float', required=False, name='sigmaxy', defaultValue=0.)
        self.widgetDescr['sigmax'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':2, 'type':'float',
            'wheelPad':2, 'initialValue':1.0,
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'sigmax'} }
        self.widgetDescr['sigmay'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':2, 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':1.0,
            'labelCfg':{'text':'sigmay'} }
        self.widgetDescr['mux'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':2, 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':0.0,
            'labelCfg':{'text':'mux'} }
        self.widgetDescr['muy'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':2, 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':0.0,
            'labelCfg':{'text':'muy'} }
        self.widgetDescr['sigmaxy'] = {
            'class':'NEThumbWheel','master':'ParamPanel',
            'width':61, 'height':21, 'oneTurn':2, 'type':'float',
            'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w'},
            'wheelPad':2, 'initialValue':0.0,
            'labelCfg':{'text':'sigmaxy'} }
        op = self.outputPortsDescr
        op.append(datatype=None, name='z')
        
        code = """def doit(self, x, y, sigmax, sigmay, mux, muy, sigmaxy):
    import numpy
    X=numpy.array(x)
    Y=numpy.array(y)
    z=bivariate_normal( X, Y, sigmax=sigmax, sigmay=sigmay, mux=mux, muy=muy, sigmaxy=sigmaxy)
    self.outputData(z=z)
"""
        self.setFunction(code)
    
###########################################################################
#
#  Create and populate library
#
###########################################################################

matplotliblib = NodeLibrary('MatPlotLib', '#99AFD8',
                              doc='2D plots with matplotlib, shown in panels of the page')


class MPLFigureType(AnyArrayType):
    def __init__(self, name='MPLFigure', datashape=None, color='#99AFD8', shape='oval',
                 width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape, klass=Figure)


class MPLAxesType(AnyArrayType):
    def __init__(self, name='MPLAxes', datashape=None, color='#99AFD8', shape='oval',
                 width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape, klass=Axes)


class MPLDrawAreaType(AnyArrayType):
    def __init__(self, name='MPLDrawArea', datashape=None, color='#99AFD8', shape='diamond',
                 width=None, height=None):
        AnyArrayType.__init__(self, name=name, color=color, shape=shape, klass=dict)


for _t in (MPLFigureType, MPLAxesType, MPLDrawAreaType):
    matplotliblib.addType(_t())
try:
    from wewos.libs.imaging import ImageType
    matplotliblib.addType(ImageType())
except Exception:
    pass
matplotliblib.addNode(MPLFigureNE, 'Figure', 'Input')
matplotliblib.addNode(MPLImageNE, 'ImageFigure', 'Input')
matplotliblib.addNode(MPLDrawAreaNE, 'Draw Area', 'Input')
matplotliblib.addNode(MultiPlotNE, 'MultiPlot', 'Misc')
matplotliblib.addNode(MPLMergeTextNE, 'MergeText', 'Input')
matplotliblib.addNode(ColorBarNE, 'ColorBar', 'Misc')
matplotliblib.addNode(Text, 'Text', 'Input')
matplotliblib.addNode(PolarAxesNE, 'PolarAxes', 'Plotting')
matplotliblib.addNode(HistogramNE, 'Histogram', 'Plotting')
matplotliblib.addNode(PlotNE, 'Plot', 'Plotting')
matplotliblib.addNode(PlotDateNE, 'PlotDate', 'Plotting')
matplotliblib.addNode(PieNE, 'Pie', 'Plotting')
matplotliblib.addNode(SpyNE, 'Spy', 'Plotting')
#matplotliblib.addNode(Spy2NE, 'Spy2', 'Plotting')
matplotliblib.addNode(VlineNE, 'Vline', 'Plotting')
matplotliblib.addNode(ScatterNE, 'Scatter', 'Plotting')
#matplotliblib.addNode(ScatterClassicNE, 'ScatterClassic', 'Plotting')
matplotliblib.addNode(FigImageNE, 'Figimage', 'Plotting')
matplotliblib.addNode(FillNE, 'Fill', 'Plotting')
matplotliblib.addNode(ContourNE, 'Contour', 'Plotting')
matplotliblib.addNode(PcolorMeshNE,'PcolorMesh', 'Plotting')
matplotliblib.addNode(PcolorNE,'Pcolor', 'Plotting')
#matplotliblib.addNode(PcolorClassicNE,'PcolorClassic', 'Plotting')
matplotliblib.addNode(RandNormDist, 'RandNormDist', 'Demo')
matplotliblib.addNode(SinFunc, 'SinFunc', 'Demo')
matplotliblib.addNode(SinFuncSerie, 'SinFuncSerie', 'Demo')
matplotliblib.addNode(MatPlotLibOptions, 'Set Matplotlib options', 'Input')
matplotliblib.addNode(LegendNE, 'Legend', 'Input')
matplotliblib.addNode(TablePlotNE, 'TablePlot', 'Plotting')
matplotliblib.addNode(SpecgramNE, 'Specgram', 'Plotting')
matplotliblib.addNode(CSDNE, 'CSD', 'Plotting')
matplotliblib.addNode(PSDNE, 'PSD', 'Plotting')
matplotliblib.addNode(LogCurveNE, 'LogCurve', 'Plotting')
matplotliblib.addNode(SemilogxNE, 'Semilogx', 'Plotting')
matplotliblib.addNode(SemilogyNE, 'Semilogy', 'Plotting')
matplotliblib.addNode(BoxPlotNE, 'BoxPlot', 'Plotting')
matplotliblib.addNode(ErrorBarNE, 'ErrorBar', 'Plotting')
matplotliblib.addNode(BarHNE, 'BarH', 'Plotting')
matplotliblib.addNode(BarNE, 'Bar', 'Plotting')
matplotliblib.addNode(QuiverNE, 'Quiver', 'Plotting')
matplotliblib.addNode(StemNE,'Stem','Plotting')
matplotliblib.addNode(BivariateNormal,'BivariateNormal','Demo')
matplotliblib.addNode(MeshGrid,'MeshGrid','Demo')
matplotliblib.addNode(SaveFig,'SaveFig','Misc')

###########################################################################
#
#  Library specific data types
#
###########################################################################


