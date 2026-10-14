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
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import ota_snapshot


ROUTE_PREFIX = "/api/imports/ota"
REVIEW_MODE_ENV = "WEBLEDGER_OTA_REVIEW_MODE"
REVIEW_DB_ENV = "WEBLEDGER_OTA_REVIEW_DB"
SOURCES_ENV = "WEBLEDGER_OTA_SOURCES_JSON"
_read_backend_factory = None
_write_backend_factory = None

_EVENT_FIELDS = (
    "ota_event_id", "provider", "booking_ref", "event_type", "paid_on", "amount",
    "currency", "amount_krw", "card_last4", "service_period", "item",
    "reservation_status", "payment_status", "evidence_status", "status", "reason",
    "refund_status", "evidence_changed", "evidence_missing", "review_warning",
    "matched_count", "unmatched_ota_count", "unmatched_card_count", "group_count",
    "ota_group_ids", "card_group_ids", "allocation_basis", "individual_payment_evidence",
    "rule_delta_krw", "discount_cause_confirmed", "group_order_frozen",
    "frozen_mapping", "proposed_mapping",
    "group_order_snapshot",
)
_CARD_FIELDS = (
    "transaction_id", "issuer", "card_kind", "card_tail", "approval_date",
    "posting_date", "merchant", "amount_krw", "foreign_amount", "currency",
    "approval_number", "direction", "transaction_direction", "refund_status", "cancellation_status",
    "already_linked_event_id", "already_linked_label", "already_linked_reason", "selection_disabled",
    "selection_disabled_reason", "authorization_number", "authorization_scheme",
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


def public_snapshot(snapshot):
    """Allowlist the UI response so core rows and source metadata never escape."""
    events = []
    for source in snapshot.get("events", []):
        event = {key: source.get(key) for key in _EVENT_FIELDS if key in source}
        event["paid_on"] = event.get("paid_on") or "미확인"
        event["service_period"] = _public_period(event.get("service_period"))
        events.append(event)
    cards_by_event = {}
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
                            "거래 충돌이 있어 선택할 수 없습니다."}
            if not block_reason and source.get("selection_disabled_reason") in safe_reasons:
                block_reason = source["selection_disabled_reason"]
            row["selection_disabled"] = bool(source.get("selection_disabled") or block_reason)
            row["selection_disabled_reason"] = block_reason
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
        return [dict(row) if hasattr(row, "keys") else dict(zip(columns, row)) for row in rows]

    def _data(self):
        events = self.payments.build_ota_payment_events(self.sources)
        transactions = self._transactions()
        manual_links = self.store.links()
        canonical_by_id = {str(event.get("ota_event_id")): event for event in events}
        legacy_links = self._legacy_exact_snapshot(events, transactions)
        manually_claimed = {_link_transaction_id(link): event_id
                            for event_id, link in manual_links.items() if _link_transaction_id(link)}
        links = {event_id: link for event_id, link in legacy_links.items()
                 if manually_claimed.get(_link_transaction_id(link), event_id) == event_id}
        links.update(manual_links)
        stored_events = self._stored_manual_events()
        stale_manual_ids = set()
        for event_id, link in manual_links.items():
            current = canonical_by_id.get(str(event_id))
            stored = stored_events.get(str(event_id))
            proof_missing = current is None or not self._has_payment_proof(current)
            if not proof_missing or not stored:
                continue
            stale_manual_ids.add(str(event_id))
            display_event = dict(stored)
            display_event.update(evidence_missing=True, evidence_changed=True,
                                review_warning="manual_link_evidence_missing")
            if current is None:
                events.append(display_event)
            else:
                events = [display_event if str(event.get("ota_event_id")) == str(event_id) else event
                          for event in events]
        rules = self.store.active_rules()
        frozen_groups = self.store.group_pins() if callable(getattr(self.store, "group_pins", None)) else []
        try:
            results = self.payments.match_ota_payment_events(
                events, transactions, existing_links=links, rules=rules,
                frozen_groups=frozen_groups)
        except TypeError as exc:
            if "unexpected keyword argument 'frozen_groups'" not in str(exc):
                raise
            results = self.payments.match_ota_payment_events(
                events, transactions, existing_links=links, rules=rules)
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
        return events, transactions, links, results

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

    def _legacy_exact_snapshot(self, events, transactions):
        """Read the previous exact matcher once per in-memory evidence/card snapshot."""
        event_ids = tuple(sorted(str(event.get("ota_event_id")) for event in events))
        card_state = tuple(sorted((str(row.get("transaction_id") or ""),
                                   str(row.get("source_hash") or ""),
                                   str(row.get("issuer") or ""),
                                   str(row.get("card_tail") or ""),
                                   str(row.get("approval_date") or ""),
                                   str(row.get("amount_krw") or ""),
                                   str(row.get("transaction_direction") or ""))
                                  for row in transactions))
        cache_key = (event_ids, card_state)
        cache = getattr(self.board, "_ota_legacy_exact_snapshot", None) or {"key": None, "links": {}}
        if cache.get("key") != cache_key:
            # Some isolated UI fixtures intentionally expose only the core's
            # minimal transaction projection. The legacy matcher consumes the
            # full card-board row shape; skip this optional comparison unless
            # every row has the fields it reads.
            legacy_fields = {"transaction_id", "source_hash", "merchant", "merchant_normalized",
                             "card_kind", "transaction_direction", "approval_date", "amount_krw",
                             "card_tail"}
            can_compare = all(legacy_fields.issubset(row) for row in transactions)
            fresh = {}
            if can_compare:
                mail = importlib.import_module("app.ota_mail")
                portal = importlib.import_module("app.ota_portal")
                from app import ota_sources
                mail_dirs = self.sources.get("mail_directories", [])
                # The content stamps key the mail-side memo, so an unchanged mail set is not parsed again.
                source_key = json.dumps(ota_sources.mail_stamps(mail_dirs), sort_keys=True)
                report = mail.match_mail(mail_dirs, transactions, source_key=source_key)
                report = portal.extend_report(report, self.sources.get("portal_databases", []), transactions)
                fresh = legacy_exact_bindings(events, transactions, report)
            retained = dict(cache.get("links", {}))
            for event_id, link in fresh.items():
                retained.setdefault(event_id, link)
            cache = {"key": cache_key, "links": retained}
            self.board._ota_legacy_exact_snapshot = cache
        return {event_id: link for event_id, link in cache.get("links", {}).items()
                if event_id in set(event_ids)}

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
                                     "자동 연결" if result["status"] == "MATCHED_AUTO" else "사용자 확정 연결"))
        return occupied

    def snapshot(self):
        return self.snapshot_from(self._data())

    def snapshot_from(self, data):
        events, transactions, links, results = data
        rules = self.store.active_rules()
        event_by_id = {str(event.get("ota_event_id")): event for event in events}
        occupied = self._occupied_cards(links, results)
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
            if not is_hold and not is_changed_manual and not is_ordered_group:
                continue
            event = {**event_by_id.get(event_id, {}), **result}
            if source_changed:
                event["evidence_changed"] = True
                event["review_warning"] = "source_changed_after_exact_link"
                if result.get("status") == "HOLD_EVIDENCE_CONFLICT":
                    event["reason"] = "기존 연결 뒤 결제 근거가 바뀌었습니다. 예전 카드 거래를 유지하고 새 연결을 다시 추론하지 않습니다."
            if is_changed_manual:
                event["evidence_changed"] = True
                event["evidence_missing"] = evidence_missing
                event["review_warning"] = "manual_link_evidence_missing" if evidence_missing else "source_changed_after_manual_link"
                event["reason"] = ("결제 근거가 사라졌습니다. 기존 수동 연결은 유지되며 새 거래로 다시 연결되지 않습니다."
                                   if evidence_missing else
                                   "수동 연결 뒤 결제 근거가 바뀌었습니다. 연결을 유지한 채 다시 확인해 주세요.")
            holds.append(event)
            rows = self._event_rows(event, transactions, links, rules)
            for row in rows:
                if result.get("status") in ("HOLD_PARTIAL_GROUP", "HOLD_GROUP_CONFIRMATION_REQUIRED") or is_ordered_group:
                    row["selection_disabled"] = True
                    row["selection_disabled_reason"] = (
                        "반복 결제 묶음이 부분 대응 상태라 개별 연결과 장부 배정을 보류합니다."
                        if result.get("status") == "HOLD_PARTIAL_GROUP" else
                        "사용자 승인 순서로 반복 거래를 배정했습니다. 개별 결제 근거가 확인된 연결은 아닙니다.")
                owner = occupied.get(str(row.get("transaction_id") or ""))
                if owner:
                    row["already_linked_event_id"] = owner[0]
                    row["already_linked_reason"] = owner[1]
                    row["already_linked_label"] = _event_label(event_by_id, owner[0])
                    if owner[1] in ("partial_group_reservation", "confirmed_group_reservation"):
                        row["selection_disabled"] = True
                        row["selection_disabled_reason"] = (
                            "\ubd80\ubd84 \ubc18\ubcf5 \uadf8\ub8f9\uc758 \uce74\ub4dc \ud6c4\ubcf4\ub85c \uc608\uc57d\ub418\uc5b4 \uc788\uc5b4 \uac1c\ubcc4 \uc5f0\uacb0\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
                            if owner[1] == "partial_group_reservation" else
                            "\uc0ac\uc6a9\uc790\uac00 \ud655\uc815\ud55c \ubc18\ubcf5 \uadf8\ub8f9\uc758 \uce74\ub4dc\ub85c \uac1c\ubcc4 \uc5f0\uacb0\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
            cards_by_event[event_id] = rows
        proposals = [proposal for proposal in self.store.proposals()
                     if proposal.get("status") == "pending"]
        return public_snapshot({"events": holds, "cards_by_event": cards_by_event, "proposals": proposals})

    def snapshot_view(self):
        """The request path: the last reconciled snapshot and its status, without computing anything."""
        return snapshot_service(self.board).view()

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
            return self.store.confirm(event, transaction, core_digest,
                                      request_id=request_id, user=user, allocations=allocations)
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
    from app import ota_sources
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
                   "events": _store_value(store, "event_snapshots", {})},
        "matching": load_defaults(),
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
                                              "reserved_card_ids", "allocation_basis")}
        verdict = guide.get(str(row.get("ota_event_id")))
        if verdict is not None:
            item["guide_airfare"] = verdict
        published.append(item)
    try:
        authority = guide_airfare_review.authority_summary(backend.board)
    except Exception:
        authority = {"state": "unavailable", "digest": "", "error": "summary_failed"}
    return {
        "public": public_snapshot(backend.snapshot_from(data)),
        "authority": authority,
        "results": published,
        "links": {str(event_id): _link_transaction_id(link)
                  for event_id, link in links.items() if _link_transaction_id(link)},
        # In memory only: actions read it, the disk copy never carries it.
        "data": {"events": events, "transactions": transactions, "links": links, "results": results,
                 "passengers": _passenger_index(backend.sources.get("mail_directories", []))},
    }


