"""High-trust, redacted PG mail matching for current card events.

PG mail is an external receipt source, not a replacement for the current card
row.  This module only joins a unique receipt to a card event and exposes a
typed classification hint.  A payment date never becomes a service date by
itself; a service period must be explicit in the PG record or linked service
mail.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, timedelta
from typing import Iterable, Mapping


CONTRACT = "pg-payment-evidence-v1"


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return re.sub(r"[^0-9A-Z가-힣]", "", text)


def _approval(value: object) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def load_pg_mail_records(db: sqlite3.Connection) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records
           WHERE source_kind IN ('pg_mail','pg_mail_supplement')
           ORDER BY source_key"""
    ).fetchall()
    if not rows:
        raise ValueError("pg_mail_source_missing")
    result: list[dict[str, object]] = []
    for source_key, source_sha256, payload_json in rows:
        payload = json.loads(str(payload_json))
        if not isinstance(payload, dict):
            raise ValueError("pg_mail_payload_invalid")
        result.append({
            "source_key": str(source_key),
            "source_sha256": str(source_sha256),
            "payload": payload,
        })
    return result


def load_service_mail_records(db: sqlite3.Connection) -> dict[str, dict[str, object]]:
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records
           WHERE source_kind='service_mail'
           ORDER BY source_key"""
    ).fetchall()
    if not rows:
        raise ValueError("service_mail_source_missing")
    result: dict[str, dict[str, object]] = {}
    for source_key, source_sha256, payload_json in rows:
        payload = json.loads(str(payload_json))
        if not isinstance(payload, dict):
            raise ValueError("service_mail_payload_invalid")
        result[str(source_key)] = {
            "source_key": str(source_key),
            "source_sha256": str(source_sha256),
            "payload": payload,
        }
    return result


def _merchant_match(row: Mapping[str, object], payload: Mapping[str, object]) -> bool:
    current = _norm(row.get("merchant"))
    external = _norm(payload.get("merchant"))
    if not current or not external:
        return True
    return current in external or external in current


def _schedule_target(
    start_text: str,
    end_text: str,
    schedule: Mapping[str, Mapping[str, object]],
) -> str | None:
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text or start_text)
    except ValueError:
        return None
    matches: list[str] = []
    for tab, item in schedule.items():
        try:
            year = int(item.get("service_year", 2026))
            trip_start = date(year, int(item["mm"]), int(item["dd"]))
            trip_end = trip_start + timedelta(days=int(item["window"]) - 1)
        except (KeyError, TypeError, ValueError):
            continue
        if trip_start <= start and end <= trip_end:
            matches.append(str(tab))
    return matches[0] if len(matches) == 1 else None


def _service_period(
    pg_payload: Mapping[str, object],
    service_records: Mapping[str, Mapping[str, object]],
) -> tuple[str, str, str] | None:
    start = str(pg_payload.get("service_start_on") or "")
    end = str(pg_payload.get("service_end_on") or start)
    service_key = str(pg_payload.get("service_evidence_key") or "")
    if service_key:
        linked = service_records.get(service_key)
        if linked is None:
            return None
        linked_payload = linked.get("payload")
        if not isinstance(linked_payload, Mapping):
            return None
        start = str(linked_payload.get("service_start_on") or "")
        end = str(linked_payload.get("service_end_on") or start)
        return start, end, str(linked.get("source_key") or service_key)
    if start:
        return start, end, "pg_mail"
    return None


def _is_travel_text(payload: Mapping[str, object], service: object) -> bool:
    text = _norm(
        f"{payload.get('merchant') or ''} {payload.get('product') or ''}"
    )
    return bool(service) or any(token in text for token in (
        "항공", "FLIGHT", "HOTEL", "숙박", "호텔", "휴양림", "산림",
        "리조트", "여행", "투어", "렌터", "RENTAL", "CAR", "의왕도시공사",
    ))


def evidence_for_row(
    row: Mapping[str, object],
    pg_records: Iterable[Mapping[str, object]],
    service_records: Mapping[str, Mapping[str, object]],
    schedule: Mapping[str, Mapping[str, object]],
) -> dict[str, object] | None:
    current_approval = _approval(row.get("approval"))
    original_approval = _approval(row.get("original_approval"))
    current_amount = abs(int(row.get("amount_krw") or 0))
    transaction_type = str(row.get("transaction_type") or "")
    candidates: list[Mapping[str, object]] = []
    for item in pg_records:
        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            continue
        external_approval = _approval(payload.get("approval_number"))
        approval_match = bool(external_approval) and external_approval in {
            current_approval, original_approval,
        }
        if not approval_match:
            if current_approval or original_approval:
                continue
            try:
                if abs(int(payload.get("amount_krw") or 0)) != current_amount:
                    continue
                if str(payload.get("payment_date") or "") != str(
                    row.get("occurred_on") or ""
                ):
                    continue
            except (TypeError, ValueError):
                continue
        if transaction_type == "purchase":
            if str(payload.get("status") or "") not in {"purchase"}:
                continue
            try:
                external_amount = abs(int(payload.get("amount_krw") or 0))
            except (TypeError, ValueError):
                continue
            if external_amount != current_amount:
                continue
            if str(payload.get("payment_date") or "") and str(
                payload.get("payment_date")
            ) != str(row.get("occurred_on") or ""):
                continue
        else:
            if str(payload.get("status") or "") not in {
                "cancel", "partial_cancel", "refund",
            }:
                continue
            try:
                cancel_amount = payload.get("cancel_amount_krw")
                if cancel_amount not in (None, "") and int(cancel_amount) not in {
                    0, current_amount,
                }:
                    continue
            except (TypeError, ValueError):
                continue
        if not _merchant_match(row, payload):
            continue
        candidates.append(item)
    if len(candidates) != 1:
        return None
    item = candidates[0]
    payload = item["payload"]
    assert isinstance(payload, Mapping)
    period = _service_period(payload, service_records)
    service_start, service_end, service_key = period or ("", "", "")
    target_hint = _schedule_target(service_start, service_end, schedule) if period else None
    service = service_records.get(service_key) if service_key else None
    travel = _is_travel_text(payload, service)
    kind = "lodging" if service or any(
        token in _norm(f"{payload.get('merchant') or ''} {payload.get('product') or ''}")
        for token in ("숙박", "호텔", "휴양림", "리조트", "산림")
    ) else "airfare" if any(
        token in _norm(f"{payload.get('merchant') or ''} {payload.get('product') or ''}")
        for token in ("항공", "FLIGHT")
    ) else "travel"
    result: dict[str, object] = {
        "contract": CONTRACT,
        "authority_status": "verified_external",
        "source_kind": "pg_mail",
        "source_key": str(item.get("source_key") or ""),
        "source_digest": str(item.get("source_sha256") or ""),
        "provider": str(payload.get("provider") or ""),
        "approval_number": str(payload.get("approval_number") or ""),
        "order_id": str(payload.get("order_id") or ""),
        "merchant": str(payload.get("merchant") or ""),
        "product": str(payload.get("product") or ""),
        "amount_krw": int(payload.get("amount_krw") or 0),
        "classification": "travel" if travel else "overhead",
        "travel_kind": kind,
        "match_method": "pg_exact_approval_amount_date_merchant",
        "legacy_transaction_evidence_used": False,
    }
    if period:
        result.update({
            "service_start": service_start,
            "service_end": service_end,
            "service_evidence_key": service_key,
            "target_status": "schedule_target" if target_hint else "schedule_hint",
        })
        if target_hint:
            result.update({"target_hint": target_hint, "auto_confirmed": True})
            result["match_method"] = (
                "pg_exact_approval_amount_date_merchant_service_mail"
            )
    if str(payload.get("status") or "") in {"cancel", "partial_cancel", "refund"}:
        result["travel_kind"] = "lodging_cancellation" if travel else "refund"
        result["lifecycle"] = "partial_cancellation" if str(
            payload.get("status")
        ) == "partial_cancel" else "cancellation"
    return result
