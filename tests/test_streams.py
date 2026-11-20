import csv
import hashlib
import io
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from backend.catalog import Catalog
from backend.model import key
from backend.server import LocalServer


def export_app(path, table='SALES', stream=None):
    (path / 'objects').mkdir(parents=True)
    props = {'qTitle': 'Shared App'}
    if stream: props['qStream'] = stream
    docs = {'app-properties.json': props, 'variables.json': [], 'dimensions.json': [], 'measures.json': [],
            'objects/sheet.json': {'qProperty': {'qInfo': {'qId': 'S', 'qType': 'sheet'}, 'qMetaDef': {'title': 'Overview'}},
                'qChildren': [{'qProperty': {'qInfo': {'qId': 'C'}, 'visualization': 'table',
                    'qHyperCubeDef': {'qMeasures': [{'qDef': {'qLabel': 'Amount', 'qDef': 'SUM(AMOUNT)'}}]}}}]}}
    for name, value in docs.items(): (path/name).write_text(json.dumps(value), encoding='utf-8')
    (path/'script.qvs').write_text(f"LIB CONNECT TO 'Oracle';\nT:\nSELECT AMOUNT FROM {table};", encoding='utf-8')


class StreamCatalogTests(unittest.TestCase):
    def test_numeric_string_sheet_ranks_do_not_drop_an_app(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'Stream Alpha'/'Shared App'
            export_app(path)
            sheet = {'qProperty': {'qInfo': {'qId': 'S2', 'qType': 'sheet'}, 'qMetaDef': {'title': 'Second'}, 'rank': '1'}, 'qChildren': []}
            (path/'objects'/'second.json').write_text(json.dumps(sheet), encoding='utf-8')
            catalog = Catalog(directory)
            self.assertFalse(catalog.errors)
            app = next(iter(catalog.apps.values()))
            self.assertEqual([(s['id'], s['rank']) for s in app.sheets], [('S', 0), ('S2', 1)])

    def test_three_streams_keep_same_named_apps_and_their_lineages_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('Stream Alpha', 'Stream Beta', 'Stream Gamma'):
                export_app(root/name/'Shared App', name.replace(' ', '_'))
            catalog = Catalog(root)
            self.assertEqual(len(catalog.apps), 3)
            summary = catalog.summary()
            self.assertEqual(summary['totals']['streams'], 3)
            self.assertEqual({s['name']: s['appCount'] for s in summary['streams']}, {'Stream Alpha': 1, 'Stream Beta': 1, 'Stream Gamma': 1})
            for app in catalog.apps.values():
                field = next(iter(app.fields.values()))
                sources = [n for n in app.graph.trace(field['id'])['nodes'] if n['kind']=='source']
                self.assertEqual({n['table'] for n in sources}, {app.stream['name'].upper().replace(' ', '_')})
                self.assertEqual(app.folder, app.stream['name'] + '/Shared App')

    def test_flat_exports_keep_legacy_ids_and_unknown_stream_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'Shared App'
            export_app(path)
            catalog = Catalog(directory)
            app = next(iter(catalog.apps.values()))
            self.assertEqual(app.id, key('Shared App'))
            self.assertEqual(app.stream['source'], 'unknown')
            self.assertEqual(app.stream['name'], '未标注 Stream')
            self.assertEqual(catalog.summary()['totals']['streams'], 0)
            self.assertEqual(next(iter(Catalog(path).apps)), app.id)

    def test_outer_apps_wrapper_has_the_same_streams_and_app_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_app(root/'apps'/'Stream Alpha'/'Shared App')
            nested = Catalog(root/'apps')
            outer = Catalog(root)
            self.assertEqual(set(nested.apps), set(outer.apps))
            self.assertEqual(outer.summary()['streams'][0]['name'], 'Stream Alpha')
            # Once an App is found, nested objects are never scanned as Apps.
            (root/'apps'/'Stream Alpha'/'Shared App'/'objects'/'nested').mkdir()
            (root/'apps'/'Stream Alpha'/'Shared App'/'objects'/'nested'/'script.qvs').write_text('LOAD 1 AS BAD AUTOGENERATE 1;')
            self.assertEqual(len(Catalog(root).apps), 1)

    def test_explicit_metadata_stream_takes_priority_over_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            export_app(Path(directory)/'Folder Name'/'Shared App', stream={'qId': 'native-stream-id', 'qName': 'Actual Stream'})
            app = next(iter(Catalog(directory).apps.values()))
            self.assertEqual(app.stream, {'id': 'stream:' + key('native-stream-id'), 'name': 'Actual Stream', 'source': 'metadata'})

    def test_failed_app_is_attributed_to_its_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_app(root/'Good'/'Shared App')
            bad = root/'Broken'/'Shared App'
            bad.mkdir(parents=True)
            (bad/'app-properties.json').write_text('[]')
            catalog = Catalog(root)
            self.assertEqual(len(catalog.apps), 1)
            self.assertEqual(catalog.errors[0]['stream']['name'], 'Broken')
            group = next(s for s in catalog.summary()['streams'] if s['name']=='Broken')
            self.assertEqual((group['appCount'], group['errorCount']), (0, 1))


class StreamApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name in ('Stream Alpha', 'Stream Beta', '=Stream Gamma'):
            export_app(cls.root/name/'Shared App', 'SOURCE_' + str(len(name)))
        cls.server = LocalServer(('127.0.0.1', 0), Catalog(cls.root))
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3); cls.temp.cleanup()

    def get(self, route, **query):
        with urllib.request.urlopen(self.base+route+'?'+urlencode(query), timeout=10) as response:
            return json.load(response)

    def test_search_and_reports_include_stream_and_respect_the_filter(self):
        summary = self.get('/api/catalog')
        self.assertEqual(summary['totals']['apps'], 3)
        stream = next(s for s in summary['streams'] if s['name']=='Stream Alpha')
        results = self.get('/api/search', q='Amount', stream=stream['id'])
        self.assertEqual(results['total'], 1)
        self.assertEqual(results['results'][0]['stream']['id'], stream['id'])
        self.assertEqual(self.get('/api/search', q='Stream Beta')['total'], 1)
        report = self.get('/api/assessment', stream=stream['id'])
        self.assertEqual(len(report['apps']), 1)
        self.assertEqual(report['apps'][0]['stream']['name'], 'Stream Alpha')
        self.assertTrue(all(a['stream']['id']==stream['id'] for source in self.get('/api/sources', stream=stream['id']) for a in source['apps']))

    def test_csv_identifies_streams_and_escapes_excel_formulas(self):
        for route in ('/api/report.csv', '/api/fields.csv'):
            with urllib.request.urlopen(self.base+route, timeout=10) as response:
                rows = list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
            self.assertEqual(len(rows), 3)
            self.assertEqual({row['Stream'] for row in rows}, {'Stream Alpha', 'Stream Beta', "'=Stream Gamma"})

    def test_reimport_nested_streams_does_not_modify_exports(self):
        def hashes(): return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        before = hashes()
        request = urllib.request.Request(self.base+'/api/import', data=json.dumps({'root':str(self.root)}).encode(),
                    headers={'Content-Type':'application/json','X-Trace-Request':'local','Origin':self.base})
        with urllib.request.urlopen(request, timeout=10) as response: result=json.load(response)
        self.assertEqual(result['totals']['streams'], 3)
        self.assertEqual(result['totals']['apps'], 3)
        self.assertEqual(hashes(), before)
