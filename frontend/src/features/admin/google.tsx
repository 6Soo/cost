import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, executeAction, getJSON, postJSON, type ActionValue } from "../../api/client";
import type { ActionDescriptor, AdminResponse, Bootstrap } from "../../api/types";
import { ActionButton, InlineNotice } from "../../components";
import { FeatureNav, featureError, type PageProps } from "../transactions/feature-ui";
import "../transactions/feature.css";
import "./google.css";

const GOOGLE_ENDPOINT = "/api/plush/admin?view=google";
const GOOGLE_SYNC_ENDPOINT = "/api/google-ledger/sync";
const ADMIN_NAV = [
  { id: "accounts", label: "계정·권한", path: "/access/admin", query: { view: "accounts" } },
  { id: "profile", label: "기본 정보", path: "/access/admin", query: { view: "profile" } },
  { id: "google", label: "Google 장부", path: "/google-ledger" },
  { id: "review", label: "AI 검수 결과", path: "/review" },
];

type MoneyValue = string | null;
type GoogleCopy = {
  present: boolean;
  layout: string | null;
  verified: boolean;
  income_total: MoneyValue;
  expense_total: MoneyValue;
  flags: string[];
};
type GoogleTrip = {
  key: string;
  kind: string;
  closure: string;
  closure_current: boolean;
  chosen_source: string | null;
  verified: boolean;
  blocked_by: string[];
  review: string[];
  income_total: MoneyValue;
  expense_total: MoneyValue;
  net: MoneyValue;
  connected_tab_id: string | null;
  source_href: string | null;
  reconciliation_href: string | null;
  copy_href: string | null;
  copies: Record<string, GoogleCopy>;
};
type GoogleSource = {
  status: string;
  error_code: string | null;
  stale: boolean;
  last_ok_at: string | null;
  checked_at: string | null;
};
type GoogleSettings = {
  connections: Array<{ trip_key: string; tab_id: string; tab_label: string | null }>;
  copy_choices: Array<{ trip_key: string; source: string }>;
  viewer_grants: Array<{ user_id: string; trip_keys: string[] }>;
  tabs: Array<{ tab_id: string; label: string }>;
};
type GoogleData = {
  enabled: boolean;
  available: boolean;
  synced_at: string | null;
  sources: Record<string, GoogleSource>;
  settings: GoogleSettings;
};
type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; payload: AdminResponse };
type NoticeState = { tone: "info" | "success" | "warning" | "error"; title: string; message?: string };
type ReconciliationResult = {
  transaction_id: string;
  trip_id: string;
  status: string;
  status_label: string;
  date: string;
  merchant: string;
  category: string;
  description: string;
  amount_krw: MoneyValue;
  currency: string;
  card: string;
  sheet_id: string;
  source: string;
  row_number: number | null;
  basis: string[];
  differences: Record<string, { manual: string; cost: string }>;
  reason: string;
  user_corrected: boolean;
  correction_source: string;
  review_href: string | null;
};
type ReconciliationPayload = {
  code: string;
  message: string;
  trip_id: string;
  source_available: boolean;
  source_info: { sheet_id: string; source: string; layout: string; synced_at: string | null };
  counts: Record<string, number>;
  results: ReconciliationResult[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  preview_digest: string;
  source_digest: string;
  links_revision: number | null;
};
type ReconciliationState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; payload: ReconciliationPayload };

const REASON_LABELS: Record<string, string> = {
  AMOUNT_INVALID: "금액이 숫자가 아님",
  AMOUNT_MISSING: "날짜는 있으나 금액이 없음",
  ARCHIVE_ONLY: "보관 장부에만 있음",
  CHOICE_REQUIRED: "비교 사본 선택 필요",
  CHOSEN_COPY_MISSING: "선택한 사본을 찾지 못함",
  COPY_NAME: "사본 이름 탭",
  COPY_NOT_VERIFIED: "선택한 사본이 검증되지 않음",
  CLOSURE_NOT_CURRENT: "마감 상태가 최신이 아님",
  DUPLICATE_IN_BOTH: "메인과 보관에 모두 있음",
  DUPLICATE_IN_SOURCE: "같은 탭 이름이 두 번 있음",
  FORMULA_ERROR: "수식 오류",
  LAYOUT_NOT_STANDARD: "구형 양식 (자동 변환하지 않음)",
  PERIOD_YEAR_CONFLICT: "여행 연도 불일치",
  PERIOD_YEAR_MISSING: "여행 연도를 확인할 수 없음",
  POSSIBLE_DUPLICATE: "이름이 비슷한 탭이 있음",
  SOURCE_NOT_CURRENT: "원본 동기화가 최신이 아님",
  SOURCE_STALE: "마지막 정상 동기화 값이 오래됨",
  TOTAL_FORMULA_UNCLEAR: "합계 수식을 찾지 못함",
  TOTAL_MISMATCH: "장부 합계와 행 합계가 다름",
  TOTAL_NOT_CACHED: "합계 값이 없음",
  TOTAL_RANGE_MISMATCH: "합계 수식 범위가 데이터 행과 다름",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function asMoney(value: unknown): MoneyValue {
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  return typeof value === "string" && value.trim() ? value : null;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeCopy(value: unknown): GoogleCopy {
  const copy = asRecord(value);
  return {
    present: copy.present === true,
    layout: asText(copy.layout),
    verified: copy.verified === true,
    income_total: asMoney(copy.income_total),
    expense_total: asMoney(copy.expense_total),
    flags: asStringList(copy.flags),
  };
}

function normalizeTrip(value: unknown): GoogleTrip | null {
  const row = asRecord(value);
  const key = asText(row.key);
  if (!key) return null;
  const rawCopies = asRecord(row.copies);
  const copies = Object.fromEntries(Object.entries(rawCopies).map(([source, copy]) => [source, normalizeCopy(copy)]));
  return {
    key,
    kind: asText(row.kind) ?? "trip",
    closure: asText(row.closure) ?? "unknown",
    closure_current: row.closure_current === true,
    chosen_source: asText(row.chosen_source),
    verified: row.verified === true,
    blocked_by: asStringList(row.blocked_by),
    review: asStringList(row.review),
    income_total: asMoney(row.income_total),
    expense_total: asMoney(row.expense_total),
    net: asMoney(row.net),
    connected_tab_id: asText(row.connected_tab_id),
    source_href: asText(row.source_href),
    reconciliation_href: asText(row.reconciliation_href),
    copy_href: asText(row.copy_href),
    copies,
  };
}

function normalizeSource(value: unknown): GoogleSource {
  const source = asRecord(value);
  return {
    status: asText(source.status) ?? "unknown",
    error_code: asText(source.error_code),
    stale: source.stale === true,
    last_ok_at: asText(source.last_ok_at),
    checked_at: asText(source.checked_at),
  };
}

function normalizeGoogleData(value: unknown): GoogleData {
  const data = asRecord(value);
  const rawSettings = asRecord(data.settings);
  const connections = asRecords(rawSettings.connections).flatMap((entry) => {
    const trip_key = asText(entry.trip_key);
    const tab_id = asText(entry.tab_id);
    return trip_key && tab_id ? [{ trip_key, tab_id, tab_label: asText(entry.tab_label) }] : [];
  });
  const copy_choices = asRecords(rawSettings.copy_choices).flatMap((entry) => {
    const trip_key = asText(entry.trip_key);
    const source = asText(entry.source);
    return trip_key && source ? [{ trip_key, source }] : [];
  });
  const viewer_grants = asRecords(rawSettings.viewer_grants).flatMap((entry) => {
    const user_id = asText(entry.user_id);
    if (!user_id) return [];
    return [{ user_id, trip_keys: asStringList(entry.trip_keys) }];
  });
  const tabs = asRecords(rawSettings.tabs).flatMap((entry) => {
    const tab_id = asText(entry.tab_id);
    return tab_id ? [{ tab_id, label: asText(entry.label) ?? tab_id }] : [];
  });
  const rawSources = asRecord(data.sources);
  return {
    enabled: data.enabled === true,
    available: data.available === true,
    synced_at: asText(data.synced_at),
    sources: Object.fromEntries(Object.entries(rawSources).map(([source, status]) => [source, normalizeSource(status)])),
    settings: { connections, copy_choices, viewer_grants, tabs },
  };
}

function normalizeTrips(value: unknown): GoogleTrip[] {
  return Array.isArray(value)
    ? value.map(normalizeTrip).filter((row): row is GoogleTrip => row !== null)
    : [];
}

function labelSource(source: string | null): string {
  if (source === "main") return "메인 장부";
  if (source === "archive") return "보관 장부";
  if (source === "andre_main") return "Andre 메인 장부";
  return source ?? "선택 안 됨";
}

function labelReason(code: string): string {
  return REASON_LABELS[code] ?? code.replaceAll("_", " ");
}

function formatMoney(value: MoneyValue): string {
  if (value === null) return "미확인";
  const text = value.trim();
  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(text);
  if (!match) return `${text}원`;
  const [, sign, integer, fraction = ""] = match;
  return `${sign}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}원`;
}

function formatTime(value: string | null): string {
  if (!value) return "기록 없음";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "시각 확인 필요";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Seoul",
  }).format(date);
}

