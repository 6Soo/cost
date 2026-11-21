// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import { TransactionsPage } from "./index";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const bootstrap: Bootstrap = {
  role: "owner", csrf: "synthetic", trips: [], capabilities: [], receipt_enabled: false,
};

function transactionsPayload(actions: unknown[] = []) {
  return {
    view: "cards", columns: [{ key: "trip_name", label: "여행" }],
    rows: [{ id: "synthetic", trip_name: "1110_합성 여행", status: "classified" }],
    total_count: 1, page: 1, page_size: 100, actions,
  };
}

const genericUploadAction = {
  id: "card-upload-batch", label: "카드 파일 업로드", method: "POST",
  href: "/api/imports/upload-batch", encoding: "multipart", csrf: "header",
  response: "json",
  fields: [{ name: "files", label: "카드 파일", type: "file", multiple: true, required: true }],
};

function stubFeatureFetch(batchId?: string, actions: unknown[] = [genericUploadAction]) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    calls.push(url);
    const body = url.includes("/api/cards/coverage/summary")
      ? { available: true, coverage_state: "needs_transactions", cards: [], files: [] }
      : batchId && url.endsWith(`/api/imports/${batchId}`)
        ? { summary: { status: "classified", row_count: 3, error_count: 0 } }
        : transactionsPayload(actions);
    return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
  }));
  return calls;
}

it("shows the upload workspace for a panel=upload deep link instead of the card list", async () => {
  const batchId = `batch-${"c".repeat(24)}`;
  const calls = stubFeatureFetch(batchId);

  render(<TransactionsPage bootstrap={bootstrap} path="/cards/all" search={new URLSearchParams([
    ["panel", "upload"], ["batch", batchId],
    ["gap_card", "synthetic-card"], ["gap_start", "2026-04-01"],
    ["gap_end", "2026-04-30"], ["gap_issuer", "SYNTH"],
  ])} />);

  expect(await screen.findByRole("heading", { name: "카드 파일 업로드" })).toBeTruthy();
  expect(screen.getByText(/파일 조회기간 사이 2026-04-01 ~ 2026-04-30/)).toBeTruthy();
  expect(await screen.findByText(/처리 행 3/)).toBeTruthy();
  // The cards list is not the upload workspace contract.
  expect(screen.queryByText("1110_합성 여행")).toBeNull();
  expect(calls.some((url) => url.includes("/api/plush/transactions"))).toBe(false);
  expect(calls.some((url) => url.endsWith(`/api/imports/${batchId}`))).toBe(true);
});

it("renders one upload entry point on cards and hides the generic action descriptor", async () => {
  const calls = stubFeatureFetch();

  render(<TransactionsPage bootstrap={bootstrap} path="/cards/all" search={new URLSearchParams()} />);

  expect((await screen.findAllByText("1110_합성 여행")).length).toBeGreaterThan(0);
  expect(await screen.findByRole("heading", { name: "수집 현황" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "카드 파일 업로드" })).toBeTruthy();
  expect(screen.getAllByRole("button", { name: "카드 파일 업로드" })).toHaveLength(1);
  expect(calls.some((url) => url.includes("/api/plush/transactions"))).toBe(true);
});

it("does not expose card tools or request card data to a viewer", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<TransactionsPage bootstrap={{ ...bootstrap, role: "viewer" }} path="/cards/all" search={new URLSearchParams()} />);
  expect(screen.queryByText("수집 현황")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
