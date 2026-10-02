"""Cheap exported-content/citation checks; opt-in targeted desktop diagnostics."""
import base64,csv,html,io,re,shutil,subprocess,unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote,unquote,urlsplit
import pipeline_core as v
import workflow as w
import delivery_paths
from contracts import require
from learner_export import allowlist,book_labels
from export_privacy import check_files
import diagnostics as diag

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

class Node:
    def __init__(self,tag,attrs=()):self.tag=tag;self.attrs=dict(attrs);self.children=[]
    def all(self,tag):
        return [x for x in self.children if isinstance(x,Node) and x.tag==tag]+[y for x in self.children if isinstance(x,Node) for y in x.all(tag)]
    def text(self):
        hidden=('hidden' in self.attrs or self.attrs.get('aria-hidden')=='true' or re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)',self.attrs.get('style',''),re.I))
        if self.tag in {'head','script','style','template'} or hidden:return ''
        return ''.join(x.text() if isinstance(x,Node) else x for x in self.children)

class Links(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True)
        self.root=Node('document');self.stack=[self.root];self.links=[];self.ids=[];self.by_id={};self.images=0
        self.feed(text);self.close()
        require(len(self.stack)==1,'Unclosed HTML element')
    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs);self.stack[-1].children.append(node);a=node.attrs
        if 'id' in a:self.ids.append(a['id']);self.by_id[a['id']]=node
        if 'href' in a:self.links.append(a['href'])
        require(tag not in {'script','iframe','object','embed','base'},'Unexpected active HTML element')
        require(not any(k.startswith('on') for k in a),'Unexpected event attribute')
        if tag=='img':
            require(a.get('alt') and a.get('src','').startswith('data:image/png;base64,'),'Image must be embedded PNG with alt text');self.images+=1
        if tag not in VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in VOID:return
        require(len(self.stack)>1 and self.stack[-1].tag==tag,'Mismatched HTML element: '+tag)
        self.stack.pop()
    def handle_data(self,data):self.stack[-1].children.append(data)


def compact(text):return re.sub(r'\s+','',unicodedata.normalize('NFC',text).replace('\u00ad','').replace('\u200b',''))


def expected(c):
    out={'index.html':[c['lesson_label']]+[o['wording'] for o in c['objectives']],
         'practice.html':[q['prompt'] for q in c['saqs']+c['sbas']]+[t for q in c['sbas'] for t in q['options'].values()],
         'answers.html':[q['prompt'] for q in c['saqs']+c['sbas']]+[x['text'] for q in c['saqs'] for x in q['marking_points']]+[q['explanation'] for q in c['saqs']]+[t for q in c['sbas'] for t in list(q['options'].values())+list(q['rationales'].values())]+['Best answer: '+q['correct'] for q in c['sbas']],
         'anki.html':['Anki','StableID, Front, Back, Sources']}
    for ch in c['chapters']:
        out[ch['file']]=[ch['wording'],ch['title']]+[s['title'] for s in ch['sections']]+[b['text'] for s in ch['sections'] for b in s['blocks']]+[t for s in ch['sections'] for b in s['blocks'] if b['type']=='table' for row in [b['headers']]+b['rows'] for t in row]
        objective=next(o for o in c['objectives'] if o['id']==ch['objective_id'])
        labels=w.objective_labels(objective);out[ch['file']]+=labels;out['index.html']+=labels
    return out


