"""Owner-only review UI/API for COST-to-Google manual expense reconciliation.

The page is a read-only projection.  Its POST records only verified linkage
metadata in the existing local link store; Google sheets are never written.
"""
from __future__ import annotations

import html
import hashlib
import json
import re
import uuid
from urllib.parse import parse_qs, quote


PAGE_PATH = "/google-ledger/expense-reconciliation"
API_PATH = "/api/google-ledger/expense-reconciliation"
PAGE_SIZE = 50
STATUSES = ("MATCHED_MANUAL", "MATCHED_EXISTING", "NEW_EXPENSE",
            "REVIEW_CONFLICT", "SOURCE_UNAVAILABLE")
STATUS_LABELS = {
    "MATCHED_MANUAL": "이미 수기로 기록됨 · 새 행 추가 안함",
    "MATCHED_EXISTING": "COST 내부 연결이 이미 기록됨",
    "NEW_EXPENSE": "신규 반영 가능 · Google에는 아직 기록되지 않음",
    "REVIEW_CONFLICT": "중복 가능성 확인 필요",
    "SOURCE_UNAVAILABLE": "시트 확인 불가 · 안전 보류",
}
FIELD_LABELS = {
    "date": "거래일", "payee": "가맹점/지급처", "merchant": "가맹점/지급처",
    "category": "항목", "item": "항목", "description": "메모", "memo": "메모",
    "amount_krw": "금액", "currency": "통화", "transaction_direction": "거래 방향",
}


def owns_route(path: str) -> bool:
    return path in (PAGE_PATH, API_PATH)


def _owner_request() -> bool:
    # Do not infer ownership from current_role(): enforcement-off requests have
    # no authenticated owner session and must fail closed for this private view.
    from . import ledger_board
    return bool(ledger_board._receipts_owner_request())


def _active_board():
    from . import ledger_board
    return ledger_board._active_store()


def _preview_for_trip(board, trip_id):
    # The projection module is owned by the read-projection worker and is
    # intentionally imported only when the route is used.
    from .sheet_expense_reconciliation import preview_for_trip
    return preview_for_trip(board, trip_id)


def _export_for_trip(board, trip_id, rows=None):
    from .sheet_expense_reconciliation import export_for_trip
    return export_for_trip(board, rows, trip_id)


def _link_store():
    # Durable linkage implementation is owned by the persistence worker.
    from app import sheet_expense_links
    return sheet_expense_links


def _query_value(query, key):
    value = (query or {}).get(key, "")
    return value[0] if isinstance(value, (list, tuple)) and value else value


def _safe_trip_id(value):
    value = str(value or "").strip()
    if not value or len(value) > 200 or any(ord(ch) < 32 for ch in value):
        return ""
    return value


def _filters(query, kind):
    query = str(query or "")
    kind = str(kind or "")
    if len(query) > 160 or any(ord(ch) < 32 for ch in query) or kind not in ("", "in", "ex"):
        raise ValueError("INVALID_FILTER")
    return query, kind


def _selected_expense_rows(trip_id, query, kind):
    from . import ledger_design
    return ledger_design._selected_rows(trip_id, query, kind)[1]


def _batch_expense_rows(board, trip_id, batch_id):
    from app import ledger, quarter_costs
    return [row for row in ledger.preview(board, batch_id)['rows']
            if row.get('display_tab_id') == trip_id and not quarter_costs.destination(row)]


