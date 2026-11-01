/* Author: Michel Sanner, PhD. Copyright (c) 2026. */
/* Port widgets: HTML controls drawn from the server's widget spec
   ({class, kind, label, value, options}). They replace the Tk widgets of
   NetworkEditor/widgets.py. A widget never keeps state of its own: a change
   is sent to the server (ctx.change), which sets the value and sends back a
   'widget' event that redraws it. */
'use strict';
const W = (() => {
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const el = (tag, attrs, html) => {
    const e = document.createElement(tag);
    for(const k in (attrs || {})){
      if(k === 'class') e.className = attrs[k];
      else if(k === 'style') e.style.cssText = attrs[k];
      else if(attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    }
    if(html !== undefined) e.innerHTML = html;
    return e;
  };

  /* ---- mouse wheel and trackpad --------------------------------------------
     Scrolling over a number field changes it: one step per notch of a mouse
     wheel, about one step per 12 px of trackpad scrolling. Shift gives
     steps 10 times finer, Alt (Option) 10 times coarser. To keep a panel or
     the canvas scrollable, a scroll that started outside a field and passes
     over it within 400 ms is left alone. */
  let lastOutside = 0;
  // while a value is being dragged or scrolled the page must not redraw the
  // widget under the pointer (app.js asks isBusy() before redrawing the panel)
  let busyUntil = 0, dragging = false;
  const isBusy = () => dragging || performance.now() < busyUntil;
  document.addEventListener('wheel', e => {
    if(!(e.target.closest && e.target.closest('.wheelable'))) lastOutside = performance.now();
  }, {capture: true, passive: true});

  /* Direction: moving the fingers (or the wheel) up or right increases the
     value. Browsers report scrolling after macOS "natural scrolling" has
     inverted it; Safari says when it did (webkitDirectionInvertedFromDevice),
     elsewhere on a Mac natural scrolling (the default) is assumed. The
     Edit menu can reverse the direction, remembered in this browser. */
  const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
  let reverse = false;
  try { reverse = localStorage.getItem('wewos.reverseScroll') === '1'; } catch(e) {}
  function setReverse(v){
    reverse = !!v;
    try { localStorage.setItem('wewos.reverseScroll', reverse ? '1' : '0'); } catch(e) {}
  }

  function wheelSteps(e, st){
    let d = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? -e.deltaY : e.deltaX;
    const inverted = typeof e.webkitDirectionInvertedFromDevice === 'boolean'
      ? e.webkitDirectionInvertedFromDevice : IS_MAC;
    if(inverted !== reverse) d = -d;
    if(e.deltaMode === 1) d *= 33;                 // lines
    else if(e.deltaMode === 2) d *= 400;           // pages
    // a mouse wheel notch is reported as a multiple of 120 (wheelDelta);
    // trackpads report small, varying amounts
    const wd = e.wheelDeltaY || e.wheelDeltaX || 0;
    if(wd && wd % 120 === 0) return Math.sign(d);
    st.acc = (st.acc || 0) + d / 12;
    const n = Math.trunc(st.acc);
    st.acc -= n;
    return n;
  }

  function onWheel(target, apply){
    target.classList.add('wheelable');
    const st = {};
    target.addEventListener('wheel', e => {
      if(performance.now() - lastOutside < 400) return;   // scrolling through
      if(e.ctrlKey || e.metaKey) return;                  // pinch zoom (trackpad)
      e.preventDefault(); e.stopPropagation();
      busyUntil = performance.now() + 600;
      const n = wheelSteps(e, st);
      if(n) apply(n * (e.shiftKey ? 0.1 : e.altKey ? 10 : 1));
    }, {passive: false});
  }

  // 1, 2 or 5 times a power of ten: the step closest to x
  function nice(x){
    if(!(x > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(x))), f = x / p;
    return p * (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10);
  }
  // round away the float noise of repeated additions
  const clean = (v, step) => +v.toFixed(Math.max(0, Math.min(10, 2 - Math.floor(Math.log10(step)))));

  function stepOf(o){
    if(o.increment > 0) return o.increment;
    if(o.type === 'int') return 1;
    if(o.min != null && o.max != null && o.max > o.min) return nice((o.max - o.min) / 100);
    if(o.oneTurn) return nice(o.oneTurn / 100);
    return 0.1;
  }

  // send continuous changes at most every 150 ms (and the last one always),
  // so the network can follow a drag or a scroll without a backlog
  function throttled(fn, ms){
    let last = 0, timer = null, pending;
    return v => {
      pending = v;
      if(timer) return;
      const wait = Math.max(0, ms - (performance.now() - last));
      timer = setTimeout(() => { timer = null; last = performance.now(); fn(pending); }, wait);
    };
  }

  function fmt(v, o){
    if(v === null || v === undefined || v === '') return '';
    if(o.type === 'int') return String(Math.round(v));
    const p = o.precision == null ? 3 : o.precision;
    return Number(v).toFixed(Math.min(Math.max(p, 0), 8)).replace(/\.?0+$/, m => m.startsWith('.') ? '' : m);
  }

  /* number: thumbwheel and dial. Drag the handle (or the field with the
     middle button) to change the value continuously, like a thumbwheel. */
  function number(spec, ctx){
    const o = spec.options || {};
    const box = el('div', {class: 'w-number'});
    const hasRange = o.min != null && o.max != null;
    const inp = el('input', {type: 'number', step: o.type === 'int' ? 1 : (o.increment || 'any')});
    inp.value = fmt(spec.value, o);
    const scrub = el('span', {class: 'scrub', title: 'drag left/right, or scroll, to change\n(Shift: finer, Alt/Option: coarser)'}, '&#8644;');
    inp.title = 'scroll to change (Shift: finer, Alt/Option: coarser)';
    /* our own up/down arrows: the browser's spin buttons are hidden, as
       WebKit draws them at the corner of the canvas for an input inside the
       SVG of a node (foreignObject) */
    const spin = el('span', {class: 'spin', title: 'click or hold to step (Shift: finer, Alt/Option: coarser)'},
                    '<span data-d=1>&#9652;</span><span data-d=-1>&#9662;</span>');
    box.append(scrub, inp, spin);
    let range = null;
    if(hasRange && !ctx.compact){
      range = el('input', {type: 'range', min: o.min, max: o.max,
                           step: o.type === 'int' ? 1 : ((o.max - o.min) / 500 || 'any')});
      range.value = spec.value;
      range.addEventListener('input', () => { inp.value = fmt(range.value, o); send(+range.value, false); });
      range.addEventListener('change', () => send(+range.value, true));
      box.append(range);
    }
    const live = throttled(v => ctx.change(v, true), 150);
    function send(v, final){
      if(final) ctx.change(v, true); else live(v);
    }
    const clamp = v => {
      if(o.type === 'int') v = Math.round(v);
      if(o.min != null) v = Math.max(o.min, v);
      if(o.max != null) v = Math.min(o.max, v);
      return v;
    };
    const step = stepOf(o);
    const bump = k => {
      const cur = inp.value === '' ? 0 : +inp.value;
      const st = o.type === 'int' ? Math.max(1, Math.round(step * Math.abs(k))) * Math.sign(k) : step * k;
      const v = clamp(clean(cur + st, Math.abs(st)));
      if(v === cur) return;
      inp.value = fmt(v, o);
      if(range) range.value = v;
      send(v, false);
    };
    onWheel(box, bump);
    spin.addEventListener('pointerdown', e => {
      const d = +(e.target.dataset && e.target.dataset.d);
      if(!d) return;
      e.preventDefault(); e.stopPropagation();     // not a node drag
      const k = d * (e.shiftKey ? 0.1 : e.altKey ? 10 : 1);
      dragging = true;
      bump(k);
      let timer = setTimeout(function again(){ bump(k); timer = setTimeout(again, 70); }, 400);
      const stop = () => {
        clearTimeout(timer);
        spin.removeEventListener('pointerup', stop); spin.removeEventListener('pointercancel', stop);
        spin.removeEventListener('lostpointercapture', stop);
        dragging = false; busyUntil = performance.now() + 400;
        if(inp.value !== '') live(+inp.value);
      };
      spin.setPointerCapture(e.pointerId);
      spin.addEventListener('pointerup', stop); spin.addEventListener('pointercancel', stop);
      spin.addEventListener('lostpointercapture', stop);
    });
    inp.addEventListener('change', () => { if(inp.value !== '') send(+inp.value, true); });
    inp.addEventListener('keydown', e => { if(e.key === 'Enter') inp.blur(); });
    scrub.addEventListener('pointerdown', e => {
      e.preventDefault(); e.stopPropagation();
      scrub.setPointerCapture(e.pointerId);
      dragging = true;
      const x0 = e.clientX, v0 = +inp.value || 0;
      const oneTurn = o.oneTurn || (hasRange ? (o.max - o.min) : 10);
      const per = oneTurn / 200;                // 200 px = one turn of the wheel
      const move = ev => {
        let v = v0 + (ev.clientX - x0) * per * (ev.shiftKey ? 0.1 : 1);
        if(o.increment) v = Math.round(v / o.increment) * o.increment;
        if(o.type === 'int') v = Math.round(v);
        if(o.min != null) v = Math.max(o.min, v);
        if(o.max != null) v = Math.min(o.max, v);
        inp.value = fmt(v, o);
        if(range) range.value = v;
        send(v, false);
      };
      const up = () => { scrub.removeEventListener('pointermove', move);
                         scrub.removeEventListener('pointerup', up);
                         dragging = false; busyUntil = performance.now() + 400;
                         live(+inp.value); };
      scrub.addEventListener('pointermove', move);
      scrub.addEventListener('pointerup', up);
    });
    if(Array.isArray(o.signatures) && o.signatures.length && !ctx.compact && hasRange){
      // contour spectrum: the signature curves over the value range; a click
      // on the plot sets the value there
      const wrap = el('div', {style: 'display:flex;flex-direction:column;gap:2px;width:100%'});
      wrap.append(spectrum(o, spec.value, v => {
        v = clamp(v); inp.value = fmt(v, o); if(range) range.value = v; send(v, true);
      }), box);
      return wrap;
    }
    return box;
  }

  const SIG_COLORS = ['#e8590c', '#1c7ed6', '#2b8a3e', '#ae3ec9', '#868e96'];
  function spectrum(o, value, set){
    const W = 300, H = 70, NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.style.cssText = 'width:100%;height:70px;background:var(--soft);border:1px solid var(--line);border-radius:4px;cursor:crosshair';
    const x0 = o.min, x1 = o.max, sx = x => (x - x0) / ((x1 - x0) || 1) * W;
    o.signatures.forEach((c, i) => {
      if(!c.x || !c.x.length) return;
      const ymax = Math.max(...c.y.map(Math.abs)) || 1;
      const pts = c.x.map((x, k) => sx(x).toFixed(1) + ',' + (H - 4 - (c.y[k] / ymax) * (H - 8)).toFixed(1));
      const pl = document.createElementNS(NS, 'polyline');
      pl.setAttribute('points', pts.join(' '));
      pl.setAttribute('fill', 'none');
      pl.setAttribute('stroke', SIG_COLORS[i % SIG_COLORS.length]);
      pl.setAttribute('stroke-width', '1.2');
      pl.setAttribute('vector-effect', 'non-scaling-stroke');
      svg.append(pl);
    });
    const mark = document.createElementNS(NS, 'line');
    mark.setAttribute('y1', 0); mark.setAttribute('y2', H);
    mark.setAttribute('x1', sx(value)); mark.setAttribute('x2', sx(value));
    mark.setAttribute('stroke', 'var(--fg)'); mark.setAttribute('stroke-dasharray', '3 2');
    mark.setAttribute('vector-effect', 'non-scaling-stroke');
    svg.append(mark);
    const title = document.createElementNS(NS, 'title');
    title.textContent = 'contour spectrum (click to set the isovalue)';
    svg.append(title);
    svg.addEventListener('pointerdown', e => {
      e.stopPropagation();
      const r = svg.getBoundingClientRect();
      const v = x0 + (e.clientX - r.left) / r.width * (x1 - x0);
      mark.setAttribute('x1', sx(v)); mark.setAttribute('x2', sx(v));
      set(v);
    });
    return svg;
  }

  function entry(spec, ctx){
    const inp = el('input', {type: 'text', spellcheck: 'false'});
    inp.value = spec.value == null ? '' : spec.value;
    inp.addEventListener('change', () => ctx.change(inp.value, true));
    inp.addEventListener('keydown', e => { if(e.key === 'Enter') inp.blur(); });
    return inp;
  }

  function checkbox(spec, ctx){
    const c = el('input', {type: 'checkbox'});
    c.checked = !!spec.value;
    c.addEventListener('change', () => ctx.change(c.checked ? 1 : 0, true));
    return c;
  }

  function button(spec, ctx){
    const b = el('button', {}, esc(spec.options.text || spec.label || 'press'));
    b.addEventListener('click', e => { e.stopPropagation(); ctx.change(1, true); });
    return b;
  }

  function combo(spec, ctx){
    const o = spec.options || {};
    const choices = (o.choices || []).map(x => x == null ? '' : String(x));
    const cur = spec.value == null ? '' : String(spec.value);
    if(!o.fixedChoices && !ctx.compact){
      // free text with suggestions
      const inp = el('input', {type: 'text', list: 'dl' + Math.random().toString(36).slice(2)});
      const dl = el('datalist', {id: inp.getAttribute('list')});
      choices.forEach(c => dl.append(el('option', {value: c})));
      inp.value = cur;
      inp.addEventListener('change', () => ctx.change(inp.value, true));
      const box = el('span', {style: 'display:flex;width:100%'});
      inp.style.flex = '1';
      box.append(inp, dl);
      return box;
    }
    const s = el('select');
    if(!choices.includes(cur)) s.append(el('option', {value: cur}, esc(cur)));
    choices.forEach(c => { const op = el('option', {value: c}, esc(c)); if(c === cur) op.selected = true; s.append(op); });
    s.addEventListener('change', () => ctx.change(s.value, true));
    return s;
  }

  function file(spec, ctx){
    const box = el('div', {class: 'w-file'});
    const inp = el('input', {type: 'text', spellcheck: 'false', placeholder: spec.kind === 'dir' ? 'folder' : 'file'});
    inp.value = spec.value || '';
    inp.title = inp.value;
    inp.addEventListener('change', () => ctx.change(inp.value, true));
    const b = el('button', {title: 'browse files on the server'}, '&hellip;');
    b.addEventListener('click', async e => {
      e.stopPropagation();
      const p = await ctx.pickFile(spec.kind, inp.value, spec.options || {});
      if(p != null){ inp.value = p; ctx.change(p, true); }
    });
    box.append(inp, b);
    if(spec.kind === 'file' && !ctx.compact){
      const u = el('button', {title: 'upload a file from this computer'}, '&#8679;');
      u.addEventListener('click', async e => {
        e.stopPropagation();
        const p = await ctx.upload();
        if(p){ inp.value = p; ctx.change(p, true); }
      });
      box.append(u);
    }
    return box;
  }

  function text(spec, ctx){
    if(ctx.compact) return entry(spec, ctx);
    const t = el('textarea', {class: 'w-text', spellcheck: 'false'});
    t.value = spec.value == null ? '' : spec.value;
    t.addEventListener('change', () => ctx.change(t.value, true));
    return t;
  }

  // a plain number field that scrolls by step, then calls live()
  function wheelField(inp, step, live){
    onWheel(inp, k => {
      const s = step * k;
      inp.value = clean((+inp.value || 0) + s, Math.abs(s));
      live();
    });
  }

  function vector(spec, ctx){
    const box = el('div', {class: 'w-vector'});
    // as many fields as the value has components (3 when there is none yet)
    const v = Array.isArray(spec.value) && spec.value.length ? spec.value : [0, 0, 0];
    const n = Math.min(v.length, 16);
    const ins = [];
    const live = throttled(() => ctx.change(ins.map(x => +x.value), true), 150);
    for(let i = 0; i < n; i++){
      const inp = el('input', {type: 'number', step: 'any', title: 'scroll to change by 0.1 (Shift: 0.01, Alt/Option: 1)'});
      inp.value = v[i] == null ? 0 : v[i];
      inp.addEventListener('change', () => ctx.change(ins.map(x => +x.value), true));
      wheelField(inp, 0.1, live);
      ins.push(inp); box.append(inp);
    }
    return box;
  }

  /* symserv translation: a length and an axis for each of x, y and z */
  function xyzvect(spec, ctx){
    const box = el('div', {style: 'display:grid;grid-template-columns:auto 70px 1fr;gap:3px;align-items:center;width:100%'});
    const v = Array.isArray(spec.value) && spec.value.length === 6 ? spec.value
      : [0, 0, 0, [1, 0, 0], [0, 1, 0], [0, 0, 1]];
    const lens = [], axes = [];
    const send = () => ctx.change(lens.map(x => +x.value).concat(axes.map(a => a.map(x => +x.value))), true);
    const live = throttled(send, 150);
    ['x', 'y', 'z'].forEach((k, i) => {
      const l = el('input', {type: 'number', step: 'any', title: k + ' length'}); l.value = v[i];
      l.addEventListener('change', send); wheelField(l, 1, live); lens.push(l);
      const ax = el('div', {class: 'w-vector'}), a = [];
      for(let j = 0; j < 3; j++){ const c = el('input', {type: 'number', step: 'any'});
        c.value = (v[3 + i] || [0, 0, 0])[j]; c.addEventListener('change', send); wheelField(c, 0.1, live);
        a.push(c); ax.append(c); }
      axes.push(a);
      box.append(el('span', {class: 'dim'}, k), l, ax);
    });
    return box;
  }

  function color(spec, ctx){
    const c = el('input', {type: 'color'});
    const v = Array.isArray(spec.value) ? spec.value : [1, 1, 1];
    const h = x => ('0' + Math.round(Math.max(0, Math.min(1, x)) * 255).toString(16)).slice(-2);
    c.value = '#' + h(v[0]) + h(v[1]) + h(v[2]);
    c.addEventListener('change', () => ctx.change(c.value, true));
    return c;
  }

  function multicheck(spec, ctx){
    const box = el('div', {class: 'w-multi'});
    const items = Array.isArray(spec.value) ? spec.value : [];
    if(!items.length){ box.innerHTML = '<span class=dim>no buttons yet: the node builds them from valueList</span>'; return box; }
    const state = {};
    items.forEach(([name, on]) => {
      state[name] = on;
      const lab = el('label');
      const c = el('input', {type: 'checkbox'}); c.checked = !!on;
      c.addEventListener('change', () => { state[name] = c.checked ? 1 : 0; ctx.change(state, true); });
      lab.append(c, document.createTextNode(' ' + name));
      box.append(lab);
    });
    return box;
  }

  /* colormap: DejaVu's color map editor (ColorMapGUI). The ramp is drawn as
     curves, one channel at a time, in RGB, HSV or HSL (Vision used HSL) plus
     opacity: the left button draws freehand, the right one a straight line,
     and Shift-click a straight segment from the last point (a polyline when
     repeated). Undo (also Ctrl/Cmd+Z on the curve) and reset are under it.
     Presets come from static/colormaps.json (WEWoS's ramps and MGLTools'
     color maps); Vision colormap files are read and written by the server.
     The value is {ramp: [[r, g, b, a], ...], mini, maxi, name}, or a preset name. */
  let CM_PRESETS = null;
  function cmPresets(){
    if(!CM_PRESETS){
      const v = (window.STATIC_V || {})['colormaps.json'] || '0';
      CM_PRESETS = fetch('static/colormaps.json?v=' + v).then(r => r.json()).then(d => d.presets || []).catch(() => []);
    }
    return CM_PRESETS;
  }
  const CM_STATE = {};                   // per node input: mode, channel, history
  const CM_MODES = {RGB: ['red', 'green', 'blue'], HSV: ['hue', 'saturation', 'value'],
                    HSL: ['hue', 'saturation', 'luminance']};
  function rgb2hsv(r, g, b){
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0;
    if(d){ h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h /= 6; if(h < 0) h += 1; }
    return [h, mx ? d / mx : 0, mx];
  }
  function hsv2rgb(h, s, v){
    const f = h * 6, i = Math.floor(f), t = f - i, p = v * (1 - s), q = v * (1 - t * s), u = v * (1 - (1 - t) * s);
    return [[v, u, p], [q, v, p], [p, v, u], [p, q, v], [u, p, v], [v, p, q]][((i % 6) + 6) % 6];
  }
  function rgb2hsl(r, g, b){
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
    return [d ? rgb2hsv(r, g, b)[0] : 0, d ? Math.min(1, d / (1 - Math.abs(2 * l - 1))) : 0, l];
  }
  function hsl2rgb(h, s, l){
    const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h * 6) % 2 - 1)), m = l - c / 2;
    const [r, g, b] = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][((Math.floor(h * 6) % 6) + 6) % 6];
    return [r + m, g + m, b + m];
  }
  const toMode = (m, c) => m === 'HSV' ? rgb2hsv(c[0], c[1], c[2]) : m === 'HSL' ? rgb2hsl(c[0], c[1], c[2]) : [c[0], c[1], c[2]];
  const fromMode = (m, x) => m === 'HSV' ? hsv2rgb(x[0], x[1], x[2]) : m === 'HSL' ? hsl2rgb(x[0], x[1], x[2]) : [x[0], x[1], x[2]];
  const cmCss = c => 'rgba(' + Math.round(c[0] * 255) + ',' + Math.round(c[1] * 255) + ',' + Math.round(c[2] * 255) + ',' + (c[3] == null ? 1 : c[3]) + ')';
  const cmCopy = cm => ({ramp: cm.ramp.map(c => c.slice()), mini: cm.mini, maxi: cm.maxi, name: cm.name});
  // {ramp, mini, maxi, name} of a value (a preset name is looked up)
  async function cmResolve(val){
    if(val && typeof val === 'object' && Array.isArray(val.ramp) && val.ramp.length)
      return {ramp: val.ramp.map(c => [c[0], c[1], c[2], c[3] == null ? 1 : c[3]]),
              mini: val.mini == null ? null : val.mini, maxi: val.maxi == null ? null : val.maxi, name: val.name || ''};
    const name = typeof val === 'string' && val ? val : 'rgb';
    const p = (await cmPresets()).find(x => x.name === name) || {ramp: [[0, 0, 1, 1], [1, 0, 0, 1]]};
    return {ramp: p.ramp.map(c => c.slice()), mini: null, maxi: null, name};
  }
  function cmBar(cv, ramp){
    const g = cv.getContext('2d'), W = cv.width, H = cv.height, s = Math.max(4, Math.round(H / 2));
    for(let x = 0; x < W; x += s) for(let y = 0; y < H; y += s){ g.fillStyle = ((x + y) / s) % 2 ? '#c8c8c8' : '#fff'; g.fillRect(x, y, s, s); }
    if(!ramp || !ramp.length) return;
    for(let x = 0; x < W; x++){ g.fillStyle = cmCss(V3DU.rampAt(ramp, x / Math.max(1, W - 1))); g.fillRect(x, 0, 1, H); }
  }
  function resampleRamp(ramp, n){
    const out = [];
    for(let k = 0; k < n; k++){
      const x = k / (n - 1) * (ramp.length - 1), i = Math.min(Math.floor(x), ramp.length - 2), f = x - i;
      out.push([0, 1, 2, 3].map(j => ramp[i][j] * (1 - f) + ramp[i + 1][j] * f));
    }
    return out;
  }

  function colormap(spec, ctx){
    const key = ctx.key || 'colormap';
    const st = CM_STATE[key] = CM_STATE[key] || {mode: 'HSV', ch: 0, hist: []};
    if(ctx.compact){
      const cv = el('canvas', {width: 120, height: 14, class: 'w-cmbar', title: 'the color ramp: select the node to edit it in its parameter panel'});
      cmResolve(spec.value).then(r => cmBar(cv, r.ramp));
      return cv;
    }
    const box = el('div', {class: 'w-cmap'});
    box.innerHTML =
      '<canvas class=cm-bar width=256 height=16></canvas>' +
      '<div class=cm-row><select class=cm-mode title="edit the ramp as red, green, blue; hue, saturation, value; or hue, saturation, luminance (Vision\'s)">' +
      Object.keys(CM_MODES).map(m => '<option>' + m + '</option>').join('') + '</select><span class=cm-chs></span></div>' +
      '<canvas class=cm-curve width=256 height=120 tabindex=0 title="left button: draw the curve freehand\n' +
      'Shift-click: a straight segment from the last point (repeat for a polyline)\nright button: a straight line\nCtrl/Cmd+Z: undo"></canvas>' +
      '<div class=cm-row><button class=cm-undo title="undo the last change (Ctrl/Cmd+Z on the curve)">&#8630; undo</button>' +
      '<button class=cm-reset title="back to the ramp the editing started from">&#10226; reset</button>' +
      '<label title="update the network while drawing"><input class=cm-cont type=checkbox> continuous</label>' +
      '<span class="cm-hint dim">Shift-click: segment</span></div>' +
      '<div class=cm-row><label>min <input class=cm-min type=number step=any placeholder=auto></label>' +
      '<label>max <input class=cm-max type=number step=any placeholder=auto></label>' +
      '<label>name <input class=cm-name type=text></label></div>' +
      '<div class=cm-row><select class=cm-preset title="start from a preset"><option value="">preset&hellip;</option></select>' +
      '<button class=cm-read title="read a Vision colormap file (e.g. rgb256_map.py)">read&hellip;</button>' +
      '<button class=cm-write title="write a Vision colormap file">write&hellip;</button></div>' +
      '<div class="cm-msg dim"></div>';
    const $$ = s => box.querySelector(s);
    const bar = $$('.cm-bar'), curve = $$('.cm-curve'), msg = $$('.cm-msg');
    let cur = null, chans = null;
    const toChans = () => { chans = cur.ramp.map(c => toMode(st.mode, c).concat([c[3]])); };
    const fromChans = (i0, i1) => {
      for(let i = i0; i <= i1; i++){ const x = chans[i], c = fromMode(st.mode, x); cur.ramp[i] = [c[0], c[1], c[2], x[3]]; }
    };
    const value = () => ({ramp: cur.ramp.map(c => c.map(x => Math.round(Math.max(0, Math.min(1, x)) * 1e4) / 1e4)),
                          mini: cur.mini, maxi: cur.maxi, name: cur.name || undefined});
    const send = () => ctx.change(value(), true);
    const live = throttled(send, 200);
    const remember = () => { st.hist.push(cmCopy(cur)); if(st.hist.length > 60) st.hist.splice(1, 1); };
    const LINE = {RGB: ['#d33', '#2a2', '#36d'], HSV: ['#c3c', '#d80', '#555'], HSL: ['#c3c', '#d80', '#555']};
    function draw(){
      cmBar(bar, cur.ramp);
      const g = curve.getContext('2d'), W = curve.width, H = curve.height, n = cur.ramp.length;
      g.clearRect(0, 0, W, H);
      g.fillStyle = 'rgba(128,128,128,0.08)'; g.fillRect(0, 0, W, H);
      g.strokeStyle = 'rgba(128,128,128,0.35)'; g.lineWidth = 1;
      [0.25, 0.5, 0.75].forEach(f => { g.beginPath(); g.moveTo(0, H * f); g.lineTo(W, H * f); g.stroke(); });
      const X = i => (i + 0.5) / n * W, Y = v => H - 3 - v * (H - 6);
      const cols = LINE[st.mode].concat(['#888']);
      [0, 1, 2, 3].sort((a, b) => (a === st.ch) - (b === st.ch)).forEach(k => {
        g.beginPath();
        for(let i = 0; i < n; i++){ const y = Y(chans[i][k]); i ? g.lineTo(X(i), y) : g.moveTo(X(i), y); }
        g.strokeStyle = cols[k]; g.globalAlpha = k === st.ch ? 1 : 0.3; g.lineWidth = k === st.ch ? 2 : 1;
        g.stroke(); g.globalAlpha = 1;
      });
      // the last point: where a Shift-click segment starts
      if(st.anchor){
        const [f, v] = st.anchor;
        g.beginPath(); g.arc(X(Math.round(f * (n - 1))), Y(v), 4, 0, 2 * Math.PI);
        g.lineWidth = 2; g.strokeStyle = cols[st.ch]; g.fillStyle = 'rgba(255,255,255,0.85)'; g.fill(); g.stroke();
      }
    }
    function chButtons(){
      const names = CM_MODES[st.mode].concat(['opacity']);
      $$('.cm-chs').innerHTML = names.map((nm, k) => '<button data-ch=' + k + (k === st.ch ? ' class=on' : '') + '>' + nm + '</button>').join('');
    }
    function load(cm, push){
      if(push && cur) remember();
      cur = cm; toChans(); draw();
      $$('.cm-min').value = cur.mini == null ? '' : cur.mini;
      $$('.cm-max').value = cur.maxi == null ? '' : cur.maxi;
      $$('.cm-name').value = cur.name || '';
    }
    $$('.cm-mode').value = st.mode;
    chButtons();
    cmResolve(spec.value).then(cm => { load(cm, false); if(!st.hist.length) st.hist.push(cmCopy(cm)); });
    cmPresets().then(list => {
      const sel = $$('.cm-preset');
      list.forEach(p => { const o = el('option', {value: p.name}); o.textContent = p.name + (p.from ? ' (' + p.from + ')' : ''); sel.append(o); });
    });
    $$('.cm-mode').addEventListener('change', e => { st.mode = e.target.value; chButtons(); toChans(); draw(); });
    $$('.cm-chs').addEventListener('click', e => {
      const b = e.target.closest('button'); if(!b) return;
      st.ch = +b.dataset.ch; chButtons(); draw();
    });
    // drawing on the curves
    const pos = e => {
      const r = curve.getBoundingClientRect(), n = cur.ramp.length;
      const i = Math.max(0, Math.min(n - 1, Math.floor((e.clientX - r.left) / r.width * n)));
      const v = 1 - ((e.clientY - r.top) / r.height * curve.height - 3) / (curve.height - 6);
      return [i, Math.max(0, Math.min(1, v))];
    };
    curve.addEventListener('contextmenu', e => { e.preventDefault(); e.stopPropagation(); });
    curve.addEventListener('pointerdown', e => {
      if(!cur) return;
      e.preventDefault(); e.stopPropagation();
      curve.setPointerCapture(e.pointerId);
      remember();
      if(cur.ramp.length < 64){ cur.ramp = resampleRamp(cur.ramp, 128); toChans(); }
      dragging = true;
      const n = cur.ramp.length, ch = st.ch, start = pos(e), snap = chans.map(c => c.slice());
      const toI = f => Math.max(0, Math.min(n - 1, Math.round(f * (n - 1))));
      const fromI = p => [p[0] / (n - 1), p[1]];
      // a straight line: from where the right button went down, or (Shift) from the last point
      const lineFrom = e.button === 2 ? start
        : (e.shiftKey && st.anchor ? [toI(st.anchor[0]), st.anchor[1]] : null);
      const right = !!lineFrom;
      let last = start, end = start;
      const paint = (a, b) => {
        let [i0, v0] = a, [i1, v1] = b;
        if(i0 > i1){ [i0, i1] = [i1, i0]; [v0, v1] = [v1, v0]; }
        for(let i = i0; i <= i1; i++) chans[i][ch] = i1 === i0 ? v1 : v0 + (v1 - v0) * (i - i0) / (i1 - i0);
        fromChans(i0, i1);
      };
      if(right) paint(lineFrom, start);
      else paint(start, start);
      draw();
      const move = ev => {
        const p = pos(ev);
        end = p;
        if(right){ chans = snap.map(c => c.slice()); fromChans(0, chans.length - 1); paint(lineFrom, p); }
        else { paint(last, p); last = p; }
        draw();
        if($$('.cm-cont').checked) live();
      };
      const up = () => {
        curve.removeEventListener('pointermove', move); curve.removeEventListener('pointerup', up);
        dragging = false; busyUntil = performance.now() + 400;
        st.anchor = fromI(end);                       // the next Shift-click starts here
        draw();
        send();
      };
      curve.addEventListener('pointermove', move); curve.addEventListener('pointerup', up);
    });
    curve.addEventListener('keydown', e => {
      if((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z'){ e.preventDefault(); $$('.cm-undo').click(); }
    });
    const num = v => v === '' ? null : +v;
    $$('.cm-min').addEventListener('change', e => { remember(); cur.mini = num(e.target.value); send(); });
    $$('.cm-max').addEventListener('change', e => { remember(); cur.maxi = num(e.target.value); send(); });
    $$('.cm-name').addEventListener('change', e => { cur.name = e.target.value; send(); });
    $$('.cm-preset').addEventListener('change', async e => {
      const name = e.target.value; e.target.value = '';
      if(!name) return;
      const p = (await cmPresets()).find(x => x.name === name);
      if(!p) return;
      load({ramp: p.ramp.map(c => c.slice()), mini: cur.mini, maxi: cur.maxi, name}, true);
      send();
    });
    $$('.cm-undo').addEventListener('click', () => {
      if(!st.hist.length) return;
      // the state before the last change (the first one stays, for reset)
      const prev = st.hist.length > 1 ? st.hist.pop() : st.hist[0];
      load(cmCopy(prev), false); send();
    });
    $$('.cm-reset').addEventListener('click', () => { if(!st.hist.length) return; load(cmCopy(st.hist[0]), true); send(); });
    $$('.cm-read').addEventListener('click', async () => {
      if(!ctx.pickFile || !ctx.colormapFile) return;
      const path = await ctx.pickFile('file', '', {title: 'Read a Vision colormap file'});
      if(!path) return;
      const d = await ctx.colormapFile('read', path);
      if(!d || d.error) return;
      load(await cmResolve(d.colorMap), true); send();
      msg.textContent = 'read ' + path;
    });
    $$('.cm-write').addEventListener('click', async () => {
      if(!ctx.pickFile || !ctx.colormapFile) return;
      const path = await ctx.pickFile('filesave', '', {title: 'Write a Vision colormap file (name_map.py)'});
      if(!path) return;
      const d = await ctx.colormapFile('write', path, value());
      if(d && !d.error) msg.textContent = 'wrote ' + d.path;
    });
    return box;
  }

  function json(spec, ctx){
    const inp = el('input', {type: 'text', spellcheck: 'false',
                             title: 'widget ' + spec.class + ' is shown as a value (JSON)'});
    inp.value = JSON.stringify(spec.value);
    inp.addEventListener('change', () => {
      let v = inp.value;
      try { v = JSON.parse(inp.value); } catch(e) {}
      ctx.change(v, true);
    });
    return inp;
  }

  const KINDS = {number, entry, checkbox, button, combo, file, dir: file, filesave: file,
                 text, vector, xyzvect, color, multicheck, colormap, json};

  /* render(spec, ctx) -> HTMLElement. ctx: {change(value, run), pickFile(kind,
     current, options) -> Promise<path|null>, upload() -> Promise<path|null>,
     compact: true inside a node} */
  function render(spec, ctx){
    const fn = KINDS[spec.kind] || json;
    const e = fn(spec, ctx);
    e.addEventListener('pointerdown', ev => ev.stopPropagation());
    e.addEventListener('keydown', ev => ev.stopPropagation());
    return e;
  }

  return {render, esc, el, setReverse, isReversed: () => reverse, isBusy};
})();