function safeSourceHref(value: string | null): string | null {
  if (!value) return null;
  try {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(value, origin);
    const tripValues = url.searchParams.getAll("trip");
    if (url.origin !== origin || url.pathname !== "/api/google-ledger/source" ||
        url.hash || url.username || url.password || tripValues.length !== 1 ||
        [...url.searchParams.keys()].some((key) => key !== "trip") || !tripValues[0]) {
      return null;
    }
    return `${url.pathname}?trip=${encodeURIComponent(tripValues[0])}`;
  } catch {
    return null;
  }
}

function safeReconciliationHref(value: string | null, page?: number): string | null {
  if (!value) return null;
  try {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(value, origin);
    const trips = url.searchParams.getAll("trip");
    const pages = url.searchParams.getAll("page");
    if (url.origin !== origin || url.pathname !== "/api/google-ledger/expense-reconciliation" ||
        url.hash || url.username || url.password || trips.length !== 1 || !trips[0] ||
        pages.length !== 1 || !/^\d+$/.test(pages[0]) ||
        [...url.searchParams.keys()].some((key) => key !== "trip" && key !== "page")) return null;
    const nextPage = page ?? Number(pages[0]);
    if (!Number.isSafeInteger(nextPage) || nextPage < 1) return null;
    return `${url.pathname}?trip=${encodeURIComponent(trips[0])}&page=${nextPage}`;
  } catch {
    return null;
  }
}

function safeCopyHref(value: string | null): string | null {
  if (!value) return null;
  try {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(value, origin);
    const tabs = url.searchParams.getAll("tab");
    const kinds = url.searchParams.getAll("kind");
    const queries = url.searchParams.getAll("q");
    if (url.origin !== origin || url.pathname !== "/api/board/tsv" || url.hash || url.username || url.password ||
        tabs.length !== 1 || !tabs[0] || kinds.length !== 1 || kinds[0] !== "ex" || queries.length > 1 ||
        [...url.searchParams.keys()].some((key) => key !== "tab" && key !== "kind" && key !== "q")) return null;
    const params = new URLSearchParams({ tab: tabs[0], kind: "ex" });
    if (queries[0]) params.set("q", queries[0]);
    return `${url.pathname}?${params.toString()}`;
  } catch {
    return null;
  }
}

function safeReviewHref(value: string | null): string | null {
  if (!value) return null;
  try {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(value, origin);
    const tabs = url.searchParams.getAll("tab");
    if (url.origin !== origin || url.pathname !== "/board" || url.hash || url.username || url.password ||
        tabs.length !== 1 || !tabs[0] || [...url.searchParams.keys()].some((key) => key !== "tab")) return null;
    return `${url.pathname}?tab=${encodeURIComponent(tabs[0])}`;
  } catch {
    return null;
  }
}

