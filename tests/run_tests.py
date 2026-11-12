# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Run the WEWoS tests (no pytest in the shared adcpsuite env).

    bin/wewos test [-k substr]     # or: <adcpsuite python> tests/run_tests.py

Outputs go to tests/_out/<timestamp>/ (git-ignored), never /tmp.
"""
import argparse
import importlib
import os
import sys
import time
import traceback
import warnings

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-k', default='', help='run tests whose name contains this')
    a = p.parse_args()
    mods = sorted(f[:-3] for f in os.listdir(HERE)
                  if f.startswith('test_') and f.endswith('.py'))
    failed = passed = skipped = 0
    import common
    for m in mods:
        mod = importlib.import_module(m)
        for name in sorted(n for n in dir(mod) if n.startswith('test_')):
            if a.k and a.k not in '%s.%s' % (m, name):
                continue
            t = time.time()
            try:
                getattr(mod, name)()
                passed += 1
                print('ok    %-55s %5.1fs' % ('%s.%s' % (m, name), time.time() - t), flush=True)
            except common.Skip as e:
                skipped += 1
                print('skip  %-55s (%s)' % ('%s.%s' % (m, name), e), flush=True)
            except Exception:
                failed += 1
                print('FAIL  %-55s %5.1fs' % ('%s.%s' % (m, name), time.time() - t), flush=True)
                traceback.print_exc()
    print('\n%d passed, %d skipped, %d failed   (outputs: %s)' % (passed, skipped, failed, common.OUT))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
