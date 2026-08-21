"""Build fail-closed, review-only current-card trip clusters.

The registry is intentionally separate from the canonical trip schedule.  A
cluster is only a classification hint: it never becomes an allocation target
or a transaction fact until the owner confirms it in a later workflow.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping


RULE_ID = "current-card-trip-cluster-registry-v1"
REGISTRY_VERSION = "current-card-trip-cluster-registry-v1"
REGISTRY_PATH = "current_card_trip_cluster_registry_exact"
ACTIVITY_PLACEHOLDER_RULE_ID = "current-card-travel-activity-placeholder-v1"
ACTIVITY_PLACEHOLDER_VERSION = "current-card-travel-activity-placeholder-v1"
UNKNOWN_MIXED_ACTIVITY_PLACEHOLDER_RULE_ID = (
    "current-card-travel-activity-placeholder-unknown-mixed-v1"
)
UNKNOWN_MIXED_ACTIVITY_PLACEHOLDER_VERSION = (
    "current-card-travel-activity-placeholder-unknown-mixed-v1"
)
ACTIVITY_PLACEHOLDER_PATH = "current_card_travel_activity_placeholder"
RESERVATION_PLACEHOLDER_RULE_ID = "current-card-reservation-placeholder-v1"
RESERVATION_PLACEHOLDER_VERSION = "current-card-reservation-placeholder-v1"
RESERVATION_PLACEHOLDER_PATH = "current_card_reservation_placeholder"
ACTIVITY_PLACEHOLDER_TARGET_KIND = "activity_placeholder"
RESERVATION_PLACEHOLDER_TARGET_KIND = "reservation_placeholder"

# An UNKNOWN activity placeholder is intentionally much narrower than the
# ordinary activity-window placeholder.  These bounds describe the only
# markerless cohort that may be lifted from the residual queue: a compact
# mixed-country parent run with one explicit country marker per country and a
# positive foreign-card amount on each selected markerless purchase.
UNKNOWN_MIXED_ACTIVITY_MAX_SPAN_DAYS = 3

# These are typed place names, not country-only markers.  Country codes are
# used only to attach a row to an already anchored region cluster.
REGION_COUNTRIES: dict[str, str] = {
    "AOMORI": "JP", "AKITA": "JP", "IWATE": "JP", "YAMAGATA": "JP",
    "FUKUSHIMA": "JP", "IBARAKI": "JP", "TOCHIGI": "JP",
    "GUNMA": "JP", "SAITAMA": "JP", "CHIBA": "JP", "TOKYO": "JP",
    "KANAGAWA": "JP", "YAMANASHI": "JP", "NAGANO": "JP",
    "NIIGATA": "JP", "TOYAMA": "JP", "ISHIKAWA": "JP", "FUKUI": "JP",
    "GIFU": "JP", "SHIZUOKA": "JP", "AICHI": "JP", "NAGOYA": "JP",
    "MIE": "JP", "SHIGA": "JP", "KYOTO": "JP", "OSAKA": "JP",
    "HYOGO": "JP", "NARA": "JP", "WAKAYAMA": "JP", "TOTTORI": "JP",
    "SHIMANE": "JP", "OKAYAMA": "JP", "HIROSHIMA": "JP",
    "YAMAGUCHI": "JP", "TOKUSHIMA": "JP", "KAGAWA": "JP",
    "EHIME": "JP", "KOCHI": "JP", "FUKUOKA": "JP", "SAGA": "JP",
    "NAGASAKI": "JP", "KUMAMOTO": "JP", "OITA": "JP",
    "MIYAZAKI": "JP", "KAGOSHIMA": "JP", "OKINAWA": "JP",
    "HOKKAIDO": "JP", "SAPPORO": "JP", "KUSHIRO": "JP",
    "CHIANGMAI": "TH", "BANGKOK": "TH", "PHUKET": "TH",
    "PATTAYA": "TH", "AYUTTHAYA": "TH",
    "TAIPEI": "TW", "TAICHUNG": "TW", "TAINAN": "TW",
    "TAITUNG": "TW", "NANTOU": "TW", "HUALIEN": "TW",
    "HUALIAN": "TW", "KAOHSIUNG": "TW", "PINGTUNG": "TW",
    "PARIS": "FR", "LYON": "FR", "LONDON": "GB", "ROME": "IT",
    "MILAN": "IT", "MADRID": "ES", "BARCELONA": "ES",
    "SINGAPORE": "SG", "HANOI": "VN", "HOCHIMINH": "VN",
    "NEWYORK": "US", "LOSANGELES": "US", "SANFRANCISCO": "US",
    "VANCOUVER": "CA", "SYDNEY": "AU", "MELBOURNE": "AU",
}

REGION_LABELS: dict[str, str] = {
    "AOMORI": "아오모리", "AKITA": "아키타", "IWATE": "이와테",
    "YAMAGATA": "야마가타", "FUKUSHIMA": "후쿠시마", "IBARAKI": "이바라키",
    "TOCHIGI": "도치기", "GUNMA": "군마", "CHIBA": "치바",
    "TOKYO": "도쿄", "KANAGAWA": "가나가와", "YAMANASHI": "야마나시",
    "NAGANO": "나가노", "NIIGATA": "니가타", "TOYAMA": "도야마",
    "ISHIKAWA": "이시카와", "FUKUI": "후쿠이", "GIFU": "기후",
    "SHIZUOKA": "시즈오카", "AICHI": "아이치", "NAGOYA": "나고야",
    "MIE": "미에", "SHIGA": "시가", "KYOTO": "교토", "OSAKA": "오사카",
    "HYOGO": "효고", "NARA": "나라", "WAKAYAMA": "와카야마",
    "OKAYAMA": "오카야마", "HIROSHIMA": "히로시마", "YAMAGUCHI": "야마구치",
    "TOKUSHIMA": "도쿠시마", "KAGAWA": "가가와", "EHIME": "에히메",
    "KOCHI": "고치", "FUKUOKA": "후쿠오카", "SAGA": "사가",
    "NAGASAKI": "나가사키", "KUMAMOTO": "구마모토", "OITA": "오이타",
    "MIYAZAKI": "미야자키", "KAGOSHIMA": "가고시마", "OKINAWA": "오키나와",
    "HOKKAIDO": "홋카이도", "SAPPORO": "삿포로", "KUSHIRO": "구시로",
    "CHIANGMAI": "치앙마이", "BANGKOK": "방콕", "PHUKET": "푸껫",
    "PATTAYA": "파타야", "AYUTTHAYA": "아유타야",
    "TAIPEI": "대만", "TAICHUNG": "대만", "TAINAN": "대만",
    "TAITUNG": "대만", "NANTOU": "대만", "HUALIEN": "대만",
    "HUALIAN": "대만", "KAOHSIUNG": "대만", "PINGTUNG": "대만",
}
for _name in REGION_COUNTRIES:
    REGION_LABELS.setdefault(_name, _name.lower())

COUNTRY_CODES = frozenset(REGION_COUNTRIES.values())
COUNTRY_LABELS = {
    "JP": "일본", "TW": "대만", "TH": "태국", "SG": "싱가포르",
    "VN": "베트남", "CA": "캐나다", "AU": "호주", "GB": "영국",
    "FR": "프랑스", "IT": "이탈리아", "ES": "스페인", "US": "미국",
}
WRAPPER_TOKENS = frozenset({
    "NICE", "NICESHOP", "KCP", "KICC", "INICIS", "ARS", "PG",
    "PAYCO", "PAYMENT", "PAYMENTS", "TOSS", "PAYMENTS", "ONLINE",
    "PREPAID", "OVERSEAS", "FOREIGN", "CARD", "VISA", "MASTER",
})
# A branch/location suffix is not a second merchant.  Keep this list limited
# to unmistakable chain stems so unrelated merchants are never collapsed by
# a fuzzy substring rule.
MERCHANT_CHAIN_STEMS = (
    "FAMILYMART", "LAWSON", "SUSHIRO", "ENEOS", "SEVENELEVEN",
    "TOYOKOINN", "MAXVALU", "AEON", "MCDONALDS", "SUKIYA",
    "YOSHINOYA", "RINGERHUT", "STARBUCKS",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).upper()


def _tokens(value: object) -> tuple[str, ...]:
    raw = _text(value)
    return tuple(
        token for token in re.findall(r"[A-Z]+|[가-힣]+", raw)
        if token
    )


def normalize_actual_merchant(row: Mapping[str, object]) -> str:
    """Return a stable merchant identity after removing payment wrappers."""
    raw = row.get("merchant") or row.get("relation_merchant") or row.get("biz")
    parts = [
        token for token in _tokens(raw)
        if token not in WRAPPER_TOKENS and token not in COUNTRY_CODES
    ]
    compact = "".join(parts)
    # A location suffix is not a second merchant.  This also handles raw
    # feeds that omit spaces, such as FAMILYMARTTOKYOJP.
    for token in REGION_COUNTRIES:
        compact = compact.replace(token, "")
    for token in ("도쿄", "오사카", "교토", "대만", "방콕", "치앙마이"):
        compact = compact.replace(token, "")
    for stem in sorted(MERCHANT_CHAIN_STEMS, key=len, reverse=True):
        if compact.startswith(stem):
            return stem
    return compact


def _region_hits(row: Mapping[str, object]) -> list[tuple[str, str, str]]:
    text = " ".join(
        str(row.get(field) or "")
        for field in ("merchant", "relation_merchant", "biz")
    )
    tokens = set(_tokens(text))
    hits: list[tuple[str, str, str]] = []
    for token, country in REGION_COUNTRIES.items():
        if token in tokens:
            hits.append((country, token, REGION_LABELS[token]))
    # Korean place aliases are kept explicit to retain token boundaries.
    aliases = {
        "도쿄": ("JP", "TOKYO", "도쿄"),
        "오사카": ("JP", "OSAKA", "오사카"),
        "교토": ("JP", "KYOTO", "교토"),
        "대만": ("TW", "TAIWAN", "대만"),
        "방콕": ("TH", "BANGKOK", "방콕"),
        "치앙마이": ("TH", "CHIANGMAI", "치앙마이"),
    }
    for alias, value in aliases.items():
        if alias in text:
            hits.append(value)
    deduped = sorted(set(hits))
    return deduped


def _country_marker(row: Mapping[str, object]) -> str:
    hits = _region_hits(row)
    countries = {item[0] for item in hits}
    if len(countries) == 1:
        return next(iter(countries))
    tokens = set(_tokens(
        " ".join(str(row.get(field) or "") for field in (
            "merchant", "relation_merchant", "biz",
        ))
    ))
    explicit = sorted(tokens & COUNTRY_CODES)
    if len(explicit) == 1:
        return explicit[0]
    # A currency is only an attachment hint here.  It can never start a
    # cluster, and ambiguous currencies such as USD/EUR are deliberately not
    # mapped to a country.
    return {
        "JPY": "JP", "THB": "TH", "TWD": "TW", "SGD": "SG",
        "VND": "VN", "CAD": "CA", "AUD": "AU", "GBP": "GB",
    }.get(_text(row.get("currency")), "")


def _direct_country_marker(row: Mapping[str, object]) -> str:
    """Return only a country explicitly present in the merchant text.

    Currency is intentionally excluded.  A currency can attach to an already
    anchored strict cluster, but it can never create a location or a new
    activity placeholder.
    """
    hits = _region_hits(row)
    countries = {item[0] for item in hits}
    if len(countries) == 1:
        return next(iter(countries))
    tokens = set(_tokens(
        " ".join(str(row.get(field) or "") for field in (
            "merchant", "relation_merchant", "biz",
        ))
    ))
    explicit = sorted(tokens & COUNTRY_CODES)
    return explicit[0] if len(explicit) == 1 else ""


def _event_date(row: Mapping[str, object]) -> date | None:
    try:
        return date.fromisoformat(str(row.get("occurred_on") or ""))
    except (TypeError, ValueError):
        return None


def _schedule_region_matches(region: str, schedule_region: object) -> bool:
    left_raw = _text(region).replace(" ", "")
    right_raw = _text(schedule_region).replace(" ", "")
    left = _text(REGION_LABELS.get(left_raw, left_raw)).replace(" ", "")
    right = _text(REGION_LABELS.get(right_raw, right_raw)).replace(" ", "")
    return bool(left and right and (left == right or left in right or right in left))


def _schedule_candidates(
    starts_on: date,
    ends_on: date,
    country: str,
    region: str,
    schedules: Iterable[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], bool]:
    period_matches: list[Mapping[str, object]] = []
    overlap_matches: list[Mapping[str, object]] = []
    for trip in schedules:
        try:
            service_year = int(trip.get("service_year", 2026))
            if service_year != starts_on.year and service_year != ends_on.year:
                continue
            start = date(
                service_year, int(trip["mm"]), int(trip["dd"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        end = start + timedelta(days=int(trip["window"]) - 1)
        if start <= ends_on and starts_on <= end:
            overlap_matches.append({
                **dict(trip),
                "starts_on": start.isoformat(),
                "ends_on": end.isoformat(),
            })
        if start <= starts_on and ends_on <= end:
            period_matches.append(overlap_matches[-1])
    period_matches.sort(key=lambda item: str(item.get("tab")))
    overlap_matches.sort(key=lambda item: str(item.get("tab")))
    if not overlap_matches:
        return [], False

    def compatible(trip: Mapping[str, object]) -> bool:
        schedule_country = ""
        for token, known in REGION_COUNTRIES.items():
            if _schedule_region_matches(token, trip.get("region")):
                schedule_country = known
                break
        return not (
            (schedule_country and schedule_country != country)
            or not _schedule_region_matches(region, trip.get("region"))
        )

    # Any overlapping schedule for a different region is a contradiction,
    # even when it only covers one edge of the card cluster.  This prevents a
    # partial date overlap from silently producing a new temporary target.
    if any(not compatible(trip) for trip in overlap_matches):
        return [], True
    if len(period_matches) > 1:
        return [], True
    return period_matches, False


def _eligible(row: Mapping[str, object]) -> bool:
    return (
        str(row.get("transaction_type") or "") == "purchase"
        and int(row.get("amount_krw") or 0) > 0
        and str(row.get("sub") or "") == "해외"
        and bool(str(row.get("source") or "").strip())
        and bool(str(row.get("card4") or "").strip())
        and _event_date(row) is not None
    )


def _placeholder_purchase_eligible(row: Mapping[str, object]) -> bool:
    return (
        str(row.get("transaction_type") or "") == "purchase"
        and int(row.get("amount_krw") or 0) > 0
        and bool(str(row.get("source") or "").strip())
        and bool(str(row.get("card4") or "").strip())
        and _event_date(row) is not None
    )


def _placeholder_reversal_eligible(row: Mapping[str, object]) -> bool:
    """Return whether a negative current-card row can be a review member.

    A reversal placeholder is only a classification proposal.  It records the
    current-card reversal fact and its payment window, never a service period
    or an inferred original purchase.
    """
    return (
        str(row.get("transaction_type") or "") in {"cancellation", "refund"}
        and int(row.get("amount_krw") or 0) < 0
        and bool(str(row.get("source") or "").strip())
        and bool(str(row.get("card4") or "").strip())
        and _event_date(row) is not None
    )


def _cluster_runs(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    rows = sorted(rows, key=lambda row: str(row["occurred_on"]))
    runs: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for row in rows:
        day = _event_date(row)
        if day is None:
            continue
        if not current:
            current = [row]
            continue
        previous = _event_date(current[-1])
        first = _event_date(current[0])
        assert previous is not None and first is not None
        if (day - previous).days <= 2 and (day - first).days <= 7:
            current.append(row)
        else:
            runs.append(current)
            current = [row]
    if current:
        runs.append(current)
    return runs


def _positive_foreign_activity_signal(row: Mapping[str, object]) -> bool:
    """Require a foreign-card amount before lifting an UNKNOWN row.

    ``sub=해외`` is a residual classification hint, not evidence that a
    markerless row was an on-site foreign purchase.  The raw card fact must
    also carry a positive foreign-currency amount and a non-KRW currency.
    Provider, gateway, OTA, and manual-conflict filtering remains the
    classifier's responsibility before this registry is called.
    """
    currency = _text(row.get("currency")).strip()
    if not currency or currency == "KRW":
        return False
    try:
        foreign_amount = Decimal(
            _text(row.get("foreign")).replace(",", "").strip()
        )
    except (InvalidOperation, ValueError):
        return False
    return foreign_amount > 0


def _unknown_mixed_parent_markerless_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[tuple[list[dict[str, object]], list[dict[str, object]]]]:
    """Return only markerless rows from a narrow mixed-country parent run.

    The parent run is the exact run rejected by the ordinary activity builder:
    same source/card, at least two explicit countries, one explicit marker per
    country, a markerless majority, and a compact use-date span.  A singleton
    or an unrelated markerless run can therefore never become an UNKNOWN
    placeholder through this path.  The parent run is returned alongside its
    markerless rows so its selection contract can be included in the registry
    hash payload.
    """
    selected: list[tuple[list[dict[str, object]], list[dict[str, object]]]] = []
    for run in _placeholder_runs(rows):
        explicit_rows = [row for row in run if _direct_country_marker(row)]
        markerless_rows = [
            row for row in run if not _direct_country_marker(row)
        ]
        countries = {
            _direct_country_marker(row) for row in explicit_rows
        }
        dates = [_event_date(row) for row in run]
        valid_dates = [value for value in dates if value is not None]
        if (
            len(countries) < 2
            or len(explicit_rows) != len(countries)
            or len(markerless_rows) <= len(explicit_rows)
            or not markerless_rows
            or len(valid_dates) != len(run)
            or (max(valid_dates) - min(valid_dates)).days
            > UNKNOWN_MIXED_ACTIVITY_MAX_SPAN_DAYS
            or not all(
                _positive_foreign_activity_signal(row)
                for row in markerless_rows
            )
        ):
            continue
        selected.append((run, markerless_rows))
    return sorted(
        selected,
        key=lambda item: str(item[0][0].get("direct_event_key") or ""),
    )


def build_trip_cluster_registry(
    rows: Iterable[Mapping[str, object]],
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Return strict provisional cluster records and payment membership.

    Country-only rows are attached after a region anchor is found.  They can
    never create a cluster by themselves.
    """
    context_rows = [dict(row) for row in context_schedule]
    eligible = [dict(row) for row in rows if _eligible(row)]
    explicit: list[dict[str, object]] = []
    country_only: list[dict[str, object]] = []
    for row in eligible:
        hits = _region_hits(row)
        if len(hits) == 1:
            country, token, label = hits[0]
            explicit.append({
                **row, "_country": country, "_region_token": token,
                "_region": label,
                "_merchant_identity": normalize_actual_merchant(row),
            })
        else:
            country = _country_marker(row)
            if country:
                country_only.append({**row, "_country": country})

    grouped: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in explicit:
        merchant_identity = str(row.get("_merchant_identity") or "")
        if not merchant_identity:
            continue
        key = (
            str(row["source"]), str(row["card4"]),
            str(row["_country"]), str(row["_region"]),
        )
        grouped[key].append(row)

    schedules = [*canonical_schedule.values(), *context_rows]
    candidate_clusters: list[dict[str, object]] = []
    for (source, card4, country, region), group in sorted(grouped.items()):
        for run in _cluster_runs(group):
            dates = {_event_date(row) for row in run}
            merchants = {
                str(row.get("_merchant_identity") or "") for row in run
            }
            anchor_merchants = {
                str(row.get("_merchant_identity") or "") for row in run
                if row.get("_region_token")
            }
            if len(dates) < 2 or len(run) < 3 or len(merchants) < 2:
                continue
            if len(anchor_merchants) < 2:
                continue
            starts_on = min(day for day in dates if day is not None)
            ends_on = max(day for day in dates if day is not None)
            attached = [
                row for row in country_only
                if str(row.get("source")) == source
                and str(row.get("card4")) == card4
                and str(row.get("_country")) == country
                and starts_on <= _event_date(row) <= ends_on
            ]
            members = sorted(
                [*run, *attached],
                key=lambda row: str(row["direct_event_key"]),
            )
            schedule_matches, schedule_conflict = _schedule_candidates(
                starts_on, ends_on, country, region, schedules,
            )
            if schedule_conflict:
                continue
            target = (
                str(schedule_matches[0]["tab"])
                if schedule_matches else
                f"임시여행_{starts_on.strftime('%Y%m%d')}_{region}_"
                f"{_sha([str(row['current_fact_sha256']) for row in members])[:8]}"
            )
            identity_sha = _sha({"source": source, "card4": card4})
            event_keys = sorted(str(row["direct_event_key"]) for row in members)
            fact_shas = sorted(str(row["current_fact_sha256"]) for row in members)
            core = {
                "registry_version": REGISTRY_VERSION,
                "rule_id": RULE_ID,
                "source_system": source,
                "card_identity_sha256": identity_sha,
                "country": country,
                "region": region,
                "starts_on": starts_on.isoformat(),
                "ends_on": ends_on.isoformat(),
                "target_code": target,
                "event_keys": event_keys,
                "fact_shas": fact_shas,
                "target_kind": (
                    "context_schedule"
                    if schedule_matches and str(
                        schedule_matches[0].get("source_kind") or ""
                    ) == "geographic_trip_context"
                    else "canonical_schedule" if schedule_matches
                    else "new_registry_target"
                ),
            }
            registry_id = "trip-cluster:" + _sha(core)
            candidate_clusters.append({
                **core,
                "registry_id": registry_id,
                "registry_sha256": _sha(core),
                "members": members,
                "payload_json": _canonical(core).decode("utf-8"),
            })

    # A single card cannot be in two countries at overlapping dates.  Remove
    # both clusters when that contradiction appears.
    conflicted: set[str] = set()
    for left_index, left in enumerate(candidate_clusters):
        for right in candidate_clusters[left_index + 1:]:
            if left["source_system"] != right["source_system"]:
                continue
            left_identity = str(left["card_identity_sha256"])
            if left_identity != str(right["card_identity_sha256"]):
                continue
            if left["country"] == right["country"]:
                continue
            if not (
                str(left["starts_on"]) <= str(right["ends_on"])
                and str(right["starts_on"]) <= str(left["ends_on"])
            ):
                continue
            conflicted.update({str(left["registry_id"]), str(right["registry_id"])})

    payment_registry_ids: dict[int, set[str]] = defaultdict(set)
    for registry in candidate_clusters:
        for row in registry["members"]:
            payment_registry_ids[int(row["payment_id"])].add(
                str(registry["registry_id"])
            )
    for registry_ids in payment_registry_ids.values():
        if len(registry_ids) > 1:
            conflicted.update(registry_ids)

    registries = [
        item for item in candidate_clusters
        if str(item["registry_id"]) not in conflicted
    ]
    registries.sort(key=lambda item: str(item["registry_id"]))
    by_payment: dict[int, dict[str, object]] = {}
    for registry in registries:
        for row in registry["members"]:
            payment_id = int(row["payment_id"])
            if payment_id in by_payment:
                raise ValueError("trip_cluster_payment_membership_conflict")
            by_payment[payment_id] = registry
    return {
        "registries": registries,
        "by_payment": by_payment,
        "conflicted_registry_count": len(conflicted),
        "rule_id": RULE_ID,
        "registry_version": REGISTRY_VERSION,
    }


