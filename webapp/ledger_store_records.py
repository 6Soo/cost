"""Pure row read, projection, and record decoding module for LedgerStore.

Extracted under RF-101 (Store decomposition first implementation bundle).
Maintains pure functions with no circular dependencies, hidden globals, or write side-effects.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Callable

ALLOCATION_ROW_EDITABLE = (
    "customer_id",
    "customer_name",
    "nickname",
    "display_tab_id",
    "income_kind",
)


def _row_to_record(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw row dict to a normalized revision 1 record."""
    amount = row["amount_krw"]
    if isinstance(amount, Decimal):
        amount = int(amount)
    record: dict[str, Any] = {
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
            amount_krw=amount,
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
            amount_krw=amount,
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
) -> dict[str, Any]:
    """Reconstruct a complete row record from board_rows columns and payload JSON."""
    payload = json.loads(payload_json)
    payload["row_id"] = row_id
    payload["row_kind"] = row_kind
    payload["display_tab_id"] = display_tab_id
    payload["revision"] = revision
    return payload


def calculate_display_amount(
    row: dict[str, Any],
    latest_correction: tuple | list | dict[str, Any] | None = None,
) -> int:
    """Current display amount: latest bank correction wins, else stored amount."""
    if row.get("source_kind") != "은행":
        return row["amount_krw"]
    if latest_correction:
        if isinstance(latest_correction, (tuple, list)):
            return latest_correction[1]
        if isinstance(latest_correction, dict):
            return latest_correction.get("corrected_amount_krw", row["amount_krw"])
    return row["amount_krw"]


def calculate_display_occurred_on(
    row: dict[str, Any],
    latest_correction: tuple | list | dict[str, Any] | None = None,
) -> str:
    """Current display date: latest bank date correction wins, else stored date."""
    if row.get("source_kind") != "은행":
        return row["occurred_on"]
    if latest_correction:
        if isinstance(latest_correction, (tuple, list)):
            if len(latest_correction) > 2 and latest_correction[2]:
                return latest_correction[2]
        elif isinstance(latest_correction, dict):
            val = latest_correction.get("corrected_occurred_on")
            if val:
                return val
    return row["occurred_on"]


