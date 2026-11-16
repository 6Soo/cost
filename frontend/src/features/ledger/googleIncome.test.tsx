// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { LedgerPage } from './index';
import { getJSON } from '../../api/client';
import type { TripSummary } from '../../api/types';

vi.mock('../../api/client', async (original) => ({
  ...await original<typeof import('../../api/client')>(), getJSON: vi.fn(),
}));
afterEach(cleanup);

test('shows Google income rows and warns that incomplete income and profit are provisional', async () => {
  const trip: TripSummary = { id: 'syn-trip', title: '합성 여행', kind: 'trip', previous: false,
    starts_on: '2026-07-12', ends_on: '2026-07-16', income: '1000', expense: '100', profit: '900', closed: false, archived: false };
  vi.mocked(getJSON).mockResolvedValue({ trip, rows: [
    { id: 'google-income|syn-trip|main|18', date: '', merchant: 'SYNTHETIC INCOME', description: '예약금 200000원',
      amount: '미확인', currency: 'KRW', category: 'Google 수입', payment: 'Google', period: '', evidence_summary: '', read_only: true },
  ], total_count: 1, page: 1, page_size: 50, total: '1000', filtered_total: '1000', closed: false,
  income_source: { available: true, verified: false, reason: 'INCOME_UNVERIFIED' } });
  render(<LedgerPage path='/ledger' search={new URLSearchParams('tab=syn-trip&kind=income')}
    bootstrap={{ role: 'owner', csrf: 'synthetic', trips: [trip], capabilities: [], receipt_enabled: false }} />);
  expect(await screen.findByText('수입 원장 대조 정보')).toBeTruthy();
  expect(screen.getByText(/수입과 차액은 잠정 금액/)).toBeTruthy();
  expect(screen.getAllByText('SYNTHETIC INCOME').length).toBeGreaterThan(0);
  expect(screen.getAllByText(/미확인/).length).toBeGreaterThan(0);
});
