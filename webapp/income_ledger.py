"""Phase 4 income and manual-expense paths (synthetic working DB only).

Direct income: one event per row, customer link or pending, deposit /
balance / additional kinds. Direct rows allow date and amount edits
with history. Bank source rows are immutable; display corrections are
separate correction events. Refunds stay separate events with sign.

Bank CSV profile `synthetic-bank-v1` columns: occurred_on, payer_name,
amount_krw, direction, account_ref, transaction_id, memo. direction must
be credit for income; debit rows are excluded with a reason and kept in
the batch. Linking a bank row to a direct income attaches evidence and
adds no new income. Customer matching is by explicit customer_id only;
same display names never merge.

Manual expense: cash or transfer rows created directly with editable
date and amount plus history. The same save path still rejects amount
changes for card rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3

from .import_source import parse_csv_rows, verify_source_bytes

BANK_PROFILE_ID = "synthetic-bank-v1"
BANK_REQUIRED_COLUMNS = ("occurred_on", "payer_name", "amount_krw", "direction")
BANK_MAX_UPLOAD_BYTES = 5 * 1024 * 1024

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bank_import_batches (
    batch_id TEXT PRIMARY KEY,
    file_sha256 TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_rows INTEGER NOT NULL DEFAULT 0,
    credit_rows INTEGER NOT NULL DEFAULT 0,
    excluded_rows INTEGER NOT NULL DEFAULT 0,
    new_events INTEGER NOT NULL DEFAULT 0,
    skipped_existing INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bank_import_rows (
    batch_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    stable_key TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (batch_id, row_index)
);
CREATE TABLE IF NOT EXISTS source_blobs (
    batch_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    content BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS income_corrections (
    correction_id TEXT PRIMARY KEY,
    row_id TEXT NOT NULL,
    corrected_amount_krw INTEGER NOT NULL,
    corrected_occurred_on TEXT,
    row_revision INTEGER,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS income_source_links (
    row_id TEXT NOT NULL,
    bank_batch_id TEXT NOT NULL,
    bank_row_index INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (row_id, bank_batch_id, bank_row_index)
);
"""

ERRORS = ("BANK_TOO_LARGE", "BANK_BAD_FORMAT")


class BankImportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def bank_stable_key(fields: dict) -> str:
    # R08: 안정 식별자와 내용 digest를 분리한다. 거래 ID가 있으면 그것을
    # 식별 근거로 쓰고, 없으면 날짜·금액만으로 자동 중복 판정하지 않고
    # 입금자까지 함께 본다.
    txn = str(fields.get("transaction_id", "") or "").strip()
    acct = str(fields.get("account_ref", "") or "").strip()
    occurred = str(fields.get("occurred_on", "") or "").strip()
    amount = str(fields.get("amount_krw", "") or "").strip()
    payer = str(fields.get("payer_name", "") or "").strip()
    if txn:
        parts = [BANK_PROFILE_ID, acct, txn]
    elif acct:
        parts = [BANK_PROFILE_ID, acct, occurred, amount, payer]
    else:
        parts = [BANK_PROFILE_ID, occurred, amount, payer]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def bank_content_digest(payload: dict) -> str:
    base = "|".join([
        str(payload.get("occurred_on", "")),
        str(payload.get("payer_name", "")),
        str(payload.get("amount_krw", "")),
        str(payload.get("account_ref", "") or ""),
        str(payload.get("transaction_id", "") or ""),
        str(payload.get("memo", "") or ""),
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def raw_content_digest(fields: dict) -> str:
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_bank_csv(content: bytes):
    return parse_csv_rows(content, BANK_REQUIRED_COLUMNS, BankImportError, "BANK_BAD_FORMAT")


def classify_bank_row(fields: dict):
    import re

    occurred = fields.get("occurred_on", "")
    payer = fields.get("payer_name", "")
    raw_amount = fields.get("amount_krw", "")
    direction = (fields.get("direction") or "").strip().lower()
    if not occurred or not payer or not raw_amount:
        return False, "필수 값이 비었어요"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", occurred):
        return False, "날짜 형식이 달라요"
    try:
        amount = int(raw_amount.replace(",", ""))
    except ValueError:
        return False, "금액이 숫자가 아니에요"
    if direction not in ("credit", "입금"):
        return False, f"출금·내부이체는 수입으로 올리지 않아요: {direction or '방향 없음'}"
    if amount <= 0:
        return False, "0원 이하 입금은 수입 사건이 아니에요"
    return True, {
        "occurred_on": occurred,
        "payer_name": payer,
        "amount_krw": amount,
        "account_ref": (fields.get("account_ref") or "").strip(),
        "transaction_id": (fields.get("transaction_id") or "").strip(),
        "memo": (fields.get("memo") or "").strip(),
    }


def _main_db_file(conn: sqlite3.Connection):
    # PRAGMA database_list의 file 열은 열 때 쓴 경로다. :memory: 는 빈 문자열이라
    # 서로 다른 메모리 DB도 경로가 같아 보이므로, 비어 있으면 동일 DB로 증명할 수 없다.
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except sqlite3.Error:
        return None
    for row in rows:
        if len(row) >= 3 and row[1] == "main":
            path = row[2]
            if not path:
                return None
            return os.path.abspath(path)
    return None


class BankImporter:
    def __init__(self, conn: sqlite3.Connection, store):
        self.store = store
        # R02: 은행 적치 원자성 경계를 store가 실제 저장에 쓰는 커넥션(store.conn)으로
        # 고정한다. 호출자가 같은 DB 파일을 가리키는 별도 conn을 건네도 두 conn 모두
        # BEGIN을 시작해 "database is locked"가 되므로, 별도 conn이 *다른* DB를 가리킬
        # 때만 거르고(무시 금지) 원자성 단위는 store.conn으로 묶는다.
        # 외부 트랜잭션은 커밋하지 않는다. schema executescript의 암시적 COMMIT은
        # 생성 시점 계약이고 receive의 BEGIN IMMEDIATE 경계와 분리한다.
        if conn is not store.conn:
            caller = _main_db_file(conn)
            keeper = _main_db_file(store.conn)
            if caller is None or keeper is None or caller != keeper:
                raise BankImportError(
                    "BANK_DB_MISMATCH",
                    "은행 입력 커넥션과 원천 저장 커넥션이 다른 DB를 가리켜요",
                )
        self.conn = store.conn
        self.conn.executescript(SCHEMA_SQL)
        from .ledger_store import _ensure_correction_columns
        _ensure_correction_columns(self.conn)

    def receive(self, content: bytes, file_name: str) -> dict:
        if len(content) > BANK_MAX_UPLOAD_BYTES:
            raise BankImportError("BANK_TOO_LARGE", "파일이 너무 커요")
        digest = hashlib.sha256(content).hexdigest()
        # R08: batch_id는 내용 bytes의 sha256만으로 만든다. 파일명은 배치 식별자에
        # 포함하지 않는다. 같은 bytes는 이름이 달라도 같은 배치로 재사용되고,
        # source/event/candidate는 하나도 늘지 않는다.
        batch_id = f"bnk-{digest[:16]}"
        existing = self.conn.execute(
            "SELECT batch_id, result_json FROM bank_import_batches WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
        if existing:
            return {"batch_id": existing[0], "reused": True,
                    "result": json.loads(existing[1])}
        rows = parse_bank_csv(content)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "INSERT INTO bank_import_batches(batch_id, file_sha256, file_name, file_size,"
                " profile_id, status, source_rows, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (batch_id, digest, file_name[:200], len(content), BANK_PROFILE_ID,
                 "reconciling", len(rows), _utc_now()),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO source_blobs(batch_id, sha256, size, content, created_at)"
                " VALUES (?,?,?,?,?)",
                (batch_id, digest, len(content), bytes(content), _utc_now()),
            )
            credit = 0
            excluded = 0
            created = 0
            skipped = 0
            candidates = 0
            for position, (index, fields) in enumerate(rows):
                key = bank_stable_key(fields)
                digest_raw = raw_content_digest(fields)
                ok, payload = classify_bank_row(fields)
                if not ok:
                    status, note = "excluded", str(payload)
                    excluded += 1
                else:
                    same_file = self.conn.execute(
                        "SELECT raw_json FROM bank_import_rows WHERE stable_key=?"
                        " AND batch_id=?",
                        (key, batch_id),
                    ).fetchall()
                    conflict = any(
                        raw_content_digest(json.loads(r[0])) != digest_raw
                        for r in same_file
                    )
                    if conflict:
                        status, note = "excluded", "같은 식별자에 다른 내용이에요(충돌 보존)"
                        excluded += 1
                    elif same_file:
                        status, note = ("duplicate-candidate",
                                        "같은 파일의 동일 내용이에요. 사용자 확인이 필요해요")
                        candidates += 1
                    else:
                        cross = self.conn.execute(
                            "SELECT raw_json FROM bank_import_rows WHERE stable_key=?"
                            " AND batch_id!=?",
                            (key, batch_id),
                        ).fetchall()
                        cross_conflict = any(
                            raw_content_digest(json.loads(r[0])) != digest_raw
                            for r in cross
                        )
                        if cross_conflict:
                            status, note = "excluded", "같은 식별자에 다른 내용이에요(충돌 보존)"
                            excluded += 1
                        elif cross and not fields.get("transaction_id", "").strip():
                            # R08: 거래 ID 없는 파일 간 일치는 식별 근거가 부족하므로
                            # 자동 중복 판정이나 새 사건 생성을 하지 않고 후보로 보존한다.
                            status, note = (
                                "duplicate-candidate",
                                "파일 간 식별 근거가 없어 사용자 확인이 필요해요",
                            )
                            candidates += 1
                        else:
                            dup = self.store.get_row(f"bnk-{key[:16]}")
                            if dup is not None:
                                same = (
                                    str(dup.get("occurred_on", "")) == str(payload["occurred_on"])
                                    and str(dup.get("customer_name", "")) == str(payload["payer_name"])
                                    and dup.get("amount_krw") == payload["amount_krw"]
                                )
                                if same:
                                    status, note = "skipped", "이미 있는 입금이에요"
                                    skipped += 1
                                else:
                                    status, note = "excluded", "같은 식별자에 다른 내용이에요(충돌 보존)"
                                    excluded += 1
                            else:
                                self.store.import_income_row(
                                    row_id=f"bnk-{key[:16]}",
                                    fields={
                                        "occurred_on": payload["occurred_on"],
                                        "customer_id": None,
                                        "customer_name": payload["payer_name"],
                                        "nickname": "",
                                        "income_kind": "deposit",
                                        "event_type": "receipt",
                                        "amount_krw": payload["amount_krw"],
                                        "source_kind": "은행",
                                        "source_event_id": payload["transaction_id"] or f"bnk-{key[:16]}",
                                        "display_tab_id": None,
                                    },
                                    batch_id=batch_id,
                                    client_request_id=f"{batch_id}-{position}",
                                )
                                status, note = "placed", "귀속 전 수입"
                                credit += 1
                                created += 1
                self.conn.execute(
                    "INSERT INTO bank_import_rows(batch_id, row_index, stable_key, raw_json,"
                    " status, note) VALUES (?,?,?,?,?,?)",
                    (batch_id, position, key, json.dumps(fields, ensure_ascii=False),
                     status, note),
                )
            result = {
                "batch_id": batch_id, "status": "completed",
                "source_rows": len(rows), "credit_rows": credit,
                "excluded_rows": excluded, "new_events": created,
                "skipped_existing": skipped,
                "duplicate_candidates": candidates,
            }
            self.conn.execute(
                "UPDATE bank_import_batches SET status='completed', credit_rows=?,"
                " excluded_rows=?, new_events=?, skipped_existing=?, result_json=?"
                " WHERE batch_id=?",
                (credit, excluded, created, skipped,
                 json.dumps(result, ensure_ascii=False), batch_id),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        self.store._replay_pending()
        return {"batch_id": batch_id, "reused": False, "result": result}
