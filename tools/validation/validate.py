# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Check Vision networks in WEWoS: import, open, run, and compare every
output port with the same network run in MGLTools Vision 1.5.7.

    python tools/validation/validate.py NAME=GLOB [NAME=GLOB ...] \
        [--out DIR] [--mgl /path/to/mgl157] [--only SUBSTRING] [--jobs N]

Each network runs twice (WEWoS, Vision), each time in a bubblewrap sandbox:
the file system is read-only except the network's own scratch folder, which
holds copies of the files the network names, and there is no network
access. Results: DIR/<NAME>.csv (one row per network), DIR/<NAME>_ports.csv
(the ports that differ) and a summary on stdout.
"""
import argparse
import concurrent.futures
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from wewos.legacy.classmap import lookup, map_port  # noqa: E402
from wewos.legacy.importer import import_file  # noqa: E402

PY = os.path.realpath(sys.executable)
ENV = os.path.dirname(os.path.dirname(PY))
TIMEOUT = 300
MAXCOPY = 400e6          # bytes of data copied for one network


# ---- data the network reads ---------------------------------------------------
def _entries(netd):
    for e in netd.get('nodes', []):
        yield e
        if 'macro' in e:
            yield from _entries(e['macro'])


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def referenced(data, srcdir):
    """Relative paths, named by widgets, that exist next to the network."""
    out = set()
    for e in _entries(data['network']):
        for v in _strings(e.get('widgets') or {}):
            if '\n' in v or len(v) > 300 or not v.strip() or os.path.isabs(v):
                continue
            for cand in (v, os.path.dirname(re.split(r'[*?\[]', v)[0])):
                cand = os.path.normpath(cand) if cand else ''
                if cand and not cand.startswith('..') and cand != '.' \
                        and os.path.exists(os.path.join(srcdir, cand)):
                    out.add(cand)
                    break
    return sorted(out)


def _size(p):
    if os.path.isfile(p):
        return os.path.getsize(p)
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)


def stage(files, srcdir, dst):
    os.makedirs(dst)
    for d in ('.home', '.tmp', '.mpl'):
        os.makedirs(os.path.join(dst, d))
    total, skipped = 0, []
    for f in files:
        s = os.path.join(srcdir, f)
        n = _size(s)
        if total + n > MAXCOPY:
            skipped.append(f)
            continue
        total += n
        t = os.path.join(dst, f)
        os.makedirs(os.path.dirname(t) or dst, exist_ok=True)
        (shutil.copytree if os.path.isdir(s) else shutil.copy)(s, t)
    return skipped


# ---- running in the sandbox ---------------------------------------------------
DISPLAY = os.environ.get('VALIDATE_DISPLAY', '')    # a virtual X display for Vision


def sandbox(cmd, wdir, env):
    b = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
         '--unshare-net', '--die-with-parent', '--bind', wdir, wdir, '--chdir', wdir,
         '--unsetenv', 'DISPLAY']
    for k, v in env.items():
        b += ['--setenv', k, v]
    return b + cmd


def common_env(wdir):
    return {'HOME': os.path.join(wdir, '.home'), 'TMPDIR': os.path.join(wdir, '.tmp'),
            'MPLCONFIGDIR': os.path.join(wdir, '.mpl'), 'MPLBACKEND': 'Agg'}


def run_side(side, src, wdir, mgl):
    out = os.path.join(wdir, '.dump')
    env = common_env(wdir)
    if side == 'wewos':
        env.update({'PATH': os.path.join(ENV, 'bin') + ':' + os.environ.get('PATH', ''),
                    'ADS_ROOT': ENV, 'PYTHONNOUSERSITE': 'disable', 'PYTHONPATH': ROOT,
                    'LD_LIBRARY_PATH': os.environ.get('LD_LIBRARY_PATH', '') + ':' +
                    os.path.join(ENV, 'lib')})
        cmd = [PY, os.path.join(HERE, 'run_wewos.py'), src, wdir, out]
    else:
        cmd = [os.path.join(mgl, 'bin', 'pythonsh'), os.path.join(HERE, 'run_vision.py'),
               src, wdir, out]
        if DISPLAY:
            env['DISPLAY'] = DISPLAY
    try:
        p = subprocess.run(sandbox(cmd, wdir, env), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=TIMEOUT)
        log = p.stdout.decode('utf-8', 'replace')
    except subprocess.TimeoutExpired as e:
        log = (e.stdout or b'').decode('utf-8', 'replace') + '\nTIMEOUT'
    with open(os.path.join(wdir, '.run.log'), 'w') as fh:
        fh.write(log)
    meta, arrays = None, {}
    if os.path.exists(out + '.json'):
        with open(out + '.json') as fh:
            meta = json.load(fh)
        if os.path.exists(out + '.npz'):
            z = numpy.load(out + '.npz')
            arrays = {k: z['a%d' % i] for i, k in enumerate(meta['arrays'])}
    return meta, arrays, log


# ---- comparing ------------------------------------------------------------------
def same_array(a, b):
    if a.ndim == 2 and b.ndim == 2 and len(a) == len(b) and \
            sorted((a.shape[1], b.shape[1])) == [3, 4]:
        four = a if a.shape[1] == 4 else b                # RGBA and RGB colors
        if numpy.allclose(four[:, 3], 1):
            a, b = a[:, :3], b[:, :3]
    if a.shape != b.shape:
        if a.size == b.size and a.size:
            a, b = a.reshape(-1), b.reshape(-1)
        else:
            return None
    tol = dict(rtol=1e-4, atol=1e-6, equal_nan=True)
    if numpy.allclose(a, b, **tol):
        return 'equal'
    if a.ndim == 3 and a.shape[2] in (3, 4) and numpy.abs(a - b).max() <= 1:
        return 'equal'          # images: rounding of one level
    if a.ndim == 2 and len(a):
        sa = a[numpy.lexsort(a.T[::-1])]
        sb = b[numpy.lexsort(b.T[::-1])]
        if numpy.allclose(sa, sb, **tol):
            return 'equal'      # same rows, another order
    return None


def vision_to_wewos_key(key, vnodes):
    """Vision dump key 'node|port|sub' -> the WEWoS key, through the class
    map's port renames."""
    path, port, *rest = key.split('|')
    info = vnodes.get(path)
    if info:
        m = lookup(info['module'], info['class'])
        if m:
            port = map_port(m[3], port) or port
    return '|'.join([path, port] + rest)


