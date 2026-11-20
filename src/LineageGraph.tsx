import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ReactFlow, Background, BackgroundVariant, BaseEdge, Controls, ControlButton, MiniMap, Handle, Position, MarkerType, Panel, useNodesInitialized, useReactFlow, useNodesState, useUpdateNodeInternals, type Edge, type EdgeProps, type NodeProps, type Viewport } from '@xyflow/react';
import { ArrowRight, Braces, Code2, Database, Eye, FileCode2, Focus, FunctionSquare, GitBranch, Info, Layers3, MousePointer2, RotateCcw, Scan, Sigma, Table2, TriangleAlert, Variable } from 'lucide-react';
import { connectionPath, defaultAnchor, dependencyOverview, graphIndex, layoutLineage, nodeVisualState, relationHighlight, type FlowNode, type RelationTone } from './graphRelations';
import type { LineageGraphData as Lineage, LineageEdge } from './types';
import type { Evidence } from './types';
import { apiParams, useResource } from './api';
import '@xyflow/react/dist/style.css';

export const KIND_LABELS: Record<string, string> = { source: '数据源字段', sql: 'SQL 转换', load: 'Qlik LOAD', field: '数据模型字段', variable: '变量', master: '主维度 / 主度量', expression: '图表表达式', usage: 'Sheet 字段', unresolved: '待补充定义' };
const icons = { source: Database, sql: FileCode2, load: Layers3, field: Table2, variable: Variable, master: Sigma, expression: FunctionSquare, usage: GitBranch, unresolved: TriangleAlert };
const nodeColors: Record<string, string> = { source: '#23856D', sql: '#657386', load: '#657386', field: '#3478C5', variable: '#657386', master: '#3478C5', expression: '#3478C5', usage: '#163A70', unresolved: '#D6A21E' };
const lineColors: Record<RelationTone, string> = { normal: '#A9B5C4', focus: '#3478C5', upstream: '#3478C5', downstream: '#23856D', inspected: '#C66A16', muted: '#A9B5C4' };
type FlowEdge = Edge<{ tone: RelationTone; sourceLabel: string; targetLabel: string; inputIndex: number; relation: string; issue: string } & Record<string, unknown>, 'trace'>;

