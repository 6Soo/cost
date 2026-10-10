"""Natural-language rule proposal for one card batch. Read-only: it never saves anything.

The browser applies an approved proposal by posting each decision to the existing review decision
endpoint, so every save keeps the existing revision, trip and hold checks. This module only builds
the proposal and a fingerprint of the exact decisions, so an approval can be refused if the
rows changed after the person looked at the proposal.
"""

from __future__ import annotations

import hashlib
import json
import re

from app import rule_proposals
from .card_flow import CardFlow

ROUTE = re.compile(r"^/api/imports/([^/]+)/rule-proposal$")


def owns_route(path: str) -> bool:
    return ROUTE.match(path) is not None


def fingerprint(payloads: list[dict], rows: list[dict]) -> str:
    """Covers the exact decisions and the money and date they would be made on."""
    by_id = {r["transaction_id"]: r for r in rows}
    stable = sorted((p["transaction_id"], p["revision"], p["item"], by_id[p["transaction_id"]]["amount_krw"],
                     by_id[p["transaction_id"]]["occurred_on"]) for p in payloads)
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def propose(state: dict, *, text: str, transaction_id: str) -> dict:
    rows = state["preview"]["rows"]
    focus = next((r for r in rows if r["transaction_id"] == transaction_id), None)
    if focus is None:
        raise KeyError("ROW_NOT_IN_BATCH")
    proposal = rule_proposals.propose(text, rows=rows, focus={"transaction_id": transaction_id,
                                                              "merchant": focus.get("merchant")})
    payloads = rule_proposals.decision_payloads(proposal, rows) if proposal["status"] == "proposed" else []
    return {"text": text, "transaction_id": transaction_id, "status": proposal["status"],
            "kind": proposal.get("kind"), "skipped_confirmed": proposal.get("skipped_confirmed", 0),
            "needs_confirmation": bool(proposal.get("needs_confirmation")),
            "changes": [{"transaction_id": c["transaction_id"], "before_item": c["before_item"],
                         "after_item": c["after_item"]} for c in proposal.get("changes", [])
                        if not c.get("exclude")],
            "payloads": payloads, "digest": fingerprint(payloads, rows)}


def dispatch(handler, parsed, *, raw, csrf: str, board) -> bool:
    match = ROUTE.match(parsed.path)
    if match is None:
        return False
    if raw is None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
        handler._send_json({"code": "CSRF_REQUIRED", "message": "화면을 다시 열어 주세요"}, 403)
        return True
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
        text = str(body.get("text", "")).strip()
        if not text:
            raise ValueError("TEXT_REQUIRED")
        state = CardFlow(board).state(match.group(1))
        handler._send_json(propose(state, text=text, transaction_id=str(body.get("transaction_id", ""))))
    except (ValueError, KeyError, TypeError) as error:
        handler._send_json({"code": str(error) or "INVALID_VALUE"}, 400)
    return True
