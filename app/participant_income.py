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
STATE_REVIEWED = "reviewed"

DECISION_LINKED = "linked"
DECISION_UNLINKED = "unlinked"
#: 명단과 미연결인 수입 행에 대한 명시적 검토 결정.
DECISION_REVIEWED = "reviewed"

#: 대조가 끝났다고 말할 수 없는 이유.
BLOCKING_REASONS = ("ROSTER_INCOMPLETE", "TRANSCRIPTION_PENDING", "CONNECTION_PENDING",
                    "INCOME_UNCLASSIFIED", "INPUT_CHANGED", "CORRECTION_PENDING",
                    "DUPLICATE_UNRESOLVED")


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


def income_rows_from_trip(*, index, amount_rows, source: str, sheet: str) -> list[dict]:
    """원본 수입 행과 이름 인덱스를 고유 행 기준으로 합친다.

    이름 인덱스만 보면 이름이 공란인 실제 금액 행이 빠진다. 원본 행을 기준으로
    다시 합쳐 어떤 행도 잃지 않는다. 날짜·구성액·금액은 원문 그대로 둔다.
    """
    rows = income_rows_from_index(index, source=source, sheet=sheet)
    by_row = {row["row"]: row for row in rows}
    for raw in amount_rows or []:
        cells = {"B": raw.get("date"), "C": raw.get("name"), "D": raw.get("nickname"),
                 "E": raw.get("deposit"), "F": raw.get("balance"), "G": raw.get("extra")}
        row = by_row.get(raw.get("row"))
        if row is None:
            row = {"source": source, "sheet": sheet, "row": raw.get("row"), "cells": dict(cells),
                   "name": raw.get("name") or "", "nickname": raw.get("nickname") or "",
                   "amount": raw.get("amount"), "amount_state": "amounted"}
            row["ref"] = income_ref(source, sheet, row["row"])
            row["fingerprint"] = income_fingerprint(row)
            by_row[row["row"]] = row
            rows.append(row)
            continue
        # 원본 행의 날짜·구성액을 그대로 채운다.
        row["cells"].update(cells)
        if row.get("amount") is None and raw.get("amount") is not None:
            row["amount"] = raw.get("amount")
            row["amount_state"] = "amounted"
            row["fingerprint"] = income_fingerprint(row)
    rows.sort(key=lambda item: (item["row"] if isinstance(item["row"], int) else 0))
    return rows


