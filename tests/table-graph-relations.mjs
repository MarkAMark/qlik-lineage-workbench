import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/tableGraphRelations.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ES2020 } }).outputText;
const { filterTableGraph, resolveTableSelection } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
const node = id => ({ id, label: id });
const edge = (source, target) => ({ id: `${source}-${target}`, source, target });
const graph = { nodes: ['raw', 'temp', 'final', 'sibling', 'chart', 'isolated'].map(node),
  edges: [edge('raw', 'temp'), edge('temp', 'final'), edge('temp', 'sibling'), edge('final', 'chart')], scope: 'app' };

test('table focus distinguishes one-hop, ancestors and unrelated branches', () => {
  assert.deepEqual(filterTableGraph(graph, 'final', 'upstream', '1').nodes.map(n => n.id), ['temp', 'final']);
  const all = filterTableGraph(graph, 'final', 'upstream', 'all');
  assert.deepEqual(all.nodes.map(n => n.id), ['raw', 'temp', 'final']);
  assert(!all.nodes.some(n => n.id === 'sibling'));
  assert.deepEqual(all.edges.map(e => e.id), ['raw-temp', 'temp-final']);
});

test('bidirectional table focus retains the business endpoint without sibling branches', () => {
  const view = filterTableGraph(graph, 'final', 'both', 'all');
  assert.deepEqual(view.nodes.map(n => n.id), ['raw', 'temp', 'final', 'chart']);
  assert(view.edges.every(e => view.nodes.some(n => n.id === e.source) && view.nodes.some(n => n.id === e.target)));
  assert.equal(graph.nodes.length, 6);
  assert.equal(graph.edges.length, 4);
});

test('restoring all keeps isolated tables and invalid selections do not silently empty a graph', () => {
  assert.equal(filterTableGraph(graph, 'final', 'all', '1'), graph);
  assert.equal(filterTableGraph(graph, 'expired', 'upstream', 'all'), graph);
});

test('table traversal terminates even when given an unexpected cycle', () => {
  const cyclic = { ...graph, edges: [...graph.edges, edge('final', 'raw')] };
  const focused = filterTableGraph(cyclic, 'final', 'both', 'all');
  assert.equal(focused.nodes.filter(n => n.id === 'final').length, 1);
  assert(focused.nodes.length <= cyclic.nodes.length);
});

const app = { sheets: [{ id: 'empty', fieldCount: 0 }, { id: 'sales', fieldCount: 4 }, { id: 'targets', fieldCount: 2 }],
  charts: [{ id: 'sales-chart', sheetId: 'sales' }, { id: 'targets-chart', sheetId: 'targets' }] };

test('table selection resolves when App data arrives before a default Sheet and field', () => {
  assert.deepEqual(resolveTableSelection(app, '', ''), { sheet: 'sales', chart: 'sales-chart' });
});

test('an explicitly selected empty Sheet never inherits a chart from the previous Sheet', () => {
  assert.deepEqual(resolveTableSelection(app, 'empty', 'sales-chart', 'sales', 'sales-chart'), { sheet: 'empty', chart: '' });
});

test('stale App identifiers and charts from a different Sheet are replaced by valid current selections', () => {
  assert.deepEqual(resolveTableSelection(app, 'previous-app-sheet', 'previous-app-chart', 'targets'), { sheet: 'targets', chart: 'targets-chart' });
  assert.deepEqual(resolveTableSelection(app, 'sales', 'targets-chart'), { sheet: 'sales', chart: 'sales-chart' });
});

test('a script-only App does not invent a Sheet or chart', () => {
  assert.deepEqual(resolveTableSelection({ sheets: [], charts: [] }, 'old-sheet', 'old-chart'), { sheet: '', chart: '' });
});
