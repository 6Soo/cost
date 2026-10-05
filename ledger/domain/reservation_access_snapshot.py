"""Strict parser for Reservation -> COST access snapshots.

The document contains only the stable Reservation person identity, display
labels and exact COST trip codes needed to synchronize viewer access.  It is a
complete directory snapshot and every person's assignment list is complete.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from typing import Mapping

def _strict_json_bytes(raw_bytes, label):
    def unique_pairs(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise ValueError(f'{label}_duplicate_key:{key}')
            result[key]=value
        return result
    try:
        return json.loads(raw_bytes.decode('utf-8'),object_pairs_hook=unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ValueError(f'{label}_nonfinite:{value}')))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ValueError(f'{label}_json_invalid') from exc


SCHEMA_VERSION = "reservation-access-snapshot-v1"
ROOT_KEYS = {"schema_version", "exported_at", "snapshot_revision", "persons"}
PERSON_KEYS = {
    "reservation_person_id",
    "display_name",
    "nickname",
    "is_active",
    "assignments",
}
MAX_SAFE_INTEGER = 9_007_199_254_740_991

# Display labels are shown in the access UI and in owner decisions, so they
# get the tightest cap. Stable ids and trip codes only need a sanity cap that
# stops a corrupt export from becoming a huge row.
DISPLAY_NAME_MAX_LEN = 100
TEXT_MAX_LEN = 200


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def check_label_text(value: object, field: str, *, allow_empty: bool = False,
                     max_len: int = TEXT_MAX_LEN) -> str:
    """Validate a human-visible label or a stable id.

    Newlines were the only thing refused before, so a tab, a bell or a
    zero-width control could pass the parser and reach the access UI or the
    owner decision list. Every Unicode control (category Cc: ``\\n``, ``\\r``,
    ``\\t``, ``\\x00``-``\\x1f``, ``\\x7f``-``\\x9f``) is now refused, and the
    stripped value must fit the cap. Raises the same ``ValueError`` shape the
    parser already uses so every caller maps it the same way.
    """
    if not isinstance(value, str):
        raise ValueError(f"reservation_access_{field}_invalid")
    value = value.strip()
    if not allow_empty and not value:
        raise ValueError(f"reservation_access_{field}_invalid")
    if len(value) > max_len:
        raise ValueError(f"reservation_access_{field}_too_long")
    for char in value:
        if unicodedata.category(char) == "Cc":
            raise ValueError(f"reservation_access_{field}_invalid")
    return value


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    return check_label_text(value, field, allow_empty=allow_empty)


def _revision(value: object) -> int:
    if type(value) is not int or value < 0 or value > MAX_SAFE_INTEGER:
        raise ValueError("reservation_access_snapshot_revision_invalid")
    return value


def _exported_at(value: object) -> str:
    text = _text(value, "exported_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reservation_access_exported_at_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("reservation_access_exported_at_invalid")
    return text


def _load_raw(raw: bytes | str | Mapping[str, object]) -> dict[str, object]:
    if isinstance(raw, bytes):
        value = _strict_json_bytes(raw, "reservation_access_snapshot")
    elif isinstance(raw, str):
        value = _strict_json_bytes(raw.encode("utf-8"), "reservation_access_snapshot")
    elif isinstance(raw, Mapping):
        value = dict(raw)
    else:
        raise ValueError("reservation_access_snapshot_root_invalid")
    if not isinstance(value, dict) or set(value) != ROOT_KEYS:
        raise ValueError("reservation_access_snapshot_root_invalid")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("reservation_access_schema_version_invalid")
    return value


def stable_document(snapshot: Mapping[str, object]) -> dict[str, object]:
    """Return the content identity, excluding transport time/revision."""
    persons = [dict(person) for person in snapshot["persons"]]
    persons.sort(key=lambda person: str(person["reservation_person_id"]).encode("utf-8"))
    for person in persons:
        person["assignments"] = sorted(person["assignments"], key=lambda value: value.encode("utf-8"))
    return {"schema_version": snapshot["schema_version"], "persons": persons}


def stable_digest(snapshot: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(stable_document(snapshot)).encode("utf-8")).hexdigest()


def parse_reservation_access_snapshot(
    raw: bytes | str | Mapping[str, object],
) -> dict[str, object]:
    value = _load_raw(raw)
    exported_at = _exported_at(value["exported_at"])
    revision = _revision(value["snapshot_revision"])

    parsed_time = datetime.fromisoformat(exported_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    expected_revision = int(parsed_time.timestamp() * 1000)
    if revision != expected_revision:
        raise ValueError("reservation_access_revision_time_mismatch")

    if not isinstance(value["persons"], list):
        raise ValueError("reservation_access_persons_invalid")

    person_ids: set[str] = set()
    nicknames: set[str] = set()
    persons: list[dict[str, object]] = []
    for raw_person in value["persons"]:
        if not isinstance(raw_person, Mapping) or set(raw_person) != PERSON_KEYS:
            raise ValueError("reservation_access_person_invalid")
        person_id = _text(raw_person["reservation_person_id"], "reservation_person_id")
        if person_id in person_ids:
            raise ValueError("reservation_access_person_id_duplicate")
        person_ids.add(person_id)

        display_name = check_label_text(raw_person["display_name"], "display_name",
                                          allow_empty=True,
                                          max_len=DISPLAY_NAME_MAX_LEN)
        nickname = _text(raw_person["nickname"], "nickname")
        if nickname:
            if nickname in nicknames:
                raise ValueError("reservation_access_nickname_duplicate")
            nicknames.add(nickname)
        if type(raw_person["is_active"]) is not bool:
            raise ValueError("reservation_access_is_active_invalid")
        assignments_raw = raw_person["assignments"]
        if not isinstance(assignments_raw, list):
            raise ValueError("reservation_access_assignments_invalid")
        assignments: list[str] = []
        seen_assignments: set[str] = set()
        for raw_trip_code in assignments_raw:
            trip_code = _text(raw_trip_code, "assignment")
            if trip_code in seen_assignments:
                raise ValueError("reservation_access_assignment_duplicate")
            seen_assignments.add(trip_code)
            assignments.append(trip_code)
        if not raw_person["is_active"] and assignments:
            raise ValueError("reservation_access_inactive_assignments_invalid")
        persons.append({
            "reservation_person_id": person_id,
            "display_name": display_name,
            "nickname": nickname,
            "is_active": raw_person["is_active"],
            "assignments": assignments,
        })

    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at,
        "snapshot_revision": revision,
        "persons": persons,
    }
    result["digest"] = stable_digest(result)
    return result