@diag.observe('exported_content_checks')
def artifacts(p,images=None):
    stage=p/'learner';c=v.read(p/'content.json');allowed=allowlist(c);check_files(stage,allowed)
    source_prefix=delivery_paths.source_prefix(p)
    parsed={n:Links((stage/n).read_text(encoding='utf-8')) for n in allowed if n.endswith('.html')}
    links=0;pdf_sizes={}
    for name,doc in parsed.items():
        require(len(doc.ids)==len(set(doc.ids)),'Duplicate HTML ID: '+name)
        for href in doc.links:
            u=urlsplit(href);require(not u.scheme and not u.netloc and not u.query,'Only portable local links permitted')
            rel=unquote(u.path)
            require(not rel.startswith('/') and '\\' not in rel and not re.match(r'^[A-Za-z]:',rel),'Absolute/nonportable link')
            target=(stage/rel).resolve() if rel else stage/name
            if rel.startswith(source_prefix):
                source_rel=rel[len(source_prefix):];source=v.get_source(source_rel)
                require(source['role']=='textbooks' and source_rel==source['path'],'External link is not a registered textbook')
                target=w.project_path(source_rel)
            else:require(target.parent==stage.resolve(),'Learner link escapes delivery')
            require(target.is_file() and not target.is_symlink(),'Broken link '+href)
            if u.fragment:
                if target.suffix=='.pdf':
                    require(re.fullmatch(r'page=[1-9]\d*',u.fragment),'Bad PDF anchor')
                    if target not in pdf_sizes:
                        with v.fitz.open(target) as pdf:pdf_sizes[target]=len(pdf)
                    require(int(u.fragment[5:])<=pdf_sizes[target],'PDF page link out of range')
                else:require(unquote(u.fragment) in parsed[target.name].ids,'Broken HTML anchor')
            links+=1
    for name,passages in expected(c).items():
        visible=compact(parsed[name].root.text())
        require(all(compact(t) in visible for t in passages),'Missing exported teaching/answer in '+name)
    ledger=v.read(p/'citation-occurrences.json');refs={};labels=book_labels()
    import evidence
    plan=evidence.occurrence_plan(c,v.read(p/'evidence.json'))
    require(len(plan)==len(ledger) and all(all(row[k]==wanted[k] for k in wanted) for row,wanted in zip(ledger,plan)),'Citation ledger differs from authored evidence')
    for row in ledger:refs.setdefault(row['record_id'],[]).append(row)
    def cite_check(doc,rid):
        block=doc.by_id[rid]
        actual=[x.attrs['id'] for x in block.all('span') if x.attrs.get('class')=='cite']
        require(actual==['cite-'+str(r['occurrence']) for r in refs[rid]],'Citation occurrence attached to wrong record: '+rid)
        for row in refs[rid]:
            node=doc.by_id['cite-'+str(row['occurrence'])]
            expected_links=[quote(source_prefix+row['source_path'],safe='/')+'#page='+str(row['pdf_page']),
                'evidence-unmarked.pdf#page='+str(row['evidence_page']),'evidence-highlighted.pdf#page='+str(row['evidence_page'])]
            require([a.attrs.get('href') for a in node.all('a')]==expected_links,'Wrong source/page citation: '+rid)
            require(compact(labels[row['source_id']]+' · PDF p. '+str(row['pdf_page'])) in compact(node.text()),'Wrong readable source label')
    if images is None:images=evidence.figures(p,c,v.read(p/'evidence.json'))
    for ch in c['chapters']:
        doc=parsed[ch['file']]
        for sec in ch['sections']:
            require(sec['id'] in doc.by_id,'Missing section anchor')
            for b in sec['blocks']:
                require(b['id'] in doc.by_id,'Missing teaching block');node=doc.by_id[b['id']]
                require(compact(b['text']) in compact(node.text()),'Teaching appears under the wrong block')
                if b['type']=='table':
                    tables=node.all('table');require(len(tables)==1,'Missing teaching table')
                    require([x.text() for x in tables[0].all('th')]==b['headers'],'Table headers changed')
                    rows=[[x.text() for x in row.all('td')] for row in tables[0].all('tr') if row.all('td')]
                    require(rows==b['rows'],'Table values or column associations changed')
                if b['type']=='figure':
                    imgs=node.all('img');require(len(imgs)==1 and imgs[0].attrs.get('alt')==b['alt'],'Figure label changed')
                    require(base64.b64decode(imgs[0].attrs['src'].split(',',1)[1],validate=True)==images[b['id']],'Figure differs from approved source crop/asset')
                cite_check(doc,b['id'])
    for answers in (False,True):
        doc=parsed['answers.html' if answers else 'practice.html']
        for q in c['saqs']+c['sbas']:
            require(q['id'] in doc.by_id,'Missing question');node=doc.by_id[q['id']];text=compact(node.text())
            require(compact(q['prompt']) in text,'Question mapped to wrong record')
            marks=[compact(x.text()) for x in node.all('p') if x.attrs.get('class')=='marks']
            require(marks==[compact(str(q['marks'])+(' mark' if q['marks']==1 else ' marks'))],'Incorrect question marks')
            if 'options' in q:
                options=[x for x in node.all('ol') if x.attrs.get('class')=='options']
                require(len(options)==1 and [x.text() for x in options[0].all('li')]==[k+'. '+t for k,t in q['options'].items()],'Options or option labels changed')
                if answers:
                    require(compact('Best answer: '+q['correct']) in text,'Wrong correct-answer label')
                    for k,t in q['rationales'].items():require(compact(k+'. '+t) in text,'Wrong distractor rationale association')
            elif answers:
                points=[x.text() for x in node.all('li')]
                require(points==[pt['text']+' ('+str(pt['marks'])+(' mark' if pt['marks']==1 else ' marks')+')' for pt in q['marking_points']],'Marking points or marks changed')
                require(compact(q['explanation']) in text,'Missing answer explanation')
            if answers:cite_check(doc,q['id'])
    validate_anki(stage,c,v.read(p/'scope.json'),refs,labels)
    return {'status':'pass','links':links,'images':sum(d.images for d in parsed.values()),'anki_cards':len(c['cards']),'chapters':len(c['chapters']),'content_and_citations':'pass','model_image_inspections':0}


