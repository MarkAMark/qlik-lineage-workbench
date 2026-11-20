import { Fragment, useEffect, useMemo, useState } from 'react';
import { ChevronRight, LayoutDashboard, Search } from 'lucide-react';
import type { Catalog } from './types';

export default function StreamAppList({ catalog, streamId, appId, active, onStream, onApp }: {
  catalog: Catalog | null; streamId: string; appId: string; active: boolean;
  onStream: (id: string) => void; onApp: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  useEffect(() => { setQuery(''); }, [streamId]);
  const groups = useMemo(() => (catalog?.streams || []).filter(stream => !streamId || stream.id === streamId).map(stream => ({ ...stream,
    apps: (catalog?.apps || []).filter(app => app.stream.id === stream.id && `${app.name} ${app.folder}`.toLowerCase().includes(query.toLowerCase())) })), [catalog, streamId, query]);
  useEffect(() => {
    const app = catalog?.apps.find(app => app.id === appId);
    if (app && query && !`${app.name} ${app.folder}`.toLowerCase().includes(query.toLowerCase())) setQuery('');
  }, [appId]);
  return <><label className="stream-select"><span>QLIK STREAM</span><select aria-label="选择 Stream" value={streamId} onChange={event => onStream(event.target.value)}>
    <option value="">全部应用 · {catalog?.totals.streams || 0} Streams</option>
    {catalog?.streams.map(stream => <option key={stream.id} value={stream.id}>{stream.name} · {stream.appCount} Apps{stream.errorCount ? ` · ${stream.errorCount} 失败` : ''}</option>)}
  </select></label><div className="app-search"><Search size={13} /><input aria-label="搜索应用" placeholder="搜索当前 Stream 的 App…" value={query} onChange={event => setQuery(event.target.value)} /></div>
    <div className="app-list-heading"><span>QLIK APPLICATIONS</span><span>{groups.reduce((sum, group) => sum + group.apps.length, 0)}</span></div>
    <div className="app-list">{groups.map(group => <Fragment key={group.id}><div className="stream-group-heading" data-stream-id={group.id} title={group.name}><strong>{group.name}</strong><span>{group.apps.length}</span></div>
      {group.apps.map(app => <button data-app-id={app.id} data-stream-id={group.id} className={appId === app.id && active ? 'active' : ''} key={app.id} onClick={() => onApp(app.id)} title={app.name}>
        <span className="app-list-icon"><LayoutDashboard size={15} /></span><div><strong>{app.name}</strong><span>{app.stats.sheets} Sheets · {app.stats.fields} 个字段</span></div>{appId === app.id && active && <ChevronRight size={13} />}
      </button>)}{!group.apps.length && <p className="stream-empty">{group.errorCount ? '此分组导入失败，请查看导入提示。' : '没有匹配的 App。'}</p>}</Fragment>)}</div></>;
}