function normalizeReconciliation(value: unknown): ReconciliationPayload {
  const payload = asRecord(value);
  const rawSource = asRecord(payload.source_info);
  const rawCounts = asRecord(payload.counts);
  const rawResults = Array.isArray(payload.results) ? payload.results : [];
  const results = rawResults.flatMap((raw): ReconciliationResult[] => {
    const row = asRecord(raw);
    const transaction_id = asText(row.transaction_id);
    if (!transaction_id) return [];
    const rawDifferences = asRecord(row.differences);
    const differences = Object.fromEntries(Object.entries(rawDifferences).flatMap(([field, values]) => {
      const pair = asRecord(values);
      return [[field, { manual: displaySafeValue(pair.manual), cost: displaySafeValue(pair.cost) }]];
    }));
    const rawRowNumber = row.row_number;
    return [{
      transaction_id,
      trip_id: asText(row.trip_id) ?? "",
      status: asText(row.status) ?? "SOURCE_UNAVAILABLE",
      status_label: asText(row.status_label) ?? "상태 확인 필요",
      date: asText(row.date) ?? "",
      merchant: asText(row.merchant) ?? "가맹점 정보 없음",
      category: asText(row.category) ?? "분류 없음",
      description: asText(row.description) ?? "",
      amount_krw: asMoney(row.amount_krw),
      currency: asText(row.currency) ?? "KRW",
      card: safeMaskedCard(row.card),
      sheet_id: asText(row.sheet_id) ?? "",
      source: asText(row.source) ?? "",
      row_number: typeof rawRowNumber === "number" && Number.isSafeInteger(rawRowNumber) && rawRowNumber > 0 ? rawRowNumber : null,
      basis: asStringList(row.basis),
      differences,
      reason: asText(row.reason) ?? "",
      user_corrected: row.user_corrected === true,
      correction_source: asText(row.correction_source) ?? "",
      review_href: asText(row.review_href),
    }];
  });
  const linksRevision = payload.links_revision;
  return {
    code: asText(payload.code) ?? "UNKNOWN",
    message: asText(payload.message) ?? "",
    trip_id: asText(payload.trip_id) ?? "",
    source_available: payload.source_available === true,
    source_info: {
      sheet_id: asText(rawSource.sheet_id) ?? "",
      source: asText(rawSource.source) ?? "",
      layout: asText(rawSource.layout) ?? "",
      synced_at: asText(rawSource.synced_at),
    },
    counts: Object.fromEntries(Object.entries(rawCounts).map(([key, count]) => [key,
      typeof count === "number" && Number.isSafeInteger(count) && count >= 0 ? count : 0,
    ])),
    results,
    total: nonNegativeInteger(payload.total),
    page: Math.max(1, nonNegativeInteger(payload.page) || 1),
    page_size: Math.max(1, nonNegativeInteger(payload.page_size) || 50),
    pages: Math.max(1, nonNegativeInteger(payload.pages) || 1),
    preview_digest: asText(payload.preview_digest) ?? "",
    source_digest: asText(payload.source_digest) ?? "",
    links_revision: typeof linksRevision === "number" && Number.isSafeInteger(linksRevision) && linksRevision >= 0 ? linksRevision : null,
  };
}

function displaySafeValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function safeMaskedCard(value: unknown): string {
  if (typeof value !== "string") return "카드 정보 없음";
  if (/^(?:••••|\*{4})\s*\d{4}$/.test(value.trim())) return value.trim();
  if (/^(?:카드 정보 없음|정보 없음|없음)$/.test(value.trim())) return "카드 정보 없음";
  return "카드 정보 없음";
}

function nonNegativeInteger(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

function syncActionFrom(actions: ActionDescriptor[]): ActionDescriptor | null {
  return actions.find((action) => action.id === "google-sync" &&
    action.method === "POST" && action.href === GOOGLE_SYNC_ENDPOINT &&
    action.encoding === "json" && action.csrf === "header" && action.response === "json") ?? null;
}

function newRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID().replaceAll("-", "");
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    return [...globalThis.crypto.getRandomValues(new Uint8Array(16))]
      .map((value) => value.toString(16).padStart(2, "0")).join("");
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.padEnd(32, "0").slice(0, 32);
}

function sourceStatus(status: GoogleSource): { label: string; explanation: string; tone: "success" | "warning" | "error" | "info" } {
  if (status.status === "ok" && !status.stale) {
    return { label: "정상", explanation: `최근 정상 확인 ${formatTime(status.last_ok_at)}`, tone: "success" };
  }
  if (status.status === "running") {
    return { label: "확인 중", explanation: "원본 상태를 다시 확인하고 있습니다.", tone: "info" };
  }
  if (status.status === "error") {
    return { label: "읽기 실패", explanation: "원본을 읽지 못했습니다. 새로 읽기 후 다시 확인해 주세요.", tone: "error" };
  }
  return { label: "확인 필요", explanation: status.stale ? "최근 정상 확인 값이 오래됐습니다." : "원본 상태를 확인하지 못했습니다.", tone: "warning" };
}

function OwnerOnly() {
  return (
    <main className="e-feature-page e-google-page">
      <section className="cost-panel e-feature-state" role="alert">
        <h1>관리 화면은 소유자 전용입니다</h1>
        <p>현재 계정에서 사용할 수 있는 관리 기능이 없습니다.</p>
      </section>
    </main>
  );
}

function ConnectionSummary({ data }: { data: GoogleData }) {
  const rows = Object.entries(data.sources);
  return (
    <section className="cost-panel e-google-source-panel" aria-labelledby="google-sources-heading">
      <div className="e-google-section-heading">
        <div>
          <h2 id="google-sources-heading">원본 동기화 상태</h2>
          <p>마지막 동기화 값과 원본별 확인 결과입니다.</p>
        </div>
        <p className="e-google-sync-time"><span>최근 동기화</span><strong>{formatTime(data.synced_at)}</strong></p>
      </div>
      {rows.length ? (
        <ul className="e-google-source-list">
          {rows.map(([source, raw]) => {
            const status = sourceStatus(raw);
            return (
              <li className={`e-google-source e-google-source-${status.tone}`} key={source}>
                <span className="e-google-source-name">{labelSource(source)}</span>
                <span className="e-google-source-state">{status.label}</span>
                <span className="e-google-source-explanation">{status.explanation}</span>
              </li>
            );
          })}
        </ul>
      ) : <p className="e-google-muted">확인된 원본 상태가 없습니다.</p>}
    </section>
  );
}

