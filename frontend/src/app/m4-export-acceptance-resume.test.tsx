// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TripSummary } from "../api/types";
import { ExportPage } from "../features/auxiliary/export";
import { LedgerPage } from "../features/ledger";

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  if (originalClipboard) Object.defineProperty(navigator, "clipboard", originalClipboard);
  else Reflect.deleteProperty(navigator, "clipboard");
});

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function trip(id: string, title: string): TripSummary {
  return {
    id,
    title,
    kind: "trip",
    previous: false,
    starts_on: "2026-11-01",
    ends_on: "2026-11-03",
    income: "0",
    expense: "0",
    profit: "0",
    closed: false,
    archived: false,
  };
}

function bootstrap(trips: TripSummary[]) {
  return {
    role: "owner" as const,
    csrf: "m4-synthetic-csrf",
    trips,
    capabilities: [],
    receipt_enabled: false,
  };
}

function ledgerPayload(selectedTrip: TripSummary, rows: Array<Record<string, unknown>>) {
  return {
    trip: selectedTrip,
    rows,
    total_count: 237,
    page: 4,
    page_size: 25,
    total: "1200000",
    filtered_total: "512345",
    closed: false,
  };
}

function ledgerRows() {
  return Array.from({ length: 25 }, (_, index) => ({
    id: `m4-visible-${index + 1}`,
    date: "2026-11-02",
    merchant: "합성 가맹점",
    description: "synthetic-match visible page",
    category: "식비",
    amount: String(1000 + index),
    currency: "KRW",
    payment: "카드",
  }));
}

const xlsxAction = {
  id: "exports-xlsx",
  label: "XLSX 내보내기",
  method: "POST" as const,
  href: "/api/exports/xlsx",
  encoding: "json" as const,
  csrf: "header" as const,
  response: "json" as const,
  fields: [
    { name: "tab_ids", label: "여행", type: "hidden" as const, multiple: true, required: true },
    { name: "client_request_id", label: "요청 ID", type: "hidden" as const, required: true },
  ],
};

