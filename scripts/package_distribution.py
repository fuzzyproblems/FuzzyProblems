"""Build a reusable release from an explicit file allowlist, never a working tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'distribution-files.json'
STAMP = (1980, 1, 1, 0, 0, 0)


def member_path(name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Distribution members must be safe relative paths.')
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name:
        raise ValueError('Distribution members must be normalized relative paths.')
    for part in path.parts:
        if (part in {'.', '..'} or part.endswith(('.', ' ')) or PureWindowsPath(part).is_reserved()
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
            raise ValueError('Distribution member is not portable.')
    return path


def regular(root, name):
    path = root / member_path(name)
    current = root
    for part in path.relative_to(root).parts:
        if not current.is_dir() or part not in {p.name for p in current.iterdir()}:
            raise ValueError('Missing or case-mismatched distribution file.')
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError('Distribution files must not use symlinks or junctions.')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Distribution allowlist requires regular files.')
    return path


def payload(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads(regular(root, MANIFEST).read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('Distribution file allowlist must contain an object.')
    files = manifest.get('files')
    if manifest.get('version') != 1 or not isinstance(files, list) or not files:
        raise ValueError('Unsupported or empty distribution file allowlist.')
    if len(files) != len({name.casefold() for name in files if isinstance(name, str)}):
        raise ValueError('Duplicate, invalid or case-colliding distribution member.')
    # Each file is explicitly selected. These structural families prevent a
    # mistaken manifest addition from distributing operational trees/configuration.
    top = {'AGENTS.md','CLAUDE.md','README.md','START_HERE.md','RUNBOOK.md',
           'PLATFORM_SUPPORT.md','.gitignore','.gitattributes',MANIFEST,
           'pipeline.py','regenerate_study_guide.py','requirements.txt',
           'requirements-test.txt','bootstrap-settings.json','pipeline-config.example.json'}
    result = {}
    directories = {}
    for name in files:
        path = member_path(name)
        parts = path.parts
        permitted = name in top or (
            len(parts) == 2 and parts[0] == 'scripts' and path.suffix == '.py') or (
            name == 'foundation/SPECIFICATION.md') or (
            len(parts) == 3 and parts[:2] in {('foundation','guidance'),('foundation','schemas'),
                ('foundation','library'),('foundation','ingestion')} and path.suffix in {'.md','.json'}) or (
            len(parts) == 5 and parts[0] in {'.agents','.claude'} and parts[1] == 'skills'
            and parts[2] in {'fuzzy-start','job-queue'} and parts[3:] == ('agents','openai.yaml')) or (
            len(parts) == 4 and parts[0] in {'.agents','.claude'} and parts[1] == 'skills'
            and parts[2] in {'fuzzy-start','job-queue'} and parts[3] == 'SKILL.md') or (
            len(parts) == 3 and parts[:2] == ('.codex','agents')
            and parts[2] in {'author.toml','reviewer.toml','delivery.toml'}) or (
            len(parts) == 3 and parts[:2] == ('.claude','agents')
            and parts[2] in {'fuzzy-author.md','fuzzy-reviewer.md','fuzzy-delivery.md'}) or (
            name in {'.claude/settings.json','.github/workflows/portability.yml'})
        if not permitted:
            raise ValueError('Distribution allowlist contains a path outside reusable source families.')
        for n in range(1, len(parts)):
            directory = '/'.join(parts[:n])
            prior = directories.setdefault(directory.casefold(), directory)
            if prior != directory:
                raise ValueError('Case-colliding distribution directory.')
        result[name] = regular(root, name).read_bytes()
    if MANIFEST not in result:
        raise ValueError('Release must include its reproducible file allowlist.')
    return result


def verify(archive_path, expected):
    with zipfile.ZipFile(archive_path) as archive:
        names = ['FuzzyProblems/' + name for name in sorted(expected)]
        if archive.namelist() != names or archive.comment:
            raise ValueError('Archive member list or metadata differs.')
        for info, name in zip(archive.infolist(), sorted(expected)):
            if (info.date_time != STAMP or info.create_system != 0 or info.extra or info.comment
                    or info.external_attr != 0o100644 << 16):
                raise ValueError('Archive metadata is not neutral.')
            if archive.read(info) != expected[name]:
                raise ValueError('Archive differs from selected source bytes.')


def build(destination, root=ROOT, replace=False):
    expected = payload(root)
    destination = Path(destination).absolute()
    if destination.is_symlink() or destination.is_junction():
        raise ValueError('Archive destination must be a regular file.')
    # Do not follow a redirected output directory. The filesystem's own /tmp
    # alias may be resolved by the caller before supplying the destination.
    for part in destination.parents:
        if part.is_symlink() or part.is_junction():
            raise ValueError('Archive destination must not traverse symlinks/junctions.')
    if destination.exists() and not replace:
        raise FileExistsError('Archive exists; choose a new name or explicitly use --replace.')
    if destination.resolve().is_relative_to(Path(root).resolve()):
        relative = destination.resolve().relative_to(Path(root).resolve()).as_posix()
        if relative in expected:
            raise ValueError('Cannot overwrite a distribution source file.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.release-',suffix='.zip',dir=destination.parent,delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, 'w') as archive:
            for name, data in sorted(expected.items()):
                info = zipfile.ZipInfo('FuzzyProblems/' + name, date_time=STAMP)
                info.create_system = 0
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        verify(temporary, expected)
        if destination.exists() and not replace:
            raise FileExistsError('Archive appeared during construction; no replacement requested.')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {'status':'pass','members':len(expected),'exact_bytes':True,
            'archive_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'releases/FuzzyProblems.zip')
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = build(args.output, replace=args.replace)
    except (OSError, ValueError, zipfile.BadZipFile):
        parser.exit(1,'Release failed: check the allowlist, regular files, destination and permissions; no unchecked archive was published.\n')
    print(json.dumps(report,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
