// @vitest-environment jsdom
// 수락 기준 #10(없는 대상 주소는 404 화면과 상태 코드)의 장부 화면 시험.
// 서버가 없는 여행 id에 404(RESOURCE_NOT_FOUND)를 주면 화면 제목은 '찾을 수 없음'이어야 하고,
// 404가 아닌 오류는 일반 장부 제목을 유지해야 한다. 서버 404 자체는 webapp/tests/test_plush_api.py가 검증한다.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LedgerPage } from "../../src/features/ledger";
import { ApiError, getJSON, postJSON } from "../../src/api/client";
import type { Bootstrap, TripSummary } from "../../src/api/types";

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

function bootstrap(): Bootstrap {
  return { role: "owner", csrf: "synthetic-csrf", trips: [trip], capabilities: [], receipt_enabled: false };
}

beforeEach(() => {
  vi.mocked(postJSON).mockResolvedValue({});
  window.history.replaceState(null, "", "/board?tab=trip-missing&kind=expense");
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("수락 #10 없는 여행 404 화면", () => {
  it("없는 여행 id의 404 응답이면 제목이 '찾을 수 없음'이고 서버 안내를 보여준다", async () => {
    vi.mocked(getJSON).mockRejectedValue(new ApiError("RESOURCE_NOT_FOUND", 404, "없는 여행이에요"));
    render(<LedgerPage bootstrap={bootstrap()} path="/board" search={new URLSearchParams("tab=trip-missing&kind=expense")} />);
    const heading = await screen.findByRole("heading", { level: 1, name: /찾을 수 없음/ });
    expect(heading.textContent).toContain("찾을 수 없음");
    expect(await screen.findByText("없는 여행이에요")).toBeTruthy();
  });

  it("404가 아닌 오류는 '찾을 수 없음' 제목을 쓰지 않고 일반 장부 제목을 유지한다", async () => {
    vi.mocked(getJSON).mockRejectedValue(new ApiError("STORE_UNBOUND", 503, "저장소가 연결되지 않았어요"));
    render(<LedgerPage bootstrap={bootstrap()} path="/board" search={new URLSearchParams("tab=trip-missing&kind=expense")} />);
    await screen.findByText("저장소가 연결되지 않았어요");
    expect(screen.queryByRole("heading", { level: 1, name: /찾을 수 없음/ })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "여행 장부" })).toBeTruthy();
  });
});
