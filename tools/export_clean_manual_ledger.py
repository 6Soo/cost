from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from copy import copy
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.result_selection_rules import (  # noqa: E402
    ALLOWED_EVENT_YEARS,
    EventPeriod,
    evidence_date_period,
    event_period_for_targets,
    normalize_merchant_name,
    split_targets,
)
from ledger.domain.manual_ledger_booking_link import (  # noqa: E402
    link_booking_numbers,
    load_manual_booking_rows,
    load_manual_expense_rows,
)
from tools.export_event_year_manual_ledger import (  # noqa: E402
    _as_int,
    _is_nontravel_target,
    _load_period_context,
    _safe_sheet_name,
    _evidence_label,
)
from tools.export_package_c_results import HEADERS, build_rows  # noqa: E402


MANUAL_HEADERS = (
    "거래일자",
    "항목",
    "내용",
    "기간",
    "예약번호",
    "증빙유형",
    "금액(원)",
)

FORBIDDEN_HEADERS = {
    "행사기간",
    "행사년도",
    "원본가맹점",
    "배분대상",
    "분류경로",
    "결제ID",
}

CONTENT_MAP = {
    "숙박비": "숙박",
    "항공료": "항공",
    "렌터카": "렌트",
    "주유비": "주유",
    "비용제외": "기타비용",
}

PERIOD_ACCOUNTS = frozenset({
    "항공료",
    "항공",
    "숙박비",
    "숙박",
    "렌터카",
    "렌트",
    "여행자보험",
})
OUTPUT_FONT_NAME = "Carlito"
OUTPUT_FONT_SIZE = 11
PERIOD_COLUMN_WIDTH = 16
TOTAL_ROW_FILL = PatternFill(fill_type="solid", fgColor="FFFFFF00")
CANCELLATION_REFUND_TARGET = "취소환불"
LOCAL_ACTIVITY_TARGET_PREFIX = "임시여행활동_"
LOCAL_ACTIVITY_REFUND_PREFIX = "임시여행활동환불_"
EUROPE_LOCAL_TARGET = "5월_유럽"
DOMESTIC_TRIP_REGIONS = frozenset({"부산", "도고", "의왕", "화순", "군산"})

# These paths are useful candidate signals, not independent service-period
# evidence.  They may reach a travel tab only through the bounded onsite-use
# rule below or through a unique OTA/PG/service-mail confirmation.
WEAK_TRAVEL_PATHS = (
    "current_card_trip_cluster_registry_exact",
    "current_card_inferred_external_target",
    "current_card_geography_context_exact_2026",
    "current_card_foreign_use_date_schedule_exact_2026",
)
ACTIVITY_PATH = "current_card_travel_activity_placeholder"
MAIL_REQUIRED_PATH = "current_card_reservation_placeholder"

# Only these persisted source kinds represent an independently collected
# OTA/PG/service mail.  A non-empty source-kind field is not sufficient:
# values such as ``card_raw`` or an unrecognised adapter label must fail
# closed and cannot satisfy the 2025/2026 mail gate.
MAIL_SOURCE_ALLOWLIST = frozenset({
    "ota_mail",
    "ota_mail_live",
    "ota_mail_snapshot",
    "pg_mail",
    "pg_mail_supplement",
    "gmail_payment",
    "gmail_payment_live",
    "gmail_payment_snapshot",
    "service_mail",
})

# A weak geography/cluster candidate may be displayed under a canonical trip
# only when the card fact looks like an onsite purchase and the payment date
# belongs to exactly one canonical trip.  This rule is intentionally separate
# from the classifier's existing activity placeholder path: it never promotes
# OTA/PG reservations, airfare, lodging prepayments, rentals, insurance, or
# reversals from a merchant/country label alone.
LOCAL_PURCHASE_ACCOUNTS = frozenset({
    "식비",
    "교통비",
    "통행료",
    "주유비",
    "입장료",
    "이용료",
    "주차비",
})
ONLINE_OR_GATEWAY_TOKENS = (
    "TRIP",
    "트립",
    "AGODA",
    "아고다",
    "BOOKING",
    "부킹",
    "GOTOGATE",
    "고투게이트",
    "KLOOK",
    "클룩",
    "TRAVELROVER",
    "트래블로버",
    "MYTRIP",
    "마이트립",
    "AIRBNB",
    "EXPEDIA",
    "익스피디아",
    "NICE",
    "나이스",
    "KCP",
    "KICC",
    "이니시스",
    "토스페이",
    "네이버페이",
    "카카오페이",
    "PAYCO",
    "PG",
)


def _is_airfare_account(account: object) -> bool:
    return str(account or "").strip() in {"항공료", "항공"}


def _is_reversal_row(row: dict[str, object]) -> bool:
    return str(row.get("transaction_type") or "").strip().lower() in {
        "refund",
        "cancellation",
        "reversal",
    }


def _is_airfare_content(content: object) -> bool:
    value = str(content or "").strip()
    return value.startswith("항공_") and bool(value[len("항공_"):].strip())


_NON_PASSENGER_CONTENTS = frozenset({
    "항공",
    "항공료",
    "숙박",
    "숙박비",
    "렌트",
    "렌터카",
    "여행자보험",
    "보험",
    "식비",
    "교통비",
    "통행료",
    "주유비",
    "기타비용",
    "비용제외",
    "복리후생비",
    "수수료",
    "지급수수료",
    "소모품비",
    "입장료",
    "이용료",
    "회의비",
    "통신비",
    "세금과공과",
    "영수증",
})


def _account_group(value: object) -> str:
    text = str(value or "").strip()
    if text in {"항공", "항공료"}:
        return "항공"
    if text in {"숙박", "숙박비"}:
        return "숙박"
    if text in {"렌트", "렌터카"}:
        return "렌트"
    if text.startswith("여행자보험") or text == "보험":
        return "여행자보험"
    return text


def _manual_content_group(content: object) -> str:
    text = str(content or "").strip()
    if _is_airfare_content(text):
        return "항공"
    return _account_group(text)


def _period_from_text(value: object) -> str:
    text = str(value or "").strip()
    match = re.search(r"(?<!\d)(\d{4})(?:_(\d{4}))?(?!\d)", text)
    if not match:
        return ""
    return (
        f"{match.group(1)}_{match.group(2)}"
        if match.group(2)
        else match.group(1)
    )


