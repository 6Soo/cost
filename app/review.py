# -*- coding: utf-8 -*-
"""Receive an upload, and record what the owner decides about a transaction.

`receive` is idempotent on content, not on filename. The same bytes uploaded
again return the batch that already exists, with its existing result. The same
transactions arriving inside a *differently named* file are matched on their
identity and their source text, and are not written a second time.

Identity and content are kept apart:

* `transaction_id` says *which* transaction this is, from the issuer, the card,
  the kind, the source approval date and the approval number.
* `source_hash` says *what the source said*, from the original cells.

So editing a memo, a classification or a trip changes neither, and the same
transaction whose amount or merchant changed in a later statement is a
**conflict** rather than an update — because the two statements cannot both be
right about the same approval number.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from .db import (CODE_INVALID_INPUT, CODE_NOT_FOUND, CODE_REVISION_CONFLICT,
                 CODE_SOURCE_CONFLICT, StoreError, canonical, utc_now)
from .import_card import ParseError, ParsedRow, parse_card_file
from .normalize import normalize_merchant

__all__ = ["receive", "get_batch", "save_decision", "transaction_identity",
           "source_hash_of", "content_key"]

# No built-in list of tabs. The web app owns the real trips — there are far more
# of them than a hardcoded list could ever hold, and a guess would silently
# narrow where a cost can be booked. A `display_tab_id` is accepted only when the
# caller supplies `tab_validator`, and an unassigned cost may use a
# quarantine/accounting-period tab the caller also validates explicitly.
#
# `item` (식비, 숙박, 교통) is a *category* and is deliberately a different field
# from `display_tab_id`, which is a trip or an accounting bucket. Setting one
# never sets the other.
_CANCEL_KINDS = ("취소", "매입취소", "부분취소", "cancel", "refund")


def _sha256(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def transaction_identity(row: ParsedRow, occurrence: int | None = None) -> str:
    """A stable id for the transaction, from what the issuer states.

    Approval number alone is not enough: two cards can share one, and so can a
    cancellation and its original. Issuer, card, kind and the source approval
    date are in the key, and a cancellation points at the approval it cancels,
    so the link survives without overloading the number.
    """
    parts = [
        row.issuer or "",
        row.card_tail or "",
        row.transaction_direction or "",
        row.transaction_kind or "",
        row.approval_date or row.posting_date or "",
        row.approval_number or "",
        row.original_approval_number or "",
    ]
    if not row.approval_number and not row.original_approval_number:
        # No approval number at all. Then the identity has to come from the
        # row's own content plus a discriminator, so two real transactions that
        # happen to share a date, merchant and amount stay two rows.
        # `occurrence` is the n-th identical row inside one file. It replaces the file row
        # number, so the same economic transaction gets the same id from any file.
        parts.extend([
            row.merchant_normalized,
            "" if row.amount_krw is None else str(row.amount_krw),
            str(row.row_index) if occurrence is None else "#%d" % occurrence,
        ])
        if occurrence is not None:
            parts.extend([row.posting_date or "", row.foreign_currency or "",
                          _plain_number(row.foreign_amount)])
    return _sha256("\x1f".join(parts))


def _plain_number(value) -> str:
    """`5400.0` and `5400` are one amount. Anything that is not a number is kept as text."""
    text = str(value or "").strip().replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if not number.is_finite():
        return text
    normalized = format(number.normalize(), "f")
    return "0" if normalized in ("-0", "") else normalized


def content_key(row: ParsedRow) -> tuple:
    """What a source row says about the economic event, without any file position.

    Used for rows that carry no approval number (overseas acquisitions), so the same
    payment seen in two files is one transaction while two real payments stay two.
    """
    return (row.issuer or "", row.card_tail or "", row.transaction_direction or "",
            row.transaction_kind or "", row.posting_date or "", row.approval_date or "",
            row.merchant_normalized, "" if row.amount_krw is None else str(row.amount_krw),
            row.foreign_currency or "", _plain_number(row.foreign_amount))


def source_hash_of(row: ParsedRow) -> str:
    """What the source said, and only that.

    Deliberately excludes anything a human later types: a memo, a
    classification, a trip. Those live in their own columns, so re-importing the
    same statement does not look like a change to the source.
    """
    return _sha256(canonical({
        "issuer": row.issuer,
        "card_tail": row.card_tail,
        "direction": row.transaction_direction,
        "kind": row.transaction_kind,
        "approval_number": row.approval_number,
        "original_approval_number": row.original_approval_number,
        "approval_date": row.approval_date,
        "posting_date": row.posting_date,
        "merchant": row.merchant,
        "amount_krw": row.amount_krw,
        "foreign_amount": row.foreign_amount,
        "foreign_currency": row.foreign_currency,
    }))


def _kind_is_cancel(kind: str) -> bool:
    return any(word in str(kind or "").casefold() for word in _CANCEL_KINDS)


# ------------------------------------------------------------------ receive

def receive(store, content: bytes, filename: str) -> dict:
    """Take one upload. Idempotent on content.

    Returns the batch. Re-uploading identical bytes returns the same batch with
    the same rows, not a second copy.
    """
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise StoreError(CODE_INVALID_INPUT, "업로드 내용이 필요해요")
    if not filename or not str(filename).strip():
        raise StoreError(CODE_INVALID_INPUT, "파일 이름이 필요해요")
    content = bytes(content)
    content_sha = _sha256(content)
    batch_id = "batch-" + content_sha[:24]

    with store.lock:
        existing = store.conn.execute(
            "SELECT batch_id, filename, content_sha256, parser, received_at,"
            " row_count, error_count, status FROM import_batches"
            " WHERE content_sha256=?", (content_sha,)).fetchone()
        if existing is not None:
            # Same bytes, already received: return the result that exists.
            return {"batch_id": existing[0], "filename": existing[1],
                    "content_sha256": existing[2], "reused": True,
                    "parser": existing[3], "received_at": existing[4],
                    "row_count": existing[5], "error_count": existing[6],
                    "status": existing[7]}

    try:
        parsed = parse_card_file(content, filename)
    except ParseError as exc:
        with store.lock:
            store.conn.execute(
                "INSERT OR REPLACE INTO import_batches(batch_id, filename,"
                " content_sha256, content_bytes, byte_size, parser, received_at,"
                " row_count, error_count, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (batch_id, filename, content_sha, content, len(content),
                 "failed:" + exc.code, utc_now(), 0, 0, "rejected"))
            store.log_change("batch.rejected", batch_id,
                             {"code": exc.code, "message": exc.message})
        raise StoreError(exc.code, exc.message) from None

    received_at = utc_now()
    stored = _persist(store, batch_id, filename, content_sha, content, parsed,
                      received_at)
    stored["reused"] = False
    return stored


def _persist(store, batch_id, filename, content_sha, content, parsed, received_at):
    """Insert the batch and its transactions, atomically."""
    if getattr(parsed, "channel", "") == "approval":
        return _persist_approvals(store, batch_id, filename, content_sha, content, parsed, received_at)
    now = received_at
    inserted = 0
    reused = 0
    matched = 0
    conflicts = 0
    unresolved = 0
    with store.lock:
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            store.conn.execute(
                "INSERT OR REPLACE INTO import_batches(batch_id, filename,"
                " content_sha256, content_bytes, byte_size, parser, received_at,"
                " parsed_at, row_count, error_count, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, filename, content_sha, content, len(content),
                 parsed.parser, now, now, len(parsed.rows), len(parsed.issues),
                 "parsed"))
            plan = _keyless_plan(store, batch_id, parsed.rows)
            occurrences = {}
            for row in parsed.rows:
                keyless = plan.get(row.row_index)
                if keyless is not None and keyless["matched"]:
                    # The same payment is already recorded: link this file's row to it.
                    outcome, identity = "reused", keyless["matched"]
                    matched += 1
                else:
                    forced = keyless["identity"] if keyless is not None else None
                    if forced is None and not row.approval_number and not row.original_approval_number:
                        key = content_key(row)
                        occurrence = occurrences.get(key, 0)
                        occurrences[key] = occurrence + 1
                        forced = transaction_identity(row, occurrence)
                    outcome = _insert_row(store, batch_id, row, now, forced)
                    identity = forced or transaction_identity(row)
                if outcome == 'conflict':
                    identity = _conflict_id(identity, row.row_index, batch_id)
                store.conn.execute('INSERT OR IGNORE INTO import_batch_rows VALUES (?,?,?)',
                                   (batch_id,identity,row.row_index))
                if outcome == "inserted":
                    inserted += 1
                elif outcome == "reused":
                    reused += 1
                elif outcome == "conflict":
                    conflicts += 1
                if row.parse_error:
                    unresolved += 1
            store.conn.execute(
                "UPDATE import_batches SET row_count=?, error_count=?,"
                " status='parsed' WHERE batch_id=?",
                (inserted + reused + conflicts, len(parsed.issues), batch_id))
            store.log_change("batch.received", batch_id,
                             {"inserted": inserted, "reused": reused, "matched_by_content": matched,
                              "conflicts": conflicts, "issues": len(parsed.issues),
                              "channel": getattr(parsed, "channel", "")})
            store.conn.execute("COMMIT")
        except Exception:
            store.conn.execute("ROLLBACK")
            raise
    _reconcile_after_receive(store)
    return {"batch_id": batch_id, "filename": filename, "content_sha256": content_sha,
            "parser": parsed.parser, "received_at": now, "reused": False,
            "channel": getattr(parsed, "channel", ""),
            "inserted": inserted, "already_present": reused,
            "matched_by_content": matched,
            "conflicts": conflicts, "unresolved": unresolved,
            "row_count": inserted + reused + conflicts,
            "issues": parsed.issues}


def _keyless_plan(store, batch_id: str, rows) -> dict:
    """Decide, for rows without an approval number, which are already recorded.

    Multiset matching on `content_key`: a file with n identical rows against m identical
    transactions already recorded adds max(0, n - m). Rows are never paired by position,
    so two real payments of the same amount on the same day stay two, and the same
    payment arriving in another file is not a second one.
    """
    eligible = [row for row in rows
                if not row.approval_number and not row.original_approval_number
                and not row.parse_error and row.amount_krw is not None]
    if not eligible:
        return {}
    exact: dict[tuple, list[str]] = {}
    undated: dict[tuple, list[str]] = {}
    sql = ("SELECT transaction_id, issuer, card_tail, transaction_direction, transaction_kind, posting_date,"
           " approval_date, merchant_normalized, amount_krw, foreign_currency, foreign_amount"
           " FROM transactions WHERE approval_number='' AND original_approval_number=''"
           " AND parse_error='' AND amount_krw IS NOT NULL AND transaction_id NOT LIKE '%:conflict:%'"
           " AND issuer IN ({marks}) ORDER BY created_at, transaction_id")
    issuers = sorted({row.issuer or "" for row in eligible})
    for record in store.conn.execute(sql.format(marks=",".join("?" * len(issuers))), issuers):
        key = (record[1], record[2], record[3], record[4], record[5], record[6], record[7],
               str(record[8]), record[9], _plain_number(record[10]))
        exact.setdefault(key, []).append(record[0])
        if not record[6]:
            undated.setdefault(key[:5] + key[6:], []).append(record[0])
    used: set[str] = set()
    seen: dict[tuple, int] = {}
    plan: dict[int, dict] = {}
    for row in eligible:
        key = content_key(row)
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        pool = list(exact.get(key, ()))
        if row.approval_date:
            pool += undated.get(key[:5] + key[6:], [])
        found = next((candidate for candidate in pool if candidate not in used), None)
        if found is not None:
            used.add(found)
        plan[row.row_index] = {"matched": found,
                               "identity": transaction_identity(row, occurrence)}
    return plan


def _insert_row(store, batch_id: str, row: ParsedRow, now: str,
                transaction_id: str | None = None) -> str:
    """One transaction. Returns inserted / reused / conflict.

    A transaction already known with the same source text is left exactly as it
    is — including any classification and any decision — and only counted. A
    transaction already known with *different* source text is recorded as a
    conflict on the incoming row, never as an overwrite.
    """
    transaction_id = transaction_id or transaction_identity(row)
    source_hash = source_hash_of(row)
    found = store.conn.execute(
        "SELECT source_hash, row_index FROM transactions WHERE transaction_id=?",
        (transaction_id,)).fetchone()
    if found is not None:
        if found[0] == source_hash:
            return "reused"
        store.conn.execute(
            "INSERT INTO transactions(transaction_id, source_hash, batch_id,"
            " issuer, card_tail, card_kind, transaction_direction,"
            " transaction_kind, approval_number, original_approval_number,"
            " approval_date, posting_date, merchant, merchant_normalized,"
            " amount_krw, foreign_amount, foreign_currency, description_raw,"
            " row_index, raw_row_json, conflict_reason, parse_error,"
            " classification_state, classification_source, classification_basis,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_conflict_id(transaction_id, row.row_index, batch_id), source_hash, batch_id,
             row.issuer, row.card_tail, row.card_kind, row.transaction_direction,
             row.transaction_kind, row.approval_number,
             row.original_approval_number, row.approval_date, row.posting_date,
             row.merchant, row.merchant_normalized, row.amount_krw,
             row.foreign_amount, row.foreign_currency, row.description_raw,
             row.row_index, canonical(row.raw), "같은 거래 ID인데 원문 금액·가맹점이 달라요",
             row.parse_error, "needs_review", "source_conflict",
             "원문과 이미 기록한 내용이 달라 확인이 필요해요", now))
        store.log_change("transaction.conflict", transaction_id,
                         {"batch_id": batch_id, "row_index": row.row_index})
        return "conflict"

    # 승인번호 없는 행이 다른 파일의 같은 금액·날짜 거래와 가맹점 표기만 다르면, 같은 결제인지
    # 증명할 수 없으므로 확인 대상으로 둔다. 완전히 같은 행은 위의 다중집합 대사가 이미 처리했다.
    drift = not row.approval_number and row.amount_krw is not None and store.conn.execute(
        "SELECT 1 FROM transactions WHERE batch_id<>? AND issuer=? AND card_tail=? AND transaction_direction=?"
        " AND posting_date=? AND approval_date=? AND amount_krw=? AND foreign_currency=?"
        " AND merchant_normalized<>? AND approval_number='' LIMIT 1",
        (batch_id, row.issuer, row.card_tail, row.transaction_direction, row.posting_date,
         row.approval_date, row.amount_krw, row.foreign_currency, row.merchant_normalized)).fetchone()
    store.conn.execute(
        "INSERT INTO transactions(transaction_id, source_hash, batch_id, issuer,"
        " card_tail, card_kind, transaction_direction, transaction_kind,"
        " approval_number, original_approval_number, approval_date, posting_date,"
        " merchant, merchant_normalized, amount_krw, foreign_amount,"
        " foreign_currency, description_raw, row_index, raw_row_json, parse_error,"
        " classification_state, classification_basis, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (transaction_id, source_hash, batch_id, row.issuer, row.card_tail,
         row.card_kind, row.transaction_direction, row.transaction_kind,
         row.approval_number, row.original_approval_number, row.approval_date,
         row.posting_date, row.merchant, row.merchant_normalized, row.amount_krw,
         row.foreign_amount, row.foreign_currency, row.description_raw,
         row.row_index, canonical(row.raw), row.parse_error,
         "needs_review", "아직 분류하지 않았어요", now))
    if drift:
        store.conn.execute("UPDATE transactions SET conflict_reason=? WHERE transaction_id=?",
                           ("다른 파일에 금액·날짜가 같고 가맹점 표기만 다른 거래가 있습니다. 같은 결제인지 확인이 필요합니다",
                            transaction_id))
    return "inserted"


def _persist_approvals(store, batch_id, filename, content_sha, content, parsed, received_at):
    """Approval lists are evidence of an event, not an accounting amount.

    They are stored apart from `transactions`, so an approval can never become a second
    cost. Linking to the acquired transaction is recomputed from the stored sets
    (`source_links.reconcile`), which keeps the result independent of upload order.
    """
    now = received_at
    stored = 0
    known = 0
    conflicts = 0
    with store.lock:
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            store.conn.execute(
                "INSERT OR REPLACE INTO import_batches(batch_id, filename,"
                " content_sha256, content_bytes, byte_size, parser, received_at,"
                " parsed_at, row_count, error_count, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, filename, content_sha, content, len(content),
                 parsed.parser, now, now, len(parsed.rows), len(parsed.issues), "approval_evidence"))
            for row in parsed.rows:
                if row.parse_error:
                    continue
                key = _sha256("\x1f".join([row.issuer, row.card_tail, row.transaction_direction,
                                           row.approval_number, row.approval_date]))
                source_hash = source_hash_of(row)
                present = store.conn.execute(
                    "SELECT source_hash FROM approval_evidence WHERE approval_key=?", (key,)).fetchone()
                if present is None:
                    store.conn.execute(
                        "INSERT INTO approval_evidence(approval_key, source_hash, batch_id, row_index, issuer,"
                        " card_tail, card_kind, transaction_direction, approval_number, approval_date,"
                        " approval_time, merchant, amount_krw, foreign_amount, foreign_currency,"
                        " approval_method, raw_row_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (key, source_hash, batch_id, row.row_index, row.issuer, row.card_tail, row.card_kind,
                         row.transaction_direction, row.approval_number, row.approval_date,
                         row.raw.get("_approval_time", ""), row.merchant, row.amount_krw,
                         row.foreign_amount, row.foreign_currency, row.raw.get("_approval_method", ""),
                         canonical(row.raw), now))
                    stored += 1
                elif present[0] == source_hash:
                    known += 1
                else:
                    store.conn.execute(
                        "UPDATE approval_evidence SET conflict_reason=? WHERE approval_key=?",
                        ("같은 승인번호인데 다른 파일의 금액·가맹점이 달라요", key))
                    conflicts += 1
                store.conn.execute("INSERT OR IGNORE INTO approval_batch_rows VALUES (?,?,?)",
                                   (batch_id, key, row.row_index))
            store.conn.execute(
                "UPDATE import_batches SET row_count=?, error_count=?, status='approval_evidence'"
                " WHERE batch_id=?", (stored + known + conflicts, len(parsed.issues), batch_id))
            store.log_change("batch.received", batch_id,
                             {"channel": "approval", "stored": stored, "known": known,
                              "conflicts": conflicts, "issues": len(parsed.issues)})
            store.conn.execute("COMMIT")
        except Exception:
            store.conn.execute("ROLLBACK")
            raise
    summary = _reconcile_after_receive(store)
    return {"batch_id": batch_id, "filename": filename, "content_sha256": content_sha,
            "parser": parsed.parser, "received_at": now, "reused": False, "channel": "approval",
            "inserted": 0, "already_present": known, "approval_stored": stored,
            "conflicts": conflicts, "unresolved": len(parsed.issues),
            "row_count": stored + known + conflicts, "issues": parsed.issues,
            "approval_summary": summary}


def _reconcile_after_receive(store):
    from . import source_links
    return source_links.reconcile(store)


def _conflict_id(transaction_id: str, row_index: int, batch_id: str) -> str:
    """A distinct id for the conflicting copy, so the original stays intact."""
    return transaction_id + ":conflict:" + batch_id + ':' + str(row_index)


# --------------------------------------------------------------- get_batch

def get_batch(store, batch_id: str) -> dict:
    """One batch's summary and rows, with the original cells attached."""
    found = store.conn.execute(
        "SELECT filename, content_sha256, byte_size, parser, received_at,"
        " parsed_at, row_count, error_count, status FROM import_batches"
        " WHERE batch_id=?", (batch_id,)).fetchone()
    if found is None:
        raise StoreError(CODE_NOT_FOUND, "없는 접수 건이에요")
    rows = store.conn.execute(
        "SELECT transaction_id, source_hash, issuer, card_tail, card_kind,"
        " transaction_direction, transaction_kind, approval_number,"
        " original_approval_number, approval_date, posting_date, merchant,"
        " merchant_normalized, amount_krw, foreign_amount, foreign_currency,"
        " description_raw, row_index, raw_row_json, duplicate_of, conflict_reason,"
        " parse_error, classification_state, classification_source,"
        " classification_basis, item, description, display_tab_id, trip_id,"
        " revision, user_confirmed, decided_at FROM transactions"
        " WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?) ORDER BY row_index", (batch_id,)).fetchall()
    summary = {
        "batch_id": batch_id, "filename": found[0], "content_sha256": found[1],
        "byte_size": found[2], "parser": found[3], "received_at": found[4],
        "parsed_at": found[5], "row_count": found[6], "error_count": found[7],
        "status": found[8],
        "counts": _counts(store, batch_id),
    }
    return {"batch_id": batch_id, "summary": summary,
            "rows": [_row_dict(r) for r in rows]}


