import hashlib
import io
import json

import pytest
import app.insurance_income_match as income_match

from app.insurance_income_match import (
    ManifestError,
    load_review_manifest,
    match_contract,
    match_masked_name,
)


def manifest(**changes):
    contract = {
        "contract_id": "synthetic-contract-1",
        "travel_start": "2026-03-01",
        "travel_end": "2026-03-05",
        "insured_count": 1,
        "insurance_status": "completed_or_expired",
        "trip_mapping_status": "mapped",
        "cost_trip_id": "trip_1",
        "already_registered": False,
        "source_pdf": "synthetic/source.pdf",
        "sha256": hashlib.sha256(b"synthetic source").hexdigest(),
        "items": [{"source_row": "row-1", "masked_name": "김*수", "status": "unresolved"}],
    }
    value = {"schema_version": 1, "kind": "synthetic", "created_at": "2026-01-01",
             "query_basis": "synthetic fixture", "notes": [], "contracts": [contract]}
    value.update(changes)
    return value


def test_load_returns_opaque_ids_and_fingerprint_without_source_reference(tmp_path):
    raw = json.dumps(manifest(), ensure_ascii=False).encode()
    path = tmp_path / "review.json"
    path.write_bytes(raw)
    loaded = load_review_manifest(path)
    assert loaded["fingerprint"] == hashlib.sha256(raw).hexdigest()
    assert loaded["contracts"][0]["rows"][0]["masked_name"] == "김*수"
    assert "synthetic-contract-1" not in repr(loaded)
    assert "source.pdf" not in repr(loaded)
    assert "row-1" not in repr(loaded)


@pytest.mark.parametrize(("pattern", "value", "expected"), [
    ("김*수", "김민수", True), ("김＊수", "김민수", True), ("김○수", "김민수", True),
    ("김*수", "김수", False), ("김*수", "김민수님", False),
    ("김x수", "김x수", True), ("김X수", "김X수", True), ("김엑스수", "김엑스수", True),
    ("김스수", "김스수", True), ("김×수", "김민수", True),
    ("가 나*", "가나수", True), ("*", "민수", False), ("김*수", "이민수", False),
    ("Kim *", "kimx", True), ("김[+]*", "김[+]민", True),
])
def test_masked_name_matching(pattern, value, expected):
    assert match_masked_name(pattern, value) is expected


def test_unicode_casefold_and_compatibility_normalization():
    assert match_masked_name("ＡＢ*Ｄ", "abcd")
    assert match_masked_name("Straße*", "STRASSEx")


def test_ambiguity_includes_cross_row_collisions_and_is_replay_safe():
    contract = {"rows": [{"review_row_id": "r1", "masked_name": "김*수"},
                         {"review_row_id": "r2", "masked_name": "김민*"}]}
    incomes = [{"ref": "i1", "fingerprint": "f1", "name": "김민수", "nickname": "별칭",
                "cells": {"C": "", "D": ""}, "trip_id": "t", "trip_name": "T", "date": "2026-03-02", "amount": 10}]
    before = json.dumps((contract, incomes), ensure_ascii=False, sort_keys=True)
    first = match_contract(contract, incomes)
    second = match_contract(contract, incomes)
    assert [row["match_state"] for row in first["rows"]] == ["ambiguous", "ambiguous"]
    assert first == second
    assert json.dumps((contract, incomes), ensure_ascii=False, sort_keys=True) == before


def test_match_name_nickname_and_c_d_fields_but_not_arbitrary_cells():
    c = {"rows": [{"review_row_id": "r", "masked_name": "박*희"}]}
    for income in ({"name": "다른이", "nickname": "박은희"},
                   {"name": "다른이", "cells": {"C": "박은희"}},
                   {"name": "다른이", "cells": {"D": "박은희"}}):
        assert match_contract(c, [income])["rows"][0]["match_state"] == "matched"
    assert match_contract(c, [{"name": "다른이", "cells": {"A": "박은희"}}])["rows"][0]["match_state"] == "unmatched"


