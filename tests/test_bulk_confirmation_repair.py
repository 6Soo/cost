import json
import sqlite3

import pytest

from app import ai_review_repair
from app import bulk_confirmation_repair as repair
from webapp.tests.test_automatic_classification_completion import setup, TRIPS

YEAR, QUARTER = 2026, 4
MINUTE = '2026-10-05T03:12'
Q3_TRIPS = TRIPS + [dict(trip_id='C', starts_on='2026-07-05', ends_on='2026-07-09')]


def prepare(c):
    c.execute("UPDATE transactions SET approval_date='2026-10-03',classification_state='classified',"
              "classification_source='inference',item='식비',trip_id='A',display_tab_id='A',"
              "classification_basis='AUTO_INFERRED · 합성 추론',decided_at=NULL")
    c.commit()


def add_owner_row(c, tid, *, minute=MINUTE, shape='batch'):
    row = repair._state(c, tid)['transaction']
    payload = dict(item=row['item'], description='synthetic', display_tab_id=row['display_tab_id'],
                   trip_id=row['trip_id'], classification_state=row['classification_state'],
                   classification_source=row['classification_source'], confirmed_by='owner', revision=1)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    row_id = 'card-' + tid
    c.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense',?,1,?)",
              (row_id, row['display_tab_id'], encoded))
    stamp = dict(event_id='', change_mode='exception', actor='owner', kind='save', confirmed_by='owner')
    if shape == 'event':
        stamp['event_id'] = 'synthetic-event'
    elif shape == 'edit':
        stamp['change_mode'] = 'edit'
    elif shape == 'rule':
        stamp['change_mode'], stamp['actor'] = 'rule_change', 'automatic'
    elif shape == 'conflict':
        stamp['kind'] = 'conflict'
    elif shape == 'automatic_only':
        stamp['confirmed_by'] = 'automatic'
    if shape != 'none':
        new_json = json.dumps(dict(payload, confirmed_by=stamp['confirmed_by']), ensure_ascii=False, sort_keys=True)
        c.execute('INSERT INTO board_revisions(row_id,revision,prev_json,new_json,event_id,change_mode,actor,created_at,client_request_id,kind) '
                  'VALUES (?,1,?,?,?,?,?,?,?,?)',
                  (row_id, '{}', new_json, stamp['event_id'], stamp['change_mode'], stamp['actor'],
                   minute + ':00+00:00', row_id, stamp['kind']))
    c.commit()


def add_ledger(c, tid):
    row = repair._state(c, tid)['transaction']
    c.execute('INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,'
              'amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
              (tid, 'synthetic-batch', row['item'], 'synthetic', row['display_tab_id'], row['trip_id'],
               row['amount_krw'], row['merchant'], row['approval_date'], row['transaction_direction'],
               row['source_hash'], 'synthetic'))
    c.commit()


def stamp_all(c, tids, **kwargs):
    for tid in tids:
        add_owner_row(c, tid, **kwargs)