def _row_dict(r) -> dict:
    return {
        "transaction_id": r[0], "source_hash": r[1], "issuer": r[2],
        "card_tail": r[3], "card_kind": r[4], "transaction_direction": r[5],
        "transaction_kind": r[6], "approval_number": r[7],
        "original_approval_number": r[8], "approval_date": r[9],
        "posting_date": r[10], "merchant": r[11], "merchant_normalized": r[12],
        "amount_krw": r[13], "foreign_amount": r[14], "foreign_currency": r[15],
        "description_raw": r[16], "row_index": r[17], "raw_row": json.loads(r[18]),
        "duplicate_of": r[19], "conflict_reason": r[20], "parse_error": r[21],
        "classification_state": r[22], "classification_source": r[23],
        "classification_basis": r[24], "item": r[25], "description": r[26],
        "display_tab_id": r[27], "trip_id": r[28], "revision": r[29],
        "user_confirmed": bool(r[30]), "decided_at": r[31],
    }


def _counts(store, batch_id: str) -> dict:
    rows = store.conn.execute(
        "SELECT classification_state, COUNT(*) FROM transactions"
        " WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?) GROUP BY classification_state", (batch_id,)).fetchall()
    counts = {state: 0 for state in ("needs_review", "classified", "confirmed")}
    counts.update({r[0]: r[1] for r in rows})
    counts["total"] = sum(r[1] for r in rows)
    return counts