function SettingsSummary({ data }: { data: GoogleData }) {
  const { settings } = data;
  const hasSettings = settings.connections.length || settings.copy_choices.length || settings.viewer_grants.length;
  if (!hasSettings) {
    return (
      <section className="cost-panel e-google-settings-panel" aria-labelledby="google-settings-heading">
        <h2 id="google-settings-heading">현재 연결 설정</h2>
        <p className="e-google-muted">저장된 여행 연결이나 viewer 열람 허용이 없습니다.</p>
      </section>
    );
  }

  return (
    <section className="cost-panel e-google-settings-panel" aria-labelledby="google-settings-heading">
      <div className="e-google-section-heading">
        <div>
          <h2 id="google-settings-heading">현재 연결 설정</h2>
          <p>서버에 저장된 연결과 선택 상태를 읽기 전용으로 표시합니다.</p>
        </div>
        <span className="e-google-readonly-badge">읽기 전용</span>
      </div>
      <div className="e-google-settings-grid">
        <section aria-label="COST 여행 연결">
          <h3>COST 여행 연결</h3>
          {settings.connections.length ? <ul>
            {settings.connections.map((connection) => (
              <li key={`${connection.trip_key}-${connection.tab_id}`}>
                <span>{connection.trip_key}</span>
                <span aria-hidden="true">→</span>
                <span>{connection.tab_label ?? settings.tabs.find((tab) => tab.tab_id === connection.tab_id)?.label ?? connection.tab_id}</span>
              </li>
            ))}
          </ul> : <p className="e-google-muted">연결된 여행이 없습니다.</p>}
        </section>
        <section aria-label="선택된 Google 사본">
          <h3>선택된 Google 사본</h3>
          {settings.copy_choices.length ? <ul>
            {settings.copy_choices.map((choice) => (
              <li key={`${choice.trip_key}-${choice.source}`}>
                <span>{choice.trip_key}</span><span>{labelSource(choice.source)}</span>
              </li>
            ))}
          </ul> : <p className="e-google-muted">선택된 사본이 없습니다.</p>}
        </section>
        <section aria-label="viewer 열람 허용">
          <h3>viewer 열람 허용</h3>
          {settings.viewer_grants.length ? <ul>
            {settings.viewer_grants.map((grant) => (
              <li key={grant.user_id}>
                <span>{grant.user_id}</span><span>{grant.trip_keys.length}개 여행</span>
              </li>
            ))}
          </ul> : <p className="e-google-muted">열람을 허용한 viewer가 없습니다.</p>}
        </section>
      </div>
    </section>
  );
}

function connectedLabel(row: GoogleTrip, data: GoogleData): string {
  const connection = data.settings.connections.find((item) => item.trip_key === row.key);
  if (!row.connected_tab_id && !connection) return "연결 없음";
  const tabId = row.connected_tab_id ?? connection?.tab_id ?? null;
  return connection?.tab_label ?? (tabId ? data.settings.tabs.find((tab) => tab.tab_id === tabId)?.label : null) ?? "연결 확인 필요";
}

function selectedCopy(row: GoogleTrip, data: GoogleData): string {
  const source = row.chosen_source ?? data.settings.copy_choices.find((choice) => choice.trip_key === row.key)?.source ?? null;
  return source ? labelSource(source) : "선택 필요";
}

function reasonText(row: GoogleTrip): string {
  const reasons = [...new Set([...row.blocked_by, ...row.review])];
  if (reasons.length) return reasons.map(labelReason).join(" · ");
  return row.verified ? "확인 사항 없음" : "확인 사유를 제공하지 않았습니다.";
}

function closureLabel(row: GoogleTrip): string {
  if (row.closure === "closed") return row.closure_current ? "마감" : "마감 상태 확인 필요";
  if (row.closure === "open") return row.closure_current ? "미마감" : "마감 상태 확인 필요";
  return "상태 확인 중";
}

function tripCell(row: GoogleTrip, key: string): string {
  switch (key) {
    case "key": return row.key;
    case "kind": return row.kind === "quarter" ? "분기" : "여행";
    case "closure": return closureLabel(row);
    case "income_total": return formatMoney(row.income_total);
    case "expense_total": return formatMoney(row.expense_total);
    case "net": return formatMoney(row.net);
    case "verified": return row.verified ? "검증됨" : "미검증";
    case "review": return reasonText(row);
    default: return "";
  }
}

function displayColumns(payload: AdminResponse): Array<{ key: string; label: string }> {
  const columns = Array.isArray(payload.columns)
    ? payload.columns.filter((column) => column && typeof column.key === "string" && typeof column.label === "string")
    : [];
  return columns.length ? columns : [
    { key: "key", label: "Google 여행" },
    { key: "kind", label: "구분" },
    { key: "closure", label: "마감" },
    { key: "income_total", label: "수입" },
    { key: "expense_total", label: "지출" },
    { key: "net", label: "순수익" },
    { key: "verified", label: "검증" },
    { key: "review", label: "확인 사항" },
  ];
}

function CopyComparison({ row }: { row: GoogleTrip }) {
  const copies = Object.entries(row.copies);
  return (
    <details className="e-google-copy-details">
      <summary>사본 비교</summary>
      {copies.length ? (
        <ul className="e-google-copy-list">
          {copies.map(([source, copy]) => (
            <li key={source}>
              <div className="e-google-copy-heading">
                <strong>{labelSource(source)}</strong>
                <span>{!copy.present ? "자료 없음" : copy.verified ? "검증됨" : "미검증"}</span>
              </div>
              <dl>
                <div><dt>양식</dt><dd>{copy.layout ?? "확인 필요"}</dd></div>
                <div><dt>수입</dt><dd>{copy.present ? formatMoney(copy.income_total) : "자료 없음"}</dd></div>
                <div><dt>지출</dt><dd>{copy.present ? formatMoney(copy.expense_total) : "자료 없음"}</dd></div>
                <div><dt>확인 사항</dt><dd>{copy.flags.length ? copy.flags.map(labelReason).join(" · ") : "없음"}</dd></div>
              </dl>
            </li>
          ))}
        </ul>
      ) : <p className="e-google-muted">비교할 사본 자료가 없습니다.</p>}
    </details>
  );
}

function SourceLink({ row }: { row: GoogleTrip }) {
  const href = safeSourceHref(row.source_href);
  return href ? <a className="e-google-source-link" href={href}>원본 열기</a>
    : <span className="e-google-muted">원본 경로 없음</span>;
}

function TripActions({ row, active, copyPending, onOpen, onCopy }: {
  row: GoogleTrip;
  active: boolean;
  copyPending: boolean;
  onOpen: (row: GoogleTrip) => void;
  onCopy: (row: GoogleTrip) => void;
}) {
  const canReconcile = safeReconciliationHref(row.reconciliation_href) !== null;
  const canCopy = safeCopyHref(row.copy_href) !== null;
  return (
    <div className="e-google-card-actions">
      {canReconcile ? (
        <ActionButton variant="secondary" onClick={() => onOpen(row)} aria-expanded={active}>
          {active ? "상세 비교 숨기기" : "상세 비교 보기"}
        </ActionButton>
      ) : <span className="e-google-muted">비교 상세 경로 없음</span>}
      {canCopy ? (
        <ActionButton variant="secondary" onClick={() => onCopy(row)} disabled={copyPending}>
          {copyPending ? "TSV 준비 중…" : "Google 붙여넣기 복사"}
        </ActionButton>
      ) : <span className="e-google-muted">붙여넣기 경로 없음</span>}
    </div>
  );
}

