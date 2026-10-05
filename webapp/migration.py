"""Phase 8 local synthetic import: seal two sources, compare, decide, migrate.

Scope and boundary
------------------
This is the local synthetic implementation of PHASES Phase 8 and the import
contract in SPEC_REFINEMENT 17/18. It does NOT touch the real Google reference
workbook, any production DB, any customer original or any external service.
Both inputs are synthetic SQLite sources built by `build_source_db` in a
temporary directory, sealed with the existing
`snapshot_descriptor.seal_snapshot`, and opened read-only. Nothing in this
module writes to a source database; the only writable target is a separate
migration DB (SPEC: "별도 이관 DB에 적용").

Decisions recorded from the specification:

* Both sources are sealed and verified before anything is read, and a sidecar
  file next to a source is a refusal rather than a repair (execution
  contract: a source SQLite is a read-only sealed snapshot; repair or
  checkpoint the original instead of making it pass).
* Rows are matched on an explicit source identity. A shared name, date or
  amount never merges two rows on its own: a candidate match with no verified
  identity is `ambiguous` and stays unresolved (PHASES 8.1).
* The comparison reports `equal`, `mismatch`, `google_only`, `db_only` and
  `ambiguous` separately, so "only one side", "both but different" and
  "cannot tell" are never collapsed into one count.
* A `mismatch` needs an explicit per-field choice. There is no default: an
  undecided field leaves the row unresolved instead of silently preferring one
  side (PHASES 8.2).
* An amount or date disagreement is preserved as a provenance record in its own
  right. Choosing a displayed value never erases what the other source said
  (PHASES 8.2: an amount mismatch is not hidden by the display choice).
* A decision is bound to the comparison id, both input hashes, the field, the
  chosen value, the user and the timestamp. If either input hash changes the
  decision is not reusable (execution contract: changed source means a new
  computation, the old authority is not reused).
* The migration target is a separate DB and applying the same comparison twice
  produces no second effect (execution contract: identical output recalled
  leaves the result unchanged).
* The report states the unresolved count, the migration event count, the signed
  totals, the missing business fields and the memo/evidence/provenance
  preservation state, so "done" is not judged on totals alone.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .comparator import diff_json
from .contracts import canonical_text, normalize_amount, sha256_file
from .snapshot_descriptor import seal_snapshot, verify_snapshot

SOURCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_entries (
    entry_id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL DEFAULT '',
    occurred_on TEXT NOT NULL DEFAULT '',
    amount_krw INTEGER NOT NULL DEFAULT 0,
    sign INTEGER NOT NULL DEFAULT 1,
    reservation_no TEXT NOT NULL DEFAULT '',
    item TEXT NOT NULL DEFAULT '',
    evidence_ref TEXT NOT NULL DEFAULT '',
    memo TEXT NOT NULL DEFAULT '',
    memo_updated_at TEXT NOT NULL DEFAULT '',
    source_identity TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""

# The business fields the ledger needs. A source that lacks one of these is
# reported as a missing business field rather than being filled in silently.
BUSINESS_FIELDS = ("customer_name", "occurred_on", "amount_krw", "sign",
                   "item", "reservation_no")

MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS migration_events (
    event_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    action TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    left_input_sha256 TEXT NOT NULL,
    right_input_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_rows (
    row_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    row_kind TEXT NOT NULL,
    occurred_on TEXT NOT NULL DEFAULT '',
    amount_krw INTEGER NOT NULL DEFAULT 0,
    sign INTEGER NOT NULL DEFAULT 1,
    customer_name TEXT NOT NULL DEFAULT '',
    item TEXT NOT NULL DEFAULT '',
    reservation_no TEXT NOT NULL DEFAULT '',
    evidence_ref TEXT NOT NULL DEFAULT '',
    memo TEXT NOT NULL DEFAULT '',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_provenance (
    row_id TEXT NOT NULL,
    field TEXT NOT NULL,
    left_value TEXT NOT NULL DEFAULT '',
    right_value TEXT NOT NULL DEFAULT '',
    left_input_sha256 TEXT NOT NULL,
    right_input_sha256 TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (row_id, field)
);
CREATE TABLE IF NOT EXISTS migration_decisions (
    decision_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    field TEXT NOT NULL,
    chosen_value TEXT NOT NULL,
    chosen_side TEXT NOT NULL,
    user_id TEXT NOT NULL,
    left_input_sha256 TEXT NOT NULL,
    right_input_sha256 TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_comparisons (
    comparison_id TEXT PRIMARY KEY,
    left_input_sha256 TEXT NOT NULL,
    right_input_sha256 TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_requests (
    client_request_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    left_input_sha256 TEXT NOT NULL,
    right_input_sha256 TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class MigrationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------- synthetic sources
def build_source_db(path, entries: list[dict], *, side: str) -> Path:
    """Create one synthetic source. The caller seals it and then only reads it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SOURCE_SCHEMA)
        for entry in entries:
            conn.execute(
                "INSERT INTO source_entries(entry_id, customer_name, occurred_on,"
                " amount_krw, sign, reservation_no, item, evidence_ref, memo,"
                " memo_updated_at, source_identity, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry["entry_id"], entry.get("customer_name", ""),
                 entry.get("occurred_on", ""),
                 normalize_amount(entry.get("amount_krw", 0)),
                 int(entry.get("sign", 1)),
                 entry.get("reservation_no", ""), entry.get("item", ""),
                 entry.get("evidence_ref", ""), entry.get("memo", ""),
                 entry.get("memo_updated_at", ""),
                 entry.get("source_identity", ""), utc_now()))
        conn.commit()
    finally:
        conn.close()
    return path


def open_source_readonly(db_path) -> sqlite3.Connection:
    """Open a source read-only so a bug cannot modify the original."""
    return sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)


