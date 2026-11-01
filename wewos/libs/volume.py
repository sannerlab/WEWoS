# Ported to Python 3 from MGLTools Volume/VisionInterface/VolumeNodes.py
# Original: Michel Sanner, Daniel Stoffler, Anna Omelchenko, Sophie Coon and
# others (TSRI); revision Guillaume Vareille.
# Port: Michel Sanner, PhD. Copyright (c) 2026.
"""Volume: read, write, transform, mask, blur, slice and isocontour 3D grids.

Grids are Volume.Grid3D objects; the readers, operators and the UT packages
(isocontour, blur, signed distance, meshing) come from the Python 3 Volume
and UTpackages of the environment (the ADCP distribution's adcpsuite).

Converted mechanically (wewos.legacy.py2to3, which also converts the doit
code strings), then edited by hand where nodes drew through DejaVu or asked
questions with Tk:
  * OrthoSlice draws a slice as a colored mesh (3Dmol has no textures) and
    BoundingBox as lines, both with the 3D Visualization geometry;
  * ReadAnyMap takes the file format on a port instead of a Tk dialog;
  * the contour spectrum widget is drawn by the page (isovalue slider with
    the area / volume / gradient signatures above it);
  * nodes that took MolKit atoms take MolKit2 molecules or selections;
  * UTiso and CoarseMolSurf are rebuilt with the 3D Visualization
    IndexedPolygons node; CoarseMolSurf no longer decimates (no QSlim);
  * not ported: UT-VolRen (volume rendering), UTiso+Decim (QSlim), the
    Pmv grid chooser.
"""
import numpy
import math, types
import warnings
import re
from wewos.engine import MacroNode, NetworkNode, NodeLibrary
from wewos.engine.datatypes import AnyType
from wewos import geom as G
from wewos.libs.viz3d import GeometryNode, colormap
from wewos.libs.molecules import atoms_of, radii as radii_of

from wewos.volcore.IO.volReaders import ReadMRC, ReadCCP4, ReadCNS, ReadGRD, ReadBRIX,\
                                    ReadSPIDER, ReadRawiv, ReadEM, ReadFLDBinary
from wewos.volcore.IO.volWriters import WriteCCP4
from wewos.volcore.IO.UHBDGridReader import UHBDReaderASCII
from wewos.volcore.IO.DelphiReader import DelphiReaderBin
#from wewos.volcore.IO.rawivReader import ReadRawiv
from wewos.volcore.IO.AutoGridReader import ReadAutoGrid
from wewos.volcore.Grid3D import Grid3D, Grid3DD, Grid3DF, Grid3DI, \
     Grid3DSI, Grid3DUI, Grid3DUSI, Grid3DUC, ArrayTypeToGrid, GridTypeToArray
from wewos.mglmath.stats import stats



def importMolKitLib(net):
    """MGLTools loaded a library into the editor here."""


def importVizLib(net):
    """MGLTools loaded a library into the editor here."""


