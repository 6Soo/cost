// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import { TransactionsPage } from "./index";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows reviewed cancellations separately from linked refunds", async () => {
  const bootstrap: Bootstrap = {
    role: "owner", csrf: "synthetic", trips: [], capabilities: [], receipt_enabled: false,
  };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    view: "refunds", columns: [], rows: [], total_count: 0, page: 1, page_size: 100, actions: [],
    settlement_review: [{
      id: "synthetic", merchant: "합성 거래", date: "2026-11-01", amount: "-40000",
      description: "취소 근거 확인", status: "내부 장부 미기록",
      hold: "환급 근거 확인 중", note: "합성 대사 기록", source_href: "/board?row=card-synthetic",
    }],
  }), { headers: {"content-type": "application/json"} })));

  render(<TransactionsPage bootstrap={bootstrap} path="/board" search={new URLSearchParams("tab=refunds")} />);

  const panel = await screen.findByRole("region", { name: "취소 정산 확인 중 · 1건" });
  expect(within(panel).getAllByText("내부 장부 미기록")).toHaveLength(2);
  expect(within(panel).getAllByRole("link", { name: "카드 근거 보기" })[0].getAttribute("href"))
    .toBe("/board?row=card-synthetic&legacy=1");
  expect(screen.getByText(/환불 연결 0건/)).toBeTruthy();
  expect(screen.queryByText("표시할 거래가 없습니다")).toBeNull();
});
