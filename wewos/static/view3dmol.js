/* Author: Michel Sanner, PhD. Copyright (c) 2026. */
/* The 3Dmol.js renderer of the viewer panels (the interface is described in
   viewer3d.js). Each geometry is drawn as 3Dmol objects:
     mol       -> addModel(pdb) + styles, surfaces       (picking: the atom)
     spheres   -> one shape per color, addSphere per center
     cylinders -> one shape per color, addCylinder / addArrow
     lines     -> one shape per color, addLine per segment
     mesh      -> addCustom (per-vertex colors and normals)
     labels    -> addLabel per position
   Silhouettes and fog: 3Dmol's outline style, and its fog with the range
   computed from the scene's bounding sphere, so fog fractions are of the
   scene's depth (3Dmol's own are of the clipping slab, several times deeper). */
'use strict';
(() => {
  const BACKENDS = window.VIEW3D_BACKENDS = window.VIEW3D_BACKENDS || {};
  BACKENDS['3dmol'] = {label: '3Dmol', create};

  /* 3Dmol draws a shape in its shape-level color (a color given to one
     sphere or cylinder of a shape is not used), so items are grouped by
     color, one shape per color; colors are rounded to 1/64 to bound the
     number of shapes. Returns [[hexColor, [indices]], ...]. */
  function byColor(n, cols, color){
    const hex = V3DU.hex;
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

  function create(div, opts){
    const {dec, hex, vec, sample, maxOf} = V3DU;
    const v = $3Dmol.createViewer(div, {backgroundColor: opts.bg});
    const objs = {};             // geometry name -> {models, shapes, labels, surfaces, pts, pad}
    let empty = true;
    let rendering = Object.assign({}, opts.rendering || {});

    // the scene's bounding sphere radius about the center of rotation
    function sceneRadius(){
      const view = v.getView();
      const cx = -view[0], cy = -view[1], cz = -view[2];
      let r2 = 0;
      v.selectedAtoms({}).forEach(a => {
        const d = (a.x - cx) ** 2 + (a.y - cy) ** 2 + (a.z - cz) ** 2;
        if(d > r2) r2 = d;
      });
      let r = r2 > 0 ? Math.sqrt(r2) + 3 : 0;          // atoms: room for spheres and surfaces
      // shapes: points kept when drawn (3Dmol's bounding spheres are those of boxes)
      Object.values(objs).forEach(o => {
        const p = o.pts;
        if(!p) return;
        let m = 0;
        for(let i = 0; i < p.length; i += 3){
          const d = (p[i] - cx) ** 2 + (p[i + 1] - cy) ** 2 + (p[i + 2] - cz) ** 2;
          if(d > m) m = d;
        }
        r = Math.max(r, Math.sqrt(m) + (o.pad || 0));
      });
      return Math.max(r, 5);
    }
    function look(){
      const r = rendering, R = sceneRadius();
      /* the clipping slab fits the scene: all of it is inside (a saved camera
         comes without a slab), and the depth buffer's precision is not spent on
         empty space (3Dmol's zoomTo makes it 8 times deeper, and the outline,
         drawn just behind the surfaces, then showed through them) */
      v.setSlab(-1.1 * R, 1.1 * R);
      if(r.outline)
        v.setViewStyle({style: 'outline', color: r.outlineColor || '#000000',
                        width: R * 0.05, maxpixels: r.outlineWidth || 2, pushback: Math.max(1, R * 0.03)});
      else v.setViewStyle({style: ''});
      if(r.fog){
        // 3Dmol's fog fractions are of the slab: map the scene's depth onto them
        const s = v.getSlab(), span = s.far - s.near;
        const f = t => (-R + 2 * R * t - s.near) / span;
        const a = f(r.fogStart), b = f(Math.max(r.fogEnd, r.fogStart + 0.05));
        v.enableFog({fogStart: a, fogEnd: b});
      } else v.enableFog(false);
    }

    function clearObj(name){
      const o = objs[name];
      if(!o) return;
      (o.models || []).forEach(m => v.removeModel(m));
      (o.shapes || []).forEach(s => v.removeShape(s));
      (o.labels || []).forEach(l => v.removeLabel(l));
      (o.surfaces || []).forEach(s => { Promise.resolve(s).then(id => { try { v.removeSurface(id); } catch(e) {} }); });
      delete objs[name];
    }

    function drawMol(o, g, M){
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
          opts.onPick({geom: g.name, atom: {index: atom.index, serial: atom.serial, atom: atom.atom, resn: atom.resn,
                       resi: atom.resi, chain: atom.chain, elem: atom.elem, x: atom.x, y: atom.y, z: atom.z}});
        });
        m.setHoverable({}, true, atom => {
          opts.onHover((atom.chain || '') + ':' + atom.resn + atom.resi + ':' + atom.atom);
        }, () => {});
      }
    }

    function draw(g){
      clearObj(g.name);
      if(!g.visible) return;
      const o = objs[g.name] = {models: [], shapes: [], labels: [], surfaces: []};
      const alpha = g.opacity == null ? 1 : g.opacity;
      const click = g.pickable ? (() => opts.onPick({geom: g.name})) : null;
      if(g.type === 'mol'){
        // one model per instance matrix (symmetry copies), else one model
        (g.instances && g.instances.length ? g.instances : [null]).forEach(M => drawMol(o, g, M));
      } else if(g.type === 'spheres'){
        const c = dec(g.centers), r = dec(g.radii), cols = dec(g.colors);
        const n = c.length / 3;
        o.pts = sample(c); o.pad = maxOf(r, g.radius);
        byColor(n, cols, g.color).forEach(([color, idx]) => {
          const sh = v.addShape({color, alpha, clickable: !!click, callback: click});
          idx.forEach(i => sh.addSphere({center: vec(c, i), radius: r ? r[i] : g.radius}));
          o.shapes.push(sh);
        });
      } else if(g.type === 'cylinders'){
        const s = dec(g.starts), e = dec(g.ends), r = dec(g.radii), cols = dec(g.colors);
        const n = s.length / 3;
        const se = new Float32Array(s.length + e.length); se.set(s); se.set(e, s.length);
        o.pts = sample(se); o.pad = maxOf(r, g.radius) * (g.arrows ? 2 : 1);
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
        o.pts = sample(p);
        byColor(ns, V3DU.segmentColors(seg, cols), g.color).forEach(([color, idx]) => {
          const sh = v.addShape({color, alpha, clickable: !!click, callback: click});
          idx.forEach(i => sh.addLine({start: vec(p, seg[2 * i]), end: vec(p, seg[2 * i + 1])}));
          o.shapes.push(sh);
        });
      } else if(g.type === 'mesh'){
        const p = dec(g.vertices), f = dec(g.faces), nm = dec(g.normals), cols = dec(g.colors);
        const n = p.length / 3;
        o.pts = sample(p);
        /* two-sided, as in DejaVu: the back side is a copy of the faces, reversed,
           on vertices with reversed normals. 3Dmol draws a mesh one-sided, so
           the back of an open surface (an isosurface cut by its box, a slice)
           was not drawn, and the outline pass painted it black. */
        const two = !g.wireframe, nv = two ? 2 * n : n;
        const vertexArr = new Array(nv), normalArr = new Array(nv);
        for(let i = 0; i < n; i++){
          vertexArr[i] = vec(p, i);
          normalArr[i] = nm ? vec(nm, i) : {x: 0, y: 0, z: 1};
          if(two){ vertexArr[n + i] = vertexArr[i];
                   normalArr[n + i] = {x: -normalArr[i].x, y: -normalArr[i].y, z: -normalArr[i].z}; }
        }
        let faceArr = Array.from(f);
        if(two){
          const back = new Array(f.length);
          for(let j = 0; j < f.length; j += 3){ back[j] = f[j] + n; back[j + 1] = f[j + 2] + n; back[j + 2] = f[j + 1] + n; }
          faceArr = faceArr.concat(back);
        }
        const spec = {vertexArr, normalArr, faceArr, color: hex(g.color), alpha,
                      wireframe: !!g.wireframe, clickable: !!click, callback: click};
        // per-vertex colors: an array in 'color' (this 3Dmol build ignores colorArr)
        if(cols){ const ca = new Array(nv); for(let i = 0; i < n; i++){ ca[i] = hex([cols[3*i], cols[3*i+1], cols[3*i+2]]); if(two) ca[n + i] = ca[i]; } spec.color = ca; }
        o.shapes.push(v.addCustom(spec));
      } else if(g.type === 'labels'){
        const p = dec(g.positions), cols = dec(g.colors);
        o.pts = sample(p);
        (g.labels || []).forEach((t, i) => {
          o.labels.push(v.addLabel(t, {position: vec(p, i), fontSize: g.fontSize || 14,
            fontColor: cols ? hex([cols[3*i], cols[3*i+1], cols[3*i+2]]) : hex(g.color),
            backgroundOpacity: 0.0, inFront: true}));
        });
      }
    }

    return {
      kind: '3dmol',
      set(g){ draw(g); },
      remove(name){ clearObj(name); },
      async flush(){
        const has = Object.keys(objs).length > 0;
        if(empty && has){ v.zoomTo(); empty = false; }
        if(!has) empty = true;
        look();
        v.render();
      },
      fit(){ v.zoomTo(); look(); v.render(); },
      getView(){ return v.getView(); },
      setView(view){ v.setView(view); empty = false; look(); v.render(); },
      async png(){ v.render(); return v.pngURI(); },
      setRendering(r){ rendering = Object.assign({}, r); look(); v.render(); },
      background(c){ v.setBackgroundColor(c); look(); v.render(); },
      resize(){ if(div.clientHeight > 0){ v.resize(); v.render(); } },
      interacted(){ look(); v.render(); },       // a translation moves the center of rotation
      dispose(){
        try { v.clear(); } catch(e) {}
        const c = div.querySelector('canvas');
        try { const gl = c && (c.getContext('webgl2') || c.getContext('webgl'));
              const ext = gl && gl.getExtension('WEBGL_lose_context'); if(ext) ext.loseContext(); } catch(e) {}
        div.innerHTML = '';
      },
    };
  }
})();
