"""CPython and third-party license bundling helpers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OMIT_CODE_DIRS = {'__pycache__', '.git', 'node_modules'}
OMIT_STDLIB_DIRS = {'__pycache__', 'test', 'tests', 'site-packages', 'ensurepip', 'idlelib', 'tkinter', 'turtledemo'}
OMIT_RUNTIME_FILES = {'pythonw.exe', '_tkinter.pyd', 'tcl90.dll', 'tcl9tk90.dll', 'libtommath.dll'}
# The web service does not use Python's GUI or sampling-profiler assets.
OMIT_STDLIB_DIRS |= {'profiling'}


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_tree(source: Path, target: Path, omit: set[str] | None = None) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if omit and any(part in omit for part in relative.parts):
            continue
        if path.is_symlink() or path.is_junction():
            raise ValueError(f'Linked files must be resolved explicitly before packaging: {path}')
        if not path.is_file() or (omit is not None and path.suffix in {'.pyc', '.pyo'}):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def copy_runtime(destination: Path) -> dict:
    base = Path(sys.base_prefix)
    if sys.platform != 'win32' or platform.machine().upper() not in {'AMD64', 'X86_64'}:
        raise RuntimeError('Build this distribution with a Windows x64 CPython installation.')
    if sys.version_info < (3, 12):
        raise RuntimeError('The packaging tool requires Python 3.12 or newer.')
    notice_info = json.loads((PROJECT / 'docs/licenses/runtime-provenance.json').read_text(encoding='utf-8'))
    if platform.python_version() != notice_info['pythonVersion'] or digest(base / 'LICENSE.txt') != notice_info['pythonLicenseSha256']:
        raise RuntimeError('Runtime changed: review and refresh its component notices before packaging.')
    destination.mkdir()
    for pattern in ('python.exe', 'pythonw.exe', '*.dll', 'LICENSE*'):
        for path in base.glob(pattern):
            if path.is_file() and path.name not in OMIT_RUNTIME_FILES:
                shutil.copy2(path, destination / path.name)
    if not (destination / 'python.exe').is_file() or not (destination / 'LICENSE.txt').is_file():
        raise RuntimeError('The Python runtime or its redistribution license was not found.')
    copy_tree(base / 'Lib', destination / 'Lib', OMIT_STDLIB_DIRS)
    copy_tree(base / 'DLLs', destination / 'DLLs', OMIT_STDLIB_DIRS | OMIT_RUNTIME_FILES)
    # This file disables registry, user-site and environment path discovery.
    (destination / f'python{sys.version_info.major}{sys.version_info.minor}._pth').write_text('.\nDLLs\nLib\n', encoding='ascii')
    return {'implementation': 'CPython', 'version': platform.python_version(), 'architecture': 'Windows x64',
            'license': 'runtime/LICENSE.txt', 'componentNotices': 'docs/licenses/CPython-3.15-NOTICES.md',
            'windowsTerms': 'docs/WINDOWS-RUNTIME-TERMS.md', 'isolatedPath': True}


def collect_frontend_licenses(bundle: Path) -> None:
    lock = json.loads((PROJECT / 'package-lock.json').read_text(encoding='utf-8-sig'))
    records = []
    for relative, info in lock.get('packages', {}).items():
        if not relative.startswith('node_modules/'):
            continue
        source = PROJECT / relative
        name = relative.removeprefix('node_modules/')
        if not source.is_dir():
            if info.get('optional'):
                continue
            raise RuntimeError(f'Installed frontend dependency missing: {relative}')
        manifest = json.loads((source / 'package.json').read_text(encoding='utf-8'))
        if manifest.get('version') != info.get('version'):
            raise RuntimeError(f'Dependency version differs from lock: {name}')
        files = []
        notice_source = source
        # The platform package points to the same packages/rolldown upstream
        # directory, but omits license files from its npm tarball.
        if name.startswith('@rolldown/binding-'):
            parent = PROJECT / 'node_modules/rolldown'
            parent_manifest = json.loads((parent / 'package.json').read_text(encoding='utf-8'))
            repository = manifest.get('repository', {})
            if (parent_manifest.get('version') != manifest['version'] or not isinstance(repository, dict)
                    or repository.get('url') != 'git+https://github.com/rolldown/rolldown.git'
                    or repository.get('directory') != 'packages/rolldown'):
                raise RuntimeError('Rolldown binding license mapping needs a new review.')
            notice_source = parent
        for path in notice_source.iterdir():
            if path.is_file() and path.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'THIRD-PARTY-LICENSE', 'THIRDPARTYNOTICE')):
                destination = bundle / 'licenses' / 'frontend' / name / path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                files.append(destination.relative_to(bundle).as_posix())
        license_id = manifest.get('license') or info.get('license')
        if not license_id or not files:
            raise RuntimeError(f'Dependency license identifier or text missing: {name}')
        records.append({'name': name, 'version': info.get('version'), 'license': license_id,
                        'scope': 'build/dev (not necessarily shipped)' if info.get('dev') else 'frontend dependency',
                        'noticeSource': notice_source.relative_to(PROJECT).as_posix(),
                        'files': files})
    (bundle / 'licenses').mkdir(exist_ok=True)
    write_json(bundle / 'licenses' / 'frontend-dependencies.json', records)