def compare(v, va, w, wa, vdir='', wdir=''):
    """Counts of the output ports of the nodes that ran in both. vdir and
    wdir, the two work folders, are taken out of strings."""
    res = {'equal': 0, 'different': 0, 'only_vision': 0, 'not_compared': 0}
    diffs = []
    wnodes = w['wewos'].get('nodes', {}) if w else {}
    vkeys = {}
    for k in list(v['values']) + list(va):
        vkeys[vision_to_wewos_key(k, v['nodes'])] = k
    wkeys = set(w['values']) | set(wa)
    ports = {}
    for wk, vk in vkeys.items():
        path = wk.split('|')[0]
        node = wnodes.get(path)
        if node is None or node.get('placeholder') or node.get('below_placeholder'):
            continue
        port = '|'.join(wk.split('|')[:2])
        if wk not in wkeys:
            ports.setdefault(port, []).append('only_vision')
            continue
        a = va.get(vk, v['values'].get(vk))
        b = wa.get(wk, w['values'].get(wk))
        if isinstance(a, dict) or isinstance(b, dict):
            r = 'not_compared'
        elif isinstance(a, numpy.ndarray) and isinstance(b, numpy.ndarray):
            r = 'equal' if same_array(a, b) else 'different'
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            r = 'equal' if abs(a - b) <= 1e-6 + 1e-4 * abs(a) else 'different'
        elif isinstance(a, str) and isinstance(b, str):
            a2 = a.replace(vdir, '$WORK') if vdir else a
            b2 = b.replace(wdir, '$WORK') if wdir else b
            r = 'equal' if a2.strip() == b2.strip() else 'different'
        else:
            r = 'different'
        ports.setdefault(port, []).append(r)
        if r == 'different':
            diffs.append((wk, _short(a), _short(b), _maxdiff(a, b)))
    for port, rs in ports.items():
        if 'different' in rs:
            res['different'] += 1
        elif 'only_vision' in rs and 'equal' not in rs:
            res['only_vision'] += 1
        elif all(r == 'not_compared' for r in rs):
            res['not_compared'] += 1
        else:
            res['equal'] += 1
    return res, diffs


