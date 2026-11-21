// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import { CardCoverage } from "./cardCoverage";
import { TransactionsPage } from "./index";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const OWNER: Bootstrap = {
  role: "owner",
  csrf: "synthetic",
  trips: [],
  capabilities: [],
  receipt_enabled: false,
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(handler: (url: string) => Response | Promise<Response>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      calls.push(url);
      return handler(url);
    }),
  );
  return calls;
}

const CARD = {
  card_id: "synthetic-card-b",
  issuer: "SYNTH B",
  date_basis: "거래일자",
  identity_scope: "issuer",
  periods: [
    { start: "2026-01-01", end: "2026-03-31" },
    { start: "2026-05-01", end: "2026-06-30" },
  ],
  gaps: [{ start: "2026-04-01", end: "2026-04-30" }],
  files: [],
};

it("shows missing periods before collected periods and links the gap to upload", async () => {
  const calls = stubFetch(() => jsonResponse({
    available: true,
    coverage_state: "transaction_dates",
    overview: { card_count: 1, gap_count: 1 },
    cards: [CARD],
    files: [],
  }));

  render(<CardCoverage search={new URLSearchParams()} />);

  expect(await screen.findByRole("heading", { name: "수집 현황" })).toBeTruthy();
  expect(screen.getByText("빈 기간 1곳")).toBeTruthy();
  const card = screen.getByRole("region", { name: "SYNTH B 수집 기간" });
  // Missing periods stay ahead of supporting collected periods.
  const children = Array.from(card.children);
  expect(children[1]!.textContent).toContain("비어 있는 기간 2026-04-01 ~ 2026-04-30");
  const collected = children.slice(2).map((child) => child.textContent ?? "").join(" ");
  expect(collected).toContain("2026-01-01 ~ 2026-03-31");
  const upload = screen.getByRole("link", { name: "이 기간 업로드" });
  const url = new URL(upload.getAttribute("href") ?? "", "http://localhost");
  expect(url.searchParams.get("legacy")).toBe("1");
  expect(url.searchParams.get("panel")).toBe("upload");
  expect(url.searchParams.get("gap_card")).toBe("synthetic-card-b");
  expect(url.searchParams.get("gap_start")).toBe("2026-04-01");
  expect(url.searchParams.get("gap_end")).toBe("2026-04-30");
  expect(calls[0]).toContain("/api/cards/coverage/summary");
});

it("uses the source file name when the card cannot be identified beyond one file", async () => {
  stubFetch(() => jsonResponse({
    available: true,
    coverage_state: "transaction_dates",
    cards: [{
      card_id: "file-card",
      issuer: "",
      identity_scope: "source_file",
      periods: [{ start: "2026-04-01", end: "2026-04-30" }],
      gaps: [],
      files: [{ filename: "synthetic-long-card-statement-1.csv" }],
    }],
    files: [],
  }));

  render(<CardCoverage search={new URLSearchParams()} />);

  expect(await screen.findByText("synthetic-long-card-statement-1.csv")).toBeTruthy();
  expect(screen.getByText("기간 사이 공백 없음")).toBeTruthy();
});

it("groups unverified files and lists dated upload files with processing links", async () => {
  const pendingBatch = `batch-${"b".repeat(24)}`;
  const datedBatch = `batch-${"a".repeat(24)}`;
  stubFetch(() => jsonResponse({
    available: true,
    coverage_state: "transaction_dates",
    cards: [CARD],
    files: [
      {
        batch_id: pendingBatch,
        filename: "pending.csv",
        coverage_status: "no_transaction_dates",
        issuer_hint: "SYNTH B",
      },
      {
        batch_id: datedBatch,
        filename: "dated.csv",
        status: "classified",
        source_rows: 5,
        unique_transactions: 2,
        transaction_start: "2026-04-01",
        transaction_end: "2026-04-30",
        coverage_status: "transaction_dates",
      },
    ],
  }));

  render(<CardCoverage search={new URLSearchParams({ q: "카드" })} />);

  expect(await screen.findByText("기간을 확인할 수 없는 파일 1개")).toBeTruthy();
  expect(screen.getByText("dated.csv")).toBeTruthy();
  expect(screen.getByText(/원천 5행/)).toBeTruthy();
  const links = screen.getAllByRole("link", { name: /처리 결과/ });
  expect(links).toHaveLength(2);
  // File order is server supplied; match links to batches instead of assuming it.
  const batches = links.map((link) => new URL(link.getAttribute("href") ?? "", "http://localhost").searchParams.get("batch"));
  expect(new Set(batches)).toEqual(new Set([pendingBatch, datedBatch]));
  for (const link of links) {
    const url = new URL(link.getAttribute("href") ?? "", "http://localhost");
    expect(url.searchParams.get("panel")).toBe("upload");
    expect(url.searchParams.get("q")).toBe("카드");
  }
});

