"""OTA 결제 근거를 카드 거래와 분리해 정규화하고 대조한다."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app import ota_mail, ota_portal
from app.ota_matching_defaults import load_defaults


_NO_ALLOCATION_SNAPSHOT = object()
PARSER_VERSION = 3


class OtaSourcesError(ValueError):
    """Source inventory is incomplete; no new automatic match may be derived."""

    def __init__(self, failures):
        self.failures = list(failures)
        super().__init__(f"OTA_SOURCES_INCOMPLETE: {len(self.failures)} source diagnostic(s)")


def _as_items(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_id(source_ids):
    # 변경 가능한 예약·금액 사실과 근거 다이제스트를 identity에서 분리한다.
    identity = sorted(set(source_ids or []))
    return "ota_" + _digest(identity)


_MAIL_EVENT_MEMO = {}


def _mail_events(directories, *, read_only=False):
    """The mail parse reads only mail files, so it is reused while their content digests are unchanged.

    A caller that only reads the events passes read_only=True and gets the memo itself;
    everyone else gets a copy, so the memo cannot be changed from outside.
    """
    from app import ota_sources
    key = (tuple(str(Path(d)) for d in (directories or [])),
           json.dumps(ota_sources.mail_stamps(directories), sort_keys=True))
    if key not in _MAIL_EVENT_MEMO:
        _MAIL_EVENT_MEMO.clear()
        _MAIL_EVENT_MEMO[key] = _parse_mail_events(directories)
    if read_only:
        return _MAIL_EVENT_MEMO[key]
    return copy.deepcopy(_MAIL_EVENT_MEMO[key])


def _parse_mail_events(directories):
    from app import ota_booking_context
    try:
        messages, inventory = ota_mail.load_messages_from(directories)
    except Exception as exc:
        raise OtaSourcesError([{"kind":"mail_loader", "error":type(exc).__name__}]) from exc
    failures = [entry for entry in inventory if entry.get("error")]
    if failures:
        raise OtaSourcesError(failures)
    events = {}
    context = ota_booking_context.collect(messages)
    for message_id, message in sorted(messages.items()):
        fact = ota_mail.extract_mail(message)
        if not fact:
            fact = _extract_signed_payment_message(message)
        if not fact:
            continue
        amount = fact.get("paid_amount_krw")
        paid_on = fact.get("paid_on")
        event_type = fact.get("event_type", "charge")
        explicit_status = fact.get("evidence_status")
        status = explicit_status or ("paid_verified" if amount not in (None, 0) else "not_card_charge")
        if fact.get("reservation_status") == "cancelled" and not amount and not explicit_status:
            event_type = "reservation"
        source_id = f"mail:{message_id}"
        digest = fact["source_sha256"]
        text = ota_mail.body_text(message.get("payload", {}))
        payment_match = re.search(r"(?:payment|결제)\s*(?:id|reference|번호)\s*[:#：]?\s*([A-Za-z0-9_-]{4,64})",
                                  text, re.I)
        card_match = re.search(r"(?:card|카드)(?:\s*(?:ending|ends|끝\s*자리))?\s*[:#-]?\s*(?:\*+|X+)?(\d{4})\b",
                               text, re.I)
        payment_id = fact.get("payment_id") or (payment_match.group(1) if payment_match else None)
        raw_amount = fact.get("amount", amount)
        currency = fact.get("currency", "KRW")
        event = {
            "provider": fact["provider"], "booking_ref": fact["booking_ref"],
            "event_type": event_type, "paid_on": paid_on if status in ("paid_verified", "refund_verified") else None,
            "scheduled_for": fact.get("scheduled_for"),
            "amount": raw_amount, "currency": currency, "amount_krw": amount,
            "card_last4": fact.get("card_last4"), "refund_status": fact.get("refund_status"),
            "item": fact.get("item"), "service_period": fact.get("period"),
            "reservation_status": fact.get("reservation_status"),
            "payment_status": fact.get("payment_status") or
                ("paid" if status in ("paid_verified", "refund_verified") else
                 "scheduled" if status == "scheduled" else "unknown"),
            "evidence_status": status, "source_digest": digest, "source_ids": [source_id],
            "identity_source_ids": [source_id],
            "source_digests": [digest],
            "evidence_kind": "authenticated_payment_mail", "source_inventory": inventory,
            "payment_id": payment_id,
            "card_issuer": ota_booking_context.payment_issuer(text),
            "source_binding_ids": sorted(set(fact.get("source_binding_ids") or [])),
        }
        if not event["card_last4"] and card_match:
            event["card_last4"] = card_match.group(1)
        event["ota_event_id"] = _event_id(event["identity_source_ids"])
        events[event["ota_event_id"]] = ota_booking_context.attach(
            event, context.get((event['provider'], event['booking_ref']), ()))
    return list(events.values())


def _extract_signed_payment_message(message):
    """지원 공급자의 서명된 결제·환불 메일을 카드 없이 읽는다."""
    authenticated = ota_mail.authenticated_headers(message, (
        "trip.com", "trip.co.kr", "klook.com", "agoda.com", "booking.com",
        "agoda-messaging.com"))
    if not authenticated:
        return None
    headers, domain = authenticated
    subject = headers.get("subject", "")
    text = ota_mail.body_text(message.get("payload", {}))
    combined = subject + "\n" + text
    is_refund = bool(re.search(r"환불|refund", subject, re.I))
    scheduled_for = ota_mail.scheduled_charge_day(text)
    scheduled = scheduled_for is not None or bool(re.search(
        r"결제\s*(?:예정|될 예정)|scheduled payment|payment is scheduled|will be charged",
        combined, re.I))
    if is_refund:
        complete = bool(re.search(r"환불\s*(?:이|가)?\s*(?:완료|처리)|refund\s+(?:completed|processed|issued|successful)",
                                  combined, re.I))
        label = r"(?:환불(?:된)?\s*금액|refund(?:ed)?\s+amount|amount\s+refunded)"
        event_type = "refund"
    else:
        complete = bool(re.search(
            r"결제.*완료|결제가 완료|payment.*(?:confirm|received|successful|completed)",
            subject, re.I))
        label = r"(?:총\s*(?:지불\s*)?(?:금액|요금)|total(?:\s+price)?|결제\s*(?:완료|금액)|paid\s+amount|payment\s+amount|charged)"
        event_type = "scheduled_charge" if scheduled else "charge"
    refs = set(re.findall(r"(?:예약\s*(?:번호|코드|ID)|booking\s*(?:reference|number|ID)|reservation\s*(?:number|ID))\s*[:：#]?\s*([A-Z0-9-]{6,32})",
                          text, re.I))
    if len(refs) != 1:
        return None
    if not complete and not scheduled and not is_refund:
        event_type = "reservation"
        label = r"(?!)"
    elif is_refund and not complete:
        event_type = "reservation"
        label = r"(?!)"
    elif scheduled:
        event_type = "scheduled_charge"
    values = []
    pattern = re.compile(label + r"\s*[:：]?\s*(KRW|USD|EUR|GBP|JPY|₩|\$|€|£|¥)?\s*([0-9][0-9.,]*)(?:\s*(KRW|USD|EUR|GBP|JPY|원|₩|\$|€|£|¥))?", re.I)
    for prefix_currency, raw, suffix_currency in pattern.findall(text):
        try:
            amount = ota_mail.decimal_amount(raw)
        except (InvalidOperation, ValueError):
            continue
        currency = (prefix_currency or suffix_currency).upper()
        currency = {"₩": "KRW", "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}.get(currency, currency)
        if currency == "원":
            currency = "KRW"
        if currency:
            values.append((currency, amount))
    if complete and not scheduled and len(set(values)) != 1:
        return None
    if len(set(values)) > 1:
        return None
    currency, amount = values[0] if values else ("", None)
    paid_on = ota_mail.sent_day(message, headers) if complete and not scheduled else None
    if complete and not scheduled and paid_on is None:
        return None
    provider = next((name for name, domain_names in (("trip", ("trip.com", "trip.co.kr")),
                     ("klook", ("klook.com",)), ("agoda", ("agoda.com", "agoda-messaging.com")),
                     ("booking", ("booking.com",)))
                     if any(domain == domain_name or domain.endswith("." + domain_name)
                            for domain_name in domain_names)), "")
    digest = _digest(message)
    last4 = re.search(r"(?:card|카드)(?:\s*(?:ending|ends|끝\s*자리))?\s*[:#-]?\s*(?:\*+|X+)?(\d{4})\b", text, re.I)
    payment_id = re.search(r"(?:payment|결제)\s*(?:id|reference|번호)\s*[:#：]?\s*([A-Za-z0-9_-]{4,64})",
                           text, re.I)
    period = ota_mail.service_period(text)
    status = ("scheduled" if scheduled else "refund_verified" if is_refund and complete else
              "paid_verified" if complete else "not_card_charge")
    if event_type == "reservation":
        status = "not_card_charge"
    return {"provider": provider, "booking_ref": next(iter(refs)), "item": "",
            "paid_amount_krw": int(amount) if amount is not None and currency == "KRW" and amount == amount.to_integral_value() else None,
            "amount": str(amount) if amount is not None else None, "currency": currency,
            "paid_on": paid_on.isoformat() if paid_on else None,
            "period": period, "source_sha256": digest,
            "reservation_status": "observed", "payment_status": "scheduled" if scheduled else
                "paid" if complete else "unknown",
            "evidence_status": status, "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "event_type": event_type, "refund_status": "refunded" if is_refund and complete else "none_displayed",
            "card_last4": last4.group(1) if last4 else None,
            "payment_id": payment_id.group(1) if payment_id else None,
            "source_binding_ids": []}


def _portal_events(databases):
    grouped = defaultdict(list)
    database_paths = [Path(item).resolve() for item in ota_portal.as_databases(databases)]
    missing = [{"kind":"portal_database", "path":str(path)} for path in database_paths
               if not path.is_file()]
    if missing:
        raise OtaSourcesError(missing)
    rows = []
    try:
        for database_index, path in enumerate(database_paths):
            rows.extend(ota_portal._read_records(path, database_index))
    except Exception as exc:
        raise OtaSourcesError([{"kind":"portal_loader", "error":type(exc).__name__}]) from exc
    for row in rows:
        grouped[(row["database"], row["booking_number"], row["id"])].append(row)
    events = []
    for (database_index, booking, record_id), evidence in sorted(grouped.items()):
        roles = {row["evidence_role"] for row in evidence}
        if (not ota_portal.REQUIRED_EVIDENCE_ROLES <= roles or
                any(row["conflict_count"] or row["evidence_status"] != "observed" for row in evidence)):
            continue
        first = evidence[0]
        raw = first["payload_json"]
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if digest != first["source_sha256"]:
            raise ValueError("OTA_PORTAL_PAYLOAD_HASH_MISMATCH")
        fact = json.loads(raw)
        if fact.get("provider") != "agoda" or fact.get("booking_number") != booking:
            continue
        amounts = ota_portal.price_amounts(fact)
        if not amounts:
            continue
        verdict = ota_portal.payment_verdict(fact, first["status"])
        # 취소된 예약도 이미 결제된 원본 요금이면 그 charge를 보존한다.
        canonical_paid = (fact.get("payment_status") == "paid" and
                          fact.get("collection_model") == "agoda_collect")
        legacy_paid = verdict == "paid"
        if not (canonical_paid or legacy_paid):
            continue
        if fact.get("refund_status") in ("refund_pending", "refund_requested", "unknown"):
            continue
        card_last4 = str(fact.get("card_last4") or "")
        if not re.fullmatch(r"\d{4}", card_last4):
            continue
        start, end = fact.get("service_start_on"), fact.get("service_end_on")
        period = None
        if start and end:
            try:
                if date.fromisoformat(start) > date.fromisoformat(end):
                    continue
                period = {"starts_on": start, "ends_on": end}
            except (TypeError, ValueError):
                continue
        components = [component for component in fact.get("price_components", []) or []
                      if component.get("kind") == "paid_today"]
        for component_index, component in enumerate(components):
            currency = str(component.get("currency") or "").upper()
            try:
                amount = Decimal(str(component["decimal_text"]).replace(",", ""))
                if not amount.is_finite() or amount <= 0:
                    continue
            except (InvalidOperation, KeyError, TypeError, ValueError):
                continue
            payment_id = component.get("payment_id") or fact.get("payment_id")
            payment_identity = str(payment_id) if payment_id else f"row-{record_id}-part-{component_index}"
            source_id = f"portal:record:{record_id}:payment:{payment_identity}"
            # 포털 원본에는 paid_on/payment_date가 없으므로 날짜를 추정하지 않는다.
            event = {
                "provider": "agoda", "booking_ref": booking, "event_type": "charge",
                "paid_on": fact.get("paid_on"), "amount": str(amount), "currency": currency,
                "amount_krw": int(amount) if currency == "KRW" and amount == amount.to_integral_value() else None,
                "card_last4": card_last4, "service_period": period, "item": fact.get("item"),
                "reservation_status": fact.get("reservation_status"), "payment_status": "paid",
                "refund_status": fact.get("refund_status"), "evidence_status": "paid_verified",
                "source_digest": digest, "source_digests": [digest], "source_ids": [source_id],
                "identity_source_ids": [source_id],
                "payment_id": str(payment_id) if payment_id else None,
                "source_binding_ids": sorted(set(fact.get("source_binding_ids") or [])),
                "evidence_kind": "portal_payment_claim",
                "verified_portal_snapshot": fact.get('evidence_format') == 'agoda-aside-v1',
            }
            event["ota_event_id"] = _event_id(event["identity_source_ids"])
            events.append(event)
        if fact.get("refund_status") in ("refunded", "refund_completed"):
            for component_index, component in enumerate(fact.get("price_components", []) or []):
                if component.get("kind") not in ("refund_completed", "refunded", "refund"):
                    continue
                try:
                    amount = Decimal(str(component["decimal_text"]).replace(",", ""))
                    scale = int(component["scale"])
                    if (not amount.is_finite() or amount <= 0 or
                            amount * (Decimal(10) ** scale) != int(component["minor_units"])):
                        continue
                except (InvalidOperation, KeyError, TypeError, ValueError):
                    continue
                refunded_on = component.get("refunded_on") or component.get("refund_date")
                if refunded_on:
                    try:
                        refunded_on = date.fromisoformat(refunded_on).isoformat()
                    except (TypeError, ValueError):
                        continue
                payment_id = component.get("payment_id") or fact.get("refund_id")
                payment_identity = str(payment_id) if payment_id else f"row-{record_id}-refund-{component_index}"
                source_id = f"portal:record:{record_id}:refund:{payment_identity}"
                event = {"provider":"agoda", "booking_ref":booking, "event_type":"refund",
                         "paid_on":refunded_on, "amount":str(amount),
                         "currency":str(component.get("currency") or "").upper(),
                         "amount_krw":int(amount) if component.get("currency") == "KRW" and
                             amount == amount.to_integral_value() else None,
                         "card_last4":card_last4, "service_period":period, "item":fact.get("item"),
                         "reservation_status":fact.get("reservation_status"), "payment_status":"paid",
                         "refund_status":"refunded", "evidence_status":"refund_verified",
                         "source_digest":digest, "source_digests":[digest], "source_ids":[source_id],
                         "identity_source_ids":[source_id],
                         "payment_id":str(payment_id) if payment_id else None,
                         "source_binding_ids":[], "evidence_kind":"portal_refund_claim"}
                event["ota_event_id"] = _event_id(event["identity_source_ids"])
                events.append(event)
    return _collapse_portal_source_copies(events)


def _event_semantic_conflict(left, right):
    for key in ("provider", "booking_ref", "event_type", "currency", "card_last4",
                "service_period", "payment_id", "paid_on"):
        if left.get(key) is not None and right.get(key) is not None and left[key] != right[key]:
            return True
    if left.get("amount") is not None and right.get("amount") is not None:
        if not _decimal_equal(left["amount"], right["amount"]):
            return True
    return False


def _combine_evidence(group, *, conflict=False):
    item = dict(group[0])
    item["source_ids"] = sorted({source for event in group for source in event.get("source_ids", [])})
    item["source_digests"] = sorted({digest for event in group for digest in
                                      (event.get("source_digests") or [event.get("source_digest")]) if digest})
    item["source_digest"] = (item["source_digests"][0] if len(item["source_digests"]) == 1
                             else _digest(item["source_digests"]))
    item["source_binding_ids"] = sorted({binding for event in group
                                         for binding in event.get("source_binding_ids", [])})
    if conflict:
        item["evidence_status"] = "evidence_conflict"
    item["ota_event_id"] = _event_id(item.get("identity_source_ids") or item["source_ids"])
    return item


def _collapse_portal_source_copies(events):
    """같은 원본 행 ID의 동일 결제 근거만 복사본으로 합친다."""
    groups = defaultdict(list)
    for event in events:
        key = (tuple(event.get("identity_source_ids") or event.get("source_ids") or []),
               event.get("event_type"))
        groups[key].append(event)
    collapsed = []
    for group in groups.values():
        conflict = any(_event_semantic_conflict(group[0], other) for other in group[1:])
        collapsed.append(_combine_evidence(group, conflict=conflict) if len(group) > 1 else group[0])
    return collapsed


def build_ota_payment_events(sources):
    """메일·포털의 검증된 금전 근거만 카드와 독립적으로 이벤트로 만든다."""
    sources = sources or {}
    failures = []
    failures.extend(_as_items(sources.get("missing")))
    failures.extend(_as_items(sources.get("diagnostics")))
    inventory = sources.get("ota_source_inventory") or {}
    failures.extend(_as_items(inventory.get("missing")))
    failures.extend(_as_items(inventory.get("diagnostics")))
    registered = sources.get("registered") or {}
    for key, kind in (("mail_directories", "mail_directory"),
                      ("portal_databases", "portal_database"),
                      ("reference_documents", "reference_document")):
        for value in _as_items(registered.get(key)):
            path = Path(value)
            from app.ota_store import is_store
            exists = (path.is_dir() or is_store(path)) if kind == "mail_directory" else path.is_file()
            if not exists:
                failures.append({"kind":kind, "path":str(path)})
    if failures:
        raise OtaSourcesError(failures)
    references = _as_items(sources.get("reference_documents"))
    if references:
        try:
            reference_report = ota_mail.load_reference_documents(references)
        except Exception as exc:
            raise OtaSourcesError([{"kind":"reference_loader", "error":type(exc).__name__}]) from exc
        if reference_report.get("errors"):
            raise OtaSourcesError(reference_report["errors"])
    events = _mail_events(sources.get("mail_directories"))
    events.extend(_portal_events(sources.get("portal_databases")))
    events = _merge_proven_duplicate_payments(events)
    # 참고 문서는 진단에만 쓰며 금전 이벤트를 공급하지 않는다.
    events.sort(key=lambda event: event["ota_event_id"])
    return events


def _merge_proven_duplicate_payments(events):
    """독립 증거가 같은 실제 지급을 유일하게 가리킬 때만 자료를 합친다."""
    parent = list(range(len(events)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def compatible(left, right):
        if (left.get("provider"), left.get("booking_ref"), left.get("event_type")) != (
                right.get("provider"), right.get("booking_ref"), right.get("event_type")):
            return False
        if left.get("payment_id") and right.get("payment_id"):
            return left["payment_id"] == right["payment_id"]
        left_bindings = set(left.get("source_binding_ids") or [])
        right_bindings = set(right.get("source_binding_ids") or [])
        if left_bindings.intersection(right.get("source_ids") or []) or right_bindings.intersection(left.get("source_ids") or []):
            return True
        return False

    paired = []
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            if compatible(events[i], events[j]):
                paired.append((i, j))
    # 모호한 동액 결제 후보는 병합하지 않고 각각 보존한다.
    for i, j in paired:
        if sum(1 for a, b in paired if a == i or b == i) == 1 and \
                sum(1 for a, b in paired if a == j or b == j) == 1:
            parent[root(j)] = root(i)
    groups = defaultdict(list)
    for index, event in enumerate(events):
        groups[root(index)].append(event)
    merged = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        conflict = any(_event_semantic_conflict(group[0], other) for other in group[1:])
        merged.append(_combine_evidence(group, conflict=conflict))
    return merged


def _direction(row):
    return str(row.get("transaction_direction") or "").lower()


def _event_is_paid(event):
    if event.get("event_type") not in ("charge", "refund"):
        return False
    if event.get("evidence_status") not in ("paid_verified", "refund_verified") or event.get("payment_status") != "paid":
        return False
    if event.get("event_type") == "refund":
        return event.get("evidence_status") == "refund_verified" and event.get("refund_status") in (
            "refunded", "refund_completed")
    return event.get("evidence_status") == "paid_verified"


def _event_amount(event):
    value = event.get("amount_krw")
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
        return abs(amount) if amount.is_finite() and amount != 0 else None
    except InvalidOperation:
        return None


def _card_amount(row):
    try:
        value = Decimal(str(row.get("amount_krw")))
        return value if value.is_finite() and value != 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _descriptor_matches(event, row, rules=()):
    merchant = str(row.get("merchant_normalized") or row.get("merchant") or "").casefold()
    provider = str(event.get("provider") or "").casefold()
    defaults = load_defaults()
    records = defaults.get("provider_merchant_alias_records", {}).get(provider, ())
    approved = [item.get("alias", "") for item in records
                if item.get("status") == "approved" and item.get("version") and item.get("source")]
    for rule in rules or ():
        conditions = rule.get("conditions", {})
        status = str(rule.get("status") or "").lower()
        if (("active" in rule and not bool(rule.get("active"))) or status in ("inactive", "revoked")):
            continue
        if (conditions.get("rule_kind") == "provider_alias" and _rule_scope_valid(conditions) and
                conditions.get("provider", "").casefold() == provider and
                conditions.get("approval_source") and conditions.get("alias_version") and
                rule.get("approved_by")):
            approved.append(conditions["alias"])
    return bool(merchant and any(re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", merchant)
                                 for name in approved if name))


def _rule_scope_valid(conditions):
    if not isinstance(conditions, dict):
        return False
    allowed = {"provider", "item", "merchant_normalized", "issuer", "card_last4",
               "date_lag_days", "date_lag_min_days", "date_lag_max_days", "amount_delta_krw",
               "currency", "event_type", "discount_rate_bps",
               "discount_cap_krw", "minimum_amount_krw", "rounding_mode",
               "payment_method", "valid_from", "valid_to", "rule_kind",
               "approval_source", "alias_version", "alias", "event_issuer_alias"}
    if not set(conditions) <= allowed:
        return False
    if conditions.get("rule_kind") == "provider_alias":
        return (bool(conditions.get("provider")) and bool(conditions.get("alias")) and
                bool(conditions.get("approval_source")) and
                isinstance(conditions.get("alias_version"), int) and
                not isinstance(conditions.get("alias_version"), bool) and
                conditions.get("alias_version") > 0)
    if conditions.get("rule_kind") == "issuer_alias":
        return (bool(conditions.get("provider")) and bool(conditions.get("event_issuer_alias")) and
                bool(conditions.get("issuer")) and bool(conditions.get("approval_source")) and
                isinstance(conditions.get("alias_version"), int) and
                not isinstance(conditions.get("alias_version"), bool) and conditions.get("alias_version") > 0)
    if not conditions.get("provider") or not conditions.get("item"):
        return False
    if not (conditions.get("merchant_normalized") or
            (conditions.get("issuer") and conditions.get("card_last4"))):
        return False
    lag = conditions.get("date_lag_days", 0)
    lag_min, lag_max = conditions.get("date_lag_min_days"), conditions.get("date_lag_max_days")
    if (lag_min is None) != (lag_max is None):
        return False
    if lag_min is not None and ("date_lag_days" in conditions or
            any(isinstance(value, bool) or not isinstance(value, int) or not -7 <= value <= 7
                for value in (lag_min, lag_max)) or lag_min > lag_max):
        return False
    delta = conditions.get("amount_delta_krw", 0)
    last4 = conditions.get("card_last4")
    percent = conditions.get("discount_rate_bps")
    date_bounds = ("valid_from" in conditions, "valid_to" in conditions)
    date_bounds_valid = (date_bounds == (False, False) or (date_bounds == (True, True) and
        _valid_iso_day(conditions.get("valid_from")) and _valid_iso_day(conditions.get("valid_to")) and
        conditions["valid_from"] <= conditions["valid_to"]))
    percent_valid = (percent is None or (isinstance(percent, int) and not isinstance(percent, bool) and
                      1 <= percent <= 10000 and isinstance(conditions.get("minimum_amount_krw"), int) and
                      not isinstance(conditions.get("minimum_amount_krw"), bool) and
                      conditions["minimum_amount_krw"] > 0 and
                      isinstance(conditions.get("discount_cap_krw"), int) and
                      not isinstance(conditions.get("discount_cap_krw"), bool) and
                      conditions["discount_cap_krw"] > 0 and
                      conditions.get("rounding_mode") in ("floor", "half_up", "ceiling") and
                      bool(conditions.get("payment_method")) and
                      bool(conditions.get("valid_from")) and bool(conditions.get("valid_to"))))
    return (isinstance(lag, int) and not isinstance(lag, bool) and -7 <= lag <= 7 and isinstance(delta, int)
            and not isinstance(delta, bool)
            and -10000 <= delta <= 10000 and
            date_bounds_valid and
            percent_valid and
            (last4 in (None, "") or bool(re.fullmatch(r"\d{4}", str(last4)))) and
            (conditions.get("currency") is None or
             bool(re.fullmatch(r"[A-Za-z]{3}", str(conditions["currency"])))) and
            (conditions.get("event_type") is None or conditions["event_type"] in {"charge", "refund"}))


def _rule_matches(event, row, rules):
    for rule in rules:
        status = str(rule.get("status") or "").lower()
        if ("active" in rule and not bool(rule.get("active"))) or status in ("inactive", "revoked"):
            continue
        if not (rule.get("approved_by") or rule.get("user_confirmation") or
                rule.get("approved") is True):
            continue
        allowed = {"provider", "item", "merchant_normalized", "issuer", "card_last4",
                   "date_lag_days", "date_lag_min_days", "date_lag_max_days", "amount_delta_krw",
                   "currency", "event_type", "discount_rate_bps",
                   "discount_cap_krw", "minimum_amount_krw", "rounding_mode",
                   "payment_method", "valid_from", "valid_to", "rule_kind",
                   "approval_source", "alias_version", "alias", "event_issuer_alias"}
        conditions = rule.get("conditions")
        if conditions is None:
            conditions = {key:value for key, value in rule.items() if key in allowed}
        if not _rule_scope_valid(conditions):
            continue
        if conditions.get("rule_kind") in ("provider_alias", "issuer_alias"):
            continue
        if conditions.get("provider") != event.get("provider") or conditions.get("item") != event.get("item"):
            continue
        if conditions.get("currency") and str(conditions["currency"]).upper() != str(event.get("currency") or "").upper():
            continue
        if conditions.get("event_type") and conditions["event_type"] != event.get("event_type"):
            continue
        if "valid_from" in conditions and (not event.get("paid_on") or
                not conditions["valid_from"] <= event["paid_on"] <= conditions["valid_to"]):
            continue
        if conditions.get("merchant_normalized") and conditions["merchant_normalized"] != row.get("merchant_normalized"):
            continue
        if conditions.get("issuer") and conditions["issuer"] != row.get("issuer"):
            continue
        if conditions.get("card_last4") and str(row.get("card_tail") or "") != str(conditions["card_last4"]):
            continue
        if conditions.get("discount_rate_bps") is not None:
            if (str(event.get("event_type")) != "charge" or
                    _direction(row) != "purchase" or
                    str(row.get("payment_method") or "") != str(conditions["payment_method"]) or
                    _event_amount(event) is None or _event_amount(event) < conditions["minimum_amount_krw"] or
                    not event.get("paid_on") or not conditions["valid_from"] <= event["paid_on"] <= conditions["valid_to"]):
                continue
        return True
    return False


def _approved_delta_match(event, row, rules):
    if (str(event.get("currency") or "").upper() != "KRW" or event.get("amount_krw") is None or
            event.get("event_type") != "charge" or _direction(row) != "purchase"):
        return False
    try:
        delta = Decimal(str(row.get("amount_krw"))) - Decimal(str(event["amount_krw"]))
    except (InvalidOperation, TypeError, ValueError):
        return False
    for rule in rules:
        conditions = rule.get("conditions", {})
        expected = conditions.get("amount_delta_krw")
        if expected is None or not _rule_matches(event, row, [rule]):
            continue
        try:
            if delta == Decimal(str(expected)):
                return True
        except (InvalidOperation, TypeError, ValueError):
            continue
    for rule in rules:
        conditions = rule.get("conditions", {})
        rate = conditions.get("discount_rate_bps")
        if rate is None or not _rule_matches(event, row, [rule]):
            continue
        try:
            from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
            modes = {"floor": ROUND_FLOOR, "half_up": ROUND_HALF_UP, "ceiling": ROUND_CEILING}
            amount = _event_amount(event)
            discount = (amount * Decimal(rate) / Decimal(10000)).quantize(Decimal("1"),
                       rounding=modes[conditions["rounding_mode"]])
            discount = min(discount, Decimal(conditions["discount_cap_krw"]))
            if delta == -discount:
                return True
        except (InvalidOperation, KeyError, TypeError, ValueError):
            continue
    delta = Decimal(str(row.get("amount_krw"))) - Decimal(str(event["amount_krw"]))
    discount = load_defaults().get("trip_flight_charge_delta", {})
    step = int(discount.get("step_krw", -1000))
    low, high = int(discount.get("minimum_delta_krw", -10000)), int(discount.get("maximum_delta_krw", -1000))
    if (discount.get("enabled") and str(event.get("provider") or "").casefold() == "trip" and
            str(event.get("item") or "").casefold() in discount.get("item_values", []) and
            str(event.get("currency") or "").upper() == discount.get("currency") and
            event.get("event_type") == "charge" and row.get("transaction_direction") == discount.get("direction") and
            low <= delta <= high and (delta - Decimal(low)) % abs(step) == 0):
        return True
    return False


def _foreign_decimal(value):
    text = str(value).strip()
    if not re.fullmatch(r'[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?', text):
        raise ValueError('INVALID_FOREIGN_AMOUNT')
    return Decimal(text.replace(',', ''))


def _amount_matches(event, row, rules):
    currency = str(event.get("currency") or "").upper()
    if currency == "KRW":
        target, actual = _event_amount(event), _card_amount(row)
        if target is None or actual is None:
            return False
        if event.get("event_type") == "refund":
            return abs(actual) == target
        return (actual > 0 and actual == target) or _approved_delta_match(event, row, rules or [])
    if not currency:
        return False
    try:
        expected = abs(_foreign_decimal(event.get("amount")))
        signed_card_amount = _foreign_decimal(row.get("foreign_amount"))
        actual = abs(signed_card_amount)
        return (str(row.get("foreign_currency") or "").upper() == currency and
                expected.is_finite() and actual.is_finite() and expected == actual and
                (event.get("event_type") == "refund" or signed_card_amount > 0))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _approved_lag_match(event, row, rules):
    if not event.get("paid_on") or not row.get("approval_date"):
        return False
    try:
        lag = (date.fromisoformat(row["approval_date"]) - date.fromisoformat(event["paid_on"])).days
    except (TypeError, ValueError):
        return False
    for rule in rules:
        conditions = rule.get("conditions", rule)
        low, high = _date_lag_bounds(conditions)
        if low is None or not _rule_matches(event, row, [rule]):
            continue
        if low <= lag <= high and lag != 0:
            return True
    return False


def foreign_date_lag_days():
    """외화 결제에서 카드 날짜와 결제일이 다를 수 있는 일수. 소유자 2026-10-16 승인에 따라 하루다."""
    value = load_defaults().get("foreign_date_lag_days", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 7 else 0


def _foreign_day_lag_match(event, row):
    currency = str(event.get("currency") or "").upper()
    limit = foreign_date_lag_days()
    if not limit or currency in ("", "KRW") or not event.get("paid_on") or not row.get("approval_date"):
        return False
    try:
        lag = abs((date.fromisoformat(row["approval_date"]) - date.fromisoformat(event["paid_on"])).days)
    except (TypeError, ValueError):
        return False
    return lag <= limit


def _date_lag_bounds(conditions):
    low, high = conditions.get("date_lag_min_days"), conditions.get("date_lag_max_days")
    if low is not None and high is not None:
        if (isinstance(low, int) and not isinstance(low, bool) and
                isinstance(high, int) and not isinstance(high, bool) and -7 <= low <= high <= 7):
            return low, high
        return None, None
    limit = conditions.get("date_lag_days", 0)
    if not isinstance(limit, int) or isinstance(limit, bool) or not -7 <= limit <= 7:
        return None, None
    return (0, limit) if limit >= 0 else (limit, 0)


def _strict_card_identity(event, row, rules=()):
    hint = str(event.get("card_last4") or "")
    card_tail = str(row.get("card_tail") or row.get("card_last4") or "")
    if hint and (not re.fullmatch(r"\d{4}", hint) or card_tail != hint):
        return False
    issuer = event.get("card_issuer") or event.get("issuer")
    row_issuer = str(row.get("issuer") or "")
    if issuer and str(issuer).casefold() != row_issuer.casefold():
        alias_ok = any(
            (rule.get("approved_by") or rule.get("user_confirmation") or rule.get("approved") is True) and
            rule.get("active", True) and
            str(rule.get("status") or "").lower() not in ("inactive", "revoked") and
            (rule.get("conditions") or {}).get("rule_kind") == "issuer_alias" and
            _rule_scope_valid(rule.get("conditions") or {}) and
            str((rule.get("conditions") or {}).get("provider")) == str(event.get("provider")) and
            str((rule.get("conditions") or {}).get("event_issuer_alias", "")).casefold() == str(issuer).casefold() and
            str((rule.get("conditions") or {}).get("issuer", "")).casefold() == row_issuer.casefold() and
            (rule.get("conditions") or {}).get("approval_source") and
            (rule.get("conditions") or {}).get("alias_version")
            for rule in rules or ())
        if not alias_ok:
            return False
    ota_auth = event.get("authorization_number") or event.get("approval_number")
    card_auth = row.get("authorization_number") or row.get("approval_number") or row.get("authorization_id")
    ota_scheme = event.get("authorization_scheme") or event.get("authorization_number_scheme")
    card_scheme = row.get("authorization_scheme") or row.get("authorization_number_scheme")
    if ota_auth and card_auth and ota_scheme and card_scheme and ota_scheme == card_scheme:
        if str(ota_auth).strip() != str(card_auth).strip():
            return False
    return True


def _has_corroborator(event, row, rules):
    hint = str(event.get("card_last4") or "")
    card = str(row.get("card_tail") or row.get("card_last4") or "")
    if hint and card == hint:
        return True
    ota_auth = event.get("authorization_number") or event.get("approval_number")
    card_auth = row.get("authorization_number") or row.get("approval_number") or row.get("authorization_id")
    ota_scheme = event.get("authorization_scheme") or event.get("authorization_number_scheme")
    card_scheme = row.get("authorization_scheme") or row.get("authorization_number_scheme")
    if ota_auth and card_auth and ota_scheme and ota_scheme == card_scheme and str(ota_auth) == str(card_auth):
        return True
    ota_payment = event.get("payment_id")
    card_payment = row.get("payment_id") or row.get("ota_payment_id")
    ota_payment_scheme = event.get("payment_id_scheme") or event.get("payment_scheme")
    card_payment_scheme = row.get("payment_id_scheme") or row.get("payment_scheme")
    if (ota_payment and card_payment and ota_payment_scheme and
            ota_payment_scheme == card_payment_scheme and str(ota_payment) == str(card_payment)):
        return True
    # 트립닷컴 결제는 가맹점 이름이 결제 대행사마다 달라서 날짜·금액·유일 후보로 판단한다(사용자 승인 2026-10-15).
    if str(event.get("provider") or "").casefold() == "trip":
        return True
    return _descriptor_matches(event, row, rules) or _rule_matches(event, row, rules)


def _eligible_cards(event, transactions, links=None, rules=None):
    if not event.get("paid_on"):
        return []
    expected_direction = "refund" if event.get("event_type") == "refund" else "purchase"
    eligible = []
    for row in transactions:
        if row.get("duplicate_of") or row.get("parse_error") or row.get("conflict_reason"):
            continue
        if not _strict_card_identity(event, row, rules):
            continue
        if _direction(row) != expected_direction or not _amount_matches(event, row, rules):
            continue
        exact_date = row.get("approval_date") == event.get("paid_on")
        if not exact_date and not _approved_lag_match(event, row, rules or []) and not _foreign_day_lag_match(event, row):
            continue
        last4 = str(event.get("card_last4") or "")
        if last4 and not (str(row.get("card_tail") or row.get("card_last4") or "").endswith(last4)):
            continue
        if not _has_corroborator(event, row, rules or []):
            continue
        copy = dict(row)
        copy["already_linked_event_id"] = (links or {}).get(row.get("transaction_id"))
        eligible.append(copy)
    # Keep every approved edge. Exact-amount priority belongs to the global
    # assignment, since pruning here can make a feasible repeated group partial.
    return eligible


def portal_payment_date_required():
    """2026-10-08 결제일 필수 기본값. 2026-10-21 승인한 아고다 일대일 추론은 별도 규칙에서 검증한다."""
    return bool(load_defaults().get("portal_payment_date_required", True))


def pair_check(event, row, rules=None):
    """이벤트와 카드 행 한 쌍을 코어 규칙으로만 확인한다. 통과하면 None, 막히면 사유 코드를 돌려준다."""
    rules = rules or []
    if row.get("duplicate_of") or row.get("parse_error") or row.get("conflict_reason"):
        return "row_flagged"
    paid_on = event.get("paid_on")
    if not paid_on and portal_payment_date_required():
        return "payment_date_unknown"
    if not _strict_card_identity(event, row, rules):
        return "card_identity"
    expected_direction = "refund" if event.get("event_type") == "refund" else "purchase"
    if _direction(row) != expected_direction:
        return "direction"
    if not _amount_matches(event, row, rules):
        return "amount"
    if paid_on and row.get("approval_date") != paid_on and not _approved_lag_match(event, row, rules) and not _foreign_day_lag_match(event, row):
        return "date"
    last4 = str(event.get("card_last4") or "")
    if last4 and not str(row.get("card_tail") or row.get("card_last4") or "").endswith(last4):
        return "card_identity"
    if not _has_corroborator(event, row, rules):
        return "corroboration"
    return None


def _assign_exact_first(events, options_by_event, *, unavailable=(), excluded_edges=()):
    """Maximize cardinality, then exact edges, then the approved stable order."""
    ordered_events = sorted(events, key=lambda item:(str(item.get("booking_ref") or ""),
                                                      str(item.get("ota_event_id") or "")))
    event_ids = [str(value.get("ota_event_id") or "") for value in ordered_events]
    unavailable = set(unavailable)
    excluded_edges = set(excluded_edges)
    row_by_card = {str(row.get("transaction_id")):row for identity in event_ids
                   for row in options_by_event.get(identity, ()) if row.get("transaction_id")}
    card_ids = sorted((identity for identity in row_by_card if identity not in unavailable),
        key=lambda identity:(str(row_by_card[identity].get("approval_number") or
                                 row_by_card[identity].get("authorization_number") or
                                 row_by_card[identity].get("authorization_id") or ""), identity))
    if not event_ids or not card_ids:
        return []
    source = 0
    event_base = 1
    card_base = event_base + len(event_ids)
    sink = card_base + len(card_ids)
    graph = [[] for _ in range(sink + 1)]
    def edge(start, end, capacity, cost):
        forward = [end, len(graph[end]), capacity, cost]
        reverse = [start, len(graph[start]), 0, -cost]
        graph[start].append(forward)
        graph[end].append(reverse)
        return forward
    card_index = {identity:index for index, identity in enumerate(card_ids)}
    max_stable_cost = (len(card_ids) - 1) * len(event_ids) * (len(event_ids) + 1) // 2
    exact_priority = max_stable_cost + 1
    chosen_edges = {}
    for index, identity in enumerate(event_ids):
        edge(source, event_base + index, 1, 0)
        options = options_by_event.get(identity, ())
        for row in options:
            card_id = str(row.get("transaction_id") or "")
            if card_id not in card_index or (identity, card_id) in excluded_edges:
                continue
            exact = (str(ordered_events[index].get("currency") or "").upper() != "KRW" or
                     _event_amount(ordered_events[index]) == _card_amount(row))
            stable_cost = card_index[card_id] * (len(event_ids) - index)
            chosen_edges[(identity, card_id)] = edge(event_base + index,
                card_base + card_index[card_id], 1,
                stable_cost - (exact_priority if exact else 0))
    for index in range(len(card_ids)):
        edge(card_base + index, sink, 1, 0)
    while True:
        distances = [None] * len(graph)
        previous = [None] * len(graph)
        in_queue = [False] * len(graph)
        queue = [source]
        distances[source] = 0
        in_queue[source] = True
        cursor = 0
        while cursor < len(queue):
            node = queue[cursor]
            cursor += 1
            in_queue[node] = False
            for edge_index, current in enumerate(graph[node]):
                target, _reverse, capacity, cost = current
                if capacity <= 0:
                    continue
                distance = distances[node] + cost
                if distances[target] is None or distance < distances[target]:
                    distances[target] = distance
                    previous[target] = (node, edge_index)
                    if not in_queue[target]:
                        queue.append(target)
                        in_queue[target] = True
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            parent, edge_index = previous[node]
            current = graph[parent][edge_index]
            current[2] -= 1
            graph[node][current[1]][2] += 1
            node = parent
    return sorted((identity, card_id) for (identity, card_id), selected in chosen_edges.items()
                  if selected[2] == 0)


def _ambiguous_optimal_singletons(events, options_by_event, selected, unavailable=()):
    """Return singleton events whose maximum-cardinality exact match is not unique."""
    unavailable = set(unavailable)
    event_by_id = {str(event.get("ota_event_id") or ""):event for event in events}
    card_to_events = defaultdict(set)
    for identity in event_by_id:
        for row in options_by_event.get(identity, ()):
            card_id = str(row.get("transaction_id") or "")
            if card_id and card_id not in unavailable:
                card_to_events[card_id].add(identity)
    adjacency = defaultdict(set)
    for card_id, identities in card_to_events.items():
        for identity in identities:
            adjacency[identity].update(identities - {identity})
    unresolved = set(event_by_id)
    ambiguous = set()
    while unresolved:
        root = unresolved.pop()
        component = {root}
        stack = [root]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current] & unresolved:
                unresolved.remove(neighbor)
                component.add(neighbor)
                stack.append(neighbor)
        root_cards = {str(row.get("transaction_id")) for row in options_by_event.get(root, ())
                      if row.get("transaction_id") and str(row.get("transaction_id")) not in unavailable}
        if len(component) == 1 and len(root_cards) <= 1:
            continue
        component_events = [event_by_id[identity] for identity in component]
        current_pairs = [(identity, card_id) for identity, card_id in selected if identity in component]
        current_count = len(current_pairs)
        current_exact = sum(
            str(event_by_id[identity].get("currency") or "").upper() != "KRW" or
            _event_amount(event_by_id[identity]) == _card_amount(next(
                row for row in options_by_event[identity] if str(row.get("transaction_id")) == card_id))
            for identity, card_id in current_pairs)
        for pair in current_pairs:
            alternative = _assign_exact_first(component_events, options_by_event,
                unavailable=unavailable, excluded_edges={pair})
            alternative_count = len(alternative)
            alternative_exact = 0
            for identity, card_id in alternative:
                row = next(row for row in options_by_event[identity]
                           if str(row.get("transaction_id")) == card_id)
                alternative_exact += int(str(event_by_id[identity].get("currency") or "").upper() != "KRW" or
                                         _event_amount(event_by_id[identity]) == _card_amount(row))
            if alternative_count == current_count and alternative_exact == current_exact:
                ambiguous.update(component)
    return ambiguous


def same_date_cards(event, transactions, *, links=None, rules=None):
    """가맹점과 금액에 제한 없이 승인된 날짜 범위의 모든 카드 행을 돌려준다."""
    if not event.get("paid_on"):
        return []
    links = links or {}
    linked_by_transaction = {}
    for key, value in links.items():
        if isinstance(value, dict) and value.get("transaction_id"):
            linked_by_transaction[value["transaction_id"]] = key
        elif not isinstance(value, dict):
            linked_by_transaction[key] = value
    rows = []
    allowed_dates = {event.get("paid_on")}
    if event.get("paid_on"):
        try:
            paid_on = date.fromisoformat(event["paid_on"])
            for rule in rules or []:
                conditions = rule.get("conditions", rule)
                if not _rule_matches(event, {"merchant_normalized": conditions.get("merchant_normalized"),
                                             "issuer": conditions.get("issuer"),
                                             "card_tail": conditions.get("card_last4")}, [rule]):
                    continue
                low, high = _date_lag_bounds(conditions)
                if low is not None:
                    allowed_dates.update((paid_on + timedelta(days=day)).isoformat()
                                         for day in range(low, high + 1))
        except (TypeError, ValueError):
            pass
    for row in transactions:
        if row.get("approval_date") not in allowed_dates:
            continue
        copy = dict(row)
        copy["already_linked_event_id"] = linked_by_transaction.get(row.get("transaction_id"))
        rows.append(copy)
    return sorted(rows, key=lambda row: (
        _card_amount(row) is None, _card_amount(row) or Decimal(0), str(row.get("card_tail") or ""),
        str(row.get("merchant_normalized") or row.get("merchant") or ""),
        str(row.get("transaction_id") or "")))


def _event_group_signature(event):
    return (event.get("provider"), event.get("item"), event.get("event_type"),
            event.get("paid_on"), str(event.get("currency") or "").upper(),
            str(event.get("amount") if event.get("currency") != "KRW" else event.get("amount_krw")))


def _card_identity(row):
    return (str(row.get("issuer") or "").strip().casefold(),
            str(row.get("card_tail") or row.get("card_last4") or "").strip(),
            _direction(row))


def match_ota_payment_events(events, transactions, *, existing_links=None, rules=None,
                             frozen_groups=None):
    """검증된 OTA 이벤트와 카드 행을 입력 변경 없이 전역 일대일 대조한다."""
    existing_links = existing_links or {}
    rules = rules or []
    frozen_groups = frozen_groups or []
    rows = {row.get("transaction_id"): row for row in transactions if row.get("transaction_id")}
    result = []
    claimed = {}
    pinned_counts = defaultdict(int)
    # 이미 고정된 연결을 먼저 점유시켜 자동 대조가 이를 바꾸거나 재사용하지 않게 한다.
    for identity, link in existing_links.items():
        transaction_id = link.get("transaction_id") if isinstance(link, dict) else link
        if transaction_id:
            claimed[transaction_id] = identity
            pinned_counts[transaction_id] += 1
    pin_owners_by_card = defaultdict(list)
    for pin in frozen_groups:
        for transaction_id in pin.get("card_ids", ()):
            pin_owners_by_card[str(transaction_id)].append(pin)
    all_events_by_id = {str(event.get("ota_event_id")):event for event in events
                        if event.get("ota_event_id") is not None}
    raw_options = {
        str(event.get("ota_event_id")): _eligible_cards(event, transactions, rules=rules)
        for event in events if not existing_links.get(event.get("ota_event_id"))
    }
    options_by_event = {}
    for identity, options in raw_options.items():
        options_by_event[identity] = [row for row in options
            if str(row.get("transaction_id")) not in claimed and
            all(identity in {str(value) for value in pin.get("event_ids", ())}
                for pin in pin_owners_by_card.get(str(row.get("transaction_id")), ()))]
    # 동일 조건의 반복 거래를 먼저 나눈 뒤, 후보 카드가 증명하는 카드 정체성별로 묶는다.
    by_signature = defaultdict(list)
    signature_by_event = {}
    for event in events:
        identity = event.get("ota_event_id")
        if identity in existing_links or not _event_is_paid(event) or not event.get("paid_on"):
            continue
        signature = _event_group_signature(event)
        signature_by_event[str(identity)] = signature
        by_signature[signature].append(event)
    grouped_results = {}
    group_specs = []
    reserved_partial = set(pin_owners_by_card)
    stale_pin_indexes = set()
    for pin_index, pin in enumerate(frozen_groups):
        pin_event_ids = {str(identity) for identity in pin.get("event_ids", ())}
        pin_card_ids = {str(identity) for identity in pin.get("card_ids", ())}
        present = [identity for identity in pin_event_ids if identity in all_events_by_id]
        signatures = {signature_by_event.get(identity) for identity in pin_event_ids}
        stale = (not pin_event_ids or not pin_card_ids or len(present) != len(pin_event_ids) or
                 None in signatures or len(signatures) != 1)
        for identity, transaction_id in (pin.get("mapping") or {}).items():
            identity = str(identity)
            if identity not in options_by_event or str(transaction_id) not in {
                    str(row.get("transaction_id")) for row in options_by_event.get(identity, ())}:
                stale = True
        if not stale:
            identity_keys = {_card_identity(row) for identity in pin_event_ids
                             for row in options_by_event.get(identity, ())}
            if len(identity_keys) != 1:
                stale = True
        if not stale:
            continue
        stale_pin_indexes.add(pin_index)
        current_card_ids = pin_card_ids | {str(row.get("transaction_id"))
            for identity in present for row in raw_options.get(identity, ()) if row.get("transaction_id")}
        reserved_partial.update(current_card_ids)
        for identity in present:
            event = all_events_by_id[identity]
            if identity in existing_links:
                continue
            grouped_results[identity] = dict(event, status="HOLD_GROUP_CHANGED", transaction_id=None,
                candidates=sorted(current_card_ids), reason="frozen_group_evidence_changed",
                review_warning="confirm_group_reallocation", frozen_mapping=pin.get("mapping", {}),
                proposed_mapping={}, group_order_snapshot=pin.get("order_snapshot", {}),
                group_count={"ota":len(pin_event_ids), "cards":len(current_card_ids)},
                ota_group_ids=sorted(pin_event_ids), card_group_ids=sorted(current_card_ids),
                reserved_card_ids=sorted(current_card_ids))
    for pin_index, pin in enumerate(frozen_groups):
        if pin_index in stale_pin_indexes:
            continue
        pin_event_ids = {str(identity) for identity in pin.get("event_ids", ())}
        signatures = {signature_by_event.get(identity) for identity in pin_event_ids}
        signature = next(iter(signatures))
        signature_events = by_signature.get(signature, ())
        if {str(item.get("ota_event_id")) for item in signature_events} != pin_event_ids:
            stale_pin_indexes.add(pin_index)
            current_card_ids = {str(identity) for identity in pin.get("card_ids", ())}
            current_event_ids = {str(item.get("ota_event_id")) for item in signature_events}
            current_card_ids.update(str(row.get("transaction_id")) for identity in pin_event_ids | current_event_ids
                                     for row in raw_options.get(identity, ()) if row.get("transaction_id"))
            reserved_partial.update(current_card_ids)
            for identity in pin_event_ids | current_event_ids:
                if identity in all_events_by_id and identity not in existing_links:
                    event = all_events_by_id[identity]
                    grouped_results[identity] = dict(event, status="HOLD_GROUP_CHANGED", transaction_id=None,
                        candidates=sorted(current_card_ids), reason="frozen_group_membership_changed",
                        review_warning="confirm_group_reallocation", frozen_mapping=pin.get("mapping", {}),
                        proposed_mapping={}, group_order_snapshot=pin.get("order_snapshot", {}),
                        group_count={"ota":len(pin_event_ids), "cards":len(current_card_ids)},
                        ota_group_ids=sorted(pin_event_ids), card_group_ids=sorted(current_card_ids),
                        reserved_card_ids=sorted(current_card_ids))
    for group_events in by_signature.values():
        card_identity_groups = defaultdict(list)
        for event in group_events:
            identity = str(event.get("ota_event_id"))
            if identity in grouped_results:
                continue
            identity_keys = {_card_identity(row) for row in options_by_event.get(identity, ())}
            if len(identity_keys) == 1:
                card_identity_groups[next(iter(identity_keys))].append(event)
        for card_identity, identity_events in card_identity_groups.items():
            event_ids = [event.get("ota_event_id") for event in identity_events]
            card_ids = {str(row.get("transaction_id")) for identity in event_ids
                        for row in options_by_event.get(str(identity), ())
                        if _card_identity(row) == card_identity and row.get("transaction_id")}
            if not card_ids or (len(identity_events) < 2 and len(card_ids) < 2):
                continue
            if len(identity_events) == 1:
                identity = str(identity_events[0].get("ota_event_id"))
                overlaps_other = any(other_id != identity and card_ids &
                    {str(row.get("transaction_id")) for row in other_options}
                    for other_id, other_options in options_by_event.items())
                if overlaps_other:
                    continue
            sorted_events = sorted(identity_events, key=lambda item: (str(item.get("booking_ref") or ""),
                                                                       str(item.get("ota_event_id") or "")))
            card_rows = {str(row.get("transaction_id")):row for identity in event_ids
                         for row in options_by_event.get(str(identity), ())
                         if str(row.get("transaction_id")) in card_ids}
            if (not card_identity[0] or not re.fullmatch(r"\d{4}", card_identity[1]) or
                    any(event.get("card_last4") and event.get("card_last4") != card_identity[1]
                        for event in sorted_events)):
                all_ids = sorted(card_ids)
                reserved_partial.update(card_ids)
                for ota in sorted_events:
                    grouped_results[ota["ota_event_id"]] = dict(ota, status="HOLD_AMBIGUOUS",
                        transaction_id=None, candidates=all_ids,
                        reason="repeated_group_card_identity_conflict",
                        group_count={"ota":len(sorted_events), "cards":len(card_ids)},
                        ota_group_ids=sorted(event_ids), card_group_ids=all_ids,
                        reserved_card_ids=all_ids)
                continue
            sorted_cards = sorted(card_ids, key=lambda identity: (
                str(card_rows[identity].get("approval_number") or card_rows[identity].get("authorization_number") or
                    card_rows[identity].get("authorization_id") or ""), str(identity)))
            order_snapshot = {"events":[[str(item.get("ota_event_id")),str(item.get("booking_ref") or "")]
                                        for item in sorted_events],
                "cards":[[str(card_id),str(card_rows[card_id].get("approval_number") or
                           card_rows[card_id].get("authorization_number") or
                           card_rows[card_id].get("authorization_id") or "")] for card_id in sorted_cards],
                "event_evidence":[[str(item.get("ota_event_id")),_digest(item)] for item in sorted_events],
                "card_evidence":[[str(card_id),_digest(card_rows[card_id])] for card_id in sorted_cards],
                "eligible_edges_digest":_digest([[str(item.get("ota_event_id")), str(card_id)]
                    for item in sorted_events
                    for card_id in sorted(str(row.get("transaction_id"))
                        for row in options_by_event.get(str(item.get("ota_event_id")), ())
                        if str(row.get("transaction_id")) in card_ids)])}
            selected_pairs = _assign_exact_first(sorted_events, options_by_event,
                                                  unavailable=set(claimed))
            matched_count = len(selected_pairs)
            current_event_ids = sorted(str(identity) for identity in event_ids)
            current_card_ids = sorted(card_ids)
            pin = next((item for item in frozen_groups
                        if set(map(str, item.get("event_ids", ()))) & set(current_event_ids)), None)
            if pin:
                pin_event_ids = set(map(str, pin.get("event_ids", ())))
                pin_card_ids = set(map(str, pin.get("card_ids", ())))
                frozen_mapping = {str(key):str(value) for key, value in (pin.get("mapping") or {}).items()}
                reserved_ids = sorted(pin_card_ids | set(current_card_ids))
                if (pin_event_ids != set(current_event_ids) or pin_card_ids != set(current_card_ids) or
                        (pin.get("order_snapshot") and pin["order_snapshot"] != order_snapshot) or
                        set(frozen_mapping) != set(current_event_ids) or
                        set(frozen_mapping.values()) != set(current_card_ids)):
                    for ota in sorted_events:
                        grouped_results[ota["ota_event_id"]] = dict(ota, status="HOLD_GROUP_CHANGED",
                            transaction_id=None, candidates=reserved_ids,
                            reason="frozen_group_evidence_changed", review_warning="confirm_group_reallocation",
                            frozen_mapping=pin.get("mapping", {}),
                            proposed_mapping=dict(selected_pairs),
                            group_order_snapshot=order_snapshot,
                            group_count={"ota":len(pin_event_ids | set(current_event_ids)), "cards":len(reserved_ids)},
                            ota_group_ids=sorted(pin_event_ids | set(current_event_ids)),
                            card_group_ids=reserved_ids,
                            reserved_card_ids=reserved_ids)
                    reserved_partial.update(reserved_ids)
                    continue
                selected_pairs = sorted(frozen_mapping.items())
            group_specs.append({"events": sorted_events, "event_ids": event_ids,
                                "card_ids": sorted(card_ids),
                                "pairs": selected_pairs, "matched_count": matched_count,
                                "card_rows": card_rows, "pin":pin,
                                "order_snapshot":order_snapshot})
    # A card candidate shared by separate groups or singleton events makes
    # every connected component ambiguous. Never claim by iteration order.
    event_group = {event["ota_event_id"]: spec for spec in group_specs for event in spec["events"]}
    card_owners = defaultdict(set)
    for index, spec in enumerate(group_specs):
        for card_id in spec["card_ids"]:
            card_owners[card_id].add(index)
    collision_indices = {index for owners in card_owners.values() if len(owners) > 1 for index in owners}
    grouped_event_ids = set(event_group) | set(grouped_results)
    for identity, options in options_by_event.items():
        if identity in grouped_event_ids:
            continue
        for row in options:
            for index in card_owners.get(row["transaction_id"], ()):
                collision_indices.add(index)
                for spec in group_specs:
                    if identity in {event["ota_event_id"] for event in spec["events"]}:
                        collision_indices.add(group_specs.index(spec))
    for index, spec in enumerate(group_specs):
        sorted_events, card_ids = spec["events"], spec["card_ids"]
        all_event_ids, all_card_ids = sorted(spec["event_ids"]), sorted(card_ids)
        if index in collision_indices:
            for ota in sorted_events:
                grouped_results[ota["ota_event_id"]] = dict(ota, status="HOLD_AMBIGUOUS",
                    transaction_id=None, candidates=all_card_ids, reason="overlapping_global_group_candidates",
                    group_count={"ota":len(sorted_events), "cards":len(card_ids)},
                    ota_group_ids=all_event_ids, card_group_ids=all_card_ids,
                    reserved_card_ids=all_card_ids)
            reserved_partial.update(card_ids)
            continue
        if spec["matched_count"] < len(sorted_events) or spec["matched_count"] < len(card_ids):
            reserved_partial.update(card_ids)
            status = ("HOLD_AMBIGUOUS" if len(sorted_events) > 1 and len(card_ids) == 1
                      else "HOLD_PARTIAL_GROUP")
            for ota in sorted_events:
                grouped_results[ota["ota_event_id"]] = dict(ota, status=status, transaction_id=None,
                    candidates=all_card_ids, reason="partial_repeated_payment_group",
                    matched_count=spec["matched_count"], unmatched_ota_count=max(0, len(sorted_events)-spec["matched_count"]),
                    unmatched_card_count=max(0, len(card_ids)-spec["matched_count"]),
                    group_count={"ota":len(sorted_events), "cards":len(card_ids)},
                    ota_group_ids=all_event_ids, card_group_ids=all_card_ids,
                    reserved_card_ids=all_card_ids)
            continue
        selected = dict(spec["pairs"])
        # 같은 금액 반복 결제는 승인 없이 승인번호·예약번호 순서로 자동 배정하고, 기록 근거를 남겨 월별 검토에서 고친다.
        for ota in sorted_events:
            identity = ota["ota_event_id"]
            card_id = selected[identity]
            allocation_basis = ("frozen_user_confirmed_order" if spec.get("pin")
                                else "auto_stable_order")
            grouped_results[identity] = dict(ota, status="MATCHED_AUTO", transaction_id=card_id,
                candidates=[card_id], reason=allocation_basis, allocation_basis=allocation_basis,
                group_order_frozen=bool(spec.get("pin")),
                individual_payment_evidence=False, group_count={"ota":len(sorted_events), "cards":len(card_ids)},
                ota_group_ids=all_event_ids, card_group_ids=all_card_ids,
                group_order_snapshot=spec["order_snapshot"],
                rule_delta_krw=(int(_card_amount(spec["card_rows"][card_id]) - _event_amount(ota))
                                if _card_amount(spec["card_rows"][card_id]) != _event_amount(ota) and
                                _event_amount(ota) is not None and _card_amount(spec["card_rows"][card_id]) is not None else None),
                discount_cause_confirmed=False)
            claimed[card_id] = identity
    # Resolve remaining singleton candidates as one bipartite problem. Exact
    # edges win globally; equal best allocations remain a hold.
    singleton_events = [event for event in events if event.get("ota_event_id") not in grouped_event_ids and
                        event.get("ota_event_id") not in existing_links and _event_is_paid(event) and
                        event.get("paid_on")]
    singleton_events.sort(key=lambda event: str(event.get("ota_event_id") or ""))
    singleton_unavailable = set(claimed) | reserved_partial
    singleton_pairs = _assign_exact_first(singleton_events, options_by_event,
                                           unavailable=singleton_unavailable)
    singleton_selected = dict(singleton_pairs)
    singleton_conflicts = _ambiguous_optimal_singletons(
        singleton_events, options_by_event, singleton_pairs, unavailable=singleton_unavailable)
    from app import ota_inference
    inferred_pairs = ota_inference.unique_pairs(events, transactions,
        occupied=set(claimed) | set(reserved_partial), rules=rules)
    for event in events:
        identity = event.get("ota_event_id")
        if identity in grouped_results:
            result.append(grouped_results[identity])
            continue
        link = existing_links.get(identity)
        if link:
            transaction_id = link.get("transaction_id") if isinstance(link, dict) else link
            status = link.get("status", "MATCHED_USER") if isinstance(link, dict) else "MATCHED_USER"
            if pinned_counts[transaction_id] > 1:
                result.append(dict(event, status="HOLD_AMBIGUOUS", transaction_id=None,
                                   candidates=[transaction_id], reason="pinned_global_one_to_one_collision"))
                continue
            if status not in ("MATCHED_AUTO", "MATCHED_USER"):
                result.append(dict(event, status="HOLD_EVIDENCE_CONFLICT", transaction_id=None,
                                   candidates=[], reason="invalid_existing_link_status"))
                continue
            if isinstance(link, dict) and link.get("legacy_exact"):
                row = rows.get(transaction_id)
                valid = (row is not None and link.get("source_digest") == event.get("source_digest") and
                         status in ("MATCHED_AUTO", "MATCHED_USER") and _event_is_paid(event))
                if valid:
                    expected = "refund" if event.get("event_type") == "refund" else "purchase"
                    card_hint = str(event.get("card_last4") or "")
                    actual_hint = str(row.get("card_tail") or row.get("card_last4") or "")
                    amount_match = _amount_matches(event, row, rules)
                    valid = (amount_match and _direction(row) == expected and
                             (not card_hint or actual_hint.endswith(card_hint)))
                    old_sources = set(link.get("source_digests") or [])
                    current_sources = set(event.get("source_digests") or [])
                    valid = valid and bool(old_sources and current_sources and old_sources & current_sources)
                if not valid:
                    result.append(dict(event, status="HOLD_EVIDENCE_CONFLICT", transaction_id=None,
                                       candidates=[], reason="legacy_exact_binding_validation_failed"))
                    continue
            result.append(dict(event, status=status, transaction_id=transaction_id,
                               candidates=[], reason="pinned_existing_link"))
            continue
        if not _event_is_paid(event):
            if event.get("evidence_status") in ("conflict", "evidence_conflict", "refund_conflict"):
                status = "HOLD_EVIDENCE_CONFLICT"
            else:
                status = ("PENDING_PAYMENT" if event.get("event_type") == "scheduled_charge" or
                          event.get("evidence_status") == "scheduled" or
                          event.get("payment_status") == "scheduled" else "NOT_CARD_CHARGE")
            result.append(dict(event, status=status, transaction_id=None, candidates=[],
                               reason="no_verified_paid_evidence"))
            continue
        if event.get("event_type") == "refund" and event.get("refund_status") not in ("refunded", "refund_completed"):
            result.append(dict(event, status="HOLD_EVIDENCE_CONFLICT", transaction_id=None,
                               candidates=[], reason="refund_not_explicitly_verified"))
            continue
        if identity in inferred_pairs:
            transaction_id = inferred_pairs[identity]['transaction_id']
            result.append(dict(event, status='MATCHED_AUTO', transaction_id=transaction_id,
                               candidates=[transaction_id], reason=ota_inference.BASIS,
                               allocation_basis=ota_inference.BASIS, inferred_link=True,
                               inference_basis=ota_inference.NOTE, payment_date_verified=False))
            continue
        if not event.get("paid_on"):
            result.append(dict(event, status="HOLD_DATE_UNKNOWN", transaction_id=None,
                               candidates=[], reason="payment_date_not_in_source"))
            continue
        options = options_by_event.get(identity, [])
        if identity in singleton_conflicts:
            reserved_ids = sorted({str(row.get("transaction_id"))
                                   for candidate_id in singleton_conflicts
                                   for row in options_by_event.get(candidate_id, ())
                                   if row.get("transaction_id")})
            reserved_partial.update(reserved_ids)
            result.append(dict(event, status="HOLD_AMBIGUOUS", transaction_id=None,
                               candidates=[row["transaction_id"] for row in options],
                               reserved_card_ids=reserved_ids,
                               reason="equal_optimum_global_singleton_allocations"))
            continue
        if any(row.get("transaction_id") in reserved_partial for row in options):
            result.append(dict(event, status="HOLD_AMBIGUOUS", transaction_id=None,
                               candidates=[row["transaction_id"] for row in options],
                               reserved_card_ids=sorted({str(row.get("transaction_id")) for row in options
                                                         if row.get("transaction_id") in reserved_partial}),
                               reason="card_reserved_by_partial_or_ambiguous_group"))
            continue
        free = [row for row in options if row["transaction_id"] not in claimed]
        if identity in singleton_selected:
            free = [row for row in options if row["transaction_id"] == singleton_selected[identity]]
        competing = False
        if not options:
            blocked_candidates = [row for row in raw_options.get(str(identity), ())
                if str(row.get("transaction_id")) in claimed or any(
                    str(identity) not in {str(value) for value in pin.get("event_ids", ())}
                    for pin in pin_owners_by_card.get(str(row.get("transaction_id")), ()))]
            if blocked_candidates:
                blocked_ids = sorted({str(row.get("transaction_id")) for row in blocked_candidates
                                      if row.get("transaction_id")})
                result.append(dict(event, status="HOLD_AMBIGUOUS", transaction_id=None,
                                   candidates=blocked_ids, reserved_card_ids=blocked_ids,
                                   reason="candidate_cards_reserved_by_existing_or_frozen_link"))
                continue
            wrong_amount = [row for row in transactions
                            if row.get("approval_date") == event.get("paid_on") and
                            _direction(row) == ("refund" if event.get("event_type") == "refund" else "purchase") and
                            row.get("transaction_id") not in claimed and
                            _strict_card_identity(event, row, rules) and
                            _has_corroborator(event, row, rules)]
            status = "HOLD_AMOUNT_MISMATCH" if wrong_amount else "HOLD_NO_CARD"
            # 같은 금액·날짜·방향의 카드가 있어도 가맹점 별칭 승인이 없으면 연결하지 않는다. 사유를 따로 밝힌다.
            exact_direction = "refund" if event.get("event_type") == "refund" else "purchase"
            exact_cards = [row for row in transactions
                           if row.get("approval_date") == event.get("paid_on") and
                           _direction(row) == exact_direction and
                           row.get("transaction_id") not in claimed and
                           not row.get("duplicate_of") and not row.get("parse_error") and
                           not row.get("conflict_reason") and
                           _amount_matches(event, row, rules) and
                           _strict_card_identity(event, row, rules)]
            if wrong_amount:
                reason = "amount_differs"
            elif exact_cards:
                reason = "exact_card_needs_descriptor_approval"
            else:
                reason = "no_exact_amount_date_direction_card"
            result.append(dict(event, status=status, transaction_id=None,
                               candidates=[row.get("transaction_id") for row in wrong_amount],
                               reason=reason))
        elif len(free) != 1 or competing:
            result.append(dict(event, status="HOLD_AMBIGUOUS", transaction_id=None,
                               candidates=[row["transaction_id"] for row in options],
                               reason="global_one_to_one_collision"))
        else:
            row = free[0]
            claimed[row["transaction_id"]] = identity
            delta = Decimal(str(row.get("amount_krw") or 0)) - Decimal(str(event.get("amount_krw") or 0))
            has_delta_rule = (_event_amount(event) != _card_amount(row) and
                              _approved_delta_match(event, row, rules))
            trip_delta = (has_delta_rule and str(event.get("provider") or "").casefold() == "trip" and
                          str(event.get("item") or "").casefold() in
                          load_defaults().get("trip_flight_charge_delta", {}).get("item_values", []))
            result.append(dict(event, status="MATCHED_AUTO", transaction_id=row["transaction_id"],
                                candidates=[row["transaction_id"]],
                                reason=("approved_trip_flight_delta" if trip_delta else
                                        "approved_delta_rule" if has_delta_rule else "unique_exact_evidence"),
                                rule_delta_krw=int(delta) if has_delta_rule else None,
                                discount_cause_confirmed=False if trip_delta else None))
    return result


def bind_legacy_portal_links(events, legacy_links):
    """기존에 검증된 포털 연결을 예약·원본·카드·금액 근거로 고정한다.

    입력은 기존 검증 결과에서 추출한 매핑이다. 추측한 결제일은 사용하지 않는다.
    """
    bound = {}
    for old in legacy_links or []:
        if not old.get("verified_exact") or old.get("evidence_kind") != "portal_payment_claim":
            continue
        candidates = [event for event in events if event.get("provider") == "agoda" and
                      event.get("booking_ref") == old.get("booking_ref") and
                      event.get("source_digest") == old.get("source_digest") and
                      event.get("card_last4") == old.get("card_last4") and
                      str(event.get("amount")) == str(old.get("amount")) and
                      event.get("currency") == old.get("currency", "KRW")]
        if len(candidates) == 1:
            bound[candidates[0]["ota_event_id"]] = {
                "transaction_id": old["transaction_id"], "status": "MATCHED_AUTO",
                "legacy_exact": True, "source_digest": old["source_digest"],
                "source_digests": sorted(set(old.get("source_digests") or [old["source_digest"]]))}
    return bound


def _decimal_equal(left, right):
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _valid_iso_day(value):
    try:
        date.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False
