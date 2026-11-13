/* Author: Michel Sanner, PhD. Copyright (c) 2026. Conventions (token in the URL,
   api() wrapper, theme switch) from ADapt / ADCP_docking (BSD 3-Clause). */
/* The page: palette, network tabs, parameter panel, menus, and the loop that
   keeps the drawing in step with the server. The server holds the network;
   every user action is a request (api/edit, api/run...) and every change comes
   back as an event from api/events, including changes made while a network
   runs. */
'use strict';
const T = new URLSearchParams(location.search).get('t') || '';
const $ = i => document.getElementById(i);
const esc = W.esc;

const ST = {
  sid: null, name: '', folder: '', seq: 0, gen: 0, exec: 'waiting', auto: true,
  nets: {},              // netid -> {id, name, nodes:{}, conns:{}, macroNode, parent}
  tabs: ['main'], cur: 'main',
  sessions: [],          // the open networks (api/sessions), for their tabs
  opening: 0,            // a network is being opened: the one on screen may close as unused
  libs: [], types: {}, sel: [], errors: {},
  iso: null,             // isolation settings of the server (api/settings)
  isolation: null,       // how the current network is isolated
};

/* ------------------------------------------------------------ api */
async function api(path, body, raw){
  const url = path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(T);
  const opt = raw !== undefined && raw !== null ? {method: 'POST', body: raw}
            : body ? {method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify(body)} : {};
  try {
    const r = await fetch(url, opt);
    let d;
    try { d = await r.json(); }
    catch(e){ d = {error: 'the server did not answer with JSON (' + r.status + ')'}; }
    if(d.error){ status('<span class=bad>' + esc(d.error) + '</span>'); if(d.trace) logText(d.trace + '\n'); }
    return d;
  } catch(e){
    status('<span class=bad>the server did not answer: ' + esc(e) + '</span>');
    return {error: String(e), offline: true};
  }
}
function status(html){ $('status').innerHTML = html || '&nbsp;'; }
function logText(t){
  const pre = $('log');
  pre.textContent += t;
  if(pre.textContent.length > 400000) pre.textContent = pre.textContent.slice(-300000);
  pre.scrollTop = pre.scrollHeight;
  $('loglen').textContent = '(' + pre.textContent.split('\n').length + ' lines)';
}
const edit = (op, args) => api('api/edit', Object.assign({s: ST.sid, op}, args || {}));
const run = (mode, extra) => api('api/run', Object.assign({s: ST.sid, mode, net: ST.cur}, extra || {}));

/* ------------------------------------------------------------ store */
function netOf(id){ return ST.nets[id] || (ST.nets[id] = {id, name: id, nodes: {}, conns: {}}); }
function addNetwork(d){
  const n = netOf(d.id);
  n.name = d.name; n.macroNode = d.macroNode; n.parent = d.parent;
  n.nodes = {}; n.conns = {};
  (d.nodes || []).forEach(x => { n.nodes[x.id] = x; });
  (d.connections || []).forEach(c => { n.conns[c.id] = c; });
}
function findNode(id){
  for(const k in ST.nets) if(ST.nets[k].nodes[id]) return [ST.nets[k], ST.nets[k].nodes[id]];
  return [null, null];
}
async function loadSession(sid){
  const d = await api('api/session?s=' + encodeURIComponent(sid));
  if(d.error) return false;
  ST.gen++;
  ST.sid = d.session; ST.name = d.name; ST.folder = d.folder; ST.seq = d.seq;
  ST.isolation = d.isolation || {level: 'unrestricted', internet: true};
  showIsolation();
  ST.nets = {}; ST.errors = {};
  Object.values(d.networks).forEach(addNetwork);
  const q = new URLSearchParams(location.search);
  // the macro tabs this network had open when the page last showed it, and the one in
  // front; the tab in the address (a reload) belongs to the network it was opened in
  const kept = recallTabs(d.session) || {};
  ST.tabs = ['main'].concat((kept.tabs || []).filter(t => t !== 'main' && ST.nets[t]));
  ST.cur = ST.tabs.includes(kept.cur) ? kept.cur : 'main';
  const tab = q.get('session') === d.session ? q.get('tab') : null;
  if(tab && ST.nets[tab]){ if(!ST.tabs.includes(tab)) ST.tabs.push(tab); ST.cur = tab; }
  if(ST.cur === 'main') q.delete('tab'); else q.set('tab', ST.cur);
  setExec(d.execStatus); setAuto(d.runOnNewData);
  // opening a network loads the libraries it uses: show them in the palette
  const have = (ST.libs || []).map(l => l.name).sort().join('|');
  if(d.libraries && d.libraries.join('|') !== have) await loadLibraries();
  q.set('session', ST.sid);
  history.replaceState(null, '', '?' + q.toString());
  VIEW3D.reset();
  drawTabs(); ED.show(ST.nets[ST.cur]); ED.fit(); panel();
  document.title = ST.name + ' · WEWoS';
  refreshSessions();
  poll(ST.gen);
  VIEW3D.requestAll(ST.nets);
  if(d.report && d.report.length){ reportDialog('Opened with problems', d.report); }
  return true;
}

/* ------------------------------------------------------------ events */
async function poll(gen){
  while(gen === ST.gen){
    const d = await api('api/events?s=' + encodeURIComponent(ST.sid) + '&since=' + ST.seq + '&timeout=25');
    if(gen !== ST.gen) return;
    if(d.error){
      if(/no such network/.test(d.error)){ if(gen === ST.gen && !ST.opening) refreshSessions(); return; }
      await new Promise(r => setTimeout(r, 2000));
      continue;
    }
    if(d.reset){ loadSession(ST.sid); return; }
    applyEvents(d.events || []);
    ST.seq = Math.max(ST.seq, d.seq || 0);
  }
}
function applyEvents(evs){
  const dirty = new Set(), stat = new Set();
  let refreshPanel = false, reshow = false;
  for(const e of evs){
    if(e.seq <= ST.seq) continue;
    ST.seq = e.seq;
    const net = e.net ? netOf(e.net) : null;
    switch(e.kind){
      case 'node_added':
        net.nodes[e.node.id] = e.node;
        if(e.node.macro) netOf(e.node.id).parent = e.net;
        dirty.add(e.node.id); break;
      case 'node_deleted': {
        delete net.nodes[e.node];
        for(const cid in net.conns){ const c = net.conns[cid];
          if(c.from[0] === e.node || c.to[0] === e.node){ delete net.conns[cid]; if(e.net === ST.cur) ED.removeConn(cid); } }
        if(ST.nets[e.node]){ delete ST.nets[e.node]; closeTab(e.node); }
        if(e.net === ST.cur) ED.removeNode(e.node);
        VIEW3D.removeViewer(e.node);
        if(ST.sel.includes(e.node)) { ST.sel = ST.sel.filter(x => x !== e.node); refreshPanel = true; }
        break; }
      case 'node_moved': { const [, n] = findNode(e.node); if(n){ n.pos = e.pos; if(e.net === ST.cur) ED.moveNode(e.node); } break; }
      case 'node_renamed': { const [, n] = findNode(e.node); if(n){ n.name = e.name; dirty.add(e.node);
        if(ST.nets[e.node]) { ST.nets[e.node].name = e.name; drawTabs(); } } break; }
      case 'node_status': { const [, n] = findNode(e.node); if(n){ n.status = e.status;
        if(e.status === 'error'){ ST.errors[e.node] = e; status_err(n, e); }
        else if(e.status === 'running') delete ST.errors[e.node];
        n.time = e.time; stat.add(e.node); if(ST.sel.includes(e.node)) refreshPanel = true; } break; }
      case 'node_label': { const [, n] = findNode(e.node); if(n){ n.label = e.label; dirty.add(e.node); } break; }
      case 'node_frozen': { const [, n] = findNode(e.node); if(n){ n.frozen = e.frozen; stat.add(e.node); } break; }
      case 'node_code': { const [, n] = findNode(e.node); if(n){ n.codeModified = e.modified; dirty.add(e.node); } break; }
      case 'progress': { const [, n] = findNode(e.node); if(n){ n.progress = e.value; if(e.net === ST.cur) ED.progress(e.node, e.value); } break; }
      case 'ports': { const [, n] = findNode(e.node); if(n){ n.in = e.ports.in; n.out = e.ports.out; dirty.add(e.node);
        if(ST.sel.includes(e.node)) refreshPanel = true; } break; }
      case 'port_type': { const [, n] = findNode(e.node); if(n){
        const p = (e.io === 'in' ? n.in : n.out).find(x => x.name === e.port); if(p) p.datatype = e.datatype; dirty.add(e.node); } break; }
      case 'widget': { const [, n] = findNode(e.node); if(n){
        const p = n.in.find(x => x.name === e.port);
        if(p){ p.widget = e.widget; if(!e.widget) p.unbound = true; else p.unbound = false; }
        dirty.add(e.node);
        if(ST.sel.includes(e.node) || (e.net && ST.sel.includes(e.net))) refreshPanel = true; } break; }
      case 'connected':
        net.conns[e.conn.id] = e.conn;
        if(e.net === ST.cur) ED.addConn(e.conn);
        break;
      case 'disconnected':
        if(net){ delete net.conns[e.conn]; if(e.net === ST.cur) ED.removeConn(e.conn); }
        break;
      case 'exec_status': setExec(e.status); break;
      case 'run_on_new_data': setAuto(e.value); break;
      case 'log': logText(e.text); if(/ERROR|Traceback|Error/.test(e.text)) $('logbox').open = true; break;
      case 'saved': status('saved ' + esc(e.file)); break;
      case 'network_added': addNetwork(e.network); break;
      case 'network_renamed': ST.name = e.name; document.title = e.name + ' · WEWoS'; drawTabs(); refreshSessions(); break;
      case 'scene': VIEW3D.apply(e); break;
      case 'viewer': VIEW3D.viewerEvent(e); break;
      case 'image': VIEW3D.imageEvent(e); break;
      case 'snapshot_request': VIEW3D.snapshot(e); break;
      case 'message': reportDialog(e.title || 'Message', [e.text]); break;
    }
  }
  const cur = ST.nets[ST.cur];
  if(reshow){ ED.show(cur); }
  dirty.forEach(id => { if(cur && cur.nodes[id]) ED.updateNode(id); });
  stat.forEach(id => { if(cur && cur.nodes[id] && !dirty.has(id)) ED.statusOnly(id); });
  if(refreshPanel) panelSoon();
}
let panelTimer = null;
function panelSoon(){
  // redraw the parameter panel, but not while its user is dragging, scrolling
  // or typing in it
  clearTimeout(panelTimer);
  const a = document.activeElement;
  const typing = a && $('panel').contains(a) &&
    (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && /^(text|number|search)$/.test(a.type)));
  if(W.isBusy() || typing) panelTimer = setTimeout(panelSoon, 300);
  else panel();
}
function status_err(n, e){
  status('<span class=bad>node ' + esc(n.name) + ' failed: ' + esc(e.error) + '</span>');
}
function setExec(s){
  ST.exec = s;
  const p = $('execstatus');
  p.textContent = s === 'waiting' ? 'idle' : s;
  p.className = 'pill ' + s;
  $('b_pause').innerHTML = s === 'pause' ? '&#9654; resume' : '&#10073;&#10073;';
}
function setAuto(v){ ST.auto = !!v; $('b_auto').checked = ST.auto; }

