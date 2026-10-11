import copy

import pytest

from webapp import receipt_review as rr


def region(**changes):
    return dict(box=[0, 0, 100, 100], merchant='SYN-SHOP', date='2026-10-01',
                currency='JPY', total=1200, payment='cash', confidence=1.0, **changes)


def test_edited_receipt_rescan_cannot_create_another_cost(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': ['synthetic-image'], 'candidates': [], 'holds': []})
    original = {'image': 'synthetic-image', 'regions': [region()]}
    rr.scan(path, original)
    identity = rr.load(path)['candidates'][0]['identity']
    rr.edit(path, identity=identity, changes={'total_jpy': 1300})
    rr.confirm(path, identity=identity, payee='SYN-SHOP', category='식비')
    changed = copy.deepcopy(original)
    changed['regions'][0].update(total=1400, payment='private_card')
    result = rr.scan(path, changed)
    assert result['added'] == 0
    candidate, = rr.load(path)['candidates']
    assert candidate['identity'] == identity
    assert candidate['total_jpy'] == 1300
    assert candidate['category'] == '식비'


def test_payment_difference_is_not_evidence_of_a_second_receipt(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [region()]})
    other = region()
    other.update(payment='private_card', box=[200, 200, 300, 300])
    result = rr.scan(path, {'regions': [other]})
    assert result['added'] == 0
    assert result['holds'][0]['reason'] == 'DUPLICATE_CONTENT'


@pytest.mark.parametrize('changes', [{'total_jpy': -1}, {'total_jpy': 1.5},
                                    {'total_jpy': True}, {'date': '2026-02-30'}, {'merchant': '  '}])
def test_invalid_edit_preserves_file_and_confirmation(tmp_path, changes):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [region()]})
    identity = rr.load(path)['candidates'][0]['identity']
    rr.confirm(path, identity=identity, payee='SYN-SHOP', category='식비')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        rr.edit(path, identity=identity, changes=changes)
    assert path.read_bytes() == before


def test_amount_edit_requires_confirmation_again(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [region()]})
    identity = rr.load(path)['candidates'][0]['identity']
    rr.edit(path, identity=identity, changes={'trip_id': 'trip-syn'}, valid_trips={'trip-syn'})
    rr.confirm(path, identity=identity, payee='SYN-SHOP', category='식비')
    assert rr.tsv(path, 'trip-syn')['row_count'] == 1
    rr.edit(path, identity=identity, changes={'total_jpy': 1300})
    assert rr.tsv(path, 'trip-syn')['row_count'] == 0


def test_cash_receipt_with_card_evidence_is_held_instead_of_counted_twice(tmp_path, monkeypatch):
    path = tmp_path / 'receipts.json'
    cards = [{'transaction_id': 'card-syn', 'date': '2026-10-01', 'merchant': 'SYN-SHOP', 'original_jpy': 1200}]
    monkeypatch.setattr(rr, 'card_rows', lambda board: cards)
    rr.scan(path, {'regions': [region()]})
    stored, = rr.load(path)['candidates']
    rr.edit(path, identity=stored['identity'], changes={'trip_id': 'trip-syn'},
            valid_trips={'trip-syn'}, card_rows_list=cards)
    rr.confirm(path, identity=stored['identity'], payee='SYN-SHOP', category='식비')
    result = rr.tsv(path, 'trip-syn')
    assert result['row_count'] == 0
    assert any(h['reason'] == 'CARD_PAYMENT_CONFLICT' for h in result['held'])


def test_copy_rechecks_cards_imported_after_receipt_confirmation(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [region()]})
    stored, = rr.load(path)['candidates']
    rr.edit(path, identity=stored['identity'], changes={'trip_id': 'trip-syn'}, valid_trips={'trip-syn'})
    rr.confirm(path, identity=stored['identity'], payee='SYN-SHOP', category='식비')
    before = path.read_bytes()
    cards = [{'transaction_id': 'card-syn', 'date': '2026-10-01', 'merchant': 'SYN-SHOP', 'original_jpy': 1200}]
    assert rr.tsv(path, 'trip-syn', card_rows_list=cards)['row_count'] == 0
    assert path.read_bytes() == before


def test_repeated_confirmation_does_not_append_duplicate_history(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [region()]})
    stored, = rr.load(path)['candidates']
    rr.confirm(path, identity=stored['identity'], payee='SYN-SHOP', category='식비')
    before = path.read_bytes()
    rr.confirm(path, identity=stored['identity'], payee='SYN-SHOP', category='식비')
    assert path.read_bytes() == before


def test_card_linked_receipt_can_choose_trip_when_form_resends_unchanged_payment(tmp_path, monkeypatch):
    path = tmp_path / 'receipts.json'
    cards = [{'transaction_id': 'card-syn', 'date': '2026-10-01', 'merchant': 'SYN-SHOP', 'original_jpy': 1200}]
    monkeypatch.setattr(rr, 'card_rows', lambda board: cards)
    rr.scan(path, {'regions': [{**region(), 'payment': 'corporate_card'}]})
    stored, = rr.load(path)['candidates']
    # The browser sends every field on the row, even when only the trip was changed.
    result = rr.edit(path, identity=stored['identity'], valid_trips={'trip-syn'}, card_rows_list=cards,
                     changes={'trip_id': 'trip-syn', 'merchant': stored['merchant'], 'date': stored['date'],
                              'total_jpy': stored['total_jpy'], 'payment': stored['payment']})
    assert result['trip_id'] == 'trip-syn'
    assert result['card_transaction_id'] == 'card-syn' and result['amount_krw'] is None
    assert rr.tsv(path, 'trip-syn')['row_count'] == 0