def read_source_entries(db_path) -> list[dict]:
    conn = open_source_readonly(db_path)
    try:
        rows = conn.execute(
            "SELECT entry_id, customer_name, occurred_on, amount_krw, sign,"
            " reservation_no, item, evidence_ref, memo, memo_updated_at,"
            " source_identity, updated_at FROM source_entries"
            " ORDER BY entry_id").fetchall()
    finally:
        conn.close()
    keys = ("entry_id", "customer_name", "occurred_on", "amount_krw", "sign",
            "reservation_no", "item", "evidence_ref", "memo", "memo_updated_at",
            "source_identity", "updated_at")
    return [dict(zip(keys, row)) for row in rows]


def _identity(row: dict) -> str:
    """The only accepted key for a match: an explicit source identity.

    Falling back to a name, a date or an amount would merge two real
    transactions that merely look alike, so an empty identity is never a key.
    The identity is the shared stable id only: the two sides keep their own
    entry ids, and joining on those would never match.
    """
    return str(row.get("source_identity") or "").strip()


def _entry_of(identity: str) -> str:
    return identity or ""


def _loose_match_key(row: dict) -> str:
    """A candidate key used only to raise `ambiguous`, never to merge."""
    return canonical_text({
        "customer_name": str(row.get("customer_name") or "").strip(),
        "occurred_on": str(row.get("occurred_on") or "").strip(),
        "amount_krw": int(row.get("amount_krw") or 0),
    })


# ---------------------------------------------------------------- compare
def compare_sources(left_rows, right_rows) -> dict:
    """Compare two sealed sources by verified identity.

    Returns the five states separately. `ambiguous` is raised when the two
    sides look the same on name/date/amount but carry no verified identity, or
    when one side repeats an identity, so the operator has to look rather than
    have a guess applied.
    """
    left_by_identity, left_ambiguous = _index_side(left_rows, "left")
    right_by_identity, right_ambiguous = _index_side(right_rows, "right")

    equal, mismatch = [], []
    for identity in sorted(set(left_by_identity) & set(right_by_identity)):
        left = left_by_identity[identity]["row"]
        right = right_by_identity[identity]["row"]
        diff = diff_json(_comparable(left), _comparable(right))["changes"]
        entry_id = left["entry_id"]
        if diff:
            mismatch.append({
                "identity": identity, "entry_id": entry_id,
                "right_entry_id": right["entry_id"],
                "left": _comparable(left), "right": _comparable(right),
                "changed_fields": sorted(c["key"] for c in diff),
            })
        else:
            equal.append({"identity": identity, "entry_id": entry_id,
                          "right_entry_id": right["entry_id"]})
    google_only = [
        {"identity": i, "entry_id": left_by_identity[i]["row"]["entry_id"],
         "row": _comparable(left_by_identity[i]["row"])}
        for i in sorted(set(left_by_identity) - set(right_by_identity))
    ]
    db_only = [
        {"identity": i, "entry_id": right_by_identity[i]["row"]["entry_id"],
         "row": _comparable(right_by_identity[i]["row"])}
        for i in sorted(set(right_by_identity) - set(left_by_identity))
    ]

    # Rows that look alike on name/date/amount but have no verified identity
    # on at least one side are a possible merge a human must confirm. They are
    # never merged, and they are held out of the one-sided lists so the five
    # states stay distinct and nothing is counted twice.
    ambiguous = []
    all_loose_left = _loose_index(left_rows)
    all_loose_right = _loose_index(right_rows)
    for key in sorted(set(all_loose_left) & set(all_loose_right)):
        lefts = all_loose_left[key]
        rights = all_loose_right[key]
        if all(_identity(r) for r in lefts) and all(_identity(r) for r in rights):
            # both sides carry a verified identity, so this is a real match and
            # was already compared above
            continue
        ambiguous.append({
            "loose_key": key,
            "left": [_diagnostic(r) for r in lefts],
            "right": [_diagnostic(r) for r in rights],
            "reason": "no verified source identity on at least one side",
        })
    consumed_left_ids = {r["entry_id"] for a in ambiguous for r in a["left"]}
    consumed_right_ids = {r["entry_id"] for a in ambiguous for r in a["right"]}

    ambiguous.extend(left_ambiguous["duplicate"])
    ambiguous.extend(right_ambiguous["duplicate"])
    consumed_left_ids.update(r["entry_id"] for a in right_ambiguous["duplicate"]
                             for r in a["left"])
    consumed_right_ids.update(r["entry_id"] for a in left_ambiguous["duplicate"]
                              for r in a["right"])

    for key, rows in sorted(left_ambiguous["loose"].items()):
        if rows[0]["entry_id"] in consumed_left_ids:
            continue
        google_only.append({"identity": "", "entry_id": rows[0]["entry_id"],
                            "row": _diagnostic(rows[0]),
                            "reason": "source has no verified identity"})
    for key, rows in sorted(right_ambiguous["loose"].items()):
        if rows[0]["entry_id"] in consumed_right_ids:
            continue
        db_only.append({"identity": "", "entry_id": rows[0]["entry_id"],
                        "row": _diagnostic(rows[0]),
                        "reason": "target has no verified identity"})

    return {
        "equal": equal,
        "mismatch": mismatch,
        "google_only": google_only,
        "db_only": db_only,
        "ambiguous": ambiguous,
        "counts": {
            "equal": len(equal), "mismatch": len(mismatch),
            "google_only": len(google_only), "db_only": len(db_only),
            "ambiguous": len(ambiguous),
        },
    }


def _loose_index(rows) -> dict:
    """Group every row by the fields that must never be a merge key."""
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(_loose_match_key(row), []).append(row)
    return grouped


