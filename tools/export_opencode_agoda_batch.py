"""Export and attest an Agoda worker JSON result from an OpenCode session.

The browser worker is read-only.  This parent-side utility reads the provider's
local SQLite event store, locates the final JSON for one lane, and verifies each
successful record against the browser-tool transcript for that booking.  Any
record that cannot be attested is downgraded to a failed record instead of
being imported fail-open.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from tools.agoda_paseo_batch_import import normalize_worker_record


DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
DETAIL_SELECTOR = "blp-booking-item-button-edit"


def _parts(db: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT p.time_created, m.data, p.data
          FROM part AS p
          JOIN message AS m ON m.id = p.message_id
         WHERE p.session_id = ?
         ORDER BY p.time_created, p.id
        """,
        (session_id,),
    )
    result: list[dict[str, Any]] = []
    for created, message_json, part_json in rows:
        message = json.loads(message_json)
        part = json.loads(part_json)
        result.append({"created": int(created), "role": message.get("role"), "part": part})
    return result


def _find_prompt_time(parts: list[dict[str, Any]], lane: str, *, first: bool = False) -> int:
    matches = [
        row["created"]
        for row in parts
        if row["role"] == "user"
        and row["part"].get("type") == "text"
        and lane in str(row["part"].get("text") or "")
    ]
    if not matches:
        raise ValueError("opencode_lane_prompt_not_found")
    return min(matches) if first else max(matches)


def _find_batch(parts: list[dict[str, Any]], lane: str, after: int) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for row in parts:
        if row["created"] < after or row["role"] != "assistant":
            continue
        part = row["part"]
        if part.get("type") != "text":
            continue
        text = str(part.get("text") or "").strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, re.I | re.S)
        if fenced is not None:
            text = fenced.group(1)
        if not text.startswith("{"):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("lane") == lane:
            candidates.append(value)
    if not candidates:
        raise ValueError("opencode_lane_result_not_found")
    return candidates[-1]


def _tool_input_blob(row: dict[str, Any]) -> str:
    part = row["part"]
    if part.get("type") != "tool":
        return ""
    state = part.get("state") or {}
    return json.dumps(state.get("input") or {}, ensure_ascii=False, sort_keys=True)


