import datetime as dt
import hashlib
import json

import openpyxl
import pytest

from app import automatic_classification as policy
from app import manual_google_evidence as evidence
from app.google_expense_rows import read
from tests.card_pipeline.fixtures import domestic_row, make_csv
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore


def catalog(board):
    return [dict(t, trip_id=t['tab_id']) for t in board.list_trips()]


def workbook(tmp_path, layout='legacy'):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '0610_SYNTHETIC'
    cols = {'legacy': (2, 4, 6, 8, 9), 'europe': (1, 2, 3, 4, 5, 6, 7)}[layout]
    labels = (('거래일자', '항목', '내용', '증빙유형', '금액(원)') if layout == 'legacy'
              else ('거래일자', '항목', '내용', '기간', '예약번호', '증빙유형', '금액(원)'))
    data = ((dt.date(2026, 6, 12), 'SYNTHETIC HOTEL', '숙박비', '국민', 5000) if layout == 'legacy'
            else (dt.date(2026, 6, 12), 'SYNTHETIC HOTEL', '숙박비', None, None, '국민', 5000))
    for column, label, value in zip(cols, labels, data):
        ws.cell(5, column, label)
        ws.cell(6, column, value)
    letter = openpyxl.utils.get_column_letter(cols[-1])
    ws.cell(7, 3, f'=SUM({letter}6:{letter}6)')
    ws.cell(10, cols[1], 'summary explanation')
    ws.cell(10, cols[-1], 'not an expense')
    path = tmp_path / 'original.xlsx'
    wb.save(path)
    return path


@pytest.mark.parametrize('layout', ['legacy', 'europe'])
def test_original_columns_and_summary_boundary_are_preserved(tmp_path, layout):
    path = workbook(tmp_path, layout)
    values = openpyxl.load_workbook(path, data_only=True)
    formulas = openpyxl.load_workbook(path)
    result = read(formulas.active, values.active)
    assert result['status'] == 'readable'
    assert result['rows'] == [{'row': 6, 'amount': 5000, 'cells': dict(B='2026-06-12',
        C='SYNTHETIC HOTEL', D='숙박비', E=None, F=None, G='국민')}]


