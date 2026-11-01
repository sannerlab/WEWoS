/* Author: Michel Sanner, PhD. Copyright (c) 2026. */
/* The Mol* renderer of the viewer panels (the interface is described in
   viewer3d.js). Mol* (molstar.js, MIT) is loaded the first time a viewer is
   switched to it.

   The scene is described with MolViewSpec (MVS), Mol*'s declarative scene
   format, and loaded whole each time something changes (it takes tens of
   milliseconds); the camera is kept. Each geometry becomes:
     mol       -> the PDB text (a data: URL), one instance per matrix,
                  representations (cartoon, ball_and_stick, spacefill, line,
                  surface) colored like 3Dmol: per-atom colors as an
                  annotation, color schemes as Mol* color themes
     spheres   -> ellipsoid primitives      cylinders -> tube / arrow primitives
     lines     -> a lines primitive          labels    -> label primitives
     mesh      -> a PLY file (normals, per-vertex colors) drawn as a shape;
                  a wireframe mesh -> a lines primitive of its edges
   Mol*'s rendering settings (ambient occlusion, shadows, outline, depth of
   field, bloom, fog, illumination...) are set in its viewport (the settings and
   the illumination buttons) or with the quick switches of the panel. The page
   keeps them, saves them with the network, and applies them again after each
   load (loading an MVS scene resets them). */
