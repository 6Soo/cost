// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import { TransactionsPage } from "./index";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const bootstrap: Bootstrap = {
  role: "owner", csrf: "synthetic", trips: [], capabilities: [], receipt_enabled: false,
};

it("shows the assigned trip and a working entry to the existing coverage panel", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    view: "cards", columns: [{ key: "trip_name", label: "여행" }],
    rows: [{ id: "synthetic", trip_name: "1110_합성 여행", status: "classified" }],
    total_count: 1, page: 1, page_size: 100, actions: [],
  }), { headers: { "content-type": "application/json" } })));

  render(<TransactionsPage bootstrap={bootstrap} path="/cards/all" search={new URLSearchParams()} />);

  expect((await screen.findAllByText("1110_합성 여행")).length).toBeGreaterThan(0);
  expect(screen.queryByText("classified")).toBeNull();
  const coverage = screen.getByRole("link", { name: "카드 이용내역 공백 확인" });
  expect(coverage.getAttribute("href")).toBe("/cards/all?legacy=1&panel=coverage");
});

it("does not expose card tools or request card data to a viewer", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<TransactionsPage bootstrap={{ ...bootstrap, role: "viewer" }} path="/cards/all" search={new URLSearchParams()} />);
  expect(screen.queryByRole("link", { name: "카드 이용내역 공백 확인" })).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
