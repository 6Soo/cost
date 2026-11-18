import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { ActionDescriptor, Bootstrap, FieldDescriptor, LedgerRow } from '../../api/types';
import { ActionButton, Amount, Drawer, FormField, InlineNotice, Input, Select, Loading } from '../../components';
import { getJSON, postJSON, ApiError } from '../../api/client';
import { humanDate, internalHref, legacyCorrectionHref, requestId, type LedgerKind } from './urlState';
import { PeriodValue } from './index';

type RowDetail = {
  row: LedgerRow;
  source: Record<string, unknown> | null;
  classification_origin?: string | null;
  decision: Record<string, unknown> | null;
  history: unknown[];
  expected_revision: string | number | null;
  actions: ActionDescriptor[];
};

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

function fieldInitial(field: FieldDescriptor): string | boolean {
  if (field.type === 'checkbox') return field.value === true || field.value === 'true' || field.value === '1';
  return field.value === undefined || field.value === null ? '' : String(field.value);
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
  const revision = detail.expected_revision;
  const encoding = (action as ActionDescriptor & { encoding?: string }).encoding;
  const canSubmit = Boolean(actionHref?.startsWith('/api/'))
    && action.method === 'POST'
    && fields.length > 0
    && (encoding === undefined || encoding === 'json')
    && revision !== null
    && revision !== undefined
    && String(revision).trim() !== ''
    && bootstrap.role === 'owner'
    && !detail.row.read_only
    && !action.disabled;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || !actionHref || pending) return;
    const payload: Record<string, unknown> = {};
    fields.forEach((field) => {
      if (field.read_only || field.type === 'file') return;
      const value = values[field.name];
      if (value === undefined) return;
      // The projection can intentionally omit a current value (such as a private
      // note). Leaving that editor blank must not clear the stored value.
      if ((field.value === undefined || field.value === null) && value === '' && field.type !== 'checkbox') return;
      payload[field.name] = value;
    });
    // Use the dedicated API concurrency token even if a descriptor also lists it.
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
  const writeActions = actions.filter((action) => action.method === 'POST');
  const selectedAction = actions.find((action) => action.id === editingAction) ?? null;
  const title = detail?.row.merchant || detail?.row.description || '거래 상세';

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
              status={detail.row.period_status}
              basis={detail.row.period_basis}
              source={detail.row.period_source}
              manualBlank={detail.row.period_manual_blank}
            />
          </p>
          {detail.row.read_only && <InlineNotice tone="info" title="읽기 전용">이 행 또는 마감 기간은 현재 수정할 수 없습니다.</InlineNotice>}
          {bootstrap.role === 'owner' && writeActions.length > 0 && (
            <section className="cost-ledger__detail-actions" aria-label="거래 동작">
              <h3>동작</h3>
              {writeActions.map((action) => {
                const href = internalHref(action.href);
                const actionEncoding = (action as ActionDescriptor & { encoding?: string }).encoding;
                const hasRevision = detail.expected_revision !== null && detail.expected_revision !== undefined && String(detail.expected_revision).trim() !== '';
                const postCanEdit = action.method === 'POST' && action.fields?.length && (actionEncoding === undefined || actionEncoding === 'json') && href?.startsWith('/api/') && hasRevision && !action.disabled && !detail.row.read_only;
                if (action.method === 'GET' && href?.startsWith('/api/')) {
                  return <a className="cost-ledger__action-link" href={href} key={action.id}>{action.label}</a>;
                }
                return (
                  <div className="cost-ledger__action" key={action.id}>
                    <ActionButton
                      type="button"
                      variant="secondary"
                      disabled={!postCanEdit}
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
          <div className="cost-ledger__edit-heading">
            <h3>{selectedAction.label}</h3>
            {selectedAction.reason && <p>{selectedAction.reason}</p>}
          </div>
          <RowActionForm
            action={selectedAction}
            detail={detail}
            bootstrap={bootstrap}
            onCancel={() => setEditingAction(null)}
            onSaved={() => {
              setEditingAction(null);
              onSaved();
              setDetail(null);
              setDetailVersion((version) => version + 1);
            }}
          />
        </section>
      )}
    </Drawer>
  );
}
