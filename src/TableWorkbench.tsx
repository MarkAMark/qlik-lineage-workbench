import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Viewport } from '@xyflow/react';
import { ArrowLeft, ArrowRight, Check, ChevronDown, Code2, Copy, Database, Download, FileCode2, GitBranch, Layers3, LayoutDashboard, LoaderCircle, Maximize2, Minimize2, RefreshCw, Search, Table2, TriangleAlert, X } from 'lucide-react';
import LineageModeSwitch from './LineageModeSwitch';
import TableLineageGraph from './TableLineageGraph';
import SourceFileView, { useSourceFile } from './SourceFileView';
import { apiParams, saveJson, useResource } from './api';
import { CodeBlock, formatTime, StateMessage, StatusBadge } from './components';
import { filterTableGraph, resolveTableSelection, tableNodeType, type TableDirection } from './tableGraphRelations';
import type { AppDetail, Field, TableContext, TableDetail, TableEdge, TableEvidence, TableGraph, TableOperation, TableScope, TechnicalFieldRef } from './types';
import './TableLineage.css';

function TableOperationCode({ operation, appId, snapshot, revision, active, initiallyOpen }: { operation: TableOperation; appId: string; snapshot: string; revision: number; active: boolean; initiallyOpen: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const [fullFile, setFullFile] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  const source = useSourceFile(appId, snapshot, revision, operation.ref, active && open && fullFile);
  const code = fullFile ? source.data?.content || '' : operation.code;
  useEffect(() => { setCopied(false); setError(''); }, [fullFile]);
  useEffect(() => { if (!copied) return; const timer = setTimeout(() => setCopied(false), 1800); return () => clearTimeout(timer); }, [copied]);
  return <details className="table-operation" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><FileCode2 size={15} /><strong>{operation.kinds.join(' → ')}</strong><span>{operation.ref.file} · L{operation.ref.line}–{operation.ref.endLine}</span><ChevronDown size={14} /></summary>
    <div className="table-operation-actions">{operation.notes.map(note => <span key={note}>{note}</span>)}<div className="segmented small" role="group" aria-label="表操作代码查看方式"><button className={!fullFile ? 'active' : ''} aria-pressed={!fullFile} onClick={() => setFullFile(false)}>原始片段</button><button className={fullFile ? 'active' : ''} aria-pressed={fullFile} onClick={() => setFullFile(true)}>完整文件</button></div><button className="button" disabled={!code} onClick={async () => {
      try { await navigator.clipboard.writeText(code); setCopied(true); setError(''); }
      catch { setError('复制未完成，可在代码区选择文本后复制。'); }
    }}>{copied ? <Check size={13} /> : <Copy size={13} />}复制代码</button></div>
    {error && <p role="status" className="table-message">{error}</p>}
    {fullFile ? <SourceFileView resource={source} targetKey={operation.id} /> : <CodeBlock code={operation.code} firstLine={operation.ref.line} />}
  </details>;
}

export function TableOperations({ operations, appId, snapshot, revision, active }: { operations: TableOperation[]; appId: string; snapshot: string; revision: number; active: boolean }) {
  if (!operations.length) return <div className="empty-compact">没有独立加载代码；可从下游关系或具体字段继续查看定义。</div>;
  return <div className="table-operation-list">{operations.map((operation, i) => <TableOperationCode key={operation.id} operation={operation} appId={appId} snapshot={snapshot} revision={revision} active={active} initiallyOpen={i === 0} />)}</div>;
}

function RelationDialog({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const overflow = document.body.style.overflow;
    dialog.showModal(); document.body.style.overflow = 'hidden';
    return () => { dialog.close(); document.body.style.overflow = overflow; };
  }, []);
  return <dialog ref={ref} className="table-code-dialog" aria-label="表关系代码" onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); } }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="table-dialog-heading"><div><span className="section-eyebrow">TABLE RELATION EVIDENCE</span><h2>{title}</h2></div><button className="icon-button" autoFocus aria-label="关闭表关系代码" onClick={onClose}><X size={20} /></button></div>{children}
  </dialog>;
}