class TestVolume(NetworkNode):
    """Outputs a 3D volume of user specified dimensions where each
voxel contains the distance to 'point'

Input Ports
    dim: number of grid points along a size of the volume
    point: point from wich distance is computed. Defaults to (0,0,0)
    
Output Ports
    data: the 3D volume
"""

    def dist(self, x , y, z): 
        return math.sqrt((x-self.xo)**2+(y-self.yo)**2++(z-self.zo)**2)


    def __init__(self, name='Test Volume', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        self.xo = self.yo = self.zo = 0.0
        
        self.widgetDescr['dim'] = {
            'class':'NEDial', 'master':'node', 'initialValue':10,
            'labelCfg':{'text':'dim:'}, 'size':50, 'type':'int' }
        self.inputPortsDescr.append(datatype='int', name='dim')
        self.inputPortsDescr.append(datatype='None', required=False,
                                    name='point')

        self.outputPortsDescr.append(datatype='Grid3DF', name='grid')

        code = """def doit(self, dim, point):
    if point is None:
        point = (0.,0,0)
    self.xo, self.yo, self.zo = point
    #m = numpy.fromfunction( self.dist, ( dim, dim, dim)) 
    m = numpy.indices( (dim,dim,dim), 'f' )[0]
    h = {'title':'testgrid'}
    g = Grid3DF( m.astype('f'), [0.,0.,0.], [1.0, 1.0, 1.0], h )
    if g:
        self.outputData(grid=g)
"""
            
        if code: self.setFunction(code)


class PointsBB(NetworkNode):
    """Compute the bounding box of a set of 3D points

Input Ports
    coords: number of grid points along a size of the volume
    
Output Ports
    boundingBox:  Two 3-float tuple providing 2 corners
"""

    def __init__(self, name='PointsBB', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        #ip.append(datatype='coord3', name='points')
        ip.append(datatype='None', name='points')

        self.outputPortsDescr.append(datatype='list', name='boundingBox')

        code = """def doit(self, points):

    import numpy
    p1 = numpy.min(points, 0)
    p2 = numpy.max(points, 0)
    self.outputData(boundingBox=(p1,p2))
"""

        if code: self.setFunction(code)


class GridPoints(NetworkNode):
    """
    Outputs 3D coordinates of selected the grid points and corresponding values

Input Ports
    grid: grid3D object
    cutLow: cutoff value for selecting points
    cutHigh: cutoff value for selecting points
    
Output Ports
    points: list of 3D coordinates of the grid with values in specified range
    values: values at these grid points
"""

    def __init__(self, name='GridPoints', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='float', name='cutLow')
        self.inputPortsDescr.append(datatype='float', name='cutHigh')

        self.outputPortsDescr.append(datatype='list', name='points')
        self.outputPortsDescr.append(datatype='list', name='values')

        code = """def doit(self, grid, cutLow, cutHigh):
    import numpy

    coords, values, a, b, c = grid.gridPoints(cutLow, cutHigh)

##     # array of boolean for values larger
##     gr = numpy.greater(grid.data, cutLow)
##     ls = numpy.less(grid.data, cutHigh)
##     inrange = gr*ls
##     indi, indj, indk = numpy.nonzero( inrange )

##     coords = []
##     values = []
##     data = grid.data
##     ox, oy, oz = grid.getOriginReal()
##     step = grid.getStepSizeReal()
##     for i, j, k in zip( indi, indj, indk):
##         values.append( data[i][j][k] )
##         coords.append( (ox+i*step[0], oy+j*step[1], oz+k*step[2] ) )
        
##     maxi = numpy.max( grid.data.flatten())
##     coords = []
##     values = []
##     ox, oy, oz = grid.getOriginReal()
##     step = grid.getStepSizeReal()
##     dimx, dimy, dimz = grid.dimensions

##     if cutoff is None:
##         for i in xrange(dimx):
##             dx = i*step[0]
##             for j in xrange(dimy):
##                 dy = j*step[1]
##                 for k in xrange(dimz):
##                     coords.append( (ox+dx, oy+dy, oz+(k*step[2])) )
##         values = grid.data.flatten().tolist()
##     else:
##         data = grid.data
##         for i in xrange(dimx):
##             dx = i*step[0]
##             for j in xrange(dimy):
##                 dy = j*step[1]
##                 for k in xrange(dimz):
##                     val = data[i][j][k]
##                     if val > cutoff:
##                         coords.append( (ox+dx, oy+dy, oz+(k*step[2])) )
##                         values.append( val )
    self.outputData(points = coords, values=values)
"""
            
        if code: self.setFunction(code)


class Grid3DNode(NetworkNode):
    """Create a Grid3D object.
    The position and size to fhte gris can be specified by providing an origin
    and a step size or by providing 2 corners of the volume. The boundingBox
    definition takes precedence

Input Ports
    dimx: number of grid points along a size of the volume
    dimy: number of grid points along a size of the volume
    dimz: number of grid points along a size of the volume
    dtype: data type
    origin: 3-float tuple
    stepsize:  3-float tuple or single float
    boundingBox:  Two 3-float tuple providing 2 corners
    
Output Ports
    grid: Grid3D object
"""

    def __init__(self, name='Grid3D', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='int', name='dimx')
        ip.append(datatype='int', name='dimy')
        ip.append(datatype='int', name='dimz')
        ip.append(datatype='string', name='dtype')
        ip.append(datatype='list', name='origin', required=False)
        ip.append(datatype='list', name='stepsize', required=False)
        ip.append(datatype='list', name='boundingBox', required=False)

        self.widgetDescr['dimx'] = {
            'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'int',
            'showLabel':1, 'oneTurn':5, 'min':1, 'lockMin':True,
            'master':'node', 'labelCfg':{'text':'dimx:'},
            'initialValue':32}
        self.widgetDescr['dimy'] = {
            'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'int',
            'showLabel':1, 'oneTurn':5, 'min':1, 'lockMin':True,
            'master':'node', 'labelCfg':{'text':'dimy:'},
            'initialValue':32}
        self.widgetDescr['dimz'] = {
            'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'int',
            'showLabel':1, 'oneTurn':5, 'min':1, 'lockMin':True,
            'master':'node', 'labelCfg':{'text':'dimz:'},
            'initialValue':32}
        self.widgetDescr['dtype'] = {
            'initialValue': 'Grid3DF', 'fixedChoices': 1, 'autoList': False,
            'choices': ('Grid3DD', 'Grid3DF', 'Grid3DF', 'Grid3DI',
                        'Grid3DSI', 'Grid3DUC'), 'master': 'node',
            'labelCfg': {'text': 'data type'},
            'entryfield_entry_width':8,
            'class': 'NEComboBox'}
        self.widgetDescr['origin'] = {'class':'NEEntry',
            'labelGridCfg':{'sticky':'we'}, 'master':'node',
            'labelCfg':{'text':'origin ox,oy,oz:'},
            'initialValue': '0,0,0'
            }
        self.widgetDescr['stepsize'] = {'class':'NEEntry',
            'labelGridCfg':{'sticky':'we'}, 'master':'node',
            'labelCfg':{'text':'stepsize:'},
            'initialValue': '1,1,1'
            }

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')

        code = """def doit(self, dimx, dimy, dimz, dtype, origin, stepsize, boundingBox):

    import numpy
    dt = GridTypeToArray[dtype]
    array= numpy.zeros( (dimx,dimy,dimz), dt)
    gtype = ArrayTypeToGrid[dt]
    import types

    if boundingBox is not None:
        p1, p2 = boundingBox
        origin = p1 
        stepsize = ( float(p2[0]-p1[0])/dimx, float(p2[1]-p1[1])/dimy,
                     float(p2[2]-p1[2])/dimz )
    else:
        stepsize = eval(stepsize)
        if type(stepsize)==float:
            stepsize=[stepsize]*3
        elif type(stepsize)==int:
            stepsize=[float(stepsize)]*3

        origin = eval(origin)

    grid = gtype(array, origin, stepsize, {}, None)
    self.outputPorts[0].setDataType(gtype)
    self.outputData(grid=grid)
"""

        if code: self.setFunction(code)


class SetValuesAtPositions(NetworkNode):
    """Set values in grid as position indicated by real coordinates

Input Ports
    positions: list of (x,y,z) positions
    values: list of values
    
Output Ports
    grid: Grid3D object
"""

    def __init__(self, name='setValAtPos', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='grid')
        ip.append(datatype='list', name='positions')
        ip.append(datatype='list', name='values')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')

        code = """def doit(self, grid, positions, values):

    assert len(positions)==len(values)
    ox, oy, oz = grid.origin
    sx, sy, sz = grid.stepSize
    dx, dy, dz = grid.dimensions
    data = grid.data
    for p,v in zip(positions, values):
        i = int((p[0]-ox)/sx)
        j = int((p[1]-oy)/sy)
        k = int((p[2]-oz)/sz)
        data[i,j,k] = v

    self.outputPorts[0].setDataType(grid)
    self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


class ToGrid3D(NetworkNode):
    """Takes 3D scale data and turns it into a Grid3D object

Input Ports
    array: data that will be turned into a 3D numpy array
    
Output Ports
    grid: Grid3D Volume object
"""

    def __init__(self, name='NumericToGrid', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='NumericArray', name='array')
        self.inputPortsDescr.append(datatype='Grid3D', name='headerGrid',
                                    required=False)

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        
        code = """def doit(self, array, headerGrid):
    if not isinstance(array, numpy.ndarray):
        castok = False
        tp = [numpy.uint8, numpy.int16, numpy.int32, numpy.float8,
              numpy.float32, numpy.float64]
        for tp in typelist:
            try:
                ar = numpy.array( array, tp )
            except:
                pass
            break
        array = ar
        
    gtype = ArrayTypeToGrid[array.dtype]

    if headerGrid is not None:
        # we should make sure headerGrid.dimensions matches array.shape
        origin = headerGrid.origin[:]
        stepSize = headerGrid.stepSize[:]
        header = headerGrid.header.copy()
        crystal = headerGrid.crystal
    else:
        origin = [0.,0.,0.]
        stepSize = [1.,1.,1.]
        header = {'title':'from numpy array'}
        crystal = None
        
    grid = gtype(array, origin, stepSize, header, crystal)
    self.outputPorts[0].setDataType(gtype)
    self.outputData(grid=grid)
"""
        if code: self.setFunction(code)



class Sample(NetworkNode):
    """Subsamples a grid using strides, creating a new volume object of the same type
Simply implements the numpy ::step to get values from the original volume

Input Ports
    grid: Grid3D Volume object to be sampled
    step: stride value
    
Output Ports
    grid: new Grid3D Volume object
"""

    def __init__(self, name='SampleGrid', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='int', name='step')
        self.widgetDescr['step'] = {
            'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'int',
            'showLabel':1, 'oneTurn':5, 'min':1, 'lockMin':True,
            'master':'node',
            'labelCfg':{'text':'step:'},
            }
        
        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        
        code = """def doit(self, grid, step):

    if step==1:
        self.outputData(grid=grid)
    else:
        smallarray = numpy.array(grid.data[::step, ::step, ::step])
        # recompute spacing
        d = grid.dimensions
        s = grid.stepSize
        dims = smallarray.shape
        sx = s[0]*step
        sy = s[1]*step
        sz = s[2]*step
        gtype = ArrayTypeToGrid[smallarray.dtype]
        crystal = None
        if grid.crystal:
            from wewos.mglmath.crystal import Crystal
            crystal = Crystal( grid.crystal.length, grid.crystal.angles)
        ngrid = gtype(smallarray, grid.origin, (sx,sy,sz),
                      grid.header.copy(), crystal)
        ngrid.normalize()
        self.outputPorts[0].setDataType(gtype)
        self.outputData(grid=ngrid)
"""
        if code: self.setFunction(code)


from wewos.volcore.Operators.trilinterp import trilinterp

class GridByLookUp(NetworkNode):
    """Create a new Grid3D object by looking up grid values in another grid.
    It is assumed the new grid is contained in the grid it is getting values
    from. The new grid values are calculated by tri-linear interpolation.

Input Ports
    gridToLookUp: Grid3D Volume object to be sampled
    newGrid: Grid3D object to be filled with values looked up in gridToLookUp
    
Output Ports
    newGrid: new Grid3D Volume object
"""

    def __init__(self, name='GridByLookUp', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='Grid3D', name='gridToLookUp')
        self.inputPortsDescr.append(datatype='Grid3D', name='newGrid')
        
        self.outputPortsDescr.append(datatype='Grid3D', name='newGrid')
        
        code = """def doit(self, gridToLookUp, newGrid):

    import numpy

    points = []
    ox, oy, oz = newGrid.getOriginReal()
    step = newGrid.getStepSizeReal()

    for i in range(newGrid.dimensions[0]):
        dx = i*step[0]
        for j in range(newGrid.dimensions[1]):
            dy = j*step[1]
            for k in range(newGrid.dimensions[2]):
                points.append( (ox+dx, oy+dy, oz+(k*step[2])) )

    origin = numpy.array(gridToLookUp.origin, numpy.float32)
    stepSize = numpy.array(gridToLookUp.stepSize, numpy.float32)
    invstep = ( 1./stepSize[0], 1./stepSize[1], 1./stepSize[2] )
    if gridToLookUp.crystal:
        points = gridToLookUp.crystal.toFractional(vert)

    values = trilinterp(points, gridToLookUp.data, invstep, origin)

    newGrid.data.flat = values

    self.outputData(newGrid=newGrid)
"""
        if code: self.setFunction(code)


class ArrayArrayOp(NetworkNode):
    """Add, subtract, multiply or divide the data of 2 Grid3d objects.
It is assumed the grids are of same shape and aligned (i.e. same origin and same step size).

Input Ports
    grid1: first Grid3D Volume object
    grid2: second Grid3D Volume object
    operation: string in 'add', 'sub', 'mult', div'
    copy: boolean indicating of a new grid object shoudl be crated.  When
          False grid1.data is modified
    
Output Ports
    grid: Grid3D with modified values
"""
    def __init__(self, name='ArrayOp', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append({'datatype': 'Grid3D', 'name': 'grid1'})
        ip.append({'datatype': 'Grid3D', 'name': 'grid2'})
        ip.append({'datatype': 'string', 'name': 'operator'})
        ip.append({'datatype': 'boolean', 'name': 'copy'})

        self.widgetDescr['operator'] = {
            'initialValue': '', 'fixedChoices': 1, 'autoList': False,
            'choices': ('add','sub','mul','div'), 'master': 'node',
            'widgetGridCfg': {'column': 1, 'labelSide': 'left', 'row': 0},
            'labelCfg': {'text': 'operator'},
            'entryfield_entry_width':8,
            'class': 'NEComboBox'}

        self.widgetDescr['copy'] = {'class':'NECheckButton', 'master':'node',
            'initialValue':True,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'create new grid:'},
            }

        op = self.outputPortsDescr
        op.append({'datatype': 'Grid3D', 'name': 'grid'})
        
        code = """def doit(self, grid1, grid2, operation, copy):
    import operator
    op = getattr(operator, operation)
    if copy is False:
        grid1.data = apply(op, (grid1.data, grid2.data)).astype(grid1.data.dtype.char)
        newgrid = grid1
    else:
        newdata = apply(op, (grid1.data, grid2.data)).astype(grid1.data.dtype.char)
        newgrid = grid1.__class__( newdata, grid1.origin, grid1.stepSize,
                                   grid1.header)
    self.outputData(grid=newgrid)
"""
        self.configure(function=code)


class ArrayScalarOp(NetworkNode):
    """Add, subtract, multiply or divide the data of 2 a Grid3d object by a
scalar value.  It is assumed the grids are of same shape.

Input Ports
    grid: Grid3D Volume object
    value: scalar value
    operation: string in 'add', 'sub', 'mult', div'
    copy: boolean indicating of a new grid object should be crated.
    
Output Ports
    grid: Grid3DF with modified values if a new grid is created or grid1 with
          modified values
"""
    def __init__(self, name='ArrayOp', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append({'datatype': 'Grid3D', 'name': 'grid'})
        ip.append({'datatype': 'float', 'name': 'value'})
        ip.append({'datatype': 'string', 'name': 'operator'})
        ip.append({'datatype': 'boolean', 'name': 'copy'})

        self.widgetDescr['operator'] = {
            'initialValue': '', 'fixedChoices': 1, 'autoList': False,
            'choices': ('add','sub','mul','div'), 'master': 'node',
            'widgetGridCfg': {'column': 1, 'labelSide': 'left', 'row': 0},
            'labelCfg': {'text': 'operator'},
            'entryfield_entry_width':8,
            'class': 'NEComboBox'}

        self.widgetDescr['copy'] = {'class':'NECheckButton', 'master':'node',
            'initialValue':True,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'create new grid:'},
            }

        op = self.outputPortsDescr
        op.append({'datatype': 'Grid3DF', 'name': 'grid'})
        
        code = """def doit(self, grid, value, operation, copy):
    import operator
    op = getattr(operator, operation)
    if copy is False:
        grid.data = (op(*(grid.data, value))).astype(grid.data.dtype.char)
        newgrid = grid
    else:
        newdata = apply(op, (grid.data, value)).astype('f')
        newgrid = Grid3DF( newdata, grid.origin, grid.stepSize, grid.header)
    self.outputData(grid=newgrid)
"""
        self.configure(function=code)


    



##
##  MS attempt to make a node with 3 slicing planes
##
## class OrthoSlices(GeometryNode):
##     """Create a texture mapped quad displ;aying a 2D slices orthogonal
## to the volume axes.

## Input Ports
##     grid:        Grid3D object
##     axis:        'x', 'y' or 'z'
##     sliceNumber: position along the axis
##     colorMap:    colormap object used to build 2D texture
    
## Output Ports
##     geom: geom object textured2DArray
## """
##     def __init__(self, name='OrthoSlices', **kw):
##         kw['name'] = name
##         apply( GeometryNode.__init__, (self, 'indexedPolygons'), kw )        

##         from DejaVu.Textured2DArray import textured2DArray
##         self.xsliceGeom = textured2DArray('xslice')
##         self.geoms.append(self.xsliceGeom)
##         self.ysliceGeom = textured2DArray('yslice')        
##         self.geoms.append(self.ysliceGeom)
##         self.zsliceGeom = textured2DArray('zslice')
##         self.geoms.append(self.zsliceGeom)

##         ip = self.inputPortsDescr
##         ip.append({'datatype': 'Grid3D', 'name': 'grid'})
##         ip.append({'datatype': 'string', 'name': 'xaxis'})
##         ip.append({'datatype': 'string', 'name': 'yaxis'})
##         ip.append({'datatype': 'string', 'name': 'zaxis'})
##         ip.append({'datatype': 'int', 'name': 'slicex'})
##         ip.append({'datatype': 'int', 'name': 'slicey'})
##         ip.append({'datatype': 'int', 'name': 'slicez'})
##         ip.append({'datatype': 'ColorMapType', 'name': 'colorMap'})

##         self.widgetDescr['xaxis'] = {
##             'class': 'NECheckButton', 'initialValue': 0, 
##             'master': 'node',
##             'widgetGridCfg': {'column': 0, 'labelSide': 'top', 'row': 0},
##             'labelCfg': {'text': 'axis'},
##             }

##         self.widgetDescr['slicex'] = {
##             'class':'NEThumbWheel', 'width':60, 'height':30, 'type':'int',
##             'min':0, 'showLabel':1, 'oneTurn':10, 'master': 'node',
##             'widgetGridCfg': {'column': 1, 'labelSide': 'top', 'row': 0},
##             'labelCfg':{'text':'sliceNumber:'},
##             }

##         self.widgetDescr['yaxis'] = {
##             'class': 'NECheckButton', 'initialValue': 0, 
##             'master': 'node',
##             'widgetGridCfg': {'column': 0, 'row': 1},
##             }

##         self.widgetDescr['slicey'] = {
##             'class':'NEThumbWheel', 'width':60, 'height':30, 'type':'int',
##             'min':0, 'showLabel':1, 'oneTurn':10, 'master': 'node',
##             'widgetGridCfg': {'column': 1, 'row': 1},
##             }

##         self.widgetDescr['zaxis'] = {
##             'class': 'NECheckButton', 'initialValue': 1, 
##             'master': 'node',
##             'widgetGridCfg': {'column': 0, 'row': 2},
##             }

##         self.widgetDescr['slicez'] = {
##             'class':'NEThumbWheel', 'width':60, 'height':30, 'type':'int',
##             'min':0, 'showLabel':1, 'oneTurn':10, 'master': 'node',
##             'widgetGridCfg': {'column': 1, 'row': 2},
##             }

## ##         self.widgetDescr['sliceNumber'] = {
## ##             'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'int',
## ##             'min':0, 'showLabel':1, 'oneTurn':10, 'master': 'node',
## ##             'labelCfg':{'text':'sliceNumber:'},
## ##             }

## ##         self.widgetDescr['axis'] = {
## ##             'initialValue': 'z', 'fixedChoices': 1, 'autoList': False,
## ##             'choices': ('x','y','z'), 'master': 'node',
## ##             'widgetGridCfg': {'column': 1, 'labelSide': 'left', 'row': 0},
## ##             'labelCfg': {'text': 'axis'},
## ##             'entryfield_entry_width':4,
## ##             'class': 'NEComboBox'}

##         self.widgetDescr['colorMap'] = {
##             'class':'NEColorMap', 'mini':0.0, 'maxi':255.0,
##             'labelCfg':{'text':''}, }

##         self.widgetDescr['name']['choices'] = ['slice']
##         self.widgetDescr['name']['initialValue'] = 'slice'

##         self.rearrangePorts()
                
##         code = """def doit(self, grid, xaxis, yaxis, zaxis, slicex, slicey, slicez, colorMap,
## name, instanceMatrices, geomOptions, parent):

##     GeometryNode.doit(self, name, instanceMatrices, geomOptions, parent)

##     p = self.getInputPortByName('grid')
##     if p.hasNewValidData():
##         dims = grid.dimensions[0]
##         w = self.getInputPortByName('slicex').widget
##         if w: w.configure(max=dims[0]-1)
##         w = self.getInputPortByName('slicey').widget
##         if w: w.configure(max=dims[1]-1)
##         w = self.getInputPortByName('slicez').widget
##         if w: w.configure(max=dims[1]-1)

##     if xaxis:
##         data, vertices = grid.get2DOrthoSlice('x', slicex)
##         g = self.xsliceGeom
##         g.Set(visible=True, vertices=vertices, array=data, colormap=colorMap)

##     if yaxis:
##         data, vertices = grid.get2DOrthoSlice('y', slicey)
##         g = self.xsliceGeom
##         g.Set(visible=True, vertices=vertices, array=data, colormap=colorMap)

##     if zaxis:
##         data, vertices = grid.get2DOrthoSlice('z', slicez)
##         g = self.zsliceGeom
##         g.Set(visible=True, vertices=vertices, array=data, colormap=colorMap)

##     if self.xlisceGeom.viewer is None:
##         self.outputData(orthoslices=self.geoms, allGeometries=self.geoms)
## """
##         self.configure(function=code)

##     def appendGeometry(self, name):
##         return 1 # num of appended geoms


class Grid3DTo2D(NetworkNode):
    """Project the grid data along one of the axis.

Input Ports
    grid: Grid3D Volume object
    axis: string  in ['x', 'y', 'z']
    
Output Ports
    projection: 2D array of values
"""
    def __init__(self, name='ArrayOp', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        ip = self.inputPortsDescr
        ip.append({'datatype': 'Grid3D', 'name': 'grid'})
        ip.append({'datatype': 'string', 'name': 'axis'})

        self.widgetDescr['axis'] = {
            'initialValue': 'z', 'fixedChoices': 1, 'autoList': False,
            'choices': ('x','y','z'), 'master': 'node',
            'widgetGridCfg': {'column': 1, 'labelSide': 'left', 'row': 0},
            'labelCfg': {'text': 'axis'},
            'entryfield_entry_width':4,
            'class': 'NEComboBox'}

        op = self.outputPortsDescr
        op.append({'datatype': '2Darray', 'name': 'projection'})

        code = """def doit(self, grid, axis):
    import numpy

    axisInt = ['x', 'y', 'z'].index(axis)
    proj = data = numpy.sum(grid.data, axisInt)
    self.outputData(projection=proj)
"""
        self.configure(function=code)



class SetOrigin(NetworkNode):
    """Set the grid's origin attribute to a sequence of 3 floats. These
number are given in fractional coordinates

Input Ports
    grid: Grid3D Volume object to be sampled
    origin: sequence of 3 floating point values in fractional coord.
    
Output Ports
    grid: Grid3D with new origin
"""

    def __init__(self, name='SetOrigin', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='None', name='origin')
        
        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        
        code = """def doit(self, grid, origin):
    assert len(origin)==3
    assert type(origin[0])==float
    assert type(origin[1])==float
    assert type(origin[2])==float
    grid.origin = origin
    self.outputData(grid=grid)
"""
        if code: self.setFunction(code)


class SetStepSize(NetworkNode):
    """Scales the stepSize

Input Ports
    grid: Grid3D Volume object to be sampled
    stepSize: sequence of 3 floating point values providing the length of a
              voxel in the 3 x,y and z in angstroms
    
Output Ports
    grid: Grid3D Volume with scaled stepSize
"""

    def __init__(self, name='StepSize', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='None', name='stepSize')
        
        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        
        code = """def doit(self, grid, stepSize):
    assert len(stepSize)==3
    assert type(stepSize[0])==float
    assert type(stepSize[1])==float
    assert type(stepSize[2])==float
    grid.stepSize = stepSize
    self.outputData(grid=grid)
"""
        if code: self.setFunction(code)


class Center(NetworkNode):
    """Center a grid ona user specified point

Input Ports
    grid: Grid3D Volume object to be centered
    center: 3-D point
    
Output Ports
    grid: same grid as incomming on bu with origin modified such that the
          Grid3D's center is on the user specified point
"""

    def __init__(self, name='ScaleGrid', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='None', name='center')
        self.widgetDescr['center'] = {
            'class':'NEVectEntry',
            'initialValue':[0.,0.,0.],
            'widgetGridCfg':{'labelSide':'top'},
            'labelCfg':{'text':'center point'},
            'master':'node'
            }
        
        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        
        code = """def doit(self, grid, center):
    ocenter = grid.centerPoint()
    grid.origin[0] += center[0]-ocenter[0]
    grid.origin[1] += center[1]-ocenter[1]
    grid.origin[2] += center[2]-ocenter[2]
    self.outputData(grid=grid)
"""
        if code: self.setFunction(code)


class VolumeStats(NetworkNode):
    """Compute simple statistics over volumetric data.
    Computes the min, max, mean and standard deviation
    
Input Ports
    grid: Grid3D object to be sampled
    
Output Ports
    mini: minimum value
    maxi: maximum value
    mean: mean value
    stdDev: standard deviation value
"""

    def __init__(self, name='VolumeStats', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.outputPortsDescr.append(datatype='float', name='mini')
        self.outputPortsDescr.append(datatype='float', name='maxi')
        self.outputPortsDescr.append(datatype='float', name='mean')
        self.outputPortsDescr.append(datatype='float', name='stdDev')
        code = """def doit(self, grid):
    
    mymin, mymax, mymean, mystdev = grid.stats()
    self.outputData(mini=mymin,maxi=mymax,mean=mymean,stdDev=mystdev)
    print("\\nSTATS:")
    print("minimum: ",mymin)
    print("maximum: ",mymax)
    print("mean: ",mymean)
    print("standard deviation: ",mystdev)
"""
        if code: self.setFunction(code)


class TransposeGrid3D(NetworkNode):
    """takes the Volume object and transposes the data array
[[1 2 3]   ->  [[1 4 7]
 [4 5 6]   ->   [2 5 6]
 [7 8 9]]  ->   [3 6 9]]

Input Ports
    grid: Grid3D Volume object to be transposed
    copy: (optional)
          When True, a new Volume will be produced for the transposed
          data, else the data is transposed within the original Volume.

Output Ports
    grid: Grid3D object
"""

    def __init__(self, name='NumericToGrid', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['copy'] = {'class':'NECheckButton', 'master':'node',
            'initialValue':0,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'create new grid:'},
            }
        
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='boolean', name='copy')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        
        code = """def doit(self, grid, copy):
    art = numpy.ascontiguousarray(numpy.transpose(grid.data), grid.data.dtype.char)
    if copy is False:
        grid.data = art
        grid.dimensions = art.shape
        grid.stepSize = grid.stepSize[::-1]
        newgrid = grid
    else:
        newgrid = grid.__class__( art, grid.origin, grid.stepSize[::-1],
                                  grid.header)

    self.outputPorts[0].setDataType(grid)
    self.outputData(grid=newgrid)
"""
        if code: self.setFunction(code)


class Orthogonalize(NetworkNode):
    """Create an orthogonal grid for non-orthogonal volumetric data

Input Ports
    grid: Grid3D Volume object

Output Ports
    grid: orthogonal Grid3D Volume object
"""

    def __init__(self, name='Orthog', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.inputPortsDescr.append(datatype='Grid3D', name='grid')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')

        code = """def doit(self, grid):
    if grid.crystal is None:
        self.outputPorts[0].setDataType(grid)
        self.outputData(grid=grid)
    else:
        # find grid dimensions in real space
        pt1 = grid.origin
        dims = grid.data.shape
        pt2 = [pt1[0]+(grid.stepSize[0]*(dims[0]-1)),
               pt1[1]+(grid.stepSize[1]*(dims[1]-1)),
               pt1[2]+(grid.stepSize[2]*(dims[2]-1))]
        coords = (pt1, pt2)

        ptList=((pt2[0],pt2[1],pt1[2]),
                (pt1[0],pt2[1],pt1[2]),
                (pt1[0],pt1[1],pt1[2]),
                (pt2[0],pt1[1],pt1[2]),
                (pt2[0],pt2[1],pt2[2]),
                (pt1[0],pt2[1],pt2[2]),
                (pt1[0],pt1[1],pt2[2]),
                (pt2[0],pt1[1],pt2[2]))
        coords = grid.crystal.toCartesian(ptList)
        mini = coords[0].copy()
        maxi = coords[0].copy()
        for i in range(1,8):
            for j in (0,1,2):
                if coords[i][j]<mini[j]:
                    mini[j] = coords[i][j]
                if coords[i][j]>maxi[j]:
                    maxi[j] = coords[i][j]

        realdims = [0,0,0]
        fracdims = [0,0,0]
        stepsize = grid.getStepSizeReal()
        origin = grid.getOriginReal()
        for i in (0,1,2):
            realdims[i] = maxi[i]-mini[i]
            fracdims[i] = int(realdims[i]/stepsize[i])+2

        data = numpy.zeros( fracdims, grid.data.dtype.char )
        tocart = grid.crystal.toCartesian
        # 1/2 step size real
        sx2,sy2,sz2 = stepsize[0]*.5, stepsize[1]*.5, stepsize[2]*.5
        # real step size
        sxr,syr,szr = 1./stepsize[0],1./stepsize[1],1./stepsize[2]
        # fractioanl step size
        sxf,syf,szf = grid.stepSize
        # offset is new_origin - old_origin + 1/2 voxel
        offx,offy,offz = [ mini[0]-origin[0]+sx2, mini[1]-origin[1]+sy2,
                           mini[2]-origin[2]+sz2]
        source = grid.data
        for i in range(grid.dimensions[0]):
            for j in range(grid.dimensions[1]):
                for k in range(grid.dimensions[2]):
                    # real coordinate of point inside box
                    rx,ry,rz = tocart((i*sxf,j*syf,k*szf))
                    # add origin offset and divide by real step size
                    ix = int( ( offx + rx) * sxr )
                    iy = int( ( offy + ry) * syr )
                    iz = int( ( offz + rz) * szr )
                    #print ix, iy, iz
                    data[ix][iy][iz] = source[i][j][k]

        h={}
        ngrid = grid.__class__( data, mini, stepsize, h, None)
        
        self.outputPorts[0].setDataType(grid)
        self.outputData(grid=ngrid)
"""
        if code: self.setFunction(code)






class RegionBox(NetworkNode):
    """Situates a 3D box within the grid boundaries of a volume,
for quick bounding of octants or halves.
Quadrant numbering ascribes to the traditional numbering system
used in describing graphs.

Inputs Ports
    grid: Grid3D Volume object

Output Ports
    geom: 3D box placed in the desired position
"""
    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)

    def __init__(self, name='Place Box', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='string', name='placement')
        ip.append(datatype='Grid3D', name='grid')

        self.widgetDescr['placement'] = {
            'class': 'NEComboBox', 'master':'node',
            'choices':['No Box','FrontI', 'FrontII', 'FrontIII', 'FrontIV',
                       'BackI','BackII','BackIII','BackIV',
                       'Front Half','Back Half','Right Half','Left Half'],
            'initialValue':'FrontI',
            'entryfield_entry_width':10,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'placement:'},
        }


        self.outputPortsDescr.append(datatype='geom', name='geom')
        self.bb = G.IndexedPolylines('regionBox')

        code = """def doit(self, placement, grid):
    ori = grid.origin
    dims = grid.data.shape
    if placement=='No Box': pt1=ori
        
    elif placement=='BackIII' or placement=='Back Half' or placement=='Left Half':
        pt1 = ori

    elif placement=='BackIV' or placement=='Right Half':
        pt1 = [ori[0]+(0.5*grid.stepSize[0]*(dims[0]-1)),
               ori[1],
               ori[2]]

    elif placement=='BackII':
        pt1 = [ori[0],
               ori[1]+(0.5*grid.stepSize[1]*(dims[1]-1)),
               ori[2]]

    elif placement=='FrontIII' or placement == 'Front Half':
        pt1 = [ori[0],
               ori[1],
               ori[2]+(0.5*grid.stepSize[2]*(dims[2]-1))]

    elif placement=='FrontII':
        pt1 = [ori[0],
               ori[1]+(0.5*grid.stepSize[1]*(dims[1]-1)),
               ori[2]+(0.5*grid.stepSize[2]*(dims[2]-1))]

    elif placement=='BackI':
        pt1 = [ori[0]+(0.5*grid.stepSize[0]*(dims[0]-1)),
               ori[1]+(0.5*grid.stepSize[1]*(dims[1]-1)),
               ori[2]]

    elif placement=='FrontIV':
        pt1 = [ori[0]+(0.5*grid.stepSize[0]*(dims[0]-1)),
               ori[1],
               ori[2]+(0.5*grid.stepSize[2]*(dims[2]-1))]

    elif placement=='FrontI':
        pt1 = [ori[0]+(0.5*grid.stepSize[0]*(dims[0]-1)),
               ori[1]+(0.5*grid.stepSize[1]*(dims[1]-1)),
               ori[2]+(0.5*grid.stepSize[2]*(dims[2]-1))]


    if placement=='No Box': pt2=ori
    elif placement=='Front Half' or placement=='Back Half':
        pt2 = [pt1[0]+(grid.stepSize[0]*(dims[0]-1)),
               pt1[1]+(grid.stepSize[1]*(dims[1]-1)),
               pt1[2]+(0.5*grid.stepSize[2]*(dims[2]-1))]

    elif placement=='Right Half' or placement=='Left Half':
        pt2 = [pt1[0]+(0.5*grid.stepSize[0]*(dims[0]-1)),
               pt1[1]+(grid.stepSize[1]*(dims[1]-1)),
               pt1[2]+(grid.stepSize[2]*(dims[2]-1))]
               
    else:
        pt2 = [pt1[0]+(0.5*grid.stepSize[0]*(dims[0]-1)),
               pt1[1]+(0.5*grid.stepSize[1]*(dims[1]-1)),
               pt1[2]+(0.5*grid.stepSize[2]*(dims[2]-1))]

    set_box(self.bb, pt1, pt2, grid.crystal)
    self.outputData(geom=self.bb)
"""
        if code: self.setFunction(code)



class ReadBinary(NetworkNode):
    """Parse a binary volume data file

Input Ports
    filename: filename of the file to parse
    dims:     3-tuples (nx,ny,nz)
    dtype:    datatype ('int', float')
    swap:     True of False to swap or not the bytes
    
Output Ports
    grid:   Grid3D Volume object
"""

    def __init__(self, name='Read Binary 3D file', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['dims'] = {'class':'NEEntry',
            'labelGridCfg':{'sticky':'we'}, 'master':'node',
            'labelCfg':{'text':'dims (nx,ny,nz):'},
            }
        
        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'title':'browse files', 'master':'node',
            'filetypes':[('all', '*')],
            'labelCfg':{'text':'file:'},
            'width':10
            }
        
        self.widgetDescr['dtype'] = {
            'class': 'NEComboBox', 'master':'node',
            'choices':['double', 'float', 'int', 'uint', 'short', 'ushort',
                       'uchar'],
            'initialValue':'float',
            'entryfield_entry_width':16,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'datatype:'},
            }
        
        self.widgetDescr['byteorder'] = {
            'class': 'NEComboBox', 'master':'node',
            'choices':['None', 'native =', 'native @', 'little-endian',
                       'big-endian', 'network'],
            'initialValue':'None',
            'entryfield_entry_width':16,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'byteorder:'},
            }
        
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='None', name='dims')
        self.inputPortsDescr.append(datatype='string', name='dtype')
        self.inputPortsDescr.append(datatype='string', name='byteorder')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = DelphiReaderBin()
        
        code = """def doit(self, filename, dims, dtype, byteorder):
    if not filename:
        return

    if dims=='':
        return
    
    import types
    if type(dims)==str:
        dims = eval(dims)
    assert len(dims)==3
    size = dims[0]*dims[1]*dims[2]

    # read file
    f = open(filename, 'rb')
    data = f.read()
    f.close()

    if byteorder=='native @': swapc = '@'
    elif byteorder=='native =': swapc = '='
    elif byteorder=='little-endian': swapc = '>'
    elif byteorder=='big-endian': swapc = '<'
    elif byteorder=='network': swapc = '!'
    else: swapc = ''

    import numpy
    if dtype=='double':
        dtypec='d'
        ntype=numpy.float64
    elif dtype=='float':
        dtypec='f'
        ntype=numpy.float32
    elif dtype=='int':
        dtypec='i'
        ntype=numpy.int32
    elif dtype=='uint':
        dtypec='I'
        ntype=numpy.int32
    elif dtype=='short':
        dtypec='h'
        ntype=numpy.int16
    elif dtype=='ushort':
        dtypec='H'
        ntype=numpy.int16
    elif dtype=='uchar':
        dtypec=''
        ntype=numpy.uint8

    import struct
    values = struct.unpack('%1s%d%1s'%(swapc,size,dtypec), data)
    
    values = numpy.array(values, ntype)
    values.shape = dims

    gtype = ArrayTypeToGrid[values.dtype]
    grid = gtype(values, [0.,0.,0.], [1.,1.,1.], {'title':'from %s'%filename})
    self.outputPorts[0].setDataType(gtype)
    self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)



class ReadDelphiBin(NetworkNode):
    """Parse a binary Delphi file

