"""Portable project launcher; run with Python 3.12."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit('Use Python 3.12: python3.12 pipeline.py init, or py -3.12 pipeline.py init on Windows.')
    args = sys.argv[1:]
    if args and args[0] == 'host':
        sys.path.insert(0, str(ROOT / 'scripts'))
        import host_runtime
        return host_runtime.main(args[1:])
    if not args or args[0] in {'init', 'initialize'}:
        sys.path.insert(0, str(ROOT / 'scripts'))
        import initialize
        return initialize.main(args[1:] if args else [])
    executable = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not executable.is_file():
        raise SystemExit('Run Python 3.12 with pipeline.py init first.')
    script = {'queue': 'job_queue.py', 'rebuild-cache': 'rebuild_cache.py'}.get(args[0], 'production.py')
    if script != 'production.py': args = args[1:]
    command = [str(executable), '-B', str(ROOT / 'scripts' / script), *args]
    return subprocess.call(command, cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1'))

if __name__ == '__main__':
    raise SystemExit(main())
