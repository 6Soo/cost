"""Receipt candidates: image, optional local Windows OCR, manual edit and copy.

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

ROUTES = ("/receipts", "/api/receipts", "/api/receipts/scan",
          "/api/receipts/edit", "/api/receipts/tsv", "/api/receipts/upload", "/api/receipts/image", "/api/receipts/vision",
          "/api/receipts/vision/rescan", "/api/receipts/vision/new", "/api/receipts/learn", "/api/receipts/learn/delete",
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
                                 confidence=float(r.get("confidence", 1.0)), ordinal=ordinal, reading=reading,
                                 category=r.get("category") or None))
    return regions


def reading_key(values: dict) -> str:
    return json.dumps([values.get('merchant'), values.get('date'), values.get('total'),
                       values.get('currency', 'JPY'), values.get('payment')], ensure_ascii=False)


def _recognizer(guidance, lesson=False):
    def run(image_path):
        result = opencode_receipt_vision.recognize_with_fallback(image_path, guidance=guidance, lesson=lesson)
        # The reading is what Muse first gave; a later correction must not change which receipt it is.
        for item in result.get('receipts', []):
            item['reading'] = reading_key({'merchant': item['merchant'], 'date': item['date'], 'total': item['amount'],
                                           'currency': item['currency'], 'payment': item['payment']})
        return result
    return run


def learn_from_job(path: Path, *, image: str, job_id: str) -> dict:
    """Saves the lesson that a re-analysis wrote, once the owner has registered a receipt it found."""
    state = receipt_vision_jobs.lookup(job_id)
    if state is None or state['image'] != image or state['status'] != 'done':
        return {'status': 'no_lesson'}
    lesson = state['result'].get('lesson')
    if not lesson:
        return {'status': 'no_lesson'}
    # Merchant names on this photo, old and newly found, are kept out of the lesson.
    names = [c.get('merchant') for c in load(path)['candidates'] if c.get('image_sha') == image]
    names += [r.get('merchant') for r in state['result']['receipts']]
    return receipt_learning.remember_lesson(lesson, names=names)


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
        stored['payee'] = region.merchant or None
        stored['category'] = region.category
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
    """Why a candidate cannot be classified yet. A partial reading stays a candidate until a person fills the gap."""
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
        allowed = {"merchant", "date", total_field, "payment", "trip_id", "payee", "category"}
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
        if ("merchant" in changes and before.get("merchant") == stored.get("payee") and not ("payee" in changes)):
            stored["payee"] = stored["merchant"]
        if any(before[k] != stored.get(k) for k in changes):
            stored.setdefault("history", []).append({"edit": before, "to": changes, "note": note,
                                                     "operation": "edit", "request_version": expected_version})
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
            handler._send_json({"enabled": receipt_learning.enabled(), "notes": receipt_learning.list_notes()})
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
            guidance = receipt_learning.guidance(notes=receipt_learning.notes_for_prompt())
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
            feedback = body.get("feedback")
            if not isinstance(feedback, str) or not feedback.strip():
                raise ValueError("FEEDBACK_REQUIRED")
            known = [_known_line(c) for c in load(path)["candidates"] if c.get("image_sha") == sha]
            guidance = receipt_learning.guidance(notes=receipt_learning.notes_for_prompt(), known=known,
                                                 feedback=feedback)
            try:
                # A separate key: a re-analysis is always a new run, never the earlier result for the photo.
                state = receipt_vision_jobs.submit(sha, _images_dir(path) / f"{sha}.bin", _recognizer(guidance, lesson=True),
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
            sha = body.get("image", "")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("IMAGE_NOT_FOUND")
            job_id = body.get("job_id", "")
            if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
                raise ValueError("VISION_JOB_NOT_READY")
            handler._send_json(learn_from_job(path, image=sha, job_id=job_id))
        elif parsed.path == "/api/receipts/learn/delete":
            handler._send_json(receipt_learning.delete_note(str(body.get("id", ""))))
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
            if set(body) - {"identity", "note", "merchant", "date", "total_jpy", "total_original", "payment", "trip_id", "payee", "category", "expected_version"}:
                raise ValueError("FIELD_NOT_EDITABLE")
            changes = {k: body[k] for k in ("merchant", "date", "total_jpy", "total_original", "payment", "trip_id", "payee", "category") if k in body}
            result = edit(path, identity=str(body.get("identity", "")), changes=changes,
                          note=str(body.get("note", "")), valid_trips=_trip_ids(board),
                          card_rows_list=card_rows(board), expected_version=body.get('expected_version'))
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
    classified = bool(candidate.get("payee") and candidate.get("category"))
    source = (f"<a href='/api/receipts/image/{html.escape(candidate['image_sha'])}' target='_blank' rel='noopener'>원본 사진</a>"
              if candidate.get('image_sha') else '수동 입력')
    return (
        f"<tr data-version='{candidate_version(candidate)}' data-currency='{candidate.get('currency', 'JPY')}' "
        f"data-group-id='{html.escape(candidate.get('group_id') or '')}' data-saved-trip='{html.escape(candidate.get('trip_id') or '')}'>"
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
        f"<td data-label='원화' data-amount>{amount}</td><td data-label='상태' data-state>{html.escape(MESSAGES.get(candidate.get('hold'), candidate.get('hold')) or ('분류됨' if classified else '분류 확인 필요'))}</td>"
        f"<td data-label='분류'><label>지급처<input data-payee='{identity}' aria-label='지급처' value='{html.escape(candidate.get('payee') or '')}' placeholder='지급처'></label>"
        f"<label>비용 분류<input data-category='{identity}' aria-label='비용 분류' value='{html.escape(candidate.get('category') or '')}' placeholder='식비·숙박비 등'></label>"
        "</td></tr>")


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


VISION_SCRIPT = r"""const visionChoices={currency:[['','통화 선택'],['JPY','엔화 JPY'],['KRW','원화 KRW']],payment:[['','결제수단 선택'],['cash','현금'],['private_card','개인카드'],['corporate_card','법인카드']]};
const selectedTrip=document.getElementById('selected-trip');
try{const requested=new URLSearchParams(location.search).get('trip');const old=requested||sessionStorage.getItem('cost-receipt-trip');if(old&&[...selectedTrip.options].some(o=>o.value===old))selectedTrip.value=old;}catch{}
const syncTrip=()=>{document.getElementById('copy-trip').value=selectedTrip.value;
if(selectedTrip.value){const url=new URL(location.href);url.searchParams.set('trip',selectedTrip.value);history.replaceState(null,'',url.pathname+url.search+url.hash);document.querySelectorAll('a.work-back').forEach(a=>a.href='/board?'+new URLSearchParams({tab:selectedTrip.value}))}};
syncTrip();
selectedTrip.onchange=()=>{try{sessionStorage.setItem('cost-receipt-trip',selectedTrip.value)}catch{};syncTrip()};
const pendingKey='cost-receipt-pending';
let pending=[];
try{pending=JSON.parse(sessionStorage.getItem(pendingKey)||'[]')}catch{pending=[]}
const storePending=()=>{try{sessionStorage.setItem(pendingKey,JSON.stringify(pending))}catch{say('분석 결과를 임시 저장하지 못했습니다. 이 화면에서 바로 등록해 주세요.')}};
const photoNumber=sha=>{const b=document.querySelector('[data-image-sha="'+sha+'"]');return b?b.dataset.photoIndex:'?'};
const setPhotoState=(sha,text)=>{const el=document.querySelector('[data-photo-state="'+sha+'"]');if(el)el.textContent=text};
const fieldInput=(type,value,placeholder,label)=>{const input=document.createElement('input');input.type=type;input.value=value??'';input.placeholder=placeholder;input.setAttribute('aria-label',label);return input};
const fieldSelect=(choices,value,label)=>{const select=document.createElement('select');select.setAttribute('aria-label',label);for(const [v,t] of choices){const option=document.createElement('option');option.value=v;option.textContent=t;select.append(option)}select.value=value||'';return select};
const receiptCard=(group,index,receipt)=>{
 const card=document.createElement('article');card.className='receipt-card';card.dataset.key=group.sha+'|'+index;
 const include=document.createElement('input');include.type='checkbox';include.checked=receipt.include!==false;
 const top=document.createElement('label');top.className='card-top';top.append(include,' 등록에 포함');
 const merchant=fieldInput('text',receipt.merchant,'상호 (읽히지 않으면 직접 입력)','상호');
 const amount=fieldInput('number',receipt.amount,'금액','금액');amount.inputMode='numeric';amount.className='amount-input';
 const date=fieldInput('text',receipt.date,'날짜 2026-10-01','날짜');
 const currency=fieldSelect(visionChoices.currency,receipt.currency,'통화');
 const payment=fieldSelect(visionChoices.payment,receipt.payment,'결제수단');
 const row2=document.createElement('div');row2.className='row2';row2.append(date,currency,payment);
 const error=document.createElement('p');error.className='card-error';error.setAttribute('role','alert');
 const remove=document.createElement('button');remove.type='button';remove.className='remove';remove.textContent='이 후보 제외';
 remove.onclick=()=>{group.receipts=group.receipts.filter(r=>r!==receipt);if(!group.receipts.length)pending=pending.filter(g=>g!==group);storePending();renderPending()};
 const sync=()=>{Object.assign(receipt,{include:include.checked,merchant:merchant.value.trim()||null,date:date.value.trim()||null,
   amount:amount.value===''?null:Number(amount.value),currency:currency.value||null,payment:payment.value||null});storePending()};
 for(const control of [include,merchant,amount,date,currency,payment]){control.addEventListener('change',sync);control.addEventListener('input',sync)}
 card.append(top,merchant,amount,row2,error,remove);
 return card;
};
const renderPending=()=>{
 const box=document.getElementById('vision-results');if(!box)return;
 box.replaceChildren();
 for(const group of pending){
  const section=document.createElement('div');section.className='result-group';
  const head=document.createElement('h3');
  head.textContent='사진 '+photoNumber(group.sha)+(group.kind==='rescan'?' · 다시 찾은 영수증 ':' · 분석 결과 ')+group.receipts.length+'건';
  section.append(head);
  group.receipts.forEach((receipt,index)=>section.append(receiptCard(group,index,receipt)));
  box.append(section);
 }
 if(pending.length){const go=document.createElement('button');go.type='button';go.id='vision-register';go.className='primary';
  go.textContent='선택한 영수증 등록';go.onclick=registerPending;box.append(go)}
};
const pollJob=async(state,label)=>{const t0=Date.now();
 while(state.status==='queued'||state.status==='running'){
  if(Date.now()-t0>420000)throw new Error('인식 시간이 길어지고 있어요. 잠시 후 다시 시도해 주세요.');
  say(label+' 분석 중 · '+Math.round((Date.now()-t0)/1000)+'초 경과');
  await new Promise(r=>setTimeout(r,2000));
  state=await fetch('/api/receipts/vision/'+state.job_id,{headers:{'X-CSRF-Token':csrf}}).then(readResponse);
 }
 return state};
