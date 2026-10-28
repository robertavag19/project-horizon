"""Offline API integration tests using temporary projects and simulated workers."""
import contextlib
import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from newton.api import APIError, LocalServer, NewtonAPI
from newton.conversation import ConversationSession
from newton.profile import Profile
from test_conversation import FakeWorker, decision
import test_devtools as fixtures


class APITests(unittest.TestCase):
    def make_app(self, folder, mode='mock', worker=None):
        root = fixtures.CoordinatorTests().make_repo(folder)
        app = NewtonAPI(root, mode, worker_factory=(lambda: worker) if worker else None)
        self.addCleanup(app.close)
        return root, app

    def wait(self, app, run):
        app.jobs[run['run_id']]['thread'].join(10)
        result = app.run_info(run['run_id'])
        self.assertNotIn(result['status'], ('queued', 'running'))
        return result

    def test_mock_demo_has_files_checks_and_trace_but_no_model_or_source_edits(self):
        with TemporaryDirectory() as folder:
            root, app = self.make_app(folder)
            cli_session = ConversationSession(root, Profile())
            original_latest = (root / 'runs/newton/latest.json').read_bytes()
            with patch('newton.conversation.ConversationWorker') as worker:
                session = app.create_session({})
                run = self.wait(app, app.submit(session['session_id'], {'message': 'demo'}))
            worker.assert_not_called()
            self.assertEqual((root / 'runs/newton/latest.json').read_bytes(), original_latest)
            self.assertFalse((root / 'src/newton_demo.py').exists())
            self.assertTrue(run['result']['simulated'])
            self.assertTrue(run['result']['verification']['simulated'])
            self.assertEqual(session['budget']['live_used'], 0)
            self.assertTrue(app.file(session['session_id'], 'src/newton_demo.py')['simulated'])
            self.assertTrue(app.trace(run['run_id'])['simulated'])
            self.assertIsNone(app.active_job)

    def test_live_requires_explicit_session_budget_and_live_approval(self):
        with TemporaryDirectory() as folder:
            worker = FakeWorker(decision())
            root, app = self.make_app(folder, 'codex', worker)
            with self.assertRaises(APIError) as caught:
                app.create_session({})
            self.assertEqual(caught.exception.code, 'confirm_new_session_budget')
            session = app.create_session({'confirm_new_budget': True})
            identity = session['session_id']
            run = self.wait(app, app.submit(identity, {'message': 'Explain the project'}))
            self.assertEqual(run['result']['status'], 'approval_required')
            self.assertEqual(worker.calls, 0)
            app.approve(identity, {'kind': 'live_work', 'allow': True})
            run = self.wait(app, app.submit(identity, {'message': 'Explain the project'}))
            self.assertEqual(run['result']['status'], 'answered')
            self.assertEqual(worker.calls, 1)
            self.assertEqual(app.session_info(identity)['budget']['live_used'], 1)
            app.approve(identity, {'kind': 'live_work', 'allow': False})
            run = self.wait(app, app.submit(identity, {'message': 'Explain more'}))
            self.assertEqual(run['result']['status'], 'approval_required')
            self.assertEqual(worker.calls, 1)

    def test_files_and_live_approvals_are_independent_and_expire_on_restart(self):
        with TemporaryDirectory() as folder:
            root, app = self.make_app(folder, 'codex', FakeWorker(decision()))
            session = app.create_session({'confirm_new_budget': True})
            identity = session['session_id']
            app.approve(identity, {'kind': 'personal_files', 'allow': True})
            info = app.session_info(identity)
            self.assertTrue(info['permissions']['personal_files'])
            self.assertFalse(info['permissions']['live_work'])
            app.approve(identity, {'kind': 'live_work', 'allow': True})
            app.close()
            second = NewtonAPI(root, 'codex'); self.addCleanup(second.close)
            restored = second.create_session({'resume': identity})
            self.assertFalse(restored['permissions']['personal_files'])
            self.assertFalse(restored['permissions']['live_work'])
            self.assertEqual(restored['budget']['live_used'], 0)

    def test_budget_approval_is_explicit_and_local(self):
        with TemporaryDirectory() as folder:
            worker = FakeWorker(decision())
            root, app = self.make_app(folder, 'codex', worker)
            identity = app.create_session({'confirm_new_budget': True})['session_id']
            app.approve(identity, {'kind': 'budget', 'allow': False, 'command': 'add budget 10'})
            self.assertEqual(app.session_info(identity)['budget']['live_limit'], 50)
            app.approve(identity, {'kind': 'budget', 'allow': True, 'command': 'add budget 10'})
            self.assertEqual(app.session_info(identity)['budget']['live_limit'], 60)
            self.assertEqual(worker.calls, 0)
            with self.assertRaises(APIError):
                app.approve(identity, {'kind': 'budget', 'allow': True, 'command': 'run a shell command'})

    def test_real_controller_edits_and_file_previews_stay_in_worktree(self):
        with TemporaryDirectory() as folder:
            worker = FakeWorker(decision('implement', file_edits=[{'path': 'src/value.py', 'content': 'VALUE = 2\n'}]))
            root, app = self.make_app(folder, 'codex', worker)
            identity = app.create_session({'confirm_new_budget': True})['session_id']
            app.approve(identity, {'kind': 'live_work', 'allow': True})
            run = self.wait(app, app.submit(identity, {'message': 'Fix src/value.py so VALUE is 2'}))
            self.assertEqual(run['result']['status'], 'changes_tested_review_required')
            self.assertTrue(run['result']['verification']['tests_passed'])
            self.assertEqual((root / 'src/value.py').read_text(), 'VALUE = 1\n')
            self.assertIn('VALUE = 2', app.file(identity, 'src/value.py')['text'])
            self.assertFalse(app.trace(run['run_id'])['simulated'])
            self.assertEqual(worker.calls, 1)
            for path in ('../outside.txt', str(root / '.env'), '.env'):
                with self.subTest(path=path), self.assertRaises(Exception):
                    app.file(identity, path)

    def test_all_tasks_serialize_and_progress_reads_never_launch_more_workers(self):
        entered, release = threading.Event(), threading.Event()
        class Slow(FakeWorker):
            def decide(self, prompt, root):
                entered.set()
                release.wait(8)
                return super().decide(prompt, root)
        with TemporaryDirectory() as folder:
            worker = Slow(decision())
            root, app = self.make_app(folder, 'codex', worker)
            first = app.create_session({'confirm_new_budget': True})['session_id']
            second = app.create_session({'confirm_new_budget': True})['session_id']
            app.approve(first, {'kind': 'live_work', 'allow': True})
            run = app.submit(first, {'message': 'Explain code'})
            try:
                self.assertTrue(entered.wait(3))
                for _ in range(4):
                    self.assertEqual(app.run_info(run['run_id'])['status'], 'running')
                with self.assertRaises(APIError) as caught:
                    app.submit(second, {'message': 'Explain more'})
                self.assertEqual(caught.exception.status, 409)
                with self.assertRaises(APIError):
                    app.approve(first, {'kind': 'personal_files', 'allow': True})
            finally:
                release.set()
            self.wait(app, run)
            self.assertEqual(worker.calls, 1)

    def test_unknown_fields_cannot_change_mode_or_bypass_approval(self):
        with TemporaryDirectory() as folder:
            root, app = self.make_app(folder)
            with self.assertRaises(APIError):
                app.create_session({'mode': 'codex'})
            identity = app.create_session({})['session_id']
            with self.assertRaises(APIError):
                app.submit(identity, {'message': 'hi', 'approve_live': True})
            with self.assertRaises(APIError):
                app.approve(identity, {'kind': 'personal_files', 'allow': 'true'})
            self.assertFalse(app.session_info(identity)['permissions']['personal_files'])

    def test_failed_worker_is_not_retried_and_current_result_has_no_old_tests(self):
        from devtools.workers import WorkerError
        with TemporaryDirectory() as folder:
            worker = FakeWorker(WorkerError('process_timeout'))
            root, app = self.make_app(folder, 'codex', worker)
            identity = app.create_session({'confirm_new_budget': True})['session_id']
            app.approve(identity, {'kind': 'live_work', 'allow': True})
            run = self.wait(app, app.submit(identity, {'message': 'Explain'}))
            self.assertEqual(run['result']['status'], 'process_timeout')
            self.assertIsNone(run['result']['verification'])
            self.assertEqual(worker.calls, 1)
            self.assertEqual(app.session_info(identity)['budget']['live_used'], 1)

    def test_ui_controls_and_quit_never_accidentally_invoke_a_model(self):
        with TemporaryDirectory() as folder:
            worker = FakeWorker(decision())
            root, app = self.make_app(folder, 'codex', worker)
            identity = app.create_session({'confirm_new_budget': True})['session_id']
            app.approve(identity, {'kind': 'live_work', 'allow': True})
            for message in ('enable files', 'use project another', 'new session', 'resume latest'):
                run = self.wait(app, app.submit(identity, {'message': message}))
                self.assertEqual(run['result']['status'], 'local')
            self.wait(app, app.submit(identity, {'message': 'quit'}))
            self.assertFalse(app.session_info(identity)['permissions']['live_work'])
            self.assertFalse(app.session_info(identity)['permissions']['personal_files'])
            self.assertEqual(worker.calls, 0)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        root = fixtures.CoordinatorTests().make_repo(self.folder.name)
        self.app = NewtonAPI(root)
        self.server = LocalServer(self.app, token='test-local-token')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3)
        self.app.close(); self.folder.cleanup()

    def request(self, method, path, data=None, headers=None, authenticate=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        values = {'Authorization': 'Bearer test-local-token'} if authenticate else {}
        if data is not None:
            values['Content-Type'] = 'application/json'
        values.update(headers or {})
        conn.request(method, path, None if data is None else json.dumps(data), values)
        response = conn.getresponse(); body = response.read(); status = response.status
        received_headers = dict(response.getheaders()); conn.close()
        return status, body, received_headers

    def test_loopback_authentication_and_same_origin_only(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        self.assertEqual(self.request('GET', '/api/info', authenticate=False)[0], 401)
        self.assertEqual(self.request('GET', '/api/info')[0], 200)
        self.assertEqual(self.request('GET', '/api/info', headers={'Origin': 'https://example.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/api/info', headers={'Host': 'attacker.invalid'})[0], 403)
        self.assertEqual(self.request('OPTIONS', '/api/info', headers={'Origin': 'https://example.invalid'})[0], 403)

    def test_browser_assets_have_no_embedded_token_and_no_arbitrary_file_route(self):
        for path in ('/', '/app.js', '/style.css'):
            status, body, headers = self.request('GET', path, authenticate=False)
            self.assertEqual(status, 200)
            self.assertNotIn(b'test-local-token', body)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('GET', '/../../.env')[0], 404)

    def test_http_chat_job_results_trace_and_file_contract(self):
        status, body, _ = self.request('POST', '/api/sessions', {})
        self.assertEqual(status, 201)
        identity = json.loads(body)['session_id']
        status, body, _ = self.request('POST', f'/api/sessions/{identity}/messages', {'message': 'demo'})
        self.assertEqual(status, 202)
        run_id = json.loads(body)['run_id']
        self.app.jobs[run_id]['thread'].join(5)
        status, body, _ = self.request('GET', '/api/runs/' + run_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'completed')
        self.assertTrue(json.loads(body)['result']['simulated'])
        self.assertEqual(self.request('GET', '/api/runs/' + run_id + '/trace')[0], 200)
        self.assertEqual(self.request('GET', f'/api/sessions/{identity}/files?path=src%2Fnewton_demo.py')[0], 200)
        self.assertEqual(self.request('GET', f'/api/sessions/{identity}/files?path=..%2F.env')[0], 400)
        self.assertEqual(self.request('GET', f'/api/sessions/{identity}')[0], 200)

    def test_invalid_types_and_body_limits(self):
        self.assertEqual(self.request('POST', '/api/sessions', [1])[0], 400)
        self.assertEqual(self.request('POST', '/api/sessions', {'resume': '../outside'})[0], 400)
        self.assertEqual(self.request('POST', '/api/sessions', {'value': 'x' * 33000})[0], 413)
        self.assertEqual(self.request('POST', '/api/sessions', {}, headers={'Content-Type': 'text/plain'})[0], 415)
