#!/usr/bin/env python3
"""Build a private Agoda amount-reconciliation candidate database.

The input detail DB is a sealed, converged Agoda portal census.  Exact amount
creates candidate edges.  A relation is confirmed only by the closed graph
rules in :mod:`tools.agoda_amount_candidate_graph`; equal N:N populations are
preserved as unordered groups and never expanded into invented pairs.

This is relation evidence only.  It does not create classification decisions,
allocations, journals, postings, or reversal inheritance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from tools.agoda_amount_candidate_graph import (
    PaymentAmount,
    ReservationAmount,
    resolve_candidate_graph,
)
from tools.agoda_card_payment_confirmation import (
    _canonical,
    _connect_immutable,
    _integrity,
    _publish_noreplace,
    _sha_path,
    _table_exists,
    _unlink_if_owned,
)


RULE_ID = "agoda-portal-amount-closed-graph-v2"
ARTIFACT_TYPE = "agoda-amount-reconciliation-candidate-v2"
GENERIC_LINK_STATUS = "proposed"
TARGET_SCOPE = "target_2026_overlap"
CURRENCY_SCALES = {"JPY": 0, "KRW": 0, "TWD": 0, "VND": 0}
NO_PRICE_OBSERVATION_KIND = "price_evidence_not_displayed"
STATUS_CONFLICT_OBSERVATION_KIND = (
    "cancelled_list_detail_status_conflict_no_price"
)
TERMINAL_SOURCE_RESERVATION_STATUSES = frozenset({"Cancelled", "unknown"})


class ReconciliationError(RuntimeError):
    pass


def _terminal_kind_matches_detail_status(kind: object, status: object) -> bool:
    return (
        str(kind) == NO_PRICE_OBSERVATION_KIND
        and str(status) in {"cancelled", "unknown"}
    ) or (
        str(kind) == STATUS_CONFLICT_OBSERVATION_KIND
        and str(status) in {"confirmed", "completed"}
    )


@dataclass(frozen=True)
class ReservationEvidence:
    node: ReservationAmount
    booking_id: str
    booking_id_sha256: str
    booking_pseudonym_hmac: str
    service_start_on: str
    service_end_on: str
    source_scope_status: str
    detail_scope_status: str
    evidence_kind: str
    semantic_detail_sha256: str


@dataclass(frozen=True)
class PaymentEvidence:
    node: PaymentAmount
    payment_id: int
    occurred_on: str
    direct_event_key_sha256: str
    source_sha256: str


def _sha_text(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _sha_json(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _capture_membership_sha256(value: object) -> str:
    """Match the detail capture's canonical JSON hash (without a newline)."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _require_private_sqlite(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or (
        os.name != "nt" and _mode(path) != 0o600
    ):
        raise ReconciliationError("private_sqlite_contract_invalid")
    if any(os.path.lexists(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        raise ReconciliationError("sqlite_sidecar_present")


def _scalar(payload: dict[str, object], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            return re.sub(r"\s+", " ", str(value)).strip()
    return ""


def _card4(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if len(digits) >= 4 else None


def _foreign_minor_units(value: object, currency: str) -> int | None:
    raw = re.sub(r"[\s,]", "", str(value or ""))
    if not raw:
        return None
    try:
        decimal_value = Decimal(raw)
    except InvalidOperation:
        return None
    scale = CURRENCY_SCALES.get(currency.upper(), 2)
    scaled = decimal_value * (10**scale)
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        return None
    return int(scaled)


def _detail_snapshot(path: Path) -> dict[str, object]:
    _require_private_sqlite(path)
    before = _sha_path(path)
    db = _connect_immutable(path)
    try:
        _integrity(db)
        db.row_factory = sqlite3.Row
        required = {
            "sealed_manifest",
            "capture_run_manifest",
            "booking_detail_snapshots",
            "price_components",
            "payment_events",
        }
        tables = {
            str(row[0])
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not required <= tables:
            raise ReconciliationError("detail_database_schema_incomplete")
        sealed_rows = db.execute("SELECT * FROM sealed_manifest").fetchall()
        run_rows = db.execute("SELECT * FROM capture_run_manifest").fetchall()
        if len(sealed_rows) != 1 or len(run_rows) != 1:
            raise ReconciliationError("detail_manifest_cardinality_invalid")
        sealed, run = sealed_rows[0], run_rows[0]
        run_id = str(sealed["run_id"])
        sealed_keys = set(sealed.keys())
        capture_scope = (
            str(sealed["capture_scope"])
            if "capture_scope" in sealed_keys
            else "source_selected"
        )
        expected_booking_count = (
            int(run["target_2026_count"])
            if capture_scope == "target_2026_overlap"
            else int(run["target_count"])
        )
        if (
            run_id != str(run["run_id"])
            or str(run["epoch_status"]) != "complete"
            or not run["final_revalidation_sha256"]
            or int(sealed["booking_count"]) != expected_booking_count
            or int(sealed["target_2026_count"]) != int(run["target_2026_count"])
            or int(sealed["competitor_count"]) != int(run["competitor_count"])
        ):
            raise ReconciliationError("detail_manifest_not_complete_or_bound")
        terminal_no_price_count = (
            int(sealed["terminal_no_price_count"])
            if "terminal_no_price_count" in sealed_keys
            else 0
        )
        amount_universe_sealed = (
            bool(int(sealed["amount_universe_sealed"]))
            if "amount_universe_sealed" in sealed_keys
            else terminal_no_price_count == 0
        )
        has_observation_table = "booking_detail_observations" in tables
        observations = (
            db.execute(
                "SELECT * FROM booking_detail_observations "
                "WHERE run_id=? ORDER BY booking_id_sha256",
                (run_id,),
            ).fetchall()
            if has_observation_table
            else []
        )
        if len(observations) != terminal_no_price_count:
            raise ReconciliationError("detail_terminal_observation_count_invalid")
        if amount_universe_sealed != (terminal_no_price_count == 0):
            raise ReconciliationError("detail_amount_universe_flag_invalid")
        if observations:
            if not {"page_attestations", "page_attestation_members"} <= tables:
                raise ReconciliationError("detail_terminal_attestation_table_missing")
            if (
                "source_capture_set_sha256" not in set(run.keys())
                or not str(run["source_capture_set_sha256"])
            ):
                raise ReconciliationError("detail_source_manifest_binding_missing")
            observation_columns = {
                str(row[1])
                for row in db.execute(
                    "PRAGMA table_info(booking_detail_observations)"
                )
            }
            required_observation_columns = {
                "run_id",
                "booking_id_sha256",
                "booking_pseudonym_hmac",
                "tab_name",
                "page_no",
                "list_card_sha256",
                "list_attestation_id",
                "attested_ordered_membership_sha256",
                "attested_set_membership_sha256",
                "attested_source_page_set_sha256",
                "source_service_start_on",
                "source_service_end_on",
                "source_reservation_status",
                "detail_service_start_on",
                "detail_service_end_on",
                "reservation_status",
                "detail_reservation_status",
                "observation_kind",
                "payment_information_present",
                "gross_total_present",
                "visible_money_value_count",
                "amount_matching_eligible",
                "unresolved_competitor",
                "semantic_detail_sha256",
            }
            if not required_observation_columns <= observation_columns:
                raise ReconciliationError(
                    "detail_terminal_observation_schema_incomplete"
                )
        snapshots = db.execute(
            "SELECT * FROM booking_detail_snapshots WHERE run_id=? ORDER BY booking_id_sha256",
            (run_id,),
        ).fetchall()
        snapshot_hashes = {str(row["booking_id_sha256"]) for row in snapshots}
        observation_hashes = {
            str(row["booking_id_sha256"]) for row in observations
        }
        if (
            len(snapshots) + len(observations) != int(sealed["booking_count"])
            or len(snapshot_hashes) != len(snapshots)
            or len(observation_hashes) != len(observations)
            or snapshot_hashes & observation_hashes
        ):
            raise ReconciliationError("detail_booking_population_invalid")
        if "price_snapshot_count" in sealed_keys and int(
            sealed["price_snapshot_count"]
        ) != len(snapshots):
            raise ReconciliationError("detail_price_snapshot_count_invalid")
        for row in observations:
            source_start = row["source_service_start_on"]
            source_end = row["source_service_end_on"]
            detail_start = row["detail_service_start_on"]
            detail_end = row["detail_service_end_on"]
            if (
                str(row["run_id"]) != run_id
                or str(row["tab_name"]) != "Cancelled"
                or str(row["source_reservation_status"])
                not in TERMINAL_SOURCE_RESERVATION_STATUSES
                or str(row["reservation_status"]) != "cancelled"
                or not _terminal_kind_matches_detail_status(
                    row["observation_kind"],
                    row["detail_reservation_status"],
                )
                or not source_start
                or not source_end
                or source_start != detail_start
                or source_end != detail_end
                or int(row["gross_total_present"]) != 0
                or int(row["payment_information_present"]) not in {0, 1}
                or int(row["visible_money_value_count"]) != 0
                or int(row["amount_matching_eligible"]) != 0
                or int(row["unresolved_competitor"]) != 1
                or row["list_attestation_id"] is None
                or not str(row["list_card_sha256"])
                or not str(row["attested_ordered_membership_sha256"])
                or not str(row["attested_set_membership_sha256"])
                or not str(row["attested_source_page_set_sha256"])
                or str(row["attested_source_page_set_sha256"])
                != str(run["source_capture_set_sha256"])
                or not str(row["semantic_detail_sha256"])
            ):
                raise ReconciliationError(
                    "detail_terminal_observation_contract_invalid"
                )
            attestation = db.execute(
                """
                SELECT 1 FROM page_attestations
                WHERE attestation_id=? AND run_id=? AND tab_name=? AND page_no=?
                  AND phase='before_click'
                  AND expected_selected_page=? AND observed_selected_page=?
                  AND ordered_membership_sha256=?
                  AND set_membership_sha256=?
                  AND source_page_set_sha256=?
                """,
                (
                    int(row["list_attestation_id"]),
                    run_id,
                    row["tab_name"],
                    int(row["page_no"]),
                    int(row["page_no"]),
                    int(row["page_no"]),
                    str(row["attested_ordered_membership_sha256"]),
                    str(row["attested_set_membership_sha256"]),
                    str(row["attested_source_page_set_sha256"]),
                ),
            ).fetchone()
            if attestation is None:
                raise ReconciliationError(
                    "detail_terminal_observation_attestation_invalid"
                )
            members = db.execute(
                """
                SELECT ordinal, booking_pseudonym_hmac, list_card_sha256
                FROM page_attestation_members
                WHERE attestation_id=?
                ORDER BY ordinal
                """,
                (int(row["list_attestation_id"]),),
            ).fetchall()
            ordinals = [int(member["ordinal"]) for member in members]
            pseudonyms = [
                str(member["booking_pseudonym_hmac"]) for member in members
            ]
            if (
                not members
                or ordinals != list(range(1, len(members) + 1))
                or len(pseudonyms) != len(set(pseudonyms))
                or _capture_membership_sha256(pseudonyms)
                != str(row["attested_ordered_membership_sha256"])
                or _capture_membership_sha256(sorted(pseudonyms))
                != str(row["attested_set_membership_sha256"])
                or not any(
                    str(member["booking_pseudonym_hmac"])
                    == str(row["booking_pseudonym_hmac"])
                    and str(member["list_card_sha256"])
                    == str(row["list_card_sha256"])
                    for member in members
                )
            ):
                raise ReconciliationError(
                    "detail_terminal_observation_list_membership_invalid"
                )

        evidence: list[ReservationEvidence] = []
        evidence_kind_counts: Counter[str] = Counter()
        for snapshot in snapshots:
            snapshot_id = int(snapshot["snapshot_id"])
            components = db.execute(
                "SELECT * FROM price_components WHERE snapshot_id=? ORDER BY ordinal",
                (snapshot_id,),
            ).fetchall()
            events = db.execute(
                "SELECT * FROM payment_events WHERE snapshot_id=? ORDER BY event_id",
                (snapshot_id,),
            ).fetchall()
            gross = [row for row in components if row["component_kind"] == "gross_total"]
            paid = [row for row in components if row["component_kind"] == "paid_today"]
            if len(gross) != 1 or len(paid) > 1:
                raise ReconciliationError("detail_price_cardinality_invalid")
            card4 = _card4(snapshot["card4"])
            target = (
                str(snapshot["detail_scope_status"]) == TARGET_SCOPE
                and str(snapshot["source_scope_status"]) in {TARGET_SCOPE, "year_unknown"}
            )
            lifecycle_clear = (
                str(snapshot["reservation_status"]) != "cancelled"
                and str(snapshot["refund_status"]) == "none_displayed"
            )
            collection = str(snapshot["collection_model"])
            explicit = [
                row
                for row in events
                if row["event_kind"] in {"charge", "refund", "chargeback"}
                and int(row["amount_minor_units"]) != 0
            ]
            selected: list[tuple[sqlite3.Row, str, bool]] = []
            if explicit:
                selected.extend((row, "explicit_event", True) for row in explicit)
            elif (
                paid
                and int(paid[0]["amount_minor_units"]) != 0
                and collection in {"agoda_collect", "hybrid"}
            ):
                selected.append((paid[0], "paid_today", True))
            elif paid and int(paid[0]["amount_minor_units"]) == 0:
                selected.append((gross[0], "noncard_settlement_no_charge", False))
            elif collection != "property_collect":
                selected.append((gross[0], "gross_competitor_only", False))
            else:
                selected.append((gross[0], "property_collect_noncompeting", False))

            for ordinal, (amount_row, evidence_kind, actual_charge) in enumerate(selected, 1):
                event_kind = (
                    str(amount_row["event_kind"])
                    if "event_kind" in amount_row.keys()
                    else "charge"
                )
                amount = int(amount_row["amount_minor_units"])
                competes = evidence_kind not in {
                    "property_collect_noncompeting",
                    "noncard_settlement_no_charge",
                }
                promotion_eligible = bool(target and lifecycle_clear and actual_charge)
                hold_reason = None
                if not competes:
                    hold_reason = (
                        "noncard_settlement_has_no_card_charge"
                        if evidence_kind == "noncard_settlement_no_charge"
                        else "property_collect_has_no_agoda_charge"
                    )
                elif not target:
                    hold_reason = "competition_only_outside_2026"
                elif not lifecycle_clear:
                    hold_reason = "reservation_lifecycle_not_clear"
                elif not actual_charge:
                    hold_reason = "gross_total_is_not_charge_event"
                node_key = "r:" + _sha_json(
                    {
                        "booking": str(snapshot["booking_id_sha256"]),
                        "event_kind": event_kind,
                        "currency": str(amount_row["currency"]),
                        "amount": amount,
                        "evidence_kind": evidence_kind,
                        "ordinal": ordinal,
                    }
                )
                node = ReservationAmount(
                    key=node_key,
                    currency=str(amount_row["currency"]),
                    amount_minor_units=amount,
                    event_kind=event_kind,
                    card4=card4 if collection in {"agoda_collect", "hybrid"} else None,
                    competes_for_payment=competes,
                    promotion_eligible=promotion_eligible,
                    hold_reason=hold_reason,
                )
                evidence_kind_counts[evidence_kind] += 1
                evidence.append(
                    ReservationEvidence(
                        node=node,
                        booking_id=str(snapshot["booking_id"]),
                        booking_id_sha256=str(snapshot["booking_id_sha256"]),
                        booking_pseudonym_hmac=str(snapshot["booking_pseudonym_hmac"]),
                        service_start_on=str(snapshot["detail_service_start_on"]),
                        service_end_on=str(snapshot["detail_service_end_on"]),
                        source_scope_status=str(snapshot["source_scope_status"]),
                        detail_scope_status=str(snapshot["detail_scope_status"]),
                        evidence_kind=evidence_kind,
                        semantic_detail_sha256=str(snapshot["semantic_detail_sha256"]),
                    )
                )
        return {
            "path": path,
            "sha256": before,
            "run_id": run_id,
            "capture_scope": capture_scope,
            "membership_set_sha256": str(sealed["membership_set_sha256"]),
            "policy_sha256": str(sealed["policy_sha256"]),
            "booking_count": int(sealed["booking_count"]),
            "target_2026_count": int(sealed["target_2026_count"]),
            "competitor_count": int(sealed["competitor_count"]),
            "price_snapshot_count": len(snapshots),
            "terminal_no_price_count": terminal_no_price_count,
            "amount_universe_sealed": amount_universe_sealed,
            "evidence": tuple(evidence),
            "evidence_kind_counts": dict(sorted(evidence_kind_counts.items())),
        }
    finally:
        db.close()
        if _sha_path(path) != before:
            raise ReconciliationError("detail_database_changed_during_read")


def _current_card_snapshot(path: Path) -> dict[str, object]:
    before = _sha_path(path)
    db = _connect_immutable(path)
    try:
        _integrity(db)
        db.row_factory = sqlite3.Row
        projection = db.execute(
            "SELECT run_id,status FROM direct_projection_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if projection is None:
            raise ReconciliationError("base_projection_run_missing")
        run_id = str(projection["run_id"])
        rows = db.execute(
            """SELECT e.direct_event_key,e.source_sha256,p.id AS payment_id,
                      p.occurred_on,p.transaction_type,p.amount_krw,p.merchant,
                      p.currency,p.foreign_amount,
                      s.payload_json
                 FROM direct_promotion_evidence e
                 JOIN direct_normalized_payments d
                   ON e.direct_event_key=d.card_event_id || '#' || d.event_role
                 JOIN direct_payment_projection_links l
                   ON l.run_id=e.run_id AND l.direct_payment_id=d.id
                 JOIN payment_transactions p ON p.id=l.payment_id
                 JOIN direct_source_records s
                   ON s.id=d.source_record_id AND s.source_kind=e.source_kind
                  AND s.source_key=e.source_key AND s.source_sha256=e.source_sha256
                WHERE e.run_id=? AND e.evidence_kind='current_card'
                  AND e.authority_status='current_raw' AND e.source_kind='card_raw'
                ORDER BY p.id""",
            (run_id,),
        ).fetchall()
        seen_payment_ids: set[int] = set()
        all_card_coverage: dict[str, str] = {}
        all_current_dates: list[str] = []
        payments: list[PaymentEvidence] = []
        settlement_payment_ids = (
            {
                int(item[0])
                for item in db.execute(
                    "SELECT DISTINCT payment_id FROM direct_cancellation_settlement_members"
                )
            }
            if _table_exists(db, "direct_cancellation_settlement_members")
            else set()
        )
        for row in rows:
            payment_id = int(row["payment_id"])
            if payment_id in seen_payment_ids:
                raise ReconciliationError("current_card_payment_not_unique")
            seen_payment_ids.add(payment_id)
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ReconciliationError("current_card_payload_invalid") from exc
            if not isinstance(payload, dict):
                raise ReconciliationError("current_card_payload_invalid")
            card4 = _card4(_scalar(payload, "card4", "card_last4", "last4"))
            occurred_on = str(row["occurred_on"])
            all_current_dates.append(occurred_on)
            if card4:
                all_card_coverage[card4] = max(all_card_coverage.get(card4, ""), occurred_on)
            if "agoda" not in str(row["merchant"] or "").casefold():
                continue
            transaction_type = str(row["transaction_type"]).casefold()
            if transaction_type == "purchase" and int(row["amount_krw"]) > 0:
                event_kind = "charge"
            elif transaction_type in {"cancellation", "refund"}:
                event_kind = "refund"
            else:
                continue
            currency = (
                _scalar(payload, "currency", "foreign_currency")
                or str(row["currency"] or "")
            ).upper()
            foreign_amount = _foreign_minor_units(
                _scalar(payload, "foreign_amount", "foreign", "local_amount")
                or row["foreign_amount"],
                currency,
            )
            if currency and currency != "KRW" and foreign_amount:
                amount = abs(foreign_amount)
            else:
                currency = "KRW"
                amount = abs(int(row["amount_krw"]))
            if amount == 0:
                continue
            existing_link = db.execute(
                "SELECT COUNT(*) FROM payment_booking_links WHERE payment_id=? "
                "AND link_status IN ('legacy','proposed','confirmed')",
                (payment_id,),
            ).fetchone()[0]
            lifecycle_conflict = payment_id in settlement_payment_ids
            hold_reason = None
            if existing_link:
                hold_reason = "existing_booking_link_conflict"
            elif lifecycle_conflict:
                hold_reason = "cancellation_settlement_requires_lifecycle_authority"
            node = PaymentAmount(
                key=f"p:{payment_id}",
                currency=currency,
                amount_minor_units=amount,
                event_kind=event_kind,
                card4=card4,
                promotion_eligible=int(existing_link) == 0 and not lifecycle_conflict,
                hold_reason=hold_reason,
            )
            payments.append(
                PaymentEvidence(
                    node=node,
                    payment_id=payment_id,
                    occurred_on=occurred_on,
                    direct_event_key_sha256=_sha_text(row["direct_event_key"]),
                    source_sha256=str(row["source_sha256"]),
                )
            )
        if not all_card_coverage:
            raise ReconciliationError("card_coverage_missing")
        if not all_current_dates:
            raise ReconciliationError("current_card_event_dates_missing")
        coverage_end = max(all_current_dates)
        return {
            "sha256": before,
            "run_id": run_id,
            "projection_status": str(projection["status"]),
            "payments": tuple(payments),
            "current_card_count": len(rows),
            "agoda_payment_count": len(payments),
            "coverage_end": coverage_end,
            "coverage_card_count": len(all_card_coverage),
        }
    finally:
        db.close()
        if _sha_path(path) != before:
            raise ReconciliationError("base_database_changed_during_read")


def _apply_card_coverage(
    evidence: Iterable[ReservationEvidence],
    coverage_end: str,
) -> tuple[ReservationEvidence, ...]:
    result: list[ReservationEvidence] = []
    coverage_date = date.fromisoformat(coverage_end)
    for item in evidence:
        node = item.node
        if node.promotion_eligible and date.fromisoformat(item.service_end_on) > coverage_date:
            node = replace(
                node,
                promotion_eligible=False,
                hold_reason="card_source_coverage_ends_before_service_end",
            )
        result.append(replace(item, node=node))
    return tuple(result)


def _side_effect_counts(db: sqlite3.Connection) -> dict[str, int]:
    def count(table: str) -> int:
        return (
            int(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            if _table_exists(db, table)
            else 0
        )

    return {
        "payment": count("payment_transactions"),
        "decision": count("classification_decisions"),
        "allocation_plan": count("allocation_plans"),
        "cost_allocation": count("cost_allocations"),
        "journal": count("journal_entries"),
        "posting_batch": count("direct_accounting_posting_batches"),
        "posting_line": count("direct_accounting_posting_lines"),
        "reversal_inheritance": count("direct_high_coverage_reversal_inheritance"),
    }


def _create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE direct_agoda_amount_candidate_edges(
          reconciliation_run_id TEXT NOT NULL,
          reservation_node_key TEXT NOT NULL,
          payment_node_key TEXT NOT NULL,
          booking_id_sha256 TEXT NOT NULL CHECK(length(booking_id_sha256)=64),
          payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
          event_kind TEXT NOT NULL,
          currency TEXT NOT NULL,
          amount_minor_units INTEGER NOT NULL,
          match_method TEXT NOT NULL,
          edge_sha256 TEXT NOT NULL CHECK(length(edge_sha256)=64),
          PRIMARY KEY(reconciliation_run_id,reservation_node_key,payment_node_key)
        );
        CREATE TABLE direct_agoda_amount_individual_authorities(
          authority_id TEXT PRIMARY KEY,
          reconciliation_run_id TEXT NOT NULL,
          reservation_node_key TEXT NOT NULL UNIQUE,
          payment_node_key TEXT NOT NULL UNIQUE,
          payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
          booking_id_sha256 TEXT NOT NULL CHECK(length(booking_id_sha256)=64),
          event_kind TEXT NOT NULL,
          currency TEXT NOT NULL,
          amount_minor_units INTEGER NOT NULL,
          evidence_tier TEXT NOT NULL,
          relation_status TEXT NOT NULL CHECK(relation_status='confirmed'),
          generic_link_status TEXT NOT NULL CHECK(generic_link_status='proposed'),
          accounting_side_effects INTEGER NOT NULL CHECK(accounting_side_effects=0),
          authority_sha256 TEXT NOT NULL CHECK(length(authority_sha256)=64),
          payload_json TEXT NOT NULL
        );
        CREATE TABLE direct_agoda_amount_group_authorities(
          group_id TEXT PRIMARY KEY,
          reconciliation_run_id TEXT NOT NULL,
          event_kind TEXT NOT NULL,
          currency TEXT NOT NULL,
          amount_minor_units INTEGER NOT NULL,
          member_count_each_side INTEGER NOT NULL CHECK(member_count_each_side>1),
          individual_pair_asserted INTEGER NOT NULL CHECK(individual_pair_asserted=0),
          relation_status TEXT NOT NULL CHECK(relation_status='confirmed_group'),
          member_set_sha256 TEXT NOT NULL CHECK(length(member_set_sha256)=64),
          authority_sha256 TEXT NOT NULL CHECK(length(authority_sha256)=64),
          payload_json TEXT NOT NULL
        );
        CREATE TABLE direct_agoda_amount_group_members(
          group_id TEXT NOT NULL REFERENCES direct_agoda_amount_group_authorities(group_id),
          member_side TEXT NOT NULL CHECK(member_side IN ('reservation','payment')),
          member_key TEXT NOT NULL,
          booking_id INTEGER REFERENCES bookings(id),
          booking_id_sha256 TEXT,
          payment_id INTEGER REFERENCES payment_transactions(id),
          member_sha256 TEXT NOT NULL CHECK(length(member_sha256)=64),
          PRIMARY KEY(group_id,member_side,member_key),
          CHECK(
            (member_side='reservation' AND booking_id IS NOT NULL AND payment_id IS NULL)
            OR (member_side='payment' AND booking_id IS NULL AND payment_id IS NOT NULL)
          )
        );
        CREATE TABLE direct_agoda_amount_withheld(
          reconciliation_run_id TEXT NOT NULL,
          withheld_id TEXT NOT NULL,
          reason_code TEXT NOT NULL,
          event_kind TEXT,
          currency TEXT,
          amount_minor_units INTEGER,
          reservation_count INTEGER,
          payment_count INTEGER,
          detail_sha256 TEXT NOT NULL CHECK(length(detail_sha256)=64),
          PRIMARY KEY(reconciliation_run_id,withheld_id)
        );
        CREATE TABLE direct_agoda_amount_reconciliation_manifests(
          reconciliation_run_id TEXT PRIMARY KEY,
          artifact_type TEXT NOT NULL,
          rule_id TEXT NOT NULL,
          base_db_sha256 TEXT NOT NULL CHECK(length(base_db_sha256)=64),
          detail_db_sha256 TEXT NOT NULL CHECK(length(detail_db_sha256)=64),
          base_projection_run_id TEXT NOT NULL,
          detail_run_id TEXT NOT NULL,
          detail_booking_count INTEGER NOT NULL,
          target_2026_count INTEGER NOT NULL,
          competitor_count INTEGER NOT NULL,
          card_coverage_end TEXT NOT NULL,
          amount_candidate_edge_count INTEGER NOT NULL,
          confirmed_individual_count INTEGER NOT NULL,
          confirmed_group_count INTEGER NOT NULL,
          confirmed_group_member_count INTEGER NOT NULL,
          withheld_count INTEGER NOT NULL,
          individual_pair_asserted_for_groups INTEGER NOT NULL CHECK(individual_pair_asserted_for_groups=0),
          accounting_side_effects INTEGER NOT NULL CHECK(accounting_side_effects=0),
          membership_sha256 TEXT NOT NULL CHECK(length(membership_sha256)=64),
          policy_sha256 TEXT NOT NULL CHECK(length(policy_sha256)=64),
          report_sha256 TEXT NOT NULL CHECK(length(report_sha256)=64),
          publication_status TEXT NOT NULL CHECK(publication_status='private_candidate_only'),
          payload_json TEXT NOT NULL
        );
        """
    )


def _ensure_booking(
    db: sqlite3.Connection,
    item: ReservationEvidence,
    source_document_id: int,
) -> int:
    db.execute(
        """INSERT OR IGNORE INTO bookings(
               provider,booking_number,product_type,label,
               service_start_on,service_end_on,status
             ) VALUES ('agoda',?,'lodging','Agoda 포털예약',?,?,?)""",
        (
            item.booking_id,
            item.service_start_on,
            item.service_end_on,
            "confirmed" if item.detail_scope_status == TARGET_SCOPE else "unknown",
        ),
    )
    booking_id = int(
        db.execute(
            "SELECT id FROM bookings WHERE provider='agoda' AND booking_number=?",
            (item.booking_id,),
        ).fetchone()[0]
    )
    db.execute(
        """INSERT OR IGNORE INTO booking_identifiers(
               booking_id,provider,identifier,identifier_type,
               identifier_status,rule_id,first_seen_document_id,last_seen_document_id
             ) VALUES (?,'agoda',?,'booking_number','confirmed',?,?,?)""",
        (booking_id, item.booking_id, RULE_ID, source_document_id, source_document_id),
    )
    return booking_id


def _insert_results(
    db: sqlite3.Connection,
    *,
    reconciliation_run_id: str,
    detail: dict[str, object],
    cards: dict[str, object],
    reservation_evidence: tuple[ReservationEvidence, ...],
    payment_evidence: tuple[PaymentEvidence, ...],
    graph: dict[str, object],
    policy_sha256: str,
    report_sha256: str,
) -> dict[str, int]:
    reservation_by_key = {item.node.key: item for item in reservation_evidence}
    payment_by_key = {item.node.key: item for item in payment_evidence}
    db.execute(
        "INSERT OR IGNORE INTO source_documents(source_kind,path,sha256) VALUES (?,?,?)",
        ("agoda_portal_detail_sealed", str(detail["path"]), str(detail["sha256"])),
    )
    source_document_id = int(
        db.execute(
            "SELECT id FROM source_documents WHERE source_kind=? AND path=? AND sha256=?",
            ("agoda_portal_detail_sealed", str(detail["path"]), str(detail["sha256"])),
        ).fetchone()[0]
    )

    for edge in graph["amount_candidates"]:
        reservation = reservation_by_key[str(edge["reservation_key"])]
        payment = payment_by_key[str(edge["payment_key"])]
        signature = tuple(edge["signature"])
        edge_payload = {
            "reservation_node_key": reservation.node.key,
            "payment_node_key": payment.node.key,
            "signature": signature,
            "match_method": edge["match_method"],
        }
        db.execute(
            "INSERT INTO direct_agoda_amount_candidate_edges VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                reconciliation_run_id,
                reservation.node.key,
                payment.node.key,
                reservation.booking_id_sha256,
                payment.payment_id,
                signature[0],
                signature[1],
                signature[2],
                str(edge["match_method"]),
                _sha_json(edge_payload),
            ),
        )

    individual_count = 0
    for relation in graph["confirmed_individuals"]:
        reservation = reservation_by_key[str(relation["reservation_key"])]
        payment = payment_by_key[str(relation["payment_key"])]
        if not reservation.node.promotion_eligible or not payment.node.promotion_eligible:
            raise ReconciliationError("graph_promoted_ineligible_individual")
        booking_id = _ensure_booking(db, reservation, source_document_id)
        relation_type = "pays_for" if reservation.node.event_kind == "charge" else "refunds_for"
        db.execute(
            """INSERT INTO payment_booking_links(
                   payment_id,booking_id,relation_type,confidence,link_status,
                   first_seen_document_id,last_seen_document_id
                 ) VALUES (?,?,?,?,?,?,?)""",
            (
                payment.payment_id,
                booking_id,
                relation_type,
                1.0,
                GENERIC_LINK_STATUS,
                source_document_id,
                source_document_id,
            ),
        )
        payload = {
            "booking_id_sha256": reservation.booking_id_sha256,
            "booking_pseudonym_hmac": reservation.booking_pseudonym_hmac,
            "payment_id": payment.payment_id,
            "evidence_kind": reservation.evidence_kind,
            "evidence_tier": relation["tier"],
            "semantic_detail_sha256": reservation.semantic_detail_sha256,
            "direct_event_key_sha256": payment.direct_event_key_sha256,
            "source_sha256": payment.source_sha256,
        }
        authority_id = _sha_json(
            {"rule_id": RULE_ID, "run": reconciliation_run_id, **payload}
        )
        db.execute(
            """INSERT INTO direct_agoda_amount_individual_authorities VALUES (
                   ?,?,?,?,?,?,?,?,?,?,?,'confirmed','proposed',0,?,?
                 )""",
            (
                authority_id,
                reconciliation_run_id,
                reservation.node.key,
                payment.node.key,
                payment.payment_id,
                booking_id,
                reservation.booking_id_sha256,
                reservation.node.event_kind,
                reservation.node.currency.upper(),
                abs(reservation.node.amount_minor_units),
                str(relation["tier"]),
                _sha_json(payload),
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        individual_count += 1

    group_count = 0
    group_member_count = 0
    for group in graph["confirmed_groups"]:
        signature = tuple(group["signature"])
        member_payload = {
            "reservations": tuple(group["reservation_keys"]),
            "payments": tuple(group["payment_keys"]),
        }
        member_set_sha256 = _sha_json(member_payload)
        authority_payload = {
            "rule_id": RULE_ID,
            "group_id": group["group_id"],
            "signature": signature,
            "member_set_sha256": member_set_sha256,
            "individual_pair_asserted": False,
        }
        db.execute(
            """INSERT INTO direct_agoda_amount_group_authorities VALUES (
                   ?,?,?,?,?,?,0,'confirmed_group',?,?,?
                 )""",
            (
                str(group["group_id"]),
                reconciliation_run_id,
                signature[0],
                signature[1],
                signature[2],
                int(group["member_count_each_side"]),
                member_set_sha256,
                _sha_json(authority_payload),
                json.dumps(authority_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
        for reservation_key in group["reservation_keys"]:
            reservation = reservation_by_key[str(reservation_key)]
            if not reservation.node.promotion_eligible:
                raise ReconciliationError("graph_promoted_ineligible_group_reservation")
            booking_id = _ensure_booking(db, reservation, source_document_id)
            member = {
                "group_id": group["group_id"],
                "side": "reservation",
                "key": reservation.node.key,
                "booking_id_sha256": reservation.booking_id_sha256,
            }
            db.execute(
                "INSERT INTO direct_agoda_amount_group_members VALUES (?,?,?,?,?,?,?)",
                (
                    str(group["group_id"]),
                    "reservation",
                    reservation.node.key,
                    booking_id,
                    reservation.booking_id_sha256,
                    None,
                    _sha_json(member),
                ),
            )
            group_member_count += 1
        for payment_key in group["payment_keys"]:
            payment = payment_by_key[str(payment_key)]
            if not payment.node.promotion_eligible:
                raise ReconciliationError("graph_promoted_ineligible_group_payment")
            member = {
                "group_id": group["group_id"],
                "side": "payment",
                "key": payment.node.key,
                "payment_id": payment.payment_id,
            }
            db.execute(
                "INSERT INTO direct_agoda_amount_group_members VALUES (?,?,?,?,?,?,?)",
                (
                    str(group["group_id"]),
                    "payment",
                    payment.node.key,
                    None,
                    None,
                    payment.payment_id,
                    _sha_json(member),
                ),
            )
            group_member_count += 1
        group_count += 1

    for held in graph["held"]:
        signature = held.get("signature")
        event_kind = currency = amount = None
        if signature is not None:
            event_kind, currency, amount = tuple(signature)
        detail_hash = _sha_json(held)
        db.execute(
            "INSERT INTO direct_agoda_amount_withheld VALUES (?,?,?,?,?,?,?,?,?)",
            (
                reconciliation_run_id,
                detail_hash,
                str(held["reason"]),
                event_kind,
                currency,
                amount,
                held.get("reservation_count"),
                held.get("payment_count"),
                detail_hash,
            ),
        )

    counts = {
        "edge": len(graph["amount_candidates"]),
        "individual": individual_count,
        "group": group_count,
        "group_member": group_member_count,
        "withheld": len(graph["held"]),
    }
    membership = {
        "individuals": [
            (row[0], row[1], row[2])
            for row in db.execute(
                "SELECT authority_id,booking_id_sha256,payment_id "
                "FROM direct_agoda_amount_individual_authorities ORDER BY authority_id"
            )
        ],
        "groups": [
            (row[0], row[1], row[2])
            for row in db.execute(
                "SELECT group_id,member_side,member_key "
                "FROM direct_agoda_amount_group_members ORDER BY group_id,member_side,member_key"
            )
        ],
    }
    manifest_payload = {
        "detail_evidence_kind_counts": detail["evidence_kind_counts"],
        "detail_price_snapshot_count": detail["price_snapshot_count"],
        "detail_terminal_no_price_count": detail["terminal_no_price_count"],
        "amount_universe_sealed": detail["amount_universe_sealed"],
        "current_card_count": cards["current_card_count"],
        "agoda_payment_count": cards["agoda_payment_count"],
        "coverage_card_count": cards["coverage_card_count"],
        "counts": counts,
    }
    db.execute(
        """INSERT INTO direct_agoda_amount_reconciliation_manifests VALUES (
               ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?,'private_candidate_only',?
             )""",
        (
            reconciliation_run_id,
            ARTIFACT_TYPE,
            RULE_ID,
            cards["sha256"],
            detail["sha256"],
            cards["run_id"],
            detail["run_id"],
            detail["booking_count"],
            detail["target_2026_count"],
            detail["competitor_count"],
            cards["coverage_end"],
            counts["edge"],
            counts["individual"],
            counts["group"],
            counts["group_member"],
            counts["withheld"],
            _sha_json(membership),
            policy_sha256,
            report_sha256,
            json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ),
    )
    return counts


def _report(
    *,
    reconciliation_run_id: str,
    detail: dict[str, object],
    cards: dict[str, object],
    graph: dict[str, object],
    policy_sha256: str,
    output_db: Path,
) -> dict[str, object]:
    group_members = sum(
        int(group["member_count_each_side"]) * 2
        for group in graph["confirmed_groups"]
    )
    held_reasons = Counter(str(item["reason"]) for item in graph["held"])
    tiers = Counter(str(item["tier"]) for item in graph["confirmed_individuals"])
    return {
        "artifact_type": ARTIFACT_TYPE,
        "rule_id": RULE_ID,
        "reconciliation_run_id": reconciliation_run_id,
        "publication_status": "private_candidate_only",
        "output_db": str(output_db),
        "base_db_sha256": cards["sha256"],
        "detail_db_sha256": detail["sha256"],
        "base_projection_run_id": cards["run_id"],
        "base_projection_status": cards["projection_status"],
        "detail_run_id": detail["run_id"],
        "detail_booking_count": detail["booking_count"],
        "detail_price_snapshot_count": detail["price_snapshot_count"],
        "detail_terminal_no_price_count": detail["terminal_no_price_count"],
        "amount_universe_sealed": detail["amount_universe_sealed"],
        "target_2026_count": detail["target_2026_count"],
        "competitor_count": detail["competitor_count"],
        "card_source_coverage_end": cards["coverage_end"],
        "card_source_coverage_basis": "latest_current_card_event_on",
        "current_card_count": cards["current_card_count"],
        "agoda_card_event_count": cards["agoda_payment_count"],
        "amount_candidate_edge_count": len(graph["amount_candidates"]),
        "confirmed_individual_count": len(graph["confirmed_individuals"]),
        "confirmed_individual_tiers": dict(sorted(tiers.items())),
        "confirmed_group_count": len(graph["confirmed_groups"]),
        "confirmed_group_member_count": group_members,
        "individual_pair_asserted_for_groups": False,
        "withheld_cluster_count": len(graph["held"]),
        "withheld_reasons": dict(sorted(held_reasons.items())),
        "policy_sha256": policy_sha256,
        "generic_links_are_proposed": True,
        "accounting_finality_created": 0,
        "classification_created": 0,
        "allocation_created": 0,
        "journal_created": 0,
        "posting_created": 0,
        "reversal_inheritance_created": 0,
        "external_posting": False,
        "sensitive_row_values_in_report": False,
    }


def build(
    *,
    base_db: Path,
    detail_db: Path,
    output_db: Path,
    report_path: Path,
) -> dict[str, object]:
    if os.path.lexists(output_db) or os.path.lexists(report_path):
        raise FileExistsError("output_artifact_exists")
    if output_db.parent != report_path.parent:
        raise ReconciliationError("output_parent_mismatch")
    output_db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_db.parent.resolve() != Path(tempfile.gettempdir()).resolve():
        os.chmod(output_db.parent, 0o700)
    detail = _detail_snapshot(detail_db)
    cards = _current_card_snapshot(base_db)
    reservation_evidence = _apply_card_coverage(
        detail["evidence"],
        str(cards["coverage_end"]),
    )
    payment_evidence = tuple(cards["payments"])
    policy = {
        "rule_id": RULE_ID,
        "requires": [
            "sealed_converged_three_tab_detail_census",
            "zero_terminal_no_price_observations_for_final_confirmation",
            "2025-08-or-later-competition-universe",
            "exact_currency_and_minor_unit_amount",
            "bidirectionally_closed_candidate_graph",
            "current_card_source_coverage",
        ],
        "individual": [
            "forced_foreign_amount_card4_edge",
            "closed_universe_unique_exact_amount",
        ],
        "group": [
            "balanced_exact_amount_multiset",
            "individual_pair_asserted_false",
            "no_cartesian_generic_links",
        ],
        "forbids": [
            "property_collect_gross_as_card_charge",
            "gross_only_individual_promotion",
            "outside_2026_promotion",
            "classification_side_effect",
            "allocation_side_effect",
            "journal_or_posting_side_effect",
            "reversal_inheritance_side_effect",
        ],
    }
    policy_sha256 = _sha_json(policy)
    graph = resolve_candidate_graph(
        [item.node for item in reservation_evidence],
        [item.node for item in payment_evidence],
        universe_sealed=bool(detail["amount_universe_sealed"]),
    )
    identity = {
        "rule_id": RULE_ID,
        "base_db_sha256": cards["sha256"],
        "detail_db_sha256": detail["sha256"],
        "policy_sha256": policy_sha256,
        "individuals": graph["confirmed_individuals"],
        "groups": graph["confirmed_groups"],
    }
    reconciliation_run_id = "agoda-amount-" + _sha_json(identity)[:20]
    report = _report(
        reconciliation_run_id=reconciliation_run_id,
        detail=detail,
        cards=cards,
        graph=graph,
        policy_sha256=policy_sha256,
        output_db=output_db,
    )
    report_bytes = _canonical(report)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()

    stage_dir = Path(
        tempfile.mkdtemp(prefix=".agoda-amount-reconcile-", dir=str(output_db.parent))
    )
    os.chmod(stage_dir, 0o700)
    stage_db = stage_dir / output_db.name
    stage_report = stage_dir / report_path.name
    published: dict[Path, tuple[int, int]] = {}
    try:
        shutil.copyfile(base_db, stage_db)
        os.chmod(stage_db, 0o600)
        db = sqlite3.connect(stage_db)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            _integrity(db)
            db.row_factory = sqlite3.Row
            before_side_effects = _side_effect_counts(db)
            _create_tables(db)
            with db:
                counts = _insert_results(
                    db,
                    reconciliation_run_id=reconciliation_run_id,
                    detail=detail,
                    cards=cards,
                    reservation_evidence=reservation_evidence,
                    payment_evidence=payment_evidence,
                    graph=graph,
                    policy_sha256=policy_sha256,
                    report_sha256=report_sha256,
                )
            after_side_effects = _side_effect_counts(db)
            if before_side_effects != after_side_effects:
                raise ReconciliationError("accounting_or_payment_side_effect_detected")
            if counts != {
                "edge": report["amount_candidate_edge_count"],
                "individual": report["confirmed_individual_count"],
                "group": report["confirmed_group_count"],
                "group_member": report["confirmed_group_member_count"],
                "withheld": report["withheld_cluster_count"],
            }:
                raise ReconciliationError("inserted_result_count_mismatch")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.commit()
        finally:
            db.close()
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(stage_db) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.chmod(stage_db, 0o600)
        stage_report.write_bytes(report_bytes)
        os.chmod(stage_report, 0o600)
        with stage_db.open("r+b") as stream:
            os.fsync(stream.fileno())
        with stage_report.open("r+b") as stream:
            os.fsync(stream.fileno())

        published[output_db] = _publish_noreplace(stage_db, output_db)
        published[report_path] = _publish_noreplace(stage_report, report_path)
        with closing(_connect_immutable(output_db)) as verified:
            _integrity(verified)
            verified.row_factory = sqlite3.Row
            manifest = verified.execute(
                "SELECT * FROM direct_agoda_amount_reconciliation_manifests"
            ).fetchone()
            if (
                manifest is None
                or str(manifest["reconciliation_run_id"]) != reconciliation_run_id
                or str(manifest["report_sha256"]) != report_sha256
                or int(manifest["confirmed_individual_count"])
                != int(report["confirmed_individual_count"])
                or int(manifest["confirmed_group_count"])
                != int(report["confirmed_group_count"])
            ):
                raise ReconciliationError("published_manifest_verification_failed")
        if report_path.read_bytes() != report_bytes:
            raise ReconciliationError("published_report_verification_failed")
        if _sha_path(base_db) != cards["sha256"] or _sha_path(detail_db) != detail["sha256"]:
            raise ReconciliationError("source_changed_during_publication")
        return {
            **report,
            "output_db_sha256": _sha_path(output_db),
            "report_sha256": report_sha256,
        }
    except Exception:
        for path, token in published.items():
            _unlink_if_owned(path, token)
        raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-db", type=Path, required=True)
    parser.add_argument("--detail-db", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        base_db=args.base_db,
        detail_db=args.detail_db,
        output_db=args.db,
        report_path=args.report,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
