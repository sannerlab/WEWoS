# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""The ported NetworkEditor engine: scheduling, data flow, types, macros."""
import threading
import time

from common import Add, Record, Value, check, eq, net, std

from wewos.engine import MacroNode, Network, NetworkNode, Runner


def test_soft_and_hard_run():
    a, b, s, r = Value('a'), Value('b'), Add(), Record()
    n = net(a, b, s, r)
    n.connectNodes(a, s, 'out', 'a')
    n.connectNodes(b, s, 'out', 'b')
    n.connectNodes(s, r, 'sum', 'x')
    eq([x.name for x in n.rootNodes], ['a', 'b'])
    n.run()                                 # soft run: widgets hold new data
    eq(r.got, [2.0])
    n.run()                                 # nothing new: nothing runs
    eq(r.got, [2.0])
    n.run(n.rootNodes)                      # hard run
    eq(r.got, [2.0, 2.0])
    a.inputPorts[0].widget.set(5)           # schedules a's subtree
    eq(r.got, [2.0, 2.0, 6.0])


def test_breadth_first_waits_for_all_parents():
    Record.LOG[:] = []
    src = Value('src')
    r1, r2, r3 = Record('r1'), Record('r2'), Record('r3')
    join = Add('join')
    n = net(src, r1, r2, r3, join)
    n.connectNodes(src, r1, 'out', 'x')
    n.connectNodes(r1, r2, 'out', 'x')
    n.connectNodes(r2, join, 'out', 'a')
    n.connectNodes(src, join, 'out', 'b')
    n.connectNodes(join, r3, 'sum', 'x')
    Record.LOG[:] = []
    order = [x.name for x in n.getAllNodes([src])]
    eq(order, ['src', 'r1', 'r2', 'join', 'r3'])
    n.run([src])
    eq(Record.LOG, ['r1', 'r2', 'r3'])
    eq(r3.got[-1], 2.0)


def test_non_blocking_connection_keeps_root():
    a, r = Value('a'), Record()
    n = net(a, r)
    n.connectNodes(a, r, 'out', 'x', blocking=False)
    check(r in n.rootNodes, 'child of a non blocking connection stays a root')


