"""Evidence-only boundary for cost-classification promotion.

Historical labels, legacy replay, and manual ledgers may nominate candidates,
but they are deliberately absent from the evidence index and promotion schema.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping


ARTIFACT_TYPE = "direct-independent-evidence-v1"
RULE_VERSION = "current-card-once-three-axis-promotion-v1"
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")
EXPECTED_CURRENT_EVENT_COUNT = 5328
FORBIDDEN_PROVENANCE_TOKENS = (
    "legacy",
    "historical",
    "lineage",
    "manual",
    "replay",
    "proposal",
    "tolerance",
    "within_2_percent",
    "trips.json",
    "vat_tag",
)
WITHHELD_COHORTS = (
    ("legacy_replay_three_active_axes", 750, 613),
    ("legacy_replay_missing_cost_type", 14, 0),
    ("historical_exact_manual_card", 42, 42),
    ("manual_frontier_lodging", 6, 6),
    ("manual_frontier_airfare", 2, 2),
    ("exact_manual_groups", 5, 5),
    ("verified_mutsu_legacy_bound", 6, 6),
    ("verified_kamenoi_legacy_bound", 2, 2),
    ("verified_partial_mixed_evidence", 7, 0),
    ("minatoya_tolerance_only", 2, 0),
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: object) -> str:
    data = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(data).hexdigest()


def _payload_scalar(payload: Mapping[str, object], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and not isinstance(value, (list, dict, tuple, set)):
            return str(value).strip()
    return ""


def materialize_current_card_evidence(db: object, run_id: str) -> dict[str, object]:
    """Materialize the complete current-card index once from the candidate DB."""
    rows = db.execute(
        """
        SELECT d.card_event_id,d.event_role,s.source_kind,s.source_key,s.source_sha256,
               e.identity_status,e.source_system,e.occurred_on,e.merchant,
               e.approval_number,d.amount_krw,d.transaction_type,s.payload_json
        FROM direct_payment_projection_links l
        JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
        JOIN direct_source_records s ON s.id=d.source_record_id
        JOIN direct_card_events e ON e.source_record_id=d.source_record_id
        WHERE l.run_id=?
        ORDER BY d.card_event_id,d.event_role
        """,
        (run_id,),
    ).fetchall()
    events: list[dict[str, object]] = []
    for row in rows:
        try:
            payload = json.loads(str(row[12]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("current_evidence_payload_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("current_evidence_payload_invalid")
        fact = {
            "direct_event_key": f"{row[0]}#{row[1]}",
            "source_kind": str(row[2]),
            "source_key": str(row[3]),
            "source_sha256": str(row[4]),
            "identity_status": str(row[5]),
            "source_system": str(row[6]),
            "occurred_on": str(row[7] or ""),
            "merchant": str(row[8] or ""),
            "approval_number": str(row[9] or ""),
            "amount_krw": int(row[10]),
            "transaction_type": str(row[11]),
            "event_role": str(row[1]),
            "card4": _payload_scalar(payload, "card4", "card_last4", "last4"),
            "currency": _payload_scalar(payload, "currency", "foreign_currency"),
            "foreign_amount": _payload_scalar(
                payload, "foreign_amount", "foreign", "local_amount"
            ),
            "payload_sha256": _sha(str(row[12]).encode("utf-8")),
        }
        fact["current_event_sha256"] = _sha(fact)
        fact["current_evidence_id"] = "current-card:" + str(
            fact["current_event_sha256"]
        )
        db.execute(
            """INSERT INTO direct_promotion_evidence(
                 evidence_id,run_id,evidence_kind,authority_status,direct_event_key,
                 source_kind,source_key,source_sha256,fact_sha256)
               VALUES (?,?,'current_card','current_raw',?,?,?,?,?)""",
            (
                fact["current_evidence_id"], run_id, fact["direct_event_key"],
                fact["source_kind"], fact["source_key"], fact["source_sha256"],
                fact["current_event_sha256"],
            ),
        )
        events.append(fact)
    keys = [str(event["direct_event_key"]) for event in events]
    if (
        len(events) != EXPECTED_CURRENT_EVENT_COUNT
        or len(set(keys)) != EXPECTED_CURRENT_EVENT_COUNT
        or any(event["source_kind"] != "card_raw" for event in events)
    ):
        raise ValueError("current_evidence_scope_invalid")
    ordered = sorted(events, key=lambda event: str(event["direct_event_key"]))
    event_set_sha256 = _sha(("\n".join(sorted(keys)) + "\n").encode("utf-8"))
    evidence_set_sha256 = _sha(ordered)
    contract = {
        "artifact_type": ARTIFACT_TYPE,
        "rule_version": RULE_VERSION,
        "active_dimensions": list(ACTIVE_DIMENSIONS),
        "excluded_dimensions": ["vat_tag"],
        "event_count": len(ordered),
        "unique_event_count": len(set(keys)),
        "event_set_sha256": event_set_sha256,
        "evidence_set_sha256": evidence_set_sha256,
        "source_counts": dict(sorted(Counter(
            str(event["source_system"]) for event in ordered
        ).items())),
        "identity_status_counts": dict(sorted(Counter(
            str(event["identity_status"]) for event in ordered
        ).items())),
        "manual_evidence_count": 0,
        "historical_evidence_count": 0,
        "generic_tolerance_evidence_count": 0,
        "materialization_count": 1,
    }
    contract["evidence_run_id"] = _sha(contract)
    return {
        "manifest": contract,
        "events": ordered,
        "by_key": {str(event["direct_event_key"]): event for event in ordered},
    }


def load_promotion_evidence_registry(
        db: object, run_id: str) -> dict[str, dict[str, object]]:
    columns = (
        "evidence_id", "run_id", "evidence_kind", "authority_status",
        "direct_event_key", "source_kind", "source_key", "source_sha256",
        "fact_sha256",
    )
    rows = db.execute(
        """SELECT evidence_id,run_id,evidence_kind,authority_status,
                  direct_event_key,source_kind,source_key,source_sha256,fact_sha256
           FROM direct_promotion_evidence WHERE run_id=? ORDER BY evidence_id""",
        (run_id,),
    ).fetchall()
    return {str(row[0]): dict(zip(columns, row)) for row in rows}


def build_legacy_candidate_audit() -> dict[str, object]:
    """Describe withdrawn legacy cohorts without treating their labels as evidence."""
    cohorts = [
        {
            "cohort": name,
            "reported_candidate_count": candidate_count,
            "previous_gate5_credit": previous_credit,
            "current_gate5_credit": 0,
            "status": "withheld_pending_independent_evidence",
        }
        for name, candidate_count, previous_credit in WITHHELD_COHORTS
    ]
    return {
        "artifact_type": "legacy-candidate-audit-v1",
        "authority_status": "candidate_only",
        "counts_are_diagnostic_not_a_set_union": True,
        "previous_gate5_credit": sum(row[2] for row in WITHHELD_COHORTS),
        "current_gate5_credit": 0,
        "cohorts": cohorts,
    }


def _forbidden_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(token in lowered for token in FORBIDDEN_PROVENANCE_TOKENS)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _content_address(evidence_kind: object, fact_sha256: object) -> str:
    if evidence_kind == "current_card":
        return f"current-card:{fact_sha256}"
    return f"{evidence_kind}:{fact_sha256}"


def validate_promotion_candidate(
    candidate: Mapping[str, object],
    current_index: Mapping[str, Mapping[str, object]],
    evidence_registry: Mapping[str, Mapping[str, object]],
) -> dict[str, str]:
    """Validate a future promotion payload without consulting candidate labels."""
    required = {"direct_event_key", "current_evidence_id", "conflict_count", "derivations"}
    if set(candidate) != required:
        raise ValueError("promotion_schema_invalid")
    event_key = candidate.get("direct_event_key")
    if not isinstance(event_key, str) or not event_key:
        raise ValueError("promotion_current_evidence_invalid")
    event = current_index.get(event_key)
    if event is None or candidate.get("current_evidence_id") != event.get("current_evidence_id"):
        raise ValueError("promotion_current_evidence_invalid")
    current_record = evidence_registry.get(str(candidate.get("current_evidence_id")))
    if (
        not isinstance(current_record, Mapping)
        or current_record.get("evidence_kind") != "current_card"
        or current_record.get("authority_status") != "current_raw"
        or current_record.get("direct_event_key") != event_key
        or current_record.get("source_kind") != "card_raw"
        or not isinstance(current_record.get("source_key"), str)
        or not str(current_record["source_key"]).strip()
        or not _is_sha256(current_record.get("source_sha256"))
        or current_record.get("fact_sha256") != event.get("current_event_sha256")
        or candidate.get("current_evidence_id") != _content_address(
            current_record.get("evidence_kind"), current_record.get("fact_sha256")
        )
    ):
        raise ValueError("promotion_current_evidence_unregistered")
    if type(candidate.get("conflict_count")) is not int or candidate["conflict_count"] != 0:
        raise ValueError("promotion_conflict_present")
    derivations = candidate.get("derivations")
    if not isinstance(derivations, Mapping) or set(derivations) != set(ACTIVE_DIMENSIONS):
        raise ValueError("promotion_dimensions_invalid")
    derivation_ids: set[str] = set()
    derivation_bindings: set[tuple[str, str, str]] = set()
    axes: dict[str, str] = {}
    for dimension in ACTIVE_DIMENSIONS:
        derivation = derivations[dimension]
        if not isinstance(derivation, Mapping) or set(derivation) != {
            "value", "status", "derivation_id", "rule_id", "evidence_ids"
        }:
            raise ValueError("promotion_derivation_schema_invalid")
        value = derivation.get("value")
        derivation_id = derivation.get("derivation_id")
        rule_id = derivation.get("rule_id")
        evidence_ids = derivation.get("evidence_ids")
        if (
            not isinstance(value, str) or not value.strip()
            or derivation.get("status") != "pass"
            or not isinstance(derivation_id, str) or not derivation_id.strip()
            or _forbidden_text(derivation_id)
            or not isinstance(rule_id, str) or not rule_id.strip()
            or _forbidden_text(rule_id)
            or not isinstance(evidence_ids, list)
            or len(evidence_ids) != 2
            or len(set(evidence_ids)) != 2
            or candidate["current_evidence_id"] not in evidence_ids
            or any(not isinstance(item, str) or not item for item in evidence_ids)
            or any(_forbidden_text(item) for item in evidence_ids)
        ):
            raise ValueError("promotion_derivation_invalid")
        if derivation_id in derivation_ids:
            raise ValueError("promotion_derivation_alias")
        independent_id = next(
            item for item in evidence_ids
            if item != candidate["current_evidence_id"]
        )
        independent_record = evidence_registry.get(independent_id)
        if (
            not isinstance(independent_record, Mapping)
            or independent_record.get("evidence_kind") == "current_card"
            or independent_record.get("authority_status") != "verified_external"
            or independent_record.get("direct_event_key") != event_key
            or _forbidden_text(independent_record.get("source_kind"))
            or independent_record.get("source_kind") == "card_raw"
            or not isinstance(independent_record.get("source_key"), str)
            or not str(independent_record["source_key"]).strip()
            or not _is_sha256(independent_record.get("source_sha256"))
            or not _is_sha256(independent_record.get("fact_sha256"))
            or independent_id != _content_address(
                independent_record.get("evidence_kind"),
                independent_record.get("fact_sha256"),
            )
        ):
            raise ValueError("promotion_independent_evidence_unregistered")
        binding = (str(candidate["current_evidence_id"]), independent_id, rule_id)
        if binding in derivation_bindings:
            raise ValueError("promotion_derivation_alias")
        derivation_ids.add(derivation_id)
        derivation_bindings.add(binding)
        axes[dimension] = value.strip()
    return axes


def project_independent_promotion(
        db: object, run_id: str, candidate: Mapping[str, object],
        current_index: Mapping[str, Mapping[str, object]]) -> dict[str, int]:
    """Project a promotion only from evidence already registered for this run."""
    registry = load_promotion_evidence_registry(db, run_id)
    axes = validate_promotion_candidate(candidate, current_index, registry)
    payment = db.execute(
        """SELECT l.payment_id FROM direct_payment_projection_links l
           JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
           WHERE l.run_id=? AND d.card_event_id || '#' || d.event_role=?""",
        (run_id, candidate["direct_event_key"]),
    ).fetchall()
    if len(payment) != 1:
        raise ValueError("promotion_payment_binding_invalid")
    payment_id = int(payment[0][0])
    existing = int(db.execute(
        """SELECT COUNT(*) FROM current_classification_decisions
           WHERE target_type='payment' AND target_id=?
             AND dimension IN ('account','cost_type','allocation_target')""",
        (payment_id,),
    ).fetchone()[0])
    if existing:
        raise ValueError("promotion_existing_decision_conflict")
    inserted = 0
    db.execute("SAVEPOINT independent_promotion")
    try:
        for dimension in ACTIVE_DIMENSIONS:
            derivation = candidate["derivations"][dimension]
            evidence_ids = list(derivation["evidence_ids"])
            independent_id = next(
                item for item in evidence_ids
                if item != candidate["current_evidence_id"]
            )
            decision_id = int(db.execute(
                """INSERT INTO classification_decisions(
                     target_type,target_id,dimension,value,confidence,confidence_label,
                     decision_status,rule_id,rationale)
                   VALUES ('payment',?,?,?,?,?,'confirmed',?,?)""",
                (
                    payment_id, dimension, axes[dimension], 1.0,
                    "독립원천검증", derivation["rule_id"],
                    "registered current-card and verified external evidence",
                ),
            ).lastrowid)
            db.execute(
                """INSERT INTO direct_axis_derivations(
                     derivation_id,run_id,payment_id,dimension,value,rule_id,
                     current_evidence_id,independent_evidence_id,
                     derivation_status,conflict_count)
                   VALUES (?,?,?,?,?,?,?,?,'pass',0)""",
                (
                    derivation["derivation_id"], run_id, payment_id, dimension,
                    axes[dimension], derivation["rule_id"],
                    candidate["current_evidence_id"], independent_id,
                ),
            )
            db.execute(
                """INSERT INTO direct_decision_promotion_bindings(
                     run_id,decision_id,derivation_id) VALUES (?,?,?)""",
                (run_id, decision_id, derivation["derivation_id"]),
            )
            inserted += 1
    except Exception:
        db.execute("ROLLBACK TO independent_promotion")
        db.execute("RELEASE independent_promotion")
        raise
    else:
        db.execute("RELEASE independent_promotion")
    return {"payments": 1, "decisions": inserted}
