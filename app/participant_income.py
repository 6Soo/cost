"""참가자와 Google 수입 행의 대조와 연결 결정.

대조는 참가 확정, 수입 연결, 판독 상태를 서로 다른 것으로 다룬다. 이름은 원문을
보존하고 비교값에만 유니코드 정규화와 공백 정리, 영문 대소문자 통일을 쓴다.
한글 내부 공백 삭제나 부분 문자열 일치는 연결 근거가 아니다.

Google의 수입 행과 금액은 이 모듈이 바꾸지 않는다. 연결과 결정만 저장한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from .participant_roster import RosterError, canonical, utc_now

RULE_VERSION = "participant-income-v1"

#: 대조 상태. 화면 문구는 webapp이 붙인다.
STATE_NAME_MATCH = "name_match"
STATE_INCOME_PRESENT = "income_present"
STATE_NO_INCOME = "no_income"
STATE_NEEDS_CHECK = "needs_check"
STATE_MANUAL = "manual"
STATE_JOINT = "joint"
STATE_UNVERIFIED = "unverified"
STATE_NOT_IN_ROSTER = "not_in_roster"

DECISION_LINKED = "linked"
DECISION_UNLINKED = "unlinked"

#: 대조가 끝났다고 말할 수 없는 이유.
BLOCKING_REASONS = ("ROSTER_INCOMPLETE", "TRANSCRIPTION_PENDING", "CONNECTION_PENDING",
                    "INCOME_UNCLASSIFIED", "INPUT_CHANGED")


class ReconciliationError(RosterError):
    """대조 저장 오류. 코드는 HTTP 상태로 그대로 전달한다."""


def normalize_name(value) -> str:
    """비교값. 원문은 그대로 두고 비교할 때만 정규화한다."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).strip()
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def participant_keys(participant: dict) -> set[str]:
    """참가자가 가질 수 있는 비교값. 원문에 적힌 이름·닉네임·영문명만 쓴다."""
    keys = set()
    for field in ("display_name", "nickname", "english_name"):
        value = normalize_name(participant.get(field))
        if value:
            keys.add(value)
    return keys


def income_row_keys(row: dict) -> set[str]:
    keys = set()
    for field in ("name", "nickname"):
        value = normalize_name(row.get(field))
        if value:
            keys.add(value)
    cells = row.get("cells") or {}
    for field in ("C", "D"):
        value = normalize_name(cells.get(field))
        if value:
            keys.add(value)
    return keys


def income_ref(source: str, sheet: str, row) -> str:
    """수입 행의 연결 기준. 행 번호만으로 영구 ID를 쓰지 않는다."""
    return f"{source}|{sheet}|{row}"


def income_fingerprint(row: dict) -> str:
    """수입 행의 내용 지문. 행 위치가 바뀌어도 같은 내용이면 같은 지문이다."""
    return hashlib.sha256(canonical({
        "cells": row.get("cells") or {},
        "name": row.get("name") or "",
        "nickname": row.get("nickname") or "",
        "amount": row.get("amount"),
    }).encode("utf-8")).hexdigest()[:32]


def income_rows_from_index(index, *, source: str, sheet: str) -> list[dict]:
    """이름 인덱스를 대조에 쓸 수입 행 목록으로 바꾼다."""
    rows = []
    for entry in (index or {}).get("rows") or []:
        cells = entry.get("cells") or {}
        row = {
            "source": source,
            "sheet": sheet,
            "row": entry.get("row"),
            "cells": cells,
            "name": entry.get("name") or cells.get("C") or "",
            "nickname": entry.get("nickname") or cells.get("D") or "",
            "amount": entry.get("amount"),
            "amount_state": entry.get("amount_state") or "blank",
        }
        row["ref"] = income_ref(source, sheet, row["row"])
        row["fingerprint"] = income_fingerprint(row)
        rows.append(row)
    return rows


def input_fingerprint(*, roster_version: str, google_generation: str, income_rows) -> str:
    """대조 입력의 지문. 화면이 오래됐는지 판단할 때 쓴다."""
    return hashlib.sha256(canonical({
        "roster_version": roster_version,
        "google_generation": google_generation,
        "income": [{"ref": row["ref"], "fingerprint": row["fingerprint"]} for row in income_rows],
    }).encode("utf-8")).hexdigest()


