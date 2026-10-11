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