Input Ports
    filename: filename of the file to parse

Output Ports
    grid:   Grid3DF object
"""

    def __init__(self, name='Read Delphi bin', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('phi','*.phi'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.inputPortsDescr.append(datatype='string', name='filename')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = DelphiReaderBin()
        
        code = """def doit(self, filename):
    if not filename:
        return
    grid = self.reader.read(filename)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


class ReadUHBDAscii(NetworkNode):
    """Parse a UHBD file in ASCII format

Input Ports
    filename: filename of the file to parse

Output Ports
    grid:   Grid3DF object
"""

    def __init__(self, name='Read UHBD ASCII', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('UHBD ASCII files','*.uhbd'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.inputPortsDescr.append(datatype='string', name='filename')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = UHBDReaderASCII()
        
        code = """def doit(self, filename):
    if not filename:
        return
    grid = self.reader.read(filename)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)



class ReadMRCfile(NetworkNode):
    """Parse an MRC file.

Input Ports
    filename: filename of the file to parse

Output Ports
    grid:   Grid3D Volume object
"""

    def __init__(self, name='Read MRC', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('MRC files','*.mrc'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.inputPortsDescr.append(datatype='string', name='filename')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadMRC()
        
        code = """def doit(self, filename):
    if not filename:
        return
    grid = self.reader.read(filename)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


class ReadCCP4file(NetworkNode):
    """Parse a CCP4 file.

Input Ports
    filename: filename of the file to parse
    normalize: boolean, check to normalize the data
    
Output Ports
    data: the resulting 3D table
    header: the complete header as a dictionary
    origin: the lower left corner of the data (3-tuple)
    step:   the grid step size (3-tuple)
"""

    def __init__(self, name='Read CCP4', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('CCP4 files','*.map'),('CCP4 files','*.ccp4'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.widgetDescr['normalize'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1,  'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'normalize:'},
            }
        
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadCCP4()
        
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename, normalize=normalize)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


class ReadSPIDERfile(NetworkNode):
    """Parse a SPIDER file.

Input Ports
    filename: filename of the file to parse
    normalize: boolean, check to normalize the data
    
Output Ports
    data: the resulting 3D table
    header: the complete header as a dictionary
    origin: the lower left corner of the data (3-tuple)
    step:   the grid step size (3-tuple)
"""

    def __init__(self, name='Read SPIDER', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('SPIDER files','*.spi'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.widgetDescr['normalize'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1,  'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'normalize:'},
            }
        
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadSPIDER()
        
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename, normalize=normalize)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


class ReadCNSfile(NetworkNode):
    """Parse a CNS/XPLOR formatted file.

Input Ports
    filename: filename of the file to parse
    normalize: boolean, check to normalize the data
    
Output Ports
    data: the resulting 3D table
    header: the complete header as a dictionary
    origin: the lower left corner of the data (3-tuple)
    step:   the grid step size (3-tuple)
"""

    def __init__(self, name='Read CNS/XPLOR', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('CNS files','*.cns'),
                         ('XPLOR files','*.xplor'),
                         ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.widgetDescr['normalize'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1,  'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'normalize:'},
            }
        
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadCNS()
        
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename, normalize=normalize)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)

class ReadGRDfile(NetworkNode):
    """Parse a GRD formatted file.

Input Ports
    filename: filename of the file to parse
    normalize: boolean, check to normalize the data
    
Output Ports
    data: the resulting 3D table
    header: the complete header as a dictionary
    origin: the lower left corner of the data (3-tuple)
    step:   the grid step size (3-tuple)
"""

    def __init__(self, name='Read GRD', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('GRD files','*.grd'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.widgetDescr['normalize'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1,  'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'normalize:'},
            }
        
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadGRD()
        
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename, normalize=normalize)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


class ReadEMfile(NetworkNode):
    """Parse an EM formatted file.
(This format is used at the MPI for Biochemistry, Munich, for electron
microscopy 3-D reconstructions)

Input Ports
    filename: filename of the file to parse
    normalize: boolean, check to normalize the data
    
Output Ports
    data: the resulting 3D table
    header: the complete header as a dictionary
    origin: the lower left corner of the data (3-tuple)
    step:   the grid step size (3-tuple)
"""

    def __init__(self, name='Read EM', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('EM files','*'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        
        self.inputPortsDescr.append(datatype='string', name='filename')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadEM()
        
        code = """def doit(self, filename):
    if not filename:
        return
    grid = self.reader.read(filename)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


class ReadBRIXfile(NetworkNode):
    """Parse a BRIX file.

Input Ports
    filename: filename of the file to parse
    normalize: boolean, check to normalize the data
    
Output Ports
    data: the resulting 3D table
    header: the complete header as a dictionary
    origin: the lower left corner of the data (3-tuple)
    step:   the grid step size (3-tuple)
"""

    def __init__(self, name='Read BRIX', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('BRIX files','*.brix'),
                         ('DSN6 files','*.dsn6'),
                         ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.widgetDescr['normalize'] = {
            'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1,  'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'normalize:'},
            }
        
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadBRIX()
        
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename, normalize=normalize)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)

from wewos.volcore.IO.dxReader import ReadDX

class ReadDXfile(NetworkNode):
    """Parse an DX (data explorer) volume data file.

Input Ports
    filename: filename of the file to parse
    
Output Ports
    grid:   the resulting Grid3DF object
"""

    def __init__(self, name='Read MRC', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('Data Explorer files','*.dx'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3DF', name='grid')
        self.reader = ReadDX()
        
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename, normalize)
    if grid:
        self.outputData(grid=grid)
\n"""
            
        if code: self.setFunction(code)


class ReadFLDBinaryNode(NetworkNode):
    """Reads AVS/Express Field binary data
    http://help.avs.com/Express/doc/help/books/dv/dvfdtype.html.

Input Ports
    filename: filename of the file to parse
    
Output Ports
    grid:   the resulting Grid3D object
"""

    def __init__(self, name='Read FLD Binary', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('','*.fld'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3DF', name='grid')
        self.reader = ReadFLDBinary()
            
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename)
    if grid:
        self.outputPortByName['grid'].setDataType(grid)
        self.outputData(grid=grid)
\n"""
            
        if code: self.setFunction(code)
    
class ReadRawivfile(NetworkNode):
    """Parse a rawiv binary file.

Input Ports
    filename: filename of the file to parse
    
Output Ports
    grid:   the resulting Grid3D table
"""

    def __init__(self, name='Read MRC', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('Raw Data Files','*.rawiv'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='boolean', required=False, name='normalize', defaultValue=True)

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadRawiv()
        
        code = """def doit(self, filename, normalize):
    if not filename:
        return
    grid = self.reader.read(filename)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)


#from wewos.volcore.IO.volWriters import WriteRawiv
class WriteRawiv(NetworkNode):
    """Write volumetric data into .rawiv file.

Input Ports
    grid:     Grid3DF or  GridGrid3DUC Volume object
    filename: name of the file 

"""
    def __init__(self, name='Read MRC', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        wd = self.widgetDescr
        
        wd['filename'] = {'class':'NEEntry',
                          'labelGridCfg':{'sticky':'we'}, 'master':'node',
                          'labelCfg':{'text':'filename:'},
                          'initialValue': "output.rawiv",
                          'width':15
                          }
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='string', name='filename', required=False, defaultValue='output.rawiv')

        from wewos.volcore.IO.volWriters import WriteRawiv
        self.wr = WriteRawiv()
        
        code = """def doit(self, grid, filename):
        if grid:
            dims = grid.dimensions
            origin = grid.origin
            stepSize = grid.stepSize
            data = grid.data
            self.wr.write_file(filename, data, dims, stepSize, origin)
"""
            
        if code: self.setFunction(code)

class ReadAutoGridfile(NetworkNode):
    """Parse an AutoGrid file.

Input Ports
    filename: filename of the file to parse
    
Output Ports
    grid:   the resulting Grid3DUC table
"""

    def __init__(self, name='Read AutoGrid Map', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
            'master':'node', 'title':'browse files',
            'filetypes':[('AutoGrid files','*.fld'), ('all', '*')],
            'labelCfg':{'text':'file:'}, 'width':10 }
        self.inputPortsDescr.append(datatype='string', name='filename')

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.reader = ReadAutoGrid()    
        code = """def doit(self, filename):
    if not filename:
        return
    grid = self.reader.read(filename)
    if grid:
        self.outputData(grid=grid)
"""
            
        if code: self.setFunction(code)



class TriInterp(NetworkNode):
    """Determine the set of points on a volume surface based on
points from a performed trilienar interpolation

Input Ports
    grid: volume object onto which points will be calculated
    points: Points used for interpolation onto the volume object
    
Output Ports
    data: the values of the points located on the volume
"""

    def __init__(self, name='TriInterp', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='grid')
        ip.append(datatype='coordinates3D', name='points')

        op = self.outputPortsDescr
        op.append(datatype='list', name='data')
        
        code = """def doit(self, grid, points):
    values = []
    import numpy

    origin = numpy.array(grid.origin, numpy.float32)
    stepSize = numpy.array(grid.stepSize, numpy.float32)

    invstep = ( 1./stepSize[0], 1./stepSize[1], 1./stepSize[2] )

    if grid.crystal:
        points = grid.crystal.toFractional(vert)

    values = trilinterp(points, grid.data, invstep, origin)
    
    self.outputData(data=values)
"""
            
        if code: self.setFunction(code)



class Isocontour(NetworkNode):
    """Isocontours a Grid3D Volume object to a level specified
by the user.  By default this value is set to 1.0

Input Ports
    grid3D: grid3d Volume object to be isocontoured
    value: value at which to contour the volume object

Output Ports
    coords: Nx3 values of the 3D coordinates of the contour
    indices: nested lists of the indices (1 tuple per polygon)
    normals: normal vectors at each vertex
   """

    
    def __init__(self, name='UT-Isocontour', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        self.data = None
        self.verbosity = 0
        
        #self.readOnly = 1
        code = """def doit(self, grid3D, isovalue, calculatesignatures, verbosity):
    from UTpackages.UTisocontour import isocontour
    if verbosity is not None and verbosity!=self.verbosity:
        isocontour.setVerboseLevel(verbosity)
        self.verbosity = verbosity
        #return

    data = grid3D.data
    if self.inputPortByName['grid3D'].hasNewValidData():
        origin = numpy.array(grid3D.origin).astype('f')
        stepsize = numpy.array(grid3D.stepSize).astype('f')
        # add 1 dimension for time steps amd 1 for multiple variables
        if data.dtype.char!=numpy.float32:
            print('converting from ', data.dtype.char)
            data = data.astype('f')#numpy.float32)

        self.newgrid3D = numpy.ascontiguousarray(numpy.reshape( numpy.transpose(data),
                                          (1, 1)+tuple(data.shape) ), data.dtype.char)
        # destroy the ConDataset structure
        if self.data:
            isocontour.delDatasetReg(self.data)
            
        self.data = isocontour.newDatasetRegFloat3D(\
            self.newgrid3D, origin, stepsize)

        w = self.inputPortByName['isovalue'].widget
        if w and grid3D is not None:
            mymin, mymax, mymean, mystdev = grid3D.stats()
            if (isinstance(mymin, numpy.ndarray)) and (mymin.shape == () ):
                mymin = mymin[0]
            if (isinstance(mymax, numpy.ndarray)) and (mymax.shape == () ):
                mymax = mymax[0]
            w.widget.setMin(mymin)
            w.widget.setMax(mymax)
            #print 'isovalue in doit():', isovalue
            if (isovalue < mymin) or (isovalue > mymax):
                isovalue = mymean
                w.widget.set( isovalue )                    
                warnings.warn('%s: isovalue was outside data range, isovalue is now set to the mean'%self.name)
            if data.size <= 4000000:
                self.calculateSignatures()

    if self.data:
        isoc = isocontour.getContour3d(self.data, 0, 0, isovalue,
                                       isocontour.NO_COLOR_VARIABLE)

        vert = numpy.zeros((isoc.nvert,3)).astype('f')
        norm = numpy.zeros((isoc.nvert,3)).astype('f')
        col = numpy.zeros((isoc.nvert)).astype('f')
        tri = numpy.zeros((isoc.ntri,3)).astype('i')
        isocontour.getContour3dData(isoc, vert, norm, col, tri, 0)

        if grid3D.crystal:
            vert = grid3D.crystal.toCartesian(vert)
            
        self.outputData(coords=vert, indices=tri, normals=norm)
        #self.outputData(colors=c)
"""

        self.setFunction(code)

        # Widgets
        self.widgetDescr['isovalue'] = {
            'class':'NEContourSpectrum', 
            'master':'ParamPanel',
            'showLabel':1, 
            'type':'float',
            'initialValue':9.e99,
            'labelCfg':{'text':'isovalue:'},
            }
        
        self.widgetDescr['calculatesignatures'] = {
            'class': 'NEButton',
            'master': 'ParamPanel',
            'text': 'Calculate signatures',
            'command': self.calculateSignatures,
            'labelGridCfg': {'sticky':'we'}, 
            }

        self.widgetDescr['verbosity'] = {
            'class':'NEThumbWheel', 
            'master':'ParamPanel',
            'width':60, 
            'height':20, 
            'type':'int',
            'min':0,
            'showLabel':1, 
            'oneTurn':5,
            'labelCfg':{'text':'verbosity:'},
            }

        # Input Ports
        self.inputPortsDescr.append(datatype='Grid3D', name='grid3D')
        self.inputPortsDescr.append(datatype='float', name='isovalue')
        self.inputPortsDescr.append(datatype='boolean', name='calculatesignatures')
        self.inputPortsDescr.append(datatype='int', required=False, name='verbosity')

        # Output Ports
        self.outputPortsDescr.append(datatype='coordinates3D', name='coords')
        self.outputPortsDescr.append(datatype='faceIndices', name='indices')
        self.outputPortsDescr.append(datatype='normals3D', name='normals')

        # self.outputPortsDescr.append(name='colors', datatype='colors')


    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)


    def calculateSignatures(self):
        #print "calculateSignatures"
        w = self.inputPortByName['isovalue'].widget
        grid3D = self.inputPortByName['grid3D']
        if w and grid3D is not None:
            if self.data is not None:
                sig = [self.data.getSignature(0, 0, 0),
                self.data.getSignature(0, 0, 1),
                self.data.getSignature(0, 0, 2),
                self.data.getSignature(0, 0, 3)]
                w.widget.setSignatures(sig)
            else:
                warnings.warn(""" %s required data to calculate signatures, run the network first"""%self.name)


class MapGrid(NetworkNode):
    """Allows user to change the map the data in a Grid3D object to a
specified data type, to a certain range of values, and also enables the user to
pad the volume to make dimension powers of 2

Input Ports
    grid:    Grid3D object to be mapped
    minimum: minimum value in the resulting Grid (optional)
    maximum: maximum value in the resulting Grid (optional)
    dataype: type of output Array (optional). can be:
              'None', 'double', 'float', 'int', 'short', 'uchar'
              numpy.float64, numpy.float,
              numpy.float32, numpy.float16,
              numpy.float8, numpy.float0,
              numpy.int32, numpy.int,
              numpy.int16,
              numpy.int0, numpy.int8
             
    powOf2:  when set to 1 the dimensions of the produced
             array will be powers of 2 (boolean, optional)

Output Ports
    grid:    a new Grid 3D object
"""

    def __init__(self, name='MapGrid', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        wd = self.widgetDescr
        wd['datatype'] = {
            'class': 'NEComboBox', 'master':'ParamPanel',
            'choices':['None', 'double', 'float', 'int', 'short', 'uchar'],
            'initialValue':'None',
            'entryfield_entry_width':16,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'datatype:'},
            }
        
        wd['src_min'] = {'class':'NEEntry',
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'src_min:'},
            }
        wd['src_max'] = {'class':'NEEntry',
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'src_max:'},
            }
        wd['dst_min'] = {'class':'NEEntry',
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'dst_min:'},
            }
        wd['dst_max'] = {'class':'NEEntry',
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'dst_max:'},
            }
        wd['mapping'] = {
            'class': 'NEComboBox', 'master':'ParamPanel',
            'choices':['linear', 'log'],
            'initialValue':'linear',
            'entryfield_entry_width':16,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'mapping:'},
        }
        wd['powerOf2'] = {'class':'NECheckButton', 'master':'ParamPanel',
            'initialValue':1,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'make power of 2:'},
            }

        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='grid')
        ip.append(datatype='string', required=False, name='datatype')
        ip.append(datatype='None', required=False, name='src_min')
        ip.append(datatype='None', required=False, name='src_max')
        ip.append(datatype='None', required=False, name='dst_min')
        ip.append(datatype='None', required=False, name='dst_max')
        ip.append(datatype='string', required=False, name='mapping')
        ip.append(datatype='boolean', required=False, name='powerOf2')

        op = self.outputPortsDescr
        op.append(datatype='Grid3D', name='grid')

        # create mapper object
        from wewos.volcore.Operators.MapData import MapGridData
        self.mapper = MapGridData()
        
        code = """def doit(self, grid, datatype, src_min, src_max, dst_min, dst_max, mapping, powerOf2):
    kw = {}

    if datatype.lower()!='none':
        if datatype=='double':
            datatype=numpy.float64
        elif datatype=='float':
            datatype=numpy.float32
        elif datatype=='int':
            datatype=numpy.int32
        elif datatype=='short':
            datatype=numpy.int16
        elif datatype=='uchar':
            datatype=numpy.uint8
        else:
            try:
                datatype = getattr(numpy, datatype)
            except AttributeError:
                raise ValueError('Bad datatype')
    else:
        datatype=None

    if datatype is not None and datatype!=grid.data.dtype.char:
        kw['datatype'] = datatype

    if src_min=='':
        mini = numpy.minimum.reduce
        src_min = mini(mini(mini(grid.data)))
        w = self.inputPorts[2].widget
        if w:
            w.set(str(src_min)[:6], run=0)

    if src_max=='': 
        maxi = numpy.maximum.reduce
        src_max = maxi(maxi(maxi(grid.data)))
        w = self.inputPorts[3].widget
        if w:
            w.set(str(src_max)[:6], run=0)

    if dst_min=='':
        if datatype in [numpy.uint8, numpy.int16, numpy.int32]:
            dst_min = 0
        elif datatype in [numpy.float32, numpy.float64]:
            dst_min = 0.
        w = self.inputPorts[4].widget
        if w:
            w.set(str(dst_min), run=0)

    if dst_max=='':
        if datatype in [numpy.uint8, numpy.int16, numpy.int32]:
            dst_max = 255
        elif datatype in [numpy.float32, numpy.float64]:
            dst_max = 255.
        w = self.inputPorts[5].widget
        if w:
            w.set(str(dst_max), run=0)

    if dst_min and dst_max and mapping in['linear', 'log']:
        datamap = {}
        datamap['src_min'] = eval(str(src_min))
        datamap['src_max'] = eval(str(src_max))
        datamap['dst_min'] = eval(str(dst_min))
        datamap['dst_max'] = eval(str(dst_max))
        datamap['map_type'] = mapping
        kw['datamap'] = datamap

    if powerOf2:
        kw['powerOf2'] = powerOf2

    #print kw
    result = self.mapper(*(grid.data,), **kw)
    gtype = ArrayTypeToGrid[result.dtype]
    #print gtype
    if grid.crystal:
        from wewos.mglmath.crystal import Crystal
        crystal = Crystal( grid.crystal.length, grid.crystal.angles)
    else:
        crystal = None
    newgrid = gtype(result, grid.origin, grid.stepSize, grid.header.copy(),
                    crystal)
    if powerOf2:
        newgrid.dataDims = grid.data.shape[:] # actual data

    self.outputPorts[0].setDataType(gtype)
    self.outputData(grid=newgrid)
"""
            
        if code: self.setFunction(code)






