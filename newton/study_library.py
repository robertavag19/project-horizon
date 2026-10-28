"""Bounded lexical retrieval with explicit source provenance, not source authority."""
import hashlib
import json
from pathlib import Path
import re
from devtools.workers import WorkerError

CATALOG = Path(__file__).resolve().parents[1] / 'education' / 'pilot.json'
STOP = {'a','an','the','of','to','and','is','in','me','please','explain','make','show','from','this','that','with','for','how','what','my','i'}

def catalogue():
    return json.loads(CATALOG.read_text(encoding='utf-8'))

def aligned(profile):
    return (profile.get('country'),profile.get('province'),profile.get('grade'),profile.get('course'),profile.get('curriculum_version')) == ('Canada','Ontario','11','SPH3U','2008 revised')

def sources(profile, private=(), allow_private=False):
    values = catalogue()['sources']
    values = [s for s in values if s['kind'] != 'official_curriculum' or aligned(profile)]
    return values + (list(private) if allow_private else [])

def reference_set(values):
    return {(s['id'], c['locator']) for s in values for c in s['chunks']}

def retrieve(query, profile, private=(), allow_private=False, limit=3, max_chars=4500):
    terms = set(re.findall(r'[a-z0-9]+', query.lower())) - STOP
    ranked = []
    for source in sources(profile,private,allow_private):
        for chunk in source['chunks']:
            words=set(re.findall(r'[a-z0-9]+', (source['title']+' '+chunk['text']+' '+' '.join(chunk['objectives'])).lower()))
            score=len(terms & words) + 2*len(terms & set(chunk['objectives']))
            if score: ranked.append((score,source['id'],chunk['locator'],source,chunk))
    ranked.sort(key=lambda item:(-item[0],item[1],item[2]))
    result=[]
    for _,_,_,source,chunk in ranked[:limit]:
        item={'source_id':source['id'],'title':source['title'],'kind':source['kind'],**chunk}
        if len(json.dumps(result+[item],ensure_ascii=False))>max_chars: break
        result.append(item)
    return result

def validate_references(refs, available):
    if not isinstance(refs,list) or len(refs)>5: raise WorkerError('study_reference_limit')
    allowed=reference_set(available)
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)!={'source_id','locator'} or not all(isinstance(x,str) for x in ref.values()):
            raise WorkerError('study_invalid_reference')
        if (ref['source_id'],ref['locator']) not in allowed: raise WorkerError('study_unknown_source_locator')
    return 'locators_exist_not_entailment' if refs else 'no_sources_claimed'

def import_excerpt(personal, name, start=1, title='', author='User-provided', language='en', version='unspecified'):
    # Existing permission, size, link and credential protections remain authoritative.
    if not isinstance(name,str) or type(start) is not int or start<1:raise WorkerError('study_invalid_source_metadata')
    if any(not isinstance(v,str) or len(v)>n for v,n in ((title,200),(author,200),(language,40),(version,100))):raise WorkerError('study_invalid_source_metadata')
    result=personal.read(name,start,3)
    if result.get('ocr_required'): raise WorkerError('study_ocr_required_no_text_imported')
    chunks=[]
    if 'pages' in result:
        for page in result['pages']:
            if page['text'].strip():
                chunks.append({'locator':'pdf-page-'+str(page['page']),'pdf_page_index':page['page']-1,'page_label':page.get('page_label'), 'text':page['text'][:3000], 'objectives':[]})
    else:
        chunks=[{'locator':'lines-'+str(start),'pdf_page_index':None,'page_label':None,'text':result['text'][:3000],'objectives':[]}]
    if not chunks or not any(c['text'].strip() for c in chunks): raise WorkerError('study_empty_source')
    digest=hashlib.sha256(json.dumps(chunks,sort_keys=True).encode()).hexdigest()
    return {'id':'personal-'+digest[:20],'title':title or Path(result['path']).name,'author':author,'publisher':'User-provided',
            'language':language,'version':version,'kind':'personal_excerpt','origin':result['path'],
            'permission':'Private excerpt stored at user request; no redistribution permission asserted',
            'checksum':digest,'checksum_scope':'selected extracted chunks','tags':[], 'chunks':chunks,
            'extraction':'bounded excerpt; not whole document; no OCR; source may contain extraction errors'}
