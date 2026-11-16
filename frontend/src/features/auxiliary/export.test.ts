// @vitest-environment jsdom
import { createElement } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExportPage } from "./export";
import {
  buildXlsxActionValues,
  exportDownloadHref,
  exportJobStatusUrl,
} from "./export";

describe("auxiliary export job contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("submits every selected trip with the same request id", () => {
    expect(buildXlsxActionValues(["trip-a", "trip-b"], "request-1")).toEqual({
      tab_ids: ["trip-a", "trip-b"],
      client_request_id: "request-1",
    });
  });

  it("reads status by the returned job id using an encoded same-origin API path", () => {
    expect(exportJobStatusUrl("xlsx-job 1")).toBe("/api/exports/xlsx-job%201");
  });

  it("offers an artifact only after the server marks the job ready", () => {
    expect(exportDownloadHref({ job_id: "xlsx-job-1", status: "ready" })).toBe(
      "/api/exports/xlsx-job-1/download",
    );
    expect(exportDownloadHref({ job_id: "xlsx-job-1", status: "started" })).toBeNull();
    expect(exportDownloadHref({ job_id: "xlsx-job-1", status: "failed" })).toBeNull();
  });

  it("checks the returned job through GET before showing its ready download", async () => {
    const xlsx = {
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/plush/auxiliary")) {
        return new Response(JSON.stringify({ title: "내보내기", actions: [xlsx] }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/exports/xlsx") && init?.method === "POST") {
        return new Response(JSON.stringify({ job_id: "xlsx-synthetic", status: "started", output_path: "private-path" }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/exports/xlsx-synthetic")) {
        return new Response(JSON.stringify({ job_id: "xlsx-synthetic", status: "ready", tabs: ["trip-a"], output_path: "private-path" }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(createElement(ExportPage, {
      bootstrap: {
        role: "owner", csrf: "csrf-test", trips: [{
          id: "trip-a", title: "합성 여행", kind: "trip", previous: false,
          starts_on: "2026-04-01", ends_on: "2026-04-02", income: "0", expense: "0",
          profit: "0", closed: false, archived: false,
        }], capabilities: [], receipt_enabled: false,
      },
      path: "/export",
      search: new URLSearchParams(),
      nav: [],
    }));

    fireEvent.click(await screen.findByRole("button", { name: "XLSX 만들기" }));

    const download = await screen.findByRole("link", { name: "XLSX 파일 다운로드" });
    expect(download.getAttribute("href")).toBe("/api/exports/xlsx-synthetic/download");
    expect(fetchMock.mock.calls.map(([input]) => new URL(String(input), window.location.origin).pathname))
      .toContain("/api/exports/xlsx-synthetic");
    expect(document.body.textContent).not.toContain("private-path");
  });
});