function ComparisonTable({ rows, columns, data, selectedTripKey, copyPendingKey, onOpenReconciliation, onCopyTsv }: {
  rows: GoogleTrip[];
  columns: Array<{ key: string; label: string }>;
  data: GoogleData;
  selectedTripKey: string | null;
  copyPendingKey: string | null;
  onOpenReconciliation: (row: GoogleTrip) => void;
  onCopyTsv: (row: GoogleTrip) => void;
}) {
  return (
    <>
      <div className="e-google-table-wrap" role="region" aria-label="Google 장부 비교 표" tabIndex={0}>
        <table className="e-google-table">
          <caption className="cost-visually-hidden">Google 여행과 COST 연결, 금액, 검증 결과 비교</caption>
          <thead><tr>
            {columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}
            <th scope="col">COST 여행 연결</th>
            <th scope="col">선택 사본</th>
            <th scope="col">원본</th>
            <th scope="col">비교</th>
            <th scope="col">대조 상세·복사</th>
          </tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                {columns.map((column) => <td key={column.key} data-label={column.label}>
                  {column.key === "verified"
                    ? <span className={row.verified ? "e-google-verified" : "e-google-unverified"}>{tripCell(row, column.key)}</span>
                    : tripCell(row, column.key)}
                </td>)}
                <td data-label="COST 여행 연결">{connectedLabel(row, data)}</td>
                <td data-label="선택 사본">{selectedCopy(row, data)}</td>
                <td data-label="원본"><SourceLink row={row} /></td>
                <td data-label="비교"><CopyComparison row={row} /></td>
                <td data-label="대조 상세·복사"><TripActions row={row} active={selectedTripKey === row.key}
                  copyPending={copyPendingKey === row.key} onOpen={onOpenReconciliation} onCopy={onCopyTsv} /></td>
              </tr>
            ))}
            {!rows.length ? <tr><td colSpan={columns.length + 5}>비교할 Google 여행이 없습니다.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="e-google-trip-cards" aria-label="Google 여행 비교 카드">
        {rows.length ? rows.map((row) => (
          <article className="e-google-trip-card" key={row.key}>
            <header>
              <div><p className="e-google-eyebrow">{row.kind === "quarter" ? "분기" : "여행"}</p><h3>{row.key}</h3></div>
              <span className={row.verified ? "e-google-verified" : "e-google-unverified"}>{row.verified ? "검증됨" : "미검증"}</span>
            </header>
            <dl className="e-google-trip-metrics">
              <div><dt>마감</dt><dd>{closureLabel(row)}</dd></div>
              <div><dt>수입</dt><dd>{formatMoney(row.income_total)}</dd></div>
              <div><dt>지출</dt><dd>{formatMoney(row.expense_total)}</dd></div>
              <div><dt>순수익</dt><dd>{formatMoney(row.net)}</dd></div>
              <div><dt>COST 연결</dt><dd>{connectedLabel(row, data)}</dd></div>
              <div><dt>선택 사본</dt><dd>{selectedCopy(row, data)}</dd></div>
            </dl>
            <p className="e-google-card-reasons">{reasonText(row)}</p>
            <div className="e-google-card-actions"><SourceLink row={row} /><CopyComparison row={row} /></div>
            <TripActions row={row} active={selectedTripKey === row.key} copyPending={copyPendingKey === row.key}
              onOpen={onOpenReconciliation} onCopy={onCopyTsv} />
          </article>
        )) : <div className="cost-panel e-feature-state"><p>비교할 Google 여행이 없습니다.</p></div>}
      </div>
    </>
  );
}

const RECONCILIATION_COUNTS = [
  ["MATCHED_MANUAL", "수기 행과 일치"],
  ["MATCHED_EXISTING", "기존 연결과 일치"],
  ["NEW_EXPENSE", "새 지출"],
  ["REVIEW_CONFLICT", "차이 확인"],
  ["SOURCE_UNAVAILABLE", "원본 확인 불가"],
] as const;

function ReconciliationItem({ row, checked, onToggle }: {
  row: ReconciliationResult;
  checked: boolean;
  onToggle: (transactionId: string, selected: boolean) => void;
}) {
  const canLink = row.status === "MATCHED_MANUAL" && !row.user_corrected;
  const reviewHref = safeReviewHref(row.review_href);
  const differenceEntries = Object.entries(row.differences);
  return (
    <li className="e-google-reconciliation-item">
      <header>
        <div><p className="e-google-eyebrow">{row.date || "날짜 정보 없음"} · {row.category}</p>
          <h3>{row.merchant}</h3></div>
        <strong className={`e-google-recon-status e-google-recon-${row.status.toLowerCase()}`}>{row.status_label}</strong>
      </header>
      <dl>
        <div><dt>금액</dt><dd>{formatMoney(row.amount_krw)}</dd></div>
        <div><dt>카드</dt><dd>{row.card}</dd></div>
        {row.description ? <div><dt>설명</dt><dd>{row.description}</dd></div> : null}
        {row.row_number !== null ? <div><dt>원본 행</dt><dd>{row.row_number}</dd></div> : null}
        {row.user_corrected ? <div><dt>보호 상태</dt><dd>사용자 교정 보존{row.correction_source ? ` · ${row.correction_source}` : ""}</dd></div> : null}
      </dl>
      {row.reason ? <p className="e-google-recon-reason">{row.reason}</p> : null}
      {row.basis.length ? <p className="e-google-recon-basis">대조 근거: {row.basis.join(" · ")}</p> : null}
      {differenceEntries.length ? <dl className="e-google-recon-differences">
        {differenceEntries.map(([field, values]) => <div key={field}>
          <dt>{field} 차이</dt><dd>원본 {values.manual || "—"} · COST {values.cost || "—"}</dd>
        </div>)}
      </dl> : null}
      <div className="e-google-reconciliation-actions">
        {canLink ? <label className="e-google-link-check">
          <input type="checkbox" checked={checked} onChange={(event) => onToggle(row.transaction_id, event.currentTarget.checked)}
            aria-label={`${row.merchant} ${row.date} 연결 선택`} />
          <span>연결 대상으로 선택</span>
        </label> : row.status === "MATCHED_EXISTING"
          ? <span className="e-google-muted">이미 연결된 행</span>
          : row.user_corrected ? <span className="e-google-muted">사용자 교정 보호로 연결 제외</span>
          : <span className="e-google-muted">자동 연결 대상 아님</span>}
        {reviewHref ? <a href={reviewHref}>COST 행 보기</a> : null}
      </div>
    </li>
  );
}

