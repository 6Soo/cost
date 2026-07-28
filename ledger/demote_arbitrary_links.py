# -*- coding: utf-8 -*-
"""원장 임의배정에서 유래한 링크를 검증 링크파일에서 강등 분리한다 (2026-07-29).

## 배경

의사결정권자 진술: 원장(수기장부)의 예약번호는 `결제일·결제금액·가맹점명(앞부분)` 이 같으면
**N:M 임의배정**으로 기입됐다. 따라서 "수기장부가 예약번호를 확정한다"를 근거로 만든 링크는
그 임의성을 상속한다.

## 적대적 검증 결론 (fable · gpt-5.6-sol 양측)

수렴:
- 재무 영향 **0**. 그룹 내 금액이 정의상 동일하고 탭 교차가 0이므로, 어떤 순열에서도
  탭 합계·계정 합계·총액이 불변이다(관측이 아니라 수학적 귀결).
- 카드이벤트·금액은 되돌리지 않는다.
- 오염된 것은 예약번호 문자열이 아니라 **행↔예약의 결합**이다.
- 실질 위험: ① 환불/취소를 임의 예약번호로 원거래에 연결 ② 예약 유래 기간·호텔·투숙객의 행별 표시.
- 향후 대사 불일치 시 신뢰 순서: 카드이벤트 · OTA 원자료 > 원장 짝짓기.

분기와 그 해소:
- fable: `verified` 파일에 두고 출처 강등 표식만.
- sol: 표식을 **인식해 차단할 수 있으면** 표식으로 충분, **없으면 별도 HOLD 파일로 이동**.
- 실측: 저장소 어디에도 `verified` 필드를 해석하는 코드가 없다. `patch_v14.py` 는
  `booking_id` 를 읽어 `예약{번호}` 를 note 에 붙여 산출물로 내보낸다.
  → sol 의 조건절에 따라 **이동**이 정답이다(fails closed).

## 하는 일

`ota_event_links_verified.json` 에서 임의배정 그룹 유래 링크를 빼내
`ota_group_assignments.json` 으로 옮긴다. 그룹의 후보 예약번호 집합을 함께 보존해
Agoda 대사 시 그룹 안에서 재짝짓기만 하면 되도록 한다.

카드이벤트·금액·여행탭은 **전혀 건드리지 않는다.**
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "ledger" / "data"
LINKS = DATA / "ota_event_links_verified.json"
GROUPS_OUT = DATA / "ota_group_assignments.json"
MANUAL = DATA / "manual_v4.csv"
CLASSIFIED = DATA / "classified_v14.csv"

ITEM_PREFIX = 14


def norm_item(value: str) -> str:
    return re.sub(r"[^A-Z가-힣0-9]", "", (value or "").upper())[:ITEM_PREFIX]


def arbitrary_groups() -> dict[str, dict]:
    """예약번호 → 소속 임의배정 그룹 정보."""
    with MANUAL.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        book = (row.get("book") or "").strip()
        if not book:
            continue
        try:
            amount = round(float(row["amount"] or 0))
        except (ValueError, TypeError):
            continue
        buckets[(row["date"], amount, norm_item(row["item"]))].append(row)

    by_booking: dict[str, dict] = {}
    for (date, amount, item), members in buckets.items():
        books = sorted({m["book"].strip() for m in members})
        if len(books) < 2:
            continue                       # 예약번호 단일 = 임의배정 아님
        tabs = sorted({m["tab"] for m in members})
        descs = sorted({(m.get("desc") or "") for m in members})
        info = {
            "group_id": f"{date}_{amount}_{item}",
            "group_bookings": books,
            "group_tabs": tabs,
            "group_descs": descs,
            "amount_krw": amount,
            "payment_date": date,
            "row_level_desc_differs": len(descs) > 1,
        }
        for b in books:
            by_booking[b] = info
    return by_booking


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 강등·저장(기본 dry-run)")
    args = ap.parse_args()

    links = json.loads(LINKS.read_text(encoding="utf-8"))
    groups = arbitrary_groups()
    existing_assign = json.loads(GROUPS_OUT.read_text(encoding="utf-8")) if GROUPS_OUT.exists() else {}
    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        rows = {r["uid"]: r for r in csv.DictReader(fh)}

    demote: dict[str, dict] = {}
    for uid, link in links.items():
        book = str(link.get("booking_id") or link.get("order_id") or "").strip()
        info = groups.get(book)
        if not info:
            continue
        row = rows.get(uid, {})
        demote[uid] = {
            "provisional_booking_id": book,
            "group_id": info["group_id"],
            "group_bookings": info["group_bookings"],
            "amount_krw": info["amount_krw"],
            "payment_date": info["payment_date"],
            "allocation_target": row.get("bucket", ""),
            "match_basis": "ledger_arbitrary_group",
            "verified": False,
            "row_level_desc_differs": info["row_level_desc_differs"],
            "demoted_on": "2026-07-29",
            "rationale": (
                "원장이 (결제일·금액·가맹점명) 동일 그룹에 예약번호를 임의배정했다는 "
                "의사결정권자 진술에 따라 강등. 그룹 귀속과 금액은 유효하며 탭·계정·총액 영향 0. "
                "개별 행↔예약 결합만 미확정이다."
            ),
            "usage_restriction": (
                "이 예약번호로 환불·취소를 원거래에 자동 연결하지 말 것. "
                "예약 유래 기간·호텔·투숙객을 행 단위 확정값으로 표시하지 말 것. "
                "세무 증빙의 핵심 근거로 제시하지 말 것."
            ),
            "correction_procedure": (
                "Agoda 원자료 확인 시 group_bookings 안에서 재짝짓기하고, 교집합이 유일해지면 "
                "merge_verified_ota_links.py 가드로 검증 링크에 승격한다. 불일치는 데이터 오류가 "
                "아니라 임의배정의 예정된 표면화이므로 원장을 방어하지 않는다."
            ),
            "prior_link": {k: v for k, v in link.items()},
        }

    kept = {u: v for u, v in links.items() if u not in demote}
    risky = {u: v for u, v in demote.items() if v["row_level_desc_differs"]}

    summary = {
        "links_before": len(links),
        "demoted": len(demote),
        "links_after": len(kept),
        "group_assignments_before": len(existing_assign),
        "group_assignments_after": len(existing_assign) + len(demote),
        "demoted_groups": len({v["group_id"] for v in demote.values()}),
        "demoted_amount_krw": sum(
            round(float(rows.get(u, {}).get("krw") or 0)) for u in demote
        ),
        "row_level_desc_differs": len(risky),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for gid in sorted({v["group_id"] for v in demote.values()}):
        members = sorted(u for u, v in demote.items() if v["group_id"] == gid)
        print(f"  {gid}")
        for uid in members:
            print(f"     {uid:16} → {demote[uid]['provisional_booking_id']}")

    if not args.apply:
        print("\ndry-run (--apply 로 실제 강등)")
        return 0

    if len(kept) + len(demote) != len(links):
        print("중단: 건수 검산 불일치")
        return 2

    for path, payload, label in (
        (LINKS, kept, "검증 링크"),
        (GROUPS_OUT, {**existing_assign, **demote}, "그룹배정"),
    ):
        backup = path.with_suffix(".json.bak")
        if path.exists():
            backup.write_bytes(path.read_bytes())
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        readback = json.loads(path.read_text(encoding="utf-8"))
        if len(readback) != len(payload):
            print(f"중단: {label} read-back {len(readback)} != {len(payload)}")
            return 3
        print(f"{label}: {len(readback)}건 저장·read-back OK → {path.relative_to(ROOT)}")

    print(f"\n강등 완료: 검증 링크 {len(links)} → {len(kept)} · 그룹배정 {len(existing_assign) + len(demote)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
