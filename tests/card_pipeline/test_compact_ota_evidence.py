"""기존 중복 압축 도구: 읽기 결과 동일·원문 불변·관측 합침·멱등·롤백·운영 보호."""
import hashlib
import json
import shutil
import sqlite3

import pytest

from app import ota_payments
from app.agoda_capture import parse_detail
from app.ota_store import OtaStore, catalog_rows, direct_facts
from tests.card_pipeline.test_agoda_capture import capture
from tests.card_pipeline.test_ota_store_dedupe import (cancel_mail, changed_parser, forest, legacy_evidence,
                                                       legacy_observations, trip, view, write)
from tools import compact_ota_evidence as tool

RAW = ('ota_raw_blobs', 'ota_messages', 'ota_raw_entries', 'ota_mail_origins', 'ota_source_revisions', 'ota_sources')


def build(tmp_path, monkeypatch, name='legacy', flip=False):
    """옛 쓰기 방식(판마다 같은 사실을 새 행으로)으로 중복이 쌓인 DB."""
    raw = capture()
    raw['observed_at'] = '2026-10-21T02:54:54Z'
    booking = parse_detail(raw)['booking_number']
    direct = tmp_path / (name + '-direct.json')
    direct.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    base = [trip(1), trip(2), cancel_mail(booking), forest(1), forest(2)]
    folder = tmp_path / (name + '-mail')
    with monkeypatch.context() as patch:
        patch.setattr(OtaStore, '_evidence', legacy_evidence)
        patch.setattr(OtaStore, 'index_reservation_observations', legacy_observations)
        store = OtaStore(tmp_path / (name + '.sqlite'))
        store.import_capture(direct)
        store.import_mail(write(folder, base))
        extra = [trip(3)]
        if flip:
            with monkeypatch.context() as parser:
                changed_parser(parser, 'parser-v2')
                store.import_mail(write(folder, base + extra))
        else:
            store.import_mail(write(folder, base + extra))
        store.import_mail(write(folder, base + extra + [forest(3)]))
        store.import_mail(write(folder, base + extra + [forest(3), trip(4)]))
        store.import_mail(write(folder, base + extra + [forest(3), trip(4), forest(4)]))
    path = store.path
    store.close()
    return path


def snapshot(path, tables=RAW):
    with sqlite3.connect(path) as conn:
        return {t: hashlib.sha256(repr(sorted(conn.execute('SELECT * FROM ' + t).fetchall())).encode()).hexdigest()
                for t in tables}


def counts(path):
    with sqlite3.connect(path) as conn:
        return {t: conn.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                for t in ('ota_booking_evidence', 'ota_reservation_observations', 'ota_row_seen')}


def outputs(path):
    store = OtaStore(path)
    try:
        events = [{k: v for k, v in e.items() if k != 'source_inventory'}
                  for e in ota_payments.build_ota_payment_events({'mail_directories': [store.path]})]
        return view(store), events, sorted(json.dumps(r, sort_keys=True) for r in catalog_rows(store.conn))
    finally:
        store.close()


def run(capsys, *args):
    code = tool.main([str(a) for a in args])
    return code, json.loads(capsys.readouterr().out)


def distinct(path):
    with sqlite3.connect(path) as conn:
        return (conn.execute("SELECT count(*) FROM (SELECT DISTINCT booking_id,entry_key,fact_json FROM "
                             "ota_booking_evidence WHERE evidence_kind='mail')").fetchone()[0],
                conn.execute('SELECT count(*) FROM (SELECT DISTINCT observation_id,entry_key,fact_json '
                             'FROM ota_reservation_observations)').fetchone()[0])


@pytest.mark.parametrize('flip', [False, True])
def test_apply_keeps_every_read_output_and_raw_tables(tmp_path, monkeypatch, capsys, flip):
    db = build(tmp_path, monkeypatch, flip=flip)
    before_out, before_raw, before_counts, before_distinct = outputs(db), snapshot(db), counts(db), distinct(db)
    seen_before = sqlite3.connect(db).execute('SELECT coalesce(sum(seen_count),0) FROM ota_row_seen').fetchone()[0]
    code, report = run(capsys, '--db', db, '--apply')
    assert code == 0 and report['status'] == 'APPLIED' and report['equivalence'] == 'equal'
    after = counts(db)
    assert after['ota_booking_evidence'] < before_counts['ota_booking_evidence']
    assert after['ota_reservation_observations'] < before_counts['ota_reservation_observations']
    assert distinct(db) == before_distinct
    assert outputs(db) == before_out
    assert snapshot(db) == before_raw
    # 관측 횟수 보존: 합친 행 + 행 자체 관측(옛 DB에는 없던 것)
    seen_after = sqlite3.connect(db).execute('SELECT coalesce(sum(seen_count),0) FROM ota_row_seen').fetchone()[0]
    assert seen_after == seen_before + report['seen_rows_synthesized']
    with sqlite3.connect(db) as conn:
        current = conn.execute("SELECT current_revision FROM ota_sources WHERE kind='mail_directory'").fetchone()[0]
        row = conn.execute("SELECT first_revision,last_revision,seen_count FROM ota_row_seen WHERE kind='evidence' "
                           "AND entry_key='trip-1'").fetchone()
        assert row[1] == current and row[0] != current and row[2] == 5
        assert conn.execute('SELECT count(*) FROM ota_booking_evidence').fetchone()[0] >= before_distinct[0]


