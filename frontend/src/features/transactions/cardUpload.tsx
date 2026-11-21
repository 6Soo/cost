import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import type { Bootstrap } from "../../api/types";

const UPLOAD_URL = "/api/imports/upload-batch";
const STATUS_URL = /^\/api\/imports\/upload-status\/[a-f0-9]{32}$/;
const BATCH_ID = /^batch-[a-f0-9]{24}$/;
const JOB_KEY = "cost-card-upload-job";
const MAX_FILES = 100;
const MAX_TOTAL_BYTES = 99 * 1024 * 1024;
const MAX_TRANSIENT_FAILURES = 5;
const GAP_DATE = /^\d{4}-\d{2}-\d{2}$/;

export type CardUploadJob = {
  filename?: string;
  batch_id: string;
  status_url: string;
};

export type CardBatchDetail = {
  summary?: { status?: string; row_count?: number; error_count?: number; counts?: Record<string, number> };
  [key: string]: unknown;
};

type JobState = {
  state: "pending" | "saved" | "server-error" | "unknown";
  message: string;
};

type CardUploadProps = { bootstrap: Bootstrap; search: URLSearchParams };

const isUnknownStatusMessage = (message: string): boolean =>
  /처리 상태를 확인하지 못했습니다|저장된 파일의 처리 결과를 확인|파일은 저장됐지만/.test(message);

function readStoredJobs(storage: Storage): CardUploadJob[] {
  let raw: string | null = null;
  try {
    raw = storage.getItem(JOB_KEY);
  } catch {
    return [];
  }
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    const list = Array.isArray(parsed) ? parsed : parsed ? [parsed] : [];
    return list.filter((job): job is CardUploadJob => {
      if (!job || typeof job !== "object") return false;
      const record = job as Record<string, unknown>;
      return typeof record.status_url === "string" && STATUS_URL.test(record.status_url) &&
        typeof record.batch_id === "string" && BATCH_ID.test(record.batch_id);
    });
  } catch {
    return [];
  }
}

function storeJobs(storage: Storage, jobs: CardUploadJob[]): void {
  try {
    if (jobs.length) storage.setItem(JOB_KEY, JSON.stringify(jobs));
    else storage.removeItem(JOB_KEY);
  } catch {
    // Durable batch state still answers through /api/imports/<batch_id>.
  }
}

function messageFromError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json();
    if (payload && typeof payload === "object") {
      const record = payload as Record<string, any>;
      return String(record.message || record.code || fallback);
    }
  } catch {
    // fall through to the legacy-compatible message
  }
  return fallback;
}

function uploadOutcome(result: Record<string, any>): string {
  const downloaded = result.recovered_upload === true;
  const summary = (result.upload_summary || (downloaded ? result.recovery : undefined)) as
    Record<string, any> | undefined;
  const count = summary?.transaction_count ?? summary?.unique_transactions ?? summary?.saved_count;
  const duplicate = summary?.duplicate_count ?? summary?.duplicate_rows ?? summary?.duplicates;
  let outcome = downloaded ? "저장된 결과 조회 완료" : "처리 완료";
  if (Number.isFinite(Number(count))) outcome += ` · 거래 ${Number(count).toLocaleString("ko-KR")}건 저장`;
  if (Number.isFinite(Number(duplicate))) outcome += ` · 중복 ${Number(duplicate).toLocaleString("ko-KR")}건`;
  return outcome;
}

function gapContext(search: URLSearchParams): { card: string; start: string; end: string } | null {
  const card = search.get("gap_card") ?? "";
  const start = search.get("gap_start") ?? "";
  const end = search.get("gap_end") ?? "";
  if (!card || !GAP_DATE.test(start) || !GAP_DATE.test(end)) return null;
  return { card, start, end };
}

function batchHref(search: URLSearchParams, batchId: string): string {
  const params = new URLSearchParams(search);
  params.delete("legacy");
  params.set("panel", "upload");
  params.set("batch", batchId);
  params.delete("review");
  return `/cards/all?${params.toString()}`;
}

