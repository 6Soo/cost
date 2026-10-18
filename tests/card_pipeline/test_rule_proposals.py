import pytest

from app.rule_proposals import AuditLog, apply, parse, propose


def row(tx, **over):
    base = {"transaction_id": tx, "merchant": "CONVI-SYN", "item": "", "decided": False,
            "amount_krw": 4500, "occurred_on": "2027-08-02"}
    base.update(over)
    return base


ROWS = [row("t1"), row("t2"), row("t3", merchant="OTHER-SYN"), row("t4", decided=True, item="숙박비")]
FOCUS = {"transaction_id": "t1", "merchant": "CONVI-SYN"}


@pytest.mark.parametrize("text, kind", [
    ("이 가맹점은 앞으로 현지잡비로 분류해 줘", "MERCHANT_RULE"),
    ("같은 가맹점 식비로 분류해 줘", "MERCHANT_RULE"),
    ("이 건만 식비로 분류해 줘", "THIS_ONLY"),
    ("이 거래는 회사 경비 아님", "NOT_COMPANY"),
    ("금액을 9999로 바꿔 줘", "REJECTED_ORIGINAL_EDIT"),
    ("날짜 수정해 줘", "REJECTED_ORIGINAL_EDIT"),
    ("잘 부탁해", "NOT_UNDERSTOOD"),
])
def test_fixed_phrasings_map_to_a_kind_and_others_do_nothing(text, kind):
    assert parse(text, merchant_hint="CONVI-SYN")["kind"] == kind


def test_merchant_rule_previews_only_unconfirmed_rows_of_that_merchant():
    proposal = propose("이 가맹점은 앞으로 현지잡비로 분류해 줘", rows=ROWS, focus=FOCUS)
    assert proposal["status"] == "proposed"
    assert [c["transaction_id"] for c in proposal["changes"]] == ["t1", "t2"]
    assert all(c["after_item"] == "현지잡비" for c in proposal["changes"])
    assert proposal["skipped_decided"] == 1  # t4 is the same merchant but already decided


def test_agoda_named_merchant_instruction_only_matches_actual_agoda_rows():
    text = '아고다 결제는 숙박비로 분류하고, 예약 이용기간으로 여행을 찾아줘.'
    assert parse(text, merchant_hint='AGODA.COM') == {
        'kind': 'MERCHANT_RULE', 'item': '숙박비', 'merchant': 'AGODA.COM'}
    assert parse(text, merchant_hint='OTHER-SYN')['kind'] == 'NOT_UNDERSTOOD'
    rows = [row('a', merchant='AGODA.COM'), row('b', merchant='AGODA.COM'),
            row('c', merchant='OTHER-SYN', item='')]
    proposal = propose(text, rows=rows, focus={'transaction_id': 'a', 'merchant': 'AGODA.COM'})
    assert [c['transaction_id'] for c in proposal['changes']] == ['a', 'b']


def test_decided_rows_are_counted_and_never_changed(tmp_path):
    rows = [row("t1"), row("t4", merchant="CONVI-SYN", decided=True, item="숙박비")]
    proposal = propose("이 가맹점은 앞으로 현지잡비로 분류해 줘", rows=rows, focus=FOCUS)
    assert proposal["skipped_decided"] == 1
    apply(proposal, approved=True, approved_by="owner", rows=rows, audit=AuditLog(tmp_path / "a.json"))
    assert rows[1]["item"] == "숙박비"


def test_nothing_changes_without_explicit_approval(tmp_path):
    proposal = propose("이 건만 식비로 분류해 줘", rows=ROWS, focus=FOCUS)
    with pytest.raises(PermissionError, match="APPROVAL_REQUIRED"):
        apply(proposal, approved=False, approved_by="owner", rows=ROWS, audit=AuditLog(tmp_path / "a.json"))
    assert ROWS[0]["item"] == ""


def test_apply_changes_only_classification_and_keeps_amount_date_and_id(tmp_path):
    rows = [row("t1")]
    proposal = propose("이 건만 식비로 분류해 줘", rows=rows, focus=FOCUS)
    result = apply(proposal, approved=True, approved_by="owner", rows=rows, audit=AuditLog(tmp_path / "a.json"))
    assert result == {"status": "APPLIED", "applied": ["t1"]}
    assert rows[0] == {**row("t1"), "item": "식비"}


def test_second_approval_of_same_proposal_is_a_no_op(tmp_path):
    audit = AuditLog(tmp_path / "a.json")
    rows = [row("t1")]
    proposal = propose("이 건만 식비로 분류해 줘", rows=rows, focus=FOCUS)
    apply(proposal, approved=True, approved_by="owner", rows=rows, audit=audit)
    assert apply(proposal, approved=True, approved_by="owner", rows=rows, audit=audit)["status"] == "ALREADY_APPLIED"
    assert len(audit.entries()) == 1 and audit.entries()[0]["approved_by"] == "owner"


