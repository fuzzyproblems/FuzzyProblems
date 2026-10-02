"""Repeatable environment installation and empty operational initialization."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv
import host_runtime

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('Objectives', 'Textbooks', 'PastPapers', 'packs', 'output', 'work',
               'foundation/sources', 'foundation/curriculum', 'foundation/intake',
               'foundation/intake-cache', 'foundation/library/entries',
               'foundation/reviews', 'foundation/preferences')
INITIAL = {
    'foundation/sources/sources.json': [],
    'foundation/sources/files.json': [],
    'foundation/curriculum/objective_register.json': {'lessons': [], 'entries': []},
    'foundation/curriculum/curriculum_blueprint.json': {'objective_plans': [], 'relationship_edges': []},
    'foundation/intake/units.json': {},
    'foundation/intake/styles.json': {},
}

def safe(relative):
    path = ROOT / relative
    for part in [path, *path.parents]:
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('Use regular project directories: ' + str(relative))
        if part == ROOT: break
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError('Path escapes the project')
    return path

def create_initial(host=None):
    host_runtime.configuration(ROOT, host)
    for name in DIRECTORIES: safe(name).mkdir(parents=True, exist_ok=True)
    for name, value in INITIAL.items():
        path = safe(name)
        try:
            with path.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        except FileExistsError:
            json.loads(path.read_text(encoding='utf-8'))
    # A configuration choice belongs to the recipient and is never overwritten.
    config = safe('pipeline-config.json')
    if not config.exists():
        with config.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write((ROOT / 'pipeline-config.example.json').read_text(encoding='utf-8'))
    host_runtime.select(ROOT, host)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-install', action='store_true', help='Check an already installed environment without downloading')
    parser.add_argument('--wheelhouse', type=Path, help='Use a local directory of dependency wheels without network access')
    parser.add_argument('--host', choices=host_runtime.HOSTS, help='Select a host without resetting project or per-host settings')
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 12):
        parser.exit(1, 'Python 3.12 is required. Use python3.12 or the Windows py -3.12 launcher.\n')
    if platform.system() not in {'Darwin', 'Windows', 'Linux'}:
        parser.exit(1, 'Supported operating systems: macOS, Windows and Linux.\n')
    try:
        host_runtime.configuration(ROOT, args.host)
    except ValueError as error:
        parser.exit(2, str(error) + '\n')
    safe('.venv')
    executable = safe('.venv/' + ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
    if not executable.is_file():
        if args.no_install: parser.exit(1, 'Environment missing; run init without --no-install.\n')
        if (ROOT / '.venv').exists():
            parser.exit(1, 'Incomplete .venv: move that environment aside and rerun init. Inputs and working data are separate.\n')
        venv.EnvBuilder(with_pip=True, symlinks=False).create(ROOT / '.venv')
    pins = [line for line in (ROOT / 'requirements.txt').read_text().splitlines() if line and not line.startswith('#')]
    probe = ('import importlib.metadata as m,sys; '
             'pins=' + repr(pins) + '; '
             'assert sys.version_info[:2]==(3,12); '
             'assert all(m.version(p.split("==")[0])==p.split("==")[1] for p in pins)')
    ready = subprocess.run([str(executable), '-c', probe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not ready:
        if args.no_install: parser.exit(1, 'Required dependencies are missing or differ; run init without --no-install.\n')
        command = [str(executable), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(ROOT / 'requirements.txt')]
        if args.wheelhouse: command += ['--no-index', '--find-links', str(args.wheelhouse.resolve())]
        subprocess.run(command, check=True, cwd=ROOT)
    create_initial(args.host)
    result = subprocess.run([str(executable), '-B', str(ROOT / 'scripts/production.py'), 'doctor'], cwd=ROOT,
                            text=True, encoding='utf-8', capture_output=True, env=dict(os.environ, PYTHONUTF8='1'))
    if result.returncode:
        parser.exit(1, result.stdout + result.stderr)
    report = json.loads(result.stdout)
    if not report.get('production_runtime_ready'):
        parser.exit(1, 'Local runtime is incomplete; check Python 3.12, pinned dependencies and SQLite FTS5 with pipeline.py doctor.\n')
    print(json.dumps({'status': 'initialized', 'platform': platform.system(),
                      'runtime': report, 'host': host_runtime.describe(ROOT, args.host),
                      'codex_cli_available': bool(shutil.which('codex')),
                      'next': 'Supply PDFs in Objectives, Textbooks and optionally PastPapers. Follow START_HERE.md.'}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
