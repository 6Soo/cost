/** Same-origin, no-store JSON client for authenticated COST APIs. */

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

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  let payload: unknown;
  try {
    payload = contentType.toLowerCase().includes("application/json")
      ? await response.json()
      : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = payload && typeof payload === "object"
      ? payload as Record<string, unknown>
      : {};
    throw new ApiError(
      typeof error.code === "string" ? error.code : "REQUEST_FAILED",
      response.status,
      typeof error.message === "string" ? error.message : "요청을 처리하지 못했습니다.",
    );
  }

  if (payload === null) {
    throw new ApiError("INVALID_RESPONSE", response.status, "서버 응답을 읽지 못했습니다.");
  }
  return payload as T;
}

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(checkedUrl(path), {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  return parseResponse<T>(response);
}

export async function postJSON<T>(path: string, payload: unknown, csrf: string): Promise<T> {
  const response = await fetch(checkedUrl(path), {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
    },
    body: JSON.stringify(payload),
  });
  return parseResponse<T>(response);
}
