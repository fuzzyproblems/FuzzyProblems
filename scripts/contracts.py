"""Structural gates complement, and cannot replace, fresh educational review."""
import re,math
import pipeline_core as v
import workflow as w
import verification_policy as policy
import diagnostics as diag

def require(condition,message):
    if not condition:raise ValueError(message)

@diag.observe('structure_checks')
def validate_structure(p):
    for name in ['scope.json','content.json','coverage.json','evidence.json']:w.safe_tree(p/name)
    scope=v.read(p/'scope.json');c=v.read(p/'content.json');coverage=v.read(p/'coverage.json');ev=v.read(p/'evidence.json')
    diag.annotate(input_key=w.semantic([scope,c,coverage,ev]))
    le,original=w.select_scope(scope['lesson_id'],None if scope['full_lesson'] else scope['objective_ids'])
    if le.get('intake_version'):
        require(scope.get('dependency_version')==2,'Mixed-document units require their scoped dependency contract')
    require([o['id'] for o in original]==scope['objective_ids'],'Changed requested scope')
    w.scope_current(scope)
    require(c['objectives']==original,'Preserve complete original objective records')
    require(c['authors'] and all(isinstance(x,str) and x.strip() for x in c['authors']),'Record authors internally')
    w.author_models(c)
    require(c.get('quantity_rationale','').strip(),'Explain practice/card quantities for this requested scope')
    require([ch['objective_id'] for ch in c['chapters']]==scope['objective_ids'],'Missing, merged, reordered or additional chapter')
    require([ch['objective_id'] for ch in coverage['chapters']]==scope['objective_ids'],'Coverage chapter mismatch')
    require(not coverage.get('unresolved_gaps'),'Required gaps remain; cannot publish complete')
    record_ids=[];block_ids=set();files=[];section_ids=set()
    for obj,ch,cv in zip(original,c['chapters'],coverage['chapters']):
        w.safe_name(ch['file']);require(ch['file'].endswith('.html') and ch['file'].casefold() not in {'index.html','practice.html','answers.html','anki.html'},'Invalid chapter filename');files.append(ch['file'])
        for key in ['original_number','wording','pbl_labels']:require(ch[key]==obj.get(key,[]),'Changed original objective '+key)
        require(ch.get('title') and ch.get('teaching_approach') and ch['sections'],'Unwritten chapter')
        require(set(ch.get('related_objective_ids',[]))<=set(scope['objective_ids']),'Unknown chapter cross-link')
        local={b['id']:b for s in ch['sections'] for b in s['blocks']}
        require(local,'Chapter has no teaching')
        for sec in ch['sections']:
            require(sec.get('title') and sec.get('blocks'),'Empty section');w.safe_name(sec['id']);require(sec['id'] not in section_ids,'Repeated section ID');section_ids.add(sec['id'])
        for b in local.values():
            require(b['type'] in {'paragraph','table','figure'} and b.get('text'),'Unsupported/empty teaching block')
            if b['type']=='table':require(b.get('headers') and b.get('rows') and all(len(r)==len(b['headers']) for r in b['rows']),'Ragged table')
            if b['type']=='figure':require(b.get('alt') and b.get('figure'),'Figure needs source-bound rendering definition and alt text')
        block_ids.update(local)
        require(cv.get('complete_wording_interpretation') and cv.get('depth_rationale'),'Missing objective-specific explanation/depth plan')
        components=cv['components'];ids=[x['id'] for x in components]
        require(len(ids)==len(set(ids)) and set(w.objective_requirements(obj))<=set(ids),'Every original component/required item needs guide-local accounting')
        for x in components:
            require(x['role'] in {'direct','supporting_prerequisite','extension'},'Invalid coverage role')
            require(x.get('requirement') and x.get('completion_test') and x['status']=='covered','Unresolved component')
            require(x['guide_blocks'] and set(x['guide_blocks'])<=set(local),'Questions/cards/crosslinks cannot replace local teaching')
            cited={eid for bid in x['guide_blocks'] for eid in local[bid]['evidence_ids']}
            require(x['evidence_ids'] and set(x['evidence_ids'])<=cited,'Component evidence is not taught/cited in this chapter')
    require(len(files)==len({name.casefold() for name in files}),'Repeated or case-colliding chapter file')
    import intake
    if scope.get('practice_contract',{}).get('version')==2:
        wanted=set(scope['practice_contract']['types'])
        actual={q.get('kind','short_answer') for q in c['saqs']}|({'sba'} if c['sbas'] else set())
        require(wanted and wanted<=intake.PRACTICE_TYPES and actual==wanted and c['cards'],'Every declared practice type and Anki material is required')
    else:require(c['saqs'] and c['sbas'] and c['cards'],'Full pack requires SAQ, SBA/MCQ and Anki material')
    def positive_mark(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0
    for q in c['saqs']:
        require(q.get('kind','short_answer') in intake.PRACTICE_TYPES-{'sba'},'Unknown constructed-response practice type')
        require(q.get('prompt') and q.get('explanation') and q.get('marking_points'),'Incomplete SAQ')
        require(positive_mark(q['marks']) and all(x.get('text') and positive_mark(x['marks']) for x in q['marking_points']) and math.isclose(sum(x['marks'] for x in q['marking_points']),q['marks'],rel_tol=0,abs_tol=1e-9),'SAQ marking total mismatch')
    for q in c['sbas']:
        require(q.get('prompt') and 3<=len(q['options'])<=6 and q['correct'] in q['options'] and set(q['rationales'])==set(q['options']) and all(q['rationales'].values()) and q['marks']==1,'Incomplete SBA or distractor explanations')
    for q in c['saqs']+c['sbas']:
        require(q.get('guide_blocks') and set(q['guide_blocks'])<=block_ids,'Missing practice-to-chapter mapping')
    from anki_export import canonical_tags
    for card in c['cards']:
        require(card.get('front') and card.get('back'),'Incomplete card')
    canonical_tags(c,scope)
    for rec in w.records(c):
        w.safe_name(rec['id']);record_ids.append(rec['id'])
        require(rec.get('evidence_ids') and set(rec['evidence_ids'])<=set(ev),'Unsupported authored record')
        require(rec.get('objective_ids') and set(rec['objective_ids'])<=set(scope['objective_ids']),'Record objective mapping missing')
    require(len(record_ids)==len(set(record_ids)) and not set(record_ids)&section_ids,'Duplicate HTML/record IDs')
    for eid,e in ev.items():
        w.safe_name(eid);source=v.get_source(e['source_id'])
        require(source['role']=='textbooks' and e['source_sha256']==source['sha256'],'Invalid evidence source')
        require(isinstance(e['pdf_page'],int) and 1<=e['pdf_page']<=source['pdf_pages'],'Evidence page out of bounds')
        require(e.get('passages') or e.get('reviewed_coordinates') or (e.get('highlight_optional') is True and e.get('limitations')),'Evidence needs source text/coordinates or a documented optional-highlight limitation')
        require(e.get('context') and 'limitations' in e,'Evidence context/limitations missing')
        intake.source_snapshot([e['source_id']])
    if scope.get('claim_binding'):
        import claim_coverage
        bindings=claim_coverage.bindings(c,ev,scope['claim_binding'])
        require(not bindings['errors'],'Incomplete claim bindings; every teaching unit needs a quoted support or an explicit exemption (FORMAT "Claim bindings"): '+str(bindings['errors'][:2]))
    return c,coverage,ev

def test_guard(test):
    if test:
        import tempfile
        root=v.ROOT.resolve()
        require(root.is_relative_to(__import__('pathlib').Path(tempfile.gettempdir()).resolve()) and (root/'.synthetic-fixture').is_file(),'Synthetic receipts only in disposable test root')

@diag.observe('educational_receipt_gate')
def review_gate(p,test=False,inputs=None):
    test_guard(test);c,coverage,ev=validate_structure(p);r=v.read(p/'review/independent.json')
    scope=v.read(p/'scope.json')
    diag.annotate(input_key=w.semantic(r.get('inputs')),receipt_sha256=v.digest(p/'review/independent.json'))
    require(r.get('kind')==('synthetic_test' if test else 'educational'),'Synthetic records never approve production')
    w.identity(r,c['authors']);require(policy.same_inputs(r.get('inputs'),inputs if inputs is not None else w.inputs(p)),'Missing or stale independent review inputs')
    require(r.get('guide_only_assessed') is True,'Assess guide itself, not companions')
    axes=('factual_support','chapter_coverage','explanatory_depth','educational_quality')
    if not test:
        require(c.get('entry_dependencies'),'Real packs need reusable reviewed knowledge entries')
        for rec in w.records(c):require(rec.get('entry_ids') and set(rec['entry_ids'])<=set(c['entry_dependencies']),'Each teaching/practice/card record needs checked knowledge dependencies plus original evidence')
    ids={x['id'] for x in w.records(c)}
    if r.get('mode','full')=='targeted':
        baseline_path=p/'review'/w.safe_name(r['baseline_receipt'])
        require(baseline_path.name!='independent.json' and not baseline_path.is_symlink(),'Preserve a distinct immutable prior receipt')
        require(v.digest(baseline_path)==r['baseline_sha256'],'Baseline receipt changed')
        baseline=v.read(baseline_path);w.identity(baseline,c['authors'])
        accepted_path=w.safe_tree(p/'review/accepted'/f'{r["baseline_sha256"]}.json')
        accepted=v.read(accepted_path)
        require(accepted.get('status')=='pass' and accepted.get('kind')==('synthetic_test' if test else 'educational_pack') and accepted.get('review_sha256')==r['baseline_sha256'] and policy.same_inputs(accepted.get('inputs'),baseline.get('inputs')),'Baseline was not accepted at the complete gate')
        require(baseline.get('kind')==r['kind'] and all(baseline.get('verdicts',{}).get(a)=='pass' for a in axes),'Invalid baseline approval')
        require(baseline.get('guide_only_assessed') and baseline.get('chapters') and baseline.get('original_pages_inspected') and baseline.get('independent_searches'),'Baseline is not an adequate independent review')
        old=baseline['inputs']['records'];now=r['inputs']['records']
        require(set(baseline.get('reviewed_records',[]))|set(baseline.get('retained_records',[]))==set(old),'Baseline has unreviewed records')
        changed={rid for rid in now if now[rid]!=old.get(rid)};removed=set(old)-set(now);retained=ids-changed
        require(set(r.get('reviewed_records',[]))==changed and set(r.get('retained_records',[]))==retained,'Targeted review must inspect every changed/new record and explicitly retain only unchanged supported records')
        require(r.get('delta')=={'changed_records':sorted(changed),'removed_records':sorted(removed),'changed_inputs':policy.changed_inputs(baseline['inputs'],r['inputs'])},'Targeted delta is not exact')
        require(r.get('current_standard_assessment') and r.get('meaning_and_depth_assessment'),'Targeted reuse must reconcile current standards and complete chapter meaning/depth')
    else:
        require(r.get('mode','full')=='full' and set(r.get('reviewed_records',[]))==ids,'Unreviewed teaching, answer, distractor, marking or card')
    require(all(r.get('verdicts',{}).get(k)=='pass' for k in axes),'All four independent review axes must pass')
    if scope.get('claim_binding'):
        require(isinstance(r.get('claim_binding_assessment'),str) and r['claim_binding_assessment'].strip(),'Assess the declared claim bindings and their exemptions')
    require(r.get('independent_searches') and r.get('original_pages_inspected'),'Review must inspect originals and search beyond selection')
    rr=r.get('chapters',[]);require([x['objective_id'] for x in rr]==[x['objective_id'] for x in coverage['chapters']],'Chapter review missing')
    for cv,ch,rc in zip(coverage['chapters'],c['chapters'],rr):
        require(rc.get('teaching_approach_assessment') and rc.get('complete_wording_assessment'),'Missing subject-appropriate teaching judgment')
        for axis in axes:require(rc.get(axis)=='pass','Chapter axis failed')
        rows=rc.get('components',[]);require([x['id'] for x in rows]==[x['id'] for x in cv['components']],'Incomplete component review')
        for x,y in zip(cv['components'],rows):
            require(y.get('guide_blocks')==x['guide_blocks'] and y.get('evidence_ids')==x['evidence_ids'],'Review map differs from authored map')
            require(all(y.get(a)=='pass' for a in axes) and y.get('rationale') and y.get('evidence_assessment'),'Component review is not adequate')
    import selection_checks
    selection_checks.validate_review(selection_checks.inspect(p,c,ev),r.get('selection_review'))
    return r
