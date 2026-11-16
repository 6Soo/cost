// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FeatureActionPanel } from "./feature-ui";
import { buildStructuredResultModel } from "./action-results";

const bootstrap = {
  role: "owner" as const,
  csrf: "csrf-test",
  trips: [],
  capabilities: [],
  receipt_enabled: false,
};

const participants = {
  trip_id: "trip-synthetic",
  configured: true,
  participants: [{
    participant_id: "person-1",
    display_name: "합성 참가자",
    state: "linked",
    links: [{
      income_ref: "income|2",
      row: { row: 2, name: "합성 입금자", amount: "125000", cells: { B: "2026-04-08" } },
      method: "masked_name_match",
    }],
    candidate_refs: [],
  }],
  unlinked_income: [{ ref: "income|3", row: 3, name: "합성 미연결", amount: "30000", state: "unverified" }],
  counts: { roster_confirmed: 1, linked: 1, unlinked_income_rows: 1 },
  completion: { complete: false, blocked_by: ["ROSTER_INCOMPLETE"] },
};

const insurance = {
  available: true,
  code: "OK",
  message: "합성 보험 대조 상태입니다.",
  counts: { contracts: 1, rows: 1, matched: 1, ambiguous: 0, unmatched: 0, source_unavailable: 0 },
  contracts: [{
    contract_key: "contract-synthetic",
    travel_start: "2026-05-01",
    travel_end: "2026-05-04",
    insurance_status: "확인 완료",
    scope_label: "선택한 여행의 수입에서 대조",
    counts: { matched: 1, ambiguous: 0, unmatched: 0 },
    rows: [{ review_row_id: "insurance-row-4", masked_name: "합*성", match_state: "matched", candidate_count: 1,
      matches: [{ trip_name: "합성 여행", date: "2026-05-02", name: "합성 참가자", amount: "125000" }] }],
  }],
};

const reservePlan = {
  configured: true,
  readable: true,
  counts: { source_identifiers: 2, resolved_transactions: 1, unlinked_identifiers: 1, persons: 1 },
  applicable: false,
  persons: [{ reservation_person_id: "reservation-1", display_name: "합성 예약자", is_active: true, assignments: ["R-100"], connected: [] }],
  resolved: [{ source_event_key: "R-101", target_tab_id: "trip-synthetic", origin: "owner" }],
  unlinked: [{ source_event_key: "R-102" }],
};

describe("structured GET action results", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows participant names and income rows in labeled summaries and tables", () => {
    const model = buildStructuredResultModel("/api/participants/state", participants);

    expect(model.title).toBe("참가자 대조 결과");
    expect(model.summary).toContainEqual({ label: "확정 인원", value: "1명" });
    expect(model.sections.map((section) => section.title)).toContain("참가자 명단");
    expect(model.sections.map((section) => section.title)).toContain("미연결 수입");
    expect(model.sections.flatMap((section) => section.rows.flatMap((row) => Object.values(row))))
      .toContain("합성 참가자");
  });

  it("shows insurance contract scope and match outcomes as tables", () => {
    const model = buildStructuredResultModel("/api/participants/insurance-match", insurance);

    expect(model.title).toBe("보험 대조 결과");
    expect(model.summary).toContainEqual({ label: "대조 계약", value: "1건" });
    expect(model.sections.map((section) => section.title)).toContain("보험 계약");
    expect(model.sections.map((section) => section.title)).toContain("이름 대조 결과");
    expect(model.sections.flatMap((section) => section.rows.flatMap((row) => Object.values(row))))
      .toContain("합성 여행 · 2026-05-02 · 합성 참가자 · 125000원");
  });

  it("shows reservation plan counts, assigned people, resolved and unlinked identifiers", () => {
    const model = buildStructuredResultModel("/api/reserve-link/plan", reservePlan);

    expect(model.title).toBe("예약 연결 계획 결과");
    expect(model.summary).toContainEqual({ label: "연결 예약", value: "1건" });
    expect(model.sections.map((section) => section.title)).toEqual(
      expect.arrayContaining(["예약자", "연결된 예약 식별자", "미연결 예약 식별자"]),
    );
  });

  it("renders the successful GET response in the action panel without dumping raw JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(participants), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));

    render(<FeatureActionPanel
      actions={[{
        id: "participants-state",
        label: "참가자 대조 조회",
        method: "GET",
        href: "/api/participants/state",
        encoding: "form",
        csrf: "none",
        response: "json",
      }]}
      bootstrap={bootstrap}
      onRefresh={() => undefined}
      onNotice={() => undefined}
    />);

    fireEvent.click(screen.getByRole("button", { name: "참가자 대조 조회" }));

    expect(await screen.findByRole("table", { name: "참가자 명단" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "참가자 명단" }).textContent).toContain("합성 참가자");
    expect(screen.getByRole("table", { name: "참가자 명단" }).textContent).toContain("125000원");
    expect(document.body.textContent).not.toContain('"participant_id"');
  });
});
