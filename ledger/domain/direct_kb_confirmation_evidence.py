"""R45 KB overseas-use confirmation evidence for one atomic 3-event group.

Private decrypted records and issuer envelopes stay outside the repository.  Public output
contains only content commitments and opaque event hashes; no approval, card, customer,
booking, amount, merchant, or source locator value is exported.
"""
from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import stat
import tempfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from ledger.domain import direct_document_acquisition_census as r42
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT

ARTIFACT_TYPE = "r45-kb-confirmation-group-evidence-v1"
RULE_VERSION = "r45-kb-atomic-three-permutation-v1"
FILES = ("manifest.json", "groups.csv", "proposals.csv", "exclusions.csv")
EXPECTED_CURRENT = r44.EXPECTED_CURRENT
EXPECTED_SCOPE = r44.EXPECTED_SCOPE
EXPECTED_RESIDUAL = r44.EXPECTED_RESIDUAL
EXPECTED_FRONTIER24 = r44.EXPECTED_FRONTIER24
A0_POLICY_SHA256 = r44.A0_POLICY_SHA256
TRIPS_SHA256 = r44.TRIPS_SHA256
TRIP_TARGET = "0613_북해도"
ACCOUNT, COST_TYPE, VAT_TAG = "여행원가", "숙박비", "불공제_해외"
EVENTS = {
    "card:08661a27178cda06754688a3673c731c1dfe33d3b0448d57908734c2bf57fe92#single": "c75cb428047c9f566b93b579e34b1f5038800af8408430209f3f827306c41931",
    "card:5b7d60168fbc90c1b8bda9d5ea94b1ab42c13b81592f111bdd1f907fb8d38180#single": "f28f070c71b48c03b694a8758212188b2838541f4c598f3b5e4a6315017c82ad",
    "card:a78d5516eee7b460ccfd6083fdecc1f4b01bf064a97b95fce5cb83f2bf83c9c1#single": "eb29e2bc007bd2f4eb5259bee016ec981949782a1c63227fcbab8832c96e6b47",
}
ADJACENT_SOURCE_KEYS = {"KBO:E:1475", "KBO:E:1476", "KBO:E:1479"}
ADJACENT_EVENTS = {
    "card:2ca232ff5c71bec299ac3c978e0e3b0ab320532b59d3d40fd89bcd2ca9fda1b9#single":
        "d5e1393032528ae43b810a458f3b77ff5f93ce773a67afa6a764ad3c0c0f49d7",
    "card:e7c2b38e42a3e4494312780e8ae0455549775bb40dc3974ef9a99513f39a4f80#single":
        "5669919651c0c4cb4154a236823ad9dc52b9533fc4346d70f1a7e8c8f0c8d350",
    "card:e92b31b1ecbaa352c217e8111f316fe1d5d600cc94fbd9092f0593ccb44cbb38#single":
        "5de5ca985a61ec698c292dc11f5512c4e77a26ef9dc11f1477f4e0eeb4748cb4",
}
SELECTED_SET = "a743559bb1568c35aa78cbe0320245810e4addc7ab0c5f6c4f1eadf559b77f7f"
POST_ACCEPTED_SET = "fb6fb36c32ad428e69530cb2d1a6fec032e41e3254f8dee14a49e3e72794ca31"
POST_RESIDUAL_SET = "3ddfedb0a88efdd197ac07c19449d65e610bc310293ff9c1e1c69d648f697dba"
REMAINING_FRONTIER_SET = "4bfb88f4d378bee1a78f304c422afac13f525cfbc16ec42db78bbf33c8cda61b"
EXPECTED_R42_PACKAGE = r44.EXPECTED_R42_PACKAGE
EXPECTED_PRIVATE_MANIFEST_SHA256 = "5cd7233d539f3709539eff5b727c235fe5623e646aa3715098751a67ba07cc2f"
EXPECTED_PRIVATE_PIN_SET_SHA256 = "455cbca4464db9361e518d638c0f2a2206b9ea895fba1f4628b322b4a080cdbf"
EXPECTED_DUPLICATE_ENVELOPE_GROUPS = {
    frozenset({"03.html", "08.html"}), frozenset({"04.html", "06.html"}),
    frozenset({"05.html", "07.html"}), frozenset({"09.html", "10.html"}),
}
GROUP_FIELDS = ("group_id", "member_set_sha256", "member_count", "private_pin_set_sha256",
                "trip_target", "relation_kind", "bijection_asserted", "individual_relation_count",
                "permutation_invariant", "disposition", "authority_status", "posting_status",
                "confirmed_count", "gate5_credit", "applied")
