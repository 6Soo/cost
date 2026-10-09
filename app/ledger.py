# -*- coding: utf-8 -*-
"""Preview what would be booked, then book it exactly once.

`preview` produces a digest over everything that would be written. `commit`
refuses unless that digest still matches, so a decision made after the preview
was looked at cannot slip into the ledger unseen.

`commit` is one `BEGIN IMMEDIATE`. Inside it: the preview is re-checked, each
ready row is inserted against `ledger_entries.transaction_id UNIQUE`, the request
result is recorded, the history is appended, and an optional projection to the
web app's `board_rows` is called. If any step fails, everything rolls back — so a
retry after a crash cannot leave two rows for one transaction, and a failure
half way cannot leave one.

Two rows that resolve to the same transaction are reported as a duplicate
possibility and held back rather than guessed at. Only a transaction the owner
confirmed reaches the ledger; a candidate and a review row book nothing.
"""

from __future__ import annotations

import hashlib

from .db import (CODE_INVALID_INPUT, CODE_NOT_FOUND, CODE_PREVIEW_STALE,
                 StoreError, canonical, utc_now)

__all__ = ["preview", "commit", "preview_digest", "recordable_rows"]


def recordable_rows(rows):
    """Unique transactions that can be newly booked from a preview."""
    return list({row['transaction_id']: row for row in rows
                 if not row.get('blocked') and not row.get('already_booked')}.values())


def _ready_rows(store, batch_id: str, review_from=None):
    return store.conn.execute(
        "SELECT transaction_id, source_hash, merchant, amount_krw,"
        " COALESCE(NULLIF(approval_date,''),posting_date), transaction_direction, item, description,"
        " display_tab_id, trip_id, revision, user_confirmed, classification_state,"
        " conflict_reason, parse_error FROM transactions WHERE classification_state!='preserved' AND transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)"
        " AND (? IS NULL OR COALESCE(NULLIF(approval_date,''),posting_date)=''"
        " OR COALESCE(NULLIF(approval_date,''),posting_date)>=?)"
        " ORDER BY transaction_id", (batch_id,review_from,review_from)).fetchall()


def _decision_rows(store, batch_id: str):
    """Latest decision per transaction, for the preview to reflect."""
    rows = store.conn.execute(
        "SELECT d.transaction_id, d.revision, d.item, d.description,"
        " d.display_tab_id, d.note FROM review_decisions d"
        " JOIN transactions t ON t.transaction_id = d.transaction_id"
        " WHERE t.transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?) AND d.revision ="
        " (SELECT MAX(revision) FROM review_decisions x"
        "  WHERE x.transaction_id = d.transaction_id)",
        (batch_id,)).fetchall()
    return {r[0]: {"revision": r[1], "item": r[2], "description": r[3],
                   "display_tab_id": r[4], "note": r[5]} for r in rows}