/* ------------------------------------------------------------ palette */
async function loadLibraries(){
  const d = await api('api/libraries');
  if(d.error) return;
  applyCatalog(d);
}
function applyCatalog(d){
  ST.libs = d.libraries; ST.types = d.types; ST.known = d.known || [];
  for(const k in NODEINFO) delete NODEINFO[k];
  ED.setTypes(d.types);
  drawPalette($('search').value);
  // redraw the current network: ports of newly known types get their colors
  if(ST.sid && ST.nets[ST.cur]) ED.show(ST.nets[ST.cur]);
}

/* Libraries are loaded on demand, as in Vision: only Standard (and those
   marked "load at start") are in the palette when the server starts;
   opening a network loads the libraries it uses. */
async function librariesDialog(){
  const d = await api('api/libraries');
  if(d.error) return;
  applyCatalog(d);
  const box = document.createElement('div');
  const rows = d.known.map(k =>
    '<tr><td><b>' + esc(k.name) + '</b><div class=dim style="font-size:11px">' +
      esc(k.doc || (k.source && (k.source.module || k.source.file)) || '') + '</div>' +
      (k.error ? '<div class=bad style="font-size:11px">' + esc(k.error) + '</div>' : '') + '</td>' +
    '<td>' + (k.loaded ? '<span class=good>loaded</span> <span class=dim>' + (k.nodes || 0) + ' nodes</span>'
                       : '<button data-load="' + esc(k.name) + '">Load</button>') + '</td>' +
    '<td><label class=chk title="load it when the server starts"><input type=checkbox data-start="' + esc(k.name) + '"' +
      (k.startup || k.name === 'Standard' ? ' checked' : '') + (k.name === 'Standard' ? ' disabled' : '') +
      '> at start</label></td></tr>').join('');
  box.innerHTML = '<table class=libtable>' + rows + '</table>' +
    '<h4 style="margin:14px 0 4px">Load a library of your own</h4>' +
    '<p class=dim style="margin:0 0 6px">A Python module (e.g. <code>mypackage.mynodes</code>) or a <code>.py</code> file on the server ' +
    'that creates a <code>NodeLibrary</code> (<code>from wewos.engine import NodeLibrary, NetworkNode</code>). ' +
    'It is remembered for the next sessions.</p>' +
    '<div style="display:flex;gap:6px"><input id=lib_src style="flex:1" placeholder="module name or /path/to/file.py" spellcheck=false>' +
    '<button id=lib_browse>&hellip;</button><button id=lib_load class=primary>Load</button></div><p id=lib_err class=bad></p>';
  modal('Libraries', box);
  const after = r => { if(!r.error){ applyCatalog(r); librariesDialog(); } else box.querySelector('#lib_err').textContent = r.error; };
  box.querySelectorAll('button[data-load]').forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = 'loading\u2026';
    after(await api('api/library', {name: b.dataset.load}));
  });
  box.querySelectorAll('input[data-start]').forEach(c => c.onchange = async () => {
    const r = await api('api/library_startup', {name: c.dataset.start, on: c.checked});
    if(!r.error) applyCatalog(r);
  });
  box.querySelector('#lib_browse').onclick = async () => {
    const p = await filePicker('file', '', {title: 'A library file (.py)'});
    if(p){ const r = await api('api/library', {file: p});
           if(r.error) reportDialog('Library not loaded', [r.error]); else { applyCatalog(r); librariesDialog(); } }
  };
  box.querySelector('#lib_load').onclick = async () => {
    const v = box.querySelector('#lib_src').value.trim();
    if(!v) return;
    const isFile = v.includes('/') || v.endsWith('.py');
    after(await api('api/library', isFile ? {file: v} : {module: v}));
  };
}
$('m_libs').onclick = e => { e.stopPropagation(); librariesDialog(); };
// how a palette node looks (its ports), asked once when the mouse goes down
// on it, for the picture dragged to the network
const NODEINFO = {};
function nodeInfo(lib, label){
  const k = lib + '\n' + label;
  if(!NODEINFO[k]){
    const q = 'api/nodeinfo?lib=' + encodeURIComponent(lib) + '&label=' + encodeURIComponent(label) + '&t=' + encodeURIComponent(T);
    const forget = () => { delete NODEINFO[k]; return null; };
    NODEINFO[k] = fetch(q).then(r => r.json()).then(d => d.error ? forget() : d, forget);
  }
  return NODEINFO[k];
}
const OPENCATS = new Set((() => { try { return JSON.parse(localStorage.getItem('wewos.cats') || '["Standard/Input"]'); } catch(e) { return []; } })());
function saveCats(){ try { localStorage.setItem('wewos.cats', JSON.stringify([...OPENCATS])); } catch(e) {} }
function drawPalette(q){
  q = (q || '').toLowerCase();
  const box = $('libs'); box.innerHTML = '';
  ST.libs.forEach(lib => {
    const det = document.createElement('details');
    det.className = 'lib'; det.open = true;
    det.innerHTML = '<summary><span class=swatch style="background:' + esc(lib.color) + '"></span>' + esc(lib.name) + '</summary>';
    if(lib.error){ det.innerHTML += '<div class=liberr>not available: ' + esc(lib.error) + '</div>'; box.append(det); return; }
    let any = false;
    lib.categories.forEach(cat => {
      // a node matches by its name or its category's, or (from 3 letters on)
      // by its documentation, which is then marked on its entry
      const nodes = cat.nodes.filter(n => {
        n._inDoc = false;
        if(!q || n.label.toLowerCase().includes(q) || cat.name.toLowerCase().includes(q)) return true;
        n._inDoc = q.length >= 3 && (n.fullDoc || n.doc || '').toLowerCase().includes(q);
        return n._inDoc;
      });
      if(!nodes.length) return;
      any = true;
      const c = document.createElement('details'); c.className = 'cat';
      const key = lib.name + '/' + cat.name;
      c.open = !!q || OPENCATS.has(key);
      c.innerHTML = '<summary class=cname>' + esc(cat.name) + ' <span class=dim>' + nodes.length + '</span></summary>';
      c.addEventListener('toggle', () => { if(!q){ if(c.open) OPENCATS.add(key); else OPENCATS.delete(key); saveCats(); } });
      nodes.forEach(n => {
        const e = document.createElement('div');
        e.className = 'pnode'; e.textContent = n.label; e.title = n.doc || n.cls;
        if(n._inDoc) e.insertAdjacentHTML('beforeend', ' <span class=doctag title="found in its documentation">doc</span>');
        e.draggable = true;
        e.addEventListener('mousedown', () => nodeInfo(lib.name, n.label));
        e.addEventListener('dragstart', ev => {
          ev.dataTransfer.setData('application/x-wewos-node', JSON.stringify({lib: lib.name, label: n.label}));
          ev.dataTransfer.effectAllowed = 'copy';
          const d = {lib: lib.name, label: n.label, color: lib.color};
          ED.ghostStart(d, ev);
          nodeInfo(lib.name, n.label).then(info => { if(info) ED.ghostInfo(d, info); });
        });
        e.addEventListener('dblclick', () => {
          const [x, y] = ED.center();
          edit('add', {net: ST.cur, lib: lib.name, label: n.label, pos: [Math.round(x), Math.round(y)]});
        });
        c.append(e);
      });
      det.append(c);
    });
    if(any || !q) box.append(det);
  });
  const more = document.createElement('div');
  more.innerHTML = '<button class=plainbtn style="margin:8px 4px;color:var(--accent)">+ Load a library&hellip;</button>';
  more.firstChild.onclick = librariesDialog;
  box.append(more);
}
$('search').addEventListener('input', e => drawPalette(e.target.value));

