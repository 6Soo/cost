"""Owner-only, isolated preview and guarded execution for bulk expense cleanup."""
from __future__ import annotations

import copy
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from . import card_flow

_PREVIEW_TTL = 300
_PREVIEWS = {}
_PREVIEWS_LOCK = threading.RLock()
_APPLY_LOCK = threading.Lock()
_CONFIRMATION_SCOPE = "classification+ledger_record+existing_trip_assignment"


class PreviewError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _snapshot_identity(board):
    service = getattr(board, "_ota_snapshot_service", None)
    if service is None:
        return None
    current, state = service.display_context()
    return {"generation": (current or {}).get("generation"),
            "key": (current or {}).get("key"), "fresh": bool(state.get("fresh"))}


def _db_digest(conn):
    digest = hashlib.sha256()
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for name in tables:
        if name == "change_log":
            # Apply-attempt audit records do not affect classification and must
            # not invalidate their own freshness check.
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        digest.update(name.encode("utf-8"))
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({quoted})")]
        order = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
        rows = conn.execute(f"SELECT * FROM {quoted} ORDER BY {order}")
        for row in rows:
            digest.update(repr(tuple(row)).encode("utf-8", "backslashreplace"))
            digest.update(b"\0")
    return digest.hexdigest()


def _source_identity(board):
    # _ota_sources only needs the configured data path. Avoid constructing a
    # live Pipeline here: its schema guard may write missing schema on startup.
    flow = object.__new__(card_flow.CardFlow)
    flow.board = board
    from app import ota_sources
    from . import card_flow as card_flow_module

    sources = flow._ota_sources()
    stamps = ota_sources.source_stamps(sources)
    files = []

    def add_file(label, path):
        try:
            source_path = Path(path)
            raw_bytes = source_path.read_bytes()
            stat = source_path.stat()
            files.append((label, stat.st_size, stat.st_mtime_ns,
                          hashlib.sha256(raw_bytes).hexdigest()))
        except OSError:
            files.append((label, "unavailable"))

    for env_name in ("WEBLEDGER_TRIP_AUTHORITY", "WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT"):
        raw = card_flow_module.os.environ.get(env_name, "").strip()
        if raw:
            add_file(env_name, raw)
            if env_name == "WEBLEDGER_TRIP_AUTHORITY":
                try:
                    from ledger.domain.direct_trip_schedule_authority import load_document
                    records, _ = load_document(Path(raw))
                    for record in records:
                        source = record.source_locator.partition("#")[0]
                        if source:
                            add_file("trip-evidence", source)
                except (OSError, ValueError, TypeError):
                    files.append(("trip-evidence", "unavailable"))
            else:
                from . import google_ledger_page
                try:
                    add_file("google-mapping", google_ledger_page.mapping_path(Path(raw)))
                except (OSError, ValueError, TypeError):
                    files.append(("google-mapping", "unavailable"))
    return {"ota": stamps, "authority_files": files,
            "snapshot": _snapshot_identity(board)}


