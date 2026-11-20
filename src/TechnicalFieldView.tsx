import { useEffect, useRef, useState } from 'react';
import type { Viewport } from '@xyflow/react';
import { ArrowLeft, ArrowRight, Code2, Download, GitBranch, Layers3, Search, Table2 } from 'lucide-react';
import EvidencePanel from './EvidencePanel';
import EdgeCodeDialog from './EdgeCodeDialog';
import LineageGraph from './LineageGraph';
import NodeCodeDialog from './NodeCodeDialog';
import LineageModeSwitch from './LineageModeSwitch';
import { apiParams, saveJson, useResource } from './api';
import { StateMessage, StatusBadge } from './components';
import type { Evidence, Field, LineageEdge, TableDetail, TechnicalFieldRef, TechnicalLineage } from './types';

export default function TechnicalFieldView({ appId, snapshot, revision, reference, active, onTables, onBack, onOpenField, onOpenUsage }: {
  appId: string; snapshot: string; revision: number; reference: TechnicalFieldRef; active: boolean;
  onTables: () => void; onBack: () => void; onOpenField: (field: TechnicalFieldRef) => void; onOpenUsage: (field: Field) => void;
}) {
  const [selected, setSelected] = useState('');
  const [codeNode, setCodeNode] = useState('');
  useEffect(() => { setCodeNode(''); }, [active, reference, revision]);
  const [edge, setEdge] = useState<LineageEdge | null>(null);
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const viewports = useRef<Record<string, Viewport>>({});
  const resource = useResource<TechnicalLineage>('/api/table-field-lineage?' + apiParams({ app: appId, snapshot, ...reference }), revision);
  const trace = resource.data?.technicalField.version === reference.version && resource.data.technicalField.field === reference.field ? resource.data : null;
  const columns = useResource<TableDetail>('/api/table-detail?' + apiParams({ app: appId, snapshot, table: reference.version, q: query, offset }), revision);
  const syntheticRoot = trace?.rootEvidence && selected === trace.root;
  const evidenceResource = useResource<Evidence>(selected && !syntheticRoot ? '/api/evidence?' + apiParams({ app: appId, snapshot, node: selected }) : null, revision);
  const evidence = syntheticRoot ? trace.rootEvidence! : evidenceResource.data?.id === selected ? evidenceResource.data : null;
  useEffect(() => { setSelected(trace?.root || ''); setEdge(null); }, [trace]);
  useEffect(() => { setQuery(''); setOffset(0); }, [reference.version]);
  useEffect(() => { if (!active) setEdge(null); }, [active]);
  const viewportKey = `${reference.version}:${reference.field}`;
  const source = trace?.nodes.find(n => n.id === edge?.source);
  const target = trace?.nodes.find(n => n.id === edge?.target);
  const [exportError, setExportError] = useState('');
  const [exporting, setExporting] = useState(false);
  const exportTrace = async () => {
    if (!trace) return;
    setExporting(true); setExportError('');
    try {
      const nodes = await Promise.all(trace.nodes.map(async node => {
        if (trace.rootEvidence && node.id === trace.root) return trace.rootEvidence;
        const response = await fetch('/api/evidence?' + apiParams({ app: appId, snapshot, node: node.id }));
        const body = await response.json(); if (!response.ok) throw new Error(body.error); return body as Evidence;
      }));
      saveJson({ ...trace, nodes, rootType: 'technicalField' }, `${trace.technicalField.table}-${reference.field}.technical-lineage.json`);
    } catch (error) { setExportError((error as Error).message); }
    finally { setExporting(false); }
  };
  return <main className="lineage-page technical-field-page" hidden={!active}>
    <LineageModeSwitch mode="field" onFields={() => {}} onTables={onTables}><button className="button" onClick={onBack}><ArrowLeft size={14} />返回原表</button></LineageModeSwitch>
    <div className="page-heading lineage-heading"><div><div className="section-eyebrow">TECHNICAL FIELD LINEAGE</div><h1>表字段的每一层来源。</h1><p>以具体表版本中的字段为根，无需 Sheet 使用处。</p></div><button className="button" disabled={!trace || exporting} onClick={() => { void exportTrace(); }}><Download size={14} />{exporting ? '正在导出…' : '导出字段与代码'}</button></div>
    <section className="technical-root-context"><Table2 size={18} /><strong>{trace?.technicalField.table || '表版本'}</strong><ArrowRight size={14} /><code>{reference.field}</code><span>技术字段 · {columns.data?.node.version ? `v${columns.data.node.version}` : '源资产'} · {columns.data?.node.dropped ? '已删除表的历史字段' : '保留明确版本'}</span></section>
    {exportError && <p className="table-message" role="status">{exportError}</p>}
    <div className="technical-field-grid"><section className="table-list-panel"><div className="field-panel-title"><h2>此版本的已识别字段</h2><span>{columns.data?.fieldTotal || 0}</span></div><div className="search-box table-list-search"><Search size={14} /><input aria-label="搜索技术字段" value={query} onChange={event => { setQuery(event.target.value); setOffset(0); }} placeholder="搜索此表字段" /></div>
      {columns.loading || columns.error ? <StateMessage error={columns.error} /> : <div className="table-node-list">{columns.data?.fields.map(column => <button key={column.name} className={`table-list-row ${column.name === reference.field ? 'active' : ''}`} onClick={() => onOpenField({ version: reference.version, field: column.name })}><Code2 size={14} /><div><strong>{column.name}</strong><small>{column.nodeId ? '已有字段计算路径' : '引用已识别，映射待核实'}</small></div></button>)}</div>}
      {(columns.data?.fieldTotal || 0) > 200 && <div className="table-pagination"><button disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 200))}>上一页</button><button disabled={offset + 200 >= (columns.data?.fieldTotal || 0)} onClick={() => setOffset(n => n + 200)}>下一页</button></div>}
    </section><div className="trace-workspace">{resource.loading || resource.error || !trace ? <StateMessage error={resource.error} text="正在追溯此版本的字段…" /> : <>
      <section className="selected-field-card"><div className="selected-field-top"><div><span className="section-eyebrow">TECHNICAL COLUMN</span><h2>{trace.technicalField.table}.{reference.field}</h2></div><StatusBadge status={trace.status} /></div><div className="selected-field-bottom"><span>{trace.nodes.length} 个字段节点</span><span>{trace.sourceCount} 个源字段</span><span>技术字段身份与图表字段使用处分别保留</span></div></section>
      <section className="graph-card"><div className="graph-toolbar"><div className="graph-title"><GitBranch size={16} /><h2>字段计算依赖</h2><span>源列 → 当前表版本字段</span></div></div><div className="graph-canvas">{active && <LineageGraph key={viewportKey} graph={trace} rootEvidence={trace.rootEvidence} selected={selected} onSelect={setSelected} evidenceContext={{ appId, snapshot }} onCode={id => { setSelected(id); setCodeNode(id); }} onEdgeSelect={setEdge} savedViewport={viewports.current[viewportKey]} onViewportChange={viewport => { viewports.current[viewportKey] = viewport; }} />}</div></section>
      <section className="technical-table-context"><div><Layers3 size={15} /><strong>表级行集与加工上下文</strong><button className="table-drill-link" onClick={onTables}>在表级视图中查看 <ArrowRight size={13} /></button></div><p>下列操作作用于表或行集，单独展示；没有字段映射时不生成数值依赖连线。</p>{trace.tableContext.map(context => <span className="technical-context-chip" key={context.id}>{context.source} · {context.operationKinds.join(' → ')}{context.roles.includes('context') ? ' · 包含行集上下文' : ''}</span>)}{!trace.tableContext.length && <span>未识别到独立上游表操作。</span>}</section>
      <EvidencePanel appId={appId} snapshot={snapshot} revision={revision} active={active} evidence={evidence} loading={!syntheticRoot && evidenceResource.loading} error={syntheticRoot ? '' : evidenceResource.error} field={undefined} onJump={onOpenUsage} onNodeSelect={setSelected} />
    </>}</div></div>
    {active && codeNode && <NodeCodeDialog key={codeNode} appId={appId} snapshot={snapshot} nodeId={codeNode} evidence={codeNode === trace?.root ? trace.rootEvidence : undefined} revision={revision} onClose={() => setCodeNode('')} />}
    {active && edge && source && target && <EdgeCodeDialog appId={appId} snapshot={snapshot} edge={edge} source={source} target={target} revision={revision} onClose={() => setEdge(null)} />}
  </main>;
}
