# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Where the nodes of MGLTools libraries go in WEWoS.

lookup(module, cls) returns (library, class, in-port map, out-port map) or
None. Port maps rename ports whose name changed; '*' maps any port not listed
(used for library macros that became single nodes, whose port names were
built from their inner nodes). With '*', a name '<inner node>_<port>' goes to
<port> when the new node has that port (map_port finds them under '**ports').
"""

# Vision.StandardNodes: same class names in the Standard library
STANDARD = 'Standard'

DEJAVU = {
    'Viewer': ('3D Visualization', 'Viewer', {}, {'dejaVuViewer': 'viewer'}),
    'Spheres': ('3D Visualization', 'Spheres', {}, {}),
    'Points': ('3D Visualization', 'Points', {}, {}),
    'Cylinders': ('3D Visualization', 'Cylinders', {}, {}),
    'IndexedPolygonsNE': ('3D Visualization', 'IndexedPolygons', {}, {}),
    'IndexedPolylinesNE': ('3D Visualization', 'IndexedPolylines', {}, {}),
    'GlfLabelsNE': ('3D Visualization', 'Labels', {}, {}),
    'BoxNE': ('3D Visualization', 'BoxNE', {}, {}),
    'AxisNE': ('3D Visualization', 'AxisNE', {}, {}),
    'GeomContainer': ('3D Visualization', 'GeomContainer', {}, {}),
    'GroupGeomsNE': ('3D Visualization', 'GeomContainer', {'*': 'geoms'}, {'*': 'geomContainer'}),
    'GeomOptions': ('3D Visualization', 'GeomOptions', {}, {}),
    'ColorMapNE': ('3D Visualization', 'ColorMap', {'colorMap': 'ramp'}, {'mappedColors': 'colors'}),
    'OneRedraw': ('3D Visualization', 'OneRedraw', {}, {}),
}

MOLKIT = {
    'ReadMolecule': ('Molecules', 'ReadMolecule', {}, {'MolSets': 'mol'}),
    'NodeSelector': ('Molecules', 'NodeSelector', {}, {'nodes': 'selection'}),
    'AtomsProperty': ('Molecules', 'AtomsProperty', {}, {}),
    'AssignRadii': ('Molecules', 'AssignRadii', {'molecules': 'atoms'}, {'molecules': 'atoms'}),
    'AtomsAsCPK': ('Molecules', 'AtomsAsCPK', {}, {'CPK': 'spheres'}),
    'GetMSMStriangles': ('Molecules', 'GetMSMStriangles', {}, {}),
    'AtomsAsSticks': ('Molecules', 'AtomsAsSticks', {}, {}),
    'AtomsAsMSMS': ('Molecules', 'AtomsAsMSMS', {'probe_radius': 'probeRadius'},
                    {'MSMS': 'surface'}),
    'WritePDB': ('Molecules', 'WriteMolecule', {'nodes': 'atoms'}, {}),
    'WriteMolecule': ('Molecules', 'WriteMolecule', {'mols': 'atoms'}, {}),
    # library macros that are single nodes here
    'CPKMacro': ('Molecules', 'AtomsAsCPK', {'*': 'atoms'}, {'*': 'spheres'}),
    'LinesMacro': ('Molecules', 'AtomsAsLines', {'*': 'atoms'}, {'*': 'lines'}),
    'MSMSMacro': ('Molecules', 'AtomsAsMSMS', {'*': 'atoms'}, {'*': 'surface'}),
}

# the module names (and getNodeLib library names) of each MGLTools library
PACKAGES = (
    (('Vision.StandardNodes', 'stdlib', 'Standard'), 'standard'),
    (('DejaVu.VisionInterface', 'vizlib', 'DejaVu'), 'dejavu'),
    (('MolKit.VisionInterface', 'molkitlib', 'MolKit'), 'molkit'),
    (('symserv', 'symlib', 'SymServer'), 'symserv'),
    (('Volume.VisionInterface', 'vollib', 'volume'), 'volume'),
    (('Vision.matplotlibNodes', 'matplotliblib', 'MatPlotLib'), 'matplotlib'),
    (('Vision.PILNodes', 'imagelib', 'Imaging'), 'imaging'),
)

# ports renamed between MGLTools versions, for classes that keep their names
RENAMES = {('Volume', 'BoundingBox'): ({}, {'geom': 'Grid3DBB'}),
           # the 2007 TablePlot
           ('MatPlotLib', 'TablePlotNE'): ({'rowlabels': 'rowLabels', 'columnlabels': 'colLabels',
                                            'rowcolors': 'rowColors', 'columncolors': 'colColors'}, {})}

# classes Vision dropped (matplotlib removed the functions they called): the
# class that took their place, with the same ports
ALIASES = {('MatPlotLib', 'ScatterClassicNE'): 'ScatterNE',
           ('MatPlotLib', 'PcolorClassicNE'): 'PcolorNE',
           ('MatPlotLib', 'Spy2NE'): 'SpyNE'}

# libraries whose node classes keep their names here
SAME_NAMES = {'symserv': 'SymServer', 'volume': 'Volume', 'matplotlib': 'MatPlotLib',
              'imaging': 'Imaging'}


def family(module, libname=None):
    for prefixes, fam in PACKAGES:
        for p in prefixes:
            if (module or '').startswith(p) or libname == p:
                return fam
    return None


def lookup(module, cls, libname=None):
    fam = family(module, libname)
    if fam == 'standard':
        from wewos.engine import get_library
        lib = get_library(STANDARD)
        if cls in lib.nodeClassFromName:
            return (STANDARD, cls, {}, {})
        return None
    if fam == 'dejavu':
        return DEJAVU.get(cls)
    if fam == 'molkit':
        return MOLKIT.get(cls)
    if fam in SAME_NAMES:
        from wewos.engine import get_library
        lib = SAME_NAMES[fam]
        new = ALIASES.get((lib, cls), cls)
        if new in get_library(lib).nodeClassFromName:
            inmap, outmap = RENAMES.get((lib, cls), ({}, {}))
            return (lib, new, inmap, outmap)
        return None
    return None


# ports a library macro's user added to an inner node that the single node
# replacing the macro does not have: kept by name (the connection is reported
# as not made) instead of falling on the catch-all port
_NOT_CAUGHT = ('parent',)


def map_port(pmap, name):
    if name in pmap:
        return pmap[name]
    if '*' in pmap and isinstance(name, str):
        for p in sorted(pmap.get('**ports', ()), key=len, reverse=True):
            if name == p or name.endswith('_' + p):
                return p
        if any(name == p or name.endswith('_' + p) for p in _NOT_CAUGHT):
            return name
        return pmap['*']
    return name
