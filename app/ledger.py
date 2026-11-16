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
import json

from .db import (CODE_INVALID_INPUT, CODE_NOT_FOUND, CODE_PREVIEW_STALE,
                 CODE_REFUND_GROUP_INCOMPLETE, CODE_REFUND_PAIR_PARTIALLY_BOOKED,
                 StoreError, canonical, decided_sql, utc_now)

__all__ = ["preview", "commit", "preview_digest", "recordable_rows"]


def recordable_rows(rows):
    """Unique transactions that can be newly booked from a preview."""
    return list({row['transaction_id']: row for row in rows
                 if not row.get('blocked') and not row.get('already_booked')}.values())


def _ready_rows(store, batch_id: str, review_from=None, *, include_verified_full_refunds=False,
                transaction_ids=None):
    """Keep ordinary previews scoped to their file; expand only verified zero-net
    refund groups for the automatic recorder. Inferred links are never expanded.
    """
    columns = (
        "transaction_id, source_hash, merchant, amount_krw,"
        " COALESCE(NULLIF(approval_date,''),posting_date), transaction_direction, item, description,"
        " display_tab_id, trip_id, revision, " + decided_sql() + ", classification_state, classification_source,"
        " conflict_reason, parse_error, duplicate_of"
    )
    eligible = (
        "(? IS NULL OR COALESCE(NULLIF(approval_date,''),posting_date)=''"
        " OR COALESCE(NULLIF(approval_date,''),posting_date)>=?)"
    )
    rows = list(store.conn.execute(
        "SELECT " + columns + " FROM transactions WHERE " + eligible +
        " AND transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)"
        + ("" if transaction_ids is None else " AND transaction_id IN (SELECT value FROM json_each(?))") +
        " ORDER BY transaction_id",
        (review_from, review_from, batch_id) if transaction_ids is None
        else (review_from, review_from, batch_id, json.dumps(sorted(transaction_ids)))).fetchall())
    if not include_verified_full_refunds:
        return rows
    from .partial_refund import refund_links, refund_group, is_numbered_partial, partial_group_exclusion
    current_ids = {row[0] for row in rows}
    refund_ids = [r[0] for r in store.conn.execute(
        "SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'")]
    links = refund_links(store.conn, refund_ids)
    extra = set()
    for refund_id, link in links.items():
        if link.get('inferred') or not (
                (link['status'] == 'full' and link['net_krw'] == 0) or is_numbered_partial(link)):
            continue
        if is_numbered_partial(link) and partial_group_exclusion(store.conn, link['original_id']):
            continue
        if refund_id in current_ids or link['original_id'] in current_ids:
            extra.update(refund_group(store.conn, link['original_id']))
    extra.difference_update(current_ids)
    # Only ever use actual imported originals. Never construct synthetic money rows.
    # Bounded SQL parameters work even when a source batch has thousands of rows.
    for start in range(0, len(extra), 400):
        chunk = sorted(extra)[start:start + 400]
        marks = ",".join("?" for _ in chunk)
        rows.extend(store.conn.execute(
            "SELECT " + columns + " FROM transactions WHERE " + eligible +
            " AND transaction_id IN (" + marks + ")"
            " AND EXISTS (SELECT 1 FROM import_batch_rows r WHERE r.transaction_id=transactions.transaction_id)"
            " ORDER BY transaction_id", (review_from, review_from, *chunk)).fetchall())
    return sorted(rows, key=lambda row: row[0])


def _decision_rows(store, batch_id: str, transaction_ids=None):
    """Latest decision per transaction, for the preview to reflect."""
    from .decision_provenance import active_decision_sql
    rows = store.conn.execute(
        "SELECT d.transaction_id, d.revision, d.item, d.description,"
        " d.display_tab_id, d.note FROM review_decisions d"
        " JOIN transactions t ON t.transaction_id = d.transaction_id"
        " WHERE t.transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?) AND d.revision ="
        " (SELECT MAX(revision) FROM review_decisions x"
        "  WHERE x.transaction_id = d.transaction_id) AND "+active_decision_sql()
        + ("" if transaction_ids is None else " AND t.transaction_id IN (SELECT value FROM json_each(?))"),
        (batch_id,) if transaction_ids is None else (batch_id, json.dumps(sorted(transaction_ids)))).fetchall()
    return {r[0]: {"revision": r[1], "item": r[2], "description": r[3],
                   "display_tab_id": r[4], "note": r[5]} for r in rows}


