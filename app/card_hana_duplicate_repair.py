"""Mark Hana approval-source rows that double-book an acquired purchase (SRC-013).

A Hana overseas purchase arrived twice: once in the acquired usage view
(`hana_foreign`, billed 청구금액) and once in an approval-source download
(`headered`, approval-time 승인금액). The two views pad the same approval number
with different leading zeros, so the importer stored them as two transactions and
booked both. This repair marks the approval-source row as a duplicate of the
acquired row and drops only its derived ledger/board projection, so the purchase
is counted once. The acquired row stays the financial canonical because cost is
judged from the acquired original and the overseas billed total (SRC-005, SRC-009).

The canonical direction is independent of import order: even when the approval
source was imported and booked first, the acquired billed row stays canonical.
A shared normalized approval number + card + date is one authorization, so a
same-merchant pair is one purchase even when the approval is a small pre-auth hold
and the bill is the final total (overseas gas), and a normal-FX-ratio pair whose
merchant notation differs (operator/category/romanization) is one purchase too.
When the canonical row was never booked, the approval's ledger/board projection
moves onto it with the billed amount and inherited attribution.

Nothing here deletes a card source row or rewrites an original cell: the
`transactions` row, its `raw_row_json`, amount, sign, id and stored approval
number are preserved. Only `duplicate_of` is set and the duplicate's
`ledger_entries`/`board_rows` projections are removed (open periods) or left in
place (closed periods already handed to the tax firm). Refund-paired, manually
corrected, source-protected and trip-attribution-disagreeing pairs are never
moved; they are reported by reason.

Structure mirrors `closed_period_repair`: count-only preview, digest/backup-gated
apply, audited restore and idempotent replay.
"""
from collections import Counter
import json

from .core_links import uncommitted_rows
from .db import utc_now
from .decision_provenance import _state, _digest
from .normalize import normalize_approval_number

SCOPE = 'hana_double_import'
RELEASE = 'card.hana_duplicate_marked'
RESTORE = 'card.hana_duplicate_restored'

# Cost is judged from the acquired original; the approval-source download is the
# redundant view. Layouts are the parser suffix after the format prefix.
ACQUIRED_LAYOUTS = ('hana_foreign', 'hana_usage')
APPROVAL_LAYOUTS = ('headered',)
MANUAL_SOURCES = {'user_decision', 'user_exception', 'owner_booking', 'manual', 'manual_hold'}
# A normal FX/fee ratio corroborates one purchase when the merchant notation
# differs. A wide multiple alone no longer excludes a same-merchant pair: an
# overseas gas pre-auth hold is small next to the final billed total (SRC-009).
RATIO_MIN, RATIO_MAX = 0.5, 2.0


def _open_trips(conn):
    if not _has_table(conn, 'trip_tabs'):
        return []
    cursor = conn.execute('SELECT * FROM trip_tabs')
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, record)) for record in cursor.fetchall()]


def _period_label(day):
    text = str(day or '')[:7]
    if len(text) >= 7 and text[5:7].isdigit():
        return f"{text[:4]}Q{(int(text[5:7]) - 1) // 3 + 1}"
    return text[:4] or 'unknown'


def closed_period(conn, row):
    """Closed = outside the common open scope (REC-007 / SPEC §6.5).

    Delegates to `closed_period.open_scope` — trips attributed from the 0630 trip
    (departing 2026-06-30) onward, or dates in 2026 Q3 and later, are open; every
    other period is closed. No hardcoded dates here, so the cleanup and the import
    path share the one open/closed boundary. Returns a display period label when
    closed, else None.
    """
    from .closed_period import open_scope
    if open_scope(row, _open_trips(conn)):
        return None
    return _period_label(row.get('approval_date') or row.get('posting_date'))


def _layout(parser):
    return str(parser or '').split(':', 1)[-1]