def _mask_card(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return "카드 정보 없음"
    return "•••• " + digits[-4:]


def _public_result(item, cost_by_id):
    transaction_id = str(item.get("transaction_id") or "")
    cost = cost_by_id.get(transaction_id) or {}
    status = item.get("status") if item.get("status") in STATUSES else "SOURCE_UNAVAILABLE"
    trip_id = str(item.get("trip_id") or cost.get("trip_id") or cost.get("display_tab_id") or "")
    sheet_id = str(item.get("sheet_id") or "")
    source = str(item.get("source") or "")
    row_number = item.get("row_number")
    if type(row_number) is not int or row_number < 1:
        row_number = None
    differences = item.get("differences") if isinstance(item.get("differences"), dict) else {}
    safe_differences = {}
    for field, values in differences.items():
        if not isinstance(values, dict):
            continue
        safe_differences[str(field)] = {
            "manual": _display_value(values.get("manual")),
            "cost": _display_value(values.get("cost")),
        }
    basis = item.get("basis") if isinstance(item.get("basis"), list) else []
    result = {
        "transaction_id": transaction_id,
        "trip_id": trip_id,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "date": str(cost.get("date") or cost.get("occurred_on") or cost.get("approval_date") or ""),
        "merchant": str(cost.get("merchant") or cost.get("payee") or ""),
        "category": str(cost.get("item") or cost.get("category") or ""),
        "description": str(cost.get("description") or cost.get("memo") or ""),
        "amount_krw": cost.get("amount_krw"),
        "currency": str(cost.get("currency") or "KRW"),
        "card": _mask_card(cost.get("card_tail")),
        "sheet_id": sheet_id,
        "source": source,
        "row_number": row_number,
        "basis": [str(value)[:120] for value in basis[:20] if isinstance(value, (str, int, float))],
        "differences": safe_differences,
        "reason": str(item.get("reason") or ""),
        "user_corrected": bool(item.get("user_corrected") or item.get("manual_decision")
                                or item.get("manual_override") or item.get("link_source") == "manual"),
        "correction_source": str(item.get("correction_source") or item.get("manual_source") or ""),
    }
    result["review_href"] = "/board?tab=" + quote(trip_id, safe="") if trip_id else "/board"
    return result


def _display_value(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _public_payload(preview, trip_id, page=1):
    raw_results = preview.get("results") if isinstance(preview, dict) else []
    raw_results = raw_results if isinstance(raw_results, list) else []
    cost_rows = preview.get("cost_rows") if isinstance(preview.get("cost_rows"), list) else []
    cost_by_id = {str(row.get("transaction_id") or ""): row for row in cost_rows if isinstance(row, dict)}
    results = [_public_result(item, cost_by_id) for item in raw_results if isinstance(item, dict)]
    counts = preview.get("counts") if isinstance(preview.get("counts"), dict) else {}
    safe_counts = {status: max(0, int(counts.get(status) or 0)) for status in STATUSES}
    # Prefer verified result counts over any malformed/inconsistent summary.
    for status in STATUSES:
        safe_counts[status] = sum(row["status"] == status for row in results)
    page_count = max(1, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, int(page)), page_count)
    start = (page - 1) * PAGE_SIZE
    info = preview.get("source_info") if isinstance(preview.get("source_info"), dict) else {}
    revision = preview.get("revision")
    preview_digest = str(preview.get("preview_digest") or "")
    source_digest = str(preview.get("source_digest") or "")
    source_available = bool(preview.get("source_available"))
    return {
        "code": "OK" if source_available else "SOURCE_UNAVAILABLE",
        "trip_id": trip_id,
        "source_available": source_available,
        "source_info": {key: info.get(key) for key in ("sheet_id", "source", "layout", "synced_at")},
        "counts": safe_counts,
        "results": results[start:start + PAGE_SIZE],
        "total": len(results), "page": page, "page_size": PAGE_SIZE, "pages": page_count,
        "preview_digest": preview_digest,
        "source_digest": source_digest,
        "revision": revision,
        "links_revision": None,
    }


def _with_link_revision(payload, preview):
    path = str(preview.get("links_path") or "") if isinstance(preview, dict) else ""
    if not path:
        return payload
    try:
        payload["links_revision"] = _link_store().load_links(path)["revision"]
    except Exception:
        payload["source_available"] = False
        payload["code"] = "LINKS_UNAVAILABLE"
        payload["links_revision"] = None
        payload["counts"] = {status: 0 for status in STATUSES}
        payload["counts"]["SOURCE_UNAVAILABLE"] = payload.get("total", 0)
        for item in payload.get("results", []):
            item["status"] = "SOURCE_UNAVAILABLE"
            item["status_label"] = STATUS_LABELS["SOURCE_UNAVAILABLE"]
    return payload


def _render_page(payload, *, csrf, request_id, query="", kind=""):
    trip = html.escape(str(payload.get("trip_id") or ""), quote=True)
    query_qs = "&amp;q=" + quote(query, safe="") if query else ""
    kind_qs = "&amp;kind=" + quote(kind, safe="") if kind else ""
    counts = payload.get("counts") or {}
    cards = "".join(
        "<div class='ser-count'><span>" + html.escape(STATUS_LABELS[status]) + "</span><strong>"
        + str(counts.get(status, 0)) + "</strong></div>" for status in STATUSES)
    results = payload.get("results") or []
    rows = []
    for item in results:
        status = item["status"]
        differences = item.get("differences") or {}
        diff_html = "".join(
            "<li><b>" + html.escape(FIELD_LABELS.get(field, field)) + "</b>: 수기 ‘"
            + html.escape(values.get("manual", "")) + "’ ↔ COST ‘"
            + html.escape(values.get("cost", "")) + "’</li>"
            for field, values in differences.items())
        if differences and status in ("MATCHED_MANUAL", "MATCHED_EXISTING"):
            note = "연결 완료 · 수기 원본 유지 · 차이 있음"
        elif status == "REVIEW_CONFLICT":
            note = STATUS_LABELS[status]
        else:
            note = STATUS_LABELS[status]
        position = " · ".join(value for value in (
            item.get("source"), item.get("sheet_id"),
            ("행 " + str(item["row_number"])) if item.get("row_number") else "") if value)
        can_save = status == "MATCHED_MANUAL" and not item.get("user_corrected")
        checkbox = ("<label class='ser-select'><input type='checkbox' name='transaction_ids' value='"
                    + html.escape(item["transaction_id"], quote=True) + "'> 연결 기록 선택</label>" if can_save else "")
        basis = " · ".join(html.escape(value) for value in item.get("basis") or []) or "근거 상세 없음"
        details = ("<ul class='ser-diffs'>" + diff_html + "</ul>") if diff_html else ""
        correction = ("<p class='ser-correction'>사용자 교정 유지" +
                      (" · " + html.escape(item.get("correction_source") or "") if item.get("correction_source") else "")
                      + "</p>") if item.get("user_corrected") else ""
        rows.append(
            "<article class='ser-row ser-" + status.lower() + "'><header><span class='ser-status'>"
            + html.escape(note) + "</span><a href='" + html.escape(item["review_href"], quote=True)
            + "'>COST 거래 검토</a></header><dl><div><dt>거래일 · 가맹점</dt><dd>"
            + html.escape(item.get("date") or "날짜 미상") + " · " + html.escape(item.get("merchant") or "가맹점 미상")
            + "</dd></div><div><dt>금액 · 카드</dt><dd>" + html.escape(_display_value(item.get("amount_krw")))
            + " " + html.escape(item.get("currency") or "") + " · " + html.escape(item.get("card") or "")
            + "</dd></div><div><dt>수기 행 위치</dt><dd>" + html.escape(position or "위치 정보 없음")
            + "</dd></div><div><dt>동일성 근거</dt><dd>" + basis + "</dd></div></dl>"
            + details + correction + ("<p class='ser-reason'>" + html.escape(item.get("reason") or "") + "</p>" if item.get("reason") else "")
            + checkbox + "</article>")
    total, page, pages = payload.get("total", 0), payload.get("page", 1), payload.get("pages", 1)
    pagination = ""
    if pages > 1:
        pagination = "<nav class='ser-pages' aria-label='대조 결과 페이지'>"
        if page > 1:
            pagination += f"<a rel='prev' href='{PAGE_PATH}?trip={trip}&amp;page={page-1}{query_qs}{kind_qs}'>이전 페이지</a>"
        pagination += f"<span aria-current='page'>{page} / {pages}</span>"
        if page < pages:
            pagination += f"<a rel='next' href='{PAGE_PATH}?trip={trip}&amp;page={page+1}{query_qs}{kind_qs}'>다음 페이지</a>"
        pagination += "</nav>"
    unavailable_message = ("연결 상태 파일을 확인할 수 없어 안전하게 보류했습니다."
                           if payload.get("code") == "LINKS_UNAVAILABLE" else
                           "Google 시트 원본을 확인할 수 없어 안전하게 보류했습니다.")
    unavailable = ("<p class='ser-alert' role='alert'>" + html.escape(unavailable_message)
                   + " 새 행 추가나 연결 저장은 할 수 없습니다.</p>" if not payload.get("source_available") else "")
    source = payload.get("source_info") or {}
    source_label = " · ".join(str(source.get(key) or "") for key in ("source", "sheet_id") if source.get(key))
    form = ""
    if payload.get("source_available") and payload.get("links_revision") is not None:
        expected = ("이미 수기 " + str(counts.get("MATCHED_MANUAL", 0)) + "건 · 기존 연결 "
                    + str(counts.get("MATCHED_EXISTING", 0)) + "건 · 신규 TSV "
                    + str(counts.get("NEW_EXPENSE", 0)) + "건 · 검토 보류 "
                    + str(counts.get("REVIEW_CONFLICT", 0)) + "건")
        form = ("<form class='ser-save' id='ser-save' aria-label='검증된 연결 메타데이터 저장'>"
                f"<input type='hidden' name='csrf' value='{html.escape(csrf, quote=True)}'>"
                f"<input type='hidden' name='trip_id' value='{trip}'>"
                f"<input type='hidden' name='expected_revision' value='{payload['links_revision']}'>"
                f"<input type='hidden' name='preview_digest' value='{html.escape(payload['preview_digest'], quote=True)}'>"
                f"<input type='hidden' name='request_id' value='{html.escape(request_id, quote=True)}'>"
                f"<input type='hidden' name='query' value='{html.escape(query, quote=True)}'>"
                f"<input type='hidden' name='kind' value='{html.escape(kind, quote=True)}'>"
                + "<p class='ser-expected'>예상 결과: " + html.escape(expected) + "</p>"
                + "<p class='ser-note'>신규 지출 복사는 장부의 현재 검색어와 종류 필터를 적용합니다.</p>"
                + "<button type='submit' name='action' value='links'>선택한 연결 기록</button> "
                + "<button type='submit' name='action' value='export'>신규 지출 복사</button>"
                + "<p class='ser-live' id='ser-live' role='status' aria-live='polite'></p>"
                "<p class='ser-note'>COST 내부 연결 메타데이터와 TSV만 준비합니다. Google 시트는 변경하지 않습니다.</p></form>")
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>수기 지출 중복 대조</title><style>"
        ".ser-page{max-width:1100px;margin:0 auto;padding:16px;color:var(--shell-ink);line-height:1.55}"
        ".ser-page *{box-sizing:border-box}.ser-page h1{font-size:1.45rem}.ser-page a{color:var(--shell-accent)}"
        ".ser-counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:16px 0}"
        ".ser-count{border:1px solid var(--shell-line);border-radius:12px;padding:12px;background:var(--shell-paper)}"
        ".ser-count span{display:block;font-size:.9rem;color:var(--shell-muted)}.ser-count strong{font-size:1.35rem}"
        ".ser-row{border:1px solid var(--shell-line);border-radius:12px;padding:14px;margin:12px 0;overflow-wrap:anywhere}"
        ".ser-row header{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}"
        ".ser-status{font-weight:700}.ser-row dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}"
        ".ser-row dl div{min-width:0}.ser-row dt{font-size:.85rem;color:var(--shell-muted)}.ser-row dd{margin:0}"
        ".ser-diffs{border-left:3px solid var(--shell-accent);padding-left:22px}.ser-alert{padding:12px;border:1px solid var(--shell-warn);border-radius:10px;color:var(--shell-warn)}"
        ".ser-select{display:inline-flex;align-items:center;gap:8px;min-height:44px}.ser-select input{width:20px;height:20px}"
        ".ser-save{position:sticky;bottom:0;padding:12px;background:var(--shell-paper);border-top:1px solid var(--shell-line)}"
        ".ser-save button,.ser-pages a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 14px;border:1px solid var(--shell-line);border-radius:9px;background:var(--shell-paper);color:var(--shell-ink);font:inherit}"
        ".ser-pages{display:flex;justify-content:center;align-items:center;gap:14px;margin:16px 0}.ser-note,.ser-live{color:var(--shell-muted)}"
        "@media(max-width:560px){.ser-page{padding:12px}.ser-row{padding:12px}.ser-row dl{grid-template-columns:1fr}.ser-pages{justify-content:space-between}}"
        "</style></head><body><main class='ser-page' id='main' tabindex='-1'><h1>수기 지출 중복 대조</h1>"
        f"<p>선택 여행: <b>{trip}</b>" + (f" · 원본: {html.escape(source_label)}" if source_label else "")
        + "</p><p>수기와 COST 값을 비교해 기존 행 연결을 확인합니다. 자동 연결은 Google 시트에 새로 기입했다는 뜻이 아닙니다.</p>"
        + unavailable + f"<section class='ser-counts' aria-label='상태별 건수'>{cards}</section>"
        + ("<p>표시할 대조 결과가 없습니다.</p>" if not total else "")
        + "<section aria-label='거래별 대조 결과'>" + "".join(rows) + "</section>" + pagination + form
        + "<script>(function(){const f=document.getElementById('ser-save');if(!f)return;"
        "f.addEventListener('submit',async e=>{e.preventDefault();const ids=[...f.querySelectorAll('input[name=transaction_ids]:checked')].map(x=>x.value);"
        "const status=document.getElementById('ser-live');const action=e.submitter?.value||'links';"
        "if(action==='links'&&!ids.length){status.textContent='연결할 행을 선택해 주세요.';return;}"
        "const b=f.querySelector('button');b.disabled=true;status.textContent='최신 원본을 다시 확인하고 있습니다.';"
        "const d=Object.fromEntries(new FormData(f).entries());d.transaction_ids=ids;d.action=action;d.request_id=action+':'+d.request_id;"
        "try{const r=await fetch('" + API_PATH + "',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':d.csrf},body:JSON.stringify(d)});"
        "const j=await r.json();if(!r.ok)throw new Error(j.message||j.code||'저장하지 못했습니다.');"
        "if(action==='export'){if(j.row_count&&j.tsv){await navigator.clipboard.writeText(j.tsv);status.textContent=j.row_count+'건의 TSV를 복사했습니다. Google 시트에는 입력되지 않았습니다.';}"
        "else{status.textContent='복사할 신규 지출이 없습니다. 기존 수기 행은 그대로 유지됩니다.';}return;}"
        "status.textContent=j.replayed?'이전 연결 요청이 이미 처리되었습니다. 현재 상태를 다시 불러옵니다.':'연결 메타데이터를 저장했습니다. Google 시트는 변경하지 않았습니다.';"
        "setTimeout(()=>location.reload(),500);}catch(err){status.textContent=err.message;b.disabled=false;}});})();</script>"
        "</main></body></html>")


