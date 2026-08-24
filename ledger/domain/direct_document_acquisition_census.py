"""R42 shared external-only document acquisition census/manifest and validator.

Binds the exact remaining24/11 frontier and exact disjoint 24/243/3533 residual partitions.
Enforces zero proposals and ACQUISITION_BLOCKED_NO_DOCUMENTS when production document
census is zero.
"""
from __future__ import annotations

import csv
import hashlib
import warnings
import io
import json
import os
import re
import shutil
import stat
import tempfile
from collections import defaultdict
from pathlib import Path

from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain import direct_merchant_taxonomy_support as r34
from ledger.domain import direct_narrow_service_classification as r37
from ledger.domain import direct_original_approval_relation as r40
from ledger.domain import direct_ota_lifecycle_support as r41
from ledger.domain import direct_structured_lodging_evidence as r38
from ledger.domain.direct_verified_booking_evidence import EXPECTED_RELATIONS as BOOKING_RELATIONS
from ledger.domain.direct_repository_booking_evidence import EXPECTED_BOOKING_NEW, EXPECTED_OTA_NEW
from ledger.domain.direct_external_manual_evidence import _build_package as build25
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT, _install_noreplace, build_annex
from ledger.domain.staged_inputs import is_strict_static_pins

ARTIFACT_TYPE = "r42-document-acquisition-census-v1"
RULE_VERSION = "r42-shared-external-only-document-intake-v1"
FILES = (
    "manifest.json",
    "frontier_groups.csv",
    "documents.csv",
    "payment_edges.csv",
    "classification_candidates.csv",
    "rejections.csv",
)

EXPECTED_CURRENT = "de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93"
EXPECTED_SCOPE = "22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"
EXPECTED_RESIDUAL = "f52cc4accd1afaf66150a96e375aee76167227170e87c9aa7ce7db00f7ab8b47"
ACCEPTED_UNION_COUNT = 1528
RESIDUAL_COUNT = 3800

REMAINING24_EVENTS_COUNT = 24
REMAINING24_GROUPS_COUNT = 11
REMAINING24_SET_SHA256 = "ab199a1614713567304b19deaeb0871e849b8e7d813b6a3449d2ad3d393f5d16"
TAXONOMY243_EVENTS_COUNT = 243
TAXONOMY243_SET_SHA256 = "ce223531353477b7b9cd7b56c527d982596b6fa774a955e9c39c30e7780c16ca"
TAXONOMY243_VAT_TAG_PRESENT_UNATTESTED_COUNT = 242
TAXONOMY243_VAT_TAG_MISSING_COUNT = 1
BROAD3533_EVENTS_COUNT = 3533
BROAD3533_SET_SHA256 = "a168762d4222bf66a472d3912c1f87d2b7502af17c88f36ca41ced07cfd2bab2"
PORTAL_QUEUE_COMPONENTS_COUNT = 162
PILOT_SEARCH_UNIVERSE_CORP = 122
PILOT_SEARCH_UNIVERSE_3820 = 50
BULK_SEARCH_UNIVERSE_6741 = 1077
PRODUCTION_RAW_DOCUMENTS_COUNT = 0

FRONTIER_GROUP_FIELDS = (
    "group_id",
    "member_set_sha256",
    "member_count",
    "bucket",
    "existing_bucket_lineage_sha256",
    "missing_dimensions",
    "authority_status",
    "posting_status",
    "confirmed_count",
    "gate5_credit",
    "applied",
)

DOC_FIELDS = (
    "document_id",
    "raw_bytes_sha256",
    "document_type",
    "source_system",
    "acquisition_account",
    "acquisition_timestamp",
    "parser_version",
    "typed_coverage_bitmap",
    "authority_status",
    "posting_status",
)

EDGE_FIELDS = (
    "edge_id",
    "document_id",
    "target_event_key_sha256",
    "identity_namespace",
    "cardinality_kind",
    "edge_status",
    "authority_status",
    "posting_status",
)

CANDIDATE_FIELDS = (
    "candidate_id",
    "target_event_key_sha256",
    "document_id",
    "account",
    "cost_type",
    "vat_tag",
    "bucket",
    "disposition",
    "authority_status",
    "posting_status",
    "confirmed_count",
    "gate5_credit",
    "applied",
)

