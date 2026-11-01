# Author: Michel Sanner, PhD. Copyright (c) 2026.
# Replaces MGLTools MolKit/VisionInterface/MolKitNodes.py, using MolKit2 and ProDy.
"""Molecules: read, select, measure, draw and surface molecules.

Molecules are MolKit2 Molecule objects; atom sets are MolKit2 (ProDy)
selections, which carry the molecule they come from. Drawing nodes (CPK,
Sticks, Lines, Cartoon, Surface) output a MolRep geometry that 3Dmol.js draws
itself, so clicking an atom in the viewer identifies that atom; MSMS outputs
a triangle mesh (mslib) like Vision's MSMS node.
"""
import io
import os

import numpy

from wewos import geom as G
from wewos.geom import instance_list
from wewos.engine import NetworkNode, NodeLibrary
from wewos.libs import viz3d  # noqa: F401  (registers the 'geom' port type)
from wewos.engine.datatypes import AnyType


class _ObjType(AnyType):
    def __init__(self, name, color, shape, klass, check):
        AnyType.__init__(self, name=name, color=color, shape=shape, klass=klass)
        self._check = check

    def validate(self, data):
        return self._check(data)

    def cast(self, data):
        return False, data


def _is_mol(d):
    from MolKit2.molecule import Molecule
    return isinstance(d, Molecule)


def _is_atoms(d):
    import prody
    return isinstance(d, (prody.AtomGroup, prody.Selection, prody.AtomSubset)) or _is_mol(d)


class MoleculeType(_ObjType):
    def __init__(self, name='Molecule', datashape=None, **kw):
        _ObjType.__init__(self, name, '#0ea5e9', 'oval', None, _is_mol)


class AtomSetType(_ObjType):
    def __init__(self, name='AtomSet', datashape=None, **kw):
        _ObjType.__init__(self, name, '#f43f5e', 'oval', None, _is_atoms)


# ---- helpers --------------------------------------------------------------------------
def atoms_of(x):
    """(molecule, selection) for a Molecule or a selection of one (MolKit2
    selections keep a weak reference to their molecule in _molecule)."""
    from MolKit2.molecule import Molecule
    if isinstance(x, (list, tuple)) and len(x) == 1:
        x = x[0]
    if isinstance(x, Molecule):
        return x, x.select()
    mol = None
    ref = getattr(x, '_molecule', None)
    if callable(ref):
        mol = ref()
    if mol is None:
        ag = x.getAtomGroup() if hasattr(x, 'getAtomGroup') else None
        ref = getattr(ag, '_molecule', None)
        mol = ref() if callable(ref) else None
    return mol, x


def tag(sel, mol):
    return sel


def pdb_text(sel):
    import prody
    buf = io.StringIO()
    prody.writePDBStream(buf, sel)
    return buf.getvalue()


CPK = {'H': (1, 1, 1), 'C': (.56, .56, .56), 'N': (.19, .31, .97), 'O': (1, .05, .05),
       'S': (1, 1, .19), 'P': (1, .5, 0), 'F': (.56, .88, .31), 'CL': (.12, .94, .12),
       'BR': (.65, .16, .16), 'I': (.58, 0, .58), 'FE': (.88, .4, .2), 'ZN': (.49, .5, .69),
       'MG': (.54, 1, 0), 'CA': (.24, 1, 0), 'NA': (.67, .36, .95), 'K': (.56, .25, .83),
       'MN': (.61, .48, .78), 'CU': (.78, .5, .2)}
CHAIN = [(.27, .53, .93), (.93, .53, .27), (.33, .73, .33), (.87, .33, .53), (.6, .47, .87),
         (.53, .8, .8), (.93, .8, .33), (.6, .6, .6)]


def colors_for(sel, scheme):
    """Per-atom colors (n x 3) for a coloring scheme name."""
    n = sel.numAtoms()
    if scheme in (None, '', 'element'):
        els = [e.upper() for e in sel.getElements()]
        return numpy.array([CPK.get(e, (1, .08, .58)) for e in els], 'f')
    if scheme == 'chain':
        ids = {c: i for i, c in enumerate(sorted(set(sel.getChids())))}
        return numpy.array([CHAIN[ids[c] % len(CHAIN)] for c in sel.getChids()], 'f')
    if scheme == 'residue number':
        from wewos.libs.viz3d import colormap
        return colormap(sel.getResnums(), 'rainbow')
    if scheme == 'b-factor':
        from wewos.libs.viz3d import colormap
        return colormap(sel.getBetas(), 'rwb')
    return numpy.tile(G._rgb(scheme) or [.8, .8, .8], (n, 1)).astype('f')