PROPOSAL_FIELDS = ("proposal_id", "event_key_sha256", "current_event_sha256", "current_source_sha256",
                   "current_payload_sha256", "group_id", "account",
                   "cost_type", "vat_tag", "trip_target", "relation_kind", "bijection_asserted",
                   "individual_relation_count", "atomic_group_required", "atomic_member_count",
                   "disposition", "authority_status", "posting_status", "confirmed_count",
                   "gate5_credit", "applied")
EXCLUSION_FIELDS = ("exclusion_id", "event_key_sha256", "current_event_sha256", "group_id",
                    "group_member_set_sha256", "reason_code", "disposition", "authority_status",
                    "posting_status", "confirmed_count", "gate5_credit", "applied")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def _setsha(values) -> str:
    return r36._event_set_sha(set(values))


def _csv(fields, rows) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: (str(row.get(key, "")).lower()
                              if isinstance(row.get(key), bool) else row.get(key, ""))
                         for key in fields})
    return out.getvalue().encode()


def _strict_json(data: bytes, label: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"r45_{label}_duplicate_key")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"r45_{label}_invalid") from exc


def _private_bytes_at(dirfd: int, name: str) -> bytes:
    if not re.fullmatch(r"[0-9]{2}\.(?:json|html)|manifest\.json", name):
        raise ValueError("r45_private_filename_invalid")
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                 getattr(os, "O_CLOEXEC", 0), dir_fd=dirfd)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
            raise ValueError("r45_private_file_invalid")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError("r45_private_file_changed")
    return b"".join(chunks)


def _open_private_dir(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                 getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    st = os.fstat(fd)
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or
            stat.S_IMODE(st.st_mode) != 0o700):
        os.close(fd)
        raise ValueError("r45_private_file_invalid")
    return fd


