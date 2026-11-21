// Shared JSON-shape display helpers for the auxiliary feature pages. Kept in one
// module so participant and reservation screens render server rows the same way.
export type AnyRecord = Record<string, unknown>;

export function record(value: unknown): AnyRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
}

export function records(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

export function text(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

export function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : [];
}

export function amountLabel(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return `${new Intl.NumberFormat("ko-KR").format(value)}원`;
  const valueText = text(value);
  return valueText ? `${valueText}원` : "금액 확인 안 됨";
}
