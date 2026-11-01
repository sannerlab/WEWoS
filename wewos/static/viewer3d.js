/* Author: Michel Sanner, PhD. Copyright (c) 2026. */
/* 3D viewers, replacing DejaVu. One panel per Viewer node, drawn with 3Dmol.js
   (view3dmol.js, the default) or Mol* (viewmolstar.js), switched per viewer
   in the panel's header and saved with the network.

   The Viewer node keeps the scene on the server; 'scene' events say which
   geometries changed (name, version) or went away, and this file fetches the
   changed ones (api/edit viewer_geoms), keeps them, and hands them to the
   renderer. A click goes back to the Viewer node (api/pick), which outputs it
   on its lastPick port. The camera is sent back when it changes, so it is
   saved with the network (one camera per renderer).

   A renderer is made by VIEW3D_BACKENDS[kind].create(div, opts) with
   opts = {bg, rendering, canvas, onPick({geom, atom}), onHover(text),
   onCanvas(settings), status(html)} and has:
     set(g), remove(name)    add or replace / remove a geometry
     flush()                 draw what changed (a Promise); fits the first scene
     fit(), getView(), setView(v), png() (a Promise of a data URL)
     setRendering(r)         3Dmol's silhouette and fog settings
     background(color), resize(), interacted() (after a mouse action), dispose()
   Mol* has its own rendering settings (canvas): setCanvas(c), effect(k),
   setEffect(k, on). */
'use strict';

