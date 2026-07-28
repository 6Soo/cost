# -*- coding: utf-8 -*-
"""수기장부 임의배정 그룹의 안전조건 상설 검사 (2026-07-29).

배경(의사결정권자 진술): 원장(수기장부)의 예약번호는 일부 구간에서 **임의배정**됐다.
규칙 — `결제일·결제금액·가맹점명(숙박명 일부 포함)`이 같으면 N:M으로 임의배정.

이 임의배정이 **무해한 이유는 단 하나**다: 그런 그룹이 전부 **단일 여행탭 내부**에 있어
어떤 순열을 적용해도 여행탭 합계·계정 합계·총액이 변하지 않기 때문이다.

따라서 그 전제가 깨지는 순간(임의배정 그룹이 여행탭을 넘나드는 순간) 임의배정은
**장부 귀속을 흔드는 실제 오류**가 된다. 원장이 갱신될 때마다 이 조건을 상설로 검사한다.

실측 기준선(2026-07-29): 임의배정 그룹 20개 · 수기행 47건 · 금액합 16,718,569원 · **탭 교차 0개**.
"""
from __future__ import annotations

import csv
import re
import unittest
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
MANUAL = DATA / "manual_v4.csv"

# 의사결정권자가 실제로 적용한 그룹 키의 가맹점명 부분.
# 원장 표기가 'AGODA.COM APA HOTEL' / '아고다_Hakuba Hotel' 처럼 흔들리므로
# 영숫자·한글만 남기고 앞부분만 취해 비교한다.
ITEM_PREFIX = 14


def norm_item(value: str) -> str:
    return re.sub(r"[^A-Z가-힣0-9]", "", (value or "").upper())[:ITEM_PREFIX]


def load_groups() -> dict[tuple, list[dict]]:
    with MANUAL.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        book = (row.get("book") or "").strip()
        if not book:
            continue
        try:
            amount = round(float(row["amount"] or 0))
        except (ValueError, TypeError):
            continue
        groups[(row["date"], amount, norm_item(row["item"]))].append(row)
    # 서로 다른 예약번호가 2개 이상인 묶음만이 '임의배정' 대상이다.
    return {
        key: rows_
        for key, rows_ in groups.items()
        if len({r["book"].strip() for r in rows_}) > 1
    }


class LedgerArbitraryGroupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.groups = load_groups()

    def test_no_arbitrary_group_crosses_trip_tabs(self):
        """★핵심 안전조건: 임의배정 그룹은 단일 여행탭 안에 머물러야 한다.

        여기 걸리면 임의배정이 여행탭 간 금액 귀속을 바꿀 수 있다는 뜻이므로,
        해당 그룹은 임의배정 대상에서 빼고 개별 증거로 확정해야 한다.
        """
        crossing = {
            key: sorted({r["tab"] for r in rows})
            for key, rows in self.groups.items()
            if len({r["tab"] for r in rows}) > 1
        }
        self.assertEqual(
            crossing, {},
            "임의배정 그룹이 여행탭을 교차한다 — 장부 귀속이 임의배정에 좌우된다:\n"
            + "\n".join(f"  {k} → {v}" for k, v in crossing.items()),
        )

    def test_amounts_identical_within_group(self):
        """그룹 정의상 금액은 동일해야 한다(집계 배정-불변의 근거)."""
        for key, rows in self.groups.items():
            amounts = {round(float(r["amount"] or 0)) for r in rows}
            self.assertEqual(len(amounts), 1, f"{key}: 그룹 내 금액 불일치 {amounts}")

    def _groups_with_distinguishing_desc(self) -> dict[tuple, list[str]]:
        """행마다 `desc` 가 다른 임의배정 그룹.

        `desc` 는 기간(`숙박_0426_0428`)일 수도 있고 **탑승객 이름**일 수도 있다.
        실측(2026-07-29): `26.03.14 / 793,669 / 마이트립` 그룹은 desc 가 `김명심` / `이미숙` 으로
        승객별 PNR(`Z36AK7` / `Z37EZO`)이 1:1로 붙는 항공 건이다.
        이런 그룹에서 임의배정을 하면 **PNR에 엉뚱한 승객이 붙는다** — 참조 문자열 하나가 아니라
        산출물의 탑승객 표기가 틀린다(인계서 §9.3: 항공권은 내용 열에 탑승객명 병기).
        """
        return {
            key: sorted({(r.get("desc") or "") for r in rows})
            for key, rows in self.groups.items()
            if len({(r.get("desc") or "") for r in rows}) > 1
        }

    def test_distinguishing_desc_groups_are_not_linked(self):
        """★행별 구별정보가 갈리는 그룹은 임의배정해서는 안 되며, 링크로 확정돼서도 안 된다.

        임의배정이 무해한 근거는 "그룹 내 행들이 서로 구별되지 않는다"는 것이다.
        desc 가 승객명처럼 행마다 다르면 그 근거가 무너지므로, 해당 예약번호가 중앙
        링크파일에 들어가 있으면 안 된다. 들어가려면 개별 증거로 확정해야 한다.
        """
        import json

        risky = self._groups_with_distinguishing_desc()
        if not risky:
            return
        links_path = DATA / "ota_event_links_verified.json"
        links = json.loads(links_path.read_text(encoding="utf-8")) if links_path.exists() else {}
        linked_books = {
            str(v.get("booking_id") or v.get("order_id") or "").strip()
            for v in links.values()
        }
        leaked = []
        for key, _ in risky.items():
            for row in self.groups[key]:
                book = row["book"].strip()
                if book in linked_books:
                    leaked.append((key, book, row.get("desc")))
        self.assertEqual(
            leaked, [],
            "행별 구별정보(desc)가 갈리는 임의배정 그룹의 예약번호가 중앙 링크에 확정돼 있다. "
            "임의배정 무해성 근거가 성립하지 않는 구간이므로 개별 증거 없이 링크하면 안 된다:\n"
            + "\n".join(f"  {k} 예약={b} desc={d}" for k, b, d in leaked),
        )

    def test_distinguishing_desc_groups_are_reported(self):
        """구별정보가 갈리는 그룹은 조용히 넘어가지 않는다(현황 고정).

        2026-07-29 실측: 1개 그룹(마이트립 항공, 승객명 상이).
        늘어나면 사람이 봐야 한다 — 그때마다 임의배정 가능 여부를 개별 판단한다.
        """
        risky = self._groups_with_distinguishing_desc()
        self.assertLessEqual(
            len(risky), 1,
            f"행별 구별정보가 갈리는 임의배정 그룹이 {len(risky)}개다(기준선 1). "
            f"각 그룹의 임의배정 가능 여부를 개별 판단하라:\n"
            + "\n".join(f"  {k} → {v}" for k, v in risky.items()),
        )

    def test_booking_number_not_reused_across_groups(self):
        """한 예약번호가 서로 다른 임의배정 그룹에 걸치면 순열 범위가 불명확해진다."""
        owner: dict[str, tuple] = {}
        clashes = []
        for key, rows in self.groups.items():
            for r in rows:
                book = r["book"].strip()
                if book in owner and owner[book] != key:
                    clashes.append((book, owner[book], key))
                owner[book] = key
        self.assertEqual(clashes, [], f"예약번호가 복수 임의배정 그룹에 등장한다: {clashes[:5]}")

    def test_baseline_scale_is_tracked(self):
        """규모가 크게 움직이면 사람이 다시 본다(고정 기대값 아님, 상한 가드)."""
        rows_in_groups = sum(len(v) for v in self.groups.values())
        self.assertLessEqual(
            len(self.groups), 40,
            f"임의배정 그룹이 {len(self.groups)}개로 늘었다(기준선 20). 원장 변경 내역을 확인하라.",
        )
        self.assertLessEqual(
            rows_in_groups, 90,
            f"임의배정 수기행이 {rows_in_groups}건으로 늘었다(기준선 47). 원장 변경 내역을 확인하라.",
        )


if __name__ == "__main__":
    unittest.main()