def validate_anki(stage,c,scope,refs,labels):
    """Independent TSV/note checks; also used by complete artifact validation."""
    lines=(stage/'anki.tsv').read_text(encoding='utf-8').splitlines(keepends=True)
    require('#tags column:5' in [line.strip() for line in lines],'Missing Anki tag-column mapping')
    rows=list(csv.reader(io.StringIO(''.join(x for x in lines if not x.startswith('#'))),delimiter='\t'))
    require(len(rows)==len(c['cards']) and all(len(row)==5 for row in rows),'Anki row/column count')
    require([r[0] for r in rows]==[card['id'] for card in c['cards']],'Stable Anki IDs/order changed')
    require(len({r[0] for r in rows})==len(rows),'Duplicate Anki ID')
    from anki_export import canonical_tags
    tags=canonical_tags(c,scope)
    for row,card in zip(rows,c['cards']):
        def norm(t):return t.replace('\r\n','\n').replace('\r','\n')
        require(html.unescape(row[1].replace('<br>','\n'))==norm(card['front']) and html.unescape(row[2].replace('<br>','\n'))==norm(card['back']) and row[4].split()==tags[card['id']],'Anki field corruption')
        sources='\n'.join(labels[r['source_id']]+f' · PDF p. {r["pdf_page"]}; included source page {r["evidence_page"]}' for r in refs[card['id']])
        require(html.unescape(row[3].replace('<br>','\n'))==sources,'Anki source mapping changed')
    from anki_export import NOTE_TYPE
    require(v.read(stage/'anki-note-type.json')==NOTE_TYPE,'Anki note type field/template mismatch')
    return {'status':'pass','anki_cards':len(rows)}


@diag.observe('artifact_validation')
def validate(p,images=None):
    c=v.read(p/'content.json');files=check_files(p/'learner',allowlist(c))
    delivery_folder=delivery_paths.configured_folder(p)
    dependencies={'content':w.semantic(c),'scope':v.digest(p/'scope.json'),'register':v.digest(v.BASE/'curriculum/objective_register.json') if (v.BASE/'curriculum/objective_register.json').exists() else None,'evidence':v.digest(p/'evidence.json'),'ledger':v.digest(p/'citation-occurrences.json'),'artifacts':files,'engine':w.engine('validation'),'anki_engine':w.engine('anki'),'figures_engine':w.engine('evidence'),'sources':v.digest(v.BASE/'sources/sources.json') if (v.BASE/'sources/sources.json').exists() else None}
    dependencies['delivery_folder']=delivery_folder
    scope=v.read(p/'scope.json')
    if scope.get('dependency_version')==2:
        import intake,anki_preferences
        dependencies['register']=w.semantic(w.scope_context(scope))
        dependencies['sources']=intake.source_snapshot({e['source_id'] for e in v.read(p/'evidence.json').values()})
        dependencies['anki_preferences']=anki_preferences.read_for(scope)
    key=w.semantic(dependencies)
    path=w.safe_tree(p/'validation/artifacts.json')
    prior=v.read(path) if path.exists() else None
    diag.annotate(input_key=key)
    diag.emit('cache_decision',component='artifact_validation',input_key=key,previous_key=prior.get('key') if prior else None,
              reused=bool(prior and prior.get('key')==key and prior.get('checks',{}).get('status')=='pass'),
              dependency_keys={k:w.semantic(x) if isinstance(x,dict) else x for k,x in dependencies.items()})
    if prior and prior.get('key')==key and prior.get('checks',{}).get('status')=='pass':return dict(prior['checks'],reused=True)
    result=artifacts(p,images);v.write(path,{'key':key,'checks':result})
    return dict(result,reused=False)


