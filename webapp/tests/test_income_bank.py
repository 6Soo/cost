"""Phase 4 income/bank/manual tests (synthetic only).

Covers the user-checked flows: 500000 direct income edited to 450000,
bank income correction, duplicate handling, manual expense with history,
and the same API refusing card amount changes.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp.income_ledger import BankImporter
from webapp.ledger_store import LedgerStore, SaveError


def make_store():
    directory = tempfile.mkdtemp()
    return LedgerStore(Path(directory) / "webledger.sqlite")


BANK_CSV = (
    "occurred_on,payer_name,amount_krw,direction,account_ref,transaction_id,memo\n"
    "2026-04-02,김예시,500000,credit,ACC1,T1,\n"
    "2026-04-03,김예시,200000,credit,ACC1,T2,\n"
    "2026-04-04,출금자,-50000,debit,ACC1,T3,\n"
)


class DirectIncomeTests(unittest.TestCase):
    def test_create_and_edit_500000_to_450000(self):
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": "U1", "customer_name": "김예시",
                    "nickname": "예시별명", "memo": "",
                },
                client_request_id="inc-direct-1",
            )
            self.assertEqual(store.tab_totals("trip-demo-a")["income"], 1500000)
            saved = store.save(
                row_id=created["row_id"], expected_revision=1,
                client_request_id="inc-edit-1", change_mode="exception",
                changes={"amount_krw": 450000},
            )
            self.assertEqual(saved["revision"], 2)
            self.assertEqual(store.tab_totals("trip-demo-a")["income"], 1450000)
            history = store.list_history(created["row_id"])
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["new"]["amount_krw"], 500000)
        finally:
            store.close()

    def test_create_duplicate_request_reused(self):
        store = make_store()
        try:
            first = store.create_direct_income(
                fields={
                    "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-01",
                    "amount_krw": 100000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "", "nickname": "", "memo": "",
                },
                client_request_id="inc-dup-1",
            )
            second = store.create_direct_income(
                fields={
                    "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-01",
                    "amount_krw": 100000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "", "nickname": "", "memo": "",
                },
                client_request_id="inc-dup-1",
            )
            self.assertEqual(first, second)
        finally:
            store.close()


BANK_CSV = (
    "occurred_on,payer_name,amount_krw,direction,account_ref,transaction_id,memo\n"
    "2026-04-02,김예시,500000,credit,ACC1,T1,\n"
    "2026-04-03,김예시,200000,credit,ACC1,T2,\n"
    "2026-04-04,출금자,-50000,debit,ACC1,T3,\n"
)


class BankImportTests(unittest.TestCase):
    def make_bank(self):
        directory = tempfile.mkdtemp()
        store = LedgerStore(Path(directory) / "webledger.sqlite")
        conn = sqlite3.connect(str(Path(directory) / "webledger.sqlite"), check_same_thread=False)
        return BankImporter(conn, store), store

    def test_credit_placed_debit_excluded(self):
        importer, store = self.make_bank()
        try:
            received = importer.receive(BANK_CSV.encode("utf-8"), "bank.csv")
            self.assertFalse(received["reused"])
            result = received["result"]
            self.assertEqual(result["source_rows"], 3)
            self.assertEqual(result["new_events"], 2)
            self.assertEqual(result["excluded_rows"], 1)
            rows = store.conn.execute(
                "SELECT row_id FROM board_rows WHERE row_kind='income' AND row_id LIKE 'bnk-%'"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            unclassified = [r for r in store.list_tab_rows(None) if r["row_kind"] == "income"]
            self.assertEqual(len(unclassified), 2)
        finally:
            store.close()

    def test_same_file_no_new_events(self):
        importer, store = self.make_bank()
        try:
            first = importer.receive(BANK_CSV.encode("utf-8"), "bank.csv")
            second = importer.receive(BANK_CSV.encode("utf-8"), "bank.csv")
            self.assertTrue(second["reused"])
            count = store.conn.execute(
                "SELECT COUNT(*) FROM board_rows WHERE row_id LIKE 'bnk-%'"
            ).fetchone()[0]
            self.assertEqual(count, 2)
        finally:
            store.close()

    def test_link_bank_to_direct_no_double_count(self):
        importer, store = self.make_bank()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-02",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": "U1", "customer_name": "김예시",
                    "nickname": "예시별명", "memo": "",
                },
                client_request_id="inc-link-1",
            )
            received = importer.receive(BANK_CSV.encode("utf-8"), "bank.csv")
            before = store.tab_totals("trip-demo-a")["income"]
            linked = store.link_bank_source(
                row_id=created["row_id"],
                bank_batch_id=received["batch_id"], bank_row_index=0,
                expected_revision=created["revision"],
                client_request_id="inc-link-bank-1",
            )
            self.assertFalse(linked["reused"])
            self.assertEqual(linked["revision"], created["revision"] + 1)
            self.assertEqual(store.tab_totals("trip-demo-a")["income"], before)
        finally:
            store.close()

    def test_bank_correction_flow(self):
        importer, store = self.make_bank()
        try:
            importer.receive(BANK_CSV.encode("utf-8"), "bank.csv")
            # row_id 사전순 임의 선택 대신 fixture의 500000 은행 원천 행을 명시 고른다.
            matched = []
            for (rid,) in store.conn.execute(
                "SELECT row_id FROM board_rows WHERE row_kind='income' AND row_id LIKE 'bnk-%'"
                " ORDER BY row_id"
            ).fetchall():
                record = store.get_row(rid)
                if (record.get("amount_krw") == 500000
                        and str(record.get("occurred_on")) == "2026-04-02"
                        and record.get("source_kind") == "은행"):
                    matched.append(rid)
            self.assertEqual(len(matched), 1,
                             "fixture의 500000 은행 원천 행은 정확히 하나여야 해요")
            row = matched[0]
            first = store.correct_bank_income(
                row_id=row, corrected_amount_krw=450000,
                reason="은행 확인 금액", client_request_id="corr-1",
                expected_revision=1,
            )
            self.assertFalse(first["reused"])
            self.assertEqual(store.display_amount(store.get_row(row)), 450000)
            second = store.correct_bank_income(
                row_id=row, corrected_amount_krw=470000,
                reason="은행 재확인", client_request_id="corr-2",
                expected_revision=2,
            )
            self.assertEqual(store.display_amount(store.get_row(row)), 470000)
            corrections = store.list_corrections(row)
            self.assertEqual([c["corrected_amount_krw"] for c in corrections], [450000, 470000])
            original = store.get_row(row)["amount_krw"]
            self.assertEqual(original, 500000)

            # 같은 요청 ID를 그대로 다시 보내도 정정이 하나 더 생기지 않는다.
            replay = store.correct_bank_income(
                row_id=row, corrected_amount_krw=450000,
                reason="은행 확인 금액", client_request_id="corr-1",
                expected_revision=1,
            )
            self.assertEqual(replay["row_id"], row)
            self.assertEqual(
                [c["corrected_amount_krw"] for c in store.list_corrections(row)],
                [450000, 470000],
            )
            self.assertEqual(store.display_amount(store.get_row(row)), 470000)
            self.assertEqual(store.get_row(row)["amount_krw"], 500000)
        finally:
            store.close()

    def test_bank_row_date_amount_fixed(self):
        importer, store = self.make_bank()
        try:
            importer.receive(BANK_CSV.encode("utf-8"), "bank.csv")
            row = store.conn.execute(
                "SELECT row_id FROM board_rows WHERE row_kind='income' AND row_id LIKE 'bnk-%'"
                " ORDER BY row_id LIMIT 1"
            ).fetchone()[0]
            with self.assertRaises(SaveError) as ctx:
                store.save(
                    row_id=row, expected_revision=1,
                    client_request_id="bnk-edit-1", change_mode="exception",
                    changes={"amount_krw": 1},
                )
            self.assertEqual(ctx.exception.code, "FIELD_READ_ONLY")
        finally:
            store.close()


class ManualExpenseTests(unittest.TestCase):
    def test_create_edit_history(self):
        store = make_store()
        try:
            created = store.create_manual_expense(
                fields={
                    "display_tab_id": "trip-demo-b", "occurred_on": "2026-04-21",
                    "pay_method": "현금", "item": "식음료", "description": "저녁",
                    "amount_krw": 25000, "memo": "",
                },
                client_request_id="man-1",
            )
            self.assertEqual(store.tab_totals("trip-demo-b")["expense"], 25000)
            store.save(
                row_id=created["row_id"], expected_revision=1,
                client_request_id="man-2", change_mode="exception",
                changes={"amount_krw": 27000},
            )
            self.assertEqual(store.tab_totals("trip-demo-b")["expense"], 27000)
            history = store.list_history(created["row_id"])
            self.assertEqual(len(history), 2)
        finally:
            store.close()

    def test_same_api_rejects_card_amount(self):
        store = make_store()
        try:
            with self.assertRaises(SaveError) as ctx:
                store.save(
                    row_id="expense-demo-c1", expected_revision=1,
                    client_request_id="card-amount-x", change_mode="exception",
                    changes={"amount_krw": 5},
                )
            self.assertEqual(ctx.exception.code, "FIELD_READ_ONLY")
        finally:
            store.close()


class IncomeSplitTests(unittest.TestCase):
    def make_source(self, store, amount=500000, request_id="split-p1"):
        return store.create_direct_income(
            fields={
                "display_tab_id": None, "occurred_on": "2026-04-01",
                "amount_krw": amount, "income_kind": "deposit",
                "customer_id": None, "customer_name": "P1",
                "nickname": "", "memo": "",
            },
            client_request_id=request_id,
        )

    def test_split_totals_and_principal_hidden(self):
        store = make_store()
        try:
            created = self.make_source(store)
            result = store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="split-plan-1",
            )
            self.assertEqual(result["remainder"], 0)
            self.assertEqual(store.tab_totals("trip-demo-a")["income"], 1300000)
            self.assertEqual(store.tab_totals("trip-demo-b")["income"], 200000)
            ids = [r["row_id"] for r in store.list_tab_rows("trip-demo-a")]
            self.assertNotIn(created["row_id"], ids)
        finally:
            store.close()

    def test_13_1_a_split_row_shows_its_own_amount_not_the_source_total(self):
        """13.1: 화면 행의 금액은 해당 배분액이고, 원금은 따로 유지된다."""
        store = make_store()
        try:
            created = self.make_source(store, request_id="s13-1-src")
            sid = created["row_id"]
            store.save_allocations(
                source_row_id=sid, expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="s13-1-plan")
            live = {a["allocation_id"]: a
                    for a in store.active_allocations(sid)}
            self.assertEqual(len(live), 2)
            for allocation in live.values():
                # the row shows the allocation amount, never the source total
                self.assertIn(allocation["amount_krw"], (300000, 200000))
                self.assertNotEqual(allocation["amount_krw"], 500000)
            # the source total is untouched by a split
            self.assertEqual(store.get_row(sid)["amount_krw"], 500000)
            # and the two rows add back up to it
            self.assertEqual(sum(a["amount_krw"] for a in live.values()),
                             500000)
        finally:
            store.close()

    def test_13_2_an_allocation_keeps_its_id_across_a_move(self):
        """13.2: 정렬·여행 이동·탭 삭제 후 이동으로 새 ID를 만들지 않는다."""
        store = make_store()
        try:
            created = self.make_source(store, request_id="s13-2-src")
            sid = created["row_id"]
            store.save_allocations(
                source_row_id=sid, expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="s13-2-plan")
            l1 = next(a for a in store.active_allocations(sid)
                      if a["display_tab_id"] == "trip-demo-a")
            l2_id = next(a["allocation_id"] for a in store.active_allocations(sid)
                         if a["display_tab_id"] == "trip-demo-b")
            original_id = l1["allocation_id"]

            store.update_allocation(
                allocation_id=original_id, expected_source_revision=2,
                client_request_id="s13-2-move",
                changes={"display_tab_id": "trip-demo-b"})

            moved = store.get_allocation(original_id)
            self.assertEqual(moved["allocation_id"], original_id)
            self.assertEqual(moved["display_tab_id"], "trip-demo-b")
            # the sibling row is a different row and is not disturbed
            sibling = store.get_allocation(l2_id)
            self.assertEqual(sibling["display_tab_id"], "trip-demo-b")
            self.assertEqual(sibling["customer_name"], "U2")
            self.assertEqual(sibling["amount_krw"], 200000)
        finally:
            store.close()

    def test_13_2_a_stale_plan_cannot_overwrite_a_newer_allocation(self):
        """13.2: 낡은 전체 배분안이 새 결과를 덮어쓰지 못한다."""
        store = make_store()
        try:
            created = self.make_source(store, request_id="s13-2b-src")
            sid = created["row_id"]
            store.save_allocations(
                source_row_id=sid, expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                ],
                client_request_id="s13-2b-plan")
            l1 = store.active_allocations(sid)[0]
            # one allocation moves, which advances the source version
            store.update_allocation(
                allocation_id=l1["allocation_id"], expected_source_revision=2,
                client_request_id="s13-2b-move",
                changes={"display_tab_id": "trip-demo-b"})
            # an editor holding the old whole-plan view now saves it
            with self.assertRaises(SaveError) as ctx:
                store.save_allocations(
                    source_row_id=sid, expected_source_revision=2,
                    allocations=[{"customer_name": "U9",
                                  "display_tab_id": "trip-demo-a",
                                  "income_kind": "deposit",
                                  "amount_krw": 500000}],
                    client_request_id="s13-2b-stale")
            self.assertEqual(ctx.exception.code, "EDIT_CONFLICT")
            # the newer destination survived
            self.assertEqual(store.get_allocation(l1["allocation_id"])
                             ["display_tab_id"], "trip-demo-b")
            # and a stale single-row edit is refused on the same version bound
            with self.assertRaises(SaveError) as ctx2:
                store.update_allocation(
                    allocation_id=l1["allocation_id"],
                    expected_source_revision=2,
                    client_request_id="s13-2b-stale-edit",
                    changes={"display_tab_id": "trip-demo-a"})
            self.assertEqual(ctx2.exception.code, "EDIT_CONFLICT")
        finally:
            store.close()

    def test_13_3_an_unassigned_allocation_and_a_remainder_are_different(self):
        """13.3: 미배정 배분은 여행 없는 활성 배분, 미배분 잔액은 원금에서
        활성 배분 합계를 뺀 값이다. 둘은 같은 분류대기에 보일 수 있지만
        업무 의미가 다르다."""
        store = make_store()
        try:
            created = self.make_source(store, request_id="s13-3-src")
            sid = created["row_id"]

            def revision():
                return store.get_row(sid)["revision"]

            store.save_allocations(
                source_row_id=sid, expected_source_revision=1,
                allocations=[
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                    # decided amount, customer and kind, but no trip
                    {"customer_name": "U3", "display_tab_id": None,
                     "income_kind": "deposit", "amount_krw": 100000},
                ],
                client_request_id="s13-3-plan")

            actives = store.active_allocations(sid)
            unassigned = [a for a in actives if not a.get("display_tab_id")]
            remainder = store.split_remainder(sid)

            # the unassigned row is a real allocation and keeps its own identity
            self.assertEqual(len(unassigned), 1)
            self.assertEqual(unassigned[0]["customer_name"], "U3")
            self.assertEqual(unassigned[0]["income_kind"], "deposit")
            self.assertTrue(unassigned[0]["allocation_id"])

            # the remainder is 500000 - 200000 - 100000, and the unassigned
            # amount is not counted a second time
            self.assertEqual(remainder, 200000)
            self.assertEqual(sum(a["amount_krw"] for a in actives)
                             + remainder, 500000)

            # a remainder is displayed as a derived row, not as a new income
            listed = store.list_tab_rows(None)
            shown = [r for r in listed if r.get("is_remainder")]
            self.assertEqual(len(shown), 1)
            self.assertEqual(shown[0]["amount_krw"], 200000)
            self.assertEqual(shown[0]["source_row_id"], sid)

            # and when everything is allocated the remainder row disappears
            store.save_allocations(
                source_row_id=sid, expected_source_revision=revision(),
                allocations=[
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                    {"customer_name": "U3", "display_tab_id": None,
                     "income_kind": "deposit", "amount_krw": 300000},
                ],
                client_request_id="s13-3-full")
            self.assertEqual(store.split_remainder(sid), 0)
            self.assertEqual(
                [r for r in store.list_tab_rows(None) if r.get("is_remainder")],
                [])
        finally:
            store.close()

    def test_partial_split_remainder_and_over_rejected(self):
        store = make_store()
        try:
            created = self.make_source(store, request_id="split-q1")
            result = store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                ],
                client_request_id="split-qplan",
            )
            self.assertEqual(result["remainder"], 200000)
            self.assertEqual(store.split_remainder(created["row_id"]), 200000)
            with self.assertRaises(SaveError) as ctx:
                store.save_allocations(
                    source_row_id=created["row_id"], expected_source_revision=2,
                    allocations=[
                        {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                         "income_kind": "deposit", "amount_krw": 300000},
                        {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                         "income_kind": "balance", "amount_krw": 250000},
                    ],
                    client_request_id="split-over",
                )
            self.assertEqual(ctx.exception.code, "INVALID_VALUE")
        finally:
            store.close()

    def test_move_revert_remove_and_conflicts(self):
        store = make_store()
        try:
            created = self.make_source(store, request_id="split-m1")
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="split-mplan",
            )
            live = {a["allocation_id"]: a for a in store.active_allocations(created["row_id"])}
            l1 = next(a for a in live.values() if a["display_tab_id"] == "trip-demo-a")
            moved = [
                {"allocation_id": a["allocation_id"], "customer_name": a["customer_name"],
                 "display_tab_id": "trip-demo-b" if a["allocation_id"] == l1["allocation_id"] else a["display_tab_id"],
                 "income_kind": a["income_kind"], "amount_krw": a["amount_krw"]}
                for a in live.values()
            ]
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=2,
                allocations=moved, client_request_id="split-move",
            )
            self.assertEqual(store.tab_totals("trip-demo-a")["income"], 1000000)
            self.assertEqual(store.tab_totals("trip-demo-b")["income"], 500000)
            with self.assertRaises(SaveError) as ctx:
                store.revert_row(
                    row_id=created["row_id"], expected_revision=3,
                    client_request_id="split-rv-full",
                )
            self.assertEqual(ctx.exception.code, "INVALID_VALUE")
            self.assertIn("배분", str(ctx.exception))
            with self.assertRaises(SaveError) as ctx:
                store.save_allocations(
                    source_row_id=created["row_id"], expected_source_revision=2,
                    allocations=[], client_request_id="split-stale",
                )
            self.assertEqual(ctx.exception.code, "EDIT_CONFLICT")
        finally:
            store.close()


class AllocationRevertTests(unittest.TestCase):
    """개별 배분 행 되돌리기/편집 테스트 (X07, X03 반영)."""

    def test_revert_single_allocation(self):
        """X07: L1 A→B 이동 후 되돌리면 L1은 A로 복원, L2 유지."""
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": None, "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1", "nickname": "", "memo": "",
                },
                client_request_id="split-rev-1",
            )
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="split-rev-plan",
            )
            live = {a["allocation_id"]: a for a in store.active_allocations(created["row_id"])}
            l1 = next(a for a in live.values() if a["display_tab_id"] == "trip-demo-a")
            l2 = next(a for a in live.values() if a["display_tab_id"] == "trip-demo-b")
            l2_before = dict(l2)
            edited = store.update_allocation(
                allocation_id=l1["allocation_id"], expected_source_revision=2,
                client_request_id="split-edit-l1",
                changes={"display_tab_id": "trip-demo-b"},
            )
            self.assertEqual(edited["outcome"], "saved")
            self.assertEqual(edited["revision"], 3)
            retry = store.update_allocation(
                allocation_id=l1["allocation_id"], expected_source_revision=2,
                client_request_id="split-edit-l1",
                changes={"display_tab_id": "trip-demo-b"},
            )
            self.assertEqual(retry, edited)
            with self.assertRaises(SaveError) as ctx:
                store.update_allocation(
                    allocation_id=l1["allocation_id"], expected_source_revision=2,
                    client_request_id="split-edit-l1",
                    changes={"display_tab_id": "trip-demo-a"},
                )
            self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")
            after_edit = store.get_allocation(l2["allocation_id"])
            self.assertEqual(after_edit["customer_name"], l2_before["customer_name"])
            self.assertEqual(after_edit["amount_krw"], l2_before["amount_krw"])
            self.assertEqual(after_edit["source_revision"], 3)
            reverted = store.revert_row(
                row_id=l1["allocation_id"], expected_revision=3,
                client_request_id="split-revert-l1",
            )
            self.assertEqual(reverted["outcome"], "reverted")
            self.assertEqual(reverted["revision"], 4)
            self.assertEqual(store.get_allocation(l1["allocation_id"])["display_tab_id"], "trip-demo-a")
            final_l2 = store.get_allocation(l2["allocation_id"])
            for field in ("customer_id", "customer_name", "nickname", "display_tab_id",
                          "income_kind", "amount_krw", "active"):
                self.assertEqual(final_l2[field], after_edit[field])
            self.assertEqual(final_l2["source_revision"], 4)
            self.assertEqual(store.tab_totals("trip-demo-a")["income"], 1300000)
            self.assertEqual(store.tab_totals("trip-demo-b")["income"], 200000)
            retry_revert = store.revert_row(
                row_id=l1["allocation_id"], expected_revision=3,
                client_request_id="split-revert-l1",
            )
            self.assertEqual(retry_revert, reverted)
            with self.assertRaises(SaveError) as ctx:
                store.revert_row(
                    row_id=l1["allocation_id"], expected_revision=4,
                    client_request_id="split-revert-l1-again",
                )
            self.assertEqual(ctx.exception.code, "INVALID_VALUE")
            self.assertIn("이미", str(ctx.exception))
        finally:
            store.close()


class AllocationEditTests(unittest.TestCase):
    """개별 배분 행 편집 테스트 (X05, X03 반영)."""

    def test_edit_allocation_customer_trip_kind(self):
        """개별 배분 행의 고객/여행/입금종류만 수정."""
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": None, "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1", "nickname": "", "memo": "",
                },
                client_request_id="split-edit-1",
            )
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="split-edit-plan",
            )
            allocs = store.active_allocations(created["row_id"])
            a1 = next(a for a in allocs if a["display_tab_id"] == "trip-demo-a")
            a2 = next(a for a in allocs if a["display_tab_id"] == "trip-demo-b")
            
            # Edit a1: change customer, trip, kind
            result = store.update_allocation(
                allocation_id=a1["allocation_id"],
                expected_source_revision=2,
                client_request_id="edit-a1",
                changes={
                    "customer_name": "U1-mod",
                    "display_tab_id": "trip-demo-b",
                    "income_kind": "balance",
                },
            )
            self.assertEqual(result["outcome"], "saved")
            self.assertEqual(result["revision"], 3)
            retry = store.update_allocation(
                allocation_id=a1["allocation_id"],
                expected_source_revision=2,
                client_request_id="edit-a1",
                changes={
                    "customer_name": "U1-mod",
                    "display_tab_id": "trip-demo-b",
                    "income_kind": "balance",
                },
            )
            self.assertEqual(retry, result)
            with self.assertRaises(SaveError) as ctx:
                store.update_allocation(
                    allocation_id=a1["allocation_id"],
                    expected_source_revision=2,
                    client_request_id="edit-a1",
                    changes={"customer_name": "different"},
                )
            self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")
            with self.assertRaises(SaveError) as ctx:
                store.revert_row(
                    row_id=a1["allocation_id"], expected_revision=3,
                    client_request_id="edit-a1",
                )
            self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")
            updated = store.get_allocation(a1["allocation_id"])
            self.assertEqual(updated["customer_name"], "U1-mod")
            self.assertEqual(updated["display_tab_id"], "trip-demo-b")
            self.assertEqual(updated["income_kind"], "balance")
            a2_check = store.get_allocation(a2["allocation_id"])
            self.assertEqual(a2_check["customer_name"], "U2")
            self.assertEqual(a2_check["display_tab_id"], "trip-demo-b")
            self.assertEqual(a2_check["amount_krw"], 200000)
            self.assertEqual(a2_check["source_revision"], 3)
            self.assertEqual(store.get_row(created["row_id"])["revision"], 3)
            self.assertEqual(
                store.conn.execute(
                    "SELECT COUNT(*) FROM income_allocation_history WHERE client_request_id=?",
                    ("edit-a1",),
                ).fetchone()[0],
                1,
            )
        finally:
            store.close()

    def test_revert_rejects_stale_full_plan_and_inactive(self):
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": None, "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1", "nickname": "", "memo": "",
                },
                client_request_id="split-stale-1",
            )
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="split-stale-plan",
            )
            a1 = next(
                a for a in store.active_allocations(created["row_id"])
                if a["display_tab_id"] == "trip-demo-a"
            )
            store.update_allocation(
                allocation_id=a1["allocation_id"], expected_source_revision=2,
                client_request_id="split-stale-edit",
                changes={"display_tab_id": "trip-demo-b"},
            )
            current_plan = []
            for allocation in store.active_allocations(created["row_id"]):
                current_plan.append({
                    "allocation_id": allocation["allocation_id"],
                    "customer_name": (
                        "U2-new" if allocation["allocation_id"] != a1["allocation_id"]
                        else allocation["customer_name"]
                    ),
                    "display_tab_id": allocation["display_tab_id"],
                    "income_kind": allocation["income_kind"],
                    "amount_krw": allocation["amount_krw"],
                })
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=3,
                allocations=current_plan, client_request_id="split-after-edit-plan",
            )
            with self.assertRaises(SaveError) as ctx:
                store.revert_row(
                    row_id=a1["allocation_id"], expected_revision=4,
                    client_request_id="split-stale-revert",
                )
            self.assertEqual(ctx.exception.code, "INVALID_VALUE")
            self.assertIn("최신", str(ctx.exception))
            without_a1 = [
                item for item in current_plan
                if item["allocation_id"] != a1["allocation_id"]
            ]
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=4,
                allocations=without_a1, client_request_id="split-remove-a1",
            )
            with self.assertRaises(SaveError) as ctx:
                store.update_allocation(
                    allocation_id=a1["allocation_id"], expected_source_revision=5,
                    client_request_id="split-inactive-edit",
                    changes={"customer_name": "inactive-edit"},
                )
            self.assertEqual(ctx.exception.code, "INVALID_VALUE")
            self.assertIn("비활성", str(ctx.exception))
            with self.assertRaises(SaveError) as ctx:
                store.revert_row(
                    row_id=a1["allocation_id"], expected_revision=5,
                    client_request_id="split-inactive-revert",
                )
            self.assertEqual(ctx.exception.code, "INVALID_VALUE")
            self.assertIn("비활성", str(ctx.exception))
        finally:
            store.close()

    def test_the_revert_scope_is_one_row_and_there_is_no_whole_plan_restore(self):
        """REVIEW 수정 D: 개별 행 되돌리기는 허용하되 전체 배분안 복원 기능은 없다.

        The contract keeps two things apart: an operator may undo one allocation
        row they just moved, and there is no feature that rolls a whole
        allocation plan back. The second is a *capability that must not exist*,
        so it is asserted by name rather than by behaviour.
        """
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": None, "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1", "nickname": "",
                    "memo": "",
                },
                client_request_id="rv-scope-src",
            )
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                    {"customer_name": "U2", "display_tab_id": "trip-demo-b",
                     "income_kind": "balance", "amount_krw": 200000},
                ],
                client_request_id="rv-scope-plan",
            )
            live = {a["allocation_id"]: a
                    for a in store.active_allocations(created["row_id"])}
            l1 = next(a for a in live.values()
                      if a["display_tab_id"] == "trip-demo-a")
            l2 = next(a for a in live.values()
                      if a["display_tab_id"] == "trip-demo-b")
            l2_before = dict(l2)

            # 1. no whole-plan restore exists under any plausible name
            for name in dir(store):
                lowered = name.lower()
                if "plan" in lowered and ("revert" in lowered
                                          or "restore" in lowered
                                          or "rollback" in lowered):
                    self.fail(f"a whole-plan restore appeared: {name}")
            # the only revert entry point is the per-row one
            self.assertTrue(hasattr(store, "revert_row"))

            # 2. one row can be moved and undone, and the sibling is untouched
            edited = store.update_allocation(
                allocation_id=l1["allocation_id"],
                expected_source_revision=2,
                client_request_id="rv-scope-edit",
                changes={"display_tab_id": "trip-demo-b"},
            )
            self.assertEqual(edited["outcome"], "saved")
            reverted = store.revert_row(
                row_id=l1["allocation_id"],
                expected_revision=edited["revision"],
                client_request_id="rv-scope-revert",
            )
            self.assertEqual(reverted["outcome"], "reverted")
            self.assertEqual(store.get_allocation(l1["allocation_id"])["display_tab_id"],
                             "trip-demo-a")

            # 3. the sibling kept its own values throughout
            after = store.get_allocation(l2["allocation_id"])
            for field in ("customer_name", "amount_krw", "display_tab_id"):
                self.assertEqual(after[field], l2_before[field], field)
        finally:
            store.close()

    def test_revert_rejects_deleted_previous_trip(self):
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": None, "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1", "nickname": "", "memo": "",
                },
                client_request_id="split-deleted-trip",
            )
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                ],
                client_request_id="split-deleted-plan",
            )
            allocation = store.active_allocations(created["row_id"])[0]
            store.update_allocation(
                allocation_id=allocation["allocation_id"], expected_source_revision=2,
                client_request_id="split-deleted-edit-1",
                changes={"display_tab_id": "trip-demo-b"},
            )
            store.update_allocation(
                allocation_id=allocation["allocation_id"], expected_source_revision=3,
                client_request_id="split-deleted-edit-2",
                changes={"display_tab_id": "trip-demo-a"},
            )
            store.conn.execute(
                "UPDATE trip_tabs SET deleted=1 WHERE tab_id='trip-demo-b'"
            )
            with self.assertRaises(SaveError) as ctx:
                store.revert_row(
                    row_id=allocation["allocation_id"], expected_revision=4,
                    client_request_id="split-deleted-revert",
                )
            self.assertEqual(ctx.exception.code, "TARGET_NOT_ASSIGNABLE")
            self.assertEqual(store.get_row(created["row_id"])["revision"], 4)
        finally:
            store.close()

    def test_edit_amount_rejected(self):
        """금액/날짜/원천 변경은 거부."""
        store = make_store()
        try:
            created = store.create_direct_income(
                fields={
                    "display_tab_id": None, "occurred_on": "2026-04-01",
                    "amount_krw": 500000, "income_kind": "deposit",
                    "customer_id": None, "customer_name": "P1", "nickname": "", "memo": "",
                },
                client_request_id="split-edit-2",
            )
            store.save_allocations(
                source_row_id=created["row_id"], expected_source_revision=1,
                allocations=[
                    {"customer_name": "U1", "display_tab_id": "trip-demo-a",
                     "income_kind": "deposit", "amount_krw": 300000},
                ],
                client_request_id="split-edit-plan",
            )
            alloc = store.active_allocations(created["row_id"])[0]
            for field, value, request_id in (
                ("amount_krw", 100000, "edit-amount"),
                ("occurred_on", "2026-04-02", "edit-date"),
                ("source_row_id", "other-source", "edit-source"),
            ):
                with self.subTest(field=field):
                    with self.assertRaises(SaveError) as ctx:
                        store.update_allocation(
                            allocation_id=alloc["allocation_id"],
                            expected_source_revision=2,
                            client_request_id=request_id,
                            changes={field: value},
                        )
                    self.assertEqual(ctx.exception.code, "FIELD_READ_ONLY")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()