import { useEffect, useState, type FormEvent } from "react";
import { ApiError, executeAction, getJSON, type ActionResult, type ActionValue } from "../../api/client";
import type { ActionDescriptor } from "../../api/types";
import { FeatureNav, type PageProps, featureError } from "../transactions/feature-ui";

type AnyRecord = Record<string, unknown>;
type ExportJob = AnyRecord & { job_id?: string; status?: string; status_checked?: boolean };
type ExportPayload = { title?: string; actions: ActionDescriptor[]; status?: { code?: string; message?: string } };
type TsvResult = {
  tsv?: string;
  row_count?: number;
  total_krw?: string | number;
  held?: unknown[];
  source_available?: boolean;
  tab_id?: string;
  [key: string]: unknown;
};

const countFormatter = new Intl.NumberFormat("ko-KR");

function asRecord(value: unknown): AnyRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

function scalar(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function newRequestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message || error.code;
  if (error instanceof Error) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export function buildXlsxActionValues(tabIds: string[], requestId: string): Record<string, ActionValue> {
  return { tab_ids: [...tabIds], client_request_id: requestId };
}

export function exportJobStatusUrl(jobId: string): string {
  return `/api/exports/${encodeURIComponent(jobId)}`;
}

export function exportDownloadHref(job: { job_id?: unknown; status?: unknown }): string | null {
  if (job.status !== "ready" || typeof job.job_id !== "string" || !job.job_id.trim()) return null;
  return `/api/exports/${encodeURIComponent(job.job_id)}/download`;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "파일 준비 완료",
    queued: "대기 중",
    running: "파일 만드는 중",
    started: "파일 만드는 중",
    failed: "생성 실패",
    cancelled: "취소됨",
  };
  return labels[status] || (status ? "상태 확인 중" : "상태 정보 없음");
}

async function jsonResult<T>(result: ActionResult<T>): Promise<T> {
  if (result.kind !== "json") throw new Error("서버가 JSON 결과를 반환하지 않았습니다.");
  const value = result.data as AnyRecord;
  if (value.ok === false || value.success === false || asRecord(value.status).code === "FAILED") {
    throw new Error(scalar(value.message) || scalar(asRecord(value.status).message) || scalar(value.code) || "요청을 완료하지 못했습니다.");
  }
  return result.data;
}