def _has_table(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _repair_state(conn, tid):
    """Like decision_provenance._state, but the board projection is optional.

    The import path can run on the card-only schema, which has no board tables;
    the cleanup runs on the full ledger schema. Both share the move below.
    """
    from .decision_provenance import _dict_row
    board = (_dict_row(conn, 'board_rows', 'row_id', 'card-' + tid)
             if _has_table(conn, 'board_rows') else None)
    return dict(transaction=_dict_row(conn, 'transactions', 'transaction_id', tid),
                ledger=_dict_row(conn, 'ledger_entries', 'transaction_id', tid),
                board=board)


def _merchant_compatible(a, b):
    a, b = str(a or ''), str(b or '')
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    # Notation variants of one merchant share a brand stem (romanization, branch
    # or punctuation differences). A short shared prefix is corroboration only;
    # the amount ratio is the decisive guard against approval-number reuse.
    stem = 0
    for x, y in zip(a, b):
        if x != y:
            break
        stem += 1
    return stem >= 4


def _financial_state(conn):
    """Bind the refund graph and protection records that must not change."""
    from .partial_refund import refund_links
    ids = [r[0] for r in conn.execute('SELECT transaction_id FROM transactions')]
    names = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                   if 'refund' in r[0] or 'link' in r[0] or 'group_pin' in r[0]
                   or r[0] in {'transaction_review_holds', 'transaction_company_exclusions',
                               'board_manual_overrides', 'review_decisions'})
    tables = {name: sorted(conn.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(),
                           key=lambda row: json.dumps(row, sort_keys=True, default=str)) for name in names}
    with uncommitted_rows():  # runs inside the repair transaction: read its own rows, roll back as a unit
        links = refund_links(conn, ids)
    return _digest(dict(links=links, tables=tables))


def _manual_reason(conn, tid, row):
    if row.get('decided_at') or row.get('classification_source') in MANUAL_SOURCES:
        return 'MANUAL_CORRECTION'
    if conn.execute('SELECT 1 FROM review_decisions WHERE transaction_id=?', (tid,)).fetchone():
        return 'MANUAL_CORRECTION'
    if _has_table(conn, 'board_manual_overrides') and conn.execute(
            'SELECT 1 FROM board_manual_overrides WHERE row_id=?', ('card-' + tid,)).fetchone():
        return 'MANUAL_CORRECTION'
    if conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=?', (tid,)).fetchone():
        return 'REVIEW_HOLD'
    if conn.execute('SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=? AND excluded=1',
                    (tid,)).fetchone():
        return 'COMPANY_EXCLUDED'
    return ''


def _refund_reason(conn, pair_tids, number_index):
    from .partial_refund import refund_links
    pair = set(pair_tids)
    # Overseas cancellations carry no approval number and pair by amount/merchant,
    # so inspect every formed link (numbered, foreign, inferred), not just the
    # approval-number index. A row is touched if it is a refund or an original.
    cancels = [r[0] for r in conn.execute(
        "SELECT transaction_id FROM transactions WHERE transaction_direction='cancellation'")]
    with uncommitted_rows():  # the import transaction has inserted earlier rows of the same file
        links = refund_links(conn, cancels)
    touched = set(links) | {link['original_id'] for link in links.values()}
    if touched & pair:
        return 'REFUND_PAIRED'
    # A cancellation may reference either row's approval number without a formed
    # link yet (ambiguous or held); that reference still protects the pair.
    for tid in pair:
        for ref in number_index.get(tid, ()):
            if ref not in pair:
                return 'REFUND_PAIRED'
    return ''


def _attribution_reason(keep, dup):
    """Protect a trip-vs-trip attribution disagreement (existing ledger rule).

    The two views of one purchase can land in different trips when trip windows
    overlap. `closed_period_repair` refuses to re-attribute a projection it cannot
    place (`PROJECTION_ATTRIBUTION_DISAGREEMENT`); the same rule applies here, so a
    genuine trip conflict is reported for review instead of silently moving cost.
    An empty/unclassified side is not a conflict — the survivor can inherit it.
    """
    ka = str(keep.get('trip_id') or keep.get('display_tab_id') or '')
    da = str(dup.get('trip_id') or dup.get('display_tab_id') or '')
    if ka.startswith('trip-') and da.startswith('trip-') and ka != da:
        return 'ATTRIBUTION_DISAGREEMENT'
    return ''


