"""Admit the five non-conflicting manual groups left after R59.

The three groups are deliberately narrow: exact current cardinality and exact
manual multiset are both required.  No rule is broadcast by merchant name.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
from pathlib import Path

from ledger.domain import direct_agoda_customer_service_evidence as r49
from ledger.domain import direct_kb_confirmation_evidence as r45
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_mytrip_airfare_atomic_admission as r59
from ledger.domain import direct_trip_airfare_atomic_admission as r57
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-safe-manual-groups-full-v1"
RULE_VERSION = "all-period-exact-current-manual-multiset-v1"
MANUAL = r57.MANUAL
MANUAL_SHA256 = r57.MANUAL_SHA256
SELECTED_SET_SHA256 = "414856751e5b4de59d2515352d0387c17259b85a1cceb0425c1d94d39be53e8c"

# (source, date, signed KRW, card4, merchant, count, manual tab, manual item,
#  account, cost type, VAT tag)
GROUPS = (
    ("KBO", "2026-04-03", 150970, "8835", "BKG*BOOKING.COM HOTEL", 3,
     "0413_나가센도", None, "숙박비", "여행원가", "불공제_해외"),
    ("KBO", "2026-04-08", 148228, "8835", "AGODA.COM HOTEL PEAR", 2,
     "0408_교토", "AGODA.COM HOTEL PEAR", "숙박비", "여행원가", "불공제_해외"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def _setsha(values) -> str:
    return r36._event_set_sha(set(values))


def _amount(row: dict[str, str]) -> int:
    try:
        return abs(int(float(row.get("amount") or 0)))
    except (TypeError, ValueError):
        return -1


def _date(value: str) -> str:
    text = str(value or "").strip().replace(".", "-")
    if len(text) == 8 and text[2] == "-":
        text = "20" + text
    return text


def _manual_groups(path: Path = MANUAL) -> dict[tuple, list[dict[str, str]]]:
    if path.resolve() != MANUAL.resolve():
        raise ValueError("all_period_manual_path_invalid")
    data = r57._secure_read(path, MANUAL_SHA256)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    if len(rows) != 1559 or len({(row["tab"], row["row"]) for row in rows}) != 1559:
        raise ValueError("all_period_manual_census_invalid")
    result = {}
    for group in GROUPS:
        source, date, amount, card4, merchant, count, tab, item, *_ = group
        del source, card4
        matches = [row for row in rows if row.get("tab") == tab and
                   _date(row.get("date")) == date and
                   row.get("card") in {"국민", "하나"} and _amount(row) == amount and
                   (item is None or row.get("item") == item)]
        # Booking has two raw-merchant rows plus one provider-labelled row.
        if merchant.startswith("BKG*"):
            matches = [row for row in matches if row.get("item") in
                       {merchant, "부킹_Nezame Hotel"}]
        if len(matches) != count or len({(row["tab"], row["row"]) for row in matches}) != count:
            raise ValueError("all_period_manual_group_cardinality_invalid")
        result[group[:6]] = matches
    return result


def _later_selected(universe: dict[str, dict]) -> set[str]:
    trip = {key for key, event in universe.items()
            if event["source_system"] == "KBD" and event["occurred_on"] == "2026-03-24"
            and int(event["signed_amount_krw"]) == 208400
            and event["transaction_type"] == "purchase" and event["event_role"] == "single"}
    mytrip = set()
    for _gid, (_member, _doc, _tab, day, amount, _item) in r59.GROUPS.items():
        iso = "20" + day.replace(".", "-")
        mytrip |= {key for key, event in universe.items()
                   if event["source_system"] == "KBD" and event["occurred_on"] == iso
                   and int(event["signed_amount_krw"]) == amount
                   and event["transaction_type"] == "purchase" and event["event_role"] == "single"}
    if len(trip) != 2 or _setsha(trip) != r57.MEMBER_SET_SHA256 or len(mytrip) != 4 or _setsha(mytrip) != r59.SELECTED_SET_SHA256:
        raise ValueError("all_period_later_admission_membership_invalid")
    return trip | mytrip


def _live(ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> tuple[dict, list[dict]]:
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("all_period_noncanonical_ledger")
    manual = _manual_groups()
    with tempfile.TemporaryDirectory(prefix="all-period-safe-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            rows = list(context["events"])
        finally:
            context["db"].close()
    universe = {row["direct_event_key"]: row for row in rows}
    if len(universe) != 5328 or len(universe) != len(rows):
        raise ValueError("all_period_current_census_invalid")
    accepted0, _ = r44._accepted_union(ledger_dir)
    admitted = set(r45.EVENTS) | {r49.TARGET_EVENT} | set(r44.EVENTS) | _later_selected(universe)
    pre_residual = set(universe) - accepted0 - admitted
    if len(pre_residual) != 3786 or _setsha(pre_residual) != r59.POST_RESIDUAL_SHA256:
        raise ValueError("all_period_r59_state_invalid")
    selected = set()
    proposals = []
    for group in GROUPS:
        source, date, amount, card4, merchant, count, tab, _item, account, cost_type, vat = group
        matches = {key for key in pre_residual if
                   universe[key]["source_system"] == source and universe[key]["occurred_on"] == date and
                   int(universe[key]["signed_amount_krw"]) == amount and universe[key]["card4"] == card4 and
                   universe[key]["merchant"] == merchant and universe[key]["transaction_type"] == "purchase" and
                   universe[key]["event_role"] == "single"}
        if len(matches) != count:
            raise ValueError("all_period_current_group_cardinality_invalid")
        selected |= matches
        manual_sha = _sha(_json(sorted(manual[group[:6]], key=lambda row: int(row["row"]))))
        group_id = _sha(_json({"signature": group[:6], "manual": manual_sha}))
        for key in sorted(matches):
            event = universe[key]
            proposals.append({"event_key_sha256": _sha(key.encode()),
                              "current_event_sha256": event["current_event_sha256"],
                              "current_source_sha256": event["current_source_sha256"],
                              "group_id": group_id, "group_count": count, "account": account,
                              "cost_type": cost_type, "vat_tag": vat, "trip_target": tab})
    if len(selected) != 5 or _setsha(selected) != SELECTED_SET_SHA256:
        raise ValueError("all_period_selected_set_invalid")
    post = pre_residual - selected
    manifest = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
                "selected_event_set_sha256": SELECTED_SET_SHA256,
                "full_classification_delta": 5, "accepted_union": 1547,
                "global_residual": len(post), "post_residual_set_sha256": _setsha(post),
                "authority_status": "unattested", "posting_status": "blocked",
                "database_applied": False, "contains_sensitive_raw_values": False}
    return manifest, proposals


def build_all_period_safe_group_admission(*, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    manifest, proposals = _live(ledger_dir)
    return {"manifest": manifest, "proposals": proposals}
