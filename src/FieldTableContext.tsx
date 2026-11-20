import { LayoutDashboard, Table2 } from 'lucide-react';
import { apiParams, useResource } from './api';
import FieldUsagePath from './FieldUsagePath';
import type { Field, TableGraph } from './types';

export default function FieldTableContext({ appId, field, snapshot, revision, onTables }: {
  appId: string; field: Field; snapshot: string; revision: number; onTables: () => void;
}) {
  const resource = useResource<TableGraph>('/api/table-lineage?' + apiParams({ app: appId, snapshot, scope: 'field', usage: field.id }), revision, true);
  const graph = resource.data;
  const binding = graph?.bindings[field.id];
  const tables = graph?.nodes.filter(n => binding?.tableIds.includes(n.id)) || [];
  const contexts = graph?.edges.filter(e => e.roles.includes('context')) || [];
  return <section className="field-table-context" aria-label="业务字段的展示归属与表依赖">
    <div className="field-display-context"><span className="field-context-label"><LayoutDashboard size={14} />展示归属</span><FieldUsagePath field={field} /></div>
    <div className="field-source-context"><Table2 size={14} /><span>依赖表</span>{resource.loading ? <small>正在定位…</small> : resource.error ? <small>{resource.error}</small> : tables.length ? tables.map(table => <code key={table.id}>{table.label}</code>) : <small>{binding?.mappingStatus === 'no_table' ? '无已识别表依赖' : '来源定义待确认'}</small>}<button className="table-drill-link" onClick={onTables}>切换到表级血缘</button></div>
    {binding?.mappingStatus === 'review' && <p>同名字段存在多个表成员或来源缺口，保留全部已知依赖，关联语义需核实。</p>}
    {binding?.mappingStatus === 'multiple' && <p>此计算明确依赖多张表，不指定唯一所属表。</p>}
    {!!contexts.length && <details><summary>{contexts.length} 条表级行集上下文 · 与字段数值依赖分别展示</summary>{contexts.map(edge => <p key={edge.id}>{graph?.nodes.find(n => n.id === edge.source)?.label} → {graph?.nodes.find(n => n.id === edge.target)?.label}<small>{edge.operationKinds.join(' → ')}</small></p>)}</details>}
  </section>;
}
