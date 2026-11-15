"""Tool-written overrides are not manual, and recorded booking rows follow a changed evidence digest (TRIP-033/036)."""
import json

import pytest

from app.closed_period import manual_ids
from webapp.tests.test_automatic_classification_completion import setup  # noqa: F401


def _record(setup, monkeypatch, *, item='숙박비'):
    board, flow, batch, rows = setup
    first = board.create_trip(starts_on='2026-10-01', ends_on='2026-10-05',
                              destination='Payment', client_request_id='payment')['tab_id']
    second = board.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                               destination='Stay', client_request_id='stay')['tab_id']
    monkeypatch.setattr(flow, 'trip_valid', lambda _tab, include_archived=False: True)
    tid = rows[0]['transaction_id']
    c = board.conn
    c.execute("UPDATE transactions SET classification_state='classified',classification_source='inference',"
              "item=?,trip_id=?,display_tab_id=? WHERE transaction_id=?", (item, first, first, tid))
    preview = flow.pipeline.preview(batch, trip_validator=lambda _: True, tab_validator=lambda _: True)
    flow.pipeline.commit(batch, preview['digest'], 'record', trip_validator=lambda _: True,
                         tab_validator=lambda _: True, projection=flow.project)
    c.commit()
    return board, flow, rows[0], first, second


def _snapshot(flow, monkeypatch, row, period, additional=()):
    event = dict(ota_event_id='booking', event_type='charge', payment_status='paid', evidence_status='paid_verified')
    current = {'data': {'events': [event]}, 'generation': 1}
    facts = [dict(transaction_id=entry['transaction_id'], source_hash=entry['source_hash'],
                  source_sha256='a' * 64, ota_event_id='booking', item='숙박비',
                  reservation_status='confirmed', period=period) for entry in (row, *additional)]
    monkeypatch.setattr(flow, '_held_ota_snapshot', lambda: (current, True))
    monkeypatch.setattr(flow, '_canonical_snapshot_report', lambda _: {'matches': facts})
    return current


def _tool_save(board, row_id, tab, actor):
    from webapp import ledger_board
    ledger_board.bind_store(board)
    try:
        _save(board, row_id, tab, actor)
    finally:
        ledger_board.bind_store(None)


