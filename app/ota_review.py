"""OTA 수동 연결과 승인 규칙을 전용 검토 데이터베이스에 보존한다."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.ota_payments import (
    _NO_ALLOCATION_SNAPSHOT,
    _approved_lag_match, _digest, _direction, _event_amount, _event_is_paid,
    _rule_scope_valid,
    _has_corroborator, match_ota_payment_events,
)


def _dump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _narrow(conditions):
    return _rule_scope_valid(conditions)


def _proposal_conditions(event, transaction):
    conditions = {"provider":event.get("provider"), "item":event.get("item"),
                  "merchant_normalized":transaction.get("merchant_normalized"),
                  "issuer":transaction.get("issuer"),
                  "card_last4":transaction.get("card_tail"), "date_lag_days":0,
                  "currency":event.get("currency"), "event_type":event.get("event_type")}
    conditions = {key:value for key, value in conditions.items() if value not in (None, "")}
    warnings = []
    try:
        paid_on = date.fromisoformat(event["paid_on"])
        approval_date = date.fromisoformat(transaction["approval_date"])
        lag = (approval_date - paid_on).days
        if abs(lag) <= 7:
            conditions["date_lag_days"] = lag
        else:
            warnings.append("date_lag_out_of_supported_range")
    except (KeyError, TypeError, ValueError):
        warnings.append("verified_date_pair_required")
    if (event.get("event_type") != "charge" or event.get("currency") != "KRW" or
            transaction.get("transaction_direction") != "purchase" or
            transaction.get("foreign_currency") not in (None, "", "KRW") or
            transaction.get("currency") not in (None, "", "KRW")):
        warnings.append("signed_krw_charge_delta_required")
    else:
        try:
            ota_amount = Decimal(str(event["amount_krw"]))
            card_amount = Decimal(str(transaction["amount_krw"]))
            delta = card_amount - ota_amount
            if (not ota_amount.is_finite() or not card_amount.is_finite() or
                    ota_amount != ota_amount.to_integral_value() or
                    card_amount != card_amount.to_integral_value() or
                    ota_amount <= 0 or card_amount <= 0):
                warnings.append("signed_krw_charge_delta_required")
            elif -10000 <= delta <= 10000:
                conditions["amount_delta_krw"] = int(delta)
            else:
                warnings.append("amount_delta_out_of_supported_range")
        except (KeyError, InvalidOperation, TypeError, ValueError):
            warnings.append("signed_krw_charge_delta_required")
    return conditions, sorted(set(warnings))


BOOKING_TRIP_BASIS_LIMIT = 600


class BookingTripError(Exception):
    """A refused booking-trip write. `code` is stable; `message` is for the owner."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _create_booking_trip_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ota_review_booking_trips(
            provider TEXT NOT NULL, booking_ref TEXT NOT NULL,
            trip_tab_id TEXT NOT NULL, trip_code TEXT NOT NULL, basis TEXT NOT NULL,
            revision INTEGER NOT NULL, status TEXT NOT NULL,
            user TEXT NOT NULL, changed_at TEXT NOT NULL,
            PRIMARY KEY (provider, booking_ref));
        CREATE TABLE IF NOT EXISTS ota_review_booking_trip_history(
            provider TEXT NOT NULL, booking_ref TEXT NOT NULL, revision INTEGER NOT NULL,
            trip_tab_id TEXT NOT NULL, trip_code TEXT NOT NULL, basis TEXT NOT NULL,
            status TEXT NOT NULL, user TEXT NOT NULL, changed_at TEXT NOT NULL,
            PRIMARY KEY (provider, booking_ref, revision));
    """)


def _utc_now_text():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_booking_trip(conn, provider, booking_ref, expected_revision, user, status, current, *,
                        trip_tab_id, trip_code, basis):
    have = int(current["revision"]) if current is not None else 0
    if int(expected_revision) != have:
        raise BookingTripError("REVISION_CONFLICT", "다른 곳에서 먼저 바꿨어요. 새로고침해 주세요")
    revision = have + 1
    now = _utc_now_text()
    conn.execute(
        "INSERT INTO ota_review_booking_trips(provider,booking_ref,trip_tab_id,trip_code,basis,revision,status,user,changed_at)"
        " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(provider,booking_ref) DO UPDATE SET"
        " trip_tab_id=excluded.trip_tab_id, trip_code=excluded.trip_code, basis=excluded.basis,"
        " revision=excluded.revision, status=excluded.status, user=excluded.user, changed_at=excluded.changed_at",
        (str(provider), str(booking_ref), str(trip_tab_id), str(trip_code), basis, revision, status,
         str(user), now))
    conn.execute(
        "INSERT INTO ota_review_booking_trip_history(provider,booking_ref,revision,trip_tab_id,trip_code,basis,status,user,changed_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (str(provider), str(booking_ref), revision, str(trip_tab_id), str(trip_code), basis, status,
         str(user), now))
    return {"provider": str(provider), "booking_ref": str(booking_ref), "trip_tab_id": str(trip_tab_id),
            "trip_code": str(trip_code), "basis": basis, "revision": revision, "status": status}


class OtaReviewStore:
    """명시한 분리 SQLite만 사용한다. 기본 경로나 운영 DB를 찾지 않는다."""

    def __init__(self, path):
        if path is None:
            raise ValueError("EXPLICIT_REVIEW_DATABASE_REQUIRED")
        self.path = Path(path)
        self.conn = None
        if self.path.is_file():
            self.conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row
            self._check_isolated()

    def _check_isolated(self):
        existing_tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if any(not name.startswith("ota_review_") for name in existing_tables):
            if self.conn:
                self.conn.close()
                self.conn = None
            raise ValueError("REVIEW_DATABASE_NOT_ISOLATED")

    def _ensure_initialized(self):
        if self.conn:
            self.conn.close()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._check_isolated()
        self.conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS ota_review_links(
                event_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL, transaction_json TEXT NOT NULL,
                source_digest TEXT, evidence_changed INTEGER NOT NULL DEFAULT 0,
                evidence_missing INTEGER NOT NULL DEFAULT 0,
                user TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS ota_review_event_crosswalk(
                old_event_id TEXT PRIMARY KEY, current_event_id TEXT NOT NULL,
                evidence_digest TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS ota_review_proposals(
                proposal_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, transaction_id TEXT NOT NULL,
                conditions_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                answer_json TEXT, user TEXT NOT NULL, review_warning TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS ota_review_rules(
                rule_id TEXT PRIMARY KEY, version INTEGER NOT NULL, conditions_json TEXT NOT NULL,
                source_event_id TEXT NOT NULL, source_transaction_id TEXT NOT NULL,
                approved_by TEXT NOT NULL, user_confirmation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS ota_review_requests(
                request_id TEXT PRIMARY KEY, result_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ota_review_group_pins(
                group_id TEXT PRIMARY KEY, event_ids_json TEXT NOT NULL, card_ids_json TEXT NOT NULL,
                mapping_json TEXT NOT NULL, confirmed_by TEXT NOT NULL,
                confirmed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, version INTEGER NOT NULL,
                order_snapshot_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS ota_review_group_requests(
                request_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, result_json TEXT NOT NULL);
        """)
        _create_booking_trip_tables(self.conn)
        group_request_columns = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(ota_review_group_requests)")}
        if "request_digest" not in group_request_columns:
            self.conn.execute("ALTER TABLE ota_review_group_requests "
                              "ADD COLUMN request_digest TEXT NOT NULL DEFAULT ''")
        proposal_columns = {row[1] for row in self.conn.execute(
            "PRAGMA table_info(ota_review_proposals)")}
        if "review_warning" not in proposal_columns:
            self.conn.execute("ALTER TABLE ota_review_proposals ADD COLUMN review_warning TEXT NOT NULL DEFAULT '[]'")
        pin_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(ota_review_group_pins)")}
        if "order_snapshot_json" not in pin_columns:
            self.conn.execute("ALTER TABLE ota_review_group_pins ADD COLUMN order_snapshot_json TEXT NOT NULL DEFAULT '{}'")
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def _has_table(self, name):
        if not self.conn:
            return False
        return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                 (name,)).fetchone() is not None

    def links(self):
        if not self._has_table("ota_review_links"):
            return {}
        return {row["event_id"]: {"transaction_id": row["transaction_id"],
                                  "status": "MATCHED_USER", "source_digest": row["source_digest"],
                                  "evidence_changed": bool(row["evidence_changed"]),
                                  "evidence_missing": bool(row["evidence_missing"])}
                for row in self.conn.execute("SELECT * FROM ota_review_links ORDER BY event_id")}

    def reservation_links(self):
        """예약 관계만 읽는다. 없는 DB/테이블은 읽기 경로에서 만들지 않는다."""
        if not self._has_table("ota_review_reservation_links"):
            return {}
        return {row["event_id"]: {"status": "USER_CONFIRMED",
                "transaction_id": row["transaction_id"], "basis": row["basis"],
                "amount_status": row["amount_status"], "payment_verified": False,
                "revision": row["revision"], "event": json.loads(row["event_json"]),
                "transaction": json.loads(row["transaction_json"])}
                for row in self.conn.execute("SELECT * FROM ota_review_reservation_links ORDER BY event_id")}

    def reservation_preview(self, event, transaction):
        from app.toyoko_reservation_links import relation_digest
        digest = relation_digest(event, transaction)
        return {"preview_digest": digest, "event_id": str(event.get("ota_event_id") or ""),
                "transaction_id": str(transaction.get("transaction_id") or "")}

    def confirm_reservation(self, event, transaction, preview_digest, *, expected_revision, request_id,
                            user, basis="USER_CONFIRMED", amount_status="UNKNOWN"):
        from app.toyoko_reservation_links import relation_digest
        request_id = str(request_id).strip()
        event_id = str(event.get("ota_event_id") or "")
        transaction_id = str(transaction.get("transaction_id") or "")
        request_digest = self.reservation_request_digest(event_id, transaction_id, preview_digest,
                                                         expected_revision, user)
        if not request_id or not event_id or not transaction_id:
            raise ValueError("STABLE_IDENTITIES_REQUIRED")
        if amount_status not in ("MATCH", "UNKNOWN", "MISMATCH"):
            raise ValueError("INVALID_RESERVATION_AMOUNT_STATUS")
        if self._has_table("ota_review_reservation_requests"):
            prior = self.conn.execute("SELECT request_digest,result_json FROM ota_review_reservation_requests WHERE request_id=?",
                                      (request_id,)).fetchone()
            if prior:
                if prior[0] != request_digest:
                    raise ValueError("REQUEST_ID_REUSED")
                return json.loads(prior[1])
        if preview_digest != relation_digest(event, transaction):
            raise ValueError("STALE_RESERVATION_PREVIEW")
        self._ensure_initialized()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS ota_review_reservation_links(
                event_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL,
                event_json TEXT NOT NULL, transaction_json TEXT NOT NULL,
                basis TEXT NOT NULL, amount_status TEXT NOT NULL,
                revision INTEGER NOT NULL, user TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS ota_review_reservation_requests(
                request_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL,
                result_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ota_review_reservation_history(
                event_id TEXT NOT NULL, revision INTEGER NOT NULL, transaction_id TEXT NOT NULL,
                result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(event_id,revision));
        """)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            prior = self.conn.execute("SELECT request_digest,result_json FROM ota_review_reservation_requests WHERE request_id=?",
                                      (request_id,)).fetchone()
            if prior:
                if prior[0] != request_digest:
                    raise ValueError("REQUEST_ID_REUSED")
                result = json.loads(prior[1])
                self.conn.commit()
                return result
            paid_owner = self.conn.execute("SELECT event_id FROM ota_review_links WHERE transaction_id=?",
                                           (transaction_id,)).fetchone()
            if paid_owner:
                raise ValueError("RESERVATION_CARD_OCCUPIED")
            if self._has_table("ota_review_group_pins"):
                for row in self.conn.execute("SELECT event_ids_json,card_ids_json FROM ota_review_group_pins"):
                    if transaction_id in set(map(str, json.loads(row["card_ids_json"]))):
                        raise ValueError("RESERVATION_CARD_OCCUPIED")
            occupied = self.conn.execute("SELECT event_id FROM ota_review_reservation_links WHERE transaction_id=? AND event_id<>?",
                                         (transaction_id, event_id)).fetchone()
            if occupied:
                raise ValueError("RESERVATION_CARD_OCCUPIED")
            current = self.conn.execute("SELECT revision FROM ota_review_reservation_links WHERE event_id=?",
                                        (event_id,)).fetchone()
            have_revision = int(current[0]) if current else 0
            if int(expected_revision) != have_revision:
                raise ValueError("STALE_RESERVATION_REVISION")
            revision = have_revision + 1
            result = {"status": "USER_CONFIRMED", "transaction_id": transaction_id,
                      "basis": str(basis), "amount_status": amount_status,
                      "payment_verified": False, "revision": revision}
            params = (event_id, transaction_id, _dump(event), _dump(transaction),
                      str(basis), amount_status, revision, str(user))
            self.conn.execute("INSERT INTO ota_review_reservation_links(event_id,transaction_id,event_json,transaction_json,basis,amount_status,revision,user) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET transaction_id=excluded.transaction_id,event_json=excluded.event_json,transaction_json=excluded.transaction_json,basis=excluded.basis,amount_status=excluded.amount_status,revision=excluded.revision,user=excluded.user,updated_at=CURRENT_TIMESTAMP", params)
            self.conn.execute("INSERT INTO ota_review_reservation_history(event_id,revision,transaction_id,result_json) VALUES(?,?,?,?)",
                              (event_id, revision, transaction_id, _dump(result)))
            self.conn.execute("INSERT INTO ota_review_reservation_requests(request_id,request_digest,result_json) VALUES(?,?,?)",
                              (request_id, request_digest, _dump(result)))
            self.conn.commit()
            return result
        except BaseException:
            self.conn.rollback()
            raise

    def reservation_request_digest(self, event_id, transaction_id, preview_digest, expected_revision, user):
        return _digest({"event_id": str(event_id), "transaction_id": str(transaction_id),
                        "preview_digest": str(preview_digest), "expected_revision": int(expected_revision),
                        "user": str(user)})

    def prior_reservation_confirmation(self, request_id, event_id, transaction_id, preview_digest,
                                       expected_revision, user):
        if not self._has_table("ota_review_reservation_requests"):
            return None
        digest = self.reservation_request_digest(event_id, transaction_id, preview_digest,
                                                expected_revision, user)
        row = self.conn.execute("SELECT request_digest,result_json FROM ota_review_reservation_requests WHERE request_id=?",
                                (str(request_id),)).fetchone()
        if row and row[0] != digest:
            raise ValueError("REQUEST_ID_REUSED")
        return json.loads(row[1]) if row else None

    def prior_confirmation(self, request_id):
        """The result an earlier confirm with this request id recorded, or None. Read only."""
        if not self._has_table("ota_review_requests"):
            return None
        row = self.conn.execute("SELECT result_json FROM ota_review_requests WHERE request_id=?",
                                (str(request_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def event_snapshots(self):
        """Read-only snapshots keyed by event ID, including persisted evidence warnings."""
        if not self._has_table("ota_review_links"):
            return {}
        snapshots = {}
        for row in self.conn.execute(
                "SELECT event_id,event_json,evidence_changed,evidence_missing FROM ota_review_links ORDER BY event_id"):
            snapshot = json.loads(row["event_json"])
            snapshot["_evidence_changed"] = bool(row["evidence_changed"])
            snapshot["_evidence_missing"] = bool(row["evidence_missing"])
            snapshots[row["event_id"]] = snapshot
        return snapshots

    def event_crosswalks(self):
        """Persisted legacy-to-current IDs for user-pinned payment events."""
        if not self._has_table("ota_review_event_crosswalk"):
            return {}
        return {row["old_event_id"]: {
            "current_event_id": row["current_event_id"],
            "evidence_digest": row["evidence_digest"],
        } for row in self.conn.execute(
            "SELECT old_event_id,current_event_id,evidence_digest "
            "FROM ota_review_event_crosswalk ORDER BY old_event_id")}

    def active_rules(self):
        if not self._has_table("ota_review_rules"):
            return []
        return [{"rule_id": row["rule_id"], "version": row["version"],
                 "conditions": json.loads(row["conditions_json"]),
                 "source_event_id": row["source_event_id"], "approved_by": row["approved_by"],
                 "source_transaction_id": row["source_transaction_id"],
                 "user_confirmation": json.loads(row["user_confirmation"]),
                 "created_at": row["created_at"], "active": bool(row["active"]),
                 "status": "active" if row["active"] else "inactive"}
                for row in self.conn.execute("SELECT * FROM ota_review_rules WHERE active=1 ORDER BY rule_id")]

    def _open_reader(self):
        """Opens the read connection on first use, so a store made before the file existed sees later writes."""
        if self.conn is None and self.path.is_file():
            self.conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row

    def booking_trip_rules(self):
        """Active owner trip assignments keyed by (provider, booking_ref). Read only."""
        self._open_reader()
        if not self._has_table("ota_review_booking_trips"):
            return {}
        return {(row["provider"], row["booking_ref"]): self._booking_trip_row(row)
                for row in self.conn.execute(
                    "SELECT * FROM ota_review_booking_trips WHERE status='active' ORDER BY provider, booking_ref")}

    def booking_trip_states(self):
        """Every booking's current trip rule, active or revoked, keyed by (provider, booking_ref). Read only."""
        self._open_reader()
        if not self._has_table("ota_review_booking_trips"):
            return {}
        return {(row["provider"], row["booking_ref"]): self._booking_trip_row(row)
                for row in self.conn.execute("SELECT * FROM ota_review_booking_trips")}

    def booking_trip_rule(self, provider, booking_ref):
        """The current rule for one booking, active or revoked, or None. Read only."""
        self._open_reader()
        if not self._has_table("ota_review_booking_trips"):
            return None
        row = self.conn.execute("SELECT * FROM ota_review_booking_trips WHERE provider=? AND booking_ref=?",
                                (str(provider), str(booking_ref))).fetchone()
        return self._booking_trip_row(row) if row else None

    def booking_trip_history(self, provider, booking_ref):
        """Every revision of one booking's trip assignment, oldest first. Read only."""
        self._open_reader()
        if not self._has_table("ota_review_booking_trip_history"):
            return []
        return [dict(row) for row in self.conn.execute(
            "SELECT revision, trip_tab_id, trip_code, basis, status, user, changed_at "
            "FROM ota_review_booking_trip_history WHERE provider=? AND booking_ref=? ORDER BY revision",
            (str(provider), str(booking_ref)))]

    @staticmethod
    def _booking_trip_row(row):
        return {"provider": row["provider"], "booking_ref": row["booking_ref"],
                "trip_tab_id": row["trip_tab_id"], "trip_code": row["trip_code"],
                "basis": row["basis"], "revision": int(row["revision"]), "status": row["status"],
                "user": row["user"], "changed_at": row["changed_at"]}

    def save_booking_trip(self, *, provider, booking_ref, trip_tab_id, trip_code, basis,
                          expected_revision, user):
        """Assign or revise one booking's trip. The caller names the revision it read."""
        basis = str(basis or "").strip()
        if not basis:
            raise BookingTripError("BASIS_REQUIRED", "배정 근거를 적어 주세요")
        if len(basis) > BOOKING_TRIP_BASIS_LIMIT:
            raise BookingTripError("BASIS_TOO_LONG", "배정 근거가 너무 깁니다")

        def write(conn):
            current = conn.execute("SELECT * FROM ota_review_booking_trips WHERE provider=? AND booking_ref=?",
                                   (str(provider), str(booking_ref))).fetchone()
            return _write_booking_trip(conn, provider, booking_ref, expected_revision, user, "active",
                                       current, trip_tab_id=trip_tab_id, trip_code=trip_code, basis=basis)
        return self._write_booking_trips(write)

    def revoke_booking_trip(self, *, provider, booking_ref, expected_revision, user):
        """Stop applying one booking's trip assignment. The history keeps what was revoked."""
        def write(conn):
            current = conn.execute("SELECT * FROM ota_review_booking_trips WHERE provider=? AND booking_ref=?",
                                   (str(provider), str(booking_ref))).fetchone()
            if current is not None and current["status"] != "active":
                raise BookingTripError("NO_ACTIVE_RULE", "해제할 배정이 없습니다")
            # 규칙이 없으면 기간 배정을 막는 해제 기록만 남긴다. 여행 칸은 비운다.
            return _write_booking_trip(conn, provider, booking_ref, expected_revision, user, "revoked",
                                       current, trip_tab_id=current["trip_tab_id"] if current else "",
                                       trip_code=current["trip_code"] if current else "",
                                       basis=current["basis"] if current else "기간 배정 해제")
        return self._write_booking_trips(write)

    def _write_booking_trips(self, write):
        """Run one write in its own immediate transaction on a fresh connection."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            existing = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if any(not name.startswith("ota_review_") for name in existing):
                raise BookingTripError("REVIEW_DATABASE_NOT_ISOLATED", "검토 자료 경로를 확인해 주세요")
            _create_booking_trip_tables(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = write(conn)
                conn.execute("COMMIT")
                return result
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def proposals(self):
        if not self._has_table("ota_review_proposals"):
            return []
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(ota_review_proposals)")}
        return [{"proposal_id": row["proposal_id"], "event_id": row["event_id"],
                 "transaction_id": row["transaction_id"],
                 "conditions": json.loads(row["conditions_json"]), "status": row["status"],
                 "review_warnings": json.loads(row["review_warning"] or "[]")
                     if "review_warning" in columns else []}
                for row in self.conn.execute("SELECT * FROM ota_review_proposals ORDER BY proposal_id")]

    def group_pins(self):
        """Read frozen ordered mappings without creating or migrating the review DB."""
        if not self._has_table("ota_review_group_pins"):
            return []
        return [{"group_id":row["group_id"], "event_ids":json.loads(row["event_ids_json"]),
                 "card_ids":json.loads(row["card_ids_json"]), "mapping":json.loads(row["mapping_json"]),
                 "confirmed_by":row["confirmed_by"], "version":row["version"],
                 "order_snapshot":json.loads(row["order_snapshot_json"] or "{}")}
                for row in self.conn.execute("SELECT * FROM ota_review_group_pins ORDER BY group_id")]

    def confirm_group_order(self, event_ids, card_ids, mapping, *, user, replace=False,
                            order_snapshot=None, request_id=None):
        event_ids = sorted(set(map(str, event_ids)))
        card_ids = sorted(set(map(str, card_ids)))
        if (not event_ids or not card_ids or len(event_ids) != len(card_ids) or
                set(mapping) != set(event_ids) or set(mapping.values()) != set(card_ids)):
            raise ValueError("INVALID_GROUP_ORDER_MAPPING")
        group_id = "group_" + _digest(event_ids)
        self._ensure_initialized()
        if not request_id or not str(request_id).strip():
            raise ValueError("GROUP_ORDER_REQUEST_ID_REQUIRED")
        request_id = str(request_id).strip()
        request_payload = {"group_id":group_id, "event_ids":event_ids, "card_ids":card_ids,
                           "mapping":mapping, "user":str(user), "replace":bool(replace),
                           "order_snapshot":order_snapshot or {}}
        request_digest = _digest(request_payload)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            prior = self.conn.execute("SELECT request_digest,result_json FROM ota_review_group_requests WHERE request_id=?",
                                      (request_id,)).fetchone()
            if prior:
                if prior[0] != request_digest:
                    raise ValueError("GROUP_ORDER_REQUEST_REPLAY_CONFLICT")
                result = json.loads(prior[1])
                self.conn.commit()
                return result
            current = self.conn.execute("SELECT version FROM ota_review_group_pins WHERE group_id=?",
                                        (group_id,)).fetchone()
            if current and not replace:
                raise ValueError("GROUP_ORDER_ALREADY_FROZEN")
            placeholders = ",".join("?" for _ in card_ids)
            if self._has_table("ota_review_links"):
                paid_rows = self.conn.execute(
                    f"SELECT event_id,transaction_id FROM ota_review_links WHERE transaction_id IN ({placeholders})",
                    tuple(card_ids)).fetchall()
                if any(mapping.get(str(row["event_id"])) != str(row["transaction_id"]) for row in paid_rows):
                    raise ValueError("GROUP_CARD_PAID_LINK_CONFLICT")
            other_pin = self.conn.execute(
                f"SELECT group_id FROM ota_review_group_pins WHERE group_id<>? "
                f"AND EXISTS (SELECT 1 FROM json_each(card_ids_json) WHERE value IN ({placeholders})) LIMIT 1",
                (group_id, *card_ids)).fetchone()
            if other_pin:
                raise ValueError("GROUP_CARD_RESERVED_BY_OTHER_GROUP")
            if self._has_table("ota_review_reservation_links"):
                reservation_owner = self.conn.execute(
                    f"SELECT transaction_id FROM ota_review_reservation_links WHERE transaction_id IN ({placeholders}) LIMIT 1",
                    tuple(card_ids)).fetchone()
                if reservation_owner:
                    raise ValueError("GROUP_CARD_RESERVED_BY_RESERVATION_LINK")
            result = {"status":"frozen", "group_id":group_id, "event_ids":event_ids,
                      "card_ids":card_ids, "mapping":mapping, "order_snapshot":order_snapshot or {},
                      "version":int(current[0])+1 if current else 1}
            if current:
                self.conn.execute("UPDATE ota_review_group_pins SET event_ids_json=?,card_ids_json=?,mapping_json=?,"
                    "confirmed_by=?,confirmed_at=CURRENT_TIMESTAMP,version=version+1,order_snapshot_json=? WHERE group_id=?",
                    (_dump(event_ids), _dump(card_ids), _dump(mapping), str(user), _dump(order_snapshot or {}), group_id))
            else:
                self.conn.execute("INSERT INTO ota_review_group_pins"
                    "(group_id,event_ids_json,card_ids_json,mapping_json,confirmed_by,version,order_snapshot_json)"
                    " VALUES(?,?,?,?,?,1,?)", (group_id,_dump(event_ids),_dump(card_ids),_dump(mapping),
                                                str(user),_dump(order_snapshot or {})))
            self.conn.execute("INSERT INTO ota_review_group_requests(request_id,request_digest,result_json) VALUES(?,?,?)",
                              (request_id,request_digest,_dump(result)))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return result

    def _preview_value(self, event, transaction):
        differences = {}
        for key, left, right in (
            ("amount_krw", event.get("amount_krw"), transaction.get("amount_krw")),
            ("paid_on", event.get("paid_on"), transaction.get("approval_date")),
            ("card_last4", event.get("card_last4"), transaction.get("card_tail")),
            ("direction", event.get("event_type"), transaction.get("transaction_direction")),
        ):
            if left is not None and right is not None and str(left) != str(right):
                differences[key] = {"event": left, "transaction": right}
        value = {"event": event, "transaction": transaction, "differences": differences}
        value["preview_digest"] = _digest(value)
        return value

    def preview(self, event, transaction):
        return self._preview_value(event, transaction)

    def confirm(self, event, transaction, preview_digest, *, request_id, user,
                allocations=_NO_ALLOCATION_SNAPSHOT, id_crosswalk=None):
        if allocations is _NO_ALLOCATION_SNAPSHOT or allocations is None:
            raise ValueError("GLOBAL_ALLOCATIONS_REQUIRED")
        if not isinstance(allocations, (dict, list, tuple)):
            raise ValueError("INVALID_GLOBAL_ALLOCATIONS")
        self._ensure_initialized()
        previous = self.conn.execute("SELECT result_json FROM ota_review_requests WHERE request_id=?",
                                     (request_id,)).fetchone()
        if previous:
            return json.loads(previous[0])
        current = self._preview_value(event, transaction)
        if current["preview_digest"] != preview_digest:
            raise ValueError("STALE_PREVIEW")
        if not _event_is_paid(event) or _event_amount(event) is None:
            raise ValueError("VERIFIED_PAYMENT_REQUIRED")
        if event.get("event_type") == "refund" and event.get("refund_status") not in ("refunded", "refund_completed"):
            raise ValueError("EXPLICIT_REFUND_VERIFICATION_REQUIRED")
        transaction_id = transaction.get("transaction_id")
        event_id = event.get("ota_event_id")
        if not transaction_id or not event_id:
            raise ValueError("STABLE_IDENTITIES_REQUIRED")
        if transaction.get("already_linked_event_id"):
            raise ValueError("CARD_ALREADY_LINKED")
        allocation_conflict = False
        if isinstance(allocations, dict):
            for key, value in allocations.items():
                if key == transaction_id or value == transaction_id:
                    allocation_conflict = True
                if isinstance(value, dict) and value.get("transaction_id") == transaction_id:
                    allocation_conflict = True
        elif allocations:
            allocation_conflict = any(item.get("transaction_id") == transaction_id
                                      for item in allocations if isinstance(item, dict))
        if allocation_conflict:
            raise ValueError("CARD_ALREADY_LINKED")
        conditions, review_warnings = _proposal_conditions(event, transaction)
        proposal_id = "proposal_" + _digest([event_id, transaction_id])
        result = {"status": "MATCHED_USER", "ota_event_id": event_id,
                  "transaction_id": transaction_id, "evidence_changed": False,
                  "proposal_id": proposal_id, "differences": current["differences"],
                  "proposal_conditions": conditions, "proposal_review_warnings": review_warnings}
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            occupied = self.conn.execute(
                "SELECT event_id FROM ota_review_links WHERE transaction_id=?", (transaction_id,)).fetchone()
            if occupied:
                raise ValueError("CARD_ALREADY_LINKED")
            if self._has_table("ota_review_reservation_links"):
                reservation_owner = self.conn.execute(
                    "SELECT event_id FROM ota_review_reservation_links WHERE transaction_id=?",
                    (transaction_id,)).fetchone()
                if reservation_owner:
                    raise ValueError("RESERVATION_CARD_OCCUPIED")
            if self._has_table("ota_review_group_pins"):
                for pin in self.conn.execute("SELECT card_ids_json FROM ota_review_group_pins"):
                    if transaction_id in set(map(str, json.loads(pin[0]))):
                        raise ValueError("CARD_RESERVED_BY_GROUP")
            for old_event_id, current_event_id in (id_crosswalk or {}).items():
                if str(current_event_id) != str(event_id) or not str(old_event_id):
                    continue
                self.conn.execute(
                    "INSERT INTO ota_review_event_crosswalk(old_event_id,current_event_id,evidence_digest) "
                    "VALUES(?,?,?) ON CONFLICT(old_event_id) DO UPDATE SET "
                    "current_event_id=excluded.current_event_id,evidence_digest=excluded.evidence_digest",
                    (str(old_event_id), str(current_event_id), str(event.get("source_digest") or "")))
            self.conn.execute("""INSERT INTO ota_review_links
                (event_id,transaction_id,event_json,transaction_json,source_digest,user)
                VALUES(?,?,?,?,?,?)""", (event_id, transaction_id, _dump(event), _dump(transaction),
                                            event.get("source_digest"), str(user)))
            self.conn.execute("""INSERT OR IGNORE INTO ota_review_proposals
                (proposal_id,event_id,transaction_id,conditions_json,user,review_warning)
                VALUES(?,?,?,?,?,?)""",
                              (proposal_id, event_id, transaction_id, _dump(conditions), str(user),
                               _dump(review_warnings)))
            self.conn.execute("INSERT INTO ota_review_requests(request_id,result_json) VALUES(?,?)",
                              (request_id, _dump(result)))
            self.conn.commit()
            return result
        except BaseException:
            self.conn.rollback()
            raise

    def answer_proposal(self, proposal_id, action, *, user, conditions=None):
        self._ensure_initialized()
        row = self.conn.execute("SELECT * FROM ota_review_proposals WHERE proposal_id=?",
                                (proposal_id,)).fetchone()
        if not row:
            raise ValueError("PROPOSAL_NOT_FOUND")
        if row["status"] != "pending":
            raise ValueError("PROPOSAL_ALREADY_ANSWERED")
        review_warnings = json.loads(row["review_warning"] or "[]")
        if action == "approve" and review_warnings:
            raise ValueError("PROPOSAL_REQUIRES_EDIT")
        proposed = json.loads(row["conditions_json"])
        if action == "once":
            status = "answered_once"
            selected = proposed
        elif action in ("approve", "edit"):
            selected = conditions if conditions is not None else proposed
            if not _narrow(selected):
                raise ValueError("RULE_SCOPE_TOO_BROAD")
            status = "approved" if action == "approve" else "edited"
        else:
            raise ValueError("INVALID_PROPOSAL_ACTION")
        with self.conn:
            self.conn.execute("UPDATE ota_review_proposals SET status=?,answer_json=? WHERE proposal_id=?",
                              (status, _dump({"action": action, "conditions": selected, "user": user}), proposal_id))
            if action == "approve":
                previous = self.conn.execute("SELECT MAX(version) FROM ota_review_rules").fetchone()[0] or 0
                rule_id = "rule_" + _digest([proposal_id, selected])
                self.conn.execute("""INSERT INTO ota_review_rules
                    (rule_id,version,conditions_json,source_event_id,source_transaction_id,
                     approved_by,user_confirmation,active) VALUES(?,?,?,?,?,?,?,1)""",
                                  (rule_id, previous + 1, _dump(selected), row["event_id"],
                                   row["transaction_id"], str(user),
                                   _dump({"proposal_id":proposal_id,"action":"approve","user":str(user)})))
            new_proposal_id = None
            if action == "edit":
                new_proposal_id = "proposal_" + _digest([proposal_id, selected])
                self.conn.execute("""INSERT OR IGNORE INTO ota_review_proposals
                    (proposal_id,event_id,transaction_id,conditions_json,user) VALUES(?,?,?,?,?)""",
                                  (new_proposal_id, row["event_id"], row["transaction_id"],
                                   _dump(selected), str(user)))
        result = {"proposal_id": proposal_id, "action": action, "active": action == "approve",
                  "conditions": selected}
        if action == "edit":
            result["new_proposal_id"] = new_proposal_id
        return result

    def refresh(self, events, transactions, *, changed_transaction_ids=None, changed_event_ids=None):
        changed_transaction_ids = set(changed_transaction_ids or [])
        changed_event_ids = set(changed_event_ids or [])
        event_by_id = {event.get("ota_event_id"): event for event in events}
        stored_links = (self.conn.execute("SELECT * FROM ota_review_links").fetchall()
                        if self._has_table("ota_review_links") else [])
        if any((current := event_by_id.get(row["event_id"])) and
               current.get("source_digest") != row["source_digest"] or
               row["event_id"] not in event_by_id and not row["evidence_missing"]
               for row in stored_links):
            self._ensure_initialized()
            stored_links = self.conn.execute("SELECT * FROM ota_review_links").fetchall()
        for row in stored_links:
            current = event_by_id.get(row["event_id"])
            if current and not _event_is_paid(current):
                with self.conn:
                    self.conn.execute("""UPDATE ota_review_links
                        SET evidence_changed=?,evidence_missing=1 WHERE event_id=?""",
                                      (int(current.get("source_digest") != row["source_digest"] or
                                           row["evidence_changed"]), row["event_id"]))
                continue
            if current and (current.get("source_digest") != row["source_digest"] or row["evidence_missing"]):
                with self.conn:
                    self.conn.execute("""UPDATE ota_review_links
                        SET evidence_changed=?,evidence_missing=0 WHERE event_id=?""",
                                      (int(current.get("source_digest") != row["source_digest"] or row["evidence_changed"]),
                                       row["event_id"]))
            elif not current and not row["evidence_missing"]:
                with self.conn:
                    self.conn.execute("UPDATE ota_review_links SET evidence_missing=1 WHERE event_id=?",
                                      (row["event_id"],))
        pinned = self.links()
        if changed_event_ids or changed_transaction_ids:
            targeted = set(changed_event_ids)
            targeted.update(identity for identity, link in pinned.items()
                            if link["transaction_id"] in changed_transaction_ids)
            changed_rows = [row for row in transactions
                            if row.get("transaction_id") in changed_transaction_ids]
            rules = self.active_rules()
            for event in events:
                if event.get("ota_event_id") in targeted or not _event_is_paid(event):
                    continue
                expected_direction = "refund" if event.get("event_type") == "refund" else "purchase"
                for row in changed_rows:
                    if _direction(row) != expected_direction:
                        continue
                    exact_date = row.get("approval_date") == event.get("paid_on")
                    if ((exact_date or _approved_lag_match(event, row, rules)) and
                            _has_corroborator(event, row, rules)):
                        targeted.add(event.get("ota_event_id"))
                        break
            selected = [event for event in events if event.get("ota_event_id") in targeted]
        else:
            selected = list(events)
        selected_ids = {event.get("ota_event_id") for event in selected}
        for row in self.conn.execute("SELECT * FROM ota_review_links").fetchall() if self._has_table("ota_review_links") else []:
            current = event_by_id.get(row["event_id"])
            unusable_current = current is not None and not _event_is_paid(current)
            missing = row["event_id"] not in event_by_id or unusable_current
            if missing:
                if unusable_current and row["event_id"] in selected_ids:
                    selected = [event for event in selected
                                if event.get("ota_event_id") != row["event_id"]]
                    selected_ids.discard(row["event_id"])
            if missing and row["event_id"] not in selected_ids:
                snapshot = json.loads(row["event_json"])
                snapshot["_evidence_missing"] = True
                selected.append(snapshot)
                selected_ids.add(row["event_id"])
        result = match_ota_payment_events(selected, transactions, existing_links=pinned,
                                          rules=self.active_rules())
        for item in result:
            link = pinned.get(item.get("ota_event_id"))
            if link:
                item["evidence_changed"] = link["evidence_changed"]
                item["evidence_missing"] = link["evidence_missing"]
                item["review_warning"] = ("evidence_missing" if link["evidence_missing"] else
                                           "evidence_changed" if link["evidence_changed"] else None)
        return result
