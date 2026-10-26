"""환불 표시만 검사하며 금융 연결/기장 로직은 기존 함수를 사용한다."""
import pytest

from app.partial_refund import refund_links
from webapp.card_flow import CardFlow, _render_refund_evidence, _render_refund_merchant_candidates
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.test_partial_refund import HEADER


@pytest.mark.parametrize('scenario,expected', [
    ('missing', '원결제 자료 미확인'), ('ambiguous', '후보를 하나로 정할 수 없습니다'),
    ('conflict', '원본 충돌'), ('linked', '환불 기록 처리 대기'),
    ('recorded', '환불 기록 완료'), ('excess', '원결제를 초과'),
])
def test_refund_display_separates_source_pair_and_recording(tmp_path, scenario, expected):
    board = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            '국민,1234,domestic,purchase,합성숙박,625280,,,625280,2026-09-22,2026-09-23,A100,,매입\n' +
            '국민,1234,domestic,purchase,합성숙박,625280,,,625280,2026-09-22,2026-09-23,A200,,매입\n').encode(), 'synthetic.csv')['batch_id']
        rows = flow.pipeline.get_batch(batch)['rows']
        original = next(r['transaction_id'] for r in rows if r['approval_number'] == '100')
        refund = next(r['transaction_id'] for r in rows if r['approval_number'] == '200')
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=?,original_approval_number=? WHERE transaction_id=?",
                           (-700000 if scenario == 'excess' else -625280, '999' if scenario == 'missing' else '100', refund))
        if scenario == 'ambiguous':
            board.conn.execute("INSERT INTO transactions SELECT " + ','.join(
                "'synthetic-other'" if c[1] == 'transaction_id' else c[1]
                for c in board.conn.execute('PRAGMA table_info(transactions)')) + ' FROM transactions WHERE transaction_id=?', (original,))
        if scenario == 'conflict':
            board.conn.execute("UPDATE transactions SET conflict_reason='synthetic' WHERE transaction_id=?", (original,))
        if scenario == 'recorded':
            for row in (original, refund):
                board.conn.execute("INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) SELECT transaction_id,batch_id,'숙박비','','refunds','',amount_krw,merchant,approval_date,transaction_direction,source_hash,'2026-10-24' FROM transactions WHERE transaction_id=?", (row,))
        board.conn.commit()
        before = board.conn.total_changes
        link = refund_links(board.conn, [refund]).get(refund)
        markup = _render_refund_evidence(board, refund, link)
        assert expected in markup
        if not link:
            assert original in markup  # 비교 후보의 원문 링크
            assert '원결제 연결은 미확정' in markup
        else:
            assert original not in markup
        assert board.conn.total_changes == before
        assert '<li><li>' not in markup
    finally:
        board.close()


def test_merchant_comparison_includes_partial_refunds_without_linking(tmp_path):
    board = LedgerStore(tmp_path / 'merchant.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            '국민,1234,domestic,purchase,카카오T일반택시(법인)_0,16000,,,16000,2026-10-02,2026-10-03,A100,,매입\n' +
            '국민,1234,domestic,purchase,카카오T가승인_유페이,9800,,,9800,2026-10-02,2026-10-03,A200,,매입\n' +
            '국민,9999,domestic,purchase,카카오T일반택시,9800,,,9800,2026-10-02,2026-10-03,A300,,매입\n' +
            '국민,1234,domestic,purchase,카카오T일반택시,9800,,,9800,2026-10-03,2026-10-04,A400,,매입\n'
        ).encode(), 'synthetic.csv')['batch_id']
        rows = flow.pipeline.get_batch(batch)['rows']
        ids = {r['approval_number']: r['transaction_id'] for r in rows}
        refund = ids['200']
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-9800 WHERE transaction_id=?", (refund,))
        board.conn.commit()
        before = list(board.conn.iterdump())
        assert refund_links(board.conn, [refund]) == {}
        markup = _render_refund_merchant_candidates(board, refund)
        assert '16,000원' in markup and ids['100'] in markup
        assert ids['300'] not in markup and ids['400'] not in markup
        assert '가승인 해제' in markup and '원결제 연결은 미확정' in markup
        assert '원승인번호 없음' in markup and '가맹점명으로 전체 카드 거래 검색' in markup
        assert list(board.conn.iterdump()) == before
    finally:
        board.close()


def test_kakao_taxi_aliases_are_diagnostic_only_and_exclude_other_services():
    from webapp.card_flow import _refund_merchant_key
    aliases = (
        '카카오T가승인_유페이', '카카오T일반택시(법인)_0',
        '카카오택시 선승인', 'Kakao Taxi 일반',
        '카카오모빌리티 택시요금',
    )
    assert {_refund_merchant_key(name) for name in aliases} == {'카카오택시'}
    for other in ('카카오페이 편의점', '카카오 선물하기', '카카오T 대리',
                  '카카오T 주차', '유페이', '카카오모빌리티 퀵'):
        assert _refund_merchant_key(other) != '카카오택시'


