// Split-plan editing for one income source row, rendered inside Plush.
//
// The write target is the existing legacy authority
// `POST /api/income/{sourceId}/allocations`; this component owns only the
// form and the client-side guards. The full desired allocation array is sent,
// never a delta, together with the source revision and a request id, so a
// changed plan is a stated value instead of an omitted field.
//
// The source/initial-plan DTO is still being settled server-side by another
// worker, and the shared API types are owned by another open change, so the
// data this form needs is read structurally here and the caller maps the
// server projection into it. Anything that cannot be read is a blocked submit,
// never an invented value.
import { useRef, useState, type FormEvent } from 'react';
import { ActionButton, FormField, InlineNotice, Input, Select } from '../../components';
import { ApiError, postJSON } from '../../api/client';
import { requestId } from './urlState';

export type SplitIncomeKind = 'deposit' | 'balance' | 'additional';

/** One allocation in the income split plan, read structurally from the server projection. */
export type SplitAllocation = {
  allocation_id: string;
  customer_id: string | null;
  customer_name: string;
  nickname: string;
  display_tab_id: string | null;
  income_kind: string;
  amount_krw: number;
};

/** The income source a plan belongs to. */
export type SplitSource = {
  row_id: string;
  revision: number;
  amount_krw: number | null;
  /** '직접 입력' sources also accept the optional principal amount. */
  source_kind?: string | null;
};

export type SplitTripOption = { id: string; title: string };

export type SplitSaveSummary = { revision: number | null; remainder: number | null };

export type SplitPlanFormProps = {
  source: SplitSource;
  /** The recorded/current plan, or null when it could not be read. */
  initialAllocations: SplitAllocation[] | null;
  trips: SplitTripOption[];
  csrf: string;
  onSaved?: (result: SplitSaveSummary) => void;
};

type DraftRow = {
  key: string;
  allocation_id: string;
  customer_id: string | null;
  customer_name: string;
  nickname: string;
  display_tab_id: string;
  income_kind: string;
  amount: string;
  existed: boolean;
};

type AmountParse = { kind: 'ok'; amount: number } | { kind: 'omit' } | { kind: 'error'; reason: string };

const SPLIT_INCOME_KINDS = ['deposit', 'balance', 'additional'];
const DIRECT_INPUT_KIND = '직접 입력';
const WON = new Intl.NumberFormat('ko-KR');

function splitLabel(index: number): string {
  return `배분 ${index + 1}`;
}

function parseAmount(raw: string): AmountParse {
  const cleaned = raw.trim().replace(/[,\s]/g, '');
  if (cleaned === '') return { kind: 'omit' };
  if (!/^[+-]?\d+$/.test(cleaned)) return { kind: 'error', reason: '배분액은 정수 원화로 입력해 주세요' };
  const amount = Number(cleaned);
  if (!Number.isSafeInteger(amount)) return { kind: 'error', reason: '배분액이 너무 커요' };
  if (amount === 0) return { kind: 'error', reason: '배분액은 0이 아니어야 해요' };
  return { kind: 'ok', amount };
}

function readAllocation(value: unknown): SplitAllocation | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (typeof row.allocation_id !== 'string') return null;
  if (typeof row.amount_krw !== 'number' || !Number.isFinite(row.amount_krw)) return null;
  if (typeof row.income_kind !== 'string' || !SPLIT_INCOME_KINDS.includes(row.income_kind)) return null;
  const customer_name = typeof row.customer_name === 'string' ? row.customer_name : '';
  const nickname = typeof row.nickname === 'string' ? row.nickname : '';
  if (row.display_tab_id !== undefined && row.display_tab_id !== null && typeof row.display_tab_id !== 'string') {
    return null;
  }
  if (row.customer_id !== undefined && row.customer_id !== null && typeof row.customer_id !== 'string') {
    return null;
  }
  return {
    allocation_id: row.allocation_id,
    customer_id: row.customer_id ?? null,
    customer_name,
    nickname,
    display_tab_id: row.display_tab_id ?? null,
    income_kind: row.income_kind,
    amount_krw: row.amount_krw,
  };
}

