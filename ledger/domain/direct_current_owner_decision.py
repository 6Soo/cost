"""Content-bound owner decisions for the current-card projection.

These are explicit current-run decisions, not manual-ledger training data and
not transaction evidence.  They are imported as a declared source so their
scope and rationale remain part of the run provenance.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from typing import Mapping


CONTRACT = "current-owner-decision-v1"
FORMAT_VERSION = 1
SOURCE_KIND = "current_owner_decision"
REQUIRED_FIELDS = {
    "decision_id", "source_system", "occurred_on", "approval_number",
    "amount_krw", "merchant_tokens", "account", "cost_type",
    "allocation_target", "decision_status", "scope_status", "rationale",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return re.sub(r"[^0-9A-Z가-힣]+", "", text)


def _approval(value: object) -> str:
    return "".join(re.findall(r"\d", str(value or "")))


def parse_owner_decision_document(raw: bytes) -> list[dict[str, object]]:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("current_owner_decision_json_invalid") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"format_version", "contract", "decisions"}
        or document.get("format_version") != FORMAT_VERSION
        or document.get("contract") != CONTRACT
        or not isinstance(document.get("decisions"), list)
        or not document["decisions"]
    ):
        raise ValueError("current_owner_decision_document_invalid")
    result: list[dict[str, object]] = []
    decision_ids: set[str] = set()
    payment_keys: set[tuple[str, str, str, int]] = set()
    for index, item in enumerate(document["decisions"]):
        if not isinstance(item, dict) or set(item) - (REQUIRED_FIELDS | {"quarter"}):
            raise ValueError(f"current_owner_decision_row_invalid:{index}")
        if set(item) & REQUIRED_FIELDS != REQUIRED_FIELDS:
            raise ValueError(f"current_owner_decision_row_incomplete:{index}")
        decision_id = str(item["decision_id"]).strip()
        source = str(item["source_system"]).strip()
        approval = _approval(item["approval_number"])
        occurred_on = str(item["occurred_on"]).strip()
        amount = item["amount_krw"]
        tokens = item["merchant_tokens"]
        if (
            not decision_id or decision_id in decision_ids or not source
            or not occurred_on or not approval or type(amount) is not int
            or amount <= 0 or not isinstance(tokens, list) or not tokens
            or any(not isinstance(token, str) or not token.strip() for token in tokens)
        ):
            raise ValueError(f"current_owner_decision_identity_invalid:{index}")
        payment_key = (source, occurred_on, approval, amount)
        if payment_key in payment_keys:
            raise ValueError("current_owner_decision_duplicate_payment_key")
        if item["decision_status"] != "confirmed":
            raise ValueError("current_owner_decision_status_invalid")
        if not all(isinstance(item[field], str) and item[field].strip() for field in (
            "account", "cost_type", "allocation_target", "scope_status", "rationale",
        )):
            raise ValueError(f"current_owner_decision_value_invalid:{index}")
        decision_ids.add(decision_id)
        payment_keys.add(payment_key)
        result.append({
            "format_version": FORMAT_VERSION,
            "contract": CONTRACT,
            **dict(item),
            "approval_number": approval,
            "merchant_tokens": [str(token) for token in tokens],
        })
    return result


def source_keys(raw: bytes) -> list[str]:
    return [str(row["decision_id"]) for row in parse_owner_decision_document(raw)]


def load_current_owner_decisions(db: object) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records
           WHERE source_kind=? ORDER BY source_key""",
        (SOURCE_KIND,),
    ).fetchall()
    decisions: list[dict[str, object]] = []
    for source_key, source_sha256, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("current_owner_decision_payload_invalid") from exc
        if not isinstance(payload, dict) or payload.get("decision_id") != source_key:
            raise ValueError("current_owner_decision_source_binding_invalid")
        decisions.append({
            **payload,
            "source_kind": SOURCE_KIND,
            "source_key": str(source_key),
            "source_sha256": str(source_sha256),
        })
    return decisions


def decision_for_row(
    row: Mapping[str, object],
    decisions: list[dict[str, object]],
) -> dict[str, object] | None:
    source = str(row.get("source") or "")
    occurred_on = str(row.get("occurred_on") or row.get("use") or "")
    approval = _approval(
        row.get("approval_number") or row.get("approval") or row.get("appr")
    )
    amount = abs(int(row.get("amount_krw") or 0))
    merchant_text = _norm(f"{row.get('merchant') or ''} {row.get('biz') or ''}")
    matches = [
        item for item in decisions
        if str(item.get("source_system") or "") == source
        and str(item.get("occurred_on") or "") == occurred_on
        and _approval(item.get("approval_number")) == approval
        and int(item.get("amount_krw") or 0) == amount
        and all(_norm(token) in merchant_text for token in item.get("merchant_tokens", ()))
    ]
    if len(matches) > 1:
        raise ValueError("current_owner_decision_ambiguous")
    return dict(matches[0]) if matches else None


def assert_single_use(matches: list[dict[str, object] | None]) -> None:
    counts = Counter(
        str(item["decision_id"])
        for item in matches
        if isinstance(item, dict)
    )
    if any(count > 1 for count in counts.values()):
        raise ValueError("current_owner_decision_reused")