def _send_error(handler, code, http_status, message="요청을 처리할 수 없습니다"):
    handler._send_json({"code": code, "message": message}, http_status)


def _preview_payload(trip_id, page):
    board = _active_board()
    if board is None:
        return None, None, "COST_STORE_UNAVAILABLE"
    try:
        preview = _preview_for_trip(board, trip_id)
        if not isinstance(preview, dict):
            return None, None, "PREVIEW_INVALID"
        payload = _with_link_revision(_public_payload(preview, trip_id, page), preview)
        return payload, preview, ""
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return None, None, "PREVIEW_UNAVAILABLE"


def _saved_request(store, path, request_id):
    data = store.load_links(path)
    request = next((entry for entry in reversed(data["history"])
                    if entry.get("kind") == "request" and entry.get("request_id") == request_id), None)
    if request is None:
        return None, []
    saved = [entry.get("after") for entry in data["history"]
             if entry.get("kind") == "link_saved"
             and (entry.get("after") or {}).get("provenance", {}).get("request_id") == request_id]
    return request, saved


def _linkable_rows(results):
    """Build storage input only from fresh automatic/manual-sheet matches."""
    rows = []
    for row in results:
        if row.get("status") not in ("MATCHED_MANUAL", "MATCHED_EXISTING"):
            continue
        # MATCHED_MANUAL identifies a manually entered sheet row, not a user
        # approval. Existing user corrections are preserved as-is.
        if row.get("status") == "MATCHED_EXISTING":
            continue
        if (row.get("user_corrected") or row.get("manual_decision")
                or row.get("manual_override") or row.get("link_source") == "manual"):
            raise ValueError("USER_CORRECTION_PROTECTED")
        required = ("transaction_id", "trip_id", "sheet_id", "source",
                    "sheet_row_key", "sheet_fingerprint")
        if not all(str(row.get(key) or "").strip() for key in required):
            raise ValueError("MATCH_IDENTITY_INCOMPLETE")
        basis = row.get("basis")
        if not isinstance(basis, list) or not basis:
            raise ValueError("MATCH_EVIDENCE_INCOMPLETE")
        rows.append({
            "transaction_id": row["transaction_id"], "trip_id": row["trip_id"],
            "sheet_id": row["sheet_id"], "source": row["source"],
            "sheet_row_key": row["sheet_row_key"],
            "sheet_fingerprint": row["sheet_fingerprint"],
            "row_number": row.get("row_number"), "basis": basis,
            "status": "MATCHED_MANUAL", "user_override": False,
            "link_method": "automatic_match",
        })
    return rows