function hasContent(row: DraftRow): boolean {
  return row.customer_name.trim() !== '' || row.display_tab_id.trim() !== '' || row.nickname.trim() !== '';
}

function formatWon(value: number): string {
  return `${WON.format(value)}원`;
}

export function SplitPlanForm({ source, initialAllocations, trips, csrf, onSaved }: SplitPlanFormProps) {
  const [clientRequestId] = useState(requestId);
  const newRowRef = useRef(0);
  const sourceKind = typeof source?.source_kind === 'string' ? source.source_kind : null;
  const directInput = sourceKind === DIRECT_INPUT_KIND;
  const reflected = typeof source?.amount_krw === 'number' && Number.isFinite(source.amount_krw)
    ? source.amount_krw : null;
  const readiness = readSourceReadiness(source, reflected, csrf);
  const plan = readInitialPlan(initialAllocations);
  const planBlocked = plan.status === 'blocked' ? plan.reason : null;
  const blockedReason = planBlocked ?? readiness;
  const [rows, setRows] = useState<DraftRow[]>(() => (plan.status === 'ready' ? plan.drafts : []));
  const [principal, setPrincipal] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const issues = collectIssues(rows, reflected, principal, directInput);
  const remaining = blockedReason === null && issues.length === 0 && reflected !== null
    ? reflected - rows.reduce<number>((sum, row) => sum + includedAmount(row), 0)
    : null;

  function updateRow(index: number, patch: Partial<Pick<DraftRow, 'amount' | 'customer_name' | 'display_tab_id' | 'income_kind'>>) {
    setRows(current => current.map((row, at) => at === index ? { ...row, ...patch } : row));
  }

  function addRow() {
    newRowRef.current += 1;
    setRows(current => [...current, {
      key: `new-${newRowRef.current}`,
      allocation_id: '',
      customer_id: null,
      customer_name: '',
      nickname: '',
      display_tab_id: '',
      income_kind: 'deposit',
      amount: '',
      existed: false,
    }]);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (pending) return;
    if (blockedReason !== null) { setError(`${blockedReason}. 제출할 수 없어요`); return; }
    const rowIssues = collectIssues(rows, reflected, principal, directInput);
    if (rowIssues.length > 0) { setError(`${rowIssues[0]}. 다른 입력값도 확인해 주세요`); return; }
    const plan: SplitAllocation[] = rows
      .filter(row => parseAmount(row.amount).kind === 'ok')
      .map(row => ({
      allocation_id: row.allocation_id,
      customer_id: row.customer_id,
      customer_name: row.customer_name,
      nickname: row.nickname,
      display_tab_id: row.display_tab_id.trim() === '' ? null : row.display_tab_id,
      income_kind: row.income_kind,
      amount_krw: includedAmount(row),
    }));
    const body: Record<string, unknown> = {
      expected_source_revision: source.revision,
      client_request_id: clientRequestId,
      allocations: plan,
    };
    const principalValue = principal.trim().replace(/[,\s]/g, '');
    if (directInput && /^[+-]?\d+$/.test(principalValue) && principalValue !== '') {
      body.new_principal_amount = Number(principalValue);
    }
    setPending(true);
    try {
      const saved = await postJSON<{ revision?: unknown; remainder?: unknown }>(
        `/api/income/${encodeURIComponent(source.row_id)}/allocations`, body, csrf);
      onSaved?.({
        revision: typeof saved?.revision === 'number' && Number.isFinite(saved.revision)
          ? saved.revision : null,
        remainder: typeof saved?.remainder === 'number' && Number.isFinite(saved.remainder)
          ? saved.remainder : null,
      });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message
        : reason instanceof Error ? reason.message : '저장하지 못했습니다. 입력값을 확인해 주세요');
    } finally {
      setPending(false);
    }
  }

  const saveBlocked = blockedReason !== null || issues.length > 0 || pending;

  return (
    <form className="cost-ledger__split-form" onSubmit={(event) => { void submit(event); }} noValidate>
      <h3>입금 배분</h3>
      <p className="cost-help-text">
        {reflected === null ? '원천 금액 미확인' : `원천 입금액 ${formatWon(reflected)}`}
        {remaining === null ? '' : ` · 남은 금액 ${formatWon(remaining)}`}
      </p>
      {blockedReason !== null && <InlineNotice tone="error" title="배분안을 저장할 수 없어요">{blockedReason}</InlineNotice>}
      {blockedReason === null && issues.length > 0
        && <InlineNotice tone="error" title="입력을 확인해 주세요">{issues.join(' ')}</InlineNotice>}
      {blockedReason === null && issues.length === 0 && error !== null
        && <InlineNotice tone="error" title="저장하지 못했어요">{error}</InlineNotice>}

      <div className="cost-ledger__split-rows">
        {rows.map((row, index) => (
          <div className="cost-ledger__split-row" key={row.key}>
            <Input aria-label={`${splitLabel(index)} 배분 ID`} readOnly tabIndex={-1}
              value={row.allocation_id || '새 배분'} />
            <FormField id={`split-alloc-${index}-customer`} label="고객">
              <Input aria-label={`${splitLabel(index)} 고객`} value={row.customer_name}
                autoComplete="off" onChange={(event) => updateRow(index, { customer_name: event.target.value })} />
            </FormField>
            <FormField id={`split-alloc-${index}-trip`} label="여행">
              <Select aria-label={`${splitLabel(index)} 여행`} value={row.display_tab_id}
                onChange={(event) => updateRow(index, { display_tab_id: event.target.value })}>
                <option value="">미배정</option>
                {trips.map(trip => <option key={trip.id} value={trip.id}>{trip.title}</option>)}
              </Select>
            </FormField>
            <FormField id={`split-alloc-${index}-kind`} label="종류">
              <Select aria-label={`${splitLabel(index)} 입금 종류`} value={row.income_kind}
                onChange={(event) => updateRow(index, { income_kind: event.target.value })}>
                <option value="deposit">예약금</option>
                <option value="balance">잔금</option>
                <option value="additional">추가금</option>
              </Select>
            </FormField>
            <FormField id={`split-alloc-${index}-amount`} label="금액 (원)">
              <Input aria-label={`${splitLabel(index)} 금액`} value={row.amount} placeholder="정수 원화"
                autoComplete="off" onChange={(event) => updateRow(index, { amount: event.target.value })} />
            </FormField>
          </div>
        ))}
      </div>
      <div className="cost-ledger__split-actions">
        <ActionButton type="button" variant="secondary" size="sm" onClick={addRow} disabled={pending}>
          배분 행 추가
        </ActionButton>
        {directInput && (
          <FormField id="split-principal" label="원금(선택, 배분안과 함께 저장)">
            <Input aria-label="원금(선택)" value={principal} placeholder="정수 원화"
              autoComplete="off" onChange={(event) => setPrincipal(event.target.value)} />
          </FormField>
        )}
        <ActionButton type="submit" variant="primary" pending={pending} pendingLabel="저장 중"
          disabled={saveBlocked}>배분안 저장</ActionButton>
      </div>
    </form>
  );
}

