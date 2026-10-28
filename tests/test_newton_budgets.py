"""Offline regression tests: budgets, launch approval, and bounded complex answers."""
import contextlib
from dataclasses import replace
import importlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from newton.conversation import ConversationSession
from newton.profile import Profile
from newton.project_tools import ProjectTools
from test_conversation import FakeWorker, decision
import test_devtools as fixtures

cli = importlib.import_module('newton.__main__')


class BudgetTests(unittest.TestCase):
    def session(self, folder, profile=None, value=None):
        root = fixtures.CoordinatorTests().make_repo(folder)
        worker = FakeWorker(value or decision())
        session = ConversationSession(root, profile or Profile(), worker_factory=lambda: worker)
        return root, worker, session

    def test_default_fifty_is_enforced_and_persists(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder)
            self.assertEqual(session.budget()['live_limit'], 50)
            for _ in range(50):
                self.assertEqual(session.respond('Explain the code', approve_live=True)['status'], 'answered')
            result = session.respond('More detail', approve_live=True)
            self.assertEqual(result['status'], 'budget_exhausted')
            self.assertIn('add budget 10', result['reply'])
            self.assertEqual(worker.calls, 50)
            session.respond('list files')
            restored = ConversationSession(root, Profile(), session_id=session.session_id)
            self.assertEqual(restored.budget()['live_used'], 50)
            self.assertEqual(restored.budget()['live_remaining'], 0)

    def test_overspent_legacy_budget_adds_actual_available_capacity(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder, Profile(max_live_invocations=3))
            session.state['live_used'] = 4
            session._persist()
            for message in ('add budget 10', 'increase budget by 10'):
                self.assertEqual(session.respond(message)['status'], 'budget_approval_required')
                self.assertEqual(session.budget()['live_limit'], 3)
                result = session.respond(message, approve_budget=True)
                self.assertEqual(result['budget']['live_remaining'], 10)
                session.state['live_limit'] = 3
                session._persist()
            self.assertEqual(session.state['live_used'], 4)
            self.assertEqual(worker.calls, 0)

    def test_set_budget_changes_total_only_after_confirmation(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder, Profile(max_live_invocations=3))
            session.state['live_used'] = 4
            session._persist()
            session.respond('set budget 50')
            self.assertEqual(session.budget()['live_limit'], 3)
            session.respond('set budget 50', approve_budget=True)
            self.assertEqual(session.budget()['live_used'], 4)
            self.assertEqual(session.budget()['live_remaining'], 46)
            restored = ConversationSession(root, Profile(), session_id=session.session_id)
            self.assertEqual(restored.budget()['live_remaining'], 46)
            session.respond('set budget 2', approve_budget=True)
            self.assertEqual(session.budget()['live_remaining'], 0)
            self.assertEqual(worker.calls, 0)

    def test_invalid_budget_commands_never_launch_model_or_change_limit(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder)
            for message in ('set budget 0', 'add budget 0', 'set budget -1', 'add budget many', 'set budget 1001', 'add budget 99999'):
                with self.subTest(message=message):
                    self.assertEqual(session.respond(message, approve_live=True, approve_budget=True)['status'], 'invalid_budget')
            self.assertEqual(session.budget()['live_limit'], 50)
            self.assertEqual(worker.calls, 0)

    def test_existing_session_does_not_silently_adopt_new_default(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder, Profile(max_live_invocations=4))
            session.state['live_used'] = 4
            session._persist()
            restored = ConversationSession(root, Profile(), session_id=session.session_id)
            with patch('builtins.input', side_effect=['n', 'y']), contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(cli.approve_launch(restored))
            self.assertEqual(restored.budget()['live_limit'], 4)
            with patch('builtins.input', side_effect=['y', 'n']), contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(cli.approve_launch(restored))
            self.assertEqual(restored.budget()['live_used'], 4)
            self.assertEqual(restored.budget()['live_limit'], 50)
            self.assertEqual(worker.calls, 0)

    def test_cli_restart_requires_new_approval_and_never_replays_messages(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder)
            output = io.StringIO()
            with patch.object(cli, 'PROJECT', root), patch.object(cli, 'load_profile', return_value=Profile()), \
                 patch('newton.conversation.ConversationWorker', return_value=worker), patch('sys.argv', ['newton']), \
                 patch('builtins.input', side_effect=['y', 'n', 'Explain one', 'Explain two', 'quit']) as inputs, contextlib.redirect_stdout(output):
                cli.main()
            self.assertEqual(worker.calls, 2)
            self.assertEqual(sum('Authorize live work' in c.args[0] for c in inputs.call_args_list), 1)
            with patch.object(cli, 'PROJECT', root), patch.object(cli, 'load_profile', return_value=Profile()), \
                 patch('newton.conversation.ConversationWorker', return_value=worker), patch('sys.argv', ['newton']), \
                 patch('builtins.input', side_effect=['n', 'n', 'Explain three', 'status', 'quit']) as inputs, contextlib.redirect_stdout(output):
                cli.main()
            self.assertEqual(worker.calls, 2)
            self.assertEqual(sum('Authorize live work' in c.args[0] for c in inputs.call_args_list), 1)
            restored = ConversationSession(root, Profile(), session_id='latest')
            self.assertEqual(restored.budget()['live_used'], 2)
            self.assertNotIn('launch_approved', restored.state)

    def test_cli_local_budget_confirmation_does_not_invoke_worker(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder)
            with patch.object(cli, 'PROJECT', root), patch.object(cli, 'load_profile', return_value=Profile()), \
                 patch('newton.conversation.ConversationWorker', return_value=worker), patch('sys.argv', ['newton']), \
                 patch('builtins.input', side_effect=['n', 'n', 'set budget 75', 'n', 'add budget 10', 'y', 'quit']), contextlib.redirect_stdout(io.StringIO()):
                cli.main()
            restored = ConversationSession(root, Profile(), session_id='latest')
            self.assertEqual(restored.budget()['live_limit'], 60)
            self.assertEqual(worker.calls, 0)

    def test_reply_limit_is_configurable_but_not_unbounded(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder, Profile(reply_chars=6000), decision(reply='x' * 3000))
            result = session.respond('Explain carefully', approve_live=True)
            self.assertEqual(result['status'], 'answered')
            self.assertEqual(len(result['reply']), 3000)
            self.assertIn('Keep replies under 6000 characters', worker.prompts[0])
            self.assertLessEqual(len(session.state['last_reply']), 1800)
            session.profile = replace(session.profile, reply_chars=1800)
            self.assertEqual(session.respond('Explain again', approve_live=True)['status'], 'invalid_decision_text')
            self.assertEqual(worker.calls, 2)

    def test_worker_timeout_above_ninety_is_not_silently_clamped(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.session(folder, Profile(worker_timeout=300, turn_timeout=450))
            session.worker_factory = None
            with patch('newton.conversation.ConversationWorker') as factory:
                session._worker()
            factory.assert_called_once_with(timeout=300)

    def test_larger_context_can_supply_complete_larger_file(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'README.md').write_text('x' * 9000)
            source, hashes = ProjectTools(root).context('README.md', max_chars=10000, max_files=1, file_chars=10000)
            self.assertTrue(source['files'][0]['complete'])
            self.assertIn('README.md', hashes)
            self.assertEqual(source['context_chars'], 9000)

    def test_configuration_boundaries(self):
        self.assertEqual(Profile().worker_timeout, 90)
        for values in ({'max_live_invocations': 1001}, {'reply_chars': 12001}, {'context_chars': 64001}, {'worker_timeout': 601}, {'turn_timeout': 901}, {'context_files': 11}, {'context_file_chars': 20001}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Profile(**values)