def fingerprint(board):
    """Hash current DB and registered evidence inputs without writing or starting workers."""
    with board._lock:
        return hashlib.sha256(json.dumps(
            {"database": _db_digest(board.conn), "sources": _source_identity(board)},
            sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _clone_store(board):
    """Copy a consistent SQLite snapshot into volatile memory and isolate its audit ledger."""
    from .operator_ledger import OperatorLedger

    clone = copy.copy(board)
    clone.conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    with board._lock:
        board.conn.backup(clone.conn)
    clone._lock = threading.RLock()
    clone._space_hold = None
    clone._card_pipeline = None
    clone._embedded_audit = True
    clone._card_review_mail_cache = {}
    clone.ledger = OperatorLedger.in_database(clone.conn, Path(":memory:"))
    return clone


def _row_snapshot(conn):
    transactions = {row[0]: tuple(row[1:]) for row in conn.execute(
        "SELECT transaction_id,revision,classification_state,item,description,display_tab_id,trip_id,classification_basis"
        " FROM transactions")}
    entries = {row[0] for row in conn.execute("SELECT transaction_id FROM ledger_entries")}
    rows = {row[0]: (row[1], json.loads(row[2]).get("source_event_id", "")) for row in conn.execute(
        "SELECT row_id,display_tab_id,payload_json FROM board_rows WHERE row_kind='expense'")}
    return transactions, entries, rows


def _changed_targets(before, after):
    before_tx, before_entries, before_rows = before
    after_tx, after_entries, after_rows = after
    classified = sorted(tid for tid, value in after_tx.items()
                        if tid in before_tx and value != before_tx[tid])
    recorded = sorted(tid for tid in after_entries - before_entries)
    assigned = sorted(source_id for row_id, (tab, source_id) in after_rows.items()
                      if row_id in before_rows and before_rows[row_id][0] is None and tab is not None)
    return {"classified": classified, "recorded": recorded, "assigned_existing": assigned}


def _simulate(board):
    clone = _clone_store(board)
    try:
        before = _row_snapshot(clone.conn)
        flow = card_flow.CardFlow(clone)
        # display_context is a read-only snapshot read; unlike held(), it does not start a worker.
        source_service = getattr(board, "_ota_snapshot_service", None)
        flow._held_ota_snapshot = (lambda: _held_read_only(source_service)) if source_service else (lambda: (None, False))
        result = card_flow.reclassify_cleanup(clone, _preview=True, flow=flow,
                                             request_snapshot=False)
        targets = _changed_targets(before, _row_snapshot(clone.conn))
        result["targets"] = targets
        result["target_counts"] = {kind: len(values) for kind, values in targets.items()}
        return result
    finally:
        clone.close()


def _requires_snapshot_refresh(board):
    from . import ota_payment_review
    if not ota_payment_review.enabled():
        return False
    with board._lock:
        merchants = board.conn.execute(
            "SELECT DISTINCT t.merchant" + card_flow._cleanup_card_where()).fetchall()
    return any(card_flow._is_ota_row({"merchant": merchant}) for (merchant,) in merchants)


def _held_read_only(service):
    current, state = service.display_context()
    return current, bool(state.get("fresh"))


def create_preview(board):
    before = fingerprint(board)
    result = _simulate(board)
    result["requires_ota_snapshot_refresh"] = _requires_snapshot_refresh(board)
    after = fingerprint(board)
    if before != after:
        raise PreviewError("SOURCE_CHANGED", "미리보기 중 자료가 바뀌었습니다. 새로 미리보기를 실행해 주세요.")
    token = secrets.token_urlsafe(32)
    record = {"fingerprint": before, "result": result,
              "created": time.monotonic(), "state": "ready", "response": None}
    with _PREVIEWS_LOCK:
        now = time.monotonic()
        for key in [key for key, value in _PREVIEWS.items()
                    if now - value["created"] > _PREVIEW_TTL]:
            _PREVIEWS.pop(key, None)
        if len(_PREVIEWS) >= 64:
            oldest = min(_PREVIEWS, key=lambda key: _PREVIEWS[key]["created"])
            _PREVIEWS.pop(oldest, None)
        _PREVIEWS[token] = record
    return {"preview_id": token, "expires_in_seconds": _PREVIEW_TTL,
            "summary": result}


def _audit(board, operation_id, kind, detail):
    from app.db import utc_now
    payload = json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    board.conn.execute(
        "INSERT INTO change_log(at,kind,subject,detail_json) VALUES (?,?,?,?)",
        (utc_now(), kind, operation_id, payload))


def apply_preview(board, preview_id, scope, *, confirmed=False, actor_id="owner-single-operator"):
    if confirmed is not True:
        raise PreviewError("CONFIRMATION_REQUIRED", "명시적으로 적용을 확인해 주세요.")
    with _PREVIEWS_LOCK:
        preview = _PREVIEWS.get(str(preview_id or ""))
        if preview is None or time.monotonic() - preview["created"] > _PREVIEW_TTL:
            raise PreviewError("PREVIEW_EXPIRED", "미리보기가 만료됐습니다. 다시 미리보기를 실행해 주세요.")
        scope_suffix = ("+ota_snapshot_refresh"
                        if preview and preview["result"].get("requires_ota_snapshot_refresh") else "")
        if scope != _CONFIRMATION_SCOPE + scope_suffix:
            raise PreviewError("SCOPE_REQUIRED", "분류·장부 기록·기존 지출 여행 배정 범위를 확인해 주세요.")
        if preview["state"] == "done":
            return preview["response"]
        if preview["state"] == "failed":
            stored = preview["response"] or {}
            raise PreviewError(stored.get("code", "APPLY_FAILED"),
                               stored.get("message", "적용에 실패했습니다. 다시 미리보기를 실행해 주세요."))
        if preview["state"] != "ready":
            raise PreviewError("APPLY_IN_PROGRESS", "이미 이 미리보기의 적용을 처리하고 있습니다.")
        preview["state"] = "running"

    operation_id = secrets.token_hex(16)
    before_apply = None
    try:
        with _APPLY_LOCK:
            current = fingerprint(board)
            if current != preview["fingerprint"]:
                raise PreviewError("PREVIEW_STALE", "미리보기 뒤 자료가 바뀌었습니다. 다시 미리보기를 실행해 주세요.")
            expected = preview["fingerprint"]
            _audit(board, operation_id, "expense.bulk.started", {
                "actor_id": actor_id, "scope": scope, "preview_id": preview_id,
                "target_counts": preview["result"].get("target_counts", {})})
            before_apply = _row_snapshot(board.conn)
            result = card_flow.reclassify_cleanup(board, expected_fingerprint=expected)
            actual_targets = _changed_targets(before_apply, _row_snapshot(board.conn))
            response = {"operation_id": operation_id, "actual": result,
                        "expected": preview["result"], "actual_targets": actual_targets}
            _audit(board, operation_id, "expense.bulk.completed", {
                "actor_id": actor_id, "scope": scope,
                "processed": result.get("processed", 0),
                "recorded": result.get("recorded", 0),
                "assigned_existing": result.get("assigned_existing", 0),
                "failures": result.get("failures", []),
                "targets": actual_targets})
            with _PREVIEWS_LOCK:
                preview["state"] = "done"
                preview["response"] = response
            return response
    except Exception as exc:
        if isinstance(exc, PreviewError):
            code, message = exc.code, str(exc)
        else:
            code, message = "BULK_APPLY_FAILED", "일괄 정리를 완료하지 못했습니다. 감사 기록에서 실제 처리 상태를 확인해 주세요."
        try:
            actual_targets = (_changed_targets(before_apply, _row_snapshot(board.conn))
                              if before_apply is not None else {})
            _audit(board, operation_id, "expense.bulk.failed",
                   {"code": code, "targets": actual_targets})
        except Exception:
            pass
        with _PREVIEWS_LOCK:
            preview["state"] = "failed"
            preview["response"] = {"code": code, "message": message,
                                   "operation_id": operation_id}
        raise PreviewError(code, message) from None


def dispatch(handler, parsed, *, board, raw=None, csrf=""):
    from .ledger_board import current_role

    if parsed.path not in ("/maintenance/expense-bulk",
                           "/api/maintenance/expense-bulk/preview",
                           "/api/maintenance/expense-bulk/apply"):
        return False
    if current_role() != "owner":
        handler._send_json({"code": "FORBIDDEN"}, 403)
        return True
    if parsed.path == "/maintenance/expense-bulk":
        if raw is not None:
            handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        else:
            handler._send(_render_page(csrf))
        return True
    if raw is None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if not csrf or handler.headers.get("X-CSRF-Token") != csrf:
        handler._send_json({"code": "CSRF_REQUIRED"}, 403)
        return True
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        if parsed.path.endswith("/preview"):
            handler._send_json(create_preview(board))
        else:
            from .ledger_board import current_request_session
            session = current_request_session()
            raw_actor = getattr(session, "user_id", "") if session else ""
            actor_id = ("owner-" + hashlib.sha256(str(raw_actor).encode("utf-8")).hexdigest()[:16]
                        if raw_actor else "owner-single-operator")
            handler._send_json(apply_preview(
                board, payload.get("preview_id"), payload.get("scope"),
                confirmed=payload.get("confirmed") is True, actor_id=actor_id))
    except PreviewError as exc:
        status = 503 if exc.code == "BULK_APPLY_FAILED" else 409
        handler._send_json({"code": exc.code, "message": str(exc)}, status)
    except (ValueError, TypeError, json.JSONDecodeError):
        handler._send_json({"code": "INVALID_INPUT", "message": "요청 내용을 확인해 주세요."}, 422)
    except Exception:
        handler._send_json({"code": "PREVIEW_UNAVAILABLE",
                            "message": "읽기 전용 미리보기를 만들지 못했습니다. 자료는 변경하지 않았습니다."}, 503)
    return True


def _render_page(csrf):
    token = json.dumps(csrf)
    return """<!doctype html><html lang='ko'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>지출 정리 유지관리</title>
<style>
main{max-width:900px;margin:24px auto;padding:0 16px;color:var(--ink,#202521)}
section{border:1px solid var(--line,#e3e7e3);border-radius:8px;padding:20px;margin:16px 0;background:var(--paper,#fff)}
button{min-height:44px;padding:0 16px}label{display:flex;gap:10px;align-items:flex-start;margin:16px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere}.warning{color:#8a5a12}
</style></head><body><main><h1>지출 정리 유지관리</h1>
<p>owner 전용 작업입니다. 미리보기는 저장소의 메모리 복제본에서 실행하며 자료를 바꾸지 않습니다. 등록된 OTA 근거 파일과 현재 보관된 스냅샷은 읽기만 하며 외부 요청이나 갱신 워커를 시작하지 않습니다.</p>
<section><h2>1. 변경 예상 확인</h2><p>미리보기에는 대상 거래 ID와 변경 종류만 표시합니다. 가맹점, 원문, 예약번호와 금액은 표시하거나 기록하지 않습니다.</p>
<button id='preview' type='button'>읽기 전용 미리보기</button><pre id='result' role='status' aria-live='polite'></pre></section>
<section><h2>2. 명시적 적용 확인</h2><p class='warning'>분류, 확인된 지출의 장부 기록, 기존 미배정 지출의 여행 배정을 한 번에 실행합니다. 미리보기에서 OTA 스냅샷 갱신이 표시되면 등록 자료를 다시 읽는 별도 작업도 실행됩니다. 운영 대량 재처리는 별도 운영 승인 대상입니다.</p>
<label><input id='confirm' type='checkbox' disabled><span>미리보기 내용을 확인했고 표시된 모든 변경 및 자료 확인 범위를 승인합니다.</span></label>
<button id='apply' type='button' disabled>확인한 미리보기 적용</button><p id='apply-status' role='status' aria-live='polite'></p></section>
<p><a href='/import'>일반 지출 정리로 돌아가기</a></p></main><script>
const csrf=__CSRF__;let current=null;const result=document.getElementById('result');
document.getElementById('preview').onclick=async()=>{current=null;document.getElementById('confirm').checked=false;document.getElementById('confirm').disabled=true;document.getElementById('apply').disabled=true;result.textContent='미리보기를 계산하고 있습니다.';
try{const r=await fetch('/api/maintenance/expense-bulk/preview',{method:'POST',headers:{'X-CSRF-Token':csrf,'Content-Type':'application/json'},body:'{}',cache:'no-store'});const j=await r.json();if(!r.ok)throw Error(j.message||j.code);current=j;result.textContent=JSON.stringify(j.summary,null,2);document.getElementById('confirm').disabled=false;document.getElementById('apply-status').textContent='미리보기는 5분 동안 유효합니다.'}catch(e){result.textContent=e.message}};
document.getElementById('confirm').onchange=e=>document.getElementById('apply').disabled=!(current&&e.target.checked);
document.getElementById('apply').onclick=async()=>{if(!current||!document.getElementById('confirm').checked)return;document.getElementById('apply').disabled=true;document.getElementById('apply-status').textContent='자료 최신성을 확인한 뒤 실행합니다.';
try{const scope='classification+ledger_record+existing_trip_assignment'+(current.summary.requires_ota_snapshot_refresh?'+ota_snapshot_refresh':'');const r=await fetch('/api/maintenance/expense-bulk/apply',{method:'POST',headers:{'X-CSRF-Token':csrf,'Content-Type':'application/json'},body:JSON.stringify({preview_id:current.preview_id,scope,confirmed:true})});const j=await r.json();if(!r.ok)throw Error(j.message||j.code);result.textContent=JSON.stringify(j,null,2);document.getElementById('apply-status').textContent='예상 결과와 실제 결과를 확인해 주세요.';current=null}catch(e){document.getElementById('apply-status').textContent=e.message;document.getElementById('apply').disabled=false}};
</script></body></html>""".replace("__CSRF__", token)