type InitialPlan = { status: 'ready'; drafts: DraftRow[] } | { status: 'blocked'; reason: string };

function readInitialPlan(initialAllocations: SplitAllocation[] | null): InitialPlan {
  if (initialAllocations === null) {
    return { status: 'blocked', reason: '배분 계획을 읽지 못해 제출할 수 없어요' };
  }
  if (!Array.isArray(initialAllocations)) {
    return { status: 'blocked', reason: '배분 계획 형식을 확인하지 못해 제출할 수 없어요' };
  }
  const drafts: DraftRow[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < initialAllocations.length; index += 1) {
    const allocation = readAllocation(initialAllocations[index]);
    if (allocation === null) {
      return { status: 'blocked', reason: '배분 계획 형식을 확인하지 못해 제출할 수 없어요' };
    }
    if (allocation.allocation_id !== '') {
      if (seen.has(allocation.allocation_id)) {
        return { status: 'blocked', reason: '배분 계획의 배분 ID가 중복되어 제출할 수 없어요' };
      }
      seen.add(allocation.allocation_id);
    }
    drafts.push({
      key: allocation.allocation_id === '' ? `seeded-${index}` : `alloc-${allocation.allocation_id}`,
      allocation_id: allocation.allocation_id,
      customer_id: allocation.customer_id,
      customer_name: allocation.customer_name,
      nickname: allocation.nickname,
      display_tab_id: allocation.display_tab_id ?? '',
      income_kind: allocation.income_kind,
      amount: String(allocation.amount_krw),
      existed: true,
    });
  }
  return { status: 'ready', drafts };
}

