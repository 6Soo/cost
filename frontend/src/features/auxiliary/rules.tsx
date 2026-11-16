import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, getJSON, postJSON } from "../../api/client";
import { FeatureNav, type PageProps } from "../transactions/feature-ui";

type AnyRecord = Record<string, unknown>;
type RulesViewProps = PageProps & {
  nav: Array<{ id: string; label: string; path: string; query?: Record<string, string> }>;
};

type LoadState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; dialog: AnyRecord; conversation: AnyRecord; rule: AnyRecord | null };

type PreviewState = AnyRecord & { apply_existing: boolean; apply_future: boolean };

const CONDITION_LABELS: Record<string, string> = {
  merchant_normalized: "가맹점",
  merchant: "가맹점",
  card_kind: "카드 구분",
  direction: "지출 방향",
  item: "항목",
  display_tab_id: "여행",
  category: "분류",
  pay_method: "결제 수단",
  amount_krw: "금액",
};

function asRecord(value: unknown): AnyRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

function rows(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function scalar(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(scalar).filter(Boolean).join(", ");
  return "";
}

function stateLabel(value: unknown): string {
  const text = scalar(value);
  const labels: Record<string, string> = {
    not_started: "시작 전",
    open: "진행 중",
    closed: "닫힘",
    one_off: "이 사례에만 적용",
    not_found: "대화 없음",
    queued: "대기 중",
    running: "처리 중",
    answered: "초안 도착",
    failed: "실패",
    timed_out: "시간 초과",
    abandoned: "종료됨",
    pending: "확인 대기",
  };
  return labels[text] || text || "—";
}

function newRequestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function queryUrl(path: string, name: string, value: string): string {
  const query = new URLSearchParams([[name, value]]);
  return `${path}?${query.toString()}`;
}

export function ruleDialogStateUrl(caseId: string): string {
  return queryUrl("/api/classification/dialog", "case_id", caseId);
}

export function conversationStateUrl(caseId: string): string {
  return queryUrl("/api/classification/conversation", "conversation_id", `conv-${caseId}`);
}

export function buildRuleActionRequest(
  action: string,
  caseId: string,
  csrf: string,
  requestId: string,
  fields: Record<string, string | string[]> = {},
) {
  const paths: Record<string, string> = {
    "owner-draft": "/api/classification/conversation/owner-draft",
    "direct-answer": "/api/classification/dialog/answer",
  };
  const path = paths[action];
  if (!path) throw new Error("지원하지 않는 규칙 동작입니다.");
  const body = new URLSearchParams();
  body.set("csrf", csrf);
  body.set("case", caseId);
  body.set("client_request_id", requestId);
  for (const [name, value] of Object.entries(fields)) {
    for (const item of Array.isArray(value) ? value : [value]) body.append(name, item);
  }
  return { path, body };
}

function ruleValue(value: unknown): string {
  const record = asRecord(value);
  return scalar(Object.prototype.hasOwnProperty.call(record, "value") ? record.value : value);
}

function humanize(key: string): string {
  return CONDITION_LABELS[key] || key.replace(/_/g, " ");
}

export function summarizeRuleDraft(value: unknown): Array<{ label: string; value: string }> {
  const wrapper = asRecord(value);
  const draft = asRecord(wrapper.rule ?? wrapper);
  const summary: Array<{ label: string; value: string }> = [];
  const conditions = asRecord(draft.conditions);
  for (const [key, condition] of Object.entries(conditions)) {
    const valueText = ruleValue(condition);
    if (valueText) summary.push({ label: humanize(key), value: valueText });
  }

  const effects = asRecord(draft.effects);
  for (const [key, effect] of Object.entries(effects)) {
    const valueText = ruleValue(effect);
    if (valueText) summary.push({ label: humanize(key), value: valueText });
  }

  const scope = asRecord(draft.scope);
  const scopeParts = [
    scalar(scope.trip_name ?? scope.trip_id),
    scope.event_year != null ? `${scalar(scope.event_year)}년` : "",
  ].filter(Boolean);
  if (scopeParts.length) summary.push({ label: "적용 범위", value: scopeParts.join(" · ") });
  const note = scalar(draft.note);
  if (note) summary.push({ label: "메모", value: note });
  return summary;
}

function apiMessage(value: unknown, fallback: string): string {
  const data = asRecord(value);
  const status = asRecord(data.status);
  return scalar(data.message) || scalar(status.message) || fallback;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message || error.code;
  if (error instanceof Error) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

function turnDraft(conversation: AnyRecord): { draft: AnyRecord | null; error: string } {
  const answered = rows(conversation.turns).filter((turn) => turn.state === "answered");
  const last = answered.at(-1);
  if (!last) return { draft: null, error: "" };
  const raw = asRecord(last.draft);
  const draft = asRecord(raw.rule);
  const failure = asRecord(raw.draft_error);
  return {
    draft: Object.keys(draft).length ? draft : null,
    error: scalar(failure.message),
  };
}

function questionAnswerLabel(question: AnyRecord): string {
  const value = scalar(question.answer);
  const option = rows(question.options).find((item) => scalar(item.value) === value);
  return scalar(option?.label) || value || "—";
}

function resultCount(value: unknown): string {
  return value == null ? "0" : scalar(value);
}

function previewTableRows(value: unknown): AnyRecord[] {
  return rows(value);
}

export function RulesPage({ bootstrap, search, nav }: RulesViewProps) {
  const initialCaseId = search.get("case") || "";
  const [caseId, setCaseId] = useState(initialCaseId);
  const [loadState, setLoadState] = useState<LoadState>({ kind: "idle" });
  const [reloadVersion, setReloadVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [note, setNote] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [directAnswers, setDirectAnswers] = useState<Record<string, string>>({});
  const [applyExisting, setApplyExisting] = useState(true);
  const [applyFuture, setApplyFuture] = useState(false);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const requestIds = useRef(new Map<string, string>());

  useEffect(() => setCaseId(initialCaseId), [initialCaseId]);

  useEffect(() => {
    if (!caseId) {
      setLoadState({ kind: "idle" });
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setLoadState({ kind: "loading" });
    setError("");
    Promise.all([
      getJSON<AnyRecord>(ruleDialogStateUrl(caseId), controller.signal),
      getJSON<AnyRecord>(conversationStateUrl(caseId), controller.signal),
    ]).then(async ([dialog, conversation]) => {
      const ruleId = scalar(conversation.rule_id);
      let rule: AnyRecord | null = null;
      if (ruleId) {
        try { rule = await getJSON<AnyRecord>(`/api/classification/rules/${encodeURIComponent(ruleId)}`, controller.signal); }
        catch { rule = null; }
      }
      if (!active) return;
      setNote(scalar(asRecord(dialog.draft).note));
      setAnswers({});
      setDirectAnswers({});
      setLoadState({ kind: "ready", dialog, conversation, rule });
    }).catch((loadError: unknown) => {
      if (active && !(loadError instanceof DOMException && loadError.name === "AbortError")) {
        setLoadState({ kind: "error", message: errorMessage(loadError) });
      }
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [caseId, reloadVersion]);

  function updateCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = caseId.trim();
    if (!normalized) return;
    setCaseId(normalized);
    const url = new URL(window.location.href);
    url.searchParams.set("case", normalized);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    setPreview(null);
    setReloadVersion((value) => value + 1);
  }

  function requestIdFor(path: string, payload: Record<string, unknown>): string {
    const key = `${path}\n${JSON.stringify(payload)}`;
    let value = requestIds.current.get(key);
    if (!value) {
      value = newRequestId();
      requestIds.current.set(key, value);
    }
    return value;
  }

  async function mutate(path: string, payload: Record<string, unknown>): Promise<AnyRecord> {
    const id = requestIdFor(path, payload);
    const result = await postJSON<AnyRecord>(path, { ...payload, client_request_id: id }, bootstrap.csrf);
    requestIds.current.delete(`${path}\n${JSON.stringify(payload)}`);
    return result;
  }

  async function runAction(action: () => Promise<string>, refresh = true) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setNotice(await action());
      if (refresh) setReloadVersion((value) => value + 1);
    } catch (actionError) {
      setError(errorMessage(actionError));
    } finally {
      setBusy(false);
    }
  }

  async function postNotice(path: string, payload: Record<string, unknown>, fallback: string) {
    const result = await mutate(path, payload);
    return apiMessage(result, fallback);
  }

  async function submitLegacyForm(action: string, fields: Record<string, string | string[]> = {}) {
    const path = action === "owner-draft"
      ? "/api/classification/conversation/owner-draft"
      : "/api/classification/dialog/answer";
    const identity = { case: caseId, ...fields };
    const requestId = requestIdFor(path, identity);
    const request = buildRuleActionRequest(action, caseId, bootstrap.csrf, requestId, fields);
    const response = await fetch(request.path, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "follow",
      headers: {
        Accept: "text/html",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      },
      body: request.body.toString(),
    });
    if (!response.ok) throw new Error("규칙 동작을 처리하지 못했습니다.");
    const destination = new URL(response.url || window.location.href, window.location.origin);
    if (destination.origin !== window.location.origin || destination.pathname !== "/rules") {
      throw new Error("규칙 초안 응답 경로를 확인할 수 없습니다.");
    }
    const message = destination.searchParams.get("msg") || "수정 내용으로 규칙 초안을 만들었습니다.";
    if (/^[A-Z][A-Z0-9_]+\s*:/.test(message)) throw new Error(message);
    requestIds.current.delete(`${path}\n${JSON.stringify(identity)}`);
    return message;
  }

  const navWithCase = nav.map((item) => item.id === "rules" && caseId
    ? { ...item, query: { ...item.query, case: caseId } }
    : item);
  const ready = loadState.kind === "ready" ? loadState : null;
  const dialog = ready?.dialog ?? {};
  const conversation = ready?.conversation ?? {};
  const savedRule = asRecord(ready?.rule);
  const savedRuleBody = asRecord(savedRule.rule);
  const pending = turnDraft(conversation);
  const pendingRule = pending.draft;
  const ruleId = scalar(conversation.rule_id || savedRule.rule_id);
  const questions = rows(dialog.questions);
  const turns = rows(conversation.turns);
  const dialogState = scalar(dialog.dialog_state);
  const conversationState = scalar(conversation.state);
  const displayRule = Object.keys(savedRuleBody).length ? savedRuleBody : pendingRule || asRecord(dialog.draft);
  const draftSummary = summarizeRuleDraft({ rule: displayRule });
  const previewCounts = asRecord(preview?.counts);

  return (
    <main className="e-feature-page e-rules-page">
      <header className="e-feature-header">
        <div><p className="e-feature-eyebrow">COST · 업무 도구</p><h1>규칙 보조</h1></div>
        <button type="button" className="cost-button cost-button-quiet" disabled={!caseId || busy}
          onClick={() => { setPreview(null); setReloadVersion((value) => value + 1); }}>
          새로고침
        </button>
      </header>
      <FeatureNav label="규칙 보조 메뉴" items={navWithCase} current="rules" />

      <form className="e-rules-case-picker cost-panel" onSubmit={updateCase}>
        <label className="e-feature-field">
          <span>규칙 대화 사례 ID</span>
          <input value={caseId} onChange={(event) => setCaseId(event.currentTarget.value)} autoComplete="off" />
        </label>
        <button type="submit" className="cost-button" disabled={!caseId.trim() || busy}>사례 열기</button>
      </form>

      {!caseId ? (
        <section className="cost-panel e-feature-state">
          <h2>사례를 선택해 주세요</h2>
          <p>거래 수정 화면에서 전달된 사례 ID를 열면 기존 규칙 대화와 저장된 초안을 확인할 수 있습니다.</p>
        </section>
      ) : null}
      {loadState.kind === "loading" ? <p className="cost-panel e-feature-loading" role="status">규칙 대화를 불러오는 중입니다…</p> : null}
      {loadState.kind === "error" ? (
        <section className="cost-panel e-feature-state" role="alert">
          <h2>규칙 대화를 불러오지 못했습니다</h2><p>{loadState.message}</p>
          <button type="button" className="cost-button" onClick={() => setReloadVersion((value) => value + 1)}>다시 불러오기</button>
        </section>
      ) : null}
      {notice ? <p className="e-feature-notice" role="status">{notice}</p> : null}
      {error ? <p className="e-feature-error" role="alert">{error}</p> : null}

      {ready ? (
        <>
          <section className="cost-panel e-rules-status">
            <h2>현재 상태</h2>
            <dl className="e-feature-record-list">
              <div className="e-feature-record-line"><dt>대화</dt><dd>{stateLabel(dialogState)}</dd></div>
              <div className="e-feature-record-line"><dt>초안 대화</dt><dd>{stateLabel(conversationState)}</dd></div>
              {dialog.row_revision != null || conversation.row_revision != null
                ? <div className="e-feature-record-line"><dt>거래 수정 버전</dt><dd>{scalar(dialog.row_revision ?? conversation.row_revision)}</dd></div>
                : null}
              {ruleId ? <div className="e-feature-record-line"><dt>저장된 규칙</dt><dd>{`${ruleId} · ${scalar(savedRule.version) || "버전 확인 중"} · ${stateLabel(savedRule.status)}`}</dd></div> : null}
            </dl>
            {dialog.rule_should_not_be_created === true
              ? <p className="e-feature-hint">이 사례는 한 번의 교정으로 처리되므로 반복 규칙을 만들지 않습니다.</p>
              : null}
            {dialogState === "closed" ? (
              <button type="button" className="cost-button" disabled={busy}
                onClick={() => void runAction(() => postNotice("/api/classification/dialog/resume", { learning_case_id: caseId }, "대화를 다시 열었습니다."))}>
                대화 다시 열기
              </button>
            ) : null}
          </section>

          {dialogState !== "closed" && dialog.rule_should_not_be_created !== true ? (
            <section className="cost-panel e-rules-dialog">
              <h2>대화와 근거</h2>
              <form className="e-rules-note" onSubmit={(event) => {
                event.preventDefault();
                void runAction(() => postNotice("/api/classification/dialog/note", { case: caseId, note }, "근거 설명을 저장했습니다."));
              }}>
                <label className="e-feature-field"><span>근거 설명</span>
                  <textarea value={note} onChange={(event) => setNote(event.currentTarget.value)} rows={3} maxLength={1000} />
                </label>
                <button type="submit" className="cost-button cost-button-secondary" disabled={busy}>근거 저장</button>
              </form>
              {questions.map((question) => {
                const questionId = scalar(question.question_id);
                const options = rows(question.options);
                const isDirect = scalar(question.question_key) === "trip_move_reason" && !options.length;
                const answered = question.answered === true || question.answer != null;
                return (
                  <form className="e-rules-question" key={questionId} onSubmit={(event) => {
                    event.preventDefault();
                    const answer = answers[questionId] || "";
                    const directAnswer = (directAnswers[questionId] || "").trim();
                    const chosen = isDirect ? directAnswer : answer;
                    if (!chosen) { setError("질문에 답하거나 직접 입력해 주세요."); return; }
                    if (isDirect) {
                      void runAction(() => submitLegacyForm("direct-answer", {
                        question_id: questionId,
                        expected_row_revision: scalar(dialog.row_revision ?? conversation.row_revision ?? 0),
                        answer: "__direct__",
                        direct_answer: directAnswer,
                      }));
                      return;
                    }
                    const payload = {
                      case: caseId,
                      question_id: questionId,
                      answer,
                      expected_row_revision: dialog.row_revision ?? conversation.row_revision ?? 0,
                    };
                    void runAction(() => postNotice("/api/classification/dialog/answer", payload, "답변을 저장했습니다."));
                  }}>
                    <h3>{scalar(question.prompt)}</h3>
                    {answered ? <p className="e-feature-status">답변 완료 · {questionAnswerLabel(question)}</p> : (
                      <>
                      {options.length ? (
                          <div className="e-rules-options">
                            {options.map((option) => (
                              <label className="e-feature-check" key={scalar(option.value)}>
                                <input type="radio" name={`answer-${questionId}`} value={scalar(option.value)}
                                  checked={(answers[questionId] ?? "") === scalar(option.value)}
                                  onChange={() => setAnswers((current) => ({ ...current, [questionId]: scalar(option.value) }))} />
                                <span>{scalar(option.label) || scalar(option.value)}</span>
                              </label>
                            ))}
                          </div>
                        ) : null}
                        {scalar(question.question_key) === "trip_move_reason" && !answered && !options.length ? (
                          <button type="button" className="cost-button cost-button-secondary" disabled={busy}
                            onClick={() => void runAction(() => postNotice("/api/classification/conversation/reasons", { case: caseId }, "이동 이유 선택지를 준비했습니다."))}>
                            이동 이유 선택지 제안
                          </button>
                        ) : null}
                        {isDirect ? (
                          <label className="e-feature-field"><span>직접 입력</span>
                            <textarea value={directAnswers[questionId] || ""} maxLength={500} rows={2}
                              onChange={(event) => setDirectAnswers((current) => ({ ...current, [questionId]: event.currentTarget.value }))} />
                          </label>
                        ) : null}
                        <button type="submit" className="cost-button cost-button-secondary" disabled={busy}>답변 저장</button>
                      </>
                    )}
                  </form>
                );
              })}
              {!questions.length ? <p className="e-feature-hint">저장된 질문이 없습니다.</p> : null}
              {pending.error ? <p className="e-feature-error" role="alert">초안 검증 실패 · {pending.error}</p> : null}
              {conversationState !== "not_found" ? (
                <>
                  <div className="e-rules-turns">
                    <h3>규칙 초안 대화</h3>
                    {turns.length ? (
                      <ul className="e-feature-record-list">
                        {turns.map((turn, index) => (
                          <li className="e-feature-record-line" key={scalar(turn.turn_id) || index}>
                            <span>{scalar(turn.state_label) || stateLabel(turn.state)}</span>
                            <strong>{[scalar(turn.adopted_provider), scalar(turn.reason_code), turn.switch_count ? `전환 ${scalar(turn.switch_count)}회` : ""].filter(Boolean).join(" · ") || "상세 없음"}</strong>
                          </li>
                        ))}
                      </ul>
                    ) : <p className="e-feature-hint">초안 요청 이력이 없습니다.</p>}
                    <button type="button" className="cost-button" disabled={busy}
                      onClick={() => void runAction(() => postNotice("/api/classification/conversation/advance", { case: caseId }, "규칙 초안 요청을 처리했습니다."))}>
                      규칙 초안 요청
                    </button>
                  </div>
                  {pendingRule && !ruleId ? (
                    <div className="e-rules-confirm">
                      <p>검증을 통과한 초안입니다. 저장 후 영향 미리보기를 별도로 실행하세요.</p>
                      <button type="button" className="cost-button" disabled={busy}
                        onClick={() => void runAction(() => postNotice("/api/classification/conversation/confirm-draft", { case: caseId }, "규칙 초안을 저장했습니다."))}>
                        초안 저장
                      </button>
                    </div>
                  ) : null}
                </>
              ) : null}
              {!ruleId ? (
                <div className="e-rules-owner-draft">
                  <p>거래에 저장한 소유자 수정 내용을 같은 가맹점 규칙 초안으로 만듭니다. 이 작업은 행에 적용하지 않습니다.</p>
                  <button type="button" className="cost-button" disabled={busy}
                    onClick={() => void runAction(() => submitLegacyForm("owner-draft"))}>
                    내 수정 내용으로 규칙 초안 만들기
                  </button>
                </div>
              ) : null}
              {dialogState !== "not_started" ? (
                <button type="button" className="cost-button cost-button-quiet" disabled={busy}
                  onClick={() => void runAction(() => postNotice("/api/classification/dialog/close", { learning_case_id: caseId }, "대화를 닫았습니다."))}>
                  대화 닫기
                </button>
              ) : null}
            </section>
          ) : null}

          {draftSummary.length ? (
            <section className="cost-panel e-rules-draft">
              <h2>{ruleId ? "저장된 규칙 내용" : "규칙 초안"}</h2>
              <dl className="e-feature-record-list">
                {draftSummary.map((field) => <div className="e-feature-record-line" key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}
              </dl>
            </section>
          ) : null}

          {ruleId ? (
            <section className="cost-panel e-rules-preview">
              <h2>영향 확인과 적용</h2>
              <label className="e-feature-check"><input type="checkbox" checked={applyExisting} disabled={busy}
                onChange={(event) => { setApplyExisting(event.currentTarget.checked); setPreview(null); }} />
                <span>기존 행에 적용</span></label>
              <label className="e-feature-check"><input type="checkbox" checked={applyFuture} disabled={busy}
                onChange={(event) => { setApplyFuture(event.currentTarget.checked); setPreview(null); }} />
                <span>앞으로 입력될 행에 적용</span></label>
              <button type="button" className="cost-button" disabled={busy || !applyExisting && !applyFuture}
                onClick={() => void runAction(async () => {
                  const result = await postJSON<AnyRecord>("/api/classification/rules/preview", {
                    rule_id: ruleId, apply_existing: applyExisting, apply_future: applyFuture,
                  }, bootstrap.csrf);
                  setPreview({ ...result, apply_existing: applyExisting, apply_future: applyFuture });
                  const counts = asRecord(result.counts);
                  return `영향 미리보기 · 포함 ${resultCount(counts.included_rows)}건 · 제외 ${resultCount(counts.excluded_rows)}건`;
                }, false)}>
                영향 미리보기
              </button>
              {!applyExisting && !applyFuture ? <p className="e-feature-hint">적용할 범위를 하나 이상 선택해 주세요.</p> : null}
              {preview ? (
                <>
                  <dl className="e-feature-record-list">
                    <div className="e-feature-record-line"><dt>포함</dt><dd>{resultCount(previewCounts.included_rows)}건</dd></div>
                    <div className="e-feature-record-line"><dt>제외</dt><dd>{resultCount(previewCounts.excluded_rows)}건</dd></div>
                    <div className="e-feature-record-line"><dt>일치</dt><dd>{resultCount(previewCounts.matched_rows)}건</dd></div>
                  </dl>
                  {previewTableRows(preview.candidates).length ? (
                    <div className="e-feature-table-wrap" role="region" aria-label="영향 미리보기 후보 표" tabIndex={0}>
                      <table className="e-feature-table" aria-label="영향 미리보기 후보">
                        <thead><tr><th scope="col">행</th><th scope="col">이동 전</th><th scope="col">이동 후</th><th scope="col">금액</th></tr></thead>
                        <tbody>{previewTableRows(preview.candidates).map((row, index) => (
                          <tr key={scalar(row.row_id) || index}>
                            <td>{scalar(row.row_id)}</td><td>{scalar(row.from_tab_id) || "귀속 없음"}</td>
                            <td>{scalar(row.to_tab_id) || "귀속 없음"}</td><td>{scalar(row.amount_krw) || "—"}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                    </div>
                  ) : <p className="e-feature-hint">포함할 기존 행이 없습니다.</p>}
                  {previewTableRows(preview.excluded).length ? (
                    <section className="e-rules-excluded"><h3>제외된 행</h3>
                      <ul>{previewTableRows(preview.excluded).map((row, index) => <li key={scalar(row.row_id) || index}>{scalar(row.row_id)} · {scalar(row.reason)}</li>)}</ul>
                    </section>
                  ) : null}
                  {preview.apply_existing || preview.apply_future ? (
                    <button type="button" className="cost-button" disabled={busy}
                      onClick={() => void runAction(async () => {
                        const candidateIds = previewTableRows(preview.candidates).map((row) => scalar(row.row_id)).filter(Boolean);
                        const payload: Record<string, unknown> = {
                          preview_id: scalar(preview.preview_id),
                          apply_existing: preview.apply_existing,
                          apply_future: preview.apply_future,
                        };
                        if (candidateIds.length) payload.selected_row_ids = candidateIds;
                        const result = await mutate("/api/classification/rules/apply", payload);
                        setPreview(null);
                        return apiMessage(result, "규칙을 적용했습니다.");
                      })}>
                      확인한 범위로 적용
                    </button>
                  ) : null}
                </>
              ) : <p className="e-feature-hint">규칙을 적용하기 전에 새 영향 미리보기를 확인하세요.</p>}
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
