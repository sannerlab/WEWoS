/* Author: Michel Sanner, PhD. Copyright (c) 2026. */
/* 3D viewers (3Dmol.js), replacing DejaVu. One panel per Viewer node.

   The Viewer node keeps the scene on the server; 'scene' events say which
   geometries changed (name, version) or went away, and this file fetches the
   changed ones (api/edit viewer_geoms) and draws them:
     mol       -> addModel(pdb) + styles, surfaces       (picking: the atom)
     spheres   -> one shape, addSphere per center         (picking: the shape)
     cylinders -> one shape, addCylinder / addArrow
     lines     -> one shape, addLine per segment
     mesh      -> addCustom (per-vertex colors and normals)
     labels    -> addLabel per position
   A click goes back to the Viewer node (api/pick), which outputs it on its
   lastPick port. The camera is sent back when it changes, so it is saved
   with the network. */
'use strict';
const VIEW3D = (() => {
  let box, cb;
  const V = {};          // viewer node id -> {panel, div, v, objs:{}, versions:{}, empty, pickEl}
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  function bg(){
    const dark = document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    return dark ? '#151922' : '#ffffff';
  }
  function dec(o){
    if(!o) return null;
    const bin = atob(o.b64);
    const buf = new ArrayBuffer(bin.length);
    const u8 = new Uint8Array(buf);
    for(let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return o.dtype === 'i4' ? new Int32Array(buf) : new Float32Array(buf);
  }
  const hex = c => {
    if(!c) return '#cccccc';
    const h = x => ('0' + Math.round(Math.max(0, Math.min(1, x)) * 255).toString(16)).slice(-2);
    return '#' + h(c[0]) + h(c[1]) + h(c[2]);
  };
  const vec = (a, i) => ({x: a[3 * i], y: a[3 * i + 1], z: a[3 * i + 2]});
  /* 3Dmol draws a shape in its shape-level color (a color given to one
     sphere or cylinder of a shape is not used), so items are grouped by
     color, one shape per color; colors are rounded to 1/64 to bound the
     number of shapes. Returns [[hexColor, [indices]], ...]. */
  function byColor(n, cols, color){
    if(!cols) return [[hex(color), Array.from({length: n}, (_, i) => i)]];
    const groups = new Map();
    for(let i = 0; i < n; i++){
      const q = x => Math.round(x * 64) / 64;
      const k = hex([q(cols[3*i]), q(cols[3*i+1]), q(cols[3*i+2])]);
      if(!groups.has(k)) groups.set(k, []);
      groups.get(k).push(i);
    }
    return [...groups.entries()];
  }

  function init(container, callbacks){ box = container; cb = callbacks; }

  function ensure(id){
    if(V[id]) return V[id];
    const n = cb.find(id);
    const panel = document.createElement('div');
    panel.className = 'vpanel';
    panel.innerHTML = '<div class=vhead><b>' + esc(n ? n.name : id) + '</b>' +
      '<button class=plainbtn data-a=fit title="center the scene">&#8982;</button>' +
      '<button class=plainbtn data-a=png title="save an image">&#128247;</button>' +
      '<button class=plainbtn data-a=max title="use the whole column (hide the parameter panel)">&#8661;</button>' +
      '<button class=plainbtn data-a=full title="fill the window (Esc to come back)">&#10530;</button>' +
      '<button class=plainbtn data-a=fold title="hide / show">&#9662;</button></div>' +
      '<div class=vbox></div><div class=vpick></div>';
    box.append(panel);
    const div = panel.querySelector('.vbox');
    const v = $3Dmol.createViewer(div, {backgroundColor: bg()});
    const rec = {panel, div, v, objs: {}, versions: {}, empty: true, pickEl: panel.querySelector('.vpick'), id};
    V[id] = rec;
    panel.querySelector('.vhead').addEventListener('click', e => {
      const a = e.target.dataset && e.target.dataset.a;
      if(a === 'fit'){ v.zoomTo(); v.render(); sendView(rec); }
      if(a === 'png'){ const url = v.pngURI(); const l = document.createElement('a');
        l.href = url; l.download = (n ? n.name : 'viewer') + '.png'; l.click(); }
      if(a === 'fold'){ div.hidden = !div.hidden; panel.classList.toggle('folded', div.hidden); }
      if(a === 'max') setLayout(document.getElementById('side').classList.contains('vmax') ? null : 'vmax');
      if(a === 'full') setLayout(document.body.classList.contains('vfull') ? null : 'vfull');
    });
    // 3Dmol sizes its canvas when created: follow every later size change
    if(window.ResizeObserver){
      let raf = 0;
      new ResizeObserver(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => { if(div.clientHeight > 0){ v.resize(); v.render(); } });
      }).observe(div);
    }
    let t = null;
    div.addEventListener('pointerup', () => { clearTimeout(t); t = setTimeout(() => sendView(rec), 400); });
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

  function sendView(rec){
    try { cb.edit('viewer_view', {node: rec.id, view: rec.v.getView()}); } catch(e) {}
  }

  function clearObj(rec, name){
    const o = rec.objs[name];
    if(!o) return;
    const v = rec.v;
    (o.models || []).forEach(m => v.removeModel(m));
    (o.shapes || []).forEach(s => v.removeShape(s));
    (o.labels || []).forEach(l => v.removeLabel(l));
    (o.surfaces || []).forEach(s => { Promise.resolve(s).then(id => { try { v.removeSurface(id); } catch(e) {} }); });
    delete rec.objs[name];
  }

  function pickInfo(rec, g, atom){
    rec.pickEl.textContent = atom
      ? g.name + ': ' + (atom.chain || '') + ':' + (atom.resn || '') + (atom.resi != null ? atom.resi : '') + ':' + (atom.atom || '') +
        ' (' + [atom.x, atom.y, atom.z].map(x => Number(x).toFixed(2)).join(', ') + ')'
      : 'picked ' + g.name;
  }

  function drawMol(v, o, g, M, rec){
      const m = v.addModel(g.data, g.format || 'pdb', {keepH: true});
      o.models.push(m);
      if(M){
        // x' = M x (row-major, translation in the last column); 3Dmol builds
        // its geometry at the next render, so moving the atoms now is enough
        m.selectedAtoms({}).forEach(a => {
          const x = a.x, y = a.y, z = a.z;
          a.x = M[0] * x + M[1] * y + M[2] * z + M[3];
          a.y = M[4] * x + M[5] * y + M[6] * z + M[7];
          a.z = M[8] * x + M[9] * y + M[10] * z + M[11];
        });
      }
      const colors = g.atomColors ? dec(g.atomColors) : null;
      m.setStyle({}, {});
      (g.styles || []).forEach(([sel, st]) => {
        st = JSON.parse(JSON.stringify(st || {}));
        if(colors) for(const rep in st){
          if(st[rep] && typeof st[rep] === 'object' && !st[rep].color && !st[rep].colorscheme)
            st[rep].colorfunc = a => { const i = a.index; return colors.length > 3 * i ? hex([colors[3*i], colors[3*i+1], colors[3*i+2]]) : '#cccccc'; };
        }
        m.setStyle(sel || {}, st, true);     // add to the model's styles
      });
      (g.surfaces || []).forEach(s => {
        const type = $3Dmol.SurfaceType[s.type || 'VDW'] || $3Dmol.SurfaceType.VDW;
        const style = {opacity: s.opacity == null ? 0.85 : s.opacity};
        if(s.color) style.color = Array.isArray(s.color) ? hex(s.color) : s.color;
        if(s.colorscheme) style.colorscheme = s.colorscheme;
        o.surfaces.push(v.addSurface(type, style, Object.assign({model: m}, s.sel || {})));
      });
      if(g.pickable){
        m.setClickable({}, true, atom => {
          const a = {index: atom.index, serial: atom.serial, atom: atom.atom, resn: atom.resn, resi: atom.resi,
                     chain: atom.chain, elem: atom.elem, x: atom.x, y: atom.y, z: atom.z};
          pickInfo(rec, g, a);
          cb.pick({node: rec.id, geom: g.name, atom: a});
        });
        m.setHoverable({}, true, atom => {
          rec.pickEl.textContent = (atom.chain || '') + ':' + atom.resn + atom.resi + ':' + atom.atom;
        }, () => {});
      }
  }

  function draw(rec, g){
    clearObj(rec, g.name);
    rec.versions[g.name] = g.version;
    if(!g.visible) return;
    const v = rec.v, o = rec.objs[g.name] = {models: [], shapes: [], labels: [], surfaces: []};
    const alpha = g.opacity == null ? 1 : g.opacity;
    const click = g.pickable ? (shape => {
      pickInfo(rec, g, null);
      cb.pick({node: rec.id, geom: g.name});
    }) : null;
    if(g.type === 'mol'){
      // one model per instance matrix (symmetry copies), else one model
      (g.instances && g.instances.length ? g.instances : [null]).forEach(M => drawMol(v, o, g, M, rec));
    } else if(g.type === 'spheres'){
      const c = dec(g.centers), r = dec(g.radii), cols = dec(g.colors);
      const n = c.length / 3;
      byColor(n, cols, g.color).forEach(([color, idx]) => {
        const sh = v.addShape({color, alpha, clickable: !!click, callback: click});
        idx.forEach(i => sh.addSphere({center: vec(c, i), radius: r ? r[i] : g.radius}));
        o.shapes.push(sh);
      });
    } else if(g.type === 'cylinders'){
      const s = dec(g.starts), e = dec(g.ends), r = dec(g.radii), cols = dec(g.colors);
      const n = s.length / 3;
      byColor(n, cols, g.color).forEach(([color, idx]) => {
        const sh = v.addShape({color, alpha, clickable: !!click, callback: click});
        idx.forEach(i => {
          const spec = {start: vec(s, i), end: vec(e, i), radius: r ? r[i] : g.radius};
          if(g.arrows) sh.addArrow(Object.assign(spec, {radiusRatio: 2.0, mid: 0.85}));
          else sh.addCylinder(Object.assign(spec, {fromCap: 1, toCap: 1}));
        });
        o.shapes.push(sh);
      });
    } else if(g.type === 'lines'){
      const p = dec(g.vertices), seg = dec(g.segments), cols = dec(g.colors);
      const ns = seg.length / 2;
      // a segment takes the color of its first vertex
      const segCols = cols ? (() => { const a = new Float32Array(ns * 3);
        for(let i = 0; i < ns; i++){ const k = seg[2 * i]; a.set([cols[3*k], cols[3*k+1], cols[3*k+2]], 3 * i); } return a; })() : null;
      byColor(ns, segCols, g.color).forEach(([color, idx]) => {
        const sh = v.addShape({color, alpha, clickable: !!click, callback: click});
        idx.forEach(i => sh.addLine({start: vec(p, seg[2 * i]), end: vec(p, seg[2 * i + 1])}));
        o.shapes.push(sh);
      });
    } else if(g.type === 'mesh'){
      const p = dec(g.vertices), f = dec(g.faces), nm = dec(g.normals), cols = dec(g.colors);
      const n = p.length / 3;
      const vertexArr = new Array(n), normalArr = new Array(n);
      for(let i = 0; i < n; i++){ vertexArr[i] = vec(p, i); normalArr[i] = nm ? vec(nm, i) : {x: 0, y: 0, z: 1}; }
      const spec = {vertexArr, normalArr, faceArr: Array.from(f), color: hex(g.color), alpha,
                    wireframe: !!g.wireframe, clickable: !!click, callback: click};
      // per-vertex colors: an array in 'color' (this 3Dmol build ignores colorArr)
      if(cols){ const ca = new Array(n); for(let i = 0; i < n; i++) ca[i] = hex([cols[3*i], cols[3*i+1], cols[3*i+2]]); spec.color = ca; }
      o.shapes.push(v.addCustom(spec));
    } else if(g.type === 'labels'){
      const p = dec(g.positions), cols = dec(g.colors);
      (g.labels || []).forEach((t, i) => {
        o.labels.push(v.addLabel(t, {position: vec(p, i), fontSize: g.fontSize || 14,
          fontColor: cols ? hex([cols[3*i], cols[3*i+1], cols[3*i+2]]) : hex(g.color),
          backgroundOpacity: 0.0, inFront: true}));
      });
    }
  }

  async function fetchAndDraw(rec, names){
    const d = await cb.edit('viewer_geoms', {node: rec.id, names});
    if(!d || d.error) return;
    d.geoms.forEach(g => draw(rec, g));
    finish(rec);
  }
  function finish(rec){
    const has = Object.keys(rec.objs).length > 0;
    if(rec.empty && has){ rec.v.zoomTo(); rec.empty = false; }
    if(!has) rec.empty = true;
    rec.v.render();
  }

  async function load(id){
    const rec = ensure(id);
    const d = await cb.edit('viewer_state', {node: id});
    if(!d || d.error) return;
    Object.keys(rec.objs).forEach(n => clearObj(rec, n));
    d.geoms.forEach(g => draw(rec, g));
    if(d.camera){ rec.v.setView(d.camera); rec.empty = !d.geoms.length; rec.v.render(); }
    else finish(rec);
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
    rec.panel.querySelector('.isize').textContent = d.size ? d.size[0] + '\u00d7' + d.size[1] + ' ' + (d.mode || '') : '';
  }

  return {
    init,
    reset(){ Object.keys(V).forEach(id => this.removeViewer(id)); Object.keys(IM).forEach(id => this.removeViewer(id)); },
    requestAll(nets){
      for(const k in nets) for(const id in nets[k].nodes){
        if(nets[k].nodes[id].viewer) load(id);
        if(nets[k].nodes[id].imageViewer) loadImage(id);
      }
    },
    imageEvent(e){ loadImage(e.node); },
    async snapshot(e){
      // a Grab Image node asks for the picture a viewer shows (once what
      // the viewer is still fetching is drawn)
      const rec = V[e.viewer];
      if(!rec || rec.div.hidden) return;
      try { await rec.pending; } catch(err) {}
      rec.v.render();
      cb.edit('viewer_snapshot', {node: e.viewer, request: e.request, png: rec.v.pngURI()});
    },
    viewerEvent(e){ if(e.op === 'add') ensure(e.node); },
    apply(e){
      const rec = ensure(e.viewer);
      (e.removed || []).forEach(n => { clearObj(rec, n); delete rec.versions[n]; });
      const names = (e.changed || []).map(c => c.name);
      // drawing is chained, so a snapshot can wait for what is pending
      rec.pending = (rec.pending || Promise.resolve()).then(() =>
        names.length ? fetchAndDraw(rec, names) : finish(rec));
    },
    removeViewer(id){
      if(IM[id]){ IM[id].panel.remove(); delete IM[id]; }
      const rec = V[id]; if(!rec) return;
      try { rec.v.clear(); } catch(e) {}
      rec.panel.remove(); delete V[id];
    },
    resize(){ Object.values(V).forEach(r => { r.v.resize(); r.v.render(); }); },
    theme(){ Object.values(V).forEach(r => { r.v.setBackgroundColor(bg()); r.v.render(); }); },
    viewers: V,
  };
})();