class FillMapWithBox(NetworkNode):
    """Create a copy of a Volume in which the geometric box has been
filled with a given value.  This can be used to create empty octants,
slabs, etc, by filling the box with the value zero.

Input:
    grid3D: Grid3D volume object
    Box: 3D box defining the subvolume to be filled

Output:
    filledMap: resulting Volume object incorporating new fillBox values
"""
    
    def __init__(self, constrkw={}, name='FillMapWithBox', library=None, **kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library

        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['fillValue'] = {
            'class':'NEDial', 'size':50, 'master':'node',
            'showLabel':1, 'oneTurn':1,  'increment':0, 'type':'float',
            'labelCfg':{'text':'fill value:'},
            }

        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='grid3D')
        ip.append(datatype='geom', name='Box')
        ip.append(datatype='float', name='fillValue')

        self.outputPortsDescr.append(datatype='Grid3D', name='filledMap')

        code = """def doit(self, grid3D, Box, fillValue):
    bc1 = [0,0,0]
    bc2 = [0,0,0]
    bside = (Box.xside, Box.yside, Box.zside) 
    # compute indices into large grid array
    shape = grid3D.data.shape
    if 'acell' in grid3D.header:
        stepSize = [ grid3D.header['acell']/grid3D.header['nx'],
                     grid3D.header['bcell']/grid3D.header['ny'],
                     grid3D.header['ccell']/grid3D.header['nz'] ]
    else:
        stepSize = grid3D.stepSize
        
    origin = grid3D.origin
    if grid3D.crystal:
        origin = grid3D.crystal.toCartesian(grid3D.origin)

    for i in (0,1,2):
        bc1[i] = ( Box.center[i] - bside[i]*0.5 - origin[i] ) / stepSize[i]
        bc2[i] = ( Box.center[i] + bside[i]*0.5 - origin[i] ) / stepSize[i]

    for i in (0,1,2):
        bc1[i] = max(0, int(round( bc1[i])))
        bc2[i] = min(shape[i], int(round( bc2[i])))

    # write fillValue into sub array
    data = grid3D.data.copy()
    if fillValue is None:
        fillValue = 0.0
    data[ bc1[0]:bc2[0]+1, bc1[1]:bc2[1]+1, bc1[2]:bc2[2]+1] = fillValue

    crystal= None
    if grid3D.crystal:
        from wewos.mglmath.crystal import Crystal
        crystal = Crystal( grid3D.crystal.length, grid3D.crystal.angles )
    maskedGrid = grid3D.__class__( data, grid3D.origin, grid3D.stepSize, grid3D.header, crystal)

    self.outputData(filledMap=maskedGrid)
"""
        self.setFunction(code)


    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)



class ClipMeshWithMaskNE(NetworkNode):
    """This node takes a mesh i.e. IndexedPolgons and selects all vertices
which fall onto voxel with a true value in a mask grid.  It outputs a new
IndexedPolygons geometry with the triangles for which 3 vertices are selected.
    
Input:
    mesh:   IndexedPolygon geometry to be clipped
    gridMask: grid3d Volume object to be copied and clipped

Output:
    clippedMesh: new and clipped IndexedPolgon geometry
"""
    
    def __init__(self, constrkw={}, name='ClipMeshWithMaskNE', library=None, **kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        self.inputPortsDescr.append(datatype='geom', name='mesh')
        self.inputPortsDescr.append(datatype='Grid3D', name='gridMask')

        self.outputPortsDescr.append(datatype='geom', name='clippedMesh')

        from wewos.volcore.Operators.clip import ClipMeshWithMask
        self.clipper = ClipMeshWithMask()

        code = """def doit(self, mesh, gridMask):
    g = self.clipper.clip(mesh, gridMask)
    self.outputData(clippedMesh=g)
"""
        self.setFunction(code)


    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)


        
class ClipMapWithBox(NetworkNode):
    """Clips a Volume using a 3-D box geometry.
A new copy of the volume data is created using only the data
that is included within the confines of the box.

Input:
    grid3D: grid3d Volume object to be copied and clipped
    Box: 3D box defining subvolume to be clipped

Output:
    clippedMap: grid3D subvolume object 
"""
    
    def __init__(self, constrkw={}, name='ClipMapWithBox', library=None, **kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        self.inputPortsDescr.append(datatype='Grid3D', name='grid3D')
        self.inputPortsDescr.append(datatype='geom', name='Box')
        self.outputPortsDescr.append(datatype='Grid3D', name='clippedMap')

        code = """def doit(self, grid3D, Box):
    #Get the Box indices in relation to the Grid origin
    bc1,bc2=grid3D.overlapWithBox(grid3D,Box)
    shape = grid3D.data.shape

    # round the indices to integers and make sure at least one of the
    # corners of each box face is within the dimensions of the grid
    for i in (0,1,2):
        max_bc = max(0, int(round( bc1[i])))
        min_bc = min(shape[i], int(round( bc2[i])))
        if (max_bc <= 0 and min_bc <= 0) or \
           (max_bc >= shape[i]-1 and min_bc >= shape[i]-1):
            print("box is out of range of data")
            return
        else:
            bc1[i]=max_bc
            bc2[i]=min_bc

    # make copy of data for sub-array
    clippedData = numpy.array( grid3D.data[ bc1[0]:bc2[0]+1,
                                             bc1[1]:bc2[1]+1, bc1[2]:bc2[2]+1],
                                             grid3D.data.dtype.char )
    # compute origin and size (will be different from Box because of rounding)
    origin = [0,0,0]
    for i in (0,1,2):
        origin[i] = grid3D.origin[i] + bc1[i]*grid3D.stepSize[i]

    h = grid3D.header.copy()
##     if h.has_key('ncstart'):
##         h['ncstart'] = round(h['nx']*origin[0])
##         h['nrstart'] = round(h['ny']*origin[1])
##         h['nsstart'] = round(h['nz']*origin[2])
    crystal= None
    if grid3D.crystal:
        from wewos.mglmath.crystal import Crystal
        crystal = Crystal( grid3D.crystal.length, grid3D.crystal.angles )
    maskedGrid = grid3D.__class__( clippedData, origin, grid3D.stepSize, h,
                                   crystal)
## to ouput data on port out0 use
    self.outputData(clippedMap=maskedGrid)
"""
        self.setFunction(code)
    

    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)


# import node's base class library
class LogicOP(NetworkNode):
    """Perform logical operation on the data in 2 Volume objects.
The 2 grids must have the same stepSize.

Input:
    grid1: First grid3D Volume object
    grid2: second grid3D Volume object
    operation: AND, OR, XOR, NOT
    new:  when true, a new Volume object is created, else grid1 is modified

Ouput:
    grid: the resulting Volume object after the operation.
          If a new array is created, it will be of type Grid3DUC
"""
    def __init__(self, constrkw={},  name='Logic OP', library=None, **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='grid1')
        ip.append(datatype='Grid3D', name='grid2')
        ip.append(datatype='string', name='operation')
        ip.append(datatype='boolean', name='new')

        self.widgetDescr['new'] = {
            'class':'NECheckButton', 'master':'node', 'initialValue':0,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'create new grid:'},
            }
        self.widgetDescr['operation'] = {
            'class': 'NEComboBox', 'master':'node',
            'choices':['AND', 'OR', 'XOR', 'NOT'],
            'initialValue':'AND',
            'entryfield_entry_width':5,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'operation:'},
        }

        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        
        code = """def doit(self, grid1, grid2, operation, new):
    bc1, bc2 = grid1.overlapWithGrid(grid2)
    bc3, bc4 = grid2.overlapWithGrid(grid1)
    #print bc1, bc2
    #print bc3, bc4
    if operation=='AND':
        op = numpy.logical_and
    elif operation=='OR':
        op = numpy.logical_or
    elif operation=='XOR':
        op = numpy.logical_xor
    elif operation=='NOT':
        op = numpy.logical_not
    else:
        print('unknown operation', operation)
        return 'STOP'

    #print grid1.data[bc1[0]:bc2[0]+1,bc1[1]:bc2[1]+1,bc1[2]:bc2[2]+1].shape
    #print grid2.data[bc3[0]:bc4[0]+1,bc3[1]:bc4[1]+1,bc3[2]:bc4[2]+1].shape

    ndata = op(grid1.data[bc1[0]:bc2[0]+1,
                          bc1[1]:bc2[1]+1,
                          bc1[2]:bc2[2]+1],
               grid2.data[bc3[0]:bc4[0]+1,
                          bc3[1]:bc4[1]+1,
                          bc3[2]:bc4[2]+1]).astype(grid1.data.dtype.char)
    #print ndata.shape
    if new:
        h = {}
        stepSize = grid1.getStepSizeReal()
        origin = grid1.getOriginReal()
        for i in (0,1,2):
            origin[i] += bc1[i]*stepSize[i]
        from wewos.volcore.Grid3D import Grid3DUC
        nGrid = Grid3DUC( ndata.astype('B'), origin, stepSize, h)
    else:
        grid1.data[bc1[0]:bc2[0]+1, bc1[1]:bc2[1]+1,bc1[2]:bc2[2]+1] = ndata
        nGrid = grid1
    self.outputPorts[0].setDataType(nGrid)
    self.outputData(grid=nGrid)
"""
        self.setFunction(code)


class ThresholdMask(NetworkNode):
    """Create a masking grid of 0 and 1 by comparing voxel values with a
user-defined parameter

Input:
    grid : Grid3D Volume object
    value: threshold value
    operation: greater, equal, not_equal, greater_equal, less, less_equal
        
Ouput:
    mask: the Grid3DUC mask resulting from the operation.
"""
    def __init__(self, constrkw={},  name='ThresholdMask', library=None, **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        # define a function to determine the datatype of the input port
        codeOnConnect = """def onConnect(self,conn):
    # self refers to the port
    # conn is the connection that has been created
    c = conn.port1.originalDatatype
    # if input is of type Grid3DUC, change settings of dial
    if c=='Grid3DUC':
        print("is Grid3DUC")
        self.node.inputPorts[1].widget.configure(type=int,min=0,max=255,oneTurn=50)
"""
        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='grid', afterConnect=codeOnConnect)
        ip.append(datatype='None', name='value')
        ip.append(datatype='string', name='operation')

        # Widgets

        self.widgetDescr['operation'] = {
            'class': 'NEComboBox', 'master':'node',
            'choices':['greater', 'equal', 'not_equal', 'greater_equal',
                       'less', 'less_equal'],
            'initialValue':'greater',
            'fixedChoices':True,            
            'entryfield_entry_width':10,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'operation:'},
        }

        self.widgetDescr['value'] = {
            'class':'NEDial', 'size':50, 'master':'node',
            'showLabel':1, 'oneTurn':1,  'increment':0, 'type':'float',
            'labelCfg':{'text':'threshold value:'},
            }

        self.outputPortsDescr.append(datatype='Grid3DUC', name='mask')
        
        code = """def doit(self, grid, value, operation):
    try:
        operation = getattr(numpy, operation)
    except AttributeError:
        print('ERROR: %s is not a known operation'%operation)
        return 'STOP'

    maskdata = operation(grid.data, value)
    h = grid.header.copy()
    crystal= None
    if grid.crystal:
        from wewos.mglmath.crystal import Crystal
        crystal = Crystal( grid.crystal.length, grid.crystal.angles )
    
    mask = Grid3DUC( maskdata.astype('B'), grid.origin, grid.stepSize, h,
                     crystal)
    self.outputData(mask=mask)
"""
        self.setFunction(code)


class InvertMask(NetworkNode):
    """inverts a 3D mask using a set of spheres
Input:
    maskGrid: Grid3DUC mask of the spheres

Output:
    maskGrid: Grid3DUC mask of the spheres
"""
    def __init__(self, constrkw={},  name='Iverse Mask', library=None, **kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='Grid3DUC', name='maskGrid')

        op = self.outputPortsDescr
        op.append(datatype='Grid3DUC', name='maskGrid')

        code = """def doit(self, maskGrid):
    maskGrid.data = numpy.logical_not(maskGrid.data)
    self.outputData(maskGrid=maskGrid)
"""
        self.setFunction(code)

            
class SpheresMask(NetworkNode):
    """Create a 3D mask using a set of spheres

Input:
    centers: the centers of the sphere used in the mask (list)
    radii: the radii of the spheres to be used (list)
    grid3D: grid3D Volume object

Output:
    maskGrid: Grid3DUC mask of the spheres
"""
    
    def __init__(self, constrkw={},  name='Spheres Mask', library=None, **kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='list', name='centers')
        ip.append(datatype='list', name='radii')
        ip.append(datatype='Grid3D', name='grid3D')

        op = self.outputPortsDescr
        op.append(datatype='Grid3DUC', name='maskGrid')

        code = """def doit(self, centers, radii, grid3D):

    from wewos.volcore.Operators.spheres2Voxels import discreteSpheres
    # stamp spheres on orthogonal grid in cartesian space
    assert len(radii)==len(centers)
    dcpk = discreteSpheres(centers, radii, grid3D.getStepSizeReal(),
                           grid3D.getOriginReal(), grid3D.dimensions)

    if grid3D.crystal:
        from wewos.mglmath.crystal import Crystal
        crystal = Crystal(grid3D.crystal.length, grid3D.crystal.angles)
    else:
        crystal = None

    from wewos.volcore.Grid3D import Grid3DUC
    h = grid3D.header.copy()
    if 'nx' in h:
        h['ncstart'] = round(h['nx']*grid3D.origin[0])
        h['nrstart'] = round(h['ny']*grid3D.origin[1])
        h['nsstart'] = round(h['nz']*grid3D.origin[2])
    else:
        h['ncstart'] = 0
        h['ncstart'] = 0
        h['ncstart'] = 0

    maskGrid = Grid3DUC( dcpk.grid, grid3D.origin, grid3D.stepSize,
                         h, crystal )
    self.outputData(maskGrid=maskGrid)
"""
        self.setFunction(code)
    


