import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Boxes, ChartNoAxesCombined, CheckCheck, ChevronDown, ChevronRight, Code2, Database, Download, FileSearch, FolderOpen, GitBranch, Layers3, LayoutDashboard, ListFilter, LoaderCircle, Maximize2, Network, PanelLeftClose, PanelLeftOpen, RefreshCw, Search, Settings2, ShieldCheck, Sigma, Table2, TriangleAlert, X } from 'lucide-react';
import LineageGraph, { KIND_LABELS } from './LineageGraph';
import StreamAppList from './StreamAppList';
import FieldPanelResizer from './FieldPanelResizer';
import NodeCodeDialog from './NodeCodeDialog';
import EvidencePanel from './EvidencePanel';
import EdgeCodeDialog from './EdgeCodeDialog';
import TableWorkbench from './TableWorkbench';
import TechnicalFieldView from './TechnicalFieldView';
import LineageModeSwitch from './LineageModeSwitch';
import FieldTableContext from './FieldTableContext';
import type { Viewport } from '@xyflow/react';
import { AssessmentView, SourcesView } from './Portfolio';
import { FIELD_KIND, formatTime, RiskBadge, StateMessage, STATUS, StatusBadge } from './components';
import { apiParams, saveJson, useResource } from './api';
import type { AppDetail, Catalog, Evidence, Field, Lineage, LineageEdge, Stream, TableContext, TechnicalFieldRef } from './types';

type View = 'lineage' | 'tables' | 'technical' | 'assessment' | 'sources';
type FieldOrigin = { kind: 'usage'; field: Field } | { kind: 'technical'; reference: TechnicalFieldRef };

