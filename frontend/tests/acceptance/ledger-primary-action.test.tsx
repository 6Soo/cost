// @vitest-environment jsdom
// 수락 기준 #13(한 화면에 주 행동은 하나)의 장부 화면 시험.
// 기본 강조(primary) 버튼은 화면당 1개여야 하고, 복사·내보내기는 보조 동작이어야 한다.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LedgerPage } from "../../src/features/ledger";
import { getJSON, postJSON } from "../../src/api/client";
import type { Bootstrap, LedgerRow, TripSummary } from "../../src/api/types";

vi.mock("../../src/api/client", async (original) => ({
  ...await original<typeof import("../../src/api/client")>(),
  getJSON: vi.fn(),
  postJSON: vi.fn(),
}));

const trip: TripSummary = {
  id: "trip-synthetic", title: "합성 여행", kind: "trip", previous: false,
  starts_on: "2026-11-10", ends_on: "2026-11-20",
  income: "0", expense: "100", profit: "-100", closed: false, archived: false,
};
const row: LedgerRow = {
  id: "row-synthetic", date: "2026-11-16", merchant: "합성 상점", description: "",
  category: "교통비", amount: "100", currency: "KRW", payment: "현금", period: "",
  evidence_summary: "", read_only: false,
};
const payload = {
  trip, rows: [row], total_count: 1, page: 1, page_size: 50,
  filtered_total: "100", total: "100", closed: false,
};

function bootstrap(role: "owner" | "viewer"): Bootstrap {
  return { role, csrf: "synthetic-csrf", trips: [trip], capabilities: [], receipt_enabled: false };
}

const PRIMARY = 'button.cost-action-button[data-variant="default"]';

beforeEach(() => {
  vi.mocked(getJSON).mockResolvedValue(payload);
  vi.mocked(postJSON).mockResolvedValue({});
  window.history.replaceState(null, "", "/board?tab=trip-synthetic&kind=expense");
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("수락 #13 장부 주 행동", () => {
  it("소유자 장부의 기본 강조 버튼은 1개(수기 지출 추가)이고 복사·내보내기는 보조다", async () => {
    render(<LedgerPage bootstrap={bootstrap("owner")} path="/board" search={new URLSearchParams("tab=trip-synthetic&kind=expense")} />);
    await screen.findByRole("button", { name: /수기 지출 추가/ });
    const primary = document.querySelectorAll(PRIMARY);
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toContain("수기 지출 추가");
    expect(screen.getByRole("button", { name: /Google 장부용 복사/ }).getAttribute("data-variant")).toBe("secondary");
    expect(screen.getByRole("button", { name: /XLSX 내보내기/ }).getAttribute("data-variant")).toBe("ghost");
  });

  it("열람 권한에는 동작 그룹(복사·내보내기·쓰기)이 전혀 없다", async () => {
    render(<LedgerPage bootstrap={bootstrap("viewer")} path="/board" search={new URLSearchParams("tab=trip-synthetic&kind=expense")} />);
    await screen.findByText("조회 합계");
    expect(document.querySelectorAll(PRIMARY)).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /수기 지출 추가/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Google 장부용 복사/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /XLSX 내보내기/ })).toBeNull();
  });
});