def project_record(
    row: dict[str, Any],
    display_amount_krw: int | None = None,
    display_occurred_on: str | None = None,
    latest_correction: tuple | list | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R05: Projection used by UI, summary calculations, and export."""
    out = dict(row)
    if display_amount_krw is not None:
        out["display_amount_krw"] = display_amount_krw
    else:
        out["display_amount_krw"] = calculate_display_amount(row, latest_correction)
    if display_occurred_on is not None:
        out["display_occurred_on"] = display_occurred_on
    else:
        out["display_occurred_on"] = calculate_display_occurred_on(row, latest_correction)
    return out


def allocation_row_to_dict(row: tuple | list) -> dict[str, Any]:
    """Decode an income_allocations row into a standard allocation dict."""
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


def build_allocation_display_row(
    alloc: dict[str, Any],
    source: dict[str, Any],
    display_occurred_on: str | None = None,
) -> dict[str, Any]:
    """Assemble a pseudo-row representing an active allocation for board display."""
    shown_date = (
        display_occurred_on
        if display_occurred_on is not None
        else source.get("display_occurred_on", source.get("occurred_on", ""))
    )
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


def build_remainder_display_row(
    source: dict[str, Any],
    remainder_krw: int,
    display_occurred_on: str | None = None,
) -> dict[str, Any]:
    """Assemble a pseudo-row representing unassigned remainder for board display."""
    shown_date = (
        display_occurred_on
        if display_occurred_on is not None
        else source.get("display_occurred_on", source.get("occurred_on", ""))
    )
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
        "amount_krw": remainder_krw,
        "display_amount_krw": remainder_krw,
        "source_kind": source.get("source_kind", ""),
        "source_event_id": source.get("source_event_id", ""),
        "operator_note": "",
    }


def project_allocation_history(allocation: dict[str, Any]) -> dict[str, Any]:
    """Project editable and control fields of an allocation for revision diffing."""
    return {
        **{field: allocation.get(field) for field in ALLOCATION_ROW_EDITABLE},
        "amount_krw": allocation.get("amount_krw"),
        "active": bool(allocation.get("active")),
        "source_revision": allocation.get("source_revision"),
    }


def calculate_split_remainder(
    source: dict[str, Any] | None,
    display_amount_krw: int,
    active_allocations: list[dict[str, Any]],
) -> int:
    """Calculate unassigned remainder for a split source row."""
    if source is None:
        return 0
    return display_amount_krw - sum(a.get("amount_krw", 0) for a in active_allocations)


def format_correction_record(
    r: tuple | list,
    has_extended_columns: bool = True,
) -> dict[str, Any]:
    """Decode an income_corrections row with backwards compatible fallback."""
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


def format_history_entry(
    r: tuple | list,
    has_extended_columns: bool = True,
) -> dict[str, Any]:
    """Decode a board_revisions row into a revision history entry."""
    prev_data = json.loads(r[1]) if r[1] else {}
    new_data = json.loads(r[2]) if r[2] else {}
    if has_extended_columns:
        return {
            "revision": r[0],
            "prev": prev_data,
            "new": new_data,
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
        "prev": prev_data,
        "new": new_data,
        "event_id": r[3],
        "change_mode": r[4],
        "actor": r[5],
        "created_at": r[6],
        "client_request_id": r[7],
        "kind": "save",
        "reverts_event_id": "",
    }


# ============================================================================
# Pure SQLite read operations (isolated from write / audit / idempotency paths)
# ============================================================================

def read_board_row(conn: Any, row_id: str) -> dict[str, Any] | None:
    """Fetch and decode a single row from board_rows."""
    row = conn.execute(
        "SELECT row_kind, display_tab_id, revision, payload_json FROM board_rows WHERE row_id=?",
        (row_id,),
    ).fetchone()
    if row is None:
        return None
    return deserialize_row_record(row_id, row[0], row[1], row[2], row[3])


def read_tab_rows(
    conn: Any,
    tab_id: str | None,
    split_source_ids: set[str],
    get_row_fn: Callable[[str], dict[str, Any] | None],
    split_remainder_fn: Callable[[str], int],
    display_occurred_on_fn: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    """Assemble all visible rows for a tab, including allocations and unassigned remainder."""
    if tab_id is None:
        rows = conn.execute(
            "SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows"
            " WHERE display_tab_id IS NULL ORDER BY row_id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows"
            " WHERE display_tab_id=? ORDER BY row_id",
            (tab_id,),
        ).fetchall()

    out: list[dict[str, Any]] = []
    for row_id, kind, display, revision, payload_json in rows:
        if row_id in split_source_ids:
            continue
        out.append(deserialize_row_record(row_id, kind, display, revision, payload_json))

    try:
        alloc_rows = conn.execute(
            "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
            " display_tab_id, income_kind, amount_krw, active, source_revision"
            " FROM income_allocations WHERE active=1"
            " AND ((? IS NULL AND display_tab_id IS NULL) OR display_tab_id=?)"
            " ORDER BY allocation_id",
            (tab_id, tab_id),
        ).fetchall()
    except Exception:
        alloc_rows = []

    for raw in alloc_rows:
        alloc = allocation_row_to_dict(raw)
        source = get_row_fn(alloc["source_row_id"])
        if source is None:
            continue
        out.append(
            build_allocation_display_row(
                alloc,
                source,
                display_occurred_on=display_occurred_on_fn(source),
            )
        )

    if tab_id is None:
        for source_id in sorted(split_source_ids):
            source = get_row_fn(source_id)
            if source is None:
                continue
            rem = split_remainder_fn(source_id)
            if rem != 0:
                out.append(
                    build_remainder_display_row(
                        source,
                        rem,
                        display_occurred_on=display_occurred_on_fn(source),
                    )
                )

    return out


def count_visible_rows(
    conn: Any,
    split_source_ids: set[str],
    has_nonzero_remainder_fn: Callable[[str], bool],
) -> int:
    """Count visible rows across existing tabs without loading their payloads."""
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

    remainders = sum(1 for sid in split_source_ids if has_nonzero_remainder_fn(sid))
    return ordinary + allocations + remainders


def read_history(conn: Any, row_id: str) -> list[dict[str, Any]]:
    """Fetch revision history for a row, ordered by revision and id."""
    try:
        rows = conn.execute(
            "SELECT revision, prev_json, new_json, event_id, change_mode, actor, created_at,"
            " client_request_id, kind, reverts_event_id FROM board_revisions"
            " WHERE row_id=? ORDER BY revision, id",
            (row_id,),
        ).fetchall()
        return [format_history_entry(r, has_extended_columns=True) for r in rows]
    except Exception:
        rows = conn.execute(
            "SELECT revision, prev_json, new_json, event_id, change_mode, actor, created_at,"
            " client_request_id FROM board_revisions WHERE row_id=? ORDER BY revision",
            (row_id,),
        ).fetchall()
        return [format_history_entry(r, has_extended_columns=False) for r in rows]


def read_row_conflict(conn: Any, row_id: str) -> dict[str, Any] | None:
    """Fetch unresolved conflict note on this row, or None."""
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


def read_conflicting_row_ids(conn: Any) -> set[str]:
    """Every row whose newest ledger event is a conflict note."""
    rows = conn.execute(
        "SELECT row_id, kind FROM board_revisions ORDER BY row_id, revision, id"
    ).fetchall()
    newest: dict[str, str] = {}
    for row_id, kind in rows:
        newest[row_id] = kind or "save"
    return {row_id for row_id, kind in newest.items() if kind == "conflict"}


def read_latest_correction(conn: Any, row_id: str) -> tuple | None:
    """Fetch the latest income_corrections row for row_id."""
    try:
        return conn.execute(
            "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
            " row_revision, reason, actor, created_at, client_request_id"
            " FROM income_corrections WHERE row_id=? ORDER BY rowid DESC LIMIT 1",
            (row_id,),
        ).fetchone()
    except Exception:
        return None


def read_corrections(conn: Any, row_id: str) -> list[dict[str, Any]]:
    """Fetch all corrections for row_id ordered by insertion."""
    try:
        rows = conn.execute(
            "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
            " row_revision, reason, actor, created_at"
            " FROM income_corrections WHERE row_id=? ORDER BY rowid",
            (row_id,),
        ).fetchall()
        return [format_correction_record(r, has_extended_columns=True) for r in rows]
    except Exception:
        rows = conn.execute(
            "SELECT correction_id, corrected_amount_krw, reason, actor, created_at"
            " FROM income_corrections WHERE row_id=? ORDER BY rowid",
            (row_id,),
        ).fetchall()
        return [format_correction_record(r, has_extended_columns=False) for r in rows]


def read_active_allocations(conn: Any, source_row_id: str) -> list[dict[str, Any]]:
    """Fetch active allocations for source_row_id."""
    rows = conn.execute(
        "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
        " display_tab_id, income_kind, amount_krw, active, source_revision"
        " FROM income_allocations WHERE source_row_id=? AND active=1"
        " ORDER BY allocation_id",
        (source_row_id,),
    ).fetchall()
    return [allocation_row_to_dict(r) for r in rows]


def read_split_source_ids(conn: Any) -> set[str]:
    """Fetch set of source_row_ids with at least one active allocation."""
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_row_id FROM income_allocations WHERE active=1"
        ).fetchall()
    except Exception:
        return set()
    return {r[0] for r in rows}


def read_allocation(conn: Any, allocation_id: str) -> dict[str, Any] | None:
    """Fetch a single allocation by ID."""
    row = conn.execute(
        "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
        " display_tab_id, income_kind, amount_krw, active, source_revision"
        " FROM income_allocations WHERE allocation_id=?",
        (allocation_id,),
    ).fetchone()
    if row is None:
        return None
    return allocation_row_to_dict(row)


def read_latest_allocation_history(conn: Any, allocation_id: str) -> dict[str, Any] | None:
    """Fetch the latest revision history row for an allocation."""
    row = conn.execute(
        "SELECT id, prev_json, new_json, event_id, client_request_id, reverts_event_id"
        " FROM income_allocation_history WHERE allocation_id=? ORDER BY id DESC LIMIT 1",
        (allocation_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "prev": json.loads(row[1]),
        "new": json.loads(row[2]),
        "event_id": row[3],
        "client_request_id": row[4],
        "reverts_event_id": row[5],
    }
