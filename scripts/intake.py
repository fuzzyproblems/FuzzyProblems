"""Incremental PDF discovery and provisional interpretation; never approval."""
import copy
import gzip
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pipeline_core as v

ROLES = {'Objectives': 'objectives', 'Textbooks': 'textbooks', 'PastPapers': 'pastpapers'}
PRACTICE_TYPES = {'short_answer', 'essay', 'calculation', 'data_interpretation', 'practical', 'sba'}


def location(name):
    import workflow as w
    return w.safe_tree(v.BASE / 'intake' / name)


def load(name, default):
    path = location(name)
    return v.read(path) if path.is_file() else copy.deepcopy(default)


def originals():
    path = v.BASE / 'sources/sources.json'
    return v.read(path) if path.is_file() else []


def sources():
    path=location('catalog.json')
    return v.read(path)['sources'] if path.is_file() else originals()


def curriculum():
    path = v.BASE / 'curriculum/objective_register.json'
    result = v.read(path) if path.is_file() else {'lessons': [], 'entries': []}
    for unit in load('units.json', {}).values():
        lid = unit['lesson']['id']
        result['lessons'] = [x for x in result['lessons'] if x['id'] != lid] + [unit['lesson']]
        result['entries'] = [x for x in result['entries'] if x['lesson_id'] != lid] + unit['entries']
    return result


def source_directory(source):
    import cache_paths
    import workflow as w
    if source.get('intake_cache'):
        return w.safe_tree(w.project_path(source['intake_cache']))
    return cache_paths.cache_root(v.ROOT)


def checked_source(sid, role=None):
    import workflow as w
    source = v.get_source(sid)
    if role and source['role'] != role:
        raise ValueError('Wrong source role: ' + sid)
    if v.digest(w.project_path(source['path'])) != source['sha256']:
        raise ValueError('Original changed; run intake and reassess affected work: ' + source['path'])
    return source


def raw_pages(source):
    directory = source_directory(source)
    path = directory / 'raw-cache/raw' / source['sha256'] / 'pages.jsonl.gz'
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def page_text(source, page, method='native'):
    if type(page) is not int or not 1 <= page <= source['pdf_pages']:
        raise ValueError('Original PDF page out of bounds')
    if method == 'native':
        with v.fitz.open(v.ROOT / source['path']) as pdf:
            return pdf[page - 1].get_text(sort=False)
    if method != 'local_ocr':
        raise ValueError('Only native text or recorded local OCR may anchor intake')
    directory = source_directory(source)
    candidates = sorted((directory / 'ocr' / source['sha256']).glob(f'{page}-*.json'))
    rows = [v.read(p) for p in candidates]
    rows = [r for r in rows if r.get('source_sha256') == source['sha256'] and r.get('pdf_page') == page]
    if not rows or len({r['text'] for r in rows}) != 1:
        raise ValueError('Missing/ambiguous local OCR; select and reconcile the original page')
    return rows[0]['text']


def check_anchor(anchor, role):
    source = checked_source(anchor['source_id'], role)
    quote = anchor.get('quote', '')
    norm = lambda t: ' '.join(v.normalize(t).split())
    if not quote.strip() or norm(quote) not in norm(page_text(source, anchor['pdf_page'], anchor.get('method', 'native'))):
        raise ValueError('Intake quotation is absent from original native/local OCR text')
    return {**anchor, 'source_sha256': source['sha256']}


def _index(directory, source):
    import rebuild_cache as cache
    target = directory / 'search.sqlite'
    # The whole per-source directory is uncommitted until catalog publication.
    with closing(sqlite3.connect(target)) as db:
        db.executescript(cache.SCHEMA)
        with db:
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?)', cache.source_row(source))
            db.executemany('INSERT INTO pages (source_id,pdf_page,classification,text,method,flags,raw_ref) '
                           'VALUES (?,?,?,?,?,?,?)', cache.page_rows(v.ROOT, source, directory))
            db.execute("INSERT INTO search(search) VALUES ('rebuild')")
    cache.validate(target, v.ROOT, [source], directory)