function readSourceReadiness(source: SplitSource | null | undefined, reflected: number | null, csrf: string): string | null {
  if (source === null || source === undefined || typeof source !== 'object') {
    return '원천 입금 정보를 읽지 못해 제출할 수 없어요';
  }
  if (typeof source.row_id !== 'string' || source.row_id.trim() === '') {
    return '원천 입금 ID를 확인하지 못해 제출할 수 없어요';
  }
  if (!Number.isSafeInteger(source.revision)) {
    return '원천 revision을 확인하지 못해 제출할 수 없어요';
  }
  if (reflected === null) return '원천 금액을 확인하지 못해 제출할 수 없어요';
  if (typeof csrf !== 'string' || csrf.trim() === '') return '저장 권한을 확인하지 못해 제출할 수 없어요';
  return null;
}

function includedAmount(row: DraftRow): number {
  const parsed = parseAmount(row.amount);
  return parsed.kind === 'ok' ? parsed.amount : 0;
}

function collectIssues(
  rows: DraftRow[],
  reflected: number | null,
  principalRaw: string,
  directInput: boolean,
): string[] {
  const issues: string[] = [];
  let sum = 0;
  let parseable = true;
  rows.forEach((row, index) => {
    const label = splitLabel(index);
    const parsed = parseAmount(row.amount);
    if (parsed.kind === 'error') { issues.push(`${label}: ${parsed.reason}`); parseable = false; return; }
    if (parsed.kind === 'omit') {
      if (row.existed) issues.push(`${label}: 기존 배분 행의 금액이 비어 있으면 제출할 수 없어요`);
      else if (hasContent(row)) issues.push(`${label}: 금액을 입력해 주세요`);
      return;
    }
    sum += parsed.amount;
    if (reflected !== null && reflected > 0 && parsed.amount < 0) {
      issues.push(`${label}: 양수 입금은 양수 배분만 할 수 있어요`);
    }
    if (reflected !== null && reflected < 0 && parsed.amount > 0) {
      issues.push(`${label}: 음수 환불은 음수 배분만 할 수 있어요`);
    }
    if (row.customer_name.trim() === '') issues.push(`${label}: 배분 고객 이름이 필요해요`);
    if (!SPLIT_INCOME_KINDS.includes(row.income_kind)) issues.push(`${label}: 입금 종류를 골라 주세요`);
  });
  if (reflected !== null && parseable) {
    if (reflected === 0 && sum !== 0) issues.push('나눌 금액이 없어요');
    else if (reflected !== 0 && Math.abs(sum) > Math.abs(reflected)) issues.push('배분 합계가 입금액을 넘었어요');
  }
  const principal = principalRaw.trim().replace(/[,\s]/g, '');
  if (directInput && principal !== '' && !/^[+-]?\d+$/.test(principal)) {
    issues.push('원금은 정수 원화로 입력해 주세요');
  }
  return issues;
}