it("fails closed with a readable message when coverage is unavailable", async () => {
  stubFetch(() => jsonResponse({
    available: false,
    coverages: [],
    gaps: [],
    rechecks: [],
    cards: [],
    files: [],
    overview: {},
    coverage_state: "unavailable",
  }));

  render(<CardCoverage search={new URLSearchParams()} />);

  expect(await screen.findByText(/수집 기간을 불러올 수 없습니다/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "카드 파일 업로드" }).getAttribute("href")).toBe(
    "/cards/all?legacy=1&panel=upload",
  );
});

it("shows the empty state when no card material has transaction dates", async () => {
  stubFetch(() => jsonResponse({
    available: true,
    coverage_state: "needs_transactions",
    cards: [],
    files: [],
  }));

  render(<CardCoverage search={new URLSearchParams()} />);

  expect(await screen.findByText(/거래일자가 있는 카드 자료가 없습니다/)).toBeTruthy();
});

it("offers a retry after a failed read and refreshes on demand", async () => {
  let calls = 0;
  const urls = stubFetch(() => {
    calls += 1;
    return calls === 1
      ? jsonResponse({ code: "COVERAGE_NOT_READY", message: "수집 현황을 준비하지 못했습니다." }, 503)
      : jsonResponse({ available: true, coverage_state: "needs_transactions", cards: [], files: [] });
  });

  render(<CardCoverage search={new URLSearchParams()} />);
  expect(await screen.findByText("수집 현황을 준비하지 못했습니다. 다시 확인해 주세요.")).toBeTruthy();

  screen.getByRole("button", { name: "수집 현황 다시 불러오기" }).click();
  expect(await screen.findByText(/거래일자가 있는 카드 자료가 없습니다/)).toBeTruthy();

  screen.getByRole("button", { name: "새로고침" }).click();
  await waitFor(() => expect(calls).toBe(3));
  expect(urls.filter((url) => url.includes("/api/cards/coverage/summary"))).toHaveLength(3);
});

it("renders the native collection status in the owner card view and retires the legacy coverage link", async () => {
  const urls = stubFetch((url) => {
    if (url.includes("/api/plush/transactions")) {
      return jsonResponse({
        view: "cards",
        columns: [],
        rows: [],
        total_count: 0,
        page: 1,
        page_size: 100,
        actions: [],
      });
    }
    return jsonResponse({
      available: true,
      coverage_state: "transaction_dates",
      cards: [{
        card_id: "synthetic-card",
        issuer: "SYNTH",
        date_basis: "거래일자",
        identity_scope: "issuer",
        periods: [{ start: "2026-01-01", end: "2026-03-31" }],
        gaps: [{ start: "2026-04-01", end: "2026-04-30" }],
      }],
      files: [],
    });
  });

  render(<TransactionsPage bootstrap={OWNER} path="/cards/all" search={new URLSearchParams()} />);

  // The same function is available natively and in the legacy surface is gone.
  expect(await screen.findByRole("heading", { name: "수집 현황" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "카드 이용내역 공백 확인" })).toBeNull();

  // Upload entry points keep their existing query contract.
  const url = new URL(
    screen.getByRole("link", { name: "이 기간 업로드" }).getAttribute("href") ?? "",
    "http://localhost",
  );
  expect(url.searchParams.get("legacy")).toBe("1");
  expect(url.searchParams.get("panel")).toBe("upload");
  expect(url.searchParams.get("gap_start")).toBe("2026-04-01");
  expect(url.searchParams.get("gap_end")).toBe("2026-04-30");
  expect(urls.some((entry) => entry.includes("/api/plush/transactions"))).toBe(true);
  expect(urls.some((entry) => entry.includes("/api/cards/coverage/summary"))).toBe(true);
});
