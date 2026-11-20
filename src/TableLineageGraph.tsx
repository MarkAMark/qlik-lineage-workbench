import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { ReactFlow, Background, BackgroundVariant, BaseEdge, Controls, Handle, MarkerType, MiniMap, Panel, Position, useNodesInitialized, useReactFlow, type Edge, type EdgeProps, type Node, type NodeProps, type Viewport } from '@xyflow/react';
import { Database, Eye, Focus, LayoutDashboard, Scan, Table2, TriangleAlert } from 'lucide-react';
import { connectionPath, layoutLineage, NODE_WIDTH, relationHighlight, type Port, type RelationTone } from './graphRelations';
import { tableNodeType } from './tableGraphRelations';
import type { LineageGraphData, TableEdge, TableGraph, TableNode } from './types';

type TableFlowData = TableNode & { inputs: Port[]; outputs: Port[]; tone: RelationTone } & Record<string, unknown>;
type TableFlowNode = Node<TableFlowData, 'table'>;
type TableFlowEdge = Edge<{ edge: TableEdge; tone: RelationTone; sourceLabel: string; targetLabel: string } & Record<string, unknown>, 'table'>;
const colors = { normal: '#A9B5C4', focus: '#3478C5', upstream: '#3478C5', downstream: '#23856D', inspected: '#C66A16', muted: '#A9B5C4' };

const TableCard = memo(function TableCard({ data, selected }: NodeProps<TableFlowNode>) {
  const Icon = data.kind === 'dataset' ? LayoutDashboard : data.kind === 'table_source' ? Database : Table2;
  return <div className={`table-flow-node ${data.kind} tone-${data.tone} ${selected ? 'is-selected' : ''}`} data-tone={data.tone} title={`${data.label}${data.connection ? '\n' + data.connection : ''}`}>
    {data.inputs.map(port => <Handle key={port.id} id={port.id} type="target" position={Position.Left} isConnectable={false} style={{ top: port.offset }} className="trace-port numbered-port"><span>{port.index}</span></Handle>)}
    <div className="table-node-kind"><Icon size={13} /><span>{tableNodeType(data)}</span>{data.status !== 'complete' && <TriangleAlert size={12} />}</div>
    <strong className="table-node-name">{data.label}</strong>
    <span className="table-node-meta">{data.versionCount > 1 ? `v${data.version} / ${data.versionCount} · ` : ''}{data.kind === 'dataset' ? `${data.fieldCount} 个字段使用处` : `${data.kind === 'table_source' ? '已识别引用' : '已识别'} ${data.fieldCount} 列`}</span>
    <span className="table-node-foot">{data.focusLabel || data.sheetTitle || data.connection || (data.schemaStatus !== 'known' ? '字段清单未完整确认' : data.dropped ? '保留历史来源' : '静态脚本依赖')}</span>
    {data.outputs.map(port => <Handle key={port.id} id={port.id} type="source" position={Position.Right} isConnectable={false} style={{ top: port.offset }} className="trace-port numbered-port"><span>{port.index}</span></Handle>)}
  </div>;
});

const TableConnection = memo(function TableConnection({ id, sourceX, sourceY, targetX, targetY, markerEnd, data }: EdgeProps<TableFlowEdge>) {
  const path = connectionPath(sourceX, sourceY, targetX, targetY);
  const tone = data?.tone || 'normal';
  const edge = data?.edge;
  const contextOnly = !edge?.roles.includes('data') && edge?.roles.includes('context');
  const consumption = edge?.relation === 'consumption';
  const active = ['upstream', 'downstream', 'inspected'].includes(tone);
  const label = consumption ? '图表消费' : `${edge?.operationKinds.filter(k => k !== 'LOAD TABLE').join(' → ') || '加载'}${edge?.roles.includes('context') ? ' · 行集上下文' : ''}`;
  return <g className="table-connection" data-connection-id={id} data-tone={tone}>
    <title>{data?.sourceLabel} → {data?.targetLabel} · {label} · 点击查看代码</title>
    <path d={path} fill="none" stroke="#fbfcfd" strokeWidth={7} pointerEvents="none" />
    <BaseEdge id={id} path={path} markerEnd={markerEnd} interactionWidth={24} style={{ stroke: tone === 'normal' && consumption ? '#657386' : colors[tone], strokeWidth: active ? 3 : 2, strokeDasharray: consumption ? '3 4' : contextOnly ? '7 5' : undefined, opacity: tone === 'muted' ? .48 : 1, vectorEffect: 'non-scaling-stroke' }} />
    {active && <text x={(sourceX + targetX) / 2} y={(sourceY + targetY) / 2 - 9} textAnchor="middle" className="table-edge-label" pointerEvents="none">{label}</text>}
  </g>;
});
const nodeTypes = { table: TableCard };
const edgeTypes = { table: TableConnection };

function TableViewport({ request, graph }: { request: { id: string; serial: number }; graph: TableGraph }) {
  const initialized = useNodesInitialized();
  const previous = useRef(request.serial);
  const { fitView } = useReactFlow();
  const focus = (id: string) => {
    const ids = new Set([id, ...graph.edges.filter(e => e.source === id || e.target === id).flatMap(e => [e.source, e.target])]);
    void fitView({ nodes: [...ids].map(id => ({ id })), padding: .2, maxZoom: 1, duration: 180 });
  };
  useEffect(() => {
    if (initialized && request.serial !== previous.current) { previous.current = request.serial; focus(request.id); }
  }, [initialized, request]);
  return <Panel position="top-left" className="viewport-actions"><button onClick={() => { void fitView({ padding: .15, maxZoom: 1, duration: 180 }); }}><Scan size={12} />全图概览</button><button disabled={!request.id} onClick={() => focus(request.id)}><Focus size={12} />定位当前表</button></Panel>;
}

