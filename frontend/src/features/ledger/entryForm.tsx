import { useRef, useState, type FormEvent } from 'react';
import type { Bootstrap } from '../../api/types';
import { ActionButton, FormField, InlineNotice, Input, Select } from '../../components';
import { postJSON, ApiError } from '../../api/client';
import { requestId } from './urlState';

type EntryKind = 'expense' | 'income';

type EntryFormProps = {
  kind: EntryKind;
  bootstrap: Bootstrap;
  tripId: string;
  onCreated: (rowId: string) => void;
  onCancel: () => void;
};

type CreateResult = { row_id?: string; id?: string };

export function EntryForm({ kind, bootstrap, tripId, onCreated, onCancel }: EntryFormProps) {
  const requestIdRef = useRef(requestId());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || bootstrap.role !== 'owner') return;
    const form = new FormData(event.currentTarget);
    const common = {
      display_tab_id: String(form.get('display_tab_id') || '') || null,
      occurred_on: String(form.get('occurred_on') || ''),
      amount_krw: String(form.get('amount_krw') || '').replaceAll(',', '').trim(),
      client_request_id: requestIdRef.current,
    };
    const payload = kind === 'expense'
      ? {
          ...common,
          pay_method: String(form.get('pay_method') || ''),
          item: String(form.get('item') || ''),
          description: String(form.get('description') || ''),
          operator_note: String(form.get('operator_note') || ''),
        }
      : {
          ...common,
          income_kind: String(form.get('income_kind') || ''),
          customer_name: String(form.get('customer_name') || ''),
          nickname: String(form.get('nickname') || ''),
          operator_note: String(form.get('operator_note') || ''),
        };

    setPending(true);
    setError(null);
    try {
      const endpoint = kind === 'expense' ? '/api/expenses/manual' : '/api/income';
      const result = await postJSON<CreateResult>(endpoint, payload, bootstrap.csrf);
      const rowId = result.row_id || result.id;
      if (!rowId) throw new Error('저장 응답에서 장부 행 ID를 확인하지 못했습니다. 장부를 다시 조회해 주세요.');
      onCreated(rowId);
    } catch (reason: unknown) {
      setError(reason instanceof ApiError ? reason.message : reason instanceof Error ? reason.message : '저장하지 못했습니다. 입력값을 확인해 주세요.');
      // Keep the same request id after an uncertain network result so retry is idempotent.
    } finally {
      setPending(false);
    }
  }

  const selectedTrip = bootstrap.trips.find((trip) => trip.id === tripId);
  const trips = bootstrap.trips.filter((trip) => !trip.archived || trip.id === tripId);

  return (
    <form className="cost-ledger__entry-form" onSubmit={submit}>
      {error && <InlineNotice tone="error" title="저장하지 못했습니다">{error}</InlineNotice>}
      <FormField id="entry-trip" label="여행" hint={selectedTrip?.title}>
        <Select id="entry-trip" name="display_tab_id" defaultValue={tripId.startsWith('quarter:') ? '' : tripId}>
          <option value="">분기 기타비용</option>
          {trips.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}
        </Select>
      </FormField>
      <FormField id="entry-date" label="거래일자" required>
        <Input id="entry-date" type="date" name="occurred_on" required />
      </FormField>
      {kind === 'expense' ? (
        <>
          <FormField id="entry-payment" label="지급 수단">
            <Select id="entry-payment" name="pay_method" defaultValue="현금">
              <option value="현금">현금</option>
              <option value="계좌이체">계좌이체</option>
            </Select>
          </FormField>
          <FormField id="entry-category" label="항목">
            <Input id="entry-category" name="item" />
          </FormField>
          <FormField id="entry-description" label="내용">
            <Input id="entry-description" name="description" />
          </FormField>
        </>
      ) : (
        <>
          <FormField id="entry-income-kind" label="입금 종류" required>
            <Select id="entry-income-kind" name="income_kind" defaultValue="deposit">
              <option value="deposit">예약금</option>
              <option value="balance">잔금</option>
              <option value="additional">추가금</option>
            </Select>
          </FormField>
          <FormField id="entry-customer-name" label="이름">
            <Input id="entry-customer-name" name="customer_name" />
          </FormField>
          <FormField id="entry-nickname" label="닉네임">
            <Input id="entry-nickname" name="nickname" />
          </FormField>
        </>
      )}
      <FormField id="entry-amount" label="금액 (원)" hint="정수 원화로 입력합니다. 환불은 음수로 입력합니다." required>
        <Input id="entry-amount" name="amount_krw" inputMode="numeric" required autoComplete="off" />
      </FormField>
      <FormField id="entry-note" label="메모">
        <Input id="entry-note" name="operator_note" />
      </FormField>
      <div className="cost-ledger__entry-actions">
        <ActionButton type="button" variant="secondary" onClick={onCancel} disabled={pending}>취소</ActionButton>
        <ActionButton type="submit" variant="primary" pending={pending} pendingLabel="저장 중">저장</ActionButton>
      </div>
    </form>
  );
}
