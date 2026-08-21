"""Run-scoped, fail-closed gates for the isolated direct candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping
from ledger.domain.decision_integrity import decision_integrity
from ledger.domain.direct_structural_rule_requests import (
    build_structural_rule_request_report,
)
from ledger.domain.direct_2025_payment_terminal import (
    build_census,
    terminal_payment_ids,
    validate_2025_payment_terminals,
)
from ledger.domain.direct_2025_cost_accounting import (
    cost_payment_ids,
    validate_2025_cost_accounting,
)


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
SCHEMA_VERSION = "p07-direct-v3"
PARSER_BUNDLE_VERSION = "direct-source-v5"
OTA_CONFIRMED_TARGET_PATHS = frozenset({
    "ota_mail_service_period_exact",
    "ota_mail_service_period_mn_target_invariant",
    "ota_mail_service_period_amount_tolerance_exact",
    "ota_mail_service_period_amount_tolerance_mn_target_invariant",
})
REQUIRED_INPUTS = (
    {
        "source_kind": "card_raw:A_20260720",
        "relative_path": "ledger/newcard/conv/A_20260720.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "CORP:A_20260720:",
    },
    {
        "source_kind": "card_raw:E",
        "relative_path": "ledger/newcard/conv/E.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "KBO:E:",
    },
    {
        "source_kind": "card_raw:F",
        "relative_path": "ledger/newcard/conv/F.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "KBD:F:",
    },
    {
        "source_kind": "card_raw:G",
        "relative_path": "ledger/newcard/conv/G.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "HAN:G:",
    },
    {
        "source_kind": "card_raw:H",
        "relative_path": "ledger/newcard/conv/H.xlsx",
        "db_source_kind": "card_raw",
        "record_prefix": "HAN:H:",
    },
    {
        "source_kind": "manual_ledger",
        "relative_path": "ledger/data/manual_v4.csv",
        "db_source_kind": "manual_ledger",
        "record_prefix": None,
    },
    {
        "source_kind": "classifier_training",
        "relative_path": "ledger/data/classified_v14.csv",
        "db_source_kind": "classifier_training",
        "record_prefix": None,
    },
    {
        "source_kind": "ota_mail",
        "relative_path": "ledger/data/ota_mail_index.json",
        "db_source_kind": "ota_mail",
        "record_prefix": None,
    },
    {
        "source_kind": "ota_mail_live",
        "relative_path": "ledger/data/ota_mail_live_index.json",
        "db_source_kind": "ota_mail_live",
        "record_prefix": None,
    },
    {
        "source_kind": "pg_mail",
        "relative_path": "ledger/data/pg_mail_index.json",
        "db_source_kind": "pg_mail",
        "record_prefix": None,
    },
    {
        "source_kind": "pg_mail_supplement",
        "relative_path": "ledger/data/pg_mail_supplemental_index.json",
        "db_source_kind": "pg_mail_supplement",
        "record_prefix": None,
    },
    {
        "source_kind": "service_mail",
        "relative_path": "ledger/data/service_mail_index.json",
        "db_source_kind": "service_mail",
        "record_prefix": None,
    },
    {
        "source_kind": "trip_schedule",
        "relative_path": "ledger/data/trips.json",
        "db_source_kind": "trip_schedule",
        "record_prefix": None,
    },
    {
        "source_kind": "geographic_trip_context",
        "relative_path": "ledger/data/current_geographic_trip_context.json",
        "db_source_kind": "geographic_trip_context",
        "record_prefix": None,
    },
    {
        "source_kind": "ota_lodging_fact",
        "relative_path": "ledger/data/ota_lodging_facts_v2.json",
        "db_source_kind": "ota_lodging_fact",
        "record_prefix": None,
    },
    {
        "source_kind": "ota_reservation_fact",
        "relative_path": "ledger/data/ota_event_links_verified.json",
        "db_source_kind": "ota_reservation_fact",
        "record_prefix": None,
    },
    {
        "source_kind": "current_owner_decision",
        "relative_path": "ledger/data/current_owner_decisions_v1.json",
        "db_source_kind": "current_owner_decision",
        "record_prefix": None,
    },
)
GATE_NAMES = (
    "source_provenance",
    "event_projection_cardinality",
    "legacy_leakage",
    "amount_sign_and_relations",
    "allocation_and_decision_completeness",
    "semantic_regression",
    "report_freshness",
)
# Gate5 separates lossless triage from release finality.  These limits are
# operational queue SLOs only: exceeding one must stay visible in the report,
# but it cannot turn an otherwise lossless, side-effect-free triage run into a
# correctness failure.  Release readiness is evaluated independently and still
# requires every payment in the declared release scope to be final.
TRAVEL_UNASSIGNED_QUEUE_SLO = 5
HUMAN_QUESTION_GROUP_QUEUE_SLO = 10


def _travel_unassigned_queue_slo_met(keys: Iterable[object]) -> bool:
    """Return whether the unique travel-unassigned key count meets its SLO."""
    return len({str(key) for key in keys}) <= TRAVEL_UNASSIGNED_QUEUE_SLO


def _queue_slo_diagnostics(
    travel_unassigned_keys: Iterable[object],
    human_question_group_count: int,
) -> dict[str, object]:
    """Report queue workload targets without changing correctness gates."""
    travel_slo_met = _travel_unassigned_queue_slo_met(
        travel_unassigned_keys
    )
    human_slo_met = (
        human_question_group_count <= HUMAN_QUESTION_GROUP_QUEUE_SLO
    )
    warnings = []
    if not travel_slo_met:
        warnings.append("travel_unassigned_slo_exceeded")
    if not human_slo_met:
        warnings.append("human_question_group_slo_exceeded")
    return {
        "enforcement": "advisory_only",
        "warnings": warnings,
        "travel_unassigned_slo_met": travel_slo_met,
        "human_question_group_slo_met": human_slo_met,
    }


# A reservation placeholder has no service period.  Payment year is never
# written as the reservation's service year and is not used to exclude rows
# from the automatic follow-up lane.
AUTO_PROVISIONAL_ACTION_YEAR = "service_period_unknown"
AUTO_PROVISIONAL_ACTION_PATH = "current_card_reservation_placeholder"
CURRENT_ASSIGNMENT_QUEUE_SCOPE = "all_period_automatic_followup"
CURRENT_ASSIGNMENT_PAYMENT_YEAR = None
AUTO_PROVISIONAL_REVIEW_STATUS = "auto_provisional"
OWNER_CONFIRMATION_REVIEW_STATUS = "needs_review"
GMAIL_PAYMENT_SERVICE_PERIOD_PATH = "gmail_payment_service_period_evidence"
GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH = (
    "gmail_payment_service_period_pending_review"
)
GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH = (
    "gmail_payment_approval_family_pending_review"
)
INFERRED_EXTERNAL_TARGET_PATH = "current_card_inferred_external_target"
INFERRED_EXTERNAL_TARGET_KIND = "inferred_external_target"
DOMESTIC_GATEWAY_UNVERIFIED_PATH = "domestic_gateway_unverified"
FOREIGN_USE_DATE_SCHEDULE_PATH = (
    "current_card_foreign_use_date_schedule_overrides_manual_ambiguity"
)


def _unknown_service_period_reservation(paths: Iterable[str]) -> bool:
    """Return true only for the reservation placeholder action lane.

    The caller must not pass a payment year here.  A card posting year is not
    evidence of an OTA service year, so every still-unknown reservation stays
    actionable until a service-period source closes it.
    """
    return set(paths) == {AUTO_PROVISIONAL_ACTION_PATH}


def _current_assignment_queue_in_scope(occurred_on: object) -> bool:
    """Keep every unknown-period reservation in the automatic lane.

    The argument remains for source compatibility with older callers.  A card
    posting date is not a service date, so no payment-year filter may remove a
    row from the all-period follow-up queue.
    """
    del occurred_on
    return True
APPROVAL_REQUIRED_FIELDS = {
    "transition_id",
    "rule_id",
    "direct_event_keys",
    "before_event_sha256",
    "after_event_sha256",
    "evidence_set_sha256",
    "before_semantic_sha256",
    "after_semantic_sha256",
    "approved_by",
    "approved_at",
    "approval_source",
    "approval_source_sha256",
    "source_run_id",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _semantic_manifest_payload(payload_json: object) -> object:
    """Return manifest meaning without run-scoped operational metadata.

    Settlement and lodging manifests retain ``run_id`` in their persisted
    payload for lineage validation.  That identifier is intentionally not a
    semantic input: otherwise identical candidates from two fresh runs would
    receive different candidate semantic hashes.
    """
    try:
        payload = json.loads(str(payload_json))
    except (TypeError, json.JSONDecodeError):
        return str(payload_json)
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.pop("run_id", None)
    return payload


def _key_set_sha256(keys: Iterable[str]) -> str:
    return _sha256_bytes(
        ("\n".join(sorted(str(key) for key in keys)) + "\n").encode("utf-8")
    )


def input_manifest_sha256(inventory: Iterable[dict[str, object]]) -> str:
    ordered = sorted(
        (dict(item) for item in inventory),
        key=lambda row: (str(row["source_kind"]), str(row["relative_path"])),
    )
    return _sha256_bytes(_canonical_json_bytes(ordered))


def candidate_semantic_sha256(db: object, run_id: str) -> str:
    payment_rows = db.execute(
        """
        SELECT
            p.external_key,
            p.source_event_id,
            p.identity_fingerprint,
            p.source_system,
            p.occurred_on,
            p.merchant,
            p.approval_number,
            p.amount_krw,
            p.transaction_type,
            d.card_event_id,
            d.event_role,
            s.source_kind,
            s.source_key,
            s.source_sha256
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE l.run_id=?
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    relation_rows = db.execute(
        """
        SELECT p.external_key,rp.external_key,r.relation_type,r.reference_value,
               r.match_method,r.confidence,r.relation_status,r.resolution_code,r.rationale
        FROM transaction_relations r
        JOIN payment_transactions p ON p.id=r.transaction_id
        LEFT JOIN payment_transactions rp ON rp.id=r.related_transaction_id
        JOIN direct_payment_projection_links l ON l.payment_id=p.id
        WHERE l.run_id=?
        ORDER BY p.external_key,r.relation_type,r.reference_value
        """, (run_id,)).fetchall()
    decision_rows = db.execute(
        """SELECT p.external_key,d.dimension,d.value,d.confidence,d.confidence_label,
                  d.decision_status,d.rule_id,d.rationale
           FROM classification_decisions d
           JOIN payment_transactions p ON d.target_type='payment' AND p.id=d.target_id
           JOIN direct_payment_projection_links l ON l.payment_id=p.id
           WHERE l.run_id=? AND d.target_type='payment'
           ORDER BY p.external_key,d.dimension""", (run_id,)).fetchall()
    allocation_rows = db.execute(
        """SELECT p.external_key,ap.plan_version,ap.plan_status,ap.confidence,
                  sd.dimension,sd.value,t.target_type,t.code,t.name,tr.code,tr.region,
                  tr.starts_on,tr.ends_on,a.amount_krw,a.booking_id
           FROM allocation_plans ap
           JOIN payment_transactions p ON p.id=ap.payment_id
           JOIN direct_payment_projection_links l ON l.payment_id=p.id
           JOIN cost_allocations a ON a.plan_id=ap.id
           JOIN allocation_targets t ON t.id=a.target_id
           LEFT JOIN trips tr ON tr.id=t.trip_id
           LEFT JOIN classification_decisions sd ON sd.id=ap.source_decision_id
           WHERE l.run_id=?
           ORDER BY p.external_key,ap.plan_version,a.id""", (run_id,)).fetchall()
    review_rows = db.execute(
        """SELECT p.external_key,r.outcome,r.reason_code,r.rationale,
                  r.review_status,r.rule_id
           FROM allocation_review_cases r
           JOIN payment_transactions p ON p.id=r.payment_id
           JOIN direct_payment_projection_links l ON l.payment_id=p.id
           WHERE l.run_id=?
           ORDER BY p.external_key""", (run_id,)).fetchall()
    promotion_evidence_rows = db.execute(
        """SELECT evidence_id,evidence_kind,authority_status,direct_event_key,
                  source_kind,source_key,source_sha256,fact_sha256
           FROM direct_promotion_evidence WHERE run_id=? ORDER BY evidence_id""",
        (run_id,),
    ).fetchall()
    derivation_rows = db.execute(
        """SELECT derivation_id,p.external_key,x.dimension,x.value,x.rule_id,
                  x.current_evidence_id,x.independent_evidence_id,
                  x.derivation_status,x.conflict_count
           FROM direct_axis_derivations x
           JOIN payment_transactions p ON p.id=x.payment_id
           WHERE x.run_id=? ORDER BY derivation_id""",
        (run_id,),
    ).fetchall()
    promotion_binding_rows = db.execute(
        """SELECT p.external_key,d.dimension,d.value,d.rule_id,b.derivation_id
           FROM direct_decision_promotion_bindings b
           JOIN classification_decisions d ON d.id=b.decision_id
           JOIN payment_transactions p ON p.id=d.target_id
           WHERE b.run_id=? ORDER BY p.external_key,d.dimension""",
        (run_id,),
    ).fetchall()
    try:
        high_classifier_rows = db.execute(
            """SELECT m.model_id,m.model_sha256,m.run_state_sha256,
                      m.candidate_set_sha256,m.prediction_set_sha256,
                      p.direct_event_key,p.account,p.cost_type,
                      p.allocation_target,p.rule_path,p.confidence,
                      p.schedule_status,x.dimension,x.value,x.rule_id,
                      x.current_evidence_id,x.derivation_status,x.conflict_count
               FROM direct_high_coverage_classifier_models m
               JOIN direct_high_coverage_classifier_predictions p
                 ON p.run_id=m.run_id AND p.model_id=m.model_id
               JOIN direct_high_coverage_classifier_axis_derivations x
                 ON x.run_id=p.run_id AND x.prediction_id=p.prediction_id
               WHERE m.run_id=?
               ORDER BY p.direct_event_key,x.dimension""",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        high_classifier_rows = []
    settlement_authority_rows = db.execute(
        """SELECT authority_id,authority_kind,relation_key_sha256,
                  member_set_sha256,source_set_sha256,authority_sha256,
                  member_count,purchase_count,reversal_count,net_krw,
                  account,cost_type,allocation_target,individual_pair_asserted,
                  payload_json
           FROM direct_cancellation_settlement_authorities
           WHERE run_id=? ORDER BY authority_id""",
        (run_id,),
    ).fetchall()
    settlement_member_rows = db.execute(
        """SELECT m.authority_id,m.direct_event_key,m.current_evidence_id,
                  p.external_key,m.source_key,m.source_sha256,
                  m.transaction_type,m.member_role,m.amount_krw,m.occurred_on
           FROM direct_cancellation_settlement_members m
           JOIN payment_transactions p ON p.id=m.payment_id
           WHERE m.run_id=? ORDER BY m.authority_id,m.direct_event_key""",
        (run_id,),
    ).fetchall()
    settlement_derivation_rows = db.execute(
        """SELECT x.derivation_id,x.authority_id,p.external_key,
                  x.direct_event_key,x.dimension,x.value,x.rule_id,
                  x.current_evidence_id,x.derivation_status,x.conflict_count
           FROM direct_cancellation_settlement_derivations x
           JOIN payment_transactions p ON p.id=x.payment_id
           WHERE x.run_id=? ORDER BY x.derivation_id""",
        (run_id,),
    ).fetchall()
    settlement_binding_rows = db.execute(
        """SELECT p.external_key,d.dimension,d.value,d.rule_id,b.derivation_id
           FROM direct_cancellation_settlement_decision_bindings b
           JOIN classification_decisions d ON d.id=b.decision_id
           JOIN payment_transactions p ON p.id=d.target_id
           WHERE b.run_id=? ORDER BY p.external_key,d.dimension""",
        (run_id,),
    ).fetchall()
    settlement_withheld_rows = db.execute(
        """SELECT direct_event_key,current_evidence_id,reason_code,detail_sha256
           FROM direct_cancellation_settlement_withheld
           WHERE run_id=? ORDER BY direct_event_key""",
        (run_id,),
    ).fetchall()
    settlement_manifest_rows = db.execute(
        """SELECT state_sha256,manifest_sha256,run_sha256,payload_json
           FROM direct_cancellation_settlement_manifests WHERE run_id=?""",
        (run_id,),
    ).fetchall()
    input_rows = db.execute(
        """SELECT source_kind,relative_path,raw_sha256,lf_sha256,byte_count,
                  key_set_sha256,record_count,parser_version
           FROM direct_projection_inputs WHERE run_id=?
           ORDER BY source_kind,relative_path""", (run_id,),
    ).fetchall()
    lodging_source_rows = db.execute(
        """SELECT source_kind,source_key,source_sha256,payload_json,redaction_version
           FROM direct_source_records
           WHERE source_kind IN ('trip_schedule','ota_lodging_fact')
           ORDER BY source_kind,source_key"""
    ).fetchall()
    geographic_context_source_rows = db.execute(
        """SELECT source_kind,source_key,source_sha256,payload_json,redaction_version
           FROM direct_source_records
           WHERE source_kind='geographic_trip_context'
           ORDER BY source_key"""
    ).fetchall()
    ota_reservation_source_rows = db.execute(
        """SELECT source_kind,source_key,source_sha256,payload_json,redaction_version
           FROM direct_source_records
           WHERE source_kind='ota_reservation_fact'
           ORDER BY source_key"""
    ).fetchall()
    lodging_fact_rows = db.execute(
        """SELECT fact_id,source_key,source_sha256,fact_sha256,provider,booking_ref,
                  property_name,check_in,check_out,seoul_sent_on,paid_total_krw,
                  target_code,account,cost_type,lifecycle_status,payload_json
           FROM direct_verified_lodging_facts WHERE run_id=? ORDER BY fact_id""",
        (run_id,),
    ).fetchall()
    lodging_authority_rows = db.execute(
        """SELECT authority_id,authority_kind,event_set_sha256,fact_set_sha256,
                  amount_multiset_sha256,authority_sha256,event_count,fact_count,
                  property_name,check_in,check_out,account,cost_type,
                  allocation_target,payload_json
           FROM direct_lodging_authorities WHERE run_id=? ORDER BY authority_id""",
        (run_id,),
    ).fetchall()
    lodging_authority_event_rows = db.execute(
        """SELECT e.authority_id,e.direct_event_key,e.current_evidence_id,p.external_key
           FROM direct_lodging_authority_events e
           JOIN payment_transactions p ON p.id=e.payment_id
           WHERE e.run_id=? ORDER BY e.authority_id,e.direct_event_key""",
        (run_id,),
    ).fetchall()
    lodging_authority_fact_rows = db.execute(
        """SELECT authority_id,fact_id FROM direct_lodging_authority_facts
           WHERE run_id=? ORDER BY authority_id,fact_id""", (run_id,),
    ).fetchall()
    lodging_derivation_rows = db.execute(
        """SELECT x.derivation_id,x.authority_id,p.external_key,x.direct_event_key,
                  x.dimension,x.value,x.rule_id,x.current_evidence_id,
                  x.derivation_status,x.conflict_count
           FROM direct_lodging_axis_derivations x
           JOIN payment_transactions p ON p.id=x.payment_id
           WHERE x.run_id=? ORDER BY x.derivation_id""", (run_id,),
    ).fetchall()
    lodging_binding_rows = db.execute(
        """SELECT p.external_key,d.dimension,d.value,d.rule_id,b.derivation_id
           FROM direct_lodging_decision_bindings b
           JOIN classification_decisions d ON d.id=b.decision_id
           JOIN payment_transactions p ON p.id=d.target_id
           WHERE b.run_id=? ORDER BY p.external_key,d.dimension""", (run_id,),
    ).fetchall()
    lodging_withheld_rows = db.execute(
        """SELECT item_kind,item_key,reason_code,detail_sha256
           FROM direct_lodging_withheld WHERE run_id=?
           ORDER BY item_kind,item_key,reason_code""", (run_id,),
    ).fetchall()
    lodging_manifest_rows = db.execute(
        """SELECT state_sha256,manifest_sha256,run_sha256,payload_json
           FROM direct_lodging_cohort_manifests WHERE run_id=?""", (run_id,),
    ).fetchall()
    classifier_training_rows = db.execute(
        """SELECT source_key,source_sha256,payload_json,redaction_version
           FROM direct_source_records WHERE source_kind='classifier_training'
           ORDER BY source_key"""
    ).fetchall()
    classifier_model_rows = db.execute(
        """SELECT model_id,model_contract,model_sha256,run_state_sha256,
                  training_source_sha256,
                  candidate_set_sha256,prediction_set_sha256,
                  validation_set_sha256,training_row_count,candidate_count,
                  promoted_count,validation_count,validation_error_count,
                  minimum_peer_count,training_role,payload_json
           FROM direct_validated_classifier_models WHERE run_id=?
           ORDER BY model_id""", (run_id,),
    ).fetchall()
    classifier_prediction_rows = db.execute(
        """SELECT prediction_id,model_id,direct_event_key,current_evidence_id,
                  payment_id,feature_sha256,loo_model_sha256,
                  held_out_association_sha256,
                  account,cost_type,allocation_target,account_a_support,
                  account_b_support,target_q_support,target_r_support,
                  account_a_peer_set_sha256,account_b_peer_set_sha256,
                  target_q_peer_set_sha256,target_r_peer_set_sha256,
                  schedule_status,conflict_count,prediction_sha256,
                  peer_payload_json
           FROM direct_validated_classifier_predictions WHERE run_id=?
           ORDER BY prediction_id""", (run_id,),
    ).fetchall()
    classifier_derivation_rows = db.execute(
        """SELECT x.derivation_id,x.model_id,x.prediction_id,p.external_key,
                  x.direct_event_key,x.dimension,x.value,x.rule_id,
                  x.current_evidence_id,x.derivation_status,x.conflict_count
           FROM direct_validated_classifier_axis_derivations x
           JOIN payment_transactions p ON p.id=x.payment_id
           WHERE x.run_id=? ORDER BY x.derivation_id""", (run_id,),
    ).fetchall()
    classifier_binding_rows = db.execute(
        """SELECT p.external_key,d.dimension,d.value,d.rule_id,b.derivation_id
           FROM direct_validated_classifier_decision_bindings b
           JOIN classification_decisions d ON d.id=b.decision_id
           JOIN payment_transactions p ON p.id=d.target_id
           WHERE b.run_id=? ORDER BY p.external_key,d.dimension""", (run_id,),
    ).fetchall()
    classifier_withheld_rows = db.execute(
        """SELECT direct_event_key,current_evidence_id,reason_code,detail_sha256
           FROM direct_validated_classifier_withheld WHERE run_id=?
           ORDER BY direct_event_key,reason_code""", (run_id,),
    ).fetchall()
    ota_reservation_queue_rows = db.execute(
        """SELECT source_key,fact_sha256,reason_code,candidate_count,detail_sha256
           FROM direct_ota_reservation_queue WHERE run_id=?
           ORDER BY source_key""", (run_id,),
    ).fetchall()
    trip_registry_rows = db.execute(
        """SELECT registry_id,registry_version,rule_id,registry_sha256,
                  target_code,target_kind,source_system,card_identity_sha256,
                  country,region,starts_on,ends_on,event_set_sha256,
                  fact_set_sha256,registry_status,payload_json
           FROM direct_high_coverage_trip_registries
           WHERE run_id=? ORDER BY registry_id""",
        (run_id,),
    ).fetchall()
    trip_registry_member_rows = db.execute(
        """SELECT registry_id,payment_id,direct_event_key,
                  current_evidence_id,current_fact_sha256
           FROM direct_high_coverage_trip_registry_members
           WHERE run_id=? ORDER BY registry_id,payment_id""",
        (run_id,),
    ).fetchall()
    try:
        terminal_rows = db.execute(
            """
            SELECT payment_id,direct_event_key,disposition,rule_id,
                   provenance_sha256,travel_eligible,accounting_final,
                   allocation_eligible,posting_eligible,
                   reversal_inheritance_eligible,membership_sha256,payload_json
            FROM direct_2025_payment_terminals
            WHERE run_id=? ORDER BY payment_id
            """,
            (run_id,),
        ).fetchall()
        terminal_manifest_rows = db.execute(
            """
            SELECT rule_id,candidate_count,cancellation_count,mail_travel_count,
                   residual_terminal_count,excluded_count,candidate_set_sha256,
                   cancellation_set_sha256,mail_travel_set_sha256,
                   residual_terminal_set_sha256,excluded_set_sha256,
                   partition_set_sha256,payload_json
            FROM direct_2025_payment_terminal_manifests WHERE run_id=?
            """,
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        terminal_rows = []
        terminal_manifest_rows = []
    try:
        cost_rows = db.execute(
            """SELECT payment_id,direct_event_key,rule_id,account,cost_type,
                      allocation_target,target_type,current_evidence_id,
                      independent_evidence_id,membership_sha256,provenance_sha256,
                      travel_eligible,accounting_final,allocation_eligible,
                      posting_eligible,reversal_inheritance_eligible,payload_json
               FROM direct_2025_cost_accounting
               WHERE run_id=? ORDER BY payment_id""",
            (run_id,),
        ).fetchall()
        cost_manifest_rows = db.execute(
            """SELECT rule_id,candidate_count,payment_count,payment_set_sha256,
                      policy_source_sha256,partition_sha256,payload_json
               FROM direct_2025_cost_accounting_manifests WHERE run_id=?""",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        cost_rows = []
        cost_manifest_rows = []
    return _sha256_bytes(_canonical_json_bytes({
        "payments": [list(row) for row in payment_rows],
        "relations": [list(row) for row in relation_rows],
        "decisions": [list(row) for row in decision_rows],
        "allocations": [list(row) for row in allocation_rows],
        "allocation_review_cases": [list(row) for row in review_rows],
        "promotion_evidence": [list(row) for row in promotion_evidence_rows],
        "axis_derivations": [list(row) for row in derivation_rows],
        "promotion_bindings": [list(row) for row in promotion_binding_rows],
        "high_coverage_classifier": [
            list(row) for row in high_classifier_rows
        ],
        "settlement_authorities": [
            list(row) for row in settlement_authority_rows
        ],
        "settlement_members": [list(row) for row in settlement_member_rows],
        "settlement_derivations": [
            list(row) for row in settlement_derivation_rows
        ],
        "settlement_bindings": [list(row) for row in settlement_binding_rows],
        "settlement_withheld": [list(row) for row in settlement_withheld_rows],
        "settlement_manifest": [
            [row[0], _semantic_manifest_payload(row[3])]
            for row in settlement_manifest_rows
        ],
        "projection_inputs": [list(row) for row in input_rows],
        "lodging_safe_sources": [list(row) for row in lodging_source_rows],
        "geographic_trip_context_sources": [
            list(row) for row in geographic_context_source_rows
        ],
        "ota_reservation_sources": [
            list(row) for row in ota_reservation_source_rows
        ],
        "lodging_verified_facts": [list(row) for row in lodging_fact_rows],
        "lodging_authorities": [list(row) for row in lodging_authority_rows],
        "lodging_authority_events": [list(row) for row in lodging_authority_event_rows],
        "lodging_authority_facts": [list(row) for row in lodging_authority_fact_rows],
        "lodging_derivations": [list(row) for row in lodging_derivation_rows],
        "lodging_bindings": [list(row) for row in lodging_binding_rows],
        "lodging_withheld": [list(row) for row in lodging_withheld_rows],
        "lodging_manifest": [
            [row[0], _semantic_manifest_payload(row[3])]
            for row in lodging_manifest_rows
        ],
        "classifier_training_sources": [
            list(row) for row in classifier_training_rows
        ],
        "classifier_models": [list(row) for row in classifier_model_rows],
        "classifier_predictions": [
            list(row) for row in classifier_prediction_rows
        ],
        "classifier_derivations": [
            list(row) for row in classifier_derivation_rows
        ],
        "classifier_bindings": [list(row) for row in classifier_binding_rows],
        "classifier_withheld": [list(row) for row in classifier_withheld_rows],
        "ota_reservation_queue": [list(row) for row in ota_reservation_queue_rows],
        "trip_registries": [list(row) for row in trip_registry_rows],
        "trip_registry_members": [
            list(row) for row in trip_registry_member_rows
        ],
        "payment_year_2025_terminals": [list(row) for row in terminal_rows],
        "payment_year_2025_terminal_manifests": [
            list(row) for row in terminal_manifest_rows
        ],
        "payment_year_2025_cost_accounting": [list(row) for row in cost_rows],
        "payment_year_2025_cost_accounting_manifests": [
            list(row) for row in cost_manifest_rows
        ],
    }))


def gate_report_sha256(report: dict[str, object]) -> str:
    payload = dict(report)
    payload.pop("gate_report_sha256", None)
    return _sha256_bytes(_canonical_json_bytes(payload))


def _validate_sha256(value: object, field: str, index: int) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"approval_hash_invalid:{index}:{field}")
    return value


def _validate_rfc3339_with_timezone(
    value: object, field: str, index: int
) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            r"(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
            value,
        ) is None
    ):
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}")
    if value.endswith("-00:00"):
        raise ValueError(f"approval_timestamp_invalid:{index}:{field}")
    return value


