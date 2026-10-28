"""Offline tests: teaching, prevented calls, provider boundaries and app approvals."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devtools.workers import WorkerError
from newton.api import APIError, NewtonAPI
from newton.conversation import ConversationSession
from newton.profile import Profile
from newton.providers import AccountWorker, account_environment, valid_model
from test_conversation import FakeWorker, decision
import test_devtools as fixtures


class TeachingTests(unittest.TestCase):
    def setup(self, folder, value=None):
        root = fixtures.CoordinatorTests().make_repo(folder)
        worker = FakeWorker(value or decision())
        session = ConversationSession(root, Profile(), worker_factory=lambda: worker)
        return root, worker, session

    def test_style_is_local_persisted_and_added_to_the_single_worker_prompt(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.assertEqual(session.profile.response_style, 'teacher')
            session.respond('style supervisor')
            self.assertEqual(worker.calls, 0)
            restored = ConversationSession(root, Profile(), session_id=session.session_id, worker_factory=lambda: worker)
            restored.respond('Explain centripetal acceleration', approve_live=True)
            prompt = worker.prompts[0]
            self.assertIn('Response style: supervisor', prompt)
            self.assertIn('Never invent citations', prompt)
            self.assertIn('units, and domain restrictions', prompt)
            self.assertIn('Follow the current user goal', prompt)
            self.assertEqual(restored.budget()['live_used'], 1)

    def test_dirty_new_workspace_prevents_call_and_preserves_earlier_success(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            prior = {'status': 'changes_tested_review_required', 'changed_files': ['src/previous.py']}
            session.state['last_success'] = prior
            (root / 'src/value.py').write_text('VALUE = 2\n')
            result = session.respond('Create src/example.py', approve_live=True)
            self.assertEqual(result['status'], 'commit_changes_before_implementation')
            self.assertEqual(worker.calls, 0)
            self.assertEqual(result['budget']['live_used'], 0)
            self.assertEqual(result['budget']['prevented_invocations'], 1)
            self.assertEqual(session.state['last_success'], prior)
            report = json.loads(Path(result['report_file']).read_text())
            self.assertEqual(report['worker_invocations'], 0)
            self.assertIsNone(report['verification'])
            trace = Path(report['trace_file']).read_text()
            self.assertIn('invocation_prevented', trace)
            self.assertNotIn('Create src/example.py', trace)
            # Discussion remains usable with uncommitted project changes.
            session.respond('Explain acceleration', approve_live=True)
            self.assertEqual(worker.calls, 1)

    def test_missing_auth_or_cli_prevents_call_before_budget_reservation(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            with patch.object(worker, 'preflight', side_effect=WorkerError('claude_subscription_login_required')):
                result = session.respond('Explain acceleration', approve_live=True)
            self.assertEqual(result['status'], 'claude_subscription_login_required')
            self.assertEqual(worker.calls, 0)
            self.assertEqual(session.budget()['live_used'], 0)
            self.assertEqual(session.budget()['prevented_invocations'], 1)
            self.assertIn('No worker started', result['reply'])

    def test_protected_test_edit_is_stopped_before_worker(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            result = session.respond('Update tests/test_value.py', approve_live=True)
            self.assertEqual(result['status'], 'protected_test_file')
            self.assertEqual(worker.calls, 0)

    def test_exhaustion_and_missing_approval_are_recorded_without_spending(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.assertEqual(session.respond('Explain gravity')['status'], 'approval_required')
            session.state['live_used'] = 50
            self.assertEqual(session.respond('Explain gravity', approve_live=True)['status'], 'budget_exhausted')
            self.assertEqual(session.budget()['prevented_invocations'], 2)
            self.assertEqual(worker.calls, 0)
            restored = ConversationSession(root, Profile(), session_id=session.session_id)
            self.assertEqual(restored.budget()['live_used'], 50)
            self.assertEqual(restored.budget()['prevented_invocations'], 2)

    def test_legacy_state_gets_new_fields_without_changing_usage(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            state = json.loads(session.path.read_text())
            for key in ('provider', 'model', 'response_style', 'prevented_invocations'):
                del state[key]
            state['live_used'] = 34
            session.path.write_text(json.dumps(state))
            restored = ConversationSession(root, Profile(worker='gemini'), session_id=session.session_id)
            self.assertEqual(restored.profile.worker, 'codex')
            self.assertEqual(restored.profile.response_style, 'teacher')
            self.assertEqual(restored.budget()['live_used'], 34)
            self.assertEqual(restored.budget()['prevented_invocations'], 0)

    def test_tools_are_evidence_not_premature_verified_claims(self):
        request = {'name': 'read_text', 'path': 'src/value.py', 'query': '', 'start_line': 1, 'limit': 20}
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, decision('investigate', reply='I verified the file contains VALUE = 999.', tool_requests=[request]))
            result = session.respond('What is inside src/value.py?', approve_live=True)
            self.assertEqual(result['status'], 'tool_results_ready')
            self.assertNotIn('VALUE = 999', result['reply'])
            self.assertIn('VALUE = 1', result['tool_results'][0]['result']['text'])
            self.assertEqual(worker.calls, 1)
            worker.value = decision(reply='The inspected file sets VALUE = 1.')
            session.respond('Explain those results', approve_live=True)
            self.assertIn('VALUE = 1', worker.prompts[-1])
            self.assertEqual(worker.calls, 2)
            session.respond('disable files')
            self.assertEqual(session.pending_context, [])

    def test_worker_timeout_still_consumes_reserved_slot_no_retry(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, WorkerError('process_timeout'))
            result = session.respond('Explain gravity', approve_live=True)
            self.assertEqual(result['status'], 'process_timeout')
            self.assertEqual(result['budget']['live_used'], 1)
            self.assertEqual(result['budget']['prevented_invocations'], 0)
            self.assertEqual(worker.calls, 1)


class ProviderTests(unittest.TestCase):
    def result(self, stdout='', code=0):
        return subprocess.CompletedProcess([], code, stdout, '')

    def claude_help(self):
        return self.result('--safe-mode --restricted --tools --strict-mcp-config --no-session-persistence')

    def test_credentials_removed_from_child_only(self):
        private = {'ANTHROPIC_API_KEY': 'secret', 'GEMINI_API_KEY': 'secret', 'GOOGLE_APPLICATION_CREDENTIALS': 'secret', 'CLAUDE_CODE_USE_BEDROCK': '1', 'OPENAI_API_KEY': 'secret', 'NODE_OPTIONS': '--require evil.js'}
        with patch.dict(os.environ, private):
            env = account_environment('claude')
            for key in private:
                self.assertNotIn(key, env)
                self.assertIn(key, os.environ)

    def test_claude_requires_account_auth_and_disables_native_tools(self):
        worker = AccountWorker('claude', command=['fake-claude'], model='chosen-model')
        responses = [self.claude_help(), self.result(json.dumps({'authMethod': 'claude.ai', 'loggedIn': True})), self.result(json.dumps({'structured_output': decision(), 'usage': {'input_tokens': 12, 'output_tokens': 3, 'private': 'omit'}}))]
        with patch('newton.providers.execute', side_effect=responses) as execute:
            worker.preflight(Path('.'))
            self.assertEqual(worker.decide('Explain inertia', Path('.'))['intent'], 'discuss')
            self.assertEqual(execute.call_count, 3)  # help + auth + one inference
            command = execute.call_args.args[0]
            self.assertEqual(command[command.index('--tools') + 1], '')
            self.assertEqual(command[command.index('--model') + 1], 'chosen-model')
            self.assertIn('--safe-mode', command)
            self.assertIn('--restricted', command)
            self.assertIn('--no-session-persistence', command)
            self.assertEqual(command[command.index('--max-turns') + 1], '1')
            self.assertNotIn('--dangerously-skip-permissions', command)
            self.assertEqual(worker.events[0]['usage'], {'input_tokens': 12, 'output_tokens': 3})
            with self.assertRaisesRegex(WorkerError, 'one_invocation'):
                worker.decide('again', Path('.'))
            self.assertEqual(execute.call_count, 3)

    def test_claude_rejects_api_console_and_third_party_auth(self):
        for method in ('api_key', 'api_key_helper', 'oauth_token', 'third_party', 'none'):
            with self.subTest(method=method):
                worker = AccountWorker('claude', command=['fake'])
                with patch('newton.providers.execute', side_effect=[self.claude_help(), self.result(json.dumps({'authMethod': method, 'loggedIn': True}))]) as execute:
                    with self.assertRaisesRegex(WorkerError, 'subscription_login_required'):
                        worker.preflight(Path('.'))
                    self.assertFalse(worker.ready)
                    self.assertEqual(execute.call_count, 2)

    def test_old_claude_cli_is_rejected_without_inference(self):
        with patch('newton.providers.execute', return_value=self.result('old help')) as execute:
            with self.assertRaisesRegex(WorkerError, 'cli_update_required'):
                AccountWorker('claude', command=['fake']).preflight(Path('.'))
            self.assertEqual(execute.call_count, 1)

    def test_gemini_uses_google_only_and_isolated_no_tool_settings(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            (home / '.gemini').mkdir()
            (home / '.gemini/settings.json').write_text(json.dumps({'security': {'auth': {'selectedType': 'oauth-personal'}}}))
            (home / '.gemini/oauth_creds.json').write_text('DO NOT READ OR LOG THIS')
            calls = []
            def execute(command, **kwargs):
                calls.append(command)
                if '--help' in command: return self.result('--output-format --policy')
                config = json.loads(Path(kwargs['env']['GEMINI_CLI_SYSTEM_SETTINGS_PATH']).read_text())
                self.assertEqual(config['security']['auth']['enforcedType'], 'oauth-personal')
                self.assertEqual(config['tools']['core'], [])
                self.assertFalse(config['hooksConfig']['enabled'])
                self.assertFalse(config['admin']['mcp']['enabled'])
                self.assertEqual(config['model']['maxSessionTurns'], 1)
                self.assertEqual(config['billing']['overageStrategy'], 'never')
                self.assertEqual(config['general']['maxAttempts'], 1)
                self.assertIn('decision = "deny"', Path(command[command.index('--policy') + 1]).read_text())
                self.assertNotEqual(Path(kwargs['cwd']), home)
                return self.result(json.dumps({'response': json.dumps(decision())}))
            with patch('newton.providers.Path.home', return_value=home), patch('newton.providers.execute', side_effect=execute):
                worker = AccountWorker('gemini', command=['fake'], model='gemini-chosen-model')
                self.assertEqual(worker.preflight(home)['authentication'], 'google_cached_login_unverified')
                worker.decide('Explain vectors', home)
                self.assertEqual(len(calls), 2)
            self.assertEqual((home / '.gemini/oauth_creds.json').read_text(), 'DO NOT READ OR LOG THIS')

    def test_gemini_missing_or_api_login_cannot_launch(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            with patch('newton.providers.Path.home', return_value=home), patch('newton.providers.execute', return_value=self.result('--output-format --policy')) as execute:
                worker = AccountWorker('gemini', command=['fake'], model='gemini-chosen-model')
                with self.assertRaisesRegex(WorkerError, 'google_login_required'):
                    worker.preflight(home)
                with self.assertRaisesRegex(WorkerError, 'preflight_required'):
                    worker.decide('question', home)
                self.assertEqual(execute.call_count, 1)

    def test_invalid_envelope_fails_without_retry_or_raw_output(self):
        for provider in ('claude', 'gemini'):
            with self.subTest(provider=provider), patch('newton.providers.execute', return_value=self.result('PRIVATE BAD OUTPUT')) as execute:
                worker = AccountWorker(provider, command=['fake'])
                worker.ready = True
                with self.assertRaisesRegex(WorkerError, '^invalid_decision_schema$'):
                    worker.decide('question', Path('.'))
                self.assertEqual(execute.call_count, 1)

    def test_model_is_explicit_validated_and_defaults_are_unchanged(self):
        self.assertEqual(Profile().worker, 'codex')
        self.assertEqual(Profile().model, '')
        self.assertEqual(Profile().max_live_invocations, 50)
        self.assertEqual(Profile().reply_chars, 1800)
        for bad in ('--dangerous', 'a b', 'x;cmd', '../oops', None):
            self.assertFalse(valid_model(bad))
        self.assertTrue(valid_model('provider/model-v1'))


class PreferencesTests(unittest.TestCase):
    def test_switch_needs_confirmation_revokes_permissions_preserves_usage(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            worker = FakeWorker(decision())
            app = NewtonAPI(root, 'codex', worker_factory=lambda: worker)
            self.addCleanup(app.close)
            identity = app.create_session({'confirm_new_budget': True})['session_id']
            session = app.sessions[identity]['session']
            session.state['live_used'] = 22
            app.approve(identity, {'kind': 'live_work', 'allow': True})
            app.approve(identity, {'kind': 'personal_files', 'allow': True})
            with self.assertRaisesRegex(APIError, 'confirm_provider_change'):
                app.preferences(identity, {'provider': 'gemini'})
            self.assertEqual(session.profile.worker, 'codex')
            info = app.preferences(identity, {'provider': 'gemini', 'model': 'chosen-model', 'response_style': 'supervisor', 'confirm_provider_change': True})
            self.assertEqual(info['budget']['live_used'], 22)
            self.assertFalse(info['permissions']['live_work'])
            self.assertFalse(info['permissions']['personal_files'])
            self.assertEqual(worker.calls, 0)
            resumed = ConversationSession(root, Profile(), session_id=identity, storage_name=app.storage_name)
            self.assertEqual(resumed.profile.worker, 'gemini')
            self.assertEqual(resumed.profile.model, 'chosen-model')
            self.assertEqual(resumed.profile.response_style, 'supervisor')
            self.assertEqual(resumed.budget()['live_used'], 22)
            # Style-only settings require no model call or repeated live approval.
            app.approve(identity, {'kind': 'live_work', 'allow': True})
            info = app.preferences(identity, {'response_style': 'teacher'})
            self.assertTrue(info['permissions']['live_work'])
            self.assertEqual(worker.calls, 0)

    def test_mock_and_busy_server_cannot_change_live_connection(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            app = NewtonAPI(root, 'mock')
            self.addCleanup(app.close)
            identity = app.create_session({})['session_id']
            with self.assertRaisesRegex(APIError, 'mock_cannot_switch_to_live'):
                app.preferences(identity, {'provider': 'claude', 'confirm_provider_change': True})
            self.assertEqual(app.preferences(identity, {'response_style': 'concise'})['response_style'], 'concise')
            app.active_job = 'busy'
            with self.assertRaisesRegex(APIError, 'task_already_running'):
                app.preferences(identity, {'response_style': 'teacher'})
            app.active_job = None


class FrontDoorTests(unittest.TestCase):
    def test_cli_provider_override_retains_usage_and_reapproves(self):
        import contextlib
        import io
        from newton import __main__ as cli
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            saved = ConversationSession(root, Profile())
            saved.state['live_used'] = 22
            saved._persist()
            worker = FakeWorker(decision())
            with patch.object(cli, 'PROJECT', root), patch('newton.conversation.AccountWorker', return_value=worker), patch('sys.argv', ['newton', '--provider', 'claude', '--model', 'chosen-model', '--style', 'supervisor']), patch('builtins.input', side_effect=['y', 'n', 'Explain gravity', 'quit']) as inputs, contextlib.redirect_stdout(io.StringIO()):
                cli.main()
            restored = ConversationSession(root, Profile(), session_id=saved.session_id)
            self.assertEqual(restored.profile.worker, 'claude')
            self.assertEqual(restored.profile.model, 'chosen-model')
            self.assertEqual(restored.profile.response_style, 'supervisor')
            self.assertEqual(restored.budget()['live_used'], 23)
            self.assertEqual(worker.calls, 1)
            self.assertEqual(sum('Authorize live work' in call.args[0] for call in inputs.call_args_list), 1)

    def test_preferences_route_is_authenticated_local_and_cannot_activate_mock(self):
        from test_newton_api import HTTPTests
        server = HTTPTests()
        server.setUp()
        try:
            status, body, _ = server.request('POST', '/api/sessions', {})
            identity = json.loads(body)['session_id']
            route = '/api/sessions/' + identity + '/preferences'
            self.assertEqual(server.request('POST', route, {'response_style': 'teacher'}, authenticate=False)[0], 401)
            status, body, _ = server.request('POST', route, {'response_style': 'supervisor'})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['response_style'], 'supervisor')
            self.assertEqual(json.loads(body)['budget']['live_used'], 0)
            self.assertEqual(server.request('POST', route, {'provider': 'claude', 'confirm_provider_change': True})[0], 400)
            self.assertEqual(server.request('POST', route, {'response_style': []})[0], 400)
            status, body, _ = server.request('GET', '/api/info')
            self.assertEqual({p['id'] for p in json.loads(body)['providers']}, {'codex', 'claude', 'gemini'})
        finally:
            server.tearDown()
