# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Lay out a network from left to right.

Vision drew data flowing down the page (inputs on top of nodes, outputs
below), and the macros of its libraries and its saved networks keep those
positions. WEWoS draws ports on the sides, so these networks are laid out
again: nodes go in columns by their depth in the graph (sources on the left,
the macro's output node on the right), each column is ordered to keep links
straight, and nodes are spaced by the sizes the page draws them at.

    arrange(net, source='vision')   # positions written for Vision
    arrange(net)                    # re-arrange a WEWoS network
"""
import math
import re


HEAD, ROW = 22, 22          # the page's node geometry (static/editor.js, layout())
SHORT = 12                  # longer port names are shown short in a node


def _tw(s, px):
    return len(str(s or '')) * px


def _cut_word(w, i):
    if i == 0:
        c = w[:4]
        if len(w) > 4 and c[-1:].lower() in 'aeiou':
            c = c[:3]
        return c
    return w[0].upper() + w[1:3]


def _abbrev(s):
    """One name part cut short: its camelCase words, or its first letters."""
    if len(s) <= SHORT:
        return s
    words = [w for w in re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s).split(' ') if w]
    if len(words) < 2:
        return s[:SHORT - 1] + '…'
    return ''.join(_cut_word(w, i) for i, w in enumerate(words))


def _compact(parts):
    """Several parts, each kept when short, joined in camelCase."""
    out = []
    for i, p in enumerate(parts):
        q = p if len(p) <= 6 else _abbrev(p)
        out.append(q[0].upper() + q[1:] if i else q)
    return ''.join(out)


def short_name(name):
    """A port name as a node shows it (static/editor.js shortName): the longest
    tail of its "_" parts that fits, else its last part cut short."""
    name = str(name or '')
    if len(name) <= SHORT:
        return name
    parts = [p for p in name.split('_') if p]
    best = ''
    for k in range(1, len(parts) + 1):
        tail = '_'.join(parts[-k:])
        if len(tail) > SHORT:
            break
        best = tail
    if len(best) >= 4:
        return best
    if best:
        return _compact(parts[-2:])
    return _abbrev(parts[-1] if parts else name)


def short_names(names):
    """Short names of one side of a node, different from each other."""
    out = {n: short_name(n) for n in names}
    seen = {}
    for n in names:
        seen[out[n]] = seen.get(out[n], 0) + 1
    for n in names:
        if seen[out[n]] > 1 and out[n] != n:
            out[n] = _compact([p for p in n.split('_') if p])
    again = {}
    for n in names:
        s = out[n]
        again[s] = again.get(s, 0) + 1
        if again[s] > 1:
            out[n] = s + str(again[s])
    return out


def _number(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _number_chars(w):
    o = w.get('options') or {}
    vals = [x for x in (_number(v) for v in (w.get('value'), o.get('min'), o.get('max'))
                        if v is not None and v != '') if x is not None]
    n = max([1] + [len(str(int(abs(x)))) for x in vals])
    if any(x < 0 for x in vals):
        n += 1
    if o.get('type') != 'int':
        p = o.get('precision')
        n += 1 + min(3 if p is None else int(p), 3)
    return max(2, min(10, n))


def _text_chars(v, lo, hi):
    return max(lo, min(hi, len('' if v is None else str(v))))


def widget_width(w):
    """How wide a widget is drawn in a node (static/editor.js widgetW): the
    width the user chose (option nodeWidth), else what it holds needs."""
    w = w or {}
    o = w.get('options') or {}
    if o.get('nodeWidth'):
        return max(30, min(400, float(o['nodeWidth'])))
    kind = w.get('kind')
    if kind == 'number':
        return 38 + _number_chars(w) * 7
    if kind == 'checkbox':
        return 18
    if kind == 'entry':
        return 16 + _text_chars(w.get('value'), 4, 16) * 6.6
    if kind in ('file', 'dir', 'filesave'):
        return 38 + _text_chars(w.get('value'), 6, 18) * 6.6
    if kind == 'combo':
        values = list(o.get('choices') or []) + [w.get('value')]
        longest = max(len('' if c is None else str(c)) for c in values)
        return max(60, min(130, longest * 6.5 + 28))
    if kind == 'button':
        return min(120, _tw(o.get('text') or w.get('label') or 'press', 6.5) + 20)
    if kind == 'color':
        return 30
    if kind == 'colormap':
        return 124
    if kind == 'vector':
        return 110
    return 100


def node_geometry(d):
    """Width, height and port offsets of a node drawn by the page, from
    node.describe() (mirrors layout() in static/editor.js)."""
    rows = []
    for p in d.get('in') or []:
        w = p.get('widget')
        if not w:
            rows.append((p, 'port'))
        elif w.get('master') == 'node':
            rows.append((p, 'widget'))
    outs = d.get('out') or []
    in_short = short_names([p['name'] for p, k in rows])
    out_short = short_names([p['name'] for p in outs])
    in_w = 0
    for p, kind in rows:
        if kind == 'widget':
            w = p['widget']
            label = w.get('label') or in_short[p['name']]
            lw = 0 if w.get('label') == '' else min(_tw(label, 6), 70) + 4
            in_w = max(in_w, lw + widget_width(w))
        else:
            in_w = max(in_w, _tw(in_short[p['name']], 5.8) + 14)
    out_w = max([_tw(out_short[p['name']], 5.8) + 14 for p in outs] or [0])
    w = max(110, _tw(d.get('label') or d.get('name'), 7.2) + 34,
            in_w + out_w + (22 if outs and rows else 10))
    h = HEAD + max(len(rows), len(outs), 1) * ROW + 6 + (4 if d.get('progbar') else 0)
    ins = {p['name']: HEAD + i * ROW + ROW / 2.0 for i, (p, k) in enumerate(rows)}
    outp = {p['name']: HEAD + i * ROW + ROW / 2.0 for i, p in enumerate(outs)}
    return {'w': w, 'h': h, 'ins': ins, 'outs': outp}


def _pav(t):
    """Least-squares non-decreasing fit of t (pool adjacent violators)."""
    blocks = []
    for v in t:
        blocks.append([v, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    out = []
    for s, c in blocks:
        out.extend([s / c] * c)
    return out


def arrange(net, source='wewos', x0=40, y0=40, hgap=70, vgap=24, emit=True):
    """Give the nodes of net left-to-right positions. source='vision' when
    the current positions were made for Vision's top-down drawing (its
    horizontal order then orders the nodes of a column)."""
    nodes = list(net.nodes)
    if not nodes:
        return
    ip = getattr(net, 'ipNode', None)
    op = getattr(net, 'opNode', None)
    idx = {id(n): i for i, n in enumerate(nodes)}
    geo = {id(n): node_geometry(n.describe()) for n in nodes}
    if source == 'vision':
        key = {id(n): (n.posx, n.posy, idx[id(n)]) for n in nodes}
    else:
        key = {id(n): (n.posy, n.posx, idx[id(n)]) for n in nodes}

    # links: (parent, child, out port, in port), without the ones closing loops:
    # blocking links first, then those going forward in the current drawing
    # (down for Vision, right here); a link that would make a cycle is left out
    flow = (lambda n: n.posy) if source == 'vision' else (lambda n: n.posx)
    cands = []
    for c in net.connections:
        a, b = c.port1.node, c.port2.node
        if id(a) in idx and id(b) in idx and a is not b:
            cands.append((a, b, c.port1.name, c.port2.name, bool(c.blocking)))
    cands.sort(key=lambda l: (not l[4], flow(l[0]) - flow(l[1])))
    succ = {id(n): [] for n in nodes}

    def reaches(src, dst):
        stack, seen = [src], {id(src)}
        while stack:
            n = stack.pop()
            if n is dst:
                return True
            for ch in succ[id(n)]:
                if id(ch) not in seen:
                    seen.add(id(ch))
                    stack.append(ch)
        return False

    links = []
    for a, b, pa, pb, blocking in cands:
        if not reaches(b, a):
            succ[id(a)].append(b)
            links.append((a, b, pa, pb))
    parents = {id(n): [] for n in nodes}
    children = {id(n): [] for n in nodes}
    for l in links:
        parents[id(l[1])].append(l)
        children[id(l[0])].append(l)

    # columns: longest path from the sources; a source sits just before its
    # first child; the macro's input node is first and its output node last
    order, indeg = [], {id(n): len(parents[id(n)]) for n in nodes}
    ready = sorted([n for n in nodes if indeg[id(n)] == 0], key=lambda n: key[id(n)])
    while ready:
        n = ready.pop(0)
        order.append(n)
        for l in children[id(n)]:
            indeg[id(l[1])] -= 1
            if indeg[id(l[1])] == 0:
                ready.append(l[1])
    rank = {}
    for n in order:
        rank[id(n)] = max([rank[id(l[0])] + 1 for l in parents[id(n)]] or [0])
    for n in reversed(order):
        if not parents[id(n)] and children[id(n)] and n is not ip:
            rank[id(n)] = max(0, min(rank[id(l[1])] for l in children[id(n)]) - 1)
    if ip is not None and id(ip) in rank:
        rank[id(ip)] = 0
    if op is not None and id(op) in rank:
        others = [rank[id(n)] for n in nodes if n is not op]
        rank[id(op)] = max(rank[id(op)], (max(others) + 1) if others else 0)
    ncol = max(rank.values()) + 1
    cols = [[] for _ in range(ncol)]
    for n in nodes:
        cols[rank[id(n)]].append(n)

    # x: columns as wide as their widest node
    xs, x = [], x0
    for col in cols:
        xs.append(x)
        x += max([geo[id(n)]['w'] for n in col] or [0]) + hgap

    # y: each node where its links are straight, in order, without overlaps
    y = {}

    def wanted(n, use):
        g = geo[id(n)]
        vals = []
        if 'parents' in use:
            for a, b, pa, pb in parents[id(n)]:
                if id(a) in y:
                    ga = geo[id(a)]
                    vals.append(y[id(a)] + ga['outs'].get(pa, ga['h'] / 2.0)
                                - g['ins'].get(pb, g['h'] / 2.0))
        if 'children' in use:
            for a, b, pa, pb in children[id(n)]:
                if id(b) in y:
                    gb = geo[id(b)]
                    vals.append(y[id(b)] + gb['ins'].get(pb, gb['h'] / 2.0)
                                - g['outs'].get(pa, g['h'] / 2.0))
        return sum(vals) / len(vals) if vals else None

    def place(col, want):
        # nodes without a wish keep their place (or stack in key order)
        cur = sorted(col, key=lambda n: (y.get(id(n), float('inf')), key[id(n)]))
        stack, d = y0, {}
        for n in cur:
            d[id(n)] = y[id(n)] if id(n) in y else stack
            stack = d[id(n)] + geo[id(n)]['h'] + vgap
        for n in col:
            w = want.get(id(n))
            if w is not None:
                d[id(n)] = w
        seq = sorted(col, key=lambda n: (d[id(n)], key[id(n)]))
        offs, off = [], 0
        for n in seq:
            offs.append(off)
            off += geo[id(n)]['h'] + vgap
        fit = _pav([d[id(n)] - o for n, o in zip(seq, offs)])
        for n, o, f in zip(seq, offs, fit):
            y[id(n)] = f + o

    if cols[0]:
        place(cols[0], {})
    for c in range(1, ncol):
        place(cols[c], {id(n): wanted(n, ('parents',)) for n in cols[c]})
    for c in range(ncol - 1, -1, -1):
        place(cols[c], {id(n): wanted(n, ('children',)) for n in cols[c]
                        if not parents[id(n)] and children[id(n)]})
    for c in range(1, ncol):
        place(cols[c], {id(n): wanted(n, ('parents', 'children')) if parents[id(n)] else None
                        for n in cols[c]})

    top = min(y.values())
    for n in nodes:
        n.move(round(xs[rank[id(n)]]), round(y[id(n)] - top + y0))
        if emit:
            net.emit('node_moved', node=n.id, pos=[n.posx, n.posy])
