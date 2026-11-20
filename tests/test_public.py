import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from backend.catalog import Catalog
from backend.server import LocalServer
from test_streams import export_app
from tools.check_public import check


class PublicEditionTests(unittest.TestCase):
    def test_empty_startup_then_import_three_streams_and_preserve_snapshot_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty = root / 'empty'
            empty.mkdir()
            with self.assertRaises(ValueError):
                Catalog(empty)
            catalog = Catalog(empty, allow_empty=True)
            self.assertEqual(catalog.summary()['totals']['apps'], 0)
            self.assertEqual(catalog.sources(), [])
            server = LocalServer(('127.0.0.1', 0), catalog)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def post(path):
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/import',
                    data=json.dumps({'root': str(path)}).encode(), headers={'X-Trace-Request': 'local'})
                try:
                    response = urllib.request.urlopen(request, timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    return response.status, json.loads(response.read())
            try:
                for stream in ('Stream Alpha', 'Stream Beta', 'Stream Gamma'):
                    export_app(root / 'exports' / stream / 'Shared App', stream.replace(' ', '_'))
                status, summary = post(root / 'exports')
                self.assertEqual(status, 200)
                self.assertEqual((summary['totals']['streams'], summary['totals']['apps']), (3, 3))
                snapshot = server.catalog
                for bad in (empty, root / 'missing'):
                    self.assertEqual(post(bad)[0], 400)
                    self.assertIs(server.catalog, snapshot)
                for app in snapshot.apps.values():
                    trace = app.graph.trace(next(iter(app.fields)))
                    self.assertEqual(trace['status'], 'complete')
                    self.assertEqual({n['table'] for n in trace['nodes'] if n['kind'] == 'source'},
                                     {app.stream['name'].upper().replace(' ', '_')})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_allow_empty_does_not_hide_broken_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'app-properties.json').write_text('[]')
            with self.assertRaises(ValueError):
                Catalog(root, allow_empty=True)

    def test_public_guard_rejects_metadata_payload_and_personal_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'metadata/apps').mkdir(parents=True)
            payload = root / 'metadata/apps/anything.json'
            payload.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'metadata payload'):
                check(root, check_git=False)
            payload.unlink()
            (root / 'README.md').write_text('C:' + '/Users/' + 'Example/Desktop/export')
            with self.assertRaisesRegex(ValueError, 'personal absolute path'):
                check(root, check_git=False)


if __name__ == '__main__':
    unittest.main()