def _ocr_discovery(directory, source, settings):
    """Make local OCR searchable, preserving raw native pages and unreviewed status."""
    import bootstrap as b
    cleaned=directory/'cleaned'/source['sha256']/'pages.jsonl.gz'
    rows=list(b.load_rows(cleaned))
    for row in rows:
        if len(row['text'].strip())>=settings['native_text_threshold']:
            continue
        candidates=sorted((directory/'ocr'/source['sha256']).glob(f'{row["pdf_page"]}-*.json'))
        if not candidates:continue
        ocr_rows=[v.read(path) for path in candidates]
        if len({o['text'] for o in ocr_rows})!=1:
            raise ValueError('Different local OCR results need explicit reconciliation')
        text=ocr_rows[0]['text']
        if not text.strip():
            row['flags']=list(dict.fromkeys(row['flags']+['local_ocr_empty_verify_original']))
            continue
        row.update(text=text,reading_order='local_ocr_unreviewed')
        if row['classification']=='no_native_text':
            row['classification']='teaching_candidate' if source['role']=='textbooks' else source['role']
        row['flags']=list(dict.fromkeys(row['flags']+['local_ocr_unreviewed']))
    b.jsonl(cleaned,rows)


def _extract(source, ocr, runtime):
    import bootstrap as b
    import workflow as w
    settings = v.read(v.ROOT / 'bootstrap-settings.json')['ocr']
    recipe = {'source': source['sha256'], 'settings': settings, 'pymupdf': v.fitz.VersionBind,
              'ocr_mode':ocr,'ocr_runtime':{k:runtime.get(k) for k in ('tesseract_version','language_sha256')} if ocr=='auto' else None,
              'extractor': v.digest(v.ROOT / 'scripts/bootstrap.py'),
              'cleaner': v.digest(v.ROOT / 'scripts/pipeline_core.py')}
    directory = w.safe_tree(v.BASE / 'intake-cache' / source['sha256'] / w.semantic(recipe)[:16])
    source['raw_cache'] = (directory / 'raw-cache/raw' / source['sha256'] / 'pages.jsonl.gz').relative_to(v.ROOT).as_posix()
    receipt = directory / 'extraction.json'
    if receipt.is_file():
        old = v.read(receipt)
        if old['recipe'] == recipe and all(v.digest(directory / p) == h for p, h in old['payloads'].items()):
            return directory, False
        raise ValueError('Changed intake payload; preserve the damaged cache and restore/re-extract it explicitly')
    directory.mkdir(parents=True, exist_ok=True)
    # An interrupted, never-published index may be replaced safely.
    (directory / 'search.sqlite').unlink(missing_ok=True)
    result = b.extract(v.ROOT, directory, source, settings)
    pending = result['ocr_pages']
    if pending and ocr == 'auto':
        if not runtime.get('tesseract') or not runtime.get('language'):
            raise ValueError('Local Tesseract and configured language data are required for selected OCR pages')
        for number in pending:
            b.recognize((v.ROOT, directory, source, number, settings, runtime))
        pending = []
        _ocr_discovery(directory,source,settings)
    _index(directory, source)
    v.write(receipt, {'recipe': recipe, 'result': result, 'pending_ocr_pages': pending,
                     'payloads': {p.relative_to(directory).as_posix(): v.digest(p) for p in directory.rglob('*')
                                  if p.is_file() and p != receipt}, 'educational_approval': False})
    return directory, True


