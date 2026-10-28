"""Study workflows shared by terminal and API; all methods here are local."""
import copy
import json
import re
from devtools.workers import WorkerError
from .study_store import StudyStore, DEFAULT_PROFILE, PROVINCES
from .study_library import catalogue, sources, retrieve, aligned, import_excerpt
from .study_contract import STUDY_INSTRUCTIONS, LIMIT
from .study_math import visualization

ACTIONS=('explain','visualize','flashcards','practice','plan')

def infer_action(message):
    t=message.lower()
    # Restrict to teaching-artifact requests; source-code requests keep their existing route.
    if re.search(r'\b(?:src|tests|newton|docs)/|\b(?:file|function|module|python code)\b',t):return None
    if re.search(r'\b(?:flash\s?cards?|deck)\b',t) and re.search(r'\b(?:make|create|generate|build|give|prepare)\b',t):return 'flashcards'
    if re.search(r'\b(?:visuali[sz]e|diagram|plot|graph)\b',t) and re.search(r'\b(?:show|make|draw|plot|visuali[sz]e|create)\b',t):return 'visualize'
    if re.search(r'\b(?:quiz me|test my understanding|give me.*practice|make.*practice)\b',t):return 'practice'
    return None

def demo_bundle():
    ref=[{'source_id':'newton-mechanics-v1','locator':'velocity'}]
    calc={'formula':'average_velocity','inputs':{'displacement':{'value':20,'unit':'m'},'time':{'value':4,'unit':'s'}}}
    cards=[]
    items=[('concept','What is average velocity?','Displacement divided by elapsed time.','velocity'),('misconception','Can constant speed coexist with acceleration?','Yes, when the velocity direction changes, as in circular motion.','circular'),('cloze','The SI unit of acceleration is ____.','m/s²','units'),('basic','What does the slope of a velocity-time graph represent?','Acceleration.','graphs'),('numeric','Find average velocity for +20 m displacement over 4 s.','5 m/s','velocity')]
    for kind,front,back,locator in items:
        cards.append({'kind':kind,'front':front,'back':back,'explanation':'Consider direction and use compatible units.','difficulty':'easy','sources':[{'source_id':'newton-mechanics-v1','locator':locator}],'calculation':calc if kind=='numeric' else None})
    return {'schema_version':1,'blocks':[
        {'type':'explanation','title':'Mechanics starter — original offline material','objective':'Distinguish velocity and acceleration.','sources':ref,'body':'Velocity describes rate and direction of displacement. Acceleration describes change in velocity. These are original project notes, not an official textbook or live answer.'},
        {'type':'visualization','title':'Constant-acceleration graph','objective':'Connect position and velocity.','sources':[{'source_id':'newton-mechanics-v1','locator':'graphs'}],'spec':{'kind':'motion','parameters':{'position':0,'velocity':2,'acceleration':3,'duration':4}}},
        {'type':'flashcards','title':'Mechanics starter deck','objective':'Recall five mechanics ideas.','sources':ref,'cards':cards},
        {'type':'practice','title':'Short mechanics practice','objective':'Calculate velocity and explain acceleration.','sources':ref,'questions':[
            {'kind':'numeric','prompt':'An object moves +20 m in 4 s. Calculate average velocity.','calculation':calc,'sources':ref,'rubric':'Use displacement/time with compatible units; retain direction.','hints':['Identify displacement and elapsed time.','Use v_avg = Δx/Δt.','Substitute 20 m / 4 s.','The result is +5 m/s.']},
            {'kind':'open','prompt':'Why can constant speed around a circle involve acceleration?','calculation':None,'sources':[{'source_id':'newton-mechanics-v1','locator':'circular'}],'rubric':'Mention velocity direction changes; acceleration is inward. Constant speed alone does not mean constant velocity.','hints':['Compare speed with velocity.','Velocity includes direction.','The tangent changes around the circle.','Acceleration describes the changing velocity direction and points inward.']}
        ]}
    ]}

