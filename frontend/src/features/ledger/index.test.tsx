// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { getJSON } from '../../api/client';
import type { TripSummary } from '../../api/types';
import { LedgerPage } from './index';

vi.mock('../../api/client', async (original) => ({
  ...await original<typeof import('../../api/client')>(), getJSON: vi.fn(),
}));
afterEach(cleanup);

test('shows stored inferred period basis and marks the protected previous-attribution ledger as read-only', async () => {
  const trip: TripSummary = {
    id: 'unclassified', title: '내부 보호 · 이전 귀속 결과', kind: 'quarter', previous: false,
    starts_on: '', ends_on: '', income: '0', expense: '8000', profit: '-8000', closed: false,
    archived: false, protected: true,
  };
  vi.mocked(getJSON).mockResolvedValue({ trip, rows: [
    { id: 'card-syn-inferred', date: '2026-11-16', merchant: '합성 카드 가맹점', description: '',
      category: '숙박비', amount: '8000', currency: 'KRW', payment: '카드',
      period: '2026-11-15~2026-11-16', period_status: 'inferred',
      period_basis: '예약 자료 연결', evidence_summary: '카드', read_only: true },
  ], total_count: 1, page: 1, page_size: 50, total: '8000', filtered_total: '8000', closed: false });

  render(<LedgerPage path="/board" search={new URLSearchParams('tab=unclassified')}
    bootstrap={{ role: 'owner', csrf: 'synthetic', trips: [], capabilities: [], receipt_enabled: false }} />);

  expect((await screen.findAllByText('2026-11-15–2026-11-16')).length).toBeGreaterThan(0);
  expect(screen.getAllByText('추정 · 예약 자료 연결').length).toBeGreaterThan(0);
  expect(screen.getByText('내부 보호 · 이전 귀속 결과 열람')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Google 장부용 복사' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'XLSX 내보내기' })).toBeNull();
});

test('keeps verified and unknown stored period states visible', async () => {
  const trip: TripSummary = {
    id: 'trip-synthetic', title: '합성 여행', kind: 'trip', previous: false,
    starts_on: '2026-11-01', ends_on: '2026-11-02', income: '0', expense: '0', profit: '0',
    closed: false, archived: false,
  };
  vi.mocked(getJSON).mockResolvedValue({ trip, rows: [
    { id: 'card-verified', date: '2026-11-01', merchant: '합성 가맹점', description: '',
      category: '숙박비', amount: '8000', currency: 'KRW', payment: '카드',
      period: '2026-11-01~2026-11-02', period_status: 'verified', evidence_summary: '카드', read_only: true },
    { id: 'card-unknown', date: '2026-11-01', merchant: '합성 가맹점 2', description: '',
      category: '숙박비', amount: '9000', currency: 'KRW', payment: '카드',
      period: '', period_status: 'unknown', evidence_summary: '카드', read_only: true },
    { id: 'card-manual-empty', date: '2026-11-01', merchant: '합성 가맹점 3', description: '',
      category: '숙박비', amount: '10000', currency: 'KRW', payment: '카드',
      period: '', period_status: 'unknown', period_manual_blank: true, evidence_summary: '카드', read_only: true },
  ], total_count: 3, page: 1, page_size: 50, total: '27000', filtered_total: '27000', closed: false });

  render(<LedgerPage path="/board" search={new URLSearchParams('tab=trip-synthetic')}
    bootstrap={{ role: 'viewer', csrf: '', trips: [trip], capabilities: [], receipt_enabled: false }} />);

  expect((await screen.findAllByText('확인됨 · 2026-11-01–2026-11-02')).length).toBeGreaterThan(0);
  expect(screen.getAllByText('기간 근거 없음').length).toBeGreaterThan(0);
  expect(screen.getAllByText('사용자가 비워 둔 이용 기간').length).toBeGreaterThan(0);
});
