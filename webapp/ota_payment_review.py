"""Opt-in, isolated UI for reviewing OTA payment holds.

The backend is deliberately injected. Its snapshot operation must be read-only;
write methods must persist only in the separately configured OTA review store.
"""
from __future__ import annotations

import atexit
import importlib
import json
import os
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import ota_snapshot
from app.ota_queue_projection import summarize_queue


ROUTE_PREFIX = "/api/imports/ota"
REVIEW_MODE_ENV = "WEBLEDGER_OTA_REVIEW_MODE"
REVIEW_DB_ENV = "WEBLEDGER_OTA_REVIEW_DB"
SOURCES_ENV = "WEBLEDGER_OTA_SOURCES_JSON"
_read_backend_factory = None
_write_backend_factory = None

_EVENT_FIELDS = (
    "ota_event_id", "transaction_id", "provider", "booking_ref", "event_type", "paid_on", "amount",
    "currency", "amount_krw", "card_last4", "card_issuer", "service_period", "item",
    "service_period_conflict", "service_period_candidates", "booking_changes",
    "inferred_link", "inference_basis", "payment_date_verified",
    "reservation_status", "reservation_group_only", "payment_status", "evidence_status", "status", "reason",
    "refund_status", "evidence_changed", "evidence_missing", "review_warning",
    "matched_count", "unmatched_ota_count", "unmatched_card_count", "group_count",
    "ota_group_ids", "card_group_ids", "allocation_basis", "individual_payment_evidence",
    "rule_delta_krw", "discount_cause_confirmed", "group_order_frozen",
    "frozen_mapping", "proposed_mapping",
    "group_order_snapshot", "candidate_search_status", "candidate_date_status", "candidate_count",
    "candidate_rejected_count", "reservation_link",
)
_CARD_FIELDS = (
    "transaction_id", "issuer", "card_kind", "card_tail", "approval_date",
    "posting_date", "merchant", "amount_krw", "foreign_amount", "currency",
    "approval_number", "direction", "transaction_direction", "refund_status", "cancellation_status",
    "already_linked_event_id", "already_linked_label", "already_linked_reason", "selection_disabled",
    "selection_disabled_reason", "authorization_number", "authorization_scheme",
    "candidate_date_status", "candidate_resolution_allowed",
    "candidate_rejection_reason", "reservation_candidate", "reservation_candidate_basis",
    "reservation_amount_status", "reservation_stay_date_status", "reservation_history",
)
_CONDITION_FIELDS = (
    "provider", "item", "merchant_normalized", "issuer", "card_last4",
    "amount_delta_krw", "date_lag_days", "date_lag_min_days", "date_lag_max_days",
    "currency", "event_type", "rule_kind", "alias",
    "approval_source", "alias_version", "event_issuer_alias", "discount_rate_bps", "discount_cap_krw",
    "minimum_amount_krw", "rounding_mode", "payment_method", "valid_from", "valid_to",
)
_LINK_REASON_TEXT = {
    "자동 연결": "다른 예약에 연결됨",
    "기존 연결": "다른 예약에 연결됨",
    "사용자 확정 연결": "다른 예약에 연결됨",
}


def _public_period(value):
    if isinstance(value, dict):
        return {key: value[key] for key in ("starts_on", "ends_on") if key in value}
    return value if isinstance(value, (str, int, float, type(None))) else None


def _public_reservation_link(value):
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status not in {"INFERRED", "USER_CONFIRMED", "NEEDS_REVIEW", "STALE"}:
        return None
    transaction_id = value.get("transaction_id")
    if transaction_id is not None and not isinstance(transaction_id, str):
        return None
    basis, amount_status = value.get("basis"), value.get("amount_status")
    if basis is not None and not isinstance(basis, str):
        return None
    if amount_status not in {None, "MATCH", "UNKNOWN", "MISMATCH"}:
        return None
    result = {"status": status, "transaction_id": transaction_id, "basis": basis,
              "amount_status": amount_status, "payment_verified": False}
    for key in ("merchant", "approval_date", "amount_krw", "historical_card_missing", "revision"):
        item = value.get(key)
        if key == "amount_krw" and isinstance(item, (int, float)) and not isinstance(item, bool):
            result[key] = item
        elif key == "revision" and isinstance(item, int) and not isinstance(item, bool):
            result[key] = item
        elif key in ("merchant", "approval_date") and isinstance(item, str):
            result[key] = item
        elif key == "historical_card_missing" and isinstance(item, bool):
            result[key] = item
    return result


def _transaction_selection_block_reason(transaction):
    if transaction.get("duplicate_of"):
        return "중복 거래라 선택할 수 없습니다."
    if transaction.get("parse_error"):
        return "거래 파싱 오류가 있어 선택할 수 없습니다."
    if transaction.get("conflict_reason"):
        return "거래 충돌이 있어 선택할 수 없습니다."
    return ""


def _proposal_question(conditions):
    conditions = conditions if isinstance(conditions, dict) else {}
    if conditions.get("rule_kind") == "provider_alias":
        return (f"{conditions.get('provider', '')} 가맹점 별칭 {conditions.get('alias', '')}를 "
                f"출처 {conditions.get('approval_source', '')}, 버전 {conditions.get('alias_version', '')}로 승인할까요?")
    if conditions.get("rule_kind") == "issuer_alias":
        return (f"{conditions.get('provider', '')} 결제의 발급사 별칭 {conditions.get('event_issuer_alias', '')}를 "
                f"카드 발급사 {conditions.get('issuer', '')}에 연결할까요?")
    details = []
    delta = conditions.get("amount_delta_krw")
    if isinstance(delta, int) and not isinstance(delta, bool):
        if delta < 0:
            details.append(f"OTA 금액보다 카드 금액이 {abs(delta):,}원 적고")
        elif delta > 0:
            details.append(f"OTA 금액보다 카드 금액이 {delta:,}원 많고")
        else:
            details.append("OTA 금액과 카드 금액이 같고")
    identity = []
    for key in ("provider", "item", "merchant_normalized"):
        if conditions.get(key):
            identity.append(str(conditions[key]))
    if conditions.get("issuer"):
        identity.append(f"카드사 {conditions['issuer']}")
    if conditions.get("card_last4"):
        identity.append(f"카드 끝 네 자리 {conditions['card_last4']}")
    if not details and not identity and "date_lag_days" not in conditions:
        return "이 연결을 규칙으로 저장할까요?"
    details.extend(identity)
    lag = conditions.get("date_lag_days")
    if isinstance(lag, int) and not isinstance(lag, bool) and lag:
        details.append(f"카드 승인일은 OTA 결제일보다 최대 {abs(lag)}일 {'늦고' if lag > 0 else '빠르고'}")
    return " ".join(details) + " 조건을 다음 결제에도 적용할까요?"


def _event_label(event_by_id, event_ids):
    """The booking a card is linked to, as people name it: 'provider · booking ref'. Never the internal id."""
    labels = []
    for event_id in str(event_ids or "").split("|"):
        event = event_by_id.get(event_id)
        if event:
            labels.append(f"{event.get('provider') or '예약'} · {event.get('booking_ref') or '번호 없음'}")
    return ", ".join(dict.fromkeys(labels)) or "다른 예약"


def _sanitize_card_row(source):
    """Apply field allowlist and post-processing to a card row for public API.

    This mirrors the logic in public_snapshot(include_cards=True) so that
    the /cards/<event_id> endpoint exposes exactly the same safe fields.
    """
    row = {key: source.get(key) for key in _CARD_FIELDS if key in source}
    if row.get("already_linked_event_id") and not row.get("already_linked_label"):
        row["already_linked_label"] = "다른 예약"
    row.setdefault("approval_number", source.get("approval_number") or source.get("authorization_id"))
    row.setdefault("currency", source.get("foreign_currency") or source.get("currency"))
    row["direction"] = (source.get("transaction_direction") or source.get("direction") or "미확인")
    block_reason = _transaction_selection_block_reason(source)
    safe_reasons = {"중복 거래라 선택할 수 없습니다.",
                    "거래 파싱 오류가 있어 선택할 수 없습니다.",
                    "거래 충돌이 있어 선택할 수 없습니다.",
                    "저장한 예약 관계의 선택 이력입니다."}
    if not block_reason and source.get("selection_disabled_reason") in safe_reasons:
        block_reason = source["selection_disabled_reason"]
    if (not block_reason and source.get("candidate_rejection_reason") in
            ("AMOUNT_MISMATCH", "CURRENCY_MISMATCH", "FX_EVIDENCE_REQUIRED", "AMOUNT_EVIDENCE_REQUIRED")):
        block_reason = _OTA_REASON[source["candidate_rejection_reason"]]
    row["selection_disabled"] = bool(source.get("selection_disabled") or block_reason)
    row["selection_disabled_reason"] = block_reason
    if not block_reason and source.get("candidate_date_status") in ("UNKNOWN", "MISMATCH"):
        row["selection_disabled_reason"] = "OTA_PAYMENT_DATE_" + str(source["candidate_date_status"])
    if row.get("already_linked_event_id"):
        row["already_linked_reason"] = _LINK_REASON_TEXT.get(
            row.get("already_linked_reason"), "다른 예약에 연결됨")
    return row


def public_snapshot(snapshot, *, include_cards=False):
    """Allowlist the UI response so core rows and source metadata never escape.

    Returns events and proposals only. Cards are fetched per-event via /api/imports/ota/cards/<event_id>
    to avoid sending the full 500MB+ payload on every poll.
    """
    events = []
    for source in snapshot.get("events", []):
        event = {key: source.get(key) for key in _EVENT_FIELDS if key in source}
        event["paid_on"] = event.get("paid_on") or "미확인"
        event["service_period"] = _public_period(event.get("service_period"))
        relation = _public_reservation_link(event.get("reservation_link"))
        if relation:
            event["reservation_link"] = relation
        else:
            event.pop("reservation_link", None)
        # Include card count summary for UI badges (pre-computed by snapshot_from)
        event["card_candidate_count"] = source.get("card_candidate_count", 0)
        events.append(event)
    cards_by_event = {}
    if include_cards:
        for event_id, source_rows in snapshot.get("cards_by_event", {}).items():
            rows = []
            for source in source_rows:
                row = {key: source.get(key) for key in _CARD_FIELDS if key in source}
                if row.get("already_linked_event_id") and not row.get("already_linked_label"):
                    row["already_linked_label"] = "다른 예약"
                row.setdefault("approval_number", source.get("approval_number") or source.get("authorization_id"))
                row.setdefault("currency", source.get("foreign_currency") or source.get("currency"))
                row["direction"] = (source.get("transaction_direction") or source.get("direction") or "미확인")
                block_reason = _transaction_selection_block_reason(source)
                safe_reasons = {"중복 거래라 선택할 수 없습니다.",
                                "거래 파싱 오류가 있어 선택할 수 없습니다.",
                                "거래 충돌이 있어 선택할 수 없습니다.",
                                "저장한 예약 관계의 선택 이력입니다."}
                if not block_reason and source.get("selection_disabled_reason") in safe_reasons:
                    block_reason = source["selection_disabled_reason"]
                if (not block_reason and source.get("candidate_rejection_reason") in
                        ("AMOUNT_MISMATCH", "CURRENCY_MISMATCH", "FX_EVIDENCE_REQUIRED", "AMOUNT_EVIDENCE_REQUIRED")):
                    block_reason = _OTA_REASON[source["candidate_rejection_reason"]]
                row["selection_disabled"] = bool(source.get("selection_disabled") or block_reason)
                row["selection_disabled_reason"] = block_reason
                if not block_reason and source.get("candidate_date_status") in ("UNKNOWN", "MISMATCH"):
                    row["selection_disabled_reason"] = "OTA_PAYMENT_DATE_" + str(source["candidate_date_status"])
                if row.get("already_linked_event_id"):
                    row["already_linked_reason"] = _LINK_REASON_TEXT.get(
                        row.get("already_linked_reason"), "다른 예약에 연결됨")
                rows.append(row)
            cards_by_event[str(event_id)] = rows
    proposals = []
    for source in snapshot.get("proposals", []):
        conditions = source.get("conditions") or {}
        proposals.append({
            "proposal_id": source.get("proposal_id"),
            "question": _proposal_question(conditions) if conditions else source.get("question"),
            "status": source.get("status"),
            "conditions": {key: conditions[key] for key in _CONDITION_FIELDS if key in conditions},
        })
    return {"events": events, "cards_by_event": cards_by_event, "proposals": proposals}


class StalePreviewError(Exception):
    """The evidence or card transaction changed after preview."""


