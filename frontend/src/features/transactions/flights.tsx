import { useRef, useState, type FormEvent } from "react";
import { ApiError, getJSON, postJSON } from "../../api/client";
import type { Bootstrap } from "../../api/types";

type FlightToolsProps = { bootstrap: Bootstrap; search: URLSearchParams };

type FlightLeg = {
  departure_on?: string;
  origin_city?: string;
  destination_city?: string;
  segments?: Array<{ departure_airport?: string; arrival_airport?: string }>;
};

type Reservation = {
  booking_ref: string;
  passenger_name: string;
  passengers?: string[];
  cancellation_status?: string;
  cancelled?: boolean;
  conflict?: boolean;
  legs?: FlightLeg[];
  provider?: string;
  linked_cards?: Array<Record<string, unknown>>;
  assigned_trip_tab_id?: string;
  assigned_trip_title?: string;
  trip_assignment_available?: boolean;
};

type NameSearchResponse = {
  reservations: Reservation[];
  truncated: boolean;
  next_offset: number | null;
  total: number;
  revision: string;
  source_status: string;
};

type Candidate = {
  kind: string;
  reference_id: string;
  name_kr: string;
  name_en?: string;
  status?: string;
};

type PassengerProposal = {
  proposal_id: string;
  passenger_name_en: string;
  status: string;
  cancellation_status: string;
  evidence_conflict: boolean;
  candidates: Candidate[];
  assignment?: {
    stale?: boolean;
    candidate?: Candidate | null;
    candidate_reference_id?: string;
  } | null;
  stale_assignments?: Array<Record<string, unknown>>;
};

type CandidateResponse = {
  booking_ref: string;
  tour_id: string;
  source_revision: string;
  evidence_digest: string;
  cancellation_status: string;
  evidence_conflict: boolean;
  stale_assignments: Array<Record<string, unknown>>;
  passengers: PassengerProposal[];
};

type AssignmentResponse = {
  code: string;
  assignment: Record<string, unknown>;
};

const API = {
  nameSearch: "/api/flight-passengers/name-search",
  candidates: "/api/flight-passengers/candidates",
  assign: "/api/flight-passengers/assign",
} as const;

function apiMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof TypeError
      ? "항공권 서버에 연결하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요."
      : "항공권 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
  }

  const messages: Record<string, string> = {
    ACTION_FORBIDDEN: "항공권 조회와 연결은 owner만 사용할 수 있습니다.",
    CSRF_REQUIRED: "인증 확인이 만료됐습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.",
    FEATURE_DISABLED: "항공권 기능이 현재 사용 중지되어 있습니다.",
    INVALID_NAME: "탑승객 이름, 경로 또는 날짜를 입력해 주세요.",
    INVALID_VALUE: "예약번호와 예약 시스템 여행 ID를 확인해 주세요.",
    PASSENGER_AUTHORITY_INVALID: "예약 명단 응답을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    PASSENGER_ASSIGNMENT_ALREADY_CONFIRMED: "이미 다른 COST 연결이 저장되어 있습니다. 최신 후보를 다시 불러와 확인해 주세요.",
    PASSENGER_CANDIDATE_REQUIRED: "항공권 원본이나 후보가 변경됐습니다. 후보를 다시 불러와 선택해 주세요.",
    PASSENGER_CANDIDATES_STALE: "항공권 원본 또는 예약 명단이 변경됐습니다. 최신 후보를 다시 불러와 확인해 주세요.",
    RESOURCE_NOT_FOUND: "요청한 항공권 자료를 찾을 수 없습니다.",
    SOURCE_CHANGED: "항공권 자료가 변경됐습니다. 처음부터 다시 검색해 주세요.",
    STORE_UNAVAILABLE: "항공권 자료를 사용할 수 없습니다. 저장소 상태를 확인한 뒤 다시 시도해 주세요.",
    FLIGHT_PASSENGER_STORE_NOT_CONFIGURED: "COST 내부 연결 저장소가 설정되지 않았습니다. 관리자에게 문의해 주세요.",
    VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND: "확인된 항공권 예약 근거를 찾지 못했습니다. 예약번호를 확인해 주세요.",
    INVALID_RESPONSE: "로그인이 만료됐거나 서버 응답을 읽을 수 없습니다. 새로고침한 뒤 다시 시도해 주세요.",
  };

  if (error.code === "RESERVATION_AUTHORITY_UNAUTHORIZED") {
    return "예약 서비스 인증이 만료됐습니다. 관리자에게 문의해 주세요.";
  }
  if (error.code.startsWith("RESERVATION_AUTHORITY_")) {
    return "예약 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.";
  }
  if (messages[error.code]) return messages[error.code];
  if (/^PASSENGER_/.test(error.code)) {
    return "예약 근거나 참가자 후보가 변경됐습니다. 최신 후보를 다시 불러와 확인해 주세요.";
  }
  return error.message && !/^[A-Z0-9_]+$/.test(error.message)
    ? error.message
    : "항공권 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

