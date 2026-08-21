"""Fail-closed terminal authority for exact current-card cancellation sets.

The authority is regenerated from the complete current-card universe.  It does
not consume historical labels or even trust the projected relation table.
Only closed components with exact identity/card keys, valid chronology, equal
purchase/reversal cardinality, and a signed KRW sum of zero are terminal.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date


AUTHORITY_CONTRACT = "current-card-net-zero-settlement-v1"
MANIFEST_CONTRACT = "current-card-net-zero-settlement-manifest-v1"
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")
TERMINAL_AXES = {
    "account": "비용제외",
    "cost_type": "비용제외",
    "allocation_target": "취소환불",
}
PRODUCTION_SCOPE_COUNT = 5328
PRODUCTION_AUTHORITY_COUNT = 259
PRODUCTION_SET_AUTHORITY_COUNT = 54
PRODUCTION_ACCEPTED_MEMBER_COUNT = 544
RATIONALE = "현재 카드 원본 전체에서 재생성한 완전상계 묶음으로 비용대상에서 제외"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _approval_digits(value: object) -> str:
    text = str(value or "").strip()
    return (
        text
        if text and text.isascii() and text.isdigit() and len(text) <= 32
        and bool(text.strip("0"))
        else ""
    )


def _payload_scalar(payload: dict[str, object], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            return str(value).strip()
    return ""


def _foreign_text(value: object) -> str:
    return str(value or "").strip().lstrip("-")


def _valid_day(value: object) -> date | None:
    text = str(value or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def _current_event_fact(
    *, direct_event_key: str, source_kind: str, source_key: str,
    source_sha256: str, identity_status: str, source_system: str,
    occurred_on: str, merchant: str, approval_number: str, amount_krw: int,
    transaction_type: str, event_role: str, payload_json: str,
    payload: dict[str, object],
) -> dict[str, object]:
    fact = {
        "direct_event_key": direct_event_key,
        "source_kind": source_kind,
        "source_key": source_key,
        "source_sha256": source_sha256,
        "identity_status": identity_status,
        "source_system": source_system,
        "occurred_on": occurred_on,
        "merchant": merchant,
        "approval_number": approval_number,
        "amount_krw": amount_krw,
        "transaction_type": transaction_type,
        "event_role": event_role,
        "card4": _payload_scalar(payload, "card4", "card_last4", "last4"),
        "currency": _payload_scalar(payload, "currency", "foreign_currency"),
        "foreign_amount": _payload_scalar(
            payload, "foreign_amount", "foreign", "local_amount",
        ),
        "payload_sha256": _sha(payload_json.encode("utf-8")),
    }
    fact["current_event_sha256"] = _sha(fact)
    fact["current_evidence_id"] = (
        "current-card:" + str(fact["current_event_sha256"])
    )
    return fact


def _current_rows(db: object, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT p.id,p.external_key,p.source_system,p.occurred_on,p.merchant,
                  p.approval_number,p.amount_krw,p.transaction_type,
                  e.identity_status,d.card_event_id,d.event_role,
                  s.source_kind,s.source_key,s.source_sha256,s.payload_json,
                  pe.evidence_id,pe.fact_sha256
           FROM direct_payment_projection_links l
           JOIN payment_transactions p ON p.id=l.payment_id
           JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
           JOIN direct_card_events e ON e.source_record_id=d.source_record_id
           JOIN direct_source_records s ON s.id=d.source_record_id
           JOIN direct_promotion_evidence pe
             ON pe.run_id=l.run_id AND pe.evidence_kind='current_card'
            AND pe.authority_status='current_raw'
            AND pe.direct_event_key=d.card_event_id || '#' || d.event_role
            AND pe.source_kind=s.source_kind AND pe.source_key=s.source_key
            AND pe.source_sha256=s.source_sha256
           WHERE l.run_id=? ORDER BY p.external_key""",
        (run_id,),
    ).fetchall()
    linked_count = int(db.execute(
        "SELECT COUNT(*) FROM direct_payment_projection_links WHERE run_id=?",
        (run_id,),
    ).fetchone()[0])
    if len(rows) != linked_count or not rows:
        raise ValueError("settlement_current_scope_join_invalid")
    result: list[dict[str, object]] = []
    event_keys: set[str] = set()
    payment_ids: set[int] = set()
    for raw in rows:
        payload_json = str(raw[14])
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("settlement_current_payload_invalid") from exc
        if not isinstance(payload, dict) or _sha(payload) != str(raw[13]):
            raise ValueError("settlement_current_source_binding_invalid")
        direct_event_key = f"{raw[9]}#{raw[10]}"
        fact = _current_event_fact(
            direct_event_key=direct_event_key,
            source_kind=str(raw[11]), source_key=str(raw[12]),
            source_sha256=str(raw[13]), identity_status=str(raw[8]),
            source_system=str(raw[2]), occurred_on=str(raw[3] or ""),
            merchant=str(raw[4] or ""),
            approval_number=str(raw[5] or ""), amount_krw=int(raw[6]),
            transaction_type=str(raw[7]), event_role=str(raw[10]),
            payload_json=payload_json, payload=payload,
        )
        if (
            fact["source_kind"] != "card_raw"
            or payload.get("src") != fact["source_system"]
            or raw[15] != fact["current_evidence_id"]
            or raw[16] != fact["current_event_sha256"]
            or not _is_sha256(fact["source_sha256"])
            or direct_event_key in event_keys or int(raw[0]) in payment_ids
        ):
            raise ValueError("settlement_current_evidence_binding_invalid")
        event_keys.add(direct_event_key)
        payment_ids.add(int(raw[0]))
        result.append({
            **fact,
            "payment_id": int(raw[0]),
            "external_key": str(raw[1]),
            "payload": payload,
        })
    return result


