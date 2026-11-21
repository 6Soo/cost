// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { getJSON } from '../../api/client';
import type { LedgerRow, TripSummary } from '../../api/types';
import type { ArchiveExpensesPayload } from './index';
import { LedgerPage } from './index';

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

function archiveRow(overrides: Partial<ArchiveExpensesPayload['rows'][number]> & { row: number }) {
  return {
    date: '2026-11-01',
    payee: '합성 가맹점',
    category: '숙박비',
    period: '11.01–11.02',
    evidence: '카드 명세서',
    amount: '8000',
    ...overrides,
  };
}

function renderPage(payload: {
  rows: LedgerRow[];
  search?: string;
  archive?: ArchiveExpensesPayload;
  role?: 'viewer' | 'owner';
}) {
  vi.mocked(getJSON).mockResolvedValue({
    trip, rows: payload.rows, total_count: payload.rows.length, page: 1, page_size: 50,
    total: '0', filtered_total: '0', closed: false,
    ...(payload.archive ? { archive_expenses: payload.archive } : {}),
  });
  render(<LedgerPage path="/board" search={new URLSearchParams(payload.search ?? 'tab=trip-synthetic')}
    bootstrap={{ role: payload.role ?? 'viewer', csrf: '', trips: [trip], capabilities: [], receipt_enabled: false }} />);
}

describe('Google 보관 지출 원장', () => {
  test('네이티브 0건이면 빈 상태 대신 행·출처·미확인 금액·미검증 상태를 보인다', async () => {
    renderPage({
      rows: [],
      archive: { verified: false, total_count: 2, rows: [archiveRow({ row: 1 }), archiveRow({ row: 2, amount: null, evidence: '' })] },
    });

    const table = await screen.findByRole('table', { name: 'Google 보관 원장 지출 목록' });
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText('Google 보관 원장 · 2건')).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Google 보관 지출 원장' })).toBeTruthy();
    expect(within(table).getAllByText('미확인')).toHaveLength(1);
    expect(within(table).getByText('출처 없음')).toBeTruthy();
    expect(screen.getByText('미검증')).toBeTruthy();
    // 보관 전용 보기에는 실제 작동하지 않는 컨트롤·0원 KPI가 없다.
    expect(screen.queryByText('지출 내역이 없습니다')).toBeNull();
    expect(screen.queryByText('조회 합계')).toBeNull();
    expect(screen.getByLabelText('장부 검색')).toBeTruthy();
    expect(screen.getByLabelText('정렬')).toBeTruthy();
    expect(screen.queryByLabelText('페이지당 행')).toBeNull();
    expect(within(table).queryByRole('button')).toBeNull();
  });

  test('보관 payload가 있고 검색 0건이면 같은 원장 제목 아래 검색 결과 없음만 표시한다', async () => {
    renderPage({
      rows: [],
      search: 'tab=trip-synthetic&q=없는검색',
      archive: { verified: true, total_count: 131, rows: [] },
    });

    expect(await screen.findByText('Google 보관 원장 · 131건')).toBeTruthy();
    expect(screen.getByText('검색 결과가 없습니다')).toBeTruthy();
    expect(screen.queryByText('지출 내역이 없습니다')).toBeNull();
    expect(screen.queryByText('조회 합계')).toBeNull();
  });

  test('보관 payload가 있고 네이티브 검색 0건이 아니면 표시된 보관 행이 없다', async () => {
    renderPage({
      rows: [],
      archive: { verified: true, total_count: 0, rows: [] },
    });

    expect(await screen.findByText('Google 보관 원장 · 0건')).toBeTruthy();
    expect(screen.getByText('표시할 Google 보관 지출 행이 없습니다')).toBeTruthy();
    expect(screen.queryByText('지출 내역이 없습니다')).toBeNull();
  });

  test('수입 탭은 보관 원장과 무관하게 기존대로 동작한다', async () => {
    renderPage({
      rows: [],
      search: 'tab=trip-synthetic&kind=income',
      archive: { verified: true, total_count: 1, rows: [archiveRow({ row: 1 })] },
    });

    await screen.findByRole('heading', { name: trip.title });
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(screen.queryByText('Google 보관 원장 · 1건')).toBeNull();
    expect(screen.queryByRole('table', { name: 'Google 보관 원장 지출 목록' })).toBeNull();
    expect(screen.getByText('수입 내역이 없습니다')).toBeTruthy();
    expect(screen.getByText('조회 합계')).toBeTruthy();
  });

  test('기장 지출은 기존 표와 행 열기를 사용한다', async () => {
    renderPage({ rows: [row({ id: 'native-1' })] });

    const native = await screen.findByRole('table', { name: '여행 장부 거래 목록' });
    expect(within(native).getByRole('button', { name: '합성 가맹점' })).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Google 보관 원장 지출 목록' })).toBeNull();
    expect(screen.getByText('조회 합계')).toBeTruthy();
  });

  test('131행 규모에서도 전부 렌더링된다', async () => {
    const archiveRows = Array.from({ length: 131 }, (_, index) =>
      archiveRow({ row: index + 1, amount: index % 7 === 0 ? null : '8000' }));
    renderPage({ rows: [], archive: { verified: false, total_count: archiveRows.length, rows: archiveRows } });

    const table = await screen.findByRole('table', { name: 'Google 보관 원장 지출 목록' });
    expect(within(table).getAllByRole('row')).toHaveLength(132);
    expect(within(table).getAllByText('미확인')).toHaveLength(archiveRows.filter((item) => item.amount === null).length);
  });

  test('보관 payload가 없으면 기존 빈 상태가 유지된다', async () => {
    renderPage({ rows: [] });
    expect(await screen.findByText('지출 내역이 없습니다')).toBeTruthy();
    expect(screen.getByText('조회 합계')).toBeTruthy();
  });

  test('보관 전용 보기에서는 실제 작동하지 않는 내보내기·복사와 페이지당 행을 숨긴다', async () => {
    renderPage({
      rows: [],
      role: 'owner',
      archive: { verified: true, total_count: 1, rows: [archiveRow({ row: 1 })] },
    });

    expect(await screen.findByText('Google 보관 원장 · 1건')).toBeTruthy();
    expect(screen.queryByText('XLSX 내보내기')).toBeNull();
    expect(screen.queryByText('Google 장부용 복사')).toBeNull();
    expect(screen.queryByLabelText('페이지당 행')).toBeNull();
  });
});
