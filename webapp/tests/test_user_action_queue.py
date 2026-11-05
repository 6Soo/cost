import sqlite3

import pytest

from webapp import user_action_queue as queue


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE requests(request_id TEXT PRIMARY KEY, scope TEXT NOT NULL, payload_sha256 TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL)")
    yield db
    db.close()


def _register(conn, **overrides):
    values = dict(group_key="refund:transaction-1", task_type="결제·환불", title="환불 확인",
                  question="카드 환불이 실제 반영됐나요?", evidence_summary="취소 메일은 확인했으나 환불 원행은 찾지 못했습니다.",
                  source_refs=("transaction-1",), source_revision="source-v1", answer_options=("예", "아니오"))
    values.update(overrides)
    return queue.register(conn, **values)


def test_same_group_is_idempotent_and_answer_requires_current_revision(conn):
    task = _register(conn)
    duplicate = _register(conn)
    assert duplicate["action_id"] == task["action_id"]
    assert duplicate["revision"] == task["revision"]
    assert queue.open_count(conn) == 1

    answered = queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                            expected_digest=queue._digest(task), value="아니오")
    assert answered["state"] == queue.ANSWERED
    assert answered["answer"]["source"] == "USER"
    assert queue.open_count(conn) == 0
    with pytest.raises(ValueError, match="ACTION_NOT_OPEN"):
        queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                     expected_digest=queue._digest(task), value="아니오")


def test_stale_digest_is_rejected_and_changed_evidence_reopens_without_old_answer(conn):
    task = _register(conn)
    with pytest.raises(ValueError, match="STALE_ACTION"):
        queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                     expected_digest="stale", value="예")
    queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                 expected_digest=queue._digest(task), value="예")
    updated = _register(conn, source_revision="source-v2", evidence_summary="새 카드 자료도 확인했습니다.")
    assert updated["state"] == queue.OPEN
    assert updated["answer"] is None
    assert updated["revision"] == task["revision"] + 2
    assert queue.open_count(conn) == 1


def test_render_has_one_action_and_does_not_expose_internal_queue_states(conn):
    task = _register(conn)
    page = queue.render(conn, "csrf-token")
    assert "내 확인 필요 1건" in page
    assert "카드 환불이 실제 반영됐나요?" in page
    assert "답변하고 자동 재검토" in page
    assert "보류 해제" not in page
    assert "SYSTEM_RETRY" not in page
    assert task["action_id"] in page
    assert "답변을 저장했습니다" in queue.render(conn, "csrf-token", answered=True)


def test_owner_navigation_exposes_single_queue_with_action_count(conn, monkeypatch):
    from webapp import ledger_design

    _register(conn)
    fake_store = type("Store", (), {"conn": conn})()
    monkeypatch.setattr(ledger_design.board, "current_role", lambda: "owner")
    monkeypatch.setattr(ledger_design.board, "_active_store", lambda: fake_store)
    monkeypatch.setattr(ledger_design, "nav_region", lambda *args: "")
    nav = ledger_design._nav_html("", "")
    assert nav.count("/my-actions") == 1
    assert "내 확인 필요 1건" in nav
