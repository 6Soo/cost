// @vitest-environment jsdom
/* The Google income source notice belongs to the current trip tab, not to the
   panel: it may only be shown when the response that arrived is the tab the
   operator has selected now, only for a normal trip's owner. Quarter, refund
   and protected tabs have no Google income linkage, a viewer never sees the
   owner notice, and a late response for the previous tab must not paint its
   income_source over the new tab. The Google income totals and the existing
   read-failure notice keep their meaning. */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { getJSON } from '../../api/client';
import type { Bootstrap, TripSummary } from '../../api/types';
import { LedgerPage } from './index';

vi.mock('../../api/client', async (original) => ({
  ...await original<typeof import('../../api/client')>(), getJSON: vi.fn(),
}));
afterEach(cleanup);

const trip: TripSummary = { id: 'syn-trip', title: '합성 여행', kind: 'trip', previous: false,
  starts_on: '2026-07-12', ends_on: '2026-07-16', income: '1000', expense: '100', profit: '900',
  closed: false, archived: false };
const quarter: TripSummary = { id: 'quarter:2026-Q4', title: '2026년 4분기 기타비용', kind: 'quarter', previous: false,
  starts_on: '', ends_on: '', income: '0', expense: '8000', profit: '-8000', closed: false, archived: false };
const refunds: TripSummary = { id: 'refunds', title: '환불', kind: 'quarter', previous: false,
  starts_on: '', ends_on: '', income: '0', expense: '0', profit: '0', closed: false, archived: false };
const unclassified: TripSummary = { id: 'unclassified', title: '내부 보호 · 이전 귀속 결과', kind: 'quarter', previous: false,
  starts_on: '', ends_on: '', income: '0', expense: '8000', profit: '-8000', closed: false, archived: false };

const noSource = { available: false, verified: false, reason: 'NOT_CONNECTED' };

function payload(summary: TripSummary, extra: Record<string, unknown> = {}) {
  return { trip: summary, rows: [], total_count: 0, page: 1, page_size: 50,
    filtered_total: '100', total: '100', closed: false, ...extra };
}

function bootstrapFor(summary: TripSummary, role: 'owner' | 'viewer' = 'owner'): Bootstrap {
  return { role, csrf: role === 'owner' ? 'synthetic' : '', trips: [summary], capabilities: [], receipt_enabled: false };
}

function renderTab(summary: TripSummary, role: 'owner' | 'viewer' = 'owner', search = 'kind=income') {
  return render(<LedgerPage path='/board' search={new URLSearchParams(`tab=${summary.id}&${search}`)}
    bootstrap={bootstrapFor(summary, role)} />);
}

test('an owner of a normal trip is told the Google income ledger is not connected', async () => {
  vi.mocked(getJSON).mockResolvedValue(payload(trip, { income_source: noSource }));
  renderTab(trip);
  expect(await screen.findByText('Google 수입 원장 미연결')).toBeTruthy();
  expect(screen.getByText(/Google 수입 행은 이 여행의 수입 탭에 표시되지 않습니다/)).toBeTruthy();
  // The notice is the unconnected state, not the read-failure warning.
  expect(screen.queryByText('Google 수입 내역을 불러오지 못했습니다')).toBeNull();
  // The notice says only that this trip has no linked Google income rows; it
  // makes no claim about the 조회·전체 합계 or about a confirmed COST figure.
  expect(screen.queryByText(/잠정/)).toBeNull();
});

test('a quarter tab does not show the trip income-source notice', async () => {
  vi.mocked(getJSON).mockResolvedValue(payload(quarter, { income_source: noSource }));
  renderTab(quarter);
  await waitFor(() => expect(getJSON).toHaveBeenCalled());
  expect(screen.queryByText('Google 수입 원장 미연결')).toBeNull();
  expect(screen.queryByText('Google 수입 내역을 불러오지 못했습니다')).toBeNull();
  expect(screen.queryByText('수입 원장 대조 정보')).toBeNull();
});

