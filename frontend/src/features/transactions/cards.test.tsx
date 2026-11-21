// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import { TransactionsPage } from "./index";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const bootstrap: Bootstrap = {
  role: "owner", csrf: "synthetic", trips: [], capabilities: [], receipt_enabled: false,
};

function transactionsPayload() {
  return {
    view: "cards", columns: [{ key: "trip_name", label: "여행" }],
    rows: [{ id: "synthetic", trip_name: "1110_합성 여행", status: "classified" }],
    total_count: 1, page: 1, page_size: 100, actions: [],
  };
}

function stubFeatureFetch() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    calls.push(url);
    const body = url.includes("/api/cards/coverage/summary")
      ? { available: true, coverage_state: "needs_transactions", cards: [], files: [] }
      : transactionsPayload();
    return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
  }));
  return calls;
}

it("renders the native collection status without offering the retired legacy coverage link", async () => {
  const calls = stubFeatureFetch();

  render(<TransactionsPage bootstrap={bootstrap} path="/cards/all" search={new URLSearchParams()} />);

  expect((await screen.findAllByText("1110_합성 여행")).length).toBeGreaterThan(0);
  expect(screen.queryByText("classified")).toBeNull();
  expect(screen.queryByRole("link", { name: "카드 이용내역 공백 확인" })).toBeNull();
  expect(await screen.findByRole("heading", { name: "수집 현황" })).toBeTruthy();
  expect(calls.some((url) => url.includes("/api/cards/coverage/summary"))).toBe(true);
});

it("does not expose card tools or request card data to a viewer", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<TransactionsPage bootstrap={{ ...bootstrap, role: "viewer" }} path="/cards/all" search={new URLSearchParams()} />);
  expect(screen.queryByText("수집 현황")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
