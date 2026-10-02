"""Standalone synthetic checks; no parent workspace, account or private inputs."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict',action='store_true',help='Require OCR and symlink coverage without skipped tests')
    args=parser.parse_args()
    import production
    runtime=production.doctor()
    if not runtime['production_runtime_ready']:
        parser.exit(1,'Use Python 3.12 with requirements.txt installed.\n')
    if args.strict and not runtime['ocr_runtime_ready']:
        parser.exit(1,'Strict checks require local Tesseract/language data; see PLATFORM_SUPPORT.md.\n')
    log=io.StringIO()
    with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py')
        result=unittest.TextTestRunner(stream=log).run(suite)
    if not result.wasSuccessful() or (args.strict and result.skipped):
        print(log.getvalue(),file=sys.stderr)
        return 1
    print(json.dumps({'status':'pass','platform':sys.platform,'unit_tests':result.testsRun,
        'skipped':[reason for _,reason in result.skipped],'synthetic_only':True,
        'educational_approval':False,'live_host_execution':False},indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
