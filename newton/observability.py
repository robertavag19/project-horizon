"""Bounded local activity records and explicit metadata-only Langfuse OTLP export."""
import base64
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from devtools.workers import WorkerError

EVENTS={'message_started','intent_selected','edits_applied','tests_finished','local_tool_requested','local_tool_result','operation_failed','worker_event','message_finished','invocation_prevented','local_command_finished'}
SUCCESS={'answered','planned','study_artifact_saved','changes_tested_review_required','tests_passed_review_required','mock_completed','local','tool_results_ready','exit'}

def storage(root):
    root=Path(root).resolve();base=root/'runs'/'hub'
    for p in (root/'runs',base):
        if p.is_symlink() or (p.exists() and (not p.resolve().is_relative_to(root) or getattr(p.stat(),'st_file_attributes',0)&0x400)):
            raise WorkerError('hub_invalid_storage')
    base.mkdir(parents=True,exist_ok=True)
    return base

def safe_file(base,name):
    p=base/name
    if p.is_symlink() or (p.exists() and getattr(p.stat(),'st_file_attributes',0)&0x400):raise WorkerError('hub_invalid_storage')
    return p

def integer(value,default=0):return value if type(value) is int and 0<=value<=10**12 else default

def local_host(value):
    if not isinstance(value,str):raise WorkerError('langfuse_local_host_required')
    u=urlsplit(value)
    try:port=u.port
    except ValueError:raise WorkerError('langfuse_local_host_required') from None
    if u.scheme!='http' or u.hostname not in ('127.0.0.1','localhost') or not port or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:
        raise WorkerError('langfuse_local_host_required')
    return 'http://127.0.0.1:'+str(port)