def _placeholder_member_audit(
    members: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "payment_id": int(row["payment_id"]),
            "direct_event_key": str(row["direct_event_key"]),
            "current_evidence_id": str(row["current_evidence_id"]),
            "current_fact_sha256": str(row["current_fact_sha256"]),
            "source_system": str(row.get("source") or ""),
            "card_identity_sha256": _sha({
                "source": str(row.get("source") or ""),
                "card4": str(row.get("card4") or ""),
            }),
            "occurred_on": str(row.get("occurred_on") or ""),
            "amount_krw": int(row.get("amount_krw") or 0),
        }
        for row in sorted(
            members, key=lambda item: str(item["direct_event_key"])
        )
    ]


def _placeholder_registry(
    members: list[dict[str, object]],
    *,
    path: str,
    rule_id: str,
    registry_version: str,
    target_kind: str,
    target_code: str,
    source_system: str,
    card4: str,
    country: str,
    region: str,
    starts_on: date,
    ends_on: date,
    target_completeness: str,
    service_period_status: str,
    schedule_snapshot_sha256: str,
    selection_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    event_keys = sorted(str(row["direct_event_key"]) for row in members)
    fact_shas = sorted(str(row["current_fact_sha256"]) for row in members)
    core = {
        "registry_version": registry_version,
        "rule_id": rule_id,
        "source_system": source_system,
        "card_identity_sha256": _sha({
            "source": source_system, "card4": card4,
        }),
        "country": country,
        "region": region,
        "starts_on": starts_on.isoformat(),
        "ends_on": ends_on.isoformat(),
        "target_code": target_code,
        "event_keys": event_keys,
        "fact_shas": fact_shas,
        "target_kind": target_kind,
    }
    selection_context_sha256 = (
        _sha(selection_context) if selection_context is not None else None
    )
    if selection_context_sha256 is not None:
        core["selection_context_sha256"] = selection_context_sha256
    registry_sha256 = _sha(core)
    audit = {
        "classification_path": path,
        "target_completeness": target_completeness,
        "service_period_status": service_period_status,
        "payment_window_is_not_service_period": True,
        "individual_match_asserted": False,
        "manual_classification_only": False,
        "currency_used_to_create_country": False,
        "schedule_snapshot_sha256": schedule_snapshot_sha256,
        "member_count": len(members),
        "member_audit": _placeholder_member_audit(members),
    }
    if selection_context is not None:
        audit["selection_context"] = dict(selection_context)
        audit["selection_context_sha256"] = selection_context_sha256
    return {
        **core,
        "classification_path": path,
        "schedule_status": "not_applicable",
        "registry_id": "trip-cluster:" + registry_sha256,
        "registry_sha256": registry_sha256,
        "members": sorted(
            members, key=lambda row: str(row["direct_event_key"])
        ),
        "payload_json": _canonical({
            "registry_core": core,
            "audit": audit,
        }).decode("utf-8"),
    }


def _placeholder_schedule_snapshot_sha256(
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]],
) -> str:
    schedules = [
        {
            "tab": str(item.get("tab") or ""),
            "mm": item.get("mm"),
            "dd": item.get("dd"),
            "window": item.get("window"),
            "region": str(item.get("region") or ""),
            "source_kind": str(item.get("source_kind") or "canonical"),
        }
        for item in [*canonical_schedule.values(), *context_schedule]
    ]
    return _sha(sorted(schedules, key=lambda item: str(item["tab"])))