async function pollStatus(job: CardUploadJob, signal?: AbortSignal): Promise<Record<string, any>> {
  let failures = 0;
  for (;;) {
    let response: Response;
    try {
      response = await fetch(job.status_url, { cache: "no-store", credentials: "same-origin", signal });
    } catch {
      failures += 1;
      if (failures >= MAX_TRANSIENT_FAILURES) {
        throw new Error("저장된 처리 상태를 확인하지 못했습니다. 다시 조회하거나 처리 결과를 확인해 주세요.");
      }
      await wait(Math.min(10_000, failures ? 1_000 * 2 ** failures : 1_500));
      continue;
    }
    if (response.status === 401 || response.status === 403) {
      throw new Error("로그인 또는 업로드 권한을 확인해 주세요.");
    }
    if (response.status === 404) {
      let recovered: Record<string, any>;
      try {
        const saved = await fetch(`${job.status_url}?batch=${encodeURIComponent(job.batch_id)}`,
          { cache: "no-store", credentials: "same-origin", signal });
        if (!saved.ok) throw new Error(await errorMessage(saved, "업로드 처리 상태를 다시 확인해 주세요."));
        recovered = (await saved.json()) as Record<string, any>;
      } catch (error) {
        throw new Error(messageFromError(error, "업로드 처리 상태를 다시 확인해 주세요."));
      }
      if (recovered.status !== "saved" || recovered.result?.batch_id !== job.batch_id ||
          typeof recovered.result?.recovery?.pending !== "boolean") {
        throw new Error("저장된 파일의 처리 결과를 확인하고 있습니다. 처리 결과에서 다시 확인해 주세요.");
      }
      if (recovered.result.recovery.pending) {
        throw new Error("파일은 저장됐지만 처리 결과를 확인할 수 없습니다. 처리 결과에서 다시 확인해 주세요.");
      }
      return { ...(recovered.result as Record<string, any>), recovered_upload: true };
    }
    if (!response.ok) {
      failures += 1;
      if (failures >= MAX_TRANSIENT_FAILURES) {
        throw new Error("저장된 처리 상태를 확인하지 못했습니다. 다시 조회하거나 처리 결과를 확인해 주세요.");
      }
      await wait(Math.min(10_000, failures ? 1_000 * 2 ** failures : 1_500));
      continue;
    }
    let state: Record<string, any>;
    try {
      state = (await response.json()) as Record<string, any>;
    } catch {
      throw new Error("응답을 읽지 못했습니다. 페이지를 새로고침해 다시 확인해 주세요.");
    }
    if (state.status === "done") return (state.result || {}) as Record<string, any>;
    if (state.status === "error") {
      throw new Error(String(state.message || "파일 처리에 실패했습니다. 저장된 파일의 결과를 확인해 주세요."));
    }
    failures = 0;
    await wait(Math.min(10_000, failures ? 1_000 * 2 ** failures : 1_500));
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function CardUploadPanel({ bootstrap, search }: CardUploadProps) {
  const [stored, setStored] = useState<CardUploadJob[]>([]);
  const [states, setStates] = useState<Record<string, JobState>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(0);
  const [batchDetail, setBatchDetail] = useState<CardBatchDetail | null>(null);
  const [batchFailed, setBatchFailed] = useState(false);
  const storedRef = useRef<CardUploadJob[]>([]);
  const statesRef = useRef<Record<string, JobState>>({});
  const controller = useRef<AbortController | null>(null);
  const owner = bootstrap.role === "owner";

  const remember = useCallback((jobs: CardUploadJob[]) => {
    storedRef.current = jobs;
    setStored(jobs);
  }, []);

  const updateState = useCallback((statusUrl: string, state: JobState["state"], message: string) => {
    const next = { ...statesRef.current, [statusUrl]: { state, message } };
    statesRef.current = next;
    setStates(next);
  }, []);

  const persistQueue = useCallback(() => {
    // Only resumable jobs stay in the queue: finished and terminally failed
    // entries remain visible in the panel but are not re-polled on reload.
    const failed = new Set(Object.entries(statesRef.current)
      .filter(([, state]) => state.state === "saved" || state.state === "server-error")
      .map(([statusUrl]) => statusUrl));
    storeJobs(window.localStorage, storedRef.current.filter((job) => !failed.has(job.status_url)));
  }, []);

  useEffect(() => {
    controller.current?.abort();
    const active = new AbortController();
    controller.current = active;
    return () => active.abort();
  }, []);

  useEffect(() => {
    if (!owner) return;
    const saved = readStoredJobs(window.localStorage);
    if (!saved.length) return;
    remember(saved);
    let cancelled = false;
    (async () => {
      for (const job of saved) {
        if (cancelled) return;
        try {
          const result = await pollStatus(job, controller.current?.signal);
          if (!cancelled) updateState(job.status_url, "saved", uploadOutcome(result));
          persistQueue();
        } catch (error) {
          if (!cancelled) updateState(job.status_url, "unknown", messageFromError(error, "상태를 확인하지 못했습니다."));
          persistQueue();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [owner, persistQueue, remember, updateState]);

  useEffect(() => {
    if (!owner) return;
    const batchId = search.get("batch") ?? "";
    if (!BATCH_ID.test(batchId)) return;
    let cancelled = false;
    setBatchDetail(null);
    setBatchFailed(false);
    (async () => {
      try {
        const response = await fetch(`/api/imports/${encodeURIComponent(batchId)}`, {
          cache: "no-store", credentials: "same-origin", signal: controller.current?.signal,
        });
        if (!response.ok) throw new Error(await errorMessage(response, "요청을 처리하지 못했습니다."));
        if (!cancelled) setBatchDetail((await response.json()) as CardBatchDetail);
      } catch {
        if (!cancelled) { setBatchDetail(null); setBatchFailed(true); }
      }
    })();
    return () => { cancelled = true; };
  }, [owner, search]);

  function selectFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    setSelected(files.length);
    if (files.length > MAX_FILES || files.reduce((sum, file) => sum + file.size, 0) > MAX_TOTAL_BYTES) {
      setNotice("한 번에 100개, 전체 99MB 이하로 나누어 선택해 주세요.");
    } else {
      setNotice("");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !owner) return;
    const input = event.currentTarget.elements.namedItem("files") as HTMLInputElement | null;
    const files = Array.from(input?.files ?? []);
    if (!files.length) {
      setNotice("업로드할 카드 파일을 선택해 주세요.");
      input?.focus();
      return;
    }
    setBusy(true);
    setNotice(`${files.length}개 파일을 안전하게 접수하고 있습니다. 접수 완료까지 이 페이지를 유지해 주세요.`);
    try {
      const body = new FormData();
      for (const file of files) body.append("files", file);
      const response = await fetch(UPLOAD_URL, {
        method: "POST", cache: "no-store", credentials: "same-origin",
        headers: { "X-CSRF-Token": bootstrap.csrf }, body,
      });
      if (!response.ok) {
        throw new Error(await errorMessage(response, "요청을 처리하지 못했습니다. 다시 시도해 주세요."));
      }
      const received = (await response.json()) as { files?: unknown };
      const list = Array.isArray(received.files) ? received.files : [];
      if (list.length !== files.length) {
        throw new Error("접수 결과를 확인하지 못했습니다. 저장된 카드 파일 목록에서 상태를 다시 확인해 주세요.");
      }
      const accepted: CardUploadJob[] = [];
      const rejected: string[] = [];
      for (const item of list) {
        if (item && typeof item === "object") {
          const record = item as Record<string, unknown>;
          if (typeof record.status_url === "string" && STATUS_URL.test(record.status_url) &&
              typeof record.batch_id === "string" && BATCH_ID.test(record.batch_id)) {
            accepted.push({ filename: typeof record.filename === "string" ? record.filename : undefined,
              batch_id: record.batch_id, status_url: record.status_url });
          } else {
            rejected.push(typeof record.filename === "string" ? record.filename : "이름 없는 원본");
          }
        } else {
          rejected.push("이름 없는 원본");
        }
      }
      const next = [...storedRef.current.filter((job) => !accepted.some((added) => added.status_url === job.status_url)), ...accepted];
      remember(next);
      persistQueue();
      for (const filename of rejected) {
        updateState("rejected:" + filename, "server-error", `${filename} 처리 결과를 확인하지 못했습니다.`);
      }
      setNotice(`${accepted.length}개 파일 접수 완료 · 분류가 백그라운드에서 진행됩니다.`);
      if (input) input.value = "";
      setSelected(0);
      for (const job of accepted) {
        try {
          const result = await pollStatus(job);
          updateState(job.status_url, "saved", uploadOutcome(result));
          persistQueue();
        } catch (error) {
          const message = messageFromError(error, "처리 상태를 확인하지 못했습니다.");
          updateState(job.status_url, isUnknownStatusMessage(message) ? "unknown" : "server-error", message);
          persistQueue();
        }
      }
      setNotice("");
    } catch (error) {
      setNotice(messageFromError(error, "요청을 처리하지 못했습니다. 다시 시도해 주세요."));
    } finally {
      setBusy(false);
    }
  }

  if (!owner) {
    return (
      <section className="cost-panel e-feature-state" role="alert">
        <h2>카드 파일 업로드는 소유자 전용입니다</h2>
        <p>현재 계정에서 사용할 수 있는 카드 자료가 없습니다.</p>
      </section>
    );
  }

  const gap = gapContext(search);

  return (
    <section className="cost-panel e-feature-state" aria-labelledby="card-upload-heading">
      <header className="e-feature-header">
        <div>
          <p className="e-feature-eyebrow">COST · 카드</p>
          <h2 id="card-upload-heading">카드 파일 업로드</h2>
          <p>카드 명세서 파일을 올리면 원본을 저장한 뒤 백그라운드에서 분류합니다.</p>
        </div>
      </header>

      {gap ? (
        <p className="e-feature-notice" role="status">
          {gap.card ? `${gap.card} · ` : "카드사"} 파일 조회기간 사이 {gap.start} ~ {gap.end} 자료를 추가합니다. 업로드 뒤
          거래일자 공백을 다시 계산합니다.
        </p>
      ) : null}

      <form onSubmit={submit}>
        <label className="e-feature-field">
          <span>카드 명세서 파일 (.xls, .xlsx, .csv)</span>
          <input type="file" name="files" multiple accept=".xls,.xlsx,.csv" onChange={selectFiles} />
        </label>
        <button type="submit" className="cost-button" disabled={busy}>
          {busy ? "접수 중…" : "카드 파일 업로드"}
        </button>
        {selected ? <span className="e-feature-hint">{selected}개 파일 선택</span> : null}
      </form>

      {notice ? <p className="e-feature-status" role="status">{notice}</p> : null}

      {stored.length ? (
        <ul className="e-feature-record-list">
          {stored.map((job) => {
            const state = states[job.status_url];
            return (
              <li className="e-feature-record-line" key={job.status_url}>
                <strong>{job.filename || "이름 없는 원본"}</strong>
                <span className="e-feature-hint">{state?.message || "처리 상태를 확인하고 있습니다."}</span>
                {state?.state === "saved" ? <span className="e-feature-status">처리됨</span> : null}
                {state?.state === "server-error" || state?.state === "unknown" ? <span className="e-feature-error">확인 필요</span> : null}
                {BATCH_ID.test(job.batch_id) ? (
                  <a className="e-feature-hint" href={batchHref(search, job.batch_id)}
                    aria-label={(job.filename || "이름 없는 원본") + " 처리 결과"}>
                    처리 결과
                  </a>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {Object.values(states).some((state) => state.state === "server-error") &&
        !Object.keys(states).some((key) => stored.some((job) => job.status_url === key)) ? (
        <ul className="e-feature-record-list">
          {Object.entries(states)
            .filter(([key]) => !stored.some((job) => job.status_url === key))
            .map(([, state]) => (
              <li className="e-feature-record-line" key={"rejected-" + state.message}>
                <span className="e-feature-error">{state.message}</span>
              </li>
            ))}
        </ul>
      ) : null}

      {batchDetail ? (
        <section className="cost-panel" aria-label="파일 처리 결과">
          <h3>파일 처리 결과</h3>
          {typeof batchDetail.summary?.row_count === "number" ? (
            <p className="e-feature-hint">
              처리 행 {batchDetail.summary.row_count}
              {typeof batchDetail.summary?.error_count === "number" ? ` · 처리 오류 ${batchDetail.summary.error_count}` : ""}
            </p>
          ) : null}
          <p className="e-feature-hint">
            원본 저장·거래 분류·거래일자 공백 계산 상태를 함께 표시합니다. 거래일자는 카드 거래 원행에서 읽어 카드사별
            일자 공백 현황에 반영합니다.
          </p>
          {typeof batchDetail.summary?.status === "string" ? (
            <p className="e-feature-hint">처리 상태: {batchDetail.summary.status}</p>
          ) : null}
        </section>
      ) : null}

      {batchFailed ? (
        <p className="e-feature-error" role="alert">파일 처리 결과를 확인하지 못했습니다. 해당 원본을 다시 확인해 주세요.</p>
      ) : null}
    </section>
  );
}
