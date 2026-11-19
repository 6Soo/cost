"""Narrow, reversible correction of the dist141 automatic batch's provenance.

Review decisions remain immutable evidence. Only the exact audited revisions
cease to act as manual decisions; later human revisions are always protected.
"""
from __future__ import annotations

import hashlib
import json

from .db import utc_now
from .manual_overrides import exists_sql as manual_exists_sql

RELEASE = 'card.dist141_provenance_corrected'
RESTORE = 'card.dist141_provenance_restored'
AUTOMATIC_SOURCES = {'inference','code_inference','ai_inference','refund_original','rule',
                     'pattern','card_category','owner_card_residual','booking_evidence_needed'}


def active_decision_sql(alias='d', *, conn=None):
    # Older read-only projections have no audit structure. All their decisions
    # remain protected; absence of provenance is never permission to release.
    if conn is not None and not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='change_log'").fetchone():
        return '1=1'
    return f"""NOT EXISTS (
        SELECT 1 FROM change_log p WHERE p.kind='{RELEASE}'
        AND p.subject={alias}.transaction_id
        AND json_extract(p.detail_json,'$.decision_revision')={alias}.revision
        AND NOT EXISTS (SELECT 1 FROM change_log r WHERE r.kind='{RESTORE}'
            AND r.subject=p.subject
            AND json_extract(r.detail_json,'$.release_entry_id')=p.entry_id))"""


def closed_review_required(conn, tid):
    return bool(conn.execute(f"""SELECT 1 FROM change_log p WHERE p.kind=? AND p.subject=?
        AND json_extract(p.detail_json,'$.opened')=0 AND NOT EXISTS (
        SELECT 1 FROM change_log r WHERE r.kind=? AND r.subject=p.subject
        AND json_extract(r.detail_json,'$.release_entry_id')=p.entry_id)""", (RELEASE,tid,RESTORE)).fetchone())


def closed_review_ids(conn):
    return {row[0] for row in conn.execute(f"""SELECT p.subject FROM change_log p
        WHERE p.kind='{RELEASE}' AND json_extract(p.detail_json,'$.opened')=0
        AND NOT EXISTS (SELECT 1 FROM change_log r WHERE r.kind='{RESTORE}'
        AND r.subject=p.subject AND json_extract(r.detail_json,'$.release_entry_id')=p.entry_id)""")}


def _dict_row(conn, table, key, value):
    cursor = conn.execute(f'SELECT * FROM {table} WHERE {key}=?', (value,))
    row = cursor.fetchone()
    return dict(zip((d[0] for d in cursor.description), row)) if row else None


def _state(conn, tid):
    return dict(transaction=_dict_row(conn, 'transactions', 'transaction_id', tid),
                ledger=_dict_row(conn, 'ledger_entries', 'transaction_id', tid),
                board=_dict_row(conn, 'board_rows', 'row_id', 'card-'+tid))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preview(conn, trips, *, nets=None, evidence=None):
    from .classification_correction import _open_p2_tab
    targets, seen = [], set()
    requests = conn.execute("SELECT request_id,response_json FROM requests "
                            "WHERE scope='save_decision' AND request_id GLOB 'dist141-*' ORDER BY request_id")
    for request, raw in requests:
        response = json.loads(raw)
        tid = response.get('transaction_id')
        if not tid or tid in seen or not response.get('note', '').startswith('낮은 확신 분배'):
            continue
        seen.add(tid)
        state = _state(conn, tid)
        row = state['transaction']
        decision = conn.execute('SELECT revision,item,description,display_tab_id,note,decided_at '
            'FROM review_decisions WHERE transaction_id=? ORDER BY revision DESC LIMIT 1', (tid,)).fetchone()
        if (not row or not decision or row['classification_source'] not in AUTOMATIC_SOURCES | {'user_decision'}
                or row['source_hash'] != response.get('source_hash')
                or tuple(decision) != tuple(response.get(k) for k in
                    ('revision','item','description','display_tab_id','note','decided_at'))
                # Automated authority/projection repairs may advance the row
                # revision or trip without recording a new human decision.
                # Human saves create a newer decision/decided_at or override.
                or row['decided_at'] not in (None,response.get('decided_at'))
                or row['classification_source'] == 'user_decision'
                and any(row[k] != response.get(k) for k in ('item','description'))
                or conn.execute('SELECT ' + manual_exists_sql(conn, '?'), ('card-'+tid,)).fetchone()[0]):
            continue
        opened = _open_p2_tab(trips, row['display_tab_id'] or row['trip_id'])
        targets.append(dict(transaction_id=tid, original_request=request,
                            decision_revision=decision[0], opened=opened, before=state))
    inputs = dict(targets=targets, trips=trips, nets=nets or {}, evidence=evidence or {})
    return dict(digest=_digest(inputs), targets=targets, summary=dict(
        identified=len(seen), eligible=len(targets), excluded=len(seen)-len(targets),
        open=sum(t['opened'] for t in targets), closed=sum(not t['opened'] for t in targets)))


