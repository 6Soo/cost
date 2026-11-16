import { useCallback, useEffect, useState } from 'react';

export type UrlPatch = Record<string, string | number | null | undefined>;

export function useUrlSearch(initial: URLSearchParams) {
  const [search, setSearch] = useState(() => new URLSearchParams(initial.toString()));

  useEffect(() => {
    const restore = () => setSearch(new URLSearchParams(window.location.search));
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);

  const update = useCallback((patch: UrlPatch, replace = false) => {
    const next = new URLSearchParams(window.location.search);
    Object.entries(patch).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') next.delete(key);
      else next.set(key, String(value));
    });
    const query = next.toString();
    const href = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
    if (replace) window.history.replaceState(window.history.state, '', href);
    else window.history.pushState(window.history.state, '', href);
    setSearch(next);
  }, []);

  return { search, update };
}

export function readPage(search: URLSearchParams, fallback = 1): number {
  const page = Number.parseInt(search.get('page') || '', 10);
  return Number.isFinite(page) && page > 0 ? page : fallback;
}

export function internalHref(value: string): string | null {
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return null;
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : null;
  } catch {
    return null;
  }
}

export function humanDate(value: string): string {
  if (!value) return '날짜 없음';
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(parsed);
}

export function requestId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `cost-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
