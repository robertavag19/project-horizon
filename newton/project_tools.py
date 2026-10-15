"""Bounded local project tools. No arbitrary commands or model calls."""
import hashlib
import os
from pathlib import Path
import re

from devtools.coordinator import git, run_tests
from devtools.workers import WorkerError
from .decisions import redact

ROOT_FILES = {'README.md', 'AGENTS.md', 'pyproject.toml', 'newton.toml'}
DIRECTORIES = {'src', 'tests', 'docs', 'examples', 'newton', 'devtools'}
SUFFIXES = {'.py', '.md', '.txt', '.toml', '.json', '.jsonl'}


class ProjectTools:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, name):
        if not isinstance(name, str) or not name or len(name) > 240 or '\\' in name or ':' in name:
            raise WorkerError('invalid_project_path')
        relative = Path(name)
        if relative.is_absolute() or any(p.startswith('.') or p in ('node_modules', '__pycache__', 'runs') for p in relative.parts):
            raise WorkerError('invalid_project_path')
        if name not in ROOT_FILES and (not relative.parts or relative.parts[0] not in DIRECTORIES):
            raise WorkerError('invalid_project_path')
        if re.search(r'(?i)(secret|credential|password|private|id_rsa|auth\.json)', name):
            raise WorkerError('sensitive_project_path')
        target = self.root / relative
        if target.suffix not in SUFFIXES or target.is_symlink() or not target.resolve().is_relative_to(self.root):
            raise WorkerError('invalid_project_path')
        return target

    def inventory(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise WorkerError('invalid_tool_limit')
        paths = []
        candidates = [self.root / p for p in sorted(ROOT_FILES)]
        truncated = False
        for directory in sorted(DIRECTORIES):
            base = self.root / directory
            if not base.is_dir() or base.is_symlink():
                continue
            for current, folders, files in os.walk(base, followlinks=False):
                folders[:] = sorted(f for f in folders if not f.startswith('.') and f not in ('node_modules', '__pycache__', 'runs') and not (Path(current) / f).is_symlink())
                candidates.extend(Path(current) / f for f in sorted(files))
                if len(candidates) >= 1000:
                    candidates = candidates[:1000]
                    truncated = True
                    break
            if truncated:
                break
        omitted = 0
        for candidate in candidates:
            try:
                name = candidate.relative_to(self.root).as_posix()
                target = self.path(name)
                if not target.is_file():
                    continue
                if len(paths) < limit:
                    paths.append(name)
                else:
                    omitted += 1
            except WorkerError:
                continue
        return {'paths': paths, 'additional_file_count': omitted, 'scan_truncated': truncated}

    def read(self, name, start_line=1, limit=60):
        if type(start_line) is not int or type(limit) is not int or not 1 <= start_line <= 100000 or not 1 <= limit <= 200:
            raise WorkerError('invalid_line_range')
        path = self.path(name)
        if not path.is_file() or path.stat().st_size > 200_000:
            raise WorkerError('file_missing_or_oversized')
        text = path.read_text(encoding='utf-8-sig')
        lines = text.splitlines()
        selected = '\n'.join(lines[start_line - 1:start_line - 1 + limit])
        return {'path': name, 'start_line': start_line, 'text': selected[:8000],
                'truncated': len(selected) > 8000 or start_line > 1 or len(lines) > limit}

    def search(self, query, limit=20):
        if not isinstance(query, str) or not 1 <= len(query) <= 200 or type(limit) is not int or not 1 <= limit <= 50:
            raise WorkerError('invalid_search_arguments')
        matches = []
        for name in self.inventory(200)['paths']:
            path = self.path(name)
            if path.stat().st_size > 100_000:
                continue
            for line_number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append({'path': name, 'line': line_number, 'text': line[:240]})
                    if len(matches) == limit:
                        return matches
        return matches

    def changes(self):
        # Names are shown separately because ordinary git diff omits new files.
        new_files = []
        names = git(self.root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')
        for name in names:
            if not name or len(new_files) >= 3:
                continue
            try:
                result = self.read(name, 1, 40)
                new_files.append({'path': name, 'preview': result['text'][:1000], 'truncated': result['truncated'] or len(result['text']) > 1000})
            except (WorkerError, UnicodeError, OSError):
                continue
        return {'status': git(self.root, 'status', '--short'), 'diff': git(self.root, 'diff')[:12000], 'new_files': new_files}

    def dispatch(self, request, *, test_timeout=90):
        if not isinstance(request, dict) or set(request) != {'name', 'path', 'query', 'start_line', 'limit'}:
            raise WorkerError('invalid_tool_arguments')
        name = request['name']
        if not isinstance(request['path'], str) or not isinstance(request['query'], str):
            raise WorkerError('invalid_tool_arguments')
        if type(request['limit']) is not int or not 1 <= request['limit'] <= 50 or type(request['start_line']) is not int or request['start_line'] < 1:
            raise WorkerError('invalid_tool_arguments')
        if name == 'inventory':
            return self.inventory(request['limit'])
        if name == 'read_text':
            return self.read(request['path'], request['start_line'], request['limit'])
        if name == 'search':
            return self.search(request['query'], request['limit'])
        if name == 'inspect_changes':
            return self.changes()
        if name == 'run_tests':
            checked = run_tests(self.root, timeout=test_timeout)
            return {'passed': checked.passed, 'count': checked.count, 'output': checked.output}
        raise WorkerError('unknown_local_tool')

    def context(self, task, *, preferred=(), max_chars=12000):
        """Choose relevant full files where possible; mark every excerpt explicitly."""
        inventory = self.inventory(120)
        words = set(re.findall(r'[a-zA-Z_]{3,}', task.casefold()))
        ranked = []
        for name in inventory['paths']:
            path = self.path(name)
            if path.stat().st_size > 100_000:
                continue
            text = path.read_text(encoding='utf-8-sig')
            if redact(text, len(text)) != text:
                continue
            score = 100 if name in preferred else 0
            score += 40 if name.casefold() in task.casefold() else 0
            score += 3 * len(words & set(re.findall(r'[a-zA-Z_]{3,}', name.casefold())))
            score += len(words & set(re.findall(r'[a-zA-Z_]{3,}', text[:10000].casefold())))
            score += 8 if name == 'AGENTS.md' else 0
            if name == 'README.md':
                score += 2
            ranked.append((score, name, text))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        files, fingerprints, omitted = [], {}, []
        remaining = max_chars
        for score, name, text in ranked:
            if remaining < 200 or len(files) >= 5:
                omitted.append(name)
                continue
            available = min(remaining, 6000)
            complete = len(text) <= available
            content = text if complete else text[:available]
            files.append({'path': name, 'content': content, 'complete': complete})
            remaining -= len(content)
            if complete:
                fingerprints[name] = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return {'inventory': inventory, 'files': files, 'omitted': omitted,
                'context_chars': max_chars - remaining}, fingerprints

    def verify_edit_context(self, edits, fingerprints):
        for edit in edits:
            path = self.path(edit['path'])
            if path.exists():
                if edit['path'] not in fingerprints:
                    raise WorkerError('full_file_context_required')
                current = path.read_text(encoding='utf-8-sig')
                if hashlib.sha256(current.encode('utf-8')).hexdigest() != fingerprints[edit['path']]:
                    raise WorkerError('file_changed_since_snapshot')