def _evidence_blob(rows: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for row in rows:
        part = row["part"]
        kind = part.get("type")
        if kind == "tool":
            state = part.get("state") or {}
            values.append(json.dumps(state.get("input") or {}, ensure_ascii=False, sort_keys=True))
            values.append(str(state.get("output") or ""))
        elif kind == "reasoning":
            values.append(str(part.get("text") or ""))
    return "\n".join(values).replace("\\\"", '"')


def _target_segments(
    rows: list[dict[str, Any]], target_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    starts: list[int | None] = []
    cursor = 0
    for booking_id in target_ids:
        found: int | None = None
        for index in range(cursor, len(rows)):
            part = rows[index]["part"]
            if part.get("type") != "tool" or not str(part.get("tool") or "").startswith("paseo_browser_"):
                continue
            if booking_id in _tool_input_blob(rows[index]):
                found = index
                cursor = index + 1
                break
        starts.append(found)

    segments: dict[str, list[dict[str, Any]]] = {}
    for position, booking_id in enumerate(target_ids):
        start = starts[position]
        if start is None:
            segments[booking_id] = []
            continue
        later = [item for item in starts[position + 1 :] if item is not None and item > start]
        end = min(later) if later else len(rows)
        segments[booking_id] = rows[start:end]
    return segments


def _date_observed(value: object, evidence: str) -> bool:
    if value in (None, ""):
        return True
    text = str(value)
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match is None:
        return text in evidence
    year, month, day = match.groups()
    variants = {
        text,
        f"{year}-{int(month)}-{int(day)}",
        f"{year}년 {int(month)}월 {int(day)}일",
        f"{year}/{int(month)}/{int(day)}",
    }
    return any(item in evidence for item in variants)


def _attest_record(record: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    if record.get("detail_success") is not True:
        return []
    evidence = _evidence_blob(rows)
    compact = evidence.replace(",", "").replace(" ", "")
    failures: list[str] = []
    booking_id = str(record.get("booking_id") or "")
    if not rows or booking_id not in evidence:
        failures.append("booking_identity")
    if DETAIL_SELECTOR not in evidence or not re.search(
        r'(?:clicked|dispatched|ready)\\?"?\s*:\s*true', evidence, re.I
    ):
        failures.append("detail_selector")
    observed = str(record.get("observed_booking_id") or booking_id)
    if observed not in evidence:
        failures.append("observed_booking_identity")
    if not _date_observed(record.get("check_in"), evidence):
        failures.append("check_in")
    if not _date_observed(record.get("check_out"), evidence):
        failures.append("check_out")
    for component in record.get("price_components") or []:
        amount = str(component.get("decimal_text") or "").replace(",", "").replace(" ", "")
        if amount and amount not in compact:
            failures.append(f"amount:{amount}")
    card4 = str(record.get("card4") or "")
    if card4 and card4 not in evidence:
        failures.append("card4")
    if record.get("card_observation_status") == "confirmed_non_card":
        if not re.search(r"신용카드\s*필요\s*없음|non.?card[^\n]{0,30}true", evidence, re.I):
            failures.append("non_card_status")
    reference = str(record.get("reference_code") or "")
    if reference and reference not in evidence:
        failures.append("reference_code")
    panel_false = re.search(
        r'(?:panelVisible|panel_visible|panel)\\?"?\s*:\s*false', evidence, re.I
    )
    if panel_false is None:
        failures.append("panel_false")
    return failures


def export_batch(
    database: Path,
    session_id: str,
    lane: str,
    output: Path,
    *,
    evidence_lane: str | None = None,
) -> dict[str, Any]:
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        parts = _parts(db, session_id)
    finally:
        db.close()
    prompt_time = _find_prompt_time(parts, evidence_lane or lane, first=evidence_lane is not None)
    batch = _find_batch(parts, lane, prompt_time)
    scoped = [row for row in parts if row["created"] >= prompt_time]

    targets = [str(value) for value in batch.get("targets") or []]
    records = batch.get("records") or []
    if len(targets) != len(set(targets)) or not targets:
        raise ValueError("opencode_target_set_invalid")
    by_id = {str(record.get("booking_id") or ""): record for record in records if isinstance(record, dict)}
    if set(by_id) != set(targets):
        raise ValueError("opencode_record_target_set_mismatch")

    segments = _target_segments(scoped, targets)
    verified: list[str] = []
    downgraded: dict[str, list[str]] = {}
    safe_records: list[dict[str, Any]] = []
    for booking_id in targets:
        record = by_id[booking_id]
        failures = _attest_record(record, segments[booking_id])
        if failures:
            downgraded[booking_id] = failures
            safe_records.append({
                "booking_id": booking_id,
                "detail_success": False,
                "panel_visible": False,
                "failure_code": "EVIDENCE_ATTESTATION_MISMATCH",
            })
            continue
        if record.get("detail_success") is True:
            normalize_worker_record(record)
            verified.append(booking_id)
        safe_records.append(record)

    safe_batch = dict(batch)
    safe_batch["records"] = safe_records
    safe_batch["writes"] = 0
    safe_batch["evidence_audit"] = {
        "source_session_id": session_id,
        "verified_success_ids": verified,
        "downgraded": downgraded,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(safe_batch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "lane": lane,
        "targets": len(targets),
        "worker_records": len(records),
        "verified_success": len(verified),
        "downgraded": downgraded,
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--evidence-lane")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(
        export_batch(
            args.database,
            args.session_id,
            args.lane,
            args.output,
            evidence_lane=args.evidence_lane,
        ),
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