export function ExportPage({ bootstrap, search, nav }: PageProps & { nav: Array<{ id: string; label: string; path: string; query?: Record<string, string> }> }) {
  const [payload, setPayload] = useState<ExportPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedTrips, setSelectedTrips] = useState<string[]>(() => bootstrap.trips.map((trip) => trip.id));
  const [tsvTrip, setTsvTrip] = useState(search.get("trip") || search.get("tab") || bootstrap.trips[0]?.id || "");
  const [requestId, setRequestId] = useState(newRequestId);
  const [job, setJob] = useState<ExportJob | null>(null);
  const [tsv, setTsv] = useState<TsvResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const tripParam = search.get("trip") || search.get("tab");
  const viewQuery = new URLSearchParams({ view: "export" });
  if (tripParam) viewQuery.set("trip", tripParam);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    getJSON<ExportPayload>(`/api/plush/auxiliary?${viewQuery.toString()}`, controller.signal)
      .then((value) => setPayload(value))
      .catch((loadError: unknown) => { if (!(loadError instanceof DOMException && loadError.name === "AbortError")) setError(featureError(loadError)); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [tripParam]);

  const xlsxAction = payload?.actions.find((action) => action.id === "exports-xlsx" || action.href === "/api/exports/xlsx");
  const tsvAction = payload?.actions.find((action) => action.id === "board-tsv" || action.href === "/api/board/tsv");
  const downloadHref = job?.status_checked ? exportDownloadHref(job) : null;
  const selectedCount = selectedTrips.length;

  useEffect(() => {
    const jobId = scalar(job?.job_id);
    const currentStatus = scalar(job?.status);
    if (!jobId || !job?.status_checked || !["queued", "running", "started"].includes(currentStatus)) return;
    const timer = window.setTimeout(() => {
      void refreshJob(jobId);
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [job]);

  async function refreshJob(jobId: string) {
    try {
      const next = await getJSON<ExportJob>(exportJobStatusUrl(jobId));
      setJob({ ...next, status_checked: true });
    } catch (jobError) {
      setError(errorMessage(jobError));
    }
  }

  function setTripSelection(next: string[]) {
    setSelectedTrips(next);
    setRequestId(newRequestId());
    setJob(null);
  }

  async function generateXlsx(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!xlsxAction || !selectedTrips.length || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    setJob(null);
    try {
      const result = await executeAction<ExportJob>(xlsxAction, buildXlsxActionValues(selectedTrips, requestId), bootstrap.csrf);
      const created = await jsonResult(result);
      const jobId = scalar(created.job_id);
      if (!jobId) throw new Error("내보내기 응답에 작업 ID가 없습니다.");
      const checked = await getJSON<ExportJob>(exportJobStatusUrl(jobId));
      setJob({ ...checked, status_checked: true });
      setRequestId(newRequestId());
      setNotice(scalar(checked.message) || statusLabel(scalar(checked.status)));
    } catch (actionError) {
      setError(errorMessage(actionError));
    } finally {
      setBusy(false);
    }
  }

  async function loadTsv() {
    if (!tsvAction || !tsvTrip || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const url = new URL(tsvAction.href, window.location.origin);
      url.searchParams.set("tab", tsvTrip);
      const result = await executeAction<TsvResult>({ ...tsvAction, href: `${url.pathname}${url.search}` }, {}, bootstrap.csrf);
      setTsv(await jsonResult(result));
    } catch (actionError) {
      setError(errorMessage(actionError));
      setTsv(null);
    } finally {
      setBusy(false);
    }
  }

  async function copyTsv() {
    if (!tsv?.tsv) return;
    try {
      await navigator.clipboard.writeText(tsv.tsv);
      setNotice("TSV를 클립보드에 복사했습니다. Google 시트에 붙여넣을 수 있습니다.");
    } catch {
      setNotice("아래 TSV 내용을 선택해 복사한 뒤 Google 시트에 붙여넣으세요.");
    }
  }

  const navWithTrip = nav.map((item) => item.id === "export" && tripParam
    ? { ...item, query: { ...item.query, trip: tripParam } }
    : item);

  return (
    <main className="e-feature-page e-export-page">
      <header className="e-feature-header">
        <div><p className="e-feature-eyebrow">COST · 업무 도구</p><h1>{payload?.title || "장부 내보내기"}</h1></div>
        <button type="button" className="cost-button cost-button-quiet" disabled={loading || busy} onClick={() => window.location.reload()}>새로고침</button>
      </header>
      {navWithTrip.length ? <FeatureNav label="보조 기능 메뉴" items={navWithTrip} current="export" /> : null}
      {notice ? <p className="e-feature-notice" role="status">{notice}</p> : null}
      {error ? <p className="e-feature-error" role="alert">{error}</p> : null}
      {loading ? <p className="cost-panel e-feature-loading" role="status">내보내기 기능을 불러오는 중입니다…</p> : null}

      <section className="cost-panel e-export-section">
        <h2>XLSX 파일 만들기</h2>
        <p>여행을 선택하면 내보내기 작업을 만들고, 서버 상태를 확인한 뒤 준비된 파일을 받을 수 있습니다.</p>
        <form onSubmit={generateXlsx}>
          <fieldset className="e-feature-fieldset">
            <legend>내보낼 여행</legend>
            {bootstrap.trips.length ? (
              <>
                <div className="e-export-select-all">
                  <button type="button" className="cost-button cost-button-quiet" disabled={busy}
                    onClick={() => setTripSelection(bootstrap.trips.map((trip) => trip.id))}>전체 선택</button>
                  <button type="button" className="cost-button cost-button-quiet" disabled={busy}
                    onClick={() => setTripSelection([])}>선택 해제</button>
                  <span role="status">{selectedCount}개 선택</span>
                </div>
                <div className="e-feature-choice-list">
                  {bootstrap.trips.map((trip) => (
                    <label className="e-feature-check" key={trip.id}>
                      <input type="checkbox" value={trip.id} checked={selectedTrips.includes(trip.id)} disabled={busy}
                        onChange={(event) => setTripSelection(event.currentTarget.checked
                          ? [...selectedTrips, trip.id]
                          : selectedTrips.filter((id) => id !== trip.id))} />
                      <span>{trip.title}</span>
                    </label>
                  ))}
                </div>
              </>
            ) : <p className="e-feature-hint">내보낼 수 있는 여행이 없습니다.</p>}
          </fieldset>
          <button type="submit" className="cost-button" disabled={busy || loading || !xlsxAction || !selectedCount}>
            {busy ? "처리 중…" : "XLSX 만들기"}
          </button>
          {!xlsxAction && !loading ? <p className="e-feature-error">XLSX 내보내기 동작을 사용할 수 없습니다.</p> : null}
        </form>
        {job ? (
          <section className="e-export-job" aria-label="XLSX 작업 상태">
            <h3>내보내기 상태</h3>
            <dl className="e-feature-record-list">
              <div className="e-feature-record-line"><dt>상태</dt><dd role="status">{statusLabel(scalar(job.status))}</dd></div>
              {Array.isArray(job.tabs) ? <div className="e-feature-record-line"><dt>여행 수</dt><dd>{countFormatter.format(job.tabs.length)}개</dd></div> : null}
            </dl>
            {downloadHref ? <a className="cost-button" href={downloadHref}>XLSX 파일 다운로드</a> : (
              <p className="e-feature-hint">파일은 서버 상태가 준비 완료로 바뀌면 받을 수 있습니다.</p>
            )}
            {job.status_checked ? <button type="button" className="cost-button cost-button-secondary" disabled={busy}
              onClick={() => void refreshJob(scalar(job.job_id))}>상태 다시 확인</button> : null}
          </section>
        ) : null}
      </section>

      <section className="cost-panel e-export-section">
        <h2>여행별 TSV 복사</h2>
        <p>TSV를 복사해 Google 시트에 붙여넣을 수 있습니다. 장부에 자동으로 기록하지 않습니다.</p>
        <label className="e-feature-field"><span>여행</span>
          <select value={tsvTrip} onChange={(event) => { setTsvTrip(event.currentTarget.value); setTsv(null); }} disabled={busy}>
            {bootstrap.trips.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}
          </select>
        </label>
        <button type="button" className="cost-button cost-button-secondary" disabled={busy || !tsvAction || !tsvTrip}
          onClick={() => void loadTsv()}>{busy ? "처리 중…" : "TSV 불러오기"}</button>
        {!tsvAction && !loading ? <p className="e-feature-error">TSV 내보내기 동작을 사용할 수 없습니다.</p> : null}
        {tsv ? (
          <div className="e-export-tsv">
            {tsv.source_available === false ? <p className="e-feature-error" role="alert">연결된 원천을 확인할 수 없어 TSV를 만들지 않았습니다.</p> : null}
            <dl className="e-feature-record-list">
              <div className="e-feature-record-line"><dt>내보낼 행</dt><dd>{countFormatter.format(Number(tsv.row_count) || 0)}행</dd></div>
              {tsv.total_krw != null ? <div className="e-feature-record-line"><dt>합계</dt><dd>{scalar(tsv.total_krw)}원</dd></div> : null}
              {Array.isArray(tsv.held) && tsv.held.length > 0
                ? <div className="e-feature-record-line"><dt>대조 후 복사 제외</dt><dd>{countFormatter.format(tsv.held.length)}건</dd></div>
                : null}
            </dl>
            <label className="e-feature-field"><span>TSV 내용</span>
              <textarea readOnly value={tsv.tsv || ""} rows={Math.min(14, Math.max(4, (tsv.tsv || "").split("\n").length))} />
            </label>
            <button type="button" className="cost-button" disabled={!tsv.tsv} onClick={() => void copyTsv()}>TSV 복사</button>
          </div>
        ) : null}
      </section>
    </main>
  );
}
