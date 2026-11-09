"""Phase 2 save/store tests (synthetic DB only).

Covers DETAILED_CONTRACT section 9 save scenarios: C1 move totals,
lost-response retry, reused request id, illegal amount change, memo-only,
revision conflict, restart persistence, and no cascade to C2.
"""

import tempfile
import unittest
from pathlib import Path

from webapp.ledger_store import LedgerStore, SaveError


def make_store():
    directory = tempfile.mkdtemp()
    return LedgerStore(Path(directory) / "webledger.sqlite")


class LedgerEventBoundaryTests(unittest.TestCase):
    """R01: the operator event must not diverge from the board save.

    The operator ledger is a separate database, which is exactly why the
    boundary has to be checked rather than assumed. The queue row is written
    inside the outer transaction and the relay happens only after the commit,
    so an outer failure can never leave an event behind on its own.
    """

    def test_a_failed_outer_save_leaves_no_ledger_event(self):
        store = make_store()
        try:
            self.assertEqual(len(store.ledger.all_events()), 0)
            # enqueue inside an open transaction, then roll the outer one back
            store.conn.execute("BEGIN IMMEDIATE")
            store._enqueue_ledger(
                outbox_id="r01-rollback", stream_id="row-expense-demo-c1",
                action="propose", target="evt-1",
                rationale="outer failure probe", actor="local-operator")
            inside = store.conn.execute(
                "SELECT COUNT(*) FROM ledger_outbox").fetchone()[0]
            self.assertEqual(inside, 1, "the enqueue did not happen at all")
            store.conn.execute("ROLLBACK")
            # the queue row went with the transaction
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM ledger_outbox").fetchone()[0], 0)
            # and no event was appended to the separate ledger
            self.assertEqual(len(store.ledger.all_events()), 0)
        finally:
            store.close()

    def test_a_committed_save_relays_once_and_a_second_relay_adds_nothing(self):
        store = make_store()
        try:
            result = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="r01-committed", change_mode="exception",
                changes={"item": "정상 저장"})
            self.assertEqual(result["outcome"], "saved")
            after_save = len(store.ledger.all_events())
            self.assertEqual(after_save, 1,
                             "the relay did not happen after the commit")
            # relaying again must not duplicate the event
            store._relay_outbox()
            store._relay_outbox()
            self.assertEqual(len(store.ledger.all_events()), after_save)
            # and the queue row is marked relayed
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM ledger_outbox WHERE relayed=0"
            ).fetchone()[0], 0)
        finally:
            store.close()

    def test_the_same_request_id_with_different_content_is_refused(self):
        store = make_store()
        try:
            first = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="r01-reuse", change_mode="exception",
                changes={"item": "첫 번째 값"})
            # the same id and the same content replays the stored result
            again = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="r01-reuse", change_mode="exception",
                changes={"item": "첫 번째 값"})
            self.assertEqual(again, first)
            # the same id with different content is refused
            with self.assertRaises(SaveError) as ctx:
                store.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="r01-reuse", change_mode="exception",
                    changes={"item": "다른 내용"})
            self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")
            # nothing was written by the refused attempt
            self.assertEqual(store.get_row("expense-demo-c1")["item"],
                             "첫 번째 값")
        finally:
            store.close()


class SaveTotalsTests(unittest.TestCase):
    def test_c1_move_updates_both_tabs(self):
        store = make_store()
        try:
            result = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-to-b", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b", "operator_note": "사용자 확인"},
            )
            self.assertEqual(result["outcome"], "saved")
            self.assertEqual(result["revision"], 2)
            self.assertEqual(store.tab_totals("trip-demo-a")["expense"], 80000)
            self.assertEqual(store.tab_totals("trip-demo-b")["expense"], 100000)
            self.assertEqual(store.tab_totals("trip-demo-a")["profit"], 920000)
            self.assertEqual(store.tab_totals("trip-demo-b")["profit"], -100000)
        finally:
            store.close()

    def test_c2_stays_when_c1_moves(self):
        store = make_store()
        try:
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-x", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
            row = store.get_row("expense-demo-c2")
            self.assertEqual(row["display_tab_id"], "trip-demo-a")
        finally:
            store.close()


