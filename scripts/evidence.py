"""Original-page occurrence export. No previous pack or model OCR is consulted."""
import base64, io, tempfile
from contextlib import ExitStack
from pathlib import Path
import pipeline_core as v
import workflow as w
from contracts import require
from evidence_matching import matchnorm,exact_native_block,preserve_page_group
from export_privacy import sanitize_pdf,clean_png
import diagnostics as diag

def occurrence_plan(content,evidence):
    rows=[]
    for rec in w.records(content):
        for eid in rec['evidence_ids']:
            e=evidence[eid];s=v.get_source(e['source_id']);n=len(rows)+1
            rows.append({'occurrence':n,'evidence_page':n,'record_id':rec['id'],'evidence_id':eid,
                'source_id':s['source_id'],'source_sha256':s['sha256'],'source_path':s['path'],
                'pdf_page':e['pdf_page'],'passages':e.get('passages',[]),
                'reviewed_coordinates':e.get('reviewed_coordinates')})
    return rows

def coordinate_quads(p,eid,e,c,authors,test=False):
    from contracts import test_guard
    test_guard(test)
    receipt=v.read(p/'review'/w.safe_name(c['receipt']))
    w.identity(receipt,authors)
    require(receipt.get('kind')==('synthetic_test' if test else 'coordinates'),'Wrong coordinate receipt type')
    require(receipt.get('evidence_id')==eid and receipt.get('evidence_hash')==w.semantic(e),'Stale coordinate review')
    require(receipt.get('original_page_inspected') and receipt.get('geometry_assessment'),'Coordinate review must inspect original')
    return [v.fitz.Quad(q) for q in c['quads']]

