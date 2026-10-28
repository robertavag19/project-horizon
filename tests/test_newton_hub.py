"""Offline hub, launch safety and actual HTTP export-contract tests."""
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
import uuid
from devtools.workers import WorkerError
from newton.api import NewtonAPI, APIError
from newton.hub import existing_link
from newton.observability import Activity, local_host
from test_conversation import FakeWorker, decision
import test_devtools as fixtures

class HubTests(unittest.TestCase):
    def make(self,folder):
        root=fixtures.CoordinatorTests().make_repo(folder);worker=FakeWorker(decision());app=NewtonAPI(root,'codex',worker_factory=lambda:worker);self.addCleanup(app.close);return root,worker,app
    def wait(self,app,run):
        app.jobs[run['run_id']]['thread'].join(15);return app.run_info(run['run_id'])
    def test_open_local_does_not_grant_live_approval_or_invoke_worker(self):
        with TemporaryDirectory() as folder:
            root,w,app=self.make(folder)
            session=app.hub_action({'action':'open_local'})
            self.assertFalse(session['permissions']['live_work']);self.assertFalse(session['permissions']['personal_files'])
            self.assertEqual(w.calls,0);self.assertEqual(app.hub_state()['budget']['live_used'],0)
    def test_launch_approval_resume_usage_and_restart_fresh_approval(self):
        with TemporaryDirectory() as folder:
            root,w,app=self.make(folder)
            with self.assertRaises(APIError):app.hub_action({'action':'start'})
            session=app.hub_action({'action':'start','confirm':True,'live_used':0,'live_limit':50})
            self.assertEqual(w.calls,0)
            self.wait(app,app.submit(session['session_id'],{'message':'Explain a vector'}));self.assertEqual(w.calls,1)
            second=NewtonAPI(root,'codex',worker_factory=lambda:w);self.addCleanup(second.close)
            self.assertEqual(second.hub_state()['budget']['live_used'],1)
            resumed=second.hub_action({'action':'open_local'});self.assertFalse(resumed['permissions']['live_work'])
            with self.assertRaisesRegex(APIError,''):
                second.hub_action({'action':'start','confirm':True,'live_used':0,'live_limit':50})
            approved=second.hub_action({'action':'start','confirm':True,'live_used':1,'live_limit':50})
            self.assertTrue(approved['permissions']['live_work']);self.assertEqual(w.calls,1)
    def test_prevented_calls_and_failures_are_observable_and_private(self):
        with TemporaryDirectory() as folder:
            root,w,app=self.make(folder);s=app.hub_action({'action':'open_local'})
            run=self.wait(app,app.submit(s['session_id'],{'message':'Explain my private book phrase'}))
            r=app.hub_state()['records'][0]
            self.assertEqual(r['outcome'],'prevented');self.assertEqual(r['live_invocations'],0);self.assertEqual(r['prevented'],1)
            self.assertNotIn('private book',json.dumps(r));self.assertNotIn(str(root),json.dumps(r))
            app.approve(s['session_id'],{'kind':'live_work','allow':True});w.value=WorkerError('process_timeout')
            self.wait(app,app.submit(s['session_id'],{'message':'Explain a vector'}))
            self.assertEqual(app.hub_state()['records'][0]['outcome'],'failed');self.assertEqual(w.calls,1)
            self.assertEqual(Activity(root).recent()[0]['prevented'],1)
    def test_start_uses_selected_session_instead_of_an_older_one(self):
        with TemporaryDirectory() as folder:
            root,w,app=self.make(folder)
            first=app.hub_action({'action':'open_local'})
            second=app.create_session({'confirm_new_budget':True})
            selected=app.hub_action({'action':'start','session_id':second['session_id'],'confirm':True,'live_used':0,'live_limit':50})
            self.assertEqual(selected['session_id'],second['session_id'])
            self.assertFalse(app.session_info(first['session_id'])['permissions']['live_work'])
            self.assertEqual(w.calls,0)
    def test_busy_and_export_confirmation_controls(self):
        with TemporaryDirectory() as folder:
            root,w,app=self.make(folder);app.active_job='busy'
            with self.assertRaises(APIError):app.hub_action({'action':'open_local'})
            app.active_job=None
            with self.assertRaises(APIError):app.hub_action({'action':'export','id':'a'*32})
            with self.assertRaises(APIError):app.hub_action({'action':'configure_langfuse','host':'http://127.0.0.1:3000'})
            self.assertEqual(w.calls,0)
    def test_local_study_actions_record_no_worker_calls(self):
        with TemporaryDirectory() as folder:
            root,w,app=self.make(folder);s=app.hub_action({'action':'open_local'})
            app.study(s['session_id'],{'action':'create','args':{'profile':{'nickname':'Private Name'}}})
            rows=app.hub_state()['records'];self.assertEqual(rows[0]['live_invocations'],0)
            self.assertNotIn('Private Name',json.dumps(rows));self.assertEqual(w.calls,0)
    def test_http_hub_authentication_and_static_assets(self):
        from test_newton_api import HTTPTests
        h=HTTPTests();h.setUp()
        try:
            self.assertEqual(h.request('GET','/api/hub',authenticate=False)[0],401)
            self.assertEqual(h.request('GET','/api/hub')[0],200)
            self.assertEqual(h.request('POST','/api/hub',{'action':'open_local'},headers={'Origin':'https://evil.invalid'})[0],403)
            for p in ('/hub.js','/hub.css'):self.assertEqual(h.request('GET',p,authenticate=False)[0],200)
        finally:h.tearDown()

