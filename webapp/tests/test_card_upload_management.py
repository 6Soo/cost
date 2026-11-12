"""Card-by-card upload coverage UX and safe evidence regression tests."""
import csv
import io
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from app import Pipeline
from app.card_upload_coverage import CoverageStore, inspect
from app.db import StoreError
from webapp import card_upload_coverage, card_flow, card_upload_jobs


def source(*, first='2026-04-01', last='2026-04-10', full=False,
           rows=True, card='1234-56**-****-1111'):
    data = io.StringIO()
    writer = csv.writer(data)
    writer.writerow(['조회기간', first + ' ~ ' + last])
    writer.writerow(['조회기준', '이용일'])
    writer.writerow(['카드사', 'SYNTH'])
    writer.writerow(['카드번호', card])
    if full:
        writer.writerow(['조회유형', '전체'])
    writer.writerow(['카드사', '카드번호', '카드종류', '가맹점',
                     '이용금액', '승인일', '매입일', '승인번호'])
    if rows:
        writer.writerow(['SYNTH', card, '신용', 'SHOP', '10',
                         first, last, 'SYNTH-A'])
        if first != last:
            writer.writerow(['SYNTH', card, '신용', 'SHOP-2', '11',
                             last, last, 'SYNTH-B'])
    return data.getvalue().encode('utf-8-sig')


@pytest.fixture
def ctx():
    conn = sqlite3.connect(':memory:', isolation_level=None)
    pipeline = Pipeline(conn)
    # PROC-072(#815): batch_catalog now reads the completed-period boundary, which needs list_trips.
    board = SimpleNamespace(conn=conn, _lock=threading.RLock(), list_trips=lambda: [])
    yield board, pipeline
    conn.close()


def uploaded(ctx, **kwargs):
    board, pipeline = ctx
    raw = source(**kwargs)
    batch = pipeline.receive(raw, 'query.csv')['batch_id']
    return batch, raw


def confirmed(ctx, batch, raw):
    board, _ = ctx
    ev = inspect(raw, 'query.csv')['evidence']
    evidence = dict(ev, confirmed=True, complete=True,
                    evidence_source='metadata')
    return CoverageStore(board.conn).record(batch, evidence)


def test_zero_row_file_visible_and_not_mistaken_for_transaction_date(ctx):
    board, _ = ctx
    batch, raw = uploaded(ctx, rows=False, full=True)
    assert confirmed(ctx, batch, raw)['confirmed']
    dashboard = card_upload_coverage.get_coverage_summary(board, through='2026-04-10')
    assert dashboard['overview']['card_count'] == 0
    assert dashboard['overview']['covered_bases'] == 0
    assert dashboard['overview']['gap_count'] == 0
    assert dashboard['files'][0]['batch_id'] == batch
    assert dashboard['files'][0]['zero_rows'] is True
    assert dashboard['files'][0]['source_rows'] == 0
    assert dashboard['files'][0]['query_periods'] == []
    assert not dashboard['files'][0]['transaction_start']
    assert dashboard['files'][0]['coverage_status'] == 'no_transaction_dates'
    assert any(row['batch_id'] == batch for row in card_flow.batch_catalog(board))


def test_gap_dates_use_file_spans_between_transaction_endpoints(ctx):
    board, _ = ctx
    first, raw1 = uploaded(ctx, first='2026-04-01', last='2026-04-10')
    second, raw2 = uploaded(ctx, first='2026-04-15', last='2026-04-20')
    dashboard = card_upload_coverage.get_coverage_summary(board, through='2026-04-20')
    card = dashboard['cards'][0]
    assert card['periods'] == [{'start': '2026-04-01', 'end': '2026-04-10'},
                               {'start': '2026-04-15', 'end': '2026-04-20'}]
    assert card['gaps'] == [{'start': '2026-04-11', 'end': '2026-04-14'}]
    assert dashboard['overview']['gap_count'] == 1
    assert card['date_basis'] == '거래일자'


def test_missing_query_metadata_does_not_block_transaction_date_view(ctx):
    board, _ = ctx
    batch, _ = uploaded(ctx, full=False)
    dashboard = card_upload_coverage.get_coverage_summary(board)
    assert dashboard['cards']
    assert dashboard['overview']['files_need_review'] == 0
    assert dashboard['files'][0]['batch_id'] == batch
    assert dashboard['files'][0]['coverage_status'] == 'transaction_dates'


def test_declared_full_query_is_required_for_automatic_confirmation(ctx, monkeypatch):
    board, pipeline = ctx
    from webapp import ota_payment_review, card_completion_worker
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: False)
    monkeypatch.setattr(card_completion_worker, 'finish_jobs', lambda board: None)

    class Flow:
        def classify(self, batch):
            pass
        def auto_record(self, batch):
            return {}

    for full in (False, True):
        batch, raw = uploaded(ctx, full=full, first='2026-04-01',
                              last='2026-04-10' if full else '2026-04-09')
        received = {'batch_id': batch}
        output, status = card_upload_jobs.process(
            board, SimpleNamespace(), Flow(), received,
            SimpleNamespace(channel='approval'), None)
        assert status == 200
        records = CoverageStore(board.conn).get_coverage_for_batch(batch)
        if full:
            assert output['coverage_confirmed'] is True
            assert len(records) == 1 and records[0]['confirmed']
        else:
            assert not records
            assert not output.get('coverage_confirmed')


def test_card_management_markup_links_to_gap_and_source_metadata():
    html = card_flow.page('synthetic-csrf')
    assert 'id="coverage-summary"' in html
    assert 'id="gap-upload-context"' in html
    assert '/cards/all?panel=coverage' in html
    assert '관리 시작일 저장' not in html
    assert '조회기간과 별개' not in html
    assert '/coverage/confirm' not in html
    assert 'function loadCardReviewBatches' in html
    assert 'data-batch' in html  # saved-tab focus and selection contract is preserved


def test_legacy_baseline_records_keep_revision_and_conflict_protection(ctx):
    board, _ = ctx
    batch, raw = uploaded(ctx)
    confirmed(ctx, batch, raw)
    card = CoverageStore(board.conn).summary()["coverages"][0]
    store = CoverageStore(board.conn)
    before = board.conn.execute('SELECT COUNT(*) FROM change_log').fetchone()[0]
    saved = store.set_management_start(card['card_id'], '이용일',
                                       '2026-03-01', 0)
    assert saved['revision'] == 1 and saved['changed']
    new = card_upload_coverage.get_coverage_summary(board, through='2026-04-20')['cards'][0]
    assert 'management_start' not in new
    assert new['periods'] == [{'start': '2026-04-01', 'end': '2026-04-10'}]
    assert new['gaps'] == []
    repeated = store.set_management_start(card['card_id'], '이용일',
                                          '2026-03-01', 1)
    assert repeated['changed'] is False
    assert board.conn.execute('SELECT COUNT(*) FROM change_log').fetchone()[0] == before + 1
    with pytest.raises(StoreError, match='다른 화면'):
        store.set_management_start(card['card_id'], '이용일',
                                   '2026-02-01', 0)
