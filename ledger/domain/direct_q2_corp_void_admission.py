"""Resolve four 2026-Q2 corporate-card authorization voids as zero-posting events."""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_q2_safe_group_admission as q2
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "q2-corp-authorization-void-resolution-v1"
RULE_VERSION = "q2-corp-source-void-and-legacy-zero-v1"
CLASSIFIED_SHA256 = "8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989"
SELECTED_SET_SHA256 = "3acd515a122d22a8135508c055f4c817f6a29e2d032ce6f1ecb0ee07b77854ac"

# approval -> (date, signed source amount, card4, merchant)
TARGETS = {
    "51666879": ("2026-04-20", -356418, "4971", "나이스정보통신"),
    "51671053": ("2026-04-20", -356158, "4971", "트립닷컴"),
    "853146": ("2026-04-21", -1160562, "4971", "AGODA.COM              Internet      SGP"),
    "881741": ("2026-04-28", -11595, "4985", "SUZUKIDAISETSUKAN      Ishikawa      JPN"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digits(value: object) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _historical(ledger_dir: Path) -> dict[str, dict[str, str]]:
    path = ledger_dir / "data" / "classified_v14.csv"
    data = path.read_bytes()
    if _sha(data) != CLASSIFIED_SHA256:
        raise ValueError("q2_void_classified_pin_invalid")
    rows = list(csv.DictReader(data.decode("utf-8-sig").splitlines()))
    found = {}
    for row in rows:
        approval = _digits(row.get("appr"))
        if approval not in TARGETS or row.get("src") != "CORP":
            continue
        if row.get("status") != "승인취소" or int(float(row.get("krw") or 0)) != 0:
            raise ValueError("q2_void_historical_disposition_invalid")
        if approval in found:
            raise ValueError("q2_void_historical_duplicate")
        found[approval] = row
    if set(found) != set(TARGETS):
        raise ValueError("q2_void_historical_missing")
    return found


def _live(ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> tuple[dict, list[dict]]:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("q2_void_noncanonical_ledger")
    upstream = q2.build_q2_safe_group_admission(ledger_dir=ledger_dir)["manifest"]
    if (upstream["accepted_union"], upstream["global_residual"],
            upstream["selected_event_set_sha256"]) != (1547, 3781, q2.SELECTED_SET_SHA256):
        raise ValueError("q2_void_upstream_invalid")
    historical = _historical(ledger_dir)
    with tempfile.TemporaryDirectory(prefix="q2-void-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            rows = list(context["events"])
        finally:
            context["db"].close()
    selected = []
    for event in rows:
        approval = _digits(event.get("approval_number"))
        if approval not in TARGETS or event.get("source_system") != "CORP":
            continue
        date, amount, card4, merchant = TARGETS[approval]
        if (event.get("occurred_on"), int(event.get("signed_amount_krw")), event.get("card4"),
                event.get("merchant"), event.get("transaction_type"), event.get("event_role")) != (
                date, amount, card4, merchant, "cancellation", "single"):
            raise ValueError("q2_void_current_fact_invalid")
        old = historical[approval]
        selected.append({"event_key_sha256": _sha(event["direct_event_key"].encode()),
                         "current_event_sha256": event["current_event_sha256"],
                         "current_source_sha256": event["current_source_sha256"],
                         "historical_row_sha256": _sha(json.dumps(old, ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")).encode()),
                         "disposition": "void_no_posting", "posting_amount_krw": 0})
    keys = {event["direct_event_key"] for event in rows
            if _digits(event.get("approval_number")) in TARGETS and event.get("source_system") == "CORP"}
    if len(selected) != 4 or len(keys) != 4 or q2._setsha(keys) != SELECTED_SET_SHA256:
        raise ValueError("q2_void_selected_set_invalid")
    manifest = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
                "selected_event_set_sha256": SELECTED_SET_SHA256,
                "resolved_event_delta": 4, "full_classification_delta": 0,
                "accepted_union": 1551, "global_residual": 3777,
                "posting_amount_krw": 0, "disposition": "void_no_posting",
                "authority_status": "unattested", "posting_status": "blocked",
                "database_applied": False, "contains_sensitive_raw_values": False}
    return manifest, selected


def build_q2_corp_void_admission(*, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    manifest, resolutions = _live(ledger_dir)
    return {"manifest": manifest, "resolutions": resolutions}
