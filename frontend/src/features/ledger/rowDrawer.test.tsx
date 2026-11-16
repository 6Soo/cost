// @vitest-environment jsdom
import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { RowDrawer } from './rowDrawer';
import { getJSON, postJSON } from '../../api/client';

vi.mock('../../api/client', async (original) => ({
  ...await original<typeof import('../../api/client')>(), getJSON: vi.fn(), postJSON: vi.fn(),
}));
vi.mock('../../components', async (original) => ({
  ...await original<typeof import('../../components')>(),
  Drawer: ({ children, open }: { children: ReactNode; open: boolean }) => open ? <div role='dialog'>{children}</div> : null,
}));

beforeEach(() => {
  vi.mocked(postJSON).mockResolvedValue({});
  vi.mocked(getJSON).mockResolvedValue({
    row: { id: 'synthetic-allocation', date: '2026-11-16', merchant: '합성 배분', description: '', category: '교통비', amount: '100', currency: 'KRW', read_only: false },
    source: null, decision: null, history: [], expected_revision: 7,
    actions: [{ id: 'row-save', label: '수정', href: '/api/rows/synthetic-allocation/save', method: 'POST', encoding: 'json', csrf: 'header', response: 'json', fields: [
      { name: 'item', label: '항목', type: 'text', value: '교통비' },
      { name: 'expected_revision', label: 'revision', type: 'hidden', value: 7 },
      { name: 'client_request_id', label: '요청 ID', type: 'hidden' },
    ] }],
  });
});
afterEach(cleanup);

test('submits only server-advertised allocation fields plus concurrency identifiers', async () => {
  render(<RowDrawer rowId='synthetic-allocation' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: '수정' }));
  fireEvent.click(screen.getByRole('button', { name: '저장' }));
  await waitFor(() => expect(postJSON).toHaveBeenCalledTimes(1));
  const [path, payload, csrf] = vi.mocked(postJSON).mock.calls[0];
  expect(path).toBe('/api/rows/synthetic-allocation/save');
  expect(payload).toEqual({ item: '교통비', expected_revision: 7, client_request_id: expect.any(String) });
  expect(csrf).toBe('synthetic-csrf');
});
