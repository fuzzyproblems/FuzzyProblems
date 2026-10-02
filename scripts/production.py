"""Small local production route. Authoring and independent judgment remain explicit."""
import argparse,json,os,platform,shutil,subprocess,sys
from pathlib import Path
import pipeline_core as v
import workflow as w
import verification_policy as policy
from contracts import require,validate_structure,review_gate,test_guard
import evidence,learner_export,export_privacy,qa,selection_checks,delivery_paths
import diagnostics as diag

def refresh_catalogue():
    """Use the same standalone entry point as a manual library refresh."""
    script=w.safe_tree(v.ROOT/'regenerate_study_guide.py')
    run=subprocess.run([sys.executable,'-B',str(script)],check=True,
                       capture_output=True,text=True,encoding='utf-8')
    result=json.loads(run.stdout)
    result['catalogue']='StudyGuide.html'
    return result

@diag.observe('build')
def build(p,test=False,folder=None):
    test_guard(test);c,coverage,ev=validate_structure(p);deps=w.inputs(p)
    if folder is not None:
        delivery_paths.target(folder)
        v.write(w.safe_tree(p/'delivery.json'),{'folder':folder})
    delivery_folder=delivery_paths.configured_folder(p)
    selection_checks.require_clean(selection_checks.inspect(p,c,ev))
    w.safe_tree(p)
    for rel in ['learner','cache','validation','review','assets']:w.safe_tree(p/rel)
    stage=w.safe_tree(p/'learner');stage.mkdir(exist_ok=True);allowed=learner_export.allowlist(c)
    for name in allowed:w.safe_tree(stage/name)
    require({x.name for x in stage.iterdir()}<=set(allowed),'Unexpected learner staging files; reconcile explicitly')
    ledger=evidence.occurrence_plan(c,ev)
    key=w.semantic({'ledger':ledger,'engine':w.engine('evidence'),'coordinate_reviews':deps['coordinate_reviews']})
    cache=p/'cache/evidence.json';prior=v.read(cache) if cache.exists() else None
    reused=bool(prior and prior['key']==key and all((stage/n).is_file() and v.digest(stage/n)==h for n,h in prior['pdfs'].items()) and (p/'citation-occurrences.json').exists() and prior['ledger_sha256']==v.digest(p/'citation-occurrences.json'))
    diag.emit('cache_decision',component='evidence',input_key=key,previous_key=prior.get('key') if prior else None,
              reused=reused,reason='hit' if reused else 'missing_cache' if not prior else 'dependency_change' if prior['key']!=key else 'artifact_change')
    diag.annotate(input_key=w.semantic(deps),records=len(deps['records']),evidence_selections=len(ev))
    for sid,page in sorted({(e['source_id'],e['pdf_page']) for e in ev.values()}):
        diag.emit('evidence_selected',source_id=sid,pdf_page=page)
    if reused:
        ledger=v.read(p/'citation-occurrences.json');stats=prior['statistics']
    else:
        stats=evidence.compile_evidence(p,stage,c,ev,ledger,test)
        v.write(p/'citation-occurrences.json',ledger)
        v.write(cache,{'key':key,'statistics':stats,'ledger_sha256':v.digest(p/'citation-occurrences.json'),
            'pdfs':{n:v.digest(stage/n) for n in ['evidence-unmarked.pdf','evidence-highlighted.pdf']}})
    images=evidence.figures(p,c,ev)
    learner_export.render(stage,c,ledger,images,v.read(p/'scope.json'),p)
    checks=qa.validate(p,images)
    import anki_preferences
    v.write(p/'build.json',{'status':'built_not_approved','inputs':deps,'engine':w.engine(),'allowlist':allowed,
        'delivery_folder':delivery_folder,
        'anki_preferences':anki_preferences.read_for(v.read(p/'scope.json')),
        'artifacts':{n:v.digest(stage/n) for n in allowed},'evidence':stats,'citation_ledger_sha256':v.digest(p/'citation-occurrences.json')})
    return {'status':'built_not_approved','evidence_reused':reused,'checks':checks,'evidence':stats}