def _find_replay(store, path, request_id, transaction_ids):
    request, saved = _saved_request(store, path, request_id)
    if request is None:
        return None
    if {str(row.get("transaction_id") or "") for row in saved if isinstance(row, dict)} != set(transaction_ids):
        raise ValueError("LINK_REQUEST_ID_REUSED")
    candidates = [{**row, "sheet_row_key": row.get("stable_key")} for row in saved]
    return store.save_links(path, candidates, expected_revision=0,
                            request_id=request_id, source_digest=request.get("source_digest"))


def _post(handler, raw, csrf):
    if not raw or len(raw) > 64 * 1024:
        _send_error(handler, "INVALID_VALUE", 400)
        return
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _send_error(handler, "INVALID_VALUE", 400)
        return
    if not isinstance(body, dict):
        _send_error(handler, "INVALID_VALUE", 400)
        return
    token = str(body.get("csrf") or handler.headers.get("X-CSRF-Token") or "")
    if not csrf or token != csrf or handler.headers.get("X-CSRF-Token") != csrf:
        _send_error(handler, "CSRF_REQUIRED", 403, "화면을 새로 연 뒤 다시 시도해 주세요")
        return
    trip_id = _safe_trip_id(body.get("trip_id"))
    action = body.get("action", "links")
    scope = body.get('scope', 'all')
    batch_id = _safe_trip_id(body.get('batch_id'))
    ids = body.get("transaction_ids", [])
    request_id = body.get("request_id")
    expected_revision = body.get("expected_revision")
    expected_preview = body.get("preview_digest")
    try:
        query, kind = _filters(body.get("query", ""), body.get("kind", ""))
    except ValueError:
        _send_error(handler, "INVALID_FILTER", 400)
        return
    if (not trip_id or action not in ("links", "export") or scope not in ('all', 'board', 'batch')
            or (scope == 'batch' and not batch_id) or not isinstance(ids, list)
            or (action == "links" and not ids) or len(ids) > PAGE_SIZE
            or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in ids)
            or len(set(ids)) != len(ids) or type(expected_revision) is not int or expected_revision < 0
            or not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 120
            or not request_id.startswith(action + ":")
            or not isinstance(expected_preview, str) or not expected_preview):
        _send_error(handler, "INVALID_VALUE", 400)
        return
    payload, preview, failure = _preview_payload(trip_id, 1)
    if failure:
        _send_error(handler, failure, 503)
        return
    path = str(preview.get("links_path") or "")
    if not path or not payload.get("source_available"):
        _send_error(handler, "SOURCE_UNAVAILABLE", 503, "시트 원본을 확인할 수 없어 안전하게 보류했습니다")
        return
    try:
        store = _link_store()
        if action == "links":
            replay = _find_replay(store, path, request_id, ids)
            if replay is not None:
                handler._send_json({"code": "OK", "replayed": True,
                                    "message": "이전 요청이 이미 처리되었습니다"})
                return
        prior_request, prior_rows = _saved_request(store, path, request_id)
        if action == "links" or prior_request is None:
            if payload.get("preview_digest") != expected_preview:
                _send_error(handler, "PREVIEW_STALE", 409, "원본이 바뀌었습니다. 최신 대조 결과를 다시 열어 주세요")
                return
            current = store.load_links(path)
            if current.get("revision") != expected_revision:
                _send_error(handler, "LINK_REVISION_CONFLICT", 409, "연결 상태가 바뀌었습니다. 최신 대조 결과를 다시 열어 주세요")
                return
        elif prior_request.get("revision") != expected_revision + 1:
            _send_error(handler, "LINK_REQUEST_ID_REUSED", 409)
            return

        if action == "export":
            board = _active_board()
            if board is None:
                _send_error(handler, "COST_STORE_UNAVAILABLE", 503)
                return
            try:
                export_rows = (_batch_expense_rows(board, trip_id, batch_id) if scope == 'batch' else
                               _selected_expense_rows(trip_id, query, kind)
                               if scope == 'board' or query or kind else None)
            except (ValueError, TypeError):
                _send_error(handler, "INVALID_FILTER", 400)
                return
            exported = _export_for_trip(board, trip_id, export_rows)
            fresh = exported.get("reconciliation") if isinstance(exported, dict) else None
            if (not isinstance(exported, dict) or not exported.get("source_available")
                    or not isinstance(fresh, dict) or not fresh.get("source_available")):
                _send_error(handler, "SOURCE_UNAVAILABLE", 503,
                            "시트 원본을 다시 확인할 수 없어 TSV를 준비하지 않았습니다")
                return
            if (fresh.get("source_digest") != preview.get("source_digest")
                    or (prior_request is None and scope == 'all' and not (query or kind)
                        and fresh.get("preview_digest") != expected_preview)):
                _send_error(handler, "PREVIEW_STALE", 409,
                            "미리보기 이후 원본이 바뀌었습니다. 최신 결과를 다시 열어 주세요")
                return
            full_fresh = _preview_for_trip(board, trip_id)
            if not isinstance(full_fresh, dict) or not full_fresh.get("source_available"):
                _send_error(handler, "SOURCE_UNAVAILABLE", 503,
                            "전체 대조 결과를 다시 확인할 수 없어 TSV를 준비하지 않았습니다")
                return
            export_context = hashlib.sha256(json.dumps({
                'trip_id': trip_id, 'query': query, 'kind': kind, 'scope': scope, 'batch_id': batch_id,
                'cost_rows': full_fresh.get('cost_rows'),
                'tsv': exported.get('tsv'), 'held': exported.get('held'),
            }, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
            if prior_request is not None:
                if prior_request.get('request_context') != export_context:
                    _send_error(handler, 'LINK_REQUEST_ID_REUSED', 409,
                                '지출이나 복사 조건이 바뀌었습니다. 최신 대조 결과에서 다시 복사해 주세요')
                    return
                if full_fresh.get("source_digest") != prior_request.get("source_digest"):
                    _send_error(handler, "SOURCE_CHANGED", 409,
                                "원본이 이전 요청 이후 바뀌어 TSV를 준비하지 않았습니다")
                    return
                current_results = {str(row.get("transaction_id") or ""): row
                                   for row in full_fresh.get("results", []) if isinstance(row, dict)}
                for saved in prior_rows:
                    current_row = current_results.get(str(saved.get("transaction_id") or ""))
                    if (not current_row or current_row.get("status") not in ("MATCHED_MANUAL", "MATCHED_EXISTING")
                            or current_row.get("sheet_row_key") != saved.get("stable_key")
                            or current_row.get("sheet_fingerprint") != saved.get("sheet_fingerprint")):
                        _send_error(handler, "LINK_CHANGED", 409,
                                    "저장된 연결을 현재 원본에서 다시 확인할 수 없어 TSV를 준비하지 않았습니다")
                        return
                handler._send_json({"code": "OK", "replayed": True,
                                    "tsv": str(exported.get("tsv") or ""),
                                    "row_count": int(exported.get("row_count") or 0),
                                    "total_krw": int(exported.get("total_krw") or 0),
                                    "held": exported.get("held") if isinstance(exported.get("held"), list) else [],
                                    "reconciliation": _public_payload(full_fresh, trip_id),
                                    "message": "최신 원본을 다시 확인해 이전 요청 결과를 준비했습니다"})
                return
            if full_fresh.get("preview_digest") != expected_preview:
                _send_error(handler, "PREVIEW_STALE", 409,
                            "전체 대조 결과가 바뀌었습니다. 최신 결과를 다시 열어 주세요")
                return
            current = store.load_links(path)
            if current.get("revision") != expected_revision:
                _send_error(handler, "LINK_REVISION_CONFLICT", 409,
                            "연결 상태가 바뀌었습니다. TSV를 준비하지 않았습니다")
                return
            results = full_fresh.get("results") if isinstance(full_fresh.get("results"), list) else []
            to_save = _linkable_rows(results)
            if to_save:
                store.save_links(path, to_save, expected_revision=expected_revision,
                                 request_id=request_id, source_digest=fresh.get("source_digest"),
                                 request_context=export_context)
            handler._send_json({"code": "OK", "replayed": False,
                                "tsv": str(exported.get("tsv") or ""),
                                "row_count": int(exported.get("row_count") or 0),
                                "total_krw": int(exported.get("total_krw") or 0),
                                "held": exported.get("held") if isinstance(exported.get("held"), list) else [],
                                "reconciliation": _public_payload(full_fresh, trip_id),
                                "matched_count": sum(row.get("status") in ("MATCHED_MANUAL", "MATCHED_EXISTING")
                                                     for row in results),
                                "held_count": sum(row.get("status") in ("REVIEW_CONFLICT", "SOURCE_UNAVAILABLE")
                                                  for row in results),
                                "message": "최신 대조 결과입니다. Google 시트에는 입력되지 않았습니다"})
            return

        if not ids:
            _send_error(handler, "INVALID_VALUE", 400)
            return
        by_id = {}
        for row in preview.get("results", []):
            transaction_id = str(row.get("transaction_id") or "")
            if transaction_id in by_id:
                raise ValueError("RECONCILIATION_INVALID")
            by_id[transaction_id] = row
        selected = [by_id.get(transaction_id) for transaction_id in ids]
        if any(row is None or row.get("status") not in ("MATCHED_MANUAL", "MATCHED_EXISTING")
               for row in selected):
            _send_error(handler, "MATCH_NOT_CONFIRMED", 409,
                        "최신 대조에서 모두 확정된 수기 행으로 확인되지 않았습니다")
            return
        to_save = _linkable_rows(selected)
        if to_save:
            store.save_links(path, to_save, expected_revision=expected_revision,
                             request_id=request_id, source_digest=payload["source_digest"])
        handler._send_json({"code": "OK", "replayed": False,
                            "linked_count": len(ids), "saved_count": len(to_save),
                            "message": "연결 메타데이터를 저장했습니다. Google 시트는 변경하지 않았습니다"})
    except ValueError as error:
        code = str(error) or "LINK_SAVE_FAILED"
        status = 409 if code in ("LINK_REVISION_CONFLICT", "LINK_REQUEST_ID_REUSED",
                                 "TRANSACTION_ALREADY_LINKED", "SHEET_ROW_ALREADY_LINKED",
                                 "USER_CORRECTION_PROTECTED", "MATCH_IDENTITY_INCOMPLETE",
                                 "MATCH_EVIDENCE_INCOMPLETE", "PREVIEW_STALE", "SOURCE_CHANGED",
                                 "LINK_CHANGED", "MATCH_NOT_CONFIRMED") else 503
        _send_error(handler, code, status)
    except Exception as error:
        code = getattr(error, "code", "LINKS_UNAVAILABLE")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", code):
            code = "LINKS_UNAVAILABLE"
        status = 409 if code in ("LINK_REVISION_CONFLICT", "LINK_REQUEST_ID_REUSED",
                                 "TRANSACTION_ALREADY_LINKED", "SHEET_ROW_ALREADY_LINKED",
                                 "USER_CORRECTION_PROTECTED", "MATCH_IDENTITY_INCOMPLETE",
                                 "MATCH_EVIDENCE_INCOMPLETE", "PREVIEW_STALE", "SOURCE_CHANGED",
                                 "LINK_CHANGED", "MATCH_NOT_CONFIRMED") else 503
        _send_error(handler, code, status)


def dispatch(handler, parsed, query=None, raw=None, csrf="") -> bool:
    """Dispatch only the two reconciliation routes; callers own role resolution."""
    path = getattr(parsed, "path", "")
    if not owns_route(path):
        return False
    if not _owner_request():
        _send_error(handler, "OWNER_ONLY", 403, "소유자만 확인할 수 있습니다")
        return True
    method = getattr(handler, "command", "GET" if raw is None else "POST").upper()
    if path == PAGE_PATH and method == "GET":
        query = query if query is not None else parse_qs(getattr(parsed, "query", ""))
        trip_id = _safe_trip_id(_query_value(query, "trip"))
        if not trip_id:
            handler._send("<!doctype html><html lang='ko'><meta charset='utf-8'><main><h1>여행을 선택해 주세요</h1><p>유효한 여행 ID가 필요합니다.</p></main></html>", code=400)
            return True
        try:
            filter_query, kind = _filters(_query_value(query, "q"), _query_value(query, "kind"))
        except ValueError:
            handler._send("<!doctype html><html lang='ko'><meta charset='utf-8'><main><h1>잘못된 검색 조건</h1></main></html>", code=400)
            return True
        try:
            page = int(_query_value(query, "page") or 1)
        except (TypeError, ValueError):
            page = 1
        payload, _preview, failure = _preview_payload(trip_id, page)
        if failure:
            handler._send("<!doctype html><html lang='ko'><meta charset='utf-8'><main><h1>대조 결과를 표시할 수 없습니다</h1><p role='alert'>시트 또는 COST 자료를 확인할 수 없어 안전하게 보류했습니다.</p></main></html>", code=503)
            return True
        handler._send(_render_page(payload, csrf=csrf, request_id=str(uuid.uuid4()),
                                   query=filter_query, kind=kind))
        return True
    if path == API_PATH and method == "GET":
        query = query if query is not None else parse_qs(getattr(parsed, "query", ""))
        trip_id = _safe_trip_id(_query_value(query, "trip"))
        if not trip_id:
            _send_error(handler, "TRIP_REQUIRED", 400)
            return True
        try:
            page = int(_query_value(query, "page") or 1)
        except (TypeError, ValueError):
            page = 1
        payload, _preview, failure = _preview_payload(trip_id, page)
        if failure:
            _send_error(handler, failure, 503)
        elif not payload["source_available"]:
            handler._send_json(payload, 503)
        elif payload.get("code") == "LINKS_UNAVAILABLE":
            handler._send_json(payload, 503)
        else:
            handler._send_json(payload)
        return True
    if path == API_PATH and method == "POST":
        _post(handler, raw, csrf)
        return True
    handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
    return True
