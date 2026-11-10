"""Phase 3 synthetic card import (working DB only).

Synthetic CSV profile `synthetic-card-v1` first; real card profiles reuse
the existing ledger parsers later. No originals leave the server.

Columns: occurred_on, merchant, amount_krw, currency, card_last4,
approval_no, cancel_flag, suggested_tab, memo, card_kind.
`card_kind` is an optional card source column. It is not a required
column, so an older profile still parses, and it does not join the
content digest, so the existing dedupe and conflict contract is
unchanged. `classify_parsed` is the single place that turns a source
row into the direction and card kind used by classification rules.
Required: occurred_on, merchant, amount_krw. Missing required columns or
bad values keep the source row in import errors, never as a 0-won row.

Stable row key: sha256 of profile + occurred_on + merchant + amount +
currency + card_last4 + approval_no. Same file hash re-upload reuses the
batch. Same stable key in another file skips the existing event and only
adds new ones. Same key with different content stays a conflict; both
source rows are preserved and nothing merges.

Event kinds: cancel_flag=1 -> cancellation, amount<0 -> refund,
amount==0 -> import error. One source row yields at most one event, and
source-row counts and event counts are reported separately.

Classification mirrors the owner policy: a suggested trip tab from
the existing pipeline goes straight to that tab as auto_classified, no
per-row approval. Rows without a decidable destination stay in
unclassified. Display placement never promotes accounting authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from .import_source import parse_csv_rows, verify_source_bytes

from .space_guard import (IMPORT_FILE_OVERHEAD_BYTES, IMPORT_ROW_BYTES,
                           SpaceRefused, reserve, reserve_conn)

PROFILE_ID = "synthetic-card-v1"
REQUIRED_COLUMNS = ("occurred_on", "merchant", "amount_krw")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
CHUNK_SIZE = 50

# Bytes one import summary update costs.
IMPORT_SUMMARY_BYTES = 4 * 1024


def _database_file(conn) -> str:
    """The file this connection writes to, for a free-space probe.

    `PRAGMA database_list` is the connection's own answer. Guessing from an
    attribute would be a second source of truth about where the ledger lives,
    and a probe on the wrong volume is a probe of the wrong disk.
    """
    row = conn.execute("PRAGMA database_list").fetchone()
    if row and row[2]:
        return row[2]
    return "."


def reserve_acceptance_space(content: bytes, conn) -> None:
    """Refuse a card file the volume cannot hold.

    Raises `SpaceRefused` before the caller writes a batch row, so a refused
    file leaves no trace and cannot be mistaken for a received one. The file's
    own bytes plus a fixed allowance for the rows it will produce is what is
    asked for; the allowance is stated as an allowance.
    """
    reserve(_database_file(conn),
            len(content) + IMPORT_FILE_OVERHEAD_BYTES,
            code="IMPORT_NO_SPACE", what="카드 파일을 받는 데")


# The output path raises the same class. One name at the seam keeps a caller
# from having to know which module a refusal came from.
SourceFileRefused = SpaceRefused

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS card_import_batches (
    batch_id TEXT PRIMARY KEY,
    file_sha256 TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_rows INTEGER NOT NULL DEFAULT 0,
    parsed_ok INTEGER NOT NULL DEFAULT 0,
    parse_errors INTEGER NOT NULL DEFAULT 0,
    new_events INTEGER NOT NULL DEFAULT 0,
    skipped_existing INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    placed_trips INTEGER NOT NULL DEFAULT 0,
    placed_unclassified INTEGER NOT NULL DEFAULT 0,
    cursor_index INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS card_import_rows (
    batch_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    stable_key TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (batch_id, row_index)
);
CREATE INDEX IF NOT EXISTS idx_card_import_rows_key
    ON card_import_rows(stable_key);
CREATE TABLE IF NOT EXISTS source_blobs (
    batch_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    content BLOB NOT NULL,
    created_at TEXT NOT NULL
);
"""

TRIP_TABS = ("trip-demo-a", "trip-demo-b")

ERRORS = ("IMPORT_TOO_LARGE", "IMPORT_BAD_FORMAT", "IMPORT_CONFLICT")


class ImportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_content_digest(fields: dict) -> str:
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_cancel_flag(fields: dict) -> str:
    return "1" if str(fields.get("cancel_flag", "") or "").strip() in (
        "1", "Y", "y", "true") else ""


