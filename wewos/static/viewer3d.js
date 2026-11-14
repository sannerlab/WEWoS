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
  // is the page in its dark theme (chosen, or the system's)?
  isDark(){
    const t = document.documentElement.dataset.theme;
    return t === 'dark' || (!t && matchMedia('(prefers-color-scheme: dark)').matches);
  },
  // a lines geometry given no color: DejaVu's light grey on the dark theme,
  // a dark grey on the light one (light grey lines vanish on white)
  lineColor(g){ return g.defaultColor ? (V3DU.isDark() ? [0.8, 0.8, 0.8] : [0.3, 0.33, 0.4]) : g.color; },
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
  // the color of a ramp at f in 0..1, interpolated between its entries (as the server maps values)
  rampAt(ramp, f){
    if(ramp.length === 1) return ramp[0].slice();
    const x = Math.max(0, Math.min(1, f)) * (ramp.length - 1), i = Math.min(Math.floor(x), ramp.length - 2), t = x - i;
    return [0, 1, 2, 3].map(j => {
      const a = ramp[i][j] == null ? 1 : ramp[i][j], b = ramp[i + 1][j] == null ? 1 : ramp[i + 1][j];
      return a * (1 - t) + b * t;
    });
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

  function bg(){ return V3DU.isDark() ? '#151922' : '#ffffff'; }

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
      '<button class=plainbtn data-a=max title="give the viewers the network\'s height too (hide the network)">&#8661;</button>' +
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
      '<div class=vbox><div class=vrender></div><div class=vlegends></div></div><div class=vpick></div>';
    box.append(panel);
    // the renderer draws in .vrender; color map legends are drawn above it, in .vlegends
    const vbox = panel.querySelector('.vbox'), div = panel.querySelector('.vrender');
    const rec = {panel, vbox, div, layer: panel.querySelector('.vlegends'), id, be: null, kind: null,
                 geoms: new Map(), legends: new Map(), legendOpts: {}, pickEl: panel.querySelector('.vpick'),
                 rendering: Object.assign({}, RENDERING), canvas: null, cameras: {}, pending: Promise.resolve()};
    V[id] = rec;
    lookControls(rec);
    const sel = panel.querySelector('.vrend');
    if(sel) sel.addEventListener('change', () => { rec.pending = rec.pending.then(() => switchTo(rec, sel.value, true)); });
    panel.querySelector('.vhead').addEventListener('click', async e => {
      const a = e.target.dataset && e.target.dataset.a;
      if(!a) return;
      if(a === 'fit' && rec.be){ rec.be.fit(); setTimeout(() => sendView(rec, true), 300); }
      if(a === 'look'){ const l = panel.querySelector('.vlook'); l.hidden = !l.hidden; e.target.classList.toggle('on', !l.hidden); showLook(rec); }
      if(a === 'png' && rec.be){ const url = await pngWithLegends(rec); const l = document.createElement('a');
        l.href = url; l.download = (n ? n.name : 'viewer') + '.png'; l.click(); }
      if(a === 'fold'){ vbox.hidden = !vbox.hidden; panel.classList.toggle('folded', vbox.hidden); }
      if(a === 'max') setLayout(document.getElementById('center').classList.contains('vmax') ? null : 'vmax');
      if(a === 'full') setLayout(document.body.classList.contains('vfull') ? null : 'vfull');
    });
    // the renderers size their canvas when created: follow every later size change
    if(window.ResizeObserver){
      let raf = 0;
      new ResizeObserver(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => { if(rec.be && div.clientHeight > 0) rec.be.resize(); rec.legends.forEach(L => placeLegend(rec, L)); });
      }).observe(div);
    }
    /* the view is sent when the mouse lets go (and every 300 ms while it
       drags): it is saved with the network, and it is a redraw for the nodes
       connected to the Viewer's redraw output (One Redraw -> Grab Image) */
    let t = null, last = 0;
    div.addEventListener('pointerup', () => { clearTimeout(t); t = setTimeout(() => { if(rec.be){ rec.be.interacted(); sendView(rec, true); } }, 400); });
    div.addEventListener('pointermove', e => {
      if(!e.buttons || !rec.be) return;
      const now = performance.now();
      if(now - last > 300){ last = now; sendView(rec, true); }
    });
    div.addEventListener('wheel', () => { clearTimeout(t); t = setTimeout(() => sendView(rec, true), 600); }, {passive: true});
    return rec;
  }
  /* layout of the viewers: null (the row under the network, divider above it),
     'vmax' (the network's height too), 'vfull' (the window) */
  function setLayout(mode){
    document.getElementById('center').classList.toggle('vmax', mode === 'vmax');
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
  // a geometry: a color map legend goes to the layer above the view, the rest to the renderer
  const isLegend = g => g && g.type === 'legend';
  function put(rec, g){
    rec.geoms.set(g.name, g);
    if(isLegend(g)) setLegend(rec, g);
    else rec.be.set(g);
  }
  function drop(rec, name){
    const g = rec.geoms.get(name);
    rec.geoms.delete(name);
    if(isLegend(g)) removeLegend(rec, name);
    else if(rec.be) rec.be.remove(name);
  }
  // draw everything the viewer has with the current renderer (after creating it)
  async function redraw(rec){
    rec.geoms.forEach(g => { if(isLegend(g)) setLegend(rec, g); else rec.be.set(g); });
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

  // redraw: the view was moved with the mouse (the Viewer's redraw output fires)
  /* ---- color map legends (DejaVu's ColorMapLegend), over the 3D view ----
     A legend geometry (from a Color Map node's legend output) is drawn on a
     canvas in the layer above the view: the ramp, its range (or the color
     map's labels) and its name. Drag it to move it; right-click it for its
     orientation, number of labels, size, title and frame. Its place and look
     are kept by the Viewer node (viewer_legend), as fractions of the view. */
  const LEGEND = {vertical: true, labels: 5, size: 1, title: true, frame: true};
  const legendOpts = (rec, name) => Object.assign({}, LEGEND, rec.legendOpts[name] || {});
  function fmtNum(v){
    if(v === 0) return '0';
    const a = Math.abs(v);
    return (a >= 1e4 || a < 1e-2) ? v.toExponential(2) : String(+v.toPrecision(4));
  }
  function setLegend(rec, g){
    let L = rec.legends.get(g.name);
    if(!g.visible){ if(L) removeLegend(rec, g.name); return; }
    if(!L){
      const el = document.createElement('canvas');
      el.className = 'vlegend';
      rec.layer.append(el);
      L = {el, g, left: 0, top: 0, w: 0, h: 0};
      rec.legends.set(g.name, L);
      legendEvents(rec, L);
    }
    L.g = g;
    drawLegend(rec, L);
    placeLegend(rec, L);
  }
  function removeLegend(rec, name){
    const L = rec.legends.get(name);
    if(L){ L.el.remove(); rec.legends.delete(name); }
  }
  function drawLegend(rec, L){
    const g = L.g, o = legendOpts(rec, g.name), s = Math.max(0.5, Math.min(2.5, o.size || 1));
    const dark = V3DU.isDark(), fg = dark ? '#e6eaf2' : '#1b2333', back = dark ? 'rgba(21,25,34,0.72)' : 'rgba(255,255,255,0.78)';
    const font = Math.round(11 * s), pad = Math.round(6 * s), tick = Math.round(4 * s);
    const ramp = g.ramp && g.ramp.length ? g.ramp : [[0, 0, 0, 1], [1, 1, 1, 1]];
    const n = g.labels && g.labels.length ? g.labels.length : Math.max(2, o.labels | 0);
    const texts = g.labels && g.labels.length ? g.labels.map(String)
      : Array.from({length: n}, (_, k) => fmtNum(g.mini + (g.maxi - g.mini) * k / (n - 1)));
    const meas = document.createElement('canvas').getContext('2d');
    meas.font = font + 'px system-ui, sans-serif';
    const tw = texts.map(t => meas.measureText(t).width), maxW = Math.max(...tw);
    meas.font = '600 ' + font + 'px system-ui, sans-serif';
    const title = o.title && g.title ? g.title : '', titleW = title ? meas.measureText(title).width : 0;
    const titleH = title ? font + Math.round(4 * s) : 0;
    let W, H, bx, by, bw, bh;
    if(o.vertical){
      bw = Math.round(14 * s); bh = Math.round(150 * s);
      W = Math.ceil(Math.max(pad + bw + tick + 3 + maxW + pad, titleW + 2 * pad));
      H = Math.ceil(pad + titleH + font / 2 + bh + font / 2 + pad);
      bx = pad; by = pad + titleH + font / 2;
    } else {
      bw = Math.round(180 * s); bh = Math.round(12 * s);
      const half = Math.max(tw[0], tw[tw.length - 1]) / 2;
      W = Math.ceil(Math.max(bw + 2 * Math.max(pad, half + 2), titleW + 2 * pad));
      H = Math.ceil(pad + titleH + bh + tick + 2 + font + pad);
      bx = (W - bw) / 2; by = pad + titleH;
    }
    const dpr = window.devicePixelRatio || 1, cv = L.el;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const c = cv.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, W, H);
    if(o.frame){
      c.fillStyle = back; c.strokeStyle = dark ? 'rgba(230,234,242,0.35)' : 'rgba(27,35,51,0.3)'; c.lineWidth = 1;
      const r = 5;
      c.beginPath(); c.moveTo(r, 0.5); c.arcTo(W - 0.5, 0.5, W - 0.5, H - 0.5, r); c.arcTo(W - 0.5, H - 0.5, 0.5, H - 0.5, r);
      c.arcTo(0.5, H - 0.5, 0.5, 0.5, r); c.arcTo(0.5, 0.5, W - 0.5, 0.5, r); c.closePath(); c.fill(); c.stroke();
    }
    // the bar: a checkerboard under transparent colors, high values at the top (or the right)
    const sq = Math.max(3, Math.round(bh < bw ? bh / 2 : bw / 2));
    for(let x = 0; x < bw; x += sq) for(let y = 0; y < bh; y += sq){
      c.fillStyle = ((x + y) / sq) % 2 ? '#c8c8c8' : '#ffffff'; c.fillRect(bx + x, by + y, Math.min(sq, bw - x), Math.min(sq, bh - y));
    }
    const len = o.vertical ? bh : bw;
    for(let p = 0; p < len; p++){
      const col = V3DU.rampAt(ramp, p / Math.max(1, len - 1));      // interpolated, as the colors are
      c.fillStyle = 'rgba(' + Math.round(col[0] * 255) + ',' + Math.round(col[1] * 255) + ',' + Math.round(col[2] * 255) + ',' + (col[3] == null ? 1 : col[3]) + ')';
      if(o.vertical) c.fillRect(bx, by + bh - 1 - p, bw, 1); else c.fillRect(bx + p, by, 1, bh);
    }
    c.strokeStyle = fg; c.lineWidth = 1; c.strokeRect(bx + 0.5, by + 0.5, bw - 1, bh - 1);
    // ticks and labels
    c.fillStyle = fg; c.font = font + 'px system-ui, sans-serif';
    texts.forEach((t, k) => {
      const f = n === 1 ? 0 : k / (n - 1);
      c.beginPath();
      if(o.vertical){
        const y = by + bh - f * bh;
        c.moveTo(bx + bw, y); c.lineTo(bx + bw + tick, y); c.stroke();
        c.textAlign = 'left'; c.textBaseline = 'middle'; c.fillText(t, bx + bw + tick + 3, y);
      } else {
        const x = bx + f * bw;
        c.moveTo(x, by + bh); c.lineTo(x, by + bh + tick); c.stroke();
        c.textAlign = 'center'; c.textBaseline = 'top'; c.fillText(t, x, by + bh + tick + 2);
      }
    });
    if(title){
      c.font = '600 ' + font + 'px system-ui, sans-serif'; c.textBaseline = 'top';
      c.textAlign = o.vertical ? 'left' : 'center';
      c.fillText(title, o.vertical ? pad : W / 2, pad);
    }
    L.w = W; L.h = H;
  }
  // its corner, in fractions of the view (default: the top right)
  function placeLegend(rec, L){
    const o = legendOpts(rec, L.g.name), W = rec.vbox.clientWidth, H = rec.vbox.clientHeight;
    if(!W || !H) return;
    const fx = o.x == null ? (W - L.w - 12) / W : o.x, fy = o.y == null ? 12 / H : o.y;
    L.left = Math.max(0, Math.min(W - L.w, fx * W));
    L.top = Math.max(0, Math.min(H - L.h, fy * H));
    L.el.style.left = L.left + 'px'; L.el.style.top = L.top + 'px';
  }
  function saveLegend(rec, name, opts){
    rec.legendOpts[name] = opts;
    cb.edit('viewer_legend', {node: rec.id, name, opts});
  }
  function legendEvents(rec, L){
    const el = L.el;
    el.addEventListener('pointerdown', e => {
      if(e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      const x0 = e.clientX - L.left, y0 = e.clientY - L.top, W = rec.vbox.clientWidth, H = rec.vbox.clientHeight;
      const move = ev => {
        L.left = Math.max(0, Math.min(W - L.w, ev.clientX - x0));
        L.top = Math.max(0, Math.min(H - L.h, ev.clientY - y0));
        el.style.left = L.left + 'px'; el.style.top = L.top + 'px';
      };
      const up = () => {
        el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up);
        saveLegend(rec, L.g.name, Object.assign(legendOpts(rec, L.g.name), {x: L.left / W, y: L.top / H}));
      };
      el.addEventListener('pointermove', move); el.addEventListener('pointerup', up);
    });
    el.addEventListener('contextmenu', e => {
      e.preventDefault(); e.stopPropagation();
      if(!cb.menu) return;
      const name = L.g.name, o = legendOpts(rec, name);
      const set = ch => { saveLegend(rec, name, Object.assign(o, ch)); drawLegend(rec, L); placeLegend(rec, L); };
      const custom = L.g.labels && L.g.labels.length;
      cb.menu(e, [
        [(o.vertical ? '✓ ' : '') + 'Vertical', () => set({vertical: true})],
        [(!o.vertical ? '✓ ' : '') + 'Horizontal', () => set({vertical: false})],
        '-',
        ['More numbers (' + o.labels + ')', () => set({labels: o.labels + 1}), custom || o.labels >= 11],
        ['Fewer numbers', () => set({labels: o.labels - 1}), custom || o.labels <= 2],
        ['Larger', () => set({size: +(o.size + 0.25).toFixed(2)}), o.size >= 2.5],
        ['Smaller', () => set({size: +(o.size - 0.25).toFixed(2)}), o.size <= 0.5],
        [(o.title ? '✓ ' : '') + 'Title', () => set({title: !o.title})],
        [(o.frame ? '✓ ' : '') + 'Frame', () => set({frame: !o.frame})],
        '-',
        ['Back to the corner', () => { delete rec.legendOpts[name]; cb.edit('viewer_legend', {node: rec.id, name, opts: null}); drawLegend(rec, L); placeLegend(rec, L); }],
      ]);
    });
  }
  // the renderer's picture with the legends drawn on it (Grab Image, the camera button)
  async function pngWithLegends(rec){
    const url = await rec.be.png();
    if(!rec.legends.size) return url;
    const img = await new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = url; });
    const cv = document.createElement('canvas');
    cv.width = img.width; cv.height = img.height;
    const c = cv.getContext('2d');
    c.drawImage(img, 0, 0);
    const sx = img.width / (rec.vbox.clientWidth || img.width), sy = img.height / (rec.vbox.clientHeight || img.height);
    rec.legends.forEach(L => c.drawImage(L.el, L.left * sx, L.top * sy, L.w * sx, L.h * sy));
    return cv.toDataURL('image/png');
  }

  function sendView(rec, redraw){
    if(!rec.be) return;
    try {
      const view = rec.be.getView();
      if(!view) return;
      rec.cameras[rec.kind] = view;
      cb.edit('viewer_view', {node: rec.id, view, renderer: rec.kind, redraw: !!redraw});
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
    d.geoms.forEach(g => put(rec, g));
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
    rec.legendOpts = Object.assign({}, d.legends || {});
    [...rec.legends.keys()].forEach(name => removeLegend(rec, name));
    if(rec.be){ rec.geoms.forEach((g, name) => { if(!isLegend(g)) rec.be.remove(name); }); if(rec.kind !== kind){ rec.be.dispose(); rec.be = null; } }
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
      '<button class=plainbtn data-a=max title="give the viewers the network\'s height too (hide the network)">&#8661;</button>' +
      '<button class=plainbtn data-a=full title="fill the window (Esc to come back)">&#10530;</button>' +
      '<button class=plainbtn data-a=fold title="hide / show">&#9662;</button></div>' +
      '<div class=ibox><img alt=""></div>';
    box.append(panel);
    const rec = {panel, img: panel.querySelector('img'), id};
    panel.querySelector('.vhead').addEventListener('click', e => {
      const a = e.target.dataset && e.target.dataset.a;
      if(a === 'save' && rec.img.src){ const l = document.createElement('a');
        l.href = rec.img.src; l.download = (n ? n.name : 'image') + '.png'; l.click(); }
      if(a === 'fold'){ const b = panel.querySelector('.ibox'); b.hidden = !b.hidden; panel.classList.toggle('folded', b.hidden); }
      if(a === 'max') setLayout(document.getElementById('center').classList.contains('vmax') ? null : 'vmax');
      if(a === 'full') setLayout(document.body.classList.contains('vfull') ? null : 'vfull');
    });
    IM[id] = rec;
    return rec;
  }
  // one request at a time per image; a change meanwhile fetches it once more after
  const IMQ = {};
  async function loadImage(id){
    const q = IMQ[id] || (IMQ[id] = {busy: false, again: false});
    if(q.busy){ q.again = true; return; }
    q.busy = true;
    try { do { q.again = false; await loadImageNow(id); } while(q.again); }
    finally { q.busy = false; }
  }
  async function loadImageNow(id){
    const d = await cb.edit('image_data', {node: id});
    if(!d || d.error || !d.png) return;
    const rec = ensureImage(id);
    // only a picture made by the network's node: never a URL it names
    if(typeof d.png === 'string' && d.png.startsWith('data:image/')) rec.img.src = d.png;
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
      if(!rec || !rec.be || rec.vbox.hidden) return;
      try { await rec.pending; } catch(err) {}
      cb.edit('viewer_snapshot', {node: e.viewer, request: e.request, png: await pngWithLegends(rec)});
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
      // drawing is chained, so a snapshot can wait for what is pending. Changes
      // that arrive while a draw waits to start merge into it: a burst of runs
      // (a widget turned fast) is drawn once, with the latest geometries
      if(!rec.queued){
        const job = rec.queued = {ops: new Map()};
        rec.pending = rec.pending.then(async () => {
          rec.queued = null;              // from here on, changes start a new draw
          if(!rec.be) makeBackend(rec, rec.kind || '3dmol');
          const puts = [];
          job.ops.forEach((op, name) => { if(op === 'drop') drop(rec, name); else puts.push(name); });
          if(puts.length) await fetchAndDraw(rec, puts);
          else await rec.be.flush();
        }).catch(err => status('viewer: ' + esc(err.message)));
      }
      (e.removed || []).forEach(n => rec.queued.ops.set(n, 'drop'));
      (e.changed || []).forEach(c => rec.queued.ops.set(c.name, 'put'));
    },
    removeViewer(id){
      if(IM[id]){ IM[id].panel.remove(); delete IM[id]; }
      const rec = V[id]; if(!rec) return;
      if(rec.be) rec.be.dispose();
      rec.panel.remove(); delete V[id];
    },
    resize(){ Object.values(V).forEach(r => { if(r.be) r.be.resize(); }); },
    theme(){ Object.values(V).forEach(r => {
      if(r.be){
        r.be.background(bg());
        // lines and labels drawn in the theme's default color
        let any = false;
        r.geoms.forEach(g => { if(g.defaultColor && (g.type === 'lines' || g.type === 'labels')){ r.be.set(g); any = true; } });
        if(any) r.be.flush();
      }
      r.legends.forEach(L => { drawLegend(r, L); placeLegend(r, L); });
    }); },
    viewers: V,
  };
})();