def test_manifest_rejects_duplicate_keys_bad_digest_and_duplicate_source_rows(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ManifestError):
        load_review_manifest(p)
    value = manifest()
    value["contracts"][0]["sha256"] = "../bad"
    p.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_review_manifest(p)
    value = manifest()
    value["contracts"][0]["items"].append(dict(value["contracts"][0]["items"][0]))
    p.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_review_manifest(p)


@pytest.mark.parametrize("change", [
    {"schema_version": 2},
    {"contracts": [{**manifest()["contracts"][0], "travel_start": "2026-02-30"}]},
    {"contracts": [{**manifest()["contracts"][0], "travel_start": "2026-03-06"}]},
    {"contracts": [{**manifest()["contracts"][0], "insured_count": True}]},
    {"contracts": [{**manifest()["contracts"][0], "insured_count": 2}]},
])
def test_manifest_rejects_bad_schema_dates_and_insured_count(tmp_path, change):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(manifest(**change)), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_review_manifest(p)


def test_manifest_rejects_duplicate_contract_id_across_versions(tmp_path):
    value = manifest()
    second = dict(value["contracts"][0], sha256=hashlib.sha256(b"another version").hexdigest())
    value["contracts"].append(second)
    p = tmp_path / "duplicate.json"
    p.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_review_manifest(p)


def test_manifest_read_is_bounded_even_if_file_grows_after_stat(tmp_path, monkeypatch):
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * (income_match._MAX_BYTES + 10))

    class BoundedStream:
        def __init__(self):
            self.requested = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            self.requested = size
            return b"x" * size

    stream = BoundedStream()
    monkeypatch.setattr(income_match.Path, "open", lambda *_a, **_k: stream)
    with pytest.raises(ManifestError):
        load_review_manifest(path)
    assert stream.requested == income_match._MAX_BYTES + 1


def test_candidate_public_fields_exclude_cells():
    contract = {"rows": [{"review_row_id": "r", "masked_name": "김*수"}]}
    result = match_contract(contract, [{"ref": "i", "name": "김민수", "cells": {"C": "private-cell"}}])
    assert set(result["rows"][0]["matches"][0]) == {
        "ref", "fingerprint", "name", "nickname", "trip_id", "trip_name", "date", "amount"
    }
    assert "private-cell" not in repr(result)


def test_candidate_choices_are_capped_but_count_retains_total():
    contract = {"rows": [{"review_row_id": "r", "masked_name": "김*수"}]}
    incomes = [{"ref": str(i), "name": "김민수"} for i in range(25)]
    result = match_contract(contract, incomes)["rows"][0]
    assert result["match_state"] == "ambiguous"
    assert len(result["matches"]) == 20
    assert result["candidate_count"] == 25


def test_fixed_multi_mask_token_uses_visible_ends_and_bidirectional_uniqueness():
    contract = {'rows': [{'review_row_id': 'r', 'masked_name': '김***수'}]}
    assert match_masked_name('김***수', '김민수')
    assert match_masked_name('김***수', '김가나다수')
    assert not match_masked_name('김***수', '김수')
    assert not match_masked_name('김***수', '이민수')
    result = match_contract(contract, [{'name': '김민수', 'ref': 'i'}])['rows'][0]
    assert result['match_state'] == 'matched'
    assert result['candidate_count'] == 1 and result['mask_length_unknown']
    assert match_contract(contract,[{'name':'김민수'},{'name':'김가나다수'}])['rows'][0]['match_state']=='ambiguous'
    assert not match_masked_name('김*수', '김가나수')
    assert not match_masked_name('***', '김민수')


def test_repeated_mask_runs_are_bounded_and_visible_letters_remain_anchored():
    assert not match_masked_name(('가***' * 40) + '나', '가' * 100)
    assert match_masked_name('가**나**다', '가마나바다')
    assert not match_masked_name('가**나**다', '가마다나')
