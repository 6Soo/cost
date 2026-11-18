import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { Bootstrap, LedgerRow, TripSummary } from '../../api/types';
import { ActionButton, Amount, DataTable, Drawer, EmptyState, FormField, InlineNotice, Input, Loading, Select, Tabs } from '../../components';
import { getJSON, postJSON, ApiError } from '../../api/client';
import { EntryForm } from './entryForm';
import { RowDrawer } from './rowDrawer';
import { humanDate, readPage, requestId, useUrlSearch } from './urlState';
import './ledger.css';

import type { LedgerKind } from './urlState';
type LedgerSort = 'date_desc' | 'date_asc' | 'amount_desc' | 'amount_asc' | 'merchant_asc';
type LedgerPayload = {
  trip: TripSummary;
  rows: LedgerRow[];
  total_count: number;
  page: number;
  page_size: number;
  filtered_total: string;
  total: string;
  closed: boolean;
  income_source?: { available: boolean; verified: boolean; reason: string; total?: string | null };
};
type CopyPayload = { tsv: string; row_count: number; total_krw: string; message?: string };
type ExportJob = { job_id?: string; id?: string; status?: string; message?: string };
type EntryKind = 'expense' | 'income';

type PageProps = {
  bootstrap: Bootstrap;
  path: string;
  search: URLSearchParams;
};

function tripLabel(trip: TripSummary): string {
  return trip.title;
}

function currencyLabel(currency: string): string {
  return currency || 'KRW';
}

function safeMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : reason instanceof Error ? reason.message : fallback;
}

function LedgerDesktopTable({
  rows,
  onOpen,
}: {
  rows: LedgerRow[];
  onOpen: (row: LedgerRow) => void;
}) {
  const columns = [
    { key: 'date', header: '날짜', cell: (row: LedgerRow) => humanDate(row.date) },
    {
      key: 'merchant',
      header: '가맹점 / 내용',
      cell: (row: LedgerRow) => (
        <button className="cost-ledger__row-open" type="button" onClick={() => onOpen(row)}>
          <strong>{row.merchant || row.description || '내용 없음'}</strong>
          {row.description && row.description !== row.merchant && <span>{row.description}</span>}
        </button>
      ),
    },
    { key: 'category', header: '항목', cell: (row: LedgerRow) => row.category || '항목 없음' },
    { key: 'amount', header: '금액', align: 'end' as const, cell: (row: LedgerRow) => <Amount value={row.amount} currency={currencyLabel(row.currency)} /> },
    { key: 'evidence', header: '근거', cell: (row: LedgerRow) => row.evidence_summary || '근거 요약 없음' },
  ];
  return (
    <div className="cost-ledger__desktop-table">
      <DataTable caption="여행 장부 거래 목록" columns={columns} rows={rows} getRowKey={(row) => row.id} />
    </div>
  );
}