def test_dry_run_writes_nothing_and_reports_counts(tmp_path, monkeypatch, capsys):
    db = build(tmp_path, monkeypatch)
    sqlite3.connect(db).execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    code, report = run(capsys, '--db', db, '--dry-run')
    assert code == 0 and report['status'] == 'DRY_RUN' and report['writes'] == 0
    assert report['ota_booking_evidence']['rows_to_delete'] > 0 and report['estimated_bytes_saved'] > 0
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
    assert 'trip-1' not in json.dumps(report)


def test_rerun_is_idempotent(tmp_path, monkeypatch, capsys):
    db = build(tmp_path, monkeypatch)
    run(capsys, '--db', db, '--apply')
    first, state = counts(db), snapshot(db, ('ota_row_seen', 'ota_booking_evidence'))
    code, report = run(capsys, '--db', db, '--apply')
    assert code == 0 and report['ota_booking_evidence']['rows_to_delete'] == 0
    assert report['ota_reservation_observations']['rows_to_delete'] == 0
    assert counts(db) == first and snapshot(db, ('ota_row_seen', 'ota_booking_evidence')) == state


def test_new_writer_continues_after_compaction_without_new_rows(tmp_path, monkeypatch, capsys):
    db = build(tmp_path, monkeypatch)
    run(capsys, '--db', db, '--apply')
    folder = tmp_path / 'legacy-mail'
    store = OtaStore(db)
    try:
        before = store.summary()
        store.import_mail(folder)
        assert store.summary() == before
        base = json.loads((folder / 'gmail.json').read_text(encoding='utf-8'))['responses']
        store.import_mail(write(folder, base + [trip(9)]))
        after = store.summary()
        assert after['ota_booking_evidence'] == before['ota_booking_evidence'] + 1
    finally:
        store.close()


def test_mismatch_rolls_back_everything(tmp_path, monkeypatch, capsys):
    db = build(tmp_path, monkeypatch)
    before, state = counts(db), snapshot(db, ('ota_row_seen', 'ota_booking_evidence', 'ota_reservation_observations'))
    real, calls = tool.read_digest, []

    def tampered(conn, path):
        calls.append(1)
        value = real(conn, path)
        return dict(value, catalog_rows='x') if len(calls) == 2 else value

    monkeypatch.setattr(tool, 'read_digest', tampered)
    code, report = run(capsys, '--db', db, '--apply')
    assert code == 1 and report == {'status': 'FAILED', 'code': 'EQUIVALENCE_MISMATCH'}
    assert counts(db) == before
    assert snapshot(db, ('ota_row_seen', 'ota_booking_evidence', 'ota_reservation_observations')) == state


def test_write_lock_held_by_another_writer_refuses(tmp_path, monkeypatch, capsys):
    db = build(tmp_path, monkeypatch)
    before = counts(db)
    other = sqlite3.connect(db, isolation_level=None)
    other.execute('BEGIN IMMEDIATE')
    try:
        code, report = run(capsys, '--db', db, '--apply')
    finally:
        other.execute('ROLLBACK')
        other.close()
    assert code == 2 and report['code'] == 'WRITE_LOCK_NOT_ACQUIRED' and counts(db) == before


def test_operational_file_needs_fresh_backup_evidence(tmp_path, monkeypatch, capsys):
    host = tmp_path / 'host'
    (host / 'data').mkdir(parents=True)
    live = host / 'data' / 'ota-evidence.sqlite'
    shutil.copy(build(tmp_path, monkeypatch), live)
    before = counts(live)
    code, report = run(capsys, '--db', live, '--apply', '--host-root', host)
    assert code == 2 and report['code'] == 'BACKUP_EVIDENCE_REQUIRED'
    stale = tmp_path / 'ev.json'
    stale.write_text(json.dumps({'recorded_at': '2020-01-01T00:00:00+00:00', 'backup_directory': str(host),
                                 'live_state_unchanged': True, 'restored_review_binding_equal': True,
                                 'backup_scope_kind': 'scoped', 'out_of_scope_unchanged': True,
                                 'backup_scope': ['board.sqlite']}), encoding='utf-8')
    code, report = run(capsys, '--db', live, '--apply', '--host-root', host, '--backup-evidence', stale)
    assert code == 2 and report['code'].startswith('BACKUP')
    assert counts(live) == before
    # 예행은 증거 없이 가능하고 쓰기가 없다.
    code, report = run(capsys, '--db', live, '--dry-run', '--host-root', host)
    assert code == 0 and report['writes'] == 0


def test_vacuum_shrinks_file_and_mode_is_required(tmp_path, monkeypatch, capsys):
    db = build(tmp_path, monkeypatch)
    code, report = run(capsys, '--db', db, '--apply', '--vacuum')
    assert code == 0 and report['db_bytes_after'] < report['db_bytes_before'] and 'seconds_vacuum' in report
    assert sqlite3.connect(db).execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    code, report = run(capsys, '--db', db)
    assert code == 2 and report['code'] == 'MODE_REQUIRED_DRY_RUN_OR_APPLY'
