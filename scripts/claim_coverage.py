"""Bind every teaching unit to its quoted support or a declared exemption.

Structural checks enforce complete claim tiling and current quoted spans.
Advisory acronym and quotation signals help independent review; they do not
establish factual support or educational adequacy.
"""

import json
import re
import sys
from pathlib import Path

import pipeline_core as v
import workflow as w

BINDING_POLICY = {
    'version': 1,
    'max_supported_unit_words': 60,
    'exemptions': ['instruction', 'framing', 'exclusion', 'figure'],
}

COVERAGE_POLICY = {
    'version': 1,
    'fragment_min_chars': 60,
    'acronym_max_length': 8,
    }

WORD = re.compile(r'[A-Za-z][A-Za-z0-9]*')
TERMINAL = re.compile(r'[.:;!?)\]]\s*$')
# Roman numerals read as acronyms and are never a claim about a named entity.
ROMAN = frozenset({'I', 'II', 'III', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'})


def normalise(text):
    return ' '.join((text or '').split())


def variants(term):
    """Conservative inflection/suffix tolerance for the advisory signals."""
    out = {term}
    if term.endswith('s') and not term.endswith('ss'):
        out.add(term[:-1])
    if term.endswith('es') and len(term) > 4:
        out.add(term[:-2])
    if term.endswith('ies') and len(term) > 4:
        out.add(term[:-3]+'y')
    if term.endswith('ing') and len(term) > 5:
        out.add(term[:-3])
        out.add(term[:-3]+'e')
    if term.endswith('ed') and len(term) > 4:
        out.add(term[:-2])
        out.add(term[:-1])
    for suffix in ('al', 'ic', 'ine', 'ous', 'ary', 'ial', 'ian'):
        if term.endswith(suffix) and len(term)-len(suffix) >= 4:
            out.add(term[:-len(suffix)])
    if term.endswith('us') and len(term) > 5:
        out.add(term[:-2])
    if term.endswith('is') and len(term)-2 >= 4:
        out.add(term[:-2])
    if term.endswith('um') and len(term) > 5:
        out.add(term[:-2])
    if term.endswith('y') and len(term) > 4:
        out.add(term[:-1])
    if term.endswith('e') and len(term) > 4:
        out.add(term[:-1])
    return {x for x in out if x}


def vocabulary(texts):
    out = set()
    for text in texts:
        for token in (m.group(0).lower() for m in WORD.finditer(text or '')):
            out |= variants(token)
    return out


def acronyms(text):
    """Short capitalised tokens such as GnRH, FSH, IVF, ESBLs, MRSA."""
    out = set()
    for match in WORD.finditer(text or ''):
        token = match.group(0)
        if len(token) > COVERAGE_POLICY['acronym_max_length'] or not token[0].isupper():
            continue
        if token in ROMAN:
            continue
        if sum(1 for char in token if char.isupper()) >= 2:
            out.add(token)
    return out


def records(content):
    """Every record with its canonical teaching parts, in reading order.

    ``parts`` defines the text a binding must tile; ``text`` is those parts
    joined exactly as the tiling check compares them.
    """
    out = []

    def add(row, kind, parts):
        parts = [p for p in parts if p]
        out.append({'id': row['id'], 'kind': kind, 'parts': parts, 'text': normalise(' '.join(parts)),
                    'evidence_ids': list(row.get('evidence_ids') or []),
                    'claims': row.get('claims')})

    for chapter in content.get('chapters', []):
        for section in chapter.get('sections', []):
            for block in section.get('blocks', []):
                kind = block.get('type') or 'block'
                parts = [block.get('text', '')]
                if kind == 'figure':
                    parts.append(block.get('alt', ''))
                if kind == 'table':
                    parts += list(block.get('headers') or [])
                    for row in block.get('rows') or []:
                        parts += [str(cell) for cell in row]
                add(block, kind, parts)
    for saq in content.get('saqs', []):
        add(saq, 'saq', [saq.get('prompt', '')]
            + [row.get('text', '') for row in saq.get('marking_points', [])]
            + [saq.get('explanation', '')])
    for sba in content.get('sbas', []):
        correct = sba.get('correct')
        options = sba.get('options') or {}
        # Option wording is question material, not a taught claim; the
        # rationales carry the statements, in option order.
        add(sba, 'sba', [sba.get('prompt', '')] + list((sba.get('rationales') or {}).values()))
    for card in content.get('cards', []):
        add(card, 'card', [card.get('front', ''), card.get('back', '')])
    return out


def scope_declaration(p):
    """The claim-binding declaration lives in scope.json, which authoring does
    not rewrite; storing it in content.json would let a regenerated content file
    silently drop the contract."""
    path = p/'scope.json'
    scope = v.read(path) if path.is_file() else {}
    return scope.get('claim_binding') if isinstance(scope, dict) else None


def review_sections(content):
    """Stable selectors for complete teaching in its original reading order."""
    sections = []
    for ci, chapter in enumerate(content.get('chapters', []), 1):
        for si, section in enumerate(chapter.get('sections', []), 1):
            sections.append((f'chapter-{ci}/section-{si}',
                             {'chapter': chapter.get('title'), 'objective_id': chapter['objective_id'],
                              'section': section.get('title')}, section['blocks']))
    for name in ('saqs', 'sbas', 'cards'):
        sections.append((name, {'section': name}, content.get(name, [])))
    return sections


REVIEW_VIEW_MAX_CHARS = 24000


def review_view(p, section=None, start=0, limit=8, receipt=False):
    """Read-only projection. Quotes are shared within a page; nothing is approved.

    All record fields are retained except expanded bindings, whose quoted text is
    replaced by references to the quote table. Pagination never clips a record.
    """
    if start < 0 or not 1 <= limit <= 20:
        raise ValueError('Use start >= 0 and a limit from 1 to 20 records.')
    if receipt and section:
        raise ValueError('Choose a section or the receipt view, not both.')
    content, evidence = v.read(p/'content.json'), v.read(p/'evidence.json')
    sections = review_sections(content)
    if receipt:
        request = v.read(p/'review/request.json')
        # Preserve every decision field; large dependency objects stay on disk.
        hidden = {'inputs', 'read', 'instructions', 'selection_diagnostics'}
        return {'status': 'review_scaffold_not_approval',
                'scaffold': {k: value for k, value in request.items() if k not in hidden}}
    if section is None:
        return {'status': 'review_outline_not_approval', 'objectives': content['objectives'],
                'scope': v.read(p/'scope.json'), 'coverage': v.read(p/'coverage.json'),
                'chapters': [{k: value for k, value in ch.items() if k != 'sections'}
                             for ch in content.get('chapters', [])],
                'sections': [{'selector': key, **context, 'records': len(rows),
                              'record_ids': [r['id'] for r in rows]}
                             for key, context, rows in sections],
                'entries': list(content.get('entry_dependencies', {})),
                'read': 'Read each section in order, then all SAQs, SBAs and cards. '
                        'Continue while next_start is non-null. Fetch original context as needed.'}
    match = next((x for x in sections if x[0] == section), None)
    if match is None:
        raise ValueError('Unknown section; run review-view PACK to list selectors.')
    _, context, rows = match
    if start > len(rows) or (start == len(rows) and rows):
        raise ValueError('Start is outside this section.')
    report = inspect(p, content, evidence)
    selection_path = p/'review/selection-diagnostics.json'
    selections = v.read(selection_path) if selection_path.exists() else {}
    source_cache = {}

    def chunk(chosen):
        quotes, quote_keys, notes, note_keys, sources, evidence_view, projected = {}, {}, {}, {}, {}, {}, []

        def note_ref(value):
            key = json.dumps(value, sort_keys=True, ensure_ascii=False)
            if key not in note_keys:
                ref = 'n'+str(len(notes)+1)
                note_keys[key] = ref
                notes[ref] = value
            return note_keys[key]

        def quote_ref(eid, passage):
            e = evidence[eid]
            # Equal text on different source pages must never be conflated.
            key = (e['source_id'], e['source_sha256'], e['pdf_page'], normalise(passage))
            if key not in quote_keys:
                ref = 'q'+str(len(quotes)+1)
                quote_keys[key] = ref
                quotes[ref] = {'source_id': e['source_id'], 'pdf_page': e['pdf_page'], 'text': passage}
            return quote_keys[key]

        for row in chosen:
            for eid in row.get('evidence_ids', []):
                if eid in evidence_view:
                    continue
                e = evidence[eid]
                if e['source_id'] not in sources:
                    sid = e['source_id']
                    if sid not in source_cache:
                        source_cache[sid] = v.get_source(sid)
                    source = source_cache[sid]
                    sources[e['source_id']] = {k: source[k] for k in
                                              ('path', 'title', 'edition') if k in source}
                evidence_view[eid] = {'source_id': e['source_id'], 'pdf_page': e['pdf_page'],
                                      'quotes': [quote_ref(eid, q) for q in e.get('passages', [])],
                                      'context_note': note_ref(e.get('context')),
                                      'limitations_note': note_ref(e.get('limitations', []))}
                for key in ('reviewed_coordinates', 'highlight_optional'):
                    if key in e:
                        evidence_view[eid][key] = e[key]
            teaching = {k: value for k, value in row.items() if k != 'claims'}
            units = []
            for unit in row.get('claims', []):
                value = {'text': unit['text']}
                if 'support' in unit:
                    support = unit['support']
                    eid, passage = support['evidence_id'], support['passage']
                    if eid not in row.get('evidence_ids', []) or normalise(passage) not in [
                            normalise(q) for q in evidence[eid].get('passages', [])]:
                        raise ValueError('Invalid binding in '+row['id']+'; run review-handoff.')
                    value['support'] = {'evidence_id': eid, 'quote': quote_ref(eid, passage)}
                else:
                    value['exempt'] = unit.get('exempt')
                units.append(value)
            # For a paragraph, ordered units already supply the complete prose.
            # Complex records retain their layout/mark allocation and field labels.
            if row.get('type') == 'paragraph' and units and normalise(' '.join(
                    u['text'] for u in units)) == normalise(row.get('text', '')):
                teaching.pop('text', None)
            projected.append({'teaching': teaching, 'claims_in_reading_order': units})
        ids = {r['id'] for r in chosen}
        next_start = start+len(chosen)
        return {'status': 'review_view_not_approval', **context, 'selector': section,
                'start': start, 'total_records': len(rows),
                'next_start': next_start if next_start < len(rows) else None,
                'records': projected, 'evidence': evidence_view, 'quotes': quotes, 'notes': notes, 'sources': sources,
                'selection_flags': [r for r in selections.get('flags', [])
                                    if ids.intersection(r.get('record_ids', []))],
                'selection_note': 'Flags are from the last handoff/request; confirm current inputs with review-changes.',
                'attention': {key: [r for r in report[key] if ids.intersection(r.get('record_ids', []))]
                              for key in ('acronym_gaps', 'quote_fragments')},
                'records_without_quoted_spans': sorted(ids.intersection(report['records_without_quoted_spans']))}

    # A record count alone does not bound long questions or their evidence.
    # Fit complete records to the CLI's serialized output; never clip content.
    chosen = rows[start:start+limit]
    result = chunk(chosen)
    while len(chosen) > 1 and len(json.dumps(result, ensure_ascii=False, indent=2)) > REVIEW_VIEW_MAX_CHARS:
        chosen = chosen[:-1]
        result = chunk(chosen)
    if len(json.dumps(result, ensure_ascii=False, indent=2)) > REVIEW_VIEW_MAX_CHARS:
        result['size_note'] = 'One complete record exceeds the soft character target; nothing was truncated.'
    return result


def bindings(content, evidence, declaration=None):
    """Validate declared claim bindings. Empty errors mean the contract holds."""
    declared = bool(declaration)
    errors, exemptions = [], []
    units = supported = 0
    exempt_counts = {name: 0 for name in BINDING_POLICY['exemptions']}
    missing = []
    if declared and declaration.get('version') != BINDING_POLICY['version']:
        errors.append({'record_ids': [], 'reason': 'unsupported_binding_version',
                       'detail': str(declaration.get('version'))})
        return {'declared': True, 'errors': errors, 'exemptions': [], 'units': [],
                'summary': {'records': len(records(content)), 'units': 0, 'supported_units': 0,
                            'exempt_units': exempt_counts, 'records_without_bindings': [],
                            'oversized_units': [], 'declared_version': declaration.get('version')}}
    for record in records(content):
        if not record['text']:
            continue
        claims = record['claims']
        if not isinstance(claims, list) or not claims:
            if declared:
                missing.append(record['id'])
                errors.append({'record_ids': [record['id']], 'reason': 'record_has_no_bindings',
                               'detail': 'every record tiles its teaching text with claims[]'})
            continue
        tiled, record_error = [], False
        for index, unit in enumerate(claims):
            if not isinstance(unit, dict) or not normalise(unit.get('text')):
                errors.append({'record_ids': [record['id']], 'unit': index,
                               'reason': 'unit_needs_text', 'detail': json.dumps(unit)[:120]})
                record_error = True
                continue
            tiled.append(normalise(unit['text']))
            if unit.get('exempt') is not None:
                if unit.get('support') is not None:
                    errors.append({'record_ids': [record['id']], 'unit': index,
                                   'reason': 'unit_has_support_and_exempt',
                                   'detail': normalise(unit['text'])[:120]})
                    record_error = True
                elif unit['exempt'] not in BINDING_POLICY['exemptions']:
                    errors.append({'record_ids': [record['id']], 'unit': index,
                                   'reason': 'unknown_exemption', 'detail': str(unit['exempt'])})
                    record_error = True
                else:
                    exempt_counts[unit['exempt']] += 1
                    exemptions.append({'record_ids': [record['id']], 'record_kind': record['kind'],
                                       'exempt': unit['exempt'], 'text': normalise(unit['text'])})
                continue
            support = unit.get('support')
            if not isinstance(support, dict):
                errors.append({'record_ids': [record['id']], 'unit': index,
                               'reason': 'unit_needs_support_or_exemption',
                               'detail': normalise(unit['text'])[:120]})
                record_error = True
                continue
            eid = support.get('evidence_id')
            passage = normalise(support.get('passage'))
            unit_error = False
            if eid not in record['evidence_ids']:
                errors.append({'record_ids': [record['id']], 'unit': index,
                               'reason': 'support_evidence_not_cited', 'detail': str(eid)})
                record_error = unit_error = True
            elif passage not in [normalise(x) for x in (evidence.get(eid) or {}).get('passages') or []]:
                errors.append({'record_ids': [record['id']], 'unit': index,
                               'reason': 'support_passage_not_quoted',
                               'detail': f"{eid}: {passage[:90]}"})
                record_error = unit_error = True
            elif len(normalise(unit['text']).split()) > BINDING_POLICY['max_supported_unit_words']:
                errors.append({'record_ids': [record['id']], 'unit': index,
                               'reason': 'supported_unit_too_long',
                               'detail': '%d words' % len(normalise(unit['text']).split())})
                record_error = unit_error = True
            if not unit_error:
                supported += 1
        units += len(claims)
        if normalise(' '.join(tiled)) != record['text']:
            errors.append({'record_ids': [record['id']], 'reason': 'undeclared_teaching_text',
                           'detail': _first_difference(record['text'], normalise(' '.join(tiled)))})
            record_error = True
        if record_error:
            missing.append(record['id'])
    return {'declared': declared, 'errors': errors, 'exemptions': exemptions,
            'summary': {'records': len(records(content)), 'units': units, 'supported_units': supported,
                        'exempt_units': exempt_counts, 'records_without_bindings': sorted(set(missing)),
                        'oversized_units': [e['record_ids'] for e in errors
                                            if e['reason'] == 'supported_unit_too_long'],
                        'declared_version': (declaration or {}).get('version')}}


def _first_difference(expected, got):
    limit = min(len(expected), len(got))
    index = next((i for i in range(limit) if expected[i] != got[i]), limit)
    return f"first difference at char {index}: teaching ...{expected[max(0,index-40):index+40]!r} vs declared ...{got[max(0,index-40):index+40]!r}"


def analyze(content, evidence, declaration=None):
    """Pure advisory report plus the binding result. No PDF, render or model call."""
    spans_by_record, acronym_gaps, without_spans = [], [], []
    quoted = fragments = 0
    fragment_rows = []
    for record in records(content):
        spans = [passage for eid in record['evidence_ids']
                 for passage in (evidence.get(eid) or {}).get('passages') or []]
        pages = sorted({f"{evidence[eid]['source_id']}:{evidence[eid]['pdf_page']}"
                        for eid in record['evidence_ids'] if eid in evidence})
        spans_by_record.append({'id': record['id'], 'kind': record['kind'], 'pages': pages, 'spans': spans})
        if not spans:
            without_spans.append(record['id'])
            continue
        span_vocabulary = vocabulary(spans)
        absent = sorted(a for a in acronyms(record['text']) if not (variants(a.lower()) & span_vocabulary))
        if absent:
            acronym_gaps.append({'record_ids': [record['id']], 'record_kind': record['kind'],
                                 'acronyms': absent, 'pages': pages,
                                 'evidence_ids': sorted(set(record['evidence_ids']))})
    seen = set()
    for eid, row in evidence.items():
        for passage in row.get('passages') or []:
            quoted += 1
            text = normalise(passage)
            if len(text) < COVERAGE_POLICY['fragment_min_chars'] or TERMINAL.search(text):
                continue
            fragments += 1
            if (eid, text) in seen:
                continue
            seen.add((eid, text))
            fragment_rows.append({'evidence_id': eid,
                                  'page': f"{row['source_id']}:{row['pdf_page']}",
                                  'record_ids': [r['id'] for r in spans_by_record if text in (r['spans'] or [])],
                                  'text': text})
    binding_report = bindings(content, evidence, declaration)
    status = 'flags' if (binding_report['errors'] or acronym_gaps or without_spans) \
        else 'attention' if fragments else 'quiet'
    return {'binding_policy': dict(BINDING_POLICY), 'policy': dict(COVERAGE_POLICY), 'status': status,
            'bindings': binding_report,
            'records_without_quoted_spans': sorted(without_spans),
            'acronym_gaps': acronym_gaps,
            'quote_fragments': sorted(fragment_rows, key=lambda row: (row['page'], row['text'])),
            'spans_by_record': spans_by_record,
            'summary': {'records_checked': len(spans_by_record),
                        'records_with_quoted_spans': len(spans_by_record)-len(without_spans),
                        'quoted_passages': quoted, 'quote_fragments': fragments,
                        'acronym_gap_records': len(acronym_gaps),
                        'records_without_quoted_spans': len(without_spans),
                        'binding_declared': binding_report['declared'],
                        'binding_units': binding_report['summary']['units'],
                        'binding_supported_units': binding_report['summary']['supported_units'],
                        'binding_exempt_units': dict(binding_report['summary']['exempt_units']),
                        'binding_errors': len(binding_report['errors']),
                        'binding_records_incomplete': len(binding_report['summary']['records_without_bindings'])}}


def inspect(p, content=None, evidence=None):
    """Read only the pack's JSON; no PDF, no rendering, no model call."""
    content = content if content is not None else v.read(p/'content.json')
    evidence = evidence if evidence is not None else v.read(p/'evidence.json')
    report = analyze(content, evidence, scope_declaration(p))
    module = v.ROOT/'scripts'/'claim_coverage.py'
    report['engine'] = {module.name: v.digest(module)} if module.is_file() else {}
    return report


def brief(report, exemptions=8, fragments=6, acronyms_per_record=5):
    """Compact reviewer-facing lines; never a verdict."""
    lines = []
    bindings = report['bindings']
    if bindings['declared']:
        summary = bindings['summary']
        lines.append(f"- bindings declared: {summary['supported_units']} unit(s) bound to a named quoted passage, "
                     + ', '.join(f"{count} {name}" for name, count in summary['exempt_units'].items() if count)
                     + ' declared exempt.')
        for row in bindings['exemptions'][:exemptions]:
            lines.append(f"- exempt ({row['exempt']}) `{row['record_ids'][0]}` ({row['record_kind']}): {row['text'][:110]}")
        if len(bindings['exemptions']) > exemptions:
            lines.append(f"- ({len(bindings['exemptions'])-exemptions} further declarations in the file)")
    else:
        lines.append('- no claim bindings declared for this pack (pre-binding contract); coverage is judged from the quotes below.')
    for row in report['acronym_gaps']:
        shown = ', '.join(row['acronyms'][:acronyms_per_record])
        lines.append(f"- acronym gap `{row['record_ids'][0]}` ({row['record_kind']}): {shown}")
    if report['records_without_quoted_spans']:
        lines.append('- no quoted span at all: ' + ', '.join(report['records_without_quoted_spans']))
    for row in report['quote_fragments'][:fragments]:
        lines.append(f"- fragment `{row['evidence_id']}` ({row['page']}): ...{row['text'][-90:]}")
    if len(report['quote_fragments']) > fragments:
        lines.append(f"- ({len(report['quote_fragments'])-fragments} further incomplete quotes in the file)")
    return lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print('usage: claim_coverage.py PACK_DIRECTORY', file=sys.stderr)
        return 2
    report = inspect(Path(argv[0]))
    print(json.dumps({'status': report['status'], **report['summary']}, indent=2))
    for line in brief(report):
        print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