@diag.observe('desktop_or_html_qa')
def layout(p,render=False,files=None):
    """Normal QA is raw HTML; explicit desktop diagnostics render <=3 files."""
    result=validate(p)
    if not render:return {'status':result['status'],'checks':result,'renders':0,'mode':'html','live_browser_tested':False}
    c=v.read(p/'content.json');names=files or [c['chapters'][0]['file'],'answers.html']
    require(1<=len(names)<=3 and len(names)==len(set(names)) and set(names)<=set(expected(c)),'Choose one to three learner HTML files')
    from bootstrap import dependencies
    wk=dependencies('skip')['wkhtmltopdf'];require(wk,'Optional desktop diagnostics need wkhtmltopdf')
    out=w.safe_tree(p/'validation/desktop');out.mkdir(parents=True,exist_ok=True);rows=[]
    for name in names:
        dest=w.safe_tree(out/(Path(name).stem+'.pdf'))
        cmd=[wk,'--quiet','--disable-javascript','--disable-local-file-access','--disable-smart-shrinking','--encoding','utf-8','--no-print-media-type','--viewport-size','1280x900','--page-width','338.667mm','--page-height','1000mm','--margin-top','0','--margin-bottom','0','--margin-left','0','--margin-right','0','-',str(dest)]
        run=subprocess.run(cmd,input=(p/'learner'/name).read_bytes(),capture_output=True,timeout=60)
        require(run.returncode==0,'Optional desktop renderer failed')
        with v.fitz.open(dest) as doc:
            text=compact(' '.join(page.get_text() for page in doc))
            missing=[t for t in expected(c)[name] if compact(t) not in text]
            png=w.safe_tree(out/(Path(name).stem+'.png'));doc[0].get_pixmap(dpi=96).save(png)
            rows.append({'artifact':name,'input_sha256':v.digest(p/'learner'/name),'pages':len(doc),'missing_text':missing,'preview':png.relative_to(v.ROOT).as_posix(),'pdf':dest.relative_to(v.ROOT).as_posix()})
    report={'status':'needs_attention' if any(r['missing_text'] for r in rows) else 'pass','mode':'desktop','method':'Optional offline desktop diagnostic; not a live browser test','live_browser_tested':False,'html_engine':w.engine('html'),'renders':rows}
    v.write(p/'validation/desktop.json',report)
    return {'status':report['status'],'renders':len(rows),'mode':'desktop','live_browser_tested':False}


@diag.observe('desktop_gate')
def layout_gate(p,test=False):
    """No routine visual receipt. A current detected content defect still blocks."""
    from contracts import test_guard
    test_guard(test)
    report=p/'validation/desktop.json'
    if not report.exists():return {'status':'not_requested'}
    r=v.read(report)
    if r.get('html_engine')!=w.engine('html'):return {'status':'stale_diagnostic'}
    for row in r.get('renders',[]):
        path=p/'learner'/w.safe_name(row['artifact'])
        if path.exists() and row.get('input_sha256')==v.digest(path):
            require(not row.get('missing_text'),'Desktop diagnostic found missing teaching; repair the affected file')
    return {'status':'pass'}
