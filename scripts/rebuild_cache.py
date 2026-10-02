"""Reconstruct a derived search index from intact source-keyed caches."""
import argparse


import gzip


import hashlib


import json


import os


from pathlib import Path


import sqlite3


import tempfile


from cache_paths import cache_root


ROOT = Path(__file__).resolve().parents[1]


SCHEMA = """
CREATE TABLE sources (id TEXT PRIMARY KEY, role TEXT, sha256 TEXT, path TEXT, aliases TEXT);
CREATE TABLE pages (id INTEGER PRIMARY KEY, source_id TEXT, pdf_page INTEGER,
 classification TEXT, text TEXT, method TEXT, flags TEXT, raw_ref TEXT,
 UNIQUE(source_id,pdf_page));
CREATE VIRTUAL TABLE search USING fts5(text,content='pages',content_rowid='id',
 tokenize='unicode61 remove_diacritics 2');
CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT);
"""


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def page_rows(root, source, cache_dir=None):
    path = (cache_dir or cache_root(root)) / 'cleaned' / source['sha256'] / 'pages.jsonl.gz'
    count = 0
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for count, line in enumerate(stream, 1):
            row = json.loads(line)
            anchor = source['raw_cache'] + '#pdf_page=' + str(count)
            if (row['source_id'] != source['source_id']
                    or row['source_sha256'] != source['sha256']
                    or type(row['pdf_page']) is not int or row['pdf_page'] != count
                    or row['raw_ref'] != anchor):
                raise ValueError(f'Invalid page identity/order/anchor: {path}, line {count}')
            if (not all(isinstance(row[k], str) for k in
                        ('classification', 'text', 'reading_order'))
                    or not isinstance(row['flags'], list)):
                raise ValueError(f'Invalid cleaned page fields: {path}, line {count}')
            yield (source['source_id'], count, row['classification'], row['text'],
                   row['reading_order'], json.dumps(row['flags']), anchor)
    if count != source['pdf_pages']:
        raise ValueError(f'Incomplete cleaned cache: {path}: {count}/{source["pdf_pages"]}')


def source_row(source):
    return (source['source_id'], source['role'], source['sha256'], '', '[]')


def normalized(row, json_column):
    values = list(row)
    values[json_column] = json.loads(values[json_column])
    return values


def validate(path, root, sources, cache_dir=None):
    # An explicit transaction lets FTS5 check its index against external content.
    # The integrity-check command performs no content edits; always roll it back.
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        total = 0
        if db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] != len(sources):
            raise ValueError('Source count mismatch')
        for source in sources:
            stored = db.execute('SELECT id,role,sha256,path,aliases FROM sources WHERE id=?',
                                (source['source_id'],)).fetchone()
            if stored is None or normalized(stored, 4) != normalized(source_row(source), 4):
                raise ValueError('Source metadata mismatch: ' + source['source_id'])
            rows = iter(db.execute('SELECT source_id,pdf_page,classification,text,method,flags,raw_ref '
                                   'FROM pages WHERE source_id=? ORDER BY pdf_page',
                                   (source['source_id'],)))
            for expected in page_rows(root, source, cache_dir):
                actual = next(rows, None)
                if actual is None or normalized(actual, 5) != normalized(expected, 5):
                    raise ValueError(f'Page content mismatch: {source["source_id"]}/{expected[1]}')
                total += 1
            if next(rows, None) is not None:
                raise ValueError('Unexpected extra source page')
        if db.execute('SELECT COUNT(*) FROM pages').fetchone()[0] != total:
            raise ValueError('Orphan or extra database pages')
        db.execute('BEGIN')
        db.execute("INSERT INTO search(search,rank) VALUES ('integrity-check',1)")
        return {'sources': len(sources), 'pages': total, 'fts5_integrity': 'pass'}
    finally:
        db.rollback()
        db.close()


def destination(root, output, cache_dir=None):
    directory = cache_dir or cache_root(root)
    if not directory.resolve().is_relative_to((root / 'foundation').resolve()):
        raise ValueError('Cache output must stay under foundation')
    path = directory / output
    if Path(output).name != output or not output.endswith('.sqlite'):
        raise ValueError('--output must be a simple .sqlite filename')
    for candidate in [path, *path.parents]:
        if candidate.is_symlink():
            raise ValueError('Symlinks are not allowed in cache output paths')
        if candidate == root:
            break
    if not directory.is_dir():
        raise ValueError('Missing foundation/ingestion directory')
    return path



def run(root=ROOT, *, check=False, rebuild=False):
    from contextlib import closing
    import intake
    import workflow as w
    import pipeline_core as v
    results = []
    for source in intake.sources():
        intake.checked_source(source['source_id'])
        directory = intake.source_directory(source)
        target = w.safe_tree(directory / 'search.sqlite')
        receipt_path = w.safe_tree(directory / 'extraction.json')
        receipt = v.read(receipt_path)
        for name, expected in receipt['payloads'].items():
            if name != 'search.sqlite' and digest(directory / name) != expected:
                raise ValueError('Preserved extraction payload changed; index reconstruction cannot repair it')
        if check or not rebuild:
            results.append(validate(target, root, [source], directory))
            continue
        for suffix in ('-wal','-shm','-journal'):
            if Path(str(target)+suffix).exists():
                raise ValueError('Close/recover SQLite writers before reconstruction')
        old = digest(target) if target.exists() else None
        receipt_hash = digest(receipt_path)
        handle, filename = tempfile.mkstemp(prefix='.index-', suffix='.sqlite', dir=directory)
        os.close(handle);temporary = Path(filename)
        try:
            with closing(sqlite3.connect(temporary)) as db:
                db.executescript(SCHEMA)
                with db:
                    db.execute('INSERT INTO sources VALUES (?,?,?,?,?)', source_row(source))
                    db.executemany('INSERT INTO pages (source_id,pdf_page,classification,text,method,flags,raw_ref) VALUES (?,?,?,?,?,?,?)', page_rows(root, source, directory))
                    db.execute("INSERT INTO search(search) VALUES ('rebuild')")
            results.append(validate(temporary, root, [source], directory))
            if (digest(target) if target.exists() else None) != old or digest(receipt_path) != receipt_hash:
                raise ValueError('Concurrent index/receipt update; original preserved')
            for name, expected in receipt['payloads'].items():
                if name != 'search.sqlite' and digest(directory/name) != expected:
                    raise ValueError('Extraction changed during index reconstruction')
            os.replace(temporary, target)
            receipt['payloads']['search.sqlite'] = digest(target)
            v.write(receipt_path, receipt)
        finally:
            temporary.unlink(missing_ok=True)
    return {'status':'rebuilt' if rebuild and not check else 'valid', 'indexes':len(results),
            'pages':sum(x['pages'] for x in results), 'educational_approval':False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    from review_runner import Lock
    import pipeline_core as v
    import workflow as w
    with Lock(w.safe_tree(v.BASE / '.intake.lock')):
        result = run(check=args.check, rebuild=args.rebuild)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
