"""Builds wewos/libs/mpl.py from the Python 3 conversion of MGLTools
Vision/matplotlibNodes.py (one-time port script; Python 3.8+ for ast).

    python3 tools/ports/make_matplotlib.py matplotlibNodes_py3.py wewos/libs/mpl.py \
        tools/ports/matplotlib_new_classes.py colours_py3.py posnegFill_py3.py
"""
import ast
import re
import sys

src_path, out_path, new_path, colours_path, posneg_path = sys.argv[1:6]
s = open(src_path).read()


def stmts(s, pred):
    tree = ast.parse(s)
    lines = s.split('\n')
    for node in tree.body:
        text = '\n'.join(lines[node.lineno - 1:node.end_lineno])
        if pred(node, text):
            yield node.lineno - 1, node.end_lineno


def replace_stmts(s, pred, new, what, expect=None):
    spans = list(stmts(s, pred))
    if expect is not None and len(spans) != expect:
        raise SystemExit('%s: %d matched, expected %d' % (what, len(spans), expect))
    lines = s.split('\n')
    for i, (a, b) in enumerate(reversed(spans)):
        lines[a:b] = [new] if (new and i == len(spans) - 1) else []
    return '\n'.join(lines)


def is_class(*names):
    return lambda n, t: isinstance(n, ast.ClassDef) and n.name in names


def sub1(s, old, new):
    if old not in s:
        raise SystemExit('not found: %r' % old[:80])
    return s.replace(old, new, 1)


s = re.sub(r'^#{20,}\n(#.*\n)*?#{20,}\n', '', s, count=1, flags=re.M)
HEADER = '''# Ported to Python 3 from MGLTools Vision/matplotlibNodes.py
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
'''

# ---- imports --------------------------------------------------------------------------
s = sub1(s, 'import tkinter\n', '')
s = sub1(s, 'import Pmw,math,os, sys\n', 'import math, os, sys\n')
s = sub1(s, 'from mglutil.util.callback import CallBackFunction\n', '')
s = sub1(s, 'from NetworkEditor.widgets import TkPortWidget, PortWidget\n', '')
s = sub1(s, 'from mglutil.gui.BasicWidgets.Tk.thumbwheel import ThumbWheel\n', '')
s = sub1(s, 'from Vision import UserLibBuild\n', '')
s = sub1(s, 'from NetworkEditor.items import NetworkNode\n',
         'from wewos.engine import NetworkNode, NodeLibrary\n'
         'from wewos.engine.datatypes import AnyArrayType\n')
s = re.sub(r"if not 'matplotlib\.backends' in sys\.modules:\n\s+matplotlib\.use\('TkAgg'\)\n",
           "matplotlib.use('Agg', force=True)     # figures are drawn off screen\n", s)
s = sub1(s, 'from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg\n', '')
s = sub1(s, 'from matplotlib.backends.backend_tkagg import NavigationToolbar2TkAgg\n', '')
s = sub1(s, 'from Vision.colours import get_colours\n', '')
s = sub1(s, 'from Vision.posnegFill import posNegFill\n', '')
s = sub1(s, 'from matplotlib.cbook import iterable\n', 'from numpy import iterable\n')
s = sub1(s, 'mplversion = list(map(int, matplotlib.__version__.split(".")))',
         'mplversion = [int(x) for x in re.findall(r"\\d+", matplotlib.__version__)[:3]]\nimport re')
s = 'import re\n' + s
# old matplotlib calls inside node code
s = s.replace('.set_axis_bgcolor(', '.set_facecolor(')
s = s.replace('.figurePatch', '.patch').replace('.axesPatch', '.patch')
# matplotlib 3 renamed or removed these
for old, new in (
        ("add_axes(self.axes.get_position(),polar=True,axisbg=axisbg)",
         "add_axes(self.axes.get_position(),polar=True,facecolor=axisbg)"),
        ("self.axes.hist(values, bins=bins, normed=normed)",
         "self.axes.hist(values, bins=bins, density=bool(normed))"),
        ("self.axes.loglog(x,y,basex=basex)", "self.axes.loglog(x,y,base=basex)"),
        ("self.axes.loglog( x,y,basey=basey)", "self.axes.loglog( x,y,base=basey)"),
        ("self.axes.semilogx(x,y,basex=basex)", "self.axes.semilogx(x,y,base=basex)"),
        ("self.axes.semilogy(x,y,basey=basey)", "self.axes.semilogy(x,y,base=basey)"),
        # Vision's quiver units widget started on the invalid value 'units'
        ("'initialValue':'units',", "'initialValue':'width',"),
        # TablePlot without row colors (an optional port)
        ("self.axes.bar(ind, data[row], width, bottom=yoff, color=rowColors[row])",
         "self.axes.bar(ind, data[row], width, bottom=yoff,\n"
         "                      color=rowColors[row] if rowColors else None)")):
    s = sub1(s, old, new)
