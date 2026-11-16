import { useMemo, useState } from "react";
import type { TransactionsResponse } from "../../api/types";
import {
  DataRows,
  FeatureActionPanel,
  FeatureNav,
  featureError,
  pagePath,
  transactionPath,
  transactionView,
  useResource,
  type FeaturePayload,
  type PageProps,
} from "./feature-ui";
import "./feature.css";

const TRANSACTION_TABS = [
  { id: "cards", label: "카드", path: "/cards/all" },
  { id: "ota", label: "OTA", path: "/ota" },
  { id: "refunds", label: "환불", path: "/board", query: { tab: "refunds" } },
  { id: "flights", label: "항공권", path: "/flight-passengers" },
];

const TITLES: Record<string, string> = {
  cards: "카드 거래",
  ota: "OTA 예약",
  refunds: "환불 연결",
  flights: "항공권 연결",
};

// Keep the card history filters used by the existing /cards/all URLs. Cursor
// values are forwarded for deep links, while React page navigation starts a
// fresh offset page and therefore drops those old cursor values.
const CARD_FILTER_KEYS = ["year", "month", "period", "card", "card_kind", "q", "undated"];
const SOURCE_FILTER_KEYS: Record<string, string[]> = {
  cards: CARD_FILTER_KEYS,
  ota: ["q", "month", "provider", "state", "sort"],
  flights: ["q", "trip", "tab"],
  refunds: ["q"],
};
const filterKeysFor = (view: string) => SOURCE_FILTER_KEYS[view] || ["q"];

const CARD_CURSOR_KEYS = ["cursor", "undated_cursor"];
const DEFAULT_PAGE_SIZE = 50;
const CARD_PAGE_SIZE = 100;

function validPage(search: URLSearchParams) {
  const value = Number(search.get("page") || "1");
  return Number.isSafeInteger(value) && value > 0 ? value : 1;
}

function validPageSize(search: URLSearchParams, view: string) {
  const fallback = view === "cards" ? CARD_PAGE_SIZE : DEFAULT_PAGE_SIZE;
  const value = Number(search.get("page_size") || String(fallback));
  return Number.isSafeInteger(value) && value > 0 && value <= 200 ? value : fallback;
}

function copyQueryKeys(target: URLSearchParams, source: URLSearchParams, keys: string[]) {
  for (const key of keys) {
    for (const value of source.getAll(key)) {
      if (value !== "") target.append(key, value);
    }
  }
}

export function endpointFor(view: string, query: URLSearchParams) {
  const params = new URLSearchParams();
  params.set("view", view);
  params.set("page", String(validPage(query)));
  params.set("page_size", String(validPageSize(query, view)));
  if (view === "cards") {
    copyQueryKeys(params, query, [...CARD_FILTER_KEYS, ...CARD_CURSOR_KEYS]);
  } else {
    copyQueryKeys(params, query, filterKeysFor(view));
  }
  return `/api/plush/transactions?${params.toString()}`;
}

export function queryForPage(path: string, view: string, query: URLSearchParams, page: number, pageSize: number) {
  const params = new URLSearchParams({ view, page: String(page), page_size: String(pageSize) });
  copyQueryKeys(params, query, filterKeysFor(view));
  if (view === "refunds") params.set("tab", "refunds");
  return uiPathWithQuery(path, params);
}

export function queryForSearch(path: string, view: string, query: URLSearchParams, pageSize: number, term: string) {
  const params = new URLSearchParams({ view, page: "1", page_size: String(pageSize) });
  copyQueryKeys(params, query, filterKeysFor(view).filter((key) => key !== "q"));
  if (term) params.set("q", term);
  if (view === "refunds") params.set("tab", "refunds");
  return uiPathWithQuery(path, params);
}

function uiPathWithQuery(path: string, params: URLSearchParams) {
  const target = path.startsWith("/") ? `/ui${path}` : `/ui/${path}`;
  return [...params.keys()].length ? `${target}?${params.toString()}` : target;
}

function OwnerOnlyTransactions() {
  return (
    <main className="e-feature-page">
      <section className="cost-panel e-feature-state" role="alert">
        <h1>거래 화면은 소유자 전용입니다</h1>
        <p>현재 계정에서 사용할 수 있는 거래 자료가 없습니다.</p>
      </section>
    </main>
  );
}

export function TransactionsPage(props: PageProps) {
  if (props.bootstrap.role !== "owner") return <OwnerOnlyTransactions />;
  return <OwnerTransactionsPage {...props} />;
}

