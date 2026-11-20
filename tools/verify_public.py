"""Exercise the actual portable archive with no system Python/Node on PATH."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'tests'))
from test_streams import export_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    checks = []
    with tempfile.TemporaryDirectory(prefix='TracePublicVerify-') as temporary:
        temporary = Path(temporary)
        extracted = temporary / '\u672c\u673a \u516c\u5f00\u7248'
        with zipfile.ZipFile(archive) as source:
            assert source.testzip() is None
            for name in source.namelist():
                assert (extracted / name).resolve().is_relative_to(extracted.resolve())
            source.extractall(extracted)
        # Windows runners may expose TEMP through an 8.3 alias or a junction.
        # Compare canonical paths on both sides when proving runtime isolation.
        bundle = next(extracted.iterdir()).resolve()
        shipped = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
        forbidden = {'pythonw.exe', '_tkinter.pyd', 'tcl90.dll', 'tcl9tk90.dll', 'libtommath.dll'}
        assert not any(Path(name).name in forbidden or '/profiling/' in name for name in shipped)
        notices = '\n'.join(p.read_text(encoding='utf-8-sig') for p in (bundle / 'docs/licenses').rglob('*') if p.is_file())
        for marker in ('VoidZero', 'Evan Wallace', 'Daan Leijen', 'Stefan Krah',
                       'UNICODE LICENSE V3', 'Thai Open Source Software Center', 'Microsoft Distributable Code'):
            assert marker in notices, 'Missing attribution: ' + marker
        dependencies = json.loads((bundle / 'licenses/frontend-dependencies.json').read_text(encoding='utf-8'))
        assert all(record['license'] and record['files'] for record in dependencies)
        assert {'vite', 'rolldown'} <= {record['name'] for record in dependencies}
        for record in dependencies:
            assert all((bundle / path).is_file() for path in record['files'])
        checks.append('Component notices and build-helper attributions present; unused GUI/profiler assets absent')
        windows = Path(os.environ['SystemRoot'])
        powershell = windows / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        environment = {**os.environ, 'PATH': os.pathsep.join(map(str, [windows, windows / 'System32', powershell.parent])),
                       'PYTHONHOME': str(temporary / 'absent-python'), 'PYTHONPATH': str(temporary / 'absent-packages')}
        runtime = bundle / 'runtime/python.exe'
        rejected = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                  '-File', str(bundle / 'Start-Trace.ps1'), '-NoBrowser'],
                                 cwd=temporary, env=environment, input=b'NO\n', capture_output=True, timeout=20,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        assert rejected.returncode != 0 and b'Local URL:' not in rejected.stdout
        assert b'not accepted' in rejected.stderr or b'NonInteractive' in rejected.stderr
        checks.append('Launcher refuses to start without runtime-terms acceptance')

        def python(*arguments):
            result = subprocess.run([str(runtime), '-I', '-B', '-X', 'utf8', *map(str, arguments)], cwd=temporary,
                                    env=environment, capture_output=True, text=True, encoding='utf-8', timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout

        python(bundle / 'verify_package.py')
        proof = json.loads(python('-c', 'import sys,json;sys.path.insert(0,sys.argv[1]);import backend,sqlglot,ssl;'
                                 'print(json.dumps([sys.executable,sqlglot.__file__,ssl.__file__]))', bundle))
        assert all(Path(path).resolve().is_relative_to(bundle) for path in proof), {
            'bundle': str(bundle), 'runtimePaths': proof}
        checks.append('ZIP CRC, manifest hashes and isolated bundled runtime pass')
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        sentinel = socket.socket()
        sentinel.bind(('127.0.0.1', 0))
        sentinel.listen()
        occupied = sentinel.getsockname()[1]
        process = None
        try:
            launch = [str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(bundle / 'Start-Trace.ps1'),
                      '-NoBrowser', '-AcceptRuntimeTerms', '-Port', str(occupied)]
            log_path = temporary / 'launch.log'
            with log_path.open('wb') as log:
                process = subprocess.Popen(launch, cwd=temporary, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
            base = ''
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                log = log_path.read_bytes().decode('utf-8', errors='replace')
                match = re.search(r'Local URL: (http://127\.0\.0\.1:\d+)', log)
                if match:
                    base = match[1]
                    try:
                        with http.open(base + '/api/health', timeout=1) as response:
                            assert json.load(response)['apps'] == 0
                            break
                    except OSError:
                        pass
                if process.poll() is not None:
                    raise RuntimeError(log)
                time.sleep(.15)
            else:
                raise RuntimeError('Portable startup timed out: ' + log)

            def api(route):
                with http.open(base + route, timeout=15) as response:
                    return json.load(response)

            def post(root):
                request = urllib.request.Request(base + '/api/import', data=json.dumps({'root': str(root)}).encode(),
                                                 headers={'X-Trace-Request': 'local'})
                try:
                    response = http.open(request, timeout=15)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    return response.status, json.load(response)

            catalog = api('/api/catalog')
            assert catalog['totals']['apps'] == 0 and not catalog['errors']
            assert Path(catalog['root']).resolve() == (bundle / 'metadata/apps').resolve()
            assert int(base.rsplit(':', 1)[1]) != occupied
            checks.append('Relocated Unicode/space path starts empty and skips an occupied port')
            repeated = subprocess.run(launch, cwd=temporary, env=environment, capture_output=True, timeout=20,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            assert repeated.returncode == 0 and b'already running' in repeated.stdout
            checks.append('Repeated startup reuses only this package service')
            with http.open(base + '/', timeout=10) as response:
                html = response.read().decode('utf-8')
            for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html):
                with http.open(base + asset, timeout=10) as response:
                    assert response.read()
            exports = temporary / 'synthetic-exports'
            for stream in ('Stream Alpha', 'Stream Beta', 'Stream Gamma'):
                export_app(exports / stream / 'Shared App', stream.replace(' ', '_'))
            status, imported = post(exports)
            assert status == 200 and imported['totals']['apps'] == imported['totals']['streams'] == 3
            for summary in imported['apps']:
                app = api('/api/app?' + urllib.parse.urlencode({'id': summary['id']}))
                query = urllib.parse.urlencode({'app': app['id'], 'field': app['fields'][0]['id']})
                trace = api('/api/lineage?' + query)
                assert trace['status'] == 'complete'
                sql = next(n for n in trace['nodes'] if n['kind'] == 'sql')
                evidence = api('/api/evidence?' + urllib.parse.urlencode({'app': app['id'], 'node': sql['id']}))
                assert 'SELECT AMOUNT FROM' in evidence['original']
                full_file = api('/api/source-file?' + urllib.parse.urlencode({'app': app['id'], 'file': 'script.qvs'}))
                assert evidence['original'] in full_file['content']
            assert post(bundle / 'metadata/apps')[0] == 400
            assert api('/api/catalog')['importedAt'] == imported['importedAt']
            checks.append('Three synthetic Streams import; SQL lineage and full code work; failed import preserves snapshot')
            python(bundle / 'verify_package.py')
            checks.append('Runtime usage leaves every packaged file unchanged; metadata payload remains zero')
        finally:
            if process and process.poll() is None:
                subprocess.run([str(windows / 'System32/taskkill.exe'), '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                process.wait(timeout=15)
            sentinel.close()
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    result = {'status': 'passed', 'archive': archive.name, 'sha256': checksum, 'metadataFiles': 0, 'checks': checks}
    archive.with_suffix('.verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