def validate_approved_transitions(
    approvals: Iterable[dict[str, object]] | None,
    *,
    expected_source_run_id: str | None = None,
    expected_after_semantic_sha256: str | None = None,
) -> list[dict[str, object]]:
    if approvals is None:
        return []
    validated: list[dict[str, object]] = []
    transition_ids: set[str] = set()
    event_keys_seen: set[str] = set()
    for index, raw in enumerate(approvals):
        if not isinstance(raw, dict):
            raise ValueError(f"approval_not_object:{index}")
        missing = sorted(APPROVAL_REQUIRED_FIELDS - set(raw))
        if missing:
            raise ValueError(
                f"approval_missing_event_lineage:{index}:{','.join(missing)}"
            )
        event_keys = raw["direct_event_keys"]
        if not isinstance(event_keys, list) or len(event_keys) != 1:
            raise ValueError(f"approval_event_keys_invalid:{index}")
        if (
            not isinstance(event_keys[0], str)
            or re.fullmatch(
                r"card:[0-9a-f]{64}#(single|approval|cancellation)",
                event_keys[0],
            ) is None
        ):
            raise ValueError(f"approval_event_keys_invalid:{index}")
        for field in (
            "before_event_sha256",
            "after_event_sha256",
            "evidence_set_sha256",
            "before_semantic_sha256",
            "after_semantic_sha256",
            "approval_source_sha256",
        ):
            _validate_sha256(raw[field], field, index)
        _validate_sha256(raw["transition_id"], "transition_id", index)
        for field in ("rule_id", "approved_by", "approval_source", "source_run_id"):
            if not isinstance(raw[field], str) or not raw[field].strip():
                raise ValueError(f"approval_field_invalid:{index}:{field}")
        _validate_rfc3339_with_timezone(raw["approved_at"], "approved_at", index)
        if raw.get("supersedes_approval_id") is not None:
            raise ValueError(f"approval_supersession_unsupported:{index}")
        if raw.get("supersedes") is not None:
            raise ValueError(f"approval_supersedes_field_invalid:{index}")
        if raw["transition_id"] in transition_ids:
            raise ValueError(f"approval_duplicate_transition:{index}")
        if event_keys[0] in event_keys_seen:
            raise ValueError(f"approval_duplicate_event:{index}")
        if (
            expected_source_run_id is not None
            and raw["source_run_id"] != expected_source_run_id
        ):
            raise ValueError(f"approval_source_run_mismatch:{index}")
        if (
            expected_after_semantic_sha256 is not None
            and raw["after_semantic_sha256"] != expected_after_semantic_sha256
        ):
            raise ValueError(f"approval_after_semantic_mismatch:{index}")
        transition_ids.add(raw["transition_id"])
        event_keys_seen.add(event_keys[0])
        validated.append(dict(raw))
    return validated