@diag.observe('acceptance_check')
def check(p,test=False):
    test_guard(test);manifest=v.read(p/'build.json');deps=w.inputs(p)
    review_gate(p,test,inputs=deps)
    require(policy.same_inputs(manifest['inputs'],deps) and manifest['engine']==w.engine(),'Build inputs/runtime changed; rebuild selectively')
    require(manifest.get('delivery_folder')==delivery_paths.configured_folder(p),'Delivery location changed; rebuild links and artifact checks')
    import anki_preferences
    require(manifest.get('anki_preferences')==anki_preferences.read_for(v.read(p/'scope.json')),'Anki preferences changed; rebuild Anki and artifact checks')
    c=v.read(p/'content.json');allowed=learner_export.allowlist(c)
    require(manifest['allowlist']==allowed,'Stale explicit learner allowlist')
    require(manifest['artifacts']==export_privacy.check_files(p/'learner',allowed),'Learner payload changed since build')
    require(manifest['citation_ledger_sha256']==v.digest(p/'citation-occurrences.json'),'Changed occurrence ledger')
    qa.layout_gate(p,test)
    review_sha=v.digest(p/'review/independent.json')
    key=w.semantic({'inputs':deps,'engine':w.engine(),'artifacts':manifest['artifacts'],'ledger':manifest['citation_ledger_sha256'],'review':review_sha,'synthetic':test,'delivery_folder':manifest.get('delivery_folder')})
    diag.annotate(input_key=key)
    completion=p/'validation/completion.json'
    prior=v.read(completion) if completion.exists() else None
    diag.emit('cache_decision',component='completion',input_key=key,previous_key=prior.get('validation_key') if prior else None,
              reused=bool(prior and prior.get('validation_key')==key and prior.get('status')=='pass'))
    if prior and prior.get('validation_key')==key and prior.get('status')=='pass':
        return dict(prior,reused=True)
    checks=qa.validate(p)
    result={'status':'pass','kind':'synthetic_test' if test else 'educational_pack',
        'inputs':deps,'artifacts':manifest['artifacts'],'review_sha256':review_sha,
        'validation_key':key,'checks':checks,'verification_policy':'content-first-desktop',
        'highlight_limitations':manifest['evidence'].get('highlight_warnings',[]),
        'full_lesson':v.read(p/'scope.json')['full_lesson']}
    v.write(completion,result)
    accepted=w.safe_tree(p/'review/accepted'/f'{review_sha}.json')
    # Accepted snapshots are immutable.
    if not accepted.exists():v.write(accepted,result)
    return dict(result,reused=False)

@diag.observe('publish')
def publish(p,folder,test=False):
    test_guard(test)
    target=delivery_paths.target(folder)
    configured=delivery_paths.configured_folder(p)
    require(folder==configured if configured is not None else len(delivery_paths.parts(folder))==1,
            'Publication folder differs from checked learner links; rebuild for this location')
    require(not target.exists(),'Never replace an existing export; choose a new version')
    result=check(p,test)
    allowed=learner_export.allowlist(v.read(p/'content.json'))
    delivery=export_privacy.publish_bytes(p/'learner',target,allowed)
    catalogue_result=refresh_catalogue()
    v.write(p/'publication.json',{'folder':target.relative_to(v.ROOT).as_posix(),'kind':result['kind'],
        'completion_sha256':v.digest(p/'validation/completion.json'),'artifacts':result['artifacts'],
        'allowlist':allowed,'catalogue':catalogue_result,'delivery':delivery})
    if result['full_lesson'] and not test:
        v.write(v.BASE/'production-gate.json',{'status':'complete_first_lesson_validated','pack':p.name,
            'completion_sha256':v.digest(p/'validation/completion.json'),'publication_sha256':v.digest(p/'publication.json')})
    if not test:
        from job_queue import record_publication
        try:
            record_publication(v.ROOT,p)
        except (OSError,ValueError,KeyError) as exc:
            print(f'Published successfully; queue receipt could not be recorded: {exc}',file=sys.stderr)
    return {'status':'published','folder':target.relative_to(v.ROOT).as_posix(),'catalogue':catalogue_result}

