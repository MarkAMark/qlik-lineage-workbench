"""Build public source and Windows x64 archives. Never accepts a metadata root."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from check_public import PROJECT, PATTERNS, check
from runtime_bundle import collect_frontend_licenses, copy_runtime, copy_tree, digest, write_json


def archive(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                output.write(path, folder.name + '/' + path.relative_to(folder).as_posix())
    target.with_suffix(target.suffix + '.sha256').write_text(digest(target) + '  ' + target.name + '\n', encoding='ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true')
    parser.add_argument('--output', type=Path, default=PROJECT / 'releases')
    args = parser.parse_args()
    files = check()
    version = json.loads((PROJECT / 'package.json').read_text())['version']
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='TracePublicBuild-') as temporary:
        staging = Path(temporary)
        source = staging / f'Trace-Qlik-Lineage-Source-v{version}'
        for path in files:
            destination = source / path.relative_to(PROJECT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        check(source, check_git=False)
        source_zip = args.output / (source.name + '.zip')
        archive(source, source_zip)
        print(f'Source: {source_zip.name}', flush=True)
        if args.source_only:
            return
        if not (PROJECT / 'dist/index.html').is_file():
            raise RuntimeError('Run npm run build first.')
        bundle = staging / f'Trace-Qlik-Lineage-Public-Windows-x64-v{version}'
        for folder in ('backend', 'dist'):
            copy_tree(PROJECT / folder, bundle / folder, {'__pycache__', '.git'})
        # Inspect the built app as well as source; no stale internal assets.
        for path in (bundle / 'dist').rglob('*'):
            if path.is_file():
                content = path.read_text(encoding='utf-8')
                if any(regex.search(content) for regex, _ in PATTERNS):
                    raise ValueError('Unsafe content in built frontend: ' + path.name)
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'README.zh-CN.md', 'SECURITY.md'):
            shutil.copy2(PROJECT / name, bundle / name)
        copy_tree(PROJECT / 'docs', bundle / 'docs', {'__pycache__'})
        copy_tree(PROJECT / 'packaging', bundle, {'__pycache__'})
        # Copy only SQLGlot code and its license; omit install provenance and all other packages.
        copy_tree(PROJECT / '.deps/sqlglot', bundle / '.deps/sqlglot', {'__pycache__'})
        license_paths = list((PROJECT / '.deps').glob('sqlglot-*.dist-info/licenses/LICENSE'))
        if len(license_paths) != 1:
            raise RuntimeError('Exactly one SQLGlot installation and its MIT license are required.')
        destination = bundle / 'licenses/SQLGlot-LICENSE.txt'
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(license_paths[0], destination)
        (bundle / 'metadata/apps').mkdir(parents=True)
        (bundle / 'metadata/apps/.gitkeep').touch()
        runtime = copy_runtime(bundle / 'runtime')
        collect_frontend_licenses(bundle)
        metadata_files = [p for p in (bundle / 'metadata').rglob('*') if p.is_file() and p.name != '.gitkeep']
        if metadata_files:
            raise RuntimeError('A public release must contain zero metadata files.')
        records = {p.relative_to(bundle).as_posix(): {'bytes': p.stat().st_size, 'sha256': digest(p)}
                   for p in sorted(bundle.rglob('*')) if p.is_file()}
        write_json(bundle / 'manifest.json', {'edition': 'public', 'version': version, 'runtime': runtime,
                   'metadata': {'files': 0, 'streams': []}, 'files': records})
        verified = subprocess.run([str(bundle / 'runtime/python.exe'), '-I', '-B', str(bundle / 'verify_package.py')],
                                  cwd=staging, capture_output=True, text=True, check=True)
        print(verified.stdout.strip(), flush=True)
        portable_zip = args.output / (bundle.name + '.zip')
        archive(bundle, portable_zip)
        print(f'Portable: {portable_zip.name}; metadata = 0 files', flush=True)


if __name__ == '__main__':
    main()
