from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from ledger.domain.review_verifier import verify_review_claims


class ReviewVerifierTest(unittest.TestCase):
    @staticmethod
    def _csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_manual_and_canonical_sources_contradict_misc_absence_claim(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            fields = ["uid", "src", "use_date", "merchant", "krw", "note", "appr"]
            self._csv(
                classified,
                fields,
                [
                    {
                        "uid": "HAN-1",
                        "src": "HAN",
                        "use_date": "2026-05-20",
                        "merchant": "HERTZ INTERNATIONAL",
                        "krw": 543947,
                        "note": "수기 매칭",
                        "appr": "00305072",
                    },
                    {
                        "uid": "MISC-1",
                        "src": "HAN",
                        "use_date": "2026-05-20",
                        "merchant": "HERTZ INTERNATIONAL",
                        "krw": 543947,
                        "note": "수기 미기재 실카드결제",
                        "appr": "00305072",
                    },
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [
                    {
                        "tab": "5월_유럽",
                        "row": 47,
                        "date": "2026.05.20",
                        "item": "HERTZ INTERNATIONAL",
                        "desc": "렌터카",
                        "card": "하나",
                        "amount": 543947,
                        "book": "",
                    }
                ],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertFalse(result["passed"])
            self.assertEqual(
                result["counts"]["manual_absence_claim_contradicted"], 1
            )
            self.assertEqual(
                result["counts"]["unsupported_canonical_card_event"], 1
            )

    def test_mytrip_subject_with_empty_core_fields_is_field_loss(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "mail-1",
                                "provider": "mytrip",
                                "subject": "1122-610-807 (1) 주문에 대한 추가 서비스 영수증",
                                "bookingRefs": [],
                                "amounts": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["ota_field_loss"], 1)

    def test_transactional_sky_and_booking_index_cannot_drop_core_fields(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "sky-1",
                                "provider": "skyticket",
                                "subject": "항공권 신청 완료",
                                "bookingRefs": [],
                                "amounts": [],
                                "travelDates": [],
                            },
                            {
                                "messageId": "booking-1",
                                "provider": "booking",
                                "subject": "예약 결제 완료 영수증",
                                "bookingRefs": ["5502442589"],
                                "amounts": [],
                                "travelDates": [],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["ota_field_loss"], 2)
            self.assertEqual(result["counts"]["ota_booking_ref_loss"], 1)
            self.assertEqual(result["counts"]["ota_amount_loss"], 2)
            self.assertEqual(result["counts"]["ota_travel_date_loss"], 2)

    def test_forwarded_and_attachment_close_reasons_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "forwarded-open",
                                "provider": "mytrip",
                                "subject": "FW: 4/23 항공권 예약정보",
                                "bookingRefs": ["1115-449-361"],
                                "amounts": [44053],
                                "travelDates": ["0423"],
                            },
                            {
                                "messageId": "forwarded-done",
                                "provider": "mytrip",
                                "subject": "FW: 4/13 항공권 예약정보",
                                "bookingRefs": ["1117-227-848"],
                                "amounts": [1185597],
                                "travelDates": ["0413", "0416"],
                                "forwardedContentExtracted": True,
                                "extractionSources": ["forwarded_message"],
                            },
                            {
                                "messageId": "attachment-open",
                                "provider": "skyticket",
                                "subject": "구입 완료 안내",
                                "bookingRefs": ["32071283"],
                                "amounts": [791012],
                                "travelDates": ["1127", "1130"],
                                "attachmentState": "present_unread",
                                "attachmentCount": 1,
                                "attachmentReceiptDetected": True,
                            },
                            {
                                "messageId": "attachment-done",
                                "provider": "skyticket",
                                "subject": "구입 완료 안내",
                                "bookingRefs": ["32071219"],
                                "amounts": [2373036],
                                "travelDates": ["1127", "1130"],
                                "attachmentState": "text_extracted",
                                "attachmentCount": 1,
                                "attachmentReceiptDetected": True,
                                "extractionSources": ["attachment_text"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["forwarded_unextracted"], 1)
            self.assertEqual(result["counts"]["attachment_required"], 1)
            self.assertNotIn("ota_field_loss", result["counts"])
            open_ids = {
                item["uid"]: item["type"] for item in result["assertions"]
            }
            self.assertEqual(
                open_ids,
                {
                    "forwarded-open": "forwarded_unextracted",
                    "attachment-open": "attachment_required",
                },
            )

    def test_nontransactional_attachment_and_fw_name_do_not_overcapture(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "hotel-guide",
                                "provider": "trip",
                                "subject": "호텔 이용 안내",
                                "bookingRefs": [],
                                "amounts": [],
                                "travelDates": [],
                                "attachmentState": "present_unread",
                                "attachmentCount": 1,
                                "attachmentReceiptDetected": False,
                            },
                            {
                                "messageId": "fw-hotel-name",
                                "provider": "booking",
                                "subject": "FW Hotel 예약이 확정되었습니다",
                                "bookingRefs": ["5502442589"],
                                "amounts": [],
                                "travelDates": ["0520", "0522"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertTrue(result["passed"])
            self.assertNotIn("attachment_required", result["counts"])
            self.assertNotIn("forwarded_unextracted", result["counts"])

    def test_booking_confirmation_without_price_is_not_amount_field_loss(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "booking-confirmation",
                                "provider": "booking",
                                "subject": "감사합니다! 호텔 예약이 확정되었습니다",
                                "bookingRefs": ["5502442589"],
                                "amounts": [],
                                "travelDates": ["2026-05-20", "2026-05-22"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertNotIn("ota_field_loss", result["counts"])

    def test_booking_promotion_is_not_travel_date_field_loss(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "booking-promotion",
                                "provider": "booking",
                                "subject": "예약 고객을 위한 여행 혜택과 추천 소식",
                                "bookingRefs": ["5502442589"],
                                "amounts": [],
                                "travelDates": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertNotIn("ota_field_loss", result["counts"])

    def test_booking_payment_only_mail_is_not_travel_date_field_loss(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "19e3bb0f2e298fad",
                                "provider": "booking",
                                "subject": "결제가 완료되었습니다",
                                "bookingRefs": ["5502442589"],
                                "amounts": [272320],
                                "travelDates": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertNotIn("ota_field_loss", result["counts"])

    def test_booking_confirmation_missing_reference_is_not_reported_as_missing_amount(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "booking-reference-loss",
                                "provider": "booking",
                                "subject": "감사합니다! 호텔 예약이 확정되었습니다",
                                "bookingRefs": [],
                                "amounts": [],
                                "travelDates": ["2026-05-20", "2026-05-22"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            assertion = next(
                item for item in result["assertions"]
                if item["type"] == "ota_field_loss"
            )
            self.assertEqual(assertion["source_evidence"]["missing"], ["bookingRefs"])

    def test_exact_manual_event_with_wrong_year_is_review_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "HAN-3004",
                        "src": "HAN",
                        "use_date": "2026-04-07",
                        "merchant": "TRIP ARS NICE",
                        "krw": 1224285,
                        "note": "",
                        "appr": "17101710",
                    }
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [
                    {
                        "tab": "1127_야쿠시마",
                        "row": 42,
                        "date": "24.04.07",
                        "item": "Trip ARS/NICE",
                        "desc": "숙박",
                        "card": "하나",
                        "amount": 1224285,
                        "book": "",
                    }
                ],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["manual_year_conflict"], 1)

    def test_manual_two_digit_year_normalizes_to_the_same_card_date(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "HAN-3004",
                        "src": "HAN",
                        "use_date": "2026-04-07",
                        "merchant": "TRIP ARS NICE",
                        "krw": 1224285,
                        "note": "",
                        "appr": "17101710",
                    }
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [
                    {
                        "tab": "1127_야쿠시마",
                        "row": 42,
                        "date": "26.04.07",
                        "item": "Trip ARS/NICE",
                        "desc": "숙박",
                        "card": "하나",
                        "amount": 1224285,
                        "book": "",
                    }
                ],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertNotIn("manual_year_conflict", result["counts"])

    def test_opposite_sign_same_day_of_year_is_not_year_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "HAN-REFUND",
                        "src": "HAN",
                        "use_date": "2026-04-07",
                        "merchant": "TRIP ARS NICE",
                        "krw": -1224285,
                        "note": "",
                        "appr": "17101710",
                    }
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [
                    {
                        "tab": "1127_야쿠시마",
                        "row": 42,
                        "date": "24.04.07",
                        "item": "Trip ARS/NICE",
                        "desc": "숙박",
                        "card": "하나",
                        "amount": 1224285,
                        "book": "",
                    }
                ],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertNotIn("manual_year_conflict", result["counts"])

    def test_manual_month_only_date_is_reviewed_without_guessing_the_day(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "KBD-0887",
                        "src": "KBD",
                        "use_date": "2026-05-06",
                        "merchant": "아시아나항공",
                        "krw": 149800,
                        "note": "",
                        "appr": "30101426",
                    }
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [
                    {
                        "tab": "0722_가루이자와",
                        "row": 36,
                        "date": "26.05",
                        "item": "아시아나",
                        "desc": "항공",
                        "card": "국민",
                        "amount": 149800,
                        "book": "",
                    }
                ],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["manual_date_incomplete"], 1)
            self.assertNotIn("manual_year_conflict", result["counts"])

    def test_gmail_confirmed_and_mail_absent_cannot_coexist(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "KBD-1096",
                        "src": "KBD",
                        "use_date": "2026-06-20",
                        "merchant": "11번가",
                        "krw": 177590,
                        "note": "Gmail확정:11번가 오픈마켓, 메일없음",
                        "appr": "30059180",
                    }
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["self_contradictory_mail_claim"], 1)

    def test_same_approval_with_different_amount_is_not_called_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "HAN-3245",
                        "src": "HAN",
                        "use_date": "2026-05-22",
                        "merchant": "HERTZ INTERNATIONAL",
                        "krw": 422687,
                        "note": "",
                        "appr": "00305072",
                    },
                    {
                        "uid": "MISC-0011",
                        "src": "HAN",
                        "use_date": "2026-05-20",
                        "merchant": "HERTZ INTERNATIONAL",
                        "krw": 543947,
                        "note": "",
                        "appr": "00305072",
                    },
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertNotIn("unsupported_canonical_card_event", result["counts"])

    def test_unique_naverpay_receipt_cannot_be_reused_by_different_merchants(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "KBD-0995",
                        "merchant": "아성다이소",
                        "krw": "7000",
                        "note": "naverpay/아성다이소/예약202606058620964164",
                    },
                    {
                        "uid": "KBD-0998",
                        "merchant": "다빈치",
                        "krw": "7000",
                        "note": "naverpay/아성다이소/예약202606058620964164",
                    },
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(
                result["counts"]["reused_unique_receipt_identifier"],
                1,
            )

    def test_same_approval_event_cannot_be_projected_twice(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": uid,
                        "src": "KBD",
                        "use_date": "2026-06-11",
                        "merchant": "트립닷컴",
                        "krw": "99120",
                        "note": "",
                        "appr": "30103285",
                    }
                    for uid in ("KBD-1025", "TRIP-9999")
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(
                result["counts"]["duplicate_card_event_projection"],
                1,
            )


    def test_prior_period_claim_is_rejected_when_original_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            fields = [
                "uid",
                "src",
                "use_date",
                "merchant",
                "krw",
                "note",
                "appr",
                "orig_appr",
            ]
            self._csv(
                classified,
                fields,
                [
                    {
                        "uid": "KBD-0917",
                        "src": "KBD",
                        "use_date": "2026-05-22",
                        "merchant": "KLOOK",
                        "krw": "53200",
                        "note": "",
                        "appr": "30102078",
                        "orig_appr": "",
                    },
                    {
                        "uid": "KBD-0916",
                        "src": "KBD",
                        "use_date": "2026-05-22",
                        "merchant": "KLOOK",
                        "krw": "-53200",
                        "note": "\uC804\uAE30(Q1) \uC608\uC57D \uCDE8\uC18C",
                        "appr": "42019265",
                        "orig_appr": "30102078",
                    },
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(
                result["counts"]["outside_window_claim_contradicted"],
                1,
            )

    def test_generic_pg_and_travel_detail_are_one_event_representation(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [
                    {
                        "tab": "0620_\uBB18\uCF54",
                        "row": "89",
                        "date": "2026-06-14",
                        "item": "Trip_\uB2C8\uAC00\uD0C0",
                        "desc": "\uD56D\uACF5 \uC774\uC815\uD76C",
                        "card": "\uAD6D\uBBFC",
                        "amount": "499200",
                        "book": "1400827583267273",
                    },
                    {
                        "tab": "2\uBD84\uAE30_\uAE30\uD0C0\uBE44\uC6A9",
                        "row": "120",
                        "date": "2026-06-14",
                        "item": "TossPay_\uC77C\uBC18",
                        "desc": "",
                        "card": "\uAD6D\uBBFC",
                        "amount": "499200",
                        "book": "",
                    },
                ],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(
                result["counts"]["duplicate_manual_event_representation"],
                1,
            )

    def test_booking_confirmation_with_empty_reference_is_field_loss(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [],
            )
            ota.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "messageId": "booking-mail",
                                "provider": "booking",
                                "subject": (
                                    "\uAC10\uC0AC\uD569\uB2C8\uB2E4! "
                                    "\uD638\uD154 \uC608\uC57D\uC744 "
                                    "\uD655\uC815\uD558\uC600\uC2B5\uB2C8\uB2E4"
                                ),
                                "bookingRefs": [],
                                "amounts": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["ota_field_loss"], 1)

    def test_manual_positive_refund_row_conflicts_with_negative_card_event(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            classified = root / "classified.csv"
            manual = root / "manual.csv"
            ota = root / "ota.json"
            self._csv(
                classified,
                ["uid", "src", "use_date", "merchant", "krw", "note", "appr"],
                [
                    {
                        "uid": "KBO-2833",
                        "src": "KBO",
                        "use_date": "2026-05-11",
                        "merchant": "LOONG AGE",
                        "krw": "-421101",
                        "note": "",
                        "appr": "",
                    }
                ],
            )
            self._csv(
                manual,
                ["tab", "row", "date", "item", "desc", "card", "amount", "book"],
                [
                    {
                        "tab": "5\uC6D4_\uC720\uB7FD",
                        "row": "72",
                        "date": "2026-05-11",
                        "item": "LOONG AGE",
                        "desc": "",
                        "card": "\uAD6D\uBBFC",
                        "amount": "421101",
                        "book": "",
                    }
                ],
            )
            ota.write_text('{"records":[]}', encoding="utf-8")
            result = verify_review_claims(classified, manual, ota)
            self.assertEqual(result["counts"]["manual_sign_conflict"], 1)


if __name__ == "__main__":
    unittest.main()
