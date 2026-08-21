"""Promote only uniquely matched, independently verified OTA reservations.

This authority deliberately separates the service period in the reservation
fact from the card payment date.  The card is identified by the exact
card-last-four, currency, and foreign amount tuple; a singleton match is
required in both directions.  Amount-only, date-only, manual-ledger, and
many-to-many matches remain in the run-scoped queue.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from typing import Iterable

from ledger.domain.direct_verified_ota_lodging import load_trip_schedule


SOURCE_KIND = "ota_reservation_fact"
EVIDENCE_KIND = "verified_booking"
RULE_ID = "ota-reservation-current-card-unique-service-period-v1"
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")
FORBIDDEN_SOURCE_TOKENS = (
    "manual",
    "historical",
    "replay",
    "proposal",
    "tolerance",
    "ledger",
)
PERIOD_PATTERN = re.compile(r"^(\d{4})(?:_(\d{4}))?$")
CARD4_PATTERN = re.compile(r"^\d{4}$")
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

# These are place-name aliases, not transaction evidence.  They are used only
# to select a trip target after the external reservation's service date is
# known.  ``Mutsu`` is the city name represented by the Aomori trip tab.
SERVICE_REGION_ALIASES = {
    "MUTSU": "아오모리",
    "AOMORI": "아오모리",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    data = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(data).hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized(value: object) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", _text(value)).upper()
        if char.isalnum()
    )


def _integer(value: object) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str):
        raw = value.strip().replace(",", "")
        if re.fullmatch(r"\d+(?:\.0+)?", raw) is not None:
            return int(raw.split(".", 1)[0])
    return None


def _payload_scalar(payload: dict[str, object], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            return _text(value)
    return ""


def _period(value: object) -> tuple[date, date] | None:
    if not isinstance(value, str):
        return None
    match = PERIOD_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    try:
        start = date(2026, int(match.group(1)[:2]), int(match.group(1)[2:]))
        end = date(2026, int(match.group(2)[:2]), int(match.group(2)[2:])) \
            if match.group(2) else start
    except ValueError:
        return None
    return (start, end) if start <= end else None


def _provider_tokens(fact: dict[str, object]) -> tuple[str, ...]:
    source = _normalized(fact.get("verification_source"))
    if "AGODA" in source:
        return ("AGODA",)
    if "BOOKING" in source:
        return ("BOOKING", "BKG")
    if "TRIP" in source:
        return ("TRIP", "KCP")
    return ("AGODA", "BOOKING", "BKG", "TRIP", "KCP")


def _source_allowed(fact: dict[str, object]) -> bool:
    source = _normalized(fact.get("verification_source"))
    return bool(source) and not any(token.upper() in source for token in FORBIDDEN_SOURCE_TOKENS)


def _fact_validation(fact: object) -> tuple[dict[str, object] | None, str | None]:
    if not isinstance(fact, dict):
        return None, "fact_not_object"
    category = _text(fact.get("category"))
    if category not in {"숙박", "항공"}:
        return None, "unsupported_category"
    if not _source_allowed(fact):
        return None, "independent_source_missing_or_forbidden"
    service_period = _period(fact.get("period"))
    if service_period is None:
        return None, "service_period_invalid"
    card4 = _text(fact.get("card4"))
    currency = _text(fact.get("currency"))
    foreign_amount = _integer(fact.get("foreign_amount"))
    if CARD4_PATTERN.fullmatch(card4) is None:
        return None, "exact_card_identity_missing"
    if CURRENCY_PATTERN.fullmatch(currency) is None or foreign_amount is None \
            or foreign_amount <= 0:
        return None, "exact_foreign_amount_missing"
    return {
        "category": category,
        "period": _text(fact.get("period")),
        "service_start": service_period[0],
        "service_end": service_period[1],
        "card4": card4,
        "currency": currency,
        "foreign_amount": foreign_amount,
        "provider_tokens": _provider_tokens(fact),
    }, None


def _load_facts(db: sqlite3.Connection) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records
           WHERE source_kind=? ORDER BY source_key""",
        (SOURCE_KIND,),
    ).fetchall()
    if not rows:
        raise ValueError("ota_reservation_fact_source_missing")
    result: list[dict[str, object]] = []
    for source_key, source_sha256, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            payload = None
        result.append({
            "source_key": str(source_key),
            "source_sha256": str(source_sha256),
            "fact": payload,
            "fact_sha256": _sha(payload),
            "source_digest_valid": str(source_sha256) == _sha(payload),
        })
    return result


