# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Builds wewos/static/colormaps.json, the presets of the colormap editor:
WEWoS's named ramps (rgb, rwb, grey, rainbow, resampled to 128 colors) and
the color maps distributed with MGLTools (ViewerFramework/ColorMaps/*_map.py,
read without running them).

    bin/wewos-python tools/ports/make_colormaps.py [MGLToolsPckgs/ViewerFramework/ColorMaps]
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import numpy  # noqa: E402

from wewos.colormaps import read_vision  # noqa: E402
from wewos.libs.viz3d import _RAMPS  # noqa: E402

SOURCE = '/export/people/sanner/dev/MakeInstallers/python2.7/MGLToolsPckgs/ViewerFramework/ColorMaps'


def resample(cols, n=128):
    c = numpy.asarray(cols, 'f')
    x = numpy.linspace(0, len(c) - 1, n)
    i = numpy.minimum(x.astype(int), len(c) - 2)
    f = (x - i)[:, None]
    out = c[i] * (1 - f) + c[i + 1] * f
    return [[round(float(v), 4) for v in row] + [1.0] for row in out[:, :3]]


def main(src):
    presets = [{'name': k, 'ramp': resample(v)} for k, v in _RAMPS.items()]
    for f in sorted(glob.glob(os.path.join(src, '*_map.py'))):
        with open(f) as fh:
            cm = read_vision(fh.read())
        name = os.path.basename(f)[:-len('_map.py')]
        ramp = cm['ramp']
        if name == 'rwb256' and ramp[0][:3] == [1.0, 0.0, 0.0]:
            ramp[0] = list(ramp[1])        # a slip in MGLTools' file: the ramp starts blue
        presets.append({'name': name, 'ramp': ramp, 'from': 'MGLTools'})
    out = os.path.join(ROOT, 'wewos', 'static', 'colormaps.json')
    with open(out, 'w') as fh:
        json.dump({'presets': presets}, fh, separators=(',', ':'))
    print('wrote %s: %s' % (out, ', '.join('%s (%d)' % (p['name'], len(p['ramp'])) for p in presets)))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else SOURCE)
