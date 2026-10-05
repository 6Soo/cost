# -*- coding: utf-8 -*-
"""Synthetic tests for reviewed-source guidance.

No customer data, no production database: every case here is a temporary
directory holding the shared synthetic fixture bundle.
"""

from pathlib import Path

import pytest

from webapp.ledger_store import LedgerStore
from webapp.real_review import DecisionsStore, RealReviewService
from webapp.review_guidance import (CODE_BINDING_STALE, CODE_CANDIDATE_REQUIRED,
                                    CODE_NOTHING_TO_SAVE,
                                    CODE_PREVIEW_NOT_OWNED,
                                    CODE_REF_NOT_EXPENSE, CODE_REF_NOT_FOUND,
                                    CODE_REQUEST_ID_REUSED,
                                    CODE_REVISION_CONFLICT,
                                    CODE_TEXT_TOO_LONG, DESCRIPTION_MAX,
                                    GuidanceError, GuidanceService)
from webapp.tests import review_fixtures as fx


def expense_service(directory: Path):
    """A review service over one synthetic bundle, with a writable decisions db."""
    manifest = fx.write_case(directory, rows=2)
    service = RealReviewService(
        manifest, store=DecisionsStore(str(Path(directory) / "decisions.sqlite")))
    return service


def guidance_for(directory: Path, store: LedgerStore | None = None):
    service = expense_service(directory)
    store = store or LedgerStore(str(Path(directory) / "ledger.sqlite"))
    return GuidanceService(service, store), service, store


def first_ref(service) -> str:
    return service.model()["rows"][0]["ref"]


def first_key(service) -> str:
    return service.model()["rows"][0]["candidates"][0]["key"]


# ------------------------------------------------------------------- answers