def test_bulk_stamp_corrected(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    assert plan['summary']['owner_stamped_rows'] == 5
    assert plan['summary']['to_correct'] == 5
    assert plan['summary']['excluded'] == {}
    assert plan['summary']['stamp_minutes'] == [dict(minute=MINUTE, rows=5, batch_size=5)]
    assert plan['summary']['trip_corrections'] == [dict(trip='A', count=5)]
    financial = repair._financial_state(c)
    transactions_before = c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    result = repair.apply(c, plan, TRIPS, request_id='synthetic-bulk', year=YEAR, quarter=QUARTER)
    assert result['applied_this_run'] == 5 and result['replay'] is False
    for tid in tids:
        state = repair._state(c, tid)
        payload = json.loads(state['board']['payload_json'])
        assert payload['confirmed_by'] == 'automatic'
        assert payload['revision'] == 2 and state['board']['revision'] == 2
        revisions = c.execute('SELECT change_mode,actor,client_request_id FROM board_revisions '
                              'WHERE row_id=? ORDER BY revision', ('card-' + tid,)).fetchall()
        assert revisions[-1] == ('rule_change', 'automatic', 'synthetic-bulk')
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == transactions_before
    assert repair._financial_state(c) == financial
    details = [json.loads(r[0]) for r in c.execute('SELECT detail_json FROM change_log WHERE kind=?', (repair.RELEASE,))]
    assert len(details) == 5
    for detail in details:
        assert detail['before_confirmed_by'] == 'owner' and detail['after_confirmed_by'] == 'automatic'
        assert detail['stamp'] == dict(revision=1, minute=MINUTE, batch_size=5)
        assert detail['before']['board']['payload_json'] != detail['after']['board']['payload_json']
    stored = c.execute('SELECT payload_sha256 FROM requests WHERE request_id=? AND scope=?',
                       ('synthetic-bulk', repair.SCOPE)).fetchone()
    assert stored[0] == plan['digest']


def test_individual_stamp_preserved_at_min_batch_boundary(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids[:4])
    add_owner_row(c, tids[4], minute='2026-10-05T04:00')
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER, min_batch=5)
    assert plan['summary']['to_correct'] == 0
    assert plan['summary']['excluded'] == {'INDIVIDUAL_STAMP': 5}
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER, min_batch=4)
    assert plan['summary']['to_correct'] == 4
    assert plan['summary']['excluded'] == {'INDIVIDUAL_STAMP': 1}
    repair.apply(c, plan, TRIPS, request_id='synthetic-boundary', year=YEAR, quarter=QUARTER, min_batch=4)
    assert json.loads(repair._state(c, tids[4])['board']['payload_json'])['confirmed_by'] == 'owner'
    assert json.loads(repair._state(c, tids[0])['board']['payload_json'])['confirmed_by'] == 'automatic'


def test_batch_size_counts_rows_outside_scope(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    c.execute("UPDATE transactions SET trip_id='C',display_tab_id='C' WHERE transaction_id IN (?,?)", (tids[3], tids[4]))
    c.commit()
    stamp_all(c, tids)
    plan = repair.preview(c, Q3_TRIPS, year=YEAR, quarter=QUARTER)
    assert plan['summary']['owner_stamped_rows'] == 3
    assert plan['summary']['to_correct'] == 3
    assert plan['summary']['stamp_minutes'] == [dict(minute=MINUTE, rows=3, batch_size=5)]
    plan_q3 = repair.preview(c, Q3_TRIPS, year=YEAR, quarter=3)
    assert plan_q3['summary']['to_correct'] == 2


def test_out_of_quarter_rows_not_counted(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    c.execute("UPDATE transactions SET trip_id='C',display_tab_id='C' WHERE transaction_id=?", (tids[1],))
    c.execute("UPDATE transactions SET trip_id='',display_tab_id='quarter:2026:3' WHERE transaction_id=?", (tids[2],))
    c.execute("UPDATE transactions SET trip_id='',display_tab_id='quarter:2026:4' WHERE transaction_id=?", (tids[3],))
    c.execute("UPDATE transactions SET trip_id='',display_tab_id='' WHERE transaction_id=?", (tids[4],))
    c.commit()
    stamp_all(c, tids)
    plan = repair.preview(c, Q3_TRIPS, year=YEAR, quarter=QUARTER)
    assert plan['summary']['owner_stamped_rows'] == 2
    assert plan['summary']['to_correct'] == 2
    assert {t['tid'] for t in plan['targets']} == {tids[0], tids[3]}
    repair.apply(c, plan, Q3_TRIPS, request_id='synthetic-scope', year=YEAR, quarter=QUARTER)
    assert json.loads(repair._state(c, tids[3])['board']['payload_json'])['confirmed_by'] == 'automatic'
    assert json.loads(repair._state(c, tids[1])['board']['payload_json'])['confirmed_by'] == 'owner'


@pytest.mark.parametrize('kind', ['decided_at', 'user_decision', 'previous_decision', 'manual_hold',
                                  'review_decision', 'board_override'])
def test_manual_signals_preserved(setup, kind):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    tid = tids[0]
    if kind == 'decided_at':
        c.execute("UPDATE transactions SET decided_at='synthetic' WHERE transaction_id=?", (tid,))
    elif kind in ('user_decision', 'previous_decision', 'manual_hold'):
        c.execute('UPDATE transactions SET classification_source=? WHERE transaction_id=?', (kind, tid))
    elif kind == 'review_decision':
        c.execute('INSERT INTO review_decisions(transaction_id,revision,item,description,display_tab_id,note,reuse_rule,decided_at) '
                  "VALUES (?,99,'식비','','A','',0,'synthetic')", (tid,))
    else:
        c.execute("INSERT INTO board_manual_overrides(row_id,field,event_id) VALUES (?,'item','synthetic')", ('card-' + tid,))
    c.commit()
    stamp_all(c, tids)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    assert plan['summary']['excluded'].get('MANUAL_OR_USER_EXCEPTION') == 1
    assert plan['summary']['to_correct'] == 4
    assert tid not in {t['tid'] for t in plan['targets']}


@pytest.mark.parametrize('shape', ['event', 'edit', 'rule', 'conflict'])
def test_non_record_batch_revision_preserved(setup, shape):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids[1:])
    add_owner_row(c, tids[0], shape=shape)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER, min_batch=4)
    assert plan['summary']['excluded'].get('NOT_RECORD_BATCH') == 1
    assert plan['summary']['to_correct'] == 4