def test_kakao_alias_review_shows_only_same_card_earlier_taxi_payments(tmp_path):
    from webapp.card_flow import _refund_merchant_candidates_readonly, _refund_merchant_key
    store = LedgerStore(tmp_path / 'kakao-evidence.sqlite', seed_demo=False)
    try:
        flow = CardFlow(store)
        batch = flow.pipeline.receive((HEADER +
            '국민,1234,domestic,purchase,카카오T일반택시(법인)_0,16000,,,16000,2026-10-02,2026-10-03,A100,,매입\n' +
            '국민,1234,domestic,purchase,카카오T가승인_유페이,9800,,,9800,2026-10-02,2026-10-03,A200,,매입\n' +
            '국민,1234,domestic,purchase,카카오페이편의점,9800,,,9800,2026-10-02,2026-10-03,A300,,매입\n' +
            '국민,9999,domestic,purchase,카카오T일반택시,9800,,,9800,2026-10-02,2026-10-03,A400,,매입\n' +
            '국민,1234,domestic,purchase,카카오T주차,9800,,,9800,2026-10-02,2026-10-03,A500,,매입\n' +
            '국민,1234,domestic,purchase,카카오T일반택시,9800,,,9800,2026-10-03,2026-10-04,A600,,매입\n'
        ).encode(), 'kakao-synthetic.csv')['batch_id']
        records = flow.pipeline.get_batch(batch)['rows']
        ids = {r['approval_number']: r['transaction_id'] for r in records}
        refund = ids['200']
        store.conn.execute('UPDATE transactions SET transaction_direction=?,amount_krw=? WHERE transaction_id=?',
                           ('cancellation', -9800, refund))
        store.conn.commit()
        before = list(store.conn.iterdump())
        from webapp.card_flow import _kakao_merchant_inventory_readonly
        inventory = _kakao_merchant_inventory_readonly(store)
        assert sum(x['count'] for x in inventory if x['family'] == '카카오택시') == 4
        assert sum(x['count'] for x in inventory if x['family'] != '카카오택시') == 2
        original, matches, total = _refund_merchant_candidates_readonly(store, refund)
        assert total == 1
        assert [row[0] for row in matches] == [ids['100']]
        html = _render_refund_merchant_candidates(store, refund)
        assert '표기 변형' in html and '16,000원' in html
        assert '카카오페이' not in html and ids['400'] not in html and ids['600'] not in html
        assert 'cleanup-merchant-compare' in html and '원결제 연결은 미확정' in html
        assert list(store.conn.iterdump()) == before
    finally:
        store.close()


@pytest.mark.parametrize('scenario', ['full', 'partial', 'excess', 'manual', 'conflict', 'other_batch'])
def test_classified_full_refund_without_trip_uses_refund_tab_but_keeps_protection(tmp_path, monkeypatch, scenario):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'full-offset.sqlite', seed_demo=False)
    try:
        flow = CardFlow(board)
        monkeypatch.setattr(flow, 'ota_group_holds', lambda: {})
        monkeypatch.setattr(flow, '_already_projected', lambda *_: False)
        batch = flow.pipeline.receive((HEADER +
            '국민,1234,domestic,purchase,AGODA_NICE-Agoda,625280,,,625280,2026-09-22,2026-09-23,A100,,매입\n' +
            '국민,1234,domestic,purchase,AGODA_NICE-Agoda,625280,,,625280,2026-09-22,2026-09-23,A200,,매입\n').encode(), 'synthetic.csv')['batch_id']
        rows = flow.pipeline.get_batch(batch)['rows']
        original = next(r['transaction_id'] for r in rows if r['approval_number'] == '100')
        refund = next(r['transaction_id'] for r in rows if r['approval_number'] == '200')
        board.conn.execute("UPDATE transactions SET classification_state='classified',item='숙박비',display_tab_id='',trip_id=''")
        amount = -400000 if scenario == 'partial' else -700000 if scenario == 'excess' else -625280
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=?,original_approval_number='100' WHERE transaction_id=?", (amount, refund))
        if scenario == 'manual':
            source = board.conn.execute('SELECT source_hash FROM transactions WHERE transaction_id=?', (original,)).fetchone()[0]
            board.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)', (original, source, 'evidence_pending', 'manual hold'))
        if scenario == 'conflict':
            board.conn.execute("UPDATE transactions SET conflict_reason='source conflict' WHERE transaction_id=?", (original,))
        if scenario == 'other_batch':
            board.conn.execute('DELETE FROM import_batch_rows WHERE transaction_id=?', (original,))
        board.conn.commit()
        before = list(board.conn.iterdump())
        holds = flow.automatic_holds(batch)
        preview = flow.pipeline.preview(batch, trip_validator=lambda _: False,
                                        tab_validator=lambda t: t == 'refunds', additional_holds=holds)
        selected = [r for r in preview['rows'] if r['transaction_id'] in (original, refund)]
        if scenario == 'full':
            assert len(selected) == 2 and all(not r.get('blocked') for r in selected)
            assert all(r['display_tab_id'] == 'refunds' and r['trip_id'] == '' for r in selected)
            assert {r['amount_krw'] for r in selected} == {625280, -625280}
        else:
            assert selected and all(r.get('blocked') for r in selected)
        assert list(board.conn.iterdump()) == before
    finally:
        board.close()