export default memo(function TableLineageGraph({ graph, selected, selectedEdge, request, onSelect, onEdgeSelect, savedViewport, onViewportChange }: {
  graph: TableGraph; selected: string; selectedEdge: string; request: { id: string; serial: number };
  onSelect: (id: string) => void; onEdgeSelect: (edge: TableEdge) => void;
  savedViewport?: Viewport; onViewportChange: (viewport: Viewport) => void;
}) {
  const [hovered, setHovered] = useState('');
  const restored = useRef(!!savedViewport);
  const [hoveredEdge, setHoveredEdge] = useState('');
  const [showAll, setShowAll] = useState(false);
  useEffect(() => { setShowAll(false); }, [selected, selectedEdge]);
  const basic = useMemo<LineageGraphData>(() => ({ root: graph.root, status: 'complete', sourceCount: 0, reviewCount: 0, unresolvedCount: 0,
    nodes: graph.nodes.map(node => ({ ...node, kind: node.kind === 'table_source' || node.kind === 'table_unresolved' ? 'source' : node.kind })), edges: graph.edges }), [graph]);
  const layout = useMemo(() => layoutLineage(basic), [basic]);
  const highlight = useMemo(() => relationHighlight(basic, hovered || (showAll ? '' : selected), hovered ? 'direct' : 'path', hoveredEdge || (showAll ? '' : selectedEdge)), [basic, hovered, selected, showAll, hoveredEdge, selectedEdge]);
  const byId = useMemo(() => new Map(graph.nodes.map(n => [n.id, n])), [graph]);
  const nodes = useMemo<TableFlowNode[]>(() => layout.map(node => {
    const height = Number(node.style?.height || 88), nextHeight = height + 30;
    return { id: node.id, type: 'table', position: node.position, selected: node.id === selected,
      measured: { width: NODE_WIDTH, height: nextHeight }, style: { width: NODE_WIDTH, height: nextHeight },
      data: { ...byId.get(node.id)!, tone: highlight.nodeTones[node.id],
        inputs: node.data.inputs.map(p => ({ ...p, offset: p.offset * nextHeight / height })),
        outputs: node.data.outputs.map(p => ({ ...p, offset: p.offset * nextHeight / height })) } };
  }), [layout, selected, byId, highlight]);
  const edges = useMemo<TableFlowEdge[]>(() => graph.edges.map(edge => ({ ...edge, type: 'table',
    sourceHandle: `out-${edge.id}`, targetHandle: `in-${edge.id}`, ariaRole: 'button',
    ariaLabel: `查看表关系 ${byId.get(edge.source)?.label} → ${byId.get(edge.target)?.label}`,
    domAttributes: { 'aria-haspopup': edge.relation === 'consumption' ? undefined : 'dialog', onKeyDown: event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); onEdgeSelect(edge); }
    } },
    markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: colors[highlight.edgeTones[edge.id]] },
    data: { edge, tone: highlight.edgeTones[edge.id], sourceLabel: byId.get(edge.source)?.label || '', targetLabel: byId.get(edge.target)?.label || '' },
  })), [graph, byId, highlight, onEdgeSelect]);
  return <div className="table-lineage-graph"><ReactFlow<TableFlowNode, TableFlowEdge> nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
    defaultViewport={savedViewport} fitView={!restored.current} fitViewOptions={{ padding: .15, maxZoom: .95 }} onMoveEnd={(_, viewport) => onViewportChange(viewport)} nodesDraggable={false} nodesConnectable={false}
    minZoom={.025} maxZoom={1.7} deleteKeyCode={null} edgesFocusable
    onNodeClick={(_, node) => { setShowAll(false); onSelect(node.id); }}
    onNodeMouseEnter={(_, node) => { setHoveredEdge(''); setHovered(node.id); }} onNodeMouseLeave={() => setHovered('')}
    onEdgeMouseEnter={(_, edge) => { setHovered(''); setHoveredEdge(edge.id); }} onEdgeMouseLeave={() => setHoveredEdge('')}
    onEdgeClick={(event, edge) => { event.stopPropagation(); onEdgeSelect(edge.data!.edge); }} onPaneClick={() => setShowAll(true)}
    aria-label="表级血缘图，实线表示数据输入，虚线表示行集上下文，点线表示图表消费">
    <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#d7dfe3" />
    <TableViewport request={request} graph={graph} />
    <Panel position="bottom-left" className="viewport-actions"><button onClick={() => setShowAll(v => !v)}><Eye size={12} />{showAll ? '恢复关系高亮' : '显示全部连线'}</button></Panel>
    <MiniMap nodeColor={node => node.data.kind === 'dataset' ? '#a58dc2' : node.data.kind === 'table_source' ? '#56aa98' : '#7294c1'} pannable zoomable />
    <Controls showInteractive={false} />
  </ReactFlow></div>;
});
