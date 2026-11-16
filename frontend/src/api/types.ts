/** Authenticated JSON DTOs shared by the Plush UI feature pages. */

export type Role = "owner" | "viewer";

export interface TripSummary {
  id: string;
  title: string;
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
  status: string;
  updated_at?: string;
  detail?: string;
}

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
}

export interface ActionDescriptor {
  id: string;
  label: string;
  method: "GET" | "POST";
  href: string;
  fields?: FieldDescriptor[];
  disabled?: boolean;
  reason?: string;
}

export interface RowDetailResponse {
  row: LedgerRow;
  source: Record<string, unknown> | null;
  decision: Record<string, unknown> | null;
  history: Array<Record<string, unknown>>;
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
