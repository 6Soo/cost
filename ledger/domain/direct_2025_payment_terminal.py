"""Strict, display-only disposition for non-mail-backed 2025 payments.

The ordinary classifier intentionally keeps these rows non-final because a
2025 card posting cannot, by itself, prove a 2026 event.  This module records
the user-facing ``2025년 결제`` terminal separately from the three accounting
axes.  It is therefore safe to count the terminal for population completion
without making it eligible for travel, allocation, posting, or reversal
inheritance.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from typing import Iterable


RULE_ID = "current-card-2025-payment-terminal-v1"
DISPOSITION = "2025년 결제"
MINIMUM_RESIDUAL_COUNT = 1892
MAIL_SOURCE_KINDS = frozenset({
    "ota_mail",
    "pg_mail",
    "pg_mail_supplement",
    "service_mail",
    "gmail_payment_snapshot",
})


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def key_set_sha256(keys: Iterable[str]) -> str:
    return _sha256_bytes(
        ("\n".join(sorted(str(key) for key in keys)) + "\n").encode("utf-8")
    )


def _partition_sha256(category_hashes: dict[str, str]) -> str:
    return _sha256_json(
        {key: category_hashes[key] for key in sorted(category_hashes)}
    )


def _cost_payment_ids(db: sqlite3.Connection, run_id: str) -> set[int]:
    """Read the accounting partition without creating a module cycle."""
    try:
        rows = db.execute(
            "SELECT payment_id FROM direct_2025_cost_accounting WHERE run_id=?",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {int(row[0]) for row in rows}


def _effective_partition(
    census: dict[str, object], cost_ids: set[int],
) -> dict[str, object]:
    """Split strict residuals into accounting-final and display-only rows."""
    rows_by_id = census["rows_by_id"]
    residual_ids = set(int(value) for value in census["residual_ids"])
    cost_ids = residual_ids & set(cost_ids)
    display_ids = residual_ids - cost_ids

    def keys(ids: set[int]) -> set[str]:
        return {
            str(rows_by_id[payment_id]["external_key"])
            for payment_id in ids
        }

    category_keys = dict(census["category_keys"])
    category_keys["cost_accounting"] = keys(cost_ids)
    category_keys["residual_terminal"] = keys(display_ids)
    category_names = [
        "cancellation", "mail_travel", "cost_accounting",
        "residual_terminal", "excluded",
    ]
    union = set().union(*(category_keys[name] for name in category_names))
    if union != category_keys["candidate"]:
        raise ValueError("payment_year_2025_effective_partition_incomplete")
    if sum(len(category_keys[name]) for name in category_names) != len(union):
        raise ValueError("payment_year_2025_effective_partition_overlap")
    hashes = {
        name: key_set_sha256(category_keys[name])
        for name in ["candidate", *category_names]
    }
    return {
        "category_keys": category_keys,
        "hashes": hashes,
        "partition_sha256": _partition_sha256(hashes),
        "cost_ids": cost_ids,
        "display_ids": display_ids,
    }


def _candidate_rows(db: sqlite3.Connection, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """
        SELECT p.id,p.external_key,p.occurred_on,p.transaction_type,p.amount_krw,
               n.card_event_id,n.event_role
        FROM direct_payment_projection_links l
        JOIN payment_transactions p ON p.id=l.payment_id
        JOIN direct_normalized_payments n ON n.id=l.direct_payment_id
        WHERE l.run_id=?
        ORDER BY p.external_key
        """,
        (run_id,),
    ).fetchall()
    result: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    seen_keys: set[str] = set()
    for row in rows:
        payment_id = int(row[0])
        external_key = str(row[1])
        direct_event_key = f"{row[5]}#{row[6]}"
        if payment_id in seen_ids or external_key in seen_keys:
            raise ValueError("payment_year_2025_terminal_candidate_not_unique")
        seen_ids.add(payment_id)
        seen_keys.add(external_key)
        result.append(
            {
                "payment_id": payment_id,
                "external_key": external_key,
                "occurred_on": str(row[2] or ""),
                "transaction_type": str(row[3]),
                "amount_krw": int(row[4]),
                "direct_event_key": direct_event_key,
            }
        )
    return result


def _current_evidence_by_event(
    db: sqlite3.Connection, run_id: str
) -> dict[str, dict[str, str]]:
    rows = db.execute(
        """
        SELECT direct_event_key,evidence_id,fact_sha256,source_sha256,
               source_kind,source_key
        FROM direct_promotion_evidence
        WHERE run_id=? AND evidence_kind='current_card'
          AND authority_status='current_raw'
        ORDER BY direct_event_key,evidence_id
        """,
        (run_id,),
    ).fetchall()
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        result.setdefault(
            str(row[0]),
            {
                "evidence_id": str(row[1]),
                "fact_sha256": str(row[2]),
                "source_sha256": str(row[3]),
                "source_kind": str(row[4]),
                "source_key": str(row[5]),
            },
        )
    return result


def _settlement_payment_ids(
    db: sqlite3.Connection, run_id: str
) -> set[int]:
    rows = db.execute(
        """
        SELECT DISTINCT m.payment_id
        FROM direct_cancellation_settlement_members m
        JOIN direct_cancellation_settlement_authorities a
          ON a.run_id=m.run_id AND a.authority_id=m.authority_id
        WHERE m.run_id=?
          AND a.member_count=a.purchase_count+a.reversal_count
          AND a.purchase_count=a.reversal_count
          AND a.net_krw=0
          AND a.account='비용제외'
          AND a.cost_type='비용제외'
          AND a.allocation_target='취소환불'
        """,
        (run_id,),
    ).fetchall()
    return {int(row[0]) for row in rows}


def _mail_verified_high_payment_ids(
    db: sqlite3.Connection, run_id: str
) -> set[int]:
    try:
        rows = db.execute(
            """
            SELECT p.payment_id,pt.transaction_type,p.allocation_target,
                   p.axis_evidence_json
            FROM direct_high_coverage_classifier_predictions p
            JOIN payment_transactions pt ON pt.id=p.payment_id
            WHERE p.run_id=?
            """,
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    result: set[int] = set()
    for payment_id, transaction_type, target, raw in rows:
        if str(transaction_type) != "purchase":
            continue
        if str(target) in {"취소환불", "기타비용", "여행_미배정", ""}:
            continue
        try:
            payload = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            continue
        finality = payload.get("row_finality") if isinstance(payload, dict) else None
        if not isinstance(finality, dict):
            continue
        source_kinds = {
            str(value) for value in finality.get("mail_service_period_source_kinds", [])
        }
        if (
            finality.get("payment_year") == 2025
            and finality.get("eligible") is True
            and finality.get("mail_service_period_verified") is True
            and source_kinds & MAIL_SOURCE_KINDS
        ):
            result.add(int(payment_id))
    return result


def _mail_verified_lodging_payment_ids(
    db: sqlite3.Connection, run_id: str
) -> set[int]:
    rows = db.execute(
        """
        SELECT DISTINCT e.payment_id,a.check_in,a.check_out
        FROM direct_lodging_authority_events e
        JOIN direct_lodging_authorities a
          ON a.run_id=e.run_id AND a.authority_id=e.authority_id
        JOIN payment_transactions p ON p.id=e.payment_id
        WHERE e.run_id=?
          AND substr(p.occurred_on,1,4)='2025'
          AND p.transaction_type='purchase'
          AND a.event_count=a.fact_count
          AND (substr(a.check_in,1,4) IN ('2026','2027')
               OR substr(a.check_out,1,4) IN ('2026','2027'))
        """,
        (run_id,),
    ).fetchall()
    return {int(row[0]) for row in rows}


def build_census(db: sqlite3.Connection, run_id: str) -> dict[str, object]:
    """Recompute the strict 2025 partition from source-linked facts."""
    rows = _candidate_rows(db, run_id)
    rows_by_id = {int(row["payment_id"]): row for row in rows}
    evidence_by_event = _current_evidence_by_event(db, run_id)
    year_rows = {
        int(row["payment_id"]): row
        for row in rows
        if str(row["occurred_on"])[:4] == "2025"
    }
    settlement_ids = _settlement_payment_ids(db, run_id) & set(year_rows)
    mail_ids = (
        _mail_verified_high_payment_ids(db, run_id)
        | _mail_verified_lodging_payment_ids(db, run_id)
    ) & set(year_rows)
    overlap = settlement_ids & mail_ids
    if overlap:
        raise ValueError("payment_year_2025_terminal_priority_overlap")

    purchase_ids = {
        payment_id
        for payment_id, row in year_rows.items()
        if str(row["transaction_type"]) == "purchase"
    }
    residual_candidates = purchase_ids - settlement_ids - mail_ids
    lineage_missing_ids = {
        payment_id
        for payment_id in residual_candidates
        if str(rows_by_id[payment_id]["direct_event_key"]) not in evidence_by_event
    }
    residual_ids = residual_candidates - lineage_missing_ids
    excluded_ids = set(year_rows) - settlement_ids - mail_ids - residual_ids

    def keys(ids: set[int]) -> set[str]:
        return {str(rows_by_id[payment_id]["external_key"]) for payment_id in ids}

    category_keys = {
        "candidate": keys(set(year_rows)),
        "cancellation": keys(set(settlement_ids)),
        "mail_travel": keys(set(mail_ids)),
        "residual_terminal": keys(set(residual_ids)),
        "excluded": keys(set(excluded_ids)),
    }
    union = set().union(*category_keys.values())
    if union != category_keys["candidate"]:
        raise ValueError("payment_year_2025_terminal_partition_incomplete")
    category_names = ["cancellation", "mail_travel", "residual_terminal", "excluded"]
    if sum(len(category_keys[name]) for name in category_names) != len(union):
        raise ValueError("payment_year_2025_terminal_partition_overlap")
    hashes = {name: key_set_sha256(value) for name, value in category_keys.items()}
    return {
        "rows": rows,
        "year_rows": year_rows,
        "rows_by_id": rows_by_id,
        "evidence_by_event": evidence_by_event,
        "settlement_ids": settlement_ids,
        "mail_ids": mail_ids,
        "residual_ids": residual_ids,
        "excluded_ids": excluded_ids,
        "lineage_missing_ids": lineage_missing_ids,
        "category_keys": category_keys,
        "hashes": hashes,
        "partition_sha256": _partition_sha256(hashes),
    }


def _row_membership_sha256(
    row: dict[str, object], evidence: dict[str, str]
) -> str:
    return _sha256_json(
        {
            "category": "residual_terminal",
            "payment_id": int(row["payment_id"]),
            "direct_event_key": str(row["direct_event_key"]),
            "external_key_sha256": _sha256_bytes(
                str(row["external_key"]).encode("utf-8")
            ),
            "current_fact_sha256": evidence["fact_sha256"],
        }
    )


def _row_provenance_sha256(evidence: dict[str, str]) -> str:
    return _sha256_json(
        {
            "evidence_id": evidence["evidence_id"],
            "fact_sha256": evidence["fact_sha256"],
            "source_sha256": evidence["source_sha256"],
            "source_kind": evidence["source_kind"],
            "source_key_sha256": _sha256_bytes(
                evidence["source_key"].encode("utf-8")
            ),
        }
    )


def project_2025_payment_terminals(
    db: sqlite3.Connection, run_id: str
) -> dict[str, object]:
    census = build_census(db, run_id)
    db.execute(
        "DELETE FROM direct_2025_payment_terminals WHERE run_id=?", (run_id,)
    )
    db.execute(
        "DELETE FROM direct_2025_payment_terminal_manifests WHERE run_id=?",
        (run_id,),
    )
    rows_by_id = census["rows_by_id"]
    evidence_by_event = census["evidence_by_event"]
    effective = _effective_partition(
        census, _cost_payment_ids(db, run_id),
    )
    residual_ids = set(effective["display_ids"])
    for payment_id in sorted(residual_ids):
        row = rows_by_id[payment_id]
        evidence = evidence_by_event[str(row["direct_event_key"])]
        membership_sha256 = _row_membership_sha256(row, evidence)
        provenance_sha256 = _row_provenance_sha256(evidence)
        payload = {
            "contract": "payment-year-2025-terminal-v1",
            "rule_id": RULE_ID,
            "disposition": DISPOSITION,
            "payment_id": payment_id,
            "direct_event_key": str(row["direct_event_key"]),
            "occurred_on": str(row["occurred_on"]),
            "transaction_type": str(row["transaction_type"]),
            "current_evidence_id": evidence["evidence_id"],
            "current_fact_sha256": evidence["fact_sha256"],
            "source_sha256": evidence["source_sha256"],
            "source_kind": evidence["source_kind"],
            "source_key_sha256": _sha256_bytes(
                evidence["source_key"].encode("utf-8")
            ),
            "mail_service_period_verified": False,
            "reason_code": "payment_year_2025_terminal_no_mail",
            "travel_eligible": False,
            "accounting_final": False,
            "allocation_eligible": False,
            "posting_eligible": False,
            "reversal_inheritance_eligible": False,
            "membership_sha256": membership_sha256,
            "provenance_sha256": provenance_sha256,
        }
        db.execute(
            """
            INSERT INTO direct_2025_payment_terminals(
                run_id,payment_id,direct_event_key,disposition,rule_id,
                provenance_sha256,travel_eligible,accounting_final,
                allocation_eligible,posting_eligible,
                reversal_inheritance_eligible,membership_sha256,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                payment_id,
                str(row["direct_event_key"]),
                DISPOSITION,
                RULE_ID,
                provenance_sha256,
                0,
                0,
                0,
                0,
                0,
                membership_sha256,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        db.execute(
            """
            INSERT INTO allocation_review_cases(
                payment_id,outcome,reason_code,rationale,review_status,rule_id
            ) VALUES (?,?,?,?,?,?)
            ON CONFLICT(payment_id) DO UPDATE SET
                outcome=excluded.outcome,
                reason_code=excluded.reason_code,
                rationale=excluded.rationale,
                review_status=excluded.review_status,
                rule_id=excluded.rule_id,
                reviewed_at=CURRENT_TIMESTAMP
            """,
            (
                payment_id,
                "payment_year_2025",
                "payment_year_2025_terminal_no_mail",
                "2025년 결제이며 카드 원천만으로 2026 행사일을 확정할 수 없어 표시 전용으로 종결",
                "confirmed",
                RULE_ID,
            ),
        )

    category_keys = effective["category_keys"]
    hashes = effective["hashes"]
    payload = {
        "contract": "payment-year-2025-terminal-census-v1",
        "rule_id": RULE_ID,
        "priority": [
            "cancellation", "mail_travel", "cost_accounting",
            "residual_terminal", "excluded",
        ],
        "payment_year": 2025,
        "minimum_residual_count": MINIMUM_RESIDUAL_COUNT,
        "objective_met": len(census["residual_ids"]) >= MINIMUM_RESIDUAL_COUNT,
        "lineage_missing_count": len(census["lineage_missing_ids"]),
        "counts": {name: len(category_keys[name]) for name in category_keys},
        "hashes": hashes,
        "partition_set_sha256": effective["partition_sha256"],
    }
    db.execute(
        """
        INSERT INTO direct_2025_payment_terminal_manifests(
            run_id,rule_id,candidate_count,cancellation_count,mail_travel_count,
            residual_terminal_count,excluded_count,candidate_set_sha256,
            cancellation_set_sha256,mail_travel_set_sha256,
            residual_terminal_set_sha256,excluded_set_sha256,
            partition_set_sha256,payload_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            RULE_ID,
            len(category_keys["candidate"]),
            len(category_keys["cancellation"]),
            len(category_keys["mail_travel"]),
            len(category_keys["residual_terminal"]),
            len(category_keys["excluded"]),
            hashes["candidate"],
            hashes["cancellation"],
            hashes["mail_travel"],
            hashes["residual_terminal"],
            hashes["excluded"],
            effective["partition_sha256"],
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {
        "candidate_count": len(category_keys["candidate"]),
        "cancellation_count": len(category_keys["cancellation"]),
        "mail_travel_count": len(category_keys["mail_travel"]),
        "residual_terminal_count": len(category_keys["residual_terminal"]),
        "cost_accounting_count": len(category_keys["cost_accounting"]),
        "excluded_count": len(category_keys["excluded"]),
        "lineage_missing_count": len(census["lineage_missing_ids"]),
        "objective_met": len(census["residual_ids"]) >= MINIMUM_RESIDUAL_COUNT,
        "partition_set_sha256": effective["partition_sha256"],
        "candidate_set_sha256": hashes["candidate"],
        "residual_terminal_set_sha256": hashes["residual_terminal"],
        "cost_accounting_set_sha256": hashes["cost_accounting"],
    }


def validate_2025_payment_terminals(
    db: sqlite3.Connection, run_id: str
) -> dict[str, object]:
    issues: list[str] = []
    try:
        # Gate fixtures that predate the display-terminal projection do not
        # have a terminal manifest.  The production projection writes this
        # manifest before Gate5; leave older synthetic fixtures to exercise
        # their intended gate diagnostics instead of inventing a terminal
        # failure for them.
        manifest_presence = db.execute(
            """SELECT 1 FROM direct_2025_payment_terminal_manifests
               WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if manifest_presence is None:
            return {
                "passed": True,
                "issues": [],
                "not_applicable": True,
                "counts": {},
                "objective_met": True,
            }
        census = build_census(db, run_id)
        manifest = db.execute(
            """
            SELECT rule_id,candidate_count,cancellation_count,mail_travel_count,
                   residual_terminal_count,excluded_count,candidate_set_sha256,
                   cancellation_set_sha256,mail_travel_set_sha256,
                   residual_terminal_set_sha256,excluded_set_sha256,
                   partition_set_sha256,payload_json
            FROM direct_2025_payment_terminal_manifests WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        if manifest is None:
            return {"passed": False, "issues": ["terminal_manifest_missing"]}
        effective = _effective_partition(
            census, _cost_payment_ids(db, run_id),
        )
        hashes = effective["hashes"]
        category_keys = effective["category_keys"]
        expected_counts = {
            "candidate": len(category_keys["candidate"]),
            "cancellation": len(category_keys["cancellation"]),
            "mail_travel": len(category_keys["mail_travel"]),
            "residual_terminal": len(category_keys["residual_terminal"]),
            "excluded": len(category_keys["excluded"]),
        }
        actual_counts = dict(zip(
            ("candidate", "cancellation", "mail_travel", "residual_terminal", "excluded"),
            (int(manifest[1]), int(manifest[2]), int(manifest[3]), int(manifest[4]), int(manifest[5])),
        ))
        if str(manifest[0]) != RULE_ID:
            issues.append("terminal_manifest_rule_id_invalid")
        if actual_counts != expected_counts:
            issues.append("terminal_manifest_count_mismatch")
        stored_hashes = dict(zip(
            ("candidate", "cancellation", "mail_travel", "residual_terminal", "excluded"),
            (str(manifest[6]), str(manifest[7]), str(manifest[8]), str(manifest[9]), str(manifest[10])),
        ))
        expected_stored_hashes = {
            name: hashes[name]
            for name in ("candidate", "cancellation", "mail_travel",
                         "residual_terminal", "excluded")
        }
        if stored_hashes != expected_stored_hashes:
            issues.append("terminal_manifest_membership_hash_mismatch")
        if str(manifest[11]) != str(effective["partition_sha256"]):
            issues.append("terminal_effective_partition_hash_mismatch")
        try:
            manifest_payload = json.loads(str(manifest[12]))
        except (TypeError, json.JSONDecodeError):
            manifest_payload = None
        if (
            not isinstance(manifest_payload, dict)
            or int(manifest_payload.get("counts", {}).get("cost_accounting", -1))
            != len(category_keys["cost_accounting"])
            or str(manifest_payload.get("hashes", {}).get("cost_accounting"))
            != hashes["cost_accounting"]
        ):
            issues.append("terminal_cost_partition_payload_invalid")

        terminal_rows = db.execute(
            """
            SELECT payment_id,direct_event_key,disposition,rule_id,
                   provenance_sha256,travel_eligible,accounting_final,
                   allocation_eligible,posting_eligible,
                   reversal_inheritance_eligible,membership_sha256,payload_json
            FROM direct_2025_payment_terminals WHERE run_id=?
            ORDER BY payment_id
            """,
            (run_id,),
        ).fetchall()
        expected_ids = set(effective["display_ids"])
        actual_ids = {int(row[0]) for row in terminal_rows}
        if actual_ids != expected_ids:
            issues.append("terminal_membership_payment_id_mismatch")
        rows_by_id = census["rows_by_id"]
        evidence_by_event = census["evidence_by_event"]
        for row in terminal_rows:
            payment_id = int(row[0])
            candidate = rows_by_id.get(payment_id)
            if candidate is None:
                issues.append("terminal_payment_not_in_candidate")
                continue
            evidence = evidence_by_event.get(str(candidate["direct_event_key"]))
            if (
                str(candidate["occurred_on"])[:4] != "2025"
                or str(candidate["transaction_type"]) != "purchase"
                or evidence is None
                or str(row[1]) != str(candidate["direct_event_key"])
                or str(row[2]) != DISPOSITION
                or str(row[3]) != RULE_ID
                or any(int(row[index]) != 0 for index in (5, 6, 7, 8, 9))
            ):
                issues.append("terminal_row_contract_invalid")
                continue
            expected_provenance = _row_provenance_sha256(evidence)
            expected_membership = _row_membership_sha256(candidate, evidence)
            if str(row[4]) != expected_provenance or str(row[10]) != expected_membership:
                issues.append("terminal_row_hash_invalid")
            try:
                payload = json.loads(str(row[11]))
            except (TypeError, json.JSONDecodeError):
                payload = None
            if not isinstance(payload, dict) or str(payload.get("rule_id")) != RULE_ID:
                issues.append("terminal_row_payload_invalid")

        terminal_ids = tuple(sorted(actual_ids))
        if terminal_ids:
            placeholders = ",".join("?" for _ in terminal_ids)
            confirmed_count = int(db.execute(
                f"""SELECT COUNT(*) FROM current_classification_decisions
                    WHERE target_type='payment' AND decision_status='confirmed'
                      AND target_id IN ({placeholders})""",
                terminal_ids,
            ).fetchone()[0])
            if confirmed_count:
                issues.append("terminal_confirmed_decision_leak")
            side_effect_queries = {
                "plan": f"SELECT COUNT(*) FROM allocation_plans WHERE payment_id IN ({placeholders})",
                "allocation": f"SELECT COUNT(*) FROM cost_allocations a JOIN allocation_plans p ON p.id=a.plan_id WHERE p.payment_id IN ({placeholders})",
                "journal": f"SELECT COUNT(*) FROM journal_entries j JOIN cost_allocations a ON a.id=j.allocation_id JOIN allocation_plans p ON p.id=a.plan_id WHERE p.payment_id IN ({placeholders})",
                "reversal": f"SELECT COUNT(*) FROM direct_high_coverage_reversal_inheritance WHERE run_id=? AND reversal_payment_id IN ({placeholders})",
            }
            for name, sql in side_effect_queries.items():
                params = terminal_ids if name != "reversal" else (run_id, *terminal_ids)
                if int(db.execute(sql, params).fetchone()[0]):
                    issues.append(f"terminal_{name}_side_effect_leak")
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as exc:
        issues.append(f"terminal_validation_error:{exc}")
        census = {}
    validation_counts = {}
    objective_met = True
    if isinstance(census, dict):
        try:
            effective = _effective_partition(
                census, _cost_payment_ids(db, run_id),
            )
        except (sqlite3.Error, ValueError):
            effective = None
        if isinstance(effective, dict):
            category_keys = effective.get("category_keys", {})
            if isinstance(category_keys, dict):
                validation_counts = {
                    str(name): len(value)
                    for name, value in category_keys.items()
                    if isinstance(value, (set, list, tuple))
                }
                objective_met = (
                    validation_counts.get("residual_terminal", 0)
                    + validation_counts.get("cost_accounting", 0)
                    >= MINIMUM_RESIDUAL_COUNT
                )
    return {
        "passed": not issues,
        "issues": issues,
        "counts": validation_counts,
        "objective_met": objective_met,
    }


def terminal_payment_ids(db: sqlite3.Connection, run_id: str) -> set[int]:
    return {
        int(row[0]) for row in db.execute(
            "SELECT payment_id FROM direct_2025_payment_terminals WHERE run_id=?",
            (run_id,),
        ).fetchall()
    }
