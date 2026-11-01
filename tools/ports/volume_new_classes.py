
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
    from Volume.IO.dxReader import ReadDX
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
            net.connectNodes(bl, iso, 'maskGrid', 'grid3D', doNotSchedule=True)
            for a, b in (('coords', 'coords'), ('indices', 'indices'), ('normals', 'vnormals')):
                net.connectNodes(iso, poly, a, b, doNotSchedule=True)
            net.connectNodes(poly, net.opNode, 'indexedPolygons', 0, doNotSchedule=True)
            net.ipNode.move(201, 10)
            net.opNode.move(201, 400)
        finally:
            net.runOnNewData.value = saved

#--REGISTER--
vollib.addNode(ReadAnyMap, 'ReadAnyMap', 'Input')
vollib.addNode(ReadRawNumpyVol, 'Read numpy volume', 'Input')
vollib.addNode(UT_Iso, 'UTiso', 'Macro')
vollib.addNode(CoarseMolSurf, 'CoarseMolSurf', 'Macro')
vollib.addNode(OrthoSlice, 'OrthoSlice', 'Operator')
vollib.addNode(BoundingBox, 'GridBB', 'Mapper')
for _t in (Grid3DType, Grid3DDType, Grid3DFType, Grid3DIType, Grid3DSIType, Grid3DUIType,
           Grid3DUSIType, Grid3DUCType):
    vollib.addType(_t())
