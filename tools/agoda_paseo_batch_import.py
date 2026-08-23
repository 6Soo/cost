"""Import one read-only Paseo Agoda worker result into the staging database.

Browser workers return JSON only.  This module is the single-writer boundary:
it validates exact booking identity and browser safety observations before
delegating canonical evidence creation to ``import_agoda_portal_details``.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from ledger.domain.agoda_booking_evidence import import_agoda_portal_details


BOOKING_ID_RE = re.compile(r"^[0-9]{8,32}$")
CARD4_RE = re.compile(r"^[0-9]{4}$")
REFERENCE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CARD_STATUSES = {
    "observed_card4",
    "confirmed_non_card",
    "confirmed_absent",
    "unresolved",
}
COMPONENT_KINDS = {
    "base",
    "charge",
    "chargeback",
    "coupon",
    "fee",
    "gross_total",
    "paid_today",
    "future_due",
    "remaining_due",
    "property_due",
    "discount",
    "points",
    "agoda_cash",
    "refund",
    "tax",
    "taxes_and_fees",
}


def _text(value: object) -> str | None:
    value = " ".join(str(value or "").split()).strip()
    return value or None


def _component_kind(item: Mapping[str, Any]) -> str | None:
    explicit = _text(item.get("kind") or item.get("component") or item.get("name"))
    if explicit in COMPONENT_KINDS:
        return explicit
    explicit_aliases = {
        "room": "base",
        "room_charge": "base",
        "surcharge": "fee",
        "additional_charge": "fee",
        "extra_charge": "fee",
    }
    if explicit in explicit_aliases:
        return explicit_aliases[explicit]
    label = (_text(item.get("label")) or "").casefold()
    aliases = (
        (("객실", "room", "base"), "base"),
        (("세금 및 봉사료", "taxes and fees", "taxes_and_fees"), "taxes_and_fees"),
        (("오늘 결제", "paid today", "paid_today"), "paid_today"),
        (("향후 결제", "추후 결제", "future due"), "future_due"),
        (("남은 금액", "remaining due"), "remaining_due"),
        (("체크인 시", "숙소에서 결제", "property due"), "property_due"),
        (("총 금액", "gross total", "total"), "gross_total"),
        (("agoda cash", "agodacash", "아고다캐시"), "agoda_cash"),
        (("쿠폰", "coupon"), "coupon"),
        (("할인", "discount"), "discount"),
        (("포인트", "points"), "points"),
        (("환불", "refund"), "refund"),
        (("세금", "tax"), "tax"),
        (("수수료", "fee"), "fee"),
    )
    for needles, kind in aliases:
        if any(needle in label for needle in needles):
            return kind
    return None


def _normalize_components(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        kind = _component_kind(raw)
        currency = (_text(raw.get("currency")) or "").upper()
        decimal_text = _text(raw.get("decimal_text") or raw.get("amount"))
        if kind is None or not re.fullmatch(r"[A-Z]{3}", currency) or decimal_text is None:
            continue
        compact = decimal_text.replace(",", "")
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", compact) is None:
            raise ValueError("worker_component_decimal_invalid")
        scale = len(compact.rsplit(".", 1)[1]) if "." in compact else 0
        try:
            minor_units = int(Decimal(compact) * (Decimal(10) ** scale))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("worker_component_decimal_invalid") from exc
        component: dict[str, Any] = {
            "kind": kind,
            "currency": currency,
            "decimal_text": decimal_text,
            "minor_units": minor_units,
            "scale": scale,
        }
        label = _text(raw.get("label"))
        if label is not None:
            component["label"] = label
        normalized.append(component)
    return normalized


def normalize_worker_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate one worker record and adapt it to the domain importer.

    Failed detail observations remain in the worker artifact but are not
    promoted into canonical portal evidence.
    """
    booking_id = _text(record.get("booking_id"))
    if booking_id is None or BOOKING_ID_RE.fullmatch(booking_id) is None:
        raise ValueError("worker_booking_id_invalid")
    if record.get("detail_success") is not True:
        return None
    observed = _text(record.get("observed_booking_id")) or booking_id
    if observed != booking_id:
        raise ValueError("worker_observed_booking_id_mismatch")
    if record.get("panel_visible") is not False:
        raise ValueError("worker_customer_center_panel_not_false")
    if record.get("selector_count") != 1:
        raise ValueError("worker_selector_count_not_one")

    card_status = _text(record.get("card_observation_status")) or "unresolved"
    if card_status not in CARD_STATUSES:
        raise ValueError("worker_card_observation_status_invalid")
    card4 = _text(record.get("card4") or record.get("card_last4"))
    if card4 is not None and CARD4_RE.fullmatch(card4) is None:
        raise ValueError("worker_card4_invalid")
    if card_status == "observed_card4" and card4 is None:
        raise ValueError("worker_observed_card4_missing")
    if card_status in {"confirmed_non_card", "confirmed_absent"} and card4 is not None:
        raise ValueError("worker_non_card_has_card4")

    reference_code = _text(record.get("reference_code"))
    if reference_code is not None and REFERENCE_CODE_RE.fullmatch(reference_code) is None:
        # Agoda can display several room-level references in one field.  Keep
        # that observation in the immutable worker JSON, but do not promote a
        # comma-separated set as one canonical booking identifier.
        references = [_text(item) for item in reference_code.split(",")]
        if (
            len(references) < 2
            or any(item is None or REFERENCE_CODE_RE.fullmatch(item) is None for item in references)
        ):
            raise ValueError("worker_reference_code_invalid")
        reference_code = None

    components = _normalize_components(record.get("price_components"))
    if not components:
        currency = _text(record.get("total_currency"))
        amount = record.get("total_minor_units")
        if amount is None:
            amount = record.get("total_minor_units_or_text")
        if currency and isinstance(amount, int):
            components = [{
                "kind": "gross_total",
                "currency": currency.upper(),
                "decimal_text": str(amount),
                "minor_units": amount,
                "scale": 0,
            }]

    normalized: dict[str, Any] = {
        "booking_id": booking_id,
        "status": _text(record.get("status") or record.get("reservation_status")) or "unknown",
        "reservation_status": _text(record.get("reservation_status")),
        "detail_service_start_on": _text(record.get("check_in") or record.get("service_start_on")),
        "detail_service_end_on": _text(record.get("check_out") or record.get("service_end_on")),
        "payment_status": _text(record.get("payment_status") or record.get("payment_state")),
        "collection_model": _text(record.get("collection_model")),
        "refund_status": _text(record.get("refund_status")) or "none_displayed",
        "card_type": _text(record.get("card_type")),
        "card4": card4,
        "card_role": _text(record.get("card_role")),
        "card_observation_status": card_status,
        "reference_code": reference_code,
        "price_components": components,
        "observed_at_utc": _text(record.get("ended_at") or record.get("observed_at")),
    }
    return {key: value for key, value in normalized.items() if value not in (None, "", [])}