function OwnerTransactionsPage(props: PageProps) {
  const path = pagePath(props);
  const view = transactionView(path, props.search);
  const page = validPage(props.search);
  const requestedPageSize = validPageSize(props.search, view);
  const endpoint = endpointFor(view, props.search);
  const { state, reload } = useResource<TransactionsResponse>(endpoint);
  const [notice, setNotice] = useState("");
  const [searchError, setSearchError] = useState("");
  const isKnownView = Object.prototype.hasOwnProperty.call(TITLES, view);
  const pageTitle = TITLES[view] || "거래";
  const payload = state.kind === "ready"
    ? ({ ...state.payload, title: pageTitle } as FeaturePayload & TransactionsResponse)
    : null;
  const actions = useMemo(() => (payload?.actions ?? []).filter((action) => {
    if (action.method === "POST" && props.bootstrap.role !== "owner") return false;
    const target = `${action.id} ${action.href}`.toLowerCase();
    return !/\/api\/user-actions\/answer/.test(target);
  }), [payload, props.bootstrap.role]);
  const currentPath = transactionPath(view);
  const pageSize = state.kind === "ready" ? Math.max(1, state.payload.page_size) : requestedPageSize;
  const totalCount = state.kind === "ready" ? Math.max(0, state.payload.total_count) : 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const previousHref = queryForPage(currentPath, view, props.search, Math.max(1, page - 1), pageSize);
  const nextHref = queryForPage(currentPath, view, props.search, Math.min(totalPages, page + 1), pageSize);

  if (!isKnownView) {
    return (
      <main className="e-feature-page">
        <section className="cost-panel e-feature-state" role="alert">
          <h1>지원하지 않는 거래 화면입니다</h1>
          <p>거래 탭을 선택해 주세요.</p>
          <FeatureNav label="거래" items={TRANSACTION_TABS} current="cards" />
        </section>
      </main>
    );
  }

  async function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const q = String(form.get("q") ?? "").trim();
    setSearchError("");
    try {
      // Keep filtering and pagination on the server; only the query state is placed in the URL.
      window.location.assign(queryForSearch(currentPath, view, props.search, pageSize, q));
    } catch (error) {
      setSearchError(featureError(error));
    }
  }

  return (
    <main className="e-feature-page">
      <header className="e-feature-header">
        <div><p className="e-feature-eyebrow">COST · 거래</p><h1>{payload?.title || pageTitle}</h1></div>
        <button type="button" className="cost-button cost-button-quiet" onClick={() => { setNotice(""); reload(); }}>
          새로고침
        </button>
      </header>
      <FeatureNav label="거래 종류" items={TRANSACTION_TABS} current={view} />

      <form className="e-feature-filter cost-panel" onSubmit={submitSearch} role="search" aria-label="거래 검색">
        <label className="e-feature-field" htmlFor="transaction-search">
          <span>검색</span>
          <input id="transaction-search" type="search" name="q" defaultValue={props.search.get("q") || ""}
            autoComplete="off" placeholder="내용·예약·가맹점 검색" />
        </label>
        <button type="submit" className="cost-button">검색</button>
        {props.search.has("q") ? <a className="cost-button cost-button-quiet"
          href={queryForSearch(currentPath, view, props.search, pageSize, "")}>초기화</a> : null}
      </form>
      {searchError ? <p className="e-feature-error" role="alert">{searchError}</p> : null}
      {notice ? <p className="e-feature-notice" role="status">{notice}</p> : null}

      {state.kind === "loading" ? <p className="cost-panel e-feature-loading" role="status">거래 자료를 불러오는 중입니다…</p> : null}
      {state.kind === "error" ? (
        <section className="cost-panel e-feature-state" role="alert">
          <h2>거래를 불러오지 못했습니다</h2><p>{state.message}</p>
          <button className="cost-button" type="button" onClick={reload}>다시 불러오기</button>
        </section>
      ) : null}
      {payload ? (
        <>
          {payload.status?.message ? <p className="e-feature-status" role="status">{payload.status.message}</p> : null}
          <DataRows payload={payload} />
          {!payload.rows.length ? (
            <section className="cost-panel e-feature-state">
              <h2>표시할 거래가 없습니다</h2>
              <p>{payload.status?.message || "현재 조건에 맞는 거래가 없습니다."}</p>
            </section>
          ) : null}
          <div className="e-feature-pagination" aria-label="거래 페이지 정보">
            <p>전체 {totalCount.toLocaleString("ko-KR")}건 · {page} / {totalPages}페이지</p>
            <nav aria-label="페이지 이동">
              <a className="cost-button cost-button-secondary" aria-disabled={page <= 1 || undefined}
                href={previousHref} tabIndex={page <= 1 ? -1 : undefined}>이전</a>
              <a className="cost-button cost-button-secondary" aria-disabled={page >= totalPages || undefined}
                href={nextHref} tabIndex={page >= totalPages ? -1 : undefined}>다음</a>
            </nav>
          </div>
          <FeatureActionPanel actions={actions} bootstrap={props.bootstrap} onRefresh={reload} onNotice={setNotice} />
        </>
      ) : null}
    </main>
  );
}
