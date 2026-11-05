"""Domain adapters for creating and applying owner action queue tasks."""
from __future__ import annotations

from urllib.parse import urlencode

from app.ai_classification import ITEMS

from . import user_action_queue


def register_card_item_tasks(conn, rows, job_loader):
    """Create P3 category choices only after a clean P1/P2 terminal result."""
    count = 0
    for row in rows:
        transaction_id, batch_id, revision, _state, _source, item, _tab, _trip, source_hash, _date = row
        job = job_loader(conn, transaction_id) or {}
        if job.get("status") not in {"no_ai_needed", "p2_applied"} or str(item or "").strip():
            continue
        action = user_action_queue.register(
            conn,
            group_key=f"card-item:{transaction_id}",
            task_type="카드 비용 항목",
            title="카드 거래 비용 항목 확인",
            question="이 거래의 비용 항목을 선택해 주세요.",
            evidence_summary="자동 분류를 마쳤지만 비용 항목을 정하지 못했습니다. 거래 화면에서 원문을 확인할 수 있습니다.",
            recommendation="",
            source_refs=(transaction_id,),
            source_revision=f"{int(revision)}:{source_hash}",
            answer_options=({"value": value, "label": value} for value in ITEMS),
            answer_effect={"kind": "card_item", "transaction_id": transaction_id,
                           "batch_id": batch_id, "revision": int(revision), "source_hash": source_hash},
            action_url="/import?" + urlencode({"batch": batch_id, "transaction": transaction_id}),
        )
        if action.get("state") == user_action_queue.OPEN:
            count += 1
    return count


def apply_card_item_answers(conn, flow):
    """Apply submitted category answers through the existing manual-decision API."""
    applied = 0
    for task in user_action_queue.pending_answers(conn):
        effect = task.get("answer_effect") or {}
        if effect.get("kind") != "card_item":
            continue
        transaction_id = str(effect.get("transaction_id") or "")
        answer = (task.get("answer") or {}).get("value")
        current = conn.execute(
            "SELECT revision,source_hash,classification_state,classification_source,item,display_tab_id,trip_id,"
            "parse_error,conflict_reason,duplicate_of,transaction_direction,amount_krw,decided_at "
            "FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        batch_exists = conn.execute(
            "SELECT 1 FROM import_batch_rows WHERE batch_id=? AND transaction_id=?",
            (str(effect.get("batch_id") or ""), transaction_id)).fetchone()
        financial_guard = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM ledger_entries WHERE transaction_id=?),"
            " EXISTS(SELECT 1 FROM board_rows WHERE row_id='card-'||?),"
            " EXISTS(SELECT 1 FROM review_decisions WHERE transaction_id=?),"
            " EXISTS(SELECT 1 FROM board_manual_overrides WHERE row_id='card-'||?),"
            " EXISTS(SELECT 1 FROM transaction_review_holds WHERE transaction_id=?),"
            " EXISTS(SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=? AND excluded=1),"
            " EXISTS(SELECT 1 FROM transactions t JOIN transactions f"
            " ON f.issuer=t.issuer AND f.card_tail=t.card_tail"
            " AND f.original_approval_number=t.approval_number"
            " WHERE t.transaction_id=? AND COALESCE(t.approval_number,'')!=''"
            " AND (f.transaction_direction IN ('cancellation','refund') OR f.amount_krw<0))",
            (transaction_id, transaction_id, transaction_id, transaction_id, transaction_id,
             transaction_id, transaction_id),
        ).fetchone()
        if not current or not batch_exists:
            user_action_queue.set_state(conn, task["action_id"], user_action_queue.SUPERSEDED)
            continue
        (revision, source_hash, state, source, item, tab, trip, parse_error, conflict,
         duplicate, direction, amount, decided_at) = current
        decision_request = "user-action-answer:" + task["action_id"]
        replayed = conn.execute(
            "SELECT 1 FROM requests WHERE request_id=? AND scope='save_decision'",
            (decision_request,)).fetchone()
        decision_matches = conn.execute(
            "SELECT 1 FROM review_decisions WHERE transaction_id=? AND item=?",
            (transaction_id, str(answer or ""))).fetchone()
        if (replayed and decision_matches and source == "user_decision" and item == answer
                and str(source_hash or "") == str(effect.get("source_hash") or "")):
            user_action_queue.set_state(conn, task["action_id"], user_action_queue.RESOLVED)
            applied += 1
            continue
        eligible = (
            int(revision) == int(effect.get("revision", -1))
            and str(source_hash or "") == str(effect.get("source_hash") or "")
            and state not in ("booked",)
            and source not in ("user_decision", "user_exception", "owner_booking", "manual", "manual_hold")
            and not str(item or "").strip() and not parse_error and not conflict and not duplicate
            and direction == "purchase" and int(amount or 0) > 0 and not decided_at
            and not any(financial_guard)
            and answer in ITEMS
        )
        if not eligible:
            user_action_queue.set_state(conn, task["action_id"], user_action_queue.SUPERSEDED)
            continue
        valid_tab = str(tab or "unclassified")
        valid_trip = str(trip or "")
        if not flow.tab_valid(valid_tab) or (valid_trip and not flow.trip_valid(valid_trip)):
            user_action_queue.set_state(conn, task["action_id"], user_action_queue.SUPERSEDED)
            continue
        flow.pipeline.save_decision(
            transaction_id, int(revision), item=str(answer), description="",
            display_tab_id=valid_tab, trip_id=valid_trip,
            note="내 확인 필요 답변", reuse_rule=False,
            request_id="user-action-answer:" + task["action_id"],
            trip_validator=flow.trip_valid, tab_validator=flow.tab_valid,
        )
        user_action_queue.set_state(conn, task["action_id"], user_action_queue.RESOLVED)
        applied += 1
    return applied