def _index_side(rows, label):
    """Index one side by verified identity and collect what cannot be indexed."""
    by_identity = {}
    duplicates = {}
    loose = {}
    for row in rows:
        identity = _identity(row)
        if not identity:
            loose.setdefault(_loose_match_key(row), []).append(row)
            continue
        if identity in by_identity:
            duplicates.setdefault(identity, [by_identity[identity]["row"]]).append(row)
            continue
        by_identity[identity] = {"row": row, "entry_id": row["entry_id"]}
    for identity in list(duplicates):
        # a repeated identity is not decided here
        by_identity.pop(identity, None)
    no_identity = [
        {"loose_key": key, "left": [_diagnostic(r) for r in rows],
         "right": [], "reason": "no verified source identity on at least one side"}
        for key, rows in sorted(loose.items())
    ]
    for item in no_identity:
        if label == "right":
            item["left"], item["right"] = item["right"], item["left"]
    duplicate_items = [
        {"loose_key": f"{label}:{identity}",
         "left": [_diagnostic(r) for r in rows],
         "right": [],
         "reason": "the same source identity appears more than once on one side"}
        for identity, rows in sorted(duplicates.items())
    ]
    for item in duplicate_items:
        if label == "right":
            item["left"], item["right"] = item["right"], item["left"]
    return by_identity, {"loose": loose, "no_identity": no_identity,
                         "duplicate": duplicate_items}


def _entry_of_unused(identity: str) -> str:
    return identity


def _comparable(row: dict) -> dict:
    return {field: row.get(field) for field in BUSINESS_FIELDS}


def _diagnostic(row: dict) -> dict:
    """A comparable row plus the keys a human needs to look it up.

    Only used in the one-sided and ambiguous payloads, never in the field
    diff, so the entry id can never make two rows look different.
    """
    return dict(_comparable(row), entry_id=row.get("entry_id"),
                source_identity=row.get("source_identity") or "")


