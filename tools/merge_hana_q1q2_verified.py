"""Merge the two independently verified Hana cancellation events.

This script is intentionally idempotent.  It only appends event keys and UIDs
that are absent, preserves the source issuer rows as immutable cancellations,
and leaves the unresolved/conflicting rows untouched.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "ledger" / "master_ledger.csv"
CLASSIFIED = [
    ROOT / "ledger" / "data" / "classified_v13.csv",
    ROOT / "ledger" / "data" / "classified_v14.csv",
]
OUT = ROOT / "outputs" / "hana_q1q2_revalidation"

EVENTS = [
    {
        "uid": "HAN-9111",
        "card4": "4595",
        "approval": "462859",
        "date": "2026-06-24",
        "merchant": "LOTTE ARAI RESORT",
        "krw": -52954,
        "foreign": 5400,
        "country_note": "일본",
        "source_row": 13,
    },
    {
        "uid": "HAN-9112",
        "card4": "6741",
        "approval": "171682",
        "date": "2026-01-11",
        "merchant": "HI-YES HOTEL HUA LIAN",
        "krw": -7021,
        "foreign": 150,
        "country_note": "타이완",
        "source_row": 579,
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_dicts(path: Path, encoding: str) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding=encoding, newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def write_dicts(path: Path, fields: list[str], rows: list[dict[str, str]], encoding: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding=encoding, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def merge_master() -> int:
    fields, rows = read_dicts(MASTER, "utf-8-sig")
    present = {row["거래키"] for row in rows}
    added = 0
    for event in EVENTS:
        key = (
            f"하나|{event['card4']}|A{event['approval']}|"
            f"취소|{abs(event['krw'])}"
        )
        if key in present:
            continue
        rows.append(
            {
                "거래키": key,
                "카드사": "하나",
                "카드4": event["card4"],
                "구분": "해외",
                "승인일": event["date"],
                "매입일": "",
                "가맹점": event["merchant"],
                "원화금액": str(event["krw"]),
                "현지금액": str(event["foreign"]),
                "통화": "",
                "승인번호": event["approval"],
                "취소여부": "취소",
                "출처": "하나카드_해외_Q1Q2_20260727",
                "적재일": "2026-07-27",
                "기록여부": "Y",
                "워크북참조": event["uid"],
                "비고": (
                    f"하나카드 해외 원본3 행{event['source_row']} "
                    f"재검증 신규 취소 | {event['country_note']}"
                ),
            }
        )
        present.add(key)
        added += 1
    write_dicts(MASTER, fields, rows, "utf-8-sig")
    return added


def merge_classified(path: Path) -> int:
    fields, rows = read_dicts(path, "utf-8")
    present = {row["uid"] for row in rows}
    added = 0
    for event in EVENTS:
        if event["uid"] in present:
            continue
        row = {field: "" for field in fields}
        row.update(
            {
                "uid": event["uid"],
                "src": "HAN",
                "use_date": event["date"],
                "post_date": event["date"],
                "card4": event["card4"],
                "merchant": event["merchant"],
                "country": "해외",
                "currency": "",
                "foreign": str(event["foreign"]),
                "krw": str(event["krw"]),
                "vat": "0.0",
                "status": "취소",
                "bucket": "취소환불",
                "account": "숙박비",
                "cancel": "True",
                "cost_type": "여행원가",
                "vat_tag": "불공제_해외",
                "confidence": "상",
                "note": (
                    f"하나카드 해외 Q1Q2 원본3 행{event['source_row']} "
                    f"재검증 신규 취소 이벤트 | 원승인 {event['approval']} | "
                    "원거래 추정·상계 없이 독립 보존"
                ),
                "tax_conf": "상",
                "appr": event["approval"],
                "orig_appr": event["approval"],
            }
        )
        rows.append(row)
        present.add(event["uid"])
        added += 1
    write_dicts(path, fields, rows, "utf-8")
    return added


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = OUT / f"premerge_backup_{stamp}"
    backup_dir.mkdir()
    for path in [MASTER, *CLASSIFIED]:
        shutil.copy2(path, backup_dir / path.name)

    before = {str(path): sha256(path) for path in [MASTER, *CLASSIFIED]}
    result = {
        "master_added": merge_master(),
        "classified_added": {
            str(path): merge_classified(path) for path in CLASSIFIED
        },
        "events": EVENTS,
        "held": {
            "conflicts": 3,
            "review": 1,
            "review_amount_krw": -56666,
        },
        "backup_dir": str(backup_dir),
        "before_sha256": before,
        "after_sha256": {
            str(path): sha256(path) for path in [MASTER, *CLASSIFIED]
        },
    }
    report = OUT / "merge_result.json"
    report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    json.loads(report.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