def _component(
    kind: str, relation_key: object, members: list[dict[str, object]],
) -> dict[str, object]:
    ordered = sorted(members, key=lambda row: str(row["direct_event_key"]))
    member_descriptor = [
        {
            "direct_event_key": row["direct_event_key"],
            "current_evidence_id": row["current_evidence_id"],
            "source_system": row["source_system"],
            "source_key": row["source_key"],
            "source_sha256": row["source_sha256"],
            "current_event_sha256": row["current_event_sha256"],
            "transaction_type": row["transaction_type"],
            "member_role": (
                "purchase" if row["transaction_type"] == "purchase"
                else "reversal"
            ),
            "amount_krw": row["amount_krw"],
            "occurred_on": row["occurred_on"],
        }
        for row in ordered
    ]
    source_descriptor = sorted({
        (str(row["source_key"]), str(row["source_sha256"])) for row in ordered
    })
    purchase_count = sum(
        row["transaction_type"] == "purchase" for row in ordered
    )
    reversal_count = len(ordered) - purchase_count
    relation_key_sha256 = _sha({
        "authority_kind": kind, "relation_key": relation_key,
    })
    member_set_sha256 = _sha(member_descriptor)
    source_set_sha256 = _sha([list(row) for row in source_descriptor])
    payload = {
        "contract": AUTHORITY_CONTRACT,
        "authority_kind": kind,
        "relation_key_sha256": relation_key_sha256,
        "member_set_sha256": member_set_sha256,
        "source_set_sha256": source_set_sha256,
        "member_count": len(ordered),
        "purchase_count": purchase_count,
        "reversal_count": reversal_count,
        "net_krw": sum(int(row["amount_krw"]) for row in ordered),
        "axes": dict(TERMINAL_AXES),
        "members": member_descriptor,
        "complete_current_relation_universe": True,
        "amount_tolerance_krw": 0,
        "individual_pair_asserted": (
            kind == "approval_exact" and len(ordered) == 2
        ),
    }
    authority_sha256 = _sha(payload)
    return {
        "authority_id": "settlement-authority:" + authority_sha256,
        "authority_sha256": authority_sha256,
        "authority_kind": kind,
        "relation_key_sha256": relation_key_sha256,
        "member_set_sha256": member_set_sha256,
        "source_set_sha256": source_set_sha256,
        "purchase_count": purchase_count,
        "reversal_count": reversal_count,
        "net_krw": payload["net_krw"],
        "individual_pair_asserted": (
            kind == "approval_exact" and len(ordered) == 2
        ),
        "payload": payload,
        "members": ordered,
    }


