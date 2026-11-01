# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The Python environment WEWoS runs in, and what it records about it.

The engine needs only Python 3.7+ and numpy. The Molecules library needs
MolKit2 and prody, and molecular surfaces need mslib (MSMS); the ADCP
distribution's `adcpsuite` env (Python 3.7) has all of them, which is what
bin/wewos looks for.
"""
import os
import subprocess
import sys


def check():
    """What is missing, as short messages; empty when everything is there."""
    missing = []
    for mod, why in (('numpy', 'the engine'), ('MolKit2', 'the Molecules library'),
                     ('prody', 'the Molecules library'),
                     ('mslib', 'molecular surfaces (MSMS)')):
        try:
            __import__(mod)
        except Exception:
            missing.append('%s (%s)' % (mod, why))
    return missing


def provenance():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        commit = subprocess.run(['git', '-C', here, 'rev-parse', 'HEAD'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                universal_newlines=True).stdout.strip() or None
    except OSError:
        commit = None
    import numpy
    return {'python': sys.version.split()[0], 'executable': sys.executable,
            'numpy': numpy.__version__, 'commit': commit}
