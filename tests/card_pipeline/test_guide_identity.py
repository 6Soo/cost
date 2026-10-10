import json

from app.guide_identity import (
    IDENTITY_VERSION,
    guide_identities,
    identity_digest,
    load_alias_registry,
    match_passenger,
    normalize_name_part,
)

TRIPS = [{"prepared_by_name": "김철수", "assignee_source": "manual"}]


def _registry(aliases):
    return {"version": 1, "guides": [{"assignee_name": "김철수", "aliases": aliases}]}


def _identities(aliases=None):
    registry = _registry(aliases or [{"surname": "KIM", "given_name": "CHULSOO"}])
    return guide_identities(TRIPS, "", registry)


def test_normalize_name_part_rules():
    assert normalize_name_part(None) == ""
    assert normalize_name_part("  o'Brien-Lee_x.  ") == "OBRIEN LEE X"
    assert normalize_name_part("Do·Hyun,’a`") == "DO HYUNA"
    assert normalize_name_part("ｋｉｍ  chul") == "KIM CHUL"


def test_exact_normalized_match_ignores_case_spacing_hyphen_apostrophe():
    identities = _identities([{"surname": "O'KIM", "given_name": "CHUL-SOO"}])
    result = match_passenger({"surname": "  okim ", "given_name": "chul   soo"}, identities)
    assert result == {"status": "guide", "guide": "김철수"}


def test_partial_given_name_does_not_match():
    result = match_passenger({"surname": "KIM", "given_name": "CHUL"}, _identities())
    assert result["status"] != "guide"


def test_surname_only_does_not_match():
    result = match_passenger({"surname": "KIM", "given_name": ""}, _identities())
    assert result == {"status": "unknown", "guide": ""}


def test_given_name_only_does_not_match():
    result = match_passenger({"surname": "", "given_name": "CHULSOO"}, _identities())
    assert result == {"status": "unknown", "guide": ""}


def test_spacing_inside_latin_given_name_is_significant():
    identities = _identities([{"surname": "DOH", "given_name": "YUN"}])
    result = match_passenger({"surname": "DO", "given_name": "HYUN"}, identities)
    assert result == {"status": "not_guide", "guide": ""}
    result = match_passenger({"surname": "DOH", "given_name": "YUN"}, identities)
    assert result == {"status": "guide", "guide": "김철수"}


def test_hangul_exact_match_with_and_without_space():
    identities = _identities()
    assert match_passenger({"surname": "김", "given_name": "철수"}, identities) == {
        "status": "guide", "guide": "김철수"}
    assert match_passenger({"surname": "김철수", "given_name": "  "}, identities) == {
        "status": "unknown", "guide": ""}
    assert match_passenger({"surname": "김", "given_name": "철 수"}, identities) == {
        "status": "guide", "guide": "김철수"}


def test_hangul_different_name_is_not_guide():
    result = match_passenger({"surname": "이", "given_name": "영희"}, _identities())
    assert result == {"status": "not_guide", "guide": ""}


def test_latin_without_registered_alias_is_unknown():
    identities = guide_identities(TRIPS, "", {})
    result = match_passenger({"surname": "KIM", "given_name": "CHULSOO"}, identities)
    assert result == {"status": "unknown", "guide": ""}


def test_latin_with_alias_but_different_person_is_not_guide():
    result = match_passenger({"surname": "LEE", "given_name": "MINHO"}, _identities())
    assert result == {"status": "not_guide", "guide": ""}


def test_latin_with_one_identity_lacking_alias_is_unknown():
    trips = [
        {"prepared_by_name": "김철수", "assignee_source": "manual"},
        {"prepared_by_name": "박영희", "assignee_source": "manual"},
    ]
    registry = _registry([{"surname": "KIM", "given_name": "CHULSOO"}])
    identities = guide_identities(trips, "", registry)
    result = match_passenger({"surname": "LEE", "given_name": "MINHO"}, identities)
    assert result == {"status": "unknown", "guide": ""}


def test_empty_identities_is_unknown():
    assert match_passenger({"surname": "KIM", "given_name": "CHULSOO"}, []) == {
        "status": "unknown", "guide": ""}


def test_untrusted_provenance_yields_no_identity():
    trips = [
        {"prepared_by_name": "김철수", "assignee_source": "seed"},
        {"prepared_by_name": "박영희", "assignee_source": ""},
        {"prepared_by_name": "최민수", "assignee_source": "unknown-thing"},
        {"prepared_by_name": "   ", "assignee_source": "manual"},
    ]
    assert guide_identities(trips, "", {}) == []


def test_owner_assignee_name_alone_yields_identity():
    identities = guide_identities([], "김철수", {})
    assert identities == [{
        "assignee_name": "김철수",
        "normalized": "김철수",
        "sources": ["owner_profile"],
        "aliases": [],
        "trusted": True,
    }]