/* ------------------------------------------------------------ tabs */
// One tab per open network, in the order they were opened, as in Vision. The
// network on screen has a full tab, followed by the tabs of its open macros;
// the others have thin tabs that switch to them.
// Each network's open macro tabs, kept for this browser tab (sessionStorage), so that
// switching to another network and back, or reloading, finds them again.
function rememberTabs(){
  if(!ST.sid) return;
  try { sessionStorage.setItem('wewos.tabs.' + ST.sid, JSON.stringify({tabs: ST.tabs, cur: ST.cur})); } catch(e) {}
}
function recallTabs(sid){
  try { return JSON.parse(sessionStorage.getItem('wewos.tabs.' + sid) || 'null'); } catch(e) { return null; }
}
function drawTabs(){
  const nav = $('tabs'); nav.innerHTML = '';
  ST.tabs = ST.tabs.filter(t => ST.nets[t]);
  rememberTabs();
  // 'created' is an ISO time; the server lists networks opened in the same second
  // oldest first, and a stable sort keeps that
  const nets = (ST.sessions || []).slice().sort((a, b) => a.created < b.created ? -1 : a.created > b.created ? 1 : 0);
  if(!nets.some(x => x.session === ST.sid)) nets.push({session: ST.sid});
  nets.forEach(x => {
    if(x.session === ST.sid){ nav.append(currentTabs()); return; }
    const lv = (x.isolation || {}).level;
    const b = document.createElement('button');
    b.className = 'tab thin' + (x.status === 'stopped' ? ' stopped' : '');
    b.innerHTML = (lv === 'sandboxed' || lv === 'readonly' ? '<span class=ic>&#128737;</span>' : '') +
                  '<span class=nm>' + esc(x.name) + '</span><span class=x title="close this network">&#10005;</span>';
    b.title = x.name + ' (' + x.nodes + ' nodes' + (lv ? ', ' + lv : '') +
              (x.status === 'stopped' ? ', stopped' : '') + '): click to show it';
    b.onclick = e => {
      if(e.target.classList.contains('x')){ closeNetwork(x.session); return; }
      loadSession(x.session);
    };
    nav.append(b);
  });
  const on = nav.querySelector('.tab.on');
  if(on) on.scrollIntoView({block: 'nearest', inline: 'nearest'});
}
function currentTabs(){
  const g = document.createElement('span');
  g.className = 'tabgroup';
  ST.tabs.forEach(id => {
    const b = document.createElement('button');
    b.className = 'tab' + (id === ST.cur ? ' on' : '');
    const n = id === 'main' ? null : findNode(id)[1];
    b.innerHTML = esc(id === 'main' ? (ST.name || 'network') : ('▣ ' + (n ? n.name : id))) +
                  ' <span class=x title="' + (id === 'main' ? 'close this network' : 'close this tab') +
                  '">&#10005;</span>';
    b.addEventListener('click', e => {
      if(e.target.classList.contains('x')){ if(id === 'main') closeNetwork(ST.sid); else closeTab(id); return; }
      switchTab(id);
    });
    g.append(b);
  });
  return g;
}
function switchTab(id){
  if(!ST.nets[id]) return;
  if(!ST.tabs.includes(id)) ST.tabs.push(id);
  ST.cur = id;
  const q = new URLSearchParams(location.search);
  if(id === 'main') q.delete('tab'); else q.set('tab', id);
  history.replaceState(null, '', '?' + q.toString());
  drawTabs(); ED.show(ST.nets[id]);
  if(!Object.keys(ST.nets[id].nodes).length) ED.fit();
}
function closeTab(id){
  ST.tabs = ST.tabs.filter(t => t !== id);
  if(ST.cur === id) switchTab('main'); else drawTabs();
}
// Close an open network on the server. Its folder stays on disk with a last autosave,
// so File > Open brings it back. Closing the one on screen shows its neighbour in the
// tabs, or a new empty network when it was the last.
async function closeNetwork(sid){
  sid = sid || ST.sid;
  const nets = (ST.sessions || []).slice().sort((a, b) => a.created < b.created ? -1 : a.created > b.created ? 1 : 0);
  const i = nets.findIndex(x => x.session === sid);
  const x = nets[i] || {};
  const name = sid === ST.sid ? ST.name : (x.name || 'this network');
  const nodes = sid === ST.sid ? Object.keys((ST.nets.main || {nodes: {}}).nodes).length : (x.nodes || 0);
  if(nodes && !confirm('Close ' + name + '?\n\nIts folder stays on disk with its last autosave, ' +
                       'so File > Open can bring it back.')) return;
  if(sid === ST.sid) ST.gen++;          // stop following it: it is about to go
  const d = await api('api/close', {s: sid});
  if(d.error){ if(sid === ST.sid) poll(ST.gen); return; }
  status('closed ' + esc(name) + (nodes ? '; its folder is kept: ' + esc(d.folder) : ''));
  try { sessionStorage.removeItem('wewos.tabs.' + sid); } catch(e) {}
  if(sid !== ST.sid){ refreshSessions(); return; }
  const next = nets[i + 1] || nets[i - 1];
  if(next && await loadSession(next.session)) return;
  await showAnotherNetwork();
}
// The network on screen is gone (closed here or from another page, or the server
// restarted): show another open one, or a new empty one.
async function showAnotherNetwork(){
  const d = await api('api/sessions');
  const left = (!d.error && d.sessions) || [];
  if(left.length && await loadSession(left[0].session)) return;
  const n = await api('api/new', {name: 'network'});
  if(!n.error) loadSession(n.session);
}

