/** Same-origin, no-store client for authenticated COST JSON and action APIs. */

import type { ActionDescriptor } from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export type ActionRedirect = { kind: "redirect"; location: string };
export type ActionBlob = { kind: "blob"; blob: Blob };
export type ActionJson<T> = { kind: "json"; data: T };
export type ActionResult<T> = ActionJson<T> | ActionBlob | ActionRedirect;
export type ActionValue = string | number | boolean | Blob | Array<string | number | boolean | Blob> | null | undefined;

function checkedUrl(path: string): URL {
  if (typeof path !== "string" || !path.startsWith("/api/") || path.startsWith("//")) {
    throw new ApiError("INVALID_API_PATH", 0, "허용된 API 경로가 아닙니다.");
  }

  const origin = typeof globalThis.location !== "undefined"
    ? globalThis.location.origin
    : "http://localhost";
  const url = new URL(path, origin);
  if (url.origin !== origin || url.username || url.password || url.hash) {
    throw new ApiError("INVALID_API_PATH", 0, "허용된 API 경로가 아닙니다.");
  }
  return url;
}

function apiErrorFromPayload(payload: unknown, status: number): ApiError {
  const error = payload && typeof payload === "object"
    ? payload as Record<string, unknown>
    : {};
  return new ApiError(
    typeof error.code === "string" ? error.code : "REQUEST_FAILED",
    status,
    typeof error.message === "string" ? error.message : "요청을 처리하지 못했습니다.",
  );
}

async function readJson(response: Response): Promise<unknown> {
  if (!(response.headers.get("content-type") || "").toLowerCase().includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function readError(response: Response): Promise<ApiError> {
  return apiErrorFromPayload(await readJson(response), response.status);
}

function jsonResult<T>(payload: unknown, status: number): ActionJson<T> {
  if (payload === null) {
    throw new ApiError("INVALID_RESPONSE", status, "서버 응답을 읽지 못했습니다.");
  }
  return { kind: "json", data: payload as T };
}

async function send<T>(url: URL, init: RequestInit, responseKind: ActionDescriptor["response"]): Promise<ActionResult<T>> {
  const response = await fetch(url, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json", ...(init.headers || {}) },
  });

  if (!response.ok) throw await readError(response);

  if (responseKind === "blob") {
    if (response.redirected) {
      throw new ApiError("UNEXPECTED_REDIRECT", response.status, "다운로드 경로가 바뀌었습니다.");
    }
    const textBody = await response.text();
    return { kind: "blob", blob: new Blob([textBody], { type: response.headers.get("content-type") || "application/octet-stream" }) };
  }

  if (responseKind === "redirect") {
    if (response.redirected) {
      const destination = new URL(response.url);
      if (destination.origin !== url.origin || !destination.pathname.startsWith("/api/")) {
        throw new ApiError("UNEXPECTED_REDIRECT", response.status, "허용된 API 경로로 이동하지 않았습니다.");
      }
      return { kind: "redirect", location: `${destination.pathname}${destination.search}` };
    }
    return jsonResult<T>(await readJson(response), response.status);
  }

  return jsonResult<T>(await readJson(response), response.status);
}

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const result = await send<T>(checkedUrl(path), { method: "GET", signal }, "json");
  return (result as ActionJson<T>).data;
}

export async function postJSON<T>(path: string, payload: unknown, csrf: string): Promise<T> {
  const result = await send<T>(checkedUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(payload),
  }, "json");
  return (result as ActionJson<T>).data;
}

function valueForField(action: ActionDescriptor, name: string, value: ActionValue): ActionValue {
  const field = action.fields?.find((item) => item.name === name);
  if (!field) throw new ApiError("INVALID_ACTION_PAYLOAD", 0, "허용되지 않은 입력 항목입니다.");
  if (field.read_only) throw new ApiError("INVALID_ACTION_PAYLOAD", 0, "읽기 전용 항목은 보낼 수 없습니다.");
  if (Array.isArray(value) && !field.multiple) {
    throw new ApiError("INVALID_ACTION_PAYLOAD", 0, "여러 값을 보낼 수 없는 항목입니다.");
  }
  if (field.type === "file") {
    const files = Array.isArray(value) ? value : value == null ? [] : [value];
    if (files.some((file) => !(file instanceof Blob))) {
      throw new ApiError("INVALID_ACTION_PAYLOAD", 0, "파일 입력 형식이 올바르지 않습니다.");
    }
  } else if (value instanceof Blob || (Array.isArray(value) && value.some((item) => item instanceof Blob))) {
    throw new ApiError("INVALID_ACTION_PAYLOAD", 0, "파일 입력 항목이 아닙니다.");
  }
  return value;
}

