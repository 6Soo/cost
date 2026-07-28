# -*- coding: utf-8 -*-
"""외부 모델(codex/agy)이 낸 OTA 링크 판정을 원천 데이터와 교차검증한다 (2026-07-29).

저추론 모델의 판정은 그대로 신뢰하지 않는다. 아래를 전부 통과한 `link` 판정만
가드 병합기 입력으로 내보낸다.

  ① uid 가 classified_v14 에 실재하고 아직 미확정이다.
  ② booking_id 가 **모델이 본 입력 안에** 실재한다
     (candidates[].booking_refs_in_body / mail_booking_refs / manual_ledger_matches[].book).
     입력에 없는 번호는 환각으로 간주해 기각한다.
  ③ 그 booking_id 가 이미 다른 uid 에 배정돼 있지 않다.
  ④ 같은 실행 안에서 두 uid 가 같은 booking_id 를 주장하지 않는다(상호 충돌).
  ⑤ period 는 공란이거나 MMDD / MMDD_MMDD 형식이다. 그 외에는 공란으로 강등한다.

기각 사유는 전부 파일로 남긴다. 통계만 요약하지 않는다.
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

PERIOD_RE = re.compile(r"^\d{4}(?:_\d{4})?$")


def allowed_bookings(item: dict) -> set[str]:
    allowed: set[str] = set()
    for m in item.get("manual_ledger_matches", []):
        book = str(m.get("book") or "").strip()
        if book:
            allowed.add(book)
    for c in item.get("candidates", []):
        for key in ("booking_refs_in_body", "mail_booking_refs"):
            for ref in c.get(key) or []:
                ref = str(ref).strip()
                if ref:
                    allowed.add(ref)
    return allowed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards-dir", required=True)
    ap.add_argument("--verdicts-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        rows = {r["uid"]: r for r in csv.DictReader(fh)}
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    linked_bookings = {
        str(v.get("booking_id") or v.get("order_id") or "").strip(): uid
        for uid, v in links.items()
    }
    linked_bookings.pop("", None)

    shard_items: dict[str, dict] = {}
    for path in sorted(Path(args.shards_dir).glob("*.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            shard_items[item["uid"]] = item

    verdicts: list[dict] = []
    for path in sorted(Path(args.verdicts_dir).glob("*.json")):
        if path.name == "run_summary.json":
            continue
        engine = path.stem.split(".")[-1]
        for v in json.loads(path.read_text(encoding="utf-8")):
            verdicts.append({**v, "_engine": engine, "_file": path.name})

    accepted, rejected, held = [], [], []
    claimed: dict[str, list[str]] = defaultdict(list)

    for v in verdicts:
        uid = v.get("uid")
        if v.get("decision") != "link":
            held.append(v)
            continue
        item = shard_items.get(uid)
        booking = str(v.get("booking_id") or "").strip()

        def reject(reason: str):
            rejected.append({**v, "reject_reason": reason})

        if item is None:
            reject("샤드 입력에 없는 uid")
            continue
        if uid not in rows:
            reject("classified_v14 에 없는 uid")
            continue
        if uid in links:
            reject("이미 확정된 uid")
            continue
        if not booking:
            reject("link 인데 booking_id 공란")
            continue
        allowed = allowed_bookings(item)
        if booking not in allowed:
            reject(f"입력에 없는 예약번호(환각 의심). 허용집합 {sorted(allowed)[:6]}")
            continue
        if booking in linked_bookings:
            reject(f"예약번호가 이미 {linked_bookings[booking]} 에 배정됨")
            continue
        period = str(v.get("period") or "").strip()
        if period and not PERIOD_RE.match(period):
            v = {**v, "period": "", "_period_downgraded": period}
            period = ""
        claimed[booking].append(uid)
        accepted.append({
            "uid": uid,
            "provider": item.get("provider"),
            "booking_id": booking,
            "category": "숙박",
            "period": period,
            "verification": "외부모델 판정(%s, confidence=%s) + 원천 교차검증 통과: %s"
                            % (v.get("_engine"), v.get("confidence"), str(v.get("reason"))[:120]),
            "source": f"{args.verdicts_dir}/{v.get('_file')}",
        })

    # ④ 같은 실행 내 상호 충돌 제거
    conflicts = {b: uids for b, uids in claimed.items() if len(set(uids)) > 1}
    if conflicts:
        kept = []
        for a in accepted:
            if a["booking_id"] in conflicts:
                rejected.append({**a, "reject_reason":
                                 f"같은 예약번호를 {sorted(set(conflicts[a['booking_id']]))} 가 동시 주장"})
            else:
                kept.append(a)
        accepted = kept

    # uid 중복(교차검증 모드에서 두 엔진이 같은 uid 판정) 제거 — 동일 booking 이면 1건만 남긴다
    seen: dict[str, dict] = {}
    dedup_rejected = []
    for a in accepted:
        prev = seen.get(a["uid"])
        if prev is None:
            seen[a["uid"]] = a
        elif prev["booking_id"] == a["booking_id"]:
            continue
        else:
            dedup_rejected.append({**a, "reject_reason":
                                   f"동일 uid 에 서로 다른 예약번호 판정({prev['booking_id']} vs {a['booking_id']})"})
            seen.pop(a["uid"], None)
    rejected.extend(dedup_rejected)
    accepted = list(seen.values())

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "01_mergeable_verified_links.json").write_text(
        json.dumps(accepted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "02_rejected.json").write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "03_model_holds.json").write_text(
        json.dumps(held, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "verdicts_total": len(verdicts),
        "model_link": sum(1 for v in verdicts if v.get("decision") == "link"),
        "model_hold": len(held),
        "accepted_after_crosscheck": len(accepted),
        "rejected": len(rejected),
        "reject_breakdown": dict(sorted(
            ((r["reject_reason"].split(".")[0].split("(")[0].strip(), 1) for r in rejected),
            key=lambda kv: kv[0])) if rejected else {},
    }
    breakdown: dict[str, int] = defaultdict(int)
    for r in rejected:
        breakdown[r["reject_reason"].split(".")[0].split("(")[0].strip()] += 1
    summary["reject_breakdown"] = dict(sorted(breakdown.items(), key=lambda kv: -kv[1]))
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