class OtaSnapshotNotReady(Exception):
    """No fresh, complete reconciled snapshot exists yet; the caller must try again later."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class InvalidReviewInput(Exception):
    """A request does not match the review API contract."""


def review_db_path() -> str:
    return os.environ.get(REVIEW_DB_ENV, "").strip()


def enabled() -> bool:
    """Enable only when an operator explicitly selects isolated review mode."""
    configured_path = Path(review_db_path()) if review_db_path() else None
    return (os.environ.get(REVIEW_MODE_ENV) == "isolated" and configured_path is not None
            and configured_path.is_absolute())


AUTHORITY_ENV = "WEBLEDGER_OTA_AUTHORITY"


def mode() -> str:
    """legacy: off. isolated: review UI and group holds. authority: isolated plus the ledger guard."""
    if not enabled():
        return "legacy"
    return "authority" if os.environ.get(AUTHORITY_ENV) == "authority" else "isolated"


def authority() -> bool:
    """OTA-first decides which OTA card rows may reach the ledger. Needs isolated review config."""
    return mode() == "authority"


def owns_route(path: str) -> bool:
    return path == ROUTE_PREFIX or path.startswith(ROUTE_PREFIX + "/")


def configure_backend_factory(*, read_factory, write_factory) -> None:
    """Install separate read-only and review-store adapters from the host."""
    global _read_backend_factory, _write_backend_factory
    _read_backend_factory = read_factory
    _write_backend_factory = write_factory


def backend_for_request(board, handler, *, read_only: bool):
    """Resolve a core-backed adapter; GET always opens its review DB read-only."""
    factory = _read_backend_factory if read_only else _write_backend_factory
    if factory is not None:
        return factory(board=board, handler=handler, review_db_path=review_db_path())
    return CoreOtaPaymentBackend.from_host(board, read_only=read_only)


def _path_key(value: str) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def _link_transaction_id(link):
    if isinstance(link, dict):
        return str(link.get("transaction_id") or "")
    return str(link or "")


def _manual_link_crosswalk(events, links, stored_events, persisted_crosswalk=None):
    """Map a legacy pinned ID only when its saved payment evidence identifies one new event."""
    current_ids = {str(event.get("ota_event_id") or "") for event in events}
    resolved = {}
    crosswalk = {}
    for old_id, link in (links or {}).items():
        old_id = str(old_id)
        if old_id in current_ids:
            resolved[old_id] = link
            continue
        saved = (stored_events or {}).get(old_id)
        if not isinstance(saved, dict):
            resolved[old_id] = link
            continue
        digest = saved.get("source_digest")
        prior = (persisted_crosswalk or {}).get(old_id) or {}
        matches = [event for event in events
                   if digest and event.get("source_digest") == digest
                   and event.get("provider") == saved.get("provider")
                   and event.get("booking_ref") == saved.get("booking_ref")
                   and event.get("event_type") == saved.get("event_type")
                   and str(event.get("amount_krw") or "") == str(saved.get("amount_krw") or "")
                   and str(event.get("card_last4") or "") == str(saved.get("card_last4") or "")]
        if (prior.get("current_event_id") in current_ids and digest and
                prior.get("evidence_digest") == digest):
            pinned = [event for event in matches
                      if str(event.get("ota_event_id") or "") == prior["current_event_id"]]
            if len(pinned) == 1:
                matches = pinned
        if len(matches) == 1:
            new_id = str(matches[0].get("ota_event_id") or "")
            resolved[new_id] = link
            crosswalk[old_id] = new_id
        else:
            resolved[old_id] = link
    return resolved, crosswalk


def _evidence_digests(record):
    values = record.get("source_digests") or record.get("evidence_digests") or []
    if isinstance(values, str):
        values = [values]
    values = {str(value) for value in values if value}
    values.update(str(record[key]) for key in ("source_digest", "source_sha256") if record.get(key))
    return values


def _same_card_amount_as_event(event, row):
    currency = str(event.get("currency") or "").upper()
    if currency == "KRW":
        expected, actual = event.get("amount_krw"), row.get("amount_krw")
    else:
        if str(row.get("foreign_currency") or "").upper() != currency:
            return False
        expected, actual = event.get("amount"), row.get("foreign_amount")
    try:
        expected_value = abs(Decimal(str(expected).replace(",", "")))
        actual_value = abs(Decimal(str(actual).replace(",", "")))
        return expected_value.is_finite() and actual_value.is_finite() and expected_value == actual_value
    except (InvalidOperation, TypeError, ValueError):
        return False


def legacy_exact_bindings(events, transactions, report):
    """Pin only a unique legacy exact whose evidence agrees with the canonical event."""
    rows = {str(row.get("transaction_id")): row for row in transactions if row.get("transaction_id")}
    candidates = {}
    reverse = {}
    for event in events:
        if event.get("event_type") not in ("charge", "refund") or not event.get("source_digest"):
            continue
        event_digests = _evidence_digests(event)
        expected_direction = "refund" if event.get("event_type") == "refund" else "purchase"
        matching = []
        for fact in (report or {}).get("matches", []):
            if fact.get('inferred_link') or fact.get('core_link'):
                continue
            transaction_id = str(fact.get("transaction_id") or "")
            row = rows.get(transaction_id)
            if row is None or row.get("duplicate_of") or row.get("parse_error") or row.get("conflict_reason"):
                continue
            legacy_digests = _evidence_digests(fact)
            event_card = str(event.get("card_last4") or "")
            row_card = str(row.get("card_tail") or row.get("card_last4") or "")
            direction = str(fact.get("direction") or "")
            if (not event_digests or not legacy_digests or not event_digests.intersection(legacy_digests) or
                    fact.get("provider") != event.get("provider") or
                    fact.get("booking_ref") != event.get("booking_ref") or
                    not _same_card_amount_as_event(event, row) or
                    len(row_card) < 4 or not row_card[-4:].isdigit() or
                    (event_card and not row_card.endswith(event_card)) or
                    direction != expected_direction or
                    str(row.get("transaction_direction") or "") != expected_direction or
                    fact.get("source_hash") != row.get("source_hash")):
                continue
            matching.append((transaction_id, fact))
        if len(matching) == 1:
            candidates[event["ota_event_id"]] = matching[0]
            reverse.setdefault(matching[0][0], []).append(event["ota_event_id"])
    return {
        event_id: {
            "transaction_id": transaction_id,
            "status": "MATCHED_AUTO",
            "legacy_exact": True,
            "source_digest": event["source_digest"],
            "source_digests": sorted(_evidence_digests(event)),
        }
        for event_id, (transaction_id, _fact) in candidates.items()
        if len(reverse.get(transaction_id, [])) == 1
        for event in events if event.get("ota_event_id") == event_id
    }


class CoreOtaPaymentBackend:
    """Adapter from the UI routes to the core shared API and review database."""

    def __init__(self, board, review_path, *, read_only, payments, store_type, sources):
        path = Path(review_path).expanduser()
        if not path.is_absolute():
            raise ValueError("OTA review database path must be absolute")
        self.review_path = str(path.resolve(strict=False))
        self.board = board
        self.payments = payments
        self.store_type = store_type
        self.sources = sources
        self._assert_separate_database()
        # The shared core store opens an existing file with SQLite mode=ro and
        # leaves a missing file untouched. Its write methods initialize lazily.
        self.store = store_type(self.review_path)
        self.read_only = read_only

    @classmethod
    def from_host(cls, board, *, read_only):
        payments = importlib.import_module("app.ota_payments")
        review = importlib.import_module("app.ota_review")
        raw_sources = os.environ.get(SOURCES_ENV, "").strip()
        if raw_sources:
            sources = json.loads(raw_sources)
            if not isinstance(sources, dict):
                raise ValueError("OTA source configuration must be a JSON object")
        else:
            ota_sources = importlib.import_module("app.ota_sources")
            ota_portal = importlib.import_module("app.ota_portal")
            data_directory = Path(board.path).parent
            mail_default = os.environ.get("WEBLEDGER_OTA_MAIL_DIR") or (data_directory / "ota-mail")
            sources = ota_sources.resolve_sources(
                data_directory, mail_default=mail_default,
                portal_default=ota_portal.evidence_path(data_directory))
        return cls(board, review_db_path(), read_only=read_only, payments=payments,
                   store_type=review.OtaReviewStore, sources=sources)

    def _assert_separate_database(self):
        connection = getattr(self.board, "conn", None)
        if connection is None:
            raise RuntimeError("board read connection is unavailable")
        rows = connection.execute("PRAGMA database_list").fetchall()
        for row in rows:
            if len(row) >= 3 and row[1] == "main" and row[2]:
                if _path_key(row[2]) == _path_key(self.review_path):
                    raise ValueError("OTA review database must be separate from the board database")

    def _transactions(self):
        lock = getattr(self.board, "_lock", None)
        with lock if lock is not None else nullcontext():
            cursor = self.board.conn.execute("SELECT * FROM transactions")
            columns = [column[0] for column in cursor.description or ()]
            rows = cursor.fetchall()
            from app import ota_exact
            tables = {row[0] for row in self.board.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            eligible = (ota_exact.open_transaction_ids(self.board.conn)
                        if {'board_rows', 'transactions'} <= tables and
                        {'classification_source', 'classification_state'} <= set(columns) else set())
            review_held = ({row[0] for row in self.board.conn.execute('SELECT transaction_id FROM transaction_review_holds')}
                           if 'transaction_review_holds' in tables else set())
            eligible -= review_held
        result = [dict(row) if hasattr(row, 'keys') else dict(zip(columns, row)) for row in rows]
        for row in result:
            row['ota_inference_eligible'] = str(row.get('transaction_id')) in eligible
            row['ota_review_held'] = row.get('transaction_id') in review_held
        return result

    def _data(self):
        events = self.payments.build_ota_payment_events(self.sources)
        transactions = self._transactions()
        stored_events = self._stored_manual_events()
        manual_links, id_crosswalk = _manual_link_crosswalk(
            events, self.store.links(), stored_events,
            getattr(self.store, "event_crosswalks", lambda: {})())
        canonical_by_id = {str(event.get("ota_event_id")): event for event in events}
        # The app.ota_payments solver is the single decision owner. Historical
        # mail/portal exact matches remain available as diagnostics, but cannot
        # occupy a card or affect group allocation without a user pin.
        links = dict(manual_links)
        stale_manual_ids = set()
        old_ids_by_current = {new: old for old, new in id_crosswalk.items()}
        for event_id, link in manual_links.items():
            old_id = old_ids_by_current.get(str(event_id), str(event_id))
            current = canonical_by_id.get(str(event_id))
            stored = stored_events.get(old_id)
            proof_missing = current is None or not self._has_payment_proof(current)
            if not proof_missing or not stored:
                continue
            stale_manual_ids.add(str(event_id))
            display_event = dict(stored)
            display_event["ota_event_id"] = str(event_id)
            display_event.update(evidence_missing=True, evidence_changed=True,
                                review_warning="manual_link_evidence_missing")
            if current is None:
                events.append(display_event)
            else:
                events = [display_event if str(event.get("ota_event_id")) == str(event_id) else event
                          for event in events]
        rules = self.store.active_rules()
        frozen_groups = self.store.group_pins() if callable(getattr(self.store, "group_pins", None)) else []
        confirmed_reservation_links = _store_value(self.store, "reservation_links", {})
        reservation_card_ids = {
            str(link.get("transaction_id") or "")
            for link in confirmed_reservation_links.values()
            if isinstance(link, dict) and link.get("transaction_id")
        }
        # Reservation relations occupy a card for solver purposes only. Keep the
        # complete transaction set for reservation candidate search and display.
        solver_transactions = [row for row in transactions
                              if str(row.get("transaction_id") or "") not in reservation_card_ids]
        try:
            results = self.payments.match_ota_payment_events(
                events, solver_transactions, existing_links=links, rules=rules,
                frozen_groups=frozen_groups)
        except TypeError as exc:
            if "unexpected keyword argument 'frozen_groups'" not in str(exc):
                raise
            results = self.payments.match_ota_payment_events(
                events, solver_transactions, existing_links=links, rules=rules)
        result_ids = {str(result.get("ota_event_id")): index for index, result in enumerate(results)}
        for event_id in stale_manual_ids:
            index = result_ids.get(event_id)
            if index is None:
                results.append({"ota_event_id": event_id, "status": "MATCHED_USER",
                                "transaction_id": _link_transaction_id(manual_links[event_id])})
                index = len(results) - 1
            results[index].update(evidence_missing=True, evidence_changed=True,
                                  review_warning="manual_link_evidence_missing",
                                  reason="결제 근거가 사라졌습니다. 기존 수동 연결은 유지되며 새 거래로 다시 연결되지 않습니다.")
        candidate_search = getattr(self.payments, "search_card_candidates", None)
        raw_reservation_searches = {}
        occupied_cards = {
            transaction_id for transaction_id in
            (_link_transaction_id(link) for link in links.values()) if transaction_id
        }
        for result in results:
            if result.get("status") in ("MATCHED_AUTO", "MATCHED_USER") and result.get("transaction_id"):
                occupied_cards.add(str(result["transaction_id"]))
            occupied_cards.update(str(identity) for identity in result.get("reserved_card_ids") or ())
        if callable(candidate_search):
            for result in results:
                event_id = str(result.get("ota_event_id") or "")
                event = canonical_by_id.get(event_id)
                if (not event or result.get("status") not in
                        ("HOLD_DATE_UNKNOWN", "HOLD_NO_CARD", "HOLD_AMOUNT_MISMATCH", "HOLD_AMOUNT_UNVERIFIED", "RESERVATION_ONLY") or
                        result.get("evidence_missing") or result.get("evidence_changed")):
                    continue
                trace = candidate_search(event, transactions, existing_links=links, rules=rules)
                if event.get("provider") == "toyoko" and event.get("event_type") == "reservation":
                    raw_reservation_searches[event_id] = dict(trace,
                        candidates=[dict(candidate) for candidate in trace.get("candidates") or ()],
                        rejected=[dict(candidate) for candidate in trace.get("rejected") or ()])
                trace["candidates"] = [candidate for candidate in trace.get("candidates") or ()
                                       if str(candidate.get("transaction_id") or "") not in occupied_cards]
                trace["rejected"] = [candidate for candidate in trace.get("rejected") or ()
                                     if str(candidate.get("transaction_id") or "") not in occupied_cards]
                if not trace["candidates"] and trace.get("status") == "CANDIDATES_FOUND":
                    trace["status"] = "NO_CANDIDATE"
                result["candidate_search"] = trace
        from app.toyoko_reservation_links import infer_links, relation_digest as _reservation_relation_digest
        toyoko_events = [event for event in events if event.get("provider") == "toyoko"
                         and event.get("event_type") == "reservation"]
        confirmed = _store_value(self.store, "reservation_links", {})
        card_by_id = {str(card.get("transaction_id") or ""): card for card in transactions}
        relation_occupied = set(occupied_cards)
        for pin in frozen_groups:
            relation_occupied.update(map(str, pin.get("card_ids") or ()))
        relations = infer_links(toyoko_events,
            raw_reservation_searches, confirmed, occupied_transaction_ids=relation_occupied)
        for result in results:
            event_id = str(result.get("ota_event_id") or "")
            if event_id in relations:
                relation = relations[event_id]
                saved = confirmed.get(event_id)
                stored_transaction = (saved or {}).get("transaction") or {}
                current_transaction = card_by_id.get(str((saved or {}).get("transaction_id") or ""))
                stale = bool(saved and (not canonical_by_id.get(event_id) or not current_transaction or
                    _reservation_relation_digest(saved.get("event") or {}, stored_transaction) !=
                    _reservation_relation_digest(canonical_by_id[event_id], current_transaction) or
                    str((saved or {}).get("transaction_id") or "") in relation_occupied))
                if stale:
                    relation = dict(relation, status="STALE", payment_verified=False)
                result["reservation_link"] = {key: relation.get(key) for key in
                    ("status", "transaction_id", "basis", "amount_status", "payment_verified")}
        for event_id, saved in confirmed.items():
            if str(event_id) in canonical_by_id:
                continue
            historical_event = dict(saved.get("event") or {})
            historical_event.update(ota_event_id=str(event_id), evidence_missing=True,
                                   evidence_changed=True, review_warning="reservation_event_missing")
            events.append(historical_event)
            results.append({"ota_event_id": str(event_id), "status": "RESERVATION_ONLY",
                            "evidence_missing": True, "evidence_changed": True,
                            "candidate_search": {"status": "NO_CANDIDATE", "candidates": [], "rejected": []},
                            "reservation_link": {"status": "STALE",
                                "transaction_id": str(saved.get("transaction_id") or ""),
                                "basis": saved.get("basis"), "amount_status": saved.get("amount_status"),
                                "payment_verified": False}})
        return events, transactions, links, results

    def reservation_preview(self, event_id, transaction_id):
        if self.read_only:
            raise RuntimeError("read-only OTA backend cannot preview a reservation write")
        data, _snapshot = self._action_data()
        events, transactions, links, results = data["events"], data["transactions"], data["links"], data["results"]
        event = next((row for row in events if str(row.get("ota_event_id")) == str(event_id)), None)
        transaction = next((row for row in transactions if str(row.get("transaction_id")) == str(transaction_id)), None)
        result = next((row for row in results if str(row.get("ota_event_id")) == str(event_id)), None)
        if (not event or event.get("provider") != "toyoko" or not transaction or not result
                or result.get("status") == "HOLD_EVIDENCE_CONFLICT"):
            raise InvalidReviewInput("reservation relation is not selectable")
        occupied = self._occupied_cards(links, results)
        confirmed = _store_value(self.store, "reservation_links", {})
        for linked_event, relation in confirmed.items():
            if str(linked_event) == str(event_id):
                continue
            linked_card = str(relation.get("transaction_id") or "")
            if linked_card:
                occupied.setdefault(linked_card, (str(linked_event), "예약 관계 확인"))
        if str(transaction_id) in occupied:
            raise InvalidReviewInput("card transaction is already linked")
        trace = result.get("candidate_search") or {}
        if str(transaction_id) not in {str(row.get("transaction_id")) for row in trace.get("candidates") or ()}:
            raise InvalidReviewInput("card is not a current reservation candidate")
        preview = self.store.reservation_preview(event, transaction)
        existing = _store_value(self.store, "reservation_links", {}).get(str(event_id), {})
        event_amount = event.get("amount")
        card_amount = transaction.get("foreign_amount")
        event_currency = str(event.get("currency") or "").upper()
        card_currency = str(transaction.get("foreign_currency") or transaction.get("currency") or "").upper()
        if event_currency == "KRW":
            comparable = True
            event_amount_for_diff = event.get("amount_krw", event_amount)
            card_amount_for_diff = transaction.get("amount_krw")
        else:
            comparable = bool(event_currency and card_currency == event_currency and
                              transaction.get("foreign_amount") not in (None, ""))
            event_amount_for_diff = event_amount
            card_amount_for_diff = card_amount
        try:
            difference = (float(card_amount_for_diff) - float(event_amount_for_diff)) if comparable and event_amount_for_diff is not None and card_amount_for_diff is not None else None
        except (TypeError, ValueError):
            difference = None
        return dict(preview, expected_revision=int(existing.get("revision", 0)),
                    hotel_name=event.get("hotel_name"), service_period=event.get("service_period"),
                    reservation_amount=event_amount, reservation_currency=event.get("currency"),
                    card_merchant=transaction.get("merchant"), card_foreign_amount=card_amount,
                    card_currency=transaction.get("foreign_currency") or transaction.get("currency"),
                    card_amount_krw=transaction.get("amount_krw"), amount_difference=difference,
                    payment_verified=False)

    def reservation_confirm(self, event_id, transaction_id, preview_digest, *,
                            expected_revision, request_id, user):
        if self.read_only:
            raise RuntimeError("read-only OTA backend cannot confirm a reservation relation")
        replay = self.store.prior_reservation_confirmation(request_id, event_id, transaction_id,
                                                           preview_digest, expected_revision, user)
        if replay is not None:
            return replay
        data, _snapshot = self._action_data()
        preview = self.reservation_preview(event_id, transaction_id)
        if preview["preview_digest"] != preview_digest:
            raise StalePreviewError
        events, transactions, links, results = data["events"], data["transactions"], data["links"], data["results"]
        event = next(row for row in events if str(row.get("ota_event_id")) == str(event_id))
        transaction = next(row for row in transactions if str(row.get("transaction_id")) == str(transaction_id))
        occupied = self._occupied_cards(links, results)
        for linked_event, relation in _store_value(self.store, "reservation_links", {}).items():
            if str(linked_event) == str(event_id):
                continue
            linked_card = str(relation.get("transaction_id") or "")
            if linked_card:
                occupied.setdefault(linked_card, (str(linked_event), "예약 관계 확인"))
        current, snapshot = self._action_data()
        if (input_key_for(self) != _snapshot["key"] or
                ota_snapshot.digest([data["events"], data["transactions"], data["results"]]) !=
                ota_snapshot.digest([current["events"], current["transactions"], current["results"]])):
            raise StalePreviewError
        return self.store.confirm_reservation(event, transaction, preview_digest,
            expected_revision=expected_revision, request_id=request_id, user=user,
            amount_status=next((c.get("amount_status") for c in
                (next(r for r in current["results"] if str(r.get("ota_event_id")) == str(event_id))
                 .get("candidate_search") or {}).get("candidates", ())
                if str(c.get("transaction_id")) == str(transaction_id)), "UNKNOWN"))

    def _has_payment_proof(self, event):
        checker = getattr(self.payments, "_event_is_paid", None)
        if callable(checker):
            return bool(checker(event))
        return True

    def _stored_manual_events(self):
        """Read persisted event snapshots using the core's read-only store API."""
        reader = getattr(self.store, "event_snapshots", None)
        if not callable(reader):
            return {}
        try:
            snapshots = reader()
        except Exception:
            return {}
        return {str(event_id): dict(event) for event_id, event in snapshots.items()
                if isinstance(event, dict)} if isinstance(snapshots, dict) else {}

    def _event_rows(self, event, transactions, links, rules=None):
        try:
            rows = self.payments.same_date_cards(event, transactions, links=links, rules=rules)
        except TypeError as exc:
            if "unexpected keyword argument 'rules'" not in str(exc):
                raise
            rows = self.payments.same_date_cards(event, transactions, links=links)
        return [dict(row) for row in rows]

    def _occupied_cards(self, links, results):
        occupied = {}
        pins = self.store.group_pins() if callable(getattr(self.store, "group_pins", None)) else []
        for pin in pins:
            for transaction_id in pin.get("card_ids", ()):
                occupied.setdefault(str(transaction_id),
                                    ("|".join(map(str, pin.get("event_ids", ()))), "confirmed_group_reservation"))
        for event_id, link in links.items():
            transaction_id = _link_transaction_id(link)
            if transaction_id:
                occupied[transaction_id] = (str(event_id), "기존 연결")
        for result in results:
            for transaction_id in result.get("reserved_card_ids", ()):
                occupied.setdefault(str(transaction_id),
                                    (str(result.get("ota_event_id") or ""), "partial_group_reservation"))
            if result.get("status") in ("MATCHED_AUTO", "MATCHED_USER") and result.get("transaction_id"):
                occupied.setdefault(str(result["transaction_id"]),
                                    (str(result.get("ota_event_id") or ""),
                                     "추론 연결" if result.get('inferred_link') else
                                     "자동 연결" if result["status"] == "MATCHED_AUTO" else "사용자 확정 연결"))
        return occupied

    def snapshot(self):
        return self.snapshot_from(self._data())

    def _build_event_card_rows(self, event, result, event_by_id, card_by_id, transactions, links, rules, occupied, confirmed, *, build_rows=True):
        """Build card rows for a single event using shared financial post-processing logic.

        This is the single source of truth for card row construction, used by both
        snapshot_from (for all events) and cards_for_event (for a single event).

        Args:
            build_rows: If False, only compute candidate count and metadata without
                constructing full card rows. Used by public snapshot (include_cards=False)
                to avoid 500MB+ payload duplication.
        """
        event_id = str(result.get("ota_event_id") or "")
        event_source = event_by_id.get(event_id, {})
        link = links.get(event_id) or {}
        stored_digest = link.get("source_digest") if isinstance(link, dict) else None
        source_changed = bool(isinstance(link, dict) and link.get("evidence_changed"))
        source_changed = source_changed or bool(stored_digest and event_source.get("source_digest")
                                                and stored_digest != event_source.get("source_digest"))
        source_changed = source_changed or bool(event_source.get("evidence_changed"))
        evidence_missing = bool(event_source.get("evidence_missing") or result.get("evidence_missing"))
        is_hold = str(result.get("status") or "").startswith("HOLD")
        is_changed_manual = result.get("status") == "MATCHED_USER" and (source_changed or evidence_missing)
        is_ordered_group = result.get("allocation_basis") in (
            "user_approved_stable_order", "frozen_user_confirmed_order",
            "user_confirmed_group_required")
        trace = result.get('candidate_search') or {}
        is_reservation_candidate = (result.get('status') == 'RESERVATION_ONLY'
                                    and bool(trace.get('candidates') or trace.get('rejected')))
        relation = result.get("reservation_link") or {}
        saved_relation = confirmed.get(event_id) or {}
        saved_card = card_by_id.get(str(relation.get("transaction_id") or ""))
        if saved_card:
            relation["merchant"] = saved_card.get("merchant")
            relation["approval_date"] = saved_card.get("approval_date") or saved_card.get("posting_date")
            relation["amount_krw"] = saved_card.get("amount_krw")
        elif saved_relation:
            relation["historical_card_missing"] = True
        relation["revision"] = saved_relation.get("revision")
        has_reservation_relation = relation.get("status") in ("INFERRED", "USER_CONFIRMED", "STALE")

        # Determine if this event should be in the hold list (needs card display)
        show_in_holds = (is_hold or is_changed_manual or is_ordered_group
                         or is_reservation_candidate or has_reservation_relation)

        # Build base event data for hold list
        event_data = {**event_by_id.get(event_id, {}), **result}
        search = result.get("candidate_search") or {}
        event_data["candidate_search_status"] = search.get("status")
        event_data["candidate_date_status"] = search.get("date_status")
        event_data["candidate_count"] = len(search.get("candidates") or [])
        event_data["candidate_rejected_count"] = len(search.get("rejected") or [])
        if source_changed:
            event_data["evidence_changed"] = True
            event_data["review_warning"] = "source_changed_after_exact_link"
            if result.get("status") == "HOLD_EVIDENCE_CONFLICT":
                event_data["reason"] = "기존 연결 뒤 결제 근거가 바뀌었습니다. 예전 카드 거래를 유지하고 새 연결을 다시 추론하지 않습니다."
        if is_changed_manual:
            event_data["evidence_changed"] = True
            event_data["evidence_missing"] = evidence_missing
            event_data["review_warning"] = "manual_link_evidence_missing" if evidence_missing else "source_changed_after_manual_link"
            event_data["reason"] = ("결제 근거가 사라졌습니다. 기존 수동 연결은 유지되며 새 거래로 다시 연결되지 않습니다."
                                   if evidence_missing else
                                   "수동 연결 뒤 결제 근거가 바뀌었습니다. 연결을 유지한 채 다시 확인해 주세요.")

        # Compute candidate count WITHOUT building rows (used by public snapshot)
        # Count reservation candidates that are NOT already linked to another event
        candidate_count = 0
        if search.get("candidates"):
            for candidate in search["candidates"]:
                transaction_id = str(candidate.get("transaction_id") or "")
                owner = occupied.get(transaction_id)
                if not (owner and str(owner[0]) != event_id):
                    candidate_count += 1

        # Only build full rows when explicitly requested
        # Also build for MATCHED_AUTO/MATCHED_USER events which have linked transactions
        is_matched = result.get("status") in ("MATCHED_AUTO", "MATCHED_USER")
        rows = []
        if build_rows and (show_in_holds or is_matched):
            rows = self._event_rows(event_data, transactions, links, rules)
            visible_ids = {str(row.get("transaction_id") or "") for row in rows}
            transaction_by_id = {str(row.get("transaction_id") or ""): row for row in transactions}
            relation = result.get("reservation_link") or {}
            candidate_by_id = {str(candidate.get("transaction_id") or ""): candidate
                               for candidate in search.get("candidates") or ()}
            for row in rows:
                candidate = candidate_by_id.get(str(row.get("transaction_id") or ""))
                if candidate:
                    row.update(reservation_candidate=True,
                               reservation_candidate_basis=candidate.get("basis"),
                               reservation_amount_status=candidate.get("amount_status"),
                               reservation_stay_date_status=candidate.get("stay_date_status"))
            for candidate in search.get("candidates") or ():
                transaction_id = str(candidate.get("transaction_id") or "")
                card = transaction_by_id.get(transaction_id)
                if not card or transaction_id in visible_ids:
                    continue
                date_status = str(candidate.get("date_status") or "UNKNOWN")
                rows.append(dict(card, candidate_date_status=date_status,
                                 candidate_resolution_allowed=bool(candidate.get("resolution_allowed")),
                                 reservation_candidate=True,
                                 reservation_candidate_basis=candidate.get("basis"),
                                 reservation_amount_status=candidate.get("amount_status"),
                                 reservation_stay_date_status=candidate.get("stay_date_status"),
                                 selection_disabled=True,
                                 selection_disabled_reason=(
                                     "같은 호텔·숙박기간의 후보지만 원문 금액이 달라 결제 연결은 확정할 수 없습니다."
                                     if candidate.get('basis') == 'HOTEL_BRANCH_AND_STAY_ONLY' else
                                     "OTA 결제일이 없어 결제 검증은 불가합니다. 동일 외화 금액은 후보 근거일 뿐입니다. 예약 관계는 아래 별도 미리보기에서 수동 확인할 수 있습니다."
                                     if date_status == "UNKNOWN" else
                                     "결제일이 맞지 않아 OTA 예약 연결은 확정할 수 없습니다.")))
                visible_ids.add(transaction_id)
            if relation.get("status") in ("USER_CONFIRMED", "STALE"):
                historical_id = str(relation.get("transaction_id") or "")
                historical = transaction_by_id.get(historical_id)
                if historical:
                    existing = next((row for row in rows
                                     if str(row.get("transaction_id") or "") == historical_id), None)
                    historical_fields = {
                        "reservation_history": True,
                        "selection_disabled": True,
                        "selection_disabled_reason": "저장한 예약 관계의 선택 이력입니다.",
                    }
                    if existing is not None:
                        existing.update(historical_fields)
                    elif historical_id not in visible_ids:
                        rows.append(dict(historical, **historical_fields))
                    visible_ids.add(historical_id)
            for rejected in search.get("rejected") or ():
                transaction_id = str(rejected.get("transaction_id") or "")
                card = transaction_by_id.get(transaction_id)
                if not card:
                    continue
                reason = str(rejected.get("reason") or "NO_CARD_CANDIDATE")
                rejected_fields = {
                    "candidate_date_status": "MISMATCH",
                    "candidate_resolution_allowed": False,
                    "candidate_rejection_reason": reason,
                    "selection_disabled": True,
                    "selection_disabled_reason": _OTA_REASON.get(reason, "필수 연결 근거가 부족합니다."),
                }
                existing = next((row for row in rows
                                 if str(row.get("transaction_id") or "") == transaction_id), None)
                if existing is not None:
                    existing.update(rejected_fields)
                elif transaction_id not in visible_ids:
                    rows.append(dict(card, **rejected_fields))
                visible_ids.add(transaction_id)

            # Apply shared post-processing (occupied, group holds, hold states, etc.)
            for row in rows:
                if result.get("status") in ("HOLD_PARTIAL_GROUP", "HOLD_GROUP_CONFIRMATION_REQUIRED") or is_ordered_group:
                    row["selection_disabled"] = True
                    row["selection_disabled_reason"] = (
                        "반복 결제 묶음이 부분 대응 상태라 개별 연결과 장부 배정을 보류합니다."
                        if result.get("status") == "HOLD_PARTIAL_GROUP" else
                        "사용자 승인 순서로 반복 거래를 배정했습니다. 개별 결제 근거가 확인된 연결은 아닙니다.")
                owner = occupied.get(str(row.get("transaction_id") or ""))
                if owner and str(owner[0]) != event_id:
                    row["already_linked_event_id"] = owner[0]
                    row["already_linked_reason"] = owner[1]
                    row["already_linked_label"] = _event_label(event_by_id, owner[0])
                    if owner[1] in ("partial_group_reservation", "confirmed_group_reservation"):
                        row["selection_disabled"] = True
                        row["selection_disabled_reason"] = (
                            "부분 반복 그룹의 카드 후보로 예약되어 있어 개별 연결할 수 없습니다."
                            if owner[1] == "partial_group_reservation" else
                            "사용자가 확정한 반복 그룹의 카드로 개별 연결할 수 없습니다.")
                    elif owner[1] == "다른 예약에서 관계 확인":
                        row["selection_disabled"] = True
                        row["selection_disabled_reason"] = "다른 예약에 이미 관계 확인된 카드입니다."

        return event_data, rows, candidate_count

    def snapshot_from(self, data, *, include_cards=True):
        events, transactions, links, results = data
        rules = self.store.active_rules()
        confirmed = _store_value(self.store, "reservation_links", {})
        event_by_id = {str(event.get("ota_event_id")): event for event in events}
        card_by_id = {str(card.get("transaction_id") or ""): card for card in transactions}
        occupied = self._occupied_cards(links, results)
        for relation_event, relation in confirmed.items():
            transaction_id = str(relation.get("transaction_id") or "")
            if transaction_id:
                occupied.setdefault(transaction_id, (str(relation_event), "다른 예약에서 관계 확인"))
        holds, cards_by_event = [], {}
        for result in results:
            event_id = str(result.get("ota_event_id") or "")
            event_source = event_by_id.get(event_id, {})
            link = links.get(event_id) or {}
            stored_digest = link.get("source_digest") if isinstance(link, dict) else None
            source_changed = bool(isinstance(link, dict) and link.get("evidence_changed"))
            source_changed = source_changed or bool(stored_digest and event_source.get("source_digest")
                                                    and stored_digest != event_source.get("source_digest"))
            source_changed = source_changed or bool(event_source.get("evidence_changed"))
            evidence_missing = bool(event_source.get("evidence_missing") or result.get("evidence_missing"))
            is_hold = str(result.get("status") or "").startswith("HOLD")
            is_changed_manual = result.get("status") == "MATCHED_USER" and (source_changed or evidence_missing)
            is_ordered_group = result.get("allocation_basis") in (
                "user_approved_stable_order", "frozen_user_confirmed_order",
                "user_confirmed_group_required")
            trace = result.get('candidate_search') or {}
            is_reservation_candidate = (result.get('status') == 'RESERVATION_ONLY'
                                        and bool(trace.get('candidates') or trace.get('rejected')))
            relation = result.get("reservation_link") or {}
            saved_relation = confirmed.get(event_id) or {}
            saved_card = card_by_id.get(str(relation.get("transaction_id") or ""))
            if saved_card:
                relation["merchant"] = saved_card.get("merchant")
                relation["approval_date"] = saved_card.get("approval_date") or saved_card.get("posting_date")
                relation["amount_krw"] = saved_card.get("amount_krw")
            elif saved_relation:
                relation["historical_card_missing"] = True
            relation["revision"] = saved_relation.get("revision")
            has_reservation_relation = relation.get("status") in ("INFERRED", "USER_CONFIRMED", "STALE")
            if (not is_hold and not is_changed_manual and not is_ordered_group
                    and not is_reservation_candidate and not has_reservation_relation):
                continue
            event = {**event_by_id.get(event_id, {}), **result}
            search = result.get("candidate_search") or {}
            event["candidate_search_status"] = search.get("status")
            # Use shared card row builder (build_rows=include_cards avoids 500MB+ duplication)
            event_data, rows, candidate_count = self._build_event_card_rows(
                event, result, event_by_id, card_by_id, transactions, links, rules, occupied, confirmed, build_rows=include_cards)
            holds.append(event_data)
            event_data["card_candidate_count"] = candidate_count
            if include_cards:
                cards_by_event[event_id] = rows
        proposals = [proposal for proposal in self.store.proposals()
                     if proposal.get("status") == "pending"]
        return public_snapshot({"events": holds, "cards_by_event": cards_by_event, "proposals": proposals}, include_cards=include_cards)

    def snapshot_view(self):
        """The request path: the last reconciled snapshot and its status, without computing anything."""
        return snapshot_service(self.board).view()

    def cards_for_event(self, event_id):
        """Return processed card rows for a single event, using the same logic as snapshot_from."""
        data, _snapshot = self._action_data()
        events, transactions, links, results = (data[key] for key in ('events', 'transactions', 'links', 'results'))
        event_by_id = {str(event.get("ota_event_id")): event for event in events}
        card_by_id = {str(card.get("transaction_id") or ""): card for card in transactions}
        rules = self.store.active_rules()
        confirmed = _store_value(self.store, "reservation_links", {})
        occupied = self._occupied_cards(links, results)
        for relation_event, relation in confirmed.items():
            transaction_id = str(relation.get("transaction_id") or "")
            if transaction_id:
                occupied.setdefault(transaction_id, (str(relation_event), "다른 예약에서 관계 확인"))

        result = next((row for row in results if str(row.get("ota_event_id") or "") == str(event_id)), None)
        if not result:
            return []

        # Use shared card row builder - always build rows for per-event endpoint
        dummy_event = event_by_id.get(str(event_id), {})
        _, rows, _ = self._build_event_card_rows(
            dummy_event, result, event_by_id, card_by_id, transactions, links, rules, occupied, confirmed, build_rows=True)

        return rows

    def request_refresh(self):
        snapshot_service(self.board).request_check(wait_seconds=0)

    def _action_data(self):
        """The reconciled data an action may use: fresh, complete, and matching the input fingerprint now.

        Returns (data, snapshot) where snapshot is {generation, key}. Never reconciles on the request thread.
        """
        service = snapshot_service(self.board)
        context, reason = service.action_context()
        if context is None:
            raise OtaSnapshotNotReady(reason)
        if input_key_for(self) != context["key"]:
            service.request_check()
            raise StalePreviewError
        return context["data"], {"generation": context["generation"], "key": context["key"]}

    def _action_digest(self, event, transaction, core_digest, data, snapshot):
        """What a human confirmed: the snapshot identity, the exact event and card, and every state that
        could change the answer (rules, proposals, occupancy, source evidence)."""
        occupied = self._occupied_cards(data["links"], data["results"])
        return ota_snapshot.digest({
            "snapshot": [snapshot["generation"], snapshot["key"]],
            "event_id": str(event.get("ota_event_id")),
            "transaction_id": str(transaction.get("transaction_id")),
            "amounts": [event.get("amount_krw"), transaction.get("amount_krw")],
            "directions": [event.get("event_type"), transaction.get("transaction_direction")],
            "rules": self.store.active_rules(),
            "proposals": [p for p in self.store.proposals() if p.get("status") == "pending"],
            "occupancy": sorted((key, list(value)) for key, value in occupied.items()),
            "evidence": event,
            "core": core_digest,
        })

    def _selection(self, event_id, transaction_id, data=None):
        if data is None:
            events, transactions, links, results = self._data()
        else:
            events, transactions, links, results = (data["events"], data["transactions"],
                                                    data["links"], data["results"])
        event = next((row for row in events if str(row.get("ota_event_id")) == event_id), None)
        result = next((row for row in results if str(row.get("ota_event_id")) == event_id), None)
        if (event is None or result is None or result.get("status") in
                ("HOLD_PARTIAL_GROUP", "HOLD_GROUP_CHANGED", "HOLD_GROUP_CONFIRMATION_REQUIRED")
                or not str(result.get("status") or "").startswith("HOLD")
                or not event.get("paid_on")):
            raise InvalidReviewInput("only an OTA hold can be manually linked")
        transaction = next((row for row in transactions
                            if str(row.get("transaction_id")) == transaction_id), None)
        if transaction is None:
            raise InvalidReviewInput("card transaction does not exist")
        if _transaction_selection_block_reason(transaction):
            raise InvalidReviewInput("card transaction is not selectable")
        rows = self._event_rows(event, transactions, links, self.store.active_rules())
        visible_ids = {str(row.get("transaction_id")) for row in rows}
        if transaction_id not in visible_ids:
            raise InvalidReviewInput("card transaction is not on the payment date")
        occupied = self._occupied_cards(links, results)
        if transaction_id in occupied:
            raise InvalidReviewInput("card transaction is already linked")
        allocations = {str(row.get("ota_event_id")): str(row.get("transaction_id"))
                       for row in results
                       if row.get("status") in ("MATCHED_AUTO", "MATCHED_USER")
                       and row.get("ota_event_id") and row.get("transaction_id")}
        allocations.update({str(identity): _link_transaction_id(link)
                            for identity, link in links.items() if _link_transaction_id(link)})
        return event, transaction, allocations

    def preview(self, event_id, transaction_id):
        data, snapshot = self._action_data()
        event, transaction, _allocations = self._selection(event_id, transaction_id, data)
        preview = self.store.preview(event, transaction)
        if not isinstance(preview, dict) or not preview.get("preview_digest"):
            raise RuntimeError("core preview must return preview_digest")
        event_amount = event.get("amount_krw")
        card_amount = transaction.get("amount_krw")
        return {"preview_digest": self._action_digest(event, transaction, preview["preview_digest"], data, snapshot),
                "snapshot_generation": snapshot["generation"],
                "event_amount_krw": event_amount, "card_amount_krw": card_amount,
                "difference_krw": (card_amount - event_amount
                                   if isinstance(card_amount, int) and isinstance(event_amount, int)
                                   else None),
                "differences": preview.get("differences", {})}

    def confirm(self, event_id, transaction_id, preview_digest, *, request_id, user):
        if self.read_only:
            raise RuntimeError("read-only OTA backend cannot confirm")
        # A retry of an already recorded request returns that record, before any freshness check.
        reader = getattr(self.store, "prior_confirmation", None)
        prior = reader(request_id) if callable(reader) else None
        if prior is not None:
            return prior
        data, snapshot = self._action_data()
        event, transaction, allocations = self._selection(event_id, transaction_id, data)
        core_digest = self.store.preview(event, transaction)["preview_digest"]
        if self._action_digest(event, transaction, core_digest, data, snapshot) != preview_digest:
            raise StalePreviewError
        # Written last, after the fingerprint is read again: a change in between refuses the whole write.
        if input_key_for(self) != snapshot["key"]:
            snapshot_service(self.board).request_check()
            raise StalePreviewError
        try:
            _manual, id_crosswalk = _manual_link_crosswalk(
                data["events"], self.store.links(), self._stored_manual_events(),
                getattr(self.store, "event_crosswalks", lambda: {})())
            confirm_options = {"request_id": request_id, "user": user,
                               "allocations": allocations}
            if id_crosswalk:
                confirm_options["id_crosswalk"] = id_crosswalk
            return self.store.confirm(event, transaction, core_digest,
                                      **confirm_options)
        except Exception as exc:
            if (getattr(exc, "code", "") == "STALE_PREVIEW" or
                    "STALE_PREVIEW" in str(exc) or "stale" in type(exc).__name__.lower()):
                raise StalePreviewError from exc
            raise

    def answer_proposal(self, proposal_id, action, *, user, conditions=None):
        if self.read_only:
            raise RuntimeError("read-only OTA backend cannot answer proposals")
        result = self.store.answer_proposal(proposal_id, action, user=user, conditions=conditions)
        result = dict(result)
        result["status"] = {"once": "answered_once", "approve": "approved", "edit": "edited"}[action]
        return result

    def confirm_group_order(self, event_ids, *, user, replace=False, request_id=None):
        if self.read_only:
            raise RuntimeError("read-only OTA backend cannot freeze group order")
        _events, _transactions, _links, results = self._data()
        selected = [row for row in results if str(row.get("ota_event_id")) in set(event_ids)]
        if not selected or len(selected) != len(set(event_ids)):
            raise InvalidReviewInput("group order proposal is stale or incomplete")
        if replace:
            if any(row.get("status") != "HOLD_GROUP_CHANGED" or
                   row.get("review_warning") != "confirm_group_reallocation" for row in selected):
                raise InvalidReviewInput("changed group requires a fresh confirmation proposal")
            mapping = selected[0].get("proposed_mapping") or {}
        else:
            allowed = all((row.get("status") == "MATCHED_AUTO" and
                           row.get("allocation_basis") == "user_approved_stable_order") or
                          (row.get("status") == "HOLD_GROUP_CONFIRMATION_REQUIRED" and
                           row.get("allocation_basis") == "user_confirmed_group_required")
                          for row in selected)
            if not allowed:
                raise InvalidReviewInput("group order proposal is stale or incomplete")
            mapping = {}
            for row in selected:
                if row.get("status") == "HOLD_GROUP_CONFIRMATION_REQUIRED":
                    mapping.update({str(key):str(value) for key,value in
                                    (row.get("proposed_mapping") or {}).items()})
                else:
                    mapping[str(row["ota_event_id"])] = str(row["transaction_id"])
        expected_events = set(selected[0].get("ota_group_ids", ()))
        expected_cards = set(selected[0].get("card_group_ids", ()))
        if set(event_ids) != expected_events or any(set(row.get("ota_group_ids", ())) != expected_events or
                                                    set(row.get("card_group_ids", ())) != expected_cards
                                                    for row in selected):
            raise InvalidReviewInput("group order proposal changed")
        return self.store.confirm_group_order(sorted(expected_events), sorted(expected_cards), mapping,
                                              user=user, replace=replace,
                                              order_snapshot=selected[0].get("group_order_snapshot"),
                                              request_id=request_id)

    def close(self):
        self.store.close()

    def refresh_after_import(self, transaction_ids):
        if self.read_only:
            raise RuntimeError("read-only OTA backend cannot refresh")
        changed_transactions = sorted({str(identity) for identity in transaction_ids if str(identity)})
        if not changed_transactions:
            return {"status": "skipped", "changed_transaction_ids": [], "changed_event_ids": []}
        events, transactions, links, _results = self._data()
        changed_events = self._changed_event_ids(events, links)
        refreshed = self.store.refresh(events, transactions,
                                       changed_transaction_ids=changed_transactions,
                                       changed_event_ids=changed_events)
        return {"status": "refreshed", "changed_transaction_ids": changed_transactions,
                "changed_event_ids": changed_events,
                "refreshed_events": len(refreshed or []) if isinstance(refreshed, list) else 0}

    @staticmethod
    def _changed_event_ids(events, links):
        changed = []
        for event in events:
            link = links.get(str(event.get("ota_event_id") or "")) or {}
            old_digest = link.get("source_digest") if isinstance(link, dict) else None
            new_digest = event.get("source_digest")
            if old_digest and new_digest and old_digest != new_digest:
                changed.append(str(event["ota_event_id"]))
        return sorted(changed)


