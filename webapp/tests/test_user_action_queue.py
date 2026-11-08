import json
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


def _insert_task(conn, request_id, raw):
    payload = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    conn.execute("INSERT INTO requests VALUES(?,?,?,?,?)",
                 (request_id, queue.SCOPE, "synthetic", payload, "2026-11-05T00:00:00Z"))


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


def test_owner_navigation_has_no_historical_queue_even_with_open_audit_records(conn,monkeypatch):
    from webapp import ledger_design
    _register(conn)
    monkeypatch.setattr(ledger_design.board,'current_role',lambda:'owner')
    monkeypatch.setattr(ledger_design.board,'_active_store',lambda:type('Store',(),{'conn':conn})())
    monkeypatch.setattr(ledger_design,'nav_region',lambda *args:'')
    nav=ledger_design._nav_html('','')
    assert '/my-actions' not in nav and '내 확인 필요' not in nav
    assert '/cards/all' in nav and len(queue.list_tasks(conn)) == 1


def test_navigation_is_independent_of_audit_snapshot_changes(conn,monkeypatch):
    from webapp import ledger_design
    _register(conn,group_key='historical-a')
    monkeypatch.setattr(ledger_design.board,'current_role',lambda:'owner')
    monkeypatch.setattr(ledger_design,'nav_region',lambda *args:'')
    with queue.request_snapshot_scope():
        assert queue.open_snapshot(conn).count == 1
        before=ledger_design._nav_html('','')
        _register(conn,group_key='historical-b')
        assert queue.open_snapshot(conn).count == 1
        assert ledger_design._nav_html('','') == before
    assert queue.open_snapshot(conn).count == 2
    assert '/my-actions' not in before


def test_audit_snapshot_failure_is_preserved_but_cannot_affect_navigation(monkeypatch):
    from webapp import ledger_design
    conn=sqlite3.connect(':memory:')
    monkeypatch.setattr(ledger_design.board,'current_role',lambda:'owner')
    monkeypatch.setattr(ledger_design,'nav_region',lambda *args:'')
    try:
        with queue.request_snapshot_scope():
            with pytest.raises(queue.QueueReadUnavailable):queue.open_snapshot(conn)
            conn.execute('CREATE TABLE requests(request_id TEXT PRIMARY KEY,scope TEXT,payload_sha256 TEXT,response_json TEXT,created_at TEXT)')
            with pytest.raises(queue.QueueReadUnavailable):queue.open_snapshot(conn)
            assert '/my-actions' not in ledger_design._nav_html('','')
        assert queue.open_snapshot(conn).count == 0
    finally:conn.close()


def test_open_snapshot_deduplicates_valid_actions_and_shares_count_revision(conn):
    first = _register(conn, group_key="refund:group-a")
    other = _register(conn, group_key="refund:group-b")
    newest = {**first, "title": "\ucd5c\uc2e0 \ud655\uc778 \uc9c8\ubb38", "updated_at": "9999-01-01T00:00:00Z",
              "revision": first["revision"] + 1}
    _insert_task(conn, "duplicate-a", newest)
    _insert_task(conn, "invalid-id", {**first, "action_id": "ua-invalid"})
    _insert_task(conn, "invalid-title", {**first, "title": "  "})
    _insert_task(conn, "malformed-json", "{broken json")

    snapshot = queue.open_snapshot(conn)
    assert snapshot.count == 2
    selected = {task["action_id"]: task for task in snapshot.tasks}
    assert selected[first["action_id"]]["title"] == "\ucd5c\uc2e0 \ud655\uc778 \uc9c8\ubb38"
    assert selected[other["action_id"]]["title"] == other["title"]

    attrs = queue.queue_data_attrs(snapshot)
    actions_page = queue.render(conn, "csrf-token", snapshot=snapshot)
    import_summary = queue.render_queue_summary(snapshot)
    assert attrs in actions_page
    assert attrs in import_summary
    assert f"\ub0b4 \ud655\uc778 \ud544\uc694 {snapshot.count}\uac74" in actions_page
    assert f"\ub0b4 \ud655\uc778 \ud544\uc694 {snapshot.count}\uac74" in import_summary
    assert snapshot.revision in actions_page and snapshot.revision in import_summary


def test_queue_read_failure_is_not_rendered_as_zero(conn):
    missing_table = sqlite3.connect(":memory:")
    try:
        with pytest.raises(queue.QueueReadUnavailable):
            queue.open_snapshot(missing_table)
        page = queue.render(missing_table, "csrf-token")
        assert "\uc791\uc5c5 \ubaa9\ub85d\uc744 \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4" in page
        assert "\ub0b4 \ud655\uc778 \ud544\uc694 0\uac74" not in page
        assert "data-action-count='0'" not in page
    finally:
        missing_table.close()


def test_owner_navigation_never_queries_retired_task_store(monkeypatch):
    from webapp import ledger_design
    monkeypatch.setattr(ledger_design.board,'current_role',lambda:'owner')
    monkeypatch.setattr(ledger_design,'nav_region',lambda *args:'')
    def forbidden(*_):raise AssertionError('navigation must not read the retired queue')
    monkeypatch.setattr(queue,'open_snapshot',forbidden)
    nav=ledger_design._nav_html('','')
    assert '/cards/all' in nav and '/my-actions' not in nav


def test_answer_options_keep_internal_values_and_render_human_labels(conn):
    task = _register(conn, answer_options=({"value": "meal", "label": "식비"},))
    page = queue.render(conn, "csrf-token")
    assert "value='meal'>식비</option>" in page
    answered = queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                            expected_digest=queue._digest(task), value="meal")
    assert answered["answer"]["value"] == "meal"


def test_pending_answers_only_returns_reprocessing_tasks(conn):
    task = _register(conn)
    queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                 expected_digest=queue._digest(task), value="아니오")
    assert queue.pending_answers(conn) == []
    queue.set_state(conn, task["action_id"], queue.REPROCESSING)
    assert [item["action_id"] for item in queue.pending_answers(conn)] == [task["action_id"]]


def test_card_adapter_neither_registers_questions_nor_consumes_historical_answers(conn):
    from webapp import user_action_adapters as adapter
    task=_register(conn)
    queue.answer(conn,action_id=task['action_id'],expected_revision=task['revision'],expected_digest=queue._digest(task),value='아니오')
    queue.set_state(conn,task['action_id'],queue.REPROCESSING)
    before=list(conn.iterdump())
    row=('tx-1','batch-1',4,'needs_review','','','unclassified','','hash-1','2026-01-01')
    for status in ('no_ai_needed','p2_applied','ai_retry','ai_dead'):
        assert adapter.register_card_item_tasks(conn,[row],lambda *_:{'status':status}) == 0
    class Flow:
        def __getattr__(self,name):raise AssertionError('retired answers cannot call the card pipeline')
    assert adapter.apply_card_item_answers(conn,Flow()) == 0
    assert list(conn.iterdump()) == before and len(queue.pending_answers(conn)) == 1


def test_retired_answers_preserve_existing_financial_hold_and_audit_history(conn):
    from webapp import user_action_adapters as adapter
    conn.execute('CREATE TABLE transaction_review_holds(transaction_id TEXT,kind TEXT)')
    conn.execute("INSERT INTO transaction_review_holds VALUES('tx-1','manual')")
    task=_register(conn)
    before=list(conn.iterdump())
    assert adapter.apply_card_item_answers(conn,object()) == 0
    assert list(conn.iterdump()) == before
    assert queue.list_tasks(conn)[0]['action_id'] == task['action_id']
