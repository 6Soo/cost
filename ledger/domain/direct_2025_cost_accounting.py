"""Account non-mail-backed 2025 card payments in a separate cost bucket.

The 2025-cost rule is deliberately narrower than a travel rule and broader
than the display-only ``2025년 결제`` disposition.  It recognizes only the
transaction year and the current-card fact.  It never creates a service
period, trip code, reservation number, or reversal inheritance.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable

from ledger.domain.direct_2025_payment_terminal import build_census


RULE_ID = "payment-year-2025-cost-accounting-v1"
POLICY_SOURCE_KIND = "approved_accounting_rule"
POLICY_SOURCE_KEY = RULE_ID
EVIDENCE_KIND = "sourced_adjustment"
ACCOUNT = "기타비용"
COST_TYPE = "판관비"
ALLOCATION_TARGET = "2025년 비용"
TARGET_TYPE = "other"
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _key_set_sha256(keys: Iterable[str]) -> str:
    return _sha(("\n".join(sorted(str(key) for key in keys)) + "\n").encode())


def _policy_payload() -> dict[str, object]:
    return {
        "contract": "payment-year-2025-cost-accounting-v1",
        "rule_id": RULE_ID,
        "payment_year": 2025,
        "account": ACCOUNT,
        "cost_type": COST_TYPE,
        "allocation_target": ALLOCATION_TARGET,
        "target_type": TARGET_TYPE,
        "accounting_period": "2025",
        "posting_date_source": "payment.occurred_on",
        "travel_eligible": False,
        "service_period_source": "none",
        "reservation_source": "none",
        "reversal_inheritance": False,
        "exclusions": [
            "settled_cancellation_or_refund",
            "mail_backed_2026_or_2027_travel",
            "lineage_missing",
            "non_purchase",
            "non_positive_amount",
            "existing_confirmed_decision",
        ],
    }


def _register_policy_source(db: sqlite3.Connection) -> str:
    payload = _policy_payload()
    digest = _sha(payload)
    row = db.execute(
        """SELECT source_sha256,payload_json FROM direct_source_records
           WHERE source_kind=? AND source_key=?""",
        (POLICY_SOURCE_KIND, POLICY_SOURCE_KEY),
    ).fetchone()
    if row is not None:
        if str(row[0]) != digest or _sha(json.loads(str(row[1]))) != digest:
            raise ValueError("2025_cost_policy_source_conflict")
        return digest
    db.execute(
        """INSERT INTO direct_source_records(
             source_kind,source_key,source_sha256,payload_json,redaction_version
           ) VALUES (?,?,?,?,?)""",
        (
            POLICY_SOURCE_KIND,
            POLICY_SOURCE_KEY,
            digest,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "approved-accounting-rule-v1",
        ),
    )
    return digest


def _current_evidence_by_event(
    db: sqlite3.Connection, run_id: str,
) -> dict[str, dict[str, str]]:
    rows = db.execute(
        """SELECT direct_event_key,evidence_id,fact_sha256,source_sha256,
                  source_kind,source_key
           FROM direct_promotion_evidence
           WHERE run_id=? AND evidence_kind='current_card'
             AND authority_status='current_raw'
           ORDER BY direct_event_key,evidence_id""",
        (run_id,),
    ).fetchall()
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        key = str(row[0])
        if key in result:
            raise ValueError(f"2025_cost_current_evidence_not_unique:{key}")
        result[key] = {
            "evidence_id": str(row[1]),
            "fact_sha256": str(row[2]),
            "source_sha256": str(row[3]),
            "source_kind": str(row[4]),
            "source_key": str(row[5]),
        }
    return result


def _cost_membership_sha(row: dict[str, object], evidence: dict[str, str]) -> str:
    return _sha({
        "rule_id": RULE_ID,
        "payment_id": int(row["payment_id"]),
        "direct_event_key": str(row["direct_event_key"]),
        "external_key_sha256": _sha(str(row["external_key"]).encode()),
        "current_fact_sha256": evidence["fact_sha256"],
    })


def _cost_provenance_sha(
    evidence: dict[str, str], policy_sha256: str, membership_sha256: str,
) -> str:
    return _sha({
        "rule_id": RULE_ID,
        "current_evidence_id": evidence["evidence_id"],
        "current_fact_sha256": evidence["fact_sha256"],
        "policy_source_kind": POLICY_SOURCE_KIND,
        "policy_source_key": POLICY_SOURCE_KEY,
        "policy_source_sha256": policy_sha256,
        "membership_sha256": membership_sha256,
    })


def _candidate_rows(db: sqlite3.Connection, run_id: str) -> dict[int, dict[str, object]]:
    census = build_census(db, run_id)
    return {
        int(payment_id): dict(row)
        for payment_id, row in census["rows_by_id"].items()
        if int(payment_id) in census["residual_ids"]
    }


def cost_payment_ids(db: sqlite3.Connection, run_id: str) -> set[int]:
    try:
        rows = db.execute(
            "SELECT payment_id FROM direct_2025_cost_accounting WHERE run_id=?",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {int(row[0]) for row in rows}


def project_2025_cost_accounting(
    db: sqlite3.Connection, run_id: str,
) -> dict[str, object]:
    """Promote the strict residual 2025 purchase set into the cost bucket."""
    if db.execute(
        "SELECT COUNT(*) FROM direct_2025_cost_accounting WHERE run_id=?",
        (run_id,),
    ).fetchone()[0]:
        raise ValueError("2025_cost_accounting_already_projected")
    census = build_census(db, run_id)
    rows_by_id = {
        int(payment_id): dict(row)
        for payment_id, row in census["rows_by_id"].items()
    }
    cost_ids = sorted(int(payment_id) for payment_id in census["residual_ids"])
    evidence_by_event = _current_evidence_by_event(db, run_id)
    policy_sha256 = _register_policy_source(db)
    inserted = 0
    superseded_decisions = 0
    db.execute("SAVEPOINT payment_year_2025_cost")
    try:
        for payment_id in cost_ids:
            row = rows_by_id[payment_id]
            if (
                str(row["occurred_on"])[:4] != "2025"
                or str(row["transaction_type"]) != "purchase"
                or int(row["amount_krw"]) <= 0
            ):
                raise ValueError("2025_cost_candidate_contract_invalid")
            current_evidence = evidence_by_event.get(str(row["direct_event_key"]))
            if current_evidence is None:
                raise ValueError("2025_cost_current_evidence_missing")
            existing_rows = db.execute(
                """SELECT id,dimension,decision_status
                   FROM current_classification_decisions
                   WHERE target_type='payment' AND target_id=?
                     AND dimension IN ('account','cost_type','allocation_target')
                   ORDER BY dimension,id""",
                (payment_id,),
            ).fetchall()
            if any(str(item[2]) == "confirmed" for item in existing_rows):
                raise ValueError("2025_cost_existing_decision_conflict")
            stale_decisions_by_dimension = {
                str(item[1]): int(item[0]) for item in existing_rows
            }
            membership_sha256 = _cost_membership_sha(row, current_evidence)
            fact_sha256 = _sha({
                "rule_id": RULE_ID,
                "payment_id": payment_id,
                "direct_event_key": str(row["direct_event_key"]),
                "current_fact_sha256": current_evidence["fact_sha256"],
            })
            independent_evidence_id = f"{EVIDENCE_KIND}:{fact_sha256}"
            db.execute(
                """INSERT INTO direct_promotion_evidence(
                     evidence_id,run_id,evidence_kind,authority_status,
                     direct_event_key,source_kind,source_key,source_sha256,fact_sha256)
                   VALUES (?,?,'sourced_adjustment','verified_external',?,?,?,?,?)""",
                (
                    independent_evidence_id,
                    run_id,
                    str(row["direct_event_key"]),
                    POLICY_SOURCE_KIND,
                    POLICY_SOURCE_KEY,
                    policy_sha256,
                    fact_sha256,
                ),
            )
            axis_values = {
                "account": ACCOUNT,
                "cost_type": COST_TYPE,
                "allocation_target": ALLOCATION_TARGET,
            }
            rationale = (
                "사용자 승인 payment-year-2025-cost-accounting-v1: "
                "2025년 결제를 여행으로 추정하지 않고 2025년 비용으로 배부함. "
                "행사기간·여행코드·예약번호·환불상속은 만들지 않음"
            )
            for dimension in ACTIVE_DIMENSIONS:
                value = axis_values[dimension]
                axis_rule_id = f"{RULE_ID}:{dimension}"
                derivation_id = "2025-cost-derivation:" + _sha({
                    "payment_id": payment_id,
                    "dimension": dimension,
                    "value": value,
                    "current_evidence_id": current_evidence["evidence_id"],
                    "independent_evidence_id": independent_evidence_id,
                })
                decision_id = int(db.execute(
                    """INSERT INTO classification_decisions(
                         target_type,target_id,dimension,value,confidence,
                         confidence_label,decision_status,rule_id,rationale)
                       VALUES ('payment',?,?,?,?,?,'superseded',?,?)""",
                    (
                        payment_id,
                        dimension,
                        value,
                        1.0,
                        "사용자 승인 규칙",
                        axis_rule_id,
                        rationale,
                    ),
                ).lastrowid)
                stale_decision_id = stale_decisions_by_dimension.get(dimension)
                if stale_decision_id is not None:
                    db.execute(
                        """UPDATE classification_decisions
                           SET superseded_by_id=?
                           WHERE id=? AND superseded_by_id IS NULL""",
                        (decision_id, stale_decision_id),
                    )
                    superseded_decisions += 1
                db.execute(
                    "UPDATE classification_decisions SET decision_status='confirmed' WHERE id=?",
                    (decision_id,),
                )
                db.execute(
                    """INSERT INTO direct_axis_derivations(
                         derivation_id,run_id,payment_id,dimension,value,rule_id,
                         current_evidence_id,independent_evidence_id,
                         derivation_status,conflict_count)
                       VALUES (?,?,?,?,?,?,?,?,'pass',0)""",
                    (
                        derivation_id,
                        run_id,
                        payment_id,
                        dimension,
                        value,
                        axis_rule_id,
                        current_evidence["evidence_id"],
                        independent_evidence_id,
                    ),
                )
                db.execute(
                    """INSERT INTO direct_decision_promotion_bindings(
                         run_id,decision_id,derivation_id) VALUES (?,?,?)""",
                    (run_id, decision_id, derivation_id),
                )
            provenance_sha256 = _cost_provenance_sha(
                current_evidence, policy_sha256, membership_sha256,
            )
            idempotency_key = (
                f"{RULE_ID}:"
                f"{_sha(str(row['direct_event_key']).encode())}"
            )
            db.execute(
                """INSERT INTO direct_2025_cost_accounting(
                     run_id,payment_id,direct_event_key,rule_id,account,cost_type,
                     allocation_target,target_type,current_evidence_id,
                     independent_evidence_id,membership_sha256,provenance_sha256,
                     travel_eligible,accounting_final,allocation_eligible,
                     posting_eligible,reversal_inheritance_eligible,payload_json,
                     accounting_period,posting_date_source,idempotency_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    payment_id,
                    str(row["direct_event_key"]),
                    RULE_ID,
                    ACCOUNT,
                    COST_TYPE,
                    ALLOCATION_TARGET,
                    TARGET_TYPE,
                    current_evidence["evidence_id"],
                    independent_evidence_id,
                    membership_sha256,
                    provenance_sha256,
                    0,
                    1,
                    1,
                    1,
                    0,
                    json.dumps({
                        "contract": "payment-year-2025-cost-accounting-v1",
                        "rule_id": RULE_ID,
                        "payment_id": payment_id,
                        "direct_event_key": str(row["direct_event_key"]),
                        "occurred_on": str(row["occurred_on"]),
                        "amount_krw": int(row["amount_krw"]),
                        "period": "",
                        "trip_code": "",
                        "reservation_number": "",
                        "accounting_period": "2025",
                        "posting_date_source": "payment.occurred_on",
                        "idempotency_key": idempotency_key,
                        "membership_sha256": membership_sha256,
                        "provenance_sha256": provenance_sha256,
                    }, ensure_ascii=False, sort_keys=True),
                    "2025",
                    "payment.occurred_on",
                    idempotency_key,
                ),
            )
            db.execute(
                """INSERT INTO allocation_review_cases(
                     payment_id,outcome,reason_code,rationale,review_status,rule_id)
                   VALUES (?,?,?,?, 'confirmed', ?)
                   ON CONFLICT(payment_id) DO UPDATE SET
                     outcome=excluded.outcome,reason_code=excluded.reason_code,
                     rationale=excluded.rationale,review_status=excluded.review_status,
                     rule_id=excluded.rule_id,reviewed_at=CURRENT_TIMESTAMP""",
                (
                    payment_id,
                    "overhead",
                    "payment_year_2025_cost_accounting",
                    rationale,
                    f"{RULE_ID}:allocation_target",
                ),
            )
            inserted += 1
    except Exception:
        db.execute("ROLLBACK TO payment_year_2025_cost")
        db.execute("RELEASE payment_year_2025_cost")
        raise
    else:
        db.execute("RELEASE payment_year_2025_cost")

    keys = {
        str(rows_by_id[payment_id]["external_key"])
        for payment_id in cost_ids
    }
    membership_set_sha256 = _key_set_sha256(
        _sha(str(rows_by_id[payment_id]["external_key"]).encode())
        for payment_id in cost_ids
    )
    partition_sha256 = _sha({
        "rule_id": RULE_ID,
        "candidate_set_sha256": _key_set_sha256(
            str(row["external_key"])
            for row in rows_by_id.values()
            if str(row["occurred_on"])[:4] == "2025"
        ),
        "cost_accounting_set_sha256": membership_set_sha256,
        "policy_source_sha256": policy_sha256,
    })
    db.execute(
        """INSERT INTO direct_2025_cost_accounting_manifests(
             run_id,rule_id,candidate_count,payment_count,payment_set_sha256,
             policy_source_sha256,partition_sha256,payload_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            run_id,
            RULE_ID,
            len(census["year_rows"]),
            inserted,
            membership_set_sha256,
            policy_sha256,
            partition_sha256,
            json.dumps({
                "contract": "payment-year-2025-cost-accounting-manifest-v1",
                "rule_id": RULE_ID,
                "candidate_count": len(census["year_rows"]),
                "payment_count": inserted,
                "payment_set_sha256": membership_set_sha256,
                "policy_source_sha256": policy_sha256,
                "partition_sha256": partition_sha256,
                "travel_eligible": False,
                "period_and_reservation_blank": True,
            }, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {
        "candidate_count": len(census["year_rows"]),
        "payment_count": inserted,
        "decisions": inserted * len(ACTIVE_DIMENSIONS),
        "superseded_decisions": superseded_decisions,
        "allocation_target": ALLOCATION_TARGET,
        "payment_set_sha256": membership_set_sha256,
        "policy_source_sha256": policy_sha256,
        "partition_sha256": partition_sha256,
    }


def validate_2025_cost_accounting(
    db: sqlite3.Connection, run_id: str, *, require_manifest: bool = False,
) -> dict[str, object]:
    issues: list[str] = []
    try:
        # Older/synthetic gate fixtures do not run the current projection
        # phase and therefore have no rule manifest.  The production
        # pipeline always writes this manifest before Gate5 is evaluated;
        # keep those fixtures diagnostic-compatible without treating an
        # unexecuted projection as a validated accounting result.
        manifest_presence = db.execute(
            """SELECT 1 FROM direct_2025_cost_accounting_manifests
               WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if manifest_presence is None:
            if require_manifest:
                return {
                    "passed": False,
                    "issues": ["2025_cost_manifest_missing"],
                    "not_applicable": False,
                    "candidate_count": 0,
                    "payment_count": 0,
                    "accounting_target": ALLOCATION_TARGET,
                }
            return {
                "passed": True,
                "issues": [],
                "not_applicable": True,
                "candidate_count": 0,
                "payment_count": 0,
                "accounting_target": ALLOCATION_TARGET,
            }
        census = build_census(db, run_id)
        expected_ids = {int(value) for value in census["residual_ids"]}
        rows = db.execute(
            """SELECT payment_id,direct_event_key,rule_id,account,cost_type,
                      allocation_target,target_type,current_evidence_id,
                      independent_evidence_id,membership_sha256,provenance_sha256,
                      travel_eligible,accounting_final,allocation_eligible,
                      posting_eligible,reversal_inheritance_eligible,payload_json,
                      accounting_period,posting_date_source,idempotency_key
               FROM direct_2025_cost_accounting WHERE run_id=?
               ORDER BY payment_id""",
            (run_id,),
        ).fetchall()
        actual_ids = {int(row[0]) for row in rows}
        if actual_ids != expected_ids:
            issues.append("2025_cost_membership_mismatch")
        decision_rows_by_payment: dict[int, list[tuple[object, ...]]] = {}
        allocations_by_payment: dict[int, list[tuple[object, ...]]] = {}
        amounts_by_payment: dict[int, int] = {}
        if actual_ids:
            placeholders = ",".join("?" for _ in actual_ids)
            ordered_ids = tuple(sorted(actual_ids))
            decision_rows = db.execute(
                f"""SELECT target_id,dimension,value,rule_id,decision_status
                    FROM current_independently_promoted_decisions
                    WHERE run_id=? AND target_type='payment'
                      AND target_id IN ({placeholders})
                      AND dimension IN ('account','cost_type','allocation_target')
                    ORDER BY target_id,dimension""",
                (run_id, *ordered_ids),
            ).fetchall()
            for item in decision_rows:
                decision_rows_by_payment.setdefault(int(item[0]), []).append(
                    tuple(item[1:])
                )
            allocation_rows = db.execute(
                f"""SELECT ap.payment_id,ap.plan_status,ap.confidence,
                          ca.amount_krw,ca.booking_id,t.code,t.target_type,t.trip_id
                    FROM allocation_plans ap
                    JOIN cost_allocations ca ON ca.plan_id=ap.id
                    JOIN allocation_targets t ON t.id=ca.target_id
                    WHERE ap.payment_id IN ({placeholders})
                      AND ap.plan_status='confirmed'
                    ORDER BY ap.payment_id,ap.id,ca.id""",
                ordered_ids,
            ).fetchall()
            for item in allocation_rows:
                allocations_by_payment.setdefault(int(item[0]), []).append(
                    tuple(item[1:])
                )
            amount_rows = db.execute(
                f"""SELECT id,amount_krw FROM payment_transactions
                    WHERE id IN ({placeholders})""",
                ordered_ids,
            ).fetchall()
            amounts_by_payment = {
                int(item[0]): int(item[1]) for item in amount_rows
            }
        for row in rows:
            if (
                str(row[2]) != RULE_ID
                or str(row[3]) != ACCOUNT
                or str(row[4]) != COST_TYPE
                or str(row[5]) != ALLOCATION_TARGET
                or str(row[6]) != TARGET_TYPE
                or any(int(row[index]) != expected for index, expected in (
                    (11, 0), (12, 1), (13, 1), (14, 1), (15, 0),
                ))
            ):
                issues.append("2025_cost_row_contract_invalid")
            try:
                payload = json.loads(str(row[16]))
            except (TypeError, json.JSONDecodeError):
                payload = None
            if not isinstance(payload, dict) or any(
                str(payload.get(field) or "")
                for field in ("period", "trip_code", "reservation_number")
            ):
                issues.append("2025_cost_service_fields_not_blank")
            if (
                str(row[17]) != "2025"
                or str(row[18]) != "payment.occurred_on"
                or not str(row[19]).startswith(f"{RULE_ID}:")
                or not isinstance(payload, dict)
                or str(payload.get("accounting_period") or "") != "2025"
                or str(payload.get("posting_date_source") or "")
                != "payment.occurred_on"
                or str(payload.get("idempotency_key") or "") != str(row[19])
            ):
                issues.append("2025_cost_accounting_audit_contract_invalid")
            wanted = {
                ("account", ACCOUNT, f"{RULE_ID}:account"),
                ("cost_type", COST_TYPE, f"{RULE_ID}:cost_type"),
                ("allocation_target", ALLOCATION_TARGET, f"{RULE_ID}:allocation_target"),
            }
            actual = {
                (str(item[0]), str(item[1]), str(item[2]))
                for item in decision_rows_by_payment.get(int(row[0]), [])
                if str(item[3]) == "confirmed"
            }
            if actual != wanted:
                issues.append("2025_cost_decision_contract_invalid")
            allocations = allocations_by_payment.get(int(row[0]), [])
            amount = amounts_by_payment.get(int(row[0]), 0)
            if len(allocations) != 1 or (
                str(allocations[0][4]) != ALLOCATION_TARGET
                or str(allocations[0][5]) != TARGET_TYPE
                or allocations[0][6] is not None
                or allocations[0][3] is not None
                or int(allocations[0][2]) != amount
            ):
                issues.append("2025_cost_allocation_contract_invalid")
        manifest = db.execute(
            """SELECT rule_id,candidate_count,payment_count,payment_set_sha256,
                      policy_source_sha256,partition_sha256,payload_json
               FROM direct_2025_cost_accounting_manifests WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if manifest is None:
            issues.append("2025_cost_manifest_missing")
        else:
            if str(manifest[0]) != RULE_ID or int(manifest[2]) != len(rows):
                issues.append("2025_cost_manifest_count_invalid")
            expected_set = _key_set_sha256(
                _sha(str(census["rows_by_id"][payment_id]["external_key"]).encode())
                for payment_id in sorted(actual_ids)
            )
            if str(manifest[3]) != expected_set:
                issues.append("2025_cost_manifest_membership_invalid")
        reversal_count = int(db.execute(
            """SELECT COUNT(*) FROM direct_high_coverage_reversal_inheritance
               WHERE run_id=? AND reversal_payment_id IN (%s)""" % (
                   ",".join("?" for _ in actual_ids) or "NULL"
               ),
            (run_id, *sorted(actual_ids)),
        ).fetchone()[0]) if actual_ids else 0
        if reversal_count:
            issues.append("2025_cost_reversal_inheritance_leak")
    except (sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
        issues.append(f"2025_cost_validation_error:{exc}")
    return {
        "passed": not issues,
        "issues": issues,
        "candidate_count": len(census.get("year_rows", {})) if "census" in locals() else 0,
        "payment_count": len(actual_ids) if "actual_ids" in locals() else 0,
        "accounting_target": ALLOCATION_TARGET,
    }