def verify_private_pin(pin_dir: Path, envelope_dir: Path) -> dict[str, object]:
    pinfd = _open_private_dir(pin_dir)
    envelopefd = _open_private_dir(envelope_dir)
    try:
        pin_identity = _identity(os.fstat(pinfd))
        envelope_identity = _identity(os.fstat(envelopefd))
        envelope_names = set(os.listdir(envelopefd))
        expected_envelopes = {f"{index:02d}.html" for index in range(1, 24)}
        if envelope_names != expected_envelopes:
            raise ValueError("r45_envelope_census_invalid")
        envelope_bytes = {name: _private_bytes_at(envelopefd, name) for name in sorted(envelope_names)}
        envelope_hashes = {name: _sha(data) for name, data in envelope_bytes.items()}
        frequencies = Counter(envelope_hashes.values())
        duplicate_groups = {
            frozenset(name for name, digest in envelope_hashes.items() if digest == target)
            for target, count in frequencies.items() if count == 2
        }
        if len(frequencies) != 19 or sorted(frequencies.values()).count(2) != 4 or any(
                count not in {1, 2} for count in frequencies.values()) or \
                duplicate_groups != EXPECTED_DUPLICATE_ENVELOPE_GROUPS:
            raise ValueError("r45_envelope_duplicate_census_invalid")
        manifest_bytes = _private_bytes_at(pinfd, "manifest.json")
        if _sha(manifest_bytes) != EXPECTED_PRIVATE_MANIFEST_SHA256:
            raise ValueError("r45_pin_manifest_hash_invalid")
        manifest = _strict_json(manifest_bytes, "pin_manifest")
        if (set(manifest) != {"artifact_type", "format_version", "members"} or
                manifest.get("artifact_type") != "r45-kb-confirmation-private-pin-v1" or
                manifest.get("format_version") != 1 or len(manifest.get("members", [])) != 3):
            raise ValueError("r45_pin_manifest_contract_invalid")
        expected_files = {"manifest.json"}
        approvals = set()
        commitments = []
        for member in manifest["members"]:
            if set(member) != {"decrypted_dom_sha256", "envelope_filename", "envelope_sha256",
                               "normalized_table_sha256", "opaque_member", "private_record_filename",
                               "private_record_sha256"}:
                raise ValueError("r45_pin_member_schema_invalid")
            record_name = member["private_record_filename"]
            envelope_name = member["envelope_filename"]
            if (not re.fullmatch(r"(?:15|17|20)\.json", record_name) or
                    not re.fullmatch(r"(?:15|17|20)\.html", envelope_name)):
                raise ValueError("r45_pin_member_name_invalid")
            expected_files.add(record_name)
            record_bytes = _private_bytes_at(pinfd, record_name)
            selected_envelope_bytes = envelope_bytes[envelope_name]
            if (_sha(record_bytes) != member["private_record_sha256"] or
                    _sha(selected_envelope_bytes) != member["envelope_sha256"] or
                    envelope_hashes[envelope_name] != member["envelope_sha256"]):
                raise ValueError("r45_pin_member_hash_invalid")
            record = _strict_json(record_bytes, "private_record")
            if (set(record) != {"decrypted_dom_html", "decrypted_dom_sha256", "format_version",
                                "normalized_body_lines", "normalized_body_sha256",
                                "normalized_table_sha256", "source_envelope", "table_rows"} or
                    record.get("format_version") != 1 or record.get("source_envelope") != envelope_name or
                    record.get("decrypted_dom_sha256") != member["decrypted_dom_sha256"] or
                    record.get("normalized_table_sha256") != member["normalized_table_sha256"]):
                raise ValueError("r45_private_record_binding_invalid")
            dom = record.get("decrypted_dom_html")
            lines = record.get("normalized_body_lines")
            table_text = record.get("table_rows")
            if (not isinstance(dom, str) or _sha(dom.encode()) != record.get("decrypted_dom_sha256") or
                    not isinstance(table_text, (str, list)) or
                    _sha(json.dumps(table_text, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()) != record.get("normalized_table_sha256") or
                    not isinstance(lines, list) or len(lines) != 10 or
                    _sha(json.dumps(lines, ensure_ascii=False, separators=(",", ":")).encode()) !=
                    record.get("normalized_body_sha256")):
                raise ValueError("r45_private_fresh_hash_invalid")
            parsed_table = (_strict_json(table_text.encode(), "private_table")
                            if isinstance(table_text, str) else table_text)
            semantic_lines = [line.split("\t") for line in lines if "\t" in line]
            if (len(semantic_lines) != 3 or any(len(row) != 6 for row in semantic_lines) or
                    parsed_table != semantic_lines):
                raise ValueError("r45_private_body_shape_invalid")
            flat = {str(row[index]): str(row[index + 1])
                    for row in semantic_lines for index in range(0, 6, 2)}
            approval = flat.get("승인번호", "")
            if (not re.fullmatch(r"[0-9]{6}", approval) or approval in approvals or
                    flat.get("사용자명") != "주식회사 숲길여행" or
                    flat.get("카드번호") != "5585-26**-****-8835" or
                    flat.get("가맹점명") != "AGODA.COM NEW AKAN H" or
                    flat.get("총 결제금액") != "410,621" or flat.get("현지금액") != "43,200.000" or
                    flat.get("사용금액") != "409,608" or flat.get("환가료") != "1,013"):
                raise ValueError("r45_private_target_fact_invalid")
            approvals.add(approval)
            commitments.append({key: member[key] for key in sorted(member) if key != "opaque_member"})
        pin_set_sha = _sha(_json(commitments))
        if (set(os.listdir(pinfd)) != expected_files or len(approvals) != 3 or
                pin_set_sha != EXPECTED_PRIVATE_PIN_SET_SHA256 or
                _identity(os.fstat(pinfd)) != pin_identity or
                _identity(os.fstat(envelopefd)) != envelope_identity or
                set(os.listdir(envelopefd)) != expected_envelopes or
                {name: _private_bytes_at(envelopefd, name) for name in sorted(expected_envelopes)} !=
                envelope_bytes):
            raise ValueError("r45_pin_census_invalid")
        return {"private_pin_set_sha256": pin_set_sha, "member_count": 3,
                "delivery_count": len(envelope_names), "unique_envelope_count": len(frequencies),
                "duplicate_pairs": sum(count == 2 for count in frequencies.values()),
                "decrypted_fact_attestation": "session-asserted-artifact-pinned"}
    finally:
        os.close(pinfd)
        os.close(envelopefd)


def _trip_contract(ledger_dir: Path) -> str:
    policy = REPOSITORY_ROOT / "docs/비용분류_지시사항_원장.md"
    trips_path = ledger_dir / "data/trips.json"
    if _sha(policy.read_bytes()) != A0_POLICY_SHA256 or _sha(trips_path.read_bytes()) != TRIPS_SHA256:
        raise ValueError("r45_a0_or_trips_drift")
    rows = [row for row in _strict_json(trips_path.read_bytes(), "trips") if row.get("tab") == TRIP_TARGET]
    if len(rows) != 1:
        raise ValueError("r45_trip_target_invalid")
    row = rows[0]
    start = date(2026, int(row["mm"]), int(row["dd"]))
    end = start + timedelta(days=int(row["window"]) - 1)
    if not (start <= date(2026, 6, 15) <= date(2026, 6, 16) <= end):
        raise ValueError("r45_stay_outside_trip")
    return _sha(_json(row))


def _validate_raw_target_census(rows) -> None:
    signature = []
    for source_key, payload in rows:
        if (payload.get("src") == "KBO" and payload.get("card4") == "8835" and
                payload.get("currency") == "JPY" and str(payload.get("foreign")) in
                {"43200", "43200.0"} and payload.get("merchant") == "AGODA.COM NEW AKAN H" and
                abs(int(payload.get("krw", 0))) == 410621):
            signature.append((source_key, payload))
    purchases = [(key, row) for key, row in signature if row.get("cancel") is False and
                 int(row.get("cancel_amount", -1)) == 0]
    cancellations = [(key, row) for key, row in signature if row.get("cancel") is not False or
                     int(row.get("cancel_amount", 0)) != 0]
    expected = {"KBO:E:1477", "KBO:E:1478", "KBO:E:1480"}
    if len(signature) != 3 or len(purchases) != 3 or cancellations or \
            {key for key, _ in purchases} != expected:
        raise ValueError("r45_raw_target_census_invalid")


def _live(ledger_dir: Path):
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve():
        raise ValueError("r45_noncanonical_ledger")
    m42, _ = r42._build(ledger_dir)
    if m42.get("package_set_sha256") != EXPECTED_R42_PACKAGE:
        raise ValueError("r45_r42_package_drift")
    accepted, f38 = r44._accepted_union(ledger_dir)
    with tempfile.TemporaryDirectory(prefix="r45-current-") as td:
        ctx = r36._context(ledger_dir, Path(td))
        db = ctx["db"]
        events = {event["direct_event_key"]: event for event in ctx["events"]}
        try:
            if (ctx["current_event_set_sha256"], ctx["decision_scope_sha256"]) != (EXPECTED_CURRENT, EXPECTED_SCOPE):
                raise ValueError("r45_current_context_invalid")
            residual = set(events) - accepted
            if (len(accepted), len(residual), _setsha(residual)) != (1528, 3800, EXPECTED_RESIDUAL):
                raise ValueError("r45_upstream_residual_invalid")
            bindings = []
            raw_rows = []
            for source_key, payload_json in db.execute(
                    "SELECT source_key,payload_json FROM direct_source_records"):
                candidate = _strict_json(payload_json.encode(), "source_payload_census")
                raw_rows.append((source_key, candidate))
            _validate_raw_target_census(raw_rows)
            for key, content_sha in EVENTS.items():
                event = events.get(key)
                if event is None:
                    raise ValueError("r45_selected_event_missing")
                raw = db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",
                                 (event["current_source_key"],)).fetchone()
                payload = _strict_json(raw[0].encode(), "selected_payload") if raw else None
                if (event["current_event_sha256"] != content_sha or event["source_system"] != "KBO" or
                        event["current_source_kind"] != "card_raw" or event["event_role"] != "single" or
                        event["transaction_type"] != "purchase" or event["card4"] != "8835" or
                        event["currency"] != "JPY" or str(event["foreign_amount"]) != "43200" or
                        int(event["signed_amount_krw"]) != 410621 or event["merchant"] != "AGODA.COM NEW AKAN H" or
                        (event["occurred_on"], event["posted_on"]) != ("2026-02-07", "2026-02-12") or
                        payload is None or payload.get("raw_record_id") not in {"E:1477", "E:1478", "E:1480"} or
                        payload.get("cancel") is not False or payload.get("biz") != "해외"):
                    raise ValueError("r45_selected_event_contract_invalid")
                bindings.append({"key": key, "event_key_sha256": _sha(key.encode()),
                                 "current_event_sha256": content_sha,
                                 "current_source_sha256": event["current_source_sha256"],
                                 "current_payload_sha256": _sha(_json(payload))})
            adjacent = [event for event in events.values() if event["current_source_key"] in ADJACENT_SOURCE_KEYS]
            if (len(adjacent) != 3 or
                    {x["direct_event_key"]: x["current_event_sha256"] for x in adjacent} != ADJACENT_EVENTS or
                    {x["current_source_key"] for x in adjacent} != ADJACENT_SOURCE_KEYS or
                    any(int(x["signed_amount_krw"]) != 205309 or
                        str(x["foreign_amount"]) != "21600" or x["transaction_type"] != "purchase" or
                        x["card4"] != "8835" or x["currency"] != "JPY" or
                        x["merchant"] != "AGODA.COM NEW AKAN H" for x in adjacent)):
                raise ValueError("r45_adjacent_group_drift")
        finally:
            db.close()
    post_accepted = accepted | set(EVENTS)
    post_residual = residual - set(EVENTS)
    if (_setsha(EVENTS) != SELECTED_SET or not set(EVENTS) < residual or
            len(post_accepted) != 1531 or _setsha(post_accepted) != POST_ACCEPTED_SET or
            len(post_residual) != 3797 or _setsha(post_residual) != POST_RESIDUAL_SET):
        raise ValueError("r45_selected_residual_membership_invalid")
    frontier = list(csv.DictReader(io.StringIO(f38["exclusions.csv"].decode())))
    frontier_keys = {row["direct_event_key"] for row in frontier}
    if len(frontier) != 24 or not set(EVENTS) < frontier_keys:
        raise ValueError("r45_frontier_membership_invalid")
    remaining = [row for row in frontier if row["direct_event_key"] not in EVENTS]
    if (len(remaining) != 21 or len({row["group_id"] for row in remaining}) != 10 or
            _setsha(row["direct_event_key"] for row in remaining) != REMAINING_FRONTIER_SET):
        raise ValueError("r45_frontier21_invalid")
    return bindings, remaining, residual