export default function TableWorkbench({ app, active, snapshot, revision, context, selectedField, sheetId, onImport, onReturnField, onSheetChange, onOpenUsage, onOpenTechnical }: {
  app: AppDetail; active: boolean; snapshot: string; revision: number; context: TableContext; selectedField: Field | undefined;
  sheetId: string; onImport: () => void; onReturnField: () => void; onSheetChange: (sheet: string) => void;
  onOpenUsage: (field: Field) => void; onOpenTechnical: (field: TechnicalFieldRef) => void;
}) {
  const [scope, setScope] = useState<TableScope>(context.scope);
  const [appliedContext, setAppliedContext] = useState(context.serial);
  const [scopeSheet, setScopeSheet] = useState(context.sheet || sheetId);
  const [scopeChart, setScopeChart] = useState(context.chart || selectedField?.chartId || '');
  const [includeContext, setIncludeContext] = useState(true);
  const [query, setQuery] = useState('');
  const [fieldQuery, setFieldQuery] = useState('');
  const [selected, setSelected] = useState(context.version);
  const [selectedEdge, setSelectedEdge] = useState('');
  const [direction, setDirection] = useState<TableDirection>('all');
  const [depth, setDepth] = useState<'1' | 'all'>('all');
  const [tab, setTab] = useState<'fields' | 'code' | 'usage'>('fields');
  const [offset, setOffset] = useState(0);
  const [request, setRequest] = useState({ id: '', serial: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [message, setMessage] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportRange, setExportRange] = useState<'current' | 'app'>('current');
  const viewports = useRef<Record<string, Viewport>>({});
  useEffect(() => { if (!active) { setFullscreen(false); setDialog(false); } }, [active]);
  useEffect(() => {
    setScope(context.scope); setScopeSheet(context.sheet || sheetId); setScopeChart(context.chart || selectedField?.chartId || '');
    setSelected(context.version); setSelectedEdge(''); setDirection('all'); setMessage(''); setOffset(0); setFieldQuery(''); setDialog(false);
    setAppliedContext(context.serial);
  }, [context.serial]);
  useEffect(() => { setOffset(0); setFieldQuery(''); }, [selected, selectedEdge]);
  useEffect(() => {
    const handle = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) setFullscreen(false); };
    window.addEventListener('keydown', handle); return () => window.removeEventListener('keydown', handle);
  }, []);
  const technical = scope === 'field' && !!context.version;
  const usageId = app.fields.some(field => field.id === context.usage) ? context.usage : selectedField?.id || '';
  const selection = resolveTableSelection(app, scopeSheet, scopeChart, sheetId, selectedField?.chartId);
  const params: Record<string, string | number> = { app: app.id, snapshot, scope };
  if (scope === 'sheet' || scope === 'chart') params.sheet = selection.sheet;
  if (scope === 'chart') params.chart = selection.chart;
  if (scope === 'field') {
    if (technical) { params.version = context.version; params.field = context.field; }
    else params.usage = usageId;
  }
  if (!includeContext) params.context = 0;
  const queryString = apiParams(params);
  const resource = useResource<TableGraph>(active && appliedContext === context.serial ? '/api/table-lineage?' + queryString : null, revision, true);
  const graph = resource.data?.snapshot === snapshot ? resource.data : null;
  useEffect(() => {
    if (!graph) return;
    if (selected && !graph.nodes.some(n => n.id === selected)) { setSelected(''); setDirection('all'); }
    if (selectedEdge && !graph.edges.some(e => e.id === selectedEdge)) setSelectedEdge('');
  }, [graph]);
  const visible = useMemo(() => graph ? filterTableGraph(graph, selected, direction, depth) : null, [graph, selected, direction, depth]);
  const selectedNode = graph?.nodes.find(n => n.id === selected);
  const edge = graph?.edges.find(e => e.id === selectedEdge);
  const tableResource = useResource<TableDetail>(active && selectedNode ? '/api/table-detail?' + apiParams({ app: app.id, snapshot, table: selected, q: fieldQuery, offset }) : null, revision, true);
  const evidenceResource = useResource<TableEvidence>(active && edge && edge.relation !== 'consumption' ? '/api/table-evidence?' + apiParams({ app: app.id, snapshot, edge: edge.id, offset }) : null, revision, true);
  const detail = tableResource.data?.node.id === selected ? tableResource.data : null;
  const evidence = evidenceResource.data?.edge.id === selectedEdge ? evidenceResource.data : null;
  const filtered = useMemo(() => (graph?.nodes || []).filter(node => `${node.label} ${node.connection} ${node.sheetTitle || ''} ${node.fieldNames.join(' ')}`.toLowerCase().includes(query.toLowerCase())), [graph, query]);
  const viewportKey = `${queryString}:${direction}:${depth}:${direction === 'all' ? '' : selected}`;
  const onViewportChange = useCallback((viewport: Viewport) => { viewports.current[viewportKey] = viewport; }, [viewportKey]);
  const chooseNode = useCallback((id: string) => { setSelected(id); setSelectedEdge(''); setTab('fields'); setMessage(''); setRequest(r => ({ id, serial: r.serial + 1 })); }, []);
  const chooseEdge = useCallback((item: TableEdge) => {
    if (item.relation === 'consumption') { chooseNode(item.target); setTab('usage'); return; }
    setSelectedEdge(item.id); setTab('code'); setDialog(true); setMessage('');
  }, [chooseNode]);
  const exportJson = async () => {
    if (!visible) return;
    setExporting(true); setMessage('');
    try {
      let exported = visible;
      if (exportRange === 'app') {
        const response = await fetch('/api/table-lineage?' + apiParams({ app: app.id, snapshot, scope: 'app' }));
        const body = await response.json(); if (!response.ok) throw new Error(body.error); exported = body as TableGraph;
      }
      const operations = await Promise.all(exported.edges.filter(e => e.relation !== 'consumption').map(async e => {
        let merged: TableEvidence | null = null;
        let start = 0;
        do {
          const response = await fetch('/api/table-evidence?' + apiParams({ app: app.id, snapshot, edge: e.id, offset: start, limit: 1000 }));
          const body = await response.json(); if (!response.ok) throw new Error(body.error);
          const page = body as TableEvidence;
          if (!merged) merged = { ...page, fieldMappings: [...page.fieldMappings] };
          else merged.fieldMappings.push(...page.fieldMappings);
          start += page.fieldMappings.length;
          if (!page.fieldMappings.length && start < page.mappingTotal) throw new Error('字段映射分页未完整返回，请重新导出。');
        } while (start < merged.mappingTotal);
        return { ...merged, offset: 0, fieldMappingsComplete: true };
      }));
      saveJson({ ...exported, exportRange, view: { direction: exportRange === 'app' ? 'all' : direction, depth, selected }, evidence: operations,
        exportedAt: new Date().toISOString(), note: '静态导出元数据；图表逻辑数据集是展示容器；行集上下文不等于字段数值依赖。' }, `${app.name}-table-lineage-${exportRange}.json`);
    } catch (error) { setMessage('导出失败：' + (error as Error).message); }
    finally { setExporting(false); }
  };
  const csvParams: Record<string, string | number> = exportRange === 'app' ? { app: app.id, snapshot, scope: 'app' } : { ...params, edges: visible?.edges.map(e => e.id).join(',') || 'none' };
  const chartOptions = [...new Map(app.charts.filter(c => c.sheetId === selection.sheet).map(c => [c.id, c])).values()];
  const pageTotal = edge ? evidence?.mappingTotal || 0 : detail?.fieldTotal || 0;
  const operationList = edge ? evidence?.operations : detail?.operations;
  const scopedConsumers = detail?.consumers.filter(f => selectedNode?.kind !== 'dataset' || selectedNode.fieldIds?.includes(f.id)) || [];
  const pagination = pageTotal > 200 && <div className="table-pagination"><button className="button" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 200))}>上一页</button><span>{offset + 1}–{Math.min(offset + 200, pageTotal)} / {pageTotal}</span><button className="button" disabled={offset + 200 >= pageTotal} onClick={() => setOffset(n => n + 200)}>下一页</button></div>;
  const mappings = evidence && <><p className="table-detail-note">{evidence.note} 已确认 {evidence.mappingTotal} 条映射。</p>{evidence.fieldMappings.length ? <div className="table-scroll"><table className="data-table table-mappings"><thead><tr><th>来源字段</th><th>目标字段</th><th /></tr></thead><tbody>{evidence.fieldMappings.map((mapping, i) => <tr key={i}><td><code>{mapping.sourceField}</code></td><td><code>{mapping.targetField}</code></td><td><button className="table-drill-link" onClick={() => { setDialog(false); onOpenTechnical({ version: mapping.targetVersion, field: mapping.targetField }); }}>字段级血缘 <ArrowRight size={13} /></button></td></tr>)}</tbody></table></div> : <div className="empty-compact">此关系没有已确认的数值字段映射，可查看原始代码与表级上下文。</div>}{pagination}</>;

  return <main className="lineage-page table-lineage-page" hidden={!active}>
    <LineageModeSwitch mode="table" onFields={onReturnField} onTables={() => {}} />
    <div className="page-heading lineage-heading"><div><div className="section-eyebrow">TABLE LINEAGE EXPLORER</div><h1>从一张表，看清整条链路。</h1><p>查看源资产、加载逻辑表与图表逻辑数据集，沿关系下钻到字段和代码。</p></div><button className="button" onClick={onImport}><RefreshCw size={14} />重新扫描</button></div>
    <section className="table-context-bar"><div className="table-app-name"><Layers3 size={19} /><strong>{app.name}</strong></div>
      <label>查看范围<select aria-label="表血缘范围" value={scope} onChange={event => { setScope(event.target.value as TableScope); setScopeSheet(selection.sheet); setScopeChart(selection.chart); setSelected(''); setSelectedEdge(''); setDirection('all'); }}>
        <option value="app">整个 App</option><option value="field" disabled={!usageId && !context.version}>当前字段</option><option value="chart" disabled={!selection.chart}>当前图表</option><option value="sheet" disabled={!app.sheets.length}>当前 Sheet</option>
      </select></label>
      <label>Sheet<select aria-label="表血缘 Sheet" value={scope === 'app' ? '' : selection.sheet} disabled={!app.sheets.length} onChange={event => {
        const id = event.target.value; setScopeSheet(id); setScopeChart(''); setScope(id ? 'sheet' : 'app');
        setSelected(''); setSelectedEdge(''); setDirection('all'); setDialog(false); onSheetChange(id);
      }}><option value="">{app.sheets.length ? '全部 Sheet（整个 App）' : '未导出 Sheet'}</option>{app.sheets.map(s => <option key={s.id} value={s.id}>{s.title} · {s.fieldCount} 个字段</option>)}</select></label>
      {scope === 'chart' && <label>图表<select aria-label="表血缘图表" value={selection.chart} onChange={event => setScopeChart(event.target.value)}>{chartOptions.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></label>}
      <label className="table-context-toggle"><input type="checkbox" checked={includeContext} onChange={event => setIncludeContext(event.target.checked)} />包含行集上下文</label>
    </section>
    {scope === 'field' && <div className="table-current-field"><LayoutDashboard size={15} /><span>{technical ? '技术字段' : `${selectedField?.sheetTitle || ''} / ${selectedField?.chartTitle || ''}`}</span><strong>{technical ? context.field : app.fields.find(f => f.id === usageId)?.label}</strong><span>图表使用处与数据来源分别保留</span></div>}
    {message && <div className="table-message" role="status">{message}</div>}
    {resource.loading || resource.error || !graph || !visible ? <StateMessage error={resource.error} text="正在构建表级依赖…" /> : <>
      <div className="table-stat-strip"><span><Database size={15} /><strong>{graph.stats.sourceAssets}</strong> 源资产</span><span><Table2 size={15} /><strong>{graph.stats.finalTables}</strong> 最终逻辑表</span><span><Layers3 size={15} /><strong>{graph.stats.intermediateTables}</strong> 中间 / 辅助表</span><span><GitBranch size={15} /><strong>{graph.stats.relations}</strong> 关系</span><span><LayoutDashboard size={15} /><strong>{graph.stats.datasets}</strong> 图表逻辑数据集</span><span className="table-review-count"><TriangleAlert size={14} />{graph.stats.review} 项待核实</span></div>
      <div className="table-workbench-grid"><section className="table-list-panel"><div className="field-panel-title"><h2>表与逻辑数据集</h2><span>{graph.nodes.length}</span></div><div className="search-box table-list-search"><Search size={14} /><input value={query} aria-label="搜索表和逻辑数据集" placeholder="表名、连接、已识别字段…" onChange={event => setQuery(event.target.value)} /></div>
        <div className="table-node-list">{filtered.map(node => <button key={node.id} data-table-id={node.id} className={`table-list-row ${selected === node.id ? 'active' : ''}`} onClick={() => chooseNode(node.id)}><span className={`table-list-icon ${node.kind}`}>{node.kind === 'dataset' ? <LayoutDashboard size={16} /> : node.kind === 'table_source' ? <Database size={16} /> : <Table2 size={16} />}</span><div><strong>{node.label}</strong><small>{tableNodeType(node)}{node.versionCount > 1 ? ` · v${node.version}` : ''}</small><small>{node.fieldCount} {node.kind === 'dataset' ? '个使用处' : '已识别列'}</small></div><i className={`status-indicator status-${node.status}`} /></button>)}{!filtered.length && <div className="empty-compact">没有匹配的表或数据集。</div>}</div>
      </section><section className={`graph-card table-graph-card ${fullscreen ? 'table-fullscreen' : ''}`}>
        <div className="graph-toolbar"><div className="graph-title"><GitBranch size={16} /><h2>表级依赖</h2><span>{visible.nodes.length} / {graph.nodes.length} 节点 · {visible.edges.length} 条关系</span></div><button className="icon-button" aria-label={fullscreen ? '退出表血缘全屏' : '全屏查看表血缘'} onClick={() => setFullscreen(v => !v)}>{fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button></div>
        <div className="table-graph-controls"><label>方向<select value={direction} aria-label="表血缘方向" onChange={event => { if (!selected) { setMessage('先选择一张表，再查看指定方向。'); return; } setDirection(event.target.value as TableDirection); }}><option value="all">全图</option><option value="upstream">上游</option><option value="downstream">下游</option><option value="both">上下游</option></select></label><label>深度<select aria-label="表血缘深度" value={depth} onChange={event => setDepth(event.target.value as '1' | 'all')}><option value="all">完整路径</option><option value="1">直接一层</option></select></label><span>{edge ? `${graph.nodes.find(n => n.id === edge.source)?.label} → ${graph.nodes.find(n => n.id === edge.target)?.label}` : selectedNode?.label || '选择表查看字段，点击连线查看代码'}</span></div>
        {active && <div className="table-graph-canvas">{visible.nodes.length ? <TableLineageGraph key={viewportKey} graph={visible} selected={selected} selectedEdge={selectedEdge} request={request} onSelect={chooseNode} onEdgeSelect={chooseEdge} savedViewport={viewports.current[viewportKey]} onViewportChange={onViewportChange} /> : <div className="empty-workspace"><Table2 size={32} /><h2>没有已识别的表路径</h2><p>当前字段可能为常量、定义缺失或含动态引用；可切换整个 App 范围查看。</p></div>}</div>}
        <div className="table-graph-legend"><span><i className="table-line-data" />数据输入</span><span><i className="table-line-context" />行集上下文</span><span><i className="table-line-consumption" />图表消费</span><small>图表逻辑数据集不计为表 · 表版本保留先后顺序</small></div>
      </section></div>
      <div className="table-scope-note">{graph.scopeNote}</div>
      <section className="table-inspector"><div className="table-inspector-heading"><div><span className="section-eyebrow">{edge ? 'RELATION DETAILS' : 'TABLE / DATASET DETAILS'}</span><h2>{edge ? `${graph.nodes.find(n => n.id === edge.source)?.label} → ${graph.nodes.find(n => n.id === edge.target)?.label}` : selectedNode?.label || '选择一张表或一条关系'}</h2></div>{selectedNode && !edge && <StatusBadge status={selectedNode.status} />}</div>
        <div className="table-detail-tabs" role="tablist" aria-label="表关系详情"><button role="tab" aria-selected={tab === 'fields'} className={tab === 'fields' ? 'active' : ''} onClick={() => setTab('fields')}>{edge ? '字段映射' : selectedNode?.kind === 'dataset' ? '图表字段使用处' : '已识别字段'}</button><button role="tab" aria-selected={tab === 'code'} className={tab === 'code' ? 'active' : ''} onClick={() => setTab('code')}>代码证据</button>{!edge && <button role="tab" aria-selected={tab === 'usage'} className={tab === 'usage' ? 'active' : ''} onClick={() => setTab('usage')}>下游使用处 {detail?.consumers.length ?? ''}</button>}</div>
        {!selectedNode && !edge ? <div className="empty-compact">从左侧清单或画布选择表；进入字段级时会让你选择具体字段。</div> : tableResource.loading || evidenceResource.loading ? <StateMessage text="正在定位表定义与字段映射…" /> : tableResource.error || evidenceResource.error ? <StateMessage error={tableResource.error || evidenceResource.error} /> : <>
          {tab === 'fields' && (edge ? mappings : selectedNode?.kind === 'dataset' ? <div className="table-consumers">{scopedConsumers.map(f => <button key={f.id} onClick={() => onOpenUsage(f)}><div><strong>{f.label}</strong><code>{f.expression}</code></div><span>{f.sheetTitle} / {f.chartTitle}</span><ArrowRight size={14} /></button>)}</div> : <>
            <div className="table-definition-meta"><span>{selectedNode && tableNodeType(selectedNode)}</span><span>{selectedNode?.connection || (selectedNode?.sourceType === 'logical' ? 'Qlik 加载模型' : selectedNode?.sourceType)}</span><span>{selectedNode?.schemaStatus === 'known' ? '加载字段清单已识别' : '字段清单未完整确认'}</span>{selectedNode?.dropRef && <span>删除于 {selectedNode.dropRef.file} · L{selectedNode.dropRef.line}</span>}</div>
            {selectedNode?.note && <p className="table-detail-note">{selectedNode.note}</p>}
            {!!detail?.versions.length && detail.versions.length > 1 && <div className="table-version-list"><span>版本：</span>{detail.versions.map(v => <button key={v.id} className={v.id === selected ? 'active' : ''} onClick={() => chooseNode(v.id)}>v{v.version}{v.current ? ' · 当前' : ''}</button>)}</div>}
            <div className="search-box table-column-search"><Search size={14} /><input value={fieldQuery} aria-label="搜索表字段" placeholder="搜索此表已识别字段" onChange={event => { setFieldQuery(event.target.value); setOffset(0); }} /><span>{detail?.fieldTotal || 0} 列</span></div>
            <div className="table-column-list">{detail?.fields.map(column => <button key={column.name} data-column-name={column.name} onClick={() => onOpenTechnical({ version: selected, field: column.name })}><code>{column.name}</code><span>{column.nodeId ? '技术字段血缘' : '查看已知定义 / 映射缺口'}</span><ArrowRight size={14} /></button>)}{!detail?.fields.length && <div className="empty-compact">未识别出具体列名；表级读取关系和原始代码仍可查看。</div>}</div>{pagination}
          </>)}
          {tab === 'code' && <TableOperations operations={operationList || []} appId={app.id} snapshot={snapshot} revision={revision} active={active} />}
          {tab === 'usage' && <div className="table-consumers">{scopedConsumers.map(f => <button key={f.id} onClick={() => onOpenUsage(f)}><div><strong>{f.label}</strong><span>{f.sheetTitle} / {f.chartTitle}</span></div><span className={f.influence === 'context' ? 'table-context-influence' : ''}>{f.influence === 'value' ? '字段计算依赖' : '表级上下文可能影响'}</span><ArrowRight size={14} /></button>)}{!scopedConsumers.length && <div className="empty-compact">没有识别到此对象的 Sheet 字段使用处；表字段仍可独立查看。</div>}</div>}
        </>}
      </section>
      <div className="table-export-bar"><div><strong>导出表关系</strong><span>包含范围、快照时间、状态与证据位置</span></div><select aria-label="表级导出范围" value={exportRange} onChange={event => setExportRange(event.target.value as 'current' | 'app')}><option value="current">当前视图</option><option value="app">全 App</option></select><a className="button" href={'/api/table-relations.csv?' + apiParams(csvParams)}><Download size={14} />CSV</a><button className="button" disabled={exporting} onClick={() => { void exportJson(); }}>{exporting ? <LoaderCircle size={14} className="spin" /> : <Code2 size={14} />}含代码 JSON</button></div>
      {!!graph.boundaries.length && <details className="boundary-notice"><summary><TriangleAlert size={15} />{graph.boundaries.length} 处静态解析边界<ChevronDown size={14} /></summary><div>{graph.boundaries.map((w, i) => <p key={i}>{w.message}</p>)}</div></details>}
      <footer className="page-footer"><span>元数据导入于 {formatTime(snapshot)}</span><span>表关系与字段清单完整性分别判断 · 未执行脚本或 SQL</span></footer>
    </>}
    {dialog && active && edge && <RelationDialog title={`${graph?.nodes.find(n => n.id === edge.source)?.label} → ${graph?.nodes.find(n => n.id === edge.target)?.label}`} onClose={() => setDialog(false)}>
      <p className="table-detail-note">{edge.operationKinds.join(' → ')} · {edge.roles.includes('context') ? '包含行集上下文' : '数据输入'}</p>
      {evidenceResource.loading || evidenceResource.error ? <StateMessage error={evidenceResource.error} text="正在读取关系代码…" /> : <><TableOperations operations={evidence?.operations || []} appId={app.id} snapshot={snapshot} revision={revision} active={active} /><details className="table-dialog-mappings"><summary>已确认字段映射 {evidence?.mappingTotal || 0} 条 · 可进入字段级血缘</summary>{mappings}</details></>}
      <button className="button" onClick={() => { setDialog(false); setTab('fields'); }}><ArrowLeft size={14} />返回关系详情与字段映射</button>
    </RelationDialog>}
  </main>;
}
