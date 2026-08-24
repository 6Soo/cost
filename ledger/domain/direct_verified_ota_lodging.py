"""Fail-closed promotion from authenticated Trip lodging mail facts.

The module deliberately keeps three claims separate:

* an authenticated booking fact is active only after booking-reference lifecycle checks;
* a trip target is accepted only by an exact schedule-region token and service date;
* a card set is classified only when the complete exact date/amount component closes.

For equal-amount M:N components, no individual card-to-booking pairing is asserted.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ledger.domain.direct_trip_schedule_authority import (
    END_SEMANTICS,
    EXCLUSIVE_SERVICE_END_SEMANTICS,
    normalize_service_period,
    sha256_value,
    validate_record,
)


FACT_ARTIFACT_TYPE = "trip-gmail-lodging-safe-facts-v2"
FACT_ACQUISITION_SCOPE = "authenticated_trip_hotel_targeted_cohort"
FACT_PARSER_CONTRACT = "trip-hotel-gmail-mime-v2"
FACT_PRIVACY_CONTRACT = "no_subject_body_name_pin_recipient_or_address_text"
AUTHORITY_CONTRACT = "trip-exact-lodging-authority-v2"
MANIFEST_CONTRACT = "direct-lodging-cohort-manifest-v2"
REGION_ALIAS_CONTRACT = "ota-target-region-alias-v1"
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")
STATIC_AXES = {"account": "숙박비", "cost_type": "여행원가"}

ROOT_KEYS = {
    "artifact_type", "acquisition_scope", "parser_contract", "privacy_contract",
    "record_count", "eligible_count", "withheld_count", "records",
    "record_set_sha256",
}
FACT_KEYS = {
    "provider", "message_id", "raw_mime_sha256", "message_class",
    "booking_ref", "property_name", "check_in", "check_out",
    "address_tokens", "address_evidence_sha256", "paid_total_krw",
    "refund_amount_krw", "mime_date_utc", "gmail_internal_date_utc",
    "seoul_sent_on", "from_contract", "aligned_dkim_domain",
    "auth_evidence_sha256", "parser_contract", "eligibility_status",
    "withheld_reasons", "fact_sha256",
}
FORBIDDEN_PRIVACY_KEYS = {
    "subject", "body", "html", "text", "pin", "recipient", "recipients",
    "to", "cc", "bcc", "guest", "guest_name", "traveler", "customer",
    "full_address", "address_text", "raw_address", "email",
}

# Exact issuer-specific merchant contracts.  These are equality checks, not
# substring, regex, fuzzy, or historical-label rules.
TRIP_MERCHANT_CONTRACTS = {
    "KBD": frozenset({"트립닷컴(구)_NICE"}),
    "KBO": frozenset({"TRIP.COM"}),
    "HAN": frozenset({"트립닷컴(ARS)_나이스", "트립닷컴_이니시스"}),
    "CORP": frozenset({"트립닷컴"}),
}

# These aliases are target-selection metadata only.  They never describe a
# card transaction and cannot enter promotion evidence.  The Taiwan fact uses
# the explicit Pingtung/Taiwan spelling from the authenticated reservation.
SERVICE_REGION_ALIASES = {
    "PINGTUNG": "대만",
    "PINGDUNG": "대만",
    "핑둥": "대만",
    "TAIWAN": "대만",
    "대만": "대만",
    # These are narrow service-region aliases for the 2026-04-14 Nagano
    # lodging cohort.  Do not broaden them to all of Nagano.
    "KOMAGANE": "나가센도",
    "고마가네": "나가센도",
    "코마가네": "나가센도",
    "KOUMI": "다테시나",
    "고우미": "다테시나",
    # Rebun is the only safe Hokkaido-area alias in this cohort.  Do not add
    # a broad Hokkaido alias: 2026-06-17..19 overlaps the 0613_북해도 trip.
    "REBUN": "레분토&리시리",
    "레분": "레분토&리시리",
}


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _canonical(value: object) -> bytes:
    def normalized(item: object) -> object:
        if isinstance(item, str):
            return _nfc(item)
        if isinstance(item, list):
            return [normalized(child) for child in item]
        if isinstance(item, dict):
            return {_nfc(str(key)): normalized(child) for key, child in item.items()}
        return item

    return json.dumps(
        normalized(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


REGION_ALIAS_SHA256 = _sha(SERVICE_REGION_ALIASES)


def _is_sha256(value: object, *, allow_empty: bool = False) -> bool:
    if allow_empty and value == "":
        return True
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_clean_text(value: object, *, maximum: int = 240) -> bool:
    return (
        isinstance(value, str) and value == _nfc(value) and value == value.strip()
        and 0 < len(value) <= maximum
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _iso_date(value: object, label: str) -> date:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"lodging_fact_{label}_invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"lodging_fact_{label}_invalid") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"lodging_fact_{label}_invalid")
    return parsed


def _utc_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"lodging_fact_{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"lodging_fact_{label}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"lodging_fact_{label}_invalid")
    return parsed


def _assert_privacy_shape(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_PRIVACY_KEYS:
                raise ValueError(f"lodging_fact_privacy_key_forbidden:{key}")
            _assert_privacy_shape(child)
    elif isinstance(value, list):
        for child in value:
            _assert_privacy_shape(child)


def validate_lodging_fact_record(raw: object) -> dict[str, object]:
    """Validate one safe fact and its self-address without trusting root counts."""
    if not isinstance(raw, dict) or set(raw) != FACT_KEYS:
        raise ValueError("ota_lodging_fact_record_schema_invalid")
    row = dict(raw)
    _assert_privacy_shape(row)
    if row["provider"] != "trip":
        raise ValueError("lodging_fact_provider_invalid")
    if not isinstance(row["message_id"], str) or re.fullmatch(
        r"[0-9a-f]{16}", row["message_id"]
    ) is None:
        raise ValueError("lodging_fact_message_id_invalid")
    if not _is_sha256(row["raw_mime_sha256"]):
        raise ValueError("lodging_fact_raw_mime_hash_invalid")
    if row["message_class"] not in {"confirmation", "cancel"}:
        raise ValueError("lodging_fact_message_class_invalid")
    if not isinstance(row["booking_ref"], str) or re.fullmatch(
        r"[0-9]{16}", row["booking_ref"]
    ) is None:
        raise ValueError("lodging_fact_booking_ref_invalid")
    if not _is_clean_text(row["property_name"]):
        raise ValueError("lodging_fact_property_invalid")
    check_in = _iso_date(row["check_in"], "check_in")
    check_out = _iso_date(row["check_out"], "check_out")
    if check_out <= check_in:
        raise ValueError("lodging_fact_service_period_invalid")
    tokens = row["address_tokens"]
    if (
        not isinstance(tokens, list) or not (1 <= len(tokens) <= 8)
        or len(tokens) != len(set(tokens))
        or any(not _is_clean_text(token, maximum=80) for token in tokens)
    ):
        raise ValueError("lodging_fact_address_tokens_invalid")
    if not _is_sha256(row["address_evidence_sha256"]):
        raise ValueError("lodging_fact_address_hash_invalid")
    paid = row["paid_total_krw"]
    refund = row["refund_amount_krw"]
    if row["message_class"] == "confirmation":
        if type(paid) is not int or paid <= 0 or refund is not None:
            raise ValueError("lodging_fact_confirmation_amount_invalid")
    elif type(refund) is not int or refund <= 0 or paid is not None:
        raise ValueError("lodging_fact_cancel_amount_invalid")
    mime_date = _utc_datetime(row["mime_date_utc"], "mime_date")
    internal_date = _utc_datetime(row["gmail_internal_date_utc"], "internal_date")
    if abs((mime_date - internal_date).total_seconds()) > 86400:
        raise ValueError("lodging_fact_message_date_divergence")
    seoul_date = _iso_date(row["seoul_sent_on"], "seoul_sent_on")
    if mime_date.astimezone(ZoneInfo("Asia/Seoul")).date() != seoul_date:
        raise ValueError("lodging_fact_seoul_date_mismatch")
    if row["from_contract"] != "KR_HTL_NoReply@trip.com":
        raise ValueError("lodging_fact_from_contract_invalid")
    if row["parser_contract"] != FACT_PARSER_CONTRACT:
        raise ValueError("lodging_fact_parser_contract_invalid")
    if row["eligibility_status"] not in {"eligible", "withheld"}:
        raise ValueError("lodging_fact_eligibility_invalid")
    reasons = row["withheld_reasons"]
    if (
        not isinstance(reasons, list) or len(reasons) != len(set(reasons))
        or any(not _is_clean_text(reason, maximum=100) for reason in reasons)
    ):
        raise ValueError("lodging_fact_withheld_reasons_invalid")
    if row["eligibility_status"] == "eligible":
        if (
            reasons or row["aligned_dkim_domain"] != "trip.com"
            or not _is_sha256(row["auth_evidence_sha256"])
        ):
            raise ValueError("lodging_fact_authenticated_eligibility_invalid")
    elif (
        not reasons
        or row["aligned_dkim_domain"] not in {"", "trip.com"}
        or not _is_sha256(row["auth_evidence_sha256"], allow_empty=True)
    ):
        raise ValueError("lodging_fact_withheld_contract_invalid")
    supplied_hash = row["fact_sha256"]
    if not _is_sha256(supplied_hash):
        raise ValueError("lodging_fact_hash_invalid")
    payload = dict(row)
    del payload["fact_sha256"]
    if _sha(payload) != supplied_hash:
        raise ValueError("lodging_fact_hash_mismatch")
    return row


def validate_lodging_fact_document(raw: object) -> dict[str, object]:
    """Validate the complete acquisition artifact, including every count/hash."""
    if not isinstance(raw, dict) or set(raw) != ROOT_KEYS:
        raise ValueError("ota_lodging_fact_root_schema_invalid")
    if (
        raw["artifact_type"] != FACT_ARTIFACT_TYPE
        or raw["acquisition_scope"] != FACT_ACQUISITION_SCOPE
        or raw["parser_contract"] != FACT_PARSER_CONTRACT
        or raw["privacy_contract"] != FACT_PRIVACY_CONTRACT
    ):
        raise ValueError("ota_lodging_fact_contract_invalid")
    rows = raw["records"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("ota_lodging_fact_records_invalid")
    validated = [validate_lodging_fact_record(row) for row in rows]
    message_ids = [str(row["message_id"]) for row in validated]
    fact_hashes = [str(row["fact_sha256"]) for row in validated]
    if len(message_ids) != len(set(message_ids)) or len(fact_hashes) != len(set(fact_hashes)):
        raise ValueError("ota_lodging_fact_identity_duplicate")
    eligible = sum(row["eligibility_status"] == "eligible" for row in validated)
    withheld = len(validated) - eligible
    if (
        type(raw["record_count"]) is not int
        or type(raw["eligible_count"]) is not int
        or type(raw["withheld_count"]) is not int
        or raw["record_count"] != len(validated)
        or raw["eligible_count"] != eligible
        or raw["withheld_count"] != withheld
    ):
        raise ValueError("ota_lodging_fact_count_mismatch")
    if raw["record_set_sha256"] != _sha(sorted(fact_hashes)):
        raise ValueError("ota_lodging_fact_record_set_hash_mismatch")
    return dict(raw)


def load_trip_schedule(db: object) -> dict[str, dict[str, object]]:
    """Load legacy schedule rows as *candidate* metadata only.

    This function is retained for candidate/audit code that needs to explain
    what the old ``mm/dd/window`` file would have suggested.  It must not be
    used by a promotion, allocation, or posting path.  Those paths use
    :func:`load_authoritative_trip_schedule` below.
    """
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records WHERE source_kind='trip_schedule'
           ORDER BY source_key"""
    ).fetchall()
    if not rows:
        raise ValueError("trip_schedule_source_missing")
    result: dict[str, dict[str, object]] = {}
    legacy_shape = {"tab", "mm", "dd", "region", "window"}
    explicit_shape = {
        "tab", "event_year", "starts_on", "ends_on", "region",
        "authority_kind", "authority_status", "end_semantics",
    }
    explicit_service_shape = {
        "tab", "event_year", "service_start_on", "service_end_on", "region",
        "authority_kind", "authority_status", "end_semantics",
    }
    for source_key, source_sha256, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("trip_schedule_payload_invalid") from exc
        if isinstance(payload, dict) and set(payload) in (
            explicit_shape, explicit_service_shape,
        ):
            continue
        if not isinstance(payload, dict) or set(payload) != legacy_shape:
            raise ValueError("trip_schedule_payload_invalid")
        if (
            not _is_clean_text(payload["tab"])
            or str(source_key) != payload["tab"]
            or not _is_clean_text(payload["region"])
            or type(payload["mm"]) is not int or type(payload["dd"]) is not int
            or type(payload["window"]) is not int
            or not 1 <= payload["window"] <= 60
            or not _is_sha256(str(source_sha256))
            or _sha(payload) != source_sha256
        ):
            raise ValueError("trip_schedule_contract_invalid")
        try:
            start = date(2026, payload["mm"], payload["dd"])
        except ValueError as exc:
            raise ValueError("trip_schedule_date_invalid") from exc
        if payload["tab"] in result:
            raise ValueError("trip_schedule_duplicate_target")
        result[str(payload["tab"])] = {
            **payload,
            # trips.json is the current 2026 schedule source.  Keep the
            # source payload/hash unchanged, but carry the year as a typed
            # derived field so consumers cannot silently rebuild a 2025
            # event from the same month/day template.
            "service_year": 2026,
            "starts_on": start.isoformat(),
            "ends_on": (start + timedelta(days=payload["window"] - 1)).isoformat(),
            "source_sha256": str(source_sha256),
        }
    return result


