// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ReceiptsPage } from './index';
import { getJSON, postJSON } from '../../api/client';

vi.mock('../../api/client', async (original) => ({
  ...await original<typeof import('../../api/client')>(),
  getJSON: vi.fn(), postJSON: vi.fn(),
}));

let legacySources = { images: [] as string[], candidates: [], pdfs: [] as Array<{ sha256: string; pages: string[] }>, uploads: [] };

beforeEach(() => {
  sessionStorage.clear();
  legacySources = { images: [], candidates: [], pdfs: [], uploads: [] };
  vi.mocked(getJSON).mockImplementation(async (path) => {
    if (path.startsWith('/api/receipts/paseo/models')) return {
      connected: true, default_provider: 'codex', default_model: 'synthetic-terra', default_thinking: 'high',
      providers: [{ id: 'claude', label: 'Synthetic Claude', available: true }, { id: 'codex', label: 'Synthetic Codex', available: true }],
      models: path.includes('provider=claude') ? [] : [{ provider: 'codex', id: 'synthetic-terra', label: 'Synthetic Terra', selectable: true, effective_thinking: 'high' }],
    } as never;
    if (path === '/api/receipts/workflow') return { batches: [{
      batch_id: 'synthetic-batch', created_at: '2026-11-16T00:00:00Z', provider: 'codex', model: 'synthetic-terra', thinking: 'high', status: 'completed', jobs: [], candidates: [],
    }] } as never;
    return legacySources as never;
  });
});
afterEach(cleanup);

test('uses the server default provider without submitting a model run', async () => {
  render(<ReceiptsPage bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: true }} path='/receipts' search={new URLSearchParams()} />);
  await waitFor(() => expect((screen.getByLabelText('Provider') as HTMLSelectElement).value).toBe('codex'));
  expect(postJSON).not.toHaveBeenCalled();
});

test('shows the actual batch model and effective reasoning level', async () => {
  render(<ReceiptsPage bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: true }} path='/receipts' search={new URLSearchParams()} />);
  await waitFor(() => expect(screen.getByText('codex · synthetic-terra · high')).toBeTruthy());
  expect(screen.getByText('적용 추론 · high')).toBeTruthy();
  expect(postJSON).not.toHaveBeenCalled();
});

test('preserves the PDF original link when a page also appears in the images list', async () => {
  legacySources = { images: ['synthetic-page'], candidates: [], pdfs: [{ sha256: 'synthetic-pdf', pages: ['synthetic-page'] }], uploads: [] };
  const { container } = render(<ReceiptsPage bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: true }} path='/receipts' search={new URLSearchParams()} />);
  const original = await screen.findByRole('link', { name: 'PDF 원본 열기' });
  expect(original.getAttribute('href')).toBe('/api/receipts/pdf/synthetic-pdf');
  expect(container.querySelectorAll('.receipt-source-tile').length).toBe(1);
});
