/** Authenticated JSON DTOs shared by the Plush UI feature pages. */

export type Role = "owner" | "viewer";

export interface TripSummary {
  id: string;
  title: string;
  display_key?: string;
  kind: "trip" | "quarter";
  previous: boolean;
  starts_on: string;
  ends_on: string;
  income: string;
  expense: string;
  profit: string;
  closed: boolean;
  archived: boolean;
}

export interface Bootstrap {
  role: Role;
  csrf: string;
  trips: TripSummary[];
  capabilities: string[];
  receipt_enabled: boolean;
  screen_titles?: Record<string, string>;
}

export interface JobSummary {
  id: string;
  label: string;
  status?: "running" | "success" | "error" | "unknown";
  state?: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "unknown";
  updated_at?: string;
  detail?: string;
  message?: string;
  completed?: number;
  total?: number;
  href?: string;
}

export type LedgerSort = "date_desc" | "date_asc" | "merchant_asc" | "merchant_desc" | "amount_desc" | "amount_asc";
export const LEDGER_SORTS: readonly LedgerSort[] = [
  "date_desc", "date_asc", "merchant_asc", "merchant_desc", "amount_desc", "amount_asc",
];

export interface HomeResponse {
  trips: TripSummary[];
  jobs: JobSummary[];
  updated_at: string;
}

export interface LedgerRow {
  id: string;
  date: string;
  merchant: string;
  description: string;
  category: string;
  amount: string;
  currency: string;
  payment: string;
  period: string;
  evidence_summary: string;
  revision?: string | number;
  read_only: boolean;
}

export interface LedgerResponse {
  trip: TripSummary;
  rows: LedgerRow[];
  total_count: number;
  page: number;
  page_size: number;
  filtered_total: string;
  total: string;
  closed: boolean;
}

export interface FieldOption {
  value: string;
  label: string;
}

export interface FieldDescriptor {
  name: string;
  label: string;
  type: "text" | "number" | "date" | "select" | "checkbox" | "file" | "hidden";
  value?: string | number | boolean;
  options?: FieldOption[];
  required?: boolean;
  read_only?: boolean;
  accept?: string;
  multiple?: boolean;
}

export interface ActionDescriptor {
  id: string;
  label: string;
  method: "GET" | "POST";
  href: string;
  encoding: "json" | "form" | "multipart";
  csrf: "header" | "field" | "none";
  response: "json" | "redirect" | "blob";
  fields?: FieldDescriptor[];
  disabled?: boolean;
  reason?: string;
}

export interface RowDetailResponse {
  row: LedgerRow;
  source: Record<string, unknown> | null;
  decision: Record<string, unknown> | null;
  history: Array<Record<string, unknown>>;
  lineage: Array<Record<string, unknown>>;
  detail: Record<string, unknown>;
  expected_revision: string | number | null;
  edit_fields: FieldDescriptor[];
  read_only: boolean;
  actions: ActionDescriptor[];
}

export interface TransactionColumn {
  key: string;
  label: string;
}

export interface TransactionsResponse {
  view: "cards" | "ota" | "refunds" | "flights";
  columns: TransactionColumn[];
  rows: Array<Record<string, unknown>>;
  total_count: number;
  page: number;
  page_size: number;
  actions: ActionDescriptor[];
  status?: { code: string; message: string };
}

export interface AdminAuxResponse {
  title: string;
  columns?: TransactionColumn[];
  rows?: Array<Record<string, unknown>>;
  fields?: FieldDescriptor[];
  actions: ActionDescriptor[];
  status?: { code: string; message: string };
  data?: Record<string, unknown>;
}

export type AdminResponse = AdminAuxResponse;
export type AuxiliaryResponse = AdminAuxResponse;

/** Existing JSON API endpoints used by the Plush UI. These builders never
 * point at legacy HTML screens and always encode path identifiers. */
export const COST_API_ROUTES = {
  boardTsv: "/api/board/tsv",
  exportsXlsx: "/api/exports/xlsx",
  exportsJob: (jobId: string) => `/api/exports/${encodeURIComponent(jobId)}`,
  exportsDownload: (jobId: string) => `/api/exports/${encodeURIComponent(jobId)}/download`,
  manualExpense: "/api/expenses/manual",
  income: "/api/income",
  rowSave: (rowId: string) => `/api/rows/${encodeURIComponent(rowId)}/save`,
  rowLineage: (rowId: string) => `/api/rows/${encodeURIComponent(rowId)}/lineage`,
} as const;