def load_worker_batch(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    batch = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(batch, dict):
        raise ValueError("worker_batch_not_object")
    if batch.get("writes") not in (None, 0, "0", "none"):
        raise ValueError("worker_reported_write_effect")
    targets = batch.get("targets")
    records = batch.get("records")
    if not isinstance(targets, list) or not isinstance(records, list):
        raise ValueError("worker_batch_shape_invalid")
    target_ids = [_text(value) for value in targets]
    if any(value is None or BOOKING_ID_RE.fullmatch(value) is None for value in target_ids):
        raise ValueError("worker_target_id_invalid")
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("worker_target_duplicate")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("worker_record_not_object")
        booking_id = _text(raw.get("booking_id"))
        if booking_id not in target_ids:
            raise ValueError("worker_record_outside_targets")
        if booking_id in seen:
            raise ValueError("worker_record_duplicate")
        seen.add(booking_id)
        item = normalize_worker_record(raw)
        if item is not None:
            normalized.append(item)
    return batch, normalized


def import_worker_batch(db_path: Path, input_path: Path, run_id: str) -> dict[str, Any]:
    batch, records = load_worker_batch(input_path)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        stats = import_agoda_portal_details(db, records, run_id=run_id)
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(db.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("worker_import_integrity_failure")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {
        "lane": batch.get("lane"),
        "targets": len(batch.get("targets", [])),
        "worker_records": len(batch.get("records", [])),
        "importable_records": len(records),
        "failed_records": len(batch.get("records", [])) - len(records),
        "stats": stats,
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    report = import_worker_batch(args.db, args.input, args.run_id)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
