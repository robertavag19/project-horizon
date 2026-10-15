import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devtools.coordinator import coordinate
from devtools.workers import CodexWorker, WorkerError, apply_edits
import test_devtools as fixtures


def model_result(task_status, edits):
    message = json.dumps({'task_status': task_status, 'summary': 'Proposed edits', 'file_edits': edits})
    events = [json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': message}}),
              json.dumps({'type': 'turn.completed'})]
    return subprocess.CompletedProcess([], 0, '\n'.join(events), '')


class EditRecoveryTests(unittest.TestCase):
    def transport(self, responses):
        responses = iter(responses)
        def run(command, **kwargs):
            if 'login' in command:
                return subprocess.CompletedProcess([], 0, '', 'Logged in using ChatGPT')
            return next(responses)
        return run

    def test_blocked_response_with_proposals_is_rejected_before_writing(self):
        response = model_result('blocked', [{'path': 'README.md', 'content': 'PRIVATE_CANDIDATE'}])
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            with patch('devtools.workers.execute', side_effect=self.transport([response])):
                report = coordinate(root, 'Task', CodexWorker(command=['codex']), max_repairs=0)
            self.assertEqual(report['status'], 'blocked_status_with_edits')
            self.assertEqual(report['last_error'], 'blocked_status_with_edits')
            self.assertEqual(report['tests_run'], 0)
            self.assertFalse((Path(report['worktree']) / 'README.md').exists())
            trace = Path(report['trace_file']).read_text()
            self.assertIn('turn.completed', trace)
            self.assertNotIn('PRIVATE_CANDIDATE', trace)

    def test_validation_repair_can_complete_without_weakening_guard(self):
        bad = model_result('blocked', [{'path': 'README.md', 'content': 'PRIVATE_CANDIDATE'}])
        good = model_result('completed', [{'path': 'src/value.py', 'content': 'VALUE = 2\n'}])
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            with patch('devtools.workers.execute', side_effect=self.transport([bad, good])):
                report = coordinate(root, 'Fix value', CodexWorker(command=['codex']), max_repairs=1)
            self.assertEqual(report['status'], 'tests_passed_review_required')
            self.assertEqual(report['worker_attempts'], 2)
            self.assertEqual(report['tests_run'], 1)
            self.assertTrue(report['tests_passed'])
            self.assertFalse((Path(report['worktree']) / 'README.md').exists())
            self.assertIn('edit_validation', Path(report['trace_file']).read_text())

    def test_rejection_retry_stops_at_budget(self):
        bad = model_result('blocked', [{'path': 'README.md', 'content': 'x'}])
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            with patch('devtools.workers.execute', side_effect=self.transport([bad, bad])):
                report = coordinate(root, 'Task', CodexWorker(command=['codex']), max_repairs=1)
        self.assertEqual(report['worker_attempts'], 2)
        self.assertEqual(report['status'], 'blocked_status_with_edits')
        self.assertEqual(report['tests_run'], 0)

    def test_read_only_reason_is_explicit(self):
        with TemporaryDirectory() as folder, self.assertRaises(WorkerError) as error:
            apply_edits(Path(folder), [{'path': 'README.md', 'content': 'x'}], read_only=True)
        self.assertEqual(str(error.exception), 'read_only_edit_rejected')

    def test_malformed_edit_reason_is_explicit(self):
        for edits, reason in ((None, 'invalid_edit_list'), ([{}], 'invalid_edit_fields'),
                              ([{'path': 'README.md', 'content': None}], 'invalid_edit_content')):
            with self.subTest(reason=reason), TemporaryDirectory() as folder:
                with self.assertRaises(WorkerError) as error:
                    apply_edits(Path(folder), edits)
                self.assertEqual(str(error.exception), reason)