# --------------------------------------------------------------- the store
class MigrationStore:
    """Decisions and the migrated rows, in a DB that is not either source."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(MIGRATION_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------- input binding
    @staticmethod
    def input_sha256(rows: list[dict]) -> str:
        """The hash of the compared input, not of a run id or a timestamp."""
        payload = canonical_text([_comparable(r) for r in rows])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record_comparison(self, *, comparison_id: str, left_rows, right_rows,
                         summary: dict) -> dict:
        left_hash = self.input_sha256(left_rows)
        right_hash = self.input_sha256(right_rows)
        self.conn.execute(
            "INSERT INTO migration_comparisons(comparison_id,"
            " left_input_sha256, right_input_sha256, summary_json, created_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(comparison_id) DO UPDATE SET"
            " left_input_sha256=excluded.left_input_sha256,"
            " right_input_sha256=excluded.right_input_sha256,"
            " summary_json=excluded.summary_json",
            (comparison_id, left_hash, right_hash, canonical_text(summary),
             utc_now()))
        self.conn.commit()
        return {"comparison_id": comparison_id, "left_input_sha256": left_hash,
                "right_input_sha256": right_hash}

    def input_hashes(self, comparison_id: str) -> dict:
        row = self.conn.execute(
            "SELECT left_input_sha256, right_input_sha256"
            " FROM migration_comparisons WHERE comparison_id=?",
            (comparison_id,)).fetchone()
        if not row:
            raise MigrationError("UNKNOWN_COMPARISON", "비교 기록이 없어요")
        return {"left_input_sha256": row[0], "right_input_sha256": row[1]}

    # ------------------------------------------------------------ decisions
    def decide_field(self, *, comparison_id: str, entry_id: str, field: str,
                     chosen_side: str, user_id: str,
                     left_rows, right_rows) -> dict:
        """Record one explicit per-field choice for one mismatched field.

        The decision is bound to the comparison, both input hashes, the field,
        the value, the user and the timestamp. A decision made against other
        input hashes is not reusable later, so a changed source forces a new
        decision instead of silently inheriting the old one.
        """
        if field not in BUSINESS_FIELDS:
            raise MigrationError("UNKNOWN_FIELD", f"알 수 없는 업무 필드예요: {field}")
        if chosen_side not in ("left", "right"):
            raise MigrationError("INVALID_SIDE", "어느 쪽인지 정해 주세요")
        current = self.input_hashes(comparison_id)
        left_hash = self.input_sha256(left_rows)
        right_hash = self.input_sha256(right_rows)
        if (left_hash, right_hash) != (current["left_input_sha256"],
                                       current["right_input_sha256"]):
            raise MigrationError(
                "INPUT_CHANGED",
                "비교 대상이 바뀌었어요. 이전 결정을 재사용할 수 없으니 다시 확인해 주세요")
        left, right = self._resolve_pair(left_rows, right_rows, entry_id)
        if left is None or right is None:
            raise MigrationError("ENTRY_NOT_FOUND", "양쪽에 모두 있는 행이 아니에요")
        value = left[field] if chosen_side == "left" else right[field]
        decision_id = f"dec-{uuid.uuid4().hex[:16]}"
        self.conn.execute(
            "INSERT INTO migration_decisions(decision_id, comparison_id,"
            " entry_id, field, chosen_value, chosen_side, user_id,"
            " left_input_sha256, right_input_sha256, decided_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (decision_id, comparison_id, entry_id, field, canonical_text(value),
             chosen_side, user_id, left_hash, right_hash, utc_now()))
        self.conn.commit()
        return {"decision_id": decision_id, "entry_id": entry_id, "field": field,
                "chosen_value": value, "chosen_side": chosen_side,
                "user_id": user_id, "left_input_sha256": left_hash,
                "right_input_sha256": right_hash}

    def decisions_for(self, comparison_id: str, entry_id: str) -> dict:
        rows = self.conn.execute(
            "SELECT field, chosen_value, chosen_side, user_id,"
            " left_input_sha256, right_input_sha256, decided_at"
            " FROM migration_decisions WHERE comparison_id=? AND entry_id=?",
            (comparison_id, entry_id)).fetchall()
        return {r[0]: {"field": r[0], "chosen_value": json.loads(r[1]),
                       "chosen_side": r[2], "user_id": r[3],
                       "left_input_sha256": r[4], "right_input_sha256": r[5],
                       "decided_at": r[6]} for r in rows}

    @staticmethod
    def _row_by_entry(rows, entry_id):
        for row in rows:
            if row.get("entry_id") == entry_id:
                return row
        return None

    @staticmethod
    def _resolve_pair(left_rows, right_rows, entry_id):
        """Find the two rows of one pair.

        The two sides keep their own entry ids, so a left entry id is resolved
        to the shared source identity and the right row is found through that
        identity instead of through its own id.
        """
        left = MigrationStore._row_by_entry(left_rows, entry_id)
        if left is None:
            return None, None
        identity = _identity(left)
        right = None
        for row in right_rows:
            if _identity(row) == identity:
                right = row
                break
        return left, right

    # --------------------------------------------------------------- apply
    def apply(self, *, comparison_id: str, left_rows, right_rows, summary: dict,
              user_id: str, client_request_id: str) -> dict:
        """Apply the comparison to this migration DB only.

        Re-applying the same comparison with the same request id returns the
        first result without a second effect. A different request id over the
        same inputs is also idempotent, because each row is keyed by
        (comparison_id, side, entry_id) and an event is keyed by the same.
        """
        if not client_request_id:
            raise MigrationError("INVALID_VALUE", "요청 ID가 필요해요")
        left_hash = self.input_sha256(left_rows)
        right_hash = self.input_sha256(right_rows)
        existing = self.conn.execute(
            "SELECT result_json, left_input_sha256, right_input_sha256"
            " FROM migration_requests WHERE client_request_id=?",
            (client_request_id,)).fetchone()
        if existing:
            if (existing[1], existing[2]) != (left_hash, right_hash):
                raise MigrationError(
                    "REQUEST_ID_REUSED",
                    "같은 요청 ID로 다른 비교 입력을 보냈어요")
            result = json.loads(existing[0])
            result["reused"] = True
            return result

        decisions = {}
        for item in summary["mismatch"]:
            decided = self.decisions_for(comparison_id, item["entry_id"])
            decisions[item["entry_id"]] = decided
        unresolved_mismatch = []
        for item in summary["mismatch"]:
            decided = decisions[item["entry_id"]]
            missing = [f for f in item["changed_fields"] if f not in decided]
            if missing:
                # No default: an undecided field leaves the row unresolved.
                unresolved_mismatch.append(
                    {"entry_id": item["entry_id"], "undecided_fields": missing})

        written, events, provenance = [], [], []
        for item in summary["equal"]:
            row = self._row_by_entry(left_rows, item["entry_id"])
            written.append(self._write_row(comparison_id, "both",
                                          item["entry_id"], row, {}, user_id))
        for item in summary["google_only"]:
            row = self._row_by_entry(left_rows, item["entry_id"])
            written.append(self._write_row(comparison_id, "google_only",
                                          item["entry_id"], row, {}, user_id))
            events.append(self._event(comparison_id, "google_only",
                                      item["entry_id"], "insert", client_request_id,
                                      left_hash, right_hash, row))
        for item in summary["db_only"]:
            row = self._row_by_entry(right_rows, item["entry_id"])
            written.append(self._write_row(comparison_id, "db_only",
                                          item["entry_id"], row, {}, user_id))
            events.append(self._event(comparison_id, "db_only",
                                      item["entry_id"], "keep_existing",
                                      client_request_id, left_hash, right_hash, row))
        for item in summary["mismatch"]:
            decided = decisions[item["entry_id"]]
            if [f for f in item["changed_fields"] if f not in decided]:
                # unresolved: nothing is written for this row
                continue
            left, right = self._resolve_pair(left_rows, right_rows,
                                             item["entry_id"])
            if left is None or right is None:
                continue
            merged = dict(left)
            for field, choice in decided.items():
                merged[field] = choice["chosen_value"]
            written.append(self._write_row(comparison_id, "mismatch",
                                          item["entry_id"], merged, {}, user_id))
            # An amount or date disagreement is preserved on its own, so the
            # display choice never erases what the other side said.
            for field in item["changed_fields"]:
                provenance.append(self._provenance(
                    comparison_id, item["entry_id"], field, left, right,
                    left_hash, right_hash))
            events.append(self._event(comparison_id, "mismatch",
                                      item["entry_id"], "merged", client_request_id,
                                      left_hash, right_hash, merged))

        result = self._report(comparison_id, summary, unresolved_mismatch)
        self.conn.execute(
            "INSERT INTO migration_requests(client_request_id, comparison_id,"
            " left_input_sha256, right_input_sha256, result_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (client_request_id, comparison_id, left_hash, right_hash,
             canonical_text(result), utc_now()))
        self.conn.commit()
        result["reused"] = False
        return result

    def _write_row(self, comparison_id, side, entry_id, source_row, _unused,
                   user_id) -> dict:
        row_id = f"mig-{sha256_short(f'{comparison_id}|{side}|{entry_id}')}"
        self.conn.execute(
            "INSERT INTO migration_rows(row_id, comparison_id, side, entry_id,"
            " source_identity, row_kind, occurred_on, amount_krw, sign,"
            " customer_name, item, reservation_no, evidence_ref, memo,"
            " provenance_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(row_id) DO NOTHING",
            (row_id, comparison_id, side, entry_id,
             str(source_row.get("source_identity") or ""),
             "income" if int(source_row.get("amount_krw") or 0) > 0 else "expense",
             str(source_row.get("occurred_on") or ""),
             int(source_row.get("amount_krw") or 0),
             int(source_row.get("sign", 1)),
             str(source_row.get("customer_name") or ""),
             str(source_row.get("item") or ""),
             str(source_row.get("reservation_no") or ""),
             str(source_row.get("evidence_ref") or ""),
             str(source_row.get("memo") or ""),
             canonical_text({"source": side, "entry_id": entry_id,
                             "user_id": user_id}), utc_now()))
        return row_id

    def _event(self, comparison_id, side, entry_id, action, request_id,
               left_hash, right_hash, payload) -> dict:
        event_id = f"mev-{sha256_short(f'{comparison_id}|{side}|{entry_id}|{action}')}"
        self.conn.execute(
            "INSERT INTO migration_events(event_id, comparison_id, side, entry_id,"
            " source_identity, action, client_request_id, payload_json,"
            " left_input_sha256, right_input_sha256, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(event_id) DO NOTHING",
            (event_id, comparison_id, side, entry_id,
             str(payload.get("source_identity") or ""), action, request_id,
             canonical_text({k: payload.get(k) for k in BUSINESS_FIELDS}),
             left_hash, right_hash, utc_now()))
        return event_id

    def _provenance(self, comparison_id, entry_id, field, left, right,
                    left_hash, right_hash) -> dict:
        row_id = f"mig-{sha256_short(f'{comparison_id}|mismatch|{entry_id}')}"
        self.conn.execute(
            "INSERT INTO migration_provenance(row_id, field, left_value,"
            " right_value, left_input_sha256, right_input_sha256, recorded_at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(row_id, field) DO UPDATE SET"
            " left_value=excluded.left_value, right_value=excluded.right_value,"
            " left_input_sha256=excluded.left_input_sha256,"
            " right_input_sha256=excluded.right_input_sha256,"
            " recorded_at=excluded.recorded_at",
            (row_id, field, canonical_text(left.get(field)),
             canonical_text(right.get(field)), left_hash, right_hash, utc_now()))
        return {"row_id": row_id, "field": field,
                "left": left.get(field), "right": right.get(field)}

    # --------------------------------------------------------------- report
    def _report(self, comparison_id, summary, unresolved_mismatch) -> dict:
        counts = summary["counts"]
        rows = self.conn.execute(
            "SELECT row_kind, sign, amount_krw, evidence_ref, memo"
            " FROM migration_rows WHERE comparison_id=?", (comparison_id,)).fetchall()
        # The sign is applied, so an expense really is a negative contribution
        # and the balance is income + expense. Summing the bare amount would
        # make a signed total unsigned and hide a missing expense.
        signed_income = sum(r[2] * r[1] for r in rows if r[1] > 0)
        signed_expense = sum(r[2] * r[1] for r in rows if r[1] < 0)
        with_memo = sum(1 for r in rows if r[4])
        with_evidence = sum(1 for r in rows if r[3])
        provenance_count = self.conn.execute(
            "SELECT COUNT(*) FROM migration_provenance WHERE row_id IN"
            " (SELECT row_id FROM migration_rows WHERE comparison_id=?)",
            (comparison_id,)).fetchone()[0]
        events = self.conn.execute(
            "SELECT COUNT(*) FROM migration_events WHERE comparison_id=?",
            (comparison_id,)).fetchone()[0]
        # A business field is missing when a migrated row cannot answer it.
        missing_fields = self._missing_business_fields(comparison_id)
        unresolved = (counts["mismatch"] - len([u for u in unresolved_mismatch])
                      + counts["ambiguous"])
        return {
            "comparison_id": comparison_id,
            "counts": counts,
            "unresolved": {
                "total": unresolved,
                "ambiguous": counts["ambiguous"],
                "mismatch_undecided": unresolved_mismatch,
            },
            "migration_events": events,
            "migrated_rows": len(rows),
            "signed_totals": {
                "income_krw": signed_income,
                "expense_krw": signed_expense,
                "balance_krw": signed_income + signed_expense,
            },
            "preservation": {
                "rows_with_memo": with_memo,
                "rows_with_evidence": with_evidence,
                "provenance_records": provenance_count,
                "memo_preserved": with_memo > 0,
                "evidence_preserved": with_evidence > 0,
                "provenance_preserved": provenance_count > 0,
            },
            "missing_business_fields": missing_fields,
        }

    def _missing_business_fields(self, comparison_id) -> dict:
        rows = self.conn.execute(
            "SELECT row_id, customer_name, occurred_on, amount_krw, item,"
            " reservation_no FROM migration_rows WHERE comparison_id=?",
            (comparison_id,)).fetchall()
        missing: dict = {}
        for row in rows:
            for index, field in enumerate(
                    ("customer_name", "occurred_on", "amount_krw", "item",
                     "reservation_no"), start=1):
                value = row[index]
                if value in (None, "", 0):
                    missing.setdefault(field, []).append(row[0])
        return {k: sorted(v) for k, v in sorted(missing.items())}

    def provenance_rows(self, comparison_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT p.row_id, p.field, p.left_value, p.right_value"
            " FROM migration_provenance p JOIN migration_rows r"
            " ON r.row_id = p.row_id WHERE r.comparison_id=?"
            " ORDER BY p.row_id, p.field", (comparison_id,)).fetchall()
        return [{"row_id": r[0], "field": r[1],
                 "left": json.loads(r[2]), "right": json.loads(r[3])}
                for r in rows]


# ------------------------------------------------- Phase B read-only plan
# Sol-approved Phase B: deterministic, read-only eligible-import plan. This
# section adds no DB apply/write API and does not touch the synthetic
# SQLite-to-SQLite `compare_sources` / `MigrationStore` / `run_import` path
# above. It performs no filesystem or database I/O and never calls
# `MigrationStore` mutation methods or `run_import`.
REVIEWED_PLAN_MATCHED_DISPOSITION = "matched"


def _reviewed_plan_id(snapshot_sha256: str, ref: str, chosen_key: str) -> str:
    """Deterministic plan id over canonical structured fields.

    Hashes a canonical mapping instead of delimiter-joined text, so refs or
    keys containing a delimiter can never collide.
    """
    payload = {
        "snapshot_sha256": snapshot_sha256,
        "source_ref_snapshot_only": ref,
        "chosen_candidate_key": chosen_key,
    }
    return "rip-" + hashlib.sha256(
        canonical_text(payload).encode("utf-8")).hexdigest()[:16]


def _reviewed_plan_digest(snapshot_sha256, eligible_entries,
                          refused_records) -> str:
    """Canonical digest over allowlisted eligible and refused plan material.

    Builds the hashed structure itself from the given eligible entries and
    refused output records, keeping only stable fields. From each refused
    record only the stable identity, disposition, binding, approval flag,
    chosen key, candidate fingerprint/count and `reason_code` are kept.
    Display prose (`reason`) and `review_note` are excluded by the
    allowlist, so prose-only edits leave the digest unchanged.
    """
    entries = [{
        "source_ref_snapshot_only": e["source_ref_snapshot_only"],
        "review_snapshot_sha256": e["review_snapshot_sha256"],
        "chosen_candidate_key": e["chosen_candidate_key"],
        "candidate_transaction_keys": list(e["candidate_transaction_keys"]),
        "plan_id": e["plan_id"],
    } for e in eligible_entries]
    refused = [{
        "source_ref_snapshot_only": r["source_ref_snapshot_only"],
        "disposition": r["disposition"],
        "reason_code": r["reason_code"],
        "review_snapshot_sha256": r["review_snapshot_sha256"],
        "approved": r["approved"],
        "chosen_candidate_key": r["chosen_candidate_key"],
        "candidate_fingerprint": r["candidate_fingerprint"],
        "candidate_count": r["candidate_count"],
    } for r in refused_records]
    refused.sort(key=lambda e: canonical_text(e))
    core = {
        "snapshot_sha256": snapshot_sha256,
        "entries": entries,
        "refused": refused,
    }
    return hashlib.sha256(
        canonical_text(core).encode("utf-8")).hexdigest()


def build_reviewed_import_plan(snapshot_sha256, review_rows) -> dict:
    """Build a deterministic, read-only eligible-import plan for one snapshot.

    Accepted input shape: already-normalized synthetic dict fixtures only::

        snapshot_sha256: str -- current snapshot hash this plan is built for.
            Must be type str and non-blank (empty or whitespace-only is
            blank and refused); no coercion is applied.
        review_rows: iterable of dicts, each holding exactly:
          - source_ref_snapshot_only: str (required; empty or whitespace-only
            is blank and refused; an accepted value is kept byte-for-byte
            with no trimming; exact type)
          - candidate_count: None, omitted, or exact int >= 0
            (type(value) is int; bool, float, string and negatives are refused;
            when present must equal len(candidate_transaction_keys))
          - candidate_transaction_keys: list/tuple of str, never a string
            (each entry must satisfy type(entry) is str and be non-blank:
            empty or whitespace-only entries are refused; duplicates are
            refused; accepted keys are kept byte-for-byte)
          - disposition: str (only exact "matched" may be eligible; the
            caller sets this only after a human explicitly approves and
            selects a candidate; raw manifest values such as
            "candidate_review_required" and "unmatched_review_required" are
            refused, as are "unmatched", blank and unknown)
          - approved: bool (required; type(value) is bool and must be True;
            truthy non-bool values such as 1 or "approve" are refused)
          - chosen_candidate_key: str (required explicit target-side plan
            identity; empty or whitespace-only is blank and refused; never
            inferred, even for a single candidate; kept byte-for-byte)
          - review_note: str (optional; preserved when present, never required;
            excluded from the plan digest)
          - review_snapshot_sha256: str (required decision-to-snapshot
            binding; empty or whitespace-only is blank and refused, otherwise
            must equal `snapshot_sha256` exactly)

    The external review manifest is never read or edited here.

    Identity and scope
    ------------------
    `(snapshot_sha256, source_ref_snapshot_only)` is a same-snapshot
    review-plan identity only. It is not a cross-snapshot or persistent
    business identity: a changed snapshot hash never inherits a prior
    snapshot's approval because the row binding must equal the current
    `snapshot_sha256`, otherwise the row is refused.

    Fail-closed rules (each unresolved row is preserved in `refused` with a
    `reason_code`, never dropped and never auto-selected):

    * snapshot/ref/binding/disposition/chosen key/candidate entries that are
      not strings, empty or whitespace-only where a value is required, or
      otherwise mistyped
    * `candidate_count` that is bool, float, string or negative
    * binding missing or not exactly equal to the current snapshot hash
    * zero candidates, or inconsistent count/list (string list, blank or
      whitespace-only entry, non-string entry, duplicate entries, or
      count/list length mismatch)
    * any `disposition` other than exact "matched"
    * `approved` anything other than boolean True
    * missing chosen key or a chosen key not in the candidate list
    * duplicate `(snapshot_sha256, source_ref_snapshot_only)` within one call

    Determinism and purity
    ----------------------
    Candidate order is not meaningful: eligible entries carry
    `candidate_transaction_keys` sorted, refused-row candidate fingerprints
    carry their items sorted, and the digest covers the sorted sets.
    Eligible and refused lists are sorted by
    `source_ref_snapshot_only`, and the digest helper sorts the allowlisted
    refused material by its canonical form so input order never moves the
    digest. Plan ids hash
    canonical structured fields via `canonical_text` (never delimiter-joined
    text). `plan_digest` covers the current snapshot hash, each eligible row
    (snapshot binding, sorted candidate set, chosen key) and every refused
    row (stable row identity/source ref, disposition, stable `reason_code`,
    plus safe identity fields for changed binding/candidate input:
    binding, approval flag, chosen key, candidate fingerprint and count).
    Display prose (`reason`) and `review_note` are excluded from the digest,
    so prose-only edits leave it unchanged. Identical inputs give identical
    order, ids and digests. This function has no filesystem or database
    side effects and never calls `MigrationStore` mutation methods or
    `run_import`.
    """
    snapshot_is_str = type(snapshot_sha256) is str
    # Whitespace-only is blank, like ref/chosen/binding: short-circuit keeps
    # this safe for a non-string snapshot (no .strip() call on it).
    snapshot_empty = (not snapshot_is_str) or (snapshot_sha256.strip() == "")
    snapshot = snapshot_sha256 if snapshot_is_str else ""
    try:
        rows = list(review_rows) if review_rows is not None else []
    except TypeError:
        rows = []

    normalized: list[dict] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            normalized.append({"index": index, "row_invalid": True})
            continue
        row = raw
        ref_val = row.get("source_ref_snapshot_only")
        binding_val = row.get("review_snapshot_sha256")
        disposition_val = row.get("disposition")
        chosen_val = row.get("chosen_candidate_key")
        approved_val = row.get("approved")
        note_val = row.get("review_note")
        note = note_val if type(note_val) is str else ""

        raw_candidates = row.get("candidate_transaction_keys")
        candidates: list[str] = []
        candidates_error = False
        candidates_missing = ("candidate_transaction_keys" not in row
                              or raw_candidates is None)
        if candidates_missing or isinstance(raw_candidates, str):
            candidates_error = True
        elif isinstance(raw_candidates, (list, tuple)):
            seen: set[str] = set()
            for item in raw_candidates:
                # Whitespace-only entries are blank and refused. Accepted
                # values are kept byte-for-byte: nothing is trimmed here.
                if type(item) is not str or item.strip() == "":
                    candidates_error = True
                    candidates = []
                    break
                if item in seen:
                    candidates_error = True
                    candidates = []
                    break
                seen.add(item)
                candidates.append(item)
        else:
            candidates_error = True
        # Stable, prose-free fingerprint of the candidate input so the plan
        # digest binds changed candidate input for refused rows too. Valid
        # candidate strings are recorded byte-for-byte; a raw string
        # container itself is an invalid container, so it carries only its
        # stable kind marker, never its raw value. Mistyped entries carry
        # only a stable type marker, never repr(). Items are sorted by
        # canonical form so candidate order and list-vs-tuple never drift
        # the digest where the candidate set is the same.
        if isinstance(raw_candidates, str):
            candidates_fp: dict = {"kind": "string"}
        elif isinstance(raw_candidates, (list, tuple)):
            fp_items = []
            for entry in raw_candidates:
                if type(entry) is str:
                    fp_items.append({"key": entry})
                else:
                    fp_items.append({
                        "non_string_type": type(entry).__name__,
                    })
            fp_items.sort(key=canonical_text)
            candidates_fp = {"kind": "sequence", "items": fp_items}
        elif candidates_missing:
            candidates_fp = {"kind": "missing"}
        else:
            candidates_fp = {"kind": "invalid",
                             "type": type(raw_candidates).__name__}

        count_present = ("candidate_count" in row
                         and row.get("candidate_count") is not None)
        count = None
        count_error = False
        if count_present:
            count_val = row.get("candidate_count")
            if type(count_val) is not int or count_val < 0:
                count_error = True
            else:
                count = count_val
        normalized.append({
            "index": index,
            "row_invalid": False,
            "ref_val": ref_val,
            "binding_val": binding_val,
            "disposition_val": disposition_val,
            "chosen_val": chosen_val,
            "approved_val": approved_val,
            "note": note,
            "candidates": candidates,
            "candidates_error": candidates_error,
            "candidates_fp": candidates_fp,
            "count": count,
            "count_error": count_error,
        })

    ref_counts: dict[str, int] = {}
    for item in normalized:
        if item.get("row_invalid"):
            continue
        ref_val = item["ref_val"]
        if type(ref_val) is str and ref_val != "":
            ref_counts[ref_val] = ref_counts.get(ref_val, 0) + 1

    eligible: list[dict] = []
    refused: list[dict] = []

    def refuse(item, ref_text, code, reason):
        # The refused output record carries the display fields (`reason`,
        # `review_note`) together with the stable digest fields (identity,
        # disposition, reason code, binding, approval flag, chosen key,
        # candidate fingerprint/count). `_reviewed_plan_digest` allowlists
        # the stable subset itself, so prose-only edits never move it.
        disp_val = item.get("disposition_val")
        bind_val = item.get("binding_val")
        chosen_raw = item.get("chosen_val")
        appr_val = item.get("approved_val")
        refused.append({
            "source_ref_snapshot_only": ref_text,
            "disposition": disp_val if type(disp_val) is str else "",
            "reason_code": code,
            "reason": reason,
            "review_note": item.get("note", ""),
            "review_snapshot_sha256": bind_val if type(bind_val) is str else "",
            "approved": True if type(appr_val) is bool and appr_val is True
            else False,
            "chosen_candidate_key": chosen_raw if type(chosen_raw) is str
            else "",
            "candidate_fingerprint": item.get("candidates_fp",
                                              {"kind": "missing"}),
            "candidate_count": item.get("count"),
        })

    for item in normalized:
        if item.get("row_invalid"):
            refuse(item, "", "INVALID_ROW_TYPE",
                   "row is not a mapping; refused fail-closed")
            continue
        ref_val = item["ref_val"]
        ref_text = ref_val if type(ref_val) is str else ""
        if not snapshot_is_str:
            refuse(item, ref_text, "INVALID_SNAPSHOT_HASH_TYPE",
                   "current snapshot hash is not a string; refused fail-closed")
            continue
        if snapshot_empty:
            refuse(item, ref_text, "MISSING_SNAPSHOT_HASH",
                   "snapshot hash is missing; refused without a current snapshot")
            continue
        if type(ref_val) is not str:
            refuse(item, ref_text, "INVALID_REF_TYPE",
                   "source ref is not a string; refused without coercion")
            continue
        if ref_val == "" or ref_val.strip() == "":
            refuse(item, ref_text, "MISSING_REF",
                   "source ref is blank; refused without a plan identity")
            continue
        if ref_counts.get(ref_val, 0) > 1:
            refuse(item, ref_text, "DUPLICATE_REF",
                   f"duplicate (snapshot, ref) {ref_val!r} in the same snapshot;"
                   " refused without choosing one")
            continue
        binding_val = item["binding_val"]
        if type(binding_val) is not str:
            refuse(item, ref_text, "INVALID_BINDING_TYPE",
                   "decision-to-snapshot binding is not a string; refused")
            continue
        if binding_val.strip() == "":
            refuse(item, ref_text, "MISSING_BINDING",
                   "decision-to-snapshot binding is missing; refused fail-closed")
            continue
        if binding_val != snapshot:
            refuse(item, ref_text, "BINDING_MISMATCH",
                   "binding does not equal the current snapshot hash;"
                   " a changed snapshot never inherits a prior approval")
            continue
        candidates = item["candidates"]
        if item["candidates_error"] or item["count_error"]:
            refuse(item, ref_text, "INCONSISTENT_CANDIDATES",
                   "candidate count/list is inconsistent or mistyped;"
                   " refused without guessing")
            continue
        if item["count"] is not None and item["count"] != len(candidates):
            refuse(item, ref_text, "INCONSISTENT_CANDIDATES",
                   f"candidate_count {item['count']} !="
                   f" {len(candidates)} listed keys; refused without guessing")
            continue
        if len(candidates) == 0:
            refuse(item, ref_text, "ZERO_CANDIDATES",
                   "no candidate transaction keys; refused without a target")
            continue
        disposition_val = item["disposition_val"]
        if type(disposition_val) is not str:
            refuse(item, ref_text, "INVALID_DISPOSITION_TYPE",
                   "disposition is not a string; refused without coercion")
            continue
        if disposition_val != REVIEWED_PLAN_MATCHED_DISPOSITION:
            refuse(item, ref_text, "UNMATCHED_DISPOSITION",
                   f"disposition {disposition_val!r} is not 'matched';"
                   " raw review states stay refused until validly normalized")
            continue
        approved_val = item["approved_val"]
        if type(approved_val) is not bool or approved_val is not True:
            refuse(item, ref_text, "NOT_APPROVED",
                   "approved is not boolean True; refused without approval")
            continue
        chosen_val = item["chosen_val"]
        if type(chosen_val) is not str:
            refuse(item, ref_text, "INVALID_SELECTED_KEY_TYPE",
                   "chosen candidate key is not a string; refused")
            continue
        if chosen_val == "" or chosen_val.strip() == "":
            refuse(item, ref_text, "MISSING_SELECTED_KEY",
                   "chosen candidate key is blank;"
                   " the selection is never inferred")
            continue
        if chosen_val not in candidates:
            refuse(item, ref_text, "SELECTION_NOT_IN_CANDIDATES",
                   "chosen key is not in the candidate list; refused"
                   " without guessing")
            continue
        sorted_keys = sorted(candidates)
        plan_id = _reviewed_plan_id(snapshot, ref_val, chosen_val)
        eligible.append({
            "source_ref_snapshot_only": ref_val,
            "chosen_candidate_key": chosen_val,
            "candidate_transaction_keys": sorted_keys,
            "review_snapshot_sha256": binding_val,
            "plan_id": plan_id,
            "review_note": item["note"],
        })

    eligible.sort(key=lambda e: e["source_ref_snapshot_only"])
    refused.sort(key=lambda e: (e["source_ref_snapshot_only"], e["reason_code"]))
    plan_digest = _reviewed_plan_digest(snapshot, eligible, refused)
    return {
        "snapshot_sha256": snapshot,
        "eligible": eligible,
        "refused": refused,
        "counts": {"eligible": len(eligible), "refused": len(refused),
                   "total": len(normalized)},
        "plan_digest": plan_digest,
    }


def sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------- the flow
def seal_and_verify_sources(left_db, right_db, work_dir, *,
                            left_gate=None, right_gate=None) -> dict:
    """Seal both sources read-only and verify them before any comparison.

    Reuses `snapshot_descriptor` rather than a second sealing scheme, and
    refuses a source that still has an SQLite sidecar next to it. The
    descriptor is written beside the source, because it records the source by
    bare file name and `verify_snapshot` resolves that name next to the
    descriptor. Nothing in the source database itself is written.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for label, db, gate in (("google", left_db, left_gate),
                            ("db", right_db, right_gate)):
        db = Path(db)
        gate_path = Path(gate) if gate else None
        if gate_path is not None and gate_path.parent.resolve() != db.parent.resolve():
            # verify_snapshot resolves the report name next to the descriptor,
            # so the descriptor has to live where the report is.
            local_gate = db.parent / gate_path.name
            if not local_gate.is_file():
                raise MigrationError("GATE_REPORT_MISSING",
                                     f"봉인 보고서를 찾을 수 없어요: {gate_path}")
            gate_path = local_gate
        descriptor_path = db.with_name(f"{label}.snapshot.json")
        descriptor = seal_snapshot(db, gate_report_path=gate_path,
                                   output_path=descriptor_path)
        verified = verify_snapshot(descriptor_path)
        if not verified["ok"]:
            raise MigrationError("SNAPSHOT_NOT_SEALED",
                                 f"{label} 원천 봉인 검증 실패: {verified['problems']}")
        out[label] = {
            "descriptor_path": str(descriptor_path),
            "sha256": descriptor["candidate_db"]["sha256"],
            "size_bytes": descriptor["candidate_db"]["size_bytes"],
            "semantic_sha256": descriptor.get("candidate_semantic_sha256"),
            "verified": True,
        }
    return out


