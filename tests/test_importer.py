# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Importing Vision *_net.py networks (tests/data holds a few real ones)."""
import os

from common import DATA, check, eq

from wewos.engine import Network, fileio
from wewos.legacy import importer, py2to3


def _load(name):
    data, report = importer.import_file(os.path.join(DATA, name))
    net = Network('imported')
    problems = fileio.from_dict(net, data)
    return net, data, report, problems


def test_cpk_net_maps_completely():
    net, data, report, problems = _load('cpk_net.py')
    eq(problems, [])
    eq(report.unmapped, [])
    eq(sorted(n.__class__.__name__ for n in net.nodes), ['AtomsAsCPK', 'ReadMolecule', 'Viewer'])
    eq(len(net.connections), 2)
    rd = [n for n in net.nodes if n.name == 'Read Molecule'][0]
    eq(rd.inputPortByName['filename'].widget.get(), 'cv.pdb')


def test_unsupported_nodes_become_placeholders():
    src = ('from NoSuchPackage.Nodes import mylib\n'
           'from NoSuchPackage.Nodes import Thing\n'
           'from Vision.StandardNodes import stdlib\n'
           'from Vision.StandardNodes import Pass\n'
           't = Thing(constrkw={}, name="thing", library=mylib)\n'
           'masterNet.addNode(t, 10, 10)\n'
           'p = Pass(constrkw={}, name="Pass", library=stdlib)\n'
           'masterNet.addNode(p, 10, 80)\n'
           'masterNet.connectNodes(t, p, "out", "in1", blocking=True)\n')
    data, report = importer.import_source(src, 'x_net.py')
    net = Network('imported')
    eq(fileio.from_dict(net, data), [])
    eq(len(report.unmapped), 1)
    eq([n.__class__.__name__ for n in net.nodes], ['UnsupportedNode', 'Pass'])
    eq(len(net.connections), 1)


def test_coraliso_imports_with_volume():
    net, data, report, problems = _load('coralIso_net.py')
    eq(problems, [])
    eq(report.unmapped, [])
    m = [n for n in net.nodes if n.__class__.__name__ == 'UT_Iso'][0]
    iso = m.macroNetwork.nodes[2]
    check(abs(iso.inputPortByName['isovalue'].widget.get() - 11.954) < 1e-3)


def test_generic_nodes_keep_ports_and_code():
    net, data, report, problems = _load('send-multiple-sin-packet_net.py')
    eq(problems, [])
    pp = [n for n in net.nodes if n.name == 'Packet Packer'][0]
    eq([p.name for p in pp.inputPorts], ['audio_data', 'data_sync_index', 'signal_amplitude'])
    eq([p.name for p in pp.outputPorts], ['out0'])
    check(pp.codeModified and 'def doit(self, audio_data' in pp.sourceCode)
    check('Packet Packer' in report.code)
    compile(pp.sourceCode, 'x', 'exec')        # converted to Python 3


def test_standard_network_runs_after_import():
    net, data, report, problems = _load('loop_net.py')
    eq(problems, [])
    w = [n for n in net.nodes if n.name == 'while'][0]
    eq(w.inputPortByName['condition'].widget.get(), 'val1==0.0')


def test_import_never_executes_the_file():
    src = ('import os\nos.system("touch SHOULD_NOT_EXIST")\n'
           'from Vision.StandardNodes import stdlib\n'
           'from Vision.StandardNodes import Pass\n'
           'p = Pass(constrkw={}, name="Pass", library=stdlib)\n'
           'masterNet.addNode(p, 10, 10)\n')
    data, report = importer.import_source(src, 'evil_net.py')
    check(not os.path.exists('SHOULD_NOT_EXIST'))
    eq(len(data['network']['nodes']), 1)


def test_py2_code_strings_converted():
    code = "def doit(self, x):\n\tprint x\n\tif d.has_key('a'): apply(f, (1,))\n"
    new, changed = py2to3.convert_code(code)
    check(changed)
    compile(new, 'x', 'exec')
    check("'a' in d" in new and 'print(x)' in new, new)
