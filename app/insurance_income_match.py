"""Privacy-preserving matching of masked insurance names to income rows."""
from __future__ import annotations

import hashlib
from datetime import date
import json
import re
import unicodedata
from pathlib import Path

_MAX_BYTES = 2 * 1024 * 1024
_MAX_CONTRACTS = 1000
_MAX_ROWS = 10000
_MAX_CHOICES = 20
_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_MASKS = frozenset("*＊○〇●□■◇◆×✕✖")


class ManifestError(ValueError):
    """The review manifest is malformed or exceeds its bounds."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError("duplicate JSON key")
        result[key] = value
    return result


def _opaque(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def load_review_manifest(path) -> dict:
    """Load bounded manifest metadata; never opens referenced source documents."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
    except OSError as exc:
        raise ManifestError("manifest unavailable") from exc
    if len(raw) > _MAX_BYTES:
        raise ManifestError("manifest exceeds size limit")
    fingerprint = hashlib.sha256(raw).hexdigest()
    try:
        source = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ManifestError("invalid manifest JSON") from exc
    if not isinstance(source, dict) or type(source.get("schema_version")) is not int or source["schema_version"] != 1:
        raise ManifestError("invalid manifest header")
    if not all(isinstance(source.get(k), str) and source[k] for k in ("kind", "created_at", "query_basis")):
        raise ManifestError("invalid manifest header")
    if not isinstance(source.get("notes"), list) or not all(isinstance(x, str) for x in source["notes"]):
        raise ManifestError("invalid manifest notes")
    contracts = source.get("contracts")
    if not isinstance(contracts, list) or len(contracts) > _MAX_CONTRACTS:
        raise ManifestError("invalid contract list")
    normalized, seen_contracts, seen_contract_ids, seen_rows, total = [], set(), set(), set(), 0
    for contract in contracts:
        if not isinstance(contract, dict):
            raise ManifestError("invalid contract")
        cid, start, end = (contract.get(k) for k in ("contract_id", "travel_start", "travel_end"))
        if not all(isinstance(x, str) and x.strip() for x in (cid, start, end)):
            raise ManifestError("invalid contract identity or dates")
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError as exc:
            raise ManifestError("invalid travel date") from exc
        if end_date < start_date:
            raise ManifestError("invalid travel date")
        if contract.get("insurance_status") != "completed_or_expired":
            raise ManifestError("unsupported insurance status")
        trip_status, trip_id = contract.get("trip_mapping_status"), contract.get("cost_trip_id")
        if not isinstance(trip_status, str) or (trip_id is not None and
                (not isinstance(trip_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", trip_id))):
            raise ManifestError("invalid trip reference")
        if type(contract.get("already_registered")) is not bool:
            raise ManifestError("invalid registration flag")
        digest = contract.get("sha256")
        if not isinstance(digest, str) or not _HEX.fullmatch(digest):
            raise ManifestError("invalid source digest")
        source_ref = contract.get("source_pdf")
        if (not isinstance(source_ref, str) or not source_ref.strip() or "\x00" in source_ref
                or source_ref.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", source_ref)
                or ".." in source_ref.replace("\\", "/").split("/")):
            raise ManifestError("invalid source reference")
        items = contract.get("items")
        if not isinstance(items, list):
            raise ManifestError("invalid items")
        insured_count = contract.get("insured_count")
        if type(insured_count) is not int or insured_count < 0 or insured_count != len(items):
            raise ManifestError("invalid insured count")
        total += len(items)
        if total > _MAX_ROWS:
            raise ManifestError("row limit exceeded")
        key = _opaque("contract", digest.lower(), cid, start, end)
        if key in seen_contracts or cid in seen_contract_ids:
            raise ManifestError("duplicate contract")
        seen_contracts.add(key)
        seen_contract_ids.add(cid)
        rows = []
        for item in items:
            if not isinstance(item, dict):
                raise ManifestError("invalid item")
            source_row, masked = item.get("source_row"), item.get("masked_name")
            if not isinstance(source_row, str) or not source_row.strip() or not isinstance(masked, str):
                raise ManifestError("invalid row metadata")
            if item.get("status") != "unresolved":
                raise ManifestError("unsupported row status")
            row_id = _opaque("row", digest.lower(), key, source_row)
            if row_id in seen_rows:
                raise ManifestError("duplicate source row")
            seen_rows.add(row_id)
            rows.append({"review_row_id": row_id, "masked_name": masked})
        normalized.append({"contract_key": key, "travel_start": start, "travel_end": end,
                           "cost_trip_id": trip_id, "already_registered": contract["already_registered"],
                           "insurance_status": contract["insurance_status"], "rows": rows})
    return {"fingerprint": fingerprint, "contracts": normalized}


def _name_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(ch for ch in value if not ch.isspace())


def _pattern_parts(pattern: str):
    normalized = unicodedata.normalize("NFKC", pattern).casefold()
    parts, visible = [], 0
    for char in normalized:
        if char.isspace():
            continue
        if char in _MASKS:
            parts.append(None)
        else:
            parts.append(char)
            if unicodedata.category(char)[0] in "LNM":
                visible += 1
    return parts, visible


def _unknown_mask_length(pattern):
    parts = _pattern_parts(pattern)[0]
    return any(a is None and b is None for a, b in zip(parts, parts[1:]))


def _match_basis(pattern: str, value: str) -> str:
    if not isinstance(pattern, str) or not isinstance(value, str):
        return ''
    parts, visible = _pattern_parts(pattern)
    candidate = _name_key(value)
    if not visible or not candidate or len(candidate) > 128:
        return ''
    # Some insurers use a fixed *** token regardless of the hidden name length.
    # Preserve single-mask positional matching; consecutive masks are length
    # unknown and can only produce review candidates, never a unique match.
    if any(a is None and b is None for a, b in zip(parts, parts[1:])):
        positions, index = {0}, 0
        while index < len(parts):
            if parts[index] is not None:
                positions = {p + 1 for p in positions if p < len(candidate) and candidate[p] == parts[index]}
                index += 1
            else:
                end = index + 1
                while end < len(parts) and parts[end] is None:
                    end += 1
                # Bounded dynamic positions avoid exponential regex backtracking.
                positions = ({p for p in range(min(positions) + 1, len(candidate) + 1)}
                             if end - index > 1 and positions else
                             {p + 1 for p in positions if p < len(candidate)})
                index = end
            if not positions:
                return ''
        return 'mask_length_unknown' if len(candidate) in positions else ''
    if len(parts) != len(candidate):
        return ''
    return 'positional' if all(part is None or part == char for part, char in zip(parts, candidate)) else ''


def match_masked_name(pattern: str, value: str) -> bool:
    return bool(_match_basis(pattern, value))


def unique_identity_name_match(pattern: str, value: str) -> bool:
    """Eligible name evidence; callers must also prove uniqueness both ways.

    A masked name needs visible characters at both ends. Repeated mask tokens
    may hide an unknown number of characters; never reconstruct those letters.
    """
    if not isinstance(pattern, str) or not isinstance(value, str):
        return False
    parts, visible = _pattern_parts(pattern)
    candidate, _ = _pattern_parts(value)
    if not parts or not candidate or any(p is None for p in candidate):
        return False
    if any(p is None for p in parts):
        if visible < 2 or parts[0] is None or parts[-1] is None:
            return False
    else:
        normalize = lambda text: re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text).strip()).casefold()
        return normalize(pattern) == normalize(value)
    return bool(_match_basis(pattern, value))


def match_contract(contract, income_rows) -> dict:
    rows = contract.get("rows", []) if isinstance(contract, dict) else []
    incomes = list(income_rows)
    possible = []
    for row in rows:
        pat = row.get("masked_name", "")
        hits = []
        if _pattern_parts(pat)[1]:
            for idx, income in enumerate(incomes):
                if not isinstance(income, dict):
                    continue
                fields = [income.get("name", ""), income.get("nickname", "")]
                cells = income.get("cells", {})
                if isinstance(cells, dict):
                    fields.extend((cells.get("C", ""), cells.get("D", "")))
                if any(isinstance(v, str) and match_masked_name(pat, v) for v in fields):
                    hits.append(idx)
        possible.append(hits)
    occurrences = {}
    for hits in possible:
        for idx in hits:
            occurrences[idx] = occurrences.get(idx, 0) + 1
    output = []
    counts = {state: 0 for state in ("matched", "ambiguous", "unmatched", "no_visible_letters")}
    for row, hits in zip(rows, possible):
        if not _pattern_parts(row.get("masked_name", ""))[1]:
            state = "no_visible_letters"
        elif not hits:
            state = "unmatched"
        elif len(hits) == 1 and occurrences[hits[0]] == 1:
            income = incomes[hits[0]]
            fields = [income.get('name',''),income.get('nickname','')]
            cells = income.get('cells') or {}
            if isinstance(cells,dict):
                fields.extend((cells.get('C',''),cells.get('D','')))
            state = 'matched' if any(unique_identity_name_match(row.get('masked_name',''),v)
                                     for v in fields) else 'ambiguous'
        else:
            state = "ambiguous"
        counts[state] += 1
        choices = []
        for idx in hits[:_MAX_CHOICES]:
            income = incomes[idx]
            choices.append({k: income.get(k) for k in ("ref", "fingerprint", "name", "nickname", "trip_id", "trip_name", "date", "amount")})
        output.append({"review_row_id": row.get("review_row_id"), "masked_name": row.get("masked_name"),
                       "mask_length_unknown": _unknown_mask_length(row.get('masked_name', '')),
                       "match_state": state, "matches": choices, "candidate_count": len(hits)})
    return {"rows": output, "counts": counts}
