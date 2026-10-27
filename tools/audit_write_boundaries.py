"""Read-only AST inventory for RF-001 R0 write-boundary review."""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


DEFAULT_TARGETS = (
    "webapp/ledger_board.py", "webapp/ledger_store.py", "webapp/card_flow.py",
    "webapp/ota_payment_review.py", "webapp/access_control.py", "webapp/ops.py",
)
WRITE_SQL = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP")


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return dotted(node.func)
    return ""


def string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(p.value if isinstance(p, ast.Constant) and isinstance(p.value, str) else "{dynamic}" for p in node.values)
    return None


def sql_metadata(value: str | None) -> dict:
    """Return structural SQL metadata only; never return SQL text or literals."""
    if value is None:
        return {"verb": None, "table": None, "status": "OPEN_QUESTION"}
    stripped = value.strip()
    if (not stripped or "--" in stripped or "/*" in stripped or "*/" in stripped
            or ";" in stripped or re.match(r"(?is)^WITH\b", stripped)):
        return {"verb": None, "table": None, "status": "OPEN_QUESTION"}
    match = re.match(r"(?is)^\s*(INSERT(?:\s+OR\s+\w+)?|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|SELECT|PRAGMA)\b", stripped)
    if not match:
        return {"verb": None, "table": None, "status": "OPEN_QUESTION"}
    verb = match.group(1).upper()
    rest = stripped[match.end():]
    table_pattern = (r"\s+([A-Za-z_][A-Za-z0-9_.]*)" if verb.startswith("UPDATE") else
                     r"\s+FROM\s+([A-Za-z_][A-Za-z0-9_.]*)" if verb == "DELETE" else
                     r"\s+INTO\s+([A-Za-z_][A-Za-z0-9_.]*)" if verb.startswith(("INSERT", "REPLACE")) else
                     r"(?is).*?\bFROM\s+([A-Za-z_][A-Za-z0-9_.]*)" if verb == "SELECT" else
                     r"\s+TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([A-Za-z_][A-Za-z0-9_.]*)")
    table_match = re.match(r"(?is)" + table_pattern, rest)
    table = table_match.group(1) if table_match else None
    status = "STATIC_CANDIDATE" if verb.split()[0] in WRITE_SQL else "STATIC_NONWRITE"
    return {"verb": verb, "table": table, "status": status}


def analyze_source(source: str, path: str = "<memory>") -> dict:
    tree = ast.parse(source, filename=path)
    findings = []
    parents: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [dotted(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list]
            findings.append({"kind": "callable", "name": node.name, "line": node.lineno,
                             "async": isinstance(node, ast.AsyncFunctionDef),
                             "decorators": decorators,
                             "signals": [d for d in decorators if any(x in d.lower() for x in ("login", "owner", "csrf", "auth"))]})
        elif isinstance(node, ast.Call):
            name = dotted(node.func)
            if name.endswith((".execute", ".executemany", ".executescript")):
                sql = string_value(node.args[0]) if node.args else None
                dynamic = sql is None or "{dynamic}" in sql
                meta = sql_metadata(None if dynamic else sql)
                findings.append({"kind": "sql_unknown" if meta["status"] == "OPEN_QUESTION" else ("sql_write" if meta["status"] == "STATIC_CANDIDATE" else "sql_read_or_other"),
                                 "call": name, "line": node.lineno, "verb": meta["verb"],
                                 "table": meta["table"], "status": meta["status"]})
            elif any(token in name.lower() for token in ("save", "write", "commit", "delete", "update", "apply")):
                findings.append({"kind": "write_like_call", "call": name or "<dynamic>", "line": node.lineno,
                                 "status": "OPEN_QUESTION"})
    findings.sort(key=lambda item: (item["line"], item["kind"], item.get("name", item.get("call", ""))))
    return {"path": path, "findings": findings,
            "limitations": ["AST findings are candidates, not runtime proof.", "Indirect dispatch, aliases, generated SQL, decorators with dynamic meaning, and framework middleware require manual review."]}


def audit(paths: list[Path], root: Path) -> dict:
    root = root.resolve()
    files, errors = [], []
    for path in paths:
        resolved = path.resolve()
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            errors.append({"path": str(path), "code": "PATH_OUTSIDE_ROOT"})
            continue
        try:
            source = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append({"path": rel, "code": "SOURCE_READ_ERROR", "error_type": type(exc).__name__})
            continue
        try:
            files.append(analyze_source(source, rel))
        except SyntaxError as exc:
            errors.append({"path": rel, "code": "SYNTAX_ERROR", "line": exc.lineno})
    return {"schema": "rf001-write-boundary-audit/v1", "mode": "static_ast_only",
            "files": files, "errors": errors}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Python source paths; defaults to the six R0 targets")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    paths = [Path(p) if Path(p).is_absolute() else root / p for p in (args.paths or DEFAULT_TARGETS)]
    result = audit(paths, root)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
