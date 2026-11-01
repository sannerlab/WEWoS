# Third-party notices

WEWoS is Copyright © 2026 Michel Sanner, PhD. It includes, adapts, or is derived from the
following software, which keeps its own licence and copyright.

## 3Dmol.js (bundled)

`wewos/static/3Dmol-min.js`, the 3D viewer: 3Dmol.js 2.5.5, BSD 3-Clause. Its licence texts are
bundled next to it: `wewos/static/3Dmol.LICENSE.txt` and `wewos/static/3Dmol-min.js.LICENSE.txt`.
Rego N, Koes D. 3Dmol.js: molecular visualization with WebGL. *Bioinformatics* 31(8):1322-1324,
2015.

## MGLTools (ported code)

`wewos/engine/` (datatypes, ports, nodes, network scheduler, macros, node libraries) is a
Python 3 port of MGLTools NetworkEditor and Vision, and `wewos/libs/standard.py` of
Vision/StandardNodes.py. Original authors: Michel Sanner and Daniel Stoffler, The Scripps
Research Institute, Molecular Graphics Laboratory (revisions by Guillaume Vareille).
`wewos/libs/viz3d.py` and `wewos/libs/molecules.py` replace DejaVu/VisionInterface and
MolKit/VisionInterface, keeping their node and port names. The MGLTools packages were
distributed under the MGLTools license (TSRI); see the license shipped with MGLTools.

## symserv, Volume and mglutil.math (ported and bundled code)

`wewos/symserv/` (symOperators, spaceGroups, utils) and `wewos/libs/symserv.py` are Python 3
ports of MGLTools symserv by Michel Sanner (TSRI), under the MGLTools license
(`wewos/symserv/LICENSE`).

`wewos/volcore/` (Grid3D, IO, Operators) is MGLTools Volume (Michel Sanner and others, TSRI)
in the Python 3 version of the ADFR/ADCP distribution, with what still failed under Python 3
fixed; `wewos/libs/volume.py` is a port of Volume/VisionInterface/VolumeNodes.py. MGLTools
license (`wewos/volcore/LICENSE`). Isocontouring, blurring, signed distances and meshing call
the UTpackages (University of Texas, CVC) of the environment, which are not included.

`wewos/libs/imaging.py` is a port of Vision/PILNodes.py; it uses Pillow from the environment.

`wewos/libs/mpl.py` is a port of Vision/matplotlibNodes.py (Michel Sanner, Daniel Stoffler,
Sowjanya Karnati, TSRI), with Vision/colours.py and Vision/posnegFill.py folded in; MGLTools
license. It uses matplotlib from the environment (matplotlib license, PSF-based).

`wewos/mglmath/` holds rotax, transformation, VectorModule, TensorModule, crystal and stats
from MGLTools mglutil.math (Python 3 versions from the ADFR/ADCP distribution, with removed
numpy calls updated), under the GNU LGPL as stated in their headers.

## ADCP_docking (adapted code)

The web server pattern (`adapt/server.py`: a standard-library server on localhost with a URL
token, JSON routes, static files), the page conventions (`adapt/page.py`,
`wewos/static/app.js`), and the RCSB fetch (`adapt/fetch.py`) were adapted from ADCP_docking,
https://github.com/aadhilhaq/ADCP_docking, under this licence:

```
BSD 3-Clause License

Copyright (c) 2026, Aadhil Haq and Sandun Fernando, HOPE Lab, Texas A&M University

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## MolKit2, ProDy, mslib (used, not included)

The Molecules library uses MolKit2, ProDy and mslib (MSMS) from the Python environment it runs
in (the ADCP distribution's adcpsuite env); they are not included here and keep their own
licences.