@diag.observe('review_request')
def review_request(p,baseline=None):
    c,coverage,ev=validate_structure(p)
    selections=selection_checks.inspect(p,c,ev)
    selection_checks.require_clean(selections)
    v.write(w.safe_tree(p/'review/selection-diagnostics.json'),selections)
    result={'status':'review_requested_not_approved','inputs':w.inputs(p),'author_ids':c['authors'],
        'required_records':[r['id'] for r in w.records(c)],'required_axes':['factual_support','chapter_coverage','explanatory_depth','educational_quality'],
        'read':['foundation/SPECIFICATION.md','foundation/guidance/CHAPTER_AUTHORING.md','foundation/guidance/LEARNER_EXPORT.md',
                (p/'scope.json').relative_to(v.ROOT).as_posix(),(p/'content.json').relative_to(v.ROOT).as_posix(),(p/'coverage.json').relative_to(v.ROOT).as_posix(),(p/'evidence.json').relative_to(v.ROOT).as_posix()],
        'instructions':'Fresh independent reviewer using the selected model/effort (SPECIFICATION SG-004): inspect original textbook pages; independently search beyond selected evidence; judge guide alone against complete original wording, prerequisites and appropriate depth. Inspect every answer, marking point, option/distractor and card. Record four separate verdicts and component maps. Never create approval if gaps remain.'}
    # The request doubles as an unapproved receipt scaffold. Copy mechanical
    # bindings, never decisions from the author, a baseline or an existing review.
    unset={axis:None for axis in result['required_axes']}
    result.update(kind='educational',mode='full',reviewer={},fresh_context=None,
        unresolved_findings=None,guide_only_assessed=None,reviewed_records=[],
        verdicts=dict(unset),original_pages_inspected=[],independent_searches=[],
        selection_review=selection_checks.scaffold(selections),
        selection_diagnostics=(p/'review/selection-diagnostics.json').relative_to(v.ROOT).as_posix(),
        chapters=[{'objective_id':ch['objective_id'],**unset,
            'teaching_approach_assessment':None,'complete_wording_assessment':None,
            'components':[{**{k:row[k] for k in ('id','guide_blocks','evidence_ids')},**unset,
                'rationale':None,'evidence_assessment':None} for row in ch['components']]}
            for ch in coverage['chapters']])
    if v.read(p/'scope.json').get('claim_binding'):
        result['claim_binding_assessment']=None
    if baseline:
        prior_path=p/'review'/w.safe_name(baseline);prior=v.read(prior_path)
        before=prior['inputs']['records'];now=result['inputs']['records']
        changed=sorted(k for k in now if now[k]!=before.get(k))
        result.update(mode='targeted',baseline_receipt=baseline,baseline_sha256=v.digest(prior_path),
            required_records=changed,retained_record_candidates=sorted(set(now)-set(changed)),
            delta={'changed_records':changed,'removed_records':sorted(set(before)-set(now)),
                'changed_inputs':policy.changed_inputs(prior['inputs'],result['inputs'])},
            retained_records=[],current_standard_assessment=None,meaning_and_depth_assessment=None,
            preservation_requirement='Fresh current-standard and complete chapter meaning/depth assessment is required; proposed reuse is not approval.')
    v.write(w.safe_tree(p/'review/request.json'),result)
    v.write(w.safe_tree(p/'review/inputs.json'),result['inputs'])
    diag.annotate(input_key=w.semantic(result['inputs']),required_records=len(result['required_records']),
                  retained_candidates=len(result.get('retained_record_candidates',[])))
    return result

def preflight(p,full=False):
    """Independent selection/tag checks; no build, entry approval or publication."""
    from anki_export import canonical_tags
    c,_,ev=validate_structure(p)
    report=selection_checks.inspect(p,c,ev)
    tags=canonical_tags(c,v.read(p/'scope.json'))
    if full:return {'selections':report,'anki_tags':tags}
    return {'status':report['status'],'selection_key':report['key'],
        'selection_groups':len(report['groups']),'errors':len(report['errors']),'review_flags':len(report['flags']),
        'error_evidence_ids':sorted({eid for row in report['errors'] for eid in row.get('evidence_ids',[])}),
        'details':'Use preflight PACK --full for grouped selections, consumers and dispositions.',
        'anki_cards':len(tags),'identity_tags':sorted({t for row in tags.values() for t in row if t.startswith(('Lesson::','Objective::'))}),
        'approval':False}


