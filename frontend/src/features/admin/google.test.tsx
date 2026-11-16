// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import { GooglePage } from "./google";

const ownerBootstrap: Bootstrap = {
  role: "owner",
  csrf: "synthetic-csrf-token",
  trips: [],
  capabilities: ["admin.read"],
  receipt_enabled: false,
};

const syncAction = {
  id: "google-sync",
  label: "Google 장부 새로 읽기",
  method: "POST" as const,
  href: "/api/google-ledger/sync",
  encoding: "json" as const,
  csrf: "header" as const,
  response: "json" as const,
  fields: [{
    name: "client_request_id",
    label: "요청 ID",
    type: "hidden" as const,
  }],
};

const projection = {
  title: "Google 장부 비교",
  columns: [
    { key: "key", label: "Google 여행" },
    { key: "closure", label: "마감" },
    { key: "income_total", label: "수입" },
    { key: "expense_total", label: "지출" },
    { key: "net", label: "순수익" },
    { key: "verified", label: "검증" },
    { key: "review", label: "확인 사항" },
  ],
  rows: [{
    key: "2030-demo",
    kind: "trip",
    closure: "open",
    closure_current: true,
    chosen_source: "main",
    verified: true,
    blocked_by: [],
    review: [],
    income_total: "120000",
    expense_total: "45000",
    net: "75000",
    connected_tab_id: "cost-trip-demo",
    source_href: "/api/google-ledger/source?trip=cost-trip-demo",
    reconciliation_href: "/api/google-ledger/expense-reconciliation?trip=cost-trip-demo&page=1",
    copy_href: "/api/board/tsv?tab=cost-trip-demo&kind=ex",
    copies: {
      main: { present: true, layout: "rev", verified: true, income_total: "120000", expense_total: "45000", flags: [] },
      archive: { present: true, layout: "rev", verified: true, income_total: "120000", expense_total: "45000", flags: [] },
    },
  }],
  actions: [syncAction],
  data: {
    enabled: true,
    available: true,
    synced_at: "2026-11-16T01:00:00+09:00",
    sources: {
      main: { status: "ok", error_code: null, stale: false, last_ok_at: "2026-11-16T01:00:00+09:00", checked_at: "2026-11-16T01:00:00+09:00" },
      archive: { status: "ok", error_code: null, stale: false, last_ok_at: "2026-11-16T01:00:00+09:00", checked_at: "2026-11-16T01:00:00+09:00" },
    },
    settings: {
      connections: [{ trip_key: "2030-demo", tab_id: "cost-trip-demo", tab_label: "2030 합성 여행" }],
      copy_choices: [{ trip_key: "2030-demo", source: "main" }],
      viewer_grants: [],
      tabs: [{ tab_id: "cost-trip-demo", label: "2030 합성 여행" }],
    },
  },
};

const reconciliation = {
  code: "OK",
  message: "",
  trip_id: "cost-trip-demo",
  source_available: true,
  source_info: { sheet_id: "synthetic-sheet", source: "main", layout: "rev", synced_at: "2026-11-16T01:00:00+09:00" },
  counts: { MATCHED_MANUAL: 1, MATCHED_EXISTING: 1, NEW_EXPENSE: 1, REVIEW_CONFLICT: 1, SOURCE_UNAVAILABLE: 0 },
  results: [
    {
      transaction_id: "synthetic-manual-1", trip_id: "cost-trip-demo", status: "MATCHED_MANUAL", status_label: "수기 행과 일치",
      date: "2030-04-05", merchant: "합성 식당", category: "식비", description: "합성 점심", amount_krw: "12345678901234567890",
      currency: "KRW", card: "•••• 1234", sheet_id: "synthetic-sheet", source: "main", row_number: 12,
      basis: ["날짜·금액·가맹점 일치"], differences: {}, reason: "", user_corrected: false, correction_source: "",
      review_href: "/board?tab=cost-trip-demo",
    },
    {
      transaction_id: "synthetic-conflict-1", trip_id: "cost-trip-demo", status: "REVIEW_CONFLICT", status_label: "차이 확인 필요",
      date: "2030-04-06", merchant: "다른 합성 식당", category: "식비", description: "", amount_krw: "98765432109876543210",
      currency: "KRW", card: "•••• 9876", sheet_id: "synthetic-sheet", source: "main", row_number: 13,
      basis: [], differences: { amount: { manual: "12,000", cost: "11,000" } }, reason: "금액 차이",
      user_corrected: true, correction_source: "사용자 교정", review_href: "/board?tab=cost-trip-demo",
    },
  ],
  total: 4, page: 1, page_size: 50, pages: 1, preview_digest: "synthetic-preview-v1", source_digest: "synthetic-source-v1",
  revision: 3, links_revision: 2,
};

