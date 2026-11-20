import json
import tempfile
import unittest
from pathlib import Path

from backend.catalog import Application


class ModelFieldEvidenceTests(unittest.TestCase):
    def application(self, script):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'app-properties.json').write_text(json.dumps({'qTitle': 'Demo'}), encoding='utf-8')
        (root / 'script.qvs').write_text("LIB CONNECT TO 'Oracle';\n" + script, encoding='utf-8')
        return Application(root)

    def test_model_field_exposes_the_real_definition_without_claiming_an_own_file(self):
        app = self.application('Sales:\nSELECT AMOUNT FROM sales;')
        model = app.parser.resolve('AMOUNT')
        evidence = app.evidence(model)
        self.assertIsNone(evidence['ref'])
        self.assertEqual(evidence['original'], '')
        self.assertEqual(evidence['expression'], 'AMOUNT')
        self.assertEqual(len(evidence['definitionSources']), 1)
        definition = evidence['definitionSources'][0]
        self.assertEqual(definition['kind'], 'sql')
        self.assertIn('SELECT AMOUNT FROM sales', definition['original'])
        self.assertIn(definition['id'], app.graph.incoming[model])
        self.assertEqual(definition['original'], app.evidence(definition['id'])['original'])
        self.assertEqual(definition['ref']['file'], 'script.qvs')

    def test_resident_model_uses_the_nearest_load_instead_of_the_earlier_sql(self):
        app = self.application('Raw:\nSELECT AMOUNT FROM sales;\nFinal:\nLOAD AMOUNT AS FINAL_AMOUNT Resident Raw;\nDROP TABLE Raw;')
        definition = app.evidence(app.parser.resolve('FINAL_AMOUNT'))['definitionSources'][0]
        self.assertEqual(definition['kind'], 'load')
        self.assertIn('Resident Raw', definition['original'])
        self.assertNotIn('SELECT AMOUNT', definition['original'])

    def test_all_same_name_definitions_are_preserved_in_source_order(self):
        app = self.application('First:\nSELECT AMOUNT, A FROM first_source;\nSecond:\nSELECT AMOUNT, B FROM second_source;')
        evidence = app.evidence(app.parser.resolve('AMOUNT'))
        self.assertEqual(evidence['confidence'], 'review')
        sources = evidence['definitionSources']
        self.assertEqual(len(sources), 2)
        self.assertIn('first_source', sources[0]['original'])
        self.assertIn('second_source', sources[1]['original'])
        self.assertLess(sources[0]['ref']['line'], sources[1]['ref']['line'])

    def test_fileless_intermediate_nodes_and_cycles_terminate_at_a_real_definition(self):
        app = self.application('Sales:\nSELECT AMOUNT FROM sales;')
        sql = next(node for node in app.graph.nodes.values() if node['kind'] == 'sql')
        first = app.graph.add('field', 'first', 'first', expression='first')
        second = app.graph.add('field', 'second', 'second', expression='second')
        app.graph.link(first, second)
        app.graph.link(second, first)
        app.graph.link(sql['id'], second)
        sources = app.evidence(first)['definitionSources']
        self.assertEqual([source['id'] for source in sources], [sql['id']])

    def test_missing_definitions_do_not_borrow_a_more_distant_input(self):
        app = self.application('Sales:\nSELECT AMOUNT FROM sales;')
        sql = next(node for node in app.graph.nodes.values() if node['kind'] == 'sql')
        missing = app.graph.add('load', 'missing', 'Missing load', ref={'file': 'unexported.qvs', 'line': 1, 'endLine': 2})
        model = app.graph.add('field', 'missing-model', 'Missing model', expression='Missing model')
        app.graph.link(sql['id'], missing)
        app.graph.link(missing, model)
        self.assertEqual(app.evidence(model)['definitionSources'], [])
        empty = app.graph.add('field', 'empty', 'Empty', expression='Empty')
        self.assertEqual(app.evidence(empty)['definitionSources'], [])

    def test_shared_source_ranges_are_not_duplicated(self):
        app = self.application('Sales:\nSELECT AMOUNT FROM sales;')
        sql = next(node for node in app.graph.nodes.values() if node['kind'] == 'sql')
        alias = app.graph.add('sql', 'same-statement', 'Alias definition', ref=sql['ref'])
        model = app.graph.add('field', 'merged', 'Merged', expression='Merged')
        app.graph.link(sql['id'], model)
        app.graph.link(alias, model)
        self.assertEqual(len(app.evidence(model)['definitionSources']), 1)

    def test_nodes_with_own_references_keep_their_own_code(self):
        app = self.application('Sales:\nSELECT AMOUNT FROM sales;')
        sql = next(node for node in app.graph.nodes.values() if node['kind'] == 'sql')
        evidence = app.evidence(sql['id'])
        self.assertEqual(evidence['definitionSources'], [])
        self.assertEqual(evidence['ref'], sql['ref'])
        self.assertIn('SELECT AMOUNT FROM sales', evidence['original'])


if __name__ == '__main__':
    unittest.main()
