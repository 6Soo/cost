"""Check the static runtime-environment catalog against application source.

This tool reads source text only. It never reads ``os.environ``, configuration
files containing runtime values, or any configured paths.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "runtime-environment-catalog.json"
SOURCE_ROOTS = (ROOT / "app", ROOT / "webapp")
ENTRYPOINT = ROOT / "run_candidate.py"
ENV_BINDING = re.compile(r"(?:_ENV|_FLAG|_TOKEN_ENV|_URL_ENV|_PATH_ENV|_DB_ENV|_SOURCES_ENV|_STORE_ENV|_CONFIG_ENV)$|^ENV_")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,}$")


def _valid_env_name(value: str) -> bool:
    return bool(ENV_NAME.fullmatch(value) and (
        value.startswith(("WEBLEDGER_", "RESERVATION_INTERNAL_"))
        or value in {"PORT", "APPDATA", "XDG_CONFIG_HOME", "OPENROUTER_API_KEY"}
    ))


def _source_files():
    return [ENTRYPOINT, *(path for base in SOURCE_ROOTS for path in base.rglob("*.py"))]


def _is_environ(node):
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _static_names(path: Path, tree: ast.Module) -> set[str]:
    names = set()
    constants = {}
    constant_sequences = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for target in targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = value.value
            elif isinstance(value, (ast.Tuple, ast.List)):
                items = [item.value for item in value.elts
                         if isinstance(item, ast.Constant) and isinstance(item.value, str)]
                for target in targets:
                    if isinstance(target, ast.Name):
                        constant_sequences[target.id] = items
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "get" or not _is_environ(node.func.value) or not node.args:
                continue
            key = node.args[0]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)
            elif isinstance(key, ast.Name) and key.id in constants:
                names.add(constants[key.id])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
            names.update(keyword.arg for keyword in node.keywords
                         if keyword.arg and _valid_env_name(keyword.arg))
    # Constant names passed through environment APIs (or a required-env tuple)
    # are metadata references even when another function performs the read.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Name):
                binding = node.args[0].id
                if binding in constants and ENV_BINDING.search(binding):
                    names.add(constants[binding])
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name):
            names.update(constant_sequences.get(node.iter.id, ()))
        if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            for generator in node.generators:
                if isinstance(generator.iter, ast.Name):
                    names.update(constant_sequences.get(generator.iter.id, ()))
    for binding, value in constants.items():
        if ENV_BINDING.search(binding):
            names.add(value)
    for binding, values in constant_sequences.items():
        if binding.endswith("REQUIRED_ENV") or binding.endswith("OPTIONAL_DATA_PATHS"):
            names.update(values)
    return {name for name in names if _valid_env_name(name)}


def inspect_catalog(root: Path = ROOT) -> dict:
    catalog_path = root / "config" / "runtime-environment-catalog.json"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if data.get("schema") != "runtime-environment-catalog-v1":
        raise ValueError("CATALOG_SCHEMA")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("CATALOG_ENTRIES")
    catalog_names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
    duplicates = sorted({name for name in catalog_names if catalog_names.count(name) > 1})
    malformed = [entry.get("name") for entry in entries if not isinstance(entry, dict)
                 or not isinstance(entry.get("name"), str)
                 or not entry.get("owner") or not entry.get("role")
                 or entry.get("status") not in ("confirmed", "unknown")]
    observed = set()
    for path in _source_files() if root == ROOT else [root / "run_candidate.py", *[p for folder in (root / "app", root / "webapp") for p in folder.rglob("*.py")]]:
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeError):
            continue
        observed.update(_static_names(path, tree))
    listed = set(catalog_names)
    missing = sorted(observed - listed)
    stale = sorted(listed - observed)
    unknown = sorted(entry["name"] for entry in entries
                     if isinstance(entry, dict) and entry.get("status") == "unknown")
    return {"status": "DRIFT" if missing or duplicates or malformed else "REVIEW" if unknown else "MATCH",
            "observed_count": len(observed), "catalog_count": len(listed),
            "missing": missing, "stale": stale, "duplicates": duplicates,
            "malformed": malformed, "unknown": unknown}


def main() -> int:
    try:
        result = inspect_catalog()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "ERROR", "code": str(error)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result["status"] == "DRIFT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