def _passenger_index(mail_directories) -> dict:
    """booking ref -> the flight passengers the authenticated Trip.com mail names.

    Display evidence only: the booker and payer are never in this list, and a
    failure to read the mail leaves the index empty rather than failing the refresh.
    """
    from app import flight_evidence
    try:
        evidence = flight_evidence.collect_flight_evidence(mail_directories)
    except Exception:
        return {}
    index = {}
    for (provider, booking_ref), found in evidence.items():
        if provider != "trip":
            continue
        names = [f"{person['surname']} {person['given_name']}" for person in found.get("passengers", [])]
        index[str(booking_ref)] = {"names": names, "conflict": bool(found.get("conflict"))}
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
PASSENGER_SCHEMA = "ota-passengers-v1"
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


def passenger_index_for(board) -> dict:
    """The passenger index for display, read without waiting for any refresh.

    The in-memory index of the current refresh wins. Otherwise the saved index is
    used only when its input fingerprint is the one the worker last read and its
    parser is the current one; anything else is unknown, never guessed.
    """
    from app import flight_evidence
    service = snapshot_service(board)
    current, _fresh = service.held()
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
    service = getattr(board, "_ota_snapshot_service", None)
    if service is not None:
        service.stop()


def _stop_quietly(service) -> None:
    try:
        service.stop(timeout=5)
    except RuntimeError:
        pass