def supersede_protection(conn, keep, dup, number_index):
    """Protection reason that forbids auto-superseding the approval row, or ''.

    Shared by the import path and the cleanup tool so both protect the same
    pairs (PROC-005 / financial protection). A manually corrected, refund-paired,
    source-protected or trip-attribution-disagreeing pair is never auto-moved; it
    is left for AI review. `keep`/`dup` are row dicts carrying transaction_id and
    the classification/attribution fields; the import path passes a freshly built
    keep dict for the incoming billed row.
    """
    for row in (keep, dup):
        if row.get('parse_error') or row.get('conflict_reason') or row.get('duplicate_of'):
            return 'SOURCE_PROTECTED'
        reason = _manual_reason(conn, row['transaction_id'], row)
        if reason:
            return reason
    reason = _refund_reason(conn, (keep['transaction_id'], dup['transaction_id']), number_index)
    if reason:
        return reason
    return _attribution_reason(keep, dup)


def _hana_rows(conn):
    cursor = conn.execute(
        "SELECT t.transaction_id, t.issuer, t.card_tail, t.card_kind, t.transaction_direction,"
        " t.approval_number, t.original_approval_number, t.approval_date, t.posting_date,"
        " t.merchant_normalized, t.amount_krw, t.batch_id, t.source_hash, t.duplicate_of,"
        " t.conflict_reason, t.parse_error, t.classification_source, t.decided_at,"
        " t.item, t.trip_id, t.display_tab_id, b.parser"
        " FROM transactions t JOIN import_batches b ON b.batch_id=t.batch_id"
        " WHERE t.issuer='하나' AND COALESCE(t.approval_number,'')<>''")
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, record)) for record in cursor.fetchall()]


def _pairs(conn):
    """Yield (keep, dup, reason) candidate pairs; reason '' means confirmed.

    keep is the acquired row, dup the approval-source row. Groups that are not a
    clean one-acquired/one-apparoval pair, or whose economics disagree, are
    returned with a reason so the preview can report them without moving them.
    """
    groups = {}
    for row in _hana_rows(conn):
        key = normalize_approval_number(row['approval_number'])
        if not key:
            continue
        gk = (row['card_tail'], row['approval_date'], row['transaction_direction'], key)
        groups.setdefault(gk, []).append(row)
    for gk, members in sorted(groups.items()):
        acquired = [r for r in members if _layout(r['parser']) in ACQUIRED_LAYOUTS]
        approval = [r for r in members if _layout(r['parser']) in APPROVAL_LAYOUTS]
        if len(members) != 2 or len(acquired) != 1 or len(approval) != 1:
            if len(acquired) >= 1 and len(approval) >= 1:
                yield acquired[0], approval[0], 'AMBIGUOUS_GROUP'
            continue
        keep, dup = acquired[0], approval[0]
        if keep['batch_id'] == dup['batch_id']:
            continue
        merchant_ok = _merchant_compatible(keep['merchant_normalized'], dup['merchant_normalized'])
        ratio_ok = True
        if keep['amount_krw'] and dup['amount_krw'] and keep['amount_krw'] > 0 and dup['amount_krw'] > 0:
            ratio_ok = RATIO_MIN <= keep['amount_krw'] / dup['amount_krw'] <= RATIO_MAX
        # A shared normalized approval number + card + date is one authorization.
        # With the same merchant it stays one purchase even when the approval is a
        # small pre-auth hold and the acquired row is the final billed total (overseas
        # gas). With a normal FX/fee ratio, a merchant-notation difference (operator,
        # category or romanization) is the same purchase too. Only a merchant mismatch
        # combined with a wide amount multiple cannot be confirmed, so it is reported.
        if merchant_ok or ratio_ok:
            yield keep, dup, ''
        else:
            yield keep, dup, 'MERCHANT_MISMATCH'


