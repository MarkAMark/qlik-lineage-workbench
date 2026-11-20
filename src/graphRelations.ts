import type { Node } from '@xyflow/react';
import type { Evidence, LineageGraphData as Lineage, LineageNode } from './types';

export const NODE_WIDTH = 256;
export type RelationTone = 'normal' | 'focus' | 'upstream' | 'downstream' | 'inspected' | 'muted';
export type Port = { id: string; edgeId: string; peer: string; index: number; offset: number };
export type TraceNodeData = LineageNode & {
  height: number;
  inputs: Port[];
  outputs: Port[];
  tone?: RelationTone;
  edgeTones?: Record<string, RelationTone>;
  onInspect?: (id: string) => void;
  evidenceUrl?: string;
  previewEvidence?: Evidence;
} & Record<string, unknown>;
export type FlowNode = Node<TraceNodeData, 'lineage'>;
export type LineageEdge = Lineage['edges'][number];

export function nodeVisualState(node: LineageNode): 'cycle' | 'missing' | 'error' | 'warning' | '' {
  if (/循环|circular|cycle/i.test(node.note || '')) return 'cycle';
  if (/表达式错误|解析失败|syntax error|parse error/i.test(node.note || '')) return 'error';
  if (node.kind === 'unresolved' || node.confidence === 'unresolved') return 'missing';
  return node.confidence === 'parsed' ? '' : 'warning';
}

export function graphIndex(graph: Lineage) {
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const incoming = new Map<string, LineageEdge[]>(graph.nodes.map(node => [node.id, []]));
  const outgoing = new Map<string, LineageEdge[]>(graph.nodes.map(node => [node.id, []]));
  for (const edge of graph.edges) {
    if (!nodes.has(edge.source) || !nodes.has(edge.target)) continue;
    incoming.get(edge.target)!.push(edge);
    outgoing.get(edge.source)!.push(edge);
  }
  return { nodes, incoming, outgoing };
}

export function layoutLineage(graph: Lineage): FlowNode[] {
  const { nodes: byId, incoming, outgoing } = graphIndex(graph);
  const remaining = new Map(graph.nodes.map(node => [node.id, outgoing.get(node.id)!.length]));
  const distance = new Map(graph.nodes.map(node => [node.id, 0]));
  const queue = graph.nodes.filter(node => !remaining.get(node.id)).map(node => node.id);
  for (let i = 0; i < queue.length; i++) {
    const current = queue[i];
    for (const edge of incoming.get(current) || []) {
      distance.set(edge.source, Math.max(distance.get(edge.source) || 0, (distance.get(current) || 0) + 1));
      remaining.set(edge.source, remaining.get(edge.source)! - 1);
      if (!remaining.get(edge.source)) queue.push(edge.source);
    }
  }
  const depth = Math.max(0, ...distance.values());
  const levels = new Map<number, LineageNode[]>();
  const heights = new Map(graph.nodes.map(node => [node.id,
    Math.max(116, 32 + (Math.max(incoming.get(node.id)!.length, outgoing.get(node.id)!.length) - 1) * 20)]));
  for (const node of graph.nodes) {
    const rank = node.kind === 'source' ? 0 : depth - (distance.get(node.id) || 0);
    if (!levels.has(rank)) levels.set(rank, []);
    levels.get(rank)!.push(node);
  }
  const levelHeight = (nodes: LineageNode[]) => nodes.reduce((sum, node) => sum + heights.get(node.id)!, 0) + Math.max(0, nodes.length - 1) * 32;
  const totalHeight = Math.max(88, ...[...levels.values()].map(levelHeight));
  const positions = new Map<string, { x: number; y: number }>();
  for (const [rank, nodes] of [...levels].sort(([a], [b]) => a - b)) {
    const average = (id: string) => {
      const parents = (incoming.get(id) || []).map(edge => edge.source).filter(id => positions.has(id));
      return parents.length ? parents.reduce((sum, id) => sum + positions.get(id)!.y + heights.get(id)! / 2, 0) / parents.length : totalHeight / 2;
    };
    nodes.sort((a, b) => average(a.id) - average(b.id) || a.label.localeCompare(b.label));
    let y = (totalHeight - levelHeight(nodes)) / 2;
    for (const node of nodes) {
      positions.set(node.id, { x: rank * (NODE_WIDTH + 48), y });
      y += heights.get(node.id)! + 32;
    }
  }
  const ports = (node: LineageNode, edges: LineageEdge[], input: boolean): Port[] => {
    const peer = (edge: LineageEdge) => input ? edge.source : edge.target;
    const ordered = [...edges].sort((a, b) => {
      const aId = peer(a), bId = peer(b);
      return positions.get(aId)!.y + heights.get(aId)! / 2 - positions.get(bId)!.y - heights.get(bId)! / 2
        || byId.get(aId)!.label.localeCompare(byId.get(bId)!.label) || a.id.localeCompare(b.id);
    });
    const height = heights.get(node.id)!;
    return ordered.map((edge, index) => ({ id: `${input ? 'in' : 'out'}-${edge.id}`, edgeId: edge.id,
      peer: peer(edge), index: index + 1, offset: ordered.length === 1 ? height / 2 : 16 + index * (height - 32) / (ordered.length - 1) }));
  };
  return graph.nodes.map(node => ({ id: node.id, type: 'lineage', position: positions.get(node.id)!,
    // Controlled highlight updates must retain measured dimensions. React Flow
    // otherwise discards handle bounds before ResizeObserver fires again.
    measured: { width: NODE_WIDTH, height: heights.get(node.id)! },
    style: { width: NODE_WIDTH, height: heights.get(node.id)! },
    data: { ...node, height: heights.get(node.id)!, inputs: ports(node, incoming.get(node.id)!, true), outputs: ports(node, outgoing.get(node.id)!, false) } }));
}

