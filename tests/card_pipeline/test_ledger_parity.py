"""M6: 이관 후 통합 장부가 화면 행의 모든 필드를 담는지 고정한다.

이 검사가 없어서 `classification_source`(2,490건)·`classification_basis`(2,579건)·
`ota_evidence`(12건)가 조용히 사라질 뻔했다. 실제 운영 사본 대조에서 발견했다.
"""
import json
import sqlite3

import pytest

from app import db
from tools import migrate_to_ledger

# 화면 행 payload가 쓸 수 있는 전체 키. 컬럼으로 펼 수 없는 것만 따로 표시한다.
RENAMED = {'row_id': 'entry_id', 'row_kind': 'entry_kind'}
AS_JSON = {'ota_evidence': 'ota_evidence_json'}

PAYLOAD_KEYS = [
    'row_id', 'row_kind', 'display_tab_id', 'revision', 'occurred_on', 'item',
    'description', 'amount_krw', 'service_period', 'reservation_no',
    'evidence_type', 'source_kind', 'source_event_id', 'source_fact_digest',
    'source_merchant', 'source_issuer', 'source_card_last4',
    'source_approval_number', 'source_approval_date', 'source_posting_date',
    'source_local_amount', 'source_currency', 'event_kind',
    'classification_state', 'classification_source', 'classification_basis',
    'confirmed_by', 'memo', 'operator_note',
    'customer_id', 'customer_name', 'nickname', 'income_kind', 'event_type',
    'created_by_request', 'ota_evidence',
]


def _conn(tmp_path):
    conn = sqlite3.connect(tmp_path / 'board.sqlite', isolation_level=None)
    from webapp.ledger_store_schema import SCHEMA_SQL as BOARD_SCHEMA_SQL
    conn.executescript(db.SCHEMA_SQL)
    conn.executescript(BOARD_SCHEMA_SQL)
    return conn


def _insert(conn, row_id, tab, payload_extra):
    payload = {'row_id': row_id, 'row_kind': 'expense', 'display_tab_id': tab,
               'revision': 1, 'item': '숙박비', 'description': '숙박비',
               'amount_krw': 12_000, 'occurred_on': '2026-05-01'}
    payload.update(payload_extra)
    conn.execute(
        'INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)'
        ' VALUES (?,?,?,?,?)',
        (row_id, 'expense', tab, 1, json.dumps(payload, ensure_ascii=False)))


def test_every_payload_key_has_a_ledger_home(tmp_path):
    """payload가 쓸 수 있는 키마다 ledger 컬럼이 있어야 한다."""
    conn = _conn(tmp_path)
    try:
        migrate_to_ledger.migrate(conn, apply=True)
        columns = {r[1] for r in conn.execute('PRAGMA table_info(ledger)')}
        absent = []
        for key in PAYLOAD_KEYS:
            column = AS_JSON.get(key) or RENAMED.get(key, key)
            if column not in columns:
                absent.append(f'{key} -> {column}')
        assert absent == [], f'ledger에 자리가 없는 payload 키: {absent}'
    finally:
        conn.close()


def test_classification_provenance_survives_migration(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(conn, 'card-p1', 'trip-A',
                {'classification_source': 'ai_inference',
                 'classification_basis': 'AI 추론 근거 문장'})
        migrate_to_ledger.migrate(conn, apply=True)
        row = conn.execute(
            "SELECT classification_source, classification_basis FROM ledger"
            " WHERE entry_id='card-p1'").fetchone()
        assert row == ('ai_inference', 'AI 추론 근거 문장')
    finally:
        conn.close()


def test_ota_evidence_survives_migration(tmp_path):
    conn = _conn(tmp_path)
    try:
        evidence = {'kind': 'exact', 'providers': ['agoda'], 'group_size': 2}
        _insert(conn, 'card-o1', 'trip-A', {'ota_evidence': evidence})
        migrate_to_ledger.migrate(conn, apply=True)
        stored = conn.execute(
            "SELECT ota_evidence_json FROM ledger WHERE entry_id='card-o1'").fetchone()[0]
        assert json.loads(stored) == evidence
    finally:
        conn.close()


def test_empty_payload_trip_id_keeps_the_ledger_entries_value(tmp_path):
    """화면 행 payload에 trip_id가 없어도 기장 기록의 값을 잃지 않는다."""
    conn = _conn(tmp_path)
    try:
        _insert(conn, 'card-t1', 'trip-A', {})
        conn.execute(
            "INSERT INTO ledger_entries(transaction_id,batch_id,item,description,"
            "display_tab_id,trip_id,amount_krw,merchant,occurred_on,"
            "transaction_direction,source_hash,committed_at)"
            " VALUES ('t1','b1','숙박비','숙박비','trip-A','trip-A',12000,'m',"
            "'2026-05-01','purchase','h','2026-05-01')")
        migrate_to_ledger.migrate(conn, apply=True)
        assert conn.execute(
            "SELECT trip_id FROM ledger WHERE entry_id='card-t1'").fetchone()[0] == 'trip-A'
    finally:
        conn.close()
