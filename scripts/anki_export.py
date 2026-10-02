"""Anki field serialization, independent of HTML/CSS."""
import csv,html,io,json,re,unicodedata
from pathlib import Path
import pipeline_core as v
import workflow as w
E=html.escape
NOTE_TYPE={'name':'Textbook Basic','fields':['StableID','Front','Back','Sources'],
    'card_templates':[{'name':'Recall','front':'{{Front}}','back':'{{FrontSide}}<hr id="answer">{{Back}}<div class="sources">{{Sources}}</div>'}],
    'css':'.card{font-family:Arial;font-size:22px;text-align:left;line-height:1.5}.sources{font-size:12px;margin-top:1.5em}',
    'stable_id_is_regular_first_field':True}

def topic_tags(card):
    tags=card.get('tags')
    if not isinstance(tags,list) or not all(isinstance(t,str) and re.fullmatch(r'[A-Za-z0-9_:.+-]+',t) for t in tags):
        raise ValueError('Card topic tags must be a list of safe tag strings')
    if any(t.split('::')[0].casefold() in {'lesson','objective'} for t in tags):
        raise ValueError('Lesson/Objective tag namespaces are generated; use topic tags only')
    return list(dict.fromkeys(tags))


def canonical_tags(c,scope):
    """Identity comes from verified scope/register data, never model labels."""
    import intake,anki_preferences
    register=intake.curriculum()
    w.scope_current(scope)
    lesson,objectives=w.select_scope(scope['lesson_id'],None if scope['full_lesson'] else scope['objective_ids'])
    if ([o['id'] for o in objectives]!=scope['objective_ids'] or c['objectives']!=objectives
            or any(scope[k]!=lesson[j] for k,j in [('lesson_filename','filename'),('source_path','source_path'),('source_sha256','source_sha256')])):
        raise ValueError('Anki scope differs from registered lesson/objectives')
    slugs={};seen=set()
    for row in register['lessons']:
        name=re.sub(r'^LOs?\s+','',Path(row['filename']).stem,flags=re.I)
        name=unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode()
        slug=re.sub(r'[^A-Za-z0-9]+','_',name).strip('_')
        if row.get('intake_version'):
            slug=(slug or 'Unit')+'_'+w.semantic(row['id'])[:8]
        elif not slug or slug.casefold() in seen:
            raise ValueError('Empty/colliding lesson tag; explicit tag disambiguation policy needed')
        seen.add(slug.casefold());slugs[row['id']]=slug
    slug=slugs[lesson['id']];objective_tags={};seen=set()
    for obj in register['entries']:
        if obj['lesson_id']!=lesson['id'] or obj['entry_kind']!='objective':continue
        token=obj['original_number'];occurrence=obj.get('number_occurrence',1)
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*',token) or type(occurrence) is not int or occurrence<1:
            raise ValueError('Unsupported original objective numbering')
        tag='Objective::'+slug+'::'+token+(f'::occurrence_{occurrence}' if occurrence>1 else '')
        if tag in seen:raise ValueError('Colliding registered objective tags')
        seen.add(tag);objective_tags[obj['id']]=tag
    result={};custom=anki_preferences.tags(scope,objectives)
    for card in c['cards']:
        ids=card.get('objective_ids')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(scope['objective_ids']):
            raise ValueError('Missing, duplicate or out-of-scope card objective')
        result[card['id']]=list(dict.fromkeys(['Lesson::'+slug]+[objective_tags[o['id']] for o in objectives if o['id'] in ids]
                                            +[custom[o['id']] for o in objectives if o['id'] in ids and o['id'] in custom]+topic_tags(card)))
    return result


def payloads(c,refs,labels,scope):
    tags=canonical_tags(c,scope)
    stream=io.StringIO(newline='');stream.write('#separator:Tab\n#html:true\n#columns:StableID\tFront\tBack\tSources\tTags\n#tags column:5\n')
    writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
    def anki_text(text):return E(text).replace('\r\n','\n').replace('\r','\n').replace('\t','&#9;').replace('\n','<br>')
    for card in c['cards']:
        sources='<br>'.join(E(labels[r['source_id']])+f' · PDF p. {r["pdf_page"]}; included source page {r["evidence_page"]}' for r in refs[card['id']])
        writer.writerow([card['id'],anki_text(card['front']),anki_text(card['back']),sources,' '.join(tags[card['id']])])
    return {'anki.tsv':stream.getvalue(),'anki-note-type.json':json.dumps(NOTE_TYPE,ensure_ascii=False,indent=2)+'\n'}