export default function App() {
  const [view, setView] = useState<View>('lineage');
  const [revision, setRevision] = useState(0);
  const catalogResource = useResource<Catalog>('/api/catalog', revision);
  const catalog = catalogResource.data;
  const [appId, setAppId] = useState('');
  const [streamId, setStreamId] = useState('');
  const [sheetId, setSheetId] = useState('');
  const [fieldId, setFieldId] = useState('');
  const [selectedNode, setSelectedNode] = useState('');
  const [selectedEdge, setSelectedEdge] = useState<LineageEdge | null>(null);
  const [fieldQuery, setFieldQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [fieldPanel, setFieldPanel] = useState(true);
  const [fieldWidth, setFieldWidth] = useState(() => { try { return Math.max(288, Math.min(440, Number(localStorage.getItem('trace.fieldWidth')) || 304)); } catch { return 304; } });
  useEffect(() => { try { localStorage.setItem('trace.fieldWidth', String(fieldWidth)); } catch { /* Optional local preference. */ } }, [fieldWidth]);
  const [codeNode, setCodeNode] = useState('');
  useEffect(() => { setCodeNode(''); }, [appId, fieldId, revision]);
  const [graphExpanded, setGraphExpanded] = useState(false);
  const [graphView, setGraphView] = useState('graph');
  const [showImport, setShowImport] = useState(false);
  const [importPath, setImportPath] = useState('');
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState('');
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState('');
  const [globalQuery, setGlobalQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const [tableContext, setTableContext] = useState<TableContext>({ scope: 'app', usage: '', sheet: '', chart: '', version: '', field: '', serial: 0 });
  const [technical, setTechnical] = useState<TechnicalFieldRef | null>(null);
  const [fieldOrigin, setFieldOrigin] = useState<FieldOrigin | null>(null);
  const [cameFromTable, setCameFromTable] = useState(false);
  const fieldViewports = useRef<Record<string, Viewport>>({});
  const lastFieldRoot = useRef('');
  const appResource = useResource<AppDetail>(appId && catalog ? '/api/app?' + apiParams({ id: appId, snapshot: catalog.importedAt }) : null, revision, true);
  const app = appResource.data?.id === appId ? appResource.data : null;
  const traceResource = useResource<Lineage>(view === 'lineage' && appId && fieldId && catalog ? '/api/lineage?' + apiParams({ app: appId, field: fieldId, snapshot: catalog.importedAt }) : null, revision, true);
  const trace = traceResource.data?.root === fieldId ? traceResource.data : null;
  const evidenceResource = useResource<Evidence>(view === 'lineage' && appId && selectedNode && trace?.nodes.some(node => node.id === selectedNode) && catalog ? '/api/evidence?' + apiParams({ app: appId, node: selectedNode, snapshot: catalog.importedAt }) : null, revision, true);
  const search = useResource<{ total: number; results: (Field & { appId: string; appName: string; stream: Stream })[] }>(debouncedQuery ? '/api/search?' + apiParams({ q: debouncedQuery }) : null, revision);

  useEffect(() => { const timer = setTimeout(() => setDebouncedQuery(globalQuery.trim()), 200); return () => clearTimeout(timer); }, [globalQuery]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key === 'Escape') { setGraphExpanded(false); if (!importing) setShowImport(false); setGlobalQuery(''); }
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, [importing]);
  useEffect(() => {
    if (!catalog) return;
    if (streamId && !catalog.streams.some(stream => stream.id === streamId)) { setStreamId(''); return; }
    const candidates = catalog.apps.filter(app => !streamId || app.stream.id === streamId);
    if (!candidates.some(a => a.id === appId)) setAppId(candidates[0]?.id || '');
    setImportPath(catalog.root);
  }, [catalog, appId, streamId]);
  useEffect(() => {
    if (!app) return;
    const sheet = app.sheets.find(s => s.id === sheetId) || app.sheets.find(s => s.fieldCount > 0) || app.sheets[0];
    if (!sheet) { setSheetId(''); setFieldId(''); return; }
    if (sheet.id !== sheetId) setSheetId(sheet.id);
    const fields = app.fields.filter(f => f.sheetId === sheet.id);
    if (!fields.some(f => f.id === fieldId)) setFieldId((fields.find(f => f.kind === 'measure') || fields[0])?.id || '');
  }, [app, sheetId, fieldId]);
  useEffect(() => {
    if (trace) {
      const restore = lastFieldRoot.current === trace.root;
      setSelectedNode(previous => restore && trace.nodes.some(node => node.id === previous) ? previous : trace.root);
      lastFieldRoot.current = trace.root; setSelectedEdge(null);
    }
  }, [trace]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 4500); return () => clearTimeout(timer); }, [notice]);
  useEffect(() => {
    if (!revision) return;
    setTechnical(null); setFieldOrigin(null); setCameFromTable(false); fieldViewports.current = {};
    setTableContext(previous => ({ scope: 'app', usage: '', sheet: '', chart: '', version: '', field: '', serial: previous.serial + 1 }));
    setView(previous => previous === 'technical' ? 'tables' : previous);
  }, [revision]);

  const selectedField = app?.fields.find(f => f.id === fieldId);
  const edgeSource = trace?.nodes.find(node => node.id === selectedEdge?.source);
  const edgeTarget = trace?.nodes.find(node => node.id === selectedEdge?.target);
  const sheet = app?.sheets.find(s => s.id === sheetId);
  const sheetFields = useMemo(() => app?.fields.filter(f => f.sheetId === sheetId) || [], [app, sheetId]);
  const visibleFields = useMemo(() => sheetFields.filter(f => (kind === 'all' || f.kind === kind) && `${f.label} ${f.expression} ${f.chartTitle} ${f.masterId}`.toLowerCase().includes(fieldQuery.toLowerCase())), [sheetFields, fieldQuery, kind]);
  const chooseApp = (id: string, selectedSheet = '', selectedField = '') => {
    const target = catalog?.apps.find(app => app.id === id);
    if (streamId && target && target.stream.id !== streamId) setStreamId(target.stream.id);
    setAppId(id); setSheetId(selectedSheet); setFieldId(selectedField); setSelectedNode(''); setFieldQuery(''); setKind('all'); setView(view === 'tables' && !selectedField ? 'tables' : 'lineage'); setGlobalQuery('');
    setTechnical(null); setFieldOrigin(null); setCameFromTable(false);
    setTableContext(previous => ({ scope: 'app', usage: '', sheet: selectedSheet, chart: '', version: '', field: '', serial: previous.serial + 1 }));
  };
  const chooseStream = (id: string) => {
    setStreamId(id);
    if (!id || catalog?.apps.some(app => app.id === appId && app.stream.id === id)) return;
    const next = catalog?.apps.find(app => app.stream.id === id);
    setAppId(next?.id || ''); setSheetId(''); setFieldId(''); setSelectedNode(''); setFieldQuery(''); setKind('all');
  };
  const jumpToField = (field: Field) => { setSheetId(field.sheetId); setFieldId(field.id); setFieldQuery(''); setKind('all'); };
  const openAppTables = () => {
    setFieldOrigin(null); setGraphExpanded(false);
    setTableContext(previous => ({ scope: 'app', usage: '', sheet: sheetId, chart: selectedField?.chartId || '', version: '', field: '', serial: previous.serial + 1 }));
    setView('tables');
  };
  const tablesFromField = () => {
    if (!selectedField) { openAppTables(); return; }
    setFieldOrigin({ kind: 'usage', field: selectedField }); setGraphExpanded(false);
    setTableContext(previous => ({ scope: 'field', usage: selectedField.id, sheet: selectedField.sheetId, chart: selectedField.chartId, version: '', field: '', serial: previous.serial + 1 }));
    setView('tables');
  };
  const tablesFromTechnical = () => {
    if (!technical) { openAppTables(); return; }
    setFieldOrigin({ kind: 'technical', reference: technical });
    setTableContext(previous => ({ scope: 'field', usage: '', sheet: sheetId, chart: selectedField?.chartId || '', ...technical, serial: previous.serial + 1 }));
    setView('tables');
  };
  const returnToField = () => {
    if (fieldOrigin?.kind === 'usage' && app?.fields.some(field => field.id === fieldOrigin.field.id)) { setSheetId(fieldOrigin.field.sheetId); setFieldId(fieldOrigin.field.id); setView('lineage'); return; }
    if (fieldOrigin?.kind === 'technical') { setTechnical(fieldOrigin.reference); setView('technical'); return; }
    setView('lineage');
  };
  const selectTableSheet = (id: string) => {
    setSheetId(id); setFieldId(''); setSelectedNode(''); setFieldQuery(''); setKind('all');
    setTechnical(null); setFieldOrigin(null); setCameFromTable(false);
    setTableContext(previous => ({ scope: id ? 'sheet' : 'app', usage: '', sheet: id, chart: '', version: '', field: '', serial: previous.serial + 1 }));
  };
  const openUsageFromTable = (field: Field) => { jumpToField(field); setFieldOrigin({ kind: 'usage', field }); setCameFromTable(true); setView('lineage'); };
  const openTechnical = (reference: TechnicalFieldRef) => { setTechnical(reference); setFieldOrigin({ kind: 'technical', reference }); setCameFromTable(true); setView('technical'); };
  const openImport = () => { setImportError(''); setShowImport(true); };
  const importMetadata = async () => {
    setImporting(true); setImportError('');
    try {
      const response = await fetch('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Trace-Request': 'local' }, body: JSON.stringify({ root: importPath }) });
      const body = await response.json(); if (!response.ok) throw new Error(body.error);
      setRevision(n => n + 1); setShowImport(false); setNotice(`已导入 ${body.totals.apps} 个 App、${body.totals.streams} 个 Stream、${body.totals.sheets} 个 Sheet。`);
    } catch (error) { setImportError(String((error as Error).message)); }
    finally { setImporting(false); }
  };
  const exportLineage = async () => {
    if (!trace || !app) return;
    setExporting(true);
    try {
      const evidence = await Promise.all(trace.nodes.map(async node => { const response = await fetch('/api/evidence?' + apiParams({ app: appId, node: node.id })); if (!response.ok) throw new Error('代码证据读取失败'); return response.json(); }));
      saveJson({ ...trace, importedAt: catalog?.importedAt, nodes: evidence, scope: '离线静态解析；数据库血缘止于已导出脚本中的源表或视图。' }, `${app.name}-${trace.field.label}.lineage.json`);
      setNotice('已导出血缘关系及每层代码证据。');
    } catch (error) { setNotice('导出失败：' + (error as Error).message); }
    finally { setExporting(false); }
  };
  const appSummary = catalog?.apps.find(a => a.id === appId);
  const inputFields = trace?.nodes.filter(node => node.kind === 'field') || [];
  const fieldTitle = selectedField?.label.startsWith('=') && inputFields.length === 1 ? inputFields[0].label : selectedField?.label;

  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => setView('lineage')} aria-label="Trace 首页"><img src="/trace.svg" width="37" height="37" alt="" /><div><strong>trace<span>.</span></strong><span>QLIK MIGRATION STUDIO</span></div></button>
      <div className="workspace-label">WORKSPACE <span>LOCAL</span></div>
      <nav className="main-nav"><button data-view="fields" className={view === 'lineage' || view === 'technical' ? 'active' : ''} onClick={returnToField}><Network size={18} />字段血缘<span className="nav-dot" /></button><button data-view="tables" className={view === 'tables' ? 'active' : ''} onClick={openAppTables}><Table2 size={18} />表级血缘</button><button data-view="assessment" className={view === 'assessment' ? 'active' : ''} onClick={() => setView('assessment')}><ChartNoAxesCombined size={18} />迁移评估</button><button data-view="sources" className={view === 'sources' ? 'active' : ''} onClick={() => setView('sources')}><Database size={18} />数据源目录</button></nav>
      <div className="sidebar-divider" /><StreamAppList catalog={catalog} streamId={streamId} appId={appId} active={['lineage', 'tables', 'technical'].includes(view)} onStream={chooseStream} onApp={id => chooseApp(id)} />
      <div className="sidebar-footer"><div className="local-status"><span />本机运行 <ShieldCheck size={12} /></div><button className="metadata-folder" onClick={openImport} title={catalog?.root}><FolderOpen size={16} /><div><strong>元数据目录</strong><span>{catalog?.root || '正在读取…'}</span></div><Settings2 size={14} /></button><p>Qlik Sense → Amazon QuickSight</p></div>
    </aside>
    <div className="app-main">
      <header className="topbar"><div className="topbar-breadcrumb"><Boxes size={16} /><span>迁移工作空间</span><ChevronRight size={13} /><strong>{view === 'lineage' ? '字段血缘' : view === 'technical' ? '技术字段血缘' : view === 'tables' ? '表级血缘' : view === 'assessment' ? '迁移评估' : '数据源目录'}</strong></div>
        <div className="global-search"><Search size={16} /><input ref={searchRef} value={globalQuery} onChange={e => setGlobalQuery(e.target.value)} placeholder="跨 Stream / App 搜索字段…" aria-label="全局搜索字段" /><kbd>Ctrl K</kbd>{globalQuery && <button className="icon-button" onClick={() => setGlobalQuery('')} aria-label="清空全局搜索"><X size={13} /></button>}
          {globalQuery && <div className="global-results">{search.loading ? <StateMessage text="正在搜索…" /> : search.error ? <StateMessage error={search.error} /> : <><div className="search-results-heading">找到 {search.data?.total || 0} 个字段使用处{(search.data?.total || 0) > 80 && ' · 显示前 80 个'}</div>{search.data?.results.map(result => <button key={`${result.appId}-${result.id}`} onClick={() => chooseApp(result.appId, result.sheetId, result.id)}><span className={`field-type-icon type-${result.kind}`}>{result.kind === 'measure' ? <Sigma size={15} /> : <Table2 size={15} />}</span><div><strong>{result.label}</strong><span>{result.stream.name} / {result.appName} / {result.sheetTitle} / {result.chartTitle}</span><code>{result.expression.slice(0, 150)}</code></div><ArrowRight size={14} /></button>)}{!search.data?.results.length && !search.loading && <div className="empty-compact">尝试搜索源字段名，例如 AMOUNT、ORDER_DATE 或 CUSTOMER_ID。</div>}</>}</div>}
        </div><div className="topbar-local"><span /><span>本机工作台</span></div>
      </header>
      {catalogResource.loading || catalogResource.error ? <StateMessage error={catalogResource.error} text="正在加载 Qlik 血缘工作空间…" /> : catalog && (catalog.apps.length === 0 ? <main className="onboarding" aria-labelledby="welcome-title">
        <div className="section-eyebrow">LOCAL METADATA WORKSPACE</div>
        <h1 id="welcome-title">导入元数据，开始追溯血缘</h1>
        <p>公开版不附带任何 Qlik 元数据。选择本机导出目录后，即可按 Stream、应用和 Sheet 查看字段、转换表达式与源表。</p>
        <ol className="onboarding-steps"><li><strong>选择本机 metadata 目录</strong><span>支持 Stream / App 分层和 App 平铺目录</span></li><li><strong>扫描应用</strong><span>读取导出的脚本与对象，建立本机分析快照</span></li><li><strong>查看血缘</strong><span>选择字段，追溯来源并查看每层代码证据</span></li></ol>
        <button className="button primary" onClick={openImport}><FolderOpen size={17} />选择元数据目录</button>
        <div className="onboarding-note"><ShieldCheck size={17} /><span>导入仅读取本机文件；无需 Qlik、数据库或 AWS 账号。重启后请重新选择外部目录，或使用启动参数指定目录。</span></div>
      </main> : <>
        {view === 'assessment' && <AssessmentView catalog={catalog} streamId={streamId} revision={revision} onOpen={id => chooseApp(id)} />}
        {view === 'sources' && <SourcesView streamId={streamId} revision={revision} onOpen={id => chooseApp(id)} />}
        {app && <TableWorkbench key={'tables:' + appId + revision} app={app} active={view === 'tables'} snapshot={catalog.importedAt} revision={revision} context={tableContext} selectedField={selectedField} sheetId={sheetId} onImport={openImport} onReturnField={returnToField} onSheetChange={selectTableSheet} onOpenUsage={openUsageFromTable} onOpenTechnical={openTechnical} />}
        {app && technical && <TechnicalFieldView key={'technical:' + appId + revision} appId={appId} snapshot={catalog.importedAt} revision={revision} reference={technical} active={view === 'technical'} onTables={tablesFromTechnical} onBack={() => setView('tables')} onOpenField={openTechnical} onOpenUsage={openUsageFromTable} />}
        {(view === 'tables' || view === 'technical') && !app && <main className="lineage-page lineage-loading-page"><LineageModeSwitch mode={view === 'tables' ? 'table' : 'field'} onFields={returnToField} onTables={openAppTables} /><StateMessage error={appResource.error} text="正在读取当前 App…" /></main>}
        {(view === 'tables' || view === 'technical') && catalog.errors.length > 0 && <div className="import-errors"><TriangleAlert size={16} /><span>{catalog.errors.length} 个 App 导入失败：{catalog.errors.map(error => error.app + '：' + error.message).join('；')}</span></div>}
        {view === 'lineage' && <main className="lineage-page">

          <div className="page-heading lineage-heading"><div><div className="section-eyebrow">FIELD LINEAGE EXPLORER</div><h1>字段血缘</h1><p>从 Sheet 中的业务字段，追溯到源表与每一层转换代码。</p></div><div className="inline-actions"><LineageModeSwitch mode="field" onFields={() => {}} onTables={tablesFromField}>{cameFromTable && <button className="button" onClick={() => setView('tables')}><ArrowLeft size={14} />返回原表</button>}</LineageModeSwitch><button className="button" onClick={openImport}><RefreshCw size={14} />重新扫描</button><a className="button" href={'/api/fields.csv?' + apiParams({ app: appId })}><Download size={14} />字段清单</a></div></div>
          <section className="context-bar"><div className="context-app"><span className="context-icon"><LayoutDashboard size={20} /></span><div><span title={appSummary?.stream.name}>STREAM / {appSummary?.stream.name}</span><strong>{appSummary?.name || '选择 App'}</strong></div><ChevronRight size={17} /></div><label className="sheet-select"><span>SHEET</span><select value={sheetId} aria-label="选择 Sheet" onChange={e => { setSheetId(e.target.value); setFieldId(''); setFieldQuery(''); setKind('all'); }}>{app?.sheets.map(s => <option key={s.id} value={s.id}>{s.title} · {s.fieldCount} 个字段</option>)}</select><ChevronDown size={15} /></label><div className="context-stats"><span><Table2 size={14} />{sheet?.fieldCount ?? '—'} 个字段</span><span><Layers3 size={14} />{sheet?.chartCount ?? '—'} 个对象</span></div><button className="icon-button panel-toggle" onClick={() => setFieldPanel(!fieldPanel)} title={fieldPanel ? '收起字段列表' : '展开字段列表'} aria-label={fieldPanel ? '收起字段列表' : '展开字段列表'}>{fieldPanel ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button></section>
          {appResource.loading || appResource.error ? <StateMessage error={appResource.error} text="正在读取 Sheet 与字段定义…" /> : app && <div className={`lineage-workbench ${!fieldPanel ? 'fields-collapsed' : ''}`} style={fieldPanel ? { gridTemplateColumns: `${fieldWidth}px 12px minmax(0, 1fr)` } : undefined}>
            {fieldPanel && <section className="field-panel"><div className="field-panel-title"><h2>Sheet 字段</h2><span>{sheetFields.length}</span></div><div className="field-search search-box"><Search size={14} /><input value={fieldQuery} onChange={e => setFieldQuery(e.target.value)} placeholder="搜索字段、表达式或图表" aria-label="搜索当前 Sheet 字段" />{fieldQuery && <button className="icon-button" aria-label="清空字段搜索" onClick={() => setFieldQuery('')}><X size={12} /></button>}</div><div className="field-filters"><ListFilter size={12} />{[['all', '全部'], ['measure', '度量'], ['dimension', '维度'], ['filter', '筛选']].map(([value, label]) => <button key={value} aria-pressed={kind === value} className={kind === value ? 'active' : ''} onClick={() => setKind(value)}>{label}</button>)}</div>
              <div className="field-list">{visibleFields.map(field => <button key={field.id} className={`field-row ${fieldId === field.id ? 'active' : ''}`} aria-pressed={fieldId === field.id} onClick={() => setFieldId(field.id)} title={`${FIELD_KIND[field.kind] || '字段'}：${field.originalLabel || field.label}\n图表：${field.chartTitle || '未命名图表'}\n表达式：${field.expression}`}><span className={`field-type-icon type-${field.kind}`}>{field.kind === 'measure' ? <Sigma size={16} /> : field.kind === 'filter' ? <ListFilter size={15} /> : <Table2 size={15} />}</span><div><strong>{field.label}</strong><div className="field-row-meta"><span className="field-chart-label" title={`图表：${field.chartTitle || '未命名图表'}`}>图表：{field.chartTitle || '未命名图表'}</span><span className="field-kind-label">{FIELD_KIND[field.kind]}</span>{field.masterId && <span>主项 {field.masterId}</span>}</div></div><span className={`field-status status-${field.status}`} title={STATUS[field.status]} aria-label={STATUS[field.status]}>{field.status === 'complete' ? <CheckCheck size={14} /> : <TriangleAlert size={14} />}</span>{fieldId === field.id && <ChevronRight size={13} />}</button>)}{!visibleFields.length && <div className="empty-compact"><FileSearch size={22} /><p>{sheetFields.length ? '没有匹配字段，试试搜索表达式中的原始列名。' : '此 Sheet 未导出可识别的字段定义。'}</p></div>}</div><div className="field-panel-footer"><span className="status-indicator status-complete" />可追溯<span className="status-indicator status-partial" />待核实<span className="status-indicator status-unresolved" />缺少定义</div>
            </section>}
            <>{fieldPanel && <FieldPanelResizer width={fieldWidth} onChange={setFieldWidth} />}</><div className="trace-workspace">{traceResource.loading || traceResource.error ? <StateMessage error={traceResource.error} text="正在构建字段血缘…" /> : trace && selectedField ? <>
              <section className="selected-field-card"><div className="selected-field-top"><div><span className="section-eyebrow">当前分析 · {FIELD_KIND[selectedField.kind]}</span><h2 title={selectedField.label}>{fieldTitle}</h2></div><RiskBadge level={selectedField.risk.level} /></div><div className="selected-field-bottom"><StatusBadge status={trace.status} /><span>{trace.nodes.length} 个节点</span><span>{trace.sourceCount} 个源字段</span><button onClick={exportLineage} disabled={exporting}>{exporting ? <LoaderCircle size={13} className="spin" /> : <Download size={13} />}导出血缘与代码</button></div></section>
              <FieldTableContext appId={appId} field={selectedField} snapshot={catalog.importedAt} revision={revision} onTables={tablesFromField} />
              <section className="graph-card"><div className="graph-toolbar"><div className="graph-title"><GitBranch size={16} /><h2>上游血缘</h2><span>数据源 → 当前字段</span></div><div className="inline-actions"><div className="segmented small"><button className={graphView === 'graph' ? 'active' : ''} onClick={() => setGraphView('graph')} aria-label="血缘图视图"><Network size={14} /></button><button className={graphView === 'list' ? 'active' : ''} onClick={() => setGraphView('list')} aria-label="血缘节点列表视图"><Table2 size={14} /></button></div><button className="icon-button" onClick={() => setGraphExpanded(true)} aria-label="全屏查看血缘图" title="全屏查看"><Maximize2 size={15} /></button></div></div><div className="graph-canvas">{graphView === 'graph' ? !graphExpanded && <LineageGraph key={trace.root + revision} graph={trace} expressionPreview={trace.field.expression.trim()} selected={selectedNode} onSelect={setSelectedNode} evidenceContext={{ appId, snapshot: catalog?.importedAt || '' }} onCode={id => { setSelectedNode(id); setCodeNode(id); }} onEdgeSelect={setSelectedEdge} savedViewport={fieldViewports.current[appId + trace.root + revision]} onViewportChange={viewport => { fieldViewports.current[appId + trace.root + revision] = viewport; }} /> : <div className="node-table"><table className="data-table"><thead><tr><th>层类型</th><th>节点 / 字段</th><th>状态</th><th /></tr></thead><tbody>{trace.nodes.map(node => <tr key={node.id} className={selectedNode === node.id ? 'expanded-row' : ''}><td><span className={`kind-chip kind-${node.kind}`}>{KIND_LABELS[node.kind]}</span></td><td><button onClick={() => setSelectedNode(node.id)}>{node.label}</button></td><td>{node.confidence === 'parsed' ? '已静态解析' : node.confidence === 'review' ? '需核实' : '缺少定义'}</td><td><button className="icon-button" onClick={() => setSelectedNode(node.id)} aria-label={`查看 ${node.label} 代码`}><Code2 size={15} /></button></td></tr>)}</tbody></table></div>}</div></section>
              {trace.boundaries.length > 0 && <details className="boundary-notice"><summary><TriangleAlert size={15} /><span>此 App 有 {trace.boundaries.length} 处迁移边界需要核实</span><ChevronDown size={14} /></summary><div>{trace.boundaries.map((warning, i) => <p key={i}>{warning.message}{warning.ref?.line && <small>script.qvs · L{warning.ref.line}</small>}</p>)}</div></details>}
              <EvidencePanel appId={appId} snapshot={catalog.importedAt} revision={revision} evidence={evidenceResource.data?.id === selectedNode ? evidenceResource.data : null} loading={evidenceResource.loading} error={evidenceResource.error} field={selectedField} onJump={jumpToField} onNodeSelect={setSelectedNode} />
            </> : <div className="empty-workspace"><Network size={43} /><h2>从 Sheet 选择一个字段</h2><p>字段的转换链路、源表和代码会显示在这里。</p></div>}</div>
          </div>}
          <footer className="page-footer"><span>元数据导入于 {formatTime(catalog.importedAt)} · App 快照重载时间 {formatTime(app?.lastReload || '')}</span><span>静态解析 · 血缘止于已导出源表 / 视图</span></footer>
          {catalog.errors.length > 0 && <div className="import-errors"><TriangleAlert size={16} /><span>{catalog.errors.length} 个 App 导入失败：{catalog.errors.map(e => e.app + '：' + e.message).join('；')}</span></div>}
        </main>}
      </>)}
    </div>
    {notice && <div className="toast" role="status"><CheckCheck size={17} />{notice}<button className="icon-button" onClick={() => setNotice('')} aria-label="关闭提示"><X size={14} /></button></div>}
    {showImport && <div className="modal-backdrop" onClick={() => { if (!importing) setShowImport(false); }}><section className="import-modal" role="dialog" aria-modal="true" aria-labelledby="import-title" onClick={e => e.stopPropagation()}><div className="modal-top"><span className="modal-symbol"><FolderOpen size={26} /></span><button className="icon-button" disabled={importing} onClick={() => setShowImport(false)} aria-label="关闭导入窗口"><X size={19} /></button></div><div className="section-eyebrow">LOCAL METADATA</div><h2 id="import-title">连接本机的 Qlik 导出目录</h2><p>选择导出根目录，支持 Stream / App 分层目录，也支持原有的 App 平铺目录。</p><label className="path-input-label">元数据目录<input value={importPath} onChange={e => setImportPath(e.target.value)} spellCheck={false} aria-label="元数据目录路径" disabled={importing} autoFocus /></label><div className="import-format"><FolderOpen size={15} /><div><strong>apps / Stream / App 名称 /</strong><code>script.qvs · variables.json · dimensions.json · measures.json · objects/</code></div></div><div className="import-readonly"><ShieldCheck size={15} />在本机读取和分析导出文件，扫描完成后刷新目录与评估。</div>{importError && <p className="form-error" role="alert">{importError}</p>}<div className="modal-actions"><button className="button" disabled={importing} onClick={() => setShowImport(false)}>取消</button><button className="button primary" disabled={importing || !importPath.trim()} onClick={importMetadata}>{importing ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}{importing ? '正在解析所有 App…' : '扫描并导入'}</button></div></section></div>}
    {graphExpanded && trace && <div className="graph-fullscreen" role="dialog" aria-modal="true" aria-label="全屏血缘图"><div className="fullscreen-toolbar"><div><GitBranch size={20} /><strong>{trace.field.label}</strong><StatusBadge status={trace.status} /><span>点击连线直接查看代码；节点代码可返回工作台查看</span></div><button className="button" onClick={() => setGraphExpanded(false)}><ArrowLeft size={15} />返回工作台 <kbd>Esc</kbd></button></div><div className="fullscreen-canvas"><LineageGraph graph={trace} expressionPreview={trace.field.expression.trim()} selected={selectedNode} onSelect={setSelectedNode} evidenceContext={{ appId, snapshot: catalog?.importedAt || '' }} onCode={id => { setSelectedNode(id); setCodeNode(id); }} onEdgeSelect={setSelectedEdge} /></div><div className="fullscreen-node"><Code2 size={15} /><span>已选择：{trace.nodes.find(n => n.id === selectedNode)?.label}</span><button onClick={() => setGraphExpanded(false)}>查看代码证据 <ArrowRight size={14} /></button></div></div>}
    {codeNode && view === 'lineage' && <NodeCodeDialog key={codeNode} appId={appId} snapshot={catalog?.importedAt || ''} nodeId={codeNode} revision={revision} onClose={() => setCodeNode('')} />}
    {view === 'lineage' && selectedEdge && edgeSource && edgeTarget && <EdgeCodeDialog key={`${appId}:${trace?.root}:${selectedEdge.id}:${revision}`} appId={appId} snapshot={catalog?.importedAt || ''} edge={selectedEdge} source={edgeSource} target={edgeTarget} revision={revision} onClose={() => setSelectedEdge(null)} />}
  </div>;
}