def _maxdiff(a, b):
    try:
        if isinstance(a, numpy.ndarray) and isinstance(b, numpy.ndarray):
            if a.shape != b.shape:
                return 'shapes %s %s' % (a.shape, b.shape)
            return '%.3g' % numpy.nanmax(numpy.abs(a - b))
        return '%.3g' % abs(a - b)
    except Exception:
        return ''


def _short(x):
    if isinstance(x, numpy.ndarray):
        return 'array%s %s' % (x.shape, numpy.array2string(x.reshape(-1)[:6], precision=4))
    return repr(x)[:120]


# ---- one network -----------------------------------------------------------------
def header(src):
    """Date of the Vision header, as the file gives it."""
    with open(src, 'rb') as fh:
        head = fh.read(2000).decode('latin-1')
    m = re.search(r'generated by vision\s*\n#\s*(.+?)\s*\n', head)
    return m.group(1).strip() if m else ''


def outcome(nodes):
    """How the run went, without the nodes below placeholders and those
    that need a page."""
    err, notrun = [], []
    for path, e in nodes.items():
        if e.get('placeholder') or e.get('below_placeholder') or e.get('needs_page'):
            continue
        if e['status'] == 'error':
            err.append(path)
        elif e['status'] not in ('done',):
            notrun.append(path)
    return err, notrun


def one(collection, src, base, mgl):
    name = os.path.basename(src)[:-len('_net.py')] if src.endswith('_net.py') \
        else os.path.basename(src)
    row = {'collection': collection, 'network': name, 'date': header(src)}
    try:
        data, report = import_file(src)
        row['imported'] = 1
    except Exception as e:
        row.update(imported=0, note='import failed: %s' % e)
        return row, []
    srcdir = os.path.dirname(os.path.abspath(src))
    files = referenced(data, srcdir)
    work = os.path.join(base, collection, name)
    shutil.rmtree(work, ignore_errors=True)
    sides = {}
    for side in ('wewos', 'vision'):
        wdir = os.path.join(work, side)
        skipped = stage(files, srcdir, wdir)
        if skipped:
            row['note'] = 'not copied (too large): %s' % ', '.join(skipped)
        sides[side] = run_side(side, os.path.abspath(src), wdir, mgl)
    w, wa, wlog = sides['wewos']
    v, va, vlog = sides['vision']
    if not w or 'wewos' not in w:
        opened = os.path.exists(os.path.join(work, 'wewos', '.dump.opened'))
        row['opened'] = int(opened)
        if 'TIMEOUT' in wlog:
            row['category'] = 'endless (also in Vision)' if 'TIMEOUT' in vlog else 'timeout'
        else:
            row['category'] = 'did not open' if not opened else 'crashed'
        row['note'] = (row.get('note', '') + ' wewos: ' + wlog.strip()[-200:]).strip()
        return row, []
    r = w['wewos']
    nodes = r.get('nodes', {})
    row['opened'] = int(r['stage'] in ('run', 'ran'))
    row['nodes'] = len(nodes)
    row['placeholders'] = sum(1 for e in nodes.values() if e.get('placeholder'))
    row['below_placeholders'] = sum(1 for e in nodes.values()
                                    if e.get('below_placeholder') and not e.get('placeholder'))
    row['needs_page'] = sum(1 for e in nodes.values() if e.get('needs_page'))
    unported = sorted({(e['placeholder'].get('module') or '?').split('.')[0]
                       for e in nodes.values() if e.get('placeholder')})
    row['unported'] = ' '.join(unported)
    err, notrun = outcome(nodes)
    row['errors'] = len(err)
    row['not_run'] = len(notrun)
    if err:
        first = nodes[err[0]].get('error', '').strip().splitlines()
        row['first_error'] = '%s: %s' % (err[0], first[-1] if first else '')
    if notrun:
        row['first_not_run'] = '%s (%s)' % (notrun[0], nodes[notrun[0]]['status'])
    row['wewos_run_s'] = round(r.get('seconds', {}).get('run', 0), 2)
    if r.get('exception'):
        row['note'] = (row.get('note', '') + ' exception: ' +
                       r['exception'].strip().splitlines()[-1]).strip()
    # Vision
    if not v or 'vision' not in v:
        row['vision'] = 'no dump: ' + vlog.strip().splitlines()[-1][:200] if vlog.strip() else 'no dump'
        row['category'] = ('endless in Vision' if 'TIMEOUT' in vlog else 'no Vision reference') + \
            ('' if not (err or notrun) else ', fails here')
        return row, []
    vr = v['vision']
    row['vision'] = vr['stage'] + (': ' + vr['exception'].strip().splitlines()[-1][:200]
                                   if vr.get('exception') else '')
    counts, diffs = compare(v, va, w, wa, os.path.join(work, 'vision'), os.path.join(work, 'wewos'))
    row.update(('ports_' + k, n) for k, n in counts.items())
    # the nodes that did not run here: did they give anything in Vision?
    # (a Vision Viewer node outputs its viewer when it is made, without running)
    vpaths = {k.split('|')[0] for k in list(v['values']) + list(va)
              if v['nodes'].get(k.split('|')[0], {}).get('class') != 'Viewer'}
    bad = err + notrun
    also = [p for p in bad if p not in vpaths]
    row['failed_in_vision_too'] = len(also)
    row['category'] = category(row, nodes, err, bad, also)
    return row, [(collection, name) + d for d in diffs]


