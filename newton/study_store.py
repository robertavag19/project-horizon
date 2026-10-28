"""Local, profile-isolated study records. No network or model calls."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import copy
import csv
import io
import json
import os
from pathlib import Path
import re
import uuid
from devtools.workers import WorkerError
from .study_contract import text, check_card, raw_bundle, validate_bundle
from .study_library import sources, catalogue
from .study_math import grade
from .study_schedule import schedule

DEFAULT_PROFILE={'nickname':'','country':'Canada','province':'','grade':'','course':'','curriculum_version':'','subject':'Physics','knowledge_level':'','goal':'','language':'en','vocabulary':'plain','depth':'standard','help':'worked_example','response_style':'teacher','reduced_motion':True,'large_text':False,'review_scheduler':'simple'}
PROVINCES=['','Ontario','Quebec','British Columbia','Alberta','Manitoba','Saskatchewan','Nova Scotia','New Brunswick','Newfoundland and Labrador','Prince Edward Island','Yukon','Northwest Territories','Nunavut']

def validate_profile(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT_PROFILE):raise WorkerError('study_invalid_profile')
    p={**DEFAULT_PROFILE,**value}
    for k,v in p.items():
        if k in ('reduced_motion','large_text'):
            if type(v) is not bool:raise WorkerError('study_invalid_profile')
        else:text(v,400 if k=='goal' else 80)
    enums={'vocabulary':['plain','standard','technical'],'depth':['brief','standard','detailed'],'help':['hints','guided','worked_example','practice'], 'response_style':['teacher','supervisor','concise'],'province':PROVINCES,'review_scheduler':['simple','fsrs']}
    if any(p[k] not in choices for k,choices in enums.items()):raise WorkerError('study_invalid_profile')
    return p

class StudyStore:
    def __init__(self,root):
        self.root=Path(root).resolve(); self.base=self.root/'runs'/'study'
        for path in (self.root/'runs',self.base):
            if path.is_symlink() or (path.exists() and not path.resolve().is_relative_to(self.root)):
                raise WorkerError('study_invalid_storage_path')
            if path.exists() and getattr(path.stat(),'st_file_attributes',0)&0x400:raise WorkerError('study_invalid_storage_path')
        self.base.mkdir(parents=True,exist_ok=True)

    def path(self,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{32}',identity):raise WorkerError('study_invalid_id')
        path=self.base/(identity+'.json')
        if path.is_symlink() or (path.exists() and getattr(path.stat(),'st_file_attributes',0)&0x400):raise WorkerError('study_invalid_storage_path')
        return path

    def read(self,identity):
        path=self.path(identity)
        if not path.is_file():raise WorkerError('study_profile_not_found')
        if path.stat().st_size>2_000_000:raise WorkerError('study_storage_limit')
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema_version')!=1 or data.get('id')!=identity:raise WorkerError('study_invalid_storage')
        data['profile']=validate_profile(data['profile'])
        return data

    def listing(self):
        result=[]
        for p in sorted(self.base.glob('*.json'))[:20]:
            d=self.read(p.stem);result.append({'id':d['id'],'nickname':d['profile']['nickname'] or 'Learner '+d['id'][:6]})
        return result

    def save(self,data):
        data['revision']+=1
        body=json.dumps(data,ensure_ascii=False,allow_nan=False)
        if len(body.encode())>2_000_000:raise WorkerError('study_storage_limit')
        path=self.path(data['id']);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_text(body,encoding='utf-8');os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)

    @contextmanager
    def transaction(self,identity):
        path=self.path(identity);lock=path.with_suffix('.lock')
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise WorkerError('study_profile_busy') from None
        os.close(fd)
        try:
            data=self.read(identity);yield data;self.save(data)
        finally:lock.unlink(missing_ok=True)

    def create(self,profile):
        if len(self.listing())>=20:raise WorkerError('study_profile_limit')
        identity=uuid.uuid4().hex
        data={'schema_version':1,'id':identity,'revision':0,'profile':validate_profile(profile),'artifacts':[], 'attempts':[], 'reviews':[], 'private_sources':[]}
        self.save(data);return data

    def update_profile(self,identity,profile):
        with self.transaction(identity) as data:data['profile']=validate_profile(profile)
        return self.read(identity)

    def reset(self,identity):
        with self.transaction(identity) as data:
            data.update(profile=copy.deepcopy(DEFAULT_PROFILE),artifacts=[],attempts=[],reviews=[],private_sources=[])
        return self.read(identity)

    def delete(self,identity):
        # Explicit confirmed local UI/CLI operation, never model-controlled.
        path=self.path(identity);lock=path.with_suffix('.lock')
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise WorkerError('study_profile_busy') from None
        os.close(fd)
        try:self.read(identity);path.unlink()
        finally:lock.unlink(missing_ok=True)

    def add_source(self,identity,source):
        with self.transaction(identity) as data:
            if len(data['private_sources'])>=20:raise WorkerError('study_source_limit')
            if not any(s['id']==source['id'] for s in data['private_sources']):data['private_sources'].append(source)
        return source['id']

    def add_bundle(self,identity,bundle,available,origin='model_draft'):
        with self.transaction(identity) as data:
            checked=validate_bundle(bundle,available,data['profile'])
            if len(data['artifacts'])>=50:raise WorkerError('study_artifact_limit')
            artifact={'id':uuid.uuid4().hex,'created_at':datetime.now(timezone.utc).isoformat(),'origin':origin,'revision':1,'bundle':checked}
            for block in checked['blocks']:
                block.update(id=uuid.uuid4().hex,revision=1,active=False)
                for card in block.get('cards',[]):card.update(id=uuid.uuid4().hex,revision=1,next_due=None)
                for q in block.get('questions',[]):q['id']=uuid.uuid4().hex
            data['artifacts'].append(artifact)
        return artifact

    def block(self,data,artifact_id,block_id):
        for a in data['artifacts']:
            if a['id']==artifact_id:
                for b in a['bundle']['blocks']:
                    if b['id']==block_id:return a,b
        raise WorkerError('study_artifact_not_found')

    def accept_deck(self,identity,artifact_id,block_id):
        with self.transaction(identity) as data:
            a,b=self.block(data,artifact_id,block_id)
            if b['type']!='flashcards':raise WorkerError('study_deck_required')
            b['active']=True;b['accepted_at']=datetime.now(timezone.utc).isoformat();b['revision']+=1;a['revision']+=1
        return self.read(identity)

    def edit_card(self,identity,artifact_id,block_id,card_id,changes,allow_private=False):
        if not isinstance(changes,dict) or not set(changes)<= {'front','back','explanation'}:raise WorkerError('study_invalid_card_edit')
        with self.transaction(identity) as data:
            a,b=self.block(data,artifact_id,block_id)
            card=next((c for c in b.get('cards',[]) if c['id']==card_id),None)
            if card is None:raise WorkerError('study_card_not_found')
            for k,v in changes.items():text(v,500 if k=='front' else 800,False)
            card.update(changes)
            if card['kind']=='cloze' and card['front'].count('____')!=1:raise WorkerError('study_cloze_requires_one_blank')
            if any(c['id']!=card_id and ' '.join(c['front'].lower().split())==' '.join(card['front'].lower().split()) for c in b['cards']):raise WorkerError('study_duplicate_card')
            # An edited numeric card is no longer tied to its old calculation.
            card['calculation']=None
            if card['kind']=='numeric':card['kind']='basic'
            card.pop('scheduling',None)
            card['revision']+=1;card['next_due']=None
            card['verification']={'structure':'passed','source_locators':'recheck_required','numerical':'invalidated_by_edit','curriculum':'recheck_required','human_review':'not_reviewed','remaining':['Edited content requires review.']}
            b['verification']=copy.deepcopy(card['verification']);b['active']=False;b['revision']+=1;a['revision']+=1
        return self.read(identity)

    def review(self,identity,artifact_id,block_id,card_id,rating,now=None):
        if rating not in ('Again','Hard','Good','Easy'):raise WorkerError('study_invalid_rating')
        now=now or datetime.now(timezone.utc)
        with self.transaction(identity) as data:
            a,b=self.block(data,artifact_id,block_id)
            if b['type']!='flashcards' or not b['active']:raise WorkerError('study_accept_deck_first')
            card=next((c for c in b['cards'] if c['id']==card_id),None)
            if card is None:raise WorkerError('study_card_not_found')
            due,state,engine=schedule(card,rating,now,data['profile'].get('review_scheduler','simple'))
            card['next_due']=due
            if state is None:card.pop('scheduling',None)
            else:card['scheduling']=state
            data['reviews']=(data['reviews']+[{'card_id':card_id,'revision':card['revision'],'rating':rating,'at':now.isoformat(),'kind':'self_reported_recall','scheduler':engine}])[-1000:]
        return self.read(identity)

    def attempt(self,identity,artifact_id,block_id,question_id,answer):
        with self.transaction(identity) as data:
            _,b=self.block(data,artifact_id,block_id)
            q=next((q for q in b.get('questions',[]) if q['id']==question_id),None)
            if q is None:raise WorkerError('study_question_not_found')
            if q['kind']=='numeric':outcome=grade(q['calculation'],answer)
            else:
                text(answer,1500,False)
                outcome={'correct':None,'reason':'ungraded_open_response','feedback':'Compare your answer with the rubric, or explicitly ask Newton for formative feedback (one invocation maximum).','rubric':q['rubric']}
            data['attempts']=(data['attempts']+[{'question_id':question_id,'artifact_id':artifact_id,'at':datetime.now(timezone.utc).isoformat(),'answer':answer,'outcome':outcome}])[-200:]
        return outcome

    def export_deck(self,identity,artifact_id,block_id,format='json'):
        _,b=self.block(self.read(identity),artifact_id,block_id)
        if b['type']!='flashcards':raise WorkerError('study_deck_required')
        raw=raw_bundle({'schema_version':1,'blocks':[b]})
        if format=='json':return json.dumps(raw,ensure_ascii=False,indent=2)
        if format!='csv':raise WorkerError('study_export_format')
        out=io.StringIO();writer=csv.writer(out);writer.writerow(['front','back','explanation'])
        def safe(s):return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r','\n')) or s.startswith(('\t','\r','\n')) else s
        for c in b['cards']:writer.writerow([safe(c[k]) for k in ('front','back','explanation')])
        return out.getvalue()
