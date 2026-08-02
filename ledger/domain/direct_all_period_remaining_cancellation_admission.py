"""Resolve the remaining cancellation pair and prior-period refund group."""
from __future__ import annotations

import csv
import hashlib
import io
import tempfile
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_all_period_corp_void_admission as voids
from ledger.domain import direct_all_period_safe_group_admission as base
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "all-period-remaining-cancellation-resolution-v1"
RULE_VERSION = "all-period-exact-source-pair-and-prior-trip-refund-group-v1"
SELECTED_SET_SHA256 = "24d585580723593e60f9b07e361a328ecf4bd45ae2231a5424fe4c614c0cb517"
HAN_CANCEL_KEY = "card:f6d8bb9008bab3a843ae258e306ea3e69d058d46968f52c240f2870f10824380#cancellation"
HAN_APPROVAL_KEY = "card:bfced2e7b5f9e1d069b38a408abdd0ab5192260d6b4f2191a150298cf3c5d111#approval"
KBO_REFUND_KEYS = {
    "card:8c25632742eb020f86e41c550ef5f6459cfc7bb02795afbaced1b8e09c37bb06#single",
    "card:9bc21326ea255a38023a83ee26b253a0efec72c5eac5b9a71a13d5eb1f2524fe#single",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manual_originals() -> list[dict[str, str]]:
    data = base.r57._secure_read(base.MANUAL, base.MANUAL_SHA256)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    selected = [row for row in rows if row.get("tab") == "0613_북해도" and
                row.get("item") == "아고다_New Akan" and row.get("card") == "국민"]
    amounts = sorted(base._amount(row) for row in selected)
    bookings = {row.get("book") for row in selected}
    if (len(selected) != 4 or amounts != [205309, 410621, 410621, 410621] or
            len(bookings) != 4 or "" in bookings):
        raise ValueError("all_period_cancel_manual_original_group_invalid")
    return selected


def _live(ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> tuple[dict, list[dict]]:
    upstream = voids.build_all_period_corp_void_admission(ledger_dir=ledger_dir)["manifest"]
    if (upstream["accepted_union"], upstream["global_residual"],
            upstream["selected_event_set_sha256"]) != (1551, 3777, voids.SELECTED_SET_SHA256):
        raise ValueError("all_period_cancel_upstream_invalid")
    originals = _manual_originals()
    with tempfile.TemporaryDirectory(prefix="all-period-cancel-") as directory:
        context = r36._context(ledger_dir, Path(directory))
        try:
            universe = {row["direct_event_key"]: row for row in context["events"]}
        finally:
            context["db"].close()
    if (HAN_CANCEL_KEY not in universe or HAN_APPROVAL_KEY not in universe or
            not KBO_REFUND_KEYS <= set(universe)):
        raise ValueError("all_period_cancel_current_member_missing")
    approval = universe[HAN_APPROVAL_KEY]
    cancellation = universe[HAN_CANCEL_KEY]
    pair_fields = ("source_system", "occurred_on", "merchant", "approval_number", "card4", "current_source_key")
    if (any(approval[field] != cancellation[field] for field in pair_fields) or
            (approval["transaction_type"], approval["event_role"], int(approval["signed_amount_krw"]),
             cancellation["transaction_type"], cancellation["event_role"], int(cancellation["signed_amount_krw"])) != (
             "purchase", "approval", 139761, "cancellation", "cancellation", -139761)):
        raise ValueError("all_period_cancel_han_pair_invalid")
    refunds = [universe[key] for key in sorted(KBO_REFUND_KEYS)]
    if len({row["current_source_key"] for row in refunds}) != 2 or any(
            (row["source_system"], row["occurred_on"], int(row["signed_amount_krw"]),
             row["foreign_amount"], row["currency"], row["card4"], row["merchant"],
             row["transaction_type"], row["event_role"]) !=
            ("KBO", "2026-05-22", -209498, "21600", "JPY", "8835",
             "AGODA.COM NEW AKAN H", "cancellation", "single") for row in refunds):
        raise ValueError("all_period_cancel_kbo_refund_group_invalid")
    selected = {HAN_CANCEL_KEY} | KBO_REFUND_KEYS
    if base._setsha(selected) != SELECTED_SET_SHA256:
        raise ValueError("all_period_cancel_selected_set_invalid")
    original_sha = _sha(base._json(sorted(originals, key=lambda row: int(row["row"]))))
    resolutions = [{"event_key_sha256": _sha(HAN_CANCEL_KEY.encode()),
                    "current_event_sha256": cancellation["current_event_sha256"],
                    "disposition": "approval_cancellation_pair", "posting_amount_krw": -139761,
                    "counterpart_event_key_sha256": _sha(HAN_APPROVAL_KEY.encode())}]
    for event in refunds:
        resolutions.append({"event_key_sha256": _sha(event["direct_event_key"].encode()),
                            "current_event_sha256": event["current_event_sha256"],
                            "disposition": "prior_period_lodging_refund", "posting_amount_krw": -209498,
                            "account": "숙박비", "cost_type": "여행원가", "vat_tag": "불공제_해외",
                            "trip_target": "0613_북해도", "posting_bucket": "전기예약_환불",
                            "manual_original_group_sha256": original_sha})
    manifest = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
                "selected_event_set_sha256": SELECTED_SET_SHA256,
                "resolved_event_delta": 3, "full_classification_delta": 2,
                "accepted_union": 1554, "global_residual": 3774,
                "han_pair_net_krw": 0, "kbo_refund_total_krw": -418996,
                "refund_bijection_asserted": False, "refund_group_count": 2,
                "authority_status": "unattested", "posting_status": "blocked",
                "database_applied": False, "contains_sensitive_raw_values": False}
    return manifest, resolutions


def build_all_period_remaining_cancellation_admission(*, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger") -> dict:
    manifest, resolutions = _live(ledger_dir)
    return {"manifest": manifest, "resolutions": resolutions}
