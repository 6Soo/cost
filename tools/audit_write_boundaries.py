"""Read-only AST inventory for RF-001 R0 write-boundary review."""
from __future__ import annotations

import argparse
import ast
import json
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
                normalized = (sql or "").lstrip().upper()
                dynamic = sql is None or "{dynamic}" in sql
                write = any(normalized.startswith(k) for k in WRITE_SQL)
                findings.append({"kind": "sql_unknown" if dynamic else ("sql_write" if write else "sql_read_or_other"),
                                 "call": name, "line": node.lineno, "statement": sql,
                                 "status": "OPEN_QUESTION" if dynamic else ("STATIC_CANDIDATE" if write else "STATIC_NONWRITE")})
            elif any(token in name.lower() for token in ("save", "write", "commit", "delete", "update", "apply")):
                findings.append({"kind": "write_like_call", "call": name or "<dynamic>", "line": node.lineno,
                                 "status": "OPEN_QUESTION"})
    findings.sort(key=lambda item: (item["line"], item["kind"], item.get("name", item.get("call", ""))))
    return {"path": path, "findings": findings,
            "limitations": ["AST findings are candidates, not runtime proof.", "Indirect dispatch, aliases, generated SQL, decorators with dynamic meaning, and framework middleware require manual review."]}


def audit(paths: list[Path], root: Path) -> dict:
    return {"schema": "rf001-write-boundary-audit/v1", "mode": "static_ast_only",
            "files": [analyze_source(p.read_text(encoding="utf-8"), p.relative_to(root).as_posix()) for p in paths]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Python source paths; defaults to the six R0 targets")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    paths = [Path(p) if Path(p).is_absolute() else args.root / p for p in (args.paths or DEFAULT_TARGETS)]
    result = audit(paths, args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
