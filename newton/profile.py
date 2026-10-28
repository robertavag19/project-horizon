"""Validated personal preferences, not model training or credentials."""
from dataclasses import dataclass
from pathlib import Path
import tomllib
from .providers import PROVIDERS, valid_model
from .teaching import STYLES


@dataclass(frozen=True)
class Profile:
    name: str = 'Newton'
    worker: str = 'codex'
    model: str = ''
    response_style: str = 'teacher'
    max_repairs: int = 0
    worker_timeout: int = 90
    max_tasks_per_session: int = 5
    max_live_invocations: int = 50
    context_chars: int = 12000
    reply_chars: int = 1800
    context_files: int = 5
    context_file_chars: int = 6000
    turn_timeout: int = 180
    instructions: str = 'You are Newton, a personal technical teacher and project supervisor. Follow the current user goal. Never use API-key billing.'

    def __post_init__(self):
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 40:
            raise ValueError('invalid agent name')
        if self.worker not in (*PROVIDERS, 'mock'):
            raise ValueError('unsupported provider')
        if not valid_model(self.model) or not isinstance(self.response_style, str) or self.response_style not in STYLES:
            raise ValueError('invalid model or response style')
        for value, low, high in ((self.max_repairs, 0, 2), (self.worker_timeout, 1, 600), (self.max_tasks_per_session, 1, 20)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('invalid Newton limit')
        limits = ((self.max_live_invocations, 1, 1000), (self.context_chars, 2000, 64000),
                  (self.reply_chars, 256, 12000), (self.context_files, 1, 10),
                  (self.context_file_chars, 1000, 20000), (self.turn_timeout, 10, 900))
        for value, low, high in limits:
            if type(value) is not int or not low <= value <= high:
                raise ValueError('invalid Economy limit')
        if not isinstance(self.instructions, str) or len(self.instructions) > 4000:
            raise ValueError('invalid profile instructions')


def load_profile(root: Path):
    path = root / 'newton.toml'
    if not path.is_file():
        return Profile()
    values = tomllib.loads(path.read_text(encoding='utf-8-sig'))
    if set(values) != {'agent'} or not isinstance(values['agent'], dict):
        raise ValueError('newton.toml must contain only an [agent] table')
    try:
        return Profile(**values['agent'])
    except TypeError:
        raise ValueError('unknown Newton profile setting') from None
