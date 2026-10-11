"""Receipt candidates: image, regions, manual edit, confirm and copy. No OCR engine is used.

Routes stay off unless WEBLEDGER_RECEIPTS_STORE names a JSON store. A synthetic or real image is
stored as a file next to the store after a PNG or JPEG signature check. Regions and values are typed
by a person; the machine never reads the image. The /api/receipts/upload route answers 501 while no
OCR engine is approved. Every manual change keeps its history.
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
from pathlib import Path

from app import receipt_candidates as rc
from app.google_tsv import expense_tsv

ROUTES = ("/receipts", "/api/receipts", "/api/receipts/scan", "/api/receipts/confirm",
          "/api/receipts/edit", "/api/receipts/tsv", "/api/receipts/upload", "/api/receipts/image")
IMAGE_PATH = re.compile(r"^/api/receipts/image/([0-9a-f]{64})$")
# Matches the board's own request ceiling (5 MB), so a photo is refused at the same size either way.
IMAGE_LIMIT = 5 * 1024 * 1024
PAYMENTS = ("cash", "private_card", "corporate_card")
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
    'Failed to fetch': '연결하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.',
}
_STORE_LOCK = threading.RLock()


def _serialized(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _STORE_LOCK:
            return function(*args, **kwargs)
    return wrapped


def _candidate(stored: dict) -> rc.Candidate:
    return rc.Candidate(**{k: v for k, v in stored.items() if k in rc.Candidate.__dataclass_fields__})


def _validate_values(merchant, date, total) -> None:
    if not isinstance(merchant, str) or not merchant.strip():
        raise ValueError("FIELD_MISSING")
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("DATE_INVALID")
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise ValueError("DATE_INVALID") from None
    if type(total) is not int or total <= 0:
        raise ValueError("TOTAL_UNCLEAR")


def enabled() -> bool:
    return bool(os.environ.get("WEBLEDGER_RECEIPTS_STORE"))


def owns_route(path: str) -> bool:
    return path in ROUTES or IMAGE_PATH.match(path) is not None


def _store_path() -> Path:
    return Path(os.environ["WEBLEDGER_RECEIPTS_STORE"])


def _images_dir(store: Path) -> Path:
    return store.parent / "receipt-images"


def load(path: Path) -> dict:
    if not path.exists():
        return {"candidates": [], "holds": [], "images": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("images", [])
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
    if not target.exists():
        target.write_bytes(body)
    data = load(path)
    if sha not in data["images"]:
        data["images"].append(sha)
        _save(path, data)
    return {"sha256": sha, "bytes": len(body), "media_type": media}


def image_bytes(path: Path, sha: str) -> bytes:
    data = load(path)
    if sha not in data["images"]:
        raise KeyError("IMAGE_NOT_FOUND")
    return (_images_dir(path) / f"{sha}.bin").read_bytes()


def _regions(payload: dict) -> list[rc.Region]:
    if not isinstance(payload, dict):
        raise ValueError('INVALID_VALUE')
    raw = payload.get("regions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("REGIONS_REQUIRED")
    for region in raw:
        if not isinstance(region, dict):
            raise ValueError('REGION_INVALID')
        box = region.get('box')
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError('BOX_INVALID')
        confidence = region.get('confidence', 1.0)
        if (type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1):
            raise ValueError('CONFIDENCE_INVALID')
    image = str(payload.get("image") or "")
    # The page fingerprint is the picture and the regions typed on it, so the same entry sent again is one receipt.
    basis = json.dumps({"image": image, "regions": raw}, ensure_ascii=False, sort_keys=True)
    page_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    return [rc.Region(page_id=page_id, box=tuple(r["box"]), merchant=r.get("merchant"), date=r.get("date"),
                      currency=r.get("currency", "JPY"), total=r.get("total"), payment=r.get("payment"),
                      confidence=float(r.get("confidence", 1.0))) for r in raw]


def card_rows(board) -> list[dict]:
    """Corporate-card purchases in the database, the only card evidence a receipt may link to."""
    if board is None:
        return []
    try:
        rows = board.conn.execute(
            "SELECT transaction_id, COALESCE(NULLIF(approval_date,''), posting_date), merchant, foreign_amount"
            " FROM transactions WHERE transaction_kind='purchase' AND transaction_direction='purchase'"
            " AND duplicate_of IS NULL AND foreign_currency='JPY'").fetchall()
    except sqlite3.OperationalError:
        return []  # no card tables yet: there is no card evidence to link to
    return [{"transaction_id": tid, "date": date, "merchant": merchant, "original_jpy": amount}
            for tid, date, merchant, amount in rows]


@_serialized
def scan(path: Path, payload: dict, *, board=None) -> dict:
    data = load(path)
    regions = _regions(payload)
    if payload.get("image") and payload["image"] not in data["images"]:
        raise KeyError("IMAGE_NOT_FOUND")
    for region in regions:
        if region.confidence >= rc.MIN_CONFIDENCE and region.total is not None:
            _validate_values(region.merchant, region.date, region.total)
    known = {c["identity"] for c in data["candidates"]}
    # A card link comes from the server's own rows. Any card_rows the client sent are ignored.
    cards = card_rows(board)
    result = rc.build_candidates(regions, cards, known=known)
    by_identity = {rc._identity(region): region for region in regions}
    for hold in result['holds']:
        region = by_identity[hold['identity']]
        hold['region'] = {**region.__dict__, 'box': list(region.box)}
        if payload.get('image'):
            hold['image_sha'] = payload['image']
    duplicates = []
    added = 0
    resolved = set()
    for candidate in result["candidates"]:
        region = next(r for r in regions if rc._identity(r) == candidate.identity)
        stored = {**candidate.__dict__, "history": [], "hold": None, 'box': list(region.box)}
        _settle(stored, cards)
        if payload.get("image"):
            source_region = hashlib.sha256(json.dumps(
                [payload["image"], list(region.box)], sort_keys=True).encode()).hexdigest()
            stored["source_region"] = source_region
            stored.update(image_sha=payload['image'], box=list(region.box))
            if any(c.get("source_region") == source_region for c in data["candidates"]):
                duplicates.append({"identity": candidate.identity, "reason": "DUPLICATE_CONTENT", 'candidate': stored})
                continue
        # The same slip photographed twice, or entered twice, is one cost. A second copy waits for a person.
        if any(_signature(c) == _signature(stored) for c in data["candidates"]):
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
    return [r for r in card_rows_list
            if r["date"] == stored["date"] and r["merchant"] == stored["merchant"]
            and r.get("original_jpy") is not None and float(r["original_jpy"]) == float(stored["total_jpy"])]


def _settle(stored: dict, card_rows_list: list) -> None:
    """Re-derives the card link and the priced amount from the stored fields and the server's card rows."""
    if stored.get('card_transaction_id'):
        stored.setdefault('card_evidence_transaction_id', stored['card_transaction_id'])
    stored["hold"] = None
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
            stored["amount_krw"] = int(stored["total_jpy"]) * rc.JPY_TO_KRW