function isSourceChanged(error: unknown) {
  return error instanceof ApiError && error.code === "SOURCE_CHANGED";
}

function reservationSummary(row: Reservation) {
  const leg = row.legs?.find((item) => item.departure_on || item.origin_city || item.destination_city);
  if (!leg) return "여행 일정 정보가 없습니다.";
  const route = [leg.origin_city, leg.destination_city].filter(Boolean).join(" → ");
  const airports = leg.segments?.map((segment) => [segment.departure_airport, segment.arrival_airport]
    .filter(Boolean).join(" → ")).filter(Boolean)[0];
  return [leg.departure_on, route || airports].filter(Boolean).join(" · ") || "여행 일정 정보가 없습니다.";
}

function kindLabel(kind: string) {
  if (kind === "lead") return "예약자";
  if (kind === "companion") return "동행인";
  if (kind === "guide") return "안내자";
  return "참가자";
}

function passengerStatusLabel(status: string) {
  const labels: Record<string, string> = {
    EXACT_CANDIDATE: "후보 1명",
    AMBIGUOUS: "복수 후보",
    UNMATCHED: "후보 없음",
    CANCELLED_EVIDENCE: "취소 확인",
    CONFLICTING_EVIDENCE: "자료 충돌",
  };
  return labels[status] || "상태 확인 필요";
}

function sourceStatusMessage(status: string) {
  if (status === "LOADING") return "항공권 원본 자료를 준비하고 있습니다. 잠시 후 다시 검색해 주세요.";
  if (status === "UNAVAILABLE") return "최근 항공권 자료를 확인할 수 없습니다. 원본 상태를 확인한 뒤 다시 검색해 주세요.";
  return "검색 조건에 맞는 확인된 항공권 예약이 없습니다.";
}