def _period_from_manual_row(manual) -> str:
    period = _period_from_text(manual.period)
    if period:
        return period
    content = str(manual.content or "").strip()
    if content.startswith("여행자보험"):
        return _period_from_text(content[len("여행자보험"):])
    if content.startswith("항공_"):
        return _period_from_text(content[len("항공_"):])
    return ""


def _period_content_allowed(content: object) -> bool:
    value = str(content or "").strip()
    return (
        value in {"항공", "숙박", "렌트", "여행자보험"}
        or _is_airfare_content(value)
    )


def human_content(account: object, passenger_content: object = "") -> str:
    """Return the manual-ledger expense category, not an internal cost lane."""

    value = str(account or "").strip()
    if _is_airfare_account(value):
        passenger = str(passenger_content or "").strip()
        return passenger if _is_airfare_content(passenger) else "항공"
    return CONTENT_MAP.get(value, value)


def _airfare_passenger_name(content: object) -> str:
    """Extract a passenger name from one exact manual-ledger airline row.

    The source ledger contains both ``항공_이름`` labels and bare passenger
    names.  Date tokens may appear before or after the name.  This helper only
    normalizes the display label; the caller still requires exact target/date/
    amount matching and an airfare account.
    """

    text = re.sub(r"\s+", " ", str(content or "").strip())
    if not text or text in _NON_PASSENGER_CONTENTS:
        return ""
    if text.startswith("항공_"):
        name = text[len("항공_"):].strip()
        name = re.sub(r"^(?:\d{4}_){1,2}", "", name)
        name = re.sub(r"_\d{4}(?:_\d{4})?$", "", name)
    else:
        name = text
    name = re.sub(r"\s+", " ", name).strip(" _")
    if not name or name in _NON_PASSENGER_CONTENTS:
        return ""
    return name


def manual_period(period, account: object = "") -> str:
    """Format an event period for a service account."""

    if _account_group(account) not in {"항공", "숙박", "렌트", "여행자보험"}:
        return ""
    if period is None:
        return ""
    if isinstance(period, str):
        return _period_from_text(period)
    if period.starts_on is None or period.ends_on is None:
        return ""
    if period.starts_on == period.ends_on:
        return period.starts_on.strftime("%m%d")
    return f"{period.starts_on:%m%d}_{period.ends_on:%m%d}"


def _target_name(row: dict[str, object]) -> str:
    targets = split_targets(row.get("allocation_target"))
    for target in targets:
        if target != "기타비용" and "행사기간미상" not in target:
            return target
    return ""


def _date_value(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value or "")


def _airfare_passenger_content(
    row: dict[str, object],
    target: str,
    manual_rows,
) -> str:
    """Return a unique manual passenger label for an already-classified fare.

    Manual content is display metadata only.  It never changes the classifier
    account or target.  Exact target/date/amount plus one or more matching
    passenger rows is required; both ``항공_...`` and bare names in the
    manual ledger are accepted.  Otherwise the safe fallback is generic
    ``항공``.
    """

    if not _is_airfare_account(row.get("account")) or _is_reversal_row(row):
        return ""
    payment_date = _date_value(row.get("occurred_on"))
    amount = _as_int(row.get("amount_krw"))
    if not isinstance(payment_date, date) or not amount:
        return ""
    matches = [
        manual
        for manual in manual_rows
        if manual.target == target
        and manual.occurred_on == payment_date
        and manual.amount_krw == amount
        and _airfare_passenger_name(manual.content)
    ]
    names: list[str] = []
    for manual in matches:
        name = _airfare_passenger_name(manual.content)
        if name and name not in names:
            names.append(name)
    return f"항공_{' '.join(names)}" if names else ""


def _lineage_key(row: dict[str, object]) -> tuple[str, ...]:
    """Compatibility fallback for callers that do not have a candidate DB."""

    return tuple(str(row.get(field) or "").strip() for field in (
        "source_system", "external_key", "identity_fingerprint", "record_version"
    ))


def _load_lineage_keys(db: sqlite3.Connection) -> dict[int, tuple[str, ...]]:
    """Load the candidate's immutable source-row lineage, not a re-created key.

    The projection link is the authoritative one-to-one bridge from the
    user-facing payment row to the current normalized source record.  The
    source tuple is intentionally content-addressed and includes event role.
    """

    rows = db.execute(
        """
        SELECT link.payment_id,
               source.source_kind,
               source.source_key,
               source.source_sha256,
               normalized.event_role
          FROM direct_payment_projection_links AS link
          JOIN direct_normalized_payments AS normalized
            ON normalized.id = link.direct_payment_id
          JOIN direct_source_records AS source
            ON source.id = normalized.source_record_id
         ORDER BY link.payment_id
        """
    ).fetchall()
    result: dict[int, tuple[str, ...]] = {}
    for payment_id, source_kind, source_key, source_sha256, event_role in rows:
        key = tuple(
            str(value or "").strip()
            for value in (source_kind, source_key, source_sha256, event_role)
        )
        if not all(key) or int(payment_id) in result:
            raise RuntimeError("candidate_source_lineage_not_one_to_one")
        result[int(payment_id)] = key
    return result


def _conflict_free(row: dict[str, object]) -> bool:
    try:
        return int(row.get("conflict_count") or 0) == 0
    except (TypeError, ValueError):
        return False


def _is_cancellation_refund_lane(row: dict[str, object]) -> bool:
    """Return true for the explicit zero-net cancellation/refund lane."""

    return (
        str(row.get("allocation_target") or "").strip()
        == CANCELLATION_REFUND_TARGET
        and str(row.get("cost_type") or "").strip() == "비용제외"
    )


def _is_local_activity_purchase(row: dict[str, object]) -> bool:
    """Recognize an onsite-use purchase whose payment date is its event date.

    This is deliberately limited to the classifier's activity placeholder
    path.  Reservation placeholders (OTA, airfare, lodging prepayments) do
    not qualify, and activity reversals stay outside the travel lane.
    """

    target = _target_name(row)
    occurred = _date_value(row.get("occurred_on"))
    transaction_type = str(row.get("transaction_type") or "").strip().lower()
    return (
        isinstance(occurred, date)
        and transaction_type == "purchase"
        and _conflict_free(row)
        and _is_physical_local_purchase(row)
        and target.startswith(LOCAL_ACTIVITY_TARGET_PREFIX)
        and not target.startswith(LOCAL_ACTIVITY_REFUND_PREFIX)
    )


