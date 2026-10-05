"""선택 결과의 실제 장부 이관 — 합성 자료만으로.

고객 값, 실제 자료, 실제 장부는 이 파일에 없다. 합성 카드 원장과 합성 워크북으로
기준에 적힌 근거를 하나씩 고정한다. "지금 승인 0건"이라는 상태는 그대로 둔다 —
검사가 성공하기 위해 그 상태를 바꾸지 않는다.

선택은 검토 CSV가 아니라 **선택 저장소**에 있다. 검토 CSV의 `reviewer_decision`은
항상 공란이고, 소유자가 누른 결정이 저장 versioning의 새 행이 된다. 그래서 이
검사는 승인 상태를 만들 때도 저장 경로만 쓴다.
"""

import csv
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from webapp import ledger_apply, ledger_store, real_review, review_refresh  # noqa: E402
from webapp.ledger_store import SaveError  # noqa: E402
from webapp.review_context import MASTER_HEADERS  # noqa: E402
from webapp.tests import review_fixtures as fx  # noqa: E402


class ApplyFixture(unittest.TestCase):
    """A synthetic bundle, a real store, and no customer anything."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.store = ledger_store.LedgerStore(self.tmp / "board.sqlite",
                                              seed_demo=False)
        self.addCleanup(self._close)

        self.bundle_root = self.tmp / "bundles"
        self.config_path = self.tmp / "review.json"
        self.decisions_db = self.tmp / "decisions.sqlite"
        self._previous = {
            real_review.CONFIG_ENV: os.environ.get(real_review.CONFIG_ENV),
            "WEBLEDGER_DB": os.environ.get("WEBLEDGER_DB"),
        }
        os.environ[real_review.CONFIG_ENV] = str(self.config_path)
        os.environ["WEBLEDGER_DB"] = str(self.decisions_db)
        real_review.clear_real_review()
        self.addCleanup(self._restore)
        self.facts = []
        # A bundle inherits the decision history from the config it replaces.
        self.config_path.write_text(json.dumps(
            {"decisions_db_path": str(self.decisions_db)}), encoding="utf-8")

    def _close(self):
        try:
            self.store.close()
        finally:
            self.store.ledger.close()

    def _restore(self):
        real_review.clear_real_review()
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # -- the synthetic source -------------------------------------------------
    def fact(self, key="T-1", *, krw="12000", approval="", posting="",
             cancel="정상", local="", currency="", merchant="합성이용점",
             issuer="합성카드사", last4="0000"):
        """One card fact, in the master's own seventeen columns.

        The dates default per key. Two transactions on the same day with the same
        amount would each be a candidate for both workbook rows, and the tests
        here are about what reaches the ledger, not about how the match works.
        """
        if not local and not currency and krw.startswith("-"):
            local, currency = "-900", "JPY"
        index = int(key.split("-")[-1]) if key.split("-")[-1].isdigit() else 1
        approval = approval or f"2026-04-{index:02d}"
        posting = posting or f"2026-04-{index + 10:02d}"
        return {
            "거래키": key, "카드사": issuer, "카드4": last4, "구분": "매출",
            "승인일": approval, "매입일": posting, "가맹점": merchant,
            "원화금액": krw, "현지금액": local, "통화": currency,
            "승인번호": "APPROVAL-" + key, "취소여부": cancel,
            "출처": "합성원장", "적재일": "2026-04-30", "기록여부": "N",
            "워크북참조": "", "비고": "",
        }

    def master_text(self, facts):
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(MASTER_HEADERS),
                                lineterminator="\n")
        writer.writeheader()
        for record in facts:
            writer.writerow({name: record.get(name, "")
                             for name in MASTER_HEADERS})
        return buffer.getvalue()

    def snapshot_bytes(self, facts):
        """A workbook whose cells say what the card master says.

        The candidate match is by date and amount, so a workbook row that says a
        different amount than the master would offer no candidates at all — and a
        test about what gets written would pass for the wrong reason.
        """
        return fx.build_snapshot_bytes([
            (fact["승인일"] or fact["매입일"], "합성항목",
             f"합성내용{index + 1}", int(fact["원화금액"]))
            for index, fact in enumerate(facts)])

    def activate(self, facts, *, keys_per_ref=None):
        """Collect and activate a bundle from the synthetic facts.

        The review CSV the collector builds is blank, exactly as it always is.
        Approving happens through the decision store, below.
        """
        self.facts = list(facts)
        result = review_refresh.collect_and_activate(
            self.config_path, self.bundle_root,
            self.snapshot_bytes(facts), self.master_text(facts),
            minimum_rows=0)
        self.assertNotEqual(result.get("code"), "REFRESH_SCOPE_UNPROVEN")
        return result

    # -- approving the way the owner does -------------------------------------
    def approve(self, keys, note=""):
        """Store the owner's decisions, through the same save the screen uses."""
        service = self.service()
        rows = {row["ref"]: row for row in service.model()["rows"]}
        submitted = []
        for ref, row in rows.items():
            candidates = [candidate["key"] for candidate in row["candidates"]]
            if not candidates:
                continue
            if candidates[0] in keys:
                submitted.append({"ref": ref,
                                  "value": "APPROVE:" + candidates[0]})
        saved = service.save_decisions(submitted, 0, service.model_binding())
        self.assertEqual(saved["revision"], 1)
        del note
        return submitted

    def service(self):
        real_review._LAST_RECHECK = 0.0
        service = real_review.active_service()
        self.assertIsNotNone(service)
        return service

    def plan(self, service=None):
        return ledger_apply.build_apply_plan(service or self.service(),
                                              self.store)

    def apply(self, plan, request_id="apply-1", transactions=None):
        # Named explicitly, the way a page names them. The core's convenience
        # default exists for callers that have read the plan; these tests are
        # about the contract a request actually has to satisfy.
        if transactions is None:
            # Exactly the entry the plan route publishes, which is what a page
            # holds and sends back.
            transactions = [{"ref": item["ref"],
                             "source_event_key": item["chosen_candidate_key"],
                             "fact_digest": item["fact_digest"]}
                            for item in plan["transactions"]]
        return ledger_apply.apply_apply_plan(
            self.service(), self.store, request_id=request_id,
            presented_binding=plan["binding"],
            presented_revision=plan["choices_revision"],
            presented_plan_digest=plan["plan_digest"],
            presented_transactions=transactions)

    def board_rows(self):
        return self.store.conn.execute(
            "SELECT row_id, payload_json FROM board_rows").fetchall()

    def facts_on_disk(self, key="T-1"):
        row = self.store.conn.execute(
            "SELECT facts_json FROM source_fact_rows WHERE source_event_key=?",
            (key,)).fetchone()
        return None if row is None else json.loads(row[0])