def impact():
    rows=[]
    for p in sorted((v.ROOT/'packs').iterdir()):
        if not p.is_dir() or not (p/'build.json').exists():continue
        old=v.read(p/'build.json')
        try:
            now=w.inputs(p);changed=policy.changed_inputs(old['inputs'],now)
            rows.append({'pack':p.name,'changed_semantic_dependencies':changed,'render_runtime_changed':old['engine']!=w.engine(),
                'action':'targeted independent re-review, build and artifact checks' if changed else 'reuse current factual review; rebuild affected stages and inspect desktop only if needed'})
        except (ValueError,FileNotFoundError,KeyError) as exc:rows.append({'pack':p.name,'status':'stale','reason':str(exc)})
    return rows

def doctor(host=None):
    import PIL
    from bootstrap import dependencies
    runtime=dependencies('skip')
    result={'python':platform.python_version(),'pymupdf':v.fitz.VersionBind,'pillow':PIL.__version__,
        'sqlite_fts5':bool(v.sqlite3.connect(':memory:').execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0]),
        'wkhtmltopdf':bool(runtime['wkhtmltopdf']),'tesseract':bool(runtime['tesseract']),
        'ocr_language_configured':bool(runtime['language']),
        'network_or_paid_api_required':False,
        'runtime_scope':'local Python, PDF, extraction and OCR only; AI workers use the selected external provider'}
    pins=[line.split('==') for line in (v.ROOT/'requirements.txt').read_text(encoding='utf-8').splitlines() if line and not line.startswith('#')]
    import importlib.metadata
    result['dependency_mismatches']=[name+'=='+version for name,version in pins if importlib.metadata.version(name)!=version]
    result['production_runtime_ready']=result['sqlite_fts5'] and sys.version_info[:2]==(3,12) and not result['dependency_mismatches']
    result['ocr_runtime_ready']=bool(runtime['tesseract'] and runtime['language'])
    result['source_cache_validated']=False
    import host_runtime
    result['host']=host_runtime.describe(v.ROOT,host,probe=False)
    return result

