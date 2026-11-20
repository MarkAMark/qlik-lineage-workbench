import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/graphRelations.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ES2020 } }).outputText;
const { connectionPath, defaultAnchor, dependencyOverview, layoutLineage, nodeVisualState, relationHighlight } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));

const node = (id, kind = 'field') => ({ id, kind, label: id, confidence: 'parsed' });
const edge = (source, target) => ({ id: `${source}-${target}`, source, target, relation: 'value' });
test('visual states distinguish missing definitions, verified errors and cycle warnings without changing node identity', () => {
  assert.equal(nodeVisualState(node('valid')), '');
  assert.equal(nodeVisualState({ ...node('review'), confidence: 'review' }), 'warning');
  assert.equal(nodeVisualState({ ...node('missing', 'unresolved'), confidence: 'unresolved' }), 'missing');
  assert.equal(nodeVisualState({ ...node('expression', 'expression'), confidence: 'review', note: '表达式解析失败' }), 'error');
  assert.equal(nodeVisualState({ ...node('cycle', 'variable'), confidence: 'review', note: '存在循环依赖，需要核实。' }), 'cycle');
});
const graph = { root: 'result', nodes: [node('sourceA', 'source'), node('sourceB', 'source'), node('A'), node('B'), node('expression', 'expression'), node('result', 'usage')],
  edges: [edge('sourceA', 'A'), edge('sourceB', 'B'), edge('A', 'expression'), edge('B', 'expression'), edge('expression', 'result')] };

test('default relationship shows every expression input and the resulting field', () => {
  assert.equal(defaultAnchor(graph, graph.root), 'expression');
  assert.deepEqual(dependencyOverview(graph).inputs.map(node => node.id), ['A', 'B']);
  const { nodeTones, edgeTones } = relationHighlight(graph, 'expression');
  assert.equal(nodeTones.expression, 'focus');
  assert.equal(edgeTones['A-expression'], 'upstream');
  assert.equal(edgeTones['B-expression'], 'upstream');
  assert.equal(edgeTones['expression-result'], 'downstream');
  assert.equal(edgeTones['sourceA-A'], 'muted');
});

test('fixed layout retains measured dimensions during controlled highlight updates', () => {
  for (const n of layoutLineage(graph)) {
    assert.deepEqual(n.measured, { width: n.style.width, height: n.style.height });
    assert.equal(n.measured.width, 256);
    assert(n.measured.height >= 116);
  }
});

test('node hover previews immediate neighbors without claiming transitive edges', () => {
  const { nodeTones, edgeTones } = relationHighlight(graph, 'A', 'direct');
  assert.equal(nodeTones.sourceA, 'upstream');
  assert.equal(nodeTones.expression, 'downstream');
  assert.equal(nodeTones.result, 'muted');
  assert.equal(nodeTones.B, 'muted');
  assert.equal(edgeTones['expression-result'], 'muted');
});

test('clicked branch highlights its complete paths and keeps sibling inputs unrelated', () => {
  const { nodeTones, edgeTones } = relationHighlight(graph, 'A', 'path');
  assert.equal(nodeTones.sourceA, 'upstream');
  assert.equal(nodeTones.A, 'focus');
  assert.equal(nodeTones.expression, 'downstream');
  assert.equal(nodeTones.result, 'downstream');
  assert.equal(nodeTones.B, 'muted');
  assert.equal(nodeTones.sourceB, 'muted');
  assert.equal(edgeTones['B-expression'], 'muted');
  assert.equal(edgeTones['expression-result'], 'downstream');
});

test('inspecting a connection isolates its exact endpoints, independent of the selected node', () => {
  const { nodeTones, edgeTones } = relationHighlight(graph, 'A', 'path', 'B-expression');
  assert.equal(nodeTones.B, 'upstream');
  assert.equal(nodeTones.expression, 'downstream');
  assert.equal(nodeTones.A, 'muted');
  assert.equal(Object.values(nodeTones).filter(tone => tone !== 'muted').length, 2);
  assert.equal(Object.values(edgeTones).filter(tone => tone !== 'muted').length, 1);
  assert.equal(edgeTones['B-expression'], 'inspected');
});

test('show all restores every relationship without removing graph data', () => {
  const { nodeTones, edgeTones } = relationHighlight(graph);
  assert(Object.values(nodeTones).every(tone => tone === 'normal'));
  assert(Object.values(edgeTones).every(tone => tone === 'normal'));
  assert.equal(graph.nodes.length, 6);
  assert.equal(graph.edges.length, 5);
});

test('each edge has independent, ordered input and output ports', () => {
  const nodes = layoutLineage(graph);
  const byId = new Map(nodes.map(node => [node.id, node]));
  const inputs = byId.get('expression').data.inputs;
  assert.deepEqual(inputs.map(port => port.peer), ['A', 'B']);
  assert.notEqual(inputs[0].offset, inputs[1].offset);
  for (const edge of graph.edges) {
    assert(byId.get(edge.source).data.outputs.some(port => port.id === 'out-' + edge.id));
    assert(byId.get(edge.target).data.inputs.some(port => port.id === 'in-' + edge.id));
  }
  assert.equal(byId.get('A').position.x, byId.get('B').position.x);
  const reversed = layoutLineage({ ...graph, nodes: [...graph.nodes].reverse(), edges: [...graph.edges].reverse() });
  assert.deepEqual(reversed.find(node => node.id === 'expression').data.inputs, inputs);
});

test('large fan-in nodes have readable ports and do not overlap neighboring nodes', () => {
  const inputs = [...Array(13)].map((_, index) => node(`VOLUME_${String(index + 1).padStart(2, '0')}`));
  const fanIn = { root: 'value', nodes: [...inputs, node('value', 'load')], edges: inputs.map(input => edge(input.id, 'value')) };
  const nodes = layoutLineage(fanIn);
  const value = nodes.find(node => node.id === 'value');
  assert.equal(value.data.inputs.length, 13);
  const positions = value.data.inputs.map(port => port.offset);
  assert.equal(new Set(positions).size, 13);
  for (let i = 1; i < positions.length; i++) assert(positions[i] - positions[i - 1] >= 16);
  const columns = new Map();
  for (const node of nodes) columns.set(node.position.x, [...(columns.get(node.position.x) || []), node]);
  for (const column of columns.values()) {
    column.sort((a, b) => a.position.y - b.position.y);
    for (let i = 1; i < column.length; i++) assert(column[i - 1].position.y + column[i - 1].data.height < column[i].position.y);
  }
});

test('cycles terminate and connection curves preserve their exact endpoints', () => {
  const cyclic = { ...graph, edges: [...graph.edges, edge('expression', 'A')] };
  const highlighted = relationHighlight(cyclic, 'A', 'path');
  assert.equal(Object.keys(highlighted.edgeTones).length, cyclic.edges.length);
  assert.equal(layoutLineage(cyclic).length, cyclic.nodes.length);
  assert.match(connectionPath(10, 20, 200, 80), /^M 10,20 C .+ 200,80$/);
  assert.notEqual(connectionPath(10, 20, 200, 80), connectionPath(10, 20, 200, 96));
});