function formValue(value: string | number | boolean): string {
  return typeof value === "boolean" ? (value ? "1" : "0") : String(value);
}

function scalarValues(value: ActionValue): Array<string | number | boolean> {
  if (value == null || value instanceof Blob) return [];
  if (Array.isArray(value)) return value.filter((item): item is string | number | boolean => !(item instanceof Blob));
  return [value];
}

/**
 * Execute a server supplied, allowlisted action. Payload keys must be declared
 * by the descriptor; arbitrary same-origin paths or form fields are refused.
 */
export async function executeAction<T>(
  action: ActionDescriptor,
  values: Record<string, ActionValue> = {},
  csrfToken = "",
): Promise<ActionResult<T>> {
  if (action.disabled) {
    throw new ApiError("ACTION_DISABLED", 0, action.reason || "이 동작을 사용할 수 없습니다.");
  }
  const url = checkedUrl(action.href);
  if (!(action.method === "GET" || action.method === "POST") ||
      !(action.encoding === "json" || action.encoding === "form" || action.encoding === "multipart") ||
      !(action.csrf === "header" || action.csrf === "field" || action.csrf === "none") ||
      !(action.response === "json" || action.response === "redirect" || action.response === "blob")) {
    throw new ApiError("INVALID_ACTION", 0, "서버 동작 설명이 올바르지 않습니다.");
  }
  if (action.method === "GET" && action.encoding !== "form") {
    throw new ApiError("INVALID_ACTION", 0, "조회 동작 형식이 올바르지 않습니다.");
  }
  if (action.method === "POST" && action.response === "blob") {
    throw new ApiError("INVALID_ACTION", 0, "파일 응답은 GET 동작에서만 허용됩니다.");
  }
  if (action.csrf !== "none" && !csrfToken) {
    throw new ApiError("CSRF_REQUIRED", 403, "확인 토큰이 없습니다.");
  }

  const normalized: Record<string, ActionValue> = {};
  for (const [name, value] of Object.entries(values)) {
    normalized[name] = valueForField(action, name, value);
  }
  for (const field of action.fields || []) {
    if (!(field.name in normalized) && field.value != null && !field.read_only) {
      normalized[field.name] = valueForField(action, field.name, field.value as ActionValue);
    }
    const value = normalized[field.name];
    if (field.required && (value == null || (Array.isArray(value) && value.length === 0)) && field.value == null) {
      throw new ApiError("INVALID_ACTION_PAYLOAD", 0, `필수 입력 항목이 없습니다: ${field.label}`);
    }
  }

  const headers: Record<string, string> = {};
  if (action.csrf === "header") headers["X-CSRF-Token"] = csrfToken;
  const data = { ...normalized };
  if (action.csrf === "field") data.csrf = csrfToken;

  if (action.method === "GET") {
    const orderedNames = [
      ...(action.fields || []).map((field) => field.name),
      ...Object.keys(data).filter((name) => !(action.fields || []).some((field) => field.name === name)),
    ];
    for (const name of orderedNames) {
      const value = data[name];
      if (value == null) continue;
      if (value instanceof Blob || (Array.isArray(value) && value.some((item) => item instanceof Blob))) {
        throw new ApiError("INVALID_ACTION_PAYLOAD", 0, "파일은 조회 조건으로 보낼 수 없습니다.");
      }
      for (const item of scalarValues(value)) url.searchParams.append(name, formValue(item));
    }
    return send<T>(url, { method: "GET", headers }, action.response);
  }

  if (action.encoding === "json") {
    headers["Content-Type"] = "application/json";
    return send<T>(url, { method: "POST", headers, body: JSON.stringify(data) }, action.response);
  }

  if (action.encoding === "form") {
    const form = new URLSearchParams();
    for (const [name, value] of Object.entries(data)) {
      if (value == null) continue;
      if (value instanceof Blob || (Array.isArray(value) && value.some((item) => item instanceof Blob))) {
        throw new ApiError("INVALID_ACTION_PAYLOAD", 0, "파일은 일반 폼으로 보낼 수 없습니다.");
      }
      for (const item of scalarValues(value)) form.append(name, formValue(item));
    }
    headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8";
    return send<T>(url, { method: "POST", headers, body: form.toString() }, action.response);
  }

  const multipart = new FormData();
  for (const [name, value] of Object.entries(data)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item instanceof Blob) multipart.append(name, item);
        else multipart.append(name, formValue(item));
      }
    } else if (value instanceof Blob) {
      multipart.append(name, value);
    } else {
      multipart.append(name, formValue(value));
    }
  }
  return send<T>(url, { method: "POST", headers, body: multipart }, action.response);
}

/** Backward-compatible name for feature pages already using submit terminology. */
export const submitAction = executeAction;