def _recording_guard(*, source_hash, state, conflict_reason, parse_error,
                     duplicate_of=None, exclusion=None, hold=None):
    """Common source/review guards that must block every path into ledger_entries."""
    if exclusion and exclusion['source_hash'] != source_hash:
        return 'exclusion_source_changed', '회사 경비 제외를 확인한 원본이 달라 다시 검토해야 합니다'
    if exclusion and exclusion['excluded']:
        return 'company_excluded', '사용자가 회사 경비에서 제외했습니다'
    if hold:
        return 'review_hold', hold['reason']
    if conflict_reason:
        return 'source_conflict', conflict_reason
    if duplicate_of:
        return 'duplicate_card_source', 'duplicate card source requires review'
    if parse_error:
        return 'amount_unreadable', parse_error
    if state != 'classified':
        return 'needs_review', '분류가 끝나지 않아 장부에 기록하지 않아요'
    return None


def preview(store, batch_id: str, *, trip_validator=None,
             tab_validator=None, review_from=None, entry_metadata=None,
             additional_holds=None, group_original=None,
             include_verified_full_refunds=False, transaction_ids=None) -> dict:
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

    source_rows = _ready_rows(store, batch_id, review_from,
                              include_verified_full_refunds=include_verified_full_refunds,
                              transaction_ids=transaction_ids)
    decisions = _decision_rows(store, batch_id, transaction_ids)
    if include_verified_full_refunds:
        # A counterpart may have a user decision in another import batch.
        batch_ids = {r[0] for r in store.conn.execute(
            "SELECT transaction_id FROM import_batch_rows WHERE batch_id=?", (batch_id,))}
        for external in (r[0] for r in source_rows if r[0] not in batch_ids):
            from .decision_provenance import active_decision_sql
            decision = store.conn.execute(
                "SELECT d.revision,d.item,d.description,d.display_tab_id,d.note "
                "FROM review_decisions d WHERE d.transaction_id=? "
                "AND d.revision=(SELECT MAX(revision) FROM review_decisions "
                "WHERE transaction_id=?) AND "+active_decision_sql(), (external, external)).fetchone()
            if decision:
                decisions[external] = dict(zip(
                    ('revision','item','description','display_tab_id','note'), decision))
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
    for row in source_rows:
        (transaction_id, source_hash, merchant, amount_krw, approval_date,
         direction, item, description, tab, trip_id, revision, decided,
         state, classification_source, conflict_reason, parse_error, duplicate_of) = row
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
            "duplicate_of": duplicate_of or "",
        }
        entry["classification_source"] = classification_source or ""
        if include_verified_full_refunds and transaction_id not in batch_ids:
            source = store.conn.execute(
                "SELECT batch_id FROM import_batch_rows WHERE transaction_id=? "
                "ORDER BY batch_id LIMIT 1", (transaction_id,)).fetchone()
            if source:
                entry["source_batch_id"] = source[0]
        exclusion = exclusions.get(transaction_id)
        entry['exclusion_revision'] = exclusion['revision'] if exclusion else 0
        entry['excluded_from_company'] = bool(exclusion and exclusion['excluded'])
        hold = holds.get(transaction_id)
        blocked = _recording_guard(source_hash=source_hash, state=state,
                                   conflict_reason=conflict_reason, parse_error=parse_error,
                                   duplicate_of=duplicate_of,
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
        blocked = _authority_block(entry, trip_validator, tab_validator, conn=store.conn)
        if blocked:
            entry["blocked"] = blocked[0]
            entry["reason"] = blocked[1]
            unresolved.append(entry)
            rows.append(entry)
            continue
        ready.append(entry)
        rows.append(entry)

    _apply_refund_pairs(store, rows, ready, unresolved, trip_validator, tab_validator)
    _guard_past_trip_pairs(store.conn, rows, ready, unresolved)

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
    # Existing authoritative OTA metadata wins. P2 adds a display period only;
    # it cannot alter payment/approval dates or assert a financial connection.
    from .ai_classification import service_metadata
    for entry in ready_now:
        if not entry.get('service_period') and not entry.get('booking_ref') and not entry.get('ota_evidence'):
            metadata = service_metadata(store.conn, entry['transaction_id'])
            for key in METADATA_KEYS:
                if key in metadata:
                    entry[key] = metadata[key]
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
        return scope_group(store, result, group_original,
                           require_verified_zero=include_verified_full_refunds)
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


def scope_group(store, result: dict, original_id: str,
                *, require_verified_zero=False) -> dict:
    """One refund group's rows taken from a whole-batch preview. Writes nothing.

    The group is decided by the database, so a group cannot be shrunk by the
    caller. Every member must be on this batch and the group must not be half
    booked; a group that is held as a whole comes back `recordable: False`.
    """
    members = group_members(store, original_id)
    if require_verified_zero:
        from .partial_refund import refund_links, is_numbered_partial
        links = refund_links(store.conn, members[1:])
        if (not links or len(links) != len(members) - 1
                or any(link.get('inferred') or link['original_id'] != original_id
                       or not ((link['status'] == 'full' and link['net_krw'] == 0)
                               or is_numbered_partial(link))
                       for link in links.values())):
            raise StoreError(CODE_REFUND_GROUP_INCOMPLETE,
                             "원승인번호로 검증된 원결제·환불 묶음만 이 화면에서 기록할 수 있어요")
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
    from . import core_links
    if core_links.selected() == 'rust':
        return core_links.ledger_pairs(store.conn, rows, ready, unresolved,
                                       trip_validator=trip_validator, tab_validator=tab_validator)
    from .partial_refund import refund_links
    by_id = {r["transaction_id"]: r for r in rows}
    refund_ids = [r[0] for r in store.conn.execute(
        "SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'")]
    for refund_id, link in refund_links(store.conn, refund_ids).items():
        refund = by_id.get(refund_id)
        original = by_id.get(link["original_id"])
        if refund is None:
            if original is not None and not original.get('already_booked'):
                _block_pair([original], 'refund_group_incomplete',
                            '연결된 취소가 이 접수 건에 없어 원결제를 함께 확인해야 합니다.', ready, unresolved)
            continue
        if original is None:
            _block_pair([refund], "refund_original_missing",
                        "환불의 원거래가 이 접수 건에 없어 함께 기록할 수 없어요", ready, unresolved)
            continue
        pair = [original, refund]
        if link.get('inferred'):
            # Displaying an inferred relation never authorizes ledger writes,
            # inheritance of a trip/item, or cash-refund settlement.
            net = {key: link[key] for key in ('gross_krw', 'net_krw', 'status', 'basis')}
            net['refund_krw'] = link['refunds_total_krw']
            net['inferred'] = True
            for entry, role, counterpart in ((original, 'original', refund_id),
                                              (refund, 'refund', link['original_id'])):
                entry['refund_link'] = dict(net, role=role, counterpart_id=counterpart)
                if not entry.get('already_booked'):
                    if not entry.get('blocked') or entry['blocked'] in (
                            'needs_review', 'item_missing', 'tab_no_longer_valid', 'trip_no_longer_valid'):
                        _block_pair([entry], 'refund_inferred',
                                    '원결제 추론 연결 · 별도 근거 검증 전 장부 기록 보류 (환급 완료 아님)',
                                    ready, unresolved)
            continue
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
            if not refund.get('blocked') or refund['blocked'] in _PAIR_UNBLOCKABLE:
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
        cross_file = bool(original.get("source_batch_id") or refund.get("source_batch_id"))
        if link["status"] == "partial" and cross_file:
            from .partial_refund import partial_group_exclusion
            reason = partial_group_exclusion(store.conn, link["original_id"])
            if reason:
                _block_pair(pair, "refund_" + reason,
                            "완료 기간 자료이거나 오류·중복·충돌 취소가 있어 파일 간 부분환불을 기록하지 않아요",
                            ready, unresolved)
                continue
        if (link["status"] != "full" and cross_file
                and not original.get("trip_id")
                and original.get("display_tab_id") in ("", "unclassified", REFUND_TAB)):
            # A cross-file partial refund is booked only to the original's real trip or quarter cost.
            _block_pair(pair, "refund_original_unattributed",
                        "원결제에 여행이나 분기 기타비용 귀속이 없어 취소를 기록하지 않아요", ready, unresolved)
            continue
        for key in ("item", "display_tab_id", "trip_id", "description"):
            if not target.get(key):
                target[key] = source.get(key) or ""
        if link["status"] == "full":
            for row in pair:
                if not row.get("already_booked"):
                    row["display_tab_id"] = REFUND_TAB
                    row["trip_id"] = ""
        block = _authority_block(target, trip_validator, tab_validator, conn=store.conn)
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


def _past_trip_block(conn, entry):
    if conn is None or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trip_tabs'").fetchone():
        return None
    from .trip_selection import past_trip
    source = conn.execute('SELECT approval_date,posting_date FROM transactions WHERE transaction_id=?',
                          (entry['transaction_id'],)).fetchone()
    if not source:
        return None
    for target in {entry.get('trip_id'), entry.get('display_tab_id')} - {None, ''}:
        trip = conn.execute('SELECT ends_on FROM trip_tabs WHERE tab_id=?', (target,)).fetchone()
        if trip and past_trip(dict(approval_date=source[0], posting_date=source[1]), dict(ends_on=trip[0])):
            return ('past_trip', 'TRIP-099 · 결제일보다 7일 넘게 전에 끝난 여행에는 기록할 수 없어요')
    return None


def _guard_past_trip_pairs(conn, rows, ready, unresolved):
    """Recheck inherited destinations after either Python or Rust pair assembly."""
    from .partial_refund import refund_group
    for entry in list(ready):
        block = _past_trip_block(conn, entry)
        if not block:
            continue
        ids = {entry['transaction_id']}
        link = entry.get('refund_link') or {}
        if link:
            original = entry['transaction_id'] if link.get('role') == 'original' else link['counterpart_id']
            ids.update(refund_group(conn, original))
        _block_pair([r for r in rows if r['transaction_id'] in ids], *block, ready, unresolved)


def _authority_block(entry: dict, trip_validator, tab_validator, *, conn=None):
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
    return _past_trip_block(conn, entry)


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
             "already_booked": bool(r.get("already_booked")),
             "classification_source": r.get("classification_source", ""),
             "booking_ref": r.get("booking_ref"),
             "service_period": r.get("service_period"),
             "ota_evidence": r.get("ota_evidence"),
             "refund_link": r.get("refund_link"),
             **({"source_batch_id": r["source_batch_id"]} if r.get("source_batch_id") else {})}
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


