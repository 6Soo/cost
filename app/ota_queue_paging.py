"""Pure in-memory paging index for worker-prepared OTA queue rows.

The shape follows ``docs/specs/ota-review-queue-performance-20261027.md`` §5,
§8 and §11. Callers build this once per snapshot. The index retains bounded
scalar snapshots and search text, never merges reservation/payment groups,
and does not classify events.
Without ``q``, selection is indexed and slicing is O(page size); ``q`` scans
the selected precomputed positions (O(n) per request) without a query cache.
Only page items are serialized. This component does not provide HTTP/auth,
freshness gating, persistence, or a product latency guarantee.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
from datetime import date
from typing import Any


QUEUES = ("needs_action", "waiting_source", "evidence_missing",
          "auto_recheck", "completed", "historical")
_PRIORITY = {queue: n for n, queue in enumerate(QUEUES)}
_REASONS = frozenset({
    "EVENT_ID_DUPLICATE", "EVENT_ID_MISSING", "EVIDENCE_CHANGED",
    "EVIDENCE_MISSING", "EVIDENCE_UNKNOWN", "HOLD_AMBIGUOUS",
    "HOLD_AMOUNT_MISMATCH", "HOLD_AMOUNT_UNVERIFIED", "HOLD_DATE_UNKNOWN",
    "HOLD_EVIDENCE_CONFLICT", "HOLD_GROUP_CHANGED", "HOLD_NO_CARD",
    "HOLD_PARTIAL_GROUP", "INFERRED_OR_GROUP_MATCH", "MALFORMED_EVENT",
    "MATCH_REASON_UNKNOWN", "MATCHED_AUTO", "MATCHED_USER",
    "MATCHING_REVIEW_REQUIRED", "MATCHING_REVIEW_RESOLVED",
    "NOT_CARD_CHARGE", "PAYMENT_EVIDENCE_CONFLICT",
    "PAYMENT_EVIDENCE_MISSING", "PAYMENT_EVIDENCE_UNVERIFIED",
    "PAYMENT_STATUS_UNVERIFIED", "PENDING_PAYMENT", "RESERVATION_ONLY",
    "REVIEW_WARNING", "SCHEDULED_EVIDENCE_REVIEW", "SOURCE_OR_DATE_PENDING",
    "STATUS_UNKNOWN", "TRANSACTION_ID_MISSING",
})
_STATUSES = frozenset({
    "MATCHED_AUTO", "MATCHED_USER", "PENDING_PAYMENT", "HOLD_DATE_UNKNOWN",
    "HOLD_NO_CARD", "RESERVATION_ONLY", "HOLD_AMOUNT_UNVERIFIED",
    "HOLD_AMOUNT_MISMATCH", "HOLD_AMBIGUOUS", "HOLD_EVIDENCE_CONFLICT",
    "HOLD_GROUP_CHANGED", "HOLD_PARTIAL_GROUP", "NOT_CARD_CHARGE",
    "UNKNOWN_STATUS",
})
_PROVIDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)
_SAFE_FIELD = re.compile(r"[^\x00-\x1f\x7f]*\Z")
_TOKEN_PART = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_MAX_TOKEN = 1024
_MAX_Q = 120
_MAX_NONCE = 128
_MAX_ID = 200
_MAX_BOOKING = 120
_MAX_ITEM = 160
_MAX_EVENT_TYPE = 48
_MAX_CURRENCY = 8
_MAX_AMOUNT = 80


class PagingError(ValueError):
    """Safe paging failure; ``code`` and ``status_code`` are finite metadata."""

    def __init__(self, code: str, status_code: int):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _bad_input() -> PagingError:
    return PagingError("INVALID_INPUT", 400)


def _bounded_text(value: Any, maximum: int) -> str | None:
    if type(value) is not str or len(value) > maximum or not _SAFE_FIELD.fullmatch(value):
        return None
    return value


def _provider_value(value: Any) -> str | None:
    if type(value) is not str or not _PROVIDER.fullmatch(value):
        return None
    return value.casefold()


def _valid_date(value: Any) -> str | None:
    if type(value) is not str or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _event_text(event: dict[str, Any]) -> tuple[str, ...]:
    fields = []
    for key, maximum in (("booking_ref", _MAX_BOOKING), ("provider", 64),
                         ("item", _MAX_ITEM), ("merchant", 160)):
        value = _bounded_text(event.get(key), maximum)
        if value is not None:
            fields.append(value.casefold())
    return tuple(fields)


def _safe_reason_codes(value: Any) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or len(value) > 16:
        raise _bad_input()
    out: list[str] = []
    for code in value:
        if type(code) is not str or code not in _REASONS:
            raise _bad_input()
        if code not in out:
            out.append(code)
    return tuple(out)


def _safe_snapshot_value(value: Any, *, generation: bool) -> int | str:
    if generation:
        if type(value) is not int or value < 0:
            raise _bad_input()
        return value
    if type(value) is not str or not value or len(value) > _MAX_NONCE or not _SAFE_FIELD.fullmatch(value):
        raise _bad_input()
    return value


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(part: str) -> bytes:
    if not _TOKEN_PART.fullmatch(part):
        raise ValueError
    return base64.b64decode(part + "=" * (-len(part) % 4), altchars=b"-_", validate=True)


def _filter_digest(queue: str | None, provider: str | None, q: str | None) -> str:
    blob = json.dumps([queue, provider, q], ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(blob).hexdigest()


class QueueIndex:
    """Opaque-by-convention snapshot index; create with :func:`build_queue_index`."""

    __slots__ = ("_rows", "_positions", "_generation", "_nonce_hash", "_key")

    def __init__(self, rows, positions, generation, nonce_hash, key):
        self._rows = rows
        self._positions = positions
        self._generation = generation
        self._nonce_hash = nonce_hash
        self._key = key

    @property
    def event_count(self) -> int:
        return len(self._rows)


def build_queue_index(rows, *, generation: int, snapshot_nonce: str,
                      signing_key: bytes) -> QueueIndex:
    """Index worker-prepared rows without changing any input event.

    ``rows`` must be a finite list/tuple of exact dictionaries with ``queue``,
    finite ``reason_codes`` and an exact-dict ``event``. Only bounded allowlisted
    scalar fields are retained, so later source mutation does not affect the index.
    ``signing_key`` is caller-owned bytes (at least 32 bytes); no key discovery or
    storage is performed here.
    """
    gen = _safe_snapshot_value(generation, generation=True)
    nonce = _safe_snapshot_value(snapshot_nonce, generation=False)
    if type(signing_key) is not bytes or len(signing_key) < 32:
        raise _bad_input()
    if type(rows) not in (list, tuple):
        raise _bad_input()

    indexed = []
    buckets: dict[tuple[str | None, str | None], list[int]] = {}
    all_positions: dict[tuple[str | None, str | None], list[int]] = {}
    for ordinal, row in enumerate(rows):
        if type(row) is not dict:
            raise _bad_input()
        queue = row.get("queue")
        if type(queue) is not str or queue not in QUEUES:
            raise _bad_input()
        event = row.get("event")
        if type(event) is not dict:
            raise _bad_input()
        reasons = _safe_reason_codes(row.get("reason_codes"))
        provider = _provider_value(event.get("provider"))
        paid_on = _valid_date(event.get("paid_on"))
        safe_event = _serialize_event(event, include_search=True)
        search_fields = _event_text(safe_event)
        provider = _provider_value(safe_event.get("provider"))
        paid_on = safe_event.get("paid_on")
        safe_id = safe_event.get("ota_event_id")
        record = (queue, reasons, safe_event, ordinal, provider, paid_on,
                  safe_id.casefold() if safe_id is not None else "", search_fields)
        indexed.append(record)
        buckets.setdefault((queue, provider), []).append(ordinal)

    def sort_key(pos: int):
        queue, _, _, ordinal, _, paid_on, event_id, _ = indexed[pos]
        return (_PRIORITY[queue], paid_on is None, paid_on or "", event_id, ordinal)

    positions: dict[tuple[str | None, str | None], tuple[int, ...]] = {}
    for key, values in buckets.items():
        positions[key] = tuple(sorted(values, key=sort_key))
        qkey, pkey = key
        for aggregate_key in {(None, pkey), (qkey, None), (None, None)}:
            all_positions.setdefault(aggregate_key, []).extend(values)
    for key, values in all_positions.items():
        positions[key] = tuple(sorted(values, key=sort_key))

    return QueueIndex(tuple(indexed), positions, gen,
                      hashlib.sha256(nonce.encode("utf-8")).hexdigest(), signing_key)


def _encode_cursor(index: QueueIndex, offset: int, filter_hash: str, limit: int) -> str:
    payload = json.dumps({"v": 1, "o": offset, "g": index._generation,
                          "f": filter_hash, "l": limit, "n": index._nonce_hash},
                         sort_keys=True, separators=(",", ":")).encode("ascii")
    encoded = _b64encode(payload)
    signature = _b64encode(hmac.new(index._key, encoded.encode("ascii"), hashlib.sha256).digest())
    return encoded + "." + signature


def _decode_cursor(index: QueueIndex, token: Any) -> dict[str, Any]:
    if type(token) is not str or len(token) > _MAX_TOKEN or token.count(".") != 1:
        raise PagingError("BAD_CURSOR", 400)
    left, right = token.split(".")
    try:
        payload_bytes = _b64decode(left)
        signature = _b64decode(right)
        if _b64encode(payload_bytes) != left or _b64encode(signature) != right:
            raise ValueError
        expected = hmac.new(index._key, left.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(payload_bytes.decode("ascii"))
        if type(payload) is not dict or set(payload) != {"v", "o", "g", "f", "l", "n"}:
            raise ValueError
        if (type(payload["v"]) is not int or payload["v"] != 1 or
                type(payload["o"]) is not int or payload["o"] < 0 or
                type(payload["g"]) is not int or payload["g"] < 0 or
                type(payload["l"]) is not int or payload["l"] < 1 or payload["l"] > 100 or
                type(payload["f"]) is not str or len(payload["f"]) != 64 or
                type(payload["n"]) is not str or len(payload["n"]) != 64):
            raise ValueError
        return payload
    except Exception:
        raise PagingError("BAD_CURSOR", 400) from None


def _serialize_event(event: dict[str, Any], *, include_search: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    specs = (("ota_event_id", _MAX_ID), ("provider", 64),
             ("booking_ref", _MAX_BOOKING), ("event_type", _MAX_EVENT_TYPE),
             ("item", _MAX_ITEM), ("currency", _MAX_CURRENCY))
    for key, maximum in specs:
        value = _bounded_text(event.get(key), maximum)
        if key == "provider":
            value = value if _provider_value(value) is not None else None
        if key == "currency" and value is not None and not re.fullmatch(r"[A-Za-z0-9]{3,8}", value, re.ASCII):
            value = None
        out[key] = value
    out["paid_on"] = _valid_date(event.get("paid_on"))
    amount = event.get("amount")
    if type(amount) is int:
        out["amount"] = amount
    elif type(amount) is float and math.isfinite(amount):
        out["amount"] = amount
    elif (type(amount) is str and len(amount) <= _MAX_AMOUNT and
          re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", amount, re.ASCII)):
        out["amount"] = amount
    else:
        out["amount"] = None
    status = event.get("status")
    out["status"] = status if type(status) is str and status in _STATUSES else "UNKNOWN_STATUS"
    if include_search:
        out["merchant"] = _bounded_text(event.get("merchant"), 160)
    return out


def list_queue_page(index: QueueIndex, *, queue: str | None = None,
                    provider: str | None = None, q: str | None = None,
                    limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    """Return one allowlisted page; ``None`` queue/provider means no such filter."""
    if type(index) is not QueueIndex:
        raise _bad_input()
    if queue is not None and (type(queue) is not str or queue not in QUEUES):
        raise _bad_input()
    if provider is not None:
        normalized_provider = _provider_value(provider)
        if normalized_provider is None:
            raise _bad_input()
    else:
        normalized_provider = None
    if type(q) is not str and q is not None:
        raise _bad_input()
    normalized_q = q.strip().casefold() if q is not None else None
    if normalized_q is not None and (len(normalized_q) > _MAX_Q or not normalized_q or not _SAFE_FIELD.fullmatch(normalized_q)):
        raise _bad_input()
    if type(limit) is not int or not 1 <= limit <= 100:
        raise _bad_input()

    digest = _filter_digest(queue, normalized_provider, normalized_q)
    offset = 0
    if cursor is not None:
        payload = _decode_cursor(index, cursor)
        if (payload["g"] != index._generation or payload["n"] != index._nonce_hash or
                payload["f"] != digest or payload["l"] != limit):
            raise PagingError("SNAPSHOT_CHANGED", 409)
        offset = payload["o"]

    base = index._positions.get((queue, normalized_provider), ())
    if normalized_q is None:
        total = len(base)
        chosen = base[offset:offset + limit]
    else:
        chosen = []
        total = 0
        needle = normalized_q
        for pos in base:
            if any(needle in text for text in index._rows[pos][7]):
                if offset <= total < offset + limit:
                    chosen.append(pos)
                total += 1

    items = []
    for pos in chosen:
        row_queue, reasons, event, _, _, _, _, _ = index._rows[pos]
        items.append({"queue": row_queue, "reason_codes": list(reasons),
                      "event": _serialize_event(event)})
    next_offset = offset + len(chosen)
    next_cursor = (_encode_cursor(index, next_offset, digest, limit)
                   if next_offset < total else None)
    return {"generation": index._generation, "total_count": total,
            "next_cursor": next_cursor, "items": items}
