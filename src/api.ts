import { useEffect, useState } from 'react';

type ResourceRequest = { controller: AbortController; promise: Promise<unknown>; subscribers: number };
const snapshots = new Map<string, unknown>();
const pendingSnapshots = new Map<string, ResourceRequest>();
const snapshotLimit = 96;

function requestResource(url: string, key: string, cache: boolean): ResourceRequest {
  const pending = cache ? pendingSnapshots.get(key) : undefined;
  if (pending) return pending;
  const controller = new AbortController();
  const request: ResourceRequest = { controller, subscribers: 0, promise: Promise.resolve() };
  request.promise = fetch(url, { signal: controller.signal }).then(async response => {
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || '读取失败');
    if (cache && !controller.signal.aborted) {
      snapshots.delete(key); snapshots.set(key, body);
      if (snapshots.size > snapshotLimit) snapshots.delete(snapshots.keys().next().value!);
    }
    return body;
  }).finally(() => { if (pendingSnapshots.get(key) === request) pendingSnapshots.delete(key); });
  if (cache) pendingSnapshots.set(key, request);
  return request;
}

// Opt-in caching is for immutable snapshot URLs; live catalog/search requests remain uncached.
export function useResource<T>(url: string | null, revision = 0, cache = false) {
  const key = `${revision}:${url || ''}`;
  const [state, setState] = useState<{ key: string; data: T | null; error: string; loading: boolean }>({ key: '', data: null, error: '', loading: false });
  const cached = url && cache ? snapshots.get(key) as T | undefined : undefined;
  useEffect(() => {
    if (!url) return;
    if (cache && snapshots.has(key)) {
      const value = snapshots.get(key) as T;
      snapshots.delete(key); snapshots.set(key, value);
      setState({ key, data: value, error: '', loading: false });
      return;
    }
    let active = true;
    const request = requestResource(url, key, cache);
    request.subscribers++;
    setState({ key, data: null, error: '', loading: true });
    request.promise.then(body => {
      if (active && !request.controller.signal.aborted) setState({ key, data: body as T, error: '', loading: false });
    }).catch(error => {
      if (active && !request.controller.signal.aborted) setState({ key, data: null, error: String(error.message), loading: false });
    });
    return () => {
      active = false; request.subscribers--;
      // Another view can subscribe in the same commit when granularity changes.
      queueMicrotask(() => {
        if (!request.subscribers && (!cache || pendingSnapshots.get(key) === request)) {
          if (cache) pendingSnapshots.delete(key);
          request.controller.abort();
        }
      });
    };
  }, [url, revision, cache]);
  if (!url) return { data: null, error: '', loading: false };
  if (cached !== undefined) return { data: cached, error: '', loading: false };
  return state.key === key ? { data: state.data, error: state.error, loading: state.loading } : { data: null, error: '', loading: true };
}

export function saveJson(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name.replace(/[\\/:*?"<>|]/g, '_'); anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const apiParams = (params: Record<string, string | number>) => new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]))).toString();
