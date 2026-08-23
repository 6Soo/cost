from __future__ import annotations

import unittest
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from ledger import cardindex, ingest
from ledger.domain.han_normalizer import (HAN_NORMALIZER_CONTRACT_SHA256,
    HanRawAmounts, normalize_han_components, parse_han_amounts,
    validate_han_header)


class HanNormalizerTests(unittest.TestCase):
    @staticmethod
    def _han_rows(approval="100", purchase="120", cancel="0"):
        header = ["h"] * 19
        header[4] = "승인번호"
        header[5] = "승인금액"; header[6] = "승인취소금액"; header[14] = "매입금액"
        row = [""] * 19
        row[0] = "1"; row[1] = "2026-07-01"; row[3] = "0000-0000-0000-1234"
        row[4] = "123"; row[5] = approval; row[6] = cancel; row[7] = "SYNTHETIC"
        row[11] = "국내"; row[14] = purchase; row[16] = "2026-07-02"; row[17] = "정상"
        return [[""] * 19] * 5 + [header, row]

    def test_header_name_binding_reorder_missing_duplicate_and_wrong_name(self):
        columns = validate_han_header(["매입금액", "기타", "승인취소금액", "승인금액"])
        self.assertEqual((columns.approval_amount, columns.cancel_amount, columns.purchase_amount), (3, 2, 0))
        self.assertEqual(parse_han_amounts(["1,200원", "x", "0", "1,000"], columns),
                         HanRawAmounts(1000, 1200, 0))
        for header, code in ((["승인금액", "승인취소금액"], "missing:purchase_amount"),
            (["승인금액", "승인금액", "승인취소금액", "매입금액"], "duplicate:approval_amount"),
            (["승인 금", "승인취소금액", "매입금액"], "missing:approval_amount")):
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, code):
                validate_han_header(header)

    def test_numeric_domains(self):
        columns = validate_han_header(["승인금액", "승인취소금액", "매입금액"])
        self.assertEqual(parse_han_amounts(["1,000 원", "", None], columns), HanRawAmounts(1000, 0, 0))
        self.assertEqual(parse_han_amounts(["100", "-20", "999"], columns), HanRawAmounts(100, 999, -20))
        for value, code in ((True, "bool"), ("NaN", "nonfinite"), ("Infinity", "nonfinite"),
                            ("1.5", "fractional"), (Decimal("2.1"), "fractional"), (-1, "negative"), ("x", "invalid")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, code):
                parse_han_amounts([value, 0, 0], columns)
        self.assertRegex(HAN_NORMALIZER_CONTRACT_SHA256, r"^[0-9a-f]{64}$")

    def test_normal_purchase_fallback_and_zero(self):
        purchase = normalize_han_components(HanRawAmounts(100, 120, 0))
        self.assertEqual((purchase[0].role, purchase[0].signed_amount_krw, purchase[0].selection_reason),
                         ("single", 120, "purchase_amount_nonzero"))
        fallback = normalize_han_components(HanRawAmounts(100, 0, 0))
        self.assertEqual((fallback[0].signed_amount_krw, fallback[0].selection_reason),
                         (100, "approval_amount_fallback"))
        zero = normalize_han_components(HanRawAmounts(0, 0, 0))
        self.assertEqual((zero[0].signed_amount_krw, zero[0].selection_reason),
                         (0, "approval_amount_fallback"))
        for invalid in (HanRawAmounts(0, 120, 0), HanRawAmounts(0, 0, 20), HanRawAmounts(0, 0, -20)):
            with self.assertRaisesRegex(ValueError, "han_approval_amount_required"):
                normalize_han_components(invalid)

    def test_split_preserves_approval_and_negative_cancel_not_purchase(self):
        components = normalize_han_components(HanRawAmounts(100, 999, 20))
        self.assertEqual([(x.role, x.signed_amount_krw, x.transaction_type, x.selection_reason) for x in components], [
            ("approval", 100, "purchase", "split_approval_amount"),
            ("cancellation", -20, "cancellation", "split_cancel_amount")])
        for invalid in (HanRawAmounts(-1, 0, 0), HanRawAmounts(True, 0, 0)):
            with self.assertRaisesRegex(ValueError, "domain"): normalize_han_components(invalid)

    def test_ingest_and_cardindex_share_normal_and_split_semantics(self):
        for approval, purchase, cancel, expected in (
            ("100", "120", "0", [("정상", 120)]),
            ("100", "0", "0", [("정상", 100)]),
            ("100", "999", "20", [("정상", 100), ("취소", -20)]),
        ):
            rows = self._han_rows(approval, purchase, cancel)
            legacy = ingest.norm(rows, "하나승인", "2026-08-01")
            self.assertEqual([(x["취소여부"], x["원화금액"]) for x in legacy], expected)
            def load(name, **_kwargs):
                if name == "G": return rows
                if name == "H": return rows[:6]
                return []
            with patch.object(cardindex, "load", side_effect=load):
                cards = cardindex.build_cards(ledger_dir=Path("/synthetic"))
            self.assertEqual(len(cards), 1)
            self.assertEqual([(x[0], x[1]) for x in cards[0]["han_components"]],
                [("single", expected[0][1])] if not int(cancel) else [("approval", 100), ("cancellation", -20)])

    def test_existing_master_hana_incremental_merge_fails_before_write(self):
        rows = self._han_rows()
        with tempfile.TemporaryDirectory() as dirname:
            master = Path(dirname) / "master.csv"
            master.write_text("거래키,카드사\nold,하나\n", "utf-8-sig")
            before = master.read_bytes()
            with patch.object(ingest, "MASTER", str(master)), patch.object(ingest, "load", return_value=rows), \
                 self.assertRaisesRegex(SystemExit, "han_full_rebuild_required"):
                ingest.main(["synthetic.xlsx"])
            self.assertEqual(master.read_bytes(), before)

    def test_both_consumers_reject_purchase_only_and_cancel_only_rows(self):
        for approval, purchase, cancel, code in (("0", "120", "0", "han_approval_amount_required"),
                                                  ("0", "0", "-20", "han_approval_amount_required"),
                                                  ("0", "0", "0", "han_zero_amount_transaction")):
            rows=self._han_rows(approval,purchase,cancel)
            with self.subTest(consumer="ingest",purchase=purchase,cancel=cancel), \
                 self.assertRaisesRegex(ValueError,code):
                ingest.norm(rows,"하나승인","2026-08-01")
            def load(name,**_kwargs):
                if name=="G": return rows
                if name=="H": return rows[:6]
                return []
            with self.subTest(consumer="cardindex",purchase=purchase,cancel=cancel), \
                 patch.object(cardindex,"load",side_effect=load), \
                 self.assertRaisesRegex(ValueError,code):
                cardindex.build_cards(ledger_dir=Path("/synthetic"))

        footer=self._han_rows("0","0","0");footer[-1][3]="";footer[-1][4]=""
        self.assertEqual(ingest.norm(footer,"하나승인","2026-08-01"),[])

    def test_blank_or_no_marker_cannot_hide_identified_zero_row(self):
        for marker in ("", "NO"):
            rows=self._han_rows("0","0","0");rows[-1][0]=marker
            with self.subTest(consumer="ingest",marker=marker), \
                 self.assertRaisesRegex(ValueError,"han_zero_amount_transaction"):
                ingest.norm(rows,"하나승인","2026-08-01")
            def load(name,**_kwargs):
                if name=="G": return rows
                if name=="H": return rows[:6]
                return []
            with self.subTest(consumer="cardindex",marker=marker), \
                 patch.object(cardindex,"load",side_effect=load), \
                 self.assertRaisesRegex(ValueError,"han_zero_amount_transaction"):
                cardindex.build_cards(ledger_dir=Path("/synthetic"))

    def test_none_footer_and_one_sided_identities_are_normalized_strictly(self):
        footer=self._han_rows("0","0","0");footer[-1][3]=None;footer[-1][4]=None
        self.assertEqual(ingest.norm(footer,"하나승인","2026-08-01"),[])
        def footer_load(name,**_kwargs):
            if name=="G": return footer
            if name=="H": return footer[:6]
            return []
        with patch.object(cardindex,"load",side_effect=footer_load):
            self.assertEqual(cardindex.build_cards(ledger_dir=Path("/synthetic")),[])

        for missing in (3,4):
            zero=self._han_rows("0","0","0");zero[-1][missing]=None
            with self.subTest(kind="zero",missing=missing),self.assertRaisesRegex(ValueError,"han_zero_amount_transaction"):
                ingest.norm(zero,"하나승인","2026-08-01")
            valid=self._han_rows("100","120","0");valid[-1][missing]=None
            legacy=ingest.norm(valid,"하나승인","2026-08-01")
            self.assertEqual(len(legacy),1)
            def valid_load(name,**_kwargs):
                if name=="G": return valid
                if name=="H": return valid[:6]
                return []
            with patch.object(cardindex,"load",side_effect=valid_load):
                cards=cardindex.build_cards(ledger_dir=Path("/synthetic"))
            self.assertEqual((len(cards),cards[0]["krw"]),(1,120))


if __name__ == "__main__": unittest.main()
