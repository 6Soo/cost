"""Read-only, local-only diagnostic for OTA observations and card coverage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ota_mail, ota_payments, ota_portal, ota_sources, ota_review
from app.reconcile.observations import inspect_observations
from app.reconcile.trace import build_coverage_report, pseudonym


def _read_rows(path, table):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            raise ValueError("REQUIRED_TABLE_MISSING")
        return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')]


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _source_digest(sources):
    try:
        stamps = ota_sources.source_stamps(sources)
        payload = json.dumps(stamps, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(payload).hexdigest(), len(stamps)
    except Exception as exc:
        return None, type(exc).__name__


def _snapshot_summary(review_db):
    if not review_db:
        return {"generation": None, "generated_at": None, "age_seconds": None,
                "stale": None, "status": "SNAPSHOT_PATH_NOT_PROVIDED"}
    path = Path(review_db).resolve().parent / "ota-snapshot.json"
    if not path.is_file():
        return {"generation": None, "generated_at": None, "age_seconds": None,
                "stale": None, "status": "SNAPSHOT_NOT_FOUND"}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(str(document["generated_at"]).replace("Z", "+00:00"))
        age = max(0, int((datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds()))
        return {"generation": int(document.get("generation") or 0),
                "generated_at": generated.isoformat(), "age_seconds": age,
                "stale": age > 150, "status": "SNAPSHOT_STALE" if age > 150 else "SNAPSHOT_FRESH"}
    except Exception as exc:
        return {"generation": None, "generated_at": None, "age_seconds": None,
                "stale": None, "status": "SNAPSHOT_UNREADABLE_" + type(exc).__name__}


def audit(*, board_db, output_dir, data_dir=None, review_db=None, manifest=None):
    board_path = Path(board_db).resolve(strict=True)
    data_path = Path(data_dir).resolve() if data_dir else board_path.parent
    mail_default = Path(os.environ.get("WEBLEDGER_OTA_MAIL_DIR", data_path / "ota-mail"))
    portal_default = ota_portal.evidence_path(data_path)
    failures = []
    try:
        sources = ota_sources.resolve_sources(data_path, mail_default=mail_default,
                                              portal_default=portal_default,
                                              manifest_file=manifest)
    except Exception as exc:
        sources = {"mail_directories": [], "portal_databases": [], "reference_documents": [],
                   "registered": {}, "missing": [], "diagnostics": []}
        failures.append(type(exc).__name__)
    for item in sources.get("missing", ()):
        failures.append("SOURCE_MISSING:" + str(item.get("kind", "unknown")))
    for item in sources.get("diagnostics", ()):
        failures.append("SOURCE_DIAGNOSTIC")

    cards = _read_rows(board_path, "transactions")
    events = []
    observations = {"raw_observations": 0, "skipped_observation_count": 0,
                    "skipped_reason_counts": {}, "skipped": []}
    try:
        events = ota_payments.build_ota_payment_events(sources)
        observations = inspect_observations(sources, events)
        if observations["skipped_reason_counts"].get("SOURCE_UNREADABLE"):
            failures.append("SOURCE_UNREADABLE")
    except Exception as exc:
        failures.append(type(exc).__name__)
        try:
            observations = inspect_observations(sources, events)
        except Exception:
            pass

    legacy_links, user_links, frozen_groups = {}, {}, []
    if review_db:
        path = Path(review_db).resolve()
        try:
            store = ota_review.OtaReviewStore(path)
            if store.conn:
                user_links = store.links()
                frozen_groups = store.group_pins()
                store.close()
        except Exception as exc:
            failures.append("REVIEW_SOURCE_" + type(exc).__name__)

    try:
        if events and cards and all(k in row for row in cards for k in (
                "transaction_id", "source_hash", "merchant", "merchant_normalized", "card_kind",
                "transaction_direction", "approval_date", "amount_krw", "card_tail")):
            mail_report = ota_mail.match_mail(sources.get("mail_directories", []), cards)
            legacy_report = ota_portal.extend_report(mail_report, sources.get("portal_databases", []), cards)
            from webapp.ota_payment_review import legacy_exact_bindings
            legacy_links = legacy_exact_bindings(events, cards, legacy_report)
    except Exception as exc:
        failures.append("LEGACY_MATCHER_" + type(exc).__name__)

    run_secret = secrets.token_bytes(32)
    reconciliation_results = []
    try:
        if events and cards:
            reconciliation_results = ota_payments.match_ota_payment_events(
                events, cards, existing_links=legacy_links | user_links,
                frozen_groups=frozen_groups)
    except Exception as exc:
        failures.append("RECONCILIATION_ENGINE_" + type(exc).__name__)
    summary, cases = build_coverage_report(
        events=events, cards=cards, legacy_links=legacy_links, user_links=user_links,
        frozen_groups=frozen_groups, source_diagnostics=sorted(set(failures)),
        observation_report=observations, run_secret=run_secret,
        reconciliation_results=reconciliation_results)
    version, stamp_count = _source_digest(sources)
    summary["snapshot"] = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "registered_input_version_sha256": version,
        "registered_input_count": stamp_count if isinstance(stamp_count, int) else None,
        "input_stamp_error": stamp_count if isinstance(stamp_count, str) else None,
        **_snapshot_summary(review_db),
    }
    summary["privacy"] = {
        "report_scope": "LOCAL_ONLY",
        "identifiers": "RANDOM_PER_RUN_HMAC_PSEUDONYMS",
        "pseudonym_key_persisted": False,
        "raw_card_tail_booking_reference_and_message_body_included": False,
    }
    summary["run_mode"] = "READ_ONLY"

    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    _write_jsonl(destination / "unmatched-cases.jsonl", cases)
    diff = []
    for event_id, legacy in legacy_links.items():
        event = next((item for item in events if str(item.get("ota_event_id")) == str(event_id)), None)
        legacy_card = str(legacy.get("transaction_id") or "") if isinstance(legacy, dict) else str(legacy or "")
        if event is None:
            difference = "LEGACY_EVENT_NOT_IN_CURRENT_SOURCE"
        else:
            candidates = [case for case in cases if case.get("direction") == "OTA_TO_CARD"
                          and case.get("id") == pseudonym(run_secret, "ota", event_id)]
            candidate_ids = set()
            if candidates:
                candidate_ids = {entry["id"] for entry in candidates[0].get("candidates", ())}
            if pseudonym(run_secret, "card", legacy_card) in candidate_ids:
                continue
            difference = "LEGACY_NEW_CORE_DISAGREEMENT"
        diff.append({"id": pseudonym(run_secret, "legacy", event_id), "difference": difference,
                     "user_pinned": str(event_id) in user_links})
    _write_jsonl(destination / "legacy-diff.jsonl", diff)
    _write_jsonl(destination / "reconciliation-diff.jsonl",
                 summary.pop("reconciliation_divergences", []))
    _write_json(destination / "coverage-summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", required=True,
                        help="필수 안전 확인 플래그입니다. 모든 입력 SQLite를 mode=ro로 엽니다.")
    parser.add_argument("--board-db", required=True, help="읽기 전용 카드 원행 SQLite")
    parser.add_argument("--data-dir", help="OTA 기본 입력을 찾을 데이터 디렉터리")
    parser.add_argument("--manifest", help="사용할 OTA sources manifest")
    parser.add_argument("--review-db", help="기존 수동 연결/고정 묶음이 있는 분리 검토 SQLite")
    parser.add_argument("--output-dir", required=True, help="보고서를 저장할 로컬 전용 디렉터리")
    args = parser.parse_args(argv)
    try:
        summary = audit(board_db=args.board_db, output_dir=args.output_dir,
                        data_dir=args.data_dir, review_db=args.review_db, manifest=args.manifest)
    except Exception as exc:
        print(json.dumps({"status": "FAILED_READ_ONLY_AUDIT", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps({"status": summary["status"], "card_rows": summary["denominators"]["card_rows"],
                      "ota_events": summary["ota_event_count"], "reports": str(Path(args.output_dir).resolve())}))
    return 0 if summary["status"] == "COMPLETE_INPUTS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