@diag.command
def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='cmd',required=True)
    for cmd in ['catalogue','source-check','impact']:sub.add_parser(cmd)
    sub.add_parser('doctor').add_argument('--host',choices=['codex','claude'])
    prep=sub.add_parser('prepare');prep.add_argument('--lesson',required=True);prep.add_argument('--pack');prep.add_argument('--objectives',nargs='+');prep.add_argument('--scope-reason',default='')
    prep.add_argument('--preview',action='store_true',help='Read exact selected objectives and planning context without creating a pack')
    prep.add_argument('--practice-types',nargs='+',choices=['short_answer','essay','calculation','data_interpretation','practical','sba'])
    it=sub.add_parser('intake',help='Discover and cache changed PDFs once before production')
    it.add_argument('--scan-only',action='store_true');it.add_argument('--ocr',choices=['auto','skip'],default='auto')
    iv=sub.add_parser('intake-view',help='Read up to three complete native/local-OCR discovery pages')
    iv.add_argument('source');iv.add_argument('--start',type=int,default=1);iv.add_argument('--limit',type=int,default=3)
    for command in ['register-source','register-unit','register-style']:
        item=sub.add_parser(command);item.add_argument('record',help='Root-relative JSON record authored from original PDFs')
    tags=sub.add_parser('anki-tags',help='Prompt for or save user-supplied deck tag labels')
    tags.add_argument('pack');tags.add_argument('--school');tags.add_argument('--course');tags.add_argument('--lesson-label')
    tags.add_argument('--tasks-json');tags.add_argument('--use-defaults',action='store_true');tags.add_argument('--prompt',action='store_true')
    for cmd in ['entry-inputs','check-entry']:
        p=sub.add_parser(cmd);p.add_argument('entry')
        if cmd=='check-entry':p.add_argument('--full',action='store_true',help='Print checked dependencies instead of a compact success result')
    rv=sub.add_parser('review-view',help='Read complete teaching and deduplicated evidence in bounded sections')
    rv.add_argument('pack');rv.add_argument('--start',type=int,default=0);rv.add_argument('--limit',type=int,default=8)
    view=rv.add_mutually_exclusive_group();view.add_argument('--section');view.add_argument('--receipt',action='store_true')
    rr=sub.add_parser('review-run',help='Optional CLI reviewer fallback using the shared handoff')
    rr.add_argument('--host',choices=['codex','claude'],help='Optional CLI transport is Codex-only')
    rr.add_argument('pack');rr.add_argument('--model');rr.add_argument('--effort');rr.add_argument('--timeout',type=int)
    rr.add_argument('--resume',action='store_true',help='Continue the recorded reviewer session')
    rr.add_argument('--force',action='store_true',help='Recover a lock only when its owners are stopped')
    rr.add_argument('--dry-run',action='store_true',help='Preview without modifying the pack or calling a model')
    rr.add_argument('--publish',metavar='FOLDER',help='Publish to this output folder when acceptance passes')
    rr.add_argument('--cli',help='Explicit path to the Codex CLI (default: CODEX_CLI_PATH or PATH)')
    rr.add_argument('--validate-only',action='store_true',help='Validate existing receipts and acceptance without launching a reviewer')
    for cmd in ['build','qa','check','review-request','review-handoff','review-changes','inputs','publish','archive','preflight']:
        p=sub.add_parser(cmd);p.add_argument('pack')
        if cmd in {'inputs','review-request','preflight'}:p.add_argument('--full',action='store_true',help='Print full dependencies/diagnostics instead of a compact result')
        if cmd in {'build','publish'}:p.add_argument('--folder',required=cmd=='publish')
        if cmd=='archive':p.add_argument('--name',required=True)
        if cmd=='review-request':p.add_argument('--baseline')
        if cmd=='review-changes':p.add_argument('--handoff',help='Immutable handoff version; defaults to latest')
        if cmd=='qa':
            p.add_argument('--render',action='store_true',help='Optional desktop diagnostics; normal QA uses HTML/data only')
            p.add_argument('--files',nargs='+',help='One to three HTML files for --render')
    s=sub.add_parser('search');s.add_argument('query');s.add_argument('--limit',type=int,default=8);s.add_argument('--recovery',action='store_true');s.add_argument('--source')
    s.add_argument('--role',choices=['textbooks','objectives','pastpapers'],default='textbooks')
    s=sub.add_parser('page');s.add_argument('source');s.add_argument('page',type=int);s.add_argument('--context',type=int,default=0)
    s=sub.add_parser('render');s.add_argument('source');s.add_argument('page',type=int);s.add_argument('destination')
    s=sub.add_parser('ocr');s.add_argument('source');s.add_argument('page',type=int)
    a=parser.parse_args()
    if a.cmd=='review-run':
        import host_runtime
        try:host_runtime.require_codex(v.ROOT,a.host)
        except ValueError as error:parser.exit(2,str(error)+'\n')
    if getattr(a,'pack',None):
        diag.annotate(pack='packs/'+w.safe_name(a.pack))
    if a.cmd=='prepare':result=w.prepare(a.lesson,a.pack,a.objectives,a.scope_reason,a.preview,a.practice_types)
    elif a.cmd=='intake':
        import intake
        result=intake.sync(a.ocr,a.scan_only)
    elif a.cmd=='intake-view':
        import intake
        result=intake.view_source(a.source,a.start,a.limit)
    elif a.cmd in {'register-source','register-unit','register-style'}:
        import intake
        result=getattr(intake,a.cmd.replace('-','_'))(v.read(w.project_path(a.record)))
    elif a.cmd=='anki-tags':
        import anki_preferences
        result=anki_preferences.configure(w.pack(a.pack),school=a.school,course=a.course,lesson=a.lesson_label,
            tasks=v.read(w.project_path(a.tasks_json)) if a.tasks_json else None,use_defaults=a.use_defaults,interactive=a.prompt)
    elif a.cmd=='entry-inputs':result=w.entry_inputs(a.entry)
    elif a.cmd=='check-entry':result=w.entry_dependency(a.entry,w.entry_inputs(a.entry)['entry_hash'])
    elif a.cmd=='doctor':result=doctor(a.host)
    elif a.cmd=='catalogue':result=refresh_catalogue()
    elif a.cmd=='source-check':
        from validate_sources import check_sources
        result=check_sources()
    elif a.cmd=='impact':result=impact()
    elif a.cmd=='search':return v.search(a.query,role=a.role,limit=a.limit,recovery=a.recovery,source=a.source)
    elif a.cmd=='page':return v.page(a.source,a.page,a.context)
    elif a.cmd=='render':return v.render(a.source,a.page,a.destination)
    elif a.cmd=='ocr':return v.ocr(a.source,a.page)
    else:
        p=w.pack(a.pack)
        if a.cmd=='build':result=build(p,folder=a.folder)
        elif a.cmd=='preflight':result=preflight(p,a.full)
        elif a.cmd=='qa':result=qa.layout(p,render=a.render,files=a.files)
        elif a.cmd=='check':result=check(p)
        elif a.cmd=='inputs':
            result=w.inputs(p)
            v.write(p/'review/inputs.json',result)
        elif a.cmd=='review-request':result=review_request(p,a.baseline)
        elif a.cmd=='review-view':
            import claim_coverage
            result=claim_coverage.review_view(p,a.section,a.start,a.limit,a.receipt)
        elif a.cmd in {'review-handoff','review-changes'}:
            import review_handoff
            result=review_handoff.create(p) if a.cmd=='review-handoff' else review_handoff.changes(p,a.handoff)
        elif a.cmd=='publish':result=publish(p,a.folder)
        elif a.cmd=='review-run':
            import review_runner
            options={k:getattr(a,k) for k in ('model','effort','timeout','cli','host') if getattr(a,k) is not None}
            if a.publish:options['publish_folder']=a.publish
            result=review_runner.run(a.pack,force=a.force,dry_run=a.dry_run,
                                     validate_only=a.validate_only,resume=a.resume,**options)
        elif a.cmd=='archive':
            check(p);pub=v.read(p/'publication.json');target=v.ROOT/pub['folder'];w.safe_name(a.name)
            require(a.name.endswith('.zip'),'Archive name must end .zip')
            require(pub['artifacts']=={n:v.digest(target/n) for n in pub['allowlist']},'Changed published bytes')
            result=export_privacy.archive_bytes(target,v.ROOT/'output'/a.name,pub['allowlist'])
    if a.cmd=='check-entry' and not a.full:result={'status':'pass','entry':a.entry}
    elif a.cmd=='check':result={k:result[k] for k in ('status','kind','checks','full_lesson','reused')}
    elif a.cmd in {'inputs','review-request'} and not a.full:
        name='inputs.json' if a.cmd=='inputs' else 'request.json'
        result={'status':result.get('status','inputs_not_approval'),'file':(p/'review'/name).relative_to(v.ROOT).as_posix(),
                'records':len(result.get('records',result.get('required_records',[])))}
    elif a.cmd=='build':
        warnings=result['evidence'].get('highlight_warnings',[])
        result['evidence']=dict(result['evidence'],highlight_warnings=len(warnings))
        if warnings:result['highlight_details']=(p/'build.json').relative_to(v.ROOT).as_posix()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if a.cmd=='doctor' and not result['production_runtime_ready']:
        raise SystemExit(1)
    if a.cmd=='review-run' and result['status'] not in {'accepted','published','dry_run'}:
        raise SystemExit(1)
    if a.cmd=='preflight' and (result['selections']['errors'] if a.full else result['errors']):
        raise SystemExit(1)

if __name__=='__main__':main()
