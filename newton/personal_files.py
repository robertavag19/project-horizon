"""Launch-scoped, read-only personal files. No automatic crawl or external writes."""
from pathlib import Path
from collections import deque
import os
import re
import stat
import time

from devtools.workers import WorkerError
from .decisions import redact

TEXT = {'.txt', '.md', '.rst', '.py', '.js', '.ts', '.html', '.css', '.csv', '.json', '.toml', '.yaml', '.yml'}
SKIP = {'appdata', 'node_modules', '__pycache__', 'venv', 'env', 'runs', '$recycle.bin', 'system volume information'}


class PersonalFiles:
    def __init__(self, root=None):
        self.root = Path(root or Path.home()).resolve()
        self.approved = False
        self.context = []

    def revoke(self):
        self.approved = False
        self.context = []

    def path(self, name, directory=False):
        if not self.approved:
            raise WorkerError('file_access_required: use enable files and confirm access for this launch')
        name = str(name).strip().strip('"').strip("'")
        if len(name) > 4096 or '\0' in name:
            raise WorkerError('personal_path_denied')
        if name.startswith(('\\\\', '//')) or ':' in name[2:]:
            raise WorkerError('personal_path_denied')
        target = Path(name).expanduser()
        if not target.is_absolute():
            target = self.root / target
        if '..' in target.parts:
            raise WorkerError('personal_path_denied')
        try:
            relative = target.relative_to(self.root)
        except ValueError:
            raise WorkerError('outside_user_folder') from None
        if any(part.startswith('.') or part.casefold() in SKIP for part in relative.parts):
            raise WorkerError('protected_personal_path')
        if re.search(r'(?i)(credential|password|id_rsa|auth\.json|secret)', target.name):
            raise WorkerError('protected_personal_path')
        for ancestor in [self.root, *[self.root.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1)]]:
            try:
                info = ancestor.lstat()
            except OSError:
                raise WorkerError('personal_file_unavailable') from None
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise WorkerError('personal_link_denied')
        resolved = target.resolve()
        if not resolved.is_relative_to(self.root):
            raise WorkerError('outside_user_folder')
        if directory:
            if not resolved.is_dir():
                raise WorkerError('personal_folder_required')
        elif resolved.suffix.lower() not in TEXT | {'.pdf'} or not resolved.is_file():
            raise WorkerError('unsupported_personal_file')
        return resolved

    def find(self, query='', folder='', limit=20):
        if not isinstance(query, str) or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 50:
            raise WorkerError('invalid_file_search')
        base = self.path(folder or str(self.root), directory=True)
        hits, count, truncated = [], 0, False
        deadline = time.monotonic() + 3
        queue = deque([(base, 0)])
        while queue:
            current, depth = queue.popleft()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        count += 1
                        if count > 1000 or time.monotonic() > deadline:
                            truncated = True
                            break
                        if entry.name.startswith('.') or entry.name.casefold() in SKIP:
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if depth < 8:
                                    child = self.path(entry.path, directory=True)
                                    queue.append((child, depth + 1))
                                continue
                            if query.casefold() not in entry.name.casefold() or Path(entry.name).suffix.lower() not in TEXT | {'.pdf'}:
                                continue
                            path = self.path(entry.path)
                        except (WorkerError, OSError):
                            continue
                        hits.append(str(path))
                        if len(hits) >= limit:
                            truncated = True
                            break
            except OSError:
                continue
            if truncated:
                break
        return {'paths': hits, 'scan_truncated': truncated, 'entries_checked': count}

    def read(self, name, start=1, limit=3):
        if type(start) is not int or type(limit) is not int or not 1 <= start <= 100000 or not 1 <= limit <= 50:
            raise WorkerError('invalid_file_range')
        path = self.path(name)
        size = path.stat().st_size
        if size > (50_000_000 if path.suffix.lower() == '.pdf' else 2_000_000):
            raise WorkerError('personal_file_too_large')
        if path.suffix.lower() == '.pdf':
            try:
                from pypdf import PdfReader
            except ImportError:
                raise WorkerError('pdf_reader_missing: install locally with python -m pip install pypdf') from None
            try:
                with path.open('rb') as stream:
                    reader = PdfReader(stream)
                    if reader.is_encrypted:
                        raise WorkerError('encrypted_pdf_not_supported')
                    stop = min(start - 1 + min(limit, 5), len(reader.pages))
                    if start > len(reader.pages):
                        raise WorkerError('pdf_page_out_of_range')
                    labels = getattr(reader, 'page_labels', None)
                    pages = []
                    remaining = 12000
                    for index in range(start - 1, stop):
                        content = (reader.pages[index].extract_text() or '')[:remaining]
                        pages.append({'page': index + 1, 'page_label': labels[index] if labels and index < len(labels) else None, 'pdf_page_index': index, 'text': redact(content, len(content))})
                        remaining -= len(content)
                        if remaining <= 0:
                            break
                    result = {'path': str(path), 'pages': pages, 'total_pages': len(reader.pages),
                              'truncated': True, 'ocr_required': not any(p['text'].strip() for p in pages)}
            except WorkerError:
                raise
            except Exception:
                raise WorkerError('pdf_text_extraction_failed') from None
        else:
            try:
                lines = path.read_text(encoding='utf-8-sig').splitlines()
            except (OSError, UnicodeError):
                raise WorkerError('personal_text_read_failed') from None
            content = '\n'.join(lines[start - 1:start - 1 + min(limit, 50)])[:12000]
            result = {'path': str(path), 'start_line': start, 'text': redact(content, len(content)),
                      'truncated': start > 1 or len(lines) > limit or len(content) >= 12000}
        self.context = [result]  # One selected excerpt; never a durable personal-file index.
        return result

    def selected(self, message):
        # Explicit paths can be read in the same bounded model invocation as the question.
        pattern = r'(?<![\w/\\])(?:[A-Za-z]:[\\/]|/)[^"\r\n<>|?]*?\.(?:pdf|txt|md|py|csv|json|rst)\b'
        names = list(dict.fromkeys(re.findall(pattern, message)))
        if names:
            match = re.search(r'\bpages?\s+(\d+)(?:\s*[-–]\s*(\d+))?', message, re.I)
            start = int(match[1]) if match else 1
            limit = min(5, max(1, int(match[2] or match[1]) - start + 1)) if match else 3
            self.read(names[0], start, limit if Path(names[0]).suffix.lower() == '.pdf' else 50)
        return self.context if self.approved else []
