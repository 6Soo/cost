export type Revision = number;

export interface PaseoProvider {
  id: string;
  label: string;
  available: boolean;
}

export interface PaseoModel {
  provider: string;
  id: string;
  label: string;
  selectable: boolean;
  reason?: string | null;
  thinking_options?: string[];
  default_thinking?: string | null;
  effective_thinking?: string | null;
}

export interface PaseoCatalog {
  connected: boolean;
  host_label?: string | null;
  checked_at?: string | null;
  providers: PaseoProvider[];
  models: PaseoModel[];
  default_provider?: string | null;
  default_model?: string | null;
  default_thinking?: string | null;
}

export interface WorkflowJob {
  job_id: string;
  image: string;
  status: string;
  code?: string | null;
}

export interface WorkflowCandidate {
  candidate_id: string;
  image: string;
  revision: Revision;
  selected: boolean;
  merchant: string | null;
  date: string | null;
  amount: string | number | null;
  currency: string | null;
  payment: string | null;
  trip_id: string | null;
  category: string | null;
  box: number[] | null;
  applied: boolean;
  ledger_id?: string | null;
  company_expense?: boolean | null;
}

export interface WorkflowBatch {
  batch_id: string;
  created_at: string;
  provider: string;
  model: string;
  thinking?: string | null;
  status: string;
  jobs: WorkflowJob[];
  candidates: WorkflowCandidate[];
}

export interface WorkflowList {
  batches: WorkflowBatch[];
}

export interface LegacyCandidate {
  identity: string;
  version?: string;
  image_sha?: string;
  merchant: string;
  date: string;
  total_jpy: number | null;
  total_original?: number | null;
  currency?: string;
  payment: string;
  amount_krw: number | null;
  trip_id?: string | null;
  payee?: string | null;
  category?: string | null;
  hold?: string | null;
  group_id?: string | null;
  card_transaction_id?: string | null;
}

export interface LegacyPdf {
  sha256: string;
  pages: string[];
}

export interface LegacyUpload {
  kind: 'image' | 'pdf';
  sha256: string;
  name: string;
}

export interface LegacyReceiptList {
  candidates: LegacyCandidate[];
  holds?: unknown[];
  images: string[];
  pdfs?: LegacyPdf[];
  uploads?: LegacyUpload[];
}

export interface ReceiptReviewDraft {
  expectedRevision: Revision;
  merchant: string;
  date: string;
  amount: string;
  currency: string;
  payment: string;
  trip_id: string;
  category: string;
  company_expense: boolean | null;
  selected: boolean;
  editing: boolean;
  dirty: boolean;
  saving: boolean;
  error?: string;
  revisionConflict?: boolean;
  pending?: {
    expected_revision: Revision;
    changes: Record<string, unknown>;
    selected: boolean;
  };
}
