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

function detail(overrides: Record<string, unknown> = {}) {
  return {
    row: { id: 'synthetic-row', date: '2026-11-16', merchant: '합성 행', description: '', category: '숙박비', amount: '100', currency: 'KRW', read_only: false },
    source: null, classification_origin: null, decision: null, history: [], expected_revision: 7, actions: [],
    ...overrides,
  };
}

const fullDecision = { state: 'classified', basis: 'AUTO_TRIP_INFERRED 합성 기간', category: '숙박비' };

test.each(['코드 추론', 'AI 추론'])(
  'shows "%s" as one line and drops the judgement card even when a decision payload exists',
  async (origin) => {
    vi.mocked(getJSON).mockResolvedValue(detail({ classification_origin: origin, decision: fullDecision }));
    render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(await screen.findByText(origin)).toBeTruthy();
    expect(screen.getByText('분류 출처')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: '판정' })).toBeNull();
    expect(screen.queryByText('판정 상태')).toBeNull();
    expect(screen.queryByText('판정 근거')).toBeNull();
    expect(screen.queryByText('AUTO_TRIP_INFERRED 합성 기간')).toBeNull();
  },
);

test('omits the origin line when the row has no known classification source', async () => {
  vi.mocked(getJSON).mockResolvedValue(detail({ classification_origin: '' }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  await screen.findByText('수정 이력');
  expect(screen.queryByText('분류 출처')).toBeNull();
});

/**
 * SPEC §11.2.1 계약 4: "목록 또는 행 상세에서 기존에 확인할 수 있던 이용기간,
 * 예약·증빙 근거, Google 대사 상태 ... 를 확인할 수 있다."
 *
 * The server sends the owner these fields in `detail` (`plush_projection.
 * safe_detail`: reservation_no, evidence_type, source_merchant, service_period,
 * source_event_id ...). The legacy panel prints 예약번호/원문 가맹점 (ledger_design
 * `_panel_html`). If the drawer drops the whole block, a value the owner can see
 * on the legacy screen is unreachable on the React path — the two entry paths
 * disagree (계약 1·4). Read-only rows keep them too: they are evidence, not edits.
 */
test('an owner sees the reservation number the legacy panel prints', async () => {
  vi.mocked(getJSON).mockResolvedValue(detail({
    detail: {
      row_id: 'synthetic-row', reservation_no: 'SYNTH-PNR-7',
      evidence_type: '카드', source_merchant: '합성 원문 가맹점',
      service_period: '2026-11-14~2026-11-17', source_kind: 'card',
    },
  }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(await screen.findByText('SYNTH-PNR-7')).toBeTruthy();
  expect(screen.getByText('예약번호')).toBeTruthy();
});

test('the new evidence section adds only the reservation number, nothing already on screen', async () => {
  // M4 LOW #「거래 상세 서랍의 제목·닫기가 2회」: one value, one place. The 원문
  // section already shows evidence_type/source_merchant/source_kind/event_id,
  // and the 이용 기간 row shows the period — so the added block must carry
  // 예약번호 and nothing else. Scoped to the section so this does not assert
  // anything about pre-existing behaviour inside 원문.
  vi.mocked(getJSON).mockResolvedValue(detail({
    source: { kind: '카드', event_id: 'TX-9', merchant: '합성 원문 가맹점', evidence_type: '카드', has_source: true },
    detail: { reservation_no: 'SYNTH-PNR-9', evidence_type: '카드', source_merchant: '합성 원문 가맹점' },
  }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  const section = await screen.findByRole('region', { name: '예약·증빙 근거' });
  expect(section.textContent).toContain('SYNTH-PNR-9');
  expect(section.textContent).not.toContain('합성 원문 가맹점');
  expect(screen.getAllByText('예약번호')).toHaveLength(1);
});

test('a read-only owner row still shows the reservation number, it is not an edit', async () => {
  vi.mocked(getJSON).mockResolvedValue(detail({
    row: { id: 'synthetic-row', date: '2026-11-16', merchant: '합성 행', description: '', category: '숙박비', amount: '100', currency: 'KRW', read_only: true },
    detail: { reservation_no: 'SYNTH-PNR-8', evidence_type: '영수증' },
  }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(await screen.findByText('SYNTH-PNR-8')).toBeTruthy();
});

test('a viewer sees no evidence section when the server sends an empty detail', async () => {
  vi.mocked(getJSON).mockResolvedValue(detail({ detail: {} }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'viewer', csrf: '', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  await screen.findByText('수정 이력');
  expect(screen.queryByRole('heading', { name: '예약·증빙 근거' })).toBeNull();
});

/**
 * Defense in depth (SPEC §13#10). The server already refuses to send `detail`
 * to a viewer, so the test above only proves the happy path. This one hands a
 * viewer a response that *does* carry the stored reservation number — a
 * regression in the projection, an over-eager cache, or a proxy could produce
 * that — and requires the screen to still withhold it. Without the client-side
 * owner gate this test fails; with it the value never reaches the DOM.
 */
test('a viewer is not shown the reservation number even if a response carries it', async () => {
  vi.mocked(getJSON).mockResolvedValue(detail({
    detail: { reservation_no: 'SYNTH-PNR-LEAK', evidence_type: '카드', source_merchant: '합성 원문 가맹점' },
  }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'viewer', csrf: '', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  await screen.findByText('수정 이력');
  expect(screen.queryByRole('heading', { name: '예약·증빙 근거' })).toBeNull();
  expect(screen.queryByText('SYNTH-PNR-LEAK')).toBeNull();
  const dialog = screen.getByRole('dialog');
  expect(dialog.textContent ?? '').not.toContain('SYNTH-PNR-LEAK');
});

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

/**
 * The server already advertises the row-lineage GET on the row detail, but
 * the drawer filtered the action list to POST only, so the advertised read
 * action could never be reached from this screen. The link uses the existing
 * same-origin `internalHref` plus the API target restriction; no new page or
 * API is introduced.
 */
test('an owner reaches an advertised row-lineage GET as a link, not hidden behind the POST filter', async () => {
  vi.mocked(getJSON).mockResolvedValue(detail({
    expected_revision: 7,
    actions: [
      { id: 'row-save', label: '수정', href: '/api/rows/synthetic-row/save', method: 'POST', fields: [] },
      { id: 'row-lineage', label: '거래 이력', href: '/api/rows/synthetic-row/lineage', method: 'GET' },
    ],
  }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  const link = await screen.findByRole('link', { name: '거래 이력' });
  expect(link.getAttribute('href')).toBe('/api/rows/synthetic-row/lineage');
  expect(screen.queryByRole('button', { name: '거래 이력' })).toBeNull();
});

test('a read-only action outside the advertised API target is not linked', async () => {
  vi.mocked(getJSON).mockResolvedValue(detail({
    actions: [
      { id: 'foreign-lineage', label: '외부 이력', href: '/not-an-api/lineage', method: 'GET' },
    ],
  }));
  render(<RowDrawer rowId='synthetic-row' bootstrap={{ role: 'owner', csrf: 'synthetic-csrf', trips: [], capabilities: [], receipt_enabled: false }} onClose={vi.fn()} onSaved={vi.fn()} />);
  await screen.findByText('수정 이력');
  expect(screen.queryByRole('link', { name: '외부 이력' })).toBeNull();
  expect(screen.queryByRole('button', { name: '외부 이력' })).toBeNull();
});