/* ------------------------------------------------------------ parameter panel */
function widgetCtx(nid, port, compact){
  return {
    compact,
    key: nid + ':' + port,
    colormapFile: (action, path, colorMap) => edit('colormap_file', {action, path, colorMap}),
    change: (value, runIt) => edit('set_widget', {node: nid, port, value, run: runIt && ST.auto}),
    pickFile: (kind, cur, opts) => filePicker(kind, cur, Object.assign({relative: true}, opts)),
    upload: () => uploadFile(),
  };
}
function panel(){
  const box = $('panel');
  const ids = ED.selection().nodes;
  ST.sel = ids;
  if(ids.length !== 1){
    box.innerHTML = ids.length ? '<p class=dim>' + ids.length + ' nodes selected.</p>' +
      '<div class=btns><button id=p_group>Group into a macro</button><button id=p_del>Delete</button></div>'
      : '<p class=dim>Select a node to see its parameters.</p>';
    if(ids.length){
      $('p_group').onclick = () => groupMacro(ids);
      $('p_del').onclick = () => edit('delete', {nodes: ids});
    }
    return;
  }
  const [, n] = findNode(ids[0]);
  if(!n){ box.innerHTML = ''; return; }
  const h = [];
  h.push('<h3><input id=p_name value="' + esc(n.name) + '" title="rename"></h3>');
  h.push('<div class=dim>' + esc(n.lib || 'built-in') + ' &middot; ' + esc(n.cls) +
         (n.time != null ? ' &middot; last run ' + (n.time * 1000).toFixed(0) + ' ms' : '') + '</div>');
  if(n.unsupported) h.push('<p class=bad>This node is not available here (' + esc(JSON.stringify(n.unsupported)) + '); it does not run.</p>');
  const err = ST.errors[n.id];
  if(err && n.status === 'error') h.push('<p class=bad>' + esc(err.error) + '</p><details><summary>traceback</summary><div class=err>' + esc(err.trace) + '</div></details>');
  if(n.doc) h.push('<details><summary class=dim>About this node</summary><div class=doc>' + esc(n.doc) + '</div></details>');
  h.push('<div id=p_widgets></div>');
  h.push('<div class=btns><button id=p_run class=primary>Run node</button><button id=p_code>Edit code&hellip;</button>' +
         '<button id=p_freeze>' + (n.frozen ? 'Unfreeze' : 'Freeze') + '</button>' +
         (n.macro ? '<button id=p_open>Open macro</button><button id=p_explode>Explode macro</button>' : '') +
         '<button id=p_del>Delete</button></div>');
  h.push('<table id=p_ports></table>');
  if(!n.macro && !n.unsupported && !n.readOnly)
    h.push('<details id=p_addport><summary class=dim>Add a port</summary><div class=row style="grid-template-columns:auto 1fr auto auto">' +
      '<select id=ap_io><option value=in>input</option><option value=out>output</option></select>' +
      '<input id=ap_name placeholder="name" spellcheck=false>' +
      '<select id=ap_type>' + ['None', 'float', 'int', 'boolean', 'string', 'list', 'dict', 'coord3(0)', 'geom', 'AtomSet', 'Molecule']
        .map(t => '<option>' + t + '</option>').join('') + '</select>' +
      '<label class=chk title="give the input a widget"><input type=checkbox id=ap_w> widget</label></div>' +
      '<button id=ap_go>Add port</button> <span class=dim>The compute function gets one more argument.</span></details>');
  box.innerHTML = h.join('');
  const wbox = $('p_widgets');
  (n.in || []).forEach(p => {
    if(!p.widget) return;
    const row = document.createElement('div'); row.className = 'row';
    const lab = document.createElement('label');
    lab.textContent = p.widget.label || p.name; lab.title = p.name + ': ' + p.datatype + (p.widget.master === 'node' ? ' (also shown in the node)' : '');
    if(p.widget.kind === 'colormap') row.classList.add('wide');      // the editor takes the row
    row.append(lab, W.render(p.widget, widgetCtx(n.id, p.name, false)));
    lab.addEventListener('contextmenu', ev => { ev.preventDefault(); widgetMenu(n, p, ev); });
    wbox.append(row);
  });
  if(n.macro && ST.nets[n.id]){
    // widgets inside the macro that were put in the macro's panel
    Object.values(ST.nets[n.id].nodes).forEach(inner => (inner.in || []).forEach(p => {
      if(!p.widget || p.widget.master !== 'macroParamPanel') return;
      const row = document.createElement('div'); row.className = 'row';
      const lab = document.createElement('label');
      lab.textContent = p.widget.label || p.name;
      lab.title = inner.name + ' . ' + p.name + ' (inside the macro)';
      row.append(lab, W.render(p.widget, widgetCtx(inner.id, p.name, false)));
      wbox.append(row);
    }));
  }
  const t = $('p_ports');
  const rows = [];
  (n.in || []).forEach(p => rows.push('<tr><td>&#9664; ' + esc(p.name) + '</td><td class=t>' + esc(p.datatype) +
      (p.required ? '' : ' (opt.)') + '</td><td>' + (p.widget ? '<button data-unbind="' + esc(p.name) + '" class=plainbtn title="remove the widget so the port can be connected">unbind</button>'
      : (p.unbound ? '<button data-rebind="' + esc(p.name) + '" class=plainbtn>rebind widget</button>' : '')) +
      '<button data-show="in:' + esc(p.name) + '" class=plainbtn>data</button>' +
      (n.macro ? '' : '<button data-del="in:' + esc(p.name) + '" class=plainbtn title="delete this port">&#10005;</button>') + '</td></tr>'));
  (n.out || []).forEach(p => rows.push('<tr><td>' + esc(p.name) + ' &#9654;</td><td class=t>' + esc(p.datatype) +
      '</td><td><button data-show="out:' + esc(p.name) + '" class=plainbtn>data</button>' +
      (n.macro ? '' : '<button data-del="out:' + esc(p.name) + '" class=plainbtn title="delete this port">&#10005;</button>') + '</td></tr>'));
  t.innerHTML = rows.join('');
  t.onclick = e => {
    const b = e.target.closest('button'); if(!b) return;
    if(b.dataset.show){ const [io, port] = b.dataset.show.split(':'); showData(n.id, io, port); }
    if(b.dataset.unbind) edit('unbind', {node: n.id, port: b.dataset.unbind});
    if(b.dataset.rebind) edit('rebind', {node: n.id, port: b.dataset.rebind});
    if(b.dataset.del){ const [io, port] = b.dataset.del.split(':');
      if(confirm('Delete port ' + port + ' of ' + n.name + '?')) edit('delete_port', {node: n.id, io, port}); }
  };
  if($('ap_go')) $('ap_go').onclick = () => edit('add_port', {node: n.id, io: $('ap_io').value,
      name: $('ap_name').value.trim(), datatype: $('ap_type').value, widget: $('ap_w').checked});
  $('p_name').addEventListener('change', e => edit('rename', {node: n.id, name: e.target.value}));
  $('p_run').onclick = () => run('run_node', {node: n.id});
  $('p_code').onclick = () => codeEditor(n.id);
  $('p_freeze').onclick = () => edit('freeze', {node: n.id, frozen: !n.frozen});
  $('p_del').onclick = () => edit('delete', {nodes: [n.id]});
  if($('p_open')) $('p_open').onclick = () => switchTab(n.id);
  if($('p_explode')) $('p_explode').onclick = () => explodeMacro(n.id);
}
function widgetMenuItems(n, p){
  return [
    ['Show in the node', () => edit('widget_opts', {node: n.id, port: p.name, opts: {master: 'node'}}), p.widget.master === 'node'],
    ['Show in the panel only', () => edit('widget_opts', {node: n.id, port: p.name, opts: {master: 'ParamPanel'}}), p.widget.master !== 'node'],
    ['Unbind (show the port)', () => edit('unbind', {node: n.id, port: p.name}), p.widget.locked],
  ].concat(p.widget.kind === 'number' ? [['Options\u2026', () => widgetOptions(n, p)]] : [])
   .concat(p.widget.master === 'node' ? ['-',
    ['Wider', () => widgetWidth(n, p, 1.3)],
    ['Narrower', () => widgetWidth(n, p, 1 / 1.3)],
    ['Automatic width', () => widgetWidth(n, p, null), !(p.widget.options || {}).nodeWidth]] : []);
}
// the width of a widget in its node, saved with the network (null: as its content needs)
function widgetWidth(n, p, factor){
  const w = factor == null ? null
    : Math.max(30, Math.min(400, Math.round(ED.widgetW(p.widget) * factor)));
  edit('widget_opts', {node: n.id, port: p.name, opts: {nodeWidth: w}});
}
// a number widget's options: Vision's option panel (min, max, step, one turn, precision)
function widgetOptions(n, p){
  const o = p.widget.options || {};
  const fields = [['min', 'minimum', 'none'], ['max', 'maximum', 'none'],
                  ['increment', 'step', '0: any value'], ['oneTurn', 'one turn', 'change for one turn of a dial']]
    .concat(o.type === 'int' ? [] : [['precision', 'digits shown', '']]);
  const box = document.createElement('div');
  box.innerHTML = '<p class=dim>The widget of <b>' + esc(n.name) + '</b>, input <b>' + esc(p.name) +
    '</b>. Leave the minimum or maximum empty for none.</p><table class=wopts>' +
    fields.map(([k, label, ph]) => '<tr><td>' + label + '</td><td><input data-k="' + k + '" value="' +
      (o[k] == null ? '' : esc(String(o[k]))) + '" placeholder="' + esc(ph) + '" spellcheck=false></td></tr>').join('') +
    '</table><p id=wo_err class=bad></p><div class=btns style="display:flex;gap:6px">' +
    '<button class=primary id=wo_ok>OK</button><button id=wo_cancel>Cancel</button></div>';
  modal('Widget options', box);
  box.querySelector('#wo_cancel').onclick = closeModal;
  box.querySelector('#wo_ok').onclick = async () => {
    const opts = {};
    for(const inp of box.querySelectorAll('input[data-k]')){
      const k = inp.dataset.k, t = inp.value.trim();
      if(t === ''){ if(k === 'min' || k === 'max') opts[k] = null; continue; }
      const v = Number(t);
      if(!isFinite(v)){ box.querySelector('#wo_err').textContent = 'not a number: ' + t; return; }
      opts[k] = v;
    }
    if(opts.min != null && opts.max != null && opts.min > opts.max){
      box.querySelector('#wo_err').textContent = 'the minimum is larger than the maximum'; return; }
    const d = await edit('widget_opts', {node: n.id, port: p.name, opts});
    if(!d.error) closeModal();
  };
}
function widgetMenu(n, p, ev){ menu(ev, widgetMenuItems(n, p)); }
// right-click on a widget shown in a node: its menu, then the node's
function nodeWidgetMenu(id, port, ev){
  const [, n] = findNode(id);
  const p = n && (n.in || []).find(x => x.name === port);
  if(!p || !p.widget) return nodeMenu(id, ev);
  menu(ev, widgetMenuItems(n, p).concat(['-'], nodeMenuItems(id)));
}