def preview(conn):
    rows = {r['transaction_id']: r for r in _hana_rows(conn)}
    number_index = _number_index_for(conn)
    targets, excluded = [], Counter()
    excluded_pairs = []
    seen = set()
    for keep, dup, reason in _pairs(conn):
        kt, dt = keep['transaction_id'], dup['transaction_id']
        if dt in seen:
            continue
        seen.add(dt)
        if reason:
            excluded[reason] += 1
            excluded_pairs.append(dict(keep=kt, dup=dt, reason=reason))
            continue
        guard = supersede_protection(conn, keep, dup, number_index)
        if guard:
            excluded[guard] += 1
            excluded_pairs.append(dict(keep=kt, dup=dt, reason=guard))
            continue
        period = closed_period(conn, dup)
        if period:
            # Closed (submitted) period: the cleanup never touches the pair. It is
            # preserved as CLOSED_PERIOD and surfaced only to AI quarter review.
            excluded['CLOSED_PERIOD'] += 1
            excluded_pairs.append(dict(keep=kt, dup=dt, reason='CLOSED_PERIOD', period=period))
            continue
        keep_before = _state(conn, kt)
        dup_before = _state(conn, dt)
        # If the canonical acquired row was never booked but the approval row was,
        # the ledger/board projection moves to the canonical row (billed amount,
        # inherited attribution) instead of being dropped, so the cost stays booked.
        ledger_action = 'move' if not keep_before['ledger'] and dup_before['ledger'] else 'unbook'
        target = dict(tid=dt, keep=kt, closed=False, period=None,
                      before=dup_before, keep_before=keep_before, ledger_action=ledger_action,
                      values=dict(duplicate_of=kt))
        targets.append(target)
    summary = dict(
        confirmed_pairs=len(targets) + sum(excluded.values()),
        to_mark=len(targets),
        to_move=sum(1 for t in targets if t['ledger_action'] == 'move'),
        to_unbook=sum(1 for t in targets if t['ledger_action'] == 'unbook'),
        excluded=dict(excluded),
        excluded_pairs=excluded_pairs,
        quarter_distribution=dict(Counter(
            _quarter(rows[t['tid']]['approval_date'] or rows[t['tid']]['posting_date']) for t in targets)),
    )
    return dict(digest=_digest([targets, _financial_state(conn)]), targets=targets, summary=summary)


def _quarter(day):
    text = str(day or '')
    if len(text) >= 7 and text[5:7].isdigit():
        return f"{text[:4]}Q{(int(text[5:7]) - 1) // 3 + 1}"
    return 'unknown'


def _number_index_for(conn):
    by_number = {}
    for row in _hana_rows(conn):
        key = (normalize_approval_number(row['approval_number']), row['card_tail'])
        by_number.setdefault(key, []).append(row['transaction_id'])
    index = {}
    for ref_id, ref_tail, ref_number in conn.execute(
            "SELECT transaction_id, card_tail, original_approval_number FROM transactions"
            " WHERE issuer='하나' AND transaction_direction='cancellation'"
            " AND COALESCE(original_approval_number,'')<>''"):
        key = (normalize_approval_number(ref_number), ref_tail)
        for tid in by_number.get(key, ()):
            index.setdefault(tid, set()).add(ref_id)
    return index


def replay(conn, request_id):
    row = conn.execute('SELECT payload_sha256,response_json FROM requests WHERE request_id=? AND scope=?',
                       (request_id, SCOPE)).fetchone()
    return dict(digest=row[0], **json.loads(row[1])) if row else None


def _unbook(conn, tid):
    conn.execute('DELETE FROM ledger_entries WHERE transaction_id=?', (tid,))
    if _has_table(conn, 'board_rows'):
        conn.execute('DELETE FROM board_rows WHERE row_id=?', ('card-' + tid,))


