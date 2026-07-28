#!/usr/bin/env python3
"""로컬 체크포인트에서 검증된 OTA 링크를 중앙 링크파일에 가드 병합한다.

인계서(docs/CODEX_LINUX_MIGRATION_HANDOFF_2026-07-27.md) §4-1 / §12-7 이행 스크립트.

가드 원칙:
- 기존 링크는 절대 overwrite 하지 않는다(overwrite 발생 시 즉시 중단).
- 병합 대상 uid는 classified_v14.csv에 실재하는 카드 이벤트여야 한다.
- 병합 전후 링크 수 = 기존 + 신규 (검산 불일치 시 중단).
- 저장은 임시파일 → 원자적 rename → read-back → SHA-256 기록 순서.

사용법:
    python merge_verified_ota_links.py            # 검사만(dry-run)
    python merge_verified_ota_links.py --apply    # 실제 병합
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINKS = ROOT / "ledger" / "data" / "ota_event_links_verified.json"
CLASSIFIED = ROOT / "ledger" / "data" / "classified_v14.csv"
MERGEABLE = ROOT / "outputs" / "codex_reconcile_20260727" / "01_mergeable_verified_links.json"

# 링크 레코드에 보존할 필드(체크포인트 메타는 provenance로 남긴다)
LINK_FIELDS = ("booking_id", "category", "period", "hotel", "guest", "card4",
               "foreign_amount", "currency")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_card_uids() -> set[str]:
    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        return {row["uid"] for row in csv.DictReader(fh) if row.get("uid")}


def build_record(item: dict) -> dict:
    rec = {k: item[k] for k in LINK_FIELDS if item.get(k) not in (None, "")}
    rec["verification_source"] = item.get("source", "local_checkpoint")
    if item.get("source_message_id"):
        rec["source_message_id"] = item["source_message_id"]
    if item.get("verification"):
        rec["verification"] = item["verification"]
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 병합·저장한다")
    args = ap.parse_args()

    existing = json.loads(LINKS.read_text(encoding="utf-8"))
    incoming = json.loads(MERGEABLE.read_text(encoding="utf-8"))
    card_uids = load_card_uids()

    before = len(existing)
    print(f"중앙 링크파일: {LINKS.relative_to(ROOT)}  기존 {before}건  "
          f"sha256={sha256(LINKS)[:16]}")
    print(f"병합 후보:     {MERGEABLE.relative_to(ROOT)}  {len(incoming)}건")

    overwrite, missing, staged = [], [], {}
    for item in incoming:
        uid = item["uid"]
        if uid in existing:
            overwrite.append(uid)
        if uid not in card_uids:
            missing.append(uid)
        staged[uid] = build_record(item)

    for uid in sorted(staged):
        flag = "OVERWRITE" if uid in overwrite else ("NO-CARD-EVENT" if uid in missing else "NEW")
        print(f"  [{flag:>13}] {uid}  booking={staged[uid].get('booking_id','-')}  "
              f"period={staged[uid].get('period','') or '(공란)'}")

    if overwrite:
        print(f"\n중단: 기존 링크 overwrite {len(overwrite)}건 감지 — {overwrite}", file=sys.stderr)
        return 2
    if missing:
        print(f"\n중단: classified_v14에 없는 uid {len(missing)}건 — {missing}", file=sys.stderr)
        return 3
    if len(staged) != len(incoming):
        print(f"\n중단: 후보 내 uid 중복 ({len(incoming)} → {len(staged)})", file=sys.stderr)
        return 4

    expected = before + len(staged)
    print(f"\n가드 통과: overwrite 0건 · 미존재 uid 0건 · 기대 링크수 {before} + {len(staged)} = {expected}")

    if not args.apply:
        print("dry-run (--apply 로 실제 병합)")
        return 0

    backup = LINKS.with_suffix(".json.bak")
    backup.write_bytes(LINKS.read_bytes())
    print(f"백업: {backup.relative_to(ROOT)}  sha256={sha256(backup)[:16]}")

    merged = dict(existing)
    merged.update(staged)
    if len(merged) != expected:
        print(f"중단: 병합 후 {len(merged)}건 ≠ 기대 {expected}건", file=sys.stderr)
        return 5

    tmp = LINKS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, LINKS)

    readback = json.loads(LINKS.read_text(encoding="utf-8"))
    if len(readback) != expected:
        print(f"중단: read-back {len(readback)}건 ≠ 기대 {expected}건", file=sys.stderr)
        return 6
    for uid, rec in staged.items():
        if readback.get(uid) != rec:
            print(f"중단: read-back 불일치 uid={uid}", file=sys.stderr)
            return 7
    for uid, rec in existing.items():
        if readback.get(uid) != rec:
            print(f"중단: 기존 링크 변형 감지 uid={uid}", file=sys.stderr)
            return 8

    print(f"병합 완료: {before} → {len(readback)}건 (신규 {len(staged)})")
    print(f"read-back 검증 OK · 기존 {before}건 무변형 확인")
    print(f"새 sha256={sha256(LINKS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