def test_ambiguous_rows_or_cards_never_prove_an_attribution():
    card = dict(transaction_id='syn', approval_date='2026-06-12', amount_krw=5000,
                issuer='국민', merchant='SYNTHETIC HOTEL JP', source_hash='syn-hash', transaction_direction='purchase')
    original = dict(sheet='0610_SYNTHETIC', row=6, trip_id='syn-trip', year=2026,
                    cells=dict(B='2026-06-12', C='SYNTHETIC HOTEL', G='국민'), amount=5000)
    assert len(evidence.match([card], [original], digest='syn')) == 1
    assert evidence.match([card, dict(card, transaction_id='other')], [original], digest='syn') == {}
    assert evidence.match([card], [original, dict(original, sheet='other')], digest='syn') == {}
    assert evidence.match([card], [dict(original, cells=dict(original['cells'], G='하나'))], digest='syn') == {}


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.delenv('WEBLEDGER_CLASSIFICATION_WRITER', raising=False)
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda *args: True)
    monkeypatch.setattr(CardFlow, '_ota_report', lambda *args: {})
    monkeypatch.setattr(CardFlow, 'ota_group_holds', lambda *args, **kwargs: {})
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    flow = CardFlow(board)
    old = board.create_trip(starts_on='2026-06-12', ends_on='2026-06-15',
        destination='SYN OLD', client_request_id='old')['tab_id']
    target = board.create_trip(starts_on='2026-06-10', ends_on='2026-06-11',
        destination='SYN NEW', client_request_id='new')['tab_id']
    board.conn.execute("UPDATE trip_tabs SET display_key='0610_SYNTHETIC' WHERE tab_id=?", (target,))
    batch = flow.pipeline.receive(make_csv([domestic_row(merchant='SYNTHETIC HOTEL',
        amount=5000, approval='SYN-01', date='2026-06-12', posting='2026-06-14', issuer='국민')]), 'synthetic.csv')['batch_id']
    board.conn.execute("UPDATE transactions SET classification_source='inference',classification_state='classified',"
        "item='숙박비',trip_id=?,display_tab_id=?", (old, old))
    board.conn.commit()
    flow._auto_record_locked(batch, include_state=False)
    root = tmp_path / 'reviewed-manual-ledger'
    root.mkdir()
    path = workbook(root)
    manifest = dict(version=1, reviewer=dict(kind='ai_review', provider='synthetic', model='synthetic', run_id='syn'),
        source=dict(role='archive', spreadsheet_id=evidence.__name__, path='original.xlsx', sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
        sheets=[dict(sheet='0610_SYNTHETIC', trip_id=target, year=2026)])
    from app.google_authority import SPREADSHEET_IDS
    manifest['source']['spreadsheet_id'] = SPREADSHEET_IDS['archive']
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    yield board, target, old, root, manifest
    board.close()


def test_explicit_source_review_corrects_all_projections_and_is_repeatable(source):
    board, target, old, root, _ = source
    trips = catalog(board)
    facts = evidence.load(board.conn, trips, root)
    assert len(facts) == 1
    tid = next(iter(facts))
    board.conn.execute("UPDATE board_rows SET payload_json=json_set(payload_json,'$.trip_id',?)", (old,))
    board.conn.commit()
    before = board.conn.execute('SELECT source_hash,amount_krw,raw_row_json,approval_date FROM transactions').fetchall()
    # A normal read/import completion never migrates an existing financial row.
    assert policy.plan(board.conn, trips, evidence=facts)['targets'] == []
    expected = policy.plan(board.conn, trips, evidence=facts, reconsider=True)
    assert len(expected['targets']) == 1 and expected['targets'][0]['booking_trip_correction']
    policy.apply(board.conn, expected, trips, evidence=facts, reconsider=True)
    assert board.conn.execute('SELECT display_tab_id FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone() == (target,)
    assert board.conn.execute('SELECT display_tab_id FROM board_rows WHERE row_id=?', ('card-'+tid,)).fetchone() == (target,)
    assert board.conn.execute("SELECT json_extract(payload_json,'$.trip_id') FROM board_rows WHERE row_id=?", ('card-'+tid,)).fetchone() == (target,)
    assert board.conn.execute('SELECT display_tab_id FROM transactions WHERE transaction_id=?', (tid,)).fetchone() == (target,)
    assert board.conn.execute('SELECT source_hash,amount_krw,raw_row_json,approval_date FROM transactions').fetchall() == before
    assert policy.plan(board.conn, trips, evidence=facts, reconsider=True)['targets'] == []
    assert board.conn.execute("SELECT COUNT(*) FROM change_log WHERE kind='card.google_trip_correction'").fetchone()[0] == 1


@pytest.mark.parametrize('direction', ['trip_to_quarter', 'quarter_to_trip'])
def test_quarter_transitions_keep_items_and_all_trip_fields_consistent(source, direction):
    board, target, old, root, _ = source
    facts = evidence.load(board.conn, catalog(board), root)
    tid = next(iter(facts))
    quarter = 'quarter:2026:2'
    if direction == 'trip_to_quarter':
        facts[tid]['trip_id'] = quarter
        expected_tab, expected_trip, expected_item = quarter, '', '분기 기타비용'
    else:
        board.conn.execute("UPDATE transactions SET display_tab_id=?,trip_id='',item='분기 기타비용'", (quarter,))
        board.conn.execute("UPDATE ledger_entries SET display_tab_id=?,trip_id='',item='분기 기타비용'", (quarter,))
        board.conn.execute("UPDATE board_rows SET display_tab_id=?,payload_json=json_set(payload_json,'$.display_tab_id',?,'$.trip_id','','$.item','분기 기타비용')", (quarter,quarter))
        board.conn.commit()
        expected_tab, expected_trip, expected_item = target, target, '숙박비'
    preview = policy.plan(board.conn, catalog(board), evidence=facts, reconsider=True)
    assert len(preview['targets']) == 1
    policy.apply(board.conn, preview, catalog(board), evidence=facts, reconsider=True)
    for table in ('transactions', 'ledger_entries'):
        assert board.conn.execute(f'SELECT display_tab_id,trip_id,item FROM {table} WHERE transaction_id=?', (tid,)).fetchone() == (expected_tab,expected_trip,expected_item)
    payload = json.loads(board.conn.execute('SELECT payload_json FROM board_rows WHERE row_id=?', ('card-'+tid,)).fetchone()[0])
    assert (payload['display_tab_id'],payload['trip_id'],payload['item']) == (expected_tab,expected_trip,expected_item)
    assert policy.plan(board.conn, catalog(board), evidence=facts, reconsider=True)['targets'] == []


@pytest.mark.parametrize('defect', ['hash', 'escape', 'wrong_sheet', 'wrong_year'])
def test_changed_original_or_mapping_is_rejected_without_writes(source, defect):
    board, _, _, root, manifest = source
    if defect == 'hash':
        (root/'original.xlsx').write_bytes(b'changed')
    elif defect == 'escape':
        manifest['source']['path'] = '../board.sqlite'
    elif defect == 'wrong_sheet':
        manifest['sheets'][0]['sheet'] = 'other'
    else:
        manifest['sheets'][0]['year'] = 2027
    (root/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    before = board.conn.total_changes
    with pytest.raises(ValueError, match='MANUAL_GOOGLE_EVIDENCE_INVALID'):
        evidence.load(board.conn, catalog(board), root)
    assert board.conn.total_changes == before


@pytest.mark.parametrize('field', ['ledger_display', 'ledger_trip', 'transaction_trip', 'payload_display', 'payload_trip'])
def test_actual_manual_decision_and_projection_conflict_remain_protected(source, field):
    board, _, old, root, _ = source
    facts = evidence.load(board.conn, catalog(board), root)
    board.conn.execute("UPDATE transactions SET classification_source='user_decision',decided_at='synthetic'")
    board.conn.commit()
    assert policy.plan(board.conn, catalog(board), evidence=facts, reconsider=True)['targets'] == []
    board.conn.execute("UPDATE transactions SET classification_source='inference',decided_at=NULL")
    if field == 'ledger_display':
        board.conn.execute("UPDATE ledger_entries SET display_tab_id='syn-conflict'")
    elif field == 'ledger_trip':
        board.conn.execute("UPDATE ledger_entries SET trip_id='syn-conflict'")
    elif field == 'transaction_trip':
        board.conn.execute("UPDATE transactions SET trip_id='syn-conflict'")
    else:
        key = 'display_tab_id' if field == 'payload_display' else 'trip_id'
        board.conn.execute("UPDATE board_rows SET payload_json=json_set(payload_json,?, 'syn-conflict')", ('$.'+key,))
    board.conn.commit()
    assert policy.plan(board.conn, catalog(board), evidence=facts, reconsider=True)['targets'] == []
