#!/usr/bin/env python3
# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Regenerate the documentation screenshots (docs/img/*.png) from WEWoS itself.

    bin/wewos-python docs/make_screenshots.py [scene ...]

Starts a WEWoS server in this process (port 0) and a headless Chrome, and for
each scene opens an example network, runs it, clicks through the page the way
a user would, and captures the window or a part of it. Every image in the
docs is a WEWoS screenshot made here, so they can be remade after the page
changes. The networks' folders go to ~/wewos_runs/docs_screenshots/, the
Chrome profile to tests/_out/docs_run/ (git-ignored); never /tmp.

Needs: google-chrome and the adcpsuite environment (MolKit2, prody, mslib).
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(HERE, 'tools'))
import cdp  # noqa: E402

IMG = os.path.join(HERE, 'img')
WORK = os.path.join(REPO, 'tests', '_out', 'docs_run')
SESSIONS = os.path.join(os.path.expanduser('~'), 'wewos_runs', 'docs_screenshots')
TUTORIAL = ('/export/people/sanner/dev/MakeInstallers/buildrc-1-5-7/sharedpackages/'
            'VisionDIST/Vision/doc/Tutorial')
W, H = 1440, 900

# Counts in-flight requests (the event poll excepted), so a scene waits for
# the page to finish talking to the server instead of sleeping.
INFLIGHT = """(() => { const f = window.fetch; window.__inflight = 0;
  window.fetch = function(...a){ const poll = String(a[0]).includes('api/events');
    if(!poll) window.__inflight++;
    return f.apply(this, a).finally(() => { if(!poll) window.__inflight--; }); }; })();"""

HELPERS = r"""
window.DOC = {
  id(name){ const n = Object.values(ST.nets[ST.cur].nodes).find(n => n.name === name);
            if(!n) throw new Error('no node ' + name); return n.id; },
  sel(name){ return '#canvas .node[data-id="' + DOC.id(name) + '"]'; },
  port(name, io, port){ return '#canvas .port[data-node="' + DOC.id(name) + '"][data-io="' + io + '"][data-port="' + port + '"]'; },
  center(sel){ const r = document.querySelector(sel).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; },
  rect(sel){ const e = typeof sel === 'string' ? document.querySelector(sel) : sel;
             if(!e) throw new Error('no element ' + sel);
             const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; },
  union(sels){ let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    sels.forEach(s => { const r = DOC.rect(s); x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y);
      x1 = Math.max(x1, r.x + r.width); y1 = Math.max(y1, r.y + r.height); });
    return {x: x0, y: y0, width: x1 - x0, height: y1 - y0}; },
  select(name){ ED.select([DOC.id(name)]); panel(); },
  context(sel, dx, dy){ const r = document.querySelector(sel).getBoundingClientRect();
    document.querySelector(sel).dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true,
      clientX: r.x + (dx == null ? r.width / 2 : dx), clientY: r.y + (dy == null ? r.height / 2 : dy)})); },
  menu(label){ const d = [...document.querySelectorAll('#menu div')].find(d => d.textContent === label);
    if(!d) throw new Error('no menu entry ' + label); d.click(); },
};
"""


