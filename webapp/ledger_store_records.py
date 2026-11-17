"""Pure row read, projection, and record decoding module for LedgerStore.

Extracted under RF-101 (Store decomposition first implementation bundle).
Preserves exact execution semantics, types, and error behavior of the original store.
"""
from __future__ import annotations

import json
from typing import Any

ALLOCATION_ROW_EDITABLE = (
    "customer_id",
    "customer_name",
    "nickname",
    "display_tab_id",
    "income_kind",
)


def _row_to_record(kind: str, row: dict) -> dict:
    record = {
        "row_id": row["row_id"],
        "row_kind": kind,
        "display_tab_id": row["display_tab_id"],
        "revision": 1,
    }
    if kind == "expense":
        record.update(
            occurred_on=row["occurred_on"],
            item=row["item"],
            description=row["description"],
            service_period=row.get("service_period", ""),
            reservation_no=row.get("reservation_no", ""),
            evidence_type=row.get("evidence_type", ""),
            amount_krw=row["amount_krw"],
            source_kind=row["source_kind"],
            source_event_id=row["source_event_id"],
            classification_state=row.get("classification_state", ""),
            classification_basis=row.get("classification_basis", ""),
            source_merchant=row.get("source_merchant", ""),
            event_kind=row.get("event_kind", ""),
            card_kind=row.get("card_kind", ""),
            operator_note="",
        )
    else:
        record.update(
            occurred_on=row["occurred_on"],
            customer_id=row["customer_id"],
            customer_name=row["customer_name"],
            nickname=row.get("nickname", ""),
            income_kind=row["income_kind"],
            event_type=row.get("event_type", "receipt"),
            amount_krw=row["amount_krw"],
            source_kind=row["source_kind"],
            source_event_id=row["source_event_id"],
            operator_note="",
        )
    return record


def deserialize_row_record(
    row_id: str,
    row_kind: str,
    display_tab_id: str | None,
    revision: int,
    payload_json: str,
) -> dict:
    payload = json.loads(payload_json)
    payload["row_id"] = row_id
    payload["row_kind"] = row_kind
    payload["display_tab_id"] = display_tab_id
    payload["revision"] = revision
    return payload


def ledger_table_exists(conn: Any) -> bool:
    """통합 장부 테이블이 있나. 없으면 아직 이관 전 DB다."""
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger'").fetchone())


def ledger_is_authoritative(conn: Any) -> bool:
    """통합 장부가 읽기 정본인가.

    테이블이 '있기만' 하면 정본이 아니다. `LedgerStore`가 스키마를 만들기 때문에
    새 합성 DB에도 빈 `ledger`가 생긴다. 이관이 실제로 끝난 DB만 정본으로 본다 —
    기준은 `ledger`에 행이 있는 것이다.

    빈 `ledger`를 정본으로 보면 기장 판정이 전부 '미기장'으로 뒤집힌다.
    """
    try:
        if not ledger_table_exists(conn):
            return False
        return conn.execute('SELECT 1 FROM ledger LIMIT 1').fetchone() is not None
    except Exception:
        return False


