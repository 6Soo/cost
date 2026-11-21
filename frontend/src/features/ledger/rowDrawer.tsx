import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { ActionDescriptor, Bootstrap, FieldDescriptor, LedgerRow } from '../../api/types';
import { ActionButton, Amount, Drawer, FormField, InlineNotice, Input, Select, Loading } from '../../components';
import { getJSON, postJSON, ApiError } from '../../api/client';
import { humanDate, internalHref, legacyCorrectionHref, requestId, type LedgerKind } from './urlState';
import { PeriodValue } from './index';
import { SplitPlanForm, type SplitAllocation } from './splitPlanForm';

/**
 * SPEC §11.2.1 계약 4: the owner's row detail carries the same stored
 * reservation·evidence values the legacy panel prints. The server sends them
 * in `detail` (`plush_projection.safe_detail`); the drawer only prints what it
 * was given — it never derives a period or an amount from these fields.
 * `api/types.ts` is owned by another open change, so the shape is read
 * structurally here rather than added to the shared DTO.
 */
type RowEvidence = Record<string, unknown>;

type RowDetail = {
  row: LedgerRow;
  source: Record<string, unknown> | null;
  classification_origin?: string | null;
  decision: Record<string, unknown> | null;
  history: unknown[];
  expected_revision: string | number | null;
  actions: ActionDescriptor[];
  detail?: RowEvidence | null;
  corrections?: {
    corrected_amount_krw: string | number;
    corrected_occurred_on?: string | null;
    reason: string;
    created_at: string;
  }[];
  linked_bank_sources?: { bank_batch_id: string; bank_row_index: number }[];
  bank_candidates?: { occurred_on: string; customer_name: string; amount_krw: string | number; row_id: string }[];
  bank_source_locked?: boolean;
  split?: {
    source_row_id: string;
    expected_source_revision: number;
    reflected_amount_krw: number | null;
    source_kind?: string | null;
    plan: SplitAllocation[];
  } | null;
};

/** The stored values the drawer was missing. Only `reservation_no` is listed:
 *  the other `safe_detail` keys already reach the reader elsewhere on this
 *  screen — `source_merchant`/`source_kind`/`source_event_id`/`evidence_type`
 *  in the 원문 section and the period in the 이용 기간 row — and printing them
 *  twice is the duplicate-display defect M4 LOW #「거래 상세 서랍의 제목·닫기가
 *  2회」 warns about. A blank value is omitted, so a missing reservation number
 *  never prints an empty row (계약 4: 미확인 ≠ 0). */
const EVIDENCE_FIELDS: Array<[key: string, label: string]> = [
  ['reservation_no', '예약번호'],
];

function evidenceEntries(evidence: RowEvidence | null | undefined): Array<[string, string]> {
  if (!evidence) return [];
  return EVIDENCE_FIELDS
    .map(([key, label]) => {
      const raw = evidence[key];
      const text = raw === null || raw === undefined ? '' : String(raw).trim();
      return [label, text] as [string, string];
    })
    .filter(([, text]) => text !== '');
}

type RowDrawerProps = {
  rowId: string | null;
  bootstrap: Bootstrap;
  tab?: string;
  kind?: LedgerKind;
  search?: URLSearchParams;
  onClose: () => void;
  onSaved: () => void;
};

const LABELS: Record<string, string> = {
  id: '행 ID', row_id: '행 ID', date: '날짜', occurred_on: '거래일', merchant: '가맹점',
  source_merchant: '원문 가맹점', description: '내용', original_description: '원문 내용',
  category: '항목', item: '항목', amount: '금액', amount_krw: '원화 금액', currency: '통화',
  payment: '결제 수단', pay_method: '지급 수단', period: '이용 기간', evidence_summary: '근거 요약',
  evidence: '근거', kind: '종류', event_id: '원본 사건 ID', source_event_id: '원본 사건 ID',
  classification_state: '판정 상태', classification_basis: '판정 근거', rationale: '판정 설명',
  display_tab_id: '여행 ID', actor: '수정 주체', created_at: '기록 시각', revision: 'revision',
  change_mode: '변경 방식', field: '수정 항목', before: '변경 전', after: '변경 후',
  reason: '사유', user_edits: '수동 수정', proposal: '자동 판정', status: '상태',
};

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '없음';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  try { return JSON.stringify(value); } catch { return '표시할 수 없는 값'; }
}

