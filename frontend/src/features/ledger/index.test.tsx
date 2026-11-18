// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { getJSON } from '../../api/client';
import type { LedgerRow, TripSummary } from '../../api/types';
import { LedgerPage, PeriodValue } from './index';

vi.mock('../../api/client', async (original) => ({
  ...await original<typeof import('../../api/client')>(), getJSON: vi.fn(),
}));
afterEach(cleanup);

const trip: TripSummary = {
  id: 'trip-synthetic', title: '합성 여행', kind: 'trip', previous: false,
  starts_on: '2026-11-01', ends_on: '2026-11-02', income: '0', expense: '0', profit: '0',
  closed: false, archived: false,
};

function row(overrides: Partial<LedgerRow> & { id: string }): LedgerRow {
  return {
    date: '2026-11-01', merchant: '합성 가맹점', description: '', category: '숙박비',
    amount: '8000', currency: 'KRW', payment: '카드', period: '',
    evidence_summary: '카드', read_only: true, ...overrides,
  };
}

function renderPage(rows: LedgerRow[]) {
  vi.mocked(getJSON).mockResolvedValue({
    trip, rows, total_count: rows.length, page: 1, page_size: 50,
    total: '0', filtered_total: '0', closed: false,
  });
  render(<LedgerPage path="/board" search={new URLSearchParams('tab=trip-synthetic')}
    bootstrap={{ role: 'viewer', csrf: '', trips: [trip], capabilities: [], receipt_enabled: false }} />);
}

/**
 * SPEC §11.2.1 계약 4: 확정·추론·미확인·증빙 계산·원본 변경·수동은 서로 구분되어야 하고,
 * 화면은 서버가 준 값을 그대로 보여야 한다 (사용자 결정 2026-11-14: 렌더 시점 판정 금지).
 *
 * The value is asserted verbatim — including its `~` separator — because the screen
 * must not normalise, parse or re-derive what the server already decided.
 */
describe('stored use period on the React ledger', () => {
  test('verified shows the server value as a confirmed period', async () => {
    renderPage([row({ id: 'r-verified', period: '2026-11-15~2026-11-16', period_status: 'verified', period_source: 'decision' })]);
    expect((await screen.findAllByText(/2026-11-15~2026-11-16/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/확인됨/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/추정/)).toHaveLength(0);
  });

  test('inferred shows the same value but is labelled as an inference', async () => {
    renderPage([row({ id: 'r-inferred', period: '2026-11-15~2026-11-16', period_status: 'inferred',
      period_basis: '예약 자료 연결', period_source: 'decision_inferred' })]);
    expect((await screen.findAllByText(/2026-11-15~2026-11-16/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/추정 · 예약 자료 연결/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/확인됨/)).toHaveLength(0);
  });

  test('unknown states what is missing instead of inventing a period', async () => {
    renderPage([row({ id: 'r-unknown', period: '', period_status: 'unknown', period_source: 'decision' })]);
    expect((await screen.findAllByText('기간 근거 없음')).length).toBeGreaterThan(0);
  });

  test('a manual blank is told apart from a missing evidence basis', async () => {
    renderPage([row({ id: 'r-manual-blank', period: '', period_status: 'unknown',
      period_manual_blank: true, period_source: 'manual' })]);
    expect((await screen.findAllByText('사용자가 비워 둔 이용 기간')).length).toBeGreaterThan(0);
  });

  test('computed states that the period came from evidence, not a stored decision', async () => {
    renderPage([row({ id: 'r-computed', period: '2026-11-15~2026-11-16', period_status: 'computed', period_source: 'computed' })]);
    expect((await screen.findAllByText(/2026-11-15~2026-11-16/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/증빙 계산/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/확인됨/)).toHaveLength(0);
  });

  test('a period a person typed is labelled as a manual value', async () => {
    renderPage([row({ id: 'r-manual', period: '2026-11-14~2026-11-17', period_source: 'manual' })]);
    expect((await screen.findAllByText(/2026-11-14~2026-11-17/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/수동 지정/).length).toBeGreaterThan(0);
  });

  test('a changed source hides the saved value and says why', async () => {
    renderPage([row({ id: 'r-stale', period: '', period_status: 'stale', period_source: '' })]);
    expect((await screen.findAllByText('원본이 바뀌어 저장된 기간을 표시하지 않습니다')).length).toBeGreaterThan(0);
  });

  test('renders the server value verbatim and never re-derives it', () => {
    // A value the screen could not have computed: reversed order and an unusual
    // separator must survive untouched, because the screen does not parse it.
    render(<PeriodValue period="2026-11-16~2026-11-15" status="verified" />);
    expect(screen.getByText('2026-11-16~2026-11-15')).toBeTruthy();
  });

  test('a value with no state at all is shown without a status claim', () => {
    render(<PeriodValue period="07.~08. · 1박" />);
    expect(screen.getByText('07.~08. · 1박')).toBeTruthy();
    expect(screen.queryByText(/확인됨|추정|증빙 계산|수동 지정/)).toBeNull();
  });
});