const TraceNode = memo(function TraceNode({ data, selected }: NodeProps<FlowNode>) {
  const [popover, setPopover] = useState<{ left: number; top: number } | null>(null);
  const element = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const popoverId = useId();
  const detail = useResource<Evidence>(popover && !data.previewEvidence && data.evidenceUrl ? data.evidenceUrl : null, 0, true);
  const evidence = data.previewEvidence || detail.data;
  const updateNodeInternals = useUpdateNodeInternals();
  useLayoutEffect(() => {
    const frame = requestAnimationFrame(() => updateNodeInternals(data.id));
    return () => cancelAnimationFrame(frame);
  }, [data.id, data.inputs, data.outputs, updateNodeInternals]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const open = () => {
    clearTimeout(timer.current);
    const rect = element.current?.getBoundingClientRect();
    if (rect) setPopover({ left: Math.max(12, Math.min(window.innerWidth - 352, rect.left)), top: rect.bottom + 308 < window.innerHeight ? rect.bottom + 8 : Math.max(12, rect.top - 308) });
  };
  const close = () => { clearTimeout(timer.current); timer.current = setTimeout(() => setPopover(null), 180); };
  const Icon = icons[data.kind as keyof typeof icons] || Braces;
  const split = data.label.lastIndexOf('.');
  const label = ['source', 'sql', 'load'].includes(data.kind) && split >= 0 ? data.label.slice(split + 1) : data.label;
  const context = data.operation === 'crosstable-value' ? `${data.table} · Crosstable 数值` : data.operation === 'crosstable-attribute' ? `${data.table} · Crosstable 字段名` : data.table || (data.kind === 'field' ? data.tables?.join(' / ') : data.kind === 'usage' ? '当前选中字段' : data.kind === 'variable' ? '变量定义 / script' : '');
  const issue = nodeVisualState(data);
  const issueLabel = { cycle: '循环依赖', missing: '缺少定义', error: '表达式错误', warning: '待核实' }[issue || 'warning'];
  return <div ref={element} data-tone={data.tone || 'normal'} data-state={issue || 'complete'} className={`trace-node kind-${data.kind} ${selected ? 'is-selected' : ''} tone-${data.tone || 'normal'} ${data.confidence !== 'parsed' ? 'needs-review' : ''}`}
    onMouseEnter={() => { clearTimeout(timer.current); timer.current = setTimeout(open, 650); }} onMouseLeave={close}
    onKeyDown={event => { if (event.key === 'Escape') { setPopover(null); event.stopPropagation(); } }}>
    {data.inputs.map(port => <Handle key={port.id} id={port.id} type="target" position={Position.Left} isConnectable={false} style={{ top: port.offset }}
      className={`trace-port ${data.inputs.length > 1 ? 'numbered-port' : ''} port-${data.edgeTones?.[port.edgeId] || 'normal'}`} title={`输入 ${port.index}`} data-edge-id={port.edgeId}>
      {data.inputs.length > 1 && <span>{port.index}</span>}
    </Handle>)}
    <div className="node-kind"><Icon size={14} /><span>{KIND_LABELS[data.kind] || data.kind}</span>{data.confidence !== 'parsed' && <TriangleAlert size={14} className="node-warning" aria-label={data.kind === 'unresolved' ? '缺少定义' : '需要核实'} />}<button className="node-info nodrag nopan" aria-label={`查看 ${data.label} 详情`} aria-expanded={!!popover} aria-controls={popover ? popoverId : undefined}
      onFocus={open} onBlur={close} onClick={event => { event.stopPropagation(); open(); requestAnimationFrame(() => document.getElementById(popoverId)?.querySelector('button')?.focus()); }}><Info size={14} /></button></div>
    <div className="node-label">{label}</div><div className="node-context">{issue ? <span className="node-issue">{issue === 'cycle' ? <RotateCcw size={12} /> : <TriangleAlert size={12} />}{issueLabel}</span> : context || `${data.inputs.length} 项输入 · ${data.outputs.length} 项输出`}</div>
    {popover && createPortal(<div id={popoverId} role="region" aria-label="节点详情" className="node-popover" style={popover}
      onMouseEnter={() => clearTimeout(timer.current)} onMouseLeave={close} onFocus={() => clearTimeout(timer.current)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) close(); }}
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); element.current?.querySelector('button')?.focus(); setPopover(null); } }}>
      <div className="popover-type"><Icon size={15} />{KIND_LABELS[data.kind] || data.kind}</div><strong>{data.label}</strong>
      <span className="popover-caption">完整表达式 / 定义</span><pre>{detail.loading ? '正在读取表达式…' : detail.error ? '表达式读取失败，请通过「查看代码」重试。' : evidence?.expression || data.expression || data.label}</pre>
      {issue && <p className="popover-issue">{issueLabel} · {data.note || '请补充定义或核对导出元数据。'}</p>}
      <div className="popover-footer"><span>输入字段 {evidence?.inputs.length ?? data.inputs.length} 项</span><button onClick={() => { setPopover(null); data.onInspect?.(data.id); }}><Code2 size={15} />查看代码<ArrowRight size={14} /></button></div>
    </div>, document.body)}
    {data.outputs.map(port => <Handle key={port.id} id={port.id} type="source" position={Position.Right} isConnectable={false} style={{ top: port.offset }}
      className={`trace-port ${data.outputs.length > 1 ? 'numbered-port' : ''} port-${data.edgeTones?.[port.edgeId] || 'normal'}`} title={`输出 ${port.index}`} data-edge-id={port.edgeId}>
      {data.outputs.length > 1 && <span>{port.index}</span>}
    </Handle>)}
  </div>;
});