def _signature(candidate: dict) -> tuple:
    return (candidate["date"], candidate["merchant"].strip(), int(candidate["total_jpy"]))


@_serialized
def edit(path: Path, *, identity: str, changes: dict, note: str = "", valid_trips: set | None = None,
         card_rows_list: list | None = None) -> dict:
    """A person corrects what was typed. Card-linked receipts keep the card amount, so they cannot be re-priced."""
    data = load(path)
    for stored in data["candidates"]:
        if stored["identity"] != identity:
            continue
        allowed = {"merchant", "date", "total_jpy", "payment", "trip_id"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("FIELD_NOT_EDITABLE")
        _validate_values(changes.get("merchant", stored["merchant"]), changes.get("date", stored["date"]),
                         changes.get("total_jpy", stored["total_jpy"]))
        before = {k: stored.get(k) for k in changes}
        if "payment" in changes and changes["payment"] not in PAYMENTS:
            raise ValueError("PAYMENT_UNKNOWN")
        if "trip_id" in changes and changes["trip_id"] and changes["trip_id"] not in (valid_trips or set()):
            raise ValueError("TRIP_UNKNOWN")
        if (stored.get('card_transaction_id') or stored.get('card_evidence_transaction_id')) and any(
                key in changes and changes[key] != stored[key]
                for key in ('merchant', 'date', 'total_jpy', 'payment')):
            # Unlinking would turn the card purchase plus a cash receipt into two costs. Refused, not guessed.
            raise ValueError("CARD_LINKED_NOT_EDITABLE")
        for key, value in changes.items():
            stored[key] = int(value) if key == "total_jpy" else str(value).strip()
        others = [c for c in data["candidates"] if c["identity"] != identity]
        if any(_signature(c) == _signature(stored) for c in others):
            raise ValueError("DUPLICATE_CONTENT")
        _settle(stored, card_rows_list or [])
        if any(before[k] != stored.get(k) for k in changes):
            stored["payee"], stored["category"] = None, None
            stored.setdefault("history", []).append({"edit": before, "to": changes, "note": note})
        _save(path, data)
        return stored
    raise KeyError("CANDIDATE_NOT_FOUND")


@_serialized
def confirm(path: Path, *, identity: str, payee: str, category: str, note: str = "") -> dict:
    data = load(path)
    for stored in data["candidates"]:
        if stored["identity"] == identity:
            if stored.get('payee') == payee.strip() and stored.get('category') == category.strip():
                return stored
            candidate = _candidate(stored)
            candidate.history = list(stored["history"])
            rc.confirm(candidate, payee=payee, category=category, note=note)
            stored.update(payee=candidate.payee, category=candidate.category, history=candidate.history)
            _save(path, data)
            return stored
    raise KeyError("CANDIDATE_NOT_FOUND")


def tsv(path: Path, trip: str | None = None, *, card_rows_list: list | None = None) -> dict:
    data = load(path)
    if card_rows_list is not None:
        for stored in data['candidates']:
            _settle(stored, card_rows_list)
    candidates = [_candidate(c) for c in data["candidates"]]
    if not trip:
        raise ValueError("TRIP_REQUIRED")
    mine = [c for c, stored in zip(candidates, data["candidates"])
            if stored.get("trip_id") == trip and not stored.get('hold')]
    unassigned = [{"identity": c["identity"], "reason": "TRIP_UNASSIGNED"} for c in data["candidates"]
                  if not c.get("trip_id")]
    card_holds = [{"identity": c["identity"], "reason": c["hold"]} for c in data["candidates"]
                  if c.get("hold") and c.get("trip_id") == trip]
    result = expense_tsv(rc.to_expense_rows(mine), layout="rev")
    return {**result, "trip_id": trip,
            "held": result["held"] + data["holds"] + unassigned + card_holds}


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
        except (KeyError, OSError):
            handler._send_json({"code": "IMAGE_NOT_FOUND"}, 404)
        return True
    if parsed.path == "/api/receipts/upload":
        handler._send_json({"code": "OCR_ENGINE_NOT_APPROVED",
                            "message": "글자를 읽는 엔진이 승인되지 않았습니다. 영역과 값을 직접 입력하세요."}, 501)
        return True
    if raw is None:
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
        if parsed.path == "/api/receipts/scan":
            handler._send_json(scan(path, body, board=board))
        elif parsed.path == "/api/receipts/edit":
            if set(body) - {"identity", "note", "merchant", "date", "total_jpy", "payment", "trip_id"}:
                raise ValueError("FIELD_NOT_EDITABLE")
            changes = {k: body[k] for k in ("merchant", "date", "total_jpy", "payment", "trip_id") if k in body}
            handler._send_json(edit(path, identity=str(body.get("identity", "")), changes=changes,
                                    note=str(body.get("note", "")), valid_trips=_trip_ids(board),
                                    card_rows_list=card_rows(board)))
        elif parsed.path == "/api/receipts/confirm":
            handler._send_json(confirm(path, identity=str(body.get("identity", "")), payee=str(body.get("payee", "")),
                                       category=str(body.get("category", "")), note=str(body.get("note", ""))))
        else:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
    except KeyError as error:
        handler._send_json({"code": str(error.args[0]) if error.args else "NOT_FOUND"}, 404)
    except (ValueError, TypeError) as error:
        handler._send_json({"code": str(error) or "INVALID_VALUE"}, 400)
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
        "<tr>"
        f"<td>{source}<br><select data-trip='{identity}'><option value=''>여행 미배정</option>"
        + "".join(f"<option value='{html.escape(t['id'])}'{' selected' if t['id'] == candidate.get('trip_id') else ''}>"
                  f"{html.escape(t['name'])}</option>" for t in trips)
        + f"</select><input data-merchant='{identity}' value='{html.escape(candidate['merchant'])}'>"
        f"<input data-date='{identity}' value='{html.escape(candidate['date'])}'></td>"
        f"<td><input data-total='{identity}' value='{candidate['total_jpy']}' inputmode='numeric'>"
        f"<select data-payment='{identity}'>"
        + "".join(f"<option value='{p}'{' selected' if p == candidate['payment'] else ''}>{p}</option>" for p in PAYMENTS)
        + "</select>"
        f"<button type='button' data-edit='{identity}'>수정</button></td>"
        f"<td>{amount}</td><td>{html.escape(MESSAGES.get(candidate.get('hold'), candidate.get('hold')) or ('확정됨' if confirmed else '사람 확인 필요'))}</td>"
        f"<td><input data-payee='{identity}' value='{html.escape(candidate.get('payee') or '')}' placeholder='지급처'>"
        f"<input data-category='{identity}' value='{html.escape(candidate.get('category') or '')}' placeholder='내용'>"
        f"<button type='button' data-confirm='{identity}'>확정</button></td></tr>")


