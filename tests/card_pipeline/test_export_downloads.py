"""Synthetic reproductions of issuer print/usage download failures."""
import datetime
import io
import sqlite3
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app import Pipeline, StoreError
from app.card_export_profiles import HANA_USAGE, HANA_FOREIGN, IBK_PRINT
from app.card_preflight import validate_upload
from app.import_card import ParseError, parse_card_file, read_cells
from .fixtures import make_xlsx, make_csv

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def legacy_workbook(content):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, 'w') as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == 'xl/styles.xml':
                root = ET.fromstring(data)
                for xf in root.iter(NS + 'xf'):
                    xf.set('styleId', '7')
                    xf.set('xfid', xf.attrib.pop('xfId', '0'))
                data = ET.tostring(root)
            elif info.filename == 'xl/worksheets/sheet1.xml':
                root = ET.fromstring(data)
                root.find(NS + 'dimension').set('ref', 'A1:A1')
                data = ET.tostring(root)
            target.writestr(info, data)
    return output.getvalue()


def hana_usage(*, amount=10000, fee=300, status='정상', card='****1234'):
    return [1, '2026-10-09', '2026-10-11', card, '해외', '해외일시불',
            '00001111', '합성상점', None, '100', amount, status, fee, 0, '2026-11-25', 0]


def hana_foreign(*, amount=10300, card='****1234'):
    return [1, '2026-10-09', card, '00001111', '합성상점', 1000.5,
            10000, 7, 1300, 300, '일본', amount]


def ibk_row(*, kind='외화', amount=12000, cancelled=0):
    return [kind, '해외일시불', datetime.datetime(2026, 10, 9, 12), '****6789',
            '합성카드', '합성상점', amount, '1,234.500 (JPY)', '합성상품', '일시불',
            0, 0, 0, 'A0000123', 0, 0, cancelled, None, '2026-10-11', None, None]


@pytest.mark.parametrize('headered', [False, True])
def test_ibk_print_styles_dimensions_dates_original_ids_and_amounts(headered):
    values = ibk_row()
    content = legacy_workbook(make_xlsx([values], headers=IBK_PRINT, headered=headered))
    parsed, inspection = validate_upload(content, 'renamed.xlsx')
    assert inspection['transaction_rows'] == 1
    row = parsed.rows[0]
    assert row.issuer == '기업' and row.card_tail == '6789'
    assert row.approval_number == 'A0000123'
    assert row.approval_date == '2026-10-09' and row.posting_date == '2026-10-11'
    assert row.amount_krw == 12000 and row.foreign_amount == '1234.500'
    assert row.foreign_currency == 'JPY'
    assert row.source_row == read_cells(content)[1][int(headered)]
    assert row.source_row[:19] == values[:19]


def test_leading_blank_ibk_header_and_total_are_not_transactions():
    content = legacy_workbook(make_xlsx(
        [[''] + ibk_row(), ['', '', '총 계'] + [None] * 19], headers=[''] + list(IBK_PRINT)))
    parsed, _ = validate_upload(content, 'print.xlsx')
    assert len(parsed.rows) == 1 and parsed.rows[0].amount_krw == 12000


def test_partial_cancel_uses_cancel_column_without_changing_source_purchase_amount():
    values = ibk_row(kind='취소또는할인', cancelled=3000)
    content = make_xlsx([values], headers=IBK_PRINT)
    row = validate_upload(content, 'cancel.xlsx')[0].rows[0]
    assert row.amount_krw == -3000 and row.transaction_direction == 'cancellation'
    assert row.source_row[6] == 12000 and row.source_row[16] == 3000


def test_hana_usage_headers_footer_and_positive_cancel():
    rows = [hana_usage(), hana_usage(amount=2300, fee=0, status='취소'), ['안내 문구']]
    parsed, _ = validate_upload(make_csv(rows, headers=HANA_USAGE), 'anything.csv')
    assert [r.amount_krw for r in parsed.rows] == [10300, -2300]
    assert all(r.issuer == '하나' for r in parsed.rows)
    assert parsed.rows[0].approval_date == '2026-10-09'
    assert parsed.rows[0].posting_date == '2026-10-11'
    assert parsed.rows[0].approval_number == '00001111'


def test_hana_foreign_billed_total_is_not_principal_plus_fee_twice():
    parsed, _ = validate_upload(make_csv([hana_foreign(), ['안내 문구']], headers=HANA_FOREIGN), 'foreign.csv')
    row = parsed.rows[0]
    assert row.issuer == '하나' and row.card_kind == '해외'
    assert row.amount_krw == 10300
    assert row.foreign_amount == '1000.5' and row.foreign_currency == ''
    assert row.posting_date == ''


@pytest.mark.parametrize('headers,values', [(HANA_USAGE, hana_usage(card='')),
                                         (HANA_FOREIGN, hana_foreign(card=''))])
