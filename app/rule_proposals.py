"""Turns a short Korean instruction into a reviewable classification proposal. No AI model.

A deterministic parser recognises a few fixed phrasings (merchant rule, this-one-only, not a
company expense). It never reads a raw bank amount, date or id as something to change. Nothing
changes until a person approves the exact preview; approval touches only rows the user has not
already decided, writes an audit entry, and a second approval of the same proposal does nothing.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

PATTERN_MERCHANT = re.compile(r"^(?:이|같은) 가맹점(?:\s*\S+)?\s*(?:은|는)?\s*(?:앞으로\s*)?(?P<item>\S+?)(?:으로|로)\s*(?:분류|처리)")
PATTERN_THIS_ONLY = re.compile(r"^이 건(?:만|은)?\s*(?P<item>\S+?)(?:으로|로)\s*(?:분류|처리|바꿔)")
PATTERN_AGODA = re.compile(r"^아고다\s*결제는\s*(?P<item>\S+?)(?:으로|로)\s*(?:분류|처리)")
PATTERN_NOT_COMPANY = re.compile(r"회사 경비 아님")
PATTERN_ORIGINAL = re.compile(r"(금액|날짜|일자|거래 ?id|승인번호).{0,20}?(바꿔|수정|변경)", re.IGNORECASE)


def parse(text: str, merchant_hint: str | None = None) -> dict:
    """Returns {kind, item?, merchant?} or {kind: 'REJECTED_ORIGINAL_EDIT' | 'NOT_UNDERSTOOD'}."""
    cleaned = text.strip()
    if PATTERN_ORIGINAL.search(cleaned):
        return {"kind": "REJECTED_ORIGINAL_EDIT"}
    if PATTERN_NOT_COMPANY.search(cleaned):
        return {"kind": "NOT_COMPANY", "merchant": merchant_hint}
    if match := PATTERN_THIS_ONLY.match(cleaned):
        return {"kind": "THIS_ONLY", "item": match.group("item")}
    if match := PATTERN_MERCHANT.match(cleaned):
        return {"kind": "MERCHANT_RULE", "item": match.group("item"), "merchant": merchant_hint}
    # A named provider must match the focused transaction; never widen a rule to unrelated cards.
    if match := PATTERN_AGODA.match(cleaned):
        if merchant_hint and re.search(r"AGODA|아고다", merchant_hint, re.IGNORECASE):
            return {"kind": "MERCHANT_RULE", "item": match.group("item"), "merchant": merchant_hint}
    return {"kind": "NOT_UNDERSTOOD"}


def propose(text: str, *, rows: list[dict], focus: dict) -> dict:
    """focus: the row the user is looking at (transaction_id, merchant)."""
    parsed = parse(text, merchant_hint=focus.get("merchant"))
    if parsed["kind"] in ("REJECTED_ORIGINAL_EDIT", "NOT_UNDERSTOOD"):
        return {"id": None, "status": parsed["kind"], "changes": [], "skipped_decided": 0}
    if parsed["kind"] == "THIS_ONLY":
        scope = [r for r in rows if r["transaction_id"] == focus["transaction_id"]]
    elif parsed["kind"] == "MERCHANT_RULE":
        scope = [r for r in rows if r.get("merchant") == parsed.get("merchant")]
    else:
        scope = [r for r in rows if r["transaction_id"] == focus["transaction_id"]]
    skipped = [r for r in scope if r.get("decided")]
    changes = []
    for row in scope:
        if row.get("decided"):
            continue
        new_item = None if parsed["kind"] == "NOT_COMPANY" else parsed["item"]
        changes.append({"transaction_id": row["transaction_id"], "amount_krw": row["amount_krw"],
                        "occurred_on": row["occurred_on"], "before_item": row.get("item"), "after_item": new_item,
                        "exclude": parsed["kind"] == "NOT_COMPANY"})
    return {"id": f"p-{uuid.uuid4().hex}", "status": "proposed", "kind": parsed["kind"], "changes": changes,
            "skipped_decided": len(skipped), "needs_confirmation": parsed["kind"] == "NOT_COMPANY"}


class AuditLog:
    def __init__(self, path: Path):
        self.path = path

    def entries(self) -> list:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def append(self, entry: dict) -> None:
        data = self.entries() + [entry]
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def apply(proposal: dict, *, approved: bool, approved_by: str, rows: list[dict], audit: AuditLog,
          confirm_exclusion: bool = False) -> dict:
    """Applies only to undecided rows, only the classification, only after explicit approval."""
    if not approved:
        raise PermissionError("APPROVAL_REQUIRED")
    if proposal.get("status") != "proposed":
        raise ValueError("NOT_APPLICABLE")
    if proposal.get("needs_confirmation") and not confirm_exclusion:
        raise PermissionError("EXCLUSION_NEEDS_CONFIRMATION")
    if any(e.get("proposal_id") == proposal["id"] for e in audit.entries()):
        return {"status": "ALREADY_APPLIED", "applied": []}
    by_id = {r["transaction_id"]: r for r in rows}
    # Check every change before touching any row, so a stale change never leaves a partial apply.
    targets = []
    for change in proposal["changes"]:
        row = by_id.get(change["transaction_id"])
        if row is None or row.get("decided"):
            continue  # a decided row is never overwritten by a rule
        if (row["amount_krw"], row["occurred_on"]) != (change["amount_krw"], change["occurred_on"]):
            raise ValueError("ROW_CHANGED_SINCE_PREVIEW")  # nothing applied; propose again
        if row.get("item", "") != change["before_item"]:
            raise ValueError("ROW_CHANGED_SINCE_PREVIEW")
        targets.append((row, change))
    applied = []
    for row, change in targets:
        if change["exclude"]:
            row["excluded_from_company"] = True
        else:
            row["item"] = change["after_item"]
        applied.append(change["transaction_id"])
    audit.append({"proposal_id": proposal["id"], "kind": proposal["kind"], "approved_by": approved_by,
                  "applied": applied, "skipped_decided": proposal["skipped_decided"]})
    return {"status": "APPLIED", "applied": applied}


def decision_payloads(proposal: dict, rows: list[dict]) -> list[dict]:
    """Request bodies for the existing review decision endpoint, one per approved change.

    Keeps each row's own description, tab and revision, so the decision is written against the
    revision the person saw. Nothing is sent from here.
    """
    by_id = {r["transaction_id"]: r for r in rows}
    payloads = []
    for change in proposal.get("changes", []):
        row = by_id.get(change["transaction_id"])
        if row is None or row.get("decided") or change.get("exclude"):
            continue
        if row.get("item") == change["after_item"]:
            continue  # already has this item; a second decision would only add a revision
        payloads.append({
            "transaction_id": change["transaction_id"],
            "revision": row.get("revision"),
            "item": change["after_item"],
            "description": row.get("description") or "",
            "display_tab_id": row.get("display_tab_id") or "",
            "note": f"규칙 제안 {proposal['id']} 승인",
            "reuse_rule": False,
            "resolve_hold": False,
        })
    return payloads