test('a refund tab does not show the trip income-source notice', async () => {
  vi.mocked(getJSON).mockResolvedValue(payload(refunds, { income_source: noSource }));
  renderTab(refunds);
  await waitFor(() => expect(getJSON).toHaveBeenCalled());
  expect(screen.queryByText('Google 수입 원장 미연결')).toBeNull();
  expect(screen.queryByText('Google 수입 내역을 불러오지 못했습니다')).toBeNull();
});

test('a protected previous-attribution tab does not show the trip income-source notice', async () => {
  vi.mocked(getJSON).mockResolvedValue(payload(unclassified, { income_source: noSource }));
  render(<LedgerPage path='/board' search={new URLSearchParams('tab=unclassified&kind=income')}
    bootstrap={{ role: 'owner', csrf: 'synthetic', trips: [], capabilities: [], receipt_enabled: false }} />);
  await waitFor(() => expect(getJSON).toHaveBeenCalled());
  expect(screen.queryByText('Google 수입 원장 미연결')).toBeNull();
  expect(screen.queryByText('Google 수입 내역을 불러오지 못했습니다')).toBeNull();
});

test('a viewer of the same trip never gets the owner income-source notice', async () => {
  vi.mocked(getJSON).mockResolvedValue(payload(trip, { income_source: noSource }));
  renderTab(trip, 'viewer');
  await waitFor(() => expect(getJSON).toHaveBeenCalled());
  expect(screen.queryByText('Google 수입 원장 미연결')).toBeNull();
});

test('the read-failure notice keeps its existing meaning for a trip owner', async () => {
  vi.mocked(getJSON).mockResolvedValue(payload(trip, { income_source: { available: false, verified: false, reason: 'READ_FAILED' } }));
  renderTab(trip);
  expect(await screen.findByText('Google 수입 내역을 불러오지 못했습니다')).toBeTruthy();
  expect(screen.queryByText('Google 수입 원장 미연결')).toBeNull();
});

/* (e) §11.2.1 계약 1: the summary is computed by the server. The screen shows
   the server's trip.income/trip.profit verbatim and never re-adds the Google
   amount, not even when the Google block is unverified. */
test('an unverified Google block is never re-added to the summary on screen', async () => {
  const summary: TripSummary = { ...trip, income: '1000000', expense: '100000', profit: '900000' };
  vi.mocked(getJSON).mockResolvedValue(payload(summary, {
    income_source: { available: true, verified: false, reason: 'INCOME_UNVERIFIED', total: '1000' },
  }));
  renderTab(summary);
  expect(await screen.findByText('수입 원장 대조 정보')).toBeTruthy();
  // Exactly the server figures: no 항목 shows 1001000 or 1001000-derived 차액.
  expect(screen.getAllByText(/1,000,000/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/900,000/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/1,001,000/)).toBeNull();
  expect(screen.queryByText(/901,000/)).toBeNull();
  // The label is added, the figure is not: both 수입 and 차액 are labelled 잠정
  // so an unverified state is never read as a confirmed number.
  expect(screen.getAllByText('잠정')).toHaveLength(2);
});

test('a verified Google block leaves the summary unmarked', async () => {
  const summary: TripSummary = { ...trip, income: '1000000', expense: '100000', profit: '900000' };
  vi.mocked(getJSON).mockResolvedValue(payload(summary, {
    income_source: { available: true, verified: true, reason: '', total: '1000' },
  }));
  renderTab(summary);
  await waitFor(() => expect(screen.queryByText('장부 조회 중')).toBeNull());
  expect(screen.queryByText('잠정')).toBeNull();
  expect(screen.getByText('검증됨')).toBeTruthy();
});

/* (f) COST-only and COST+Google are distinguishable only by the Google evidence
   line: the summary stays the COST figure in both, and the Google amount shows
   up as separate evidence, never inside the 수입/차액. */
