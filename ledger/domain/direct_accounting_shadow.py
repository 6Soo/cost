"""Fail-closed double-entry shadow accounting for the Gate5 families.

This module is intentionally not wired into the normal projection path.  It is
an opt-in, local shadow layer used to prove that a family can be represented
as an atomic, balanced accounting batch before any legacy journal or external
posting engine is touched.

The important separation is:

* a payment can be accounting-final without becoming travel-final;
* a settlement is one atomic M:N component batch, not a collection of
  independently posted reversals;
* ``ledger_currency=KRW`` means the ledger amount is the source
  ``amount_krw`` field.  It does not assert that the source card currency is
  KRW; the source currency and its evidence hash are preserved separately;
* every batch remains ``shadow_balanced``.  There is no code path here that
  writes the legacy ``journal_entries`` table or marks an external posting as
  complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


LEDGER_CURRENCY = "KRW"
SHADOW_SCHEMA_VERSION = "accounting-shadow-v2"
FAMILY_EXISTING = "existing_confirmed_allocation"
FAMILY_OVERHEAD = "confirmed_overhead"
FAMILY_SETTLEMENT = "cancellation_settlement_component"
FAMILY_2026_CLEARING = "unresolved_2026_purchase_clearing"
RULE_EXISTING = "confirmed-allocation-shadow-v2"
RULE_OVERHEAD = "confirmed-overhead-shadow-v2"
RULE_SETTLEMENT = "cancellation-settlement-shadow-v2"
RULE_2026_CLEARING = "unresolved-2026-purchase-clearing-shadow-v1"
CARD_CLEARING_ACCOUNT = "법인카드미지급금"
SETTLEMENT_ACCOUNT = "취소환불대기"
UNRESOLVED_2026_ACCOUNT = "미확정여행원가"


SHADOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS direct_accounting_shadow_batches (
  run_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  family_id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  batch_status TEXT NOT NULL CHECK(batch_status IN ('shadow_balanced','rejected')),
  accounting_period TEXT NOT NULL,
  posting_date TEXT NOT NULL,
  posting_date_source TEXT NOT NULL,
  ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
  currency_basis TEXT NOT NULL,
  source_currency_status TEXT NOT NULL
    CHECK(source_currency_status IN ('known','unknown','mixed')),
  debit_total_krw INTEGER NOT NULL CHECK(debit_total_krw>=0),
  credit_total_krw INTEGER NOT NULL CHECK(credit_total_krw>=0),
  member_count INTEGER NOT NULL CHECK(member_count>0),
  line_count INTEGER NOT NULL CHECK(line_count>0),
  membership_sha256 TEXT NOT NULL CHECK(length(membership_sha256)=64),
  provenance_sha256 TEXT NOT NULL CHECK(length(provenance_sha256)=64),
  idempotency_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,batch_id),
  UNIQUE(run_id,idempotency_key),
  CHECK(debit_total_krw=credit_total_krw),
  CHECK(batch_status='shadow_balanced')
);

CREATE TABLE IF NOT EXISTS direct_accounting_shadow_members (
  run_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  family_id TEXT NOT NULL,
  member_key TEXT NOT NULL,
  payment_id INTEGER NOT NULL,
  source_component_key TEXT NOT NULL,
  member_role TEXT NOT NULL,
  signed_amount_krw INTEGER NOT NULL CHECK(signed_amount_krw<>0),
  occurred_on TEXT NOT NULL,
  accounting_period TEXT NOT NULL,
  source_currency TEXT,
  source_currency_status TEXT NOT NULL
    CHECK(source_currency_status IN ('known','unknown')),
  ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
  currency_evidence_sha256 TEXT NOT NULL CHECK(length(currency_evidence_sha256)=64),
  source_event_key_sha256 TEXT NOT NULL CHECK(length(source_event_key_sha256)=64),
  member_sha256 TEXT NOT NULL CHECK(length(member_sha256)=64),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,batch_id,member_key),
  UNIQUE(run_id,family_id,source_component_key)
);

CREATE TABLE IF NOT EXISTS direct_accounting_shadow_lines (
  run_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  line_no INTEGER NOT NULL CHECK(line_no>0),
  side TEXT NOT NULL CHECK(side IN ('debit','credit')),
  account_code TEXT NOT NULL CHECK(length(trim(account_code))>0),
  amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
  payment_id INTEGER NOT NULL,
  source_component_key TEXT NOT NULL,
  signed_source_amount_krw INTEGER NOT NULL CHECK(signed_source_amount_krw<>0),
  occurred_on TEXT NOT NULL,
  accounting_period TEXT NOT NULL,
  posting_date TEXT NOT NULL,
  ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
  source_currency TEXT,
  currency_evidence_sha256 TEXT NOT NULL CHECK(length(currency_evidence_sha256)=64),
  provenance_sha256 TEXT NOT NULL CHECK(length(provenance_sha256)=64),
  line_sha256 TEXT NOT NULL CHECK(length(line_sha256)=64),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,batch_id,line_no),
  UNIQUE(run_id,batch_id,line_sha256)
);

CREATE TABLE IF NOT EXISTS direct_accounting_shadow_manifests (
  run_id TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('base','with_2026_clearing')),
  schema_version TEXT NOT NULL,
  selected_payment_count INTEGER NOT NULL CHECK(selected_payment_count>=0),
  batch_count INTEGER NOT NULL CHECK(batch_count>=0),
  member_count INTEGER NOT NULL CHECK(member_count>=0),
  line_count INTEGER NOT NULL CHECK(line_count>=0),
  family_set_sha256 TEXT NOT NULL CHECK(length(family_set_sha256)=64),
  membership_sha256 TEXT NOT NULL CHECK(length(membership_sha256)=64),
  policy_sha256 TEXT NOT NULL CHECK(length(policy_sha256)=64),
  ledger_mapping_sha256 TEXT NOT NULL CHECK(length(ledger_mapping_sha256)=64),
  status TEXT NOT NULL CHECK(status='shadow_balanced'),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,mode)
);

CREATE INDEX IF NOT EXISTS direct_accounting_shadow_members_by_payment
  ON direct_accounting_shadow_members(run_id,payment_id);
CREATE INDEX IF NOT EXISTS direct_accounting_shadow_lines_by_batch
  ON direct_accounting_shadow_lines(run_id,batch_id);
"""