def _evaluate(
    members: list[dict[str, object]], *,
    purchase_required: int | None,
) -> str:
    purchases = [
        row for row in members if row["transaction_type"] == "purchase"
    ]
    reversals = [
        row for row in members
        if row["transaction_type"] in {"cancellation", "refund"}
    ]
    if (
        not purchases or len(purchases) != len(reversals)
        or (purchase_required is not None and len(purchases) != purchase_required)
    ):
        return "component_cardinality_mismatch"
    parsed_days = [_valid_day(row["occurred_on"]) for row in members]
    if any(day is None for day in parsed_days):
        return "component_date_invalid"
    purchase_days = [_valid_day(row["occurred_on"]) for row in purchases]
    reversal_days = [_valid_day(row["occurred_on"]) for row in reversals]
    if max(day for day in purchase_days if day is not None) > min(
        day for day in reversal_days if day is not None
    ):
        return "component_date_order_invalid"
    if any(row["identity_status"] != "unique" for row in members):
        return "component_identity_not_unique"
    if sum(int(row["amount_krw"]) for row in members) != 0:
        return "component_net_nonzero"
    return "accepted"


def _authority_models(
    db: object, run_id: str,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    rows = _current_rows(db, run_id)
    reason_by_event = {
        str(row["direct_event_key"]): "not_exact_reversal_component"
        for row in rows
    }
    approval_purchases: dict[
        tuple[str, str, str], list[dict[str, object]]
    ] = defaultdict(list)
    approval_reversals: dict[
        tuple[str, str, str], list[dict[str, object]]
    ] = defaultdict(list)
    kbo_purchases: dict[
        tuple[str, str, str, str], list[dict[str, object]]
    ] = defaultdict(list)
    kbo_reversals: dict[
        tuple[str, str, str, str], list[dict[str, object]]
    ] = defaultdict(list)

    for row in rows:
        payload = row["payload"]
        source = str(row["source_system"])
        transaction_type = str(row["transaction_type"])
        if source in {"HAN", "KBD"}:
            card4 = str(payload.get("card4") or "")
            if transaction_type == "purchase":
                approval = _approval_digits(
                    row["approval_number"] or payload.get("appr")
                )
                if approval and len(card4) == 4 and card4.isdigit():
                    approval_purchases[(source, card4, approval)].append(row)
            elif transaction_type in {"cancellation", "refund"}:
                original = _approval_digits(payload.get("orig_appr"))
                if original and len(card4) == 4 and card4.isdigit():
                    approval_reversals[(source, card4, original)].append(row)
                else:
                    reason_by_event[str(row["direct_event_key"])] = (
                        "relation_key_invalid"
                    )
        elif source == "KBO":
            key = (
                str(payload.get("card4") or ""),
                str(payload.get("currency") or ""),
                _foreign_text(payload.get("foreign")),
                str(row["merchant"]),
            )
            key_valid = (
                len(key[0]) == 4 and key[0].isdigit()
                and bool(key[1]) and bool(key[2]) and bool(key[3])
            )
            if transaction_type == "purchase" and key_valid:
                kbo_purchases[key].append(row)
            elif transaction_type in {"cancellation", "refund"}:
                if key_valid:
                    kbo_reversals[key].append(row)
                else:
                    reason_by_event[str(row["direct_event_key"])] = (
                        "relation_key_invalid"
                    )

    accepted: list[dict[str, object]] = []
    candidate_members: set[str] = set()
    for relation_key in sorted(approval_reversals):
        members = (
            approval_purchases.get(relation_key, [])
            + approval_reversals[relation_key]
        )
        keys = {str(row["direct_event_key"]) for row in members}
        if keys & candidate_members:
            raise ValueError("settlement_candidate_component_overlap")
        candidate_members |= keys
        result = _evaluate(members, purchase_required=1)
        if result == "accepted":
            accepted.append(_component("approval_exact", relation_key, members))
        else:
            for key in keys:
                reason_by_event[key] = result

    for relation_key in sorted(kbo_reversals):
        members = kbo_purchases.get(relation_key, []) + kbo_reversals[relation_key]
        keys = {str(row["direct_event_key"]) for row in members}
        if keys & candidate_members:
            raise ValueError("settlement_candidate_component_overlap")
        candidate_members |= keys
        result = _evaluate(members, purchase_required=None)
        if result == "accepted":
            accepted.append(_component("kbo_exact_set", relation_key, members))
        else:
            for key in keys:
                reason_by_event[key] = result

    accepted_keys = {
        str(row["direct_event_key"])
        for authority in accepted for row in authority["members"]
    }
    if len(accepted_keys) != sum(len(row["members"]) for row in accepted):
        raise ValueError("settlement_accepted_component_overlap")
    withheld = [
        {
            "direct_event_key": str(row["direct_event_key"]),
            "current_evidence_id": str(row["current_evidence_id"]),
            "reason_code": reason_by_event[str(row["direct_event_key"])],
            "detail_sha256": _sha({
                "contract": AUTHORITY_CONTRACT,
                "direct_event_key": row["direct_event_key"],
                "current_evidence_id": row["current_evidence_id"],
                "reason_code": reason_by_event[str(row["direct_event_key"])],
            }),
        }
        for row in rows if str(row["direct_event_key"]) not in accepted_keys
    ]
    current_keys = {str(row["direct_event_key"]) for row in rows}
    withheld_keys = {str(row["direct_event_key"]) for row in withheld}
    if (
        accepted_keys & withheld_keys
        or accepted_keys | withheld_keys != current_keys
        or len(withheld_keys) != len(withheld)
    ):
        raise ValueError("settlement_scope_partition_invalid")
    if len(rows) == PRODUCTION_SCOPE_COUNT and (
        len(accepted) != PRODUCTION_AUTHORITY_COUNT
        or sum(
            row["authority_kind"] == "kbo_exact_set" for row in accepted
        ) != PRODUCTION_SET_AUTHORITY_COUNT
        or len(accepted_keys) != PRODUCTION_ACCEPTED_MEMBER_COUNT
    ):
        raise ValueError("settlement_production_census_drift")
    return accepted, withheld, rows


def project_current_cancellation_settlements(
    db: object, run_id: str,
) -> dict[str, int]:
    existing = sum(int(db.execute(
        f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,),
    ).fetchone()[0]) for table in (
        "direct_cancellation_settlement_authorities",
        "direct_cancellation_settlement_members",
        "direct_cancellation_settlement_derivations",
        "direct_cancellation_settlement_withheld",
    ))
    if existing:
        raise ValueError("settlement_projection_already_exists")
    authorities, withheld, rows = _authority_models(db, run_id)
    db.execute("SAVEPOINT cancellation_settlement_projection")
    try:
        for item in withheld:
            db.execute(
                """INSERT INTO direct_cancellation_settlement_withheld(
                     run_id,direct_event_key,current_evidence_id,reason_code,
                     detail_sha256) VALUES (?,?,?,?,?)""",
                (
                    run_id, item["direct_event_key"],
                    item["current_evidence_id"], item["reason_code"],
                    item["detail_sha256"],
                ),
            )
        decision_count = 0
        member_count = 0
        set_count = 0
        for authority in authorities:
            db.execute(
                """INSERT INTO direct_cancellation_settlement_authorities(
                     run_id,authority_id,authority_kind,relation_key_sha256,
                     member_set_sha256,source_set_sha256,authority_sha256,
                     member_count,purchase_count,reversal_count,net_krw,
                     account,cost_type,allocation_target,
                     individual_pair_asserted,payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, authority["authority_id"],
                    authority["authority_kind"],
                    authority["relation_key_sha256"],
                    authority["member_set_sha256"],
                    authority["source_set_sha256"],
                    authority["authority_sha256"],
                    len(authority["members"]), authority["purchase_count"],
                    authority["reversal_count"], authority["net_krw"],
                    TERMINAL_AXES["account"], TERMINAL_AXES["cost_type"],
                    TERMINAL_AXES["allocation_target"],
                    int(authority["individual_pair_asserted"]),
                    _canonical(authority["payload"]).decode("utf-8"),
                ),
            )
            for member in authority["members"]:
                payment_id = int(member["payment_id"])
                if int(db.execute(
                    """SELECT COUNT(*) FROM current_classification_decisions
                       WHERE target_type='payment' AND target_id=?
                         AND dimension IN ('account','cost_type',
                                           'allocation_target')""",
                    (payment_id,),
                ).fetchone()[0]):
                    raise ValueError("settlement_existing_decision_conflict")
                role = (
                    "purchase" if member["transaction_type"] == "purchase"
                    else "reversal"
                )
                db.execute(
                    """INSERT INTO direct_cancellation_settlement_members(
                         run_id,authority_id,direct_event_key,current_evidence_id,
                         payment_id,source_key,source_sha256,transaction_type,
                         member_role,amount_krw,occurred_on)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, authority["authority_id"],
                        member["direct_event_key"],
                        member["current_evidence_id"], payment_id,
                        member["source_key"], member["source_sha256"],
                        member["transaction_type"], role,
                        member["amount_krw"], member["occurred_on"],
                    ),
                )
                for dimension in ACTIVE_DIMENSIONS:
                    value = TERMINAL_AXES[dimension]
                    derivation_id = "settlement-derivation:" + _sha({
                        "authority_id": authority["authority_id"],
                        "direct_event_key": member["direct_event_key"],
                        "dimension": dimension, "value": value,
                    })
                    decision_id = int(db.execute(
                        """INSERT INTO classification_decisions(
                             target_type,target_id,dimension,value,confidence,
                             confidence_label,decision_status,rule_id,rationale)
                           VALUES ('payment',?,?,?,?,?,'confirmed',?,?)""",
                        (
                            payment_id, dimension, value, 1.0,
                            "현재원본완전상계", AUTHORITY_CONTRACT, RATIONALE,
                        ),
                    ).lastrowid)
                    db.execute(
                        """INSERT INTO direct_cancellation_settlement_derivations(
                             derivation_id,run_id,authority_id,payment_id,
                             direct_event_key,dimension,value,rule_id,
                             current_evidence_id,derivation_status,conflict_count)
                           VALUES (?,?,?,?,?,?,?,?,?,'pass',0)""",
                        (
                            derivation_id, run_id, authority["authority_id"],
                            payment_id, member["direct_event_key"], dimension,
                            value, AUTHORITY_CONTRACT,
                            member["current_evidence_id"],
                        ),
                    )
                    db.execute(
                        """INSERT INTO
                           direct_cancellation_settlement_decision_bindings(
                             run_id,decision_id,derivation_id)
                           VALUES (?,?,?)""",
                        (run_id, decision_id, derivation_id),
                    )
                    decision_count += 1
                member_count += 1
            set_count += authority["authority_kind"] == "kbo_exact_set"
    except Exception:
        db.execute("ROLLBACK TO cancellation_settlement_projection")
        db.execute("RELEASE cancellation_settlement_projection")
        raise
    else:
        db.execute("RELEASE cancellation_settlement_projection")
    return {
        "scope_payments": len(rows),
        "authorities": len(authorities),
        "set_authorities": int(set_count),
        "payments": member_count,
        "decisions": decision_count,
        "withheld_payments": len(withheld),
    }


