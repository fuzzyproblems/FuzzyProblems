"""Typed learner-only projection; one dedicated page per original objective."""
import base64,html
import anki_export
import delivery_paths
from urllib.parse import quote
import pipeline_core as v
from workflow import objective_labels
from guide_style import CSS,EXTRA_CSS
from export_privacy import neutral_filesystem

E=html.escape
STYLE=CSS+EXTRA_CSS+'''
main{display:block;max-width:1040px}.citations{font-size:13px;line-height:1.6;margin-top:12px}
.cite{display:block;margin:4px 0}.cite a{overflow-wrap:anywhere}nav{display:flex;flex-wrap:wrap;gap:10px 20px}
.scope{margin:24px 0}figure{margin:26px 0}figcaption{line-height:1.55}.contents{line-height:1.9}
img{max-width:100%;height:auto}table{width:100%;table-layout:auto}td,th{word-break:normal;overflow-wrap:normal;hyphens:none}
@media(max-width:600px){main{padding:20px 16px}h1{font-size:30px}.citations{font-size:12px}thead{display:none}tr{display:block;margin:14px 0;border:1px solid #ddd}td{display:block}td:before{content:attr(data-label);display:block;font-weight:bold}}
@media print{nav,.contents,.no-print{display:none}main{padding:0}.citations{font-size:8pt}.cite{margin:2pt 0}a{color:inherit}article,.block{break-inside:auto}figure,tr{break-inside:avoid}}
@media print{.answer,.question{break-inside:avoid;page-break-inside:avoid}.answer h3,.question h3{break-after:avoid;page-break-after:avoid}}
@media print{.constructed-response,.section-opening.extended-opening{break-inside:auto;page-break-inside:auto}}
@media print{
 .block,.section-opening{break-inside:avoid;page-break-inside:avoid}
 table{display:table;width:100%;table-layout:auto}caption{display:table-caption}
 thead{display:table-header-group}tbody{display:table-row-group}
 tr{display:table-row;margin:0;border:0}th,td{display:table-cell;width:auto;padding:9px;border:1px solid #cbd7d0}
 td:before{display:none;content:none}
}
'''
NAV='<nav aria-label="Study materials"><a href="index.html">Study guide</a><a href="practice.html">Practice</a><a href="answers.html">Answers</a><a href="anki.html">Anki</a></nav>'

def allowlist(content):
    return ['index.html']+[ch['file'] for ch in content['chapters']]+['practice.html','answers.html','anki.html','anki.tsv','anki-note-type.json','evidence-unmarked.pdf','evidence-highlighted.pdf']

def book_labels():
    labels={}
    for s in v.sources():
        b=s.get('book_identity',{})
        if b.get('title'):labels[s['source_id']]=b['title']+(' · edition '+str(b['edition']) if b.get('edition') else '')
    return labels

