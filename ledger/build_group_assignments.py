# -*- coding: utf-8 -*-
"""다객실 예약 그룹의 카드↔예약 잠정 배정 기록기 (2026-07-29).

대표 판단: "동일 날짜·동일 금액이면 임의배정을 해도 되지 않나."
fable(A안) ↔ gpt-5.6-sol(C안) 1차·반박 2라운드 검토를 거친 종합 결론:

  · 대표 판단의 **결론은 유지**한다. 단 **근거는 교정**한다 —
    정당화 근거는 "동일 객실"(현 자료로 미확인)이 아니라
    **"그룹 내 금액이 완전히 동일해 어떤 짝을 지어도 집계가 1원도 변하지 않는다"** 이다.
  · 실측: 그룹 내 수기행 기간 표기는 전원 동일하거나 전원 부재 → 임의배정이 기간 열을
    틀리게 만들 수 없다. 오류 공간은 **예약번호 문자열 하나뿐**이며 그마저 확정 집합 내부의
    치환(permutation)이다.
  · 그러나 잠정 배정을 `ota_event_links_verified.json` 의 `booking_id` 로 저장하면 안 된다.
    실측 확인: `patch_v14.py` 가 `booking_id` 를 읽어 `예약{번호}` 를 note 에 붙여 산출물로
    내보내며, **저장소 어디에도 `verified` 필드를 해석하는 코드가 없다.**
    따라서 검증 링크와 같은 자리에 두면 임의배정이 확정처럼 인쇄된다.

→ 별도 파일 `ledger/data/ota_group_assignments.json` 에 기록한다.
  기존 소비자는 이 파일을 읽지 않으므로 **안전하게 실패**한다(fails closed).
  그룹 관계(C안이 지키려던 것)와 잠정 1:1(A안이 지키려던 것)을 한 레코드에 모두 담는다.

배정 규칙(고정, 버전명 `group_zip_v1`):
  카드 uid 오름차순 ↔ 예약번호를 **숫자로 해석해** 오름차순으로 zip.
  (문자열 정렬은 자릿수가 다른 번호에서 순서가 뒤집힌다. 숫자 변환 불가 시 문자열 정렬로 폴백.)

정정 절차: Agoda 상세 확인 후 `group_bookings` 안에서 `provisional_booking_id` 를 치환하고,
확정되면 `merge_verified_ota_links.py` 가드를 통해 중앙 링크파일로 승격한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "ledger" / "data"
CLASSIFIED = DATA / "classified_v14.csv"
LINKS = DATA / "ota_event_links_verified.json"
OUT = DATA / "ota_group_assignments.json"

RULE = "group_zip_v1"


def booking_sort_key(book: str):
    return (0, int(book)) if book.isdigit() else (1, book)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collisions", required=True,
                    help="build_manual_ledger_links.py 가 만든 02_collisions.json")
    ap.add_argument("--assigned-by", default="대표 승인 2026-07-29")
    ap.add_argument("--apply", action="store_true", help="실제로 파일에 기록(기본 dry-run)")
    args = ap.parse_args()

    collisions = json.loads(Path(args.collisions).read_text(encoding="utf-8"))
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        rows = {r["uid"]: r for r in csv.DictReader(fh)}

    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    assignments: dict[str, dict] = {}
    skipped = []
    for group in collisions:
        cards = group["card_events"]
        mans = group["manual_rows"]
        books = sorted({m["book"] for m in mans if m.get("book")}, key=booking_sort_key)
        tab, amount = group["tab"], group["amount_krw"]

        # 대상 조건: 닫힌군(카드수=예약수) · 예약번호가 2개 이상 · 전원 미확정
        if len(cards) != len(mans):
            skipped.append({"tab": tab, "amount_krw": amount, "reason": "열린군(카드수≠예약수)"})
            continue
        if len(books) < 2:
            skipped.append({"tab": tab, "amount_krw": amount, "reason": "예약번호 단일 — 짝 문제 없음"})
            continue
        if len(books) != len(cards):
            skipped.append({"tab": tab, "amount_krw": amount, "reason": "고유 예약번호 수≠카드 수"})
            continue
        linked = [c["uid"] for c in cards if c["uid"] in links]
        if linked:
            skipped.append({"tab": tab, "amount_krw": amount,
                            "reason": f"이미 확정된 uid 포함 {linked}"})
            continue

        dates = sorted({c["use_date"] for c in cards})
        periods = sorted({(m.get("desc") or "") for m in mans})
        group_id = f"{tab}_{amount}_{dates[0].replace('-','')}"
        uids = sorted(c["uid"] for c in cards)
        for uid, book in zip(uids, books):
            assignments[uid] = {
                "provisional_booking_id": book,
                "group_id": group_id,
                "group_bookings": books,
                "group_uids": uids,
                "match_basis": RULE,
                "verified": False,
                "amount_krw": amount,
                "allocation_target": tab,
                "assigned_by": args.assigned_by,
                "rationale": (
                    "그룹 귀속은 확정(카드 %d건 ↔ 예약 %d건, 동일 탭·결제일·금액·카드사). "
                    "개별 1:1은 미검증이며 그룹 내 금액이 동일해 집계는 배정 불변. "
                    "기간 표기도 그룹 내 동일(%s)이라 임의배정이 기간을 틀리게 하지 않는다."
                    % (len(cards), len(books), "/".join(periods) or "없음")
                ),
                "correction_procedure": (
                    "Agoda 상세 확인 후 group_bookings 안에서 provisional_booking_id 를 치환하고, "
                    "확정되면 merge_verified_ota_links.py 가드로 중앙 링크파일에 승격한다."
                ),
            }

    groups = {a["group_id"] for a in assignments.values()}
    summary = {
        "rule": RULE,
        "groups": len(groups),
        "assigned_card_events": len(assignments),
        "amount_total_krw": sum(a["amount_krw"] for a in assignments.values()),
        "skipped_groups": len(skipped),
        "target_file": str(OUT.relative_to(ROOT)),
        "note": "이 파일은 검증 링크가 아니다. 기존 소비자는 읽지 않으므로 산출물에 인쇄되지 않는다.",
    }

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for g in sorted(groups):
        members = [(u, a["provisional_booking_id"]) for u, a in assignments.items() if a["group_id"] == g]
        print(f"  {g}")
        for uid, book in sorted(members):
            print(f"     {uid:12} → {book}")
    if skipped:
        print(" 제외:")
        for s in skipped:
            print(f"     {s['tab']:16} {s['amount_krw']:>10,} — {s['reason']}")

    if not args.apply:
        print("\ndry-run (--apply 로 기록)")
        return 0

    merged = dict(existing)
    overwrite = [u for u in assignments if u in existing and existing[u] != assignments[u]]
    if overwrite:
        print(f"중단: 기존 배정 overwrite {len(overwrite)}건 — {overwrite[:5]}")
        return 2
    merged.update(assignments)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, OUT)
    readback = json.loads(OUT.read_text(encoding="utf-8"))
    if len(readback) != len(merged):
        print(f"중단: read-back {len(readback)} != {len(merged)}")
        return 3
    print(f"\n기록 완료: {len(existing)} → {len(readback)}건 ({OUT.relative_to(ROOT)}) · read-back OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