SNAPSHOT_FILE = "ota-snapshot.json"


def _store_value(store, name, default):
    method = getattr(store, name, None)
    return method() if callable(method) else default


def input_key_for(backend) -> str:
    """Every input a reconciliation reads, from one backend. Source files are keyed by content, never by size or time."""
    from app import ota_sources, flight_evidence
    from app.ota_matching_defaults import load_defaults
    store = backend.store
    return ota_snapshot.digest({
        "schema": ota_snapshot.SCHEMA,
        "sources": ota_sources.source_stamps(backend.sources),
        "transactions": backend._transactions(),
        "review": {"links": _store_value(store, "links", {}),
                   "rules": _store_value(store, "active_rules", []),
                   "proposals": _store_value(store, "proposals", []),
                   "pins": _store_value(store, "group_pins", []),
                   "events": _store_value(store, "event_snapshots", {}),
                   "reservation_links": _store_value(store, "reservation_links", {})},
        "matching": load_defaults(),
        "payment_parser": getattr(getattr(backend, 'payments', None), 'PARSER_VERSION', 1),
        "payment_matcher": getattr(getattr(backend, 'payments', None), 'MATCHER_VERSION', 1),
        "passenger_index_schema": PASSENGER_SCHEMA,
        "flight_parser": flight_evidence.PARSER_VERSION,
        "guide_airfare": _guide_input_digest(backend.board),
    })


