"""Subscription-only Codex worker. Never reads credentials or calls model APIs."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess


class WorkerError(RuntimeError):
    pass


def subscription_environment():
    env = os.environ.copy()
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'OPENAI_BASE_URL',
                 'CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID',
                 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE', 'CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY',
                 'CODEX_PERMISSION_PROFILE'):
        env.pop(name, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def execute(command, *, cwd, env, timeout, input_text=None):
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace', **options)
    try:
        stdout, stderr = process.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=15)
        raise WorkerError('process_timeout') from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def find_codex():
    executable = shutil.which('codex.exe') or shutil.which('codex')
    if not executable:
        raise WorkerError('codex_not_installed: install Codex CLI and sign in with ChatGPT')
    if Path(executable).suffix.lower() in ('.cmd', '.bat', '.ps1'):
        # Execute the actual CLI script through Node, rather than interpolating a shell command.
        script = Path(executable).parent / 'node_modules' / '@openai' / 'codex' / 'bin' / 'codex.js'
        node = shutil.which('node')
        if not node or not script.is_file():
            raise WorkerError('codex_launcher_unsupported: use a native CLI executable')
        return [node, str(script)]
    return [executable]


def check_subscription(command, root):
    result = execute([*command, '-c', 'forced_login_method="chatgpt"', 'login', 'status'],
                     cwd=root, env=subscription_environment(), timeout=15)
    status = (result.stdout + result.stderr).lower()
    if result.returncode != 0 or 'logged in using chatgpt' not in status:
        raise WorkerError('chatgpt_login_required: run codex login and choose ChatGPT; API login is rejected')
    return {'installed': True, 'authentication': 'chatgpt'}


def normalized_event(event):
    """Keep only observable metadata, never raw messages, command text or reasoning."""
    if not isinstance(event, dict):
        return None
    kind = event.get('type')
    if kind in ('thread.started', 'turn.started', 'turn.completed', 'turn.failed', 'error'):
        result = {'kind': kind}
        if kind == 'turn.completed' and isinstance(event.get('usage'), dict):
            result['usage'] = {k: event['usage'][k] for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')
                               if type(event['usage'].get(k)) is int and event['usage'][k] >= 0}
        return result
    if kind in ('item.started', 'item.completed', 'item.updated'):
        item = event.get('item')
        if not isinstance(item, dict) or item.get('type') not in ('command_execution', 'file_change', 'agent_message'):
            return None
        result = {'kind': kind, 'item_type': item['type']}
        if item.get('status') in ('in_progress', 'completed', 'failed', 'declined'):
            result['status'] = item['status']
        if type(item.get('exit_code')) is int:
            result['exit_code'] = item['exit_code']
        return result
    return None


@dataclass
class WorkerResult:
    completed: bool
    events: list[dict]
    final_message: str = ''
    task_status: str = 'completed'


class CodexWorker:
    def __init__(self, *, timeout=180, read_only=False, command=None):
        self.command = command or find_codex()
        self.timeout = timeout
        self.read_only = read_only

    def preflight(self, root):
        return check_subscription(self.command, root)

    def run(self, prompt, root):
        # Explicit authentication/provider overrides prevent API-key fallback.
        command = [*self.command, '-a', 'never', 'exec', '--json', '--ephemeral',
                   '--ignore-user-config', '--sandbox', 'read-only' if self.read_only else 'workspace-write',
                   '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"',
                   '-c', 'hide_agent_reasoning=true', '-c', 'web_search="disabled"',
                   '-c', 'mcp_servers={}', '-c', 'hooks={}',
                   '--output-schema', str(Path(__file__).with_name('worker_result.schema.json')), '-']
        result = execute(command, cwd=root, env=subscription_environment(),
                         timeout=self.timeout, input_text=prompt)
        normalized = []
        complete = False
        failed = False
        final_message = ''
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            safe = normalized_event(event)
            if safe:
                normalized.append(safe)
            complete |= event.get('type') == 'turn.completed'
            failed |= event.get('type') in ('turn.failed', 'error')
            item = event.get('item', {})
            if event.get('type') == 'item.completed' and isinstance(item, dict) and item.get('type') == 'agent_message':
                final_message = item.get('text', '') if isinstance(item.get('text'), str) else ''
        if result.returncode != 0 or failed or not complete:
            raise WorkerError('codex_run_failed: inspect CLI login, plan allowance and sandbox support')
        try:
            summary = json.loads(final_message)
            if set(summary) != {'task_status', 'summary'} or summary['task_status'] not in ('completed', 'blocked') or not isinstance(summary['summary'], str):
                raise ValueError
        except (ValueError, TypeError):
            raise WorkerError('invalid_worker_summary') from None
        return WorkerResult(True, normalized, summary['summary'], summary['task_status'])


class MockWorker:
    """Exercises orchestration without making edits or contacting a model."""
    def preflight(self, root):
        return {'installed': None, 'authentication': 'mock'}

    def run(self, prompt, root):
        return WorkerResult(True, [{'kind': 'turn.completed'}], 'Mock worker: no model run or code edits.')
