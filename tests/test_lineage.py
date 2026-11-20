import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.assessment import estimate, risk
from backend.catalog import Application, Catalog
from backend.model import Graph
from backend.script import ScriptParser, statements, strip_comments


class ScriptTests(unittest.TestCase):
    def parse(self, script):
        graph = Graph()
        parser = ScriptParser(graph, {})
        parser.parse("LIB CONNECT TO 'Oracle';\n" + script)
        return graph, parser

    def test_scanner_preserves_quotes_comments_and_source_lines(self):
        text = "// header\nSET vList='A;B';\n$(Include=[lib://Data (owner)/config.txt]);\n/* SELECT bogus; */\nT:\nSELECT a FROM real_table;"
        parts = statements(text)
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[-1].line, 5)
        self.assertIn('lib://Data (owner)', strip_comments(text))
        self.assertNotIn('bogus', strip_comments(text))

    def test_resident_alias_retains_dropped_upstream_source(self):
        graph, parser = self.parse('Raw:\nSELECT p.price AS PRICE FROM prices p;\nFinal:\nLOAD PRICE * 2 AS TOTAL Resident Raw;\nDROP TABLE Raw;')
        self.assertNotIn('Raw', parser.tables)
        root = parser.resolve('TOTAL')
        nodes = [graph.nodes[n] for n in graph.ancestors(root)]
        self.assertEqual([(n['table'], n['field']) for n in nodes if n['kind'] == 'source'], [('PRICES', 'PRICE')])
        self.assertTrue(any(n['kind'] == 'load' and 'PRICE * 2' in n['expression'] for n in nodes))

    def test_multiline_drop_fields_only_changes_named_tables(self):
        graph, parser = self.parse('A:\nSELECT id AS ID, a AS AMOUNT FROM one;\nB:\nSELECT id AS ID, b AS PRICE FROM two;\nDROP Fields ID\n,AMOUNT\nFROM A;')
        self.assertNotIn('ID', parser.tables['A'].fields)
        self.assertNotIn('AMOUNT', parser.tables['A'].fields)
        self.assertIn('ID', parser.tables['B'].fields)
        self.assertEqual({n['table'] for n in graph.trace(parser.resolve('ID'))['nodes'] if n['kind'] == 'source'}, {'TWO'})

    def test_sql_union_uses_column_positions_and_subqueries(self):
        graph, parser = self.parse('T:\nSELECT x.p AS VALUE FROM (SELECT p FROM left_prices) x UNION ALL SELECT q AS DIFFERENT_ALIAS FROM right_prices;')
        nodes = graph.trace(parser.resolve('VALUE'))['nodes']
        sources = {(n['table'], n['field']) for n in nodes if n['kind'] == 'source'}
        self.assertEqual(sources, {('LEFT_PRICES', 'P'), ('RIGHT_PRICES', 'Q')})

    def test_subquery_star_expands_known_projection_only(self):
        graph, parser = self.parse('T:\nSELECT * FROM (SELECT p AS PRICE FROM prices);')
        self.assertIn('PRICE', parser.tables['T'].fields)
        self.assertEqual(graph.trace(parser.resolve('PRICE'))['status'], 'complete')

    def test_unknown_star_does_not_invent_columns(self):
        graph, parser = self.parse('T:\nSELECT * FROM missing_schema;')
        trace = graph.trace(parser.resolve('UNKNOWN_COLUMN'))
        self.assertEqual(trace['status'], 'unresolved')
        self.assertEqual(trace['sourceCount'], 0)
        self.assertTrue(any(w['code'] == 'wildcard-schema' for w in parser.warnings))

    def test_crosstable_preserves_value_columns_and_generated_attribute(self):
        graph, parser = self.parse('Raw:\nCrosstable (MONTH, TOTAL_VOLUME, 2)\nLOAD ID, YEAR, VOLUME_01, VOLUME_02;\nSELECT id AS ID, year AS YEAR, a AS VOLUME_01, b AS VOLUME_02 FROM volumes;')
        self.assertEqual(set(parser.tables['Raw'].fields), {'ID', 'YEAR', 'MONTH', 'TOTAL_VOLUME'})
        trace = graph.trace(parser.resolve('TOTAL_VOLUME'))
        self.assertEqual({(n['table'], n['field']) for n in trace['nodes'] if n['kind'] == 'source'}, {('VOLUMES', 'A'), ('VOLUMES', 'B')})
        self.assertEqual(trace['status'], 'complete')
        month = graph.trace(parser.resolve('MONTH'))
        self.assertEqual(month['sourceCount'], 0)
        self.assertTrue(any(n.get('operation') == 'crosstable-attribute' for n in month['nodes']))

    def test_preceding_load_supplies_explicit_columns_through_qualified_star(self):
        graph, parser = self.parse('Raw:\nLOAD YEAR, VOLUME_01, PLANT;\nSELECT b.*, p.PLANT FROM volumes b LEFT JOIN (SELECT id, plant FROM plants) p ON b.id=p.id;')
        trace = graph.trace(parser.resolve('VOLUME_01'))
        self.assertEqual({(n['table'], n['field']) for n in trace['nodes'] if n['kind'] == 'source'}, {('VOLUMES', 'VOLUME_01')})
        self.assertEqual(trace['status'], 'complete')
        plant = graph.trace(parser.resolve('PLANT'))
        self.assertEqual({(n['table'], n['field']) for n in plant['nodes'] if n['kind'] == 'source'}, {('PLANTS', 'PLANT')})

    def test_requested_star_columns_traverse_subquery_but_not_ambiguous_stars(self):
        graph, parser = self.parse('T:\nLOAD Amount;\nSELECT * FROM (SELECT a.*, ROW_NUMBER() OVER (ORDER BY a.id) AS RN FROM sales a) x WHERE RN=1;')
        # Oracle unquoted outputs are uppercase; Qlik field names remain case-sensitive.
        self.assertEqual(graph.trace(parser.resolve('Amount'))['sourceCount'], 0)
        graph, parser = self.parse('T:\nLOAD AMOUNT;\nSELECT * FROM (SELECT a.*, ROW_NUMBER() OVER (ORDER BY a.id) AS RN FROM sales a) x WHERE RN=1;')
        trace = graph.trace(parser.resolve('AMOUNT'))
        self.assertEqual({(n['table'], n['field']) for n in trace['nodes'] if n['kind'] == 'source'}, {('SALES', 'AMOUNT')})
        graph, parser = self.parse('T:\nLOAD AMOUNT;\nSELECT a.*, b.* FROM sales a JOIN refunds b ON a.id=b.id;')
        self.assertEqual(graph.trace(parser.resolve('AMOUNT'))['status'], 'unresolved')

    def test_preceding_load_over_resident_is_applied(self):
        graph, parser = self.parse('Raw:\nSELECT p AS PRICE FROM prices;\nFinal:\nLOAD PRICE*2 AS TOTAL;\nLOAD PRICE Resident Raw;\nDROP TABLE Raw;')
        trace = graph.trace(parser.resolve('TOTAL'))
        self.assertEqual(trace['status'], 'complete')
        self.assertEqual({n['field'] for n in trace['nodes'] if n['kind'] == 'source'}, {'P'})
        self.assertFalse(any(w['code'] == 'missing-preceding-source' for w in parser.warnings))

    def test_expression_identifiers_and_unknown_mixed_case_are_not_silently_omitted(self):
        graph, parser = self.parse('T:\nSELECT a AS "Sales Amount", b AS "收入", c AS "vAmount" FROM sales;')
        variable = graph.add('variable', 'vAmount', 'vAmount', expression='123')
        parser.variables['vAmount'] = variable
        expression = graph.add('expression', 'measure', 'measure')
        parser.bind(expression, 'Sum([Sales Amount]) + Sum(收入) + Sum([vAmount]) + Sum(MissingAmount)')
        trace = graph.trace(expression)
        self.assertEqual({n['field'] for n in trace['nodes'] if n['kind'] == 'source'}, {'A', 'B', 'C'})
        self.assertTrue(any(n['kind'] == 'unresolved' and n['label'] == 'MissingAmount' for n in trace['nodes']))
        self.assertNotIn(variable, graph.incoming[expression])

    def test_load_clause_keywords_inside_strings_are_not_treated_as_source_clauses(self):
        graph, parser = self.parse('T:\nLOAD AMOUNT, \'FROM\' AS TAG;\nSELECT amount AS AMOUNT FROM sales;')
        self.assertEqual(graph.trace(parser.resolve('AMOUNT'))['status'], 'complete')

    def test_set_search_literals_and_dollar_variables_have_distinct_dependencies(self):
        graph, parser = self.parse('T:\nSELECT amount AS AMOUNT, region AS REGION FROM sales;')
        variable = graph.add('variable', 'vRegion', 'vRegion', expression="'EU'")
        parser.variables['vRegion'] = variable
        node = graph.add('expression', 'measure', 'measure')
        parser.bind(node, 'Sum({<REGION={"$(vRegion)*"}>} AMOUNT) + 1e6')
        trace = graph.trace(node)
        self.assertEqual(trace['status'], 'complete')
        self.assertIn(variable, graph.incoming[node])
        self.assertEqual({n['field'] for n in trace['nodes'] if n['kind']=='source'}, {'REGION', 'AMOUNT'})

    def test_same_field_across_tables_is_not_arbitrarily_resolved(self):
        graph, parser = self.parse('A:\nSELECT id AS ID, a FROM one;\nB:\nSELECT id AS ID, b FROM two;')
        trace = graph.trace(parser.resolve('ID'))
        self.assertEqual(trace['status'], 'partial')
        self.assertEqual({n['table'] for n in trace['nodes'] if n['kind'] == 'source'}, {'ONE', 'TWO'})

    def test_concatenate_keeps_both_row_sources_without_cycles(self):
        graph, parser = self.parse('T:\nSELECT v AS V FROM one;\nCONCATENATE (T)\nSELECT w AS V FROM two;')
        root = parser.resolve('V')
        nodes = graph.trace(root)['nodes']
        self.assertEqual({n['table'] for n in nodes if n['kind'] == 'source'}, {'ONE', 'TWO'})
        self.assertTrue(all(e['source'] != e['target'] for e in graph.edges.values()))

    def test_qlik_field_case_is_preserved(self):
        graph, parser = self.parse('T:\nSELECT YEAR_MONTH FROM calendar;')
        self.assertEqual(graph.trace(parser.resolve('Year_Month'))['status'], 'unresolved')

    def test_include_path_with_parentheses_is_not_truncated(self):
        _, parser = self.parse('$(Include=[lib://Data (owner)/config.txt]);')
        self.assertEqual(parser.includes[0]['path'], 'lib://Data (owner)/config.txt')

    def test_dynamic_table_is_not_claimed_as_a_physical_source(self):
        graph, parser = self.parse('T:\nSELECT id AS ID FROM $(vTable);')
        trace = graph.trace(parser.resolve('ID'))
        self.assertEqual(trace['status'], 'unresolved')
        self.assertEqual(trace['sourceCount'], 0)

    def test_sql_join_does_not_merge_into_previous_qlik_table(self):
        _, parser = self.parse('A:\nSELECT a FROM one;\nB:\nSELECT b FROM two LEFT JOIN\nthree ON two.id=three.id;')
        self.assertIn('A', parser.tables)
        self.assertIn('B', parser.tables)
        self.assertNotIn('B', parser.tables['A'].fields)

    def test_preceding_load_keeps_qlik_join_target(self):
        graph, parser = self.parse('A:\nSELECT id AS ID, a AS A FROM one;\nLEFT JOIN(A)\nLOAD ID, AMOUNT AS AMOUNT;\nSELECT id AS ID, b AS AMOUNT FROM two;')
        self.assertIn('AMOUNT', parser.tables['A'].fields)
        trace = graph.trace(parser.resolve('AMOUNT'))
        self.assertIn(('TWO', 'B'), {(n['table'], n['field']) for n in trace['nodes'] if n['kind'] == 'source'})

    def test_inventory_includes_predicate_inputs_but_not_cte_names(self):
        graph, parser = self.parse('T:\nWITH q AS (SELECT a.x AS X FROM value_table a WHERE EXISTS (SELECT 1 FROM filter_table b WHERE b.id=a.id)) SELECT X FROM q;')
        self.assertEqual({r['table'] for r in parser.references.values()}, {'VALUE_TABLE', 'FILTER_TABLE'})
        trace = graph.trace(parser.resolve('X'))
        self.assertEqual({n['table'] for n in trace['nodes'] if n['kind'] == 'source'}, {'VALUE_TABLE'})
        _, wildcard = self.parse('T:\nSELECT * FROM unknown_schema;')
        self.assertIn(('Oracle', 'UNKNOWN_SCHEMA'), wildcard.references)


