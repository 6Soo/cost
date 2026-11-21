import { useState } from "react";
import type { Bootstrap } from "../../api/types";
import { record, records, text, type AnyRecord } from "./display";

function participantStateLabel(value: unknown): string {
  const state = text(value);
  if (state === "confirmed") return "참가 확정";
  if (state === "correction_pending") return "이름 정정 자료 확인";
  if (state === "merged") return "같은 사람으로 합쳐짐";
  return "상태 확인 필요";
}

type Draft = {
  name: string;
  alias: string;
  reason: string;
  target: string;
  other: string;
};

function emptyDraft(participant: AnyRecord, tripId: string): Draft {
  return {
    name: text(participant.display_name),
    alias: text(participant.nickname),
    reason: "",
    target: text(participant.trip_id) || tripId,
    other: "",
  };
}

type ParticipantRosterProps = {
  bootstrap: Bootstrap;
  state: AnyRecord;
  configured: boolean;
  fingerprint: string;
  busy: boolean;
  onWrite: (path: string, payload: Record<string, unknown>, success: string) => void;
};

function ParticipantRoster({
  bootstrap,
  state,
  configured,
  fingerprint,
  busy,
  onWrite,
}: ParticipantRosterProps) {
  const tripId = text(state.trip_id);
  const participants = records(state.participants);
  const trips = Array.isArray(bootstrap.trips) ? bootstrap.trips : [];
  const canWrite = configured && Boolean(fingerprint) && !busy;
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => {
    const initial: Record<string, Draft> = {};
    for (const participant of participants) {
      const participantId = text(participant.participant_id);
      if (participantId) initial[participantId] = emptyDraft(participant, tripId);
    }
    return initial;
  });

  function draftFor(participantId: string, participant: AnyRecord): Draft {
    return drafts[participantId] || emptyDraft(participant, tripId);
  }

  function update(participantId: string, patch: Partial<Draft>): void {
    const current = drafts[participantId] || emptyDraft({}, tripId);
    setDrafts((previous) => ({ ...previous, [participantId]: { ...current, ...patch } }));
  }

  function submit(path: string, payload: Record<string, unknown>, success: string): void {
    if (!canWrite) return;
    onWrite(path, payload, success);
  }

  if (!participants.length) return null;

  return (
    <>
      <section className="cost-panel">
        <h2>참가자 이름·별칭·여행 교정</h2>
        <p className="e-feature-hint">
          교정해도 서버 대조 지문으로 현재 상태를 다시 확인합니다. 근거가 되는 원본 자료는 바뀌지 않습니다.
        </p>
        {!canWrite ? <p className="e-feature-hint">대조 상태가 준비되지 않아 교정 내용을 저장할 수 없습니다.</p> : null}
        {participants.map((participant, index) => {
          const participantId = text(participant.participant_id);
          const name = text(participant.display_name) || "이름 확인 필요";
          const draft = participantId ? draftFor(participantId, participant) : emptyDraft(participant, tripId);
          const others = participants.filter((_other, otherIndex) => otherIndex !== index);
          return (
            <div className="e-feature-record-list" key={participantId || `missing-id-${index}`}>
              <div className="e-feature-record-line"><span>참가자</span><strong>{name}</strong></div>
              <div className="e-feature-record-line"><span>상태</span><span className="e-feature-status">{participantStateLabel(participant.participant_state ?? participant.state)}</span></div>
              {!participantId ? (
                <p className="e-feature-hint">참가자 식별자가 없어 교정 내용을 저장하지 않습니다.</p>
              ) : null}
              <form className="e-feature-action" onSubmit={(event) => {
                event.preventDefault();
                submit("/api/participants/participant", {
                  trip: tripId, action: "rename", participant_id: participantId,
                  name: draft.name.trim(), reason: draft.reason.trim(),
                  input_fingerprint: fingerprint,
                }, "이름을 정정했습니다.");
              }}>
                {!participantId ? null : (
                  <label className="e-feature-field"><span>이름 정정</span>
                    <input aria-label={`이름 정정 값 · ${name}`} value={draft.name} disabled={!canWrite || !participantId}
                      onChange={(event) => update(participantId, { name: event.currentTarget.value })} />
                  </label>
                )}
                {!participantId ? null : (
                  <label className="e-feature-field"><span>사유</span>
                    <input aria-label={`이름 정정 사유 · ${name}`} value={draft.reason} disabled={!canWrite || !participantId}
                      onChange={(event) => update(participantId, { reason: event.currentTarget.value })} />
                  </label>
                )}
                {!participantId ? null : (
                  <button type="submit" className="cost-button cost-button-quiet" disabled={!canWrite || !participantId}
                    aria-label={`이름 정정 저장 · ${name}`}>이름 정정</button>
                )}
              </form>
              <form className="e-feature-action" onSubmit={(event) => {
                event.preventDefault();
                submit("/api/participants/participant", {
                  trip: tripId, action: "alias", participant_id: participantId,
                  alias: draft.alias.trim(), input_fingerprint: fingerprint,
                }, "별칭을 확인했습니다.");
              }}>
                <label className="e-feature-field"><span>확인된 별칭</span>
                  <input aria-label={`확인된 별칭 값 · ${name}`} value={draft.alias} disabled={!canWrite || !participantId}
                    onChange={(event) => update(participantId, { alias: event.currentTarget.value })} />
                </label>
                <button type="submit" className="cost-button cost-button-quiet" disabled={!canWrite || !participantId}
                  aria-label={`별칭 확인 저장 · ${name}`}>별칭 확인</button>
              </form>
              <form className="e-feature-action" onSubmit={(event) => {
                event.preventDefault();
                submit("/api/participants/participant", {
                  trip: tripId, action: "remap", participant_id: participantId,
                  target_trip: draft.target, reason: draft.reason.trim(),
                  input_fingerprint: fingerprint,
                }, "여행 연결을 수정했습니다.");
              }}>
                {!participantId ? null : !trips.length ? (
                  <p className="e-feature-hint">수정할 여행 선택지가 없습니다.</p>
                ) : (
                  <label className="e-feature-field"><span>여행 선택</span>
                    <select aria-label={`여행 선택 · ${name}`} value={draft.target} disabled={!canWrite || !participantId}
                      onChange={(event) => update(participantId, { target: event.currentTarget.value })}>
                      <option value="">여행 선택</option>
                      {trips.map((trip, tripIndex) => {
                        const tripRecord = record(trip);
                        const value = text(tripRecord.id) || text(tripRecord.tab_id);
                        const label = text(tripRecord.title) || text(tripRecord.display_key) || value || `여행 ${tripIndex + 1}`;
                        return <option key={value || tripIndex} value={value}>{label}</option>;
                      })}
                    </select>
                  </label>
                )}
                {!participantId ? null : (
                  <label className="e-feature-field"><span>사유</span>
                    <input aria-label={`여행 교정 사유 · ${name}`} value={draft.reason} disabled={!canWrite || !participantId}
                      onChange={(event) => update(participantId, { reason: event.currentTarget.value })} />
                  </label>
                )}
                {!participantId ? null : (
                  <button type="submit" className="cost-button cost-button-quiet" disabled={!canWrite || !participantId || !trips.length}
                    aria-label={`여행 연결 수정 · ${name}`}>여행 연결 수정</button>
                )}
              </form>
              {others.length && participantId ? (
                <>
                  <form className="e-feature-action" onSubmit={(event) => {
                    event.preventDefault();
                    submit("/api/participants/participant", {
                      trip: tripId, action: "same_person", participant_id: participantId,
                      other_participant_id: draft.other, input_fingerprint: fingerprint,
                    }, "같은 사람으로 확인했습니다.");
                  }}>
                    <label className="e-feature-field"><span>다른 참가자</span>
                      <select aria-label={`같은 사람으로 확인 대상 · ${name}`} value={draft.other} disabled={!canWrite || !participantId}
                        onChange={(event) => update(participantId, { other: event.currentTarget.value })}>
                        <option value="">다른 참가자 선택</option>
                        {others.map((other, otherIndex) => (
                          <option key={text(other.participant_id) || otherIndex} value={text(other.participant_id)}>
                            {text(other.display_name) || "이름 확인 필요"}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button type="submit" className="cost-button cost-button-quiet" disabled={!canWrite || !participantId}
                      aria-label={`같은 사람 확인 저장 · ${name}`}>같은 사람으로 확인</button>
                  </form>
                  <form className="e-feature-action" onSubmit={(event) => {
                    event.preventDefault();
                    submit("/api/participants/participant", {
                      trip: tripId, action: "separate", participant_id: participantId,
                      other_participant_id: draft.other, input_fingerprint: fingerprint,
                    }, "서로 다른 사람으로 확인했습니다.");
                  }}>
                    <label className="e-feature-field"><span>다른 참가자</span>
                      <select aria-label={`서로 다른 사람으로 확인 대상 · ${name}`} value={draft.other} disabled={!canWrite || !participantId}
                        onChange={(event) => update(participantId, { other: event.currentTarget.value })}>
                        <option value="">다른 참가자 선택</option>
                        {others.map((other, otherIndex) => (
                          <option key={text(other.participant_id) || otherIndex} value={text(other.participant_id)}>
                            {text(other.display_name) || "이름 확인 필요"}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button type="submit" className="cost-button cost-button-quiet" disabled={!canWrite || !participantId}
                      aria-label={`서로 다른 사람 확인 저장 · ${name}`}>서로 다른 사람으로 확인</button>
                  </form>
                </>
              ) : null}
            </div>
          );
        })}
      </section>
    </>
  );
}

export { ParticipantRoster };
