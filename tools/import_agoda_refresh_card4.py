"""Validate and import the trusted Agoda page-3 refresh/card artifact pair.

The two committed artifacts form one evidence bundle: the card-detail artifact
pins the byte digest of the 591-row refresh census, while the baseline database
proves that its 36 records are exactly the census delta.  This adapter refuses
partial or loosely matched bundles before delegating writes to the canonical
Agoda portal importer.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ledger.domain.agoda_booking_evidence import import_agoda_portal_details


BOOKING_ID_RE = re.compile(r"^[0-9]{8,32}$")
CARD4_RE = re.compile(r"^[0-9]{4}$")
MONEY_RE = re.compile(r"^([A-Z]{3}) ([0-9][0-9,]*(?:\.[0-9]+)?)$")
KOREAN_DATE_RE = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일(?:\s|$)")
PAYMENT_KINDS = {
    "paid_today": "paid_today",
    "scheduled": "future_due",
    "pay_at_property": "property_due",
    "guarantee_only": None,
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("artifact_not_object")
    return value


def _unique_records(value: object, label: str) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    if not isinstance(value, list):
        raise ValueError(f"{label}_records_not_list")
    records: list[Mapping[str, Any]] = []
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{label}_record_not_object")
        source_id = str(item.get("source_id") or "")
        if BOOKING_ID_RE.fullmatch(source_id) is None:
            raise ValueError(f"{label}_source_id_invalid")
        if source_id in indexed:
            raise ValueError(f"{label}_source_id_duplicate")
        records.append(item)
        indexed[source_id] = item
    return records, indexed


def _baseline_ids(path: Path) -> set[str]:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        if str(db.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
            raise ValueError("baseline_integrity_failure")
        if list(db.execute("PRAGMA foreign_key_check")):
            raise ValueError("baseline_foreign_key_failure")
        return {
            str(row[0])
            for row in db.execute(
                "SELECT booking_number FROM bookings WHERE provider='agoda' AND product_type='lodging'"
            )
        }
    finally:
        db.close()


def _date(value: object) -> str:
    match = KOREAN_DATE_RE.match(str(value or ""))
    if match is None:
        raise ValueError("refresh_date_invalid")
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _dates(value: object) -> tuple[str, str]:
    if not isinstance(value, list) or len(value) != 5:
        raise ValueError("refresh_dates_shape_invalid")
    if value[1] != "체크인" or value[3] != "체크아웃":
        raise ValueError("refresh_dates_labels_invalid")
    start, end = _date(value[2]), _date(value[4])
    range_dates = re.findall(r"\d{4}년 \d{1,2}월 \d{1,2}일", str(value[0]))
    if len(range_dates) != 2 or (_date(range_dates[0]), _date(range_dates[1])) != (start, end):
        raise ValueError("refresh_dates_range_mismatch")
    if start >= end:
        raise ValueError("refresh_dates_order_invalid")
    return start, end


def _money(value: object) -> tuple[str, str, int, int]:
    match = MONEY_RE.fullmatch(str(value or ""))
    if match is None:
        raise ValueError("refresh_money_invalid")
    currency, decimal_text = match.groups()
    compact = decimal_text.replace(",", "")
    scale = len(compact.rsplit(".", 1)[1]) if "." in compact else 0
    amount = Decimal(compact)
    if amount <= 0:
        raise ValueError("refresh_money_nonpositive")
    minor_units = int(amount * (Decimal(10) ** scale))
    return currency, decimal_text, minor_units, scale


def _components(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    lines = record.get("payment_lines")
    if not isinstance(lines, list) or len(lines) != 4:
        raise ValueError("refresh_payment_lines_shape_invalid")
    parsed = [_money(value) for value in lines]
    if len({item[0] for item in parsed}) != 1:
        raise ValueError("refresh_payment_currency_mismatch")
    decimals = [Decimal(item[1].replace(",", "")) for item in parsed]
    if decimals[0] + decimals[1] != decimals[2] or decimals[2] != decimals[3]:
        raise ValueError("refresh_payment_equation_mismatch")
    state = str(record.get("payment_state") or "")
    if state not in PAYMENT_KINDS:
        raise ValueError("refresh_payment_state_invalid")
    expected_amount = str(lines[2])
    observed_payment = str(record.get("payment_amount") or "")
    if (state == "paid_today" and observed_payment != expected_amount) or (
        state != "paid_today" and observed_payment
    ):
        raise ValueError("refresh_payment_amount_mismatch")
    total_amount = str(record.get("total_amount") or "")
    if total_amount and total_amount != str(lines[3]):
        raise ValueError("refresh_total_amount_mismatch")
    total_line = record.get("total_line")
    if total_line is not None and total_line != ["총 금액", lines[3]]:
        raise ValueError("refresh_total_line_mismatch")

    def component(kind: str, parsed_money: tuple[str, str, int, int]) -> dict[str, Any]:
        currency, decimal_text, minor_units, scale = parsed_money
        return {
            "kind": kind,
            "currency": currency,
            "decimal_text": decimal_text,
            "minor_units": minor_units,
            "scale": scale,
        }

    result = [component("base", parsed[0]), component("taxes_and_fees", parsed[1])]
    payment_kind = PAYMENT_KINDS[state]
    if payment_kind is not None:
        result.append(component(payment_kind, parsed[2]))
    result.append(component("gross_total", parsed[3]))
    return result


def _validate_detail_id(value: object) -> str:
    text = str(value or "")
    try:
        decoded = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ValueError("refresh_detail_id_invalid") from exc
    if len(decoded) != 16:
        raise ValueError("refresh_detail_id_invalid")
    return text


def validate_bundle(
    refresh_path: Path,
    card_path: Path,
    baseline_db_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    refresh = _object(refresh_path)
    card = _object(card_path)
    refresh_records, refresh_by_id = _unique_records(refresh.get("records"), "refresh")
    card_records, card_by_id = _unique_records(card.get("records"), "card")

    refresh_digest = _file_sha256(refresh_path)
    card_digest = _file_sha256(card_path)
    if card.get("schema") != "agoda-paseo-staging-refresh-card4-v1":
        raise ValueError("card_schema_invalid")
    if str(card.get("source_staging_sha256") or "").lower() != refresh_digest:
        raise ValueError("card_source_staging_digest_mismatch")
    if card.get("customer_center_clicks") != 0:
        raise ValueError("card_customer_center_clicks_nonzero")
    if refresh.get("cancelled_excluded") is not True:
        raise ValueError("refresh_cancelled_scope_invalid")

    integrity = refresh.get("integrity")
    manifest = refresh.get("refresh_manifest")
    summary = card.get("summary")
    if not all(isinstance(item, Mapping) for item in (integrity, manifest, summary)):
        raise ValueError("artifact_summary_shape_invalid")
    if integrity.get("record_count") != len(refresh_records) or integrity.get("unique_source_ids") != len(refresh_by_id):
        raise ValueError("refresh_integrity_count_mismatch")
    if integrity.get("duplicate_source_ids") != 0 or integrity.get("records_sha256") != _json_sha256(refresh_records):
        raise ValueError("refresh_integrity_digest_mismatch")

    baseline_ids = _baseline_ids(baseline_db_path)
    refresh_ids = set(refresh_by_id)
    card_ids = set(card_by_id)
    if not baseline_ids <= refresh_ids or refresh_ids - baseline_ids != card_ids:
        raise ValueError("refresh_baseline_delta_mismatch")
    if manifest.get("record_count") != len(card_ids) or manifest.get("unique_source_ids") != len(card_ids):
        raise ValueError("refresh_manifest_count_mismatch")
    if manifest.get("source_ids_sha256") != _json_sha256(sorted(card_ids)):
        raise ValueError("refresh_manifest_id_digest_mismatch")
    if manifest.get("customer_center_click_count") != 0 or manifest.get("customer_center_route_count") != 0:
        raise ValueError("refresh_manifest_customer_center_nonzero")
    if summary.get("record_count") != len(card_ids) or summary.get("detail_captured") != len(card_ids):
        raise ValueError("card_summary_count_mismatch")
    if summary.get("card4_present") != len(card_ids) or summary.get("distinct_card4") != ["8835"]:
        raise ValueError("card_summary_card4_mismatch")

    normalized: list[dict[str, Any]] = []
    states: Counter[str] = Counter()
    for source_id in sorted(card_ids):
        source = refresh_by_id[source_id]
        detail = card_by_id[source_id]
        for key in ("source_id", "status", "detail_id", "hotel", "dates", "payment_lines", "total_line"):
            if source.get(key) != detail.get(key):
                raise ValueError(f"refresh_card_field_mismatch:{source_id}:{key}")
        if source.get("id_exact_match") is not True or source.get("status") != "Upcoming":
            raise ValueError("refresh_identity_or_status_invalid")
        if detail.get("detail_capture_route") is not True or detail.get("support_clicks") != 0:
            raise ValueError("card_route_or_support_safety_invalid")
        _validate_detail_id(detail.get("detail_id"))
        card4 = str(detail.get("card4") or "")
        if CARD4_RE.fullmatch(card4) is None or not str(detail.get("card_line") or "").endswith(card4):
            raise ValueError("card_observation_invalid")
        start, end = _dates(detail.get("dates"))
        components = _components(detail)
        state = str(detail.get("payment_state"))
        states[state] += 1
        normalized.append({
            "booking_id": source_id,
            "status": "Upcoming",
            "detail_service_start_on": start,
            "detail_service_end_on": end,
            "payment_status": state,
            "card4": card4,
            "card_role": "payment_or_guarantee_unresolved",
            "card_observation_status": "observed_card4",
            "price_components": components,
            "observed_at_utc": manifest.get("captured_at_utc"),
        })
    if dict(sorted(states.items())) != dict(sorted(summary.get("payment_states", {}).items())):
        raise ValueError("card_summary_payment_states_mismatch")

    metadata = {
        "refresh_sha256": refresh_digest,
        "card_sha256": card_digest,
        "baseline_count": len(baseline_ids),
        "refresh_count": len(refresh_ids),
        "delta_count": len(card_ids),
        "payment_states": dict(sorted(states.items())),
    }
    return metadata, normalized


def import_bundle(
    db_path: Path,
    refresh_path: Path,
    card_path: Path,
    baseline_db_path: Path,
    run_id: str,
) -> dict[str, Any]:
    metadata, records = validate_bundle(refresh_path, card_path, baseline_db_path)
    before_ids = _baseline_ids(db_path)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        stats = import_agoda_portal_details(
            db,
            records,
            run_id=run_id,
            staging_sha256=metadata["refresh_sha256"],
            observed_at_utc=str(_object(card_path).get("captured_at") or ""),
        )
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(db.execute("PRAGMA foreign_key_check"))
        after_ids = {
            str(row[0])
            for row in db.execute(
                "SELECT booking_number FROM bookings WHERE provider='agoda' AND product_type='lodging'"
            )
        }
        expected_ids = {record["booking_id"] for record in records}
        if integrity != "ok" or foreign_keys or not expected_ids <= after_ids:
            raise RuntimeError("refresh_import_integrity_failure")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {
        **metadata,
        "run_id": run_id,
        "bookings_before": len(before_ids),
        "bookings_after": len(after_ids),
        "bookings_added": len(after_ids - before_ids),
        "stats": stats,
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--baseline-db", type=Path, required=True)
    parser.add_argument("--refresh", type=Path, required=True)
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    report = import_bundle(
        args.db, args.refresh, args.card, args.baseline_db, args.run_id
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
