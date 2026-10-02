"""Selection precision diagnostics, never educational approval or quote rewriting."""
from collections import defaultdict
from contextlib import ExitStack
import re
import pipeline_core as v
import workflow as w
from evidence_matching import matchnorm

# Review triggers, not maximum permitted lengths or medical judgments.
POLICY = {'version': 1, 'page_words_above': 500, 'page_fraction_at_least': .85,
          'fraction_min_words': 150, 'record_words_above': 1000}


def occurrences(text, needle):
    """Include overlapping matches; str.count alone can miss ambiguity."""
    return [m.start() for m in re.finditer('(?='+re.escape(needle)+')', text)] if needle else []


def select_passage(text, start, end):
    """Explicit unique inclusive start/exclusive end; no whole-page default."""
    if not start or not end:
        raise ValueError('Supply explicit nonempty selection boundaries')
    starts, ends = occurrences(text, start), occurrences(text, end)
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError('Selection boundaries must each occur exactly once')
    if ends[0] < starts[0]+len(start):
        raise ValueError('Selection end must follow start')
    return text[starts[0]:ends[0]].strip()


def union(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    return merged


def analyze(records, evidence, pages):
    """Pure checks. pages maps (source SHA256, PDF page) to original native text."""
    groups, totals, errors = {}, {}, []
    for record in records:
        by_page = defaultdict(list)
        ids = record['evidence_ids']
        if len(ids) != len(set(ids)):
            errors.append({'reason': 'duplicate_evidence_id', 'record_ids': [record['id']]})
        for eid in ids:
            e = evidence[eid]
            by_page[(e['source_sha256'], e['pdf_page'])].append(eid)
        group_ids, total, complete = [], 0, True
        for (sha, page), eids in by_page.items():
            gid = 'selection-'+w.semantic([sha, page, sorted(set(eids))])[:20]
            group_ids.append(gid)
            if gid not in groups:
                full = matchnorm(pages[(sha, page)])
                spans, unavailable, problems = [], [], []
                for eid in sorted(set(eids)):
                    e = evidence[eid]
                    if e.get('reviewed_coordinates'):
                        unavailable.append('reviewed_coordinates')
                    if not e.get('passages'):
                        unavailable.append('no_native_passages')
                    for passage in e.get('passages', []):
                        quote = matchnorm(passage)
                        found = occurrences(full, quote)
                        if not found:
                            problems.append('absent_or_empty_passage:'+eid)
                        elif len(found) != 1:
                            unavailable.append('ambiguous_native_match:'+eid)
                        else:
                            spans.append((found[0], found[0]+len(quote)))
                merged = union(spans)
                selected_chars = sum(b-a for a,b in merged)
                overlap = sum(b-a for a,b in spans)-selected_chars
                if overlap:
                    problems.append('overlapping_passages')
                words = sum(len(full[a:b].split()) for a,b in merged)
                fraction = selected_chars/len(full) if full else None
                reasons = []
                if words > POLICY['page_words_above']:
                    reasons.append('large_page_selection')
                if fraction is not None and fraction >= POLICY['page_fraction_at_least'] and words >= POLICY['fraction_min_words']:
                    reasons.append('near_whole_page')
                if unavailable:
                    reasons.append('native_metrics_incomplete')
                groups[gid] = {'id': gid, 'source_sha256': sha, 'pdf_page': page,
                    'source_ids': sorted({evidence[eid]['source_id'] for eid in eids}),
                    'evidence_ids': sorted(set(eids)), 'record_ids': [],
                    'selected_words': words, 'page_words': len(full.split()),
                    'selected_fraction': fraction, 'overlapping_chars': overlap,
                    'metrics_complete': not unavailable, 'limitations': sorted(set(unavailable)),
                    'reasons': reasons, 'errors': sorted(set(problems))}
            group = groups[gid]
            group['record_ids'].append(record['id'])
            total += group['selected_words']
            complete = complete and group['metrics_complete']
        # Group identical citation sets; reasons must apply to every listed consumer.
        tid = 'total-'+w.semantic(sorted(group_ids))[:20]
        if tid not in totals:
            totals[tid] = {'id': tid, 'selection_ids': sorted(group_ids), 'record_ids': [],
                           'selected_words': total, 'metrics_complete': complete}
        totals[tid]['record_ids'].append(record['id'])
    flags = []
    for group in groups.values():
        if group['errors']:
            errors.append({'id': group['id'], 'reasons': group['errors'],
                           'evidence_ids': group['evidence_ids'], 'record_ids': group['record_ids']})
        if group['reasons']:
            flags.append({k: group[k] for k in ('id', 'reasons', 'evidence_ids', 'record_ids')})
    for total in totals.values():
        if total['selected_words'] > POLICY['record_words_above']:
            flags.append({'id': total['id'], 'reasons': ['large_record_total'],
                          'record_ids': total['record_ids'], 'selected_words': total['selected_words']})
    return {'policy': dict(POLICY), 'groups': list(groups.values()), 'record_totals': list(totals.values()),
            'errors': errors, 'flags': flags}


def inspect(p, content=None, evidence=None):
    """Read originals once per source/page; do not build PDFs or write receipts."""
    content = content if content is not None else v.read(p/'content.json')
    evidence = evidence if evidence is not None else v.read(p/'evidence.json')
    pages, sources, coordinates = {}, {}, {}
    with ExitStack() as stack:
        docs = {}
        for eid, e in evidence.items():
            source = v.get_source(e['source_id'])
            if source['role'] != 'textbooks' or source['sha256'] != e['source_sha256']:
                raise ValueError('Invalid evidence source: '+eid)
            path = w.project_path(source['path'])
            if source['source_id'] not in sources:
                if v.digest(path) != source['sha256']:
                    raise ValueError('Changed original textbook: '+source['source_id'])
                sources[source['source_id']] = source['sha256']
            sha = source['sha256']
            if sha not in docs:
                docs[sha] = stack.enter_context(v.fitz.open(path))
            page = e['pdf_page']
            if type(page) is not int or not 1 <= page <= len(docs[sha]):
                raise ValueError('Invalid original PDF page: '+eid)
            if (sha, page) not in pages:
                pages[(sha, page)] = docs[sha][page-1].get_text()
            if e.get('reviewed_coordinates'):
                receipt = w.safe_tree(p/'review'/w.safe_name(e['reviewed_coordinates']['receipt']))
                coordinates[eid] = v.digest(receipt) if receipt.exists() else None
    report = analyze(w.records(content), evidence, pages)
    specification = (v.BASE/'SPECIFICATION.md').read_text(encoding='utf-8')
    requirement = next((line for line in specification.splitlines() if line.startswith('- **SG-035')),
                       specification)  # Disposable fixtures may have a plain standard.
    report['key'] = w.semantic({'content': content, 'evidence': evidence, 'sources': sources,
        'coordinates': coordinates, 'policy': POLICY, 'requirement': requirement,
        'engine': {name: v.digest(v.ROOT/'scripts'/name) for name in ['selection_checks.py','evidence_matching.py']},
        'pymupdf': v.fitz.VersionBind})
    report['status'] = 'errors' if report['errors'] else 'review_required'
    return report


def require_clean(report):
    if report['errors']:
        raise ValueError('Invalid evidence selections; run preflight for details: '+str(report['errors'][:3]))


def scaffold(report):
    return {'key': report['key'], 'verdict': None, 'exceptions': {flag['id']: None for flag in report['flags']}}


def validate_review(report, review):
    require_clean(report)
    if not isinstance(review, dict) or review.get('key') != report['key'] or review.get('verdict') != 'pass':
        raise ValueError('Missing or stale independent selection-precision review')
    exceptions = review.get('exceptions')
    if not isinstance(exceptions, dict) or set(exceptions) != {f['id'] for f in report['flags']}:
        raise ValueError('Every current selection flag needs an exact review disposition')
    if not all(isinstance(reason, str) and reason.strip() for reason in exceptions.values()):
        raise ValueError('Justify each accepted selection exception for all listed consumers')