# matplotlib.mlab.bivariate_normal was removed (matplotlib 3.1): the same formula
BIVARIATE = '''def bivariate_normal(X, Y, sigmax=1.0, sigmay=1.0, mux=0.0, muy=0.0, sigmaxy=0.0):
    """Bivariate Gaussian distribution for equal shape X, Y (as the former
    matplotlib.mlab.bivariate_normal)."""
    Xmu = X - mux
    Ymu = Y - muy
    rho = sigmaxy / (sigmax * sigmay)
    z = Xmu ** 2 / sigmax ** 2 + Ymu ** 2 / sigmay ** 2 - 2 * rho * Xmu * Ymu / (sigmax * sigmay)
    denom = 2 * numpy.pi * sigmax * sigmay * numpy.sqrt(1 - rho ** 2)
    return numpy.exp(-z / (2 * (1 - rho ** 2))) / denom


class BivariateNormal('''
s = sub1(s, 'class BivariateNormal(', BIVARIATE)
# SaveFig: 'None' in the format menu means "from the file name"; papertype is
# deprecated in matplotlib 3 and only passed when set
s = sub1(s, """        figure.savefig(fname,dpi=dpi,facecolor=facecolor,edgecolor=edgecolor,orientation=orientation,papertype=papertype,format=format)""",
         """        if format in (None, '', 'None', 'none'):
            format = None
        kw = {'papertype': papertype} if papertype else {}
        figure.savefig(fname, dpi=dpi, facecolor=facecolor, edgecolor=edgecolor,
                       orientation=orientation, format=format, **kw)""")
# ColorBar: a Bbox is no longer a sequence
s = s.replace('pl.ax.get_position()[', 'pl.ax.get_position().bounds[')
# MultiPlot: copy the artists of its input plots (see copy_artists)
i = s.index('        code = """def doit(self, plots, drawAreaDef):\n    self.axes.clear()\n    ax=self.axes')
j = s.index('    self.outputData(multiplot=self.axes)\n"""', i)
s = s[:i] + '''        code = """def doit(self, plots, drawAreaDef):
    self.axes.clear()
    ax = self.axes
    for p in plots:
        copy_artists(p, ax)
    ax.autoscale_view()
    self.setDrawAreaDef(drawAreaDef)
    self.canvas.draw()
''' + s[j:]

# ---- the classes rewritten in matplotlib_new_classes.py ----------------------------------
new = open(new_path).read()
s = replace_stmts(s, is_class('Figure', 'MPLFigureNE', 'MPLPlottingNode', 'MPLImageNE',
                              'MatPlotLibOptions', 'NEMatPlotLibOptions'), None, 'others', 6)
s = replace_stmts(s, is_class('MPLBaseNE'), new, 'MPLBaseNE', 1)
s = s.replace('from matplotlib.figure import Figure as OriginalFigure\n',
              'from matplotlib.figure import Figure\n')

# ---- helpers that were Vision modules ----------------------------------------------------
helpers = ('\n# ---- Vision.colours and Vision.posnegFill (ported) ----\n' +
           re.sub(r'^(from|import) .*\n', '', open(colours_path).read(), flags=re.M) + '\n' +
           re.sub(r'^from matplotlib\.pylab import \*\n', '', open(posneg_path).read(), flags=re.M))
s = sub1(s, 'from numpy import iterable\n', 'from numpy import iterable\n')
s = s.replace('import numpy\nfrom matplotlib.artist import setp\n',
              'import numpy\nfrom matplotlib.artist import setp\n'
              'from matplotlib.colors import colorConverter\n'
              'from numpy import sum, asarray, linspace\n' + helpers, 1)

# ---- library tail --------------------------------------------------------------------------
s = replace_stmts(s, lambda n, t: isinstance(n, ast.Try) and 'UserLibBuild' in t, None, 'tail try')
s = re.sub(r'\nUserLibBuild\.addTypes\(.*\)\n', '\n', s)
s = s.replace('matplotliblib.addWidget(NEMatPlotLibOptions)\n', '')
s = s.replace('from Vision.VPE import NodeLibrary\n', '')
s = s.replace("matplotliblib = NodeLibrary('MatPlotLib', '#99AFD8')",
              """matplotliblib = NodeLibrary('MatPlotLib', '#99AFD8',
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
    pass""")
open(out_path, 'w').write(HEADER + s.lstrip('\n'))
print('wrote', out_path)
