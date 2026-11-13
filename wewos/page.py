# Author: Michel Sanner, PhD. Copyright (c) 2026. Page conventions from ADapt /
# ADCP_docking (BSD 3-Clause); see THIRD_PARTY_NOTICES.md.
"""The web page: one HTML file, plain JavaScript, no build step, no network
access at run time (3Dmol.js is bundled)."""
from . import APP, APP_LONG, COPYRIGHT, __version__

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__APP__</title>
<script nonce="__NONCE__">try { const t = localStorage.getItem("wewos.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {}</script>
<link rel="stylesheet" href="static/app.css?v=__V_CSS__">
</head><body>
<header>
  <b>__APP__</b>
  <div class=menubar>
    <button id=m_file class=plainbtn>File &#9662;</button>
    <button id=m_edit class=plainbtn>Edit &#9662;</button>
    <button id=m_libs class=plainbtn title="load node libraries">Libraries&hellip;</button>
  </div>
  <span class=sep></span>
  <button id=b_run title="Soft run: run the nodes that have new data (Vision's run)">&#9654; Run</button>
  <button id=b_hardrun title="Hard run: run every node">&#9193; Run all</button>
  <button id=b_pause title="Pause / resume">&#10073;&#10073;</button>
  <button id=b_stop title="Stop after the current node">&#9632;</button>
  <label class=chk title="Run a node's subtree when its widget or input changes"><input type=checkbox id=b_auto checked> run on change</label>
  <span id=execstatus class=pill>idle</span>
  <button id=isolation class="pill iso" hidden title="how this network is isolated; click to change"></button>
  <span class=grow></span>
  <select id=sessions title="Open networks"></select>
  <a class=btn href="docs/index.html" target=_blank rel=noopener>Docs</a>
  <button id=theme class=plainbtn title="light / dark">&#9681;</button>
</header>
<main>
  <aside id=palette>
    <input id=search type=search placeholder="Find a node" title="by name or category; from 3 letters on, also in the nodes' documentation" spellcheck=false autocomplete=off>
    <div id=libs></div>
  </aside>
  <section id=center>
    <nav id=tabs></nav>
    <div id=canvaswrap>
      <svg id=canvas tabindex=0></svg>
      <div id=hint class=dim>Drag nodes from the left. Drag from an output (right side of a node) to an input (left side) to connect.
        Right-click for menus. Shift-drag selects.</div>
    </div>
    <div id=hsplit title="drag to share the height between the network and the viewers"></div>
    <div id=viewers></div>
    <details id=logbox><summary>Log <span id=loglen class=dim></span>
      <button id=logclear class=plainbtn>clear</button></summary><pre id=log></pre></details>
  </section>
  <div id=splitter title="drag to resize"></div>
  <aside id=side>
    <div id=panel><p class=dim>Select a node to see its parameters.</p></div>
  </aside>
</main>
<footer><span id=status>&nbsp;</span><span class=grow></span>
  <span class=dim>__APP__ __VERSION__ &middot; __COPYRIGHT__ &middot; engine ported from MGLTools Vision/NetworkEditor
  &middot; viewers 3Dmol.js and Mol*</span></footer>
<div id=menu class=menu hidden></div>
<div id=modal hidden><div class=dialog><div class=dhead><b id=mtitle></b><span class=grow></span>
  <button id=mclose class=plainbtn>&#10005;</button></div><div id=mbody></div></div></div>
<input type=file id=fileopen accept=".json,.wnet.json" hidden>
<input type=file id=fileimport accept=".py" hidden>
<input type=file id=fileupload hidden>
<script src="static/3Dmol-min.js?v=__V_3DMOL__"></script>
<script nonce="__NONCE__">const STATIC_V = {'molstar.js': '__V_MOLSTAR__', 'molstar.css': '__V_MOLSTARCSS__',
                  'molstar-dark.css': '__V_MOLSTARDARK__', 'colormaps.json': '__V_COLORMAPS__'};</script>
<script src="static/widgets.js?v=__V_WIDGETS__"></script>
<script src="static/view3dmol.js?v=__V_VIEW3DMOL__"></script>
<script src="static/viewmolstar.js?v=__V_VIEWMOLSTAR__"></script>
<script src="static/viewer3d.js?v=__V_VIEWER__"></script>
<script src="static/editor.js?v=__V_EDITOR__"></script>
<script src="static/app.js?v=__V_JS__"></script>
</body></html>
"""


def _v(name):
    """Short md5 of a static file, so a changed file is never served from cache."""
    import hashlib
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', name)
    try:
        with open(path, 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:10]
    except OSError:
        return '0'


def csp(nonce):
    """The page's Content-Security-Policy. Its scripts come only from this
    server (and its two inline scripts carry the nonce), and it talks only to
    this server: text or a picture from a network cannot run script in the
    page, which holds the token, nor send anything elsewhere.

    'unsafe-eval' is there for Mol*: the WebAssembly glue in its bundle makes
    functions with new Function() when it loads. Nothing a network sends is
    evaluated: the page has no eval of its own, and the one eval of 3Dmol.js
    (callbacks given as strings) never sees a network's data (view3dmol.js
    plainScene())."""
    return ("default-src 'self'; script-src 'self' 'nonce-%s' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' data: blob:; "
            "worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'" % nonce)


def render(nonce=''):
    import html
    return (PAGE.replace('__NONCE__', nonce).replace('__VERSION__', __version__)
                .replace('__APP_LONG__', html.escape(APP_LONG))
                .replace('__COPYRIGHT__', html.escape(COPYRIGHT).replace('(c)', '&copy;'))
                .replace('__APP__', html.escape(APP))
                .replace('__V_CSS__', _v('app.css'))
                .replace('__V_JS__', _v('app.js'))
                .replace('__V_EDITOR__', _v('editor.js'))
                .replace('__V_WIDGETS__', _v('widgets.js'))
                .replace('__V_VIEWER__', _v('viewer3d.js'))
                .replace('__V_3DMOL__', _v('3Dmol-min.js'))
                .replace('__V_VIEW3DMOL__', _v('view3dmol.js'))
                .replace('__V_VIEWMOLSTAR__', _v('viewmolstar.js'))
                .replace('__V_MOLSTARCSS__', _v('molstar.css'))
                .replace('__V_MOLSTARDARK__', _v('molstar-dark.css'))
                .replace('__V_COLORMAPS__', _v('colormaps.json'))
                .replace('__V_MOLSTAR__', _v('molstar.js')))
