"""Account-based CLI adapters. No API keys, automatic provider fallback or native tools."""
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

from devtools.workers import WorkerError, execute, subscription_environment, find_codex
from .decisions import validate_decision

PROVIDERS = {
    'codex': {'label': 'ChatGPT / Codex', 'login': 'codex login', 'account': 'ChatGPT sign-in', 'docs': 'https://developers.openai.com/codex/auth'},
    'claude': {'label': 'Claude', 'login': 'claude auth login', 'account': 'Claude Code with a claude.ai subscription', 'docs': 'https://code.claude.com/docs/en/authentication'},
    'gemini': {'label': 'Gemini', 'login': 'gemini (choose Sign in with Google)', 'account': 'Gemini CLI with a cached Google login', 'docs': 'https://geminicli.com/docs/get-started/authentication/'},
}

def valid_model(model):
    return isinstance(model, str) and (model == '' or bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,99}', model)))

def find_cli(provider):
    if provider == 'codex':
        return find_codex()
    if provider not in PROVIDERS:
        raise WorkerError('unsupported_provider')
    binary = shutil.which(provider + '.exe') or shutil.which(provider)
    if not binary:
        raise WorkerError(provider + '_not_installed')
    if Path(binary).suffix.lower() in ('.cmd', '.bat', '.ps1'):
        package = {'claude': '@anthropic-ai/claude-code/cli.js', 'gemini': '@google/gemini-cli/dist/index.js'}[provider]
        script = Path(binary).parent / 'node_modules' / package
        node = shutil.which('node')
        if not node or not script.is_file():
            raise WorkerError(provider + '_launcher_unsupported')
        return [node, str(script)]
    return [binary]

def catalog():
    result = []
    for name, spec in PROVIDERS.items():
        try:
            find_cli(name)
            installed = True
        except WorkerError:
            installed = False
        result.append({'id': name, **spec, 'installed': installed, 'authentication': 'not_checked',
                       'status': 'installed_sign_in_not_checked' if installed else 'setup_required'})
    return result

def account_environment(provider):
    env = subscription_environment()
    # Remove injected credentials, provider endpoints and third-party billing routes.
    prefixes = ('ANTHROPIC_', 'CLAUDE_', 'GEMINI_', 'GOOGLE_', 'GCLOUD_', 'CLOUDSDK_', 'VERTEX_', 'AWS_', 'AZURE_')
    for key in list(env):
        if key.upper().startswith(prefixes) or key.upper() in ('NODE_OPTIONS', 'NODE_PATH'):
            env.pop(key, None)
    return env

CLAUDE_SETTINGS = {'forceLoginMethod': 'claudeai', 'disableAllHooks': True,
                   'autoMemoryEnabled': False, 'enableAllProjectMcpServers': False}