def _build(pin_dir: Path, envelope_dir: Path, ledger_dir: Path = REPOSITORY_ROOT / "ledger"):
    pin = verify_private_pin(pin_dir, envelope_dir)
    bindings, remaining, residual = _live(ledger_dir)
    trip_sha = _trip_contract(ledger_dir)
    signatures = {_sha(_json(sorted((row["event_key_sha256"], row["current_event_sha256"],
                                      ACCOUNT, COST_TYPE, VAT_TAG, TRIP_TARGET) for row in permutation)))
                  for permutation in itertools.permutations(bindings)}
    if len(signatures) != 1 or len(bindings) != 3:
        raise ValueError("r45_permutation_invariance_invalid")
    group_id = _sha(_json({"artifact": ARTIFACT_TYPE, "selected": SELECTED_SET,
                           "pin": pin["private_pin_set_sha256"]}))
    common = {"group_id": group_id, "member_set_sha256": SELECTED_SET, "member_count": 3,
              "private_pin_set_sha256": pin["private_pin_set_sha256"], "trip_target": TRIP_TARGET,
              "relation_kind": "issuer_closed_group_lodging_classification", "bijection_asserted": False,
              "individual_relation_count": 0, "permutation_invariant": True,
              "disposition": "atomic_three_full_classification_review_proposal",
              "authority_status": "unattested", "posting_status": "blocked",
              "confirmed_count": 0, "gate5_credit": 0, "applied": False}
    proposals = []
    for binding in sorted(bindings, key=lambda row: row["event_key_sha256"]):
        row = {key: value for key, value in binding.items() if key != "key"}
        row.update({"group_id": group_id, "account": ACCOUNT, "cost_type": COST_TYPE,
                    "vat_tag": VAT_TAG, "trip_target": TRIP_TARGET,
                    "relation_kind": common["relation_kind"], "bijection_asserted": False,
                    "individual_relation_count": 0, "atomic_group_required": True,
                    "atomic_member_count": 3, "disposition": common["disposition"],
                    "authority_status": "unattested", "posting_status": "blocked",
                    "confirmed_count": 0, "gate5_credit": 0, "applied": False})
        row["proposal_id"] = _sha(_json({"group": group_id, "event": row["event_key_sha256"]}))
        proposals.append(row)
    exclusions = []
    for old in remaining:
        row = {"event_key_sha256": _sha(old["direct_event_key"].encode()),
               "current_event_sha256": old["current_event_sha256"], "group_id": old["group_id"],
               "group_member_set_sha256": old["group_member_set_sha256"],
               "reason_code": old["reason_code"], "disposition": "deferred_insufficient_independent_evidence",
               "authority_status": "unattested", "posting_status": "blocked",
               "confirmed_count": 0, "gate5_credit": 0, "applied": False}
        row["exclusion_id"] = _sha(_json(row))
        exclusions.append(row)
    payload = {"groups.csv": _csv(GROUP_FIELDS, [common]),
               "proposals.csv": _csv(PROPOSAL_FIELDS, proposals),
               "exclusions.csv": _csv(EXCLUSION_FIELDS, sorted(exclusions, key=lambda row: row["event_key_sha256"]))}
    base = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "authority_status": "unattested", "posting_status": "blocked", "confirmed_count": 0,
            "gate5_credit": 0, "applied": False, "contains_sensitive_raw_values": False,
            "atomic_all_three": True, "full_classification_delta": 3, "accepted_union": 1531,
            "global_residual": 3797, "frontier_authoritative": 21, "review_candidate_count": 3,
            "bijection_asserted": False, "individual_relation_count": 0,
            "selected_set_sha256": SELECTED_SET,
            "post_admission_accepted_set_sha256": POST_ACCEPTED_SET,
            "post_admission_residual_set_sha256": POST_RESIDUAL_SET,
            "remaining_frontier_set_sha256": _setsha(row["direct_event_key"] for row in remaining),
            "remaining_frontier_group_count": 10,
            "permutation_semantic_sha256": signatures.pop(), "trip_target": TRIP_TARGET,
            "trip_row_sha256": trip_sha, "a0_policy_sha256": A0_POLICY_SHA256,
            "trips_raw_sha256": TRIPS_SHA256, "private_pin_set_sha256": pin["private_pin_set_sha256"],
            "delivery_count": pin["delivery_count"], "unique_envelope_count": pin["unique_envelope_count"],
            "duplicate_pairs": pin["duplicate_pairs"],
            "decrypted_fact_attestation": pin["decrypted_fact_attestation"],
            "adjacent_group_unchanged": True, "database_applied": False,
            "selection_census_authority": "capture_claim_unverified",
            "r42_package_set_sha256": EXPECTED_R42_PACKAGE,
            "current_event_set_sha256": EXPECTED_CURRENT, "decision_scope_sha256": EXPECTED_SCOPE,
            "state_semantics": "classification-review delta only; no DB apply or activation authority",
            "files": {name: {"sha256": _sha(data), "rows": len(data.splitlines()) - 1}
                      for name, data in payload.items()}}
    base["package_set_sha256"] = _sha(_json(base) + b"".join(payload[name] for name in sorted(payload)))
    files = {"manifest.json": _json(base), **payload}
    _privacy_scan(files)
    return base, files