/* ------------------------------------------------------------ dialogs */
function modal(title, bodyEl){
  $('mtitle').textContent = title;
  const b = $('mbody'); b.innerHTML = '';
  if(typeof bodyEl === 'string') b.innerHTML = bodyEl; else b.append(bodyEl);
  $('modal').hidden = false;
}
function closeModal(){ $('modal').hidden = true; if(modalCancel){ const f = modalCancel; modalCancel = null; f(); } }
let modalCancel = null;
$('mclose').onclick = closeModal;
$('modal').addEventListener('pointerdown', e => { if(e.target === $('modal')) closeModal(); });
document.addEventListener('keydown', e => { if(e.key === 'Escape' && !$('modal').hidden) closeModal(); });

function reportDialog(title, lines){
  const ul = '<ul class=report>' + lines.map(l => '<li>' + esc(typeof l === 'string' ? l : JSON.stringify(l)) + '</li>').join('') + '</ul>';
  modal(title, ul);
}
async function showData(nid, io, port){
  const d = await edit('port_data', {node: nid, io, port});
  if(d.error) return;
  const pre = document.createElement('pre');
  pre.style.cssText = 'white-space:pre-wrap;font:12px ui-monospace,Menlo,monospace;max-height:65vh;overflow:auto';
  pre.textContent = d.text;
  modal(port + ' (' + d.type + ')', pre);
}
async function codeEditor(nid){
  const d = await edit('get_code', {node: nid});
  if(d.error) return;
  const box = document.createElement('div');
  box.innerHTML = '<p class=dim>The compute function of <b>' + esc(d.name) + '</b>. Its arguments are the input ports, in order; ' +
    'call <code>self.outputData(port=value)</code> to send data. ' + (d.readOnly ? '<span class=warn>This node is read only.</span>' : '') + '</p>' +
    '<textarea class=code spellcheck=false></textarea><p id=c_err class=bad></p>' +
    '<div class=btns style="display:flex;gap:6px"><button class=primary id=c_save>Save</button><button id=c_saverun>Save and run</button><button id=c_cancel>Cancel</button></div>';
  const ta = box.querySelector('textarea');
  ta.value = d.code || '';
  ta.addEventListener('keydown', e => {
    if(e.key === 'Tab'){ e.preventDefault();
      const s = ta.selectionStart; ta.setRangeText('    ', s, ta.selectionEnd, 'end'); }
  });
  modal('Edit code', box);
  const save = async runAfter => {
    const r = await edit('set_code', {node: nid, code: ta.value, force: true});
    if(r.error){ box.querySelector('#c_err').textContent = r.error; return; }
    closeModal();
    if(runAfter) run('run_node', {node: nid});
  };
  box.querySelector('#c_save').onclick = () => save(false);
  box.querySelector('#c_saverun').onclick = () => save(true);
  box.querySelector('#c_cancel').onclick = closeModal;
  setTimeout(() => ta.focus(), 30);
}
function filePicker(kind, current, opts){
  return new Promise(resolve => {
    let dir = current ? current.replace(/\/[^/]*$/, '') || current : '';
    let chosen = null;
    const box = document.createElement('div');
    box.innerHTML = '<div style="display:flex;gap:6px;align-items:center"><button id=f_up>&#8593;</button>' +
      '<button id=f_sess title="this network\'s folder">network folder</button><input id=f_dir style="flex:1"></div>' +
      '<div class=fb-list id=f_list></div>' +
      (kind === 'filesave' ? '<div style="display:flex;gap:6px;align-items:center">name <input id=f_name style="flex:1"></div>' : '') +
      '<div class=btns style="display:flex;gap:6px;margin-top:8px"><button class=primary id=f_ok>' +
      (kind === 'dir' ? 'Choose this folder' : 'Choose') + '</button><button id=f_cancel>Cancel</button><span class=grow></span>' +
      (kind === 'file' ? '<button id=f_upload>Upload from this computer&hellip;</button>' : '') + '</div>';
    modal(opts.title || (kind === 'dir' ? 'Choose a folder' : 'Choose a file'), box);
    modalCancel = () => resolve(null);
    let session = '';
    // a widget's file inside the network's folder is given relative to it,
    // as nodes read it (and as Vision networks kept their file names)
    const rel = v => (opts.relative && v && session && v.startsWith(session + '/')) ? v.slice(session.length + 1) : v;
    const done = v => { modalCancel = null; $('modal').hidden = true; resolve(rel(v)); };
    async function go(d){
      const r = await api('api/files?s=' + encodeURIComponent(ST.sid) + '&dir=' + encodeURIComponent(d || ''));
      if(r.error) return;
      dir = r.path; session = r.session;
      box.querySelector('#f_dir').value = dir;
      const list = box.querySelector('#f_list'); list.innerHTML = '';
      r.entries.forEach(en => {
        const it = document.createElement('div');
        it.innerHTML = (en.dir ? '&#128193; ' : '&#128196; ') + esc(en.name) + (en.dir ? '' : '<span class=sz>' + (en.size / 1024).toFixed(1) + ' kB</span>');
        it.onclick = () => { if(en.dir) go(dir + '/' + en.name); else {
          list.querySelectorAll('.sel').forEach(x => x.classList.remove('sel')); it.classList.add('sel');
          chosen = dir + '/' + en.name; if(box.querySelector('#f_name')) box.querySelector('#f_name').value = en.name; } };
        it.ondblclick = () => { if(!en.dir) done(dir + '/' + en.name); };
        list.append(it);
      });
    }
    box.querySelector('#f_up').onclick = () => go(dir.replace(/\/[^/]+$/, '') || '/');
    box.querySelector('#f_sess').onclick = () => go(session);
    box.querySelector('#f_dir').addEventListener('change', e => go(e.target.value));
    box.querySelector('#f_cancel').onclick = () => done(null);
    box.querySelector('#f_ok').onclick = () => {
      if(kind === 'dir') done(dir);
      else if(kind === 'filesave'){ const nm = box.querySelector('#f_name').value.trim(); done(nm ? dir + '/' + nm : null); }
      else done(chosen);
    };
    if(box.querySelector('#f_upload')) box.querySelector('#f_upload').onclick = async () => {
      const p = await uploadFile(); if(p) done(p); };
    go(dir);
  });
}
function uploadFile(){
  return new Promise(resolve => {
    const inp = $('fileupload');
    inp.value = '';
    inp.onchange = async () => {
      const f = inp.files[0]; if(!f){ resolve(null); return; }
      status('uploading ' + esc(f.name) + '&hellip;');
      const d = await api('api/upload?s=' + encodeURIComponent(ST.sid) + '&name=' + encodeURIComponent(f.name), null, f);
      if(d.error){ resolve(null); return; }
      status('uploaded ' + esc(d.name));
      resolve(d.path);
    };
    inp.click();
  });
}

/* ------------------------------------------------------------ isolation */
/* A network from someone else runs in its own sandboxed process
   (wewos/isolation.py). Opening a file asks how it should run; the badge in
   the toolbar shows how the current network runs. */