def _is_physical_local_purchase(row: dict[str, object]) -> bool:
    """Recognize a weak-candidate purchase that behaves like onsite use.

    The merchant's ``TOKYO JP``-style suffix is never used as evidence here.
    The safe display-only rule requires a positive purchase, a physical-use
    account category, no classifier conflict, and no online/provider/gateway
    marker.  It is deliberately narrower than ``activity_placeholder``.
    """

    if (
        str(row.get("transaction_type") or "").strip().lower() != "purchase"
        or _as_int(row.get("amount_krw")) <= 0
        or not _conflict_free(row)
        or _account_group(row.get("account")) not in LOCAL_PURCHASE_ACCOUNTS
    ):
        return False
    merchant = str(row.get("merchant") or "").upper()
    return not any(token in merchant for token in ONLINE_OR_GATEWAY_TOKENS)


def _single_active_trip_local_target(
    row: dict[str, object],
    trip_ranges: dict[str, tuple[object, object]] | None = None,
) -> str:
    """Return the one canonical trip for a safe weak-candidate local use.

    A target already present on the row must be a canonical trip and must be
    the only trip active on the payment date.  This prevents a geography or
    cluster label from deciding the trip when dates overlap or no canonical
    trip exists.  The caller still applies the strict 2025 mail-only branch
    before this helper can be used.
    """

    if not _is_physical_local_purchase(row):
        return ""
    target = _target_name(row)
    ranges = trip_ranges or {}
    if not target or target not in ranges:
        return ""
    occurred = _date_value(row.get("occurred_on"))
    if not isinstance(occurred, date):
        return ""
    active = _active_trip_codes_for_date(occurred, ranges)
    return target if len(active) == 1 and active[0] == target else ""


def _active_trip_codes_for_date(
    occurred: date,
    trip_ranges: dict[str, tuple[object, object]] | None = None,
) -> list[str]:
    """Return canonical trips active on one date, preserving input order."""

    active: list[str] = []
    for code, bounds in (trip_ranges or {}).items():
        if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
            continue
        starts_on = _date_value(bounds[0])
        ends_on = _date_value(bounds[1])
        if (
            isinstance(starts_on, date)
            and isinstance(ends_on, date)
            and starts_on <= occurred <= ends_on
            and not str(code).startswith(LOCAL_ACTIVITY_TARGET_PREFIX)
        ):
            active.append(str(code))
    return active


def _single_active_trip_for_activity(
    row: dict[str, object],
    trip_ranges: dict[str, tuple[object, object]] | None = None,
) -> str:
    """Map a temporary onsite activity to exactly one canonical trip."""

    if not _is_local_activity_purchase(row):
        return ""
    occurred = _date_value(row.get("occurred_on"))
    if not isinstance(occurred, date):
        return ""
    active = _active_trip_codes_for_date(occurred, trip_ranges)
    return active[0] if len(active) == 1 else ""


def _is_europe_carpisa_purchase(
    row: dict[str, object],
    trip_ranges: dict[str, tuple[object, object]] | None = None,
) -> bool:
    """Recognize the bounded CARPISA onsite purchase for the Europe trip.

    CARPISA VERONA is a physical merchant in the 2026 Europe itinerary.  The
    rule is intentionally bounded by the canonical ``5월_유럽`` schedule and
    only applies to a conflict-free purchase that is currently unassigned.
    It does not turn an arbitrary CARPISA/Europe-looking row into a trip.
    """

    target = _target_name(row)
    merchant = str(row.get("merchant") or "").upper()
    occurred = _date_value(row.get("occurred_on"))
    transaction_type = str(row.get("transaction_type") or "").strip().lower()
    if not (
        "CARPISA" in merchant
        and isinstance(occurred, date)
        and transaction_type == "purchase"
        and _conflict_free(row)
        and (not target or target.startswith("여행_미배정"))
    ):
        return False
    bounds = (trip_ranges or {}).get(EUROPE_LOCAL_TARGET)
    if not bounds or len(bounds) != 2:
        return False
    starts_on = _date_value(bounds[0])
    ends_on = _date_value(bounds[1])
    return (
        isinstance(starts_on, date)
        and isinstance(ends_on, date)
        and starts_on <= occurred <= ends_on
    )


def _load_nonzero_reversal_parents(
    db: sqlite3.Connection,
    rows_by_payment: dict[int, dict[str, object]],
) -> dict[int, int]:
    """Return reversal->original links whose individual pair is nonzero.

    This is a display-order rule only.  Relation evidence is already present
    in the candidate DB; no classifier, allocation, or posting state is
    changed here.  Ambiguous multiple-parent links fail closed and are not
    attached automatically.
    """

    candidates: dict[int, set[int]] = defaultdict(set)
    relation_rows = db.execute(
        """
        SELECT transaction_id, related_transaction_id
          FROM transaction_relations
         WHERE relation_type IN ('refunds', 'cancellations', 'reverses')
           AND relation_status NOT IN ('rejected', 'superseded')
         ORDER BY id
        """
    ).fetchall()
    for left_id, right_id in relation_rows:
        left = rows_by_payment.get(int(left_id))
        right = rows_by_payment.get(int(right_id))
        if left is None or right is None:
            continue
        left_reversal = _is_reversal_row(left)
        right_reversal = _is_reversal_row(right)
        if left_reversal == right_reversal:
            continue
        reversal, original = (
            (left, right) if left_reversal else (right, left)
        )
        if str(original.get("transaction_type") or "").strip().lower() != "purchase":
            continue
        pair_net = _as_int(reversal.get("amount_krw")) + _as_int(
            original.get("amount_krw")
        )
        if pair_net != 0:
            candidates[_as_int(reversal.get("payment_id"))].add(
                _as_int(original.get("payment_id"))
            )
    return {
        reversal_id: next(iter(parents))
        for reversal_id, parents in candidates.items()
        if len(parents) == 1 and reversal_id and next(iter(parents))
    }