def _check_refund_groups(store, rows) -> frozenset[str] | None:
    """Refuse a commit that would leave a refund group half booked. Writes nothing."""
    from . import core_links
    if core_links.selected() == 'rust':
        return core_links.check_ledger_groups(store.conn, rows)
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


def _committed_group_replay(store, payload_sha, current_digest, current):
    """Return a no-op only for an exact request with its post-commit digest."""
    import json
    ids = {item["transaction_id"] for item in current.get("rows", [])}
    if not ids:
        return None
    if any(item.get("blocked") or not item.get("already_booked")
           for item in current["rows"]):
        return None
    current_revisions = {item["transaction_id"]: item.get("revision")
                         for item in current["rows"]}
    current_core = [store.conn.execute(
        "SELECT item, description, display_tab_id, trip_id, amount_krw, merchant,"
        "occurred_on, transaction_direction, source_hash FROM ledger_entries "
        "WHERE transaction_id=?", (item["transaction_id"],)).fetchone()
                    for item in current["rows"]]
    if any(row is None for row in current_core):
        return None
    fingerprint = hashlib.sha256(canonical(current_core).encode("utf-8")).hexdigest()
    rows = store.conn.execute(
        "SELECT response_json FROM requests WHERE scope='commit' AND payload_sha256=?",
        (payload_sha,)).fetchall()
    for (raw,) in rows:
        response = json.loads(raw)
        if (response.get("replay_post_digest") == current_digest
                and set(response.get("replay_post_revisions", {})) == ids
                and response.get("replay_post_revisions") == current_revisions
                and response.get("replay_ledger_fingerprint") == fingerprint):
            return dict(response, applied=0, already=len(ids), booked=[],
                        already_booked=sorted(ids))
    return None


