// @vitest-environment jsdom
import { createElement } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import type { PageProps } from "../transactions/feature-ui";
import { AuxiliaryPage } from "./index";

function renderLinksPage(view: "participants" | "reserve-links", search = "",
                          options: { trips?: Bootstrap["trips"] } = {}) {
  const props: PageProps = {
    bootstrap: {
      role: "owner",
      csrf: "csrf-synthetic",
      trips: options.trips ?? [{
        id: "trip-a", title: "알파 여행", kind: "trip", previous: false,
        starts_on: "2026-11-01", ends_on: "2026-11-03", income: "0",
        expense: "0", profit: "0", closed: false, archived: false,
      }],
      capabilities: [],
      receipt_enabled: false,
    },
    path: view === "participants" ? "/participants" : "/reserve-links",
    search: new URLSearchParams(search),
  };
  return render(createElement(AuxiliaryPage, props));
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestBody(init: RequestInit | undefined): Record<string, unknown> {
  return JSON.parse(String(init?.body || "{}")) as Record<string, unknown>;
}

describe("auxiliary link screens", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("links and unlinks a participant using GET choices and the current fingerprint", async () => {
    let linked = false;
    const writes: Array<{ path: string; init?: RequestInit }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") {
        return jsonResponse({
          trip_id: "trip-a",
          configured: true,
          input_fingerprint: linked ? "participant-fp-2" : "participant-fp-1",
          counts: { participants: 1, linked_income_rows: linked ? 1 : 0, unlinked_income_rows: linked ? 0 : 1 },
          participants: [{
            participant_id: "participant-syn-1",
            display_name: "가람 합성",
            active: true,
            participant_state: "confirmed",
            state: linked ? "manual" : "unlinked",
            links: linked ? [{
              income_ref: "income-ref-syn-9",
              method: "manual",
              row: { ref: "income-ref-syn-9", row: 9, name: "가람 합성", amount: 12000 },
            }] : [],
            candidate_refs: ["income-ref-syn-9"],
          }],
          income_rows: [{
            ref: "income-ref-syn-9", row: 9, name: "가람 합성", nickname: "가람",
            amount: 12000, cells: { E: 4000, F: 8000, G: 0 },
          }],
          unlinked_income: linked ? [] : [{
            ref: "income-ref-syn-9", row: 9, name: "가람 합성", amount: 12000,
          }],
        });
      }
      if (url.pathname === "/api/participants/link" || url.pathname === "/api/participants/unlink") {
        writes.push({ path: url.pathname, init });
        linked = url.pathname.endsWith("/link");
        return jsonResponse({ code: "OK", result: { saved: true } });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a");

    const incomeSelect = await screen.findByRole("combobox", { name: "수입 행 선택 · 가람 합성" });
    expect(screen.getByRole("option", { name: /가람 합성/ })).toBeTruthy();
    fireEvent.change(incomeSelect, { target: { value: "income-ref-syn-9" } });
    fireEvent.click(screen.getByRole("button", { name: "연결 · 가람 합성" }));
    expect(await screen.findByRole("button", { name: "연결 해제 · 가람 합성 · 9행" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "연결 해제 · 가람 합성 · 9행" }));
    await screen.findByRole("button", { name: "연결 · 가람 합성" });

    expect(writes.map(({ path }) => path)).toEqual([
      "/api/participants/link",
      "/api/participants/unlink",
    ]);
    expect(requestBody(writes[0].init)).toMatchObject({
      trip: "trip-a",
      participant_id: "participant-syn-1",
      income_ref: "income-ref-syn-9",
      input_fingerprint: "participant-fp-1",
      joint: false,
    });
    expect(requestBody(writes[1].init)).toMatchObject({
      trip: "trip-a",
      participant_id: "participant-syn-1",
      income_ref: "income-ref-syn-9",
      input_fingerprint: "participant-fp-2",
    });
    for (const write of writes) {
      expect(write.init?.headers).toMatchObject({ "X-CSRF-Token": "csrf-synthetic" });
    }
  });

  it("offers name, alias, trip and duplicate-name correction with the current fingerprint", async () => {
    const participantWrites: Array<{ body: Record<string, unknown>; init?: RequestInit }> = [];
    const linkWrites: Array<{ body: Record<string, unknown>; init?: RequestInit }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") {
        return jsonResponse({
          trip_id: "trip-a",
          configured: true,
          input_fingerprint: "participant-fp-roster",
          counts: { participants: 2, linked_income_rows: 0, unlinked_income_rows: 1 },
          participants: [
            {
              participant_id: "participant-syn-1", display_name: "가람 합성", nickname: "가람",
              active: true, participant_state: "confirmed", state: "unlinked", links: [],
              candidate_refs: ["income-ref-syn-9"],
            },
            {
              participant_id: "participant-syn-2", display_name: "나래 합성",
              active: true, participant_state: "confirmed", state: "unlinked", links: [],
            },
          ],
          income_rows: [
            { ref: "income-ref-syn-9", row: 9, name: "가람 합성", amount: 12000 },
            { ref: "income-ref-syn-8", row: 8, name: "이름 미확인 합성", nickname: "", amount: null },
          ],
          unlinked_income: [
            { ref: "income-ref-syn-8", row: 8, name: "이름 미확인 합성", nickname: "",
              amount: null, cells: {}, state: "not_in_roster" },
          ],
        });
      }
      if (url.pathname === "/api/participants/participant") {
        participantWrites.push({ body: requestBody(init), init });
        return jsonResponse({ code: "OK", result: { saved: true } });
      }
      if (url.pathname === "/api/participants/link") {
        linkWrites.push({ body: requestBody(init), init });
        return jsonResponse({ code: "OK", result: { saved: true } });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a", { trips: [
      { id: "trip-a", title: "알파 여행", kind: "trip", previous: false,
        starts_on: "2026-11-01", ends_on: "2026-11-03", income: "0", expense: "0",
        profit: "0", closed: false, archived: false },
      { id: "trip-b", title: "베타 여행", kind: "trip", previous: false,
        starts_on: "2026-11-04", ends_on: "2026-11-05", income: "0", expense: "0",
        profit: "0", closed: false, archived: false },
    ] });

    const rename = await screen.findByLabelText("이름 정정 값 · 가람 합성");
    fireEvent.change(rename, { target: { value: "가람 정정" } });
    fireEvent.click(await screen.findByRole("button", { name: "이름 정정 저장 · 가람 합성" }));
    expect(await screen.findByText("이름을 정정했습니다.")).toBeTruthy();

    fireEvent.change(await screen.findByLabelText("확인된 별칭 값 · 가람 합성"), { target: { value: "가람별칭" } });
    fireEvent.click(screen.getByRole("button", { name: "별칭 확인 저장 · 가람 합성" }));
    expect(await screen.findByText("별칭을 확인했습니다.")).toBeTruthy();

    fireEvent.change(await screen.findByLabelText("여행 선택 · 가람 합성"), { target: { value: "trip-b" } });
    fireEvent.change(await screen.findByLabelText("여행 교정 사유 · 가람 합성"), { target: { value: "이동" } });
    fireEvent.click(await screen.findByRole("button", { name: "여행 연결 수정 · 가람 합성" }));
    expect(await screen.findByText("여행 연결을 수정했습니다.")).toBeTruthy();

    fireEvent.change(await screen.findByLabelText("같은 사람으로 확인 대상 · 나래 합성"),
      { target: { value: "participant-syn-1" } });
    fireEvent.click(await screen.findByRole("button", { name: "같은 사람 확인 저장 · 나래 합성" }));
    expect(await screen.findByText("같은 사람으로 확인했습니다.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("서로 다른 사람으로 확인 대상 · 나래 합성"),
      { target: { value: "participant-syn-1" } });
    fireEvent.click(await screen.findByRole("button", { name: "서로 다른 사람 확인 저장 · 나래 합성" }));
    expect(await screen.findByText("서로 다른 사람으로 확인했습니다.")).toBeTruthy();

    expect(screen.queryByRole("heading", { name: "미연결 수입 검토" })).toBeNull();

    expect(participantWrites.map((write) => write.body)).toEqual([
      { trip: "trip-a", action: "rename", participant_id: "participant-syn-1",
        name: "가람 정정", reason: "", input_fingerprint: "participant-fp-roster" },
      { trip: "trip-a", action: "alias", participant_id: "participant-syn-1",
        alias: "가람별칭", input_fingerprint: "participant-fp-roster" },
      { trip: "trip-a", action: "remap", participant_id: "participant-syn-1",
        target_trip: "trip-b", reason: "이동", input_fingerprint: "participant-fp-roster" },
      { trip: "trip-a", action: "same_person", participant_id: "participant-syn-2",
        other_participant_id: "participant-syn-1", input_fingerprint: "participant-fp-roster" },
      { trip: "trip-a", action: "separate", participant_id: "participant-syn-2",
        other_participant_id: "participant-syn-1", input_fingerprint: "participant-fp-roster" },
    ]);
    expect(linkWrites).toHaveLength(0);
    for (const write of participantWrites) {
      expect(write.init?.headers).toMatchObject({ "X-CSRF-Token": "csrf-synthetic" });
    }
  });

  it("keeps correction writes disabled without a usable fingerprint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") {
        return jsonResponse({
          trip_id: "trip-a", configured: true, input_fingerprint: "",
          counts: { participants: 1, linked_income_rows: 0, unlinked_income_rows: 0 },
          participants: [{
            participant_id: "participant-syn-1", display_name: "가람 합성", nickname: "",
            active: true, participant_state: "confirmed", state: "unlinked", links: [],
          }],
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a");
    expect(await screen.findByText(
      "대조 상태가 준비되지 않아 교정 내용을 저장할 수 없습니다.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "이름 정정 저장 · 가람 합성" })
      .hasAttribute("disabled")).toBe(true);
  });

  it("surfaces a stale conflict without reporting a false success", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") {
        return jsonResponse({
          trip_id: "trip-a", configured: true, input_fingerprint: "participant-fp-stale",
          counts: { participants: 1, linked_income_rows: 0, unlinked_income_rows: 0 },
          participants: [{
            participant_id: "participant-syn-1", display_name: "가람 합성", nickname: "",
            active: true, participant_state: "confirmed", state: "unlinked", links: [],
          }],
        });
      }
      if (url.pathname === "/api/participants/participant") {
        return jsonResponse({
          code: "STALE_RECONCILIATION", message: "화면이 오래됐어요. 다시 확인해 주세요",
        }, 409);
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a");
    const rename = await screen.findByLabelText("이름 정정 값 · 가람 합성");
    fireEvent.change(rename, { target: { value: "가람 정정" } });
    fireEvent.click(screen.getByRole("button", { name: "이름 정정 저장 · 가람 합성" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent)
      .toContain("화면이 오래됐어요. 다시 확인해 주세요");
    expect(screen.queryByText("이름을 정정했습니다.")).toBeNull();
  });

  it("skips correction writes for rows without a participant identifier or income ref", async () => {
    const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") {
        return jsonResponse({
          trip_id: "trip-a", configured: true, input_fingerprint: "participant-fp-identity",
          counts: { participants: 1, linked_income_rows: 0, unlinked_income_rows: 1 },
          participants: [{
            display_name: "식별자 없는 합성", nickname: "",
            active: true, participant_state: "confirmed", state: "unlinked", links: [],
          }],
          income_rows: [],
          unlinked_income: [{ ref: "", row: 3, name: "식별자 없는 행", nickname: "", amount: 5000, cells: {}, state: "not_in_roster" }],
        });
      }
      if (String(url.pathname).startsWith("/api/participants/")) {
        writes.push({ path: url.pathname, body: requestBody(init) });
        return jsonResponse({ code: "OK", result: { saved: true } });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a");
    expect(await screen.findByText("참가자 식별자가 없어 교정 내용을 저장하지 않습니다.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /이름 정정/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /검토 완료/ })).toBeNull();
    writes.length = 0;
  });

  it("does not carry an unsubmitted draft onto a new fingerprint and sends only re-submitted values", async () => {
    let stateCalls = 0;
    const participantWrites: Array<{ body: Record<string, unknown>; init?: RequestInit }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") {
        stateCalls += 1;
        return jsonResponse({
          trip_id: "trip-a", configured: true,
          input_fingerprint: stateCalls === 1 ? "participant-fp-first" : "participant-fp-refreshed",
          counts: { participants: 1, linked_income_rows: 0, unlinked_income_rows: 0 },
          participants: [{
            participant_id: "participant-syn-1",
            display_name: stateCalls === 1 ? "가람 합성" : "가람 갱신",
            nickname: "", active: true, participant_state: "confirmed",
            state: "unlinked", links: [],
          }],
        });
      }
      if (url.pathname === "/api/participants/participant") {
        participantWrites.push({ body: requestBody(init), init });
        return jsonResponse({ code: "OK", result: { saved: true } });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a");
    const rename = await screen.findByLabelText("이름 정정 값 · 가람 합성");
    fireEvent.change(rename, { target: { value: "가람-미제출-값" } });
    fireEvent.click(screen.getByRole("button", { name: "새로고침" }));
    await waitFor(() => expect(stateCalls).toBe(2));
    expect(participantWrites).toHaveLength(0);
    // A refresh that returns a new fingerprint must not attach the unapproved
    // draft to it: the field shows the fresh server value again.
    const refreshed = await screen.findByLabelText("이름 정정 값 · 가람 갱신");
    expect((refreshed as HTMLInputElement).value).toBe("가람 갱신");

    fireEvent.change(refreshed, { target: { value: "가람-새-값" } });
    fireEvent.click(await screen.findByRole("button", { name: "이름 정정 저장 · 가람 갱신" }));
    expect(await screen.findByText("이름을 정정했습니다.")).toBeTruthy();
    expect(participantWrites).toHaveLength(1);
    expect(participantWrites[0].body).toMatchObject({
      trip: "trip-a", action: "rename", participant_id: "participant-syn-1",
      name: "가람-새-값", reason: "", input_fingerprint: "participant-fp-refreshed",
    });
    // A successful write is not re-sent by the retained draft; another request
    // needs another explicit submit.
    await waitFor(() => expect(participantWrites).toHaveLength(1));
    expect((await screen.findByLabelText("이름 정정 값 · 가람 갱신") as HTMLInputElement).value)
      .toBe("가람-새-값");
  });

  it("saves selected reservation links and applies the refreshed plan with stable request ids", async () => {
    const sourceEventKey = "reservation:event:synthetic";
    const sourceBinding = { source_revision: 4, source_digest: "source-digest-synthetic" };
    let saved = false;
    const saveRequests: Array<{ init?: RequestInit; body: Record<string, unknown> }> = [];
    const applyRequests: Array<{ init?: RequestInit; body: Record<string, unknown> }> = [];
    let saveAttempt = 0;
    let applyAttempt = 0;
    const currentPlan = () => ({
      configured: true,
      readable: true,
      binding: sourceBinding,
      link_version: saved ? 2 : 1,
      link_revision: saved ? 3 : 2,
      link_digest: saved ? "link-digest-synthetic-2" : "link-digest-synthetic-1",
      apply_digest: saved ? "apply-digest-synthetic-2" : "apply-digest-synthetic-1",
      applicable: saved,
      refusal_code: saved ? "" : "UNLINKED",
      counts: { source_identifiers: 1, resolved_transactions: saved ? 1 : 0, unlinked_identifiers: saved ? 0 : 1, persons: 1 },
      persons: [{
        reservation_person_id: "reservation-person-syn-1",
        display_name: "예약자 합성",
        is_active: true,
        assignments: [sourceEventKey],
        connected: [],
      }],
      per_identifier: { [sourceEventKey]: saved ? ["trip-target-syn-1"] : [] },
      unlinked: saved ? [] : [sourceEventKey],
      resolved: saved ? [{ source_event_key: sourceEventKey, target_tab_id: "trip-target-syn-1", origin: "manual" }] : [],
      choices: [{ tab_id: "trip-target-syn-1", label: "알파 여행", destination: "합성 목적지" }],
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/reserve-link/plan" && (!init || init.method === "GET")) {
        return jsonResponse(currentPlan());
      }
      if (url.pathname === "/api/reserve-link/links") {
        saveAttempt += 1;
        saveRequests.push({ init, body: requestBody(init) });
        if (saveAttempt === 1) throw new Error("synthetic lost response");
        saved = true;
        return jsonResponse({
          outcome: "saved",
          request_id: requestBody(init).request_id,
          linked: [{ source_event_key: sourceEventKey, target_tab_id: "trip-target-syn-1" }],
          unlinked: [],
          link_version: 2,
          link_revision: 3,
          link_digest: "link-digest-synthetic-2",
          counts: { links: 1 },
        });
      }
      if (url.pathname === "/api/reserve-link/apply") {
        applyAttempt += 1;
        applyRequests.push({ init, body: requestBody(init) });
        if (applyAttempt === 1) throw new Error("synthetic lost apply response");
        return jsonResponse({
          outcome: "applied",
          request_id: requestBody(init).request_id,
          apply_digest: "apply-digest-synthetic-2",
          counts: { linked: 1, disconnected: 0, unchanged: 0 },
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("reserve-links");

    const targets = await screen.findByRole("listbox", { name: `대상 선택 · ${sourceEventKey}` });
    expect(screen.getByRole("option", { name: "알파 여행" })).toBeTruthy();
    (screen.getByRole("option", { name: "알파 여행" }) as HTMLOptionElement).selected = true;
    fireEvent.change(targets);
    fireEvent.click(screen.getByRole("button", { name: "연결 저장" }));
    expect(await screen.findByText("synthetic lost response")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "연결 저장" }));
    expect(await screen.findByText("예약 연결을 저장했습니다.")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "현재 연결 반영" }).hasAttribute("disabled")).toBe(false);
    });

    fireEvent.click(screen.getByRole("button", { name: "현재 연결 반영" }));
    expect(await screen.findByText("synthetic lost apply response")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "현재 연결 반영" }).hasAttribute("disabled")).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: "현재 연결 반영" }));
    expect(await screen.findByText(/예약 연결 반영 완료.*1건/)).toBeTruthy();

    expect(saveRequests).toHaveLength(2);
    expect(saveRequests[0].body.request_id).toBeTruthy();
    expect(saveRequests[1].body.request_id).toBe(saveRequests[0].body.request_id);
    expect(saveRequests[0].body).toMatchObject({
      source_binding: sourceBinding,
      link_revision: 2,
      links: [{ source_event_key: sourceEventKey, target_tab_id: "trip-target-syn-1" }],
      unlinks: [],
    });
    expect(saveRequests[0].init?.headers).toMatchObject({ "X-CSRF-Token": "csrf-synthetic" });

    expect(applyRequests).toHaveLength(2);
    expect(applyRequests[0].body.request_id).toBeTruthy();
    expect(applyRequests[1].body.request_id).toBe(applyRequests[0].body.request_id);
    expect(applyRequests[0].body).toMatchObject({
      source_binding: sourceBinding,
      link_revision: 3,
      apply_digest: "apply-digest-synthetic-2",
    });
    expect(applyRequests[0].init?.headers).toMatchObject({ "X-CSRF-Token": "csrf-synthetic" });
  });

  it("keeps the saved reservation assignment visible and blocks apply while a different draft is unsaved", async () => {
    const sourceEventKey = "reservation:event:already-linked";
    const applyRequests: RequestInit[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/reserve-link/plan") {
        return jsonResponse({
          configured: true,
          readable: true,
          binding: { source_revision: 7, source_digest: "source-digest-current" },
          link_revision: 8,
          apply_digest: "apply-digest-current",
          applicable: true,
          counts: { source_identifiers: 1, resolved_transactions: 1, unlinked_identifiers: 0, persons: 1 },
          persons: [{ reservation_person_id: "person-syn", display_name: "예약자 합성", assignments: [sourceEventKey] }],
          per_identifier: { [sourceEventKey]: ["trip-target-a"] },
          choices: [
            { tab_id: "trip-target-a", label: "알파 여행", destination: "합성 목적지 A" },
            { tab_id: "trip-target-b", label: "베타 여행", destination: "합성 목적지 B" },
          ],
        });
      }
      if (url.pathname === "/api/reserve-link/apply") {
        applyRequests.push(init || {});
        return jsonResponse({ outcome: "applied", counts: { linked: 1, disconnected: 0, unchanged: 0 } });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("reserve-links");

    const targets = await screen.findByRole("listbox", { name: `대상 선택 · ${sourceEventKey}` }) as HTMLSelectElement;
    const alpha = screen.getByRole("option", { name: "알파 여행" }) as HTMLOptionElement;
    const beta = screen.getByRole("option", { name: "베타 여행" }) as HTMLOptionElement;
    alpha.selected = false;
    beta.selected = true;
    fireEvent.change(targets);

    expect(screen.getByRole("button", { name: "현재 연결 반영" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("저장되지 않은 연결 변경이 있습니다. 현재 연결 반영 전에 연결을 먼저 저장해 주세요.")).toBeTruthy();

    const row = within(screen.getByRole("table", { name: "예약 식별자 연결" })).getAllByRole("row")[1];
    const cells = within(row).getAllByRole("cell");
    expect(cells[1].textContent).toContain("알파 여행");
    expect(cells[1].textContent).not.toContain("베타 여행");
    expect(targets.value).toBe("trip-target-b");

    fireEvent.click(screen.getByRole("button", { name: "현재 연결 반영" }));
    expect(applyRequests).toHaveLength(0);
  });

  it("counts unique linked income refs from participant links when server summary counts are absent", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") {
        return jsonResponse({
          trip_id: "trip-a",
          configured: true,
          input_fingerprint: "participant-fingerprint-synthetic",
          participants: [
            {
              participant_id: "participant-syn-1", display_name: "가람 합성", active: true,
              participant_state: "confirmed", state: "manual",
              links: [{ income_ref: "income-ref-shared", row: { ref: "income-ref-shared", row: 4, name: "공동 합성", amount: 15000 } }],
            },
            {
              participant_id: "participant-syn-2", display_name: "나래 합성", active: true,
              participant_state: "confirmed", state: "manual",
              links: [
                { income_ref: "income-ref-shared", row: { ref: "income-ref-shared", row: 4, name: "공동 합성", amount: 15000 } },
                { income_ref: "income-ref-second", row: { ref: "income-ref-second", row: 5, name: "나래 합성", amount: 9000 } },
              ],
            },
          ],
          income_rows: [],
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a");

    const summaryHeading = await screen.findByRole("heading", { name: "현재 대조 상태" });
    const summary = summaryHeading.closest("section");
    expect(summary).toBeTruthy();
    expect(within(summary as HTMLElement).getByText("2건")).toBeTruthy();
  });

  it("links to the existing participant correction and income review workflow for the selected trip", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname === "/api/participants/state") return jsonResponse({
        trip_id: "trip-a", configured: true, input_fingerprint: "participant-fp-synthetic",
        counts: { participants: 0, unlinked_income_rows: 0 }, participants: [], income_rows: [],
      });
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderLinksPage("participants", "trip=trip-a");

    const legacyWorkflow = await screen.findByRole("link", {
      name: "참가자 이름·별칭·여행 교정 및 미연결 수입 검토 (기존 화면)",
    });
    expect(legacyWorkflow.getAttribute("href")).toBe("/participants?trip=trip-a");
  });
});