def render(folder,c,ledger,images,scope,pack=None):
    labels=book_labels();refs={};blocks={};chapter_for={x['objective_id']:x for x in c['chapters']}
    source_prefix=delivery_paths.source_prefix(pack or folder.parent)
    for row in ledger:
        if row['source_id'] not in labels:raise ValueError('Verify a readable book identity before export')
        refs.setdefault(row['record_id'],[]).append(row)
    def citations(rid):
        return '<div class="citations">'+''.join('<span class="cite" id="cite-'+str(r['occurrence'])+'"><a href="'+quote(source_prefix+r['source_path'],safe='/')+'#page='+str(r['pdf_page'])+'">'+E(labels[r['source_id']])+' · PDF p. '+str(r['pdf_page'])+'</a> · <a href="evidence-unmarked.pdf#page='+str(r['evidence_page'])+'">Page</a> · <a href="evidence-highlighted.pdf#page='+str(r['evidence_page'])+'">Marked page</a></span>' for r in refs[rid])+'</div>'
    label=c['lesson_label'];scope_label='Full lesson' if scope['full_lesson'] else 'Objectives '+', '.join(o['original_number'] for o in c['objectives'])
    def source_labels(ch):
        objective=next(o for o in c['objectives'] if o['id']==ch['objective_id'])
        labels=objective_labels(objective)
        if objective.get('number_origin')=='assigned' and objective.get('source_label'):
            labels=labels+['Original label: '+objective['source_label']]
        return ''.join('<p class="session-label">'+E(x)+'</p>' for x in labels if x not in ch['wording'])
    def shell(title,body):
        return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+E(title+' | '+label)+'</title><style>'+STYLE+'</style></head><body><main><p class="eyebrow">'+E(label+' · '+scope_label)+'</p>'+NAV+body+'</main></body></html>\n'
    def write(name,text):v.write_bytes(folder/name,text.encode());neutral_filesystem(folder/name)
    index='<h1>'+E(label)+'</h1><p>'+E(scope_label)+'</p><ol class="lesson-chapters">'
    for ch in c['chapters']:index+='<li><a href="'+E(ch['file'])+'">Objective '+E(ch['original_number'])+' · '+E(ch['title'])+'</a><p>'+E(ch['wording'])+'</p>'+source_labels(ch)+'</li>'
    write('index.html',shell(label,index+'</ol>'))
    for ch in c['chapters']:
        body='<h1>'+E(ch['title'])+'</h1><div class="scope"><strong>Objective '+E(ch['original_number'])+'</strong><p>'+E(ch['wording'])+'</p>'+source_labels(ch)+'</div>'
        body+='<ol class="contents">'+''.join('<li><a href="#'+E(s['id'])+'">'+E(s['title'])+'</a></li>' for s in ch['sections'])+'</ol>'
        for sec in ch['sections']:
            body+='<article id="'+E(sec['id'])+'">'
            for block_index,b in enumerate(sec['blocks']):
                if block_index==0:body+='<div class="section-opening"><h2>'+E(sec['title'])+'</h2>'
                blocks[b['id']]={'file':ch['file'],'title':sec['title'],'section_id':sec['id']}
                body+='<div class="block" id="'+E(b['id'])+'">'
                if b['type']=='figure':body+='<figure><img src="data:image/png;base64,'+base64.b64encode(images[b['id']]).decode()+'" alt="'+E(b['alt'])+'"><figcaption>'+E(b['text'])+'</figcaption></figure>'
                elif b['type']=='table':
                    body+='<table><caption>'+E(b['text'])+'</caption><thead><tr>'+''.join('<th scope="col">'+E(h)+'</th>' for h in b['headers'])+'</tr></thead><tbody>'
                    body+=''.join('<tr>'+''.join('<td data-label="'+E(h)+'">'+E(t)+'</td>' for h,t in zip(b['headers'],row))+'</tr>' for row in b['rows'])+'</tbody></table>'
                else:body+='<p>'+E(b['text'])+'</p>'
                body+=citations(b['id'])+'</div>'
                if block_index==0:body+='</div>'
            body+='</article>'
        if ch.get('related_objective_ids'):
            body+='<nav aria-label="Related chapters">'+''.join('<a href="'+E(chapter_for[i]['file'])+'">Objective '+E(chapter_for[i]['original_number'])+'</a>' for i in ch['related_objective_ids'])+'</nav>'
        write(ch['file'],shell(ch['title'],body))
    for answers in (False,True):
        title='Answers and marking guidance' if answers else 'Practice questions';body='<h1>'+title+'</h1>'
        if answers:body+='<p>Credit equivalent accurate wording. Award each point once, up to the stated total. No negative marking.'+(' A single-best-answer question carries one mark.' if c['sbas'] else '')+'</p>'
        for group,group_label in [('saqs','Written-response questions' if any(q.get('kind','short_answer')!='short_answer' for q in c['saqs']) else 'Short-answer questions'),('sbas','Single-best-answer questions')]:
            if not c[group]:continue
            extended=group=='saqs' and any(q.get('kind','short_answer')!='short_answer' for q in c[group])
            body+='<div class="section-opening'+(' extended-opening' if extended else '')+'"><h2>'+group_label+'</h2>'
            for n,q in enumerate(c[group],1):
                extra=' constructed-response' if q.get('kind','short_answer')!='short_answer' and group=='saqs' else ''
                body+='<article class="'+('answer' if answers else 'question')+extra+'" id="'+E(q['id'])+'"><p class="marks">'+str(q['marks'])+(' mark' if q['marks']==1 else ' marks')+'</p><h3>'+str(n)+'. '+E(q['prompt']).replace('\n','<br>')+'</h3>'
                if group=='sbas':body+='<ol class="options" style="list-style:none">'+''.join('<li>'+E(k)+'. '+E(t)+'</li>' for k,t in q['options'].items())+'</ol>'
                elif q.get('kind','short_answer')!='short_answer':body+='<p class="question-type">'+E({'essay':'Essay','calculation':'Calculation','data_interpretation':'Data interpretation','practical':'Practical scenario'}[q['kind']])+'</p>'
                if answers:
                    if group=='saqs':body+='<ol>'+''.join('<li>'+E(pt['text']).replace('\n','<br>')+' ('+str(pt['marks'])+(' mark' if pt['marks']==1 else ' marks')+')</li>' for pt in q['marking_points'])+'</ol><p>'+E(q['explanation']).replace('\n','<br>')+'</p>'
                    else:body+='<p><strong>Best answer: '+E(q['correct'])+'</strong></p>'+''.join('<p><strong>'+E(k)+'.</strong> '+E(t)+'</p>' for k,t in q['rationales'].items())
                    sections=dict.fromkeys((blocks[b]['file'],blocks[b]['section_id'],blocks[b]['title']) for b in q['guide_blocks'])
                    body+=citations(q['id'])+'<p>Revisit '+', '.join('<a href="'+E(file)+'#'+E(section)+'">'+E(title)+'</a>' for file,section,title in sections)+'.</p>'
                else:body+='<div class="answer-space"></div><a class="no-print" href="answers.html#'+E(q['id'])+'">Check answer</a>'
                body+='</article>'
                if n==1:body+='</div>'
        write('answers.html' if answers else 'practice.html',shell(title,body))
    for name,text in anki_export.payloads(c,refs,labels,scope).items():write(name,text)
    body='''<h1>Anki</h1><p><a href="anki.tsv" download>Download cards</a></p><ol><li>Create the <strong>Textbook Basic</strong> note type with fields <strong>StableID, Front, Back, Sources</strong>, in that order. Keep StableID first and off the displayed card.</li><li>Import <a href="anki.tsv">anki.tsv</a> as UTF-8 tab-separated text with HTML enabled. Map columns 1–4 to the fields and column 5 to Tags. Choose your deck. Matching stable IDs allow later imports to update notes.</li><li>Use the templates and styling in the <a href="anki-note-type.json">note-type specification</a>.</li></ol><p>The Sources field identifies the book, PDF page and included source page. Open the <a href="evidence-unmarked.pdf">source pages</a> or <a href="evidence-highlighted.pdf">marked source pages</a>.</p>'''
    write('anki.html',shell('Anki',body));neutral_filesystem(folder)