const pastedTsv = "2030-04-05\t합성 식당\t12345678901234567890\n";

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), window.location.origin);
    return handler(`${url.pathname}${url.search}`, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("GooglePage", () => {
  it("keeps owner-only data out of viewer sessions without requesting the projection", () => {
    const fetchMock = installFetch(() => response(projection));

    render(<GooglePage bootstrap={{ ...ownerBootstrap, role: "viewer" }} path="/google-ledger" search={new URLSearchParams()} />);

    expect(screen.getByRole("alert").textContent).toContain("소유자 전용");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("hides source, reconciliation, and copy controls when the projection advertises unsafe routes", async () => {
    const unsafeProjection = {
      ...projection,
      rows: [{ ...projection.rows[0],
        source_href: "https://example.invalid/source",
        reconciliation_href: "/api/google-ledger/rows?trip=cost-trip-demo",
        copy_href: "/api/google-ledger/mapping?trip=cost-trip-demo",
      }],
    };
    installFetch(() => response(unsafeProjection));

    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);

    expect(await screen.findByRole("heading", { name: "Google 장부 비교·복사" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "원본 열기" })).toBeNull();
    expect(screen.queryByRole("button", { name: /상세 비교/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Google 붙여넣기 복사/ })).toBeNull();
  });

  it("shows the server comparison, verification reasons, and only the authorized source route", async () => {
    installFetch((url) => {
      expect(url).toBe("/api/plush/admin?view=google");
      return response(projection);
    });

    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);

    expect(await screen.findByRole("heading", { name: "Google 장부 비교·복사" })).toBeTruthy();
    expect(screen.getAllByText("2030-demo").length).toBeGreaterThan(0);
    expect(screen.getAllByText("120,000원").length).toBeGreaterThan(0);
    expect(screen.getAllByText("45,000원").length).toBeGreaterThan(0);
    expect(screen.getAllByText("75,000원").length).toBeGreaterThan(0);
    expect(screen.getAllByText("검증됨").length).toBeGreaterThan(0);
    expect(screen.getAllByText("사본 비교").length).toBeGreaterThan(0);

    const sourceLinks = screen.getAllByRole("link", { name: "원본 열기" });
    expect(sourceLinks.every((sourceLink) => sourceLink.getAttribute("href") === "/api/google-ledger/source?trip=cost-trip-demo")).toBe(true);
    expect(screen.getAllByRole("button", { name: "상세 비교 보기" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Google 붙여넣기 복사" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /연결 저장|복사 선택|열람 허용/ })).toBeNull();
  });

  it("loads reconciliation from the server and formats long exact amount strings without precision loss", async () => {
    const fetchMock = installFetch((url) => {
      if (url === "/api/plush/admin?view=google") return response(projection);
      if (url === "/api/google-ledger/expense-reconciliation?trip=cost-trip-demo&page=1") return response(reconciliation);
      throw new Error(`unexpected request ${url}`);
    });

    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);
    fireEvent.click((await screen.findAllByRole("button", { name: "상세 비교 보기" }))[0]);

    expect(await screen.findByText("12,345,678,901,234,567,890원")).toBeTruthy();
    expect(screen.getByText("•••• 1234")).toBeTruthy();
    expect(screen.getByText("금액 차이")).toBeTruthy();
    expect(screen.queryByText("98765432109876543210")).toBeNull();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("expense-reconciliation?trip=cost-trip-demo&page=1"))).toBe(true);
  });

  it("sends selected links with the current revision and preview digest, preserving the request id", async () => {
    const requestBodies: Array<Record<string, unknown>> = [];
    const fetchMock = installFetch((url, init) => {
      if (url === "/api/plush/admin?view=google") return response(projection);
      if (url === "/api/google-ledger/expense-reconciliation?trip=cost-trip-demo&page=1") return response(reconciliation);
      if (url === "/api/google-ledger/expense-reconciliation") {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("synthetic-csrf-token");
        requestBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        if (requestBodies.length === 1) return response({ code: "TEMPORARY", message: "합성 응답 유실" }, 503);
        return response({ code: "OK", linked_count: 1, saved_count: 1, message: "연결 메타데이터 저장" });
      }
      throw new Error(`unexpected request ${url}`);
    });

    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);
    fireEvent.click((await screen.findAllByRole("button", { name: "상세 비교 보기" }))[0]);
    fireEvent.click(await screen.findByRole("checkbox", { name: /합성 식당/ }));
    fireEvent.click(screen.getByRole("button", { name: /^선택 항목 연결/ }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/합성 응답 유실/);
    fireEvent.click(screen.getByRole("button", { name: /^선택 항목 연결/ }));

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(requestBodies).toHaveLength(2);
    expect(requestBodies[0]).toEqual({
      trip_id: "cost-trip-demo", action: "links", scope: "all", transaction_ids: ["synthetic-manual-1"],
      request_id: expect.stringMatching(/^links:[\da-f]{32}$/), expected_revision: 3,
      preview_digest: "synthetic-preview-v1", query: "", kind: "",
    });
    expect(requestBodies[1].request_id).toBe(requestBodies[0].request_id);
    expect(fetchMock.mock.calls.some(([input]) => new URL(String(input), window.location.origin).pathname === "/api/google-ledger/sync")).toBe(false);
  });

  it("exports through the active reconciliation API and copies the server TSV without writing to Google", async () => {
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText: clipboardWrite } });
    let exportBody: Record<string, unknown> | null = null;
    const fetchMock = installFetch((url, init) => {
      if (url === "/api/plush/admin?view=google") return response(projection);
      if (url === "/api/google-ledger/expense-reconciliation?trip=cost-trip-demo&page=1") return response(reconciliation);
      if (url === "/api/google-ledger/expense-reconciliation") {
        expect(init?.method).toBe("POST");
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("synthetic-csrf-token");
        exportBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return response({ code: "OK", tsv: pastedTsv, row_count: 1, total_krw: "12345678901234567890", held: [], reconciliation });
      }
      throw new Error(`unexpected request ${url}`);
    });

    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);
    fireEvent.click((await screen.findAllByRole("button", { name: "상세 비교 보기" }))[0]);
    fireEvent.click(await screen.findByRole("button", { name: "대조 결과 TSV 복사" }));

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(clipboardWrite).toHaveBeenCalledWith(pastedTsv);
    expect(exportBody).toEqual({
      trip_id: "cost-trip-demo", action: "export", scope: "all", transaction_ids: [],
      request_id: expect.stringMatching(/^export:.+/), expected_revision: 3,
      preview_digest: "synthetic-preview-v1", query: "", kind: "",
    });
    expect(fetchMock.mock.calls.some(([input]) => new URL(String(input), window.location.origin).pathname === "/api/google-ledger/source")).toBe(false);
    expect(fetchMock.mock.calls.some(([input]) => new URL(String(input), window.location.origin).pathname === "/api/google-ledger/sync")).toBe(false);
  });

  it("gets board TSV from its server-provided safe route and shows a manual-copy fallback", async () => {
    const clipboardWrite = vi.fn().mockRejectedValue(new Error("clipboard unavailable"));
    vi.stubGlobal("navigator", { clipboard: { writeText: clipboardWrite } });
    installFetch((url) => {
      if (url === "/api/plush/admin?view=google") return response(projection);
      if (url === "/api/board/tsv?tab=cost-trip-demo&kind=ex") return response({ tsv: pastedTsv, row_count: 1, total_krw: "12345678901234567890" });
      throw new Error(`unexpected request ${url}`);
    });

    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Google 붙여넣기 복사" }))[0]);

    expect(await screen.findByRole("textbox", { name: "복사할 TSV" })).toBeTruthy();
    expect(clipboardWrite).toHaveBeenCalledWith(pastedTsv);
  });

  it("sends the real sync action with the bootstrap CSRF token and does not claim completion", async () => {
    const fetchMock = installFetch((url, init) => {
      if (url === "/api/plush/admin?view=google") return response(projection);
      expect(url).toBe("/api/google-ledger/sync");
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("synthetic-csrf-token");
      expect(JSON.parse(String(init?.body))).toEqual({ client_request_id: expect.stringMatching(/^[\da-f]{32}$/) });
      return response({ status: "running", message: "Google 장부를 읽고 있습니다." }, 202);
    });

    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Google 장부 새로 읽기" }));

    expect((await screen.findByRole("status")).textContent).toMatch(/시작|읽고/);
    expect(screen.queryByText(/동기화가 완료/)).toBeNull();
    expect(fetchMock.mock.calls.some(([input, init]) =>
      new URL(String(input), window.location.origin).pathname === "/api/google-ledger/sync" && init?.method === "POST",
    )).toBe(true);
  });

  it("distinguishes a missing Google snapshot from a failed projection request", async () => {
    installFetch((url) => url === "/api/plush/admin?view=google"
      ? response({ ...projection, data: { enabled: true, available: false, synced_at: null, sources: {}, settings: { connections: [], copy_choices: [], viewer_grants: [], tabs: [] } }, rows: [] })
      : response({ code: "INTERNAL", message: "합성 오류" }, 503));

    const { unmount } = render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);
    expect(await screen.findByText(/동기화 자료를 확인할 수 없습니다/)).toBeTruthy();

    unmount();
    installFetch((url) => url === "/api/plush/admin?view=google"
      ? response({ code: "INTERNAL", message: "합성 오류" }, 503)
      : response({ code: "INTERNAL", message: "합성 오류" }, 503));
    render(<GooglePage bootstrap={ownerBootstrap} path="/google-ledger" search={new URLSearchParams()} />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/합성 오류/);
  });
});