def _display_sort_key(
    row: dict[str, object],
    reversal_parents: dict[int, int] | None = None,
    child_rank: dict[int, int] | None = None,
    original_date_by_reversal: dict[int, str] | None = None,
) -> tuple[str, int, int, int, int]:
    """Sort a reversal immediately after its nonzero-net original payment."""

    payment_id = _as_int(row.get("payment_id"))
    parents = reversal_parents or {}
    ranks = child_rank or {}
    original_id = parents.get(payment_id)
    if original_id:
        original_dates = original_date_by_reversal or {}
        original_date = original_dates.get(payment_id, "")
        return (
            original_date,
            original_id,
            1,
            ranks.get(payment_id, 1),
            payment_id,
        )
    return (
        str(row.get("occurred_on") or ""),
        payment_id,
        0,
        0,
        payment_id,
    )


def _local_activity_period(
    row: dict[str, object], target: str
) -> EventPeriod | None:
    """Build the user-authorized one-day event period for onsite use."""

    occurred = _date_value(row.get("occurred_on"))
    if not isinstance(occurred, date):
        return None
    return EventPeriod(
        occurred,
        occurred,
        "payment_date_local_activity",
        target,
        "onsite-use payment date treated as event date by user rule",
    )


def _is_confirmed_2025_travel(
    row: dict[str, object],
    target: str,
    period,
    evidence_payloads,
) -> bool:
    """Allow 2025 travel output only for a mail-bound 2026 service period."""

    occurred = _date_value(row.get("occurred_on"))
    if not isinstance(occurred, date) or occurred.year != 2025:
        return False
    if 2026 not in period.event_years:
        return False
    if not _has_mail_confirmed_service_period(
        evidence_payloads, target, payment_year=2025
    ):
        return False
    return _is_confirmed_event_target(row, target, period, evidence_payloads)


def _has_mail_confirmed_service_period(
    evidence_payloads,
    target: str,
    payment_year: int | None = None,
) -> bool:
    """Read the classifier's persisted mail-only promotion decision.

    The exporter must not reconstruct an event from a trip schedule,
    local-use target, or a payment-date placeholder.  It accepts only the
    explicit finality flag written by the classifier after checking a unique
    OTA/PG/service-mail source and its allowed 2026/2027 service period.  The
    2025 branch passes ``payment_year=2025`` and separately requires a 2026
    event period.
    """

    for payload in evidence_payloads or ():
        if not isinstance(payload, dict):
            continue
        finality = payload.get("row_finality")
        axes = payload.get("axes")
        if not isinstance(finality, dict) or not isinstance(axes, dict):
            continue
        target_axis = axes.get("allocation_target")
        if not isinstance(target_axis, dict):
            continue
        if payment_year is not None and finality.get("payment_year") != payment_year:
            continue
        if not _allowed_mail_source_kinds(finality):
            continue
        if (
            finality.get("mail_service_period_verified") is True
            and target_axis.get("value") == target
            and finality.get("eligible") is True
        ):
            return True
    return False


def _allowed_mail_source_kinds(finality: dict[str, object]) -> bool:
    """Require every persisted mail source kind to be an allowed mail type."""

    source_kinds = finality.get("mail_service_period_source_kinds")
    if not isinstance(source_kinds, (list, tuple)):
        return False
    normalized = {str(kind or "").strip() for kind in source_kinds}
    normalized.discard("")
    return bool(normalized) and normalized.issubset(MAIL_SOURCE_ALLOWLIST)


def _has_payment_mail_evidence(row: dict[str, object], evidence_payloads) -> bool:
    """Return whether an independently linked payment/service mail exists."""

    for payload in evidence_payloads or ():
        if not isinstance(payload, dict):
            continue
        finality = payload.get("row_finality")
        if not isinstance(finality, dict):
            continue
        if _allowed_mail_source_kinds(finality):
            return True
    path_text = " ".join(
        str(row.get(field) or "")
        for field in ("rule_path", "classification_source")
    ).lower()
    return any(
        token in path_text
        for token in (
            "ota_mail",
            "pg_mail",
            "gmail_payment",
            "service_mail",
        )
    )


def _has_rule_path(row: dict[str, object], token: str) -> bool:
    path_text = " ".join(
        str(row.get(field) or "")
        for field in ("rule_path", "classification_source")
    )
    return token in path_text


def _requires_mail_service_period(row: dict[str, object]) -> bool:
    """Identify online/provider/reservation rows that cannot use a schedule alone."""

    if _has_rule_path(row, MAIL_REQUIRED_PATH):
        return True
    merchant = str(row.get("merchant") or "").upper()
    return any(token in merchant for token in ONLINE_OR_GATEWAY_TOKENS)


