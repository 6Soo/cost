"""Statically inventory explicit environment evidence in tracked pytest sources.

Counts are source-level test definition candidates, not pytest collection results.
Dynamic imports, generated tests, runtime conditions, and indirect dependencies
remain outside this static analysis and therefore may be UNVERIFIED.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Iterable


REASON_CODES = {
    "BROWSER_IMPORT": "browser automation import",
    "WINDOWS_IMPORT": "Windows-specific import",
    "LIVE_ENV_IMPORT": "live environment or service import",
    "BROWSER_MARKER": "browser pytest marker",
    "LIVE_MARKER": "live environment pytest marker",
    "ENV_NAME": "environment variable name",
    "SKIP_MARKER": "skip-related pytest marker",
    "PYTEST_INI": "pytest configuration file",
}

IMPORT_RULES = {
    "BROWSER_IMPORT": ("playwright", "selenium", "pyppeteer", "undetected_chromedriver"),
    "WINDOWS_IMPORT": ("winreg", "win32api", "win32com", "pywinauto"),
    "LIVE_ENV_IMPORT": ("googleapiclient", "google.auth", "requests", "httpx", "boto3"),
}
MARKER_RULES = {
    "BROWSER_MARKER": {"browser", "ui", "web_ui"},
    "LIVE_MARKER": {"live", "integration", "requires_live", "requires_database", "requires_network"},
}
ENV_NAME_RE = re.compile(
    r"^[A-Z][A-Z0-9_]{0,63}$", re.IGNORECASE
)
ENV_HINT_RE = re.compile(
    r"(?:^|_)(?:DATABASE|DB|LIVE|PROD|PRODUCTION|BROWSER|PLAYWRIGHT|SELENIUM|GOOGLE|GMAIL|API|TOKEN|PASSWORD|SECRET|CREDENTIALS?)(?:_|$)",
    re.IGNORECASE,
)


class AuditError(Exception):
    """A safe-to-report audit failure."""


def _is_test_source(name: str) -> bool:
    path = Path(name)
    base = path.name.casefold()
    if any(part.casefold() in {"outputs", "scratch", "artifacts", "archive", "archives", ".local-archive"} for part in path.parts):
        return False
    in_tests = any(part.casefold() == "tests" for part in path.parts)
    return base == "conftest.py" and in_tests or base.startswith("test_") or base.endswith("_test.py")


def _git_files(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.py", "pytest.ini"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AuditError("GIT_LIST_FAILED") from exc
    try:
        names = result.stdout.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        raise AuditError("GIT_PATH_ENCODING") from exc
    return sorted(name for name in names if name and (name.casefold() == "pytest.ini" or _is_test_source(name)))


def _safe_path(root: Path, name: str) -> Path:
    candidate = root / name
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise AuditError("PATH_OUTSIDE_OR_MISSING") from exc
    if not resolved.is_file():
        raise AuditError("PATH_NOT_FILE")
    return resolved


def _module_name(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return ",".join(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return ("." * node.level) + (node.module or "")
    return ""


def _test_count(tree: ast.AST) -> int:
    """Count test functions at module or class scope, excluding nested definitions."""
    count = 0
    for node in getattr(tree, "body", ()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            count += 1
        elif isinstance(node, ast.ClassDef):
            count += sum(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test")
                for child in node.body
            )
    return count


def _pytest_ini_evidence(text: str) -> list[dict]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise AuditError("PYTEST_INI_PARSE_FAILED") from exc
    evidence: list[dict] = []
    in_markers = False
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("["):
            in_markers = False
            continue
        if re.match(r"markers\s*=", stripped, re.IGNORECASE):
            in_markers = True
            value = stripped.split("=", 1)[1].strip()
        elif in_markers and line[:1].isspace():
            value = stripped
        else:
            in_markers = False
            continue
        marker = value.split("(", 1)[0].split(":", 1)[0].strip().split()
        if not marker:
            continue
        name = marker[0].casefold()
        code = "BROWSER_MARKER" if name in MARKER_RULES["BROWSER_MARKER"] else (
            "LIVE_MARKER" if name in MARKER_RULES["LIVE_MARKER"] else None
        )
        if code:
            evidence.append({"line": line_no, "reason_code": code, "identifier": name})
    return evidence


def _analyze_python(text: str, path: str) -> tuple[int, list[dict]]:
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, TypeError) as exc:
        raise AuditError("PYTHON_PARSE_FAILED") from exc
    evidence: list[dict] = []
    os_aliases = {"os"}
    getenv_aliases = {"getenv"}
    environ_aliases = {"environ"}
    pytest_aliases = {"pytest"}
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            for alias in item.names:
                if alias.name == "os":
                    os_aliases.add(alias.asname or "os")
                elif alias.name == "pytest":
                    pytest_aliases.add(alias.asname or "pytest")
        elif isinstance(item, ast.ImportFrom):
            if item.module == "os":
                for alias in item.names:
                    if alias.name == "getenv":
                        getenv_aliases.add(alias.asname or alias.name)
                    elif alias.name == "environ":
                        environ_aliases.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported = _module_name(node)
            for code, prefixes in IMPORT_RULES.items():
                hit = next((p for p in prefixes if any(part == p or part.startswith(p + ".") for part in imported.split(","))), None)
                if hit:
                    evidence.append({"line": node.lineno, "reason_code": code, "identifier": hit})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"skip", "skipif", "importorskip", "skip_module"}:
                evidence.append({"line": node.lineno, "reason_code": "SKIP_MARKER", "identifier": node.func.attr})
        if isinstance(node, ast.Attribute) and node.attr in {"skip", "skipif", "importorskip"}:
            evidence.append({"line": node.lineno, "reason_code": "SKIP_MARKER", "identifier": node.attr})
        if isinstance(node, ast.Name) and node.id in {"skip", "skipif", "importorskip"}:
            evidence.append({"line": node.lineno, "reason_code": "SKIP_MARKER", "identifier": node.id})
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            is_env_get = (
                isinstance(func, ast.Attribute) and func.attr in {"get", "getenv"}
                and ((isinstance(func.value, ast.Name) and func.value.id in os_aliases and func.attr == "getenv")
                     or (isinstance(func.value, ast.Name) and func.value.id in environ_aliases and func.attr == "get")
                     or (isinstance(func.value, ast.Attribute) and func.value.attr == "environ"
                         and isinstance(func.value.value, ast.Name) and func.value.value.id in os_aliases))
            ) or isinstance(func, ast.Name) and func.id in getenv_aliases
            if is_env_get:
                _append_env_evidence(evidence, node.args[0], node.lineno)
        if isinstance(node, ast.Subscript):
            value = node.value
            is_environ = isinstance(value, ast.Name) and value.id in environ_aliases
            is_environ = is_environ or (
                isinstance(value, ast.Attribute) and value.attr == "environ"
                and isinstance(value.value, ast.Name) and value.value.id in os_aliases
            )
            if is_environ:
                _append_env_evidence(evidence, node.slice, node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            decorators = node.decorator_list if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else []
            for decorator in decorators:
                marker = _pytest_marker(decorator, pytest_aliases)
                if marker:
                    evidence.append(marker)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            value_node = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if value_node is not None and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
                for child in ast.walk(value_node):
                    marker = _pytest_marker(child, pytest_aliases)
                    if marker:
                        evidence.append(marker)
    deduped = {(e["line"], e["reason_code"], e["identifier"]): e for e in evidence}
    return _test_count(tree), sorted(deduped.values(), key=lambda e: (e["line"], e["reason_code"], e["identifier"]))


def _append_env_evidence(evidence: list[dict], key_node: ast.AST, line: int) -> None:
    if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
        return
    key = key_node.value
    if ENV_NAME_RE.fullmatch(key) and ENV_HINT_RE.search(key):
        evidence.append({"line": line, "reason_code": "ENV_NAME", "identifier": key})


def _pytest_marker(node: ast.AST, pytest_aliases: set[str]) -> dict | None:
    current = node
    while isinstance(current, (ast.Call, ast.Attribute)):
        current = current.func if isinstance(current, ast.Call) else current.value
    if not isinstance(current, ast.Name) or current.id not in pytest_aliases:
        return None
    chain = []
    cursor = node.func if isinstance(node, ast.Call) else node
    while isinstance(cursor, ast.Attribute):
        chain.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name) or cursor.id not in pytest_aliases or len(chain) < 2 or chain[-1] != "mark":
        return None
    marker_name = chain[-2].casefold()
    code = "BROWSER_MARKER" if marker_name in MARKER_RULES["BROWSER_MARKER"] else (
        "LIVE_MARKER" if marker_name in MARKER_RULES["LIVE_MARKER"] else None
    )
    return {"line": getattr(node, "lineno", 1), "reason_code": code, "identifier": marker_name} if code else None


def audit(root: Path, runtime: str | None = None) -> dict:
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AuditError("INVALID_ROOT") from exc
    if not root.is_dir() or not (root / ".git").exists():
        raise AuditError("INVALID_ROOT")
    files = _git_files(root)
    rows = []
    errors = []
    for name in files:
        try:
            path = _safe_path(root, name)
        except AuditError as exc:
            errors.append({"path": name, "reason": str(exc)})
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            errors.append({"path": name, "reason": "SOURCE_READ_FAILED"})
            continue
        if name.casefold() == "pytest.ini":
            try:
                evidence = _pytest_ini_evidence(text)
            except AuditError as exc:
                errors.append({"path": name, "reason": str(exc)})
                continue
            count = None
            evidence.append({"line": 1, "reason_code": "PYTEST_INI", "identifier": "pytest.ini"})
        else:
            try:
                count, evidence = _analyze_python(text, name)
            except AuditError as exc:
                errors.append({"path": name, "reason": str(exc)})
                continue
        rows.append({
            "path": name,
            "test_candidate_count": count,
            "status": "EVIDENCE_FOUND" if evidence else "UNVERIFIED",
            "evidence": evidence,
        })
    runtime = runtime or f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return {
        "schema_version": 1,
        "analysis_limitations": "Static source candidates only; not pytest collection or execution. Dynamic/generated tests and indirect runtime dependencies may remain UNVERIFIED.",
        "root": ".",
        "python_runtime": runtime,
        "tracked_python_file_count": sum(name.casefold() != "pytest.ini" for name in files),
        "tracked_test_candidate_count": sum(row["test_candidate_count"] or 0 for row in rows),
        "files": rows,
        "errors": errors,
    }


def collect_baseline(root: Path, *, timeout: int = 120) -> dict:
    """Collect in an explicit subprocess. Pytest imports/conftest hooks still run.

    Never publish pytest's raw output: import errors may quote private paths or
    source lines. A digest binds aggregate evidence to the captured result.
    """
    root = root.resolve(strict=True)
    command = [sys.executable, '-m', 'pytest', '--collect-only', '-q']
    result = {
        'schema': 'cost-test-collection-v1',
        'python_runtime': platform.python_version(),
        'platform': platform.system(),
        'test_bodies_executed': False,
        'imports_and_collection_hooks_executed': True,
        'tests_executed': False,
    }
    try:
        run = subprocess.run(command, cwd=root, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return dict(result, status='COLLECTION_TIMEOUT', collected=None, exit_code=None)
    except OSError:
        return dict(result, status='COLLECTION_UNAVAILABLE', collected=None, exit_code=None)
    output = run.stdout.decode('utf-8', errors='replace')
    counts = re.findall(r'(\d+) tests? collected(?:\s|$)', output)
    count = int(counts[-1]) if counts else None
    status = 'COLLECTED' if run.returncode == 0 and count is not None else 'COLLECTION_FAILED'
    return dict(result, status=status, collected=count, exit_code=run.returncode,
                output_sha256=hashlib.sha256(run.stdout).hexdigest())


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--summary", action="store_true", help="print compact inventory summary")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON (default)")
    parser.add_argument("--collect", action="store_true", help="explicitly run pytest collection; does not execute test bodies")
    args = parser.parse_args(argv)
    try:
        report = audit(args.root)
    except AuditError as exc:
        print(json.dumps({"errors": [{"path": ".", "reason": str(exc)}]}, separators=(",", ":")), file=sys.stderr)
        return 2
    if args.collect:
        report['collection'] = collect_baseline(args.root)
    if args.summary:
        verified = sum(row["status"] == "EVIDENCE_FOUND" for row in report["files"])
        print(f"Python runtime: {report['python_runtime']}")
        print(f"Tracked Python files: {report['tracked_python_file_count']}")
        print(f"Test function/method candidates: {report['tracked_test_candidate_count']}")
        print(f"Files with explicit environment evidence: {verified}")
        print(f"Files UNVERIFIED: {len(report['files']) - verified}")
        print(f"File errors: {len(report['errors'])}")
        print("Counts are static definition candidates, not pytest collection or execution.")
        if args.collect:
            print(json.dumps(report['collection'], sort_keys=True))
        for error in report["errors"]:
            print(f"ERROR {error['path']} {error['reason']}")
    else:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if report["errors"] or args.collect and report['collection']['status'] != 'COLLECTED' else 0


if __name__ == "__main__":
    raise SystemExit(main())
