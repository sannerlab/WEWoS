/* Author: Michel Sanner, PhD. Copyright (c) 2026. */
/* The network editor: an SVG canvas replacing NetworkEditor's Tk canvas.

   Nodes are drawn left to right: input ports on the left edge, output ports
   on the right edge, one row per port; an input bound to a widget shown in
   the node has the widget on its row (and no port icon, as in Vision); an
   input whose widget lives in the parameter panel is not drawn. The special
   ports are small squares: runNode on the top edge, trigger on the bottom.

   The editor draws what the store holds (app.js keeps it in step with the
   server) and reports user actions through callbacks; it never changes the
   network itself. */
'use strict';
const ED = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const HEAD = 22, ROW = 22, PR = 5;
  let svg, world, gConns, gNodes, gTop, cb;
  let NET = null;                  // the network shown: {id, nodes:{}, conns:{}}
  let TYPES = {};
  let view = {x: 40, y: 30, k: 1};
  const views = {};                // per network id
  const geo = {};                  // node id -> {w, h, ins:{name:[x,y]}, outs:{name:[x,y]}, run:[x,y], trig:[x,y]}
  const gEls = {};                 // node id -> <g>
  const cEls = {};                 // conn id -> <path>
  let SEL = new Set(), CSEL = new Set();

  const S = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for(const k in (attrs || {})) if(attrs[k] != null) e.setAttribute(k, attrs[k]);
    return e;
  };
  const tw = (s, px) => String(s || '').length * (px || 6.4);   // text width estimate
  const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');

  /* ------------------------------------------------------------ setup */
  function init(svgEl, callbacks){
    svg = svgEl; cb = callbacks;
    const defs = S('defs');
    const pat = S('pattern', {id: 'grid', width: 24, height: 24, patternUnits: 'userSpaceOnUse'});
    pat.append(S('path', {d: 'M24 0H0V24', fill: 'none', stroke: 'var(--grid)', 'stroke-width': 1}));
    defs.append(pat);
    svg.append(defs);
    world = S('g', {id: 'world'});
    const bg = S('rect', {x: -50000, y: -50000, width: 100000, height: 100000, fill: 'url(#grid)', class: 'bg'});
    gConns = S('g'); gNodes = S('g'); gTop = S('g');
    world.append(bg, gConns, gNodes, gTop);
    svg.append(world);
    bindCanvas();
  }
  function setTypes(t){ TYPES = t || {}; }
  function applyView(){ world.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`); }
  function toWorld(cx, cy){
    const r = svg.getBoundingClientRect();
    return [(cx - r.left - view.x) / view.k, (cy - r.top - view.y) / view.k];
  }

  /* ------------------------------------------------------------ geometry */
  /* A long port name is shown short in the node (its full name is in the
     tooltip and the parameter panel): the last part after "_" when that is
     short enough, else each camelCase word cut short: indexedPolygons_
     instanceMatrices -> instMat. wewos/engine/layout.py has the same rules. */
  const SHORT = 12;
  function cutWord(w, i){
    if(i === 0){ let c = w.slice(0, 4); if(w.length > 4 && /[aeiou]$/i.test(c)) c = c.slice(0, 3); return c; }
    return w[0].toUpperCase() + w.slice(1, 3);
  }
  // one name part cut short: its camelCase words, or its first letters
  function abbrev(s){
    if(s.length <= SHORT) return s;
    const words = s.replace(/([a-z0-9])([A-Z])/g, '$1 $2').split(' ').filter(Boolean);
    if(words.length < 2) return s.slice(0, SHORT - 1) + '…';
    return words.map(cutWord).join('');
  }
  // several parts, each kept when short, joined in camelCase
  function compact(parts){
    return parts.map((p, i) => {
      const q = p.length <= 6 ? p : abbrev(p);
      return i ? q[0].toUpperCase() + q.slice(1) : q;
    }).join('');
  }
  function shortName(name){
    name = String(name || '');
    if(name.length <= SHORT) return name;
    const parts = name.split('_').filter(Boolean);
    let best = '';
    for(let k = 1; k <= parts.length; k++){              // the longest tail of whole parts that fits
      const tail = parts.slice(-k).join('_');
      if(tail.length > SHORT) break;
      best = tail;
    }
    if(best.length >= 4) return best;
    if(best) return compact(parts.slice(-2));
    return abbrev(parts.length ? parts[parts.length - 1] : name);
  }
  // short names of one side of a node, different from each other
  function shortNames(names){
    const out = {}, seen = {};
    names.forEach(n => { out[n] = shortName(n); seen[out[n]] = (seen[out[n]] || 0) + 1; });
    names.forEach(n => {
      if(seen[out[n]] > 1 && out[n] !== n) out[n] = compact(n.split('_').filter(Boolean));
    });
    const again = {};
    names.forEach(n => { const s = out[n]; again[s] = (again[s] || 0) + 1;
                         if(again[s] > 1) out[n] = s + again[s]; });
    return out;
  }
  // how wide a widget is drawn in a node (wewos/engine/layout.py: widget_width):
  // the width the user chose (widget option nodeWidth), else what it holds needs
  const digits = x => String(Math.trunc(Math.abs(+x || 0))).length;
  function numberChars(w){
    const o = w.options || {};
    const vals = [w.value, o.min, o.max].filter(v => v != null && v !== '' && isFinite(+v));
    let n = Math.max(1, ...vals.map(digits));
    if(vals.some(v => +v < 0)) n += 1;
    if(o.type !== 'int') n += 1 + Math.min(o.precision == null ? 3 : +o.precision, 3);
    return Math.max(2, Math.min(10, n));
  }
  const textChars = (v, lo, hi) => Math.max(lo, Math.min(hi, String(v == null ? '' : v).length));
  function widgetW(w){
    const o = (w && w.options) || {};
    if(o.nodeWidth) return Math.max(30, Math.min(400, +o.nodeWidth));
    switch(w && w.kind){
      case 'number': return 38 + numberChars(w) * 7;
      case 'checkbox': return 18;
      case 'entry': return 16 + textChars(w.value, 4, 16) * 6.6;
      case 'file': case 'dir': case 'filesave': return 46 + textChars(w.value, 6, 18) * 6.6;  // input padding + the … button
      case 'combo': {
        const longest = (o.choices || []).concat([w.value == null ? '' : w.value])
          .reduce((m, c) => Math.max(m, String(c == null ? '' : c).length), 0);
        return Math.max(60, Math.min(130, longest * 6.5 + 28)); }
      case 'button': return Math.min(120, tw(o.text || w.label || 'press', 6.5) + 20);
      case 'color': return 30;
      case 'colormap': return 124;
      case 'vector': return 110;
      default: return 100;
    }
  }
  function rows(n){
    // visible input rows: ports with no widget, or a widget shown in the node
    const r = [];
    (n.in || []).forEach(p => {
      if(!p.widget) r.push({p, kind: 'port'});
      else if(p.widget.master === 'node') r.push({p, kind: 'widget'});
    });
    return r;
  }
  // the label of a widget in a node: its own label, else the port's short name
  const widgetLabel = (p, short) => p.widget.label || short[p.name] || p.name;
  function layout(n){
    const rs = rows(n), outs = n.out || [];
    const inShort = shortNames(rs.map(r => r.p.name)), outShort = shortNames(outs.map(p => p.name));
    let inW = 0, wid = false;
    rs.forEach(r => {
      if(r.kind === 'widget'){
        wid = true;
        const lw = r.p.widget.label === '' ? 0 : Math.min(tw(widgetLabel(r.p, inShort), 6), 70) + 4;
        inW = Math.max(inW, lw + widgetW(r.p.widget));
      }
      else inW = Math.max(inW, tw(inShort[r.p.name], 5.8) + 14);
    });
    const outW = outs.reduce((m, p) => Math.max(m, tw(outShort[p.name], 5.8) + 14), 0);
    const w = Math.max(110, tw(n.label || n.name, 7.2) + 34, inW + outW + (outs.length && rs.length ? 22 : 10));
    const nrows = Math.max(rs.length, outs.length, 1);
    const h = HEAD + nrows * ROW + 6 + (n.progbar ? 4 : 0);
    const g = {w, h, ins: {}, outs: {}, rows: rs, wid, inShort, outShort};
    rs.forEach((r, i) => { if(r.kind === 'port') g.ins[r.p.name] = [0, HEAD + i * ROW + ROW / 2]; });
    outs.forEach((p, i) => { g.outs[p.name] = [w, HEAD + i * ROW + ROW / 2]; });
    g.run = [w / 2, 0]; g.trig = [w / 2, h];
    return g;
  }
  function portXY(nid, io, name){
    const n = NET.nodes[nid], g = geo[nid];
    if(!n || !g) return null;
    let p;
    if(io === 'out') p = name === 'trigger' ? g.trig : g.outs[name];
    else p = name === 'runNode' ? g.run : g.ins[name];
    if(!p) return null;
    return [n.pos[0] + p[0], n.pos[1] + p[1]];
  }

  /* ------------------------------------------------------------ drawing */
  function shape(t, x, y, io){
    const ty = TYPES[t] || {color: 'white', shape: 'diamond'};
    const fill = ty.color || 'white';
    const s = ty.shape;
    let e;
    if(s === 'circle' || s === 'oval') e = S('circle', {cx: x, cy: y, r: PR});
    else if(s === 'rect' || s === 'square') e = S('rect', {x: x - PR, y: y - PR, width: 2 * PR, height: 2 * PR});
    else if(typeof s === 'number' && s >= 3){
      const pts = [];
      for(let i = 0; i < s; i++){ const a = Math.PI * 2 * i / s - Math.PI / 2;
        pts.push((x + PR * 1.25 * Math.cos(a)).toFixed(1) + ',' + (y + PR * 1.25 * Math.sin(a)).toFixed(1)); }
      e = S('polygon', {points: pts.join(' ')});
    }
    else if(s === 'triangle') e = S('polygon', {points: `${x-PR},${y-PR} ${x+PR},${y} ${x-PR},${y+PR}`});
    else e = S('polygon', {points: `${x},${y-PR-1} ${x+PR+1},${y} ${x},${y+PR+1} ${x-PR-1},${y}`});
    e.setAttribute('fill', fill);
    return e;
  }

  function drawNode(n){
    const g = geo[n.id] = layout(n);
    const old = gEls[n.id];
    const el = nodeShape(n, g);
    el.setAttribute('transform', `translate(${n.pos[0]},${n.pos[1]})`);
    nodeClasses(el, n);
    if(old) gNodes.replaceChild(el, old); else gNodes.append(el);
    gEls[n.id] = el;
  }
  // a port's label; a shortened name shows the full one as a tooltip
  function portLabel(x, y, name, short, anchor){
    const l = S('text', {class: 'plabel', x, y: y + 3.5, 'text-anchor': anchor});
    l.textContent = short || name;
    if(short && short !== name){ const t = S('title'); t.textContent = name; l.append(t); }
    return l;
  }
  // a node's picture; a ghost (a palette node dragged to the network) has no
  // id and shows its widgets as empty boxes
  function nodeShape(n, g, ghost){
    const el = S('g', {class: 'node', 'data-id': n.id});
    const color = n.color || '#9aa4b8';
    el.append(S('rect', {class: 'body', x: 0, y: 0, rx: 6, width: g.w, height: g.h}));
    const head = S('path', {class: 'head', fill: color, opacity: 0.85,
      d: `M0 ${HEAD}V6Q0 0 6 0H${g.w - 6}Q${g.w} 0 ${g.w} 6V${HEAD}Z`});
    el.append(head);
    const title = S('text', {class: 'title', x: 8, y: 15}); title.textContent = n.label || n.name;
    el.append(title);
    if(n.macro){ const b = S('text', {class: 'badge', x: g.w - 8, y: 14, 'text-anchor': 'end'}); b.textContent = '▣'; el.append(b); }
    if(n.codeModified){ const b = S('text', {class: 'badge', x: g.w - (n.macro ? 20 : 8), y: 14, 'text-anchor': 'end'});
      b.textContent = '✎'; el.append(b); }
    // input rows
    g.rows.forEach((r, i) => {
      const y = HEAD + i * ROW + ROW / 2;
      if(r.kind === 'port'){
        const s = shape(r.p.datatype, 0, y, 'in');
        s.setAttribute('class', 'port');
        s.dataset.io = 'in'; s.dataset.port = r.p.name; s.dataset.node = n.id;
        const ti = S('title'); ti.textContent = `${r.p.name}: ${r.p.datatype}${r.p.required ? '' : ' (optional)'}${r.p.balloon ? '\n' + r.p.balloon : ''}`;
        s.append(ti);
        el.append(portLabel(9, y, r.p.name, g.inShort[r.p.name], 'start'), s);
      } else if(ghost){
        const lab = widgetLabel(r.p, g.inShort);
        const lw = r.p.widget.label === '' ? 0 : Math.min(tw(lab, 6), 70) + 6;
        if(lw){ const l = S('text', {class: 'plabel', x: 8, y: y + 3.5}); l.textContent = lab; el.append(l); }
        const ow = n.out && n.out[i] ? tw(g.outShort[n.out[i].name], 5.8) + 14 : 0;
        el.append(S('rect', {class: 'wbox', x: 8 + lw, y: y - ROW / 2 + 3, rx: 3, height: ROW - 6,
                             width: Math.max(20, g.w - 16 - lw - ow)}));
      } else {
        const fo = S('foreignObject', {x: 6, y: y - ROW / 2, width: g.w - 12 - (n.out && n.out[i] ? tw(g.outShort[n.out[i].name], 5.8) + 14 : 0), height: ROW});
        const div = document.createElementNS('http://www.w3.org/1999/xhtml', 'div');
        div.className = 'nw';
        const row = document.createElement('div'); row.className = 'wrow'; row.dataset.port = r.p.name;
        const lab = document.createElement('label'); lab.textContent = widgetLabel(r.p, g.inShort);
        lab.title = r.p.name + ': ' + r.p.datatype + '\nright-click: wider or narrower';
        if(r.p.widget.label !== '') row.append(lab);
        // the widget keeps its own width (what it holds, or what the user chose)
        // even when the node is wider, for its title or another row
        const wEl = W.render(r.p.widget, cb.widgetCtx(n.id, r.p.name, true));
        wEl.style.flex = '0 0 auto';
        wEl.style.width = widgetW(r.p.widget) + 'px';
        row.append(wEl);
        div.append(row); fo.append(div); el.append(fo);
      }
    });
    (n.out || []).forEach((p, i) => {
      const y = HEAD + i * ROW + ROW / 2;
      const s = shape(p.datatype, g.w, y, 'out');
      s.setAttribute('class', 'port');
      s.dataset.io = 'out'; s.dataset.port = p.name; s.dataset.node = n.id;
      const ti = S('title'); ti.textContent = `${p.name}: ${p.datatype}${p.balloon ? '\n' + p.balloon : ''}\n(right-click: show data)`;
      s.append(ti);
      el.append(portLabel(g.w - 9, y, p.name, g.outShort[p.name], 'end'), s);
    });
    // special ports: runNode on top, trigger at the bottom
    const sp1 = S('rect', {class: 'port special', x: g.run[0] - 3.5, y: -3.5, width: 7, height: 7});
    sp1.dataset.io = 'in'; sp1.dataset.port = 'runNode'; sp1.dataset.node = n.id;
    sp1.append(Object.assign(S('title'), {textContent: 'runNode: a connection here runs this node'}));
    const sp2 = S('rect', {class: 'port special', x: g.trig[0] - 3.5, y: g.h - 3.5, width: 7, height: 7});
    sp2.dataset.io = 'out'; sp2.dataset.port = 'trigger'; sp2.dataset.node = n.id;
    sp2.append(Object.assign(S('title'), {textContent: 'trigger: runs the connected nodes after this one'}));
    el.append(sp1, sp2);
    if(n.progbar){
      el.append(S('rect', {class: 'prog', x: 0, y: g.h - 4, height: 3, width: g.w * (n.progress || 0)}));
    }
    if(!ghost){
      const tip = S('title');
      tip.textContent = n.name + ' (' + (n.lib || '') + ' ' + n.cls + ')' + (n.unsupported ? '\nNOT AVAILABLE: ' + JSON.stringify(n.unsupported) : '');
      head.append(tip);
    }
    return el;
  }
  function nodeClasses(el, n){
    const c = ['node'];
    if(SEL.has(n.id)) c.push('sel');
    if(n.frozen) c.push('frozen');
    if(n.status === 'running' || n.status === 'error' || n.status === 'stopped') c.push(n.status);
    if(n.unsupported) c.push('unsupported');
    el.setAttribute('class', c.join(' '));
  }

  function connPath(c){
    const a = portXY(c.from[0], 'out', c.from[1]), b = portXY(c.to[0], 'in', c.to[1]);
    if(!a || !b) return null;
    if(c.special) {
      const dy = Math.max(30, Math.abs(b[1] - a[1]) / 2);
      return `M${a[0]} ${a[1]}C${a[0]} ${a[1] + dy} ${b[0]} ${b[1] - dy} ${b[0]} ${b[1]}`;
    }
    const dx = Math.max(40, Math.abs(b[0] - a[0]) / 2);
    return `M${a[0]} ${a[1]}C${a[0] + dx} ${a[1]} ${b[0] - dx} ${b[1]} ${b[0]} ${b[1]}`;
  }
  function drawConn(c){
    const d = connPath(c);
    let p = cEls[c.id];
    if(!d){ if(p){ p.remove(); delete cEls[c.id]; } return; }
    if(!p){
      p = S('path', {'data-id': c.id});
      gConns.append(p);
      cEls[c.id] = p;
      p.append(S('title'));
    }
    const ty = TYPES[c.datatype] || {};
    p.setAttribute('d', d);
    p.setAttribute('stroke', c.special ? '#f08c00' : (ty.color && ty.color !== 'white' ? ty.color : '#8a93a6'));
    p.setAttribute('class', 'conn' + (c.blocking ? '' : ' nb') + (CSEL.has(c.id) ? ' sel' : ''));
    p.firstChild.textContent = `${c.from[1]} → ${c.to[1]} (${c.datatype}${c.blocking ? '' : ', non blocking'})`;
  }
  function connsOf(nid){
    return Object.values(NET.conns).filter(c => c.from[0] === nid || c.to[0] === nid);
  }

  /* ------------------------------------------------------------ public update api */
  function show(net){
    if(NET) views[NET.id] = Object.assign({}, view);
    NET = net;
    const first = !views[net.id];
    view = views[net.id] || {x: 40, y: 30, k: 1};
    applyView();
    gNodes.innerHTML = ''; gConns.innerHTML = '';
    for(const k in gEls) delete gEls[k];
    for(const k in cEls) delete cEls[k];
    SEL = new Set([...SEL].filter(id => net.nodes[id]));
    CSEL = new Set();
    Object.values(net.nodes).forEach(drawNode);
    Object.values(net.conns).forEach(drawConn);
    if(first && Object.keys(net.nodes).length) fit(1);    // a macro opened for the first time
  }
  function current(){ return NET; }
  function updateNode(id, full){
    if(!NET || !NET.nodes[id]) return;
    const el = gEls[id], n = NET.nodes[id];
    if(!full && el && el.contains(document.activeElement)){
      nodeClasses(el, n);               // keep the field being typed in
      return;
    }
    drawNode(n);
    connsOf(id).forEach(drawConn);
  }
  function statusOnly(id){
    const el = gEls[id];
    if(el && NET.nodes[id]) nodeClasses(el, NET.nodes[id]);
  }
  function progress(id, v){
    const el = gEls[id]; if(!el) return;
    const r = el.querySelector('.prog'); if(r) r.setAttribute('width', geo[id].w * v);
  }
  function moveNode(id){
    const n = NET.nodes[id], el = gEls[id];
    if(!n || !el) return;
    el.setAttribute('transform', `translate(${n.pos[0]},${n.pos[1]})`);
    connsOf(id).forEach(drawConn);
  }
  function removeNode(id){
    if(gEls[id]){ gEls[id].remove(); delete gEls[id]; }
    SEL.delete(id);
  }
  function addConn(c){ drawConn(c); }
  function removeConn(id){ if(cEls[id]){ cEls[id].remove(); delete cEls[id]; } CSEL.delete(id); }
  function selection(){ return {nodes: [...SEL], conns: [...CSEL]}; }
  function select(ids, add){
    if(!add){ SEL.clear(); CSEL.clear(); }
    ids.forEach(i => SEL.add(i));
    refreshSel();
  }
  function refreshSel(){
    Object.keys(gEls).forEach(id => statusOnly(id));
    Object.values(NET ? NET.conns : {}).forEach(drawConn);
    cb.selected([...SEL]);
  }
  function fit(maxK){
    if(!NET) return;
    const ns = Object.values(NET.nodes);
    if(!ns.length){ view = {x: 40, y: 30, k: 1}; applyView(); return; }
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    ns.forEach(n => { const g = geo[n.id] || {w: 120, h: 50};
      x0 = Math.min(x0, n.pos[0]); y0 = Math.min(y0, n.pos[1]);
      x1 = Math.max(x1, n.pos[0] + g.w); y1 = Math.max(y1, n.pos[1] + g.h); });
    const r = svg.getBoundingClientRect();
    const k = Math.min(maxK || 1.5, Math.max(0.2, Math.min((r.width - 60) / (x1 - x0 || 1), (r.height - 60) / (y1 - y0 || 1))));
    view = {k, x: 30 - x0 * k + Math.max(0, (r.width - 60 - (x1 - x0) * k) / 2), y: 30 - y0 * k};
    applyView();
  }
  function center(){ const r = svg.getBoundingClientRect(); return toWorld(r.left + r.width / 2 - 60, r.top + r.height / 2 - 30); }

  /* ------------------------------------------------------------ interaction */
  function compatible(outType, inType){
    if(!outType || !inType || outType === 'None' || inType === 'None') return true;
    if(outType === inType) return true;
    const b = t => t.split('(')[0];
    const num = new Set(['float', 'int', 'boolean', 'coord2', 'coord3', 'normal3', 'colorfloat3or4',
                         'instancemat', 'indice2', 'indice2+', 'indice3or4', '2Darray', 'colorRGB',
                         'colorsRGB', 'coordinates3D', 'faceIndices', 'normals3D', 'NumericArray']);
    const seq = new Set(['list', 'tuple', 'vector', 'NumericArray', 'array']);
    if(b(outType) === b(inType)) return true;
    if(num.has(b(outType)) && num.has(b(inType))) return true;
    if(seq.has(b(inType)) && (seq.has(b(outType)) || num.has(b(outType)))) return true;
    if(inType === 'string' || inType === 'str') return true;     // casts
    const ti = TYPES[inType] || {}, to = TYPES[outType] || {};
    return false;
  }
  function portInfo(nid, io, name){
    const n = NET.nodes[nid];
    if(!n) return null;
    return (io === 'in' ? n.in : n.out).find(p => p.name === name) || {name, datatype: 'None', special: true};
  }
  function hasParent(nid, name){
    return Object.values(NET.conns).some(c => c.to[0] === nid && c.to[1] === name);
  }

  let drag = null;
  function bindCanvas(){
    svg.addEventListener('pointerdown', e => {
      if(e.button === 2) return;
      // on a Mac, Control-click is a right click: leave it to the context menu
      if(e.ctrlKey && IS_MAC && e.button === 0) return;
      svg.focus();
      const t = e.target;
      const port = t.closest && t.closest('.port');
      const nodeEl = t.closest && t.closest('.node');
      const conn = t.closest && t.closest('.conn');
      const [wx, wy] = toWorld(e.clientX, e.clientY);
      if(port){
        e.preventDefault();
        const nid = port.dataset.node, io = port.dataset.io, name = port.dataset.port;
        const start = portXY(nid, io, name);
        const line = S('path', {class: 'rubber'});
        gTop.append(line);
        const info = portInfo(nid, io, name);
        markTargets(nid, io, info);
        drag = {kind: 'wire', nid, io, name, start, line, info};
      } else if(nodeEl){
        const nid = nodeEl.dataset.id;
        if(e.shiftKey || e.metaKey || (e.ctrlKey && !IS_MAC)){
          if(SEL.has(nid)) SEL.delete(nid); else SEL.add(nid);
          CSEL.clear(); refreshSel();
        } else if(!SEL.has(nid)){ SEL = new Set([nid]); CSEL.clear(); refreshSel(); }
        const start = {};
        SEL.forEach(id => { if(NET.nodes[id]) start[id] = NET.nodes[id].pos.slice(); });
        drag = {kind: 'move', x: wx, y: wy, start, moved: false};
      } else if(conn){
        const id = conn.dataset.id;
        if(!e.shiftKey){ SEL.clear(); CSEL.clear(); }
        CSEL.add(id); refreshSel();
      } else if(e.shiftKey){
        const box = S('rect', {class: 'selbox'});
        gTop.append(box);
        drag = {kind: 'box', x: wx, y: wy, box};
      } else {
        if(SEL.size || CSEL.size){ SEL.clear(); CSEL.clear(); refreshSel(); }
        drag = {kind: 'pan', x: e.clientX, y: e.clientY, vx: view.x, vy: view.y};
      }
      if(drag) svg.setPointerCapture(e.pointerId);
    });
    svg.addEventListener('pointermove', e => {
      if(!drag) return;
      const [wx, wy] = toWorld(e.clientX, e.clientY);
      if(drag.kind === 'pan'){
        view.x = drag.vx + e.clientX - drag.x; view.y = drag.vy + e.clientY - drag.y; applyView();
      } else if(drag.kind === 'move'){
        const dx = wx - drag.x, dy = wy - drag.y;
        if(Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
        for(const id in drag.start){
          NET.nodes[id].pos = [drag.start[id][0] + dx, drag.start[id][1] + dy];
          moveNode(id);
        }
      } else if(drag.kind === 'wire'){
        const [x0, y0] = drag.start;
        const a = drag.io === 'out' ? [x0, y0] : [wx, wy], b = drag.io === 'out' ? [wx, wy] : [x0, y0];
        const dx = Math.max(40, Math.abs(b[0] - a[0]) / 2);
        drag.line.setAttribute('d', `M${a[0]} ${a[1]}C${a[0] + dx} ${a[1]} ${b[0] - dx} ${b[1]} ${b[0]} ${b[1]}`);
      } else if(drag.kind === 'box'){
        const x = Math.min(wx, drag.x), y = Math.min(wy, drag.y);
        Object.assign(drag, {x1: x, y1: y, x2: Math.max(wx, drag.x), y2: Math.max(wy, drag.y)});
        drag.box.setAttribute('x', x); drag.box.setAttribute('y', y);
        drag.box.setAttribute('width', Math.abs(wx - drag.x)); drag.box.setAttribute('height', Math.abs(wy - drag.y));
      }
    });
    const end = e => {
      if(!drag) return;
      const d = drag; drag = null;
      if(d.kind === 'move' && d.moved){
        const nodes = {};
        for(const id in d.start) nodes[id] = NET.nodes[id].pos.map(v => Math.round(v));
        cb.edit('move', {nodes});
      } else if(d.kind === 'wire'){
        d.line.remove(); clearTargets();
        const t = document.elementFromPoint(e.clientX, e.clientY);
        const port = t && t.closest && t.closest('.port');
        if(port && port.dataset.io !== d.io && port.dataset.node !== d.nid){
          const a = d.io === 'out' ? [d.nid, d.name] : [port.dataset.node, port.dataset.port];
          const b = d.io === 'out' ? [port.dataset.node, port.dataset.port] : [d.nid, d.name];
          cb.edit('connect', {from: a, to: b});
        }
      } else if(d.kind === 'box'){
        d.box.remove();
        if(d.x1 != null){
          Object.values(NET.nodes).forEach(n => {
            const g = geo[n.id];
            if(n.pos[0] >= d.x1 && n.pos[1] >= d.y1 && n.pos[0] + g.w <= d.x2 && n.pos[1] + g.h <= d.y2) SEL.add(n.id);
          });
          refreshSel();
        }
      }
    };
    svg.addEventListener('pointerup', end);
    svg.addEventListener('pointercancel', end);
    svg.addEventListener('wheel', e => {
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const k = Math.min(3, Math.max(0.15, view.k * Math.exp(-e.deltaY * 0.0015)));
      view.x = mx - (mx - view.x) * k / view.k; view.y = my - (my - view.y) * k / view.k; view.k = k;
      applyView();
    }, {passive: false});
    svg.addEventListener('dblclick', e => {
      // pressing a node captures the pointer (to drag it), and the browser then sends
      // the double-click to the canvas itself: look at what is under the pointer
      const t = document.elementFromPoint(e.clientX, e.clientY) || e.target;
      const nodeEl = t.closest && t.closest('.node');
      if(!nodeEl || (t.closest && t.closest('foreignObject'))) return;
      cb.dblclick(nodeEl.dataset.id);
    });
    svg.addEventListener('contextmenu', e => {
      e.preventDefault();
      const t = e.target;
      const port = t.closest && t.closest('.port');
      const nodeEl = t.closest && t.closest('.node');
      const conn = t.closest && t.closest('.conn');
      const wrow = t.closest && t.closest('.wrow');
      if(port) cb.contextPort(port.dataset.node, port.dataset.io, port.dataset.port, e);
      else if(nodeEl && wrow && cb.contextWidget){
        // a widget shown in the node: its menu (unbind...), then the node's
        const id = nodeEl.dataset.id;
        if(!SEL.has(id)){ SEL = new Set([id]); CSEL.clear(); refreshSel(); }
        cb.contextWidget(id, wrow.dataset.port, e);
      }
      else if(nodeEl){
        const id = nodeEl.dataset.id;
        if(!SEL.has(id)){ SEL = new Set([id]); CSEL.clear(); refreshSel(); }
        cb.contextNode(id, e);
      }
      else if(conn) cb.contextConn(conn.dataset.id, e);
      else cb.contextCanvas(toWorld(e.clientX, e.clientY), e);
    });
    svg.addEventListener('keydown', e => {
      if(e.target !== svg) return;
      const mod = e.ctrlKey || e.metaKey;
      if(e.key === 'Delete' || e.key === 'Backspace'){
        if(SEL.size || CSEL.size){ e.preventDefault(); cb.edit('delete', {nodes: [...SEL], conns: [...CSEL]}); }
      } else if(mod && e.key === 'a'){ e.preventDefault(); select(Object.keys(NET.nodes)); }
      else if(mod && e.key === 'c'){ if(SEL.size) cb.edit('copy', {nodes: [...SEL]}); }
      else if(mod && e.key === 'v'){ cb.paste(); }
      else if(e.key === 'f'){ fit(); }
    });
    // drop a node from the palette
    svg.addEventListener('dragover', e => {
      if(!e.dataTransfer.types.includes('application/x-wewos-node')) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
    });
    svg.addEventListener('drop', e => {
      const raw = e.dataTransfer.getData('application/x-wewos-node');
      if(!raw) return;
      e.preventDefault();
      const d = JSON.parse(raw);
      const [x, y] = toWorld(e.clientX, e.clientY);
      cb.edit('add', {net: NET.id, lib: d.lib, label: d.label, pos: [Math.round(x - DROP[0]), Math.round(y - DROP[1])]});
    });
  }

  /* ------------------------------------------------------------ a palette node being dragged */
  // The node is drawn under the cursor (the browser's own drag picture is
  // hidden), at the network's zoom and where it will land: dimmed away from
  // the network, solid with a dashed outline over it. Until the server has
  // described its ports (app.js asks when the mouse goes down on the palette
  // entry) it is an outline with its name.
  const DROP = [20, 10];                     // the dropped node's corner, up-left of the cursor
  const NOIMG = new Image();
  NOIMG.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  let GHOST = null;                          // {layer, g, d}
  function ghostStart(d, ev){
    ghostEnd();
    try { ev.dataTransfer.setDragImage(NOIMG, 0, 0); } catch(e) {}
    const layer = S('svg', {id: 'dragghost'}), g = S('g');
    layer.append(g);
    document.body.append(layer);
    GHOST = {layer, g, d};
    ghostDraw();
    ghostMove(ev.clientX, ev.clientY, false);
    document.addEventListener('dragover', ghostOver, true);
    document.addEventListener('dragleave', ghostLeave, true);
    document.addEventListener('drop', ghostEnd, true);
    document.addEventListener('dragend', ghostEnd, true);
  }
  function ghostInfo(d, info){
    if(GHOST && GHOST.d === d){ d.info = info; ghostDraw(); }
  }
  function ghostDraw(){
    const d = GHOST.d, info = d.info || {in: [], out: []};
    const n = Object.assign({}, info, {label: info.label || d.label, color: info.color || d.color});
    const el = nodeShape(n, layout(n), true);
    el.classList.add('ghost');
    if(!d.info) el.classList.add('pending');
    GHOST.g.replaceChildren(el);
  }
  function ghostMove(x, y, over){
    const k = view.k;
    GHOST.g.setAttribute('transform', `translate(${x - DROP[0] * k},${y - DROP[1] * k}) scale(${k})`);
    GHOST.layer.classList.toggle('over', over);
    GHOST.layer.style.display = '';
  }
  function ghostOver(e){
    if(GHOST) ghostMove(e.clientX, e.clientY, svg.contains(e.target) && !!NET);
  }
  function ghostLeave(e){
    // out of the window: hide it until the drag comes back
    if(GHOST && !e.relatedTarget && (e.clientX <= 0 || e.clientY <= 0 ||
                                     e.clientX >= innerWidth || e.clientY >= innerHeight))
      GHOST.layer.style.display = 'none';
  }
  function ghostEnd(){
    if(!GHOST) return;
    GHOST.layer.remove(); GHOST = null;
    document.removeEventListener('dragover', ghostOver, true);
    document.removeEventListener('dragleave', ghostLeave, true);
    document.removeEventListener('drop', ghostEnd, true);
    document.removeEventListener('dragend', ghostEnd, true);
  }
  function markTargets(nid, io, info){
    svg.querySelectorAll('.port').forEach(p => {
      if(p.dataset.node === nid || p.dataset.io === io){ p.classList.add('no'); return; }
      const other = portInfo(p.dataset.node, p.dataset.io, p.dataset.port);
      const special = p.dataset.port === 'runNode' || p.dataset.port === 'trigger' || info.special;
      if(special){
        if((p.dataset.port === 'runNode' || p.dataset.port === 'trigger') && info.special) p.classList.add('ok');
        else p.classList.add('no');
        return;
      }
      const ot = io === 'out' ? info.datatype : other.datatype, it = io === 'out' ? other.datatype : info.datatype;
      const inPort = io === 'out' ? other : info, inNode = io === 'out' ? p.dataset.node : nid;
      if(inPort.single === true && hasParent(inNode, inPort.name)) p.classList.add('no');
      else p.classList.add(compatible(ot, it) ? 'ok' : 'no');
    });
  }
  function clearTargets(){ svg.querySelectorAll('.port.ok,.port.no').forEach(p => p.classList.remove('ok', 'no')); }

  return {shortNames, widgetW, init, setTypes, show, current, updateNode, statusOnly, progress, moveNode, removeNode,
          addConn, removeConn, drawConn, selection, select, fit, center, ghostStart, ghostInfo, ghostEnd};
})();