# 3Dmol color schemes for the representations drawn by 3Dmol itself
SCHEMES = ['element', 'chain', 'spectrum', 'secondary structure', 'residue number',
           'b-factor', 'white', 'grey', 'green', 'orange']


def style_color(scheme):
    if scheme in (None, '', 'element'):
        return {'colorscheme': 'Jmol'}
    if scheme == 'chain':
        return {'colorscheme': 'chain'}
    if scheme == 'secondary structure':
        return {'colorscheme': 'ssJmol'}
    if scheme == 'spectrum':
        return {'color': 'spectrum'}
    return None          # computed per atom


class RepNode(NetworkNode):
    """Base class of the nodes outputting a MolRep."""
    rep = 'stick'
    outName = 'geom'

    def __init__(self, name, **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.geom = None
        ip = self.inputPortsDescr
        ip.append(datatype='AtomSet', name='atoms')
        ip.append(datatype='string', name='colorBy', required=False)
        ip.append(datatype='colorfloat3or4(0)', name='colors', required=False)
        ip.append(datatype='float', name='opacity', required=False)
        ip.append(datatype='string', name='name', required=False)
        ip.append(datatype='instancemat(0)', name='instanceMatrices', required=False,
                  singleConnection=False)
        self.widgetDescr['colorBy'] = {'class': 'NEComboBox', 'master': 'node',
                                       'choices': SCHEMES, 'fixedChoices': True,
                                       'initialValue': self.defaultScheme,
                                       'labelCfg': {'text': 'color'}}
        self.widgetDescr['opacity'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                       'initialValue': 1.0, 'min': 0., 'max': 1., 'oneTurn': 1.,
                                       'labelCfg': {'text': 'opacity'}}
        self.outputPortsDescr.append(datatype='geom', name=self.outName)

    defaultScheme = 'element'

    def repStyle(self, extra):
        return {}

    def makeRep(self, atoms, colorBy, colors, opacity, name, extra=None, instanceMatrices=None):
        mol, sel = atoms_of(atoms)
        st = dict(self.repStyle(extra or {}))
        c = style_color(colorBy) if colors is None else None
        atomColors = None
        if colors is not None:
            atomColors = numpy.resize(numpy.asarray(colors, 'f').reshape(-1, 3)
                                      if numpy.asarray(colors).ndim > 1
                                      else numpy.asarray(colors, 'f')[:3][None, :],
                                      (sel.numAtoms(), 3))
        elif c is None:
            atomColors = colors_for(sel, colorBy)
        else:
            st.update(c)
        if opacity is not None and opacity < 1:
            st['opacity'] = float(opacity)
        styles = [[{}, {self.rep: st}]]
        gname = name or self.name.replace(' ', '_')
        if self.geom is None:
            self.geom = G.MolRep(gname)
        self.geom.Set(name=gname, pdb=pdb_text(sel), styles=styles, mol=mol,
                      atomColors=atomColors, atomIndices=sel.getIndices(),
                      instanceMatrices=instance_list(instanceMatrices))
        self.outputData(**{self.outName: self.geom})
        return self.geom


class AtomsAsCPK(RepNode):
    """Atoms as spheres (van der Waals radii times scale)."""
    rep = 'sphere'
    outName = 'spheres'

    def __init__(self, name='CPK', **kw):
        RepNode.__init__(self, name, **kw)
        self.inputPortsDescr.append(datatype='float', name='scale', required=False)
        self.widgetDescr['scale'] = {'class': 'NEThumbWheel', 'master': 'node',
                                     'initialValue': 1.0, 'min': 0.05, 'max': 3., 'oneTurn': 2.,
                                     'labelCfg': {'text': 'scale'}}
        self.setFunction("""def doit(self, atoms, colorBy, colors, opacity, name, instanceMatrices, scale):
    self.makeRep(atoms, colorBy, colors, opacity, name, {'scale': scale}, instanceMatrices)
""")

    def repStyle(self, extra):
        return {'scale': float(extra.get('scale') or 1.0)}


class AtomsAsSticks(RepNode):
    """Atoms and bonds as sticks."""
    rep = 'stick'
    outName = 'sticks'

    def __init__(self, name='Sticks', **kw):
        RepNode.__init__(self, name, **kw)
        self.inputPortsDescr.append(datatype='float', name='cradii', required=False)
        self.widgetDescr['cradii'] = {'class': 'NEThumbWheel', 'master': 'node',
                                      'initialValue': 0.2, 'min': 0.02, 'max': 1., 'oneTurn': .5,
                                      'labelCfg': {'text': 'radius'}}
        self.setFunction("""def doit(self, atoms, colorBy, colors, opacity, name, instanceMatrices, cradii):
    self.makeRep(atoms, colorBy, colors, opacity, name, {'radius': cradii}, instanceMatrices)
""")

    def repStyle(self, extra):
        return {'radius': float(extra.get('radius') or 0.2)}


class AtomsAsLines(RepNode):
    """Bonds as lines."""
    rep = 'line'
    outName = 'lines'

    def __init__(self, name='Lines', **kw):
        RepNode.__init__(self, name, **kw)
        self.setFunction("""def doit(self, atoms, colorBy, colors, opacity, name, instanceMatrices):
    self.makeRep(atoms, colorBy, colors, opacity, name, None, instanceMatrices)
""")


class Cartoon(RepNode):
    """Secondary structure cartoon (helices, strands, coil) of proteins and
nucleic acids."""
    rep = 'cartoon'
    outName = 'cartoon'
    defaultScheme = 'spectrum'

    def __init__(self, name='Cartoon', **kw):
        RepNode.__init__(self, name, **kw)
        self.setFunction("""def doit(self, atoms, colorBy, colors, opacity, name, instanceMatrices):
    self.makeRep(atoms, colorBy, colors, opacity, name, None, instanceMatrices)
""")


class Surface3Dmol(NetworkNode):
    """A molecular surface computed in the browser by 3Dmol.js (fast; for an
analytical surface with vertices, faces and normals in the network, use MSMS)."""

    def __init__(self, name='Surface', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.geom = None
        ip = self.inputPortsDescr
        ip.append(datatype='AtomSet', name='atoms')
        ip.append(datatype='string', name='surfaceType', required=False)
        ip.append(datatype='string', name='colorBy', required=False)
        ip.append(datatype='float', name='opacity', required=False)
        ip.append(datatype='string', name='name', required=False)
        ip.append(datatype='instancemat(0)', name='instanceMatrices', required=False,
                  singleConnection=False)
        self.widgetDescr['surfaceType'] = {'class': 'NEComboBox', 'master': 'node',
                                           'choices': ['MS', 'SAS', 'VDW', 'SES'],
                                           'fixedChoices': True, 'initialValue': 'MS',
                                           'labelCfg': {'text': 'type'}}
        self.widgetDescr['colorBy'] = {'class': 'NEComboBox', 'master': 'node',
                                       'choices': ['white', 'element', 'chain', 'spectrum'],
                                       'fixedChoices': True, 'initialValue': 'white',
                                       'labelCfg': {'text': 'color'}}
        self.widgetDescr['opacity'] = {'class': 'NEThumbWheel', 'master': 'node',
                                       'initialValue': 0.8, 'min': 0., 'max': 1., 'oneTurn': 1.,
                                       'labelCfg': {'text': 'opacity'}}
        self.outputPortsDescr.append(datatype='geom', name='surface')
        self.setFunction("""def doit(self, atoms, surfaceType, colorBy, opacity, name, instanceMatrices):
    mol, sel = atoms_of(atoms)
    s = {'type': surfaceType or 'MS', 'opacity': opacity}
    c = style_color(colorBy)
    if c:
        s.update(c)
    elif colorBy:
        s['color'] = colorBy
    gname = name or self.name.replace(' ', '_')
    if self.geom is None:
        self.geom = G.MolRep(gname)
    self.geom.Set(name=gname, pdb=pdb_text(sel), styles=[], surfaces=[s], mol=mol,
                  atomIndices=sel.getIndices(),
                  instanceMatrices=instance_list(instanceMatrices))
    self.outputData(surface=self.geom)
""")


class ReadMolecule(NetworkNode):
    """Read a molecule (PDB, PDBQT, mol2, SDF, mmCIF) with MolKit2."""

    def __init__(self, name='Read Molecule', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.widgetDescr['filename'] = {
            'class': 'NEEntryWithFileBrowser', 'master': 'node',
            'filetypes': [('molecule', '*.pdb *.pdbqt *.ent *.mol2 *.sdf *.cif')],
            'title': 'read molecule', 'labelCfg': {'text': 'file'}}
        self.outputPortsDescr.append(datatype='Molecule', name='mol')
        self.setFunction("""def doit(self, filename):
    if not filename:
        return 'Stop'
    from MolKit2 import Read
    mol = Read(filename)
    self.outputData(mol=mol)
""")


class FetchPDB(NetworkNode):
    """Download an entry from the RCSB by its PDB id (cached in the network
folder) and read it."""

    def __init__(self, name='Fetch PDB', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='string', name='pdbId')
        self.widgetDescr['pdbId'] = {'class': 'NEEntry', 'master': 'node',
                                     'initialValue': '1crn', 'labelCfg': {'text': 'PDB id'}}
        self.outputPortsDescr.append(datatype='Molecule', name='mol')
        self.outputPortsDescr.append(datatype='string', name='filename')
        self.setFunction("""def doit(self, pdbId):
    from wewos import fetch
    from MolKit2 import Read
    cache = os.path.join(self.network.workdir() or os.getcwd(), '_rcsb')
    path, url, cached = fetch.fetch(pdbId, cache)
    mol = Read(path)
    self.outputData(mol=mol, filename=path)
""")


class NodeSelector(NetworkNode):
    """Select atoms. syntax 'prody': a ProDy selection, e.g.
'chain A and resnum 10 to 20', 'protein and not hydrogen', 'within 5 of resname HEM'.
syntax 'molkit': chains:residues:atoms as in MolKit, e.g. 'A:1to10:CA'."""

    def __init__(self, name='Select', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        ip = self.inputPortsDescr
        ip.append(datatype='AtomSet', name='nodes')
        ip.append(datatype='string', name='selectionString', required=False)
        ip.append(datatype='string', name='syntax', required=False)
        self.widgetDescr['selectionString'] = {'class': 'NEEntry', 'master': 'node',
                                               'initialValue': 'all',
                                               'labelCfg': {'text': 'select'}}
        self.widgetDescr['syntax'] = {'class': 'NEComboBox', 'master': 'ParamPanel',
                                      'choices': ['prody', 'molkit'], 'fixedChoices': True,
                                      'initialValue': 'prody', 'labelCfg': {'text': 'syntax'}}
        self.outputPortsDescr.append(datatype='AtomSet', name='selection')
        self.outputPortsDescr.append(datatype='int', name='numAtoms')
        self.setFunction("""def doit(self, nodes, selectionString, syntax):
    mol, sel = atoms_of(nodes)
    s = (selectionString or 'all').strip()
    if syntax == 'molkit':
        if sel.numAtoms() != mol.select().numAtoms():
            raise ValueError('molkit syntax selects in a whole molecule; use prody syntax on a selection')
        res = mol.selectMolKit(s)
    else:
        res = sel.select(s) if s != 'all' else sel
    if res is None or res.numAtoms() == 0:
        print('%s: nothing matches %r' % (self.name, s))
        return 'Stop'
    self.outputData(selection=tag(res, mol), numAtoms=res.numAtoms())
""")


class AtomsProperty(NetworkNode):
    """Extract a property of the atoms (coords, radii, element, name,
resname, resnum, chain, bfactor, occupancy, charge, index)."""

    PROPS = ['coords', 'radii', 'element', 'name', 'resname', 'resnum', 'chain',
             'bfactor', 'occupancy', 'charge', 'index', 'serial']

    def __init__(self, name='Extract Atom Property', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='AtomSet', name='atoms')
        self.inputPortsDescr.append(datatype='string', name='propertyName', required=False)
        self.widgetDescr['propertyName'] = {'class': 'NEComboBox', 'master': 'node',
                                            'choices': self.PROPS, 'fixedChoices': True,
                                            'initialValue': 'coords',
                                            'labelCfg': {'text': 'property'}}
        self.outputPortsDescr.append(datatype='None', name='propertyValues')
        self.setFunction("""def doit(self, atoms, propertyName):
    mol, sel = atoms_of(atoms)
    self.outputData(propertyValues=atom_property(mol, sel, propertyName or 'coords'))
""")


def atom_property(mol, sel, p):
    if p == 'coords':
        return sel.getCoords().astype('f')
    if p == 'radii':
        return radii(mol, sel)
    get = {'element': sel.getElements, 'name': sel.getNames, 'resname': sel.getResnames,
           'resnum': sel.getResnums, 'chain': sel.getChids, 'bfactor': sel.getBetas,
           'occupancy': sel.getOccupancies, 'charge': sel.getCharges,
           'index': sel.getIndices, 'serial': sel.getSerials}[p]
    v = get()
    return v.tolist() if v is not None and v.dtype.kind in 'US' else v


def radii(mol, sel):
    r = sel.getRadii() if hasattr(sel, 'getRadii') else None
    if r is None or not numpy.any(r):
        if mol is not None:
            ag = mol._ag
            mol.defaultRadii()
            r = ag.getRadii()[sel.getIndices()]
        else:
            r = numpy.full(sel.numAtoms(), 1.8, 'f')
    return numpy.asarray(r, 'f')


class AssignRadii(NetworkNode):
    """Assign van der Waals radii to the atoms; outputs the atoms and radii."""

    def __init__(self, name='Assign Radii', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='AtomSet', name='atoms')
        self.outputPortsDescr.append(datatype='AtomSet', name='atoms')
        self.outputPortsDescr.append(datatype='float(0)', name='radii')
        self.setFunction("""def doit(self, atoms):
    mol, sel = atoms_of(atoms)
    self.outputData(atoms=sel, radii=radii(mol, sel))
""")


class AtomsAsMSMS(NetworkNode):
    """Solvent excluded surface of the atoms computed by MSMS (Sanner, Olson &
Spehner 1996). Outputs the surface as a mesh, its vertices, faces and
normals, and for each vertex the index (in the atom set) of the closest atom."""

    def __init__(self, name='MSMS', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.geom = None
        ip = self.inputPortsDescr
        ip.append(datatype='AtomSet', name='atoms')
        ip.append(datatype='float', name='probeRadius', required=False)
        ip.append(datatype='float', name='density', required=False)
        ip.append(datatype='string', name='colorBy', required=False)
        ip.append(datatype='colorfloat3or4(0)', name='colors', required=False)
        ip.append(datatype='float', name='opacity', required=False)
        ip.append(datatype='instancemat(0)', name='instanceMatrices', required=False,
                  singleConnection=False)
        self.widgetDescr['probeRadius'] = {'class': 'NEThumbWheel', 'master': 'node',
                                           'initialValue': 1.5, 'min': 0.5, 'max': 10.,
                                           'oneTurn': 2., 'labelCfg': {'text': 'probe'}}
        self.widgetDescr['density'] = {'class': 'NEThumbWheel', 'master': 'node',
                                       'initialValue': 3.0, 'min': 0.5, 'max': 20.,
                                       'oneTurn': 5., 'labelCfg': {'text': 'density'}}
        self.widgetDescr['colorBy'] = {'class': 'NEComboBox', 'master': 'node',
                                       'choices': ['white', 'element', 'chain', 'residue number',
                                                   'b-factor'],
                                       'fixedChoices': True, 'initialValue': 'white',
                                       'labelCfg': {'text': 'color'}}
        self.widgetDescr['opacity'] = {'class': 'NEThumbWheel', 'master': 'ParamPanel',
                                       'initialValue': 1.0, 'min': 0., 'max': 1., 'oneTurn': 1.,
                                       'labelCfg': {'text': 'opacity'}}
        op = self.outputPortsDescr
        op.append(datatype='geom', name='surface')
        op.append(datatype='coord3(0)', name='vertices')
        op.append(datatype='None', name='faces')
        op.append(datatype='normal3(0)', name='normals')
        op.append(datatype='None', name='closestAtoms')
        self.setFunction("""def doit(self, atoms, probeRadius, density, colorBy, colors, opacity, instanceMatrices):
    mol, sel = atoms_of(atoms)
    v, f, n, closest = msms_surface(sel.getCoords(), radii(mol, sel), probeRadius, density)
    if colors is None:
        ac = colors_for(sel, colorBy or 'white')
        colors = ac[closest]
    if self.geom is None:
        self.geom = G.IndexedPolygons(self.name.replace(' ', '_'))
    self.geom.Set(vertices=v, faces=f, vnormals=n, materials=colors,
                  opacity=1.0 if opacity is None else opacity,
                  instanceMatrices=instance_list(instanceMatrices))
    self.outputData(surface=self.geom, vertices=v, faces=f, normals=n, closestAtoms=closest)
""")


def msms_surface(coords, rad, probe=1.5, density=3.0):
    """(vertices, triangles, normals, closest atom index per vertex)."""
    from wewos.engine.events import captured
    from mslib import MSMS
    with captured(lambda t: None):      # mslib prints a banner
        srf = MSMS(coords=numpy.asarray(coords, 'f'), radii=numpy.asarray(rad, 'f'))
        srf.compute(probe_radius=float(probe or 1.5), density=float(density or 3.0))
        vf, vi, tri = srf.getTriangles()
    v = numpy.asarray(vf[:, :3], 'f')
    n = numpy.asarray(vf[:, 3:6], 'f')
    f = numpy.asarray(tri[:, :3], 'i')
    closest = numpy.asarray(vi[:, 1], 'i') - 1
    return v, f, n, closest


class WriteMolecule(NetworkNode):
    """Write atoms to a PDB file (relative names go in the network folder)."""

    def __init__(self, name='Write PDB', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='AtomSet', name='atoms')
        self.inputPortsDescr.append(datatype='string', name='filename')
        self.widgetDescr['filename'] = {'class': 'NEEntryWithFileSaver', 'master': 'node',
                                        'initialValue': 'out.pdb',
                                        'labelCfg': {'text': 'file'}}
        self.outputPortsDescr.append(datatype='string', name='filename')
        self.setFunction("""def doit(self, atoms, filename):
    mol, sel = atoms_of(atoms)
    import prody
    prody.writePDB(filename, sel)
    self.outputData(filename=os.path.abspath(filename))
""")


class Sequence(NetworkNode):
    """The one-letter sequence of the atoms' residues."""

    def __init__(self, name='Sequence', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='AtomSet', name='atoms')
        self.outputPortsDescr.append(datatype='string', name='sequence')
        self.setFunction("""def doit(self, atoms):
    from MolKit2 import getSequence
    mol, sel = atoms_of(atoms)
    self.outputData(sequence=getSequence(sel))
""")


class PickedAtom(NetworkNode):
    """The atom (and its residue) clicked in a Viewer: connect the Viewer's
lastPick output here."""

    def __init__(self, name='Picked Atom', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='None', name='pick')
        self.outputPortsDescr.append(datatype='AtomSet', name='atom')
        self.outputPortsDescr.append(datatype='AtomSet', name='residue')
        self.outputPortsDescr.append(datatype='string', name='label')
        self.setFunction("""def doit(self, pick):
    obj = pick.get('object') if isinstance(pick, dict) else None
    idx = pick.get('atomIndex') if isinstance(pick, dict) else None
    if obj is None or idx is None or getattr(obj, 'mol', None) is None:
        print('%s: the pick is not an atom' % self.name)
        return 'Stop'
    mol = obj.mol
    a = mol._ag[idx]
    atom = mol.select('index %d' % idx)
    res = mol.select('resindex %d' % a.getResindex())
    label = '%s:%s%d:%s' % (a.getChid(), a.getResname(), a.getResnum(), a.getName())
    self.outputData(atom=atom, residue=res, label=label)
""")


molkitlib = NodeLibrary('Molecules', '#5BA4CF',
                        doc='MolKit2 molecules: read, select, draw, MSMS surfaces')
molkitlib.addType(MoleculeType())
molkitlib.addType(AtomSetType())
molkitlib.addType(MoleculeType('MoleculeSet'))
molkitlib.addType(AtomSetType('TreeNodeSet'))

molkitlib.addNode(ReadMolecule, 'Read Molecule', 'Input')
molkitlib.addNode(FetchPDB, 'Fetch PDB', 'Input')
molkitlib.addNode(AssignRadii, 'Assign Radii', 'Input')
molkitlib.addNode(AtomsProperty, 'Extract Atom Property', 'Input')
molkitlib.addNode(NodeSelector, 'Select', 'Filter')
molkitlib.addNode(Sequence, 'Sequence', 'Filter')
molkitlib.addNode(PickedAtom, 'Picked Atom', 'Filter')
molkitlib.addNode(AtomsAsCPK, 'CPK', 'Mapper')
molkitlib.addNode(AtomsAsSticks, 'Sticks', 'Mapper')
molkitlib.addNode(AtomsAsLines, 'Lines', 'Mapper')
molkitlib.addNode(Cartoon, 'Cartoon', 'Mapper')
molkitlib.addNode(Surface3Dmol, 'Surface', 'Mapper')
molkitlib.addNode(AtomsAsMSMS, 'MSMS', 'Mapper')
molkitlib.addNode(WriteMolecule, 'Write PDB', 'Output')