def _load_card_facts(db: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """Load card4/sub from the immutable source lineage, not payment_methods."""

    rows = db.execute(
        """
        SELECT link.payment_id, source.payload_json
          FROM direct_payment_projection_links AS link
          JOIN direct_normalized_payments AS normalized
            ON normalized.id = link.direct_payment_id
          JOIN direct_source_records AS source
            ON source.id = normalized.source_record_id
         ORDER BY link.payment_id
        """
    ).fetchall()
    result: dict[int, dict[str, str]] = {}
    for payment_id, payload_json in rows:
        payment_id = int(payment_id)
        if payment_id in result:
            raise RuntimeError("candidate_card_fact_not_one_to_one")
        try:
            payload = json.loads(str(payload_json or "{}"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("candidate_card_fact_payload_invalid") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("candidate_card_fact_payload_invalid")
        result[payment_id] = {
            "card4": str(payload.get("card4") or "").strip(),
            "sub": str(payload.get("sub") or "").strip(),
            "currency": str(payload.get("currency") or "").strip(),
        }
    return result


def _load_trip_regions(db: sqlite3.Connection) -> dict[str, str]:
    rows = db.execute("SELECT code, region FROM trips ORDER BY code").fetchall()
    return {str(code).strip(): str(region or "").strip() for code, region in rows}


def _is_domestic_trip_code(code: str, region: str) -> bool:
    value = str(region or "").strip()
    if value in DOMESTIC_TRIP_REGIONS:
        return True
    return any(token in str(code or "") for token in DOMESTIC_TRIP_REGIONS)


def _domestic_trip_active(
    occurred: object,
    trip_ranges: dict[str, tuple[object, object]] | None,
    trip_regions: dict[str, str] | None,
) -> bool:
    if not isinstance(occurred, date):
        return False
    for code, bounds in (trip_ranges or {}).items():
        if len(bounds) != 2 or not _is_domestic_trip_code(
            code, (trip_regions or {}).get(code, "")
        ):
            continue
        starts_on = _date_value(bounds[0])
        ends_on = _date_value(bounds[1])
        if (
            isinstance(starts_on, date)
            and isinstance(ends_on, date)
            and starts_on <= occurred <= ends_on
        ):
            return True
    return False


def _is_3820_domestic_nontravel(
    row: dict[str, object],
    card_fact: dict[str, str] | None,
    evidence_payloads,
    trip_ranges: dict[str, tuple[object, object]] | None,
    trip_regions: dict[str, str] | None,
) -> bool:
    """Apply the user's 3820/no-mail/outside-domestic-trip rule."""

    fact = card_fact or {}
    occurred = _date_value(row.get("occurred_on"))
    return (
        fact.get("card4") == "3820"
        and fact.get("sub") == "국내"
        and str(row.get("transaction_type") or "").strip().lower() == "purchase"
        and _as_int(row.get("amount_krw")) > 0
        and _conflict_free(row)
        and not _has_payment_mail_evidence(row, evidence_payloads)
        and isinstance(occurred, date)
        and not _domestic_trip_active(occurred, trip_ranges, trip_regions)
    )


def _is_confirmed_event_target(
    row: dict[str, object],
    target: str,
    period,
    evidence_payloads,
) -> bool:
    """Require a single target and an allowed, conflict-free period source."""

    targets = split_targets(row.get("allocation_target"))
    if len(targets) != 1 or targets[0] != target or not _conflict_free(row):
        return False
    event_years = frozenset(period.event_years)
    if (
        period.target != target
        or not event_years
        or not (event_years & ALLOWED_EVENT_YEARS)
    ):
        return False
    if period.source == "trip_schedule":
        return True
    if period.source == "service_evidence" and len(evidence_payloads) == 1:
        return evidence_date_period(evidence_payloads) is not None
    return False


def _raw_target_for_matching(row: dict[str, object], fallback: str = "") -> str:
    """Return one unambiguous raw target for display-only manual matching."""

    targets = split_targets(row.get("allocation_target"))
    if len(targets) == 1 and targets[0] not in {"기타비용", ""}:
        return targets[0]
    return fallback


def _output_lane(
    row: dict[str, object],
    period,
    evidence_payloads=(),
    trip_ranges: dict[str, tuple[object, object]] | None = None,
    card_fact: dict[str, str] | None = None,
    trip_regions: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Assign one and only one user-facing output lane.

    ``여행`` is reserved for an eligible 2026/2027 event period, with one
    user-authorized exception for onsite-use purchases: an unambiguous
    ``임시여행활동_`` purchase uses its payment date as a one-day event date.
    Reservation placeholders still require an independent service period.
    A 2025 payment may enter a travel tab only when the independently resolved
    event period contains 2026.  Explicit zero-net cancellation/refund rows
    are always placed in their own display-only lane.
    """

    occurred = _date_value(row.get("occurred_on"))
    occurred_year = occurred.year if isinstance(occurred, date) else None
    target = _target_name(row)
    if _is_cancellation_refund_lane(row):
        return "cancellation_refund", CANCELLATION_REFUND_TARGET
    if str(row.get("terminal_disposition") or "") == "2025년 결제":
        # The projection explicitly marked this row as the strict 2025
        # display terminal.  Do not infer a travel target from a related row,
        # a region label, or a payment-date activity fallback.
        return "2025_payment", "2025년 결제"
    if occurred_year == 2025:
        if target and _is_confirmed_2025_travel(
            row, target, period, evidence_payloads
        ):
            return "travel", target
        return "2025_payment", "2025년 결제"
    if _is_3820_domestic_nontravel(
        row,
        card_fact,
        evidence_payloads,
        trip_ranges,
        trip_regions,
    ):
        return "other", "기타비용"
    if _is_nontravel_target(row.get("allocation_target")):
        return "other", "기타비용"
    if _is_europe_carpisa_purchase(row, trip_ranges):
        return "travel", EUROPE_LOCAL_TARGET
    activity_target = _single_active_trip_for_activity(row, trip_ranges)
    weak_local_target = _single_active_trip_local_target(row, trip_ranges)
    mail_confirmed = bool(
        target and _has_mail_confirmed_service_period(evidence_payloads, target)
    )
    # Reservation/provider rows are gated before any local-use fallback.
    # A lodging/OTA/PG-looking row cannot become travel merely because its
    # account and date resemble onsite use.
    if _requires_mail_service_period(row) and not mail_confirmed:
        return "review", "검토필요"
    if _has_rule_path(row, ACTIVITY_PATH) and not activity_target and not mail_confirmed:
        return "review", "검토필요"
    if (
        any(_has_rule_path(row, path) for path in WEAK_TRAVEL_PATHS)
        and not mail_confirmed
        and not activity_target
        and not weak_local_target
    ):
        return "review", "검토필요"
    if (
        target
        and _is_confirmed_event_target(row, target, period, evidence_payloads)
    ):
        return "travel", target
    if activity_target:
        return "travel", activity_target
    if weak_local_target:
        return "travel", weak_local_target
    return "review", "검토필요"


def _output_period(
    row: dict[str, object],
    event_period,
    target: str,
    booking_number: str,
    manual_rows,
) -> str:
    """Resolve the display period without turning a trip window into a booking period.

    Lodging and rental rows use an exact manual-ledger service period when one
    exists; otherwise they stay blank.  Insurance uses the same explicit
    period first, then the trip window as a display-only coverage fallback.
    Airfare keeps the trip-window fallback because the passenger/service
    period is ordinarily the event window in this ledger.
    """

    if _is_reversal_row(row):
        return ""
    group = _account_group(row.get("account"))
    if group not in {"항공", "숙박", "렌트", "여행자보험"}:
        return ""

    payment_date = _date_value(row.get("occurred_on"))
    amount = _as_int(row.get("amount_krw"))
    exact = [
        manual
        for manual in manual_rows
        if manual.target == target
        and manual.occurred_on == payment_date
        and manual.amount_krw == amount
        and _manual_content_group(manual.content) == group
    ]
    if booking_number:
        booked = [manual for manual in exact if manual.booking_number == booking_number]
        if booked:
            exact = booked

    periods = {
        period
        for period in (_period_from_manual_row(manual) for manual in exact)
        if period
    }
    if len(periods) == 1:
        return next(iter(periods))

    if getattr(event_period, "source", "") == "payment_date_local_activity":
        return manual_period(event_period, group)

    if group in {"항공", "여행자보험"}:
        return manual_period(event_period, group)
    return ""


def _row_for_manual_ledger(
    row: dict[str, object],
    period,
    booking_number: str = "",
    passenger_content: str = "",
) -> list[object]:
    return [
        _date_value(row.get("occurred_on")),
        normalize_merchant_name(row.get("merchant")),
        human_content(row.get("account"), passenger_content),
        manual_period(period, row.get("account")),
        booking_number,
        _evidence_label(row.get("source_system")),
        _as_int(row.get("amount_krw")),
    ]


def _copy_style(source, target) -> None:
    # Copy public style components rather than the source workbook's internal
    # style-array index; style IDs are workbook-local and break on merge.
    target.font = copy(source.font)
    target.fill = copy(source.fill)
    target.border = copy(source.border)
    target.alignment = copy(source.alignment)
    target.number_format = source.number_format
    target.protection = copy(source.protection)


def _copy_row_style(template, output, source_row: int, target_row: int, max_col: int = 9) -> None:
    for column in range(1, max_col + 1):
        _copy_style(template.cell(source_row, column), output.cell(target_row, column))
    source_height = template.row_dimensions[source_row].height
    if source_height is not None:
        output.row_dimensions[target_row].height = source_height


def _copy_column_widths(template, output, max_col: int = 10) -> None:
    for column in range(1, max_col + 1):
        letter = template.cell(1, column).column_letter
        source_dimension = template.column_dimensions[letter]
        output.column_dimensions[letter].width = source_dimension.width
        output.column_dimensions[letter].hidden = source_dimension.hidden


def _copy_sheet_basics(template, output) -> None:
    output.sheet_view.showGridLines = template.sheet_view.showGridLines
    output.sheet_format.defaultColWidth = template.sheet_format.defaultColWidth
    output.sheet_format.defaultRowHeight = template.sheet_format.defaultRowHeight
    output.freeze_panes = template.freeze_panes
    output.sheet_properties.pageSetUpPr = copy(template.sheet_properties.pageSetUpPr)
    output.page_setup = copy(template.page_setup)
    output.page_margins = copy(template.page_margins)
    output.print_options = copy(template.print_options)
    output.sheet_properties.outlinePr = copy(template.sheet_properties.outlinePr)


def _apply_output_font(cell) -> None:
    font = copy(cell.font)
    font.name = OUTPUT_FONT_NAME
    font.sz = OUTPUT_FONT_SIZE
    cell.font = font


def _write_trip_sheet(
    template,
    workbook,
    target: str,
    rows: list[tuple[dict[str, object], object, str, str]],
    sheet_name: str,
) -> None:
    sheet = workbook.create_sheet(sheet_name)
    _copy_sheet_basics(template, sheet)
    _copy_column_widths(template, sheet)

    # Match the current manual-ledger expense section: company/title, section
    # band, seven expense columns, then the total row.
    _copy_row_style(template, sheet, 2, 2)
    _copy_row_style(template, sheet, 4, 4)
    _copy_row_style(template, sheet, 25, 6)
    _copy_row_style(template, sheet, 26, 7)
    for cell in sheet[2]:
        if cell.column <= 9:
            cell.value = None
    sheet["B2"] = "㈜숲길여행"
    if target == "2025년 결제":
        title = "2025년 결제내역"
    elif target in {"검토필요", "기타비용"}:
        title = f"2026·2027년 행사 지출내역_{target}"
    else:
        title = f"2026·2027년 행사 지출내역_{target}"
    sheet["C2"] = title
    sheet.merge_cells("C2:H2")

    sheet["B6"] = "지출 내용"
    sheet.merge_cells("B6:H6")
    for column, header in enumerate(MANUAL_HEADERS, start=2):
        sheet.cell(7, column, header)

    for index, (row, period, booking_number, passenger_content) in enumerate(rows, start=8):
        _copy_row_style(template, sheet, 27, index)
        values = _row_for_manual_ledger(
            row, period, booking_number, passenger_content
        )
        for column, value in enumerate(values, start=2):
            sheet.cell(index, column, value)
        sheet.cell(index, 2).number_format = "yyyy\\-mm\\-dd"
        sheet.cell(index, 5).number_format = "@"
        sheet.cell(index, 8).number_format = "#,##0"

    total_row = 8 + len(rows)
    _copy_row_style(template, sheet, 77, total_row)
    sheet.cell(total_row, 2, "총 금액 (B)")
    sheet.cell(total_row, 3, f"=SUM(H8:H{total_row - 1})")
    for column in range(2, 9):
        cell = sheet.cell(total_row, column)
        cell.fill = copy(TOTAL_ROW_FILL)
        font = copy(cell.font)
        font.name = OUTPUT_FONT_NAME
        font.sz = OUTPUT_FONT_SIZE
        font.color = "FF000000"
        cell.font = font
    sheet.merge_cells(start_row=total_row, start_column=3, end_row=total_row, end_column=8)

    # Keep only the user-facing area.  Technical columns are never written.
    for row in sheet.iter_rows(min_row=1, max_row=total_row, min_col=1, max_col=9):
        for cell in row:
            if cell.value is not None:
                cell.alignment = copy(cell.alignment)
            _apply_output_font(cell)
    sheet.column_dimensions["E"].width = max(
        float(sheet.column_dimensions["E"].width or 0), PERIOD_COLUMN_WIDTH
    )


def _source_count(report: dict[str, object]) -> int:
    for gate in report.get("gates", []):
        if gate.get("gate") == 5:
            return int(gate.get("actual", {}).get("candidate_payment_count") or 0)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--manual-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    db = sqlite3.connect(args.db)
    try:
        raw_rows = build_rows(db)
        try:
            terminal_payment_ids = {
                _as_int(row[0])
                for row in db.execute(
                    """SELECT payment_id
                       FROM direct_2025_payment_terminals
                       WHERE disposition='2025년 결제'"""
                ).fetchall()
            }
        except sqlite3.OperationalError:
            terminal_payment_ids = set()
        trips, registries, evidence = _load_period_context(db)
        card_facts_by_payment = _load_card_facts(db)
        trip_regions = _load_trip_regions(db)
        rows_by_payment = {
            _as_int(row[0]): dict(zip(HEADERS, row))
            for row in raw_rows
        }
        nonzero_reversal_parents = _load_nonzero_reversal_parents(
            db, rows_by_payment
        )
        lineage_by_payment = _load_lineage_keys(db)
    finally:
        db.close()

    expected = _source_count(report)
    if expected and len(raw_rows) != expected:
        raise RuntimeError(f"candidate_row_count_mismatch:{len(raw_rows)}!={expected}")
    raw_payment_ids = {_as_int(dict(zip(HEADERS, row))["payment_id"]) for row in raw_rows}
    if len(lineage_by_payment) != len(raw_rows) or set(lineage_by_payment) != raw_payment_ids:
        raise RuntimeError("candidate_lineage_population_mismatch")

    selected: list[tuple[dict[str, object], object, str, str, str, str]] = []
    excluded = Counter()
    lane_counts = Counter()
    lane_amounts = Counter()
    content_counts = Counter()
    lineage_keys: set[tuple[str, ...]] = set()
    manual_expense_rows = load_manual_expense_rows(args.manual_ledger)
    for raw in raw_rows:
        row = dict(zip(HEADERS, raw))
        if _as_int(row.get("payment_id")) in terminal_payment_ids:
            row["terminal_disposition"] = "2025년 결제"
        if (
            not str(row.get("occurred_on") or "").strip()
            or not str(row.get("merchant") or "").strip()
            or row.get("amount_krw") in {None, ""}
        ):
            excluded["필수 원본 필드 없음"] += 1
            continue
        payment_id = _as_int(row.get("payment_id"))
        lineage_key = lineage_by_payment.get(payment_id)
        if lineage_key is None or lineage_key in lineage_keys:
            raise RuntimeError("candidate_lineage_key_not_unique")
        lineage_keys.add(lineage_key)
        evidence_payloads = evidence.get(payment_id, ())
        period = event_period_for_targets(
            row.get("allocation_target"),
            trips=trips,
            registries=registries,
            evidence_payloads=evidence_payloads,
        )
        lane, output_target = _output_lane(
            row,
            period,
            evidence_payloads,
            trips,
            card_facts_by_payment.get(payment_id),
            trip_regions,
        )
        activity_target = _single_active_trip_for_activity(row, trips)
        weak_local_target = _single_active_trip_local_target(row, trips)
        output_period = (
            _local_activity_period(row, output_target)
            if lane == "travel"
            and (
                activity_target == output_target
                or _is_europe_carpisa_purchase(row, trips)
                or weak_local_target == output_target
            )
            else period
        )
        target = _target_name(row)
        matching_target = _raw_target_for_matching(row, target)
        passenger_content = _airfare_passenger_content(
            row, matching_target, manual_expense_rows
        )
        selected.append(
            (
                row,
                output_period,
                output_target,
                matching_target,
                passenger_content,
                lane,
            )
        )

    base_target_by_payment = {
        _as_int(row.get("payment_id")): output_target
        for row, _period, output_target, _matching, _passenger, _lane in selected
    }
    base_lane_by_payment = {
        _as_int(row.get("payment_id")): lane
        for row, _period, _output_target, _matching, _passenger, lane in selected
    }
    display_target_by_payment = dict(base_target_by_payment)
    display_lane_by_payment = dict(base_lane_by_payment)
    original_date_by_reversal: dict[int, str] = {}
    children_by_original: dict[int, list[int]] = defaultdict(list)
    for reversal_id, original_id in nonzero_reversal_parents.items():
        if original_id in terminal_payment_ids:
            # A terminal purchase has no reversal-inheritance semantics.  Its
            # related refund/cancellation remains in the dedicated reversal
            # display lane instead of being pulled under 2025 payment.
            continue
        original_target = base_target_by_payment.get(original_id)
        original_lane = base_lane_by_payment.get(original_id)
        if not original_target or not original_lane:
            continue
        display_target_by_payment[reversal_id] = original_target
        display_lane_by_payment[reversal_id] = original_lane
        original_date_by_reversal[reversal_id] = str(
            rows_by_payment[original_id].get("occurred_on") or ""
        )
        children_by_original[original_id].append(reversal_id)
    child_rank: dict[int, int] = {}
    for original_id, children in children_by_original.items():
        for rank, reversal_id in enumerate(sorted(children), start=1):
            child_rank[reversal_id] = rank

    for row, _period, _output_target, _matching, passenger_content, _lane in selected:
        payment_id = _as_int(row.get("payment_id"))
        lane_counts[display_lane_by_payment[payment_id]] += 1
        lane_amounts[display_lane_by_payment[payment_id]] += _as_int(
            row.get("amount_krw")
        )
        content_counts[human_content(row.get("account"), passenger_content)] += 1

    manual_booking_rows = [
        row for row in manual_expense_rows if row.booking_number
    ]
    link_inputs = [
        {
            "payment_id": _as_int(row.get("payment_id")),
            "target": matching_target,
            "amount_krw": row.get("amount_krw"),
            "occurred_on": row.get("occurred_on"),
            "merchant": row.get("merchant"),
            "account": row.get("account"),
            "event_start": period.starts_on,
            "event_end": period.ends_on,
        }
        for row, period, _output_target, matching_target, _passenger, _lane in selected
    ]
    booking_links, link_diagnostics = link_booking_numbers(
        link_inputs, manual_booking_rows
    )
    grouped: dict[str, list[tuple[dict[str, object], object, str, str]]] = defaultdict(list)
    target_starts: dict[str, date] = {}
    for row, period, base_output_target, matching_target, passenger_content, base_lane in selected:
        payment_id = _as_int(row.get("payment_id"))
        output_target = display_target_by_payment[payment_id]
        lane = display_lane_by_payment[payment_id]
        if lane == "travel" and period.starts_on is not None:
            current_start = target_starts.get(output_target)
            if current_start is None or period.starts_on < current_start:
                target_starts[output_target] = period.starts_on
        booking_number = (
            ""
            if _is_reversal_row(row)
            else booking_links.get(_as_int(row.get("payment_id")), "")
        )
        # Only a travel lane may show a period.  The 2025, cancellation/refund,
        # other, and review lanes deliberately leave it blank even when a
        # weaker manual row happens to contain a date range.
        display_period = (
            _output_period(
                row,
                period,
                matching_target,
                booking_number,
                manual_expense_rows,
            )
            if lane == "travel"
            else ""
        )
        grouped[output_target].append(
            (
                row,
                display_period,
                booking_number,
                passenger_content,
            )
        )

    # Canonical trip order by the manual schedule, then name for same-day trips.
    def trip_sort(item: tuple[str, list[tuple[dict[str, object], object, str, str]]]) -> tuple[str, str]:
        target, _target_rows = item
        if target == "2025년 결제":
            return ("9999-01-01", target)
        if target == "기타비용":
            return ("9999-01-02", target)
        if target == CANCELLATION_REFUND_TARGET:
            return ("9999-01-03", target)
        if target == "검토필요":
            return ("9999-01-04", target)
        start = target_starts.get(target)
        return (start.isoformat() if start is not None else "9999-99-99", target)

    ordered = sorted(grouped.items(), key=trip_sort)
    template_book = load_workbook(args.template, read_only=False, data_only=False)
    template = template_book["0404_에히메"]
    workbook = Workbook()
    workbook.remove(workbook.active)
    used_sheet_names: set[str] = set()
    output_sheet_names: list[str] = []
    for target, target_rows in ordered:
        target_rows.sort(
            key=lambda item: _display_sort_key(
                item[0],
                nonzero_reversal_parents,
                child_rank,
                original_date_by_reversal,
            )
        )
        sheet_name = _safe_sheet_name(target, used_sheet_names)
        output_sheet_names.append(sheet_name)
        _write_trip_sheet(template, workbook, target, target_rows, sheet_name)
    template_book.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"
    workbook.properties.title = "행사 지출내역 — 수기장부형 여행별 탭"
    workbook.properties.subject = "사용자용 지출 결과"
    workbook.save(args.output)

    # Compact post-save checks: no technical headers/sheets and all tabs retain
    # the exact manual-ledger expense header/style shape.
    check = load_workbook(args.output, read_only=False, data_only=False)
    expected_sheets = output_sheet_names
    if check.sheetnames != expected_sheets:
        raise RuntimeError("technical_or_unexpected_sheet_present")
    total_rows = 0
    total_amount = 0
    for sheet_name in check.sheetnames:
        sheet = check[sheet_name]
        header = tuple(sheet.cell(7, column).value for column in range(2, 9))
        if header != MANUAL_HEADERS:
            raise RuntimeError(f"manual_header_mismatch:{sheet_name}")
        if any(str(cell.value or "") in FORBIDDEN_HEADERS for row in sheet.iter_rows() for cell in row):
            raise RuntimeError(f"forbidden_header_present:{sheet_name}")
        data_end = sheet.max_row - 1
        if data_end < 8:
            raise RuntimeError(f"empty_trip_sheet:{sheet_name}")
        for row_index in range(8, data_end + 1):
            if sheet.cell(row_index, 2).value is None:
                raise RuntimeError(f"missing_date:{sheet_name}:{row_index}")
            if sheet.cell(row_index, 5).value and not _period_content_allowed(
                sheet.cell(row_index, 4).value
            ):
                raise RuntimeError(f"period_on_non_service_expense:{sheet_name}:{row_index}")
            total_rows += 1
            total_amount += int(sheet.cell(row_index, 8).value or 0)
        if sheet["B6"].value != "지출 내용" or sheet["B2"].value != "㈜숲길여행":
            raise RuntimeError(f"section_shape_mismatch:{sheet_name}")
        if f"C{sheet.max_row}:H{sheet.max_row}" not in {
            str(merged) for merged in sheet.merged_cells.ranges
        }:
            raise RuntimeError(f"total_row_merge_mismatch:{sheet_name}")
        if sheet.cell(sheet.max_row, 2).fill.fgColor.rgb != "FFFFFF00":
            raise RuntimeError(f"total_row_fill_mismatch:{sheet_name}")
        if sheet.cell(sheet.max_row, 2).font.color is None or sheet.cell(
            sheet.max_row, 2
        ).font.color.type != "rgb" or sheet.cell(sheet.max_row, 2).font.color.rgb != "FF000000":
            raise RuntimeError(f"total_row_font_color_mismatch:{sheet_name}")
        if sheet["B7"].font.name != OUTPUT_FONT_NAME or sheet["B7"].font.sz != OUTPUT_FONT_SIZE:
            raise RuntimeError(f"font_mismatch:{sheet_name}")
        if sheet["B7"].fill.fgColor.rgb != template["B26"].fill.fgColor.rgb:
            raise RuntimeError(f"fill_mismatch:{sheet_name}")
        if float(sheet.column_dimensions["E"].width or 0) < PERIOD_COLUMN_WIDTH:
            raise RuntimeError(f"period_column_too_narrow:{sheet_name}")
        if any(
            cell.value is not None
            and (cell.font.name != OUTPUT_FONT_NAME or cell.font.sz != OUTPUT_FONT_SIZE)
            for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, min_col=1, max_col=9)
            for cell in row
        ):
            raise RuntimeError(f"font_mismatch:{sheet_name}")
    check.close()
    if len(lineage_keys) + sum(excluded.values()) != len(raw_rows):
        raise RuntimeError("candidate_lineage_partition_mismatch")
    if total_rows != len(selected):
        raise RuntimeError(f"rendered_row_count_mismatch:{total_rows}!={len(selected)}")
    if sum(lane_counts.values()) != total_rows:
        raise RuntimeError("lane_render_count_mismatch")
    if lane_amounts.get("cancellation_refund", 0) != 0:
        raise RuntimeError("cancellation_refund_lane_not_zero_net")
    print("output", args.output)
    print("trip_sheets", len(expected_sheets))
    print("selected_rows", total_rows)
    print("selected_amount_krw", total_amount)
    print("lane_counts", dict(sorted(lane_counts.items())))
    print("lane_amounts", dict(sorted(lane_amounts.items())))
    print("nonzero_reversal_pairs", len(nonzero_reversal_parents))
    print(
        "cross_target_reversal_rows",
        sum(
            1
            for payment_id, target in display_target_by_payment.items()
            if target != base_target_by_payment.get(payment_id)
        ),
    )
    print("booking_links", link_diagnostics.get("linked", 0))
    print("booking_link_diagnostics", link_diagnostics)
    print("content_top", content_counts.most_common(12))
    print("excluded_rows", sum(excluded.values()))


if __name__ == "__main__":
    main()
