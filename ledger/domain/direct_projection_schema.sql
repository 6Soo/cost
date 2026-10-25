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

-- A strict 2025 payment is a display terminal, not a three-axis accounting
-- decision.  Its membership is recorded separately so Gate 5 can count it
-- without allowing it into travel allocation, posting, or reversal logic.
CREATE TABLE IF NOT EXISTS direct_2025_payment_terminals (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  direct_event_key TEXT NOT NULL CHECK(length(trim(direct_event_key))>0),
  disposition TEXT NOT NULL CHECK(disposition='2025년 결제'),
  rule_id TEXT NOT NULL CHECK(rule_id='current-card-2025-payment-terminal-v1'),
  provenance_sha256 TEXT NOT NULL CHECK(length(provenance_sha256)=64),
  travel_eligible INTEGER NOT NULL CHECK(travel_eligible=0),
  accounting_final INTEGER NOT NULL CHECK(accounting_final=0),
  allocation_eligible INTEGER NOT NULL CHECK(allocation_eligible=0),
  posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
  reversal_inheritance_eligible INTEGER NOT NULL CHECK(reversal_inheritance_eligible=0),
  membership_sha256 TEXT NOT NULL CHECK(length(membership_sha256)=64),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,payment_id),
  UNIQUE(run_id,direct_event_key)
);

CREATE INDEX IF NOT EXISTS direct_2025_payment_terminals_by_payment
  ON direct_2025_payment_terminals(run_id,payment_id);

-- User-approved accounting disposition for 2025 card payments that do not
-- have a uniquely bound OTA/PG/service-mail proof of a 2026/2027 service
-- period.  This is accounting-final and allocation/posting-eligible, but it
-- is never a travel decision and carries no service period, trip, or booking.
CREATE TABLE IF NOT EXISTS direct_2025_cost_accounting (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  direct_event_key TEXT NOT NULL,
  rule_id TEXT NOT NULL CHECK(rule_id='payment-year-2025-cost-accounting-v1'),
  account TEXT NOT NULL CHECK(account='기타비용'),
  cost_type TEXT NOT NULL CHECK(cost_type='판관비'),
  allocation_target TEXT NOT NULL CHECK(allocation_target='2025년 비용'),
  target_type TEXT NOT NULL CHECK(target_type='other'),
  current_evidence_id TEXT NOT NULL,
  independent_evidence_id TEXT NOT NULL,
  membership_sha256 TEXT NOT NULL CHECK(length(membership_sha256)=64),
  provenance_sha256 TEXT NOT NULL CHECK(length(provenance_sha256)=64),
  travel_eligible INTEGER NOT NULL CHECK(travel_eligible=0),
  accounting_final INTEGER NOT NULL CHECK(accounting_final=1),
  allocation_eligible INTEGER NOT NULL CHECK(allocation_eligible=1),
  posting_eligible INTEGER NOT NULL CHECK(posting_eligible=1),
  reversal_inheritance_eligible INTEGER NOT NULL CHECK(reversal_inheritance_eligible=0),
  payload_json TEXT NOT NULL,
  accounting_period TEXT NOT NULL CHECK(accounting_period='2025'),
  posting_date_source TEXT NOT NULL CHECK(posting_date_source='payment.occurred_on'),
  idempotency_key TEXT NOT NULL CHECK(length(trim(idempotency_key))>0),
  PRIMARY KEY(run_id,payment_id),
  UNIQUE(run_id,direct_event_key),
  UNIQUE(run_id,idempotency_key)
);

CREATE INDEX IF NOT EXISTS direct_2025_cost_accounting_by_payment
  ON direct_2025_cost_accounting(run_id,payment_id);