const TraceEdge = memo(function TraceEdge({ id, sourceX, sourceY, targetX, targetY, markerEnd, data }: EdgeProps<FlowEdge>) {
  const path = connectionPath(sourceX, sourceY, targetX, targetY);
  const tone = data?.tone || 'normal';
  const active = ['upstream', 'downstream', 'inspected'].includes(tone);
  const color = data?.issue ? data.issue === 'warning' ? '#D6A21E' : '#C8473D' : lineColors[tone];
  return <g className={`trace-connection connection-${tone}`} data-tone={tone} data-connection-id={id}>
    <title>{data?.sourceLabel} → {data?.targetLabel} · 输入 {data?.inputIndex} · {data?.relation === 'measure-reference' ? '度量引用' : '字段计算依赖'} · 点击查看代码</title>
    <path d={path} className="connection-halo" fill="none" stroke="#fbfcfd" strokeWidth={active ? 7 : 5} vectorEffect="non-scaling-stroke" pointerEvents="none" />
    <BaseEdge id={id} path={path} markerEnd={markerEnd} interactionWidth={28} style={{ stroke: color, strokeDasharray: data?.issue ? '5 4' : undefined, strokeWidth: tone === 'inspected' ? 3 : active ? 2.5 : 2, vectorEffect: 'non-scaling-stroke', opacity: tone === 'muted' ? 0.48 : 1 }} />
    {data?.relation === 'measure-reference' && <text className="connection-relation-label" x={(sourceX + targetX) / 2} y={(sourceY + targetY) / 2 - 7} textAnchor="middle" pointerEvents="none">度量引用</text>}
  </g>;
});
const nodeTypes = { lineage: TraceNode };
const edgeTypes = { trace: TraceEdge };

type Direction = 'upstream' | 'downstream' | 'all';
function ViewportActions({ graph, overview, selected, request, restored, direction, onDirection, mode, onMode }: { graph: Lineage; overview: string[]; selected: string; request: { id: string; serial: number }; restored?: boolean; direction: Direction; onDirection: (value: Direction) => void; mode: string; onMode: (mode: string) => void }) {
  const initialized = useNodesInitialized();
  const ready = useRef(false);
  const { fitView } = useReactFlow();
  const focus = (id: string) => {
    const ids = [id, ...graph.edges.filter(e => e.target === id || e.source === id).flatMap(e => [e.source, e.target])];
    void fitView({ nodes: [...new Set(ids)].map(id => ({ id })), padding: 0.2, maxZoom: 0.95, duration: 180 });
  };
  useEffect(() => {
    if (!initialized || ready.current) return;
    ready.current = true;
    if (restored) return;
    void fitView({ nodes: overview.map(id => ({ id })), padding: 0.03, maxZoom: 1 });
  }, [initialized, fitView, overview]);
  useEffect(() => { if (initialized && request.serial) focus(request.id); }, [initialized, request]);
  return <Panel position="top-left" className="viewport-actions"><div className="canvas-view-modes" role="group" aria-label="画布范围"><button aria-pressed={mode === 'all'} title="适应画布，查看当前字段的全部已导出链路" onClick={() => { onMode('all'); void fitView({ padding: 0.13, maxZoom: 1, duration: 180 }); }}><Scan size={14} />全图概览</button><button aria-pressed={mode === 'dependencies'} title="定位当前字段、表达式与直接输入" onClick={() => { onMode('dependencies'); void fitView({ nodes: overview.map(id => ({ id })), padding: 0.03, maxZoom: 1, duration: 180 }); }}><GitBranch size={14} />表达式依赖</button><button aria-pressed={mode === 'focus'} title="定位选中节点及其直接上下游" onClick={() => { onMode('focus'); focus(selected || graph.root); }}><Focus size={14} />选中上下游</button></div><div className="canvas-directions" role="group" aria-label="血缘关系方向">{([['upstream', '上游'], ['downstream', '下游'], ['all', '完整']] as const).map(([value, label]) => <button key={value} title={`高亮当前图中相对选中节点的${label}关系；下游使用处见代码证据`} aria-pressed={direction === value} onClick={() => onDirection(value)}>{label}</button>)}</div></Panel>;
}

function ResetView({ overview, onReset }: { overview: string[]; onReset: () => void }) {
  const { fitView } = useReactFlow();
  return <ControlButton title="重置视图到表达式依赖" aria-label="重置视图" onClick={() => { onReset(); void fitView({ nodes: overview.map(id => ({ id })), padding: .03, maxZoom: 1, duration: 180 }); }}><RotateCcw size={16} /></ControlButton>;
}

