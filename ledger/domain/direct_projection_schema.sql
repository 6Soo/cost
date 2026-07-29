PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS direct_projection_runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('building','failed','passed')),
  schema_version TEXT NOT NULL,
  input_manifest_sha256 TEXT NOT NULL,
  candidate_semantic_sha256 TEXT,
  gate_report_sha256 TEXT,
  code_commit TEXT NOT NULL,
  code_bundle_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS direct_projection_inputs (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  source_kind TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL,
  lf_sha256 TEXT,
  byte_count INTEGER NOT NULL CHECK(byte_count > 0),
  key_set_sha256 TEXT NOT NULL,
  record_count INTEGER NOT NULL CHECK(record_count > 0),
  parser_version TEXT NOT NULL,
  PRIMARY KEY(run_id, source_kind, relative_path)
);

CREATE TABLE IF NOT EXISTS direct_payment_projection_links (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  direct_payment_id INTEGER NOT NULL REFERENCES direct_normalized_payments(id),
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  UNIQUE(run_id, direct_payment_id),
  UNIQUE(run_id, payment_id)
);

CREATE VIEW IF NOT EXISTS direct_candidate_payments AS
SELECT l.run_id, l.direct_payment_id, p.*
FROM direct_payment_projection_links l
JOIN payment_transactions p ON p.id = l.payment_id
JOIN direct_projection_runs r ON r.run_id = l.run_id
WHERE r.status = 'passed';