class GaussiansMask(NetworkNode):
    """creates a 3D mask in which Gaussians are placed on the
atomic centers of a molecule.  The output mask is of type Grid3DF,
which encodes the density of each voxel as a floating point value.
To convert this output to a mask of type Grid3DUC (type used by the
clipping filters), use the Threshold Mask node.

Input:
    atoms: a set of atomic coordinates

Output:
    maskGrid: Grid3DF mask of the Gaussians
"""
    
    def __init__(self, constrkw={},  name='Gaussian Mask', library=None,**kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='AtomSet', name='atoms')
        ip.append(datatype='int', required=False, name='box', defaultValue=0)
        ip.append(datatype='float', required=False, name='apix', defaultValue=1.)
        ip.append(datatype='float', required=False, name='res', defaultValue=1.5)
        ip.append(datatype='boolean', required=False, name='solv', defaultValue=False)

        wd = self.widgetDescr
        wd['box'] = {
            'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'int',
            'showLabel':1, 'oneTurn':5, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'box size in voxels:'},
            'initialValue':0}
        wd['apix'] = {
            'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'float',
            'showLabel':1, 'oneTurn':5., 'min':0.0, 'lockMin':True,
            'labelCfg':{'text':'voxel size:'},
            'initialValue':1.0}
        wd['res'] = {
            'class':'NEThumbWheel', 'width':60, 'height':20, 'type':'float',
            'showLabel':1, 'oneTurn':5., 'min':0.0, 'lockMin':True,
            'labelCfg':{'text':'Gaussian 1/2 width:'},
            'initialValue':1.5}
        wd['solv'] = {
            'class':'NECheckButton', 'initialValue':0,
            'labelGridCfg':{'sticky':'we'},
            'labelCfg':{'text':'solvate:'},
            }
            
        op = self.outputPortsDescr
        op.append(datatype='Grid3DF', name='maskGrid')

        code = """def doit(self, atoms, box, apix, res, solv):
    from wewos.volcore.Operators.blurSpheres import blurSpheres
    mol, sel = atoms_of(atoms)
    elist, totmass = get_charge_mass(sel)
    volarr, origin, s = blurSpheres(sel.getCoords().tolist(), elist, totmass,
                                    box, apix, res, solv)

    h = {}
    maskGrid = Grid3DF( volarr, origin, (s,s,s), h)
    maskGrid.normalize()
    h['amin'], h['amax'],h['amean'],h['arms']= maskGrid.stats()
    self.outputData(maskGrid=maskGrid)
"""
        self.setFunction(code)


    def beforeAddingToNetwork(self, net):
        # loading library molkitlib
        importMolKitLib(net)

class UTBlurSpheres(NetworkNode):
    """creates a 3D mask in which Gaussians are placed on the
sphere centers.  The output mask is of type Grid3DF,
which encodes the density of each voxel as a floating point value.
To convert this output to a mask of type Grid3DUC (type used by the
clipping filters), use the Threshold Mask node.

Input:
    coords: a set of 3D coordinates
    radii: one or a list of floating point radii
    Xdim, Ydim Zdim: volume dimensions
    blobbyness: default is -2.344 (has to be less than 0)

Output:
    maskGrid: Grid3DF mask of the Gaussians
"""
    
    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)

    
    def __init__(self, constrkw={},  name='Gaussian Mask', library=None,**kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='coordinates3D', name='coords')
        ip.append(datatype='float(>0)', name='radii')
        ip.append(datatype='int', name='Xdim')
        ip.append(datatype='int', name='Ydim')
        ip.append(datatype='int', name='Zdim')
        ip.append(datatype='float', name='blobbyness')

        wd = self.widgetDescr
        width = 70
        height = 20
        wd['Xdim'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'int', 'continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'X dimension:'},  'master':'node',
            'initialValue':64}
        wd['Ydim'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'int', 'continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'Y dimension:'}, 'master':'node',
            'initialValue':64}
        wd['Zdim'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'int','continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'Z dimension:'},  'master':'node',
            'initialValue':64}

        wd['blobbyness'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'continuous':False, 'type':'float','precision':4,
            'showLabel':1, 'oneTurn':1., 'max':-0.001, 'lockMax':True,
            'labelCfg':{'text':'blobbyness:'},  'master':'node',
            'initialValue':-2.344}

            
        op = self.outputPortsDescr
        op.append(datatype='Grid3DF', name='maskGrid')
        self.data = None

        code = """def doit(self, coords, radii, Xdim, Ydim, Zdim, blobbyness):

    if type(radii)==float:
        radii = [radii]*len(coords)
    volarr, origin, span = blur.generateBlurmap(
        coords, radii, [Xdim, Ydim, Zdim], blobbyness)
    volarr.shape = (Zdim, Ydim, Xdim)
    volarr = numpy.ascontiguousarray(numpy.transpose(volarr), 'f')
    self.data = volarr
    h = {}
    maskGrid = Grid3DF( volarr, origin, span , h)
    #maskGrid.normalize()
    h['amin'], h['amax'],h['amean'],h['arms']= maskGrid.stats()
    self.outputData(maskGrid=maskGrid)
"""
        self.setFunction(code)

class UTblurSpheres(NetworkNode):
    """creates a 3D mask in which Gaussians are placed on the
spheres centers.  The output mask is of type Grid3DF,
which encodes the density of each voxel as a floating point value.

Input:
    coords: a list of (X,Y,Z) coordinates
    radii : can be one value or a list of values 
    blobbyness: default is -2.344 (has to be less than 0)
    Xres, Yres, Zres: 3D grid resolution
    switch:  0 - use resolution, 1 - use volume dimensions to create a volume
    Xdim, Ydim Zdim: volume dimensions

Output:
    maskGrid: Grid3DF mask of the Gaussians
"""
    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)
        
    def __init__(self, constrkw={},  name='UT-BlurSpheres(1)', library=None,**kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='coordinates3D', name='coords')
        #ip.append(datatype='list', name='radius')
        ip.append(datatype='None', name='radius')
        ip.append(datatype='float', name='blobbyness')
        self.inputPortsDescr.append(datatype='boolean', name='oneRes')
        ip.append(datatype='float', name='resX')
        ip.append(datatype='float', name='resY', required=False, defaultValue=0)
        ip.append(datatype='float', name='resZ', required=False, defaultValue=0)
        self.inputPortsDescr.append(datatype='boolean', name='switch', defaultValue=0)
        ip.append(datatype='string', name='dims', required=False)

        wd = self.widgetDescr
        width = 70
        width1 = 15
        height = 20
        wd['blobbyness'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'continuous':False, 'type':'float','precision':4,
            'showLabel':1, 'oneTurn':1, 'max':-0.001, 'lockMax':True,
            'labelCfg':{'text':'blobbyness:'},  'master':'ParamPanel',
            'widgetGridCfg':{'sticky':'we', 'labelSide':'left', 'row':0,
                             'columnspan':2, 'column':0},
            'initialValue':-2.344}
        wd['oneRes'] = {
            'class':'NECheckButton', 'master':'ParamPanel', 'initialValue':1,
            'labelGridCfg':{'sticky':'we'}, 'labelCfg':{'text':'use Xres only:'} }
        
        wd['resX'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'float', 'continuous':False,
            'showLabel':1, 'oneTurn':3, 'min':0.0, 'lockMin':True,
            'labelCfg':{'text':'X res  (Xdim=   )       '},  'master':'ParamPanel',
            'widgetGridCfg':{'sticky':'we', 'labelSide':'right'},
            'initialValue':0.5}

        wd['resY'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'float', 'continuous':False,
            'showLabel':1, 'oneTurn':3, 'min':0.0, 'lockMin':True,
            'labelCfg':{'text':'Y res  (Ydim=   )       '}, 'master':'ParamPanel',
            'widgetGridCfg':{'sticky':'we', 'labelSide':'right'},
            'initialValue':0.0}
        
        wd['resZ'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'float','continuous':False,
            'showLabel':1, 'oneTurn':3, 'min':0.0, 'lockMin':True,
            'labelCfg':{'text':'Z res  (Zdim=   )       '},  'master': 'ParamPanel',
            'widgetGridCfg':{'sticky':'we', 'labelSide':'right'},
            'initialValue':0.0}
        
        wd['switch'] = {
            'class':'NECheckButton', 'master':'ParamPanel', 'initialValue':0,
            'labelGridCfg':{'sticky':'we'}, 'labelCfg':{'text':'use volume dims:'},
            'command': self.usedims_cb}
                    
        wd['dims'] = {
            'class':'NEEntry', 'labelGridCfg':{'sticky':'we'},
            'master': 'ParamPanel', 'labelCfg':{'text':'Xdim, Ydim, Zdim:'}, 'width':width1,
            'widgetGridCfg':{'sticky':'we', 'labelSide':'left'} }
            
        op = self.outputPortsDescr
        op.append(datatype='Grid3DF', name='maskGrid')
        self.data = None

        code = """def doit(self, coords, radius, blobbyness, oneRes, resX, resY, resZ, switch, dims):

        try:
            len(radius)
            islist = True
        except TypeError:
            islist = False
        if islist:
            assert len(radius)==len(coords)
        else:
            radius = (numpy.ones(len(coords))*radius).astype('f')
        print('radius is list -', islist)

        wxres = self.getInputPortByName('resX').widget
        wyres = self.getInputPortByName('resY').widget
        wzres = self.getInputPortByName('resZ').widget
        if switch:
            if dims:
                dimensions = dims.split(',')
                assert len(dimensions) == 3
                Xdim = int(dimensions[0])
                Ydim = int(dimensions[1])
                Zdim = int(dimensions[2])
            else:
               Xdim , Ydim, Zdim = (64, 64,64)
            
        else:
            if resY == 0 or oneRes:
                resY = resX
                wyres.set(resY, run=0)
            if resZ == 0 or oneRes:
                resZ = resX
                wzres.set(resZ, run=0)
            assert resX !=0 and resY != 0 and resZ != 0
            minb, maxb = blur.getBoundingBox(coords, radius, blobbyness)
            Xdim = int(round( (maxb[0] - minb[0])/resX + 1))
            Ydim = int(round( (maxb[1] - minb[1])/resY + 1))
            Zdim = int(round( (maxb[2] - minb[2])/resZ + 1))

        wxres.configure(labelCfg= {'text':'X res  (Xdim='+str(Xdim)+')       '})
        wyres.configure(labelCfg= {'text':'Y res  (Ydim='+str(Ydim)+')       '})
        wzres.configure(labelCfg= {'text':'Z res  (Zdim='+str(Zdim)+')       '})
        #print blobbyness, Xdim, Ydim, Zdim
        #print coords[:5]
        #print radius[:5]
        volarr, origin, span = blur.generateBlurmap(coords, radius, [Xdim, Ydim, Zdim], blobbyness)
        if switch:
            wxres.set(span[0], run=0)
            wyres.set(span[1], run=0)
            wzres.set(span[2], run=0)
        volarr.shape = (Zdim, Ydim, Xdim)
        volarr = numpy.ascontiguousarray(numpy.transpose(volarr), 'f')
        self.data = volarr
        h = {}
        maskGrid = Grid3DF( volarr, origin, span , h)
        #maskGrid.normalize()
        h['amin'], h['amax'],h['amean'],h['arms']= maskGrid.stats()
        self.outputData(maskGrid=maskGrid)
"""
        self.setFunction(code)


    def usedims_cb (self):
        #print "usedims_cb" 
        val = self.getInputPortByName('switch').widget.get()
        entry = self.getInputPortByName('dims').widget 
        if val:
            entry.configure(state='normal')
            entry.set("64, 64, 64", run =0)
        else:
            entry.set("", run =0)
            entry.configure(state='disabled')

        
class UTBlurring(NetworkNode):
    """creates a 3D mask in which Gaussians are placed on the
atomic centers of a molecule.  The output mask is of type Grid3DF,
which encodes the density of each voxel as a floating point value.
To convert this output to a mask of type Grid3DUC (type used by the
clipping filters), use the Threshold Mask node.

Input:
    molFrag: molecular fragments
    Xdim, Ydim Zdim: volume dimensions
    blobbyness: default is -2.344 (has to be less than 0)
    padding: size of the padding around the molecule (float)
Output:
    maskGrid: Grid3DF mask of the Gaussians
"""
    
    def beforeAddingToNetwork(self, net):
        # import molkitlib
        importMolKitLib(net)
    
    def __init__(self, constrkw={},  name='UT-blur', library=None,**kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='AtomSet', name='molFrag')
        ip.append(datatype='int', name='Xdim')
        ip.append(datatype='int', name='Ydim')
        ip.append(datatype='int', name='Zdim')
        ip.append(datatype='float', name='padding')
        ip.append(datatype='float', name='blobbyness')


        wd = self.widgetDescr
        width = 70
        height = 20
        wd['Xdim'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'int', 'continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'X dimension:'},  'master':'node',
            'initialValue':64}
        wd['Ydim'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'int', 'continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'Y dimension:'}, 'master':'node',
            'initialValue':64}
        wd['Zdim'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'int','continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'Z dimension:'},  'master':'node',
            'initialValue':64}
        wd['padding'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'float','continuous':False, 'precision':1,
            'showLabel':1, 'oneTurn':10, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'padding:'},  'master':'node',
            'initialValue':0.0}

        wd['blobbyness'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'continuous':False, 'type':'float','precision':4,
            'showLabel':1, 'oneTurn':1., 'max':-0.001, 'lockMax':True,
            'labelCfg':{'text':'blobbyness:'},  'master':'node',
            'initialValue':-2.344}

            
        op = self.outputPortsDescr
        op.append(datatype='Grid3DF', name='maskGrid')
        self.data = None

        code = """def doit(self, molFrag, Xdim, Ydim, Zdim, padding, blobbyness):

    mol, sel = atoms_of(molFrag)
    coords = sel.getCoords().tolist()
    radii = radii_of(mol, sel).tolist()
##     names = []
##     for atom in atoms:
##         names.append(atom.name+':'+atom.parent.type)
##     radii = blur.getRadii(names)
    #print radii[:10]
    volarr, origin, span = blur.generateBlurmap(coords, radii, [Xdim, Ydim, Zdim], blobbyness, padding = padding)
    volarr.shape = (Zdim, Ydim, Xdim)
    volarr = numpy.ascontiguousarray(numpy.transpose(volarr), 'f')
    self.data = volarr
    h = {}
    maskGrid = Grid3DF( volarr, origin, span , h)
    #maskGrid.normalize()
    h['amin'], h['amax'],h['amean'],h['arms']= maskGrid.stats()
    self.outputData(maskGrid=maskGrid)
"""
        self.setFunction(code)

class UTsdf(NetworkNode):
    """Generates the Signed Distance Function fields.
    Input:
      geom - an Indexed Polygons geometry;
      size - resolution of the volume grid (has to be a power of 2);
      flipNormals - if set to 1, the orientation of the input surface
                    is checked and the normals of the triangles are flipped
                    to a uniform side;
      insideNeg - if set to 1, the sign inside the volume is set to negative
                  and outside - to positive.
    Output: Grid3DF.
    """
    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)

    
    def __init__(self, constrkw={},  name='UTsdf', library=None,**kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype= 'geom', name='geom')
        ip.append(datatype='int', name='size')
        ip.append(datatype='boolean', name='flipNormals')
        ip.append(datatype='boolean', name='insideNeg')
        ip.append(datatype = 'float', name = 'xpad')
        ip.append(datatype = 'float', name = 'ypad')
        ip.append(datatype = 'float', name = 'zpad')

        wd = self.widgetDescr
        width = 70
        height = 20