def _hold_html(hold: dict) -> str:
    candidate = hold.get('candidate') or hold.get('region') or {}
    amount = candidate.get('total_jpy', candidate.get('total'))
    currency = candidate.get('currency', 'JPY') or '통화 미확인'
    detail = (f"{candidate.get('merchant') or '상호 미확인'} · {candidate.get('date') or '날짜 미확인'} · "
              f"{amount if amount is not None else '금액 미확인'} {currency} · "
              if candidate else '')
    image = hold.get('image_sha') or candidate.get('image_sha')
    source = (f" <a href='/api/receipts/image/{html.escape(image)}' target='_blank' rel='noopener'>원본 사진</a>"
              if image else '')
    box = ' · 영역 ' + str(candidate['box']) if 'box' in candidate else ''
    return '<li>' + html.escape(detail + MESSAGES.get(hold['reason'], hold['reason']) + box) + source + '</li>'


def render_html(data: dict, csrf: str, trips: list | None = None) -> str:
    trips = trips or []
    trip_options = "".join(f"<option value='{html.escape(t['id'])}'>{html.escape(t['name'])}</option>"
                            for t in trips)
    rows = "".join(_row_html(c, trips) for c in data["candidates"]) or '<tr><td colspan="5">등록된 후보가 없습니다. 영수증 영역과 값을 입력해 주세요.</td></tr>'
    holds = ''.join(_hold_html(h) for h in data['holds']) or '<li>보류된 영수증이 없습니다.</li>'
    images = "".join(
        f"<button type='button' data-image-sha='{sha}' aria-pressed='{'true' if sha == data['images'][-1] else 'false'}' "
        f"style='max-width:30%'>사진 {index} 선택<img src='/api/receipts/image/{sha}' alt='등록한 영수증 사진' style='max-width:100%'></button>"
        for index, sha in enumerate(data['images'][-3:], start=max(1, len(data['images']) - 2)))
    script = (
        f"const csrf={json.dumps(csrf)};"
        f"const messages={json.dumps(MESSAGES)};const message=code=>messages[code]||code;"
        "const post=(p,b)=>fetch(p,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},"
        "body:JSON.stringify(b)}).then(r=>r.json().then(j=>{if(!r.ok)throw new Error(j.message||message(j.code));return j}));"
        "const say=t=>document.getElementById('status').textContent=message(t);"
        "const val=(name,id)=>document.querySelector('['+name+'=\"'+id+'\"]').value;"
        "const editableFields='[data-trip],[data-merchant],[data-date],[data-total],[data-payment]';"
        "const originalValues=new Map([...document.querySelectorAll(editableFields)].map(input=>[input,input.value]));"
        "document.querySelectorAll('[data-image-sha]').forEach(button=>button.onclick=()=>{"
        "document.getElementById('image-sha').value=button.dataset.imageSha;"
        "document.querySelectorAll('[data-image-sha]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));"
        "say('선택한 사진의 영역과 값을 입력해 주세요.')});"
        "document.getElementById('img-go').onclick=async()=>{const f=document.getElementById('img-file').files[0];"
        "if(!f){say('사진 파일을 고르세요');return}const button=document.getElementById('img-go');button.disabled=true;"
        "say('사진을 등록하고 있습니다.');try{const r=await fetch('/api/receipts/image',{method:'POST',"
        "headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':csrf},body:f});"
        "const j=await r.json();if(!r.ok)throw new Error(j.message||message(j.code));"
        "document.getElementById('image-sha').value=j.sha256;say('사진을 등록했습니다. 영역을 입력하세요.');location.reload()}"
        "catch(error){say(error.message||'사진을 등록하지 못했습니다. 다시 시도해 주세요.')}finally{button.disabled=false}};"
        "document.getElementById('region-go').onclick=()=>{const sha=document.getElementById('image-sha').value;"
        "const region={box:[1,2,3,4].map(i=>Number(document.getElementById('box'+i).value)),"
        "merchant:document.getElementById('r-merchant').value,date:document.getElementById('r-date').value,"
        "currency:'JPY',total:Number(document.getElementById('r-total').value),payment:document.getElementById('r-payment').value,confidence:1};"
        "post('/api/receipts/scan',{image:sha||undefined,regions:[region]}).then(()=>location.reload()).catch(e=>say(e.message))};"
        "document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{const id=b.dataset.edit;"
        "post('/api/receipts/edit',{identity:id,trip_id:val('data-trip',id),merchant:val('data-merchant',id),date:val('data-date',id),"
        "total_jpy:Number(val('data-total',id)),payment:val('data-payment',id)}).then(()=>location.reload()).catch(e=>say(e.message))});"
        "document.querySelectorAll('[data-confirm]').forEach(b=>b.onclick=()=>{const id=b.dataset.confirm;"
        "if([...b.closest('tr').querySelectorAll(editableFields)].some(input=>input.value!==originalValues.get(input))){"
        "say('금액·결제수단·여행 변경은 수정 버튼으로 먼저 저장한 뒤 확정해 주세요.');return}"
        "post('/api/receipts/confirm',{identity:id,payee:val('data-payee',id),category:val('data-category',id)})"
        ".then(()=>location.reload()).catch(e=>say(e.message))});"
        "document.getElementById('copy-tsv').onclick=async()=>{const button=document.getElementById('copy-tsv');"
        "const selection=document.getElementById('copy-trip');const trip=selection.value;if(!trip){say('복사할 여행을 고르세요');return}"
        "const key='gcopy-trip:'+trip;const previous=localStorage.getItem(key);"
        "if(previous&&!confirm('이 여행은 '+previous+'에 이미 구글 시트용으로 복사했습니다. 카드와 영수증을 각각 복사했다면 중복 붙여넣기에 주의하세요. 계속할까요?'))return;"
        "button.disabled=true;selection.disabled=true;try{const response=await fetch('/api/receipts/tsv?trip='+encodeURIComponent(trip));"
        "const x=await response.json();if(!response.ok)throw new Error(x.message||x.code);"
        "if(!x.row_count){say('복사할 확정 영수증이 없습니다. 보류 '+x.held.length+'건');return}"
        "await navigator.clipboard.writeText(x.tsv);let historyWarning='';try{localStorage.setItem(key,new Date().toLocaleString('ko-KR'))}catch{historyWarning=' 복사 이력을 저장하지 못했습니다. 중복 붙여넣기에 주의해 주세요.'}"
        "say('영수증 '+x.row_count+'행을 클립보드에 복사했습니다. 구글 시트에 붙여넣은 뒤에만 반영됩니다.'+historyWarning)}"
        "catch(error){say(error.message||'복사하지 못했습니다. 다시 시도해 주세요')}finally{button.disabled=false;selection.disabled=false}};")
    box_inputs = "".join(f"<input id='box{i}' type='number' value='0' aria-label='영역 {i}' style='width:4.5em'>"
                         for i in range(1, 5))
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>영수증 후보</title>"
            "<style>table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccc;padding:4px}"
            "@media(max-width:600px){table{display:block;overflow-x:auto}}</style></head><body>"
            "<h1>영수증 후보</h1>"
            "<section><h2>사진 등록</h2><input id='img-file' type='file' accept='image/png,image/jpeg'>"
            "<button type='button' id='img-go'>사진 등록</button>"
            f"<input type='hidden' id='image-sha' value='{data['images'][-1] if data['images'] else ''}'>"
            f"<p>최근 사진 중 입력할 사진을 선택해 주세요.</p><div>{images}</div></section>"
            "<section><h2>영역 입력</h2>"
            f"<p>사진 위치 (x0, y0, x1, y1): {box_inputs}</p>"
            "<input id='r-merchant' placeholder='상호'> <input id='r-date' placeholder='2027-08-03'> "
            "<input id='r-total' type='number' placeholder='금액(JPY)'> "
            "<select id='r-payment'><option value='cash'>현금</option><option value='private_card'>개인카드</option>"
            "<option value='corporate_card'>법인카드</option></select>"
            "<button type='button' id='region-go'>영역 추가</button></section>"
            "<h2>후보</h2>"
            "<table><thead><tr><th>상호·날짜</th><th>금액·결제</th><th>원화</th><th>상태</th><th>확정</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
            f"<h2>보류</h2><ul>{holds}</ul>"
            f"<p><label>복사할 여행 <select id='copy-trip'>{trip_options}</select></label> "
            "<button type='button' id='copy-tsv'>구글 지출 7열 복사</button> <span id='status' role='status'></span></p>"
            f"<script>{script}</script></body></html>")
