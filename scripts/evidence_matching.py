import re, unicodedata
import pipeline_core as v
def matchnorm(t):
    t=unicodedata.normalize('NFC',t).replace('\u00ad','').replace('\u200b','')
    # Preserve hard hyphens, including numeric ranges and scientific notation.
    # Only actual soft hyphens may be removed; a wrap is not proof of semantics.
    return ' '.join(t.split())

def unique_start(full,needle):
    start=full.find(needle)
    return start if needle and start>=0 and full.find(needle,start+1)<0 else -1
def exact_highlight_fragments(page,passage,min_words=8):
    """Match bounded exact word sequences when a long PDF search cannot span runs.

    Every accepted fragment must be unique in original text. Failure is recorded,
    never repaired with guessed geometry or generative transcription.
    """
    full=matchnorm(page.get_text());accepted=[];unmatched=[]
    def visit(words):
        phrase=' '.join(words)
        # Search is case-insensitive and normally removes hard line-end hyphens.
        # Neither behaviour may select extra text or change the cited wording.
        quads=page.search_for(phrase,quads=True,flags=v.fitz.TEXTFLAGS_TEXT)
        if quads and unique_start(full,phrase)>=0 and unique_start(full.lower(),phrase.lower())>=0:
            accepted.append((phrase,quads));return
        if len(words)<min_words:
            unmatched.append(phrase);return
        pivot=len(words)//2;visit(words[:pivot]);visit(words[pivot:])
    visit(matchnorm(passage).split())
    return accepted,unmatched

def exact_native_span(page,passage):
    """Align just the two passage boundaries to native character/span geometry.

    Reconstruct the same page text and use matchnorm unchanged. Prefixes are
    checked exactly, including NFC composition; no fuzzy or word-only alignment.
    """
    pieces=[];spans=[];offset=0
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                text=''.join(ch['c'] for ch in span['chars'])
                spans.append((offset,offset+len(text),line['dir'],span))
                pieces.append(text);offset+=len(text)
            pieces.append('\n');offset+=1
    raw=''.join(pieces);full=matchnorm(raw);needle=matchnorm(passage)
    start=unique_start(full,needle)
    if full!=matchnorm(page.get_text()) or start<0:
        return []
    prefixes={}
    def prefix(pos):
        # The sentinel preserves a trailing normalized space at a boundary.
        if pos not in prefixes:prefixes[pos]=matchnorm(raw[:pos]+'\0')[:-1]
        return prefixes[pos]
    def boundary(target):
        candidates=[]
        for lo,hi,_,span in spans:
            if len(prefix(lo))<=target<=len(prefix(hi)):
                pos=lo
                for ch in span['chars']:
                    if prefix(pos)==full[:target]:candidates.append(pos)
                    pos+=len(ch['c'])
                if prefix(pos)==full[:target]:candidates.append(pos)
        return max(candidates) if candidates else None
    lo=boundary(start);hi=boundary(start+len(needle))
    if lo is None or hi is None or matchnorm(raw[lo:hi])!=needle:return []
    quads=[]
    for begin,end,direction,span in spans:
        if end<=lo or begin>=hi:continue
        chars=[];pos=begin
        for ch in span['chars']:
            next_pos=pos+len(ch['c'])
            if lo<=pos and next_pos<=hi:chars.append(ch)
            pos=next_pos
        while chars and not matchnorm(chars[0]['c']):chars.pop(0)
        while chars and not matchnorm(chars[-1]['c']):chars.pop()
        if chars:quads.append(v.fitz.recover_span_quad(direction,span,chars=chars))
    return quads

def preserve_page_group(source,source_page,destination,destination_page):
    # Adopted unchanged algorithm from kit; preserve transparency object graph.
    if source.xref_get_key(source[source_page].xref,'Group')[0]=='null':return
    pdf=v.fitz.mupdf;src=pdf.PdfDocument(source.this);dst=pdf.PdfDocument(destination.this)
    group=pdf.pdf_dict_gets(pdf.pdf_lookup_page_obj(src,source_page),'Group')
    pdf.pdf_dict_puts(pdf.pdf_lookup_page_obj(dst,destination_page),'Group',pdf.pdf_graft_object(dst,group))
def exact_native_block(page, passage):
    """Locate a unique complete native-text block before using its span quads.

    This handles soft-hyphen and mixed-font search failures without dropping
    words or inventing geometry. Source text and the authored passage must match.
    """
    full=matchnorm(page.get_text());needle=matchnorm(passage)
    if unique_start(full,needle)<0:
        return ([],[needle]), 'exact_phrase_fragments'
    candidates=[]
    for block in page.get_text('dict')['blocks']:
        if 'lines' not in block:
            continue
        text='\n'.join(''.join(span['text'] for span in line['spans']) for line in block['lines'])
        if matchnorm(text)==matchnorm(passage):
            candidates.append(block)
    if len(candidates)!=1:
        fragments=exact_highlight_fragments(page, passage, min_words=2)
        if fragments[1]:
            quads=exact_native_span(page,passage)
            if quads:return ([(needle,quads)],[]), 'exact_native_span_text'
        return fragments, 'exact_phrase_fragments'
    quads=[v.fitz.recover_quad(line['dir'],span) for line in candidates[0]['lines']
           for span in line['spans'] if span['text'].strip()]
    assert quads
    return ([(matchnorm(passage),quads)],[]), 'exact_native_block_text'
