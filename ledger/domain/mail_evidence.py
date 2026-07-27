"""Gmail 검색 결과를 append-only 실증으로 기록하는 최소 도메인."""
from __future__ import annotations

import hashlib
import json
import sqlite3


def record_mail_search(
    db: sqlite3.Connection,
    evidence_id: str,
    payment_external_key: str,
    *,
    query: str,
    query_version: str,
    account_scope: str,
    search_complete: bool,
    searched_at: str,
    result_status: str,
    candidate_count: int,
    actor: str,
    message_id: str | None = None,
    candidate_message_ids: list[str] | None = None,
    subject: str | None = None,
    observed_amount_krw: int | None = None,
    supersedes_evidence_id: str | None = None,
) -> bool:
    """같은 evidence_id의 재실행은 멱등이며 기존 사실을 덮어쓰지 않는다."""
    if result_status == "found" and (candidate_count <= 0 or not message_id):
        raise ValueError("found 메일 실증에는 candidate_count와 message_id가 필요합니다.")
    candidates = candidate_message_ids or []
    if result_status == "not_found" and (
        candidate_count != 0 or message_id or not search_complete
    ):
        raise ValueError("not_found는 완료된 검색의 후보 0건과 빈 message_id여야 합니다.")
    query_sha256 = hashlib.sha256(query.encode("utf-8")).hexdigest()
    before = db.total_changes
    db.execute(
        """
        INSERT OR IGNORE INTO mail_search_evidence(
            evidence_id, payment_external_key, query_sha256, query_version,
            account_scope, search_complete, searched_at, result_status,
            candidate_count, candidate_message_ids_json, message_id, subject,
            observed_amount_krw, actor, supersedes_evidence_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            payment_external_key,
            query_sha256,
            query_version,
            account_scope,
            int(search_complete),
            searched_at,
            result_status,
            int(candidate_count),
            json.dumps(candidates, ensure_ascii=False, sort_keys=True),
            message_id,
            subject,
            observed_amount_krw,
            actor,
            supersedes_evidence_id,
        ),
    )
    return db.total_changes > before


def mail_claim_strength(row: sqlite3.Row | dict[str, object]) -> str:
    """실제 message_id가 있는 found만 자동확정에 사용할 수 있다."""
    return (
        "strong"
        if row["result_status"] == "found" and row["message_id"]
        else "absence_scoped"
        if row["result_status"] == "not_found"
        else "insufficient"
    )
