"""Local, bounded authorization context. Model summaries cannot grant permission."""
import re

ACTIONS = r'(?:create|write|add|fix|update|change|implement|build|make|refactor)'
RESTRICTED = r'\b(?:delete|remove|erase|wipe|overwrite|deploy|publish|upload|purchase|buy|email|merge|push)\b'


def normal(message):
    return ' '.join(message.strip().lower().replace('\u2019', "'").split())


def action_matches(text):
    frames = [
        rf'(?:^|[.!?,;:]\s*)(?:(?:hey|hi)\s+)?(?:newton[, ]+)?(?:(?:please|now|okay|ok|then)\s+)*{ACTIONS}\b',
        rf'\b(?:can|could|would|will)\s+(?:you|u)\s+(?:please\s+)?{ACTIONS}\b',
        rf'\b(?:i|we)\s+(?:want|need|would like)(?:\s+you)?\s+to\s+{ACTIONS}\b',
        rf"\b(?:i'd|we'd)\s+like(?:\s+you)?\s+to\s+{ACTIONS}\b",
        rf"\b(?:please|go ahead and|let's|lets)\s+{ACTIONS}\b",
        r'\b(?:i|we)\s+(?:need|want|would like)\s+(?:a|an|some|new)\s+(?:new\s+)?(?:python\s+)?(?:file|function|test|module)\b',
    ]
    return [match for pattern in frames if (match := re.search(pattern, text))]


def discussion_only(message):
    text = normal(message)
    if re.search(r"\b(?:do not|don't|dont|never)\s+(?:edit|change|write|create|implement|modify)|\bwithout\s+(?:editing|changing|writing|creating)|\bnot yet\b", text):
        return True
    if re.match(r'^(?:how|why|what|would it|should i|should we)\b', text):
        return True
    discussion = re.search(r'\b(?:explain|describe|discuss|review|investigate|plan|tell me)\b', text)
    actions = action_matches(text)
    # "Create ... and explain it" still requests edits. "Explain how to create" does not.
    return bool(discussion and (not actions or discussion.start() < min(m.start() for m in actions)))


def explicit_request(message):
    text = normal(message)
    if discussion_only(message):
        return False
    if re.search(RESTRICTED, text):
        return False
    return bool(action_matches(text))


def targets(message):
    return list(dict.fromkeys(re.findall(r'\b(?:src|tests|docs|examples)/[A-Za-z0-9_./-]+\.(?:py|md|txt|jsonl?)\b', message)))[:10]


def continuation(message):
    text = normal(message).rstrip('.!?')
    return bool(re.match(r'^(?:please\s+)?(?:continue|proceed|start with the smallest)\b', text)
                or re.fullmatch(r'(?:please )?(?:implement|fix|create|write|add|do|make) (?:it|this|that|the first step|the next step|the first small step)(?: now)?', text)
                or text in ('add tests', 'fix the tests', 'run the next step'))


def confirmation(message):
    return normal(message).rstrip('.!') in ('yes', 'y', 'yes please', 'okay', 'ok', 'go ahead', 'do it')


def resolve(message, state, read_only=False):
    pending = state.get('pending_clarification')
    explicit = explicit_request(message)
    named = targets(message)
    current = state.get('task')
    followup = False
    inherited = False
    if pending and not discussion_only(message) and not explicit:
        # Questions/new subjects and destructive requests are not answers to a clarification.
        text = normal(message)
        followup = not bool(re.match(r'^(?:what|how|why|who|where|when|new task)\b', text)
                           or re.search(RESTRICTED, text) or re.search(r'\b(?:cancel|forget)\b', text))
        if named and pending['targets'] and not set(named).issubset(pending['targets']):
            followup = False
        if confirmation(message):
            followup = pending['yes_allowed']
        inherited = followup and pending['authorized']
    continuing = continuation(message) and not (named and current and not set(named).issubset(current['targets']))
    if explicit and pending and (continuing or (named and set(named) & set(pending['targets']))):
        followup = True
    authorized = (explicit or inherited or (continuing and bool(current or state['plan']))) and not read_only and not discussion_only(message) and not re.search(RESTRICTED, normal(message))
    return {'authorized': bool(authorized), 'new_task': bool(explicit and not followup and not continuing),
            'followup': followup, 'continuing': continuing, 'targets': named,
            'ambiguous_yes': confirmation(message) and not (followup and inherited),
            'request': pending['request'] if followup else message}