def validate_cancellation_settlement_authorities(
    db: object, run_id: str, *, require_terminal: bool = False,
) -> dict[str, object]:
    issues: list[str] = []
    expected_authorities, expected_withheld, current_rows = _authority_models(
        db, run_id,
    )
    expected_authority_rows = [
        (
            row["authority_id"], row["authority_kind"],
            row["relation_key_sha256"], row["member_set_sha256"],
            row["source_set_sha256"], row["authority_sha256"],
            len(row["members"]), row["purchase_count"], row["reversal_count"],
            row["net_krw"], TERMINAL_AXES["account"],
            TERMINAL_AXES["cost_type"], TERMINAL_AXES["allocation_target"],
            int(row["individual_pair_asserted"]),
            _canonical(row["payload"]).decode("utf-8"),
        )
        for row in sorted(expected_authorities, key=lambda item: item["authority_id"])
    ]
    actual_authority_rows = [
        tuple(row) for row in db.execute(
            """SELECT authority_id,authority_kind,relation_key_sha256,
                      member_set_sha256,source_set_sha256,authority_sha256,
                      member_count,purchase_count,reversal_count,net_krw,
                      account,cost_type,allocation_target,
                      individual_pair_asserted,payload_json
               FROM direct_cancellation_settlement_authorities
               WHERE run_id=? ORDER BY authority_id""",
            (run_id,),
        ).fetchall()
    ]
    if actual_authority_rows != expected_authority_rows:
        issues.append("settlement_authority_set_mismatch")

    expected_members = sorted(
        (
            authority["authority_id"], member["direct_event_key"],
            member["current_evidence_id"], member["external_key"],
            member["source_key"], member["source_sha256"],
            member["transaction_type"],
            "purchase" if member["transaction_type"] == "purchase" else "reversal",
            member["amount_krw"], member["occurred_on"],
        )
        for authority in expected_authorities for member in authority["members"]
    )
    actual_members = [
        tuple(row) for row in db.execute(
            """SELECT m.authority_id,m.direct_event_key,m.current_evidence_id,
                      p.external_key,m.source_key,m.source_sha256,
                      m.transaction_type,m.member_role,m.amount_krw,m.occurred_on
               FROM direct_cancellation_settlement_members m
               JOIN payment_transactions p ON p.id=m.payment_id
               WHERE m.run_id=?
               ORDER BY m.authority_id,m.direct_event_key""",
            (run_id,),
        ).fetchall()
    ]
    if actual_members != expected_members:
        issues.append("settlement_member_set_mismatch")

    expected_withheld_rows = sorted(
        (
            row["direct_event_key"], row["current_evidence_id"],
            row["reason_code"], row["detail_sha256"],
        ) for row in expected_withheld
    )
    actual_withheld_rows = [
        tuple(row) for row in db.execute(
            """SELECT direct_event_key,current_evidence_id,reason_code,
                      detail_sha256
               FROM direct_cancellation_settlement_withheld
               WHERE run_id=? ORDER BY direct_event_key""",
            (run_id,),
        ).fetchall()
    ]
    if actual_withheld_rows != expected_withheld_rows:
        issues.append("settlement_withheld_set_mismatch")

    expected_decisions = sorted(
        (
            member["external_key"], dimension, TERMINAL_AXES[dimension],
            AUTHORITY_CONTRACT,
            "settlement-derivation:" + _sha({
                "authority_id": authority["authority_id"],
                "direct_event_key": member["direct_event_key"],
                "dimension": dimension, "value": TERMINAL_AXES[dimension],
            }),
        )
        for authority in expected_authorities for member in authority["members"]
        for dimension in ACTIVE_DIMENSIONS
    )
    actual_decisions = [
        tuple(row) for row in db.execute(
            """SELECT p.external_key,d.dimension,d.value,d.rule_id,b.derivation_id
               FROM direct_cancellation_settlement_decision_bindings b
               JOIN classification_decisions d ON d.id=b.decision_id
               JOIN payment_transactions p ON p.id=d.target_id
               JOIN direct_cancellation_settlement_derivations x
                 ON x.run_id=b.run_id AND x.derivation_id=b.derivation_id
                AND x.payment_id=d.target_id AND x.dimension=d.dimension
                AND x.value=d.value AND x.rule_id=d.rule_id
               WHERE b.run_id=? AND d.target_type='payment'
                 AND d.decision_status='confirmed' AND d.confidence=1.0
                 AND d.confidence_label='현재원본완전상계'
                 AND d.rationale=?
                 AND x.derivation_status='pass' AND x.conflict_count=0
               ORDER BY p.external_key,d.dimension""",
            (run_id, RATIONALE),
        ).fetchall()
    ]
    if actual_decisions != expected_decisions:
        issues.append("settlement_decision_set_mismatch")
    promoted_count = int(db.execute(
        """SELECT COUNT(*) FROM current_independently_promoted_decisions d
           JOIN direct_cancellation_settlement_decision_bindings b
             ON b.run_id=d.run_id AND b.decision_id=d.id
           WHERE d.run_id=?""",
        (run_id,),
    ).fetchone()[0])
    if promoted_count != len(expected_decisions):
        issues.append("settlement_promoted_view_mismatch")

    accepted_keys = {row[1] for row in expected_members}
    withheld_keys = {row[0] for row in expected_withheld_rows}
    current_keys = {str(row["direct_event_key"]) for row in current_rows}
    if (
        accepted_keys & withheld_keys
        or accepted_keys | withheld_keys != current_keys
        or len(accepted_keys) + len(withheld_keys) != len(current_keys)
    ):
        issues.append("settlement_scope_partition_mismatch")
    overlap = int(db.execute(
        """SELECT COUNT(*) FROM direct_cancellation_settlement_members s
           JOIN direct_lodging_authority_events l
             ON l.run_id=s.run_id AND l.payment_id=s.payment_id
           WHERE s.run_id=?""",
        (run_id,),
    ).fetchone()[0])
    if overlap:
        issues.append("settlement_lodging_overlap")

    if require_terminal:
        terminal_rows = [
            tuple(row) for row in db.execute(
                """SELECT p.external_key,r.outcome,r.review_status,r.rule_id
                   FROM direct_cancellation_settlement_members m
                   JOIN payment_transactions p ON p.id=m.payment_id
                   LEFT JOIN allocation_review_cases r ON r.payment_id=m.payment_id
                   WHERE m.run_id=? ORDER BY p.external_key""",
                (run_id,),
            ).fetchall()
        ]
        expected_terminal = sorted(
            (
                member["external_key"], "cancellation_settlement",
                "confirmed", AUTHORITY_CONTRACT,
            )
            for authority in expected_authorities for member in authority["members"]
        )
        if terminal_rows != expected_terminal:
            issues.append("settlement_terminal_review_mismatch")
        allocation_overlap = int(db.execute(
            """SELECT COUNT(*) FROM direct_cancellation_settlement_members m
               JOIN current_cost_allocations a ON a.payment_id=m.payment_id
               WHERE m.run_id=?""",
            (run_id,),
        ).fetchone()[0])
        if allocation_overlap:
            issues.append("settlement_cost_allocation_present")
    return {
        "passed": not issues,
        "issues": issues,
        "scope_payment_count": len(current_rows),
        "authority_count": len(expected_authorities),
        "set_authority_count": sum(
            row["authority_kind"] == "kbo_exact_set"
            for row in expected_authorities
        ),
        "promoted_payment_count": len(expected_members),
        "withheld_payment_count": len(expected_withheld_rows),
        "decision_count": len(expected_decisions),
    }


