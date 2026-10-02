"""Resolve source-keyed discovery caches with project-relative paths."""
from pathlib import Path

def cache_root(root):
    return Path(root) / 'foundation/ingestion'

def raw_path(root, source, directory=None):
    base = directory or Path(root) / source['intake_cache']
    return base / 'raw-cache/raw' / source['sha256'] / 'pages.jsonl.gz'
