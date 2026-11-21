// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Bootstrap } from "../../api/types";
import { CardUploadPanel, type CardUploadJob } from "./cardUpload";

const OWNER: Bootstrap = {
  role: "owner", csrf: "synthetic-csrf", trips: [], capabilities: [], receipt_enabled: false,
};

const STATUS_A = `/api/imports/upload-status/${"a".repeat(32)}`;
const STATUS_B = `/api/imports/upload-status/${"b".repeat(32)}`;
const BATCH_A = `batch-${"a".repeat(24)}`;
const BATCH_B = `batch-${"b".repeat(24)}`;

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stubFetch(handler: (url: string) => Response) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    calls.push({ url, init });
    return handler(url);
  });
  vi.stubGlobal("fetch", stub);
  return { calls, stub };
}

function chooseFile(file: File) {
  const input = screen.getByLabelText(/카드 명세서 파일/) as HTMLInputElement;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

function uploadOne(filename: string) {
  chooseFile(new File(["a"], filename, { type: "text/csv" }));
  fireEvent.click(screen.getByRole("button", { name: "카드 파일 업로드" }));
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

it("renders the owner-only state without requesting anything for a viewer", () => {
  const { stub } = stubFetch(() => jsonResponse({}));
  render(<CardUploadPanel bootstrap={{ ...OWNER, role: "viewer" }} search={new URLSearchParams()} />);

  expect(screen.getByRole("heading", { name: "카드 파일 업로드는 소유자 전용입니다" })).toBeTruthy();
  expect(stub).not.toHaveBeenCalled();
});

it("shows the gap context for a valid gap query and stays quiet otherwise", () => {
  stubFetch(() => jsonResponse({}));
  render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams({
    gap_card: "synthetic-card", gap_start: "2026-04-01", gap_end: "2026-04-30", gap_issuer: "SYNTH",
  })} />);

  expect(screen.getByText(/파일 조회기간 사이 2026-04-01 ~ 2026-04-30/)).toBeTruthy();
});

it("fetches and renders a valid batch detail while ignoring an invalid batch id", async () => {
  const { calls } = stubFetch((url) => {
    if (url.endsWith(`/api/imports/${BATCH_A}`)) {
      return jsonResponse({ summary: { status: "classified", row_count: 7, error_count: 0 } });
    }
    return jsonResponse({});
  });

  const first = render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams({ batch: BATCH_A })} />);
  expect(await screen.findByText(/처리 행 7/)).toBeTruthy();
  expect(screen.getByText("처리 상태: classified")).toBeTruthy();
  expect(calls.some((call) => call.url.endsWith(`/api/imports/${BATCH_A}`))).toBe(true);
  first.unmount();

  calls.splice(0);
  render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams({ batch: "not-a-batch" })} />);
  expect(screen.queryByText("파일 처리 결과")).toBeNull();
  expect(calls.some((call) => call.url.includes("/api/imports/"))).toBe(false);
});

it("uploads a synthetic batch with the CSRF header, polls it, and reports the outcome", async () => {
  const { calls } = stubFetch((url) => {
    if (url === "/api/imports/upload-batch") {
      return jsonResponse({ files: [
        { filename: "synthetic-a.csv", batch_id: BATCH_A, status_url: STATUS_A },
        { filename: "synthetic-b.csv", batch_id: BATCH_B, status_url: STATUS_B },
      ] }, 202);
    }
    if (url === STATUS_A) return jsonResponse({ status: "done", result: { upload_summary: { transaction_count: 4 } } });
    if (url === STATUS_B) return jsonResponse({ status: "done", result: { upload_summary: { transaction_count: 2 } } });
    return jsonResponse({ code: "UNEXPECTED" }, 500);
  });

  render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams()} />);
  const input = screen.getByLabelText(/카드 명세서 파일/) as HTMLInputElement;
  Object.defineProperty(input, "files", {
    value: [new File(["a"], "synthetic-a.csv", { type: "text/csv" }),
      new File(["b"], "synthetic-b.csv", { type: "text/csv" })],
    configurable: true,
  });
  fireEvent.change(input);
  expect(screen.getByText("2개 파일 선택")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "카드 파일 업로드" }));

  await waitFor(() => expect(screen.getAllByText("처리됨")).toHaveLength(2));
  const post = calls.find((call) => call.url === "/api/imports/upload-batch");
  expect(post).toBeTruthy();
  expect(post!.init?.method).toBe("POST");
  expect((post!.init!.headers as Record<string, string>)["X-CSRF-Token"]).toBe("synthetic-csrf");
  expect(post!.init?.body).toBeInstanceOf(FormData);
  expect((post!.init!.body as FormData).getAll("files")).toHaveLength(2);
  expect(screen.getByText(/거래 4건 저장/)).toBeTruthy();
  expect(screen.getByText(/거래 2건 저장/)).toBeTruthy();
  await waitFor(() => expect(window.localStorage.getItem("cost-card-upload-job")).toBeNull());
});

