"""Local source discovery and reusable deterministic primitives. Originals are read-only."""
import argparse, collections, csv, gzip, hashlib, io, json, os, re, shutil, sqlite3, subprocess, tempfile, unicodedata
from pathlib import Path
import fitz
import cache_paths
import diagnostics as diag
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'foundation'
VERSION='study-source-1'
_DIGEST_CACHE={}
DIGEST_STATS={'full_reads':0,'cache_hits':0,'bytes_read':0}
def _file_stamp(path):
    s=path.stat()
    return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns

def digest(path, *, fresh=False):
    """Read each unchanged file once per process; never trust timestamps across runs."""
    path=Path(path).resolve(); before=_file_stamp(path)
    if not fresh and _DIGEST_CACHE.get(path, (None,))[0]==before:
        DIGEST_STATS['cache_hits']+=1
        return _DIGEST_CACHE[path][1]
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    if _file_stamp(path)!=before:
        raise RuntimeError(f'File changed during hashing: {path}')
    value=h.hexdigest(); _DIGEST_CACHE[path]=(before,value)
    DIGEST_STATS['full_reads']+=1; DIGEST_STATS['bytes_read']+=before[2]
    return value

def read(path):
    text=Path(path).read_text(encoding='utf-8');value=json.loads(text)
    diag.file_event('json_read',path,text.encode('utf-8'))
    diag.receipt_observed(path,value)
    return value

def write_bytes(path, data):
    """Atomic replacement only when bytes change; returns whether a write occurred."""
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()==data:
        diag.file_event('file_write',path,data,changed=False)
        return False
    with tempfile.NamedTemporaryFile('wb',dir=path.parent,delete=False) as f:
        f.write(data); f.flush(); os.fsync(f.fileno()); name=f.name
    os.replace(name,path)
    diag.file_event('file_write',path,data,changed=True)
    return True