def _guide_input_digest(board) -> str:
    """Guide identity, trip authority and parser state. An unreadable state is a distinct, stable value."""
    from . import guide_airfare_review
    try:
        return guide_airfare_review.input_digest(board)
    except Exception as exc:
        return "unreadable:" + type(exc).__name__


def input_key(board) -> str:
    """The worker's fingerprint. It alone refreshes the reservation authority (a network read)."""
    from . import guide_airfare_review
    guide_airfare_review.refresh_authority(board)
    backend = CoreOtaPaymentBackend.from_host(board, read_only=True)
    try:
        return input_key_for(backend)
    finally:
        backend.close()


def scheduled_card_settlements(sources, transactions, occupied):
    """Card rows a portal auto-charge scheduled for their use date settle in authority mode (owner decision 2)."""
    from app import ota_portal
    databases = sources.get("portal_databases", [])
    # 규칙이 읽는 열이 없는 최소 투영 자료는 건너뛴다. 운영 자료는 전체 열을 가진다.
    if not databases or any(not {"transaction_id", "source_hash", "merchant_normalized", "card_kind"} <= set(row)
                            for row in transactions):
        return []
    matches = ota_portal.scheduled_card_date_matches(databases, transactions)
    # 다른 결과나 연결이 이미 쓰는 카드 원행은 두 번 연결하지 않는다.
    return sorted({str(fact["transaction_id"]) for fact in matches} - set(occupied))


def _canonical_queue_summary(events, results, links) -> dict:
    """Join worker-owned canonical rows one-to-one and retain ambiguous rows as unresolved units."""
    source_counts, result_counts = {}, {}
    for row in events:
        identity = row.get("ota_event_id") if type(row) is dict else None
        if type(identity) is str and identity.strip():
            source_counts[identity] = source_counts.get(identity, 0) + 1
    for row in results:
        identity = row.get("ota_event_id") if type(row) is dict else None
        if type(identity) is str and identity.strip():
            result_counts[identity] = result_counts.get(identity, 0) + 1

    result_by_id = {}
    for index, row in enumerate(results):
        identity = row.get("ota_event_id") if type(row) is dict else None
        if (type(identity) is str and identity.strip() and
                source_counts.get(identity) == 1 and result_counts.get(identity) == 1):
            result_by_id[identity] = (index, row)

    queue_rows, consumed = [], set()

    def flagged(row, key):
        value = row.get(key) if type(row) is dict else None
        if value is None or value is False:
            return False, False
        if value is True:
            return True, False
        if type(value) is str:
            return bool(value), False
        return False, True

    def evidence_state(source, result, identity):
        changed = missing = review_warning = malformed = False
        for row in (source, result):
            for key in ("evidence_changed", "evidence_missing"):
                value, bad = flagged(row, key)
                malformed |= bad
                if key == "evidence_changed":
                    changed |= value
                else:
                    missing |= value
            value, bad = flagged(row, "review_warning")
            review_warning |= value
            malformed |= bad
        link = links.get(identity) if identity and type(links) is dict else None
        if type(link) is dict:
            value, bad = flagged(link, "evidence_changed")
            changed |= value
            malformed |= bad
            value, bad = flagged(link, "evidence_missing")
            missing |= value
            malformed |= bad
            stored_digest = link.get("source_digest")
            source_digest = source.get("source_digest") if type(source) is dict else None
            if (type(stored_digest) is str and stored_digest and
                    type(source_digest) is str and source_digest and stored_digest != source_digest):
                changed = True
        review_warning |= changed or missing or malformed
        return changed, missing, review_warning

    for source in events:
        identity = source.get("ota_event_id") if type(source) is dict else None
        valid_id = type(identity) is str and bool(identity.strip())
        unique = valid_id and source_counts.get(identity) == 1
        joined = result_by_id.get(identity) if unique else None
        if joined is not None:
            result_index, result = joined
            consumed.add(result_index)
            row = dict(source)
            row.update(result)
            # Matching authority belongs to the solver, never a source fallback.
            for key in ("status", "reason", "transaction_id"):
                row[key] = result.get(key)
            changed, missing, warning = evidence_state(source, result, identity)
            source_evidence = source.get("evidence_status")
            if (type(source_evidence) is str and
                    source_evidence in ("conflict", "evidence_conflict", "refund_conflict")):
                warning = True
            row["evidence_changed"] = changed
            row["evidence_missing"] = missing
            row["review_warning"] = warning
            queue_rows.append(row)
            continue

        row = dict(source) if type(source) is dict else {}
        # Source facts alone never stand in for a solver result.
        row.update(status=None, reason=None, transaction_id=None)
        changed, missing, _ = evidence_state(source, None, identity if valid_id else None)
        row["evidence_changed"] = changed
        row["evidence_missing"] = missing
        row["review_warning"] = True
        queue_rows.append(row)

    for index, result in enumerate(results):
        if index in consumed:
            continue
        row = dict(result) if type(result) is dict else {}
        identity = row.get("ota_event_id")
        valid_id = type(identity) is str and bool(identity.strip())
        changed, missing, _ = evidence_state(None, result, identity if valid_id else None)
        row["evidence_changed"] = changed
        row["evidence_missing"] = missing
        row["review_warning"] = True
        queue_rows.append(row)

    return summarize_queue(queue_rows, {
        "status": "ready", "stale": False, "refreshing": False,
        "fresh": True, "enabled": True, "generation": 0,
    }, coverage="canonical")


def reconcile_for(backend) -> dict:
    """The full reconciliation through one backend. The caller owns the backend's lifetime."""
    data = backend._data()
    events, transactions, links, results = data
    from . import guide_airfare_review
    try:
        guide = guide_airfare_review.evaluate(backend.board, backend.sources.get("mail_directories", []),
                                              events, transactions, results)
    except Exception as exc:
        airfare_ids = {str(event.get("ota_event_id")) for event in events
                       if guide_airfare_review._is_airfare(event.get("item"))}
        guide = {str(row.get("ota_event_id")): guide_airfare_review.failed(exc) for row in results
                 if row.get("status") in ("MATCHED_AUTO", "MATCHED_USER")
                 and str(row.get("ota_event_id")) in airfare_ids}
    published = []
    for row in results:
        item = {key: row.get(key) for key in ("ota_event_id", "status", "transaction_id",
                                              "reserved_card_ids", "allocation_basis", "inferred_link",
                                              "inference_basis", "payment_date_verified")}
        if row.get("reservation_link"):
            item["reservation_link"] = row["reservation_link"]
        verdict = guide.get(str(row.get("ota_event_id")))
        if verdict is not None:
            item["guide_airfare"] = verdict
        published.append(item)
    try:
        authority = guide_airfare_review.authority_summary(backend.board)
    except Exception:
        authority = {"state": "unavailable", "digest": "", "error": "summary_failed"}
    scheduled = scheduled_card_settlements(backend.sources, transactions, backend._occupied_cards(links, results))
    queue_summary = _canonical_queue_summary(events, results, links)
    public = public_snapshot(backend.snapshot_from(data, include_cards=False))
    return {
        "public": public,
        "queue_summary": queue_summary,
        "authority": authority,
        "results": published,
        "links": {str(event_id): _link_transaction_id(link)
                  for event_id, link in links.items() if _link_transaction_id(link)},
        # In memory only: actions read it, the disk copy never carries it.
        "data": {"events": events, "transactions": transactions, "links": links, "results": results,
                 "rules": backend.store.active_rules(),
                 "passengers": _passenger_index(backend.sources.get("mail_directories", [])),
                 "scheduled_card_ids": scheduled},
    }


def _passenger_index(mail_directories, *, strict=False) -> dict:
    """booking ref -> the flight passengers the authenticated Trip.com mail names.

    Display evidence only: the booker and payer are never in this list, and a
    failure to read the mail leaves the index empty rather than failing the refresh.
    """
    from app import flight_evidence
    try:
        evidence = flight_evidence.collect_flight_evidence(mail_directories)
    except Exception:
        if strict:
            raise
        return {}
    index = {}
    for (provider, booking_ref), found in evidence.items():
        if provider != "trip":
            continue
        names = [f"{person['surname']} {person['given_name']}" for person in found.get("passengers", [])]
        index[str(booking_ref)] = {"names": names, "conflict": bool(found.get("conflict"))}
        if found.get('source_digests'):
            # 소유자 후보 조회에 필요한 검증 근거만 유지한다. 메일 본문은 담지 않는다.
            index[str(booking_ref)].update({key: found[key] for key in
                ('booking_ref', 'passengers', 'legs', 'source_digests', 'digest', 'cancellation_status', 'reserved_on', 'booking_date_status', 'booking_date_evidence', 'booking_card_day')
                if key in found})
    return index


def reconcile(board) -> dict:
    """The full reconciliation. Runs on the refresh worker only, never on a request."""
    backend = CoreOtaPaymentBackend.from_host(board, read_only=True)
    try:
        return reconcile_for(backend)
    finally:
        backend.close()


CHILD_TIMEOUT_SECONDS = 900
CHILD_BOOTSTRAP = ("import sys; sys.path.insert(0, sys.argv[1]); "
                   "from webapp import ota_reconcile_child as child; child.run(*sys.argv[1:])")


def _stop_process_tree(pid: int) -> None:
    """Stop this child and what it started, and nothing else: the PID tree of one process."""
    import subprocess
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"] if os.name == "nt" else ["kill", "-9", str(pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


class OtaReconcileChildError(RuntimeError):
    """The child process ended with an error; the message names the original exception."""