class FactPreservationTests(ApplyFixture):
    """The seventeen columns and the facts inside them survive the write."""

    def test_every_original_column_is_kept_on_the_fact_row(self):
        self.activate([self.fact("T-1", krw="-9000", local="-900",
                                 currency="JPY", cancel="취소")])
        self.approve({"T-1"})
        result = self.apply(self.plan())
        self.assertEqual(result["counts"]["applied"], 1)
        kept = self.facts_on_disk("T-1")
        self.assertEqual(tuple(kept), MASTER_HEADERS)
        self.assertEqual(kept["승인일"], "2026-04-01")
        self.assertEqual(kept["매입일"], "2026-04-11")
        self.assertEqual(kept["원화금액"], "-9000")
        self.assertEqual(kept["현지금액"], "-900")
        self.assertEqual(kept["통화"], "JPY")
        self.assertEqual(kept["취소여부"], "취소")
        self.assertEqual(kept["출처"], "합성원장")

    def test_both_dates_survive_and_a_zero_amount_is_kept(self):
        self.activate([self.fact("T-1", krw="0", local="0")])
        self.approve({"T-1"})
        self.apply(self.plan())
        payload = json.loads(self.board_rows()[0][1])
        self.assertEqual(payload["source_approval_date"], "2026-04-01")
        self.assertEqual(payload["source_posting_date"], "2026-04-11")
        self.assertEqual(payload["amount_krw"], 0)

    def test_a_cancellation_keeps_its_negative_sign(self):
        self.activate([self.fact("T-1", krw="-9000", local="-900",
                                 currency="JPY", cancel="취소")])
        self.approve({"T-1"})
        self.apply(self.plan())
        payload = json.loads(self.board_rows()[0][1])
        self.assertEqual(payload["amount_krw"], -9000)
        self.assertEqual(payload["source_cancelled"], "취소")

    def test_the_transaction_key_is_the_identity_not_an_approval_number(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        result = self.apply(self.plan())
        self.assertEqual(result["applied"][0]["source_event_key"], "T-1")
        payload = json.loads(self.board_rows()[0][1])
        self.assertEqual(payload["source_event_id"], "T-1")
        self.assertNotEqual(payload["source_event_id"],
                            payload["source_approval_number"])

    def test_no_item_is_named_from_a_merchant_and_no_rule_is_applied(self):
        """`import_row` writes 숙박비 for AGODA and runs the active rules.

        A reviewed fact is classified by neither. The item stays empty and the
        basis says where the row came from.
        """
        self.activate([self.fact("T-1", merchant="AGODA")])
        self.approve({"T-1"})
        self.apply(self.plan())
        payload = json.loads(self.board_rows()[0][1])
        self.assertEqual(payload["item"], "")
        self.assertEqual(payload["classification_state"], "unclassified")
        self.assertNotIn("영칙적용", payload["classification_basis"])

    def test_the_source_binding_is_kept_on_the_row(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        self.apply(self.plan())
        service = self.service()
        payload = json.loads(self.board_rows()[0][1])
        self.assertEqual(payload["source_fact_digest"],
                         self.store.applied_source_fact("T-1")["fact_digest"])
        self.assertEqual(service.model_binding().count("|"), 2)


class DedupeTests(ApplyFixture):
    """One transaction is one expense, whatever the workbook did to it."""

    def test_the_same_amount_under_two_keys_is_two_transactions(self):
        self.activate([self.fact("T-1"), self.fact("T-2")])
        self.approve({"T-1", "T-2"})
        # The workbook must offer two distinct candidates for two rows.
        result = self.apply(self.plan())
        self.assertEqual(result["counts"]["applied"], 2)
        self.assertEqual(len(self.board_rows()), 2)

    def test_two_refs_naming_one_transaction_make_one_expense(self):
        """The same key offered to two rows is applied once and held once."""
        # Two workbook rows with the same date and amount, and a master holding
        # one transaction. Both rows therefore offer the same single candidate,
        # which is the situation the dedupe exists for.
        fact = self.fact("T-1")
        workbook = fx.build_snapshot_bytes([
            (fact["승인일"], "합성항목", "합성내용1", 12000),
            (fact["승인일"], "합성항목", "합성내용2", 12000)])
        review_refresh.collect_and_activate(
            self.config_path, self.bundle_root, workbook,
            self.master_text([fact]), minimum_rows=0)
        self.facts = [fact]
        service = self.service()
        rows = service.model()["rows"]
        self.assertGreaterEqual(len(rows), 2)
        # Both rows are pointed at the one transaction key, which is what happens
        # when a workbook cell is matched to a candidate already claimed.
        submitted = [{"ref": rows[0]["ref"], "value": "APPROVE:T-1"},
                     {"ref": rows[1]["ref"], "value": "APPROVE:T-1"}]
        saved = service.save_decisions(submitted, 0, service.model_binding())
        self.assertEqual(saved["revision"], 1)
        result = self.apply(self.plan())
        self.assertEqual(result["counts"]["applied"] + result["counts"]["unchanged"],
                         1)
        self.assertEqual(len(self.board_rows()), 1)


class IdempotencyTests(ApplyFixture):
    """Applying twice writes once."""

    def test_the_same_key_and_facts_apply_once_and_change_nothing(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        shown = self.plan()
        named = [{"ref": item["ref"],
                  "source_event_key": item["chosen_candidate_key"],
                  "fact_digest": item["fact_digest"]}
                 for item in shown["transactions"]]
        first = self.apply(shown, request_id="apply-1")
        self.assertEqual(first["counts"]["applied"], 1)
        rows_before = self.board_rows()
        revisions_before = self.store.conn.execute(
            "SELECT COUNT(*) FROM board_revisions").fetchone()[0]

        # A different request naming the same transaction: a no-change success,
        # because that is what applying the same thing twice is.
        second = self.apply(shown, request_id="apply-2", transactions=named)
        self.assertEqual(second["counts"]["applied"], 0)
        self.assertEqual(second["counts"]["unchanged"], 1)

        # The same request again: the same answer, from the request record.
        replay = self.apply(shown, request_id="apply-1", transactions=named)
        self.assertEqual(replay["counts"], first["counts"])
        self.assertEqual(replay["request_id"], first["request_id"])

        self.assertEqual(self.board_rows(), rows_before)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM board_revisions").fetchone()[0],
            revisions_before)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM source_fact_applies").fetchone()[0], 2)

    def test_a_fresh_plan_with_nothing_left_to_write_is_refused(self):
        """An apply is never a silent success.

        Once every approved transaction is in the ledger, the plan has nothing to
        offer and the request says so rather than reporting a success nobody can
        distinguish from a write that happened.
        """
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        self.apply(self.plan(), request_id="apply-1")
        with self.assertRaises(ledger_apply.ApplyPlanError) as caught:
            self.apply(self.plan(), request_id="apply-3")
        self.assertEqual(caught.exception.code,
                         ledger_apply.CODE_APPLY_NOTHING_TO_DO)
        self.assertEqual(len(self.board_rows()), 1)

    def test_the_plan_reports_what_is_already_there_before_it_is_run(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        self.apply(self.plan())
        plan = self.plan()
        self.assertEqual(plan["counts"]["already_applied_transactions"], 1)
        self.assertEqual(plan["counts"]["applicable_transactions"], 0)

    def test_a_users_own_edit_survives_a_repeat(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        shown = self.plan()
        named = [{"ref": item["ref"],
                  "source_event_key": item["chosen_candidate_key"],
                  "fact_digest": item["fact_digest"]}
                 for item in shown["transactions"]]
        result = self.apply(shown)
        row_id = result["applied"][0]["row_id"]
        self.store.save(row_id=row_id, expected_revision=1,
                        client_request_id="manual-1",
                        change_mode="exception",
                        changes={"operator_note": "팀장 확인함"})
        again = self.apply(shown, request_id="apply-2", transactions=named)
        self.assertEqual(again["counts"]["unchanged"], 1)
        self.assertEqual(self.store.get_row(row_id)["operator_note"],
                         "팀장 확인함")

    def test_changed_facts_under_the_same_key_are_a_conflict(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        self.apply(self.plan())
        self.activate([self.fact("T-1", krw="99999")])
        self.approve({"T-1"}, note="re-approve")
        plan = self.plan()
        self.assertEqual(plan["counts"]["conflict_transactions"], 1)
        self.assertEqual(plan["counts"]["applicable_transactions"], 0)
        # A client that still holds the plan it was shown names the transaction,
        # and is told the facts moved rather than being handed a silent no-op.
        with self.assertRaises(ledger_apply.ApplyPlanError) as caught:
            self.apply(plan, request_id="apply-2",
                       transactions=[{"ref": "어떤 행",
                                      "source_event_key": "T-1",
                                      "fact_digest": self.plan()["approved_refs"][0]["fact_digest"]}])
        self.assertEqual(caught.exception.code,
                         ledger_apply.CODE_APPLY_ONLY_CONFLICTS)
        # A plan that offers nothing to write is refused as itself.
        with self.assertRaises(ledger_apply.ApplyPlanError) as nothing:
            self.apply(plan, request_id="apply-3")
        self.assertEqual(nothing.exception.code,
                         ledger_apply.CODE_APPLY_NOTHING_TO_DO)
        # Nothing was overwritten and nothing was written under a new key.
        self.assertEqual(len(self.board_rows()), 1)
        self.assertEqual(json.loads(self.board_rows()[0][1])["amount_krw"],
                         12000)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM source_fact_rows").fetchone()[0], 1)

    def test_the_same_request_id_with_other_inputs_is_a_conflict(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        plan = self.plan()
        items = [{"source_event_key": entry["chosen_candidate_key"],
                  "facts": entry["facts"], "workbook_ref": "",
                  "review_ref": entry["ref"],
                  "review_snapshot_sha256": plan["snapshot_sha256"],
                  "review_note": ""} for entry in plan["transactions"]]
        first = self.store.apply_reviewed_source_facts(
            request_id="apply-1", input_digest="a" * 64,
            expected_binding=plan["binding"], expected_choices_revision=1,
            items=items)
        self.assertEqual(first["counts"]["applied"], 1)
        # The same request id, a different set of inputs.
        with self.assertRaises(SaveError) as caught:
            self.store.apply_reviewed_source_facts(
                request_id="apply-1", input_digest="b" * 64,
                expected_binding=plan["binding"],
                expected_choices_revision=1, items=[])
        self.assertEqual(caught.exception.code, "APPLY_REQUEST_INPUT_CONFLICT")
        # And through the API the same request is refused, writing nothing.
        with self.assertRaises(ledger_apply.ApplyPlanError):
            self.apply(self.plan(), request_id="apply-1",
                       transactions=[{"ref": "어떤 행",
                                      "source_event_key": "T-1",
                                      "fact_digest": "f" * 64}])
        self.assertEqual(len(self.board_rows()), 1)


class TransactionTests(ApplyFixture):
    """One transaction, and a retry that reproduces it."""

    def test_a_failure_part_way_leaves_nothing_behind(self):
        self.activate([self.fact("T-1"), self.fact("T-2")])
        self.approve({"T-1", "T-2"})
        plan = self.plan()
        self.assertEqual(plan["counts"]["applicable_transactions"], 2)
        original = self.store._apply_one_source_fact
        calls = {"n": 0}

        def explode(item, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("half way")
            return original(item, **kwargs)

        self.store._apply_one_source_fact = explode
        self.addCleanup(setattr, self.store, "_apply_one_source_fact",
                        original)
        with self.assertRaises(RuntimeError):
            self.apply(plan)
        self.assertEqual(self.board_rows(), [])
        for table in ("source_fact_rows", "source_fact_applies",
                      "ledger_outbox", "board_revisions"):
            self.assertEqual(self.store.conn.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

        # The same request, retried, reproduces the same result.
        self.store._apply_one_source_fact = original
        result = self.apply(plan)
        self.assertEqual(result["counts"]["applied"], 2)
        self.assertEqual(len(self.board_rows()), 2)

    def test_the_fact_the_row_the_version_and_the_event_are_one_write(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        self.apply(self.plan())
        counts = self.store.conn.execute(
            "SELECT (SELECT COUNT(*) FROM source_fact_rows),"
            " (SELECT COUNT(*) FROM source_fact_applies),"
            " (SELECT COUNT(*) FROM board_rows),"
            " (SELECT COUNT(*) FROM board_revisions),"
            " (SELECT COUNT(*) FROM ledger_outbox)").fetchone()
        self.assertEqual(tuple(counts), (1, 1, 1, 1, 1))

    def test_an_audit_event_left_waiting_goes_out_through_the_old_path(self):
        """A relay failure is not a lost row and never a second row."""
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        original = self.store.ledger.append

        def refuse(**kwargs):
            raise RuntimeError("감사 기록이 멈췄어요")

        self.store.ledger.append = refuse
        self.addCleanup(setattr, self.store.ledger, "append", original)
        shown = self.plan()
        named = [{"ref": item["ref"],
                  "source_event_key": item["chosen_candidate_key"],
                  "fact_digest": item["fact_digest"]}
                 for item in shown["transactions"]]
        result = self.apply(shown)
        self.assertEqual(result["counts"]["applied"], 1)
        self.assertEqual(self.store.conn.execute(
            "SELECT relayed FROM ledger_outbox").fetchall(), [(0,)])

        # The next write retries it through `_replay_pending`, and the row is not
        # made a second time.
        self.store.ledger.append = original
        self.apply(shown, request_id="apply-2", transactions=named)
        self.assertEqual(len(self.board_rows()), 1)
        self.assertEqual(self.store.conn.execute(
            "SELECT relayed FROM ledger_outbox").fetchall(), [(1,)])


class ConcurrencyTests(ApplyFixture):
    """Two writers, one result."""

    def test_two_applies_of_one_plan_produce_one_row(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        plan = self.plan()
        results, errors = [], []

        def run():
            try:
                results.append(self.apply(plan, request_id="apply-1"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # The two writers are serialised, so one of three things happens and all
        # three are safe: the first applies, the second is refused as busy, or the
        # second is answered from the request record. What cannot happen is a
        # second row, or a refusal that left a row behind.
        self.assertEqual(len(self.board_rows()), 1)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM source_fact_rows").fetchone()[0], 1)
        applied = [r["counts"]["applied"] for r in results]
        self.assertTrue(applied.count(1) <= 1)
        for error in errors:
            self.assertIn(error.code,
                          ("REFRESH_COLLECTOR_BUSY", "APPLY_REQUEST_INPUT_CONFLICT",
                           "REVIEW_APPLY_REVISION_CONFLICT",
                           "REVIEW_SOURCE_BINDING_CONFLICT"))
        self.assertEqual(len(results) + len(errors), 2)


class RefusalTests(ApplyFixture):
    """The checks that stop a write, and what stays held."""

    def test_an_earlier_bundle_is_refused(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        old = self.plan()
        self.activate([self.fact("T-1"), self.fact("T-2")])
        with self.assertRaises(ledger_apply.ApplyPlanError) as caught:
            ledger_apply.apply_apply_plan(
                self.service(), self.store, request_id="apply-1",
                presented_binding=old["binding"],
                presented_revision=old["choices_revision"],
                presented_plan_digest=old["plan_digest"])
        self.assertIn(caught.exception.code,
                      (ledger_apply.CODE_PLAN_BINDING_CONFLICT,
                       ledger_apply.CODE_PLAN_REVISION_CONFLICT))
        self.assertEqual(self.board_rows(), [])

    def test_an_earlier_choices_version_is_refused(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        service = self.service()
        self.activate([self.fact("T-1"), self.fact("T-2")])
        with self.assertRaises(ledger_apply.ApplyPlanError) as caught:
            ledger_apply.apply_apply_plan(
                self.service(), self.store, request_id="apply-1",
                presented_binding=service.model_binding(),
                presented_revision=0, presented_plan_digest="")
        self.assertIn(caught.exception.code,
                      (ledger_apply.CODE_PLAN_REVISION_CONFLICT,
                       ledger_apply.CODE_PLAN_BINDING_CONFLICT))
        self.assertEqual(self.board_rows(), [])

    def test_nothing_approved_is_refused_rather_than_silently_succeeding(self):
        self.activate([self.fact("T-1")])
        plan = self.plan()
        self.assertEqual(plan["counts"]["applicable_transactions"], 0)
        with self.assertRaises(ledger_apply.ApplyPlanError) as caught:
            self.apply(plan)
        self.assertEqual(caught.exception.code,
                         ledger_apply.CODE_APPLY_NOTHING_TO_DO)
        self.assertEqual(self.board_rows(), [])

    def test_unselected_and_rejected_rows_stay_held(self):
        self.activate([self.fact("T-1"), self.fact("T-2"), self.fact("T-3")])
        service = self.service()
        rows = service.model()["rows"]
        first, second, third = (rows[0], rows[1], rows[2])
        key = lambda row: row["candidates"][0]["key"]  # noqa: E731
        service.save_decisions(
            [{"ref": first["ref"], "value": "APPROVE:" + key(first)},
             {"ref": second["ref"], "value": "REJECT"},
             # The third is left alone: unselected.
             {"ref": third["ref"], "value": ""}],
            0, service.model_binding())
        plan = self.plan()
        self.assertEqual(plan["counts"]["applicable_transactions"], 1)
        self.assertEqual(plan["counts"]["held_refs"], 2)
        self.assertEqual(self.apply(plan)["counts"]["applied"], 1)
        self.assertEqual(len(self.board_rows()), 1)

    def test_a_plan_is_a_read_and_writes_nothing(self):
        self.activate([self.fact("T-1")])
        self.approve({"T-1"})
        for _ in range(3):
            plan = self.plan()
        self.assertEqual(self.board_rows(), [])
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM source_fact_rows").fetchone()[0], 0)

    def test_the_plan_reads_the_stored_choices_not_the_bundle_csv(self):
        """The bundle's review CSV is blank, and the plan is not.

        If the plan read the CSV there would be nothing to apply, ever. If it read
        the browser it would apply what nobody saved. It reads the store.
        """
        self.activate([self.fact("T-1")])
        service = self.service()
        manifest = json.loads(self.config_path.read_text(encoding="utf-8"))
        csv_text = pathlib.Path(manifest["review_path"]).read_bytes().decode(
            "utf-8")
        self.assertNotIn("APPROVE:", csv_text)
        self.assertEqual(self.plan()["counts"]["applicable_transactions"], 0)
        self.approve({"T-1"})
        self.assertEqual(self.plan()["counts"]["applicable_transactions"], 1)




class SeparateProcessTests(ApplyFixture):
    """A second operating-system process, saving to the same decision database.

    An in-process fence proves nothing about the operator's real situation, where
    the web app and an apply can be in different processes — a background service
    and a browser, two terminals, a scheduled run. The lock therefore has to be
    the operating system's, on a file beside the database, and this is the check
    that says so.
    """

    PEER = """
import json, pathlib, sys, time
from webapp import real_review
config, binding, revision, ref, ready, go = sys.argv[1:]
peer = real_review.RealReviewService(real_review.load_manifest(config))
peer.config_path = config
pathlib.Path(ready).write_text("ready")
deadline = time.monotonic() + 15
while not pathlib.Path(go).exists():
    if time.monotonic() >= deadline:
        raise SystemExit(3)
    time.sleep(0.02)
try:
    saved = peer.save_decisions([{"ref": ref, "value": "REJECT"}],
                                int(revision), binding)
    print(json.dumps({"changed": True, "revision": saved["revision"]}))
except real_review.RealReviewError as error:
    print(json.dumps({"changed": False, "code": error.code}))
"""

    def test_another_process_cannot_change_the_choices_at_the_commit_boundary(self):
        self.activate([self.fact("CROSS-PROCESS")])
        self.approve({"CROSS-PROCESS"})
        shown = self.plan()
        service = self.service()
        ref = service.model()["rows"][0]["ref"]
        ready = self.tmp / "peer-ready"
        go = self.tmp / "peer-go"
        process = subprocess.Popen(
            [sys.executable, "-c", self.PEER, str(self.config_path),
             shown["binding"], str(shown["choices_revision"]), ref,
             str(ready), str(go)],
            # The repository root, so the peer can import `webapp` at all. Its own
            # working directory says nothing about the lock it is about to meet.
            cwd=str(pathlib.Path(__file__).resolve().parents[2]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        original = self.store._commit_write
        observed = []

        def competing_writer():
            go.write_text("go")
            output, errors = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, errors)
            observed.append(json.loads(output))
            return original()

        self.addCleanup(self._stop, process, go)
        deadline = time.monotonic() + 10
        while not ready.exists():
            self.assertIsNone(process.poll(),
                              "the peer process failed before its save attempt")
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)

        self.store._commit_write = competing_writer
        failure = None
        try:
            self.apply(shown, request_id="cross-process-1")
        except (ledger_apply.ApplyPlanError, real_review.RealReviewError) as error:
            failure = error
        self.assertEqual(len(observed), 1, "the peer never got to try its save")

        # The peer's save is refused, because the apply holds the database's lock
        # from before the plan is read to after the commit. Not queued, not merged.
        self.assertFalse(observed[0]["changed"], observed[0])
        self.assertEqual(observed[0]["code"],
                         real_review.CODE_DECISIONS_BUSY)
        self.assertIsNone(failure)
        self.assertEqual(len(self.board_rows()), 1)
        # And the stored decision is the one the plan was built from.
        self.assertEqual(self.service().state()["choices"][ref],
                         "APPROVE:" + shown["transactions"][0]["source_event_key"])
        self.assertTrue(shown["transactions"][0]["ref"])

    def _stop(self, process, go):
        if process.poll() is None:
            go.write_text("go")
            try:
                process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)

    def test_the_same_save_succeeds_once_the_apply_has_finished(self):
        """The lock is released, so the peer's save is not permanently lost.

        A fence that never opened again would be a denial of service wearing a
        safety feature's name. The decision the apply refused is still the right
        one to make afterwards, and it is still made against the right version.
        """
        self.activate([self.fact("CROSS-PROCESS-2")])
        self.approve({"CROSS-PROCESS-2"})
        shown = self.plan()
        self.apply(shown, request_id="cross-process-2")
        service = self.service()
        ref = service.model()["rows"][0]["ref"]
        saved = service.save_decisions(
            [{"ref": ref, "value": "REJECT"}], shown["choices_revision"],
            shown["binding"])
        self.assertEqual(saved["revision"], shown["choices_revision"] + 1)
        # And the ledger is untouched by that later decision.
        self.assertEqual(len(self.board_rows()), 1)


if __name__ == "__main__":
    unittest.main()