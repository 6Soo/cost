import pytest

from app.automatic_classification import infer_item


def _row(merchant='', industry='', **extra):
    row = {'merchant': merchant, 'description_raw': f'card-category:{industry}' if industry else '',
           'transaction_direction': 'purchase'}
    row.update(extra)
    return row


def test_overseas_by_transaction_region_without_merchant_country():
    row = _row(card_kind='해외')
    assert infer_item(row)[0] == '현지경비'
    row = _row(raw_row={'c11': '해외'})
    assert infer_item(row)[0] == '현지경비'


def test_domestic_fallback_unchanged():
    assert infer_item(_row(card_kind='국내'))[0] == '기타경비'
    assert infer_item(_row())[0] == '기타경비'


@pytest.mark.parametrize('merchant', ['SEVEN-ELEVEN 합성점', 'FamilyMart Synthetic', 'LAWSON 100', 'CU 합성점', '세븐일레븐 합성'])
def test_convenience_store_is_food_item(merchant):
    assert infer_item(_row(merchant))[0] == '식비'


def test_convenience_store_industry_is_food_item():
    assert infer_item(_row(industry='편의점'))[0] == '식비'


@pytest.mark.parametrize('industry, item', [('RF유료도로.터널', '통행료'), ('공연장/전시장', '입장료')])
def test_card_industry_vocabulary(industry, item):
    assert infer_item(_row(industry=industry))[0] == item


def test_existing_item_and_cu_word_boundary():
    assert infer_item(_row('ACCUMULATE SYNTHETIC'))[0] == '기타경비'
    assert infer_item(_row('편의점', item='교통비'))[0] == '교통비'


@pytest.mark.parametrize('industry, item', [('RF유료도로.터널', '통행료'), ('공연장/전시장', '입장료')])
def test_import_path_card_industry_items(industry, item):
    from app.classify import classify_transaction
    row = {'merchant': '합성', 'merchant_normalized': '합성', 'approval_date': '2026-10-04',
           'transaction_direction': 'purchase', 'amount_krw': 5000,
           'description_raw': f'card-category:{industry}'}
    result = classify_transaction(row, rules=[])
    assert result['classification_source'] == 'card_category'
    assert result['item'] == item