def stable_key(fields: dict) -> str:
    # R08: 안정 식별자와 내용 digest를 분리한다. 승인번호가 있으면
    # 승인번호·카드뒷자리를 식별 근거로 쓰고, 금액·가맹점 같은 가변
    # 원문은 키에 넣지 않는다. 취소 구분은 내용 digest에서 다룬다.
    approval = str(fields.get("approval_no", "") or "").strip()
    last4 = str(fields.get("card_last4", "") or "").strip()
    if approval:
        parts = [PROFILE_ID, last4, approval]
    else:
        parts = [
            PROFILE_ID,
            str(fields.get("occurred_on", "")),
            str(fields.get("merchant", "")),
            str(fields.get("amount_krw", "")),
            str(fields.get("currency", "") or ""),
            last4,
            _normalize_cancel_flag(fields),
            "no-approval",
        ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def content_digest(event: dict) -> str:
    base = "|".join([
        str(event.get("occurred_on", "")),
        str(event.get("merchant", "")),
        str(event.get("amount_krw", "")),
        str(event.get("currency", "") or ""),
        str(event.get("card_last4", "") or ""),
        str(event.get("approval_no", "") or ""),
        str(event.get("event_kind", "")),
        str(event.get("display_tab_id", "") or ""),
        str(event.get("memo", "") or ""),
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def parse_csv(content: bytes):
    return parse_csv_rows(content, REQUIRED_COLUMNS, ImportError, "IMPORT_BAD_FORMAT")


def classify_parsed(fields: dict):
    """Return (ok, event_fields | error_note)."""
    occurred = fields.get("occurred_on", "")
    merchant = fields.get("merchant", "")
    raw_amount = fields.get("amount_krw", "")
    if not occurred or not merchant or not raw_amount:
        return False, "필수 값이 비었어요"
    import re

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", occurred):
        return False, "날짜 형식이 달라요"
    try:
        amount = int(raw_amount.replace(",", ""))
    except ValueError:
        return False, "금액이 숫자가 아니에요"
    if amount == 0:
        return False, "0원 행은 장부에 넣지 않아요"
    cancel = str(fields.get("cancel_flag", "") or "").strip() in ("1", "Y", "y", "true")
    kind = "cancellation" if cancel else ("refund" if amount < 0 else "purchase")
    suggested = (fields.get("suggested_tab") or "").strip()
    if suggested in TRIP_TABS:
        tab, state = suggested, "auto_classified"
    else:
        tab, state = None, "unclassified"
    return True, {
        "occurred_on": occurred,
        "merchant": merchant,
        "amount_krw": amount,
        "currency": (fields.get("currency") or "KRW").strip() or "KRW",
        "card_last4": (fields.get("card_last4") or "").strip(),
        "approval_no": (fields.get("approval_no") or "").strip(),
        "event_kind": kind,
        "display_tab_id": tab,
        "classification_state": state,
        "memo": (fields.get("memo") or "").strip(),
        "card_kind": (fields.get("card_kind") or "").strip(),
    }


class CardImporter:
    def __init__(self, conn: sqlite3.Connection, store):
        self.conn = conn
        self.store = store
        self.conn.executescript(SCHEMA_SQL)
        try:
            cols = {r[1] for r in self.conn.execute(
                "PRAGMA table_info(card_import_batches)").fetchall()}
            if "duplicate_candidates" not in cols:
                self.conn.execute(
                    "ALTER TABLE card_import_batches"
                    " ADD COLUMN duplicate_candidates INTEGER NOT NULL DEFAULT 0")
                self.conn.commit()
        except Exception:
            pass

    def receive(self, content: bytes, file_name: str) -> dict:
        if len(content) > MAX_UPLOAD_BYTES:
            raise ImportError("IMPORT_TOO_LARGE", "파일이 너무 커요")
        # SPEC_REFINEMENT 19.3: a volume that cannot hold the file refuses the
        # *acceptance*, before any batch row exists, so a file that was never
        # received is not recorded as received. The digest is computed first so
        # a re-upload of a file that is already stored is answered from the
        # existing batch rather than refused for space it does not need.
        digest = _sha256_bytes(content)
        batch_id = f"imp-{digest[:16]}"
        existing = self.conn.execute(
            "SELECT batch_id, status, result_json FROM card_import_batches WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
        if existing:
            return {"batch_id": existing[0], "reused": True,
                    "status": existing[1], "result": json.loads(existing[2])}
        reserve_acceptance_space(content, self.conn)
        rows = parse_csv(content)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "INSERT INTO card_import_batches(batch_id, file_sha256, file_name, file_size,"
                " profile_id, status, source_rows, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (batch_id, digest, file_name[:200], len(content), PROFILE_ID,
                 "parsing", len(rows), _utc_now()),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO source_blobs(batch_id, sha256, size, content, created_at)"
                " VALUES (?,?,?,?,?)",
                (batch_id, digest, len(content), bytes(content), _utc_now()),
            )
            for position, (index, fields) in enumerate(rows):
                key = stable_key(fields)
                ok, payload = classify_parsed(fields)
                self.conn.execute(
                    "INSERT INTO card_import_rows(batch_id, row_index, stable_key, raw_json, status, note)"
                    " VALUES (?,?,?,?,?,?)",
                    (batch_id, position, key, json.dumps(fields, ensure_ascii=False),
                     "parsed" if ok else "error",
                     "" if ok else str(payload)),
                )
                if ok:
                    self.conn.execute(
                        "UPDATE card_import_batches SET parsed_ok=parsed_ok+1 WHERE batch_id=?",
                        (batch_id,),
                    )
                else:
                    self.conn.execute(
                        "UPDATE card_import_batches SET parse_errors=parse_errors+1 WHERE batch_id=?",
                        (batch_id,),
                    )
            self.conn.execute(
                "UPDATE card_import_batches SET status='reconciling' WHERE batch_id=?",
                (batch_id,),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return {"batch_id": batch_id, "reused": False, "status": "reconciling"}

    def process_to_completion(self, batch_id: str, chunk: int = 200) -> dict:
        """R03: 저장된 미처리 범위를 끝까지 처리한다. 단일 작업자, 재개 가능."""
        guard = 0
        while True:
            result = self.process(batch_id, limit=chunk)
            guard += 1
            if result.get("status") != "reconciling" or guard > 1000:
                return result

    def reset_stuck(self) -> int:
        """시작 시 처리 중 표시를 재개 가능 상태로 되돌린다."""
        cursor = self.conn.execute(
            "UPDATE card_import_batches SET status='reconciling' WHERE status='processing'"
        )
        self.conn.commit()
        return cursor.rowcount


    def process(self, batch_id: str, limit: int | None = None) -> dict:
        """Reconcile parsed rows from cursor. Returns batch summary.

        19.3: the file was already accepted, so the space it needs was already
        reserved once. This loop writes the parsed rows, their events and their
        decisions, so it reserves for the rows it is about to write rather than
        assuming the acceptance reservation covered them. A refusal here leaves
        the batch at its cursor, which is what makes the retry honest.
        """
        limit = CHUNK_SIZE if limit is None else limit
        rows = self.conn.execute(
            "SELECT row_index, stable_key, raw_json, status FROM card_import_rows"
            " WHERE batch_id=? AND row_index>=(SELECT cursor_index FROM card_import_batches"
            " WHERE batch_id=?) AND status='parsed' ORDER BY row_index LIMIT ?",
            (batch_id, batch_id, limit),
        ).fetchall()
        # Nothing to write, so nothing to reserve for. Reserving anyway would
        # refuse an empty batch on a full volume for no reason.
        if not rows:
            return self._process_rows(batch_id, rows)
        with reserve_conn(self.conn, len(rows) * IMPORT_ROW_BYTES,
                          code="IMPORT_ROW_NO_SPACE",
                          what="가져온 카드 행을 기록하는 데"):
            return self._process_rows(batch_id, rows)

    def _process_rows(self, batch_id: str, rows) -> dict:
        for row_index, key, raw_json, _ in rows:
            fields = json.loads(raw_json)
            ok, event = classify_parsed(fields)
            assert ok
            digest = content_digest(event)
            same_file = self.conn.execute(
                "SELECT raw_json FROM card_import_rows WHERE stable_key=?"
                " AND batch_id=? AND row_index<?",
                (key, batch_id, row_index),
            ).fetchall()
            same_file_digests = []
            for (other_raw,) in same_file:
                other_fields = json.loads(other_raw)
                other_ok, other_event = classify_parsed(other_fields)
                same_file_digests.append(
                    content_digest(other_event) if other_ok else None)
            if any(d is None or d != digest for d in same_file_digests):
                self._mark(batch_id, row_index, "conflict", "같은 키에 다른 내용이에요")
                self._bump(batch_id, "conflicts")
                continue
            if same_file_digests:
                self._mark(batch_id, row_index, "duplicate-candidate",
                           "같은 파일의 동일 내용입니다. 사용자 확인이 필요합니다.")
                self._bump(batch_id, "duplicate_candidates")
                continue
            conflict = False
            for (other_raw,) in self.conn.execute(
                "SELECT raw_json FROM card_import_rows WHERE stable_key=?"
                " AND batch_id!=?",
                (key, batch_id),
            ).fetchall():
                other_fields = json.loads(other_raw)
                other_ok, other_event = classify_parsed(other_fields)
                if not other_ok or content_digest(other_event) != digest:
                    conflict = True
                    break
            if conflict:
                self._mark(batch_id, row_index, "conflict", "같은 키에 다른 내용이에요")
                self._bump(batch_id, "conflicts")
                continue
            dup = self.store.get_row(f"imp-{key[:16]}")
            if dup is not None:
                same = (
                    str(dup.get("occurred_on", "")) == str(event["occurred_on"])
                    and str(dup.get("description", "")) == str(event["merchant"])
                    and dup.get("amount_krw") == event["amount_krw"]
                    and str(dup.get("source_event_id", "")) == str(event["approval_no"] or f"imp-{key[:16]}")
                    and (dup.get("display_tab_id") is None) == (event["display_tab_id"] is None)
                    and str(dup.get("display_tab_id") or "") == str(event["display_tab_id"] or "")
                )
                if same:
                    self._mark(batch_id, row_index, "skipped", "이미 있는 거래예요")
                    self._bump(batch_id, "skipped_existing")
                else:
                    self._mark(batch_id, row_index, "conflict", "같은 키에 다른 내용이에요")
                    self._bump(batch_id, "conflicts")
            else:
                self.store.import_row(
                    row_id=f"imp-{key[:16]}",
                    fields=event,
                    batch_id=batch_id,
                    client_request_id=f"{batch_id}-{row_index}",
                )
                self._mark(batch_id, row_index, "placed",
                           "여행 탭 배치" if event["display_tab_id"] else "귀속 전")
                self._bump(batch_id, "new_events")
                self._bump(batch_id, "placed_trips" if event["display_tab_id"] else "placed_unclassified")
            self.conn.execute(
                "UPDATE card_import_batches SET cursor_index=? WHERE batch_id=?",
                (row_index + 1, batch_id),
            )
            self.conn.commit()
        return self.finish(batch_id)

    def _mark(self, batch_id, row_index, status, note):
        self.conn.execute(
            "UPDATE card_import_rows SET status=?, note=? WHERE batch_id=? AND row_index=?",
            (status, note, batch_id, row_index),
        )

    def _bump(self, batch_id, column):
        self.conn.execute(
            f"UPDATE card_import_batches SET {column}={column}+1 WHERE batch_id=?",
            (batch_id,),
        )

    def _batch_counters(self, batch_id: str) -> dict:
        try:
            row = self.conn.execute(
                "SELECT source_rows, parsed_ok, parse_errors, new_events, skipped_existing,"
                " conflicts, placed_trips, placed_unclassified, cursor_index,"
                " duplicate_candidates FROM card_import_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
            if row is None:
                return {}
            return {
                "source_rows": row[0], "parsed_ok": row[1], "parse_errors": row[2],
                "new_events": row[3], "skipped_existing": row[4], "conflicts": row[5],
                "placed_trips": row[6], "placed_unclassified": row[7],
                "cursor_index": row[8], "duplicate_candidates": row[9],
            }
        except Exception:
            row = self.conn.execute(
                "SELECT source_rows, parsed_ok, parse_errors, new_events, skipped_existing,"
                " conflicts, placed_trips, placed_unclassified, cursor_index"
                " FROM card_import_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
            if row is None:
                return {}
            return {
                "source_rows": row[0], "parsed_ok": row[1], "parse_errors": row[2],
                "new_events": row[3], "skipped_existing": row[4], "conflicts": row[5],
                "placed_trips": row[6], "placed_unclassified": row[7],
                "cursor_index": row[8], "duplicate_candidates": 0,
            }

    def finish(self, batch_id: str) -> dict:
        counters = self._batch_counters(batch_id)
        remaining = self.conn.execute(
            "SELECT COUNT(*) FROM card_import_rows WHERE batch_id=? AND status='parsed'",
            (batch_id,),
        ).fetchone()[0]
        status = "completed" if remaining == 0 else "reconciling"
        if counters.get("parse_errors", 0) > 0 and status == "completed":
            status = "completed_with_issues"
        result = {
            "batch_id": batch_id, "status": status,
            "source_rows": counters.get("source_rows", 0),
            "parsed_ok": counters.get("parsed_ok", 0),
            "parse_errors": counters.get("parse_errors", 0),
            "new_events": counters.get("new_events", 0),
            "skipped_existing": counters.get("skipped_existing", 0),
            "conflicts": counters.get("conflicts", 0),
            "duplicate_candidates": counters.get("duplicate_candidates", 0),
            "placed_trips": counters.get("placed_trips", 0),
            "placed_unclassified": counters.get("placed_unclassified", 0),
        }
        # 19.3: the summary is the record that says the import finished, so a
        # volume that cannot take it must not be told the import completed. The
        # refusal leaves the batch status as it was, which is the honest state.
        with reserve_conn(self.conn, IMPORT_SUMMARY_BYTES,
                          code="IMPORT_SUMMARY_NO_SPACE",
                          what="가져오기 결과를 기록하는 데"):
            self.conn.execute(
                "UPDATE card_import_batches SET status=?, result_json=? WHERE batch_id=?",
                (status, json.dumps(result, ensure_ascii=False), batch_id),
            )
            self.conn.commit()
        return result

    def progress(self, batch_id: str):
        row = self.conn.execute(
            "SELECT batch_id, file_name, file_size, status, result_json"
            " FROM card_import_batches WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
        if row is None:
            return None
        result = json.loads(row[4])
        counters = self._batch_counters(batch_id)
        return {
            "batch_id": row[0], "file_name": row[1], "file_size": row[2], "status": row[3],
            "source_rows": result.get("source_rows", counters.get("source_rows", 0)),
            "parsed_ok": result.get("parsed_ok", counters.get("parsed_ok", 0)),
            "parse_errors": result.get("parse_errors", counters.get("parse_errors", 0)),
            "new_events": result.get("new_events", counters.get("new_events", 0)),
            "skipped_existing": result.get("skipped_existing",
                                           counters.get("skipped_existing", 0)),
            "conflicts": result.get("conflicts", counters.get("conflicts", 0)),
            "duplicate_candidates": result.get("duplicate_candidates",
                                               counters.get("duplicate_candidates", 0)),
            "placed_trips": result.get("placed_trips", counters.get("placed_trips", 0)),
            "placed_unclassified": result.get("placed_unclassified",
                                              counters.get("placed_unclassified", 0)),
            "cursor_index": counters.get("cursor_index", 0),
            "result": result,
        }


class CardWorker:
    """R03: 접수와 처리 실행을 분리한 단일 작업자.

    외부 큐 없이 DB의 작업 상태·커서로 동작한다. 접수 응답은 즉시
    반환하고, 이 작업자가 백그라운드에서 묶음씩 처리한다. 중단 뒤에는
    같은 작업을 이어가며 파일 재업로드를 요구하지 않는다.
    """

    def __init__(self, db_path, chunk: int = 20, idle_poll: float = 0.3):
        self.db_path = str(db_path)
        self.chunk = chunk
        self.idle_poll = idle_poll
        self._stop = None
        self._thread = None

    def start(self):
        import threading

        if self._thread is not None:
            return self._thread
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self, timeout: float = 5.0) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        from .ledger_store import LedgerStore

        store = LedgerStore(self.db_path)
        try:
            importer = CardImporter(store.conn, store)
            importer.reset_stuck()
            while self._stop is not None and not self._stop.is_set():
                try:
                    worked = self.sweep_once(importer)
                except Exception:
                    worked = False
                if not worked:
                    self._stop.wait(self.idle_poll)
        finally:
            try:
                store.close()
            except Exception:
                pass

    def sweep_once(self, importer: CardImporter | None = None) -> bool:
        """미완료 묶음 하나를 한 묶음만큼 처리한다. 동작했으면 True."""
        close_store = False
        if importer is None:
            from .ledger_store import LedgerStore

            store = LedgerStore(self.db_path)
            importer = CardImporter(store.conn, store)
            close_store = True
        try:
            row = importer.conn.execute(
                "SELECT batch_id FROM card_import_batches WHERE status='reconciling'"
                " ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            batch_id = row[0]
            claimed = importer.conn.execute(
                "UPDATE card_import_batches SET status='processing' WHERE batch_id=?"
                " AND status='reconciling'",
                (batch_id,),
            )
            importer.conn.commit()
            if claimed.rowcount == 0:
                return False
            try:
                result = importer.process(batch_id, limit=self.chunk)
            finally:
                rest = importer.conn.execute(
                    "SELECT status FROM card_import_batches WHERE batch_id=?",
                    (batch_id,),
                ).fetchone()
                if rest is not None and rest[0] == "processing":
                    importer.conn.execute(
                        "UPDATE card_import_batches SET status='reconciling'"
                        " WHERE batch_id=?",
                        (batch_id,),
                    )
                    importer.conn.commit()
            return result.get("status") in ("completed", "completed_with_issues",
                                            "reconciling", "processing")
        finally:
            if close_store:
                try:
                    importer.store.close()
                except Exception:
                    pass
