# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Shared helpers: a per-run output folder, small test nodes, network builders."""
import datetime
import os
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
warnings.filterwarnings('ignore')

from wewos.engine import Network, NetworkNode, get_library  # noqa: E402

# outputs of one test run, inside the repo (git-ignored), never /tmp
OUT = os.path.join(HERE, '_out', datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
DATA = os.path.join(HERE, 'data')


class Skip(Exception):
    """A test that cannot run here: a package it needs is not installed."""


def requires(*modules):
    """Skip the test when one of these modules does not import (MolKit2,
    mslib and UTpackages come only with the ADCP environment)."""
    import functools
    import importlib

    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **k):
            for m in modules:
                try:
                    importlib.import_module(m)
                except Exception:
                    raise Skip('needs %s' % m)
            return f(*a, **k)
        return wrapper
    return deco


def outdir(name):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    return d


def check(cond, msg=''):
    if not cond:
        raise AssertionError(msg or 'check failed')


def eq(a, b, msg=''):
    if a != b:
        raise AssertionError('%s: %r != %r' % (msg or 'not equal', a, b))


class Value(NetworkNode):
    """Outputs the value of its thumbwheel."""

    def __init__(self, name='value', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.widgetDescr['v'] = {'class': 'NEThumbWheel', 'master': 'node',
                                 'initialValue': 1.0}
        self.inputPortsDescr.append(datatype='float', name='v')
        self.outputPortsDescr.append(datatype='float', name='out')
        self.setFunction("def doit(self, v):\n    self.outputData(out=v)\n")


class Add(NetworkNode):
    def __init__(self, name='add', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.inputPortsDescr.append(datatype='float', name='a')
        self.inputPortsDescr.append(datatype='float', name='b', required=False,
                                    defaultValue=0.0)
        self.outputPortsDescr.append(datatype='float', name='sum')
        self.setFunction("def doit(self, a, b):\n    self.outputData(sum=a + b)\n")


class Record(NetworkNode):
    """Appends what it receives to self.got (and the run order to LOG)."""
    LOG = []

    def __init__(self, name='record', **kw):
        kw['name'] = name
        NetworkNode.__init__(self, **kw)
        self.got = []
        self.inputPortsDescr.append(datatype='None', name='x')
        self.outputPortsDescr.append(datatype='None', name='out')
        self.setFunction("def doit(self, x):\n    self.got.append(x)\n"
                         "    Record.LOG.append(self.name)\n    self.outputData(out=x)\n")


def net(*nodes):
    n = Network('test')
    n.runOnNewData.value = False
    for x in nodes:
        n.addNode(x)
    n.runOnNewData.value = True
    return n


def std(label, **kw):
    return get_library('Standard').instantiate(label=label, **kw)