class RetryTests(unittest.TestCase):
    def test_lost_response_retry_single_event(self):
        store = make_store()
        try:
            first = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-retry", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
            second = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-retry", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
            self.assertEqual(first, second)
            self.assertEqual(len(store.list_history("expense-demo-c1")), 1)
            self.assertEqual(store.tab_totals("trip-demo-b")["expense"], 100000)
        finally:
            store.close()

    def test_same_id_different_content_rejected(self):
        store = make_store()
        try:
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-dup", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
            with self.assertRaises(SaveError) as ctx:
                store.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="save-c1-dup", change_mode="exception",
                    changes={"display_tab_id": "trip-demo-a"},
                )
            self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")
            self.assertEqual(store.tab_totals("trip-demo-b")["expense"], 100000)
        finally:
            store.close()


class ValidationTests(unittest.TestCase):
    def test_amount_change_rejected_whole(self):
        store = make_store()
        try:
            with self.assertRaises(SaveError) as ctx:
                store.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="save-c1-amount", change_mode="exception",
                    changes={"amount_krw": 999},
                )
            self.assertEqual(ctx.exception.code, "FIELD_READ_ONLY")
            self.assertEqual(store.tab_totals("trip-demo-a")["expense"], 180000)
            self.assertEqual(store.list_history("expense-demo-c1"), [])
        finally:
            store.close()

    def test_revision_conflict_no_overwrite(self):
        store = make_store()
        try:
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-first", change_mode="exception",
                changes={"operator_note": "첫 저장"},
            )
            with self.assertRaises(SaveError) as ctx:
                store.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="save-c1-stale", change_mode="exception",
                    changes={"operator_note": "낡은 저장"},
                )
            self.assertEqual(ctx.exception.code, "EDIT_CONFLICT")
            self.assertEqual(store.get_row("expense-demo-c1")["operator_note"], "첫 저장")
        finally:
            store.close()

    def test_memo_only_keeps_totals(self):
        store = make_store()
        try:
            result = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-memo", change_mode="exception",
                changes={"operator_note": "오탈자 수정"},
            )
            self.assertEqual(result["outcome"], "saved")
            self.assertIsNone(result["learning_case_id"])
            self.assertEqual(store.tab_totals("trip-demo-a")["expense"], 180000)
        finally:
            store.close()

    def test_rule_change_creates_waiting_case(self):
        store = make_store()
        try:
            result = store.save(
                row_id="expense-demo-c3", expected_revision=1,
                client_request_id="save-c3-rule", change_mode="rule_change",
                changes={"display_tab_id": "trip-demo-a"},
            )
            self.assertIsNotNone(result["learning_case_id"])
            row = self.conn_case(store, result["learning_case_id"])
            self.assertEqual(row[0], "waiting")
        finally:
            store.close()

    def conn_case(self, store, case_id):
        return store.conn.execute(
            "SELECT dialog_state FROM board_learning_cases WHERE case_id=?", (case_id,)
        ).fetchone()

    def test_restart_keeps_state(self):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "webledger.sqlite"
        store = LedgerStore(path)
        try:
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-restart", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
        finally:
            store.close()
        reopened = LedgerStore(path)
        try:
            self.assertEqual(reopened.tab_totals("trip-demo-b")["expense"], 100000)
            self.assertEqual(len(reopened.list_history("expense-demo-c1")), 1)
        finally:
            reopened.close()


class UnclassifiedNormalizeTests(unittest.TestCase):
    """R07: 문자열 미배정 정규화·메모 전용 학습 미생성·왕복 보존."""

    def test_string_unclassified_saved_as_null(self):
        store = make_store()
        try:
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-uncl", change_mode="exception",
                changes={"display_tab_id": "unclassified"},
            )
            row = store.get_row("expense-demo-c1")
            self.assertIsNone(row["display_tab_id"])
            self.assertIn(
                "expense-demo-c1",
                [r["row_id"] for r in store.list_tab_rows(None)],
            )
        finally:
            store.close()

    def test_memo_only_rule_change_creates_no_case(self):
        store = make_store()
        try:
            result = store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-memorule", change_mode="rule_change",
                changes={"operator_note": "메모만"},
            )
            self.assertIsNone(result["learning_case_id"])
            self.assertEqual(store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-a")
        finally:
            store.close()

    def test_trip_unclassified_roundtrip_keeps_totals(self):
        store = make_store()
        try:
            before = store.tab_totals("trip-demo-a")["expense"]
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-out", change_mode="exception",
                changes={"display_tab_id": None},
            )
            self.assertEqual(store.tab_totals("trip-demo-a")["expense"], before - 100000)
            store.save(
                row_id="expense-demo-c1", expected_revision=2,
                client_request_id="save-c1-back", change_mode="exception",
                changes={"display_tab_id": "trip-demo-a"},
            )
            self.assertEqual(store.tab_totals("trip-demo-a")["expense"], before)
        finally:
            store.close()