def _privacy_scan(files: dict[str, bytes]) -> None:
    blob = b"".join(files.values()).decode()
    forbidden = (r"card:[0-9a-f]{64}#", r"KBO:E:", r"\b8835\b",
                 r"(?<![0-9A-Fa-f])\d{6}(?![0-9A-Fa-f])",
                 r"\b(?:410621|43200|205309|21600)\b", r"AGODA", r"NEW AKAN", r"주식회사",
                 r"https?://", r"approval", r"booking")
    if any(re.search(pattern, blob, re.I) for pattern in forbidden):
        raise ValueError("r45_public_privacy_violation")


def _capture(directory: Path):
    try:
        return r42._capture_package(directory, FILES)
    except ValueError as exc:
        raise ValueError("r45_package_shape_invalid") from exc


class PublicationDurabilityError(OSError):
    def __init__(self, output, package_set_sha256, parent_identity, target_identity):
        super().__init__("r45_published_durability_unknown")
        self.output = output; self.package_set_sha256 = package_set_sha256; self.published = True
        self.parent_path = output.parent; self.target_name = output.name
        self.parent_identity = parent_identity; self.target_identity = target_identity


class PublicationIntegrityError(OSError):
    def __init__(self, output, package_set_sha256, parent_identity, target_identity):
        super().__init__("r45_published_integrity_invalid")
        self.output = output; self.package_set_sha256 = package_set_sha256; self.published = True
        self.parent_path = output.parent; self.target_name = output.name
        self.parent_identity = parent_identity; self.target_identity = target_identity


