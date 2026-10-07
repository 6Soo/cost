"""Opt-in, isolated UI for reviewing OTA payment holds.

The backend is deliberately injected. Its snapshot operation must be read-only;
write methods must persist only in the separately configured OTA review store.
"""
from __future__ import annotations

import importlib
import json
import os
from contextlib import nullcontext
from decimal import Decimal, InvalidOperation
from pathlib import Path


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
)
_CARD_FIELDS = (
    "transaction_id", "issuer", "card_kind", "card_tail", "approval_date",
    "posting_date", "merchant", "amount_krw", "foreign_amount", "currency",
    "approval_number", "direction", "transaction_direction", "refund_status", "cancellation_status",
    "already_linked_event_id", "already_linked_reason", "selection_disabled",
    "selection_disabled_reason",
)
_CONDITION_FIELDS = (
    "provider", "item", "merchant_normalized", "issuer", "card_last4",
    "amount_delta_krw", "date_lag_days",
)


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
        details.append(f"결제일 차이는 최대 {lag}일")
    return " ".join(details) + " 조건을 다음 결제에도 적용할까요?"


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
                reason = row.get("already_linked_reason")
                if reason not in ("자동 연결", "기존 연결", "사용자 확정 연결"):
                    row["already_linked_reason"] = "이미 연결된 거래라 선택할 수 없습니다."
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


class InvalidReviewInput(Exception):
    """A request does not match the review API contract."""


def review_db_path() -> str:
    return os.environ.get(REVIEW_DB_ENV, "").strip()


