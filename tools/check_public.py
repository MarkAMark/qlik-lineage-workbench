"""Fail closed when building a public source tree. No private marker list required."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ROOT_FILES = {
    '.gitignore', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'README.zh-CN.md',
    'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'index.html', 'package.json',
    'package-lock.json', 'requirements.txt', 'tsconfig.json', 'tsconfig.node.json',
    'vite.config.ts', 'Setup.ps1', 'Start-Local.cmd', 'Start-Local.ps1',
}
SOURCE_DIRS = {'backend', 'src', 'public', 'tests', 'tools', 'docs', 'packaging', '.github'}
SOURCE_EXT = {'.py', '.tsx', '.ts', '.css', '.svg', '.mjs', '.md', '.yml', '.yaml', '.ps1', '.cmd'}
EXPORT_NAMES = {'app-properties.json', 'variables.json', 'dimensions.json', 'measures.json'}
PATTERNS = [
    (re.compile(r'[A-Za-z]:[\\/]Users[\\/][^\s"\'<>]+'), 'personal absolute path'),
    (re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), 'private key'),
    (re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'), 'AWS credential'),
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'), 'GitHub token'),
    (re.compile(r'https?://[^\s/@:]+:[^\s/@]+@'), 'URL credential'),
]


def source_files(root: Path = PROJECT) -> list[Path]:
    files = [root / name for name in sorted(ROOT_FILES) if (root / name).is_file()]
    for folder in sorted(SOURCE_DIRS):
        for path in sorted((root / folder).rglob('*')):
            if '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
                continue
            if path.is_file():
                files.append(path)
    placeholder = root / 'metadata/apps/.gitkeep'
    if placeholder.is_file():
        files.append(placeholder)
    return files


def check(root: Path = PROJECT, *, check_git: bool = True) -> list[Path]:
    errors = []
    files = source_files(root)
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in path.parents if p != root.parent):
            errors.append(f'{relative}: linked source is not allowed')
        license_data = relative.startswith('docs/licenses/') and (path.suffix in {'.txt', '.json'} or
            path.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'THIRD-PARTY-LICENSE', 'THIRDPARTYNOTICE')))
        if path.name not in ROOT_FILES and relative != 'metadata/apps/.gitkeep' and path.suffix not in SOURCE_EXT and not license_data:
            errors.append(f'{relative}: unexpected source file type')
        if path.name in EXPORT_NAMES or path.suffix.lower() in {'.qvs', '.qvf', '.qvd', '.qvx'}:
            errors.append(f'{relative}: exported metadata is forbidden')
        try:
            content = path.read_text(encoding='utf-8-sig')
        except (UnicodeError, OSError):
            errors.append(f'{relative}: unreadable text file')
            continue
        for regex, description in PATTERNS:
            if regex.search(content):
                errors.append(f'{relative}: {description}')
    for path in (root / 'metadata').rglob('*'):
        if path.is_file() and path.relative_to(root).as_posix() != 'metadata/apps/.gitkeep':
            errors.append('metadata payload exists; public builds require an empty metadata directory')
    if check_git and (root / '.git').is_dir():
        tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True).stdout.decode('utf-8').split('\0')
        allowed = {p.relative_to(root).as_posix() for p in files}
        for name in tracked:
            if name and name not in allowed:
                errors.append(f'{name}: tracked file is outside the public source allowlist')
    if errors:
        raise ValueError('\n'.join(errors))
    return files


if __name__ == '__main__':
    try:
        files = check()
        print(f'PASS: {len(files)} public source files checked; metadata payload = 0 files.')
    except (ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))
