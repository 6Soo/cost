"""Tests for the merchant-to-item rule table builder."""

import copy
import json

from tools.p2_rules import merchant_table as mt

KEEP = "기존 항목 유지"


def prop(merchant, item, confidence="높음", rows=1, basis="base", run_id="r1"):
    return {
        "merchant": merchant,
        "item": item,
        "confidence": confidence,
        "rows": rows,
        "basis": basis,
        "run_id": run_id,
    }


# normalize_merchant

def test_normalize_merchant_whitespace_and_case():
    assert mt.normalize_merchant("  aeon   otaru  ") == "AEON OTARU"
    assert mt.normalize_merchant("\t STARBUCKS \n COFFEE \t") == "STARBUCKS COFFEE"


def test_normalize_merchant_strips_country_code():
    assert mt.normalize_merchant("AEON OTARU JP") == "AEON OTARU"
    assert mt.normalize_merchant("INN SEOUL KR") == "INN"
    assert mt.normalize_merchant("CAFE DE PARIS FR") == "CAFE DE PARIS"


def test_normalize_merchant_strips_region_after_country():
    assert mt.normalize_merchant("AEON OTARU HOKKAIDO JP") == "AEON OTARU"
    assert mt.normalize_merchant("INN BUSAN KR") == "INN"


def test_normalize_merchant_strips_region_without_country():
    assert mt.normalize_merchant("AEON OTARU HOKKAIDO") == "AEON OTARU"
    assert mt.normalize_merchant("INN BUSAN") == "INN"


def test_normalize_merchant_keeps_when_removal_would_empty():
    assert mt.normalize_merchant("TOKYO JP") == "TOKYO"
    assert mt.normalize_merchant("SEOUL KR") == "SEOUL"
    assert mt.normalize_merchant("HOKKAIDO") == "HOKKAIDO"


def test_normalize_merchant_keeps_region_in_middle():
    assert mt.normalize_merchant("TOKYO STATION HOTEL") == "TOKYO STATION HOTEL"


def test_normalize_merchant_none_and_empty():
    assert mt.normalize_merchant(None) == ""
    assert mt.normalize_merchant("") == ""
    assert mt.normalize_merchant("   ") == ""


# grouping / rules

def test_aliases_merge_into_one_rule_with_variants():
    result = mt.build_rule_table([
        prop("AEON OTARU", "식비"),
        prop("aeon otaru", "식비", rows=2, basis="second", run_id="r2"),
        prop("AEON OTARU", "식비", rows=3, basis="first", run_id="r1"),
    ])
    assert len(result["rules"]) == 1
    rule = result["rules"][0]
    assert rule["merchant_key"] == "AEON OTARU"
    assert rule["item"] == "식비"
    assert rule["rows"] == 6
    assert rule["variants"] == sorted(["AEON OTARU", "aeon otaru"])
    assert rule["basis"] == "first"
    assert rule["run_ids"] == ["r1", "r2"]
    assert result["stats"]["rules"] == 1


def test_keep_and_low_confidence_go_to_skipped():
    result = mt.build_rule_table([
        prop("AEON", KEEP),
        prop("STARBUCKS", "식비", confidence="낮음"),
    ])
    assert result["rules"] == []
    assert result["skipped"] == [
        {"merchant": "AEON", "reason": "keep"},
        {"merchant": "STARBUCKS", "reason": "low_confidence"},
    ]


def test_empty_merchant_goes_to_skipped():
    result = mt.build_rule_table([
        prop("   ", "식비"),
        prop(None, "식비"),
    ])
    assert result["rules"] == []
    assert [entry["reason"] for entry in result["skipped"]] == ["empty_merchant", "empty_merchant"]


# conflicts

def test_conflict_majority_rule_and_resolved():
    result = mt.build_rule_table([
        prop("SHOP X", "식비", rows=3, basis="food", run_id="r1"),
        prop("SHOP X", "교통비", rows=1, basis="ride", run_id="r2"),
    ])
    assert len(result["rules"]) == 1
    rule = result["rules"][0]
    assert rule["merchant_key"] == "SHOP X"
    assert rule["item"] == "식비"
    assert rule["rows"] == 4
    assert result["conflicts"] == [
        {"merchant_key": "SHOP X", "items": {"식비": 3, "교통비": 1}, "resolved": "식비"},
    ]


