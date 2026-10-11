"""Natural-language rule proposal for one card batch.

Two routes. The proposal is read-only and saves nothing. The approval re-derives the proposal on the
server, refuses it when the fingerprint no longer matches what the person approved, and saves all
decisions in one transaction through app.review.save_decisions_atomic, which reuses the single-answer
checks. Any failure rolls every write back.
"""

from __future__ import annotations

import hashlib
import json
import re

from app import rule_proposals, review
from .card_flow import CardFlow

ROUTE = re.compile(r"^/api/imports/([^/]+)/rule-proposal$")
APPROVE = re.compile(r"^/api/imports/([^/]+)/rule-proposal/approve$")
EXCLUSION = re.compile(r"^/api/imports/([^/]+)/company-exclusion$")


def owns_route(path: str) -> bool:
    return ROUTE.match(path) is not None or APPROVE.match(path) is not None or EXCLUSION.match(path) is not None


def fingerprint(payloads: list[dict], rows: list[dict]) -> str:
    """Binds decisions to the reviewed assignment, description and source values, not just the revision."""
    by_id = {r["transaction_id"]: r for r in rows}
    stable = sorted((p["transaction_id"], p["revision"], p["item"], p.get("description", ""),
                     p.get("display_tab_id", ""), by_id[p["transaction_id"]]["amount_krw"],
                     by_id[p["transaction_id"]]["occurred_on"], by_id[p["transaction_id"]].get("item"),
                     by_id[p["transaction_id"]].get("merchant"), by_id[p["transaction_id"]].get("trip_id"))
                    for p in payloads)
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
                        ],
            "payloads": payloads, "digest": fingerprint(payloads, rows)}


class RequestIdReused(Exception):
    code = "REQUEST_ID_REUSED"


def request_basis(batch: str, body: dict) -> str:
    """What the person approved: the batch, the focus row, the sentence and the fingerprint of the proposal."""
    basis = {"batch": batch, "transaction_id": str(body.get("transaction_id", "")),
             "text": str(body.get("text", "")).strip(), "digest": str(body.get("digest", ""))}
    return hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def approve(flow: CardFlow, batch: str, body: dict) -> dict:
    # HTTP requests share this connection. Keep its read/replay/write sequence together.
    with flow.pipeline.store.lock:
        return _approve_locked(flow, batch, body)


def saved_response(flow: CardFlow, batch: str, result: dict, *, classify: bool = False) -> dict:
    """A failed read after a committed write must not report that write as rolled back."""
    state = flow.saved_state(batch, classify=classify)
    if state.get('refresh_required'):
        return {**result, 'state': None, 'refresh_required': True}
    return {**result, 'state': state}


def _approve_locked(flow: CardFlow, batch: str, body: dict) -> dict:
    if body.get("approved") is not True:
        raise ValueError("APPROVAL_REQUIRED")
    request_id = str(body.get("request_id", ""))
    if not request_id:
        raise ValueError("REQUEST_ID_REQUIRED")
    basis = request_basis(batch, body)
    def replay():
        earlier = review.batch_result_for(flow.pipeline.store, request_id)
        if earlier is None:
            return None
        if earlier.get("basis") != basis:
            raise RequestIdReused("same request id, different approval")
        return saved_response(flow, batch,
                              {"applied": [x["transaction_id"] for x in earlier["results"]]}, classify=True)

    earlier = replay()
    if earlier is not None:
        return earlier
    state = flow.state(batch)
    proposal = propose(state, text=str(body.get("text", "")).strip(),
                       transaction_id=str(body.get("transaction_id", "")))
    if proposal["digest"] != body.get("digest"):
        # Another connection may have committed this approval while we read the state.
        earlier = replay()
        if earlier is not None:
            return earlier
        raise LookupError("STALE_PROPOSAL")
    if not proposal["payloads"]:
        raise ValueError("NOTHING_TO_APPLY")
    amounts = {r["transaction_id"]: r["amount_krw"] for r in state["preview"]["rows"]}
    decisions = []
    for payload in proposal["payloads"]:
        tab = str(payload.get("display_tab_id") or "")
        decisions.append({**payload, "trip_id": tab if tab not in ("", "unclassified") else "",
                          "expected_amount_krw": amounts[payload["transaction_id"]]})
    result = review.save_decisions_atomic(flow.pipeline.store, decisions, request_id=request_id,
                                          tab_validator=flow.tab_valid, trip_validator=flow.trip_valid,
                                          basis=basis)
    return saved_response(flow, batch,
                          {"applied": [r["transaction_id"] for r in result["results"]]}, classify=True)


def dispatch(handler, parsed, *, raw, csrf: str, board) -> bool:
    proposal_match = ROUTE.match(parsed.path)
    approve_match = APPROVE.match(parsed.path)
    exclusion_match = EXCLUSION.match(parsed.path)
    if proposal_match is None and approve_match is None and exclusion_match is None:
        return False
    if raw is None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
        handler._send_json({"code": "CSRF_REQUIRED", "message": "화면을 다시 열어 주세요"}, 403)
        return True
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError('INVALID_VALUE')
        if exclusion_match:
            from .ledger_board import _receipts_owner_request
            if not _receipts_owner_request():
                handler._send_json({'code': 'OWNER_ONLY', 'message': '소유자만 변경할 수 있습니다'}, 403)
                return True
            from app.company_expenses import set_excluded
            flow = CardFlow(board)
            batch = exclusion_match.group(1)
            transaction_id = str(body.get('transaction_id') or '')
            if not flow.pipeline.store.conn.execute(
                    'SELECT 1 FROM import_batch_rows WHERE batch_id=? AND transaction_id=?',
                    (batch, transaction_id)).fetchone():
                raise KeyError('ROW_NOT_IN_BATCH')
            result = set_excluded(flow.pipeline.store, transaction_id=transaction_id,
                                  expected_revision=body.get('revision'),
                                  expected_exclusion_revision=body.get('exclusion_revision'),
                                  excluded=body.get('excluded'), confirmed=body.get('confirmed'),
                                  request_id=body.get('request_id'), note=str(body.get('note') or ''))
            handler._send_json(saved_response(flow, batch, {'result': result}))
            return True
        if approve_match:
            handler._send_json(approve(CardFlow(board), approve_match.group(1), body))
            return True
        text = str(body.get("text", "")).strip()
        if not text:
            raise ValueError("TEXT_REQUIRED")
        state = CardFlow(board).state(proposal_match.group(1))
        handler._send_json(propose(state, text=text, transaction_id=str(body.get("transaction_id", ""))))
    except RequestIdReused:
        handler._send_json({"code": "REQUEST_ID_REUSED",
                            "message": "이 요청 번호는 다른 승인에 이미 쓰였습니다. 새로고침 후 다시 승인하세요"}, 409)
    except LookupError as error:
        handler._send_json({"code": str(error), "message": "제안 이후 거래가 바뀌었습니다. 다시 제안하세요"}, 409)
    except (ValueError, KeyError, TypeError) as error:
        handler._send_json({"code": str(error) or "INVALID_VALUE"}, 400)
    except Exception as error:  # a store refusal rolled the whole batch back
        code = getattr(error, "code", None)
        if code is None:
            raise
        handler._send_json({"code": code, "message": "일괄 적용하지 않았습니다. 모든 변경을 되돌렸어요"}, 409)
    return True
