import csv
import hashlib
import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from backend.catalog import Catalog
from backend.server import LocalServer


class LocalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        app = cls.root / 'Demo'
        (app / 'objects').mkdir(parents=True)
        files = {'app-properties.json': {'qTitle': '=Demo'}, 'variables.json': [],
                 'dimensions.json': [], 'measures.json': [],
                 'objects/sheet.json': {'qProperty': {'qInfo': {'qId': 'S', 'qType': 'sheet'}, 'qMetaDef': {'title': 'Sheet'}},
                     'qChildren': [{'qProperty': {'qInfo': {'qId': 'C'}, 'visualization': 'table',
                         'qHyperCubeDef': {'qMeasures': [{'qDef': {'qDef': 'SUM(AMOUNT)'}}]}}}]}}
        for name, value in files.items(): (app / name).write_text(json.dumps(value), encoding='utf-8')
        (app / 'script.qvs').write_text("LIB CONNECT TO 'Oracle';\nSales:\nSELECT AMOUNT FROM sales;", encoding='utf-8')
        cls.server = LocalServer(('127.0.0.1', 0), Catalog(cls.root))
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3); cls.temp.cleanup()

    def request(self, path, value=None, headers=None):
        data = json.dumps(value).encode() if value is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try: response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error: response = error
        with response: return response.status, response.headers, response.read()

    def get_json(self, path):
        status, _, body = self.request(path)
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def test_api_round_trip_reaches_real_source_evidence(self):
        catalog = self.get_json('/api/catalog')
        app = self.get_json('/api/app?id=' + catalog['apps'][0]['id'])
        query = urllib.parse.urlencode({'app': app['id'], 'field': app['fields'][0]['id']})
        trace = self.get_json('/api/lineage?' + query)
        self.assertEqual(trace['status'], 'complete')
        source = next(n for n in trace['nodes'] if n['kind'] == 'source')
        evidence = self.get_json('/api/evidence?' + urllib.parse.urlencode({'app': app['id'], 'node': source['id']}))
        self.assertEqual(evidence['table'], 'SALES')
        self.assertIn('SELECT AMOUNT FROM sales', evidence['original'])
        self.assertEqual(len(evidence['consumers']), 1)
        field_evidence = self.get_json('/api/evidence?' + urllib.parse.urlencode({'app': app['id'], 'node': trace['root']}))
        self.assertEqual(len(field_evidence['inputs']), 1)
        self.assertEqual(field_evidence['inputs'][0]['kind'], 'expression')

    def test_full_source_file_preserves_content_and_script_line_reference(self):
        catalog = self.get_json('/api/catalog')
        app_id = catalog['apps'][0]['id']
        query = urllib.parse.urlencode(dict(app=app_id, snapshot=catalog['importedAt'], file='script.qvs'))
        source = self.get_json('/api/source-file?' + query)
        self.assertEqual(source['content'], "LIB CONNECT TO 'Oracle';\nSales:\nSELECT AMOUNT FROM sales;")
        self.assertEqual(source['lineCount'], 3)
        self.assertEqual(source['snapshot'], catalog['importedAt'])
        app = self.server.catalog.apps[app_id]
        node = next(n for n in app.graph.nodes.values() if n['kind'] == 'sql')
        original = app.evidence(node['id'])['original']
        self.assertEqual('\n'.join(source['content'].splitlines()[node['ref']['line'] - 1:node['ref']['endLine']]), original)
        with patch.object(Path, 'read_text', side_effect=AssertionError('Source viewer must use the imported snapshot')):
            self.assertEqual(self.get_json('/api/source-file?' + query)['content'], source['content'])

    def test_model_field_evidence_links_to_a_real_imported_definition(self):
        app_id = self.get_json('/api/catalog')['apps'][0]['id']
        app = self.get_json('/api/app?id=' + app_id)
        trace = self.get_json('/api/lineage?' + urllib.parse.urlencode(dict(app=app_id, field=app['fields'][0]['id'])))
        model = next(node for node in trace['nodes'] if node['kind'] == 'field')
        evidence = self.get_json('/api/evidence?' + urllib.parse.urlencode(dict(app=app_id, node=model['id'])))
        self.assertEqual(evidence['id'], model['id'])
        self.assertIsNone(evidence['ref'])
        definition = evidence['definitionSources'][0]
        source = self.get_json('/api/source-file?' + urllib.parse.urlencode(dict(app=app_id, file=definition['ref']['file'])))
        self.assertIn(definition['original'], source['content'])
        self.assertIn(definition['id'], [node['id'] for node in evidence['inputs']])

    def test_full_json_file_reports_actual_pointer_columns_without_reformatting(self):
        app_id = self.get_json('/api/catalog')['apps'][0]['id']
        app = self.get_json('/api/app?id=' + app_id)
        evidence = self.get_json('/api/evidence?' + urllib.parse.urlencode(dict(app=app_id, node=app['fields'][0]['id'])))
        source = self.get_json('/api/source-file?' + urllib.parse.urlencode(dict(app=app_id, file=evidence['ref']['file'])))
        self.assertEqual(source['content'], self.server.catalog.apps[app_id].files[evidence['ref']['file']])
        self.assertEqual(source['lineCount'], 1)  # This fixture is deliberately minified.
        location = source['locations'][evidence['ref']['pointer']]
        self.assertEqual(location['line'], 1)
        selected = source['content'][location['column'] - 1:location['endColumn'] - 1]
        self.assertEqual(json.loads(selected), json.loads(evidence['original']))

    def test_full_source_file_rejects_unimported_paths_and_stale_snapshots(self):
        app_id = self.get_json('/api/catalog')['apps'][0]['id']
        for filename in ('../backend/server.py', '../../outside.txt', str(self.root / 'Demo/script.qvs'), 'missing.qvs'):
            status, _, body = self.request('/api/source-file?' + urllib.parse.urlencode(dict(app=app_id, file=filename)))
            self.assertEqual(status, 400)
            self.assertIn('error', json.loads(body))
        status, _, _ = self.request('/api/source-file?' + urllib.parse.urlencode(dict(app=app_id, file='script.qvs', snapshot='expired')))
        self.assertEqual(status, 409)

    def test_invalid_import_retains_previous_snapshot(self):
        before = self.server.catalog
        headers = {'Content-Type': 'application/json', 'X-Trace-Request': 'local'}
        self.assertEqual(self.request('/api/import', [], headers)[0], 400)
        self.assertEqual(self.request('/api/import', {'root': 123}, headers)[0], 400)
        self.assertEqual(self.request('/api/import', {'root': str(self.root / 'missing')}, headers)[0], 400)
        self.assertIs(self.server.catalog, before)

    def test_reimport_is_read_only_and_replaces_snapshot_on_success(self):
        def hashes(): return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in self.root.rglob('*') if p.is_file()}
        before, snapshot = hashes(), self.server.catalog
        status, _, body = self.request('/api/import', {'root': str(self.root)},
                                        {'Content-Type': 'application/json', 'X-Trace-Request': 'local', 'Origin': self.base})
        self.assertEqual(status, 200, body)
        self.assertIsNot(self.server.catalog, snapshot)
        self.assertEqual(hashes(), before)

    def test_cross_origin_and_unmarked_imports_are_rejected(self):
        self.assertEqual(self.request('/api/import', {'root': str(self.root)})[0], 403)
        self.assertEqual(self.request('/api/import', {'root': str(self.root)},
            {'X-Trace-Request': 'local', 'Origin': 'https://external.example'})[0], 403)

    def test_host_and_static_path_traversal_are_rejected(self):
        self.assertEqual(self.request('/api/health', headers={'Host': 'external.example'})[0], 403)
        self.assertEqual(self.request('/%2e%2e/backend/server.py')[0], 400)

    def test_reports_use_requested_assumptions_and_escape_excel_formulas(self):
        report = self.get_json('/api/assessment?contingency=40&hoursPerDay=7&productivity=1.2')
        self.assertEqual(report['apps'][0]['contingency'], 40)
        self.assertEqual(report['apps'][0]['hoursPerDay'], 7)
        status, headers, body = self.request('/api/report.csv?contingency=40&hoursPerDay=7&productivity=1.2')
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
        self.assertEqual(float(rows[0]['Contingency %']), 40)
        self.assertEqual(rows[0]['App'], "'=Demo")
        self.assertIn('attachment', headers['Content-Disposition'])

    def test_invalid_estimate_and_unknown_resources_return_json_errors(self):
        for route in ('/api/assessment?hoursPerDay=0', '/api/app?id=missing', '/api/assessment?contingency=nan'):
            status, _, body = self.request(route)
            self.assertEqual(status, 400)
            self.assertIn('error', json.loads(body))

    def test_json_is_local_and_non_cacheable(self):
        status, headers, body = self.request('/api/health')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['service'], 'qlik-lineage-studio')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_table_scope_detail_evidence_and_technical_root_round_trip(self):
        catalog = self.get_json('/api/catalog')
        app = self.get_json('/api/app?id=' + catalog['apps'][0]['id'])
        params = dict(app=app['id'], snapshot=catalog['importedAt'])
        graph = self.get_json('/api/table-lineage?' + urllib.parse.urlencode(params))
        self.assertEqual(graph['snapshot'], catalog['importedAt'])
        table = next(n for n in graph['nodes'] if n['kind'] == 'table' and n['current'])
        detail = self.get_json('/api/table-detail?' + urllib.parse.urlencode(dict(params, table=table['id'])))
        column = next(c for c in detail['fields'] if c['name'] == 'AMOUNT')
        self.assertTrue(column['nodeId'])
        trace = self.get_json('/api/table-field-lineage?' + urllib.parse.urlencode(dict(params, version=table['id'], field='AMOUNT')))
        self.assertNotIn('field', trace)
        self.assertEqual(trace['technicalField']['version'], table['id'])
        self.assertTrue(any(n.get('table') == 'SALES' for n in trace['nodes']))
        evidence = self.get_json('/api/table-evidence?' + urllib.parse.urlencode(dict(params, edge=graph['edges'][0]['id'])))
        self.assertTrue(any('SELECT AMOUNT FROM sales' in o['code'] for o in evidence['operations']))
        self.assertGreater(evidence['mappingTotal'], 0)
        focused = self.get_json('/api/table-lineage?' + urllib.parse.urlencode(dict(params, scope='field', usage=app['fields'][0]['id'])))
        self.assertEqual(focused['stats']['datasets'], 1)
        self.assertTrue(any(e['relation'] == 'consumption' for e in focused['edges']))

    def test_table_csv_preserves_scope_evidence_and_empty_view_selection(self):
        catalog = self.get_json('/api/catalog')
        params = dict(app=catalog['apps'][0]['id'], snapshot=catalog['importedAt'])
        status, headers, body = self.request('/api/table-relations.csv?' + urllib.parse.urlencode(params))
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'))
        self.assertIn('attachment', headers['Content-Disposition'])
        rows = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
        self.assertTrue(rows)
        self.assertTrue(all(r['App'] == "'=Demo" and r['Snapshot'] == catalog['importedAt'] for r in rows))
        self.assertTrue(all(r['File'] == 'script.qvs' and int(r['Line']) > 0 for r in rows))
        status, _, empty = self.request('/api/table-relations.csv?' + urllib.parse.urlencode(dict(params, edges='none')))
        self.assertEqual(status, 200)
        self.assertEqual(list(csv.DictReader(io.StringIO(empty.decode('utf-8-sig')))), [])

    def test_table_snapshot_and_invalid_parameters_do_not_return_mixed_definitions(self):
        app_id = self.get_json('/api/catalog')['apps'][0]['id']
        status, _, body = self.request('/api/table-lineage?' + urllib.parse.urlencode(dict(app=app_id, snapshot='expired')))
        self.assertEqual(status, 409)
        self.assertIn('error', json.loads(body))
        for suffix in ('&scope=missing', '&scope=field&usage=missing', '&limit=1001', '&offset=-1'):
            self.assertEqual(self.request('/api/table-lineage?app=' + app_id + suffix)[0], 400)
        self.assertEqual(self.request('/api/table-detail?app=' + app_id + '&table=missing')[0], 400)
        self.assertEqual(self.request('/api/table-field-lineage?app=' + app_id + '&version=missing&field=X')[0], 400)

    def test_workbench_endpoint_cannot_serve_two_independent_snapshots(self):
        with self.assertRaises(OSError):
            LocalServer(('127.0.0.1', self.server.server_port), self.server.catalog)
        self.assertEqual(self.get_json('/api/catalog')['importedAt'], self.server.catalog.imported_at)


if __name__ == '__main__': unittest.main()
