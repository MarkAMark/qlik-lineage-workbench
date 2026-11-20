"""Check the public package manifest and zero-metadata distribution."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    errors = []
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    expected_files = set(manifest['files']) | {'manifest.json'}
    if actual != expected_files:
        errors.append('Unexpected or missing package files; verify a freshly extracted archive.')
    if manifest.get('edition') != 'public' or manifest.get('metadata', {}).get('files') != 0:
        errors.append('This is not a zero-metadata public distribution.')
    for relative, expected in manifest['files'].items():
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            errors.append(f'Missing or invalid file: {relative}')
        else:
            with target.open('rb') as handle:
                checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
            if target.stat().st_size != expected['bytes'] or checksum != expected['sha256']:
                errors.append(f'Checksum mismatch: {relative}')
    if errors:
        print('\n'.join(errors))
        raise SystemExit(1)
    print(f"PASS: {len(manifest['files'])} files verified, including {manifest['metadata']['files']} metadata files.")
    print('Metadata streams: ' + ', '.join(f"{s['name']} ({s['appCount']} Apps)" for s in manifest['metadata']['streams']))


if __name__ == '__main__':
    main()
