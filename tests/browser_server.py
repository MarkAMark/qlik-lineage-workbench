"""Disposable browser fixture service; never reads existing metadata."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.catalog import Catalog
from backend.server import LocalServer
from test_streams import export_app

root = Path(sys.argv[1]).resolve()
empty = root / 'empty'
empty.mkdir()
exports = root / 'exports'
for stream in ('Stream Alpha', 'Stream Beta', 'Stream Gamma'):
    export_app(exports / stream / 'Shared App', stream.replace(' ', '_'))
server = LocalServer(('127.0.0.1', 0), Catalog(empty, allow_empty=True))
print(json.dumps({'base': f'http://127.0.0.1:{server.server_port}', 'exports': str(exports), 'empty': str(empty)}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
