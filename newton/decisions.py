"""Validated model decisions; one response must never start a second worker."""
import json
import re

from devtools.workers import WorkerError

INTENTS = {'discuss', 'investigate', 'plan', 'implement', 'review', 'clarify'}
FIELDS = {'intent', 'status', 'reply', 'goal', 'memory_summary', 'plan', 'criteria', 'file_edits', 'tool_requests'}


def safe_text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise WorkerError('invalid_decision_text')
    return value


def validate_decision(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise WorkerError('invalid_decision_schema')
    if not isinstance(value['intent'], str) or value['intent'] not in INTENTS or value['status'] not in ('completed', 'blocked', 'needs_clarification'):
        raise WorkerError('invalid_decision_status')
    for name, limit in (('reply', 1800), ('goal', 1000), ('memory_summary', 1500)):
        safe_text(value[name], limit)
    for field, limit in (('plan', 6), ('criteria', 10), ('file_edits', 5), ('tool_requests', 3)):
        if not isinstance(value[field], list) or len(value[field]) > limit:
            raise WorkerError('decision_size_limit')
    ids = set()
    for step in value['plan']:
        if not isinstance(step, dict) or set(step) != {'id', 'description'}:
            raise WorkerError('invalid_plan')
        if not isinstance(step['id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,24}', step['id']) or step['id'] in ids:
            raise WorkerError('invalid_plan')
        ids.add(step['id'])
        safe_text(step['description'], 500)
    ids = set()
    for criterion in value['criteria']:
        if not isinstance(criterion, dict) or set(criterion) != {'id', 'step_id', 'description', 'kind', 'path', 'text'}:
            raise WorkerError('invalid_acceptance_criterion')
        if criterion['kind'] not in ('manual', 'file_exists', 'text_contains', 'tests_pass'):
            raise WorkerError('invalid_acceptance_criterion')
        for key, limit in (('id', 24), ('step_id', 24), ('description', 500), ('path', 240), ('text', 500)):
            safe_text(criterion[key], limit)
        if not criterion['id'] or criterion['id'] in ids:
            raise WorkerError('invalid_acceptance_criterion')
        ids.add(criterion['id'])
    for edit in value['file_edits']:
        if not isinstance(edit, dict) or set(edit) != {'path', 'content'}:
            raise WorkerError('invalid_edit_fields')
        safe_text(edit['path'], 240)
        safe_text(edit['content'], 20000)
    if sum(len(e['content']) for e in value['file_edits']) > 40000:
        raise WorkerError('decision_size_limit')
    for request in value['tool_requests']:
        if not isinstance(request, dict) or set(request) != {'name', 'path', 'query', 'start_line', 'limit'}:
            raise WorkerError('invalid_tool_arguments')
        if request['name'] not in ('inventory', 'read_text', 'search', 'inspect_changes', 'run_tests'):
            raise WorkerError('unknown_local_tool')
        safe_text(request['path'], 240)
        safe_text(request['query'], 200)
        if type(request['start_line']) is not int or request['start_line'] < 1 or type(request['limit']) is not int or not 1 <= request['limit'] <= 50:
            raise WorkerError('invalid_tool_arguments')
    if value['file_edits'] and (value['intent'] != 'implement' or value['status'] != 'completed' or value['tool_requests']):
        raise WorkerError('edit_intent_conflict')
    return value


def redact(text, limit=1500):
    text = re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{8,}', '[REDACTED]', text)
    text = re.sub(r'(?i)(api[_ -]?key|password|access[_ -]?token)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', text)
    return text[:limit]


def obvious_implementation_request(message):
    # A conservative authorization gate, not the general intent classifier.
    text = message.strip().lower()
    if re.match(r'^(explain|discuss|review|investigate|plan|how|why|what|could you explain|can you explain)\b', text):
        return False
    return bool(re.match(r'^(?:(?:please|now)\s+)?(?:(?:can|could|would)\s+you\s+)?(?:implement|add|create|fix|update|change|write|build|make|refactor|start|continue|proceed)\b', text))