test('COST-only and COST+Google differ by the Google evidence line, not the summary', async () => {
  const summary: TripSummary = { ...trip, income: '1000000', expense: '100000', profit: '900000' };
  vi.mocked(getJSON).mockResolvedValue(payload(summary, { income_source: noSource }));
  renderTab(summary);
  await waitFor(() => expect(screen.queryByText('장부 조회 중')).toBeNull());
  const costOnly = {
    income: screen.getAllByText(/1,000,000/).length,
    profit: screen.getAllByText(/900,000/).length,
    googleEvidence: screen.queryByText('연결된 Google 수입 합계') !== null,
  };

  cleanup();
  vi.mocked(getJSON).mockResolvedValue(payload(summary, {
    income_source: { available: true, verified: true, reason: '', total: '1000' },
  }));
  renderTab(summary);
  await waitFor(() => expect(screen.queryByText('장부 조회 중')).toBeNull());
  // The summary figures are unchanged by the verified Google block (GGL-003).
  expect(screen.getAllByText(/1,000,000/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/900,000/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/1,001,000/)).toBeNull();
  // The difference is that Google income is now shown as separate evidence.
  expect(screen.getByText('연결된 Google 수입 합계')).toBeTruthy();
  expect(screen.getByText('검증됨')).toBeTruthy();
  expect(costOnly.googleEvidence).toBe(false);
});

/* The server's trip.income is "미확인" when it cannot confirm an income figure
   (no COST income and no verified Google block). The summary must show that
   word as a state, never as an amount: no currency unit, no NaN and no
   "미확인원". This is the display risk the new server contract exposes. */
test('an unknown income and 차액 show the word with no currency unit', async () => {
  const summary: TripSummary = { ...trip, income: '미확인', expense: '250000', profit: '미확인' };
  vi.mocked(getJSON).mockResolvedValue(payload(summary, {
    income_source: { available: true, verified: false, reason: 'INCOME_UNVERIFIED' },
  }));
  renderTab(summary);
  await waitFor(() => expect(screen.queryByText('장부 조회 중')).toBeNull());
  // Both summary words render as exactly "미확인", with no currency unit.
  const unknown = screen.getAllByText('미확인');
  expect(unknown.length).toBeGreaterThanOrEqual(2);
  for (const node of unknown) expect(node.textContent).toBe('미확인');
  // A currency-formatted expense is still money.
  expect(screen.getAllByText(/250,000/).length).toBeGreaterThan(0);
  // No broken currency rendering of the unknown state.
  expect(screen.queryByText(/미확인\s*원/)).toBeNull();
  expect(screen.queryByText(/미확인\s*KRW/)).toBeNull();
  expect(screen.queryByText(/NaN/)).toBeNull();
  expect(screen.queryByText(/₩미확인/)).toBeNull();
  // The unverified state is labelled provisional without changing the word.
  expect(screen.getAllByText('잠정')).toHaveLength(2);
});

test('an unknown income with no Google block still shows the word, not money', async () => {
  const summary: TripSummary = { ...trip, income: '미확인', expense: '0', profit: '미확인' };
  vi.mocked(getJSON).mockResolvedValue(payload(summary, { income_source: noSource }));
  renderTab(summary);
  await waitFor(() => expect(screen.queryByText('장부 조회 중')).toBeNull());
  const unknown = screen.getAllByText('미확인');
  for (const node of unknown) expect(node.textContent).toBe('미확인');
  expect(screen.queryByText(/NaN/)).toBeNull();
  expect(screen.queryByText(/미확인\s*(원|KRW)/)).toBeNull();
});

