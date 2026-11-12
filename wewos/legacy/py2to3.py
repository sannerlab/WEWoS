# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Python 2 to 3 conversion for Vision code: whole modules and the node
source code Vision kept in strings (doit functions, port callbacks), which a
plain 2to3 run leaves untouched.

Tabs are expanded first (Python 2 read a tab as up to 8 columns; Python 3
refuses mixed indentation), then lib2to3's fixers run (fissix's, the same
code, on Python 3.13 and later). Code strings are found
as string literals whose text starts with 'def ' and converted the same way.
"""
import ast
import io
import re
import tokenize
import warnings

_TOOL = None

# fixers that only add noise for this code
_SKIP = {'lib2to3.fixes.fix_ws_comma', 'lib2to3.fixes.fix_idioms',
         'lib2to3.fixes.fix_set_literal', 'lib2to3.fixes.fix_buffer',
         'lib2to3.fixes.fix_callable',
         # done by _fix_types: 2to3 maps StringType to bytes, wrong for this code
         'lib2to3.fixes.fix_types'}

_TYPES = {
    'StringType': 'str', 'UnicodeType': 'str', 'StringTypes': '(str,)',
    'IntType': 'int', 'LongType': 'int', 'FloatType': 'float',
    'BooleanType': 'bool', 'ComplexType': 'complex',
    'ListType': 'list', 'TupleType': 'tuple', 'DictType': 'dict',
    'DictionaryType': 'dict', 'NoneType': 'type(None)', 'TypeType': 'type',
    'ClassType': 'type', 'InstanceType': 'object', 'ObjectType': 'object',
    'FileType': 'io.IOBase', 'SliceType': 'slice', 'XRangeType': 'range',
}


def _fix_types(src):
    return re.sub(r'\btypes\.(%s)\b' % '|'.join(sorted(_TYPES, key=len, reverse=True)),
                  lambda m: _TYPES[m.group(1)], src)


def _tool():
    """lib2to3's refactoring tool; from Python 3.13 on, where lib2to3 is gone,
    the same code from fissix (pip install fissix)."""
    global _TOOL
    if _TOOL is None:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                import lib2to3.refactor as refactor
                pkg = 'lib2to3'
            except ImportError:
                import fissix.refactor as refactor
                pkg = 'fissix'
        skip = {f.replace('lib2to3.', pkg + '.', 1) for f in _SKIP}
        fixers = [f for f in refactor.get_fixers_from_package(pkg + '.fixes') if f not in skip]
        _TOOL = refactor.RefactoringTool(fixers, {'print_function': False})
    return _TOOL


def expand_tabs(src):
    return '\n'.join(_expand_line(l) for l in src.split('\n'))


def _expand_line(line):
    # only leading whitespace matters for indentation; keep the rest as is
    m = re.match(r'[ \t]*', line)
    lead = m.group(0)
    if '\t' not in lead:
        return line
    return lead.expandtabs(8) + line[len(lead):]


def convert(src, name='<string>'):
    """Python 3 source for Python 2 source (raises SyntaxError if lib2to3
    cannot parse it)."""
    src = _fix_types(expand_tabs(src))
    if not src.endswith('\n'):
        src += '\n'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        tree = _tool().refactor_string(src, name)
    return str(tree)


def is_py3(src):
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def convert_code(code):
    """Convert one code string (a doit or callback) if it is not already valid
    Python 3 with Python 3 meaning; returns (new_code, changed)."""
    if not code or not code.strip():
        return code, False
    try:
        new = convert(code)
    except Exception:
        return code, False
    new = _post(new)
    return new, new != code


_PIL = ('Image', 'ImageChops', 'ImageColor', 'ImageDraw', 'ImageEnhance', 'ImageFile',
        'ImageFilter', 'ImageFont', 'ImageOps', 'ImagePalette', 'ImageStat', 'ImageTk')


def _none_tests(src):
    """x == None -> x is None, x != None -> x is not None (outside strings and
    comments). With Numeric, an array compared to None was False; with numpy
    it is an array of booleans, and `if a == None:` raises an error."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src
    edits = []
    for i, t in enumerate(toks[:-1]):
        if t.type == tokenize.OP and t.string in ('==', '!=') and \
                toks[i + 1].type == tokenize.NAME and toks[i + 1].string == 'None':
            edits.append((t.start, t.end, 'is' if t.string == '==' else 'is not'))
    if not edits:
        return src
    lines = src.split('\n')
    for (r0, c0), (r1, c1), new in reversed(edits):        # an operator is on one line
        l = lines[r0 - 1]
        pre = '' if c0 == 0 or l[c0 - 1] == ' ' else ' '
        post = '' if c1 < len(l) and l[c1] == ' ' else ' '
        lines[r0 - 1] = l[:c0] + pre + new + post + l[c1:]
    return '\n'.join(lines)


def _post(src):
    src = _none_tests(src)
    # PIL's modules moved into the PIL package (Pillow)
    src = re.sub(r'^(\s*)import (%s)\s*$' % '|'.join(_PIL), r'\1from PIL import \2', src, flags=re.M)
    src = re.sub(r'^(\s*)from (%s) import' % '|'.join(_PIL), r'\1from PIL.\2 import', src, flags=re.M)
    # map(None, a, b) is zip_longest in Python 3; 2to3 leaves it alone
    src = re.sub(r'\bmap\(None,\s*', '_zip_longest(', src)
    if '_zip_longest(' in src and 'import zip_longest' not in src:
        # keep the def first in the string: insert the import inside the function
        lines = src.split('\n')
        for i, l in enumerate(lines):
            if l.lstrip().startswith('def '):
                # after the signature, which may span several lines
                j = i
                while j < len(lines) - 1 and not lines[j].rstrip().endswith(':'):
                    j += 1
                nxt = lines[j + 1] if j + 1 < len(lines) else '    '
                indent = re.match(r'\s*', nxt).group(0) or '    '
                lines.insert(j + 1, indent + 'from itertools import zip_longest as _zip_longest')
                break
        src = '\n'.join(lines)
    return src


_STR = re.compile(r'''(?P<q>"""|\'\'\')(?P<body>.*?)(?P=q)''', re.S)


def convert_module(src, name='<module>'):
    """Convert a module and the code strings inside it. Returns
    (new_source, report) where report lists the code strings converted."""
    report = []
    new = convert(src, name)

    def repl(m):
        body = m.group('body')
        if not body.lstrip().startswith('def '):
            return m.group(0)
        conv, changed = convert_code(body)
        if changed:
            report.append(body.strip().split('\n')[0][:60])
        return m.group('q') + conv + m.group('q')

    new = _STR.sub(repl, new)
    return _post(new), report


def tokens_ok(src):
    try:
        list(tokenize.generate_tokens(io.StringIO(src).readline))
        return True
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return False