def _sync_projection(conn, tid, row, request_id, *, attribution_changed):
    """Existing rows only; use existing board revision and audit structures."""
    if attribution_changed:
        conn.execute('UPDATE ledger_entries SET item=?,description=?,display_tab_id=?,trip_id=? WHERE transaction_id=?',
            (row['item'],row['description'],row['display_tab_id'],row['trip_id'],tid))
        # M6: 통합 장부에도 같은 값을 쓴다. 귀속이 바뀐 경우에만 반영한다.
        from .ledger import sync_ledger_row
        sync_ledger_row(conn, tid, item=row['item'], description=row['description'],
                        display_tab_id=row['display_tab_id'], trip_id=row['trip_id'])
    board = _dict_row(conn, 'board_rows', 'row_id', 'card-'+tid)
    if not board:
        return
    payload = json.loads(board['payload_json'])
    for key in ('item','description','display_tab_id','trip_id','classification_state',
                'classification_source','classification_basis','decided_at'):
        if key in ('item','description','display_tab_id','trip_id') and not attribution_changed:
            continue
        if key in payload or key in ('classification_source','classification_basis'):
            payload[key] = row[key]
    payload['confirmed_by'] = 'automatic'
    payload['revision'] = board['revision']+1
    encoded = json.dumps(payload,ensure_ascii=False,sort_keys=True)
    conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) '
        'VALUES (?,?,?,?,?,?,?,?,?)', ('card-'+tid,board['revision']+1,board['payload_json'],encoded,
        '', 'rule_change','automatic',utc_now(),request_id))
    conn.execute('UPDATE board_rows SET payload_json=?,display_tab_id=?,revision=revision+1 WHERE row_id=?',
                 (encoded,row['display_tab_id'] if attribution_changed else board['display_tab_id'],'card-'+tid))