function ReconciliationPanel({ row, bootstrap, onClose }: {
  row: GoogleTrip;
  bootstrap: Bootstrap;
  onClose: () => void;
}) {
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<ReconciliationState>({ kind: "loading" });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [linkPending, setLinkPending] = useState(false);
  const [exportPending, setExportPending] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [fallbackTsv, setFallbackTsv] = useState("");
  const linkRequestId = useRef<string | null>(null);
  const exportRequestId = useRef<string | null>(null);
  const baseHref = safeReconciliationHref(row.reconciliation_href);

  useEffect(() => {
    if (!baseHref) {
      setState({ kind: "error", message: "서버가 제공한 대조 경로를 확인하지 못했습니다." });
      return;
    }
    const href = safeReconciliationHref(baseHref, page);
    if (!href) {
      setState({ kind: "error", message: "대조 요청 주소를 확인하지 못했습니다." });
      return;
    }
    const controller = new AbortController();
    let active = true;
    setState({ kind: "loading" });
    getJSON<unknown>(href, controller.signal)
      .then((result) => { if (active) setState({ kind: "ready", payload: normalizeReconciliation(result) }); })
      .catch((error: unknown) => {
        if (active && !(error instanceof DOMException && error.name === "AbortError")) {
          setState({ kind: "error", message: featureError(error) });
        }
      });
    return () => { active = false; controller.abort(); };
  }, [baseHref, page, reload]);

  function changePage(nextPage: number) {
    setSelectedIds([]);
    setNotice(null);
    setFallbackTsv("");
    linkRequestId.current = null;
    exportRequestId.current = null;
    setPage(nextPage);
  }

  function refreshDetails() {
    setSelectedIds([]);
    setNotice(null);
    setFallbackTsv("");
    linkRequestId.current = null;
    exportRequestId.current = null;
    setReload((value) => value + 1);
  }

  function toggleSelected(transactionId: string, selected: boolean) {
    setSelectedIds((current) => {
      if (!selected) return current.filter((id) => id !== transactionId);
      if (current.includes(transactionId) || current.length >= 50) return current;
      return [...current, transactionId];
    });
    setNotice(null);
  }

  async function linkSelected() {
    if (state.kind !== "ready" || !state.payload.source_available || !state.payload.preview_digest ||
        state.payload.links_revision === null || !selectedIds.length || selectedIds.length > 50 || linkPending) return;
    const requestId = linkRequestId.current ?? `links:${newRequestId()}`;
    linkRequestId.current = requestId;
    setLinkPending(true);
    setNotice({ tone: "info", title: "연결 메타데이터를 저장하고 있습니다." });
    try {
      const result = await postJSON<Record<string, unknown>>("/api/google-ledger/expense-reconciliation", {
        trip_id: state.payload.trip_id,
        action: "links",
        scope: "all",
        transaction_ids: selectedIds,
        request_id: requestId,
        expected_revision: state.payload.links_revision,
        preview_digest: state.payload.preview_digest,
        query: "",
        kind: "",
      }, bootstrap.csrf);
      if (asText(result.code) && result.code !== "OK") {
        throw new ApiError(asText(result.code) ?? "LINK_SAVE_FAILED", 0, asText(result.message) ?? "연결을 저장하지 못했습니다.");
      }
      setNotice({ tone: "success", title: "연결 메타데이터를 저장했습니다.",
        message: asText(result.message) ?? "Google 시트는 변경하지 않았습니다." });
      linkRequestId.current = null;
      setSelectedIds([]);
      setReload((value) => value + 1);
    } catch (error) {
      setNotice({ tone: "error", title: "연결을 저장하지 못했습니다.", message: featureError(error) });
    } finally {
      setLinkPending(false);
    }
  }

  async function exportAndCopy() {
    if (state.kind !== "ready" || !state.payload.source_available || !state.payload.preview_digest ||
        state.payload.links_revision === null || exportPending) return;
    const requestId = exportRequestId.current ?? `export:${newRequestId()}`;
    exportRequestId.current = requestId;
    setExportPending(true);
    setFallbackTsv("");
    setNotice({ tone: "info", title: "최신 대조 결과로 TSV를 준비하고 있습니다." });
    try {
      const result = await postJSON<Record<string, unknown>>("/api/google-ledger/expense-reconciliation", {
        trip_id: state.payload.trip_id,
        action: "export",
        scope: "all",
        transaction_ids: [],
        request_id: requestId,
        expected_revision: state.payload.links_revision,
        preview_digest: state.payload.preview_digest,
        query: "",
        kind: "",
      }, bootstrap.csrf);
      if (asText(result.code) && result.code !== "OK") {
        throw new ApiError(asText(result.code) ?? "EXPORT_FAILED", 0, asText(result.message) ?? "TSV를 준비하지 못했습니다.");
      }
      if (typeof result.tsv !== "string") throw new ApiError("INVALID_EXPORT_RESPONSE", 0, "서버가 복사할 TSV를 반환하지 않았습니다.");
      exportRequestId.current = null;
      const count = nonNegativeInteger(result.row_count);
      const total = formatMoney(asMoney(result.total_krw));
      try {
        if (!navigator.clipboard?.writeText) throw new Error("클립보드를 사용할 수 없습니다.");
        await navigator.clipboard.writeText(result.tsv);
        setNotice({ tone: "success", title: "대조 TSV를 복사했습니다.",
          message: `${count}건 · 합계 ${total}. Google 시트에 붙여넣으세요. 시트에는 아직 입력되지 않았습니다.` });
      } catch {
        setFallbackTsv(result.tsv);
        setNotice({ tone: "warning", title: "대조 TSV를 준비했습니다.",
          message: `${count}건 · 합계 ${total}. 아래 텍스트를 직접 복사해 Google 시트에 붙여넣으세요.` });
      }
    } catch (error) {
      setNotice({ tone: "error", title: "대조 TSV를 준비하지 못했습니다.", message: featureError(error) });
    } finally {
      setExportPending(false);
    }
  }

  const payload = state.kind === "ready" ? state.payload : null;
  return (
    <section className="cost-panel e-google-reconciliation" aria-labelledby="google-reconciliation-heading">
      <div className="e-google-section-heading">
        <div><h2 id="google-reconciliation-heading">{row.key} 지출 대조</h2>
          <p>서버가 마스킹한 카드 정보와 확인된 대조 상태입니다. 원본 거래를 수정하지 않습니다.</p></div>
        <div className="e-google-reconciliation-toolbar">
          <ActionButton variant="secondary" onClick={refreshDetails} disabled={state.kind === "loading"}>대조 새로고침</ActionButton>
          <ActionButton variant="secondary" onClick={onClose}>닫기</ActionButton>
        </div>
      </div>
      {notice ? <InlineNotice tone={notice.tone} title={notice.title}>{notice.message}</InlineNotice> : null}
      {state.kind === "loading" ? <p role="status">지출 대조 결과를 불러오는 중…</p> : null}
      {state.kind === "error" ? <InlineNotice tone="error" title="지출 대조 결과를 불러오지 못했습니다." action={{ label: "다시 시도", onClick: refreshDetails }}>
        {state.message}</InlineNotice> : null}
      {payload ? <>
        {!payload.source_available ? <InlineNotice tone="warning" title="Google 원본 대조를 사용할 수 없습니다.">
          {payload.message || "최신 시트 원본을 확인할 수 없어 연결이나 복사를 진행할 수 없습니다."}
        </InlineNotice> : null}
        <p className="e-google-reconciliation-source">
          대조 원본: {payload.source_info.source ? labelSource(payload.source_info.source) : "확인 필요"}
          {payload.source_info.layout ? ` · 양식 ${payload.source_info.layout}` : ""}
          {payload.source_info.synced_at ? ` · 동기화 ${formatTime(payload.source_info.synced_at)}` : ""}
        </p>
        <dl className="e-google-reconciliation-summary">
          {RECONCILIATION_COUNTS.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{payload.counts[key] ?? 0}</dd></div>)}
        </dl>
        <div className="e-google-reconciliation-toolbar">
          <ActionButton onClick={linkSelected} pending={linkPending} pendingLabel="저장 중"
            disabled={!payload.source_available || !selectedIds.length || payload.links_revision === null || !payload.preview_digest}>
            선택 항목 연결{selectedIds.length ? ` (${selectedIds.length})` : ""}
          </ActionButton>
          <ActionButton variant="secondary" onClick={exportAndCopy} pending={exportPending} pendingLabel="TSV 준비 중"
            disabled={!payload.source_available || payload.links_revision === null || !payload.preview_digest}>
            대조 결과 TSV 복사
          </ActionButton>
          <span className="e-google-muted">복사는 서버가 검증한 내용을 클립보드로 전달합니다. Google 시트에 자동 입력하지 않습니다.</span>
        </div>
        {fallbackTsv ? <label className="e-google-tsv-fallback" htmlFor="google-reconciliation-tsv">
          <span>복사할 TSV</span><textarea id="google-reconciliation-tsv" value={fallbackTsv} readOnly />
        </label> : null}
        {payload.results.length ? <ul className="e-google-reconciliation-list">
          {payload.results.map((result) => <ReconciliationItem key={result.transaction_id} row={result}
            checked={selectedIds.includes(result.transaction_id)} onToggle={toggleSelected} />)}
        </ul> : <p className="e-google-muted">이 페이지에 표시할 지출 대조 행이 없습니다.</p>}
        <div className="e-google-pagination">
          <span>{payload.total}건 · {payload.page} / {payload.pages}페이지</span>
          <div>
            <ActionButton variant="secondary" onClick={() => changePage(payload.page - 1)} disabled={payload.page <= 1 || state.kind === "loading"}>이전</ActionButton>
            <ActionButton variant="secondary" onClick={() => changePage(payload.page + 1)} disabled={payload.page >= payload.pages || state.kind === "loading"}>다음</ActionButton>
          </div>
        </div>
      </> : null}
    </section>
  );
}