_OTA_STATUS = {
    'HOLD_NO_CARD': '맞는 카드 거래 없음', 'HOLD_AMOUNT_MISMATCH': '금액이 다른 카드 거래만 있음',
    'HOLD_DATE_UNKNOWN': '결제일 미확인', 'HOLD_AMBIGUOUS': '후보 거래가 여러 건',
    'HOLD_PARTIAL_GROUP': '부분 묶음', 'HOLD_EVIDENCE_CONFLICT': '근거 충돌',
    'PENDING_PAYMENT': '결제 대기', 'NOT_CARD_CHARGE': '카드 결제 아님',
}
_OTA_REASON = {
    'no_exact_amount_date_direction_card': '결제 금액·날짜·방향이 모두 맞는 카드 거래가 없습니다',
    'amount_differs': '같은 날짜의 카드 거래는 있지만 금액이 다릅니다',
    'exact_card_needs_descriptor_approval': '금액·날짜가 같은 카드 거래는 있으나 가맹점 별칭이 승인되지 않아 연결하지 않았습니다',
}
_OTA_EVENT_TYPE = {'charge': '결제', 'refund': '환불'}
_OTA_DIRECTION = {'purchase': '구매', 'refund': '환불', 'cancellation': '취소'}
_OTA_REFUND = {'no_refund': '환불 없음'}
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
    return f'''<section id="ota-review" aria-labelledby="ota-title" data-ota-review>
<h2 id="ota-title" class="ota-title">{_icon("alert")}OTA 결제 보류 검토</h2>
<div id="ota-status" role="status" aria-live="polite">보류 내역을 불러오고 있습니다.</div>
<p id="ota-freshness" aria-live="polite"></p>
<div id="ota-events"></div><div id="ota-proposals"></div>
</section>
<style>
#ota-review{{max-width:100%;min-width:0;overflow-wrap:anywhere;color:#1f2a24}}
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
</style>
<script>
(()=>{{
{_OTA_LABELS_JS}
  const csrf={token},root=document.querySelector('[data-ota-review]'),status=root.querySelector('#ota-status');
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
  const money=value=>value===null||value===undefined||value===''||!Number.isFinite(Number(value))?'미확인':Number(value).toLocaleString('ko-KR')+'원';
  const ICONS={icons};
  const icon=name=>`<svg class="ota-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${{ICONS[name]||''}}</svg>`;
  const FACT_ICON={{'예약 제공자':'file','예약 번호':'tag','결제 구분':'layers','결제일':'calendar','결제 금액':'wallet','이용 기간':'calendar','항목':'tag','보류 이유':'alert','원본 근거':'shield','묶음 건수':'layers','배정 근거':'info'}};
  async function call(path,payload){{
    const options=payload===undefined?{{cache:'no-store'}}:{{method:'POST',headers:{{'Content-Type':'application/json','X-CSRF-Token':csrf}},body:JSON.stringify(payload)}};
    const response=await fetch(path,options),data=await response.json();
    if(!response.ok)throw Error(data.message||data.code||'요청을 처리하지 못했습니다.');
    return data;
  }}
  function render(snapshot){{
    const events=snapshot.events||[],cards=snapshot.cards_by_event||{{}};
    root.querySelector('#ota-events').innerHTML=events.length?events.map(event=>{{
      const eventId=esc(event.ota_event_id),allRows=cards[event.ota_event_id]||[],amountKrw=Number(event.amount_krw??event.amount);
      const gap=card=>Number.isFinite(Number(card.amount_krw))&&Number.isFinite(amountKrw)?Math.abs(Number(card.amount_krw)-amountKrw):Infinity;
      const rows=[...allRows].sort((a,b)=>gap(a)===gap(b)?0:gap(a)<gap(b)?-1:1);
      const sameAmount=rows.filter(card=>gap(card)===0).length;
      const period=event.service_period&&typeof event.service_period==='object'?`${{event.service_period.starts_on||'자료 없음'}} ~ ${{event.service_period.ends_on||'자료 없음'}}`:event.service_period;
      const group=event.group_count?`${{event.group_count.ota}}건 ↔ ${{event.group_count.cards}}건, 대응 ${{event.matched_count??Math.min(event.group_count.ota,event.group_count.cards)}}건`:'';
      const basis=event.allocation_basis==='user_approved_stable_order'?'사용자 승인 순서 배정 · 개별 결제 근거 미확인':event.status==='HOLD_PARTIAL_GROUP'?'부분 묶음 · 개별 연결과 장부 기록 차단':'';
      const amountText=event.currency&&event.currency!=='KRW'?`${{event.amount}} ${{event.currency}} (원화 환산 ${{money(event.amount_krw)}})`:money(event.amount??event.amount_krw);
      const evidence=event.evidence_missing?'근거 사라짐':event.evidence_changed?'변경됨':'확인됨';
      const facts=[['예약 제공자',event.provider],['예약 번호',event.booking_ref],['결제 구분',label(EVENT_TYPE_LABELS,event.event_type)],['결제일',event.paid_on],['결제 금액',amountText],['이용 기간',period],['항목',event.item],['보류 이유',label(REASON_LABELS,event.reason)],['원본 근거',evidence]];
      if(group)facts.push(['묶음 건수',group]);
      if(basis)facts.push(['배정 근거',basis]);
      const verdict=sameAmount?`결제 금액과 같은 카드 거래가 ${{sameAmount}}건 있습니다.`:'결제 금액과 같은 카드 거래가 없습니다.';
      const ids=[...(event.ota_group_ids?.length?[['예약 거래 ID',event.ota_group_ids.join(', ')]]:[]),...(event.card_group_ids?.length?[['카드 거래 ID',event.card_group_ids.join(', ')]]:[])];
      const fact=(name,value)=>value===null||value===undefined||value===''?'':`<span>${{name}}: ${{esc(value)}}</span>`;
      const renderCard=card=>{{
        const same=gap(card)===0,linked=card.already_linked_event_id,blocked=card.selection_disabled||linked||event.evidence_missing;
        const reason=card.selection_disabled?(card.selection_disabled_reason||'선택할 수 없습니다.'):linked?(card.already_linked_reason||'다른 예약에 연결됨'):event.evidence_missing?'기존 근거가 사라져 다시 선택할 수 없습니다.':'';
        return `<label class="ota-card-row"><input type="radio" name="ota-card-${{eventId}}" value="${{esc(card.transaction_id)}}" ${{blocked?'disabled':''}} aria-label="${{esc(card.issuer)}} ${{esc(card.merchant)}} ${{money(card.amount_krw)}} 선택"><span><strong class="ota-card-title">${{icon('card')}}${{esc(card.issuer||'카드')}} ·${{esc(card.approval_date||card.transaction_date||'날짜 없음')}}</strong>${{same?'<em class="ota-match">금액 일치</em>':''}}<span class="ota-card-facts">${{fact('가맹점',card.merchant)}}${{fact('원화 금액',money(card.amount_krw))}}${{fact('외화 금액',card.foreign_amount)}}${{fact('승인일',card.approval_date)}}${{fact('매입일',card.posting_date)}}${{fact('카드 끝 네 자리',card.card_tail)}}${{fact('카드 종류',card.card_kind)}}${{fact('승인 번호',card.approval_number||card.authorization_id)}}${{fact('거래 방향',label(DIRECTION_LABELS,card.transaction_direction||card.direction))}}${{fact('취소 상태',card.cancellation_status)}}${{fact('환불 상태',label(REFUND_LABELS,card.refund_status))}}${{fact('연결된 예약',card.already_linked_label)}}</span>${{reason?`<span class="ota-blocked">${{icon('lock')}}<span>${{esc(reason)}}</span></span>`:`<span class="ota-ok">${{icon('check')}}<span>선택 가능</span></span>`}}</span></label>`;
      }};
      const openRows=rows.filter(card=>!card.already_linked_event_id).map(renderCard).join('');
      const linkedRows=rows.filter(card=>card.already_linked_event_id).map(renderCard).join('');
      return `<article class="ota-event" data-event="${{eventId}}"><h3>${{icon('alert')}}<span>${{esc(event.provider)}} · ${{esc(event.booking_ref)}}</span><span class="ota-chip">${{esc(label(STATUS_LABELS,event.status))}}</span></h3><p class="ota-verdict">${{esc(verdict)}}</p><div class="ota-facts">${{facts.map(([name,value])=>`<div><strong>${{icon(FACT_ICON[name]||'info')}}${{esc(name)}}:</strong> <span class="ota-value">${{value===null||value===undefined||value===''?'자료 없음':esc(value)}}</span></div>`).join('')}}</div>${{ids.length?`<details class="ota-ids"><summary>거래 ID 보기</summary>${{ids.map(([name,value])=>`<p><strong>${{esc(name)}}:</strong> ${{esc(value)}}</p>`).join('')}}</details>`:''}}<h4>${{icon('card')}}결제일과 승인 규칙 범위의 카드 거래 ${{rows.length}}건 · 결제 금액과 가까운 순</h4><div class="ota-cards">${{openRows}}</div>${{linkedRows?`<details class="ota-linked-cards"><summary>다른 예약에 연결된 거래 ${{rows.filter(card=>card.already_linked_event_id).length}}건</summary><div class="ota-cards">${{linkedRows}}</div></details>`:''}}<div class="ota-actions"><button type="button" data-preview="${{eventId}}" disabled>${{icon('scale')}}차이 미리 보기</button><button type="button" data-none="${{eventId}}">${{icon('lock')}}연결할 거래 없음 · 보류 유지</button></div><div id="ota-difference" data-difference-for="${{eventId}}"></div></article>`;
    }}).join(''):'<p>검토할 OTA 결제 보류가 없습니다.</p>';
    const orderGroups=new Map();
    events.filter(event=>((event.allocation_basis==='user_approved_stable_order'||event.allocation_basis==='user_confirmed_group_required')&&!event.group_order_frozen)||event.review_warning==='confirm_group_reallocation')
      .forEach(event=>{{const ids=[...(event.ota_group_ids||[])].sort(),replace=event.review_warning==='confirm_group_reallocation';if(ids.length>1)orderGroups.set(ids.join('|'),{{ids,replace,confirmable:(event.group_count?.ota===event.group_count?.cards)&&(event.matched_count??event.group_count?.ota)===event.group_count?.ota&&(!replace||Object.keys(event.proposed_mapping||{{}}).length===event.group_count?.ota)}});}});
    if(orderGroups.size)root.querySelector('#ota-events').insertAdjacentHTML('beforeend',
      [...orderGroups.values()].map(group=>`<div class="ota-actions"><p>순서 배정은 개별 결제 근거가 아닙니다. ${{group.replace?(group.confirmable?'구성이 달라졌습니다. 새 제안을 확인해야 합니다.':'구성이 달라져 완전한 대응을 만들 수 없습니다. 새 카드나 OTA 거래가 확인될 때까지 보류합니다.'):'확인 뒤 현재 순서 배정을 고정합니다.'}}</p><button type="button" data-freeze-group="${{esc(encodeURIComponent(JSON.stringify(group)))}}" ${{group.confirmable?'':'disabled'}}>${{icon('lock')}}${{group.replace?'새 순서 배정 검토 및 고정':'현재 순서 배정을 확인하고 고정'}}</button></div>`).join(''));
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
    root.querySelectorAll('[data-freeze-group]').forEach(button=>button.addEventListener('click',async()=>{{
      const payload=JSON.parse(decodeURIComponent(button.dataset.freezeGroup));
      if(!window.confirm(payload.replace?'바뀐 예약과 카드의 새 순서 배정을 확인하고 고정할까요?':'표시된 순서 배정을 확인하고 고정할까요? 이후 구성이나 순서가 달라지면 다시 확인이 필요합니다.'))return;
      button.disabled=true;
      try{{
        await call('/api/imports/ota/group/confirm',{{event_ids:payload.ids,replace:payload.replace,request_id:crypto.randomUUID()}});
        applyFresh(await call('/api/imports/ota'));status.textContent='확인한 그룹 순서를 고정했습니다.';
      }}catch(error){{status.textContent=error.message;button.disabled=false;}}
    }}));
    root.querySelectorAll('.ota-event').forEach(eventCard=>{{
      const button=eventCard.querySelector('[data-preview]'),radios=eventCard.querySelectorAll('input[type=radio]');
      let selectionVersion=0;
      eventCard.querySelector('[data-none]').addEventListener('click',()=>{{
        eventCard.querySelectorAll('input[type=radio]').forEach(radio=>{{radio.checked=false;}});
        selectionVersion++;button.disabled=true;eventCard.querySelector('#ota-difference').replaceChildren();
        status.textContent='연결하지 않고 보류로 둡니다.';
      }});
      radios.forEach(radio=>radio.addEventListener('change',()=>{{selectionVersion++;button.disabled=false;eventCard.querySelector('#ota-difference').replaceChildren();}}));
      button.addEventListener('click',async()=>{{
        const selected=eventCard.querySelector('input[type=radio]:checked');if(!selected)return;
        const version=++selectionVersion;
        button.disabled=true;
        try{{const preview=await call('/api/imports/ota/preview',{{event_id:eventCard.dataset.event,transaction_id:selected.value,request_id:crypto.randomUUID()}});const target=eventCard.querySelector('[data-difference-for]');
          if(version!==selectionVersion||!selected.checked||!eventCard.isConnected)return;
          target.innerHTML=`<div class="ota-preview"><strong>${{icon('scale')}}차이 ${{money(preview.difference_krw)}}</strong><p>OTA 결제: ${{money(preview.event_amount_krw)}} · 카드 거래: ${{money(preview.card_amount_krw)}}</p><button type="button" class="ota-primary" id="ota-confirm">${{icon('check')}}이 거래로 결제 연결 확정</button></div>`;
          target.querySelector('#ota-confirm').addEventListener('click',async()=>{{const confirm=target.querySelector('#ota-confirm');confirm.disabled=true;try{{await call('/api/imports/ota/confirm',{{event_id:eventCard.dataset.event,transaction_id:selected.value,preview_digest:preview.preview_digest,request_id:crypto.randomUUID()}});applyFresh(await call('/api/imports/ota'));status.textContent='사용자 확인 연결';}}catch(error){{status.textContent=error.message;confirm.disabled=false;}}}});
        }}catch(error){{if(version===selectionVersion&&eventCard.isConnected){{status.textContent=error.message;button.disabled=false;}}}}
      }});
    }});
  }}
  const freshness=root.querySelector('#ota-freshness');
  let loadTimer=null,loading=false,lastBody='',shownOnce=false,followUps=0;
  const bodyOf=snapshot=>JSON.stringify([snapshot.events||[],snapshot.cards_by_event||{{}},snapshot.proposals||[]]);
  // Background updates wait while the reviewer has an unsaved choice; a finished save renders at once.
  function reviewing(){{
    const active=document.activeElement;
    if(active&&root.contains(active)&&active.tagName!=='BODY')return true;
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
  loadSnapshot();
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


def dispatch(handler, parsed, *, raw=None, csrf="", backend) -> bool:
    """Handle OTA routes after the host's normal access decision."""
    path = parsed.path
    if not owns_route(path):
        return False
    if not enabled():
        return _reply_error(handler, "OTA_REVIEW_DISABLED", "격리 검토 모드가 설정되지 않았습니다.", 404)
    if raw is None:
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
                handler._send_json(public_snapshot(backend.snapshot()))
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
