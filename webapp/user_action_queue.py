"""Owner-facing unified user action queue backed by the existing request log."""
from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone


SCOPE = "user_action_task_v1"
OPEN = "OPEN"
ANSWERED = "ANSWERED"
REPROCESSING = "REPROCESSING"
RESOLVED = "RESOLVED"
SUPERSEDED = "SUPERSEDED"
_NO_REQUEST_SNAPSHOT = object()
_REQUEST_SNAPSHOT = ContextVar("user_action_queue_request_snapshot", default=_NO_REQUEST_SNAPSHOT)
_QUEUE_UNAVAILABLE = object()

class QueueReadUnavailable(RuntimeError):
    """The action queue could not be read, so a zero count cannot be claimed."""


@dataclass(frozen=True)
class OpenTaskSnapshot:
    tasks: tuple[dict, ...]
    count: int
    revision: str


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _task_id(group_key):
    return "ua-" + hashlib.sha256(str(group_key).encode("utf-8")).hexdigest()[:32]


def _digest(task):
    payload = {key: value for key, value in task.items() if key not in {"updated_at", "revision"}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _decode(row):
    try:
        task = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return task if isinstance(task, dict) and task.get("scope") == SCOPE else None


def _valid_open_task(task):
    if not task or task.get("state") != OPEN:
        return False
    group_key = task.get("action_group_key")
    action_id = task.get("action_id")
    if not isinstance(group_key, str) or not isinstance(action_id, str):
        return False
    group_key = group_key.strip()
    action_id = action_id.strip()
    if not group_key or not action_id or action_id != _task_id(group_key):
        return False
    if any(not isinstance(task.get(key), str) or not task[key].strip()
           for key in ("task_type", "title", "question", "evidence_summary")):
        return False
    revision = task.get("revision")
    priority = task.get("priority", 0)
    if (not isinstance(revision, int) or isinstance(revision, bool)
            or not isinstance(priority, int) or isinstance(priority, bool)):
        return False
    return revision > 0


def _option(option):
    if isinstance(option, dict):
        value = str(option.get("value", ""))
        return value, str(option.get("label", value))
    return str(option), str(option)


def list_tasks(conn):
    return list(open_snapshot(conn).tasks)


def pending_answers(conn):
    """Return submitted actions that still need their domain effect applied."""
    try:
        rows = conn.execute(
            "SELECT response_json FROM requests WHERE scope=? AND json_extract(response_json,'$.state')=?",
            (SCOPE, REPROCESSING)).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: requests" not in str(exc).lower():
            raise
        return []
    return [task for (raw,) in rows if (task := _decode((raw,))) and task.get("state") == REPROCESSING]


def open_count(conn):
    return open_snapshot(conn).count


def open_snapshot(conn):
    """Return valid, unique OPEN human actions from one database read."""
    request_state = _REQUEST_SNAPSHOT.get()
    if request_state is not _NO_REQUEST_SNAPSHOT and request_state is not None:
        cached_conn, cached_snapshot = request_state
        if cached_conn is conn:
            if cached_snapshot is _QUEUE_UNAVAILABLE:
                raise QueueReadUnavailable("The user action queue is unavailable")
            return cached_snapshot

    try:
        snapshot = _read_open_snapshot(conn)
    except QueueReadUnavailable:
        if request_state is not _NO_REQUEST_SNAPSHOT:
            _REQUEST_SNAPSHOT.set((conn, _QUEUE_UNAVAILABLE))
        raise
    if request_state is not _NO_REQUEST_SNAPSHOT:
        _REQUEST_SNAPSHOT.set((conn, snapshot))
    return snapshot


def _read_open_snapshot(conn):
    if conn is None:
        raise QueueReadUnavailable("The user action queue is unavailable")
    try:
        rows = conn.execute(
            "SELECT response_json FROM requests WHERE scope=? "
            "AND CASE WHEN json_valid(response_json) THEN json_extract(response_json,'$.state')=? ELSE 0 END "
            "ORDER BY request_id",
            (SCOPE, OPEN),
        ).fetchall()
    except sqlite3.Error as exc:
        raise QueueReadUnavailable("The user action queue is unavailable") from exc

    by_group = {}
    for (raw,) in rows:
        task = _decode((raw,))
        if not _valid_open_task(task):
            continue
        group_key = task["action_group_key"].strip()
        current_order = (str(task.get("updated_at") or ""), int(task["revision"]),
                         task["action_id"], _digest(task))
        previous = by_group.get(group_key)
        previous_order = ((str(previous.get("updated_at") or ""), int(previous["revision"]),
                           previous["action_id"], _digest(previous))
                          if previous else None)
        if previous is None or current_order > previous_order:
            by_group[group_key] = task

    tasks = list(by_group.values())
    tasks.sort(key=lambda task: (-task.get("priority", 0), str(task.get("created_at") or ""), task["action_id"]))
    revision_items = [{"action_id": task["action_id"], "revision": int(task["revision"]),
                       "digest": _digest(task)} for task in tasks]
    revision = hashlib.sha256(json.dumps(revision_items, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()
    return OpenTaskSnapshot(tuple(tasks), len(tasks), revision)


@contextmanager
def request_snapshot_scope():
    """Reuse one action-queue read for every component rendered in an HTTP request."""
    token = _REQUEST_SNAPSHOT.set(None)
    try:
        yield
    finally:
        _REQUEST_SNAPSHOT.reset(token)


def queue_data_attrs(snapshot):
    return (" data-action-count='" + str(snapshot.count) + "' data-queue-revision='" +
            html.escape(snapshot.revision, quote=True) + "'")


def render_queue_summary(snapshot):
    """Render the shared action count for the import page, without inventing zero on failure."""
    if snapshot is None:
        return ("<section class='action-queue-summary' aria-labelledby='action-queue-title'>"
                "<h2 id='action-queue-title'>내 확인 필요</h2>"
                "<p role='alert'>작업 수를 확인할 수 없습니다. 거래 상태와 구분해 다시 불러와 주세요.</p>"
                "<p><a href='/my-actions'>내 확인 필요 다시 확인</a></p></section>")
    empty = "현재 직접 답할 작업이 없습니다." if snapshot.count == 0 else "답변이나 자료 제출이 필요한 사용자 작업입니다."
    return ("<section class='action-queue-summary' aria-labelledby='action-queue-title'" +
            queue_data_attrs(snapshot) + ">"
            "<h2 id='action-queue-title'><a href='/my-actions'>내 확인 필요 " +
            str(snapshot.count) + "건</a></h2><p>" + empty + "</p></section>")


def register(conn, *, group_key, task_type, title, question, evidence_summary,
             recommendation="", source_refs=(), source_revision="", priority=0,
             answer_options=(), answer_effect=None, action_url=""):
    """Upsert one human decision. Callers must register only actionable P3 work."""
    group_key = str(group_key or "").strip()
    if not group_key or len(group_key) > 500:
        raise ValueError("action group key is required")
    fields = (task_type, title, question, evidence_summary)
    if any(not str(value or "").strip() for value in fields):
        raise ValueError("task type, title, question and evidence are required")
    action_id = _task_id(group_key)
    existing = conn.execute("SELECT response_json FROM requests WHERE request_id=? AND scope=?",
                            ("user-action:" + action_id, SCOPE)).fetchone()
    old = _decode(existing) if existing else None
    incoming = {
        "action_group_key": group_key, "task_type": str(task_type)[:80], "title": str(title)[:240],
        "question": str(question)[:1000], "evidence_summary": str(evidence_summary)[:3000],
        "recommendation": str(recommendation or "")[:1500],
        "source_refs": [str(ref)[:300] for ref in source_refs][:30],
        "source_revision": str(source_revision)[:300], "priority": max(0, min(100, int(priority))),
        "answer_options": [
            ({"value": str(option.get("value", ""))[:300],
              "label": str(option.get("label", option.get("value", "")))[:300]}
             if isinstance(option, dict) else
             {"value": str(option)[:300], "label": str(option)[:300]})
            for option in answer_options][:12],
        "answer_effect": dict(answer_effect or {}),
        "action_url": str(action_url or "")[:1000],
    }
    if old and all(old.get(key) == value for key, value in incoming.items()):
        return old
    now = _now()
    task = {
        "scope": SCOPE, "action_id": action_id, **incoming,
        "state": OPEN, "created_at": old.get("created_at", now) if old else now,
        "updated_at": now, "revision": int(old.get("revision", 0) if old else 0) + 1,
        "answer": None,
    }
    digest = _digest(task)
    conn.execute("INSERT INTO requests(request_id,scope,payload_sha256,response_json,created_at) VALUES(?,?,?,?,?) "
                 "ON CONFLICT(request_id) DO UPDATE SET scope=excluded.scope,payload_sha256=excluded.payload_sha256,"
                 "response_json=excluded.response_json,created_at=excluded.created_at",
                 ("user-action:" + action_id, SCOPE, digest,
                  json.dumps(task, ensure_ascii=False, sort_keys=True), now))
    return task


def answer(conn, *, action_id, expected_revision, expected_digest, value, actor="owner"):
    row = conn.execute("SELECT response_json FROM requests WHERE request_id=? AND scope=?",
                       ("user-action:" + str(action_id), SCOPE)).fetchone()
    task = _decode(row) if row else None
    if not task or task.get("state") != OPEN:
        raise ValueError("ACTION_NOT_OPEN")
    if int(task.get("revision", 0)) != int(expected_revision) or _digest(task) != expected_digest:
        raise ValueError("STALE_ACTION")
    value = str(value or "").strip()
    if not value or len(value) > 2000:
        raise ValueError("ANSWER_REQUIRED")
    options = task.get("answer_options") or []
    if options and value not in {_option(option)[0] for option in options}:
        raise ValueError("ANSWER_INVALID")
    task["answer"] = {"value": value, "source": "USER", "actor": str(actor)[:100], "answered_at": _now()}
    task["state"] = ANSWERED
    task["updated_at"] = _now()
    task["revision"] = int(task["revision"]) + 1
    conn.execute("UPDATE requests SET payload_sha256=?,response_json=?,created_at=? WHERE request_id=? AND scope=?",
                 (_digest(task), json.dumps(task, ensure_ascii=False, sort_keys=True), task["updated_at"],
                  "user-action:" + str(action_id), SCOPE))
    return task


def set_state(conn, action_id, state):
    if state not in {REPROCESSING, RESOLVED, SUPERSEDED, OPEN}:
        raise ValueError("invalid task state")
    key = "user-action:" + str(action_id)
    row = conn.execute("SELECT response_json FROM requests WHERE request_id=? AND scope=?", (key, SCOPE)).fetchone()
    task = _decode(row) if row else None
    if not task:
        return None
    task["state"] = state
    task["revision"] = int(task["revision"]) + 1
    task["updated_at"] = _now()
    conn.execute("UPDATE requests SET payload_sha256=?,response_json=?,created_at=? WHERE request_id=? AND scope=?",
                 (_digest(task), json.dumps(task, ensure_ascii=False, sort_keys=True), task["updated_at"], key, SCOPE))
    return task


def render_unavailable():
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>내 확인 필요</title><style>main{max-width:880px;margin:0 auto;padding:20px}"
            "a{display:inline-flex;align-items:center;min-height:44px}</style></head><body><main><h1>내 확인 필요</h1>"
            "<p role='alert'>작업 목록을 불러오지 못했습니다. 현재 작업 수를 확인할 수 없어요.</p>"
            "<p><a href='/my-actions'>다시 불러오기</a></p></main></body></html>")


def render(conn, csrf, *, answered=False, snapshot=None):
    try:
        if snapshot is None:
            snapshot = open_snapshot(conn)
    except QueueReadUnavailable:
        return render_unavailable()
    tasks = snapshot.tasks
    cards = []
    for task in tasks:
        esc = lambda value: html.escape(str(value or ""), quote=True)
        options = task.get("answer_options") or []
        answer_control = ("<select name='answer' required aria-label='질문에 대한 답변'><option value=''>답변을 선택하세요</option>"
                          + "".join(f"<option value='{esc(_option(option)[0])}'>{esc(_option(option)[1])}</option>" for option in options)
                          + "</select>" if options else "<textarea name='answer' required maxlength='2000' aria-label='질문에 대한 답변'></textarea>")
        cards.append("<article class='action-card' data-action-id='" + esc(task["action_id"]) + "'>"
                     + "<p class='action-kind'>" + esc(task.get("task_type")) + "</p><h2>" + esc(task.get("title")) + "</h2>"
                     + "<p>" + esc(task.get("evidence_summary")) + "</p>"
                     + ("<p class='recommendation'>추천: " + esc(task.get("recommendation")) + "</p>" if task.get("recommendation") else "")
                     + "<form method='post' action='/api/user-actions/answer'><input type='hidden' name='csrf' value='" + esc(csrf) + "'>"
                     + "<input type='hidden' name='action_id' value='" + esc(task["action_id"]) + "'>"
                     + "<input type='hidden' name='revision' value='" + str(int(task["revision"])) + "'>"
                     + "<input type='hidden' name='digest' value='" + esc(_digest(task)) + "'>"
                     + "<label>" + esc(task.get("question")) + answer_control + "</label>"
                     + "<button type='submit'>답변하고 자동 재검토</button></form>"
                     + "<p><a href='" + esc(task.get("action_url") or
                         ('/import?transaction=' + str((task.get("source_refs") or [""])[0]))) + "'>원본 거래 보기</a></p></article>")
    body = "".join(cards) if cards else "<p class='queue-empty'>현재 직접 답할 작업이 없습니다.</p>"
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>내 확인 필요</title><style>main{max-width:880px;margin:0 auto;padding:20px}.action-card{border:1px solid var(--shell-line,var(--c-border));padding:16px;margin:12px 0;border-radius:var(--r-md)}"
            ".action-card button{min-height:44px}.action-card textarea{display:block;width:100%;min-height:70px}.action-card select{display:block;min-height:44px;max-width:100%}.action-kind{color:var(--shell-muted,var(--c-text-secondary))}</style></head>"
            "<body><main" + queue_data_attrs(snapshot) + "><h1>내 확인 필요 " + str(snapshot.count) +
            "건</h1><p>자동 검토로 해결되지 않아 답변이 필요한 작업만 표시합니다.</p>"
            + ("<p role='status'>답변을 저장했습니다. 관련 자동 검토를 다시 확인하고 있습니다.</p>" if answered else "")
            + body + "</main></body></html>")
