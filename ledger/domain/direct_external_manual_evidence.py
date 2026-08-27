"""Build a content-bound, non-authoritative latest-manual evidence annex."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity

from ledger.domain.direct_lineage_annex import (
    CLASSIFIED_SHA256,
    _build_temp_db,
    _install_noreplace,
    build_annex,
)
from ledger.domain.direct_projection import REPOSITORY_ROOT, candidate_semantic_snapshot
from ledger.domain.transition_gates_v2 import input_manifest_sha256

ARTIFACT_TYPE = "direct-external-manual-evidence-v1"
RULE_VERSION = "exact-source-date-signed-amount-bilateral-v1"
CSV_HEADER = ("tab", "row", "date", "item", "desc", "card", "amount", "book")
ISSUERS = {"국민": ("KBD", "KBO"), "하나": ("HAN",), "기업": ("CORP",)}
PROVIDER_ALIASES = {
    "agoda": ("AGODA", "아고다"),
    "booking.com": ("BOOKINGCOM", "부킹닷컴"),
    "gotogate": ("GOTOGATE", "고투게이트"),
    "jejuair": ("JEJUAIR", "제주항공"),
    "koreanair": ("KOREANAIR", "대한항공"),
    "mytrip": ("MYTRIP", "마이트립"),
    "trip.com": ("TRIPCOM", "트립닷컴"),
}
ALIAS_CONTRACT_VERSION = "provider-alias-v1"
ALIAS_CONTRACT_SHA256 = ""
FILES = ("manifest.json", "proposals.csv", "conflicts.csv", "groups.csv", "diagnostics.csv", "evidence_sets.csv")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


ALIAS_CONTRACT_SHA256 = _sha(_json({"version": ALIAS_CONTRACT_VERSION, "aliases": PROVIDER_ALIASES}))
RULE_SHA256 = _sha(_json({"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION, "alias_contract_sha256": ALIAS_CONTRACT_SHA256, "signed_amount": True, "bilateral": True, "merchant_is_support_only": True, "physical_row_single_use": True}))


def _norm(value: object) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", str(value or "")).upper() if char.isalnum())


def _date(value: str) -> str:
    text = value.strip()
    parts = text.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts) or tuple(map(len, parts)) != (2, 2, 2):
        raise ValueError("r25_manual_date_invalid")
    try:
        return date(2000 + int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except ValueError as exc:
        raise ValueError("r25_manual_date_invalid") from exc


def _amount(value: str) -> int:
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("r25_manual_amount_invalid") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError("r25_manual_amount_invalid")
    return int(number)


def _provider(value: object) -> str:
    text = _norm(value)
    found = [name for name, tokens in PROVIDER_ALIASES.items() if any(_norm(token) in text for token in tokens)]
    return found[0] if len(found) == 1 else ""


def _merchant_compatible(current: object, manual: object) -> bool:
    left, right = _norm(current), _norm(manual)
    if not left or not right: return False
    if left == right or (min(len(left), len(right)) >= 4 and (left in right or right in left)): return True
    left_provider, right_provider = _provider(current), _provider(manual)
    return bool(left_provider and left_provider == right_provider)


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) if isinstance(value, (dict, list)) else str(value).lower() if isinstance(value, bool) else "" if value is None else value for key, value in row.items()})
    return stream.getvalue().encode()


PROPOSAL_COLUMNS = (
    "proposal_id", "direct_event_key", "current_event_sha256", "source_system", "occurred_on",
    "signed_amount_krw", "event_role", "transaction_type", "merchant", "posted_on", "approval_number",
    "card4", "currency", "foreign_amount", "current_source_kind",
    "current_source_key", "current_source_sha256", "manual_locator", "manual_row_sha256", "manual_tab",
    "manual_row", "manual_date", "manual_item", "manual_description", "manual_card", "manual_amount_raw",
    "booking_reference", "match_rule", "merchant_exact", "merchant_containment", "booking_ref_exact",
    "booking_ref_unique", "merchant_provider_current", "merchant_provider_manual", "merchant_alias_compatible",
    "merchant_conflict", "disposition", "authority_status", "posting_status", "gate5_credit",
)
CONFLICT_COLUMNS = (
    "conflict_id", "direct_event_key", "current_event_sha256", "historical_uid", "historical_bucket",
    "historical_proposal_json", "historical_row_sha256", "manual_tab", "manual_locator", "manual_row_sha256",
    "manual_row_json", "current_source_kind", "current_source_key", "current_source_sha256", "current_merchant",
    "transaction_type", "event_role", "signed_amount_krw", "cancellation_event", "conflict_type", "disposition",
)
GROUP_COLUMNS = (
    "group_id", "group_type", "compound_key_json", "current_event_keys_json", "manual_locators_json",
    "current_cardinality", "manual_cardinality", "current_signed_total", "manual_signed_total", "disposition",
)
DIAGNOSTIC_COLUMNS = ("diagnostic_id", "diagnostic_type", "manual_locator", "manual_row_sha256", "reason", "payload_json", "disposition")
EVIDENCE_SET_COLUMNS = ("direct_event_key", "current_event_sha256", "evidence_tier", "relation_kind", "manual_188_member", "authority_status", "posting_status", "gate5_credit", "disposition")


def _manual(path: Path) -> tuple[bytes, list[dict[str, object]], list[dict[str, object]]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("r25_manual_not_regular")
    raw = path.read_bytes()
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CSV_HEADER:
            raise ValueError("r25_manual_header_invalid")
        source_rows = [dict(row) for row in reader]
    seen: set[str] = set(); rows: list[dict[str, object]] = []; malformed: list[dict[str, object]] = []
    for raw_row in source_rows:
        locator = f"{raw_row['tab'].strip()}:{raw_row['row'].strip()}"
        if not raw_row["tab"].strip() or not raw_row["row"].strip() or locator in seen:
            raise ValueError("r25_manual_locator_invalid")
        seen.add(locator)
        canonical = {key: str(raw_row[key]) for key in CSV_HEADER}
        row_hash = _sha(_json(canonical))
        try:
            occurred = _date(raw_row["date"])
            amount = _amount(raw_row["amount"])
        except ValueError as exc:
            malformed.append({"locator": locator, "row_sha256": row_hash, "reason": str(exc), "raw": canonical}); continue
        rows.append({**canonical, "locator": locator, "occurred_on": occurred, "amount_krw": amount, "row_sha256": row_hash})
    rows.sort(key=lambda row: (str(row["tab"]), str(row["row"]), str(row["row_sha256"])))
    malformed.sort(key=lambda row: str(row["locator"]))
    return raw, rows, malformed


def _ota_refs(ledger_dir: Path) -> tuple[set[str], set[str]]:
    payload = json.loads((ledger_dir / "data/ota_mail_index.json").read_text(encoding="utf-8"))
    counts: Counter[str] = Counter()
    for record in payload.get("records", []):
        for value in list(record.get("bookingRefs", [])) + list(record.get("pnrs", [])):
            if str(value).strip(): counts[_norm(value)] += 1
    return set(counts), {key for key, count in counts.items() if count == 1}


def _independent_manual_sets(events: list[dict[str, object]], manual_rows: list[dict[str, object]], blocked_ids: set[str]) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    """Independently rebuild alias and exact-merchant bilateral edge sets."""
    expanded = []
    for row in manual_rows:
        for source in ISSUERS.get(str(row["card"]).strip(), ()):
            expanded.append((source, row))

    def isolate(compatible) -> dict[str, dict[str, object]]:
        edges = []
        for event in events:
            event_id = str(event["direct_event_key"])
            if event_id not in blocked_ids: continue
            for source, row in expanded:
                if source == event["source_system"] and row["occurred_on"] == event["occurred_on"] and row["amount_krw"] == event["signed_amount_krw"] and compatible(event["merchant"], row["item"]):
                    edges.append((event_id, row))
        event_degree = Counter(event_id for event_id, _ in edges)
        locator_degree = Counter(str(row["locator"]) for _, row in edges)
        return {event_id: row for event_id, row in edges if event_degree[event_id] == 1 and locator_degree[str(row["locator"])] == 1}

    alias = isolate(_merchant_compatible)
    exact = isolate(lambda current, manual: bool(_norm(current)) and _norm(current) == _norm(manual))
    return alias, exact


def _bucket(value: object) -> str:
    return "기타비용" if str(value or "") == "2분기_기타비용" else str(value or "")


def _context(ledger_dir: Path, root: Path) -> dict[str, object]:
    db, run_id, inventory, eventset, scope, current_hashes = _build_temp_db(ledger_dir, root)
    rows = db.execute("""
      SELECT d.card_event_id,d.event_role,p.source_system,p.occurred_on,d.amount_krw,
             p.transaction_type,p.merchant,s.source_kind,s.source_key,s.source_sha256,
             s.payload_json,p.posted_on,p.approval_number,pm.last4
      FROM direct_payment_projection_links l
      JOIN payment_transactions p ON p.id=l.payment_id
      JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
      JOIN direct_source_records s ON s.id=d.source_record_id
      LEFT JOIN payment_methods pm ON pm.id=p.payment_method_id
      WHERE l.run_id=? ORDER BY d.card_event_id,d.event_role
    """, (run_id,)).fetchall()
    items = []
    for row in rows:
        key = f"{row[0]}#{row[1]}"
        payload = json.loads(row[10])
        items.append({"direct_event_key": key, "current_event_sha256": current_hashes[key], "event_role": row[1], "source_system": row[2], "occurred_on": payload.get("use_date") or row[3], "posted_on": payload.get("post_date") or row[11], "signed_amount_krw": int(row[4]), "transaction_type": row[5], "merchant": payload.get("merchant") or row[6], "approval_number": payload.get("appr") or row[12], "card4": payload.get("card4") or row[13], "currency": payload.get("currency") or "", "foreign_amount": payload.get("foreign") or "", "current_source_kind": row[7], "current_source_key": row[8], "current_source_sha256": row[9]})
    result = {"db": db, "run_id": run_id, "inventory": inventory, "input_manifest_sha256": input_manifest_sha256(inventory), "candidate_semantic_sha256": candidate_semantic_snapshot(db, run_id), "current_event_set_sha256": eventset, "decision_scope_sha256": scope, "events": items}
    return result


def _digits(value: object) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _approval(value: object) -> str:
    return _digits(value).lstrip("0")


def _decimal_text(value: object) -> str:
    text = str(value or "").replace(",", "").strip()
    if not text: return ""
    try: return format(Decimal(text).normalize(), "f")
    except InvalidOperation: return text


def _historical_rows(ledger_dir: Path) -> list[dict[str, object]]:
    with (ledger_dir / "data/classified_v14.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = [dict(row) for row in csv.DictReader(stream) if row.get("src") in {"KBD", "KBO", "HAN", "CORP"}]
    for row in rows:
        amount = int(row.get("krw") or 0)
        if row["src"] in {"KBO", "CORP"} and str(row.get("cancel")).lower() == "true": amount = -abs(amount)
        row["_amount"] = amount
    return rows


def _require_same_event_set(left: set[str], right: set[str]) -> None:
    if left != right:
        raise ValueError("r25_signed_exact_merchant_set_mismatch")


def _evidence_overlap_sets(events: list[dict[str, object]], old: dict[str, dict[str, object]], ledger_dir: Path) -> dict[str, set[str]]:
    """Recompute accepted R25 tier sets with stable event/UID identifiers."""
    historical = _historical_rows(ledger_dir)
    blocked_ids = {key for key, row in old.items() if row["lineage_tier"] == "unmatched"}
    blocked = [event for event in events if event["direct_event_key"] in blocked_ids]
    consumed_uids = {str(row["historical_uid"]) for row in old.values() if row["lineage_tier"] != "unmatched" and row.get("historical_uid")}
    free = {str(row["uid"]): row for row in historical if str(row.get("uid") or "") not in consumed_uids}
    remaining = {str(event["direct_event_key"]): event for event in blocked}
    clean: set[str] = set()

    def stage(history_key, current_key) -> None:
        history_groups: dict[object, list[str]] = defaultdict(list)
        for uid, row in free.items():
            key = history_key(row)
            if key is not None: history_groups[key].append(uid)
        current_groups: dict[object, list[str]] = defaultdict(list)
        for event_id, event in remaining.items():
            key = current_key(event)
            if key is not None: current_groups[key].append(event_id)
        chosen = []
        for key, event_ids in current_groups.items():
            uids = history_groups.get(key, [])
            if len(event_ids) == len(uids) == 1: chosen.append((event_ids[0], uids[0]))
        for event_id, uid in chosen:
            clean.add(event_id); remaining.pop(event_id); free.pop(uid)

    stage(
        lambda row: (row["src"], str(row.get("use_date") or ""), row["_amount"], _approval(row.get("appr")), _digits(row.get("card4"))[-4:]) if _approval(row.get("appr")) else None,
        lambda event: (event["source_system"], str(event["occurred_on"] or ""), event["signed_amount_krw"], _approval(event["approval_number"]), _digits(event["card4"])[-4:]) if _approval(event["approval_number"]) else None,
    )
    stage(
        lambda row: (row["src"], str(row.get("use_date") or ""), row["_amount"], _approval(row.get("appr"))) if _approval(row.get("appr")) and not _digits(row.get("card4")) else None,
        lambda event: (event["source_system"], str(event["occurred_on"] or ""), event["signed_amount_krw"], _approval(event["approval_number"])) if _approval(event["approval_number"]) else None,
    )
    stage(
        lambda row: (row["src"], str(row.get("use_date") or ""), row["_amount"], _approval(row.get("appr")), _digits(row.get("card4"))[-4:]) if _approval(row.get("appr")) else None,
        lambda event: (event["source_system"], str(event["posted_on"] or ""), event["signed_amount_krw"], _approval(event["approval_number"]), _digits(event["card4"])[-4:]) if _approval(event["approval_number"]) else None,
    )

    amount_conflicts: set[str] = set()
    for event_id, event in remaining.items():
        if not ("2026-04-01" <= str(event["occurred_on"]) <= "2026-06-30") or not _approval(event["approval_number"]): continue
        candidates = []
        for row in free.values():
            if row["src"] != event["source_system"] or _approval(row.get("appr")) != _approval(event["approval_number"]): continue
            if _digits(row.get("card4"))[-4:] not in {"", _digits(event["card4"])[-4:]}: continue
            try: distance = abs((date.fromisoformat(str(row.get("use_date"))) - date.fromisoformat(str(event["occurred_on"]))).days)
            except ValueError: continue
            delta = abs(int(row["_amount"]) - int(event["signed_amount_krw"]))
            if distance <= 1 and delta and delta <= max(300, abs(int(event["signed_amount_krw"])) * 0.035): candidates.append(row)
        if len(candidates) == 1: amount_conflicts.add(event_id)

    def exact_key_event(event: dict[str, object]) -> tuple[object, ...]:
        return (event["source_system"], str(event["occurred_on"]), int(event["signed_amount_krw"]), _digits(event["approval_number"]), _digits(event["card4"])[-4:])
    def exact_key_history(row: dict[str, object]) -> tuple[object, ...]:
        return (row["src"], str(row.get("use_date") or ""), int(row["_amount"]), _digits(row.get("appr")), _digits(row.get("card4"))[-4:])
    cg: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list); hg: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for event in events: cg[exact_key_event(event)].append(event)
    for row in historical: hg[exact_key_history(row)].append(row)
    group_members: set[str] = set()
    proposal_fields = ("bucket", "account", "cost_type", "vat_tag", "confidence", "tax_conf")
    for key, current_rows in cg.items():
        history_rows = hg.get(key, [])
        if len(current_rows) > 1 and len(current_rows) == len(history_rows) and len({tuple(str(row.get(field) or "") for field in proposal_fields) for row in history_rows}) == 1:
            group_members.update(str(row["direct_event_key"]) for row in current_rows if str(row["direct_event_key"]) in blocked_ids)

    def normalized_current(event: dict[str, object]) -> dict[str, object]:
        return {"id": event["direct_event_key"], "src": event["source_system"], "date": str(event["occurred_on"] or ""), "bill": str(event["posted_on"] or ""), "amount": int(event["signed_amount_krw"]), "approval": _digits(event["approval_number"]), "card4": _digits(event["card4"])[-4:], "merchant": re.sub(r"\s+", " ", str(event["merchant"] or "")).strip().upper(), "currency": re.sub(r"\s+", " ", str(event["currency"] or "")).strip().upper(), "foreign": _decimal_text(event["foreign_amount"]), "kind": "purchase" if event["transaction_type"] == "purchase" else "cancellation"}
    def normalized_history(row: dict[str, object]) -> dict[str, object]:
        return {"id": str(row.get("uid") or ""), "src": row["src"], "date": str(row.get("use_date") or ""), "bill": str(row.get("post_date") or ""), "amount": int(row["_amount"]), "approval": _digits(row.get("appr")), "card4": _digits(row.get("card4"))[-4:], "merchant": re.sub(r"\s+", " ", str(row.get("merchant") or "")).strip().upper(), "currency": re.sub(r"\s+", " ", str(row.get("currency") or "")).strip().upper(), "foreign": _decimal_text(row.get("foreign")), "kind": "cancellation" if str(row.get("cancel")).lower() == "true" or int(row["_amount"]) < 0 else "purchase"}
    current_norm = [normalized_current(event) for event in blocked]
    history_norm = [normalized_history(row) for row in historical]
    typed_maps: list[dict[str, str]] = []
    specs = [
        (("src", "date", "approval", "card4", "kind"), lambda row: row["src"] != "KBO"),
        (("src", "approval", "card4", "kind"), lambda row: row["src"] != "KBO"),
        (("src", "date", "amount", "card4", "merchant", "kind"), lambda row: True),
        (("src", "bill", "amount", "card4", "merchant", "kind"), lambda row: True),
        (("src", "date", "card4", "currency", "foreign", "kind"), lambda row: row["src"] == "KBO"),
        (("src", "bill", "card4", "currency", "foreign", "kind"), lambda row: row["src"] == "KBO"),
        (("src", "date", "bill", "amount", "card4", "currency", "foreign", "merchant", "kind"), lambda row: row["src"] == "KBO"),
    ]
    for fields, predicate in specs:
        current_map: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list); history_map: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
        for row in current_norm:
            values = tuple(row[field] for field in fields)
            if predicate(row) and all(value not in ("", None) for value in values): current_map[values].append(row)
        for row in history_norm:
            values = tuple(row[field] for field in fields)
            if predicate(row) and all(value not in ("", None) for value in values): history_map[values].append(row)
        typed_maps.append({str(rows[0]["id"]): str(history_map[key][0]["id"]) for key, rows in current_map.items() if len(rows) == 1 and len(history_map.get(key, [])) == 1})
    by_event: dict[str, set[str]] = defaultdict(set)
    for mapping in typed_maps:
        for event_id, uid in mapping.items(): by_event[event_id].add(uid)
    typed_v14 = {event_id for event_id, uids in by_event.items() if len(uids) == 1}

    portal_rows = json.loads((ledger_dir / "data/ota_event_links_verified.json").read_text(encoding="utf-8"))
    portal_groups: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for uid, row in portal_rows.items():
        if all(row.get(field) not in ("", None) for field in ("card4", "currency", "foreign_amount")):
            portal_groups[("KBO", _digits(row["card4"])[-4:], str(row["currency"]).strip().upper(), _decimal_text(row["foreign_amount"]))].append(uid)
    portal_current: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for row in current_norm:
        if row["src"] == "KBO" and all(row[field] not in ("", None) for field in ("card4", "currency", "foreign")):
            portal_current[("KBO", str(row["card4"]), str(row["currency"]), str(row["foreign"]))].append(str(row["id"]))
    portal = {rows[0] for key, rows in portal_current.items() if len(rows) == 1 and len(portal_groups.get(key, [])) == 1}

    return {"clean_110": clean, "amount_conflict_21": amount_conflicts, "group_members_29": group_members, "typed_v14_65": typed_v14, "portal_1": portal}


def _build_package(manual_csv: Path, ledger_dir: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve():
        raise ValueError("r25_noncanonical_ledger")
    raw, manual_rows, malformed = _manual(manual_csv)
    with tempfile.TemporaryDirectory(prefix="r25-context-") as dirname:
        ctx = _context(ledger_dir, Path(dirname))
        try:
            annex = build_annex(ledger_dir=ledger_dir)
            old = {row["direct_event_key"]: row for row in annex["package"]["envelopes"]}
            refs, unique_refs = _ota_refs(ledger_dir)
            current_groups: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
            for event in ctx["events"]:
                current_groups[(str(event["source_system"]), str(event["occurred_on"]), int(event["signed_amount_krw"]))].append(event)
            manual_groups: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
            for row in manual_rows:
                for source in ISSUERS.get(str(row["card"]).strip(), ()):
                    manual_groups[(source, str(row["occurred_on"]), int(row["amount_krw"]))].append(row)
            edges = []
            all_keys = sorted(set(current_groups) | set(manual_groups))
            groups: list[dict[str, object]] = []
            for key in all_keys:
                currents, manuals = current_groups.get(key, []), manual_groups.get(key, [])
                if len(currents) == 1 and len(manuals) == 1:
                    edges.append((key, currents[0], manuals[0]))
                elif currents and manuals:
                    group_type = "both_duplicate" if len(currents) > 1 and len(manuals) > 1 else "current_duplicate" if len(currents) > 1 else "manual_duplicate"
                    payload = {"key": key, "current": sorted(str(x["direct_event_key"]) for x in currents), "manual": sorted(str(x["locator"]) for x in manuals)}
                    groups.append({"group_id": _sha(_json({"rule": RULE_SHA256, **payload})), "group_type": group_type, "compound_key_json": list(key), "current_event_keys_json": payload["current"], "manual_locators_json": payload["manual"], "current_cardinality": len(currents), "manual_cardinality": len(manuals), "current_signed_total": sum(int(x["signed_amount_krw"]) for x in currents), "manual_signed_total": sum(int(x["amount_krw"]) for x in manuals), "disposition": "group_evidence_no_row_lineage"})
            locator_edges: dict[str, list[tuple]] = defaultdict(list)
            event_edges: dict[str, list[tuple]] = defaultdict(list)
            for edge in edges:
                locator_edges[str(edge[2]["locator"])].append(edge); event_edges[str(edge[1]["direct_event_key"])].append(edge)
            reusable = {locator for locator, values in locator_edges.items() if len(values) > 1}
            reusable_events = {event for event, values in event_edges.items() if len(values) > 1}
            for locator in sorted(reusable):
                values = locator_edges[locator]; currents = [x[1] for x in values]; manuals = [values[0][2]]
                payload = {"locator": locator, "events": sorted(str(x["direct_event_key"]) for x in currents)}
                groups.append({"group_id": _sha(_json({"rule": RULE_SHA256, **payload})), "group_type": "expanded_locator_reuse", "compound_key_json": {"manual_locator": locator}, "current_event_keys_json": payload["events"], "manual_locators_json": [locator], "current_cardinality": len(currents), "manual_cardinality": 1, "current_signed_total": sum(int(x["signed_amount_krw"]) for x in currents), "manual_signed_total": int(manuals[0]["amount_krw"]), "disposition": "group_evidence_no_row_lineage"})
            proposals=[]; conflicts=[]; known_agreement=0; isolated_total=0; source_counts=Counter(); role_counts=Counter(); negative=0
            for _, event, manual in edges:
                if str(manual["locator"]) in reusable or str(event["direct_event_key"]) in reusable_events: continue
                isolated_total += 1
                previous = old[str(event["direct_event_key"])]
                if previous["lineage_tier"] != "unmatched":
                    historical_bucket = (previous.get("proposal") or {}).get("bucket")
                    if _bucket(historical_bucket) != _bucket(manual["tab"]):
                        historical_proposal = previous.get("proposal") or {}
                        conflicts.append({"conflict_id": _sha(_json({"rule": RULE_SHA256, "event": event["direct_event_key"], "manual": manual["row_sha256"]})), "direct_event_key": event["direct_event_key"], "current_event_sha256": event["current_event_sha256"], "historical_uid": previous.get("historical_uid"), "historical_bucket": historical_bucket, "historical_proposal_json": historical_proposal, "historical_row_sha256": previous.get("historical_row_sha256"), "manual_tab": manual["tab"], "manual_locator": manual["locator"], "manual_row_sha256": manual["row_sha256"], "manual_row_json": {key: manual[key] for key in CSV_HEADER}, "current_source_kind": event["current_source_kind"], "current_source_key": event["current_source_key"], "current_source_sha256": event["current_source_sha256"], "current_merchant": event["merchant"], "transaction_type": event["transaction_type"], "event_role": event["event_role"], "signed_amount_krw": event["signed_amount_krw"], "cancellation_event": event["transaction_type"] in {"cancellation", "refund"}, "conflict_type": "classification_target_conflict", "disposition": "needs_review_no_overwrite"})
                    else: known_agreement += 1
                    continue
                merchant_current, merchant_manual = _norm(event["merchant"]), _norm(manual["item"])
                merchant_exact = bool(merchant_current and merchant_current == merchant_manual)
                containment = bool(merchant_current and merchant_manual and min(len(merchant_current), len(merchant_manual)) >= 4 and (merchant_current in merchant_manual or merchant_manual in merchant_current))
                booking = str(manual["book"]).strip(); booking_norm = _norm(booking)
                current_provider, manual_provider = _provider(event["merchant"]), _provider(manual["item"])
                provider_conflict = bool(current_provider and manual_provider and current_provider != manual_provider)
                alias_compatible = _merchant_compatible(event["merchant"], manual["item"])
                source_counts[str(event["source_system"])] += 1; role_counts[str(event["event_role"])] += 1
                negative += int(event["signed_amount_krw"] < 0)
                proposals.append({"proposal_id": _sha(_json({"rule": RULE_SHA256, "event": event["direct_event_key"], "manual": manual["row_sha256"]})), **event, "manual_locator": manual["locator"], "manual_row_sha256": manual["row_sha256"], "manual_tab": manual["tab"], "manual_row": manual["row"], "manual_date": manual["date"], "manual_item": manual["item"], "manual_description": manual["desc"], "manual_card": manual["card"], "manual_amount_raw": manual["amount"], "booking_reference": booking, "match_rule": RULE_VERSION, "merchant_exact": merchant_exact, "merchant_containment": containment, "booking_ref_exact": bool(booking_norm and booking_norm in refs), "booking_ref_unique": bool(booking_norm and booking_norm in unique_refs), "merchant_provider_current": current_provider, "merchant_provider_manual": manual_provider, "merchant_alias_compatible": alias_compatible, "merchant_conflict": provider_conflict, "disposition": "needs_review_merchant_conflict" if provider_conflict else "manual_evidence_proposal", "authority_status": "unattested", "posting_status": "blocked", "gate5_credit": 0})
            proposals.sort(key=lambda row: str(row["direct_event_key"])); conflicts.sort(key=lambda row: str(row["direct_event_key"])); groups.sort(key=lambda row: str(row["group_id"]))
            blocked_ids = {key for key, row in old.items() if row["lineage_tier"] == "unmatched"}
            alias_set, exact_merchant_set = _independent_manual_sets(list(ctx["events"]), manual_rows, blocked_ids)
            proposal_event_ids = {str(row["direct_event_key"]) for row in proposals}
            diagnostics = [{"diagnostic_id": _sha(_json({"rule": RULE_SHA256, "manual": row["row_sha256"], "reason": row["reason"]})), "diagnostic_type": "malformed_manual_row", "manual_locator": row["locator"], "manual_row_sha256": row["row_sha256"], "reason": row["reason"], "payload_json": row["raw"], "disposition": "excluded_from_exact_join"} for row in malformed]
            for event_id in sorted(set(alias_set) - proposal_event_ids):
                row = alias_set[event_id]
                diagnostics.append({"diagnostic_id": _sha(_json({"rule": RULE_SHA256, "event": event_id, "manual": row["row_sha256"], "type": "alias_only"})), "diagnostic_type": "merchant_alias_only_not_primary", "manual_locator": row["locator"], "manual_row_sha256": row["row_sha256"], "reason": "primary_source_date_signed_amount_not_bilateral", "payload_json": {"direct_event_key": event_id, "alias_contract_sha256": ALIAS_CONTRACT_SHA256}, "disposition": "diagnostic_not_proposal"})
            diagnostics.sort(key=lambda row: str(row["diagnostic_id"]))
            proposal_bytes = _csv_bytes(PROPOSAL_COLUMNS, proposals); conflict_bytes = _csv_bytes(CONFLICT_COLUMNS, conflicts); group_bytes = _csv_bytes(GROUP_COLUMNS, groups); diagnostic_bytes = _csv_bytes(DIAGNOSTIC_COLUMNS, diagnostics)
            manual_canonical = _sha(b"".join(_json({key: row[key] for key in CSV_HEADER}) for row in manual_rows))
            r23_unmatched = sum(row["lineage_tier"] == "unmatched" for row in old.values())
            exact_event_ids = {str(row["direct_event_key"]) for row in proposals if row["merchant_exact"]}
            _require_same_event_set(set(exact_merchant_set), exact_event_ids)
            evidence_sets = _evidence_overlap_sets(list(ctx["events"]), old, ledger_dir)
            evidence_sets["manual_signed_exact_19"] = set(exact_merchant_set)
            set_counts = {name: len(values) for name, values in evidence_sets.items()}
            intersections = {f"manual_188_intersect_{name}": len(proposal_event_ids & values) for name, values in evidence_sets.items()}
            individual_union = proposal_event_ids | evidence_sets["clean_110"] | evidence_sets["typed_v14_65"] | evidence_sets["portal_1"]
            current_hashes = {str(row["direct_event_key"]): str(row["current_event_sha256"]) for row in ctx["events"]}
            evidence_rows = []
            for tier, event_ids in evidence_sets.items():
                relation_kind = "individual_proposal" if tier in {"clean_110", "typed_v14_65", "portal_1", "manual_signed_exact_19"} else "amount_conflict" if tier == "amount_conflict_21" else "group_relation"
                for event_id in event_ids:
                    evidence_rows.append({"direct_event_key": event_id, "current_event_sha256": current_hashes[event_id], "evidence_tier": tier, "relation_kind": relation_kind, "manual_188_member": event_id in proposal_event_ids, "authority_status": "unattested", "posting_status": "blocked", "gate5_credit": 0, "disposition": "diagnostic_event_id_export"})
            evidence_rows.sort(key=lambda row: (str(row["direct_event_key"]), str(row["evidence_tier"])))
            evidence_bytes = _csv_bytes(EVIDENCE_SET_COLUMNS, evidence_rows)
            counts = {"manual_rows": len(manual_rows), "malformed_rows": len(malformed), "isolated_total": isolated_total, "known_agreement": known_agreement, "classification_conflicts": len(conflicts), "r23_unmatched": r23_unmatched, "new_proposals": len(proposals), "remaining_r23_unmatched": r23_unmatched-len(proposals), "individual_proposal_event_union": len(individual_union), "remaining_after_individual_proposal_union": r23_unmatched-len(individual_union), "group_rows": len(groups), "merchant_exact": len(exact_event_ids), "independent_signed_exact_merchant": len(exact_merchant_set), "signed_exact_merchant_set_equal": set(exact_merchant_set) == exact_event_ids, "merchant_alias_bilateral": len(alias_set), "merchant_alias_intersect_primary": len(set(alias_set) & proposal_event_ids), "merchant_alias_only_not_primary": len(set(alias_set) - proposal_event_ids), "merchant_containment": sum(bool(x["merchant_containment"]) for x in proposals), "merchant_alias_compatible_within_188": sum(bool(x["merchant_alias_compatible"]) for x in proposals), "merchant_conflicts": sum(bool(x["merchant_conflict"]) for x in proposals), "booking_present": sum(bool(x["booking_reference"]) for x in proposals), "booking_ref_exact": sum(bool(x["booking_ref_exact"]) for x in proposals), "booking_ref_unique": sum(bool(x["booking_ref_unique"]) for x in proposals), "negative_proposals": negative, "source_counts": dict(sorted(source_counts.items())), "role_counts": dict(sorted(role_counts.items())), "evidence_set_counts": set_counts, "event_id_intersections": intersections}
            file_meta = {"proposals.csv": {"sha256": _sha(proposal_bytes), "rows": len(proposals)}, "conflicts.csv": {"sha256": _sha(conflict_bytes), "rows": len(conflicts)}, "groups.csv": {"sha256": _sha(group_bytes), "rows": len(groups)}, "diagnostics.csv": {"sha256": _sha(diagnostic_bytes), "rows": len(diagnostics)}, "evidence_sets.csv": {"sha256": _sha(evidence_bytes), "rows": len(evidence_rows)}}
            base = {"format_version": 1, "artifact_type": ARTIFACT_TYPE, "authority_status": "unattested", "posting_status": "blocked", "confirmed_count": 0, "gate5_credit": 0, "rule_contract_version": RULE_VERSION, "rule_contract_sha256": RULE_SHA256, "alias_contract_version": ALIAS_CONTRACT_VERSION, "alias_contract_sha256": ALIAS_CONTRACT_SHA256, "deferred_evidence": ["verified_mail_booking_chain_13", "exact_evidence_union_96"], "input_manifest_sha256": ctx["input_manifest_sha256"], "candidate_semantic_sha256": ctx["candidate_semantic_sha256"], "current_event_set_sha256": ctx["current_event_set_sha256"], "decision_scope_sha256": ctx["decision_scope_sha256"], "classified_v14_sha256": CLASSIFIED_SHA256, "manual_raw_sha256": _sha(raw), "manual_canonical_rows_sha256": manual_canonical, "manual_byte_count": len(raw), "manual_row_count": len(manual_rows) + len(malformed), "manual_header": list(CSV_HEADER), "files": file_meta, "counts": counts}
            package_set = _sha(_json(base) + proposal_bytes + conflict_bytes + group_bytes + diagnostic_bytes + evidence_bytes)
            manifest = {**base, "package_set_sha256": package_set, "analysis_run_id": _sha(_json({"artifact_type": ARTIFACT_TYPE, "package_set_sha256": package_set, "current_event_set_sha256": ctx["current_event_set_sha256"], "manual_raw_sha256": _sha(raw)}))}
            files = {"manifest.json": _json(manifest), "proposals.csv": proposal_bytes, "conflicts.csv": conflict_bytes, "groups.csv": group_bytes, "diagnostics.csv": diagnostic_bytes, "evidence_sets.csv": evidence_bytes}
            return manifest, files
        finally:
            ctx["db"].close()


def build_external_manual_evidence(manual_csv: Path, *, ledger_dir: Path = REPOSITORY_ROOT / "ledger", output: Path | None = None) -> dict[str, object]:
    manifest, files = _build_package(manual_csv.resolve(strict=True), ledger_dir)
    if output is not None:
        parent = output.parent.resolve(strict=True)
        try: parent.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError: pass
        else: raise ValueError("r25_output_inside_repository")
        target = parent / output.name
        if os.path.lexists(target): raise FileExistsError("r25_output_exists")
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=str(parent)))
        try:
            for name, data in files.items():
                with (stage / name).open("wb") as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
            directory = open_dir(stage); fsync_dir(directory); os.close(directory)
            verify_external_manual_evidence(stage, manual_csv=manual_csv, ledger_dir=ledger_dir, current=False)
            _install_noreplace(stage, target)
            parent_fd = open_dir(parent)
            try: fsync_dir(parent_fd)
            finally: os.close(parent_fd)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True); raise
    return {"manifest": manifest, "manifest_sha256": _sha(files["manifest.json"]), "files": manifest["files"], "output": None if output is None else str(output)}


def verify_external_manual_evidence(directory: Path, *, manual_csv: Path, ledger_dir: Path = REPOSITORY_ROOT / "ledger", current: bool = True) -> dict[str, object]:
    if directory.is_symlink() or not directory.is_dir() or sorted(item.name for item in directory.iterdir()) != sorted(FILES):
        raise ValueError("r25_package_shape_invalid")
    if any((directory / name).is_symlink() or not (directory / name).is_file() for name in FILES):
        raise ValueError("r25_package_file_invalid")
    actual = {name: (directory / name).read_bytes() for name in FILES}
    manifest = json.loads(actual["manifest.json"])
    if manifest.get("artifact_type") != ARTIFACT_TYPE or manifest.get("rule_contract_sha256") != RULE_SHA256:
        raise ValueError("r25_manifest_schema_invalid")
    if (manifest.get("authority_status"), manifest.get("posting_status"), manifest.get("confirmed_count"), manifest.get("gate5_credit")) != ("unattested", "blocked", 0, 0):
        raise ValueError("r25_authority_boundary_invalid")
    for name in FILES[1:]:
        if manifest.get("files", {}).get(name, {}).get("sha256") != _sha(actual[name]):
            raise ValueError("r25_file_hash_mismatch")
    expected_manifest, expected = _build_package(manual_csv.resolve(strict=True), ledger_dir)
    if current and any(actual[name] != expected[name] for name in FILES):
        raise ValueError("r25_live_context_or_semantics_mismatch")
    if not current:
        if actual != expected:
            raise ValueError("r25_staging_semantics_mismatch")
    return {"status": "valid", "analysis_run_id": expected_manifest["analysis_run_id"], "proposal_count": expected_manifest["counts"]["new_proposals"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual-csv", type=Path, required=True); parser.add_argument("--output", type=Path); parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        result = verify_external_manual_evidence(args.verify, manual_csv=args.manual_csv) if args.verify else build_external_manual_evidence(args.manual_csv, output=args.output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, sort_keys=True)); return 2


if __name__ == "__main__":
    raise SystemExit(main())