class Page(object):
    def __init__(self):
        from wewos.server import build
        os.makedirs(WORK, exist_ok=True)
        os.makedirs(SESSIONS, exist_ok=True)
        self.httpd = build('127.0.0.1', 0, SESSIONS)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:%d/?t=%s' % (self.httpd.server_address[1], self.httpd.app.token)
        self.chrome, self.ws = cdp.start_chrome(os.path.join(WORK, 'chrome'), width=W, height=H)
        ws = self.ws
        ws.call('Page.enable')
        ws.call('Runtime.enable')
        ws.call('Emulation.setDeviceMetricsOverride', width=W, height=H, deviceScaleFactor=1, mobile=False)
        ws.call('Page.addScriptToEvaluateOnNewDocument', source=INFLIGHT +
                "try { localStorage.clear(); localStorage.setItem('wewos.theme', 'light'); } catch(e) {}")
        ws.call('Page.navigate', url=url)
        cdp.wait(ws, "typeof ST !== 'undefined' && !!ST.sid && document.querySelectorAll('.pnode').length > 0",
                 what='page load')
        self.js(HELPERS)
        self.idle()

    def js(self, expr):
        return cdp.js(self.ws, expr)

    def idle(self, settle=0.6):
        """No request in flight and the network idle for a short while, then let WebGL draw."""
        quiet, t = 0, time.time()
        while quiet < 3:
            if time.time() - t > 300:
                raise RuntimeError('the page never went idle')
            ok = self.js("window.__inflight === 0 && document.getElementById('execstatus').textContent.trim() === 'idle'")
            quiet = quiet + 1 if ok else 0
            time.sleep(0.15)
        time.sleep(settle)

    def session(self):
        return self.httpd.app.sessions[self.js('ST.sid')]

    def example(self, name, run=True, fit=True):
        """Open an example network (examples/<name>) and run it all."""
        self.js("closeModal(); document.getElementById('menu').hidden = true; status('');"
                "document.getElementById('logclear').click(); document.getElementById('logbox').open = false;"
                "document.getElementById('viewers').style.height = ''; dispatchEvent(new Event('resize'))")
        old = self.js('ST.sid')
        self.js("api('api/example', {name: %s}).then(r => loadSession(r.session))" % json.dumps(name))
        cdp.wait(self.ws, "ST.sid !== %s && !!ST.nets.main && "
                 "(Object.keys(ST.nets.main.nodes).length > 0 || %s)"
                 % (json.dumps(old), json.dumps(name.endswith('00_start.wnet.json'))), 60, 'open ' + name)
        self.js("if(ST.cur !== 'main') switchTab('main')")
        self.idle()
        if run:
            self.js("document.getElementById('b_hardrun').click()")
            time.sleep(0.5)
            self.session().runner.wait(300)
            self.idle(1.5)
        if fit:
            self.js('ED.fit()')
        self.views()
        if fit:
            self.tight()

    def tight(self, margin=40):
        """A wide network fits the editor's width and leaves its height
        empty: give that height to the row of panels under it."""
        if not self.js("document.querySelectorAll('#viewers > *').length > 0"):
            return
        self.js("ED.fit()")
        time.sleep(0.3)
        free = self.js("""(() => {
            const nodes = [...document.querySelectorAll('#canvas .node')];
            if(!nodes.length) return 0;
            let y0 = 1e9, y1 = -1e9;
            nodes.forEach(n => { const r = n.getBoundingClientRect(); y0 = Math.min(y0, r.top); y1 = Math.max(y1, r.bottom); });
            const c = document.getElementById('canvaswrap').getBoundingClientRect();
            return Math.floor(c.height - (y1 - y0) - 2 * %d); })()""" % margin)
        if free > 20:
            self.js("""(() => { const vw = document.getElementById('viewers'), H = document.getElementById('center').clientHeight;
                vw.style.height = Math.min(0.86 * H, vw.offsetHeight + %d) + 'px';
                dispatchEvent(new Event('resize')); })()""" % free)
            time.sleep(0.8)
            self.js("ED.fit()")
            self.views()

    def views(self):
        """Wait for the 3D viewers to have drawn their scenes."""
        self.js("Promise.all(Object.values(VIEW3D.viewers).map(r => r.pending)).then(() => true)")
        self.idle(1.5)

    def shot(self, name, clip=None, pad=0):
        """Capture the window, or a rectangle {x, y, width, height}, or a CSS selector's box."""
        if isinstance(clip, str):
            clip = self.js('DOC.rect(%s)' % json.dumps(clip))
        if clip:
            clip = {'x': max(0, clip['x'] - pad), 'y': max(0, clip['y'] - pad),
                    'width': min(W, clip['width'] + 2 * pad), 'height': min(H, clip['height'] + 2 * pad)}
        path = os.path.join(IMG, name + '.png')
        cdp.screenshot(self.ws, path, clip)
        print('  %-28s %4d kB' % (name + '.png', os.path.getsize(path) // 1024), flush=True)

    def badges(self, marks):
        """Numbered callouts: [(n, css selector, fx, fy, dx, dy)] puts badge n at
        fraction (fx, fy) of the element's box, shifted by (dx, dy) pixels."""
        self.js(r"""(() => { const box = document.createElement('div'); box.id = 'docbadges';
          box.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2000';
          for(const [n, sel, fx, fy, dx, dy] of %s){
            const el = document.querySelector(sel); if(!el) throw new Error('no element ' + sel);
            const r = el.getBoundingClientRect();
            const b = document.createElement('div'); b.textContent = n;
            b.style.cssText = 'position:absolute;width:26px;height:26px;border-radius:13px;background:#d6336c;'
              + 'color:#fff;font:bold 14px system-ui;display:flex;align-items:center;justify-content:center;'
              + 'box-shadow:0 1px 4px rgba(0,0,0,.4);border:2px solid #fff';
            b.style.left = (r.left + fx * r.width + dx - 13) + 'px';
            b.style.top = (r.top + fy * r.height + dy - 13) + 'px';
            box.appendChild(b); }
          document.body.appendChild(box); })()""" % json.dumps(marks))

    def unbadge(self):
        self.js("(() => { const b = document.getElementById('docbadges'); if(b) b.remove(); })()")

    def mouse(self, kind, x, y, buttons=1):
        button = 'left' if (buttons or kind != 'mouseMoved') else 'none'
        self.ws.call('Input.dispatchMouseEvent', type=kind, x=x, y=y, button=button,
                     buttons=buttons, clickCount=1)

    def drag(self, x0, y0, x1, y1, steps=12, release=True):
        self.mouse('mouseMoved', x0, y0, 0)
        self.mouse('mousePressed', x0, y0)
        for k in range(1, steps + 1):
            self.mouse('mouseMoved', x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
            time.sleep(0.02)
        if release:
            self.mouse('mouseReleased', x1, y1, 0)

    def edit(self, op, **args):
        return self.js('edit(%s, %s)' % (json.dumps(op), json.dumps(args)))

    def add(self, lib, label, x, y):
        """Add a palette node at (x, y) of the network; returns its id."""
        d = self.js("edit('add', %s)" % json.dumps({'net': 'main', 'lib': lib, 'label': label, 'pos': [x, y]}))
        self.idle(0.3)
        return d['node']['id']

    def close(self):
        errs = cdp.js_errors(self.ws)
        self.chrome.terminate()
        self.httpd.shutdown()
        return errs


TUT = 'tutorial/'


# ---------------------------------------------------------------- Start here
def overview(p):
    p.example(TUT + '09_mol2plv.wnet.json')
    p.js("DOC.select('Color Map')")
    # the libraries with their categories closed, so that all of them show
    p.js("OPENCATS.clear(); drawPalette('')")
    p.idle(1.0)
    p.badges([(1, '#libs', 0.82, 0, 0, 14), (2, '#search', 1, 0.5, -16, 0), (3, '#m_edit', 0.5, 1, 0, 12),
              (4, '#b_run', 0, 0.5, -16, 0), (5, '#execstatus', 1, 0.5, 16, 0), (6, '#sessions', 0, 0.5, -16, 0),
              (7, 'header a.btn', 0.5, 1, 0, 14), (8, '#tabs .tab', 1, 0.5, 16, 0),
              (9, '#canvas', 0.5, 0.82, 0, 0), (10, p.js("DOC.sel('Lines')"), 0.3, 0, 0, -14),
              (11, '#panel', 0, 0.16, -2, 0), (12, '.vpanel .vhead', 0, 0.5, 70, 0),
              (13, '.vlegend', 0, 0.5, -16, 0), (14, '#logbox summary', 0, 0.5, 140, 0),
              (15, '#status', 0, 0.5, 300, 0)])
    p.shot('overview')
    p.unbadge()


def examples(p):
    p.example(TUT + '00_start.wnet.json', run=False)
    p.js("examplesDialog()")
    p.idle(0.5)
    p.js("document.querySelectorAll('#mbody details.exgroup').forEach((d, i) => d.open = i === 1)")
    time.sleep(0.3)
    p.shot('examples', '#modal .dialog', pad=8)
    p.js('closeModal()')


# ---------------------------------------------------------------- Building a network
def editor(p):
    p.example(TUT + '00_start.wnet.json', run=False)
    p.js("document.getElementById('search').value = 'dial'; drawPalette('dial')")
    time.sleep(0.3)
    # a Dial dragged from the palette: the node under the cursor
    p.js(r"""(() => { const e = [...document.querySelectorAll('.pnode')].find(e => e.textContent === 'Dial');
        const r = e.getBoundingClientRect(), x = r.x + 20, y = r.y + 8;
        e.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, clientX: x, clientY: y}));
        window.__dt = new DataTransfer(); window.__src = e;
        e.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: window.__dt, clientX: x, clientY: y})); })()""")
    time.sleep(0.8)
    cv = p.js("DOC.rect('#canvas')")
    x, y = cv['x'] + 300, cv['y'] + 160
    for k in range(4):
        p.js("""(() => { const t = document.elementFromPoint(%d, %d);
            t.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: window.__dt,
                                                         clientX: %d, clientY: %d})); })()""" % (x - 30 + 10 * k, y, x - 30 + 10 * k, y))
    time.sleep(0.3)
    p.shot('drag_ghost', {'x': 0, 'y': 40, 'width': 760, 'height': 330})
    p.js("""(() => { const t = document.elementFromPoint(%d, %d);
        t.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: window.__dt, clientX: %d, clientY: %d}));
        window.__src.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: window.__dt})); })()""" % (x, y, x, y))
    p.idle(0.5)
    p.js("document.getElementById('search').value = ''; drawPalette('')")
    p.add('Standard', 'print', 560, 170)
    p.add('Standard', 'Op2', 560, 40)
    # dragging from the Dial's output: the inputs that can take a float light up
    x0, y0 = p.js("DOC.center(DOC.port('Dial', 'out', 'value'))")
    p.drag(x0, y0, x0 + 150, y0 + 30, release=False)
    time.sleep(0.3)
    p.shot('connect', {'x': cv['x'], 'y': cv['y'], 'width': 760, 'height': 300})
    x1, y1 = p.js("DOC.center(DOC.port('print', 'in', 'in1'))")
    p.mouse('mouseMoved', x1, y1)
    p.mouse('mouseReleased', x1, y1, 0)
    p.idle(0.5)
    # the node menu and a widget's menu
    p.js("DOC.context(DOC.sel('print'), 40, 8)")
    time.sleep(0.3)
    p.shot('node_menu', DOC_UNION(p, [DOC_JS("DOC.sel('print')"), '#menu']), pad=10)
    p.js("document.getElementById('menu').hidden = true")
    p.js("DOC.context(DOC.sel('Op2') + ' .wrow label')")
    time.sleep(0.3)
    p.shot('widget_menu', DOC_UNION(p, [DOC_JS("DOC.sel('Op2')"), '#menu']), pad=10)
    p.js("document.getElementById('menu').hidden = true")
    # the parameter column of the selected node
    p.js("DOC.select('Op2')")
    p.idle(0.5)
    p.shot('panel', DOC_UNION(p, ['#panel h3', '#p_ports', '#p_addport']), pad=10)


def DOC_JS(expr):
    return ('js', expr)


def DOC_UNION(p, items):
    sels = [p.js(x[1]) if isinstance(x, tuple) else x for x in items]
    return p.js('DOC.union(%s)' % json.dumps(sels))


def code_editor(p):
    p.example(TUT + '05_cartoon1b.wnet.json')
    p.js("codeEditor(DOC.id('Filelist'))")
    p.idle(0.5)
    p.shot('code_editor', '#modal .dialog', pad=8)
    p.js('closeModal()')


def macro(p):
    p.example(TUT + '08_cartoon2b.wnet.json')
    p.shot('cartoon2b', {'x': 220, 'y': 40, 'width': 935, 'height': 760})
    p.js("switchTab(DOC.id('indexMax'))")
    p.idle(0.8)
    p.js('ED.fit()')
    p.idle(0.5)
    p.shot('macro_tab', {'x': 220, 'y': 40, 'width': 935, 'height': 380})


# ---------------------------------------------------------------- Running
def running(p):
    p.example(TUT + '02_cartoon0.wnet.json', run=False)
    p.edit('set_widget', node=p.js("DOC.id('Read Image')"), port='filename', value='cartoonMovie/missing.png', run=False)
    p.js("document.getElementById('b_hardrun').click()")
    time.sleep(0.5)
    p.session().runner.wait(60)
    p.idle(1.0)
    p.js("DOC.select('Read Image')")
    p.idle(0.5)
    p.badges([(1, '#b_run', 0.5, 1, 0, 14), (2, '#b_hardrun', 0.5, 1, 0, 14), (3, '#b_pause', 0.5, 1, 0, 14),
              (4, '#b_stop', 0.5, 1, 0, 14), (5, '#b_auto', 0.5, 1, 30, 14), (6, '#execstatus', 0.5, 1, 0, 14)])
    p.shot('toolbar', {'x': 0, 'y': 0, 'width': 640, 'height': 74})
    p.unbadge()
    p.shot('node_error', {'x': 220, 'y': 40, 'width': 1220, 'height': 300})


# ---------------------------------------------------------------- Tutorials
def tut_first(p):
    p.example(TUT + '01_dial_print.wnet.json')
    p.js("document.getElementById('logclear').click(); document.getElementById('logbox').open = true")
    p.js("document.getElementById('b_hardrun').click()")
    time.sleep(0.5)
    p.session().runner.wait(60)
    p.idle(0.5)
    for v in (0.25, 0.5, 1.0):
        p.edit('set_widget', node=p.js("DOC.id('Dial')"), port='dial', value=v)
        p.idle(0.3)
    p.js("ED.fit(1.6)")
    p.idle(0.5)
    p.shot('first_network', DOC_UNION(p, ['#canvaswrap', '#logbox']))
    p.js("showData(DOC.id('Dial'), 'out', 'value')")
    p.idle(0.5)
    p.shot('show_data', '#modal .dialog', pad=8)
    p.js('closeModal()')
    p.js("codeEditor(DOC.id('print'))")
    p.idle(0.5)
    p.shot('print_code', '#modal .dialog', pad=8)
    p.js('closeModal()')
    p.js("document.getElementById('logbox').open = false")


def tut_image(p):
    p.example(TUT + '02_cartoon0.wnet.json')
    p.js("DOC.select('Scale')")
    p.idle(0.5)
    p.shot('image_viewer')
    p.js("(filePicker('file', 'cartoonMovie/crnCartoon0000.png', {title: 'Choose a file'}), true)")
    p.idle(0.8)
    p.shot('file_picker', '#modal .dialog', pad=8)
    p.js('closeModal()')
    # the exercise: a contour filter and a second Show Image
    f = p.add('Imaging', 'Filter Image', 700, 260)
    s = p.add('Imaging', 'Show Image', 980, 260)
    p.edit('set_widget', node=f, port='filter', value='CONTOUR', run=False)
    p.edit('connect', **{'from': [f, 'image'], 'to': [s, 'image']})
    p.edit('connect', **{'from': [p.js("DOC.id('Scale')"), 'scaledImage'], 'to': [f, 'image']})
    p.js("document.getElementById('b_hardrun').click()")
    time.sleep(0.5)
    p.session().runner.wait(60)
    p.idle(1.0)
    p.js('ED.fit()')
    p.idle(0.5)
    p.shot('contour', {'x': 220, 'y': 40, 'width': 935, 'height': 800})


def tut_movie(p):
    p.example(TUT + '02_cartoon0.wnet.json')
    p.js("DOC.context(DOC.sel('Read Image') + ' .wrow')")
    time.sleep(0.3)
    p.shot('unbind_menu', DOC_UNION(p, [DOC_JS("DOC.sel('Read Image')"), '#menu']), pad=10)
    p.js("document.getElementById('menu').hidden = true")
    p.example(TUT + '03_cartoon0b.wnet.json')
    p.shot('cartoon0b', {'x': 220, 'y': 40, 'width': 935, 'height': 800})
    p.example(TUT + '04_cartoon1.wnet.json')
    p.js("DOC.select('range')")
    p.idle(0.5)
    p.shot('cartoon1')
    p.example(TUT + '05_cartoon1b.wnet.json')
    p.shot('cartoon1b', {'x': 220, 'y': 40, 'width': 935, 'height': 800})


def tut_macro(p):
    p.example(TUT + '07_cartoon2.wnet.json')
    p.js("DOC.select('ThumbWheelInt')")
    p.idle(0.5)
    p.shot('cartoon2')


def tut_molecule(p):
    p.example(TUT + '09_mol2plv.wnet.json')
    p.shot('mol2plv')
    p.js("switchTab(DOC.id('Icosahedral1'))")
    p.idle(0.8)
    p.js('ED.fit()')
    p.idle(0.5)
    p.shot('icosahedral1', {'x': 220, 'y': 40, 'width': 935, 'height': 380})


def tut_cage(p):
    p.example(TUT + '10_icoscage.wnet.json')
    p.shot('icoscage')


def tut_volumes(p):
    for name in ('12_headandslice', '13_isorad', '14_regioncapsid', '11_blurgaussian'):
        p.example(TUT + name + '.wnet.json')
        p.shot(name.split('_', 1)[1])


# ---------------------------------------------------------------- Viewing results
def viewer(p):
    p.example(TUT + '14_regioncapsid.wnet.json')
    p.badges([(1, '.vhead select', 0.5, 1, 0, 14), (2, '.vhead button[data-a=fit]', 0.5, 1, 0, 14),
              (3, '.vhead button[data-a=png]', 0.5, 1, 0, 14), (4, '.vhead button[data-a=look]', 0.5, 1, 0, 14),
              (5, '.vhead button[data-a=max]', 0.5, 1, 0, 14), (6, '.vhead button[data-a=full]', 0.5, 1, 0, 14),
              (7, '.vhead button[data-a=fold]', 0.5, 1, 0, 14)])
    p.shot('viewer_header', '.vpanel')
    p.unbadge()
    p.js("document.querySelector('.vhead button[data-a=look]').click()")
    p.idle(0.5)
    p.shot('rendering_strip', '.vpanel')
    p.js("document.querySelector('.vhead button[data-a=look]').click()")
    # the same scene in Mol*
    p.js("(s => { s.value = 'molstar'; s.dispatchEvent(new Event('change')); })(document.querySelector('.vhead select'))")
    p.views()
    cdp.wait(p.ws, "Object.values(VIEW3D.viewers).every(r => r.be && r.be.kind === 'molstar')", 180, 'Mol*')
    p.views()
    p.idle(4.0)
    p.shot('molstar', '.vpanel')
    p.js("(s => { s.value = '3dmol'; s.dispatchEvent(new Event('change')); })(document.querySelector('.vhead select'))")
    p.idle(2.0)


def colormap(p):
    p.example(TUT + '09_mol2plv.wnet.json')
    p.js("DOC.select('Color Map')")
    p.idle(1.0)
    p.shot('colormap_editor', '#side')
    p.js("DOC.context('.vlegend')")
    time.sleep(0.3)
    p.shot('legend_menu', DOC_UNION(p, ['.vlegend', '#menu']), pad=12)
    p.js("document.getElementById('menu').hidden = true")


def images(p):
    p.example('plots.wnet.json')
    p.shot('plots')


# ---------------------------------------------------------------- Reference
def files(p):
    with open(os.path.join(TUTORIAL, 'cartoon', 'cartoon2b_net.py')) as fh:
        text = fh.read()
    # void: openUpload's promise waits for the dialog this scene answers below
    p.js("void openUpload(new File([%s], 'cartoon2b_net.py'), 'import')" % json.dumps(text))
    # importing asks how the network runs (unless told not to ask again)
    cdp.wait(p.ws, "!!document.getElementById('iso_ok') || /^Imported/.test(document.getElementById('mtitle').textContent)",
             60, 'execution mode dialog')
    if p.js("!!document.getElementById('iso_ok')"):
        p.idle(0.3)
        p.shot('open_mode', '#modal .dialog', pad=8)
        p.js("document.querySelector('input[value=unrestricted]').click(); document.getElementById('iso_ok').click()")
    cdp.wait(p.ws, "!document.getElementById('modal').hidden && /^Imported/.test(document.getElementById('mtitle').textContent)",
             120, 'import report')
    p.idle(0.8)
    p.shot('import_report', '#modal .dialog', pad=8)
    p.js('closeModal()')


def libraries(p):
    p.js('librariesDialog()')
    p.idle(0.8)
    p.shot('libraries', '#modal .dialog', pad=8)
    p.js('closeModal()')


def nodes(p):
    p.example(TUT + '00_start.wnet.json', run=False)
    g = p.add('Standard', 'Generic', 80, 60)
    p.edit('rename', node=g, name='square')
    p.edit('add_port', node=g, io='in', name='x', datatype='float', widget=False)
    p.edit('add_port', node=g, io='out', name='y', datatype='float', widget=False)
    p.edit('set_code', node=g, code='def doit(self, x):\n    self.outputData(y=x * x)\n', force=True)
    p.idle(0.5)
    p.js("ED.select([%s]); panel(); document.getElementById('p_addport').open = true" % json.dumps(g))
    p.idle(0.5)
    p.shot('add_port', '#side')


SCENES = [overview, examples, editor, code_editor, macro, running, tut_first, tut_image, tut_movie,
          tut_macro, tut_molecule, tut_cage, tut_volumes, viewer, colormap, images, files, libraries,
          nodes]


def main(argv):
    names = set(argv)
    os.makedirs(IMG, exist_ok=True)
    p = Page()
    try:
        for scene in SCENES:
            if names and scene.__name__ not in names:
                continue
            print(scene.__name__, flush=True)
            scene(p)
    finally:
        errs = p.close()
    if errs:
        print('JS errors:', json.dumps(errs)[:2000])


if __name__ == '__main__':
    main(sys.argv[1:])
