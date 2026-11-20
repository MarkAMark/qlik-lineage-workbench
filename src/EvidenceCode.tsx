import { useEffect, useState, type ReactNode } from 'react';
import { Check, Copy, FileCode2, TriangleAlert } from 'lucide-react';
import { KIND_LABELS } from './LineageGraph';
import { CodeBlock } from './components';
import SourceFileView, { useSourceFile } from './SourceFileView';
import type { Evidence } from './types';

export type CodeMode = 'expression' | 'snippet' | 'file';

export default function EvidenceCode({ appId, snapshot, revision, evidence, mode, onModeChange, copyLabel = '复制当前代码', active = true, children }: {
  appId: string; snapshot: string; revision: number; evidence: Evidence; mode: CodeMode; onModeChange: (mode: CodeMode) => void; copyLabel?: string; active?: boolean; children?: ReactNode;
}) {
  const [selection, setSelection] = useState({ node: '', source: '' });
  const definitions = evidence.ref?.file ? [] : evidence.definitionSources || [];
  const definition = definitions.find(item => selection.node === evidence.id && item.id === selection.source) || definitions[0];
  const reference = evidence.ref || definition?.ref;
  const original = evidence.original || definition?.original || '';
  const showing: CodeMode = (mode === 'file' && !reference?.file) || (mode === 'snippet' && !original) ? 'expression' : mode;
  const source = useSourceFile(appId, snapshot, revision, reference, active && showing === 'file');
  const code = showing === 'file' ? source.data?.content || '' : showing === 'snippet' ? original : evidence.expression;
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  useEffect(() => { setCopied(false); setCopyError(''); }, [evidence.id, showing, definition?.id]);
  useEffect(() => { if (!copied) return; const timer = setTimeout(() => setCopied(false), 1800); return () => clearTimeout(timer); }, [copied]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); setCopied(true); setCopyError(''); }
    catch { setCopyError('复制失败，请手动选择代码。'); }
  };
  return <>
    <div className="code-toolbar"><div className="code-origin"><span className={`kind-chip kind-${evidence.kind}`}>{KIND_LABELS[evidence.kind] || evidence.kind}</span><strong title={evidence.label}>{evidence.label}</strong></div><div className="inline-actions"><div className="segmented small code-view-switch" role="group" aria-label="代码查看方式">
      <button className={showing === 'expression' ? 'active' : ''} aria-pressed={showing === 'expression'} onClick={() => onModeChange('expression')}>本层表达式</button>
      <button className={showing === 'snippet' ? 'active' : ''} aria-pressed={showing === 'snippet'} disabled={!original} title={original ? definition ? '查看此字段的上游定义代码' : '查看当前节点的原始片段' : '未导出可验证的原始定义'} onClick={() => onModeChange('snippet')}>原始片段</button>
      <button className={showing === 'file' ? 'active' : ''} aria-pressed={showing === 'file'} disabled={!reference?.file} title={reference?.file ? '查看原始文件并定位当前定义' : '未导出可定位的原始定义'} onClick={() => onModeChange('file')}>完整文件</button>
    </div><button className="icon-button" onClick={copy} disabled={!code} aria-label={copyLabel} title={copied ? '已复制' : copyLabel}>{copied ? <Check size={15} /> : <Copy size={15} />}</button></div></div>
    <div className="code-location"><FileCode2 size={13} />{reference ? <><span>{definition ? '上游定义 · ' : ''}{reference.file}</span><span className="code-pointer">{reference.pointer || (reference.line ? `L${reference.line}${reference.endLine ? `–${reference.endLine}` : ''}` : '')}</span></> : <span>未导出可定位的原始定义，可查看本层表达式和直接上游。</span>}</div>
    {definition && <div className="code-definition-source" data-definition-node={definition.id}><span>此数据模型字段的原始代码来自上游定义：</span>{definitions.length > 1 ? <label>定义来源（{definitions.length} 处）<select aria-label="选择原始代码定义" value={definition.id} onChange={event => setSelection({ node: evidence.id, source: event.target.value })}>{definitions.map(item => <option key={item.id} value={item.id}>{item.label} · {item.ref.file}{item.ref.line ? ` · L${item.ref.line}` : item.ref.pointer || ''}</option>)}</select></label> : <strong>{definition.label}</strong>}</div>}
    {evidence.note && <div className={`node-note ${evidence.confidence !== 'parsed' ? 'warning-note' : ''}`}>{evidence.confidence !== 'parsed' && <TriangleAlert size={13} />}{evidence.note}</div>}
    {(evidence.parameterized || definition?.parameterized) && <div className="node-note warning-note">SQL 含美元展开参数；原始片段保留实际代码。</div>}
    {children}
    {showing === 'file' ? <SourceFileView resource={source} targetKey={evidence.id + ':' + (definition?.id || '')} /> : <CodeBlock code={code} firstLine={showing === 'snippet' ? reference?.line || 1 : 1} />}
    {copyError && <p className="code-copy-error" role="status">{copyError}</p>}
  </>;
}