const ISO_TEXT = {
  sandboxed: ['Sandboxed', "Its code sees only this network's own folder (and the folders you add below). " +
                           'Your other files do not exist for it.'],
  readonly: ['Read-only', 'Its code can read every file you can, and write only in this network\'s folder.'],
  unrestricted: ['Unrestricted', 'Its code runs with your rights, like a program you start yourself. ' +
                                 'For networks you trust.'],
};
const ISO_RANK = {unrestricted: 0, readonly: 1, sandboxed: 2};
const isolated = () => !!ST.isolation && ST.isolation.level !== 'unrestricted';
async function loadIsoSettings(){
  const d = await api('api/settings');
  if(!d.error) ST.iso = d;
  return ST.iso;
}
function showIsolation(){
  const b = $('isolation'), iso = ST.isolation || {level: 'unrestricted'};
  // the canvas is tinted and framed for an isolated network (app.css)
  $('center').classList.toggle('iso-sandboxed', iso.level === 'sandboxed');
  $('center').classList.toggle('iso-readonly', iso.level === 'readonly');
  b.hidden = false;
  b.className = 'pill iso ' + iso.level;
  b.textContent = iso.level === 'unrestricted' ? '\u{1F513} unrestricted' :
                  '\u{1F6E1} ' + (iso.level === 'sandboxed' ? 'sandboxed' : 'read-only') +
                  (iso.internet ? ' \u00b7 internet' : '');
  b.title = ISO_TEXT[iso.level] ? ISO_TEXT[iso.level][1] + (iso.internet ? ' It may use the internet.' : ' No internet.') +
            ' Click to change.' : '';
}
// opts: {askBox: show "Don't ask me again", dontAsk: its state, askNote: a line (HTML) under it}
function isolationChooser(title, init, okLabel, intro, opts){
  opts = opts || {};
  return new Promise(resolve => {
    const minimum = (ST.iso && ST.iso.minimum) || 'unrestricted';
    const box = document.createElement('div');
    box.className = 'isodlg';
    box.innerHTML = (intro ? '<p>' + esc(intro) + '</p>' : '') +
      '<div class=isolevels>' + ['sandboxed', 'readonly', 'unrestricted'].map(l => {
        const here = !ST.iso || !ST.iso.available_levels || ST.iso.available_levels.includes(l);
        const off = ISO_RANK[l] < ISO_RANK[minimum] || !here;
        const why = !here ? ((ST.iso.level_notes || {})[l] || 'not available on this system')
                          : 'this server isolates every network at least as ' + minimum;
        return '<label' + (off ? ' class=off title="' + esc(why) + '"' : '') +
          '><input type=radio name=isolevel value=' + l + (off ? ' disabled' : '') + '><span><b>' + ISO_TEXT[l][0] +
          '</b><br><span class=what>' + esc(ISO_TEXT[l][1]) + '</span></span></label>';
      }).join('') + '</div>' +
      Object.entries((ST.iso && ST.iso.level_notes) || {}).map(([l, why]) =>
        '<p class="note dim">' + esc(ISO_TEXT[l] ? ISO_TEXT[l][0] : l) + ': ' + esc(why) + '.</p>').join('') +
      '<label class=chk><input type=checkbox id=iso_net> Allow internet access</label>' +
      '<div class="note warn" id=iso_warn hidden>With read-only access and the internet, the network could send ' +
      'any file you can read to another computer.</div>' +
      '<div id=iso_grants><div class=note>Also let it read these folders (one per line):</div>' +
      '<textarea id=iso_g spellcheck=false placeholder="/path/to/data"></textarea></div>' +
      '<p class="note dim">Fetch PDB works at every level: without internet access, WEWoS downloads the entry for the network.</p>' +
      (opts.askBox ? '<label class=chk><input type=checkbox id=iso_noask> Don\'t ask me again: open networks in this mode</label>' +
        (opts.askNote ? '<p class="note dim" id=iso_noask_note>' + opts.askNote + '</p>' : '') : '') +
      '<div class=btns style="display:flex;gap:6px"><button class=primary id=iso_ok>' + esc(okLabel) +
      '</button><button id=iso_cancel>Cancel</button></div>';
    modal(title, box);
    modalCancel = () => resolve(null);
    const radios = [...box.querySelectorAll('input[name=isolevel]')];
    let level = ISO_RANK[init.level] < ISO_RANK[minimum] ? minimum : (init.level || 'sandboxed');
    if(ST.iso && ST.iso.available_levels && !ST.iso.available_levels.includes(level)) level = 'sandboxed';
    radios.forEach(r => { r.checked = r.value === level; });
    const net = box.querySelector('#iso_net');
    net.checked = !!init.internet && init.level !== 'unrestricted';
    box.querySelector('#iso_g').value = (init.grants || []).join('\n');
    const upd = () => {
      level = (radios.find(r => r.checked) || {}).value || minimum;
      net.disabled = level === 'unrestricted';
      box.querySelector('#iso_warn').hidden = !(level === 'readonly' && net.checked);
      box.querySelector('#iso_grants').hidden = level !== 'sandboxed';
    };
    const noask = box.querySelector('#iso_noask');
    if(noask) noask.checked = !!opts.dontAsk;
    radios.forEach(r => r.addEventListener('change', upd));
    net.addEventListener('change', upd);
    upd();
    const done = v => { modalCancel = null; $('modal').hidden = true; resolve(v); };
    box.querySelector('#iso_cancel').onclick = () => done(null);
    box.querySelector('#iso_ok').onclick = () => done({
      level, internet: level === 'unrestricted' ? true : net.checked, dontAsk: !!(noask && noask.checked),
      grants: level === 'sandboxed' ? box.querySelector('#iso_g').value.split('\n').map(x => x.trim()).filter(Boolean) : []});
  });
}
// how a network about to be opened runs: the saved choice when the user said
// not to be asked again, else the dialog (its answer saved when save is set,
// and "Don't ask me again" saved in any case). Returns {level, internet, grants,
// saved} or null when cancelled.
async function chooseOpenLevel(title, intro, save){
  const st = ST.iso || await loadIsoSettings();
  if(!st || !st.available) return {level: 'unrestricted', internet: true, grants: []};
  if(st.ask === false) return {level: st.open_level, internet: st.internet, grants: [], saved: true};
  const ch = await isolationChooser(title, {level: st.open_level, internet: st.internet}, 'Open', intro,
    {askBox: true, askNote: 'File &gt; Execution mode&hellip; (or the badge in the toolbar) shows this choice again.'});
  if(!ch) return null;
  const pref = {};
  if(save || ch.dontAsk){
    pref.open_level = ch.level;
    pref.internet = ch.level === 'unrestricted' ? st.internet : ch.internet;
  }
  if(ch.dontAsk) pref.ask = false;
  if(Object.keys(pref).some(k => pref[k] !== st[k])){
    const s2 = await api('api/settings', pref); if(!s2.error) ST.iso = s2; }
  return ch;
}
function savedModeNote(ch){
  return ch && ch.saved ? ' (' + esc(ISO_TEXT[ch.level][0].toLowerCase()) + (ch.internet && ch.level !== 'unrestricted' ? ', internet' : '') +
    ', your saved choice: File &gt; Execution mode&hellip; changes it)' : '';
}
// File > Execution mode... and the badge: how this network runs, and whether the
// networks opened later ask ("Don't ask me again"). The network is reopened only
// when its own mode changes. Ticking or unticking the box, or picking another
// mode while it is ticked, saves the choice for the networks opened later.
async function changeIsolation(){
  const st = ST.iso || await loadIsoSettings();
  if(!st || !st.available){ reportDialog('Execution mode', [st ? st.reason : 'the server did not answer']); return; }
  const cur = ST.isolation || {level: 'unrestricted', internet: true};
  const asked = st.ask !== false;
  const lower = l => esc(ISO_TEXT[l] ? ISO_TEXT[l][0].toLowerCase() : l);
  const saved = lower(st.open_level) + (st.internet && st.open_level !== 'unrestricted' ? ' with internet access' : '');
  const ch = await isolationChooser('Execution mode of ' + ST.name, cur, 'OK',
    'Another mode saves this network, closes it and opens it again in that mode; the results of its last run are not kept.',
    {askBox: true, dontAsk: !asked,
     askNote: asked ? 'Networks you open, import or take from the examples ask how they run.'
                    : 'Networks you open, import or take from the examples run ' + saved + ', without asking.'});
  if(!ch) return;
  const same = (a, b) => JSON.stringify(a || []) === JSON.stringify(b || []);
  const moved = ch.level !== cur.level || (ch.level !== 'unrestricted' && !!ch.internet !== !!cur.internet) ||
                !same(ch.grants, cur.level === 'sandboxed' ? cur.grants : []);
  const pref = {};
  if(ch.dontAsk && (asked || moved))
    Object.assign(pref, {ask: false, open_level: ch.level, internet: ch.level === 'unrestricted' ? st.internet : ch.internet});
  else if(!ch.dontAsk && !asked) pref.ask = true;
  if(Object.keys(pref).length){ const s2 = await api('api/settings', pref); if(!s2.error) ST.iso = s2; }
  const note = pref.ask === false ? 'networks you open now run ' + lower(ch.level) + ' without asking'
             : pref.ask === true ? 'WEWoS will ask how each network you open runs' : '';
  if(!moved){ if(note) status(note); return; }
  status('reopening ' + esc(ST.name) + '&hellip;');
  const d = await api('api/isolation', {s: ST.sid, level: ch.level, internet: ch.internet, grants: ch.grants});
  if(d.error) return;
  await loadSession(ST.sid);
  status('reopened ' + esc(ST.name) + ': ' + lower(ch.level) + (note ? '; ' + note : ''));
}
async function forceStop(){
  status('restarting the network&hellip;');
  const d = await run('kill');
  if(d.error) return;
  await loadSession(ST.sid);
  status('the network was restarted from its last autosave');
}

