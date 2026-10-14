"""One task -> isolated worktree -> worker -> tests -> bounded repairs -> report."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

from horizon.tracing import Recorder
from .workers import MockWorker, WorkerError, execute, subscription_environment


@dataclass
class TestResult:
    passed: bool
    count: int
    output: str


def git(root, *arguments):
    result = execute(['git', *arguments], cwd=root, env=subscription_environment(), timeout=30)
    if result.returncode:
        raise WorkerError('git_operation_failed')
    return result.stdout.strip()


def run_tests(root, timeout=90):
    env = subscription_environment()
    env['PYTHONPATH'] = str(root / 'src')
    result = execute([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                     cwd=root, env=env, timeout=timeout)
    output = result.stdout + result.stderr
    match = re.search(r'Ran (\d+) tests? in ', output)
    count = int(match.group(1)) if match else 0
    return TestResult(result.returncode == 0 and count > 0, count, output[-12000:])


def coordinate(root: Path, task: str, worker, *, max_repairs=1, test_runner=run_tests):
    root = root.resolve()
    if not isinstance(task, str) or not 1 <= len(task.strip()) <= 8000:
        raise ValueError('task must contain 1 to 8000 characters')
    if type(max_repairs) is not int or not 0 <= max_repairs <= 2:
        raise ValueError('max_repairs must be 0, 1 or 2')
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise WorkerError('run_from_project_root')
    if git(root, 'status', '--porcelain'):
        raise WorkerError('commit_or_stash_changes_first: worktree starts from committed HEAD')
    worker.preflight(root)
    run_id = uuid.uuid4().hex
    folder = root / 'runs' / 'development' / run_id
    folder.mkdir(parents=True)
    checkout = folder / 'worktree'
    branch = 'codex/dev-' + run_id[:12]
    git(root, 'worktree', 'add', '-b', branch, str(checkout), 'HEAD')
    recorder = Recorder(folder / 'events.jsonl', run_id, 'development_task')
    recorder.record('development_started', 0, branch=branch,
                    worker='mock' if isinstance(worker, MockWorker) else 'codex', max_repairs=max_repairs)
    # Prompt and test output are used in memory only, not written to traces/reports.
    instructions = '''Work only on the following task in this Git worktree.
Read README and applicable AGENTS instructions first. Make the smallest relevant change.
Preserve existing test coverage; do not weaken or remove tests to hide a failure.
Do not read .env, credential stores, or private files. Do not call paid model APIs,
install packages, use external services, push, merge, commit, or delete this worktree.
The coordinator runs tests independently. Give a brief final summary and limitations.
Task:\n'''
    prompt = instructions + task
    status = 'repair_limit'
    attempts = 0
    worker_reply = ''
    tests = TestResult(False, 0, '')
    for attempt in range(max_repairs + 1):
        attempts += 1
        recorder.record('worker_started', attempts)
        try:
            result = worker.run(prompt, checkout)
            worker_reply = result.final_message
            for event in result.events:
                recorder.record('worker_event', attempts, **event)
            if not result.completed:
                raise WorkerError('worker_not_completed')
            recorder.record('worker_finished', attempts, final_message_length=len(result.final_message))
            tests = test_runner(checkout)
        except WorkerError as error:
            status = str(error).split(':', 1)[0]
            recorder.record('development_error', attempts, reason=status)
            break
        recorder.record('tests_finished', attempts, passed=tests.passed, tests_run=tests.count)
        if tests.passed:
            status = 'tests_passed_review_required'
            break
        if attempt < max_repairs:
            prompt = instructions + task + '\nPrevious attempt failed independent tests. Fix the failure without weakening tests.\n' + tests.output
            recorder.record('repair_requested', attempts)
    changed = git(checkout, 'status', '--porcelain').splitlines()
    report = {
        'run_id': run_id, 'status': status, 'worker_attempts': attempts,
        'tests_passed': tests.passed, 'tests_run': tests.count,
        'branch': branch, 'worktree': str(checkout), 'changed_files': changed,
        'trace_file': str(recorder.path),
        'report_file': str(folder / 'report.json'),
        'limitations': 'Tests passing does not prove task fulfillment. Changes require review; no merge or push. Codex uses plan allowance; no token cap is enforced by this coordinator.',
    }
    recorder.record('development_finished', attempts, status=status, tests_passed=tests.passed,
                    tests_run=tests.count, changed_file_count=len(changed))
    (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    # Display the worker's final answer, but do not persist it in the metadata report.
    report['worker_reply'] = worker_reply
    return report