def category(row, nodes, err, bad, also):
    ph = ' (placeholders)' if row.get('placeholders') else ''
    if not bad:
        return 'ran' + ph
    text = ' '.join(nodes[p].get('error', '') for p in err)
    if len(also) == len(bad):
        if 'No such file' in text or 'FileNotFound' in text or "does't exist" in text:
            return 'data file missing (also in Vision)' + ph
        return 'fails in Vision too' + ph
    if 'No such file' in text or 'FileNotFound' in text:
        return 'data file missing' + ph
    return 'differs from Vision' + ph


FIELDS = ['collection', 'network', 'date', 'imported', 'opened', 'nodes', 'placeholders',
          'below_placeholders', 'needs_page', 'unported', 'errors', 'not_run', 'first_error',
          'first_not_run', 'wewos_run_s', 'vision', 'ports_equal', 'ports_different',
          'ports_only_vision', 'ports_not_compared', 'failed_in_vision_too', 'category', 'note']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('collections', nargs='+', help='NAME=GLOB')
    ap.add_argument('--out', default=os.path.join(HERE, 'results'))
    ap.add_argument('--mgl', default=os.path.expanduser('~/tools/mgl157'))
    ap.add_argument('--only', default='')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--work', default='')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    base = a.work or tempfile.mkdtemp(prefix='wewos-validate-')
    for spec in a.collections:
        cname, pattern = spec.split('=', 1)
        srcs = sorted(f for f in glob.glob(pattern, recursive=True) if a.only in f)
        rows, diffs = [], []
        with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
            for row, d in ex.map(lambda s: one(cname, s, base, a.mgl), srcs):
                rows.append(row)
                diffs += d
                print('%-12s %-28s %s' % (cname, row['network'], ' '.join(
                    '%s=%s' % (k, row[k]) for k in FIELDS[3:] if row.get(k) not in (None, '', 0)
                    and k not in ('date',))), flush=True)
        with open(os.path.join(a.out, cname + '.csv'), 'w', newline='') as fh:
            wr = csv.DictWriter(fh, FIELDS)
            wr.writeheader()
            wr.writerows(rows)
        with open(os.path.join(a.out, cname + '_ports.csv'), 'w', newline='') as fh:
            wr = csv.writer(fh)
            wr.writerow(['collection', 'network', 'port', 'vision', 'wewos', 'max_abs_diff'])
            wr.writerows(diffs)
        summary(cname, rows)
    print('work folders in', base)


def summary(cname, rows):
    n = len(rows)
    imp = sum(r.get('imported', 0) for r in rows)
    op = sum(r.get('opened', 0) for r in rows)
    clean = sum(1 for r in rows if r.get('opened') and not r.get('errors') and not r.get('not_run')
                and not r.get('placeholders'))
    ph = sum(1 for r in rows if r.get('placeholders'))
    eq = sum(r.get('ports_equal', 0) for r in rows)
    df = sum(r.get('ports_different', 0) for r in rows)
    print('== %s: %d networks, %d imported, %d opened, %d ran every node, %d with placeholders; '
          'ports equal %d, different %d' % (cname, n, imp, op, clean, ph, eq, df))
    import collections
    for k, c in sorted(collections.Counter(r.get('category', '?') for r in rows).items()):
        print('   %-45s %d' % (k, c))


if __name__ == '__main__':
    main()
