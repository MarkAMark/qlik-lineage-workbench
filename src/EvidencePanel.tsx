import { useEffect, useState } from 'react';
import { ArrowRight, CheckCheck, Code2, GitBranch } from 'lucide-react';
import EvidenceCode, { type CodeMode } from './EvidenceCode';
import { KIND_LABELS } from './LineageGraph';
import { RiskBadge, StateMessage } from './components';
import type { Evidence, Field } from './types';

export default function EvidencePanel({ appId, snapshot, revision, active = true, evidence, loading, error, field, onJump, onNodeSelect }: { appId: string; snapshot: string; revision: number; active?: boolean; evidence: Evidence | null; loading: boolean; error: string; field: Field | undefined; onJump: (field: Field) => void; onNodeSelect: (id: string) => void }) {
  const [tab, setTab] = useState('code');
  const [mode, setMode] = useState<CodeMode>('expression');
  useEffect(() => { setTab('code'); }, [evidence?.id]);
  return <section className="evidence-panel">
    <div className="evidence-tabs"><div className="tabs" role="tablist" aria-label="节点详情">
      <button role="tab" aria-selected={tab === 'code'} className={tab === 'code' ? 'active' : ''} onClick={() => setTab('code')}><Code2 size={15} />代码证据</button>
      {field && <button role="tab" aria-selected={tab === 'migration'} className={tab === 'migration' ? 'active' : ''} onClick={() => setTab('migration')}><ArrowRight size={15} />迁移建议</button>}
      <button role="tab" aria-selected={tab === 'impact'} className={tab === 'impact' ? 'active' : ''} onClick={() => setTab('impact')}><GitBranch size={15} />下游使用{evidence && <span className="tiny-count">{evidence.consumers.length}</span>}</button>
    </div><span className="evidence-hint">点击血缘节点，切换本层代码</span></div>
    {loading || error ? <StateMessage error={error} text="正在定位代码…" /> : evidence && <>
      {tab === 'code' && <><EvidenceCode appId={appId} snapshot={snapshot} revision={revision} active={active} evidence={evidence} mode={mode} onModeChange={setMode}>
        {!!evidence.inputs?.length && <div className="evidence-inputs"><span>直接上游 {evidence.inputs.length} 项 · 点击逐层查看代码</span><div className="dependency-chips">{evidence.inputs.map(node => <button key={node.id} data-node-id={node.id} onClick={() => onNodeSelect(node.id)} title={KIND_LABELS[node.kind]}><code>{node.label}</code><ArrowRight size={11} /></button>)}</div></div>}
        </EvidenceCode>
        {evidence.assignments && <details className="assignment-details"><summary>脚本中的赋值记录（{evidence.assignments.length}）</summary>{evidence.assignments.map((a, i) => <div key={i}><span>script.qvs · L{a.ref.line}</span><code>{a.expression}</code></div>)}</details>}
      </>}
      {tab === 'migration' && field && <div className="migration-detail"><div className="section-eyebrow">当前 Sheet 字段 → QUICKSIGHT</div><div className="migration-detail-title"><strong>{field.label}</strong><RiskBadge level={field.risk.level} /></div><p>{field.risk.action}</p>{field.risk.issues.length ? <div className="issue-grid">{field.risk.issues.map(issue => <div className="issue-card" key={issue.code}><span className={`issue-dot risk-${issue.level}`} /><div><strong>{issue.title}</strong><p>{issue.action}</p></div></div>)}</div> : <div className="positive-note"><CheckCheck size={17} />未识别到高复杂度 Qlik 语法，适合作为基础功能的试迁移候选。</div>}<div className="method-note">复杂度根据字段表达式及其变量依赖静态识别。需要同时验证 SQL、数据模型关联、筛选交互和实际业务口径。</div></div>}
      {tab === 'impact' && <div className="impact-list"><div className="section-eyebrow">此节点在当前 APP 中的下游字段</div>{evidence.consumers.length ? evidence.consumers.map(consumer => <button key={consumer.id} onClick={() => onJump(consumer)}><div><strong>{consumer.label}</strong><span>{consumer.sheetTitle} / {consumer.chartTitle}</span></div><ArrowRight size={15} /></button>) : <div className="empty-compact">没有识别到 Sheet 字段使用此节点。</div>}</div>}
    </>}
  </section>;
}