def _query_lists(db: object, sql: str, run_id: str) -> list[list[object]]:
    return [list(row) for row in db.execute(sql, (run_id,)).fetchall()]


def _manifest_state(db: object, run_id: str) -> dict[str, object]:
    return {
        "inputs": _query_lists(db, """SELECT source_kind,relative_path,raw_sha256,
            lf_sha256,byte_count,key_set_sha256,record_count,parser_version
            FROM direct_projection_inputs WHERE run_id=?
            ORDER BY source_kind,relative_path""", run_id),
        "authorities": _query_lists(db, """SELECT authority_id,authority_kind,
            relation_key_sha256,member_set_sha256,source_set_sha256,
            authority_sha256,member_count,purchase_count,reversal_count,net_krw,
            account,cost_type,allocation_target,individual_pair_asserted,
            payload_json FROM direct_cancellation_settlement_authorities
            WHERE run_id=? ORDER BY authority_id""", run_id),
        "members": _query_lists(db, """SELECT m.authority_id,m.direct_event_key,
            m.current_evidence_id,p.external_key,m.source_key,m.source_sha256,
            m.transaction_type,m.member_role,m.amount_krw,m.occurred_on
            FROM direct_cancellation_settlement_members m
            JOIN payment_transactions p ON p.id=m.payment_id
            WHERE m.run_id=? ORDER BY m.authority_id,m.direct_event_key""", run_id),
        "derivations": _query_lists(db, """SELECT x.derivation_id,x.authority_id,
            p.external_key,x.direct_event_key,x.dimension,x.value,x.rule_id,
            x.current_evidence_id,x.derivation_status,x.conflict_count
            FROM direct_cancellation_settlement_derivations x
            JOIN payment_transactions p ON p.id=x.payment_id
            WHERE x.run_id=? ORDER BY x.derivation_id""", run_id),
        "decisions": _query_lists(db, """SELECT p.external_key,d.dimension,d.value,
            d.confidence,d.confidence_label,d.decision_status,d.rule_id,d.rationale,
            b.derivation_id
            FROM direct_cancellation_settlement_decision_bindings b
            JOIN classification_decisions d ON d.id=b.decision_id
            JOIN payment_transactions p ON p.id=d.target_id
            WHERE b.run_id=? ORDER BY p.external_key,d.dimension""", run_id),
        "terminal_reviews": _query_lists(db, """SELECT p.external_key,r.outcome,
            r.reason_code,r.rationale,r.review_status,r.rule_id
            FROM direct_cancellation_settlement_members m
            JOIN payment_transactions p ON p.id=m.payment_id
            JOIN allocation_review_cases r ON r.payment_id=m.payment_id
            WHERE m.run_id=? ORDER BY p.external_key""", run_id),
        "withheld": _query_lists(db, """SELECT direct_event_key,
            current_evidence_id,reason_code,detail_sha256
            FROM direct_cancellation_settlement_withheld WHERE run_id=?
            ORDER BY direct_event_key""", run_id),
    }


