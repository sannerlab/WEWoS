"""Builds wewos/libs/imaging.py from the Python 3 conversion of
MGLTools Vision/PILNodes.py (one-time port script)."""
import ast
import re
import sys

src_path, out_path = sys.argv[1], sys.argv[2]
s = open(src_path).read()


def drop_stmts(s, pred, what, expect=None):
    tree = ast.parse(s)
    lines = s.split('\n')
    spans = []
    for node in tree.body:
        start = node.lineno - 1
        text = '\n'.join(lines[start:node.end_lineno])
        if pred(node, text):
            spans.append((start, node.end_lineno))
    if expect is not None and len(spans) != expect:
        raise SystemExit('%s: %d matched, expected %d' % (what, len(spans), expect))
    for a, b in reversed(spans):
        del lines[a:b]
    return '\n'.join(lines)


s = re.sub(r'^#{20,}\n(#.*\n)*?#{20,}\n', '', s, count=1, flags=re.M)
HEADER = '''# Ported to Python 3 from MGLTools Vision/PILNodes.py
# Original: Michel Sanner, Daniel Stoffler (TSRI). Port: Michel Sanner, PhD. Copyright (c) 2026.
"""Imaging: read, filter, combine, measure and save images (PIL / Pillow).

Converted mechanically (wewos.legacy.py2to3), then: the old PIL module names
and calls are updated (Image.fromstring -> frombytes, import Image -> from
PIL import Image...); Show Image shows the image in a panel of the page
instead of a Tk window; Grab Image takes a snapshot of a 3D viewer from the
page instead of reading the OpenGL front buffer; the MPEG nodes (pymedia)
are not ported.
"""
'''

# old PIL names
s = s.replace('import Image, ImageTk\n', 'from PIL import Image\n')
s = re.sub(r'(\n\s*)import (Image|ImageFilter|ImageChops|ImageStat|ImageOps|ImageEnhance)\b',
           r'\1from PIL import \2', s)
s = s.replace('Image.fromstring(', 'Image.frombytes(').replace('.tostring()', '.tobytes()')
s = s.replace('import tkinter\n', '')
s = s.replace('from NetworkEditor.items import NetworkNode\n',
              'from wewos.engine import NetworkNode, NodeLibrary\n'
              'from wewos.engine.datatypes import AnyArrayType\n')
s = s.replace('from Vision import UserLibBuild\n', '')
s = s.replace('from Vision.VPE import NodeLibrary\n', '')

for name in ('GetFrontBuffer', 'GetZBuffer', 'ShowImage'):
    s = drop_stmts(s, lambda n, t, name=name: isinstance(n, ast.ClassDef) and n.name == name,
                   name, 1)
# the MPEG nodes (pymedia) and the type registrations from MGLTools packages
s = drop_stmts(s, lambda n, t: (isinstance(n, ast.Try) and ('pymedia' in t or 'UserLibBuild' in t))
               or (isinstance(n, ast.Expr) and 'UserLibBuild' in t), 'tail')

i = s.index("imagelib = NodeLibrary(")
body, lib = s[:i], s[i:]
lib = lib.replace("imagelib = NodeLibrary('Imaging', '#995699')",
                  "imagelib = NodeLibrary('Imaging', '#C38DB5',\n"
                  "                       doc='images with PIL: read, filter, combine, show, save')\n"
                  "imagelib.addType(ImageType())")
new = open(sys.argv[3]).read()
open(out_path, 'w').write(HEADER + body.lstrip('\n') + '\n' + new + '\n\n' + lib)
print('wrote', out_path)
