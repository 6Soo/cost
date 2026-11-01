"""Completed full refunds and unrelated questions remain visually separate."""
import copy

import pytest
from playwright.sync_api import sync_playwright

from webapp.card_flow import page as render_page
from webapp.tests.test_card_automatic_ux import flow


@pytest.mark.parametrize('scenario', ['complete', 'partial', 'held', 'unbooked'])
def test_full_refund_completion_is_separate_without_hiding_real_review(flow, scenario):
    service, batch, _ = flow
    state = service.state(batch)
    before = list(service.board.conn.iterdump())
    pair = state['preview']['rows']
    for row in pair:
        row.pop('blocked', None)
        row.pop('reason', None)
        row['already_booked'] = True
        row['next_action'] = {'status': '기록 완료', 'group': 'booked', 'required': False}
    extra = copy.deepcopy(pair[0])
    extra.update(transaction_id='synthetic-unrelated', already_booked=False, item='',
                 next_action={'status': '비용 항목 선택 필요', 'group': 'review',
                              'label': '비용 항목 선택', 'reason': '합성 일반 거래', 'required': True})
    source = copy.deepcopy(state['rows'][0])
    source.update(transaction_id=extra['transaction_id'], item='')
    state['rows'].append(source)
    state['preview']['rows'].append(extra)
    group = {'original_id': pair[0]['transaction_id'], 'digest': 'synthetic-digest',
             'status': 'full', 'net_krw': 0, 'gross_krw': 10000, 'refund_krw': -10000,
             'item': '합성항목', 'trip_name': '합성여행', 'recordable': True, 'reason': '',
             'rows': [dict(row) for row in pair[:2]]}
    state['refund_groups'] = [group]
    if scenario == 'partial':
        group.update(status='partial', net_krw=1000, refund_krw=-9000)
    elif scenario == 'held':
        group['rows'][0]['blocked'] = 'review_hold'
        pair[0]['review_hold'] = {'kind': 'manual', 'reason': '합성 수동 보류'}
    elif scenario == 'unbooked':
        group['rows'][0]['already_booked'] = False
        pair[0]['already_booked'] = False

    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            for width in (390, 1440):
                page = browser.new_page(viewport={'width': width, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def route(request):
                    path = request.request.url.split('cost.test', 1)[-1]
                    if path == '/import':
                        request.fulfill(content_type='text/html', body=render_page('synthetic'))
                    elif path == '/api/imports':
                        request.fulfill(json={'batches': [{'batch_id': batch, 'rows': 3, 'display_name': '합성자료'}]})
                    elif path == '/api/imports/' + batch:
                        request.fulfill(json=state)
                    else:
                        request.fulfill(json={'rules': []})
                page.route('**/*', route)
                page.goto('http://cost.test/import')
                page.locator('[data-review-state="all"]').click()
                completed = scenario == 'complete'
                assert page.locator('.refund-complete').count() == int(completed)
                assert page.locator('#preview tbody tr').count() == (1 if completed else 3)
                if completed:
                    group_text = page.locator('.refund-complete').inner_text()
                    assert '추가 입력 없음' in group_text
                    assert '합성항목' not in group_text and '합성여행' not in group_text
                    assert page.locator('.refund-complete button').count() == 0
                    assert '그 외 거래 처리 결과' in page.locator('#preview').inner_text()
                    assert '비용 항목 선택' in page.locator('#preview tbody').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert errors == []
                page.close()
        finally:
            browser.close()
    assert before == list(service.board.conn.iterdump())