def _save(board, row_id, tab, actor):
    revision = board.conn.execute('SELECT revision FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0]
    board.save(row_id=row_id, expected_revision=revision, client_request_id='save-' + actor,
               change_mode='exception', changes={'display_tab_id': tab}, actor=actor)


def _trip(conn, tid):
    return (conn.execute('SELECT trip_id FROM transactions WHERE transaction_id=?', (tid,)).fetchone()[0],
            conn.execute('SELECT trip_id FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()[0],
            conn.execute('SELECT display_tab_id FROM board_rows WHERE row_id=?', ('card-' + tid,)).fetchone()[0])


def test_tool_save_leaves_no_manual_override_and_old_tool_records_are_not_manual(setup, monkeypatch):
    board, flow, row, first, second = _record(setup, monkeypatch)
    tid, row_id = row['transaction_id'], 'card-' + row['transaction_id']
    _tool_save(board, row_id, second, 'authority-review-20261016')
    assert board.conn.execute('SELECT COUNT(*) FROM board_manual_overrides').fetchone()[0] == 0
    # A record left by an earlier tool save is preserved but not manual.
    event = board.conn.execute('SELECT event_id FROM board_revisions WHERE row_id=? ORDER BY revision DESC',
                               (row_id,)).fetchone()[0] or 'tool-event'
    board.conn.execute("UPDATE board_revisions SET event_id=? WHERE row_id=? AND actor='authority-review-20261016'",
                       (event, row_id))
    board.conn.execute("INSERT INTO board_manual_overrides VALUES (?,'display_tab_id',?)", (row_id, event))
    assert tid not in manual_ids(board.conn)
    assert board.manual_locked_fields(row_id) == set()
    # A person's save is manual.
    _tool_save(board, row_id, first, 'owner')
    assert board.manual_locked_fields(row_id) == {'display_tab_id'} and tid in manual_ids(board.conn)


def test_unknown_override_history_stays_manual(setup, monkeypatch):
    board, _, row, _, _ = _record(setup, monkeypatch)
    board.conn.execute("INSERT INTO board_manual_overrides VALUES (?,'display_tab_id','no-such-event')",
                       ('card-' + row['transaction_id'],))
    assert row['transaction_id'] in manual_ids(board.conn)


def test_sync_rows_update_a_tool_override_but_not_a_person_override(setup, monkeypatch):
    board, flow, row, first, second = _record(setup, monkeypatch)
    row_id = 'card-' + row['transaction_id']
    _tool_save(board, row_id, second, 'authority-review-20261016')
    event = 'tool-event'
    board.conn.execute("UPDATE board_revisions SET event_id=? WHERE row_id=? AND actor='authority-review-20261016'",
                       (event, row_id))
    board.conn.execute("INSERT INTO board_manual_overrides VALUES (?,'display_tab_id',?)", (row_id, event))
    board.conn.commit()
    from webapp import ledger_board
    ledger_board.bind_store(board)
    try:
        flow.sync_ledger_rows()
    finally:
        ledger_board.bind_store(None)
    assert board.conn.execute('SELECT display_tab_id FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0] == first


@pytest.mark.parametrize('protection', ['', 'owner_override', 'hold', 'refund_pair', 'refund_tab', 'user_decision',
                                        'archived_source'])
def test_changed_digest_moves_recorded_row_atomically_and_unchanged_digest_writes_nothing(
        setup, monkeypatch, protection):
    from webapp import booking_period_rejudge as rejudge
    board, flow, row, first, second = _record(setup, monkeypatch)
    tid, c = row['transaction_id'], board.conn
    # The calendar guess is kept by a tool-written override: it must not block the correction.
    c.execute("INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,"
              "client_request_id) VALUES (?,99,'{}','{}','tool-e','exception','authority-review-20261016','t','x')",
              ('card-' + tid,))
    c.execute("INSERT INTO board_manual_overrides VALUES (?,'display_tab_id','tool-e')", ('card-' + tid,))
    if protection == 'owner_override':
        c.execute("UPDATE board_revisions SET actor='owner' WHERE event_id='tool-e'")
    elif protection == 'hold':
        c.execute("INSERT INTO transaction_review_holds VALUES (?,?,'user_hold','hold')", (tid, row['source_hash']))
    elif protection == 'refund_pair':
        other = setup[3][1]['transaction_id']
        c.execute("UPDATE transactions SET transaction_direction='cancellation',original_approval_number=?,issuer=?,"
                  "card_tail=? WHERE transaction_id=?", (row['approval_number'], row['issuer'], row['card_tail'], other))
    elif protection == 'user_decision':
        c.execute("UPDATE transactions SET classification_source='user_decision' WHERE transaction_id=?", (tid,))
    elif protection == 'refund_tab':
        c.execute("UPDATE board_rows SET display_tab_id='refunds' WHERE row_id=?", ('card-' + tid,))
    elif protection == 'archived_source':
        c.execute('UPDATE trip_tabs SET archived=1 WHERE tab_id=?', (first,))
    c.commit()
    current = _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-02', ends_on='2026-10-04'))
    # First generation: the digest is only a baseline; the row does not move.
    assert rejudge.rejudge(flow, current, request_id='g1')['corrected'] == 0
    assert _trip(c, tid)[:2] == (first, first)
    # Reading again with the same evidence writes nothing.
    changes = c.total_changes
    assert rejudge.rejudge(flow, current, request_id='g2')['corrected'] == 0
    assert c.total_changes == changes
    # New evidence: the stay is in the second trip.
    current = _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-11', ends_on='2026-10-12'))
    raw = c.execute('SELECT source_hash,raw_row_json,amount_krw,approval_date FROM transactions WHERE transaction_id=?',
                    (tid,)).fetchone()
    result = rejudge.rejudge(flow, current, request_id='g3')
    if protection:
        assert result['corrected'] == 0 and _trip(c, tid)[:2] == (first, first)
        return
    assert result['corrected'] == 1 and _trip(c, tid) == (second, second, second)
    assert raw == c.execute('SELECT source_hash,raw_row_json,amount_krw,approval_date FROM transactions'
                            ' WHERE transaction_id=?', (tid,)).fetchone()
    payload, revision = c.execute('SELECT payload_json,revision FROM board_rows WHERE row_id=?',
                                  ('card-' + tid,)).fetchone()
    assert json.loads(payload)['revision'] == revision
    detail = json.loads(c.execute("SELECT detail_json FROM change_log WHERE kind='card.booking_trip_correction'")
                        .fetchone()[0])
    assert detail['before']['transaction']['trip_id'] == first and detail['after']['trip_id'] == second
    assert c.execute("SELECT COUNT(*) FROM board_manual_overrides WHERE event_id='tool-e'").fetchone()[0] == 1
    assert rejudge.rejudge(flow, current, request_id='g4')['corrected'] == 0


def test_rejudge_rolls_back_every_projection_on_failure(setup, monkeypatch):
    from webapp import booking_period_rejudge as rejudge
    board, flow, row, first, second = _record(setup, monkeypatch)
    tid, c = row['transaction_id'], board.conn
    rejudge.rejudge(flow, _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-02', ends_on='2026-10-04')),
                    request_id='g1')
    c.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON change_log WHEN NEW.kind='card.booking_trip_correction'"
              " BEGIN SELECT RAISE(ABORT,'audit failed'); END")
    current = _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-11', ends_on='2026-10-12'))
    with pytest.raises(Exception, match='audit failed'):
        rejudge.rejudge(flow, current, request_id='g2')
    assert _trip(c, tid) == (first, first, first)
    assert c.execute("SELECT COUNT(*) FROM board_revisions WHERE client_request_id LIKE 'g2:%'").fetchone()[0] == 0


def test_tool_moves_only_non_overlapping_rows_into_archived_trips_idempotently_and_reverts(
        setup, monkeypatch, tmp_path):
    from tools import correct_booking_trips as tool
    board, flow, row, first, second = _record(setup, monkeypatch)
    tid, c = row['transaction_id'], board.conn
    c.execute('UPDATE trip_tabs SET archived=1 WHERE tab_id=?', (second,))
    c.commit()
    current = _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-11', ends_on='2026-10-12'))
    monkeypatch.setattr(tool, 'flow_for', lambda conn, host, cur: flow)
    out = tmp_path / 'private'
    report, targets, _ = tool.preview(c, tmp_path, current, out)
    assert report['counts']['non_overlap'] == 1 and report['counts']['to_archived'] == 1
    assert _trip(c, tid) == (first, first, first)  # preview writes nothing
    with pytest.raises(tool.Refused, match='PREVIEW_STALE'):
        tool.apply(c, tmp_path, current, out, request_id='r0', expected_digest='0' * 64)
    result = tool.apply(c, tmp_path, current, out, request_id='r1', expected_digest=report['digest'])
    assert result['written'] == 1 and _trip(c, tid) == (second, second, second)
    replay = tool.apply(c, tmp_path, current, out, request_id='r1', expected_digest=report['digest'])
    assert replay['written'] == 0 and replay['transaction_ids'] is None
    again, _, _ = tool.preview(c, tmp_path, current, out)
    assert again['counts']['non_overlap'] == 0
    index = json.loads((out / 'applied-paste' / 'paste-index.json').read_text(encoding='utf-8'))
    assert {(e['side'], e['tab_id'], e['rows']) for e in index} == {('add', second, 1), ('remove', first, 1)}
    assert tool.revert(c, out, applied_id='r1', request_id='u1')['written'] == 1
    assert _trip(c, tid) == (first, first, first)
    assert tool.revert(c, out, applied_id='r1', request_id='u1')['written'] == 0


def test_revert_preserves_same_trip_owner_item_and_description_save(setup, monkeypatch, tmp_path):
    from tools import correct_booking_trips as tool
    board, flow, row, first, second = _record(setup, monkeypatch)
    tid, row_id, c = row['transaction_id'], 'card-' + row['transaction_id'], board.conn
    current = _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-11', ends_on='2026-10-12'))
    monkeypatch.setattr(tool, 'flow_for', lambda conn, host, cur: flow)
    report, _, _ = tool.preview(c, tmp_path, current, tmp_path / 'private')
    tool.apply(c, tmp_path, current, tmp_path / 'private', request_id='same-trip-apply',
               expected_digest=report['digest'])

    revision = c.execute('SELECT revision FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0]
    from webapp import ledger_board
    ledger_board.bind_store(board)
    try:
        saved = board.save(row_id=row_id, expected_revision=revision, client_request_id='same-trip-owner-save',
                           change_mode='exception',
                           changes={'display_tab_id': second, 'item': '주차비', 'description': '사용자 설명'},
                           actor='owner')
    finally:
        ledger_board.bind_store(None)
    assert saved['outcome'] == 'saved'
    assert board.manual_locked_fields(row_id) == {'item', 'description'}
    after_owner_payload = json.loads(c.execute('SELECT payload_json FROM board_rows WHERE row_id=?',
                                               (row_id,)).fetchone()[0])

    result = tool.revert(c, tmp_path, applied_id='same-trip-apply', request_id='same-trip-revert')
    assert result['written'] == 1
    assert _trip(c, tid) == (first, first, first)
    reverted = json.loads(c.execute('SELECT payload_json FROM board_rows WHERE row_id=?', (row_id,)).fetchone()[0])
    assert reverted['item'] == after_owner_payload['item'] == '주차비'
    assert reverted['description'] == after_owner_payload['description'] == '사용자 설명'
    assert board.manual_locked_fields(row_id) == {'item', 'description'}
    detail = json.loads(c.execute("SELECT detail_json FROM change_log WHERE kind='card.booking_trip_correction'"
                                  " AND json_extract(detail_json,'$.request_id')='same-trip-apply'").fetchone()[0])
    assert detail['changed_fields']['transaction'].keys() == {'display_tab_id', 'trip_id', 'classification_basis'}
    assert set(detail['changed_fields']['board_payload']) == {'display_tab_id', 'classification_basis'}


def test_revert_refuses_changed_source_hash_without_writing(setup, monkeypatch, tmp_path):
    from tools import correct_booking_trips as tool
    board, flow, row, first, second = _record(setup, monkeypatch)
    tid, c = row['transaction_id'], board.conn
    current = _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-11', ends_on='2026-10-12'))
    monkeypatch.setattr(tool, 'flow_for', lambda conn, host, cur: flow)
    report, _, _ = tool.preview(c, tmp_path, current, tmp_path / 'private')
    tool.apply(c, tmp_path, current, tmp_path / 'private', request_id='hash-apply',
               expected_digest=report['digest'])
    c.execute('UPDATE transactions SET source_hash=?, revision=revision+1 WHERE transaction_id=?',
              ('changed-source-hash', tid))
    c.commit()
    before_revert_events = c.execute("SELECT count(*) FROM change_log WHERE kind='card.booking_trip_correction_revert'").fetchone()[0]

    with pytest.raises(tool.Refused, match='SOURCE_CHANGED_SINCE_APPLY'):
        tool.revert(c, tmp_path, applied_id='hash-apply', request_id='hash-revert')
    assert _trip(c, tid) == (second, second, second)
    assert c.execute("SELECT count(*) FROM change_log WHERE kind='card.booking_trip_correction_revert'").fetchone()[0] == before_revert_events
    assert c.execute("SELECT count(*) FROM requests WHERE scope=? AND request_id=?",
                      (tool.REQUEST_SCOPE, 'booking-trip-correction:hash-revert')).fetchone()[0] == 0


def test_multirow_revert_refuses_one_stale_row_atomically(setup, monkeypatch, tmp_path):
    from tools import correct_booking_trips as tool
    board, flow, first_row, first, second = _record(setup, monkeypatch)
    c = board.conn
    second_row = setup[3][1]
    second_tid = second_row['transaction_id']
    c.execute("UPDATE transactions SET classification_state='classified',classification_source='inference',"
              "classification_basis='synthetic',item='숙박비',trip_id=?,display_tab_id=?,revision=revision+1 "
              "WHERE transaction_id=?", (first, first, second_tid))
    board_row_id = 'card-' + second_tid
    source = c.execute('SELECT source_hash,amount_krw,merchant FROM transactions WHERE transaction_id=?',
                       (second_tid,)).fetchone()
    columns = [column[1] for column in c.execute('PRAGMA table_info(ledger_entries)')]
    original_ledger = c.execute('SELECT * FROM ledger_entries WHERE transaction_id=?',
                                (first_row['transaction_id'],)).fetchone()
    assert original_ledger is not None
    ledger_values = dict(zip(columns, original_ledger))
    ledger_values.update(transaction_id=second_tid, item='숙박비', display_tab_id=first, trip_id=first,
                         source_hash=source[0])
    c.execute('INSERT INTO ledger_entries(' + ','.join(columns) + ') VALUES (' +
              ','.join('?' for _ in columns) + ')', [ledger_values[column] for column in columns])
    original_payload = c.execute('SELECT payload_json FROM board_rows WHERE row_id=?',
                                 ('card-' + first_row['transaction_id'],)).fetchone()
    assert original_payload is not None
    payload = json.loads(original_payload[0])
    payload.update(row_id=board_row_id, item='숙박비', display_tab_id=first,
                   source_event_id=second_tid, source_fact_digest=source[0],
                   amount_krw=source[1], source_merchant=source[2], revision=1)
    c.execute('INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,?,?,?,?)',
              (board_row_id, 'expense', first, 1, json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    c.commit()

    current = _snapshot(flow, monkeypatch, first_row, dict(starts_on='2026-10-11', ends_on='2026-10-12'),
                        additional=(second_row,))
    monkeypatch.setattr(tool, 'flow_for', lambda conn, host, cur: flow)
    report, targets, _ = tool.preview(c, tmp_path, current, tmp_path / 'private')
    assert len(targets) == 2
    tool.apply(c, tmp_path, current, tmp_path / 'private', request_id='multi-apply',
               expected_digest=report['digest'])
    target_ids = [record['transaction_id'] for record in targets]
    stale_tid = target_ids[-1]
    c.execute('UPDATE transactions SET source_hash=?,revision=revision+1 WHERE transaction_id=?',
              ('changed-late-row', stale_tid))
    c.commit()
    assert all(_trip(c, tid) == (second, second, second) for tid in target_ids)

    with pytest.raises(tool.Refused, match='SOURCE_CHANGED_SINCE_APPLY'):
        tool.revert(c, tmp_path, applied_id='multi-apply', request_id='multi-revert')
    assert all(_trip(c, tid) == (second, second, second) for tid in target_ids)
    assert c.execute("SELECT count(*) FROM change_log WHERE kind='card.booking_trip_correction_revert'").fetchone()[0] == 0


def test_tool_lists_overlapping_differences_for_review_without_moving_them(setup, monkeypatch, tmp_path):
    from tools import correct_booking_trips as tool
    board, flow, row, first, second = _record(setup, monkeypatch)
    c = board.conn
    # The stay shares nights with both trips; the second covers more, the first overlaps.
    c.execute("UPDATE trip_tabs SET ends_on='2026-10-11' WHERE tab_id=?", (first,))
    c.commit()
    current = _snapshot(flow, monkeypatch, row, dict(starts_on='2026-10-10', ends_on='2026-10-13'))
    monkeypatch.setattr(tool, 'flow_for', lambda conn, host, cur: flow)
    report, targets, _ = tool.preview(c, tmp_path, current, tmp_path / 'private')
    assert targets == [] and report['counts']['overlap_differs'] == 1
    assert json.loads((tmp_path / 'private' / 'review-list.json').read_text(encoding='utf-8'))[0]['chosen_trip'] == second


def test_owner_change_later_overwritten_by_a_tool_stays_manual(setup, monkeypatch):
    board, _, row, first, second = _record(setup, monkeypatch)
    row_id = 'card-' + row['transaction_id']
    c = board.conn
    c.execute("INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,"
              "client_request_id) VALUES (?,50,?,?,'o1','exception','owner','t','o')",
              (row_id, json.dumps({'display_tab_id': first}), json.dumps({'display_tab_id': second})))
    c.execute("INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,"
              "client_request_id) VALUES (?,51,'{}','{}','t1','exception','authority-review-20261016','t','t')",
              (row_id,))
    c.execute("INSERT INTO board_manual_overrides VALUES (?,'display_tab_id','t1')", (row_id,))
    assert row['transaction_id'] in manual_ids(c)
    assert board.manual_locked_fields(row_id) == {'display_tab_id'}
