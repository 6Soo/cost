# -*- coding: utf-8 -*-
"""미확정 OTA 카드이벤트 ↔ Gmail 원문 후보 생성기 (2026-07-29).

기존 `reconcile_ota_index.py` 는 메일 **메타데이터**(subject·bookingRefs·amounts·travelDates)만
보고 점수를 매긴다. 원문 색인(`ota_mail_index.raw.json`)에는 각 메일의 `rawText` 전문이 있는데
이 신호를 전혀 쓰지 않아 자동확정이 0으로 나온다(2026-07-29 실측).

이 스크립트는 **rawText 본문**을 근거로 후보를 만든다. 판정은 하지 않고 후보와 근거만 만든다.
중앙 링크파일은 **읽기만** 하며 절대 쓰지 않는다.

출력 (outputs/ota_candidates_<stamp>/):
  auto_candidates.json      — 근거가 유일·강한 건(가드 병합기 입력 형식)
  ambiguous_shards/NN.json  — 판단 필요 건을 에이전트 분배용 샤드로 분할
  no_candidate.json         — 원문에서 근거를 못 찾은 건
  summary.json              — 검산 수치

사용법:
    python build_ota_candidates.py --out-stamp 20260729 [--shard-size 12]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "ledger" / "data"
RAW_INDEX = DATA / "ota_mail_index.raw.json"
INDEX = RAW_INDEX if RAW_INDEX.exists() else DATA / "ota_mail_index.json"
CLASSIFIED = DATA / "classified_v14.csv"
LINKS = DATA / "ota_event_links_verified.json"
MANUAL = DATA / "manual_v4.csv"


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


def amount_forms(value: int) -> list[str]:
    """본문에 등장할 수 있는 금액 표기 변형."""
    v = abs(int(value))
    if v == 0:
        return []
    return list(dict.fromkeys([str(v), f"{v:,}"]))


def parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def mail_date(record: dict):
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(record.get("sentAt", "")).date()
    except (TypeError, ValueError, OverflowError):
        return None


BOOKING_RE = re.compile(r"\b\d{8,19}\b|\b\d{3,6}(?:-\d{3}){2}\b")


def evidence(row: dict, record: dict) -> tuple[int, list[str], list[str]]:
    """(점수, 근거태그, 본문에서 찾은 예약번호 후보)"""
    body = record.get("rawText") or ""
    if not body:
        return 0, [], []
    tags: list[str] = []
    points = 0

    krw = abs(round(float(row.get("krw") or 0)))
    if krw and any(form in body for form in amount_forms(krw)):
        points += 6
        tags.append("본문_정확원화")

    try:
        fx = abs(round(float(row.get("foreign") or 0)))
    except ValueError:
        fx = 0
    if fx and any(form in body for form in amount_forms(fx)):
        points += 5
        tags.append("본문_정확외화")

    card4 = (row.get("card4") or "").strip()
    if card4 and len(card4) == 4 and card4 in body:
        points += 3
        tags.append("본문_카드끝4자리")

    rd, md = parse_date(row.get("use_date", "")), mail_date(record)
    if rd and md:
        gap = abs((rd - md).days)
        if gap == 0:
            points += 4
            tags.append("메일일=결제일")
        elif gap <= 3:
            points += 2
            tags.append("메일일±3일")
        elif gap <= 31:
            points += 1
            tags.append("메일일31일내")

    anchor = re.match(r"(\d{4})_", row.get("bucket", ""))
    if anchor and anchor.group(1) in (record.get("travelDates") or []):
        points += 2
        tags.append("여행탭일치")

    # 카드 note 에 이미 적힌 예약번호가 본문에 있으면 결정적
    note_refs = set(BOOKING_RE.findall(row.get("note") or ""))
    hit_refs = [r for r in note_refs if r in body]
    if hit_refs:
        points += 8
        tags.append("note예약번호_본문일치")

    body_refs = list(dict.fromkeys(BOOKING_RE.findall(body)))[:6]
    return points, tags, (hit_refs or body_refs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-stamp", default="20260729")
    ap.add_argument("--shard-size", type=int, default=12)
    ap.add_argument("--min-score", type=int, default=6)
    ap.add_argument("--auto-score", type=int, default=14)
    args = ap.parse_args()

    records = json.loads(INDEX.read_text(encoding="utf-8"))["records"]
    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    with MANUAL.open(encoding="utf-8-sig", newline="") as fh:
        manual = list(csv.DictReader(fh))

    # 수기장부 금액→예약번호 색인(보조근거)
    manual_by_amount: dict[int, list[dict]] = defaultdict(list)
    for m in manual:
        try:
            manual_by_amount[round(float(m["amount"] or 0))].append(m)
        except ValueError:
            continue

    by_provider: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        if rec.get("rawText"):
            by_provider[rec.get("provider")].append(rec)

    # 원장 임의배정에서 강등된 건은 후보 풀에서 제외한다(2026-07-29).
    # 제외하지 않으면 모델 팬아웃이 방금 강등한 배정을 그대로 재확정한다 —
    # 강등 사유(원장 짝짓기가 임의)는 모델이 볼 수 있는 증거로 해소되지 않는다.
    # 해소는 Agoda 상세 확보 후 promote_group_assignments.py 게이트로만 이뤄진다.
    group_assign_path = DATA / "ota_group_assignments.json"
    demoted = (
        set(json.loads(group_assign_path.read_text(encoding="utf-8")))
        if group_assign_path.exists() else set()
    )

    targets = [
        r for r in rows
        if provider_of(f"{r.get('merchant','')} {r.get('note','')}")
        and r["uid"] not in links
        and r["uid"] not in demoted
    ]

    auto, ambiguous, none_found = [], [], []
    for row in targets:
        provider = provider_of(f"{row.get('merchant','')} {row.get('note','')}")
        ranked = []
        for rec in by_provider.get(provider, []):
            points, tags, refs = evidence(row, rec)
            if points >= args.min_score:
                ranked.append((points, rec, tags, refs))
        ranked.sort(key=lambda item: -item[0])

        krw = abs(round(float(row.get("krw") or 0)))
        manual_hits = [
            {"tab": m["tab"], "row": m["row"], "item": m["item"], "card": m["card"],
             "book": (m.get("book") or "").strip()}
            for m in manual_by_amount.get(krw, [])
        ]

        base = {
            "uid": row["uid"],
            "provider": provider,
            "use_date": row["use_date"],
            "card4": row["card4"],
            "merchant": row["merchant"],
            "krw": krw,
            "currency": row["currency"],
            "foreign": row["foreign"],
            "bucket": row["bucket"],
            "note": (row.get("note") or "")[:220],
            "manual_ledger_matches": manual_hits,
        }

        if not ranked:
            none_found.append(base)
            continue

        top_score = ranked[0][0]
        tied = [item for item in ranked if item[0] == top_score]
        cands = [
            {
                "score": p,
                "message_id": rec["messageId"],
                "sent_at": rec.get("sentAt", ""),
                "subject": rec.get("subject", ""),
                "evidence_tags": tags,
                "booking_refs_in_body": refs,
                "mail_booking_refs": rec.get("bookingRefs") or [],
                "mail_amounts": rec.get("amounts") or [],
                "mail_travel_dates": rec.get("travelDates") or [],
            }
            for p, rec, tags, refs in ranked[:5]
        ]
        item = {**base, "candidates": cands}

        # 자동확정: 최고점이 임계 이상 + 동점 유일 + 예약번호 특정 가능
        if top_score >= args.auto_score and len(tied) == 1 and cands[0]["booking_refs_in_body"]:
            refs = cands[0]["booking_refs_in_body"]
            note_refs = set(BOOKING_RE.findall(row.get("note") or ""))
            decisive = [r for r in refs if r in note_refs] or (refs if len(refs) == 1 else [])
            if len(decisive) == 1:
                auto.append({
                    "uid": row["uid"],
                    "provider": provider,
                    "booking_id": decisive[0],
                    "category": "숙박",
                    "period": "",
                    "source_message_id": cands[0]["message_id"],
                    "verification": "Gmail 원문 본문 대조(%s) 점수 %d, 동점 후보 없음"
                                    % ("+".join(cands[0]["evidence_tags"]), top_score),
                    "source": "ledger/build_ota_candidates.py",
                })
                continue
        ambiguous.append(item)

    out = ROOT / "outputs" / f"ota_candidates_{args.out_stamp}"
    (out / "ambiguous_shards").mkdir(parents=True, exist_ok=True)
    (out / "auto_candidates.json").write_text(
        json.dumps(auto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "no_candidate.json").write_text(
        json.dumps(none_found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ambiguous.sort(key=lambda x: -x["krw"])
    shards = [ambiguous[i:i + args.shard_size] for i in range(0, len(ambiguous), args.shard_size)]
    for i, shard in enumerate(shards, 1):
        (out / "ambiguous_shards" / f"{i:02d}.json").write_text(
            json.dumps(shard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "mail_index": str(INDEX.relative_to(ROOT)),
        "mail_records_with_rawtext": sum(len(v) for v in by_provider.values()),
        "existing_links": len(links),
        "unlinked_ota_rows": len(targets),
        "auto_candidates": len(auto),
        "ambiguous": len(ambiguous),
        "ambiguous_shards": len(shards),
        "no_candidate": len(none_found),
        "checksum_rows": len(auto) + len(ambiguous) + len(none_found),
    }
    assert summary["checksum_rows"] == len(targets), summary
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
