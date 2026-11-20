import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.catalog import Application, Catalog
from backend.model import Graph
from backend.script import ScriptParser


class TableLineageTests(unittest.TestCase):
    def parse(self, script):
        graph = Graph()
        parser = ScriptParser(graph, {})
        parser.parse("LIB CONNECT TO 'Oracle';\n" + script)
        parser.table_lineage.finalize(parser.tables, {}, parser.warnings, 'Demo')
        return parser, parser.table_lineage

    def edge(self, index, source, target):
        return next(e for e in index.project().values()
                    if index.nodes[e['source']]['label'] == source and index.nodes[e['target']]['label'] == target)

    def test_predicate_only_input_has_context_edge_without_value_mapping(self):
        parser, index = self.parse('T:\nWITH q AS (SELECT a.x AS X FROM value_table a WHERE EXISTS '
                                  '(SELECT 1 FROM filter_table b WHERE b.id=a.id)) SELECT X FROM q;')
        edge = self.edge(index, 'FILTER_TABLE', 'T')
        self.assertEqual(edge['roles'], ['context'])
        self.assertEqual(index.evidence(edge['id'])['mappingTotal'], 0)
        self.assertNotIn('FILTER_TABLE', {n['table'] for n in parser.graph.nodes.values() if n['kind'] == 'source'})
        self.assertNotIn('Q', {n['label'] for n in index.view()['nodes']})

    def test_unused_cte_is_not_connected_to_output(self):
        _, index = self.parse('T:\nWITH unused AS (SELECT z FROM ignored) SELECT x FROM real_input;')
        self.assertEqual({n['label'] for n in index.view()['nodes'] if n['kind'] == 'table_source'}, {'REAL_INPUT'})

    def test_counts_constants_and_resident_keep_explicit_table_reads(self):
        _, index = self.parse('Raw:\nSELECT COUNT(*) AS N FROM events;\nFinal:\nLOAD 1 AS FLAG Resident Raw;')
        self.edge(index, 'EVENTS', 'Raw')
        self.edge(index, 'Raw', 'Final')

    def test_drop_retains_history_and_recreated_name_gets_new_instance(self):
        parser, index = self.parse('Raw:\nSELECT p AS PRICE FROM old_prices;\nFinal:\nLOAD PRICE*2 AS TOTAL Resident Raw;'
                                  '\nDROP TABLE Raw;\nRaw:\nSELECT n AS NEW_PRICE FROM new_prices;')
        old = next(n for n in index.view()['nodes'] if n['label'] == 'Raw' and n['dropped'])
        new = index.nodes[parser.tables['Raw'].lineage_id]
        self.assertNotEqual(old['instanceId'], new['instanceId'])
        self.assertIn('DROP TABLE', index.original(old['dropRef']))
        self.assertIn('PRICE', index.columns[old['id']])
        self.assertEqual(index.field_trace(old['id'], 'PRICE')['technicalField']['table'], 'Raw')
        self.edge(index, 'Raw', 'Final')

    def test_drop_fields_and_concatenate_have_distinct_acyclic_versions(self):
        parser, index = self.parse('T:\nSELECT a AS A, b AS B FROM one;\nCONCATENATE(T)\nSELECT c AS A FROM two;'
                                  '\nDROP FIELD B FROM T;')
        current = parser.tables['T'].lineage_id
        versions = index.instances[index.nodes[current]['instanceId']]
        self.assertEqual(len(versions), 3)
        self.assertIn('B', index.columns[versions[0]])
        self.assertNotIn('B', index.columns[current])
        self.assertTrue(all(e['source'] != e['target'] for e in index.project().values()))
        self.assertIn('TWO', {index.nodes[i]['label'] for i in index._table_ancestors({current})})

    def test_keep_preserves_both_tables_and_updates_only_reduced_sides(self):
        for side in ('LEFT', 'RIGHT', 'INNER'):
            with self.subTest(side=side):
                parser, index = self.parse('A:\nSELECT id AS ID, x AS X FROM one;\nB:\n' + side +
                                          ' KEEP(A)\nLOAD ID, Y;\nSELECT id AS ID,y AS Y FROM two;')
                self.assertEqual(set(parser.tables), {'A', 'B'})
                a, b = (parser.tables[n].lineage_id for n in ('A', 'B'))
                self.assertEqual(len(index.instances[index.nodes[a]['instanceId']]), 2 if side in ('RIGHT', 'INNER') else 1)
                a_to_b = [e for e in index.project().values() if index.nodes[e['source']]['label'] == 'A' and e['target'] == b]
                self.assertEqual(bool(a_to_b), side in ('LEFT', 'INNER'))
                if a_to_b:
                    self.assertEqual(a_to_b[0]['roles'], ['context'])

    def test_table_identity_does_not_require_known_star_schema(self):
        parser, index = self.parse('T:\nSELECT * FROM missing_schema;')
        target = index.public_node(parser.tables['T'].lineage_id)
        self.assertEqual(target['status'], 'complete')
        self.assertEqual(target['schemaStatus'], 'unknown')
        self.edge(index, 'MISSING_SCHEMA', 'T')

    def test_preceding_load_keeps_sql_and_all_load_evidence(self):
        parser, index = self.parse('T:\nLOAD PRICE*2 AS TOTAL;\nLOAD P AS PRICE;\nSELECT p AS P FROM prices;')
        edge = self.edge(index, 'PRICES', 'T')
        evidence = index.evidence(edge['id'])
        self.assertEqual({p['targetField'] for p in evidence['fieldMappings']}, {'TOTAL'})
        code = '\n'.join(o['code'] for o in evidence['operations'])
        self.assertIn('LOAD PRICE*2', code)
        self.assertIn('SELECT p', code)
        self.assertEqual(parser.tables['T'].fields.keys(), {'TOTAL'})

    def test_multiple_reads_keep_data_and_context_roles_and_evidence(self):
        _, index = self.parse('T:\nSELECT a.x AS X FROM shared a WHERE EXISTS(SELECT 1 FROM shared b WHERE b.id=a.id);')
        edge = self.edge(index, 'SHARED', 'T')
        self.assertEqual(set(edge['roles']), {'data', 'context'})
        self.assertGreater(index.evidence(edge['id'])['mappingTotal'], 0)

    def test_connection_and_import_identity_are_scoped(self):
        _, index = self.parse("A:\nSELECT x AS X FROM t;\nLIB CONNECT TO 'Second';\nB:\nSELECT y AS Y FROM t;")
        sources = [n for n in index.view()['nodes'] if n['kind'] == 'table_source']
        self.assertEqual(len(sources), 2)
        self.assertEqual({n['connection'] for n in sources}, {'Oracle', 'Second'})
        _, other = self.parse('T:\nSELECT x FROM t;')
        self.assertFalse(set(index.nodes) & set(other.nodes))

    def test_unknown_existing_schema_does_not_trigger_automatic_concatenation(self):
        parser, _ = self.parse('A:\nSELECT id AS ID, * FROM one;\nB:\nSELECT id AS ID FROM two;')
        self.assertEqual(set(parser.tables), {'A', 'B'})

    def test_dynamic_paths_are_gaps_and_separate_statements_do_not_share_unknown_identity(self):
        _, index = self.parse('A:\nLOAD X FROM [$(vPath)/a.csv];\nB:\nLOAD Y FROM [$(vPath)/a.csv];')
        sources = [n for n in index.view()['nodes'] if n['kind'].startswith('table_') and n['sourceType'] != 'logical']
        self.assertEqual(len(sources), 2)
        self.assertTrue(all(n['kind'] == 'table_unresolved' for n in sources))

    def test_source_detail_lists_read_operations_instead_of_claiming_no_code(self):
        _, index = self.parse('A:\nSELECT x AS X FROM one;\nB:\nSELECT y AS Y FROM one;')
        source = next(n for n in index.view()['nodes'] if n['label'] == 'ONE')
        operations = index.detail(source['id'])['operations']
        self.assertEqual(len(operations), 2)
        self.assertTrue(all('FROM one' in operation['code'] for operation in operations))


class TableUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name)
        (path / 'objects').mkdir()
        for filename, value in {'app-properties.json': {'qTitle': 'Demo'}, 'variables.json': [],
                                'dimensions.json': [], 'measures.json': []}.items():
            (path / filename).write_text(json.dumps(value), encoding='utf-8')
        (path / 'script.qvs').write_text("LIB CONNECT TO 'Oracle';\nA:\nSELECT a AS AMOUNT, k AS ID FROM amounts;"
                                        '\nB:\nSELECT t AS TARGET, k AS ID FROM targets;', encoding='utf-8')
        doc = {'qProperty': {'qInfo': {'qId': 'S', 'qType': 'sheet'}, 'qMetaDef': {'title': 'Sheet'}}, 'qChildren': []}
        for chart_id in ('C1', 'C2'):
            doc['qChildren'].append({'qProperty': {'qInfo': {'qId': chart_id}, 'title': chart_id,
                'visualization': 'table', 'qHyperCubeDef': {'qMeasures': [
                    {'qDef': {'qDef': expression, 'qLabel': label}} for label, expression in
                    [('Amount', 'Sum(AMOUNT)'), ('Ratio', 'Sum(AMOUNT)/Sum(TARGET)'),
                     ('Shared', 'Count(ID)'), ('Constant', '=1')]]}}})
        (path / 'objects' / 'sheet.json').write_text(json.dumps(doc), encoding='utf-8')
        self.app = Application(path)

    def usage(self, label):
        return next(f for f in self.app.fields.values() if f['label'] == label)

    def test_usage_belongs_to_chart_dataset_and_multiple_dependencies_are_not_ambiguity(self):
        index = self.app.table_lineage
        amount, ratio, shared, constant = (self.usage(label) for label in ('Amount', 'Ratio', 'Shared', 'Constant'))
        self.assertEqual(index.bindings[amount['id']]['mappingStatus'], 'resolved')
        self.assertEqual(index.bindings[ratio['id']]['mappingStatus'], 'multiple')
        self.assertEqual(index.bindings[shared['id']]['mappingStatus'], 'review')
        self.assertEqual(index.bindings[constant['id']]['mappingStatus'], 'no_table')
        self.assertEqual(len(index.datasets), 2)
        view = index.view(scope='field', usage=ratio['id'])
        self.assertEqual({n['label'] for n in view['nodes'] if n['kind'] == 'table'}, {'A', 'B'})
        self.assertEqual(view['stats']['datasets'], 1)
        self.assertEqual(next(n for n in view['nodes'] if n['kind'] == 'dataset')['fieldCount'], 1)
        self.assertEqual(index.view(scope='chart', sheet='S', chart='C1')['stats']['datasets'], 1)
        self.assertEqual(index.view(scope='sheet', sheet='S')['stats']['datasets'], 2)

    def test_technical_root_needs_no_sheet_and_source_gap_is_explicit(self):
        index = self.app.table_lineage
        version = self.app.parser.tables['B'].lineage_id
        trace = index.field_trace(version, 'TARGET')
        self.assertIn('technicalField', trace)
        self.assertNotIn('field', trace)
        self.assertEqual(trace['status'], 'complete')
        self.assertEqual({n['table'] for n in trace['nodes'] if n['kind'] == 'source'}, {'TARGETS'})
        source = next(n for n in index.view()['nodes'] if n['label'] == 'AMOUNTS')
        index.columns[source['id']]['PREDICATE_ONLY'] = ''
        gap = index.field_trace(source['id'], 'PREDICATE_ONLY')
        self.assertEqual(gap['status'], 'unresolved')
        self.assertEqual(gap['edges'], [])
        self.assertIn('rootEvidence', gap)



if __name__ == '__main__': unittest.main()