def _load_current_cards(db: sqlite3.Connection, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT e.evidence_id,e.direct_event_key,e.source_key,e.source_sha256,
                  p.id,p.external_key,p.source_system,p.transaction_type,
                  p.amount_krw,p.merchant,s.payload_json
           FROM direct_promotion_evidence e
           JOIN direct_normalized_payments d
             ON e.direct_event_key=d.card_event_id || '#' || d.event_role
           JOIN direct_payment_projection_links l
             ON l.run_id=e.run_id AND l.direct_payment_id=d.id
           JOIN payment_transactions p ON p.id=l.payment_id
           JOIN direct_source_records s
             ON s.id=d.source_record_id
            AND s.source_kind=e.source_kind
            AND s.source_key=e.source_key
            AND s.source_sha256=e.source_sha256
           WHERE e.run_id=? AND e.evidence_kind='current_card'
             AND e.authority_status='current_raw'
             AND e.source_kind='card_raw'
             AND e.direct_event_key=d.card_event_id || '#' || d.event_role
           ORDER BY e.direct_event_key,p.id""",
        (run_id,),
    ).fetchall()
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row[1])
        if key in seen:
            raise ValueError(f"current_card_evidence_not_unique:{key}")
        seen.add(key)
        try:
            payload = json.loads(str(row[10]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"current_card_payload_invalid:{key}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"current_card_payload_invalid:{key}")
        result.append({
            "current_evidence_id": str(row[0]),
            "direct_event_key": key,
            "source_key": str(row[2]),
            "source_sha256": str(row[3]),
            "payment_id": int(row[4]),
            "external_key": str(row[5]),
            "source_system": str(row[6]),
            "transaction_type": str(row[7]),
            "amount_krw": int(row[8]),
            "merchant": _text(row[9]),
            "card4": _payload_scalar(payload, "card4", "card_last4", "last4"),
            "currency": _payload_scalar(payload, "currency", "foreign_currency"),
            "foreign_amount": _integer(
                _payload_scalar(payload, "foreign_amount", "foreign", "local_amount")
            ),
        })
    return result


def _target_for_fact(
    fact: dict[str, object], schedule: dict[str, dict[str, object]],
) -> tuple[str | None, str | None]:
    start = fact["service_start"]
    end = fact["service_end"]
    active = [
        trip for trip in schedule.values()
        if date.fromisoformat(str(trip["starts_on"])) <= start
        <= date.fromisoformat(str(trip["ends_on"]))
    ]
    if not active:
        return None, "service_target_missing"
    searchable = " ".join(
        _text(fact.get(name))
        for name in ("hotel", "route", "destination", "city", "airport")
    )
    text = _normalized(searchable)
    region_hints = {
        region for alias, region in SERVICE_REGION_ALIASES.items()
        if _normalized(alias) in text
    }
    if text:
        region_hints.update(
            str(trip["region"])
            for trip in active
            if _normalized(trip["region"]) in text
        )
    if region_hints:
        active = [
            trip for trip in active if str(trip["region"]) in region_hints
        ]
    active = [
        trip for trip in active
        if end <= date.fromisoformat(str(trip["ends_on"]))
    ]
    if len(active) != 1:
        return None, "service_target_ambiguous"
    return str(active[0]["tab"]), None


def _candidate_cards(
    fact: dict[str, object], cards: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    source_key = str(fact["source_key"])
    expected_system = source_key.split("-", 1)[0]
    result = []
    for card in cards:
        if card["transaction_type"] != "purchase" or int(card["amount_krw"]) <= 0:
            continue
        if card["source_system"] != expected_system:
            continue
        if card["card4"] != fact["card4"] or card["currency"] != fact["currency"]:
            continue
        if card["foreign_amount"] != fact["foreign_amount"]:
            continue
        merchant = _normalized(card["merchant"])
        if not any(_normalized(token) in merchant for token in fact["provider_tokens"]):
            continue
        result.append(card)
    return result


def _existing_decision_count(db: sqlite3.Connection, payment_id: int) -> int:
    return int(db.execute(
        """SELECT COUNT(*) FROM classification_decisions
           WHERE target_type='payment' AND target_id=?
             AND dimension IN ('account','cost_type','allocation_target')""",
        (payment_id,),
    ).fetchone()[0])


def _evaluate(
    db: sqlite3.Connection, run_id: str, *, check_existing: bool = True,
) -> dict[str, object]:
    schedule = load_trip_schedule(db)
    cards = _load_current_cards(db, run_id)
    facts = _load_facts(db)
    proposals: list[dict[str, object]] = []
    queue: list[dict[str, object]] = []

    def enqueue(item: dict[str, object], reason: str, detail: object, count: int = 0) -> None:
        queue.append({
            "source_key": item["source_key"],
            "fact_sha256": item["fact_sha256"],
            "reason_code": reason,
            "candidate_count": count,
            "detail": detail,
            "detail_sha256": _sha(detail),
        })

    for item in facts:
        if not item["source_digest_valid"]:
            enqueue(
                item,
                "source_digest_mismatch",
                {"source_key": item["source_key"], "fact": item["fact"]},
            )
            continue
        fact, reason = _fact_validation(item["fact"])
        if reason is not None or fact is None:
            enqueue(item, str(reason), {"fact": item["fact"]})
            continue
        target_input = dict(item["fact"])
        target_input.update(fact)
        target_code, target_reason = _target_for_fact(target_input, schedule)
        candidates = _candidate_cards(fact | {"source_key": item["source_key"]}, cards)
        detail = {
            "source_key": item["source_key"],
            "period": fact["period"],
            "candidate_event_keys": [str(row["direct_event_key"]) for row in candidates],
            "target_code": target_code,
        }
        if target_reason is not None:
            enqueue(item, target_reason, detail, len(candidates))
            continue
        if len(candidates) != 1:
            enqueue(
                item,
                "no_current_exact_match" if not candidates else "non_unique_current_match",
                detail,
                len(candidates),
            )
            continue
        card = candidates[0]
        if check_existing and _existing_decision_count(db, int(card["payment_id"])):
            enqueue(item, "existing_decision_conflict", detail, 1)
            continue
        proposals.append({
            "item": item,
            "fact": fact,
            "target_code": target_code,
            "card": card,
        })

    by_event: dict[str, list[dict[str, object]]] = defaultdict(list)
    for proposal in proposals:
        by_event[str(proposal["card"]["direct_event_key"])].append(proposal)
    promoted: list[dict[str, object]] = []
    for proposal in proposals:
        event_key = str(proposal["card"]["direct_event_key"])
        if len(by_event[event_key]) != 1:
            item = proposal["item"]
            enqueue(
                item,
                "current_event_reused_by_multiple_facts",
                {
                    "candidate_event_key": event_key,
                    "source_keys": sorted(
                        str(other["item"]["source_key"])
                        for other in by_event[event_key]
                    ),
                },
                1,
            )
            continue
        promoted.append(proposal)

    return {
        "facts": facts,
        "promoted": promoted,
        "queue": sorted(queue, key=lambda row: str(row["source_key"])),
    }


def _axis_values(proposal: dict[str, object]) -> dict[str, str]:
    category = str(proposal["fact"]["category"])
    return {
        "account": "숙박비" if category == "숙박" else "항공료",
        "cost_type": "여행원가",
        "allocation_target": str(proposal["target_code"]),
    }


def _axis_rule_id(dimension: str) -> str:
    # The v3 schema requires a distinct derivation contract per axis.
    return f"{RULE_ID}:{dimension}"


def project_ota_reservation_authority(
    db: sqlite3.Connection, run_id: str,
) -> dict[str, object]:
    """Project the closed OTA authority and retain every other fact in queue."""
    if db.execute(
        "SELECT COUNT(*) FROM direct_ota_reservation_queue WHERE run_id=?",
        (run_id,),
    ).fetchone()[0]:
        raise ValueError("ota_reservation_authority_already_projected")
    evaluated = _evaluate(db, run_id)
    db.execute("SAVEPOINT ota_reservation_authority")
    try:
        for item in evaluated["queue"]:
            db.execute(
                """INSERT INTO direct_ota_reservation_queue(
                     run_id,source_key,fact_sha256,reason_code,candidate_count,
                     detail_sha256)
                   VALUES (?,?,?,?,?,?)""",
                (
                    run_id, item["source_key"], item["fact_sha256"],
                    item["reason_code"], item["candidate_count"],
                    item["detail_sha256"],
                ),
            )
        decision_count = 0
        for proposal in evaluated["promoted"]:
            item = proposal["item"]
            fact = item["fact"]
            card = proposal["card"]
            current_evidence_id = str(card["current_evidence_id"])
            independent_evidence_id = f"{EVIDENCE_KIND}:{item['fact_sha256']}"
            db.execute(
                """INSERT INTO direct_promotion_evidence(
                     evidence_id,run_id,evidence_kind,authority_status,
                     direct_event_key,source_kind,source_key,source_sha256,fact_sha256)
                   VALUES (?,?,'verified_booking','verified_external',?,?,?,?,?)""",
                (
                    independent_evidence_id, run_id, card["direct_event_key"],
                    SOURCE_KIND, item["source_key"], item["source_sha256"],
                    item["fact_sha256"],
                ),
            )
            axes = _axis_values(proposal)
            rationale = (
                "외부 OTA 예약 원문의 서비스 기간을 여행 탭으로 사용하고, "
                "결제일이 아닌 카드4·통화·외화금액의 양방향 고유 매칭으로 "
                f"현재 카드 {card['direct_event_key']}를 확정함"
            )
            for dimension in ACTIVE_DIMENSIONS:
                value = axes[dimension]
                derivation_id = "ota-reservation-derivation:" + _sha({
                    "source_key": item["source_key"],
                    "direct_event_key": card["direct_event_key"],
                    "dimension": dimension,
                    "value": value,
                })
                decision_id = int(db.execute(
                    """INSERT INTO classification_decisions(
                         target_type,target_id,dimension,value,confidence,
                         confidence_label,decision_status,rule_id,rationale)
                       VALUES ('payment',?,?,?,?,?,'confirmed',?,?)""",
                    (
                        int(card["payment_id"]), dimension, value, 1.0,
                        "독립원천검증", _axis_rule_id(dimension), rationale,
                    ),
                ).lastrowid)
                db.execute(
                    """INSERT INTO direct_axis_derivations(
                         derivation_id,run_id,payment_id,dimension,value,rule_id,
                         current_evidence_id,independent_evidence_id,
                         derivation_status,conflict_count)
                       VALUES (?,?,?,?,?,?,?,?, 'pass',0)""",
                    (
                        derivation_id, run_id, int(card["payment_id"]), dimension,
                        value, _axis_rule_id(dimension), current_evidence_id,
                        independent_evidence_id,
                    ),
                )
                db.execute(
                    """INSERT INTO direct_decision_promotion_bindings(
                         run_id,decision_id,derivation_id) VALUES (?,?,?)""",
                    (run_id, decision_id, derivation_id),
                )
                decision_count += 1
    except Exception:
        db.execute("ROLLBACK TO ota_reservation_authority")
        db.execute("RELEASE ota_reservation_authority")
        raise
    else:
        db.execute("RELEASE ota_reservation_authority")

    reason_counts = Counter(str(item["reason_code"]) for item in evaluated["queue"])
    return {
        "source_fact_count": len(evaluated["facts"]),
        "promoted_payment_count": len(evaluated["promoted"]),
        "decision_count": decision_count,
        "withheld_fact_count": len(evaluated["queue"]),
        "withheld_reason_counts": dict(sorted(reason_counts.items())),
        "unique_match_count": len(evaluated["promoted"]),
        "non_unique_match_count": sum(
            int(item["reason_code"] == "non_unique_current_match")
            for item in evaluated["queue"]
        ),
        "promoted_sample": [
            {
                "source_key": str(item["item"]["source_key"]),
                "direct_event_key": str(item["card"]["direct_event_key"]),
                "allocation_target": str(item["target_code"]),
            }
            for item in evaluated["promoted"]
        ],
        "non_unique_match_sample": [
            {
                "source_key": str(item["source_key"]),
                "candidate_count": int(item["candidate_count"]),
                "detail_sha256": str(item["detail_sha256"]),
            }
            for item in evaluated["queue"]
            if item["reason_code"] == "non_unique_current_match"
        ][:10],
    }


def validate_ota_reservation_authority(
    db: sqlite3.Connection, run_id: str, *, require_allocations: bool = False,
) -> dict[str, object]:
    """Recompute the authority and compare the stored claims and queue."""
    issues: list[str] = []
    try:
        evaluated = _evaluate(db, run_id, check_existing=False)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"passed": False, "issues": [str(exc)]}

    expected_promoted = sorted(
        (
            str(p["item"]["source_key"]),
            str(p["card"]["direct_event_key"]),
            str(p["item"]["source_sha256"]),
            str(p["item"]["fact_sha256"]),
        )
        for p in evaluated["promoted"]
    )
    actual_promoted = sorted(tuple(row) for row in db.execute(
        """SELECT source_key,direct_event_key,source_sha256,fact_sha256
           FROM direct_promotion_evidence
           WHERE run_id=? AND evidence_kind='verified_booking'
             AND authority_status='verified_external'
             AND source_kind=?""",
        (run_id, SOURCE_KIND),
    ).fetchall())
    if expected_promoted != actual_promoted:
        issues.append("promotion_evidence_set_mismatch")

    expected_queue = sorted(
        (
            str(item["source_key"]), str(item["fact_sha256"]),
            str(item["reason_code"]), int(item["candidate_count"]),
            str(item["detail_sha256"]),
        )
        for item in evaluated["queue"]
    )
    actual_queue = sorted(tuple(row) for row in db.execute(
        """SELECT source_key,fact_sha256,reason_code,candidate_count,detail_sha256
           FROM direct_ota_reservation_queue WHERE run_id=?""",
        (run_id,),
    ).fetchall())
    if expected_queue != actual_queue:
        issues.append("withheld_queue_mismatch")

    expected_decisions = []
    for proposal in evaluated["promoted"]:
        axes = _axis_values(proposal)
        for dimension in ACTIVE_DIMENSIONS:
            expected_decisions.append((
                str(proposal["card"]["external_key"]), dimension, axes[dimension],
                1.0, "독립원천검증", "confirmed", _axis_rule_id(dimension),
                str(proposal["card"]["current_evidence_id"]),
            ))
    actual_decisions = [tuple(row) for row in db.execute(
        """SELECT p.external_key,d.dimension,d.value,d.confidence,
                  d.confidence_label,d.decision_status,d.rule_id,
                  x.current_evidence_id
           FROM direct_axis_derivations x
           JOIN direct_decision_promotion_bindings b
             ON b.run_id=x.run_id AND b.derivation_id=x.derivation_id
           JOIN classification_decisions d ON d.id=b.decision_id
           JOIN payment_transactions p ON p.id=d.target_id
           WHERE x.run_id=? AND x.rule_id LIKE ?
           ORDER BY p.external_key,d.dimension""",
        (run_id, RULE_ID + ":%"),
    ).fetchall()]
    if sorted(expected_decisions) != sorted(actual_decisions):
        issues.append("decision_set_mismatch")

    for proposal in evaluated["promoted"]:
        card = proposal["card"]
        payment_id = int(card["payment_id"])
        if _existing_decision_count(db, payment_id) != len(ACTIVE_DIMENSIONS):
            issues.append(f"decision_axis_count_invalid:{card['direct_event_key']}")
    if require_allocations:
        expected_allocations = sorted(
            (
                str(p["card"]["external_key"]), str(p["target_code"]),
                int(p["card"]["amount_krw"]),
            )
            for p in evaluated["promoted"]
        )
        actual_allocations = sorted(tuple(row) for row in db.execute(
            """SELECT p.external_key,t.code,a.amount_krw
               FROM current_cost_allocations a
               JOIN allocation_plans ap ON ap.id=a.plan_id
               JOIN payment_transactions p ON p.id=a.payment_id
               JOIN allocation_targets t ON t.id=a.target_id
               JOIN direct_payment_projection_links l
                 ON l.run_id=? AND l.payment_id=p.id
               JOIN classification_decisions d
                 ON d.id=ap.source_decision_id AND d.rule_id LIKE ?
               ORDER BY p.external_key""",
            (run_id, RULE_ID + ":%"),
        ).fetchall())
        if expected_allocations != actual_allocations:
            issues.append("allocation_set_mismatch")

    return {
        "passed": not issues,
        "issues": issues,
        "source_fact_count": len(evaluated["facts"]),
        "promoted_payment_count": len(evaluated["promoted"]),
        "decision_count": len(evaluated["promoted"]) * len(ACTIVE_DIMENSIONS),
        "withheld_fact_count": len(evaluated["queue"]),
    }
