import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { ApiError, executeAction, getJSON, type ActionResult, type ActionValue } from "../../api/client";
import type { ActionDescriptor, Bootstrap, FieldDescriptor } from "../../api/types";
import "./feature.css";

export type PageProps = {
  bootstrap: Bootstrap;
  path: string;
  search: URLSearchParams;
};

type Column = { key: string; label: string };
export type FeaturePayload = {
  title: string;
  columns?: Column[];
  rows?: Array<Record<string, unknown>>;
  fields?: FieldDescriptor[];
  actions: ActionDescriptor[];
  status?: { code?: string; message?: string };
  data?: Record<string, unknown>;
};

type ResourceState<T> =
  | { kind: "loading" }
  | { kind: "error"; message: string; retry: number }
  | { kind: "ready"; payload: T; refresh: number };

export function featureError(error: unknown): string {
  if (error instanceof ApiError) return error.message || error.code;
  if (error instanceof Error) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export function useResource<T>(url: string) {
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<ResourceState<T>>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setState({ kind: "loading" });
    getJSON<T>(url, controller.signal)
      .then((payload) => {
        if (active) setState((previous) => ({
          kind: "ready",
          payload,
          refresh: previous.kind === "ready" ? previous.refresh : 0,
        }));
      })
      .catch((error: unknown) => {
        if (active && !(error instanceof DOMException && error.name === "AbortError")) {
          setState({ kind: "error", message: featureError(error), retry });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [url, retry]);

  const reload = () => setRetry((value) => value + 1);
  return { state, reload };
}

function uiHref(path: string, params?: URLSearchParams) {
  const pathname = `/ui${path.startsWith("/") ? path : `/${path}`}`;
  return params && [...params.keys()].length ? `${pathname}?${params.toString()}` : pathname;
}

export function FeatureNav({
  label,
  items,
  current,
}: {
  label: string;
  items: Array<{ id: string; label: string; path: string; query?: Record<string, string> }>;
  current: string;
}) {
  return (
    <nav className="e-feature-nav" aria-label={label}>
      {items.map((item) => {
        const params = new URLSearchParams(item.query);
        return (
          <a
            key={item.id}
            href={uiHref(item.path, params)}
            className="cost-tab"
            aria-current={item.id === current ? "page" : undefined}
          >
            {item.label}
          </a>
        );
      })}
    </nav>
  );
}

function FieldControl({ field, bootstrap, requestId }: {
  field: FieldDescriptor;
  bootstrap: Bootstrap;
  requestId: string;
}) {
  const id = useId();
  const inputId = `${id}-${field.name.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const readOnly = Boolean(field.read_only);
  const required = Boolean(field.required) && !readOnly;
  const common = {
    id: inputId,
    name: field.name,
    required,
    disabled: readOnly,
    "aria-required": required || undefined,
  };
  const stringValue = field.value == null ? "" : String(field.value);

  if (field.type === "hidden" && field.multiple && field.name === "tab_ids") {
    const options = field.options?.length
      ? field.options
      : bootstrap.trips.map((trip) => ({ value: trip.id, label: trip.title }));
    return (
      <fieldset className="e-feature-fieldset" disabled={readOnly}>
        <legend>{field.label}{required ? <span aria-hidden="true"> *</span> : null}</legend>
        {options.length ? (
          <div className="e-feature-choice-list">
            {options.map((option, index) => (
              <label className="e-feature-check" key={`${option.value}-${index}`}>
                <input
                  type="checkbox"
                  name={field.name}
                  value={option.value}
                  defaultChecked={stringValue === option.value}
                  disabled={readOnly}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        ) : (
          <p className="e-feature-hint">내보낼 수 있는 여행이 없습니다.</p>
        )}
      </fieldset>
    );
  }

  if (field.type === "hidden") {
    const hiddenValue = field.name === "client_request_id" && !stringValue.trim()
      ? requestId
      : stringValue;
    return <input type="hidden" name={field.name} value={hiddenValue} readOnly />;
  }
  if (field.type === "checkbox") {
    if (field.multiple && field.options?.length) {
      return (
        <fieldset className="e-feature-fieldset" disabled={readOnly}>
          <legend>{field.label}{required ? <span aria-hidden="true"> *</span> : null}</legend>
          <div className="e-feature-choice-list">
            {field.options.map((option, index) => (
              <label className="e-feature-check" key={`${option.value}-${index}`}>
                <input
                  type="checkbox"
                  name={field.name}
                  value={option.value}
                  defaultChecked={stringValue === option.value}
                  disabled={readOnly}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      );
    }
    const checked = field.value === true || field.value === 1 || field.value === "1" || field.value === "true";
    return (
      <label className="e-feature-check" htmlFor={inputId}>
        <input {...common} type="checkbox" value="1" defaultChecked={checked} />
        <span>{field.label}</span>
      </label>
    );
  }
  if (field.type === "select") {
    return (
      <label className="e-feature-field" htmlFor={inputId}>
        <span>{field.label}{required ? <span aria-hidden="true"> *</span> : null}</span>
        <select
          {...common}
          multiple={field.multiple || undefined}
          defaultValue={field.multiple ? (stringValue ? [stringValue] : []) : stringValue}
        >
          {!field.multiple ? <option value="">선택하세요</option> : null}
          {(field.options ?? []).map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
    );
  }

  const exactMoneyText = field.type === "number" && /(amount|money|금액)/i.test(field.name);
  const type = field.type === "number" && exactMoneyText
    ? "text"
    : field.type === "number" || field.type === "date" || field.type === "file"
    ? field.type
    : "text";
  return (
    <label className="e-feature-field" htmlFor={inputId}>
      <span>{field.label}{required ? <span aria-hidden="true"> *</span> : null}</span>
      <input
        {...common}
        type={type}
        defaultValue={type === "file" ? undefined : stringValue}
        inputMode={exactMoneyText ? "decimal" : undefined}
        accept={type === "file" ? field.accept : undefined}
        multiple={type === "file" ? field.multiple : undefined}
        readOnly={readOnly && type !== "file"}
        autoComplete="off"
      />
    </label>
  );
}

const EXACT_NON_API_ACTION_PATHS = new Set([
  "/access/applications",
  "/access/decision",
  "/access/logout",
]);

function validActionPath(href: string): string | null {
  if (typeof href !== "string" || href.startsWith("//")) return null;
  try {
    const url = new URL(href, window.location.origin);
    if (url.origin !== window.location.origin || url.username || url.password || url.hash) return null;
    const allowed = url.pathname.startsWith("/api/") || EXACT_NON_API_ACTION_PATHS.has(url.pathname);
    return allowed ? `${url.pathname}${url.search}` : null;
  } catch {
    return null;
  }
}

type ActionReply = {
  message?: string;
  code?: string;
  ok?: boolean;
  success?: boolean;
  status?: { code?: string; message?: string };
  [key: string]: unknown;
};

function responseData(result: ActionResult<ActionReply>): ActionReply | null {
  return result.kind === "json" ? result.data : null;
}

function downloadBlob(blob: Blob, label: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = label;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function actionMessage(reply: ActionReply) {
  return reply.message || reply.status?.message || "요청이 완료되었습니다.";
}

function clientRequestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function ActionForm({
  action,
  bootstrap,
  fallbackFields,
  onComplete,
}: {
  action: ActionDescriptor;
  bootstrap: Bootstrap;
  fallbackFields?: FieldDescriptor[];
  onComplete: (message: string) => void;
}) {
  const [state, setState] = useState<{ busy: boolean; error: string }>({ busy: false, error: "" });
  const [requestId, setRequestId] = useState(clientRequestId);
  const href = validActionPath(action.href);
  const fields = action.fields?.length ? action.fields : fallbackFields ?? [];
  const tripIdsUnavailable = fields.some((field) =>
    field.name === "tab_ids" && field.type === "hidden" && field.multiple &&
    !field.options?.length && bootstrap.trips.length === 0);
  const disabled = Boolean(action.disabled) || state.busy || !href || tripIdsUnavailable;
  const effectiveAction = fields === action.fields ? action : { ...action, fields };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || !href) return;
    const form = event.currentTarget;
    const formData = new FormData(form);
    setState({ busy: true, error: "" });
    try {
      const values: Record<string, ActionValue> = {};
      for (const field of fields) {
        if (field.read_only) continue;
        if (field.name === "client_request_id" && field.type === "hidden") {
          const submitted = formData.get(field.name);
          const value = typeof submitted === "string" ? submitted.trim() : "";
          values[field.name] = value || requestId;
        } else if (field.type === "hidden" && field.multiple) {
          values[field.name] = formData.getAll(field.name)
            .filter((value): value is string => typeof value === "string" && value !== "");
        } else if (field.type === "hidden") {
          const submitted = formData.get(field.name);
          values[field.name] = typeof submitted === "string" ? submitted : field.value ?? "";
        } else if (field.type === "checkbox") {
          values[field.name] = field.multiple
            ? formData.getAll(field.name).filter((value): value is string => typeof value === "string")
            : formData.has(field.name);
        } else if (field.type === "file") {
          const files = formData.getAll(field.name).filter((value): value is File => value instanceof File && value.size > 0);
          values[field.name] = field.multiple ? files : files[0] ?? null;
        } else {
          const entries = formData.getAll(field.name).filter((value): value is string => typeof value === "string");
          if (field.multiple) values[field.name] = entries;
          else if (entries.length > 1) values[field.name] = entries;
          else if (entries.length === 1) values[field.name] = entries[0];
        }
        if (field.required) {
          const value = values[field.name];
          const missing = value == null ||
            (Array.isArray(value) && (value.length === 0 || value.every((item) => String(item).trim() === ""))) ||
            (typeof value === "string" && value.trim() === "") ||
            (field.type === "checkbox" && !field.multiple && value === false);
          if (missing) throw new Error(`${field.label} 항목을 입력하거나 선택해 주세요.`);
        }
      }
      const result = await executeAction<ActionReply>(effectiveAction, values, bootstrap.csrf);
      if (result.kind === "redirect") {
        setRequestId(clientRequestId());
        setState({ busy: false, error: "" });
        onComplete(`서버가 다음 경로를 요청했습니다: ${result.location}`);
        return;
      }
      if (result.kind === "blob") {
        downloadBlob(result.blob, action.label);
        setState({ busy: false, error: "" });
        onComplete("서버가 파일을 반환해 다운로드를 시작했습니다.");
        return;
      }
      const reply = responseData(result);
      if (!reply) throw new Error("서버가 구조화된 결과를 반환하지 않았습니다. 최신 상태를 다시 불러와 확인해 주세요.");
      if (reply.ok === false || reply.success === false || reply.status?.code === "FAILED" || reply.status?.code === "ERROR") {
        throw new Error(reply.message || reply.status?.message || reply.code || "서버에서 요청을 완료하지 못했습니다.");
      }
      if (reply.client_must_clear === true || reply.logged_out === true) {
        window.location.assign("/auth/login");
        return;
      }
      const message = actionMessage(reply);
      setRequestId(clientRequestId());
      setState({ busy: false, error: "" });
      onComplete(message);
    } catch (error) {
      setState({ busy: false, error: featureError(error) });
    }
  }

  return (
    <form className="e-feature-action" onSubmit={submit}>
      {fields.map((field) => (
        <FieldControl
          key={`${field.name}-${field.type}`}
          field={field}
          bootstrap={bootstrap}
          requestId={requestId}
        />
      ))}
      <button type="submit" className="cost-button cost-button-secondary" disabled={disabled}>
        {state.busy ? "처리 중…" : action.label}
      </button>
      {action.disabled && action.reason ? <p className="e-feature-hint">{action.reason}</p> : null}
      {!href ? <p className="e-feature-error">허용된 내부 주소가 아니어서 동작을 비활성화했습니다.</p> : null}
      {state.error ? <p className="e-feature-error" role="alert">{state.error}</p> : null}
    </form>
  );
}

function displayValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(displayValue).join(", ");
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key}: ${displayValue(item)}`)
    .join(" · ");
}

function isMoneyColumn(column: Column) {
  return /(amount|money|total|income|expense|profit|금액|합계|수입|지출|차액)/i.test(`${column.key} ${column.label}`);
}

export function DataRows({ payload }: { payload: FeaturePayload }) {
  const columns = payload.columns ?? [];
  const rows = payload.rows ?? [];
  if (!columns.length && !rows.length && !payload.data && !payload.fields?.length) return null;
  if (columns.length && rows.length) {
    return (
      <>
        <div className="e-feature-table-wrap" role="region" aria-label={`${payload.title} 표`} tabIndex={0}>
          <table className="e-feature-table">
            <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id ?? row.row_id ?? row.transaction_id ?? index)}>
                  {columns.map((column) => (
                    <td key={column.key} className={isMoneyColumn(column) ? "e-feature-money" : undefined}>
                      {displayValue(row[column.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="e-feature-mobile-list" aria-label={`${payload.title} 목록`}>
          {rows.map((row, index) => (
            <li className="e-feature-mobile-card" key={String(row.id ?? row.row_id ?? row.transaction_id ?? index)}>
              {columns.map((column) => (
                <div className="e-feature-mobile-line" key={column.key}>
                  <span>{column.label}</span>
                  <strong className={isMoneyColumn(column) ? "e-feature-money" : undefined}>
                    {displayValue(row[column.key])}
                  </strong>
                </div>
              ))}
            </li>
          ))}
        </ul>
      </>
    );
  }
  if (rows.length) {
    return (
      <ul className="e-feature-record-list">
        {rows.map((row, index) => (
          <li key={String(row.id ?? row.row_id ?? index)}>
            {Object.entries(row).map(([key, value]) => (
              <div className="e-feature-record-line" key={key}>
                <span>{key}</span><strong>{displayValue(value)}</strong>
              </div>
            ))}
          </li>
        ))}
      </ul>
    );
  }
  if (payload.data) {
    return (
      <dl className="e-feature-record-list">
        {Object.entries(payload.data).map(([key, value]) => (
          <div className="e-feature-record-line" key={key}>
            <dt>{key}</dt><dd>{displayValue(value)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  if (payload.fields?.length) {
    return (
      <dl className="e-feature-record-list">
        {payload.fields.filter((field) => field.type !== "hidden").map((field) => (
          <div className="e-feature-record-line" key={field.name}>
            <dt>{field.label}</dt><dd>{displayValue(field.value)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return null;
}

function isUnavailable(payload: FeaturePayload) {
  return payload.data?.available === false || payload.status?.code === "SOURCE_UNAVAILABLE" ||
    payload.status?.code === "NOT_CONFIGURED" || payload.status?.code === "CONNECTION_REQUIRED";
}

export function FeatureActionPanel({
  actions,
  fields,
  bootstrap,
  onRefresh,
  onNotice,
}: {
  actions: ActionDescriptor[];
  fields?: FieldDescriptor[];
  bootstrap: Bootstrap;
  onRefresh: () => void;
  onNotice: (message: string) => void;
}) {
  if (!actions.length) return null;
  return (
    <section className="e-feature-actions" aria-label="사용 가능한 동작">
      <h2>동작</h2>
      <div className="e-feature-action-grid">
        {actions.map((action) => (
          <ActionForm
            key={action.id}
            action={action}
            bootstrap={bootstrap}
            fallbackFields={actions.length === 1 ? fields : undefined}
            onComplete={(message) => {
              onNotice(message);
              if (action.method === "POST") onRefresh();
            }}
          />
        ))}
      </div>
    </section>
  );
}

export function StructuredFeaturePage({
  bootstrap,
  endpoint,
  pageTitle,
  nav,
  currentNav,
  readOnly = false,
  hideReviewWrites = false,
  hideParticipantCreation = false,
  hideClassificationDecisions = false,
}: {
  bootstrap: Bootstrap;
  endpoint: string;
  pageTitle: string;
  nav?: Array<{ id: string; label: string; path: string; query?: Record<string, string> }>;
  currentNav?: string;
  readOnly?: boolean;
  hideReviewWrites?: boolean;
  hideParticipantCreation?: boolean;
  hideClassificationDecisions?: boolean;
}) {
  const { state, reload } = useResource<FeaturePayload>(endpoint);
  const [notice, setNotice] = useState("");
  const canWrite = !readOnly && bootstrap.role === "owner";
  const payload = state.kind === "ready" ? state.payload : null;
  const actions = useMemo(() => (payload?.actions ?? []).filter((action) => {
    if (action.method === "POST" && !canWrite) return false;
    const target = `${action.id} ${action.href}`.toLowerCase();
    if (hideReviewWrites && /\/api\/review\/(decisions|apply)(\/|\?|$)/.test(target)) return false;
    if (hideParticipantCreation && /participant.*create|create.*participant|new-participant/i.test(target)) return false;
    if (hideClassificationDecisions && /\/api\/classification\/(dialog|conversation)(\/|\?|$)/.test(target)) return false;
    return true;
  }), [payload, canWrite, hideReviewWrites, hideParticipantCreation, hideClassificationDecisions]);

  return (
    <main className="e-feature-page">
      <header className="e-feature-header">
        <div><p className="e-feature-eyebrow">COST · 업무 도구</p><h1>{payload?.title || pageTitle}</h1></div>
        <button type="button" className="cost-button cost-button-quiet" onClick={() => { setNotice(""); reload(); }}>
          새로고침
        </button>
      </header>
      {nav && currentNav ? <FeatureNav label={pageTitle} items={nav} current={currentNav} /> : null}
      {notice ? <p className="e-feature-notice" role="status">{notice}</p> : null}

      {state.kind === "loading" ? <p className="cost-panel e-feature-loading" role="status">자료를 불러오는 중입니다…</p> : null}
      {state.kind === "error" ? (
        <section className="cost-panel e-feature-state" role="alert">
          <h2>자료를 불러오지 못했습니다</h2>
          <p>{state.message}</p>
          <button type="button" className="cost-button" onClick={reload}>다시 불러오기</button>
        </section>
      ) : null}
      {payload ? (
        <>
          {payload.status?.message ? (
            <p className={isUnavailable(payload) ? "e-feature-error" : "e-feature-status"}
               role={isUnavailable(payload) ? "alert" : "status"}>
              {payload.status.message}
            </p>
          ) : null}
          {isUnavailable(payload) ? (
            <section className="cost-panel e-feature-state">
              <h2>자료를 사용할 수 없습니다</h2>
              <p>{payload.status?.message || "자료 원천이 연결되지 않았습니다."}</p>
            </section>
          ) : null}
          <DataRows payload={payload} />
          {!isUnavailable(payload) && !(payload.rows?.length) && !(payload.data && Object.keys(payload.data).length) && !(payload.fields?.length) ? (
            <section className="cost-panel e-feature-state">
              <h2>표시할 자료가 없습니다</h2>
              <p>{payload.status?.message || "현재 조건에 맞는 자료가 없습니다."}</p>
            </section>
          ) : null}
          <FeatureActionPanel
            actions={actions}
            fields={payload.fields}
            bootstrap={bootstrap}
            onRefresh={reload}
            onNotice={setNotice}
          />
        </>
      ) : null}
    </main>
  );
}

export function transactionPath(view: string) {
  return view === "ota" ? "/ota" : view === "refunds" ? "/board" :
    view === "flights" ? "/flight-passengers" : "/cards/all";
}

export function transactionView(path: string, search: URLSearchParams) {
  if (path === "/ota") return "ota";
  if (path === "/flight-passengers") return "flights";
  if (path === "/board" && search.get("tab") === "refunds") return "refunds";
  return search.get("view") || "cards";
}

export function withQuery(path: string, values: Record<string, string>) {
  const params = new URLSearchParams(values);
  return uiHref(path, params);
}

export function pagePath(props: PageProps) {
  return props.path.startsWith("/") ? props.path : `/${props.path}`;
}
