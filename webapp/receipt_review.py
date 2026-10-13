"""Receipt candidates: image, optional local Windows OCR, manual edit, confirm and copy.

Routes stay off unless WEBLEDGER_RECEIPTS_STORE names a JSON store. A synthetic or real image is
stored as a file next to the store after a PNG or JPEG signature check. Regions and values are typed
by a person. Explicitly enabled Windows OCR supplies review hints without creating costs.
The /api/receipts/upload route answers 501 when OCR is disabled. Every manual change keeps its history.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import datetime as dt
import functools
import threading
import math
import uuid
from pathlib import Path

from app import receipt_candidates as rc
from app import local_receipt_ocr
from app import opencode_receipt_vision
from app.google_tsv import expense_tsv
from app import receipt_learning
from . import receipt_vision_jobs, ui_icons

ROUTES = ("/receipts", "/api/receipts", "/api/receipts/scan", "/api/receipts/confirm",
          "/api/receipts/edit", "/api/receipts/tsv", "/api/receipts/upload", "/api/receipts/image", "/api/receipts/vision",
          "/api/receipts/vision/rescan", "/api/receipts/vision/new", "/api/receipts/learn", "/api/receipts/learn/status",
          "/api/receipts/group", "/api/receipts/ungroup")
IMAGE_PATH = re.compile(r"^/api/receipts/image/([0-9a-f]{64})$")
VISION_JOB = re.compile(r"^/api/receipts/vision/([0-9a-f]{32})$")
# Matches the board's own request ceiling (5 MB), so a photo is refused at the same size either way.
IMAGE_LIMIT = 5 * 1024 * 1024
PAYMENTS = ("cash", "private_card", "corporate_card")
PAYMENT_LABELS = {"cash": "현금", "private_card": "개인카드", "corporate_card": "법인카드"}
MESSAGES = {
    'IMAGE_SIZE_INVALID': '사진은 비어 있지 않은 5MB 이하 파일이어야 합니다.',
    'IMAGE_TYPE_UNSUPPORTED': 'PNG 또는 JPEG 사진을 선택해 주세요.',
    'IMAGE_CORRUPT': '사진 파일이 손상되었습니다. 원본 사진을 다시 선택해 주세요.',
    'BOX_INVALID': '영역의 시작 좌표보다 끝 좌표가 커야 합니다. 네 좌표를 확인해 주세요.',
    'DATE_INVALID': '날짜를 실제 날짜로 입력해 주세요. 예: 2027-08-03',
    'TOTAL_UNCLEAR': '최종 결제금액을 양의 정수로 입력해 주세요.',
    'FIELD_MISSING': '상호·날짜·지급처·내용의 필수 입력을 확인해 주세요.',
    'LOW_CONFIDENCE': '읽기가 불확실합니다. 원본 사진을 보고 값을 확인해 주세요.',
    'OVERLAP': '영수증 영역이 겹칩니다. 영역을 나누어 다시 입력해 주세요.',
    'CURRENCY_UNKNOWN': '엔화 금액인지 확인해 주세요.',
    'PAYMENT_UNKNOWN': '결제수단을 확인해 주세요.',
    'DUPLICATE_CONTENT': '같은 영수증 후보가 있습니다. 기존 후보를 확인해 주세요.',
    'CARD_NOT_FOUND': '대응하는 법인카드 매입을 찾지 못했습니다.',
    'CARD_MATCH_AMBIGUOUS': '대응하는 카드 매입이 여러 건입니다. 연결을 확인해 주세요.',
    'CARD_PAYMENT_CONFLICT': '같은 날짜·상호·금액의 카드 매입이 있습니다. 결제수단을 확인해 주세요.',
    'CARD_LINKED_NOT_EDITABLE': '카드에 연결된 영수증의 상호·날짜·금액·결제수단은 변경할 수 없습니다.',
    'STALE_CANDIDATE': '다른 화면에서 영수증을 변경했습니다. 입력값을 확인하고 화면을 새로 열어 주세요.',
    'RECEIPT_STORE_UNAVAILABLE': '영수증 저장소를 확인하지 못했습니다. 저장 여부와 복구 사본을 확인한 뒤 다시 시도해 주세요.',
    'Failed to fetch': '연결하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.',
}
_STORE_LOCK = threading.RLock()


class ReceiptStoreError(OSError):
    """A saved receipt file must remain untouched until it can be read or replaced safely."""


def _serialized(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _STORE_LOCK:
            try:
                return function(*args, **kwargs)
            except OSError:
                raise ReceiptStoreError('RECEIPT_STORE_UNAVAILABLE') from None
    return wrapped


def _storage_errors(function):
    @functools.wraps(function)
    def wrapped(handler, *args, **kwargs):
        try:
            return function(handler, *args, **kwargs)
        except ReceiptStoreError:
            handler._send_json({'code': 'RECEIPT_STORE_UNAVAILABLE'}, 503)
            return True
    return wrapped


def _candidate(stored: dict) -> rc.Candidate:
    return rc.Candidate(**{k: v for k, v in stored.items() if k in rc.Candidate.__dataclass_fields__})


def _native_total(stored: dict):
    return stored.get('total_original') if stored.get('currency', 'JPY') == 'KRW' else stored['total_jpy']


def _validate_date(date) -> None:
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("DATE_INVALID")
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise ValueError("DATE_INVALID") from None


def _validate_values(merchant, date, total) -> None:
    if not isinstance(merchant, str) or not merchant.strip():
        raise ValueError("FIELD_MISSING")
    _validate_date(date)
    if type(total) is not int or total <= 0:
        raise ValueError("TOTAL_UNCLEAR")


def enabled() -> bool:
    return bool(os.environ.get("WEBLEDGER_RECEIPTS_STORE"))


def owns_route(path: str) -> bool:
    return path in ROUTES or IMAGE_PATH.match(path) is not None or VISION_JOB.match(path) is not None


def _store_path() -> Path:
    return Path(os.environ["WEBLEDGER_RECEIPTS_STORE"])


def _images_dir(store: Path) -> Path:
    return store.parent / "receipt-images"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"candidates": [], "holds": [], "images": []}
    except (OSError, ValueError):
        raise ReceiptStoreError('RECEIPT_STORE_UNAVAILABLE') from None
    if not isinstance(data, dict) or any(not isinstance(data.get(key), list) for key in ('candidates', 'holds')):
        raise ReceiptStoreError('RECEIPT_STORE_UNAVAILABLE')
    data.setdefault("images", [])
    if not isinstance(data['images'], list):
        raise ReceiptStoreError('RECEIPT_STORE_UNAVAILABLE')
    required = {'identity', 'date', 'merchant', 'total_jpy', 'payment', 'amount_krw', 'history'}
    for candidate in data['candidates']:
        # A field-incomplete reading may lack its currency or total until a person supplies them.
        partial = isinstance(candidate, dict) and candidate.get('hold') in FIELD_HOLDS
        currency = candidate.get('currency', 'JPY') if isinstance(candidate, dict) else None
        total = _native_total(candidate) if isinstance(candidate, dict) and 'total_jpy' in candidate else None
        if (not isinstance(candidate, dict) or not required <= candidate.keys()
                or any(not isinstance(candidate[key], str) for key in ('identity', 'date', 'merchant', 'payment'))
                or (currency not in ('JPY', 'KRW') and not (partial and currency is None))
                or (type(total) is not int and not (partial and total is None))
                or (candidate.get('currency', 'JPY') == 'KRW' and candidate['total_jpy'] is not None)
                or (candidate['amount_krw'] is not None and type(candidate['amount_krw']) is not int)
                or not isinstance(candidate['history'], list)
                or any(candidate.get(key) is not None and not isinstance(candidate[key], str)
                       for key in ('payee', 'category', 'trip_id', 'image_sha', 'hold'))):
            raise ReceiptStoreError('RECEIPT_STORE_UNAVAILABLE')
    for hold in data['holds']:
        if (not isinstance(hold, dict) or not isinstance(hold.get('identity'), str)
                or not isinstance(hold.get('reason'), str)
                or any(hold.get(key) is not None and not isinstance(hold[key], dict) for key in ('candidate', 'region'))
                or (hold.get('image_sha') is not None and not isinstance(hold['image_sha'], str))):
            raise ReceiptStoreError('RECEIPT_STORE_UNAVAILABLE')
    if any(not isinstance(image, str) for image in data['images']):
        raise ReceiptStoreError('RECEIPT_STORE_UNAVAILABLE')
    return data


def _save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def sniff_image(body: bytes) -> str:
    """The media type the bytes really are, checked structurally. Anything else is refused."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        pos, first, ended = 8, True, False
        while pos + 8 <= len(body) and not ended:
            length = int.from_bytes(body[pos:pos + 4], "big")
            kind = body[pos + 4:pos + 8]
            if first and (kind != b"IHDR" or length != 13):
                raise ValueError("IMAGE_CORRUPT")
            first = False
            pos += 12 + length
            ended = kind == b"IEND"
        if not ended or pos != len(body):
            raise ValueError("IMAGE_CORRUPT")
        return "image/png"
    if body.startswith(b"\xff\xd8\xff") and body.rstrip().endswith(b"\xff\xd9"):
        return "image/jpeg"
    raise ValueError("IMAGE_TYPE_UNSUPPORTED")


