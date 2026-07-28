# -*- coding: utf-8 -*-
"""APA 가나자와 합산청구 분해 회귀테스트 (2026-07-29).

배경: 수기장부(원장)에는 `0424_알펜루트` 탭에 `AGODA.COM APA HOTEL` 571,962원이
서로 다른 Agoda 예약번호 4건으로 기재돼 있는데, 카드는 `KBO-2755` 한 건(¥241,920 =
2,287,848원)으로 합산청구됐다.

과거 두 가지 회귀가 모두 실측됐다:
  · 1,705행 기준본 — 분해 4행 + 합산청구 1행을 모두 계상해 2,287,848원 **이중계상**.
  · 1,835행 기준본 — 합산청구 1행 + 분해 1행만 남아 571,962원 **초과계상**,
    예약번호 3건(1721758806·1721757952·1721761805)은 장부에서 표현 자체가 소멸.

확정 처리(사용자 2026-07-29 + fable·gpt-5.6-sol 반박검증 절차):
  분해 4행을 모두 보존하고, 합산청구 카드이벤트는 삭제하지 않되 금액 0으로 연결처리한다.
  귀속 탭은 수기장부 기재와 동일한 `0424_알펜루트`로 통일한다.
"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
CLASSIFIED = DATA / "classified_v14.csv"
MANUAL_V4 = DATA / "manual_v4.csv"

COMPONENT_BOOKINGS = ("1721756989", "1721758806", "1721757952", "1721761805")
COMPONENT_KRW = 571_962
COMBINED_UID = "KBO-2755"
COMBINED_KRW = 2_287_848
TAB = "0424_알펜루트"


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def krw(row: dict) -> int:
    return round(float(row["krw"] or 0))


class ApaCombinedBillingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load(CLASSIFIED)
        cls.by_uid = {r["uid"]: r for r in cls.rows}

    def _component_rows(self) -> list[dict]:
        return [
            r for r in self.rows
            if any(f"예약{b}" in (r["note"] or "") for b in COMPONENT_BOOKINGS)
            and "APA" in (r["merchant"] or "").upper()
        ]

    def test_manual_master_still_has_four_bookings(self):
        """원천 근거: 수기 마스터에 571,962원 4행이 서로 다른 예약번호로 존재한다."""
        hits = [
            r for r in load(MANUAL_V4)
            if r["tab"] == TAB and "APA HOTEL" in (r["item"] or "").upper()
            and round(float(r["amount"] or 0)) == COMPONENT_KRW
        ]
        self.assertEqual(len(hits), 4, "수기 마스터의 APA 571,962원 4행이 유지돼야 한다")
        self.assertEqual(
            sorted(r["book"].strip() for r in hits), sorted(COMPONENT_BOOKINGS)
        )

    def test_every_booking_has_exactly_one_row(self):
        """예약번호 4건이 각각 정확히 1행으로 표현된다(소멸·중복 모두 금지)."""
        for booking in COMPONENT_BOOKINGS:
            hits = [
                r for r in self.rows
                if f"예약{booking}" in (r["note"] or "")
                and "APA" in (r["merchant"] or "").upper()
            ]
            self.assertEqual(len(hits), 1, f"예약{booking} 표현이 1행이 아니다: {[h['uid'] for h in hits]}")
            self.assertEqual(krw(hits[0]), COMPONENT_KRW, f"예약{booking} 금액 불일치")

    def test_combined_card_event_is_linked_not_deleted(self):
        """합산청구 카드이벤트는 남되 금액 0이고, 원 청구액이 보존된다."""
        row = self.by_uid.get(COMBINED_UID)
        self.assertIsNotNone(row, f"{COMBINED_UID} 카드이벤트를 삭제하면 안 된다")
        self.assertEqual(krw(row), 0, "합산청구행이 0이 아니면 이중계상이다")
        self.assertIn("합산청구_연결", row["status"])
        self.assertIn(str(COMBINED_KRW), row["extra"], "원 카드 청구액이 extra에 보존돼야 한다")

    def test_no_double_and_no_over_counting(self):
        """그룹 계상액은 정확히 카드 합산청구액과 같다."""
        total = sum(krw(r) for r in self._component_rows()) + krw(self.by_uid[COMBINED_UID])
        self.assertEqual(
            total, COMBINED_KRW,
            f"APA 그룹 계상 {total:,} != 카드 합산청구 {COMBINED_KRW:,}",
        )

    def test_tab_attribution_unified(self):
        """분해행·합산청구행 모두 판정된 귀속 탭에 있다."""
        self.assertEqual(self.by_uid[COMBINED_UID]["bucket"], TAB)
        for row in self._component_rows():
            self.assertEqual(row["bucket"], TAB, f"{row['uid']} 귀속 탭 불일치")


if __name__ == "__main__":
    unittest.main()
