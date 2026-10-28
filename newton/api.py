"""Newton's loopback-only prototype API. No model is started by launching the server."""
from argparse import ArgumentParser
import copy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from devtools.workers import WorkerError
from .conversation import ConversationSession
from .decisions import redact
from .profile import load_profile
from .providers import PROVIDERS, catalog, valid_model
from .teaching import STYLES
from .project_tools import ProjectTools
from .study import StudyService, ACTIONS
from .observability import Activity


class APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def fields(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise APIError(400, 'invalid_request_fields')


class NewtonAPI:
    def __init__(self, root, mode='mock', *, worker_factory=None):
        if mode not in ('mock', 'codex'):
            raise ValueError('invalid mode')
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('project_folder_not_found')
        self.mode = mode
        self.storage_name = 'newton_api_' + mode
        self.profile = replace(load_profile(self.root), worker=mode)
        self.worker_factory = worker_factory
        self.sessions, self.jobs, self.virtual_files = {}, {}, {}
        self.active_job = None
        self.lock = threading.RLock()
        self.closed = False
        self.activity = Activity(self.root,mode)

    def _idle(self):
        if self.closed:
            raise APIError(503, 'server_stopping')
        if self.active_job:
            raise APIError(409, 'task_already_running')

    def _entry(self, identity):
        if identity not in self.sessions:
            raise APIError(404, 'session_not_loaded')
        return self.sessions[identity]

    def create_session(self, data):
        fields(data, ('resume', 'confirm_new_budget'))
        resume = data.get('resume')
        if resume is not None and (not isinstance(resume, str) or not re.fullmatch(r'latest|[0-9a-f]{32}', resume)):
            raise APIError(400, 'invalid_session_id')
        with self.lock:
            self._idle()
            if len(self.sessions) >= 8:
                raise APIError(409, 'session_limit')
            if self.mode == 'codex' and resume is None and data.get('confirm_new_budget') is not True:
                raise APIError(409, 'confirm_new_session_budget')
            # Mock sessions are kept distinct from previous live CLI progress.
            if self.mode == 'mock' and resume is not None:
                raise APIError(400, 'mock_requires_new_session')
            identity = ConversationSession.latest_id(self.root, self.storage_name) if resume == 'latest' else resume
            if identity is None and self.mode == 'codex' and data.get('confirm_new_budget') is not True:
                raise APIError(409, 'confirm_new_session_budget')
            if identity in self.sessions:
                return self.session_info(identity)
            session = ConversationSession(self.root, self.profile, session_id=identity, worker_factory=self.worker_factory, storage_name=self.storage_name)
            identity = session.session_id
            self.sessions[identity] = {'session': session, 'live_approved': False, 'last_job': None}
            return self.session_info(identity)

    def session_info(self, identity):
        with self.lock:
            entry = self._entry(identity)
            session = entry['session']
            return {'session_id': identity, 'mode': self.mode, 'status': session.state['last_status'],
                    'provider': session.profile.worker, 'model': session.profile.model, 'response_style': session.profile.response_style,
                    'goal': session.state['goal'], 'plan': session.state['plan'], 'workspace': str(session.workspace()),
                    'budget': session.budget(), 'permissions': {'live_work': entry['live_approved'],
                    'personal_files': session.personal_files.approved, 'personal_root': str(session.personal_files.root)},
                    'active_job': self.active_job, 'last_job': entry['last_job'],
                    'last_result': session.state['last_result'], 'last_success': session.state['last_success']}

    def approve(self, identity, data):
        fields(data, ('kind', 'allow', 'command'))
        kind = data.get('kind')
        if kind not in ('live_work', 'personal_files', 'budget') or type(data.get('allow')) is not bool:
            raise APIError(400, 'invalid_approval')
        with self.lock:
            self._idle()
            entry = self._entry(identity)
            session = entry['session']
            if kind == 'live_work':
                entry['live_approved'] = data['allow'] and self.mode == 'codex'
            elif kind == 'personal_files':
                session.personal_files.revoke()
                session.pending_context = []
                session.personal_files.approved = data['allow']
            elif data['allow']:
                command = data.get('command', '')
                if not isinstance(command, str) or not re.fullmatch(r'(?:set|add) budget [0-9]{1,5}', command):
                    raise APIError(400, 'invalid_budget_command')
                result = session.respond(command, approve_budget=True)
                if result['status'] == 'invalid_budget':
                    raise APIError(400, 'invalid_budget')
            return self.session_info(identity)

    def preferences(self, identity, data):
        fields(data, ('provider', 'model', 'response_style', 'confirm_provider_change'))
        with self.lock:
            self._idle()
            entry = self._entry(identity)
            session = entry['session']
            provider = data.get('provider', session.profile.worker)
            model = data.get('model', session.profile.model if provider == session.profile.worker else '')
            style = data.get('response_style', session.profile.response_style)
            if not isinstance(provider, str) or provider not in (*PROVIDERS, 'mock') or not valid_model(model) or not isinstance(style, str) or style not in STYLES:
                raise APIError(400, 'invalid_preferences')
            changed = provider != session.profile.worker or model != session.profile.model
            if changed:
                if self.mode == 'mock' or provider == 'mock':
                    raise APIError(400, 'mock_cannot_switch_to_live')
                if data.get('confirm_provider_change') is not True:
                    raise APIError(409, 'confirm_provider_change')
                session.configure_provider(provider, model)
                entry['live_approved'] = False
            if style != session.profile.response_style:
                session.respond('style ' + style)
            return self.session_info(identity)

    def study(self, identity, data=None):
        with self.lock:
            self._idle()
            session = self._entry(identity)['session']
            service = StudyService(session)
            if data is None:return service.view()
            fields(data, ('action', 'args'))
            with session.locked():
                result=service.operation(data.get('action'), data.get('args', {}))
                job={'run_id':uuid.uuid4().hex,'created_at':time.time(),'mode':self.mode,'provider':session.profile.worker,
                     'result':{'status':'local'},'finished_at':time.time()}
                try:self.activity.record(job,session.budget(),session.budget(),[{'event_type':'local_command_finished'}])
                except (OSError,ValueError,WorkerError):result['observability_error']='local_activity_record_failed'
                return result

    def submit(self, identity, data):
        fields(data, ('message', 'read_only', 'study_action'))
        if data.get('study_action') is not None and data['study_action'] not in ACTIONS:
            raise APIError(400, 'invalid_study_action')
        message = data.get('message')
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
            raise APIError(400, 'invalid_message')
        if redact(message, 4000) != message:
            raise APIError(400, 'sensitive_input_rejected')
        if 'read_only' in data and type(data['read_only']) is not bool:
            raise APIError(400, 'invalid_read_only')
        with self.lock:
            self._idle()
            entry = self._entry(identity)
            if len(self.jobs) >= 100:
                oldest = next(iter(self.jobs))
                del self.jobs[oldest]
            job_id = uuid.uuid4().hex
            job = {'run_id': job_id, 'session_id': identity, 'mode': self.mode, 'status': 'queued',
                   'created_at': time.time(), 'result': None, 'error': None, 'events': [{'event': 'accepted'}],
                   'provider': entry['session'].profile.worker, 'budget_before': entry['session'].budget()}
            self.jobs[job_id] = job
            self.active_job = job_id
            entry['last_job'] = job_id
            thread = threading.Thread(target=self._run, args=(job_id, message, data.get('read_only', False), data.get('study_action')), daemon=False)
            job['thread'] = thread
            thread.start()
            return self.run_info(job_id)

    def _demo(self, identity):
        name = 'src/newton_demo.py'
        self.virtual_files[identity] = {name: 'def square(n):\n    """Demonstration content only; this file was not written."""\n    return n * n\n'}
        session = self._entry(identity)['session']
        return {'reply': 'Mock demonstration: file changes and three passing checks below are simulated. No model was called and no project files were written.',
                'status': 'mock_completed', 'simulated': True, 'changed_files': [name], 'file_paths': [],
                'verification': {'tests_run': 3, 'tests_passed': True, 'simulated': True},
                'acceptance_checks': [], 'budget': session.budget(), 'workspace': str(session.workspace())}

    def _run(self, job_id, message, read_only, study_action=None):
        with self.lock:
            job = self.jobs[job_id]
            entry = self._entry(job['session_id'])
            job['status'] = 'running'
            job['events'].append({'event': 'running'})
        try:
            local_control = message.strip().lower().rstrip('.!?')
            if local_control in ('enable files', 'new session', 'start a new session', '/new', 'resume latest', '/resume') or local_control.startswith('use project '):
                text = ('Use the Personal files switch to review and approve read access.' if local_control == 'enable files'
                        else 'Use New session to create browser progress. To select another project, restart the server with --project PATH. Terminal sessions are kept separate.')
                result = {'reply': text, 'status': 'local', 'budget': entry['session'].budget()}
            elif self.mode == 'mock' and local_control == 'demo':
                with self.lock:
                    result = self._demo(job['session_id'])
            else:
                result = entry['session'].respond(message, approve_live=entry['live_approved'], force_read_only=read_only, study_action=study_action)
            with self.lock:
                if result['status'] == 'exit':
                    entry['live_approved'] = False
                    entry['session'].personal_files.revoke()
                job['result'] = result
                job['status'] = 'completed'
                job['events'].append({'event': 'finished', 'result_status': result['status']})
        except (WorkerError, ValueError, OSError) as error:
            with self.lock:
                job['status'], job['error'] = 'failed', str(error).split(':', 1)[0][:100]
                job['events'].append({'event': 'failed', 'reason': job['error']})
        except Exception:
            with self.lock:
                job['status'], job['error'] = 'failed', 'internal_error'
        finally:
            with self.lock:
                job['finished_at'] = time.time()
                try:
                    events=self.trace(job_id)['events']
                    self.activity.record(job,job['budget_before'],entry['session'].budget(),events)
                except (WorkerError,OSError,ValueError,KeyError):
                    job['observability_error']='local_activity_record_failed'
                self.active_job = None

    def hub_state(self, selected=None):
        with self.lock:
            budget={'live_used':0,'live_limit':self.profile.max_live_invocations,'live_remaining':self.profile.max_live_invocations}
            provider=self.profile.worker
            if self.sessions:
                current=self.session_info(selected or next(iter(self.sessions)));budget=current['budget'];provider=current['provider']
            elif self.mode=='codex':
                identity=ConversationSession.latest_id(self.root,self.storage_name)
                if identity:
                    path=self.root/'runs'/self.storage_name/identity/'session.json'
                    if path.is_symlink() or not path.resolve().is_relative_to(self.root/'runs') or path.stat().st_size>100000:raise APIError(400,'invalid_saved_session')
                    saved=json.loads(path.read_text(encoding='utf-8'));used=saved.get('live_used',0);limit=saved.get('live_limit',self.profile.max_live_invocations)
                    if type(used) is not int or type(limit) is not int or used<0 or not 1<=limit<=1000:raise APIError(400,'invalid_saved_budget')
                    budget={'live_used':used,'live_limit':limit,'live_remaining':max(0,limit-used)}
                    if saved.get('provider') in PROVIDERS:provider=saved['provider']
            rows=self.activity.recent()
            return {'budget':budget,'provider':provider,'active_job':self.active_job,'records':rows[-100:][::-1],
                    'summary':{'scope':'last 500 recorded actions','actions':len(rows),'live_invocations':sum(r['live_invocations'] for r in rows),
                    'prevented':sum(r['prevented'] for r in rows),'failed':sum(r['outcome']=='failed' for r in rows)},
                    'langfuse':self.activity.settings()}

    def hub_action(self,data):
        fields(data,('action','confirm','live_used','live_limit','host','public_key','secret_key','id','session_id'))
        with self.lock:
            self._idle()
            action=data.get('action')
            if action in ('start','open_local'):
                if action=='start' and self.mode=='codex' and data.get('confirm') is not True:raise APIError(409,'confirm_live_launch')
                selected=data.get('session_id')
                if selected is not None:self._entry(selected)
                current=self.hub_state(selected)
                if action=='start' and self.mode=='codex' and (data.get('live_used'),data.get('live_limit'))!=(current['budget']['live_used'],current['budget']['live_limit']):raise APIError(409,'budget_changed_refresh_first')
                if self.sessions:identity=selected or next(iter(self.sessions))
                else:
                    identity=self.create_session({'resume':'latest','confirm_new_budget':True} if self.mode=='codex' else {})['session_id']
                if action=='start' and self.mode=='codex':self.approve(identity,{'kind':'live_work','allow':True})
                return self.session_info(identity)
            if action=='configure_langfuse':
                if data.get('confirm') is not True:raise APIError(409,'confirm_local_export_configuration')
                return self.activity.configure(data.get('host'),data.get('public_key'),data.get('secret_key'))
            if action=='export':
                if data.get('confirm') is not True:raise APIError(409,'confirm_metadata_export')
                return self.activity.export(data.get('id'))
            if action=='disconnect_langfuse':
                from .observability import safe_file
                safe_file(self.activity.base,'langfuse.json').unlink(missing_ok=True)
                return self.activity.settings()
            raise APIError(400,'invalid_hub_action')

    def run_info(self, identity):
        with self.lock:
            if identity not in self.jobs:
                raise APIError(404, 'run_not_found')
            return copy.deepcopy({k: v for k, v in self.jobs[identity].items() if k != 'thread'})

    def file(self, identity, name):
        with self.lock:
            self._idle()
            entry = self._entry(identity)
            if name in self.virtual_files.get(identity, {}):
                return {'path': name, 'text': self.virtual_files[identity][name], 'simulated': True, 'truncated': False}
            # No arbitrary absolute paths, personal-file serving, or shell/open commands.
            return ProjectTools(entry['session'].workspace()).read(name, 1, 200)

    def trace(self, identity):
        job = self.run_info(identity)
        result = job['result'] or {}
        report_name = result.get('report_file')
        if not report_name:
            return {'events': job['events'], 'simulated': bool(result.get('simulated'))}
        entry = self._entry(job['session_id'])
        report = Path(report_name).resolve()
        folder = entry['session'].folder.resolve()
        if not report.is_relative_to(folder) or report.stat().st_size > 100000:
            raise APIError(400, 'invalid_report')
        data = json.loads(report.read_text(encoding='utf-8'))
        trace = Path(data['trace_file']).resolve()
        if not trace.is_relative_to(folder) or trace.stat().st_size > 500000:
            raise APIError(400, 'invalid_trace')
        events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        return {'events': events, 'simulated': False}

    def close(self):
        with self.lock:
            self.closed = True
            threads = [job['thread'] for job in self.jobs.values() if 'thread' in job]
        for thread in threads:
            thread.join()
        for entry in self.sessions.values():
            entry['session'].personal_files.revoke()
            entry['live_approved'] = False


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, application, port=0, token=None):
        self.application = application
        self.token = token or secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_address[1])


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args):
        pass  # Do not log chat content, tokens, filenames or query strings.

    def reply(self, status, data, mime='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8') if mime.startswith('application/json') else data
        self.send_response(status)
        for key, value in {'Content-Type': mime, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
                           'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
                           'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'"}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def discard_small_body(self):
        # Drain bounded rejected bodies before closing: unread data can cause a TCP
        # reset on Windows and hide the intended JSON error from the client.
        remaining = getattr(self, 'remaining_body', 0)
        if 0 < remaining <= 65536:
            try:
                self.rfile.read(remaining)
            except OSError:
                pass
        self.remaining_body = 0

    def handle_request(self):
        self.connection.settimeout(5)
        length_header = self.headers.get('Content-Length', '')
        self.remaining_body = int(length_header) if length_header.isdigit() and len(length_header) < 10 else 0
        try:
            host = self.headers.get('Host', '')
            if host != self.server.origin.removeprefix('http://'):
                raise APIError(403, 'invalid_host')
            if self.headers.get('Origin') not in (None, self.server.origin):
                raise APIError(403, 'cross_origin_denied')
            path = urlsplit(self.path)
            if self.command == 'GET' and path.path == '/favicon.ico':
                return self.reply(204, b'', 'image/x-icon')
            if self.command == 'GET' and path.path in ('/', '/app.js', '/style.css', '/study.js', '/study.css', '/study-math.js', '/hub.js', '/hub.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/study.js': 'study.js', '/study.css': 'study.css', '/study-math.js': 'study-math.js', '/hub.js':'hub.js', '/hub.css':'hub.css'}[path.path]
                mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8', 'study.js': 'text/javascript; charset=utf-8', 'study.css': 'text/css; charset=utf-8', 'study-math.js': 'text/javascript; charset=utf-8', 'hub.js':'text/javascript; charset=utf-8','hub.css':'text/css; charset=utf-8'}[name]
                return self.reply(200, (Path(__file__).with_name('web') / name).read_bytes(), mime)
            authorization = self.headers.get('Authorization', '')
            if not hmac.compare_digest(authorization, 'Bearer ' + self.server.token):
                raise APIError(401, 'local_token_required')
            parts = path.path.strip('/').split('/')
            data = None
            if self.command == 'POST':
                if self.headers.get_content_type() != 'application/json':
                    raise APIError(415, 'json_required')
                length = self.headers.get('Content-Length', '')
                if not length.isdigit() or not 0 < int(length) <= 32000:
                    raise APIError(413, 'body_size_limit')
                raw = self.rfile.read(int(length))
                self.remaining_body = 0
                if len(raw) != int(length):
                    raise APIError(400, 'incomplete_body')
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise APIError(400, 'invalid_json') from None
            app = self.server.application
            if self.command == 'GET' and parts == ['api', 'info']:
                return self.reply(200, {'api_version': 1, 'mode': app.mode, 'project_root': str(app.root),
                    'sessions': list(app.sessions), 'active_job': app.active_job, 'providers': catalog(), 'response_styles': list(STYLES),
                    'limits': {'one_task_at_a_time': True, 'default_session_budget': app.profile.max_live_invocations,
                               'automatic_retries': 0, 'hard_token_cap': False}})
            if self.command == 'GET' and parts == ['api','hub']:
                return self.reply(200,app.hub_state(parse_qs(path.query).get('session_id',[None])[0]))
            if self.command == 'POST' and parts == ['api','hub']:
                return self.reply(200,app.hub_action(data))
            if self.command == 'POST' and parts == ['api','hub','stop']:
                fields(data,('confirm',))
                with app.lock:
                    app._idle()
                    if data.get('confirm') is not True:raise APIError(409,'confirm_stop')
                    for entry in app.sessions.values():
                        entry['live_approved']=False;entry['session'].personal_files.revoke()
                    self.reply(200,{'status':'stopping'})
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                    return
            if self.command == 'POST' and parts == ['api', 'sessions']:
                return self.reply(201, app.create_session(data))
            if len(parts) >= 3 and parts[:2] == ['api', 'sessions']:
                identity = parts[2]
                if self.command == 'GET' and len(parts) == 3:
                    return self.reply(200, app.session_info(identity))
                if parts[3:] == ['study'] and self.command in ('GET', 'POST'):
                    return self.reply(200, app.study(identity, data if self.command == 'POST' else None))
                if self.command == 'POST' and parts[3:] == ['messages']:
                    return self.reply(202, app.submit(identity, data))
                if self.command == 'POST' and parts[3:] == ['preferences']:
                    return self.reply(200, app.preferences(identity, data))
                if self.command == 'POST' and parts[3:] == ['approvals']:
                    return self.reply(200, app.approve(identity, data))
                if self.command == 'GET' and parts[3:] == ['files']:
                    name = parse_qs(path.query).get('path', [''])[0]
                    return self.reply(200, app.file(identity, name))
            if self.command == 'GET' and len(parts) >= 3 and parts[:2] == ['api', 'runs']:
                if len(parts) == 3:
                    return self.reply(200, app.run_info(parts[2]))
                if parts[3:] == ['trace']:
                    return self.reply(200, app.trace(parts[2]))
            raise APIError(404, 'route_not_found')
        except APIError as error:
            self.discard_small_body()
            self.reply(error.status, {'error': error.code})
        except WorkerError as error:
            self.discard_small_body()
            code = str(error).split(':', 1)[0]
            self.reply(400, {'error': code if re.fullmatch(r'[a-z_]{1,80}', code) else 'operation_rejected'})
        except (ValueError, OSError, TypeError):
            self.discard_small_body()
            self.reply(400, {'error': 'operation_rejected'})
        except Exception:
            self.reply(500, {'error': 'internal_error'})

    do_GET = handle_request
    do_POST = handle_request
    do_OPTIONS = handle_request


def main():
    parser = ArgumentParser(description='Newton local app and API (mock by default)')
    parser.add_argument('--mode', choices=('mock', 'codex'), default='mock')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--project', type=Path, default=PROJECT)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('port must be between 0 and 65535')
    application = NewtonAPI(args.project, args.mode)
    server = LocalServer(application, args.port)
    print('Newton local app | ' + args.mode, flush=True)
    print('Open this private local link in your browser:', flush=True)
    print(server.origin + '/#token=' + server.token, flush=True)
    print('No worker has started. Mock mode uses no model calls. Press Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.close()


if __name__ == '__main__':
    main()