export default function LineageGraph({ graph, selected, onSelect, onCode, evidenceContext, rootEvidence, expressionPreview, onEdgeSelect, savedViewport, onViewportChange }: { graph: Lineage; selected: string; onSelect: (id: string) => void; onCode?: (id: string) => void; evidenceContext?: { appId: string; snapshot: string }; rootEvidence?: Evidence; expressionPreview?: string; onEdgeSelect: (edge: LineageEdge) => void; savedViewport?: Viewport; onViewportChange?: (viewport: Viewport) => void }) {
  const restored = useRef(!!savedViewport);
  const initialNodes = useMemo(() => layoutLineage(graph), [graph]);
  const index = useMemo(() => graphIndex(graph), [graph]);
  const overview = useMemo(() => dependencyOverview(graph), [graph]);
  const [focusRequest, setFocusRequest] = useState({ id: '', serial: 0 });
  const [hoveredNode, setHoveredNode] = useState('');
  const [hoveredEdge, setHoveredEdge] = useState('');
  const [lockedEdge, setLockedEdge] = useState('');
  const [selectionHighlight, setSelectionHighlight] = useState(true);
  const [direction, setDirection] = useState<Direction>('all');
  const [canvasMode, setCanvasMode] = useState('dependencies');
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initialNodes);
  useEffect(() => { setNodes(initialNodes); setLockedEdge(''); setHoveredNode(''); setHoveredEdge(''); }, [initialNodes, setNodes]);
  useEffect(() => { setLockedEdge(''); setSelectionHighlight(true); }, [selected]);
  const chooseNode = (id: string, focus = false) => {
    setLockedEdge(''); setHoveredNode(''); setHoveredEdge(''); setSelectionHighlight(true); onSelect(id);
    if (focus) setFocusRequest(previous => ({ id, serial: previous.serial + 1 }));
  };
  const chooseEdge = useCallback((edge: LineageEdge) => {
    setHoveredNode(''); setHoveredEdge(''); setLockedEdge(edge.id); setSelectionHighlight(true); onEdgeSelect(edge);
  }, [onEdgeSelect]);
  const activeEdgeId = hoveredEdge || (!hoveredNode ? lockedEdge : '');
  const activeEdge = graph.edges.find(edge => edge.id === activeEdgeId);
  const anchor = hoveredNode || (selectionHighlight ? defaultAnchor(graph, selected) : '');
  const anchorNode = index.nodes.get(anchor);
  const scope = hoveredNode ? 'direct' : 'path';
  const highlight = useMemo(() => {
    const result = relationHighlight(graph, anchor, direction === 'all' ? scope : 'path', activeEdgeId);
    if (!activeEdgeId && direction !== 'all') {
      const opposite = direction === 'upstream' ? 'downstream' : 'upstream';
      Object.keys(result.nodeTones).forEach(id => { if (result.nodeTones[id] === opposite) result.nodeTones[id] = 'muted'; });
      Object.keys(result.edgeTones).forEach(id => { if (result.edgeTones[id] === opposite) result.edgeTones[id] = 'muted'; });
    }
    return result;
  }, [graph, anchor, scope, activeEdgeId, direction]);
  const inspectNode = useCallback((id: string) => { onSelect(id); if (onCode) onCode(id); else requestAnimationFrame(() => document.querySelector('.evidence-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); }, [onSelect, onCode]);
  const displayNodes = useMemo(() => nodes.map(node => ({ ...node, selected: node.id === selected,
    data: { ...node.data, tone: highlight.nodeTones[node.id], edgeTones: highlight.edgeTones, onInspect: inspectNode,
      previewEvidence: node.id === graph.root ? rootEvidence : undefined,
      evidenceUrl: evidenceContext ? '/api/evidence?' + apiParams({ app: evidenceContext.appId, snapshot: evidenceContext.snapshot, node: node.id }) : undefined } })), [nodes, selected, highlight, inspectNode, evidenceContext?.appId, evidenceContext?.snapshot, rootEvidence, graph.root]);
  const edges = useMemo<FlowEdge[]>(() => graph.edges.map<FlowEdge>(edge => {
    const tone = highlight.edgeTones[edge.id];
    const target = initialNodes.find(node => node.id === edge.target)!;
    const sourceState = nodeVisualState(index.nodes.get(edge.source)!);
    const targetState = nodeVisualState(index.nodes.get(edge.target)!);
    const issue = [sourceState, targetState].find(state => ['error', 'missing', 'cycle'].includes(state)) || sourceState || targetState;
    return { ...edge, type: 'trace', sourceHandle: `out-${edge.id}`, targetHandle: `in-${edge.id}`,
      className: `relation-${tone}`, zIndex: tone === 'inspected' ? 20 : tone === 'upstream' || tone === 'downstream' ? 10 : 0,
      ariaRole: 'button', ariaLabel: `查看 ${index.nodes.get(edge.source)?.label} → ${index.nodes.get(edge.target)?.label} 的代码`,
      domAttributes: { 'aria-haspopup': 'dialog', onKeyDown: event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); chooseEdge(edge); }
      } },
      markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: issue ? issue === 'warning' ? '#D6A21E' : '#C8473D' : lineColors[tone] },
      data: { tone, sourceLabel: index.nodes.get(edge.source)?.label || '', targetLabel: index.nodes.get(edge.target)?.label || '',
        inputIndex: target.data.inputs.find(port => port.edgeId === edge.id)!.index, relation: edge.relation, issue },
    };
  }), [graph.edges, initialNodes, index, highlight, chooseEdge]);
  const reset = () => { setSelectionHighlight(false); setDirection('all'); setLockedEdge(''); setHoveredNode(''); setHoveredEdge(''); };
  const expression = graph.nodes.find(node => node.kind === 'expression') || index.nodes.get(graph.root);
  const sources = graph.nodes.filter(node => node.kind === 'source');
  return <div className="lineage-graph"><div className="graph-dependencies">
      <div className="expression-panel-heading"><strong>表达式依赖 <span>{overview.inputs.length} 项输入</span></strong><strong>表达式预览</strong><button className="expression-code-action" onClick={() => expression && inspectNode(expression.id)}><Code2 size={14} />查看代码<ArrowRight size={13} /></button></div>
      <div className="expression-flow"><div className="dependency-chips">{overview.inputs.map(node => <button key={node.id} data-node-id={node.id} className={selected === node.id ? 'active' : ''} title={`${node.label}${node.tables?.length ? ' · ' + node.tables.join(' / ') : ''}`} onClick={() => chooseNode(node.id, true)}><i className={`status-indicator ${node.confidence === 'parsed' ? 'status-complete' : 'status-partial'}`} /><code>{node.label}</code></button>)}{!overview.inputs.length && <span>{graph.unresolvedCount ? '缺少可确认的字段映射；可查看原始代码或表级关系。' : '常量或生成表达式，无外部字段依赖'}</span>}</div><ArrowRight className="expression-arrow" size={18} /><code className="selected-expression">{expressionPreview ?? expression?.expression ?? expression?.label}</code></div>
      <div className="lineage-route"><Database size={13} /><span>来源</span><strong title={sources.map(node => node.label).join(' / ')}>{[...new Set(sources.map(node => node.table || node.label))].join(' / ') || '数据源定义待补充'}</strong><ArrowRight size={13} /><span>流向</span><strong>当前 Sheet 字段</strong></div>
    </div>
    <div className="relationship-inspector" data-mode={activeEdge ? 'edge' : anchorNode ? 'node' : 'all'} aria-live="polite">
      <div className="relationship-detail"><span className="relationship-mode"><MousePointer2 size={12} />{hoveredNode || hoveredEdge ? '悬停预览' : lockedEdge ? '已锁定连线' : selectionHighlight ? '关联高亮' : '全部连线'}</span>
        {activeEdge ? <div className="connection-endpoints"><button title={index.nodes.get(activeEdge.source)?.label} onClick={() => chooseNode(activeEdge.source, true)}>{index.nodes.get(activeEdge.source)?.label}</button><ArrowRight size={16} /><button title={index.nodes.get(activeEdge.target)?.label} onClick={() => chooseNode(activeEdge.target, true)}>{index.nodes.get(activeEdge.target)?.label}</button><span className="connection-input-label">输入 #{initialNodes.find(node => node.id === activeEdge.target)?.data.inputs.find(port => port.edgeId === activeEdge.id)?.index} · {activeEdge.relation === 'measure-reference' ? '度量引用' : '计算依赖'}</span></div>
          : anchorNode ? <div className="node-relationship"><strong title={anchorNode.label}>{anchorNode.label}</strong><span className="relation-upstream">直接上游 {index.incoming.get(anchor)!.length}</span><span className="relation-downstream">直接下游 {index.outgoing.get(anchor)!.length}</span></div>
            : <span className="relationship-instruction">悬停节点看直接关系，点击节点追踪完整路径，点击连线查看代码与起终点</span>}
      </div>
      <button className="relationship-reset" aria-label={selectionHighlight || lockedEdge ? '显示全部连线' : '恢复关系高亮'} onClick={() => { if (selectionHighlight || lockedEdge) reset(); else setSelectionHighlight(true); }}><Eye size={13} />{selectionHighlight || lockedEdge ? '显示全部' : '关系高亮'}</button>
    </div>
    <div className="flow-stage"><ReactFlow<FlowNode, FlowEdge> nodes={displayNodes} nodeTypes={nodeTypes} edges={edges} edgeTypes={edgeTypes} onNodesChange={onNodesChange}
      onNodeClick={(_, node) => chooseNode(node.id)} onNodeDoubleClick={(_, node) => chooseNode(node.id, true)}
      onNodeMouseEnter={(_, node) => { setHoveredEdge(''); setHoveredNode(node.id); }} onNodeMouseLeave={() => setHoveredNode('')}
      onEdgeMouseEnter={(_, edge) => { setHoveredNode(''); setHoveredEdge(edge.id); }} onEdgeMouseLeave={() => setHoveredEdge('')}
      onEdgeClick={(event, edge) => { event.stopPropagation(); const relation = graph.edges.find(item => item.id === edge.id); if (relation) chooseEdge(relation); }}
      onPaneClick={reset} defaultViewport={savedViewport} onMoveEnd={(_, viewport) => onViewportChange?.(viewport)} minZoom={0.02} maxZoom={1.7} nodesDraggable={false} nodesConnectable={false} edgesFocusable deleteKeyCode={null}
      ariaLabelConfig={{ 'controls.zoomIn.ariaLabel': '放大', 'controls.zoomOut.ariaLabel': '缩小', 'controls.fitView.ariaLabel': '适应画布', 'controls.ariaLabel': '画布缩放控制' }}
      aria-label="字段血缘图，悬停预览关系，点击节点查看代码，点击连线弹窗查看代码与起终点" proOptions={{ hideAttribution: false }}>
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#d7dfe3" />
      <ViewportActions graph={graph} overview={overview.ids} selected={selected} request={focusRequest} restored={restored.current} mode={canvasMode} onMode={setCanvasMode} direction={direction} onDirection={value => { setDirection(value); setSelectionHighlight(true); setLockedEdge(''); }} />
      <MiniMap nodeColor={node => node.data.tone === 'muted' ? '#dce4e8' : nodeColors[String(node.data.kind)] || '#94a3b8'} pannable zoomable ariaLabel="血缘缩略图" />
      <Controls showInteractive={false}><ResetView overview={overview.ids} onReset={() => setCanvasMode('dependencies')} /></Controls>
    </ReactFlow></div><div className="graph-legend unified-legend" aria-label="血缘图例"><span><i className="line-upstream" />上游输入</span><span><i className="line-downstream" />下游输出</span><span><i className="line-inspected" />当前路径</span><span><Database size={12} />数据源</span><span><FileCode2 size={12} />SQL / LOAD</span><span><FunctionSquare size={12} />模型 / 表达式</span><span><i className="legend-current" />当前字段</span><span><RotateCcw size={12} />循环依赖</span><small>箭头指向数据流向 · 点击节点查看详情，点击连线查看代码 · 方向切换作用于当前图</small></div></div>;
}