class MetadataTests(unittest.TestCase):
    def make_app(self, root):
        folder = Path(root) / 'Demo'
        (folder / 'objects').mkdir(parents=True)
        def write(name, value): (folder / name).write_text(json.dumps(value), encoding='utf-8')
        write('app-properties.json', {'qTitle': 'Demo'})
        write('variables.json', [{'qName': 'vAmount', 'qDefinition': 'SUM(AMOUNT)'}])
        write('dimensions.json', [])
        write('measures.json', [{'qInfo': {'qId': 'M1'}, 'qMeasure': {'qDef': '$(vAmount)'}, 'qMetaDef': {'title': 'Revenue'}}])
        (folder / 'script.qvs').write_text("LIB CONNECT TO 'Oracle';\nSales:\nSELECT amount AS AMOUNT FROM sales;", encoding='utf-8')
        write('objects/master.json', {'qProperty': {'qInfo': {'qId': 'C1'}, 'visualization': 'barchart', 'title': 'Revenue Chart', 'qHyperCubeDef': {'qMeasures': [{'qLibraryId': 'M1'}]}}})
        write('objects/sheet.json', {'qProperty': {'qInfo': {'qId': 'S1', 'qType': 'sheet'}, 'qMetaDef': {'title': 'Overview'}}, 'qChildren': [{'qProperty': {'qInfo': {'qId': 'Instance'}, 'qExtendsId': 'C1'}}]})
        return folder

    def test_master_chart_master_measure_and_variable_resolve_to_sql(self):
        with tempfile.TemporaryDirectory() as root:
            app = Application(self.make_app(root))
            self.assertEqual(len(app.fields), 1)
            field = next(iter(app.fields.values()))
            trace = app.graph.trace(field['id'])
            self.assertEqual(trace['status'], 'complete')
            self.assertTrue({'master', 'variable', 'source', 'sql', 'usage'}.issubset({n['kind'] for n in trace['nodes']}))
            for node in trace['nodes']:
                if node.get('ref'):
                    evidence = app.evidence(node['id'])
                    self.assertTrue(evidence['original'])
                    self.assertNotIn('JSON 路径无法解析', evidence['original'])
            self.assertEqual(field['chartTitle'], 'Revenue Chart')
            self.assertEqual(field['masterId'], 'M1')

    def test_estimates_are_monotonic_and_validate_settings(self):
        with tempfile.TemporaryDirectory() as root:
            app = Application(self.make_app(root))
            baseline = estimate(app)
            adjusted = estimate(app, contingency=50, productivity=1.2)
            self.assertLess(baseline['lowDays'], baseline['likelyDays'])
            self.assertGreater(baseline['highDays'], baseline['likelyDays'])
            self.assertGreater(adjusted['likelyDays'], baseline['likelyDays'])
            with self.assertRaises(ValueError): estimate(app, hours_per_day=0)

    def test_variable_risk_is_propagated(self):
        self.assertEqual(risk('AGGR(SUM(AMOUNT),KEY)')['level'], 'high')
        self.assertEqual(risk('GetSelectedCount(REGION)')['level'], 'very_high')
        self.assertEqual(risk('AVG(PRICE)')['level'], 'low')
        self.assertEqual(risk("='AGGR(SUM(AMOUNT),KEY) TOTAL OSUser' + Sum([TOTAL])")['level'], 'low')

    def test_estimate_dedup_preserves_literals_and_quoted_field_names(self):
        with tempfile.TemporaryDirectory() as root:
            app = Application(self.make_app(root))
            expressions = ["IF([Sales Amount]='A B',1,0)", " IF ( [Sales Amount] = 'A B', 1, 0 ) ", "IF([SalesAmount]='AB',1,0)"]
            app.fields = {str(i): dict(expression=code, risk=risk(code), status='complete') for i, code in enumerate(expressions)}
            self.assertEqual(estimate(app)['uniqueExpressions'], 2)

    def test_chart_measure_label_references_are_scoped_and_propagate_risk(self):
        with tempfile.TemporaryDirectory() as root:
            folder = self.make_app(root)
            sheet = {'qProperty': {'qInfo': {'qId': 'S1', 'qType': 'sheet'}}, 'qChildren': []}
            for chart_id, expression in [('C1', 'AGGR(SUM(AMOUNT),AMOUNT)'), ('C2', 'SUM(AMOUNT)*2')]:
                sheet['qChildren'].append({'qProperty': {'qInfo': {'qId': chart_id}, 'visualization': 'table', 'qHyperCubeDef': {'qMeasures': [
                    {'qDef': {'qLabel': 'Revenue', 'qDef': expression}},
                    {'qDef': {'qLabel': 'Double', 'qDef': '[Revenue]*2'}},
                    {'qDef': {'qLabel': 'Constant', 'qDef': '1'}}]}}})
            (folder/'objects'/'sheet.json').write_text(json.dumps(sheet), encoding='utf-8')
            app = Application(folder)
            for field in app.fields.values():
                self.assertEqual(field['status'], 'complete')
                if field['label'] == 'Double':
                    trace = app.graph.trace(field['id'])
                    expressions = [app.graph.nodes[n['id']]['expression'] for n in trace['nodes'] if n['kind']=='expression']
                    self.assertIn('AGGR(SUM(AMOUNT),AMOUNT)' if field['chartId']=='C1' else 'SUM(AMOUNT)*2', expressions)
                    self.assertNotIn('SUM(AMOUNT)*2' if field['chartId']=='C1' else 'AGGR(SUM(AMOUNT),AMOUNT)', expressions)
                    self.assertEqual(field['risk']['level'], 'high' if field['chartId']=='C1' else 'low')
                if field['label'] == 'Constant': self.assertEqual(field['sourceCount'], 0)

    def test_master_measure_name_references_and_cycles_remain_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            folder = self.make_app(root)
            masters = [
                {'qInfo': {'qId': 'M1'}, 'qMeasure': {'qDef': '[Base Revenue]*2'}, 'qMetaDef': {'title': 'Revenue'}},
                {'qInfo': {'qId': 'M2'}, 'qMeasure': {'qDef': 'SUM(AMOUNT)'}, 'qMetaDef': {'title': 'Base Revenue'}}]
            (folder/'measures.json').write_text(json.dumps(masters), encoding='utf-8')
            app = Application(folder)
            self.assertEqual(next(iter(app.fields.values()))['status'], 'complete')
            masters[1]['qMeasure']['qDef'] = '[Revenue]'
            (folder/'measures.json').write_text(json.dumps(masters), encoding='utf-8')
            app = Application(folder)
            self.assertNotEqual(next(iter(app.fields.values()))['status'], 'complete')
            self.assertTrue(any('cycle' in w['code'] for w in app.warnings))



if __name__ == '__main__': unittest.main()
