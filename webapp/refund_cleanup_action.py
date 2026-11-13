"""Owner-only, in-place preview/commit for already-imported verified full refund groups.

Deliberately does not run on GET or silently backfill financial records.
Only the selected, unambiguous, zero-net group can be committed, never
other cards from the same file. Reuses ledger.preview/commit and its guards.
"""
from __future__ import annotations

import json
import re

from app import StoreError

_ROUTE = re.compile(r"^/api/maintenance/refund-pair/([a-zA-Z0-9_:-]{1,160})/(preview|apply)$")


def _group_context(board, original_id):
    from app.partial_refund import refund_links, refund_group, is_numbered_partial
    from .card_flow import CardFlow

    source = board.conn.execute(
        "SELECT transaction_direction FROM transactions WHERE transaction_id=?",
        (original_id,),
    ).fetchone()
    if not source or source[0] != "purchase":
        raise StoreError("REFUND_SOURCE_NOT_FOUND", "원결제 거래를 찾을 수 없습니다")
    members = refund_group(board.conn, original_id)
    if len(members) < 2:
        raise StoreError("REFUND_LINK_NOT_VERIFIED", "검증된 취소·환불 연결이 없습니다")
    links = refund_links(board.conn, members[1:])
    if (len(links) != len(members) - 1
            or any(link["original_id"] != original_id or link.get("inferred")
                   or not ((link.get("status") == "full" and link.get("net_krw") == 0)
                           or is_numbered_partial(link))
                   for link in links.values())):
        raise StoreError("REFUND_LINK_NOT_VERIFIED",
                         "추론 연결이거나 원승인번호로 검증되지 않은 거래는 자동 기록하지 않습니다")

    # Source provenance and the complete member set are determined on the server.
    batch = board.conn.execute(
        "SELECT batch_id FROM import_batch_rows WHERE transaction_id=? ORDER BY batch_id LIMIT 1",
        (original_id,),
    ).fetchone()
    if not batch:
        raise StoreError("REFUND_SOURCE_NOT_FOUND", "원결제 카드 파일 출처가 없습니다")
    flow = CardFlow(board)
    holds = flow.automatic_holds(batch[0], include_verified_full_refunds=True)
    # A real ledger entry is already protected by the core's UNIQUE/idempotency
    # checks. Its projection must not stop the missing side of this verified
    # group. Keep legacy projections without a ledger entry and every other
    # automatic hold; persisted/manual holds are re-read by ledger.preview.
    booked = {row[0] for row in board.conn.execute(
        'SELECT transaction_id FROM ledger_entries')}
    holds = {tid: hold for tid, hold in holds.items()
             if not (tid in members and tid in booked
                     and hold.get('kind') == 'existing_ledger')}
    options = dict(
        trip_validator=flow.trip_valid,
        tab_validator=flow.tab_valid,
        additional_holds=holds,
        group_original=original_id,
        include_verified_full_refunds=True,
    )
    result = flow.pipeline.preview(batch[0], **options)
    if {r["transaction_id"] for r in result["rows"]} != set(members):
        raise StoreError("REFUND_GROUP_INCOMPLETE", "원결제·환불 원본 전체가 같은 미리보기에 없습니다")
    net = sum(int(row["amount_krw"]) for row in result["rows"])
    if net != (0 if all(l.get("status") == "full" for l in links.values()) else links[members[1]]["net_krw"]):
        raise StoreError("REFUND_GROUP_INCOMPLETE", "원결제와 환불의 순액이 검증된 순잔액과 다릅니다")
    return flow, batch[0], result, options


def _preview_response(result):
    all_rows = result["rows"]
    return {
        "recordable": bool(result.get("recordable")),
        "digest": result["digest"],
        "members": len(all_rows),
        "net_krw": sum(int(row["amount_krw"]) for row in all_rows),
        "already_booked": sum(bool(row.get("already_booked")) for row in all_rows),
        "to_book": sum(not row.get("already_booked") and not row.get("blocked") for row in all_rows),
        "reason": result.get("reason") or "",
        "message": ("이 원결제·취소 묶음만 장부에 함께 기록합니다. 환급 완료 증빙과는 별개입니다."
                    if result.get("recordable") else
                    result.get("reason") or "금융 보호로 인해 기록할 수 없습니다"),
    }


def dispatch(handler, parsed, *, board, raw=None, csrf=""):
    match = _ROUTE.fullmatch(parsed.path)
    if not match:
        return False
    from . import ledger_board
    if ledger_board.current_role() != "owner":
        handler._send_json({"code": "FORBIDDEN"}, 403)
        return True
    if raw is None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
        handler._send_json({"code": "CSRF_REQUIRED"}, 403)
        return True
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid request")
    except (ValueError, TypeError, UnicodeDecodeError):
        handler._send_json({"code": "INVALID_INPUT"}, 422)
        return True
    original, action = match.groups()
    try:
        with board._lock:
            flow, batch, result, options = _group_context(board, original)
            summary = _preview_response(result)
            if action == "preview":
                handler._send_json(summary)
                return True
            digest = payload.get("digest")
            request_id = payload.get("request_id")
            if (not isinstance(digest, str) or len(digest) != 64
                    or not re.fullmatch("[a-f0-9]{64}", digest)
                    or not isinstance(request_id, str)
                    or not re.fullmatch("[a-zA-Z0-9_-]{12,96}", request_id)):
                handler._send_json({"code": "INVALID_INPUT"}, 422)
                return True
            committed = flow.pipeline.commit(
                batch, digest, request_id,
                projection=flow.project,
                automatic_record=True,
                **options,
            )
            handler._send_json({"applied": committed["applied"],
                                "message": "검증된 환불 묶음의 장부 기록을 확인했습니다."})
            return True
    except StoreError as exc:
        handler._send_json({"code": exc.code,
                            "message": str(exc)}, 409)
        return True
    except (ValueError, TypeError):
        handler._send_json({"code": "INVALID_INPUT",
                            "message": "자료 형식이 올바르지 않습니다."}, 422)
        return True