def roster_version_of(participants, *, pending_items=0, scope: str = "partial") -> str:
    """명단 세대. 참가자·판독 대기·자료 범위가 바뀌면 값이 바뀐다."""
    return hashlib.sha256(canonical({
        "participants": sorted(
            (p.get("participant_id"), p.get("display_name"), p.get("nickname"),
             p.get("english_name"), p.get("state")) for p in (participants or [])),
        "pending": pending_items,
        "scope": scope,
    }).encode("utf-8")).hexdigest()


def _link(participant_id: str, row: dict, method: str, *, joint: bool = False,
          reason: str = "", decided_by: str = "") -> dict:
    return {"participant_id": participant_id, "income_ref": row["ref"], "row": row,
            "income_fingerprint": row["fingerprint"], "method": method, "joint": joint,
            "reason": reason, "decided_by": decided_by}


def reconcile(*, trip_id: str, participants, income_rows, index_available: bool,
              decisions=None, roster_version: str = "", google_generation: str = "",
              roster_complete: bool = False, transcription_pending: int = 0) -> dict:
    """참가자와 수입 행을 대조한다.

    우선순위는 기존 수동 결정 → 같은 여행의 명시적 참가자 연결 → 안전한 이름 일치 →
    미연결이다. 이름만 있는 참가자는 날짜·금액을 만들지 않는다.
    """
    people = list(participants or [])
    rows = list(income_rows or [])
    by_ref = {row["ref"]: row for row in rows}

    manual_links: dict[str, list[dict]] = {}
    for decision in list(decisions or []):
        if decision.get("decision") != DECISION_LINKED:
            continue
        participant_id = decision.get("participant_id") or ""
        row = by_ref.get(decision.get("income_ref"))
        if not participant_id or row is None:
            continue
        link = _link(participant_id, row, decision.get("link_method") or "manual",
                     joint=bool(decision.get("joint")), reason=decision.get("reason") or "",
                     decided_by=decision.get("decided_by") or "")
        # 저장된 연결의 원문 지문이 지금의 지문과 다르면 재확인이 필요하다.
        link["fingerprint_mismatch"] = bool(
            decision.get("income_fingerprint") and decision["income_fingerprint"] != row["fingerprint"])
        manual_links.setdefault(participant_id, []).append(link)

    # 이름 일치 후보. 이름만으로 연결 근거가 되는 경우에만 쓴다.
    candidates: dict[str, list[dict]] = {}
    row_candidates: dict[str, list[str]] = {}
    for person in people:
        keys = participant_keys(person)
        found = [row for row in rows if keys and (keys & income_row_keys(row))]
        candidates[person["participant_id"]] = found
        for row in found:
            row_candidates.setdefault(row["ref"], []).append(person["participant_id"])

    manual_refs: dict[str, list[str]] = {}
    for pid, links in manual_links.items():
        for link in links:
            manual_refs.setdefault(link["income_ref"], []).append(pid)
    linked_rows: dict[str, list[str]] = {ref: list(pids) for ref, pids in manual_refs.items()}

    results = []
    for person in people:
        pid = person["participant_id"]
        links = list(manual_links.get(pid, []))
        if links:
            shared = any(len(linked_rows.get(link["income_ref"], [])) > 1 for link in links)
            if any(link.get("fingerprint_mismatch") for link in links):
                # 원문이 바뀌어 같은 연결을 유일하게 증명할 수 없다.
                state = STATE_NEEDS_CHECK
            elif shared:
                state = STATE_JOINT
            elif any(link["method"] == "manual" for link in links):
                state = STATE_MANUAL
            elif links[0]["row"].get("amount_state") == "amounted":
                state = STATE_NAME_MATCH
            else:
                state = STATE_INCOME_PRESENT
        else:
            found = candidates.get(pid, [])
            taken = [row for row in found if row["ref"] in manual_refs]
            if found and taken:
                # 이미 다른 참가자에게 수동 연결된 행이다. 이름만으로 함께 묶지 않는다.
                state = STATE_NEEDS_CHECK
            elif len(found) == 1 and len(row_candidates.get(found[0]["ref"], [])) == 1:
                link = _link(pid, found[0], "name_match")
                links = [link]
                linked_rows.setdefault(link["income_ref"], []).append(pid)
                state = (STATE_NAME_MATCH if found[0].get("amount_state") == "amounted"
                         else STATE_INCOME_PRESENT)
            elif found:
                state = STATE_NEEDS_CHECK
            else:
                state = STATE_NO_INCOME if index_available else STATE_UNVERIFIED
        results.append({
            "participant_id": pid,
            "trip_id": trip_id,
            "display_name": person.get("display_name") or "",
            "nickname": person.get("nickname") or "",
            "state": state,
            "links": links,
            "candidate_refs": [row["ref"] for row in candidates.get(pid, [])],
            "participant_state": person.get("state") or "confirmed",
        })

    unlinked_rows = []
    for row in rows:
        if row["ref"] in linked_rows:
            continue
        unlinked_rows.append({
            "ref": row["ref"], "row": row["row"], "name": row.get("name") or "",
            "nickname": row.get("nickname") or "", "amount": row.get("amount"),
            "amount_state": row.get("amount_state"), "state": STATE_NOT_IN_ROSTER,
            "candidates": row_candidates.get(row["ref"], []),
        })

    counts = {
        "participants": len(people),
        "confirmed": sum(1 for item in results if item["state"] in
                         (STATE_NAME_MATCH, STATE_INCOME_PRESENT, STATE_NO_INCOME,
                          STATE_MANUAL, STATE_JOINT)),
        "linked": sum(1 for item in results if item["state"] in
                      (STATE_NAME_MATCH, STATE_INCOME_PRESENT, STATE_MANUAL, STATE_JOINT)),
        "name_only": sum(1 for item in results if item["state"] in
                         (STATE_INCOME_PRESENT, STATE_NO_INCOME)),
        "needs_check": sum(1 for item in results if item["state"] == STATE_NEEDS_CHECK),
        "unverified": sum(1 for item in results if item["state"] == STATE_UNVERIFIED),
        "linked_income_rows": len(linked_rows),
        "unlinked_income_rows": len(unlinked_rows),
        "income_rows": len(rows),
    }

    reasons = []
    if not roster_complete:
        reasons.append("ROSTER_INCOMPLETE")
    if transcription_pending:
        reasons.append("TRANSCRIPTION_PENDING")
    if counts["needs_check"]:
        reasons.append("CONNECTION_PENDING")
    if unlinked_rows:
        reasons.append("INCOME_UNCLASSIFIED")
    if not index_available:
        reasons.append("INPUT_CHANGED")

    return {
        "trip_id": trip_id,
        "rule_version": RULE_VERSION,
        "index_available": bool(index_available),
        "roster_version": roster_version,
        "google_generation": google_generation,
        "input_fingerprint": input_fingerprint(roster_version=roster_version,
                                               google_generation=google_generation,
                                               income_rows=rows),
        "participants": results,
        "income_rows": rows,
        "unlinked_income": unlinked_rows,
        "counts": counts,
        "completion": {"complete": not reasons, "blocked_by": reasons},
    }