def _rebook(conn, tid, before):
    ledger, board = before['ledger'], before['board']
    if ledger:
        columns = list(ledger.keys())
        conn.execute('INSERT INTO ledger_entries(' + ','.join(columns) + ') VALUES (' + ','.join('?' * len(columns)) + ')',
                     [ledger[c] for c in columns])
    if board and _has_table(conn, 'board_rows'):
        conn.execute('INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,?,?,?,?)',
                     (board['row_id'], board['row_kind'], board['display_tab_id'], board['revision'], board['payload_json']))


def move_approval_projection(conn, keep_tid, dup_tid, *, request_id, actor='automatic'):
    """Move a booked approval projection onto the canonical acquired (billed) row.

    Shared by the import path and the cleanup tool so both paths give the same
    result. The survivor keeps its OWN billed transaction info (amount, merchant,
    date, direction, source) and inherits the approval's attribution/item and
    classification; the approval row is marked a duplicate and its projection
    removed, so the cost is booked once at the billed total (SRC-005/009). The
    board edit is recorded in board_revisions. No original source cell is
    rewritten. Only used when the canonical row had no projection of its own.
    """
    keep_before = _repair_state(conn, keep_tid)
    dup_before = _repair_state(conn, dup_tid)
    keep_tx, dup_tx = keep_before['transaction'], dup_before['transaction']
    ledger, board = dup_before['ledger'], dup_before['board']
    amount = keep_tx['amount_krw']
    occurred_on = keep_tx['approval_date'] or keep_tx['posting_date']
    # Attribution/item come from the booked approval projection (fall back to its
    # transaction fields when it was never booked); classification carries over too.
    src = ledger or dup_tx
    attribution = {key: src.get(key) for key in ('item', 'description', 'display_tab_id', 'trip_id')}
    conn.execute('UPDATE transactions SET item=?,description=?,display_tab_id=?,trip_id=?,'
                 'classification_state=?,classification_source=?,classification_basis=?,decided_at=?,'
                 'revision=revision+1 WHERE transaction_id=?',
                 (attribution['item'], attribution['description'], attribution['display_tab_id'], attribution['trip_id'],
                  dup_tx.get('classification_state'), dup_tx.get('classification_source'),
                  dup_tx.get('classification_basis'), dup_tx.get('decided_at'), keep_tid))
    if ledger:
        moved = dict(ledger, transaction_id=keep_tid, batch_id=keep_tx['batch_id'], amount_krw=amount,
                     merchant=keep_tx['merchant'], occurred_on=occurred_on,
                     transaction_direction=keep_tx['transaction_direction'], source_hash=keep_tx['source_hash'],
                     committed_at=utc_now(), **attribution)
        columns = list(moved.keys())
        conn.execute('INSERT INTO ledger_entries(' + ','.join(columns) + ') VALUES (' + ','.join('?' * len(columns)) + ')',
                     [moved[c] for c in columns])
    if board and _has_table(conn, 'board_rows'):
        payload = json.loads(board['payload_json'])
        payload.update(attribution)
        payload['amount_krw'] = amount
        payload['merchant'] = keep_tx['merchant']
        if 'occurred_on' in payload:
            payload['occurred_on'] = occurred_on
        revision = board['revision'] + 1
        payload['revision'] = revision
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if _has_table(conn, 'board_revisions'):
            conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,'
                         'created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                         ('card-' + keep_tid, revision, board['payload_json'], encoded, '', 'rule_change', actor,
                          utc_now(), request_id))
        conn.execute('INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,?,?,?,?)',
                     ('card-' + keep_tid, board['row_kind'], attribution['display_tab_id'], revision, encoded))
    conn.execute('UPDATE transactions SET duplicate_of=?,revision=revision+1 WHERE transaction_id=?',
                 (keep_tid, dup_tid))
    _unbook(conn, dup_tid)
    return dict(keep_before=keep_before, dup_before=dup_before, ledger_action='move')


