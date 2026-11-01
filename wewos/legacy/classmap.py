# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Where the nodes of MGLTools libraries go in WEWoS.

lookup(module, cls) returns (library, class, in-port map, out-port map) or
None. Port maps rename ports whose name changed; '*' maps any port not listed
(used for library macros that became single nodes, whose port names were
built from their inner nodes).
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
}

MOLKIT = {
    'ReadMolecule': ('Molecules', 'ReadMolecule', {}, {'MolSets': 'mol'}),
    'NodeSelector': ('Molecules', 'NodeSelector', {}, {'nodes': 'selection'}),
    'AtomsProperty': ('Molecules', 'AtomsProperty', {}, {}),
    'AssignRadii': ('Molecules', 'AssignRadii', {'molecules': 'atoms'}, {'molecules': 'atoms'}),
    'AtomsAsCPK': ('Molecules', 'AtomsAsCPK', {}, {}),
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
)


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
    if fam == 'symserv':
        from wewos.engine import get_library
        if cls in get_library('SymServer').nodeClassFromName:
            return ('SymServer', cls, {}, {})
        return None
    return None


def map_port(pmap, name):
    if name in pmap:
        return pmap[name]
    if '*' in pmap and isinstance(name, str):
        return pmap['*']
    return name