'use strict';
(() => {
  const BACKENDS = window.VIEW3D_BACKENDS = window.VIEW3D_BACKENDS || {};
  BACKENDS.molstar = {label: 'Mol*', create,
                      effects: [['outline', 'silhouettes'], ['fog', 'fog'], ['occlusion', 'ambient occlusion'],
                                ['shadow', 'shadows'], ['dof', 'depth of field'], ['illumination', 'illumination']]};

  let loading = null;
  // Mol*'s own panels and buttons follow the page theme: its light or dark stylesheet
  function cssHref(){
    const f = V3DU.isDark() ? 'molstar-dark.css' : 'molstar.css';
    return 'static/' + f + '?v=' + ((window.STATIC_V || {})[f] || '0');
  }
  function molstarTheme(){
    const l = document.getElementById('molstar-css');
    if(l && !l.href.endsWith(cssHref())) l.href = cssHref();
  }
  function loadMolstar(status){
    if(window.molstar) return Promise.resolve();
    if(loading) return loading;
    const ver = window.STATIC_V || {};
    if(status) status('loading Mol*&hellip;');
    const css = new Promise((ok, ko) => {
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.id = 'molstar-css';
      l.href = cssHref();
      l.onload = ok; l.onerror = () => ko(new Error('could not load the Mol* stylesheet')); document.head.append(l);
    });
    const js = new Promise((ok, ko) => {
      const s = document.createElement('script');
      s.src = 'static/molstar.js?v=' + (ver['molstar.js'] || '0');
      s.onload = ok; s.onerror = () => ko(new Error('could not load molstar.js')); document.head.append(s);
    });
    loading = Promise.all([css, js]).then(() => { if(status) status('Mol* ' + (molstar.version || '') + ' loaded'); })
      .catch(e => { loading = null; throw e; });
    return loading;
  }

  // base64 of a string's UTF-8 bytes (btoa takes Latin-1 only)
  function b64(s){
    const u8 = new TextEncoder().encode(s);
    let bin = '';
    for(let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(bin);
  }
  const dataUrl = s => 'data:text/plain;base64,' + b64(s);
  const clone = o => JSON.parse(JSON.stringify(o));
  // our matrices are row-major with the translation in the last column; MVS's are column-major
  const colMajor = M => [M[0], M[4], M[8], M[12], M[1], M[5], M[9], M[13], M[2], M[6], M[10], M[14], M[3], M[7], M[11], M[15]];
  const xyz = (a, i) => [a[3 * i], a[3 * i + 1], a[3 * i + 2]];
  const num = x => String(Math.round(x * 1000) / 1000);

  // a 3Dmol color (name, '#rrggbb', 0xRRGGBB, [r, g, b] in 0-1) -> an MVS color
  function mvsColor(c){
    if(c == null) return null;
    if(Array.isArray(c)) return V3DU.hex(c);
    if(typeof c === 'number') return '#' + ('00000' + c.toString(16)).slice(-6);
    const s = String(c);
    return /^0x[0-9a-f]{6}$/i.test(s) ? '#' + s.slice(2) : s;
  }
  // a 3Dmol color scheme -> a Mol* color theme
  function theme(scheme){
    const s = typeof scheme === 'string' ? scheme : '';
    if(/^ss/i.test(s)) return 'secondary-structure';
    if(/^chain/i.test(s)) return 'chain-id';
    if(/spectrum|rainbow/i.test(s)) return 'sequence-id';
    return 'element-symbol';
  }
  // a 3Dmol atom selection -> an MVS component selector ('all' when MVS cannot say it)
  function selector(sel){
    if(!sel || !Object.keys(sel).length) return 'all';
    let parts = [{}];
    const each = (vals, f) => { const out = []; parts.forEach(p => vals.forEach(v => out.push(f(Object.assign({}, p), v)))); parts = out; };
    for(const [k, val] of Object.entries(sel)){
      const vals = Array.isArray(val) ? val : (k === 'resi' ? String(val).split(',') : [val]);
      if(k === 'chain') each(vals, (p, v) => Object.assign(p, {auth_asym_id: String(v)}));
      else if(k === 'elem') each(vals, (p, v) => Object.assign(p, {type_symbol: String(v)}));
      else if(k === 'atom') each(vals, (p, v) => Object.assign(p, {auth_atom_id: String(v)}));
      else if(k === 'index') each(vals, (p, v) => Object.assign(p, {atom_index: +v}));
      else if(k === 'resi') each(vals, (p, v) => {
        const m = String(v).match(/^\s*(-?\d+)\s*-\s*(-?\d+)\s*$/);
        return Object.assign(p, m ? {beg_auth_seq_id: +m[1], end_auth_seq_id: +m[2]} : {auth_seq_id: +v});
      });
      else if(k === 'hetflag' && parts.length === 1 && !Object.keys(parts[0]).length) return val ? 'ligand' : 'polymer';
      else return 'all';
    }
    return parts.length === 1 ? parts[0] : parts;
  }
  const REPS = {cartoon: 'cartoon', stick: 'ball_and_stick', sphere: 'spacefill', line: 'line', cross: 'line'};

  // a mesh as ASCII PLY (Mol* reads ASCII PLY; the file must end with a newline)
  function ply(p, f, nm, cols){
    const n = p.length / 3, nf = f.length / 3;
    const head = ['ply', 'format ascii 1.0', 'element vertex ' + n, 'property float x', 'property float y', 'property float z'];
    if(nm) head.push('property float nx', 'property float ny', 'property float nz');
    if(cols) head.push('property uchar red', 'property uchar green', 'property uchar blue');
    head.push('element face ' + nf, 'property list uchar int vertex_indices', 'end_header');
    const lines = head;
    const c255 = x => Math.round(Math.max(0, Math.min(1, x)) * 255);
    for(let i = 0; i < n; i++){
      let s = num(p[3*i]) + ' ' + num(p[3*i+1]) + ' ' + num(p[3*i+2]);
      if(nm) s += ' ' + num(nm[3*i]) + ' ' + num(nm[3*i+1]) + ' ' + num(nm[3*i+2]);
      if(cols) s += ' ' + c255(cols[3*i]) + ' ' + c255(cols[3*i+1]) + ' ' + c255(cols[3*i+2]);
      lines.push(s);
    }
    for(let j = 0; j < nf; j++) lines.push('3 ' + f[3*j] + ' ' + f[3*j+1] + ' ' + f[3*j+2]);
    lines.push('');
    return lines.join('\n');
  }
  // the edges of a triangle mesh, once each
  function edges(f){
    const seen = new Set(), out = [];
    for(let j = 0; j < f.length; j += 3){
      for(const [a, b] of [[f[j], f[j+1]], [f[j+1], f[j+2]], [f[j+2], f[j]]]){
        const k = a < b ? a + ',' + b : b + ',' + a;
        if(!seen.has(k)){ seen.add(k); out.push(a, b); }
      }
    }
    return out;
  }

  function create(div, opts){
    const {dec, hex} = V3DU;
    let viewer = null, plugin = null, mvs = null;
    const geoms = new Map();        // geometry name -> its JSON (as sent by the server)
    let refs = new Map();           // MVS ref -> geometry name, for the last load
    let bg = opts.bg, empty = true, pendingView = null, dirty = false, flushing = null;
    let canvas = opts.canvas || null;   // Mol* settings chosen by the user (null: our defaults)
    let defaults = null, ON = null, lastApplied = '';

    function readCanvas(){
      const p = plugin.canvas3d.props, o = {};
      ['postprocessing', 'cameraFog', 'cameraClipping', 'illumination', 'renderer', 'multiSample']
        .forEach(k => { if(p[k] !== undefined) o[k] = clone(p[k]); });
      if(o.renderer) delete o.renderer.backgroundColor;      // the page theme's
      return o;
    }
    function applyCanvas(){
      const c = clone(canvas || defaults);
      c.renderer = Object.assign({}, c.renderer || {}, {backgroundColor: parseInt(bg.slice(1), 16)});
      plugin.canvas3d.setProps(c);
      lastApplied = JSON.stringify(readCanvas());
    }
    // the user changed a setting in Mol*'s viewport (gear panel, illumination button)
    function noticeCanvas(){
      if(!plugin) return;
      const now = JSON.stringify(readCanvas());
      if(now === lastApplied) return;
      lastApplied = now;
      canvas = JSON.parse(now);
      if(opts.onCanvas) opts.onCanvas(canvas);
    }

    const ready = (async () => {
      await loadMolstar(opts.status);
      mvs = molstar.PluginExtensions.mvs;
      viewer = await molstar.Viewer.create(div, {
        layoutIsExpanded: false, layoutShowControls: false, layoutShowRemoteState: false,
        layoutShowSequence: true, layoutShowLog: false, layoutShowLeftPanel: true,
        viewportShowExpand: false, viewportShowSelectionMode: false, viewportShowAnimation: false,
        viewportShowTrajectoryControls: false, viewportShowToggleFullscreen: false,
        viewportFocusBehavior: 'disabled', volumeStreamingDisabled: true,
        viewportBackgroundColor: bg,
      });
      plugin = viewer.plugin;
      // the parameters of each effect when it is on: Mol* fills them in for an MVS canvas node
      const base = readCanvas();
      const b = mvs.createBuilder();
      b.canvas({custom: {molstar_postprocessing: {enable_outline: true, enable_shadow: true, enable_ssao: true,
                                                   enable_fog: true, enable_depth_of_field: true}}});
      await mvs.loadMVS(plugin, b.getState(), {});
      const p = plugin.canvas3d.props;
      ON = {outline: clone(p.postprocessing.outline), shadow: clone(p.postprocessing.shadow),
            occlusion: clone(p.postprocessing.occlusion), dof: clone(p.postprocessing.dof), fog: clone(p.cameraFog)};
      if(base.postprocessing.occlusion.name === 'on') ON.occlusion = base.postprocessing.occlusion;
      if(base.cameraFog.name === 'on') ON.fog = base.cameraFog;
      // ours: Mol*'s defaults (ambient occlusion...) with silhouettes and fog
      defaults = clone(base);
      defaults.postprocessing.outline = ON.outline;
      defaults.cameraFog = ON.fog;
      await mvs.loadMVS(plugin, mvs.createBuilder().getState(), {});
      applyCanvas();
      plugin.behaviors.interaction.click.subscribe(onClick);
      if(plugin.events.canvas3d && plugin.events.canvas3d.settingsUpdated)
        plugin.events.canvas3d.settingsUpdated.subscribe(() => setTimeout(noticeCanvas, 0));
    })();
    ready.catch(e => { if(opts.status) opts.status('Mol* could not start: ' + e.message); });

    /* ---- the scene as MVS ---- */
    function addMol(b, ref, g){
      const fmt = g.format || 'pdb';
      // a REMARK makes each geometry's data distinct, so it gets its own model (picking)
      const text = fmt === 'pdb' ? 'REMARK 999 WEWOS ' + ref + '\n' + g.data : g.data;
      const s = b.download({url: dataUrl(text)}).parse({format: fmt}).modelStructure({ref});
      (g.instances || []).forEach(M => s.instance({matrix: colMajor(M)}));
      let colUri = null;
      if(g.atomColors){
        const c = dec(g.atomColors), rows = [];
        for(let i = 0; i < c.length / 3; i++) rows.push({atom_index: i, color: hex([c[3*i], c[3*i+1], c[3*i+2]])});
        colUri = dataUrl(JSON.stringify(rows));
      }
      (g.styles || []).forEach(([sel, st]) => {
        const comp = s.component({selector: selector(sel)});
        for(const rep in (st || {})){
          const type = REPS[rep];
          if(!type) continue;
          const o = st[rep] || {}, params = {type};
          if(type === 'spacefill' && o.scale) params.size_factor = o.scale;
          const c = o.color;
          let th = null;
          if(c === 'spectrum') th = 'sequence-id';
          else if(!c && o.colorscheme) th = theme(o.colorscheme);
          else if(!c && !colUri && rep !== 'cartoon') th = 'element-symbol';   // 3Dmol's default
          const r = comp.representation(params);
          // Mol* color themes go on a color node
          if(th) r.color({custom: {molstar_color_theme_name: th}});
          else if(c) r.color({color: mvsColor(c)});
          else if(colUri) r.colorFromUri({uri: colUri, format: 'json', schema: 'all_atomic'});
          else r.color({custom: {molstar_use_default_coloring: true}});
          if(o.opacity != null && o.opacity < 1) r.opacity({opacity: o.opacity});
        }
      });
      (g.surfaces || []).forEach(sf => {
        const th = sf.colorscheme ? theme(sf.colorscheme) : null;
        const r = s.component({selector: selector(sf.sel)}).representation({type: 'surface', surface_type: 'molecular'});
        if(th) r.color({custom: {molstar_color_theme_name: th}});
        else r.color({color: sf.color ? mvsColor(sf.color) : '#ffffff'});
        r.opacity({opacity: sf.opacity == null ? 0.85 : sf.opacity});
      });
    }
    function addGeom(b, ref, g){
      const alpha = g.opacity == null ? 1 : g.opacity, tip = g.name;
      if(g.type === 'mol') return addMol(b, ref, g);
      if(g.type === 'spheres'){
        const c = dec(g.centers), r = dec(g.radii), cols = dec(g.colors), base = hex(g.color);
        const pr = b.primitives({ref, opacity: alpha});
        for(let i = 0; i < c.length / 3; i++)
          pr.ellipsoid({center: xyz(c, i), radius: r ? r[i] : g.radius, tooltip: tip,
                        color: cols ? hex(xyz(cols, i)) : base});
      } else if(g.type === 'cylinders'){
        const s = dec(g.starts), e = dec(g.ends), r = dec(g.radii), cols = dec(g.colors), base = hex(g.color);
        const pr = b.primitives({ref, opacity: alpha});
        for(let i = 0; i < s.length / 3; i++){
          const rad = r ? r[i] : g.radius, color = cols ? hex(xyz(cols, i)) : base;
          if(g.arrows) pr.arrow({start: xyz(s, i), end: xyz(e, i), tube_radius: rad, show_end_cap: true,
                                 end_cap_radius: 2 * rad, color, tooltip: tip});
          else pr.tube({start: xyz(s, i), end: xyz(e, i), radius: rad, color, tooltip: tip});
        }
      } else if(g.type === 'lines' || (g.type === 'mesh' && g.wireframe)){
        let p = dec(g.vertices), faces = g.type === 'mesh' ? dec(g.faces) : null, vc = dec(g.colors);
        if(faces && g.instances && g.instances.length)
          ({p, f: faces, cols: vc} = V3DU.expandMesh(p, faces, null, vc, g.instances));
        const seg = g.type === 'lines' ? Array.from(dec(g.segments)) : edges(faces);
        const ns = seg.length / 2;
        const sc = V3DU.segmentColors(seg, vc);
        const params = {vertices: Array.from(p), indices: seg, width: 1.5, tooltip: tip};
        if(sc){
          const groups = new Map(), lg = new Array(ns);
          for(let i = 0; i < ns; i++){
            const k = hex(xyz(sc, i));
            if(!groups.has(k)) groups.set(k, groups.size);
            lg[i] = groups.get(k);
          }
          params.line_groups = lg;
          params.group_colors = {};
          groups.forEach((gi, k) => { params.group_colors[gi] = k; });
        } else params.color = hex(g.type === 'lines' ? V3DU.lineColor(g) : g.color);
        b.primitives({ref, opacity: alpha}).lines(params);
      } else if(g.type === 'mesh'){
        const cols = dec(g.colors);
        const sh = b.download({url: dataUrl(ply(dec(g.vertices), dec(g.faces), dec(g.normals), cols))})
          .parse({format: 'ply'}).shape({ref, custom: {ply_coloring: cols ? 'vertex' : 'uniform'}});
        if(!cols) sh.color({color: hex(g.color)});
        if(alpha < 1) sh.opacity({opacity: alpha});
        // copies made by the graphics card
        (g.instances || []).forEach(M => sh.instance({matrix: colMajor(M)}));
      } else if(g.type === 'labels'){
        const p = dec(g.positions), cols = dec(g.colors), base = hex(g.color);
        const pr = b.primitives({ref});
        (g.labels || []).forEach((t, i) => pr.label({position: xyz(p, i), text: String(t),
          label_size: (g.fontSize || 14) * 0.12, label_color: cols ? hex(xyz(cols, i)) : base}));
      }
    }
    function build(){
      const b = mvs.createBuilder();
      refs = new Map();
      let k = 0;
      geoms.forEach((g, name) => {
        if(!g.visible) return;
        const ref = 'g' + (k++);
        refs.set(ref, name);
        try { addGeom(b, ref, g); }
        catch(e){ console.warn('Mol*: could not describe', name, e); }
      });
      return b.getState();
    }

    /* ---- picking ---- */
    const modelOf = st => st && (st.model || (st.models && st.models[0]));
    function owner(test){
      for(const [ref, name] of refs){
        const cells = mvs.util.queryMVSRef(plugin, ref) || [];
        if(cells.some(test)) return name;
      }
      return null;
    }
    function onClick(e){
      const loci = e.current && e.current.loci;
      if(!loci || loci.kind === 'empty-loci') return;
      const S = molstar.lib.structure;
      let name = null, atom = null;
      if(S.StructureElement.Loci.is(loci)){
        const model = modelOf(loci.structure);
        name = owner(c => c.obj && c.obj.data && modelOf(c.obj.data) === model);
        const l = S.StructureElement.Loci.getFirstLocation(loci), P = S.StructureProperties;
        if(l) atom = {index: P.atom.sourceIndex(l), serial: P.atom.id(l), atom: P.atom.auth_atom_id(l),
                      resn: P.residue.auth_comp_id(l), resi: P.residue.auth_seq_id(l), chain: P.chain.auth_asym_id(l),
                      elem: P.atom.type_symbol(l), x: P.atom.x(l), y: P.atom.y(l), z: P.atom.z(l)};
      } else {
        const prims = mvs.util.tryGetPrimitivesFromLoci(loci);
        if(prims && prims.length) name = prims[0].params && prims[0].params.tooltip;
        else if(loci.shape) name = owner(c => c.obj && c.obj.data && c.obj.data.repr && c.obj.data.repr.getAllLoci &&
                                             c.obj.data.repr.getAllLoci().some(x => x.shape === loci.shape));
      }
      const g = name && geoms.get(name);
      if(!g || !g.pickable) return;
      opts.onPick(atom ? {geom: name, atom} : {geom: name});
    }

    return {
      kind: 'molstar',
      ready,
      set(g){ geoms.set(g.name, g); dirty = true; },
      remove(name){ if(geoms.delete(name)) dirty = true; },
      async flush(){
        await ready;
        while(flushing) await flushing;
        if(!dirty) return;
        dirty = false;
        flushing = (async () => {
          const tree = build();
          const issues = mvs.MVSData.validationIssues(tree);
          if(issues && issues.length){ console.warn('Mol* scene:', issues); if(opts.status) opts.status('Mol*: ' + issues[0]); }
          const has = refs.size > 0;
          await mvs.loadMVS(plugin, tree, {keepCamera: !empty && has});
          applyCanvas();
          if(pendingView && has){ plugin.managers.camera.setSnapshot(pendingView, 0); pendingView = null; }
          empty = !has;
        })();
        try { await flushing; } finally { flushing = null; }
      },
      fit(){ if(plugin) plugin.managers.camera.reset(); },
      getView(){ return plugin ? clone(plugin.canvas3d.camera.getSnapshot()) : null; },
      setView(view){
        if(!view) return;
        if(!plugin || empty) pendingView = view;
        else plugin.managers.camera.setSnapshot(view, 0);
      },
      async png(){
        await ready;
        while(flushing) await flushing;
        // Mol* adds what was just loaded to its canvas at the next frame: do it now
        try { plugin.canvas3d.commit(true); } catch(e) {}
        await new Promise(r => requestAnimationFrame(() => r()));
        return plugin.helpers.viewportScreenshot.getImageDataUri();
      },
      setRendering(){},                       // 3Dmol's settings: Mol* has its own (canvas)
      setCanvas(c){ canvas = c ? clone(c) : null; if(plugin) applyCanvas(); },
      getCanvas(){ return canvas; },
      // the quick switches of the panel: is an effect on, and turn it on or off
      effect(k){
        if(!plugin) return false;
        const p = plugin.canvas3d.props;
        if(k === 'fog') return p.cameraFog.name === 'on';
        if(k === 'illumination') return !!(p.illumination && p.illumination.enabled);
        return p.postprocessing[k] && p.postprocessing[k].name === 'on';
      },
      setEffect(k, on){
        if(!plugin) return;
        const c = readCanvas();
        if(k === 'fog') c.cameraFog = on ? ON.fog : {name: 'off', params: {}};
        else if(k === 'illumination') c.illumination = Object.assign({}, c.illumination, {enabled: !!on});
        else c.postprocessing[k] = on ? ON[k] : {name: 'off', params: {}};
        canvas = c;
        applyCanvas();
        if(opts.onCanvas) opts.onCanvas(canvas);
      },
      background(c){ bg = c; molstarTheme(); if(plugin) applyCanvas(); },
      resize(){ try { if(viewer) viewer.handleResize(); if(plugin) plugin.canvas3d.requestResize(); } catch(e) {} },
      interacted(){ setTimeout(noticeCanvas, 50); },
      dispose(){ try { if(viewer) viewer.dispose(); } catch(e) {} div.innerHTML = ''; },
    };
  }
})();