def _load_comparable_baseline(
    descriptor: dict[str, object],
    repository_root: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    required = {"relative_path", "role", "raw_sha256"}
    missing = sorted(required - set(descriptor))
    if missing:
        raise ValueError(f"baseline_missing_provenance:{','.join(missing)}")
    if descriptor["role"] != "direct_semantic_baseline":
        raise ValueError("baseline_role_invalid")
    root = repository_root.resolve()
    candidate = (root / str(descriptor["relative_path"])).resolve()
    try:
        relative_path = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("baseline_path_escape") from exc
    if not candidate.is_file():
        raise ValueError("baseline_missing")
    raw = candidate.read_bytes()
    actual_hash = _sha256_bytes(raw)
    if descriptor["raw_sha256"] != actual_hash:
        raise ValueError("baseline_hash_mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("baseline_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("baseline_payload_not_object")
    return payload, {
        "relative_path": relative_path,
        "role": "direct_semantic_baseline",
        "raw_sha256": actual_hash,
    }


_DIRECT_EVENT_BASELINE_SCOPE = "direct-event-role-v1"
_DIRECT_EVENT_KEY_PATTERN = re.compile(
    r"^card:[0-9a-f]{64}#(single|approval|cancellation)$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _event_set_sha256(events: Iterable[tuple[str, str]]) -> str:
    canonical = "".join(
        f"{key} {event_hash}\n"
        for key, event_hash in sorted(events)
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def _decision_scope_sha256(keys: Iterable[str]) -> str:
    canonical = ("\n".join(sorted(keys)) + "\n").encode("utf-8")
    return _sha256_bytes(canonical)


def _direct_event_semantic_hash(payload: dict[str, object]) -> str:
    return _sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _current_direct_event_hashes(
    db: object,
    run_id: str,
) -> tuple[dict[str, str], str, str]:
    rows = db.execute(
        """
        SELECT
            d.card_event_id,
            d.event_role,
            p.external_key,
            p.source_event_id,
            p.identity_fingerprint,
            p.source_system,
            p.occurred_on,
            p.merchant,
            p.approval_number,
            p.amount_krw,
            p.transaction_type,
            s.source_kind,
            s.source_key,
            s.source_sha256
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE l.run_id=?
        ORDER BY d.card_event_id, d.event_role
        """,
        (run_id,),
    ).fetchall()
    event_hashes: dict[str, str] = {}
    for row in rows:
        key = f"{row[0]}#{row[1]}"
        if not _DIRECT_EVENT_KEY_PATTERN.fullmatch(key):
            raise ValueError("baseline_current_event_key_invalid")
        if key in event_hashes:
            raise ValueError("baseline_current_event_key_duplicate")
        payload = {
            "direct_event_key": key,
            "external_key": row[2],
            "source_event_id": row[3],
            "identity_fingerprint": row[4],
            "source_system": row[5],
            "occurred_on": row[6],
            "merchant": row[7],
            "approval_number": row[8],
            "amount_krw": int(row[9]),
            "transaction_type": row[10],
            "card_event_id": row[0],
            "event_role": row[1],
            "source_kind": row[11],
            "source_key": row[12],
            "source_sha256": row[13],
        }
        event_hashes[key] = _direct_event_semantic_hash(payload)
    return event_hashes, _event_set_sha256(event_hashes.items()), _decision_scope_sha256(
        event_hashes
    )


def _validate_event_baseline(
    payload: dict[str, object],
    *,
    run_id: str,
) -> tuple[dict[str, object], dict[str, str]]:
    format_version = payload.get("format_version")
    if type(format_version) is not int or format_version != 1:
        raise ValueError("baseline_format_version_invalid")
    if payload.get("event_scope") != _DIRECT_EVENT_BASELINE_SCOPE:
        raise ValueError("baseline_event_scope_invalid")
    if payload.get("parser_version") != PARSER_BUNDLE_VERSION:
        raise ValueError("baseline_parser_version_invalid")
    required = (
        "parser_version", "source_run_id", "input_manifest_sha256",
        "decision_scope_sha256", "candidate_semantic_sha256",
        "event_set_sha256", "events",
    )
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise ValueError(f"baseline_missing_field:{','.join(missing)}")
    if not isinstance(payload["source_run_id"], str) or not payload["source_run_id"].strip():
        raise ValueError("baseline_source_run_invalid")
    for field in (
        "input_manifest_sha256", "decision_scope_sha256",
        "candidate_semantic_sha256", "event_set_sha256",
    ):
        if not isinstance(payload[field], str) or not _SHA256_PATTERN.fullmatch(payload[field]):
            raise ValueError(f"baseline_hash_invalid:{field}")
    events = payload["events"]
    if not isinstance(events, list) or not events:
        raise ValueError("baseline_events_invalid")
    baseline_hashes: dict[str, str] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != {"direct_event_key", "event_sha256"}:
            raise ValueError(f"baseline_event_invalid:{index}")
        key = event["direct_event_key"]
        event_hash = event["event_sha256"]
        if not isinstance(key, str) or not _DIRECT_EVENT_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"baseline_event_key_invalid:{index}")
        if not isinstance(event_hash, str) or not _SHA256_PATTERN.fullmatch(event_hash):
            raise ValueError(f"baseline_event_hash_invalid:{index}")
        if key in baseline_hashes:
            raise ValueError("baseline_event_key_duplicate")
        baseline_hashes[key] = event_hash
    baseline_scope_hash = _decision_scope_sha256(baseline_hashes)
    if payload["decision_scope_sha256"] != baseline_scope_hash:
        raise ValueError("baseline_decision_scope_hash_mismatch")
    if _event_set_sha256(baseline_hashes.items()) != payload["event_set_sha256"]:
        raise ValueError("baseline_event_set_hash_mismatch")
    return payload, baseline_hashes


def _gate(
    number: int,
    name: str,
    passed: bool,
    *,
    reason: str,
    actual: object,
) -> dict[str, object]:
    return {
        "gate": number,
        "name": name,
        "passed": bool(passed),
        "reason": reason,
        "actual": actual,
    }


def _input_rows(db: object, run_id: str) -> list[dict[str, object]]:
    columns = (
        "source_kind",
        "relative_path",
        "raw_sha256",
        "lf_sha256",
        "byte_count",
        "key_set_sha256",
        "record_count",
        "parser_version",
    )
    rows = db.execute(
        """
        SELECT
            source_kind, relative_path, raw_sha256, lf_sha256,
            byte_count, key_set_sha256, record_count, parser_version
        FROM direct_projection_inputs
        WHERE run_id=?
        ORDER BY source_kind, relative_path
        """,
        (run_id,),
    ).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _actual_source_keys(
    db: object,
    spec: dict[str, object],
) -> list[str]:
    db_kind = str(spec["db_source_kind"])
    prefix = spec["record_prefix"]
    if prefix is None:
        rows = db.execute(
            """
            SELECT source_key
            FROM direct_source_records
            WHERE source_kind=?
            ORDER BY source_key
            """,
            (db_kind,),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT source_key
            FROM direct_source_records
            WHERE source_kind=? AND source_key LIKE ?
            ORDER BY source_key
            """,
            (db_kind, f"{prefix}%"),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _source_provenance_gate(
    db: object,
    run_id: str,
    run: dict[str, object],
    repository_root: Path,
) -> dict[str, object]:
    inputs = _input_rows(db, run_id)
    required = {
        (str(spec["source_kind"]), str(spec["relative_path"])): spec
        for spec in REQUIRED_INPUTS
    }
    actual_pairs = {
        (str(item["source_kind"]), str(item["relative_path"]))
        for item in inputs
    }
    expected_pairs = set(required)
    issues: list[dict[str, object]] = []
    root = repository_root.resolve()
    for item in inputs:
        pair = (str(item["source_kind"]), str(item["relative_path"]))
        spec = required.get(pair)
        if spec is None:
            issues.append({"reason": "unexpected_input", "input": pair})
            continue
        candidate = (root / str(item["relative_path"])).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            issues.append({"reason": "source_path_escape", "input": pair})
            continue
        if not candidate.is_file():
            issues.append({"reason": "source_missing", "input": pair})
            continue
        raw = candidate.read_bytes()
        expected_lf = None
        if candidate.suffix.lower() != ".xlsx":
            normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            expected_lf = _sha256_bytes(normalized)
        keys = _actual_source_keys(db, spec)
        checks = {
            "raw_sha256": _sha256_bytes(raw),
            "lf_sha256": expected_lf,
            "byte_count": len(raw),
            "record_count": len(keys),
            "key_set_sha256": _key_set_sha256(keys),
            "parser_version": PARSER_BUNDLE_VERSION,
        }
        for field, expected in checks.items():
            if item[field] != expected:
                issues.append(
                    {
                        "reason": f"source_{field}_mismatch",
                        "input": pair,
                        "expected": expected,
                        "actual": item[field],
                    }
                )
    conflicts = db.execute(
        """
        SELECT source_kind, source_key
        FROM direct_source_records
        GROUP BY source_kind, source_key
        HAVING COUNT(DISTINCT source_sha256)>1
        ORDER BY source_kind, source_key
        """
    ).fetchall()
    if conflicts:
        issues.append(
            {
                "reason": "source_key_content_conflict",
                "count": len(conflicts),
                "sample": [list(row) for row in conflicts[:10]],
            }
        )
    recalculated_manifest = input_manifest_sha256(inputs)
    if recalculated_manifest != run["input_manifest_sha256"]:
        issues.append(
            {
                "reason": "input_manifest_hash_mismatch",
                "expected": recalculated_manifest,
                "actual": run["input_manifest_sha256"],
            }
        )
    missing = sorted(expected_pairs - actual_pairs)
    extra = sorted(actual_pairs - expected_pairs)
    if missing:
        issues.append({"reason": "required_input_missing", "inputs": missing})
    if extra:
        issues.append({"reason": "unexpected_input_set", "inputs": extra})
    passed = not issues and len(inputs) == len(REQUIRED_INPUTS)
    return _gate(
        1,
        GATE_NAMES[0],
        passed,
        reason="ok" if passed else str(issues[0]["reason"]),
        actual={
            "physical_input_count": len(inputs),
            "issues": issues,
        },
    )


def _projection_cardinality_gate(
    db: object,
    run_id: str,
) -> dict[str, object]:
    direct_count = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM direct_normalized_payments d
            JOIN direct_source_records s ON s.id=d.source_record_id
            WHERE s.source_kind='card_raw'
            """
        ).fetchone()[0]
    )
    link_count = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM direct_payment_projection_links
            WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()[0]
    )
    unmatched = db.execute(
        """
        SELECT d.card_event_id, d.event_role, s.source_key
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        LEFT JOIN direct_payment_projection_links l
          ON l.direct_payment_id=d.id AND l.run_id=?
        WHERE s.source_kind='card_raw' AND l.payment_id IS NULL
        ORDER BY d.card_event_id, d.event_role
        """,
        (run_id,),
    ).fetchall()
    collisions = db.execute(
        """
        SELECT e.card_event_id, s.source_key
        FROM direct_card_events e
        JOIN direct_source_records s ON s.id=e.source_record_id
        WHERE e.identity_status='collision'
        ORDER BY e.card_event_id, s.source_key
        """
    ).fetchall()
    fallbacks = db.execute(
        """
        SELECT e.card_event_id, s.source_key, e.identity_status
        FROM direct_card_events e
        JOIN direct_source_records s ON s.id=e.source_record_id
        WHERE e.identity_status='legacy_fallback'
        ORDER BY e.card_event_id, s.source_key
        """
    ).fetchall()
    duplicates = db.execute(
        """
        SELECT d.card_event_id, d.event_role, COUNT(*)
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE s.source_kind='card_raw'
        GROUP BY d.card_event_id, d.event_role
        HAVING COUNT(*)>1
        ORDER BY d.card_event_id, d.event_role
        """
    ).fetchall()
    mismatches = db.execute(
        """
        SELECT p.external_key
        FROM direct_payment_projection_links l
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_card_events e ON e.source_record_id=d.source_record_id
        JOIN payment_transactions p ON p.id=l.payment_id
        WHERE l.run_id=?
          AND (
            p.source_event_id<>d.card_event_id
            OR p.amount_krw<>d.amount_krw
            OR p.transaction_type<>d.transaction_type
            OR p.source_system<>e.source_system
            OR COALESCE(p.occurred_on, '')<>COALESCE(e.occurred_on, '')
            OR COALESCE(p.merchant, '')<>COALESCE(e.merchant, '')
            OR COALESCE(p.approval_number, '')<>COALESCE(e.approval_number, '')
          )
        ORDER BY p.external_key
        """
        ,
        (run_id,),
    ).fetchall()
    passed = (
        direct_count > 0
        and direct_count == link_count
        and not unmatched
        and not collisions
        and not fallbacks
        and not duplicates
        and not mismatches
    )
    if collisions:
        reason = "identity_collision"
    elif fallbacks:
        reason = "identity_not_unique"
    elif unmatched:
        reason = "unmatched_direct_payment"
    elif duplicates:
        reason = "duplicate_direct_event_identity"
    elif mismatches:
        reason = "projection_business_field_mismatch"
    elif direct_count != link_count:
        reason = "projection_cardinality_mismatch"
    elif direct_count == 0:
        reason = "direct_payment_set_empty"
    else:
        reason = "ok"
    return _gate(
        2,
        GATE_NAMES[1],
        passed,
        reason=reason,
        actual={
            "direct_payments": direct_count,
            "projection_links": link_count,
            "unmatched_count": len(unmatched),
            "unmatched_sample": [list(row) for row in unmatched[:10]],
            "collision_count": len(collisions),
            "collision_sample": [list(row) for row in collisions[:10]],
            "fallback_count": len(fallbacks),
            "fallback_sample": [list(row) for row in fallbacks[:10]],
            "duplicate_event_count": len(duplicates),
            "business_mismatch_count": len(mismatches),
        },
    )


def _legacy_leakage_gate(db: object, run_id: str) -> dict[str, object]:
    linked_non_card = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM direct_payment_projection_links l
            JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
            JOIN direct_source_records s ON s.id=d.source_record_id
            WHERE l.run_id=? AND s.source_kind<>'card_raw'
            """,
            (run_id,),
        ).fetchone()[0]
    )
    unlinked_payments = db.execute(
        """
        SELECT p.external_key
        FROM payment_transactions p
        LEFT JOIN direct_payment_projection_links l
          ON l.payment_id=p.id AND l.run_id=?
        WHERE l.payment_id IS NULL
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    legacy_lineage = db.execute(
        """
        SELECT p.external_key
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN transaction_sources ts ON ts.transaction_id=p.id
        WHERE l.run_id=?
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    integrity = decision_integrity(db)
    passed = (
        not linked_non_card and not unlinked_payments and not legacy_lineage
        and integrity["orphan_count"] == 0
        and not integrity["allocation_target_binding_unconfirmed"]
        and integrity["invalid_target_type_count"] == 0
    )
    if linked_non_card:
        reason = "non_card_direct_source_linked"
    elif unlinked_payments:
        reason = "unlinked_legacy_payment"
    elif legacy_lineage:
        reason = "legacy_source_record_lineage"
    elif integrity["invalid_target_type_count"]:
        reason = "classification_decision_target_type_invalid"
    elif integrity["orphan_count"]:
        reason = "classification_decision_target_orphan"
    elif integrity["allocation_target_binding_unconfirmed"]:
        reason = "allocation_target_binding_unconfirmed"
    else:
        reason = "ok"
    return _gate(
        3,
        GATE_NAMES[2],
        passed,
        reason=reason,
        actual={
            "linked_non_card": linked_non_card,
            "unlinked_payment_count": len(unlinked_payments),
            "unlinked_payment_sample": [
                str(row[0]) for row in unlinked_payments[:10]
            ],
            "legacy_lineage_count": len(legacy_lineage),
            "decision_integrity": integrity,
        },
    )


def _relation_integrity_issues(db: object, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """
        SELECT r.id,p.external_key,p.source_system,p.transaction_type,
               rp.external_key,rp.source_system,rp.transaction_type,
               r.relation_type,r.reference_value,r.match_method,r.confidence,
               r.relation_status,r.resolution_code,r.rationale,
               CASE WHEN rp.id IS NULL THEN 0 ELSE EXISTS(
                 SELECT 1 FROM direct_payment_projection_links tl
                 WHERE tl.run_id=? AND tl.payment_id=rp.id) END
        FROM transaction_relations r
        JOIN payment_transactions p ON p.id=r.transaction_id
        JOIN direct_payment_projection_links l ON l.payment_id=p.id AND l.run_id=?
        LEFT JOIN payment_transactions rp ON rp.id=r.related_transaction_id
        ORDER BY r.id
        """, (run_id, run_id)).fetchall()
    issues: list[dict[str, object]] = []
    group_counts: dict[str, int] = {}
    for row in rows:
        (relation_id, external_key, source_system, transaction_type,
         related_key, related_source, related_type, relation_type, reference,
         method, confidence, status, resolution, rationale, target_in_run) = row
        def add(reason: str) -> None:
            issues.append({"relation_id": int(relation_id),
                           "external_key": str(external_key), "reason": reason})
        expected_relation = "cancels" if transaction_type == "cancellation" else "refunds" if transaction_type == "refund" else None
        if expected_relation is None or relation_type != expected_relation:
            add("relation_source_type_invalid")
        if status != "proposed" or float(confidence) != 1.0 or not rationale:
            add("relation_authority_invalid")
        if method == "issuer_card4_original_approval_exact":
            if (source_system not in {"HAN", "KBD"} or related_key is None
                    or not target_in_run or related_source != source_system
                    or related_type != "purchase" or not str(reference or "").isdigit()
                    or resolution != "exact_unique_original_approval"):
                add("issuer_relation_shape_invalid")
        elif method == "kbo_card4_currency_foreign_merchant_exact_singleton":
            if (source_system != "KBO" or related_key is None or not target_in_run
                    or related_source != "KBO" or related_type != "purchase"
                    or not str(reference or "").startswith("kbo-group:")
                    or resolution != "exact_unique_foreign_group"):
                add("kbo_singleton_relation_shape_invalid")
        elif method == "kbo_card4_currency_foreign_merchant_unordered_group":
            ref = str(reference or "")
            if (source_system != "KBO" or related_key is not None
                    or not re.fullmatch(r"kbo-group:[0-9a-f]{64}", ref)
                    or resolution != "exact_unordered_foreign_group"):
                add("kbo_group_relation_shape_invalid")
            group_counts[ref] = group_counts.get(ref, 0) + 1
        else:
            add("relation_match_method_invalid")
    invalid_groups = {reference for reference, count in group_counts.items() if count < 2}
    for reference in sorted(invalid_groups):
        issues.append({"relation_id": None, "external_key": None,
                       "reason": "kbo_group_cardinality_invalid",
                       "reference_value": reference, "count": group_counts[reference]})
    return issues


def _amount_relation_gate(db: object,run_id:str,han_equality_context:dict[str,object]|None=None) -> dict[str, object]:
    sign_issues = db.execute(
        """
        SELECT d.card_event_id, d.event_role, d.amount_krw,
               d.transaction_type, s.source_key
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        WHERE s.source_kind='card_raw'
          AND (
            (d.transaction_type='purchase' AND d.amount_krw<=0)
            OR (
              d.transaction_type IN ('refund','cancellation')
              AND d.amount_krw>=0
            )
          )
        ORDER BY d.card_event_id, d.event_role
        """
    ).fetchall()
    split_issues = db.execute(
        """
        SELECT s.source_key
        FROM direct_source_records s
        JOIN direct_normalized_payments d ON d.source_record_id=s.id
        WHERE s.source_kind='card_raw' AND d.event_role<>'single'
        GROUP BY s.id, s.source_key
        HAVING
          SUM(CASE WHEN d.event_role='approval' AND d.amount_krw>0
                   THEN 1 ELSE 0 END)<>1
          OR
          SUM(CASE WHEN d.event_role='cancellation' AND d.amount_krw<0
                   THEN 1 ELSE 0 END)<>1
        ORDER BY s.source_key
        """
    ).fetchall()
    relation_issues = _relation_integrity_issues(db, run_id)
    live_package=None
    if han_equality_context is not None:
        from ledger.domain.han_master_candidate import verify_candidate
        live_package=verify_candidate(**han_equality_context)
    validations=db.execute("""SELECT v.run_id,v.status,v.package_set_sha256,v.authority_sha256,v.input_manifest_sha256,
      v.candidate_semantic_sha256,v.candidate_master_sha256,v.identity_role_set_sha256,v.amount_semantic_sha256,v.validation_sha256
      FROM direct_projection_validations v JOIN direct_projection_runs r ON r.run_id=v.run_id
      WHERE v.run_id=? AND v.status='passed' AND v.input_manifest_sha256=r.input_manifest_sha256
        AND v.candidate_semantic_sha256=r.candidate_semantic_sha256""",(run_id,)).fetchall()
    validation_fields=("run_id","status","package_set_sha256","authority_sha256","input_manifest_sha256",
      "candidate_semantic_sha256","candidate_master_sha256","identity_role_set_sha256","amount_semantic_sha256","validation_sha256")
    valid=[]
    authority_sha=_sha256_bytes((Path(__file__).with_name("han_master_authority.json")).read_bytes())
    for row in validations:
        item=dict(zip(validation_fields,row));claimed=item.pop("validation_sha256")
        envelope=None if live_package is None else live_package["validation_envelope"]
        detail_fields=("package_set_sha256","authority_sha256","input_manifest_sha256","candidate_semantic_sha256",
          "candidate_master_sha256","identity_role_set_sha256","amount_semantic_sha256")
        if (item["authority_sha256"]==authority_sha and claimed==_sha256_bytes(_canonical_json_bytes(item)+b"\n")
          and envelope is not None and all(item[x]==envelope[x] for x in detail_fields)):valid.append((*row,))
    validations=valid
    passed = not sign_issues and not split_issues and not relation_issues and len(validations)==1
    reason = (
        "positive_cancellation_or_invalid_sign"
        if sign_issues
        else "hana_split_pair_invalid"
        if split_issues
        else "transaction_relation_integrity_invalid"
        if relation_issues
        else "han_equality_validation_missing_or_stale"
        if len(validations)!=1
        else "ok"
    )
    return _gate(
        4,
        GATE_NAMES[3],
        passed,
        reason=reason,
        actual={
            "sign_issue_count": len(sign_issues),
            "sign_issue_set_sha256":_sha256_bytes(_canonical_json_bytes([list(row) for row in sign_issues])),
            "hana_split_issue_count": len(split_issues),
            "hana_split_issue_set_sha256":_sha256_bytes(_canonical_json_bytes([list(row) for row in split_issues])),
            "relation_issue_count": len(relation_issues),
            "relation_issue_set_sha256": _sha256_bytes(_canonical_json_bytes(relation_issues)),
            "relation_issue_sample": relation_issues[:10],
            "validation_count":len(validations),
            "validation":dict(zip(validation_fields,validations[0])) if len(validations)==1 else None,
        },
    )


_DIRECT_EVENT_ROLE_SCOPE_FORMAT = "direct-event-role-scope-v1"
_DIRECT_EVENT_ROLE_PATTERN = re.compile(
    r"^card:[0-9a-f]{64}#(single|approval|cancellation)$"
)


def _direct_event_role_scope(rows: Iterable[dict[str, object]]) -> dict[str, object]:
    keys: list[str] = []
    counts_by_source: dict[str, int] = {}
    counts_by_role: dict[str, int] = {}
    counts_by_type: dict[str, int] = {}
    for row in rows:
        key = f"{row['card_event_id']}#{row['event_role']}"
        keys.append(key)
        source = str(row["source_system"])
        role = str(row["event_role"])
        transaction_type = str(row["transaction_type"])
        counts_by_source[source] = counts_by_source.get(source, 0) + 1
        counts_by_role[role] = counts_by_role.get(role, 0) + 1
        counts_by_type[transaction_type] = counts_by_type.get(transaction_type, 0) + 1
    ordered = sorted(keys)
    canonical = ("\n".join(ordered) + "\n").encode("utf-8")
    invalid = [
        key for key in ordered
        if _DIRECT_EVENT_ROLE_PATTERN.fullmatch(key) is None
    ]
    frequencies: dict[str, int] = {}
    for key in ordered:
        frequencies[key] = frequencies.get(key, 0) + 1
    duplicate_keys = sorted(
        key for key, count in frequencies.items() if count > 1
    )
    return {
        "decision_scope_format": _DIRECT_EVENT_ROLE_SCOPE_FORMAT,
        "decision_scope_sha256": _sha256_bytes(canonical),
        "decision_scope_count": len(ordered),
        "decision_scope_unique_count": len(frequencies),
        "decision_scope_invalid_count": len(invalid),
        "decision_scope_invalid_sample": invalid[:10],
        "decision_scope_duplicate_count": sum(
            frequencies[key] - 1 for key in duplicate_keys
        ),
        "decision_scope_duplicate_sample": duplicate_keys[:10],
        "unresolved_direct_event_key_sample": ordered[:10],
        "counts_by_source_system": dict(sorted(counts_by_source.items())),
        "counts_by_event_role": dict(sorted(counts_by_role.items())),
        "counts_by_transaction_type": dict(sorted(counts_by_type.items())),
    }


def _owner_confirmation_question_groups(
    db: object,
    run_id: str,
    reviews_by_payment: Mapping[int, tuple[object, ...]],
) -> list[dict[str, object]]:
    """Build the small user-facing queue while the automatic pass continues.

    The queue is intentionally grouped.  It contains only choices that can
    change a target or a transaction relation; metadata enrichment for an
    already safe temporary target is not listed as an owner question.
    """
    owner_queue_reasons = {
        "manual_travel_tab_ambiguous_owner_confirmation",
        "manual_geography_conflict_owner_confirmation",
        "gmail_service_period_unverified_owner_confirmation",
        "gmail_approval_family_not_singleton_owner_confirmation",
        "domestic_gateway_purpose_owner_confirmation",
        "foreign_service_period_pending_owner_confirmation",
        "row_finality_veto_owner_confirmation",
    }
    ambiguous_ids = {
        payment_id for payment_id, review in reviews_by_payment.items()
        if str(review[2]) == OWNER_CONFIRMATION_REVIEW_STATUS
        and str(review[1]) == "travel_unassigned"
        and str(review[4]) in owner_queue_reasons
    }
    groups: dict[tuple[object, ...], dict[str, object]] = {}
    link_by_event: dict[str, dict[str, object]] = {}
    model_rows = db.execute(
        """SELECT payload_json FROM direct_high_coverage_classifier_models
           WHERE run_id=?""", (run_id,),
    ).fetchall()
    for (payload_json,) in model_rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        links = payload.get("manual_match_links", [])
        if not isinstance(links, list):
            continue
        for link in links:
            if isinstance(link, dict) and str(link.get("direct_event_key") or ""):
                link_by_event[str(link["direct_event_key"])] = link

    if ambiguous_ids:
        placeholders = ",".join("?" for _ in ambiguous_ids)
        rows = db.execute(
            f"""SELECT p.id,p.external_key,p.source_system,p.occurred_on,
                       p.merchant,p.amount_krw,p.approval_number,
                       d.card_event_id || '#' || d.event_role
                FROM payment_transactions p
                JOIN direct_payment_projection_links l
                  ON l.run_id=? AND l.payment_id=p.id
                JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
                WHERE p.id IN ({placeholders})
                ORDER BY p.occurred_on,p.id""",
            (run_id, *sorted(ambiguous_ids)),
        ).fetchall()
        for payment_id, external_key, source, occurred_on, merchant, amount, approval, event_key in rows:
            link = link_by_event.get(str(event_key), {})
            match = link.get("manual_travel_tab_match", {}) if isinstance(link, dict) else {}
            matches = match.get("matches", []) if isinstance(match, dict) else []
            targets = sorted({
                str(item.get("manual_tab") or "") for item in matches
                if isinstance(item, dict) and str(item.get("manual_tab") or "")
            })
            review = reviews_by_payment.get(int(payment_id), ())
            reason = str(review[4]) if review else "manual_travel_tab_ambiguous_owner_confirmation"
            if reason == "gmail_service_period_unverified_owner_confirmation":
                question_type = "gmail_service_period_confirmation"
                question = (
                    "메일의 서비스기간은 확인됐지만 현재 일정표의 한 행사로 1:1 확정되지 않습니다. "
                    "메일·예약의 행사명을 확인해 주세요."
                )
            elif reason == "gmail_approval_family_not_singleton_owner_confirmation":
                question_type = "gmail_approval_family_confirmation"
                question = (
                    "승인번호 계열은 같은 예약군일 뿐 개별 결제 1:1 매칭은 아닙니다. "
                    "해당 결제의 행사명을 확인해 주세요."
                )
            elif reason == "domestic_gateway_purpose_owner_confirmation":
                question_type = "domestic_gateway_purpose_confirmation"
                question = (
                    "국내 결제대행사명만 확인되어 실제 상품·서비스를 알 수 없습니다. "
                    "기타비용인지 여행 관련 결제인지 확인해 주세요."
                )
            elif reason == "foreign_service_period_pending_owner_confirmation":
                question_type = "foreign_service_period_confirmation"
                question = (
                    "해외 가맹점이지만 OTA·항공·예약이 아닌 현장 이용 근거가 없어 "
                    "결제일을 행사일로 확정하지 않았습니다. 행사명을 확인해 주세요."
                )
            elif reason == "row_finality_veto_owner_confirmation":
                question_type = "row_finality_confirmation"
                question = (
                    "현재 비용축은 계산됐지만 행사일·서비스기간을 확정할 근거가 부족합니다. "
                    "메일·예약 또는 실제 행사명을 확인해 주세요."
                )
            else:
                question_type = "manual_target_choice"
                question = ""
            key = (reason, str(source), str(occurred_on), str(merchant), abs(int(amount)), tuple(targets))
            group = groups.setdefault(key, {
                "question_type": question_type,
                "reason_code": reason,
                "source_system": str(source),
                "occurred_on": str(occurred_on),
                "merchant": str(merchant),
                "amount_krw": abs(int(amount)),
                "candidate_targets": targets,
                **({"question": question} if question else {}),
                "payment_count": 0,
                "approval_numbers": [],
                "payment_external_keys": [],
                "external_key_sample": [],
            })
            group["payment_count"] = int(group["payment_count"]) + 1
            group["payment_external_keys"].append(str(external_key))
            if str(approval or ""):
                group["approval_numbers"].append(str(approval))
            if len(group["external_key_sample"]) < 5:
                group["external_key_sample"].append(str(external_key))

    # These two closed-shape M:N cases are not ordinary target questions.  The
    # user can answer them once per group while the rest of the card scope is
    # still processed automatically.  FUKUTAKE is split by the card identity
    # carried in the current-card payload: rows from different cards are not
    # allowed to become one M:N relationship question.
    fuk = db.execute(
        """SELECT p.transaction_type,p.amount_krw,p.occurred_on,s.payload_json,
                          p.external_key
           FROM direct_payment_projection_links l
           JOIN payment_transactions p ON p.id=l.payment_id
           JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
           JOIN direct_source_records s ON s.id=d.source_record_id
           WHERE l.run_id=? AND p.source_system='KBO'
             AND upper(p.merchant) LIKE '%FUKUTAKE%'
           ORDER BY p.occurred_on,p.id""", (run_id,),
    ).fetchall()
    fuk_by_card: dict[tuple[str, str, str], list[tuple[object, ...]]] = defaultdict(list)
    for row in fuk:
        try:
            payload = json.loads(str(row[3] or "{}"))
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        card4 = str(payload.get("card4") or "unknown").strip() or "unknown"
        currency = str(payload.get("currency") or "").strip()
        fuk_by_card[(card4, currency, "KBO")].append(tuple(row))
    for (card4, currency, source_system), fuk_rows in sorted(fuk_by_card.items()):
        purchase_count = sum(str(row[0]) == "purchase" for row in fuk_rows)
        reversal_count = sum(
            str(row[0]) in {"cancellation", "refund"} for row in fuk_rows
        )
        if purchase_count and reversal_count:
            groups[("partial_refund_mn", "FUKUTAKE FOUNDATION", card4, currency)] = {
                "question_type": "partial_refund_mn",
                "question": "FUKUTAKE 환불 묶음을 같은 카드의 원결제 부분환불 관계로 등록할까요?",
                "merchant": "FUKUTAKE FOUNDATION",
                "source_system": source_system,
                "card4": card4,
                "currency": currency,
                "purchase_count": purchase_count,
                "refund_count": reversal_count,
                "terminal_exclusion": "전체상계가 아니므로 취소환불 비용제외로 처리하지 않음",
                "payment_count": len(fuk_rows),
                "payment_external_keys": sorted(str(row[4]) for row in fuk_rows),
                "external_key_sample": sorted(str(row[4]) for row in fuk_rows)[:5],
            }
    result = []
    for index, group in enumerate(sorted(
        groups.values(), key=lambda row: (
            str(row.get("question_type")), str(row.get("occurred_on", "")),
            str(row.get("merchant", "")), int(row.get("amount_krw", 0)),
        )
    ), start=1):
        result.append({"question_id": f"owner-question-{index:03d}", **group})
    return result


def _travel_unassigned_metadata_question_groups(
    db: object,
    run_id: str,
    reviews_by_payment: Mapping[int, tuple[object, ...]],
) -> list[dict[str, object]]:
    """Expose terminal travel-code gaps without stopping the cost pass.

    These rows already have the three cost axes classified as
    ``여행_미배정``. They are not transaction failures, but they still need a
    travel target when the service period or the underlying merchant is not in
    the card fact. This queue is separate from the smaller owner-decision queue
    so metadata questions can be answered while automatic processing continues.
    """
    payment_ids = sorted({
        payment_id for payment_id, review in reviews_by_payment.items()
        if str(review[1]) == "travel_unassigned"
        and str(review[2]) == "confirmed"
    })
    if not payment_ids:
        return []
    placeholders = ",".join("?" for _ in payment_ids)
    prediction_rows = db.execute(
        f"""SELECT payment_id,rule_path
            FROM direct_high_coverage_classifier_predictions
            WHERE run_id=? AND payment_id IN ({placeholders})
            ORDER BY payment_id,prediction_id""",
        (run_id, *payment_ids),
    ).fetchall()
    path_by_payment: dict[int, str] = {}
    for payment_id, rule_path in prediction_rows:
        parts = str(rule_path or "").split("|")
        if len(parts) >= 2 and str(parts[1]):
            path_by_payment[int(payment_id)] = str(parts[1])
    rows = db.execute(
        f"""SELECT p.id,p.external_key,p.source_system,p.occurred_on,
                   p.merchant,p.amount_krw,p.approval_number,
                   p.currency,p.foreign_amount
            FROM payment_transactions p
            JOIN direct_payment_projection_links l
              ON l.run_id=? AND l.payment_id=p.id
            WHERE p.id IN ({placeholders})
            ORDER BY p.occurred_on,p.id""",
        (run_id, *payment_ids),
    ).fetchall()
    groups: dict[tuple[object, ...], dict[str, object]] = {}
    for (
        payment_id, external_key, source, occurred_on, merchant, amount,
        approval, currency, foreign_amount,
    ) in rows:
        review = reviews_by_payment.get(int(payment_id), ())
        reason = str(review[4]) if review else "direct_full_axis_travel_unassigned"
        path = path_by_payment.get(int(payment_id), "")
        merchant_text = str(merchant or "(가맹점명 미상)")
        key = (reason, path, str(source), merchant_text)
        group = groups.setdefault(key, {
            "question_type": "travel_target_metadata",
            "reason_code": "travel_unassigned_metadata_owner_confirmation",
            "classification_path": path,
            "source_system": str(source),
            "merchant": merchant_text,
            "payment_count": 0,
            "amount_krw_total": 0,
            "amount_krw_sample": [],
            "foreign_amount_sample": [],
            "currency_sample": [],
            "approval_numbers": [],
            "occurred_on_min": str(occurred_on or ""),
            "occurred_on_max": str(occurred_on or ""),
            "payment_external_keys": [],
            "external_key_sample": [],
            "question": (
                "비용 분류는 끝났지만 행사일·숙박기간 또는 실제 가맹점이 없어 "
                "여행 코드를 아직 붙이지 못한 묶음입니다. 메일·예약 자료가 "
                "추가되면 자동 연결하고, 없으면 여행 코드를 지정해 주세요."
            ),
            "cost_axes_status": "account/cost_type/allocation_target=여행_미배정 확정",
        })
        group["payment_count"] = int(group["payment_count"]) + 1
        group["amount_krw_total"] = int(group["amount_krw_total"]) + abs(int(amount or 0))
        group["amount_krw_sample"] = sorted({
            *[int(value) for value in group["amount_krw_sample"]], abs(int(amount or 0))
        })[:5]
        if str(foreign_amount or ""):
            group["foreign_amount_sample"] = sorted({
                *[str(value) for value in group["foreign_amount_sample"]],
                str(foreign_amount),
            })[:5]
        if str(currency or ""):
            group["currency_sample"] = sorted({
                *[str(value) for value in group["currency_sample"]], str(currency),
            })[:5]
        if str(approval or "") and len(group["approval_numbers"]) < 5:
            group["approval_numbers"].append(str(approval))
        occurred = str(occurred_on or "")
        group["occurred_on_min"] = min(str(group["occurred_on_min"]), occurred)
        group["occurred_on_max"] = max(str(group["occurred_on_max"]), occurred)
        group["payment_external_keys"].append(str(external_key))
        if len(group["external_key_sample"]) < 5:
            group["external_key_sample"].append(str(external_key))
    result = []
    for index, group in enumerate(sorted(
        groups.values(), key=lambda row: (
            str(row.get("classification_path")),
            str(row.get("merchant")),
        )
    ), start=1):
        result.append({"question_id": f"travel-metadata-question-{index:03d}", **group})
    return result


def _allocation_decision_gate(
    db: object,
    run_id: str,
    *,
    require_current_projection_contract: bool = False,
) -> dict[str, object]:
    payments = db.execute(
        """
        SELECT
            p.id,
            p.external_key,
            p.amount_krw,
            d.card_event_id,
            d.event_role,
            e.source_system,
            d.transaction_type
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_card_events e ON e.source_record_id=d.source_record_id
        WHERE l.run_id=?
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    payment_by_id = {int(row[0]): row for row in payments}
    terminal_table_exists = bool(db.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='direct_2025_payment_terminals'"""
    ).fetchone())
    terminal_manifest_exists = bool(db.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='direct_2025_payment_terminal_manifests'"""
    ).fetchone())
    if terminal_table_exists and terminal_manifest_exists:
        terminal_validation = validate_2025_payment_terminals(db, run_id)
        terminal_payment_id_set = terminal_payment_ids(db, run_id)
        try:
            terminal_census = build_census(db, run_id)
        except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
            terminal_census = None
    else:
        # Backward-compatible read path for focused unit fixtures created
        # before the strict terminal schema existed.  Real direct runs always
        # apply the schema and therefore cannot use this escape hatch.
        terminal_validation = {
            "passed": True,
            "issues": [],
            "status": "legacy_no_2025_terminal_scope",
            "objective_met": True,
        }
        terminal_payment_id_set = set()
        terminal_census = None
    cost_table_exists = bool(db.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='direct_2025_cost_accounting'"""
    ).fetchone())
    cost_manifest_exists = bool(db.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='direct_2025_cost_accounting_manifests'"""
    ).fetchone())
    if cost_table_exists and cost_manifest_exists:
        cost_validation = validate_2025_cost_accounting(
            db,
            run_id,
            require_manifest=require_current_projection_contract,
        )
        cost_payment_id_set = cost_payment_ids(db, run_id)
    elif require_current_projection_contract:
        cost_validation = {
            "passed": False,
            "issues": ["2025_cost_manifest_missing"],
            "status": "current_projection_contract_missing",
            "payment_count": 0,
        }
        cost_payment_id_set = set()
    else:
        cost_validation = {
            "passed": True,
            "issues": [],
            "status": "legacy_no_2025_cost_scope",
            "payment_count": 0,
        }
        cost_payment_id_set = set()
    payment_occurred_on = {
        int(row[0]): str(row[1] or "")
        for row in db.execute(
            """SELECT p.id,p.occurred_on
               FROM payment_transactions p
               JOIN direct_payment_projection_links l
                 ON l.payment_id=p.id
               WHERE l.run_id=?""",
            (run_id,),
        ).fetchall()
    }
    promoted_rows = db.execute(
        """SELECT d.id,d.target_id,d.dimension,d.value,d.rule_id
           FROM current_independently_promoted_decisions d
           JOIN direct_payment_projection_links l
             ON l.run_id=d.run_id AND l.payment_id=d.target_id
           WHERE l.run_id=? AND d.target_type='payment'
             AND d.decision_status='confirmed'
             AND d.dimension IN ('account','cost_type','allocation_target')
           ORDER BY d.target_id,d.dimension,d.id""",
        (run_id,),
    ).fetchall()
    decisions_by_payment: dict[int, list[tuple[object, ...]]] = defaultdict(list)
    promoted_by_id: dict[int, tuple[object, ...]] = {}
    for row in promoted_rows:
        normalized = tuple(row)
        decisions_by_payment[int(row[1])].append(normalized)
        promoted_by_id[int(row[0])] = normalized
    confirmed_current_decision_payment_ids = {
        int(row[0])
        for row in db.execute(
            """SELECT DISTINCT d.target_id
               FROM current_classification_decisions d
               JOIN direct_payment_projection_links l
                 ON l.run_id=? AND l.payment_id=d.target_id
               WHERE d.target_type='payment'
                 AND d.decision_status='confirmed'
                 AND d.dimension IN ('account','cost_type','allocation_target')""",
            (run_id,),
        ).fetchall()
    }

    cost_provisional_guard = """
             AND NOT EXISTS (
               SELECT 1 FROM direct_2025_cost_accounting c
               WHERE c.run_id=b.run_id AND c.payment_id=d.target_id
             )""" if cost_table_exists else ""
    provisional_rows = db.execute(
        f"""SELECT d.id,d.target_id,d.dimension,d.value,d.rule_id,
                  p.prediction_id,p.rule_path,p.allocation_target,pt.transaction_type
           FROM direct_high_coverage_classifier_decision_bindings b
           JOIN classification_decisions d ON d.id=b.decision_id
           JOIN direct_high_coverage_classifier_axis_derivations x
             ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
           JOIN direct_high_coverage_classifier_predictions p
             ON p.run_id=x.run_id AND p.prediction_id=x.prediction_id
            AND p.payment_id=x.payment_id AND p.direct_event_key=x.direct_event_key
           JOIN direct_high_coverage_classifier_models m
             ON m.run_id=p.run_id AND m.model_id=p.model_id
           JOIN direct_promotion_evidence current_e
             ON current_e.run_id=x.run_id
            AND current_e.evidence_id=x.current_evidence_id
           JOIN direct_payment_projection_links l
             ON l.run_id=b.run_id AND l.payment_id=d.target_id
           JOIN payment_transactions pt ON pt.id=d.target_id
           JOIN direct_normalized_payments payment ON payment.id=l.direct_payment_id
           WHERE b.run_id=? AND d.target_type='payment'
             AND d.decision_status='needs_review'
             AND d.dimension IN ('account','cost_type','allocation_target')
             AND x.dimension=d.dimension AND x.value=d.value
             AND x.rule_id=d.rule_id AND x.derivation_status='pass'
             AND x.conflict_count=0 AND p.conflict_count=0
             AND m.validation_error_count=0 AND m.validation_count>0
             AND m.training_role='learning_only_not_transaction_evidence'
             AND current_e.evidence_kind='current_card'
             AND current_e.authority_status='current_raw'
             AND current_e.direct_event_key=payment.card_event_id || '#' || payment.event_role
             AND (
               instr(p.rule_path,'|manual_travel_tab_exact|')>0
               OR instr(p.rule_path,'|manual_travel_tab_mn_target_invariant|')>0
               OR instr(p.rule_path,'|manual_travel_tab_reversal_exact|')>0
               OR instr(p.rule_path,'|manual_travel_tab_reversal_mn_target_invariant|')>0
               OR instr(p.rule_path,'|current_card_geography_context_exact_2026|')>0
               OR instr(p.rule_path,'|current_card_trip_cluster_registry_exact|')>0
               OR instr(p.rule_path,'|current_card_travel_activity_placeholder|')>0
               OR instr(p.rule_path,'|current_card_reservation_placeholder|')>0
               OR instr(p.rule_path,'|current_card_reversal_provisional_inherit|')>0
               OR instr(p.rule_path,'|ota_mail_service_period_exact|')>0
               OR instr(p.rule_path,'|ota_mail_service_period_mn_target_invariant|')>0
               OR instr(p.rule_path,'|ota_mail_service_period_amount_tolerance_exact|')>0
               OR instr(p.rule_path,'|ota_mail_service_period_amount_tolerance_mn_target_invariant|')>0
               OR instr(p.rule_path,'|gmail_payment_service_period_evidence|')>0
               OR instr(p.rule_path,'|current_card_inferred_external_target|')>0
               OR instr(p.rule_path,'|current_card_foreign_use_date_schedule_overrides_manual_ambiguity|')>0
               OR instr(p.rule_path,'|foreign_service_period_pending_review|')>0
             )
             AND NOT EXISTS (
               SELECT 1 FROM direct_2025_payment_terminals t
               WHERE t.run_id=b.run_id AND t.payment_id=d.target_id
             )
             {cost_provisional_guard}
           ORDER BY d.target_id,d.dimension,d.id""",
        (run_id,),
    ).fetchall()
    provisional_by_payment: dict[int, list[tuple[object, ...]]] = defaultdict(list)
    for row in provisional_rows:
        provisional_by_payment[int(row[1])].append(tuple(row))
    provisional_inheritance_by_payment: dict[int, list[tuple[object, ...]]] = defaultdict(list)
    for row in db.execute(
        """SELECT reversal_payment_id,reversal_direct_event_key,
                  original_payment_id,original_prediction_id,relation_id,
                  relation_match_method,original_target,
                  original_prediction_sha256,link_sha256,inheritance_status
           FROM direct_high_coverage_reversal_inheritance
           WHERE run_id=? ORDER BY reversal_payment_id""",
        (run_id,),
    ).fetchall():
        provisional_inheritance_by_payment[int(row[0])].append(tuple(row))

    allocation_rows = db.execute(
        """SELECT a.payment_id,a.plan_id,a.amount_krw,a.allocation_status,
                  a.source_decision_id,t.code
           FROM current_cost_allocations a
           JOIN allocation_targets t ON t.id=a.target_id
           JOIN direct_payment_projection_links l
             ON l.payment_id=a.payment_id AND l.run_id=?
           WHERE a.allocation_status='confirmed'
           ORDER BY a.payment_id,a.plan_id,a.id""",
        (run_id,),
    ).fetchall()
    allocations_by_payment: dict[int, list[tuple[object, ...]]] = defaultdict(list)
    for row in allocation_rows:
        allocations_by_payment[int(row[0])].append(tuple(row))

    review_rows = db.execute(
        """SELECT r.payment_id,r.outcome,r.review_status,r.rule_id,r.reason_code
           FROM allocation_review_cases r
           JOIN direct_payment_projection_links l
             ON l.payment_id=r.payment_id AND l.run_id=?
           ORDER BY r.payment_id""",
        (run_id,),
    ).fetchall()
    reviews_by_payment = {
        int(row[0]): tuple(row)
        for row in review_rows
        if int(row[0]) not in terminal_payment_id_set
        and int(row[0]) not in cost_payment_id_set
    }
    owner_question_groups = _owner_confirmation_question_groups(
        db, run_id, reviews_by_payment,
    )
    valid_settlement_decision_ids = {
        int(row[0]) for row in db.execute(
            """SELECT b.decision_id
               FROM direct_cancellation_settlement_decision_bindings b
               JOIN direct_cancellation_settlement_derivations x
                 ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
               JOIN direct_cancellation_settlement_authorities a
                 ON a.run_id=x.run_id AND a.authority_id=x.authority_id
               JOIN direct_cancellation_settlement_members m
                 ON m.run_id=x.run_id AND m.authority_id=x.authority_id
                AND m.payment_id=x.payment_id
                AND m.direct_event_key=x.direct_event_key
               WHERE b.run_id=? AND x.dimension='allocation_target'
                 AND x.value='취소환불'
                 AND x.rule_id='current-card-net-zero-settlement-v1'
                 AND x.derivation_status='pass' AND x.conflict_count=0
                 AND a.member_count=a.purchase_count+a.reversal_count
                 AND a.purchase_count=a.reversal_count AND a.net_krw=0
                 AND a.account='비용제외' AND a.cost_type='비용제외'
                 AND a.allocation_target='취소환불'""",
            (run_id,),
        ).fetchall()
    }

    allocated_keys: set[str] = set()
    terminal_keys: set[str] = {
        str(payment_by_id[payment_id][1])
        for payment_id in terminal_payment_id_set
        if payment_id in payment_by_id
    }
    structural_admitted_terminal_keys: set[str] = set()
    provisional_keys: set[str] = set()
    provisional_trip_keys: set[str] = set()
    auto_provisional_keys: set[str] = set()
    auto_provisional_trip_keys: set[str] = set()
    auto_provisional_action_keys: set[str] = set()
    out_of_scope_auto_provisional_action_keys: set[str] = set()
    named_auto_target_keys: set[str] = set()
    named_auto_target_trip_keys: set[str] = set()
    provisional_path_counts: dict[str, int] = defaultdict(int)
    auto_provisional_queue_counts: dict[tuple[str, str], int] = defaultdict(int)
    named_auto_target_queue_counts: dict[tuple[str, str], int] = defaultdict(int)
    ambiguous_review_keys: set[str] = set()
    travel_unassigned_keys: set[str] = set()
    partial_rows: list[tuple[str, int]] = []
    full_axis_rows: list[tuple[str, int]] = []
    cancellation_axes = {
        "account": "비용제외",
        "cost_type": "비용제외",
        "allocation_target": "취소환불",
    }
    provisional_plan_payment_ids = {
        int(row[0]) for row in db.execute(
            """SELECT DISTINCT ap.payment_id
               FROM allocation_plans ap
               JOIN direct_payment_projection_links l
                 ON l.run_id=? AND l.payment_id=ap.payment_id""",
            (run_id,),
        ).fetchall()
    }
    provisional_posting_payment_ids = {
        int(row[0]) for row in db.execute(
            """SELECT DISTINCT ap.payment_id
               FROM journal_entries j
               JOIN cost_allocations ca ON ca.id=j.allocation_id
               JOIN allocation_plans ap ON ap.id=ca.plan_id
               JOIN direct_payment_projection_links l
                 ON l.run_id=? AND l.payment_id=ap.payment_id""",
            (run_id,),
        ).fetchall()
    }
    provisional_reversal_derived_payment_ids = {
        int(row[0]) for row in db.execute(
            """SELECT DISTINCT d.payment_id
               FROM direct_cancellation_settlement_derivations d
               JOIN direct_payment_projection_links l
                 ON l.run_id=d.run_id AND l.payment_id=d.payment_id
               WHERE d.run_id=?""",
            (run_id,),
        ).fetchall()
    }
    try:
        from ledger.domain.direct_geographic_trip_context import (
            load_verified_trip_target_schedule,
        )
        valid_context_trip_codes = set(load_verified_trip_target_schedule(db))
    except (ValueError, sqlite3.Error):
        valid_context_trip_codes = set()
    registry_rows = db.execute(
        """SELECT registry_id,target_code,registry_sha256,registry_status,
                  target_kind,source_system,card_identity_sha256,country,
                  region,starts_on,ends_on
           FROM direct_high_coverage_trip_registries
           WHERE run_id=? ORDER BY registry_id""",
        (run_id,),
    ).fetchall()
    registry_by_target: dict[str, list[tuple[object, ...]]] = defaultdict(list)
    for row in registry_rows:
        registry_by_target[str(row[1])].append(tuple(row))
    registry_member_keys = {
        (str(row[0]), int(row[1])) for row in db.execute(
            """SELECT registry_id,payment_id
               FROM direct_high_coverage_trip_registry_members
               WHERE run_id=?""",
            (run_id,),
        ).fetchall()
    }
    for (
        registry_id, target_code, registry_sha256, registry_status,
        target_kind, source_system, card_identity_sha256, country, region,
        starts_on, ends_on,
    ) in registry_rows:
        registry_payload = db.execute(
            """SELECT payload_json,event_set_sha256,fact_set_sha256
               FROM direct_high_coverage_trip_registries
               WHERE run_id=? AND registry_id=?""",
            (run_id, registry_id),
        ).fetchone()
        members = db.execute(
            """SELECT payment_id,direct_event_key,current_evidence_id,
                      current_fact_sha256
               FROM direct_high_coverage_trip_registry_members
               WHERE run_id=? AND registry_id=? ORDER BY direct_event_key""",
            (run_id, registry_id),
        ).fetchall()
        payload_obj: object | None = None
        payload_core_valid = False
        payload_core_fields_valid = False
        payload_full_valid = False
        payload_audit_valid = False
        if registry_payload is not None:
            try:
                payload_obj = json.loads(str(registry_payload[0]))
            except (TypeError, json.JSONDecodeError):
                payload_obj = None
        if isinstance(payload_obj, dict) and isinstance(
            payload_obj.get("registry_core"), dict
        ):
            payload_full_valid = (
                _sha256_bytes(_canonical_json_bytes(payload_obj))
                == str(registry_sha256)
            )
            core = dict(payload_obj["registry_core"])
            expected_core = {
                "registry_version": core.get("registry_version"),
                "rule_id": core.get("rule_id"),
                "source_system": core.get("source_system"),
                "card_identity_sha256": core.get("card_identity_sha256"),
                "country": core.get("country"),
                "region": core.get("region"),
                "starts_on": core.get("starts_on"),
                "ends_on": core.get("ends_on"),
                "target_code": core.get("target_code"),
                "event_keys": sorted(
                    str(item) for item in core.get("event_keys", [])
                ),
                "fact_shas": sorted(
                    str(item) for item in core.get("fact_shas", [])
                ),
                "target_kind": core.get("target_kind"),
            }
            if "selection_context_sha256" in core:
                expected_core["selection_context_sha256"] = core.get(
                    "selection_context_sha256"
                )
            payload_core_fields_valid = (
                str(expected_core["target_code"]) == str(target_code)
                and str(expected_core["target_kind"]) == str(target_kind)
                and str(expected_core["source_system"]) == str(source_system)
                and str(expected_core["card_identity_sha256"])
                == str(card_identity_sha256)
                and str(expected_core["country"]) == str(country)
                and str(expected_core["region"]) == str(region)
                and str(expected_core["starts_on"]) == str(starts_on)
                and str(expected_core["ends_on"]) == str(ends_on)
                and expected_core["event_keys"]
                == sorted(str(row[1]) for row in members)
                and expected_core["fact_shas"]
                == sorted(str(row[3]) for row in members)
            )
            payload_core_valid = (
                _sha256_bytes(_canonical_json_bytes(expected_core))
                == str(registry_sha256)
                and payload_core_fields_valid
            )
            audit = payload_obj.get("audit")
            selection_context = (
                audit.get("selection_context")
                if isinstance(audit, dict)
                else None
            )
            selection_context_sha256 = (
                audit.get("selection_context_sha256")
                if isinstance(audit, dict)
                else None
            )
            selection_context_valid = (
                (
                    "selection_context_sha256" not in expected_core
                    and selection_context is None
                    and selection_context_sha256 is None
                )
                or (
                    "selection_context_sha256" in expected_core
                    and isinstance(selection_context, dict)
                    and _sha256_bytes(_canonical_json_bytes(selection_context))
                    == str(expected_core["selection_context_sha256"])
                    and str(selection_context_sha256)
                    == str(expected_core["selection_context_sha256"])
                )
            )
            audit_members = (
                audit.get("member_audit")
                if isinstance(audit, dict)
                else None
            )
            expected_member_audit = [
                {
                    "payment_id": int(row[0]),
                    "direct_event_key": str(row[1]),
                    "current_evidence_id": str(row[2]),
                    "current_fact_sha256": str(row[3]),
                }
                for row in members
            ]
            audit_member_keys: list[dict[str, object]] = []
            audit_member_shape_valid = isinstance(audit_members, list)
            if audit_member_shape_valid:
                for item in audit_members:
                    if not isinstance(item, dict):
                        audit_member_shape_valid = False
                        break
                    try:
                        audit_member_keys.append({
                            "payment_id": int(item["payment_id"]),
                            "direct_event_key": str(item["direct_event_key"]),
                            "current_evidence_id": str(item["current_evidence_id"]),
                            "current_fact_sha256": str(item["current_fact_sha256"]),
                        })
                    except (KeyError, TypeError, ValueError):
                        audit_member_shape_valid = False
                        break
            try:
                audit_member_count = int(audit.get("member_count", -1)) if isinstance(audit, dict) else -1
            except (TypeError, ValueError):
                audit_member_count = -1
            payload_audit_valid = (
                isinstance(audit, dict)
                and audit.get("individual_match_asserted") is False
                and audit.get("payment_window_is_not_service_period") is True
                and audit_member_count == len(members)
                and audit_member_shape_valid
                and audit_member_keys == expected_member_audit
                and selection_context_valid
            )
            if str(target_kind) == INFERRED_EXTERNAL_TARGET_KIND:
                candidate_targets = (
                    audit.get("candidate_target_set")
                    if isinstance(audit, dict)
                    else None
                )
                candidate_target_hash_valid = (
                    isinstance(candidate_targets, list)
                    and all(isinstance(item, str) and item for item in candidate_targets)
                    and _sha256_bytes(_canonical_json_bytes(candidate_targets))
                    == str(audit.get("candidate_target_set_sha256"))
                    if isinstance(audit, dict)
                    else False
                )
                audit_event_keys = (
                    sorted(str(item) for item in audit.get("member_event_keys", []))
                    if isinstance(audit, dict)
                    and isinstance(audit.get("member_event_keys"), list)
                    else []
                )
                audit_fact_shas = (
                    sorted(str(item) for item in audit.get("member_fact_shas", []))
                    if isinstance(audit, dict)
                    and isinstance(audit.get("member_fact_shas"), list)
                    else []
                )
                inferred_audit_valid = (
                    isinstance(audit, dict)
                    and payload_full_valid
                    and audit.get("classification_path") == INFERRED_EXTERNAL_TARGET_PATH
                    and candidate_target_hash_valid
                    and audit_event_keys == expected_core["event_keys"]
                    and audit_fact_shas == expected_core["fact_shas"]
                    and _sha256_bytes(_canonical_json_bytes(audit_fact_shas))
                    == str(audit.get("member_fact_set_sha256"))
                    and isinstance(audit.get("source_records"), list)
                    and all(isinstance(item, dict) for item in audit["source_records"])
                    and isinstance(audit.get("match_methods"), list)
                    and all(isinstance(item, str) and item for item in audit["match_methods"])
                    and audit.get("individual_match_asserted") is False
                    and audit.get("relation_asserted") is False
                    and audit.get("payment_window_is_not_service_period") is True
                    and audit.get("direct_promotion_evidence_registered") is False
                    and audit.get("allocation_or_plan_created") is False
                )
                payload_audit_valid = inferred_audit_valid
        if (
            str(registry_status) != "provisional"
            or registry_payload is None
            or (
                not payload_core_valid
                and _sha256_bytes(str(registry_payload[0]).encode("utf-8"))
                != str(registry_sha256)
            )
            or (
                str(target_kind) in {
                    "activity_placeholder", "reservation_placeholder",
                }
                and (not payload_core_valid or not payload_audit_valid)
            )
            or (
                str(target_kind) == INFERRED_EXTERNAL_TARGET_KIND
                and (
                    not payload_full_valid
                    or not payload_core_fields_valid
                    or not payload_audit_valid
                )
            )
            or str(registry_id) != "trip-cluster:" + str(registry_sha256)
            or _sha256_bytes(_canonical_json_bytes(
                sorted(str(row[1]) for row in members)
            )) != str(registry_payload[1])
            or _sha256_bytes(_canonical_json_bytes(
                sorted(str(row[3]) for row in members)
            )) != str(registry_payload[2])
        ):
            raise ValueError("direct_trip_registry_tampered_or_stale")
    valid_provisional_trip_codes = (
        valid_context_trip_codes
        | set(registry_by_target)
    )
    for payment_id, payment in payment_by_id.items():
        external_key = str(payment[1])
        decisions = decisions_by_payment.get(payment_id, [])
        partial_count = sum(
            str(row[2]) in {"account", "cost_type"} for row in decisions
        )
        if partial_count == 2:
            partial_rows.append((external_key, partial_count))
        if len(decisions) == 3:
            full_axis_rows.append((external_key, 3))

        allocations = allocations_by_payment.get(payment_id, [])
        if len(decisions) == 3 and allocations:
            plans = {int(row[1]) for row in allocations}
            allocated_total = sum(int(row[2]) for row in allocations)
            bindings_valid = True
            for allocation in allocations:
                source_decision_id = allocation[4]
                decision = (
                    None if source_decision_id is None
                    else promoted_by_id.get(int(source_decision_id))
                )
                if (
                    decision is None
                    or int(decision[1]) != payment_id
                    or str(decision[2]) != "allocation_target"
                    or str(decision[3]) != str(allocation[5])
                ):
                    bindings_valid = False
                    break
            if (
                len(plans) == 1
                and allocated_total == int(payment[2])
                and bindings_valid
            ):
                allocated_keys.add(external_key)

        review = reviews_by_payment.get(payment_id)
        target_decisions = [
            row for row in decisions if str(row[2]) == "allocation_target"
        ]
        if (
            len(decisions) == 3
            and len(target_decisions) == 1
            and review is not None
            and str(review[2]) == "confirmed"
        ):
            target_decision = target_decisions[0]
            target_rule = str(target_decision[4] or "")
            outcome = str(review[1])
            review_rule = str(review[3] or "")
            if target_rule and review_rule == target_rule:
                if outcome == "overhead" and str(target_decision[3]) == "기타비용":
                    terminal_keys.add(external_key)
                elif (
                    outcome == "travel_unassigned"
                    and str(target_decision[3]) == "여행_미배정"
                ):
                    terminal_keys.add(external_key)
                    travel_unassigned_keys.add(external_key)
                elif outcome == "cancellation_settlement":
                    axes = {
                        str(row[2]): str(row[3]) for row in decisions
                    }
                    same_rule = all(str(row[4] or "") == target_rule for row in decisions)
                    if (
                        axes == cancellation_axes
                        and same_rule
                        and target_rule == "current-card-net-zero-settlement-v1"
                        and int(target_decision[0]) in valid_settlement_decision_ids
                    ):
                        terminal_keys.add(external_key)
                elif outcome == "structural_rule_admitted":
                    if (
                        allocations
                        or payment_id in provisional_plan_payment_ids
                        or payment_id in provisional_posting_payment_ids
                        or payment_id in provisional_reversal_derived_payment_ids
                    ):
                        raise ValueError(
                            "direct_structural_rule_admission_side_effect"
                        )
                    prediction_row = db.execute(
                        """SELECT rule_path,axis_evidence_json
                           FROM direct_high_coverage_classifier_predictions
                           WHERE run_id=? AND payment_id=?""",
                        (run_id, payment_id),
                    ).fetchone()
                    admission_valid = False
                    if prediction_row is not None:
                        path_parts = str(prediction_row[0] or "").split("|")
                        path = path_parts[1] if len(path_parts) > 1 else ""
                        try:
                            payload = json.loads(str(prediction_row[1]))
                        except (TypeError, json.JSONDecodeError):
                            payload = None
                        finality = (
                            payload.get("row_finality")
                            if isinstance(payload, dict)
                            else None
                        )
                        contract = (
                            payload.get("finality_contract")
                            if isinstance(payload, dict)
                            else None
                        )
                        admission = (
                            contract.get("structural_rule_admission")
                            if isinstance(contract, dict)
                            else None
                        )
                        admission_valid = bool(
                            isinstance(finality, dict)
                            and finality.get("eligible") is True
                            and finality.get("status") == "final_eligible"
                            and finality.get("vetoes") == []
                            and finality.get("structural_rule_admitted") is True
                            and isinstance(admission, dict)
                            and admission.get("contract")
                            == "structural-rule-admission-v1"
                            and path in admission.get("admitted_paths", [])
                            and admission.get("relationship_question_overlap")
                            == "allowed_without_inheritance"
                            and str(review[4])
                            == "structural_rule_admitted_no_allocation"
                            and str(target_decision[3])
                            not in {"여행_미배정", "기타비용", "취소환불"}
                        )
                    if not admission_valid:
                        raise ValueError(
                            "direct_structural_rule_admission_contract_invalid"
                        )
                    terminal_keys.add(external_key)
                    structural_admitted_terminal_keys.add(external_key)

        provisional = provisional_by_payment.get(payment_id, [])
        if provisional:
            prediction_ids = {str(row[5]) for row in provisional}
            paths = {str(row[6]).split("|", 1)[1].split("|", 1)[0]
                     for row in provisional}
            dimensions = {str(row[2]) for row in provisional}
            rules = {str(row[4]) for row in provisional}
            target_decisions = [
                row for row in provisional
                if str(row[2]) == "allocation_target"
            ]
            pending_unassigned_path = (
                paths == {"foreign_service_period_pending_review"}
                and len(target_decisions) == 1
                and str(target_decisions[0][7]) == "여행_미배정"
            )
            if paths == {"current_card_reversal_provisional_inherit"}:
                links = provisional_inheritance_by_payment.get(payment_id, [])
                if len(links) != 1:
                    raise ValueError("direct_provisional_reversal_link_missing")
                link = links[0]
                if (
                    str(link[1]) != f"{payment[3]}#{payment[4]}"
                    or int(link[2]) <= 0
                    or str(link[9]) != "provisional"
                ):
                    raise ValueError("direct_provisional_reversal_link_invalid")
                relation_count = int(db.execute(
                    """SELECT COUNT(*) FROM transaction_relations
                       WHERE id=? AND transaction_id=?
                         AND related_transaction_id=?
                         AND relation_status NOT IN ('rejected','superseded')""",
                    (int(link[4]), payment_id, int(link[2])),
                ).fetchone()[0])
                if relation_count != 1:
                    raise ValueError("direct_provisional_reversal_relation_invalid")
            elif provisional_inheritance_by_payment.get(payment_id):
                raise ValueError("direct_provisional_reversal_link_orphaned")
            if (
                str(payment[6]) not in {"purchase", "cancellation", "refund"}
                or decisions
                or len(provisional) != 3
                or len(prediction_ids) != 1
                or dimensions != {"account", "cost_type", "allocation_target"}
                or len(rules) != 1
                or paths not in (
                    {"manual_travel_tab_exact"},
                    {"manual_travel_tab_mn_target_invariant"},
                    {"manual_travel_tab_reversal_exact"},
                    {"manual_travel_tab_reversal_mn_target_invariant"},
                    {"current_card_geography_context_exact_2026"},
                    {"current_card_trip_cluster_registry_exact"},
                    {"current_card_travel_activity_placeholder"},
                    {"current_card_reservation_placeholder"},
                    {"current_card_reversal_provisional_inherit"},
                    {"ota_mail_service_period_exact"},
                    {"ota_mail_service_period_mn_target_invariant"},
                    {"ota_mail_service_period_amount_tolerance_exact"},
                    {"ota_mail_service_period_amount_tolerance_mn_target_invariant"},
                    {GMAIL_PAYMENT_SERVICE_PERIOD_PATH},
                    {FOREIGN_USE_DATE_SCHEDULE_PATH},
                    {"foreign_service_period_pending_review"},
                    {INFERRED_EXTERNAL_TARGET_PATH},
                )
                or len(target_decisions) != 1
                or (
                    str(target_decisions[0][7]) not in valid_provisional_trip_codes
                    and not pending_unassigned_path
                )
                or (
                    str(target_decisions[0][7]) in {
                    "여행_미배정", "기타비용", "취소환불",
                    }
                    and not pending_unassigned_path
                )
                or allocations
                or payment_id in provisional_plan_payment_ids
                or payment_id in provisional_posting_payment_ids
                or payment_id in provisional_reversal_derived_payment_ids
                or (
                    paths in (
                        {"current_card_trip_cluster_registry_exact"},
                        {"current_card_travel_activity_placeholder"},
                        {"current_card_reservation_placeholder"},
                    )
                    and (
                        len(registry_by_target.get(
                            str(target_decisions[0][7]), []
                        )) != 1
                        or (
                            str(registry_by_target[
                                str(target_decisions[0][7])
                            ][0][0]), payment_id
                        ) not in registry_member_keys
                    )
                )
            ):
                raise ValueError("direct_provisional_partition_contract_invalid")
            review = reviews_by_payment.get(payment_id)
            target_rule = str(target_decisions[0][4])
            review_status = str(review[2]) if review is not None else ""
            expected_reason = (
                "foreign_service_period_pending_owner_confirmation"
                if pending_unassigned_path
                else "provisional_travel_target_metadata_enrichment"
                if review_status == AUTO_PROVISIONAL_REVIEW_STATUS
                else "provisional_travel_target_owner_confirmation"
            )
            expected_outcome = (
                "travel_unassigned" if pending_unassigned_path else "trip"
            )
            if (
                review is None
                or str(review[1]) != expected_outcome
                or review_status not in {
                    OWNER_CONFIRMATION_REVIEW_STATUS,
                    AUTO_PROVISIONAL_REVIEW_STATUS,
                }
                or str(review[3]) != target_rule
                or str(review[4]) != expected_reason
            ):
                raise ValueError("direct_provisional_review_contract_invalid")
            if review_status == AUTO_PROVISIONAL_REVIEW_STATUS:
                auto_provisional_keys.add(external_key)
                auto_provisional_trip_keys.add(external_key)
                named_auto_target_keys.add(external_key)
                named_auto_target_trip_keys.add(external_key)
                is_action_required = _unknown_service_period_reservation(paths)
                if is_action_required:
                    if _current_assignment_queue_in_scope(
                        payment_occurred_on.get(payment_id)
                    ):
                        auto_provisional_action_keys.add(external_key)
                    else:
                        out_of_scope_auto_provisional_action_keys.add(
                            external_key
                        )
                for path in paths:
                    queue_key = (path, str(target_decisions[0][7]))
                    if is_action_required:
                        if external_key in auto_provisional_action_keys:
                            auto_provisional_queue_counts[queue_key] += 1
                        else:
                            named_auto_target_queue_counts[queue_key] += 1
                    else:
                        named_auto_target_queue_counts[queue_key] += 1
            elif pending_unassigned_path:
                # The pending-service-period path is already represented by
                # the explicit owner-review lane below.  Do not also count it
                # as an ordinary provisional trip row.
                pass
            else:
                provisional_keys.add(external_key)
                provisional_trip_keys.add(external_key)
            for path in paths:
                provisional_path_counts[path] += 1

    if allocated_keys & terminal_keys:
        raise ValueError("direct_allocation_terminal_overlap")
    if (
        allocated_keys & provisional_keys
        or terminal_keys & provisional_keys
        or allocated_keys & terminal_keys
        or allocated_keys & auto_provisional_keys
        or terminal_keys & auto_provisional_keys
        or provisional_keys & auto_provisional_keys
    ):
        raise ValueError("direct_gate5_partition_overlap")
    ambiguous_review_keys = {
        str(payment_by_id[payment_id][1])
        for payment_id, review in reviews_by_payment.items()
        if str(review[2]) == "needs_review"
        and str(review[1]) == "travel_unassigned"
        and str(review[4]) in {
            "manual_travel_tab_ambiguous_owner_confirmation",
            "manual_geography_conflict_owner_confirmation",
            "gmail_service_period_unverified_owner_confirmation",
            "gmail_approval_family_not_singleton_owner_confirmation",
            "domestic_gateway_purpose_owner_confirmation",
            "foreign_service_period_pending_owner_confirmation",
            "row_finality_veto_owner_confirmation",
        }
    }
    excluded_quarantine_keys: set[str] = set()
    if isinstance(terminal_census, dict):
        category_keys = terminal_census.get("category_keys", {})
        excluded_keys = set(category_keys.get("excluded", set()))
        excluded_quarantine_keys = excluded_keys - (
            allocated_keys
            | terminal_keys
            | provisional_keys
            | auto_provisional_keys
            | ambiguous_review_keys
        )
    resolved_keys = allocated_keys | terminal_keys
    # An explicit ambiguous owner-review case is a complete partition
    # disposition, but it is not resolved and must keep Gate5 open until the
    # owner chooses a target.
    partition_keys = (
        resolved_keys
        | provisional_keys
        | auto_provisional_keys
        | ambiguous_review_keys
        | excluded_quarantine_keys
    )
    resolved = len(resolved_keys)
    # A lossless partition is not the same thing as a final decision.  The
    # old implementation reported ``unresolved_count=0`` whenever every row
    # had entered a queue, even when thousands of those rows were still
    # auto-provisional.  Keep the partition gap and final-resolution counts
    # separate so Gate 5 cannot hide non-final work.
    partition_gap_rows = [
        row for row in payments if str(row[1]) not in partition_keys
    ]
    partition_gap_count = len(partition_gap_rows)
    if len(partition_keys) + partition_gap_count != len(payments):
        raise ValueError("direct_gate5_partition_incomplete")
    nonfinal_keys = set(partition_keys) - resolved_keys
    nonfinal_keys.update(str(row[1]) for row in partition_gap_rows)
    nonfinal_count = len(nonfinal_keys)
    payment_id_by_external_key = {
        str(row[1]): int(row[0]) for row in payments
    }
    nonfinal_payment_ids = {
        payment_id_by_external_key[key] for key in nonfinal_keys
    }
    nonfinal_plan_payment_ids = (
        provisional_plan_payment_ids & nonfinal_payment_ids
    )
    nonfinal_allocation_payment_ids = (
        set(allocations_by_payment) & nonfinal_payment_ids
    )
    nonfinal_journal_payment_ids = (
        provisional_posting_payment_ids & nonfinal_payment_ids
    )
    nonfinal_reversal_derivation_payment_ids = (
        provisional_reversal_derived_payment_ids & nonfinal_payment_ids
    )
    nonfinal_reversal_inheritance_payment_ids: set[int] = set()
    for reversal_payment_id, links in provisional_inheritance_by_payment.items():
        for link in links:
            original_payment_id = int(link[2])
            if (
                reversal_payment_id in nonfinal_payment_ids
                or original_payment_id in nonfinal_payment_ids
            ):
                nonfinal_reversal_inheritance_payment_ids.update(
                    {reversal_payment_id, original_payment_id}
                    & nonfinal_payment_ids
                )
    nonfinal_confirmed_decision_payment_ids = (
        confirmed_current_decision_payment_ids & nonfinal_payment_ids
    )
    nonfinal_side_effect_invariant = not any(
        (
            nonfinal_plan_payment_ids,
            nonfinal_allocation_payment_ids,
            nonfinal_journal_payment_ids,
            nonfinal_reversal_derivation_payment_ids,
            nonfinal_reversal_inheritance_payment_ids,
            nonfinal_confirmed_decision_payment_ids,
        )
    )
    terminal_plan_payment_ids = (
        provisional_plan_payment_ids & terminal_payment_id_set
    )
    terminal_allocation_payment_ids = (
        set(allocations_by_payment) & terminal_payment_id_set
    )
    terminal_journal_payment_ids = (
        provisional_posting_payment_ids & terminal_payment_id_set
    )
    terminal_reversal_derivation_payment_ids = (
        provisional_reversal_derived_payment_ids & terminal_payment_id_set
    )
    terminal_reversal_inheritance_payment_ids: set[int] = set()
    for reversal_payment_id, links in provisional_inheritance_by_payment.items():
        if reversal_payment_id not in terminal_payment_id_set:
            continue
        terminal_reversal_inheritance_payment_ids.add(reversal_payment_id)
    terminal_confirmed_decision_payment_ids = (
        confirmed_current_decision_payment_ids & terminal_payment_id_set
    )
    terminal_side_effect_invariant = not any(
        (
            terminal_plan_payment_ids,
            terminal_allocation_payment_ids,
            terminal_journal_payment_ids,
            terminal_reversal_derivation_payment_ids,
            terminal_reversal_inheritance_payment_ids,
            terminal_confirmed_decision_payment_ids,
        )
    )
    # Finality is separate from having three populated axes.  A high-coverage
    # prediction carries hard vetoes for provisional paths, incomplete OTA
    # lifecycles, unsafe M:N cardinalities, and weak reversal inheritance.
    finality_invalid_keys: list[str] = []
    try:
        finality_rows = db.execute(
            """SELECT payment_id,rule_path,allocation_target,axis_evidence_json
               FROM direct_high_coverage_classifier_predictions
               WHERE run_id=? ORDER BY payment_id""",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        finality_rows = []
    finality_by_payment: dict[int, tuple[object, ...]] = {
        int(row[0]): tuple(row) for row in finality_rows
    }
    resolved_payment_ids = {
        payment_id for payment_id, payment in payment_by_id.items()
        if str(payment[1]) in resolved_keys
    }
    for payment_id in sorted(resolved_payment_ids):
        if payment_id in terminal_payment_id_set:
            # A display terminal is intentionally not subject to the normal
            # three-axis row-finality predicate.  Its own contract is checked
            # above; applying the classifier veto here would incorrectly turn
            # a safe terminal into a false finality bypass failure.
            continue
        if payment_id in cost_payment_id_set:
            # The approved 2025-cost rule intentionally converts the row to
            # an accounting disposition.  Its travel finality veto remains
            # true and must not invalidate the separate accounting result.
            continue
        prediction = finality_by_payment.get(payment_id)
        if prediction is None:
            continue
        try:
            axis_payload = json.loads(str(prediction[3]))
        except (TypeError, json.JSONDecodeError):
            finality_invalid_keys.append(str(payment_by_id[payment_id][1]))
            continue
        finality = (
            axis_payload.get("row_finality")
            if isinstance(axis_payload, dict)
            else None
        )
        if not isinstance(finality, dict) or (
            finality.get("eligible") is not True
            or finality.get("status") != "final_eligible"
            or finality.get("vetoes") != []
        ):
            finality_invalid_keys.append(str(payment_by_id[payment_id][1]))
    structural_rule_requests = build_structural_rule_request_report(
        [
            {
                "payment_id": int(row[0]),
                "rule_path": str(row[1]),
                "allocation_target": str(row[2]),
                "axis_evidence_json": row[3],
            }
            for row in finality_rows
        ],
        nonfinal_payment_ids,
    )
    relationship_question_keys = {
        str(key)
        for group in owner_question_groups
        if str(group.get("question_type")) in {
            "mn_duplicate_or_double_charge", "partial_refund_mn",
        }
        for key in group.get("payment_external_keys", [])
    }
    # Package-b may explicitly close a grouped structural exception without
    # creating a reversal inheritance or financial allocation.  Such rows are
    # no longer an outstanding relationship question in this run.
    relationship_question_keys -= structural_admitted_terminal_keys
    owner_question_payment_keys = {
        str(key)
        for group in owner_question_groups
        for key in group.get("payment_external_keys", [])
    }
    partial_refund_question_keys = {
        str(key)
        for group in owner_question_groups
        if str(group.get("question_type")) == "partial_refund_mn"
        for key in group.get("payment_external_keys", [])
    }
    partial_refund_question_keys -= structural_admitted_terminal_keys
    if relationship_question_keys & resolved_keys:
        finality_invalid_keys.extend(
            sorted(relationship_question_keys & resolved_keys)
        )
    # Automatic follow-up rows are not individual human questions.  Keep the
    # human lane separate; the mutually exclusive lane calculation below
    # subtracts any grouped question rows from the automatic population.
    action_required_keys: set[str] = set()
    queue_partition_invariant = (
        auto_provisional_action_keys <= auto_provisional_keys
        and nonfinal_count == (
            len(auto_provisional_keys)
            + len(provisional_keys)
            + len(ambiguous_review_keys)
            + len(excluded_quarantine_keys)
            + partition_gap_count
        )
        and partial_refund_question_keys <= nonfinal_keys
        and relationship_question_keys <= nonfinal_keys
        and action_required_keys <= nonfinal_keys
    )
    finality_invalid_keys = sorted(set(finality_invalid_keys))
    partial_rows.sort()
    full_axis_rows.sort()
    scope = _direct_event_role_scope(
        [
            {
                "external_key": row[1],
                "card_event_id": row[3],
                "event_role": row[4],
                "source_system": row[5],
                "transaction_type": row[6],
            }
            for row in payments
        ]
    )
    lodging_scope = int(db.execute(
        """SELECT COUNT(*) FROM direct_source_records
           WHERE source_kind='ota_lodging_fact'
             AND redaction_version='no_subject_body_name_pin_recipient_or_address_text'"""
    ).fetchone()[0])
    if lodging_scope:
        try:
            from ledger.domain.direct_verified_ota_lodging import (
                validate_lodging_authorities,
                validate_lodging_manifest,
            )
            lodging_validation = validate_lodging_authorities(
                db, run_id, require_allocations=True,
            )
            lodging_manifest_validation = validate_lodging_manifest(db, run_id)
        except (ValueError, sqlite3.Error) as exc:
            lodging_validation = {"passed": False, "issues": [str(exc)]}
            lodging_manifest_validation = {"passed": False, "issues": [str(exc)]}
    else:
        lodging_validation = {
            "passed": True, "issues": [], "status": "no_typed_lodging_scope",
        }
        lodging_manifest_validation = {
            "passed": True, "issues": [], "status": "no_typed_lodging_scope",
        }
    ota_reservation_scope = int(db.execute(
        """SELECT COUNT(*) FROM direct_source_records
           WHERE source_kind='ota_reservation_fact'
             AND trim(payload_json) NOT IN ('', '{}', 'null')"""
    ).fetchone()[0])
    if ota_reservation_scope:
        try:
            from ledger.domain.direct_ota_reservation_authority import (
                validate_ota_reservation_authority,
            )
            ota_reservation_validation = validate_ota_reservation_authority(
                db, run_id, require_allocations=True,
            )
        except (ValueError, sqlite3.Error) as exc:
            ota_reservation_validation = {"passed": False, "issues": [str(exc)]}
    else:
        ota_reservation_validation = {
            "passed": True, "issues": [], "status": "no_ota_reservation_scope",
        }
    settlement_scope = int(db.execute(
        """SELECT COUNT(*) FROM direct_promotion_evidence
           WHERE run_id=? AND evidence_kind='current_card'
             AND authority_status='current_raw'""",
        (run_id,),
    ).fetchone()[0])
    if settlement_scope:
        try:
            from ledger.domain.direct_current_cancellation_settlement import (
                validate_cancellation_settlement_authorities,
                validate_cancellation_settlement_manifest,
            )
            settlement_validation = validate_cancellation_settlement_authorities(
                db, run_id, require_terminal=True,
            )
            settlement_manifest_validation = (
                validate_cancellation_settlement_manifest(db, run_id)
            )
        except (ValueError, sqlite3.Error) as exc:
            settlement_validation = {"passed": False, "issues": [str(exc)]}
            settlement_manifest_validation = {
                "passed": False, "issues": [str(exc)],
            }
    else:
        settlement_validation = {
            "passed": True, "issues": [], "status": "no_current_card_scope",
        }
        settlement_manifest_validation = {
            "passed": True, "issues": [], "status": "no_current_card_scope",
        }
    classifier_scope = int(db.execute(
        """SELECT COUNT(*) FROM direct_validated_classifier_models
           WHERE run_id=?""",
        (run_id,),
    ).fetchone()[0])
    if classifier_scope:
        try:
            from ledger.domain.direct_validated_purchase_classifier import (
                validate_validated_purchase_classifier,
            )
            classifier_validation = validate_validated_purchase_classifier(
                db, run_id, require_allocations=True,
            )
        except (ValueError, sqlite3.Error) as exc:
            classifier_validation = {"passed": False, "issues": [str(exc)]}
    else:
        classifier_validation = {
            "passed": True, "issues": [], "status": "no_classifier_scope",
        }
    try:
        high_coverage_scope = int(db.execute(
            """SELECT COUNT(*) FROM direct_high_coverage_classifier_models
               WHERE run_id=?""", (run_id,),
        ).fetchone()[0])
    except sqlite3.OperationalError:
        high_coverage_scope = 0
    if high_coverage_scope:
        try:
            from ledger.domain.direct_high_coverage_classifier import (
                validate_high_coverage_classifier,
            )
            admitted_rule_paths: set[str] = set()
            for (axis_evidence_json,) in db.execute(
                """SELECT axis_evidence_json
                   FROM direct_high_coverage_classifier_predictions
                   WHERE run_id=?""",
                (run_id,),
            ).fetchall():
                try:
                    payload = json.loads(str(axis_evidence_json))
                except (TypeError, json.JSONDecodeError):
                    payload = None
                contract = (
                    payload.get("finality_contract")
                    if isinstance(payload, dict)
                    else None
                )
                admission = (
                    contract.get("structural_rule_admission")
                    if isinstance(contract, dict)
                    else None
                )
                if isinstance(admission, dict):
                    admitted_rule_paths.update(
                        str(path)
                        for path in admission.get("admitted_paths", [])
                        if str(path).strip()
                    )
            high_coverage_validation = validate_high_coverage_classifier(
                db,
                run_id,
                require_allocations=True,
                admitted_rule_paths=admitted_rule_paths,
            )
        except (ValueError, sqlite3.Error) as exc:
            high_coverage_validation = {"passed": False, "issues": [str(exc)]}
    else:
        high_coverage_validation = {
            "passed": True, "issues": [], "status": "no_high_coverage_scope",
        }
    # ``auto_provisional`` rows are processed automatically, but they are
    # still non-final until their target is promoted.  Report them separately
    # from rows that require an owner's choice; neither category may be
    # counted as final resolution.
    confirmation_question_count = len(ambiguous_review_keys)
    pending_owner_confirmation_count = len(ambiguous_review_keys)
    all_travel_unassigned_keys = travel_unassigned_keys | ambiguous_review_keys
    travel_metadata_question_groups = _travel_unassigned_metadata_question_groups(
        db, run_id, reviews_by_payment,
    )
    travel_metadata_question_keys = {
        str(key)
        for group in travel_metadata_question_groups
        for key in group.get("payment_external_keys", [])
    }
    if travel_metadata_question_keys != {
        str(key) for key in travel_unassigned_keys
    }:
        raise ValueError("travel_unassigned_question_coverage_invalid")
    # Automatic provisional rows are still processed without owner input.
    # They must be visible, but one question per (path, target) is a poor UI
    # shape for a batch queue.  Collapse the display to one batch per
    # classification path and retain a target sample for audit/navigation.
    # This changes presentation only; the row count remains authoritative.
    auto_provisional_targets_by_path: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for (path, target), count in auto_provisional_queue_counts.items():
        auto_provisional_targets_by_path[path][target] += count
    auto_provisional_question_groups = []
    for index, path in enumerate(sorted(auto_provisional_targets_by_path), start=1):
        target_counts = auto_provisional_targets_by_path[path]
        target_sample = [
            {"target": target, "payment_count": count}
            for target, count in sorted(
                target_counts.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        ]
        auto_provisional_question_groups.append(
            {
                "question_id": f"auto-provisional-batch-{index:03d}",
                "question_type": "auto_provisional_batch_summary",
                "classification_path": path,
                "payment_count": sum(target_counts.values()),
                "target_count": len(target_counts),
                "target_sample": target_sample,
                "question": (
                    "자동 임시분류 묶음입니다. 현재 비용축은 자동 처리됐고, "
                    "행사명 확정이 필요한 경우에만 나중에 확인합니다."
                ),
            }
        )
    manual_question_keys = {
        str(key)
        for group in owner_question_groups
        if str(group.get("question_type")) not in {
            "mn_duplicate_or_double_charge", "partial_refund_mn",
        }
        for key in group.get("payment_external_keys", [])
    }
    if manual_question_keys != {str(key) for key in ambiguous_review_keys}:
        raise ValueError("manual_question_coverage_invalid")
    travel_user_question_payment_keys = (
        travel_metadata_question_keys | manual_question_keys
    )
    if travel_user_question_payment_keys != {
        str(key) for key in all_travel_unassigned_keys
    }:
        raise ValueError("travel_user_question_coverage_invalid")
    user_question_payment_keys = (
        travel_user_question_payment_keys | relationship_question_keys
    )
    nonfinal_key_set = set(nonfinal_keys)
    human_question_keys = {
        str(key)
        for key in user_question_payment_keys
        if str(key) in nonfinal_key_set
    }
    auto_nonfinal_keys = {
        str(key)
        for key in auto_provisional_keys
        if str(key) in nonfinal_key_set and str(key) not in human_question_keys
    }
    excluded_quarantine_nonfinal_keys = (
        excluded_quarantine_keys & nonfinal_key_set
    )
    untriaged_nonfinal_keys = (
        nonfinal_key_set
        - human_question_keys
        - auto_nonfinal_keys
        - excluded_quarantine_nonfinal_keys
    )
    lane_partition_invariant = (
        not (human_question_keys & auto_nonfinal_keys)
        and not (human_question_keys & untriaged_nonfinal_keys)
        and not (auto_nonfinal_keys & untriaged_nonfinal_keys)
        and not (excluded_quarantine_nonfinal_keys & human_question_keys)
        and not (excluded_quarantine_nonfinal_keys & auto_nonfinal_keys)
        and not (excluded_quarantine_nonfinal_keys & untriaged_nonfinal_keys)
        and human_question_keys
        | auto_nonfinal_keys
        | excluded_quarantine_nonfinal_keys
        | untriaged_nonfinal_keys
        == nonfinal_key_set
    )
    human_question_group_count = (
        len(owner_question_groups) + len(travel_metadata_question_groups)
    )
    relationship_question_group_count = sum(
        str(group.get("question_type")) in {
            "mn_duplicate_or_double_charge", "partial_refund_mn",
        }
        for group in owner_question_groups
    )
    travel_open_keys = (
        set(travel_unassigned_keys)
        | set(provisional_trip_keys)
        | set(auto_provisional_trip_keys)
        | set(ambiguous_review_keys)
    )
    travel_open_count = len(travel_open_keys)
    owner_choice_required_keys = set(provisional_keys) | set(ambiguous_review_keys)
    manual_owner_choice_required_count = len(owner_choice_required_keys)
    owner_choice_required_keys |= relationship_question_keys
    owner_choice_required_count = len(owner_choice_required_keys)
    # ``auto_provisional_keys`` is the complete non-final automatic lane.  A
    # separate action lane contains every reservation whose service period is
    # still unknown, regardless of payment year, plus relationship questions.
    # Activity placeholders remain non-final and visible but do not block the
    # reservation-action ceiling.
    auto_provisional_action_count = len(auto_provisional_action_keys)
    action_required_keys = set(human_question_keys)
    action_required_count = len(action_required_keys)
    queue_slo = _queue_slo_diagnostics(
        all_travel_unassigned_keys,
        human_question_group_count,
    )
    triage_passed = (
        bool(payments) and partition_gap_count == 0
        and not untriaged_nonfinal_keys
        and not finality_invalid_keys
        and nonfinal_side_effect_invariant
        and bool(terminal_validation.get("passed"))
        and terminal_side_effect_invariant
        and queue_partition_invariant
        and lane_partition_invariant
        and bool(settlement_validation.get("passed"))
        and bool(settlement_manifest_validation.get("passed"))
        and bool(lodging_validation.get("passed"))
        and bool(lodging_manifest_validation.get("passed"))
        and bool(ota_reservation_validation.get("passed"))
        and bool(classifier_validation.get("passed"))
        and bool(high_coverage_validation.get("passed"))
        and bool(cost_validation.get("passed"))
    )
    release_ready = triage_passed and nonfinal_count == 0
    release_blockers = []
    if not triage_passed:
        release_blockers.append("triage_failed")
    if nonfinal_count:
        release_blockers.append("nonfinal_rows_present")
    if not settlement_validation.get("passed"):
        gate_reason = "settlement_authority_validation_failed"
    elif not settlement_manifest_validation.get("passed"):
        gate_reason = "settlement_manifest_validation_failed"
    elif not lodging_validation.get("passed"):
        gate_reason = "lodging_authority_validation_failed"
    elif not lodging_manifest_validation.get("passed"):
        gate_reason = "lodging_manifest_validation_failed"
    elif not ota_reservation_validation.get("passed"):
        gate_reason = "ota_reservation_authority_validation_failed"
    elif not classifier_validation.get("passed"):
        gate_reason = "validated_classifier_validation_failed"
    elif not high_coverage_validation.get("passed"):
        gate_reason = "high_coverage_classifier_validation_failed"
    elif not cost_validation.get("passed"):
        gate_reason = "payment_year_2025_cost_accounting_validation_failed"
    elif not terminal_validation.get("passed"):
        gate_reason = "payment_year_2025_terminal_validation_failed"
    elif not terminal_side_effect_invariant:
        gate_reason = "payment_year_2025_terminal_side_effect_leak"
    elif finality_invalid_keys:
        gate_reason = "row_finality_veto_bypassed"
    elif not nonfinal_side_effect_invariant:
        gate_reason = "nonfinal_side_effect_leak"
    elif not queue_partition_invariant:
        gate_reason = "nonfinal_action_queue_partition_invalid"
    elif not lane_partition_invariant:
        gate_reason = "nonfinal_lane_partition_invalid"
    elif partition_gap_count:
        gate_reason = "direct_allocation_decision_incomplete"
    elif untriaged_nonfinal_keys:
        gate_reason = "untriaged_nonfinal_lane_present"
    else:
        gate_reason = (
            "triage_pass_with_nonfinal_queue"
            if nonfinal_count else "ok"
        )
    return _gate(
        5,
        GATE_NAMES[4],
        triage_passed,
        reason=gate_reason,
        actual={
            "triage_status": "TRIAGE_PASS" if triage_passed else "TRIAGE_FAIL",
            "triage_passed": triage_passed,
            "release_scope_ready": release_ready,
            "release_blockers": release_blockers,
            "candidate_payment_count": len(payments),
            "resolved_count": resolved,
            "final_resolved_count": resolved,
            "display_terminal_final_count": len(terminal_keys),
            "accounting_final_count": len(allocated_keys),
            "payment_year_2025_terminal_count": (
                (terminal_validation.get("counts") or {}).get(
                    "residual_terminal", 0
                )
            ),
            "payment_year_2025_cost_accounting_count": len(
                cost_payment_id_set
            ),
            "payment_year_2025_excluded_count": (
                (terminal_validation.get("counts") or {}).get("excluded", 0)
            ),
            "final_population_objective": {
                "minimum": 5000,
                "actual": resolved,
                "passed": resolved >= 5000,
            },
            "nonfinal_count": nonfinal_count,
            "total_nonfinal_count": nonfinal_count,
            "final_count": resolved,
            "auto_nonfinal_count": len(auto_nonfinal_keys),
            "human_question_nonfinal_count": len(human_question_keys),
            "untriaged_nonfinal_count": len(untriaged_nonfinal_keys),
            "human_question_group_count": human_question_group_count,
            "human_question_payment_count": len(human_question_keys),
            "lane_partition_invariant": lane_partition_invariant,
            "finality_invalid_count": len(finality_invalid_keys),
            "finality_invalid_event_key_sample": finality_invalid_keys[:10],
            "nonfinal_side_effect_invariant": nonfinal_side_effect_invariant,
            "terminal_side_effect_invariant": terminal_side_effect_invariant,
            "terminal_plan_count": len(terminal_plan_payment_ids),
            "terminal_allocation_count": len(terminal_allocation_payment_ids),
            "terminal_journal_count": len(terminal_journal_payment_ids),
            "terminal_reversal_derivation_count": len(
                terminal_reversal_derivation_payment_ids
            ),
            "terminal_reversal_inheritance_count": len(
                terminal_reversal_inheritance_payment_ids
            ),
            "terminal_confirmed_decision_count": len(
                terminal_confirmed_decision_payment_ids
            ),
            "excluded_quarantine_count": len(excluded_quarantine_nonfinal_keys),
            "payment_year_2025_terminal_validation": terminal_validation,
            "payment_year_2025_cost_accounting_validation": cost_validation,
            "nonfinal_plan_count": len(nonfinal_plan_payment_ids),
            "nonfinal_allocation_count": len(nonfinal_allocation_payment_ids),
            "nonfinal_journal_count": len(nonfinal_journal_payment_ids),
            "nonfinal_reversal_derivation_count": len(
                nonfinal_reversal_derivation_payment_ids
            ),
            "nonfinal_reversal_inheritance_count": len(
                nonfinal_reversal_inheritance_payment_ids
            ),
            "nonfinal_confirmed_decision_count": len(
                nonfinal_confirmed_decision_payment_ids
            ),
            "partial_refund_question_payment_count": len(partial_refund_question_keys),
            "partial_refund_question_event_key_sample": sorted(
                partial_refund_question_keys
            )[:10],
            "relationship_question_payment_count": len(relationship_question_keys),
            "relationship_question_event_key_sample": sorted(
                relationship_question_keys
            )[:10],
            "nonfinal_action_queue_partition_invariant": queue_partition_invariant,
            "owner_choice_required_count": owner_choice_required_count,
            "manual_owner_choice_required_count": manual_owner_choice_required_count,
            "named_auto_target_row_count": len(named_auto_target_keys),
            "auto_provisional_action_count": auto_provisional_action_count,
            "automatic_followup_count": auto_provisional_action_count,
            "action_required_count": action_required_count,
            "out_of_scope_named_auto_target_count": len(
                out_of_scope_auto_provisional_action_keys
            ),
            "out_of_scope_named_auto_target_event_key_sample": sorted(
                out_of_scope_auto_provisional_action_keys
            )[:10],
            "partition_gap_count": partition_gap_count,
            "provisional_count": len(provisional_keys),
            "auto_provisional_count": len(auto_provisional_keys),
            "pending_owner_confirmation_count": pending_owner_confirmation_count,
            "confirmation_question_count": confirmation_question_count,
            "provisional_trip_count": len(provisional_trip_keys),
            "auto_provisional_trip_count": len(auto_provisional_trip_keys),
            "provisional_activity_count": provisional_path_counts[
                "current_card_travel_activity_placeholder"
            ],
            "provisional_reservation_count": provisional_path_counts[
                "current_card_reservation_placeholder"
            ],
            "ambiguous_manual_review_count": len(ambiguous_review_keys),
            "allocated_count": len(allocated_keys),
            "terminal_complete_count": len(terminal_keys),
            "travel_unassigned_count": len(all_travel_unassigned_keys),
            "confirmed_travel_unassigned_count": len(travel_unassigned_keys),
            "travel_open_count": travel_open_count,
            "queue_slo": queue_slo,
            # Retain the legacy object name for report consumers.  The
            # explicit enforcement field prevents these queue-size targets
            # from being mistaken for correctness or release gates.
            "acceptance_limits": {
                "enforcement": "advisory_only",
                "travel_unassigned_max": TRAVEL_UNASSIGNED_QUEUE_SLO,
                "human_question_group_max": HUMAN_QUESTION_GROUP_QUEUE_SLO,
                "automatic_followup_scope": "all_period",
                "payment_year_filter_for_queue": None,
                "nonfinal_count_cannot_be_replaced": True,
                "legacy_row_limits_not_used_for_acceptance": True,
                "auto_provisional_acceptance_scope": {
                    "year": AUTO_PROVISIONAL_ACTION_YEAR,
                    "classification_path": AUTO_PROVISIONAL_ACTION_PATH,
                    "meaning": (
                        "unknown-service-period reservations remain in an "
                        "all-period automatic follow-up queue; payment year is "
                        "not used as service year"
                    ),
                    "queue_scope": CURRENT_ASSIGNMENT_QUEUE_SCOPE,
                    "payment_year_filter_for_queue": None,
                    "excluded_rows_are_retained": True,
                    "cannot_replace_total_nonfinal_count": True,
                },
            },
            "owner_confirmation_question_groups": owner_question_groups,
            "owner_confirmation_question_group_count": len(owner_question_groups),
            "owner_confirmation_payment_count": len(owner_question_payment_keys),
            "owner_confirmation_question_payment_count": len(
                owner_question_payment_keys
            ),
            "relationship_question_group_count": relationship_question_group_count,
            "user_question_payment_count": len(user_question_payment_keys),
            "user_question_group_count": human_question_group_count,
            "human_question_event_key_sample": sorted(human_question_keys)[:10],
            "auto_nonfinal_event_key_sample": sorted(auto_nonfinal_keys)[:10],
            "untriaged_nonfinal_event_key_sample": sorted(untriaged_nonfinal_keys)[:10],
            "travel_unassigned_metadata_question_count": len(travel_unassigned_keys),
            "travel_unassigned_metadata_question_groups": travel_metadata_question_groups,
            "travel_unassigned_metadata_question_group_count": len(
                travel_metadata_question_groups
            ),
            "auto_provisional_question_groups": auto_provisional_question_groups,
            "auto_provisional_question_group_count": len(
                auto_provisional_question_groups
            ),
            "auto_provisional_detail_group_count": len(
                auto_provisional_queue_counts
            ),
            # Keep the legacy key for report consumers, but make it mean
            # "not final".  A zero now requires every row to be final.
            "unresolved_count": nonfinal_count,
            "partition_gap_event_key_sample": [
                str(row[1]) for row in partition_gap_rows[:10]
            ],
            "nonfinal_event_key_sample": sorted(nonfinal_keys)[:10],
            "resolved_event_key_sample": sorted(resolved_keys)[:10],
            "allocated_event_key_sample": sorted(allocated_keys)[:10],
            "terminal_event_key_sample": sorted(terminal_keys)[:10],
            "provisional_event_key_sample": sorted(provisional_keys)[:10],
            "unresolved_partition_event_key_sample": [
                str(row[1]) for row in partition_gap_rows[:10]
            ],
            "unresolved_event_key_sample": [
                str(key) for key in sorted(nonfinal_keys)[:10]
            ],
            "partial_taxonomy_payment_count": len(partial_rows),
            "partial_taxonomy_decision_count": sum(int(row[1]) for row in partial_rows),
            "full_axis_payment_count": len(full_axis_rows),
            "full_axis_decision_count": sum(int(row[1]) for row in full_axis_rows),
            **scope,
            "active_dimensions": ["account", "cost_type", "allocation_target"],
            "excluded_dimensions": ["vat_tag"],
            "requirements_status": "direct_decision_contract_v2_three_axis",
            "settlement_authority_validation": settlement_validation,
            "settlement_manifest_validation": settlement_manifest_validation,
            "lodging_authority_validation": lodging_validation,
            "lodging_manifest_validation": lodging_manifest_validation,
            "ota_reservation_validation": ota_reservation_validation,
            "validated_classifier_validation": classifier_validation,
            "high_coverage_validation": high_coverage_validation,
            "structural_rule_requests": structural_rule_requests,
        },
    )


def _semantic_regression_gate(
    db: object,
    run_id: str,
    stored_hash: str | None,
    *,
    approved_transitions: Iterable[dict[str, object]] | None,
    comparable_baseline: dict[str, object] | None,
    historical_comparators: list[dict[str, object]],
    repository_root: Path,
) -> dict[str, object]:
    recomputed = candidate_semantic_sha256(db, run_id)
    integrity_ok = bool(stored_hash and stored_hash == recomputed)
    try:
        approvals = validate_approved_transitions(
            approved_transitions,
            expected_source_run_id=run_id,
            expected_after_semantic_sha256=recomputed,
        )
    except ValueError as exc:
        return _gate(
            6,
            GATE_NAMES[5],
            False,
            reason=str(exc),
            actual={
                "integrity_ok": integrity_ok,
                "approvals_provided": 0,
                "approval_mode": "invalid",
                "baseline_status": "not_evaluated",
                "diagnostic_comparators": historical_comparators,
            },
        )
    baseline_descriptor: dict[str, object] | None = None
    baseline_payload: dict[str, object] | None = None
    baseline_error: str | None = None
    current_event_error: str | None = None
    current_event_hashes: dict[str, str] = {}
    current_event_set_hash: str | None = None
    current_scope_hash: str | None = None
    try:
        (
            current_event_hashes,
            current_event_set_hash,
            current_scope_hash,
        ) = _current_direct_event_hashes(db, run_id)
    except ValueError as exc:
        current_event_error = str(exc)
    if current_event_error is None and comparable_baseline is not None:
        try:
            baseline_payload, baseline_descriptor = _load_comparable_baseline(
                comparable_baseline,
                repository_root,
            )
            if baseline_payload is not None:
                baseline_payload, baseline_hashes = _validate_event_baseline(
                    baseline_payload,
                    run_id=run_id,
                )
        except ValueError as exc:
            baseline_error = str(exc)
    if not integrity_ok:
        reason = "candidate_semantic_hash_mismatch"
        baseline_status = "not_evaluated"
        passed = False
    elif current_event_error is not None:
        reason = current_event_error
        baseline_status = "not_evaluated"
        passed = False
    elif comparable_baseline is None:
        reason = "direct_baseline_unavailable"
        baseline_status = "unavailable"
        passed = False
    elif baseline_error is not None:
        reason = baseline_error
        baseline_status = "invalid"
        passed = False
    else:
        assert baseline_payload is not None
        current_keys = set(current_event_hashes)
        baseline_keys = set(baseline_hashes)
        unchanged = sorted(
            key for key in current_keys & baseline_keys
            if current_event_hashes[key] == baseline_hashes[key]
        )
        changed = sorted(
            key for key in current_keys & baseline_keys
            if current_event_hashes[key] != baseline_hashes[key]
        )
        added = sorted(current_keys - baseline_keys)
        removed = sorted(baseline_keys - current_keys)
        diff_actual = {
            "unchanged_count": len(unchanged),
            "unchanged_sample": unchanged[:10],
            "changed_count": len(changed),
            "changed_sample": changed[:10],
            "added_count": len(added),
            "added_sample": added[:10],
            "removed_count": len(removed),
            "removed_sample": removed[:10],
            "current_event_set_sha256": current_event_set_hash,
            "baseline_event_set_sha256": baseline_payload["event_set_sha256"],
            "baseline_source_run_id": baseline_payload["source_run_id"],
            "baseline_input_manifest_sha256": baseline_payload["input_manifest_sha256"],
            "baseline_decision_scope_sha256": baseline_payload["decision_scope_sha256"],
        }
        passed = False
        reason = "direct_baseline_authority_unavailable"
        baseline_status = "diff_computed_unapproved"
    return _gate(
        6,
        GATE_NAMES[5],
        passed,
        reason=reason,
        actual={
            "integrity_ok": integrity_ok,
            "stored_candidate_semantic_sha256": stored_hash,
            "recomputed_candidate_semantic_sha256": recomputed,
            "approvals_provided": len(approvals),
            "approval_mode": "none" if not approvals else "event_level",
            "baseline_status": baseline_status,
            "baseline_descriptor": baseline_descriptor,
            "diagnostic_comparators": historical_comparators,
            "current_event_set_sha256": current_event_set_hash,
            "current_decision_scope_sha256": current_scope_hash,
            **(diff_actual if "diff_actual" in locals() else {}),
        },
    )


def _report_freshness_gate(
    db: object,
    run: dict[str, object],
    expected: dict[str, object],
) -> dict[str, object]:
    checks = {
        "status": (run["status"], "building"),
        "schema_version": (
            run["schema_version"],
            expected["schema_version"],
        ),
        "input_manifest_sha256": (
            run["input_manifest_sha256"],
            expected["input_manifest_sha256"],
        ),
        "candidate_semantic_sha256": (
            run["candidate_semantic_sha256"],
            expected["candidate_semantic_sha256"],
        ),
        "code_commit": (run["code_commit"], expected["code_commit"]),
        "code_bundle_sha256": (
            run["code_bundle_sha256"],
            expected["code_bundle_sha256"],
        ),
        "gate_report_sha256": (run["gate_report_sha256"], None),
    }
    parser_versions = {
        str(row[0])
        for row in db.execute(
            """
            SELECT DISTINCT parser_version
            FROM direct_projection_inputs
            WHERE run_id=?
            """,
            (run["run_id"],),
        ).fetchall()
    }
    checks["parser_version"] = (
        sorted(parser_versions),
        [expected["parser_version"]],
    )
    mismatches = {
        field: {"actual": actual, "expected": wanted}
        for field, (actual, wanted) in checks.items()
        if actual != wanted
    }
    passed = not mismatches
    return _gate(
        7,
        GATE_NAMES[6],
        passed,
        reason="ok" if passed else "run_provenance_stale",
        actual={
            "evaluation_status": run["status"],
            "mismatches": mismatches,
        },
    )


def _readiness_summary(
    gates: Iterable[dict[str, object]],
) -> dict[str, object]:
    """Separate diagnostic shadow readiness from release authorization."""
    gate_list = list(gates)
    gates_by_number = {int(gate["gate"]): gate for gate in gate_list}
    if set(gates_by_number) != set(range(1, 8)):
        raise ValueError("gate_readiness_set_invalid")
    amount_gate = gates_by_number[4]
    amount_actual = amount_gate.get("actual") or {}
    amount_shadow_ready = bool(amount_gate["passed"]) or (
        amount_gate.get("reason") == "han_equality_validation_missing_or_stale"
        and int(amount_actual.get("sign_issue_count", -1)) == 0
        and int(amount_actual.get("hana_split_issue_count", -1)) == 0
        and int(amount_actual.get("relation_issue_count", -1)) == 0
    )
    semantic_gate = gates_by_number[6]
    semantic_actual = semantic_gate.get("actual") or {}
    semantic_shadow_ready = bool(semantic_gate["passed"]) or (
        bool(semantic_actual.get("integrity_ok"))
        and semantic_gate.get("reason") in {
            "direct_baseline_unavailable",
            "direct_baseline_authority_unavailable",
        }
    )
    shadow_checks = {
        "source_provenance": bool(gates_by_number[1]["passed"]),
        "event_projection_cardinality": bool(gates_by_number[2]["passed"]),
        "legacy_leakage": bool(gates_by_number[3]["passed"]),
        "amount_relation_integrity": amount_shadow_ready,
        "triage_integrity": bool(gates_by_number[5]["passed"]),
        "semantic_integrity": semantic_shadow_ready,
        "report_freshness": bool(gates_by_number[7]["passed"]),
    }
    shadow_ready = all(shadow_checks.values())
    gate5_actual = gates_by_number[5].get("actual") or {}
    release_ready = (
        all(bool(gate["passed"]) for gate in gate_list)
        and bool(gate5_actual.get("release_scope_ready"))
    )
    release_blockers = [
        str(gate["name"])
        for gate in gate_list
        if not bool(gate["passed"])
    ]
    if not bool(gate5_actual.get("release_scope_ready")):
        release_blockers.append("allocation_and_decision_finality")
    return {
        # ``passed`` remains the backwards-compatible release/cutover verdict.
        "passed": release_ready,
        "shadow_ready": shadow_ready,
        "release_ready": release_ready,
        "pipeline_status": (
            "RELEASE_READY"
            if release_ready
            else "TRIAGE_PASS"
            if shadow_ready
            else "BLOCKED"
        ),
        "shadow_checks": shadow_checks,
        "shadow_blockers": [
            name for name, check in shadow_checks.items() if not check
        ],
        "release_blockers": list(dict.fromkeys(release_blockers)),
    }


def build_gate_report(
    db_path: Path,
    run_id: str,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    expected_provenance: dict[str, object] | None = None,
    historical_comparators: list[dict[str, object]] | None = None,
    approved_transitions: Iterable[dict[str, object]] | None = None,
    comparable_baseline: dict[str, object] | None = None,
    han_equality_context:dict[str,object]|None=None,
    require_current_projection_contract: bool = False,
) -> dict[str, object]:
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys = ON")
    try:
        columns = (
            "run_id",
            "status",
            "schema_version",
            "input_manifest_sha256",
            "candidate_semantic_sha256",
            "gate_report_sha256",
            "code_commit",
            "code_bundle_sha256",
        )
        raw_run = db.execute(
            """
            SELECT
                run_id, status, schema_version, input_manifest_sha256,
                candidate_semantic_sha256, gate_report_sha256,
                code_commit, code_bundle_sha256
            FROM direct_projection_runs
            WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        if raw_run is None:
            raise ValueError("run_id_not_found")
        run = dict(zip(columns, raw_run))
        expected = expected_provenance or {
            "schema_version": run["schema_version"],
            "parser_version": PARSER_BUNDLE_VERSION,
            "input_manifest_sha256": run["input_manifest_sha256"],
            "candidate_semantic_sha256": run["candidate_semantic_sha256"],
            "code_commit": run["code_commit"],
            "code_bundle_sha256": run["code_bundle_sha256"],
        }
        comparators = historical_comparators or []
        gates = [
            _source_provenance_gate(
                db,
                run_id,
                run,
                repository_root,
            ),
            _projection_cardinality_gate(db, run_id),
            _legacy_leakage_gate(db, run_id),
            _amount_relation_gate(db,run_id,han_equality_context),
            _allocation_decision_gate(
                db,
                run_id,
                require_current_projection_contract=require_current_projection_contract,
            ),
            _semantic_regression_gate(
                db,
                run_id,
                run["candidate_semantic_sha256"],
                approved_transitions=approved_transitions,
                comparable_baseline=comparable_baseline,
                historical_comparators=comparators,
                repository_root=repository_root,
            ),
            _report_freshness_gate(db, run, expected),
        ]
        readiness = _readiness_summary(gates)
        return {
            "format_version": 2,
            "run_id": run_id,
            "input_manifest_sha256": run["input_manifest_sha256"],
            "candidate_semantic_sha256": run["candidate_semantic_sha256"],
            "code_commit": run["code_commit"],
            "code_bundle_sha256": run["code_bundle_sha256"],
            "schema_version": run["schema_version"],
            "parser_version": PARSER_BUNDLE_VERSION,
            **readiness,
            "gates": gates,
            "cutover_policy": (
                "candidate_ready_for_shadow"
                if bool(readiness["release_ready"])
                else "legacy_path_remains_authoritative"
            ),
        }
    except Exception as exc:
        gates = [
            _gate(
                number,
                name,
                False,
                reason=str(exc),
                actual=None,
            )
            for number, name in enumerate(GATE_NAMES, start=1)
        ]
        return {
            "format_version": 2,
            "run_id": run_id,
            "passed": False,
            "shadow_ready": False,
            "release_ready": False,
            "pipeline_status": "BLOCKED",
            "shadow_checks": {},
            "shadow_blockers": ["gate_report_exception"],
            "release_blockers": ["gate_report_exception"],
            "gates": gates,
            "cutover_policy": "legacy_path_remains_authoritative",
        }
    finally:
        db.close()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--success-level",
        choices=("release", "shadow"),
        default="release",
        help=(
            "process exit criterion; release preserves legacy fail-closed "
            "behavior, while shadow accepts a lossless triage result"
        ),
    )
    args = parser.parse_args()
    report = build_gate_report(args.db, args.run_id)
    report["gate_report_sha256"] = gate_report_sha256(report)
    _atomic_write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    success = (
        bool(report["shadow_ready"])
        if args.success_level == "shadow"
        else bool(report["passed"])
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
