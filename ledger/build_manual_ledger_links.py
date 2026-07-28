# -*- coding: utf-8 -*-
"""수기장부(원장) 기준 OTA 링크 후보 생성기 — 유일 교집합만 (2026-07-29).

배경: Gmail 원문 대조로도 근거를 못 찾은 미확정 OTA 카드이벤트 338건 중 **222건이 수기장부에
동액 행을 갖고 있고 그중 152건은 예약번호까지 보유**한다(실측). 수기장부는 원장(P15)이며,
사용자가 이미 같은 기준을 승인한 선례가 있다:
  · APA 가나자와 4건 — 수기 예약번호별 1:1 기재로 확정(2026-07-29).
  · KBO-2645 / KBO-2646 / CORP-2007 — 수기 예약번호로 HOLD 해소(2026-07-29).

따라서 메일 근거가 없어도 **교집합이 유일하면** 링크로 인정한다(불변규칙 3 충족).

유일성 판정(모두 만족해야 auto):
  ① 같은 (여행탭, 금액)의 **미확정 카드이벤트가 정확히 1건**.
  ② 같은 (여행탭, 금액)의 **예약번호 보유 수기행이 정확히 1건**.
  ③ 그 예약번호가 다른 uid 에 이미 배정돼 있지 않다.
하나라도 어긋나면 collisions 로 분리해 사람이 본다(예: 네자메호텔 ¥15,510 동일가 4실).

중앙 링크파일은 **읽기만** 한다. 병합은 merge_verified_ota_links.py 의 가드를 통과해야 한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "ledger" / "data"
CLASSIFIED = DATA / "classified_v14.csv"
LINKS = DATA / "ota_event_links_verified.json"
MANUAL = DATA / "manual_v4.csv"

# build_v13_trip.py 와 동일한 탭명 정규화
TABMAP = {"0630_오제_A": "0630_오제", "0704_야마가타": "0704_아키타"}


def normtab(tab: str) -> str:
    return TABMAP.get(tab, tab)


def provider_of(text: str) -> str | None:
    t = text.upper()
    if any(k in t for k in ("마이트립", "MYTRIP", "고투게이트")):
        return "mytrip"
    if any(k in t for k in ("트립닷컴", "TRIP.COM", "CTRIP")):
        return "trip"
    if "AGODA" in t or "아고다" in t:
        return "agoda"
    if "BOOKING.COM" in t:
        return "booking"
    if any(k in t for k in ("트래블로버", "TRAVELROVER")):
        return "travelrover"
    return None


PERIOD_RE = re.compile(r"(\d{4})_(\d{4})|숙박_(\d{4})_(\d{4})")


def period_of(manual_row: dict) -> str:
    m = PERIOD_RE.search(manual_row.get("desc") or "")
    if not m:
        return ""
    groups = [g for g in m.groups() if g]
    return "_".join(groups[:2]) if len(groups) >= 2 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-stamp", default="20260729")
    args = ap.parse_args()

    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    with MANUAL.open(encoding="utf-8-sig", newline="") as fh:
        manual = list(csv.DictReader(fh))

    linked_bookings = {
        str(v.get("booking_id") or v.get("order_id") or "").strip()
        for v in links.values()
    }
    linked_bookings.discard("")

    unlinked = [
        r for r in rows
        if provider_of(f"{r.get('merchant','')} {r.get('note','')}") and r["uid"] not in links
    ]

    # (탭, 금액) → 미확정 카드이벤트
    card_group: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in unlinked:
        card_group[(normtab(r["bucket"]), abs(round(float(r.get("krw") or 0))))].append(r)

    # (탭, 금액) → 예약번호 보유 수기행
    man_group: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for m in manual:
        book = (m.get("book") or "").strip()
        if not book:
            continue
        try:
            amt = round(float(m["amount"] or 0))
        except ValueError:
            continue
        man_group[(normtab(m["tab"]), abs(amt))].append(m)

    auto, collisions = [], []
    for key, cards in sorted(card_group.items()):
        mans = man_group.get(key, [])
        if not mans:
            continue
        tab, amt = key
        reasons = []
        if len(cards) != 1:
            reasons.append(f"동일(탭,금액) 미확정 카드이벤트 {len(cards)}건")
        if len(mans) != 1:
            reasons.append(f"동일(탭,금액) 예약보유 수기행 {len(mans)}건")
        already = [m for m in mans if (m.get("book") or "").strip() in linked_bookings]
        if already:
            reasons.append("예약번호가 이미 다른 uid에 배정됨: "
                           + ",".join(sorted({(m.get('book') or '').strip() for m in already})))

        detail = {
            "tab": tab,
            "amount_krw": amt,
            "card_events": [
                {"uid": c["uid"], "use_date": c["use_date"], "merchant": c["merchant"][:40],
                 "card4": c["card4"], "note": (c.get("note") or "")[:120]}
                for c in cards
            ],
            "manual_rows": [
                {"row": m["row"], "date": m["date"], "item": m["item"][:40],
                 "card": m["card"], "book": (m.get("book") or "").strip(),
                 "desc": m.get("desc", "")}
                for m in mans
            ],
        }
        if reasons:
            collisions.append({**detail, "reasons": reasons})
            continue

        card, man = cards[0], mans[0]
        auto.append({
            "uid": card["uid"],
            "provider": provider_of(f"{card.get('merchant','')} {card.get('note','')}"),
            "booking_id": (man.get("book") or "").strip(),
            "category": "숙박",
            "period": period_of(man),
            "hotel": man["item"][:60],
            "verification": (
                "수기장부 마스터 %s r%s(%s, %s, %s) 예약번호. "
                "동일(탭,금액) 미확정 카드이벤트 1건·예약보유 수기행 1건으로 교집합 유일, "
                "해당 예약번호 미배정 확인" % (tab, man["row"], man["item"][:30], f"{amt:,}", man["card"])
            ),
            "source": "ledger/build_manual_ledger_links.py",
        })

    out = ROOT / "outputs" / f"ota_manual_links_{args.out_stamp}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "01_mergeable_verified_links.json").write_text(
        json.dumps(auto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "02_collisions.json").write_text(
        json.dumps(collisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dup = len(auto) - len({a["uid"] for a in auto})
    summary = {
        "existing_links": len(links),
        "unlinked_ota_rows": len(unlinked),
        "auto_unique_links": len(auto),
        "collision_groups": len(collisions),
        "collision_card_events": sum(len(c["card_events"]) for c in collisions),
        "duplicate_uid_in_auto": dup,
    }
    assert dup == 0, summary
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