def input_fingerprint(*, roster_version: str, google_generation: str, income_rows,
                      decisions=None) -> str:
    """대조 입력의 지문. 화면이 오래됐는지 판단할 때 쓴다.

    수동 결정의 revision도 지문에 들어간다. 결정이 하나 바뀌면 그 화면은 오래된
    화면이 되어 이전 결정을 덮어쓸 수 없다.
    """
    revision_part = sorted(
        (str(decision.get("participant_id") or ""), str(decision.get("income_ref") or ""),
         str(decision.get("decision") or ""), int(decision.get("revision") or 0))
        for decision in (decisions or []))
    return hashlib.sha256(canonical({
        "roster_version": roster_version,
        "google_generation": google_generation,
        "income": [{"ref": row["ref"], "fingerprint": row["fingerprint"]} for row in income_rows],
        "decisions": revision_part,
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
    manual_unlinks: dict[str, set] = {}
    reviewed_refs: dict[str, str] = {}
    for decision in list(decisions or []):
        income_ref = str(decision.get("income_ref") or "")
        kind = decision.get("decision")
        if kind == DECISION_REVIEWED:
            # 명단과 미연결인 수입 행에 대한 명시적 검토 결정.
            if income_ref:
                reviewed_refs[income_ref] = decision.get("reason") or ""
            continue
        participant_id = decision.get("participant_id") or ""
        if not participant_id:
            continue
        if kind == DECISION_UNLINKED:
            # 사용자가 해제한 행은 이름이 맞아도 다시 연결하지 않는다.
            manual_unlinks.setdefault(participant_id, set()).add(income_ref)
            continue
        if kind != DECISION_LINKED:
            continue
        row = by_ref.get(income_ref)
        if row is None:
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
        manual = list(manual_links.get(pid, []))
        found = candidates.get(pid, [])
        unlinked = manual_unlinks.get(pid, set())
        taken = [row for row in found if row["ref"] in manual_refs]
        remaining = [row for row in found if row["ref"] not in unlinked]
        auto = []
        if len(remaining) == 1 and len(row_candidates.get(remaining[0]["ref"], [])) == 1 \
                and not taken:
            auto = [_link(pid, remaining[0], "name_match")]
            linked_rows.setdefault(remaining[0]["ref"], []).append(pid)
        links = manual + [link for link in auto
                          if link["income_ref"] not in {item["income_ref"] for item in manual}]
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
        elif taken:
            # 이미 다른 참가자에게 수동 연결된 행이다. 이름만으로 함께 묶지 않는다.
            state = STATE_NEEDS_CHECK
        elif remaining:
            state = STATE_NEEDS_CHECK
        else:
            # 후보가 없거나 사용자가 전부 해제한 경우다. 해제 결정이 우선한다.
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
        reviewed = row["ref"] in reviewed_refs
        unlinked_rows.append({
            "ref": row["ref"], "row": row["row"], "name": row.get("name") or "",
            "nickname": row.get("nickname") or "", "amount": row.get("amount"),
            "amount_state": row.get("amount_state"), "cells": row.get("cells") or {},
            "state": STATE_REVIEWED if reviewed else STATE_NOT_IN_ROSTER,
            "review_reason": reviewed_refs.get(row["ref"], ""),
            "candidates": row_candidates.get(row["ref"], []),
        })

    # 참가 인원은 명단으로 확정된 활성 참가자 전체다. 이름 연결 상태와 따로 센다.
    duplicate_names = _duplicate_names(people)
    correction_pending = sum(1 for person in people
                             if (person.get("state") or "") == "correction_pending")
    counts = {
        "participants": len(people),
        "roster_confirmed": len(people),
        "linked": sum(1 for item in results if item["state"] in
                      (STATE_NAME_MATCH, STATE_INCOME_PRESENT, STATE_MANUAL, STATE_JOINT)),
        "name_only": sum(1 for item in results if item["state"] in
                         (STATE_INCOME_PRESENT, STATE_NO_INCOME)),
        "needs_check": sum(1 for item in results if item["state"] == STATE_NEEDS_CHECK),
        "unverified": sum(1 for item in results if item["state"] == STATE_UNVERIFIED),
        "linked_income_rows": len(linked_rows),
        "unlinked_income_rows": sum(1 for item in unlinked_rows
                                    if item["state"] == STATE_NOT_IN_ROSTER),
        "reviewed_income_rows": sum(1 for item in unlinked_rows
                                    if item["state"] == STATE_REVIEWED),
        "income_rows": len(rows),
        "duplicate_names": duplicate_names,
        "correction_pending": correction_pending,
    }

    reasons = []
    if not roster_complete:
        reasons.append("ROSTER_INCOMPLETE")
    if transcription_pending:
        reasons.append("TRANSCRIPTION_PENDING")
    if counts["needs_check"]:
        reasons.append("CONNECTION_PENDING")
    if counts["unlinked_income_rows"]:
        reasons.append("INCOME_UNCLASSIFIED")
    if not index_available:
        reasons.append("INPUT_CHANGED")
    if correction_pending:
        reasons.append("CORRECTION_PENDING")
    if duplicate_names:
        reasons.append("DUPLICATE_UNRESOLVED")

    return {
        "trip_id": trip_id,
        "rule_version": RULE_VERSION,
        "index_available": bool(index_available),
        "roster_version": roster_version,
        "google_generation": google_generation,
        "input_fingerprint": input_fingerprint(roster_version=roster_version,
                                               google_generation=google_generation,
                                               income_rows=rows, decisions=decisions),
        "participants": results,
        "income_rows": rows,
        "unlinked_income": unlinked_rows,
        "counts": counts,
        "roster_total_declared": bool(roster_complete),
        "completion": {"complete": not reasons, "blocked_by": reasons},
    }


def _duplicate_names(people) -> list[str]:
    """같은 이름의 활성 참가자. 동명이인일 수 있어 인원을 확정하지 못한다."""
    groups: dict[str, list[str]] = {}
    for person in people:
        name = normalize_name(person.get("display_name"))
        if not name:
            continue
        groups.setdefault(name, []).append(person.get("participant_id") or "")
    return sorted(name for name, ids in groups.items() if len(ids) > 1)


# ------------------------------------------------------------------- decisions

DECISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS participant_income_links (
    link_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    trip_id TEXT NOT NULL DEFAULT '',
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(participant_income_links)")}
    if "trip_id" not in columns:
        # 이전 형식의 저장소에도 결정을 보존한다. 여행은 참가자 소속으로 대신 찾는다.
        conn.execute("ALTER TABLE participant_income_links ADD COLUMN trip_id TEXT NOT NULL DEFAULT ''")


def decision_table_exists(conn) -> bool:
    """결정 표가 있는지. 읽기 전용 경로가 준비되지 않은 저장소를 읽을 때 쓴다."""
    return any(row[0] == "participant_income_links" for row in
               conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))


def decisions_for_trip(conn, trip_id: str) -> list[dict]:
    if not decision_table_exists(conn):
        # 아직 결정이 없는 저장소다. 읽기 경로는 스키마를 만들지 않는다.
        return []
    rows = conn.execute(
        "SELECT l.link_id, l.participant_id, l.income_ref, l.income_fingerprint, l.link_method,"
        " l.decision, l.joint, l.reason, l.revision, l.input_fingerprint, l.decided_by, l.decided_at"
        " FROM participant_income_links l LEFT JOIN trip_participants p"
        " ON p.participant_id=l.participant_id"
        " WHERE l.trip_id=? OR (l.trip_id='' AND p.trip_id=?)"
        " ORDER BY l.decided_at, l.link_id", (trip_id, trip_id)).fetchall()
    return [{"link_id": r[0], "participant_id": r[1], "income_ref": r[2], "income_fingerprint": r[3],
             "link_method": r[4], "decision": r[5], "joint": bool(r[6]), "reason": r[7],
             "revision": r[8], "input_fingerprint": r[9], "decided_by": r[10], "decided_at": r[11]}
            for r in rows]


def _link_id(participant_id: str, income_ref: str) -> str:
    return "ln-" + hashlib.sha256(f"{participant_id}|{income_ref}".encode("utf-8")).hexdigest()[:24]


def save_decision(conn, *, participant_id: str, income_ref: str, decision: str,
                  trip_id: str = "", link_method: str = "manual", joint: bool = False,
                  reason: str = "",
                  income_fingerprint: str = "", decided_by: str = "",
                  presented_fingerprint: str = "", current_fingerprint: str = "",
                  expected_revision: int | None = None) -> dict:
    """수동 연결·해제·검토 결정을 저장한다.

    화면이 오래됐으면 `STALE_RECONCILIATION`으로 거절한다. 지문은 필수다. 지문이
    없으면 검사를 건너뛰는 대신 refuse한다. 결정의 revision도 함께 비교해 이전
    결정을 덮어쓰지 않게 한다.
    """
    if not income_ref:
        raise ReconciliationError("INVALID_VALUE", "수입 행이 필요해요")
    if decision not in (DECISION_LINKED, DECISION_UNLINKED, DECISION_REVIEWED):
        raise ReconciliationError("INVALID_VALUE", "결정 값이 맞지 않아요")
    if decision != DECISION_REVIEWED and not participant_id:
        raise ReconciliationError("INVALID_VALUE", "참가자가 필요해요")
    if not presented_fingerprint or not current_fingerprint:
        raise ReconciliationError("INVALID_VALUE", "화면 지문이 필요해요")
    if presented_fingerprint != current_fingerprint:
        raise ReconciliationError("STALE_RECONCILIATION", "화면이 오래됐어요. 다시 확인해 주세요")
    stamp = utc_now()
    link_id = _link_id(participant_id, income_ref)
    existing = conn.execute(
        "SELECT revision FROM participant_income_links WHERE link_id=?", (link_id,)).fetchone()
    current_revision = existing[0] if existing else 0
    if expected_revision is not None and int(expected_revision) != current_revision:
        # 이 결정을 다른 화면이 이미 바꿨다. 이전 결정을 덮어쓰지 않는다.
        raise ReconciliationError("STALE_RECONCILIATION", "결정이 이미 바뀌었어요. 다시 확인해 주세요")
    revision = current_revision + 1
    conn.execute(
        "INSERT INTO participant_income_links(link_id, participant_id, trip_id, income_ref,"
        " income_fingerprint, link_method, decision, joint, reason, revision, input_fingerprint,"
        " decided_by, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(link_id) DO UPDATE SET decision=excluded.decision,"
        " link_method=excluded.link_method, joint=excluded.joint, reason=excluded.reason,"
        " revision=excluded.revision, income_fingerprint=excluded.income_fingerprint,"
        " trip_id=excluded.trip_id, input_fingerprint=excluded.input_fingerprint,"
        " decided_by=excluded.decided_by, decided_at=excluded.decided_at",
        (link_id, participant_id, trip_id, income_ref, income_fingerprint, link_method, decision,
         1 if joint else 0, reason, revision, current_fingerprint,
         decided_by, stamp))
    conn.execute(
        "INSERT INTO roster_events(at, kind, subject, detail_json) VALUES (?,?,?,?)",
        (stamp, "participant_income_decision", participant_id or income_ref,
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
