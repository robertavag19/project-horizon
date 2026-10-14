"""Reliability events contain metadata only, never prompts or passage text."""
from datetime import datetime, timezone
import json
from pathlib import Path


class Recorder:
    def __init__(self, path: Path, run_id: str, task_id: str):
        self.path = path
        self.run_id = run_id
        self.task_id = task_id
        self.sequence = 0
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event_type: str, step_index: int, **metadata) -> None:
        self.sequence += 1
        event = {
            'schema_version': 1, 'run_id': self.run_id, 'task_id': self.task_id,
            'event_sequence': self.sequence, 'step_index': step_index,
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'event_type': event_type, 'metadata': metadata,
        }
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
