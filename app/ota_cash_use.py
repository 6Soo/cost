"""OTA 예약에서 캐시·포인트로 치른 부분을 비용 행으로 만든다.

규칙 (사용자 확정):
- 카드 결제가 같은 예약에 있을 때만 캐시 사용분을 기장한다. 캐시만 쓴 예약은 보관한다.
- 금액은 자료의 원화 금액을 그대로 쓴다. 자료에 원화 환산이 없을 때만 엔화를 간편환율(100엔 = 1,000원)로 환산한다.
- 장부 날짜와 여행 배정은 이용일(체크인·픽업·출발)로 한다. 이용일이 없을 때만 결제일을 쓴다.
- 취소·환불된 예약은 기장하지 않는다.
"""
import re
from datetime import date

from app.reconciliation import ledger_date_for_booking

JPY_KRW_PER_100 = 1000  # 간편환율: 100엔 = 1,000원 (사용자 확정 2026-10-14)
EVIDENCE_LABEL = {"klook": "클룩 포인트", "agoda": "아고다캐시", "trip": "트립코인"}


def jpy_to_krw(amount):
    return int(amount) * JPY_KRW_PER_100 // 100


def klook_points(text):
    """클룩 예약내역의 포인트 사용액과 카드 결제액. 포인트가 없으면 None."""
    points = re.search(r"클룩 포인트\s*-₩\s*([0-9][0-9,]*)", text)
    paid = re.search(r"결제 금액\s*₩\s*([0-9][0-9,]*)", text)
    if not points or not paid:
        return None
    return {"cash_krw": int(points.group(1).replace(",", "")),
            "card_krw": int(paid.group(1).replace(",", ""))}


def klook_pickup_day(text):
    match = re.search(r"픽업 날짜 및 시간:\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()


def agoda_cash_use(record):
    """포털 상세 기록 한 건의 캐시 차감과 카드 결제. 카드 결제가 없으면 None (보관)."""
    cash = [c for c in record.get("price_components") or [] if c.get("kind") == "agoda_cash"]
    paid = [c for c in record.get("price_components") or [] if c.get("kind") == "paid_today"]
    if not cash or not paid:
        return None
    currency = str(cash[0].get("currency") or "").upper()
    amount = abs(int(float(str(cash[0].get("decimal_text")).replace(",", ""))))
    if currency == "JPY":
        cash_krw = jpy_to_krw(amount)
        basis = "간편환율 100엔=1,000원"
    elif currency == "KRW":
        cash_krw = amount
        basis = "자료 원화 금액"
    else:
        return None
    return {"cash_krw": cash_krw, "basis": basis, "card_last4": record.get("card_last4")}


def cash_expense_rows(uses, *, cancelled_refs=(), card_linked_refs=(), trips=(), review_from=""):
    """기장할 비용 행 목록과 건너뛴 사유.

    uses: [{provider, booking_ref, item, cash_krw, basis, service_start, payment_date}]
    trips: [{tab_id, starts_on, ends_on}] (검증된 여행만)
    card_linked_refs: 카드 결제가 같은 예약에 연결된 (provider, booking_ref) 목록
    """
    rows, skipped = [], []
    linked = {tuple(item) for item in card_linked_refs}
    cancelled = {tuple(item) for item in cancelled_refs}
    for use in uses:
        key = (use["provider"], use["booking_ref"])
        if key in cancelled:
            skipped.append((key, "취소·환불된 예약"))
            continue
        if key not in linked:
            skipped.append((key, "같은 예약의 카드 결제가 없어 보관"))
            continue
        day = ledger_date_for_booking(use.get("service_start"), use.get("payment_date"))
        if not day or (review_from and day < review_from):
            skipped.append((key, "기장 기간 밖이거나 날짜 없음"))
            continue
        trip = next((t for t in trips if t["starts_on"] <= day <= t["ends_on"]), None)
        if trip is None:
            skipped.append((key, "이용일에 맞는 검증된 여행이 없음"))
            continue
        rows.append({
            "display_tab_id": trip["tab_id"],
            "occurred_on": day,
            "amount_krw": int(use["cash_krw"]),
            "item": use["item"],
            "description": f"{use['provider']} {use['booking_ref']} 캐시 사용분",
            "evidence_type": EVIDENCE_LABEL[use["provider"]],
            "reservation_no": use["booking_ref"],
            "service_period": day,
            "memo": f"{use['basis']}; 카드 결제분은 같은 예약번호의 카드 거래",
        })
    return rows, skipped
