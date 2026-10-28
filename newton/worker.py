"""Single-invocation subscription worker; never executes requested project actions."""
import json
from pathlib import Path

from devtools.workers import (find_codex, check_subscription, execute,
                             subscription_environment, normalized_event, WorkerError)
from .decisions import validate_decision


# Keep file I/O in the approval-gated coordinator, not native model tools.
# Supported names were verified against the installed CLI feature list.
DISABLED_WORKER_FEATURES = ('shell_tool', 'view_image', 'apps', 'plugins', 'remote_plugin',
                            'multi_agent', 'goals', 'hooks', 'code_mode_host', 'browser_use',
                            'computer_use', 'in_app_browser', 'image_generation',
                            'skill_search', 'workspace_dependencies')


class ConversationWorker:
    is_live = True

    def __init__(self, timeout=90, command=None, model=''):
        self.command = command or find_codex()
        self.timeout = timeout
        self.model = model
        self.called = False
        self.events = []

    def preflight(self, root):
        return check_subscription(self.command, root)

    def decide(self, prompt, root):
        if self.called:
            raise WorkerError('one_invocation_per_message')
        self.called = True
        command = [*self.command, '-a', 'never', 'exec', '--json', '--ephemeral',
                   '--ignore-user-config', '--sandbox', 'read-only',
                   '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"',
                   '-c', 'hide_agent_reasoning=true', '-c', 'web_search="disabled"',
                   '-c', 'mcp_servers={}', '-c', 'hooks={}',
                   '--output-schema', str(getattr(self, 'schema_path', Path(__file__).with_name('decision.schema.json'))), '-']
        # Configuration overrides are local; do not alter the user's global CLI setup.
        for feature in DISABLED_WORKER_FEATURES:
            command[len(self.command):len(self.command)] = ['-c', 'features.' + feature + '=false']
        if self.model:
            command[len(self.command):len(self.command)] = ['--model', self.model]
        response = execute(command, cwd=root, env=subscription_environment(), timeout=self.timeout, input_text=prompt)
        final = None
        completed = failed = False
        for line in response.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            safe = normalized_event(event)
            if safe:
                self.events.append(safe)
            completed |= event.get('type') == 'turn.completed'
            failed |= event.get('type') in ('turn.failed', 'error')
            item = event.get('item', {})
            if isinstance(item, dict) and event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                final = item.get('text')
        if response.returncode != 0 or failed or not completed:
            raise WorkerError('codex_run_failed')
        if not isinstance(final, str) or len(final) > 60000:
            raise WorkerError('invalid_decision_schema')
        try:
            return validate_decision(json.loads(final))
        except (ValueError, TypeError, KeyError):
            raise WorkerError('invalid_decision_schema') from None


class ConversationMock:
    is_live = False
    events = []

    def preflight(self, root):
        return {'authentication': 'mock'}

    def decide(self, prompt, root):
        return {'intent': 'clarify', 'status': 'needs_clarification',
                'reply': 'Offline mock: no model was contacted and no files changed. Use local commands such as status, list files, run tests, or quit.',
                'goal': '', 'memory_summary': '', 'plan': [], 'criteria': [], 'file_edits': [], 'tool_requests': []}