# ------------------------------------------------------------ save_decision

def save_decision(store, transaction_id: str, expected_revision: int, *,
                   item: str, description: str = "", display_tab_id: str = "",
                   note: str = "", reuse_rule: bool = False,
                   request_id: str = "", trip_id: str = "",
                   trip_validator=None, tab_validator=None,
                   trip_candidates=None, resolve_hold=False, _batch: bool = False) -> dict:
    """Record the owner's answer for one transaction.

    `expected_revision` is an optimistic lock: the revision the owner was
    looking at. A stale one is refused rather than merged, because there is no
    way to merge two answers to one question.

    Nothing is booked here. A trip and a tab are only *recorded*, and only after
    the caller's own validators accept them: `trip_validator` for a trip id, and
    `tab_validator` for any tab including an unassigned quarantine or
    accounting-period one. Candidate trips and candidate rows never book and
    never confirm anything, so `trip_candidates` is accepted and deliberately
    not consulted.
    """
    if not transaction_id or not isinstance(transaction_id, str):
        raise StoreError(CODE_INVALID_INPUT, "거래 ID가 필요해요")
    if not request_id or not isinstance(request_id, str):
        raise StoreError(CODE_INVALID_INPUT, "요청 ID가 필요해요")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise StoreError(CODE_INVALID_INPUT, "기대 버전 형식이 달라요")
    item = str(item or "").strip()
    description = str(description or "").strip()
    note = str(note or "").strip()
    tab = str(display_tab_id or "").strip()
    if not item and not description:
        raise StoreError(CODE_INVALID_INPUT, "항목이나 내용을 입력해 주세요")
    if len(item) > 60:
        raise StoreError(CODE_INVALID_INPUT, "항목이 너무 길어요")
    if len(description) > 200:
        raise StoreError(CODE_INVALID_INPUT, "내용이 너무 길어요")
    if len(note) > 2000:
        raise StoreError(CODE_INVALID_INPUT, "메모가 너무 길어요")

    trip = str(trip_id or "").strip()
    if trip:
        if trip_validator is None or not callable(trip_validator):
            raise StoreError(CODE_INVALID_INPUT,
                             "여행을 정하려면 검증 함수가 필요해요")
        if not trip_validator(trip):
            raise StoreError(CODE_INVALID_INPUT,
                             "부모가 검증하지 않은 여행이에요")
    if tab:
        if tab_validator is None or not callable(tab_validator):
            raise StoreError(CODE_INVALID_INPUT,
                             "항목 구분을 정하려면 검증 함수가 필요해요")
        if not tab_validator(tab):
            raise StoreError(CODE_INVALID_INPUT,
                             "부모가 검증하지 않은 항목 구분이에요")
    if trip_candidates:
        # A candidate list is a suggestion to show. It books nothing and it
        # confirms nothing, so it is deliberately not consulted here.
        pass

    payload = {
        "transaction_id": transaction_id, "revision": expected_revision,
        "item": item, "description": description, "display_tab_id": tab,
        "note": note, "reuse_rule": bool(reuse_rule), "trip_id": trip,
    }
    if resolve_hold:
        payload['resolve_hold']=True
    payload_sha = _sha256(canonical(payload))
    replay = store.replay_request(request_id, "save_decision", payload_sha)
    if replay is not None:
        return replay

    with store.lock:
        found = store.conn.execute(
            "SELECT revision, user_confirmed, source_hash FROM transactions"
            " WHERE transaction_id=?", (transaction_id,)).fetchone()
        if found is None:
            raise StoreError(CODE_NOT_FOUND, "없는 거래예요")
        if int(found[0]) != int(expected_revision):
            raise StoreError(CODE_REVISION_CONFLICT,
                             "다른 곳에서 먼저 고쳤어요. 새로고침해 주세요")
        revision = int(found[0]) + 1
        now = utc_now()
        # A batch owns the transaction; a single save opens and closes its own.
        if not _batch:
            store.conn.execute("BEGIN IMMEDIATE")
        try:
            repeated = store.replay_request(request_id, 'save_decision', payload_sha)
            if repeated is not None:
                if not _batch:
                    store.conn.commit()
                return repeated
            current = store.conn.execute('SELECT revision FROM transactions WHERE transaction_id=?',
                                         (transaction_id,)).fetchone()
            if current[0] != expected_revision:
                raise StoreError(CODE_REVISION_CONFLICT, '다른 곳에서 먼저 고쳤습니다. 다시 불러와 주세요')
            store.conn.execute(
                "INSERT INTO review_decisions(transaction_id, revision, item,"
                " description, display_tab_id, note, reuse_rule, decided_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (transaction_id, revision, item, description, tab, note,
                 int(bool(reuse_rule)), now))
            # The source columns are not touched here, and cannot be: this
            # statement names item, description, tab, trip, revision and the
            # confirmation flag only.
            store.conn.execute(
                "UPDATE transactions SET item=?, description=?, display_tab_id=?,"
                " trip_id=?, classification_state='confirmed',"
                " classification_source='user_decision',"
                " classification_basis='확정한 답변', user_confirmed=1,"
                " revision=?, decided_at=? WHERE transaction_id=?",
                (item, description, tab, trip, revision, now, transaction_id))
            store.log_change("transaction.decided", transaction_id,
                             {"revision": revision, "source_hash": found[2],
                              "item": item, "trip_id": trip})
            if resolve_hold:
                store.conn.execute('DELETE FROM transaction_review_holds WHERE transaction_id=? AND source_hash=?',
                                   (transaction_id,found[2]))
            result = {"transaction_id": transaction_id, "revision": revision,
                      "item": item, "description": description,
                      "display_tab_id": tab, "trip_id": trip, "note": note,
                      "user_confirmed": True, "decided_at": now,
                      "source_hash": found[2]}
            if reuse_rule:
                result['rule'] = _register_reuse_rule(store, transaction_id)
            store.remember_request(request_id, "save_decision", payload_sha, result)
            if not _batch:
                store.conn.execute("COMMIT")
        except Exception:
            if not _batch:
                store.conn.execute("ROLLBACK")
            raise

    return result


