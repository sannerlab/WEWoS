# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The few mglutil/Vision helpers that node code imports, in Python 3.

`importMainOrIPythonMain()` returned the interactive namespace eval/assign
nodes work in; here each session has its own namespace (set on the thread
running its network), so two open networks do not share variables.
"""
import fnmatch
import inspect
import os
import tempfile
import threading
import zipfile

_tls = threading.local()
_GLOBAL_NS = {'__name__': '__wewos__'}


def set_namespace(ns):
    _tls.ns = ns


def importMainOrIPythonMain():
    ns = getattr(_tls, 'ns', None)
    return ns if ns is not None else _GLOBAL_NS


def isInstance(obj):
    """True for an instance of a user-defined class (what Python 2 called an
    InstanceType), False for builtins, classes and numpy arrays."""
    if inspect.isclass(obj):
        return False
    t = type(obj)
    return t.__module__ not in ('builtins', 'numpy') and not isinstance(
        obj, (int, float, str, bytes, list, tuple, dict, set))


def suppressMultipleQuotes(aString):
    simplified = aString
    while isinstance(aString, str):
        simplified = aString
        try:
            aString = eval(simplified)
        except Exception:
            break
    return simplified


def make_zip_file(input_directory, output_directory=None, output_name=None):
    if not os.path.exists(input_directory):
        print('ERROR: Input make_zip directory ' + input_directory + ' does not exist!')
        return 'stop'
    if output_name is None:
        name = os.path.basename(input_directory)
    else:
        name = os.path.basename(output_name.split('.zip')[0])
    if output_directory is None:
        output_directory = os.getcwd()
    zipname = os.path.join(output_directory, name + '.zip')
    abpath = os.path.abspath(input_directory)
    with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirnames, filenames in os.walk(abpath):
            for filename in fnmatch.filter(filenames, '*'):
                path = os.path.join(root, filename)
                z.write(path, os.path.join(name, os.path.relpath(path, abpath)))
    return zipname
