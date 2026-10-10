"""Decide whether a flight passenger is a company guide, from trusted identity data only."""

import hashlib
import json
import unicodedata
from pathlib import Path

IDENTITY_VERSION = "guide-identity-v1"
TRUSTED_ASSIGNEE_SOURCES = ("manual", "owner_profile")

_SEPARATOR_CHARS = {ord(ch): " " for ch in "-_·"}
_DELETED_CHARS = {ord(ch): None for ch in ".,'’`"}


def normalize_name_part(text) -> str:
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).strip().casefold().upper()
    value = value.translate(_SEPARATOR_CHARS).translate(_DELETED_CHARS)
    return " ".join(value.split())


def _compact(text) -> str:
    return "".join(normalize_name_part(text).split())


def _is_hangul(text) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def _has_latin(text) -> bool:
    return any(ch.isalpha() and unicodedata.name(ch, "").startswith("LATIN") for ch in text)


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _require_text(value, path, field):
    if not isinstance(value, str) or not value.strip():
        _fail(path, f"{field} must be a non-empty string")
    return value


def _check_registry(data, path):
    if not isinstance(data, dict):
        _fail(path, "registry must be a JSON object")
    if "version" in data and data["version"] != 1:
        _fail(path, "unsupported registry version")
    guides = data.get("guides", [])
    if not isinstance(guides, list):
        _fail(path, "guides must be a list")
    for guide in guides:
        if not isinstance(guide, dict):
            _fail(path, "each guide must be an object")
        _require_text(guide.get("assignee_name"), path, "assignee_name")
        aliases = guide.get("aliases", [])
        if not isinstance(aliases, list):
            _fail(path, "aliases must be a list")
        for alias in aliases:
            if not isinstance(alias, dict):
                _fail(path, "each alias must be an object")
            _require_text(alias.get("surname"), path, "surname")
            _require_text(alias.get("given_name"), path, "given_name")
    return data


def load_alias_registry(path) -> dict:
    if not path or not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: malformed JSON: {exc}") from exc
    return _check_registry(data, path)


def guide_identities(trips, owner_assignee_name, registry) -> list[dict]:
    found = {}

    def add(name, source):
        name = (name or "").strip()
        key = _compact(name)
        if not key:
            return None
        entry = found.setdefault(key, {"names": set(), "sources": set(), "aliases": set()})
        entry["names"].add(name)
        entry["sources"].add(source)
        return entry

    for trip in trips or []:
        source = trip.get("assignee_source")
        if source in TRUSTED_ASSIGNEE_SOURCES:
            add(trip.get("prepared_by_name"), f"trip:{source}")
    add(owner_assignee_name, "owner_profile")

    for guide in (registry or {}).get("guides", []):
        entry = found.get(_compact(guide["assignee_name"]))
        if entry is None:
            continue
        entry["sources"].add("registry")
        for alias in guide.get("aliases", []):
            surname = normalize_name_part(alias["surname"])
            given_name = normalize_name_part(alias["given_name"])
            if surname and given_name:
                entry["aliases"].add((surname, given_name))

    identities = []
    for key, entry in found.items():
        identities.append({
            "assignee_name": min(entry["names"]),
            "normalized": key,
            "sources": sorted(entry["sources"]),
            "aliases": [{"surname": s, "given_name": g} for s, g in sorted(entry["aliases"])],
            "trusted": True,
        })
    return sorted(identities, key=lambda identity: identity["assignee_name"])


def match_passenger(passenger, identities) -> dict:
    unknown = {"status": "unknown", "guide": ""}
    surname = normalize_name_part(passenger.get("surname"))
    given_name = normalize_name_part(passenger.get("given_name"))
    if not surname or not given_name or not identities:
        return unknown

    both = surname + " " + given_name
    if _is_hangul(both) and not _has_latin(both):
        joined = both.replace(" ", "")
        for identity in identities:
            if identity["normalized"] == joined:
                return {"status": "guide", "guide": identity["assignee_name"]}
        return {"status": "not_guide", "guide": ""}

    if _has_latin(both) and not _is_hangul(both):
        pair = {"surname": surname, "given_name": given_name}
        matches = [identity for identity in identities if pair in identity["aliases"]]
        if len(matches) == 1:
            return {"status": "guide", "guide": matches[0]["assignee_name"]}
        if matches:
            return unknown
        if all(identity["aliases"] for identity in identities):
            return {"status": "not_guide", "guide": ""}
        return unknown

    return unknown


def identity_digest(identities) -> str:
    payload = {"v": IDENTITY_VERSION, "identities": identities}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