describe("M4 export acceptance resume", () => {
  it("copies the complete filtered server TSV with matching IDs, row count, and signed total across source pages", async () => {
    const selectedTrip = trip("m4-synthetic-trip", "합성 수락 여행");
    const sourceRows = Array.from({ length: 337 }, (_, index) => ({
      id: `m4-tsv-row-${String(index + 1).padStart(4, "0")}`,
      date: `2026-11-${String(1 + (index % 28)).padStart(2, "0")}`,
      amount: index % 11 === 0 ? -(index + 101) : index + 101,
      queryText: index < 237 ? "synthetic-match" : "synthetic-other",
    }));
    const filtered = sourceRows.filter((row) => row.queryText === "synthetic-match");
    const sourcePages = Array.from({ length: Math.ceil(filtered.length / 50) }, (_, page) =>
      filtered.slice(page * 50, (page + 1) * 50));
    const serverRows = sourcePages.flat();
    const expectedTotal = serverRows.reduce((sum, row) => sum + row.amount, 0);
    const header = ["날짜", "항목", "분류", "금액", "결제수단", "가맹점", "합성 행 ID"].join("\t");
    const tsv = [header, ...serverRows.map((row) => [
      row.date, "합성 지출", "식비", String(row.amount), "카드", "합성 가맹점", row.id,
    ].join("\t"))].join("\n");
    const serverResult = {
      tab_id: selectedTrip.id,
      source_available: true,
      row_count: serverRows.length,
      total_krw: String(expectedTotal),
      held: [],
      tsv,
    };
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });

    let copyRequest: URL | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/plush/ledger") {
        return jsonResponse(ledgerPayload(selectedTrip, ledgerRows()));
      }
      if (url.pathname === "/api/board/tsv") {
        copyRequest = url;
        return jsonResponse(serverResult);
      }
      throw new Error(`Unexpected synthetic request ${init?.method || "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LedgerPage
      path="/board"
      search={new URLSearchParams(
        `tab=${selectedTrip.id}&kind=expense&q=synthetic-match&page=4&page_size=25`,
      )}
      bootstrap={bootstrap([selectedTrip])}
    />);

    expect(await screen.findByText("237건 · 4 / 10페이지")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Google 장부용 복사" }));

    expect(await screen.findByText(/237건 · 전체 .*원이 복사되었습니다/)).toBeTruthy();
    expect(sourcePages).toHaveLength(5);
    expect(serverRows).toHaveLength(237);
    expect(serverResult.row_count).toBe(filtered.length);
    expect(Number(serverResult.total_krw)).toBe(expectedTotal);
    expect(clipboardWrite).toHaveBeenCalledOnce();
    expect(clipboardWrite).toHaveBeenCalledWith(tsv);

    const exportedLines = String(clipboardWrite.mock.calls[0][0]).split("\n").slice(1);
    const exportedCells = exportedLines.map((line) => line.split("\t"));
    expect(exportedCells).toHaveLength(237);
    expect(exportedCells.map((row) => row[6])).toEqual(filtered.map((row) => row.id));
    expect(exportedCells.reduce((sum, row) => sum + Number(row[3]), 0)).toBe(expectedTotal);

    expect(copyRequest?.pathname).toBe("/api/board/tsv");
    expect(copyRequest?.searchParams.get("tab")).toBe(selectedTrip.id);
    expect(copyRequest?.searchParams.get("kind")).toBe("ex");
    expect(copyRequest?.searchParams.get("q")).toBe("synthetic-match");
    expect(copyRequest?.searchParams.has("page")).toBe(false);
    expect(copyRequest?.searchParams.has("page_size")).toBe(false);
  });

  it("keeps XLSX scoped to the selected trip, independent of visible page/filter, and refuses running-at-100% as complete", async () => {
    const selectedTrip = trip("m4-xlsx-selected", "합성 선택 여행");
    const visibleLedger = ledgerPayload(selectedTrip, ledgerRows());
    let exportRequest: { url: URL; body: Record<string, unknown> } | undefined;
    let statusReads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/plush/ledger") return jsonResponse(visibleLedger);
      if (url.pathname === "/api/exports/xlsx" && init?.method === "POST") {
        exportRequest = { url, body: JSON.parse(String(init.body || "{}")) };
        return jsonResponse({ job_id: "m4-running-100", status: "started" });
      }
      if (url.pathname === "/api/exports/m4-running-100") {
        statusReads += 1;
        return jsonResponse({
          job_id: "m4-running-100", status: "running", progress: 100,
          tabs: [selectedTrip.id],
        });
      }
      throw new Error(`Unexpected synthetic request ${init?.method || "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LedgerPage
      path="/board"
      search={new URLSearchParams(
        `tab=${selectedTrip.id}&kind=expense&q=synthetic-match&page=4&page_size=25`,
      )}
      bootstrap={bootstrap([selectedTrip])}
    />);
    await screen.findByText("237건 · 4 / 10페이지");
    fireEvent.click(screen.getByRole("button", { name: "XLSX 내보내기" }));

    expect(await screen.findByText(/내보내기 작업이 접수됐지만/)).toBeTruthy();
    expect(statusReads).toBe(1);
    expect(screen.queryByRole("link", { name: "파일 다운로드" })).toBeNull();
    expect(screen.queryByText(/현재 필터와 관계없이/)).toBeNull();
    expect(exportRequest?.url.pathname).toBe("/api/exports/xlsx");
    expect(exportRequest?.body.tab_ids).toEqual([selectedTrip.id]);
    expect(exportRequest?.body).not.toHaveProperty("q");
    expect(exportRequest?.body).not.toHaveProperty("page");
    expect(exportRequest?.body).not.toHaveProperty("page_size");
  });

  it("does not duplicate a slow export, marks failure honestly, retries with a new request ID, and downloads only after ready", async () => {
    const trips = [trip("m4-export-a", "합성 여행 A"), trip("m4-export-b", "합성 여행 B")];
    let resolveFirstPost!: (response: Response) => void;
    const firstPost = new Promise<Response>((resolve) => { resolveFirstPost = resolve; });
    const postBodies: Array<Record<string, unknown>> = [];
    let firstJobReads = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/plush/auxiliary") {
        return jsonResponse({ title: "합성 내보내기", actions: [xlsxAction] });
      }
      if (url.pathname === "/api/exports/xlsx" && init?.method === "POST") {
        postBodies.push(JSON.parse(String(init.body || "{}")));
        return postBodies.length === 1
          ? firstPost
          : jsonResponse({ job_id: "m4-export-retry", status: "started" });
      }
      if (url.pathname === "/api/exports/m4-export-first") {
        firstJobReads += 1;
        return firstJobReads === 1
          ? jsonResponse({
            job_id: "m4-export-first", status: "running", progress: 100,
            tabs: [trips[0].id], message: "synthetic still running",
          })
          : jsonResponse({
            job_id: "m4-export-first", status: "failed", tabs: [trips[0].id],
            message: "합성 생성 실패",
          });
      }
      if (url.pathname === "/api/exports/m4-export-retry") {
        return jsonResponse({ job_id: "m4-export-retry", status: "ready", tabs: [trips[0].id] });
      }
      throw new Error(`Unexpected synthetic request ${init?.method || "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ExportPage
      path="/export"
      search={new URLSearchParams()}
      nav={[]}
      bootstrap={bootstrap(trips)}
    />);

    fireEvent.click(await screen.findByRole("button", { name: "선택 해제" }));
    fireEvent.click(screen.getByLabelText("합성 여행 A"));
    const generate = screen.getByRole("button", { name: "XLSX 만들기" });
    fireEvent.click(generate);
    const processing = screen.getAllByRole("button", { name: "처리 중…" })[0] as HTMLButtonElement;
    expect(processing.disabled).toBe(true);
    fireEvent.click(processing);
    expect(postBodies).toHaveLength(1);
    expect(screen.queryByRole("link", { name: "XLSX 파일 다운로드" })).toBeNull();

    await act(async () => {
      resolveFirstPost(jsonResponse({ job_id: "m4-export-first", status: "started" }));
    });
    expect(await screen.findByText("파일 만드는 중")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "XLSX 파일 다운로드" })).toBeNull();
    expect(postBodies[0].tab_ids).toEqual([trips[0].id]);

    fireEvent.click(screen.getByRole("button", { name: "상태 다시 확인" }));
    expect(await screen.findByText("생성 실패")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "XLSX 파일 다운로드" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "XLSX 만들기" }));
    const download = await screen.findByRole("link", { name: "XLSX 파일 다운로드" });
    expect(download.getAttribute("href")).toBe("/api/exports/m4-export-retry/download");
    expect(postBodies).toHaveLength(2);
    expect(postBodies[1].tab_ids).toEqual([trips[0].id]);
    expect(postBodies[0].client_request_id).not.toBe(postBodies[1].client_request_id);
    expect(postBodies[0].client_request_id).toMatch(/^[0-9a-f]{32}$/);
    expect(postBodies[1].client_request_id).toMatch(/^[0-9a-f]{32}$/);
  });
});