def test_missing_account_in_a_real_transaction_still_blocks(headers, values):
    with pytest.raises(StoreError) as exc:
        validate_upload(make_csv([values], headers=headers), 'missing.csv')
    assert exc.value.code == 'CARD_ACCOUNT_REQUIRED'


def test_partial_header_signature_does_not_invent_an_issuer():
    headers = list(HANA_FOREIGN)
    headers[-1] = '다른 금액'
    with pytest.raises((StoreError, ParseError)):
        validate_upload(make_csv([hana_foreign()], headers=headers), 'unknown.csv')


def test_formula_outside_incorrect_dimensions_is_rejected_even_after_parser_cache():
    content = legacy_workbook(make_xlsx([ibk_row(), ['=1+1']], headers=IBK_PRINT))
    parse_card_file(content, 'formula.xlsx')
    with pytest.raises(StoreError) as exc:
        validate_upload(content, 'formula.xlsx')
    assert exc.value.code == 'UNSAFE_FORMULA'


@pytest.mark.parametrize('reverse', [False, True])
def test_overlapping_hana_views_reuse_purchase_and_preserve_manual_decision(reverse):
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    sources = [make_csv([hana_usage()], headers=HANA_USAGE),
               make_csv([hana_foreign()], headers=HANA_FOREIGN)]
    if reverse:
        sources.reverse()
    first = pipe.receive(sources[0], 'first.csv')
    row = pipe.get_batch(first['batch_id'])['rows'][0]
    pipe.save_decision(row['transaction_id'], row['revision'], item='기타경비',
                       display_tab_id='unclassified', tab_validator=lambda _: True,
                       request_id='manual')
    before = pipe.store.conn.execute('SELECT * FROM transactions').fetchall()
    second = pipe.receive(sources[1], 'second.csv')
    assert second['inserted'] == 0 and second['already_present'] == 1
    assert pipe.store.conn.execute('SELECT * FROM transactions').fetchall() == before
    assert pipe.receive(sources[1], 'retry.csv')['reused'] is True


def test_same_approval_with_changed_billed_total_preserves_source_conflict():
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    pipe.receive(make_csv([hana_usage()], headers=HANA_USAGE), 'first.csv')
    second = pipe.receive(make_csv([hana_foreign(amount=11300)], headers=HANA_FOREIGN), 'second.csv')
    assert second['conflicts'] == 1 and second['inserted'] == 0
    assert pipe.store.conn.execute("SELECT COUNT(*) FROM transactions WHERE conflict_reason<>''").fetchone()[0] == 1


def test_conflicting_explicit_posting_dates_preserve_source_conflict():
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    first = hana_usage()
    second = hana_usage()
    second[2] = '2026-10-12'
    pipe.receive(make_csv([first], headers=HANA_USAGE), 'first.csv')
    result = pipe.receive(make_csv([second], headers=HANA_USAGE), 'second.csv')
    assert result['conflicts'] == 1 and result['inserted'] == 0
    assert pipe.store.conn.execute("SELECT COUNT(*) FROM transactions WHERE conflict_reason<>''").fetchone()[0] == 1


def legacy_domestic(*, merchant='합성상점', amount=10000, merchant_number='100'):
    return make_csv([['하나','2026-10-09','****1234','00001111',merchant,amount,merchant_number]],
                    headers=['카드사','이용일','카드번호','승인번호','가맹점명','승인금액','가맹점번호'])


def domestic_usage(*, merchant='합성상점', amount=10000, merchant_number='100'):
    row=hana_usage(amount=amount,fee=0)
    row[4:6]=['국내','국내일시불']
    row[7]=merchant
    row[9]=merchant_number
    return make_csv([row],headers=HANA_USAGE)


def test_missing_legacy_posting_date_is_not_a_conflicting_explicit_date():
    pipe=Pipeline(sqlite3.connect(':memory:',isolation_level=None))
    pipe.receive(legacy_domestic(),'legacy.csv')
    original=pipe.store.conn.execute('SELECT * FROM transactions').fetchall()
    result=pipe.receive(domestic_usage(),'usage.csv')
    assert result['conflicts']==0
    assert result['already_present']==1
    assert pipe.store.conn.execute('SELECT * FROM transactions').fetchall()==original


@pytest.mark.parametrize('merchant,number,reused',[
    ('합성상점 서울','100',True),
    ('합성상점 서울','999',False),
    ('다른상점','100',False),
    ('합성상점 서울','',False),
])
def test_merchant_label_extension_requires_same_explicit_source_merchant_number(merchant,number,reused):
    pipe=Pipeline(sqlite3.connect(':memory:',isolation_level=None))
    pipe.receive(legacy_domestic(),'legacy.csv')
    before=pipe.store.conn.execute('SELECT * FROM transactions').fetchall()
    result=pipe.receive(domestic_usage(merchant=merchant,merchant_number=number),'usage.csv')
    assert result['already_present']==int(reused)
    assert result['conflicts']==int(not reused)
    assert pipe.store.conn.execute('SELECT * FROM transactions ORDER BY created_at,transaction_id').fetchall()[0]==before[0]


