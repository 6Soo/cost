"""검증된 카드사 열 구성과 분할 취소를 합성 자료로 보호한다."""
import pytest
from app.import_card import parse_card_file
from app.classify import classify_transaction
from app.rules import normalize_rule
from app import StoreError
from .fixtures import make_xlsx


KB_FOREIGN=['매입일','승인일','부서번호','부서명','카드번호','이용자명','결제방법',
            '가맹점명','이용국가','도시명','통화코드','현지이용금액','미화환산금액',
            '적용환율','결제원금','수수료','총결제금액']
HAN=['NO','이용일','이용시간','카드번호','승인번호','승인금액','승인취소금액',
     '가맹점명','업종명','가맹점번호','가맹점사업자번호','이용구분','할부기간',
     '매입','매입금액','매출취소금액','매입일','상태','부가세','하위몰정보']


def test_foreign_total_won_and_decimal_are_separate():
    row=['2026-04-10','2026-04-08','','','****1234','','일시불','합성가맹점','','','JPY',
         '1234.56','','',10000,300,10300]
    parsed=parse_card_file(make_xlsx([row],headers=KB_FOREIGN),'renamed.xlsx',use_cache=False).rows[0]
    assert parsed.issuer=='국민'
    assert parsed.card_kind=='해외'
    assert parsed.amount_krw==10300
    assert parsed.foreign_amount=='1234.56'
    assert parsed.foreign_currency=='JPY'


def test_hana_preamble_and_purchase_cancel_components():
    row=[1,'2026-04-08','','****1234','7777',100000,30000,'합성가맹점','','','',
         '국내','','',70000,'','2026-04-10','정상',0,'']
    content=make_xlsx([[''] for _ in range(5)]+[HAN,row],headers=[],headered=False)
    parsed=parse_card_file(content,'renamed.xlsx',use_cache=False)
    assert [r.amount_krw for r in parsed.rows]==[100000,-30000]
    assert [r.transaction_direction for r in parsed.rows]==['purchase','cancellation']
    assert parsed.rows[1].original_approval_number=='7777'
    assert all(r.issuer=='하나' for r in parsed.rows)


def test_corporate_real_headerless_shape():
    row=['매출','해외','2026-04-08 12:30:00','****1234','','합성가맹점',10300,
         '1234.56 JPY','','','','','','7777','','','','','','','']
    parsed=parse_card_file(make_xlsx([row],headered=False),'renamed.xlsx',use_cache=False).rows[0]
    assert parsed.issuer=='기업'
    assert parsed.card_tail=='1234'
    assert parsed.amount_krw==10300
    assert parsed.foreign_amount=='1234.56'


def test_disagreeing_rules_need_a_person():
    rules=[normalize_rule({'conditions':{'merchant_normalized':'합성상점'},'effects':{'item':item}})
           for item in ['숙박비','항공료']]
    result=classify_transaction({'merchant':'합성상점'},rules=rules)
    assert result['classification_state']=='needs_review'
    assert result['classification_source']=='rule_conflict'


def test_merchant_rule_cannot_assign_future_trips():
    with pytest.raises(StoreError):
        normalize_rule({'conditions':{'merchant_normalized':'agoda'},
                        'effects':{'item':'숙박비','display_tab_id':'trip-a'}})
