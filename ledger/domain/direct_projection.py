"""Build an isolated, fail-closed candidate from direct card sources only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Iterable

from ledger import cardindex
from ledger.domain.direct_sources import import_all
from ledger.domain.ledger_db import connect, initialize
from ledger.domain.source_adapters import (
    adapt_ota_record,
)
from ledger.domain.transition_gates_v2 import (
    PARSER_BUNDLE_VERSION,
    REQUIRED_INPUTS,
    SCHEMA_VERSION,
    build_gate_report,
    candidate_semantic_sha256,
    gate_report_sha256,
    input_manifest_sha256,
)


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
SCHEMA = HERE / "direct_projection_schema.sql"
RUNTIME_CODE_PATHS = (
    Path("ledger/cardindex.py"),
    Path("ledger/domain/han_normalizer.py"),
    Path("ledger/domain/han_master_candidate.py"),
    Path("ledger/domain/han_master_authority.json"),
    Path("ledger/domain/direct_lineage_annex.py"),
    Path("ledger/domain/schema.sql"),
    Path("ledger/domain/decision_integrity.py"),
    Path("ledger/domain/source_adapters.py"),
    Path("ledger/domain/direct_sources.py"),
    Path("ledger/domain/ledger_db.py"),
    Path("ledger/domain/direct_projection_schema.sql"),
    Path("ledger/domain/direct_projection.py"),
    Path("ledger/domain/transition_gates_v2.py"),
    Path("ledger/domain/p07_manifest.py"),
    Path("ledger/domain/direct_owner_review.py"),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _relative_file(path: Path, repository_root: Path) -> tuple[Path, str]:
    root = repository_root.resolve()
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source_outside_repository:{resolved}") from exc
    if not resolved.is_file():
        raise ValueError(f"source_not_file:{relative.as_posix()}")
    return resolved, relative.as_posix()


def _key_set_sha256(keys: Iterable[str]) -> str:
    ordered = sorted(str(key) for key in keys)
    return _sha256_bytes(("\n".join(ordered) + "\n").encode("utf-8"))


def _read_cards(ledger_dir: Path) -> list[dict[str, object]]:
    return [dict(card) for card in cardindex.build_cards(ledger_dir=ledger_dir)]


def _card_keys_by_artifact(
    ledger_dir: Path,
) -> dict[str, list[str]]:
    by_artifact = {
        spec["source_kind"]: []
        for spec in REQUIRED_INPUTS
        if str(spec["source_kind"]).startswith("card_raw:")
    }
    artifact_for_prefix = {
        str(spec["record_prefix"]).split(":")[-2]: str(spec["source_kind"])
        for spec in REQUIRED_INPUTS
        if str(spec["source_kind"]).startswith("card_raw:")
    }
    for card in _read_cards(ledger_dir):
        raw_record_id = str(card["raw_record_id"])
        artifact = raw_record_id.split(":", 1)[0]
        source_kind = artifact_for_prefix.get(artifact)
        if source_kind is None:
            raise ValueError(f"unexpected_card_parser_input:{artifact}")
        by_artifact[source_kind].append(f"{card['src']}:{raw_record_id}")
    return by_artifact


def _manual_keys(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("manual_header_missing")
        rows = list(reader)
    if not rows:
        raise ValueError("manual_source_empty")
    return [f"{row.get('tab')}:{row.get('row')}" for row in rows]


def _ota_keys(path: Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("records", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError("ota_source_empty")
    keys: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"ota_record_not_object:{index}")
        clean = adapt_ota_record(row)
        keys.append(str(clean.get("message_id") or f"row:{index}"))
    return keys


def _validate_unique_keys(source_kind: str, keys: list[str]) -> None:
    if not keys:
        raise ValueError(f"parsed_source_empty:{source_kind}")
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate_source_key:{source_kind}")


def build_source_inventory(
    ledger_dir: Path,
    repository_root: Path = REPOSITORY_ROOT,
) -> list[dict[str, object]]:
    """Parse all seven physical inputs before creating a candidate database."""
    root = repository_root.resolve()
    ledger = ledger_dir.resolve(strict=True)
    try:
        ledger.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"ledger_outside_repository:{ledger}") from exc

    card_keys = _card_keys_by_artifact(ledger)
    inventory: list[dict[str, object]] = []
    for spec in REQUIRED_INPUTS:
        source_kind = str(spec["source_kind"])
        resolved, relative_path = _relative_file(
            root / str(spec["relative_path"]),
            root,
        )
        raw = resolved.read_bytes()
        if not raw:
            raise ValueError(f"source_empty:{relative_path}")
        if source_kind == "manual_ledger":
            keys = _manual_keys(resolved)
        elif source_kind == "ota_mail":
            keys = _ota_keys(resolved)
        else:
            keys = card_keys[source_kind]
        _validate_unique_keys(source_kind, keys)
        lf_hash = None
        if resolved.suffix.lower() != ".xlsx":
            normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            lf_hash = _sha256_bytes(normalized)
        inventory.append(
            {
                "source_kind": source_kind,
                "relative_path": relative_path,
                "raw_sha256": _sha256_bytes(raw),
                "lf_sha256": lf_hash,
                "byte_count": len(raw),
                "record_count": len(keys),
                "key_set_sha256": _key_set_sha256(keys),
                "parser_version": PARSER_BUNDLE_VERSION,
            }
        )
    inventory.sort(
        key=lambda row: (str(row["source_kind"]), str(row["relative_path"]))
    )
    return inventory


def code_bundle_descriptor(
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    root = repository_root.resolve()
    files: list[dict[str, str]] = []
    for relative in sorted(RUNTIME_CODE_PATHS, key=lambda path: path.as_posix()):
        resolved, normalized = _relative_file(root / relative, root)
        files.append(
            {
                "relative_path": normalized,
                "raw_sha256": _sha256_bytes(resolved.read_bytes()),
            }
        )
    return {
        "files": files,
        "code_bundle_sha256": _sha256_bytes(_canonical_json_bytes(files)),
    }


def _git_head(repository_root: Path = REPOSITORY_ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        text=True,
    ).strip()


def _apply_schema(db: object) -> None:
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='direct_projection_runs'").fetchone()
    if exists:
        _assert_existing_v3_schema(db)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))

def _assert_existing_v3_schema(db:object)->None:
    reference=sqlite3.connect(":memory:")
    try:
        reference.executescript(SCHEMA.read_text(encoding="utf-8"))
        expected={str(x[0]):(str(x[1]),str(x[2])) for x in reference.execute("SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL")}
    finally:reference.close()
    actual_all={str(x[0]):(str(x[1]),str(x[2]),str(x[3])) for x in db.execute("SELECT name,type,sql,tbl_name FROM sqlite_master WHERE sql IS NOT NULL")}
    actual={name:(value[0],value[1]) for name,value in actual_all.items() if name in expected}
    protected={"direct_projection_runs","direct_projection_inputs","direct_payment_projection_links","direct_projection_validations"}
    extras={name for name,value in actual_all.items() if name not in expected and (value[2] in protected or name.startswith("direct_projection"))}
    if actual!=expected or extras:raise ValueError("direct_projection_schema_v3_contract_mismatch")
    versions={str(x[0]) for x in db.execute("SELECT DISTINCT schema_version FROM direct_projection_runs")}
    if versions and versions!={SCHEMA_VERSION}:raise ValueError("direct_projection_schema_version_mismatch")


def _stable_external_key(row: object) -> str:
    identity = {
        "card_event_id": str(row["card_event_id"]),
        "event_role": str(row["event_role"]),
        "source_kind": str(row["source_kind"]),
        "source_key": str(row["source_key"]),
    }
    return "direct:" + _sha256_bytes(_canonical_json_bytes(identity))


def project_card_payments(db: object, run_id: str) -> int:
    """Project card facts and their business fields without legacy matching."""
    conflict = db.execute(
        """SELECT source_kind, source_key FROM direct_source_records
           GROUP BY source_kind, source_key
           HAVING COUNT(DISTINCT source_sha256)>1
           ORDER BY source_kind, source_key LIMIT 1"""
    ).fetchone()
    if conflict:
        raise ValueError(f"source_key_content_conflict:{conflict[0]}:{conflict[1]}")
    rows = db.execute(
        """
        SELECT
            d.id AS direct_payment_id,
            d.event_role,
            d.card_event_id,
            d.amount_krw,
            d.transaction_type,
            s.source_kind,
            s.source_key,
            s.source_sha256,
            e.source_system,
            e.occurred_on,
            e.merchant,
            e.approval_number
        FROM direct_normalized_payments d
        JOIN direct_source_records s ON s.id=d.source_record_id
        JOIN direct_card_events e ON e.source_record_id=d.source_record_id
        WHERE s.source_kind='card_raw'
        ORDER BY s.source_key, d.event_role, d.card_event_id
        """
    ).fetchall()
    if not rows:
        raise ValueError("direct_card_payments_empty")
    for row in rows:
        external_key = _stable_external_key(row)
        fingerprint = _sha256_bytes(
            _canonical_json_bytes(
                {
                    "external_key": external_key,
                    "source_sha256": row["source_sha256"],
                    "source_system": row["source_system"],
                    "occurred_on": row["occurred_on"],
                    "merchant": row["merchant"],
                    "approval_number": row["approval_number"],
                    "amount_krw": row["amount_krw"],
                    "transaction_type": row["transaction_type"],
                }
            )
        )
        cursor = db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint,
                source_system, occurred_on, merchant, amount_krw,
                approval_number, transaction_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                external_key,
                row["card_event_id"],
                fingerprint,
                row["source_system"],
                row["occurred_on"],
                row["merchant"],
                row["amount_krw"],
                row["approval_number"],
                row["transaction_type"],
            ),
        )
        db.execute(
            """
            INSERT INTO direct_payment_projection_links(
                run_id, direct_payment_id, payment_id
            ) VALUES (?, ?, ?)
            """,
            (run_id, row["direct_payment_id"], cursor.lastrowid),
        )
    return len(rows)


def candidate_semantic_snapshot(db: object, run_id: str) -> str:
    return candidate_semantic_sha256(db, run_id)

def _activate_candidate(db:object,run_id:str,report_hash:str,validation_sha256:str)->None:
    run=db.execute("SELECT input_manifest_sha256,candidate_semantic_sha256,gate_report_sha256 FROM direct_projection_runs WHERE run_id=?",(run_id,)).fetchone()
    if run is None or candidate_semantic_snapshot(db,run_id)!=run[1] or run[2]!=report_hash:
        raise RuntimeError("candidate_activation_revalidation_failed")
    cursor=db.execute("""UPDATE direct_projection_runs SET status='passed',activation_validation_sha256=(
        SELECT validation_sha256 FROM direct_projection_validations WHERE run_id=direct_projection_runs.run_id)
      WHERE run_id=? AND status='building' AND gate_report_sha256=?
        AND EXISTS (SELECT 1 FROM direct_projection_validations v
          WHERE v.run_id=direct_projection_runs.run_id AND v.status='passed'
            AND v.input_manifest_sha256=direct_projection_runs.input_manifest_sha256
            AND v.candidate_semantic_sha256=direct_projection_runs.candidate_semantic_sha256
            AND v.validation_sha256=?)""",(run_id,report_hash,validation_sha256))
    if cursor.rowcount!=1:raise RuntimeError("candidate_activation_precondition_failed")


def _historical_comparators(
    repository_root: Path = REPOSITORY_ROOT,
) -> list[dict[str, object]]:
    root = repository_root.resolve()
    candidates = (
        (
            Path("ledger/baselines/p05_latest_20260725/manifest.json"),
            "legacy_manifest_comparator",
        ),
        (
            Path("ledger/baselines/p6_transition_gate_report.json"),
            "legacy_gate_comparator",
        ),
        (
            Path("ledger/data/classified_v14.csv"),
            "historical_classified_comparator",
        ),
    )
    result: list[dict[str, object]] = []
    for relative, role in candidates:
        resolved, normalized = _relative_file(root / relative, root)
        result.append(
            {
                "relative_path": normalized,
                "role": role,
                "raw_sha256": _sha256_bytes(resolved.read_bytes()),
            }
        )
    return result


def _write_artifact_directory(
    output_dir: Path,
    slug: str,
    report: dict[str, object],
    manifest: dict[str, object],
) -> Path:
    output = output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"output_directory_exists:{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-staging-",
            dir=str(output.parent),
        )
    )
    try:
        run_dir = staging / slug
        run_dir.mkdir()
        (run_dir / "gate_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        sealed_manifest=dict(manifest);sealed_manifest["manifest_content_sha256"]=_manifest_content_sha256(sealed_manifest)
        (run_dir / "blocker_manifest.json").write_text(
            json.dumps(sealed_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, output)
        return output / slug
    finally:
        if staging.exists():
            for child in sorted(staging.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            staging.rmdir()


def _atomic_replace_json(path: Path, payload: dict[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        sealed=dict(payload);sealed["manifest_content_sha256"]=_manifest_content_sha256(sealed)
        data=(json.dumps(sealed,ensure_ascii=False,indent=2)+"\n").encode()
        view=memoryview(data)
        while view:view=view[os.write(descriptor,view):]
        os.fsync(descriptor);os.close(descriptor);descriptor=-1
        os.replace(temporary, path)
        parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:os.fsync(parent_fd)
        finally:os.close(parent_fd)
    finally:
        if descriptor>=0:os.close(descriptor)
        temporary.unlink(missing_ok=True)

def _manifest_content_sha256(payload:dict[str,object])->str:
    value=dict(payload);value.pop("manifest_content_sha256",None)
    return _sha256_bytes(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())


def _remove_sqlite_artifacts(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        candidate.unlink(missing_ok=True)

def _seal_private_directory(path:Path,names:tuple[str,...])->None:
    for name in names:
        target=path/name;os.chmod(target,0o400)
        fd=os.open(target,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try:os.fsync(fd)
    finally:os.close(fd)
    os.chmod(path,0o500)
    parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try:os.fsync(parent_fd)
    finally:os.close(parent_fd)


def _remove_new_artifact_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _reject_repository_output(
    path: Path,
    repository_root: Path,
    label: str,
) -> None:
    try:
        path.resolve().relative_to(repository_root.resolve())
    except ValueError:
        return
    raise ValueError(f"{label}_inside_repository:{path.resolve()}")


def build_direct_candidate(
    output_db: Path,
    ledger_dir: Path,
    *,
    output_dir: Path,
    manual_path: Path | None = None,
    ota_path: Path | None = None,
    code_commit: str | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    owner_review_output: Path | None = None,
    owner_review_manifest: Path | None = None,
    owner_review_events: Path | None = None,
    han_equality_output:Path|None=None,
    han_authority_sha256:str|None=None,
) -> dict[str, object]:
    """Build, gate, and publish only a fully passing shadow candidate."""
    root = repository_root.resolve()
    ledger = ledger_dir.resolve(strict=True)
    output_database = output_db.resolve()
    artifact_root = output_dir.resolve()
    _reject_repository_output(output_database, root, "candidate_output")
    _reject_repository_output(artifact_root, root, "artifact_output")
    if owner_review_output is not None:
        owner_target = owner_review_output.resolve()
        _reject_repository_output(owner_target, root, "owner_review_output")
        if owner_target == output_database or output_database in owner_target.parents or owner_target in output_database.parents:
            raise ValueError("owner_review_output_candidate_overlap")
        if owner_target == artifact_root or artifact_root in owner_target.parents or owner_target in artifact_root.parents:
            raise ValueError("owner_review_output_artifact_overlap")
    if output_database.exists():
        raise FileExistsError(f"destination_exists:{output_database}")
    if artifact_root.exists():
        raise FileExistsError(f"output_directory_exists:{artifact_root}")
    if (han_equality_output is None)!=(han_authority_sha256 is None):raise ValueError("han_equality_context_incomplete")
    if han_equality_output is not None:
        _reject_repository_output(han_equality_output.resolve(),root,"han_equality_output")
        if han_equality_output.exists():raise FileExistsError(f"han_equality_output_exists:{han_equality_output}")

    expected_manual = (ledger / "data/manual_v4.csv").resolve(strict=True)
    expected_ota = (ledger / "data/ota_mail_index.json").resolve(strict=True)
    if manual_path is not None and manual_path.resolve(strict=True) != expected_manual:
        raise ValueError("manual_path_not_in_declared_inventory")
    if ota_path is not None and ota_path.resolve(strict=True) != expected_ota:
        raise ValueError("ota_path_not_in_declared_inventory")

    inventory = build_source_inventory(ledger, root)
    input_hash = input_manifest_sha256(inventory)
    actual_commit = _git_head(root)
    if code_commit is not None and code_commit != actual_commit:
        raise ValueError(
            f"code_commit_mismatch:expected={actual_commit}:actual={code_commit}"
        )
    bundle = code_bundle_descriptor(root)
    run_id = uuid.uuid4().hex

    output_database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_database.name}-candidate-",
        suffix=".db",
        dir=str(output_database.parent),
    )
    os.close(descriptor)
    temporary_db = Path(temporary_name)
    db = None
    candidate_installed = False
    artifacts_installed = False
    owner_review_installed = False
    activation_pointer_sha256=None
    try:
        db = connect(temporary_db)
        initialize(db)
        _apply_schema(db)
        db.execute(
            """
            INSERT INTO direct_projection_runs(
                run_id, status, schema_version, input_manifest_sha256,
                code_commit, code_bundle_sha256
            ) VALUES (?, 'building', ?, ?, ?, ?)
            """,
            (
                run_id,
                SCHEMA_VERSION,
                input_hash,
                actual_commit,
                bundle["code_bundle_sha256"],
            ),
        )
        for item in inventory:
            db.execute(
                """
                INSERT INTO direct_projection_inputs(
                    run_id, source_kind, relative_path, raw_sha256,
                    lf_sha256, byte_count, key_set_sha256, record_count,
                    parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["source_kind"],
                    item["relative_path"],
                    item["raw_sha256"],
                    item["lf_sha256"],
                    item["byte_count"],
                    item["key_set_sha256"],
                    item["record_count"],
                    item["parser_version"],
                ),
            )
        import_all(db, ledger, expected_manual, expected_ota)
        projected = project_card_payments(db, run_id)
        semantic_hash = candidate_semantic_snapshot(db, run_id)
        db.execute(
            """
            UPDATE direct_projection_runs
            SET candidate_semantic_sha256=?
            WHERE run_id=?
            """,
            (semantic_hash, run_id),
        )
        db.commit()

        han_context=None;han_validation_result=None
        if han_equality_output is not None:
            db.close();db=None
            from ledger.domain.han_master_candidate import build_candidate as build_han_candidate,install_han_equality_validation
            han_context={"directory":han_equality_output,"candidate_db":temporary_db,"run_id":run_id,
              "input_manifest_sha256":input_hash,"candidate_semantic_sha256_expected":semantic_hash,
              "authority_sha256_expected":str(han_authority_sha256),"ledger_dir":ledger,"master_path":ledger/"master_ledger.csv"}
            build_han_candidate(han_equality_output,candidate_db=temporary_db,run_id=run_id,input_manifest_sha256=input_hash,
              candidate_semantic_sha256_expected=semantic_hash,authority_sha256_expected=str(han_authority_sha256),ledger_dir=ledger)
            han_validation_result=install_han_equality_validation(**han_context)

        comparators = _historical_comparators(root)
        expected_provenance = {
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_BUNDLE_VERSION,
            "input_manifest_sha256": input_hash,
            "candidate_semantic_sha256": semantic_hash,
            "code_commit": actual_commit,
            "code_bundle_sha256": bundle["code_bundle_sha256"],
        }
        report = build_gate_report(
            temporary_db,
            run_id,
            repository_root=root,
            expected_provenance=expected_provenance,
            historical_comparators=comparators,
            han_equality_context=han_context,
        )
        created_probe=sqlite3.connect(f"file:{temporary_db}?mode=ro&immutable=1",uri=True)
        try:report["run_created_at"]=str(created_probe.execute("SELECT created_at FROM direct_projection_runs WHERE run_id=?",(run_id,)).fetchone()[0])
        finally:created_probe.close()
        if han_validation_result is not None:
            report["han_equality"]={"private_package_path":str(han_equality_output),
              "package_set_sha256":han_validation_result["package_set_sha256"],
              "state":"activated" if bool(report["passed"]) else "private_validated_not_activated"}
        report_hash = gate_report_sha256(report)
        report["gate_report_sha256"] = report_hash
        passed = bool(report["passed"])
        if db is None:db=connect(temporary_db)
        db.execute(
            """
            UPDATE direct_projection_runs
            SET status=?, gate_report_sha256=?
            WHERE run_id=?
            """,
            ("building" if passed else "failed", report_hash, run_id),
        )
        db.commit()

        manifest = {
            "format_version": 2,
            "run_id": run_id,
            "artifact_state": "pending_activation" if passed else "not_published",
            "cutover_policy": report["cutover_policy"],
            "input_manifest_sha256": input_hash,
            "candidate_semantic_sha256": semantic_hash,
            "gate_report_sha256": report_hash,
            "code_commit": actual_commit,
            "code_bundle_sha256": bundle["code_bundle_sha256"],
            "code_bundle": bundle["files"],
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_BUNDLE_VERSION,
            "inputs": inventory,
            "historical_comparators": comparators,
            "approved_transitions": {
                "provided": 0,
                "mode": "none",
            },
            "failed_gates": [
                str(gate["name"])
                for gate in report["gates"]
                if not bool(gate["passed"])
            ],
            "candidate_payment_count": projected,
            "run_created_at":report["run_created_at"],
            "han_equality":report.get("han_equality"),
        }
        owner_review_result = None
        if owner_review_manifest is not None or owner_review_events is not None:
            if owner_review_manifest is None or owner_review_events is None:
                raise ValueError("owner_review_input_incomplete")
            from ledger.domain.direct_owner_review import load_owner_review
            owner_review_result = load_owner_review(
                owner_review_manifest, owner_review_events, db=db, run_id=run_id,
                report=report, provenance={
                    "source_run_id": run_id, "code_commit": actual_commit,
                    "code_bundle_sha256": bundle["code_bundle_sha256"],
                    "gate_report_sha256": report_hash, "source_inventory": inventory,
                },
            )
        if owner_review_output is not None:
            from ledger.domain.direct_owner_review import build_owner_review, write_owner_review
            owner_review_result = write_owner_review(
                build_owner_review(
                    db, run_id, report,
                    provenance={
                        "code_commit": actual_commit,
                        "code_bundle_sha256": bundle["code_bundle_sha256"],
                        "gate_report_sha256": report_hash,
                        "source_inventory": inventory,
                    },
                ),
                owner_review_output,
                repository_root=root,
            )
            owner_review_installed = True
        slug = f"{run_id}-{semantic_hash[:12]}"

        if passed:
            db.close()
            db = None
            os.replace(temporary_db, output_database)
            candidate_installed = True
            manifest["candidate_db"] = {
                "path": output_database.as_posix(),
                "candidate_semantic_sha256": semantic_hash,
            }
        report_dir = _write_artifact_directory(
            artifact_root,
            slug,
            report,
            manifest,
        )
        artifacts_installed = True
        if passed:
            validation=(report["gates"][3].get("actual") or {}).get("validation")
            if not validation:raise RuntimeError("candidate_activation_validation_missing")
            if han_context is None:raise RuntimeError("candidate_activation_package_context_missing")
            from ledger.domain.han_master_candidate import verify_candidate as verify_han_candidate,_read_regular_nofollow,FILES
            activation_context={**han_context,"candidate_db":output_database}
            verified_package=verify_han_candidate(**activation_context)
            verified_envelope=verified_package["validation_envelope"]
            captured=verified_package["_verified_file_bytes"]
            _seal_private_directory(han_equality_output,FILES)
            activation = connect(output_database)
            try:
                activation.execute("BEGIN IMMEDIATE")
                if {name:_read_regular_nofollow(han_equality_output/name,mode=0o400) for name in FILES}!=captured:
                    raise RuntimeError("candidate_activation_package_changed")
                if any(validation[key]!=verified_envelope[key] for key in verified_envelope):
                    raise RuntimeError("candidate_activation_validation_envelope_mismatch")
                if input_manifest_sha256(build_source_inventory(ledger,root))!=input_hash or gate_report_sha256(report)!=report_hash:
                    raise RuntimeError("candidate_activation_context_changed")
                validation_sha=str(validation["validation_sha256"])
                _activate_candidate(activation,run_id,report_hash,validation_sha)
                activation.commit()
                activation.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                activation.execute("PRAGMA journal_mode=DELETE")
            finally:
                activation.close()
            if any(os.path.lexists(str(output_database)+suffix) for suffix in ("-wal","-shm","-journal")):
                raise RuntimeError("candidate_activation_sidecar_present")
            verify_han_candidate(**{**activation_context,"verification_mode":"activated"})
            os.chmod(output_database,0o400);db_fd=os.open(output_database,os.O_RDONLY)
            try:os.fsync(db_fd)
            finally:os.close(db_fd)
            final_db_sha=_sha256_bytes(output_database.read_bytes())
            manifest["artifact_state"] = "candidate_ready_for_shadow"
            if manifest.get("han_equality"):manifest["han_equality"]["state"]="activated"
            manifest["candidate_db"]["final_seal_sha256"]=final_db_sha
            manifest["candidate_db"]["mode"]="0400"
            _atomic_replace_json(
                report_dir / "blocker_manifest.json",
                manifest,
            )
            activation_pointer_sha256=_manifest_content_sha256(manifest)
        return {
            "run_id": run_id,
            "passed": passed,
            "status": "candidate_ready_for_shadow" if passed else "blocked",
            "cutover_policy": report["cutover_policy"],
            "output_db": output_database.as_posix() if passed else None,
            "report_dir": report_dir.as_posix(),
            "input_manifest_sha256": input_hash,
            "candidate_semantic_sha256": semantic_hash,
            "gate_report_sha256": report_hash,
            "failed_gates": manifest["failed_gates"],
            "owner_review": owner_review_result,
            "activation_pointer_sha256":activation_pointer_sha256,
        }
    except Exception:
        if db is not None:
            try:
                db.execute(
                    """
                    UPDATE direct_projection_runs
                    SET status='failed'
                    WHERE run_id=?
                    """,
                    (run_id,),
                )
                db.commit()
            except Exception:
                pass
        if candidate_installed:
            _remove_sqlite_artifacts(output_database)
        # A successfully published diagnostic report is retained on later
        # activation failure; it is the auditable explanation for no cutover.
        if owner_review_installed and owner_review_output is not None:
            _remove_new_artifact_directory(owner_review_output.resolve())
        raise
    finally:
        if db is not None:
            db.close()
        _remove_sqlite_artifacts(temporary_db)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--manual", type=Path)
    parser.add_argument("--ota", type=Path)
    parser.add_argument("--code-commit")
    parser.add_argument("--owner-review-output", type=Path, help="write an external validation template")
    parser.add_argument("--owner-review-manifest", type=Path)
    parser.add_argument("--owner-review-events", type=Path)
    args = parser.parse_args()
    result = build_direct_candidate(
        args.output_db,
        args.ledger_dir,
        output_dir=args.output_dir,
        manual_path=args.manual,
        ota_path=args.ota,
        code_commit=args.code_commit,
        owner_review_output=args.owner_review_output,
        owner_review_manifest=args.owner_review_manifest,
        owner_review_events=args.owner_review_events,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
