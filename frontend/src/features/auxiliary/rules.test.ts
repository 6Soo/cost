// @vitest-environment jsdom
import { createElement } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { afterEach, vi } from "vitest";
import { RulesPage } from "./rules";
import {
  buildRuleActionRequest,
  conversationStateUrl,
  ruleDialogStateUrl,
  summarizeRuleDraft,
} from "./rules";

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderRulesCase(caseId: string) {
  return render(createElement(RulesPage, {
    bootstrap: { role: "owner", csrf: "csrf-test", trips: [], capabilities: [], receipt_enabled: false },
    path: "/rules",
    search: new URLSearchParams({ case: caseId }),
    nav: [{ id: "rules", label: "규칙 보조", path: "/rules" }],
  }));
}

describe("auxiliary rules API contract", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps the legacy case query in both dialog and conversation reads", () => {
    expect(ruleDialogStateUrl("case a/1")).toBe(
      "/api/classification/dialog?case_id=case+a%2F1",
    );
    expect(conversationStateUrl("case a/1")).toBe(
      "/api/classification/conversation?conversation_id=conv-case+a%2F1",
    );
  });

  it("sends owner draft through its existing CSRF form endpoint", () => {
    const request = buildRuleActionRequest(
      "owner-draft",
      "case-1",
      "csrf-token",
      "request-1",
    );

    expect(request.path).toBe("/api/classification/conversation/owner-draft");
    expect(request.body.toString()).toBe(
      "csrf=csrf-token&case=case-1&client_request_id=request-1",
    );
  });

  it("keeps the nested rule draft readable as labeled fields", () => {
    expect(summarizeRuleDraft({
      rule_id: "rule-1",
      rule: {
        conditions: {
          merchant_normalized: { value: "합성 상점" },
          card_kind: { value: ["개인", "법인"] },
        },
        effects: { item: "교통비" },
        scope: { trip_id: "trip-a", event_year: 2026 },
        note: "소유자 수정 내용에서 만든 초안",
      },
    })).toEqual([
      { label: "가맹점", value: "합성 상점" },
      { label: "카드 구분", value: "개인, 법인" },
      { label: "항목", value: "교통비" },
      { label: "적용 범위", value: "trip-a · 2026년" },
      { label: "메모", value: "소유자 수정 내용에서 만든 초안" },
    ]);
  });

  it("loads the case-specific dialog and uses the legacy form contract for owner drafts", async () => {
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push([input, init]);
      const url = String(input);
      if (url.includes("/api/classification/dialog?")) {
        return new Response(JSON.stringify({
          case_id: "case-1", row_revision: 3, dialog_state: "not_started",
          questions: [], answers: {}, draft: { note: "합성 근거" },
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/api/classification/conversation?")) {
        return new Response(JSON.stringify({ conversation_id: "conv-case-1", state: "not_found", turns: [] }), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/api/classification/conversation/owner-draft")) {
        const response = new Response(null, { status: 200 });
        Object.defineProperty(response, "url", {
          value: `${window.location.origin}/rules?case=case-1&msg=%EC%88%98%EC%A0%95%20%EB%82%B4%EC%9A%A9%EC%9C%BC%EB%A1%9C%20%EA%B7%9C%EC%B9%99%20%EC%B4%88%EC%95%88%EC%9D%84%20%EB%A7%8C%EB%93%A4%EC%97%88%EC%8A%B5%EB%8B%88%EB%8B%A4`,
        });
        return response;
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(createElement(RulesPage, {
      bootstrap: { role: "owner", csrf: "csrf-test", trips: [], capabilities: [], receipt_enabled: false },
      path: "/rules",
      search: new URLSearchParams("case=case-1"),
      nav: [{ id: "rules", label: "규칙 보조", path: "/rules" }],
    }));

    fireEvent.click(await screen.findByRole("button", { name: "내 수정 내용으로 규칙 초안 만들기" }));

    expect(await screen.findByText("수정 내용으로 규칙 초안을 만들었습니다")).toBeTruthy();
    const [formCall] = calls.filter(([input]) => String(input).endsWith("/api/classification/conversation/owner-draft"));
    expect(formCall[1]?.headers).toMatchObject({ "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" });
    const form = new URLSearchParams(String(formCall[1]?.body));
    expect(form.get("csrf")).toBe("csrf-test");
    expect(form.get("case")).toBe("case-1");
    expect(form.get("client_request_id")).toBeTruthy();
  });

  it("removes a preview before the newly entered case is loaded", async () => {
    const appliedPreviewIds: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/classification/dialog") {
        const caseId = url.searchParams.get("case_id") || "";
        return jsonResponse({ case_id: caseId, dialog_state: "open", questions: [], answers: {}, draft: {} });
      }
      if (url.pathname === "/api/classification/conversation") {
        const caseId = (url.searchParams.get("conversation_id") || "").replace(/^conv-/, "");
        return jsonResponse({ conversation_id: `conv-${caseId}`, state: "open", rule_id: `rule-${caseId}`, turns: [] });
      }
      if (url.pathname.startsWith("/api/classification/rules/rule-")) {
        const caseId = url.pathname.split("/").at(-1)?.replace(/^rule-/, "") || "";
        return jsonResponse({
          rule_id: `rule-${caseId}`,
          version: 1,
          rule: { conditions: { merchant_normalized: { value: `merchant-${caseId}-v1` } } },
        });
      }
      if (url.pathname === "/api/classification/rules/preview") {
        return jsonResponse({ preview_id: "preview-case-a", counts: { included_rows: 1, excluded_rows: 0, matched_rows: 1 }, candidates: [{ row_id: "row-case-a", from_tab_id: "trip-a", to_tab_id: "trip-b", amount_krw: 100 }] });
      }
      if (url.pathname === "/api/classification/rules/apply") {
        const body = JSON.parse(String(init?.body || "{}")) as { preview_id?: string };
        appliedPreviewIds.push(body.preview_id || "");
        return jsonResponse({ status: "applied" });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRulesCase("case-a");
    fireEvent.click(await screen.findByRole("button", { name: "영향 미리보기" }));
    expect(await screen.findByRole("button", { name: "확인한 범위로 적용" })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("규칙 대화 사례 ID"), { target: { value: "case-b" } });
    expect(await screen.findByText("merchant-case-b-v1")).toBeTruthy();

    expect(screen.queryByRole("button", { name: "확인한 범위로 적용" })).toBeNull();
    expect(screen.queryByRole("region", { name: "영향 미리보기 후보 표" })).toBeNull();
    expect(appliedPreviewIds).toEqual([]);
  });

  it("disables the case input while a preview request is in flight", async () => {
    let finishPreview!: (response: Response) => void;
    const pendingPreview = new Promise<Response>((resolve) => { finishPreview = resolve; });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/classification/dialog") {
        return jsonResponse({ dialog_state: "open", questions: [], answers: {}, draft: {} });
      }
      if (url.pathname === "/api/classification/conversation") {
        return jsonResponse({ state: "open", rule_id: "rule-case-a", turns: [] });
      }
      if (url.pathname === "/api/classification/rules/rule-case-a") {
        return jsonResponse({ rule_id: "rule-case-a", version: 1, rule: {} });
      }
      if (url.pathname === "/api/classification/rules/preview") return pendingPreview;
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRulesCase("case-a");
    await screen.findByRole("button", { name: "영향 미리보기" });
    const caseInput = screen.getByLabelText("규칙 대화 사례 ID") as HTMLInputElement;
    fireEvent.click(screen.getByRole("button", { name: "영향 미리보기" }));
    const disabledWhilePreviewing = caseInput.disabled;
    finishPreview(jsonResponse({ preview_id: "preview-case-a", counts: {}, candidates: [] }));
    await screen.findByRole("button", { name: "확인한 범위로 적용" });

    expect(disabledWhilePreviewing).toBe(true);
  });

  it("discards a preview when the loaded rule version changes", async () => {
    let ruleVersion = 1;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/classification/dialog") {
        return jsonResponse({ dialog_state: "open", questions: [], answers: {}, draft: {} });
      }
      if (url.pathname === "/api/classification/conversation") {
        return jsonResponse({ state: "open", rule_id: "rule-case-a", turns: [] });
      }
      if (url.pathname === "/api/classification/rules/rule-case-a") {
        return jsonResponse({
          rule_id: "rule-case-a",
          version: ruleVersion,
          rule: { conditions: { merchant_normalized: { value: `merchant-v${ruleVersion}` } } },
        });
      }
      if (url.pathname === "/api/classification/rules/preview") {
        return jsonResponse({ preview_id: "preview-v1", counts: { included_rows: 1 }, candidates: [{ row_id: "row-v1" }] });
      }
      if (url.pathname === "/api/classification/dialog/close") {
        ruleVersion = 2;
        return jsonResponse({ message: "대화를 닫았습니다." });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRulesCase("case-a");
    await screen.findByText("merchant-v1");
    fireEvent.click(screen.getByRole("button", { name: "영향 미리보기" }));
    expect(await screen.findByRole("button", { name: "확인한 범위로 적용" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "대화 닫기" }));
    expect(await screen.findByText("merchant-v2")).toBeTruthy();

    expect(screen.queryByRole("button", { name: "확인한 범위로 적용" })).toBeNull();
    expect(screen.queryByRole("region", { name: "영향 미리보기 후보 표" })).toBeNull();
  });
});