def write(path, value):
    """Atomic JSON write, replacing only changed bytes."""
    return write_bytes(path,(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode('utf-8'))

def normalize(text):
    # Retrieval only. No inferred character substitutions or numerical repairs.
    return unicodedata.normalize('NFC',text).replace('\u00ad','').replace('\u200b','').replace('\ufeff','')

def raw_records(record):
    import intake
    with gzip.open(cache_paths.raw_path(ROOT, record, intake.source_directory(record)),'rt',encoding='utf-8') as f:
        for line in f: yield json.loads(line)

def sources():
    import intake
    return intake.sources()

def get_source(key):
    found=[s for s in sources() if s['source_id']==key or s['sha256']==key or key in s['aliases']]
    if len(found)!=1:raise ValueError('Supply exact source ID, SHA256 or current relative path')
    return found[0]

def edge_key(block): return re.sub(r'\b\d+\b','#',normalize(block['text']).strip()).lower()

def edge_counts(pages):
    counts=collections.Counter()
    for p in pages:
        keys={edge_key(b) for b in p['blocks'] if (b['bbox'][3]<p['height']*.07 or b['bbox'][1]>p['height']*.94) and len(b['text'].strip())<160}
        counts.update(keys)
    return counts

NAV = re.compile(r'^(?:table of contents|contents|detailed contents|index|subject index|author index|preface(?:\s|$)|foreword|acknowledg[em]+nts|contributors|about the authors|notes on contributors|copyright|dedication|permissions|bibliography)(?:\b|$)',re.I)

def classify(p, outline, role):
    if role!='textbooks': return 'objectives' if role=='objectives' else 'assessment_style'
    t=normalize(p['text']); lines=[x.strip() for x in t.splitlines() if x.strip()]; head=' '.join(lines[:4])
    if not t.strip():return 'no_native_text'
    if re.search(r'activate your ebook|redeem access code|by buying this genuine product',t,re.I):return 'publisher_material'
    if (('all rights reserved' in t.lower() and ('copyright' in t.lower() or '©' in t)) and p['pdf_page']<150):return 'publisher_material'
    if NAV.match(re.sub(r'^[ivx\d]+\s+','',head,flags=re.I)):return 'navigation_or_frontmatter'
    prior=[o for o in outline if o[2]>0 and o[2]<=p['pdf_page']]
    # Only clearly marked outline sections; never infer from a common word in body text.
    if prior:
        active=max(prior,key=lambda o:o[2])
        if NAV.match(active[1].strip()):return 'navigation_or_frontmatter'
    if len(re.findall(r'\.{3,}\s*\d+|\t\s*\d+\s*$',t,re.M))>=8:return 'navigation_or_frontmatter'
    # Page position alone cannot distinguish a short teaching PDF from front matter.
    return 'teaching_candidate'

def ordered_blocks(blocks,width):
    """Conservative two-column bands; ambiguous spans retained and flagged."""
    if len(blocks)<3:return blocks,'original_block_order'
    left=[b for b in blocks if b['bbox'][2]<=width*.54 and b['bbox'][0]<width*.4]
    right=[b for b in blocks if b['bbox'][0]>=width*.46 and b['bbox'][2]>width*.6]
    if not left or not right:return blocks,'original_block_order'
    split=width*.5
    spans=[b for b in blocks if b not in left and b not in right]
    result=[];remaining=list(blocks)
    for span in sorted(spans,key=lambda b:b['bbox'][1]):
        above=[b for b in remaining if b is not span and b['bbox'][3]<=span['bbox'][1]+1]
        result.extend(sorted(above,key=lambda b:(b['bbox'][0]>=split,b['bbox'][1])))
        for b in above:remaining.remove(b)
        if span in remaining:result.append(span);remaining.remove(span)
    result.extend(sorted(remaining,key=lambda b:(b['bbox'][0]>=split,b['bbox'][1])))
    return result,'two_column_band_heuristic_verify_original'

def clean_page(p,counts):
    kept=[];removed=[];flags=list(p['flags']);w=p['width'];h=p['height']
    for b in p['blocks']:
        box=b['bbox'];text=b['text'].strip();edge=box[3]<h*.07 or box[1]>h*.94
        repeated=counts[edge_key(b)]>=5
        # Do not remove headings/captions/numeric ranges merely for looking repetitive.
        safe_edge=edge and (re.fullmatch(r'\d+|[ivxlcdm]+|Page \d+ of \d+',text,re.I) or (repeated and len(text)<100 and not re.search(r'[=<>±%µμ]|\d\s*[-–]\s*\d|figure|table|box',text,re.I)))
        if safe_edge:removed.append({'text':b['text'],'bbox':box,'reason':'repeated_edge_running_text_or_page_number'});continue
        if box[0]<-1 or box[1]<-1 or box[2]>w+1 or box[3]>h+1:flags.append('raw_box_outside_page_no_highlight_permission')
        kept.append(b)
    ordered,method=ordered_blocks(kept,w)
    text='\n\n'.join(normalize(b['text']).strip() for b in ordered if b['text'].strip())
    if any(unicodedata.category(c)=='Co' for c in text):flags.append('private_glyphs_verify_original')
    if re.search(r'\bTABLE\b|\bTable \d',text):flags.append('table_layout_verify_original')
    return text,removed,method,sorted(set(flags))


@diag.observe('search')
def search(query,role='textbooks',limit=8,recovery=False,source=None):
    diag.annotate(request_key=diag.fingerprint([query,role,limit,recovery,source]),query_characters=len(query),limit=limit,recovery=recovery)
    if not 1<=limit<=30:raise ValueError('Retrieval limit must be between 1 and 30')
    import intake
    active=[s for s in sources() if s['role']==role and s.get('format')=='pdf']
    if source:active=[get_source(source)]
    params=[query,role];where='search MATCH ? AND s.role=?'
    if not recovery and role=='textbooks':where+=" AND p.classification='teaching_candidate'"
    if source:where+=' AND s.id=?';params.append(get_source(source)['source_id'])
    params.append(min(limit,30))
    groups={}
    for item in active:groups.setdefault(intake.source_directory(item),set()).add(item['source_id'])
    rows=[]
    for directory,ids in groups.items():
        db=sqlite3.connect((directory/'search.sqlite').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:
            selected=where+' AND s.id IN ('+','.join('?' for _ in ids)+')'
            args=params[:-1]+sorted(ids)+[params[-1]]
            rows.extend(dict(r) for r in db.execute('SELECT s.id source_id,s.path,s.sha256,p.pdf_page,p.classification,p.flags,p.method,bm25(search) rank,snippet(search,0,"[", "]"," … ",48) snippet FROM search JOIN pages p ON p.id=search.rowid JOIN sources s ON s.id=p.source_id WHERE '+selected+' ORDER BY bm25(search) LIMIT ?',args))
        finally:db.close()
    rows=sorted(rows,key=lambda r:(r['rank'],r['source_id'],r['pdf_page']))[:limit]
    current={s['source_id']:s for s in active}
    for row in rows:
        row.pop('rank',None);row['path']=current[row['source_id']]['path']
    output=json.dumps(rows,ensure_ascii=False,indent=2)
    diag.annotate(results=len(rows),returned_characters=len(output),returned_utf8_bytes=len(output.encode('utf-8')),
                  returned_pages=[{'source_id':r['source_id'],'pdf_page':r['pdf_page']} for r in rows],limit_reached=len(rows)==limit)
    print(output)

@diag.observe('source_page')
def page(key,n,context=0):
    s=get_source(key);path=ROOT/s['path']
    diag.annotate(request_key=diag.fingerprint([s['sha256'],n,context]),source_id=s['source_id'],pdf_page=n,context=context)
    if digest(path)!=s['sha256']:raise ValueError('Source changed; rebuild and re-review dependencies')
    if not 0<=context<=1:raise ValueError('At most one surrounding page per side')
    with fitz.open(path) as pdf:
        if not 1<=n<=len(pdf):raise ValueError('PDF page out of bounds')
        for i in range(max(1,n-context),min(len(pdf),n+context)+1):
            output=json.dumps({'source_id':s['source_id'],'path':s['path'],'source_sha256':s['sha256'],'pdf_page':i,'authoritative':'original PDF; native text is discovery','text':pdf[i-1].get_text(sort=False)},ensure_ascii=False,indent=2)
            diag.emit('retrieved_page',source_id=s['source_id'],source_sha256=s['sha256'],pdf_page=i,returned_characters=len(output),returned_utf8_bytes=len(output.encode('utf-8')),response_sha256=hashlib.sha256(output.encode('utf-8')).hexdigest())
            print(output)

@diag.observe('ocr')
def ocr(key,n,dpi=220,psm=3):
    s=get_source(key);path=ROOT/s['path']
    if digest(path)!=s['sha256']:raise ValueError('Source changed')
    from bootstrap import dependencies
    runtime=dependencies('auto')
    version=runtime['tesseract_version'];lang=Path(runtime['language'])
    settings={'source_sha256':s['sha256'],'pdf_page':n,'engine':version,'language_sha256':digest(lang),'dpi':dpi,'psm':psm,'rotation':'rendered_display_then_derotation_to_original'}
    keyhash=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()
    import intake
    out=intake.source_directory(s)/'ocr'/s['sha256']/f'{n}-{keyhash[:16]}.json'
    diag.annotate(input_key=keyhash,reused=out.exists())
    if out.exists():print(out.relative_to(ROOT).as_posix());return
    with tempfile.TemporaryDirectory() as temp, fitz.open(path) as pdf:
        if not 1<=n<=len(pdf):raise ValueError('PDF page out of bounds')
        p=pdf[n-1];image=Path(temp)/'page.png';pix=p.get_pixmap(dpi=dpi);pix.save(image)
        command=[runtime['tesseract'],str(image),'stdout','--tessdata-dir',str(lang.parent),'-l',read(ROOT/'bootstrap-settings.json')['ocr']['language'],'--psm',str(psm)]
        text=subprocess.check_output(command,text=True,encoding='utf-8',stderr=subprocess.DEVNULL,timeout=120)
        tsv=subprocess.check_output(command+['tsv'],text=True,encoding='utf-8',stderr=subprocess.DEVNULL,timeout=120)
        words=[]
        for row in csv.DictReader(io.StringIO(tsv),delimiter='\t'):
            if row['level']=='5' and row['text'].strip():
                x,y,w,h=[float(row[k]) for k in ['left','top','width','height']]
                rect=fitz.Rect(x*p.rect.width/pix.width,y*p.rect.height/pix.height,(x+w)*p.rect.width/pix.width,(y+h)*p.rect.height/pix.height)*p.derotation_matrix
                words.append({'text':row['text'],'confidence':float(row['conf']),'bbox_original_unrotated':list(rect),'pixel_bbox':[x,y,w,h]})
        write(out,{**settings,'source_id':s['source_id'],'image_dimensions':[pix.width,pix.height],'text':text,'words':words,'capabilities':{'nonempty_text':bool(text.strip()),'word_boxes':bool(words)},'geometry_reviewed':False,'factual_review':'unreviewed','cache_key':keyhash})
    print(out.relative_to(ROOT).as_posix())

@diag.observe('source_render')
def render(key,n,dest):
    import workflow as w
    destination=Path(dest)
    destination=destination if destination.is_absolute() else ROOT/destination
    w.safe_tree(destination)
    if not any(destination.is_relative_to(ROOT/x) for x in ['packs','work']):raise ValueError('Render originals only into packs/ or work/')
    s=get_source(key)
    diag.annotate(source_id=s['source_id'],pdf_page=n,request_key=diag.fingerprint([s['sha256'],n,130]))
    if digest(ROOT/s['path'])!=s['sha256']:raise ValueError('Source changed; rebuild and re-review dependencies')
    with fitz.open(ROOT/s['path']) as pdf:
        if not 1<=n<=len(pdf):raise ValueError('PDF page out of bounds')
        p=destination;p.parent.mkdir(parents=True,exist_ok=True);pdf[n-1].get_pixmap(dpi=130).save(p)
    print(dest)
