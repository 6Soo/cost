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


def test_import_summary_and_navigation_share_one_request_snapshot(conn, monkeypatch):
    from webapp import ledger_design

    _register(conn, group_key="refund:group-a")
    fake_store = type("Store", (), {"conn": conn})()
    monkeypatch.setattr(ledger_design.board, "current_role", lambda: "owner")
    monkeypatch.setattr(ledger_design.board, "_active_store", lambda: fake_store)
    monkeypatch.setattr(ledger_design, "nav_region", lambda *args: "")

    with queue.request_snapshot_scope():
        snapshot = queue.open_snapshot(conn)
        summary = queue.render_queue_summary(snapshot)
        _register(conn, group_key="refund:group-b")
        nav = ledger_design._nav_html("", "")

        assert "내 확인 필요 1건" in summary
        assert "내 확인 필요 1건" in nav
        assert "내 확인 필요 2건" not in nav

    assert "내 확인 필요 2건" in ledger_design._nav_html("", "")


def test_request_snapshot_scope_reuses_queue_read_failure_until_response_finishes(monkeypatch):
    from webapp import ledger_design

    missing_table = sqlite3.connect(":memory:")
    fake_store = type("Store", (), {"conn": missing_table})()
    monkeypatch.setattr(ledger_design.board, "current_role", lambda: "owner")
    monkeypatch.setattr(ledger_design.board, "_active_store", lambda: fake_store)
    monkeypatch.setattr(ledger_design, "nav_region", lambda *args: "")
    try:
        with queue.request_snapshot_scope():
            with pytest.raises(queue.QueueReadUnavailable):
                queue.open_snapshot(missing_table)
            missing_table.execute(
                "CREATE TABLE requests(request_id TEXT PRIMARY KEY, scope TEXT NOT NULL, "
                "payload_sha256 TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            nav = ledger_design._nav_html("", "")
            assert "내 확인 필요 수를 확인할 수 없음" in nav
            assert "내 확인 필요 0건" not in nav

        assert "내 확인 필요 0건" in ledger_design._nav_html("", "")
    finally:
        missing_table.close()


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


def test_owner_navigation_does_not_claim_zero_when_queue_read_fails(monkeypatch):
    from webapp import ledger_design

    missing_table = sqlite3.connect(":memory:")
    fake_store = type("Store", (), {"conn": missing_table})()
    monkeypatch.setattr(ledger_design.board, "current_role", lambda: "owner")
    monkeypatch.setattr(ledger_design.board, "_active_store", lambda: fake_store)
    monkeypatch.setattr(ledger_design, "nav_region", lambda *args: "")
    try:
        nav = ledger_design._nav_html("", "")
        assert "내 확인 필요 수를 확인할 수 없음" in nav
        assert "\ub0b4 \ud655\uc778 \ud544\uc694 0\uac74" not in nav
        assert "data-action-count='0'" not in nav
    finally:
        missing_table.close()


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


def test_card_action_adapter_registers_only_terminal_p3_rows_and_applies_answer(conn):
    from webapp import user_action_adapters as adapter

    row = ("tx-1", "batch-1", 4, "needs_review", "", "", "unclassified", "", "hash-1", "2026-01-01")
    jobs = {"tx-1": {"status": "no_ai_needed"}}
    assert adapter.register_card_item_tasks(conn, [row], lambda _conn, tx: jobs[tx]) == 1
    task = queue.list_tasks(conn)[0]
    assert task["answer_effect"]["kind"] == "card_item"
    assert task["action_url"] == "/import?batch=batch-1&transaction=tx-1"
    assert adapter.register_card_item_tasks(conn, [row], lambda _conn, tx: {"status": "ai_retry"}) == 0

    conn.executescript("""
        CREATE TABLE transactions(transaction_id TEXT PRIMARY KEY, revision INTEGER, source_hash TEXT,
            classification_state TEXT, classification_source TEXT, item TEXT, display_tab_id TEXT,
            trip_id TEXT, parse_error TEXT, conflict_reason TEXT, duplicate_of TEXT,
            transaction_direction TEXT, amount_krw INTEGER, decided_at TEXT, issuer TEXT, card_tail TEXT,
            approval_number TEXT, original_approval_number TEXT);
        CREATE TABLE import_batch_rows(batch_id TEXT, transaction_id TEXT);
        CREATE TABLE review_decisions(transaction_id TEXT, item TEXT);
        CREATE TABLE ledger_entries(transaction_id TEXT);
        CREATE TABLE board_rows(row_id TEXT);
        CREATE TABLE board_manual_overrides(row_id TEXT);
        CREATE TABLE transaction_review_holds(transaction_id TEXT);
        CREATE TABLE transaction_company_exclusions(transaction_id TEXT, excluded INTEGER);
    """)
    conn.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("tx-1", 4, "hash-1", "needs_review", "", "", "unclassified", "", "", "", "", "purchase", 1200, None, "issuer", "1234", "", ""))
    conn.execute("INSERT INTO import_batch_rows VALUES('batch-1','tx-1')")
    queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                 expected_digest=queue._digest(task), value="식비")
    queue.set_state(conn, task["action_id"], queue.REPROCESSING)

    class Pipeline:
        def save_decision(self, transaction_id, revision, **kwargs):
            assert (transaction_id, revision, kwargs["item"]) == ("tx-1", 4, "식비")
            conn.execute("UPDATE transactions SET revision=revision+1,classification_state='classified',"
                         "classification_source='user_decision',item=?,decided_at='saved' WHERE transaction_id=?",
                         (kwargs["item"], transaction_id))

    class Flow:
        pipeline = Pipeline()
        tab_valid = staticmethod(lambda _tab: True)
        trip_valid = staticmethod(lambda _trip: True)

    assert adapter.apply_card_item_answers(conn, Flow()) == 1
    assert queue.pending_answers(conn) == []
    assert conn.execute("SELECT classification_source,item FROM transactions WHERE transaction_id='tx-1'").fetchone() == ("user_decision", "식비")
    assert conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0


