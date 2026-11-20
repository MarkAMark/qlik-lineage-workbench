import { useRef, type PointerEvent } from 'react';

export default function FieldPanelResizer({ width, onChange }: { width: number; onChange: (width: number) => void }) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  const resize = (next: number) => onChange(Math.max(288, Math.min(440, next)));
  const end = (event: PointerEvent<HTMLDivElement>) => {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return <div className="field-panel-resizer" role="separator" tabIndex={0} aria-label="调整字段列表宽度" aria-orientation="vertical" aria-valuemin={288} aria-valuemax={440} aria-valuenow={width}
    title="拖动调整字段栏；方向键微调，Home 恢复默认宽度"
    onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.focus(); drag.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture(event.pointerId); }}
    onPointerMove={event => { if (drag.current) resize(drag.current.width + event.clientX - drag.current.x); }}
    onPointerUp={end} onPointerCancel={end} onLostPointerCapture={() => { drag.current = null; }}
    onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); resize(event.key === 'Home' ? 304 : event.key === 'End' ? 440 : width + (event.key === 'ArrowRight' ? 8 : -8));
    }}><span /></div>;
}