const apiAction = (action: Omit<ActionDescriptor, "disabled" | "reason">): ActionDescriptor => action;

export const COST_API_ACTIONS = {
  boardTsv: apiAction({
    id: "board-tsv", label: "장부 TSV 다운로드", method: "GET", encoding: "form",
    csrf: "none", response: "json", href: COST_API_ROUTES.boardTsv,
  }),
  exportsXlsx: apiAction({
    id: "exports-xlsx", label: "XLSX 내보내기", method: "POST", encoding: "json",
    csrf: "header", response: "json", href: COST_API_ROUTES.exportsXlsx,
    fields: [
      { name: "tab_ids", label: "여행", type: "hidden", multiple: true, required: true },
      { name: "client_request_id", label: "요청 ID", type: "hidden", required: true },
    ],
  }),
  manualExpense: apiAction({
    id: "manual-expense", label: "수기 지출 추가", method: "POST", encoding: "json",
    csrf: "header", response: "json", href: COST_API_ROUTES.manualExpense,
    fields: [
      { name: "display_tab_id", label: "여행", type: "select", required: true },
      { name: "occurred_on", label: "날짜", type: "date", required: true },
      { name: "pay_method", label: "결제수단", type: "text", required: true },
      { name: "item", label: "항목", type: "text", required: true },
      { name: "description", label: "내용", type: "text", required: true },
      { name: "amount_krw", label: "금액(원)", type: "number", required: true },
      { name: "operator_note", label: "메모", type: "text" },
      { name: "client_request_id", label: "요청 ID", type: "hidden", required: true },
    ],
  }),
  income: apiAction({
    id: "direct-income", label: "수입 추가", method: "POST", encoding: "json",
    csrf: "header", response: "json", href: COST_API_ROUTES.income,
    fields: [
      { name: "display_tab_id", label: "여행", type: "select", required: true },
      { name: "occurred_on", label: "날짜", type: "date", required: true },
      { name: "amount_krw", label: "금액(원)", type: "number", required: true },
      { name: "income_kind", label: "수입 구분", type: "text", required: true },
      { name: "customer_id", label: "고객 ID", type: "text" },
      { name: "customer_name", label: "고객명", type: "text" },
      { name: "nickname", label: "별칭", type: "text" },
      { name: "operator_note", label: "메모", type: "text" },
      { name: "client_request_id", label: "요청 ID", type: "hidden", required: true },
    ],
  }),
} as const;

export function boardTsvAction(tabId: string): ActionDescriptor {
  return apiAction({
    id: "board-tsv", label: "장부 TSV 미리보기", method: "GET", encoding: "form",
    csrf: "none", response: "json", href: COST_API_ROUTES.boardTsv,
    fields: [
      { name: "tab", label: "여행", type: "hidden", value: tabId, required: true },
      { name: "q", label: "검색", type: "hidden" },
      { name: "kind", label: "구분", type: "hidden" },
    ],
  });
}

export function exportJobAction(jobId: string): ActionDescriptor {
  return apiAction({
    id: "export-job", label: "내보내기 상태", method: "GET", encoding: "form",
    csrf: "none", response: "json", href: COST_API_ROUTES.exportsJob(jobId),
  });
}

export function exportDownloadAction(jobId: string): ActionDescriptor {
  return apiAction({
    id: "export-download", label: "내보내기 다운로드", method: "GET", encoding: "form",
    csrf: "none", response: "blob", href: COST_API_ROUTES.exportsDownload(jobId),
  });
}

export function rowSaveAction(rowId: string, fields: FieldDescriptor[]): ActionDescriptor {
  return apiAction({
    id: "row-save", label: "거래 저장", method: "POST", encoding: "json",
    csrf: "header", response: "json", href: COST_API_ROUTES.rowSave(rowId), fields,
  });
}

export function rowLineageAction(rowId: string): ActionDescriptor {
  return apiAction({
    id: "row-lineage", label: "거래 이력", method: "GET", encoding: "form",
    csrf: "none", response: "json", href: COST_API_ROUTES.rowLineage(rowId),
  });
}
