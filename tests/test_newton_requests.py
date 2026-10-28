"""Offline regression tests for scoped requests and execution-grounded outcomes."""
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devtools.workers import WorkerError
from newton.conversation import ConversationSession
from newton.profile import Profile
from newton.task_context import explicit_request
from test_conversation import FakeWorker, decision
import test_devtools as fixtures


class RequestTests(unittest.TestCase):
    def setup(self, folder, value=None):
        root = fixtures.CoordinatorTests().make_repo(folder)
        # This suite tests new-file creation, so start with a passing committed baseline.
        (root / 'src/value.py').write_text('VALUE = 2\n')
        subprocess.run(['git', 'add', 'src/value.py'], cwd=root, check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.name=Horizon Test', '-c', 'user.email=test@example.invalid',
                        'commit', '-m', 'Passing request fixture'], cwd=root, check=True, capture_output=True)
        worker = FakeWorker(value or decision())
        session = ConversationSession(root, Profile(), worker_factory=lambda: worker)
        return root, worker, session

    def implementation(self, **overrides):
        return decision('implement', reply='Proposed changes; coordinator application remains pending.',
                        memory_summary='Implementation remains unauthorized and tests are pending.',
                        file_edits=[{'path': 'src/angles.py', 'content': 'def velocity(angle, time):\n    return angle / time\n'}],
                        **overrides)

    def ask(self, session, worker, question='Should velocity use radians or degrees?'):
        worker.value = decision('clarify', status='needs_clarification', reply=question)
        return session.respond('Can you create src/angles.py with velocity functions?', approve_live=True)

    def test_conversational_request_forms_are_authorized(self):
        messages = ['Create a file', 'Write these functions', 'Add tests', 'Fix this bug', 'Implement this',
                    'Can you create src/angles.py?', 'Could you please add tests?',
                    'I want you to add a function', 'I would like you to write these functions',
                    'We need to create a file', 'I have a task for you: create a module',
                    'Hey Newton, please create src/angles.py', 'For the next task, please write a file',
                    'I need a new file called angles.py', 'Create src/angles.py and explain what changed',
                    "I'd like you to create a Python file"]
        for message in messages:
            with self.subTest(message=message):
                self.assertTrue(explicit_request(message))

    def test_discussion_negation_and_external_requests_are_not_edit_authorization(self):
        messages = ['Explain how to create a file', 'What would you change?', 'Plan a feature',
                    'Could you explain how to add tests?', 'Do not create the file yet',
                    "Don't edit anything", 'Create a proposal without editing files',
                    'Review this before we implement it', 'Create a file and push it to GitHub',
                    'Delete all files', 'I saw a function that can create files']
        for message in messages:
            with self.subTest(message=message):
                self.assertFalse(explicit_request(message))

    def test_polite_creation_applies_once_without_second_confirmation(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, self.implementation())
            result = session.respond('I want you to create src/angles.py with velocity functions.', approve_live=True)
            self.assertEqual(result['status'], 'changes_tested_review_required')
            self.assertTrue((Path(result['workspace']) / 'src/angles.py').is_file())
            self.assertEqual(worker.calls, 1)
            self.assertEqual(result['budget']['live_used'], 1)
            self.assertIn('Implementation explicitly authorized: True', worker.prompts[0])

    def test_clarification_answer_inherits_scope_across_restart(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.assertEqual(self.ask(session, worker)['status'], 'clarification_required')
            pending = session.state['pending_clarification']
            self.assertEqual(pending['question'], 'Should velocity use radians or degrees?')
            worker.value = self.implementation()
            session = ConversationSession(root, Profile(), session_id=session.session_id, worker_factory=lambda: worker)
            result = session.respond('Use radians and seconds.', approve_live=True)
            self.assertEqual(result['status'], 'changes_tested_review_required')
            self.assertIsNone(session.state['pending_clarification'])
            self.assertEqual(worker.calls, 2)
            self.assertIn('Can you create src/angles.py', worker.prompts[-1])

    def test_yes_confirms_one_scoped_pending_action(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.ask(session, worker, 'Should I create src/angles.py with the velocity function?')
            worker.value = self.implementation()
            result = session.respond('yes', approve_live=True)
            self.assertEqual(result['status'], 'changes_tested_review_required')
            self.assertEqual(worker.calls, 2)

    def test_yes_without_pending_action_or_to_an_alternative_does_not_invoke_worker(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.assertEqual(session.respond('yes', approve_live=True)['status'], 'clarification_required')
            self.assertEqual(worker.calls, 0)
            self.ask(session, worker)
            self.assertEqual(session.respond('yes', approve_live=True)['status'], 'clarification_required')
            self.assertEqual(worker.calls, 1)

    def test_no_declines_pending_action_locally(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.ask(session, worker, 'Should I create src/angles.py?')
            session.respond('no', approve_live=True)
            self.assertIsNone(session.state['pending_clarification'])
            self.assertFalse(session.state['task']['authorized'])
            session.respond('yes', approve_live=True)
            self.assertEqual(worker.calls, 1)

    def test_discussion_answer_does_not_inherit_permission(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.ask(session, worker)
            worker.value = self.implementation()
            result = session.respond('Explain how you would create it first', approve_live=True)
            self.assertEqual(result['status'], 'implementation_authorization_required')
            self.assertIsNone(session.state['workspace_run'])

    def test_stale_model_memory_cannot_override_current_user_request(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, self.implementation())
            session.state['summary'] = 'Implementation unauthorized. Ask for confirmation again.'
            session._persist()
            result = session.respond('Please create src/angles.py now.', approve_live=True)
            self.assertEqual(result['status'], 'changes_tested_review_required')
            self.assertNotIn('Implementation unauthorized', worker.prompts[0])
            self.assertNotIn('pending', session.state['summary'])
            self.assertIn('Applied changes', session.state['summary'])

    def test_new_task_archives_old_review_and_uses_only_new_criteria(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, self.implementation())
            session.state['plan'] = [{'id': 'old', 'description': 'Earlier unrelated step', 'state': 'needs_review'}]
            session.state['criteria'] = [{'id': 'old', 'step_id': 'old', 'description': 'Old missing file',
                                         'kind': 'file_exists', 'path': 'src/missing.py', 'text': ''}]
            session._persist()
            result = session.respond('Create src/angles.py now', approve_live=True)
            self.assertEqual(result['status'], 'changes_tested_review_required')
            self.assertEqual(session.state['task_history'][0]['plan'][0]['state'], 'needs_review')
            self.assertFalse(session.state['criteria'])
            self.assertIn('Earlier unrelated step', session.respond('show previous tasks')['reply'])
            self.assertNotIn('Earlier unrelated step', worker.prompts[0])

    def test_new_request_clears_old_pending_question(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.ask(session, worker)
            worker.value = decision('implement', file_edits=[{'path': 'src/other.py', 'content': 'VALUE = 2\n'}])
            result = session.respond('Create src/other.py with a constant.', approve_live=True)
            self.assertEqual(result['status'], 'changes_tested_review_required')
            self.assertIsNone(session.state['pending_clarification'])
            self.assertNotIn('Should velocity use', worker.prompts[-1])

    def test_followup_cannot_expand_authorization_to_an_unrelated_file(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.ask(session, worker)
            worker.value = decision('implement', file_edits=[{'path': 'src/unrelated.py', 'content': 'VALUE = 2\n'}])
            result = session.respond('Use radians.', approve_live=True)
            self.assertEqual(result['status'], 'edit_outside_requested_scope')
            self.assertIsNone(session.state['workspace_run'])

    def test_related_test_file_can_accompany_requested_source(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            worker.value = decision('implement', file_edits=[{'path': 'src/angles.py', 'content': 'VALUE = 2\n'},
                                                            {'path': 'tests/test_angles.py', 'content': 'import unittest\n'}])
            result = session.respond('Create src/angles.py and add focused tests.', approve_live=True)
            self.assertEqual(len(result['changed_files']), 2)
            self.assertEqual(result['status'], 'changes_tested_review_required')

    def test_completed_memory_uses_coordinator_results_and_absolute_paths(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, self.implementation())
            result = session.respond('Create src/angles.py', approve_live=True)
            expected = str(Path(result['workspace']) / 'src/angles.py')
            self.assertIn(expected, result['reply'])
            self.assertIn('Current checks:', result['reply'])
            self.assertNotIn('pending', result['reply'])
            self.assertEqual(session.state['last_result']['verification'], result['verification'])
            report = json.loads(Path(result['report_file']).read_text())
            self.assertEqual(report['file_paths'], [expected])
            self.assertEqual(session.state['last_success']['run_id'], report['run_id'])

    def test_later_failure_preserves_prior_success_but_does_not_reuse_its_tests(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, self.implementation())
            first = session.respond('Create src/angles.py', approve_live=True)
            success = session.state['last_success'].copy()
            worker.value = WorkerError('invalid_tool_arguments')
            result = session.respond('Explain the last change in more detail', approve_live=True)
            self.assertEqual(result['status'], 'invalid_tool_arguments')
            self.assertEqual(session.state['last_success'], success)
            self.assertIsNone(result['verification'])
            self.assertIsNone(session.state['last_verification'])
            self.assertIsNone(session.respond('explain what you changed').get('verification'))
            self.assertTrue((Path(first['workspace']) / 'src/angles.py').exists())
            self.assertEqual(worker.calls, 2)

    def test_post_write_test_failure_reports_files_applied_and_unverified(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, self.implementation())
            with patch('newton.conversation.run_tests', side_effect=WorkerError('process_timeout')):
                result = session.respond('Create src/angles.py', approve_live=True)
            self.assertEqual(result['status'], 'process_timeout')
            self.assertEqual(result['changed_files'], ['src/angles.py'])
            self.assertIn('not verified', result['reply'])
            self.assertTrue((Path(result['workspace']) / 'src/angles.py').exists())
            self.assertIsNone(session.state['last_success'])

    def test_cancel_or_forget_clears_clarification_without_refunding_usage(self):
        for action in ('cancel', 'forget memory'):
            with self.subTest(action=action), TemporaryDirectory() as folder:
                root, worker, session = self.setup(folder)
                self.ask(session, worker)
                session.respond(action)
                self.assertIsNone(session.state['pending_clarification'])
                self.assertEqual(session.budget()['live_used'], 1)
                session.respond('yes', approve_live=True)
                self.assertEqual(worker.calls, 1)

    def test_readonly_mode_rejects_contextually_confirmed_edit(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder)
            self.ask(session, worker, 'Should I create src/angles.py?')
            worker.value = self.implementation()
            result = session.respond('yes', approve_live=True, force_read_only=True)
            self.assertEqual(result['status'], 'implementation_authorization_required')
            self.assertIsNone(session.state['workspace_run'])

    def test_explicit_request_with_no_proposal_does_not_claim_completion(self):
        with TemporaryDirectory() as folder:
            root, worker, session = self.setup(folder, decision(reply='Done, file created.'))
            result = session.respond('Create src/angles.py', approve_live=True)
            self.assertIn('No files changed', result['reply'])
            self.assertNotIn('Done, file created', result['reply'])
            self.assertIsNone(session.state['last_success'])

    def test_continuation_cannot_override_readonly_or_external_action_restrictions(self):
        for message in ('Continue without editing files', 'Continue and delete everything', 'Continue and push changes'):
            with self.subTest(message=message), TemporaryDirectory() as folder:
                root, worker, session = self.setup(folder, self.implementation())
                session.state['plan'] = [{'id': 'one', 'description': 'Create velocity functions', 'state': 'pending'}]
                session._persist()
                result = session.respond(message, approve_live=True)
                self.assertEqual(result['status'], 'implementation_authorization_required')
                self.assertIsNone(session.state['workspace_run'])