it("shows a terminal upload processing error without retrying", async () => {
  const { calls } = stubFetch((url) => {
    if (url === "/api/imports/upload-batch") {
      return jsonResponse({ files: [{ filename: "synthetic.csv", batch_id: BATCH_A, status_url: STATUS_A }] }, 202);
    }
    if (url === STATUS_A) return jsonResponse({ status: "error", message: "parser rejected synthetic input" });
    return jsonResponse({});
  });

  render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams()} />);
  uploadOne("synthetic.csv");

  expect(await screen.findByText("parser rejected synthetic input")).toBeTruthy();
  expect(screen.getByText("확인 필요")).toBeTruthy();
  expect(calls.filter((call) => call.url === STATUS_A)).toHaveLength(1);
});

it("recovers an expired upload status through the saved batch", async () => {
  const { calls } = stubFetch((url) => {
    if (url === "/api/imports/upload-batch") {
      return jsonResponse({ files: [{ filename: "synthetic.csv", batch_id: BATCH_A, status_url: STATUS_A }] }, 202);
    }
    if (url === STATUS_A) return jsonResponse({ code: "UPLOAD_STATUS_EXPIRED" }, 404);
    if (url.startsWith(`${STATUS_A}?batch=`)) {
      return jsonResponse({ status: "saved", result: { batch_id: BATCH_A, recovery: { pending: false } } });
    }
    return jsonResponse({});
  });

  render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams()} />);
  uploadOne("synthetic.csv");

  expect(await screen.findByText("저장된 결과 조회 완료")).toBeTruthy();
  expect(calls.some((call) => call.url.startsWith(`${STATUS_A}?batch=`))).toBe(true);
});

it.each([
  ["more than 100 files", 101, 1],
  ["more than 99 MB in total", 6, 17 * 1024 * 1024],
])("blocks submission with %s", (_label, count, size) => {
  const { calls } = stubFetch(() => jsonResponse({}));
  render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams()} />);
  const files = Array.from({ length: count }, (_, index) => {
    const file = new File([""], `synthetic-${index}.csv`, { type: "text/csv" });
    Object.defineProperty(file, "size", { value: size });
    return file;
  });
  const input = screen.getByLabelText(/카드 명세서 파일/) as HTMLInputElement;
  Object.defineProperty(input, "files", { value: files, configurable: true });
  fireEvent.change(input);
  expect(screen.getByText(`${count}개 파일 선택`)).toBeTruthy();
  expect(screen.getByText("한 번에 100개, 전체 99MB 이하로 나누어 선택해 주세요.")).toBeTruthy();

  fireEvent.submit(input.form as HTMLFormElement);
  expect(calls).toHaveLength(0);
});

it("resumes stored jobs from a previous visit", async () => {
  const stored: CardUploadJob = { filename: "resumed.csv", batch_id: BATCH_A, status_url: STATUS_A };
  window.localStorage.setItem("cost-card-upload-job", JSON.stringify([stored]));
  stubFetch((url) => {
    if (url === STATUS_A) return jsonResponse({ status: "done", result: { upload_summary: { transaction_count: 3 } } });
    return jsonResponse({});
  });

  render(<CardUploadPanel bootstrap={OWNER} search={new URLSearchParams()} />);

  expect(await screen.findByText("resumed.csv")).toBeTruthy();
  expect(await screen.findByText(/거래 3건 저장/)).toBeTruthy();
  await waitFor(() => expect(window.localStorage.getItem("cost-card-upload-job")).toBeNull());
});
