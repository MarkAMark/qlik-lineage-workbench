import { Network, Table2 } from 'lucide-react';

export default function LineageModeSwitch({ mode, onFields, onTables, children }: {
  mode: 'field' | 'table'; onFields: () => void; onTables: () => void; children?: React.ReactNode;
}) {
  return <div className="lineage-mode-bar"><div className="segmented" role="group" aria-label="血缘粒度">
    <button className={mode === 'field' ? 'active' : ''} aria-pressed={mode === 'field'} onClick={onFields}><Network size={15} />字段级</button>
    <button className={mode === 'table' ? 'active' : ''} aria-pressed={mode === 'table'} onClick={onTables}><Table2 size={15} />表级</button>
  </div><span className="mode-context-hint">切换粒度，保留当前查看对象</span>{children}</div>;
}
