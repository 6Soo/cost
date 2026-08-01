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
  activation_validation_sha256 TEXT,
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

CREATE TABLE IF NOT EXISTS direct_projection_validations (
  run_id TEXT PRIMARY KEY REFERENCES direct_projection_runs(run_id),
  status TEXT NOT NULL CHECK(status='passed'),
  package_set_sha256 TEXT NOT NULL CHECK(length(package_set_sha256)=64),
  authority_sha256 TEXT NOT NULL CHECK(length(authority_sha256)=64),
  input_manifest_sha256 TEXT NOT NULL CHECK(length(input_manifest_sha256)=64),
  candidate_semantic_sha256 TEXT NOT NULL CHECK(length(candidate_semantic_sha256)=64),
  candidate_master_sha256 TEXT NOT NULL CHECK(length(candidate_master_sha256)=64),
  identity_role_set_sha256 TEXT NOT NULL CHECK(length(identity_role_set_sha256)=64),
  amount_semantic_sha256 TEXT NOT NULL CHECK(length(amount_semantic_sha256)=64),
  validation_sha256 TEXT NOT NULL UNIQUE CHECK(length(validation_sha256)=64),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS direct_projection_validations_exact_run
BEFORE INSERT ON direct_projection_validations
WHEN NOT EXISTS (
  SELECT 1 FROM direct_projection_runs r WHERE r.run_id=NEW.run_id AND r.status='building'
    AND r.input_manifest_sha256=NEW.input_manifest_sha256
    AND r.candidate_semantic_sha256=NEW.candidate_semantic_sha256
)
BEGIN SELECT RAISE(ABORT, 'direct_projection_validation_run_mismatch'); END;

CREATE TRIGGER IF NOT EXISTS direct_projection_validations_no_update
BEFORE UPDATE ON direct_projection_validations
BEGIN SELECT RAISE(ABORT, 'direct_projection_validation_append_only'); END;

CREATE TRIGGER IF NOT EXISTS direct_projection_validations_no_delete
BEFORE DELETE ON direct_projection_validations
BEGIN SELECT RAISE(ABORT, 'direct_projection_validation_append_only'); END;

CREATE VIEW IF NOT EXISTS direct_candidate_payments AS
SELECT l.run_id, l.direct_payment_id, p.*
FROM direct_payment_projection_links l
JOIN payment_transactions p ON p.id = l.payment_id
JOIN direct_projection_runs r ON r.run_id = l.run_id
JOIN direct_projection_validations v ON v.run_id=r.run_id
WHERE r.status = 'passed' AND v.status='passed'
  AND r.activation_validation_sha256=v.validation_sha256
  AND v.input_manifest_sha256=r.input_manifest_sha256
  AND v.candidate_semantic_sha256=r.candidate_semantic_sha256;