def enabled() -> bool:
    """Enable only when an operator explicitly selects isolated review mode."""
    configured_path = Path(review_db_path()) if review_db_path() else None
    return (os.environ.get(REVIEW_MODE_ENV) == "isolated" and configured_path is not None
            and configured_path.is_absolute())


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
                report = mail.match_mail(self.sources.get("mail_directories", []), transactions)
                report = portal.extend_report(report, self.sources.get("portal_databases", []), transactions)
                fresh = legacy_exact_bindings(events, transactions, report)
            retained = dict(cache.get("links", {}))
            for event_id, link in fresh.items():
                retained.setdefault(event_id, link)
            cache = {"key": cache_key, "links": retained}
            self.board._ota_legacy_exact_snapshot = cache
        return {event_id: link for event_id, link in cache.get("links", {}).items()
                if event_id in set(event_ids)}

    def _event_rows(self, event, transactions, links):
        return [dict(row) for row in self.payments.same_date_cards(event, transactions, links=links)]

    def _occupied_cards(self, links, results):
        occupied = {}
        for event_id, link in links.items():
            transaction_id = _link_transaction_id(link)
            if transaction_id:
                occupied[transaction_id] = (str(event_id), "기존 연결")
        for result in results:
            if result.get("status") in ("MATCHED_AUTO", "MATCHED_USER") and result.get("transaction_id"):
                occupied.setdefault(str(result["transaction_id"]),
                                    (str(result.get("ota_event_id") or ""),
                                     "자동 연결" if result["status"] == "MATCHED_AUTO" else "사용자 확정 연결"))
        return occupied

    def snapshot(self):
        events, transactions, links, results = self._data()
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
            if not is_hold and not is_changed_manual:
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
            rows = self._event_rows(event, transactions, links)
            for row in rows:
                owner = occupied.get(str(row.get("transaction_id") or ""))
                if owner:
                    row["already_linked_event_id"] = owner[0]
                    row["already_linked_reason"] = owner[1]
            cards_by_event[event_id] = rows
        proposals = [proposal for proposal in self.store.proposals()
                     if proposal.get("status") == "pending"]
        return public_snapshot({"events": holds, "cards_by_event": cards_by_event, "proposals": proposals})

    def _selection(self, event_id, transaction_id):
        events, transactions, links, results = self._data()
        event = next((row for row in events if str(row.get("ota_event_id")) == event_id), None)
        result = next((row for row in results if str(row.get("ota_event_id")) == event_id), None)
        if (event is None or result is None or not str(result.get("status") or "").startswith("HOLD")
                or not event.get("paid_on")):
            raise InvalidReviewInput("only an OTA hold can be manually linked")
        transaction = next((row for row in transactions
                            if str(row.get("transaction_id")) == transaction_id), None)
        if transaction is None:
            raise InvalidReviewInput("card transaction does not exist")
        if _transaction_selection_block_reason(transaction):
            raise InvalidReviewInput("card transaction is not selectable")
        rows = self._event_rows(event, transactions, links)
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
        event, transaction, _allocations = self._selection(event_id, transaction_id)
        preview = self.store.preview(event, transaction)
        if not isinstance(preview, dict) or not preview.get("preview_digest"):
            raise RuntimeError("core preview must return preview_digest")
        event_amount = event.get("amount_krw")
        card_amount = transaction.get("amount_krw")
        return {"preview_digest": preview["preview_digest"],
                "event_amount_krw": event_amount, "card_amount_krw": card_amount,
                "difference_krw": (card_amount - event_amount
                                   if isinstance(card_amount, int) and isinstance(event_amount, int)
                                   else None),
                "differences": preview.get("differences", {})}

    def confirm(self, event_id, transaction_id, preview_digest, *, request_id, user):
        if self.read_only:
            raise RuntimeError("read-only OTA backend cannot confirm")
        event, transaction, allocations = self._selection(event_id, transaction_id)
        try:
            return self.store.confirm(event, transaction, preview_digest,
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


def render_import_section(csrf: str) -> str:
    """Return the opt-in OTA HOLD section embedded in the existing import page."""
    token = json.dumps(str(csrf))
    return f'''<section id="ota-review" aria-labelledby="ota-title" data-ota-review>
<h2 id="ota-title">OTA 결제 보류 검토</h2>
<p class="small">결제 근거가 있는 예약만 표시합니다. 같은 결제일의 카드 거래를 모두 확인한 뒤 직접 골라 주세요.</p>
<div id="ota-status" role="status" aria-live="polite">보류 내역을 불러오고 있습니다.</div>
<div id="ota-events"></div><div id="ota-proposals"></div>
</section>
<style>
#ota-review{{max-width:100%;min-width:0;overflow-wrap:anywhere}}
#ota-review *,#ota-review *::before,#ota-review *::after{{box-sizing:border-box;min-width:0}}
#ota-review .ota-event,#ota-review .ota-card-row,#ota-review .ota-proposal{{border:1px solid #dce3dd;border-radius:8px;background:#fff;padding:12px;margin:10px 0}}
#ota-review .ota-event h3{{font-size:16px;margin:0 0 8px;overflow-wrap:anywhere}}
#ota-review .ota-facts,#ota-review .ota-card-facts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 12px}}
#ota-review .ota-card-row{{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;align-items:start}}
#ota-review .ota-card-row input{{width:22px;height:22px;margin:4px}}
#ota-review .ota-value{{overflow-wrap:anywhere}}
#ota-review button,#ota-review select,#ota-review input{{font:inherit;max-width:100%;min-height:42px;padding:8px;border:1px solid #9aa79d;border-radius:5px;background:#fff}}
#ota-review button{{cursor:pointer;font-weight:650}}
#ota-review button:disabled{{opacity:.5;cursor:not-allowed}}
#ota-review .ota-actions{{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}}
#ota-review .ota-proposal-fields{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
#ota-review [hidden]{{display:none!important}}
@media(max-width:550px){{#ota-review{{padding:12px}}#ota-review .ota-facts,#ota-review .ota-card-facts,#ota-review .ota-proposal-fields{{grid-template-columns:minmax(0,1fr)}}#ota-review .ota-actions button{{width:100%}}}}
</style>
<script>
(()=>{{
  const csrf={token},root=document.querySelector('[data-ota-review]'),status=root.querySelector('#ota-status');
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
  const money=value=>value===null||value===undefined||value===''||!Number.isFinite(Number(value))?'미확인':Number(value).toLocaleString('ko-KR')+'원';
  async function call(path,payload){{
    const options=payload===undefined?{{cache:'no-store'}}:{{method:'POST',headers:{{'Content-Type':'application/json','X-CSRF-Token':csrf}},body:JSON.stringify(payload)}};
    const response=await fetch(path,options),data=await response.json();
    if(!response.ok)throw Error(data.message||data.code||'요청을 처리하지 못했습니다.');
    return data;
  }}
  function render(snapshot){{
    const events=snapshot.events||[],cards=snapshot.cards_by_event||{{}};
    root.querySelector('#ota-events').innerHTML=events.length?events.map(event=>{{
      const eventId=esc(event.ota_event_id),rows=cards[event.ota_event_id]||[];
      const facts=[['예약 제공자',event.provider],['예약 번호',event.booking_ref],['결제 구분',event.event_type],['결제일',event.paid_on],['결제 금액',String(event.amount??'미확인')+' '+(event.currency||'')],['확인 원화 금액',money(event.amount_krw)],['이용 기간',event.service_period],['항목',event.item],['보류 이유',event.reason],['근거 상태',event.evidence_missing?'근거 사라짐':event.evidence_changed?'변경됨':'확인됨']];
      return `<article class="ota-event" data-event="${{eventId}}"><h3>${{esc(event.provider)}} · ${{esc(event.booking_ref)}} · ${{esc(event.status)}}</h3><div class="ota-facts">${{facts.map(([label,value])=>`<div><strong>${{esc(label)}}:</strong> <span class="ota-value">${{esc(value||'미확인')}}</span></div>`).join('')}}</div><h4>같은 결제일 카드 거래 ${{rows.length}}건</h4><div class="ota-cards">${{rows.map(card=>`<label class="ota-card-row"><input type="radio" name="ota-card-${{eventId}}" value="${{esc(card.transaction_id)}}" ${{card.selection_disabled||card.already_linked_event_id||event.evidence_missing?'disabled':''}} aria-label="${{esc(card.issuer)}} ${{esc(card.merchant)}} ${{money(card.amount_krw)}} 선택"><span><strong>${{esc(card.issuer)}} · ${{esc(card.approval_date||card.transaction_date)}}</strong><span class="ota-card-facts"><span>카드 종류: ${{esc(card.card_kind||'미확인')}}</span><span>카드 끝 네 자리: ${{esc(card.card_tail||'미확인')}}</span><span>승인일: ${{esc(card.approval_date||'미확인')}}</span><span>매입일: ${{esc(card.posting_date||'미확인')}}</span><span>가맹점: ${{esc(card.merchant||'미확인')}}</span><span>원화 금액: ${{money(card.amount_krw)}}</span><span>외화 금액: ${{esc(card.foreign_amount||'없음')}}</span><span>통화: ${{esc(card.currency||'미확인')}}</span><span>승인 번호: ${{esc(card.approval_number||card.authorization_id||'미확인')}}</span><span>취소 상태: ${{esc(card.cancellation_status||'미확인')}}</span><span>환불 상태: ${{esc(card.refund_status||'미확인')}}</span><span>거래 방향: ${{esc(card.transaction_direction||card.direction||'미확인')}}</span><span>이미 연결된 결제: ${{esc(card.already_linked_event_id||'없음')}}</span><span>${{card.selection_disabled?esc(card.selection_disabled_reason||'선택할 수 없습니다.'):card.already_linked_event_id?esc(card.already_linked_reason||'이미 연결된 거래라 선택할 수 없습니다.'):event.evidence_missing?'기존 근거가 사라져 다시 선택할 수 없습니다.':'선택 가능'}}</span></span></span></label>`).join('')}}</div><div class="ota-actions"><button type="button" data-preview="${{eventId}}" disabled>차이 미리 보기</button></div><div id="ota-difference" data-difference-for="${{eventId}}"></div></article>`;
    }}).join(''):'<p>검토할 OTA 결제 보류가 없습니다.</p>';
    renderProposals(snapshot.proposals||[]);
    bindEvents();
  }}
  function renderProposals(proposals){{
    root.querySelector('#ota-proposals').innerHTML=proposals.length?'<h3>검토 질문</h3>'+proposals.map(p=>`<article class="ota-proposal" data-proposal="${{esc(p.proposal_id)}}" data-status="${{esc(p.status)}}"><p>${{esc(p.question||'이 연결을 규칙으로 저장할까요?')}}</p><p>상태: ${{esc(p.status)}}</p><label><input type="radio" name="proposal-${{esc(p.proposal_id)}}" value="once" checked> 이번 건만</label> <label><input type="radio" name="proposal-${{esc(p.proposal_id)}}" value="approve"> 규칙 저장</label> <label><input type="radio" name="proposal-${{esc(p.proposal_id)}}" value="edit"> 조건 수정</label><div class="ota-proposal-fields" hidden><label>예약 제공자<input name="provider" value="${{esc(p.conditions?.provider||'')}}"></label><label>항목<input name="item" value="${{esc(p.conditions?.item||'')}}"></label><label>가맹점<input name="merchant_normalized" value="${{esc(p.conditions?.merchant_normalized||'')}}"></label><label>카드사<input name="issuer" value="${{esc(p.conditions?.issuer||'')}}"></label><label>카드 끝 네 자리<input name="card_last4" inputmode="numeric" maxlength="4" value="${{esc(p.conditions?.card_last4||'')}}"></label><label>허용 금액 차이<input name="amount_delta_krw" type="number" step="1" value="${{esc(p.conditions?.amount_delta_krw??'')}}"></label><label>허용 날짜 차이<input name="date_lag_days" type="number" min="0" max="7" step="1" value="${{esc(p.conditions?.date_lag_days??'')}}"></label></div><div class="ota-actions"><button type="button" data-answer="${{esc(p.proposal_id)}}">제안에 답하기</button></div></article>`).join(''):'<p>대기 중인 제안이 없습니다.</p>';
    root.querySelectorAll('.ota-proposal').forEach(proposal=>proposal.querySelectorAll('input[type=radio]').forEach(radio=>radio.addEventListener('change',()=>{{proposal.querySelector('.ota-proposal-fields').hidden=radio.value==='once'||!radio.checked;}})));
    root.querySelectorAll('[data-answer]').forEach(button=>button.addEventListener('click',async()=>{{
      const proposal=button.closest('[data-proposal]'),action=proposal.querySelector('input[type=radio]:checked').value,conditions={{}};
       if(action!=='once')proposal.querySelectorAll('.ota-proposal-fields input').forEach(field=>{{if(field.value.trim())conditions[field.name]=field.type==='number'?Number(field.value):field.value.trim();}});
      button.disabled=true;
      try{{const result=await call('/api/imports/ota/proposal',{{proposal_id:button.dataset.answer,action,conditions,request_id:crypto.randomUUID()}});status.textContent=action==='once'?'규칙 저장 없이 이번 건만 처리했습니다.':action==='approve'?'검토한 조건으로 규칙을 저장했습니다.':'조건 수정을 위해 제안을 다시 열었습니다.';if(action==='edit')render(await call('/api/imports/ota'));else{{proposal.dataset.status=result.status;proposal.querySelector('p:nth-of-type(2)').textContent='상태: '+result.status;}}}}
      catch(error){{status.textContent=error.message;button.disabled=false;}}
    }}));
  }}
  function bindEvents(){{
    root.querySelectorAll('.ota-event').forEach(eventCard=>{{
      const button=eventCard.querySelector('[data-preview]'),radios=eventCard.querySelectorAll('input[type=radio]');
      radios.forEach(radio=>radio.addEventListener('change',()=>{{button.disabled=false;eventCard.querySelector('#ota-difference').replaceChildren();}}));
      button.addEventListener('click',async()=>{{
        const selected=eventCard.querySelector('input[type=radio]:checked');if(!selected)return;
        button.disabled=true;
        try{{const preview=await call('/api/imports/ota/preview',{{event_id:eventCard.dataset.event,transaction_id:selected.value,request_id:crypto.randomUUID()}});const target=eventCard.querySelector('[data-difference-for]');
          target.innerHTML=`<div class="ota-preview"><strong>차이 ${{money(preview.difference_krw)}}</strong><p>OTA 결제: ${{money(preview.event_amount_krw)}} · 카드 거래: ${{money(preview.card_amount_krw)}}</p><button type="button" id="ota-confirm">이 거래로 결제 연결 확정</button></div>`;
          target.querySelector('#ota-confirm').addEventListener('click',async()=>{{const confirm=target.querySelector('#ota-confirm');confirm.disabled=true;try{{await call('/api/imports/ota/confirm',{{event_id:eventCard.dataset.event,transaction_id:selected.value,preview_digest:preview.preview_digest,request_id:crypto.randomUUID()}});render(await call('/api/imports/ota'));status.textContent='사용자 확인 연결';}}catch(error){{status.textContent=error.message;confirm.disabled=false;}}}});
        }}catch(error){{status.textContent=error.message;button.disabled=false;}}
      }});
    }});
  }}
  call('/api/imports/ota').then(snapshot=>{{render(snapshot);status.textContent='결제 보류 내역을 불러왔습니다.';}}).catch(error=>status.textContent=error.message);
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
               "amount_delta_krw", "date_lag_days"}
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
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 7:
                raise InvalidReviewInput
            cleaned[key] = value
        else:
            value = str(value).strip()
            if not value or len(value) > 160:
                raise InvalidReviewInput
            if key == "card_last4" and (len(value) != 4 or not value.isdigit()):
                raise InvalidReviewInput
            cleaned[key] = value
    if action in ("approve", "edit") and (
            not cleaned.get("provider") or not cleaned.get("item") or
            not (cleaned.get("merchant_normalized") or
                 (cleaned.get("issuer") and cleaned.get("card_last4")))):
        raise InvalidReviewInput
    return cleaned


def _reply_error(handler, code: str, message: str, status: int) -> bool:
    handler._send_json({"code": code, "message": message}, status)
    return True


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
            # The backend contract requires snapshot() to use read-only access.
            handler._send_json(public_snapshot(backend.snapshot()))
        except Exception:
            return _reply_error(handler, "OTA_REVIEW_UNAVAILABLE", "검토 자료를 읽을 수 없습니다.", 503)
        return True
    if not csrf or not handler.headers.get("X-CSRF-Token") or handler.headers.get("X-CSRF-Token") != csrf:
        return _reply_error(handler, "CSRF_REQUIRED", "화면을 새로 연 뒤 다시 시도해 주세요.", 403)
    try:
        payload = _payload(raw)
        user = str(handler.current_user_id() or "") if hasattr(handler, "current_user_id") else ""
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
        else:
            return _reply_error(handler, "NOT_FOUND", "요청 경로를 찾을 수 없습니다.", 404)
        handler._send_json(result)
    except StalePreviewError:
        return _reply_error(handler, "STALE_PREVIEW", "자료가 바뀌었습니다. 최신 차이를 다시 확인해 주세요.", 409)
    except InvalidReviewInput:
        return _reply_error(handler, "INVALID_INPUT", "입력값을 확인해 주세요.", 422)
    except (KeyError, TypeError, ValueError):
        return _reply_error(handler, "INVALID_INPUT", "입력값을 확인해 주세요.", 422)
    except Exception:
        return _reply_error(handler, "OTA_REVIEW_UNAVAILABLE", "검토 요청을 처리하지 못했습니다.", 503)
    return True
