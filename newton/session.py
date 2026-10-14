"""Persistent workspace progress; conversation context stays in memory."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import uuid

from devtools.coordinator import coordinate, git, run_tests, session_checkout
from devtools.workers import CodexWorker, MockWorker, WorkerError
from .profile import Profile


class Session:
    def __init__(self, root: Path, profile: Profile, *, session_id=None, worker_factory=None):
        self.root = root.resolve()
        self.profile = profile
        self.session_id = session_id or uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', self.session_id):
            raise ValueError('invalid Newton session ID')
        self.folder = self.root / 'runs' / 'newton' / self.session_id
        if self.folder.is_symlink() or not self.folder.resolve().is_relative_to(self.root / 'runs' / 'newton'):
            raise ValueError('invalid Newton session path')
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_file = self.folder / 'session.json'
        self.workspace_run = None
        self.reports = []
        self.history = []
        self.worker_factory = worker_factory
        if session_id:
            if not self.state_file.is_file():
                raise ValueError('Newton session not found')
            state = json.loads(self.state_file.read_text(encoding='utf-8'))
            if state.get('project_root') != str(self.root) or state.get('session_id') != self.session_id:
                raise ValueError('session belongs to a different project')
            self.workspace_run = state.get('workspace_run')
            self.reports = state.get('reports', [])
            if not isinstance(self.reports, list) or len(self.reports) > 20:
                raise ValueError('invalid session reports')
            if self.workspace_run:
                session_checkout(self.root, self.workspace_run)
        else:
            self._save()

    def _save(self):
        state = {'session_id': self.session_id, 'project_root': str(self.root),
                 'workspace_run': self.workspace_run, 'reports': self.reports}
        temporary = self.folder / 'session.tmp'
        temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temporary.replace(self.state_file)

    @contextmanager
    def _lock(self):
        path = self.folder / 'active.lock'
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise WorkerError('session_already_active') from None
        try:
            os.close(fd)
            yield
        finally:
            path.unlink(missing_ok=True)

    def worker(self, read_only=False):
        if self.worker_factory:
            return self.worker_factory(read_only)
        return MockWorker() if self.profile.worker == 'mock' else CodexWorker(timeout=self.profile.worker_timeout, read_only=read_only)

    def run(self, task, *, read_only=False):
        if len(self.reports) >= self.profile.max_tasks_per_session:
            raise WorkerError('session_task_limit: start /new to approve a fresh allowance budget')
        with self._lock():
            context = json.dumps(self.history[-2:], ensure_ascii=False)[:10000] if self.history else ''
            report = coordinate(self.root, task, self.worker(read_only),
                max_repairs=0 if read_only else self.profile.max_repairs,
                workspace_run=self.workspace_run, extra_instructions=self.profile.instructions,
                conversation_context='Previous session exchanges (context only):\n' + context)
            self.workspace_run = report['workspace_run']
            self.reports.append({'run_id': report['run_id'], 'status': report['status'],
                                 'tests_run': report['tests_run'], 'tests_passed': report['tests_passed']})
            self.history.append({'task': task[:2000], 'reply': report['worker_reply'][:2000]})
            self._save()
        return report

    def workspace(self):
        return session_checkout(self.root, self.workspace_run)[0] if self.workspace_run else self.root

    def status(self):
        root = self.workspace()
        return {'name': self.profile.name, 'session_id': self.session_id,
                'tasks_used': len(self.reports), 'task_limit': self.profile.max_tasks_per_session,
                'workspace': str(root), 'changed_files': git(root, 'status', '--porcelain').splitlines(),
                'resume': f'python -m newton --resume {self.session_id}'}
