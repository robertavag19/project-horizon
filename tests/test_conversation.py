"""Offline tests of the conversational controller; no live model invocation."""
import copy
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devtools.workers import WorkerError
from newton.conversation import ConversationSession
from newton.decisions import validate_decision
from newton.profile import Profile
from newton.project_tools import ProjectTools
from newton.worker import ConversationWorker
import test_devtools as fixtures


def decision(intent='discuss', **changes):
    value = {'intent': intent, 'status': 'completed', 'reply': 'A concise result.',
             'goal': '', 'memory_summary': 'Bounded summary.', 'plan': [], 'criteria': [],
             'file_edits': [], 'tool_requests': []}
    value.update(changes)
    return value


class FakeWorker:
    is_live = True
    events = []
    def __init__(self, value):
        self.value = value
        self.calls = 0
        self.prompts = []
    def preflight(self, root):
        return {'authentication': 'chatgpt'}
    def decide(self, prompt, root):
        self.calls += 1
        self.prompts.append(prompt)
        if isinstance(self.value, Exception):
            raise self.value
        return copy.deepcopy(self.value)


class EconomyTests(unittest.TestCase):
    def setup_session(self, folder, value=None):
        root = fixtures.CoordinatorTests().make_repo(folder)
        worker = FakeWorker(value or decision())
        session = ConversationSession(root, Profile(max_repairs=2), worker_factory=lambda: worker)
        return root, worker, session

    def test_no_live_launch_without_explicit_message_approval(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            result = session.respond('Explain this project')
            self.assertEqual(result['status'], 'approval_required')
            self.assertEqual(worker.calls, 0)
            self.assertEqual(session.budget()['live_used'], 0)
            self.assertEqual(result['budget']['max_invocations_this_message'], 1)

    def test_three_invocations_are_persisted_and_local_commands_remain_free(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            for _ in range(3):
                session.respond('Explain this project', approve_live=True)
            self.assertEqual(session.respond('Explain more', approve_live=True)['status'], 'budget_exhausted')
            self.assertEqual(worker.calls, 3)
            self.assertEqual(session.respond('status')['status'], 'local')
            self.assertEqual(session.respond('help')['status'], 'local')
            restored = ConversationSession(root, Profile(), session_id=session.session_id, worker_factory=lambda: worker)
            self.assertEqual(restored.budget()['live_used'], 3)
            self.assertEqual(restored.respond('Explain more', approve_live=True)['status'], 'budget_exhausted')

    def test_failed_worker_consumes_one_slot_with_zero_automatic_retries(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, WorkerError('process_timeout'))
            result = session.respond('Explain this project', approve_live=True)
            self.assertEqual(result['status'], 'process_timeout')
            self.assertEqual(worker.calls, 1)
            self.assertEqual(session.budget()['live_used'], 1)
            self.assertFalse(session.state['inflight'])

    def test_invalid_model_output_is_not_retried(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, {'bad': 'shape'})
            result = session.respond('Explain this project', approve_live=True)
            self.assertEqual(result['status'], 'invalid_decision_schema')
            self.assertEqual(worker.calls, 1)

    def test_budget_increase_requires_separate_explicit_approval(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            self.assertEqual(session.respond('increase budget by 1')['status'], 'budget_approval_required')
            self.assertEqual(session.budget()['live_limit'], 3)
            session.respond('increase budget by 1', approve_budget=True)
            self.assertEqual(session.budget()['live_limit'], 4)
            self.assertEqual(worker.calls, 0)

    def test_discussion_does_not_create_a_worktree_or_run_tests(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            with patch('newton.conversation.run_tests') as tests:
                result = session.respond('Explain this project', approve_live=True)
            tests.assert_not_called()
            self.assertIsNone(session.state['workspace_run'])
            self.assertEqual(result['status'], 'answered')

    def test_planning_records_pending_steps_and_acceptance_without_edits(self):
        value = decision('plan', goal='Improve value', plan=[{'id': 'one', 'description': 'Correct the value'}],
                         criteria=[{'id': 'c1', 'step_id': 'one', 'description': 'Value is 2', 'kind': 'text_contains', 'path': 'src/value.py', 'text': 'VALUE = 2'}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            result = session.respond('Plan the change', approve_live=True)
            self.assertEqual(result['status'], 'planned')
            self.assertEqual(session.state['plan'][0]['state'], 'pending')
            self.assertEqual((root / 'src/value.py').read_text(), 'VALUE = 1\n')
            self.assertIsNone(session.state['workspace_run'])

    def test_one_authorized_edit_runs_tests_and_leaves_original_unchanged(self):
        value = decision('implement', file_edits=[{'path': 'src/value.py', 'content': 'VALUE = 2\n'}],
                         criteria=[{'id': 'c1', 'step_id': '', 'description': 'Value is 2', 'kind': 'text_contains', 'path': 'src/value.py', 'text': 'VALUE = 2'},
                                   {'id': 'c2', 'step_id': '', 'description': 'Tests pass', 'kind': 'tests_pass', 'path': '', 'text': ''}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            result = session.respond('Fix value.py so VALUE = 2', approve_live=True)
            self.assertEqual(result['status'], 'changes_tested_review_required')
            self.assertTrue(result['verification']['tests_passed'])
            self.assertTrue(all(c['verdict'] == 'passed' for c in result['acceptance_checks']))
            self.assertEqual((root / 'src/value.py').read_text(), 'VALUE = 1\n')
            self.assertEqual(worker.calls, 1)

    def test_unauthorized_edit_proposals_never_write(self):
        value = decision('implement', file_edits=[{'path': 'src/value.py', 'content': 'VALUE = 2\n'}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            result = session.respond('What should we change?', approve_live=True)
            self.assertEqual(result['status'], 'implementation_authorization_required')
            self.assertIsNone(session.state['workspace_run'])

    def test_readonly_flag_rejects_even_explicit_implementation(self):
        value = decision('implement', file_edits=[{'path': 'src/value.py', 'content': 'VALUE = 2\n'}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            result = session.respond('Fix value.py', approve_live=True, force_read_only=True)
            self.assertEqual(result['status'], 'implementation_authorization_required')

    def test_ambiguous_request_can_request_clarification_without_edits(self):
        value = decision('clarify', status='needs_clarification', reply='Which behavior should change?')
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            result = session.respond('Make it better somehow', approve_live=True)
            self.assertEqual(result['status'], 'clarification_required')
            self.assertIsNone(session.state['workspace_run'])

    def test_failing_tests_do_not_trigger_second_invocation(self):
        value = decision('implement', file_edits=[{'path': 'src/value.py', 'content': 'VALUE = 3\n'}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            result = session.respond('Change value.py to 3', approve_live=True)
            self.assertEqual(result['status'], 'checks_failed')
            self.assertFalse(result['verification']['tests_passed'])
            self.assertEqual(worker.calls, 1)
            self.assertIn('AssertionError', result['verification_output'])

    def test_manual_criterion_stays_unverified(self):
        value = decision('review', criteria=[{'id': 'c1', 'step_id': '', 'description': 'Explanation is correct', 'kind': 'manual', 'path': '', 'text': ''}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            result = session.respond('Review the explanation', approve_live=True)
            self.assertEqual(result['acceptance_checks'][0]['verdict'], 'unverified')

    def test_local_search_read_inventory_and_tests_need_no_worker(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            for text in ('list files', 'search VALUE', 'read src/value.py', 'run tests', 'show changes'):
                session.respond(text)
            self.assertEqual(worker.calls, 0)
            self.assertEqual(session.budget()['live_used'], 0)

    def test_summary_and_plan_survive_restart_without_raw_conversation(self):
        value = decision('plan', goal='A small change', memory_summary='One pending step.', plan=[{'id': 'one', 'description': 'Change the value'}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            session.respond('Plan this RAW_MESSAGE_MARKER', approve_live=True)
            restored = ConversationSession(root, Profile(), session_id='latest')
            self.assertEqual(restored.state['goal'], 'A small change')
            self.assertEqual(restored.state['summary'], 'One pending step.')
            self.assertEqual(restored.state['plan'][0]['id'], 'one')
            self.assertNotIn('RAW_MESSAGE_MARKER', restored.path.read_text())

    def test_stale_session_cannot_overwrite_newer_budget(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            stale = ConversationSession(root, Profile(), session_id=session.session_id)
            session.respond('Explain this project', approve_live=True)
            with self.assertRaises(WorkerError) as error:
                stale.respond('status')
            self.assertIn('stale_session', str(error.exception))

    def test_lock_refuses_concurrent_use(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            (session.folder / 'active.lock').write_text('active')
            with self.assertRaises(WorkerError):
                session.respond('status')

    def test_memory_clear_does_not_reset_allowance(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            session.respond('Explain this project', approve_live=True)
            session.respond('forget memory')
            self.assertEqual(session.state['summary'], '')
            self.assertEqual(session.budget()['live_used'], 1)

    def test_cancel_plan_and_exit_use_no_extra_invocations(self):
        value = decision('plan', plan=[{'id': 'one', 'description': 'Change the value'}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            session.respond('Plan a change', approve_live=True)
            session.respond('cancel the plan')
            self.assertEqual(session.state['plan'][0]['state'], 'cancelled')
            self.assertEqual(session.respond('Stop here; we will continue tomorrow')['status'], 'exit')
            self.assertEqual(worker.calls, 1)

    def test_known_secret_is_rejected_before_worker(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder)
            result = session.respond('Use sk-12345678901234567890', approve_live=True)
            self.assertEqual(result['status'], 'sensitive_input_rejected')
            self.assertEqual(worker.calls, 0)

    def test_trace_contains_intent_and_counters_not_raw_private_content(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, decision(reply='PRIVATE_REPLY_MARKER'))
            result = session.respond('Explain RAW_MESSAGE_MARKER', approve_live=True)
            report = json.loads(Path(result['report_file']).read_text())
            trace = Path(report['trace_file']).read_text()
            self.assertIn('intent_selected', trace)
            self.assertIn('live_used', trace)
            self.assertNotIn('RAW_MESSAGE_MARKER', trace)
            self.assertNotIn('PRIVATE_REPLY_MARKER', trace)
            self.assertIsNone(report['usage'])
            self.assertIsNone(report['cost'])

    def test_two_step_plan_waits_for_user_review_before_next_step(self):
        plan = [{'id': 'one', 'description': 'Correct value'}, {'id': 'two', 'description': 'Document it'}]
        value = decision('implement', plan=plan, file_edits=[{'path': 'src/value.py', 'content': 'VALUE = 2\n'}])
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, value)
            session.respond('Fix value.py', approve_live=True)
            self.assertEqual(session.state['plan'][0]['state'], 'needs_review')
            self.assertEqual(session.state['plan'][1]['state'], 'pending')
            result = session.respond('Continue with the next step', approve_live=True)
            self.assertEqual(result['status'], 'review_required')
            self.assertEqual(worker.calls, 1)
            session.respond('accept step one')
            self.assertEqual(session.state['plan'][0]['state'], 'completed')

    def test_local_tool_request_does_not_launch_a_second_worker(self):
        request = {'name': 'read_text', 'path': 'src/value.py', 'query': '', 'start_line': 1, 'limit': 20}
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup_session(folder, decision('investigate', tool_requests=[request]))
            result = session.respond('Investigate the source', approve_live=True)
            self.assertEqual(worker.calls, 1)
            self.assertIn('VALUE', result['tool_results'][0]['result']['text'])
            self.assertIn('src/value.py', session.state['preferred_paths'])


class ContextAndDecisionTests(unittest.TestCase):
    def test_context_is_bounded_and_relevant(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'src').mkdir()
            (root / 'src/arithmetic.py').write_text('def sum_up_to(n):\n return n*(n+1)//2\n')
            (root / 'README.md').write_text('x' * 20000)
            context, fingerprints = ProjectTools(root).context('Fix arithmetic.py sum_up_to', max_chars=2000)
            self.assertLessEqual(context['context_chars'], 2000)
            self.assertEqual(context['files'][0]['path'], 'src/arithmetic.py')
            self.assertIn('src/arithmetic.py', fingerprints)

    def test_partial_context_cannot_replace_existing_file(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'README.md').write_text('x' * 10000)
            tools = ProjectTools(root)
            context, fingerprints = tools.context('README.md', max_chars=2000)
            self.assertFalse(context['files'][0]['complete'])
            with self.assertRaises(WorkerError):
                tools.verify_edit_context([{'path': 'README.md', 'content': 'replacement'}], fingerprints)

    def test_file_changed_since_snapshot_is_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'README.md').write_text('before')
            tools = ProjectTools(root)
            _, fingerprints = tools.context('README.md')
            (root / 'README.md').write_text('after')
            with self.assertRaises(WorkerError):
                tools.verify_edit_context([{'path': 'README.md', 'content': 'replacement'}], fingerprints)

    def test_unsafe_paths_and_tool_args_rejected(self):
        with TemporaryDirectory() as folder:
            tools = ProjectTools(folder)
            for path in ('../outside.py', '.env', 'docs/secrets.txt', 'C:/outside.py', 'runs/report.txt'):
                with self.subTest(path=path), self.assertRaises(WorkerError):
                    tools.path(path)
            with self.assertRaises(WorkerError):
                tools.dispatch({'name': 'shell', 'path': '', 'query': 'delete', 'start_line': 1, 'limit': 1})

    def test_non_implementation_intent_cannot_contain_edits(self):
        with self.assertRaises(WorkerError):
            validate_decision(decision('discuss', file_edits=[{'path': 'README.md', 'content': 'x'}]))

    def test_worker_instance_cannot_invoke_twice(self):
        text = json.dumps(decision())
        output = '\n'.join([json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}}), '{"type":"turn.completed"}'])
        with patch('newton.worker.execute', return_value=subprocess.CompletedProcess([], 0, output, '')) as execute:
            worker = ConversationWorker(command=['codex'])
            worker.decide('task', Path('.'))
            with self.assertRaises(WorkerError):
                worker.decide('task', Path('.'))
        self.assertEqual(execute.call_count, 1)
        self.assertIn('forced_login_method="chatgpt"', execute.call_args.args[0])

class MigrationAndInterfaceTests(unittest.TestCase):
    def test_legacy_session_counts_historical_attempts_conservatively(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            identity = 'a' * 32
            path = root / 'runs/newton' / identity
            path.mkdir(parents=True)
            old = {'project_root': str(root.resolve()), 'session_id': identity, 'workspace_run': None,
                   'reports': [{'run_id': 'b' * 32}, {'run_id': 'c' * 32}, {'run_id': 'd' * 32}]}
            (path / 'session.json').write_text(json.dumps(old))
            restored = ConversationSession(root, Profile(), session_id=identity)
            self.assertEqual(restored.budget()['live_used'], 3)
            self.assertEqual(restored.budget()['live_remaining'], 0)
            restored.respond('quit')
            backup = json.loads((path / 'legacy-session-v1.json').read_text())
            self.assertEqual(backup['reports'], old['reports'])

    def test_interrupted_reservation_is_not_refunded_on_restart(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            session = ConversationSession(root, Profile())
            session.state['live_used'] = 1
            session.state['inflight'] = True
            session._persist()
            restored = ConversationSession(root, Profile(), session_id=session.session_id)
            self.assertEqual(restored.budget()['live_used'], 1)
            self.assertTrue(restored.status()['call_inflight_or_interrupted'])

    def test_missing_requested_context_stops_without_an_extra_invocation(self):
        request = {'name': 'read_text', 'path': 'src/missing.py', 'query': '', 'start_line': 1, 'limit': 20}
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            worker = FakeWorker(decision('investigate', tool_requests=[request]))
            session = ConversationSession(root, Profile(), worker_factory=lambda: worker)
            result = session.respond('Investigate missing source', approve_live=True)
            self.assertEqual(result['status'], 'file_missing_or_oversized')
            self.assertEqual(worker.calls, 1)

    def test_symlink_escape_rejected(self):
        with TemporaryDirectory() as folder, TemporaryDirectory() as outside:
            root = Path(folder)
            (root / 'src').mkdir()
            (Path(outside) / 'secret.py').write_text('private')
            try:
                (root / 'src/link.py').symlink_to(Path(outside) / 'secret.py')
            except OSError:
                self.skipTest('symlink privilege unavailable')
            with self.assertRaises(WorkerError):
                ProjectTools(root).read('src/link.py')

    def test_diff_includes_new_file_preview(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            (root / 'src/new.py').write_text('NEW_VALUE = 4')
            result = ProjectTools(root).changes()
            self.assertEqual(result['new_files'][0]['path'], 'src/new.py')
            self.assertIn('NEW_VALUE', result['new_files'][0]['preview'])

    def test_natural_test_request_is_handled_locally(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            worker = FakeWorker(decision())
            session = ConversationSession(root, Profile(), worker_factory=lambda: worker)
            result = session.respond('Can you run the tests?')
            self.assertEqual(result['status'], 'local')
            self.assertEqual(worker.calls, 0)

    def test_cli_mock_conversation_is_offline_and_human_readable(self):
        import contextlib
        import importlib
        import io
        cli = importlib.import_module('newton.__main__')
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            output = io.StringIO()
            with patch.object(cli, 'PROJECT', root), patch.object(cli, 'load_profile', return_value=Profile(worker='mock')), \
                 patch('sys.argv', ['newton']), patch('builtins.input', side_effect=['hello', 'status', 'list files', 'quit']), \
                 patch('newton.worker.execute') as execute, contextlib.redirect_stdout(output):
                cli.main()
            execute.assert_not_called()
            self.assertIn('No saved goal', output.getvalue())
            self.assertIn('0/3 live invocations', output.getvalue())

    def test_cli_one_off_task_does_not_run_without_approval(self):
        import contextlib
        import importlib
        import io
        cli = importlib.import_module('newton.__main__')
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            with patch.object(cli, 'PROJECT', root), patch.object(cli, 'load_profile', return_value=Profile()), \
                 patch('sys.argv', ['newton', '--task', 'Explain the project']), \
                 patch('newton.conversation.ConversationWorker') as worker, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main()
            self.assertEqual(error.exception.code, 2)
            worker.assert_not_called()


class ConversationalFlowTests(unittest.TestCase):
    def test_cli_plan_then_one_implementation_step_with_two_explicit_approvals(self):
        import contextlib
        import importlib
        import io
        cli = importlib.import_module('newton.__main__')
        frames = iter([
            decision('plan', goal='Correct the value', plan=[{'id': 'one', 'description': 'Fix value.py'}],
                     criteria=[{'id': 'c1', 'step_id': 'one', 'description': 'Value is 2', 'kind': 'text_contains', 'path': 'src/value.py', 'text': 'VALUE = 2'}]),
            decision('implement', file_edits=[{'path': 'src/value.py', 'content': 'VALUE = 2\n'}]),
        ])
        workers = []
        def factory(*args, **kwargs):
            worker = FakeWorker(next(frames))
            workers.append(worker)
            return worker
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            output = io.StringIO()
            with patch.object(cli, 'PROJECT', root), patch.object(cli, 'load_profile', return_value=Profile()), \
                 patch('sys.argv', ['newton']), patch('builtins.input', side_effect=['Help me plan the value change', 'y', 'Implement the first step', 'y', 'status', 'quit']), \
                 patch('newton.conversation.ConversationWorker', side_effect=factory), contextlib.redirect_stdout(output):
                cli.main()
            self.assertEqual(len(workers), 2)
            self.assertTrue(all(worker.calls == 1 for worker in workers))
            self.assertIn('2/3 live invocations', output.getvalue())
            restored = ConversationSession(root, Profile(), session_id='latest')
            self.assertEqual(restored.state['plan'][0]['state'], 'needs_review')
            self.assertEqual((root / 'src/value.py').read_text(), 'VALUE = 1\n')
            self.assertEqual((restored.workspace() / 'src/value.py').read_text(), 'VALUE = 2\n')

    def test_invalid_state_is_rejected_without_worker(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            session = ConversationSession(root, Profile())
            session.state['plan'] = [{'not': 'a plan'}]
            session.path.write_text(json.dumps(session.state))
            with self.assertRaises(WorkerError):
                ConversationSession(root, Profile(), session_id=session.session_id)