def batch_result_for(store, request_id: str):
    """The stored result of an earlier batch with this request id, or None."""
    row = store.conn.execute(
        "SELECT response_json FROM requests WHERE request_id=? AND scope='save_decisions'",
        (request_id,)).fetchone()
    if row is None:
        return None
    import json
    return json.loads(row[0])


def save_decisions_atomic(store, decisions: list, *, request_id: str, tab_validator=None,
                          trip_validator=None, basis: str = "") -> dict:
    """All or nothing. Every answer gets the same checks as save_decision, and one failure rolls back every write.

    A repeated request id returns the first result and writes nothing. Each decision may carry
    `expected_amount_krw`; a changed amount or an already confirmed row refuses the whole batch.
    """
    if not request_id or not isinstance(request_id, str):
        raise StoreError(CODE_INVALID_INPUT, "요청 ID가 필요해요")
    if not decisions:
        raise StoreError(CODE_INVALID_INPUT, "적용할 답변이 없어요")
    payload_sha = _sha256(canonical({"basis": basis, "decisions": decisions}))
    replay = store.replay_request(request_id, "save_decisions", payload_sha)
    if replay is not None:
        return replay
    with store.lock:
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            # Another connection can commit while this request waits for SQLite's writer lock.
            replay = store.replay_request(request_id, "save_decisions", payload_sha)
            if replay is not None:
                store.conn.execute("COMMIT")
                return replay
            results = []
            for decision in decisions:
                args = dict(decision)
                transaction_id = args.pop("transaction_id")
                revision = args.pop("revision")
                expected_amount = args.pop("expected_amount_krw", None)
                found = store.conn.execute(
                    "SELECT revision, user_confirmed, amount_krw FROM transactions WHERE transaction_id=?",
                    (transaction_id,)).fetchone()
                if found is None:
                    raise StoreError(CODE_NOT_FOUND, "없는 거래예요")
                if int(found[0]) != int(revision):
                    raise StoreError(CODE_REVISION_CONFLICT, "다른 곳에서 먼저 고쳤어요. 새로고침해 주세요")
                if found[1]:
                    raise StoreError(CODE_REVISION_CONFLICT, "이미 확정한 거래라 일괄 적용하지 않았어요")
                if expected_amount is not None and found[2] != expected_amount:
                    raise StoreError(CODE_REVISION_CONFLICT, "금액이 바뀌어 일괄 적용하지 않았어요")
                results.append(save_decision(
                    store, transaction_id, revision, request_id=f"{request_id}:{transaction_id}",
                    trip_validator=trip_validator, tab_validator=tab_validator, _batch=True, **args))
            response = {"results": results, "basis": basis}
            store.remember_request(request_id, "save_decisions", payload_sha, response)
            store.conn.execute("COMMIT")
        except Exception:
            store.conn.execute("ROLLBACK")
            raise
    return response


def _register_reuse_rule(store, transaction_id: str):
    """Turn one decision into a rule, but only because the owner asked.

    Reuse is never automatic: no flag, no guess, no rule written by
    `classify_batch`. If the merchant is missing there is nothing to key on, and
    the caller is told rather than given a rule that would match everything.
    """
    row = store.conn.execute(
        "SELECT merchant_normalized, card_kind, transaction_direction, item,"
        " description, display_tab_id FROM transactions WHERE transaction_id=?",
        (transaction_id,)).fetchone()
    if row is None or not row[0]:
        return {"created": False, "reason": "가맹점이 없어 규칙을 만들 수 없어요"}
    from .rules import build_rule_from_decision, save_rule
    draft = build_rule_from_decision(
        merchant=row[0], card_kind=row[1] or "",
        transaction_direction=row[2] or "", item=row[3] or "",
        description=row[4] or "", display_tab_id="",
        note="확정한 답변에서 만든 규칙")
    return {"created": True, **save_rule(store, draft)}
