import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from devtools.workers import MockWorker, WorkerError, WorkerResult, apply_edits
from newton.profile import Profile, load_profile
from newton.session import Session
import test_devtools as fixtures


class ProfileTests(unittest.TestCase):
    def test_personal_defaults(self):
        self.assertEqual(Profile().name, 'Newton')
        self.assertEqual(Profile().worker, 'codex')
        self.assertEqual(Profile().max_tasks_per_session, 5)

    def test_custom_profile(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'newton.toml').write_text('[agent]\nname="Newton"\nworker="mock"\nmax_repairs=0\n')
            profile = load_profile(root)
        self.assertEqual(profile.worker, 'mock')
        self.assertEqual(profile.max_repairs, 0)

    def test_unknown_connection_or_bad_limit_rejected(self):
        for values in ({'worker': 'claude'}, {'max_repairs': True}, {'max_tasks_per_session': 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Profile(**values)

    def test_unknown_config_field_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'newton.toml').write_text('[agent]\napi_key="not-allowed"\n')
            with self.assertRaises(ValueError):
                load_profile(root)


class SessionTests(unittest.TestCase):
    def fixture(self, folder):
        return fixtures.CoordinatorTests().make_repo(folder)

    def test_followup_reuses_pending_changes_and_in_memory_history(self):
        class Worker:
            def __init__(self):
                self.calls = 0
                self.observed = ''
            def preflight(self, root):
                pass
            def run(self, prompt, root):
                self.calls += 1
                if self.calls == 1:
                    (root / 'src/value.py').write_text('VALUE = 2\n')
                else:
                    self.observed = (root / 'src/value.py').read_text()
                    self.prompt = prompt
                return WorkerResult(True, [], 'Task handled')
        worker = Worker()
        with TemporaryDirectory() as folder:
            root = self.fixture(folder)
            session = Session(root, Profile(worker='mock'), worker_factory=lambda read_only: worker)
            first = session.run('Fix value. MEMORY_ONLY_MARKER')
            second = session.run('Check the previous change')
            self.assertEqual(first['worktree'], second['worktree'])
            self.assertEqual(worker.observed, 'VALUE = 2\n')
            self.assertIn('MEMORY_ONLY_MARKER', worker.prompt)
            self.assertNotIn('MEMORY_ONLY_MARKER', session.state_file.read_text())
            self.assertEqual((root / 'src/value.py').read_text(), 'VALUE = 1\n')
            restored = Session(root, Profile(worker='mock'), session_id=session.session_id)
            self.assertEqual(restored.workspace(), session.workspace())
            self.assertEqual(len(restored.reports), 2)
            self.assertEqual(restored.history, [])

    def test_session_task_limit_before_new_worker_call(self):
        with TemporaryDirectory() as folder:
            root = self.fixture(folder)
            session = Session(root, Profile(worker='mock', max_tasks_per_session=1, max_repairs=0))
            session.run('One task')
            with self.assertRaises(WorkerError) as error:
                session.run('Second task')
        self.assertIn('session_task_limit', str(error.exception))

    def test_traversal_session_id_rejected(self):
        with TemporaryDirectory() as folder, self.assertRaises(ValueError):
            Session(Path(folder), Profile(), session_id='../outside')

    def test_missing_session_rejected(self):
        with TemporaryDirectory() as folder, self.assertRaises(ValueError):
            Session(Path(folder), Profile(), session_id='a' * 32)

    def test_concurrent_session_lock_refuses_second_run(self):
        with TemporaryDirectory() as folder:
            session = Session(self.fixture(folder), Profile(worker='mock'))
            (session.folder / 'active.lock').write_text('active')
            with self.assertRaises(WorkerError) as error:
                session.run('Task')
        self.assertEqual(str(error.exception), 'session_already_active')

    def test_unregistered_workspace_rejected(self):
        from devtools.coordinator import session_checkout
        with TemporaryDirectory() as folder:
            root = self.fixture(folder)
            with self.assertRaises(WorkerError):
                session_checkout(root, 'a' * 32)


class NewTestRepairTests(unittest.TestCase):
    def test_new_test_can_be_repaired_without_weakening_committed_tests(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'tests').mkdir()
            (root / 'tests/test_original.py').write_text('original')
            protected = {'tests/test_original.py'}
            apply_edits(root, [{'path': 'tests/test_new.py', 'content': 'first'}], protected_tests=protected)
            apply_edits(root, [{'path': 'tests/test_new.py', 'content': 'corrected'}], protected_tests=protected)
            self.assertEqual((root / 'tests/test_new.py').read_text(), 'corrected')
            with self.assertRaises(WorkerError):
                apply_edits(root, [{'path': 'tests/TEST_ORIGINAL.py', 'content': 'changed'}], protected_tests=protected)
