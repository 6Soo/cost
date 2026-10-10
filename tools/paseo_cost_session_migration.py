"""Collect, verify, and permanently delete closed Paseo Codex sessions for COST.

Collection is read-only. Deletion is deliberately sequential and requires a
reviewed approval JSON whose transcript hashes match the frozen manifest.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import hashlib
import json
import msvcrt
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PASEO_EXE = Path(r"C:\Program Files\Paseo\Paseo.exe")
PASEO_RESOURCES = PASEO_EXE.parent / "resources"
PASEO_RUNNER = PASEO_RESOURCES / "app.asar.unpacked" / "dist" / "daemon" / "node-entrypoint-runner.js"
PASEO_CLI = PASEO_RESOURCES / "app.asar" / "node_modules" / "@getpaseo" / "cli" / "dist" / "index.js"
PASEO_ASAR = PASEO_RESOURCES / "app.asar"
POWERSHELL_EXE = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
EXPECTED_ROOT = Path(r"C:\AX\cost")
EXPECTED_WORK_DIR = EXPECTED_ROOT / ".paseo-session-migration-work-20260826"
EXPECTED_TRANSCRIPT_DIR = EXPECTED_WORK_DIR / "transcripts"
EXPECTED_MANIFEST = EXPECTED_WORK_DIR / "manifest.json"
EXPECTED_APPROVAL = EXPECTED_WORK_DIR / "approval.json"
EXPECTED_CANONICAL = (
    EXPECTED_ROOT
    / "docs"
    / "session-migration"
    / "COST_CODEX_SESSION_CONSOLIDATION_2026-08-26.md"
)
EXPECTED_LEDGER = (
    EXPECTED_ROOT
    / "docs"
    / "session-migration"
    / "COST_CODEX_SESSION_DELETION_LEDGER_2026-08-26.jsonl"
)
EXPECTED_PASEO_EXE_SHA256 = "0b67bf4762758af27b149b0fbb2e557f364a65f1cb5fbe144602839bb035eeed"
EXPECTED_PASEO_RUNNER_SHA256 = "1f4e8bcf57373018b7f9e0a0fc14cc0e7b51ab7f977a1339a52e2a7fac399c66"
EXPECTED_PASEO_ASAR_SHA256 = "1e74d8e05140bc6bee9e992dcea9056aa5b5a07b0525406364d4f8267a17d236"
EXPECTED_DELETE_HANDLER_SHA256 = "525dc3f59b1e7dc2c0f6424a2c6b42880376446aaca89df5b8e4ea198d83b38e"
EXPECTED_DELETE_HANDLER_BYTES = 1545
EXPECTED_BEGIN_DELETE_HELPER_SHA256 = "7855b0a0b22a63c697eb8345250808c201c85dac78bb142f1dc2adbe6c7baa1c"
EXPECTED_BEGIN_DELETE_HELPER_BYTES = 204
EXPECTED_STORAGE_DELETE_FENCE_SHA256 = "87baec64b440c1a99707cfb4b8be4418a0a576659ff2ed31d28327f75ae2cd0a"
EXPECTED_STORAGE_DELETE_FENCE_BYTES = 2229
EXPECTED_MANIFEST_SHA256 = "7630dd029b44d8f37d12427fd1377f8f41ea11a330d3e1c7fbc0668abc9c5876"
EXPECTED_APPROVAL_ID = "cost-closed-codex-20260826"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalized_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(value)))


def validate_agent_id(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError(f"Invalid Paseo agent ID for {context}: {value!r}")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise RuntimeError(f"Invalid Paseo agent ID for {context}: {value!r}") from exc
    if str(parsed) != value:
        raise RuntimeError(f"Paseo agent ID is not canonical lowercase UUID text for {context}: {value!r}")
    return value


def validate_thinking(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value) is None:
        raise RuntimeError(f"Invalid Paseo thinking value for {context}: {value!r}")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def paseo_command(args: Iterable[str]) -> list[str]:
    # PASEO_CLI lives inside app.asar. Electron can resolve it even though
    # pathlib cannot stat a path inside the archive.
    required = (PASEO_EXE, PASEO_RUNNER)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Bundled Paseo CLI component missing: {missing}")
    return [
        str(PASEO_EXE),
        "--disable-warning=DEP0040",
        str(PASEO_RUNNER),
        "node-script",
        str(PASEO_CLI),
        *args,
    ]


def paseo_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "ELECTRON_RUN_AS_NODE": "1",
            "PASEO_NODE_ENV": "production",
            "PASEO_DESKTOP_MANAGED": "1",
            "PASEO_CLI": str(PASEO_RESOURCES / "bin" / "paseo.cmd"),
        }
    )
    return env


def run_paseo_process(args: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        paseo_command(args),
        cwd=str(EXPECTED_ROOT),
        env=paseo_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def run_paseo(args: list[str], *, timeout: int = 90, attempts: int = 3) -> str:
    last_error = ""
    for attempt in range(1, attempts + 1):
        proc = run_paseo_process(args, timeout=timeout)
        if proc.returncode == 0:
            return proc.stdout
        last_error = (proc.stderr or proc.stdout).strip()
        if attempt < attempts:
            time.sleep(0.35 * attempt)
    raise RuntimeError(f"paseo {' '.join(args)} failed: {last_error}")


def run_paseo_json(args: list[str], *, timeout: int = 90, attempts: int = 3) -> Any:
    output = run_paseo(args, timeout=timeout, attempts=attempts)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Paseo returned non-JSON output for {args}: {output[:500]!r}") from exc


def classify_title(title: str) -> str:
    lowered = title.casefold()
    if "pipeline lightweighting" in lowered:
        return "pipeline-lightweighting"
    if any(token in lowered for token in ("웹앱", "architecture", "아키텍처")):
        return "webapp-architecture"
    if "agoda" not in lowered:
        return "other"
    if re.search(r"\b(c\d\d|u\d\d|s\d|p\d|batch|detail|dom)\b", lowered):
        return "agoda-browser-collection"
    if any(
        token in lowered
        for token in (
            "retry",
            "survey",
            "panel",
            "click-boundary",
            "live list",
            "parallel",
            "paseo recovery",
            "paseo continuation",
            "완료",
            "completed page",
        )
    ):
        return "agoda-browser-collection"
    return "agoda-accounting-and-policy"


def inspect_agent(agent_id: str) -> dict[str, Any]:
    validate_agent_id(agent_id, context="inspect")
    return run_paseo_json(["inspect", agent_id, "--json"], timeout=45)


def collect_transcript(agent_id: str) -> str:
    validate_agent_id(agent_id, context="transcript export")
    return run_paseo(["logs", agent_id], timeout=120)


def collect(args: argparse.Namespace) -> int:
    root = normalized_path(args.root)
    if root != normalized_path(str(EXPECTED_ROOT)):
        raise RuntimeError(f"Collection root is not the hard-pinned COST root: {args.root}")
    work_dir = Path(args.work_dir).resolve()
    manifest_path = Path(args.manifest).resolve()
    if work_dir != EXPECTED_WORK_DIR.resolve(strict=False):
        raise RuntimeError(f"Collection work directory is not hard-pinned: {work_dir}")
    if manifest_path != EXPECTED_MANIFEST.resolve(strict=False):
        raise RuntimeError(f"Collection manifest is not hard-pinned: {manifest_path}")
    if work_dir.exists():
        raise RuntimeError(f"Refusing to overwrite an existing frozen collection: {work_dir}")
    work_dir.mkdir(parents=True, exist_ok=False)
    transcript_dir = work_dir / "transcripts"
    transcript_dir.mkdir(exist_ok=False)

    listed = validate_agent_list(
        run_paseo_json(["ls", "--all", "--global", "--json"], timeout=90),
        scope="global collection inventory",
    )
    cost_agents = [item for item in listed if normalized_path(str(item.get("cwd", ""))) == root]

    inspections: dict[str, dict[str, Any]] = {}
    inspect_errors: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(inspect_agent, item["id"]): item["id"] for item in cost_agents}
        for future in concurrent.futures.as_completed(futures):
            agent_id = futures[future]
            try:
                inspections[agent_id] = future.result()
            except Exception as exc:  # keep the frozen inventory even if one inspect fails
                inspect_errors[agent_id] = str(exc)

    candidates = [
        item
        for item in cost_agents
        if item.get("status") == "closed" and str(item.get("provider", "")).startswith("codex/")
    ]
    transcript_results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(collect_transcript, item["id"]): item for item in candidates}
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            agent_id = item["id"]
            path = transcript_dir / f"{agent_id}.txt"
            try:
                transcript = future.result()
                payload = transcript.encode("utf-8")
                with path.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                transcript_results[agent_id] = {
                    "path": str(path),
                    "sha256": sha256_bytes(payload),
                    "bytes": len(payload),
                    "lines": transcript.count("\n") + (1 if transcript else 0),
                    "empty": not bool(transcript.strip()),
                    "error": None,
                }
            except Exception as exc:
                transcript_results[agent_id] = {
                    "path": str(path),
                    "sha256": None,
                    "bytes": 0,
                    "lines": 0,
                    "empty": True,
                    "error": str(exc),
                }

    all_records: list[dict[str, Any]] = []
    for item in cost_agents:
        agent_id = item["id"]
        inspected = inspections.get(agent_id)
        all_records.append(
            {
                "id": agent_id,
                "short_id": item.get("shortId"),
                "title": item.get("name"),
                "provider_model": item.get("provider"),
                "thinking": item.get("thinking"),
                "list_status": item.get("status"),
                "cwd": item.get("cwd"),
                "inspect": inspected,
                "inspect_error": inspect_errors.get(agent_id),
                "parent_agent_id": inspected.get("ParentAgentId") if inspected else None,
            }
        )

    candidate_records: list[dict[str, Any]] = []
    all_by_id = {record["id"]: record for record in all_records}
    for item in candidates:
        agent_id = item["id"]
        inspected = inspections.get(agent_id)
        children = sorted(
            record["id"] for record in all_records if record.get("parent_agent_id") == agent_id
        )
        candidate_records.append(
            {
                "id": agent_id,
                "title": item.get("name") or "",
                "cluster": classify_title(item.get("name") or ""),
                "provider_model": item.get("provider"),
                "thinking": item.get("thinking"),
                "list_status": item.get("status"),
                "cwd": item.get("cwd"),
                "created_at": inspected.get("CreatedAt") if inspected else None,
                "updated_at": inspected.get("UpdatedAt") if inspected else None,
                "archived": inspected.get("Archived") if inspected else None,
                "archived_at": inspected.get("ArchivedAt") if inspected else None,
                "inspect_status": inspected.get("Status") if inspected else None,
                "parent_agent_id": inspected.get("ParentAgentId") if inspected else None,
                "children": children,
                "non_candidate_children": [
                    child for child in children if child not in {candidate["id"] for candidate in candidates}
                ],
                "transcript": transcript_results.get(agent_id),
                "eligible_for_review": bool(
                    inspected
                    and inspected.get("Provider") == "codex"
                    and normalized_path(str(inspected.get("Cwd", ""))) == root
                    and inspected.get("Status") == "closed"
                    and not transcript_results.get(agent_id, {}).get("error")
                ),
            }
        )

    manifest = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "operation": "COST closed Codex session consolidation and deletion",
        "root": str(Path(args.root).resolve()),
        "selection": {
            "cwd_exact": str(Path(args.root).resolve()),
            "provider_prefix": "codex/",
            "list_status": "closed",
        },
        "counts": {
            "paseo_agents_returned": len(listed),
            "cost_agents": len(cost_agents),
            "closed_codex_candidates": len(candidate_records),
            "transcript_errors": sum(bool(record["transcript"].get("error")) for record in candidate_records),
            "empty_transcripts": sum(bool(record["transcript"].get("empty")) for record in candidate_records),
        },
        "all_cost_agents": all_records,
        "candidates": sorted(candidate_records, key=lambda item: (item.get("created_at") or "", item["id"])),
    }
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with manifest_path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"manifest": str(manifest_path), **manifest["counts"]}, ensure_ascii=False))
    return 0


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_bytes(path: Path) -> tuple[Any, bytes]:
    payload = path.read_bytes()
    try:
        return json.loads(payload.decode("utf-8")), payload
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid UTF-8 JSON file: {path}") from exc


def assert_no_reparse_components(path: Path) -> None:
    absolute = Path(os.path.abspath(str(path)))
    current = Path(absolute.anchor)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for part in absolute.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            continue
        current_stat = current.lstat()
        if getattr(current_stat, "st_file_attributes", 0) & reparse_flag:
            raise RuntimeError(f"Reparse-point paths are forbidden for migration artifacts: {current}")


def require_exact_path(raw_path: str, expected: Path, *, must_exist: bool) -> Path:
    actual = Path(os.path.abspath(os.path.normpath(raw_path)))
    expected_absolute = Path(os.path.abspath(os.path.normpath(str(expected))))
    if normalized_path(str(actual)) != normalized_path(str(expected_absolute)):
        raise RuntimeError(
            f"Path is not the hard-pinned migration artifact: {actual} != {expected_absolute}"
        )
    assert_no_reparse_components(expected_absolute)
    if must_exist and not expected_absolute.exists():
        raise RuntimeError(f"Required migration artifact does not exist: {expected_absolute}")
    return expected_absolute


def flush_directory_entry(path: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    flush_file_buffers = kernel32.FlushFileBuffers
    flush_file_buffers.argtypes = [ctypes.c_void_p]
    flush_file_buffers.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    generic_write = 0x40000000
    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    backup_semantics = 0x02000000
    handle = create_file(
        str(path),
        generic_write,
        share_all,
        None,
        open_existing,
        backup_semantics,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), f"Cannot open directory for durability flush: {path}")
    try:
        if not flush_file_buffers(handle):
            raise OSError(ctypes.get_last_error(), f"Cannot durably flush directory entry: {path}")
    finally:
        close_handle(handle)


def file_identity(path: Path) -> tuple[int, int]:
    value = path.stat(follow_symlinks=False)
    return value.st_dev, value.st_ino


def validate_dedicated_ledger(path: Path, evidence_paths: Iterable[Path]) -> tuple[int, int]:
    assert_no_reparse_components(path)
    if not path.is_file():
        raise RuntimeError(f"Pre-created deletion ledger is missing or not a file: {path}")
    ledger_stat = path.stat(follow_symlinks=False)
    if ledger_stat.st_nlink != 1:
        raise RuntimeError(f"Deletion ledger must have exactly one hardlink: {path}")
    ledger_identity = (ledger_stat.st_dev, ledger_stat.st_ino)
    for evidence in evidence_paths:
        assert_no_reparse_components(evidence)
        if not evidence.is_file():
            raise RuntimeError(f"Preservation evidence is missing or not a file: {evidence}")
        if file_identity(evidence) == ledger_identity:
            raise RuntimeError(f"Deletion ledger aliases preservation evidence: {evidence}")
    return ledger_identity


class DurableJsonlLedger:
    def __init__(self, path: Path, evidence_paths: Iterable[Path]) -> None:
        expected_identity = validate_dedicated_ledger(path, evidence_paths)
        self.path = path
        self.identity = expected_identity
        self.descriptor = self._open_exclusive_descriptor(path)
        opened = os.fstat(self.descriptor)
        if (opened.st_dev, opened.st_ino) != expected_identity or opened.st_nlink != 1:
            os.close(self.descriptor)
            raise RuntimeError(f"Deletion ledger identity changed while opening: {path}")

    @staticmethod
    def _open_exclusive_descriptor(path: Path) -> int:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        create_file.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        generic_read = 0x80000000
        generic_write = 0x40000000
        share_read = 0x00000001
        open_existing = 3
        file_attribute_normal = 0x00000080
        handle = create_file(
            str(path),
            generic_read | generic_write,
            share_read,
            None,
            open_existing,
            file_attribute_normal,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            raise OSError(ctypes.get_last_error(), f"Cannot exclusively open deletion ledger: {path}")
        try:
            return msvcrt.open_osfhandle(int(handle), os.O_RDWR | getattr(os, "O_BINARY", 0))
        except Exception:
            close_handle(handle)
            raise

    def _assert_identity(self) -> None:
        assert_no_reparse_components(self.path)
        opened = os.fstat(self.descriptor)
        current = self.path.stat(follow_symlinks=False)
        if (
            (opened.st_dev, opened.st_ino) != self.identity
            or (current.st_dev, current.st_ino) != self.identity
            or opened.st_nlink != 1
            or current.st_nlink != 1
        ):
            raise RuntimeError(f"Deletion ledger identity or hardlink count changed: {self.path}")

    def read_bytes(self) -> bytes:
        self._assert_identity()
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(self.descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        self._assert_identity()
        os.lseek(self.descriptor, 0, os.SEEK_END)
        return b"".join(chunks)

    def append(self, record: dict[str, Any]) -> None:
        self._assert_identity()
        payload = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        os.lseek(self.descriptor, 0, os.SEEK_END)
        offset = 0
        while offset < len(payload):
            written = os.write(self.descriptor, payload[offset:])
            if written <= 0:
                raise RuntimeError(f"Short write to deletion ledger: {self.path}")
            offset += written
        os.fsync(self.descriptor)
        self._assert_identity()

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1

    def __enter__(self) -> "DurableJsonlLedger":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def require_path_within_root(path: Path, root: Path) -> Path:
    assert_no_reparse_components(root)
    assert_no_reparse_components(path)
    resolved = path.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError(f"Durable artifact is outside COST root: {resolved}") from exc
    return resolved


def verify_canonical_sections(
    agent_id: str,
    entry: dict[str, Any],
    root: Path,
    cache: dict[Path, tuple[str, str]],
) -> list[dict[str, str]]:
    references = entry.get("canonical_sections")
    if not isinstance(references, list) or not references:
        raise RuntimeError(f"No durable canonical section is approved for {agent_id}")
    verified: list[dict[str, str]] = []
    for reference in references:
        if not isinstance(reference, dict):
            raise RuntimeError(f"Malformed canonical section for {agent_id}: {reference!r}")
        raw_path = reference.get("path")
        expected_hash = reference.get("sha256")
        section = reference.get("section")
        if not all(isinstance(value, str) and value.strip() for value in (raw_path, expected_hash, section)):
            raise RuntimeError(f"Incomplete canonical section for {agent_id}: {reference!r}")
        candidate_path = Path(raw_path)
        if not candidate_path.is_absolute():
            candidate_path = root / candidate_path
        path = require_path_within_root(candidate_path, root)
        if path != EXPECTED_CANONICAL.resolve(strict=True):
            raise RuntimeError(f"Unexpected canonical artifact for {agent_id}: {path}")
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Canonical artifact is missing or empty for {agent_id}: {path}")
        if path not in cache:
            payload = path.read_bytes()
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeError(f"Canonical artifact is not UTF-8: {path}") from exc
            cache[path] = (sha256_bytes(payload), text)
        actual_hash, text = cache[path]
        if actual_hash != expected_hash:
            raise RuntimeError(f"Canonical artifact hash mismatch for {agent_id}: {path}")
        if section not in text:
            raise RuntimeError(f"Canonical section marker is absent for {agent_id}: {section!r} in {path}")
        verified.append({"path": str(path), "sha256": actual_hash, "section": section})
    return verified


def validate_agent_list(listed: Any, *, scope: str) -> list[dict[str, Any]]:
    if not isinstance(listed, list):
        raise RuntimeError(f"Unexpected Paseo agent-list payload for {scope}")
    # Paseo's list API is capped at 200. Equality means completeness cannot be
    # established, so never use such a response as proof of absence/closure.
    if len(listed) >= 200:
        raise RuntimeError(f"Paseo agent list reached its 200-item cap for {scope}")
    if not all(isinstance(item, dict) for item in listed):
        raise RuntimeError(f"Paseo agent list contains a non-object row for {scope}")
    ids = [validate_agent_id(item.get("id"), context=f"agent list {scope}") for item in listed]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"Paseo agent list contains duplicate IDs for {scope}")
    return listed


def list_cost_agents() -> list[dict[str, Any]]:
    listed = validate_agent_list(
        run_paseo_json(["ls", "--all", "--json"], timeout=90),
        scope="exact COST cwd",
    )
    wrong_cwd = [
        item.get("id")
        for item in listed
        if normalized_path(str(item.get("cwd", ""))) != normalized_path(str(EXPECTED_ROOT))
    ]
    if wrong_cwd:
        raise RuntimeError(f"COST-scoped list returned agents from another cwd: {wrong_cwd}")
    return listed


def list_direct_children(agent_id: str, *, workers: int = 12) -> dict[str, dict[str, Any]]:
    validate_agent_id(agent_id, context="child lookup parent")
    listed = validate_agent_list(
        run_paseo_json(
            [
                "ls",
                "--all",
                "--global",
                "--label",
                f"paseo.parent-agent-id={agent_id}",
                "--json",
            ],
            timeout=90,
        ),
        scope=f"children of {agent_id}",
    )
    if not listed:
        return {}
    inspected: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(inspect_agent, str(item["id"])): str(item["id"]) for item in listed}
        for future in concurrent.futures.as_completed(futures):
            child_id = futures[future]
            try:
                inspected[child_id] = future.result()
            except Exception as exc:
                errors[child_id] = str(exc)
    if errors:
        raise RuntimeError(f"Cannot inspect children of {agent_id}: {errors}")
    mismatched = sorted(
        child_id
        for child_id, child in inspected.items()
        if child.get("ParentAgentId") != agent_id
    )
    if mismatched:
        raise RuntimeError(
            f"Parent-label query returned mismatched children for {agent_id}: {mismatched}"
        )
    return inspected


def list_parent_thinking_scope(parent_agent_id: str, thinking: str) -> list[dict[str, Any]]:
    validate_agent_id(parent_agent_id, context="global-list parent scope")
    validate_thinking(thinking, context="global-list thinking scope")
    return validate_agent_list(
        run_paseo_json(
            [
                "ls",
                "--all",
                "--global",
                "--label",
                f"paseo.parent-agent-id={parent_agent_id}",
                "--thinking",
                thinking,
                "--json",
            ],
            timeout=90,
        ),
        scope=f"parent={parent_agent_id}, thinking={thinking}",
    )


def unique_bundle_slice(bundle: bytes, start: bytes, end: bytes, *, name: str) -> bytes:
    start_count = bundle.count(start)
    end_count = bundle.count(end)
    if start_count != 1 or end_count != 1:
        raise RuntimeError(
            f"Paseo bundle markers are not unique for {name}: "
            f"start_count={start_count}, end_count={end_count}"
        )
    start_index = bundle.find(start)
    end_index = bundle.find(end, start_index + len(start))
    if start_index < 0 or end_index <= start_index:
        raise RuntimeError(f"Cannot locate reviewed Paseo bundle slice: {name}")
    return bundle[start_index:end_index]


def verify_running_daemon_provenance() -> dict[str, Any]:
    if not POWERSHELL_EXE.is_file():
        raise RuntimeError(f"Windows PowerShell is unavailable for daemon provenance: {POWERSHELL_EXE}")
    daemon_runner = PASEO_ASAR / "dist" / "daemon" / "node-entrypoint-runner.js"
    daemon_worker = (
        PASEO_ASAR
        / "node_modules"
        / "@getpaseo"
        / "server"
        / "dist"
        / "server"
        / "server"
        / "daemon-worker.js"
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$expectedExe = '{PASEO_EXE}'
$expectedRunner = '{daemon_runner}'
$expectedWorker = '{daemon_worker}'
$bundleWriteUtc = (Get-Item -LiteralPath '{PASEO_ASAR}').LastWriteTimeUtc
$rows = @(
  Get-CimInstance Win32_Process -Filter \"Name='Paseo.exe'\" |
    Where-Object {{
      $_.ExecutablePath -eq $expectedExe -and
      $_.CommandLine -like \"*$expectedRunner*\" -and
      $_.CommandLine -like \"*$expectedWorker*\"
    }} |
    ForEach-Object {{
      [pscustomobject]@{{
        ProcessId = [int]$_.ProcessId
        ParentProcessId = [int]$_.ParentProcessId
        ExecutablePath = $_.ExecutablePath
        CommandLine = $_.CommandLine
        CreationTimeUtc = $_.CreationDate.ToUniversalTime().ToString('o')
        StartedAfterBundleWrite = $_.CreationDate.ToUniversalTime() -gt $bundleWriteUtc
      }}
    }}
)
$rows | ConvertTo-Json -Compress
"""
    proc = subprocess.run(
        [str(POWERSHELL_EXE), "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=str(EXPECTED_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Cannot verify the running Paseo daemon: {(proc.stderr or proc.stdout).strip()}")
    output = proc.stdout.strip()
    if not output:
        raise RuntimeError("No running Paseo daemon matches the reviewed on-disk bundle")
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Daemon provenance check returned non-JSON output: {output[:500]!r}") from exc
    rows = parsed if isinstance(parsed, list) else [parsed]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError(f"Expected exactly one reviewed Paseo daemon, found {len(rows)}")
    daemon = rows[0]
    if (
        normalized_path(str(daemon.get("ExecutablePath", ""))) != normalized_path(str(PASEO_EXE))
        or daemon.get("StartedAfterBundleWrite") is not True
        or not isinstance(daemon.get("ProcessId"), int)
    ):
        raise RuntimeError(f"Running Paseo daemon is not bound to the reviewed installation: {daemon}")
    return daemon


def verify_non_cascading_hard_delete() -> dict[str, Any]:
    required_files = (PASEO_EXE, PASEO_RUNNER, PASEO_ASAR)
    missing_files = [str(path) for path in required_files if not path.is_file()]
    if missing_files:
        raise RuntimeError(f"Reviewed Paseo installation files are missing: {missing_files}")
    if sha256_file(PASEO_EXE) != EXPECTED_PASEO_EXE_SHA256:
        raise RuntimeError("Paseo executable hash differs from the reviewed installation")
    if sha256_file(PASEO_RUNNER) != EXPECTED_PASEO_RUNNER_SHA256:
        raise RuntimeError("Paseo CLI runner hash differs from the reviewed installation")

    before = PASEO_ASAR.stat()
    bundle = PASEO_ASAR.read_bytes()
    bundle_hash = sha256_bytes(bundle)
    if bundle_hash != EXPECTED_PASEO_ASAR_SHA256:
        raise RuntimeError(
            "Paseo application bundle hash differs from the reviewed installation: "
            f"{bundle_hash}"
        )

    handler = unique_bundle_slice(
        bundle,
        b"async handleDeleteAgentRequest(agentId, requestId) {",
        b"async handleArchiveAgentRequest(agentId, requestId) {",
        name="hard-delete handler",
    )
    begin_delete_helper = unique_bundle_slice(
        bundle,
        b"function beginAgentDeleteIfSupported(agentStorage, agentId) {",
        b"const FETCH_AGENTS_SORT_KEYS =",
        name="begin-delete helper",
    )
    storage_fence = unique_bundle_slice(
        bundle,
        b"    queueRecordMutation(agentId, mutate) {",
        b"    async applySnapshot(agent, options) {",
        name="storage delete fence",
    )
    slices = (
        ("hard-delete handler", handler, EXPECTED_DELETE_HANDLER_SHA256, EXPECTED_DELETE_HANDLER_BYTES),
        (
            "begin-delete helper",
            begin_delete_helper,
            EXPECTED_BEGIN_DELETE_HELPER_SHA256,
            EXPECTED_BEGIN_DELETE_HELPER_BYTES,
        ),
        (
            "storage delete fence",
            storage_fence,
            EXPECTED_STORAGE_DELETE_FENCE_SHA256,
            EXPECTED_STORAGE_DELETE_FENCE_BYTES,
        ),
    )
    for name, payload, expected_hash, expected_bytes in slices:
        actual_hash = sha256_bytes(payload)
        if actual_hash != expected_hash or len(payload) != expected_bytes:
            raise RuntimeError(
                f"Reviewed Paseo {name} changed: "
                f"sha256={actual_hash}, bytes={len(payload)}"
            )

    ordered_handler_markers = (
        b"beginAgentDeleteIfSupported(this.agentStorage, agentId);",
        b"await closeAgentCommand({ agentManager: this.agentManager }, agentId);",
        b"await this.agentManager.flush();",
        b"await this.agentStorage.remove(agentId);",
        b"await this.agentManager.deleteAgentState(agentId);",
        b'type: "agent_deleted"',
    )
    cursor = -1
    for marker in ordered_handler_markers:
        cursor = handler.find(marker, cursor + 1)
        if cursor < 0:
            raise RuntimeError(
                "Reviewed hard-delete handler lost required ordered control flow: "
                f"{marker.decode('utf-8', 'replace')}"
            )
    required_fence_markers = (
        b"if (this.deleting.has(agentId))",
        b"this.deleting.add(agentId);",
        b"this.beginDelete(agentId);",
        b"await (this.pendingWrites.get(agentId) ?? Promise.resolve());",
        b"await fs.unlink(filePath);",
    )
    if any(marker not in storage_fence for marker in required_fence_markers):
        raise RuntimeError("Reviewed storage delete fence lost required mutation suppression")

    daemon = verify_running_daemon_provenance()
    after = PASEO_ASAR.stat()
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or sha256_file(PASEO_ASAR) != EXPECTED_PASEO_ASAR_SHA256
    ):
        raise RuntimeError("Paseo bundle changed during delete-semantics verification")
    return {
        "bundle": str(PASEO_ASAR),
        "bundle_sha256": bundle_hash,
        "bundle_bytes": before.st_size,
        "bundle_mtime_ns": before.st_mtime_ns,
        "handler_sha256": sha256_bytes(handler),
        "begin_delete_helper_sha256": sha256_bytes(begin_delete_helper),
        "storage_delete_fence_sha256": sha256_bytes(storage_fence),
        "daemon_process_id": daemon["ProcessId"],
        "daemon_creation_time_utc": daemon.get("CreationTimeUtc"),
        "hard_delete_cascades_children": False,
        "delete_fence_blocks_new_snapshot_writes": True,
    }


