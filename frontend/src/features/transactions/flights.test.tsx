// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FlightTools } from "./flights";

const bootstrap = {
  role: "owner" as const,
  csrf: "csrf-synthetic",
  trips: [],
  capabilities: [],
  receipt_enabled: false,
};

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const reservation = {
  booking_ref: "SYNTH-PNR-51",
  passenger_name: "KIM ALPHA",
  passengers: ["KIM ALPHA"],
  cancellation_status: "NONE",
  legs: [{ departure_on: "2026-05-12", origin_city: "서울", destination_city: "도쿄", segments: [] }],
  cancelled: false,
  conflict: false,
  source_verified: true,
  linked_cards: [],
  provider: "synthetic-air",
  reserved_on: "2026-04-01",
  booking_card_day: "2026-04-01",
  booking_date_evidence: [],
  booking_date_status: "EXPLICIT_LABEL",
  assigned_trip_tab_id: "cost-trip-synthetic",
  assigned_trip_title: "합성 COST 여행",
  trip_assignment_available: true,
};

const firstSearchPage = {
  reservations: [reservation],
  truncated: true,
  next_offset: 1,
  total: 2,
  revision: "search-revision-synthetic-1",
  source_status: "VERIFIED",
};

const candidateResponse = {
  booking_ref: "SYNTH-PNR-51",
  tour_id: "reservation-tour-synthetic",
  source_revision: "roster-revision-synthetic-1",
  evidence_digest: "evidence-digest-synthetic",
  cancellation_status: "NONE",
  evidence_conflict: false,
  stale_assignments: [],
  passengers: [{
    proposal_id: "proposal-synthetic-1",
    passenger_name_en: "KIM ALPHA",
    status: "AMBIGUOUS",
    cancellation_status: "NONE",
    evidence_conflict: false,
    candidates: [
      { kind: "lead", reference_id: "candidate-synthetic-a", name_kr: "합성 김알파" },
      { kind: "companion", reference_id: "candidate-synthetic-b", name_kr: "합성 김알파 동행" },
    ],
    assignment: null,
    stale_assignments: [],
  }],
};