##         wd['size'] = {
##             'class':'NEThumbWheel', 'width':width, 'height':height,
##             'type':'int', 'continuous':False,
##             'showLabel':1, 'oneTurn':100, 'min':0, 'max':256, 'lockMin':True,
##             'labelCfg':{'text':'grid size'},  'master':'node',
##             'initialValue':64}
        wd['size'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':['16', '32', '64','128', '256'],
            'fixedChoices':True, 'initialValue':'32',
            'entryfield_entry_width':5, 'labelGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'grid size:'},'widgetGridCfg':{'sticky':'w'},
            }

        wd['flipNormals'] = {
            'class':'NECheckButton', 'master':'node',
            'initialValue':0,  'labelGridCfg':{'sticky':'w'},
            'labelCfg':{'text':'flip normals:'},'widgetGridCfg':{'sticky':'w'},
            }
        wd['insideNeg'] = {
            'class':'NECheckButton', 'master':'node',
            'initialValue':0,  'labelGridCfg':{'sticky':'w'},
            'labelCfg':{'text':"neg inside volume"},'widgetGridCfg':{'sticky':'w'},
            }
        wd['xpad'] = {
            'class':'NEEntry', 'master':'node', 'width':5,
            'labelCfg':{'text':'Padding: X', },'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w', 'labelSide':'top', 'row': 7, 'column':0},
            'initialValue':0,
            }
        wd['ypad'] = {
            'class':'NEEntry', 'master':'node', 'width':5,
            'labelCfg':{'text':'Y'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w', 'labelSide':'top', 'row':7, 'column':1},
            'initialValue':0,
            }
        wd['zpad'] = {
            'class':'NEEntry', 'master':'node', 'width':5,
            'labelCfg':{'text':'Z'},'labelGridCfg':{'sticky':'w'},
            'widgetGridCfg':{'sticky':'w', 'labelSide':'top', 'row':7, 'column':2},
            'initialValue':0,
            }

        op = self.outputPortsDescr
        op.append(datatype='Grid3DF', name='sdfGrid')
        self.data = None

        code = """def doit(self, geom, size, flipNormals, insideNeg, xpad, ypad, zpad):

        try:
            len(geom)
            geometry = geom[0]
        except:
            geometry = geom
        size = int(size)
        #from wewos.volcore.Operators.MapData import isPowerOf2
        #ans, power = isPowerOf2(size)
        #if not ans:
        #    size = 2**power
        verts = geometry.vertexSet.vertices.array
        faces = geometry.faceSet.faces.array
        minx, miny, minz = numpy.minimum.reduce(verts)
        maxx, maxy, maxz = numpy.maximum.reduce(verts)
        xpad = float(xpad); ypad = float(ypad); zpad=float(zpad)
        if xpad*2 >= size:
            xpad = size/2 -1
            self.inputPorts[4].widget.set(str(xpad), run=0)
        if ypad*2 >= size:
            ypad = size/2 -1
            self.inputPorts[5].widget.set(str(ypad), run=0)
        if zpad*2 >= size:
            zpad = size/2 -1
            self.inputPorts[6].widget.set(str(zpad), run=0)
        padding = [xpad, xpad, ypad, ypad, zpad,zpad]
        #utsdf.setParameters(size, flipNormals, insideNeg)
        utsdf.setParameters(size, flipNormals, insideNeg, padding)
        datap = utsdf.computeSDF(verts, faces)
        size1 = size +1
        grid_size  = size1*size1*size1
        volarr = utsdf.createNumArr(datap, grid_size)
        volarr.shape = (size1, size1, size1)
        volarr = numpy.ascontiguousarray(numpy.transpose(volarr), 'f')
        self.data = volarr
        h = {}
        #origin = [minx, miny, minz]
        tx = maxx - minx;	ty = maxy - miny;	tz = maxz - minz;
        # compute the origin of data (the expression is from sdf source)
        ox = (0-size/2)*tx/(size-xpad*2)+(tx/2)+minx
        oy = (0-size/2)*ty/(size-ypad*2)+(ty/2)+miny
        oz = (0-size/2)*tz/(size-zpad*2)+(tz/2)+minz
        origin = [ox, oy, oz]
        #scx = tx/size; scy = ty/size; scz = tz/size;
        scx = tx/(size-xpad*2); scy = ty/(size-ypad*2); scz = tz/(size-zpad*2);
        span = [scx, scy,scz]
        sdfGrid = Grid3DF( volarr, origin, span , h)
        #print 'sdf stats:', sdfGrid.stats()
        h['amin'], h['amax'],h['amean'],h['arms']= sdfGrid.stats()
        self.outputData(sdfGrid=sdfGrid)
"""
        self.setFunction(code)


class TSRIsdf(NetworkNode):
    """Generates the Signed Distance Function fields.
    Input:
      geom - an Indexed Polygons geometry;
      gridSize - number of voxels in the padded grid
      padding - around the bounding box of the geom
    Output: Grid3DF.
    """
    def beforeAddingToNetwork(self, net):
        # import vizlib
        importVizLib(net)

    
    def __init__(self, constrkw={},  name='UTsdf', library=None,**kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype= 'geom', name='geom')
        ip.append(datatype='int', name='gridSize')
        ip.append(datatype='float', name='padding')

        wd = self.widgetDescr
        width = 70
        height = 20
        wd['gridSize'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'int', 'continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'max':256, 'lockMin':True,
            'labelCfg':{'text':'grid size'},  'master':'node',
            'initialValue':32}
        wd['padding'] = {
            'class':'NEThumbWheel', 'width':width, 'height':height,
            'type':'float', 'continuous':False,
            'showLabel':1, 'oneTurn':100, 'min':0, 'lockMin':True,
            'labelCfg':{'text':'grid size'},  'master':'node',
            'initialValue':5.}

        op = self.outputPortsDescr
        op.append(datatype='Grid3DF', name='sdfGrid')
        self.data = None

        code = """def doit(self, geom, gridSize, padding):

        try:
            len(geom)
            geometry = geom[0]
        except:
            geometry = geom

        vertices = geometry.getVertices()
        faces = geometry.getFaces()
        vnormals = geometry.getVNormals()

        import numpy
        mini = numpy.minimum.reduce(numpy.array(vertices)) 
        maxi = numpy.maximum.reduce(numpy.array(vertices))
        bboxp = [ mini-padding, maxi+padding ]
        extent = bboxp[1] - bboxp[0]
        nbgpx = nbgpy = nbgpz = gridSize
        stepSize = [extent[0]/(nbgpx-1),
                    extent[1]/(nbgpy-1),
                    extent[2]/(nbgpz-1)]

        from math import sqrt
        def signedDistance(xxx_todo_changeme, bht, vertices, normals):
            (x,y,z) = xxx_todo_changeme
            nb = 0
            cut = 0.
            cutIncr = 2.0
            while nb==0:
                cut += cutIncr
                nb = bht.closePointsDist2((x,y,z), cut, result, dist2 )

            mind = 9999999
            mini= None
            for i in range(nb):
                if dist2[i] < mind:
                    mind = dist2[i]
                    mini = result[i]
            #return mini, sqrt(mind)
            # find the sign
            nx, ny, nz = normals[mini]
            px, py, pz = vertices[mini]
            vx, vy, vz = (x-px, y-py, z-pz)
            dot = (nx*vx + ny*vy + nz*vz)
            if dot > 0:
                return mini, sqrt(mind)
            else:
                return mini, -sqrt(mind)

        # build a bhtree with shape vertices
        from bhtree import bhtreelib
        bht = bhtreelib.BHtree( vertices, None, 10)
        result = numpy.zeros( (len(vertices),) ).astype('i')
        dist2 = numpy.zeros( (len(vertices),) ).astype('f')

        # distance field grid
        df = numpy.zeros( (nbgpx, nbgpy, nbgpz), 'f')

        xo, yo, zo = bboxp[0]
        xm, ym, zm = bboxp[1]
        sx, sy, sz = stepSize
        for ii in range( nbgpx ):
            #print ii
            x = xo + ii*sx
            for jj in range( nbgpy ):
                y = yo + jj*sy
                for kk in range( nbgpz ):
                    z = zo + kk*sz
                    i, d = signedDistance( (x,y,z), bht, vertices, vnormals)
                    df[ii, jj, kk] = d
                    #print x,y,z, vertices[i][0], vertices[i][1], vertices[i][2], d

        #df = numpy.array(numpy.transpose(df)).astype('f')
        h = {'title':'signed distance field'}
        from wewos.volcore.Grid3D import Grid3DF
        sdfGrid = Grid3DF( df, (xo, yo, zo), stepSize, h)

        self.outputData(sdfGrid=sdfGrid)
"""
        self.setFunction(code)


class ClipMap(NetworkNode):
    """Clips a Volume using a 3D mask.
A new copy of the volume is created using only the volume data
that is included within the confines of the mask.

Input:
    datagrid: Grid3D Volume object onto which the mask will be applied
    maskgrid: The mask defining the data to be included in the new grid

Output:
    clippedMap: the resulting Grid3D Volume object
"""
    
    def __init__(self, constrkw = {},  name='MaskMap', library=None, **kw):
        kw['name'] = name
        kw['originalClass'] = NetworkNode
        kw['library'] = library
        NetworkNode.__init__(*(self,), **kw)

        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='dataGrid')
        ip.append(datatype='Grid3DUC', name='maskGrid')

        op = self.outputPortsDescr
        op.append(datatype='Grid3D', name='clippedMap')

        code = """def doit(self, dataGrid, maskGrid):
    import numpy
    zeros = numpy.zeros(dataGrid.dimensions, dataGrid.data.dtype.char)
    clippedData = numpy.where(maskGrid.data, dataGrid.data, zeros)
    if hasattr(dataGrid, 'crystal') and dataGrid.crystal:
        from wewos.mglmath.crystal import Crystal
        crystal = Crystal( dataGrid.crystal.length, dataGrid.crystal.angles)
    else:
        crystal = None
    ## FIXME, we should recompute min, max, mean, rms
    newGrid = dataGrid.__class__(clippedData, dataGrid.origin,
             dataGrid.stepSize, dataGrid.header.copy(), crystal)
    newGrid.normalize()
    self.outputData(clippedMap=newGrid)
"""
        self.setFunction(code)



class WriteCCP4file(NetworkNode):
    """Write a CCP4 file.

Input Ports
    filename: filename of the file to be written
    grid3D: Grid3D Volume object to be written
"""

    def __init__(self, name='Write CCP4', **kw):
        kw['name'] = name

        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['filename'] = {'class':'NEEntryWithFileSaver',
            'master':'node', 'title':'browse files',
            'labelCfg':{'text':'file:'}, 'width':20 }
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.inputPortsDescr.append(datatype='Grid3DF', name='grid')

        self.writer = WriteCCP4()
        
        code = """def doit(self, filename, grid):
    if not filename:
        return
    grid = self.writer.write(filename, grid)
"""
            
        if code: self.setFunction(code)


class MoleculeBBGrid(NetworkNode):
    """Creates a mask using the bounding box of a molecule

Input Ports
    molecFrag: molecular fragment (TreeNodeSet)
    stepSize:  size of a voxel (float)
    padding: size of the padding around the molecule (float)

Output Ports
    MolMask: Grid3DUC mask of the molecule's bounding box
"""

    def __init__(self, name='Write CCP4', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)

        self.widgetDescr['stepSize'] = {
            'class':'NEThumbWheel', 'master':'node', 'initialValue':1.,
            'oneTurn': 1., 'height':30,
            'labelCfg':{'text':'stepSize:'}, 'width':90, 'type':'float' }
        self.widgetDescr['padding'] = {
            'class':'NEThumbWheel', 'master':'node', 'initialValue':5.,
            'oneTurn': 10., 'height':30,
            'labelCfg':{'text':'padding:'}, 'width':90, 'type':'float' }
        self.inputPortsDescr.append(datatype='AtomSet', name='molecFrag')
        self.inputPortsDescr.append(datatype='float', name='stepSize')
        self.inputPortsDescr.append(datatype='float', name='padding')

        self.outputPortsDescr.append(datatype='Grid3DUC', name='grid3D')
        
        code = """def doit(self, molecFrag, stepSize, padding):
    mol, sel = atoms_of(molecFrag)
    radii = radii_of(mol, sel)
    maxr= max(radii)
    coords = sel.getCoords().tolist()
    mini = (min([x[0] for x in coords]), min([x[1] for x in coords]),
            min([x[2] for x in coords]))

    maxi = (max([x[0] for x in coords]), max([x[1] for x in coords]),
            max([x[2] for x in coords]))

    minimum = [mini[i] - maxr - padding for i in [0,1,2]]
    maximum = [maxi[i] + maxr + 1 + padding for i in [0,1,2]]
    dims = [int((maximum[i]-minimum[i])/stepSize)+1 for i in [0,1,2]]

    print('Molecule BB grid has dimensions: ', dims)

    from wewos.volcore.Grid3D import Grid3DUC
    import numpy
    ar = numpy.zeros( dims, numpy.uint8)
    grid = Grid3DUC( ar, minimum, (stepSize,)*3, {} )
    self.outputData(grid3D = grid)
"""
        self.setFunction(code)


    def beforeAddingToNetwork(self, net):
        # import molkitlib
        importMolKitLib(net)

## class ReadTransfFunc(NetworkNode):
##     """
##     """
    
##     def __init__(self, name='ReadTransfFunc', **kw):
##         kw['name'] = name
##         apply( NetworkNode.__init__, (self,), kw )

##         self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
##             'master':'node', 'title':'browse files',
##             'labelCfg':{'text':'file:'}, 'width':10 }

##         ip = self.inputPortsDescr
##         ip.append(datatype='string', name='filename')
        
##         op = self.outputPortsDescr
##         op.append(datatype='None', name='cmap')

##         code = """def doit(self, filename):

##     myfile = open(filename, 'rb' )
##     l = myfile.read(256*4)
##     import numpy
##     byte_map =numpy.fromstring(l,(256*4), numpy.uint8) 
##     byte_map = numpy.reshape(byte_map,(256,4))
##     myfile.close()

##     self.outputData(cmap=byte_map)
## """

##         if code: self.setFunction(code)




## class ReadGAMESSOrbitals(NetworkNode):
##     """Parse a GAMESS Orbitals ascii file.

## Input Ports
##     filename: filename of the file to parse
    
## Output Ports
##     data: the resulting 3D table
##     header: the complete header as a dictionary
##     origin: the lower left corner of the data (3-tuple)
##     step:   the grid step size (3-tuple)
## """

##     def __init__(self, name='Games orbitals', **kw):
##         kw['name'] = name
##         apply( NetworkNode.__init__, (self,), kw)

##         self.widgetDescr['filename'] = {'class':'NEEntryWithFileBrowser',
##             'master':'node', 'title':'browse files',
##             'labelCfg':{'text':'file:'}, 'width':10 }
##         self.inputPortsDescr.append(datatype='string', name='filename')

## 	self.outputPortsDescr.append(datatype='None', name='data')
## 	self.outputPortsDescr.append(datatype='None', name='header')
## 	self.outputPortsDescr.append(datatype='None', name='origin')
## 	self.outputPortsDescr.append(datatype='None', name='step')
## 	self.reader = ReadGamessOrbitals()
        
## 	code = """def doit(self, filename):
##     if not filename:
##         return
##     header, data = self.reader.read(filename)
##     if data:
##         self.outputData(data=data, header=header)
## """
            
##         if code: self.setFunction(code)


import numpy