def test_stale_preview_is_refused_when_the_row_amount_changed(tmp_path):
    rows = [row("t1")]
    proposal = propose("이 건만 식비로 분류해 줘", rows=rows, focus=FOCUS)
    rows[0]["amount_krw"] = 9999
    with pytest.raises(ValueError, match="ROW_CHANGED_SINCE_PREVIEW"):
        apply(proposal, approved=True, approved_by="owner", rows=rows, audit=AuditLog(tmp_path / "a.json"))
    assert rows[0]["item"] == ""


def test_exclusion_needs_its_own_confirmation_and_marks_not_item(tmp_path):
    rows = [row("t1")]
    proposal = propose("이 거래는 회사 경비 아님", rows=rows, focus=FOCUS)
    with pytest.raises(PermissionError, match="EXCLUSION_NEEDS_CONFIRMATION"):
        apply(proposal, approved=True, approved_by="owner", rows=rows, audit=AuditLog(tmp_path / "a.json"))
    apply(proposal, approved=True, approved_by="owner", rows=rows, audit=AuditLog(tmp_path / "b.json"),
          confirm_exclusion=True)
    assert rows[0]["excluded_from_company"] is True and rows[0]["item"] == ""


def test_rejected_original_edit_produces_no_changes():
    proposal = propose("금액을 9999로 바꿔 줘", rows=ROWS, focus=FOCUS)
    assert proposal == {"id": None, "status": "REJECTED_ORIGINAL_EDIT", "changes": [], "skipped_decided": 0}


def test_decision_payloads_keep_the_seen_revision_and_skip_exclusions(tmp_path):
    from app.rule_proposals import decision_payloads
    rows = [row("t1", revision=4, description="메모", display_tab_id="trip-A"), row("t2", revision=2)]
    proposal = propose("이 가맹점은 앞으로 현지잡비로 분류해 줘", rows=rows, focus=FOCUS)
    payloads = decision_payloads(proposal, rows)
    assert [p["transaction_id"] for p in payloads] == ["t1", "t2"]
    assert payloads[0] == {"transaction_id": "t1", "revision": 4, "item": "현지잡비", "description": "메모",
                           "display_tab_id": "trip-A", "note": f"규칙 제안 {proposal['id']} 승인",
                           "reuse_rule": False, "resolve_hold": False}
    excluded = propose("이 거래는 회사 경비 아님", rows=rows, focus=FOCUS)
    assert decision_payloads(excluded, rows) == []


def test_one_stale_row_stops_the_whole_batch_with_nothing_applied(tmp_path):
    rows = [row("t1"), row("t2")]
    proposal = propose("이 가맹점은 앞으로 현지잡비로 분류해 줘", rows=rows, focus=FOCUS)
    rows[1]["amount_krw"] = 777  # changed after the preview
    with pytest.raises(ValueError, match="ROW_CHANGED_SINCE_PREVIEW"):
        apply(proposal, approved=True, approved_by="owner", rows=rows, audit=AuditLog(tmp_path / "a.json"))
    assert rows[0]["item"] == "" and rows[1]["item"] == ""


def test_row_item_changed_by_someone_else_is_refused(tmp_path):
    rows = [row("t1")]
    proposal = propose("이 건만 식비로 분류해 줘", rows=rows, focus=FOCUS)
    rows[0]["item"] = "교통비"  # another path changed it after the preview
    with pytest.raises(ValueError, match="ROW_CHANGED_SINCE_PREVIEW"):
        apply(proposal, approved=True, approved_by="owner", rows=rows, audit=AuditLog(tmp_path / "a.json"))
    assert rows[0]["item"] == "교통비"


def test_proposal_ids_do_not_repeat_across_restarts():
    import importlib
    import app.rule_proposals as rp
    first = propose("이 건만 식비로 분류해 줘", rows=[row("t1")], focus=FOCUS)["id"]
    importlib.reload(rp)
    second = rp.propose("이 건만 식비로 분류해 줘", rows=[row("t1")], focus=FOCUS)["id"]
    assert first != second and first.startswith("p-") and second.startswith("p-")


def test_rows_already_holding_the_item_get_no_second_decision():
    from app.rule_proposals import decision_payloads
    rows = [row("t1", item="식비")]
    proposal = propose("이 건만 식비로 분류해 줘", rows=rows, focus=FOCUS)
    assert decision_payloads(proposal, rows) == []
