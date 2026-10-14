"""Validated personal preferences, not model training or credentials."""
from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Profile:
    name: str = 'Newton'
    worker: str = 'codex'
    max_repairs: int = 1
    worker_timeout: int = 180
    max_tasks_per_session: int = 5
    instructions: str = 'You are Newton. Preserve Horizon Reliability as the primary project. Never call paid APIs.'

    def __post_init__(self):
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 40:
            raise ValueError('invalid agent name')
        if self.worker not in ('codex', 'mock'):
            raise ValueError('only codex and mock are connected')
        for value, low, high in ((self.max_repairs, 0, 2), (self.worker_timeout, 1, 600), (self.max_tasks_per_session, 1, 20)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('invalid Newton limit')
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