class StudyService:
    def __init__(self,session):self.session=session;self.store=StudyStore(session.root)
    @property
    def selected(self):return self.session.state.get('study_profile_id')
    def data(self):
        if not self.selected:raise WorkerError('study_profile_required: create or select a study profile first (local, no model call)')
        return self.store.read(self.selected)
    def select(self,identity):
        if identity:self.store.read(identity)
        self.session.state['study_profile_id']=identity
        self.session.pending_context=[]
        self.session._persist()
    def available(self,data):return sources(data['profile'],data['private_sources'],self.session.personal_files.approved)
    def view(self):
        d=self.store.read(self.selected) if self.selected else None
        catalog=catalogue()
        private=[] if not d or not self.session.personal_files.approved else [{**{k:v for k,v in s.items() if k not in ('chunks','origin')},'chunks':[{'locator':c['locator']} for c in s['chunks']]} for s in d['private_sources']]
        public=sources(d['profile'] if d else DEFAULT_PROFILE)
        return {'selected':self.selected,'profiles':self.store.listing(),'profile':d['profile'] if d else None,
                'artifacts':d['artifacts'] if d else [],'progress':{'attempts':d['attempts'] if d else [],'reviews':d['reviews'] if d else [],'notice':'Attempts and self-rated recall are not mastery or official grades.'},
                'sources':public+private,'pilot':catalog['pilot'],'provinces':PROVINCES,
                'curriculum_status':catalog['pilot']['mapping_status'] if d and aligned(d['profile']) else 'General physics practice; curriculum mapping pending.',
                'language_status':'English pilot. Other languages have not been evaluated.', 'artifact_limit':LIMIT,
                'privacy':'Local profiles are not authenticated user accounts. Personal excerpts require current file approval for retrieval.'}
    def context(self,message):
        if not self.selected:return '',[]
        d=self.data();p=d['profile']; found=retrieve(message,p,d['private_sources'],self.session.personal_files.approved)
        # Carry only references from the latest saved activity for explicit lesson follow-ups.
        if d['artifacts'] and re.search(r'\b(?:this|that|previous|last) (?:lesson|activity|explanation)\b',message,re.I):
            refs={(r['source_id'],r['locator']) for b in d['artifacts'][-1]['bundle']['blocks'] for r in b.get('sources',[])}
            related=[{'source_id':s['id'],'title':s['title'],'kind':s['kind'],**c} for s in self.available(d) for c in s['chunks'] if (s['id'],c['locator']) in refs]
            keys={(r['source_id'],r['locator']) for r in related}
            found=(related+[r for r in found if (r['source_id'],r['locator']) not in keys])[:3]
        minimal={k:p[k] for k in ('country','province','grade','course','curriculum_version','subject','knowledge_level','goal','language','vocabulary','depth','help','response_style')}
        body={'profile_preferences_untrusted':minimal,'curriculum_status':self.view()['curriculum_status'],'evidence_untrusted':found}
        while len(json.dumps(body,ensure_ascii=False))>6000 and found:
            found.pop()
        encoded=json.dumps(body,ensure_ascii=False)
        if len(encoded)>6000:raise WorkerError('study_context_limit')
        return encoded,found
    def save_generation(self,bundle,retrieved):
        d=self.data()
        allowed={(r['source_id'],r['locator']) for r in retrieved}
        available=[]
        for s in self.available(d):
            available.append({**s,'chunks':[c for c in s['chunks'] if (s['id'],c['locator']) in allowed]})
        return self.store.add_bundle(self.selected,bundle,available)
    def operation(self,action,args):
        allowed={
            'create':{'profile'},'select':{'id'},'update_profile':{'profile'},'reset':{'confirm'},'delete':{'confirm'},'export_profile':set(),
            'demo':set(),'source':{'source_id','locator'},'search':{'query'},'import_source':{'path','start','title','author','language','version'},
            'accept_deck':{'artifact_id','block_id'},'edit_card':{'artifact_id','block_id','card_id','changes'},'review':{'artifact_id','block_id','card_id','rating'},
            'attempt':{'artifact_id','block_id','question_id','answer'},'export_deck':{'artifact_id','block_id','format'},'import_deck':{'bundle'},'visualization':{'spec'}}
        if action not in allowed or not isinstance(args,dict) or set(args)-allowed[action]:raise WorkerError('study_invalid_operation')
        result=None
        if action=='create':d=self.store.create(args.get('profile',{}));self.select(d['id'])
        elif action=='select':self.select(args.get('id'))
        elif action=='visualization':result=visualization(args.get('spec'))
        else:
            d=self.data();identity=self.selected
            if action=='update_profile':self.store.update_profile(identity,args.get('profile',{}))
            elif action in ('reset','delete'):
                if args.get('confirm') is not True:raise WorkerError('study_confirmation_required')
                if action=='reset':self.store.reset(identity)
                else:self.store.delete(identity);self.select(None)
                self.session.pending_context=[]
            elif action=='export_profile':result={'format':'json','text':json.dumps(d,ensure_ascii=False,indent=2),'contains_private_data':True}
            elif action=='demo':result=self.store.add_bundle(identity,demo_bundle(),self.available(d),origin='original_offline_fixture_not_live_generation')
            elif action=='search':result=retrieve(args.get('query',''),d['profile'],d['private_sources'],self.session.personal_files.approved)
            elif action=='source':
                found=None
                for s in self.available(d):
                    for c in s['chunks']:
                        if s['id']==args.get('source_id') and c['locator']==args.get('locator'):found={'source':{k:v for k,v in s.items() if k!='chunks'},'chunk':c}
                if not found:raise WorkerError('study_source_unavailable_or_permission_required')
                result=found
            elif action=='import_source':
                source=import_excerpt(self.session.personal_files,args.get('path',''),args.get('start',1),args.get('title',''),args.get('author','User-provided'),args.get('language','en'),args.get('version','unspecified'))
                result={'source_id':self.store.add_source(identity,source)}
            elif action=='accept_deck':self.store.accept_deck(identity,args.get('artifact_id'),args.get('block_id'))
            elif action=='edit_card':self.store.edit_card(identity,args.get('artifact_id'),args.get('block_id'),args.get('card_id'),args.get('changes'),self.session.personal_files.approved)
            elif action=='review':self.store.review(identity,args.get('artifact_id'),args.get('block_id'),args.get('card_id'),args.get('rating'))
            elif action=='attempt':result=self.store.attempt(identity,args.get('artifact_id'),args.get('block_id'),args.get('question_id'),args.get('answer'))
            elif action=='export_deck':result={'format':args.get('format','json'),'text':self.store.export_deck(identity,args.get('artifact_id'),args.get('block_id'),args.get('format','json'))}
            elif action=='import_deck':
                bundle=args.get('bundle')
                if not isinstance(bundle,dict) or any(b.get('type')!='flashcards' for b in bundle.get('blocks',[]) if isinstance(b,dict)):raise WorkerError('study_deck_required')
                result=self.store.add_bundle(identity,bundle,self.available(d),origin='imported_unreviewed')
        return {'view':self.view(),'result':result}
    def local(self,message):
        t=message.strip();low=t.lower()
        if not low.startswith('study '):return None
        if low=='study help':return {'reply':'Local: study profile, study create NAME, study select ID, study ontario, study general, study demo, study sources QUERY, study progress, study export, study reset confirm, study delete confirm. Use the app Study tab for cards and interactive visuals. Generate with study ask explain|visualize|flashcards|practice|plan QUESTION (at most one invocation).','status':'local'}
        if low.startswith('study ask '):return None
        result=None
        if low.startswith('study create '):self.operation('create',{'profile':{'nickname':t[13:].strip()}})
        elif low.startswith('study select '):self.operation('select',{'id':t[13:].strip()})
        elif low in ('study ontario','study general'):
            p=copy.deepcopy(self.data()['profile']);pilot=catalogue()['pilot']
            p.update({k:pilot[k] if low=='study ontario' else DEFAULT_PROFILE[k] for k in ('country','province','grade','course','curriculum_version')})
            self.operation('update_profile',{'profile':p})
        elif low=='study demo':result=self.operation('demo',{})['result']
        elif low.startswith('study sources '):result=self.operation('search',{'query':t[14:]})['result']
        elif low=='study export':result=self.operation('export_profile',{})['result']
        elif low in ('study reset confirm','study delete confirm'):self.operation(low.split()[1],{'confirm':True})
        elif low not in ('study profile','study progress','study open'):raise WorkerError('study_unknown_command: use study help')
        v=self.view()
        summary={'selected':v['selected'],'profiles':v['profiles'],'profile':v['profile'],'curriculum_status':v['curriculum_status'],'artifacts_saved':len(v['artifacts']), 'attempts':len(v['progress']['attempts']),'self_ratings':len(v['progress']['reviews'])}
        return {'reply':json.dumps(result or summary,ensure_ascii=False,indent=2)+'\nLocal action: zero model calls. To view saved artifacts, launch python -m newton.api --mode mock in your shell and select this study profile.','status':'local','study':v}
