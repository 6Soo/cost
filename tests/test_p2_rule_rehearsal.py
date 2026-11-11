from app.normalize import normalize_merchant
from tools.p2_rules.merchant_table import build_rule_table
from tools.p2_rules.rehearsal import make_drafts


def test_exact_rule_keys_preserve_city_suffixes_and_item_only_effects():
    proposals=[dict(merchant=name,item='교통비',confidence='높음',rows=1,basis='synthetic',run_id='synthetic')
               for name in ('SYNTHETIC TOKYO JP','SYNTHETIC OSAKA JP')]
    table=build_rule_table(proposals,normalizer=normalize_merchant)
    assert len(table['rules'])==2
    drafts=make_drafts(table)
    assert {d['conditions']['merchant_normalized'] for d in drafts}=={'synthetic tokyo jp','synthetic osaka jp'}
    assert all(d['effects']=={'item':'교통비'} and d['conditions']['transaction_direction']=='purchase' for d in drafts)