def parse_json_error(proc: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    for value in (proc.stderr, proc.stdout):
        text = (value or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def is_explicitly_absent(agent_id: str, *, parent_agent_id: str, thinking: str) -> bool:
    validate_agent_id(agent_id, context="absence proof")
    proc = run_paseo_process(["inspect", agent_id, "--json"], timeout=45)
    if proc.returncode == 0:
        return False
    payload = parse_json_error(proc)
    error = payload.get("error", {}) if payload else {}
    expected = f"Agent not found: {agent_id}"
    if error.get("code") != "INSPECT_FAILED" or str(error.get("message", "")).strip() != expected:
        detail = (proc.stderr or proc.stdout).strip()[:500]
        raise RuntimeError(f"Deletion absence is not authoritative for {agent_id}: {detail}")
    listed = list_parent_thinking_scope(parent_agent_id, thinking)
    if any(str(item.get("id", "")) == agent_id for item in listed):
        raise RuntimeError(f"Deleted agent remains in the fresh global list: {agent_id}")
    return True


def assert_explicitly_absent(agent_id: str, *, parent_agent_id: str, thinking: str) -> None:
    if not is_explicitly_absent(
        agent_id,
        parent_agent_id=parent_agent_id,
        thinking=thinking,
    ):
        raise RuntimeError(f"Agent still resolves after deletion: {agent_id}")


def load_ledger_state(
    ledger: DurableJsonlLedger,
    *,
    approval_id: str,
    approval_hash: str,
    manifest_hash: str,
    approved: dict[str, dict[str, Any]],
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    committed: set[str] = set()
    outstanding_intents: dict[str, dict[str, Any]] = {}
    payload = ledger.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Deletion ledger is not valid UTF-8") from exc
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            raise RuntimeError(f"Deletion ledger contains a blank line at {line_number}")
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Deletion ledger line {line_number} is not JSON") from exc
        if not isinstance(record, dict):
            raise RuntimeError(f"Deletion ledger line {line_number} is not an object")
        if record.get("approval_id") != approval_id or record.get("manifest_sha256") != manifest_hash:
            raise RuntimeError(f"Deletion ledger line {line_number} belongs to another approval")
        if record.get("approval_sha256") != approval_hash:
            raise RuntimeError(f"Deletion ledger line {line_number} has an approval-hash mismatch")
        agent_id = validate_agent_id(record.get("agent_id"), context=f"ledger line {line_number}")
        if agent_id not in approved:
            raise RuntimeError(f"Deletion ledger line {line_number} names an unapproved agent")
        if record.get("transcript_sha256") != approved[agent_id].get("transcript_sha256"):
            raise RuntimeError(f"Deletion ledger line {line_number} has a transcript-hash mismatch")
        event = record.get("event")
        if event not in {"delete_intent", "delete_committed", "delete_failed_or_unconfirmed"}:
            raise RuntimeError(f"Deletion ledger line {line_number} has an unknown event: {event!r}")
        if event == "delete_intent":
            if agent_id in committed:
                raise RuntimeError(f"Deletion intent follows a commit for {agent_id}")
            outstanding_intents[agent_id] = record
        elif event == "delete_committed":
            if (
                record.get("verified_absent") is not True
                or record.get("verified_absent_from_global_list") is not True
            ):
                raise RuntimeError(f"Deletion commit lacks absence proof at line {line_number}")
            if agent_id in committed:
                raise RuntimeError(f"Deletion ledger contains duplicate commits for {agent_id}")
            committed.add(agent_id)
            outstanding_intents.pop(agent_id, None)
    return committed, outstanding_intents


def verified_frozen_transcript_path(agent_id: str, transcript: dict[str, Any]) -> Path:
    expected = EXPECTED_TRANSCRIPT_DIR / f"{agent_id}.txt"
    return require_exact_path(str(transcript.get("path", "")), expected, must_exist=True)


def relocate_manifest(args: argparse.Namespace) -> int:
    manifest_path = require_exact_path(args.manifest, EXPECTED_MANIFEST, must_exist=True)
    manifest, _ = read_json_bytes(manifest_path)
    if manifest.get("schema_version") != 1:
        raise RuntimeError("Manifest must use schema_version 1")
    if normalized_path(str(manifest.get("root", ""))) != normalized_path(str(EXPECTED_ROOT)):
        raise RuntimeError("Manifest root is not the hard-pinned COST root")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Manifest has no candidates")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError(f"Malformed candidate in manifest: {candidate!r}")
        agent_id = validate_agent_id(candidate.get("id"), context="manifest relocation candidate")
        transcript = candidate.get("transcript") or {}
        expected_hash = transcript.get("sha256")
        if not isinstance(expected_hash, str) or not expected_hash:
            raise RuntimeError(f"Candidate lacks transcript hash: {agent_id}")
        source = Path(str(transcript.get("path", ""))).resolve(strict=True)
        target = (EXPECTED_TRANSCRIPT_DIR / f"{agent_id}.txt").resolve(strict=True)
        source_hash = sha256_file(source)
        target_hash = sha256_file(target)
        if source_hash != expected_hash or target_hash != expected_hash:
            raise RuntimeError(
                f"Transcript relocation hash mismatch for {agent_id}: "
                f"manifest={expected_hash}, source={source_hash}, target={target_hash}"
            )
        transcript["path"] = str(target)
    manifest["relocated_at"] = utc_now()
    manifest["relocation"] = {
        "transcript_root": str(EXPECTED_TRANSCRIPT_DIR.resolve(strict=True)),
        "hash_verified": True,
        "candidate_count": len(candidates),
    }
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_path = manifest_path.with_suffix(".json.tmp")
    with temp_path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, manifest_path)
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "candidate_count": len(candidates),
                "sha256": sha256_bytes(payload),
            },
            ensure_ascii=False,
        )
    )
    return 0


