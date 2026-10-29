from app.automatic_classification import completion_for_row
from app.upload_reconciliation import KEYS, summarize


TRIPS = {'trip-a': {'trip_id': 'trip-a'}}


def row(**overrides):
    value = {
        'transaction_id': 'synthetic', 'transaction_direction': 'purchase',
        'transaction_kind': '승인', 'classification_state': 'classified',
        'classification_source': 'inference', 'classification_basis': 'AUTO_INFERRED · 낮음 · 일정근거',
        'item': '식비', 'trip_id': 'trip-a', 'display_tab_id': 'trip-a',
        'decided_at': None, 'parse_error': '', 'conflict_reason': '', 'duplicate_of': None,
    }
    value.update(overrides)
    return value


def test_low_confidence_supported_auto_assignment_completes_and_manual_lock_is_respected():
    assert completion_for_row(row(), TRIPS)['complete']
    manual = row(classification_source='user_decision', decided_at='2026-10-29T00:00:00Z')
    assert completion_for_row(manual, TRIPS)['mode'] == 'manual'


def test_saved_classification_is_not_reopened_by_candidate_wording():
    for basis in ('AUTO_PROVISIONAL · trip-a', 'AUTO_INFERRED · 동률 후보',
                  'AUTO_INFERRED · 충돌 후보', 'AUTO_INFERRED · 낮은 신뢰도'):
        assert completion_for_row(row(classification_basis=basis), TRIPS)['complete']


def test_invalid_trip_and_structured_source_conflict_remain_blocked():
    assert 'TRIP_INVALID_OR_MISSING' in completion_for_row(row(trip_id='deleted'), TRIPS)['blocked_by']
    assert 'SOURCE_UNRESOLVED' in completion_for_row(row(conflict_reason='ambiguous'), TRIPS)['blocked_by']
    assert 'CLASSIFICATION_SOURCE_CONFLICT' in completion_for_row(
        row(classification_source='inference_conflict'), TRIPS)['blocked_by']


def test_missing_booking_evidence_does_not_reopen_saved_classification():
    assert completion_for_row(row(classification_source='booking_evidence_needed'), TRIPS)['complete']
    assert 'CLASSIFICATION_SOURCE_CONFLICT' in completion_for_row(
        row(classification_source='rule_conflict'), TRIPS)['blocked_by']


def test_transaction_nature_and_trip_conflict_are_required():
    assert 'TRANSACTION_NATURE_UNCONFIRMED' in completion_for_row(row(transaction_kind=''), TRIPS)['blocked_by']
    assert 'TRIP_ASSIGNMENT_CONFLICT' in completion_for_row(
        row(display_tab_id='other-trip'), {**TRIPS, 'other-trip': {'trip_id': 'other-trip'}})['blocked_by']


def test_aggregate_buckets_keep_source_partition_and_unknown_date_separate():
    assert KEYS == ('T', 'E', 'N', 'C', 'U', 'H', 'P', 'R')
    import sqlite3

    from app import Pipeline

    conn = sqlite3.connect(':memory:', isolation_level=None)
    pipeline = Pipeline(conn)
    from app.import_card import ParsedFile
    # Use three source occurrences: no date, malformed date, and a parser failure.
    class Source:
        def __init__(self, index, date_value, error=''):
            self.row_index = index
            self.approval_date = date_value
            self.posting_date = ''
            self.parse_error = error
            self.issuer = 'synthetic'
            self.card_kind = 'credit'
            self.transaction_direction = 'purchase'
            self.amount_krw = 100 * index
            self.approval_number = str(index)
            self.card_tail = '1234'
            self.merchant = 'synthetic'
            self.foreign_currency = 'KRW'

    parsed = ParsedFile('synthetic.csv', 'synthetic', rows=[
        Source(1, ''), Source(2, 'not-a-date'), Source(3, '', 'SYNTHETIC_PARSE_ERROR'),
        Source(4, '')])
    received = {'batch_id': 'synthetic-batch', 'filename': 'synthetic.csv', 'reused': False}
    conn.execute("INSERT INTO import_batches(batch_id,filename,content_sha256,content_bytes,byte_size,parser,received_at) VALUES ('synthetic-batch','synthetic.csv','hash',X'',0,'synthetic','now')")
    conn.execute("INSERT INTO import_batch_rows(batch_id, transaction_id, row_index) VALUES ('synthetic-batch','tid',1)")
    conn.execute("INSERT INTO transactions(transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,transaction_direction,transaction_kind,approval_number,original_approval_number,approval_date,posting_date,merchant,merchant_normalized,amount_krw,foreign_amount,foreign_currency,description_raw,row_index,raw_row_json,classification_state,classification_source,classification_basis,item,description,display_tab_id,trip_id,revision,created_at) VALUES ('tid','source','synthetic-batch','synthetic','1234','credit','purchase','승인','1','','','','synthetic','synthetic',100,'','KRW','',1,'{}','classified','inference','AUTO_INFERRED · 낮음 · synthetic','식비','','trip-a','trip-a',1,'now')")
    conn.execute("INSERT INTO import_batch_rows(batch_id, transaction_id, row_index) VALUES ('synthetic-batch','tid-ambiguous',5)")
    conn.execute("INSERT INTO transactions(transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,transaction_direction,transaction_kind,approval_number,original_approval_number,approval_date,posting_date,merchant,merchant_normalized,amount_krw,foreign_amount,foreign_currency,description_raw,row_index,raw_row_json,classification_state,classification_source,classification_basis,item,description,display_tab_id,trip_id,revision,created_at) VALUES ('tid-ambiguous','source-2','synthetic-batch','synthetic','1234','credit','purchase','승인','1','','','','synthetic','synthetic',100,'','KRW','',5,'{}','classified','inference','AUTO_INFERRED · 낮음 · synthetic','식비','','trip-a','trip-a',1,'now')")
    summary = summarize(pipeline, received, parsed, [
        {'trip_id': 'trip-a', 'starts_on': '2026-01-01', 'ends_on': '2026-12-31'}])
    assert summary['counts'] == {'T': 4, 'E': 0, 'N': 1, 'C': 1, 'U': 0, 'H': 1, 'P': 2, 'R': 0}
    assert summary['unknown_date_reconciliation'][0]['T'] == 4
    assert summary['unknown_date_reconciliation'][0]['P'] == 2
    assert summary['monthly_reconciliation'] == []
    conn.close()
