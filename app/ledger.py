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
possibility and held back rather than guessed at. Only a classified transaction
reaches the ledger; a candidate and a review row book nothing.
"""

from __future__ import annotations

import hashlib

from .db import (CODE_INVALID_INPUT, CODE_NOT_FOUND, CODE_PREVIEW_STALE,
                 CODE_REFUND_GROUP_INCOMPLETE, CODE_REFUND_PAIR_PARTIALLY_BOOKED,
                 StoreError, canonical, decided_sql, utc_now)

__all__ = ["preview", "commit", "preview_digest", "recordable_rows"]


def recordable_rows(rows):
    """Unique transactions that can be newly booked from a preview."""
    return list({row['transaction_id']: row for row in rows
                 if not row.get('blocked') and not row.get('already_booked')}.values())


def _ready_rows(store, batch_id: str, review_from=None):
    return store.conn.execute(
        "SELECT transaction_id, source_hash, merchant, amount_krw,"
        " COALESCE(NULLIF(approval_date,''),posting_date), transaction_direction, item, description,"
        " display_tab_id, trip_id, revision, " + decided_sql() + ", classification_state,"
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


def _recording_guard(*, source_hash, state, conflict_reason, parse_error, exclusion=None, hold=None):
    """Common source/review guards that must block every path into ledger_entries."""
    if exclusion and exclusion['source_hash'] != source_hash:
        return 'exclusion_source_changed', '회사 경비 제외를 확인한 원본이 달라 다시 검토해야 합니다'
    if exclusion and exclusion['excluded']:
        return 'company_excluded', '사용자가 회사 경비에서 제외했습니다'
    if hold:
        return 'review_hold', hold['reason']
    if conflict_reason:
        return 'source_conflict', conflict_reason
    if parse_error:
        return 'amount_unreadable', parse_error
    if state != 'classified':
        return 'needs_review', '분류가 끝나지 않아 장부에 기록하지 않아요'
    return None


def preview(store, batch_id: str, *, trip_validator=None,
             tab_validator=None, review_from=None, entry_metadata=None,
             additional_holds=None, group_original=None) -> dict:
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
    from .company_expenses import states
    exclusions = states(store.conn)
    from .review_holds import active_holds
    holds=active_holds(store.conn)
    for transaction_id, hold in (additional_holds or {}).items():
        holds.setdefault(str(transaction_id), dict(hold) if isinstance(hold, dict) else
                         {"kind":"external_review_hold", "reason":str(hold)})
    rows: list[dict] = []
    ready: list[dict] = []
    unresolved: list[dict] = []
    duplicates: list[dict] = []
    conflicts: list[dict] = []

    # One read of the booked ids instead of one query per row: every query is a
    # GIL hand-off, and a preview of ~1000 rows was dominated by those hand-offs.
    booked_dates = dict(store.conn.execute("SELECT transaction_id,occurred_on FROM ledger_entries"))
    booked_ids = set(booked_dates)
    for row in _ready_rows(store, batch_id, review_from):
        (transaction_id, source_hash, merchant, amount_krw, approval_date,
         direction, item, description, tab, trip_id, revision, decided,
         state, conflict_reason, parse_error) = row
        decision = decisions.get(transaction_id)
        entry = {
            "transaction_id": transaction_id, "source_hash": source_hash,
            "merchant": merchant, "amount_krw": amount_krw,
            "occurred_on": booked_dates.get(transaction_id, approval_date), "transaction_direction": direction,
            "item": (decision or {}).get("item", item) or "",
            "description": (decision or {}).get("description", description) or "",
            "display_tab_id": (decision or {}).get("display_tab_id", tab) or "",
            "trip_id": trip_id, "revision": revision,
            "decided": bool(decided), "classification_state": state,
            "already_booked": transaction_id in booked_ids,
        }
        exclusion = exclusions.get(transaction_id)
        entry['exclusion_revision'] = exclusion['revision'] if exclusion else 0
        entry['excluded_from_company'] = bool(exclusion and exclusion['excluded'])
        hold = holds.get(transaction_id)
        blocked = _recording_guard(source_hash=source_hash, state=state,
                                   conflict_reason=conflict_reason, parse_error=parse_error,
                                   exclusion=exclusion, hold=hold)
        if blocked:
            entry['blocked'], entry['reason'] = blocked
            if hold:
                entry['review_hold'] = hold
            if entry['blocked'] == 'source_conflict':
                conflicts.append(entry)
            elif entry['blocked'] != 'company_excluded':
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

    _apply_refund_pairs(store, rows, ready, unresolved, trip_validator, tab_validator)

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
        "excluded": sum(r.get('excluded_from_company', False) for r in rows),
        "rows": rows,
    }
    result["digest"] = preview_digest(result)
    if group_original is not None:
        return scope_group(store, result, group_original)
    return result


def group_members(store, original_id: str) -> list:
    """The original and every linked refund, read from the database. A caller never names them."""
    from .partial_refund import refund_group, refund_links
    members = refund_group(store.conn, str(original_id))
    if len(members) < 2:
        raise StoreError(CODE_INVALID_INPUT, "연결된 환불이 없는 원거래예요")
    links = refund_links(store.conn, members[1:])
    if (sorted(links) != sorted(members[1:])
            or any(link["original_id"] != original_id for link in links.values())):
        raise StoreError(CODE_REFUND_GROUP_INCOMPLETE,
                         "환불이 원거래 하나에 명확히 연결되지 않아 함께 기록할 수 없어요")
    return members


def scope_group(store, result: dict, original_id: str) -> dict:
    """One refund group's rows taken from a whole-batch preview. Writes nothing.

    The group is decided by the database, so a group cannot be shrunk by the
    caller. Every member must be on this batch and the group must not be half
    booked; a group that is held as a whole comes back `recordable: False`.
    """
    members = group_members(store, original_id)
    by_id = {row["transaction_id"]: row for row in result["rows"]}
    if any(member not in by_id for member in members):
        raise StoreError(CODE_REFUND_GROUP_INCOMPLETE,
                         "묶인 거래가 이 접수 건에 모두 없어 기록하지 않아요")
    rows = [by_id[member] for member in members]
    booked = [bool(row.get("already_booked")) for row in rows]
    held = [row for row in rows if row.get("blocked")]
    scoped = dict(result, rows=rows, scope="refund_group", original_id=original_id, members=members,
                  ready=len(recordable_rows(rows)), unresolved=len(held),
                  duplicates=0, conflicts=0)
    scoped["recordable"] = all(booked) or not held
    scoped["reason"] = "" if scoped["recordable"] else held[0].get("reason", "")
    scoped["digest"] = preview_digest(scoped)
    return scoped


PREVIEW_VERSION = "ledger-preview-v3"

_PAIR_UNBLOCKABLE = ("needs_review", "item_missing")
# 원거래와 환불이 전액 상쇄되면 비용 탭에서 빼서 환불 탭에 둔다(소유자 규칙 2026-10-15).
REFUND_TAB = "refunds"


def _move(entry, ready, unresolved, to_ready):
    for bucket in (ready, unresolved):
        if entry in bucket:
            bucket.remove(entry)
    (ready if to_ready else unresolved).append(entry)


def _block_pair(entries, code, reason, ready, unresolved):
    for entry in entries:
        entry["blocked"] = code
        entry["reason"] = reason
        _move(entry, ready, unresolved, False)


def _apply_refund_pairs(store, rows, ready, unresolved, trip_validator, tab_validator):
    """A linked refund and its original are decided together or not at all.

    The refund inherits item, tab and trip from its original when it has none of
    its own; a conflicting classification, an over-refund or any other block on
    either row holds both. Source amounts are untouched; the net is derived.
    """
    from .partial_refund import refund_links
    by_id = {r["transaction_id"]: r for r in rows}
    for refund_id, link in refund_links(store.conn, list(by_id)).items():
        refund = by_id.get(refund_id)
        original = by_id.get(link["original_id"])
        if refund is None:
            continue
        if original is None:
            _block_pair([refund], "refund_original_missing",
                        "환불의 원거래가 이 접수 건에 없어 함께 기록할 수 없어요", ready, unresolved)
            continue
        pair = [original, refund]
        if link["status"] == "excess":
            _block_pair(pair, "refund_exceeds_original", "환불 합계가 원결제보다 커서 보류해요", ready, unresolved)
            continue
        # 원거래가 먼저 기록되고 환불이 나중에 온 경우(또는 반대): 기록된 쪽의 배속을 빠진 쪽이 이어받아 함께 맞춘다.
        if bool(original.get("already_booked")) != bool(refund.get("already_booked")):
            source, target = (original, refund) if original.get("already_booked") else (refund, original)
        else:
            source, target = original, refund
        # 이미 기록된 쪽의 "기록됨" 표시는 보류가 아니다. 빠진 쪽만 보류 여부를 본다.
        if original.get("blocked") and not original.get("already_booked"):
            _block_pair([refund], "refund_pair_incomplete", "원거래가 보류 중이라 환불도 함께 보류해요", ready, unresolved)
            continue
        if refund.get("blocked") and refund["blocked"] not in _PAIR_UNBLOCKABLE and not refund.get("already_booked"):
            _block_pair([original], "refund_pair_incomplete", "환불 거래가 보류 중이라 원거래도 함께 보류해요", ready, unresolved)
            continue
        # 전액 상쇄 쌍은 환불의 배속이 원거래와 달라도 된다. 어느 쪽이든 환불 탭으로 간다.
        clash = [k for k in ("item", "display_tab_id", "trip_id")
                 if link["status"] != "full" and refund.get(k) and original.get(k) and refund[k] != original[k]]
        if clash:
            _block_pair(pair, "refund_pair_mismatch", "환불과 원거래의 분류가 달라 보류해요", ready, unresolved)
            continue
        for key in ("item", "display_tab_id", "trip_id", "description"):
            if not target.get(key):
                target[key] = source.get(key) or ""
        if link["status"] == "full":
            for row in pair:
                if not row.get("already_booked"):
                    row["display_tab_id"] = REFUND_TAB
                    row["trip_id"] = ""
        block = _authority_block(target, trip_validator, tab_validator)
        if block or not target.get("item"):
            _block_pair(pair, block[0] if block else "refund_pair_incomplete",
                        block[1] if block else "환불에 이어받을 항목이 없어 함께 보류해요", ready, unresolved)
            continue
        if target.get("blocked"):
            target.pop("blocked", None)
            target.pop("reason", None)
            _move(target, ready, unresolved, True)
        net = {"gross_krw": link["gross_krw"], "refund_krw": link["refunds_total_krw"],
               "net_krw": link["net_krw"], "status": link["status"]}
        refund["refund_link"] = dict(net, role="refund", counterpart_id=original["transaction_id"])
        original["refund_link"] = dict(net, role="original", counterpart_id=refund_id)

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
        # 카드 원문 날짜는 그대로 두고, 새 OTA 비용 날짜에만 검증된 이용일을 쓴다.
        evidence = entry.get('ota_evidence') or {}
        if (not entry.get('already_booked') and entry.get('transaction_direction') == 'purchase'
                and entry.get('booking_ref') and evidence.get('source_digests')
                and evidence.get('kind') in ('exact', 'inferred', 'ordered_group')):
            from datetime import date
            from .reconciliation import ledger_date_for_booking
            service_day = str(entry.get('service_period') or '').split('~')[0].strip()
            try:
                service_day = date.fromisoformat(service_day).isoformat()
            except ValueError:
                continue
            entry['occurred_on'] = ledger_date_for_booking(service_day, entry['occurred_on'])


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
             "ota_evidence": r.get("ota_evidence"),
             "refund_link": r.get("refund_link")}
            for r in result.get("rows", [])
            if not r.get("blocked")
        ],
    }
    if result.get("scope"):
        body["scope"] = [result["scope"], result.get("original_id")]
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _already_booked(store, transaction_id: str) -> bool:
    return store.conn.execute(
        "SELECT 1 FROM ledger_entries WHERE transaction_id=?",
        (transaction_id,)).fetchone() is not None


def _check_refund_groups(store, rows) -> None:
    """Refuse a commit that would leave a refund group half booked. Writes nothing."""
    from .partial_refund import refund_group, refund_links
    ready = {r["transaction_id"] for r in rows if not r.get("blocked") and not r.get("already_booked")}
    links = refund_links(store.conn, [r["transaction_id"] for r in rows])
    for original_id in {link["original_id"] for link in links.values()}:
        members = refund_group(store.conn, original_id)
        booked = [m for m in members if _already_booked(store, m)]
        ready_members = [m for m in members if m in ready]
        if not booked and 0 < len(ready_members) < len(members):
            raise StoreError(CODE_REFUND_GROUP_INCOMPLETE,
                             "환불 묶음을 모두 함께 기록할 수 없어 기록하지 않았어요. 묶인 거래를 함께 확인해 주세요")


def commit(store, batch_id: str, preview_digest_value: str, request_id: str,
           *, projection=None, trip_validator=None, tab_validator=None,review_from=None,
           entry_metadata=None, additional_holds=None, group_original=None, automatic_record=False) -> dict:
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

    scope = {"batch_id": batch_id, "digest": preview_digest_value}
    if automatic_record:
        scope['automatic_record'] = True
    if group_original is not None:
        scope["group"] = str(group_original)
    payload_sha = hashlib.sha256(canonical(scope).encode("utf-8")).hexdigest()
    replay = store.replay_request(request_id, "commit", payload_sha)
    if replay is not None:
        return replay

    current = preview(store, batch_id, trip_validator=trip_validator,
                      tab_validator=tab_validator,review_from=review_from,
                      entry_metadata=entry_metadata, additional_holds=additional_holds,
                      group_original=group_original)
    if current["digest"] != preview_digest_value:
        raise StoreError(CODE_PREVIEW_STALE,
                         "미리보기 이후에 답변이 달라졌어요. 다시 확인해 주세요")
    if group_original is not None and not current["recordable"]:
        raise StoreError(CODE_REFUND_GROUP_INCOMPLETE,
                         current["reason"] or "환불 묶음을 함께 기록할 수 없어 기록하지 않았어요")

    booked: list[str] = []
    already: list[str] = []
    lost_authority: list[str] = []
    now = utc_now()
    with store.lock:
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            _check_refund_groups(store, recordable_rows(current["rows"]) if automatic_record else current["rows"])
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
                store.log_change("ledger.booked", transaction_id,
                                 {"batch_id": batch_id, "item": entry["item"],
                                  "amount_krw": entry["amount_krw"],
                                  "source_hash": entry["source_hash"]})
                if projection is not None:
                    if not callable(projection):
                        raise StoreError(CODE_INVALID_INPUT,
                                         "게시 함수가 아니에요")
                    projection(dict(entry, batch_id=batch_id, now=now))
            # 이미 기록된 행은 보류 표시가 있어도 기록된 상태로 본다. 짝을 맞출 때 기준이 된다.
            done = set(booked) | set(already) | {e["transaction_id"] for e in current["rows"] if e.get("already_booked")}
            for entry in current["rows"]:
                link = entry.get("refund_link")
                if link and not entry.get("blocked") and (
                        (entry["transaction_id"] in done) != (link["counterpart_id"] in done)):
                    raise StoreError(CODE_PREVIEW_STALE,
                                     "환불과 원거래를 함께 기록하지 못해 취소했어요. 다시 확인해 주세요")
                if link and link["role"] == "refund" and entry["transaction_id"] in booked:
                    store.log_change("ledger.refund_linked", entry["transaction_id"],
                                     {"original_id": link["counterpart_id"], "gross_krw": link["gross_krw"],
                                      "refund_krw": link["refund_krw"], "net_krw": link["net_krw"],
                                      "status": link["status"]})
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