POSTING_SCHEMA = """
CREATE TABLE IF NOT EXISTS direct_accounting_posting_batches (
  run_id TEXT NOT NULL,
  posting_batch_id TEXT NOT NULL,
  shadow_batch_id TEXT NOT NULL,
  family_id TEXT NOT NULL,
  posting_status TEXT NOT NULL
    CHECK(posting_status IN ('candidate','posted_shadow','reversed')),
  accounting_period TEXT NOT NULL,
  posting_date TEXT NOT NULL,
  ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
  debit_total_krw INTEGER NOT NULL CHECK(debit_total_krw>=0),
  credit_total_krw INTEGER NOT NULL CHECK(credit_total_krw>=0),
  member_count INTEGER NOT NULL CHECK(member_count>0),
  line_count INTEGER NOT NULL CHECK(line_count>0),
  approval_sha256 TEXT NOT NULL CHECK(length(approval_sha256)=64),
  mapping_sha256 TEXT NOT NULL CHECK(length(mapping_sha256)=64),
  source_provenance_sha256 TEXT NOT NULL CHECK(length(source_provenance_sha256)=64),
  idempotency_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,posting_batch_id),
  UNIQUE(run_id,idempotency_key),
  CHECK(debit_total_krw=credit_total_krw)
);

CREATE TABLE IF NOT EXISTS direct_accounting_posting_lines (
  run_id TEXT NOT NULL,
  posting_batch_id TEXT NOT NULL,
  line_no INTEGER NOT NULL CHECK(line_no>0),
  side TEXT NOT NULL CHECK(side IN ('debit','credit')),
  account_code TEXT NOT NULL CHECK(length(trim(account_code))>0),
  source_account_code TEXT NOT NULL CHECK(length(trim(source_account_code))>0),
  amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
  payment_id INTEGER NOT NULL,
  source_component_key TEXT NOT NULL,
  source_shadow_line_sha256 TEXT NOT NULL CHECK(length(source_shadow_line_sha256)=64),
  accounting_period TEXT NOT NULL,
  posting_date TEXT NOT NULL,
  ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
  line_sha256 TEXT NOT NULL CHECK(length(line_sha256)=64),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,posting_batch_id,line_no),
  UNIQUE(run_id,posting_batch_id,line_sha256)
);

CREATE TABLE IF NOT EXISTS direct_accounting_posting_manifests (
  run_id TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('base','with_2026_clearing')),
  posting_status TEXT NOT NULL CHECK(posting_status IN ('blocked','candidate','posted_shadow')),
  selected_payment_count INTEGER NOT NULL CHECK(selected_payment_count>=0),
  batch_count INTEGER NOT NULL CHECK(batch_count>=0),
  line_count INTEGER NOT NULL CHECK(line_count>=0),
  approval_sha256 TEXT NOT NULL CHECK(length(approval_sha256)=64),
  mapping_sha256 TEXT NOT NULL CHECK(length(mapping_sha256)=64),
  source_shadow_manifest_sha256 TEXT NOT NULL CHECK(length(source_shadow_manifest_sha256)=64),
  release_ready INTEGER NOT NULL CHECK(release_ready IN (0,1)),
  external_posting INTEGER NOT NULL CHECK(external_posting=0),
  payload_json TEXT NOT NULL,
  PRIMARY KEY(run_id,mode)
);

CREATE INDEX IF NOT EXISTS direct_accounting_posting_lines_by_payment
  ON direct_accounting_posting_lines(run_id,payment_id);
"""


@dataclass(frozen=True)
class Payment:
    payment_id: int
    external_key: str
    direct_event_key: str
    occurred_on: str
    amount_krw: int
    source_currency: str | None
    foreign_amount: str | None
    source_currency_status: str
    currency_evidence_sha256: str


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _set_sha(values: Iterable[str]) -> str:
    return _sha(("\n".join(sorted(str(value) for value in values)) + "\n").encode())


def apply_shadow_schema(db: sqlite3.Connection) -> None:
    db.executescript(SHADOW_SCHEMA)


def apply_posting_schema(db: sqlite3.Connection) -> None:
    db.executescript(POSTING_SCHEMA)


def _payment_rows(db: sqlite3.Connection, run_id: str) -> dict[int, Payment]:
    rows = db.execute(
        """SELECT p.id,p.external_key,
                  n.card_event_id || '#' || n.event_role AS direct_event_key,
                  p.occurred_on,p.amount_krw,p.currency,p.foreign_amount
           FROM payment_transactions p
           JOIN direct_payment_projection_links l
             ON l.payment_id=p.id AND l.run_id=?
           JOIN direct_normalized_payments n ON n.id=l.direct_payment_id
           ORDER BY p.id""",
        (run_id,),
    ).fetchall()
    result: dict[int, Payment] = {}
    for row in rows:
        payment_id = int(row[0])
        if payment_id in result:
            raise ValueError(f"shadow_payment_link_not_unique:{payment_id}")
        if int(row[4]) == 0:
            raise ValueError(f"shadow_zero_amount:{payment_id}")
        source_currency = str(row[5]).strip() if row[5] else None
        foreign_amount = str(row[6]) if row[6] is not None else None
        status = "known" if source_currency else "unknown"
        currency_hash = _sha({
            "payment_id": payment_id,
            "amount_krw": int(row[4]),
            "source_currency": source_currency,
            "foreign_amount": foreign_amount,
            "basis": "payment_transactions.amount_krw",
        })
        result[payment_id] = Payment(
            payment_id=payment_id,
            external_key=str(row[1]),
            direct_event_key=str(row[2]),
            occurred_on=str(row[3]),
            amount_krw=int(row[4]),
            source_currency=source_currency,
            foreign_amount=foreign_amount,
            source_currency_status=status,
            currency_evidence_sha256=currency_hash,
        )
    return result


def _current_axes(db: sqlite3.Connection, payment_ids: Iterable[int]) -> dict[int, dict[str, str]]:
    ids = sorted({int(value) for value in payment_ids})
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = db.execute(
        f"""SELECT target_id,dimension,value
            FROM current_classification_decisions
            WHERE target_type='payment' AND decision_status='confirmed'
              AND target_id IN ({marks})
              AND dimension IN ('account','cost_type','allocation_target')
            ORDER BY target_id,dimension,id""",
        tuple(ids),
    ).fetchall()
    result: dict[int, dict[str, str]] = defaultdict(dict)
    for row in rows:
        payment_id, dimension, value = int(row[0]), str(row[1]), str(row[2])
        if dimension in result[payment_id] and result[payment_id][dimension] != value:
            raise ValueError(f"shadow_axis_conflict:{payment_id}:{dimension}")
        result[payment_id][dimension] = value
    return dict(result)


def _event_hash(payment: Payment) -> str:
    return _sha({
        "external_key": payment.external_key,
        "direct_event_key": payment.direct_event_key,
        "payment_id": payment.payment_id,
    })


def _member_hash(payload: Mapping[str, object]) -> str:
    return _sha(payload)


def _payment_period(payment: Payment) -> str:
    period = payment.occurred_on[:4]
    if len(period) != 4 or not period.isdigit():
        raise ValueError(f"shadow_accounting_period_invalid:{payment.payment_id}")
    return period


def _payment_posting_date(payment: Payment) -> str:
    if len(payment.occurred_on) < 10:
        raise ValueError(f"shadow_posting_date_invalid:{payment.payment_id}")
    return payment.occurred_on[:10]


def _source_currency_status(values: Sequence[str | None]) -> str:
    known = {value for value in values if value}
    if not known:
        return "unknown"
    if len(known) == 1 and len(known) == len(values):
        return "known"
    return "mixed"


def _confirmed_allocation_members(
    db: sqlite3.Connection,
    run_id: str,
    payments: Mapping[int, Payment],
    excluded: set[int],
) -> tuple[dict[int, list[dict[str, object]]], set[int]]:
    rows = db.execute(
        """SELECT a.payment_id,a.id,a.amount_krw,t.code,t.target_type
           FROM current_cost_allocations a
           JOIN allocation_targets t ON t.id=a.target_id
           JOIN direct_payment_projection_links l
             ON l.payment_id=a.payment_id AND l.run_id=?
           WHERE a.allocation_status='confirmed'
           ORDER BY a.payment_id,a.id""",
        (run_id,),
    ).fetchall()
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        payment_id = int(row[0])
        if payment_id in excluded or payment_id not in payments:
            continue
        grouped[payment_id].append({
            "component_key": f"allocation:{int(row[1])}",
            "amount_krw": int(row[2]),
            "target_code": str(row[3]),
            "target_type": str(row[4]),
        })
    selected = set(grouped)
    for payment_id, members in grouped.items():
        if sum(int(member["amount_krw"]) for member in members) != payments[payment_id].amount_krw:
            raise ValueError(f"shadow_allocation_amount_mismatch:{payment_id}")
    return dict(grouped), selected


def _confirmed_overhead_ids(
    db: sqlite3.Connection,
    run_id: str,
    payments: Mapping[int, Payment],
    excluded: set[int],
) -> set[int]:
    rows = db.execute(
        """SELECT r.payment_id
           FROM allocation_review_cases r
           JOIN direct_payment_projection_links l
             ON l.payment_id=r.payment_id AND l.run_id=?
           JOIN payment_transactions p ON p.id=r.payment_id
           WHERE r.outcome='overhead'
             AND r.reason_code='direct_full_axis_overhead'
             AND r.review_status='confirmed'
             AND p.amount_krw<>0
           ORDER BY r.payment_id""",
        (run_id,),
    ).fetchall()
    ids = {int(row[0]) for row in rows}
    if not ids <= set(payments):
        raise ValueError("shadow_overhead_payment_not_projected")
    overlap = ids & excluded
    if overlap:
        raise ValueError(f"shadow_overhead_overlap:{sorted(overlap)[:3]}")
    axes = _current_axes(db, ids)
    for payment_id in ids:
        if set(axes.get(payment_id, {})) != {"account", "cost_type", "allocation_target"}:
            raise ValueError(f"shadow_overhead_axes_incomplete:{payment_id}")
    return ids