CREATE TABLE IF NOT EXISTS direct_2025_cost_accounting_manifests (
  run_id TEXT PRIMARY KEY REFERENCES direct_projection_runs(run_id),
  rule_id TEXT NOT NULL CHECK(rule_id='payment-year-2025-cost-accounting-v1'),
  candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
  payment_count INTEGER NOT NULL CHECK(payment_count>=0),
  payment_set_sha256 TEXT NOT NULL CHECK(length(payment_set_sha256)=64),
  policy_source_sha256 TEXT NOT NULL CHECK(length(policy_source_sha256)=64),
  partition_sha256 TEXT NOT NULL CHECK(length(partition_sha256)=64),
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS direct_2025_payment_terminal_manifests (
  run_id TEXT PRIMARY KEY REFERENCES direct_projection_runs(run_id),
  rule_id TEXT NOT NULL CHECK(rule_id='current-card-2025-payment-terminal-v1'),
  candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
  cancellation_count INTEGER NOT NULL CHECK(cancellation_count>=0),
  mail_travel_count INTEGER NOT NULL CHECK(mail_travel_count>=0),
  residual_terminal_count INTEGER NOT NULL CHECK(residual_terminal_count>=0),
  excluded_count INTEGER NOT NULL CHECK(excluded_count>=0),
  candidate_set_sha256 TEXT NOT NULL CHECK(length(candidate_set_sha256)=64),
  cancellation_set_sha256 TEXT NOT NULL CHECK(length(cancellation_set_sha256)=64),
  mail_travel_set_sha256 TEXT NOT NULL CHECK(length(mail_travel_set_sha256)=64),
  residual_terminal_set_sha256 TEXT NOT NULL CHECK(length(residual_terminal_set_sha256)=64),
  excluded_set_sha256 TEXT NOT NULL CHECK(length(excluded_set_sha256)=64),
  partition_set_sha256 TEXT NOT NULL CHECK(length(partition_set_sha256)=64),
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS direct_payment_projection_links (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  direct_payment_id INTEGER NOT NULL REFERENCES direct_normalized_payments(id),
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  UNIQUE(run_id, direct_payment_id),
  UNIQUE(run_id, payment_id)
);

-- Gate 5 may consume only content-addressed evidence registered for this run.
-- Current-card rows are populated by the canonical card materializer.  A future
-- source-specific validator must register external evidence as verified before
-- any classification can be promoted.
CREATE TABLE IF NOT EXISTS direct_promotion_evidence (
  evidence_id TEXT NOT NULL,
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  evidence_kind TEXT NOT NULL CHECK(evidence_kind IN (
    'current_card','verified_booking','trusted_schedule',
    'sourced_adjustment','exact_cancellation','verified_product_document'
  )),
  authority_status TEXT NOT NULL CHECK(authority_status IN (
    'current_raw','verified_external'
  )),
  direct_event_key TEXT NOT NULL CHECK(length(trim(direct_event_key))>0),
  source_kind TEXT NOT NULL CHECK(length(trim(source_kind))>0),
  source_key TEXT NOT NULL CHECK(length(trim(source_key))>0),
  source_sha256 TEXT NOT NULL CHECK(
    length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  fact_sha256 TEXT NOT NULL CHECK(
    length(fact_sha256)=64 AND fact_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  PRIMARY KEY(run_id, evidence_id),
  FOREIGN KEY(source_kind,source_key,source_sha256)
    REFERENCES direct_source_records(source_kind,source_key,source_sha256),
  CHECK(
    (evidence_kind='current_card' AND authority_status='current_raw'
      AND evidence_id='current-card:' || fact_sha256)
    OR
    (evidence_kind<>'current_card' AND authority_status='verified_external'
      AND evidence_id=evidence_kind || ':' || fact_sha256)
  ),
  CHECK(
    authority_status='current_raw'
    OR (
      lower(source_kind) NOT LIKE '%manual%'
      AND lower(source_kind) NOT LIKE '%legacy%'
      AND lower(source_kind) NOT LIKE '%historical%'
      AND lower(source_kind) NOT LIKE '%replay%'
      AND lower(source_kind) NOT LIKE '%lineage%'
      AND lower(source_kind) NOT LIKE '%proposal%'
      AND lower(source_kind) NOT LIKE '%tolerance%'
    )
  )
);

-- Current-card settlement validation joins the complete event universe by
-- run and direct-event identity.  Without this index SQLite rescans all 5,328
-- evidence rows once per payment.
CREATE INDEX IF NOT EXISTS direct_promotion_evidence_current_event
ON direct_promotion_evidence(
  run_id,evidence_kind,authority_status,direct_event_key,
  source_kind,source_key,source_sha256
);

CREATE TABLE IF NOT EXISTS direct_axis_derivations (
  derivation_id TEXT NOT NULL,
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  dimension TEXT NOT NULL CHECK(dimension IN (
    'account','cost_type','allocation_target'
  )),
  value TEXT NOT NULL CHECK(length(trim(value))>0),
  rule_id TEXT NOT NULL CHECK(length(trim(rule_id))>0),
  current_evidence_id TEXT NOT NULL,
  independent_evidence_id TEXT NOT NULL,
  derivation_status TEXT NOT NULL CHECK(derivation_status='pass'),
  conflict_count INTEGER NOT NULL CHECK(conflict_count=0),
  PRIMARY KEY(run_id, derivation_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id),
  FOREIGN KEY(run_id,independent_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id),
  UNIQUE(run_id, payment_id, dimension),
  UNIQUE(run_id, payment_id, current_evidence_id, independent_evidence_id, rule_id),
  CHECK(current_evidence_id<>independent_evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_decision_promotion_bindings (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  decision_id INTEGER NOT NULL REFERENCES classification_decisions(id),
  derivation_id TEXT NOT NULL,
  PRIMARY KEY(run_id, decision_id),
  UNIQUE(run_id, derivation_id),
  FOREIGN KEY(run_id,derivation_id)
    REFERENCES direct_axis_derivations(run_id,derivation_id)
);

-- Every OTA reservation fact is accounted for in this queue. Only a
-- singleton exact card match leaves the queue and becomes evidence.
CREATE TABLE IF NOT EXISTS direct_ota_reservation_queue (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  source_key TEXT NOT NULL,
  fact_sha256 TEXT NOT NULL CHECK(
    length(fact_sha256)=64 AND fact_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  reason_code TEXT NOT NULL CHECK(length(trim(reason_code))>0),
  candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
  detail_sha256 TEXT NOT NULL CHECK(
    length(detail_sha256)=64 AND detail_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  PRIMARY KEY(run_id,source_key)
);

-- Authenticated Trip lodging facts are materialized before they are matched to
-- current cards.  The fact payload contains external-source data only.
CREATE TABLE IF NOT EXISTS direct_verified_lodging_facts (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  fact_id TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK(source_kind='ota_lodging_fact'),
  source_key TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(
    length(source_sha256)=64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  fact_sha256 TEXT NOT NULL CHECK(
    length(fact_sha256)=64 AND fact_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  provider TEXT NOT NULL CHECK(provider='trip'),
  booking_ref TEXT NOT NULL CHECK(
    length(booking_ref)=16 AND booking_ref NOT GLOB '*[^0-9]*'
  ),
  property_name TEXT NOT NULL CHECK(length(trim(property_name))>0),
  check_in TEXT NOT NULL,
  check_out TEXT NOT NULL,
  seoul_sent_on TEXT NOT NULL,
  paid_total_krw INTEGER NOT NULL CHECK(paid_total_krw>0),
  target_code TEXT NOT NULL CHECK(length(trim(target_code))>0),
  account TEXT NOT NULL CHECK(account='숙박비'),
  cost_type TEXT NOT NULL CHECK(cost_type='여행원가'),
  lifecycle_status TEXT NOT NULL CHECK(lifecycle_status='active'),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,fact_id),
  UNIQUE(run_id,provider,booking_ref),
  FOREIGN KEY(source_kind,source_key,source_sha256)
    REFERENCES direct_source_records(source_kind,source_key,source_sha256)
);

-- A set authority makes no claim about an individual card-to-booking pair.
-- It asserts only that every possible pairing has the same three axes.
CREATE TABLE IF NOT EXISTS direct_lodging_authorities (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  authority_id TEXT NOT NULL,
  authority_kind TEXT NOT NULL CHECK(authority_kind IN (
    'unique','axis_invariant_set'
  )),
  event_set_sha256 TEXT NOT NULL CHECK(length(event_set_sha256)=64),
  fact_set_sha256 TEXT NOT NULL CHECK(length(fact_set_sha256)=64),
  amount_multiset_sha256 TEXT NOT NULL CHECK(length(amount_multiset_sha256)=64),
  authority_sha256 TEXT NOT NULL CHECK(length(authority_sha256)=64),
  event_count INTEGER NOT NULL CHECK(event_count>0),
  fact_count INTEGER NOT NULL CHECK(fact_count>0 AND fact_count=event_count),
  property_name TEXT NOT NULL CHECK(length(trim(property_name))>0),
  check_in TEXT NOT NULL,
  check_out TEXT NOT NULL,
  account TEXT NOT NULL CHECK(account='숙박비'),
  cost_type TEXT NOT NULL CHECK(cost_type='여행원가'),
  allocation_target TEXT NOT NULL CHECK(length(trim(allocation_target))>0),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,authority_id)
);

CREATE TABLE IF NOT EXISTS direct_lodging_authority_events (
  run_id TEXT NOT NULL,
  authority_id TEXT NOT NULL,
  direct_event_key TEXT NOT NULL,
  current_evidence_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  PRIMARY KEY(run_id,authority_id,direct_event_key),
  UNIQUE(run_id,direct_event_key),
  UNIQUE(run_id,payment_id),
  FOREIGN KEY(run_id,authority_id)
    REFERENCES direct_lodging_authorities(run_id,authority_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_lodging_authority_facts (
  run_id TEXT NOT NULL,
  authority_id TEXT NOT NULL,
  fact_id TEXT NOT NULL,
  PRIMARY KEY(run_id,authority_id,fact_id),
  UNIQUE(run_id,fact_id),
  FOREIGN KEY(run_id,authority_id)
    REFERENCES direct_lodging_authorities(run_id,authority_id),
  FOREIGN KEY(run_id,fact_id)
    REFERENCES direct_verified_lodging_facts(run_id,fact_id)
);

CREATE TABLE IF NOT EXISTS direct_lodging_axis_derivations (
  derivation_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  authority_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  direct_event_key TEXT NOT NULL,
  dimension TEXT NOT NULL CHECK(dimension IN (
    'account','cost_type','allocation_target'
  )),
  value TEXT NOT NULL CHECK(length(trim(value))>0),
  rule_id TEXT NOT NULL CHECK(length(trim(rule_id))>0),
  current_evidence_id TEXT NOT NULL,
  derivation_status TEXT NOT NULL CHECK(derivation_status='pass'),
  conflict_count INTEGER NOT NULL CHECK(conflict_count=0),
  PRIMARY KEY(run_id,derivation_id),
  UNIQUE(run_id,payment_id,dimension),
  FOREIGN KEY(run_id,authority_id)
    REFERENCES direct_lodging_authorities(run_id,authority_id),
  FOREIGN KEY(run_id,authority_id,direct_event_key)
    REFERENCES direct_lodging_authority_events(run_id,authority_id,direct_event_key),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_lodging_decision_bindings (
  run_id TEXT NOT NULL,
  decision_id INTEGER NOT NULL REFERENCES classification_decisions(id),
  derivation_id TEXT NOT NULL,
  PRIMARY KEY(run_id,decision_id),
  UNIQUE(run_id,derivation_id),
  FOREIGN KEY(run_id,derivation_id)
    REFERENCES direct_lodging_axis_derivations(run_id,derivation_id)
);

CREATE TABLE IF NOT EXISTS direct_lodging_cohort_manifests (
  run_id TEXT PRIMARY KEY REFERENCES direct_projection_runs(run_id),
  state_sha256 TEXT NOT NULL CHECK(length(state_sha256)=64),
  manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
  run_sha256 TEXT NOT NULL UNIQUE CHECK(length(run_sha256)=64),
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS direct_lodging_withheld (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  item_kind TEXT NOT NULL CHECK(item_kind IN (
    'external_fact','current_event','component'
  )),
  item_key TEXT NOT NULL CHECK(length(trim(item_key))>0),
  reason_code TEXT NOT NULL CHECK(length(trim(reason_code))>0),
  detail_sha256 TEXT NOT NULL CHECK(length(detail_sha256)=64),
  PRIMARY KEY(run_id,item_kind,item_key,reason_code)
);

-- Current-card cancellation settlements are regenerated from the complete
-- current event universe.  Only closed, exact-KRW-zero components may become
-- terminal; partial refunds, reused approvals, and open sets remain withheld.
CREATE TABLE IF NOT EXISTS direct_cancellation_settlement_authorities (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  authority_id TEXT NOT NULL,
  authority_kind TEXT NOT NULL CHECK(authority_kind IN (
    'approval_exact','kbo_exact_set'
  )),
  relation_key_sha256 TEXT NOT NULL CHECK(length(relation_key_sha256)=64),
  member_set_sha256 TEXT NOT NULL CHECK(length(member_set_sha256)=64),
  source_set_sha256 TEXT NOT NULL CHECK(length(source_set_sha256)=64),
  authority_sha256 TEXT NOT NULL CHECK(length(authority_sha256)=64),
  member_count INTEGER NOT NULL CHECK(member_count>=2),
  purchase_count INTEGER NOT NULL CHECK(purchase_count>0),
  reversal_count INTEGER NOT NULL CHECK(
    reversal_count=purchase_count AND member_count=purchase_count+reversal_count
  ),
  net_krw INTEGER NOT NULL CHECK(net_krw=0),
  account TEXT NOT NULL CHECK(account='비용제외'),
  cost_type TEXT NOT NULL CHECK(cost_type='비용제외'),
  allocation_target TEXT NOT NULL CHECK(allocation_target='취소환불'),
  individual_pair_asserted INTEGER NOT NULL CHECK(
    individual_pair_asserted IN (0,1)
  ),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,authority_id)
);

CREATE TABLE IF NOT EXISTS direct_cancellation_settlement_members (
  run_id TEXT NOT NULL,
  authority_id TEXT NOT NULL,
  direct_event_key TEXT NOT NULL,
  current_evidence_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  source_key TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  transaction_type TEXT NOT NULL CHECK(transaction_type IN (
    'purchase','cancellation','refund'
  )),
  member_role TEXT NOT NULL CHECK(member_role IN ('purchase','reversal')),
  amount_krw INTEGER NOT NULL,
  occurred_on TEXT NOT NULL,
  PRIMARY KEY(run_id,authority_id,direct_event_key),
  UNIQUE(run_id,direct_event_key),
  UNIQUE(run_id,payment_id),
  FOREIGN KEY(run_id,authority_id)
    REFERENCES direct_cancellation_settlement_authorities(run_id,authority_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_cancellation_settlement_derivations (
  derivation_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  authority_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  direct_event_key TEXT NOT NULL,
  dimension TEXT NOT NULL CHECK(dimension IN (
    'account','cost_type','allocation_target'
  )),
  value TEXT NOT NULL,
  rule_id TEXT NOT NULL CHECK(length(trim(rule_id))>0),
  current_evidence_id TEXT NOT NULL,
  derivation_status TEXT NOT NULL CHECK(derivation_status='pass'),
  conflict_count INTEGER NOT NULL CHECK(conflict_count=0),
  PRIMARY KEY(run_id,derivation_id),
  UNIQUE(run_id,payment_id,dimension),
  FOREIGN KEY(run_id,authority_id)
    REFERENCES direct_cancellation_settlement_authorities(run_id,authority_id),
  FOREIGN KEY(run_id,authority_id,direct_event_key)
    REFERENCES direct_cancellation_settlement_members(
      run_id,authority_id,direct_event_key
    ),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id),
  CHECK(
    (dimension='account' AND value='비용제외')
    OR (dimension='cost_type' AND value='비용제외')
    OR (dimension='allocation_target' AND value='취소환불')
  )
);

CREATE TABLE IF NOT EXISTS direct_cancellation_settlement_decision_bindings (
  run_id TEXT NOT NULL,
  decision_id INTEGER NOT NULL REFERENCES classification_decisions(id),
  derivation_id TEXT NOT NULL,
  PRIMARY KEY(run_id,decision_id),
  UNIQUE(run_id,derivation_id),
  FOREIGN KEY(run_id,derivation_id)
    REFERENCES direct_cancellation_settlement_derivations(run_id,derivation_id)
);

CREATE TABLE IF NOT EXISTS direct_cancellation_settlement_withheld (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  direct_event_key TEXT NOT NULL,
  current_evidence_id TEXT NOT NULL,
  reason_code TEXT NOT NULL CHECK(length(trim(reason_code))>0),
  detail_sha256 TEXT NOT NULL CHECK(length(detail_sha256)=64),
  PRIMARY KEY(run_id,direct_event_key),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_cancellation_settlement_manifests (
  run_id TEXT PRIMARY KEY REFERENCES direct_projection_runs(run_id),
  state_sha256 TEXT NOT NULL CHECK(length(state_sha256)=64),
  manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
  run_sha256 TEXT NOT NULL UNIQUE CHECK(length(run_sha256)=64),
  payload_json TEXT NOT NULL
);

-- The historical classification snapshot is training material, never payment
-- evidence.  A prediction is promotable only after four leave-one-out peer
-- models agree and the held-out historical label is used solely to score the
-- model.  Current positive purchases define candidacy; target historical
-- fields cannot add or remove a prediction.  Current-card evidence remains the
-- only transaction fact bound here.
CREATE TABLE IF NOT EXISTS direct_validated_classifier_models (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  model_id TEXT NOT NULL,
  model_contract TEXT NOT NULL,
  model_sha256 TEXT NOT NULL CHECK(length(model_sha256)=64),
  run_state_sha256 TEXT NOT NULL CHECK(length(run_state_sha256)=64),
  training_source_sha256 TEXT NOT NULL CHECK(length(training_source_sha256)=64),
  candidate_set_sha256 TEXT NOT NULL CHECK(length(candidate_set_sha256)=64),
  prediction_set_sha256 TEXT NOT NULL CHECK(length(prediction_set_sha256)=64),
  validation_set_sha256 TEXT NOT NULL CHECK(length(validation_set_sha256)=64),
  training_row_count INTEGER NOT NULL CHECK(training_row_count>0),
  candidate_count INTEGER NOT NULL CHECK(candidate_count>0),
  promoted_count INTEGER NOT NULL CHECK(promoted_count>0),
  validation_count INTEGER NOT NULL CHECK(
    validation_count>0 AND validation_count<=promoted_count
  ),
  validation_error_count INTEGER NOT NULL CHECK(validation_error_count=0),
  minimum_peer_count INTEGER NOT NULL CHECK(minimum_peer_count>=3),
  training_role TEXT NOT NULL CHECK(
    training_role='learning_only_not_transaction_evidence'
  ),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,model_id),
  UNIQUE(run_id)
);

CREATE TABLE IF NOT EXISTS direct_validated_classifier_predictions (
  run_id TEXT NOT NULL,
  prediction_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  direct_event_key TEXT NOT NULL CHECK(length(trim(direct_event_key))>0),
  current_evidence_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  feature_sha256 TEXT NOT NULL CHECK(length(feature_sha256)=64),
  loo_model_sha256 TEXT NOT NULL CHECK(length(loo_model_sha256)=64),
  held_out_association_sha256 TEXT NOT NULL CHECK(
    length(held_out_association_sha256)=64
  ),
  account TEXT NOT NULL CHECK(length(trim(account))>0),
  cost_type TEXT NOT NULL CHECK(length(trim(cost_type))>0),
  allocation_target TEXT NOT NULL CHECK(length(trim(allocation_target))>0),
  account_a_support INTEGER NOT NULL CHECK(account_a_support>=3),
  account_b_support INTEGER NOT NULL CHECK(account_b_support>=3),
  target_q_support INTEGER NOT NULL CHECK(target_q_support>=3),
  target_r_support INTEGER NOT NULL CHECK(target_r_support>=3),
  account_a_peer_set_sha256 TEXT NOT NULL CHECK(length(account_a_peer_set_sha256)=64),
  account_b_peer_set_sha256 TEXT NOT NULL CHECK(length(account_b_peer_set_sha256)=64),
  target_q_peer_set_sha256 TEXT NOT NULL CHECK(length(target_q_peer_set_sha256)=64),
  target_r_peer_set_sha256 TEXT NOT NULL CHECK(length(target_r_peer_set_sha256)=64),
  schedule_status TEXT NOT NULL CHECK(schedule_status IN (
    'unique_agreement','no_match','ambiguous_match'
  )),
  conflict_count INTEGER NOT NULL CHECK(conflict_count=0),
  prediction_sha256 TEXT NOT NULL CHECK(length(prediction_sha256)=64),
  peer_payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,prediction_id),
  UNIQUE(run_id,direct_event_key),
  UNIQUE(run_id,payment_id),
  FOREIGN KEY(run_id,model_id)
    REFERENCES direct_validated_classifier_models(run_id,model_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_validated_classifier_axis_derivations (
  derivation_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prediction_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  direct_event_key TEXT NOT NULL,
  dimension TEXT NOT NULL CHECK(dimension IN (
    'account','cost_type','allocation_target'
  )),
  value TEXT NOT NULL CHECK(length(trim(value))>0),
  rule_id TEXT NOT NULL CHECK(length(trim(rule_id))>0),
  current_evidence_id TEXT NOT NULL,
  derivation_status TEXT NOT NULL CHECK(derivation_status='pass'),
  conflict_count INTEGER NOT NULL CHECK(conflict_count=0),
  PRIMARY KEY(run_id,derivation_id),
  UNIQUE(run_id,payment_id,dimension),
  FOREIGN KEY(run_id,model_id)
    REFERENCES direct_validated_classifier_models(run_id,model_id),
  FOREIGN KEY(run_id,prediction_id)
    REFERENCES direct_validated_classifier_predictions(run_id,prediction_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_validated_classifier_decision_bindings (
  run_id TEXT NOT NULL,
  decision_id INTEGER NOT NULL REFERENCES classification_decisions(id),
  derivation_id TEXT NOT NULL,
  PRIMARY KEY(run_id,decision_id),
  UNIQUE(run_id,derivation_id),
  FOREIGN KEY(run_id,derivation_id)
    REFERENCES direct_validated_classifier_axis_derivations(run_id,derivation_id)
);

CREATE TABLE IF NOT EXISTS direct_validated_classifier_withheld (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  direct_event_key TEXT NOT NULL,
  current_evidence_id TEXT NOT NULL,
  reason_code TEXT NOT NULL CHECK(length(trim(reason_code))>0),
  detail_sha256 TEXT NOT NULL CHECK(length(detail_sha256)=64),
  PRIMARY KEY(run_id,direct_event_key,reason_code),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

-- The legacy validated classifier is intentionally narrow.  This second
-- contract carries the old Q2 operating defaults into the all-period card
-- scope: domestic ordinary spend becomes overhead, overseas use is travel
-- cost, and a service period that is not known becomes the explicit
-- ``여행_미배정`` target.  Training rows remain learning-only; only current
-- card evidence is attached to these predictions.
CREATE TABLE IF NOT EXISTS direct_high_coverage_classifier_models (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  model_id TEXT NOT NULL,
  model_contract TEXT NOT NULL,
  model_sha256 TEXT NOT NULL CHECK(length(model_sha256)=64),
  run_state_sha256 TEXT NOT NULL CHECK(length(run_state_sha256)=64),
  training_source_sha256 TEXT NOT NULL CHECK(length(training_source_sha256)=64),
  candidate_set_sha256 TEXT NOT NULL CHECK(length(candidate_set_sha256)=64),
  prediction_set_sha256 TEXT NOT NULL CHECK(length(prediction_set_sha256)=64),
  training_row_count INTEGER NOT NULL CHECK(training_row_count>0),
  candidate_count INTEGER NOT NULL CHECK(candidate_count>0),
  promoted_count INTEGER NOT NULL CHECK(promoted_count>0),
  validation_count INTEGER NOT NULL CHECK(validation_count>0),
  validation_error_count INTEGER NOT NULL CHECK(validation_error_count=0),
  training_role TEXT NOT NULL CHECK(
    training_role='learning_only_not_transaction_evidence'
  ),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,model_id),
  UNIQUE(run_id)
);

CREATE TABLE IF NOT EXISTS direct_high_coverage_classifier_predictions (
  run_id TEXT NOT NULL,
  prediction_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  direct_event_key TEXT NOT NULL CHECK(length(trim(direct_event_key))>0),
  current_evidence_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  feature_sha256 TEXT NOT NULL CHECK(length(feature_sha256)=64),
  account TEXT NOT NULL CHECK(length(trim(account))>0),
  cost_type TEXT NOT NULL CHECK(length(trim(cost_type))>0),
  allocation_target TEXT NOT NULL CHECK(length(trim(allocation_target))>0),
  rule_path TEXT NOT NULL CHECK(length(trim(rule_path))>0),
  confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),
  confidence_label TEXT NOT NULL CHECK(length(trim(confidence_label))>0),
  schedule_status TEXT NOT NULL CHECK(schedule_status IN (
    'unique_match','ambiguous_match','no_match','not_applicable'
  )),
  conflict_count INTEGER NOT NULL CHECK(conflict_count=0),
  prediction_sha256 TEXT NOT NULL CHECK(length(prediction_sha256)=64),
  axis_evidence_json TEXT NOT NULL,
  rationale TEXT NOT NULL CHECK(length(trim(rationale))>0),
  PRIMARY KEY(run_id,prediction_id),
  UNIQUE(run_id,direct_event_key),
  UNIQUE(run_id,payment_id),
  FOREIGN KEY(run_id,model_id)
    REFERENCES direct_high_coverage_classifier_models(run_id,model_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

-- A reversal may inherit a needs_review target from one exact current-card
-- relation.  Keep that inheritance as a separate, content-addressed link so
-- the original provisional registry's member set is never silently changed.
CREATE TABLE IF NOT EXISTS direct_high_coverage_reversal_inheritance (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  reversal_payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  reversal_direct_event_key TEXT NOT NULL,
  original_payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  original_prediction_id TEXT NOT NULL,
  relation_id INTEGER NOT NULL REFERENCES transaction_relations(id),
  relation_match_method TEXT NOT NULL,
  relation_reference_value TEXT,
  original_target TEXT NOT NULL,
  original_prediction_sha256 TEXT NOT NULL CHECK(length(original_prediction_sha256)=64),
  link_sha256 TEXT NOT NULL CHECK(length(link_sha256)=64),
  inheritance_status TEXT NOT NULL CHECK(inheritance_status='provisional'),
  PRIMARY KEY(run_id,reversal_payment_id),
  UNIQUE(run_id,reversal_direct_event_key),
  FOREIGN KEY(run_id,original_prediction_id)
    REFERENCES direct_high_coverage_classifier_predictions(run_id,prediction_id)
);

CREATE TABLE IF NOT EXISTS direct_high_coverage_classifier_axis_derivations (
  derivation_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prediction_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  direct_event_key TEXT NOT NULL,
  dimension TEXT NOT NULL CHECK(dimension IN (
    'account','cost_type','allocation_target'
  )),
  value TEXT NOT NULL CHECK(length(trim(value))>0),
  rule_id TEXT NOT NULL CHECK(length(trim(rule_id))>0),
  current_evidence_id TEXT NOT NULL,
  derivation_status TEXT NOT NULL CHECK(derivation_status='pass'),
  conflict_count INTEGER NOT NULL CHECK(conflict_count=0),
  PRIMARY KEY(run_id,derivation_id),
  UNIQUE(run_id,payment_id,dimension),
  FOREIGN KEY(run_id,model_id)
    REFERENCES direct_high_coverage_classifier_models(run_id,model_id),
  FOREIGN KEY(run_id,prediction_id)
    REFERENCES direct_high_coverage_classifier_predictions(run_id,prediction_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE TABLE IF NOT EXISTS direct_high_coverage_classifier_decision_bindings (
  run_id TEXT NOT NULL,
  decision_id INTEGER NOT NULL REFERENCES classification_decisions(id),
  derivation_id TEXT NOT NULL,
  PRIMARY KEY(run_id,decision_id),
  UNIQUE(run_id,derivation_id),
  FOREIGN KEY(run_id,derivation_id)
    REFERENCES direct_high_coverage_classifier_axis_derivations(
      run_id,derivation_id
    )
);

CREATE TABLE IF NOT EXISTS direct_high_coverage_classifier_withheld (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  direct_event_key TEXT NOT NULL,
  current_evidence_id TEXT NOT NULL,
  reason_code TEXT NOT NULL CHECK(length(trim(reason_code))>0),
  detail_sha256 TEXT NOT NULL CHECK(length(detail_sha256)=64),
  PRIMARY KEY(run_id,direct_event_key,reason_code),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

-- A current-card trip cluster is a review-only target registry.  It is kept
-- outside the canonical trip schedule and allocation_targets so the normal
-- allocator cannot mistake an inferred target for an approved trip.
CREATE TABLE IF NOT EXISTS direct_high_coverage_trip_registries (
  run_id TEXT NOT NULL REFERENCES direct_projection_runs(run_id),
  registry_id TEXT NOT NULL,
  registry_version TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  registry_sha256 TEXT NOT NULL CHECK(length(registry_sha256)=64),
  target_code TEXT NOT NULL CHECK(length(trim(target_code))>0),
  target_kind TEXT NOT NULL CHECK(target_kind IN (
    'canonical_schedule','context_schedule','new_registry_target',
    'activity_placeholder','reservation_placeholder','inferred_external_target'
  )),
  source_system TEXT NOT NULL CHECK(length(trim(source_system))>0),
  card_identity_sha256 TEXT NOT NULL CHECK(length(card_identity_sha256)=64),
  country TEXT NOT NULL CHECK(length(trim(country))>0),
  region TEXT NOT NULL CHECK(length(trim(region))>0),
  starts_on TEXT NOT NULL,
  ends_on TEXT NOT NULL,
  event_set_sha256 TEXT NOT NULL CHECK(length(event_set_sha256)=64),
  fact_set_sha256 TEXT NOT NULL CHECK(length(fact_set_sha256)=64),
  registry_status TEXT NOT NULL CHECK(registry_status='provisional'),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,registry_id),
  UNIQUE(run_id,registry_id,target_code)
);

CREATE TABLE IF NOT EXISTS direct_high_coverage_trip_registry_members (
  run_id TEXT NOT NULL,
  registry_id TEXT NOT NULL,
  payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
  direct_event_key TEXT NOT NULL,
  current_evidence_id TEXT NOT NULL,
  current_fact_sha256 TEXT NOT NULL CHECK(length(current_fact_sha256)=64),
  PRIMARY KEY(run_id,registry_id,payment_id),
  UNIQUE(run_id,payment_id),
  FOREIGN KEY(run_id,registry_id)
    REFERENCES direct_high_coverage_trip_registries(run_id,registry_id),
  FOREIGN KEY(run_id,current_evidence_id)
    REFERENCES direct_promotion_evidence(run_id,evidence_id)
);

CREATE VIEW IF NOT EXISTS current_independently_promoted_decisions AS
SELECT b.run_id,d.id,d.target_type,d.target_id,d.dimension,d.value,
       d.confidence,d.confidence_label,d.decision_status,d.rule_id,d.rationale,
       x.derivation_id,x.current_evidence_id,x.independent_evidence_id
FROM direct_decision_promotion_bindings b
JOIN current_classification_decisions d ON d.id=b.decision_id
JOIN direct_axis_derivations x
  ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
JOIN direct_promotion_evidence current_e
  ON current_e.run_id=x.run_id AND current_e.evidence_id=x.current_evidence_id
JOIN direct_promotion_evidence independent_e
  ON independent_e.run_id=x.run_id
 AND independent_e.evidence_id=x.independent_evidence_id
JOIN direct_payment_projection_links l
  ON l.run_id=b.run_id AND l.payment_id=d.target_id
JOIN direct_normalized_payments payment ON payment.id=l.direct_payment_id
JOIN direct_source_records current_source
  ON current_source.id=payment.source_record_id
 AND current_source.source_kind=current_e.source_kind
 AND current_source.source_key=current_e.source_key
 AND current_source.source_sha256=current_e.source_sha256
JOIN direct_source_records independent_source
  ON independent_source.source_kind=independent_e.source_kind
 AND independent_source.source_key=independent_e.source_key
 AND independent_source.source_sha256=independent_e.source_sha256
WHERE d.target_type='payment' AND d.decision_status='confirmed'
  AND d.dimension IN ('account','cost_type','allocation_target')
  AND x.run_id=b.run_id AND x.payment_id=d.target_id
  AND x.dimension=d.dimension AND x.value=d.value AND x.rule_id=d.rule_id
  AND x.derivation_status='pass' AND x.conflict_count=0
  AND current_e.run_id=b.run_id AND current_e.evidence_kind='current_card'
  AND current_e.authority_status='current_raw'
  AND current_e.direct_event_key=payment.card_event_id || '#' || payment.event_role
  AND independent_e.run_id=b.run_id
  AND independent_e.evidence_kind<>'current_card'
  AND independent_e.authority_status='verified_external'
  AND independent_e.direct_event_key=current_e.direct_event_key
  AND lower(independent_e.source_kind) NOT LIKE '%manual%'
  AND lower(independent_e.source_kind) NOT LIKE '%legacy%'
  AND lower(independent_e.source_kind) NOT LIKE '%historical%'
  AND lower(independent_e.source_kind) NOT LIKE '%replay%'
  AND lower(independent_e.source_kind) NOT LIKE '%lineage%'
  AND lower(independent_e.source_kind) NOT LIKE '%proposal%'
  AND lower(independent_e.source_kind) NOT LIKE '%tolerance%'
UNION ALL
SELECT b.run_id,d.id,d.target_type,d.target_id,d.dimension,d.value,
       d.confidence,d.confidence_label,d.decision_status,d.rule_id,d.rationale,
       x.derivation_id,x.current_evidence_id,x.authority_id
FROM direct_lodging_decision_bindings b
JOIN current_classification_decisions d ON d.id=b.decision_id
JOIN direct_lodging_axis_derivations x
  ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
JOIN direct_lodging_authorities a
  ON a.run_id=x.run_id AND a.authority_id=x.authority_id
JOIN direct_lodging_authority_events ae
  ON ae.run_id=x.run_id AND ae.authority_id=x.authority_id
 AND ae.payment_id=x.payment_id AND ae.direct_event_key=x.direct_event_key
 AND ae.current_evidence_id=x.current_evidence_id
JOIN direct_promotion_evidence current_e
  ON current_e.run_id=x.run_id AND current_e.evidence_id=x.current_evidence_id
JOIN direct_payment_projection_links l
  ON l.run_id=b.run_id AND l.payment_id=d.target_id
JOIN direct_normalized_payments payment ON payment.id=l.direct_payment_id
WHERE d.target_type='payment' AND d.decision_status='confirmed'
  AND d.dimension IN ('account','cost_type','allocation_target')
  AND x.payment_id=d.target_id AND x.dimension=d.dimension
  AND x.value=d.value AND x.rule_id=d.rule_id
  AND x.derivation_status='pass' AND x.conflict_count=0
  AND current_e.evidence_kind='current_card'
  AND current_e.authority_status='current_raw'
  AND current_e.direct_event_key=payment.card_event_id || '#' || payment.event_role
  AND a.event_count=a.fact_count
UNION ALL
SELECT b.run_id,d.id,d.target_type,d.target_id,d.dimension,d.value,
       d.confidence,d.confidence_label,d.decision_status,d.rule_id,d.rationale,
       x.derivation_id,x.current_evidence_id,x.authority_id
FROM direct_cancellation_settlement_decision_bindings b
JOIN current_classification_decisions d ON d.id=b.decision_id
JOIN direct_cancellation_settlement_derivations x
  ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
JOIN direct_cancellation_settlement_authorities a
  ON a.run_id=x.run_id AND a.authority_id=x.authority_id
JOIN direct_cancellation_settlement_members m
  ON m.run_id=x.run_id AND m.authority_id=x.authority_id
 AND m.payment_id=x.payment_id AND m.direct_event_key=x.direct_event_key
 AND m.current_evidence_id=x.current_evidence_id
JOIN direct_promotion_evidence current_e
  ON current_e.run_id=x.run_id AND current_e.evidence_id=x.current_evidence_id
JOIN direct_payment_projection_links l
  ON l.run_id=b.run_id AND l.payment_id=d.target_id
JOIN direct_normalized_payments payment ON payment.id=l.direct_payment_id
WHERE d.target_type='payment' AND d.decision_status='confirmed'
  AND d.dimension IN ('account','cost_type','allocation_target')
  AND x.payment_id=d.target_id AND x.dimension=d.dimension
  AND x.value=d.value AND x.rule_id=d.rule_id
  AND x.derivation_status='pass' AND x.conflict_count=0
  AND current_e.evidence_kind='current_card'
  AND current_e.authority_status='current_raw'
  AND current_e.direct_event_key=payment.card_event_id || '#' || payment.event_role
  AND a.member_count=a.purchase_count+a.reversal_count
  AND a.purchase_count=a.reversal_count AND a.net_krw=0
  AND a.account='비용제외' AND a.cost_type='비용제외'
  AND a.allocation_target='취소환불'
UNION ALL
SELECT b.run_id,d.id,d.target_type,d.target_id,d.dimension,d.value,
       d.confidence,d.confidence_label,d.decision_status,d.rule_id,d.rationale,
       x.derivation_id,x.current_evidence_id,x.model_id
FROM direct_validated_classifier_decision_bindings b
JOIN current_classification_decisions d ON d.id=b.decision_id
JOIN direct_validated_classifier_axis_derivations x
  ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
JOIN direct_validated_classifier_predictions p
  ON p.run_id=x.run_id AND p.prediction_id=x.prediction_id
 AND p.model_id=x.model_id AND p.payment_id=x.payment_id
 AND p.direct_event_key=x.direct_event_key
 AND p.current_evidence_id=x.current_evidence_id
JOIN direct_validated_classifier_models m
  ON m.run_id=x.run_id AND m.model_id=x.model_id
JOIN direct_promotion_evidence current_e
  ON current_e.run_id=x.run_id AND current_e.evidence_id=x.current_evidence_id
JOIN direct_payment_projection_links l
  ON l.run_id=b.run_id AND l.payment_id=d.target_id
JOIN direct_normalized_payments payment ON payment.id=l.direct_payment_id
WHERE d.target_type='payment' AND d.decision_status='confirmed'
  AND d.dimension IN ('account','cost_type','allocation_target')
  AND x.payment_id=d.target_id AND x.dimension=d.dimension
  AND x.value=d.value AND x.rule_id=d.rule_id
  AND x.derivation_status='pass' AND x.conflict_count=0
  AND p.conflict_count=0
  AND m.validation_error_count=0
  AND m.validation_count>0 AND m.validation_count<=m.promoted_count
  AND m.training_role='learning_only_not_transaction_evidence'
  AND current_e.evidence_kind='current_card'
  AND current_e.authority_status='current_raw'
  AND current_e.direct_event_key=payment.card_event_id || '#' || payment.event_role

UNION ALL
SELECT b.run_id,d.id,d.target_type,d.target_id,d.dimension,d.value,
       d.confidence,d.confidence_label,d.decision_status,d.rule_id,d.rationale,
       x.derivation_id,x.current_evidence_id,x.model_id
FROM direct_high_coverage_classifier_decision_bindings b
JOIN current_classification_decisions d ON d.id=b.decision_id
JOIN direct_high_coverage_classifier_axis_derivations x
  ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
JOIN direct_high_coverage_classifier_predictions p
  ON p.run_id=x.run_id AND p.prediction_id=x.prediction_id
 AND p.model_id=x.model_id AND p.payment_id=x.payment_id
 AND p.direct_event_key=x.direct_event_key
 AND p.current_evidence_id=x.current_evidence_id
JOIN direct_high_coverage_classifier_models m
  ON m.run_id=x.run_id AND m.model_id=x.model_id
JOIN direct_promotion_evidence current_e
  ON current_e.run_id=x.run_id AND current_e.evidence_id=x.current_evidence_id
JOIN direct_payment_projection_links l
  ON l.run_id=b.run_id AND l.payment_id=d.target_id
JOIN direct_normalized_payments payment ON payment.id=l.direct_payment_id
WHERE d.target_type='payment' AND d.decision_status='confirmed'
  AND d.dimension IN ('account','cost_type','allocation_target')
  AND x.payment_id=d.target_id AND x.dimension=d.dimension
  AND x.value=d.value AND x.rule_id=d.rule_id
  AND x.derivation_status='pass' AND x.conflict_count=0
  AND p.conflict_count=0
  AND m.validation_error_count=0
  AND m.validation_count>0
  AND m.training_role='learning_only_not_transaction_evidence'
  AND current_e.evidence_kind='current_card'
  AND current_e.authority_status='current_raw'
  AND current_e.direct_event_key=payment.card_event_id || '#' || payment.event_role;

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
