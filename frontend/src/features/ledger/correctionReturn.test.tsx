// @vitest-environment jsdom
import type { ReactNode } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { RowDrawer } from './rowDrawer';
import { getJSON } from '../../api/client';
import type { LedgerRow } from '../../api/types';

vi.mock('../../components', async (original) => ({
  ...(await original<typeof import('../../components')>()),
  Drawer: ({ children, open }: { children: ReactNode; open: boolean }) => open ? <div role='dialog'>{children}</div> : null,
}));
vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()),
  getJSON: vi.fn(),
  postJSON: vi.fn(),
}));
afterEach(cleanup);

const owner = { role: 'owner', csrf: 'synthetic', trips: [], capabilities: [], receipt_enabled: false };

function row(overrides: Partial<LedgerRow> = {}): LedgerRow {
  return {
    id: 'card-syn-1', date: '2026-11-12', merchant: '합성 가맹점', description: '합성 행',
    amount: '5000', currency: 'KRW', category: '식비', payment: '현금', period: '',
    evidence_summary: '카드', read_only: false, ...overrides,
  } as LedgerRow;
}

function renderDrawer(props: { role?: string; readOnly?: boolean; search?: URLSearchParams; tab?: string }) {
  vi.mocked(getJSON).mockResolvedValue({
    row: row({ read_only: props.readOnly ?? false }),
    source: {}, decision: {}, history: [], expected_revision: 1,
    actions: [], edit_fields: [],
  });
  const search = props.search ?? new URLSearchParams('tab=syn-trip&kind=expense&q=식비&sort=merchant_asc&page=3');
  render(
    <RowDrawer
      rowId="card-syn-1"
      bootstrap={{ ...owner, role: props.role ?? 'owner' } as never}
      tab={props.tab ?? 'syn-trip'}
      kind="expense"
      search={search}
      onClose={vi.fn()}
      onSaved={vi.fn()}
    />,
  );
}

test('an owner on an editable row gets the legacy correction link with the full return state', async () => {
  renderDrawer({});
  const link = await screen.findByRole('link', { name: '기존 화면에서 교정' });
  const href = link.getAttribute('href') ?? '';
  expect(href).toContain('legacy=1');
  expect(href).toContain('row=card-syn-1');
  expect(href).toContain('tab=syn-trip');
  expect(href).toContain('kind=ex');
  const back = new URL(href, 'http://localhost').searchParams.get('return_to') ?? '';
  const parsed = new URL(back, 'http://localhost');
  expect(parsed.pathname).toBe('/board');
  expect(parsed.searchParams.get('sort')).toBe('merchant_asc');
  expect(parsed.searchParams.get('page')).toBe('3');
  expect(parsed.searchParams.get('page_size')).toBeNull();
  expect(parsed.searchParams.get('tab')).toBe('syn-trip');
  expect(parsed.searchParams.get('q')).toBe('식비');
  expect(parsed.searchParams.get('row')).toBeNull();
  expect(parsed.searchParams.get('legacy')).toBeNull();
});

test('a read-only row shows no correction link', async () => {
  renderDrawer({ readOnly: true });
  await waitFor(() => expect(screen.queryByRole('link', { name: '기존 화면에서 교정' })).toBeNull());
});

test('a viewer sees no correction link', async () => {
  renderDrawer({ role: 'viewer' });
  await waitFor(() => expect(screen.queryByRole('link', { name: '기존 화면에서 교정' })).toBeNull());
});

test('an explicit page size and the archived drawer survive the return', async () => {
  renderDrawer({ search: new URLSearchParams('tab=syn-trip&kind=expense&sort=merchant_asc&page=3&page_size=100&arch=previous') });
  const link = await screen.findByRole('link', { name: '기존 화면에서 교정' });
  const back = new URL(new URL(link.getAttribute('href') ?? '', 'http://localhost').searchParams.get('return_to') ?? '', 'http://localhost');
  expect(back.searchParams.get('page_size')).toBe('100');
  expect(back.searchParams.get('arch')).toBe('previous');
  expect(back.searchParams.get('sort')).toBe('merchant_asc');
  expect(back.searchParams.get('page')).toBe('3');
});

test('the first-trip default entry still gets a tab in the return state', async () => {
  renderDrawer({ search: new URLSearchParams('sort=merchant_asc&page=3&q=식비'), tab: 'first-trip' });
  const link = await screen.findByRole('link', { name: '기존 화면에서 교정' });
  const back = new URL(new URL(link.getAttribute('href') ?? '', 'http://localhost').searchParams.get('return_to') ?? '', 'http://localhost');
  expect(back.searchParams.get('tab')).toBe('first-trip');
  expect(back.searchParams.get('kind')).toBe('expense');
  expect(back.searchParams.get('sort')).toBe('merchant_asc');
  expect(back.searchParams.get('page')).toBe('3');
  expect(back.searchParams.get('q')).toBe('식비');
});

test('out-of-range values are dropped instead of throwing', async () => {
  renderDrawer({ search: new URLSearchParams('tab=syn-trip&kind=expense&sort=bogus&page=0&page_size=999') });
  const link = await screen.findByRole('link', { name: '기존 화면에서 교정' });
  const back = new URL(new URL(link.getAttribute('href') ?? '', 'http://localhost').searchParams.get('return_to') ?? '', 'http://localhost');
  expect(back.searchParams.get('sort')).toBeNull();
  expect(back.searchParams.get('page')).toBeNull();
  expect(back.searchParams.get('page_size')).toBeNull();
  expect(back.searchParams.get('tab')).toBe('syn-trip');
});

test('the page and page_size bounds match the server verifier exactly', async () => {
  renderDrawer({ search: new URLSearchParams('tab=syn-trip&kind=expense&page=2&page_size=200') });
  const link = await screen.findByRole('link', { name: '기존 화면에서 교정' });
  const back = new URL(
    new URL(link.getAttribute('href') ?? '', 'http://localhost').searchParams.get('return_to') ?? '',
    'http://localhost',
  );
  expect(back.searchParams.get('page')).toBe('2');
  expect(back.searchParams.get('page_size')).toBe('200');
});

test('a page_size above the server bound and an over-long numeral are dropped', async () => {
  renderDrawer({ search: new URLSearchParams('tab=syn-trip&kind=expense&page_size=201&page=9999999') });
  const link = await screen.findByRole('link', { name: '기존 화면에서 교정' });
  const back = new URL(
    new URL(link.getAttribute('href') ?? '', 'http://localhost').searchParams.get('return_to') ?? '',
    'http://localhost',
  );
  expect(back.searchParams.get('page_size')).toBeNull();
  expect(back.searchParams.get('page')).toBeNull();
  expect(back.searchParams.get('tab')).toBe('syn-trip');
});

test('a six-digit page is kept and its normalised spelling is used', async () => {
  renderDrawer({ search: new URLSearchParams('tab=syn-trip&kind=expense&page=000123&page_size=025') });
  const link = await screen.findByRole('link', { name: '기존 화면에서 교정' });
  const back = new URL(
    new URL(link.getAttribute('href') ?? '', 'http://localhost').searchParams.get('return_to') ?? '',
    'http://localhost',
  );
  expect(back.searchParams.get('page')).toBe('123');
  expect(back.searchParams.get('page_size')).toBe('25');
});
