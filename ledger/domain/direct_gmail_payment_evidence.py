"""Sanitized Gmail-derived payment evidence used by the direct classifier.

This snapshot contains only fields derived from the Gmail approval searches
used for the current-card review.  It deliberately omits message ids, body
text, names, addresses, card numbers, and reservation identifiers.  The
snapshot is classification evidence only: it can identify the real merchant
and whether a payment is travel-type, but it never changes the card amount or
creates a one-to-one transaction pairing.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Mapping


CONTRACT = "gmail-payment-evidence-v2-sanitized-composite-snapshot"
SNAPSHOT_DATE = "2026-08-09"

# The values below are a deliberately small, content-addressed derivative of
# the Gmail receipts read during the current run.  Approval-number matches
# are the primary form.  The composite records below additionally require the
# current card source/date/amount and a merchant token; amount-only matches
# are never accepted.  Message ids and body text are intentionally omitted.
EVIDENCE: tuple[dict[str, object], ...] = (
    {
        "approval_number": "30050794", "source_system": "KBD",
        "amount_krw": 562900, "merchant": "큐제주닷컴",
        "product": "쏠라티 15인승 오토 (경)",
        "classification": "travel", "travel_kind": "rental",
        "destination_hint": "제주",
    },
    {
        "approval_number": "02226805", "source_system": "HAN",
        "amount_krw": 16000, "merchant": "주식회사와이드모바일",
        "product": "일본2GB용 와이파이도시락",
        "classification": "travel", "travel_kind": "connectivity",
        "destination_hint": "일본",
    },
    {
        "approval_number": "18228005", "source_system": "HAN",
        "amount_krw": 16500, "email_amount_krw": 165000,
        "amount_match_status": "email_card_amount_mismatch_10x",
        "merchant": "(주)제주속으로", "product": "더 뉴 카니발 11인승",
        "classification": "travel", "travel_kind": "rental",
        "destination_hint": "제주",
    },
    {
        "approval_number": "17228005", "source_system": "HAN",
        "amount_krw": 126390, "merchant": "(주)제주속으로",
        "product": "부분취소 잔여 결제",
        "classification": "travel", "travel_kind": "partial_cancellation",
        "lifecycle": "partial_cancellation", "partial_cancel_amount_krw": 20510,
        "remaining_amount_krw": 126390, "destination_hint": "제주",
    },
    {
        "approval_number": "28224006", "source_system": "HAN",
        "amount_krw": 28800, "merchant": "주식회사와이드모바일",
        "product": "대만 2GB용 와이파이도시락",
        "classification": "travel", "travel_kind": "connectivity",
        "destination_hint": "대만",
    },
    {
        "approval_number": "26224006", "source_system": "HAN",
        "amount_krw": 28800, "merchant": "주식회사와이드모바일",
        "product": "대만 2GB용 와이파이도시락",
        "classification": "travel", "travel_kind": "connectivity",
        "destination_hint": "대만",
    },
    {
        "approval_number": "22329207", "source_system": "HAN",
        "amount_krw": 419875, "merchant": "고투게이트코리아_마이트립",
        "product": "MyTrip 항공권",
        "classification": "travel", "travel_kind": "airfare",
    },
    {
        "approval_number": "24322708", "source_system": "HAN",
        "amount_krw": 138200, "merchant": "주식회사와이드모바일",
        "product": "일본2GB용 와이파이도시락",
        "classification": "travel", "travel_kind": "connectivity",
        "destination_hint": "일본",
    },
    {
        "approval_number": "30058257", "source_system": "KBD",
        "amount_krw": 74900, "merchant": "예스닉",
        "product": "도메인 등록",
        "classification": "overhead", "overhead_kind": "domain",
    },
    {
        "approval_number": "30058426", "source_system": "KBD",
        "amount_krw": 220000, "merchant": "오케이파츠",
        "product": "BMW/I8I12/I15 헤드램프 컨트롤 모듈",
        "classification": "overhead", "overhead_kind": "vehicle_part",
    },
    {
        "approval_number": "30058594", "source_system": "KBD",
        "amount_krw": 169400, "merchant": "피기너스",
        "product": "온라인 강의",
        "classification": "overhead", "overhead_kind": "education",
    },
    {
        "approval_number": "30059150", "source_system": "KBD",
        "amount_krw": 25000, "merchant": "(주)한국국제전시",
        "product": "2026 서울 와인 앤 리쿼 엑스포 입장권",
        "classification": "overhead", "overhead_kind": "event_admission",
    },
    {
        "approval_number": "30059374", "source_system": "KBD",
        "amount_krw": 25000, "merchant": "서부운전면허시험장",
        "product": "운전면허 시험 응시수수료",
        "classification": "overhead", "overhead_kind": "license_exam",
    },
    {
        "approval_number": "30098985", "source_system": "KBD",
        "occurred_on": "2026-04-10", "merchant_tokens": ("NICE",),
        "amount_krw": 205800, "merchant": "TeaFlight.com",
        "product": "고마쓰→후쿠오카 항공권",
        "classification": "travel", "travel_kind": "airfare",
        "target_hint": "0424_알펜루트", "target_status": "schedule_target",
        "service_start": "2026-04-29", "service_end": "2026-04-29",
        "auto_confirmed": True, "single_use": True,
        "legacy_cross_check": "classified_v14:KBD-0771",
        "legacy_transaction_evidence_used": False,
        "evidence_summary": (
            "TeaFlight 주문 334424064533 메일의 고마쓰→후쿠오카 항공과 "
            "카드 승인일·금액·결제대행 가맹점 복합일치"
        ),
    },
    {
        "approval_number": "30059587", "source_system": "KBD",
        "occurred_on": "2026-07-04", "merchant_tokens": ("NICE",),
        "amount_krw": 10000, "merchant": "SOLAPI Limited",
        "product": "알림톡·문자 발송 서비스",
        "classification": "overhead", "overhead_kind": "messaging_service",
        "account": "기타비용", "single_use": True,
        "evidence_summary": (
            "NaverPay 결제메일의 SOLAPI Limited 실제 가맹점·결제일·금액·카드 "
            "복합일치"
        ),
    },
)

# These records are not transaction replacements.  They are a sanitized
# classification hint for current card rows whose approval number is absent
# or whose email is a provider-generated receipt.  ``target_hint`` is only a
# lead from the mail review; the classifier must derive the final target from
# the service period and the canonical schedule.  A hint is never sufficient
# by itself.
COMPOSITE_EVIDENCE: tuple[dict[str, object], ...] = (
    {
        "source_system": "KBD", "occurred_on": "2026-06-14",
        "amount_krw": 499200, "merchant_tokens": ("토스페이",),
        "classification": "travel", "travel_kind": "airfare",
        "target_hint": "0620_묘코", "service_start": "2026-06-20",
        "service_end": "2026-06-25", "target_status": "schedule_hint",
        "evidence_summary": "Trip.com 니가타 왕복 항공 결제메일과 카드 원장 복합일치",
    },
    {
        "source_system": "KBD", "occurred_on": "2026-06-22",
        "amount_krw": 356700, "merchant_tokens": ("토스페이",),
        "classification": "travel", "travel_kind": "airfare",
        "target_hint": "1015_오제", "service_start": "2026-10-14",
        "service_end": "2026-10-21", "target_status": "schedule_hint",
        "evidence_summary": "Trip.com 니가타 왕복 항공 결제메일과 카드 원장 복합일치",
    },
    {
        "source_system": "CORP", "occurred_on": "2026-03-07",
        "amount_krw": 395600, "merchant_tokens": ("나이스정보통신",),
        "classification": "travel", "travel_kind": "airfare",
        "target_hint": "0307_시즈오카", "service_start": "2026-03-07",
        "service_end": "2026-03-07", "target_status": "inferred_service_label",
        "evidence_summary": "Trip.com 후쿠오카→시즈오카 항공 결제메일과 카드 원장 복합일치",
    },
    {
        "source_system": "CORP", "occurred_on": "2026-04-20",
        "amount_krw": 356418, "merchant_tokens": ("나이스정보통신",),
        "transaction_type": "cancellation", "classification": "travel",
        "travel_kind": "lodging_cancellation", "target_hint": "0424_알펜루트",
        "service_start": "2026-04-25", "service_end": "2026-04-26",
        "target_status": "schedule_target",
        "evidence_summary": "나카무라칸 예약·무료취소 메일과 기업카드 취소 원장 복합일치",
    },
)

# This is a same-approval family, not a one-to-one payment match.  The
# 2025-08-12 rental receipt identifies the KASINA approval family; the later
# 107,398원 row is therefore assigned only a temporary service label and is
# not claimed to be the same amount as the receipt.
APPROVAL_FAMILY_EVIDENCE: tuple[dict[str, object], ...] = (
    {
        "approval_number": "00122440", "source_system": "HAN",
        "card4": "6741", "merchant_tokens": ("KASINARENTA CAR",),
        "classification": "travel", "travel_kind": "rental_family",
        "target_hint": "0812_말레이시아", "service_start": "2025-08-12",
        "service_end": "2025-08-12", "target_status": "inferred_service_label",
        "evidence_summary": "KASINA 렌터카 승인번호 계열과 8/12 말레이시아 예약메일",
    },
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


SNAPSHOT_SHA256 = hashlib.sha256(_canonical({
    "contract": CONTRACT,
    "snapshot_date": SNAPSHOT_DATE,
    "records": EVIDENCE,
    "composite_records": COMPOSITE_EVIDENCE,
    "approval_family_records": APPROVAL_FAMILY_EVIDENCE,
})).hexdigest()


def _approval(value: object) -> str:
    return "".join(re.findall(r"\d", str(value or "")))


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    return re.sub(r"[^0-9A-Z가-힣]+", "", text)


_BY_APPROVAL = {
    str(row["approval_number"]): dict(row) for row in EVIDENCE
}


def _base_result(item: Mapping[str, object], *, match_method: str) -> dict[str, object]:
    return {
        "contract": CONTRACT,
        "snapshot_date": SNAPSHOT_DATE,
        "snapshot_sha256": SNAPSHOT_SHA256,
        "source_digest": SNAPSHOT_SHA256,
        "evidence_kind": "gmail_payment_snapshot",
        "authority_status": "verified_external",
        "match_method": match_method,
        **dict(item),
    }


def evidence_for_row(row: Mapping[str, object]) -> dict[str, object] | None:
    """Return evidence only for an auditable current-row composite match."""
    item = _BY_APPROVAL.get(
        _approval(row.get("approval_number") or row.get("approval") or row.get("appr"))
    )
    if item is not None and str(item["source_system"]) == str(row.get("source") or ""):
        if int(item["amount_krw"]) == abs(int(row.get("amount_krw") or 0)):
            occurred_on = str(row.get("occurred_on") or row.get("use") or "")
            expected_on = str(item.get("occurred_on") or "")
            merchant_text = _norm(
                f"{row.get('merchant') or ''} {row.get('biz') or ''}"
            )
            merchant_tokens = item.get("merchant_tokens", ())
            if expected_on and expected_on != occurred_on:
                return None
            if merchant_tokens and not all(
                _norm(token) in merchant_text for token in merchant_tokens
            ):
                return None
            return _base_result(
                item,
                match_method=(
                    "exact_approval_source_date_amount_merchant_token"
                    if expected_on or merchant_tokens
                    else "exact_approval_source_amount"
                ),
            )
        # The 제주속으로 receipt has a documented 10x email/card mismatch.
        if item.get("amount_match_status") == "email_card_amount_mismatch_10x":
            return _base_result(item, match_method="exact_approval_source_documented_10x")

    source = str(row.get("source") or "")
    occurred_on = str(row.get("occurred_on") or row.get("use") or "")
    amount = abs(int(row.get("amount_krw") or 0))
    merchant_text = _norm(
        f"{row.get('merchant') or ''} {row.get('biz') or ''}"
    )
    transaction_type = str(row.get("transaction_type") or "purchase")
    composite_matches = []
    for candidate in COMPOSITE_EVIDENCE:
        if (
            str(candidate.get("source_system") or "") != source
            or str(candidate.get("occurred_on") or "") != occurred_on
            or int(candidate.get("amount_krw") or 0) != amount
            or str(candidate.get("transaction_type") or "purchase") != transaction_type
            or not all(
                _norm(token) in merchant_text
                for token in candidate.get("merchant_tokens", ())
            )
        ):
            continue
        composite_matches.append(candidate)
    if len(composite_matches) == 1:
        return _base_result(
            composite_matches[0],
            match_method="exact_source_date_amount_merchant_token",
        )
    if len(composite_matches) > 1:
        raise ValueError("gmail_payment_evidence_composite_ambiguous")

    family_matches = []
    approval = _approval(
        row.get("approval_number") or row.get("approval") or row.get("appr")
    )
    for candidate in APPROVAL_FAMILY_EVIDENCE:
        if (
            str(candidate.get("approval_number") or "") == approval
            and str(candidate.get("source_system") or "") == source
            and str(candidate.get("card4") or "") == _norm(row.get("card4"))
            and all(
                _norm(token) in merchant_text
                for token in candidate.get("merchant_tokens", ())
            )
        ):
            family_matches.append(candidate)
    if len(family_matches) == 1:
        # A family match proves only that the row is in the same approval
        # family.  It does not prove a singleton transaction or its amount.
        # Keep it visible, but force the classifier to an owner-review path.
        return _base_result(
            family_matches[0],
            match_method="approval_family_source_card_merchant_unverified",
        )
    if len(family_matches) > 1:
        raise ValueError("gmail_payment_evidence_family_ambiguous")
    return None