def mark_closed_duplicate(conn, billed_tid, approval_tid, *, request_id, period):
    """Closed (already submitted) period: keep the booked approval row exactly as
    it is and mark the incoming billed row a duplicate of it.

    The period's ledger is immutable (PROC-072 / REC-007), so the booked approval
    projection and its amount are left untouched — no move, no amount change. The
    billed total must never be added on top: every automatic booking path (P1
    classify, reconsider, P2, review-list recording) skips rows whose
    `duplicate_of` is set, so marking the billed row blocks them all. The pair is
    recorded as a closed-period review target with the same `closed`/`period`
    fields the cleanup apply logs, so one query over the release log surfaces
    closed pairs from both the import path and the cleanup tool.
    """
    before = _repair_state(conn, billed_tid)
    conn.execute('UPDATE transactions SET duplicate_of=?,revision=revision+1 WHERE transaction_id=?',
                 (approval_tid, billed_tid))
    detail = dict(request_id=request_id, keep=approval_tid, closed=True, period=period,
                  ledger_action='mark_only', amount_krw=before['transaction']['amount_krw'])
    conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                 (utc_now(), RELEASE, billed_tid, json.dumps(detail, ensure_ascii=False, sort_keys=True)))
    return dict(approval_before=_repair_state(conn, approval_tid), billed_before=before, ledger_action='mark_only')


def apply(conn, expected, *, request_id):
    if not request_id or conn.in_transaction:
        raise ValueError('HANA_REQUEST_OR_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        prior = replay(conn, request_id)
        if prior:
            if expected['digest'] != prior['digest']:
                raise ValueError('HANA_REQUEST_CONFLICT')
            conn.rollback()
            return dict(prior, replay=True, applied_this_run=0)
        current = preview(conn)
        if expected['digest'] != current['digest']:
            raise ValueError('HANA_PREVIEW_STALE')
        financial = _financial_state(conn)
        for target in current['targets']:
            # Closed-period pairs are preserved in preview (CLOSED_PERIOD), so every
            # target here is an open period: move the projection or unbook the dup.
            tid = target['tid']
            if target['ledger_action'] == 'move':
                move_approval_projection(conn, target['keep'], tid, request_id=request_id)
            else:
                conn.execute('UPDATE transactions SET duplicate_of=?,revision=revision+1 WHERE transaction_id=?',
                             (target['values']['duplicate_of'], tid))
                _unbook(conn, tid)
            detail = dict(request_id=request_id, keep=target['keep'], closed=target['closed'],
                          ledger_action=target['ledger_action'], keep_before=target['keep_before'],
                          before=target['before'], after=_state(conn, tid), financial=financial)
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                         (utc_now(), RELEASE, tid, json.dumps(detail, ensure_ascii=False, sort_keys=True)))
        if _financial_state(conn) != financial:
            raise ValueError('HANA_FINANCIAL_CHANGED')
        result = dict(current['summary'], applied_this_run=len(current['targets']))
        conn.execute('INSERT INTO requests(request_id,scope,payload_sha256,response_json,created_at) VALUES (?,?,?,?,?)',
                     (request_id, SCOPE, current['digest'], json.dumps(result, sort_keys=True), utc_now()))
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def restore_preview(conn, request_id):
    targets = []
    financial = _financial_state(conn)
    for entry, tid, raw in conn.execute('SELECT entry_id,subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id',
                                        (RELEASE,)):
        detail = json.loads(raw)
        if detail['request_id'] != request_id:
            continue
        if conn.execute("SELECT 1 FROM change_log WHERE kind=? AND json_extract(detail_json,'$.release_entry_id')=?",
                        (RESTORE, entry)).fetchone():
            continue
        if _state(conn, tid) != detail['after']:
            raise ValueError('HANA_RESTORE_STALE')
        if detail.get('financial', financial) != financial:
            raise ValueError('HANA_RESTORE_FINANCIAL_STALE')
        targets.append(dict(entry=entry, tid=tid, detail=detail))
    return dict(digest=_digest([targets, financial]), targets=targets, summary=dict(restore=len(targets)))


