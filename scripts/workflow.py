"""Lesson scope, dependency identities and preparation; no educational authoring."""
import hashlib, json, re
from pathlib import Path, PurePosixPath, PureWindowsPath
import pipeline_core as v
import verification_policy as policy

def semantic(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

# User-selected models/efforts are eligible; actual runtime support belongs to
# the host/provider. This validates provenance fields, never educational quality.
def model_recorded(who):
    """Require model and effort records without a project-owned tier allowlist."""
    if not isinstance(who,dict):return False
    return all(isinstance(who.get(key),str) and who[key].strip()
               for key in ('model','reasoning'))

def safe_name(value):
    if (not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',value)
            or value.endswith('.') or PureWindowsPath(value).is_reserved()):
        raise ValueError('Use a portable relative file/folder name (no Windows device names or trailing dots)')
    return value

def project_path(value):
    """Serialized project paths use forward slashes and stay relative to root."""
    if not isinstance(value,str) or not value or '\\' in value:
        raise ValueError('Use a root-relative project path with forward slashes')
    path=PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or '..' in path.parts:
        raise ValueError('Project paths must stay relative to the project root')
    result=v.ROOT/path
    if not result.resolve().is_relative_to(v.ROOT.resolve()):raise ValueError('Project path escapes root')
    return result


def safe_tree(path):
    if '..' in Path(path).parts:raise ValueError('Parent traversal is not allowed in write paths')
    path=Path(path).absolute()
    if not path.is_relative_to(v.ROOT):raise ValueError('Write destination must stay in project')
    for item in [path]+list(path.parents):
        if item.is_symlink() or item.is_junction():raise ValueError('Symlink or junction in project write path')
        if item==v.ROOT:break
    return path

def pack(name):
    p=safe_tree(v.ROOT/'packs'/safe_name(name))
    return p

def select_scope(lesson,selected=None):
    import intake
    reg=intake.curriculum()
    matches=[x for x in reg['lessons'] if lesson in {x['id'],x['filename'],x['source_path'],x.get('title')}]
    if len(matches)!=1: raise ValueError('Specify an exact lesson filename or ID')
    le=matches[0]
    if v.digest(v.ROOT/le['source_path'])!=le['source_sha256']: raise ValueError('Changed objective source')
    objs=[o for o in reg['entries'] if o['lesson_id']==le['id'] and o['entry_kind']=='objective']
    if selected:
        ids=[]
        for key in selected:
            found=[o['id'] for o in objs if key in {o['id'],o['original_number']}]
            if len(found)!=1: raise ValueError('Objective selector missing or ambiguous; use its stable ID')
            ids.extend(found)
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate selector')
        objs=[o for o in objs if o['id'] in ids]
    if not objs:raise ValueError('Empty objective scope')
    return le,objs

def scope_context(scope):
    import intake
    lesson,objectives=select_scope(scope['lesson_id'],None if scope['full_lesson'] else scope['objective_ids'])
    return intake.unit_context(lesson,objectives)

def scope_current(scope):
    if scope.get('dependency_version')==2:
        import intake
        if scope.get('curriculum_sha256')!=semantic(intake.teaching_context(scope_context(scope))):
            raise ValueError('Selected curriculum/context changed; reconcile this scope explicitly')
    elif scope['register_sha256']!=v.digest(v.BASE/'curriculum/objective_register.json'):
        raise ValueError('Scope register changed; reconcile explicitly')

def entry_curriculum(links):
    import intake
    reg=intake.curriculum();objects={x['id']:x for x in reg['entries']};lessons={x['id']:x for x in reg['lessons']}
    return {lid:semantic(intake.teaching_context(intake.unit_context(lessons[lid],[objects[x['objective_id']] for x in links if objects[x['objective_id']]['lesson_id']==lid],include_style=False)))
            for lid in sorted({objects[x['objective_id']]['lesson_id'] for x in links})}

def guide_records(content):
    return [b for ch in content['chapters'] for sec in ch['sections'] for b in sec['blocks']]

def records(content): return guide_records(content)+content['saqs']+content['sbas']+content['cards']

def guide_contexts(content):
    guide={r['id']:semantic(r) for r in guide_records(content)}
    return {r['id']:{bid:guide[bid] for bid in r.get('guide_blocks',[])} for r in records(content)}

def objective_requirements(obj):
    return list(dict.fromkeys(obj.get('component_ids',[])+obj.get('required_item_ids',[]))) or [obj['id']]

def objective_labels(obj):
    labels=obj.get('pbl_labels',[])+obj.get('teaching_labels',[])
    labels+=[f['text'] if isinstance(f,dict) else f for f in obj.get('pbl_label_fragments',[])]
    return list(dict.fromkeys(labels))

def prepare(lesson,name=None,selected=None,scope_reason='',preview=False,practice_types=None):
    import intake
    le,objs=select_scope(lesson,selected)
    if not preview:
        if not name:raise ValueError('Specify --pack unless using --preview')
        if selected and not scope_reason.strip(): raise ValueError('Record the user-requested narrower scope')
        p=pack(name)
        if p.exists():raise FileExistsError('Choose a new working version')
    chosen=practice_types or ['short_answer','sba']
    if not chosen or len(chosen)!=len(set(chosen)) or not set(chosen)<=intake.PRACTICE_TYPES:
        raise ValueError('Unsupported or duplicate practice types')
    scope={'lesson_id':le['id'],'lesson_filename':le['filename'],'source_path':le['source_path'],
        'source_sha256':le['source_sha256'],'objective_ids':[o['id'] for o in objs],
        'full_lesson':not selected,'user_scope':scope_reason or ('Selected objectives (preview only)' if selected else 'Full lesson, every original objective'),
        'register_sha256':v.digest(v.BASE/'curriculum/objective_register.json') if (v.BASE/'curriculum/objective_register.json').is_file() else None,
        'claim_binding':{'version':1},'dependency_version':2,
        'curriculum_sha256':semantic(intake.teaching_context(intake.unit_context(le,objs))),
        'practice_contract':{'version':2,'types':chosen},'anki_preferences_required':True,'pack_id':name}
    blueprint=v.read(v.BASE/'curriculum/curriculum_blueprint.json') if (v.BASE/'curriculum/curriculum_blueprint.json').is_file() else {}
    planning={'lesson':le,'status':'Provisional; validate against original objectives and textbooks',
        'curriculum_sha256':scope['curriculum_sha256'],
        'objective_plans':[x for x in blueprint.get('objective_plans',[]) if x.get('objective_id',x.get('id')) in scope['objective_ids']],
        'relationship_edges':[x for x in blueprint.get('relationship_edges',[]) if any(i in json.dumps(x) for i in scope['objective_ids'])]}
    planning['assessment_style']=intake.unit_context(le,objs)['assessment_style']
    if preview:
        return {'status':'scope_preview_not_approval','scope':scope,'objectives':objs,'planning_context':planning}
    p.mkdir(parents=True)
    v.write(p/'scope.json',scope)
    label=le.get('title') or re.sub(r'^LOs?\s+','',Path(le['filename']).stem)
    content={'id':name,'lesson_label':label,'authors':[],'authoring_models':{},'objectives':objs,'entry_dependencies':{},
        'quantity_rationale':'','chapters':[], 'saqs':[],'sbas':[],'cards':[]}
    coverage={'chapters':[],'unresolved_gaps':le.get('unresolved_gaps',[])}
    for index,o in enumerate(objs,1):
        content['chapters'].append({'objective_id':o['id'],'file':f'objective-{index:02d}.html',
            'original_number':o['original_number'],'wording':o['wording'],'pbl_labels':o.get('pbl_labels',[]),
            'title':'','teaching_approach':'','related_objective_ids':[],'sections':[]})
        coverage['chapters'].append({'objective_id':o['id'],'complete_wording_interpretation':'',
            'depth_rationale':'','prerequisites':[],'components':[{'id':cid,'requirement':'',
                'role':'direct','guide_blocks':[],'evidence_ids':[],'completion_test':'','status':'not_started'}
                for cid in objective_requirements(o)]})
    v.write(p/'content.json',content);v.write(p/'coverage.json',coverage);v.write(p/'evidence.json',{})
    v.write(p/'planning-context.json',planning)
    import anki_preferences
    preferences=anki_preferences.initialize(p,label)
    return {'pack':p.relative_to(v.ROOT).as_posix(),'objectives':len(objs),'full_lesson':scope['full_lesson'],'status':'unwritten_unreviewed',
            'anki_tag_prompt':preferences,'planning_context_file':(p/'planning-context.json').relative_to(v.ROOT).as_posix()}

def identity(review,authors):
    who=review.get('reviewer',{})
    if not model_recorded(who):
        raise ValueError('Record the independent reviewer model and reasoning effort (SPECIFICATION SG-004)')
    if not who.get('id') or who['id'] in authors or review.get('fresh_context') is not True:
        raise ValueError('A distinct fresh reviewer is required')
    if review.get('status')!='pass' or review.get('unresolved_findings'):
        raise ValueError('Review has unresolved findings')

def author_models(content):
    authors=content.get('authors')
    if not isinstance(authors,list) or not authors or not all(isinstance(a,str) and a.strip() for a in authors) or len(authors)!=len(set(authors)):
        raise ValueError('Record nonempty unique substantive author IDs')
    rows=content.get('authoring_models',{})
    if set(rows)!=set(content['authors']):raise ValueError('Record every substantive author model/effort internally')
    for row in rows.values():
        if not model_recorded(row) or not row.get('configuration_check'):
            raise ValueError('Record each substantive author model/effort and an honest one-time configuration check')

def objective_source_dependencies(links):
    import intake
    reg=intake.curriculum();objects={x['id']:x for x in reg['entries']};lessons={x['id']:x for x in reg['lessons']}
    result={}
    for link in links:
        objective=objects[link['objective_id']];lesson=lessons[objective['lesson_id']];project_path(lesson['source_path'])
        if v.digest(v.ROOT/lesson['source_path'])!=lesson['source_sha256']:raise ValueError('Original objective PDF changed; reconcile register before reuse')
        result[lesson['source_path']]=lesson['source_sha256']
        for document in lesson.get('documents',[]):
            if document['path'] not in result:
                if v.digest(project_path(document['path']))!=document['sha256']:
                    raise ValueError('Supporting curriculum PDF changed; reconcile unit before reuse')
                result[document['path']]=document['sha256']
    return result

def entry_inputs(eid):
    e=v.read(v.BASE/'library/entries'/f'{safe_name(eid)}.json');author_models(e)
    objective_source_dependencies(e['objective_links'])
    sources={}
    for support in e['support']:
        source=v.get_source(support['source_id']);project_path(source['path'])
        if source['role']!='textbooks' or v.digest(v.ROOT/source['path'])!=source['sha256']:raise ValueError('Entry source unavailable or changed')
        sources[source['source_id']]=source['sha256']
    deps={'sources':sources,'specification_sha256':policy.educational_standard()}
    # Existing receipts keep their exact dependency contract. Scoped entries
    # receive scoped dependencies without changing any existing receipt.
    if e.get('dependencies') and 'objective_register_sha256' in e['dependencies']:
        deps['objective_register_sha256']=v.digest(v.BASE/'curriculum/objective_register.json')
    else:
        import intake
        deps.update(curriculum=entry_curriculum(e['objective_links']),source_records=intake.source_snapshot(sources))
    return {'status':'inputs_not_approval','entry_hash':semantic({k:x for k,x in e.items() if k not in {'status','review','dependencies'}}),'dependencies':deps}

def entry_dependency(eid,expected,test=False):
    if test:
        from contracts import test_guard
        test_guard(test)
    safe_name(eid);path=v.BASE/'library/entries'/f'{eid}.json';e=v.read(path)
    author_models(e)
    objective_source_dependencies(e['objective_links'])
    payload={k:x for k,x in e.items() if k not in {'status','review','dependencies'}}
    required={'id','version','title','explanation','objective_links','support','qualifications','disagreements','limitations','authors'}
    if not required<=set(e) or e['id']!=eid or not e['support'] or not e['objective_links']:raise ValueError('Incomplete knowledge-entry contract')
    if semantic(payload)!=expected or e.get('status')!='reviewed':raise ValueError('Entry not reviewed at expected version: '+eid)
    deps=e['dependencies']
    if not policy.standard_matches(deps.get('specification_sha256')):raise ValueError('Entry review predates current educational standards')
    import intake
    if 'objective_register_sha256' in deps:
        if deps['objective_register_sha256']!=v.digest(v.BASE/'curriculum/objective_register.json'):raise ValueError('Stale entry objective register')
        original=v.read(v.BASE/'curriculum/objective_register.json')
        current={o['id']:o for o in intake.curriculum()['entries']}
        for link in e['objective_links']:
            oid=link['objective_id']
            if next(o for o in original['entries'] if o['id']==oid)!=current.get(oid):raise ValueError('Changed registered objective interpretation')
    elif deps.get('curriculum')!=entry_curriculum(e['objective_links']) or deps.get('source_records')!=intake.source_snapshot(deps['sources']):
        raise ValueError('Stale entry curriculum/source records')
    register=intake.curriculum()
    objectives={o['id'] for o in register['entries'] if o['entry_kind']=='objective'}
    for link in e['objective_links']:
        if link.get('objective_id') not in objectives or link.get('role') not in {'direct','supporting_prerequisite','extension'} or not link.get('required_depth') or not link.get('rationale'):raise ValueError('Incomplete entry objective/depth linkage')
    if {s['source_id'] for s in e['support']}!=set(deps['sources']):raise ValueError('Entry source dependency omissions')
    for support in e['support']:
        source=v.get_source(support['source_id']);project_path(source['path'])
        if source['role']!='textbooks' or support['source_sha256']!=source['sha256'] or support['source_path'] not in source['aliases'] or not 1<=support['pdf_page']<=source['pdf_pages'] or not support.get('passages') or not support.get('context'):raise ValueError('Incomplete entry original support')
    for sid,sha in deps['sources'].items():
        source=v.get_source(sid)
        if source['sha256']!=sha or v.digest(v.ROOT/source['path'])!=sha:raise ValueError('Stale entry source')
    receipt=v.BASE/'reviews'/safe_name(e['review'])
    r=v.read(receipt);identity(r,e['authors'])
    if r.get('kind')!=('synthetic_test' if test else 'educational') or r.get('entry_hash')!=expected or r.get('dependencies')!=deps:raise ValueError('Missing/stale entry review')
    if r.get('factual_support')!='pass' or not r.get('evidence_assessment') or not r.get('independent_searches'):raise ValueError('Entry lacks independent factual review')
    return {'semantic_sha256':expected,'review_sha256':v.digest(receipt),'dependencies':deps}

def inputs(p):
    content=v.read(p/'content.json');evidence=v.read(p/'evidence.json')
    source_deps={}
    for row in evidence.values():
        s=v.get_source(row['source_id']);project_path(s['path'])
        if s['role']!='textbooks' or row['source_sha256']!=s['sha256']:raise ValueError('Evidence identity is not an approved textbook')
        if s['source_id'] not in source_deps and v.digest(v.ROOT/s['path'])!=s['sha256']:raise ValueError('Changed textbook bytes')
        source_deps[s['source_id']]=s['sha256']
    assets={}
    for b in guide_records(content):
        f=b.get('figure',{})
        if f.get('kind')=='authored_png':
            asset=p/'assets'/safe_name(f['file'])
            if asset.is_symlink() or v.digest(asset)!=f['sha256']:raise ValueError('Stale authored figure')
            assets[f['file']]=f['sha256']
    coordinate_reviews={}
    for eid,e in evidence.items():
        if e.get('reviewed_coordinates'):
            name=safe_name(e['reviewed_coordinates']['receipt'])
            coordinate_reviews[eid]=v.digest(p/'review'/name) if (p/'review'/name).exists() else None
    entry_deps={k:entry_dependency(k,h) for k,h in content.get('entry_dependencies',{}).items()}
    record_deps={r['id']:{'semantic':semantic(r),'evidence':{eid:semantic(evidence[eid]) for eid in r['evidence_ids']},
        'sources':{evidence[eid]['source_id']:source_deps[evidence[eid]['source_id']] for eid in r['evidence_ids']},
        'objectives':{o['id']:semantic(o) for o in content['objectives'] if o['id'] in r['objective_ids']},
        'entries':{eid:{'semantic_sha256':dep['semantic_sha256'],'sources':dep['dependencies']['sources'],**{k:val for k,val in dep['dependencies'].items() if k in {'objective_register_sha256','curriculum','source_records'}}} for eid,dep in entry_deps.items() if eid in r.get('entry_ids',[])},
        'coordinate_reviews':{eid:coordinate_reviews[eid] for eid in r['evidence_ids'] if eid in coordinate_reviews}}
        for r in records(content)}
    for rid,context in guide_contexts(content).items():
        if context:record_deps[rid]['guide_context']=context
    scope=v.read(p/'scope.json');scope_current(scope)
    result={'scope':semantic(scope),'content':semantic(content),
        'coverage':semantic(v.read(p/'coverage.json')),'evidence':semantic(evidence),
        'register':v.digest(v.BASE/'curriculum/objective_register.json') if (v.BASE/'curriculum/objective_register.json').is_file() else None,
        'specification':policy.educational_standard(),
        'source_registry':v.digest(v.BASE/'sources/sources.json') if (v.BASE/'sources/sources.json').is_file() else None,'sources':source_deps,'assets':assets,'coordinate_reviews':coordinate_reviews,
        'entries':entry_deps,'records':record_deps}
    if scope.get('dependency_version')==2:
        import intake
        context=scope_context(scope)
        result['register']=semantic(intake.teaching_context(context))
        result['source_registry']=intake.source_snapshot(source_deps)
        result['assessment_style']=semantic(context['assessment_style'])
        for row in record_deps.values():row['curriculum_context']=result['register']
        for row in content['saqs']+content['sbas']:
            record_deps[row['id']]['assessment_style']=result['assessment_style']
    return result

def engine(component=None):
    """Only relevant code/runtime invalidates each derived stage."""
    import sys
    groups={
        'evidence':['evidence.py','evidence_matching.py','export_privacy.py'],
        'html':['learner_export.py','guide_style.py','delivery_paths.py'],
        'anki':['anki_export.py','anki_preferences.py'],
        'validation':['qa.py','contracts.py','workflow.py','verification_policy.py','production.py','selection_checks.py','anki_export.py','anki_preferences.py','intake.py','delivery_paths.py'],
    }
    def stage(name):
        result={'code':{n:v.digest(v.ROOT/'scripts'/n) for n in groups[name]},'python':list(sys.version_info[:3])}
        if name in {'evidence','validation'}:result['pymupdf']=v.fitz.VersionBind
        if name=='evidence':
            import PIL
            result['pillow']=PIL.__version__
        return result
    if component is not None:return stage(component)
    return {name:stage(name) for name in groups}
