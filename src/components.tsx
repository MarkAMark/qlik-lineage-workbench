import { LoaderCircle, TriangleAlert } from 'lucide-react';
import type { RiskLevel, Status } from './types';

export const STATUS: Record<Status, string> = { complete: '静态可追溯', partial: '部分待核实', unresolved: '缺少定义' };
export const LEVEL: Record<RiskLevel, string> = { low: '低', medium: '中', high: '高', very_high: '很高' };
export const FIELD_KIND: Record<string, string> = { measure: '度量', dimension: '维度', filter: '筛选字段' };
export function StateMessage({ error, text = '正在读取元数据…' }: { error?: string; text?: string }) {
  return <div className={`state-message ${error ? 'state-error' : ''}`} role={error ? 'alert' : 'status'} aria-busy={!error}>{error ? <TriangleAlert size={25} /> : <LoaderCircle size={25} className="spin" />}<p>{error || text}</p></div>;
}
export function StatusBadge({ status }: { status: Status }) { return <span className={`status-badge status-${status}`}><span />{STATUS[status]}</span>; }
export function RiskBadge({ level }: { level: RiskLevel }) { return <span className={`risk-badge risk-${level}`}>{LEVEL[level]}复杂度</span>; }
export function formatTime(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '未导出'; }
export function CodeBlock({ code, firstLine = 1 }: { code: string; firstLine?: number }) {
  if (!code) return <div className="code-empty">此节点缺少可验证的代码。请补充导出文件或源表 schema。</div>;
  return <pre className="code-block" tabIndex={0}>{code.split('\n').map((line, i) => <div className="code-line" key={i}><span className="line-number" aria-hidden="true">{firstLine + i}</span><code>{line || ' '}</code></div>)}</pre>;
}