class ExportTests(unittest.TestCase):
    def row(self,store):
        job={'run_id':uuid.uuid4().hex,'created_at':1000,'finished_at':1001,'mode':'codex','provider':'codex',
             'result':{'status':'answered','reply':'PRIVATE ANSWER','usage':{'input_tokens':10,'output_tokens':5,'prompt':'PRIVATE'}}}
        return store.record(job,{'live_used':0},{'live_used':1},[{'event_type':'message_finished','metadata':{'prompt':'PRIVATE'}}])
    def test_endpoint_restriction_and_keys_not_exposed(self):
        for url in ('https://cloud.langfuse.com','http://example.com:3000','http://127.0.0.1:3000@evil.invalid:80','http://127.0.0.1:3000/path','http://127.0.0.1:3000?x=secret','http://[::ffff:8.8.8.8]:3000'):
            with self.assertRaises(WorkerError):local_host(url)
        self.assertEqual(local_host('http://localhost:3000'),'http://127.0.0.1:3000')
        with TemporaryDirectory() as folder:
            store=Activity(folder);store.configure('http://127.0.0.1:3000','public','secret')
            self.assertNotIn('secret',json.dumps(store.settings()))
    def test_otlp_parent_ids_usage_and_privacy(self):
        with TemporaryDirectory() as folder:
            store=Activity(folder);row=self.row(store);payload=store.payload(row);text=json.dumps(payload)
            self.assertNotIn('PRIVATE',text);spans=payload['resourceSpans'][0]['scopeSpans'][0]['spans']
            self.assertTrue(all(s['traceId']==row['id'] for s in spans));self.assertTrue(all(s['parentSpanId']==spans[0]['spanId'] for s in spans[1:]))
            self.assertIn('langfuse.observation.usage_details',text)
            self.assertNotIn('cost_details',text)
    def test_actual_http_export_headers_json_and_partial_failure(self):
        received=[];response={'body':{},'code':200}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                received.append((self.path,dict(self.headers),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(response['code']);self.end_headers();self.wfile.write(json.dumps(response['body']).encode())
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with TemporaryDirectory() as folder:
                store=Activity(folder);row=self.row(store);store.configure('http://127.0.0.1:'+str(server.server_port),'pub','sec')
                result=store.export(row['id']);self.assertEqual(result['status'],'accepted_by_collector')
                self.assertEqual(received[0][0],'/api/public/otel/v1/traces');self.assertEqual(received[0][1]['x-langfuse-ingestion-version'],'4')
                self.assertEqual(received[0][1]['Authorization'],'Basic '+base64.b64encode(b'pub:sec').decode())
                response['body']={'partialSuccess':{'rejectedSpans':'1'}}
                with self.assertRaisesRegex(WorkerError,'partially_rejected'):store.export(row['id'])
                self.assertEqual(len(received),2)
                response['code']=302
                with self.assertRaisesRegex(WorkerError,'export_rejected'):store.export(row['id'])
                self.assertEqual(len(received),3) # No redirect or retry.
        finally:server.shutdown();server.server_close();thread.join()
    def test_missing_config_and_unavailable_service_preserve_activity(self):
        with TemporaryDirectory() as folder:
            store=Activity(folder);row=self.row(store);before=store.recent()
            with self.assertRaisesRegex(WorkerError,'setup_required'):store.export(row['id'])
            store.configure('http://127.0.0.1:9','pub','sec')
            with self.assertRaises(WorkerError):store.export(row['id'])
            self.assertEqual(before,store.recent())
    def test_modes_isolated_and_retention_bounded(self):
        with TemporaryDirectory() as folder:
            a=Activity(folder);b=Activity(folder,'mock');self.row(a);self.assertEqual(b.recent(),[])
            original=a.recent()[0]
            rows=[{**original,'id':format(i,'032x')} for i in range(500)]
            (a.base/a.journal).write_text(json.dumps(rows),encoding='utf-8')
            added=self.row(a)
            self.assertEqual(len(a.recent()),500)
            self.assertEqual(a.recent()[0]['id'],format(1,'032x'))
            self.assertEqual(a.recent()[-1]['id'],added['id'])
    def test_discovery_never_opens_external_or_wrong_project_link(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'manifest.json';p.write_text(json.dumps({'project':folder,'mode':'codex','pid':123,'origin':'https://evil.invalid','token':'secret'*6}))
            with patch('newton.hub.process_exists',return_value=True):
                with patch('newton.hub.http.client.HTTPConnection') as connection:
                    self.assertIsNone(existing_link(p,folder,'codex'));connection.assert_not_called()