def preview(store, batch_id: str, *, trip_validator=None,
             tab_validator=None, review_from=None, entry_metadata=None) -> dict:
    """What a commit right now would do. Read only; writes nothing.

    `ready` is the count that would be booked. `unresolved` is held back, and
    `duplicates`/`conflicts` are the reasons a row is not in `ready`.

    When the caller supplies `trip_validator` or `tab_validator`, they run here
    *and again inside the commit transaction*. A schedule that has since been
    cancelled, or a tab that has since been closed, stops the row being booked
    rather than reaching the ledger on the strength of a decision made last week.

    `entry_metadata`, if given, is called with a copy of each row that would be
    booked and returns a dict; only `METADATA_KEYS` from it are merged in.
    """
    if entry_metadata is not None and not callable(entry_metadata):
        raise StoreError(CODE_INVALID_INPUT, "메타데이터 함수가 아니에요")
    found = store.conn.execute(
        "SELECT 1 FROM import_batches WHERE batch_id=?", (batch_id,)).fetchone()
    if found is None:
        raise StoreError(CODE_NOT_FOUND, "없는 접수 건이에요")

    decisions = _decision_rows(store, batch_id)
    from .review_holds import active_holds
    holds=active_holds(store.conn)
    rows: list[dict] = []
    ready: list[dict] = []
    unresolved: list[dict] = []
    duplicates: list[dict] = []
    conflicts: list[dict] = []

    for row in _ready_rows(store, batch_id, review_from):
        (transaction_id, source_hash, merchant, amount_krw, approval_date,
         direction, item, description, tab, trip_id, revision, user_confirmed,
         state, conflict_reason, parse_error) = row
        decision = decisions.get(transaction_id)
        entry = {
            "transaction_id": transaction_id, "source_hash": source_hash,
            "merchant": merchant, "amount_krw": amount_krw,
            "occurred_on": approval_date, "transaction_direction": direction,
            "item": (decision or {}).get("item", item) or "",
            "description": (decision or {}).get("description", description) or "",
            "display_tab_id": (decision or {}).get("display_tab_id", tab) or "",
            "trip_id": trip_id, "revision": revision,
            "user_confirmed": bool(user_confirmed), "classification_state": state,
            "already_booked": _already_booked(store, transaction_id),
        }
        if transaction_id in holds:
            entry['blocked']='review_hold'
            entry['review_hold']=holds[transaction_id]
            entry['reason']=holds[transaction_id]['reason']
            unresolved.append(entry)
            rows.append(entry)
            continue
        if conflict_reason:
            entry["blocked"] = "source_conflict"
            entry["reason"] = conflict_reason
            conflicts.append(entry)
            rows.append(entry)
            continue
        if parse_error:
            entry["blocked"] = "amount_unreadable"
            entry["reason"] = parse_error
            unresolved.append(entry)
            rows.append(entry)
            continue
        if amount_krw is None:
            entry["blocked"] = "amount_missing"
            entry["reason"] = "금액이 없어 장부에 쓸 수 없어요"
            unresolved.append(entry)
            rows.append(entry)
            continue
        if not approval_date or not merchant:
            entry['blocked'] = 'source_fields_missing'
            entry['reason'] = '원본의 거래일과 가맹점을 확인해 주세요'
            unresolved.append(entry)
            rows.append(entry)
            continue
        if not user_confirmed and state != 'classified':
            entry["blocked"] = "needs_review"
            entry["reason"] = "아직 확정하지 않아 장부에 기록하지 않아요"
            unresolved.append(entry)
            rows.append(entry)
            continue
        if not entry["item"]:
            entry["blocked"] = "item_missing"
            entry["reason"] = "항목이 비어 있어요"
            unresolved.append(entry)
            rows.append(entry)
            continue
        # Re-verify authority at the moment of the preview. A row whose trip or
        # tab the parent no longer accepts is held, not booked.
        blocked = _authority_block(entry, trip_validator, tab_validator)
        if blocked:
            entry["blocked"] = blocked[0]
            entry["reason"] = blocked[1]
            unresolved.append(entry)
            rows.append(entry)
            continue
        ready.append(entry)
        rows.append(entry)

    # Two ready rows that would land on the same transaction, or that share an
    # approval number with different content, are not guessed apart.
    seen: dict[str, dict] = {}
    for entry in ready:
        key = entry["transaction_id"]
        if key in seen:
            for other in (seen[key], entry):
                other["blocked"] = "duplicate_possible"
                other["reason"] = "같은 거래로 보이는 행이 여러 건이라 보류해요"
            for bucket in (ready,):
                if entry in bucket and entry not in duplicates:
                    duplicates.append(entry)
            continue
        seen[key] = entry

    ready_now = [e for e in ready if not e.get("blocked")]
    # Before the digest: only rows a commit would book, so provenance shows in
    # the preview and changes to it are a stale preview.
    _merge_metadata(ready_now, entry_metadata)
    result = {
        "batch_id": batch_id,
        "version": PREVIEW_VERSION,
        "ready": len(recordable_rows(rows)),
        "unresolved": len(unresolved),
        "duplicates": len(duplicates),
        "conflicts": len(conflicts),
        "rows": rows,
    }
    result["digest"] = preview_digest(result)
    return result


PREVIEW_VERSION = "ledger-preview-v2"

# The only keys a caller's entry_metadata may add. A fixed list, so a callback
# cannot inject `blocked`, `reason` or `now` and steer the commit.
METADATA_KEYS = ("booking_ref", "service_period", "ota_evidence")


def _merge_metadata(entries: list, entry_metadata) -> None:
    """Add the caller's OTA provenance to rows a commit would book."""
    if entry_metadata is None:
        return
    for entry in entries:
        metadata = entry_metadata(dict(entry)) or {}
        if not isinstance(metadata, dict):
            raise TypeError("entry_metadata 는 dict 를 돌려줘야 해요")
        for key in METADATA_KEYS:
            if key in metadata:
                entry[key] = metadata[key]


def _authority_block(entry: dict, trip_validator, tab_validator):
    """(blocked_code, reason) when the parent no longer accepts this row."""
    trip = str(entry.get("trip_id") or "")
    if trip:
        if trip_validator is None or not callable(trip_validator):
            return ("trip_unverified", "여행을 재검증할 함수가 필요해요")
        if not trip_validator(trip):
            return ("trip_no_longer_valid", "지금은 기록할 수 없는 여행이에요")
    tab = str(entry.get("display_tab_id") or "")
    if tab:
        if tab_validator is None or not callable(tab_validator):
            return ("tab_unverified", "항목 구분을 재검증할 함수가 필요해요")
        if not tab_validator(tab):
            return ("tab_no_longer_valid", "지금은 쓸 수 없는 항목 구분이에요")
    return None


