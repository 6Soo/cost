"""Synthetic UI, preview and commit boundaries; never opens a customer database."""
import pytest

from app import ledger
from app.partial_refund import refund_links, refund_group
from webapp import card_flow, ledger_board, refund_tab
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.test_partial_refund import HEADER


@pytest.fixture(params=['kakao', 'same-day'])
def context(tmp_path, monkeypatch, request):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', '')
    store = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    previous = ledger_board._STORE
    ledger_board.bind_store(store)
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
    monkeypatch.setattr(ledger_board, 'live_trips', lambda **kw: [])
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda *a: True)
    monkeypatch.setattr(CardFlow, 'tab_valid', lambda *a: True)
    monkeypatch.setattr(CardFlow, 'ota_group_holds', lambda *a: {})
    monkeypatch.setattr(CardFlow, '_already_projected', lambda *a: False)
    monkeypatch.setattr(CardFlow, '_projection_index', lambda *a: {})
    monkeypatch.setattr(card_flow, '_ota_entries_by_card', lambda *a, **kw:
                        {'__snapshot_status__': {'fresh': False, 'status': 'refreshing'}})
    flow = CardFlow(store)
    merchant, cancel = (('카카오택시', '카카오T가승인') if request.param == 'kakao'
                        else ('합성고속버스', '합성고속버스'))
    batch = flow.pipeline.receive((HEADER +
        f'국민,1234,domestic,purchase,{merchant},24600,,,24600,2026-10-02,2026-10-02,A100,,매입\n' +
        f'국민,1234,domestic,purchase,{cancel},24600,,,24600,2026-10-02,2026-10-02,A200,,매입\n'
    ).encode(), 'synthetic.csv')['batch_id']
    rows = flow.pipeline.get_batch(batch)['rows']
    ids = {r['approval_number']: r['transaction_id'] for r in rows}
    store.conn.execute("UPDATE transactions SET classification_state='classified',item='교통비',display_tab_id='unclassified'")
    store.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-24600 "
                       "WHERE transaction_id=?", (ids['200'],))
    store.conn.commit()
    try:
        yield store, flow, batch, ids['100'], ids['200']
    finally:
        ledger_board.bind_store(previous)
        store.close()


@pytest.mark.parametrize('automatic', [False, True])
def test_inferred_links_never_authorize_commit_even_when_both_rows_classified(context, automatic):
    store, flow, batch, original, refund = context
    before = list(store.conn.iterdump())
    preview = flow.pipeline.preview(batch, trip_validator=lambda _: True, tab_validator=lambda _: True)
    assert preview['ready'] == 0
    assert all(r['blocked'] == 'refund_inferred' for r in preview['rows'])
    assert {r['amount_krw'] for r in preview['rows']} == {24600, -24600}
    assert list(store.conn.iterdump()) == before
    result = ledger.commit(flow.pipeline.store, batch, preview['digest'], 'synthetic-commit',
                           trip_validator=lambda _: True, tab_validator=lambda _: True,
                           automatic_record=automatic)
    assert result['applied'] == 0
    assert store.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_render_keeps_both_source_rows_and_displays_inference_and_financial_hold(context):
    store, flow, batch, original, refund = context
    before = list(store.conn.iterdump())
    html = card_flow.render_expense_cleanup(store, 'synthetic-csrf')
    assert html.count(f"data-transaction='{original}'") == 1
    assert html.count(f"data-transaction='{refund}'") == 1
    assert '환불 추론 연결 · 기록 보류' in html
    assert '원결제 추론 연결' in html and '환급 완료 아님' in html
    assert '원결제와 환불을 함께 기록해야 합니다' not in html
    assert '원결제 연결을 확인할 수 없습니다' not in html
    assert 'OTA 예약 연결 상태와 금융 상쇄 상태는 별개입니다.' in html
    groups = refund_tab.groups(store)
    assert len(groups) == 1 and len(groups[0]) == 2 and groups[0][0]['inferred']
    assert '원결제 추론 연결 · 기록 보류 · 환급 완료 아님' in refund_tab.render(store)
    assert refund_group(store.conn, original) == [original, refund]
    assert list(store.conn.iterdump()) == before