/* ------------------------------------------------------------ menus */
function menu(ev, items){
  const m = $('menu'); m.innerHTML = '';
  items.forEach(it => {
    if(it === '-'){ m.append(document.createElement('hr')); return; }
    const [label, fn, disabled] = it;
    const d = document.createElement('div');
    d.textContent = label;
    if(disabled) d.className = 'dis';
    else d.onclick = () => { m.hidden = true; fn(); };
    m.append(d);
  });
  m.hidden = false;
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(ev.clientX, innerWidth - r.width - 6) + 'px';
  m.style.top = Math.min(ev.clientY, innerHeight - r.height - 6) + 'px';
}
document.addEventListener('pointerdown', e => { if(!$('menu').contains(e.target)) $('menu').hidden = true; });

function groupMacro(ids){
  const name = prompt('Name of the new macro node', 'macro');
  if(name === null) return;
  edit('make_macro', {nodes: ids, name});
}
function paste(){
  edit('paste', {net: ST.cur, offset: [40, 40]});
}
function nodeMenu(id, ev){ menu(ev, nodeMenuItems(id)); }
function nodeMenuItems(id){
  const [, n] = findNode(id);
  const sel = ED.selection().nodes;
  return [
    ['Run this node', () => run('run_node', {node: id})],
    ['Edit code…', () => codeEditor(id)],
    ['Rename…', () => { const nm = prompt('Name', n.name); if(nm) edit('rename', {node: id, name: nm}); }],
    [n.frozen ? 'Unfreeze' : 'Freeze', () => edit('freeze', {node: id, frozen: !n.frozen})],
  ].concat(n.macro ? [
    '-',
    ['Open macro', () => switchTab(id)],
    ['Explode macro (put its nodes here)', () => explodeMacro(id)],
  ] : []).concat([
    '-',
    ['Copy', () => edit('copy', {nodes: sel})],
    ['Group into a macro…', () => groupMacro(sel)],
    ['Delete', () => edit('delete', {nodes: sel})],
  ]);
}
async function explodeMacro(id){
  if(ST.tabs.includes(id)) closeTab(id);
  const d = await edit('explode_macro', {node: id});
  if(!d.error){
    ED.select(d.nodes || []);
    status('macro exploded into ' + (d.nodes || []).length + ' nodes' +
           (d.report && d.report.length ? '; some connections could not be remade (see the log)' : ''));
  }
}
function portMenu(nid, io, port, ev){
  const [, n] = findNode(nid);
  const items = [['Show data', () => showData(nid, io, port)]];
  if(io === 'in'){
    const p = (n.in || []).find(x => x.name === port);
    if(p && p.unbound) items.push(['Rebind widget', () => edit('rebind', {node: nid, port})]);
  }
  const net = ST.nets[ST.cur];
  const conns = Object.values(net.conns).filter(c => (io === 'out' ? c.from : c.to)[0] === nid && (io === 'out' ? c.from : c.to)[1] === port);
  if(conns.length) items.push(['Disconnect (' + conns.length + ')', () => edit('delete', {conns: conns.map(c => c.id)})]);
  menu(ev, items);
}
const fileMenu = ev => menu(ev, [
  ['New network', newNetwork],
  ['Open network (.wnet.json)…', () => $('fileopen').click()],
  ['Import a Vision network (*_net.py)…', () => $('fileimport').click()],
  ['Open an example…', examplesDialog],
  '-',
  ['Save', () => save(false)],
  ['Save as…', () => save(true)],
  ['Download the network file', downloadNet],
  ['Download the network folder (zip)', () => { location.href = 'api/download?s=' + ST.sid + '&t=' + encodeURIComponent(T); }],
  '-',
  ['Rename network…', () => { const nm = prompt('Network name', ST.name); if(nm) edit('rename_network', {name: nm}); }],
  ['Close network…', () => closeNetwork(ST.sid)],
  '-',
  ['Execution mode…', changeIsolation, !(ST.iso && ST.iso.available)],
  ['Force stop (restart its sandbox)', forceStop, isolated() ? false : true],
]);
const editMenu = ev => {
  const sel = ED.selection();
  menu(ev, [
    ['Copy', () => edit('copy', {nodes: sel.nodes}), !sel.nodes.length],
    ['Paste', paste],
    ['Delete', () => edit('delete', sel), !(sel.nodes.length || sel.conns.length)],
    ['Select all', () => ED.select(Object.keys(ST.nets[ST.cur].nodes))],
    ['Group into a macro…', () => groupMacro(sel.nodes), !sel.nodes.length],
    '-',
    ['Arrange the nodes from left to right', arrangeNodes],
    ['Fit the network in view (f)', () => ED.fit()],
    [(W.isReversed() ? '\u2713 ' : '') + 'Reverse the scrolling direction on numbers',
     () => { W.setReverse(!W.isReversed());
             status('scrolling up now ' + (W.isReversed() ? 'decreases' : 'increases') + ' values'); }],
  ]);
};
async function arrangeNodes(){
  const d = await edit('arrange', {net: ST.cur});
  if(!d || d.error) return;
  // the moves arrive as events: fit the view once they are in
  for(let i = 0; i < 60 && ST.seq < d.seq; i++) await new Promise(r => setTimeout(r, 50));
  ED.fit();
}
$('m_file').onclick = e => { e.stopPropagation(); fileMenu(e); };
$('m_edit').onclick = e => { e.stopPropagation(); editMenu(e); };

async function save(ask){
  let name = ST.name;
  if(ask){ name = prompt('Save as (in the network folder)', ST.name); if(!name) return; }
  const d = await api('api/save', {s: ST.sid, name});
  if(!d.error){ ST.savedFile = d.file; status('saved ' + esc(d.path)); }
  return d;
}
async function downloadNet(){
  const d = await save(false);
  if(d && !d.error) location.href = 'api/download?s=' + ST.sid + '&file=' + encodeURIComponent(d.file) + '&t=' + encodeURIComponent(T);
}
async function examplesDialog(){
  const d = await api('api/examples');
  if(d.error) return;
  const box = document.createElement('div');
  box.className = 'fb-list';
  // one foldable section per group (WEWoS's own examples open)
  const groups = new Map();
  d.examples.forEach(x => {
    const g = x.group || 'WEWoS';
    if(!groups.has(g)){
      const sec = document.createElement('details');
      sec.className = 'exgroup';
      sec.open = groups.size === 0;
      sec.innerHTML = '<summary></summary>';
      box.append(sec);
      groups.set(g, {sec, n: 0});
    }
    const it = document.createElement('div');
    it.innerHTML = '&#128200; ' + esc(x.name) + '<span class=sz>' + x.nodes + ' nodes</span>';
    it.onclick = async () => {
      closeModal();
      // the same choice as for a file; not remembered unless "Don't ask me again"
      // is ticked (examples come with WEWoS)
      const ch = await chooseOpenLevel('Open the example ' + x.name,
        'Examples come with WEWoS, but like any network they run code. How should this one run?', false);
      if(!ch) return;
      status('opening ' + esc(x.name) + '&hellip;');
      ST.opening++;
      try {
        const r = await api('api/example', {name: x.file, level: ch.level, internet: ch.internet, grants: ch.grants || []});
        if(r.error) return;
        await loadSession(r.session);
      } finally { ST.opening--; }
      if(ch.saved) status('opened ' + esc(x.name) + savedModeNote(ch));
    };
    const gr = groups.get(g);
    gr.sec.append(it);
    gr.n++;
  });
  groups.forEach((gr, g) => { gr.sec.querySelector('summary').textContent = g + ' (' + gr.n + ')'; });
  modal('Examples', box);
}
async function newNetwork(){
  const name = prompt('Name of the new network', 'network');
  if(name === null) return;
  const d = await api('api/new', {name});
  if(!d.error) loadSession(d.session);
}
async function openUpload(file, kind){
  if(!file) return;
  // the choice is the default for the next file
  const ch = await chooseOpenLevel((kind === 'import' ? 'Import ' : 'Open ') + file.name,
    'A network file is a program: opening it runs the code of its nodes, and running it runs ' +
    'the rest. How should this one run?', true);
  if(!ch) return;
  const q = '&level=' + ch.level + '&internet=' + (ch.internet ? 1 : 0) +
            (ch.grants || []).map(g => '&grant=' + encodeURIComponent(g)).join('');
  status((kind === 'import' ? 'importing ' : 'opening ') + esc(file.name) + '&hellip;');
  ST.opening++;
  let d;
  try {
    d = await api('api/' + kind + '?name=' + encodeURIComponent(file.name) + q, null, file);
    if(d.error) return;
    await loadSession(d.session);
  } finally { ST.opening--; }
  if(ch.saved) status('opened ' + esc(file.name) + savedModeNote(ch));
  if(kind === 'import' && d.report){
    const r = d.report, lines = [];
    lines.push(r.nodes + ' nodes, ' + r.connections + ' connections imported');
    (r.unmapped || []).forEach(u => lines.push('not available: ' + u));
    (r.code || []).forEach(u => lines.push('edited code converted to Python 3: ' + u));
    (r.warnings || []).forEach(u => lines.push(u));
    (r.load || []).forEach(u => lines.push(u));
    reportDialog('Imported ' + file.name, lines);
  }
}
$('fileopen').onchange = e => openUpload(e.target.files[0], 'open');
$('fileimport').onchange = e => openUpload(e.target.files[0], 'import');
document.addEventListener('dragover', e => { if(e.dataTransfer.types.includes('Files')){ e.preventDefault(); document.body.classList.add('drag'); } });
document.addEventListener('dragleave', e => { if(!e.relatedTarget) document.body.classList.remove('drag'); });
document.addEventListener('drop', e => {
  document.body.classList.remove('drag');
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if(!f) return;
  e.preventDefault();
  if(/_net\.py$|\.py$/.test(f.name)) openUpload(f, 'import');
  else if(/\.json$/.test(f.name)) openUpload(f, 'open');
});

