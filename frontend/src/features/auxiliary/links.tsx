import { useEffect, useRef, useState } from "react";
import { ApiError, getJSON, postJSON } from "../../api/client";
import type { Bootstrap } from "../../api/types";
import { FeatureNav, type PageProps } from "../transactions/feature-ui";

type AnyRecord = Record<string, unknown>;
type NavItem = { id: string; label: string; path: string; query?: Record<string, string> };
type LinkView = "participants" | "reserve-links";
type LinksPageProps = PageProps & { nav: NavItem[]; view: LinkView };
type ResourceState<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; value: T };

function record(value: unknown): AnyRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

function records(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : [];
}

function amountLabel(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return `${new Intl.NumberFormat("ko-KR").format(value)}원`;
  const valueText = text(value);
  return valueText ? `${valueText}원` : "금액 확인 안 됨";
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message || error.code;
  if (error instanceof Error) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

function makeRequestId(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function requestFor(cache: Map<string, string>, path: string, payload: Record<string, unknown>): { key: string; id: string } {
  const key = `${path}\n${JSON.stringify(payload)}`;
  let id = cache.get(key);
  if (!id) {
    id = makeRequestId();
    cache.set(key, id);
  }
  return { key, id };
}

function navWithTrip(nav: NavItem[], tripId: string): NavItem[] {
  return nav.map((item) => item.id === "participants" && tripId
    ? { ...item, query: { ...item.query, trip: tripId } }
    : item);
}

function Header({
  title,
  nav,
  current,
  onRefresh,
  busy,
}: {
  title: string;
  nav: NavItem[];
  current: LinkView;
  onRefresh: () => void;
  busy: boolean;
}) {
  return (
    <>
      <header className="e-feature-header">
        <div><p className="e-feature-eyebrow">COST · 업무 도구</p><h1>{title}</h1></div>
        <button type="button" className="cost-button cost-button-quiet" disabled={busy} onClick={onRefresh}>새로고침</button>
      </header>
      <FeatureNav label="보조 기능 메뉴" items={nav} current={current} />
    </>
  );
}

function ParticipantsLinksPage({ bootstrap, search, nav }: Omit<LinksPageProps, "view">) {
  const choices = bootstrap.trips || [];
  const queryTrip = search.get("trip") || search.get("tab") || "";
  const [tripId, setTripId] = useState(queryTrip || choices[0]?.id || "");
  const [resource, setResource] = useState<ResourceState<AnyRecord>>({ kind: "idle" });
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedIncome, setSelectedIncome] = useState<Record<string, string>>({});
  const [joint, setJoint] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!tripId) {
      setResource({ kind: "idle" });
      return;
    }
    const controller = new AbortController();
    let active = true;
    setResource({ kind: "loading" });
    getJSON<AnyRecord>(`/api/participants/state?${new URLSearchParams({ trip: tripId })}`, controller.signal)
      .then((value) => { if (active) setResource({ kind: "ready", value }); })
      .catch((loadError: unknown) => {
        if (active && !(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setResource({ kind: "error", message: errorMessage(loadError) });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [tripId, reload]);

  const state = resource.kind === "ready" ? resource.value : {};
  const participants = records(state.participants);
  const incomeRows = records(state.income_rows);
  const fingerprint = text(state.input_fingerprint);
  const configured = state.configured === true;
  const navItems = navWithTrip(nav, tripId);

  async function write(path: string, payload: Record<string, unknown>, success: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await postJSON<AnyRecord>(path, payload, bootstrap.csrf);
      setNotice(success);
      setSelectedIncome({});
      setReload((value) => value + 1);
    } catch (writeError) {
      setError(errorMessage(writeError));
    } finally {
      setBusy(false);
    }
  }

  function selectTrip(nextTrip: string) {
    setTripId(nextTrip);
    setSelectedIncome({});
    setJoint({});
    setError("");
    setNotice("");
    const url = new URL(window.location.href);
    if (nextTrip) url.searchParams.set("trip", nextTrip);
    else url.searchParams.delete("trip");
    url.searchParams.delete("tab");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  return (
    <main className="e-feature-page e-links-page">
      <Header title="참가자·수입 연결" nav={navItems} current="participants" busy={busy}
        onRefresh={() => setReload((value) => value + 1)} />
      <section className="cost-panel">
        <label className="e-feature-field"><span>여행</span>
          <select aria-label="대조 여행 선택" value={tripId} disabled={busy || !choices.length}
            onChange={(event) => selectTrip(event.currentTarget.value)}>
            <option value="">여행 선택</option>
            {choices.map((trip) => <option key={trip.id} value={trip.id}>{trip.title}</option>)}
          </select>
        </label>
      </section>

      {notice ? <p className="e-feature-notice" role="status">{notice}</p> : null}
      {error ? <p className="e-feature-error" role="alert">{error}</p> : null}
      {resource.kind === "idle" ? <p className="cost-panel e-feature-state">연결할 여행을 선택해 주세요.</p> : null}
      {resource.kind === "loading" ? <p className="cost-panel e-feature-loading" role="status">참가자와 수입 행을 불러오는 중입니다…</p> : null}
      {resource.kind === "error" ? (
        <section className="cost-panel e-feature-state" role="alert">
          <h2>참가자 대조를 불러오지 못했습니다</h2><p>{resource.message}</p>
          <button type="button" className="cost-button" disabled={busy} onClick={() => setReload((value) => value + 1)}>다시 불러오기</button>
        </section>
      ) : null}
      {resource.kind === "ready" ? (
        <>
          <section className="cost-panel e-links-summary">
            <h2>현재 대조 상태</h2>
            <dl className="e-feature-record-list">
              <div className="e-feature-record-line"><dt>참가자</dt><dd>{text(record(state.counts).participants) || participants.length}명</dd></div>
              <div className="e-feature-record-line"><dt>연결된 수입 행</dt><dd>{text(record(state.counts).linked_income_rows) || "0"}건</dd></div>
              <div className="e-feature-record-line"><dt>미연결 수입 행</dt><dd>{text(record(state.counts).unlinked_income_rows) || "0"}건</dd></div>
            </dl>
            {!configured ? <p className="e-feature-hint">참가 명단 저장소가 준비되지 않아 연결을 저장할 수 없습니다.</p> : null}
          </section>

          <section className="cost-panel">
            <h2>참가자별 수입 연결</h2>
            <p className="e-feature-hint">연결 선택지는 현재 여행의 서버 조회 결과에서 가져옵니다. 참가자를 새로 만들지 않습니다.</p>
            {participants.length ? (
              <div className="e-feature-table-wrap" role="region" aria-label="참가자별 수입 연결 표" tabIndex={0}>
                <table className="e-feature-table" aria-label="참가자별 수입 연결">
                  <thead><tr><th scope="col">참가자</th><th scope="col">연결된 수입 행</th><th scope="col">수입 행 연결</th></tr></thead>
                  <tbody>{participants.map((participant, index) => {
                    const participantId = text(participant.participant_id);
                    const name = text(participant.display_name) || "이름 확인 필요";
                    const participantLinks = records(participant.links);
                    const canLink = participant.participant_state === "confirmed" && participant.active !== false;
                    return (
                      <tr key={participantId || index}>
                        <td><strong>{name}</strong><br /><span>{text(participant.state) || "상태 확인 필요"}</span></td>
                        <td>{participantLinks.length ? participantLinks.map((link, linkIndex) => {
                          const row = record(link.row);
                          const rowNumber = text(row.row ?? link.row_number) || "?";
                          const linkedName = text(row.name) || name;
                          const incomeRef = text(link.income_ref);
                          return (
                            <div className="e-feature-record-line" key={`${incomeRef}-${linkIndex}`}>
                              <span>수입 {rowNumber}행 · {linkedName} · {amountLabel(row.amount)}</span>
                              <button type="button" className="cost-button cost-button-quiet" disabled={busy || !fingerprint}
                                aria-label={`연결 해제 · ${name} · ${rowNumber}행`}
                                onClick={() => void write("/api/participants/unlink", {
                                  trip: tripId, participant_id: participantId, income_ref: incomeRef,
                                  input_fingerprint: fingerprint,
                                }, "참가 수입 연결을 해제했습니다.")}>
                                연결 해제
                              </button>
                            </div>
                          );
                        }) : <span>연결된 수입 행 없음</span>}</td>
                        <td>
                          <label className="e-feature-field"><span>수입 행 선택</span>
                            <select aria-label={`수입 행 선택 · ${name}`} value={selectedIncome[participantId] || ""}
                              disabled={busy || !configured || !canLink || !fingerprint || !incomeRows.length}
                              onChange={(event) => {
                                const incomeRef = event.currentTarget.value;
                                setSelectedIncome((current) => ({ ...current, [participantId]: incomeRef }));
                              }}>
                              <option value="">수입 행 선택</option>
                              {incomeRows.map((incomeRow, rowIndex) => {
                                const incomeRef = text(incomeRow.ref);
                                const rowNumber = text(incomeRow.row) || String(rowIndex + 1);
                                const incomeName = text(incomeRow.name) || "이름 미확인";
                                return <option key={incomeRef || rowIndex} value={incomeRef}>수입 {rowNumber}행 · {incomeName} · {amountLabel(incomeRow.amount)}</option>;
                              })}
                            </select>
                          </label>
                          <label className="e-feature-check">
                            <input type="checkbox" checked={joint[participantId] || false}
                              disabled={busy || !configured || !canLink}
                              onChange={(event) => setJoint((current) => ({ ...current, [participantId]: event.currentTarget.checked }))} />
                            <span>공동 입금</span>
                          </label>
                          <button type="button" className="cost-button" disabled={busy || !configured || !canLink || !fingerprint || !selectedIncome[participantId]}
                            onClick={() => void write("/api/participants/link", {
                              trip: tripId,
                              participant_id: participantId,
                              income_ref: selectedIncome[participantId],
                              input_fingerprint: fingerprint,
                              joint: joint[participantId] || false,
                            }, "참가 수입 연결을 저장했습니다.")}>
                            연결 · {name}
                          </button>
                          {!canLink ? <p className="e-feature-hint">보험가입이 확정된 활성 참가자만 연결할 수 있습니다.</p> : null}
                        </td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            ) : <p className="e-feature-hint">현재 여행의 참가자 조회 결과가 없습니다.</p>}
          </section>
        </>
      ) : null}
    </main>
  );
}

function sortedTargets(value: unknown): string[] {
  return strings(value).sort((left, right) => left.localeCompare(right));
}

function sameTargets(left: unknown, right: unknown): boolean {
  return JSON.stringify(sortedTargets(left)) === JSON.stringify(sortedTargets(right));
}

function ReserveLinksPage({ bootstrap, nav }: Omit<LinksPageProps, "view" | "search" | "path">) {
  const [resource, setResource] = useState<ResourceState<AnyRecord>>({ kind: "idle" });
  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [applyResult, setApplyResult] = useState<AnyRecord | null>(null);
  const requestIds = useRef(new Map<string, string>());

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setResource({ kind: "loading" });
    getJSON<AnyRecord>("/api/reserve-link/plan", controller.signal)
      .then((value) => {
        if (!active) return;
        setResource({ kind: "ready", value });
        const perIdentifier = record(value.per_identifier);
        const initialDraft: Record<string, string[]> = {};
        for (const [source, targets] of Object.entries(perIdentifier)) initialDraft[source] = strings(targets);
        setDraft(initialDraft);
      })
      .catch((loadError: unknown) => {
        if (active && !(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setResource({ kind: "error", message: errorMessage(loadError) });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reload]);

  const plan = resource.kind === "ready" ? resource.value : {};
  const perIdentifier = record(plan.per_identifier);
  const sourceCodes = Object.keys(perIdentifier).sort((left, right) => left.localeCompare(right));
  const choices = records(plan.choices);
  const persons = records(plan.persons);
  const sourceNames: Record<string, string[]> = {};
  for (const person of persons) {
    const name = text(person.display_name) || "예약자 이름 없음";
    for (const code of strings(person.assignments)) sourceNames[code] = [...(sourceNames[code] || []), name];
  }
  const links: Array<{ source_event_key: string; target_tab_id: string }> = [];
  const unlinks: string[] = [];
  for (const code of sourceCodes) {
    const nextTargets = sortedTargets(draft[code] ?? perIdentifier[code]);
    if (sameTargets(nextTargets, perIdentifier[code])) continue;
    if (nextTargets.length) {
      for (const target of nextTargets) links.push({ source_event_key: code, target_tab_id: target });
    } else {
      unlinks.push(code);
    }
  }
  const binding = record(plan.binding);
  const linkRevision = typeof plan.link_revision === "number" && Number.isInteger(plan.link_revision) ? plan.link_revision : null;
  const canEdit = plan.configured === true && plan.readable === true && Object.keys(binding).length > 0 && linkRevision !== null;
  const canApply = canEdit && plan.applicable === true && !!text(plan.apply_digest);

  async function saveLinks() {
    if (busy || !canEdit || (!links.length && !unlinks.length) || linkRevision === null) return;
    const basePayload: Record<string, unknown> = {
      source_binding: binding,
      link_revision: linkRevision,
      links,
      unlinks,
    };
    const path = "/api/reserve-link/links";
    const request = requestFor(requestIds.current, path, basePayload);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await postJSON<AnyRecord>(path, { request_id: request.id, ...basePayload }, bootstrap.csrf);
      requestIds.current.delete(request.key);
      setNotice("예약 연결을 저장했습니다.");
      setApplyResult(null);
      setReload((value) => value + 1);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setBusy(false);
    }
  }

  async function applyPlan() {
    if (busy || !canApply || linkRevision === null) return;
    const basePayload: Record<string, unknown> = {
      source_binding: binding,
      link_revision: linkRevision,
      apply_digest: text(plan.apply_digest),
    };
    const path = "/api/reserve-link/apply";
    const request = requestFor(requestIds.current, path, basePayload);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await postJSON<AnyRecord>(path, { request_id: request.id, ...basePayload }, bootstrap.csrf);
      requestIds.current.delete(request.key);
      setApplyResult(result);
      const counts = record(result.counts);
      const countSummary = [
        counts.linked != null ? `연결 ${text(counts.linked)}건` : "",
        counts.disconnected != null ? `해제 ${text(counts.disconnected)}건` : "",
        counts.unchanged != null ? `유지 ${text(counts.unchanged)}건` : "",
      ].filter(Boolean).join(" · ");
      setNotice(`예약 연결 반영 완료${countSummary ? ` · ${countSummary}` : ""}`);
      setReload((value) => value + 1);
    } catch (applyError) {
      setError(errorMessage(applyError));
    } finally {
      setBusy(false);
    }
  }

  const countSummary = record(plan.counts);
  return (
    <main className="e-feature-page e-links-page">
      <Header title="예약 명단·여행 연결" nav={nav} current="reserve-links" busy={busy}
        onRefresh={() => { setApplyResult(null); setReload((value) => value + 1); }} />
      {notice ? <p className="e-feature-notice" role="status">{notice}</p> : null}
      {error ? <p className="e-feature-error" role="alert">{error}</p> : null}
      {resource.kind === "loading" || resource.kind === "idle" ? <p className="cost-panel e-feature-loading" role="status">예약 연결 계획을 불러오는 중입니다…</p> : null}
      {resource.kind === "error" ? (
        <section className="cost-panel e-feature-state" role="alert">
          <h2>예약 연결 계획을 불러오지 못했습니다</h2><p>{resource.message}</p>
          <button type="button" className="cost-button" disabled={busy} onClick={() => setReload((value) => value + 1)}>다시 불러오기</button>
        </section>
      ) : null}
      {resource.kind === "ready" && plan.configured !== true ? (
        <section className="cost-panel e-feature-state"><h2>예약 원본 연결이 필요합니다</h2><p>예약 원본이 설정된 뒤 실제 연결 선택지를 불러올 수 있습니다.</p></section>
      ) : null}
      {resource.kind === "ready" && plan.configured === true && plan.readable !== true ? (
        <section className="cost-panel e-feature-state" role="alert"><h2>예약 원본을 읽을 수 없습니다</h2><p>{text(plan.code) || "원본 상태를 확인한 뒤 다시 시도해 주세요."}</p></section>
      ) : null}
      {resource.kind === "ready" && plan.configured === true && plan.readable === true ? (
        <>
          <section className="cost-panel e-links-summary">
            <h2>현재 예약 연결 계획</h2>
            <dl className="e-feature-record-list">
              <div className="e-feature-record-line"><dt>예약 식별자</dt><dd>{text(countSummary.source_identifiers) || sourceCodes.length}건</dd></div>
              <div className="e-feature-record-line"><dt>연결될 항목</dt><dd>{text(countSummary.resolved_transactions) || "0"}건</dd></div>
              <div className="e-feature-record-line"><dt>미연결 예약</dt><dd>{text(countSummary.unlinked_identifiers) || "0"}건</dd></div>
            </dl>
            {!sourceCodes.length ? <p className="e-feature-hint">현재 예약 원본에서 연결할 식별자가 없습니다.</p> : null}
            {plan.applicable !== true ? <p className="e-feature-hint">모든 예약 식별자를 실제 여행 선택지에 연결한 뒤 반영할 수 있습니다. {text(plan.refusal_code)}</p> : null}
          </section>

          <section className="cost-panel">
            <h2>예약 식별자별 여행 연결</h2>
            <p className="e-feature-hint">저장과 반영은 별도 단계입니다. 저장은 연결 관계만 바꾸며, 반영 버튼을 눌러야 명단 연결을 적용합니다.</p>
            {!choices.length ? <p className="e-feature-error" role="alert">연결할 COST 여행이 없습니다. 장부에 여행을 등록한 뒤 다시 불러와 주세요.</p> : null}
            {sourceCodes.length ? (
              <div className="e-feature-table-wrap" role="region" aria-label="예약 식별자 연결 표" tabIndex={0}>
                <table className="e-feature-table" aria-label="예약 식별자 연결">
                  <thead><tr><th scope="col">예약자·예약 정보</th><th scope="col">현재 연결</th><th scope="col">연결할 COST 여행</th></tr></thead>
                  <tbody>{sourceCodes.map((code) => {
                    const selected = draft[code] ?? strings(perIdentifier[code]);
                    const displayedNames = sourceNames[code] || [];
                    const knownTargets = choices.map((choice) => text(choice.tab_id)).filter(Boolean);
                    const missingTargets = selected.filter((target) => !knownTargets.includes(target));
                    return (
                      <tr key={code}>
                        <td><strong>{displayedNames.join(", ") || "예약자 정보 없음"}</strong><br /><small>{code}</small></td>
                        <td>{selected.length ? selected.map((target) => {
                          const choice = choices.find((item) => text(item.tab_id) === target);
                          return <span className="e-feature-status" key={target}>{text(choice?.label) || target}</span>;
                        }) : <span>아직 연결되지 않음</span>}</td>
                        <td>
                          <label className="e-feature-field"><span>여행 선택</span>
                            <select multiple size={Math.min(4, Math.max(2, choices.length + missingTargets.length))}
                              aria-label={`대상 선택 · ${code}`} value={selected}
                              disabled={busy || !canEdit || !choices.length}
                              onChange={(event) => {
                                const selectedTargets = Array.from(event.currentTarget.selectedOptions, (option) => option.value);
                                setDraft((current) => ({ ...current, [code]: selectedTargets }));
                              }}>
                              {choices.map((choice, index) => {
                                const targetId = text(choice.tab_id);
                                const label = text(choice.label) || text(choice.destination) || targetId;
                                return <option key={targetId || index} value={targetId}>{label}</option>;
                              })}
                              {missingTargets.map((target) => <option key={target} value={target}>{target} · 현재 연결</option>)}
                            </select>
                          </label>
                          {selected.length ? <button type="button" className="cost-button cost-button-quiet" disabled={busy || !canEdit}
                            aria-label={`이 예약 연결 해제 · ${displayedNames.join(", ") || code}`}
                            onClick={() => setDraft((current) => ({ ...current, [code]: [] }))}>이 예약 연결 해제</button> : null}
                        </td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            ) : null}
            <div className="e-feature-actions">
              <button type="button" className="cost-button" disabled={busy || !canEdit || (!links.length && !unlinks.length)} onClick={() => void saveLinks()}>
                연결 저장
              </button>
              <button type="button" className="cost-button cost-button-secondary" disabled={busy || !canApply} onClick={() => void applyPlan()}>
                현재 연결 반영
              </button>
            </div>
          </section>

          {applyResult ? (
            <section className="cost-panel" aria-label="예약 연결 반영 결과">
              <h2>반영 결과</h2>
              <dl className="e-feature-record-list">
                {Object.entries(record(applyResult.counts)).map(([key, value]) => (
                  <div className="e-feature-record-line" key={key}><dt>{key === "linked" ? "연결" : key === "disconnected" ? "해제" : key === "unchanged" ? "유지" : key}</dt><dd>{text(value)}건</dd></div>
                ))}
              </dl>
              {!Object.keys(record(applyResult.counts)).length ? <p>서버가 반영 완료를 확인했습니다.</p> : null}
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}

export function AuxiliaryLinksPage(props: LinksPageProps) {
  if (props.view === "participants") return <ParticipantsLinksPage {...props} />;
  return <ReserveLinksPage {...props} />;
}

export type { Bootstrap };