def prepare_ledger(args: argparse.Namespace) -> int:
    ledger_path = require_exact_path(args.ledger, EXPECTED_LEDGER, must_exist=False)
    parent = ledger_path.parent
    if not parent.is_dir():
        raise RuntimeError(f"Ledger parent directory must already exist: {parent}")
    assert_no_reparse_components(parent)
    if os.path.lexists(ledger_path):
        raise RuntimeError(f"Refusing to replace an existing deletion ledger: {ledger_path}")
    descriptor = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    flush_directory_entry(parent)
    validate_dedicated_ledger(ledger_path, ())
    print(
        json.dumps(
            {
                "ledger": str(ledger_path),
                "bytes": ledger_path.stat().st_size,
                "hardlinks": ledger_path.stat().st_nlink,
                "directory_entry_flushed": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


def delete_verified(args: argparse.Namespace) -> int:
    manifest_path = require_exact_path(args.manifest, EXPECTED_MANIFEST, must_exist=True)
    approval_path = require_exact_path(args.approval, EXPECTED_APPROVAL, must_exist=True)
    manifest, manifest_payload = read_json_bytes(manifest_path)
    approval, approval_payload = read_json_bytes(approval_path)
    manifest_hash = sha256_bytes(manifest_payload)
    approval_hash = sha256_bytes(approval_payload)
    if manifest_hash != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError(f"Manifest is not the reviewed frozen COST inventory: {manifest_hash}")
    if manifest.get("schema_version") != 1 or approval.get("schema_version") != 1:
        raise RuntimeError("Manifest and approval must both use schema_version 1")
    if approval.get("manifest_sha256") != manifest_hash:
        raise RuntimeError("Approval is not bound to the current frozen manifest hash")
    approval_id = approval.get("approval_id")
    if approval_id != EXPECTED_APPROVAL_ID:
        raise RuntimeError(f"Approval ID is not hard-pinned: {approval_id!r}")
    tool_hash = sha256_file(Path(__file__).resolve(strict=True))
    if approval.get("deletion_tool_sha256") != tool_hash:
        raise RuntimeError("Approval is not bound to this exact reviewed deletion-tool hash")
    if approval.get("paseo_bundle_sha256") != EXPECTED_PASEO_ASAR_SHA256:
        raise RuntimeError("Approval is not bound to the reviewed Paseo application bundle")
    if approval.get("paseo_delete_handler_sha256") != EXPECTED_DELETE_HANDLER_SHA256:
        raise RuntimeError("Approval is not bound to the reviewed Paseo delete handler")

    root_path = Path(manifest["root"]).resolve(strict=True)
    root = normalized_path(str(root_path))
    if root != normalized_path(str(EXPECTED_ROOT)):
        raise RuntimeError(f"Manifest root is not the hard-pinned COST root: {root_path}")
    selection = manifest.get("selection") or {}
    if (
        normalized_path(str(selection.get("cwd_exact", ""))) != root
        or selection.get("provider_prefix") != "codex/"
        or selection.get("list_status") != "closed"
    ):
        raise RuntimeError(f"Manifest selection is not the authorized closed-Codex scope: {selection}")

    candidate_entries = manifest.get("candidates") or []
    if not isinstance(candidate_entries, list) or not all(
        isinstance(item, dict) for item in candidate_entries
    ):
        raise RuntimeError("Frozen manifest candidates must be a list of objects")
    declared_count = (manifest.get("counts") or {}).get("closed_codex_candidates")
    if not candidate_entries or declared_count != len(candidate_entries):
        raise RuntimeError(
            "Frozen candidate count is empty or inconsistent: "
            f"declared={declared_count}, actual={len(candidate_entries)}"
        )
    candidate_ids = [
        validate_agent_id(item.get("id"), context="frozen manifest candidate")
        for item in candidate_entries
    ]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise RuntimeError("Frozen manifest contains duplicate candidate IDs")
    candidates = {agent_id: item for agent_id, item in zip(candidate_ids, candidate_entries)}
    approved_entries = approval.get("approved", [])
    if not isinstance(approved_entries, list) or not all(
        isinstance(item, dict) for item in approved_entries
    ):
        raise RuntimeError("Approval `approved` must be a list of objects")
    approved_ids = [
        validate_agent_id(item.get("id"), context="approval entry") for item in approved_entries
    ]
    if len(approved_ids) != len(set(approved_ids)):
        raise RuntimeError("Approval contains duplicate session IDs")
    approved = {agent_id: item for agent_id, item in zip(approved_ids, approved_entries)}
    if not approved:
        raise RuntimeError("Approval contains no approved sessions")
    if set(approved) != set(candidates):
        missing = sorted(set(candidates) - set(approved))
        unknown = sorted(set(approved) - set(candidates))
        raise RuntimeError(
            "Approval must close over the exact frozen candidate set; "
            f"missing={missing}, unknown={unknown}"
        )

    ledger_path = require_exact_path(args.ledger, EXPECTED_LEDGER, must_exist=True)
    try:
        ledger_path.relative_to(root_path)
    except ValueError as exc:
        raise RuntimeError(f"Deletion ledger must remain under COST root: {ledger_path}") from exc

    canonical_cache: dict[Path, tuple[str, str]] = {}
    evidence_paths: set[Path] = {
        manifest_path,
        approval_path,
        require_exact_path(str(EXPECTED_CANONICAL), EXPECTED_CANONICAL, must_exist=True),
    }
    for agent_id, entry in approved.items():
        candidate = candidates[agent_id]
        transcript = candidate.get("transcript") or {}
        if not isinstance(transcript, dict):
            raise RuntimeError(f"Malformed frozen transcript metadata for {agent_id}")
        validate_agent_id(candidate.get("parent_agent_id"), context=f"frozen parent of {agent_id}")
        validate_thinking(candidate.get("thinking"), context=f"frozen thinking for {agent_id}")
        if (
            candidate.get("list_status") != "closed"
            or candidate.get("inspect_status") != "closed"
            or not str(candidate.get("provider_model", "")).startswith("codex/")
            or normalized_path(str(candidate.get("cwd", ""))) != root
            or not candidate.get("eligible_for_review")
        ):
            raise RuntimeError(f"Frozen candidate is outside authorized scope: {agent_id}")
        if entry.get("transcript_sha256") != transcript.get("sha256"):
            raise RuntimeError(f"Transcript hash mismatch for {agent_id}")
        if entry.get("review_status") != "verified":
            raise RuntimeError(f"Session is not verified: {agent_id}")
        if transcript.get("error") or transcript.get("empty") or not transcript.get("sha256"):
            raise RuntimeError(f"Frozen transcript is unavailable for {agent_id}")
        frozen_export = verified_frozen_transcript_path(agent_id, transcript)
        evidence_paths.add(frozen_export)
        if sha256_file(frozen_export) != transcript["sha256"]:
            raise RuntimeError(f"Frozen transcript export changed for {agent_id}: {frozen_export}")
        raw_children = candidate.get("children", [])
        if not isinstance(raw_children, list):
            raise RuntimeError(f"Frozen child set is malformed for {agent_id}")
        frozen_children = {
            validate_agent_id(child, context=f"frozen child of {agent_id}") for child in raw_children
        }
        if not frozen_children.issubset(approved):
            raise RuntimeError(
                f"Approved parent omits frozen children for {agent_id}: "
                f"{sorted(frozen_children - set(approved))}"
            )
        verify_canonical_sections(agent_id, entry, root_path, canonical_cache)

    ledger = DurableJsonlLedger(ledger_path, evidence_paths)
    committed, outstanding_intents = load_ledger_state(
        ledger,
        approval_id=approval_id,
        approval_hash=approval_hash,
        manifest_hash=manifest_hash,
        approved=approved,
    )
    for agent_id, intent in sorted(outstanding_intents.items()):
        candidate = candidates[agent_id]
        parent_agent_id = str(candidate.get("parent_agent_id", ""))
        thinking = str(candidate.get("thinking", ""))
        if is_explicitly_absent(
            agent_id,
            parent_agent_id=parent_agent_id,
            thinking=thinking,
        ):
            if not args.execute:
                raise RuntimeError(
                    f"Deletion ledger has an uncommitted intent for an already absent agent; "
                    f"rerun with --execute to durably reconcile it: {agent_id}"
                )
            recovery = {
                **intent,
                "event": "delete_committed",
                "deleted_at": utc_now(),
                "delete_result": {"recovered_from_durable_intent": True},
                "verified_absent": True,
                "verified_absent_from_global_list": True,
            }
            ledger.append(recovery)
            committed.add(agent_id)
    for agent_id in sorted(committed):
        candidate = candidates[agent_id]
        assert_explicitly_absent(
            agent_id,
            parent_agent_id=str(candidate.get("parent_agent_id", "")),
            thinking=str(candidate.get("thinking", "")),
        )

    pending = set(approved) - committed
    inspect_errors: dict[str, str] = {}
    live_inspections: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(inspect_agent, agent_id): agent_id for agent_id in pending}
        for future in concurrent.futures.as_completed(futures):
            agent_id = futures[future]
            try:
                live_inspections[agent_id] = future.result()
            except Exception as exc:
                inspect_errors[agent_id] = str(exc)
    if inspect_errors:
        raise RuntimeError(f"Approved sessions are unavailable before deletion: {inspect_errors}")
    initial_drift = sorted(
        agent_id
        for agent_id, inspected in live_inspections.items()
        if (
            inspected.get("Provider") != "codex"
            or normalized_path(str(inspected.get("Cwd", ""))) != root
            or inspected.get("Status") != "closed"
            or inspected.get("Archived") is not True
        )
    )
    if initial_drift:
        raise RuntimeError(
            "Approved sessions are not all archived, closed, Codex, and COST-scoped: "
            f"{initial_drift}"
        )

    initial_hard_delete_semantics = verify_non_cascading_hard_delete()
    absence_scopes: dict[tuple[str, str], set[str]] = {}
    for agent_id in pending:
        candidate = candidates[agent_id]
        parent_agent_id = str(candidate.get("parent_agent_id", ""))
        thinking = str(candidate.get("thinking", ""))
        scope_key = (parent_agent_id, thinking)
        if scope_key not in absence_scopes:
            absence_scopes[scope_key] = {
                str(item.get("id", ""))
                for item in list_parent_thinking_scope(parent_agent_id, thinking)
            }
        if agent_id not in absence_scopes[scope_key]:
            raise RuntimeError(
                f"Approved session is absent from its complete global-list proof scope: {agent_id}"
            )

    for agent_id in approved:
        live_children = list_direct_children(agent_id)
        unapproved_children = sorted(set(live_children) - set(approved))
        if unapproved_children:
            raise RuntimeError(
                f"Approved parent has out-of-scope children {agent_id}: {unapproved_children}"
            )

    # Child-first order guards against provider-specific cascade semantics.
    def depth(agent_id: str) -> int:
        seen: set[str] = set()
        value = 0
        current = candidates[agent_id].get("parent_agent_id")
        while current in candidates:
            if current in seen:
                raise RuntimeError(f"Cycle in frozen candidate hierarchy at {agent_id}")
            seen.add(current)
            value += 1
            current = candidates[current].get("parent_agent_id")
        return value

    ordered = sorted(approved, key=lambda agent_id: (-depth(agent_id), agent_id))
    results: list[dict[str, Any]] = []
    simulated_removed: set[str] = set(committed)
    try:
        for agent_id in ordered:
            if agent_id in committed:
                continue
            candidate = candidates[agent_id]
            parent_agent_id = str(candidate.get("parent_agent_id", ""))
            thinking = str(candidate.get("thinking", ""))
            live_children = sorted(
                child_id
                for child_id in list_direct_children(agent_id)
                if child_id not in simulated_removed
            )
            if live_children:
                raise RuntimeError(
                    f"Refusing to delete parent with live children {agent_id}: {live_children}"
                )
            inspected = inspect_agent(agent_id)
            if inspected.get("Provider") != "codex":
                raise RuntimeError(f"Provider drift for {agent_id}: {inspected.get('Provider')}")
            if normalized_path(str(inspected.get("Cwd", ""))) != root:
                raise RuntimeError(f"Cwd drift for {agent_id}: {inspected.get('Cwd')}")
            if inspected.get("Status") != "closed":
                raise RuntimeError(
                    f"Refusing to delete agent whose live status is not exactly closed "
                    f"{agent_id}: {inspected.get('Status')}"
                )
            if inspected.get("Archived") is not True:
                raise RuntimeError(f"Refusing to delete a session that is not temporarily archived: {agent_id}")

            transcript = candidate["transcript"]
            frozen_export = verified_frozen_transcript_path(agent_id, transcript)
            if sha256_file(frozen_export) != transcript["sha256"]:
                raise RuntimeError(
                    f"Frozen transcript export changed immediately before deletion: {agent_id}"
                )
            fresh_transcript = collect_transcript(agent_id).encode("utf-8")
            fresh_hash = sha256_bytes(fresh_transcript)
            if (
                fresh_hash != transcript["sha256"]
                or fresh_hash != approved[agent_id]["transcript_sha256"]
            ):
                raise RuntimeError(f"Live transcript changed after review: {agent_id}")
            canonical_sections = verify_canonical_sections(
                agent_id, approved[agent_id], root_path, {}
            )

            base_record = {
                "approval_id": approval_id,
                "approval_sha256": approval_hash,
                "manifest_sha256": manifest_hash,
                "agent_id": agent_id,
                "title": candidate.get("title"),
                "provider_model": candidate.get("provider_model"),
                "created_at": candidate.get("created_at"),
                "parent_agent_id": parent_agent_id,
                "cluster": candidate.get("cluster"),
                "thinking": thinking,
                "transcript_sha256": fresh_hash,
                "transcript_bytes": transcript["bytes"],
                "canonical_sections": canonical_sections,
                "hard_delete_semantics": initial_hard_delete_semantics,
                "deletion_tool_sha256": tool_hash,
                "dry_run": not args.execute,
            }

            def final_deletion_gate() -> tuple[str, dict[str, Any]]:
                if sha256_file(manifest_path) != manifest_hash:
                    raise RuntimeError("Frozen manifest changed at the final deletion gate")
                if sha256_file(approval_path) != approval_hash:
                    raise RuntimeError("Reviewed approval changed at the final deletion gate")
                if sha256_file(Path(__file__).resolve(strict=True)) != tool_hash:
                    raise RuntimeError("Deletion tool changed at the final deletion gate")
                final_children = sorted(
                    child_id
                    for child_id in list_direct_children(agent_id)
                    if child_id not in simulated_removed
                )
                if final_children:
                    raise RuntimeError(
                        f"Refusing to delete parent with children at final gate "
                        f"{agent_id}: {final_children}"
                    )
                final_scope = list_parent_thinking_scope(parent_agent_id, thinking)
                if not any(str(item.get("id", "")) == agent_id for item in final_scope):
                    raise RuntimeError(
                        f"Agent disappeared from its complete global-list scope at final gate: {agent_id}"
                    )
                final_inspection = inspect_agent(agent_id)
                if (
                    final_inspection.get("Provider") != "codex"
                    or normalized_path(str(final_inspection.get("Cwd", ""))) != root
                    or final_inspection.get("Status") != "closed"
                    or final_inspection.get("Archived") is not True
                ):
                    raise RuntimeError(
                        f"Agent drifted at final deletion gate {agent_id}: {final_inspection}"
                    )
                final_semantics = verify_non_cascading_hard_delete()
                final_transcript_hash = sha256_bytes(
                    collect_transcript(agent_id).encode("utf-8")
                )
                if (
                    final_transcript_hash != transcript["sha256"]
                    or final_transcript_hash != approved[agent_id]["transcript_sha256"]
                ):
                    raise RuntimeError(
                        f"Live transcript changed at the final deletion gate: {agent_id}"
                    )
                return final_transcript_hash, final_semantics

            if args.execute:
                intent = {**base_record, "event": "delete_intent", "intent_at": utc_now()}
                ledger.append(intent)
                try:
                    # The durable intent is already written. After this point the
                    # final state check is followed immediately by exact-ID hard
                    # deletion. The pinned installed handler proof above confirms
                    # hard deletion does not cascade to children.
                    final_hash, final_semantics = final_deletion_gate()
                    output = run_paseo_json(
                        ["delete", agent_id, "--json"],
                        timeout=60,
                        attempts=1,
                    )
                    assert_explicitly_absent(
                        agent_id,
                        parent_agent_id=parent_agent_id,
                        thinking=thinking,
                    )
                    record = {
                        **base_record,
                        "transcript_sha256": final_hash,
                        "hard_delete_semantics": final_semantics,
                        "event": "delete_committed",
                        "deleted_at": utc_now(),
                        "delete_result": output,
                        "verified_absent": True,
                        "verified_absent_from_global_list": True,
                    }
                    ledger.append(record)
                except Exception as exc:
                    failure = {
                        **base_record,
                        "event": "delete_failed_or_unconfirmed",
                        "failed_at": utc_now(),
                        "error": str(exc),
                    }
                    try:
                        ledger.append(failure)
                    except Exception as ledger_exc:
                        raise RuntimeError(
                            f"Deletion failed for {agent_id}; failure-ledger append also failed: "
                            f"{ledger_exc}"
                        ) from exc
                    raise
            else:
                final_hash, final_semantics = final_deletion_gate()
                record = {
                    **base_record,
                    "transcript_sha256": final_hash,
                    "hard_delete_semantics": final_semantics,
                    "event": "delete_dry_run",
                }
            results.append(record)
            simulated_removed.add(agent_id)
    finally:
        ledger.close()

    print(
        json.dumps(
            {
                "execute": args.execute,
                "approved_count": len(approved),
                "already_committed_count": len(committed),
                "processed_count": len(results),
                "results": results,
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="Freeze metadata and export transcripts")
    collect_parser.add_argument("--root", default=r"C:\AX\cost")
    collect_parser.add_argument("--work-dir", required=True)
    collect_parser.add_argument("--manifest", required=True)
    collect_parser.add_argument("--workers", type=int, default=8)
    collect_parser.set_defaults(func=collect)

    relocate_parser = subparsers.add_parser(
        "relocate-manifest",
        help="Rebind verified transcript paths to the hard-pinned COST work directory",
    )
    relocate_parser.add_argument("--manifest", required=True)
    relocate_parser.set_defaults(func=relocate_manifest)

    ledger_parser = subparsers.add_parser(
        "prepare-ledger",
        help="Create and durably flush the one hard-pinned empty deletion ledger",
    )
    ledger_parser.add_argument("--ledger", required=True)
    ledger_parser.set_defaults(func=prepare_ledger)

    delete_parser = subparsers.add_parser("delete", help="Delete reviewed sessions sequentially")
    delete_parser.add_argument("--manifest", required=True)
    delete_parser.add_argument("--approval", required=True)
    delete_parser.add_argument("--ledger", required=True)
    delete_parser.add_argument("--execute", action="store_true", help="Actually hard-delete; default is dry-run")
    delete_parser.set_defaults(func=delete_verified)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
