import { useEffect, useRef, useState } from 'react';
import { Code2, X } from 'lucide-react';
import { apiParams, useResource } from './api';
import EvidenceCode, { type CodeMode } from './EvidenceCode';
import { StateMessage } from './components';
import type { Evidence } from './types';
import './EdgeCodeDialog.css';

export default function NodeCodeDialog({ appId, snapshot, nodeId, revision, evidence: provided, onClose }: { appId: string; snapshot: string; nodeId: string; revision: number; evidence?: Evidence; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [mode, setMode] = useState<CodeMode>('expression');
  const resource = useResource<Evidence>(provided ? null : '/api/evidence?' + apiParams({ app: appId, snapshot, node: nodeId }), revision, true);
  const evidence = provided || resource.data;
  useEffect(() => {
    const dialog = ref.current!;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden'; dialog.showModal();
    return () => { dialog.close(); document.body.style.overflow = overflow; };
  }, []);
  return <dialog ref={ref} className="edge-code-dialog node-code-dialog" aria-labelledby="node-code-title"
    onCancel={event => { event.preventDefault(); onClose(); }} onKeyDown={event => { if (event.key === 'Escape') event.stopPropagation(); }}>
    <header className="edge-code-heading"><div><Code2 size={20} /><h2 id="node-code-title">节点代码</h2></div><button autoFocus className="icon-button" aria-label="关闭节点代码窗口" onClick={onClose}><X size={20} /></button></header>
    {resource.error || !evidence ? <StateMessage error={resource.error} text="正在读取节点代码…" /> : <section className="edge-code-evidence" data-node-id={evidence.id}>
      <EvidenceCode appId={appId} snapshot={snapshot} revision={revision} evidence={evidence} mode={mode} onModeChange={setMode} />
    </section>}
  </dialog>;
}