def _identity(st):
    return st.st_dev, st.st_ino


def _capture_dirfd(dirfd: int):
    dst = os.fstat(dirfd)
    if (not stat.S_ISDIR(dst.st_mode) or stat.S_IMODE(dst.st_mode) != 0o700 or
            dst.st_uid != os.getuid() or set(os.listdir(dirfd)) != set(FILES)):
        raise ValueError("r45_package_shape_invalid")
    result = {}
    for name in FILES:
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_CLOEXEC", 0), dir_fd=dirfd)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                    stat.S_IMODE(before.st_mode) != 0o600 or before.st_uid != os.getuid()):
                raise ValueError("r45_package_shape_invalid")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                raise ValueError("r45_package_changed_during_read")
            result[name] = b"".join(chunks)
        finally:
            os.close(fd)
    return result


def _rename_noreplace_at(parentfd: int, source: str, target: str):
    try:
        function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2")
    except AttributeError as exc:
        raise OSError("r45_atomic_noreplace_unsupported") from exc
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parentfd, os.fsencode(source), parentfd, os.fsencode(target), 1) == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError("r45_output_exists")
    raise OSError(code, "r45_renameat2")


def build_kb_confirmation_evidence(pin_dir: Path, envelope_dir: Path, output: Path | None = None):
    manifest, files = _build(pin_dir, envelope_dir)
    if output is None:
        return {"manifest": manifest, "files": files}
    if output.parent.is_symlink():
        raise ValueError("r45_output_parent_symlink")
    out = output.resolve()
    if REPOSITORY_ROOT.resolve() in (out, *out.parents):
        raise ValueError("r45_output_inside_repository")
    if os.path.lexists(out):
        raise FileExistsError(out)
    parentfd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                       getattr(os, "O_NOFOLLOW", 0))
    parent_identity = _identity(os.fstat(parentfd))
    if _identity(os.stat(output.parent, follow_symlinks=False)) != parent_identity:
        os.close(parentfd)
        raise ValueError("r45_parent_identity_changed")
    stage = Path(tempfile.mkdtemp(prefix=".r45-stage-", dir=f"/proc/self/fd/{parentfd}"))
    stage_name = stage.name
    os.chmod(stage, 0o700)
    stagefd = os.open(stage_name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                      getattr(os, "O_NOFOLLOW", 0), dir_fd=parentfd)
    published = False
    targetfd = None
    target_identity = None
    try:
        for name, data in files.items():
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=stagefd)
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(stagefd)
        if _capture_dirfd(stagefd) != files:
            raise ValueError("r45_stage_verify_failed")
        if (_identity(os.fstat(parentfd)) != parent_identity or
                _identity(os.stat(output.parent, follow_symlinks=False)) != parent_identity):
            raise ValueError("r45_parent_identity_changed")
        _rename_noreplace_at(parentfd, stage_name, out.name)
        published = True
        os.close(stagefd)
        stagefd = None
        targetfd = os.open(out.name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                           getattr(os, "O_NOFOLLOW", 0), dir_fd=parentfd)
        target_identity = _identity(os.fstat(targetfd))
        try:
            if _capture_dirfd(targetfd) != files:
                raise ValueError("r45_post_install_bytes_mismatch")
        except Exception as exc:
            raise PublicationIntegrityError(out, manifest["package_set_sha256"],
                                            parent_identity, target_identity) from exc
        try:
            os.fsync(parentfd)
        except OSError as exc:
            raise PublicationDurabilityError(out, manifest["package_set_sha256"],
                                             parent_identity, target_identity) from exc
        if (_identity(os.fstat(parentfd)) != parent_identity or
                _identity(os.fstat(targetfd)) != target_identity or
                _identity(os.stat(output.parent, follow_symlinks=False)) != parent_identity):
            raise PublicationIntegrityError(out, manifest["package_set_sha256"],
                                            parent_identity, target_identity)
        try:
            if _capture_dirfd(targetfd) != files:
                raise ValueError("r45_post_fsync_bytes_mismatch")
        except Exception as exc:
            raise PublicationIntegrityError(out, manifest["package_set_sha256"],
                                            parent_identity, target_identity) from exc
    finally:
        if targetfd is not None:
            os.close(targetfd)
        if stagefd is not None:
            os.close(stagefd)
        if not published and stage.exists():
            shutil.rmtree(stage)
        os.close(parentfd)
    return {"manifest": manifest, "output": str(out)}