@pytest.mark.parametrize('shape', ['none', 'automatic_only'])
def test_missing_stamp_revision_preserved(setup, shape):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids[1:])
    add_owner_row(c, tids[0], shape=shape)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER, min_batch=4)
    assert plan['summary']['excluded'].get('NO_STAMP_REVISION') == 1
    assert plan['summary']['to_correct'] == 4


@pytest.mark.parametrize('kind', ['duplicate', 'conflict', 'parse_error', 'review_hold', 'company_excluded'])
def test_source_protection_preserved(setup, kind):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    tid = tids[0]
    row = repair._state(c, tid)['transaction']
    expected = 'SOURCE_PROTECTED'
    if kind == 'duplicate':
        c.execute("UPDATE transactions SET duplicate_of='other' WHERE transaction_id=?", (tid,))
    elif kind == 'conflict':
        c.execute("UPDATE transactions SET conflict_reason='synthetic' WHERE transaction_id=?", (tid,))
    elif kind == 'parse_error':
        c.execute("UPDATE transactions SET parse_error='synthetic' WHERE transaction_id=?", (tid,))
    elif kind == 'review_hold':
        expected = 'REVIEW_HOLD'
        c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)', (tid, row['source_hash'], 'user_hold', 'synthetic'))
    else:
        expected = 'COMPANY_EXCLUDED'
        c.execute('INSERT INTO transaction_company_exclusions VALUES (?,?,1,1,?,?)', (tid, row['source_hash'], 'synthetic', 'synthetic'))
    c.commit()
    stamp_all(c, tids)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    assert plan['summary']['excluded'].get(expected) == 1
    assert plan['summary']['to_correct'] == 4


def test_transactions_and_ledger_unchanged(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids)
    add_ledger(c, tids[0])
    add_ledger(c, tids[1])
    transactions_before = c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    ledger_before = c.execute('SELECT * FROM ledger_entries ORDER BY transaction_id').fetchall()
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    repair.apply(c, plan, TRIPS, request_id='synthetic-immutable', year=YEAR, quarter=QUARTER)
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == transactions_before
    assert c.execute('SELECT * FROM ledger_entries ORDER BY transaction_id').fetchall() == ledger_before


def test_preview_is_read_only(setup):
    c = setup[0].conn
    prepare(c)
    stamp_all(c, [r['transaction_id'] for r in setup[3]])
    before = '\n'.join(c.iterdump())
    repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    assert '\n'.join(c.iterdump()) == before


