"""Receipt candidates: scan, review, confirm and copy. Synthetic-fed until an OCR engine is approved.

Routes stay off unless WEBLEDGER_RECEIPTS_STORE names a JSON store. The image upload route answers
501 OCR_ENGINE_NOT_APPROVED: no image is read or sent anywhere. Scans come in as the regions an
engine would report. Confirmation is always a person's action and is kept with history.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path

from app import receipt_candidates as rc
from app.google_tsv import expense_tsv

ROUTES = ("/receipts", "/api/receipts", "/api/receipts/scan", "/api/receipts/confirm",
          "/api/receipts/tsv", "/api/receipts/upload")


def enabled() -> bool:
    return bool(os.environ.get("WEBLEDGER_RECEIPTS_STORE"))


def owns_route(path: str) -> bool:
    return path in ROUTES


def _store_path() -> Path:
    return Path(os.environ["WEBLEDGER_RECEIPTS_STORE"])


def load(path: Path) -> dict:
    if not path.exists():
        return {"candidates": [], "holds": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _regions(payload: dict) -> list[rc.Region]:
    raw = payload.get("regions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("REGIONS_REQUIRED")
    # The page fingerprint is the content, so the same scan sent again has the same identities.
    page_id = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return [rc.Region(page_id=page_id, box=tuple(r["box"]), merchant=r.get("merchant"), date=r.get("date"),
                      currency=r.get("currency"), total=r.get("total"), payment=r.get("payment"),
                      confidence=float(r.get("confidence", 0))) for r in raw]


def scan(path: Path, payload: dict) -> dict:
    data = load(path)
    regions = _regions(payload)
    known = {c["identity"] for c in data["candidates"]}
    result = rc.build_candidates(regions, payload.get("card_rows", []), known=known)
    for candidate in result["candidates"]:
        data["candidates"].append({**candidate.__dict__, "history": []})
    seen = {h["identity"] for h in data["holds"]}
    data["holds"].extend(h for h in result["holds"] if h["identity"] not in seen)
    _save(path, data)
    return {"added": len(result["candidates"]), "holds": result["holds"]}


def confirm(path: Path, *, identity: str, payee: str, category: str, note: str = "") -> dict:
    data = load(path)
    for stored in data["candidates"]:
        if stored["identity"] == identity:
            candidate = rc.Candidate(**{k: v for k, v in stored.items() if k != "history"})
            candidate.history = list(stored["history"])
            rc.confirm(candidate, payee=payee, category=category, note=note)
            stored.update(payee=candidate.payee, category=candidate.category, history=candidate.history)
            _save(path, data)
            return stored
    raise KeyError("CANDIDATE_NOT_FOUND")


def tsv(path: Path) -> dict:
    data = load(path)
    candidates = [rc.Candidate(**{k: v for k, v in c.items() if k != "history"}) for c in data["candidates"]]
    result = expense_tsv(rc.to_expense_rows(candidates), layout="rev")
    return {**result, "held": result["held"] + data["holds"]}


def dispatch(handler, parsed, *, raw=None, csrf: str = "") -> bool:
    if not owns_route(parsed.path) or not enabled():
        return False
    path = _store_path()
    if parsed.path == "/api/receipts/upload":
        handler._send_json({"code": "OCR_ENGINE_NOT_APPROVED",
                            "message": "영수증 이미지를 읽는 엔진이 승인되지 않았습니다. 영역 입력을 사용하세요."}, 501)
        return True
    if raw is None:
        if parsed.path == "/receipts":
            handler._send(render_html(load(path), csrf))
        elif parsed.path == "/api/receipts":
            handler._send_json(load(path))
        elif parsed.path == "/api/receipts/tsv":
            handler._send_json(tsv(path))
        else:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
        handler._send_json({"code": "CSRF_REQUIRED", "message": "화면을 다시 열어 주세요"}, 403)
        return True
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
        if parsed.path == "/api/receipts/scan":
            handler._send_json(scan(path, body))
        elif parsed.path == "/api/receipts/confirm":
            handler._send_json(confirm(path, identity=str(body.get("identity", "")), payee=str(body.get("payee", "")),
                                       category=str(body.get("category", "")), note=str(body.get("note", ""))))
        else:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
    except (ValueError, KeyError, TypeError) as error:
        handler._send_json({"code": str(error) or "INVALID_VALUE"}, 400)
    return True


def _row_html(candidate: dict) -> str:
    identity = html.escape(candidate["identity"])
    amount = "" if candidate["amount_krw"] is None else f"{candidate['amount_krw']:,}원"
    confirmed = bool(candidate.get("payee") and candidate.get("category"))
    return (
        "<tr>"
        f"<td>{html.escape(candidate['date'])}</td><td>{html.escape(candidate['merchant'])}</td>"
        f"<td>{candidate['total_jpy']:,} JPY</td><td>{html.escape(candidate['payment'])}</td>"
        f"<td>{amount}</td><td>{'확정됨' if confirmed else '사람 확인 필요'}</td>"
        f"<td><input data-payee='{identity}' value='{html.escape(candidate.get('payee') or '')}' placeholder='지급처'>"
        f"<input data-category='{identity}' value='{html.escape(candidate.get('category') or '')}' placeholder='내용'>"
        f"<button type='button' data-confirm='{identity}'>확정</button></td></tr>")


def render_html(data: dict, csrf: str) -> str:
    rows = "".join(_row_html(c) for c in data["candidates"])
    holds = "".join(f"<li>{html.escape(h['reason'])}</li>" for h in data["holds"])
    script = (
        f"const csrf={json.dumps(csrf)};"
        "const post=(p,b)=>fetch(p,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},"
        "body:JSON.stringify(b)}).then(r=>r.json().then(j=>{if(!r.ok)throw new Error(j.message||j.code);return j}));"
        "const say=t=>document.getElementById('status').textContent=t;"
        "document.getElementById('scan-go').onclick=()=>post('/api/receipts/scan',"
        "JSON.parse(document.getElementById('scan').value||'{}')).then(()=>location.reload()).catch(e=>say(e.message));"
        "document.querySelectorAll('[data-confirm]').forEach(b=>b.onclick=()=>{const id=b.dataset.confirm;"
        "post('/api/receipts/confirm',{identity:id,payee:document.querySelector('[data-payee=\"'+id+'\"]').value,"
        "category:document.querySelector('[data-category=\"'+id+'\"]').value}).then(()=>location.reload()).catch(e=>say(e.message))});"
        "document.getElementById('copy-tsv').onclick=async()=>{const x=await (await fetch('/api/receipts/tsv')).json();"
        "if(!x.row_count){say('복사할 확정 영수증이 없습니다. 보류 '+x.held.length+'건');return}"
        "await navigator.clipboard.writeText(x.tsv);say('영수증 '+x.row_count+'행을 클립보드에 복사했습니다. "
        "구글 시트에 붙여넣은 뒤에만 반영됩니다.')};")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>영수증 후보</title>"
            "<style>table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccc;padding:4px}"
            "@media(max-width:600px){table{display:block;overflow-x:auto}}</style></head><body>"
            "<h1>영수증 후보</h1>"
            "<p>영역 입력(JSON)으로 등록합니다. 이미지 업로드는 OCR 엔진 승인 후 가능합니다.</p>"
            "<textarea id='scan' rows='4' style='width:100%'></textarea>"
            "<p><button type='button' id='scan-go'>영역 등록</button></p>"
            "<table><thead><tr><th>날짜</th><th>상호</th><th>금액</th><th>결제</th><th>원화</th>"
            f"<th>상태</th><th>확정</th></tr></thead><tbody>{rows}</tbody></table>"
            f"<h2>보류</h2><ul>{holds}</ul>"
            "<p><button type='button' id='copy-tsv'>구글 지출 7열 복사</button> <span id='status' role='status'></span></p>"
            f"<script>{script}</script></body></html>")