test('a payload left over from the previous tab does not paint its income source on the new tab', async () => {
  /* The operator switches from trip-a to trip-b. Until trip-b answers, the
     previous payload is still in component state (the list keeps the old rows
     while loading). That leftover payload describes trip-a, so its unconnected
     Google source must not be attributed to trip-b. */
  vi.mocked(getJSON).mockImplementation(((url: string) => String(url).includes('tab=trip-a')
    ? Promise.resolve(payload({ ...trip, id: 'trip-a' }, { income_source: noSource }))
    : new Promise(() => {})) as typeof getJSON);

  window.history.replaceState(null, '', '/board?tab=trip-a&kind=income');
  render(<LedgerPage path='/board' search={new URLSearchParams('tab=trip-a&kind=income')}
    bootstrap={{ ...bootstrapFor(trip), trips: [ { ...trip, id: 'trip-a' }, { ...trip, id: 'trip-b' } ] }} />);
  expect(await screen.findByText('Google 수입 원장 미연결')).toBeTruthy();

  window.history.replaceState(null, '', '/board?tab=trip-b&kind=income');
  window.dispatchEvent(new PopStateEvent('popstate'));
  // trip-b is still loading; the trip-a payload is stale.
  await waitFor(() => expect(screen.queryByText('Google 수입 원장 미연결')).toBeNull());
});

test('a late response for the previous tab does not paint its income source over the new tab', async () => {
  /* Order: the operator picks trip A, then switches to trip B before A answers.
     A's response arrives last. Only B's response may describe the visible tab. */
  const deferred: Array<{ url: string; resolve: (value: unknown) => void }> = [];
  vi.mocked(getJSON).mockImplementation(((url: string) => new Promise((resolve) => {
    deferred.push({ url: String(url), resolve: resolve as (value: unknown) => void });
  })) as typeof getJSON);

  window.history.replaceState(null, '', '/board?tab=trip-a&kind=income');
  render(<LedgerPage path='/board' search={new URLSearchParams('tab=trip-a&kind=income')}
    bootstrap={{ ...bootstrapFor(trip), trips: [ { ...trip, id: 'trip-a' }, { ...trip, id: 'trip-b' } ] }} />);
  await waitFor(() => expect(deferred.length).toBe(1));
  expect(deferred[0].url).toContain('tab=trip-a');

  // The operator switches to trip-b before trip-a answers.
  window.history.replaceState(null, '', '/board?tab=trip-b&kind=income');
  window.dispatchEvent(new PopStateEvent('popstate'));
  await waitFor(() => expect(deferred.length).toBe(2));
  expect(deferred[1].url).toContain('tab=trip-b');

  // The new tab answers first with a verified source: no notice for it.
  deferred[1].resolve({ ...payload({ ...trip, id: 'trip-b' },
    { income_source: { available: true, verified: true, reason: '' } }),
    rows: [ { id: 'card-b', date: '2026-07-13', merchant: 'B 합성 행', description: '', category: '식비',
      amount: '100', currency: 'KRW', payment: '카드', period: '', evidence_summary: '', read_only: false } ],
    total_count: 1 });
  await waitFor(() => expect(screen.queryByText('장부 조회 중')).toBeNull());
  expect((await screen.findAllByText('B 합성 행')).length).toBeGreaterThan(0);

  // The previous tab's late answer carries the unconnected state and its own
  // row. It belongs to trip-a, so neither may appear on the trip-b screen.
  deferred[0].resolve({ ...payload({ ...trip, id: 'trip-a' }, { income_source: noSource }),
    rows: [ { id: 'card-a', date: '2026-07-13', merchant: 'A 합성 행', description: '', category: '식비',
      amount: '100', currency: 'KRW', payment: '카드', period: '', evidence_summary: '', read_only: false } ],
    total_count: 1 });
  await waitFor(() => expect(screen.queryByText('Google 수입 원장 미연결')).toBeNull());
  expect(screen.queryByText('수입 원장 대조 정보')).toBeNull();
  expect(screen.queryByText('A 합성 행')).toBeNull();
  expect(screen.getAllByText('B 합성 행').length).toBeGreaterThan(0);
});