def _persist_verified_refund_classification(store, entry, transaction_id: str) -> None:
    """Persist the refund-tab classification applied by a verified pair preview."""
    link = entry.get("refund_link") or {}
    if (link.get("inferred") or link.get("status") != "full"
            or link.get("net_krw") != 0 or entry.get("transaction_id") != transaction_id):
        return
    current = store.conn.execute(
        "SELECT classification_source FROM transactions WHERE transaction_id=?",
        (transaction_id,),
    ).fetchone()
    if not current or (str(current[0] or "").startswith("user_")
                       and current[0] != "user_completed_period"):
        return
    store.conn.execute(
        "UPDATE transactions SET classification_state='classified',"
        " classification_source='refund_original',"
        " classification_basis=?, item=?, description=?, display_tab_id='refunds',"
        " trip_id='', revision=revision+1 WHERE transaction_id=?",
        (f"검증된 원결제·환불 묶음 · 원거래 {link['counterpart_id']}",
         entry.get("item") or "", entry.get("description") or "", transaction_id),
    )


def commit(store, batch_id: str, preview_digest_value: str, request_id: str,
           *, projection=None, trip_validator=None, tab_validator=None,review_from=None,
           entry_metadata=None, additional_holds=None, group_original=None,
           automatic_record=False, include_verified_full_refunds=False, transaction_ids=None) -> dict:
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
    if include_verified_full_refunds:
        if not automatic_record:
            raise StoreError(CODE_INVALID_INPUT, "검증된 환불 묶음 확장은 자동 기록 전용입니다")
        scope['include_verified_full_refunds'] = True
    if group_original is not None:
        scope["group"] = str(group_original)
    payload_sha = hashlib.sha256(canonical(scope).encode("utf-8")).hexdigest()
    try:
        replay = store.replay_request(request_id, "commit", payload_sha)
    except StoreError as exc:
        if exc.code != "REQUEST_ID_REUSED":
            raise
        probe = preview(store, batch_id, trip_validator=trip_validator,
                        tab_validator=tab_validator, review_from=review_from,
                        entry_metadata=entry_metadata, additional_holds=additional_holds,
                        group_original=group_original,
                        include_verified_full_refunds=include_verified_full_refunds,
                        transaction_ids=transaction_ids)
        if (probe["digest"] == preview_digest_value
                and probe.get("rows")
                and all(row.get("already_booked") for row in probe["rows"])):
            import json
            stored = store.conn.execute(
                "SELECT response_json FROM requests WHERE request_id=? AND scope='commit'",
                (request_id,),
            ).fetchone()
            if stored:
                return json.loads(stored[0])
        raise
    if replay is not None:
        return replay

    current = preview(store, batch_id, trip_validator=trip_validator,
                      tab_validator=tab_validator,review_from=review_from,
                      entry_metadata=entry_metadata, additional_holds=additional_holds,
                      group_original=group_original,
                      include_verified_full_refunds=include_verified_full_refunds,
                        transaction_ids=transaction_ids)
    if current["digest"] != preview_digest_value:
        if group_original is not None:
            with store.lock:
                nested = store.conn.in_transaction
                store.conn.execute('SAVEPOINT cost_ledger_commit' if nested else 'BEGIN IMMEDIATE')
                try:
                    locked = preview(store, batch_id, trip_validator=trip_validator,
                                     tab_validator=tab_validator, review_from=review_from,
                                     entry_metadata=entry_metadata, additional_holds=additional_holds,
                                     group_original=group_original,
                                     include_verified_full_refunds=include_verified_full_refunds,
                        transaction_ids=transaction_ids)
                    replay = _committed_group_replay(store, payload_sha,
                                                     locked["digest"], locked)
                    if replay is not None:
                        store.remember_request(request_id, "commit", payload_sha, replay)
                        store.conn.execute('RELEASE SAVEPOINT cost_ledger_commit' if nested else 'COMMIT')
                        return replay
                    if nested:
                        store.conn.execute('ROLLBACK TO SAVEPOINT cost_ledger_commit')
                        store.conn.execute('RELEASE SAVEPOINT cost_ledger_commit')
                    else:
                        store.conn.execute('ROLLBACK')
                except Exception:
                    if nested:
                        store.conn.execute('ROLLBACK TO SAVEPOINT cost_ledger_commit')
                        store.conn.execute('RELEASE SAVEPOINT cost_ledger_commit')
                    else:
                        store.conn.execute('ROLLBACK')
                    raise
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
        nested = store.conn.in_transaction
        store.conn.execute('SAVEPOINT cost_ledger_commit' if nested else 'BEGIN IMMEDIATE')
        try:
            sealed_members = _check_refund_groups(
                store, recordable_rows(current["rows"]) if automatic_record else current["rows"]) or frozenset()
            for entry in current["rows"]:
                if entry.get("blocked"):
                    continue
                transaction_id = entry["transaction_id"]
                # Re-checked here, not only above: this is the last point before
                # the money moves.
                block = _authority_block(entry, trip_validator, tab_validator, conn=store.conn)
                if block:
                    if transaction_id in sealed_members:
                        raise StoreError(CODE_REFUND_GROUP_INCOMPLETE,
                                         '환불 묶음의 기록 권한이 바뀌어 함께 기록하지 않았습니다.')
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
                    (transaction_id, entry.get("source_batch_id", batch_id),
                     entry["item"], entry["description"],
                     entry["display_tab_id"], entry.get("trip_id", ""),
                     entry["amount_krw"], entry["merchant"], entry["occurred_on"],
                     entry["transaction_direction"], entry["source_hash"], now))
                booked.append(transaction_id)
                store.log_change("ledger.booked", transaction_id,
                                 {"batch_id": entry.get("source_batch_id", batch_id),
                                  "item": entry["item"],
                                  "amount_krw": entry["amount_krw"],
                                  "source_hash": entry["source_hash"]})
                if projection is not None:
                    if not callable(projection):
                        raise StoreError(CODE_INVALID_INPUT,
                                         "게시 함수가 아니에요")
                    projection(dict(entry, batch_id=entry.get("source_batch_id", batch_id), now=now))
                if group_original is not None:
                    _persist_verified_refund_classification(store, entry, transaction_id)
            # 이미 기록된 행은 보류 표시가 있어도 기록된 상태로 본다. 짝을 맞출 때 기준이 된다.
            done = set(booked) | set(already) | {e["transaction_id"] for e in current["rows"] if e.get("already_booked")}
            for entry in current["rows"]:
                link = entry.get("refund_link")
                if (link and not link.get("inferred")
                        and not str(link.get("basis") or "").endswith("_inferred")
                        and not entry.get("blocked")
                        and ((entry["transaction_id"] in done) != (link["counterpart_id"] in done))):
                    raise StoreError(CODE_PREVIEW_STALE,
                                     "환불과 원거래를 함께 기록하지 못해 취소했어요. 다시 확인해 주세요")
                if link and link["role"] == "refund" and entry["transaction_id"] in booked:
                    store.log_change("ledger.refund_linked", entry["transaction_id"],
                                     {"original_id": link["counterpart_id"], "gross_krw": link["gross_krw"],
                                      "refund_krw": link["refund_krw"], "net_krw": link["net_krw"],
                                      "status": link["status"]})
            replay_post_digest = None
            replay_post_revisions = None
            if group_original is not None and booked:
                post_preview = preview(
                    store, batch_id, trip_validator=trip_validator,
                    tab_validator=tab_validator, review_from=review_from,
                    entry_metadata=entry_metadata, additional_holds=additional_holds,
                    group_original=group_original,
                    include_verified_full_refunds=include_verified_full_refunds,
                        transaction_ids=transaction_ids)
                replay_post_digest = post_preview["digest"]
                replay_post_revisions = {
                    entry["transaction_id"]: entry.get("revision")
                    for entry in post_preview["rows"]}
                ledger_core = [store.conn.execute(
                    "SELECT item, description, display_tab_id, trip_id, amount_krw, merchant,"
                    "occurred_on, transaction_direction, source_hash FROM ledger_entries "
                    "WHERE transaction_id=?", (entry["transaction_id"],)).fetchone()
                               for entry in post_preview["rows"]]
                replay_ledger_fingerprint = hashlib.sha256(
                    canonical(ledger_core).encode("utf-8")).hexdigest()
            result = {"batch_id": batch_id, "applied": len(booked),
                      "already": len(already), "unresolved": current["unresolved"],
                      "duplicates": current["duplicates"],
                      "conflicts": current["conflicts"],
                      "lost_authority": lost_authority,
                      "booked": booked, "already_booked": already,
                      "digest": preview_digest_value, "committed_at": now}
            if replay_post_digest is not None:
                result["replay_post_digest"] = replay_post_digest
                result["replay_post_revisions"] = replay_post_revisions
                result["replay_ledger_fingerprint"] = replay_ledger_fingerprint
            store.remember_request(request_id, "commit", payload_sha, result)
            store.conn.execute('RELEASE SAVEPOINT cost_ledger_commit' if nested else 'COMMIT')
        except Exception:
            if nested:
                store.conn.execute('ROLLBACK TO SAVEPOINT cost_ledger_commit')
                store.conn.execute('RELEASE SAVEPOINT cost_ledger_commit')
            else:
                store.conn.execute('ROLLBACK')
            raise
    return result