@_serialized
def store_image(path: Path, body: bytes) -> dict:
    """Keeps a picture the person registered, after a structural check. Nothing is read from its content."""
    if not body or len(body) > IMAGE_LIMIT:
        raise ValueError("IMAGE_SIZE_INVALID")
    media = sniff_image(body)
    sha = hashlib.sha256(body).hexdigest()
    folder = _images_dir(path)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{sha}.bin"
    if target.exists():
        if target.stat().st_size != len(body) or target.read_bytes() != body:
            raise ValueError('IMAGE_CORRUPT')
    else:
        temporary = target.with_suffix('.bin.tmp')
        temporary.write_bytes(body)
        os.replace(temporary, target)
    data = load(path)
    if sha not in data["images"]:
        data["images"].append(sha)
        _save(path, data)
    return {"sha256": sha, "bytes": len(body), "media_type": media}


def image_bytes(path: Path, sha: str) -> bytes:
    data = load(path)
    if sha not in data["images"]:
        raise KeyError("IMAGE_NOT_FOUND")
    body = (_images_dir(path) / f"{sha}.bin").read_bytes()
    if hashlib.sha256(body).hexdigest() != sha:
        raise ValueError('IMAGE_CORRUPT')
    return body


def _box_list(box) -> list | None:
    return None if box is None else list(box)