def _settlement_members(
    db: sqlite3.Connection,
    run_id: str,
    payments: Mapping[int, Payment],
    excluded: set[int],
) -> dict[str, list[dict[str, object]]]:
    rows = db.execute(
        """SELECT m.authority_id,m.direct_event_key,m.payment_id,m.source_key,
                  m.source_sha256,m.transaction_type,m.member_role,m.amount_krw,
                  m.occurred_on,m.current_evidence_id,a.member_count,a.purchase_count,
                  a.reversal_count,a.net_krw
           FROM direct_cancellation_settlement_members m
           JOIN direct_cancellation_settlement_authorities a
             ON a.run_id=m.run_id AND a.authority_id=m.authority_id
           WHERE m.run_id=?
           ORDER BY m.authority_id,m.payment_id,m.direct_event_key""",
        (run_id,),
    ).fetchall()
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    authority_meta: dict[str, tuple[int, int, int, int]] = {}
    for row in rows:
        authority = str(row[0])
        payment_id = int(row[2])
        if payment_id not in payments:
            raise ValueError(f"shadow_settlement_payment_not_projected:{payment_id}")
        if payment_id in excluded:
            raise ValueError(f"shadow_settlement_overlap:{payment_id}")
        amount = int(row[7])
        if amount == 0:
            raise ValueError(f"shadow_settlement_zero_component:{authority}")
        meta = (int(row[10]), int(row[11]), int(row[12]), int(row[13]))
        if authority in authority_meta and authority_meta[authority] != meta:
            raise ValueError(f"shadow_settlement_authority_conflict:{authority}")
        authority_meta[authority] = meta
        grouped[authority].append({
            "component_key": f"settlement:{authority}:{str(row[1])}",
            "payment_id": payment_id,
            "amount_krw": amount,
            "member_role": str(row[6]),
            "transaction_type": str(row[5]),
            "occurred_on": str(row[8]),
            "current_evidence_id": str(row[9]),
            "source_key": str(row[3]),
            "source_sha256": str(row[4]),
        })
    for authority, members in grouped.items():
        expected_count, purchase_count, reversal_count, net_krw = authority_meta[authority]
        if len(members) != expected_count:
            raise ValueError(f"shadow_settlement_count_mismatch:{authority}")
        if sum(int(m["amount_krw"]) for m in members) != net_krw or net_krw != 0:
            raise ValueError(f"shadow_settlement_net_nonzero:{authority}")
        if sum(1 for m in members if m["member_role"] == "purchase") != purchase_count:
            raise ValueError(f"shadow_settlement_purchase_count_mismatch:{authority}")
        if sum(1 for m in members if m["member_role"] == "reversal") != reversal_count:
            raise ValueError(f"shadow_settlement_reversal_count_mismatch:{authority}")
        if len({str(m["component_key"]) for m in members}) != len(members):
            raise ValueError(f"shadow_settlement_component_duplicate:{authority}")
        if len({str(m["occurred_on"])[:4] for m in members}) != 1:
            raise ValueError(f"shadow_settlement_period_mixed:{authority}")
    return dict(grouped)


def _2026_clearing_ids(
    db: sqlite3.Connection,
    run_id: str,
    payments: Mapping[int, Payment],
    excluded: set[int],
) -> set[int]:
    rows = db.execute(
        """SELECT r.payment_id
           FROM allocation_review_cases r
           JOIN direct_payment_projection_links l
             ON l.payment_id=r.payment_id AND l.run_id=?
           JOIN payment_transactions p ON p.id=r.payment_id
           WHERE r.outcome='trip'
             AND r.reason_code='provisional_travel_target_metadata_enrichment'
             AND r.review_status='auto_provisional'
             AND p.transaction_type='purchase'
             AND substr(p.occurred_on,1,4)='2026'
             AND p.amount_krw>0
           ORDER BY r.payment_id""",
        (run_id,),
    ).fetchall()
    ids = {int(row[0]) for row in rows}
    if not ids <= set(payments):
        raise ValueError("shadow_2026_payment_not_projected")
    overlap = ids & excluded
    if overlap:
        raise ValueError(f"shadow_2026_overlap:{sorted(overlap)[:3]}")
    return ids


def _batch_provenance(
    run_id: str, family_id: str, members: Sequence[Mapping[str, object]],
) -> tuple[str, str]:
    member_payloads = [dict(sorted(member.items())) for member in members]
    membership = _sha({
        "run_id": run_id,
        "family_id": family_id,
        "members": member_payloads,
    })
    provenance = _sha({
        "membership_sha256": membership,
        "evidence": [
            {
                "payment_id": member.get("payment_id"),
                "source_event_key_sha256": member.get("source_event_key_sha256"),
                "currency_evidence_sha256": member.get("currency_evidence_sha256"),
            }
            for member in member_payloads
        ],
    })
    return membership, provenance