function syncRequestValues(action: ActionDescriptor): Record<string, ActionValue> {
  return action.fields?.some((field) => field.name === "client_request_id")
    ? { client_request_id: newRequestId() }
    : {};
}

export function GooglePage({ bootstrap }: PageProps) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<NoticeState | null>(null);
  const [selectedTrip, setSelectedTrip] = useState<GoogleTrip | null>(null);
  const [copyPendingKey, setCopyPendingKey] = useState<string | null>(null);
  const [copyNotice, setCopyNotice] = useState<NoticeState | null>(null);
  const [clipboardFallback, setClipboardFallback] = useState("");

  useEffect(() => {
    if (bootstrap.role !== "owner") return;
    const controller = new AbortController();
    let active = true;
    setState({ kind: "loading" });
    getJSON<AdminResponse>(GOOGLE_ENDPOINT, controller.signal)
      .then((payload) => { if (active) setState({ kind: "ready", payload }); })
      .catch((error: unknown) => {
        if (active && !(error instanceof DOMException && error.name === "AbortError")) {
          setState({ kind: "error", message: featureError(error) });
        }
      });
    return () => { active = false; controller.abort(); };
  }, [bootstrap.role, attempt]);

  const payload = state.kind === "ready" ? state.payload : null;
  const data = useMemo(() => normalizeGoogleData(payload?.data), [payload]);
  const rows = useMemo(() => normalizeTrips(payload?.rows), [payload]);
  const columns = useMemo(() => payload ? displayColumns(payload) : [], [payload]);
  const syncAction = useMemo(() => payload ? syncActionFrom(payload.actions ?? []) : null, [payload]);
  const refresh = () => {
    setSyncNotice(null);
    setCopyNotice(null);
    setClipboardFallback("");
    setSelectedTrip(null);
    setState({ kind: "loading" });
    setAttempt((value) => value + 1);
  };

  function openReconciliation(row: GoogleTrip) {
    if (!safeReconciliationHref(row.reconciliation_href)) return;
    setCopyNotice(null);
    setClipboardFallback("");
    setSelectedTrip((current) => current?.key === row.key ? null : row);
  }

  async function copyBoardTsv(row: GoogleTrip) {
    const href = safeCopyHref(row.copy_href);
    if (!href || bootstrap.role !== "owner" || copyPendingKey) return;
    setCopyPendingKey(row.key);
    setCopyNotice({ tone: "info", title: "서버에서 붙여넣기 TSV를 준비하고 있습니다." });
    setClipboardFallback("");
    try {
      const result = await getJSON<Record<string, unknown>>(href);
      if (typeof result.tsv !== "string") throw new ApiError("INVALID_TSV_RESPONSE", 0, "서버가 복사할 TSV를 반환하지 않았습니다.");
      const rowCount = nonNegativeInteger(result.row_count);
      try {
        if (!navigator.clipboard?.writeText) throw new Error("클립보드를 사용할 수 없습니다.");
        await navigator.clipboard.writeText(result.tsv);
        setClipboardFallback("");
        setCopyNotice({ tone: "success", title: "Google 붙여넣기 TSV를 복사했습니다.",
          message: `${rowCount}건을 복사했습니다. Google 시트에 붙여넣으세요. 시트에는 아직 입력되지 않았습니다.` });
      } catch {
        setClipboardFallback(result.tsv);
        setCopyNotice({ tone: "warning", title: "Google 붙여넣기 TSV를 준비했습니다.",
          message: `${rowCount}건을 아래 텍스트에서 직접 복사해 Google 시트에 붙여넣으세요.` });
      }
    } catch (error) {
      setCopyNotice({ tone: "error", title: "Google 붙여넣기 TSV를 준비하지 못했습니다.", message: featureError(error) });
    } finally {
      setCopyPendingKey(null);
    }
  }

  async function startSync() {
    if (!syncAction || syncAction.disabled || syncing) return;
    setSelectedTrip(null);
    setSyncing(true);
    setSyncNotice({ tone: "info", title: "Google 장부 새로 읽기를 요청하고 있습니다." });
    try {
      const result = await executeAction<Record<string, unknown>>(
        syncAction,
        syncRequestValues(syncAction),
        bootstrap.csrf,
      );
      if (result.kind !== "json") throw new ApiError("INVALID_SYNC_RESPONSE", 0, "동기화 응답 형식이 올바르지 않습니다.");
      const body = asRecord(result.data);
      const status = asText(body.status);
      const message = asText(body.message);
      if (status === "error" || status === "failed") {
        setSyncNotice({ tone: "error", title: "Google 장부를 새로 읽지 못했습니다.", message: message ?? "원본 상태를 확인하고 다시 시도해 주세요." });
      } else if (status === "done" || status === "success") {
        setSyncNotice({ tone: "success", title: "Google 장부 새로 읽기를 완료했습니다.", message: message ?? undefined });
      } else {
        setSyncNotice({ tone: "info", title: "새로 읽기 요청을 시작했습니다.", message: message ?? "완료 여부는 원본별 확인 결과와 최근 동기화 시각에서 확인할 수 있습니다." });
      }
      setAttempt((value) => value + 1);
    } catch (error) {
      setSyncNotice({ tone: "error", title: "새로 읽기 요청을 보내지 못했습니다.", message: featureError(error) });
    } finally {
      setSyncing(false);
    }
  }

  if (bootstrap.role !== "owner") return <OwnerOnly />;

  const connectionNotice = !data.enabled
    ? { tone: "warning" as const, title: "Google 장부 연결이 설정되지 않았습니다.", message: "연결을 변경하는 기능은 현재 사용할 수 없습니다." }
    : !data.available
      ? { tone: "warning" as const, title: "동기화 자료를 확인할 수 없습니다.", message: asText(payload?.status?.message) ?? "정상 동기화 자료를 아직 읽지 못했습니다. 새로 읽기 후 다시 확인해 주세요." }
      : null;

  return (
    <main className="e-feature-page e-google-page">
      <FeatureNav label="관리 화면" items={ADMIN_NAV} current="google" />
      <header className="e-feature-header e-google-header">
        <div>
          <p className="e-google-eyebrow">관리 · 읽기 전용</p>
          <h1>Google 장부 비교·복사</h1>
          <p>서버가 확인한 합계와 사본별 검증 상태를 비교합니다. 이 화면은 Google 장부를 변경하지 않습니다.</p>
        </div>
        <div className="e-google-toolbar">
          <ActionButton variant="secondary" onClick={refresh} disabled={state.kind === "loading"}>
            상태 새로고침
          </ActionButton>
          {syncAction ? (
            <ActionButton onClick={startSync} pending={syncing} pendingLabel="새로 읽는 중" disabled={Boolean(syncAction.disabled)}>
              {syncAction.label || "Google 장부 새로 읽기"}
            </ActionButton>
          ) : <span className="e-google-muted">새로 읽기 동작을 사용할 수 없습니다.</span>}
        </div>
      </header>

      {syncAction?.disabled ? <InlineNotice tone="warning" title="새로 읽기를 사용할 수 없습니다.">{syncAction.reason ?? "Google 연결 설정을 확인해 주세요."}</InlineNotice> : null}
      {syncNotice ? <InlineNotice tone={syncNotice.tone} title={syncNotice.title}>{syncNotice.message}</InlineNotice> : null}
      {copyNotice ? <InlineNotice tone={copyNotice.tone} title={copyNotice.title}>{copyNotice.message}</InlineNotice> : null}
      {clipboardFallback ? <label className="e-google-tsv-fallback" htmlFor="google-board-tsv">
        <span>복사할 TSV</span><textarea id="google-board-tsv" value={clipboardFallback} readOnly />
      </label> : null}

      {state.kind === "loading" ? <div className="cost-panel e-feature-loading" role="status">Google 비교 자료를 불러오는 중…</div> : null}
      {state.kind === "error" ? (
        <InlineNotice tone="error" title="Google 비교 자료를 불러오지 못했습니다." action={{ label: "다시 시도", onClick: refresh }}>
          {state.message}
        </InlineNotice>
      ) : null}
      {state.kind === "ready" ? (
        <>
          {connectionNotice ? <InlineNotice tone={connectionNotice.tone} title={connectionNotice.title}>{connectionNotice.message}</InlineNotice> : null}
          <ConnectionSummary data={data} />
          <SettingsSummary data={data} />
          {data.available ? (
            <section className="cost-panel e-google-comparison" aria-labelledby="google-comparison-heading">
              <div className="e-google-section-heading">
                <div>
                  <h2 id="google-comparison-heading">여행별 비교</h2>
                  <p>검증되지 않은 금액은 서버가 전달하지 않은 상태 그대로 표시합니다.</p>
                </div>
                <span className="e-google-readonly-badge">금액·원본 읽기 전용</span>
              </div>
              <ComparisonTable rows={rows} columns={columns} data={data} selectedTripKey={selectedTrip?.key ?? null}
                copyPendingKey={copyPendingKey} onOpenReconciliation={openReconciliation} onCopyTsv={copyBoardTsv} />
              {selectedTrip ? <ReconciliationPanel key={selectedTrip.key} row={selectedTrip} bootstrap={bootstrap}
                onClose={() => setSelectedTrip(null)} /> : null}
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