@pytest.mark.parametrize('held_side', ['original', 'refund'])
def test_manual_hold_is_preserved_and_visible_on_either_row(context, held_side):
    store, flow, batch, original, refund = context
    target = original if held_side == 'original' else refund
    source = store.conn.execute('SELECT source_hash FROM transactions WHERE transaction_id=?', (target,)).fetchone()[0]
    store.conn.execute('INSERT INTO transaction_review_holds VALUES (?,?,?,?)',
                       (target, source, 'evidence_pending', 'SYNTHETIC MANUAL HOLD'))
    store.conn.commit()
    before = list(store.conn.iterdump())
    holds = flow.automatic_holds(batch)
    preview = flow.pipeline.preview(batch, trip_validator=lambda _: True,
                                    tab_validator=lambda _: True, additional_holds=holds)
    assert preview['ready'] == 0
    held = next(r for r in preview['rows'] if r['transaction_id'] == target)
    assert held['blocked'] == 'review_hold' and held['reason'] == 'SYNTHETIC MANUAL HOLD'
    html = card_flow.render_expense_cleanup(store, 'synthetic-csrf')
    assert 'SYNTHETIC MANUAL HOLD' in html
    if held_side == 'original':
        assert '보류 중' in html
    assert '내부 비용 기록 준비 가능' not in html
    assert list(store.conn.iterdump()) == before


def test_original_on_other_page_still_shows_same_global_inference(context, monkeypatch):
    store, flow, batch, original, refund = context
    monkeypatch.setattr(card_flow, '_CLEANUP_PAGE_SIZE', 1)
    pages = [card_flow.render_expense_cleanup(store, 'csrf', page=p) for p in (1, 2)]
    assert sum(p.count(f"data-transaction='{original}'") for p in pages) == 1
    assert sum(p.count(f"data-transaction='{refund}'") for p in pages) == 1
    assert all('추론 연결' in p for p in pages)
    assert all('원결제 연결을 확인할 수 없습니다' not in p for p in pages)


def test_taken_original_remains_a_visible_candidate_with_posting_date_fallback(context):
    store, flow, batch, original, refund = context
    store.conn.execute("UPDATE transactions SET approval_date='' WHERE transaction_id IN (?,?)", (original, refund))
    # Reserve the original via an authoritative partial refund outside the page.
    columns = [r[1] for r in store.conn.execute('PRAGMA table_info(transactions)')]
    store.conn.execute('INSERT INTO transactions SELECT ' + ','.join(
        "'synthetic-authoritative-refund'" if c == 'transaction_id' else c for c in columns) +
        ' FROM transactions WHERE transaction_id=?', (refund,))
    store.conn.execute("UPDATE transactions SET original_approval_number='100',amount_krw=-4100 "
                       "WHERE transaction_id='synthetic-authoritative-refund'")
    store.conn.commit()
    before = list(store.conn.iterdump())
    assert refund_links(store.conn, [refund]) == {}
    _, candidates, count = card_flow._refund_merchant_candidates_readonly(store, refund)
    assert count == 1 and candidates[0][0] == original
    html = card_flow._render_refund_evidence(store, refund, None)
    assert original in html and '원결제 연결은 미확정' in html
    assert list(store.conn.iterdump()) == before


def test_original_only_batch_cannot_book_half_an_inferred_group(context):
    store, flow, batch, original, refund = context
    store.conn.execute('DELETE FROM import_batch_rows WHERE transaction_id=?', (refund,))
    store.conn.commit()
    preview = flow.pipeline.preview(batch, trip_validator=lambda _: True, tab_validator=lambda _: True)
    assert preview['ready'] == 0 and preview['rows'][0]['blocked'] == 'refund_group_incomplete'


def test_inferred_action_does_not_use_a_trip_label_as_refund_confirmation(context):
    from webapp.card_actions import next_action
    store, flow, batch, original, refund = context
    action = next_action({'batch_id': batch, 'transaction_id': original, 'trip_name': '환불'},
                         {'blocked': 'refund_inferred'})
    assert action['required'] and action['status'] == '환불 추론 연결'


def test_inferred_link_preserves_existing_ledger_entry_and_does_not_book_counterpart(context):
    store, flow, batch, original, refund = context
    source = store.conn.execute('SELECT source_hash FROM transactions WHERE transaction_id=?', (original,)).fetchone()[0]
    store.conn.execute("INSERT INTO ledger_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (original, batch, '교통비', '합성 기장', 'unclassified', '', 24600, '합성가맹점',
         '2026-10-02', 'purchase', source, 'synthetic-time'))
    store.conn.commit()
    before = store.conn.execute('SELECT * FROM ledger_entries').fetchall()
    preview = flow.pipeline.preview(batch, trip_validator=lambda _: True, tab_validator=lambda _: True)
    assert preview['ready'] == 0
    result = ledger.commit(flow.pipeline.store, batch, preview['digest'], 'synthetic-booked',
                           trip_validator=lambda _: True, tab_validator=lambda _: True, automatic_record=True)
    assert result['applied'] == 0
    assert store.conn.execute('SELECT * FROM ledger_entries').fetchall() == before
