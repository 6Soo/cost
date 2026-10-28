"""Bounded, transaction-exact owner proposals in the existing append-only log."""
from __future__ import annotations

import json

from .provisional_assignment import propose_correction_pattern, approve_correction_pattern


def pending_proposals(store, batch_id, *, offset=0):
    rows = store.conn.execute(
        "SELECT detail_json FROM change_log p WHERE kind='trip_correction_rules.proposed' "
        "AND json_extract(detail_json,'$.batch_id')=? AND NOT EXISTS "
        "(SELECT 1 FROM change_log a WHERE a.kind='trip_correction_rules.approved' AND a.subject=p.subject) "
        "ORDER BY entry_id DESC LIMIT 21 OFFSET ?", (batch_id, offset)).fetchall()
    return {"items": [json.loads(row[0])["proposal"] for row in rows[:20]],
            "has_more": len(rows) > 20}


def propose_from_current_decisions(store, batch_id, transaction_ids):
    if (not isinstance(transaction_ids, list) or not 2 <= len(transaction_ids) <= 20
            or any(not isinstance(identity, str) or not identity for identity in transaction_ids)
            or len(set(transaction_ids)) != len(transaction_ids)):
        raise ValueError("SELECT_TWO_TO_TWENTY_DISTINCT_CORRECTIONS")
    with store.lock:
        nested = store.conn.in_transaction
        store.conn.execute("SAVEPOINT propose_trip_corrections" if nested else "BEGIN IMMEDIATE")
        try:
            corrections = []
            from .review import correction_protection_reason
            for identity in transaction_ids:
                row = store.conn.execute(
                    "SELECT t.transaction_id,t.source_hash,t.merchant_normalized,t.revision,t.trip_id,t.item "
                    "FROM transactions t JOIN import_batch_rows b USING(transaction_id) "
                    "WHERE b.batch_id=? AND t.transaction_id=? AND t.classification_source='user_decision' "
                    "AND t.decided_at IS NOT NULL AND COALESCE(t.trip_id,'')!='' "
                    "AND COALESCE(t.duplicate_of,'')='' AND COALESCE(t.conflict_reason,'')=''",
                    (batch_id, identity)).fetchone()
                if row is None or correction_protection_reason(store, identity, row[1]):
                    raise ValueError("CORRECTION_STALE_OR_PROTECTED")
                corrections.append(dict(zip(
                    ("transaction_id", "source_hash", "merchant_normalized", "revision", "trip_id", "item"), row),
                    confidence="낮음", basis="사용자 확정 교정", owner_approved=True))
            proposal = propose_correction_pattern(corrections)
            if proposal.get("status") != "PENDING_OWNER_APPROVAL":
                raise ValueError("CORRECTIONS_MUST_SHARE_EXACT_SCOPE")
            found = store.conn.execute(
                "SELECT detail_json FROM change_log WHERE kind='trip_correction_rules.proposed' AND subject=? LIMIT 1",
                (proposal["id"],)).fetchone()
            if found:
                saved = json.loads(found[0])
                if saved["batch_id"] != batch_id:
                    raise ValueError("PROPOSAL_BATCH_MISMATCH")
                proposal = saved["proposal"]
            else:
                store.log_change("trip_correction_rules.proposed", proposal["id"],
                                 {"batch_id": batch_id, "proposal": proposal})
            store.conn.execute("RELEASE SAVEPOINT propose_trip_corrections" if nested else "COMMIT")
            return proposal
        except BaseException:
            if nested:
                store.conn.execute("ROLLBACK TO SAVEPOINT propose_trip_corrections")
                store.conn.execute("RELEASE SAVEPOINT propose_trip_corrections")
            else:
                store.conn.rollback()
            raise


def approve_stored_proposal(store, batch_id, proposal_id, *, approved_by, trips):
    # Never accept replacement proposal contents from a request body.
    row = store.conn.execute(
        "SELECT detail_json FROM change_log WHERE kind='trip_correction_rules.proposed' AND subject=? LIMIT 1",
        (proposal_id,)).fetchone()
    if row is None:
        raise ValueError("PROPOSAL_NOT_FOUND")
    saved = json.loads(row[0])
    if saved["batch_id"] != batch_id:
        raise ValueError("PROPOSAL_BATCH_MISMATCH")
    return approve_correction_pattern(store, saved["proposal"], approved_by=approved_by, trips=trips)