def restore(conn, expected, request_id):
    if conn.in_transaction:
        raise ValueError('HANA_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = restore_preview(conn, request_id)
        if current['digest'] != expected['digest']:
            raise ValueError('HANA_PREVIEW_STALE')
        financial = _financial_state(conn)
        for target in current['targets']:
            tid, detail = target['tid'], target['detail']
            before = detail['before']
            conn.execute('UPDATE transactions SET duplicate_of=?,revision=revision+1 WHERE transaction_id=?',
                         (before['transaction']['duplicate_of'], tid))
            if not detail['closed']:
                if detail.get('ledger_action') == 'move':
                    keep_tid = detail['keep']
                    _unbook(conn, keep_tid)
                    keep_tx = detail['keep_before']['transaction']
                    conn.execute('UPDATE transactions SET item=?,description=?,display_tab_id=?,trip_id=?,'
                                 'classification_state=?,classification_source=?,classification_basis=?,decided_at=?,'
                                 'revision=revision+1 WHERE transaction_id=?',
                                 (keep_tx['item'], keep_tx['description'], keep_tx['display_tab_id'], keep_tx['trip_id'],
                                  keep_tx['classification_state'], keep_tx['classification_source'],
                                  keep_tx['classification_basis'], keep_tx['decided_at'], keep_tid))
                _rebook(conn, tid, before)
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                         (utc_now(), RESTORE, tid,
                          json.dumps(dict(release_entry_id=target['entry'], request_id=request_id))))
        if _financial_state(conn) != financial:
            raise ValueError('HANA_FINANCIAL_CHANGED')
        conn.commit()
        return current['summary']
    except BaseException:
        conn.rollback()
        raise


def main(argv=None):
    """Offline CLI: count-only preview, backup-gated apply, audited restore.

    Run as `python -m app.card_hana_duplicate_repair`. The gate helpers live in
    tools/ and are imported here (not at module load) so the repair logic stays
    importable without the offline tooling.
    """
    import argparse
    from contextlib import closing
    from pathlib import Path
    import sqlite3

    from .db import StoreError
    from tools.complete_card_classification import require_offline_backup
    from tools.repair_dist141_provenance import emit_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    parser.add_argument('--backup-evidence', type=Path)
    parser.add_argument('--isolated-copy', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    host = args.host_root.resolve()
    db = host / 'data/board.sqlite'
    try:
        with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as reader:
            prior = replay(reader, args.request_id) if not args.restore else None
        if prior:
            if args.expected_digest and args.expected_digest != prior['digest']:
                raise ValueError('HANA_REQUEST_CONFLICT')
            return emit_report(dict(prior, status='REPLAYED', replay=True, applied_this_run=0, to_mark=0), args.report)
        if args.apply:
            if not args.expected_digest or not args.backup_evidence:
                raise ValueError('PREVIEW_AND_BACKUP_REQUIRED')
            require_offline_backup(host, args.backup_evidence, db, isolated_copy=args.isolated_copy)
        with closing(sqlite3.connect(db.as_uri() + '?mode=' + ('rw' if args.apply else 'ro'),
                                     uri=True, isolation_level=None)) as conn:
            plan = restore_preview(conn, args.request_id) if args.restore else preview(conn)
            if args.apply and plan['digest'] != args.expected_digest:
                raise ValueError('HANA_PREVIEW_STALE')
            # Preview never runs a repair, even on an in-memory database.
            result = (restore(conn, plan, args.request_id) if args.restore else
                      apply(conn, plan, request_id=args.request_id)) if args.apply else plan['summary']
            report = dict(status='APPLIED' if args.apply else 'PREVIEW', digest=plan['digest'], **result)
        return emit_report(report, args.report)
    except (OSError, ValueError, KeyError, sqlite3.Error, StoreError) as exc:
        code = (exc.code if isinstance(exc, StoreError) else str(exc)
                if isinstance(exc, ValueError) and str(exc).replace('_', '').isalnum() else type(exc).__name__)
        print(json.dumps(dict(status='FAILED', code=code)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
