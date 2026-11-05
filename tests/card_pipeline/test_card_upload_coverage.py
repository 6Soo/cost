"""Synthetic acceptance and provenance checks for manual query coverage."""
import csv
import hashlib
import io
import sqlite3

import pytest
from app import Pipeline
from app.card_upload_coverage import CoverageStore, inspect, Period, merge_periods
from app.db import StoreError


def content(*, card='1234-56**-****-1111', issuer='SYNTH', merchant='SHOP', amount='10', preamble=(), rows=True):
    buffer=io.StringIO()
    writer=csv.writer(buffer)
    writer.writerows(preamble)
    writer.writerow(['카드사','카드번호','카드종류','가맹점','이용금액','승인일','매입일','승인번호'])
    if rows:
        writer.writerow([issuer,card,'신용',merchant,amount,'2026-04-03','2026-04-08','SYNTH-A'])
    return buffer.getvalue().encode('utf-8-sig')


@pytest.fixture
def store():
    conn=sqlite3.connect(':memory:',isolation_level=None)
    pipeline=Pipeline(conn)
    coverage=CoverageStore(conn)
    coverage.prepare_schema()
    yield coverage,pipeline
    conn.close()


def received(store, raw=None):
    raw=content() if raw is None else raw
    coverage,pipeline=store
    batch=pipeline.receive(raw,'synthetic.csv')['batch_id']
    ev=dict(inspect(raw,'synthetic.csv')['evidence'],date_basis='이용일',start_date='2026-04-01',end_date='2026-04-10',confirmed=True,complete=True,evidence_source='user')
    return batch,ev


def test_sparse_transactions_do_not_shrink_confirmed_query_interval(store):
    batch,ev=received(store)
    result=store[0].record(batch,ev)
    assert result['confirmed']
    summary=store[0].summary(through='2026-04-10')
    assert summary['coverages'][0]['periods']==[{'start':'2026-04-01','end':'2026-04-10'}]
    assert summary['gaps']==[]


def test_transaction_and_merchant_dates_are_not_query_metadata():
    result=inspect(content(merchant='조회기간 2026-04-01 ~ 2026-04-30'),'synthetic.csv')
    assert not result['evidence']['start_date']
    assert not result['evidence']['date_basis']


def test_explicit_preamble_metadata_and_zero_transactions(store):
    raw=content(rows=False,preamble=[['조회기간','2026-04-01 ~ 2026-04-10'],['조회기준','매입일'],['카드사','SYNTH'],['카드번호','1234-56**-****-1111']])
    report=inspect(raw,'synthetic.csv')
    assert report['row_count']==0 and report['evidence']['date_basis']=='매입일'
    batch,ev=received(store,raw)
    ev.update(report['evidence'],confirmed=True,complete=True,evidence_source='metadata')
    assert store[0].record(batch,ev)['confirmed']


def test_zero_rows_without_identity_cannot_be_confirmed(store):
    batch,ev=received(store,content(rows=False))
    ev.update(issuer='SYNTH',card_tail='1111')
    with pytest.raises(StoreError):
        store[0].record(batch,ev)


def test_metadata_cannot_be_forged_by_client(store):
    batch,ev=received(store)
    ev['evidence_source']='metadata'
    with pytest.raises(StoreError,match='원본'):
        store[0].record(batch,ev)


@pytest.mark.parametrize('field,value',[('issuer','OTHER'),('card_tail','9999'),('card_id','forged')])
def test_client_card_identity_is_checked_against_source(store,field,value):
    batch,ev=received(store)
    ev[field]=value
    with pytest.raises(StoreError) as error:
        store[0].record(batch,ev)
    assert error.value.code=='CARD_IDENTITY_MISMATCH'


@pytest.mark.parametrize('start,end',[('2026-02-31','2026-04-01'),('2026-04-10','2026-04-01')])
def test_invalid_and_reversed_dates_are_rejected(store,start,end):
    batch,ev=received(store)
    ev.update(start_date=start,end_date=end)
    with pytest.raises(StoreError):
        store[0].record(batch,ev)


