"""Description rules must change the displayed field and respect manual edits."""
from webapp.classification_rules import normalize_draft, plan_effect


def test_description_rule_targets_the_displayed_description_and_becomes_noop():
    rule = normalize_draft({"conditions": {"merchant_normalized": "SYN HOTEL"},
                            "effects": {"description_template": "숙박 · {merchant}"}},
                           learning_case_id="synthetic-case", rule_id="synthetic-rule")
    row = {"description": "원래 내용", "source_merchant": "SYN HOTEL",
           "amount_krw": 1000, "occurred_on": "2026-04-01"}
    changes = plan_effect(rule, row)
    assert changes == {"description": "숙박 · SYN HOTEL"}
    updated = {**row, **changes}
    assert plan_effect(rule, updated) == {}
    assert updated["source_merchant"] == row["source_merchant"]
    assert updated["amount_krw"] == row["amount_krw"]
    assert updated["occurred_on"] == row["occurred_on"]


def test_manual_description_lock_blocks_a_description_rule_but_keeps_item_change():
    rule = normalize_draft({"conditions": {"merchant_normalized": "SYN HOTEL"},
                            "effects": {"description_template": "자동 내용", "item": "숙박비"}},
                           learning_case_id="synthetic-case", rule_id="synthetic-rule")
    row = {"description": "직접 입력한 내용", "item": "기타"}
    assert plan_effect(rule, row, ("description",)) == {"item": "숙박비"}