def test_stop_prunes_descendants():
    class Stopper(NetworkNode):
        def __init__(self, name='stopper', **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.inputPortsDescr.append(datatype='None', name='x')
            self.outputPortsDescr.append(datatype='None', name='out')
            self.setFunction("def doit(self, x):\n    return 'Stop'\n")
    a, s, r = Value('a'), Stopper(), Record()
    n = net(a, s, r)
    n.connectNodes(a, s, 'out', 'x')
    n.connectNodes(s, r, 'out', 'x')
    n.run([a])
    eq(r.got, [])
    eq(s.status, 'stopped')


def test_missing_required_input_stops():
    s, r = Add(), Record()
    n = net(s, r)
    n.connectNodes(s, r, 'sum', 'x')
    n.run([s])
    eq(r.got, [])


def test_single_connection_modes():
    class Multi(NetworkNode):
        def __init__(self, name='multi', mode=False, **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.inputPortsDescr.append(datatype='None', name='x', singleConnection=mode)
            self.outputPortsDescr.append(datatype='None', name='out')
            self.got = None
            self.setFunction("def doit(self, x):\n    self.got = x\n")
    a, b = Value('a'), Value('b')
    m, auto = Multi(mode=False), Multi('auto', mode='auto')
    n = net(a, b, m, auto)
    n.connectNodes(a, m, 'out', 'x')
    n.connectNodes(b, m, 'out', 'x')
    n.connectNodes(a, auto, 'out', 'x')
    n.run(n.rootNodes)
    eq(m.got, [1.0, 1.0])
    eq(auto.got, 1.0)
    try:
        n.connectNodes(a, Add(), 'out', 'a')
    except ValueError:
        pass
    s = Add('s')
    n.addNode(s)
    n.connectNodes(a, s, 'out', 'a')
    try:
        n.connectNodes(b, s, 'out', 'a')
        raise AssertionError('a single connection port took two parents')
    except ValueError:
        pass


def test_types_validate_and_cast():
    class Coords(NetworkNode):
        def __init__(self, name='coords', **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.inputPortsDescr.append(datatype='coord3(0)', name='xyz')
            self.got = None
            self.setFunction("def doit(self, xyz):\n    self.got = xyz\n")

    class Src(NetworkNode):
        def __init__(self, name='src', value=None, **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.value = value
            self.outputPortsDescr.append(datatype='None', name='out')
            self.setFunction("def doit(self):\n    self.outputData(out=self.value)\n")
    one = Src(value=[1, 2, 3])               # a single vertex: missing leading dim
    many = Src('many', value=[[0, 0, 0], [1, 1, 1]])
    bad = Src('bad', value=[[1, 2]])
    c1, c2, c3 = Coords('c1'), Coords('c2'), Coords('c3')
    n = net(one, many, bad, c1, c2, c3)
    n.connectNodes(one, c1, 'out', 'xyz')
    n.connectNodes(many, c2, 'out', 'xyz')
    n.connectNodes(bad, c3, 'out', 'xyz')
    n.run(n.rootNodes)
    eq(c1.got, [[1, 2, 3]])
    eq(c2.got, [[0, 0, 0], [1, 1, 1]])
    eq(c3.got, None)
    # float port casts an int
    a = Src('i', value=3)
    s = Add('s')
    n.addNode(a)
    n.addNode(s)
    r = Record('r')
    n.addNode(r)
    n.connectNodes(a, s, 'out', 'a')
    n.connectNodes(s, r, 'sum', 'x')
    n.run([a])
    check(isinstance(r.got[-1], float) and r.got[-1] == 3.0)


def test_widget_proxy_configure_emits():
    t = std('ThumbWheel')
    n = net(t)
    w = t.inputPorts[0].widget
    seq = n.bus.seq
    w.configure(min=2.0, max=4.0)
    evs = n.bus.since(seq)['events']
    check(any(e['kind'] == 'widget' and e['widget']['options']['min'] == 2.0 for e in evs))
    w.set(10, run=False)
    eq(w.get(), 4.0)
    w.set(1, run=False)
    eq(w.get(), 2.0)


def test_iterate_accumulate():
    rng, it, acc, r = std('range'), std('iterate'), std('accum'), Record()
    n = net(rng, it, acc, r)
    rng.inputPortByName['toInd'].widget.set(5, run=False)
    n.connectNodes(rng, it, 0, 'listToLoopOver')
    n.connectNodes(it, acc, 'oneItem', 'data')
    n.connectNodes(it, acc, 'begin', 'begin')
    n.connectNodes(it, acc, 'end', 'output')
    n.connectNodes(acc, r, 'listOfValues', 'x')
    r.got[:] = []
    n.run(n.rootNodes)
    eq(r.got[-1], [0, 1, 2, 3, 4])


def test_macro_dynamic_ports_and_run():
    a, b, r = Value('a'), Value('b'), Record()
    m = MacroNode('mac')
    n = net(a, b, m, r)
    mn = m.macroNetwork
    inner = Add('inner')
    mn.addNode(inner)
    mn.connectNodes(mn.ipNode, inner, 0, 'a')
    mn.connectNodes(mn.ipNode, inner, 0, 'b')
    mn.connectNodes(inner, mn.opNode, 'sum', 0)
    eq([p.name for p in m.inputPorts], ['inner_a', 'inner_b'])
    eq([p.name for p in m.outputPorts], ['inner_sum'])
    n.connectNodes(a, m, 'out', 'inner_a')
    n.connectNodes(b, m, 'out', 'inner_b')
    n.connectNodes(m, r, 'inner_sum', 'x')
    a.inputPorts[0].widget.set(3, run=False)
    r.got[:] = []
    n.run(n.rootNodes)
    eq(r.got[-1], 4.0)
    check(inner.id in n.nodesById and mn.ipNode.id in n.nodesById)


def test_node_error_reported():
    class Boom(NetworkNode):
        def __init__(self, name='boom', **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.setFunction("def doit(self):\n    raise RuntimeError('kaboom')\n")
    b = Boom()
    n = net(b)
    n.run([b])
    eq(b.status, 'error')
    check('kaboom' in b.lastError)
    evs = n.bus.since(0)['events']
    check(any(e['kind'] == 'node_status' and e['status'] == 'error' and 'kaboom' in e['error']
              for e in evs))


def test_set_code_compile_error_keeps_old():
    s = Add()
    old = s.dynamicComputeFunction
    try:
        s.setFunction('def doit(self, a, b)\n    pass\n')
        raise AssertionError('bad code accepted')
    except SyntaxError:
        pass
    check(s.dynamicComputeFunction is old)


def test_runner_stop_and_pause():
    class Slow(NetworkNode):
        def __init__(self, name='slow', **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.inputPortsDescr.append(datatype='None', name='x')
            self.outputPortsDescr.append(datatype='None', name='out')
            self.setFunction("def doit(self, x):\n    import time\n    time.sleep(0.05)\n"
                             "    self.outputData(out=x)\n")
    rng, it, s, r = std('range'), std('iterate'), Slow(), Record()
    n = net(rng, it, s, r)
    rng.inputPortByName['toInd'].widget.set(200, run=False)
    n.connectNodes(rng, it, 0, 'listToLoopOver')
    n.connectNodes(it, s, 'oneItem', 'x')
    n.connectNodes(s, r, 'out', 'x')
    n.runner = Runner()
    r.got[:] = []
    n.run(n.rootNodes)
    time.sleep(0.3)
    n.pause()
    eq(n.execStatus, 'pause')
    k = len(r.got)
    time.sleep(0.3)
    check(len(r.got) <= k + 1, 'paused run kept going')
    n.resume()
    time.sleep(0.2)
    n.stop()
    check(n.runner.wait(5), 'run did not stop')
    check(0 < len(r.got) < 200, 'stopped run ran %d items' % len(r.got))
    eq(n.execStatus, 'waiting')
    # a later run still works
    r.got[:] = []
    rng.inputPortByName['toInd'].widget.set(3, run=False)
    n.run(n.rootNodes)
    check(n.runner.wait(5))
    eq(len(r.got), 3)


def test_delete_node_and_connection():
    a, s, r = Value('a'), Add(), Record()
    n = net(a, s, r)
    c = n.connectNodes(a, s, 'out', 'a')
    n.connectNodes(s, r, 'sum', 'x')
    check(s not in n.rootNodes)
    n.deleteConnections([c])
    check(s in n.rootNodes)
    n.deleteNodes([s])
    eq(len(n.connections), 0)
    check(s.id not in n.nodesById)


def test_widget_unbind_on_connect_and_rebind():
    a = Value('a')
    t = std('range')
    n = net(a, t)
    p = t.inputPortByName['toInd']
    check(p.widget is not None)
    c = n.connectNodes(a, t, 'out', 'toInd')
    check(p.widget is None)
    n.deleteConnections([c])
    check(p.widget is not None, 'widget came back after disconnect')
    # a widget locked on its port refuses the connection
    tw = std('ThumbWheel')
    n.addNode(tw)
    try:
        n.connectNodes(a, tw, 'out', 'thumbwheel')
        raise AssertionError('locked widget was unbound')
    except ValueError:
        pass


def _shape(net):
    """A comparable summary of a network: nodes, widget values, connections."""
    from wewos.engine.macros import MacroNode
    out = []
    for n in net.nodes:
        w = {p.name: p.widget.get() for p in n.inputPorts if p.widget}
        item = (n.name, n.__class__.__name__, round(n.posx), round(n.posy), sorted(w.items()))
        if isinstance(n, MacroNode):
            item = item + (_shape(n.macroNetwork),)
        out.append(item)
    conns = sorted((c.port1.node.name, c.port1.name, c.port2.node.name, c.port2.name,
                    c.blocking) for c in net.connections)
    return out, conns


def test_save_load_round_trip():
    import os
    from common import outdir
    from wewos.engine import fileio
    rng, it, acc, pr = std('range'), std('iterate'), std('accum'), std('print')
    tw = std('ThumbWheel')
    m = MacroNode('mac')
    n = net(rng, it, acc, pr, tw, m)
    rng.inputPortByName['toInd'].widget.set(4, run=False)
    tw.inputPorts[0].widget.configure(min=-1.0, max=9.0)
    tw.inputPorts[0].widget.set(3.5, run=False)
    tw.move(123, 45)
    n.connectNodes(rng, it, 0, 'listToLoopOver')
    n.connectNodes(it, acc, 'oneItem', 'data')
    n.connectNodes(it, acc, 'begin', 'begin')
    n.connectNodes(it, acc, 'end', 'output')
    n.connectNodes(acc, pr, 'listOfValues', 'in1')
    mn = m.macroNetwork
    p = std('Pass')
    mn.addNode(p)
    mn.connectNodes(mn.ipNode, p, 0, 'in1')
    mn.connectNodes(p, mn.opNode, 'out1', 0)
    n.connectNodes(tw, m, 'value', m.inputPorts[0].name)
    pr.setFunction("def doit(self, in1):\n    print('custom', in1)\n")
    path = os.path.join(outdir('fileio'), 'rt.wnet.json')
    fileio.save(n, path)
    n2 = Network('loaded')
    report = fileio.load(n2, path)
    eq(report, [])
    eq(_shape(n2), _shape(n))
    pr2 = [x for x in n2.nodes if x.name == pr.name][0]
    check('custom' in pr2.sourceCode and pr2.codeModified)
    tw2 = [x for x in n2.nodes if x.name == tw.name][0]
    eq(tw2.inputPorts[0].widget.options['max'], 9.0)
    rng2 = [x for x in n2.nodes if x.name == rng.name][0]
    check('code' not in [e for e in fileio.to_dict(n2)['network']['nodes']
                         if e.get('name') == rng2.name][0], 'unchanged code was saved')


def test_load_unknown_node_gives_placeholder():
    from wewos.engine import fileio
    data = {'format': 'wewos-net', 'version': 1, 'network': {'nodes': [
        {'id': 'n1', 'lib': 'NoSuchLib', 'cls': 'Foo', 'name': 'foo', 'pos': [0, 0]},
        {'id': 'n2', 'lib': 'Standard', 'cls': 'Pass', 'label': 'Pass', 'name': 'p',
         'pos': [0, 50]}],
        'connections': [{'from': ['n1', 'out'], 'to': ['n2', 'in1'], 'blocking': True}]}}
    n = Network('x')
    report = fileio.from_dict(n, data)
    eq(len(n.nodes), 2)
    eq(n.nodes[0].__class__.__name__, 'UnsupportedNode')
    check(len(report) == 2, report)


def test_user_added_ports_update_signature_and_round_trip():
    import os
    from common import outdir
    from wewos.engine import fileio
    g = std('Generic')
    n = net(g)
    g.addInputPort(name='x', datatype='float')
    g.widgetDescr['k'] = {'class': 'NEThumbWheel', 'master': 'node', 'initialValue': 3.0}
    g.addInputPort(name='k', datatype='float')
    g.addOutputPort(name='y', datatype='float')
    check('def doit(self, x, k)' in g.sourceCode, g.sourceCode)
    g.setFunction("def doit(self, x, k):\n    self.outputData(y=x * k)\n")
    path = os.path.join(outdir('fileio'), 'ports.wnet.json')
    fileio.save(n, path)
    n2 = Network('x')
    eq(fileio.load(n2, path), [])
    g2 = n2.nodes[0]
    eq([p.name for p in g2.inputPorts], ['x', 'k'])
    eq(g2.inputPortByName['k'].widget.get(), 3.0)
    eq([p.name for p in g2.outputPorts], ['y'])
    check('x * k' in g2.sourceCode)
    g2.deletePort(g2.inputPortByName['k'])
    check('def doit(self, x)' in g2.sourceCode, g2.sourceCode)


def test_connection_closing_a_loop_is_non_blocking():
    a, b, c2 = Record('a'), Record('b'), Add('c2')
    n = net(a, b, c2)
    n.connectNodes(a, b, 'out', 'x')
    n.connectNodes(b, c2, 'out', 'a')
    back = n.connectNodes(c2, a, 'sum', 'x')      # c2 is downstream of a
    check(back.blocking is False, 'the loop-closing connection stayed blocking')
    check(a in n.rootNodes)
    order = [x.name for x in n.getAllNodes(list(n.rootNodes))]
    eq(order, ['a', 'b', 'c2'])


def test_stop_keeps_nodes_with_another_live_parent():
    class Stopper(NetworkNode):
        def __init__(self, name='stopper', **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.outputPortsDescr.append(datatype='None', name='out')
            self.setFunction("def doit(self):\n    return 'Stop'\n")

    class Collect(NetworkNode):
        def __init__(self, name='collect', **kw):
            kw['name'] = name
            NetworkNode.__init__(self, **kw)
            self.inputPortsDescr.append(datatype='None', name='items', required=False,
                                        singleConnection=False)
            self.got = None
            self.setFunction("def doit(self, items):\n    self.got = items\n")
    v, s, mid, col = Value('v'), Stopper(), Record('mid'), Collect()
    n = net(v, s, mid, col)
    n.connectNodes(s, mid, 'out', 'x')
    n.connectNodes(mid, col, 'out', 'items')
    n.connectNodes(v, col, 'out', 'items')
    mid.got[:] = []
    n.run(list(n.rootNodes))
    eq(mid.got, [])                      # starved: only parent stopped
    eq(col.got, [1.0])                   # runs with the parent that has data