def test_digest_mismatch_rejected(setup):
    c = setup[0].conn
    prepare(c)
    stamp_all(c, [r['transaction_id'] for r in setup[3]])
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    bad = dict(plan, digest='0' * 64)
    with pytest.raises(ValueError, match='BULK_CONFIRMATION_PREVIEW_STALE'):
        repair.apply(c, bad, TRIPS, request_id='synthetic-stale', year=YEAR, quarter=QUARTER)


def test_replay_returns_zero_changes(setup):
    c = setup[0].conn
    prepare(c)
    stamp_all(c, [r['transaction_id'] for r in setup[3]])
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    repair.apply(c, plan, TRIPS, request_id='synthetic-replay', year=YEAR, quarter=QUARTER)
    result = repair.apply(c, plan, TRIPS, request_id='synthetic-replay', year=YEAR, quarter=QUARTER)
    assert result['replay'] is True and result['applied_this_run'] == 0
    assert repair.replay(c, 'synthetic-replay')['to_correct'] == 5


def test_request_conflict_on_different_digest(setup):
    c = setup[0].conn
    prepare(c)
    stamp_all(c, [r['transaction_id'] for r in setup[3]])
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    repair.apply(c, plan, TRIPS, request_id='synthetic-conflict', year=YEAR, quarter=QUARTER)
    plan2 = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    assert plan2['digest'] != plan['digest']
    with pytest.raises(ValueError, match='BULK_CONFIRMATION_REQUEST_CONFLICT'):
        repair.apply(c, plan2, TRIPS, request_id='synthetic-conflict', year=YEAR, quarter=QUARTER)


def test_restore_reverts_and_stale_restore_rejected(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids)
    transactions_before = c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    repair.apply(c, plan, TRIPS, request_id='synthetic-restore', year=YEAR, quarter=QUARTER)
    rplan = repair.restore_preview(c, 'synthetic-restore')
    assert rplan['summary']['restore'] == 5
    repair.restore(c, rplan, 'synthetic-restore')
    for tid in tids:
        state = repair._state(c, tid)
        payload = json.loads(state['board']['payload_json'])
        assert payload['confirmed_by'] == 'owner'
        assert payload['revision'] == 3 and state['board']['revision'] == 3
        assert c.execute('SELECT COUNT(*) FROM board_revisions WHERE row_id=?', ('card-' + tid,)).fetchone()[0] == 3
    assert c.execute('SELECT COUNT(*) FROM change_log WHERE kind=?', (repair.RESTORE,)).fetchone()[0] == 5
    assert c.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall() == transactions_before
    # A second correction followed by a later edit must refuse the restore.
    plan2 = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    repair.apply(c, plan2, TRIPS, request_id='synthetic-restore2', year=YEAR, quarter=QUARTER)
    payload = json.loads(repair._state(c, tids[0])['board']['payload_json'])
    payload['item'] = '변경'
    c.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?',
              (json.dumps(payload, ensure_ascii=False, sort_keys=True), 'card-' + tids[0]))
    c.commit()
    with pytest.raises(ValueError, match='BULK_CONFIRMATION_RESTORE_STALE'):
        repair.restore_preview(c, 'synthetic-restore2')


def test_restore_financial_stale_rejected(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    repair.apply(c, plan, TRIPS, request_id='synthetic-financial-stale', year=YEAR, quarter=QUARTER)
    row = repair._state(c, tids[0])['transaction']
    c.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
              (tids[0], row['source_hash'], 'user_hold', 'synthetic'))
    c.commit()
    with pytest.raises(ValueError, match='BULK_CONFIRMATION_RESTORE_FINANCIAL_STALE'):
        repair.restore_preview(c, 'synthetic-financial-stale')


def test_invalid_scope_rejected(setup):
    c = setup[0].conn
    prepare(c)
    for year, quarter in ((2026, 2), (2025, 4), (2026, 0)):
        with pytest.raises(ValueError, match='INVALID_SCOPE'):
            repair.preview(c, TRIPS, year=year, quarter=quarter)