def test_missing_full_result_confirmation_is_not_promoted(store):
    batch,ev=received(store)
    ev['complete']=False
    with pytest.raises(StoreError):
        store[0].record(batch,ev)


def test_parser_errors_cannot_be_confirmed(store):
    batch,ev=received(store,content(amount='bad'))
    result=store[0].record(batch,ev)
    assert not result['confirmed']
    assert store[0].summary()['rechecks']


def test_source_integrity_is_verified(store):
    batch,ev=received(store)
    store[0].conn.execute('UPDATE import_batches SET content_sha256=? WHERE batch_id=?',('broken',batch))
    with pytest.raises(StoreError) as error:
        store[0].record(batch,ev)
    assert error.value.code=='SOURCE_HASH_MISMATCH'


def test_same_file_reupload_and_reconfirmation_are_idempotent(store):
    batch,ev=received(store)
    first=store[0].record(batch,ev)
    before=list(store[0].conn.iterdump())
    same,_=received(store)
    second=store[0].record(same,ev)
    assert first['coverage_id']==second['coverage_id'] and not second['inserted']
    assert list(store[0].conn.iterdump())==before


def test_intervals_merge_and_gaps_remain(store):
    batch,ev=received(store)
    store[0].record(batch,ev)
    ev.update(start_date='2026-04-15',end_date='2026-04-20')
    store[0].record(batch,ev)
    assert store[0].summary(through='2026-04-20')['gaps'][0]['gaps']==[{'start':'2026-04-11','end':'2026-04-14'}]
    assert merge_periods([Period('2026-04-11','2026-04-12'),Period('2026-04-01','2026-04-10')])==[Period('2026-04-01','2026-04-12')]


def test_same_tail_different_masked_cards_and_bases_never_merge(store):
    for card,basis in [('1234-56**-****-1111','이용일'),('9876-54**-****-1111','이용일'),('1234-56**-****-1111','매입일')]:
        batch,ev=received(store,content(card=card))
        ev['date_basis']=basis
        store[0].record(batch,ev)
    assert len(store[0].summary()['coverages'])==3


def test_tail_only_cards_are_scoped_to_source_not_merged_across_files(store):
    for merchant in ['SHOP-A','SHOP-B']:
        batch,ev=received(store,content(card='****-****-****-1111',merchant=merchant))
        store[0].record(batch,ev)
    summary=store[0].summary()
    assert len(summary['coverages'])==2
    assert all(row['identity_scope']=='source_file' for row in summary['coverages'])


def test_existing_transactions_never_backfill_coverage(store):
    received(store)
    assert store[0].summary()['coverages']==[]


