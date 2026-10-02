"""Local native extraction, OCR and source-page cache primitives."""
import argparse


from collections import Counter


from concurrent.futures import ProcessPoolExecutor, as_completed


import csv


import gzip


import hashlib


import io


import json


import os


from pathlib import Path


import re


import shutil


import sqlite3


import subprocess


import tempfile


import time


import unicodedata


import uuid


import fitz


import rebuild_cache


import pipeline_core as v


ROOT = Path(__file__).resolve().parents[1]


FORMAT = 'study-bootstrap-1'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def safe_path(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes project: ' + str(relative))
    for item in [path, *path.parents]:
        if linked(item):
            raise ValueError('Linked path is not allowed: ' + str(relative))
        if item == root:
            break
    return path


def tool(name, extra=()):
    found = shutil.which(name)
    if found:
        return str(Path(found).resolve())
    for path in extra:
        if path.is_file():
            return str(path.resolve())
    return None


def dependencies(ocr_mode):
    programs = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
    language_code = read(ROOT / 'bootstrap-settings.json')['ocr']['language']
    if not re.fullmatch(r'[A-Za-z0-9_]+', language_code):
        raise ValueError('Configure one installed Tesseract language code')
    tesseract = tool('tesseract', [programs / 'Tesseract-OCR/tesseract.exe',
                                 Path('/opt/homebrew/bin/tesseract'), Path('/usr/local/bin/tesseract')])
    renderer = tool('wkhtmltopdf', [programs / 'wkhtmltopdf/bin/wkhtmltopdf.exe',
                                  Path('/opt/homebrew/bin/wkhtmltopdf'), Path('/usr/local/bin/wkhtmltopdf')])
    language = None
    version = None
    if tesseract:
        version = subprocess.check_output([tesseract, '--version'], text=True, encoding='utf-8', timeout=10).splitlines()[0]
        configured = os.environ.get('STUDY_TESSDATA')
        directories = [Path(configured)] if configured else [
            Path(os.environ.get('TESSDATA_PREFIX', '')),
            Path(tesseract).parent / 'tessdata', Path('/opt/homebrew/share/tessdata'),
            Path('/usr/local/share/tessdata'), Path('/usr/share/tesseract-ocr/5/tessdata')]
        if not configured:
            listing = subprocess.run([tesseract, '--list-langs'], capture_output=True, text=True, encoding='utf-8', check=True, timeout=10)
            match = re.search(r'in "([^"]+)"', listing.stdout + listing.stderr)
            if match:
                directories.append(Path(match[1]))
        language = next((p / (language_code + '.traineddata') for p in directories if (p / (language_code + '.traineddata')).is_file()), None)
    if ocr_mode == 'auto' and (not tesseract or not language):
        raise ValueError('Local Tesseract and the configured language data are required. Set STUDY_TESSDATA to its tessdata directory. '
                         'Or explicitly choose --ocr skip for native-text-only setup.')
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE VIRTUAL TABLE probe USING fts5(text)')
    return {'tesseract': tesseract, 'tesseract_version': version,
            'language': str(language.resolve()) if language else None,
            'language_sha256': sha(language) if language else None,
            'wkhtmltopdf': renderer, 'pymupdf': fitz.VersionBind, 'sqlite': sqlite3.sqlite_version}


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    # No timestamps or machine-dependent gzip filename headers.
    with path.open('wb') as file, gzip.GzipFile(filename='', fileobj=file, mode='wb', mtime=0) as zipped:
        for row in rows:
            zipped.write((json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8'))


def load_rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        yield from map(json.loads, stream)


def extract(root, stage, source, config):
    original = safe_path(root, source['path'])
    pages = []
    flags_count = Counter()
    candidates = set()
    with fitz.open(original) as pdf:
        if len(pdf) != source['pdf_pages'] or pdf.needs_pass:
            raise ValueError('Original page count or encryption differs: ' + source['path'])
        outline = pdf.get_toc()
        metadata = pdf.metadata
        for number, page in enumerate(pdf, 1):
            blocks = [{'bbox': list(b[:4]), 'text': b[4]} for b in page.get_text(
                'blocks', flags=fitz.TEXTFLAGS_BLOCKS & ~fitz.TEXT_PRESERVE_IMAGES, sort=False) if b[6] == 0]
            text = ''.join(b['text'] for b in blocks)
            flags = []
            if not text.strip():
                flags.append('no_native_text')
            if len(text.strip()) < config['native_text_threshold']:
                flags.append('sparse_text_review')
                candidates.add(number)
            if any(unicodedata.category(c) == 'Co' for c in text):
                flags.append('private_glyphs_verify_original')
            if '\ufffd' in text:
                flags.append('replacement_character_verify_original')
            flags_count.update(flags)
            pages.append({'document_id': source['source_id'], 'source': source['path'],
                          'source_sha256': source['sha256'], 'pdf_page': number,
                          'pdf_label': page.get_label(), 'printed_page': None, 'text': text,
                          'blocks': blocks, 'flags': flags, 'rotation': page.rotation,
                          'width': page.cropbox.width, 'height': page.cropbox.height,
                          'extractor': 'PyMuPDF ' + fitz.VersionBind, 'extraction_schema': FORMAT})
        # Repeat representative native extraction against the original. This
        # checks the serialized route, not reading-order/educational correctness.
        samples = sorted({1, max(1, len(pdf) // 2), len(pdf)})
        for n in samples:
            expected = ''.join(b[4] for b in pdf[n - 1].get_text('blocks',
                              flags=fitz.TEXTFLAGS_BLOCKS & ~fitz.TEXT_PRESERVE_IMAGES, sort=False) if b[6] == 0)
            if pages[n - 1]['text'] != expected:
                raise ValueError('Original extraction sample mismatch')
    if any(n < 1 or n > len(pages) for n in candidates):
        raise ValueError('OCR selection has an out-of-range page')
    raw_dir = stage / 'raw-cache/raw' / source['sha256']
    jsonl(raw_dir / 'pages.jsonl.gz', pages)
    write(raw_dir / 'outline.json', outline)
    write(raw_dir / 'original_metadata.json', metadata)
    counts = v.edge_counts(pages)
    classifications = Counter()

    def cleaned():
        for page in pages:
            text, removed, method, flags = v.clean_page(page, counts)
            classification = v.classify(page, outline, source['role'])
            classifications[classification] += 1
            yield {'source_id': source['source_id'], 'source_sha256': source['sha256'],
                   'pdf_page': page['pdf_page'], 'pdf_label_unverified': page['pdf_label'],
                   'printed_page_verified': None, 'classification': classification, 'text': text,
                   'reading_order': method, 'flags': flags, 'removed_blocks': removed,
                   'raw_ref': source['raw_cache'] + '#pdf_page=' + str(page['pdf_page']),
                   'cleaner_version': FORMAT}

    jsonl(stage / 'cleaned' / source['sha256'] / 'pages.jsonl.gz', cleaned())
    return {'source_id': source['source_id'], 'pages': len(pages),
            'flags': dict(flags_count), 'classifications': dict(classifications),
            'original_samples': samples, 'ocr_pages': sorted(candidates)}


def recognize(task):
    root, stage, source, number, config, runtime = task
    settings = {'source_sha256': source['sha256'], 'pdf_page': number,
                'engine': runtime['tesseract_version'], 'language_sha256': runtime['language_sha256'],
                'dpi': config['dpi'], 'psm': config['psm'],
                'rotation': 'rendered_display_then_derotation_to_original'}
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    destination = stage / 'ocr' / source['sha256'] / f'{number}-{key[:16]}.json'
    with tempfile.TemporaryDirectory(prefix='study-local-ocr-') as directory, fitz.open(root / source['path']) as doc:
        temporary = Path(directory).resolve()
        if not temporary.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise ValueError('OCR temporary directory outside local temp root')
        page = doc[number - 1]
        image = temporary / 'page.png'
        pixmap = page.get_pixmap(dpi=config['dpi'])
        pixmap.save(image)
        output = temporary / 'result'
        environment = os.environ.copy()
        environment['OMP_THREAD_LIMIT'] = '1'
        subprocess.run([runtime['tesseract'], str(image), str(output), '--tessdata-dir',
                        str(Path(runtime['language']).parent), '-l', config['language'],
                        '--psm', str(config['psm']), 'txt', 'tsv'],
                       capture_output=True, check=True, timeout=config['timeout_seconds'], env=environment)
        text = output.with_suffix('.txt').read_text(encoding='utf-8')
        words = []
        with output.with_suffix('.tsv').open(encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE):
                if row['level'] == '5' and row['text'].strip():
                    x, y, width, height = [float(row[k]) for k in ('left', 'top', 'width', 'height')]
                    rect = fitz.Rect(x * page.rect.width / pixmap.width, y * page.rect.height / pixmap.height,
                                     (x + width) * page.rect.width / pixmap.width,
                                     (y + height) * page.rect.height / pixmap.height) * page.derotation_matrix
                    words.append({'text': row['text'], 'confidence': float(row['conf']),
                                  'bbox_original_unrotated': list(rect), 'pixel_bbox': [x, y, width, height]})
        write(destination, {**settings, 'source_id': source['source_id'], 'cache_key': key,
                            'image_dimensions': [pixmap.width, pixmap.height], 'text': text, 'words': words,
                            'capabilities': {'nonempty_text': bool(text.strip()), 'word_boxes': bool(words)},
                            'status': 'nonempty' if text.strip() else 'empty',
                            'geometry_reviewed': False, 'factual_review': 'unreviewed'})
    return destination.relative_to(stage).as_posix()