export function FlightTools({ bootstrap, search }: FlightToolsProps) {
  const [name, setName] = useState(search.get("q") || "");
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [total, setTotal] = useState(0);
  const [sourceStatus, setSourceStatus] = useState("");
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [revision, setRevision] = useState<string | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchError, setSearchError] = useState("");
  const searchGeneration = useRef(0);

  const [candidateBookingRef, setCandidateBookingRef] = useState(search.get("booking_ref") || "");
  const [tourId, setTourId] = useState(search.get("tour_id") || "");
  const [candidateData, setCandidateData] = useState<CandidateResponse | null>(null);
  const [candidateBusy, setCandidateBusy] = useState(false);
  const [candidateError, setCandidateError] = useState("");
  const [candidateMessage, setCandidateMessage] = useState("");
  const [selectedCandidates, setSelectedCandidates] = useState<Record<string, string>>({});
  const [assigningProposal, setAssigningProposal] = useState("");
  const [savedProposals, setSavedProposals] = useState<Record<string, boolean>>({});
  const candidateGeneration = useRef(0);

  async function searchReservations(offset: number, sourceRevision: string | null) {
    const query = name.trim();
    setSearchError("");
    if (!query) {
      searchGeneration.current += 1;
      setReservations([]);
      setTotal(0);
      setNextOffset(null);
      setRevision(null);
      setSourceStatus("");
      candidateGeneration.current += 1;
      setCandidateData(null);
      setCandidateBusy(false);
      setCandidateError("");
      setSearchError("탑승객 이름, 경로 또는 날짜를 입력해 주세요.");
      return;
    }

    const requestGeneration = ++searchGeneration.current;
    const isFirstPage = offset === 0;
    setSearchBusy(true);
    if (isFirstPage) {
      setReservations([]);
      setTotal(0);
      setNextOffset(null);
      setRevision(null);
      setSourceStatus("");
      candidateGeneration.current += 1;
      setCandidateData(null);
      setCandidateBusy(false);
      setCandidateError("");
      setCandidateMessage("");
    }

    try {
      const result = await postJSON<NameSearchResponse>(API.nameSearch, {
        name: query,
        offset,
        revision: sourceRevision,
      }, bootstrap.csrf);
      if (requestGeneration !== searchGeneration.current) return;
      setReservations((current) => isFirstPage ? result.reservations : [...current, ...result.reservations]);
      setTotal(result.total);
      setSourceStatus(result.source_status);
      setRevision(result.revision);
      setNextOffset(Number.isSafeInteger(result.next_offset) ? result.next_offset : null);
    } catch (error) {
      if (requestGeneration !== searchGeneration.current) return;
      if (isSourceChanged(error)) {
        setReservations([]);
        setTotal(0);
        setNextOffset(null);
        setRevision(null);
        setSourceStatus("");
        candidateGeneration.current += 1;
        setCandidateData(null);
        setCandidateBusy(false);
        setCandidateError("");
        setCandidateMessage("");
        setSearchError("항공권 자료가 변경됐습니다. 처음부터 다시 검색해 주세요.");
      } else {
        setSearchError(apiMessage(error));
      }
    } finally {
      if (requestGeneration === searchGeneration.current) setSearchBusy(false);
    }
  }

  async function loadCandidates(bookingRef: string) {
    const requestGeneration = ++candidateGeneration.current;
    const booking = bookingRef.trim();
    const externalTourId = tourId.trim();
    setCandidateBookingRef(booking);
    setCandidateError("");
    setCandidateMessage("");
    if (!booking || !externalTourId) {
      setCandidateData(null);
      setCandidateBusy(false);
      setCandidateError(!booking
        ? "예약번호를 입력하거나 검색 결과에서 예약을 선택해 주세요."
        : "예약 시스템 여행 ID를 입력해 주세요. COST 여행 ID와 다른 값입니다.");
      return;
    }

    setCandidateBusy(true);
    setCandidateData(null);
    setSelectedCandidates({});
    try {
      const params = new URLSearchParams({ booking_ref: booking, tour_id: externalTourId });
      const result = await getJSON<CandidateResponse>(`${API.candidates}?${params.toString()}`);
      if (requestGeneration !== candidateGeneration.current) return;
      setCandidateData(result);
      setSavedProposals({});
    } catch (error) {
      if (requestGeneration !== candidateGeneration.current) return;
      setCandidateData(null);
      setCandidateError(apiMessage(error));
    } finally {
      if (requestGeneration === candidateGeneration.current) setCandidateBusy(false);
    }
  }

  async function submitNameSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await searchReservations(0, null);
  }

  async function submitCandidateSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await loadCandidates(candidateBookingRef);
  }

  async function saveCandidate(passenger: PassengerProposal) {
    if (!candidateData) return;
    const candidateReferenceId = selectedCandidates[passenger.proposal_id];
    if (!candidateReferenceId) {
      setCandidateError("COST에 연결할 참가자를 먼저 선택해 주세요.");
      return;
    }

    setCandidateError("");
    setCandidateMessage("");
    setAssigningProposal(passenger.proposal_id);
    try {
      await postJSON<AssignmentResponse>(API.assign, {
        booking_ref: candidateData.booking_ref,
        tour_id: candidateData.tour_id,
        proposal_id: passenger.proposal_id,
        candidate_reference_id: candidateReferenceId,
      }, bootstrap.csrf);
      setSavedProposals((current) => ({ ...current, [passenger.proposal_id]: true }));
      setCandidateMessage("COST 내부 연결을 저장했습니다. 실제 탑승 여부는 확인되지 않았습니다.");
    } catch (error) {
      if (error instanceof ApiError && [
        "PASSENGER_CANDIDATE_REQUIRED",
        "PASSENGER_CANDIDATES_STALE",
        "PASSENGER_ASSIGNMENT_ALREADY_CONFIRMED",
      ].includes(error.code)) {
        setCandidateData(null);
        setSelectedCandidates({});
      }
      setCandidateError(apiMessage(error));
    } finally {
      setAssigningProposal("");
    }
  }

  const outerBlocked = candidateData?.cancellation_status === "CANCELLED" ||
    candidateData?.cancellation_status === "CONFLICT" || candidateData?.evidence_conflict;

  return (
    <section className="cost-panel" aria-label="항공권 참가자 연결" style={{ display: "grid", gap: "16px", marginBlock: "16px" }}>
      <header>
        <h2>항공권 참가자 연결</h2>
        <p className="e-feature-status">확인된 항공권 자료를 검색하고 예약 명단 후보를 대조합니다. COST 내부 연결은 실제 탑승 확인이 아닙니다.</p>
      </header>

      <form onSubmit={submitNameSearch} role="search" aria-label="항공권 예약 검색"
        style={{ display: "flex", alignItems: "end", flexWrap: "wrap", gap: "12px" }}>
        <label className="e-feature-field" htmlFor="flight-name-search" style={{ flex: "1 1 240px", minWidth: 0 }}>
          <span>탑승객 이름·경로·날짜</span>
          <input id="flight-name-search" name="name" type="search" value={name} autoComplete="off"
            maxLength={100}
            onChange={(event) => setName(event.currentTarget.value)} />
        </label>
        <button type="submit" className="cost-button" disabled={searchBusy}>
          {searchBusy ? "검색 중…" : "예약 검색"}
        </button>
      </form>
      {searchError ? <p role="alert" className="e-feature-error">{searchError}</p> : null}
      {searchBusy && reservations.length === 0 ? <p role="status">항공권 예약 자료를 검색하고 있습니다…</p> : null}
      {sourceStatus === "LOADING" || sourceStatus === "UNAVAILABLE"
        ? <p role="status" className="e-feature-status">{sourceStatusMessage(sourceStatus)}</p> : null}
      {sourceStatus && reservations.length === 0 && sourceStatus !== "LOADING" && sourceStatus !== "UNAVAILABLE"
        ? <p role="status" className="e-feature-status">{sourceStatusMessage(sourceStatus)}</p> : null}

      {reservations.length ? (
        <section aria-label="항공권 검색 결과" style={{ display: "grid", gap: "10px", minWidth: 0 }}>
          <h3>검색 결과 {reservations.length} / {total}건</h3>
          {reservations.map((row, index) => (
            <article className="cost-panel" key={`${row.booking_ref}-${index}`}
              style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "12px", minWidth: 0 }}>
              <div style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                <h4>{row.passenger_name || "탑승객 이름 없음"}</h4>
                <p>{reservationSummary(row)}</p>
                <p>예약번호 · {row.booking_ref}</p>
                {row.assigned_trip_title ? <p>COST 여행 · {row.assigned_trip_title}</p> : null}
                {row.trip_assignment_available === false
                  ? <p className="e-feature-status">이 항공권의 COST 여행 연결 정보를 확인할 수 없습니다.</p> : null}
                {row.conflict || row.cancellation_status === "CONFLICT"
                  ? <p className="e-feature-status">항공권 자료 충돌 · 원본을 확인해 주세요.</p> : null}
                {row.cancelled || row.cancellation_status === "CANCELLED"
                  ? <p className="e-feature-status">취소된 항공권 예약 자료입니다.</p> : null}
              </div>
              <button type="button" className="cost-button cost-button-secondary" disabled={candidateBusy}
                onClick={() => { void loadCandidates(row.booking_ref); }}>
                후보 확인
              </button>
            </article>
          ))}
          {nextOffset !== null && revision ? (
            <button type="button" className="cost-button cost-button-secondary" disabled={searchBusy}
              onClick={() => { void searchReservations(nextOffset, revision); }}>
              {searchBusy ? "불러오는 중…" : "더 보기"}
            </button>
          ) : null}
        </section>
      ) : null}

      <section aria-label="예약 명단 후보 조회" style={{ display: "grid", gap: "10px", minWidth: 0 }}>
        <h3>예약 명단 후보</h3>
        <p className="e-feature-status">예약 시스템 여행 ID는 COST의 여행·탭 ID와 다릅니다. 예약 시스템에서 확인한 값을 입력하세요.</p>
        <form onSubmit={submitCandidateSearch} style={{ display: "flex", alignItems: "end", flexWrap: "wrap", gap: "12px" }}>
          <label className="e-feature-field" htmlFor="flight-candidate-booking" style={{ flex: "1 1 180px", minWidth: 0 }}>
            <span>항공권 예약번호</span>
            <input id="flight-candidate-booking" name="booking_ref" type="search" value={candidateBookingRef}
              autoComplete="off" onChange={(event) => setCandidateBookingRef(event.currentTarget.value)} />
          </label>
          <label className="e-feature-field" htmlFor="flight-reservation-tour" style={{ flex: "1 1 220px", minWidth: 0 }}>
            <span>예약 시스템 여행 ID</span>
            <input id="flight-reservation-tour" name="tour_id" type="search" value={tourId}
              autoComplete="off" onChange={(event) => setTourId(event.currentTarget.value)} />
          </label>
          <button type="submit" className="cost-button cost-button-secondary" disabled={candidateBusy}>
            {candidateBusy ? "후보 조회 중…" : "후보 조회"}
          </button>
        </form>

        {candidateError ? <p role="alert" className="e-feature-error">{candidateError}</p> : null}
        {candidateBusy ? <p role="status">예약 명단과 대조하고 있습니다…</p> : null}
        {candidateData ? (
          <section aria-label="참가자 후보 결과" style={{ display: "grid", gap: "12px", minWidth: 0 }}>
            {candidateData.stale_assignments?.length ? (
              <p className="e-feature-status">이전 COST 연결의 항공권 근거가 변경됐습니다. 현재 자료를 확인해 주세요.</p>
            ) : null}
            {outerBlocked ? (
              <p role="alert" className="e-feature-error">
                {candidateData.cancellation_status === "CANCELLED"
                  ? "취소된 항공권 근거로는 연결할 수 없습니다. 예약 상태를 확인해 주세요."
                  : "항공권 원본 자료가 서로 달라 연결할 수 없습니다. 원본을 확인해 주세요."}
              </p>
            ) : null}
            {candidateData.passengers.length ? candidateData.passengers.map((passenger) => {
              const existingAssignment = passenger.assignment;
              const blocked = Boolean(outerBlocked || passenger.evidence_conflict ||
                passenger.cancellation_status !== "NONE");
              const alreadySaved = Boolean(savedProposals[passenger.proposal_id] ||
                (existingAssignment && !existingAssignment.stale));
              const candidates = blocked ? [] : passenger.candidates || [];
              return (
                <article className="cost-panel" key={passenger.proposal_id} style={{ display: "grid", gap: "8px", minWidth: 0 }}>
                  <h4>{passenger.passenger_name_en || "항공권 탑승객"} · {passengerStatusLabel(passenger.status)}</h4>
                  {existingAssignment?.stale ? <p className="e-feature-status">저장된 연결의 원본이 변경됐습니다. 현재 후보를 다시 확인해 주세요.</p> : null}
                  {existingAssignment && !existingAssignment.stale ? (
                    <p role="status">저장된 COST 연결 · {existingAssignment.candidate?.name_kr || "사용자가 확인한 참가자"}</p>
                  ) : null}
                  {passenger.stale_assignments?.length ? <p className="e-feature-status">이 승객의 이전 연결 기록은 현재 자료와 일치하지 않습니다.</p> : null}
                  {!blocked && !candidates.length
                    ? <p>연결할 참가자 후보가 없습니다. 예약 명단과 탑승객 이름을 확인해 주세요.</p> : null}
                  {candidates.length > 1 ? <p className="e-feature-status">후보가 여러 명입니다. 예약 정보를 확인하고 한 명을 직접 선택해 주세요.</p> : null}
                  {candidates.map((candidate, index) => (
                    <label key={candidate.reference_id} style={{ display: "flex", alignItems: "center", gap: "8px", minHeight: "44px", overflowWrap: "anywhere" }}>
                      <input type="radio" name={`candidate-${passenger.proposal_id}`}
                        aria-label={`${kindLabel(candidate.kind)} ${candidate.name_kr}`}
                        value={candidate.reference_id}
                        checked={selectedCandidates[passenger.proposal_id] === candidate.reference_id}
                        disabled={blocked || alreadySaved || assigningProposal === passenger.proposal_id}
                        onChange={() => setSelectedCandidates((current) => ({
                          ...current, [passenger.proposal_id]: candidate.reference_id,
                        }))} />
                      <span>{candidates.length > 1 ? `${kindLabel(candidate.kind)} 후보 ${index + 1} · ` : `${kindLabel(candidate.kind)} · `}{candidate.name_kr}</span>
                    </label>
                  ))}
                  {candidates.length && !blocked ? (
                    <button type="button" className="cost-button" disabled={alreadySaved || assigningProposal === passenger.proposal_id}
                      onClick={() => { void saveCandidate(passenger); }}>
                      {assigningProposal === passenger.proposal_id ? "COST에 저장 중…"
                        : alreadySaved ? "COST 내부 연결 저장됨"
                          : "선택한 참가자를 COST에 연결"}
                    </button>
                  ) : null}
                </article>
              );
            }) : <p>이 예약에서 확인할 탑승자 정보를 찾지 못했습니다.</p>}
          </section>
        ) : null}
        {candidateMessage ? <p role="status" className="e-feature-status">{candidateMessage}</p> : null}
        {candidateData ? <button type="button" className="cost-button cost-button-quiet" disabled={candidateBusy}
          onClick={() => { void loadCandidates(candidateData.booking_ref); }}>
          후보 다시 불러오기
        </button> : null}
      </section>
    </section>
  );
}
