"""OTA 결제 근거를 카드 거래와 분리해 정규화하고 대조한다."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app import ota_mail, ota_portal


_NO_ALLOCATION_SNAPSHOT = object()


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


def _mail_events(directories):
    try:
        messages, inventory = ota_mail.load_messages_from(directories)
    except Exception as exc:
        raise OtaSourcesError([{"kind":"mail_loader", "error":type(exc).__name__}]) from exc
    failures = [entry for entry in inventory if entry.get("error")]
    if failures:
        raise OtaSourcesError(failures)
    events = {}
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
            "source_binding_ids": sorted(set(fact.get("source_binding_ids") or [])),
        }
        if not event["card_last4"] and card_match:
            event["card_last4"] = card_match.group(1)
        event["ota_event_id"] = _event_id(event["identity_source_ids"])
        events[event["ota_event_id"]] = event
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
            exists = path.is_dir() if kind == "mail_directory" else path.is_file()
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
            if left["payment_id"] != right["payment_id"]:
                return False
            return not _event_semantic_conflict(left, right)
        left_bindings = set(left.get("source_binding_ids") or [])
        right_bindings = set(right.get("source_binding_ids") or [])
        if left_bindings.intersection(right.get("source_ids") or []) or right_bindings.intersection(left.get("source_ids") or []):
            return not _event_semantic_conflict(left, right)
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
        merged.append(_combine_evidence(group))
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


def _descriptor_matches(event, row):
    merchant = str(row.get("merchant_normalized") or row.get("merchant") or "").casefold()
    provider = str(event.get("provider") or "").casefold()
    names = {"agoda": ("agoda", "아고다"), "trip": ("trip.com", "트립"),
             "klook": ("klook", "클룩"), "booking": ("booking.com", "booking")}
    return bool(merchant and any(name in merchant for name in names.get(provider, (provider,))))


def _rule_scope_valid(conditions):
    if not isinstance(conditions, dict):
        return False
    allowed = {"provider", "item", "merchant_normalized", "issuer", "card_last4",
               "date_lag_days", "amount_delta_krw"}
    if not set(conditions) <= allowed:
        return False
    if not conditions.get("provider") or not conditions.get("item"):
        return False
    if not (conditions.get("merchant_normalized") or
            (conditions.get("issuer") and conditions.get("card_last4"))):
        return False
    lag = conditions.get("date_lag_days", 0)
    delta = conditions.get("amount_delta_krw", 0)
    return (isinstance(lag, int) and 0 <= lag <= 7 and isinstance(delta, int)
            and -10000 <= delta <= 10000)


def _rule_matches(event, row, rules):
    for rule in rules:
        status = str(rule.get("status") or "").lower()
        if ("active" in rule and not bool(rule.get("active"))) or status in ("inactive", "revoked"):
            continue
        if not (rule.get("approved_by") or rule.get("user_confirmation") or
                rule.get("approved") is True):
            continue
        allowed = {"provider", "item", "merchant_normalized", "issuer", "card_last4",
                   "date_lag_days", "amount_delta_krw"}
        conditions = rule.get("conditions")
        if conditions is None:
            conditions = {key:value for key, value in rule.items() if key in allowed}
        if not _rule_scope_valid(conditions):
            continue
        if conditions.get("provider") != event.get("provider") or conditions.get("item") != event.get("item"):
            continue
        if conditions.get("merchant_normalized") and conditions["merchant_normalized"] != row.get("merchant_normalized"):
            continue
        if conditions.get("issuer") and conditions["issuer"] != row.get("issuer"):
            continue
        if conditions.get("card_last4") and not str(row.get("card_tail") or "").endswith(str(conditions["card_last4"])):
            continue
        return True
    return False


def _approved_delta_match(event, row, rules):
    if str(event.get("currency") or "").upper() != "KRW" or event.get("amount_krw") is None:
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
    return False


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
        expected = abs(Decimal(str(event.get("amount"))))
        signed_card_amount = Decimal(str(row.get("foreign_amount")))
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
        lag = abs((date.fromisoformat(row["approval_date"]) - date.fromisoformat(event["paid_on"])).days)
    except (TypeError, ValueError):
        return False
    return any(int(rule.get("conditions", rule).get("date_lag_days", 0)) > 0 and
               lag <= int(rule.get("conditions", rule).get("date_lag_days", 0)) and
               _rule_matches(event, row, [rule]) for rule in rules)


def _has_corroborator(event, row, rules):
    hint = str(event.get("card_last4") or "")
    card = str(row.get("card_tail") or row.get("card_last4") or "")
    if hint and card.endswith(hint):
        return True
    if event.get("payment_id") and event["payment_id"] == row.get("ota_payment_id"):
        return True
    return _descriptor_matches(event, row) or _rule_matches(event, row, rules)


def _eligible_cards(event, transactions, links=None, rules=None):
    if not event.get("paid_on"):
        return []
    expected_direction = "refund" if event.get("event_type") == "refund" else "purchase"
    matched = []
    for row in transactions:
        if row.get("duplicate_of") or row.get("parse_error") or row.get("conflict_reason"):
            continue
        if _direction(row) != expected_direction or not _amount_matches(event, row, rules):
            continue
        exact_date = row.get("approval_date") == event.get("paid_on")
        if not exact_date and not _approved_lag_match(event, row, rules or []):
            continue
        last4 = str(event.get("card_last4") or "")
        if last4 and not (str(row.get("card_tail") or row.get("card_last4") or "").endswith(last4)):
            continue
        if not _has_corroborator(event, row, rules or []):
            continue
        copy = dict(row)
        copy["already_linked_event_id"] = (links or {}).get(row.get("transaction_id"))
        matched.append(copy)
    return matched


def same_date_cards(event, transactions, *, links=None):
    """가맹점과 금액에 제한 없이 같은 결제일의 모든 카드 행을 돌려준다."""
    links = links or {}
    linked_by_transaction = {}
    for key, value in links.items():
        if isinstance(value, dict) and value.get("transaction_id"):
            linked_by_transaction[value["transaction_id"]] = key
        elif not isinstance(value, dict):
            linked_by_transaction[key] = value
    rows = []
    for row in transactions:
        if row.get("approval_date") != event.get("paid_on"):
            continue
        copy = dict(row)
        copy["already_linked_event_id"] = linked_by_transaction.get(row.get("transaction_id"))
        rows.append(copy)
    return sorted(rows, key=lambda row: (
        _card_amount(row) is None, _card_amount(row) or Decimal(0), str(row.get("card_tail") or ""),
        str(row.get("merchant_normalized") or row.get("merchant") or ""),
        str(row.get("transaction_id") or "")))


def match_ota_payment_events(events, transactions, *, existing_links=None, rules=None):
    """검증된 OTA 이벤트와 카드 행을 입력 변경 없이 전역 일대일 대조한다."""
    existing_links = existing_links or {}
    rules = rules or []
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
    options_by_event = {
        event.get("ota_event_id"): _eligible_cards(event, transactions, rules=rules)
        for event in events if not existing_links.get(event.get("ota_event_id"))
    }
    for event in events:
        identity = event.get("ota_event_id")
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
        if not event.get("paid_on"):
            result.append(dict(event, status="HOLD_DATE_UNKNOWN", transaction_id=None,
                               candidates=[], reason="payment_date_not_in_source"))
            continue
        options = options_by_event.get(identity, [])
        free = [row for row in options if row["transaction_id"] not in claimed]
        competing = any(other_id != identity and any(
            row["transaction_id"] == options[0]["transaction_id"] for row in other_options)
            for other_id, other_options in options_by_event.items()) if len(options) == 1 else False
        if not options:
            wrong_amount = [row for row in transactions
                            if row.get("approval_date") == event.get("paid_on") and
                            _direction(row) == ("refund" if event.get("event_type") == "refund" else "purchase") and
                            row.get("transaction_id") not in claimed and
                            _has_corroborator(event, row, rules)]
            status = "HOLD_AMOUNT_MISMATCH" if wrong_amount else "HOLD_NO_CARD"
            result.append(dict(event, status=status, transaction_id=None,
                               candidates=[row.get("transaction_id") for row in wrong_amount],
                               reason="amount_differs" if wrong_amount else "no_exact_amount_date_direction_card"))
        elif len(options) != 1 or len(free) != 1 or competing:
            result.append(dict(event, status="HOLD_AMBIGUOUS", transaction_id=None,
                               candidates=[row["transaction_id"] for row in options],
                               reason="global_one_to_one_collision"))
        else:
            row = free[0]
            claimed[row["transaction_id"]] = identity
            result.append(dict(event, status="MATCHED_AUTO", transaction_id=row["transaction_id"],
                               candidates=[row["transaction_id"]], reason="unique_exact_evidence"))
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
