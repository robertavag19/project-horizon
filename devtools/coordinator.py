"""One task -> isolated worktree -> worker -> tests -> bounded repairs -> report."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

from horizon.tracing import Recorder
from .workers import CodexWorker, MockWorker, WorkerError, execute, subscription_environment


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


def session_checkout(root: Path, workspace_run: str):
    """Reuse only a registered coordinator worktree in this repository."""
    root = root.resolve()
    if not isinstance(workspace_run, str) or not re.fullmatch(r'[0-9a-f]{32}', workspace_run):
        raise WorkerError('invalid_workspace_session')
    checkout = root / 'runs' / 'development' / workspace_run / 'worktree'
    if checkout.is_symlink() or not checkout.resolve().is_relative_to(root / 'runs' / 'development'):
        raise WorkerError('invalid_workspace_session')
    listed = git(root, 'worktree', 'list', '--porcelain')
    registered = [Path(line[9:]).resolve() for line in listed.splitlines() if line.startswith('worktree ')]
    if checkout.resolve() not in registered:
        raise WorkerError('workspace_not_registered')
    branch = 'codex/dev-' + workspace_run[:12]
    if git(checkout, 'branch', '--show-current') != branch:
        raise WorkerError('workspace_branch_changed')
    return checkout, branch


def coordinate(root: Path, task: str, worker, *, max_repairs=1, test_runner=run_tests, workspace_run=None, extra_instructions='', conversation_context=''):
    root = root.resolve()
    if not isinstance(task, str) or not 1 <= len(task.strip()) <= 8000:
        raise ValueError('task must contain 1 to 8000 characters')
    if type(max_repairs) is not int or not 0 <= max_repairs <= 2:
        raise ValueError('max_repairs must be 0, 1 or 2')
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise WorkerError('run_from_project_root')
    if workspace_run is None and git(root, 'status', '--porcelain'):
        raise WorkerError('commit_or_stash_changes_first: worktree starts from committed HEAD')
    worker.preflight(root)
    run_id = uuid.uuid4().hex
    folder = root / 'runs' / 'development' / run_id
    folder.mkdir(parents=True)
    if workspace_run is None:
        checkout = folder / 'worktree'
        branch = 'codex/dev-' + run_id[:12]
        git(root, 'worktree', 'add', '-b', branch, str(checkout), 'HEAD')
    else:
        checkout, branch = session_checkout(root, workspace_run)
    if isinstance(worker, CodexWorker):
        worker.protected_tests = set(git(checkout, 'ls-files', '--', 'tests').splitlines())
    recorder = Recorder(folder / 'events.jsonl', run_id, 'development_task')
    read_only = bool(getattr(worker, 'read_only', False))
    recorder.record('development_started', 0, branch=branch, read_only=read_only,
                    worker='mock' if isinstance(worker, MockWorker) else 'codex', max_repairs=max_repairs)
    # Prompt and test output are used in memory only, not written to traces/reports.
    instructions = '''Work only on the following task in this Git worktree.
Read README and applicable AGENTS instructions first. Make the smallest relevant change.
Preserve existing test coverage; do not weaken or remove tests to hide a failure.
Do not read .env, credential stores, or private files. Do not call paid model APIs,
install packages, use external services, push, merge, commit, or delete this worktree.
The coordinator runs tests independently. Give a brief final summary and limitations.
Task:\n'''
    if not isinstance(extra_instructions, str) or len(extra_instructions) > 4000:
        raise ValueError('profile instructions exceed limit')
    if not isinstance(conversation_context, str) or len(conversation_context) > 12000:
        raise ValueError('conversation context exceeds limit')
    instructions = extra_instructions + '\n' + instructions
    task = conversation_context + '\nCurrent task:\n' + task
    prompt = instructions + task
    status = 'repair_limit'
    attempts = 0
    worker_reply = ''
    worker_task_status = 'unknown'
    last_error = None
    tests = TestResult(False, 0, '')
    for attempt in range(max_repairs + 1):
        attempts += 1
        recorder.record('worker_started', attempts)
        try:
            result = worker.run(prompt, checkout)
            worker_reply = result.final_message
            worker_task_status = result.task_status
            for event in result.events:
                recorder.record('worker_event', attempts, **event)
            if not result.completed:
                raise WorkerError('worker_not_completed')
            recorder.record('worker_finished', attempts, final_message_length=len(result.final_message))
            tests = test_runner(checkout)
        except WorkerError as error:
            status = str(error).split(':', 1)[0]
            last_error = status
            if isinstance(worker, CodexWorker):
                for event in worker.last_events:
                    recorder.record('worker_event', attempts, **event)
            recorder.record('development_error', attempts, reason=status)
            repairable = {'invalid_edit_list', 'edit_count_limit', 'read_only_edit_rejected',
                          'invalid_edit_fields', 'invalid_edit_content', 'invalid_worker_path',
                          'existing_tests_are_protected', 'blocked_status_with_edits', 'invalid_worker_summary'}
            if status in repairable and attempt < max_repairs:
                prompt = instructions + task + '\nYour previous structured response was rejected by the coordinator. Rule: ' + status + '. No edits from that response were applied. Correct the response format or conflicting status. Propose only permitted files; do not weaken committed tests. When your edit proposals are ready, report completed. The coordinator applies edits and runs tests; you do not need shell access. A genuinely blocked response must have file_edits=[].'
                recorder.record('repair_requested', attempts, reason='edit_validation', rule=status)
                continue
            break
        recorder.record('tests_finished', attempts, passed=tests.passed, tests_run=tests.count)
        if worker_task_status == 'blocked':
            status = 'worker_blocked'
            break
        if tests.passed:
            status = 'tests_passed_review_required'
            break
        if attempt < max_repairs:
            prompt = instructions + task + '\nPrevious attempt failed independent tests. Fix the failure without weakening tests.\n' + tests.output
            recorder.record('repair_requested', attempts)
    changed = git(checkout, 'status', '--porcelain').splitlines()
    report = {
        'run_id': run_id, 'workspace_run': workspace_run or run_id, 'status': status, 'worker_task_status': worker_task_status, 'worker_attempts': attempts,
        'tests_passed': tests.passed, 'tests_run': tests.count,
        'branch': branch, 'worktree': str(checkout), 'read_only': read_only, 'last_error': last_error, 'changed_files': changed,
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