class UTMesher(NetworkNode):
    """Generates triangular/quadrilaterial meshes for a level set surface,
    interior and exterior tetrahedral/hexahedral meshes with level sets as
    boundary surfaces.
    Input ports:
        -grid3DF: grid3Df Volume object filename, data size should be 
                  either (2^n+1)^3 or (2^n)^3 (in last case volume will be padded to size 2^n+1);
        -filename: input data in .rawiv format (size = (2^n+1)^3);
        -meshtype: one of the following:
            'single' - triangle mesh for a single isosurface;
            'hexa'   - hexahedral mesh;
            'double' - triangle mesh for double isosurface;
            'tetra'  - tetrahedral mesh;
            'quads'  - quadrilateral mesh;
            'tetra2' - interval volume tetrahedral mesh between two isosurfaces;
        -outer_isoval: outer surface isovalue;
        -outer_error: outer surface error tolerance;
        -inner_isoval: inner surface isovalue (for meshtypes 'double' and 'tetra2');
        -inner_error: inner surface error tolerance;
        -outer surface: show only the outer surface of the mesh;
        -crossection: show the crossection of tetra or tetra2. Only X and Z planes are available(parameter panel). 
    Output ports:
        - coords: Nx3 values of the 3D coordinates of the contour;
        - indices: nested lists of the indices (1 tuple per polygon);
    """
    
    def beforeAddingToNetwork(self, net):
        importVizLib(net)

    def __init__(self, name='UT-mesh', **kw):
        kw['name'] = name
        NetworkNode.__init__(*(self,), **kw)
        
        self.widgetDescr['meshtype'] = {
            'class':'NEComboBox', 'master':'node',
            'choices':['single', 'tetra', 'hexa',
                       'quads', 'double', 'tetra2'],
            'entryfield_entry_width':12,
            'initialValue': 'single',
            'widgetGridCfg':{'sticky':'we', 'labelSide':'left','row':2,
                             'columnspan':2},
            'labelCfg':{'text': 'Mesh Type:'},
            }
        self.widgetDescr['outer_isoval'] = {
            'class':'NEThumbWheel', 'initialValue':lbiemesher.DEFAULT_IVAL,
            'master':'node', 'continuous':0, 'precision':3,
            'widgetGridCfg':{'sticky':'we', 'labelSide':'top','row':5},
            'labelCfg':{'text':'Outer Surface: isoval,'},
            'width':90, 'height':15, 
            'type':'float', 'oneTurn':10., 'lockBMin':1, 'min':-10,
            'wheelPad':2 }
        
        self.widgetDescr['outer_error'] = {
            'class':'NEThumbWheel', 'initialValue':lbiemesher.DEFAULT_ERR,
            'master':'node', 'continuous':0, 'precision':4,
            'widgetGridCfg':{'sticky':'we', 'labelSide':'top','row':5,
                             'column':1},
            'labelCfg':{'text':'error tolerance'},
            'width':90, 'height':15, 
            'type':'float', 'oneTurn':10., 'lockBMin':1, 'min':0,
            'wheelPad':2}
        
        self.widgetDescr['inner_isoval'] = {
            'class':'NEThumbWheel',  'master':'node', 'continuous':0,
            'widgetGridCfg':{'sticky':'we', 'labelSide':'top' ,'row':7},
            'initialValue':lbiemesher.DEFAULT_IVAL_IN, 
            'labelCfg':{'text':'Inner Surface: isoval,'},
            'width':90, 'height':15, 'precision':3,
            'type':'float', 'oneTurn':10., 'lockBMin':1, 'min':-10,
            'wheelPad':2}
        
        self.widgetDescr['inner_error'] = {
            'class':'NEThumbWheel', 'master':'node', 'continuous':0,
            'widgetGridCfg':{'sticky':'we', 'labelSide':'top', 'row':7,
                             'column':1},
            'initialValue':lbiemesher.DEFAULT_ERR_IN, 
            'labelCfg':{'text':'error tolerance'}, 'precision':3,
            'width':90, 'height':15, 
            'type':'float', 'oneTurn':10, 'lockBMin':1, 'min':0,
            'wheelPad':2}

        self.widgetDescr['outersurf'] = {'class':'NECheckButton',
                                     'master':'node',
                                     'initialValue':0,
                                     'widgetGridCfg':{'sticky':'we',
                                                      'labelSide':'left',
                                                      #'columnspan':2},
                                                      #'row':8, 'column': 0},
                                                      },
                                     'labelCfg':{'text':'Show outer surface'},
                                     }
        self.widgetDescr['crossection'] = {'class':'NECheckButton',
                                     'master':'node',
                                     'initialValue':0,
                                     'widgetGridCfg':{'sticky':'we',
                                                      'labelSide':'left',
                                                      #'columnspan':2},
                                                      #'row':8, 'column': 1
                                                      },
                                     'labelCfg':{'text':'Show cross-section\n(tetra, tetra2)'},
                                     }
        self.widgetDescr['planeX'] = {
            'class':'NEThumbWheel', 'master':'ParamPanel', 'continuous':0,
            'widgetGridCfg':{'sticky':'we', 'labelSide':'left'},
            'initialValue':0, 'labelCfg':{'text':'plane X'}, 'width':90, 'height':15, 
            'type':'int', 'oneTurn':10, 'lockBMin':1, 'min':0, 'wheelPad':2}
        self.widgetDescr['planeZ'] = {
            'class':'NEThumbWheel', 'master':'ParamPanel', 'continuous':0,
            'widgetGridCfg':{'sticky':'we', 'labelSide':'left'},
            'initialValue':0, 'labelCfg':{'text':'plane Z'}, 'width':90, 'height':15,
            'type':'int', 'oneTurn':10, 'lockBMin':1, 'min':0, 'wheelPad':2}
        

        ip = self.inputPortsDescr
        self.inputPortsDescr.append(datatype='Grid3DF', name='grid3DF')
        #ip.append(datatype='string', name='filename')
        ip.append(datatype='string', name='meshtype')
        ip.append(datatype='float',  name='outer_isoval')
        ip.append(datatype='float',  name='outer_error')
        ip.append(datatype='float',  name='inner_isoval')
        ip.append(datatype='float',  name='inner_error')
        ip.append(datatype='int', name='outersurf', defaultValue=0)
        ip.append(datatype='int', name='crossection', defaultValue=0)
        ip.append(datatype='int', name='planeX', defaultValue=0)
        ip.append(datatype='int', name='planeZ', defaultValue=0)
        
        op = self.outputPortsDescr
        op.append(datatype='coordinates3D', name='coords')
        op.append(datatype='faceIndices', name='indices')
        
        self.file = None
        self.grid = None
        self.mesher = None
        self.meshtype = None
        self.meshtypes = {# triangle mesh for a single level set
            'single': lbiemesher.SINGLE,
            # hexahedral mesh
            'hexa':  lbiemesher.HEXA,
            # triangle mesh for double level sets
            'double':	lbiemesher.DOUBLE,
            #tetrahedral mesh
            'tetra':  lbiemesher.TETRA,
            #quadrilateral mesh
            'quads':	lbiemesher.T_4_H,
            # interval volume tetrahedral mesh
            # between two level sets
            'tetra2': lbiemesher.TETRA2 }
        self.outersurf = 0
        self.crossection = 0
        self.planex = 0
        self.planez = 0
        self.origin = [0,0,0]
        self.stepSize = [1, 1, 1]
        self.outer_isoval = None
        self.outer_error = None
        self.inner_isoval=None
        self.inner_error=None
        

        code= """def doit(self, grid3DF,  meshtype, outer_isoval, outer_error,
inner_isoval, inner_error, outersurf, crossection, planeX, planeZ):
        from itertools import zip_longest as _zip_longest
        update = 0
        #disable the crossection button if mesh type is not tetra or tetra2:
        if meshtype not in ('tetra', 'tetra2'):
            self.getInputPortByName('crossection').widget.widget.configure(state='disabled')
        else:
            self.getInputPortByName('crossection').widget.widget.configure(state='normal')
        if outersurf != self.outersurf:
            self.outersurf = outersurf
            update = 1
        if crossection != self.crossection:
            self.crossection = crossection
            update = 1
        if self.grid != grid3DF:
            data = grid3DF.data
            # dimensions of data should be 2^n or 2^n+1
            header = grid3DF.header
            #print 'grid header: ', header
            dx, dy, dz = data.shape
            res = []
            for d in (dx, dy, dz):
                res.append(self.power2plus1(d))
            p2 , p2plus1 = _zip_longest(res[0], res[1], res[2])
            if False in p2:
                print('Error: unsupported data dimensions: ', (dx, dy,dz))
                return
            dims1 = [dx, dy, dz]
            if False in p2plus1: # the dims are 2^n, need to pad the volume
                                 #so the dims are 2^n+1 
                dims = [dx, dy, dz]
                for i in range(3):
                   if not p2plus1[i]:
                       dims1[i] =  dims1[i] + 1
                newdata = numpy.zeros(dims1, numpy.float32)
                newdata[:dx,:dy,:dz] = data
                data = newdata
            #print 'creating mesher'
            mesher = lbiemesher.LBIE_Mesher()
            #print 'input data...'
            nverts = dims1[0] * dims1[1] * dims1[2]
            ncells = (dims1[0]-1) * (dims1[1]-1) * (dims1[2]-1)
            self.origin = grid3DF.origin
            self.stepSize = grid3DF.stepSize
            data = numpy.ascontiguousarray(numpy.transpose(data), 'f')
            mesher.inputData(data.ravel(), dims1, nverts, ncells)
            maxval = mesher.getVolMax()
            minval = mesher.getVolMin()
            self.getInputPortByName('outer_isoval').widget.configure(max=maxval, min=minval)
            self.getInputPortByName('inner_isoval').widget.configure(max=maxval, min=minval)
            if outer_isoval < minval:
                outer_isoval = minval
            elif outer_isoval >  maxval:
                outer_isoval = maxval
            if inner_isoval is not None:
                if inner_isoval < minval:
                    inner_isoval = minval
                elif inner_isoval >  maxval:
                    inner_isoval = maxval
            # cross section planes:
            wpx = self.getInputPortByName('planeX').widget
            wpx.configure(max=dims1[0])
            if planeX == 0:
                planeX = self.planex = dims1[0]/2 
                wpx.set(planeX, run = 0)
            wpz = self.getInputPortByName('planeZ').widget
            wpz.configure(max=dims1[0])
            if planeZ == 0:
                planeZ = self.planez = dims1[2]/2
                wpz.set(planeZ , run = 0)
            self.grid = grid3DF
            self.meshtype = self.meshtypes[meshtype]
            mesher.setMesh(self.meshtype)
            self.mesher = mesher
            update = 1
        if self.meshtype != self.meshtypes[meshtype]:
            print('setting meshtype:', meshtype)
            self.meshtype = self.meshtypes[meshtype]
            if self.mesher:
                self.mesher.setMesh(self.meshtype)
                update = 1
        if self.planex != planeX:
            self.planex = planeX
            if self.mesher:
                self.mesher.setXCutPlane(planeX)
                update = 1
        if self.planez != planeZ:
            self.planez = planeZ
            if self.mesher:
                self.mesher.setZCutPlane(planeZ)
                update = 1
        if self.outer_isoval != outer_isoval:
            self.outer_isoval = outer_isoval
            self.mesher.isovalueChange(outer_isoval)
            update = 1
        if self.outer_error != outer_error:
            self.outer_error = outer_error
            self.mesher.errorChange(outer_error)
            update = 1
        if meshtype in ['double', 'tetra2']:
            if self.inner_isoval != inner_isoval and inner_isoval is not None:
                self.mesher.isovalueChange_in(inner_isoval)
                self.inner_isoval = inner_isoval
                update = 1
            if self.inner_error != inner_error and inner_error is not None:
                self.mesher.errorChange_in(inner_error)
                self.inner_error = inner_error
                update = 1
        if update:
            vertarr, facearr = self.getOutput(self.meshtype)
            
            #print  'in doit() : verts', len(vertarr), 'faces', len(facearr)
            #self.mesher.displayCutSection()
            self.outputData(coords=vertarr, indices=facearr)
"""
        self.setFunction(code)



    def getOutput(self, meshtype):
        nverts = self.mesher.getNumVerts()
        nfaces = self.mesher.getNumFaces()
        #print "in output: nverts: ", nverts, " nfaces: ", nfaces
        vertarr = numpy.zeros((nverts, 3), "f")
        if meshtype == lbiemesher.SINGLE or meshtype == lbiemesher.DOUBLE :
            facearr = numpy.zeros((nfaces, 3), "i")
            self.mesher.outTriangle(vertarr, facearr)
        elif  meshtype == lbiemesher.TETRA or  meshtype == lbiemesher.TETRA2:
            facearr = numpy.zeros((nfaces*4, 3), "i")
            self.mesher.outTriangle(vertarr, facearr )
        #elif  meshtype == lbiemesher.TETRA or  meshtype == lbiemesher.TETRA2:
        #    facearr = numpy.zeros((nfaces, 4), "i")
        #    self.mesher.outTetra(vertarr, facearr )
        elif meshtype == lbiemesher.HEXA:
            #facearr = numpy.zeros((nfaces, 8), "i")
            #self.mesher.outHexa(vertarr, facearr )
            facearr = numpy.zeros((nfaces*6, 4), "i")
            self.mesher.outQuad(vertarr, facearr )
        elif meshtype == lbiemesher.T_4_H :
            facearr = numpy.zeros((nfaces, 4), "i")
            self.mesher.outQuad(vertarr, facearr )
        if self.crossection and meshtype in (lbiemesher.TETRA, lbiemesher.TETRA2):
            self.outersurf = 0
            self.getInputPortByName('outersurf').widget.set(0, run = 0)
            newfaces, cutoutverts = self.mesher.getSurface(1)
            # newfaces contains faces of the original mesh minus faces of
            # the cutout section
            # cutoutverts is a list of vertices  that form cross section surface
            # vertset = [[x1, y1, z1, d], [x2, y2, z2, d] ,....,[xn, yn, zn, d]]
            # where d indicates whether the vertex can be removed from the list if
            # it is duplicated (d is 0 or 1)
            # [[x1, y1, z1], [x2, y2, z2], [x3, y3, z3]] - first triangle ...
            
            vs, fs = self.removeUnusedVerts(vertarr, newfaces)
            vertset = [x[:3] for x in cutoutverts]
            noremove = [x[3] for x in cutoutverts]
            lenv =  len(vertset)
            if lenv:
                faceset = numpy.arange( lenv) #create faces for vertset
                faceset.shape = (lenv/3 , 3)
                #from DejaVu.utils import RemoveDuplicatedVertices
                vs1, fs1 = self.removeDuplicatedVertices(vertset, faceset, noremove)
                #print "RemoveDuplicatedVertices: oldverts: %d, newverts: %d"%(len(vertset), len(vs1))
                fs2 = self.checkFaces(fs1)
                n = len(vs)
                vs.extend(vs1)
                #print "shapes: fs (%d, %d), fs2(%d, %d)" %(len(fs), len(fs[0]), len(fs2), len(fs2[0]))
                newfs = numpy.concatenate((fs, numpy.array(fs2)+n))
                return self.apply_mat(vs) , newfs
            else:
                return self.apply_mat(vs), fs
        if self.outersurf and meshtype in (lbiemesher.TETRA, lbiemesher.TETRA2, lbiemesher.HEXA):
            newfaces, vertset = self.mesher.getSurface() #vertset should be []
            return self.apply_mat(vertarr), newfaces

        else:
            return self.apply_mat(vertarr), facearr
        
    def apply_mat(self, vertarr):
        mat = numpy.identity(4, 'f')
        stepSize = self.stepSize
        origin = self.origin
        mat[0,0] = stepSize[0]; mat[1,1] = stepSize[1]; mat[2,2] = stepSize[2]
        mat[0,3] = origin[0]; mat[1,3] = origin[1]; mat[2,3] = origin[2] 
        lenv = len(vertarr)
        coordv = numpy.ones(lenv *4, 'f')
        coordv.shape = (lenv, 4)
        coordv[:,:3] = vertarr[:]
        newcoords = numpy.ascontiguousarray(numpy.dot(coordv, numpy.transpose(mat))[:, :3], 'f')
        return newcoords
        
    def removeUnusedVerts(self, vertlist, facelist):
        """ Removes vertices from vertlist that are not in the given list
        of faces. """
        newverts = []
        newfaces = []
        vertdict = {}
        nvert = 0
        for face in facelist:
            nf = []
            for v in face:
                if v not in vertdict:
                    newverts.append(vertlist[v])
                    vertdict[v] = nvert
                    nvert = nvert + 1
                nf.append(vertdict[v])
            newfaces.append(nf)
        return newverts, newfaces

    def removeDuplicatedVertices(self, vertices, faces, noremove = None):
        """Remove duplicated vertices and re-index the polygonal faces such that
        they share vertices
        """
        vl = {}
        vrl = {}
        nvert = 0
        vertList = []

        for i,v in enumerate(vertices):
            key = '%f%f%f'%tuple(v)
            if noremove:
                nd = noremove[i]
            else: nd = 0
            if key not in vl:
                vl[key] = nvert
                vrl[i] = nvert
                nvert +=1
                vertList.append(v)
            else:
                if nd:
                   vrl[i] = nvert
                   nvert +=1
                   vertList.append(v)
                else:
                    vrl[i] = vl[key]

        faceList = []
        for f in faces:
            faceList.append( list(map( lambda x, l=vrl: vrl[x],  f )) )

        return vertList, faceList

    def checkFaces(self, faces):
        """Removes triangular faces that have at list two identical vertices. Removes
        duplicated faces."""
        if len(faces[0]) == 3:
            newfaces = []
            fdict = {}
            count = 0
            for f in faces:
                if f[0] == f[1] or f[0] == f[2]:
                    count = count +1
                    continue
                if f[1] == f[0] or f[1] == f[2]:
                    count = count +1
                    continue
                if tuple(f) not in fdict:
                    newfaces.append(f)
                    fdict[tuple(f)] = True
            #print "in checkFaces oldlen : %d , newlen %d, count %d" % (len(faces), len(newfaces), count)
            return newfaces
        else:
            return faces


    def power2plus1(self, d):
        """ return values of power2plus1(d):
        - [True, True] if d is 2^n+1;
        - [True, False] if d is 2^n;
        - [False, False] in all other cases. """
        i = 0
        res = [False, False]
        while True:
            if d<=(1<<i): break
            i = i+1
        #print "in power2plus1 i=%d"%i
        p2 = 1<<i
        diff  = p2 - d
        if diff == 0:
            res[0] = True
        elif (1<<(i-1))+1 == d:
            res = [True, True]
        return res

    def find_two_surfaces(self, faces):
        from time import time
        t1 = time()
        fdict = {}
        vdict = {}
        Vco = []
        for v in faces[0]:
            Vco.append(v)
        Fco = 1
        # create a dictionary with key - vertex index, value - list of face indices
        #in which the vertex is found
        for i, f in enumerate(faces):
            for v in f:
                if v not in vdict:
                    vdict[v] = [i]
                else:
                    vdict[v].append(i)
            fdict[i] = f

        newfaces1 = []
        newfaces2 = []
        while Fco:
            if len(newfaces1) > len(faces):
                print("Warning: len(newfaces1) > len(faces) ",len(newfaces1), len(faces))  
                return newfaces1, newfaces2
            Fco = 0
            _Vco = []

            # find all vertices that share the same triangles with the vertices in Vco.
            for vert in Vco:
                vfs = vdict[vert]
                for i in vfs:
                    if i in fdict:
                        Fco = Fco+1
                        f= fdict.pop(i)
                        newfaces1.append(f) # add found triangle to the list of triangles of the first surface
                        for v in f:
                            if v != vert:
                                if v not in Vco: 
                                    if v not in _Vco:
                                            _Vco.append(v)
            Vco  = _Vco


        newfaces2 = list(fdict.values())
        t2 = time()
        print("time to find faces : %.2f" % (t2-t1)) 
        return newfaces1, newfaces2 


############################################################################
##    MACROS
############################################################################



    





# ---------------------------------------------------------------------------------------
# WEWoS: helpers and the nodes rewritten for the web page (see the module docstring)
# ---------------------------------------------------------------------------------------

def _utblur():
    """UTpackages.UTblur.blur. Its SWIG wrapper mixes tabs and spaces in some
    Python 3 builds, which Python 3 refuses: it is then loaded with the tabs
    expanded (the compiled _blur module next to it is used unchanged)."""
    try:
        from UTpackages.UTblur import blur
        return blur
    except (TabError, SyntaxError):
        import os
        import sys
        import types
        import UTpackages.UTblur as pkg
        path = os.path.join(os.path.dirname(pkg.__file__), 'blur.py')
        with open(path) as fh:
            src = fh.read().expandtabs(8)
        mod = types.ModuleType('UTpackages.UTblur.blur')
        mod.__file__ = path
        mod.__package__ = 'UTpackages.UTblur'
        exec(compile(src, path, 'exec'), mod.__dict__)
        sys.modules['UTpackages.UTblur.blur'] = mod
        return mod


_CHARGE_MASS = {'H': (1.0, 1.00794), 'C': (6.0, 12.0107), 'AU': (79.0, 196.96655),
                'N': (7.0, 14.00674), 'O': (8.0, 15.9994), 'P': (15.0, 30.973761),
                'S': (16.0, 32.066), 'W': (18.0, 1.00794 * 2 + 15.9994)}


def get_charge_mass(sel):
    """MolKit.chargeMass.getChargeMass for a MolKit2 selection: the number of
    electrons of each atom (-1 when unknown) and the total mass."""
    elist, totmass = [], 0.0
    for e in sel.getElements():
        c, m = _CHARGE_MASS.get(str(e).upper(), (-1.0, 0.0))
        elist.append(c)
        totmass += m
    return elist, totmass


MAP_FORMATS = ['auto', 'AutoGrid', 'AVS/FLD Binary', 'BRIX/DSN6', 'CCP4', 'CNS/XPLOR',
               'Data Explorer(DX)', 'Delphi', 'GRD', 'MRC', 'Rawiv', 'SPIDER', 'UHBD/GRID']
_EXTENSIONS = [(r'\.mrc$', 'MRC'), (r'\.ccp4*$', 'CCP4'), (r'\.cns$|\.xplo*r*$', 'CNS/XPLOR'),
               (r'\.grd$', 'GRD'), (r'\.fld$', 'AVS/FLD Binary'), (r'\.map$', 'AutoGrid'),
               (r'\.omap$|\.brix$|\.dsn6$|\.dn6$', 'BRIX/DSN6'), (r'\.rawiv$', 'Rawiv'),
               (r'\.d*e*l*phi$', 'Delphi'), (r'\.uhbd$', 'UHBD/GRID'),
               (r'\.dx$', 'Data Explorer(DX)'), (r'\.spi$', 'SPIDER')]


def read_map(filename, fmt='auto', normalize=True):
    """A Grid3D from a map file; the format comes from the file name unless
    given."""
    if fmt in (None, '', 'auto'):
        for pattern, f in _EXTENSIONS:
            if re.search(pattern, filename, re.I):
                fmt = f
                break
        else:
            raise ValueError('cannot tell the format of %s from its name; choose it on '
                             'the format port' % filename)
    from wewos.volcore.IO.dxReader import ReadDX
    readers = {'AutoGrid': ReadAutoGrid, 'BRIX/DSN6': ReadBRIX, 'CCP4': ReadCCP4,
               'CNS/XPLOR': ReadCNS, 'Data Explorer(DX)': ReadDX, 'Delphi': DelphiReaderBin,
               'GRD': ReadGRD, 'MRC': ReadMRC, 'Rawiv': ReadRawiv, 'SPIDER': ReadSPIDER,
               'UHBD/GRID': UHBDReaderASCII, 'AVS/FLD Binary': ReadFLDBinary}
    reader = readers[fmt]()
    try:
        return reader.read(filename, normalize=normalize)
    except TypeError:
        return reader.read(filename)