def reconcile_in_child(board) -> dict:
    """reconcile(board) in a separate process, with the same result.

    The child reads the same board database and gets the reservation authority this
    process already read, so its answer does not depend on which process computed it.
    """
    import pickle
    import subprocess
    import sys
    import uuid

    root = str(Path(__file__).resolve().parents[1])
    workdir = Path(review_db_path()).parent
    token = uuid.uuid4().hex
    request_path = workdir / f"ota-reconcile-{token}.in"
    result_path = workdir / f"ota-reconcile-{token}.out"
    request_path.write_bytes(pickle.dumps(
        {"authority": getattr(board, "_reservation_authority", None)},
        protocol=pickle.HIGHEST_PROTOCOL))
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", CHILD_BOOTSTRAP, root, str(board.path),
             str(request_path), str(result_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            _, stderr = process.communicate(timeout=CHILD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _stop_process_tree(process.pid)
            raise OtaReconcileChildError("the reconciliation process timed out")
        if process.returncode != 0 or not result_path.exists():
            tail = (stderr or b"").decode("utf-8", "replace").strip().splitlines()
            reason = tail[-1][:200] if tail else f"exit {process.returncode}"
            raise OtaReconcileChildError(f"the reconciliation process ended without a result: {reason}")
        payload = pickle.loads(result_path.read_bytes())
    finally:
        request_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)
    if payload[0] == "ok":
        return payload[1]
    raise OtaReconcileChildError(f"{payload[1]}: {payload[2]}")


PASSENGER_FILE = "ota-passengers.json"
PASSENGER_SCHEMA = "ota-passengers-v2"
_PASSENGER_CACHE = {}


def _write_passenger_index(path, current) -> None:
    """Keep the passenger index beside the snapshot, bound to its input fingerprint and parser.

    The names are display evidence only: this file is not the snapshot, and nothing logs it.
    """
    from app import flight_evidence
    passengers = (current.get("data") or {}).get("passengers")
    if passengers is None:
        return
    document = {"schema": PASSENGER_SCHEMA, "key": current["key"],
                "parser": flight_evidence.PARSER_VERSION, "passengers": passengers}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    _PASSENGER_CACHE.clear()


def passenger_index_for(board, *, require_fresh=False) -> dict:
    """The passenger index for display, read without waiting for any refresh.

    The in-memory index of the current refresh wins. Otherwise the saved index is
    used only when its input fingerprint is the one the worker last read and its
    parser is the current one; anything else is unknown, never guessed.
    """
    from app import flight_evidence
    service = snapshot_service(board)
    current, _fresh = service.held()
    if require_fresh and not _fresh:
        return {}
    if current is not None:
        return (current.get("data") or {}).get("passengers") or {}
    key = service.checked_key()
    if key is None:
        return {}
    path = Path(review_db_path()).parent / PASSENGER_FILE
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _PASSENGER_CACHE.get("stamp") != stamp:
        try:
            _PASSENGER_CACHE.update(stamp=stamp, document=json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}
    document = _PASSENGER_CACHE.get("document") or {}
    if document.get("schema") != PASSENGER_SCHEMA or document.get("key") != key:
        return {}
    if document.get("parser") != flight_evidence.PARSER_VERSION:
        return {}
    return document.get("passengers") or {}


def snapshot_service(board):
    service = getattr(board, "_ota_snapshot_service", None)
    if service is None:
        service = ota_snapshot.OtaSnapshotService(
            key_fn=lambda: input_key(board), reconcile_fn=lambda: reconcile_in_child(board),
            persist_path=Path(review_db_path()).parent / SNAPSHOT_FILE,
            log_path=Path(review_db_path()).parent / "ota-snapshot.log",
            on_published=lambda current: _write_passenger_index(
                Path(review_db_path()).parent / PASSENGER_FILE, current))
        board._ota_snapshot_service = service
        atexit.register(_stop_quietly, service)
    return service


def shutdown_snapshot_service(board) -> None:
    """Stop the board's worker and wait for it. Idempotent; called on server exit and by tests."""
    for name in ('_ota_snapshot_service', '_flight_booking_service'):
        service = getattr(board, name, None)
        if service is not None:
            service.stop()


def _stop_quietly(service) -> None:
    try:
        service.stop(timeout=5)
    except RuntimeError:
        pass


from app.ota_labels import OTA_STATUS as _OTA_STATUS
from app.ota_labels import OTA_REASON as _OTA_REASON
_OTA_EVENT_TYPE = {'charge': '결제', 'refund': '환불', 'reservation': '예약 확인'}
_OTA_DIRECTION = {'purchase': '구매', 'refund': '환불', 'cancellation': '취소'}
_OTA_REFUND = {'no_refund': '환불 없음', 'refund_pending': '환불 요청·대기',
               'refund_requested': '환불 요청·대기', 'refunded': '환불 완료', 'refund_completed': '환불 완료'}
_OTA_LABELS_JS = ("const label=(map,value)=>value===null||value===undefined||value===''?''"
                  ":(map[value]??(/^[a-z_]+$/.test(String(value))?'확인이 필요합니다':String(value)));\n"
                  f'const STATUS_LABELS={json.dumps(_OTA_STATUS, ensure_ascii=False)};'
                  f'const REASON_LABELS={json.dumps(_OTA_REASON, ensure_ascii=False)};'
                  f'const EVENT_TYPE_LABELS={json.dumps(_OTA_EVENT_TYPE, ensure_ascii=False)};'
                  f'const DIRECTION_LABELS={json.dumps(_OTA_DIRECTION, ensure_ascii=False)};'
                  f'const REFUND_LABELS={json.dumps(_OTA_REFUND, ensure_ascii=False)};')


_ICONS = {
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "card": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "message": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "scale": '<path d="M12 3v18M7 21h10M4 7h16"/><path d="m4 7-3 7a3 3 0 0 0 6 0zM20 7l-3 7a3 3 0 0 0 6 0z"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "tag": '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5"/>',
    "wallet": '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2"/>',
}


def _icon(name):
    return f'<svg class="ota-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{_ICONS[name]}</svg>'


def render_import_section(csrf: str) -> str:
    """Return the opt-in OTA HOLD section embedded in the existing import page."""
    token = json.dumps(str(csrf))
    icons = json.dumps(_ICONS, ensure_ascii=False)
    return f'''<details id="ota-review" aria-labelledby="ota-title" data-ota-review>
<summary id="ota-title" class="ota-title">{_icon("alert")}OTA 결제 보류 검토 · 펼쳐서 확인</summary>
<div id="ota-status" role="status" aria-live="polite">보류 내역을 불러오고 있습니다.</div>
<p id="ota-freshness" aria-live="polite"></p>
<div id="ota-events"></div><div id="ota-proposals"></div>
</details>
<style>
#ota-review{{max-width:100%;min-width:0;overflow-wrap:anywhere;color:#1f2a24}}
#ota-review:not([open]){{padding:12px 16px}}
#ota-review>summary{{cursor:pointer;list-style:revert;min-height:44px;align-items:center}}
#ota-review *,#ota-review *::before,#ota-review *::after{{box-sizing:border-box;min-width:0}}
#ota-review .ota-icon{{width:1em;height:1em;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;vertical-align:-.125em}}
#ota-review .ota-title{{display:flex;align-items:center;gap:8px;margin:0 0 6px}}
#ota-review .ota-lead{{color:#5b6660;margin:0 0 12px}}
#ota-review #ota-status{{padding:10px 12px;border-radius:8px;background:#f1f5f2;color:#33413a;font-size:14px}}
#ota-review #ota-freshness{{color:#5b6660;font-size:13px}}
#ota-review .ota-event,#ota-review .ota-card-row,#ota-review .ota-proposal{{border:1px solid #dce3dd;border-radius:10px;background:#fff;padding:14px;margin:12px 0;box-shadow:0 1px 2px rgba(20,40,30,.06)}}
#ota-review .ota-event{{border-left:4px solid #c7872b}}
#ota-review .ota-event h3{{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;font-size:16px;margin:0 0 10px;overflow-wrap:anywhere}}
#ota-review .ota-event h4,#ota-review #ota-proposals h3{{display:flex;align-items:center;gap:6px;font-size:15px;margin:14px 0 6px}}
#ota-review .ota-chip{{display:inline-flex;align-items:center;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:650;white-space:nowrap;background:#fdf0d5;color:#7a4a00}}
#ota-review .ota-facts,#ota-review .ota-card-facts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 12px;font-size:14px}}
#ota-review .ota-facts strong{{display:inline-flex;align-items:center;gap:4px;color:#5b6660;font-weight:600}}
#ota-review .ota-card-facts{{color:#33413a}}
#ota-review .ota-card-row{{display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;align-items:start;cursor:pointer}}
#ota-review .ota-card-row:has(input:checked){{border-color:#2f7d56;box-shadow:0 0 0 2px #cfe8da}}
#ota-review .ota-card-row:has(input:disabled){{background:#f6f7f6;border-style:dashed;cursor:default}}
#ota-review .ota-card-row:has(input:disabled) .ota-card-facts{{color:#6b7570}}
#ota-review .ota-card-row input[type=radio]{{width:22px;height:22px;margin:4px 0 0;min-height:0;padding:0;accent-color:#2f7d56}}
#ota-review .ota-card-title{{display:flex;align-items:center;gap:6px;font-size:15px;margin:0 0 8px}}
#ota-review .ota-value{{overflow-wrap:anywhere}}
#ota-review .ota-match{{font-style:normal;color:#1c7a52;font-weight:650;margin-left:6px}}
#ota-review .ota-blocked,#ota-review .ota-ok{{display:flex;align-items:flex-start;gap:6px;margin-top:8px;padding:8px 10px;border-radius:8px;font-size:13px}}
#ota-review .ota-blocked{{background:#fdf0d5;color:#7a4a00}}
#ota-review .ota-ok{{background:#e2f3e8;color:#1d5c3a}}
#ota-review .ota-verdict{{font-weight:650;margin:8px 0}}
#ota-review .ota-preview{{margin-top:10px;padding:12px;border-radius:8px;background:#f1f5f2}}
#ota-review .ota-preview strong{{display:inline-flex;align-items:center;gap:6px;font-size:15px}}
#ota-review .ota-preview p{{margin:6px 0 10px;font-size:14px;color:#33413a}}
#ota-review .ota-ids{{margin:8px 0}}
#ota-review button,#ota-review select,#ota-review input:not([type=radio]):not([type=checkbox]){{font:inherit;max-width:100%;min-height:42px;padding:8px;border:1px solid #9aa79d;border-radius:6px;background:#fff}}
#ota-review button{{display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;font-weight:650}}
#ota-review button.ota-primary{{background:#2f7d56;border-color:#2f7d56;color:#fff}}
#ota-review button:disabled{{opacity:.5;cursor:not-allowed}}
#ota-review .ota-actions{{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}}
#ota-review .ota-proposal-fields{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
#ota-review [hidden]{{display:none!important}}
@media(max-width:550px){{#ota-review{{padding:12px}}#ota-review .ota-facts,#ota-review .ota-card-facts,#ota-review .ota-proposal-fields{{grid-template-columns:minmax(0,1fr)}}#ota-review .ota-actions button{{width:100%}}}}

/* 2026-10-27: use the same semantic shell tokens as expense cleanup. */
#ota-review{{--ota-bg:var(--shell-paper,var(--paper,#fff));--ota-ink:var(--shell-ink,var(--ink,#18212c));--ota-muted:var(--shell-muted,var(--mut,#64748b));--ota-line:var(--shell-line,var(--line,#dce3dd));--ota-hover:var(--shell-hover,var(--hover,#edf2ee));--ota-warn:var(--shell-warn,#e5a146);--ota-warn-bg:var(--shell-warn-bg,var(--ota-hover));color:var(--ota-ink);border:1px solid var(--ota-line);border-radius:16px;background:var(--ota-bg);padding:20px;margin:20px 0}}
#ota-review .ota-title{{font-size:18px;line-height:1.45;font-weight:750;margin-bottom:12px;color:var(--ota-ink)}}
#ota-review{{min-width:0;overflow-wrap:anywhere}}
#ota-review .ota-event h3{{flex-wrap:wrap}}
#ota-review .ota-event h3>span{{min-width:0;max-width:100%;white-space:normal}}
#ota-review #ota-status{{background:var(--ota-hover);color:var(--ota-ink)}}
#ota-review #ota-freshness,#ota-review .ota-lead{{color:var(--ota-muted)}}
#ota-review .ota-event,#ota-review .ota-card-row,#ota-review .ota-proposal{{background:var(--ota-bg);border-color:var(--ota-line);border-radius:12px;box-shadow:none;margin:10px 0;padding:16px}}
#ota-review .ota-event{{border-left:3px solid var(--ota-warn);}}
#ota-review .ota-event h3{{font-size:15px;margin:0 0 10px}}
#ota-review .ota-event .ota-overview{{font-size:18px;line-height:1.5;font-weight:800;font-variant-numeric:tabular-nums;margin:0 0 5px;color:var(--ota-ink)}}
#ota-review .ota-chip{{color:var(--ota-warn);background:var(--ota-warn-bg);border:1px solid var(--ota-line);font-size:11px}}
#ota-review .ota-verdict{{font-size:13px;color:var(--ota-muted);font-weight:500;line-height:1.5;margin:0 0 12px}}
#ota-review .ota-more{{background:var(--ota-hover);border:1px solid var(--ota-line);border-radius:10px;padding:0 12px;margin:10px 0}}
#ota-review .ota-more summary{{min-height:44px;display:flex;align-items:center;font-weight:650;cursor:pointer;color:var(--ota-ink)}}
#ota-review .ota-facts{{padding:4px 0 14px;gap:9px 14px;line-height:1.5}}
#ota-review .ota-facts strong{{display:flex;color:var(--ota-muted);font-size:12px;line-height:1.3;gap:6px}}
#ota-review .ota-facts .ota-value{{display:block;font-size:13px;margin:3px 0 0;overflow-wrap:anywhere}}
#ota-review .ota-card-facts,#ota-review .ota-preview p{{color:var(--ota-ink)}}
#ota-review .ota-card-row:has(input:checked){{border-color:var(--shell-accent,#1c7a52);box-shadow:inset 0 0 0 1px var(--shell-accent,#1c7a52)}}
#ota-review .ota-card-row:has(input:disabled){{background:var(--ota-hover)}}
#ota-review .ota-card-row:has(input:disabled) .ota-card-facts{{color:var(--ota-muted)}}
#ota-review .ota-blocked{{background:var(--ota-warn-bg);color:var(--ota-warn)}}
#ota-review .ota-ok{{background:var(--ota-hover);color:var(--shell-accent,#1c7a52)}}
#ota-review .ota-preview{{background:var(--ota-hover)}}
#ota-review button,#ota-review select,#ota-review input:not([type=radio]):not([type=checkbox]){{border-color:var(--ota-line);background:var(--ota-bg);color:var(--ota-ink);border-radius:9px;min-height:44px}}
#ota-review button.ota-primary{{background:var(--shell-accent,#1c7a52);border-color:var(--shell-accent,#1c7a52);color:#fff}}
#ota-review button:focus-visible,#ota-review summary:focus-visible{{outline:2px solid var(--shell-focus,#5595ef);outline-offset:2px}}
#ota-review .ota-actions{{gap:10px;margin-top:12px}}
#ota-review h4[role=button]{{min-height:44px;display:flex;align-items:center;flex-wrap:wrap;gap:4px;cursor:pointer}}
#ota-review h4[role=button]:focus-visible{{outline:2px solid var(--shell-focus,#5595ef);outline-offset:2px}}
@media(width < 760px){{#ota-review{{padding:12px;margin:14px 0}}#ota-review .ota-event,#ota-review .ota-card-row{{padding:12px}}#ota-review .ota-facts,#ota-review .ota-card-facts,#ota-review .ota-proposal-fields{{grid-template-columns:1fr}}#ota-review .ota-actions button{{width:100%}}}}
</style>
<script>
(()=>{{
{_OTA_LABELS_JS}
  const csrf={token},root=document.querySelector('[data-ota-review]'),status=root.querySelector('#ota-status');
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
  const money=value=>value===null||value===undefined||value===''||!Number.isFinite(Number(value))?'미확인':Number(value).toLocaleString('ko-KR')+'원';
  const ICONS={icons};
  const icon=name=>`<svg class="ota-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${{ICONS[name]||''}}</svg>`;
  const fact=(name,value)=>value===null||value===undefined||value===''?'':`<span>${{name}}: ${{esc(value)}}</span>`;
  const FACT_ICON={{'예약 제공자':'file','예약 번호':'tag','결제 구분':'layers','결제일':'calendar','결제 금액':'wallet','이용 기간':'calendar','항목':'tag','보류 이유':'alert','원본 근거':'shield','묶음 건수':'layers','배정 근거':'info'}};
  async function call(path,payload){{
    const options=payload===undefined?{{cache:'no-store'}}:{{method:'POST',headers:{{'Content-Type':'application/json','X-CSRF-Token':csrf}},body:JSON.stringify(payload)}};
    const response=await fetch(path,options),data=await response.json();
    if(!response.ok){{const error=Error(data.message||data.code||'요청을 처리하지 못했습니다.');error.code=data.code;throw error;}}
    return data;
  }}
  function render(snapshot){{
    const events=snapshot.events||[];
    root.querySelector('#ota-events').innerHTML=events.length?events.map(event=>{{
      const eventId=esc(event.ota_event_id),amountKrw=Number(event.amount_krw??event.amount);
      const gap=card=>Number.isFinite(Number(card.amount_krw))&&Number.isFinite(amountKrw)?Math.abs(Number(card.amount_krw)-amountKrw):Infinity;
      const financialHoldReasons=['중복 거래라 선택할 수 없습니다.','거래 파싱 오류가 있어 선택할 수 없습니다.','거래 충돌이 있어 선택할 수 없습니다.'];
      const period=event.service_period&&typeof event.service_period==='object'?`${{event.service_period.starts_on||'자료 없음'}} ~ ${{event.service_period.ends_on||'자료 없음'}}`:event.service_period;
      const group=event.group_count?`${{event.group_count.ota}}건 ↔ ${{event.group_count.cards}}건, 대응 ${{event.matched_count??Math.min(event.group_count.ota,event.group_count.cards)}}건`:'';
      const basis=event.inferred_link?event.inference_basis:event.allocation_basis==='user_approved_stable_order'?'사용자 승인 순서 배정 · 개별 결제 근거 미확인':event.status==='HOLD_PARTIAL_GROUP'?'부분 묶음 · 개별 연결과 장부 기록 차단':'';
      const amountText=event.currency&&event.currency!=='KRW'?`${{event.amount}} ${{event.currency}} (원화 환산 ${{money(event.amount_krw)}})`:money(event.amount??event.amount_krw);
      const evidence=event.evidence_missing?'근거 사라짐':event.evidence_changed?'변경됨':'확인됨';
      const facts=[['예약 제공자',event.provider],['예약 번호',event.booking_ref],['결제 구분',label(EVENT_TYPE_LABELS,event.event_type)],['결제일',event.paid_on],['결제 금액',amountText],['이용 기간',period],['항목',event.item],['보류 이유',label(REASON_LABELS,event.reason)],['원본 근거',evidence]];
      if(event.card_issuer)facts.push(['메일의 결제 카드사',event.card_issuer]);
      if(event.reservation_status==='cancelled')facts.push(['예약 상태','취소됨']);
      if(event.refund_status&&event.refund_status!=='none_displayed')facts.push(['환불 상태',label(REFUND_LABELS,event.refund_status)]);
      if(event.service_period_conflict)facts.push(['이용기간 확인','같은 예약의 메일에 서로 다른 기간이 있습니다']);
      const changedTotals=[...new Set((event.booking_changes||[]).flatMap(change=>change.booking_totals_krw||[]))];
      if(changedTotals.length)facts.push(['변경 안내의 예약 총액',changedTotals.map(money).join(', ')+' · 추가 결제 완료 여부는 별도 확인']);
      if(event.candidate_count)facts.push(['연결 미확정 카드 후보',String(event.candidate_count)+'건 · 예약 번호 미확정']);
      if(event.candidate_rejected_count)facts.push(['제외한 카드 후보',String(event.candidate_rejected_count)+'건 · 금액/통화 차이']);
      if(group)facts.push(['묶음 건수',group]);
      if(basis)facts.push(['배정 근거',basis]);
      const candidateCount = event.card_candidate_count || 0;
      const verdict=event.provider==='toyoko'?'예약 관계 후보와 결제 검증은 아래 별도 영역에서 확인합니다.':candidateCount?`연결 가능한 카드 후보 ${{candidateCount}}건이 있습니다. 펼치면 로드됩니다.`:'연결 가능한 카드 후보가 없습니다.';
      const ids=[...(event.ota_group_ids?.length?[['예약 거래 ID',event.ota_group_ids.join(', ')]]:[]),...(event.card_group_ids?.length?[['카드 거래 ID',event.card_group_ids.join(', ')]]:[])];
      const proposedMapping=event.proposed_mapping&&Object.keys(event.proposed_mapping).length?event.proposed_mapping:Object.fromEntries(events.filter(row=>(event.ota_group_ids||[]).includes(row.ota_event_id)&&row.transaction_id).map(row=>[row.ota_event_id,row.transaction_id]));
      const groupPairs=Object.entries(proposedMapping).filter(([eventId,transactionId])=>(event.ota_group_ids||[]).includes(eventId)&&(event.card_group_ids||[]).includes(transactionId)).map(([eventId,transactionId])=>{{const booking=events.find(row=>row.ota_event_id===eventId);const cardEvidence='카드 근거 상세 없음';return `<p data-group-pair="${{esc(eventId)}}:${{esc(transactionId)}}"><strong>${{esc(booking?.booking_ref||eventId)}}</strong> · 결제일 미상 · 금액 미확인 ↔ <strong>${{esc(transactionId)}}</strong> · ${{esc(cardEvidence)}}</p>`;}});
      const renderCard=card=>{{
        const same=gap(card)===0,linked=card.already_linked_event_id,blocked=card.selection_disabled||linked||event.evidence_missing;
        const reason=card.selection_disabled?(card.selection_disabled_reason==='OTA_PAYMENT_DATE_UNKNOWN'?'\uacb0제일이 확인되지 않아 OTA 연결을 확정할 수 없습니다.':card.selection_disabled_reason==='OTA_PAYMENT_DATE_MISMATCH'?'\uacb0제일이 맞지 않아 OTA 연결을 확정할 수 없습니다.':card.selection_disabled_reason||'선택할 수 없습니다.'):linked?(card.already_linked_reason||'다른 예약에 연결됨'):event.evidence_missing?'기존 근거가 사라져 다시 선택할 수 없습니다.':'';
        return `<label class="ota-card-row"><input type="radio" name="ota-card-${{eventId}}" value="${{esc(card.transaction_id)}}" ${{blocked?'disabled':''}} aria-label="${{esc(card.issuer)}} ${{esc(card.merchant)}} ${{money(card.amount_krw)}} 선택"><span><strong class="ota-card-title">${{icon('card')}}${{esc(card.issuer||'카드')}} ·${{esc(card.approval_date||card.transaction_date||'날짜 없음')}}</strong>${{same?'<em class="ota-match">금액 일치</em>':''}}<span class="ota-card-facts">${{fact('가맹점',card.merchant)}}${{fact('원화 금액',money(card.amount_krw))}}${{fact('외화 금액',card.foreign_amount)}}${{fact('승인일',card.approval_date)}}${{fact('매입일',card.posting_date)}}${{fact('카드 끝 네 자리',card.card_tail)}}${{fact('카드 종류',card.card_kind)}}${{fact('승인 번호',card.approval_number||card.authorization_id)}}${{fact('거래 방향',label(DIRECTION_LABELS,card.transaction_direction||card.direction))}}${{fact('취소 상태',card.cancellation_status)}}${{fact('환불 상태',label(REFUND_LABELS,card.refund_status))}}${{fact('연결된 예약',card.already_linked_label)}}</span>${{reason?`<span class="ota-blocked">${{icon('lock')}}<span>${{esc(reason)}}</span></span>`:`<span class="ota-ok">${{icon('check')}}<span>선택 가능</span></span>`}}</span></label>`;
      }};
      return `<article class="ota-event" data-event="${{eventId}}"><h3>${{icon('alert')}}<span>${{esc(event.provider)}} · ${{esc(event.booking_ref)}}</span><span class="ota-chip">${{esc(label(STATUS_LABELS,event.status))}}</span></h3><p class="ota-overview">${{esc(amountText)}} · 카드 후보 ${{candidateCount}}건</p><p class="ota-verdict">${{esc(verdict)}}</p><details class="ota-more"><summary>예약·결제 근거 자세히 보기</summary><div class="ota-facts">${{facts.map(([name,value])=>`<div><strong>${{icon(FACT_ICON[name]||'info')}}${{esc(name)}}:</strong> <span class="ota-value">${{value===null||value===undefined||value===''?'자료 없음':esc(value)}}</span></div>`).join('')}}</div></details><details data-diagnostic="${{eventId}}"><summary>연결 근거와 금융 상태 보기</summary><pre>열면 현재 스냅샷에서 읽습니다.</pre></details>${{ids.length?`<details class="ota-ids"><summary>거래 ID 보기</summary>${{ids.map(([name,value])=>`<p><strong>${{esc(name)}}:</strong> ${{esc(value)}}</p>`).join('')}}</details>`:''}}${{groupPairs.length?`<details class="ota-group-proposal"><summary>순서 대응 제안 ${{groupPairs.length}}건 보기</summary><p>이 대응은 개별 결제 근거가 아닌 정렬 순서 제안입니다. 예약별 연결을 확인한 뒤 묶음을 고정하세요.</p>${{groupPairs.join('')}}</details>`:''}}${{event.provider==='toyoko'?'':`<h4>${{icon('card')}}결제일과 승인 규칙 범위의 카드 후보 <span class="ota-card-count">${{candidateCount}}</span>건</h4><div class="ota-cards" data-cards-loaded="false"><p class="ota-load-hint">카드를 펼치면 로드됩니다.</p></div><div class="ota-actions"><button type="button" data-preview="${{eventId}}" disabled>${{icon('scale')}}차이 미리 보기</button><button type="button" data-none="${{eventId}}">${{icon('lock')}}연결할 거래 없음 · 보류 유지</button></div><div id="ota-difference" data-difference-for="${{eventId}}"></div>`}}</article>`;
    }}).join(''):'<p>검토할 OTA 결제 보류가 없습니다.</p>';
    const orderGroups=new Map();
    events.filter(event=>((event.allocation_basis==='user_approved_stable_order'||event.allocation_basis==='user_confirmed_group_required')&&!event.group_order_frozen)||event.review_warning==='confirm_group_reallocation')
      .forEach(event=>{{const ids=[...(event.ota_group_ids||[])].sort(),replace=event.review_warning==='confirm_group_reallocation';if(ids.length>1)orderGroups.set(ids.join('|'),{{ids,replace,confirmable:(event.group_count?.ota===event.group_count?.cards)&&(event.matched_count??event.group_count?.ota)===event.group_count?.ota&&(!replace||Object.keys(event.proposed_mapping||{{}}).length===event.group_count?.ota)}});}});
    if(orderGroups.size)root.querySelector('#ota-events').insertAdjacentHTML('beforeend',
      [...orderGroups.values()].map(group=>`<div class="ota-actions"><p>순서 배정은 개별 결제 근거가 아닙니다. ${{group.replace?(group.confirmable?'구성이 달라졌습니다. 새 제안을 확인해야 합니다.':'구성이 달라져 완전한 대응을 만들 수 없습니다. 새 카드나 OTA 거래가 확인될 때까지 보류합니다.'):'확인 뒤 현재 순서 배정을 고정합니다.'}}</p><button type="button" data-freeze-group="${{esc(encodeURIComponent(JSON.stringify(group)))}}" ${{group.confirmable?'':'disabled'}}>${{icon('lock')}}${{group.replace?'새 순서 배정 검토 및 고정':'현재 순서 배정을 확인하고 고정'}}</button></div>`).join(''));
    for(const event of events.filter(item=>item.provider==='toyoko')){{
      const article=root.querySelector(`.ota-event[data-event="${{esc(event.ota_event_id)}}"]`);if(!article)continue;
      const relation=event.reservation_link||{{}};
      const state=relation.status==='INFERRED'?'자동 추론 관계 · 결제 미검증':relation.status==='USER_CONFIRMED'?'사용자 확인 관계 · 결제 미검증':relation.status==='STALE'?'저장한 관계의 근거 변경 · 기존 선택 이력 유지, 재확인 필요':relation.status==='NEEDS_REVIEW'?'여러 후보 또는 근거 차이 · 사용자가 확인해야 합니다.':'예약 관계 미확인';
      const savedAmount=relation.amount_status==='MATCH'?'금액 일치':relation.amount_status==='MISMATCH'?'금액 차이':'금액 미확인';
      const savedText=relation.transaction_id?'<p>저장한 선택: '+(relation.historical_card_missing?'이전 선택 원문을 현재 확인할 수 없음':esc(relation.merchant||'가맹점 미확인')+' · '+esc(relation.approval_date||'날짜 미확인')+' · 원화 '+esc(money(relation.amount_krw)))+' · '+(relation.status==='STALE'?'재확인 필요 · ':'사용자 예약 관계 확인 · 결제 미검증 · ')+savedAmount+'</p>':'';
      const optionBlock='<p>연결할 카드 후보를 로드합니다.</p><button type="button" data-load-reservation-candidates="'+esc(event.ota_event_id)+'">예약 카드 후보 로드</button>';
      article.insertAdjacentHTML('afterbegin','<section class="ota-reservation-link"><h4>예약 관계 확인 · 실제 결제 확정과 별도</h4><p>'+esc(state)+(event.reservation_group_only?' · 묶음 합계이며 개별 객실 확정은 아닙니다.':'')+'</p>'+savedText+optionBlock+'<div data-reservation-candidates-for="'+esc(event.ota_event_id)+'"></div><div data-reservation-preview-for="'+esc(event.ota_event_id)+'"></div></section>');
    }}
    renderProposals(snapshot.proposals||[]);
    bindEvents(snapshot);
  }}
  function renderProposals(proposals){{
    root.querySelector('#ota-proposals').innerHTML=proposals.length?'<h3>'+icon('message')+'검토 질문</h3>'+proposals.map(p=>`<article class="ota-proposal" data-proposal="${{esc(p.proposal_id)}}" data-status="${{esc(p.status)}}"><p>${{esc(p.question||'이 연결을 규칙으로 저장할까요?')}}</p><p>상태: ${{p.status==='pending'?'답변 대기':esc(p.status)}}</p><label><input type="radio" name="proposal-${{esc(p.proposal_id)}}" value="once" checked> 이번 건만</label> <label><input type="radio" name="proposal-${{esc(p.proposal_id)}}" value="approve"> 규칙 저장</label> <label><input type="radio" name="proposal-${{esc(p.proposal_id)}}" value="edit"> 조건 수정</label><div class="ota-proposal-fields" hidden><label>예약 제공자<input name="provider" value="${{esc(p.conditions?.provider||'')}}"></label><label>항목<input name="item" value="${{esc(p.conditions?.item||'')}}"></label><label>Rule currency<input name="currency" maxlength="3" value="${{esc(p.conditions?.currency||'KRW')}}"></label><label>Event type<select name="event_type"><option value="charge" ${{p.conditions?.event_type==='refund'?'':'selected'}}>charge</option><option value="refund" ${{p.conditions?.event_type==='refund'?'selected':''}}>refund</option></select></label><label>가맹점<input name="merchant_normalized" value="${{esc(p.conditions?.merchant_normalized||'')}}"></label><label>카드사<input name="issuer" value="${{esc(p.conditions?.issuer||'')}}"></label><label>카드 끝 네 자리<input name="card_last4" inputmode="numeric" maxlength="4" value="${{esc(p.conditions?.card_last4||'')}}"></label><label>허용 금액 차이<input name="amount_delta_krw" type="number" step="1" value="${{esc(p.conditions?.amount_delta_krw??'')}}"></label><label>허용 날짜 차이<input name="date_lag_days" type="number" min="-7" max="7" step="1" value="${{esc(p.conditions?.date_lag_days??'')}}"></label><label>Lag lower bound<input name="date_lag_min_days" type="number" min="-7" max="7" step="1" value="${{esc(p.conditions?.date_lag_min_days??'')}}"></label><label>Lag upper bound<input name="date_lag_max_days" type="number" min="-7" max="7" step="1" value="${{esc(p.conditions?.date_lag_max_days??'')}}"></label><label>규칙 종류<select name="rule_kind"><option value="narrow" ${{['provider_alias','issuer_alias'].includes(p.conditions?.rule_kind)?'':'selected'}}>좁은 조건 규칙</option><option value="provider_alias" ${{p.conditions?.rule_kind==='provider_alias'?'selected':''}}>가맹점 별칭 승인</option><option value="issuer_alias" ${{p.conditions?.rule_kind==='issuer_alias'?'selected':''}}>발급사 별칭 승인</option></select></label><label>OTA 발급사 이름<input name="event_issuer_alias" value="${{esc(p.conditions?.event_issuer_alias||'')}}"></label><label>가맹점 별칭<input name="alias" value="${{esc(p.conditions?.alias||p.conditions?.merchant_normalized||'')}}"></label><label>승인 근거 출처<input name="approval_source" value="user_review"></label><label>별칭 규칙 버전<input name="alias_version" type="number" min="1" step="1" value="1"></label><label>할인율 (1/10000 단위)<input name="discount_rate_bps" type="number" min="1" max="10000" step="1" value="${{esc(p.conditions?.discount_rate_bps??'')}}"></label><label>할인 한도 (원)<input name="discount_cap_krw" type="number" min="1" step="1" value="${{esc(p.conditions?.discount_cap_krw??'')}}"></label><label>최소 결제 금액 (원)<input name="minimum_amount_krw" type="number" min="1" step="1" value="${{esc(p.conditions?.minimum_amount_krw??'')}}"></label><label>원 단위 처리<select name="rounding_mode"><option value="floor">내림</option><option value="half_up">반올림</option><option value="ceiling">올림</option></select></label><label>결제 수단<input name="payment_method" value="${{esc(p.conditions?.payment_method||'')}}"></label><label>적용 시작일<input name="valid_from" type="date" value="${{esc(p.conditions?.valid_from||'')}}"></label><label>적용 종료일<input name="valid_to" type="date" value="${{esc(p.conditions?.valid_to||'')}}"></label></div><div class="ota-actions"><button type="button" data-answer="${{esc(p.proposal_id)}}">${{icon('check')}}제안에 답하기</button></div></article>`).join(''):'<p>대기 중인 제안이 없습니다.</p>';
    root.querySelectorAll('.ota-proposal').forEach(proposal=>proposal.querySelectorAll('input[type=radio]').forEach(radio=>radio.addEventListener('change',()=>{{proposal.querySelector('.ota-proposal-fields').hidden=radio.value==='once'||!radio.checked;}})));
    root.querySelectorAll('[data-answer]').forEach(button=>button.addEventListener('click',async()=>{{
      const proposal=button.closest('[data-proposal]'),action=proposal.querySelector('input[type=radio]:checked').value,conditions={{}};
       if(action!=='once')proposal.querySelectorAll('.ota-proposal-fields input,.ota-proposal-fields select').forEach(field=>{{const rateSet=[...proposal.querySelectorAll('[name="discount_rate_bps"],[name="discount_cap_krw"],[name="minimum_amount_krw"],[name="payment_method"]')].some(item=>item.value.trim());if(field.value.trim()&&(field.name!=='rounding_mode'||rateSet))conditions[field.name]=field.type==='number'?Number(field.value):field.value.trim();}});
      if(conditions.date_lag_min_days!==undefined||conditions.date_lag_max_days!==undefined)delete conditions.date_lag_days;
       button.disabled=true;
      try{{const result=await call('/api/imports/ota/proposal',{{proposal_id:button.dataset.answer,action,conditions,request_id:crypto.randomUUID()}});status.textContent=action==='once'?'규칙 저장 없이 이번 건만 처리했습니다.':action==='approve'?'검토한 조건으로 규칙을 저장했습니다.':'조건 수정을 위해 제안을 다시 열었습니다.';applyFresh(await call('/api/imports/ota'));}}
      catch(error){{status.textContent=error.message;button.disabled=false;}}
    }}));
  }}
  function bindEvents(snapshot){{
    root.querySelectorAll('[data-diagnostic]').forEach(details=>details.addEventListener('toggle',async()=>{{
      if(!details.open||details.dataset.loaded)return;
      const output=details.querySelector('pre');output.textContent='로딩 중...';
      try{{const result=await call(`/api/imports/ota/diagnostics/${{encodeURIComponent(details.dataset.diagnostic)}}`);output.textContent=JSON.stringify(result,null,2);details.dataset.loaded='true';}}
      catch(error){{output.textContent=error.message;}}
    }}));
    root.querySelectorAll('[data-freeze-group]').forEach(button=>button.addEventListener('click',async()=>{{
      const payload=JSON.parse(decodeURIComponent(button.dataset.freezeGroup));
      if(!window.confirm(payload.replace?'이전 순서 배정을 대체하고 새 배정을 고정하시겠습니까?':'이 순서 배정을 고정하시겠습니까? 이전 배정은 되돌릴 수 없습니다.'))return;
      button.disabled=true;
      try{{
        await call('/api/imports/ota/group/confirm',{{event_ids:payload.ids,replace:payload.replace,request_id:crypto.randomUUID()}});
        applyFresh(await call('/api/imports/ota'));status.textContent='순서 배정이 고정되었습니다.';
      }}catch(error){{status.textContent=error.message;button.disabled=false;}}
    }}));
    root.querySelectorAll('.ota-event').forEach(eventCard=>{{
      // Reservation link preview
      const reservationButton=eventCard.querySelector('[data-reservation-preview]');
      if(reservationButton)reservationButton.addEventListener('click',async()=>{{
        const select=eventCard.querySelector('[data-reservation-select]'),target=eventCard.querySelector('[data-reservation-preview-for]');
        if(!select||!select.value)return;
        reservationButton.disabled=true;
        try{{
          const preview=await call('/api/imports/ota/reservation/preview',{{event_id:eventCard.dataset.event,transaction_id:select.value}});
          const period=preview.service_period?`${{preview.service_period.starts_on||'자료 없음'}} ~ ${{preview.service_period.ends_on||'자료 없음'}}`:'자료 없음';
          const localKrw=String(preview.reservation_currency||'').toUpperCase()==='KRW';
          const cardNative=preview.card_foreign_amount==null||preview.card_foreign_amount==='';
          const cardNativeText=localKrw?'원문 원화 '+money(preview.card_amount_krw)+' KRW':cardNative?'원문 원화 금액 미확인':String(preview.card_foreign_amount)+' '+String(preview.card_currency||'');
          const diffUnit=localKrw?'KRW':String(preview.reservation_currency||'');
          target.innerHTML=`<div class="ota-preview"><strong>예약 관계 미리보기</strong><p>숙소: ${{esc(preview.hotel_name||'자료 없음')}} · 기간: ${{esc(period)}}</p><p>예약 금액: ${{esc(preview.reservation_amount??'자료 없음')}} ${{esc(preview.reservation_currency||'')}}</p><p>카드 금액: ${{esc(cardNativeText)}} · 원화 ${{money(preview.card_amount_krw)}}</p><p>${{preview.amount_difference===null?'원문·카드 금액 차이를 계산할 수 없습니다.':'금액 차이: '+esc(preview.amount_difference)+' '+diffUnit}}</p><p>미리보기는 실제 확정 전 확인용입니다. 금액·기간·가맹점을 검토한 뒤 확정하세요.</p><button type="button" class="ota-primary" data-reservation-confirm>예약 관계 확정</button></div>`;
          target.querySelector('[data-reservation-confirm]').addEventListener('click',async confirmEvent=>{{
            const confirmButton=confirmEvent.currentTarget;confirmButton.disabled=true;
            try{{
              const saved=await call('/api/imports/ota/reservation/confirm',{{event_id:eventCard.dataset.event,transaction_id:select.value,preview_digest:preview.preview_digest,expected_revision:preview.expected_revision,request_id:crypto.randomUUID()}});
              const snapshot=await call('/api/imports/ota'),updated=(snapshot.events||[]).find(item=>item.ota_event_id===eventCard.dataset.event);
              if(updated){{
                const savedCard={{}};
                updated.reservation_link={{...(updated.reservation_link||{{}}),status:saved.status,transaction_id:saved.transaction_id,basis:saved.basis,amount_status:saved.amount_status,payment_verified:false,merchant:savedCard.merchant||updated.reservation_link?.merchant||'',approval_date:savedCard.approval_date||savedCard.posting_date||updated.reservation_link?.approval_date||'',amount_krw:savedCard.amount_krw??updated.reservation_link?.amount_krw}};
              }}
              applyFresh(snapshot);status.textContent='예약 관계 확정 완료. 화면이 갱신됩니다.';
            }}catch(error){{status.textContent=error.message;confirmButton.disabled=false;}}
          }});
        }}catch(error){{status.textContent=error.message;}}
        finally{{reservationButton.disabled=false;}}
      }});
      // Card preview and confirm
      const button=eventCard.querySelector('[data-preview]'),radios=eventCard.querySelectorAll('input[type=radio]');
      let selectionVersion=0;
      const noneButton=eventCard.querySelector('[data-none]');
      if(noneButton)noneButton.addEventListener('click',()=>{{
        eventCard.querySelectorAll('input[type=radio]').forEach(radio=>{{radio.checked=false;}});
        selectionVersion++;if(button)button.disabled=true;
        const difference=eventCard.querySelector('#ota-difference');if(difference)difference.replaceChildren();
        status.textContent='선택이 해제되었습니다.';
      }});
      if(button){{
      radios.forEach(radio=>radio.addEventListener('change',()=>{{selectionVersion++;button.disabled=false;eventCard.querySelector('#ota-difference').replaceChildren();}}));
      button.addEventListener('click',async()=>{{
        const selected=eventCard.querySelector('input[type=radio]:checked');if(!selected)return;
        const version=++selectionVersion;
        button.disabled=true;
        try{{const preview=await call('/api/imports/ota/preview',{{event_id:eventCard.dataset.event,transaction_id:selected.value,request_id:crypto.randomUUID()}});const target=eventCard.querySelector('[data-difference-for]');
          if(version!==selectionVersion||!selected.checked||!eventCard.isConnected)return;
          target.innerHTML=`<div class="ota-preview"><strong>${{icon('scale')}}차이 ${{money(preview.difference_krw)}}</strong><p>OTA 금액: ${{money(preview.event_amount_krw)}} · 카드 금액: ${{money(preview.card_amount_krw)}}</p><button type="button" class="ota-primary" id="ota-confirm">${{icon('check')}}이 거래로 확정</button></div>`;
          target.querySelector('#ota-confirm').addEventListener('click',async()=>{{const confirm=target.querySelector('#ota-confirm');confirm.disabled=true;try{{await call('/api/imports/ota/confirm',{{event_id:eventCard.dataset.event,transaction_id:selected.value,preview_digest:preview.preview_digest,request_id:crypto.randomUUID()}});applyFresh(await call('/api/imports/ota'));status.textContent='연결 확정 완료';}}catch(error){{status.textContent=error.message;confirm.disabled=false;}}}});
        }}catch(error){{if(version===selectionVersion&&eventCard.isConnected){{status.textContent=error.message;button.disabled=false;}}}}
      }});
      }}
      // Lazy-load cards
      const cardsContainer=eventCard.querySelector('.ota-cards');
      if(cardsContainer){{
        const toggle=eventCard.querySelector('h4');
        if(toggle){{
          toggle.setAttribute('role','button');toggle.tabIndex=0;toggle.setAttribute('aria-expanded','false');
          toggle.addEventListener('keydown',event=>{{if(event.key==='Enter'||event.key===' '){{event.preventDefault();toggle.click();}}}});
          toggle.addEventListener('click',async()=>{{
            if(cardsContainer.dataset.cardsLoaded==='true'){{cardsContainer.dataset.cardsLoaded='false';toggle.setAttribute('aria-expanded','false');cardsContainer.innerHTML='<p class="ota-load-hint">카드를 펼치면 로드됩니다.</p>';return;}}
            if(cardsContainer.dataset.loading==='true')return;
            cardsContainer.dataset.loading='true';
            cardsContainer.innerHTML='<p class="ota-load-hint">카드 후보를 불러오는 중...</p>';
            try{{
              const data=await call(`/api/imports/ota/cards/${{encodeURIComponent(eventCard.dataset.event)}}`);
              const rows=data.cards||[];
              const gap=card=>Number.isFinite(Number(card.amount_krw))&&Number.isFinite(Number(eventCard.dataset.amountKrw))?Math.abs(Number(card.amount_krw)-Number(eventCard.dataset.amountKrw)):Infinity;
              const financialHoldReasons=['중복 거래라 선택할 수 없습니다.','거래 파싱 오류가 있어 선택할 수 없습니다.','거래 충돌이 있어 선택할 수 없습니다.'];
              const candidateRows=rows.filter(card=>!card.selection_disabled&&!card.already_linked_event_id);
              const reviewOnlyRows=rows.filter(card=>card.selection_disabled&&!card.already_linked_event_id);
              const linkedCards=rows.filter(card=>card.already_linked_event_id);
              const renderCard=card=>{{
                const same=gap(card)===0,linked=card.already_linked_event_id,blocked=card.selection_disabled||linked||eventCard.dataset.evidenceMissing==='true';
                const reason=card.selection_disabled?(card.selection_disabled_reason==='OTA_PAYMENT_DATE_UNKNOWN'?'\uacb0제일이 확인되지 않아 OTA 연결을 확정할 수 없습니다.':card.selection_disabled_reason==='OTA_PAYMENT_DATE_MISMATCH'?'\uacb0제일이 맞지 않아 OTA 연결을 확정할 수 없습니다.':card.selection_disabled_reason||'선택할 수 없습니다.'):linked?(card.already_linked_reason||'다른 예약에 연결됨'):eventCard.dataset.evidenceMissing==='true'?'기존 근거가 사라져 다시 선택할 수 없습니다.':'';
                return `<label class="ota-card-row"><input type="radio" name="ota-card-${{eventCard.dataset.event}}" value="${{esc(card.transaction_id)}}" ${{blocked?'disabled':''}} aria-label="${{esc(card.issuer)}} ${{esc(card.merchant)}} ${{money(card.amount_krw)}} 선택"><span><strong class="ota-card-title">${{icon('card')}}${{esc(card.issuer||'카드')}} ·${{esc(card.approval_date||card.transaction_date||'날짜 없음')}}</strong>${{same?'<em class="ota-match">금액 일치</em>':''}}<span class="ota-card-facts">${{fact('가맹점',card.merchant)}}${{fact('원화 금액',money(card.amount_krw))}}${{fact('외화 금액',card.foreign_amount)}}${{fact('승인일',card.approval_date)}}${{fact('매입일',card.posting_date)}}${{fact('카드 끝 네 자리',card.card_tail)}}${{fact('카드 종류',card.card_kind)}}${{fact('승인 번호',card.approval_number||card.authorization_id)}}${{fact('거래 방향',label(DIRECTION_LABELS,card.transaction_direction||card.direction))}}${{fact('취소 상태',card.cancellation_status)}}${{fact('환불 상태',label(REFUND_LABELS,card.refund_status))}}${{fact('연결된 예약',card.already_linked_label)}}</span>${{reason?`<span class="ota-blocked">${{icon('lock')}}<span>${{esc(reason)}}</span></span>`:`<span class="ota-ok">${{icon('check')}}<span>선택 가능</span></span>`}}</span></label>`;
              }};
              const openRows=[...candidateRows,...reviewOnlyRows].map(renderCard).join('');
              const linkedRows=linkedCards.map(renderCard).join('');
              cardsContainer.innerHTML=openRows+(linkedRows?'<details class="ota-linked-cards"><summary>다른 예약에 연결된 거래 '+linkedCards.length+'건</summary><div class="ota-cards">'+linkedRows+'</div></details>':'');
              cardsContainer.dataset.cardsLoaded='true';
              toggle.setAttribute('aria-expanded','true');
              cardsContainer.dataset.loading='false';
              // Re-bind radio events for new cards
              const newRadios=cardsContainer.querySelectorAll('input[type=radio]');
              newRadios.forEach(radio=>radio.addEventListener('change',()=>{{selectionVersion++;if(button)button.disabled=false;eventCard.querySelector('#ota-difference').replaceChildren();}}));
            }}catch(error){{cardsContainer.innerHTML='<p class="ota-load-hint">'+(error.code==='OTA_SNAPSHOT_NOT_READY'?'예약 근거 갱신 중입니다. 잠시 후 다시 펼쳐 주세요.':'로드 실패: '+esc(error.message))+'</p>';cardsContainer.dataset.loading='false';}}
          }});
        }}
      }}
      // Lazy-load reservation candidates
      const loadReservationBtn=eventCard.querySelector('[data-load-reservation-candidates]');
      if(loadReservationBtn){{
        loadReservationBtn.addEventListener('click',async()=>{{
          const target=eventCard.querySelector('[data-reservation-candidates-for]');
          loadReservationBtn.disabled=true;
          target.innerHTML='<p>예약 카드 후보를 불러오는 중...</p>';
          try{{
            const data=await call(`/api/imports/ota/cards/${{encodeURIComponent(eventCard.dataset.event)}}`);
            const rows=data.cards||[];
            const gap=card=>Number.isFinite(Number(card.amount_krw))&&Number.isFinite(Number(eventCard.dataset.amountKrw))?Math.abs(Number(card.amount_krw)-Number(eventCard.dataset.amountKrw)):Infinity;
            const reservationCandidates=rows.filter(card=>card.reservation_candidate&&!card.already_linked_event_id);
            if(reservationCandidates.length===0){{target.innerHTML='<p>예약 기간·지점·금액 근거에 맞는 카드 후보가 없습니다.</p>';loadReservationBtn.disabled=false;return;}}
            const options=reservationCandidates.map(card=>`<option value="${{esc(card.transaction_id)}}">${{esc(card.merchant||card.issuer||'카드')}} · ${{card.foreign_amount==null||card.foreign_amount===''?'원문 외화 금액 미확인':'원문 외화 '+esc(card.foreign_amount)+' '+esc(card.foreign_currency||card.currency||'')}} · 원화 ${{money(card.amount_krw)}} · ${{card.reservation_amount_status==='MATCH'?'금액 일치':card.reservation_amount_status==='UNKNOWN'?'금액 미확인':card.reservation_amount_status==='MISMATCH'?'금액 차이':'확인 필요'}}</option>`).join('');
            target.innerHTML='<label>카드 후보<select data-reservation-select="'+esc(eventCard.dataset.event)+'"><option value="">선택하세요</option>'+options+'</select></label><button type="button" data-reservation-preview="'+esc(eventCard.dataset.event)+'">예약 관계 미리보기</button>';
            target.querySelector('[data-reservation-preview]').addEventListener('click',async()=>{{
              const select=target.querySelector('[data-reservation-select]');
              if(!select||!select.value)return;
              const preview=await call('/api/imports/ota/reservation/preview',{{event_id:eventCard.dataset.event,transaction_id:select.value}});
              const period=preview.service_period?`${{preview.service_period.starts_on||'자료 없음'}} ~ ${{preview.service_period.ends_on||'자료 없음'}}`:'자료 없음';
              const localKrw=String(preview.reservation_currency||'').toUpperCase()==='KRW';
              const cardNative=preview.card_foreign_amount==null||preview.card_foreign_amount==='';
              const cardNativeText=localKrw?'원문 원화 '+money(preview.card_amount_krw)+' KRW':cardNative?'원문 원화 금액 미확인':String(preview.card_foreign_amount)+' '+String(preview.card_currency||'');
              const diffUnit=localKrw?'KRW':String(preview.reservation_currency||'');
              const previewDiv=eventCard.querySelector('[data-reservation-preview-for]');
              previewDiv.innerHTML=`<div class="ota-preview"><strong>예약 관계 미리보기</strong><p>숙소: ${{esc(preview.hotel_name||'자료 없음')}} · 기간: ${{esc(period)}}</p><p>예약 금액: ${{esc(preview.reservation_amount??'자료 없음')}} ${{esc(preview.reservation_currency||'')}}</p><p>카드 금액: ${{esc(cardNativeText)}} · 원화 ${{money(preview.card_amount_krw)}}</p><p>${{preview.amount_difference===null?'원문·카드 금액 차이를 계산할 수 없습니다.':'금액 차이: '+esc(preview.amount_difference)+' '+diffUnit}}</p><p>미리보기는 실제 확정 전 확인용입니다.</p><button type="button" class="ota-primary" data-reservation-confirm>예약 관계 확정</button></div>`;
              previewDiv.querySelector('[data-reservation-confirm]').addEventListener('click',async()=>{{
                const saved=await call('/api/imports/ota/reservation/confirm',{{event_id:eventCard.dataset.event,transaction_id:select.value,preview_digest:preview.preview_digest,expected_revision:preview.expected_revision,request_id:crypto.randomUUID()}});
                applyFresh(await call('/api/imports/ota'));
              }});
            }});
          }}catch(error){{target.innerHTML='<p style="color:red">로드 실패: '+esc(error.message)+'</p>';}}
          finally{{loadReservationBtn.disabled=false;}}
        }});
      }}
    }});
  }}
  const freshness=root.querySelector('#ota-freshness');
  let loadTimer=null,loading=false,lastBody='',shownOnce=false,followUps=0;
  const bodyOf=snapshot=>JSON.stringify([snapshot.events||[],snapshot.proposals||[]]);
  // Background updates wait while the reviewer has an unsaved choice; a finished save renders at once.
  function reviewing(){{
    const active=document.activeElement;
    if(active&&root.contains(active)&&active.tagName!=='BODY'&&active!==root.querySelector(':scope > summary'))return true;
    return !!root.querySelector('.ota-card-row input:checked,.ota-proposal input[type=radio]:checked:not([value="once"]),.ota-proposal-fields:not([hidden])');
  }}
  function scheduleLoad(delay){{clearTimeout(loadTimer);loadTimer=setTimeout(loadSnapshot,delay);}}
  // The server refreshes after an action in the background, so the reply right after it can still be the old snapshot.
  function applyFresh(snapshot){{
    render(snapshot);lastBody=bodyOf(snapshot);
    followUps=6;
    scheduleLoad((snapshot.status||'ready')!=='ready'?10000:2000);
  }}
  async function loadSnapshot(){{
    if(loading){{scheduleLoad(2000);return;}}
    if(!root.open)return;
    if(document.hidden){{scheduleLoad(10000);return;}}
    loading=true;
    try{{
      const snapshot=await call('/api/imports/ota');
      const state=snapshot.status||'ready';
      const body=bodyOf(snapshot);
      if(state==='loading'){{
        freshness.textContent='OTA 자료를 확인하고 있습니다.';
        scheduleLoad(8000);
        return;
      }}
      if(body!==lastBody){{
        if(reviewing()){{freshness.textContent='고르는 중인 항목이 있어 새 내용은 선택을 마친 뒤 반영합니다.';scheduleLoad(10000);return;}}
        render(snapshot);lastBody=body;
      }}
      if(!shownOnce){{status.textContent='결제 보류 내역을 불러왔습니다.';shownOnce=true;}}
      if(state==='ready'){{freshness.textContent='';}}
      else if(state==='refreshing'){{freshness.textContent='새 자료를 확인하는 중입니다. 아래 내용은 직전에 확인한 결과입니다.';scheduleLoad(10000);}}
      else{{freshness.textContent=snapshot.last_error?'새로 확인하지 못했습니다. 직전 확인 결과를 보여 드립니다.':'자료를 읽을 수 없습니다.';}}
      if(followUps>0){{followUps--;scheduleLoad(2000);}}
    }}catch(error){{freshness.textContent=error.message;scheduleLoad(30000);}}
    finally{{loading=false;}}
  }}
  // Loading thousands of OTA candidates on initial /import is unnecessary.
  // The deep-link still opens the section for a directly requested transaction.
  const autoOpen=location.hash==='#ota-review' || new URLSearchParams(location.search).has('transaction');
  if(autoOpen)root.open=true;
  root.addEventListener('toggle',()=>{{
    if(root.open){{loadSnapshot();}}
    else if(loadTimer){{clearTimeout(loadTimer);loadTimer=null;}}
  }});
  if(root.open)loadSnapshot();
}})();
</script>'''


def _payload(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidReviewInput from exc
    if not isinstance(value, dict):
        raise InvalidReviewInput
    return value


def _proposal_conditions(action: str, conditions):
    allowed = {"provider", "item", "merchant_normalized", "issuer", "card_last4",
               "amount_delta_krw", "date_lag_days", "date_lag_min_days", "date_lag_max_days",
               "currency", "event_type", "discount_rate_bps", "discount_cap_krw",
               "minimum_amount_krw", "rounding_mode", "payment_method", "valid_from", "valid_to",
               "rule_kind", "alias", "approval_source", "alias_version", "event_issuer_alias"}
    if not isinstance(conditions, dict) or set(conditions) - allowed:
        raise InvalidReviewInput
    if action in ("approve", "edit") and not conditions:
        raise InvalidReviewInput
    cleaned = {}
    for key, value in conditions.items():
        if key == "amount_delta_krw":
            if isinstance(value, bool) or not isinstance(value, int) or not -10000 <= value <= 10000:
                raise InvalidReviewInput
            cleaned[key] = value
        elif key == "date_lag_days":
            if isinstance(value, bool) or not isinstance(value, int) or not -7 <= value <= 7:
                raise InvalidReviewInput
            cleaned[key] = value
        elif key in ("date_lag_min_days", "date_lag_max_days"):
            if isinstance(value, bool) or not isinstance(value, int) or not -7 <= value <= 7:
                raise InvalidReviewInput
            cleaned[key] = value
        elif key in ("discount_rate_bps", "discount_cap_krw", "minimum_amount_krw", "alias_version"):
            bounds = {"discount_rate_bps": (1, 10000), "discount_cap_krw": (1, 10_000_000),
                      "minimum_amount_krw": (1, 100_000_000), "alias_version": (1, 100000)}
            low, high = bounds[key]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise InvalidReviewInput
            cleaned[key] = value
        else:
            value = str(value).strip()
            if not value or len(value) > 160:
                raise InvalidReviewInput
            if key == "card_last4" and (len(value) != 4 or not value.isdigit()):
                raise InvalidReviewInput
            if key == "rounding_mode" and value not in ("floor", "half_up", "ceiling"):
                raise InvalidReviewInput
            if key == "currency" and not re.fullmatch(r"[A-Za-z]{3}", value):
                raise InvalidReviewInput
            if key == "event_type" and value not in ("charge", "refund"):
                raise InvalidReviewInput
            if key in ("valid_from", "valid_to"):
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise InvalidReviewInput from exc
            cleaned[key] = value
    rate_fields = {"discount_rate_bps", "discount_cap_krw", "minimum_amount_krw",
                   "rounding_mode", "payment_method"}
    if set(cleaned) & rate_fields and not rate_fields <= set(cleaned):
        raise InvalidReviewInput
    if ("valid_from" in cleaned) != ("valid_to" in cleaned):
        raise InvalidReviewInput
    if "valid_from" in cleaned and cleaned["valid_from"] > cleaned["valid_to"]:
        raise InvalidReviewInput
    lag_bounds = {"date_lag_min_days", "date_lag_max_days"}
    if set(cleaned) & lag_bounds and (not lag_bounds <= set(cleaned) or "date_lag_days" in cleaned or
                                      cleaned["date_lag_min_days"] > cleaned["date_lag_max_days"]):
        raise InvalidReviewInput
    if cleaned.get("rule_kind") == "provider_alias":
        if not all(cleaned.get(key) for key in ("provider", "alias", "approval_source", "alias_version")):
            raise InvalidReviewInput
        return cleaned
    if cleaned.get("rule_kind") == "issuer_alias":
        if not all(cleaned.get(key) for key in
                   ("provider", "issuer", "event_issuer_alias", "approval_source", "alias_version")):
            raise InvalidReviewInput
        return cleaned
    if action in ("approve", "edit") and (
            not cleaned.get("provider") or not cleaned.get("item") or
            not (cleaned.get("merchant_normalized") or
                 (cleaned.get("issuer") and cleaned.get("card_last4")))):
        raise InvalidReviewInput
    return cleaned


def _reply_error(handler, code: str, message: str, status: int) -> bool:
    handler._send_json({"code": code, "message": message}, status)
    return True


def _request_user(handler) -> str:
    """Who is asking, for the review record. A handler may state it; otherwise the request's own session.

    The per-thread role is set only on the GET path, so a POST reads its session from its own headers and
    cookies. No session means no user, and the action is refused.
    """
    stated = getattr(handler, "current_user_id", None)
    if callable(stated):
        return str(stated() or "")
    from .ledger_board import current_session
    cookies = handler._cookies() if callable(getattr(handler, "_cookies", None)) else None
    session = current_session(handler.headers, cookies)
    return str(getattr(session, "user_id", "") or "")


def _diagnostic_snapshot(backend):
    """Read the current projection only; diagnostics never start reconciliation."""
    view_of = getattr(backend, "snapshot_view", None)
    if callable(view_of):
        view = view_of()
        public = view.get("current", {}).get("public") if view.get("current") else None
        if public is not None:
            return public, {
                key: view.get(key) for key in ("status", "stale", "generation", "generated_at")
            }
    # Fallback: include cards for diagnostics
    return public_snapshot(backend.snapshot(), include_cards=True), {"status": "ready", "stale": False}


_QUEUE_NAMES = ("needs_action", "waiting_source", "evidence_missing", "auto_recheck",
                "completed", "historical")
_SNAPSHOT_STATES = ("loading", "ready", "refreshing", "error")


def _stored_queue_summary_response(view):
    """Sanitize a precomputed aggregate; never classify or scan events on the request path."""
    status = view.get("status") if type(view.get("status")) is str else "unknown"
    if status not in _SNAPSHOT_STATES:
        status = "unknown"
    current = view.get("current") if type(view.get("current")) is dict else None
    summary = current.get("queue_summary") if current and type(current.get("queue_summary")) is dict else None
    generation_value = view.get("generation")
    generation = generation_value if type(generation_value) is int and generation_value >= 0 else None
    generated_at = None
    raw_generated_at = view.get("generated_at")
    if type(raw_generated_at) is str:
        try:
            parsed_generated_at = datetime.fromisoformat(raw_generated_at)
            utc_offset = parsed_generated_at.utcoffset()
            if (parsed_generated_at.tzinfo is not None and
                    utc_offset is not None and utc_offset.total_seconds() == 0):
                generated_at = parsed_generated_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        except (ValueError, OverflowError):
            pass
    stale_value, refreshing_value, fresh_value = (
        view.get("stale"), view.get("refreshing"), view.get("fresh"))
    stale = stale_value if type(stale_value) is bool else None
    refreshing = refreshing_value if type(refreshing_value) is bool else None
    fresh = fresh_value if type(fresh_value) is bool else None

    state_tags = []
    if status == "loading":
        state_tags.append("SNAPSHOT_LOADING")
    elif status == "error":
        state_tags.append("SNAPSHOT_ERROR")
    elif status == "refreshing":
        state_tags.append("SNAPSHOT_REFRESHING")
    elif status == "unknown":
        state_tags.append("SNAPSHOT_STATE_UNKNOWN")
    elif status == "ready":
        if refreshing is True:
            state_tags.append("SNAPSHOT_REFRESHING")
        elif stale is not False or fresh is not True:
            state_tags.append("SNAPSHOT_STALE")

    counts = None
    warning_count = None
    coverage = "unavailable"
    grouping = "unknown"
    if summary is not None:
        raw_counts = summary.get("counts_by_queue")
        if type(raw_counts) is dict:
            safe_counts = {}
            valid = True
            for queue in _QUEUE_NAMES:
                bucket = raw_counts.get(queue)
                if type(bucket) is not dict:
                    valid = False
                    break
                event_count, group_count = bucket.get("event_count"), bucket.get("group_count")
                if (type(event_count) is not int or event_count < 0 or
                        type(group_count) is not int or group_count < 0):
                    valid = False
                    break
                safe_counts[queue] = {"event_count": event_count, "group_count": group_count}
            raw_warning_count = summary.get("warning_count")
            if type(raw_warning_count) is not int or raw_warning_count < 0:
                valid = False
            raw_coverage = summary.get("coverage")
            if type(raw_coverage) is not str or raw_coverage not in ("canonical", "public_subset"):
                valid = False
            if valid:
                counts = safe_counts
                warning_count = raw_warning_count
                coverage = raw_coverage
                grouping = "singleton_fallback" if summary.get("grouping") == "singleton_fallback" else "unknown"

    if counts is None:
        state_tags.append("QUEUE_SUMMARY_UNAVAILABLE")
        summary_status = "unavailable"
        counts_authoritative = False
    else:
        is_current = (status == "ready" and fresh is True and stale is False and
                      refreshing is False and summary.get("counts_authoritative") is True and
                      summary.get("snapshot_status") == "ready" and
                      summary.get("fresh") is True and summary.get("stale") is False and
                      summary.get("refreshing") is False and summary.get("enabled") is True and
                      coverage == "canonical" and generation is not None and
                      type(summary.get("generation")) is int and
                      summary.get("generation") == generation and generated_at is not None and
                      type(summary.get("generated_at")) is str and
                      summary.get("generated_at") == generated_at)
        if is_current:
            summary_status = "ready"
            counts_authoritative = True
        else:
            if not state_tags:
                state_tags.append("QUEUE_SUMMARY_NOT_CURRENT")
            total_events = sum(bucket["event_count"] for bucket in counts.values())
            total_groups = sum(bucket["group_count"] for bucket in counts.values())
            counts = {queue: {"event_count": 0, "group_count": 0} for queue in _QUEUE_NAMES}
            counts["auto_recheck"] = {"event_count": total_events, "group_count": total_groups}
            warning_count += 1
            summary_status = "rechecking"
            counts_authoritative = False

    return {
        "status": status,
        "summary_status": summary_status,
        "coverage": coverage,
        "grouping": grouping,
        "count_unit": {"event": "event_count", "group": "group_count"},
        "generation": generation,
        "generated_at": generated_at,
        "fresh": fresh,
        "stale": stale,
        "refreshing": refreshing,
        "enabled": True,
        "counts_available": counts is not None,
        "counts_authoritative": counts_authoritative,
        "counts_by_queue": counts,
        "warning_count": warning_count,
        "state_tags": state_tags,
    }


def _event_diagnostic(snapshot, event_id, freshness):
    event = next((row for row in snapshot.get("events", [])
                  if str(row.get("ota_event_id") or "") == event_id), None)
    if event is None:
        return None
    cards = snapshot.get("cards_by_event", {}).get(event_id, [])
    return {
        "event_id": event_id,
        "snapshot": freshness,
        "source": {
            "present": not bool(event.get("evidence_missing")),
            "changed": bool(event.get("evidence_changed")),
            "status": event.get("evidence_status") or event.get("payment_status") or "unknown",
            "reservation_status": event.get("reservation_status") or "unknown",
        },
        "reconciliation": {
            "status": event.get("status"), "reason": event.get("reason"),
            "candidate_basis": event.get("inference_basis") or event.get("allocation_basis"),
            "candidate_search_status": event.get("candidate_search_status"),
            "candidate_count": event.get("candidate_count", 0),
            "rejected_candidate_count": event.get("candidate_rejected_count", 0),
        },
        "financial": [{key: card.get(key) for key in (
            "transaction_id", "amount_krw", "direction", "refund_status", "cancellation_status",
            "selection_disabled", "selection_disabled_reason") if key in card}
            for card in cards],
        "existing_link": {
            "status": "MATCHED_USER" if event.get("status") == "MATCHED_USER" else
                      "MATCHED_AUTO" if event.get("status") == "MATCHED_AUTO" else "none",
            "transaction_id": event.get("transaction_id"),
            "warning": event.get("review_warning"),
        },
    }


def dispatch(handler, parsed, *, raw=None, csrf="", backend) -> bool:
    """Handle OTA routes after the host's normal access decision."""
    path = parsed.path
    if not owns_route(path):
        return False
    if not enabled():
        return _reply_error(handler, "OTA_REVIEW_DISABLED", "격리 검토 모드가 설정되지 않았습니다.", 404)
    diagnostic_match = re.fullmatch(re.escape(ROUTE_PREFIX) + r"/diagnostics/([^/]+)", path)
    if raw is None and diagnostic_match:
        if not _request_user(handler):
            return _reply_error(handler, "ACCESS_REQUIRED", "로그인이 필요합니다.", 403)
        try:
            snapshot, freshness = _diagnostic_snapshot(backend)
            result = _event_diagnostic(snapshot, diagnostic_match.group(1), freshness)
            if result is None:
                return _reply_error(handler, "NOT_FOUND", "검토 거래를 찾을 수 없습니다.", 404)
            handler._send_json(result)
        except Exception:
            return _reply_error(handler, "OTA_REVIEW_UNAVAILABLE", "진단 자료를 읽을 수 없습니다.", 503)
        return True
    if raw is None:
        if path == ROUTE_PREFIX + "/summary":
            if not _request_user(handler):
                return _reply_error(handler, "ACCESS_REQUIRED", "로그인이 필요합니다.", 403)
            try:
                view_of = getattr(backend, "snapshot_view", None)
                if not callable(view_of):
                    return _reply_error(handler, "OTA_SUMMARY_UNAVAILABLE",
                                        "저장된 요약을 읽을 수 없습니다.", 503)
                handler._send_json(_stored_queue_summary_response(view_of()))
            except Exception:
                return _reply_error(handler, "OTA_SUMMARY_UNAVAILABLE",
                                    "저장된 요약을 읽을 수 없습니다.", 503)
            return True
        cards_match = re.fullmatch(re.escape(ROUTE_PREFIX) + r"/cards/([^/]+)", path)
        if cards_match:
            if not _request_user(handler):
                return _reply_error(handler, "ACCESS_REQUIRED", "로그인이 필요합니다.", 403)
            try:
                event_id = cards_match.group(1)
                cards = backend.cards_for_event(event_id)
                # Apply same field allowlist and post-processing as public_snapshot(include_cards=True)
                sanitized = [_sanitize_card_row(card) for card in cards]
                handler._send_json({"event_id": event_id, "cards": sanitized})
            except (OtaSnapshotNotReady, StalePreviewError):
                return _reply_error(handler, "OTA_SNAPSHOT_NOT_READY",
                                    "자료를 새로 확인하고 있습니다. 잠시 후 다시 펼쳐 주세요.", 409)
            except Exception:
                return _reply_error(handler, "OTA_REVIEW_UNAVAILABLE", "카드 후보를 읽을 수 없습니다.", 503)
            return True
        if path != ROUTE_PREFIX:
            return _reply_error(handler, "NOT_FOUND", "요청 경로를 찾을 수 없습니다.", 404)
        try:
            view_of = getattr(backend, "snapshot_view", None)
            if callable(view_of):
                view = view_of()
                body = dict(view["current"]["public"]) if view["current"] else {
                    "events": [], "cards_by_event": {}, "proposals": []}
                body.update({key: view[key] for key in ("status", "stale", "refreshing", "generation",
                                                        "generated_at", "snapshot_key", "last_error")})
                handler._send_json(body)
            else:
                # Backends without a snapshot service keep the direct read.
                # Exclude cards to reduce payload size; cards are lazy-loaded per event.
                handler._send_json(public_snapshot(backend.snapshot(), include_cards=False))
        except Exception:
            return _reply_error(handler, "OTA_REVIEW_UNAVAILABLE", "검토 자료를 읽을 수 없습니다.", 503)
        return True
    if not csrf or not handler.headers.get("X-CSRF-Token") or handler.headers.get("X-CSRF-Token") != csrf:
        return _reply_error(handler, "CSRF_REQUIRED", "화면을 새로 연 뒤 다시 시도해 주세요.", 403)
    try:
        payload = _payload(raw)
        user = _request_user(handler)
        if not user:
            return _reply_error(handler, "ACCESS_REQUIRED", "로그인이 필요합니다.", 403)
        if path == ROUTE_PREFIX + "/preview":
            result = backend.preview(str(payload["event_id"]), str(payload["transaction_id"]))
        elif path == ROUTE_PREFIX + "/reservation/preview":
            result = backend.reservation_preview(str(payload["event_id"]), str(payload["transaction_id"]))
        elif path == ROUTE_PREFIX + "/reservation/confirm":
            if (not str(payload.get("request_id") or "").strip() or
                    isinstance(payload.get("expected_revision"), bool) or
                    not isinstance(payload.get("expected_revision"), int)):
                raise InvalidReviewInput
            result = backend.reservation_confirm(str(payload["event_id"]), str(payload["transaction_id"]),
                str(payload["preview_digest"]), expected_revision=payload["expected_revision"],
                request_id=str(payload["request_id"]).strip(), user=user)
        elif path == ROUTE_PREFIX + "/confirm":
            if not str(payload["request_id"]).strip():
                raise InvalidReviewInput
            result = backend.confirm(str(payload["event_id"]), str(payload["transaction_id"]),
                                     str(payload["preview_digest"]),
                                     request_id=str(payload["request_id"]), user=user)
        elif path == ROUTE_PREFIX + "/proposal":
            action = str(payload["action"])
            if action not in ("once", "approve", "edit"):
                raise InvalidReviewInput
            conditions = _proposal_conditions(action, payload.get("conditions") or {})
            result = backend.answer_proposal(str(payload["proposal_id"]), action, user=user,
                                             conditions=conditions)
        elif path == ROUTE_PREFIX + "/group/confirm":
            event_ids = payload.get("event_ids")
            if (not isinstance(event_ids, list) or not event_ids or
                    any(not isinstance(identity, str) or not identity.strip() for identity in event_ids) or
                    not isinstance(payload.get("request_id"), str) or not payload["request_id"].strip()):
                raise InvalidReviewInput
            result = backend.confirm_group_order(event_ids, user=user,
                                                 replace=payload.get("replace") is True,
                                                 request_id=payload["request_id"].strip())
        else:
            return _reply_error(handler, "NOT_FOUND", "요청 경로를 찾을 수 없습니다.", 404)
        refresh = getattr(backend, "request_refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                # Best effort: the worker re-reads the inputs on its own schedule anyway.
                pass
        handler._send_json(result)
    except OtaSnapshotNotReady:
        return _reply_error(handler, "OTA_SNAPSHOT_NOT_READY",
                            "자료를 새로 확인하고 있습니다. 잠시 후 다시 시도해 주세요.", 409)
    except StalePreviewError:
        return _reply_error(handler, "STALE_PREVIEW", "자료가 바뀌었습니다. 최신 차이를 다시 확인해 주세요.", 409)
    except InvalidReviewInput:
        return _reply_error(handler, "INVALID_INPUT", "입력값을 확인해 주세요.", 422)
    except (KeyError, TypeError, ValueError):
        return _reply_error(handler, "INVALID_INPUT", "입력값을 확인해 주세요.", 422)
    except Exception:
        return _reply_error(handler, "OTA_REVIEW_UNAVAILABLE", "검토 요청을 처리하지 못했습니다.", 503)
    return True
