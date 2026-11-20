import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { LocateFixed } from 'lucide-react';
import { apiParams, useResource } from './api';
import { StateMessage } from './components';
import type { Ref, SourceFile, SourceLocation } from './types';
import './SourceFileView.css';

export function useSourceFile(appId: string, snapshot: string, revision: number, ref: Ref | undefined, active: boolean) {
  const resource = useResource<SourceFile>(active && ref?.file ? '/api/source-file?' + apiParams({ app: appId, snapshot, file: ref.file }) : null, revision, true);
  const data = resource.data?.snapshot === snapshot && resource.data.file === ref?.file ? resource.data : null;
  let location: SourceLocation | undefined;
  if (data && ref) {
    location = ref.pointer !== undefined ? data.locations[ref.pointer] : ref.line ? { line: ref.line, endLine: ref.endLine || ref.line } : data.locations[''];
    if (location && (location.line < 1 || location.line > data.lineCount)) location = undefined;
  }
  return { ...resource, data, location };
}

const rowHeight = 24;
const overscan = 6;

function SourceFileCode({ file, location, targetKey, locateRequest }: { file: SourceFile; location?: SourceLocation; targetKey: string; locateRequest: number }) {
  const viewport = useRef<HTMLDivElement>(null);
  const pendingHorizontal = useRef(true);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(360);
  const lines = useMemo(() => file.content.split('\n'), [file.content]);
  const width = useMemo(() => lines.reduce((longest, line) => Math.max(longest, line.replace(/[^\x00-\xff]|\t/g, '  ').length), 0), [lines]);
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(lines.length, Math.ceil((scrollTop + height) / rowHeight) + overscan);
  useLayoutEffect(() => {
    const element = viewport.current!;
    const observer = new ResizeObserver(() => setHeight(element.clientHeight));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    const element = viewport.current!;
    element.scrollTop = location ? Math.max(0, (location.line - 1) * rowHeight - element.clientHeight / 3) : 0;
    element.scrollLeft = 0;
    pendingHorizontal.current = true;
    setScrollTop(element.scrollTop);
  }, [file.snapshot, file.file, targetKey, location?.line, location?.column, locateRequest]);
  useLayoutEffect(() => {
    const element = viewport.current!;
    const marker = element.querySelector<HTMLElement>('[data-source-target]');
    if (pendingHorizontal.current && marker && location?.column) {
      const left = marker.getBoundingClientRect().left - element.getBoundingClientRect().left + element.scrollLeft;
      element.scrollLeft = Math.max(0, left - 100);
      pendingHorizontal.current = false;
    }
  }, [start, file.file, targetKey, location?.column, locateRequest]);
  return <div ref={viewport} className="source-file-code" role="region" aria-label="原始文件完整代码" tabIndex={0} onScroll={event => setScrollTop(event.currentTarget.scrollTop)}>
    <div className="source-file-lines" style={{ height: lines.length * rowHeight, minWidth: `calc(${width}ch + 80px)` }}>
      {lines.slice(start, end).map((text, index) => {
        const line = start + index + 1;
        const highlighted = !!location && line >= location.line && line <= location.endLine;
        const from = highlighted && line === location.line ? Math.max(0, (location.column || 1) - 1) : 0;
        const to = highlighted && line === location.endLine && location.endColumn ? location.endColumn - 1 : text.length;
        return <div className={`source-file-line ${highlighted ? 'source-current-line' : ''}`} key={line} data-source-line={line} aria-current={line === location?.line ? 'location' : undefined} style={{ top: (line - 1) * rowHeight }}>
          <span className="source-line-number" aria-hidden="true">{line}</span><code>{highlighted ? <>{text.slice(0, from)}<mark data-source-target={line === location?.line ? '' : undefined}>{text.slice(from, to) || ' '}</mark>{text.slice(to)}</> : text || ' '}</code>
        </div>;
      })}
    </div>
  </div>;
}

export default function SourceFileView({ resource, targetKey }: { resource: ReturnType<typeof useSourceFile>; targetKey: string }) {
  const [locateRequest, setLocateRequest] = useState(0);
  const { data: file, location } = resource;
  if (resource.error || !file) return <StateMessage error={resource.error} text="正在读取完整原始文件…" />;
  return <div className="source-file-view" data-source-file={file.file} data-target-line={location?.line}>
    <div className="source-file-toolbar"><span>完整文件 · {file.lineCount.toLocaleString()} 行{location && <> · 当前节点 L{location.line}{location.endLine !== location.line ? `–${location.endLine}` : ''}{location.column ? ` · 第 ${location.column} 列` : ''}</>}</span><button className="button" disabled={!location} onClick={() => setLocateRequest(value => value + 1)}><LocateFixed size={13} />定位当前节点</button></div>
    {!location && <p className="node-note warning-note">已打开完整文件；当前引用未能定位，请核对上方文件与引用路径。</p>}
    <SourceFileCode file={file} location={location} targetKey={targetKey} locateRequest={locateRequest} />
  </div>;
}
