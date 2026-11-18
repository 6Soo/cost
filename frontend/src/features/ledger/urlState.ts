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

export type LedgerKind = 'expense' | 'income';

export function normalizeLedgerKind(value: string | null | undefined): LedgerKind {
  return value === 'in' || value === 'income' ? 'income' : 'expense';
}

export function legacyLedgerKind(kind: LedgerKind): 'ex' | 'in' {
  return kind === 'income' ? 'in' : 'ex';
}

const BOARD_STATE_KEYS = ['tab', 'kind', 'q', 'sort', 'page_size', 'page', 'arch'] as const;

const BOARD_SORTS = ['date_desc', 'date_asc', 'amount_desc', 'amount_asc', 'merchant_asc'] as const;
const BOARD_PAGE_SIZE_MAX = 200;
const BOARD_PAGE_MAX_DIGITS = 6;

function boundedPositiveInt(value: string | null, maximum?: number): string | null {
  if (value === null || value === '') return null;
  if (!/^[0-9]+$/.test(value)) return null;
  if (value.length > BOARD_PAGE_MAX_DIGITS) return null;
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1) return null;
  if (maximum !== undefined && number > maximum) return null;
  return String(number);
}

export type BoardStateDefaults = { tab?: string; kind?: LedgerKind };

export function boardStateHref(search: URLSearchParams, defaults: BoardStateDefaults = {}): string {
  const params = new URLSearchParams();
  BOARD_STATE_KEYS.forEach((key) => {
    let value = search.get(key);
    if ((value === null || value === '') && key === 'tab') value = defaults.tab ?? null;
    if ((value === null || value === '') && key === 'kind') value = defaults.kind ?? null;
    if (value === null || value === '') return;
    if (key === 'kind') {
      params.set(key, normalizeLedgerKind(value));
      return;
    }
    if (key === 'sort') {
      if (!(BOARD_SORTS as readonly string[]).includes(value)) return;
    } else if (key === 'page_size') {
      const size = boundedPositiveInt(value, BOARD_PAGE_SIZE_MAX);
      if (size === null) return;
      value = size;
    } else if (key === 'page') {
      const page = boundedPositiveInt(value);
      if (page === null) return;
      value = page;
    }
    params.set(key, value);
  });
  const query = params.toString();
  return `/board${query ? `?${query}` : ''}`;
}

export function legacyCorrectionHref(rowId: string, tab: string, kind: LedgerKind, search: URLSearchParams): string {
  const params = new URLSearchParams({ tab, kind: legacyLedgerKind(kind), row: rowId, legacy: '1' });
  const q = search.get('q');
  if (q) params.set('q', q);
  params.set('return_to', boardStateHref(search, { tab, kind }));
  return `/board?${params.toString()}`;
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