def _insert_batch(
    db: sqlite3.Connection,
    run_id: str,
    family_id: str,
    rule_id: str,
    members: Sequence[Mapping[str, object]],
    debit_account: str | None = None,
    credit_account: str | None = None,
) -> tuple[int, int]:
    if not members:
        raise ValueError(f"shadow_empty_batch:{family_id}")
    normalized = [dict(member) for member in members]
    member_keys = [str(member["member_key"]) for member in normalized]
    if len(set(member_keys)) != len(member_keys):
        raise ValueError(f"shadow_member_key_duplicate:{family_id}")
    membership_sha, provenance_sha = _batch_provenance(
        run_id, family_id, normalized,
    )
    batch_id = _sha({
        "run_id": run_id,
        "family_id": family_id,
        "membership_sha256": membership_sha,
        "rule_id": rule_id,
    })
    idempotency_key = f"{SHADOW_SCHEMA_VERSION}:{batch_id}"
    periods = {str(member["accounting_period"]) for member in normalized}
    posting_dates = {str(member["posting_date"]) for member in normalized}
    if len(periods) != 1:
        raise ValueError(f"shadow_batch_period_mixed:{batch_id}")
    if family_id == FAMILY_SETTLEMENT:
        posting_date = max(posting_dates)
        posting_date_source = "max(member.occurred_on)"
    else:
        if len(posting_dates) != 1:
            raise ValueError(f"shadow_batch_posting_date_mixed:{batch_id}")
        posting_date = next(iter(posting_dates))
        posting_date_source = "payment.occurred_on"
    source_status = _source_currency_status(
        [member.get("source_currency") for member in normalized]
    )
    lines: list[dict[str, object]] = []
    line_no = 1
    for member in normalized:
        signed = int(member["signed_amount_krw"])
        amount = abs(signed)
        if family_id == FAMILY_SETTLEMENT:
            positive_debit, positive_credit = SETTLEMENT_ACCOUNT, CARD_CLEARING_ACCOUNT
        else:
            positive_debit = str(debit_account or member.get("expense_account") or "")
            positive_credit = str(credit_account or CARD_CLEARING_ACCOUNT)
        if not positive_debit or not positive_credit:
            raise ValueError(f"shadow_account_mapping_missing:{batch_id}")
        pair = (
            ("debit", positive_debit), ("credit", positive_credit)
        ) if signed > 0 else (
            ("debit", positive_credit), ("credit", positive_debit)
        )
        for side, account_code in pair:
            line_payload = {
                "run_id": run_id,
                "batch_id": batch_id,
                "line_no": line_no,
                "side": side,
                "account_code": account_code,
                "amount_krw": amount,
                "payment_id": int(member["payment_id"]),
                "source_component_key": str(member["source_component_key"]),
                "signed_source_amount_krw": signed,
                "occurred_on": str(member["occurred_on"]),
                "accounting_period": str(member["accounting_period"]),
                "posting_date": posting_date,
                "ledger_currency": LEDGER_CURRENCY,
                "source_currency": member.get("source_currency"),
                "currency_evidence_sha256": str(member["currency_evidence_sha256"]),
                "provenance_sha256": str(member["provenance_sha256"]),
            }
            line_payload["line_sha256"] = _sha(line_payload)
            lines.append(line_payload)
            line_no += 1
    debit_total = sum(int(line["amount_krw"]) for line in lines if line["side"] == "debit")
    credit_total = sum(int(line["amount_krw"]) for line in lines if line["side"] == "credit")
    if debit_total != credit_total:
        raise ValueError(f"shadow_batch_unbalanced:{batch_id}")
    payload = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "run_id": run_id,
        "batch_id": batch_id,
        "family_id": family_id,
        "rule_id": rule_id,
        "accounting_period": next(iter(periods)),
        "posting_date": posting_date,
        "posting_date_source": posting_date_source,
        "ledger_currency": LEDGER_CURRENCY,
        "currency_basis": "payment_transactions.amount_krw",
        "source_currency_status": source_status,
        "debit_total_krw": debit_total,
        "credit_total_krw": credit_total,
        "member_count": len(normalized),
        "line_count": len(lines),
        "membership_sha256": membership_sha,
        "provenance_sha256": provenance_sha,
        "idempotency_key": idempotency_key,
        "posting_status": "shadow_only",
    }
    db.execute(
        """INSERT INTO direct_accounting_shadow_batches(
             run_id,batch_id,family_id,rule_id,batch_status,accounting_period,
             posting_date,posting_date_source,ledger_currency,currency_basis,
             source_currency_status,debit_total_krw,credit_total_krw,member_count,
             line_count,membership_sha256,provenance_sha256,idempotency_key,payload_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,batch_id,family_id,rule_id,"shadow_balanced",
            next(iter(periods)),posting_date,posting_date_source,LEDGER_CURRENCY,
            "payment_transactions.amount_krw",source_status,debit_total,credit_total,
            len(normalized),len(lines),membership_sha,provenance_sha,idempotency_key,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ),
    )
    for member in normalized:
        db.execute(
            """INSERT INTO direct_accounting_shadow_members(
                 run_id,batch_id,family_id,member_key,payment_id,source_component_key,
                 member_role,signed_amount_krw,occurred_on,accounting_period,
                 source_currency,source_currency_status,ledger_currency,
                 currency_evidence_sha256,source_event_key_sha256,member_sha256,
                 payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,batch_id,family_id,str(member["member_key"]),
                int(member["payment_id"]),str(member["source_component_key"]),
                str(member["member_role"]),int(member["signed_amount_krw"]),
                str(member["occurred_on"]),str(member["accounting_period"]),
                member.get("source_currency"),str(member["source_currency_status"]),
                LEDGER_CURRENCY,str(member["currency_evidence_sha256"]),
                str(member["source_event_key_sha256"]),str(member["member_sha256"]),
                json.dumps(dict(member), ensure_ascii=False, sort_keys=True),
            ),
        )
    for line in lines:
        db.execute(
            """INSERT INTO direct_accounting_shadow_lines(
                 run_id,batch_id,line_no,side,account_code,amount_krw,payment_id,
                 source_component_key,signed_source_amount_krw,occurred_on,
                 accounting_period,posting_date,ledger_currency,source_currency,
                 currency_evidence_sha256,provenance_sha256,line_sha256,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,batch_id,int(line["line_no"]),str(line["side"]),
                str(line["account_code"]),int(line["amount_krw"]),
                int(line["payment_id"]),str(line["source_component_key"]),
                int(line["signed_source_amount_krw"]),str(line["occurred_on"]),
                str(line["accounting_period"]),str(line["posting_date"]),
                LEDGER_CURRENCY,line.get("source_currency"),
                str(line["currency_evidence_sha256"]),str(line["provenance_sha256"]),
                str(line["line_sha256"]),json.dumps(line, ensure_ascii=False, sort_keys=True),
            ),
        )
    return 1, len(normalized)


def _make_member(
    payment: Payment,
    *,
    family_id: str,
    component_key: str,
    signed_amount: int,
    member_role: str,
    provenance_extra: Mapping[str, object] | None = None,
    expense_account: str | None = None,
) -> dict[str, object]:
    accounting_period = _payment_period(payment)
    posting_date = _payment_posting_date(payment)
    provenance = {
        "family_id": family_id,
        "component_key": component_key,
        "payment_id": payment.payment_id,
        "direct_event_key": payment.direct_event_key,
        "amount_krw": signed_amount,
        "currency_evidence_sha256": payment.currency_evidence_sha256,
        **dict(provenance_extra or {}),
    }
    provenance_sha = _sha(provenance)
    member_payload = {
        "family_id": family_id,
        "component_key": component_key,
        "payment_id": payment.payment_id,
        "signed_amount_krw": signed_amount,
        "member_role": member_role,
        "source_event_key_sha256": _event_hash(payment),
        "currency_evidence_sha256": payment.currency_evidence_sha256,
        "provenance_sha256": provenance_sha,
    }
    member_sha = _member_hash(member_payload)
    return {
        "payment_id": payment.payment_id,
        "source_component_key": component_key,
        "member_role": member_role,
        "signed_amount_krw": signed_amount,
        "occurred_on": payment.occurred_on,
        "accounting_period": accounting_period,
        "posting_date": posting_date,
        "source_currency": payment.source_currency,
        "source_currency_status": payment.source_currency_status,
        "currency_evidence_sha256": payment.currency_evidence_sha256,
        "source_event_key_sha256": _event_hash(payment),
        "provenance_sha256": provenance_sha,
        "member_key": member_sha,
        "member_sha256": member_sha,
        "expense_account": expense_account,
        "provenance_payload": provenance,
    }


def _family_member_sets(
    db: sqlite3.Connection,
    run_id: str,
    payments: Mapping[int, Payment],
    include_2026_clearing: bool,
) -> tuple[dict[str, set[int]], dict[str, Any]]:
    existing_members, existing_ids = _confirmed_allocation_members(
        db, run_id, payments, set(),
    )
    overhead_ids = _confirmed_overhead_ids(db, run_id, payments, existing_ids)
    settlement_grouped = _settlement_members(
        db, run_id, payments, existing_ids | overhead_ids,
    )
    settlement_ids = {
        int(member["payment_id"])
        for members in settlement_grouped.values()
        for member in members
    }
    if existing_ids & settlement_ids or overhead_ids & settlement_ids:
        raise ValueError("shadow_family_overlap_settlement")
    clearing_ids: set[int] = set()
    if include_2026_clearing:
        clearing_ids = _2026_clearing_ids(
            db, run_id, payments, existing_ids | overhead_ids | settlement_ids,
        )
    families = {
        FAMILY_EXISTING: existing_ids,
        FAMILY_OVERHEAD: overhead_ids,
        FAMILY_SETTLEMENT: settlement_ids,
    }
    if include_2026_clearing:
        families[FAMILY_2026_CLEARING] = clearing_ids
    all_ids: set[int] = set()
    for family, ids in families.items():
        if all_ids & ids:
            raise ValueError(f"shadow_family_payment_overlap:{family}")
        all_ids |= ids
    return families, {
        "existing_members": existing_members,
        "settlement_grouped": settlement_grouped,
        "clearing_ids": clearing_ids,
        "all_ids": all_ids,
    }


def _manifest_policy(include_2026_clearing: bool) -> dict[str, object]:
    return {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "mode": "with_2026_clearing" if include_2026_clearing else "base",
        "families": [
            FAMILY_EXISTING,
            FAMILY_OVERHEAD,
            FAMILY_SETTLEMENT,
        ] + ([FAMILY_2026_CLEARING] if include_2026_clearing else []),
        "legacy_journal_write": False,
        "external_posting": False,
        "ledger_currency": LEDGER_CURRENCY,
        "currency_basis": "payment_transactions.amount_krw",
        "travel_period_used_for_accounting": False,
        "reversal_inheritance": False,
        "2025_mail_only_rule_unchanged": True,
        "2026_clearing_requires_explicit_user_rule": True,
    }


def build_shadow_accounting(
    db: sqlite3.Connection,
    run_id: str,
    *,
    include_2026_clearing: bool = False,
) -> dict[str, object]:
    """Build a deterministic, balanced shadow run in the supplied DB.

    The caller is expected to pass a disposable copy of a candidate DB.  The
    function never inserts into ``allocation_plans``, ``cost_allocations`` or
    ``journal_entries`` and never changes a classification decision.
    """
    apply_shadow_schema(db)
    mode = "with_2026_clearing" if include_2026_clearing else "base"
    existing_manifest = db.execute(
        "SELECT family_set_sha256,membership_sha256,payload_json "
        "FROM direct_accounting_shadow_manifests WHERE run_id=? AND mode=?",
        (run_id, mode),
    ).fetchone()
    if existing_manifest is not None:
        return validate_shadow_accounting(db, run_id, mode=mode)
    payments = _payment_rows(db, run_id)
    families, details = _family_member_sets(
        db, run_id, payments, include_2026_clearing,
    )
    selected_ids = details["all_ids"]
    legacy_journal_count = db.execute(
        """SELECT COUNT(*)
           FROM journal_entries j
           JOIN cost_allocations ca ON ca.id=j.allocation_id
           JOIN allocation_plans ap ON ap.id=ca.plan_id
           WHERE ap.payment_id IN (%s)""" % (
               ",".join("?" for _ in selected_ids) or "NULL"
           ),
        tuple(sorted(selected_ids)),
    ).fetchone()[0]
    if int(legacy_journal_count):
        raise ValueError("shadow_legacy_journal_already_present")
    axes = _current_axes(db, families[FAMILY_OVERHEAD] | families[FAMILY_EXISTING])
    db.execute("BEGIN")
    try:
        batch_count = 0
        member_count = 0
        line_count = 0
        family_batch_ids: dict[str, list[str]] = defaultdict(list)
        family_member_hashes: dict[str, list[str]] = defaultdict(list)
        for payment_id in sorted(families[FAMILY_EXISTING]):
            payment = payments[payment_id]
            members = []
            for allocation in details["existing_members"][payment_id]:
                members.append(_make_member(
                    payment,
                    family_id=FAMILY_EXISTING,
                    component_key=str(allocation["component_key"]),
                    signed_amount=int(allocation["amount_krw"]),
                    member_role="allocation",
                    provenance_extra={
                        "target_code": allocation["target_code"],
                        "target_type": allocation["target_type"],
                    },
                    expense_account=axes[payment_id]["account"],
                ))
            before = db.total_changes
            _insert_batch(db, run_id, FAMILY_EXISTING, RULE_EXISTING, members)
            batch_count += 1
            member_count += len(members)
            line_count += len(members) * 2
            family_member_hashes[FAMILY_EXISTING].extend(
                str(member["member_key"]) for member in members
            )
            family_batch_ids[FAMILY_EXISTING].append(
                str(db.execute(
                    "SELECT batch_id FROM direct_accounting_shadow_batches "
                    "WHERE run_id=? AND family_id=? ORDER BY rowid DESC LIMIT 1",
                    (run_id, FAMILY_EXISTING),
                ).fetchone()[0])
            )
            del before
        for payment_id in sorted(families[FAMILY_OVERHEAD]):
            payment = payments[payment_id]
            member = _make_member(
                payment,
                family_id=FAMILY_OVERHEAD,
                component_key=f"overhead:{payment_id}",
                signed_amount=payment.amount_krw,
                member_role="confirmed_overhead",
                provenance_extra={
                    "axes": axes[payment_id],
                    "review_rule": "direct_full_axis_overhead",
                },
                expense_account=axes[payment_id]["account"],
            )
            _insert_batch(db, run_id, FAMILY_OVERHEAD, RULE_OVERHEAD, [member])
            batch_count += 1
            member_count += 1
            line_count += 2
            family_member_hashes[FAMILY_OVERHEAD].append(str(member["member_key"]))
            family_batch_ids[FAMILY_OVERHEAD].append(
                str(db.execute(
                    "SELECT batch_id FROM direct_accounting_shadow_batches "
                    "WHERE run_id=? AND family_id=? ORDER BY rowid DESC LIMIT 1",
                    (run_id, FAMILY_OVERHEAD),
                ).fetchone()[0])
            )
        for authority_id, raw_members in sorted(details["settlement_grouped"].items()):
            members = []
            for raw in raw_members:
                payment = payments[int(raw["payment_id"])]
                member = _make_member(
                    payment,
                    family_id=FAMILY_SETTLEMENT,
                    component_key=str(raw["component_key"]),
                    signed_amount=int(raw["amount_krw"]),
                    member_role=str(raw["member_role"]),
                    provenance_extra={
                        "authority_id": authority_id,
                        "current_evidence_id": raw["current_evidence_id"],
                        "source_key_sha256": _sha(str(raw["source_key"])),
                        "source_sha256": raw["source_sha256"],
                        "transaction_type": raw["transaction_type"],
                    },
                )
                members.append(member)
            _insert_batch(
                db, run_id, FAMILY_SETTLEMENT, RULE_SETTLEMENT, members,
            )
            batch_count += 1
            member_count += len(members)
            line_count += len(members) * 2
            family_member_hashes[FAMILY_SETTLEMENT].extend(
                str(member["member_key"]) for member in members
            )
            family_batch_ids[FAMILY_SETTLEMENT].append(
                str(db.execute(
                    "SELECT batch_id FROM direct_accounting_shadow_batches "
                    "WHERE run_id=? AND family_id=? ORDER BY rowid DESC LIMIT 1",
                    (run_id, FAMILY_SETTLEMENT),
                ).fetchone()[0])
            )
        if include_2026_clearing:
            for payment_id in sorted(families[FAMILY_2026_CLEARING]):
                payment = payments[payment_id]
                member = _make_member(
                    payment,
                    family_id=FAMILY_2026_CLEARING,
                    component_key=f"unresolved-2026:{payment_id}",
                    signed_amount=payment.amount_krw,
                    member_role="provisional_purchase_clearing",
                    provenance_extra={
                        "source_review_status": "auto_provisional",
                        "source_reason_code": "provisional_travel_target_metadata_enrichment",
                        "travel_final": False,
                        "service_period": "",
                        "trip_code": "",
                        "reservation_number": "",
                    },
                    expense_account=UNRESOLVED_2026_ACCOUNT,
                )
                _insert_batch(
                    db, run_id, FAMILY_2026_CLEARING, RULE_2026_CLEARING, [member],
                )
                batch_count += 1
                member_count += 1
                line_count += 2
                family_member_hashes[FAMILY_2026_CLEARING].append(
                    str(member["member_key"])
                )
                family_batch_ids[FAMILY_2026_CLEARING].append(
                    str(db.execute(
                        "SELECT batch_id FROM direct_accounting_shadow_batches "
                        "WHERE run_id=? AND family_id=? ORDER BY rowid DESC LIMIT 1",
                        (run_id, FAMILY_2026_CLEARING),
                    ).fetchone()[0])
                )
        family_set_sha = _sha({
            family: _set_sha(str(value) for value in sorted(ids))
            for family, ids in sorted(families.items())
        })
        membership_sha = _sha({
            family: _set_sha(values)
            for family, values in sorted(family_member_hashes.items())
        })
        policy = _manifest_policy(include_2026_clearing)
        policy_sha = _sha(policy)
        mapping = {
            "card_clearing": CARD_CLEARING_ACCOUNT,
            "settlement": SETTLEMENT_ACCOUNT,
            "unresolved_2026": UNRESOLVED_2026_ACCOUNT,
            "expense_account_source": "confirmed account axis for base families",
            "mapping_status": "shadow_label_mapping_not_production_chart",
        }
        mapping_sha = _sha(mapping)
        payload = {
            **policy,
            "run_id": run_id,
            "selected_payment_count": len(selected_ids),
            "batch_count": batch_count,
            "member_count": member_count,
            "line_count": line_count,
            "family_counts": {family: len(ids) for family, ids in families.items()},
            "family_batch_counts": {
                family: len(ids) for family, ids in family_batch_ids.items()
            },
            "family_set_sha256": family_set_sha,
            "membership_sha256": membership_sha,
            "policy_sha256": policy_sha,
            "ledger_mapping_sha256": mapping_sha,
            "posting_status": "shadow_only",
        }
        db.execute(
            """INSERT INTO direct_accounting_shadow_manifests(
                 run_id,mode,schema_version,selected_payment_count,batch_count,
                 member_count,line_count,family_set_sha256,membership_sha256,
                 policy_sha256,ledger_mapping_sha256,status,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,mode,SHADOW_SCHEMA_VERSION,len(selected_ids),batch_count,
                member_count,line_count,family_set_sha,membership_sha,policy_sha,
                mapping_sha,"shadow_balanced",
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return validate_shadow_accounting(db, run_id, mode=mode)


def validate_shadow_accounting(
    db: sqlite3.Connection, run_id: str, *, mode: str,
) -> dict[str, object]:
    issues: list[str] = []
    manifest = db.execute(
        """SELECT mode,schema_version,selected_payment_count,batch_count,
                  member_count,line_count,family_set_sha256,membership_sha256,
                  policy_sha256,ledger_mapping_sha256,status,payload_json
           FROM direct_accounting_shadow_manifests
           WHERE run_id=? AND mode=?""",
        (run_id, mode),
    ).fetchone()
    if manifest is None:
        return {"passed": False, "issues": ["shadow_manifest_missing"], "mode": mode}
    batches = db.execute(
        """SELECT batch_id,family_id,batch_status,accounting_period,posting_date,
                  posting_date_source,ledger_currency,currency_basis,
                  source_currency_status,debit_total_krw,credit_total_krw,
                  member_count,line_count,membership_sha256,provenance_sha256,
                  idempotency_key
           FROM direct_accounting_shadow_batches WHERE run_id=? ORDER BY batch_id""",
        (run_id,),
    ).fetchall()
    batch_ids = {str(row[0]) for row in batches}
    if len(batch_ids) != len(batches):
        issues.append("shadow_batch_duplicate")
    for row in batches:
        batch_id = str(row[0])
        if str(row[2]) != "shadow_balanced" or str(row[6]) != LEDGER_CURRENCY:
            issues.append(f"shadow_batch_status_or_currency:{batch_id}")
        if not str(row[3]).strip() or len(str(row[4])) < 10:
            issues.append(f"shadow_batch_period_or_date_missing:{batch_id}")
        if str(row[7]) != "payment_transactions.amount_krw":
            issues.append(f"shadow_batch_currency_basis_missing:{batch_id}")
        if int(row[9]) != int(row[10]):
            issues.append(f"shadow_batch_unbalanced_header:{batch_id}")
        members = db.execute(
            """SELECT member_key,payment_id,member_role,signed_amount_krw,
                      accounting_period,ledger_currency,source_currency_status,
                      currency_evidence_sha256,source_event_key_sha256,member_sha256
               FROM direct_accounting_shadow_members
               WHERE run_id=? AND batch_id=? ORDER BY member_key""",
            (run_id, batch_id),
        ).fetchall()
        lines = db.execute(
            """SELECT line_no,side,amount_krw,payment_id,account_code,
                      accounting_period,posting_date,ledger_currency,
                      currency_evidence_sha256,provenance_sha256,line_sha256
               FROM direct_accounting_shadow_lines
               WHERE run_id=? AND batch_id=? ORDER BY line_no""",
            (run_id, batch_id),
        ).fetchall()
        if len(members) != int(row[11]) or len(lines) != int(row[12]):
            issues.append(f"shadow_batch_cardinality:{batch_id}")
        if len(lines) != len(members) * 2:
            issues.append(f"shadow_batch_not_two_lines_per_member:{batch_id}")
        debit = sum(int(item[2]) for item in lines if str(item[1]) == "debit")
        credit = sum(int(item[2]) for item in lines if str(item[1]) == "credit")
        if debit != credit or debit != int(row[9]):
            issues.append(f"shadow_batch_unbalanced_lines:{batch_id}")
        if any(int(item[2]) <= 0 or str(item[7]) != LEDGER_CURRENCY for item in lines):
            issues.append(f"shadow_line_amount_or_currency_invalid:{batch_id}")
        if len({str(item[0]) for item in lines}) != len(lines):
            issues.append(f"shadow_line_number_duplicate:{batch_id}")
    selected_payment_ids = {
        int(row[0]) for row in db.execute(
            "SELECT DISTINCT payment_id FROM direct_accounting_shadow_members WHERE run_id=?",
            (run_id,),
        ).fetchall()
    }
    family_payment_rows = db.execute(
        """SELECT family_id,payment_id
           FROM direct_accounting_shadow_members
           WHERE run_id=?
           GROUP BY family_id,payment_id
           ORDER BY family_id,payment_id""",
        (run_id,),
    ).fetchall()
    family_payment_sets: dict[str, set[int]] = defaultdict(set)
    for family_id, payment_id in family_payment_rows:
        family_payment_sets[str(family_id)].add(int(payment_id))
    seen_family_payment_ids: set[int] = set()
    for family_id, payment_ids in sorted(family_payment_sets.items()):
        if seen_family_payment_ids & payment_ids:
            issues.append(f"shadow_family_payment_overlap:{family_id}")
        seen_family_payment_ids |= payment_ids
    if seen_family_payment_ids != selected_payment_ids:
        issues.append("shadow_selected_payment_partition_invalid")
    if mode == "with_2026_clearing":
        rows = db.execute(
            """SELECT payload_json
               FROM direct_accounting_shadow_members
               WHERE run_id=? AND family_id=?""",
            (run_id, FAMILY_2026_CLEARING),
        ).fetchall()
        for (payload_json,) in rows:
            try:
                payload = json.loads(str(payload_json))
                provenance_payload = payload.get("provenance_payload", {})
            except (TypeError, json.JSONDecodeError):
                provenance_payload = {}
            if any(
                str(provenance_payload.get(field) or "")
                for field in ("service_period", "trip_code", "reservation_number")
            ):
                issues.append("shadow_2026_travel_fields_not_blank")
                break
    legacy_count = db.execute(
        """SELECT COUNT(*) FROM journal_entries j
           JOIN cost_allocations ca ON ca.id=j.allocation_id
           JOIN allocation_plans ap ON ap.id=ca.plan_id
           WHERE ap.payment_id IN (%s)""" % (
               ",".join("?" for _ in selected_payment_ids) or "NULL"
           ),
        tuple(sorted(selected_payment_ids)),
    ).fetchone()[0]
    if int(legacy_count):
        issues.append("shadow_legacy_journal_side_effect")
    payload = json.loads(str(manifest[11]))
    if payload.get("posting_status") != "shadow_only":
        issues.append("shadow_posting_status_invalid")
    if payload.get("external_posting") is not False:
        issues.append("shadow_external_posting_not_false")
    result = {
        "passed": not issues,
        "issues": issues,
        "run_id": run_id,
        "mode": mode,
        "selected_payment_count": int(manifest[2]),
        "batch_count": len(batches),
        "member_count": sum(
            int(row[0]) for row in db.execute(
                "SELECT COUNT(*) FROM direct_accounting_shadow_members WHERE run_id=?",
                (run_id,),
            ).fetchall()
        ),
        "line_count": sum(
            int(row[0]) for row in db.execute(
                "SELECT COUNT(*) FROM direct_accounting_shadow_lines WHERE run_id=?",
                (run_id,),
            ).fetchall()
        ),
        "legacy_journal_count": int(legacy_count),
        "shadow_only": True,
        "manifest_family_set_sha256": str(manifest[6]),
        "manifest_membership_sha256": str(manifest[7]),
        "manifest_policy_sha256": str(manifest[8]),
        "manifest_mapping_sha256": str(manifest[9]),
    }
    return result


def promote_shadow_to_posting(
    db: sqlite3.Connection,
    run_id: str,
    *,
    mode: str,
    approved_rule_ids: Iterable[str] = (),
    release_ready: bool = False,
    production_account_mapping: Mapping[str, str] | None = None,
    authorize: bool = False,
    family_approval_attestation: Mapping[str, object] | None = None,
    release_attestation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Copy a validated shadow into a local posting candidate.

    This is deliberately separate from :func:`build_shadow_accounting`.
    ``authorize=False`` creates only ``candidate`` rows.  Even
    ``authorize=True`` writes ``posted_shadow`` rows in this isolated
    accounting table; it never writes the legacy ``journal_entries`` table or
    sends anything to an external accounting system.  A production caller
    must still provide a content-addressed family approval, a real
    chart-of-accounts mapping, and a content-addressed release attestation.
    """
    apply_shadow_schema(db)
    apply_posting_schema(db)
    shadow_validation = validate_shadow_accounting(db, run_id, mode=mode)
    if not shadow_validation.get("passed"):
        return {
            "passed": False,
            "status": "blocked",
            "reason": "shadow_validation_failed",
            "shadow": shadow_validation,
            "posted_payment_count": 0,
            "external_posting": False,
        }
    manifest = db.execute(
        """SELECT mode,schema_version,selected_payment_count,batch_count,member_count,
                  line_count,family_set_sha256,membership_sha256,policy_sha256,
                  ledger_mapping_sha256,status,payload_json
           FROM direct_accounting_shadow_manifests
           WHERE run_id=? AND mode=?""",
        (run_id, mode),
    ).fetchone()
    if manifest is None:
        return {
            "passed": False,
            "status": "blocked",
            "reason": "shadow_manifest_missing",
            "posted_payment_count": 0,
            "external_posting": False,
        }
    approved = {str(value) for value in approved_rule_ids}
    shadow_rule_ids = {
        str(row[0]) for row in db.execute(
            "SELECT DISTINCT rule_id FROM direct_accounting_shadow_batches "
            "WHERE run_id=? ORDER BY rule_id",
            (run_id,),
        ).fetchall()
    }
    mapping = {
        str(key): str(value)
        for key, value in dict(production_account_mapping or {}).items()
    }
    source_accounts = {
        str(row[0]) for row in db.execute(
            "SELECT DISTINCT account_code FROM direct_accounting_shadow_lines "
            "WHERE run_id=? ORDER BY account_code",
            (run_id,),
        ).fetchall()
    }
    approval_sha = _sha(sorted(approved))
    mapping_sha = _sha(mapping)
    source_manifest_sha = _sha([list(manifest)])
    blocked_reasons: list[str] = []
    if not shadow_rule_ids <= approved:
        blocked_reasons.append("family_approval_missing")
    if not source_accounts <= set(mapping):
        blocked_reasons.append("production_chart_mapping_missing")
    if any(not mapping.get(account, "").strip() for account in source_accounts):
        blocked_reasons.append("production_chart_mapping_blank")
    approval_attestation = dict(family_approval_attestation or {})
    approval_attestation_payload = {
        "run_id": run_id,
        "mode": mode,
        "approved_rule_ids": sorted(approved),
        "approval_status": approval_attestation.get("approval_status"),
        "decision_id": approval_attestation.get("decision_id"),
    }
    approval_attestation_valid = bool(
        approval_attestation.get("approval_status") == "approved"
        and approval_attestation.get("run_id") == run_id
        and approval_attestation.get("mode") == mode
        and approval_attestation.get("approved_rule_ids") == sorted(approved)
        and str(approval_attestation.get("approval_sha256") or "")
        == _sha(approval_attestation_payload)
    )
    release_attestation_payload = dict(release_attestation or {})
    release_hash = release_attestation_payload.pop("attestation_sha256", None)
    release_attestation_valid = bool(
        release_attestation_payload.get("run_id") == run_id
        and release_attestation_payload.get("mode") == mode
        and release_attestation_payload.get("release_ready") is True
        and release_attestation_payload.get("gate5_pass") is True
        and release_attestation_payload.get("gate6_pass") is True
        and release_attestation_payload.get("han_equal") is True
        and str(release_hash or "") == _sha(release_attestation_payload)
    )
    if authorize and not approval_attestation_valid:
        blocked_reasons.append("family_approval_attestation_missing_or_invalid")
    if authorize and not release_attestation_valid:
        blocked_reasons.append("release_attestation_missing_or_invalid")
    if release_ready and not release_attestation_valid:
        blocked_reasons.append("release_attestation_missing_or_invalid")
    effective_release_ready = release_attestation_valid
    if not authorize and release_ready:
        # A release-ready check without the explicit local promotion switch is
        # still a candidate; it must never silently become posted_shadow.
        pass
    legacy_journal_count = 0
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_entries'"
    ).fetchone() is not None:
        legacy_journal_count = int(db.execute(
            "SELECT COUNT(*) FROM journal_entries"
        ).fetchone()[0])
    if legacy_journal_count:
        blocked_reasons.append("legacy_journal_not_empty")
    blocked_reasons = list(dict.fromkeys(blocked_reasons))
    status = "posted_shadow" if authorize and not blocked_reasons else (
        "candidate" if not blocked_reasons else "blocked"
    )
    selected_payment_count = int(manifest[2])
    existing_posting = db.execute(
        """SELECT posting_status,selected_payment_count,batch_count,line_count,
                  approval_sha256,mapping_sha256
           FROM direct_accounting_posting_manifests
           WHERE run_id=? AND mode=?""",
        (run_id, mode),
    ).fetchone()
    if existing_posting is not None and not blocked_reasons:
        same_contract = (
            str(existing_posting[4]) == approval_sha
            and str(existing_posting[5]) == mapping_sha
        )
        if same_contract and str(existing_posting[0]) == status:
            return {
                "passed": True,
                "status": str(existing_posting[0]),
                "selected_payment_count": int(existing_posting[1]),
                "candidate_payment_count": (
                    int(existing_posting[1])
                    if str(existing_posting[0]) == "candidate" else 0
                ),
                "posted_payment_count": (
                    int(existing_posting[1])
                    if str(existing_posting[0]) == "posted_shadow" else 0
                ),
                "batch_count": int(existing_posting[2]),
                "line_count": int(existing_posting[3]),
                "approval_sha256": approval_sha,
                "mapping_sha256": mapping_sha,
                "external_posting": False,
                "legacy_journal_count": legacy_journal_count,
                "idempotent_replay": True,
            }
        if not same_contract:
            raise ValueError("posting_contract_conflict_on_rerun")
        raise ValueError("posting_status_conflict_on_rerun")
    if blocked_reasons:
        payload = {
            "schema_version": SHADOW_SCHEMA_VERSION,
            "run_id": run_id,
            "mode": mode,
            "posting_status": status,
            "blocked_reasons": blocked_reasons,
            "approved_rule_ids": sorted(approved),
            "shadow_rule_ids": sorted(shadow_rule_ids),
            "release_ready": bool(release_ready),
            "authorize": bool(authorize),
            "family_approval_attestation_valid": approval_attestation_valid,
            "release_attestation_valid": release_attestation_valid,
            "external_posting": False,
            "selected_payment_count": selected_payment_count,
        }
        db.execute(
            """INSERT INTO direct_accounting_posting_manifests(
                 run_id,mode,posting_status,selected_payment_count,batch_count,
                 line_count,approval_sha256,mapping_sha256,
                 source_shadow_manifest_sha256,release_ready,external_posting,
                 payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id,mode) DO UPDATE SET
                 posting_status=excluded.posting_status,
                 selected_payment_count=excluded.selected_payment_count,
                 batch_count=excluded.batch_count,line_count=excluded.line_count,
                 approval_sha256=excluded.approval_sha256,
                 mapping_sha256=excluded.mapping_sha256,
                 source_shadow_manifest_sha256=excluded.source_shadow_manifest_sha256,
                 release_ready=excluded.release_ready,
                 external_posting=excluded.external_posting,
                 payload_json=excluded.payload_json""",
            (
                run_id,mode,status,selected_payment_count,0,0,approval_sha,
                mapping_sha,source_manifest_sha,int(effective_release_ready),0,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        db.commit()
        return {
            "passed": False,
            "status": "blocked",
            "reason": blocked_reasons[0],
            "blocked_reasons": blocked_reasons,
            "selected_payment_count": selected_payment_count,
            "posted_payment_count": 0,
            "external_posting": False,
            "approval_sha256": approval_sha,
            "mapping_sha256": mapping_sha,
        }
    shadow_batches = db.execute(
        """SELECT batch_id,family_id,accounting_period,posting_date,
                  debit_total_krw,credit_total_krw,member_count,line_count,
                  provenance_sha256
           FROM direct_accounting_shadow_batches
           WHERE run_id=? ORDER BY batch_id""",
        (run_id,),
    ).fetchall()
    db.execute("BEGIN")
    try:
        posting_batch_count = 0
        posting_line_count = 0
        for shadow_batch in shadow_batches:
            shadow_batch_id = str(shadow_batch[0])
            posting_batch_id = _sha({
                "run_id": run_id,
                "mode": mode,
                "shadow_batch_id": shadow_batch_id,
                "approval_sha256": approval_sha,
                "mapping_sha256": mapping_sha,
            })
            idempotency_key = f"posting:{SHADOW_SCHEMA_VERSION}:{posting_batch_id}"
            lines = db.execute(
                """SELECT line_no,side,account_code,amount_krw,payment_id,
                          source_component_key,line_sha256,accounting_period,
                          posting_date,ledger_currency,payload_json
                   FROM direct_accounting_shadow_lines
                   WHERE run_id=? AND batch_id=? ORDER BY line_no""",
                (run_id, shadow_batch_id),
            ).fetchall()
            mapped_lines: list[dict[str, object]] = []
            for line in lines:
                source_account = str(line[2])
                account_code = mapping[source_account]
                line_payload = {
                    "run_id": run_id,
                    "posting_batch_id": posting_batch_id,
                    "line_no": int(line[0]),
                    "side": str(line[1]),
                    "account_code": account_code,
                    "source_account_code": source_account,
                    "amount_krw": int(line[3]),
                    "payment_id": int(line[4]),
                    "source_component_key": str(line[5]),
                    "source_shadow_line_sha256": str(line[6]),
                    "accounting_period": str(line[7]),
                    "posting_date": str(line[8]),
                    "ledger_currency": str(line[9]),
                }
                line_payload["line_sha256"] = _sha(line_payload)
                mapped_lines.append(line_payload)
            payload = {
                "schema_version": SHADOW_SCHEMA_VERSION,
                "posting_batch_id": posting_batch_id,
                "shadow_batch_id": shadow_batch_id,
                "family_id": str(shadow_batch[1]),
                "posting_status": status,
                "approval_sha256": approval_sha,
                "mapping_sha256": mapping_sha,
                "source_provenance_sha256": str(shadow_batch[8]),
                "external_posting": False,
            }
            db.execute(
                """INSERT INTO direct_accounting_posting_batches(
                     run_id,posting_batch_id,shadow_batch_id,family_id,posting_status,
                     accounting_period,posting_date,ledger_currency,debit_total_krw,
                     credit_total_krw,member_count,line_count,approval_sha256,
                     mapping_sha256,source_provenance_sha256,idempotency_key,payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,posting_batch_id,shadow_batch_id,str(shadow_batch[1]),status,
                    str(shadow_batch[2]),str(shadow_batch[3]),LEDGER_CURRENCY,
                    int(shadow_batch[4]),int(shadow_batch[5]),int(shadow_batch[6]),
                    len(mapped_lines),approval_sha,mapping_sha,str(shadow_batch[8]),
                    idempotency_key,json.dumps(payload,ensure_ascii=False,sort_keys=True),
                ),
            )
            for line in mapped_lines:
                db.execute(
                    """INSERT INTO direct_accounting_posting_lines(
                         run_id,posting_batch_id,line_no,side,account_code,
                         source_account_code,amount_krw,payment_id,
                         source_component_key,source_shadow_line_sha256,
                         accounting_period,posting_date,ledger_currency,line_sha256,
                         payload_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id,posting_batch_id,int(line["line_no"]),str(line["side"]),
                        str(line["account_code"]),str(line["source_account_code"]),
                        int(line["amount_krw"]),int(line["payment_id"]),
                        str(line["source_component_key"]),
                        str(line["source_shadow_line_sha256"]),
                        str(line["accounting_period"]),str(line["posting_date"]),
                        LEDGER_CURRENCY,str(line["line_sha256"]),
                        json.dumps(line,ensure_ascii=False,sort_keys=True),
                    ),
                )
            posting_batch_count += 1
            posting_line_count += len(mapped_lines)
        payload = {
            "schema_version": SHADOW_SCHEMA_VERSION,
            "run_id": run_id,
            "mode": mode,
            "posting_status": status,
            "selected_payment_count": selected_payment_count,
            "batch_count": posting_batch_count,
            "line_count": posting_line_count,
            "approval_sha256": approval_sha,
            "mapping_sha256": mapping_sha,
            "source_shadow_manifest_sha256": source_manifest_sha,
                    "release_ready": bool(effective_release_ready),
            "authorize": bool(authorize),
            "external_posting": False,
        }
        db.execute(
            """INSERT INTO direct_accounting_posting_manifests(
                 run_id,mode,posting_status,selected_payment_count,batch_count,
                 line_count,approval_sha256,mapping_sha256,
                 source_shadow_manifest_sha256,release_ready,external_posting,
                 payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id,mode) DO UPDATE SET
                 posting_status=excluded.posting_status,
                 selected_payment_count=excluded.selected_payment_count,
                 batch_count=excluded.batch_count,line_count=excluded.line_count,
                 approval_sha256=excluded.approval_sha256,
                 mapping_sha256=excluded.mapping_sha256,
                 source_shadow_manifest_sha256=excluded.source_shadow_manifest_sha256,
                 release_ready=excluded.release_ready,
                 external_posting=excluded.external_posting,
                 payload_json=excluded.payload_json""",
            (
                run_id,mode,status,selected_payment_count,posting_batch_count,
                posting_line_count,approval_sha,mapping_sha,source_manifest_sha,
                int(effective_release_ready),0,
                json.dumps(payload,ensure_ascii=False,sort_keys=True),
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "passed": True,
        "status": status,
        "selected_payment_count": selected_payment_count,
        "candidate_payment_count": (
            selected_payment_count if status == "candidate" else 0
        ),
        "posted_payment_count": (
            selected_payment_count if status == "posted_shadow" else 0
        ),
        "batch_count": posting_batch_count,
        "line_count": posting_line_count,
        "approval_sha256": approval_sha,
        "mapping_sha256": mapping_sha,
        "external_posting": False,
        "legacy_journal_count": legacy_journal_count,
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--include-2026-clearing", action="store_true")
    args = parser.parse_args()
    db = sqlite3.connect(args.db)
    try:
        result = build_shadow_accounting(
            db, args.run_id, include_2026_clearing=args.include_2026_clearing,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result.get("passed") else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(_main())
