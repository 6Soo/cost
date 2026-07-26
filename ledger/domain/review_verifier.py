"""검토 큐의 부재·미매칭 주장을 원천자료로 다시 반증하는 읽기 전용 루프."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable


MANUAL_ABSENCE = re.compile(
    r"(?:수기\s*(?:미기재|장부\s*없음|미입력)|"
    r"미입력(?:추정)?\s*\(\s*수기\s*장부\s*없음\s*\))"
)
MAIL_ABSENCE = re.compile(r"(?:메일|Gmail)\s*(?:없음|미확인)")


PRIOR_PERIOD_CLAIM = re.compile(
    r"(?:Q1|2\s*[~\-]\s*3\s*\uC6D4|\uC804\uAE30|\uB2F9\uBD84\uAE30\s*\uBC16)"
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _integer(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except ValueError:
        return 0


def _date(value: object) -> str:
    text = str(value or "").strip().replace(".", "-").replace("/", "-")
    match = re.fullmatch(r"(\d{2}|\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return text
    year = match[1] if len(match[1]) == 4 else f"20{match[1]}"
    return f"{year}-{int(match[2]):02d}-{int(match[3]):02d}"


def _text(value: object) -> str:
    return re.sub(r"[^0-9A-Z가-힣]", "", str(value or "").upper())


def _issuer(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NONE", "NULL", "N/A"}:
        return ""
    if text in {"HAN", "하나"}:
        return "HAN"
    if text in {"KBD", "KBO", "국민"}:
        return "KB"
    if text in {"CORP", "기업"}:
        return "CORP"
    return text


def _merchant_compatible(left: object, right: object) -> bool:
    a, b = _text(left), _text(right)
    if not a or not b:
        return False
    return a in b or b in a or (len(a) >= 8 and len(b) >= 8 and a[:8] == b[:8])


def _manual_candidates(
    row: dict[str, str], manual_rows: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    amount = abs(_integer(row.get("krw")))
    event_date = _date(row.get("use_date"))
    issuer = _issuer(row.get("src"))
    return [
        manual
        for manual in manual_rows
        if abs(_integer(manual.get("amount"))) == amount
        and _date(manual.get("date")) == event_date
        and _issuer(manual.get("card")) == issuer
        and _merchant_compatible(row.get("merchant"), manual.get("item"))
    ]


def _manual_year_conflicts(
    row: dict[str, str], manual_rows: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    """Find otherwise exact manual rows whose two/four-digit year is wrong."""
    event_date = _date(row.get("use_date"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        return []
    amount = abs(_integer(row.get("krw")))
    event_amount = _integer(row.get("krw"))
    issuer = _issuer(row.get("src"))
    return [
        manual
        for manual in manual_rows
        if abs(_integer(manual.get("amount"))) == amount
        and _integer(manual.get("amount"))
        and (_integer(manual.get("amount")) < 0) == (event_amount < 0)
        and _issuer(manual.get("card")) == issuer
        and _merchant_compatible(row.get("merchant"), manual.get("item"))
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", _date(manual.get("date")))
        and _date(manual.get("date"))[5:] == event_date[5:]
        and _date(manual.get("date"))[:4] != event_date[:4]
    ]


def _manual_incomplete_date_matches(
    row: dict[str, str], manual_rows: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    """Expose identifier matches whose manual date lacks a day, without guessing it."""
    event_date = _date(row.get("use_date"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        return []
    event_amount = _integer(row.get("krw"))
    amount = abs(event_amount)
    issuer = _issuer(row.get("src"))
    result: list[dict[str, str]] = []
    for manual in manual_rows:
        raw_date = str(manual.get("date") or "").strip().replace(".", "-").replace("/", "-")
        match = re.fullmatch(r"(\d{2}|\d{4})-(\d{1,2})", raw_date)
        if not match:
            continue
        year = match[1] if len(match[1]) == 4 else f"20{match[1]}"
        if (
            abs(_integer(manual.get("amount"))) == amount
            and _integer(manual.get("amount"))
            and (_integer(manual.get("amount")) < 0) == (event_amount < 0)
            and _issuer(manual.get("card")) == issuer
            and _merchant_compatible(row.get("merchant"), manual.get("item"))
            and f"{year}-{int(match[2]):02d}" == event_date[:7]
        ):
            result.append(manual)
    return result


def _canonical_duplicates(
    row: dict[str, str], classified: Iterable[dict[str, str]]
) -> list[dict[str, str]]:
    approval = re.sub(r"\D", "", str(row.get("appr") or ""))
    result = []
    for other in classified:
        if str(other.get("uid", "")).startswith("MISC-"):
            continue
        if _issuer(other.get("src")) != _issuer(row.get("src")):
            continue
        other_approval = re.sub(r"\D", "", str(other.get("appr") or ""))
        # 하나카드 원천에는 같은 승인번호로 금액·일자가 다른 생명주기 행이 실제로
        # 존재한다. 승인번호만 같다는 이유로 중복이라고 단정하지 않는다.
        same_approval = bool(
            approval
            and other_approval
            and approval == other_approval
            and _date(other.get("use_date")) == _date(row.get("use_date"))
            and _integer(other.get("krw")) == _integer(row.get("krw"))
        )
        same_structure = (
            _date(other.get("use_date")) == _date(row.get("use_date"))
            and _integer(other.get("krw")) == _integer(row.get("krw"))
            and _merchant_compatible(other.get("merchant"), row.get("merchant"))
        )
        if same_approval or same_structure:
            result.append(other)
    return result


def _ota_records(path: Path) -> list[dict[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("records", raw) if isinstance(raw, dict) else raw
    return list(records)


def _ota_value(record: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _ota_bool(record: dict[str, object], *keys: str) -> bool:
    value = _ota_value(record, *keys)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _manual_representation_groups(
    manual_rows: Iterable[dict[str, str]],
) -> list[list[dict[str, str]]]:
    groups: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    for row in manual_rows:
        key = (
            _date(row.get("date")),
            _integer(row.get("amount")),
        )
        if key[0] and key[1]:
            groups[key].append(row)
    duplicates: list[list[dict[str, str]]] = []
    for rows in groups.values():
        stated_cards = {
            _issuer(row.get("card"))
            for row in rows
            if _issuer(row.get("card"))
        }
        if len(stated_cards) > 1:
            continue
        generic = [
            row
            for row in rows
            if re.search(
                r"(?:TOSSPAY|NAVERPAY|KAKAOPAY|PAYCO|"
                r"\uD1A0\uC2A4|\uB124\uC774\uBC84\uD398\uC774|"
                r"\uCE74\uCE74\uC624\uD398\uC774)",
                f"{row.get('item', '')} {row.get('desc', '')}",
                re.I,
            )
            and "\uAE30\uD0C0" in str(row.get("tab") or "")
        ]
        detailed = [
            row
            for row in rows
            if re.search(
                r"(?:TRIP|\uD2B8\uB9BD|\uD56D\uACF5|\uC219\uBC15)",
                f"{row.get('item', '')} {row.get('desc', '')}",
                re.I,
            )
            and (
                "\uAE30\uD0C0" not in str(row.get("tab") or "")
                or bool(str(row.get("book") or "").strip())
            )
        ]
        if generic and detailed:
            duplicates.append(generic + detailed)
    return duplicates


def verify_review_claims(
    classified_path: Path,
    manual_path: Path,
    ota_path: Path,
) -> dict[str, object]:
    """산출 직전 실행하며 모순이 있으면 마감 가능한 결과로 취급하지 않는다.

    금액·날짜·카드·가맹점이 모두 맞는 수기행은 '수기 없음'을 반증한다.
    중복 MISC는 승인번호 또는 구조키가 같은 정본 행으로 반증한다. 애매한 후보는
    자동 귀속하지 않고 증거만 제시한다.
    """
    classified = _rows(classified_path)
    manual = _rows(manual_path)
    assertions: list[dict[str, object]] = []
    unique_receipt_refs: dict[str, list[dict[str, str]]] = defaultdict(list)
    approval_event_refs: dict[tuple[object, ...], list[dict[str, str]]] = defaultdict(list)
    positive_approvals: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)

    for row in classified:
        approval = re.sub(r"\D", "", str(row.get("appr") or ""))
        if approval and _integer(row.get("krw")) > 0:
            positive_approvals[(_issuer(row.get("src")), approval)].append(row)

    for row in classified:
        uid = str(row.get("uid") or "")
        note = str(row.get("note") or "")
        approval = re.sub(r"\D", "", str(row.get("appr") or ""))
        amount = _integer(row.get("krw"))
        if approval and amount:
            approval_event_refs[
                (
                    _issuer(row.get("src")),
                    approval,
                    _date(row.get("use_date")),
                    amount,
                )
            ].append(row)
        original_approval = re.sub(
            r"\D", "", str(row.get("orig_appr") or row.get("original_approval") or "")
        )
        if amount < 0 and original_approval and PRIOR_PERIOD_CLAIM.search(note):
            originals = positive_approvals.get(
                (_issuer(row.get("src")), original_approval), []
            )
            if originals:
                assertions.append(
                    {
                        "type": "outside_window_claim_contradicted",
                        "uid": uid,
                        "claim": note,
                        "source_evidence": [
                            {
                                "uid": original.get("uid"),
                                "approval": original.get("appr"),
                                "date": _date(original.get("use_date")),
                                "amount": _integer(original.get("krw")),
                            }
                            for original in originals
                        ],
                    }
                )
        for receipt_ref in re.findall(
            r"naverpay/[^|]{0,100}?/예약\s*([0-9A-Z-]{10,})",
            note,
            re.I,
        ):
            unique_receipt_refs[receipt_ref].append(row)
        if re.search(r"Gmail확정[^|]{0,120}메일\s*없음", note, re.I) or re.search(
            r"메일\s*없음[^|]{0,120}메일확정", note, re.I
        ):
            assertions.append(
                {
                    "type": "self_contradictory_mail_claim",
                    "uid": uid,
                    "claim": note,
                    "source_evidence": {
                        "reason": "'Gmail확정'과 '메일 없음'을 동시에 근거로 기록함",
                        "required": "검색 계정·검색식·검색시각 또는 실제 message_id",
                    },
                }
            )
        manual_matches = _manual_candidates(row, manual)
        year_conflicts = _manual_year_conflicts(row, manual)
        if year_conflicts:
            assertions.append(
                {
                    "type": "manual_year_conflict",
                    "uid": uid,
                    "claim": "manual ledger year conflicts with the exact card event",
                    "source_evidence": [
                        {
                            "tab": item.get("tab"),
                            "row": item.get("row"),
                            "manual_date": _date(item.get("date")),
                            "card_date": _date(row.get("use_date")),
                            "amount": amount,
                        }
                        for item in year_conflicts
                    ],
                }
            )
        sign_conflicts = [
            item
            for item in manual_matches
            if _integer(item.get("amount"))
            and (_integer(item.get("amount")) < 0) != (amount < 0)
        ]
        if sign_conflicts:
            assertions.append(
                {
                    "type": "manual_sign_conflict",
                    "uid": uid,
                    "claim": "manual ledger sign conflicts with card event sign",
                    "source_evidence": [
                        {
                            "tab": item.get("tab"),
                            "row": item.get("row"),
                            "manual_amount": _integer(item.get("amount")),
                            "card_amount": amount,
                        }
                        for item in sign_conflicts
                    ],
                }
            )
        incomplete_dates = _manual_incomplete_date_matches(row, manual)
        if incomplete_dates:
            assertions.append(
                {
                    "type": "manual_date_incomplete",
                    "uid": uid,
                    "claim": "manual ledger date lacks the day for an otherwise exact card event",
                    "source_evidence": [
                        {
                            "tab": item.get("tab"),
                            "row": item.get("row"),
                            "manual_date": item.get("date"),
                            "card_date": _date(row.get("use_date")),
                            "manual_amount": _integer(item.get("amount")),
                            "card_amount": amount,
                        }
                        for item in incomplete_dates
                    ],
                }
            )
        if manual_matches and (MANUAL_ABSENCE.search(note) or uid.startswith("MISC-")):
            assertions.append(
                {
                    "type": "manual_absence_claim_contradicted",
                    "uid": uid,
                    "claim": note,
                    "source_evidence": [
                        {
                            "tab": item.get("tab"),
                            "row": item.get("row"),
                            "date": item.get("date"),
                            "item": item.get("item"),
                            "amount": _integer(item.get("amount")),
                        }
                        for item in manual_matches
                    ],
                }
            )
        if uid.startswith("MISC-"):
            duplicates = _canonical_duplicates(row, classified)
            if duplicates:
                assertions.append(
                    {
                        "type": "unsupported_canonical_card_event",
                        "uid": uid,
                        "claim": "별도 미배정 카드 이벤트",
                        "source_evidence": [
                            {
                                "canonical_uid": item.get("uid"),
                                "approval": item.get("appr"),
                                "amount": _integer(item.get("krw")),
                            }
                            for item in duplicates
                        ],
                    }
                )

    for receipt_ref, rows in unique_receipt_refs.items():
        merchants = [str(row.get("merchant") or "") for row in rows]
        incompatible = any(
            not _merchant_compatible(left, right)
            for index, left in enumerate(merchants)
            for right in merchants[index + 1 :]
        )
        if len(rows) > 1 and incompatible:
            assertions.append(
                {
                    "type": "reused_unique_receipt_identifier",
                    "uid": ",".join(str(row.get("uid") or "") for row in rows),
                    "claim": f"NaverPay receipt {receipt_ref} reused across merchants",
                    "source_evidence": [
                        {
                            "uid": row.get("uid"),
                            "merchant": row.get("merchant"),
                            "amount": _integer(row.get("krw")),
                        }
                        for row in rows
                    ],
                }
            )

    for event_key, rows in approval_event_refs.items():
        if len(rows) > 1:
            assertions.append(
                {
                    "type": "duplicate_card_event_projection",
                    "uid": ",".join(str(row.get("uid") or "") for row in rows),
                    "claim": "same approval/date/signed amount projected more than once",
                    "source_evidence": {
                        "event_key": event_key,
                        "rows": [row.get("uid") for row in rows],
                    },
                }
            )

    for rows in _manual_representation_groups(manual):
        assertions.append(
            {
                "type": "duplicate_manual_event_representation",
                "uid": ",".join(
                    f"{row.get('tab')}:{row.get('row')}" for row in rows
                ),
                "claim": (
                    "generic PG row and travel-detail row represent one card event"
                ),
                "source_evidence": [
                    {
                        "tab": row.get("tab"),
                        "row": row.get("row"),
                        "date": row.get("date"),
                        "item": row.get("item"),
                        "amount": _integer(row.get("amount")),
                        "relation": (
                            "same_as_event"
                            if "\uAE30\uD0C0" in str(row.get("tab") or "")
                            else "primary_travel_detail"
                        ),
                    }
                    for row in rows
                ],
            }
        )

    ota = _ota_records(ota_path)
    for record in ota:
        subject = str(record.get("subject") or "")
        provider = str(record.get("provider") or "").lower()
        booking_refs = _ota_value(
            record, "bookingRefs", "booking_numbers", "booking_number", "order_id"
        ) or []
        amounts = _ota_value(
            record,
            "amountCandidates",
            "amount_candidates",
            "amounts",
            "booking_display_amounts",
            "booking_display_amount",
        ) or []
        travel_dates = _ota_value(
            record,
            "travelDates",
            "travel_dates",
            "service_start_on",
            "period_original",
        ) or []
        expects_booking_ref = provider in {
            "trip",
            "booking",
            "skyticket",
        } and bool(
            re.search(
                r"(?:예약(?:을|이|은)?\s*(?:확정|정보)|결제\s*완료|인보이스|"
                r"취소됨|무료로\s*취소|항공권\s*(?:예약|환불)|영수증|"
                r"구입\s*완료|신청\s*완료|신청번호)",
                subject,
                re.I,
            )
        )
        transactional = bool(
            re.search(
                r"(?:결제\s*(?:완료|금액)|영수증|전자\s*영수증|receipt|"
                r"신청\s*(?:완료|확인)|구입\s*완료|"
                r"payment\s*(?:confirmed|receipt))",
                subject,
                re.I,
            )
        )
        expects_amount = transactional and provider in {
            "trip",
            "booking",
            "mytrip",
            "skyticket",
        }
        booking_date_document = bool(
            re.search(
                r"(?:예약.{0,20}(?:확정|취소)|"
                r"예약.{0,20}완료|영수증|receipt)",
                subject,
                re.I,
            )
        ) and not bool(
            re.search(
                r"(?:프로모션|혜택|추천|광고|업데이트|소식|여행\s*아이디어)",
                subject,
                re.I,
            )
        )
        expects_travel_dates = (
            provider == "booking" and booking_date_document
        ) or (provider == "skyticket" and transactional)
        missing = [
            name
            for name, value in (
                ("bookingRefs", booking_refs),
                ("amounts", amounts),
                ("travelDates", travel_dates),
            )
            if not value and (
                name == "bookingRefs" and expects_booking_ref
                or name == "amounts" and expects_amount
                or name == "travelDates" and expects_travel_dates
            )
        ]
        if (
            re.search(r"\b\d{4}-\d{3}-\d{3}(?:\s*\(\d+\))?", subject)
            and not booking_refs
        ) and "bookingRefs" not in missing:
            missing.insert(0, "bookingRefs")
        if missing:
            assertions.append(
                {
                    "type": "ota_field_loss",
                    "uid": str(
                        _ota_value(record, "messageId", "message_id") or ""
                    ),
                    "claim": "구조화 OTA 인덱스의 핵심 필드가 비어 있음",
                    "source_evidence": {
                        "provider": record.get("provider"),
                        "subject": subject,
                        "missing": missing,
                        "loss_types": [
                            {
                                "bookingRefs": "ota_booking_ref_loss",
                                "amounts": "ota_amount_loss",
                                "travelDates": "ota_travel_date_loss",
                            }[name]
                            for name in missing
                        ],
                    },
                }
            )

        extraction_sources = _ota_value(
            record, "extractionSources", "extraction_sources"
        ) or []
        if not isinstance(extraction_sources, (list, tuple, set)):
            extraction_sources = [extraction_sources]
        forwarded_prefix = bool(
            re.match(r"^\s*(?:RE\s*:\s*)?(?:FW|FWD|전달)\s*:", subject, re.I)
        )
        forwarded_candidate = (
            _ota_bool(record, "forwardedContentDetected", "forwarded_content_detected")
            or (
                forwarded_prefix
                and provider in {"trip", "booking", "mytrip", "skyticket"}
                and bool(
                    re.search(
                        r"(?:예약|항공|숙박|영수증|receipt|결제|구입|신청)",
                        subject,
                        re.I,
                    )
                )
            )
        )
        forwarded_extracted = (
            _ota_bool(
                record,
                "forwardedContentExtracted",
                "forwarded_content_extracted",
            )
            or "forwarded_message" in extraction_sources
        )
        if forwarded_candidate and not forwarded_extracted:
            assertions.append(
                {
                    "type": "forwarded_unextracted",
                    "uid": str(
                        _ota_value(record, "messageId", "message_id") or ""
                    ),
                    "claim": "전달된 OTA 원문을 추출했다는 증거가 없음",
                    "source_evidence": {
                        "provider": record.get("provider"),
                        "subject": subject,
                        "forwarded_content_detected": True,
                        "forwarded_content_extracted": False,
                    },
                }
            )

        attachment_state = str(
            _ota_value(record, "attachmentState", "attachment_state") or ""
        ).lower()
        attachment_count = _integer(
            _ota_value(record, "attachmentCount", "attachment_count")
        )
        if not attachment_state and (
            attachment_count > 0
            or _ota_bool(
                record,
                "hasAttachments",
                "hasAttachment",
                "has_attachment",
            )
        ):
            attachment_state = "present_unread"
        attachment_extracted = (
            attachment_state == "text_extracted"
            or "attachment_text" in extraction_sources
        )
        receipt_attachment = _ota_bool(
            record,
            "attachmentReceiptDetected",
            "attachment_receipt_detected",
        )
        unresolved_attachment = attachment_state in {
            "present_unread",
            "unsupported",
            "read_error",
        }
        if (
            unresolved_attachment
            and not attachment_extracted
            and (receipt_attachment or transactional)
        ):
            assertions.append(
                {
                    "type": "attachment_required",
                    "uid": str(
                        _ota_value(record, "messageId", "message_id") or ""
                    ),
                    "claim": "거래성 OTA 첨부 영수증이 아직 추출되지 않음",
                    "source_evidence": {
                        "provider": record.get("provider"),
                        "subject": subject,
                        "attachment_state": attachment_state,
                        "attachment_count": attachment_count,
                        "attachment_receipt_detected": receipt_attachment,
                    },
                }
            )

    counts: dict[str, int] = defaultdict(int)
    for assertion in assertions:
        counts[str(assertion["type"])] += 1
        if assertion["type"] == "ota_field_loss":
            evidence = assertion.get("source_evidence") or {}
            for loss_type in evidence.get("loss_types") or []:
                counts[str(loss_type)] += 1
    return {
        "format_version": 1,
        "passed": not assertions,
        "assertion_count": len(assertions),
        "counts": dict(sorted(counts.items())),
        "assertions": assertions,
        "source_rows": {
            "classified": len(classified),
            "manual": len(manual),
            "ota": len(ota),
        },
    }