export function dependencyOverview(graph: Lineage) {
  const { nodes, incoming } = graphIndex(graph);
  const ids = new Set<string>();
  const inputs: LineageNode[] = [];
  const pending = [graph.root];
  while (pending.length) {
    const id = pending.pop()!;
    if (ids.has(id)) continue;
    ids.add(id);
    const node = nodes.get(id);
    if (!node) continue;
    const upstream = incoming.get(id) || [];
    if (['usage', 'expression', 'master', 'variable'].includes(node.kind) && upstream.length) pending.push(...upstream.map(edge => edge.source));
    else if (id !== graph.root) inputs.push(node);
  }
  inputs.sort((a, b) => a.label.localeCompare(b.label));
  return { ids: [...ids], inputs };
}

export function defaultAnchor(graph: Lineage, selected: string) {
  const { nodes, incoming } = graphIndex(graph);
  const parents = incoming.get(graph.root) || [];
  if ((!selected || selected === graph.root) && parents.length === 1 && nodes.get(graph.root)?.kind === 'usage') return parents[0].source;
  return nodes.has(selected) ? selected : graph.root;
}

export function relationHighlight(graph: Lineage, anchor = '', scope: 'direct' | 'path' = 'direct', edgeId = '') {
  const { nodes, incoming, outgoing } = graphIndex(graph);
  const nodeTones: Record<string, RelationTone> = {};
  const edgeTones: Record<string, RelationTone> = {};
  const inspected = graph.edges.find(edge => edge.id === edgeId);
  const active = !!inspected || nodes.has(anchor);
  graph.nodes.forEach(node => { nodeTones[node.id] = active ? 'muted' : 'normal'; });
  graph.edges.forEach(edge => { edgeTones[edge.id] = active ? 'muted' : 'normal'; });
  if (inspected) {
    nodeTones[inspected.source] = 'upstream'; nodeTones[inspected.target] = 'downstream';
    edgeTones[inspected.id] = 'inspected';
    return { nodeTones, edgeTones };
  }
  if (!nodes.has(anchor)) return { nodeTones, edgeTones };
  const walk = (direction: 'up' | 'down') => {
    const seen = new Set<string>([anchor]);
    const pending = [anchor];
    while (pending.length) {
      const id = pending.pop()!;
      for (const edge of (direction === 'up' ? incoming : outgoing).get(id) || []) {
        const peer = direction === 'up' ? edge.source : edge.target;
        if (seen.has(peer)) continue;
        seen.add(peer);
        if (scope === 'path') pending.push(peer);
      }
    }
    seen.delete(anchor);
    return seen;
  };
  const up = walk('up'), down = walk('down');
  up.forEach(id => { nodeTones[id] = 'upstream'; });
  down.forEach(id => { nodeTones[id] = 'downstream'; });
  nodeTones[anchor] = 'focus';
  for (const edge of graph.edges) {
    if ((edge.target === anchor || (scope === 'path' && up.has(edge.target))) && up.has(edge.source)) edgeTones[edge.id] = 'upstream';
    else if ((edge.source === anchor || (scope === 'path' && down.has(edge.source))) && down.has(edge.target)) edgeTones[edge.id] = 'downstream';
  }
  return { nodeTones, edgeTones };
}

export function connectionPath(sourceX: number, sourceY: number, targetX: number, targetY: number) {
  const bend = Math.max(44, Math.min(Math.abs(targetX - sourceX) * 0.48, 180));
  return `M ${sourceX},${sourceY} C ${sourceX + bend},${sourceY} ${targetX - bend},${targetY} ${targetX},${targetY}`;
}
