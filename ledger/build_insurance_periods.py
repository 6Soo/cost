# -*- coding: utf-8 -*-
"""여행자보험(트래블로버) 메일의 가입기간을 파싱해 여행탭 배정 근거로 삼는다 (2026-07-29).

사용자 지시: "트래블로버 메일에 가입기간이 있다면 파싱하고 여행배정 근거로 삼도록 해."

배경: 트래블로버 카드이벤트는 전 건 계정이 `여행자보험`이며 OTA 예약번호 개념이 없어
`ota_event_links_verified.json` 링크 대상이 아니다. 대신 메일 본문의
`보험기간 2026-06-13 ~ 2026-06-19` 같은 명시 구간을 근거로 **여행탭 귀속**을 검증한다.

판정 규칙:
  · 카드 금액이 메일의 보험료와 **정확히 일치**할 때만 후보로 삼는다(근사 금지).
  · 같은 금액의 메일이 둘 이상이면 특정 불가로 HOLD.
  · 보험기간 시작일이 현재 귀속 탭의 MMDD와 같으면 `confirmed`.
  · 다르면 `reassign_candidate` 로 보고만 한다. **자동으로 탭을 바꾸지 않는다.**
  · 제목에만 기간이 있는 메일(예: "2/14~18 …")도 파싱하되 연도가 없으므로 근거 등급을 낮춘다.

출력: outputs/insurance_periods_<stamp>/ 및 ledger/data/insurance_periods_verified.json
중앙 분류자료·링크파일은 **쓰지 않는다**.
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
RAW = DATA / "ota_mail_index.raw.json"
INDEX = RAW if RAW.exists() else DATA / "ota_mail_index.json"
CLASSIFIED = DATA / "classified_v14.csv"
OUT_VERIFIED = DATA / "insurance_periods_verified.json"

PERIOD_BODY = re.compile(
    r"보험기간\s*(\d{4})-(\d{2})-(\d{2})\s*~\s*(\d{4})-(\d{2})-(\d{2})"
)
PERIOD_SUBJECT = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})\s*~\s*(?:(\d{1,2})/)?(\d{1,2})(?!\d)")
FEE = re.compile(r"보험료\s*([\d,]+)\s*원")
DEST = re.compile(r"목적지\s*([^\s]{1,12})")


def parse_mail(record: dict) -> dict | None:
    body = record.get("rawText") or ""
    subject = record.get("subject") or ""

    m = PERIOD_BODY.search(body)
    if m:
        start = f"{m.group(2)}{m.group(3)}"
        end = f"{m.group(5)}{m.group(6)}"
        grade = "body_explicit"
    else:
        s = PERIOD_SUBJECT.search(subject)
        if not s:
            return None
        start = f"{int(s.group(1)):02d}{int(s.group(2)):02d}"
        end = f"{int(s.group(3) or s.group(1)):02d}{int(s.group(4)):02d}"
        grade = "subject_only"

    fee = FEE.search(body)
    amounts = [int(fee.group(1).replace(",", ""))] if fee else list(record.get("amounts") or [])
    dest = DEST.search(body)
    return {
        "message_id": record["messageId"],
        "sent_at": record.get("sentAt", ""),
        "subject": subject[:120],
        "period": f"{start}_{end}",
        "period_start": start,
        "evidence_grade": grade,
        "fee_krw": amounts[0] if amounts else None,
        "all_amounts": amounts,
        "destination": dest.group(1) if dest else "",
    }


def tab_mmdd(bucket: str) -> str:
    m = re.match(r"(\d{4})_", bucket or "")
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-stamp", default="20260729")
    ap.add_argument("--write-verified", action="store_true",
                    help="ledger/data/insurance_periods_verified.json 갱신")
    args = ap.parse_args()

    records = json.loads(INDEX.read_text(encoding="utf-8"))["records"]
    mails = []
    for rec in records:
        text = f"{rec.get('subject','')} {rec.get('rawText','')}"
        if not re.search(r"여행자보험|트래블로버|travelrover", text, re.I):
            continue
        parsed = parse_mail(rec)
        if parsed:
            mails.append(parsed)

    by_fee: dict[int, list[dict]] = defaultdict(list)
    for m in mails:
        if m["fee_krw"]:
            by_fee[m["fee_krw"]].append(m)

    with CLASSIFIED.open(encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["account"] == "여행자보험"]

    confirmed, reassign, hold, none_found = [], [], [], []
    for row in rows:
        amt = abs(round(float(row.get("krw") or 0)))
        cands = by_fee.get(amt, [])
        base = {
            "uid": row["uid"],
            "use_date": row["use_date"],
            "krw": amt,
            "current_bucket": row["bucket"],
            "merchant": row["merchant"][:40],
        }
        if not cands:
            none_found.append(base)
            continue
        if len(cands) > 1:
            hold.append({**base, "reason": "동일 보험료 메일 %d건 — 특정 불가" % len(cands),
                         "candidates": cands})
            continue
        mail = cands[0]
        item = {
            **base,
            "period": mail["period"],
            "evidence_grade": mail["evidence_grade"],
            "destination": mail["destination"],
            "message_id": mail["message_id"],
            "mail_subject": mail["subject"],
        }
        if tab_mmdd(row["bucket"]) == mail["period_start"]:
            confirmed.append({**item, "verdict": "current_tab_confirmed"})
        else:
            item["suggested_tab_mmdd"] = mail["period_start"]
            reassign.append({**item, "verdict": "reassign_candidate"})

    out = ROOT / "outputs" / f"insurance_periods_{args.out_stamp}"
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in (("01_confirmed.json", confirmed),
                          ("02_reassign_candidates.json", reassign),
                          ("03_hold.json", hold),
                          ("04_no_mail_evidence.json", none_found),
                          ("05_parsed_mails.json", mails)):
        (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

    summary = {
        "insurance_mails_parsed": len(mails),
        "body_explicit": sum(1 for m in mails if m["evidence_grade"] == "body_explicit"),
        "subject_only": sum(1 for m in mails if m["evidence_grade"] == "subject_only"),
        "insurance_card_rows": len(rows),
        "current_tab_confirmed": len(confirmed),
        "reassign_candidates": len(reassign),
        "hold_same_fee": len(hold),
        "no_mail_evidence": len(none_found),
        "checksum": len(confirmed) + len(reassign) + len(hold) + len(none_found),
    }
    assert summary["checksum"] == len(rows), summary
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")

    if args.write_verified:
        verified = {
            x["uid"]: {
                "period": x["period"],
                "category": "여행자보험",
                "destination": x["destination"],
                "evidence_grade": x["evidence_grade"],
                "source_message_id": x["message_id"],
                "verification_source": "travelrover_mail_보험기간",
                "current_bucket": x["current_bucket"],
                **({"suggested_tab_mmdd": x["suggested_tab_mmdd"]} if "suggested_tab_mmdd" in x else {}),
            }
            for x in confirmed + reassign
        }
        tmp = OUT_VERIFIED.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(verified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        import os
        os.replace(tmp, OUT_VERIFIED)
        readback = json.loads(OUT_VERIFIED.read_text(encoding="utf-8"))
        assert len(readback) == len(verified), (len(readback), len(verified))
        summary["written_verified"] = len(verified)
        print(f"기간 검증값 {len(verified)}건 → {OUT_VERIFIED.relative_to(ROOT)} (read-back OK)")

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