def preview_digest(result: dict) -> str:
    """A digest over exactly what a commit would write.

    Version, batch, and the identity, source text, amount, date and
    classification of every ready row, plus the OTA provenance attached to it.
    A decision taken after the preview was read changes the row, so it changes
    the digest, so the stale commit is refused. Provenance counts as part of the
    row: a booking reference, service period or `ota_evidence` that now reads
    differently — including a different digest inside it — is stale too.
    """
    body = {
        "version": result.get("version"),
        "batch_id": result.get("batch_id"),
        "ready": [
            {"transaction_id": r["transaction_id"],
             "source_hash": r["source_hash"],
             "amount_krw": r["amount_krw"],
             "occurred_on": r["occurred_on"],
             "item": r["item"], "description": r["description"],
             "display_tab_id": r["display_tab_id"], "trip_id": r["trip_id"],
             "booking_ref": r.get("booking_ref"),
             "service_period": r.get("service_period"),
             "ota_evidence": r.get("ota_evidence")}
            for r in result.get("rows", [])
            if not r.get("blocked")
        ],
    }
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _already_booked(store, transaction_id: str) -> bool:
    return store.conn.execute(
        "SELECT 1 FROM ledger_entries WHERE transaction_id=?",
        (transaction_id,)).fetchone() is not None


def commit(store, batch_id: str, preview_digest_value: str, request_id: str,
           *, projection=None, trip_validator=None, tab_validator=None,review_from=None,
           entry_metadata=None) -> dict:
    """Book the previewed rows, exactly once, atomically.

    `projection` is called inside the same transaction for each booked row, so a
    caller that also publishes to the web app's `board_rows` gets the two writes
    in one transaction or neither. It is called with the row dict and must do
    its own write through `store.conn`; anything it raises rolls the whole
    commit back.

    The trip and tab validators are called again *inside* the transaction, and
    a row that no longer passes is reported as unresolved rather than booked. A
    decision taken against a schedule that has since been cancelled must not
    reach the ledger.

    `entry_metadata` is the same callback the caller previewed with, so the
    digest is recalculated over the same provenance and the entry handed to
    `projection` is the one that was digested. It is not part of the idempotency
    key: the digest already covers what it contributes.
    """
    if not request_id or not isinstance(request_id, str):
        raise StoreError(CODE_INVALID_INPUT, "요청 ID가 필요해요")
    if not preview_digest_value or not isinstance(preview_digest_value, str):
        raise StoreError(CODE_INVALID_INPUT, "미리보기 값이 필요해요")

    payload_sha = hashlib.sha256(canonical(
        {"batch_id": batch_id, "digest": preview_digest_value}).encode("utf-8")
    ).hexdigest()
    replay = store.replay_request(request_id, "commit", payload_sha)
    if replay is not None:
        return replay

    current = preview(store, batch_id, trip_validator=trip_validator,
                      tab_validator=tab_validator,review_from=review_from,
                      entry_metadata=entry_metadata)
    if current["digest"] != preview_digest_value:
        raise StoreError(CODE_PREVIEW_STALE,
                         "미리보기 이후에 답변이 달라졌어요. 다시 확인해 주세요")

    booked: list[str] = []
    already: list[str] = []
    lost_authority: list[str] = []
    now = utc_now()
    with store.lock:
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            for entry in current["rows"]:
                if entry.get("blocked"):
                    continue
                transaction_id = entry["transaction_id"]
                # Re-checked here, not only above: this is the last point before
                # the money moves.
                block = _authority_block(entry, trip_validator, tab_validator)
                if block:
                    lost_authority.append(transaction_id)
                    store.log_change("ledger.blocked", transaction_id,
                                     {"batch_id": batch_id, "reason": block[1]})
                    continue
                if _already_booked(store, transaction_id):
                    already.append(transaction_id)
                    continue
                store.conn.execute(
                    "INSERT INTO ledger_entries(transaction_id, batch_id, item,"
                    " description, display_tab_id, trip_id, amount_krw, merchant,"
                    " occurred_on, transaction_direction, source_hash,"
                    " committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (transaction_id, batch_id, entry["item"], entry["description"],
                     entry["display_tab_id"], entry.get("trip_id", ""),
                     entry["amount_krw"], entry["merchant"], entry["occurred_on"],
                     entry["transaction_direction"], entry["source_hash"], now))
                booked.append(transaction_id)
                store.conn.execute("UPDATE transactions SET user_confirmed=1,classification_state='confirmed' "
                                   "WHERE transaction_id=?", (transaction_id,))
                store.log_change("ledger.booked", transaction_id,
                                 {"batch_id": batch_id, "item": entry["item"],
                                  "amount_krw": entry["amount_krw"],
                                  "source_hash": entry["source_hash"]})
                if projection is not None:
                    if not callable(projection):
                        raise StoreError(CODE_INVALID_INPUT,
                                         "게시 함수가 아니에요")
                    projection(dict(entry, batch_id=batch_id, now=now))
            result = {"batch_id": batch_id, "applied": len(booked),
                      "already": len(already), "unresolved": current["unresolved"],
                      "duplicates": current["duplicates"],
                      "conflicts": current["conflicts"],
                      "lost_authority": lost_authority,
                      "booked": booked, "already_booked": already,
                      "digest": preview_digest_value, "committed_at": now}
            store.remember_request(request_id, "commit", payload_sha, result)
            store.conn.execute("COMMIT")
        except Exception:
            store.conn.execute("ROLLBACK")
            raise
    return result
