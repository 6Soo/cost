from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE card_payments (
    event_key TEXT PRIMARY KEY,
    occurred_on TEXT NOT NULL,
    card4 TEXT NOT NULL,
    merchant TEXT NOT NULL,
    currency TEXT NOT NULL,
    local_amount REAL,
    amount_krw INTEGER NOT NULL
);
CREATE TABLE classification_decisions (
    id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL,
    account TEXT,
    cost_type TEXT,
    allocation_target TEXT,
    vat_tag TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    superseded_by_id INTEGER
);
"""

PAYMENTS = [
    ("TX-0001", "2026-04-17", "8835", "PLAZA HOTEL MUTSU", "JPY", 21030, 205461),
    ("TX-0002", "2026-06-20", "1234", "AGODA MERCURE", "KRW", None, 556929),
    ("TX-0003", "2026-06-21", "8835", "LAWSON TOKYO", "JPY", 820, 8420),
    ("TX-0004", "2026-06-22", "1234", "HERTZ RENT", "KRW", None, -543947),
    ("TX-0005", "2026-07-05", "8835", "KAMENOI DAZAIFU", "KRW", None, 1307772),
]

DECISIONS = [
    (1, "TX-0001", "숙박비", "여행원가", "0417_아오모리", "불공제_해외",
     "superseded", 2),
    (2, "TX-0001", "숙박비", "여행원가", "0417_아오모리", "확인",
     "active", None),
    (3, "TX-0002", "숙박비", "여행원가", "0620_묘코", "불공제_해외",
     "active", None),
]


def build_demo_snapshot(base_dir: Path) -> dict:
    base_dir.mkdir(parents=True, exist_ok=True)
    db_path = base_dir / "candidate.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO card_payments VALUES (?,?,?,?,?,?,?)", PAYMENTS
        )
        conn.executemany(
            "INSERT INTO classification_decisions VALUES (?,?,?,?,?,?,?,?)",
            DECISIONS,
        )
        conn.commit()
    finally:
        conn.close()
    gate_report = {
        "run_id": "run-demo-1",
        "generated_at": "2026-08-25T00:00:00+00:00",
        "gates": [
            {"gate": f"GATE{i}", "status": "PASS"} for i in range(1, 5)
        ]
        + [
            {"gate": "GATE5", "status": "FAIL", "detail": "unresolved remain"},
            {"gate": "GATE6", "status": "FAIL", "detail": "baseline missing"},
            {"gate": "GATE7", "status": "PASS"},
        ],
        "readiness": {
            "triage_pass": True,
            "shadow_ready": True,
            "release_ready": False,
        },
        "candidate_semantic_sha256": "a" * 64,
    }
    gate_path = base_dir / "gate_report.json"
    with open(gate_path, "w", encoding="utf-8") as handle:
        json.dump(gate_report, handle, ensure_ascii=False)
    from webapp.snapshot_descriptor import seal_snapshot

    descriptor = seal_snapshot(db_path, gate_report_path=gate_path)
    return {
        "dir": base_dir,
        "db": db_path,
        "gate_report": gate_path,
        "descriptor_path": Path(descriptor["descriptor_path"]),
    }


def demo_axes(account="숙박비", cost_type="여행원가",
              allocation_target=None, vat_tag=None) -> dict:
    return {
        "account": account,
        "cost_type": cost_type,
        "allocation_target": allocation_target,
        "vat_tag": vat_tag,
    }