function DataFields({ title, values }: { title: string; values: Record<string, unknown> | null | undefined }) {
  const entries = Object.entries(values ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (!entries.length) return null;
  return (
    <section className="cost-ledger__detail-section" aria-label={title}>
      <h3>{title}</h3>
      <dl className="cost-ledger__detail-list">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{LABELS[key] ?? key}</dt>
            <dd>{displayValue(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function HistoryList({ history }: { history: unknown[] }) {
  if (!history.length) return <p className="cost-ledger__muted">표시할 변경 이력이 없습니다.</p>;
  return (
    <ol className="cost-ledger__history">
      {history.map((entry, index) => {
        const object = entry && typeof entry === 'object' && !Array.isArray(entry)
          ? entry as Record<string, unknown>
          : { value: entry };
        const title = String(object.kind ?? object.action ?? object.event ?? '기록');
        const time = object.created_at ?? object.timestamp;
        return (
          <li key={`${String(object.event_id ?? object.revision ?? index)}-${index}`}>
            <strong>{title}</strong>
            {time !== undefined && <time>{displayValue(time)}</time>}
            <DataFields title="변경 내용" values={object} />
          </li>
        );
      })}
    </ol>
  );
}

const BANK_SOURCE_LOCK_NOTE = '은행 원천에 연결한 날짜와 금액은 은행 정정에서 바꿀 수 있습니다.';

function BankIncomeDetails({ detail }: { detail: RowDetail }) {
  const corrections = detail.corrections ?? [];
  const sources = detail.linked_bank_sources ?? [];
  const candidates = detail.bank_candidates ?? [];
  return (
    <>
      {corrections.length > 0 && (
        <section className="cost-ledger__detail-section" aria-label="은행 정정 이력">
          <h3>은행 정정 이력</h3>
          <ol className="cost-ledger__history">
            {corrections.map((entry, index) => (
              <li key={`${entry.created_at}-${index}`}>
                <Amount value={String(entry.corrected_amount_krw)} />
                {entry.corrected_occurred_on && <span>장부 표시 날짜 {humanDate(entry.corrected_occurred_on)}</span>}
                <span>{entry.reason}</span>
                <time dateTime={entry.created_at}>{entry.created_at}</time>
              </li>
            ))}
          </ol>
        </section>
      )}
      {sources.length > 0 && (
        <section className="cost-ledger__detail-section" aria-label="연결된 은행 원천">
          <h3>연결된 은행 원천</h3>
          <ul className="cost-ledger__history">
            {sources.map((source) => (
              <li key={`${source.bank_batch_id}-${source.bank_row_index}`}>
                {source.bank_batch_id} #{source.bank_row_index}
              </li>
            ))}
          </ul>
          {detail.bank_source_locked && <p className="cost-ledger__muted">{BANK_SOURCE_LOCK_NOTE}</p>}
        </section>
      )}
      {candidates.length > 0 && (
        <section className="cost-ledger__detail-section" aria-label="은행 중복 후보">
          <h3>은행 중복 후보</h3>
          <p className="cost-ledger__muted">후보 표시 자체는 장부 합계에 영향을 주지 않습니다.</p>
          <ul className="cost-ledger__history">
            {candidates.map((candidate) => (
              <li key={candidate.row_id}>
                <span>{humanDate(candidate.occurred_on)} · {candidate.customer_name}</span>
                <Amount value={String(candidate.amount_krw)} />
                <span>{candidate.row_id}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function fieldInitial(field: FieldDescriptor): string | boolean {
  if (field.type === 'checkbox') return field.value === true || field.value === 'true' || field.value === '1';
  return field.value === undefined || field.value === null ? '' : String(field.value);
}

function actionRevision(action: ActionDescriptor, detail: RowDetail): number | null {
  const field = action.fields?.find(({ name }) => name === 'expected_revision');
  if (field && field.type !== 'hidden') return null;
  const value = field ? field.value : detail.expected_revision;
  const revision = typeof value === 'string' && /^[0-9]+$/.test(value.trim())
    ? Number(value.trim())
    : value;
  return typeof revision === 'number' && Number.isSafeInteger(revision) && revision >= 0
    ? revision
    : null;
}

function RowActionForm({
  action,
  detail,
  bootstrap,
  onSaved,
  onCancel,
}: {
  action: ActionDescriptor;
  detail: RowDetail;
  bootstrap: Bootstrap;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const fields = action.fields ?? [];
  const initial = useMemo(() => Object.fromEntries(fields.map((field) => [field.name, fieldInitial(field)])), [fields]);
  const [values, setValues] = useState<Record<string, string | boolean>>(initial);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clientRequestId, setClientRequestId] = useState(requestId);
  const actionHref = internalHref(action.href);
  const revision = actionRevision(action, detail);
  const encoding = (action as ActionDescriptor & { encoding?: string }).encoding;
  const canSubmit = Boolean(actionHref?.startsWith('/api/'))
    && action.method === 'POST'
    && fields.length > 0
    && (encoding === undefined || encoding === 'json')
    && revision !== null
    && bootstrap.role === 'owner'
    && !detail.row.read_only
    && !action.disabled;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || !actionHref || pending) return;
    const payload: Record<string, unknown> = {};
    fields.forEach((field) => {
      if (field.name === 'expected_revision' || field.read_only || field.type === 'file') return;
      const value = values[field.name];
      if (value === undefined) return;
      // The projection can intentionally omit a current value (such as a private
      // note). Leaving that editor blank must not clear the stored value.
      if ((field.value === undefined || field.value === null) && value === '' && field.type !== 'checkbox') return;
      payload[field.name] = value;
    });
    // An explicit action revision may refer to the source row of an allocation.
    payload.expected_revision = revision;
    if (typeof payload.client_request_id !== 'string' || !payload.client_request_id.trim()) {
      payload.client_request_id = clientRequestId;
    }
    setPending(true);
    setError(null);
    try {
      await postJSON(actionHref, payload, bootstrap.csrf);
      setClientRequestId(requestId());
      onSaved();
    } catch (reason: unknown) {
      setError(reason instanceof ApiError ? reason.message : '수정 사항을 저장하지 못했습니다. 입력값을 유지하고 다시 확인해 주세요.');
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="cost-ledger__edit-form" onSubmit={submit}>
      {action.id === 'row-save' && detail.bank_source_locked && (
        <p className="cost-ledger__muted">{BANK_SOURCE_LOCK_NOTE}</p>
      )}
      {error && <InlineNotice tone="error" title="저장하지 못했습니다">{error}</InlineNotice>}
      {!canSubmit && <InlineNotice tone="warning" title="이 수정 동작을 사용할 수 없습니다">서버에서 제공한 저장 경로, 수정 필드와 revision을 확인하지 못했습니다.</InlineNotice>}
      {fields.map((field) => {
        const id = `row-edit-${action.id}-${field.name}`;
        const value = values[field.name];
        if (field.type === 'hidden') return <input key={field.name} type="hidden" name={field.name} value={typeof value === 'boolean' ? String(value) : value ?? ''} />;
        if (field.type === 'file') return null;
        if (field.type === 'checkbox') {
          return (
            <label className="cost-ledger__checkbox" key={field.name}>
              <input
                id={id}
                type="checkbox"
                checked={Boolean(value)}
                disabled={field.read_only || pending}
                onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.currentTarget.checked }))}
              />
              <span>{field.label}</span>
            </label>
          );
        }
        return (
          <FormField id={id} label={field.label} required={field.required} key={field.name}>
            {field.type === 'select' ? (
              <Select
                id={id}
                value={typeof value === 'string' ? value : ''}
                required={field.required}
                disabled={field.read_only || pending}
                onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.currentTarget.value }))}
              >
                {(field.options ?? []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </Select>
            ) : (
              <Input
                id={id}
                type={field.type === 'number' || field.type === 'date' ? field.type : 'text'}
                value={typeof value === 'string' ? value : ''}
                required={field.required}
                disabled={field.read_only || pending}
                onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.currentTarget.value }))}
              />
            )}
          </FormField>
          );
        })}
      <div className="cost-ledger__entry-actions">
        <ActionButton type="button" variant="secondary" onClick={onCancel} disabled={pending}>취소</ActionButton>
        <ActionButton type="submit" variant="primary" pending={pending} pendingLabel="저장 중" disabled={!canSubmit}>저장</ActionButton>
      </div>
    </form>
  );
}

function OriginLabel({ origin }: { origin: string }) {
  if (!origin) return null;
  return (
    <p className="cost-ledger__origin">
      <span className="cost-ledger__origin-key">분류 출처</span>
      <span className="cost-ledger__origin-chip">{origin}</span>
    </p>
  );
}

export function RowDrawer({ rowId, bootstrap, tab, kind, search, onClose, onSaved }: RowDrawerProps) {
  const [detail, setDetail] = useState<RowDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [editingAction, setEditingAction] = useState<string | null>(null);
  const [detailVersion, setDetailVersion] = useState(0);

  useEffect(() => {
    if (!rowId) {
      setDetail(null);
      setError(null);
      setEditingAction(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getJSON<RowDetail>(`/api/plush/row?id=${encodeURIComponent(rowId)}`, controller.signal)
      .then(setDetail)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof ApiError ? reason.message : '거래 상세를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [detailVersion, rowId]);

  const actions = detail?.actions ?? [];
  const selectedAction = actions.find((action) => action.id === editingAction) ?? null;
  const activeSplit = selectedAction?.encoding === 'allocation-plan' ? detail?.split : null;

  function refreshAfterSave() {
    setEditingAction(null);
    onSaved();
    setDetail(null);
    setDetailVersion((version) => version + 1);
  }

  const title = detail?.row.merchant || detail?.row.description || '거래 상세';
  /* Two independent gates, on purpose (defense in depth — SPEC §13#10):
     1. the server sends `detail` only to the owner, so a viewer's response has
        nothing to print;
     2. this screen also refuses to print it unless the session is the owner.
     Either gate alone would be enough today; if a future projection change,
     a cache, or a proxy ever handed a viewer a populated `detail`, the client
     gate still keeps the stored reservation number off a viewer's screen. */
  const evidence = bootstrap.role === 'owner' ? evidenceEntries(detail?.detail) : [];

  return (
    <Drawer open={Boolean(rowId)} title={title} description={detail ? `${humanDate(detail.row.date)} · ${detail.row.category}` : undefined} onOpenChange={(open) => { if (!open) onClose(); }}>
      {loading && !detail && <Loading label="거래 상세 불러오는 중" />}
      {error && <InlineNotice tone="error" title="거래 상세를 불러오지 못했습니다">{error}</InlineNotice>}
      {detail && !selectedAction && (
        <div className="cost-ledger__drawer-content">
          <div className="cost-ledger__detail-amount"><Amount value={detail.row.amount} currency={detail.row.currency} /></div>
          <p className="cost-ledger__detail-description">{detail.row.description || detail.row.merchant}</p>
          <p className="cost-ledger__detail-period">
            <span className="cost-ledger__detail-period-key">이용 기간</span>
            <PeriodValue
              period={detail.row.period}
              label={detail.row.period_label}
              status={detail.row.period_status}
              basis={detail.row.period_basis}
              source={detail.row.period_source}
              manualBlank={detail.row.period_manual_blank}
            />
          </p>
          {detail.row.read_only && <InlineNotice tone="info" title="읽기 전용">이 행 또는 마감 기간은 현재 수정할 수 없습니다.</InlineNotice>}
          {evidence.length > 0 && (
            <section className="cost-ledger__detail-section" aria-label="예약·증빙 근거">
              <h3>예약·증빙 근거</h3>
              <dl className="cost-ledger__detail-list">
                {evidence.map(([label, text]) => (
                  <div key={label}><dt>{label}</dt><dd>{text}</dd></div>
                ))}
              </dl>
            </section>
          )}
          {bootstrap.role === 'owner' && <BankIncomeDetails detail={detail} />}
          {bootstrap.role === 'owner' && actions.length > 0 && (
            <section className="cost-ledger__detail-actions" aria-label="거래 동작">
              <h3>동작</h3>
              {actions.map((action) => {
                const href = internalHref(action.href);
                // A read-only action (for example the advertised row lineage)
                // is a link to navigate to, never an edit form. Like the
                // previous GET branch this stays inside internalHref's
                // same-origin check and the API target restriction.
                if (action.method === 'GET') {
                  return href?.startsWith('/api/')
                    ? <a className="cost-ledger__action-link" href={href} key={action.id}>{action.label}</a>
                    : null;
                }
                if (action.method !== 'POST') return null;
                const hasRevision = actionRevision(action, detail) !== null;
                const split = detail.split;
                const hasForm = action.encoding === 'allocation-plan'
                  ? Boolean(split && href === `/api/income/${encodeURIComponent(split.source_row_id)}/allocations`)
                  : Boolean(action.fields?.length) && (action.encoding === undefined || action.encoding === 'json') && Boolean(href?.startsWith('/api/'));
                const canEdit = hasForm && hasRevision && !action.disabled && !detail.row.read_only;
                return (
                  <div className="cost-ledger__action" key={action.id}>
                    <ActionButton
                      type="button"
                      variant="secondary"
                      disabled={!canEdit}
                      title={action.disabled ? action.reason : undefined}
                      onClick={() => setEditingAction(action.id)}
                    >
                      {action.label}
                    </ActionButton>
                    {action.disabled && action.reason && <span>{action.reason}</span>}
                  </div>
                );
              })}
            </section>
          )}
          {bootstrap.role === 'owner' && !detail.row.read_only && tab && search && (
            <section className="cost-ledger__detail-actions" aria-label="기존 교정 화면">
              <a className="cost-ledger__action-link" href={legacyCorrectionHref(detail.row.id, tab, kind ?? 'expense', search)}>기존 화면에서 교정</a>
            </section>
          )}
          {selectedAction === null && <DataFields title="원문" values={detail.source} />}
          {selectedAction === null && <OriginLabel origin={detail.classification_origin ?? ''} />}
          {selectedAction === null && <section className="cost-ledger__detail-section"><h3>수정 이력</h3><HistoryList history={detail.history ?? []} /></section>}
        </div>
      )}
      {detail && selectedAction && (
        <section className="cost-ledger__drawer-content">
          {!activeSplit && (
            <div className="cost-ledger__edit-heading">
              <h3>{selectedAction.label}</h3>
              {selectedAction.reason && <p>{selectedAction.reason}</p>}
            </div>
          )}
          {activeSplit ? (
            <>
              <SplitPlanForm
                source={{
                  row_id: activeSplit.source_row_id,
                  revision: activeSplit.expected_source_revision,
                  amount_krw: activeSplit.reflected_amount_krw,
                  source_kind: activeSplit.source_kind,
                }}
                initialAllocations={activeSplit.plan}
                trips={bootstrap.trips}
                csrf={bootstrap.csrf}
                onSaved={refreshAfterSave}
              />
              <ActionButton type="button" variant="secondary" onClick={() => setEditingAction(null)}>
                취소
              </ActionButton>
            </>
          ) : (
            <RowActionForm
              action={selectedAction}
              detail={detail}
              bootstrap={bootstrap}
              onCancel={() => setEditingAction(null)}
              onSaved={refreshAfterSave}
            />
          )}
        </section>
      )}
    </Drawer>
  );
}