def run_import(*, left_db, right_db, migration_db, work_dir, user_id,
               client_request_id, comparison_id=None,
               decisions: dict | None = None,
               left_gate=None, right_gate=None) -> dict:
    """The whole local import: seal, verify, compare, decide, apply, report.

    `decisions` maps entry_id -> {field: "left"|"right"}. Every changed field
    of every mismatched row must appear; a missing one leaves that row
    unresolved instead of defaulting to one side.
    """
    sealed = seal_and_verify_sources(left_db, right_db, work_dir,
                                     left_gate=left_gate, right_gate=right_gate)
    left_rows = read_source_entries(left_db)
    right_rows = read_source_entries(right_db)
    summary = compare_sources(left_rows, right_rows)
    comparison_id = comparison_id or f"cmp-{uuid.uuid4().hex[:16]}"
    store = MigrationStore(migration_db)
    try:
        store.record_comparison(comparison_id=comparison_id, left_rows=left_rows,
                                right_rows=right_rows, summary=summary)
        for entry_id, fields in (decisions or {}).items():
            for field, side in fields.items():
                store.decide_field(comparison_id=comparison_id, entry_id=entry_id,
                                   field=field, chosen_side=side, user_id=user_id,
                                   left_rows=left_rows, right_rows=right_rows)
        result = store.apply(comparison_id=comparison_id, left_rows=left_rows,
                             right_rows=right_rows, summary=summary,
                             user_id=user_id, client_request_id=client_request_id)
        result["sealed_sources"] = sealed
        result["summary"] = summary
        result["comparison_id"] = comparison_id
        result["sources_unmodified"] = {
            "google_sha256": sha256_file(left_db),
            "db_sha256": sha256_file(right_db),
        }
        return result
    finally:
        store.close()