def test_conflict_below_two_thirds_unresolved():
    result = mt.build_rule_table([
        prop("SHOP X", "식비", rows=2),
        prop("SHOP X", "교통비", rows=2),
    ])
    assert result["rules"] == []
    assert result["conflicts"] == [
        {"merchant_key": "SHOP X", "items": {"식비": 2, "교통비": 2}, "resolved": None},
    ]


def test_conflict_exactly_two_thirds_resolves():
    result = mt.build_rule_table([
        prop("SHOP X", "식비", rows=2),
        prop("SHOP X", "교통비", rows=1),
    ])
    assert [rule["item"] for rule in result["rules"]] == ["식비"]


# min_rows, stats, ordering

def test_below_min_rows_goes_to_skipped():
    result = mt.build_rule_table([prop("AEON", "식비", rows=1)], min_rows=2)
    assert result["rules"] == []
    assert result["skipped"] == [{"merchant": "AEON", "reason": "below_min_rows"}]


def test_stats_counts():
    result = mt.build_rule_table([
        prop("KEEP MERCHANT", KEEP),
        prop("LOW MERCHANT", "식비", confidence="낮음"),
        prop("AEON OTARU", "식비", rows=3, basis="b1", run_id="r1"),
        prop("AEON OTARU", "식비", rows=2, basis="b2", run_id="r2"),
        prop("SHOP X", "식비", rows=3, basis="b3", run_id="r3"),
        prop("SHOP X", "교통비", rows=1, basis="b4", run_id="r4"),
    ])
    assert result["stats"] == {
        "proposals": 6,
        "rules": 2,
        "rule_rows": 9,
        "conflicts": 1,
        "skipped": 2,
    }


def test_rules_conflicts_skipped_are_sorted():
    result = mt.build_rule_table([
        prop("STARBUCKS", "식비"),
        prop("AEON", "식비"),
        prop("CAFE", "식비"),
        prop("ZETA", KEEP),
        prop("SHOP Y", "식비", rows=1),
        prop("SHOP Y", "교통비", rows=1),
        prop("SHOP X", "식비", rows=2),
        prop("SHOP X", "교통비", rows=2),
    ])
    assert [rule["merchant_key"] for rule in result["rules"]] == ["AEON", "CAFE", "STARBUCKS"]
    assert [entry["merchant_key"] for entry in result["conflicts"]] == ["SHOP X", "SHOP Y"]
    assert [entry["merchant"] for entry in result["skipped"]] == ["ZETA"]


def test_order_independence():
    proposals = [
        prop("STARBUCKS", "식비", rows=2, basis="s", run_id="rs"),
        prop("AEON OTARU", "식비", rows=4, basis="a", run_id="ra"),
        prop("AEON OTARU", "식비", rows=1, basis="a2", run_id="ra2"),
        prop("SHOP X", "식비", rows=3, basis="x", run_id="rx"),
        prop("SHOP X", "교통비", rows=1, basis="x2", run_id="rx2"),
    ]
    forward = mt.build_rule_table(proposals)
    backward = mt.build_rule_table(list(reversed(proposals)))
    assert forward["rules"] == backward["rules"]
    assert forward["conflicts"] == backward["conflicts"]
    assert forward["skipped"] == backward["skipped"]
    assert forward["stats"] == backward["stats"]


def test_input_list_not_mutated():
    proposals = [
        prop("AEON OTARU", "식비", rows=2),
        prop("SHOP X", "식비", rows=2),
        prop("SHOP X", "교통비", rows=2),
    ]
    snapshot = copy.deepcopy(proposals)
    mt.build_rule_table(proposals)
    assert proposals == snapshot


# to_jsonl

def test_to_jsonl_roundtrip_and_trailing_newline():
    rules = mt.build_rule_table([
        prop("AEON OTARU", "식비", rows=2, basis="서울 지점", run_id="r1"),
        prop("STARBUCKS", "식비", rows=1, basis="b", run_id="r2"),
    ])["rules"]
    text = mt.to_jsonl(rules)
    assert text.endswith("\n")
    lines = text.split("\n")
    assert lines[-1] == ""
    assert len(lines) - 1 == len(rules)
    for line, rule in zip(lines[:-1], rules):
        assert json.loads(line) == rule
        assert line.startswith('{"basis":')


def test_to_jsonl_empty():
    assert mt.to_jsonl([]) == ""
    assert mt.to_jsonl(mt.build_rule_table([])["rules"]) == ""