class TripMetaTests(unittest.TestCase):
    """D1: 작성 정보·보관·삭제 미리보기·적용."""

    def test_meta_save_and_archive(self):
        store = make_store()
        try:
            before_assignee = store.get_trip("trip-demo-a")["prepared_by_name"]
            result = store.save_trip_meta(
                tab_id="trip-demo-a", expected_revision=1,
                client_request_id="trip-t1", display_key="봄 여행 / 정산",
            )
            self.assertEqual(result["revision"], 2)
            trip = store.get_trip("trip-demo-a")
            self.assertEqual(trip["display_key"], "봄 여행 / 정산")
            self.assertTrue(trip["prepared_on"])
            # A rename save does not touch the assignee, and a seeded trip no
            # longer arrives with a name stamped on it by the product. What has
            # to hold is that this save left the assignee exactly as it was —
            # asserted against the value read before the save rather than
            # against a literal, so the test is about the save and not about
            # whatever default the product currently ships.
            self.assertEqual(trip["prepared_by_name"], before_assignee)
            store.save_trip_meta(
                tab_id="trip-demo-a", expected_revision=2,
                client_request_id="trip-t2", archived=True,
            )
            self.assertEqual(len(store.list_trips()), 1)
            self.assertEqual(len(store.list_trips(include_archived=True)), 2)
        finally:
            store.close()

    def test_trip_management_summaries_match_delete_preview_totals(self):
        store = make_store()
        try:
            summaries = store.trip_management_summaries()
            for tab_id in ("trip-demo-a", "trip-demo-b"):
                preview = store.preview_tab_delete(tab_id)
                summary = summaries[tab_id]
                self.assertEqual(summary["income_count"], preview["income_count"])
                self.assertEqual(summary["income_total"], preview["income_total"])
                self.assertEqual(summary["expense_count"], preview["expense_count"])
                self.assertEqual(summary["expense_total"], preview["expense_total"])
        finally:
            store.close()

    def test_delete_moves_and_stale_rejected(self):
        store = make_store()
        try:
            preview = store.preview_tab_delete("trip-demo-a")
            self.assertEqual(preview["income_total"], 1000000)
            result = store.apply_tab_delete(
                tab_id="trip-demo-a", expected_revision=preview["snapshot"]["tab_revision"],
                mode="move-trip", destination="trip-demo-b",
                snapshot=preview["snapshot"], client_request_id="trip-del-1",
            )
            self.assertEqual(result["outcome"], "deleted")
            self.assertEqual(store.tab_totals("trip-demo-b")["income"], 1000000)
            self.assertTrue(store.get_trip("trip-demo-a")["deleted"])
            again = store.apply_tab_delete(
                tab_id="trip-demo-a", expected_revision=preview["snapshot"]["tab_revision"],
                mode="move-trip", destination="trip-demo-b",
                snapshot=preview["snapshot"], client_request_id="trip-del-1",
            )
            self.assertEqual(again["outcome"], "deleted")
        finally:
            store.close()

    def test_delete_stale_preview_rejected(self):
        store = make_store()
        try:
            preview = store.preview_tab_delete("trip-demo-a")
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="trip-stale-add", change_mode="exception",
                changes={"operator_note": "x"},
            )
            with self.assertRaises(SaveError) as ctx:
                store.apply_tab_delete(
                    tab_id="trip-demo-a",
                    expected_revision=preview["snapshot"]["tab_revision"],
                    mode="move-unclassified", destination=None,
                    snapshot=preview["snapshot"], client_request_id="trip-del-stale",
                )
            self.assertEqual(ctx.exception.code, "DELETE_PREVIEW_STALE")
        finally:
            store.close()