def _regions(payload: dict) -> list[rc.Region]:
    if not isinstance(payload, dict):
        raise ValueError('INVALID_VALUE')
    raw = payload.get("regions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("REGIONS_REQUIRED")
    for region in raw:
        if not isinstance(region, dict):
            raise ValueError('REGION_INVALID')
        if all(region.get(key) in (None, '') for key in ('merchant', 'date', 'total')):
            raise ValueError('REGION_EMPTY')
        box = region.get('box')
        if box is not None and (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError('BOX_INVALID')
        confidence = region.get('confidence', 1.0)
        if (type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1):
            raise ValueError('CONFIDENCE_INVALID')
    image = str(payload.get("image") or "")
    boxed = any(r.get('box') is not None for r in raw)
    # A photo analysed without positions is identified by the photo alone, so a re-analysis finds the same receipts.
    if image and not boxed:
        page_id = hashlib.sha256(image.encode("utf-8")).hexdigest()
    else:
        # The page fingerprint is the picture and the regions typed on it, so the same entry sent again is one receipt.
        basis = json.dumps({"image": image, "regions": raw}, ensure_ascii=False, sort_keys=True)
        page_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    regions, copies = [], {}
    for r in raw:
        ordinal = 0
        if r.get('box') is None and type(r.get('ordinal')) is int and r['ordinal'] >= 0:
            # A re-analysis passes the copy number it already worked out from the candidates it knows.
            ordinal = r['ordinal']
        elif r.get('box') is None:
            # Identical readings without a position are told apart by their copy number, not by their list order.
            key = reading_key(r)
            ordinal = copies.get(key, 0)
            copies[key] = ordinal + 1
        reading = r['reading'] if isinstance(r.get('reading'), str) and r['reading'] else reading_key(r)
        regions.append(rc.Region(page_id=page_id, box=tuple(r['box']) if r.get('box') is not None else None,
                                 merchant=r.get("merchant"), date=r.get("date"),
                                 currency=r.get("currency", "JPY"), total=r.get("total"), payment=r.get("payment"),
                                 confidence=float(r.get("confidence", 1.0)), ordinal=ordinal, reading=reading))
    return regions


def reading_key(values: dict) -> str:
    return json.dumps([values.get('merchant'), values.get('date'), values.get('total'),
                       values.get('currency', 'JPY'), values.get('payment')], ensure_ascii=False)


def _recognizer(guidance):
    return lambda image_path: opencode_receipt_vision.recognize_with_fallback(image_path, guidance=guidance)


def _known_line(candidate: dict) -> str:
    total = _native_total(candidate)
    return f"{candidate.get('merchant') or '상호 미확인'} | {candidate.get('date') or '날짜 미확인'} | {total} {candidate.get('currency') or '통화 미확인'}"


def vision_new(path: Path, *, image: str, job_id: str) -> dict:
    """The receipts a re-analysis found beyond those already on the page. Known receipts are never offered again."""
    state = receipt_vision_jobs.lookup(job_id)
    if state is None:
        raise KeyError('VISION_JOB_EXPIRED')
    if state['image'] != image or state['status'] != 'done':
        raise ValueError('VISION_JOB_NOT_READY')
    receipts = state['result']['receipts']
    known = {}
    for stored in load(path)['candidates']:
        if stored.get('image_sha') == image and stored.get('reading'):
            known[stored['reading']] = known.get(stored['reading'], 0) + 1
    seen, new = {}, []
    for item in receipts:
        key = reading_key({'merchant': item['merchant'], 'date': item['date'], 'total': item['amount'],
                           'currency': item['currency'], 'payment': item['payment']})
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        if occurrence >= known.get(key, 0):
            new.append({**item, 'reading': key, 'ordinal': occurrence})
    return {'new': new, 'already': len(receipts) - len(new)}


def card_rows(board) -> list[dict]:
    """Corporate-card purchases in the database, the only card evidence a receipt may link to."""
    if board is None:
        return []
    try:
        rows = board.conn.execute(
            "SELECT transaction_id, COALESCE(NULLIF(approval_date,''), posting_date), merchant, foreign_amount, foreign_currency, amount_krw"
            " FROM transactions WHERE transaction_kind='purchase' AND transaction_direction='purchase'"
            " AND duplicate_of IS NULL AND (foreign_currency='JPY' OR foreign_currency='KRW' OR foreign_currency='' OR foreign_currency IS NULL)").fetchall()
    except sqlite3.OperationalError:
        return []  # no card tables yet: there is no card evidence to link to
    return [{"transaction_id": tid, "date": date, "merchant": merchant,
             "original_jpy": amount if currency == 'JPY' else None,
             "original_krw": krw if currency in ('KRW', '', None) else None}
            for tid, date, merchant, amount, currency, krw in rows]


@_serialized
def scan(path: Path, payload: dict, *, board=None) -> dict:
    data = load(path)
    regions = _regions(payload)
    requested_trip = payload.get("trip_id") or None
    if requested_trip is not None and requested_trip not in _trip_ids(board):
        raise ValueError("TRIP_UNKNOWN")
    if payload.get("image") and payload["image"] not in data["images"]:
        raise KeyError("IMAGE_NOT_FOUND")
    for region in regions:
        if region.date is not None:
            _validate_date(region.date)
        if region.confidence >= rc.MIN_CONFIDENCE and region.total is not None and region.merchant and region.date:
            _validate_values(region.merchant, region.date, region.total)
    known = {c["identity"] for c in data["candidates"]}
    # A card link comes from the server's own rows. Any card_rows the client sent are ignored.
    cards = card_rows(board)
    result = rc.build_candidates(regions, cards, known=known)
    by_identity = {rc._identity(region): region for region in regions}
    partial = [h for h in result['holds'] if h['reason'] in FIELD_HOLDS]
    result['holds'] = [h for h in result['holds'] if h['reason'] not in FIELD_HOLDS]
    for hold in partial:
        region = by_identity[hold['identity']]
        if hold['identity'] in known or any(c.identity == hold['identity'] for c in result['candidates']):
            continue
        # An unknown currency is kept unknown: nothing is guessed, and the candidate waits for a person.
        currency = region.currency if region.currency in ('JPY', 'KRW') else None
        result['candidates'].append(rc.Candidate(
            hold['identity'], region.date or '', region.merchant or '', region.total if currency == 'JPY' else None,
            region.payment or '', None, currency=currency, total_original=region.total))
    for hold in result['holds']:
        region = by_identity[hold['identity']]
        hold['region'] = {**region.__dict__, 'box': _box_list(region.box)}
        if payload.get('image'):
            hold['image_sha'] = payload['image']
    duplicates = []
    added = 0
    resolved = set()
    for candidate in result["candidates"]:
        region = next(r for r in regions if rc._identity(r) == candidate.identity)
        stored = {**candidate.__dict__, "history": [], "hold": None, 'box': _box_list(region.box)}
        stored['reading'] = region.reading
        if requested_trip is not None:
            stored['trip_id'] = requested_trip
        _settle(stored, cards)
        if payload.get("image"):
            # Without a position, the candidate identity (photo + reading + copy number) is the source key.
            key = [payload["image"], _box_list(region.box)] if region.box is not None else [payload["image"], candidate.identity]
            source_region = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
            stored["source_region"] = source_region
            stored.update(image_sha=payload['image'], box=_box_list(region.box))
            if any(c.get("source_region") == source_region for c in data["candidates"]):
                duplicates.append({"identity": candidate.identity, "reason": "DUPLICATE_CONTENT", 'candidate': stored})
                continue
        # The same slip photographed twice, or entered twice, is one cost. A second copy waits for a person.
        if any(_same_physical_receipt(c, stored) for c in data["candidates"]):
            duplicates.append({"identity": candidate.identity, "reason": "DUPLICATE_CONTENT", 'candidate': stored})
            continue
        previous_holds = [h for h in data['holds'] if h['identity'] == candidate.identity]
        stored['history'].extend({'resolved_hold': h} for h in previous_holds)
        resolved.add(candidate.identity)
        data["candidates"].append(stored)
        added += 1
    data['holds'] = [h for h in data['holds'] if h['identity'] not in resolved]
    seen = {h["identity"] for h in data["holds"]}
    data["holds"].extend(h for h in result["holds"] + duplicates if h["identity"] not in seen)
    _save(path, data)
    return {"added": added, "holds": result["holds"] + duplicates}


def _match_card(card_rows_list: list, stored: dict) -> list:
    """Server card purchases with the same date, merchant and JPY amount. Client data never reaches here."""
    return [r for r in card_rows_list if rc.matches_card(r, date=stored['date'], merchant=stored['merchant'],
                                                       currency=stored.get('currency', 'JPY'), total=_native_total(stored))]


FIELD_HOLDS = ('FIELD_MISSING', 'TOTAL_UNCLEAR', 'PAYMENT_UNKNOWN', 'CURRENCY_UNKNOWN')


def _missing_reason(stored: dict) -> str | None:
    """Why a candidate cannot be confirmed yet. A partial reading stays a candidate until a person fills the gap."""
    if not (stored.get('merchant') or '').strip() or not stored.get('date'):
        return 'FIELD_MISSING'
    if stored.get('currency', 'JPY') not in ('JPY', 'KRW'):
        return 'CURRENCY_UNKNOWN'
    total = _native_total(stored)
    if total is None or total <= 0:
        return 'TOTAL_UNCLEAR'
    if stored.get('payment') not in PAYMENTS:
        return 'PAYMENT_UNKNOWN'
    return None


def _settle(stored: dict, card_rows_list: list) -> None:
    """Re-derives the card link and the priced amount from the stored fields and the server's card rows."""
    if stored.get('card_transaction_id'):
        stored.setdefault('card_evidence_transaction_id', stored['card_transaction_id'])
    stored["hold"] = None
    missing = _missing_reason(stored)
    if missing:
        stored.update(hold=missing, amount_krw=None, card_transaction_id=None)
        return
    if stored["payment"] == "corporate_card":
        matches = _match_card(card_rows_list, stored)
        stored["card_transaction_id"] = matches[0]["transaction_id"] if len(matches) == 1 else None
        if stored['card_transaction_id']:
            stored.setdefault('card_evidence_transaction_id', stored['card_transaction_id'])
        stored["amount_krw"] = None
        if not matches:
            stored["hold"] = "CARD_NOT_FOUND"
        elif len(matches) > 1:
            stored["hold"] = "CARD_MATCH_AMBIGUOUS"
    else:
        stored["card_transaction_id"] = None
        if _match_card(card_rows_list, stored):
            stored['hold'] = 'CARD_PAYMENT_CONFLICT'
            stored['amount_krw'] = None
        else:
            stored["amount_krw"] = int(_native_total(stored)) * (1 if stored.get('currency') == 'KRW' else rc.JPY_TO_KRW)


def _signature(candidate: dict) -> tuple | None:
    if _missing_reason(candidate) is not None:
        return None
    return (candidate["date"], candidate["merchant"].strip(), candidate.get('currency', 'JPY'), int(_native_total(candidate)))


def _same_physical_receipt(left: dict, right: dict) -> bool:
    """Equal-priced tickets at different positions on one sheet are distinct."""
    if _signature(left) is None or _signature(left) != _signature(right):
        return False
    if (left.get("image_sha") and left.get("image_sha") == right.get("image_sha")
            and left.get("source_region") and right.get("source_region")
            and left["source_region"] != right["source_region"]):
        return False
    return True


def candidate_version(candidate: dict) -> str:
    """Bind a rendered row to its saved values and history, including changes reverted later."""
    return hashlib.sha256(json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def _check_candidate_version(candidate: dict, expected_version: str | None) -> None:
    # Older internal callers remain supported; browser writes always carry the rendered version.
    if expected_version is not None and expected_version != candidate_version(candidate):
        raise ValueError('STALE_CANDIDATE')


def _saved_retry(candidate: dict, expected_version: str | None, operation: str, values: dict, note: str) -> bool:
    history = candidate.get('history') or []
    if not expected_version or not history:
        return False
    latest = history[-1]
    return (latest.get('request_version') == expected_version and latest.get('operation') == operation
            and latest.get('to') == values and latest.get('note') == note)


@_serialized
def edit(path: Path, *, identity: str, changes: dict, note: str = "", valid_trips: set | None = None,
         card_rows_list: list | None = None, expected_version: str | None = None) -> dict:
    """A person corrects what was typed. Card-linked receipts keep the card amount, so they cannot be re-priced."""
    data = load(path)
    for stored in data["candidates"]:
        if stored["identity"] != identity:
            continue
        if _saved_retry(stored, expected_version, 'edit', changes, note):
            return stored
        _check_candidate_version(stored, expected_version)
        total_field = 'total_original' if stored.get('currency') == 'KRW' else 'total_jpy'
        allowed = {"merchant", "date", total_field, "payment", "trip_id"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("FIELD_NOT_EDITABLE")
        _validate_values(changes.get("merchant", stored["merchant"]), changes.get("date", stored["date"]),
                         changes.get(total_field, _native_total(stored)))
        if stored.get('group_id') and any(changes[k] != stored.get(k) for k in changes):
            raise ValueError('GROUPED_CANDIDATE_NOT_EDITABLE')
        before = {k: stored.get(k) for k in changes}
        if "payment" in changes and changes["payment"] not in PAYMENTS:
            raise ValueError("PAYMENT_UNKNOWN")
        if "trip_id" in changes and changes["trip_id"] and changes["trip_id"] not in (valid_trips or set()):
            raise ValueError("TRIP_UNKNOWN")
        if (stored.get('card_transaction_id') or stored.get('card_evidence_transaction_id')) and any(
                key in changes and changes[key] != stored[key]
                for key in ('merchant', 'date', total_field, 'payment')):
            # Unlinking would turn the card purchase plus a cash receipt into two costs. Refused, not guessed.
            raise ValueError("CARD_LINKED_NOT_EDITABLE")
        for key, value in changes.items():
            stored[key] = int(value) if key == total_field else str(value).strip()
        if total_field == 'total_jpy' and 'total_original' in stored:
            stored['total_original'] = stored['total_jpy']
        others = [c for c in data["candidates"] if c["identity"] != identity]
        if any(_same_physical_receipt(c, stored) for c in others):
            raise ValueError("DUPLICATE_CONTENT")
        _settle(stored, card_rows_list or [])
        if any(before[k] != stored.get(k) for k in changes):
            stored["payee"], stored["category"] = None, None
            stored.setdefault("history", []).append({"edit": before, "to": changes, "note": note,
                                                     "operation": "edit", "request_version": expected_version})
        _save(path, data)
        return stored
    raise KeyError("CANDIDATE_NOT_FOUND")


@_serialized
def confirm(path: Path, *, identity: str, payee: str, category: str, note: str = "",
            expected_version: str | None = None) -> dict:
    data = load(path)
    for stored in data["candidates"]:
        if stored["identity"] == identity:
            if _saved_retry(stored, expected_version, 'confirm', {'payee': payee, 'category': category}, note):
                return stored
            _check_candidate_version(stored, expected_version)
            if stored.get('hold') in FIELD_HOLDS:
                raise ValueError(stored['hold'])
            if stored.get('group_id') and (stored.get('payee') != payee.strip()
                    or stored.get('category') != category.strip()):
                raise ValueError('GROUPED_CANDIDATE_NOT_EDITABLE')
            if stored.get('payee') == payee.strip() and stored.get('category') == category.strip():
                return stored
            candidate = _candidate(stored)
            candidate.history = list(stored["history"])
            rc.confirm(candidate, payee=payee, category=category, note=note)
            candidate.history[-1].update(operation='confirm', request_version=expected_version)
            stored.update(payee=candidate.payee, category=candidate.category, history=candidate.history)
            _save(path, data)
            return stored
    raise KeyError("CANDIDATE_NOT_FOUND")


@_serialized
def group(path: Path, *, identities: list, trip_id: str, expected_versions: dict) -> dict:
    """Explicitly group multiple already-confirmed physical slips into one expense."""
    if (not isinstance(identities, list) or len(identities) < 2 or len(identities) > 50
            or not all(isinstance(i, str) for i in identities)
            or len(set(identities)) != len(identities)
            or not isinstance(expected_versions, dict) or not trip_id):
        raise ValueError('GROUP_SELECTION_INVALID')
    data = load(path)
    rows = [c for c in data['candidates'] if c['identity'] in set(identities)]
    if len(rows) != len(identities):
        raise ValueError('CANDIDATE_NOT_FOUND')
    for row in rows:
        _check_candidate_version(row, expected_versions.get(row['identity']))
        if (not expected_versions.get(row['identity']) or row.get('group_id')
                or row.get('trip_id') != trip_id or row.get('hold')
                or row.get('payment') == 'corporate_card'
                or row.get('card_transaction_id') or row.get('card_evidence_transaction_id')
                or not row.get('payee') or not row.get('category') or row.get('amount_krw') is None):
            raise ValueError('GROUP_SELECTION_INVALID')
    for key in ('date', 'merchant', 'currency', 'payment', 'payee', 'category'):
        if len({row.get(key) for row in rows}) != 1:
            raise ValueError('GROUP_MISMATCH')
    identity = hashlib.sha256(json.dumps(sorted(identities)).encode('utf-8')).hexdigest()[:24]
    for row in rows:
        row['group_id'] = identity
        row.setdefault('history', []).append({'operation':'group','group_id':identity,
            'members':sorted(identities)})
    _save(path, data)
    return {'group_id':identity, 'members':len(rows), 'amount_krw':sum(c['amount_krw'] for c in rows)}


@_serialized
def ungroup(path: Path, *, group_id: str) -> dict:
    if not isinstance(group_id, str) or not re.fullmatch(r'[0-9a-f]{24}', group_id):
        raise ValueError('GROUP_INVALID')
    data = load(path)
    matches = [c for c in data['candidates'] if c.get('group_id') == group_id]
    if len(matches) < 2:
        raise ValueError('GROUP_NOT_FOUND')
    for row in matches:
        del row['group_id']
        row.setdefault('history', []).append({'operation':'ungroup','group_id':group_id})
    _save(path, data)
    return {'ungrouped':len(matches)}


def tsv(path: Path, trip: str | None = None, *, card_rows_list: list | None = None) -> dict:
    data = load(path)
    if card_rows_list is not None:
        for stored in data['candidates']:
            _settle(stored, card_rows_list)
    if not trip:
        raise ValueError("TRIP_REQUIRED")
    assigned = [c for c in data["candidates"] if c.get('trip_id') == trip]
    groups = {}
    singles = []
    for stored in assigned:
        if stored.get('group_id'):
            groups.setdefault(stored['group_id'], []).append(stored)
        elif not stored.get('hold'):
            singles.append(_candidate(stored))
    unassigned = [{"identity": c["identity"], "reason": "TRIP_UNASSIGNED"} for c in data["candidates"]
                  if not c.get("trip_id")]
    card_holds = [{"identity": c["identity"], "reason": c["hold"]} for c in data["candidates"]
                  if c.get("hold") and c.get("trip_id") == trip]
    rows = rc.to_expense_rows(singles)
    group_holds = []
    for group_id, members in groups.items():
        if len(members) < 2 or any(c.get('hold') or c.get('amount_krw') is None
               or not c.get('payee') or not c.get('category') for c in members):
            group_holds.append({'identity':group_id,'reason':'GROUP_INCOMPLETE'})
            continue
        # All members were confirmed with identical payee/category/payment/date.
        aggregate = rc.to_expense_rows([_candidate(members[0])])
        if len(aggregate) != 1:
            group_holds.append({'identity':group_id,'reason':'GROUP_INCOMPLETE'})
            continue
        aggregate[0]['transaction_id'] = 'receipt-group:' + group_id
        aggregate[0]['amount_krw'] = sum(c['amount_krw'] for c in members)
        rows.extend(aggregate)
    result = expense_tsv(rows, layout="rev")
    return {**result, "trip_id": trip,
            "held": result["held"] + data["holds"] + unassigned + card_holds + group_holds}


@_storage_errors
def dispatch(handler, parsed, *, raw=None, csrf: str = "", board=None, is_owner: bool = False, query=None) -> bool:
    if not owns_route(parsed.path) or not enabled():
        return False
    if not is_owner:
        # Fail closed: photos, regions, amounts and the copy text are the owner's records.
        handler._send_json({"code": "OWNER_ONLY", "message": "소유자만 볼 수 있습니다"}, 403)
        return True
    path = _store_path()
    image = IMAGE_PATH.match(parsed.path)
    if image and raw is None:
        try:
            data = image_bytes(path, image.group(1))
            handler._send_bytes(data, sniff_image(data))
        except ReceiptStoreError:
            raise
        except (KeyError, OSError):
            handler._send_json({"code": "IMAGE_NOT_FOUND"}, 404)
        except ValueError:
            handler._send_json({"code": "IMAGE_CORRUPT"}, 409)
        return True
    if parsed.path == "/api/receipts/upload" and not local_receipt_ocr.enabled():
        handler._send_json({"code": "OCR_ENGINE_NOT_APPROVED",
                            "message": "글자를 읽는 엔진이 승인되지 않았습니다. 영역과 값을 직접 입력하세요."}, 501)
        return True
    if raw is None:
        job = VISION_JOB.match(parsed.path)
        if job:
            state = receipt_vision_jobs.lookup(job.group(1))
            if state is None:
                handler._send_json({"code": "VISION_JOB_EXPIRED",
                                    "message": "분석 기록이 사라졌어요. 다시 분석해 주세요."}, 404)
            else:
                handler._send_json(state)
            return True
        if parsed.path == "/receipts":
            handler._send(render_html(load(path), csrf, _trips(board)))
        elif parsed.path == "/api/receipts":
            handler._send_json(load(path))
        elif parsed.path == "/api/receipts/tsv":
            trip = ((query or {}).get("trip") or [""])[0]
            try:
                handler._send_json(tsv(path, trip, card_rows_list=card_rows(board)))
            except ValueError as error:
                handler._send_json({"code": str(error)}, 400)
        elif parsed.path == "/api/receipts/learn":
            handler._send_json({"enabled": receipt_learning.enabled(), "records": receipt_learning.list_records()})
        else:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
        handler._send_json({"code": "CSRF_REQUIRED", "message": "화면을 다시 열어 주세요"}, 403)
        return True
    try:
        if parsed.path == "/api/receipts/image":
            handler._send_json(store_image(path, raw))
            return True
        body = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError('INVALID_VALUE')
        if parsed.path == "/api/receipts/upload":
            sha = body.get('image', '')
            if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
                raise ValueError('IMAGE_NOT_FOUND')
            image_bytes(path, sha)  # Only this owner's registered images may be read.
            try:
                result = local_receipt_ocr.recognize(_images_dir(path) / f'{sha}.bin', body.get('language', 'ja'))
                handler._send_json(result)
            except local_receipt_ocr.OcrError as error:
                handler._send_json({'code': str(error), 'message': '글자 인식이 끝나지 않았습니다. 사진을 보면서 직접 입력하거나 다시 시도해 주세요.'}, 503)
        elif parsed.path == "/api/receipts/vision":
            if not opencode_receipt_vision.enabled():
                handler._send_json({"code": "VISION_DISABLED",
                                    "message": "Muse 영수증 인식이 설정되지 않았습니다."}, 501)
                return True
            sha = body.get("image", "")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("IMAGE_NOT_FOUND")
            image_bytes(path, sha)  # Owner's registered source image only.
            guidance = receipt_learning.guidance(rules=receipt_learning.rules_for_prompt(record_use=True))
            try:
                state = receipt_vision_jobs.submit(sha, _images_dir(path) / f"{sha}.bin",
                                                   _recognizer(guidance))
            except receipt_vision_jobs.JobBusy:
                handler._send_json({"code": "VISION_BUSY",
                    "message": "이미 분석 중인 사진이 많아요. 잠시 후 다시 눌러 주세요."}, 429)
                return True
            handler._send_json(state, 202)
        elif parsed.path == "/api/receipts/vision/rescan":
            if not opencode_receipt_vision.enabled():
                handler._send_json({"code": "VISION_DISABLED",
                                    "message": "Muse 영수증 인식이 설정되지 않았습니다."}, 501)
                return True
            sha = body.get("image", "")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("IMAGE_NOT_FOUND")
            image_bytes(path, sha)
            count = body.get("expected_count")
            if count is not None and (type(count) is not int or not 1 <= count <= 50):
                raise ValueError("COUNT_INVALID")
            hint = body.get("hint")
            if hint is not None and not isinstance(hint, str):
                raise ValueError("HINT_INVALID")
            known = [_known_line(c) for c in load(path)["candidates"] if c.get("image_sha") == sha]
            guidance = receipt_learning.guidance(rules=receipt_learning.rules_for_prompt(record_use=True),
                                                 expected_count=count, known=known, hint=hint)
            try:
                # A separate key: a re-analysis is always a new run, never the earlier result for the photo.
                state = receipt_vision_jobs.submit(sha, _images_dir(path) / f"{sha}.bin", _recognizer(guidance),
                                                   key=f"{sha}:rescan:{uuid.uuid4().hex}")
            except receipt_vision_jobs.JobBusy:
                handler._send_json({"code": "VISION_BUSY",
                    "message": "이미 분석 중인 사진이 많아요. 잠시 후 다시 눌러 주세요."}, 429)
                return True
            handler._send_json(state, 202)
        elif parsed.path == "/api/receipts/vision/new":
            sha = body.get("image", "")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("IMAGE_NOT_FOUND")
            job_id = body.get("job_id", "")
            if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
                raise ValueError("VISION_JOB_NOT_READY")
            handler._send_json(vision_new(path, image=sha, job_id=job_id))
        elif parsed.path == "/api/receipts/learn":
            if body.get("confirm") is not True:
                raise ValueError("CONFIRM_REQUIRED")
            try:
                handler._send_json(receipt_learning.add_feedback(note_type=str(body.get("note_type", "")),
                                                                 scope=str(body.get("scope", "")),
                                                                 note=str(body.get("note") or "")))
            except receipt_learning.LearningUnavailable:
                handler._send_json({"code": "LEARNING_DISABLED",
                                    "message": "학습 파일 위치가 설정되지 않았습니다."}, 409)
        elif parsed.path == "/api/receipts/learn/status":
            handler._send_json(receipt_learning.set_status(str(body.get("id", "")), str(body.get("action", ""))))
        elif parsed.path == "/api/receipts/scan":
            handler._send_json(scan(path, body, board=board))
        elif parsed.path == "/api/receipts/group":
            if body.get('trip_id') not in _trip_ids(board):
                raise ValueError('TRIP_UNKNOWN')
            handler._send_json(group(path, identities=body.get('identities'),
                            trip_id=body['trip_id'], expected_versions=body.get('expected_versions')))
        elif parsed.path == "/api/receipts/ungroup":
            handler._send_json(ungroup(path, group_id=body.get('group_id')))
        elif parsed.path == "/api/receipts/edit":
            if set(body) - {"identity", "note", "merchant", "date", "total_jpy", "total_original", "payment", "trip_id", "expected_version"}:
                raise ValueError("FIELD_NOT_EDITABLE")
            changes = {k: body[k] for k in ("merchant", "date", "total_jpy", "total_original", "payment", "trip_id") if k in body}
            result = edit(path, identity=str(body.get("identity", "")), changes=changes,
                          note=str(body.get("note", "")), valid_trips=_trip_ids(board),
                          card_rows_list=card_rows(board), expected_version=body.get('expected_version'))
            handler._send_json({**result, 'version': candidate_version(result)})
        elif parsed.path == "/api/receipts/confirm":
            result = confirm(path, identity=str(body.get("identity", "")), payee=str(body.get("payee", "")),
                             category=str(body.get("category", "")), note=str(body.get("note", "")),
                             expected_version=body.get('expected_version'))
            handler._send_json({**result, 'version': candidate_version(result)})
        else:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
    except KeyError as error:
        handler._send_json({"code": str(error.args[0]) if error.args else "NOT_FOUND"}, 404)
    except (ValueError, TypeError) as error:
        handler._send_json({"code": str(error) or "INVALID_VALUE"}, 409 if str(error) == 'STALE_CANDIDATE' else 400)
    return True


def _trips(board) -> list[dict]:
    if board is None:
        return []
    return [{"id": t["tab_id"], "name": t.get("display_key") or t["tab_id"]} for t in board.list_trips()]


def _trip_ids(board) -> set:
    return {t["id"] for t in _trips(board)}


def _row_html(candidate: dict, trips: list) -> str:
    identity = html.escape(candidate["identity"])
    amount = "" if candidate["amount_krw"] is None else f"{candidate['amount_krw']:,}원"
    confirmed = bool(candidate.get("payee") and candidate.get("category"))
    source = (f"<a href='/api/receipts/image/{html.escape(candidate['image_sha'])}' target='_blank' rel='noopener'>원본 사진</a>"
              if candidate.get('image_sha') else '수동 입력')
    return (
        f"<tr data-version='{candidate_version(candidate)}' data-currency='{candidate.get('currency', 'JPY')}' "
        f"data-group-id='{html.escape(candidate.get('group_id') or '')}'>"
        f"<td data-label='상호·날짜·여행'>{source}"
        f"<label><input type='checkbox' data-group-select='{identity}'>지출 묶기 선택</label>"
        f"{'선택 묶음: '+html.escape(candidate['group_id'][:8]) if candidate.get('group_id') else ''}"
        f"<label>여행<select data-trip='{identity}' aria-label='여행'><option value=''>여행 미배정</option>"
        + "".join(f"<option value='{html.escape(t['id'])}'{' selected' if t['id'] == candidate.get('trip_id') else ''}>"
                  f"{html.escape(t['name'])}</option>" for t in trips)
        + f"</select></label><label>상호<input data-merchant='{identity}' aria-label='상호' value='{html.escape(candidate['merchant'])}'></label>"
        f"<label>거래일<input data-date='{identity}' aria-label='거래일' value='{html.escape(candidate['date'])}'></label></td>"
        f"<td data-label='금액·결제'><label>금액({candidate.get('currency', 'JPY')})<input data-total='{identity}' aria-label='금액({candidate.get('currency', 'JPY')})' value='{_native_total(candidate)}' inputmode='numeric'></label>"
        f"<label>결제수단<select data-payment='{identity}' aria-label='결제수단'>"
        + "".join(f"<option value='{p}'{' selected' if p == candidate['payment'] else ''}>{PAYMENT_LABELS[p]}</option>" for p in PAYMENTS)
        + "</select></label>"
        f"<button type='button' data-edit='{identity}'>{ui_icons.icon('pencil')}수정</button></td>"
        f"<td data-label='원화' data-amount>{amount}</td><td data-label='상태' data-state>{html.escape(MESSAGES.get(candidate.get('hold'), candidate.get('hold')) or ('확정됨' if confirmed else '사람 확인 필요'))}</td>"
        f"<td data-label='확정'><label>지급처<input data-payee='{identity}' aria-label='지급처' value='{html.escape(candidate.get('payee') or '')}' placeholder='지급처'></label>"
        f"<label>비용 분류<input data-category='{identity}' aria-label='비용 분류' value='{html.escape(candidate.get('category') or '')}' placeholder='식비·숙박비 등'></label>"
        f"<button type='button' data-confirm='{identity}'>{ui_icons.icon('check')}확정</button></td></tr>")


def _hold_html(hold: dict) -> str:
    candidate = hold.get('candidate') or hold.get('region') or {}
    amount = _native_total(candidate) if 'total_jpy' in candidate else candidate.get('total')
    currency = candidate.get('currency', 'JPY') or '통화 미확인'
    detail = (f"{candidate.get('merchant') or '상호 미확인'} · {candidate.get('date') or '날짜 미확인'} · "
              f"{amount if amount is not None else '금액 미확인'} {currency} · "
              if candidate else '')
    image = hold.get('image_sha') or candidate.get('image_sha')
    source = (f" <a href='/api/receipts/image/{html.escape(image)}' target='_blank' rel='noopener'>원본 사진</a>"
              if image else '')
    box = ' · 영역 ' + str(candidate['box']) if candidate.get('box') is not None else ''
    return '<li>' + html.escape(detail + MESSAGES.get(hold['reason'], hold['reason']) + box) + source + '</li>'


LEARN_LABELS = {'SMALL_TICKET_MISSED': '작은 승선권·영수증 누락', 'IDENTICAL_MERGED': '같은 금액 영수증 합침',
                'OVERLAPPING_SLIPS': '겹친 영수증 구분 실패', 'KOREAN_MERCHANT_MISSED': '한국어 상호 누락',
                'TOTAL_CONFUSED': '세금·거스름돈을 총액으로 혼동', 'OTHER': '기타 메모 (규칙으로 저장하지 않음)'}
LEARNING_SCRIPT = r"""const rescanChoices={currency:[['','통화 선택'],['JPY','엔화 JPY'],['KRW','원화 KRW']],payment:[['','결제수단 선택'],['cash','현금'],['private_card','개인카드'],['corporate_card','법인카드']]};
const learnLabel=type=>learnLabels[type]||type;
const renderLearning=async()=>{const list=document.getElementById('learn-list');if(!list)return;const body=await fetch('/api/receipts/learn',{headers:{'X-CSRF-Token':csrf}}).then(readResponse);list.replaceChildren();const note=text=>{const li=document.createElement('li');li.textContent=text;list.append(li)};if(!body.enabled){note('학습 파일 위치가 설정되지 않아 메모를 저장하지 않습니다.');return}if(!body.records.length){note('저장된 학습 메모가 없습니다.');return}for(const record of body.records){const li=document.createElement('li');const state=record.status==='active'?'적용 중':record.status==='disabled'?'사용 중지':record.status==='merged'?'같은 규칙이 이미 적용 중':'메모만 저장';li.textContent=learnLabel(record.type)+' · '+state+' · '+(record.note||'(메모 없음)')+(record.applied?' · 분석에 '+record.applied+'회 참고':'');for(const [action,text] of [['disable','사용 중지'],['enable','다시 사용'],['delete','삭제']]){if(action==='disable'&&record.status!=='active')continue;if(action==='enable'&&record.status!=='disabled')continue;const button=document.createElement('button');button.type='button';button.textContent=text;button.onclick=()=>save(()=>post('/api/receipts/learn/status',{id:record.id,action}),()=>renderLearning().catch(()=>{}));li.append(' ',button)}list.append(li)}};
const learnGo=document.getElementById('learn-go');
if(learnGo)learnGo.onclick=()=>{if(!document.getElementById('learn-confirm').checked){say('규칙 내용을 확인했다는 표시를 먼저 해 주세요.');return}const scope=document.querySelector('input[name=learn-scope]:checked').value;save(()=>post('/api/receipts/learn',{confirm:true,note_type:document.getElementById('learn-type').value,scope,note:document.getElementById('learn-note').value}),result=>{say(result.status==='duplicate'?'이미 같은 메모가 저장되어 있습니다.':'학습 메모를 저장했습니다. 다음 분석부터 참고합니다.');document.getElementById('learn-note').value='';document.getElementById('learn-confirm').checked=false;renderLearning().catch(()=>{})})};
const jobDone=async job=>{const started=Date.now();let state=job;while(state.status==='queued'||state.status==='running'){if(Date.now()-started>420000)throw new Error('인식 시간이 길어지고 있어요. 잠시 후 다시 시도해 주세요.');say('Muse가 빠진 영수증을 찾고 있습니다. '+Math.round((Date.now()-started)/1000)+'초 경과');await new Promise(r=>setTimeout(r,2000));state=await fetch('/api/receipts/vision/'+state.job_id,{headers:{'X-CSRF-Token':csrf}}).then(readResponse)}return state};
const renderNew=(out,receipts,sha)=>{if(!receipts.length)return;const box=document.createElement('div');for(const item of receipts){const row=document.createElement('div');row.className='rescan-row';row.dataset.reading=item.reading;row.dataset.ordinal=String(item.ordinal);row.style.cssText='margin:8px 0;padding:8px;border:1px solid #e4e7ec;border-radius:8px';const check=document.createElement('input');check.type='checkbox';check.checked=true;check.dataset.rescanCheck='1';const label=document.createElement('label');label.append(check,' 새 영수증으로 등록');row.append(label);for(const field of ['merchant','date','amount','currency','payment']){const choices=rescanChoices[field];const input=document.createElement(choices?'select':'input');input.dataset.rescanField=field;if(choices){for(const [value,text] of choices){const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option)}}else input.placeholder=field;input.value=item[field]??'';input.style.cssText='display:block;width:100%;margin:4px 0';row.append(input)}box.append(row)}const submit=document.createElement('button');submit.type='button';submit.id='rescan-register';submit.textContent='선택한 새 영수증 등록';box.append(submit);submit.onclick=()=>{const regions=[...box.querySelectorAll('.rescan-row')].filter(r=>r.querySelector('[data-rescan-check]').checked).map(r=>{const v=f=>r.querySelector('[data-rescan-field='+f+']').value.trim();return {box:null,merchant:v('merchant')||null,date:v('date')||null,currency:v('currency')||null,total:v('amount')?Number(v('amount')):null,payment:v('payment')||null,confidence:1,ordinal:Number(r.dataset.ordinal),reading:r.dataset.reading}});if(!regions.length){say('등록할 새 영수증을 선택하세요.');return}if(regions.some(r=>!r.currency)){say('통화를 선택한 뒤 등록해 주세요.');return}save(()=>post('/api/receipts/scan',{image:sha,trip_id:selectedTrip.value||undefined,regions}),result=>{say('새 영수증 '+result.added+'건을 등록했습니다. 후보 새로고침을 누르세요.')})};out.append(box)};
const rescanGo=document.getElementById('rescan-go');
if(rescanGo)rescanGo.onclick=async()=>{if(receiptBusy)return;const sha=document.getElementById('image-sha').value;if(!sha){say('사진을 먼저 선택해 주세요.');return}if(!selectedTrip.value){say('여행을 먼저 선택해 주세요.');return}receiptBusy=true;const restore=lockControls();const out=document.getElementById('rescan-results');out.replaceChildren();try{const count=document.getElementById('rescan-count').value;const hint=document.getElementById('rescan-hint').value.trim();let state=await post('/api/receipts/vision/rescan',{image:sha,expected_count:count?Number(count):undefined,hint:hint||undefined});state=await jobDone(state);if(state.status!=='done')throw new Error(state.code==='VISION_BUSY'?'이미 분석 중인 사진이 많아요. 잠시 후 다시 눌러 주세요.':'다시 찾기에 실패했습니다. 직접 추가해 주세요.');const found=await post('/api/receipts/vision/new',{image:sha,job_id:state.job_id});renderNew(out,found.new,sha);say(found.new.length?'새 후보 '+found.new.length+'건을 찾았습니다. 확인 후 등록하세요.':'새로 찾은 영수증이 없습니다. 필요하면 직접 추가하세요.')}catch(error){say(error.message||'다시 찾기에 실패했습니다.')}finally{restore();receiptBusy=false}};
if(document.getElementById('learn-list'))renderLearning().catch(()=>{});
"""


def _learning_html() -> str:
    options = "".join(f"<option value='{key}'>{html.escape(text)}</option>" for key, text in LEARN_LABELS.items())
    return ("<section><h2>Muse 누락 영수증 다시 찾기</h2>"
            "<p>빠진 영수증이 있으면 실제 개수와 설명을 적고 다시 찾을 수 있습니다. 기존 후보는 바뀌지 않으며, 새로 찾은 것만 보여 줍니다.</p>"
            "<label>실제 영수증 개수 <input id='rescan-count' type='number' min='1' max='50' style='width:5em'></label> "
            "<label>추가 설명 <input id='rescan-hint' maxlength='200' placeholder='예: 오른쪽 아래에 작은 승선권이 하나 더 있어요'></label> "
            "<button type='button' id='rescan-go'>누락된 영수증 다시 찾기</button>"
            "<div id='rescan-results' aria-live='polite'></div></section>"
            "<section><h2>인식 학습 메모 (소유자 전용)</h2>"
            "<p>잘못 인식한 종류를 고르고 확인하면 다음 Muse 분석에 참고합니다. 사진이 정본이며, 날짜·금액·상호는 규칙으로 저장하지 않습니다.</p>"
            f"<label>잘못된 종류 <select id='learn-type'>{options}</select></label> "
            "<label><input type='radio' name='learn-scope' value='general' checked> 비슷한 영수증에 앞으로도 적용</label> "
            "<label><input type='radio' name='learn-scope' value='this_photo'> 이번 사진에만 기록</label><br>"
            "<input id='learn-note' maxlength='240' placeholder='메모 (선택)'> "
            "<label><input type='checkbox' id='learn-confirm'> 저장될 내용을 확인했습니다</label> "
            "<button type='button' id='learn-go'>학습에 반영</button>"
            "<h3>저장된 학습 메모</h3><ul id='learn-list'></ul></section>")


def render_html(data: dict, csrf: str, trips: list | None = None) -> str:
    trips = trips or []
    trip_options = "".join(f"<option value='{html.escape(t['id'])}'>{html.escape(t['name'])}</option>"
                            for t in trips)
    rows = "".join(_row_html(c, trips) for c in data["candidates"]) or '<tr><td colspan="5">등록된 후보가 없습니다. 영수증 영역과 값을 입력해 주세요.</td></tr>'
    holds = ''.join(_hold_html(h) for h in data['holds']) or '<li>보류된 영수증이 없습니다.</li>'
    images = "".join(
        f"<button type='button' data-image-sha='{sha}' aria-pressed='{'true' if sha == data['images'][-1] else 'false'}' "
        f"style='max-width:30%'>사진 {index} 선택<img src='/api/receipts/image/{sha}' alt='등록한 영수증 사진' style='max-width:100%'></button>"
        for index, sha in enumerate(data['images'][-12:], start=max(1, len(data['images']) - 11)))
    script = (
        f"const csrf={json.dumps(csrf)};"
        f"const messages={json.dumps(MESSAGES)};const message=code=>messages[code]||code;"
        "const responseError=status=>status===401?'로그인이 만료됐습니다. 다시 로그인해 주세요.':"
        "status===403?'접근 권한을 확인하고 화면을 다시 열어 주세요.':"
        "'서버 응답을 확인하지 못했습니다. 저장 여부를 확인한 뒤 다시 시도해 주세요.';"
        "const readResponse=async response=>{let body;try{body=await response.json()}catch{throw new Error(responseError(response.status))}"
        "if(!body||typeof body!=='object'||Array.isArray(body))throw new Error(responseError(response.status));"
        "if(!response.ok)throw new Error(body.message||message(body.code)||responseError(response.status));return body};"
        "const post=(p,b)=>fetch(p,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},"
        "body:JSON.stringify(b)}).then(readResponse);"
        "const say=t=>document.getElementById('status').textContent=message(t);"
        "const val=(name,id)=>document.querySelector('['+name+'=\"'+id+'\"]').value;"
        "const editableFields='[data-trip],[data-merchant],[data-date],[data-total],[data-payment]';"
        "const reviewFields=editableFields+',[data-payee],[data-category]';"
        "const originalValues=new Map([...document.querySelectorAll(reviewFields)].map(input=>[input,input.value]));"
        "let receiptBusy=false;const lockControls=()=>{const controls=[...document.querySelectorAll('input,select,button')];"
        "const disabled=controls.map(control=>control.disabled);controls.forEach(control=>control.disabled=true);"
        "return()=>controls.forEach((control,index)=>control.disabled=disabled[index])};"
        "const updateCandidate=(button,result)=>{const row=button.closest('tr');row.dataset.version=result.version;"
        "for(const [field,key] of [['trip','trip_id'],['merchant','merchant'],['date','date'],['total','total_jpy'],"
        "['payment','payment'],['payee','payee'],['category','category']]){const input=row.querySelector('[data-'+field+']');"
        "input.value=(field==='total'&&result.currency==='KRW'?result.total_original:result[key])??'';originalValues.set(input,input.value)}"
        "row.querySelector('[data-amount]').textContent=result.amount_krw==null?'':result.amount_krw.toLocaleString('ko-KR')+'원';"
        "row.querySelector('[data-state]').textContent=result.hold?message(result.hold):(result.payee&&result.category?'확정됨':'사람 확인 필요');"
        "say('영수증 변경을 저장했습니다.')};"
        "const save=async(action,onSaved)=>{if(receiptBusy)return;"
        "if(!onSaved&&[...document.querySelectorAll(reviewFields)].some(input=>input.value!==originalValues.get(input))){"
        "say('영수증의 변경을 먼저 저장해 주세요. 입력값은 유지합니다.');return}"
        "receiptBusy=true;const restore=lockControls();"
        "say('저장하고 있습니다.');try{const result=await action();if(onSaved){try{onSaved(result)}catch{"
        "say('저장은 완료됐지만 화면 갱신에 실패했습니다. 입력값을 보관하고 화면을 다시 열어 주세요.')}}else location.reload()}"
        "catch(error){say(error.message||'저장하지 못했습니다. 다시 시도해 주세요.')}"
        "finally{restore();receiptBusy=false}};"
        "document.querySelectorAll('[data-image-sha]').forEach(button=>button.onclick=()=>{"
        "document.getElementById('image-sha').value=button.dataset.imageSha;"
        "document.querySelectorAll('[data-image-sha]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));"
        "say('선택한 사진의 영수증 값을 입력해 주세요.')});"
        "const normalizeReceiptImage=async file=>{const limit=5*1024*1024;if((file.type==='image/jpeg'||file.type==='image/png')&&file.size<=limit)return file;if(!file.type.startsWith('image/'))throw new Error('사진 형식만 등록할 수 있습니다.');const url=URL.createObjectURL(file);const img=new Image();try{await new Promise((ok,fail)=>{img.onload=ok;img.onerror=()=>fail(new Error('이 사진을 열 수 없습니다. iPhone에서 JPEG로 내보내 다시 시도하세요.'));img.src=url;});if(!img.naturalWidth||!img.naturalHeight)throw new Error('사진 크기를 확인할 수 없습니다.');for(const maxSide of [3000,2600,2200]){const scale=Math.min(1,maxSide/Math.max(img.naturalWidth,img.naturalHeight));const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(img.naturalWidth*scale));canvas.height=Math.max(1,Math.round(img.naturalHeight*scale));const context=canvas.getContext('2d');if(!context)throw new Error('사진 변환을 사용할 수 없습니다.');context.drawImage(img,0,0,canvas.width,canvas.height);for(const quality of [.92,.82,.72]){const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',quality));if(blob&&blob.size>0&&blob.size<=limit)return blob;}}throw new Error('사진이 5MB 제한을 넘었습니다. 더 작은 사진으로 다시 촬영해 주세요.');}finally{URL.revokeObjectURL(url)}};"
        "document.getElementById('img-go').onclick=async()=>{const files=[...document.getElementById('img-file').files];"
        "if(!files.length){say('사진 파일을 고르세요');return}await save(async()=>{"
        "for(const f of files){const r=await fetch('/api/receipts/image',{method:'POST',"
        "headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':csrf},body:await normalizeReceiptImage(f)});"
        "const j=await readResponse(r);document.getElementById('image-sha').value=j.sha256;}})};"
        "const ocrButton=document.getElementById('ocr-go');if(ocrButton)ocrButton.onclick=async()=>{"
        "if(receiptBusy)return;const sha=document.getElementById('image-sha').value;if(!sha){say('사진을 먼저 등록해 주세요.');return}"
        "receiptBusy=true;const restore=lockControls();say('PC에서 글자를 읽고 있습니다.');try{"
        "const result=await post('/api/receipts/upload',{image:sha,language:document.getElementById('ocr-language').value});"
        "document.getElementById('ocr-text').value=result.text;"
        "const hints=result.suggestions||{};if(hints.date&&!document.getElementById('r-date').value)document.getElementById('r-date').value=hints.date;"
        "if(hints.total_jpy&&document.getElementById('r-currency').value==='JPY'&&!document.getElementById('r-total').value)document.getElementById('r-total').value=hints.total_jpy;"
        "say('글자를 읽었습니다. 여러 영수증은 한 건씩 나누어 금액·통화·결제수단을 직접 확인해 주세요.');"
        "}catch(error){say(error.message)}finally{restore();receiptBusy=false}};"
        "document.getElementById('region-go').onclick=()=>{const sha=document.getElementById('image-sha').value;"
        "if(!document.getElementById('r-currency').value){say('통화를 선택해 주세요.');return}"
        "const region={box:null,"
        "merchant:document.getElementById('r-merchant').value,date:document.getElementById('r-date').value,"
        "currency:document.getElementById('r-currency').value,total:Number(document.getElementById('r-total').value),payment:document.getElementById('r-payment').value,confidence:1};"
        "save(()=>post('/api/receipts/scan',{image:sha||undefined,trip_id:selectedTrip.value||undefined,regions:[region]}))};"
        "document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{const id=b.dataset.edit;"
        "save(()=>post('/api/receipts/edit',{identity:id,expected_version:b.closest('tr').dataset.version,trip_id:val('data-trip',id),merchant:val('data-merchant',id),date:val('data-date',id),"
        "[b.closest('tr').dataset.currency==='KRW'?'total_original':'total_jpy']:Number(val('data-total',id)),payment:val('data-payment',id)}),result=>updateCandidate(b,result))});"
        "document.getElementById('r-currency').onchange=()=>{document.getElementById('r-total').placeholder='금액('+document.getElementById('r-currency').value+')'};"
        "document.querySelectorAll('[data-confirm]').forEach(b=>b.onclick=()=>{const id=b.dataset.confirm;"
        "if([...b.closest('tr').querySelectorAll(editableFields)].some(input=>input.value!==originalValues.get(input))){"
        "say('금액·결제수단·여행 변경은 수정 버튼으로 먼저 저장한 뒤 확정해 주세요.');return}"
        "save(()=>post('/api/receipts/confirm',{identity:id,expected_version:b.closest('tr').dataset.version,payee:val('data-payee',id),category:val('data-category',id)}),result=>updateCandidate(b,result))});"
        "document.getElementById('copy-tsv').onclick=async()=>{if(receiptBusy)return;"
        "const selection=document.getElementById('copy-trip');const trip=selection.value;if(!trip){say('복사할 여행을 고르세요');return}"
        "const dirty=[...document.querySelectorAll('tr[data-version]')].some(row=>{const assigned=row.querySelector('[data-trip]');"
        "return (assigned.value===trip||originalValues.get(assigned)===trip)&&"
        "[...row.querySelectorAll(reviewFields)].some(input=>input.value!==originalValues.get(input))});"
        "if(dirty){say('저장하지 않은 변경이 있습니다. 수정·확정 버튼으로 저장한 뒤 복사해 주세요.');return}"
        "const key='gcopy-trip:'+trip;let previous=null;try{previous=localStorage.getItem(key)}catch{if(!confirm('복사 이력을 읽을 수 없습니다. 이미 Google에 붙여넣었는지 확인해 주세요. 중복 붙여넣기에 주의하고 계속 복사할까요?'))return;}"
        "if(previous&&!confirm('이 여행은 '+previous+'에 이미 구글 시트용으로 복사했습니다. 카드와 영수증을 각각 복사했다면 중복 붙여넣기에 주의하세요. 계속할까요?'))return;"
        "receiptBusy=true;const restore=lockControls();try{const response=await fetch('/api/receipts/tsv?trip='+encodeURIComponent(trip));"
        "const x=await readResponse(response);"
        "if(!x.row_count){say('복사할 확정 영수증이 없습니다. 보류 '+x.held.length+'건');return}"
        "await navigator.clipboard.writeText(x.tsv);let historyWarning='';try{localStorage.setItem(key,new Date().toLocaleString('ko-KR'))}catch{historyWarning=' 복사 이력을 저장하지 못했습니다. 중복 붙여넣기에 주의해 주세요.'}"
        "say('영수증 '+x.row_count+'행을 클립보드에 복사했습니다. 구글 시트에 붙여넣은 뒤에만 반영됩니다.'+historyWarning)}"
        "catch(error){say(error.message||'복사하지 못했습니다. 다시 시도해 주세요')}finally{restore();receiptBusy=false}};")
    vision_script = (
        "const selectedTrip=document.getElementById('selected-trip');"
        "try{const old=sessionStorage.getItem('cost-receipt-trip');if(old)selectedTrip.value=old;}catch{}"
        "if(selectedTrip.value)document.getElementById('copy-trip').value=selectedTrip.value;"
        "selectedTrip.onchange=()=>{try{sessionStorage.setItem('cost-receipt-trip',selectedTrip.value)}catch{};"
        "document.getElementById('copy-trip').value=selectedTrip.value;};"
        "const visionGo=document.getElementById('vision-go');"
        "if(visionGo)visionGo.onclick=async()=>{if(receiptBusy)return;"
        "const sha=document.getElementById('image-sha').value;"
        "if(!sha){say('사진을 먼저 등록하세요.');return}"
        "if(!selectedTrip.value){say('여행을 먼저 선택하세요.');return}"
        "receiptBusy=true;const restore=lockControls();say('Muse가 영수증 영역과 금액을 인식하고 있습니다.');"
        "try{let state=await post('/api/receipts/vision',{image:sha});const t0=Date.now();"
        "while(state.status==='queued'||state.status==='running'){"
        "say('Muse로 분석 중입니다. '+Math.round((Date.now()-t0)/1000)+'초 경과');"
        "if(Date.now()-t0>420000)throw new Error('인식 시간이 길어지고 있어요. 다시 분석하거나 수동으로 입력하세요.');"
        "await new Promise(r=>setTimeout(r,2000));"
        "const poll=await fetch('/api/receipts/vision/'+state.job_id,{headers:{'X-CSRF-Token':csrf}});"
        "const body=await poll.json();"
        "if(!poll.ok)throw new Error(body.message||'분석 기록을 확인하지 못했습니다. 다시 분석해 주세요.');"
        "state=body;}"
        "if(state.status!=='done')throw new Error(state.code==='VISION_BUSY'?'이미 분석 중인 사진이 많아요. 잠시 후 다시 눌러 주세요.':state.code==='VISION_ALL_MODELS_UNAVAILABLE'?'무료 AI 모델을 사용할 수 없습니다. 직접 입력해 주세요.':'Muse 인식에 실패했습니다. 인식 설정을 확인하거나 수동으로 입력하세요.');"
        "const response=state.result;"
        "const view=document.getElementById('vision-preview');const items=document.getElementById('vision-results');"
        "view.replaceChildren();items.replaceChildren();"
        "const previewImg=document.createElement('img');previewImg.src='/api/receipts/image/'+sha;"
        "previewImg.alt='업로드한 원본 영수증 사진';previewImg.style.width='100%';view.append(previewImg);"
        "if(!response.receipts.length){say('인식된 영수증이 없습니다. 사진을 확인하거나 직접 지출을 추가해 주세요.');return}"
        "const visionOptions={currency:[['','통화 선택'],['JPY','엔화 JPY'],['KRW','원화 KRW']],payment:[['','결제수단 선택'],['cash','현금'],['private_card','개인카드'],['corporate_card','법인카드']]};"
        "for(const slip of response.receipts){const row=document.createElement('div');row.className='vision-row';"
        "row.style.cssText='margin:8px 0;padding:8px;border:1px solid #e4e7ec;border-radius:8px';"
        "const check=document.createElement('input');check.type='checkbox';check.checked=true;check.dataset.visionCheck='1';"
        "const label=document.createElement('label');label.append(check,' 등록에 포함');row.append(label);"
        "for(const field of ['merchant','date','amount','currency','payment']){const choices=visionOptions[field];"
        "const input=document.createElement(choices?'select':'input');input.dataset.visionField=field;"
        "if(choices){for(const [value,text] of choices){const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option)}}"
        "else input.placeholder=field;input.value=slip[field]??'';"
        "input.style.cssText='display:block;width:100%;margin:4px 0';row.append(input);}"
        "items.append(row);}"
        "const submit=document.createElement('button');submit.type='button';submit.id='vision-register';"
        "submit.textContent='선택한 영수증 등록';items.append(submit);"
        "submit.onclick=()=>{const regions=[...items.querySelectorAll('.vision-row')].filter(r=>r.querySelector('[data-vision-check]').checked).map(r=>{"
        "const v=f=>r.querySelector('[data-vision-field='+f+']').value.trim();"
        "return {box:null,merchant:v('merchant')||null,date:v('date')||null,currency:v('currency')||null,"
        "total:v('amount')?Number(v('amount')):null,payment:v('payment')||null,confidence:1}});"
        "if(!regions.length){say('등록할 영수증을 하나 이상 선택하세요.');return}"
        "if(regions.some(r=>!r.currency)){say('통화를 선택한 뒤 등록해 주세요.');return}"
        "save(()=>post('/api/receipts/scan',{image:sha,trip_id:selectedTrip.value||undefined,regions}),"
        "result=>{say('영수증 '+result.added+'건을 등록했습니다. 후보 새로고침을 누르세요.')})};"
        "say((response.label&&response.label!=='Muse'?'Muse 사용이 제한되어 '+response.label+'로 분석했습니다. ':'')+'영수증 '+response.receipts.length+'건을 찾았습니다. 금액·날짜를 원본과 비교한 뒤 등록하세요.');"
        "}catch(error){say(error.message||'Muse 인식이 실패했습니다. 수동으로 입력하세요.');}"
        "finally{restore();receiptBusy=false}};"
        "const visionFinish=document.getElementById('vision-finish');"
        "if(visionFinish)visionFinish.onclick=()=>location.reload();"
        "const groupSelection=()=>[...document.querySelectorAll('[data-group-select]:checked')].map(input=>input.closest('tr'));"
        "document.getElementById('group-go').onclick=()=>{const chosen=groupSelection();"
        "if(chosen.length<2){say('두 장 이상 선택한 뒤 묶어 주세요.');return}"
        "const trip=selectedTrip.value;if(!trip){say('묶을 여행을 선택하세요.');return}"
        "const identities=chosen.map(row=>row.querySelector('[data-group-select]').dataset.groupSelect);"
        "const versions=Object.fromEntries(chosen.map(row=>[row.querySelector('[data-group-select]').dataset.groupSelect,row.dataset.version]));"
        "save(()=>post('/api/receipts/group',{trip_id:trip,identities,expected_versions:versions}))};"
        "document.getElementById('ungroup-go').onclick=()=>{const chosen=groupSelection();"
        "const ids=[...new Set(chosen.map(row=>row.dataset.groupId).filter(Boolean))];"
        "if(ids.length!==1||!chosen.length){say('해제할 묶음에 속한 영수증 하나를 선택하세요.');return}"
        "save(()=>post('/api/receipts/ungroup',{group_id:ids[0]}))};"
    )
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>영수증 후보</title>"
            "<style>*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:16px;background:#f7f9fc;color:#182230}"
            "h1{font-size:24px}h2{font-size:18px}section{margin:16px 0;padding:16px;background:white;border:1px solid #e4e7ec;border-radius:8px}"
            "table{border-collapse:collapse;width:100%;font-size:14px;background:white}td,th{border:1px solid #e4e7ec;padding:8px;text-align:left}"
            "td{vertical-align:top}td label{display:block;font-size:12px;margin:6px 0}"
            "td input,td select{display:block;width:100%;min-width:0}input,select,button{font:inherit;max-width:100%;min-height:36px}"
            "input,select{padding:6px;border:1px solid #d0d5dd;border-radius:6px;background:white}"
            "button,.work-back{padding:8px 12px;border:1px solid #d0d5dd;border-radius:6px;background:white;cursor:pointer}"
            "button .ic{width:16px;height:16px;vertical-align:-3px;pointer-events:none}"
            "button .ic:first-child{margin-right:6px}"
            "@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}"
            ".work-back{display:inline-flex;align-items:center;min-height:44px;color:#166444;text-decoration:none}"
            "#status:not(:empty){position:sticky;top:0;z-index:10;background:#eff6ff;color:#1e3a8a;padding:12px;border:1px solid #bfdbfe;border-radius:8px;font-weight:600}"
            "@media(max-width:759px){table,tbody,tr,td{display:block;width:100%}table{background:transparent}"
            "thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}"
            "tr{border:1px solid #e4e7ec;border-radius:8px;background:white;padding:10px;margin:0 0 12px}"
            "td{border:0;border-bottom:1px solid #f2f4f7;padding:8px 0}td:last-child{border:0}"
            "td::before{content:attr(data-label);display:block;font-size:13px;font-weight:600;margin-bottom:6px}"
            "input,select,button{min-height:44px;font-size:16px}td button{width:100%}"
            "section>input,section>select{width:100%;margin:4px 0}section{padding:12px}"
            "#copy-trip{width:100%;margin:6px 0}#copy-tsv{width:100%}h1{font-size:22px}}"
            "</style></head><body>"
            f"<nav aria-label='장부 이동'><a class='work-back' href='/board'>{ui_icons.icon('chevron-left')}장부로 돌아가기</a></nav>"
            "<h1>영수증 후보</h1><p id='status' role='status' aria-live='polite'></p>"
            + ("<p>Windows OCR로 사진의 글자를 읽습니다. 인식값은 확정되지 않은 참고값이며 금액과 결제수단을 확인해야 합니다.</p>"
               "<label>인식 언어<select id='ocr-language'><option value='ja'>일본어</option><option value='ko'>한국어</option></select></label>"
                f"<button type='button' id='ocr-go'>{ui_icons.icon('search')}선택한 사진 글자 읽기</button>"
               "<label>인식한 글자<textarea id='ocr-text' readonly style='display:block;width:100%;min-height:120px'></textarea></label>"
               if local_receipt_ocr.enabled() else
               "<p>자동 추출은 연결되지 않았습니다. 사진을 보면서 영수증별로 상호·날짜·통화·금액을 입력해 주세요.</p>") +
            "<p>원화는 입력 금액 그대로 사용합니다. 일본 현금·개인카드는 JPY×10을 적용합니다. 법인카드는 카드와 대사하는 증빙이며 추가 지출로 복사하지 않습니다.</p>"
             "<section><h2>영수증 여행 선택</h2><label>이 페이지의 모든 영수증이 속한 여행"
            "<select id='selected-trip'><option value=''>여행을 먼저 선택하세요</option>" + trip_options +
            "</select></label></section>"
            "<section><h2>사진 등록</h2><input id='img-file' type='file' multiple accept='image/*'>"
             f"<button type='button' id='img-go'>{ui_icons.icon('upload')}사진 등록</button>"
            f"<input type='hidden' id='image-sha' value='{data['images'][-1] if data['images'] else ''}'>"
            f"<p>iPhone 사진(HEIC 포함)이나 큰 사진은 업로드 전에 JPEG로 변환합니다. 글자가 선명한지 확인해 주세요. 최근 사진을 선택할 수 있습니다.</p><div>{images}</div></section>"
            + ("<section><h2>Muse Spark AI 영수증 인식</h2>"
               "<p>선택한 여행의 사진만 분석합니다. OpenCode Contributor Free 모델로 원본 이미지가 전송되며 "
               "학습·개선에 이용될 수 있습니다. 후보는 확인 전까지 회계에 반영되지 않습니다.</p>"
               "<button type='button' id='vision-go'>Muse로 영수증 자동 찾기</button>"
               "<div id='vision-preview' style='position:relative;max-width:560px'></div>"
               "<div id='vision-results' aria-live='polite'></div>"
               "<button type='button' id='vision-finish'>후보 새로고침</button></section>"
               if opencode_receipt_vision.enabled() else "")
            + (_learning_html() if opencode_receipt_vision.enabled() else "")
            + "<section><h2>직접 입력</h2>"
            "<input id='r-merchant' placeholder='상호'> <input id='r-date' placeholder='2027-08-03'> "
"<label>통화<select id='r-currency'><option value=''>통화 확인</option><option value='JPY' selected>엔화 JPY</option><option value='KRW'>원화 KRW</option></select></label>"
            "<input id='r-total' type='number' placeholder='금액(JPY)'> "
"<select id='r-payment'><option value=''>결제수단 확인</option><option value='cash' selected>현금</option><option value='private_card'>개인카드</option>"
            "<option value='corporate_card'>법인카드</option></select>"
             f"<button type='button' id='region-go'>{ui_icons.icon('pencil')}영수증 추가</button></section>"
            "<h2>후보</h2>"
            "<table><thead><tr><th>상호·날짜</th><th>금액·결제</th><th>원화</th><th>상태</th><th>확정</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
            "<section><h2>승선권 등 선택 묶기</h2>"
            "<p>같은 여행·날짜·업체·결제수단의 확정된 영수증 여러 장을 선택하면 "
            "하나의 지출 행으로 합산됩니다. 원본 증빙과 개별 금액은 보존됩니다.</p>"
            "<button id='group-go' type='button'>선택한 영수증을 한 지출로 묶기</button> "
            "<button id='ungroup-go' type='button'>선택한 묶음 해제</button></section>"
            f"<h2>보류</h2><ul>{holds}</ul>"
            f"<p><label>복사할 여행 <select id='copy-trip'>{trip_options}</select></label> "
             f"<button type='button' id='copy-tsv'>{ui_icons.icon('copy')}구글 지출 7열 복사</button></p>"
            f"<script>const learnLabels={json.dumps(LEARN_LABELS, ensure_ascii=False)};{script}{vision_script}{LEARNING_SCRIPT}</script></body></html>")