def load_authoritative_trip_schedule(
    db: object,
) -> dict[str, dict[str, object]]:
    """Load only explicit, content-addressed trip schedule authority.

    Legacy rows remain in the source table for auditability, but a row with
    only ``mm/dd/window`` is never upgraded here.  An authoritative row must
    carry explicit start/end dates and an explicit event year.  ``ends_on``
    is therefore a normalized field produced from the source schedule
    evidence, not a value inferred from a payment date or a user-facing
    activity window.
    """

    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records WHERE source_kind='trip_schedule'
           ORDER BY source_key"""
    ).fetchall()
    if not rows:
        raise ValueError("trip_schedule_source_missing")
    result: dict[str, dict[str, object]] = {}
    legacy_shape = {"tab", "mm", "dd", "region", "window"}
    explicit_shape = {
        "tab", "event_year", "starts_on", "ends_on", "region",
        "authority_kind", "authority_status", "end_semantics",
    }
    explicit_service_shape = {
        "tab", "event_year", "service_start_on", "service_end_on", "region",
        "authority_kind", "authority_status", "end_semantics",
    }
    for source_key, source_sha256, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("trip_schedule_payload_invalid") from exc
        if isinstance(payload, dict) and set(payload) == legacy_shape:
            # Candidate-only legacy input.  Do not silently turn its window
            # into an accounting period.
            continue
        if not isinstance(payload, dict) or set(payload) not in (
            explicit_shape, explicit_service_shape,
        ):
            raise ValueError("trip_schedule_authority_payload_invalid")
        if str(source_key) != str(payload["tab"]):
            raise ValueError("trip_schedule_authority_source_key_invalid")
        if not _is_sha256(source_sha256):
            raise ValueError("trip_schedule_authority_source_digest_invalid")
        if sha256_value(payload) != str(source_sha256):
            raise ValueError("trip_schedule_authority_payload_digest_invalid")
        if set(payload) == explicit_service_shape:
            if payload["end_semantics"] != EXCLUSIVE_SERVICE_END_SEMANTICS:
                raise ValueError("trip_schedule_authority_end_semantics_invalid")
            period = normalize_service_period(
                str(payload["service_start_on"]),
                str(payload["service_end_on"]),
            )
            starts_on = period.service_start_on.isoformat()
            ends_on = period.last_service_on.isoformat()
        else:
            if payload["end_semantics"] != END_SEMANTICS:
                raise ValueError("trip_schedule_authority_end_semantics_invalid")
            starts_on = payload["starts_on"]
            ends_on = payload["ends_on"]
        raw_record = {
            "trip_code": payload["tab"],
            "event_year": payload["event_year"],
            "starts_on": starts_on,
            "ends_on": ends_on,
            "region": payload["region"],
            "authority_kind": payload["authority_kind"],
            "source_locator": f"db://direct_source_records/trip_schedule/{source_key}",
            "source_sha256": str(source_sha256),
            "authority_status": payload["authority_status"],
            "end_semantics": END_SEMANTICS,
        }
        record = validate_record(raw_record)
        if not record.is_authoritative:
            continue
        if record.trip_code in result:
            raise ValueError("trip_schedule_authority_duplicate_target")
        inclusive_days = (record.ends_on - record.starts_on).days + 1
        result[record.trip_code] = {
            "tab": record.trip_code,
            "event_year": record.event_year,
            "service_year": record.event_year,
            "mm": record.starts_on.month,
            "dd": record.starts_on.day,
            "region": record.region,
            # Compatibility metadata for consumers that render a period.
            # This value is derived from explicit dates, never authoritative
            # input and never a matching authority by itself.
            "window": inclusive_days,
            "starts_on": record.starts_on.isoformat(),
            "ends_on": record.ends_on.isoformat(),
            "authority_kind": record.authority_kind,
            "authority_status": record.authority_status,
            "end_semantics": record.end_semantics,
            "source_kind": "trip_schedule",
            "source_sha256": str(source_sha256),
        }
    return result


def schedule_matches_for_date(
    db: object, occurred_on: str,
) -> list[dict[str, object]]:
    """Match a card/use date against explicit, year-bound schedule authority.

    This helper never turns an OTA payment date into a service date; callers
    must decide whether the event is a use-date purchase first.  Legacy
    month/day windows are intentionally absent from this lookup.
    """
    try:
        event_day = date.fromisoformat(str(occurred_on))
    except (TypeError, ValueError):
        return []
    templates = load_authoritative_trip_schedule(db)
    matches: list[dict[str, object]] = []
    for trip in templates.values():
        try:
            service_year = int(trip.get("service_year", 2026))
        except (TypeError, ValueError):
            raise ValueError("trip_schedule_service_year_invalid")
        if service_year != event_day.year:
            continue
        try:
            start = date.fromisoformat(str(trip["starts_on"]))
            end = date.fromisoformat(str(trip["ends_on"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("trip_schedule_date_invalid") from exc
        matches.append({
            **trip,
            "starts_on": start.isoformat(),
            "ends_on": end.isoformat(),
        }) if start <= event_day <= end else None
    return sorted(matches, key=lambda row: str(row["tab"]))


def _withhold(
    db: object, run_id: str, item_kind: str, item_key: str,
    reason_code: str, detail: object,
) -> None:
    db.execute(
        """INSERT OR IGNORE INTO direct_lodging_withheld(
             run_id,item_kind,item_key,reason_code,detail_sha256)
           VALUES (?,?,?,?,?)""",
        (run_id, item_kind, item_key, reason_code, _sha(detail)),
    )


def _target_for_fact(
    row: dict[str, object], schedule: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    period = normalize_service_period(
        str(row["check_in"]), str(row["check_out"]),
    )
    tokens = {_nfc(str(token)) for token in row["address_tokens"]}
    alias_hints = {
        SERVICE_REGION_ALIASES[key]
        for token in tokens
        for key in (str(token).upper(), str(token))
        if key in SERVICE_REGION_ALIASES
    }
    searchable_regions = tokens | {str(value) for value in alias_hints if value}
    return [
        trip for trip in schedule.values()
        if date.fromisoformat(str(trip["starts_on"])) <= period.service_start_on
        <= date.fromisoformat(str(trip["ends_on"]))
        and period.last_service_on <= date.fromisoformat(str(trip["ends_on"]))
        and (
            _nfc(str(trip["region"])) in searchable_regions
            or str(trip.get("region_alias")) in searchable_regions
        )
    ]


def prepare_external_lodging_facts(db: object, run_id: str) -> dict[str, int]:
    """Resolve authentication, booking lifecycle, and trip target before cards."""
    if db.execute(
        "SELECT COUNT(*) FROM direct_verified_lodging_facts WHERE run_id=?", (run_id,)
    ).fetchone()[0]:
        raise ValueError("lodging_external_facts_already_prepared")
    source_rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records WHERE source_kind='ota_lodging_fact'
           ORDER BY source_key"""
    ).fetchall()
    if not source_rows:
        raise ValueError("ota_lodging_fact_source_missing")
    from ledger.domain.direct_geographic_trip_context import (
        load_verified_trip_target_schedule,
    )
    schedule = load_verified_trip_target_schedule(db)
    rows_by_identity: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    source_meta: dict[str, tuple[str, str]] = {}
    source_withheld = 0
    for source_key, source_sha256, payload_json in source_rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("ota_lodging_fact_payload_invalid") from exc
        row = validate_lodging_fact_record(payload)
        if str(source_key) != row["message_id"] or _sha(row) != source_sha256:
            raise ValueError("ota_lodging_fact_source_binding_invalid")
        fact_id = "lodging-fact:" + str(row["fact_sha256"])
        source_meta[fact_id] = (str(source_key), str(source_sha256))
        rows_by_identity[(str(row["provider"]), str(row["booking_ref"]))].append(row)
        if row["eligibility_status"] == "withheld":
            for reason in row["withheld_reasons"]:
                _withhold(db, run_id, "external_fact", fact_id, str(reason), {
                    "fact_sha256": row["fact_sha256"], "reason": reason,
                })
            source_withheld += 1
            continue

    active = 0
    lifecycle_blocked = 0
    target_blocked = 0
    for identity in sorted(rows_by_identity):
        rows = rows_by_identity[identity]
        confirmations = [
            row for row in rows
            if row["message_class"] == "confirmation"
            and row["eligibility_status"] == "eligible"
        ]
        cancellations = [
            row for row in rows
            if row["message_class"] == "cancel"
            and row["eligibility_status"] == "eligible"
        ]
        unverified_cancellations = [
            row for row in rows
            if row["message_class"] == "cancel"
            and row["eligibility_status"] == "withheld"
        ]
        for cancellation in cancellations:
            fact_id = "lodging-fact:" + str(cancellation["fact_sha256"])
            _withhold(db, run_id, "external_fact", fact_id, "cancellation_notice", {
                "identity": identity, "fact_sha256": cancellation["fact_sha256"],
            })
        if cancellations:
            for confirmation in confirmations:
                fact_id = "lodging-fact:" + str(confirmation["fact_sha256"])
                _withhold(db, run_id, "external_fact", fact_id, "booking_ref_cancelled", {
                    "identity": identity,
                    "cancellation_fact_sha256": sorted(
                        str(row["fact_sha256"]) for row in cancellations
                    ),
                })
            lifecycle_blocked += len(confirmations)
            continue
        if unverified_cancellations:
            for confirmation in confirmations:
                fact_id = "lodging-fact:" + str(confirmation["fact_sha256"])
                _withhold(
                    db, run_id, "external_fact", fact_id,
                    "unverified_cancellation_conflict", {
                        "identity": identity,
                        "cancellation_fact_sha256": sorted(
                            str(row["fact_sha256"]) for row in unverified_cancellations
                        ),
                    },
                )
            lifecycle_blocked += len(confirmations)
            continue
        if not confirmations:
            continue
        if len(confirmations) != 1:
            for confirmation in confirmations:
                fact_id = "lodging-fact:" + str(confirmation["fact_sha256"])
                _withhold(db, run_id, "external_fact", fact_id, "multiple_confirmations", {
                    "identity": identity,
                    "confirmation_fact_sha256": sorted(
                        str(row["fact_sha256"]) for row in confirmations
                    ),
                })
            lifecycle_blocked += len(confirmations)
            continue
        confirmation = confirmations[0]
        fact_id = "lodging-fact:" + str(confirmation["fact_sha256"])
        targets = _target_for_fact(confirmation, schedule)
        if len(targets) != 1:
            _withhold(db, run_id, "external_fact", fact_id, "target_not_exactly_one", {
                "fact_sha256": confirmation["fact_sha256"],
                "exact_target_codes": sorted(str(row["tab"]) for row in targets),
            })
            target_blocked += 1
            continue
        target = targets[0]
        source_key, source_sha256 = source_meta[fact_id]
        fact_payload = {
            "provider": confirmation["provider"],
            "booking_ref": confirmation["booking_ref"],
            "property_name": confirmation["property_name"],
            "check_in": confirmation["check_in"],
            "check_out": confirmation["check_out"],
            "seoul_sent_on": confirmation["seoul_sent_on"],
            "paid_total_krw": confirmation["paid_total_krw"],
            "address_tokens": confirmation["address_tokens"],
            "source_fact_sha256": confirmation["fact_sha256"],
            "target_code": target["tab"],
            "target_region": target["region"],
            "target_source_kind": str(target.get("source_kind", "trip_schedule")),
            "trip_schedule_source_sha256": target["source_sha256"],
            "region_alias_contract": REGION_ALIAS_CONTRACT,
            "region_alias_sha256": REGION_ALIAS_SHA256,
            "lifecycle_status": "active",
            "target_rule": "exact_region_token_and_service_date",
        }
        db.execute(
            """INSERT INTO direct_verified_lodging_facts(
                 run_id,fact_id,source_kind,source_key,source_sha256,fact_sha256,
                 provider,booking_ref,property_name,check_in,check_out,seoul_sent_on,
                 paid_total_krw,target_code,account,cost_type,lifecycle_status,payload_json)
               VALUES (:run_id,:fact_id,'ota_lodging_fact',:source_key,:source_sha256,
                       :fact_sha256,:provider,:booking_ref,:property_name,:check_in,
                       :check_out,:seoul_sent_on,:paid_total_krw,:target_code,
                       '숙박비','여행원가','active',:payload_json)""",
            {
                "run_id": run_id, "fact_id": fact_id, "source_key": source_key,
                "source_sha256": source_sha256,
                "fact_sha256": confirmation["fact_sha256"],
                "provider": confirmation["provider"],
                "booking_ref": confirmation["booking_ref"],
                "property_name": confirmation["property_name"],
                "check_in": confirmation["check_in"],
                "check_out": confirmation["check_out"],
                "seoul_sent_on": confirmation["seoul_sent_on"],
                "paid_total_krw": confirmation["paid_total_krw"],
                "target_code": target["tab"],
                "payload_json": _canonical(fact_payload).decode("utf-8"),
            },
        )
        active += 1
    return {
        "source_records": len(source_rows),
        "source_withheld": source_withheld,
        "lifecycle_blocked_confirmations": lifecycle_blocked,
        "target_blocked_confirmations": target_blocked,
        "active_facts": active,
    }