def apply(conn, expected, trips, *, request_id, nets=None, evidence=None):
    from . import automatic_classification as p1
    if not request_id or conn.in_transaction:
        raise ValueError('PROVENANCE_REQUEST_OR_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        replay = conn.execute("SELECT payload_sha256,response_json FROM requests WHERE request_id=? AND scope='dist141_provenance'", (request_id,)).fetchone()
        if replay:
            if replay[0] != expected['digest']:
                raise ValueError('PROVENANCE_REQUEST_CONFLICT')
            conn.rollback()
            return dict(json.loads(replay[1]), replay=True)
        current = preview(conn,trips,nets=nets,evidence=evidence)
        if current['digest'] != expected['digest']:
            raise ValueError('PROVENANCE_PREVIEW_STALE')
        entries = {}
        for target in current['targets']:
            tid = target['transaction_id']
            original = target['before']['transaction']
            source = 'inference' if original['classification_source']=='user_decision' else original['classification_source']
            basis = 'CODE_INFERRED · dist141 automatic batch · PROC-014/015 · 사용자 결정 2026-11-12'
            if original['classification_source'] != 'user_decision':
                basis = original['classification_basis']+' · '+basis
            if not target['opened']:
                basis += ' · CLOSED_QUARTER_REVIEW_REQUIRED'
            conn.execute("UPDATE transactions SET classification_source=?,classification_basis=?,"
                         'decided_at=NULL,revision=revision+1 WHERE transaction_id=?', (source,basis,tid))
            detail = dict(request_id=request_id, decision_revision=target['decision_revision'],
                          original_request=target['original_request'], before=target['before'],
                          opened=target['opened'])
            cursor = conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(),RELEASE,tid,json.dumps(detail,ensure_ascii=False,sort_keys=True)))
            entries[tid] = (cursor.lastrowid,detail)
        selected = {t['transaction_id'] for t in current['targets'] if t['opened']}
        if selected:
            options = dict(nets=nets, evidence=evidence, transaction_ids=selected, reconsider=True)
            plan = p1.plan(conn,trips,**options)
            p1.apply(conn,plan,trips,**options)
        changed = 0
        for target in current['targets']:
            tid = target['transaction_id']
            after = _dict_row(conn,'transactions','transaction_id',tid)
            before = target['before']['transaction']
            attribution_changed = any(before[k] != after[k] for k in ('item','trip_id','display_tab_id'))
            changed += attribution_changed
            # Classification writes respect the P1 protections; the provenance
            # repair itself never changes a closed quarter's attribution/item.
            _sync_projection(conn,tid,after,request_id,attribution_changed=attribution_changed)
            entry, detail = entries[tid]
            detail['after'] = _state(conn,tid)
            conn.execute('UPDATE change_log SET detail_json=? WHERE entry_id=?',
                         (json.dumps(detail,ensure_ascii=False,sort_keys=True),entry))
        result = dict(current['summary'], attribution_or_item_changed=changed, replay=False)
        conn.execute('INSERT INTO requests(request_id,scope,payload_sha256,response_json,created_at) VALUES (?,?,?,?,?)',
            (request_id,'dist141_provenance',expected['digest'],json.dumps(result),utc_now()))
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def restore_preview(conn, request_id):
    targets = []
    for entry, tid, raw in conn.execute('SELECT entry_id,subject,detail_json FROM change_log WHERE kind=? ORDER BY entry_id', (RELEASE,)):
        detail = json.loads(raw)
        if detail['request_id'] != request_id:
            continue
        if conn.execute("SELECT 1 FROM change_log WHERE kind=? AND json_extract(detail_json,'$.release_entry_id')=?", (RESTORE,entry)).fetchone():
            continue
        if _state(conn,tid) != detail['after']:
            raise ValueError('PROVENANCE_RESTORE_STALE')
        targets.append(dict(entry=entry,tid=tid,detail=detail))
    return dict(digest=_digest(targets),targets=targets,summary=dict(restore=len(targets)))


def restore(conn, expected, request_id):
    if conn.in_transaction:
        raise ValueError('PROVENANCE_TRANSACTION_INVALID')
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = restore_preview(conn,request_id)
        if current['digest'] != expected['digest']:
            raise ValueError('PROVENANCE_PREVIEW_STALE')
        for target in current['targets']:
            tid, detail = target['tid'], target['detail']
            old = detail['before']['transaction']
            from .automatic_classification import FIELDS
            keys = (*FIELDS,'decided_at')
            conn.execute('UPDATE transactions SET '+','.join(k+'=?' for k in keys)+',revision=revision+1 WHERE transaction_id=?',
                         (*[old[k] for k in keys],tid))
            # Restore projection values while retaining monotonic revisions/history.
            if detail['before']['ledger']:
                ledger = detail['before']['ledger']
                conn.execute('UPDATE ledger_entries SET item=?,description=?,display_tab_id=?,trip_id=? WHERE transaction_id=?',
                    (ledger['item'],ledger['description'],ledger['display_tab_id'],ledger['trip_id'],tid))
                # M6: 되돌리기도 통합 장부까지 함께 되돌린다.
                from .ledger import sync_ledger_row
                sync_ledger_row(conn, tid, item=ledger['item'], description=ledger['description'],
                                display_tab_id=ledger['display_tab_id'], trip_id=ledger['trip_id'])
            board = detail['before']['board']
            if board:
                now = _dict_row(conn,'board_rows','row_id','card-'+tid)
                payload = json.loads(board['payload_json'])
                payload['revision'] = now['revision']+1
                encoded = json.dumps(payload,ensure_ascii=False,sort_keys=True)
                conn.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id) VALUES (?,?,?,?,?,?,?,?,?)',
                    ('card-'+tid,now['revision']+1,now['payload_json'],encoded,'','rule_change','automatic',utc_now(),'restore-'+request_id))
                conn.execute('UPDATE board_rows SET payload_json=?,display_tab_id=?,revision=revision+1 WHERE row_id=?',
                    (encoded,board['display_tab_id'],'card-'+tid))
            conn.execute('INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)',
                (utc_now(),RESTORE,tid,json.dumps(dict(release_entry_id=target['entry'],request_id=request_id))))
        conn.commit()
        return current['summary']
    except BaseException:
        conn.rollback()
        raise