def test_a_saved_note_is_there_when_the_page_reopens(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()

    saved = guidance.save(ref, binding, "식비였습니다", "식비", "점심", 0, "req-1")
    assert saved["revision"] == 1
    assert saved["source_ref_sha256"]

    # A second service over the same manifest and the same database: this is
    # what a reload does. The bundle is not rewritten — writing it again would
    # rebuild the xlsx and move its digest, so the reopened service would be
    # looking at a different bundle than the one that was answered.
    reopened = GuidanceService(
        RealReviewService(service.manifest, store=service.store),
        LedgerStore(str(tmp_path / "case" / "ledger.sqlite")))
    got = reopened.get(ref, binding)
    assert got["exists"] is True
    assert got["note"] == "식비였습니다"
    assert got["item"] == "식비"
    assert got["description"] == "점심"
    assert got["revision"] == 1


def test_an_item_alone_is_an_answer_without_a_note(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    saved = guidance.save(first_ref(service), service.binding(),
                          "", "교통", "택시", 0, "req-1")
    assert saved["revision"] == 1
    assert saved["item"] == "교통"


def test_an_empty_answer_is_refused(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    with pytest.raises(GuidanceError) as caught:
        guidance.save(first_ref(service), service.binding(), "", "", "", 0, "req-1")
    assert caught.value.code == CODE_NOTHING_TO_SAVE


def test_a_stale_revision_is_refused_and_a_retry_with_the_same_request_replays(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()

    first = guidance.save(ref, binding, "첫 답변", "식비", "", 0, "req-1")
    assert first["revision"] == 1

    # A second tab still holding revision 0 must not overwrite revision 1.
    with pytest.raises(GuidanceError) as caught:
        guidance.save(ref, binding, "다른 탭", "간식", "", 0, "req-2")
    assert caught.value.code == CODE_REVISION_CONFLICT

    # The retry of the request that did land returns that answer, not a conflict.
    replayed = guidance.save(ref, binding, "첫 답변", "식비", "", 0, "req-1")
    assert replayed["revision"] == 1
    assert guidance.get(ref, binding)["revision"] == 1

    # The same request id with a different body is refused rather than replayed.
    with pytest.raises(GuidanceError) as caught:
        guidance.save(ref, binding, "바뀐 내용", "면세", "", 1, "req-1")
    assert caught.value.code == CODE_REQUEST_ID_REUSED


def test_a_blank_request_id_is_refused(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    with pytest.raises(GuidanceError):
        guidance.save(first_ref(service), service.binding(), "답변", "", "", 0, "")


def test_a_note_over_the_limit_is_refused(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    with pytest.raises(GuidanceError) as caught:
        guidance.save(first_ref(service), service.binding(), "가" * 5000,
                      "", "", 0, "req-1")
    assert caught.value.code == CODE_TEXT_TOO_LONG


# ------------------------------------------------------------------ identity

def test_an_unknown_ref_is_refused_not_answered(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    with pytest.raises(GuidanceError) as caught:
        guidance.get("없는-원천", service.binding())
    assert caught.value.code == CODE_REF_NOT_FOUND
    with pytest.raises(GuidanceError) as caught:
        guidance.save("없는-원천", service.binding(), "답변", "", "", 0, "req-1")
    assert caught.value.code == CODE_REF_NOT_FOUND


def test_a_stale_binding_is_refused(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    with pytest.raises(GuidanceError) as caught:
        guidance.save(first_ref(service), "REVIEWSHA:not-the-live-binding",
                      "답변", "", "", 0, "req-1")
    assert caught.value.code == CODE_BINDING_STALE


# --------------------------------------------------------- nothing else moved

def test_a_guidance_save_writes_no_choice_and_no_ledger_row(tmp_path):
    guidance, service, store = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()
    before_choices = service.store.load(binding)
    before_row = store.get_row("r-1") if _has_row(store) else None

    import_card(store, row_id="r-1", merchant="가맹점", amount=-1000,
                batch="b1", request="imp-1")
    if before_row is None:
        before_item = row_item(store, "r-1")
    else:
        before_item = before_row.get("item")
    before_choices = service.store.load(binding)

    guidance.save(ref, binding, "식비였습니다", "식비", "점심", 0, "req-1")

    assert service.store.load(binding) == before_choices
    assert row_item(store, "r-1") == before_item
    # And the answer did land, so the comparison above is not vacuous.
    assert guidance.get(ref, binding)["exists"] is True


def _has_row(store):
    try:
        store.get_row("r-1")
        return True
    except Exception:
        return False


# --------------------------------------------------------------------- rules

def import_card(store, *, row_id, merchant, amount, batch, request):
    return store.import_row(
        row_id=row_id,
        fields={"display_tab_id": "t1", "occurred_on": "2026-04-09",
                "amount_krw": amount, "merchant": merchant,
                "event_kind": "purchase", "card_kind": "신용"},
        batch_id=batch, client_request_id=request, actor="owner")


def row_item(store, row_id):
    return store.get_row(row_id).get("item")


def row_description(store, row_id):
    return store.get_row(row_id).get("description")


def test_a_rule_from_a_source_changes_an_existing_row_and_a_future_import(tmp_path):
    guidance, service, store = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()
    key = first_key(service)
    merchant = service.model()["rows"][0]["candidates"][0]["merchant"]

    # One existing card row that the rule should match, and one it should not.
    existing = import_card(store, row_id="r-1", merchant=merchant,
                           amount=-9000, batch="b1", request="imp-1")
    import_card(store, row_id="r-other", merchant="다른가맹점", amount=-1000,
                batch="b1", request="imp-2")
    assert row_item(store, "r-1") != "식비"

    preview = guidance.rule_preview(ref, binding, "식비입니다", "식비", "점심",
                                    key, True, True, "req-1")
    # The measured plan, not a count the client made up.
    assert preview["counts"]["matched_rows"] == 1
    assert preview["counts"]["included_rows"] == 1
    assert [c["row_id"] for c in preview["candidates"]] == ["r-1"]
    # No transaction direction: it could not be proven from the source.
    assert preview["condition_basis"]["transaction_direction"] is None
    assert "transaction_direction" not in preview["draft"]["conditions"]
    # No travel placement, only what was typed.
    assert preview["draft"]["effects"] == {"item": "식비",
                                          "description_template": "점심"}
    assert preview["apply_future"] is True
    assert "card_import.import_row" in preview["future"]["path_connected"]

    applied = guidance.apply_rule(preview["preview_id"], True, True, "req-2",
                                 ref=ref, binding=binding)
    assert applied["rule_id"] == preview["rule_id"]
    assert row_item(store, "r-1") == "식비"
    # The owner's description must reach the editable description. This is the
    # contract: a template effect is projected onto the displayed description.
    assert preview["candidates"][0]["changes"]["description"] == "점심"
    assert row_description(store, "r-1") == "점심"
    # The unmatched row is untouched.
    assert row_item(store, "r-other") != "식비"

    # Future: the same rule reaches a card imported after the rule was active.
    import_card(store, row_id="r-2", merchant=merchant, amount=-9500,
                batch="b2", request="imp-3")
    assert row_item(store, "r-2") == "식비"
    assert row_description(store, "r-2") == "점심"


def test_turning_future_off_leaves_a_new_import_alone(tmp_path):
    guidance, service, store = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()
    key = first_key(service)
    merchant = service.model()["rows"][0]["candidates"][0]["merchant"]

    preview = guidance.rule_preview(ref, binding, "식비입니다", "식비", "",
                                    key, False, False, "req-1")
    assert preview["apply_future"] is False
    assert preview["future"]["path_connected"] == []
    guidance.apply_rule(preview["preview_id"], False, False, "req-2",
                        ref=ref, binding=binding)

    later = import_card(store, row_id="r-3", merchant=merchant, amount=-9000,
                        batch="b3", request="imp-9")
    assert row_item(store, "r-3") != "식비"


def test_a_preview_cannot_be_applied_from_another_source_or_without_one(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()
    other_ref = service.model()["rows"][1]["ref"]
    preview = guidance.rule_preview(ref, binding, "식비입니다", "식비", "",
                                    first_key(service), False, True, "req-1")

    with pytest.raises(GuidanceError) as caught:
        guidance.apply_rule(preview["preview_id"], False, True, "req-2",
                            ref=other_ref, binding=binding)
    assert caught.value.code == CODE_PREVIEW_NOT_OWNED

    # No ref and no binding at all is refused rather than taken on trust.
    with pytest.raises(GuidanceError) as caught:
        guidance.apply_rule(preview["preview_id"], False, True, "req-3")
    assert caught.value.code == CODE_PREVIEW_NOT_OWNED


def test_a_candidate_key_is_required_and_must_belong_to_the_source(tmp_path):
    guidance, service, _ = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()

    with pytest.raises(GuidanceError) as caught:
        guidance.rule_preview(ref, binding, "답변", "식비", "", "", False, True, "r")
    assert caught.value.code == CODE_CANDIDATE_REQUIRED

    with pytest.raises(GuidanceError):
        guidance.rule_preview(ref, binding, "답변", "식비", "", "없는후보",
                              False, True, "r2")


def test_a_deposit_source_makes_no_rule(tmp_path):
    # The parent's income fixture: a bundle whose reviewed source really is a
    # deposit, so the refusal path runs instead of being skipped.
    from webapp.tests.test_income_card_boundary import income_service

    service = income_service(tmp_path / "income")
    guidance = GuidanceService(service, LedgerStore(
        str(Path(tmp_path / "income") / "l.sqlite")))
    row = service.model()["rows"][0]
    assert (row["source"].get("block_kind") or "expense") == "income"
    with pytest.raises(GuidanceError) as caught:
        guidance.rule_preview(row["ref"], service.binding(), "답변", "입금", "",
                              row["candidates"][0]["key"], False, True, "r")
    assert caught.value.code == CODE_REF_NOT_EXPENSE
    # And it is not offered as rule-able to the UI either.
    assert guidance.get(row["ref"], service.binding())["can_make_rule"] is False


def test_a_source_case_is_bound_to_binding_ref_and_candidate(tmp_path):
    guidance, service, store = guidance_for(tmp_path / "case")
    ref, binding = first_ref(service), service.binding()
    first = guidance.rule_preview(ref, binding, "답변", "식비", "",
                                  first_key(service), False, True, "req-1")
    second = guidance.rule_preview(ref, binding, "답변", "식비", "",
                                   first_key(service), False, True, "req-2")
    # Same binding, ref and candidate: the same case, re-registered, not refused.
    assert first["case_id"] == second["case_id"]
    case = store.review_rule_case(first["case_id"])
    assert case["binding"] == binding
    assert case["candidate_key"] == first_key(service)
    # The proof carries derived facts only: no person, no reservation number.
    assert set(case["context"]) == {"source_ref_sha256", "merchant_normalized",
                                    "card_kind"}
    assert first["model_generated"] is False
    assert first["deterministic"] is True


def test_a_repeated_case_registration_with_other_context_is_refused(tmp_path):
    _, _, store = guidance_for(tmp_path / "case")
    once = store.register_review_rule_case(
        case_id="case-1", binding="b", source_ref="ref", candidate_key="key",
        context={"card_kind": "신용"})
    assert once["created"] is True
    again = store.register_review_rule_case(
        case_id="case-1", binding="b", source_ref="ref", candidate_key="key",
        context={"card_kind": "신용"})
    assert again["created"] is False
    from webapp.ledger_store import SaveError
    with pytest.raises(SaveError):
        store.register_review_rule_case(
            case_id="case-1", binding="b", source_ref="ref", candidate_key="key",
            context={"card_kind": "체크"})
