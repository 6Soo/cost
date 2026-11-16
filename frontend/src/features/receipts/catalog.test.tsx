// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ReceiptsPage } from './index';
import { getJSON, postJSON } from '../../api/client';

vi.mock('../../api/client', async (original) => ({
  ...await original<typeof import('../../api/client')>(),
  getJSON: vi.fn(), postJSON: vi.fn(),
}));

beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(getJSON).mockImplementation(async (path) => {
    if (path.startsWith('/api/receipts/paseo/models')) return {
      connected: true, default_provider: 'codex', default_model: 'synthetic-terra', default_thinking: 'high',
      providers: [{ id: 'claude', label: 'Synthetic Claude', available: true }, { id: 'codex', label: 'Synthetic Codex', available: true }],
      models: path.includes('provider=claude') ? [] : [{ provider: 'codex', id: 'synthetic-terra', label: 'Synthetic Terra', selectable: true, effective_thinking: 'high' }],
    } as never;
    if (path === '/api/receipts/workflow') return { batches: [{
      batch_id: 'synthetic-batch', created_at: '2026-11-16T00:00:00Z', provider: 'codex', model: 'synthetic-terra', thinking: 'high', status: 'completed', jobs: [], candidates: [],
    }] } as never;
    return { images: [], candidates: [], pdfs: [], uploads: [] } as never;
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