def test_persisted_false_export_conflict_is_recognized_readonly_and_real_merchant_difference_stays():
    from app.card_export_profiles import redundant_purchase_conflicts
    pipe=Pipeline(sqlite3.connect(':memory:',isolation_level=None))
    pipe.receive(legacy_domestic(),'legacy.csv')
    # Reproduce an old release's strict posting comparison.
    from unittest.mock import patch
    original=pipe.store.conn.execute('SELECT transaction_id FROM transactions').fetchone()[0]
    with patch('app.card_export_profiles.existing_purchase',return_value=(original,False)):
        pipe.receive(domestic_usage(),'usage.csv')
    pipe.receive(domestic_usage(merchant='다른상점'),'changed.csv')
    before=list(pipe.store.conn.iterdump())
    equivalent=redundant_purchase_conflicts(pipe.store.conn)
    assert len(equivalent)==1
    assert list(pipe.store.conn.iterdump())==before


def test_ibk_headered_and_headerless_source_views_keep_one_financial_purchase():
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    row = ibk_row()
    a = legacy_workbook(make_xlsx([row], headers=IBK_PRINT))
    b = legacy_workbook(make_xlsx([row], headered=False))
    pipe.receive(a, 'first.xlsx')
    result = pipe.receive(b, 'second.xlsx')
    assert result['inserted'] == 0 and result['already_present'] == 1
    assert pipe.store.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 1


def test_refunds_with_different_amounts_are_not_collapsed_as_matching_purchases():
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    pipe.receive(make_csv([hana_usage()], headers=HANA_USAGE), 'purchase.csv')
    result = pipe.receive(make_csv([hana_usage(amount=2000, fee=0, status='취소'),
                                   hana_usage(amount=3000, fee=0, status='취소')],
                                  headers=HANA_USAGE), 'refunds.csv')
    assert result['row_count'] == 2
    rows = pipe.store.conn.execute("SELECT amount_krw FROM transactions WHERE transaction_direction='cancellation'").fetchall()
    assert sorted(r[0] for r in rows) == [-3000, -2000]


def _approval_source(*, approval='00001111', amount=10000, merchant='합성상점'):
    return make_csv([['하나', '2026-10-09', '****1234', approval, merchant, amount, '100']],
                    headers=['카드사', '이용일', '카드번호', '승인번호', '가맹점명', '승인금액', '가맹점번호'])


def _acquired_foreign(*, approval='00001111', amount=10300):
    row = hana_foreign(amount=amount)
    row[3] = approval
    return make_csv([row], headers=HANA_FOREIGN)


@pytest.mark.parametrize('reverse', [False, True])
def test_hana_leading_zero_approval_variant_is_one_cost_not_two(reverse):
    # The approval source pads the number (00001111); the acquired view does not
    # (1111). They are one purchase, so the second view must not book a second cost.
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    sources = [_approval_source(approval='00001111'), _acquired_foreign(approval='1111')]
    if reverse:
        sources.reverse()
    pipe.receive(sources[0], 'first.csv')
    result = pipe.receive(sources[1], 'second.csv')
    assert result['conflicts'] == 1 and result['inserted'] == 0
    conn = pipe.store.conn
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE conflict_reason<>''").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE conflict_reason='' AND parse_error=''").fetchone()[0] == 1
    # Comparison-only normalization never rewrites either stored approval number.
    assert {r[0] for r in conn.execute('SELECT approval_number FROM transactions')} == {'00001111', '1111'}


def test_all_zero_approval_number_cannot_establish_a_cross_view_match():
    from app.normalize import normalize_approval_number
    assert normalize_approval_number('000000') == ''
    assert normalize_approval_number('  00001111 ') == '1111'
    assert normalize_approval_number('A000123') == 'A000123'
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    # Different zero padding keeps the raw identities distinct, so any collapse
    # could only come from the normalized cross-view key — which must stay empty.
    pipe.receive(_approval_source(approval='000000'), 'first.csv')
    result = pipe.receive(_acquired_foreign(approval='0000000'), 'second.csv')
    assert result['conflicts'] == 0
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE conflict_reason='' AND parse_error=''").fetchone()[0] == 2


def test_same_normalized_approval_with_multiples_amount_stays_separate():
    # A reused approval number across purchases differs by multiples, not by FX/fee.
    pipe = Pipeline(sqlite3.connect(':memory:', isolation_level=None))
    pipe.receive(_approval_source(approval='00001111', amount=10000), 'first.csv')
    result = pipe.receive(_acquired_foreign(approval='1111', amount=900000), 'second.csv')
    assert result['conflicts'] == 0
    assert pipe.store.conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE conflict_reason='' AND parse_error=''").fetchone()[0] == 2