def _table_exists(conn: Any, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def booked_sql(conn: Any, transaction_alias: str = 't') -> str:
    """'이 거래가 장부에 기장됐나'를 판단하는 SQL 조각.

    통합 장부(`ledger`)에 행이 있으면 정본이고, 그때도 `board_rows`를 함께 본다 —
    과도기(일부만 이관된 DB)에서 누락을 막기 위해서다. 둘은 이중 쓰기로 같은
    트랜잭션에서 쓰이므로 정상 상태에서는 결과가 같다.

    `ledger`가 비었거나 없으면 옛 `board_rows`를 본다. 둘 다 없으면 **항상 거짓**인
    조각을 준다 — 테이블이 없으면 기장된 행도 없으므로 `EXISTS(...)`가 False가
    되는 것이 정확한 뜻이고, 호출자가 None을 따로 처리하지 않아도 된다.

    호출자는 이 조각을 `EXISTS(...)`/`NOT EXISTS(...)` 안에 넣어 쓴다.
    """
    sources = []
    if ledger_is_authoritative(conn):
        sources.append("SELECT 1 FROM ledger l"
                       f" WHERE l.transaction_id={transaction_alias}.transaction_id")
    if _table_exists(conn, 'board_rows'):
        sources.append("SELECT 1 FROM board_rows b"
                       f" WHERE b.row_id='card-'||{transaction_alias}.transaction_id")
    if not sources:
        return 'SELECT 1 WHERE 0'
    return ' UNION ALL '.join(sources)


def sync_ledger_from_record(conn: Any, record: dict) -> None:
    """화면 행 record 하나를 통합 장부에도 맞춰 쓴다(있으면 갱신, 없으면 삽입).

    `board_rows`를 고치는 경로가 모두 이 함수를 부른다. 값은 이미 화면 행이
    계산한 것을 그대로 옮겨 적으므로 두 저장소가 서로 다른 말을 할 수 없다.

    통합 장부가 없는 미이관 DB에서는 아무것도 하지 않는다. 그때는 `board_rows`가
    정본이고 어긋날 대상이 없다.
    """
    if not ledger_table_exists(conn):
        return
    row_id = record.get('row_id')
    if not row_id:
        return
    transaction_id = row_id[len('card-'):] if row_id.startswith('card-') else None
    values = dict(
        entry_id=row_id,
        transaction_id=transaction_id,
        entry_kind=record.get('row_kind') or record.get('entry_kind') or 'expense',
        item=record.get('item') or '',
        description=record.get('description') or '',
        amount_krw=record.get('amount_krw'),
        occurred_on=record.get('occurred_on') or '',
        display_tab_id=record.get('display_tab_id'),
        trip_id=record.get('trip_id') or record.get('display_tab_id') or '',
        service_period=record.get('service_period') or '',
        reservation_no=record.get('reservation_no') or '',
        evidence_type=record.get('evidence_type') or '',
        source_kind=record.get('source_kind') or '',
        source_event_id=record.get('source_event_id') or '',
        source_fact_digest=record.get('source_fact_digest') or '',
        source_merchant=record.get('source_merchant') or '',
        source_issuer=record.get('source_issuer') or '',
        source_card_last4=record.get('source_card_last4') or '',
        source_approval_number=record.get('source_approval_number') or '',
        source_approval_date=record.get('source_approval_date') or '',
        source_posting_date=record.get('source_posting_date') or '',
        source_local_amount=record.get('source_local_amount') or '',
        source_currency=record.get('source_currency') or '',
        event_kind=record.get('event_kind') or '',
        classification_state=record.get('classification_state') or '',
        classification_source=record.get('classification_source') or '',
        classification_basis=record.get('classification_basis') or '',
        confirmed_by=record.get('confirmed_by') or '',
        memo=record.get('memo') or '',
        operator_note=record.get('operator_note') or '',
        customer_id=record.get('customer_id') or '',
        customer_name=record.get('customer_name') or '',
        nickname=record.get('nickname') or '',
        income_kind=record.get('income_kind') or '',
        event_type=record.get('event_type') or '',
        created_by_request=record.get('created_by_request') or '',
        ota_evidence_json=json.dumps(record['ota_evidence'], ensure_ascii=False,
                                     sort_keys=True) if record.get('ota_evidence') else '',
        revision=record.get('revision') or 1,
    )
    if conn.execute('SELECT 1 FROM ledger WHERE entry_id=?', (row_id,)).fetchone():
        pairs = ','.join(f'{column}=?' for column in values)
        conn.execute(f'UPDATE ledger SET {pairs} WHERE entry_id=?',
                     (*values.values(), row_id))
        return
    columns = list(values) + ['committed_at', 'batch_id', 'created_at']
    row = list(values.values()) + ['', '', '']
    conn.execute(
        f'INSERT INTO ledger({",".join(columns)})'
        f' VALUES ({",".join("?" * len(columns))})', row)


def allocation_dict(row: tuple | list) -> dict:
    return {
        "allocation_id": row[0],
        "source_row_id": row[1],
        "customer_id": row[2],
        "customer_name": row[3] or "",
        "nickname": row[4] or "",
        "display_tab_id": row[5],
        "income_kind": row[6],
        "amount_krw": row[7],
        "active": bool(row[8]),
        "source_revision": row[9],
    }


def allocation_display_row(alloc: dict, source: dict, shown_date: str) -> dict:
    return {
        "row_id": alloc["allocation_id"],
        "row_kind": "income",
        "is_allocation": True,
        "source_row_id": alloc["source_row_id"],
        "display_tab_id": alloc["display_tab_id"],
        "revision": source["revision"],
        "occurred_on": shown_date,
        "display_occurred_on": shown_date,
        "customer_id": alloc["customer_id"],
        "customer_name": alloc["customer_name"],
        "nickname": alloc["nickname"],
        "income_kind": alloc["income_kind"],
        "event_type": "receipt",
        "amount_krw": alloc["amount_krw"],
        "display_amount_krw": alloc["amount_krw"],
        "source_kind": source.get("source_kind", ""),
        "source_event_id": source.get("source_event_id", ""),
        "operator_note": "",
    }


def remainder_display_row(source: dict, remainder: int, shown_date: str) -> dict:
    return {
        "row_id": f"rem-{source['row_id']}",
        "row_kind": "income",
        "is_remainder": True,
        "source_row_id": source["row_id"],
        "display_tab_id": None,
        "revision": source["revision"],
        "occurred_on": shown_date,
        "display_occurred_on": shown_date,
        "customer_id": None,
        "customer_name": "",
        "nickname": "",
        "income_kind": "",
        "event_type": "receipt",
        "amount_krw": remainder,
        "display_amount_krw": remainder,
        "source_kind": source.get("source_kind", ""),
        "source_event_id": source.get("source_event_id", ""),
        "operator_note": "",
    }


def allocation_history_projection(allocation: dict) -> dict:
    return {
        **{field: allocation.get(field) for field in ALLOCATION_ROW_EDITABLE},
        "amount_krw": allocation.get("amount_krw"),
        "active": bool(allocation.get("active")),
        "source_revision": allocation.get("source_revision"),
    }


def format_correction_record(r: tuple | list, has_extended_columns: bool = True) -> dict:
    if has_extended_columns:
        return {
            "correction_id": r[0],
            "corrected_amount_krw": r[1],
            "corrected_occurred_on": r[2],
            "row_revision": r[3],
            "reason": r[4],
            "actor": r[5],
            "created_at": r[6],
        }
    return {
        "correction_id": r[0],
        "corrected_amount_krw": r[1],
        "corrected_occurred_on": None,
        "row_revision": None,
        "reason": r[2],
        "actor": r[3],
        "created_at": r[4],
    }


def format_history_entry(r: tuple | list, has_extended_columns: bool = True) -> dict:
    if has_extended_columns:
        return {
            "revision": r[0],
            "prev": json.loads(r[1]),
            "new": json.loads(r[2]),
            "event_id": r[3],
            "change_mode": r[4],
            "actor": r[5],
            "created_at": r[6],
            "client_request_id": r[7],
            "kind": r[8] or "save",
            "reverts_event_id": r[9] or "",
        }
    return {
        "revision": r[0],
        "prev": json.loads(r[1]),
        "new": json.loads(r[2]),
        "event_id": r[3],
        "change_mode": r[4],
        "actor": r[5],
        "created_at": r[6],
        "client_request_id": r[7],
        "kind": "save",
        "reverts_event_id": "",
    }


# ============================================================================
# SQL read queries extracted for LedgerStore
# ============================================================================

def fetch_board_row(conn: Any, row_id: str) -> tuple | None:
    return conn.execute(
        "SELECT row_kind, display_tab_id, revision, payload_json FROM board_rows WHERE row_id=?",
        (row_id,),
    ).fetchone()


def fetch_tab_board_rows(conn: Any, tab_id: str | None) -> list[tuple]:
    if tab_id is None:
        return conn.execute(
            "SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows"
            " WHERE display_tab_id IS NULL ORDER BY row_id"
        ).fetchall()
    return conn.execute(
        "SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows"
        " WHERE display_tab_id=? ORDER BY row_id",
        (tab_id,),
    ).fetchall()


def fetch_board_rows_by_tab(conn: Any) -> dict[str | None, list[tuple]]:
    """Every saved row in one scan, grouped by tab in row_id order; display_tab_id has no index."""
    grouped: dict[str | None, list[tuple]] = {}
    for row in conn.execute(
        "SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows ORDER BY row_id"
    ):
        grouped.setdefault(row[2], []).append(row)
    return grouped


def fetch_active_tab_allocations(conn: Any, tab_id: str | None) -> list[tuple]:
    try:
        return conn.execute(
            "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
            " display_tab_id, income_kind, amount_krw, active, source_revision"
            " FROM income_allocations WHERE active=1"
            " AND ((? IS NULL AND display_tab_id IS NULL) OR display_tab_id=?)"
            " ORDER BY allocation_id",
            (tab_id, tab_id),
        ).fetchall()
    except Exception:
        return []


def fetch_visible_row_counts(conn: Any) -> tuple[int, int]:
    def visible_tab(alias: str) -> str:
        return (
            f"({alias}.display_tab_id IS NULL OR EXISTS(SELECT 1 FROM trip_tabs t "
            f"WHERE t.tab_id={alias}.display_tab_id AND t.deleted=0))"
        )

    ordinary = conn.execute(
        "SELECT COUNT(*) FROM board_rows b"
        " WHERE b.row_kind IN ('expense','income') AND " + visible_tab("b") +
        " AND NOT EXISTS(SELECT 1 FROM income_allocations a"
        " WHERE a.source_row_id=b.row_id AND a.active=1)"
    ).fetchone()[0]

    allocations = conn.execute(
        "SELECT COUNT(*) FROM income_allocations a"
        " JOIN board_rows b ON b.row_id=a.source_row_id"
        " WHERE a.active=1 AND " + visible_tab("a")
    ).fetchone()[0]

    return ordinary, allocations


def fetch_conflict_note(conn: Any, row_id: str) -> dict | None:
    row = conn.execute(
        "SELECT kind FROM board_revisions WHERE row_id=?"
        " ORDER BY revision DESC, id DESC LIMIT 1",
        (row_id,),
    ).fetchone()
    if row is None or (row[0] or "save") != "conflict":
        return None
    last = conn.execute(
        "SELECT revision, new_json, actor, created_at, client_request_id"
        " FROM board_revisions WHERE row_id=? AND kind='conflict'"
        " ORDER BY revision DESC, id DESC LIMIT 1",
        (row_id,),
    ).fetchone()
    if last is None:
        return None
    try:
        note = json.loads(last[1])
    except ValueError:
        note = {}
    return {
        "row_id": row_id,
        "revision": last[0],
        "actor": last[2],
        "created_at": last[3],
        "client_request_id": last[4],
        "expected_revision": note.get("expected_revision"),
        "current_revision": note.get("current_revision"),
        "attempted": note.get("attempted") or {},
    }


def fetch_conflicting_row_ids(conn: Any) -> set[str]:
    rows = conn.execute(
        "SELECT row_id, kind FROM board_revisions ORDER BY row_id, revision, id"
    ).fetchall()
    newest: dict[str, str] = {}
    for row_id, kind in rows:
        newest[row_id] = kind or "save"
    return {row_id for row_id, kind in newest.items() if kind == "conflict"}


def fetch_history_rows(conn: Any, row_id: str) -> tuple[list[tuple], bool]:
    try:
        rows = conn.execute(
            "SELECT revision, prev_json, new_json, event_id, change_mode, actor, created_at,"
            " client_request_id, kind, reverts_event_id FROM board_revisions"
            " WHERE row_id=? ORDER BY revision, id",
            (row_id,),
        ).fetchall()
        return rows, True
    except Exception:
        rows = conn.execute(
            "SELECT revision, prev_json, new_json, event_id, change_mode, actor, created_at,"
            " client_request_id FROM board_revisions WHERE row_id=? ORDER BY revision",
            (row_id,),
        ).fetchall()
        return rows, False


def fetch_latest_correction(conn: Any, row_id: str) -> tuple | None:
    try:
        return conn.execute(
            "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
            " row_revision, reason, actor, created_at, client_request_id"
            " FROM income_corrections WHERE row_id=? ORDER BY rowid DESC LIMIT 1",
            (row_id,),
        ).fetchone()
    except Exception:
        return None


def fetch_corrections(conn: Any, row_id: str) -> tuple[list[tuple], bool]:
    try:
        rows = conn.execute(
            "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
            " row_revision, reason, actor, created_at"
            " FROM income_corrections WHERE row_id=? ORDER BY rowid",
            (row_id,),
        ).fetchall()
        return rows, True
    except Exception:
        rows = conn.execute(
            "SELECT correction_id, corrected_amount_krw, reason, actor, created_at"
            " FROM income_corrections WHERE row_id=? ORDER BY rowid",
            (row_id,),
        ).fetchall()
        return rows, False


def fetch_active_allocations(conn: Any, source_row_id: str) -> list[tuple]:
    return conn.execute(
        "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
        " display_tab_id, income_kind, amount_krw, active, source_revision"
        " FROM income_allocations WHERE source_row_id=? AND active=1"
        " ORDER BY allocation_id",
        (source_row_id,),
    ).fetchall()


def fetch_split_source_ids(conn: Any) -> set[str]:
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_row_id FROM income_allocations WHERE active=1"
        ).fetchall()
    except Exception:
        return set()
    return {r[0] for r in rows}


def fetch_allocation_row(conn: Any, allocation_id: str) -> tuple | None:
    return conn.execute(
        "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
        " display_tab_id, income_kind, amount_krw, active, source_revision"
        " FROM income_allocations WHERE allocation_id=?",
        (allocation_id,),
    ).fetchone()


def fetch_latest_allocation_history_row(conn: Any, allocation_id: str) -> tuple | None:
    return conn.execute(
        "SELECT id, prev_json, new_json, event_id, client_request_id, reverts_event_id"
        " FROM income_allocation_history WHERE allocation_id=? ORDER BY id DESC LIMIT 1",
        (allocation_id,),
    ).fetchone()