def _verified_fact_rows(db: object, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT fact_id,source_key,source_sha256,fact_sha256,provider,booking_ref,
                  property_name,check_in,check_out,seoul_sent_on,paid_total_krw,
                  target_code,account,cost_type,lifecycle_status,payload_json
           FROM direct_verified_lodging_facts WHERE run_id=? ORDER BY fact_id""",
        (run_id,),
    ).fetchall()
    columns = (
        "fact_id", "source_key", "source_sha256", "fact_sha256", "provider",
        "booking_ref", "property_name", "check_in", "check_out", "seoul_sent_on",
        "paid_total_krw", "target_code", "account", "cost_type",
        "lifecycle_status", "payload_json",
    )
    result: list[dict[str, object]] = []
    for raw in rows:
        row = dict(zip(columns, raw))
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("verified_lodging_payload_invalid") from exc
        expected = {
            "provider": row["provider"], "booking_ref": row["booking_ref"],
            "property_name": row["property_name"], "check_in": row["check_in"],
            "check_out": row["check_out"], "seoul_sent_on": row["seoul_sent_on"],
            "paid_total_krw": row["paid_total_krw"],
            "address_tokens": payload.get("address_tokens"),
            "source_fact_sha256": row["fact_sha256"],
            "target_code": row["target_code"],
            "target_region": payload.get("target_region"),
            "target_source_kind": payload.get("target_source_kind"),
            "trip_schedule_source_sha256": payload.get("trip_schedule_source_sha256"),
            "region_alias_contract": payload.get("region_alias_contract"),
            "region_alias_sha256": payload.get("region_alias_sha256"),
            "lifecycle_status": "active",
            "target_rule": "exact_region_token_and_service_date",
        }
        if (
            payload != expected or row["provider"] != "trip"
            or row["account"] != "숙박비" or row["cost_type"] != "여행원가"
            or row["lifecycle_status"] != "active"
            or not _is_sha256(row["source_sha256"])
            or not _is_sha256(row["fact_sha256"])
        ):
            raise ValueError("verified_lodging_fact_contract_invalid")
        row["payload"] = payload
        result.append(row)
    return result


def _current_card_rows(db: object, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT pe.evidence_id,pe.direct_event_key,l.payment_id,p.external_key,
                  p.source_system,p.occurred_on,p.merchant,p.amount_krw,
                  p.transaction_type,e.identity_status,s.source_key,s.source_sha256,
                  s.payload_json
           FROM direct_promotion_evidence pe
           JOIN direct_normalized_payments d
             ON pe.direct_event_key=d.card_event_id || '#' || d.event_role
           JOIN direct_payment_projection_links l
             ON l.run_id=pe.run_id AND l.direct_payment_id=d.id
           JOIN payment_transactions p ON p.id=l.payment_id
           JOIN direct_card_events e ON e.source_record_id=d.source_record_id
           JOIN direct_source_records s ON s.id=d.source_record_id
           WHERE pe.run_id=? AND pe.evidence_kind='current_card'
             AND pe.authority_status='current_raw'
           ORDER BY pe.direct_event_key""",
        (run_id,),
    ).fetchall()
    columns = (
        "current_evidence_id", "direct_event_key", "payment_id", "external_key",
        "source_system", "occurred_on", "merchant", "amount_krw",
        "transaction_type", "identity_status", "source_key", "source_sha256",
        "payload_json",
    )
    result: list[dict[str, object]] = []
    for raw in rows:
        row = dict(zip(columns, raw))
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("lodging_current_card_payload_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("lodging_current_card_payload_invalid")
        row["payload"] = payload
        result.append(row)
    return result


def _kbo_group_key(row: dict[str, object]) -> tuple[str, str, str, str]:
    payload = row["payload"]
    return (
        str(payload.get("card4") or ""),
        str(payload.get("currency") or ""),
        str(payload.get("foreign") or "").strip().lstrip("-"),
        str(row["merchant"]),
    )


def _cancelled_payment_ids(
    db: object, run_id: str, current_rows: list[dict[str, object]],
) -> set[int]:
    linked = {
        int(row[0]) for row in db.execute(
            """SELECT DISTINCT r.related_transaction_id
               FROM transaction_relations r
               JOIN direct_payment_projection_links l ON l.payment_id=r.transaction_id
               WHERE l.run_id=? AND r.related_transaction_id IS NOT NULL
                 AND r.relation_type IN ('cancels','refunds')
                 AND r.relation_status NOT IN ('rejected','superseded')""",
            (run_id,),
        ).fetchall()
    }
    unordered_rows = db.execute(
        """SELECT p.merchant,s.payload_json
           FROM transaction_relations r
           JOIN direct_payment_projection_links l ON l.payment_id=r.transaction_id
           JOIN payment_transactions p ON p.id=r.transaction_id
           JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
           JOIN direct_source_records s ON s.id=d.source_record_id
           WHERE l.run_id=? AND r.related_transaction_id IS NULL
             AND r.match_method='kbo_card4_currency_foreign_merchant_unordered_group'
             AND r.relation_status NOT IN ('rejected','superseded')""",
        (run_id,),
    ).fetchall()
    unordered_keys: set[tuple[str, str, str, str]] = set()
    for merchant, payload_json in unordered_rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("lodging_cancellation_payload_invalid") from exc
        unordered_keys.add((
            str(payload.get("card4") or ""), str(payload.get("currency") or ""),
            str(payload.get("foreign") or "").strip().lstrip("-"), str(merchant),
        ))
    for row in current_rows:
        if (
            row["source_system"] == "KBO" and row["transaction_type"] == "purchase"
            and _kbo_group_key(row) in unordered_keys
        ):
            linked.add(int(row["payment_id"]))
    return linked


def _2025_mail_service_period_allowed(
    payment_date: object, service_start: object
) -> bool:
    """Apply the owner rule to this authenticated Trip service-mail path.

    Every fact consumed by this module is an authenticated Trip lodging mail,
    so it is an allowed mail evidence family.  A 2025 payment still needs the
    mail's explicit 2026 check-in/service year; the payment date itself is
    never used to manufacture that year.
    """

    try:
        payment_year = date.fromisoformat(str(payment_date)[:10]).year
        service_year = date.fromisoformat(str(service_start)[:10]).year
    except (TypeError, ValueError):
        return False
    return payment_year != 2025 or service_year == 2026


def _authority_models(
    db: object, run_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    facts = _verified_fact_rows(db, run_id)
    fact_buckets: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for fact in facts:
        fact_buckets[(str(fact["seoul_sent_on"]), int(fact["paid_total_krw"]))].append(fact)
    current_rows = _current_card_rows(db, run_id)
    cancelled = _cancelled_payment_ids(db, run_id, current_rows)
    card_buckets: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in current_rows:
        merchant_set = TRIP_MERCHANT_CONTRACTS.get(str(row["source_system"]), frozenset())
        if (
            row["transaction_type"] == "purchase" and int(row["amount_krw"]) > 0
            and str(row["merchant"]) in merchant_set
            and int(row["payment_id"]) not in cancelled
        ):
            card_buckets[(str(row["occurred_on"]), int(row["amount_krw"]))].append(row)

    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for match_key in sorted(fact_buckets):
        component_facts = sorted(fact_buckets[match_key], key=lambda row: str(row["fact_id"]))
        component_events = sorted(card_buckets.get(match_key, []), key=lambda row: str(row["direct_event_key"]))
        detail_base = {
            "match_key": [match_key[0], match_key[1]],
            "fact_ids": [str(row["fact_id"]) for row in component_facts],
            "event_keys": [str(row["direct_event_key"]) for row in component_events],
        }
        if len(component_facts) != len(component_events):
            for fact in component_facts:
                rejected.append({"item_kind": "external_fact", "item_key": fact["fact_id"],
                                 "reason_code": "component_cardinality_mismatch", "detail": detail_base})
            for event in component_events:
                rejected.append({"item_kind": "current_event", "item_key": event["direct_event_key"],
                                 "reason_code": "component_cardinality_mismatch", "detail": detail_base})
            rejected.append({"item_kind": "component", "item_key": "component:" + _sha(detail_base),
                             "reason_code": "component_cardinality_mismatch", "detail": detail_base})
            continue
        if len(component_facts) != 1:
            reason = "many_to_many_component_withheld"
            for fact in component_facts:
                rejected.append({"item_kind": "external_fact", "item_key": fact["fact_id"],
                                 "reason_code": reason, "detail": detail_base})
            for event in component_events:
                rejected.append({"item_kind": "current_event", "item_key": event["direct_event_key"],
                                 "reason_code": reason, "detail": detail_base})
            rejected.append({"item_kind": "component", "item_key": "component:" + _sha(detail_base),
                             "reason_code": reason, "detail": detail_base})
            continue
        if any(row["identity_status"] != "unique" for row in component_events):
            reason = "component_card_identity_not_unique"
            for fact in component_facts:
                rejected.append({"item_kind": "external_fact", "item_key": fact["fact_id"],
                                 "reason_code": reason, "detail": detail_base})
            for event in component_events:
                rejected.append({"item_kind": "current_event", "item_key": event["direct_event_key"],
                                 "reason_code": reason, "detail": detail_base})
            rejected.append({"item_kind": "component", "item_key": "component:" + _sha(detail_base),
                             "reason_code": reason, "detail": detail_base})
            continue
        invariant = {
            (
                str(row["property_name"]), str(row["check_in"]), str(row["check_out"]),
                str(row["account"]), str(row["cost_type"]), str(row["target_code"]),
            )
            for row in component_facts
        }
        if not component_facts or len(invariant) != 1:
            reason = "component_axis_or_stay_not_invariant"
            for fact in component_facts:
                rejected.append({"item_kind": "external_fact", "item_key": fact["fact_id"],
                                 "reason_code": reason, "detail": detail_base})
            for event in component_events:
                rejected.append({"item_kind": "current_event", "item_key": event["direct_event_key"],
                                 "reason_code": reason, "detail": detail_base})
            rejected.append({"item_kind": "component", "item_key": "component:" + _sha(detail_base),
                             "reason_code": reason, "detail": detail_base})
            continue
        property_name, check_in, check_out, account, cost_type, target_code = next(iter(invariant))
        if any(
            not _2025_mail_service_period_allowed(
                event.get("occurred_on"), check_in
            )
            for event in component_events
        ):
            reason = "2025_mail_service_period_not_2026"
            for fact in component_facts:
                rejected.append({"item_kind": "external_fact", "item_key": fact["fact_id"],
                                 "reason_code": reason, "detail": detail_base})
            for event in component_events:
                rejected.append({"item_kind": "current_event", "item_key": event["direct_event_key"],
                                 "reason_code": reason, "detail": detail_base})
            rejected.append({"item_kind": "component", "item_key": "component:" + _sha(detail_base),
                             "reason_code": reason, "detail": detail_base})
            continue
        event_descriptor = [
            {
                "direct_event_key": str(row["direct_event_key"]),
                "current_evidence_id": str(row["current_evidence_id"]),
                "source_system": str(row["source_system"]),
                "source_key": str(row["source_key"]),
                "source_sha256": str(row["source_sha256"]),
            }
            for row in component_events
        ]
        fact_descriptor = [
            {
                "fact_id": str(row["fact_id"]), "booking_ref": str(row["booking_ref"]),
                "fact_sha256": str(row["fact_sha256"]),
                "source_key": str(row["source_key"]),
                "source_sha256": str(row["source_sha256"]),
                "target_code": str(row["target_code"]),
                "target_source_kind": str(
                    row["payload"].get("target_source_kind", "trip_schedule")
                ),
                "trip_schedule_source_sha256": str(
                    row["payload"]["trip_schedule_source_sha256"]
                ),
                "region_alias_contract": str(
                    row["payload"].get("region_alias_contract", "")
                ),
                "region_alias_sha256": str(
                    row["payload"].get("region_alias_sha256", "")
                ),
            }
            for row in component_facts
        ]
        event_set_sha256 = _sha(event_descriptor)
        fact_set_sha256 = _sha(fact_descriptor)
        amount_multiset_sha256 = _sha({
            "card_amounts": sorted(int(row["amount_krw"]) for row in component_events),
            "fact_amounts": sorted(int(row["paid_total_krw"]) for row in component_facts),
        })
        kind = "unique"
        payload = {
            "contract": AUTHORITY_CONTRACT,
            "authority_kind": kind,
            "match_key": {"seoul_sent_on": match_key[0], "amount_krw": match_key[1]},
            "merchant_match": "issuer_specific_exact_equality",
            "events": event_descriptor,
            "facts": fact_descriptor,
            "property_name": property_name, "check_in": check_in, "check_out": check_out,
            "axes": {"account": account, "cost_type": cost_type,
                     "allocation_target": target_code},
            "event_set_sha256": event_set_sha256,
            "fact_set_sha256": fact_set_sha256,
            "amount_multiset_sha256": amount_multiset_sha256,
            "individual_card_booking_pair_asserted": kind == "unique",
        }
        authority_sha256 = _sha(payload)
        accepted.append({
            "authority_id": "lodging-authority:" + authority_sha256,
            "authority_sha256": authority_sha256,
            "authority_kind": kind,
            "event_set_sha256": event_set_sha256,
            "fact_set_sha256": fact_set_sha256,
            "amount_multiset_sha256": amount_multiset_sha256,
            "property_name": property_name, "check_in": check_in, "check_out": check_out,
            "account": account, "cost_type": cost_type,
            "allocation_target": target_code, "payload": payload,
            "events": component_events, "facts": component_facts,
        })
    return accepted, rejected


def project_verified_lodging_decisions(db: object, run_id: str) -> dict[str, int]:
    """Promote closed unique or axis-invariant lodging components."""
    authorities, rejected = _authority_models(db, run_id)
    db.execute("SAVEPOINT lodging_authority_projection")
    try:
        for item in rejected:
            _withhold(
                db, run_id, str(item["item_kind"]), str(item["item_key"]),
                str(item["reason_code"]), item["detail"],
            )
        decision_count = 0
        event_count = 0
        set_count = 0
        for authority in authorities:
            db.execute(
                """INSERT INTO direct_lodging_authorities(
                     run_id,authority_id,authority_kind,event_set_sha256,
                     fact_set_sha256,amount_multiset_sha256,authority_sha256,
                     event_count,fact_count,property_name,check_in,check_out,
                     account,cost_type,allocation_target,payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, authority["authority_id"], authority["authority_kind"],
                    authority["event_set_sha256"], authority["fact_set_sha256"],
                    authority["amount_multiset_sha256"], authority["authority_sha256"],
                    len(authority["events"]), len(authority["facts"]),
                    authority["property_name"], authority["check_in"], authority["check_out"],
                    authority["account"], authority["cost_type"],
                    authority["allocation_target"],
                    _canonical(authority["payload"]).decode("utf-8"),
                ),
            )
            for fact in authority["facts"]:
                db.execute(
                    """INSERT INTO direct_lodging_authority_facts(
                         run_id,authority_id,fact_id) VALUES (?,?,?)""",
                    (run_id, authority["authority_id"], fact["fact_id"]),
                )
            rule_id = AUTHORITY_CONTRACT
            rationale = (
                "인증된 Trip 숙박확정 한 건과 현재 카드 한 건의 날짜·금액이 정확히 일치함"
            )
            for event in authority["events"]:
                payment_id = int(event["payment_id"])
                existing = int(db.execute(
                    """SELECT COUNT(*) FROM current_classification_decisions
                       WHERE target_type='payment' AND target_id=?
                         AND dimension IN ('account','cost_type','allocation_target')""",
                    (payment_id,),
                ).fetchone()[0])
                if existing:
                    raise ValueError("lodging_existing_decision_conflict")
                db.execute(
                    """INSERT INTO direct_lodging_authority_events(
                         run_id,authority_id,direct_event_key,current_evidence_id,payment_id)
                       VALUES (?,?,?,?,?)""",
                    (
                        run_id, authority["authority_id"], event["direct_event_key"],
                        event["current_evidence_id"], payment_id,
                    ),
                )
                axes = {
                    "account": authority["account"],
                    "cost_type": authority["cost_type"],
                    "allocation_target": authority["allocation_target"],
                }
                for dimension in ACTIVE_DIMENSIONS:
                    value = str(axes[dimension])
                    derivation_id = "lodging-derivation:" + _sha({
                        "authority_id": authority["authority_id"],
                        "direct_event_key": event["direct_event_key"],
                        "dimension": dimension, "value": value,
                    })
                    decision_id = int(db.execute(
                        """INSERT INTO classification_decisions(
                             target_type,target_id,dimension,value,confidence,
                             confidence_label,decision_status,rule_id,rationale)
                           VALUES ('payment',?,?,?,?,?,'confirmed',?,?)""",
                        (
                            payment_id, dimension, value, 1.0, "독립원천검증",
                            rule_id, rationale,
                        ),
                    ).lastrowid)
                    db.execute(
                        """INSERT INTO direct_lodging_axis_derivations(
                             derivation_id,run_id,authority_id,payment_id,direct_event_key,
                             dimension,value,rule_id,current_evidence_id,
                             derivation_status,conflict_count)
                           VALUES (?,?,?,?,?,?,?,?,?,'pass',0)""",
                        (
                            derivation_id, run_id, authority["authority_id"], payment_id,
                            event["direct_event_key"], dimension, value, rule_id,
                            event["current_evidence_id"],
                        ),
                    )
                    db.execute(
                        """INSERT INTO direct_lodging_decision_bindings(
                             run_id,decision_id,derivation_id) VALUES (?,?,?)""",
                        (run_id, decision_id, derivation_id),
                    )
                    decision_count += 1
                event_count += 1
            set_count += authority["authority_kind"] == "axis_invariant_set"
    except Exception:
        db.execute("ROLLBACK TO lodging_authority_projection")
        db.execute("RELEASE lodging_authority_projection")
        raise
    else:
        db.execute("RELEASE lodging_authority_projection")
    return {
        "authorities": len(authorities), "set_authorities": int(set_count),
        "payments": event_count, "decisions": decision_count,
        "matching_withheld_items": len(rejected),
    }


def _authority_rationale(kind: str) -> str:
    del kind
    return "인증된 Trip 숙박확정 한 건과 현재 카드 한 건의 날짜·금액이 정확히 일치함"


def _validate_active_fact_sources(db: object, run_id: str) -> list[str]:
    issues: list[str] = []
    from ledger.domain.direct_geographic_trip_context import (
        load_verified_trip_target_schedule,
    )
    schedule = load_verified_trip_target_schedule(db)
    context_evidence_count = int(db.execute(
        """SELECT COUNT(*) FROM direct_promotion_evidence
           WHERE run_id=? AND source_kind='geographic_trip_context'""",
        (run_id,),
    ).fetchone()[0])
    if context_evidence_count:
        issues.append("geographic_context_promoted_as_evidence")
    active = _verified_fact_rows(db, run_id)
    source_rows = db.execute(
        """SELECT source_key,payload_json FROM direct_source_records
           WHERE source_kind='ota_lodging_fact' ORDER BY source_key"""
    ).fetchall()
    by_identity: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    by_message: dict[str, dict[str, object]] = {}
    for source_key, payload_json in source_rows:
        try:
            row = validate_lodging_fact_record(json.loads(str(payload_json)))
        except (TypeError, json.JSONDecodeError, ValueError) as exc:
            issues.append(f"source_fact_invalid:{source_key}:{exc}")
            continue
        by_message[str(source_key)] = row
        by_identity[(str(row["provider"]), str(row["booking_ref"]))].append(row)
    for fact in active:
        source = by_message.get(str(fact["source_key"]))
        identity = (str(fact["provider"]), str(fact["booking_ref"]))
        identity_rows = by_identity.get(identity, [])
        confirmations = [
            row for row in identity_rows
            if row["message_class"] == "confirmation"
            and row["eligibility_status"] == "eligible"
        ]
        cancellations = [row for row in identity_rows if row["message_class"] == "cancel"]
        if (
            source is None or source["message_class"] != "confirmation"
            or source["eligibility_status"] != "eligible"
            or source["fact_sha256"] != fact["fact_sha256"]
            or len(confirmations) != 1 or cancellations
        ):
            issues.append(f"active_fact_lifecycle_invalid:{fact['fact_id']}")
            continue
        targets = _target_for_fact(source, schedule)
        if len(targets) != 1 or targets[0]["tab"] != fact["target_code"]:
            issues.append(f"active_fact_target_invalid:{fact['fact_id']}")
            continue
        target = targets[0]
        expected_payload = {
            "provider": source["provider"],
            "booking_ref": source["booking_ref"],
            "property_name": source["property_name"],
            "check_in": source["check_in"],
            "check_out": source["check_out"],
            "seoul_sent_on": source["seoul_sent_on"],
            "paid_total_krw": source["paid_total_krw"],
            "address_tokens": source["address_tokens"],
            "source_fact_sha256": source["fact_sha256"],
            "target_code": target["tab"],
        "target_region": target["region"],
            "target_source_kind": str(target.get("source_kind", "trip_schedule")),
            "trip_schedule_source_sha256": target["source_sha256"],
            "region_alias_contract": REGION_ALIAS_CONTRACT,
            "region_alias_sha256": REGION_ALIAS_SHA256,
            "lifecycle_status": "active",
            "target_rule": "exact_region_token_and_service_date",
        }
        if fact["payload"] != expected_payload:
            issues.append(f"active_fact_payload_source_mismatch:{fact['fact_id']}")
    return issues


def validate_lodging_authorities(
    db: object, run_id: str, *, require_allocations: bool = False,
) -> dict[str, object]:
    """Recompute authorities from source/current evidence and compare every claim."""
    issues = _validate_active_fact_sources(db, run_id)
    try:
        expected, _ = _authority_models(db, run_id)
    except ValueError as exc:
        return {"passed": False, "issues": issues + [str(exc)]}

    expected_authorities = []
    expected_events = []
    expected_facts = []
    expected_decisions = []
    expected_allocations = []
    for authority in expected:
        expected_authorities.append((
            authority["authority_id"], authority["authority_kind"],
            authority["event_set_sha256"], authority["fact_set_sha256"],
            authority["amount_multiset_sha256"], authority["authority_sha256"],
            len(authority["events"]), len(authority["facts"]),
            authority["property_name"], authority["check_in"], authority["check_out"],
            authority["account"], authority["cost_type"], authority["allocation_target"],
            _canonical(authority["payload"]).decode("utf-8"),
        ))
        for fact in authority["facts"]:
            expected_facts.append((authority["authority_id"], fact["fact_id"]))
        for event in authority["events"]:
            expected_events.append((
                authority["authority_id"], event["direct_event_key"],
                event["current_evidence_id"], event["external_key"],
            ))
            axes = {
                "account": authority["account"], "cost_type": authority["cost_type"],
                "allocation_target": authority["allocation_target"],
            }
            for dimension in ACTIVE_DIMENSIONS:
                value = str(axes[dimension])
                derivation_id = "lodging-derivation:" + _sha({
                    "authority_id": authority["authority_id"],
                    "direct_event_key": event["direct_event_key"],
                    "dimension": dimension, "value": value,
                })
                expected_decisions.append((
                    authority["authority_id"], derivation_id, event["external_key"],
                    event["direct_event_key"], dimension, value, AUTHORITY_CONTRACT,
                    event["current_evidence_id"], "pass", 0, 1.0,
                    "독립원천검증", "confirmed", AUTHORITY_CONTRACT,
                    _authority_rationale(str(authority["authority_kind"])),
                ))
            expected_allocations.append((
                event["external_key"], authority["allocation_target"],
                int(event["amount_krw"]), 1, "confirmed", 1.0,
            ))

    actual_authorities = [tuple(row) for row in db.execute(
        """SELECT authority_id,authority_kind,event_set_sha256,fact_set_sha256,
                  amount_multiset_sha256,authority_sha256,event_count,fact_count,
                  property_name,check_in,check_out,account,cost_type,
                  allocation_target,payload_json
           FROM direct_lodging_authorities WHERE run_id=? ORDER BY authority_id""",
        (run_id,),
    ).fetchall()]
    actual_events = [tuple(row) for row in db.execute(
        """SELECT e.authority_id,e.direct_event_key,e.current_evidence_id,p.external_key
           FROM direct_lodging_authority_events e
           JOIN payment_transactions p ON p.id=e.payment_id
           WHERE e.run_id=? ORDER BY e.authority_id,e.direct_event_key""",
        (run_id,),
    ).fetchall()]
    actual_facts = [tuple(row) for row in db.execute(
        """SELECT authority_id,fact_id FROM direct_lodging_authority_facts
           WHERE run_id=? ORDER BY authority_id,fact_id""", (run_id,),
    ).fetchall()]
    actual_decisions = [tuple(row) for row in db.execute(
        """SELECT x.authority_id,x.derivation_id,p.external_key,x.direct_event_key,
                  x.dimension,x.value,x.rule_id,x.current_evidence_id,
                  x.derivation_status,x.conflict_count,d.confidence,
                  d.confidence_label,d.decision_status,d.rule_id,d.rationale
           FROM direct_lodging_axis_derivations x
           JOIN direct_lodging_decision_bindings b
             ON b.run_id=x.run_id AND b.derivation_id=x.derivation_id
           JOIN classification_decisions d ON d.id=b.decision_id
           JOIN payment_transactions p ON p.id=x.payment_id
           WHERE x.run_id=? AND d.target_type='payment' AND d.target_id=x.payment_id
             AND d.dimension=x.dimension AND d.value=x.value
           ORDER BY x.authority_id,x.direct_event_key,x.dimension""",
        (run_id,),
    ).fetchall()]
    comparisons = (
        ("authority_set_mismatch", sorted(expected_authorities), sorted(actual_authorities)),
        ("authority_event_set_mismatch", sorted(expected_events), sorted(actual_events)),
        ("authority_fact_set_mismatch", sorted(expected_facts), sorted(actual_facts)),
        ("lodging_decision_set_mismatch", sorted(expected_decisions), sorted(actual_decisions)),
    )
    for label, wanted, actual in comparisons:
        if wanted != actual:
            issues.append(label)

    promoted_rows = [tuple(row) for row in db.execute(
        """SELECT p.external_key,d.dimension,d.value
           FROM current_independently_promoted_decisions d
           JOIN direct_lodging_decision_bindings b
             ON b.run_id=d.run_id AND b.decision_id=d.id
           JOIN payment_transactions p ON p.id=d.target_id
           WHERE d.run_id=? ORDER BY p.external_key,d.dimension""",
        (run_id,),
    ).fetchall()]
    wanted_promoted = sorted(
        (row[2], row[4], row[5]) for row in expected_decisions
    )
    if promoted_rows != wanted_promoted:
        issues.append("independently_promoted_view_mismatch")
    bound_payment_ids = [int(row[0]) for row in db.execute(
        "SELECT payment_id FROM direct_lodging_authority_events WHERE run_id=?",
        (run_id,),
    ).fetchall()]
    if bound_payment_ids:
        placeholders = ",".join("?" for _ in bound_payment_ids)
        booking_links = int(db.execute(
            f"SELECT COUNT(*) FROM payment_booking_links WHERE payment_id IN ({placeholders})",
            tuple(bound_payment_ids),
        ).fetchone()[0])
        if booking_links:
            issues.append("individual_payment_booking_link_forbidden")

    if require_allocations:
        actual_allocations = [tuple(row) for row in db.execute(
            """SELECT p.external_key,t.code,a.amount_krw,ap.plan_version,
                      ap.plan_status,ap.confidence
               FROM direct_lodging_authority_events e
               JOIN payment_transactions p ON p.id=e.payment_id
               JOIN current_cost_allocations a ON a.payment_id=p.id
               JOIN allocation_plans ap ON ap.id=a.plan_id
               JOIN allocation_targets t ON t.id=a.target_id
               WHERE e.run_id=? ORDER BY p.external_key,t.code""",
            (run_id,),
        ).fetchall()]
        if sorted(expected_allocations) != actual_allocations:
            issues.append("lodging_allocation_set_mismatch")
    return {
        "passed": not issues,
        "issues": issues,
        "authority_count": len(expected_authorities),
        "set_authority_count": sum(row[1] == "axis_invariant_set" for row in expected_authorities),
        "promoted_payment_count": len(expected_events),
        "decision_count": len(expected_decisions),
    }


def _query_lists(db: object, sql: str, run_id: str) -> list[list[object]]:
    return [list(row) for row in db.execute(sql, (run_id,)).fetchall()]


def _manifest_state(db: object, run_id: str) -> dict[str, object]:
    """Build an acyclic state payload; the manifest table itself is excluded."""
    return {
        "inputs": _query_lists(db, """SELECT source_kind,relative_path,raw_sha256,
            lf_sha256,byte_count,key_set_sha256,record_count,parser_version
            FROM direct_projection_inputs WHERE run_id=?
            ORDER BY source_kind,relative_path""", run_id),
        "safe_sources": _query_lists(db, """SELECT source_kind,source_key,
            source_sha256,payload_json,redaction_version FROM direct_source_records
            WHERE source_kind IN ('trip_schedule','geographic_trip_context','ota_lodging_fact')
              AND EXISTS (SELECT 1 FROM direct_projection_runs WHERE run_id=?)
            ORDER BY source_kind,source_key""", run_id),
        "verified_facts": _query_lists(db, """SELECT fact_id,source_key,
            source_sha256,fact_sha256,provider,booking_ref,property_name,check_in,
            check_out,seoul_sent_on,paid_total_krw,target_code,account,cost_type,
            lifecycle_status,payload_json FROM direct_verified_lodging_facts
            WHERE run_id=? ORDER BY fact_id""", run_id),
        "authorities": _query_lists(db, """SELECT authority_id,authority_kind,
            event_set_sha256,fact_set_sha256,amount_multiset_sha256,authority_sha256,
            event_count,fact_count,property_name,check_in,check_out,account,cost_type,
            allocation_target,payload_json FROM direct_lodging_authorities
            WHERE run_id=? ORDER BY authority_id""", run_id),
        "authority_events": _query_lists(db, """SELECT e.authority_id,
            e.direct_event_key,e.current_evidence_id,p.external_key,pe.source_kind,
            pe.source_key,pe.source_sha256,pe.fact_sha256
            FROM direct_lodging_authority_events e
            JOIN payment_transactions p ON p.id=e.payment_id
            JOIN direct_promotion_evidence pe ON pe.run_id=e.run_id
              AND pe.evidence_id=e.current_evidence_id
            WHERE e.run_id=? ORDER BY e.authority_id,e.direct_event_key""", run_id),
        "authority_facts": _query_lists(db, """SELECT authority_id,fact_id
            FROM direct_lodging_authority_facts WHERE run_id=?
            ORDER BY authority_id,fact_id""", run_id),
        "derivations": _query_lists(db, """SELECT x.derivation_id,x.authority_id,
            p.external_key,x.direct_event_key,x.dimension,x.value,x.rule_id,
            x.current_evidence_id,x.derivation_status,x.conflict_count
            FROM direct_lodging_axis_derivations x
            JOIN payment_transactions p ON p.id=x.payment_id
            WHERE x.run_id=? ORDER BY x.derivation_id""", run_id),
        "decisions": _query_lists(db, """SELECT p.external_key,d.dimension,d.value,
            d.confidence,d.confidence_label,d.decision_status,d.rule_id,d.rationale,
            b.derivation_id FROM direct_lodging_decision_bindings b
            JOIN classification_decisions d ON d.id=b.decision_id
            JOIN payment_transactions p ON p.id=d.target_id
            WHERE b.run_id=? ORDER BY p.external_key,d.dimension""", run_id),
        "allocations": _query_lists(db, """SELECT p.external_key,ap.plan_version,
            ap.plan_status,ap.confidence,t.code,a.amount_krw,d.rule_id
            FROM direct_lodging_authority_events e
            JOIN payment_transactions p ON p.id=e.payment_id
            JOIN current_cost_allocations a ON a.payment_id=p.id
            JOIN allocation_plans ap ON ap.id=a.plan_id
            JOIN allocation_targets t ON t.id=a.target_id
            LEFT JOIN classification_decisions d ON d.id=ap.source_decision_id
            WHERE e.run_id=? ORDER BY p.external_key,t.code""", run_id),
        "withheld": _query_lists(db, """SELECT item_kind,item_key,reason_code,
            detail_sha256 FROM direct_lodging_withheld WHERE run_id=?
            ORDER BY item_kind,item_key,reason_code""", run_id),
    }


def finalize_lodging_manifest(db: object, run_id: str) -> dict[str, object]:
    if db.execute(
        "SELECT COUNT(*) FROM direct_lodging_cohort_manifests WHERE run_id=?", (run_id,)
    ).fetchone()[0]:
        raise ValueError("lodging_manifest_already_exists")
    state = _manifest_state(db, run_id)
    state_sha256 = _sha(state)
    run_input = db.execute(
        "SELECT input_manifest_sha256 FROM direct_projection_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if run_input is None:
        raise ValueError("lodging_manifest_run_missing")
    census = {key: len(rows) for key, rows in state.items()}
    set_hashes = {key + "_sha256": _sha(rows) for key, rows in state.items()}
    payload = {
        "artifact_type": MANIFEST_CONTRACT,
        "run_id": run_id,
        "input_manifest_sha256": str(run_input[0]),
        "state_sha256": state_sha256,
        "census": census,
        "set_hashes": set_hashes,
        "active_dimensions": list(ACTIVE_DIMENSIONS),
        "excluded_dimensions": ["vat_tag"],
        "manual_or_historical_evidence_used": False,
        "generic_amount_tolerance_used": False,
        "component_policy": "strict_one_to_one_only",
        "individual_pairing_claim_for_set_authority": False,
    }
    manifest_sha256 = _sha(payload)
    run_sha256 = _sha({"state_sha256": state_sha256,
                       "manifest_sha256": manifest_sha256})
    db.execute(
        """INSERT INTO direct_lodging_cohort_manifests(
             run_id,state_sha256,manifest_sha256,run_sha256,payload_json)
           VALUES (?,?,?,?,?)""",
        (run_id, state_sha256, manifest_sha256, run_sha256,
         _canonical(payload).decode("utf-8")),
    )
    return {**payload, "manifest_sha256": manifest_sha256, "run_sha256": run_sha256}


def validate_lodging_manifest(db: object, run_id: str) -> dict[str, object]:
    rows = db.execute(
        """SELECT state_sha256,manifest_sha256,run_sha256,payload_json
           FROM direct_lodging_cohort_manifests WHERE run_id=?""", (run_id,),
    ).fetchall()
    issues: list[str] = []
    if len(rows) != 1:
        return {"passed": False, "issues": ["lodging_manifest_cardinality_invalid"]}
    state_sha256, manifest_sha256, run_sha256, payload_json = rows[0]
    try:
        payload = json.loads(str(payload_json))
    except (TypeError, json.JSONDecodeError):
        return {"passed": False, "issues": ["lodging_manifest_payload_invalid"]}
    state = _manifest_state(db, run_id)
    expected_state = _sha(state)
    if state_sha256 != expected_state or payload.get("state_sha256") != expected_state:
        issues.append("lodging_manifest_state_hash_mismatch")
    if manifest_sha256 != _sha(payload):
        issues.append("lodging_manifest_hash_mismatch")
    if run_sha256 != _sha({"state_sha256": state_sha256,
                           "manifest_sha256": manifest_sha256}):
        issues.append("lodging_manifest_run_hash_mismatch")
    if payload.get("census") != {key: len(value) for key, value in state.items()}:
        issues.append("lodging_manifest_census_mismatch")
    if payload.get("set_hashes") != {
        key + "_sha256": _sha(value) for key, value in state.items()
    }:
        issues.append("lodging_manifest_set_hash_mismatch")
    if (
        payload.get("artifact_type") != MANIFEST_CONTRACT
        or payload.get("active_dimensions") != list(ACTIVE_DIMENSIONS)
        or payload.get("excluded_dimensions") != ["vat_tag"]
        or payload.get("manual_or_historical_evidence_used") is not False
        or payload.get("generic_amount_tolerance_used") is not False
        or payload.get("component_policy") != "strict_one_to_one_only"
        or payload.get("individual_pairing_claim_for_set_authority") is not False
    ):
        issues.append("lodging_manifest_policy_mismatch")
    return {"passed": not issues, "issues": issues,
            "state_sha256": expected_state, "manifest_sha256": manifest_sha256,
            "run_sha256": run_sha256}
