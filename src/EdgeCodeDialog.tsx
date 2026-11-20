import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Code2, X } from 'lucide-react';
import { apiParams, useResource } from './api';
import { StateMessage } from './components';
import EvidenceCode, { type CodeMode } from './EvidenceCode';
import { KIND_LABELS } from './LineageGraph';
import type { Evidence, LineageEdge, LineageNode } from './types';
import './EdgeCodeDialog.css';

export default function EdgeCodeDialog({ appId, snapshot, edge, source, target, revision, onClose }: {
  appId: string; snapshot: string; edge: LineageEdge; source: LineageNode; target: LineageNode; revision: number; onClose: () => void;
}) {
  // Model fields have no independent script; their incoming LOAD contains the mapping.
  const [endpoint, setEndpoint] = useState(target.kind === 'field' && !target.ref ? 'source' : 'target');
  const [mode, setMode] = useState<CodeMode>('snippet');
  const dialogRef = useRef<HTMLDialogElement>(null);
  const node = endpoint === 'source' ? source : target;
  const resource = useResource<Evidence>('/api/evidence?' + apiParams({ app: appId, snapshot, node: node.id }), revision, true);
  const evidence = resource.data?.id === node.id ? resource.data : null;

  useEffect(() => {
    const dialog = dialogRef.current!;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    return () => { dialog.close(); document.body.style.overflow = overflow; };
  }, []);

  return <dialog ref={dialogRef} className="edge-code-dialog" aria-labelledby="edge-code-title" aria-modal="true"
    onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => { if (event.key === 'Escape') event.stopPropagation(); }}
    onClick={event => {
      if (event.target !== event.currentTarget) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
    }}>
    <header className="edge-code-heading"><div><Code2 size={20} /><h2 id="edge-code-title">连线代码</h2><span>{edge.relation === 'measure-reference' ? '度量引用' : '字段依赖'}</span></div><button autoFocus className="icon-button" onClick={onClose} aria-label="关闭连线代码窗口"><X size={20} /></button></header>
    <div className="edge-code-path" aria-label="连线方向"><div data-node-id={source.id}><span className={`kind-chip kind-${source.kind}`}>{KIND_LABELS[source.kind] || source.kind}</span><strong>{source.label}</strong></div><ArrowRight size={20} /><div data-node-id={target.id}><span className={`kind-chip kind-${target.kind}`}>{KIND_LABELS[target.kind] || target.kind}</span><strong>{target.label}</strong></div></div>
    <p className="edge-code-hint">目标节点代码展示对上游的引用或转换；可切换查看来源节点的代码。</p>
    <div className="edge-code-endpoints" role="group" aria-label="选择连线代码节点"><button aria-pressed={endpoint === 'target'} className={endpoint === 'target' ? 'active' : ''} onClick={() => setEndpoint('target')}>目标节点代码</button><button aria-pressed={endpoint === 'source'} className={endpoint === 'source' ? 'active' : ''} onClick={() => setEndpoint('source')}>来源节点代码</button></div>
    {resource.error || !evidence ? <StateMessage error={resource.error} text="正在读取连线代码…" /> : <section className="edge-code-evidence" data-node-id={evidence.id}>
      <EvidenceCode appId={appId} snapshot={snapshot} revision={revision} evidence={evidence} mode={mode} onModeChange={setMode} copyLabel="复制连线代码" />
    </section>}
  </dialog>;
}