def _placeholder_runs(
    rows: Iterable[Mapping[str, object]],
) -> list[list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for source_row in rows:
        row = dict(source_row)
        if not _eligible(row):
            continue
        grouped[
            (str(row.get("source") or ""), str(row.get("card4") or ""))
        ].append(row)
    runs: list[list[dict[str, object]]] = []
    for key in sorted(grouped):
        runs.extend(_cluster_runs(grouped[key]))
    return runs


def build_travel_activity_placeholder_registry(
    rows: Iterable[Mapping[str, object]],
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build review-only placeholders for direct overseas activity.

    This registry proves only that current-card activity occurred in a bounded
    use-date window.  It deliberately does not assert a service period or a
    canonical trip target.  A run containing explicit countries from more than
    one country is discarded rather than forced into one destination.
    """
    context_rows = [dict(row) for row in context_schedule]
    schedule_sha = _placeholder_schedule_snapshot_sha256(
        canonical_schedule, context_rows,
    )
    registries: list[dict[str, object]] = []
    for run in _placeholder_runs(rows):
        registry = _activity_placeholder_registry_for_run(
            run, schedule_sha,
        )
        if registry is not None:
            registries.append(registry)
    by_payment: dict[int, dict[str, object]] = {}
    for registry in registries:
        for row in registry["members"]:
            payment_id = int(row["payment_id"])
            if payment_id in by_payment:
                raise ValueError("travel_activity_placeholder_membership_conflict")
            by_payment[payment_id] = registry
    return {
        "registries": sorted(registries, key=lambda item: str(item["registry_id"])),
        "by_payment": by_payment,
        "conflicted_registry_count": 0,
        "rule_id": ACTIVITY_PLACEHOLDER_RULE_ID,
        "registry_version": ACTIVITY_PLACEHOLDER_VERSION,
    }


def _activity_placeholder_registry_for_run(
    run: list[dict[str, object]],
    schedule_sha: str,
    *,
    rule_id: str = ACTIVITY_PLACEHOLDER_RULE_ID,
    registry_version: str = ACTIVITY_PLACEHOLDER_VERSION,
    selection_context: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    countries = {
        _direct_country_marker(row)
        for row in run
        if _direct_country_marker(row)
    }
    if len(countries) > 1:
        return None
    country = next(iter(countries), "UNKNOWN")
    regions = {
        hit[2]
        for row in run
        for hit in _region_hits(row)
        if hit[0] == country
    }
    region = next(iter(regions), "미상") if len(regions) == 1 else "미상"
    dates = [_event_date(row) for row in run]
    valid_dates = [value for value in dates if value is not None]
    if len(valid_dates) != len(run):
        return None
    first = min(valid_dates)
    last = max(valid_dates)
    label = region if region != "미상" else COUNTRY_LABELS.get(
        country, "해외미상"
    )
    fact_hashes = [str(row["current_fact_sha256"]) for row in run]
    member_hash = _sha(
        sorted(fact_hashes) if selection_context is not None else fact_hashes
    )[:10]
    target_code = (
        f"임시여행활동_{first.strftime('%Y%m%d')}_{label}_{member_hash}"
    )
    return _placeholder_registry(
        run,
        path=ACTIVITY_PLACEHOLDER_PATH,
        rule_id=rule_id,
        registry_version=registry_version,
        target_kind=ACTIVITY_PLACEHOLDER_TARGET_KIND,
        target_code=target_code,
        source_system=str(run[0].get("source") or ""),
        card4=str(run[0].get("card4") or ""),
        country=country,
        region=region,
        starts_on=first,
        ends_on=last,
        target_completeness="activity_only",
        service_period_status="not_applicable_current_use_window_only",
        schedule_snapshot_sha256=schedule_sha,
        selection_context=selection_context,
    )


def build_split_travel_activity_placeholder_registry(
    rows: Iterable[Mapping[str, object]],
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Keep direct country markers when one card window spans countries.

    The normal activity builder rejects a mixed-country payment window as one
    contradiction.  For the high-coverage review queue, an explicitly named
    country is still useful when it is separated from the other country: emit
    one provisional activity target per explicit country.  Markerless rows
    are admitted only from a compact, mixed-country parent run with a
    positive foreign-card amount; each such row gets its own ``UNKNOWN``
    registry so the rows are never asserted to be one activity.  Singleton
    markerless rows and unrelated runs remain unassigned.
    """
    source_rows = [dict(row) for row in rows]
    context_rows = [dict(row) for row in context_schedule]
    base = build_travel_activity_placeholder_registry(
        source_rows, canonical_schedule, context_rows,
    )
    registries = list(base["registries"])
    by_payment = dict(base["by_payment"])
    remaining = [
        row for row in source_rows
        if int(row["payment_id"]) not in by_payment
    ]
    by_country: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in remaining:
        country = _direct_country_marker(row)
        if country:
            by_country[country].append(row)
    for country in sorted(by_country):
        state = build_travel_activity_placeholder_registry(
            by_country[country], canonical_schedule, context_schedule,
        )
        for registry in state["registries"]:
            registries.append(registry)
            for member in registry["members"]:
                payment_id = int(member["payment_id"])
                if payment_id in by_payment:
                    raise ValueError(
                        "travel_activity_placeholder_split_membership_conflict"
                    )
                by_payment[payment_id] = registry
    schedule_sha = _placeholder_schedule_snapshot_sha256(
        canonical_schedule, context_rows,
    )
    for parent_run, unknown_rows in _unknown_mixed_parent_markerless_rows(
        source_rows
    ):
        countries = sorted({
            _direct_country_marker(row)
            for row in parent_run
            if _direct_country_marker(row)
        })
        parent_dates = [
            _event_date(row) for row in parent_run
            if _event_date(row) is not None
        ]
        selection_context = {
            "selection_kind": "mixed_country_parent_run_markerless_purchase",
            "parent_event_keys": sorted(
                str(row["direct_event_key"]) for row in parent_run
            ),
            "parent_fact_shas": sorted(
                str(row["current_fact_sha256"]) for row in parent_run
            ),
            "explicit_countries": countries,
            "explicit_marker_count": len(countries),
            "markerless_member_count": len(unknown_rows),
            "parent_span_days": (
                max(parent_dates) - min(parent_dates)
            ).days if parent_dates else None,
            "positive_foreign_amount_required": True,
        }
        for row in unknown_rows:
            registry = _activity_placeholder_registry_for_run(
                [row],
                schedule_sha,
                rule_id=UNKNOWN_MIXED_ACTIVITY_PLACEHOLDER_RULE_ID,
                registry_version=UNKNOWN_MIXED_ACTIVITY_PLACEHOLDER_VERSION,
                selection_context=selection_context,
            )
            if registry is None:
                continue
            registries.append(registry)
            for member in registry["members"]:
                payment_id = int(member["payment_id"])
                if payment_id in by_payment:
                    raise ValueError(
                        "travel_activity_placeholder_unknown_membership_conflict"
                    )
                by_payment[payment_id] = registry
    return {
        **base,
        "registries": sorted(
            registries, key=lambda item: str(item["registry_id"])
        ),
        "by_payment": by_payment,
    }


def build_reservation_placeholder_registry(
    rows: Iterable[Mapping[str, object]],
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build one review-only placeholder per travel-type payment.

    Provider, airfare, and travel-product merchant strings are not treated as
    destinations.  The payment day is retained only as a payment window, and
    the service period remains explicitly unknown.
    """
    context_rows = [dict(row) for row in context_schedule]
    schedule_sha = _placeholder_schedule_snapshot_sha256(
        canonical_schedule, context_rows,
    )
    registries: list[dict[str, object]] = []
    for source_row in sorted(
        (dict(row) for row in rows),
        key=lambda row: str(row["direct_event_key"]),
    ):
        if not _placeholder_purchase_eligible(source_row):
            continue
        event_day = _event_date(source_row)
        if event_day is None:
            continue
        member_hash = _sha({
            "payment_id": int(source_row["payment_id"]),
            "current_fact_sha256": str(source_row["current_fact_sha256"]),
        })[:12]
        target_code = f"임시예약_{member_hash}_행사기간미상"
        registries.append(_placeholder_registry(
            [source_row],
            path=RESERVATION_PLACEHOLDER_PATH,
            rule_id=RESERVATION_PLACEHOLDER_RULE_ID,
            registry_version=RESERVATION_PLACEHOLDER_VERSION,
            target_kind=RESERVATION_PLACEHOLDER_TARGET_KIND,
            target_code=target_code,
            source_system=str(source_row.get("source") or ""),
            card4=str(source_row.get("card4") or ""),
            country="UNKNOWN",
            region="미상",
            starts_on=event_day,
            ends_on=event_day,
            target_completeness="reservation_only",
            service_period_status="unknown_not_payment_date",
            schedule_snapshot_sha256=schedule_sha,
        ))
    by_payment = {
        int(registry["members"][0]["payment_id"]): registry
        for registry in registries
    }
    return {
        "registries": sorted(registries, key=lambda item: str(item["registry_id"])),
        "by_payment": by_payment,
        "conflicted_registry_count": 0,
        "rule_id": RESERVATION_PLACEHOLDER_RULE_ID,
        "registry_version": RESERVATION_PLACEHOLDER_VERSION,
    }


def build_reversal_reservation_placeholder_registry(
    rows: Iterable[Mapping[str, object]],
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build one review-only reservation placeholder per direct reversal.

    The target is deliberately distinct from the original purchase.  Without
    an exact current-card relation, a refund/cancellation cannot inherit an
    original target; it can only be labeled as a travel-type reversal awaiting
    owner confirmation.
    """
    context_rows = [dict(row) for row in context_schedule]
    schedule_sha = _placeholder_schedule_snapshot_sha256(
        canonical_schedule, context_rows,
    )
    registries: list[dict[str, object]] = []
    for source_row in sorted(
        (dict(row) for row in rows),
        key=lambda row: str(row["direct_event_key"]),
    ):
        if not _placeholder_reversal_eligible(source_row):
            continue
        event_day = _event_date(source_row)
        if event_day is None:
            continue
        member_hash = _sha({
            "payment_id": int(source_row["payment_id"]),
            "current_fact_sha256": str(source_row["current_fact_sha256"]),
        })[:12]
        target_code = f"임시예약환불_{member_hash}_행사기간미상"
        registries.append(_placeholder_registry(
            [source_row],
            path=RESERVATION_PLACEHOLDER_PATH,
            rule_id=RESERVATION_PLACEHOLDER_RULE_ID,
            registry_version=RESERVATION_PLACEHOLDER_VERSION,
            target_kind=RESERVATION_PLACEHOLDER_TARGET_KIND,
            target_code=target_code,
            source_system=str(source_row.get("source") or ""),
            card4=str(source_row.get("card4") or ""),
            country="UNKNOWN",
            region="미상",
            starts_on=event_day,
            ends_on=event_day,
            target_completeness="reservation_reversal_only",
            service_period_status="unknown_not_payment_date",
            schedule_snapshot_sha256=schedule_sha,
        ))
    by_payment = {
        int(registry["members"][0]["payment_id"]): registry
        for registry in registries
    }
    return {
        "registries": sorted(registries, key=lambda item: str(item["registry_id"])),
        "by_payment": by_payment,
        "conflicted_registry_count": 0,
        "rule_id": RESERVATION_PLACEHOLDER_RULE_ID,
        "registry_version": RESERVATION_PLACEHOLDER_VERSION,
    }


def build_reversal_activity_placeholder_registry(
    rows: Iterable[Mapping[str, object]],
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build bounded activity placeholders for direct overseas reversals.

    Rows are grouped by source, card, and actual merchant over the existing
    short payment window.  The grouping is only a review convenience; it does
    not assert that the reversals cancel those merchant purchases.
    """
    context_rows = [dict(row) for row in context_schedule]
    schedule_sha = _placeholder_schedule_snapshot_sha256(
        canonical_schedule, context_rows,
    )
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for source_row in rows:
        row = dict(source_row)
        if not _placeholder_reversal_eligible(row):
            continue
        grouped[
            (
                str(row.get("source") or ""),
                str(row.get("card4") or ""),
                normalize_actual_merchant(row),
            )
        ].append(row)
    registries: list[dict[str, object]] = []
    for key in sorted(grouped):
        for run in _cluster_runs(grouped[key]):
            if not run:
                continue
            countries = {
                _direct_country_marker(row)
                for row in run
                if _direct_country_marker(row)
            }
            if len(countries) > 1:
                continue
            country = next(iter(countries), "UNKNOWN")
            regions = {
                hit[2]
                for row in run
                for hit in _region_hits(row)
                if hit[0] == country
            }
            region = next(iter(regions), "미상") if len(regions) == 1 else "미상"
            first = _event_date(run[0])
            last = _event_date(run[-1])
            if first is None or last is None:
                continue
            label = region if region != "미상" else COUNTRY_LABELS.get(
                country, "해외미상"
            )
            member_hash = _sha([
                str(row["current_fact_sha256"]) for row in run
            ])[:10]
            target_code = (
                f"임시여행활동환불_{first.strftime('%Y%m%d')}_"
                f"{label}_{member_hash}"
            )
            registries.append(_placeholder_registry(
                run,
                path=ACTIVITY_PLACEHOLDER_PATH,
                rule_id=ACTIVITY_PLACEHOLDER_RULE_ID,
                registry_version=ACTIVITY_PLACEHOLDER_VERSION,
                target_kind=ACTIVITY_PLACEHOLDER_TARGET_KIND,
                target_code=target_code,
                source_system=key[0],
                card4=key[1],
                country=country,
                region=region,
                starts_on=first,
                ends_on=last,
                target_completeness="activity_reversal_only",
                service_period_status="not_applicable_payment_window_only",
                schedule_snapshot_sha256=schedule_sha,
            ))
    by_payment: dict[int, dict[str, object]] = {}
    for registry in registries:
        for row in registry["members"]:
            payment_id = int(row["payment_id"])
            if payment_id in by_payment:
                raise ValueError("reversal_activity_placeholder_membership_conflict")
            by_payment[payment_id] = registry
    return {
        "registries": sorted(registries, key=lambda item: str(item["registry_id"])),
        "by_payment": by_payment,
        "conflicted_registry_count": 0,
        "rule_id": ACTIVITY_PLACEHOLDER_RULE_ID,
        "registry_version": ACTIVITY_PLACEHOLDER_VERSION,
    }


def build_split_reversal_activity_placeholder_registry(
    rows: Iterable[Mapping[str, object]],
    canonical_schedule: Mapping[str, Mapping[str, object]],
    context_schedule: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Apply the explicit-country split rule to overseas reversals too.

    A mixed-country reversal window is not evidence that one reversal belongs
    to one destination.  It is still safe to create separate review-only
    activity targets for rows whose merchant explicitly names a country; rows
    without such a marker remain outside the placeholder registry.
    """
    source_rows = [dict(row) for row in rows]
    base = build_reversal_activity_placeholder_registry(
        source_rows, canonical_schedule, context_schedule,
    )
    registries = list(base["registries"])
    by_payment = dict(base["by_payment"])
    remaining = [
        row for row in source_rows
        if int(row["payment_id"]) not in by_payment
    ]
    by_country: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in remaining:
        country = _direct_country_marker(row)
        if country:
            by_country[country].append(row)
    for country in sorted(by_country):
        state = build_reversal_activity_placeholder_registry(
            by_country[country], canonical_schedule, context_schedule,
        )
        for registry in state["registries"]:
            registries.append(registry)
            for member in registry["members"]:
                payment_id = int(member["payment_id"])
                if payment_id in by_payment:
                    raise ValueError(
                        "reversal_activity_placeholder_split_membership_conflict"
                    )
                by_payment[payment_id] = registry
    return {
        **base,
        "registries": sorted(
            registries, key=lambda item: str(item["registry_id"])
        ),
        "by_payment": by_payment,
    }


def registry_manifest(registry: Mapping[str, object]) -> dict[str, object]:
    return {
        key: registry[key]
        for key in (
            "registry_id", "registry_sha256", "target_code", "target_kind",
            "source_system", "card_identity_sha256", "country", "region",
            "starts_on", "ends_on", "event_keys", "fact_shas", "rule_id",
        )
    }