def test_card_action_answer_is_superseded_if_a_protective_hold_appears(conn):
    from webapp import user_action_adapters as adapter

    conn.executescript("""
        CREATE TABLE transactions(transaction_id TEXT PRIMARY KEY, revision INTEGER, source_hash TEXT,
            classification_state TEXT, classification_source TEXT, item TEXT, display_tab_id TEXT,
            trip_id TEXT, parse_error TEXT, conflict_reason TEXT, duplicate_of TEXT,
            transaction_direction TEXT, amount_krw INTEGER, decided_at TEXT, issuer TEXT, card_tail TEXT,
            approval_number TEXT, original_approval_number TEXT);
        CREATE TABLE import_batch_rows(batch_id TEXT, transaction_id TEXT);
        CREATE TABLE review_decisions(transaction_id TEXT, item TEXT);
        CREATE TABLE ledger_entries(transaction_id TEXT);
        CREATE TABLE board_rows(row_id TEXT);
        CREATE TABLE board_manual_overrides(row_id TEXT);
        CREATE TABLE transaction_review_holds(transaction_id TEXT);
        CREATE TABLE transaction_company_exclusions(transaction_id TEXT, excluded INTEGER);
    """)
    row = ("tx-2", "batch-2", 1, "needs_review", "", "", "unclassified", "", "hash-2", "2026-01-01")
    adapter.register_card_item_tasks(conn, [row], lambda *_: {"status": "p2_applied"})
    task = queue.list_tasks(conn)[0]
    conn.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("tx-2", 1, "hash-2", "needs_review", "", "", "unclassified", "", "", "", "", "purchase", 1200, None, "issuer", "1234", "", ""))
    conn.execute("INSERT INTO import_batch_rows VALUES('batch-2','tx-2')")
    conn.execute("INSERT INTO transaction_review_holds VALUES('tx-2')")
    queue.answer(conn, action_id=task["action_id"], expected_revision=task["revision"],
                 expected_digest=queue._digest(task), value="식비")
    queue.set_state(conn, task["action_id"], queue.REPROCESSING)

    class Flow:
        class Pipeline:
            @staticmethod
            def save_decision(*_args, **_kwargs):
                raise AssertionError("protected transaction must never be changed")
        pipeline = Pipeline()
        tab_valid = staticmethod(lambda _tab: True)
        trip_valid = staticmethod(lambda _trip: True)

    assert adapter.apply_card_item_answers(conn, Flow()) == 0
    stored = conn.execute("SELECT response_json FROM requests WHERE request_id=?",
                          ("user-action:" + task["action_id"],)).fetchone()
    assert queue._decode(stored)["state"] == queue.SUPERSEDED