// helpers shared by the renderers
const V3DU = {
  dec(o){
    if(!o) return null;
    const bin = atob(o.b64);
    const buf = new ArrayBuffer(bin.length);
    const u8 = new Uint8Array(buf);
    for(let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return o.dtype === 'i4' ? new Int32Array(buf) : new Float32Array(buf);
  },
  hex(c){
    if(!c) return '#cccccc';
    const h = x => ('0' + Math.round(Math.max(0, Math.min(1, x)) * 255).toString(16)).slice(-2);
    return '#' + h(c[0]) + h(c[1]) + h(c[2]);
  },
  vec: (a, i) => ({x: a[3 * i], y: a[3 * i + 1], z: a[3 * i + 2]}),
  // at most ~3000 of the points of a geometry, for its extent
  sample(a){
    if(!a) return null;
    const n = a.length / 3, step = Math.max(1, Math.ceil(n / 3000));
    if(step === 1) return a;
    const out = new Float32Array(Math.ceil(n / step) * 3);
    let j = 0;
    for(let i = 0; i < n; i += step){ out[j++] = a[3 * i]; out[j++] = a[3 * i + 1]; out[j++] = a[3 * i + 2]; }
    return out;
  },
  maxOf(a, d){ if(!a || !a.length) return d || 0; let m = 0; for(let i = 0; i < a.length; i++) if(a[i] > m) m = a[i]; return m; },
  /* a mesh with instance matrices (row-major, translation in the last
     column) as one mesh holding all the copies */
  expandMesh(p, f, nm, cols, mats){
    const n = p.length / 3, k = mats.length;
    const P = new Float32Array(p.length * k), F = new Int32Array(f.length * k);
    const N = nm ? new Float32Array(nm.length * k) : null, C = cols ? new Float32Array(cols.length * k) : null;
    mats.forEach((M, j) => {
      const o = j * p.length;
      for(let i = 0; i < n; i++){
        const x = p[3*i], y = p[3*i+1], z = p[3*i+2], q = o + 3 * i;
        P[q] = M[0]*x + M[1]*y + M[2]*z + M[3];
        P[q+1] = M[4]*x + M[5]*y + M[6]*z + M[7];
        P[q+2] = M[8]*x + M[9]*y + M[10]*z + M[11];
        if(N){ const a = nm[3*i], b = nm[3*i+1], c = nm[3*i+2];
               N[q] = M[0]*a + M[1]*b + M[2]*c; N[q+1] = M[4]*a + M[5]*b + M[6]*c; N[q+2] = M[8]*a + M[9]*b + M[10]*c; }
      }
      if(C) C.set(cols, j * cols.length);
      const fo = j * f.length, vo = j * n;
      for(let q = 0; q < f.length; q++) F[fo + q] = f[q] + vo;
    });
    return {p: P, f: F, nm: N, cols: C};
  },
  // is a triangle mesh closed (each edge shared by two triangles)?
  isClosed(f){
    if(!f || !f.length) return false;
    const count = new Map();
    for(let j = 0; j < f.length; j += 3){
      for(let e = 0; e < 3; e++){
        const a = f[j + e], b = f[j + (e + 1) % 3];
        const key = a < b ? a * 4294967296 + b : b * 4294967296 + a;
        count.set(key, (count.get(key) || 0) + 1);
      }
    }
    for(const c of count.values()) if(c !== 2) return false;
    return true;
  },
  // a segment takes the color of its first vertex
  segmentColors(seg, cols){
    if(!cols) return null;
    const ns = seg.length / 2, a = new Float32Array(ns * 3);
    for(let i = 0; i < ns; i++){ const k = seg[2 * i]; a[3*i] = cols[3*k]; a[3*i+1] = cols[3*k+1]; a[3*i+2] = cols[3*k+2]; }
    return a;
  },
};

const VIEW3D = (() => {
  let box, cb;
  const V = {};          // viewer node id -> panel record
  const BACKENDS = window.VIEW3D_BACKENDS || {};
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const status = h => { if(cb && cb.status) cb.status(h); };

  function bg(){
    const dark = document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    return dark ? '#151922' : '#ffffff';
  }

  function init(container, callbacks){ box = container; cb = callbacks; }

  /* ---- 3Dmol's silhouettes and fog (the Viewer node's 'rendering') ---- */
  const RENDERING = {outline: true, outlineWidth: 2, outlineColor: '#000000', fog: true, fogStart: 0.3, fogEnd: 1.3};

  function ensure(id){
    if(V[id]) return V[id];
    const n = cb.find(id);
    const panel = document.createElement('div');
    panel.className = 'vpanel';
    const kinds = Object.keys(BACKENDS);
    panel.innerHTML = '<div class=vhead><b>' + esc(n ? n.name : id) + '</b>' +
      (kinds.length > 1 ? '<select class=vrend title="renderer">' +
        kinds.map(k => '<option value="' + k + '">' + esc(BACKENDS[k].label) + '</option>').join('') + '</select>' : '') +
      '<button class=plainbtn data-a=fit title="center the scene">&#8982;</button>' +
      '<button class=plainbtn data-a=png title="save an image">&#128247;</button>' +
      '<button class=plainbtn data-a=look title="silhouettes, fog and other effects">&#9680;</button>' +
      '<button class=plainbtn data-a=max title="use the whole column (hide the parameter panel)">&#8661;</button>' +
      '<button class=plainbtn data-a=full title="fill the window (Esc to come back)">&#10530;</button>' +
      '<button class=plainbtn data-a=fold title="hide / show">&#9662;</button></div>' +
      '<div class=vlook hidden>' +
      '<span class=look3dmol>' +
      '<label><input type=checkbox data-k=outline> silhouettes</label>' +
      '<label title="width in pixels"><input type=range data-k=outlineWidth min=0.5 max=6 step=0.5> <span data-v=outlineWidth></span></label>' +
      '<label title="color"><input type=color data-k=outlineColor></label>' +
      '<span class=vsep></span>' +
      '<label><input type=checkbox data-k=fog> fog</label>' +
      '<label title="where the fog starts, in % of the scene depth (0: its front)">from <input type=range data-k=fogStart min=-50 max=100 step=5> <span data-v=fogStart></span></label>' +
      '<label title="where things have faded into the background, in % of the scene depth (100: its back)">to <input type=range data-k=fogEnd min=20 max=300 step=10> <span data-v=fogEnd></span></label>' +
      '</span><span class=lookms hidden>' +
      ((BACKENDS.molstar && BACKENDS.molstar.effects) || []).map(([k, lab]) =>
        '<label><input type=checkbox data-e=' + k + '> ' + esc(lab) + '</label>').join('') +
      '<span class=dim title="Mol*\'s settings: the sliders button in its view">more: Mol*\'s settings button (sliders) in the view</span>' +
      '</span></div>' +
      '<div class=vbox></div><div class=vpick></div>';
    box.append(panel);
    const div = panel.querySelector('.vbox');
    const rec = {panel, div, id, be: null, kind: null, geoms: new Map(), pickEl: panel.querySelector('.vpick'),
                 rendering: Object.assign({}, RENDERING), canvas: null, cameras: {}, pending: Promise.resolve()};
    V[id] = rec;
    lookControls(rec);
    const sel = panel.querySelector('.vrend');
    if(sel) sel.addEventListener('change', () => { rec.pending = rec.pending.then(() => switchTo(rec, sel.value, true)); });
    panel.querySelector('.vhead').addEventListener('click', async e => {
      const a = e.target.dataset && e.target.dataset.a;
      if(!a) return;
      if(a === 'fit' && rec.be){ rec.be.fit(); setTimeout(() => sendView(rec), 300); }
      if(a === 'look'){ const l = panel.querySelector('.vlook'); l.hidden = !l.hidden; e.target.classList.toggle('on', !l.hidden); showLook(rec); }
      if(a === 'png' && rec.be){ const url = await rec.be.png(); const l = document.createElement('a');
        l.href = url; l.download = (n ? n.name : 'viewer') + '.png'; l.click(); }
      if(a === 'fold'){ div.hidden = !div.hidden; panel.classList.toggle('folded', div.hidden); }
      if(a === 'max') setLayout(document.getElementById('side').classList.contains('vmax') ? null : 'vmax');
      if(a === 'full') setLayout(document.body.classList.contains('vfull') ? null : 'vfull');
    });
    // the renderers size their canvas when created: follow every later size change
    if(window.ResizeObserver){
      let raf = 0;
      new ResizeObserver(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => { if(rec.be && div.clientHeight > 0) rec.be.resize(); });
      }).observe(div);
    }
    let t = null;
    div.addEventListener('pointerup', () => { clearTimeout(t); t = setTimeout(() => { if(rec.be){ rec.be.interacted(); sendView(rec); } }, 400); });
    div.addEventListener('wheel', () => { clearTimeout(t); t = setTimeout(() => sendView(rec), 600); }, {passive: true});
    return rec;
  }
  /* layout of the viewers: null (divider), 'vmax' (whole column), 'vfull' (window) */
  function setLayout(mode){
    const side = document.getElementById('side');
    side.classList.toggle('vmax', mode === 'vmax');
    document.body.classList.toggle('vfull', mode === 'vfull');
    document.querySelectorAll('.vhead button[data-a=max]').forEach(b => b.classList.toggle('on', mode === 'vmax'));
    document.querySelectorAll('.vhead button[data-a=full]').forEach(b => b.classList.toggle('on', mode === 'vfull'));
  }
  document.addEventListener('keydown', e => {
    if(e.key === 'Escape' && document.body.classList.contains('vfull')) setLayout(null);
  });

  /* ---- renderers ---- */
  function makeBackend(rec, kind){
    if(!BACKENDS[kind]) kind = '3dmol';
    rec.kind = kind;
    const sel = rec.panel.querySelector('.vrend');
    if(sel) sel.value = kind;
    rec.be = BACKENDS[kind].create(rec.div, {
      bg: bg(), rendering: rec.rendering, canvas: rec.canvas, status,
      onPick: ({geom, atom}) => { pickInfo(rec, geom, atom); cb.pick({node: rec.id, geom, atom}); },
      onHover: text => { rec.pickEl.textContent = text; },
      onCanvas: c => {
        rec.canvas = c; rec.localEdit = Date.now(); showLook(rec);
        clearTimeout(rec.canvasTimer);
        rec.canvasTimer = setTimeout(() => cb.edit('viewer_rendering', {node: rec.id, molstar: c}), 300);
      },
    });
    showLook(rec);
    if(rec.be.ready) rec.be.ready.then(() => showLook(rec), () => {});
    return rec.be;
  }
  // draw everything the viewer has with the current renderer (after creating it)
  async function redraw(rec){
    rec.geoms.forEach(g => rec.be.set(g));
    const cam = rec.cameras[rec.kind];
    if(cam && rec.geoms.size) rec.be.setView(cam);
    await rec.be.flush();
    showLook(rec);
  }
  async function switchTo(rec, kind, send){
    if(rec.kind === kind && rec.be) return;
    if(rec.be){
      if(rec.geoms.size) sendView(rec);         // the camera of the renderer we leave is kept
      rec.be.dispose();
    }
    makeBackend(rec, kind);
    if(send) cb.edit('viewer_renderer', {node: rec.id, renderer: rec.kind});
    try { await redraw(rec); }
    catch(e){ status('the ' + esc(BACKENDS[rec.kind].label) + ' viewer failed: ' + esc(e.message)); }
  }

  /* ---- the silhouette / fog strip ---- */
  function lookControls(rec){
    const strip = rec.panel.querySelector('.vlook');
    const show = () => strip.querySelectorAll('[data-k]').forEach(el => {
      const k = el.dataset.k, x = rec.rendering[k];
      if(el.type === 'checkbox') el.checked = !!x;
      else if(k === 'fogStart' || k === 'fogEnd') el.value = Math.round(x * 100);
      else el.value = x;
      const lab = strip.querySelector('[data-v=' + k + ']');
      if(lab) lab.textContent = (k === 'outlineWidth') ? x + ' px' : Math.round(x * 100) + '%';
    });
    rec.showLook3dmol = show;
    let t = null;
    strip.addEventListener('input', e => {
      const el = e.target;
      if(el.dataset.e){ if(rec.be && rec.be.setEffect) rec.be.setEffect(el.dataset.e, el.checked); return; }
      const k = el.dataset.k;
      if(!k) return;
      let x = el.type === 'checkbox' ? el.checked : el.value;
      if(k === 'fogStart' || k === 'fogEnd') x = Number(x) / 100;
      else if(k === 'outlineWidth') x = Number(x);
      rec.rendering[k] = x;
      rec.localEdit = Date.now();
      show();
      if(rec.be) rec.be.setRendering(rec.rendering);
      clearTimeout(t);
      t = setTimeout(() => cb.edit('viewer_rendering', {node: rec.id, rendering: rec.rendering}), 300);
    });
    show();
  }
  function showLook(rec){
    const ms = rec.kind === 'molstar';
    rec.panel.querySelector('.look3dmol').hidden = ms;
    rec.panel.querySelector('.lookms').hidden = !ms;
    if(rec.showLook3dmol) rec.showLook3dmol();
    if(ms && rec.be && rec.be.effect)
      rec.panel.querySelectorAll('.lookms [data-e]').forEach(el => { el.checked = !!rec.be.effect(el.dataset.e); });
  }

  function sendView(rec){
    if(!rec.be) return;
    try {
      const view = rec.be.getView();
      if(!view) return;
      rec.cameras[rec.kind] = view;
      cb.edit('viewer_view', {node: rec.id, view, renderer: rec.kind});
    } catch(e) {}
  }

  function pickInfo(rec, name, atom){
    rec.pickEl.textContent = atom
      ? name + ': ' + (atom.chain || '') + ':' + (atom.resn || '') + (atom.resi != null ? atom.resi : '') + ':' + (atom.atom || '') +
        ' (' + [atom.x, atom.y, atom.z].map(x => Number(x).toFixed(2)).join(', ') + ')'
      : 'picked ' + name;
  }

  async function fetchAndDraw(rec, names){
    const d = await cb.edit('viewer_geoms', {node: rec.id, names});
    if(!d || d.error) return;
    if(!rec.be) makeBackend(rec, rec.kind || '3dmol');
    d.geoms.forEach(g => { rec.geoms.set(g.name, g); rec.be.set(g); });
    await rec.be.flush();
  }

  async function load(id){
    const rec = ensure(id);
    const d = await cb.edit('viewer_state', {node: id});
    if(!d || d.error) return;
    rec.rendering = Object.assign({}, RENDERING, d.rendering || {});
    rec.canvas = d.molstar || null;
    rec.cameras = Object.assign({}, d.cameras || {}, d.camera ? {'3dmol': d.camera} : {});
    const kind = BACKENDS[d.renderer] ? d.renderer : '3dmol';
    if(rec.be){ rec.geoms.forEach((g, name) => rec.be.remove(name)); if(rec.kind !== kind){ rec.be.dispose(); rec.be = null; } }
    if(!rec.be) makeBackend(rec, kind);
    else { rec.be.setRendering(rec.rendering); if(rec.be.setCanvas) rec.be.setCanvas(rec.canvas); }
    rec.geoms = new Map(d.geoms.map(g => [g.name, g]));
    try { await redraw(rec); }
    catch(e){ status('the ' + esc(BACKENDS[rec.kind].label) + ' viewer failed: ' + esc(e.message)); }
  }

  /* ---- image panels (Imaging's Show Image node) ---------------------------------- */
  const IM = {};         // node id -> {panel, img}
  function ensureImage(id){
    if(IM[id]) return IM[id];
    const n = cb.find(id);
    const panel = document.createElement('div');
    panel.className = 'vpanel';
    panel.innerHTML = '<div class=vhead><b>' + esc(n ? n.name : id) + '</b>' +
      '<span class=isize></span>' +
      '<button class=plainbtn data-a=save title="save the image">&#128190;</button>' +
      '<button class=plainbtn data-a=fold title="hide / show">&#9662;</button></div>' +
      '<div class=ibox><img alt=""></div>';
    box.append(panel);
    const rec = {panel, img: panel.querySelector('img'), id};
    panel.querySelector('.vhead').addEventListener('click', e => {
      const a = e.target.dataset && e.target.dataset.a;
      if(a === 'save' && rec.img.src){ const l = document.createElement('a');
        l.href = rec.img.src; l.download = (n ? n.name : 'image') + '.png'; l.click(); }
      if(a === 'fold'){ const b = panel.querySelector('.ibox'); b.hidden = !b.hidden; panel.classList.toggle('folded', b.hidden); }
    });
    IM[id] = rec;
    return rec;
  }
  async function loadImage(id){
    const d = await cb.edit('image_data', {node: id});
    if(!d || d.error || !d.png) return;
    const rec = ensureImage(id);
    rec.img.src = d.png;
    rec.panel.querySelector('.isize').textContent = d.size ? d.size[0] + '×' + d.size[1] + ' ' + (d.mode || '') : '';
  }

  const recent = rec => Date.now() - (rec.localEdit || 0) < 1500;
  return {
    init,
    reset(){ Object.keys(V).forEach(id => this.removeViewer(id)); Object.keys(IM).forEach(id => this.removeViewer(id)); },
    requestAll(nets){
      for(const k in nets) for(const id in nets[k].nodes){
        if(nets[k].nodes[id].viewer){ const rec = ensure(id); rec.pending = rec.pending.then(() => load(id)); }
        if(nets[k].nodes[id].imageViewer) loadImage(id);
      }
    },
    imageEvent(e){ loadImage(e.node); },
    async snapshot(e){
      // a Grab Image node asks for the picture a viewer shows (once what
      // the viewer is still fetching is drawn)
      const rec = V[e.viewer];
      if(!rec || !rec.be || rec.div.hidden) return;
      try { await rec.pending; } catch(err) {}
      cb.edit('viewer_snapshot', {node: e.viewer, request: e.request, png: await rec.be.png()});
    },
    viewerEvent(e){
      if(e.op === 'add') ensure(e.node);
      const rec = V[e.node];
      if(!rec) return;
      // the page's own changes come back too (skip them while the user is moving a slider)
      if(e.op === 'rendering' && !recent(rec) &&
         JSON.stringify(Object.assign({}, RENDERING, e.rendering)) !== JSON.stringify(rec.rendering)){
        rec.rendering = Object.assign({}, RENDERING, e.rendering);
        if(rec.be) rec.be.setRendering(rec.rendering);
        showLook(rec);
      }
      if(e.op === 'canvas' && !recent(rec) && JSON.stringify(e.molstar || null) !== JSON.stringify(rec.canvas)){
        rec.canvas = e.molstar || null;
        if(rec.be && rec.be.setCanvas){ rec.be.setCanvas(rec.canvas); showLook(rec); }
      }
      if(e.op === 'renderer' && e.renderer !== rec.kind)
        rec.pending = rec.pending.then(() => switchTo(rec, e.renderer, false));
    },
    apply(e){
      const rec = ensure(e.viewer);
      const names = (e.changed || []).map(c => c.name);
      // drawing is chained, so a snapshot can wait for what is pending
      rec.pending = rec.pending.then(async () => {
        if(!rec.be) makeBackend(rec, rec.kind || '3dmol');
        (e.removed || []).forEach(n => { rec.geoms.delete(n); rec.be.remove(n); });
        if(names.length) await fetchAndDraw(rec, names);
        else await rec.be.flush();
      }).catch(err => status('viewer: ' + esc(err.message)));
    },
    removeViewer(id){
      if(IM[id]){ IM[id].panel.remove(); delete IM[id]; }
      const rec = V[id]; if(!rec) return;
      if(rec.be) rec.be.dispose();
      rec.panel.remove(); delete V[id];
    },
    resize(){ Object.values(V).forEach(r => { if(r.be) r.be.resize(); }); },
    theme(){ Object.values(V).forEach(r => { if(r.be) r.be.background(bg()); }); },
    viewers: V,
  };
})();