class RevertTests(unittest.TestCase):
    """D2: 직전 수정 되돌리기."""

    def test_memo_revert_and_double_locked(self):
        store = make_store()
        try:
            store.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="rv-1", change_mode="exception",
                changes={"operator_note": "B"},
            )
            result = store.revert_row(
                row_id="expense-demo-c1", expected_revision=2,
                client_request_id="rv-2",
            )
            self.assertEqual(result["outcome"], "reverted")
            self.assertEqual(result["revision"], 3)
            self.assertEqual(store.get_row("expense-demo-c1")["operator_note"], "")
            self.assertEqual(len(store.list_history("expense-demo-c1")), 2)
            retry = store.revert_row(
                row_id="expense-demo-c1", expected_revision=2,
                client_request_id="rv-2",
            )
            self.assertEqual(retry["revision"], 3)
            self.assertEqual(len(store.list_history("expense-demo-c1")), 2)
            with self.assertRaises(SaveError) as ctx:
                store.revert_row(
                    row_id="expense-demo-c1", expected_revision=3,
                    client_request_id="rv-3",
                )
            self.assertEqual(ctx.exception.code, "INVALID_VALUE")
        finally:
            store.close()


class ConcurrentRevisionTests(unittest.TestCase):
    """8.2 R01: 두 연결이 같은 revision을 보면 하나만 성공한다."""

    def test_stale_read_loses_conflict(self):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "webledger.sqlite"
        first = LedgerStore(path)
        second = LedgerStore(path)
        try:
            stale = first.get_row("expense-demo-c1")
            second.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="conc-2", change_mode="exception",
                changes={"operator_note": "second"},
            )
            first.get_row = lambda rid: (
                dict(stale, revision=1) if rid == "expense-demo-c1"
                else LedgerStore.get_row(first, rid)
            )
            with self.assertRaises(SaveError) as ctx:
                first.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="conc-1", change_mode="exception",
                    changes={"operator_note": "first"},
                )
            self.assertEqual(ctx.exception.code, "EDIT_CONFLICT")
            histories = [h for h in second.list_history("expense-demo-c1")
                         if h["revision"] == 2]
            self.assertEqual(len(histories), 1)
            self.assertEqual(
                second.get_row("expense-demo-c1")["operator_note"], "second")
        finally:
            first.close()
            second.close()


class CrashRecoveryTests(unittest.TestCase):
    """R01: ledger.append 위치 중단 후 재시작·동일 요청 재전송은 저장 재사용."""

    def test_crash_before_ledger_replays_same_result(self):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "webledger.sqlite"
        store = LedgerStore(path)
        try:
            def boom(*args, **kwargs):
                raise KeyboardInterrupt("injected at ledger.append")
            store.ledger.append = boom
            with self.assertRaises(KeyboardInterrupt):
                store.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="save-c1-crash", change_mode="exception",
                    changes={"display_tab_id": "trip-demo-b"},
                )
        finally:
            store.close()
        reopened = LedgerStore(path)
        try:
            result = reopened.save(
                row_id="expense-demo-c1", expected_revision=1,
                client_request_id="save-c1-crash", change_mode="exception",
                changes={"display_tab_id": "trip-demo-b"},
            )
            self.assertEqual(result["outcome"], "saved")
            self.assertEqual(result["revision"], 2)
            self.assertFalse(result["ledger_pending"])
            self.assertEqual(len(reopened.list_history("expense-demo-c1")), 1)
            self.assertEqual(reopened.tab_totals("trip-demo-b")["expense"], 100000)
            with self.assertRaises(SaveError) as ctx:
                reopened.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="save-c1-crash", change_mode="exception",
                    changes={"display_tab_id": "trip-demo-a"},
                )
            self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()


class RenderReadTests(unittest.TestCase):
    """A render reads saved rows in one scan and sees exactly what per-tab reads see."""

    def test_a_render_reads_every_tab_in_one_scan_with_the_same_rows(self):
        from webapp import read_scope
        store = make_store()
        try:
            tabs = [t["tab_id"] for t in store.list_trips(include_archived=True)] + [None]
            direct = {tab: store.list_tab_rows(tab) for tab in tabs}
            scans = []
            store.conn.set_trace_callback(
                lambda sql: scans.append(sql) if "FROM board_rows" in sql and "payload_json" in sql else None)

            @read_scope.scoped
            def render():
                return {tab: store.list_tab_rows(tab) for tab in tabs}

            self.assertEqual(render(), direct)
            self.assertEqual(len(scans), 1)
            scans.clear()
            self.assertEqual(render(), direct, "a later render must read again")
            self.assertEqual(len(scans), 1)
        finally:
            store.conn.set_trace_callback(None)
            store.close()