function props(search = new URLSearchParams()) {
  return { bootstrap, search };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("FlightTools active flight passenger APIs", () => {
  it("searches by name and loads more with the exact source revision", async () => {
    const calls: Array<{ url: string; init?: RequestInit; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      const call = { url: url.pathname, init, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      if (url.pathname === "/api/flight-passengers/name-search") {
        return calls.length === 1 ? response(firstSearchPage) : response({
          ...firstSearchPage,
          reservations: [{ ...reservation, booking_ref: "SYNTH-PNR-52", passenger_name: "KIM BETA" }],
          next_offset: null,
          source_status: "VERIFIED",
        });
      }
      throw new Error(`Unexpected synthetic request: ${url.pathname}`);
    }));

    render(<FlightTools {...props(new URLSearchParams("q=KIM&trip=cost-trip-synthetic"))} />);
    fireEvent.click(screen.getByRole("button", { name: "예약 검색" }));

    expect(await screen.findByText("KIM ALPHA")).toBeTruthy();
    expect(calls[0].body).toEqual({ name: "KIM", offset: 0, revision: null });
    expect(calls[0].init?.headers).toMatchObject({ "X-CSRF-Token": "csrf-synthetic" });
    expect(screen.getByText("더 보기")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "더 보기" }));
    expect(await screen.findByText("KIM BETA")).toBeTruthy();
    expect(calls[1].body).toEqual({ name: "KIM", offset: 1, revision: "search-revision-synthetic-1" });
  });

  it("loads candidates with the separate reservation tour ID and saves only an explicit COST link", async () => {
    const calls: Array<{ url: URL; init?: RequestInit; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      const call = { url, init, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      if (url.pathname === "/api/flight-passengers/name-search") return response(firstSearchPage);
      if (url.pathname === "/api/flight-passengers/candidates") return response(candidateResponse);
      if (url.pathname === "/api/flight-passengers/assign") {
        return response({ code: "OK", assignment: { candidate_reference_id: "candidate-synthetic-b" } });
      }
      throw new Error(`Unexpected synthetic request: ${url.pathname}`);
    }));

    render(<FlightTools {...props(new URLSearchParams("q=KIM&trip=cost-trip-synthetic&tour_id=reservation-tour-synthetic"))} />);
    fireEvent.click(screen.getByRole("button", { name: "예약 검색" }));
    expect(await screen.findByText("KIM ALPHA")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "후보 확인" }));

    expect(await screen.findByRole("radio", { name: /동행인 합성 김알파 동행/ })).toBeTruthy();
    const candidateCall = calls.find((call) => call.url.pathname === "/api/flight-passengers/candidates");
    expect(candidateCall?.url.searchParams.get("booking_ref")).toBe("SYNTH-PNR-51");
    expect(candidateCall?.url.searchParams.get("tour_id")).toBe("reservation-tour-synthetic");
    expect(candidateCall?.url.searchParams.get("tour_id")).not.toBe("cost-trip-synthetic");

    fireEvent.click(screen.getByRole("radio", { name: /합성 김알파 동행/ }));
    fireEvent.click(screen.getByRole("button", { name: "선택한 참가자를 COST에 연결" }));
    expect(await screen.findByText("COST 내부 연결을 저장했습니다. 실제 탑승 여부는 확인되지 않았습니다.")).toBeTruthy();

    const assignment = calls.find((call) => call.url.pathname === "/api/flight-passengers/assign");
    expect(assignment?.init?.method).toBe("POST");
    expect(assignment?.init?.headers).toMatchObject({ "X-CSRF-Token": "csrf-synthetic" });
    expect(assignment?.body).toEqual({
      booking_ref: "SYNTH-PNR-51",
      tour_id: "reservation-tour-synthetic",
      proposal_id: "proposal-synthetic-1",
      candidate_reference_id: "candidate-synthetic-b",
    });
    expect(document.body.textContent).not.toContain("실제 탑승을 확인했습니다");
  });

  it("never treats a COST trip ID as the reservation-system tour ID", async () => {
    const calls: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      calls.push(url);
      if (url.pathname === "/api/flight-passengers/name-search") return response(firstSearchPage);
      if (url.pathname === "/api/flight-passengers/candidates") return response(candidateResponse);
      throw new Error(`Unexpected synthetic request: ${url.pathname}`);
    }));

    render(<FlightTools {...props(new URLSearchParams("q=KIM&trip=cost-trip-synthetic"))} />);
    fireEvent.click(screen.getByRole("button", { name: "예약 검색" }));
    expect(await screen.findByText("KIM ALPHA")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "후보 확인" }));
    expect((await screen.findByRole("alert")).textContent).toContain("COST 여행 ID와 다른 값입니다.");
    expect(calls.some((url) => url.pathname === "/api/flight-passengers/candidates")).toBe(false);

    fireEvent.change(screen.getByLabelText("예약 시스템 여행 ID"), { target: { value: "reservation-tour-manual" } });
    fireEvent.click(screen.getByRole("button", { name: "후보 조회" }));
    expect(await screen.findByRole("radio", { name: /예약자 합성 김알파/ })).toBeTruthy();
    const candidateUrl = calls.find((url) => url.pathname === "/api/flight-passengers/candidates");
    expect(candidateUrl?.searchParams.get("trip")).toBeNull();
    expect(candidateUrl?.searchParams.get("tour_id")).toBe("reservation-tour-manual");
  });

  it("shows an unavailable source as an error state instead of an empty successful search", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({
      reservations: [], truncated: false, next_offset: null, total: 0,
      revision: "unavailable-revision-synthetic", source_status: "UNAVAILABLE",
    })));

    render(<FlightTools {...props(new URLSearchParams("q=KIM"))} />);
    fireEvent.click(screen.getByRole("button", { name: "예약 검색" }));
    expect(await screen.findByText("최근 항공권 자료를 확인할 수 없습니다. 원본 상태를 확인한 뒤 다시 검색해 주세요.")).toBeTruthy();
    expect(screen.queryByText("검색 조건에 맞는 확인된 항공권 예약이 없습니다.")).toBeNull();
  });

  it("clears paginated results when the server rejects a stale source revision", async () => {
    const calls: Array<{ url: string; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url: url.pathname, body });
      return calls.length === 1 ? response(firstSearchPage) : response({ code: "SOURCE_CHANGED" }, 409);
    }));

    render(<FlightTools {...props()} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "탑승객 이름·경로·날짜" }), { target: { value: "KIM ALPHA" } });
    fireEvent.click(screen.getByRole("button", { name: "예약 검색" }));
    expect(await screen.findByText("KIM ALPHA")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "더 보기" }));

    expect((await screen.findByRole("alert")).textContent).toContain("항공권 자료가 변경됐습니다. 처음부터 다시 검색해 주세요.");
    expect(screen.queryByText("SYNTH-PNR-51")).toBeNull();
    expect(calls[1].body).toEqual({ name: "KIM ALPHA", offset: 1, revision: "search-revision-synthetic-1" });
  });

  it("blocks candidate selection for cancelled/conflicting evidence and explains unavailable authorities", async () => {
    let candidateResult: Record<string, unknown> = {
      ...candidateResponse,
      cancellation_status: "CANCELLED",
      stale_assignments: [{ assignment_status: "USER_ASSIGNED", stale: true }],
      passengers: [],
    };
    let assignmentAttempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/flight-passengers/name-search") return response(firstSearchPage);
      if (url.pathname === "/api/flight-passengers/candidates") return response(candidateResult);
      if (url.pathname === "/api/flight-passengers/assign") {
        assignmentAttempts += 1;
        return assignmentAttempts === 1
          ? response({ code: "PASSENGER_CANDIDATES_STALE" }, 409)
          : response({ code: "RESERVATION_AUTHORITY_UNAUTHORIZED" }, 503);
      }
      return response({ code: "RESERVATION_AUTHORITY_UNAUTHORIZED" }, 503);
    }));

    render(<FlightTools {...props(new URLSearchParams("q=KIM&tour_id=reservation-tour-synthetic"))} />);
    fireEvent.click(screen.getByRole("button", { name: "예약 검색" }));
    expect(await screen.findByText("KIM ALPHA")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "후보 확인" }));
    expect((await screen.findByRole("alert")).textContent).toContain("취소된 항공권 근거로는 연결할 수 없습니다.");
    expect(screen.queryByRole("radio")).toBeNull();

    candidateResult = { ...candidateResponse, evidence_conflict: true, cancellation_status: "NONE" };
    fireEvent.click(screen.getByRole("button", { name: "후보 다시 불러오기" }));
    expect(await screen.findByText("항공권 원본 자료가 서로 달라 연결할 수 없습니다. 원본을 확인해 주세요.")).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();

    candidateResult = { ...candidateResponse, cancellation_status: "NONE", evidence_conflict: false };
    fireEvent.click(screen.getByRole("button", { name: "후보 다시 불러오기" }));
    expect(await screen.findByRole("radio", { name: /예약자 합성 김알파/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /예약자 합성 김알파/ }));
    fireEvent.click(screen.getByRole("button", { name: "선택한 참가자를 COST에 연결" }));

    expect((await screen.findByRole("alert")).textContent).toContain("최신 후보를 다시 불러와 확인해 주세요.");
    expect(screen.queryByRole("radio")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "후보 조회" }));
    expect(await screen.findByRole("radio", { name: /예약자 합성 김알파/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /예약자 합성 김알파/ }));
    fireEvent.click(screen.getByRole("button", { name: "선택한 참가자를 COST에 연결" }));
    expect(await screen.findByText("예약 서비스 인증이 만료됐습니다. 관리자에게 문의해 주세요.")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /예약자 합성 김알파$/ })).toBeTruthy();
    expect(assignmentAttempts).toBe(2);
  });
});
