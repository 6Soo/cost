"""P0 canonical inventory, input-contract, and release-block guards.

This module is deliberately read-only.  It does not build or patch the
canonical projection and it never rewrites a blocked artifact.  P1 callers can
invoke :func:`validate_input_contract` before any import so a missing required
source cannot silently reduce the imported inventory.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Mapping


class P0GuardError(RuntimeError):
    """Raised when a frozen fact or input contract no longer matches."""


DEFAULT_MANIFEST = (
    Path("ledger")
    / "baselines"
    / "p0_current_canonical_20260728_v2"
    / "manifest.json"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _amount(value: object) -> int:
    try:
        return round(float(str(value or "0").replace(",", "")))
    except (TypeError, ValueError):
        return 0


def canonical_csv_census(path: Path) -> dict[str, object]:
    """Return the frozen row/source/bucket/refund census for a canonical CSV."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required_columns = {"uid", "src", "bucket", "krw", "cancel", "orig_appr"}
    columns = list(rows[0]) if rows else []
    missing_columns = sorted(required_columns - set(columns))
    if missing_columns:
        raise P0GuardError(
            "canonical CSV is missing required columns: "
            + ", ".join(missing_columns)
        )

    def grouped(field: str) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = defaultdict(
            lambda: {"rows": 0, "amount_krw": 0}
        )
        for row in rows:
            key = str(row.get(field) or "")
            result[key]["rows"] += 1
            result[key]["amount_krw"] += _amount(row.get("krw"))
        return dict(sorted(result.items()))

    def selected(predicate: Any) -> dict[str, int]:
        selected_rows = [row for row in rows if predicate(row)]
        return {
            "rows": len(selected_rows),
            "amount_krw": sum(_amount(row.get("krw")) for row in selected_rows),
        }

    return {
        "row_count": len(rows),
        "unique_uid_count": len({str(row.get("uid") or "") for row in rows}),
        "signed_amount_krw": sum(_amount(row.get("krw")) for row in rows),
        "columns": columns,
        "sources": grouped("src"),
        "buckets": grouped("bucket"),
        "refund_census": {
            "negative_amount": selected(
                lambda row: _amount(row.get("krw")) < 0
            ),
            "cancel_flag": selected(
                lambda row: str(row.get("cancel") or "").lower()
                in {"true", "1"}
            ),
            "orig_appr_present": selected(
                lambda row: bool(str(row.get("orig_appr") or "").strip())
            ),
            "clearing_buckets": {
                bucket: selected(
                    lambda row, bucket=bucket: row.get("bucket") == bucket
                )
                for bucket in ("전기예약_환불", "취소환불")
            },
        },
    }


def _safe_path(root: Path, relative_path: object) -> Path:
    relative = Path(str(relative_path or ""))
    if not relative_path or relative.is_absolute():
        raise P0GuardError(f"input path must be repository-relative: {relative}")
    root_resolved = root.resolve()
    path = (root_resolved / relative).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise P0GuardError(f"input path escapes repository root: {relative}") from exc
    return path


def _record_count(path: Path) -> int | None:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return len(payload)
        if isinstance(payload, dict):
            records = payload.get("records")
            return len(records) if isinstance(records, list) else len(payload)
    return None


def _signed_amount_krw(path: Path) -> int | None:
    if path.suffix.lower() != ".csv":
        return None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return 0
    amount_field = (
        "krw" if "krw" in rows[0]
        else "amount" if "amount" in rows[0]
        else ""
    )
    if not amount_field:
        return None
    return sum(_amount(row.get(amount_field)) for row in rows)


def validate_input_contract(
    root: Path,
    contract: Mapping[str, object],
    stage: str,
) -> dict[str, object]:
    """Validate one stage's required/optional inputs without mutating them.

    Every selected entry must explicitly say ``required`` or ``optional``.
    Missing required files and any checksum/size/record-count drift are fatal.
    Missing optional files are returned as a visible diagnostic.
    """
    policies = contract.get("stage_policies")
    if not isinstance(policies, dict) or stage not in policies:
        raise P0GuardError(f"unknown input-contract stage: {stage}")
    entries = contract.get("inputs")
    if not isinstance(entries, list):
        raise P0GuardError("input contract must contain an inputs list")

    errors: list[str] = []
    checked: list[str] = []
    missing_optional: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("input entry is not an object")
            continue
        stage_requirements = entry.get("stages")
        if not isinstance(stage_requirements, dict) or stage not in stage_requirements:
            continue
        requirement = stage_requirements[stage]
        if requirement not in {"required", "optional"}:
            errors.append(
                f"{entry.get('path')}: invalid requirement {requirement!r}"
            )
            continue
        try:
            path = _safe_path(root, entry.get("path"))
        except P0GuardError as exc:
            errors.append(str(exc))
            continue
        display_path = str(entry.get("path"))
        if not path.exists():
            if requirement == "required":
                errors.append(f"{display_path}: required input is missing")
            else:
                missing_optional.append(display_path)
            continue
        if not path.is_file():
            errors.append(f"{display_path}: input is not a regular file")
            continue

        expected_hash = str(entry.get("sha256") or "")
        actual_hash = file_sha256(path)
        if expected_hash and actual_hash != expected_hash:
            errors.append(
                f"{display_path}: sha256 {actual_hash} != {expected_hash}"
            )
        expected_size = entry.get("bytes")
        if expected_size is not None and path.stat().st_size != int(expected_size):
            errors.append(
                f"{display_path}: bytes {path.stat().st_size} != {expected_size}"
            )
        expected_records = entry.get("record_count")
        if expected_records is not None:
            actual_records = _record_count(path)
            if actual_records != int(expected_records):
                errors.append(
                    f"{display_path}: records {actual_records} != "
                    f"{expected_records}"
                )
        expected_amount = entry.get("signed_amount_krw")
        if expected_amount is not None:
            actual_amount = _signed_amount_krw(path)
            if actual_amount != int(expected_amount):
                errors.append(
                    f"{display_path}: signed amount {actual_amount} != "
                    f"{expected_amount}"
                )
        checked.append(display_path)

    if errors:
        raise P0GuardError("; ".join(errors))
    return {
        "stage": stage,
        "checked": sorted(checked),
        "missing_optional": sorted(missing_optional),
        "passed": True,
    }


