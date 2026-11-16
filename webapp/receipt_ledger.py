"""Financial validation and COST ledger projection for receipt workflow apply."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from .ledger_store import SaveError


PAYMENTS = {"cash", "private_card", "corporate_card"}
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _native(candidate):
    amount = candidate.get("amount")
    currency = candidate.get("currency")
    if type(amount) is not int or amount <= 0:
        raise SaveError("TOTAL_UNCLEAR", "영수증 금액을 확인해 주세요")
    if currency not in ("JPY", "KRW"):
        raise SaveError("CURRENCY_UNKNOWN", "JPY 또는 KRW 통화를 직접 확인해 주세요")
    return amount, currency


def _same_source_receipt(left: dict, right: dict, review) -> bool:
    """Only block a repeat of the same photographed physical region.

    Equal merchant/date/amount values across different photos can be distinct
    purchases, so they are deliberately not a global duplicate key.
    """
    if left.get("image_sha256") != right.get("image_sha256"):
        return False
    if (left.get("source_identity") and right.get("source_identity")
            and left["source_identity"] == right["source_identity"]):
        return True
    left_box = left.get("box")
    right_box = right.get("box")
    if left_box is not None and right_box is not None:
        try:
            from app import receipt_candidates as rc
            return rc._overlap(left_box, right_box) > rc.BOX_OVERLAP_HOLD
        except (TypeError, ValueError):
            return True
    if (left_box is None) != (right_box is None):
        return True
    left_ordinal, right_ordinal = left.get("ordinal"), right.get("ordinal")
    if left_ordinal is not None and right_ordinal is not None:
        return left_ordinal == right_ordinal
    # With incomplete source coordinates and no shared ordinal, identity cannot
    # be disproved safely. Keep ambiguous same-photo reads out of the ledger.
    return True


def _legacy_candidate(row: dict) -> dict:
    amount = row.get("total_original")
    if amount is None:
        amount = row.get("total_jpy")
    return {"image_sha256": row.get("image_sha"), "box": row.get("box"),
            "merchant": row.get("merchant"), "date": row.get("date"),
            "amount": amount, "currency": row.get("currency", "JPY"),
            "ordinal": row.get("source_ordinal")}


def _card_match(store, candidate, cards):
    from . import receipt_review
    amount, currency = _native(candidate)
    probe = {"date": candidate["date"], "merchant": candidate["merchant"],
             "currency": currency, "total_original": amount,
             "total_jpy": amount if currency == "JPY" else None}
    return receipt_review._match_card(cards, probe)


def _card_ledger_row(store, card, *, trips):
    transaction_id = card["transaction_id"]
    columns = {row[1] for row in store.conn.execute("PRAGMA table_info(transactions)")}
    required = {"transaction_id", "approval_date", "posting_date", "merchant", "foreign_amount",
                "foreign_currency", "amount_krw", "transaction_kind", "transaction_direction",
                "duplicate_of", "parse_error", "conflict_reason", "source_hash"}
    if not required <= columns:
        raise SaveError("CARD_SOURCE_UNVERIFIED", "법인카드 원본을 안전하게 확인할 수 없어요")
    transaction = store.conn.execute(
        "SELECT transaction_id,approval_date,posting_date,merchant,foreign_amount,foreign_currency,"
        "amount_krw,transaction_kind,transaction_direction,duplicate_of,parse_error,conflict_reason,source_hash"
        " FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
    if (transaction is None or transaction[7] != "purchase" or transaction[8] != "purchase"
            or transaction[9] or transaction[10] or transaction[11]
            or (transaction[5] not in ("JPY", "KRW", "", None))):
        raise SaveError("CARD_SOURCE_UNSAFE", "중복·환불·충돌이 없는 법인카드 매입을 확인하지 못했습니다")

    matches = []
    for row in store.conn.execute(
            "SELECT row_id,payload_json FROM board_rows WHERE row_kind='expense'"):
        try:
            payload = json.loads(row[1])
        except (TypeError, ValueError):
            continue
        if (payload.get("source_kind") == "카드"
                and payload.get("source_event_id") == transaction_id):
            matches.append((row[0], payload))
    if len(matches) != 1:
        raise SaveError("CARD_LEDGER_ROW_NOT_FOUND", "연결할 기존 법인카드 비용을 하나로 확인하지 못했습니다")
    ledger_id, payload = matches[0]
    card_date = transaction[1] or transaction[2] or ""
    if (payload.get("occurred_on") != card_date
            or type(payload.get("amount_krw")) is not int
            or payload.get("amount_krw") != transaction[6]
            or payload.get("source_merchant") not in (None, "", transaction[3])
            or payload.get("source_fact_digest") != transaction[12]
            or not isinstance(transaction[12], str) or not _SHA.fullmatch(transaction[12])):
        raise SaveError("CARD_LEDGER_ROW_CONFLICT", "기존 카드 비용과 원본의 날짜·금액·상호가 다릅니다")
    if payload.get("display_tab_id"):
        try:
            from app.closed_period import excluded
            probe = {"approval_date": transaction[1], "posting_date": transaction[2],
                     "display_tab_id": payload.get("display_tab_id"),
                     "trip_id": payload.get("display_tab_id")}
            if excluded(probe, trips, manual=True):
                raise SaveError("CLOSED_PERIOD", "마감된 분기의 카드 비용은 변경할 수 없습니다")
        except ImportError:
            raise SaveError("CLOSED_PERIOD_CHECK_UNAVAILABLE", "마감 분기 보호를 확인할 수 없어요")
    return ledger_id, transaction, payload


def apply(board, *, request_id: str, selections: list[dict], workflow_conn,
          receipts_path, owner_id: str = "owner") -> dict:
    """Apply selected workflow candidates, then reconcile after ledger commit.

    The workflow DB write lock is held by the caller while this function runs.
    LedgerStore commits the financial request independently; its request/source
    records are the recovery authority if the workflow commit is interrupted.
    """
    if board is None:
        raise SaveError("STORE_UNBOUND", "COST 장부를 사용할 수 없습니다")
    if not isinstance(selections, list) or not 1 <= len(selections) <= 50:
        raise SaveError("INVALID_VALUE", "반영할 내역을 선택해 주세요")
    requested = {}
    for item in selections:
        if (not isinstance(item, dict) or set(item) != {"candidate_id", "expected_revision"}
                or not isinstance(item.get("candidate_id"), str)
                or type(item.get("expected_revision")) is not int
                or item["expected_revision"] < 1):
            raise SaveError("INVALID_VALUE", "영수증 선택 정보가 올바르지 않아요")
        if item["candidate_id"] in requested:
            raise SaveError("INVALID_VALUE", "같은 영수증을 두 번 선택했어요")
        requested[item["candidate_id"]] = item["expected_revision"]

    import hashlib as _hashlib
    import json as _json
    from . import receipt_review

    payload_hash = _hashlib.sha256(_json.dumps(
        {"request_id": request_id, "selections": selections}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    chosen = []
    trips = []
    live_trip_map = {}

    def prepare(store):
        nonlocal chosen, trips, live_trip_map
        # Read current trips and cards under LedgerStore's transaction so a
        # concurrent close or card import cannot race financial validation.
        trips = board.list_trips(include_archived=True)
        live_trip_map = {t.get("tab_id"): t for t in trips}
        cards = receipt_review.card_rows(board)
        rows = []
        for candidate_id, expected_revision in requested.items():
            row = workflow_conn.execute(
                "SELECT c.* FROM receipt_workflow_candidates c "
                "JOIN receipt_workflow_batches b USING(batch_id) "
                "WHERE c.candidate_id=? AND b.owner_id=?",
                (candidate_id, owner_id)).fetchone()
            if row is None:
                raise SaveError("CANDIDATE_NOT_FOUND", "영수증 내역을 찾지 못했습니다")
            if row["revision"] != expected_revision:
                raise SaveError("STALE_CANDIDATE", "다른 화면에서 영수증이 바뀌었습니다")
            if not row["selected"]:
                raise SaveError("CANDIDATE_NOT_SELECTED", "반영할 내역을 먼저 선택해 주세요")
            if row["applied"]:
                raise SaveError("CANDIDATE_ALREADY_APPLIED", "이미 COST에 반영한 영수증입니다")
            review = json.loads(row["review_json"])
            model = json.loads(row["model_json"])
            candidate = {**review, "candidate_id": candidate_id,
                         "image_sha256": row["image_sha256"], "box": review.get("box"),
                         "source_identity": row["source_identity"],
                         "source_ordinal": row["source_ordinal"]}
            if not _SHA.fullmatch(candidate["image_sha256"]):
                raise SaveError("IMAGE_SOURCE_INVALID", "영수증 원본 연결을 확인할 수 없어요")
            try:
                receipt_review.image_bytes(receipts_path, candidate["image_sha256"])
            except (OSError, KeyError, receipt_review.ReceiptStoreError):
                raise SaveError("IMAGE_SOURCE_UNAVAILABLE", "영수증 원본을 읽지 못했습니다") from None
            merchant = candidate.get("merchant")
            if not isinstance(merchant, str) or not merchant.strip() or len(merchant.strip()) > 240:
                raise SaveError("FIELD_MISSING", "상호를 확인해 주세요")
            candidate["merchant"] = merchant.strip()
            raw_date = candidate.get("date")
            if (not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date)):
                raise SaveError("DATE_INVALID", "영수증 날짜를 확인해 주세요")
            try:
                date.fromisoformat(raw_date)
            except ValueError:
                raise SaveError("DATE_INVALID", "영수증 날짜를 확인해 주세요") from None
            amount, currency = _native(candidate)
            payment = candidate.get("payment")
            if payment not in PAYMENTS:
                raise SaveError("PAYMENT_UNKNOWN", "결제수단을 확인해 주세요")
            category = candidate.get("category")
            if not isinstance(category, str) or not category.strip() or len(category.strip()) > 120:
                raise SaveError("CATEGORY_REQUIRED", "비용 항목을 확인해 주세요")
            trip_id = candidate.get("trip_id")
            trip = live_trip_map.get(trip_id)
            if (not isinstance(trip_id, str) or trip is None or trip.get("tab_kind", "trip") != "trip"
                    or trip.get("deleted") or trip.get("archived")):
                raise SaveError("TRIP_REQUIRED", "등록할 여행을 선택해 주세요")
            if trip.get("visual_closed"):
                raise SaveError("CLOSED_PERIOD", "마감된 여행에는 새 비용을 반영할 수 없습니다")
            try:
                from app.closed_period import excluded
                if excluded({"approval_date": raw_date, "posting_date": raw_date,
                             "trip_id": trip_id, "display_tab_id": trip_id}, trips, manual=True):
                    raise SaveError("CLOSED_PERIOD", "마감된 분기에는 새 비용을 반영할 수 없습니다")
            except ImportError:
                raise SaveError("CLOSED_PERIOD_CHECK_UNAVAILABLE", "마감 분기 보호를 확인할 수 없어요")
            if payment == "private_card" and candidate.get("company_expense") is not True:
                raise SaveError("COMPANY_EXPENSE_NOT_CONFIRMED", "개인카드 비용은 회사 경비 인정이 필요합니다")

            # Prevent a cash/private-card copy when an identical corporate-card
            # purchase is already in the authoritative source rows.
            matches = _card_match(store, candidate, cards)
            if payment in ("cash", "private_card") and matches:
                raise SaveError("CARD_PAYMENT_CONFLICT", "같은 법인카드 매입이 있어 별도 비용으로 반영할 수 없습니다")

            if payment == "corporate_card":
                if len(matches) != 1:
                    code = "CARD_NOT_FOUND" if not matches else "CARD_MATCH_AMBIGUOUS"
                    raise SaveError(code, "대응하는 법인카드 매입을 하나로 확인해 주세요")
                ledger_id, transaction, ledger_row = _card_ledger_row(store, matches[0], trips=trips)
                item = {"kind": "evidence", "candidate_id": candidate_id,
                        "source_identity": row["source_identity"],
                        "image_sha256": candidate["image_sha256"], "revision": expected_revision,
                        "transaction_id": transaction[0], "ledger_id": ledger_id,
                        "merchant": candidate["merchant"],
                        "source_json": {"image_sha256": candidate["image_sha256"],
                                        "source_identity": row["source_identity"],
                                        "ordinal": row["source_ordinal"],
                                        "box": candidate.get("box"), "model_id": model.get("id"),
                                        "merchant": candidate["merchant"], "date": raw_date,
                        "amount": amount, "currency": currency,
                        "payment": payment, "trip_id": trip_id,
                        "ledger_source_event_id": ledger_row.get("source_event_id"),
                        "ledger_source_sha256": ledger_row.get("source_fact_digest")},
                        "evidence_json": {"receipt_image_sha256": candidate["image_sha256"],
                                          "candidate_id": candidate_id,
                                          "date": raw_date, "merchant": candidate["merchant"],
                                          "amount": amount, "currency": currency}}
            else:
                from app.receipt_candidates import JPY_TO_KRW
                amount_krw = amount if currency == "KRW" else amount * JPY_TO_KRW
                payment_label = "현금" if payment == "cash" else "개인카드"
                description = f"{candidate['merchant']} · {payment_label} · 원금 {amount:,} {currency}"
                if currency == "JPY":
                    description += f" · 환산 {JPY_TO_KRW:,} KRW/JPY = {amount_krw:,} KRW"
                else:
                    description += f" · 원화 {amount_krw:,} KRW"
                fields = {"display_tab_id": trip_id, "occurred_on": raw_date,
                          "amount_krw": amount_krw, "item": category.strip(),
                          "description": description, "evidence_type": "영수증",
                          "pay_method": payment_label,
                          "receipt_payment": payment,
                          "receipt_amount_original": amount,
                          "receipt_currency": currency,
                          "receipt_exchange_rate_krw_per_unit": (
                              JPY_TO_KRW if currency == "JPY" else 1),
                          "memo": ""}
                item = {"kind": "expense", "candidate_id": candidate_id,
                        "source_identity": row["source_identity"],
                        "image_sha256": candidate["image_sha256"], "revision": expected_revision,
                        "merchant": candidate["merchant"], "fields": fields,
                        "source_json": {"image_sha256": candidate["image_sha256"],
                                        "source_identity": row["source_identity"],
                                        "ordinal": row["source_ordinal"],
                                        "box": candidate.get("box"), "model_id": model.get("id"),
                                        "merchant": candidate["merchant"], "date": raw_date,
                                        "amount": amount, "currency": currency,
                                        "payment": payment, "trip_id": trip_id,
                                        "company_expense": candidate.get("company_expense"),
                                        "amount_krw": amount_krw,
                                        "exchange_rate_krw_per_unit": (
                                            JPY_TO_KRW if currency == "JPY" else 1)}}
            current_identity = {"image_sha256": candidate["image_sha256"],
                                "source_identity": row["source_identity"],
                                "ordinal": row["source_ordinal"],
                                "box": candidate.get("box"), "merchant": candidate["merchant"],
                                "date": raw_date, "amount": amount, "currency": currency}
            for prior in chosen:
                if _same_source_receipt(current_identity, prior, receipt_review):
                    raise SaveError("DUPLICATE_SOURCE_RECEIPT", "같은 사진의 같은 영수증이 두 번 선택되었습니다")
            chosen.append(current_identity)
            rows.append(item)

        # Legacy candidate data is read through its safe loader. A corrupt store
        # is a refusal; it is never treated as an empty duplicate index.
        legacy = receipt_review.load(receipts_path)
        for item in rows:
            source = item["source_json"]
            probe = {"image_sha256": item["image_sha256"],
                     "box": source.get("box"), "merchant": source.get("merchant"),
                     "date": source.get("date"), "amount": source.get("amount"),
                     "currency": source.get("currency")}
            for previous in legacy.get("candidates", []):
                if _same_source_receipt(probe, _legacy_candidate(previous), receipt_review):
                    raise SaveError("DUPLICATE_SOURCE_RECEIPT", "이 사진의 영수증은 기존 후보에 이미 있습니다")
            for previous in legacy.get("holds", []):
                held = previous.get("candidate") or {}
                if held and _same_source_receipt(probe, _legacy_candidate(held), receipt_review):
                    raise SaveError("DUPLICATE_SOURCE_RECEIPT", "이 사진의 영수증은 기존 보류 후보에 이미 있습니다")

        for prior in store.conn.execute("SELECT source_json FROM receipt_apply_sources"):
            try:
                existing = json.loads(prior[0])
            except (TypeError, ValueError):
                raise SaveError("RECEIPT_APPLY_STORE_UNAVAILABLE", "기존 영수증 반영 이력을 확인할 수 없어요") from None
            for item in rows:
                probe = {"image_sha256": item["image_sha256"],
                         "source_identity": item["source_json"].get("source_identity"),
                         "ordinal": item["source_json"].get("ordinal"),
                         "box": item["source_json"].get("box"),
                         "merchant": item["source_json"].get("merchant"),
                         "date": item["source_json"].get("date"),
                         "amount": item["source_json"].get("amount"),
                         "currency": item["source_json"].get("currency")}
                old = {"image_sha256": existing.get("image_sha256"),
                       "source_identity": existing.get("source_identity"),
                       "ordinal": existing.get("ordinal"),
                       "box": existing.get("box"), "merchant": existing.get("merchant"),
                       "date": existing.get("date"), "amount": existing.get("amount"),
                       "currency": existing.get("currency")}
                if _same_source_receipt(probe, old, receipt_review):
                    raise SaveError("DUPLICATE_SOURCE_RECEIPT", "같은 사진의 같은 영수증이 이미 반영되었습니다")
        return rows

    try:
        result = board.apply_receipt_batch(request_id=request_id, request_hash=payload_hash,
                                           prepare=prepare, actor="owner")
    except SaveError:
        raise
    return result


def applied_sources(board, candidate_ids: list[str]) -> dict[str, str]:
    if board is None or not candidate_ids:
        return {}
    output = {}
    for start in range(0, len(candidate_ids), 200):
        part = candidate_ids[start:start + 200]
        marks = ",".join("?" for _ in part)
        for candidate_id, ledger_id in board.conn.execute(
                f"SELECT candidate_id,ledger_id FROM receipt_apply_sources WHERE candidate_id IN ({marks})",
                part):
            output[candidate_id] = ledger_id
    return output
