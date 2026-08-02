"""Pin the complete available card-source coverage without a quarter filter."""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from ledger import cardindex
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-card-source-coverage-census-v1"
RULE_VERSION = "p25-all-available-input-rows-no-period-filter-v1"
EXPECTED_FILES = {
    "A_20260720.xlsx": "45d29d086de7b01f9e4c0f55452f2ef8acc12baa44a5a9fe77f046a4f8a7dd56",
    "E.xlsx": "7db0f68cb4d01fb33f50694b04e4a28796079f67db09e35e6e4b75372cb3c16c",
    "F.xlsx": "e9f1656a297b76e6834ae5785755cfbffbf9c7ec64d7400db41f5e26440cf4a5",
    "G.xlsx": "f90ae46f217b2694c3d2fb012bf9550f0b7e395a785f7d19b8e83d5ca9060bb0",
    "H.xlsx": "e719a4b5468ae529663118cc2ac3dffc80094d75687d6e868655a7de4f82b9b0",
}
EXPECTED_SOURCES = {
    "CORP": {"raw_rows": 174, "normalized_events": 174,
             "min_date": "2026-01-25", "max_date": "2026-07-14"},
    "HAN": {"raw_rows": 2097, "normalized_events": 2188,
            "min_date": "2025-07-21", "max_date": "2026-07-20"},
    "KBD": {"raw_rows": 1287, "normalized_events": 1287,
            "min_date": "2025-05-06", "max_date": "2026-07-15"},
    "KBO": {"raw_rows": 1679, "normalized_events": 1679,
            "min_date": "2025-07-21", "max_date": "2026-07-14"},
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_all_period_source_coverage_census(
        *, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("all_period_source_coverage_noncanonical_ledger")
    source_dir = ledger_dir / "newcard" / "conv"
    actual_files = {name: _sha(source_dir / name) for name in EXPECTED_FILES}
    if actual_files != EXPECTED_FILES:
        raise ValueError("all_period_source_coverage_file_pin_drift")
    cards = cardindex.build_cards(ledger_dir=ledger_dir)
    sources = {}
    for source in sorted({card["src"] for card in cards}):
        rows = [card for card in cards if card["src"] == source]
        normalized_events = sum(len(card["han_components"]) if source == "HAN" else 1
                                for card in rows)
        sources[source] = {"raw_rows": len(rows), "normalized_events": normalized_events,
                           "min_date": min(card["use"] for card in rows),
                           "max_date": max(card["use"] for card in rows)}
    if sources != EXPECTED_SOURCES:
        raise ValueError("all_period_source_coverage_census_drift")
    raw_rows = sum(source["raw_rows"] for source in sources.values())
    normalized_events = sum(source["normalized_events"] for source in sources.values())
    month_counts = Counter(card["use"][:7] for card in cards)
    if raw_rows != 5237 or normalized_events != 5328 or sum(month_counts.values()) != raw_rows:
        raise ValueError("all_period_source_coverage_total_drift")
    return {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "input_file_sha256": actual_files, "source_coverage": sources,
            "raw_card_row_count": raw_rows, "normalized_event_count": normalized_events,
            "han_component_expansion_count": normalized_events - raw_rows,
            "period_filter_applied": False, "available_input_rows_excluded": 0,
            "earliest_available_date": min(card["use"] for card in cards),
            "latest_available_date": max(card["use"] for card in cards),
            "pre_source_range_data_claimed": False,
            "database_applied": False}
