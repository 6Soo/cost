"""Gmail OTA 추출 인덱스를 카드 이벤트와 대사한다.

고신뢰 단일 후보만 ota_event_links_verified.json에 병합한다. 기존 검증값은
절대 덮어쓰지 않으며 복수 후보·저신뢰 후보는 검토 목록으로 남긴다.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path


DATA = Path(__file__).resolve().parent / "data"
INDEX = DATA / "ota_mail_index.json"
CLASSIFIED = DATA / "classified_v14.csv"
LINKS = DATA / "ota_event_links_verified.json"
REPORT = DATA / "ota_reconcile_report.json"
RETIRED_INDEX = DATA / "retired_staff_ota_index.json"


def amount(row: dict) -> int:
    return abs(round(float(row.get("krw") or 0)))


def row_provider(row: dict) -> str | None:
    text = f"{row.get('merchant', '')} {row.get('note', '')}".upper()
    if any(token in text for token in ("마이트립", "MYTRIP", "고투게이트")):
        return "mytrip"
    if any(token in text for token in ("트립닷컴", "TRIP.COM", "CTRIP")):
        return "trip"
    if any(token in text for token in ("AGODA", "아고다")):
        return "agoda"
    if "BOOKING.COM" in text:
        return "booking"
    if any(token in text for token in ("트래블로버", "TRAVELROVER")):
        return "travelrover"
    return None


def parsed_date(value: str):
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, OverflowError):
        return None


def row_names(row: dict) -> set[str]:
    text = f"{row.get('merchant', '')} {row.get('note', '')}"
    ignored = {
        "수기장부", "선결제", "반영", "국민", "항공", "숙박", "취소",
        "트립닷컴", "마이트립", "예약", "메일확정",
    }
    return {
        token
        for token in re.findall(r"[가-힣]{2,4}", text)
        if token not in ignored
    }


def booking_ref(mail: dict) -> str:
    for value in mail.get("bookingRefs", []):
        value = str(value).replace(" ", "")
        if re.fullmatch(r"\d{8,19}|\d{3,6}(?:-\d{3}){2}", value):
            return value
    return ""


def bucket_mmdd(row: dict) -> str:
    match = re.match(r"(\d{4})_", row.get("bucket", ""))
    return match.group(1) if match else ""


def explicit_period(mail: dict, anchor: str) -> str:
    subject = mail.get("subject", "")
    match = re.search(
        r"(?<!\d)(\d{1,2})[./](\d{1,2})\s*(?:~|-)\s*(?:(\d{1,2})[./])?(\d{1,2})(?!\d)",
        subject,
    )
    if match:
        start = f"{int(match.group(1)):02d}{int(match.group(2)):02d}"
        end_month = int(match.group(3) or match.group(1))
        end = f"{end_month:02d}{int(match.group(4)):02d}"
        return f"{start}_{end}"
    match = re.search(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?!\d)", subject)
    if match:
        return f"{int(match.group(1)):02d}{int(match.group(2)):02d}"

    dates = [d for d in mail.get("travelDates", []) if re.fullmatch(r"\d{4}", d)]
    dates = list(dict.fromkeys(dates))
    if anchor in dates:
        index = dates.index(anchor)
        later = dates[index + 1 :]
        if later:
            return f"{anchor}_{later[0]}"
        return anchor
    return ""


def score(row: dict, mail: dict) -> tuple[int, list[str]]:
    points = 1
    reasons = ["업체일치"]
    amt = amount(row)
    if amt in mail.get("amounts", []):
        points += 6
        reasons.append("정확금액")
    row_date = None
    try:
        row_date = datetime.strptime(row.get("use_date", ""), "%Y-%m-%d").date()
    except ValueError:
        pass
    mail_date = parsed_date(mail.get("sentAt", ""))
    if row_date and mail_date:
        gap = abs((row_date - mail_date).days)
        if gap == 0:
            points += 4
            reasons.append("메일일=결제일")
        elif gap <= 3:
            points += 2
            reasons.append("메일일근접")
        elif gap <= 31:
            points += 1
            reasons.append("메일일31일내")
    anchor = bucket_mmdd(row)
    if anchor and anchor in mail.get("travelDates", []):
        points += 3
        reasons.append("여행탭일치")
    names = row_names(row)
    if names and any(name in mail.get("subject", "") for name in names):
        points += 4
        reasons.append("승객명일치")
    if booking_ref(mail):
        points += 1
        reasons.append("예약키존재")
    return points, reasons


def retired_staff_candidates(row: dict, records: list[dict]) -> list[dict]:
    """Return corroborating rows, distinguishing exact and <=2% amounts."""
    provider = row_provider(row)
    row_text = f"{row.get('bucket', '')} {row.get('note', '')}"
    names = row_names(row)
    candidates = []
    for record in records:
        if record.get("provider") != provider:
            continue
        if record.get("paymentDate") != row.get("use_date"):
            continue
        signals = ["결제일", "OTA"]
        destination = record.get("destination", "")
        if destination and any(
            token in row_text
            for token in re.findall(r"[가-힣]{2,}", destination)
        ):
            signals.append("도착지")
        period = record.get("travelPeriod", "")
        anchor = bucket_mmdd(row)
        if period and anchor and anchor in period:
            signals.append("탑승일")
        passengers = record.get("passengers", "")
        if names and any(name in passengers for name in names):
            signals.append("탑승객")
        reference_amount = record.get("amountReference")
        difference_ratio = None
        if isinstance(reference_amount, (int, float)) and reference_amount:
            difference_ratio = abs(amount(row) - abs(round(reference_amount))) / abs(reference_amount)
            if difference_ratio == 0:
                signals.append("금액정확")
            elif difference_ratio <= 0.02:
                signals.append("금액2%이내")
        candidates.append({
            "sourceSheet": record["sourceSheet"],
            "sourceRow": record["sourceRow"],
            "travelPeriod": period,
            "destination": destination,
            "passengers": passengers,
            "amountReference": reference_amount,
            "amountDifferenceRatio": difference_ratio,
            "signals": signals,
            "sourceUrl": record["sourceUrl"],
            "amountPolicy": "exact_or_within_2_percent",
        })
    return sorted(candidates, key=lambda item: -len(item["signals"]))[:5]


def main():
    mails = json.loads(INDEX.read_text(encoding="utf-8"))["records"]
    rows = list(csv.DictReader(CLASSIFIED.open(encoding="utf-8")))
    links = json.loads(LINKS.read_text(encoding="utf-8")) if LINKS.exists() else {}
    retired_records = (
        json.loads(RETIRED_INDEX.read_text(encoding="utf-8"))["records"]
        if RETIRED_INDEX.exists() else []
    )
    by_provider: dict[str, list[dict]] = {}
    for mail in mails:
        if booking_ref(mail):
            by_provider.setdefault(mail["provider"], []).append(mail)

    auto = []
    ambiguous = []
    unresolved = []
    ota_rows = [row for row in rows if row_provider(row)]
    for row in ota_rows:
        uid = row["uid"]
        if uid in links:
            continue
        provider = row_provider(row)
        ranked = []
        for mail in by_provider.get(provider, []):
            points, reasons = score(row, mail)
            if points >= 5:
                ranked.append((points, mail, reasons))
        ranked.sort(key=lambda item: item[0], reverse=True)
        # The same reservation often generates confirmation, change, reminder,
        # and forwarded copies.  Those are evidence for one booking, not
        # competing candidates, so collapse them by reservation number.
        unique_ranked = []
        seen_refs = set()
        for candidate in ranked:
            ref_key = booking_ref(candidate[1])
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)
            unique_ranked.append(candidate)
        ranked = unique_ranked
        if not ranked:
            unresolved.append({
                "uid": uid, "date": row["use_date"], "merchant": row["merchant"],
                "amount": round(float(row["krw"])), "bucket": row["bucket"],
                "reason": "후보 메일 없음",
            })
            continue
        top_score, top_mail, reasons = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else -1
        ref = booking_ref(top_mail)
        period = explicit_period(top_mail, bucket_mmdd(row))
        item = {
            "uid": uid,
            "date": row["use_date"],
            "merchant": row["merchant"],
            "amount": round(float(row["krw"])),
            "bucket": row["bucket"],
            "score": top_score,
            "secondScore": second_score,
            "reasons": reasons,
            "candidate": {
                "messageId": top_mail["messageId"],
                "subject": top_mail["subject"],
                "bookingRef": ref,
                "pnr": (top_mail.get("pnrs") or [""])[0],
                "period": period,
            },
            "retiredStaffCandidates": retired_staff_candidates(row, retired_records),
        }
        # 정확금액을 포함한 9점 이상 단일 우위 후보만 자동 확정한다.
        if top_score >= 9 and "정확금액" in reasons and top_score - second_score >= 2:
            link = {
                ("order_id" if "-" in ref else "booking_id"): ref,
                "category": (
                    "숙박" if row.get("account") == "숙박비"
                    else "항공" if row.get("account") == "항공료"
                    else "여행자보험" if row.get("account") == "여행자보험"
                    else ""
                ),
                "period": period,
                "source_message_id": top_mail["messageId"],
                "match_score": top_score,
                "match_reasons": reasons,
            }
            if top_mail.get("pnrs"):
                link["pnr"] = top_mail["pnrs"][0]
            links[uid] = link
            auto.append(item)
        else:
            item["alternatives"] = [
                {
                    "score": candidate_score,
                    "subject": candidate["subject"],
                    "bookingRef": booking_ref(candidate),
                    "messageId": candidate["messageId"],
                }
                for candidate_score, candidate, _ in ranked[:3]
            ]
            ambiguous.append(item)

    LINKS.write_text(json.dumps(links, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ambiguous.sort(key=lambda item: (-abs(item["amount"]), -item["score"], item["uid"]))
    unresolved.sort(key=lambda item: (-abs(item["amount"]), item["uid"]))
    report = {
        "mailRecords": len(mails),
        "otaCardRows": len(ota_rows),
        "preexistingLinks": len(links) - len(auto),
        "autoLinked": len(auto),
        "ambiguousCount": len(ambiguous),
        "unresolvedCount": len(unresolved),
        "ambiguous": ambiguous,
        "unresolved": unresolved,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "mailRecords", "otaCardRows", "preexistingLinks", "autoLinked",
        "ambiguousCount", "unresolvedCount"
    )}, ensure_ascii=False))
    for index, item in enumerate(ambiguous[:10], 1):
        candidate = item["candidate"]
        print(
            f"{index}. {item['uid']} | {item['date']} | {item['merchant']} | "
            f"{item['amount']:,} | {item['bucket']} | "
            f"{candidate['bookingRef']} | {candidate['period']} | {candidate['subject']} "
            f"(점수 {item['score']}/{item['secondScore']})"
        )


if __name__ == "__main__":
    main()
