"""Builds wewos/libs/volume.py from the Python 3 conversion of
MGLTools Volume/VisionInterface/VolumeNodes.py (one-time port script)."""
import re
import sys

src_path, out_path = sys.argv[1], sys.argv[2]
s = open(src_path).read()


import ast


def drop_stmts(s, pred, what, expect=None):
    """Remove the module-level statements for which pred(node, text) is true
    (whole statements, found with the syntax tree: docstrings may have
    unindented lines, so text patterns cannot find where a class ends)."""
    tree = ast.parse(s)
    lines = s.split('\n')
    spans = []
    for node in tree.body:
        start = node.lineno - 1
        if getattr(node, 'decorator_list', None):
            start = min(d.lineno for d in node.decorator_list) - 1
        text = '\n'.join(lines[start:node.end_lineno])
        if pred(node, text):
            spans.append((start, node.end_lineno))
    if expect is not None and len(spans) != expect:
        raise SystemExit('%s: %d statements matched, expected %d' % (what, len(spans), expect))
    for a, b in reversed(spans):
        del lines[a:b]
    return '\n'.join(lines)


def drop_class(s, name):
    return drop_stmts(s, lambda n, t: isinstance(n, ast.ClassDef) and n.name == name,
                      'class ' + name, 1)


def sub1(s, old, new):
    if old not in s:
        raise SystemExit('not found: %r' % old[:80])
    return s.replace(old, new, 1)


# ---- header ---------------------------------------------------------------------------
s = re.sub(r'^#{20,}\n(#.*\n)*?#{20,}\n', '', s, count=1, flags=re.M)
s = re.sub(r'^#\n# \$Header.*?\n#\n# \$Id.*?\n#\n', '', s, count=1, flags=re.M | re.S)
HEADER = '''# Ported to Python 3 from MGLTools Volume/VisionInterface/VolumeNodes.py
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
'''

s = sub1(s, 'import tkinter\n', '')
# the GAMESS reader is still Python 2 in the environment; its node was not
# registered in Vision either
s = sub1(s, 'from Volume.IO.gamessOrbitalsReader import ReadGamessOrbitals\n', '')
s = sub1(s, 'from NetworkEditor.items import NetworkNode\nfrom Vision import UserLibBuild\n',
         'from wewos.engine import MacroNode, NetworkNode, NodeLibrary\n'
         'from wewos.engine.datatypes import AnyType\n'
         'from wewos import geom as G\n'
         'from wewos.libs.viz3d import GeometryNode, colormap\n'
         'from wewos.libs.molecules import atoms_of, radii as radii_of\n')
s = sub1(s, 'from mglutil.gui.BasicWidgets.Tk.customizedWidgets import ListChooser\n'
            'from mglutil.gui.InputForm.Tk.gui import InputFormDescr, InputForm, CallBackFunction\n', '')
s = sub1(s, 'from DejaVu.Box import Box\nfrom DejaVu.VisionInterface.GeometryNodes import GeometryNode\n', '')

# importMolKitLib / importVizLib: nothing to load here
for fn in ('importMolKitLib', 'importVizLib'):
    i = s.index('def %s(net):' % fn)
    j = min(k for k in (s.find('\ndef ', i + 5), s.find('\nclass ', i + 5),
                        s.find('\ntry:', i + 5)) if k > 0)
    s = s[:i] + 'def %s(net):\n    """MGLTools loaded a library into the editor here."""\n\n' % fn + s[j:]

# module-level DejaVu imports in the middle of the file
s = drop_stmts(s, lambda n, t: isinstance(n, ast.Try) and 'DejaVu.VisionInterface.GeometryNodes' in t,
               'GeometryNode import', 1)
s = re.sub(r'\nfrom DejaVu\.bitPatterns import patternList\n', '\n', s)
s = re.sub(r'\nfrom DejaVu\.VisionInterface\.GeometryNodes import GeometryNode\n', '\n', s)

# macros reference classes of this module directly
s = re.sub(r'\n *from Volume\.VisionInterface\.VolumeNodes import \w+', '', s)

# ---- classes rewritten or dropped -------------------------------------------------------
for name in ('OrthoSlice', 'BoundingBox', 'UTVolRen', 'ReadAnyMap', 'UT_Iso', 'UT_IsoDecim',
             'CoarseMolSurf', 'PmvGridChooser'):
    s = drop_class(s, name)

# ---- MolKit -> MolKit2 in node code ---------------------------------------------------------
s = sub1(s, """    from MolKit.chargeMass import getChargeMass
    elist, totmass = getChargeMass(atoms)
    volarr, origin, s = blurSpheres(atoms.coords, elist, totmass,""",
         """    mol, sel = atoms_of(atoms)
    elist, totmass = get_charge_mass(sel)
    volarr, origin, s = blurSpheres(sel.getCoords().tolist(), elist, totmass,""")