@diag.observe('evidence_construction')
def compile_evidence(p,stage,c,ev,ledger,test=False):
    stats={'occurrences':len(ledger),'unique_original_pages':len({(r['source_id'],r['pdf_page']) for r in ledger}),
        'original_render_matches':0,'underlying_content_matches':0,'highlights':0,'model_calls':0,
        'geometry_computations':0,'geometry_reused':0,'highlight_warnings':[]}
    with tempfile.TemporaryDirectory() as temp,ExitStack() as stack:
        docs={};out=stack.enter_context(v.fitz.open());original_renders={};copied_pages={}
        for r in ledger:
            sid=r['source_id']
            if sid not in docs:
                require(v.digest(v.ROOT/r['source_path'])==r['source_sha256'],'Changed original source')
                docs[sid]=stack.enter_context(v.fitz.open(v.ROOT/r['source_path']))
            src=docs[sid];n=r['pdf_page']-1;copydoc=src;copyn=n
            if src[n].first_widget is not None:
                copydoc=stack.enter_context(v.fitz.open(v.ROOT/r['source_path']));copydoc.select([n]);copydoc.bake(annots=False,widgets=True);copyn=0
            # Graft each original page once, retaining shared embedded resources.
            # Re-inserting that page with a retained graft map aliases its page
            # object / annotations, so use a full independent copy for repeats.
            key=(sid,n)
            if key in copied_pages:
                out.fullcopy_page(copied_pages[key])
            else:
                out.insert_pdf(copydoc,from_page=copyn,to_page=copyn,annots=True,links=False,widgets=False,final=False)
                copied_pages[key]=len(out)-1
            preserve_page_group(copydoc,copyn,out,len(out)-1)
            if key not in original_renders:
                pix=src[n].get_pixmap(matrix=v.fitz.Matrix(1,1));original_renders[key]=(pix.width,pix.height,pix.digest)
        raw=Path(temp)/'unmarked.pdf';out.save(raw,garbage=4,deflate=True)
        sanitize_pdf(raw,stage/'evidence-unmarked.pdf','Supporting textbook pages')
        geometry={}
        for i,r in enumerate(ledger):
            src=docs[r['source_id']][r['pdf_page']-1];quads=[];methods=[]
            key=w.semantic({'source':r['source_sha256'],'page':r['pdf_page'],'passages':r['passages'],'coordinates':r['reviewed_coordinates'],'evidence_id':r['evidence_id'] if r['reviewed_coordinates'] else None})
            if key in geometry:
                quads,methods,warning=geometry[key];stats['geometry_reused']+=1
            else:
                warning=None;stats['geometry_computations']+=1
                for passage in r['passages']:
                    count=matchnorm(src.get_text()).count(matchnorm(passage))
                    # An absent quoted passage is a source/citation problem. A
                    # repeated match is only ambiguous highlight placement.
                    require(count>0,'Cited passage absent from source page: '+r['evidence_id'])
                    # A geometry limitation must not hide absent later passages.
                    if warning:continue
                    if count!=1:
                        warning='Ambiguous native-text match; original page retained without project highlights';continue
                    (accepted,unmatched),method=exact_native_block(src,passage)
                    if not accepted or unmatched:
                        warning='Incomplete native-text geometry; original page retained without project highlights';continue
                    quads.extend(q for _,qq in accepted for q in qq);methods.append(method)
                if r['reviewed_coordinates'] and not warning:
                    try:
                        quads.extend(coordinate_quads(p,r['evidence_id'],ev[r['evidence_id']],r['reviewed_coordinates'],c['authors'],test))
                        methods.append('independently_reviewed_original_coordinates')
                    except (ValueError,FileNotFoundError,KeyError):
                        warning='Unavailable or stale optional coordinate review; original page retained without project highlights'
                if not warning and (not quads or not all(src.rect.contains(q.rect) for q in quads)):
                    warning='Unavailable in-page geometry; original page retained without project highlights'
                if warning:quads=[];methods=[]
                geometry[key]=(quads,methods,warning)
            if quads:
                destination_page=out[i]
                annot=destination_page.add_highlight_annot(quads);annot.set_colors(stroke=(1,.84,.15));annot.set_opacity(.25);annot.update()
                stats['highlights']+=1
            if warning:stats['highlight_warnings'].append({'occurrence':r['occurrence'],'evidence_id':r['evidence_id'],'reason':warning})
            r['highlight_methods']=methods;r['highlight_quads']=[[list(pt) for pt in q] for q in quads]
            r['highlight_status']='unmarked_limitation' if warning else 'exact'
        marked=Path(temp)/'highlighted.pdf';out.save(marked,garbage=4,deflate=True)
        sanitize_pdf(marked,stage/'evidence-highlighted.pdf','Highlighted supporting textbook pages')
        with v.fitz.open(stage/'evidence-unmarked.pdf') as a,v.fitz.open(stage/'evidence-highlighted.pdf') as b:
            require(len(a)==len(b)==len(ledger),'Occurrence count mismatch')
            for i,r in enumerate(ledger):
                pix=a[i].get_pixmap(matrix=v.fitz.Matrix(1,1))
                require((pix.width,pix.height,pix.digest)==original_renders[(r['source_id'],r['pdf_page']-1)],'Original-page appearance changed during export')
                require(a[i].read_contents()==b[i].read_contents() and a[i].get_text()==b[i].get_text() and a[i].rect==b[i].rect,'Highlighted evidence altered underlying source content')
                if r['highlight_status']=='exact':require(b[i].first_annot is not None,'Missing constructed highlight')
                stats['original_render_matches']+=1;stats['underlying_content_matches']+=1
        for sid,doc in docs.items():require(v.digest(v.ROOT/v.get_source(sid)['path'])==v.get_source(sid)['sha256'],'Original source changed')
    return stats

def figures(p,content,evidence):
    result={}
    for b in w.guide_records(content):
        if b['type']!='figure':continue
        f=b['figure']
        if f['kind']=='source_crop':
            require(f['evidence_id'] in b['evidence_ids'],'Figure evidence must be cited locally')
            e=evidence[f['evidence_id']];s=v.get_source(e['source_id'])
            with v.fitz.open(v.ROOT/s['path']) as doc:
                page=doc[e['pdf_page']-1];rect=v.fitz.Rect(f['rect'])
                require(page.rect.contains(rect) and not rect.is_empty,'Invalid original figure crop')
                data=page.get_pixmap(clip=rect,dpi=f.get('dpi',150),alpha=False).tobytes('png')
        elif f['kind']=='authored_png':
            path=p/'assets'/w.safe_name(f['file']);require(not path.is_symlink() and v.digest(path)==f['sha256'],'Changed authored figure')
            data=path.read_bytes()
        else:raise ValueError('Use a source crop or source-reviewed local PNG')
        result[b['id']]=clean_png(data)
    return result
