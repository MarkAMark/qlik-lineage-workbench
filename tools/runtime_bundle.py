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
    destination.mkdir()
    for pattern in ('python.exe', 'pythonw.exe', '*.dll', 'LICENSE*'):
        for path in base.glob(pattern):
            if path.is_file():
                shutil.copy2(path, destination / path.name)
    if not (destination / 'python.exe').is_file() or not (destination / 'LICENSE.txt').is_file():
        raise RuntimeError('The Python runtime or its redistribution license was not found.')
    copy_tree(base / 'Lib', destination / 'Lib', OMIT_STDLIB_DIRS)
    copy_tree(base / 'DLLs', destination / 'DLLs', OMIT_STDLIB_DIRS)
    # This file disables registry, user-site and environment path discovery.
    (destination / f'python{sys.version_info.major}{sys.version_info.minor}._pth').write_text('.\nDLLs\nLib\n', encoding='ascii')
    return {'implementation': 'CPython', 'version': platform.python_version(), 'architecture': 'Windows x64',
            'license': 'runtime/LICENSE.txt', 'isolatedPath': True}


def collect_frontend_licenses(bundle: Path) -> None:
    lock = json.loads((PROJECT / 'package-lock.json').read_text(encoding='utf-8-sig'))
    records = []
    for relative, info in lock.get('packages', {}).items():
        if not relative.startswith('node_modules/') or info.get('dev'):
            continue
        source = PROJECT / relative
        if not source.is_dir():
            raise RuntimeError(f'Installed frontend dependency missing: {relative}')
        name = relative.removeprefix('node_modules/')
        files = []
        for path in source.iterdir():
            if path.is_file() and path.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                destination = bundle / 'licenses' / 'frontend' / name / path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                files.append(destination.relative_to(bundle).as_posix())
        records.append({'name': name, 'version': info.get('version'), 'license': info.get('license'), 'files': files})
    (bundle / 'licenses').mkdir(exist_ok=True)
    write_json(bundle / 'licenses' / 'frontend-dependencies.json', records)