def validate_frozen_stage(
    root: Path,
    stage: str,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, object]:
    """Load the frozen P0 manifest and fail closed for one pipeline stage."""
    path = _safe_path(root, manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    contract = manifest.get("input_contract")
    if not isinstance(contract, dict):
        raise P0GuardError("frozen manifest is missing input_contract")
    return validate_input_contract(root, contract, stage)


def validate_candidate_against_frozen_canonical(
    root: Path,
    candidate_rows: Iterable[Mapping[str, object]],
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, object]:
    """Hard-fail a final projection that loses or mutates frozen events.

    Display notes may be enriched, but the event key, source, amount, bucket,
    cancellation flag and original approval relation must reproduce the frozen
    reference until an explicit superseding decision manifest is introduced.
    """
    path = _safe_path(root, manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    canonical = manifest.get("canonical")
    if not isinstance(canonical, dict):
        raise P0GuardError("frozen manifest is missing canonical")
    canonical_path = _safe_path(root, canonical.get("path"))
    actual_sha256 = file_sha256(canonical_path)
    expected_sha256 = str(canonical.get("sha256") or "")
    if not expected_sha256 or actual_sha256 != expected_sha256:
        raise P0GuardError(
            "frozen canonical sha256 drift: "
            f"{actual_sha256} != {expected_sha256 or '<missing>'}"
        )
    expected_bytes = canonical.get("bytes")
    if (
        expected_bytes is not None
        and canonical_path.stat().st_size != int(expected_bytes)
    ):
        raise P0GuardError(
            "frozen canonical byte-size drift: "
            f"{canonical_path.stat().st_size} != {expected_bytes}"
        )
    with canonical_path.open(encoding="utf-8-sig", newline="") as handle:
        frozen_rows = list(csv.DictReader(handle))
    rows = [dict(row) for row in candidate_rows]
    invariant_fields = (
        "src",
        "use_date",
        "post_date",
        "card4",
        "user",
        "merchant",
        "biz",
        "country",
        "currency",
        "foreign",
        "krw",
        "vat",
        "tax_type",
        "status",
        "biz_no",
        "bucket",
        "account",
        "cancel",
        "cost_type",
        "vat_tag",
        "appr",
        "orig_appr",
    )

    def keyed(items: Iterable[Mapping[str, object]]) -> dict[str, tuple[str, ...]]:
        result: dict[str, tuple[str, ...]] = {}
        duplicates: list[str] = []
        for row in items:
            uid = str(row.get("uid") or "")
            if not uid or uid in result:
                duplicates.append(uid or "<missing>")
                continue
            result[uid] = tuple(str(row.get(field) or "") for field in invariant_fields)
        if duplicates:
            raise P0GuardError(
                "candidate projection has missing/duplicate uid: "
                + ", ".join(duplicates[:10])
            )
        return result

    frozen = keyed(frozen_rows)
    candidate = keyed(rows)
    missing = sorted(set(frozen) - set(candidate))
    added = sorted(set(candidate) - set(frozen))
    mutated = sorted(
        uid for uid in set(frozen) & set(candidate)
        if frozen[uid] != candidate[uid]
    )
    frozen_total = sum(_amount(row.get("krw")) for row in frozen_rows)
    candidate_total = sum(_amount(row.get("krw")) for row in rows)
    if missing or added or mutated or candidate_total != frozen_total:
        raise P0GuardError(
            "frozen canonical reproduction failed: "
            f"missing={missing[:10]} added={added[:10]} "
            f"mutated={mutated[:10]} amount={candidate_total}!={frozen_total}"
        )
    return {
        "passed": True,
        "row_count": len(rows),
        "signed_amount_krw": candidate_total,
        "canonical_sha256": actual_sha256,
    }


def workbook_release_facts(
    workbook_path: Path,
    canonical_path: Path,
) -> dict[str, object]:
    """Measure the blocked v76 workbook against the current canonical CSV."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        raise P0GuardError("openpyxl is required to inspect XLSX artifacts") from exc

    with canonical_path.open(encoding="utf-8-sig", newline="") as handle:
        canonical_rows = list(csv.DictReader(handle))
    canonical_amounts = {
        str(row["uid"]): _amount(row.get("krw")) for row in canonical_rows
    }
    canonical_total = sum(canonical_amounts.values())
    preperiod_refund = sum(
        _amount(row.get("krw"))
        for row in canonical_rows
        if row.get("bucket") == "전기예약_환불"
    )

    workbook = openpyxl.load_workbook(
        workbook_path, read_only=True, data_only=False
    )
    occurrences: Counter[str] = Counter()
    detail_amount = 0
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            if (
                len(row) >= 12
                and isinstance(row[11], str)
                and row[11] in canonical_amounts
            ):
                occurrences[row[11]] += 1
                detail_amount += _amount(row[4])
    summary_rows = [
        row
        for row in workbook["총괄"].iter_rows(values_only=True)
        if row and row[0] == "합계"
    ]
    validation_rows = [
        row
        for row in workbook["검증"].iter_rows(values_only=True)
        if row and row[0] == "함수 검산(탭 합계 SUM 재합산)"
    ]
    sheet_count = len(workbook.sheetnames)
    workbook.close()
    if len(summary_rows) != 1 or len(validation_rows) != 1:
        raise P0GuardError("v76 workbook summary/validation rows are ambiguous")

    cached = openpyxl.load_workbook(
        workbook_path, read_only=True, data_only=True
    )
    cached_rows = [
        row
        for row in cached["검증"].iter_rows(values_only=True)
        if row and row[0] == "함수 검산(탭 합계 SUM 재합산)"
    ]
    cached_value = cached_rows[0][4] if len(cached_rows) == 1 else None
    cached.close()

    summary = summary_rows[0]
    validation = validation_rows[0]
    return {
        "sha256": file_sha256(workbook_path),
        "bytes": workbook_path.stat().st_size,
        "sheet_count": sheet_count,
        "canonical_uid_rows": len(occurrences),
        "duplicate_canonical_uid_rows": sum(
            count - 1 for count in occurrences.values() if count > 1
        ),
        "missing_canonical_uid_rows": len(
            set(canonical_amounts) - set(occurrences)
        ),
        "canonical_uid_amount_krw": detail_amount,
        "canonical_amount_krw": canonical_total,
        "summary_ai_expense_krw": _amount(summary[2]),
        "summary_row_count": int(summary[8]),
        "summary_difference_krw": _amount(summary[2]) - canonical_total,
        "preperiod_refund_amount_krw": preperiod_refund,
        "validation_formula_present": bool(
            isinstance(validation[4], str) and validation[4].startswith("=")
        ),
        "validation_formula_cached_value": cached_value,
    }


def pending_report_release_facts(
    summary_path: Path,
    dispositions_path: Path,
) -> dict[str, object]:
    """Measure the blocked 2026-07-27 pending-review report."""
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    with dispositions_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        "summary_sha256": file_sha256(summary_path),
        "summary_bytes": summary_path.stat().st_size,
        "dispositions_sha256": file_sha256(dispositions_path),
        "dispositions_bytes": dispositions_path.stat().st_size,
        "disposition_rows": len(rows),
        "dispositions": dict(
            sorted(Counter(str(row["disposition"]) for row in rows).items())
        ),
        "reason_codes": dict(
            sorted(Counter(str(row["reason_code"]) for row in rows).items())
        ),
        "summary_ota": summary["ota"],
    }


def verify_release_block(
    root: Path,
    block: Mapping[str, object],
) -> dict[str, object]:
    """Fail when a present blocked artifact drifts from its recorded facts."""
    if block.get("status") != "blocked":
        raise P0GuardError(f"{block.get('id')}: release status must be blocked")
    paths = block.get("paths")
    if not isinstance(paths, dict):
        raise P0GuardError(f"{block.get('id')}: paths must be an object")
    resolved = {
        key: _safe_path(root, value) for key, value in paths.items()
    }
    missing = sorted(
        str(paths[key]) for key, path in resolved.items() if not path.exists()
    )
    if missing:
        if block.get("missing_artifact_policy") != "remain_blocked":
            raise P0GuardError(
                f"{block.get('id')}: artifact files are missing: "
                + ", ".join(missing)
            )
        return {"available": False, "missing": missing, "status": "blocked"}

    kind = block.get("kind")
    if kind == "xlsx":
        actual = workbook_release_facts(
            resolved["artifact"], resolved["canonical"]
        )
    elif kind == "pending_report":
        actual = pending_report_release_facts(
            resolved["summary"], resolved["dispositions"]
        )
    else:
        raise P0GuardError(f"{block.get('id')}: unsupported artifact kind {kind}")
    expected = block.get("observed")
    if actual != expected:
        raise P0GuardError(
            f"{block.get('id')}: blocked artifact facts drifted\n"
            f"expected={json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
            f"actual={json.dumps(actual, ensure_ascii=False, sort_keys=True)}"
        )
    return {"available": True, "observed": actual, "status": "blocked"}