# ------------------------------------------------------------------- decisions

DECISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS participant_income_links (
    link_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    income_ref TEXT NOT NULL,
    income_fingerprint TEXT NOT NULL DEFAULT '',
    link_method TEXT NOT NULL DEFAULT 'manual',
    decision TEXT NOT NULL DEFAULT 'linked',
    joint INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    input_fingerprint TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL,
    UNIQUE (participant_id, income_ref)
);
CREATE TABLE IF NOT EXISTS participant_reconciliation_runs (
    run_id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    roster_version TEXT NOT NULL DEFAULT '',
    google_generation TEXT NOT NULL DEFAULT '',
    rule_version TEXT NOT NULL DEFAULT '',
    result_fingerprint TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL DEFAULT '{}',
    completed_at TEXT NOT NULL
);
"""


def ensure_decision_schema(conn) -> None:
    conn.executescript(DECISION_SCHEMA)


def decisions_for_trip(conn, trip_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT l.link_id, l.participant_id, l.income_ref, l.income_fingerprint, l.link_method,"
        " l.decision, l.joint, l.reason, l.revision, l.input_fingerprint, l.decided_by, l.decided_at"
        " FROM participant_income_links l JOIN trip_participants p"
        " ON p.participant_id=l.participant_id WHERE p.trip_id=?"
        " ORDER BY l.decided_at, l.link_id", (trip_id,)).fetchall()
    return [{"link_id": r[0], "participant_id": r[1], "income_ref": r[2], "income_fingerprint": r[3],
             "link_method": r[4], "decision": r[5], "joint": bool(r[6]), "reason": r[7],
             "revision": r[8], "input_fingerprint": r[9], "decided_by": r[10], "decided_at": r[11]}
            for r in rows]


def _link_id(participant_id: str, income_ref: str) -> str:
    return "ln-" + hashlib.sha256(f"{participant_id}|{income_ref}".encode("utf-8")).hexdigest()[:24]


def save_decision(conn, *, participant_id: str, income_ref: str, decision: str,
                  link_method: str = "manual", joint: bool = False, reason: str = "",
                  income_fingerprint: str = "", decided_by: str = "",
                  presented_fingerprint: str = "", current_fingerprint: str = "") -> dict:
    """수동 연결·해제 결정을 저장한다.

    화면이 오래됐으면 `STALE_RECONCILIATION`으로 거절한다. 현재 입력 지문이
    화면에 제시된 지문과 다르면 다시 읽어야 한다.
    """
    if not participant_id or not income_ref:
        raise ReconciliationError("INVALID_VALUE", "참가자와 수입 행이 필요해요")
    if decision not in (DECISION_LINKED, DECISION_UNLINKED):
        raise ReconciliationError("INVALID_VALUE", "결정 값이 맞지 않아요")
    if presented_fingerprint and current_fingerprint and presented_fingerprint != current_fingerprint:
        raise ReconciliationError("STALE_RECONCILIATION", "화면이 오래됐어요. 다시 확인해 주세요")
    stamp = utc_now()
    link_id = _link_id(participant_id, income_ref)
    existing = conn.execute(
        "SELECT revision FROM participant_income_links WHERE link_id=?", (link_id,)).fetchone()
    revision = (existing[0] + 1) if existing else 1
    conn.execute(
        "INSERT INTO participant_income_links(link_id, participant_id, income_ref, income_fingerprint,"
        " link_method, decision, joint, reason, revision, input_fingerprint, decided_by, decided_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(link_id) DO UPDATE SET decision=excluded.decision,"
        " link_method=excluded.link_method, joint=excluded.joint, reason=excluded.reason,"
        " revision=excluded.revision, income_fingerprint=excluded.income_fingerprint,"
        " input_fingerprint=excluded.input_fingerprint, decided_by=excluded.decided_by,"
        " decided_at=excluded.decided_at",
        (link_id, participant_id, income_ref, income_fingerprint, link_method, decision,
         1 if joint else 0, reason, revision, current_fingerprint or presented_fingerprint,
         decided_by, stamp))
    conn.execute(
        "INSERT INTO roster_events(at, kind, subject, detail_json) VALUES (?,?,?,?)",
        (stamp, "participant_income_decision", participant_id,
         canonical({"income_ref": income_ref, "decision": decision, "revision": revision})))
    return {"link_id": link_id, "participant_id": participant_id, "income_ref": income_ref,
            "decision": decision, "joint": bool(joint), "revision": revision, "decided_at": stamp}


def record_run(conn, *, trip_id: str, roster_version: str, google_generation: str,
               result: dict) -> str:
    """대조 실행과 완료 상태를 기록한다."""
    stamp = utc_now()
    run_id = "run-" + hashlib.sha256(
        f"{trip_id}|{roster_version}|{google_generation}|{result.get('input_fingerprint')}"
        .encode("utf-8")).hexdigest()[:24]
    conn.execute(
        "INSERT INTO participant_reconciliation_runs(run_id, trip_id, roster_version, google_generation,"
        " rule_version, result_fingerprint, summary_json, completed_at) VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(run_id) DO UPDATE SET summary_json=excluded.summary_json,"
        " completed_at=excluded.completed_at",
        (run_id, trip_id, roster_version, google_generation, RULE_VERSION,
         result.get("input_fingerprint") or "", canonical(result.get("counts") or {}), stamp))
    return run_id


def runs(conn, trip_id: str = "") -> list[dict]:
    query = ("SELECT run_id, trip_id, roster_version, google_generation, rule_version,"
             " result_fingerprint, summary_json, completed_at FROM participant_reconciliation_runs")
    params: tuple = ()
    if trip_id:
        query += " WHERE trip_id=?"
        params = (trip_id,)
    query += " ORDER BY completed_at DESC, run_id"
    rows = conn.execute(query, params).fetchall()
    return [{"run_id": r[0], "trip_id": r[1], "roster_version": r[2], "google_generation": r[3],
             "rule_version": r[4], "result_fingerprint": r[5], "summary": json.loads(r[6]),
             "completed_at": r[7]} for r in rows]