function LedgerMobileList({
  rows,
  onOpen,
}: {
  rows: LedgerRow[];
  onOpen: (row: LedgerRow) => void;
}) {
  return (
    <ul className="cost-ledger__mobile-list" aria-label="거래 목록">
      {rows.map((row) => (
        <li key={row.id}>
          <button className="cost-ledger__mobile-row" type="button" onClick={() => onOpen(row)}>
            <span className="cost-ledger__mobile-top">
              <time>{humanDate(row.date)}</time>
              <span className="cost-ledger__mobile-amount"><Amount value={row.amount} currency={currencyLabel(row.currency)} /></span>
            </span>
            <strong>{row.merchant || row.description || '내용 없음'}</strong>
            <span className="cost-ledger__mobile-bottom">
              <span>{row.category || '항목 없음'}</span>
              {row.evidence_summary && <span>{row.evidence_summary}</span>}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function LedgerPage({ bootstrap, search: initialSearch }: PageProps) {
  const { search, update } = useUrlSearch(initialSearch);
  const tab = search.get('tab') || bootstrap.trips[0]?.id || '';
  const kind = (search.get('kind') === 'income' ? 'income' : 'expense') as LedgerKind;
  const q = search.get('q') ?? '';
  const sort = (search.get('sort') || 'date_desc') as LedgerSort;
  const page = readPage(search);
  const pageSize = Number(search.get('page_size') || 50);
  const selectedRowId = search.get('row');
  const quarterTab = tab.startsWith('quarter:');
  const [data, setData] = useState<LedgerPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadNotFound, setLoadNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [draftQuery, setDraftQuery] = useState(q);
  const [copyPending, setCopyPending] = useState(false);
  const [copyNotice, setCopyNotice] = useState<{ tone: 'success' | 'warning' | 'error'; text: string } | null>(null);
  const [copyText, setCopyText] = useState('');
  const [exportPending, setExportPending] = useState(false);
  const [exportNotice, setExportNotice] = useState<{ tone: 'success' | 'warning' | 'error'; text: string } | null>(null);
  const [exportHref, setExportHref] = useState<string | null>(null);
  const [entryKind, setEntryKind] = useState<EntryKind | null>(null);

  useEffect(() => setDraftQuery(q), [q]);

  const requestUrl = useMemo(() => {
    if (!tab) return '';
    const params = new URLSearchParams({
      tab,
      kind,
      page: String(page),
      page_size: String(pageSize),
      sort,
    });
    if (q) params.set('q', q);
    return `/api/plush/ledger?${params.toString()}`;
  }, [kind, page, pageSize, q, sort, tab]);

  useEffect(() => {
    if (!requestUrl) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    setLoadNotFound(false);
    getJSON<LedgerPayload>(requestUrl, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setData(payload);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setLoadNotFound(reason instanceof ApiError && reason.status === 404);
        setLoadError(safeMessage(reason, '장부를 불러오지 못했습니다. 연결 상태를 확인해 주세요.'));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [requestUrl, refreshVersion]);

  const trips = bootstrap.trips;
  const loadedTrip = data?.trip.id === tab ? data.trip : undefined;
  /* The Google income source belongs to the trip response currently on screen.
     It is only shown to the owner of a normal trip: quarter, refund and
     protected tabs have no income linkage (the server reports their kind as
     "quarter"), and this is an operator message. Because loadedTrip is derived
     from data for the selected tab, a payload left over from the previous tab
     cannot paint its source here while the new response is still in flight. */
  const incomeSource = bootstrap.role === 'owner' && loadedTrip?.kind === 'trip'
    ? data?.income_source
    : undefined;
  /* §11.2.1 계약 4 + GGL-014: an unverified Google block does not enter the
     confirmed figure, so the summary 수입/차액 are marked provisional while the
     server figure itself is shown unchanged. This is a label only. */
  const incomeProvisional = incomeSource?.available === true && incomeSource.verified === false;
  const currentTrip = loadedTrip ?? trips.find((trip) => trip.id === tab);
  const dataPageSize = data && Number.isFinite(data.page_size) && data.page_size > 0 ? data.page_size : pageSize;
  const pageCount = data ? Math.max(1, Math.ceil(data.total_count / dataPageSize)) : 1;
  const isClosed = loadedTrip ? data?.closed === true : currentTrip?.closed ?? false;
  const ledgerLoadedForTab = loadedTrip !== undefined
    && typeof data?.closed === 'boolean'
    && !loading
    && !loadError;
  const ownerCanWrite = bootstrap.role === 'owner'
    && ledgerLoadedForTab
    && currentTrip !== undefined
    && !currentTrip.closed
    && !currentTrip.archived
    && !isClosed
    && tab !== 'unclassified'
    && !quarterTab;

  function openRow(row: LedgerRow) {
    update({ row: row.id });
  }

  function closeRow() {
    update({ row: null });
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    update({ q: draftQuery.trim(), page: null });
  }

  async function copyForGoogle() {
    if (!tab || kind !== 'expense' || bootstrap.role !== 'owner' || copyPending) return;
    setCopyPending(true);
    setCopyNotice(null);
    setCopyText('');
    try {
      const params = new URLSearchParams({ tab, kind: 'ex' });
      if (q) params.set('q', q);
      const result = await getJSON<CopyPayload>(`/api/board/tsv?${params.toString()}`);
      if (typeof result.tsv !== 'string') throw new Error('서버가 복사할 내용을 반환하지 않았습니다.');
      setCopyText(result.tsv);
      try {
        await navigator.clipboard.writeText(result.tsv);
        setCopyNotice({ tone: 'success', text: `${result.row_count}건 · 전체 ${result.total_krw}원이 복사되었습니다. Google 시트에 붙여넣으세요.` });
      } catch {
        setCopyNotice({ tone: 'warning', text: `${result.row_count}건의 서버 산출 내용을 준비했습니다. 아래 텍스트를 선택해 직접 복사해 주세요.` });
      }
    } catch (reason: unknown) {
      setCopyNotice({ tone: 'error', text: safeMessage(reason, '복사 내용을 만들지 못했습니다.') });
    } finally {
      setCopyPending(false);
    }
  }

  async function exportTrip() {
    if (!tab || quarterTab || bootstrap.role !== 'owner' || exportPending) return;
    setExportPending(true);
    setExportNotice(null);
    setExportHref(null);
    try {
      const response = await postJSON<ExportJob>('/api/exports/xlsx', {
        tab_ids: [tab],
        client_request_id: requestId(),
      }, bootstrap.csrf);
      const jobId = response.job_id || response.id;
      if (!jobId) throw new Error('내보내기 작업 ID를 확인하지 못했습니다. 장부를 다시 조회해 주세요.');
      let job = response;
      if (response.status !== 'ready') {
        job = await getJSON<ExportJob>(`/api/exports/${encodeURIComponent(jobId)}`);
      }
      if (job.status === 'ready') {
        setExportHref(`/api/exports/${encodeURIComponent(jobId)}/download`);
        setExportNotice({ tone: 'success', text: '현재 필터와 관계없이 이 여행 전체를 기준으로 XLSX를 만들었습니다.' });
      } else {
        setExportNotice({ tone: 'warning', text: job.message || '내보내기 작업이 접수됐지만 다운로드 준비 상태를 확인하지 못했습니다. 다시 조회해 주세요.' });
      }
    } catch (reason: unknown) {
      setExportNotice({ tone: 'error', text: safeMessage(reason, 'XLSX를 만들지 못했습니다.') });
    } finally {
      setExportPending(false);
    }
  }

  return (
    <main className="cost-ledger">
      <header className="cost-ledger__header">
        <div className="cost-ledger__breadcrumbs"><a href="/trips">여행</a><span aria-hidden="true">/</span><span>장부</span></div>
        <div className="cost-ledger__title-row">
          <div>
            <h1>{loadNotFound ? '여행을 찾을 수 없음' : currentTrip ? tripLabel(currentTrip) : '여행 장부'}</h1>
            {currentTrip && <p>{humanDate(currentTrip.starts_on)}–{humanDate(currentTrip.ends_on)}</p>}
          </div>
          <div className="cost-ledger__trip-select">
            <FormField id="cost-ledger-trip" label="여행 전환">
              <Select id="cost-ledger-trip" value={tab} onChange={(event) => update({ tab: event.currentTarget.value, row: null, page: null })}>
                {trips.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}
                {tab === 'unclassified' && <option value="unclassified">이전 귀속 목록</option>}
              </Select>
            </FormField>
          </div>
        </div>
        {currentTrip && (
          <dl className={`cost-ledger__summary${incomeProvisional ? ' cost-ledger__summary--provisional' : ''}`}
            aria-label="여행 손익">
            <div><dt>수입{incomeProvisional && <span className="cost-ledger__provisional">잠정</span>}</dt><dd><Amount value={currentTrip.income} currency="KRW" /></dd></div>
            <div><dt>지출</dt><dd><Amount value={currentTrip.expense} currency="KRW" /></dd></div>
            <div><dt>차액{incomeProvisional && <span className="cost-ledger__provisional">잠정</span>}</dt><dd><Amount value={currentTrip.profit} currency="KRW" /></dd></div>
          </dl>
        )}
      </header>

      {data?.closed && <InlineNotice tone="info" title="마감 기간 · 읽기 전용">이 기간은 기존 마감 보호를 유지합니다. 교정 기능은 서버가 허용한 경우에만 표시됩니다.</InlineNotice>}
      {loadError && <InlineNotice tone="error" title="장부를 불러오지 못했습니다">{loadError}</InlineNotice>}

      <Tabs
        ariaLabel="장부 종류"
        value={kind}
        onChange={(value) => update({ kind: value, page: null, row: null })}
        items={[{ id: 'expense', label: '지출' }, { id: 'income', label: '수입' }]}
      />

      <section className="cost-ledger__toolbar" aria-label="장부 검색과 동작">
        <form className="cost-ledger__search" role="search" onSubmit={submitSearch}>
          <FormField id="cost-ledger-search" label="장부 검색">
            <Input
              id="cost-ledger-search"
              type="search"
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.currentTarget.value)}
              placeholder="가맹점 또는 내용 검색"
            />
          </FormField>
          <ActionButton type="submit" variant="secondary">검색</ActionButton>
          {q && <ActionButton type="button" variant="ghost" onClick={() => { setDraftQuery(''); update({ q: null, page: null }); }}>초기화</ActionButton>}
        </form>
        <div className="cost-ledger__controls">
          <FormField id="cost-ledger-sort" label="정렬">
            <Select id="cost-ledger-sort" value={sort} onChange={(event) => update({ sort: event.currentTarget.value, page: null })}>
              <option value="date_desc">날짜 최신순</option>
              <option value="date_asc">날짜 오래된순</option>
              <option value="amount_desc">금액 높은순</option>
              <option value="amount_asc">금액 낮은순</option>
              <option value="merchant_asc">가맹점 이름순</option>
            </Select>
          </FormField>
          <FormField id="cost-ledger-page-size" label="페이지당 행">
            <Select id="cost-ledger-page-size" value={String(pageSize)} onChange={(event) => update({ page_size: event.currentTarget.value, page: null })}>
              <option value="25">25</option><option value="50">50</option><option value="100">100</option>
            </Select>
          </FormField>
        </div>
        {bootstrap.role === 'owner' && (
          <div className="cost-ledger__actions">
            {kind === 'expense' && !quarterTab && <ActionButton type="button" variant="secondary" pending={copyPending} pendingLabel="복사 준비 중" onClick={copyForGoogle}>Google 장부용 복사</ActionButton>}
            {!quarterTab && <ActionButton type="button" variant="ghost" pending={exportPending} pendingLabel="XLSX 생성 중" onClick={exportTrip}>XLSX 내보내기</ActionButton>}
            {ownerCanWrite && <ActionButton type="button" variant="primary" onClick={() => setEntryKind(kind)}> {kind === 'expense' ? '수기 지출 추가' : '수입 직접 입력'}</ActionButton>}
          </div>
        )}
      </section>

      {copyNotice && <InlineNotice tone={copyNotice.tone} title="Google 장부용 복사">{copyNotice.text}</InlineNotice>}
      {copyText && copyNotice?.tone !== 'success' && (
        <div className="cost-ledger__copy-fallback">
          <label htmlFor="cost-copy-text">서버가 만든 붙여넣기 내용</label>
          <textarea id="cost-copy-text" rows={5} readOnly value={copyText} onFocus={(event) => event.currentTarget.select()} />
        </div>
      )}
      {exportNotice && (
        <InlineNotice tone={exportNotice.tone} title="XLSX 내보내기">
          {exportNotice.text}
          {exportHref && <a className="cost-ledger__download" href={exportHref}>파일 다운로드</a>}
        </InlineNotice>
      )}

      {incomeSource?.available && !incomeSource.verified && (
        <InlineNotice tone="warning" title="수입 원장 대조 정보">
          Google 수입 원장의 대사가 완료되지 않았습니다. 표시된 수입과 차액은 잠정 금액입니다. 빈 금액은 미확인으로 표시합니다.
        </InlineNotice>
      )}
      {incomeSource && !incomeSource.available && incomeSource.reason === 'NOT_CONNECTED' && (
        <InlineNotice tone="info" title="Google 수입 원장 미연결">
          이 여행에 연결된 Google 수입 원장이 없습니다. Google 수입 행은 이 여행의 수입 탭에 표시되지 않습니다.
        </InlineNotice>
      )}
      {incomeSource && !incomeSource.available && incomeSource.reason !== 'NOT_CONNECTED' && (
        <InlineNotice tone="warning" title="Google 수입 내역을 불러오지 못했습니다">
          현재 표시된 COST 수입 외에 연결된 원장의 수입이 있을 수 있습니다.
        </InlineNotice>
      )}
      {incomeSource?.available && (
        /* GGL-003·GGL-014: the Google block is separate evidence. It is shown
           here on its own and is never added to the summary 수입·차액 above,
           which stay exactly the server's trip.income/trip.profit. */
        <section className="cost-ledger__google-income" aria-label="Google 수입 별도 증거">
          <span>연결된 Google 수입 합계</span>
          {incomeSource.total ? (
            <Amount value={incomeSource.total} currency="KRW" />
          ) : (
            <span className="cost-ledger__google-income-missing">금액 미확인</span>
          )}
          <span className={`cost-ledger__match cost-ledger__match--${incomeSource.verified ? 'ok' : 'warn'}`}>
            {incomeSource.verified ? '검증됨' : '미검증'}
          </span>
          <small>이 금액은 위 수입·차액에 더하지 않습니다.</small>
        </section>
      )}
      {loading && <Loading label="장부 조회 중" />}
      {!loading && !loadError && data && (
        <>
          <div className="cost-ledger__totals" aria-live="polite">
            <div><span>조회 합계</span><strong><Amount value={data.filtered_total} currency="KRW" /></strong></div>
            <div><span>전체 합계</span><strong><Amount value={data.total} currency="KRW" /></strong></div>
            <p>{data.total_count}건 · {data.page} / {pageCount}페이지</p>
          </div>
          {data.rows.length ? (
            <>
              <LedgerDesktopTable rows={data.rows} onOpen={openRow} />
              <LedgerMobileList rows={data.rows} onOpen={openRow} />
              <nav className="cost-ledger__pagination" aria-label="장부 페이지">
                <ActionButton type="button" variant="secondary" disabled={page <= 1 || loading} onClick={() => update({ page: page - 1 })}>이전</ActionButton>
                <span>{page} / {pageCount}페이지</span>
                <ActionButton type="button" variant="secondary" disabled={page >= pageCount || loading} onClick={() => update({ page: page + 1 })}>다음</ActionButton>
              </nav>
            </>
          ) : (
            <EmptyState
              title={q ? '검색 결과가 없습니다' : `${kind === 'expense' ? '지출' : '수입'} 내역이 없습니다`}
              description={q ? '검색어를 바꾸거나 초기화해 보세요.' : '현재 서버 조회 결과에 표시할 행이 없습니다.'}
              action={q ? <ActionButton type="button" variant="secondary" onClick={() => update({ q: null, page: null })}>검색 초기화</ActionButton> : undefined}
            />
          )}
        </>
      )}

      <RowDrawer
        rowId={selectedRowId}
        bootstrap={bootstrap}
        tab={tab}
        kind={kind}
        search={search}
        onClose={closeRow}
        onSaved={() => setRefreshVersion((version) => version + 1)}
      />
      <Drawer
        open={Boolean(entryKind)}
        title={entryKind === 'income' ? '수입 직접 입력' : '수기 지출 추가'}
        description="저장하면 실제 장부 기록을 다시 조회합니다."
        onOpenChange={(open) => { if (!open) setEntryKind(null); }}
      >
        {entryKind && (
          <EntryForm
            kind={entryKind}
            bootstrap={bootstrap}
            tripId={tab}
            onCancel={() => setEntryKind(null)}
            onCreated={(rowId) => {
              setEntryKind(null);
              setRefreshVersion((version) => version + 1);
              update({ row: rowId });
            }}
          />
        )}
      </Drawer>
    </main>
  );
}
