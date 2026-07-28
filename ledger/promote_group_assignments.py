# -*- coding: utf-8 -*-
"""그룹배정 → 검증 링크 승격 게이트 (2026-07-29).

## 의사결정권자 판단 (2026-07-29)

> "동일 날짜, 동일 금액, 동일 객실, 심지어 M에 해당하는 예약번호들이 **모두 투숙 날짜가 같다면**
> 임의배정을 해도 되는 것 아닌가?"

이 논리는 타당하다. 그룹 내 예약들이 **산출물에 나타나는 모든 속성**에서 서로 구별되지 않으면,
어느 짝을 짓든 산출물이 참 배정과 완전히 동일하다. 임의배정은 '구분 없는 구분'이 된다.

## 다만 조건은 **검증돼야** 한다

의사결정권자 선택(2026-07-29): **② Agoda 상세 확인 후 승격.**
지금 가진 것은 메일 본문에서 MMDD 토큰을 긁은 `travelDates` 휴리스틱뿐이며,
실제 체크인/아웃은 PDF 첨부(체크인 바우처·전자영수증) 안에 있어 확보되지 않았다.
휴리스틱 일치는 "조건과 모순되지 않는다"일 뿐 증명이 아니므로, 그것으로 승격하지 않는다.

## 승격 조건 (전부 만족해야 함)

  ① 그룹의 모든 후보 예약번호에 대해 **검증 등급 숙박일**이 존재한다
     (`stay_periods_verified.json` 의 `evidence_grade` 가 `verified_*` 로 시작).
  ② 그 숙박일이 그룹 내에서 **전원 동일**하다.
  ③ 그룹 내 **행별 구별정보가 갈리지 않는다**(`row_level_desc_differs` 가 False).
     — 승객명이 행마다 다른 항공 건(마이트립 몽골 사례)은 조건 ①②를 만족해도 승격 금지.
  ④ 후보 예약번호가 이미 다른 uid 에 확정 배정돼 있지 않다.

조건 ③이 필요한 이유: ①②는 '숙박일'만 같음을 보장한다. 투숙객처럼 예약별로 다른 속성이
산출물에 인쇄되면 임의배정이 그 열을 틀리게 만든다.

## 숙박일 증거 파일 형식 (`ledger/data/stay_periods_verified.json`)

```json
{
  "1400823535393192": {
    "check_in": "2026-04-08", "check_out": "2026-04-09",
    "evidence_grade": "verified_agoda_site",   // 또는 verified_pdf_voucher / verified_ota_mail_body
    "source": "Agoda 예약상세 화면 캡처 2026-07-30",
    "guest": "..."                              // 있으면 기재(없어도 됨)
  }
}
```
`evidence_grade` 가 `heuristic_*` 이면 승격에 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "ledger" / "data"
ASSIGN = DATA / "ota_group_assignments.json"
LINKS = DATA / "ota_event_links_verified.json"
STAY = DATA / "stay_periods_verified.json"

VERIFIED_PREFIX = "verified_"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 승격(기본 dry-run)")
    args = ap.parse_args()

    if not ASSIGN.exists():
        print("그룹배정 파일 없음 — 할 일 없음")
        return 0
    assign = json.loads(ASSIGN.read_text(encoding="utf-8"))
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    stay = json.loads(STAY.read_text(encoding="utf-8")) if STAY.exists() else {}

    linked_bookings = {
        str(v.get("booking_id") or v.get("order_id") or "").strip()
        for v in links.values()
    }
    linked_bookings.discard("")

    by_group: dict[str, list[str]] = {}
    for uid, info in assign.items():
        by_group.setdefault(info["group_id"], []).append(uid)

    promote: dict[str, dict] = {}
    blocked: list[dict] = []
    for gid, uids in sorted(by_group.items()):
        info0 = assign[uids[0]]
        books = info0.get("group_bookings") or []
        reasons = []

        missing = [b for b in books if b not in stay]
        if missing:
            reasons.append(f"숙박일 증거 없음 {len(missing)}/{len(books)}건")
        weak = [
            b for b in books
            if b in stay and not str(stay[b].get("evidence_grade", "")).startswith(VERIFIED_PREFIX)
        ]
        if weak:
            reasons.append(f"증거 등급 미달(휴리스틱) {len(weak)}건")
        if not missing and not weak:
            periods = {(stay[b].get("check_in"), stay[b].get("check_out")) for b in books}
            if len(periods) != 1:
                reasons.append(f"그룹 내 숙박일 상이 {sorted(periods)}")
            guests = {str(stay[b].get("guest") or "") for b in books}
            if len([g for g in guests if g]) > 1:
                reasons.append(f"그룹 내 투숙객 상이 {sorted(guests)}")
        if any(assign[u].get("row_level_desc_differs") for u in uids):
            reasons.append("행별 구별정보 상이 — 임의배정 금지 구간")
        taken = [b for b in books if b in linked_bookings]
        if taken:
            reasons.append(f"이미 확정 배정된 예약번호 {taken}")

        if reasons:
            blocked.append({"group_id": gid, "card_events": len(uids),
                            "bookings": len(books), "reasons": reasons})
            continue

        period = next(iter({(stay[b].get("check_in"), stay[b].get("check_out")) for b in books}))
        for uid in uids:
            info = assign[uid]
            promote[uid] = {
                "booking_id": info["provisional_booking_id"],
                "category": "숙박",
                "period": "%s_%s" % (period[0][5:7] + period[0][8:10],
                                     period[1][5:7] + period[1][8:10]) if all(period) else "",
                "verification": (
                    "그룹 내 후보 예약 전원의 숙박일이 검증등급 증거로 동일함이 확인돼 승격. "
                    "임의배정이 산출물에 영향을 주지 않는 조건(의사결정권자 판단 2026-07-29) 충족. "
                    "그룹 %s · 후보 %s" % (info["group_id"], "+".join(info["group_bookings"]))
                ),
                "verification_source": "stay_periods_verified.json",
                "promoted_from": "ota_group_assignments.json",
            }

    summary = {
        "groups_total": len(by_group),
        "groups_promotable": len({assign[u]["group_id"] for u in promote}),
        "card_events_promotable": len(promote),
        "groups_blocked": len(blocked),
        "stay_evidence_records": len(stay),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for b in blocked:
        print(f"  차단 {b['group_id']} (카드 {b['card_events']}건): {'; '.join(b['reasons'])}")
    for uid in sorted(promote):
        print(f"  승격 {uid:16} → {promote[uid]['booking_id']} 기간={promote[uid]['period'] or '(공란)'}")

    if not promote:
        print("\n승격 가능한 그룹 없음 — Agoda 상세 확보 후 다시 실행하라.")
        return 0
    if not args.apply:
        print("\ndry-run (--apply 로 승격)")
        return 0

    overwrite = [u for u in promote if u in links]
    if overwrite:
        print(f"중단: 기존 링크 overwrite {overwrite}")
        return 2
    for path, payload in ((LINKS, {**links, **promote}),
                          (ASSIGN, {u: v for u, v in assign.items() if u not in promote})):
        path.with_suffix(".json.bak").write_bytes(path.read_bytes())
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        if len(json.loads(path.read_text(encoding="utf-8"))) != len(payload):
            print(f"중단: read-back 불일치 {path.name}")
            return 3
    print(f"\n승격 완료: 검증 링크 {len(links)} → {len(links) + len(promote)} · "
          f"그룹배정 {len(assign)} → {len(assign) - len(promote)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
