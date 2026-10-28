"""Synthetic personal files only; no real profile reads and no live workers."""
import contextlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from devtools.workers import WorkerError
from newton.personal_files import PersonalFiles
from newton.conversation import ConversationSession
from newton.profile import Profile
from test_conversation import FakeWorker, decision
import test_devtools as fixtures

cli = importlib.import_module('newton.__main__')


class PersonalFileTests(unittest.TestCase):
    def test_denial_precedes_filesystem_access_and_permission_never_persists(self):
        with TemporaryDirectory() as folder:
            files = PersonalFiles(folder)
            with patch.object(Path, 'lstat', side_effect=AssertionError('must not inspect files')):
                with self.assertRaisesRegex(WorkerError, 'file_access_required'):
                    files.read(str(Path(folder) / 'book.txt'))
            files.approved = True
            self.assertFalse(PersonalFiles(folder).approved)
            files.context = [{'text': 'private excerpt'}]
            files.revoke()
            self.assertFalse(files.approved)
            self.assertEqual(files.context, [])

    def test_read_text_is_bounded_and_does_not_modify_source(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'notes.txt'
            path.write_text('first\nsecond\nthird\n', encoding='utf-8')
            files = PersonalFiles(folder); files.approved = True
            before = path.read_bytes()
            result = files.read(str(path), 2, 1)
            self.assertEqual(result['text'], 'second')
            self.assertTrue(result['truncated'])
            self.assertEqual(path.read_bytes(), before)

    def test_outside_hidden_credentials_appdata_and_network_paths_are_denied(self):
        with TemporaryDirectory() as folder, TemporaryDirectory() as outside:
            files = PersonalFiles(folder); files.approved = True
            for name in ('.codex/auth.json', '.ssh/id_rsa', 'AppData/data.txt', 'credentials.json', '.env'):
                path = Path(folder) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('do not read')
                with self.subTest(name=name), self.assertRaises(WorkerError):
                    files.read(str(path))
            path = Path(outside) / 'book.txt'; path.write_text('outside')
            for name in (str(path), '../book.txt', r'\\server\share\book.txt'):
                with self.subTest(name=name), self.assertRaises(WorkerError):
                    files.read(name)

    def test_find_names_is_explicit_bounded_and_skips_protected_trees(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'physics.txt').write_text('public')
            (root / 'AppData').mkdir()
            (root / 'AppData/physics-secret.txt').write_text('private')
            files = PersonalFiles(folder); files.approved = True
            with patch.object(Path, 'read_text', side_effect=AssertionError('filename search must not read content')):
                result = files.find('physics')
            self.assertEqual(result['paths'], [str(root / 'physics.txt')])
            self.assertLessEqual(result['entries_checked'], 1001)

    def test_symlink_is_not_followed(self):
        with TemporaryDirectory() as folder, TemporaryDirectory() as outside:
            target = Path(outside) / 'book.txt'; target.write_text('outside')
            link = Path(folder) / 'book.txt'
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest('symlink privilege unavailable')
            files = PersonalFiles(folder); files.approved = True
            with self.assertRaises(WorkerError):
                files.read(str(link))

    def test_relative_project_paths_are_not_misread_as_absolute_personal_paths(self):
        with TemporaryDirectory() as folder:
            files = PersonalFiles(folder)
            self.assertEqual(files.selected('Create src/angular_motion.py and tests/test_angular_motion.py'), [])

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'optional pypdf not installed')
    def test_pdf_selected_pages_and_ocr_reporting(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'book.pdf'; path.write_bytes(b'synthetic fixture')
            files = PersonalFiles(folder); files.approved = True
            pages = [SimpleNamespace(extract_text=lambda i=i: 'Page ' + str(i + 1)) for i in range(10)]
            with patch('pypdf.PdfReader', return_value=SimpleNamespace(is_encrypted=False, pages=pages)):
                result = files.read(str(path), 4, 50)
            self.assertEqual([p['page'] for p in result['pages']], [4, 5, 6, 7, 8])
            self.assertFalse(result['ocr_required'])
            with patch('pypdf.PdfReader', return_value=SimpleNamespace(is_encrypted=False, pages=[SimpleNamespace(extract_text=lambda: '')])):
                self.assertTrue(files.read(str(path))['ocr_required'])
            with patch('pypdf.PdfReader', return_value=SimpleNamespace(is_encrypted=True)):
                with self.assertRaisesRegex(WorkerError, 'encrypted_pdf'):
                    files.read(str(path))

    def test_missing_pdf_dependency_is_actionable_and_never_installs_it(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'book.pdf'; path.write_bytes(b'synthetic')
            files = PersonalFiles(folder); files.approved = True
            with patch.dict('sys.modules', {'pypdf': None}):
                with self.assertRaisesRegex(WorkerError, 'pdf_reader_missing'):
                    files.read(str(path))

    def test_revocation_blocks_even_cached_excerpts_from_a_model_prompt(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            book = root / 'book.txt'; book.write_text('PRIVATE_BOOK_MARKER')
            worker = FakeWorker(decision())
            session = ConversationSession(root, Profile(), worker_factory=lambda: worker)
            session.personal_files = PersonalFiles(root)
            session.personal_files.approved = True
            session.respond('read file "' + str(book) + '"')
            self.assertEqual(worker.calls, 0)
            session.respond('disable files')
            session.respond('Explain the project', approve_live=True)
            self.assertNotIn('PRIVATE_BOOK_MARKER', worker.prompts[0])
            self.assertEqual(worker.calls, 1)

    def test_explicit_file_question_uses_one_worker_with_bounded_context(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            book = root / 'book.txt'; book.write_text('BOOK_CONTENT_MARKER\n' + 'x' * 20000)
            worker = FakeWorker(decision())
            session = ConversationSession(root, Profile(context_chars=2000), worker_factory=lambda: worker)
            session.personal_files = PersonalFiles(root)
            result = session.respond('Summarize "' + str(book) + '"', approve_live=True)
            self.assertEqual(result['status'], 'file_access_blocked')
            self.assertEqual(worker.calls, 0)
            session.personal_files.approved = True
            result = session.respond('Summarize "' + str(book) + '"', approve_live=True)
            self.assertEqual(worker.calls, 1)
            self.assertIn('BOOK_CONTENT_MARKER', worker.prompts[0])
            report = json.loads(Path(result['report_file']).read_text())
            self.assertNotIn('BOOK_CONTENT_MARKER', Path(report['trace_file']).read_text())
            self.assertNotIn('BOOK_CONTENT_MARKER', session.path.read_text())
            restored = ConversationSession(root, Profile(), session_id=session.session_id)
            self.assertFalse(restored.personal_files.approved)
            self.assertEqual(restored.personal_files.context, [])

    def test_file_approval_cannot_authorize_external_writes(self):
        with TemporaryDirectory() as folder:
            root = fixtures.CoordinatorTests().make_repo(folder)
            book = root / 'book.txt'; book.write_text('original')
            worker = FakeWorker(decision('implement', file_edits=[{'path': str(book), 'content': 'changed'}]))
            session = ConversationSession(root, Profile(), worker_factory=lambda: worker)
            session.personal_files = PersonalFiles(root); session.personal_files.approved = True
            result = session.respond('Create src/example.py', approve_live=True)
            self.assertNotEqual(result['status'], 'changes_tested_review_required')
            self.assertEqual(book.read_text(), 'original')

    def test_approval_prompt_is_separate_from_live_budget_and_defaults_to_no(self):
        with TemporaryDirectory() as folder:
            session = SimpleNamespace(personal_files=PersonalFiles(folder))
            for answer, expected in (('', False), ('n', False), ('y', True)):
                with self.subTest(answer=answer), patch('builtins.input', return_value=answer) as asked, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.approve_files(session), expected)
                    self.assertIn('Do you want to allow Newton', asked.call_args.args[0])

    def test_confirmed_project_switch_does_not_edit_source_or_launch_workers(self):
        with TemporaryDirectory() as folder:
            home = Path(folder)
            first = home / 'first'; first.mkdir()
            second = home / 'second'; second.mkdir()
            fixtures.CoordinatorTests().make_repo(first)
            fixtures.CoordinatorTests().make_repo(second)
            output = io.StringIO()
            with patch.object(cli, 'PROJECT', first), patch.object(cli, 'load_profile', return_value=Profile()), \
                 patch('newton.personal_files.Path.home', return_value=home), patch('sys.argv', ['newton']), \
                 patch('builtins.input', side_effect=['n', 'y', 'use project "' + str(second) + '"', 'y', 'n', 'n', 'quit']), \
                 patch('newton.conversation.ConversationWorker') as worker, contextlib.redirect_stdout(output):
                cli.main()
            worker.assert_not_called()
            self.assertTrue((second / 'runs/newton/latest.json').exists())
            self.assertEqual((second / 'src/value.py').read_text(), 'VALUE = 1\n')

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'optional pypdf not installed')
    def test_real_pdf_reader_extracts_a_synthetic_page(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic_book.pdf'
            writer = PdfWriter()
            page = writer.add_blank_page(width=300, height=200)
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            content = DecodedStreamObject()
            content.set_data(b'BT /F1 12 Tf 20 100 Td (Synthetic physics chapter) Tj ET')
            page[NameObject('/Contents')] = writer._add_object(content)
            with path.open('wb') as stream:
                writer.write(stream)
            files = PersonalFiles(folder); files.approved = True
            result = files.read(str(path))
            self.assertEqual(result['pages'][0]['page'], 1)
            self.assertIn('Synthetic physics chapter', result['pages'][0]['text'])

    def test_worker_tool_overrides_preserve_a_multi_argument_cli_launcher(self):
        import subprocess
        from newton.worker import ConversationWorker
        output = '\n'.join([json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(decision())}}), '{"type":"turn.completed"}'])
        with patch('newton.worker.execute', return_value=subprocess.CompletedProcess([], 0, output, '')) as execute:
            ConversationWorker(command=['node', 'codex.js']).decide('task', Path('.'))
        self.assertEqual(execute.call_args.args[0][:2], ['node', 'codex.js'])
        self.assertIn('features.shell_tool=false', execute.call_args.args[0])
