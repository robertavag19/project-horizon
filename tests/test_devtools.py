import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from devtools.coordinator import coordinate, TestResult
from devtools.workers import (CodexWorker, WorkerError, WorkerResult, check_subscription,
                             normalized_event, subscription_environment)


class WorkerTests(unittest.TestCase):
    def test_api_credentials_removed_from_child_environment(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret', 'CODEX_API_KEY': 'secret', 'CODEX_ACCESS_TOKEN': 'secret', 'OPENAI_BASE_URL': 'https://example.invalid'}):
            environment = subscription_environment()
        for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'OPENAI_BASE_URL'):
            self.assertNotIn(name, environment)

    def test_api_auth_rejected(self):
        with patch('devtools.workers.execute', return_value=subprocess.CompletedProcess([], 0, '', 'Logged in using an API key')):
            with self.assertRaises(WorkerError):
                check_subscription(['codex'], Path('.'))

    def test_chatgpt_auth_accepted(self):
        with patch('devtools.workers.execute', return_value=subprocess.CompletedProcess([], 0, '', 'Logged in using ChatGPT')):
            self.assertEqual(check_subscription(['codex'], Path('.'))['authentication'], 'chatgpt')

    def test_auth_error_fails_closed(self):
        with patch('devtools.workers.execute', return_value=subprocess.CompletedProcess([], 1, '', 'private raw diagnostic')):
            with self.assertRaises(WorkerError) as error:
                check_subscription(['codex'], Path('.'))
        self.assertNotIn('private raw diagnostic', str(error.exception))

    def test_reasoning_and_raw_content_excluded(self):
        self.assertIsNone(normalized_event({'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'PRIVATE'}}))
        event = normalized_event({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'SECRET', 'aggregated_output': 'PRIVATE', 'exit_code': 1}})
        self.assertEqual(event['exit_code'], 1)
        self.assertNotIn('SECRET', json.dumps(event))
        self.assertNotIn('PRIVATE', json.dumps(event))

    def test_usage_only_numeric_allowed_fields(self):
        event = normalized_event({'type': 'turn.completed', 'usage': {'input_tokens': 20, 'output_tokens': 'secret', 'other': 'secret'}})
        self.assertEqual(event['usage'], {'input_tokens': 20})

    def test_worker_uses_subscription_and_sandbox_flags(self):
        events = [json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}}), json.dumps({'type': 'turn.completed'})]
        with patch('devtools.workers.execute', return_value=subprocess.CompletedProcess([], 0, '\n'.join(events), '')) as execute:
            result = CodexWorker(command=['codex']).run('task', Path('.'))
        args = execute.call_args.args[0]
        self.assertIn('forced_login_method="chatgpt"', args)
        self.assertIn('model_provider="openai"', args)
        self.assertIn('--ignore-user-config', args)
        self.assertIn('--ephemeral', args)
        self.assertIn('workspace-write', args)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
        self.assertEqual(execute.call_args.kwargs['input_text'], 'task')
        self.assertTrue(result.completed)

    def test_worker_requires_completion_event(self):
        with patch('devtools.workers.execute', return_value=subprocess.CompletedProcess([], 0, '{}', 'SECRET')):
            with self.assertRaises(WorkerError) as error:
                CodexWorker(command=['codex']).run('task', Path('.'))
        self.assertNotIn('SECRET', str(error.exception))

    def test_read_only_flag(self):
        with patch('devtools.workers.execute', return_value=subprocess.CompletedProcess([], 0, '{"type":"turn.completed"}', '')) as execute:
            CodexWorker(command=['codex'], read_only=True).run('task', Path('.'))
        self.assertIn('read-only', execute.call_args.args[0])


class CoordinatorTests(unittest.TestCase):
    def make_repo(self, folder):
        root = Path(folder)
        (root / 'src').mkdir()
        (root / 'tests').mkdir()
        (root / '.gitignore').write_text('runs/\n__pycache__/\n')
        (root / 'src' / 'value.py').write_text('VALUE = 1\n')
        (root / 'tests' / 'test_value.py').write_text('import unittest\nfrom value import VALUE\nclass ValueTests(unittest.TestCase):\n def test_value(self):\n  self.assertEqual(VALUE, 2)\n')
        for command in (['init', '-b', 'main'], ['add', '.'], ['-c', 'user.name=Horizon Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture']):
            subprocess.run(['git', *command], cwd=root, check=True, capture_output=True)
        return root

    def test_repair_loop_and_original_checkout_preserved(self):
        class RepairWorker:
            def __init__(self):
                self.calls = 0
                self.prompts = []
            def preflight(self, root):
                return {'authentication': 'mock'}
            def run(self, prompt, root):
                self.calls += 1
                self.prompts.append(prompt)
                if self.calls == 2:
                    (root / 'src' / 'value.py').write_text('VALUE = 2\n')
                return WorkerResult(True, [{'kind': 'turn.completed'}])
        with TemporaryDirectory() as folder:
            root = self.make_repo(folder)
            worker = RepairWorker()
            result = coordinate(root, 'Fix value. PRIVATE_TASK', worker)
            self.assertEqual(result['status'], 'tests_passed_review_required')
            self.assertEqual(result['worker_attempts'], 2)
            self.assertEqual(result['tests_run'], 1)
            self.assertIn('AssertionError', worker.prompts[-1])
            self.assertEqual((root / 'src' / 'value.py').read_text(), 'VALUE = 1\n')
            self.assertIn('value.py', str(result['changed_files']))
            trace = Path(result['trace_file']).read_text()
            self.assertNotIn('PRIVATE_TASK', trace)
            self.assertIn('repair_requested', trace)

    def test_dirty_repo_refused_before_worker(self):
        with TemporaryDirectory() as folder:
            root = self.make_repo(folder)
            (root / 'src' / 'value.py').write_text('VALUE = 3\n')
            with patch.object(CodexWorker, 'preflight') as preflight:
                with self.assertRaises(WorkerError):
                    coordinate(root, 'task', CodexWorker(command=['codex']))
            preflight.assert_not_called()

    def test_bounded_failure(self):
        from devtools.workers import MockWorker
        with TemporaryDirectory() as folder:
            result = coordinate(self.make_repo(folder), 'task', MockWorker(), max_repairs=0)
        self.assertEqual(result['status'], 'repair_limit')
        self.assertEqual(result['worker_attempts'], 1)
        self.assertFalse(result['tests_passed'])

    def test_timeout_returns_report(self):
        class TimeoutWorker:
            def preflight(self, root):
                pass
            def run(self, prompt, root):
                raise WorkerError('process_timeout')
        with TemporaryDirectory() as folder:
            result = coordinate(self.make_repo(folder), 'task', TimeoutWorker())
        self.assertEqual(result['status'], 'process_timeout')
        self.assertFalse(result['tests_passed'])

    def test_zero_tests_is_not_success(self):
        from devtools.coordinator import run_tests
        with patch('devtools.coordinator.execute', return_value=subprocess.CompletedProcess([], 0, '', 'Ran 0 tests in 0.001s\nOK')):
            result = run_tests(Path('.'))
        self.assertFalse(result.passed)
