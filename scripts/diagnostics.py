"""Silent, best-effort local telemetry. No model/API calls or automatic reports."""
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import hashlib
import json
import os
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
_active = ContextVar('pipeline_diagnostic_operation', default=None)
_stream = None
_size = 0
MAX_FILE_BYTES = 4 * 1024 * 1024


def enabled():
    return os.environ.get('STUDY_DIAGNOSTICS', '1') != '0'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def relative(path):
    try:
        path = Path(path)
        if not path.is_absolute():
            path = ROOT/path
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError, TypeError):
        return None


def emit(event, **fields):
    """Never print, alter pipeline results or propagate telemetry failures."""
    global _stream, _size
    try:
        if not enabled():
            return
        parent = _active.get() or {}
        now = datetime.now(timezone.utc)
        row = {'schema': 1, 'time': now.isoformat(), 'event': event,
               'operation': parent.get('operation'), 'pack': parent.get('pack'), **fields}
        data = (json.dumps(row, ensure_ascii=False, separators=(',', ':'))+'\n').encode('utf-8')
        if len(data) > 65536:
            return
        directory = ROOT/'.diagnostics'
        if directory.is_symlink() or not directory.resolve().is_relative_to(ROOT.resolve()):
            return
        directory.mkdir(exist_ok=True)
        if _stream is None or _size+len(data) > MAX_FILE_BYTES or not _stream.name.startswith(now.strftime('%Y-%m-%d')):
            _stream = directory/(now.strftime('%Y-%m-%d')+'-'+uuid.uuid4().hex+'.jsonl')
            _size = 0
        if _stream.is_symlink():
            return
        with _stream.open('ab') as output:
            output.write(data)
        _size += len(data)
    except Exception:
        pass


def annotate(**fields):
    if enabled():
        current = _active.get()
        if current is not None:
            current.update(fields)


def failure_category(exc):
    text = str(exc).lower()
    for category, words in [
        ('source_or_citation', ('source', 'citation', 'evidence', 'textbook', 'passage')),
        ('educational_receipt', ('review', 'depth', 'coverage', 'component', 'chapter axis')),
        ('answer_or_table', ('answer', 'marking', 'sba', 'saq', 'table', 'anki')),
        ('exported_content', ('teaching', 'hidden', 'content', 'figure')),
        ('dependency_or_artifact', ('stale', 'changed', 'artifact', 'cache', 'input')),
        ('path_or_environment', ('path', 'symlink', 'permission', 'renderer', 'wkhtmltopdf'))]:
        if any(word in text for word in words):
            return category
    return 'unclassified'


@contextmanager
def operation(stage, path=None):
    if not enabled():
        yield
        return
    parent = _active.get() or {}
    rel = relative(path) if path is not None else None
    pack = '/'.join(rel.split('/')[:2]) if rel and rel.startswith('packs/') else parent.get('pack')
    fields = {'operation': uuid.uuid4().hex, 'parent': parent.get('operation'),
              'stage': stage, 'pack': pack}
    if parent.get('input_key'):
        fields['input_key'] = parent['input_key']
    token = _active.set(fields)
    start = time.perf_counter()
    emit('stage_start', stage=stage, parent=fields['parent'])
    outcome = 'returned'
    try:
        yield
    except BaseException as exc:
        outcome = 'raised'
        fields['exception_type'] = type(exc).__name__
        fields['error_signature'] = hashlib.sha256(str(exc).encode('utf-8', errors='replace')).hexdigest()
        fields['failure_category_inferred'] = failure_category(exc)
        raise
    finally:
        emit('stage_end', **fields, outcome=outcome,
             duration_ms=round((time.perf_counter()-start)*1000, 3))
        _active.reset(token)


def observe(stage):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            path = args[0] if args and isinstance(args[0], Path) else kwargs.get('p')
            with operation(stage, path):
                result = fn(*args, **kwargs)
                if isinstance(result, dict):
                    metrics = {k: result[k] for k in ('reused', 'evidence_reused', 'renders',
                               'geometry_computations', 'geometry_reused') if isinstance(result.get(k), (bool, int))}
                    status = result.get('status')
                    if status in {'pass', 'needs_attention', 'not_requested', 'stale_diagnostic',
                                  'built_not_approved', 'published', 'handoff_not_approval',
                                  'changed_not_approval', 'unchanged_not_approval', 'review_requested_not_approved'}:
                        metrics['result_status'] = status
                    annotate(**metrics)
                return result
        return wrapped
    return decorate


def file_event(event, path, data=None, **fields):
    try:
        if not enabled():
            return
        rel = relative(path)
        if rel is None or rel.startswith('.diagnostics/'):
            return
        if data is not None:
            fields.update(bytes=len(data), content_sha256=hashlib.sha256(data).hexdigest())
        emit(event, path=rel, **fields)
    except Exception:
        pass


def receipt_observed(path, value):
    """Observe existing structured findings only; never ask a model to add fields."""
    try:
        rel = relative(path)
        if not rel or '/review/' not in rel or not isinstance(value, dict) or 'reviewer' not in value:
            return
        counts = {name: len(value[name]) for name in ('unresolved_findings', 'reviewed_records', 'retained_records')
                  if isinstance(value.get(name), list)}
        axes = {k: x for k, x in value.get('verdicts', {}).items()
                if k in {'factual_support', 'chapter_coverage', 'explanatory_depth', 'educational_quality'}
                and x in {'pass', 'fail', 'needs_revision'}}
        emit('receipt_observed', path=rel, counts=counts, axes=axes)
    except Exception:
        pass


class _CountingStream:
    def __init__(self, target):
        self.target = target
        self.characters = self.bytes = 0
        self.hash = hashlib.sha256()

    def write(self, value):
        result = self.target.write(value)
        try:
            data = value.encode('utf-8')
            self.characters += len(value)
            self.bytes += len(data)
            self.hash.update(data)
        except Exception:
            pass
        return result

    def __getattr__(self, name):
        return getattr(self.target, name)


def command(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not enabled():
            return fn(*args, **kwargs)
        stdout, stderr = sys.stdout, sys.stderr
        out, err = _CountingStream(stdout), _CountingStream(stderr)
        digest_stats = getattr(sys.modules.get('pipeline_core'), 'DIGEST_STATS', {})
        before = dict(digest_stats)
        with operation('command'):
            name = sys.argv[1] if len(sys.argv) > 1 else ''
            if re.fullmatch('[a-z-]{1,32}', name):
                annotate(command=name)
            sys.stdout, sys.stderr = out, err
            try:
                return fn(*args, **kwargs)
            finally:
                sys.stdout, sys.stderr = stdout, stderr
                annotate(stdout_characters=out.characters, stdout_utf8_bytes=out.bytes,
                         stdout_sha256=out.hash.hexdigest(), stderr_characters=err.characters,
                         stderr_utf8_bytes=err.bytes, stderr_sha256=err.hash.hexdigest(),
                         hash_work={k:n-before.get(k,0) for k,n in digest_stats.items()})
    return wrapped