const jobFailure=state=>state.code==='VISION_BUSY'?'이미 분석 중인 사진이 많아요. 잠시 후 다시 눌러 주세요.':
 state.code==='VISION_ALL_MODELS_UNAVAILABLE'?'무료 AI 모델을 사용할 수 없습니다. 직접 입력해 주세요.':'Muse 인식에 실패했습니다. 직접 입력해 주세요.';
const visionGo=document.getElementById('vision-go');
if(visionGo)visionGo.onclick=async()=>{
 if(receiptBusy)return;
 if(!selectedTrip.value){say('여행을 먼저 선택하세요.');return}
 const shas=[...document.querySelectorAll('.photo-check:checked')].map(c=>c.value);
 if(!shas.length){say('분석할 사진을 체크하세요.');return}
 receiptBusy=true;const restore=lockControls();const failed=[];let found=0;
 try{
  for(const [i,sha] of shas.entries()){
   const label='사진 '+photoNumber(sha)+' ('+(i+1)+'/'+shas.length+')';
   setPhotoState(sha,'분석 중');
   try{
    const state=await pollJob(await post('/api/receipts/vision',{image:sha}),label);
    if(state.status!=='done')throw new Error(jobFailure(state));
    const receipts=state.result.receipts.map(r=>({merchant:r.merchant,date:r.date,amount:r.amount,currency:r.currency,payment:r.payment,category:r.category_hint,reading:r.reading,include:true}));
    found+=receipts.length;
    setPhotoState(sha,receipts.length?'후보 '+receipts.length+'건':'인식된 영수증 없음');
    if(receipts.length){pending.push({sha,kind:'analysis',jobId:state.job_id,receipts});storePending();renderPending()}
   }catch(error){failed.push(label+' · '+(error.message||'실패'));setPhotoState(sha,'분석 실패')}
  }
  say((failed.length?'분석을 마쳤습니다. 실패한 사진: '+failed.join(' / ')+' ':'분석을 마쳤습니다. ')+(found?'결과를 확인한 뒤 등록하세요.':'인식된 영수증이 없습니다. 직접 입력할 수 있습니다.'));
 }finally{restore();receiptBusy=false}
};
const cardError=(group,index,message)=>{const card=document.querySelector('[data-key="'+group.sha+'|'+index+'"]');if(card)card.querySelector('.card-error').textContent=message};
const registerPending=async()=>{
 if(receiptBusy)return;
 const trip=selectedTrip.value;
 if(!trip){say('여행을 먼저 선택하세요.');return}
 const plan=[];
 for(const group of pending){const items=group.receipts.map((r,i)=>({r,i})).filter(({r})=>r.include!==false);
  for(const {r,i} of items){if(!r.currency){cardError(group,i,'통화를 선택해 주세요.');say('통화를 선택한 뒤 등록해 주세요.');return}
   if(!r.merchant&&!r.date&&r.amount==null){cardError(group,i,'상호·날짜·금액 중 하나는 입력해 주세요.');say('등록할 내용이 없는 후보가 있습니다.');return}}
  if(items.length)plan.push({group,items})}
 if(!plan.length){say('등록할 영수증을 하나 이상 선택하세요.');return}
 receiptBusy=true;const restore=lockControls();let added=0;
 try{
  for(const {group,items} of plan){
   say('사진 '+photoNumber(group.sha)+'의 영수증을 등록하고 있습니다.');
   const regions=items.map(({r})=>({box:null,merchant:r.merchant,date:r.date,currency:r.currency,total:r.amount,payment:r.payment,confidence:1,
     ordinal:r.ordinal,reading:r.reading,category:r.category}));
   const result=await post('/api/receipts/scan',{image:group.sha,trip_id:trip,regions});
   added+=result.added;
   if(group.kind==='rescan'&&group.jobId){try{await post('/api/receipts/learn',{image:group.sha,job_id:group.jobId})}catch{}}
   group.receipts=group.receipts.filter(r=>r.include===false);
  }
  pending=pending.filter(g=>g.receipts.length);storePending();
  say('영수증 '+added+'건을 등록했습니다. 후보를 새로 불러옵니다.');
  location.reload();
 }catch(error){pending=pending.filter(g=>g.receipts.length);storePending();renderPending();say(error.message||'등록하지 못했습니다. 다시 시도해 주세요.')}
 finally{restore();receiptBusy=false}
};
const rescanGo=document.getElementById('rescan-go');
if(rescanGo)rescanGo.onclick=async()=>{
 if(receiptBusy)return;
 const sha=document.getElementById('image-sha').value;
 if(!sha){say('사진을 먼저 선택해 주세요.');return}
 if(!selectedTrip.value){say('여행을 먼저 선택하세요.');return}
 const feedback=document.getElementById('feedback').value.trim();
 if(!feedback){say('빠진 점이나 잘못된 점을 적어 주세요.');return}
 receiptBusy=true;const restore=lockControls();
 try{
  const state=await pollJob(await post('/api/receipts/vision/rescan',{image:sha,feedback}),'다시 인식');
  if(state.status!=='done')throw new Error(jobFailure(state));
  const found=await post('/api/receipts/vision/new',{image:sha,job_id:state.job_id});
  if(found.new.length){
   pending.push({sha,kind:'rescan',jobId:state.job_id,receipts:found.new.map(r=>({merchant:r.merchant,date:r.date,amount:r.amount,
     currency:r.currency,payment:r.payment,category:r.category_hint,reading:r.reading,ordinal:r.ordinal,include:true}))});
   storePending();renderPending();document.getElementById('feedback').value='';
  }
  say(found.new.length?'새 후보 '+found.new.length+'건을 찾았습니다. 확인한 뒤 등록하세요.':'새로 찾은 영수증이 없습니다. 메모는 저장하지 않았습니다.');
 }catch(error){say(error.message||'다시 인식에 실패했습니다.')}
 finally{restore();receiptBusy=false}
};
document.querySelectorAll('[data-image-sha]').forEach(b=>b.addEventListener('click',()=>{const t=document.getElementById('rescan-target');if(t)t.textContent='사진 '+b.dataset.photoIndex}));
renderPending();
"""

LEARNING_SCRIPT = r"""const renderNotes=async()=>{const list=document.getElementById('learn-list');if(!list)return;const body=await fetch('/api/receipts/learn',{headers:{'X-CSRF-Token':csrf}}).then(readResponse);list.replaceChildren();const add=text=>{const li=document.createElement('li');li.textContent=text;list.append(li)};if(!body.enabled){add('학습 저장 위치가 설정되지 않았습니다.');return}if(!body.notes.length){add('저장된 학습 메모가 없습니다.');return}for(const note of body.notes){const li=document.createElement('li');li.textContent=note.text+' ';const button=document.createElement('button');button.type='button';button.textContent='삭제';button.onclick=()=>save(()=>post('/api/receipts/learn/delete',{id:note.id}),()=>renderNotes().catch(()=>{}));li.append(button);list.append(li)}};
if(document.getElementById('learn-list'))renderNotes().catch(()=>{});
"""

PAGE_CSS = r"""*{box-sizing:border-box}
:root{--bg:#F8FAFC;--paper:#FFFFFF;--ink:#0F172A;--mut:#475569;--line:#E2E8F0;--line2:#F1F5F9;--line-strong:#D0D5DD;--hover:#F8FAFC;--focus:#2266F5;--sel:#ECF5EF;--grn:#1C7A52;--grn-dk:#166444;--grn-lt:#F1F7F3;--warn:#B54708;--neg:#B42318;--bad:#B42318}
@media(prefers-color-scheme:dark){:root{--bg:#0F172A;--paper:#1E293B;--ink:#F8FAFC;--mut:#94A3B8;--line:#334155;--line2:#334155;--line-strong:#475569;--hover:#334155;--focus:#2266F5;--sel:#1E3A5F;--grn:#1C7A52;--grn-dk:#166444;--grn-lt:#F1F7F3;--warn:#B54708;--neg:#B42318;--bad:#B42318}}
body{font-family:system-ui,sans-serif;margin:0;padding:12px 12px 80px;background:var(--bg);color:var(--ink);font-size:16px;overflow-x:hidden}
h1{font-size:22px;margin:6px 0 10px}h2{font-size:17px;margin:0 0 8px}h3{font-size:15px;margin:6px 0}
section,details{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0;min-width:0}
details>summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-weight:600}
.hint{font-size:13px;color:var(--mut);margin:6px 0 10px}
input,select,button,.work-back{font:inherit;max-width:100%}
input,select{min-height:44px;padding:8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--paper)}
input[type=checkbox]{width:22px;height:22px;min-height:22px;min-width:22px;padding:0;margin:0;accent-color:var(--grn-dk)}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
button,.work-back{min-height:44px;padding:10px 14px;border:1px solid var(--line-strong);border-radius:8px;background:var(--paper);color:var(--ink);cursor:pointer;display:inline-flex;align-items:center}
button.primary{background:var(--grn);color:#fff;border-color:var(--grn);width:100%;margin-top:10px}
button .ic{width:16px;height:16px;margin-right:6px;pointer-events:none}
.work-back{color:var(--grn-dk);text-decoration:none}
#status:not(:empty){position:sticky;top:0;z-index:10;background:var(--sel);color:var(--ink);padding:12px;border:1px solid var(--line);border-radius:8px;font-weight:600;margin-bottom:10px}
.photo-strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100px,100%),1fr));gap:10px;margin-top:10px}
.photo{border:1px solid var(--line);border-radius:8px;padding:6px;background:var(--paper);display:flex;flex-direction:column;gap:4px;min-width:0}
.photo>button{padding:0;border:0;min-height:0;width:100%;background:none}
.photo img{width:100%;height:auto;border-radius:6px;display:block}
.photo button[aria-pressed=true] img{outline:2px solid var(--grn-dk);outline-offset:2px}
.photo-pick{font-size:14px;display:flex;align-items:center;gap:6px;min-height:44px}
.photo-state{font-size:12px;color:var(--mut)}
.result-group{border-top:1px solid var(--line);padding-top:8px;margin-top:8px}
.receipt-card{border:1px solid var(--line-strong);border-radius:10px;padding:12px;margin:8px 0;background:var(--paper);display:grid;gap:8px;min-width:0}
.receipt-card input:not([type=checkbox]),.receipt-card select{width:100%;min-width:0}
.receipt-card .amount-input{font-size:22px;font-weight:700;text-align:right}
.receipt-card .row2{display:grid;grid-template-columns:1fr;gap:8px}
.card-top{display:flex;align-items:center;gap:6px;min-height:44px;font-size:14px}
.card-error{color:var(--neg);font-size:14px;margin:0}
.remove{color:var(--neg);justify-self:start}
.rescan{border-top:1px solid var(--line);margin-top:12px;padding-top:10px}
.rescan textarea{width:100%;min-height:72px;font:inherit;padding:8px;border:1px solid var(--line-strong);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px;background:var(--paper)}td,th{border:1px solid var(--line);padding:8px;text-align:left}
td{vertical-align:top}td label{display:block;font-size:12px;margin:6px 0}
td input,td select{display:block;width:100%;min-width:0}
@media(width < 760px){table,tbody,tr,td{display:block;width:100%}table{background:transparent}
thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
tr{border:1px solid var(--line);border-radius:8px;background:var(--paper);padding:10px;margin:0 0 12px;min-width:0}
td{border:0;border-bottom:1px solid var(--line2);padding:8px 0;overflow-wrap:break-word}td:last-child{border:0}
td::before{content:attr(data-label);display:block;font-size:13px;font-weight:600;margin-bottom:6px;overflow-wrap:break-word}
input,select,button{min-height:44px;font-size:16px}td button{width:100%}}
@media(min-width:760px){body{margin:16px auto;max-width:960px;padding:0 16px 80px}.receipt-card .row2{grid-template-columns:1fr 1fr 1fr}}
tr[hidden]{display:none!important}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}"""


def _photo_strip(data: dict) -> str:
    counts = {}
    for candidate in data['candidates']:
        if candidate.get('image_sha'):
            counts[candidate['image_sha']] = counts.get(candidate['image_sha'], 0) + 1
    latest = data['images'][-1] if data['images'] else None
    shown = data['images'][-12:]
    first = max(1, len(data['images']) - len(shown) + 1)
    items = []
    for index, sha in enumerate(shown, start=first):
        count = counts.get(sha, 0)
        state = f'후보 {count}건' if count else '분석 전'
        checked = '' if count else ' checked'
        pressed = 'true' if sha == latest else 'false'
        items.append(
            "<div class='photo'>"
            f"<button type='button' data-image-sha='{sha}' data-photo-index='{index}' aria-pressed='{pressed}' "
            f"aria-label='사진 {index} 선택'><img src='/api/receipts/image/{sha}' alt='사진 {index}'></button>"
            f"<label class='photo-pick'><input type='checkbox' class='photo-check' value='{sha}'{checked}> 분석</label>"
            f"<span class='photo-state' data-photo-state='{sha}'>{state}</span></div>")
    return "".join(items)


def _rescan_html(target: str) -> str:
    return ("<details class='rescan'><summary>빠진 영수증 다시 찾기</summary>"
            "<p class='hint'>빠진 점이나 잘못된 점을 적고 다시 인식하세요. 기존 후보는 바뀌지 않고, 새로 찾은 영수증만 위에 보여 줍니다.</p>"
            f"<p class='hint'>다시 인식할 사진: <strong id='rescan-target'>{target}</strong> </p>"
            "<textarea id='feedback' maxlength='300' placeholder='예: 6장인데 5장만 찾았어. 작은 승선권 하나 더 찾아'></textarea>"
            "<button type='button' id='rescan-go'>다시 인식</button></details>")


def _notes_html() -> str:
    return ("<details><summary>저장된 학습 메모</summary>"
            "<p class='hint'>확인된 피드백만 자동으로 저장되며, 다음 분석에 참고됩니다.</p>"
            "<ul id='learn-list'></ul></details>")


def render_html(data: dict, csrf: str, trips: list | None = None) -> str:
    trips = trips or []
    trip_options = "".join(f"<option value='{html.escape(t['id'])}'>{html.escape(t['name'])}</option>"
                            for t in trips)
    rows = "".join(_row_html(c, trips) for c in data["candidates"]) or '<tr><td colspan="5">등록된 후보가 없습니다. 사진을 분석하거나 직접 입력하세요.</td></tr>'
    holds = ''.join(_hold_html(h) for h in data['holds']) or '<li>보류된 영수증이 없습니다.</li>'
    latest = data['images'][-1] if data['images'] else ''
    ai = opencode_receipt_vision.enabled()
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
        "const updateCandidate=(button,result)=>{const row=button.closest('tr');row.dataset.version=result.version;row.dataset.savedTrip=result.trip_id||'';"
        "for(const [field,key] of [['trip','trip_id'],['merchant','merchant'],['date','date'],['total','total_jpy'],"
        "['payment','payment'],['payee','payee'],['category','category']]){const input=row.querySelector('[data-'+field+']');"
        "input.value=(field==='total'&&result.currency==='KRW'?result.total_original:result[key])??'';originalValues.set(input,input.value)}"
        "row.querySelector('[data-amount]').textContent=result.amount_krw==null?'':result.amount_krw.toLocaleString('ko-KR')+'원';"
        "row.querySelector('[data-state]').textContent=result.hold?message(result.hold):(result.payee&&result.category?'분류됨':'분류 확인 필요');"
        "say('영수증 변경을 저장했습니다.')};"
        "const save=async(action,onSaved)=>{if(receiptBusy)return;"
        "if(!onSaved&&[...document.querySelectorAll(reviewFields)].some(input=>input.value!==originalValues.get(input))){"
        "say('영수증의 변경을 먼저 저장해 주세요. 입력값은 유지합니다.');return}"
        "receiptBusy=true;const restore=lockControls();"
        "say('저장하고 있습니다.');try{const result=await action();if(onSaved){try{onSaved(result)}catch{"
        "say('저장은 완료됐지만 화면 갱신에 실패했습니다. 입력값을 보관하고 화면을 다시 열어 주세요.')}}else location.reload()}"
        "catch(error){say(error.message||'저장하지 못했습니다. 다시 시도해 주세요.')}"
        "finally{restore();receiptBusy=false;document.dispatchEvent(new Event('receipt-workflow-change'))}};"
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
        "const editBody=b=>{const id=b.dataset.edit;return {identity:id,expected_version:b.closest('tr').dataset.version,trip_id:val('data-trip',id),merchant:val('data-merchant',id),date:val('data-date',id),payee:val('data-payee',id),category:val('data-category',id),"
        "[b.closest('tr').dataset.currency==='KRW'?'total_original':'total_jpy']:Number(val('data-total',id)),payment:val('data-payment',id)}};"
        "document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>save(()=>post('/api/receipts/edit',editBody(b)),result=>updateCandidate(b,result)));"
        "document.getElementById('group-go').onclick=()=>{const selected=[...document.querySelectorAll('[data-group-select]:checked')];"
        "if(selected.length<2){say('묶을 영수증을 두 장 이상 선택해 주세요.');return}"
        "const identities=selected.map(e=>e.dataset.groupSelect),expected_versions=Object.fromEntries(selected.map(e=>[e.dataset.groupSelect,e.closest('tr').dataset.version]));"
        "save(()=>post('/api/receipts/group',{identities,expected_versions,trip_id:document.getElementById('selected-trip').value}))};"
        "document.getElementById('ungroup-go').onclick=()=>{const groups=[...new Set([...document.querySelectorAll('[data-group-select]:checked')].map(e=>e.closest('tr').dataset.groupId).filter(Boolean))];"
        "if(groups.length!==1){say('해제할 묶음 하나를 선택해 주세요.');return}save(()=>post('/api/receipts/ungroup',{group_id:groups[0]}))};"
        "document.getElementById('r-currency').onchange=()=>{document.getElementById('r-total').placeholder='금액('+document.getElementById('r-currency').value+')'};"
        "document.getElementById('copy-tsv').onclick=async()=>{if(receiptBusy)return;"
        "const selection=document.getElementById('copy-trip');const trip=selection.value;if(!trip){say('복사할 여행을 고르세요');return}"
        "const dirty=[...document.querySelectorAll('tr[data-version]')].some(row=>{const assigned=row.querySelector('[data-trip]');"
        "return (assigned.value===trip||originalValues.get(assigned)===trip)&&"
        "[...row.querySelectorAll(reviewFields)].some(input=>input.value!==originalValues.get(input))});"
        "if(dirty){say('저장하지 않은 변경이 있습니다. 수정 버튼으로 저장한 뒤 복사해 주세요.');return}"
        "const key='gcopy-trip:'+trip;let previous=null;try{previous=localStorage.getItem(key)}catch{if(!confirm('복사 이력을 읽을 수 없습니다. 이미 Google에 붙여넣었는지 확인해 주세요. 중복 붙여넣기에 주의하고 계속 복사할까요?'))return;}"
        "if(previous&&!confirm('이 여행은 '+previous+'에 이미 구글 시트용으로 복사했습니다. 카드와 영수증을 각각 복사했다면 중복 붙여넣기에 주의하세요. 계속할까요?'))return;"
        "receiptBusy=true;const restore=lockControls();try{const response=await fetch('/api/receipts/tsv?trip='+encodeURIComponent(trip));"
        "const x=await readResponse(response);"
        "if(!x.row_count){say('복사할 영수증이 없습니다. 보류 '+x.held.length+'건');return}"
        "await navigator.clipboard.writeText(x.tsv);let historyWarning='';try{localStorage.setItem(key,new Date().toLocaleString('ko-KR'))}catch{historyWarning=' 복사 이력을 저장하지 못했습니다. 중복 붙여넣기에 주의해 주세요.'}"
        "say('영수증 '+x.row_count+'행을 클립보드에 복사했습니다. 구글 시트에 붙여넣은 뒤에만 반영됩니다.'+historyWarning)}"
        "catch(error){say(error.message||'복사하지 못했습니다. 다시 시도해 주세요')}finally{restore();receiptBusy=false}};")
    ocr = ("<p>Windows OCR로 사진의 글자를 읽습니다. 인식값은 참고값이며 금액과 결제수단을 확인해야 합니다.</p>"
           "<label>인식 언어<select id='ocr-language'><option value='ja'>일본어</option><option value='ko'>한국어</option></select></label> "
           f"<button type='button' id='ocr-go'>{ui_icons.icon('search')}선택한 사진 글자 읽기</button>"
           "<label>인식한 글자<textarea id='ocr-text' readonly style='display:block;width:100%;min-height:120px'></textarea></label>"
           if local_receipt_ocr.enabled() else
           "<p>자동 추출은 연결되지 않았습니다. 사진을 보면서 영수증별로 상호·날짜·통화·금액을 입력해 주세요.</p>")
    ai_section = ("<section id='step-ai'><h2>3. AI 분석</h2>"
                  "<p class='hint'>체크한 사진을 Muse가 한 장씩 읽습니다. 원본 사진은 무료 AI 모델로 전송되며, 결과는 등록 전까지 회계에 반영되지 않습니다.</p>"
                  "<button type='button' id='vision-go'>체크한 사진 분석</button>"
                  "<div id='vision-results' aria-live='polite'></div>"
                  + _rescan_html(f"사진 {len(data['images'])}" if data['images'] else "사진을 먼저 고르세요")
                  + "</section>") if ai else ""
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>영수증 정리</title>"
            f"<style>{PAGE_CSS}</style></head><body>"
            f"<nav aria-label='장부 이동'><a class='work-back' href='/board'>{ui_icons.icon('chevron-left')}장부로 돌아가기</a></nav>"
            "<h1>영수증 정리</h1><p id='status' role='status' aria-live='polite'></p>"
            "<section id='step-trip'><h2>1. 여행 선택</h2><label>검토할 여행"
            "<select id='selected-trip'><option value=''>여행을 먼저 선택하세요</option>" + trip_options +
            "</select></label></section>"
            "<p><a href='#other-methods' id='receipt-manual-open'>사진 없이 직접 입력</a></p>"
            "<section id='step-photos'><h2>2. 사진</h2>"
            "<input id='img-file' type='file' multiple accept='image/*'> "
            f"<button type='button' id='img-go'>{ui_icons.icon('upload')}사진 등록</button>"
            f"<input type='hidden' id='image-sha' value='{latest}'>"
            "<p class='hint'>iPhone 사진(HEIC 포함)이나 큰 사진은 업로드 전에 JPEG로 바꿉니다. 분석할 사진을 체크하세요.</p>"
            f"<div class='photo-strip'>{_photo_strip(data)}</div></section>"
            + ai_section +
            "<section id='step-review'><h2>4. 후보 검토</h2>"
            "<p class='hint'>분류가 끝난 영수증만 지출로 복사됩니다.</p>"
            "<p id='receipt-visible-count' role='status'></p>"
            "<table><thead><tr><th>상호·날짜</th><th>금액·결제</th><th>원화</th><th>상태</th><th>분류</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></section>"
            "<details id='step-group'><summary>승선권 등 선택 묶기</summary>"
            "<p class='hint'>같은 여행·날짜·업체·결제수단의 영수증 여러 장을 선택하면 하나의 지출 행으로 합산됩니다.</p>"
            "<button id='group-go' type='button'>선택한 영수증을 한 지출로 묶기</button> "
            "<button id='ungroup-go' type='button'>선택한 묶음 해제</button></details>"
            "<section><h2>6. 구글 지출 7열 복사</h2>"
            f"<label>복사할 여행 <select id='copy-trip'>{trip_options}</select></label>"
            f"<button type='button' id='copy-tsv' class='primary'>{ui_icons.icon('copy')}구글 지출 7열 복사</button>"
            f"<h3>보류</h3><ul>{holds}</ul></section>"
            "<details id='other-methods'><summary>직접 입력 / 다른 방법</summary>"
            + ocr +
            "<div style='margin-top:12px'><h3>직접 입력</h3>"
            "<input id='r-merchant' placeholder='상호'> <input id='r-date' placeholder='2027-08-03'> "
            "<label>통화<select id='r-currency'><option value=''>통화 확인</option><option value='JPY' selected>엔화 JPY</option><option value='KRW'>원화 KRW</option></select></label> "
            "<input id='r-total' type='number' placeholder='금액(JPY)'> "
            "<select id='r-payment'><option value=''>결제수단 확인</option><option value='cash' selected>현금</option><option value='private_card'>개인카드</option>"
            "<option value='corporate_card'>법인카드</option></select> "
            f"<button type='button' id='region-go'>{ui_icons.icon('pencil')}영수증 추가</button></div>"
            + (_notes_html() if ai else "") +
            "</details>"
            f"<script>{script}{VISION_SCRIPT}{LEARNING_SCRIPT}{WORKFLOW_SCRIPT}</script></body></html>")


WORKFLOW_SCRIPT = r"""(()=>{
const byId=id=>document.getElementById(id),trip=byId('selected-trip');
const update=()=>{
 if(receiptBusy)return;
 const checked=[...document.querySelectorAll('[data-group-select]:checked')],photos=document.querySelectorAll('.photo-check:checked').length;
 const state=(id,enabled)=>{const el=byId(id);if(el)el.disabled=!enabled};
 state('img-go',byId('img-file').files.length>0);
 state('vision-go',!!trip.value&&photos>0);
 state('rescan-go',!!trip.value&&!!byId('image-sha').value);
 state('ocr-go',!!byId('image-sha').value);
 state('group-go',!!trip.value&&checked.length>=2);
 const groups=new Set(checked.map(e=>e.closest('tr').dataset.groupId).filter(Boolean));
 state('ungroup-go',groups.size===1);
 const copy=byId('copy-trip').value;
 const candidates=[...document.querySelectorAll('tr[data-version]')];
 candidates.forEach(row=>row.hidden=!!trip.value&&!!row.dataset.savedTrip&&row.dataset.savedTrip!==trip.value);
 const visible=candidates.filter(row=>!row.hidden).length;
 byId('receipt-visible-count').textContent=visible?visible+'건의 영수증 후보': '이 여행에 등록된 후보가 없습니다. 사진을 등록하거나 직접 입력하세요.';
 state('copy-tsv',!!copy&&candidates.some(row=>row.querySelector('[data-trip]').value===copy));
 byId('step-group').hidden=candidates.length===0;
};
document.addEventListener('change',update);document.addEventListener('receipt-workflow-change',update);
byId('receipt-manual-open').addEventListener('click',()=>{byId('other-methods').open=true;byId('r-merchant').focus()});
update();
})();"""
