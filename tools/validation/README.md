# Validating WEWoS against MGLTools Vision

`validate.py` imports Vision networks (`*_net.py`) into WEWoS, opens them and runs them
without a page, runs the same files in MGLTools Vision 1.5.7, and compares the data on every
output port of every node.

```
VALIDATE_DISPLAY=:77 bin/wewos-python tools/validation/validate.py \
    "tutorial=$VISION/doc/Tutorial/*/*_net.py" \
    "examples=$VISION/doc/Examples/*_net.py" \
    "matplotlib=$VISION/doc/Examples/matplotlib/*_net.py" \
    --mgl ~/tools/mgl157 --jobs 4
```

- **Both sides:**
  - `run_wewos.py` (Python 3) and `run_vision.py` (Python 2.7, run with MGLTools' `bin/pythonsh`) each run one network and dump every output port with `canon.py`.
  - `canon.py` turns the data into numbers, strings and arrays, in the same way under both Pythons: images, geometry vertices and faces, molecule coordinates, and the lines, bars and points of matplotlib plots.
- **Sandbox:**
  - Each run happens in a bubblewrap sandbox: the file system is read-only except the network's scratch folder, which holds copies of the files its widgets name, and there is no network access.
  - The random generators are seeded the same way on both sides.
- **Vision's editor and Xvfb:**
  - Vision runs with its editor, hidden, on the X display that `VALIDATE_DISPLAY` names. Its viewers, color maps and geometry nodes need the editor.
  - Use a virtual display (Xvfb with GLX). Without one, Vision runs without its editor and those nodes give no reference.
- **Comparison:**
  - Ports are matched by node path (macros included) and port name, through the importer's port renames (`wewos/legacy/classmap.py`).
  - Arrays are compared with a relative tolerance of 1e-4, and images to within one level.
  - Lines of plots are compared without regard to their order.
  - The ports of nodes that are placeholders (libraries not ported), or that lie below one, are left out.
- **Results:** `DIR/<collection>.csv` has one row per network:
  - outcome category;
  - nodes and placeholders;
  - errors;
  - port counts: equal, different, only in Vision, not compared.

  `DIR/<collection>_ports.csv` lists the ports that differ, with both values and the largest difference.

`results/` holds the results for the networks distributed with MGLTools Vision (the tutorial and
the examples). Every difference there has a known cause; see the Validation section of the paper
and the notes below.

The results in `results/` were made with WEWoS in the `adcpsuite` environment (Python 3.7.12,
NumPy 1.21.6, Pillow 9.5.0, matplotlib 3.5.3) and MGLTools Vision 1.5.7 (Python 2.7.3,
NumPy 1.10.4, PIL 1.1.7, matplotlib 1.2.0).

## Known differences (tutorial and examples)

| Ports | Cause |
|---|---|
| 12 | mol2plv and icoscage edit the inside of SymServer's Icosahedral1 macro (a translation). The importer reports such edits and does not carry them over. |
| 7 | matplotlib 3.5 builds box plots, stem plots and scatter plots from other artists than matplotlib 1.2. Histogram flattens a 2-D input, where matplotlib 1.2 drew one histogram per row. |
| 5 | Pillow 9.5 and PIL 1.1.7 differ in nearest-neighbour resampling (about 10% of the pixels of a scaled image) and in JPEG decoding (up to 22 levels). |
| 1 | Grid3DBB gives a crystallographic map's corners in Å; Vision gave them in fractional coordinates. |
| 1 | OrthoSlice is a colored mesh; Vision drew a textured quad. |
