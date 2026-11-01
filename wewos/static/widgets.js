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
                 text, vector, xyzvect, color, multicheck, json};

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
