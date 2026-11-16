import { useMemo } from 'react';
import type { Bootstrap, TripSummary } from '../../api/types';
import { Amount, DataTable, EmptyState, FormField, Input, Select, Tabs } from '../../components';
import { humanDate, readPage, useUrlSearch } from '../ledger/urlState';
import './trips.css';

type TripKind = 'trip' | 'quarter';
type TripListItem = TripSummary & { kind?: TripKind; previous?: boolean; search_text?: string };
type TripState = 'all' | 'active' | 'closed' | 'previous' | 'archived' | 'quarter';
type TripSort = 'starts_desc' | 'starts_asc' | 'profit_desc' | 'profit_asc' | 'title_asc';

type PageProps = {
  bootstrap: Bootstrap;
  path: string;
  search: URLSearchParams;
};

function stateFor(trip: TripListItem): Exclude<TripState, 'all'> {
  if (trip.kind === 'quarter' || trip.id.startsWith('quarter:')) return 'quarter';
  if (trip.archived) return 'archived';
  if (trip.closed) return 'closed';
  if (trip.previous) return 'previous';
  return 'active';
}

function statusLabel(trip: TripListItem): string {
  const state = stateFor(trip);
  return ({
    active: '진행 중',
    closed: '마감',
    previous: '이전',
    archived: '보관',
    quarter: '분기 기타비용',
  } as const)[state];
}

function compareIntegerStrings(left: string, right: string): number {
  try {
    const a = BigInt(left || '0');
    const b = BigInt(right || '0');
    return a < b ? -1 : a > b ? 1 : 0;
  } catch {
    return left.localeCompare(right);
  }
}

function ledgerHref(id: string): string {
  return `/board?${new URLSearchParams({ tab: id }).toString()}`;
}

export function TripsPage({ bootstrap, search: initialSearch }: PageProps) {
  const { search, update } = useUrlSearch(initialSearch);
  const q = search.get('q') ?? '';
  const state = (search.get('state') || 'active') as TripState;
  const sort = (search.get('sort') || 'starts_desc') as TripSort;
  const page = readPage(search);
  const pageSize = 20;

  const trips = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase('ko-KR');
    const filtered = (bootstrap.trips as TripListItem[]).filter((trip) => {
      if (state !== 'all' && stateFor(trip) !== state) return false;
      if (!needle) return true;
      const searchable = [trip.title, trip.id, trip.search_text].filter(Boolean).join(' ').toLocaleLowerCase('ko-KR');
      return searchable.includes(needle);
    });
    return filtered.sort((a, b) => {
      switch (sort) {
        case 'starts_asc': return a.starts_on.localeCompare(b.starts_on) || a.title.localeCompare(b.title, 'ko');
        case 'profit_desc': return compareIntegerStrings(b.profit, a.profit) || b.starts_on.localeCompare(a.starts_on);
        case 'profit_asc': return compareIntegerStrings(a.profit, b.profit) || b.starts_on.localeCompare(a.starts_on);
        case 'title_asc': return a.title.localeCompare(b.title, 'ko');
        default: return b.starts_on.localeCompare(a.starts_on) || a.title.localeCompare(b.title, 'ko');
      }
    });
  }, [bootstrap.trips, q, sort, state]);

  const pageCount = Math.max(1, Math.ceil(trips.length / pageSize));
  const visibleTrips = trips.slice((page - 1) * pageSize, page * pageSize);
  const columns = [
    {
      key: 'title',
      header: '여행',
      cell: (trip: TripListItem) => (
        <a className="cost-trips__trip-link" href={ledgerHref(trip.id)} title={trip.title}>
          <strong>{trip.title}</strong>
          <span>{humanDate(trip.starts_on)}–{humanDate(trip.ends_on)}</span>
        </a>
      ),
    },
    { key: 'status', header: '상태', cell: (trip: TripListItem) => <span className="cost-trips__status">{statusLabel(trip)}</span> },
    { key: 'income', header: '수입', align: 'end' as const, cell: (trip: TripListItem) => <Amount value={trip.income} currency="KRW" /> },
    { key: 'expense', header: '지출', align: 'end' as const, cell: (trip: TripListItem) => <Amount value={trip.expense} currency="KRW" /> },
    { key: 'profit', header: '차액', align: 'end' as const, cell: (trip: TripListItem) => <Amount value={trip.profit} currency="KRW" /> },
  ];

  return (
    <main className="cost-trips">
      <header className="cost-trips__header">
        <div>
          <p className="cost-eyebrow">숲길여행 회계</p>
          <h1>여행</h1>
          <p>권한이 있는 여행과 분기 기타비용을 확인합니다.</p>
        </div>
        <span className="cost-trips__count" aria-live="polite">{trips.length}개</span>
      </header>

      <Tabs
        ariaLabel="여행 상태 필터"
        value={state}
        onChange={(value) => update({ state: value, page: null })}
        items={[
          { id: 'active', label: '진행 중' },
          { id: 'closed', label: '마감' },
          { id: 'previous', label: '이전' },
          { id: 'archived', label: '보관' },
          { id: 'quarter', label: '분기 기타비용' },
          { id: 'all', label: '전체' },
        ]}
      />

      <section className="cost-trips__filters" aria-label="여행 검색과 정렬">
        <FormField id="cost-trip-search" label="여행 검색" hint="여행 이름 또는 검색 가능한 여행 정보">
          <Input
            id="cost-trip-search"
            type="search"
            value={q}
            onChange={(event) => update({ q: event.currentTarget.value, page: null }, true)}
            placeholder="여행 이름 검색"
          />
        </FormField>
        <FormField id="cost-trip-sort" label="정렬">
          <Select id="cost-trip-sort" value={sort} onChange={(event) => update({ sort: event.currentTarget.value, page: null })}>
            <option value="starts_desc">최근 시작일순</option>
            <option value="starts_asc">오래된 시작일순</option>
            <option value="profit_desc">차액 높은순</option>
            <option value="profit_asc">차액 낮은순</option>
            <option value="title_asc">이름순</option>
          </Select>
        </FormField>
      </section>

      {visibleTrips.length ? (
        <>
          <div className="cost-trips__table">
            <DataTable
              caption="여행별 정산 요약"
              columns={columns}
              rows={visibleTrips}
              getRowKey={(trip) => trip.id}
            />
          </div>
          <nav className="cost-trips__pagination" aria-label="여행 목록 페이지">
            <button type="button" className="cost-button" disabled={page <= 1} onClick={() => update({ page: page - 1})}>이전</button>
            <span aria-live="polite">{page} / {pageCount}페이지</span>
            <button type="button" className="cost-button" disabled={page >= pageCount} onClick={() => update({ page: page + 1 })}>다음</button>
          </nav>
        </>
      ) : (
        <EmptyState
          title={q ? '검색 결과가 없습니다' : '이 상태의 여행이 없습니다'}
          description={q ? '검색어를 바꾸거나 지워 보세요.' : '다른 상태를 선택하면 해당 여행을 볼 수 있습니다.'}
          action={q ? <button type="button" className="cost-button" onClick={() => update({ q: null, page: null })}>검색 지우기</button> : undefined}
        />
      )}

      {bootstrap.role === 'owner' && (
        <p className="cost-trips__source-note">여행은 Google 시트 탭을 기준으로 표시합니다. 새 여행은 Google 시트에서 만듭니다.</p>
      )}
    </main>
  );
}