async function refreshSessions(){
  // answers can arrive out of order: keep only the newest request's
  const mine = ST.sessReq = (ST.sessReq || 0) + 1;
  const d = await api('api/sessions');
  if(d.error || mine !== ST.sessReq) return;
  ST.sessions = d.sessions;
  if(ST.sid && !ST.opening && !d.sessions.some(x => x.session === ST.sid)){ showAnotherNetwork(); return; }
  drawTabs();
  const s = $('sessions'); s.innerHTML = '';
  d.sessions.forEach(x => {
    const o = document.createElement('option');
    const lv = (x.isolation || {}).level;
    o.value = x.session;
    o.textContent = (lv === 'sandboxed' ? '\u{1F6E1} ' : lv === 'readonly' ? '\u{1F6E1}r ' : '') +
                    x.name + ' (' + x.nodes + ' nodes' + (x.status === 'stopped' ? ', stopped' : '') + ')';
    if(x.session === ST.sid) o.selected = true;
    s.append(o);
  });
}
$('sessions').onchange = e => loadSession(e.target.value);
$('sessions').onfocus = refreshSessions;
// networks opened from another page or browser tab show up when this one is used again
window.addEventListener('focus', refreshSessions);

/* ------------------------------------------------------------ toolbar */
$('b_run').onclick = () => run('run');
$('b_hardrun').onclick = () => run('hardrun');
$('b_pause').onclick = () => run(ST.exec === 'pause' ? 'resume' : 'pause');
$('b_stop').onclick = async () => {
  await run('stop');
  if(!isolated()) return;
  // stopping waits for the running node to finish: offer to end an isolated
  // network's process when that does not happen
  const sid = ST.sid;
  setTimeout(() => {
    if(ST.sid !== sid || (ST.exec !== 'running' && ST.exec !== 'stop')) return;
    const box = document.createElement('div');
    box.innerHTML = '<p>The network has not stopped: a node is still busy, and stopping waits for it to finish.</p>' +
      '<p><b>Force stop</b> ends the network\'s sandbox and starts it again from its last autosave. ' +
      'The results of this run are lost; the network itself is kept.</p>' +
      '<div class=btns style="display:flex;gap:6px"><button class=primary id=fs_go>Force stop</button><button id=fs_wait>Keep waiting</button></div>';
    modal('Stop ' + ST.name, box);
    box.querySelector('#fs_go').onclick = () => { closeModal(); forceStop(); };
    box.querySelector('#fs_wait').onclick = closeModal;
  }, 5000);
};
$('isolation').onclick = () => changeIsolation();
$('b_auto').onchange = e => edit('run_on_new_data', {value: e.target.checked});
$('logclear').onclick = e => { e.preventDefault(); $('log').textContent = ''; $('loglen').textContent = ''; };
$('theme').onclick = () => {
  const cur = document.documentElement.dataset.theme ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('wewos.theme', next); } catch(e) {}
  VIEW3D.theme();
};
(function viewerRow(){
  // the row of viewers and images under the network shows when there is one
  const vw = $('viewers'), center = $('center');
  const upd = () => center.classList.toggle('hasviewers', vw.children.length > 0);
  new MutationObserver(upd).observe(vw, {childList: true});
  upd();
})();
(function hsplit(){
  // drag the divider to share the height between the network and the viewers
  // under it; the share is remembered in this browser
  const sp = $('hsplit'), center = $('center'), vw = $('viewers');
  try { const f = parseFloat(localStorage.getItem('wewos.viewerRow')); if(f > 0.1 && f < 0.9) vw.style.height = (f * 100) + '%'; } catch(e) {}
  sp.addEventListener('pointerdown', e => {
    e.preventDefault();
    sp.setPointerCapture(e.pointerId);
    const H = center.clientHeight, bottom = vw.getBoundingClientRect().bottom;
    const mv = ev => {
      const f = Math.max(0.12, Math.min(0.88, (bottom - ev.clientY) / H));
      vw.style.height = (f * 100) + '%';
    };
    const up = () => {
      sp.removeEventListener('pointermove', mv); sp.removeEventListener('pointerup', up);
      try { localStorage.setItem('wewos.viewerRow', String(vw.offsetHeight / H)); } catch(e) {}
    };
    sp.addEventListener('pointermove', mv); sp.addEventListener('pointerup', up);
  });
})();
(function splitter(){
  // drag to resize the parameter column; its width is remembered in this browser
  const sp = $('splitter'), side = $('side');
  try { const w = parseFloat(localStorage.getItem('wewos.sideWidth')); if(w >= 240) side.style.width = w + 'px'; } catch(e) {}
  sp.addEventListener('pointerdown', e => {
    sp.setPointerCapture(e.pointerId);
    const x0 = e.clientX, w0 = side.offsetWidth;
    const mv = ev => { side.style.width = Math.max(240, Math.min(innerWidth - 500, w0 - (ev.clientX - x0))) + 'px'; };
    const up = () => {
      sp.removeEventListener('pointermove', mv); sp.removeEventListener('pointerup', up);
      try { localStorage.setItem('wewos.sideWidth', String(side.offsetWidth)); } catch(e) {}
    };
    sp.addEventListener('pointermove', mv); sp.addEventListener('pointerup', up);
  });
})();

/* ------------------------------------------------------------ start */
ED.init($('canvas'), {
  edit: (op, a) => edit(op, a).then(d => { if(op === 'copy' && !d.error) status(d.copied + ' node(s) copied'); return d; }),
  selected: () => panel(),
  dblclick: id => { const [, n] = findNode(id); if(n && n.macro) switchTab(id); else codeEditor(id); },
  contextNode: nodeMenu,
  contextWidget: nodeWidgetMenu,
  contextPort: portMenu,
  contextConn: (cid, ev) => menu(ev, [['Delete connection', () => edit('delete', {conns: [cid]})]]),
  contextCanvas: (pos, ev) => menu(ev, [['Paste', paste], ['Fit the network in view', () => ED.fit()],
                                        ['Run (soft)', () => run('run')], ['Run all', () => run('hardrun')],
                                        '-', ['Close network…', () => closeNetwork(ST.sid)]]),
  widgetCtx: (nid, port, compact) => widgetCtx(nid, port, compact),
  paste,
});
VIEW3D.init($('viewers'), {
  pick: body => api('api/pick', Object.assign({s: ST.sid}, body)),
  find: id => findNode(id)[1],
  edit: (op, a) => edit(op, a),
  status,
  menu: (ev, items) => menu(ev, items),
});
(async function start(){
  await loadLibraries();
  await loadIsoSettings();
  const q = new URLSearchParams(location.search);
  const sid = q.get('session');
  if(sid && await loadSession(sid)) return;
  const d = await api('api/sessions');
  if(!d.error && d.sessions && d.sessions.length){ await loadSession(d.sessions[0].session); return; }
  const n = await api('api/new', {name: 'network'});
  if(!n.error) loadSession(n.session);
})();