def test_registry_entry_without_trip_or_owner_yields_no_identity():
    registry = _registry([{"surname": "KIM", "given_name": "CHULSOO"}])
    assert guide_identities([], "", registry) == []


def test_registry_alias_attaches_and_merges_duplicate_entries():
    registry = {"version": 1, "guides": [
        {"assignee_name": "김철수", "aliases": [{"surname": "KIM", "given_name": "CHULSOO"}]},
        {"assignee_name": "김 철수", "aliases": [{"surname": "KIM", "given_name": "CHULSOO"},
                                              {"surname": "KIM", "given_name": "CHUL SOO"}]},
    ]}
    identities = guide_identities(TRIPS, "김철수", registry)
    assert len(identities) == 1
    assert identities[0]["sources"] == ["owner_profile", "registry", "trip:manual"]
    assert identities[0]["aliases"] == [
        {"surname": "KIM", "given_name": "CHUL SOO"},
        {"surname": "KIM", "given_name": "CHULSOO"},
    ]


def test_load_alias_registry_missing_file_returns_empty(tmp_path):
    assert load_alias_registry("") == {}
    assert load_alias_registry(None) == {}
    assert load_alias_registry(tmp_path / "missing.json") == {}


def test_load_alias_registry_accepts_bom(tmp_path):
    path = tmp_path / "registry.json"
    data = _registry([{"surname": "KIM", "given_name": "CHULSOO"}])
    path.write_bytes("﻿".encode("utf-8") + json.dumps(data, ensure_ascii=False).encode("utf-8"))
    assert load_alias_registry(path) == data


def test_load_alias_registry_malformed_json_raises(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text('{"version": 1, "guides": [', encoding="utf-8")
    try:
        load_alias_registry(path)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_load_alias_registry_wrong_shape_raises(tmp_path):
    bad_documents = [
        [],
        {"version": 1, "guides": {}},
        {"version": 1, "guides": [{"assignee_name": ""}]},
        {"version": 1, "guides": [{"assignee_name": "김철수", "aliases": [{"surname": "KIM"}]}]},
        {"version": 1, "guides": [{"assignee_name": "김철수", "aliases": "KIM"}]},
    ]
    for index, document in enumerate(bad_documents):
        path = tmp_path / f"registry-{index}.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        try:
            load_alias_registry(path)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {document!r}")


def test_identity_digest_is_stable_and_tracks_aliases():
    first = identity_digest(_identities())
    assert first == identity_digest(_identities())
    assert len(first) == 64
    with_extra = _identities([
        {"surname": "KIM", "given_name": "CHULSOO"},
        {"surname": "KIM", "given_name": "CHUL SOO"},
    ])
    assert identity_digest(with_extra) != first
    assert IDENTITY_VERSION == "guide-identity-v2"


def _reservation_guides():
    return [
        {"id": 7, "nickname": "아슬란", "real_name": "김철수", "flight_name_en": "KIM  Chulsoo", "status": "active"},
        {"id": 8, "nickname": "무명", "real_name": None, "flight_name_en": None, "status": "active"},
        {"id": 9, "nickname": "퇴사", "real_name": "박영희", "flight_name_en": "PARK YOUNGHEE", "status": "inactive"},
    ]


def test_reservation_identities_use_active_guides_and_the_registered_flight_name():
    from app.guide_identity import reservation_identities
    identities = reservation_identities(_reservation_guides())
    assert [i["assignee_name"] for i in identities] == ["guide:7", "guide:8"]
    assert identities[0]["aliases"] == [{"surname": "KIM", "given_name": "CHULSOO"}]
    assert identities[0]["normalized"] == "김철수" and identities[1]["aliases"] == []
    assert all(i["sources"] == ["reservation"] for i in identities)


def test_reservation_identity_matching_is_exact_and_unknown_when_a_guide_has_no_flight_name():
    from app.guide_identity import reservation_identities
    identities = reservation_identities(_reservation_guides())
    assert match_passenger({"surname": "kim", "given_name": "chulsoo"}, identities)["guide"] == "guide:7"
    # guide 8 has no registered flight name, so a different Latin name cannot be ruled out
    assert match_passenger({"surname": "LEE", "given_name": "YOUNGHEE"}, identities)["status"] == "unknown"
    assert match_passenger({"surname": "KIM", "given_name": "CHUL"}, identities)["status"] == "unknown"
    only_named = reservation_identities(_reservation_guides()[:1])
    assert match_passenger({"surname": "KIM", "given_name": "CHUL"}, only_named)["status"] == "not_guide"
    assert match_passenger({"surname": "김", "given_name": "철수"}, identities)["guide"] == "guide:7"
    assert match_passenger({"surname": "KIM", "given_name": "CHULSOO"}, reservation_identities(
        [dict(_reservation_guides()[0], status="inactive")]))["status"] == "unknown"