class Activity:
    def __init__(self,root,mode='codex'):
        if mode not in ('mock','codex'):raise WorkerError('hub_invalid_mode')
        self.base=storage(root);self.journal='activity-'+mode+'.json'
    def recent(self):
        p=safe_file(self.base,self.journal)
        if not p.exists():return []
        if p.stat().st_size>3_000_000:raise WorkerError('hub_activity_too_large')
        value=json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(value,list):raise WorkerError('hub_invalid_activity')
        return value[-500:]
    def add(self,record):
        rows=self.recent();rows.append(record)
        p=safe_file(self.base,self.journal);temp=safe_file(self.base,self.journal+'.tmp')
        temp.write_text(json.dumps(rows[-500:],allow_nan=False),encoding='utf-8');temp.replace(p)
    def record(self,job,before,after,events):
        result=job.get('result') or {};status=result.get('status') or ('internal_error' if job.get('error') else 'unknown')
        status=status if isinstance(status,str) and re.fullmatch(r'[a-z_]{1,64}',status) else 'other'
        prevented=max(0,integer(after.get('prevented_invocations'))-integer(before.get('prevented_invocations')))
        calls=max(0,integer(after.get('live_used'))-integer(before.get('live_used')))
        outcome='prevented' if prevented else 'local' if status in ('local','exit') else 'success' if status in SUCCESS else 'failed'
        usage=result.get('usage') or {};usage=usage if isinstance(usage,dict) else {}
        checks=result.get('verification') or {};checks=checks if isinstance(checks,dict) else {}
        provider=job.get('provider');provider=provider if provider in ('codex','mock','claude','gemini') else 'unknown'
        row={'id':job['run_id'],'at':job['created_at'],'finished_at':job.get('finished_at',time.time()),'mode':job['mode'],'provider':provider,
             'status':status,'outcome':outcome,'simulated':result.get('simulated') is True,'live_invocations':calls,'prevented':prevented,
             'duration_ms':round(max(0,(job.get('finished_at',time.time())-job['created_at'])*1000),2),
             'tests_run':integer(checks.get('tests_run')),'tests_passed':checks.get('tests_passed') if type(checks.get('tests_passed')) is bool else None,
             'tokens':{k:integer(v) for k,v in usage.items() if k in ('input_tokens','output_tokens','cached_input_tokens') and type(v) is int and v>=0},
             'timeline':[{'event':e['event_type'],'step':integer(e.get('step_index'))} for e in events[:100] if isinstance(e,dict) and e.get('event_type') in EVENTS]}
        if not row['timeline']:row['timeline']=[{'event':'local_command_finished' if calls==0 else 'message_finished','step':0}]
        self.add(row);return row
    def config(self):
        p=safe_file(self.base,'langfuse.json')
        if not p.exists():return None
        if p.stat().st_size>8000:raise WorkerError('langfuse_invalid_config')
        c=json.loads(p.read_text(encoding='utf-8'));c['host']=local_host(c.get('host'));return c
    def settings(self):
        c=self.config();return {'configured':bool(c),'host':c['host'] if c else None,'export':'manual_metadata_only','docker_available':__import__('shutil').which('docker') is not None}
    def configure(self,host,public,secret):
        host=local_host(host)
        if any(not isinstance(v,str) or not 1<=len(v)<=500 or any(ord(x)<33 or ord(x)>126 for x in v) for v in (public,secret)):
            raise WorkerError('langfuse_keys_required')
        safe_file(self.base,'langfuse.json').write_text(json.dumps({'host':host,'public_key':public,'secret_key':secret}),encoding='utf-8')
        return self.settings()
    def payload(self,row):
        trace=row['id'];root=hashlib.sha256((trace+'root').encode()).hexdigest()[:16]
        def attr(k,v):
            if type(v) is bool:value={'boolValue':v}
            elif type(v) is int:value={'intValue':str(v)}
            else:value={'stringValue':str(v)}
            return {'key':k,'value':value}
        start=int(row['at']*1e9);end=max(start+101,int(row['finished_at']*1e9))
        values={'langfuse.trace.name':'Newton request','langfuse.observation.type':'agent','newton.outcome':row['outcome'],
                'newton.provider':row['provider'],'newton.live_invocations':row['live_invocations'],'newton.prevented':row['prevented'],
                'newton.simulated':row['simulated'],'newton.tests_run':row['tests_run']}
        values.update({'newton.tokens.'+k:v for k,v in row['tokens'].items()})
        spans=[{'traceId':trace,'spanId':root,'name':'Newton request','kind':1,'startTimeUnixNano':str(start),'endTimeUnixNano':str(end),
                'attributes':[attr(k,v) for k,v in values.items()],'status':{'code':2 if row['outcome']=='failed' else 1}}]
        if row['live_invocations']:
            usage={k.replace('_tokens',''):v for k,v in row['tokens'].items() if k in ('input_tokens','output_tokens')}
            attributes=[attr('langfuse.observation.type','generation'),attr('newton.timing','coarse_request_boundaries')]
            if usage:attributes.append(attr('langfuse.observation.usage_details',json.dumps(usage)))
            spans.append({'traceId':trace,'spanId':hashlib.sha256((trace+'worker').encode()).hexdigest()[:16],
                'parentSpanId':root,'name':'CLI worker invocation (request-level timing)','kind':1,'startTimeUnixNano':str(start),'endTimeUnixNano':str(end),
                'attributes':attributes})
        for i,event in enumerate(row['timeline']):
            spans.append({'traceId':trace,'spanId':hashlib.sha256((trace+str(i)).encode()).hexdigest()[:16],
                'parentSpanId':root,'name':event['event'],'kind':1,'startTimeUnixNano':str(start+i),'endTimeUnixNano':str(start+i+1),
                'attributes':[attr('langfuse.observation.type','event'),attr('newton.sequence',i+1),attr('newton.step',event['step'])]})
        return {'resourceSpans':[{'resource':{'attributes':[attr('service.name','newton-local')]},'scopeSpans':[{'scope':{'name':'newton.hub','version':'1'},'spans':spans}]}]}
    def export(self,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):raise WorkerError('hub_invalid_run')
        row=next((r for r in self.recent() if r['id']==identity),None)
        if row is None:raise WorkerError('hub_run_not_found')
        c=self.config()
        if not c:raise WorkerError('langfuse_setup_required')
        u=urlsplit(c['host']);conn=http.client.HTTPConnection('127.0.0.1',u.port,timeout=5)
        authorization=base64.b64encode((c['public_key']+':'+c['secret_key']).encode()).decode()
        try:
            conn.request('POST','/api/public/otel/v1/traces',json.dumps(self.payload(row)),
                {'Content-Type':'application/json','Authorization':'Basic '+authorization,'x-langfuse-ingestion-version':'4'})
            response=conn.getresponse();body=response.read(65537)
            if not 200<=response.status<300:raise WorkerError('langfuse_export_rejected')
            if len(body)>65536:raise WorkerError('langfuse_response_limit')
            data=json.loads(body) if body else {}
            if not isinstance(data,dict):raise ValueError
            partial=data.get('partialSuccess',{})
            if not isinstance(partial,dict):raise ValueError
            if int(partial.get('rejectedSpans',0)):raise WorkerError('langfuse_export_partially_rejected')
        except (OSError,ValueError,http.client.HTTPException):raise WorkerError('langfuse_unreachable_or_invalid_response') from None
        finally:conn.close()
        return {'status':'accepted_by_collector','trace_id':identity,'host':c['host'],'model_calls':0,'note':'Acceptance does not establish dashboard visibility; no automatic retries.'}