def sync(ocr='auto', scan_only=False):
    """Run once before a production queue. Hash originals, never load books into a model."""
    import workflow as w
    if ocr not in {'auto', 'skip'}:
        raise ValueError('Unsupported OCR mode')
    lock = w.safe_tree(v.BASE / '.intake.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    if (v.BASE / '.setup.lock').exists():
        raise ValueError('Setup is running; wait before intake')
    with lock.open('x', encoding='utf-8') as stream:
        stream.write('Incremental intake in progress. Do not run setup concurrently.\n')
    try:
        previous = {s['source_id']: s for s in originals()}
        previous.update({s['source_id']:s for s in load('catalog.json',{}).get('unavailable_sources',[])})
        previous.update({s['source_id']: s for s in sources()})
        groups = {}; ignored = []; ignored_records=[];issues = []; seen = set()
        for folder, role in ROLES.items():
            top = w.safe_tree(v.ROOT / folder)
            if not top.exists():
                continue
            for path in sorted(top.rglob('*')):
                w.safe_tree(path)
                if not path.is_file():
                    continue
                relative = path.relative_to(v.ROOT).as_posix()
                if v.normalize(relative).casefold() in seen:
                    raise ValueError('Case-colliding source locations are not portable: ' + relative)
                seen.add(v.normalize(relative).casefold())
                if path.suffix.lower() != '.pdf':
                    ignored.append(relative)
                    ignored_records.append({'path':relative,'role':role,'sha256':v.digest(path),'status':'unsupported_non_pdf'})
                    continue
                digest = v.digest(path)
                group = groups.setdefault(digest, {'role': role, 'aliases': []})
                if group['role'] != role:
                    raise ValueError('Identical PDF in different authority folders: ' + relative)
                group['aliases'].append(relative)
        rows = []; added = []; extracted = 0;runtime=None
        for digest, group in sorted(groups.items()):
            sid = 'src-' + digest[:16]; aliases = group['aliases']
            old = previous.get(sid)
            if old and old['role'] != group['role']:
                raise ValueError('Changing a source authority role requires explicit reconciliation')
            if old:
                row = copy.deepcopy(old)
                row['aliases'] = aliases
                row['path'] = old['path'] if old['path'] in aliases else aliases[0]
                if not row.get('intake_required'):
                    directory=source_directory(row)
                    if not all(p.is_file() for p in [directory/'raw-cache/raw'/digest/'pages.jsonl.gz',
                                                     directory/'cleaned'/digest/'pages.jsonl.gz',directory/'search.sqlite']):
                        row.update(intake_required=True,quality_status='pending_original_inspection')
            else:
                try:
                    with v.fitz.open(v.ROOT / aliases[0]) as pdf:
                        if pdf.needs_pass or not len(pdf):
                            raise ValueError('Locked or empty PDF')
                        row = {'source_id': sid, 'sha256': digest, 'role': group['role'], 'format': 'pdf',
                               'path': aliases[0], 'aliases': aliases, 'original_filename': Path(aliases[0]).name,
                               'pdf_pages': len(pdf), 'metadata': pdf.metadata,
                               'raw_cache': f'foundation/ingestion/raw-cache/raw/{digest}/pages.jsonl.gz',
                               'identity_status': 'pending_original_inspection' if group['role'] == 'textbooks' else 'original_source_document',
                               'intake_required': True, 'quality_status': 'pending_original_inspection'}
                except (RuntimeError, ValueError) as exc:
                    issues.append({'path': aliases[0], 'error': str(exc)}); continue
                added.append(sid)
            if row.get('intake_required') and not scan_only:
                if runtime is None:
                    import bootstrap
                    runtime=bootstrap.dependencies('skip')
                directory, changed = _extract(row, ocr, runtime)
                if row.get('intake_cache') and row['intake_cache']!=directory.relative_to(v.ROOT).as_posix():
                    row['quality_status']='pending_original_inspection'
                row['intake_cache'] = directory.relative_to(v.ROOT).as_posix()
                extracted += int(changed)
            rows.append(row)
        removed = sorted({sid for sid,s in previous.items() if s.get('format')=='pdf'} - {s['source_id'] for s in rows})
        for source in rows:
            if any(v.digest(v.ROOT/alias)!=source['sha256'] for alias in source['aliases']):
                raise ValueError('Original changed during intake; prior catalog preserved')
        catalog = {'schema_version': 1, 'sources': rows, 'unsupported_files': ignored, 'issues': issues,
                   'unsupported_file_records':ignored_records,
                   'unavailable_sources':[previous[sid] for sid in removed]}
        if not scan_only:
            v.write(location('catalog.json'), catalog)
        result = {'status': 'needs_attention' if issues else 'discovery_ready', 'pdfs': len(rows),
                  'added_source_ids': added, 'unavailable_source_ids': removed, 'extracted_pdfs': extracted,
                  'unsupported_files': ignored, 'issues': issues, 'model_calls': 0, 'educational_approval': False}
        if not scan_only:
            result['pending'] = pending()
            v.write(location('last-intake.json'), result)
        return result
    finally:
        lock.unlink(missing_ok=True)


def pending():
    register = curriculum()
    covered = {l['source_sha256'] for l in register['lessons']}
    covered |= {d['sha256'] for l in register['lessons'] for d in l.get('documents', [])}
    styles = load('styles.json', {})
    styled = {a['source_sha256'] for p in styles.values() for a in p['observations']}
    return {'curriculum_sources': [s['source_id'] for s in sources() if s['role'] == 'objectives' and s['sha256'] not in covered],
            'textbooks_needing_identity_quality': [s['source_id'] for s in sources() if s['role'] == 'textbooks' and s.get('intake_required')
                                                  and s.get('quality_status') != 'original_samples_inspected'],
            'papers_without_style_profile': [s['source_id'] for s in sources() if s['role'] == 'pastpapers' and s.get('intake_required') and s['sha256'] not in styled]}


def register_source(record):
    source = checked_source(record['source_id'])
    if not source.get('intake_required'):
        raise ValueError('Source must be registered by intake before inspection')
    samples = record.get('quality_samples', [])
    if not samples or not record.get('limitations') or not record.get('inspector'):
        raise ValueError('Record original-page quality samples, inspector and limitations (use "none observed" if appropriate)')
    for sample in samples:
        if type(sample.get('pdf_page')) is not int or not 1 <= sample['pdf_page'] <= source['pdf_pages'] or not sample.get('assessment'):
            raise ValueError('Incomplete original-page extraction quality assessment')
    if source['role'] == 'textbooks':
        identity = record.get('book_identity', {})
        if not identity.get('title') or 'edition' not in identity or not identity.get('edition_assessment'):
            raise ValueError('Verify title and edition from originals; explicitly record an unnumbered/unresolved edition')
        identity['identity_evidence'] = [check_anchor(a, 'textbooks') for a in identity.get('identity_evidence', [])]
        if not identity['identity_evidence']:
            raise ValueError('Book identity needs original-page evidence')
        source['book_identity'] = identity
        source['identity_status'] = 'title_and_edition_verified_from_book'
    source.update(quality_status='original_samples_inspected', quality_record=record)
    catalog = load('catalog.json', {})
    catalog['sources'] = [source if s['source_id'] == source['source_id'] else s for s in catalog['sources']]
    v.write(location('catalog.json'), catalog)
    return {'status': 'source_inspection_recorded_not_educational_approval', 'source_id': source['source_id']}


def register_unit(record):
    import workflow as w
    uid = w.safe_name(record['id'])
    if not record.get('title') or not record.get('learner_level') or not record.get('grouping_rationale'):
        raise ValueError('Record unit title, learner level and why its documents belong together')
    documents = []
    for document in record.get('documents', []):
        source = checked_source(document['source_id'], 'objectives')
        if not document.get('purpose') or not document.get('coverage_note'):
            raise ValueError('Account for requirements/context/administrative material in every supplied curriculum document')
        if sorted(document.get('pages_inspected', [])) != list(range(1, source['pdf_pages'] + 1)):
            raise ValueError('Interpret the complete curriculum documents, including all pages')
        documents.append({**document, 'path': source['path'], 'sha256': source['sha256']})
    if not documents or len({d['source_id'] for d in documents}) != len(documents):
        raise ValueError('A unit needs distinct original curriculum documents')
    all_units = load('units.json', {})
    old_register = curriculum()
    prior = next((l for l in old_register['lessons'] if l['id'] == uid), None)
    # Replaced bytes at an established location retain the existing unit identity.
    owners = {l['id'] for l in old_register['lessons'] if l['source_path'] in {d['path'] for d in documents}}
    if owners - {uid}:
        raise ValueError('Preserve an established lesson ID; attach supporting documents without merging original lessons')
    previous = [o for o in old_register['entries'] if o['lesson_id'] == uid and o['entry_kind'] == 'objective']
    entries = []; assigned = set(); next_number = 1
    numeric = {str(g.get('original_label', '')) for g in record.get('goals', []) if re.fullmatch(r'\d+(?:\.\d+)*', str(g.get('original_label', '')))}
    occurrences = {}
    for index, goal in enumerate(record.get('goals', []), 1):
        label = str(goal.get('original_label', ''))
        anchors = [check_anchor(a, 'objectives') for a in goal.get('anchors', [])]
        if not anchors or any(a['source_id'] not in {d['source_id'] for d in documents} for a in anchors):
            raise ValueError('Each learning requirement needs anchors in this unit')
        wording = goal.get('wording', '')
        if ' '.join(wording.split()) != ' '.join(' '.join(a['quote'] for a in anchors).split()):
            raise ValueError('Preserve exact source wording; place interpretation in the existing coverage contract')
        number = label if label in numeric else str(goal.get('display_number', ''))
        if not number:
            while str(next_number) in numeric or str(next_number) in assigned:
                next_number += 1
            number = str(next_number); next_number += 1
        if not re.fullmatch(r'\d+(?:\.\d+)*', number):
            raise ValueError('Use intelligible numerical goal/subgoal labels')
        if not label and number in assigned:
            raise ValueError('Assigned goal numbers must be distinct')
        assigned.add(number); occurrences[number] = occurrences.get(number, 0) + 1
        matches = [o for o in previous if o['wording'] == wording and str(o.get('source_label', o['original_number'])) == label]
        oid = goal.get('id') or (matches[0]['id'] if len(matches) == 1 else uid + '-goal-' + w.semantic([label, wording, anchors[0]['source_id']])[:12])
        w.safe_name(oid)
        entries.append({'id': oid, 'lesson_id': uid, 'entry_kind': 'objective', 'original_number': number,
                        'source_label': label, 'number_origin': 'original' if number == label else 'assigned',
                        'number_occurrence': occurrences[number], 'original_order': index, 'wording': wording,
                        'pbl_labels': goal.get('labels', []), 'source_path': documents[0]['path'], 'anchors': anchors,
                        'component_ids': goal.get('component_ids', [oid + '-requirement']),
                        'required_item_ids': goal.get('required_item_ids', []),
                        'interpretation_status': 'provisional_not_educational_approval'})
    if not entries or len({o['id'] for o in entries}) != len(entries):
        raise ValueError('A unit needs distinct, source-anchored learning requirements')
    lost = {o['id'] for o in previous} - {o['id'] for o in entries}
    if lost != set(record.get('retired_goal_reasons', {})) or any(not reason for reason in record.get('retired_goal_reasons', {}).values()):
        raise ValueError('Preserve IDs for edited goals; explicitly explain actual removed requirements')
    first = documents[0]
    lesson = {'id': uid, 'filename': prior['filename'] if prior else Path(first['path']).name,
              'source_path': first['path'], 'source_sha256': first['sha256'], 'documents': documents,
              'title': record['title'], 'learner_level': record['learner_level'],
              'objective_ids': [o['id'] for o in entries], 'grouping_rationale': record['grouping_rationale'],
              'assessment_profiles': record.get('assessment_profiles', []), 'intake_version': 1,
              'unresolved_gaps':record.get('unresolved_gaps',[])}
    all_units[uid] = {'lesson': lesson, 'entries': entries, 'record': record}
    v.write(location('units.json'), all_units)
    return {'status': 'provisional_unit_registered', 'lesson_id': uid, 'goals': len(entries), 'educational_approval': False}


def register_style(record):
    import workflow as w
    key = w.safe_name(record['id'])
    if not record.get('scope') or not record.get('limitations'):
        raise ValueError('Style observations need scope and sampling limitations')
    observations = []
    for row in record.get('observations', []):
        if row.get('practice_type') not in PRACTICE_TYPES or not row.get('observation'):
            raise ValueError('Record observed question structure and supported practice type')
        observations.append(check_anchor(row, 'pastpapers'))
    if not observations:
        raise ValueError('A style summary needs bounded original-paper observations')
    profiles = load('styles.json', {})
    profiles[key] = {**record, 'observations': observations, 'authority': 'assessment_style_only'}
    v.write(location('styles.json'), profiles)
    return {'status': 'style_recorded_not_factual_evidence', 'id': key}


def unit_context(lesson, entries, include_style=True):
    """A scoped dependency, including complete unit context, never the global register."""
    import workflow as w
    register = curriculum()
    all_entries = [o for o in register['entries'] if o['lesson_id'] == lesson['id']]
    paths = {lesson['source_path']: lesson['source_sha256']}
    paths.update({d['path']: d['sha256'] for d in lesson.get('documents', [])})
    for path, digest in paths.items():
        if v.digest(w.project_path(path)) != digest:
            raise ValueError('Curriculum document changed; reconcile this unit')
    blueprint_path = v.BASE / 'curriculum/curriculum_blueprint.json'
    blueprint = v.read(blueprint_path) if blueprint_path.is_file() else {}
    ids = {o['id'] for o in all_entries}
    plans = [p for p in blueprint.get('objective_plans', []) if p.get('objective_id', p.get('id')) in ids]
    edges = [e for e in blueprint.get('relationship_edges', []) if any(i in json.dumps(e) for i in ids)]
    profiles = load('styles.json', {}); selected = {}
    for key in lesson.get('assessment_profiles', []) if include_style else []:
        profile = profiles[key]
        for a in profile['observations']:
            if checked_source(a['source_id'], 'pastpapers')['sha256'] != a['source_sha256']:
                raise ValueError('Changed assessment-style source')
        selected[key] = profile
    return {'lesson': lesson, 'unit_requirements': all_entries, 'selected': [o['id'] for o in entries],
            'plans': plans, 'relationships': edges, 'assessment_style': selected}


def teaching_context(context):
    """Assessment observations cannot change factual authority or teaching priorities."""
    result={k:value for k,value in context.items() if k!='assessment_style'}
    result['lesson']={k:value for k,value in result['lesson'].items() if k!='assessment_profiles'}
    return result


def source_snapshot(ids):
    import workflow as w
    result = {}
    for sid in sorted(ids):
        source = checked_source(sid, 'textbooks')
        if source.get('intake_required') and source.get('quality_status') != 'original_samples_inspected':
            raise ValueError('Inspect new textbook identity/extraction before using it: ' + sid)
        result[sid] = {k: source.get(k) for k in ('sha256', 'role', 'pdf_pages')}
        result[sid].update(identity_sha256=w.semantic([source.get('book_identity'),source.get('identity_status')]),
                           quality_sha256=w.semantic([source.get('quality_status'),source.get('quality_record')]))
    return result


def check_active():
    import rebuild_cache
    import bootstrap
    import workflow as w
    checked = 0; pages = 0; ocr_count=0; checked_databases=set()
    for source in sources():
        checked_source(source['source_id'])
        for alias in source['aliases']:
            if v.digest(w.project_path(alias))!=source['sha256']:
                raise ValueError('Source alias changed: '+alias)
        if source.get('format') != 'pdf':
            continue
        directory = source_directory(source)
        selected_ocr=[];pending_ocr=[]
        receipt = v.read(directory / 'extraction.json')
        if any(v.digest(directory / p) != h for p, h in receipt['payloads'].items()):
            raise ValueError('Intake extraction payload changed')
        rebuild_cache.validate(directory / 'search.sqlite', v.ROOT, [source], directory)
        selected_ocr=receipt['result']['ocr_pages'];pending_ocr=receipt['pending_ocr_pages']
        if directory not in checked_databases:
            db=sqlite3.connect((directory/'search.sqlite').resolve().as_uri()+'?mode=rw',uri=True)
            try:
                if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
                    raise ValueError('Search database integrity failure')
                db.execute('BEGIN');db.execute("INSERT INTO search(search,rank) VALUES ('integrity-check',1)")
            finally:db.rollback();db.close()
            checked_databases.add(directory)
        raw=raw_pages(source)
        if len(raw)!=source['pdf_pages'] or any(r['pdf_page']!=n or r['source_sha256']!=source['sha256'] for n,r in enumerate(raw,1)):
            raise ValueError('Raw original-page identity/count mismatch')
        found=set()
        for path in (directory/'ocr'/source['sha256']).glob('*.json'):
            row=v.read(path)
            if (row.get('source_id')!=source['source_id'] or row.get('source_sha256')!=source['sha256']
                    or type(row.get('pdf_page')) is not int or not 1<=row['pdf_page']<=source['pdf_pages']
                    or row.get('geometry_reviewed') is not False or row.get('factual_review')!='unreviewed'):
                raise ValueError('Local OCR identity or unreviewed status changed')
            found.add(row['pdf_page']);ocr_count+=1
        if not set(selected_ocr)-set(pending_ocr)<=found:
            raise ValueError('Required local OCR discovery is missing')
        checked += 1; pages += source['pdf_pages']
    register=curriculum();current_hashes={s['sha256'] for s in sources()}
    for lesson in register['lessons']:
        if lesson['source_sha256'] not in current_hashes:continue
        for name in ('raw_text_file','raw_pages_file'):
            if name in lesson and not w.project_path(lesson[name]).is_file():
                raise ValueError('Missing preserved curriculum extraction')
        for document in lesson.get('documents',[]):
            if v.digest(w.project_path(document['path']))!=document['sha256']:
                raise ValueError('Grouped curriculum input changed')
    return {'status': 'pass', 'active_pdfs': checked, 'pages': pages,'local_ocr_records':ocr_count,
            'pending': pending(), 'educational_approval': False}


def view_source(sid, start=1, limit=3):
    """Bounded, complete discovery pages, including scanned curriculum/papers."""
    source=checked_source(sid)
    if type(start) is not int or not 1<=start<=source['pdf_pages'] or not 1<=limit<=3:
        raise ValueError('Request an original page and at most three complete pages')
    pages=[]
    for number in range(start,min(start+limit,source['pdf_pages']+1)):
        native=page_text(source,number)
        row={'pdf_page':number,'native_text':native,'ocr_text':None,'ocr_status':'not_requested',
             'authority':'Original PDF; extracted text is discovery only'}
        if len(native.strip())<120:
            try:row.update(ocr_text=page_text(source,number,'local_ocr'),ocr_status='unreviewed_local_ocr')
            except ValueError as exc:row.update(ocr_status=str(exc))
        pages.append(row)
    return {'source_id':source['source_id'],'source_sha256':source['sha256'],'path':source['path'],
            'pages':pages,'next_start':start+limit if start+limit<=source['pdf_pages'] else None}
