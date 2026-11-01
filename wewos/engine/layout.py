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

HEAD, ROW = 22, 22          # the page's node geometry (static/editor.js, layout())
WIDGET_W = 150


def _tw(s, px):
    return len(str(s or '')) * px


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
    in_w = 0
    for p, kind in rows:
        if kind == 'widget':
            w = p['widget']
            in_w = max(in_w, min(_tw(w.get('label') or p['name'], 6), 70) + WIDGET_W)
        else:
            in_w = max(in_w, _tw(p['name'], 5.8) + 14)
    out_w = max([_tw(p['name'], 5.8) + 14 for p in outs] or [0])
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
