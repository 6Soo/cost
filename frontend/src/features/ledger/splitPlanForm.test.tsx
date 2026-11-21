// @vitest-environment jsdom
// Synthetic tests for the Plush income split-plan form.
//
// The form is read-only w.r.t. the store: it renders a structurally-read
// source/plan and posts the full desired allocation array to the existing
// legacy authority. These tests use fixtures only.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { postJSON } from '../../api/client';
import { SplitPlanForm, type SplitAllocation, type SplitSource } from './splitPlanForm';

vi.mock('../../api/client', async (original) => ({
  ...(await original<typeof import('../../api/client')>()), postJSON: vi.fn(),
}));
afterEach(cleanup);

function makeSource(overrides: Partial<SplitSource> = {}): SplitSource {
  return { row_id: 'inc-synth', revision: 3, amount_krw: 1000000,
    source_kind: '은행', ...overrides };
}

function makeAllocation(overrides: Partial<SplitAllocation> = {}): SplitAllocation {
  return { allocation_id: 'alc-1', customer_id: 'cus-synth', customer_name: '합성 고객',
    nickname: '합성', display_tab_id: 'trip-synth', income_kind: 'deposit',
    amount_krw: 400000, ...overrides };
}

function renderForm(overrides: {
  source?: SplitSource;
  initialAllocations?: SplitAllocation[] | null;
  trips?: { id: string; title: string }[];
  csrf?: string;
  onSaved?: (result: { revision: number | null; remainder: number | null }) => void;
} = {}) {
  const src = overrides.source ?? makeSource();
  const initialAllocations = overrides.initialAllocations === undefined ? [makeAllocation()] : overrides.initialAllocations;
  return render(<SplitPlanForm source={src} initialAllocations={initialAllocations}
    trips={overrides.trips ?? [{ id: 'trip-synth', title: '합성 여행' }]}
    csrf={overrides.csrf ?? 'csrf-synth'} onSaved={overrides.onSaved} />);
}

function submitForm() {
  const form = screen.getByRole('button', { name: '배분안 저장' }).closest('form');
  if (!form) throw new Error('split form is missing');
  fireEvent.submit(form);
}

function saveButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: '배분안 저장' }) as HTMLButtonElement;
}

test('submits the full recorded plan with revision, request id and preserved fields', async () => {
  vi.mocked(postJSON).mockResolvedValue({ revision: 4, remainder: 600000 });
  const onSaved = vi.fn();
  renderForm({ source: makeSource({ source_kind: '직접 입력' }), onSaved });
  fireEvent.change(screen.getByLabelText('배분 1 금액'), { target: { value: '500,000' } });
  fireEvent.change(screen.getByLabelText('원금(선택)'), { target: { value: '1,000,000' } });
  submitForm();
  expect(vi.mocked(postJSON)).toHaveBeenCalledTimes(1);
  const call = vi.mocked(postJSON).mock.calls[0];
  expect(call[0]).toBe('/api/income/inc-synth/allocations');
  expect(call[2]).toBe('csrf-synth');
  expect(call[1]).toEqual({
    expected_source_revision: 3,
    client_request_id: expect.any(String),
    allocations: [{
      allocation_id: 'alc-1', customer_id: 'cus-synth', customer_name: '합성 고객',
      nickname: '합성', display_tab_id: 'trip-synth', income_kind: 'deposit',
      amount_krw: 500000,
    }],
    new_principal_amount: 1000000,
  });
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ revision: 4, remainder: 600000 }));
});

test('blocks submission when the initial plan is unknown or unreadable', () => {
  renderForm({ initialAllocations: null });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('배분 계획을 읽지 못해');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();

  cleanup();
  renderForm({ initialAllocations: [{ ...makeAllocation(), amount_krw: 'nope' } as unknown as SplitAllocation] });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('형식을 확인하지 못해');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
});

test('blocks submission when a recorded row has missing input instead of sending an empty plan', () => {
  renderForm({ initialAllocations: [makeAllocation()] });
  fireEvent.change(screen.getByLabelText('배분 1 금액'), { target: { value: '' } });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('기존 배분 행의 금액이 비어 있으면');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
});

test('accepts a known empty plan and omits untouched blank rows', () => {
  renderForm({ initialAllocations: [], source: makeSource({ source_kind: '은행' }) });
  expect(screen.queryByRole('alert')).toBeNull();
  submitForm();
  expect(vi.mocked(postJSON)).toHaveBeenCalledTimes(1);
  expect(vi.mocked(postJSON).mock.calls[0][1]).toMatchObject({ allocations: [] });
  expect('new_principal_amount' in (vi.mocked(postJSON).mock.calls[0][1] as object)).toBe(false);
  vi.mocked(postJSON).mockClear();
  vi.mocked(postJSON).mockResolvedValue({});
  cleanup();
  renderForm({ initialAllocations: [] });
  fireEvent.click(screen.getByRole('button', { name: '배분 행 추가' }));
  expect(saveButton().disabled).toBe(false);
  submitForm();
  expect(vi.mocked(postJSON)).toHaveBeenCalledTimes(1);
  expect(vi.mocked(postJSON).mock.calls[0][1]).toMatchObject({ allocations: [] });
});

test('refuses a sign that contradicts the source amount', () => {
  const { unmount } = renderForm({ initialAllocations: [makeAllocation()] });
  fireEvent.change(screen.getByLabelText('배분 1 금액'), { target: { value: '-5000' } });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('양수 입금은 양수 배분만');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
  unmount();

  renderForm({ source: makeSource({ amount_krw: -1000000 }),
    initialAllocations: [makeAllocation({ amount_krw: -1000 })] });
  fireEvent.change(screen.getByLabelText('배분 1 금액'), { target: { value: '5000' } });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('음수 환불은 음수 배분만');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
});

test('refuses a plan whose total exceeds the reflected amount', () => {
  renderForm({ initialAllocations: [makeAllocation({ amount_krw: 900000 })] });
  fireEvent.change(screen.getByLabelText('배분 1 금액'), { target: { value: '2000000' } });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('배분 합계가 입금액을 넘었어요');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
});

test('blocks submission when source fields cannot be read', () => {
  const { unmount } = renderForm({ source: makeSource({ amount_krw: null }) });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('원천 금액을 확인하지 못해');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
  unmount();

  renderForm({ csrf: '' });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('저장 권한을 확인하지 못해');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
});

test('blocks an unreadable plan with duplicate allocation ids', () => {
  renderForm({ initialAllocations: [makeAllocation(), makeAllocation()] });
  expect(saveButton().disabled).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain('배분 ID가 중복되어');
  submitForm();
  expect(postJSON).not.toHaveBeenCalled();
});

test('omits untouched blank rows and reports the recorded remainder', () => {
  const { container } = renderForm({ initialAllocations: [makeAllocation()] });
  expect(container.querySelector('p.cost-help-text')?.textContent).toContain('남은 금액 600,000원');
  fireEvent.click(screen.getByRole('button', { name: '배분 행 추가' }));
  submitForm();
  expect(vi.mocked(postJSON)).toHaveBeenCalledTimes(1);
  expect(vi.mocked(postJSON).mock.calls[0][1]).toMatchObject({
    allocations: [expect.objectContaining({ allocation_id: 'alc-1', amount_krw: 400000 })],
  });
});
