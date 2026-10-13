import pytest

from webapp import receipt_review as rr


def reading(**changes):
    base = dict(merchant='SYN-SHOP', date='2026-10-01', currency='JPY', total=820, payment='cash',
                confidence=1.0, box=None)
    return {**base, **changes}


def test_a_reading_missing_its_merchant_stays_a_candidate_that_can_be_completed(tmp_path):
    path = tmp_path / 'receipts.json'
    result = rr.scan(path, {'regions': [reading(merchant=None)]})
    assert result['added'] == 1 and result['holds'] == []
    candidate, = rr.load(path)['candidates']
    assert candidate['hold'] == 'FIELD_MISSING' and candidate['merchant'] == ''
    with pytest.raises(ValueError, match='FIELD_MISSING'):
        rr.confirm(path, identity=candidate['identity'], payee='x', category='식비')
    rr.edit(path, identity=candidate['identity'], changes={'merchant': 'SYN-SHOP'})
    candidate, = rr.load(path)['candidates']
    assert candidate['hold'] is None and candidate['amount_krw'] == 820 * rr.rc.JPY_TO_KRW


def test_missing_payment_is_held_until_a_person_chooses_it(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [reading(payment=None)]})
    candidate, = rr.load(path)['candidates']
    assert candidate['hold'] == 'PAYMENT_UNKNOWN'
    rr.edit(path, identity=candidate['identity'], changes={'payment': 'private_card'})
    assert rr.load(path)['candidates'][0]['hold'] is None


def test_an_unclear_total_or_currency_is_kept_without_a_guessed_value(tmp_path):
    path = tmp_path / 'receipts.json'
    rr.scan(path, {'regions': [reading(total=None), reading(currency=None, merchant='B', total=500)]})
    holds = {c['hold'] for c in rr.load(path)['candidates']}
    assert holds == {'TOTAL_UNCLEAR', 'CURRENCY_UNKNOWN'}
    assert all(c['amount_krw'] is None for c in rr.load(path)['candidates'])


def test_identical_incomplete_readings_are_not_merged(tmp_path):
    path = tmp_path / 'receipts.json'
    result = rr.scan(path, {'regions': [reading(merchant=None), reading(merchant=None)]})
    assert result['added'] == 2
    assert len({c['identity'] for c in rr.load(path)['candidates']}) == 2


def test_rescanning_the_photo_does_not_overwrite_a_completed_candidate(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': ['synthetic-image'], 'candidates': [], 'holds': []})
    payload = {'image': 'synthetic-image', 'regions': [reading(merchant=None)]}
    rr.scan(path, payload)
    candidate, = rr.load(path)['candidates']
    rr.edit(path, identity=candidate['identity'], changes={'merchant': 'FIXED-SHOP'})
    again = rr.scan(path, payload)
    assert again['added'] == 0
    candidate, = rr.load(path)['candidates']
    assert candidate['merchant'] == 'FIXED-SHOP' and candidate['hold'] is None


def test_an_invalid_date_is_still_refused(tmp_path):
    with pytest.raises(ValueError, match='DATE_INVALID'):
        rr.scan(tmp_path / 'receipts.json', {'regions': [reading(date='2026-13-40')]})