class AccountWorker:
    is_live = True
    def __init__(self, provider, timeout=90, model='', command=None):
        if provider not in ('claude', 'gemini') or not valid_model(model):
            raise WorkerError('unsupported_provider_or_model')
        self.provider, self.timeout, self.model = provider, timeout, model
        self.command = command or find_cli(provider)
        self.called = False
        self.ready = False
        self.events = []

    def preflight(self, root):
        self.ready = False
        if self.provider == 'gemini' and (not self.model or self.model.lower().startswith('auto')):
            raise WorkerError('gemini_explicit_model_required: choose a specific Gemini model with --model or the app to avoid automatic model routing')
        # Help/auth status are local diagnostics, never inference prompts.
        with TemporaryDirectory(prefix='newton-check-') as folder:
            env = account_environment(self.provider)
            help_result = execute([*self.command, '--help'], cwd=folder, env=env, timeout=15)
            required = ('--safe-mode', '--restricted', '--tools', '--strict-mcp-config', '--no-session-persistence') if self.provider == 'claude' else ('--output-format', '--policy')
            if help_result.returncode or any(flag not in help_result.stdout for flag in required):
                raise WorkerError(self.provider + '_cli_update_required')
            if self.provider == 'claude':
                result = execute([*self.command, '--safe-mode', '--restricted', '--settings', json.dumps(CLAUDE_SETTINGS), 'auth', 'status'], cwd=folder, env=env, timeout=15)
                try:
                    auth = json.loads(result.stdout)
                except (ValueError, TypeError):
                    raise WorkerError('claude_subscription_login_required') from None
                if result.returncode or not isinstance(auth, dict) or auth.get('authMethod') != 'claude.ai' or auth.get('loggedIn') is not True:
                    raise WorkerError('claude_subscription_login_required')
                method = 'claude.ai'
            else:
                # Inspect only the auth selection, never OAuth credential contents.
                home = Path.home() / '.gemini'
                settings = home / 'settings.json'
                try:
                    if settings.stat().st_size > 200000:
                        raise ValueError
                    auth = json.loads(settings.read_text(encoding='utf-8')).get('security', {}).get('auth', {})
                except (OSError, ValueError, AttributeError):
                    raise WorkerError('gemini_google_login_required') from None
                if auth.get('selectedType') != 'oauth-personal' or not (home / 'oauth_creds.json').is_file():
                    raise WorkerError('gemini_google_login_required')
                method = 'google_cached_login_unverified'
            self.ready = True
            return {'installed': True, 'authentication': method, 'provider': self.provider,
                    'model': self.model or 'CLI default', 'live_validated': False}

    def decide(self, prompt, root):
        if self.called:
            raise WorkerError('one_invocation_per_message')
        if not self.ready:
            raise WorkerError('provider_preflight_required')
        self.called = True
        schema = Path(getattr(self, 'schema_path', Path(__file__).with_name('decision.schema.json'))).read_text(encoding='utf-8')
        with TemporaryDirectory(prefix='newton-worker-') as folder:
            env = account_environment(self.provider)
            if self.provider == 'claude':
                command = [*self.command, '--safe-mode', '--restricted', '--settings', json.dumps(CLAUDE_SETTINGS),
                           '--tools', '', '--disallowedTools', '*', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                           '--no-session-persistence', '--permission-mode', 'dontAsk', '--max-turns', '1',
                           '--output-format', 'json', '--json-schema', schema, '-p']
            else:
                # Highest-precedence per-process settings; global files are never edited.
                settings = {
                    'billing': {'overageStrategy': 'never'},
                    'general': {'maxAttempts': 1, 'retryFetchErrors': False, 'enableAutoUpdate': False, 'enableAutoUpdateNotification': False, 'plan': {'modelRouting': False}},
                    'experimental': {'enableAgents': False, 'gemmaModelRouter': {'enabled': False}},
                    'security': {'auth': {'selectedType': 'oauth-personal', 'enforcedType': 'oauth-personal'}, 'enableConseca': False},
                    'admin': {'extensions': {'enabled': False}, 'mcp': {'enabled': False}, 'skills': {'enabled': False}},
                    'hooksConfig': {'enabled': False}, 'skills': {'enabled': False},
                    'tools': {'core': [], 'disableLLMCorrection': True},
                    'model': {'maxSessionTurns': 1}, 'useWriteTodos': False,
                    'context': {'fileName': '__NEWTON_NO_AMBIENT_CONTEXT__', 'includeDirectoryTree': False, 'includeDirectories': [], 'loadFromIncludeDirectories': False, 'discoveryMaxDirs': 0},
                    'advanced': {'ignoreLocalEnv': True}, 'telemetry': {'enabled': False}, 'privacy': {'usageStatisticsEnabled': False},
                }
                settings_path = Path(folder) / 'settings.json'
                settings_path.write_text(json.dumps(settings), encoding='utf-8')
                policy = Path(folder) / 'deny-tools.toml'
                policy.write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n', encoding='utf-8')
                env['GEMINI_CLI_SYSTEM_SETTINGS_PATH'] = str(settings_path)
                env['GEMINI_CLI_SYSTEM_DEFAULTS_PATH'] = str(settings_path)
                command = [*self.command, '--output-format', 'json', '--policy', str(policy)]
                prompt += '\nReturn ONLY a JSON object matching this JSON Schema, with no markdown fences:\n' + schema
            if self.model:
                command += ['--model', self.model]
            response = execute(command, cwd=folder, env=env, timeout=self.timeout, input_text=prompt)
        if response.returncode or len(response.stdout) > 200000:
            raise WorkerError(self.provider + '_run_failed')
        try:
            envelope = json.loads(response.stdout)
            if not isinstance(envelope, dict) or envelope.get('is_error') or envelope.get('error'):
                raise ValueError
            if self.provider == 'claude':
                value = envelope.get('structured_output')
                if value is None:
                    value = json.loads(envelope['result'])
                usage = envelope.get('usage', {})
            else:
                value = json.loads(envelope['response'])
                usage = {}  # Do not invent a cross-provider token mapping.
            result = validate_decision(value)
        except (ValueError, TypeError, KeyError):
            raise WorkerError('invalid_decision_schema') from None
        usage = usage if isinstance(usage, dict) else {}
        usage = {k: v for k, v in usage.items() if k in ('input_tokens', 'output_tokens') and type(v) is int and v >= 0}
        self.events = [{'kind': 'turn.completed', 'provider': self.provider, 'usage': usage}]
        return result
