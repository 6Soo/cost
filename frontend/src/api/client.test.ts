import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, executeAction, getJSON, postJSON } from "./client";
import { boardTsvAction, COST_API_ACTIONS, COST_API_ROUTES, exportDownloadAction, exportJobAction, rowLineageAction, rowSaveAction, type ActionDescriptor } from "./types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Plush authenticated API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses same-origin credentials and disables response caching", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ value: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getJSON<{ value: string }>("/api/plush/bootstrap")).resolves.toEqual({ value: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.objectContaining({ pathname: "/api/plush/bootstrap" }),
      expect.objectContaining({ credentials: "same-origin", cache: "no-store" }),
    );
  });

  it("rejects absolute and non-API paths before sending", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(getJSON("https://example.test/api/plush/bootstrap")).rejects.toMatchObject({
      code: "INVALID_API_PATH",
      status: 0,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends JSON actions with declared fields and CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ row_id: "row-1" }));
    vi.stubGlobal("fetch", fetchMock);
    const action = COST_API_ACTIONS.manualExpense;

    await expect(executeAction(action, {
      display_tab_id: "trip-demo",
      occurred_on: "2026-11-16",
      pay_method: "현금",
      item: "교통",
      description: "합성 이동",
      amount_krw: 1000,
      client_request_id: "request-1",
    }, "csrf-1")).resolves.toMatchObject({ kind: "json", data: { row_id: "row-1" } });

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(init.headers).toMatchObject({ "X-CSRF-Token": "csrf-1", "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toMatchObject({ amount_krw: 1000 });
  });

  it("adds field CSRF for URL encoded forms and rejects undeclared fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ saved: true }));
    vi.stubGlobal("fetch", fetchMock);
    const action: ActionDescriptor = {
      id: "save", label: "저장", method: "POST", encoding: "form", csrf: "field",
      response: "json", href: "/api/rows/r1/save",
      fields: [{ name: "item", label: "항목", type: "text" }],
    };

    await executeAction(action, { item: "교통" }, "csrf-2");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      headers: expect.objectContaining({ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }),
      body: "item=%EA%B5%90%ED%86%B5&csrf=csrf-2",
    });
    await expect(executeAction(action, { item: "교통", arbitrary: "x" }, "csrf-2"))
      .rejects.toMatchObject({ code: "INVALID_ACTION_PAYLOAD" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends multipart file fields without setting the boundary header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ uploaded: true }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["synthetic"], "sample.pdf", { type: "application/pdf" });
    const action: ActionDescriptor = {
      id: "upload", label: "등록", method: "POST", encoding: "multipart", csrf: "header",
      response: "json", href: "/api/receipts/upload",
      fields: [{ name: "file", label: "파일", type: "file", required: true, accept: "application/pdf" }],
    };

    await executeAction(action, { file }, "csrf-3");
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(init.headers).toMatchObject({ "X-CSRF-Token": "csrf-3" });
    expect((init.headers as Record<string, string>)?.["Content-Type"]).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("normalizes server JSON errors to ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      code: "REVISION_CONFLICT", message: "다른 기기에서 변경했습니다.",
    }, 409)));

    const error = await postJSON("/api/rows/r1/save", {}, "csrf-4").catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      code: "REVISION_CONFLICT", status: 409, message: "다른 기기에서 변경했습니다.",
    });
  });

  it("returns blob downloads and validates actual COST API action routes", async () => {
    const blob = new Blob(["id\tamount\n"]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(blob, { status: 200 })));
    const result = await executeAction(exportDownloadAction("job 1"));
    expect(result.kind).toBe("blob");
    if (result.kind === "blob") await expect(result.blob.text()).resolves.toBe("id\tamount\n");
    expect(COST_API_ROUTES.rowSave("row/a")).toBe("/api/rows/row%2Fa/save");
    expect(rowSaveAction("r1", []).href).toBe("/api/rows/r1/save");
    expect(exportJobAction("job 1").href).toBe("/api/exports/job%201");
    expect(rowLineageAction("r1").href).toBe("/api/rows/r1/lineage");
    expect(boardTsvAction("trip-1").href).toBe("/api/board/tsv");
  });

  it("uses the server's multi-trip export payload and TSV query contract", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValueOnce(jsonResponse({ tsv: "a\tb", row_count: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    await executeAction(COST_API_ACTIONS.exportsXlsx, {
      tab_ids: ["trip-a", "trip-b"], client_request_id: "request-2",
    }, "csrf-5");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({
      tab_ids: ["trip-a", "trip-b"], client_request_id: "request-2",
    });

    await executeAction(boardTsvAction("trip-a"), { q: "lodging", kind: "expense" });
    expect(fetchMock.mock.calls[1]?.[0]).toMatchObject({
      pathname: "/api/board/tsv", search: "?tab=trip-a&q=lodging&kind=expense",
    });
  });

  it("preserves non-text download bytes", async () => {
    const bytes = new Uint8Array([0x50, 0x4b, 0, 0xff, 0x80, 0x01]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bytes)));
    const result = await executeAction(exportDownloadAction("binary-job"));
    expect(result.kind).toBe("blob");
    if (result.kind === "blob") {
      expect(new Uint8Array(await result.blob.arrayBuffer())).toEqual(bytes);
    }
  });

  it("allows only the three existing account POST actions", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const base: ActionDescriptor = {
      id: "account", label: "계정", href: "/access/logout", method: "POST",
      encoding: "json", csrf: "header", response: "json",
    };
    for (const href of ["/access/applications", "/access/decision", "/access/logout"]) {
      await executeAction({ ...base, href }, {}, "synthetic-csrf");
    }
    for (const href of ["/access/admin", "/access/logout/", "/access/logout?next=elsewhere"]) {
      await expect(executeAction({ ...base, href }, {}, "synthetic-csrf"))
        .rejects.toMatchObject({ code: "INVALID_API_PATH" });
    }
    await expect(executeAction({ ...base, method: "GET", encoding: "form", csrf: "none" }))
      .rejects.toMatchObject({ code: "INVALID_API_PATH" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