class ReadAnyMap(NetworkNode):
    """Read a 3D map: AutoGrid, AVS/FLD binary, BRIX/DSN6, CCP4, CNS/XPLOR,
DX, Delphi, GRD, MRC, Rawiv, SPIDER or UHBD. The format is taken from the
file name unless one is chosen on the format port.

Input Ports
    filename: the map file
    format:   'auto' or a format name
    normalize: normalize the values (readers that support it)
Output Ports
    grid: Grid3D object
"""

    def __init__(self, constrkw={}, name='ReadAnyMap', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        wd = self.widgetDescr
        wd['filename'] = {'class': 'NEEntryWithFileBrowser', 'master': 'node',
                          'filetypes': [('maps', '*.map *.fld *.ccp4 *.dx *.grd *.omap *.brix '
                                         '*.dsn6 *.cns *.xplor *.delphi *.phi *.mrc *.rawiv '
                                         '*.spi *.uhbd')],
                          'title': 'read a map', 'labelCfg': {'text': 'file:'}}
        wd['format'] = {'class': 'NEComboBox', 'master': 'ParamPanel', 'choices': MAP_FORMATS,
                        'fixedChoices': True, 'initialValue': 'auto',
                        'labelCfg': {'text': 'format:'}}
        wd['normalize'] = {'class': 'NECheckButton', 'master': 'ParamPanel', 'initialValue': 1,
                           'labelCfg': {'text': 'normalize'}}
        ip = self.inputPortsDescr
        ip.append(datatype='string', name='filename')
        ip.append(datatype='string', name='format', required=False)
        ip.append(datatype='boolean', name='normalize', required=False, defaultValue=True)
        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.setFunction("""def doit(self, filename, format, normalize):
    if not filename:
        return 'Stop'
    grid = read_map(filename, format, bool(normalize))
    if grid:
        self.outputData(grid=grid)
""")


class ReadRawNumpyVol(NetworkNode):
    """Read a 3D numpy array saved with numpy.save (.npy) as a grid.

Input Ports
    filename: the .npy file
    origin:   position of the first grid point
    stepSize: spacing of the grid points along x, y and z
Output Ports
    grid: Grid3DF object
"""

    def __init__(self, constrkw={}, name='ReadRawNumpyVol', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        wd = self.widgetDescr
        wd['filename'] = {'class': 'NEEntryWithFileBrowser', 'master': 'node',
                          'filetypes': [('numpy', '*.npy')], 'labelCfg': {'text': 'file:'}}
        wd['origin'] = {'class': 'NEVectEntry', 'master': 'ParamPanel',
                        'initialValue': [0., 0., 0.], 'labelCfg': {'text': 'origin'}}
        wd['stepSize'] = {'class': 'NEVectEntry', 'master': 'ParamPanel',
                          'initialValue': [1., 1., 1.], 'labelCfg': {'text': 'step size'}}
        ip = self.inputPortsDescr
        ip.append(datatype='string', name='filename')
        ip.append(datatype='None', name='origin', required=False, defaultValue=(0., 0., 0.))
        ip.append(datatype='None', name='stepSize', required=False, defaultValue=(1., 1., 1.))
        self.outputPortsDescr.append(datatype='Grid3D', name='grid')
        self.setFunction("""def doit(self, filename, origin, stepSize):
    import os
    data = numpy.load(filename)
    if data.ndim != 3:
        raise ValueError('%s holds a %dD array, not a 3D one' % (filename, data.ndim))
    grid = Grid3DF(numpy.ascontiguousarray(data, numpy.float32), tuple(origin or (0, 0, 0)),
                   tuple(stepSize or (1, 1, 1)), {'title': os.path.basename(filename)})
    self.outputData(grid=grid)
""")


def _grid_points(grid, ijk):
    """Positions of grid points given as (n, 3) indices (crystal grids are in
    fractional coordinates and are converted)."""
    o = numpy.array(grid.origin, 'f')
    st = numpy.array(grid.stepSize, 'f')
    xyz = o + numpy.asarray(ijk, 'f') * st
    if getattr(grid, 'crystal', None):
        xyz = numpy.array(grid.crystal.toCartesian(xyz), 'f')
    return xyz


class OrthoSlice(GeometryNode):
    """A slice of a grid orthogonal to x, y or z, drawn as a mesh colored by
the values (a color ramp between mini and maxi, the slice's range by
default). Vision drew a texture; 3Dmol has none, so the slice has one
colored vertex per grid point.

Input Ports
    grid:        Grid3D object
    axis:        'x', 'y' or 'z'
    sliceNumber: position along the axis (0 to the number of points - 1)
    ramp:        rgb, rwb, grey or rainbow
    mini, maxi:  values mapped to the ends of the ramp
    opacity:     0 (invisible) to 1
Output Ports
    OrthoSlice: the slice geometry
"""
    geomClass = G.IndexedPolygons
    outName = 'OrthoSlice'

    def __init__(self, name='OrthoSlice', **kw):
        GeometryNode.__init__(self, name, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='Grid3D', name='grid')
        ip.append(datatype='string', name='axis', required=False)
        ip.append(datatype='int', name='sliceNumber', required=False)
        ip.append(datatype='string', name='ramp', required=False)
        ip.append(datatype='float', name='mini', required=False)
        ip.append(datatype='float', name='maxi', required=False)
        ip.append(datatype='float', name='opacity', required=False)
        self.widgetDescr['sliceNumber'] = {'class': 'NEThumbWheel', 'master': 'node',
                                           'type': 'int', 'min': 0, 'oneTurn': 10,
                                           'initialValue': 0, 'labelCfg': {'text': 'slice'}}
        self.widgetDescr['axis'] = {'class': 'NEComboBox', 'master': 'node',
                                    'choices': ['x', 'y', 'z'], 'fixedChoices': True,
                                    'initialValue': 'z', 'labelCfg': {'text': 'axis'}}
        self.widgetDescr['ramp'] = {'class': 'NEComboBox', 'master': 'ParamPanel',
                                    'choices': ['rgb', 'rwb', 'grey', 'rainbow'],
                                    'fixedChoices': True, 'initialValue': 'rgb',
                                    'labelCfg': {'text': 'colors'}}
        self.widgetDescr['opacity'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                       'initialValue': 1.0, 'min': 0., 'max': 1., 'oneTurn': 1.,
                                       'labelCfg': {'text': 'opacity'}}
        self._commonPorts()
        self.setFunction("""def doit(self, grid, axis, sliceNumber, ramp, mini, maxi, opacity, name, instanceMatrices, geomOptions, parent):
    axis = axis or 'z'
    a = 'xyz'.index(axis)
    dims = grid.data.shape
    w = self.inputPortByName['sliceNumber'].widget
    if w is not None and (self.inputPortByName['grid'].hasNewValidData()
                          or self.inputPortByName['axis'].hasNewValidData()):
        w.configure(max=dims[a] - 1)
    k = max(0, min(int(sliceNumber or 0), dims[a] - 1))
    v, f, values = ortho_slice(grid, a, k)
    colors = colormap(values, ramp or 'rgb', mini, maxi)
    self.update({'vertices': v, 'faces': f, 'materials': colors,
                 'opacity': 1.0 if opacity is None else opacity},
                name, instanceMatrices, geomOptions, parent)
""")


def ortho_slice(grid, axis, k):
    """Vertices, triangles and values of the slice of grid at index k along
    axis (0, 1, 2): one vertex per grid point of the slice."""
    data = grid.data
    if axis == 0:
        vals = data[k, :, :]
    elif axis == 1:
        vals = data[:, k, :]
    else:
        vals = data[:, :, k]
    nu, nv = vals.shape
    uu, vv = numpy.meshgrid(numpy.arange(nu), numpy.arange(nv), indexing='ij')
    ijk = numpy.zeros((nu * nv, 3), 'f')
    others = [d for d in (0, 1, 2) if d != axis]
    ijk[:, axis] = k
    ijk[:, others[0]] = uu.ravel()
    ijk[:, others[1]] = vv.ravel()
    verts = _grid_points(grid, ijk)
    idx = numpy.arange(nu * nv).reshape(nu, nv)
    a, b = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel()
    c, d = idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    tris = numpy.vstack([numpy.stack([a, b, c], 1), numpy.stack([a, c, d], 1)]).astype('i')
    return verts, tris, numpy.asarray(vals, 'f').ravel()


def set_box(geom, pt1, pt2, crystal=None):
    """Make geom (IndexedPolylines) the 12 edges of the box with opposite
    corners pt1 and pt2 (fractional coordinates for crystal grids)."""
    v = numpy.array([[x, y, z] for x in (pt1[0], pt2[0]) for y in (pt1[1], pt2[1])
                     for z in (pt1[2], pt2[2])], 'f')
    if crystal:
        v = numpy.array(crystal.toCartesian(v), 'f')
    edges = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    geom.Set(vertices=v, faces=edges)
    return geom


class BoundingBox(GeometryNode):
    """The box around a grid, drawn as 12 lines.

Input Ports
    grid: Grid3D object
Output Ports
    Grid3DBB:    the box geometry
    boundingBox: two opposite corners (orthogonal grids)
"""
    geomClass = G.IndexedPolylines
    outName = 'Grid3DBB'

    def __init__(self, name='Grid3DBB', **kw):
        GeometryNode.__init__(self, name, **kw)
        self.inputPortsDescr.append(datatype='Grid3D', name='grid')
        self.inputPortsDescr.append(datatype='colorfloat3or4(0)', name='colors', required=False)
        self._commonPorts()
        self.outputPortsDescr.append(datatype='None', name='boundingBox')
        self.setFunction("""def doit(self, grid, colors, name, instanceMatrices, geomOptions, parent):
    dims = grid.data.shape
    corners = numpy.array([[i, j, k] for i in (0, dims[0] - 1) for j in (0, dims[1] - 1)
                           for k in (0, dims[2] - 1)], 'f')
    v = _grid_points(grid, corners)
    edges = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    self.update({'vertices': v, 'faces': edges, 'materials': colors},
                name, instanceMatrices, geomOptions, parent)
    self.outputData(boundingBox=(v[0].tolist(), v[7].tolist()))
""")


class UT_Iso(MacroNode):
    """Isocontour a grid and build a mesh: a macro holding UT-Isocontour and
IndexedPolygons. The isovalue (with the contour spectrum) is in this
node's parameter panel."""

    def __init__(self, constrkw={}, name='UTIsoMac', **kw):
        kw['name'] = name
        MacroNode.__init__(self, **kw)

    def afterAddingToNetwork(self):
        MacroNode.afterAddingToNetwork(self)
        from wewos.libs.viz3d import IndexedPolygons, vizlib
        net = self.macroNetwork
        saved = net.runOnNewData.value
        net.runOnNewData.value = False
        try:
            iso = Isocontour(name='UT-Isocontour', library=vollib)
            net.addNode(iso, 201, 92)
            w = iso.inputPortByName['isovalue'].widget
            w.configure(master='macroParamPanel', labelCfg={'text': 'Iso. value:'})
            w.set(1.0, run=False)
            poly = IndexedPolygons(name='IndexedPolygons', library=vizlib)
            net.addNode(poly, 201, 163)
            net.connectNodes(iso, poly, 'normals', 'vnormals', doNotSchedule=True)
            net.connectNodes(iso, poly, 'indices', 'indices', doNotSchedule=True)
            net.connectNodes(iso, poly, 'coords', 'coords', doNotSchedule=True)
            net.connectNodes(net.ipNode, iso, 0, 'grid3D', doNotSchedule=True)
            net.connectNodes(poly, net.opNode, 'indexedPolygons', 0, doNotSchedule=True)
            net.ipNode.move(201, 20)
            net.opNode.move(201, 250)
        finally:
            net.runOnNewData.value = saved


class CoarseMolSurf(MacroNode):
    """A coarse molecular surface: the atoms are blurred as Gaussians onto a
grid (UT Blur), the grid is isocontoured and a mesh is built. The
blobbyness, grid size and isovalue are in this node's parameter panel.
Its second input takes instance matrices (symmetry copies of the surface,
e.g. from Assembly Matrices or Icosahedral1).
(Vision's version also decimated the surface with QSlim, which is not
available here.)"""

    def __init__(self, constrkw={}, name='CoarseMolSurf', **kw):
        kw['name'] = name
        MacroNode.__init__(self, **kw)

    def afterAddingToNetwork(self):
        MacroNode.afterAddingToNetwork(self)
        from wewos.libs.viz3d import IndexedPolygons, vizlib
        net = self.macroNetwork
        saved = net.runOnNewData.value
        net.runOnNewData.value = False
        try:
            bl = UTBlurring(name='UT Blur', library=vollib)
            net.addNode(bl, 201, 80)
            for p in ('Xdim', 'Ydim', 'Zdim', 'padding', 'blobbyness'):
                bl.inputPortByName[p].widget.configure(master='macroParamPanel')
            bl.inputPortByName['blobbyness'].widget.set(-0.3, run=False)
            bl.inputPortByName['padding'].widget.set(2.0, run=False)
            iso = Isocontour(name='UT-Isocontour', library=vollib)
            net.addNode(iso, 201, 200)
            w = iso.inputPortByName['isovalue'].widget
            w.configure(master='macroParamPanel', labelCfg={'text': 'Iso. value:'})
            w.set(1.0, run=False)
            poly = IndexedPolygons(name='IndexedPolygons', library=vizlib)
            net.addNode(poly, 201, 300)
            net.connectNodes(net.ipNode, bl, 0, 'molFrag', doNotSchedule=True)
            net.connectNodes(net.ipNode, poly, 0, 'instanceMatrices', doNotSchedule=True)
            net.connectNodes(bl, iso, 'maskGrid', 'grid3D', doNotSchedule=True)
            for a, b in (('coords', 'coords'), ('indices', 'indices'), ('normals', 'vnormals')):
                net.connectNodes(iso, poly, a, b, doNotSchedule=True)
            net.connectNodes(poly, net.opNode, 'indexedPolygons', 0, doNotSchedule=True)
            net.ipNode.move(201, 10)
            net.opNode.move(201, 400)
        finally:
            net.runOnNewData.value = saved



vollib = NodeLibrary('Volume', '#B9A27A',
                     doc='3D grids: read, transform, mask, blur, slice, isocontour')



#vollib.addNode(TestVolume, 'TestVolume', 'Test')

vollib.addNode(ReadMRCfile, 'ReadMRC', 'Input')
vollib.addNode(ReadCCP4file, 'ReadCCP4', 'Input')
vollib.addNode(ReadSPIDERfile, 'ReadSPIDER', 'Input')
vollib.addNode(ReadCNSfile, 'ReadCNS', 'Input')
vollib.addNode(ReadGRDfile, 'ReadGRD', 'Input')
vollib.addNode(ReadEMfile, 'ReadEM', 'Input')
vollib.addNode(ReadBRIXfile, 'ReadBRIX', 'Input')
vollib.addNode(ReadDXfile, 'ReadDX', 'Input')
vollib.addNode(ReadRawivfile, 'ReadBinaryRawiv', 'Input')
vollib.addNode(ReadAutoGridfile, 'ReadAutoGrid', 'Input')
#vollib.addNode(ReadGAMESSOrbitals, 'Read GAMESS Orbitals', 'Input')
vollib.addNode(ReadUHBDAscii, 'Read UHBD ASCII', 'Input')
vollib.addNode(ReadDelphiBin, 'Read Delphi Binary', 'Input')
vollib.addNode(ReadBinary, 'Read Binary', 'Input')
vollib.addNode(Grid3DNode, 'New Grid', 'Input')
vollib.addNode(ReadFLDBinaryNode, 'ReadBinaryFLD ', 'Input')

vollib.addNode(WriteCCP4file, 'Write CCP4', 'Output')

#vollib.addNode(ReadTransfFunc, 'Read Transf. Func.', 'Input')

vollib.addNode(VolumeStats, 'VolumeStats', 'Mapper')
vollib.addNode(Orthogonalize, 'Orthogonalize', 'Mapper')
vollib.addNode(SpheresMask, 'Spheres Mask', 'Mapper')
vollib.addNode(InvertMask, 'Invert Mask', 'Filter')
vollib.addNode(GaussiansMask, 'Gaussians Blur', 'Mapper')
vollib.addNode(MapGrid, 'MapGrid', 'Mapper')
vollib.addNode(ToGrid3D, 'ToGrid3D', 'Mapper')
vollib.addNode(PointsBB, 'PointsBB', 'Mapper')
vollib.addNode(GridPoints, 'GridPoints', 'Mapper')

vollib.addNode(RegionBox, 'RegionBox', 'Filter')
vollib.addNode(ClipMap, 'ClipMapWithMask', 'Filter')
vollib.addNode(ClipMapWithBox, 'ClipMapWithBox', 'Filter')
vollib.addNode(FillMapWithBox, 'FillMapWithBox', 'Filter')
vollib.addNode(ClipMeshWithMaskNE, 'ClipMeshWithMask', 'Filter')

vollib.addNode(TransposeGrid3D, 'Transpose', 'Operator')
vollib.addNode(Sample, 'sample', 'Operator')
vollib.addNode(GridByLookUp, 'lookUp', 'Operator')
vollib.addNode(SetOrigin, 'set origin', 'Operator')
vollib.addNode(SetStepSize, 'set stepSize', 'Operator')
vollib.addNode(Center, 'center', 'Operator')
vollib.addNode(LogicOP, 'logicOP', 'Operator')
vollib.addNode(ThresholdMask, 'ThresholdMask', 'Operator')
vollib.addNode(TriInterp, 'triInterp', 'Operator')
vollib.addNode(ArrayScalarOp, 'ArrayScalarOp', 'Operator')
vollib.addNode(ArrayArrayOp, 'ArrayArrayOp', 'Operator')
vollib.addNode(Grid3DTo2D, 'Grid3DTo2D', 'Operator')
vollib.addNode(SetValuesAtPositions, 'SetAtPos', 'Operator')

try:
    from UTpackages.UTmesh import lbiemesher
    vollib.addNode(UTMesher, 'UT-mesh', 'Mapper')
except ImportError:
    print('Warning: Module "lbiemesher" could not be imported.\n'+\
          '         Node "UTMesher" was not added to the Library.')

try:
    from UTpackages.UTisocontour import isocontour
    isocontour.setVerboseLevel(0)
    vollib.addNode(Isocontour, 'UT-Isocontour', 'Mapper')
except:
    print('Warning: Module "isocontour" could not be imported.\n'+\
          '         Node "Isocontour" was not added to the Library.')


try:
    blur = _utblur()
    vollib.addNode(UTBlurring, "UT Blur", "Mapper")
    vollib.addNode(UTBlurSpheres, "UT Blur Spheres", "Mapper")
    vollib.addNode(UTblurSpheres, "UT-BlurSpheres(1)", "Mapper")
except:
    pass

try:
    from UTpackages.UTsdf import utsdf
    vollib.addNode(UTsdf, "UT-SDF", "Mapper")
except:
    pass


#vollib.addNode(TSRIsdf, "SDF", "Mapper")

vollib.addNode(WriteRawiv, "WriteRawiv", "Output")


from wewos.volcore.Grid3D import Grid3D

class Grid3DType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3D'
        self.data['color'] = '#995699'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3D

    def validate(self, data):
        return isinstance(data, Grid3D)

    def cast(self, data):
        return False, data
    

class Grid3DDType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3DD'
        self.data['color'] = 'magenta'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3DD

    def validate(self, data):
        return isinstance(data, Grid3DD)

    def cast(self, data):
        return False, data


class Grid3DFType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3DF'
        self.data['color'] = 'green'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3DF

    def validate(self, data):
        return isinstance(data, Grid3DF)

    def cast(self, data):
        return False, data
    
    
class Grid3DIType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3DI'
        self.data['color'] = 'yellow'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3DI

    def validate(self, data):
        return isinstance(data, Grid3DI)

    def cast(self, data):
        return False, data
    

class Grid3DSIType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3DSI'
        self.data['color'] = 'yellow'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3DSI

    def validate(self, data):
        return isinstance(data, Grid3DSI)

    def cast(self, data):
        return False, data
    
    
class Grid3DUIType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3DUI'
        self.data['color'] = 'yellow'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3DUI

    def validate(self, data):
        return isinstance(data, Grid3DUI)

    def cast(self, data):
        return False, data
    

class Grid3DUSIType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3DUSI'
        self.data['color'] = 'yellow'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3DUSI

    def validate(self, data):
        return isinstance(data, Grid3DUSI)

    def cast(self, data):
        return False, data
    
    
class Grid3DUCType(AnyType):
    
    def __init__(self):
        AnyType.__init__(self)
        self.data['name'] = 'Grid3DUC'
        self.data['color'] = 'cyan'
        self.data['shape'] = 'diamond'
        self.data['class'] = Grid3DUC

    def validate(self, data):
        return isinstance(data, Grid3DUC)

    def cast(self, data):
        return False, data






            

vollib.addNode(MoleculeBBGrid, 'Mol BB Grid', 'Mapper')

vollib.addNode(ReadAnyMap, 'ReadAnyMap', 'Input')
vollib.addNode(ReadRawNumpyVol, 'Read numpy volume', 'Input')
vollib.addNode(UT_Iso, 'UTiso', 'Macro')
vollib.addNode(CoarseMolSurf, 'CoarseMolSurf', 'Macro')
vollib.addNode(OrthoSlice, 'OrthoSlice', 'Operator')
vollib.addNode(BoundingBox, 'GridBB', 'Mapper')
for _t in (Grid3DType, Grid3DDType, Grid3DFType, Grid3DIType, Grid3DSIType, Grid3DUIType,
           Grid3DUSIType, Grid3DUCType):
    vollib.addType(_t())