def finalize_cancellation_settlement_manifest(
    db: object, run_id: str,
) -> dict[str, object]:
    if int(db.execute(
        """SELECT COUNT(*) FROM direct_cancellation_settlement_manifests
           WHERE run_id=?""", (run_id,),
    ).fetchone()[0]):
        raise ValueError("settlement_manifest_already_exists")
    validation = validate_cancellation_settlement_authorities(
        db, run_id, require_terminal=True,
    )
    if not validation["passed"]:
        raise ValueError(
            "settlement_authority_validation_failed:"
            + ",".join(str(issue) for issue in validation["issues"])
        )
    state = _manifest_state(db, run_id)
    state_sha256 = _sha(state)
    run_row = db.execute(
        "SELECT input_manifest_sha256 FROM direct_projection_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if run_row is None:
        raise ValueError("settlement_manifest_run_missing")
    payload = {
        "artifact_type": MANIFEST_CONTRACT,
        "run_id": run_id,
        "input_manifest_sha256": str(run_row[0]),
        "state_sha256": state_sha256,
        "census": {key: len(rows) for key, rows in state.items()},
        "set_hashes": {key + "_sha256": _sha(rows)
                       for key, rows in state.items()},
        "active_dimensions": list(ACTIVE_DIMENSIONS),
        "terminal_axes": dict(TERMINAL_AXES),
        "current_scope_partition_complete": True,
        "manual_or_historical_evidence_used": False,
        "generic_amount_tolerance_used": False,
        "amount_tolerance_krw": 0,
        "individual_pairing_claim_for_set_authority": False,
    }
    manifest_sha256 = _sha(payload)
    run_sha256 = _sha({
        "state_sha256": state_sha256,
        "manifest_sha256": manifest_sha256,
    })
    db.execute(
        """INSERT INTO direct_cancellation_settlement_manifests(
             run_id,state_sha256,manifest_sha256,run_sha256,payload_json)
           VALUES (?,?,?,?,?)""",
        (
            run_id, state_sha256, manifest_sha256, run_sha256,
            _canonical(payload).decode("utf-8"),
        ),
    )
    return {
        **payload, "manifest_sha256": manifest_sha256,
        "run_sha256": run_sha256,
    }


def validate_cancellation_settlement_manifest(
    db: object, run_id: str,
) -> dict[str, object]:
    rows = db.execute(
        """SELECT state_sha256,manifest_sha256,run_sha256,payload_json
           FROM direct_cancellation_settlement_manifests WHERE run_id=?""",
        (run_id,),
    ).fetchall()
    if len(rows) != 1:
        return {
            "passed": False,
            "issues": ["settlement_manifest_cardinality_invalid"],
        }
    state_sha256, manifest_sha256, run_sha256, payload_json = rows[0]
    issues: list[str] = []
    try:
        payload = json.loads(str(payload_json))
    except (TypeError, json.JSONDecodeError):
        return {"passed": False, "issues": ["settlement_manifest_payload_invalid"]}
    state = _manifest_state(db, run_id)
    expected_state = _sha(state)
    run_row = db.execute(
        "SELECT input_manifest_sha256 FROM direct_projection_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if (
        run_row is None
        or payload.get("run_id") != run_id
        or payload.get("input_manifest_sha256") != str(run_row[0])
    ):
        issues.append("settlement_manifest_run_binding_mismatch")
    if state_sha256 != expected_state or payload.get("state_sha256") != expected_state:
        issues.append("settlement_manifest_state_hash_mismatch")
    if manifest_sha256 != _sha(payload):
        issues.append("settlement_manifest_hash_mismatch")
    if run_sha256 != _sha({
        "state_sha256": state_sha256, "manifest_sha256": manifest_sha256,
    }):
        issues.append("settlement_manifest_run_hash_mismatch")
    if payload.get("census") != {
        key: len(value) for key, value in state.items()
    }:
        issues.append("settlement_manifest_census_mismatch")
    if payload.get("set_hashes") != {
        key + "_sha256": _sha(value) for key, value in state.items()
    }:
        issues.append("settlement_manifest_set_hash_mismatch")
    if (
        payload.get("artifact_type") != MANIFEST_CONTRACT
        or payload.get("active_dimensions") != list(ACTIVE_DIMENSIONS)
        or payload.get("terminal_axes") != TERMINAL_AXES
        or payload.get("current_scope_partition_complete") is not True
        or payload.get("manual_or_historical_evidence_used") is not False
        or payload.get("generic_amount_tolerance_used") is not False
        or payload.get("amount_tolerance_krw") != 0
        or payload.get("individual_pairing_claim_for_set_authority") is not False
    ):
        issues.append("settlement_manifest_policy_mismatch")
    authority = validate_cancellation_settlement_authorities(
        db, run_id, require_terminal=True,
    )
    if not authority["passed"]:
        issues.extend(
            "settlement_manifest_authority:" + str(issue)
            for issue in authority["issues"]
        )
    return {
        "passed": not issues,
        "issues": issues,
        "state_sha256": expected_state,
        "manifest_sha256": manifest_sha256,
        "run_sha256": run_sha256,
    }