def test_ai_review_no_longer_excludes_corrected_row(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids)
    add_ledger(c, tids[0])
    row = repair._state(c, tids[0])['transaction']
    manifest = dict(review_id='ai-quarter-review-2026Q4',
                    reviewer=dict(provider='claude', model='claude-fable-5-2', effort='high'),
                    corrections=[dict(transaction_id=tids[0], source_hash=row['source_hash'],
                                      revision=row['revision'], display_tab_id='B', item='숙박비',
                                      basis='TRIP-001 · 합성 근거')])
    before = ai_review_repair.preview(c, TRIPS, manifest)
    assert before['summary']['to_apply'] == 0
    assert before['summary']['excluded'].get('PROJECTION_ATTRIBUTION_DISAGREEMENT') == 1
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    repair.apply(c, plan, TRIPS, request_id='synthetic-ai-review', year=YEAR, quarter=QUARTER)
    after = ai_review_repair.preview(c, TRIPS, manifest)
    assert after['summary']['to_apply'] == 1
    assert 'PROJECTION_ATTRIBUTION_DISAGREEMENT' not in after['summary']['excluded']


def test_summary_has_no_identifiers_or_amounts(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    text = json.dumps(plan['summary'], ensure_ascii=False)
    for tid in tids:
        assert tid not in text
    assert 'SYNTHETIC' not in text and '1000' not in text


def test_mid_apply_failure_is_atomic(setup):
    c = setup[0].conn
    prepare(c)
    tids = [r['transaction_id'] for r in setup[3]]
    stamp_all(c, tids)
    plan = repair.preview(c, TRIPS, year=YEAR, quarter=QUARTER)
    before = '\n'.join(c.iterdump())
    c.execute("CREATE TEMP TRIGGER reject_bulk BEFORE UPDATE ON board_rows WHEN OLD.row_id='card-" + tids[0] +
              "' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
        repair.apply(c, plan, TRIPS, request_id='synthetic-atomic', year=YEAR, quarter=QUARTER)
    assert '\n'.join(c.iterdump()) == before


def make_host(tmp_path):
    host = tmp_path / 'host'
    (host / 'data').mkdir(parents=True)
    conn = sqlite3.connect(host / 'data/board.sqlite')
    conn.execute('CREATE TABLE requests (request_id TEXT PRIMARY KEY, scope TEXT NOT NULL, '
                 'payload_sha256 TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL)')
    conn.commit()
    return host, conn


def test_cli_scope_and_gate_errors(tmp_path, capsys):
    import tools.repair_bulk_owner_confirmation as tool
    host, conn = make_host(tmp_path)
    base = ['--host-root', str(host), '--request-id', 'synthetic-cli']
    assert tool.main(base) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'SCOPE_REQUIRED'
    assert tool.main(base + ['--year', '2026', '--quarter', '2']) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'INVALID_SCOPE'
    assert tool.main(base + ['--year', '2026', '--quarter', '4', '--min-batch', '0']) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'INVALID_MIN_BATCH'
    assert tool.main(base + ['--year', '2026', '--quarter', '4', '--apply']) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'PREVIEW_AND_BACKUP_REQUIRED'
    conn.close()


def test_cli_replay_and_conflict(tmp_path, capsys):
    import tools.repair_bulk_owner_confirmation as tool
    host, conn = make_host(tmp_path)
    stored = dict(owner_stamped_rows=5, to_correct=5, excluded={}, stamp_minutes=[],
                  trip_corrections=[], applied_this_run=5, replay=False)
    conn.execute('INSERT INTO requests VALUES (?,?,?,?,?)',
                 ('synthetic-cli', repair.SCOPE, 'a' * 64, json.dumps(stored), 'synthetic'))
    conn.commit()
    base = ['--host-root', str(host), '--request-id', 'synthetic-cli', '--year', '2026', '--quarter', '4']
    assert tool.main(base + ['--apply', '--expected-digest', 'a' * 64]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'REPLAYED' and report['applied_this_run'] == 0 and report['to_correct'] == 0
    assert tool.main(base + ['--apply', '--expected-digest', 'b' * 64]) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'BULK_CONFIRMATION_REQUEST_CONFLICT'
    conn.close()
