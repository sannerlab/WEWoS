# WEWoS: Web Enabled Workflow System

WEWoS, the **W**eb **E**nabled **Wo**rkflow **S**ystem, ports Vision, the visual programming environment of MGLTools (first presented as ViPEr in 2002, see [History](#history)), to the web: workflows are networks of nodes, built and run in a browser.
- **Server:** a Python 3 port of the NetworkEditor/Vision engine runs on a local server.
- **Browser:** draws the network editor and the 3D viewers, which replace DejaVu. Each viewer draws with [3Dmol.js](https://3dmol.csb.pitt.edu) (the default) or [Mol\*](https://molstar.org) (ambient occlusion, shadows, depth of field, illumination), switched in the viewer's header.

It follows ADapt's approach: a standard-library HTTP server bound to localhost with a URL token, plain JavaScript with no build step, and bundled viewers (3Dmol.js, and Mol\* loaded the first time a viewer uses it).

## Start

```
bin/wewos serve            # prints http://127.0.0.1:8767/?t=...   open it in a browser
bin/wewos check            # what is missing (MolKit2, prody, mslib for the Molecules library)
bin/wewos test             # the test suite
```

`bin/wewos` needs a Python 3 environment with numpy. The Molecules library also needs MolKit2, prody and mslib, which the ADCP distribution's `adcpsuite` env provides. Each network keeps its own folder under `~/wewos_runs` (`$WEWOS_OUTDIR`), holding uploads, saved networks and an autosave.

To use it from another machine, forward the port: `ssh -L 8767:127.0.0.1:8767 host`, then open the printed URL locally.

## Documentation

The page's **Docs** button opens the documentation (`docs/*.html`, served by the server at `/docs/`; the files also open directly in a browser). It has the guide to the page, the reference, and **tutorials** that follow the Vision tutorial of MGLTools 1.5.3 (Michel Sanner and Guillaume Vareille, 2008) step by step: a first network, an image viewer, a movie player with iterate and file lists, macros, a poliovirus capsid from one protomer, an icosahedral cage, and volumes (a CT scan, isosurfaces colored by radius, a capsid map cut open, a molecule blurred into a map). Their networks and data are the example group *Vision tutorial (MGLTools 1.5.3)*.

- `docs/src/<page>.html` holds each page's content; `python3 docs/build_docs.py` wraps it in the layout (navigation, previous/next, footer) and checks images and links, as ADapt's docs do.
- `bin/wewos-python docs/make_screenshots.py [scene ...]` remakes every picture in `docs/img/` from WEWoS itself, in a headless Chrome.
- `bin/wewos-python examples/make_tutorial_examples.py [--check]` rebuilds `examples/tutorial/` from the tutorial's networks and data.

## Using it

- **Add nodes:** drag them from the palette, or double-click a palette entry. *Find a node* searches the loaded libraries by node or category name and, from three letters on, in the nodes' documentation (those matches are tagged *doc*). While you drag, the node is drawn under the cursor, with its ports and widgets, at the network's zoom and where it will land.
- **Connect:** drag from an **output** (the right edge of a node) to an **input** (the left edge). Compatible ports light up while you drag.
- **Widgets:** an input with a widget shows it on its row in the node, or in the parameter column on the right. To feed it from another node instead, right-click the widget and choose *Unbind (show the port)*: the input becomes a port you can connect (right-click the port, *Rebind widget*, to get the widget back). Changing a widget runs the node's subtree when *run on change* is checked.
- **Number widgets:** scroll over one (mouse wheel or two-finger trackpad) or drag its ⇄ handle to change the value. Shift gives finer steps and Alt/Option coarser ones. Right-click one and choose *Options…* to set its minimum, maximum, step, one turn and precision (Vision's option panel).
- **Run:** **Run** runs the nodes that have new data, as Vision's run did. **Run all** runs every node. **Pause** and **Stop** act after the current node.
- **Edit a node's code:** use the panel's *Edit code…* or double-click the node. The compute function's arguments are the input ports.
- **Add ports:** *Add a port* in the panel adds an input or output port. A Generic node plus your own ports and code is a new node.
- **Macros:** select nodes, then right-click > *Group into a macro*. Double-click a macro to open its network in a tab. Inside it, connect to port `new` of the input or output node to add a macro port.
- **Layout:** the network is in the upper left, the node parameters in a column on its right, and the 3D viewers and image panels in a row under the network, from left to right. Drag the divider above that row to share the height with the network, use ⇕ to give the viewers the network's height too, or ⤢ to fill the window (Esc to come back); the splitter left of the parameter column sets its width. The sizes are remembered in the browser.
- **3D viewing:** a Viewer node opens a 3D panel, drawn with 3Dmol.js or Mol\* (the menu in the panel's header). Click an atom or shape and the Viewer's `lastPick` output carries what you clicked to the connected nodes, for example *Picked Atom*. Rotating or zooming the view fires its `redraw` output, as DejaVu's redraws did, so a *One Redraw* → *Grab Image* chain follows the view (see *ViPEr paper figure 1*).
- **Files:** File > Save writes `<name>.wnet.json` in the network's folder. *Open network* reads one back. *Download* gets the network or the whole folder.
- **Examples:** File > *Open an example…*. *poliovirus capsid* fetches PDB 2PLV, builds a coarse surface of one protomer and draws it 60 times with the file's icosahedral matrices, in a Mol\* viewer (it needs the RCSB the first time; the file is then cached in the network folder). The group *Vision tutorial (MGLTools 1.5.3)* holds the networks of the tutorials in the documentation and the tutorial's data (`examples/make_tutorial_examples.py`), with *start here*, an empty network whose folder has the data. Two more groups are the examples that came with MGLTools Vision, converted with the importer (`examples/make_vision_examples.py`): *Vision examples* (cpk, icos, image filters, and *ViPEr paper figure 1*, the network of figure 1 of the 2002 paper, see [History](#history)) and the 44 *Vision matplotlib examples*, with their data files.

## Libraries

Libraries load on demand, as in Vision. When the server starts, only Standard (and any library marked *at start*) is in the palette; **Libraries…** (or *+ Load a library…* under the palette) loads the others. Opening a network, an example or an imported Vision network loads the libraries it uses. Your own libraries load the same way: give a module name or a `.py` file on the server that creates a `NodeLibrary` (`from wewos.engine import NodeLibrary, NetworkNode`). They are remembered in `libraries.json` in the networks folder.

| Library | Contents |
|---|---|
| Standard | the 75 nodes of Vision's StandardNodes that do not drive Tk: input widgets, Python (iterate, while, accum, eval, map…), logic, filters, numpy |
| 3D Visualization | Viewer, Spheres, Cylinders, IndPolygons (meshes), IndPolylines, labels, box, axis, groups, mesh reader, and Color Map with Vision's color map editor in its parameter panel (draw the ramp's red, green, blue or hue, saturation, value/luminance, and opacity as curves: left button freehand, Shift-click a straight segment from the last point, right button a line; presets including MGLTools' color maps; min/max; undo (Ctrl/Cmd+Z) and reset; read and write Vision colormap files). Its legend output, connected to a Viewer, draws the color bar with its range and name over the 3D view, as DejaVu's legend did: drag it to move it, right-click it for vertical or horizontal, the number of values, size, title and frame; it is in the viewer's pictures (camera button, Grab Image) and kept with the network. This replaces DejaVu's vizlib, and the port names are DejaVu's. The viewer draws silhouettes and fog (depth cueing), on by default; its &#9680; button sets their width, color and depth range, and node code can call `viewer.setRendering(...)`. |

**Mol\* viewers.** The menu in a viewer's header switches it between 3Dmol.js (the default) and Mol\* (node code: `viewer.setRenderer('molstar')`); the choice, a camera for each renderer, and Mol\*'s rendering settings are saved with the network. Mol\* is loaded the first time a viewer uses it (1.5 MB). It brings Mol\*'s rendering: ambient occlusion (on by default), shadows, outlines, depth of field, bloom, fog, and its illumination mode, set with the settings (sliders) and illumination buttons in its view; the &#9680; button gives quick switches for the main ones. Its other buttons reset the camera, take a screenshot, and open Mol\*'s own panels (sequence, state tree). The scene is the network's: what you add in Mol\*'s panels is not saved, and a change in the network redraws the scene. All the geometries are drawn (molecules with their representations, colors and copies, spheres, cylinders, lines, meshes, labels), and picking works as in 3Dmol.

| Molecules | MolKit2: Read Molecule, Fetch PDB, Select (ProDy or MolKit syntax), atom properties, radii, CPK, Sticks, Lines, Cartoon, Surface (3Dmol), MSMS (mslib), Write PDB, Picked Atom, Assembly Matrices (the REMARK 350 BIOMT matrices of a PDB file: a virus capsid's 60 operators, for instanceMatrices) |
| Volume | Volume: read maps (AutoGrid, CCP4, MRC, CNS/XPLOR, DX, Delphi, GRD, BRIX, SPIDER, UHBD, Rawiv, AVS/FLD, numpy), write CCP4/Rawiv, statistics, masks, clipping, transforms, resampling, Gaussian blurring of molecules (UT blur), isocontouring with its contour spectrum (UTiso, UT-Isocontour), signed distance, meshing, orthogonal slices drawn as colored meshes, bounding boxes, a coarse molecular surface macro (CoarseMolSurf, with an input for symmetry copies). Volume rendering and QSlim decimation are not ported. |
| Imaging | Pillow: read, save, filter, invert, split, mask, paste, blend, multiply, composite, rotate, transpose, scale, statistics; Show Image shows an image in a panel of the page, Grab Image takes a snapshot of a 3D viewer. |
| MatPlotLib | matplotlib: plot, scatter, histogram, bar, barh, pie, polar, fill, log plots, stem, error bars, box plots, contour, pcolor, spectral plots (PSD, CSD, specgram, cohere), quiver, table, legend, text, color bar, Figure (several plots side by side), MultiPlot (plots overlaid), saving figures. Each plot is drawn off screen and shown in a panel of the page. Set Matplotlib Options takes its options as a dict; Vision's navigation toolbar is not ported. |
| SymServer | symserv: n-fold axes (2- to 6-fold and N-fold), helix, super-helix, rotate, translate, orient, scale, merge, multiply, split, inverse, transpose, the Icosahedral1 and IcosCage macros, reading and saving matrices. Its matrices go to the `instanceMatrices` input of a geometry, or of a molecule's CPK/Sticks/Lines/Cartoon/Surface/MSMS node, which draws one copy per matrix. |

## Vision networks (`*_net.py`)

File > *Import a Vision network* (or `bin/wewos import old_net.py`) converts a saved Vision network to the WEWoS format. The file is **not executed**: it is parsed after a Python 2 → 3 syntax conversion, and only what the generated files do is interpreted. That covers libraries, nodes, widget values, edited code, ports added to nodes, user macros and connections.

How nodes come across:
- Nodes of the Standard, DejaVu, MolKit, symserv, Volume, Imaging (Vision.PILNodes) and MatPlotLib (Vision.matplotlibNodes) libraries map onto the WEWoS libraries (`wewos/legacy/classmap.py`); settings inside library macros (e.g. UTiso's isovalue) come along.
- Other nodes become placeholders that keep their name, ports and code. They show in red and do not run.
- Edited compute functions are converted to Python 3 and kept for Standard nodes.
- Vision drew data flowing down the page. Imported networks, and the macros of the ported libraries (Icosahedral1, UTIsoMac…), are laid out again from left to right: nodes go in columns by their depth in the graph, ordered to keep links straight. *Edit > Arrange the nodes from left to right* does the same for any network.

The import report lists what was not carried over. All 76 networks in `/home/sanner/*_net.py` import and open.

## Layout

```
bin/wewos                 launcher (finds the adcpsuite env)
wewos/engine/             the Vision engine in Python 3: types, ports, nodes, network scheduler,
                          macros, widgets as data, event stream, file format
wewos/libs/               standard.py, viz3d.py, molecules.py, symserv.py, volume.py, imaging.py,
                          mpl.py (MatPlotLib)
wewos/symserv/            symserv's operators (Python 3)
wewos/volcore/            Volume's core (Grid3D, readers, writers, operators), Python 3
wewos/mglmath/            the mglutil.math modules symserv and Volume use
wewos/geom.py             geometry without OpenGL (what DejaVu geometries were to nodes)
wewos/legacy/             py2to3 conversion and the *_net.py importer
wewos/server.py, session.py, page.py, static/   the web server and page (static/viewer3d.js: the viewer
                          panels; view3dmol.js and viewmolstar.js: the two renderers)
examples/                 example networks (make_examples.py rebuilds them); vision/ and
                          vision_matplotlib/: Vision's examples (make_vision_examples.py);
                          tutorial/: the Vision tutorial's networks and data (make_tutorial_examples.py)
docs/                     the documentation: src/ (page contents), build_docs.py, make_screenshots.py, img/
tests/                    bin/wewos test
```

## What is different from Vision

The engine keeps Vision's semantics: soft and hard runs, blocking connections, breadth-first scheduling, `Stop`, scheduling nodes (iterate, while), macros, port types with shapes, casting and missing-dimension handling. It also keeps the node-definition API (`inputPortsDescr`, `widgetDescr`, `setFunction`, `outputData`).

Some things changed:
- **No Tk.** Widgets are data drawn by the page.
- **One run at a time.** Runs execute on a server thread. Changing a widget during a run queues another run.
- **Not ported:**
  - user panels;
  - the libraries that are not listed above (ImageMagick, FlexTree, ADT, WebServices, Pmv…);
  - DejaVu textures, volume rendering, stereo and clip planes.

Node code runs on the server with your rights, as it did in Vision. The server listens on 127.0.0.1 only, and the token in the URL keeps other users of the machine out.

## History

Vision began as **ViPEr**, a Visual Programming Environment for Python, written by Michel Sanner, Daniel Stoffler and Arthur Olson in the Molecular Graphics Lab of The Scripps Research Institute. It was presented at the 10th International Python Conference (February 2002), where it received the best paper award:

> Michel F. Sanner, Daniel Stoffler, Arthur J. Olson. *ViPEr, a Visual Programming Environment for Python.* 10th International Python Conference, 2002. <https://legacy.python.org/workshops/2002-02/papers/10/index.htm>

It was later renamed Vision, because of a name conflict at Scripps with VIPER, the Virus Particle Explorer of Charles Brooks's lab, and distributed with MGLTools, with NetworkEditor as its engine.

The paper describes the design WEWoS keeps: nodes that wrap Python functions, ports colored and shaped by data type, any Python object flowing on connections, data-driven breadth-first scheduling, widgets bound to input ports, macros, libraries of nodes (Standard, Imaging, MolKit, symserv), and networks saved as Python code, which is why Vision's `*_net.py` files can be read here. The network of the paper's figure 1 (crambin's MSMS surface, transparent, over its atoms with radii scaled by a dial and colored by their x coordinate, and the viewer's picture grabbed and contour-filtered) runs here as the example *ViPEr paper figure 1*; its icosahedral capsid built with symserv is close to the *icos* example.

## Licences

See THIRD_PARTY_NOTICES.md. The engine and libraries are ported from MGLTools (Michel Sanner, Daniel Stoffler, TSRI). 3Dmol.js is BSD 3-Clause; Mol\* is MIT. The server and page conventions come from ADapt and ADCP_docking (BSD 3-Clause).