def test_record_preserves_source_financial_and_manual_tables(store):
    batch,ev=received(store)
    conn=store[0].conn
    tables=[row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='change_log' AND name NOT LIKE 'sqlite_%'")]
    before={table:conn.execute('SELECT * FROM '+table).fetchall() for table in tables}
    store[0].record(batch,ev)
    assert before=={table:conn.execute('SELECT * FROM '+table).fetchall() for table in tables}


@pytest.mark.parametrize('preamble', [
    [('조회기간', '2026-04-01 ~ 2026-04-10'), ('조회기간', '2026-04-01 ~ 2026-04-20')],
    [('조회기간', '2026-02-31 ~ 2026-04-10')],
    [('조회기준', '이용일'), ('조회기준', '매입일')],
    [('카드사', 'OTHER')],
    [('카드번호', '9876-54**-****-1111')],
    [('조회유형', '취소만')],
    [('조회필터', '해외거래만')],
    [('다운로드상태', '부분')],
])
def test_conflicting_or_incomplete_source_cannot_be_promoted_by_user(store, preamble):
    batch, ev = received(store, content(preamble=preamble))
    assert not store[0].record(batch, ev)['confirmed']
    summary = store[0].summary()
    assert not summary['coverages'] and summary['rechecks']


def test_unidentified_row_cannot_hide_behind_one_identified_card(store):
    import copy
    raw = content()
    from app.import_card import parse_card_file
    parsed = copy.deepcopy(parse_card_file(raw, 'synthetic.csv'))
    unknown = copy.deepcopy(parsed.rows[0])
    unknown.card_tail = ''
    unknown.issuer = ''
    parsed.rows.append(unknown)
    assert inspect(raw, 'synthetic.csv', parsed)['blocked']


def test_failed_confirmation_preserves_other_files_evidence(store):
    good, evidence = received(store)
    store[0].record(good, evidence)
    before = store[0].summary(through='2026-04-10')['coverages']
    bad, evidence = received(store, content(amount='bad', merchant='OTHER'))
    assert not store[0].record(bad, evidence)['confirmed']
    assert store[0].summary(through='2026-04-10')['coverages'] == before


def test_explicit_full_query_marker_is_required_for_automatic_coverage():
    header=[['조회기간','2026-04-01 ~ 2026-04-10'],['조회기준','이용일']]
    no_marker=inspect(content(preamble=header),'synthetic.csv')
    assert not no_marker['metadata'].get('full_query_explicit')
    full=inspect(content(preamble=header+[ ['조회유형','전체'] ]),'synthetic.csv')
    assert full['metadata']['full_query_explicit'] is True
    restricted=inspect(content(preamble=header+[ ['조회유형','취소만'] ]),'synthetic.csv')
    assert restricted['blocked']
    assert not restricted['metadata'].get('full_query_explicit')


def test_card_baseline_is_audited_per_card_axis_and_changes_gap_math(store):
    coverage,_=store
    batch,ev=received(store)
    ev.update(start_date='2026-04-10',end_date='2026-04-20',date_basis='이용일')
    assert coverage.record(batch,ev)['confirmed']
    before=coverage.summary(through='2026-04-20')
    assert before['gaps'] == []
    card=before['coverages'][0]
    written=coverage.set_baseline(card_id=card['card_id'],issuer=card['issuer'],
        card_tail=card['card_tail'],date_basis=card['date_basis'],
        management_start='2026-04-01',expected_revision=0)
    assert written['updated'] and written['revision'] == 1
    after=coverage.summary(through='2026-04-20')
    assert after['gaps'][0]['gaps'] == [{'start':'2026-04-01','end':'2026-04-09'}]
    assert after['coverages'][0]['baseline_revision'] == 1
    count=store[0].conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
    again=coverage.set_baseline(card_id=card['card_id'],issuer=card['issuer'],
        card_tail=card['card_tail'],date_basis='이용일',
        management_start='2026-04-01',expected_revision=1)
    assert not again['updated']
    assert store[0].conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] == count
    with pytest.raises(StoreError,match='관리 기간'):
        coverage.set_baseline(card_id=card['card_id'],issuer=card['issuer'],
            card_tail=card['card_tail'],date_basis='이용일',
            management_start='2026-03-01',expected_revision=0)


def test_zero_row_source_remains_listed_in_uploaded_file_catalog(store):
    from types import SimpleNamespace
    import threading
    from webapp.card_flow import batch_catalog
    raw=content(rows=False,preamble=[['조회기간','2026-04-01 ~ 2026-04-10'],
                                     ['조회기준','이용일'],['카드사','SYNTH'],
                                     ['카드번호','1234-56**-****-1111']])
    batch=store[1].receive(raw,'zero-query.csv')['batch_id']
    board=SimpleNamespace(conn=store[0].conn,_lock=threading.RLock())
    listed=batch_catalog(board)
    assert any(item['batch_id']==batch and item['rows']==0 and
               item['filename']=='zero-query.csv' for item in listed)