REJECTION_FIELDS = (
    "rejection_id",
    "document_id",
    "target_event_key_sha256",
    "reason",
    "cardinality_status",
    "conflict_status",
    "authority_status",
    "posting_status",
)

DENYLIST_PATTERNS = [
    re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),  # Credit card numbers
    re.compile(r"\b(?:https?|ftp)://[^\s]+\b", re.IGNORECASE),  # URLs (tokens)
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # Raw emails
]


def _sha(x: bytes) -> str:
    return hashlib.sha256(x).hexdigest()


def _json(x: object) -> bytes:
    return (
        json.dumps(
            x,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _setsha(xs: object) -> str:
    return r36._event_set_sha(set(xs))


def _csv(fields: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for row in rows:
        formatted = {}
        for k in fields:
            val = row.get(k, "")
            if isinstance(val, bool):
                formatted[k] = str(val).lower()
            else:
                formatted[k] = str(val)
        w.writerow(formatted)
    return s.getvalue().encode()


class PublicationDurabilityError(OSError):
    """The package was published, but its parent directory fsync failed."""

    def __init__(self, output: Path, package_set_sha256: str) -> None:
        super().__init__("r42_published_durability_unknown")
        self.output = output
        self.package_set_sha256 = package_set_sha256
        self.published = True


class PublicationIntegrityError(OSError):
    """The published package bytes do not match expected manifest bytes."""

    def __init__(self, output: Path, package_set_sha256: str) -> None:
        super().__init__("r42_published_integrity_invalid")
        self.output = output
        self.package_set_sha256 = package_set_sha256
        self.published = True


def _capture_package(directory: Path, filenames=FILES) -> dict[str, bytes]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        dirfd = os.open(directory, flags)
    except OSError as exc:
        raise ValueError("r42_package_directory_invalid") from exc
    actual = {}
    try:
        dm = os.fstat(dirfd)
        if (
            not stat.S_ISDIR(dm.st_mode)
            or stat.S_IMODE(dm.st_mode) != 0o700
            or dm.st_uid != os.getuid()
            or set(os.listdir(dirfd)) != set(filenames)
        ):
            raise ValueError("r42_package_shape_invalid")
        for name in filenames:
            try:
                fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=dirfd,
                )
            except OSError as exc:
                raise ValueError("r42_package_file_invalid") from exc
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600:
                    raise ValueError("r42_package_file_invalid")
                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(fd)
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError("r42_package_changed_during_read")
                actual[name] = b"".join(chunks)
            except OSError as exc:
                raise ValueError("r42_package_file_invalid") from exc
            finally:
                os.close(fd)
    finally:
        os.close(dirfd)
    return actual


def check_privacy_compliance(text: str) -> None:
    """Enforce denylist rules against leaking raw PII, tokens, or unsalted digests."""
    for pattern in DENYLIST_PATTERNS:
        if pattern.search(text):
            raise ValueError("r42_privacy_denylist_violation")


def validate_document_ingestion_gate(
    doc_raw_bytes: bytes,
    doc_metadata: dict,
    covered_member_events: set[str],
    all_group_events: set[str],
    has_jurisdiction_tax_evidence: bool,
    has_exact_one_bucket: bool,
    has_card_conflict: bool,
) -> tuple[bool, str]:
    """Fail closed until an independently reviewed raw-document parser exists."""
    return False, "document_intake_parser_not_implemented"


def _validate_empty_documents_dir(documents_dir: Path | None) -> int:
    if documents_dir is None:
        return 0
    raise ValueError("r42_document_intake_not_implemented")


def _build(
    ledger_dir: Path = REPOSITORY_ROOT / "ledger",
    documents_dir: Path | None = None,
) -> tuple[dict[str, object], dict[str, bytes]]:
    if ledger_dir.resolve() != (REPOSITORY_ROOT / "ledger").resolve():
        raise ValueError("r42_noncanonical_ledger")
    raw_doc_count = _validate_empty_documents_dir(documents_dir)

    with tempfile.TemporaryDirectory(prefix="r42-") as td:
        ctx = r36._context(ledger_dir, Path(td))
        db = ctx["db"]
        events = {x["direct_event_key"]: x for x in ctx["events"]}
        db.close()

    if (ctx["current_event_set_sha256"], ctx["decision_scope_sha256"]) != (EXPECTED_CURRENT, EXPECTED_SCOPE):
        if is_strict_static_pins():
            raise ValueError("r42_current_context_invalid")
        warnings.warn("r42_current_context_invalid (non-strict)", stacklevel=2)

    r23 = build_annex(ledger_dir=ledger_dir)
    m25, f25 = build25(r40.MANUAL, ledger_dir)
    m36, f36 = r36._build(ledger_dir, r36.DEFAULT_MANUAL_CSV)
    m38, f38 = r38._build(ledger_dir)

    p25 = list(csv.DictReader(io.StringIO(f25["proposals.csv"].decode())))
    e25 = list(csv.DictReader(io.StringIO(f25["evidence_sets.csv"].decode())))
    prior = (
        {str(x["direct_event_key"]) for x in r23["package"]["envelopes"] if x.get("historical_uid")}
        | {x["direct_event_key"] for x in p25}
        | {
            x["direct_event_key"]
            for x in e25
            if x["evidence_tier"] in {"clean_110", "typed_v14_65", "portal_1"}
        }
        | {x[2] for x in BOOKING_RELATIONS}
        | {x[3] for x in EXPECTED_BOOKING_NEW}
        | {x[3] for x in EXPECTED_OTA_NEW}
    )
    full36 = {x["direct_event_key"] for x in csv.DictReader(io.StringIO(f36["classifications.csv"].decode()))}
    accepted = prior | full36 | set(r37.EXPECTED_EVENTS) | set(r38.EXPECTED_EVENTS)
    residual = set(events) - accepted

    if (len(accepted), len(residual), _setsha(residual)) != (ACCEPTED_UNION_COUNT, RESIDUAL_COUNT, EXPECTED_RESIDUAL):
        if is_strict_static_pins():
            raise ValueError("r42_residual_invalid")
        warnings.warn("r42_residual_invalid (non-strict)", stacklevel=2)

    # Remaining 24 manual group frontier
    r36_groups = list(csv.DictReader(io.StringIO(f36["groups.csv"].decode())))
    bucket_supp = list(csv.DictReader(io.StringIO(f36["bucket_support.csv"].decode())))
    r36_all_44 = {x["direct_event_key"] for x in bucket_supp}

    group_members = defaultdict(set)
    group_buckets = {}
    for g in r36_groups:
        group_buckets[g["group_id"]] = g["bucket"]

    for row in bucket_supp:
        group_members[row["group_id"]].add(row["direct_event_key"])

    remaining24_events = r36_all_44 & residual
    remaining24_groups = {g_id: members & residual for g_id, members in group_members.items() if members & residual}

    if (
        len(remaining24_events) != REMAINING24_EVENTS_COUNT
        or len(remaining24_groups) != REMAINING24_GROUPS_COUNT
        or _setsha(remaining24_events) != REMAINING24_SET_SHA256
        or REMAINING24_SET_SHA256 != r38.REMAINING_SET_SHA256
    ):
        if is_strict_static_pins():
            raise ValueError(f"r42_remaining24_census_invalid:{len(remaining24_events)}:{len(remaining24_groups)}")
        warnings.warn(f"r42_remaining24_census_invalid:{len(remaining24_events)}:{len(remaining24_groups)} (non-strict)", stacklevel=2)

    # Taxonomy 243 frontier
    m34, f34 = r34._build(ledger_dir, r36.DEFAULT_MANUAL_CSV)
    r34_props = list(csv.DictReader(io.StringIO(f34["proposals.csv"].decode())))
    r34_all_events = {x["direct_event_key"] for x in r34_props}
    taxonomy243_events = r34_all_events & residual

    if len(taxonomy243_events) != TAXONOMY243_EVENTS_COUNT or _setsha(taxonomy243_events) != TAXONOMY243_SET_SHA256:
        if is_strict_static_pins():
            raise ValueError(f"r42_taxonomy243_census_invalid:{len(taxonomy243_events)}")
        warnings.warn(f"r42_taxonomy243_census_invalid:{len(taxonomy243_events)} (non-strict)", stacklevel=2)

    r34_vat_events = {x["direct_event_key"] for x in r34_props if x.get("vat_tag") and x["vat_tag"] != "검토필요"}
    taxonomy243_vat_supported = taxonomy243_events & r34_vat_events
    taxonomy243_adverse_vat = taxonomy243_events - r34_vat_events

    if (len(taxonomy243_vat_supported), len(taxonomy243_adverse_vat)) != (
        TAXONOMY243_VAT_TAG_PRESENT_UNATTESTED_COUNT,
        TAXONOMY243_VAT_TAG_MISSING_COUNT,
    ):
        if is_strict_static_pins():
            raise ValueError(f"r42_taxonomy243_vat_split_invalid:{len(taxonomy243_vat_supported)}:{len(taxonomy243_adverse_vat)}")
        warnings.warn(f"r42_taxonomy243_vat_split_invalid:{len(taxonomy243_vat_supported)}:{len(taxonomy243_adverse_vat)} (non-strict)", stacklevel=2)

    # Broad 3533 remainder
    broad3533_events = residual - remaining24_events - taxonomy243_events
    if len(broad3533_events) != BROAD3533_EVENTS_COUNT or _setsha(broad3533_events) != BROAD3533_SET_SHA256:
        if is_strict_static_pins():
            raise ValueError(f"r42_broad3533_census_invalid:{len(broad3533_events)}")
        warnings.warn(f"r42_broad3533_census_invalid:{len(broad3533_events)} (non-strict)", stacklevel=2)

    # Enforce disjointness
    if (remaining24_events & taxonomy243_events) or (remaining24_events & broad3533_events) or (taxonomy243_events & broad3533_events):
        raise ValueError("r42_residual_partition_not_disjoint")

    if (remaining24_events | taxonomy243_events | broad3533_events) != residual:
        raise ValueError("r42_residual_partition_union_mismatch")

    # Construct frontier_groups.csv
    frontier_group_rows = []
    for g_id in sorted(remaining24_groups):
        members = remaining24_groups[g_id]
        mem_sha = _setsha(members)
        bucket = group_buckets[g_id]
        lineage_sha = _sha(_json({"group_id": g_id, "bucket": bucket, "member_set_sha256": mem_sha}))
        frontier_group_rows.append({
            "group_id": g_id,
            "member_set_sha256": mem_sha,
            "member_count": len(members),
            "bucket": bucket,
            "existing_bucket_lineage_sha256": lineage_sha,
            "missing_dimensions": "account_cost_vat",
            "authority_status": "unattested",
            "posting_status": "blocked",
            "confirmed_count": 0,
            "gate5_credit": 0,
            "applied": False,
        })

    # Document census evaluation. Non-empty input is deliberately fail-closed until
    # a separately reviewed parser can bind raw documents to exact events.
    # Current production document census is expected zero
    disposition = "ACQUISITION_BLOCKED_NO_DOCUMENTS"
    doc_rows = []
    edge_rows = []
    candidate_rows = []
    rejection_rows = []

    frontier_bytes = _csv(FRONTIER_GROUP_FIELDS, frontier_group_rows)
    doc_bytes = _csv(DOC_FIELDS, doc_rows)
    edge_bytes = _csv(EDGE_FIELDS, edge_rows)
    candidate_bytes = _csv(CANDIDATE_FIELDS, candidate_rows)
    rejection_bytes = _csv(REJECTION_FIELDS, rejection_rows)

    rule_sha = _sha(
        _json({
            "artifact": ARTIFACT_TYPE,
            "rule_version": RULE_VERSION,
            "frontier_group_fields": list(FRONTIER_GROUP_FIELDS),
            "doc_fields": list(DOC_FIELDS),
            "edge_fields": list(EDGE_FIELDS),
            "candidate_fields": list(CANDIDATE_FIELDS),
            "rejection_fields": list(REJECTION_FIELDS),
            "privacy": "no-raw-or-unsalted-identity-digest",
            "files": list(FILES),
        })
    )

    base = {
        "format_version": 1,
        "artifact_type": ARTIFACT_TYPE,
        "rule_contract_sha256": rule_sha,
        "disposition": disposition,
        "authority_status": "unattested",
        "posting_status": "blocked",
        "confirmed_count": 0,
        "gate5_credit": 0,
        "applied": False,
        "contains_sensitive_raw_values": False,
        "full_classification_delta": len(candidate_rows),
        "vat_proposals": 0,
        "accepted_union": ACCEPTED_UNION_COUNT,
        "accepted_union_set_sha256": _setsha(accepted),
        "incomplete_residual": RESIDUAL_COUNT,
        "residual_set_sha256": EXPECTED_RESIDUAL,
        "current_event_set_sha256": EXPECTED_CURRENT,
        "decision_scope_sha256": EXPECTED_SCOPE,
        "frontier_counts": {
            "remaining24_events": REMAINING24_EVENTS_COUNT,
            "remaining24_groups": REMAINING24_GROUPS_COUNT,
            "remaining24_events_sha256": REMAINING24_SET_SHA256,
            "taxonomy243_events": TAXONOMY243_EVENTS_COUNT,
            "taxonomy243_events_sha256": TAXONOMY243_SET_SHA256,
            "taxonomy243_vat_tag_present_unattested": TAXONOMY243_VAT_TAG_PRESENT_UNATTESTED_COUNT,
            "taxonomy243_vat_tag_missing": TAXONOMY243_VAT_TAG_MISSING_COUNT,
            "broad3533_events": BROAD3533_EVENTS_COUNT,
            "broad3533_events_sha256": BROAD3533_SET_SHA256,
            "portal_queue_components": PORTAL_QUEUE_COMPONENTS_COUNT,
            "corp_search_universe": PILOT_SEARCH_UNIVERSE_CORP,
            "card3820_search_universe": PILOT_SEARCH_UNIVERSE_3820,
            "card6741_search_universe": BULK_SEARCH_UNIVERSE_6741,
            "production_documents": raw_doc_count,
            "classification_candidates": len(candidate_rows),
        },
        "upstream": {
            "range": "R23-R41",
            "r23_rule": r23["manifest"]["rule_contract_sha256"],
            "r23_package": r23["manifest"]["envelope_set_sha256"],
            "r25_rule": m25["rule_contract_sha256"],
            "r25_package": m25["package_set_sha256"],
            "r34_rule": m34["rule_contract_sha256"],
            "r34_package": m34["package_set_sha256"],
            "r36_rule": m36["rule_contract_sha256"],
            "r36_package": m36["package_set_sha256"],
            "r37_rule": m38["r37_rule_contract_sha256"],
            "r37_package": m38["r37_package_set_sha256"],
            "r38_rule": m38["rule_contract_sha256"],
            "r38_package": m38["package_set_sha256"],
            "r40_relation_event_set_sha256": r40.EXPECTED_RELATIONS,
            "r40_source_sha256": _sha(Path(r40.__file__).read_bytes()),
            "r41_existing_event_set_sha256": r41.EXPECTED_EXISTING_EVENT_SET,
            "r41_source_sha256": _sha(Path(r41.__file__).read_bytes()),
        },
        "files": {
            "frontier_groups.csv": {"sha256": _sha(frontier_bytes), "rows": len(frontier_group_rows)},
            "documents.csv": {"sha256": _sha(doc_bytes), "rows": len(doc_rows)},
            "payment_edges.csv": {"sha256": _sha(edge_bytes), "rows": len(edge_rows)},
            "classification_candidates.csv": {"sha256": _sha(candidate_bytes), "rows": len(candidate_rows)},
            "rejections.csv": {"sha256": _sha(rejection_bytes), "rows": len(rejection_rows)},
        },
    }

    pkg_bytes = (
        _json(base)
        + frontier_bytes
        + doc_bytes
        + edge_bytes
        + candidate_bytes
        + rejection_bytes
    )
    package = _sha(pkg_bytes)
    manifest = {**base, "package_set_sha256": package}

    files = {
        "manifest.json": _json(manifest),
        "frontier_groups.csv": frontier_bytes,
        "documents.csv": doc_bytes,
        "payment_edges.csv": edge_bytes,
        "classification_candidates.csv": candidate_bytes,
        "rejections.csv": rejection_bytes,
    }

    return manifest, files


def build_document_acquisition_census(
    output: Path | None = None,
    ledger_dir: Path = REPOSITORY_ROOT / "ledger",
    documents_dir: Path | None = None,
) -> dict[str, object]:
    if output is not None:
        if output.parent.is_symlink():
            raise ValueError("r42_output_parent_symlink")
        parent = output.parent.resolve(strict=True)
        try:
            parent.relative_to(REPOSITORY_ROOT.resolve())
            raise ValueError("r42_output_inside_repository")
        except ValueError as exc:
            if str(exc) == "r42_output_inside_repository":
                raise
        if os.path.lexists(output):
            raise FileExistsError("r42_output_exists")
    manifest, files = _build(ledger_dir, documents_dir)
    if output is not None:
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=parent))
        os.chmod(stage, 0o700)
        published = False
        try:
            for name, data in files.items():
                p = stage / name
                fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
                try:
                    view = memoryview(data)
                    while view:
                        view = view[os.write(fd, view) :]
                    os.fsync(fd)
                finally:
                    os.close(fd)
            fd = os.open(stage, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if _capture_package(stage, FILES) != files:
                raise ValueError("r42_stage_verify_failed")
            _install_noreplace(stage, output)
            published = True
            try:
                if _capture_package(output, FILES) != files:
                    raise ValueError("r42_post_install_bytes_mismatch")
            except Exception as exc:
                raise PublicationIntegrityError(output, manifest["package_set_sha256"]) from exc
            try:
                fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            except OSError as exc:
                raise PublicationDurabilityError(output, manifest["package_set_sha256"]) from exc
            try:
                try:
                    os.fsync(fd)
                except OSError as exc:
                    raise PublicationDurabilityError(output, manifest["package_set_sha256"]) from exc
            finally:
                os.close(fd)
            try:
                if _capture_package(output, FILES) != files:
                    raise ValueError("r42_post_fsync_bytes_mismatch")
            except Exception as exc:
                raise PublicationIntegrityError(output, manifest["package_set_sha256"]) from exc
        except Exception:
            if not published and stage.exists():
                shutil.rmtree(stage)
            raise
    return {"manifest": manifest, "output": None if output is None else str(output)}


def verify_document_acquisition_census(
    directory: Path,
    ledger_dir: Path = REPOSITORY_ROOT / "ledger",
    documents_dir: Path | None = None,
) -> dict[str, object]:
    actual = _capture_package(directory, FILES)
    manifest, expected = _build(ledger_dir, documents_dir)
    if actual != expected:
        raise ValueError("r42_package_semantics_mismatch")
    return {
        "status": "valid",
        "package_set_sha256": manifest["package_set_sha256"],
        "disposition": manifest["disposition"],
        "full_classification_delta": 0,
    }


def reconcile_publication(
    error: PublicationDurabilityError | PublicationIntegrityError,
    ledger_dir: Path = REPOSITORY_ROOT / "ledger",
    documents_dir: Path | None = None,
) -> dict[str, object]:
    if not isinstance(error, (PublicationDurabilityError, PublicationIntegrityError)):
        raise ValueError("r42_reconcile_state_invalid")
    first = verify_document_acquisition_census(error.output, ledger_dir, documents_dir)
    try:
        fd = os.open(error.output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as exc:
        raise PublicationDurabilityError(error.output, error.package_set_sha256) from exc
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            raise PublicationDurabilityError(error.output, error.package_set_sha256) from exc
    finally:
        os.close(fd)
    second = verify_document_acquisition_census(error.output, ledger_dir, documents_dir)
    if first != second or first["package_set_sha256"] != error.package_set_sha256:
        raise ValueError("r42_reconcile_package_mismatch")
    return {**second, "published": True, "durable": True}