s = sub1(s, """    from MolKit.molecule import Atom
    atoms = molFrag.findType(Atom)
    coords = atoms.coords
    radii = atoms.radius""",
         """    mol, sel = atoms_of(molFrag)
    coords = sel.getCoords().tolist()
    radii = radii_of(mol, sel).tolist()""")
s = sub1(s, """    from MolKit.molecule import Atom
    atoms = molecFrag.findType(Atom)
    try:
        radii= atoms.radius
    except AttributeError:
        for m in molecFrag.top.uniq():
            m.defaultRadii()
        radii= atoms.radius
    assert len(atoms)==len(radii)

    maxr= max(radii)
    coords = atoms.coords[:]""",
         """    mol, sel = atoms_of(molecFrag)
    radii = radii_of(mol, sel)
    maxr= max(radii)
    coords = sel.getCoords().tolist()""")
s = s.replace("datatype='TreeNodeSet'", "datatype='AtomSet'")

# RegionBox drew a DejaVu Box
s = sub1(s, "self.bb = Box('regionBox', maxCube=[.5,.5,.5], minCube=[-.5,-.5,-.5])",
         "self.bb = G.IndexedPolylines('regionBox')")
i = s.index("    coords = (pt1, pt2)\n    if grid.crystal:\n        ptList=((pt2[0],pt2[1],pt1[2]),")
j = s.index("        self.bb.Set(cornerPoints=coords)\n", i) + len("        self.bb.Set(cornerPoints=coords)\n")
s = s[:i] + "    set_box(self.bb, pt1, pt2, grid.crystal)\n" + s[j:]

# the contour spectrum is computed when a new grid arrives (Vision waited
# for the "Calculate signatures" button), for grids of reasonable size
s = sub1(s, """                warnings.warn('%s: isovalue was outside data range, isovalue is now set to the mean'%self.name)
""", """                warnings.warn('%s: isovalue was outside data range, isovalue is now set to the mean'%self.name)
            if data.size <= 4000000:
                self.calculateSignatures()
""")
# the contour spectrum widget is drawn by the page
s = s.replace("'class':'NEContourSpectrum',", "'class':'NEContourSpectrum',")

# ---- library tail -------------------------------------------------------------------------------
i = s.index('vollib = NodeLibrary(')
lib = s[i:]
body = s[:i]
lib = sub1(lib, "vollib = NodeLibrary('volume', '#999999')",
           "vollib = NodeLibrary('Volume', '#B9A27A',\n"
           "                     doc='3D grids: read, transform, mask, blur, slice, isocontour')")
GONE = ('UT_Iso,', 'UT_IsoDecim', 'CoarseMolSurf', 'UTVolRen', 'ReadAnyMap,', 'OrthoSlice,',
        'BoundingBox,', 'ContourSpectrum', 'PmvGridChooser', 'UserLibBuild', 'import MolKit')
lib = drop_stmts(lib, lambda n, t: any(g in t for g in GONE) and
                 (isinstance(n, (ast.Try, ast.ImportFrom, ast.Import)) or
                  (isinstance(n, ast.Expr) and 'vollib.add' in t)), 'tail')
lib = lib.replace('from NetworkEditor.datatypes import AnyType\n', '')
# MoleculeBBGrid was registered only when MolKit imported
if "vollib.addNode(MoleculeBBGrid" not in lib:
    lib += "vollib.addNode(MoleculeBBGrid, 'Mol BB Grid', 'Mapper')\n"
# UT blur may need its wrapper loaded with tabs expanded
lib = lib.replace("    from UTpackages.UTblur import blur\n", "    blur = _utblur()\n")

def leftover(n, t):
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        return any(m in t for m in ('NetworkEditor', 'Vision', 'DejaVu', 'MolKit.'))
    if isinstance(n, ast.If):
        return 'foundGeometryNode' in t
    if isinstance(n, ast.Expr):
        return 'UserLibBuild' in t
    return False


body = drop_stmts(body, leftover, 'body leftovers')
lib = drop_stmts(lib, leftover, 'tail leftovers')

# the bundled Volume core and mglutil math
def localize(t):
    t = re.sub(r'\bfrom Volume\.', 'from wewos.volcore.', t)
    t = t.replace('from mglutil.math.crystal import', 'from wewos.mglmath.crystal import')
    t = t.replace('from mglutil.math.stats import', 'from wewos.mglmath.stats import')
    t = t.replace('from mglutil.math.rotax import', 'from wewos.mglmath.rotax import')
    return t


new_classes, register = open(sys.argv[3]).read().split('#--REGISTER--\n')
body, lib, new_classes = localize(body), localize(lib), localize(new_classes)
# Python 3 has no string.split
body = body.replace('\nfrom string import split\n', '\n')
body = body.replace("dimensions = split(dims, ',')", "dimensions = dims.split(',')")
out =HEADER + body.lstrip('\n') + '\n' + new_classes + '\n\n' + lib + '\n' + register
open(out_path, 'w').write(out)
print('wrote', out_path)
