"""Classify two Q2 card events whose latest manual rows are duplicated, not charges."""
from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_q2_remaining_cancellation_admission as cancellations
from ledger.domain import direct_q2_safe_group_admission as q2
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "q2-manual-duplicate-collapse-admission-v1"
RULE_VERSION = "q2-card-cardinality-one-manual-duplicate-axis-v1"
SELECTED_SET_SHA256 = "b612c323caef871426049a5b52153b78d930e70678a149e1ba65cdf322a68120"
TARGETS = (
    ("KBO", "2026-05-18", 634113, "3820", "ANA AIRFOOOCM",
     "0616_레분토&리시리", "항공", "항공료"),
    ("KBO", "2026-06-25", 18755, "6881", "GYOMUSUPATSURUOKAJOHOK",
     "0620_묘코", "기타비용", "기타비용"),
)


def _manual() -> dict[tuple, list[dict[str, str]]]:
    data = q2.r57._secure_read(q2.MANUAL, q2.MANUAL_SHA256)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    result = {}
    for source, date, amount, card4, merchant, tab, item, account in TARGETS:
        del source, card4, account
        matches = [row for row in rows if row.get("tab") == tab and q2._date(row.get("date")) == date and
                   row.get("card") == "국민" and q2._amount(row) == amount and row.get("item") == merchant and
                   row.get("desc") == item]
        if len(matches) != 2 or len({(row["tab"], row["row"]) for row in matches}) != 2:
            raise ValueError("q2_duplicate_manual_pair_invalid")
        result[(date, amount, merchant)] = matches
    return result


def _live(ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> tuple[dict, list[dict]]:
    upstream = cancellations.build_q2_remaining_cancellation_admission(ledger_dir=ledger_dir)["manifest"]
    if (upstream["accepted_union"], upstream["global_residual"],
            upstream["selected_event_set_sha256"]) != (1554, 3774, cancellations.SELECTED_SET_SHA256):
        raise ValueError("q2_duplicate_upstream_invalid")
    manual = _manual()
    with tempfile.TemporaryDirectory(prefix="q2-duplicate-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            events = list(context["events"])
        finally:
            context["db"].close()
    selected = set()
    proposals = []
    for source, date, amount, card4, merchant, tab, item, account in TARGETS:
        matches = [event for event in events if
                   (event["source_system"], event["occurred_on"], int(event["signed_amount_krw"]),
                    event["card4"], event["merchant"], event["transaction_type"], event["event_role"]) ==
                   (source, date, amount, card4, merchant, "purchase", "single")]
        if len(matches) != 1:
            raise ValueError("q2_duplicate_current_cardinality_invalid")
        event = matches[0]
        selected.add(event["direct_event_key"])
        proposals.append({"event_key_sha256": q2._sha(event["direct_event_key"].encode()),
                          "current_event_sha256": event["current_event_sha256"],
                          "current_source_sha256": event["current_source_sha256"],
                          "manual_duplicate_count": len(manual[(date, amount, merchant)]),
                          "physical_card_event_count": 1, "account": account,
                          "cost_type": "여행원가", "vat_tag": "불공제_해외",
                          "trip_target": tab, "manual_item": item})
    if q2._setsha(selected) != SELECTED_SET_SHA256:
        raise ValueError("q2_duplicate_selected_set_invalid")
    manifest = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
                "selected_event_set_sha256": SELECTED_SET_SHA256,
                "full_classification_delta": 2, "accepted_union": 1556, "global_residual": 3772,
                "manual_rows": 4, "physical_card_events": 2,
                "manual_duplicate_rows_not_extra_events": 2,
                "authority_status": "unattested", "posting_status": "blocked",
                "database_applied": False, "contains_sensitive_raw_values": False}
    return manifest, proposals


def build_q2_manual_duplicate_collapse_admission(*, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    manifest, proposals = _live(ledger_dir)
    return {"manifest": manifest, "proposals": proposals}