def test_possible_duplicate_keeps_second_receipt_values_for_human_review(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [region()]})
    other = {**region(), 'box': [300, 300, 400, 400], 'payment': 'private_card'}
    result = rr.scan(path, {'regions': [other]})
    assert result['added'] == 0
    data = rr.load(path)
    assert len(data['candidates']) == 1
    held, = [hold for hold in data['holds'] if hold['reason'] == 'DUPLICATE_CONTENT']
    assert held['candidate']['merchant'] == other['merchant']
    assert held['candidate']['total_jpy'] == other['total']
    assert held['candidate']['payment'] == 'private_card'
    assert held['candidate']['identity'] != data['candidates'][0]['identity']
    assert held['candidate']['box'] == other['box']
    rr.scan(path, {'regions': [other]})
    assert len(rr.load(path)['holds']) == 1


@pytest.mark.parametrize('changes', [{'merchant': 'OTHER-SHOP'}, {'date': '2026-10-02'}])
def test_linked_receipt_cannot_lose_card_identity_through_metadata_edit(tmp_path, monkeypatch, changes):
    path = tmp_path / 'receipts.json'
    cards = [{'transaction_id': 'card-syn', 'date': '2026-10-01',
              'merchant': 'SYN-SHOP', 'original_jpy': 1200}]
    monkeypatch.setattr(rr, 'card_rows', lambda board: cards)
    rr.scan(path, {'regions': [{**region(), 'payment': 'corporate_card'}]})
    stored, = rr.load(path)['candidates']
    before = path.read_bytes()
    with pytest.raises(ValueError, match='CARD_LINKED_NOT_EDITABLE'):
        rr.edit(path, identity=stored['identity'], changes=changes, card_rows_list=cards)
    assert path.read_bytes() == before


def test_missing_card_on_trip_edit_does_not_authorize_receipt_repricing(tmp_path, monkeypatch):
    path = tmp_path / 'receipts.json'
    cards = [{'transaction_id': 'card-syn', 'date': '2026-10-01',
              'merchant': 'SYN-SHOP', 'original_jpy': 1200}]
    monkeypatch.setattr(rr, 'card_rows', lambda board: cards)
    rr.scan(path, {'regions': [{**region(), 'payment': 'corporate_card'}]})
    stored, = rr.load(path)['candidates']
    rr.edit(path, identity=stored['identity'], changes={'trip_id': 'trip-syn'},
            valid_trips={'trip-syn'}, card_rows_list=[])
    before = path.read_bytes()
    with pytest.raises(ValueError, match='CARD_LINKED_NOT_EDITABLE'):
        rr.edit(path, identity=stored['identity'], changes={'payment': 'cash'})
    assert path.read_bytes() == before
    assert rr.tsv(path, 'trip-syn', card_rows_list=[])['row_count'] == 0


@pytest.mark.parametrize('changes,reason', [({'confidence': 0.4}, 'LOW_CONFIDENCE'),
                                           ({'total': None}, 'TOTAL_UNCLEAR'),
                                           ({'payment': 'corporate_card'}, 'CARD_NOT_FOUND')])
def test_held_receipt_keeps_original_region_values_and_image(tmp_path, changes, reason):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': ['synthetic-image'], 'candidates': [], 'holds': []})
    raw = {**region(), **changes}
    rr.scan(path, {'image': 'synthetic-image', 'regions': [raw]})
    data = rr.load(path)
    hold, = data['holds']
    assert hold['reason'] == reason
    assert hold['image_sha'] == 'synthetic-image'
    for field in ('merchant', 'date', 'total', 'payment', 'confidence', 'box'):
        assert hold['region'][field] == raw[field]
    assert data['candidates'] == []
    assert raw['merchant'] in rr.render_html(data, '')


def test_late_card_rescan_resolves_hold_and_preserves_review_history(tmp_path, monkeypatch):
    path = tmp_path / 'receipts.json'
    payload = {'regions': [{**region(), 'payment': 'corporate_card'}]}
    rr.scan(path, payload)
    held, = rr.load(path)['holds']
    cards = [{'transaction_id': 'card-syn', 'date': '2026-10-01',
              'merchant': 'SYN-SHOP', 'original_jpy': 1200}]
    monkeypatch.setattr(rr, 'card_rows', lambda board: cards)
    rr.scan(path, payload)
    data = rr.load(path)
    stored, = data['candidates']
    assert stored['identity'] == held['identity']
    assert not data['holds']
    assert stored['history'][0]['resolved_hold']['reason'] == 'CARD_NOT_FOUND'
    assert stored['card_transaction_id'] == 'card-syn'
    assert stored['amount_krw'] is None


def test_repeated_edit_preserves_confirmation_and_does_not_duplicate_history(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [region()]})
    stored, = rr.load(path)['candidates']
    changes = {'trip_id': 'trip-syn', 'merchant': stored['merchant'], 'date': stored['date'],
               'total_jpy': stored['total_jpy'], 'payment': stored['payment']}
    rr.edit(path, identity=stored['identity'], changes=changes, valid_trips={'trip-syn'})
    rr.confirm(path, identity=stored['identity'], payee='SYN-SHOP', category='식비')
    before = path.read_bytes()
    rr.edit(path, identity=stored['identity'], changes=changes, valid_trips={'trip-syn'})
    assert path.read_bytes() == before
    assert rr.tsv(path, 'trip-syn')['row_count'] == 1