def verify_kb_confirmation_evidence(directory: Path, pin_dir: Path, envelope_dir: Path):
    manifest, expected = _build(pin_dir, envelope_dir)
    if _capture(directory) != expected:
        raise ValueError("r45_package_or_context_mismatch")
    return {"status": "valid", "package_set_sha256": manifest["package_set_sha256"],
            "proposals": 3, "accepted_union": 1531, "global_residual": 3797,
            "frontier_authoritative": 21, "full_classification_delta": 3}


def reconcile_publication(error, pin_dir: Path, envelope_dir: Path):
    if not isinstance(error, (PublicationDurabilityError, PublicationIntegrityError)):
        raise ValueError("r45_reconcile_state_invalid")
    manifest, expected = _build(pin_dir, envelope_dir)
    parentfd = os.open(error.parent_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                       getattr(os, "O_NOFOLLOW", 0))
    try:
        if _identity(os.fstat(parentfd)) != error.parent_identity:
            raise ValueError("r45_reconcile_parent_identity_mismatch")
        targetfd = os.open(error.target_name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                           getattr(os, "O_NOFOLLOW", 0), dir_fd=parentfd)
        try:
            if (_identity(os.fstat(targetfd)) != error.target_identity or
                    _capture_dirfd(targetfd) != expected):
                raise ValueError("r45_reconcile_target_identity_mismatch")
            os.fsync(parentfd)
            if (_identity(os.fstat(parentfd)) != error.parent_identity or
                    _identity(os.fstat(targetfd)) != error.target_identity or
                    _capture_dirfd(targetfd) != expected):
                raise ValueError("r45_reconcile_identity_changed")
        finally:
            os.close(targetfd)
    finally:
        os.close(parentfd)
    if manifest["package_set_sha256"] != error.package_set_sha256:
        raise ValueError("r45_reconcile_package_mismatch")
    return {"status": "valid", "package_set_sha256": manifest["package_set_sha256"],
            "proposals": 3, "published": True, "durable": True}
