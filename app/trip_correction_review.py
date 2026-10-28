"""Bounded, transaction-exact owner proposals in the existing append-only log."""
from __future__ import annotations

import json
import hashlib

from .db import canonical

from .provisional_assignment import propose_correction_pattern, approve_correction_pattern


def pending_proposals(store, batch_id, *, offset=0):
    rows = store.conn.execute(
        "SELECT detail_json FROM change_log p WHERE kind='trip_correction_rules.proposed' "
        "AND json_extract(detail_json,'$.batch_id')=? AND NOT EXISTS "
        "(SELECT 1 FROM change_log a WHERE a.kind='trip_correction_rules.approved' AND a.subject=p.subject) "
        "ORDER BY entry_id DESC LIMIT 21 OFFSET ?", (batch_id, offset)).fetchall()
    items = []
    for row in rows[:20]:
        proposal = json.loads(row[0])["proposal"]
        refs = {ref['transaction_id']: ref for ref in proposal['corrections']}
        current = store.conn.execute(
            "SELECT transaction_id,merchant,approval_date,amount_krw,revision,source_hash FROM transactions "
            "WHERE transaction_id IN (" + ','.join('?' for _ in refs) + ')', tuple(refs)).fetchall()
        review_rows = [dict(zip(('transaction_id', 'merchant', 'date', 'amount_krw', 'revision'), value[:5]),
                            stale=value[4] != refs[value[0]]['revision'] or value[5] != refs[value[0]]['source_hash'])
                       for value in current]
        items.append(dict(proposal, review_rows=review_rows,
                          stale=len(current) != len(refs) or any(value['stale'] for value in review_rows)))
    return {"items": items, "has_more": len(rows) > 20}


def propose_from_current_decisions(store, batch_id, transaction_ids, *, protected_transaction_ids=()):
    if (not isinstance(transaction_ids, list) or not 2 <= len(transaction_ids) <= 20
            or any(not isinstance(identity, str) or not identity for identity in transaction_ids)
            or len(set(transaction_ids)) != len(transaction_ids)):
        raise ValueError("SELECT_TWO_TO_TWENTY_DISTINCT_CORRECTIONS")
    if set(transaction_ids) & set(protected_transaction_ids):
        raise ValueError("CORRECTION_STALE_OR_PROTECTED")
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
                    "AND COALESCE(t.classification_basis,'') NOT LIKE 'AUTO_TRIP_INFERRED%' "
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


def approve_stored_proposal(store, batch_id, proposal_id, *, approved_by, trips, protected_transaction_ids=()):
    # Never accept replacement proposal contents from a request body.
    row = store.conn.execute(
        "SELECT detail_json FROM change_log WHERE kind='trip_correction_rules.proposed' AND subject=? LIMIT 1",
        (proposal_id,)).fetchone()
    if row is None:
        raise ValueError("PROPOSAL_NOT_FOUND")
    saved = json.loads(row[0])
    if saved["batch_id"] != batch_id:
        raise ValueError("PROPOSAL_BATCH_MISMATCH")
    if (set(row['transaction_id'] for row in saved['proposal']['corrections']) & set(protected_transaction_ids)
            and not store.conn.execute("SELECT 1 FROM change_log WHERE kind='trip_correction_rules.approved' AND subject=?",
                                       (proposal_id,)).fetchone()):
        raise ValueError("CORRECTION_STALE_OR_PROTECTED")
    return approve_correction_pattern(store, saved["proposal"], approved_by=approved_by, trips=trips)


def hold_for_review(store, batch_id, *, transaction_id, revision, request_id):
    """Explicit hold only; existing financial holds and recorded costs stay protected."""
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 160:
        raise ValueError("REQUEST_ID_REQUIRED")
    digest = hashlib.sha256(canonical([batch_id, transaction_id, revision]).encode()).hexdigest()
    with store.lock:
        nested = store.conn.in_transaction
        store.conn.execute("SAVEPOINT trip_review_hold" if nested else "BEGIN IMMEDIATE")
        try:
            result = store.replay_request(request_id, "trip_review_hold", digest)
            if result is None:
                from .review import correction_protection_reason
                row = store.conn.execute(
                    "SELECT t.source_hash,t.revision FROM transactions t JOIN import_batch_rows b USING(transaction_id) "
                    "WHERE b.batch_id=? AND t.transaction_id=?", (batch_id, transaction_id)).fetchone()
                if row is None or row[1] != revision:
                    raise ValueError("CORRECTION_STALE_OR_PROTECTED")
                if correction_protection_reason(store, transaction_id, row[0]) or store.conn.execute(
                        "SELECT 1 FROM ledger_entries WHERE transaction_id=? LIMIT 1", (transaction_id,)).fetchone():
                    raise ValueError("CORRECTION_STALE_OR_PROTECTED")
                store.conn.execute("INSERT INTO transaction_review_holds VALUES (?,?,?,?)",
                                   (transaction_id, row[0], "user_hold", "사용자가 잠정 여행 배정 검토를 보류함"))
                store.conn.execute("UPDATE transactions SET revision=revision+1 WHERE transaction_id=?", (transaction_id,))
                store.log_change("trip_review.held", transaction_id, {"revision": revision + 1, "source_hash": row[0]})
                result = {"status": "HELD", "transaction_id": transaction_id, "revision": revision + 1}
                store.remember_request(request_id, "trip_review_hold", digest, result)
            store.conn.execute("RELEASE SAVEPOINT trip_review_hold" if nested else "COMMIT")
            return result
        except BaseException:
            if nested:
                store.conn.execute("ROLLBACK TO SAVEPOINT trip_review_hold")
                store.conn.execute("RELEASE SAVEPOINT trip_review_hold")
            else:
                store.conn.rollback()
            raise
