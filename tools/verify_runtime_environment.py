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
    return isinstance(value, str) and bool(ENV_NAME.fullmatch(value) and (
        value.startswith(("WEBLEDGER_", "RESERVATION_INTERNAL_"))
        or value in {"PORT", "APPDATA", "XDG_CONFIG_HOME", "OPENROUTER_API_KEY"}
    ))


def _source_files():
    return [ENTRYPOINT, *(path for base in SOURCE_ROOTS for path in base.rglob("*.py")
                          if "tests" not in path.parts)]


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
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "pick":
            names.update(argument.value for argument in node.args[:2]
                         if isinstance(argument, ast.Constant) and isinstance(argument.value, str))
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


def _references(path: Path, tree: ast.Module, root: Path) -> dict[str, dict]:
    """Return source-only locations and literal fallback expressions per name."""
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
                values = [item.value for item in value.elts
                          if isinstance(item, ast.Constant) and isinstance(item.value, str)]
                for target in targets:
                    if isinstance(target, ast.Name):
                        constant_sequences[target.id] = values
    found: dict[str, dict] = {}
    def record_constant_name(binding, name, node):
        if _valid_env_name(name):
            record(name, node)
    def record(name, node, default=None):
        if not _valid_env_name(name):
            return
        item = found.setdefault(name, {"source": str(path.relative_to(root)), "lines": [], "literal_defaults": []})
        if node.lineno not in item["lines"]:
            item["lines"].append(node.lineno)
        if default is not None:
            item["literal_defaults"].append(ast.unparse(default))
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                record(key.value, node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if _is_environ(node.func.value) and node.args:
                key = node.args[0]
                name = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else constants.get(key.id) if isinstance(key, ast.Name) else None
                record(name, node, node.args[1] if len(node.args) > 1 else None)
            elif isinstance(node.func.value, ast.Name) and node.args:
                key = node.args[0]
                if isinstance(key, ast.Name) and key.id in constants and ENV_BINDING.search(key.id):
                    record(constants[key.id], node, node.args[1] if len(node.args) > 1 else None)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "pick":
            for argument in node.args[:2]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    record(argument.value, node)
        if isinstance(node, (ast.For, ast.comprehension)):
            iterator = node.iter
            if isinstance(iterator, ast.Name):
                for value in constant_sequences.get(iterator.id, ()):
                    record(value, node)
        if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            for generator in node.generators:
                if isinstance(generator.iter, ast.Name):
                    for value in constant_sequences.get(generator.iter.id, ()):
                        record(value, generator)
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in targets:
                    if isinstance(target, ast.Name) and ENV_BINDING.search(target.id):
                        record_constant_name(target.id, node.value.value, node)
    return found


def inspect_catalog(root: Path = ROOT) -> dict:
    catalog_path = root / "config" / "runtime-environment-catalog.json"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("CATALOG_ROOT_NOT_OBJECT")
    if data.get("schema") != "runtime-environment-catalog-v1":
        raise ValueError("CATALOG_SCHEMA")
    if (not isinstance(data.get("scope"), list)
            or any(not isinstance(item, str) or not item.strip() for item in data["scope"])
            or not isinstance(data.get("value_policy"), str)
            or not data["value_policy"].strip()):
        raise ValueError("CATALOG_HEADER_INVALID")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("CATALOG_ENTRIES")
    catalog_names = []
    malformed = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            malformed.append(f"entry#{index}:NOT_OBJECT")
            continue
        name = entry.get("name")
        if not _valid_env_name(name):
            malformed.append(f"entry#{index}:INVALID_NAME")
            continue
        if any(not isinstance(entry.get(field), str) or not entry[field].strip()
               for field in ("owner", "role", "required", "default")):
            malformed.append(f"{name}:MISSING_TYPED_METADATA")
        if entry.get("status") not in ("confirmed", "unknown"):
            malformed.append(f"{name}:INVALID_STATUS")
        if entry.get("status") == "unknown" and (
                not isinstance(entry.get("unresolved_reason"), str)
                or not entry["unresolved_reason"].strip()):
            malformed.append(f"{name}:UNKNOWN_WITHOUT_REASON")
        catalog_names.append(name)
    duplicates = sorted({name for name in catalog_names if catalog_names.count(name) > 1})
    if malformed:
        raise ValueError("CATALOG_ENTRY_INVALID:" + ",".join(malformed))
    observed = set()
    references = {}
    for path in _source_files() if root == ROOT else [root / "run_candidate.py", *[p for folder in (root / "app", root / "webapp") for p in folder.rglob("*.py")]]:
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except OSError as error:
            raise ValueError(f"SOURCE_READ_FAILED:{path.relative_to(root)}") from error
        except UnicodeError as error:
            raise ValueError(f"SOURCE_ENCODING_INVALID:{path.relative_to(root)}") from error
        except SyntaxError as error:
            raise ValueError(f"SOURCE_SYNTAX_INVALID:{path.relative_to(root)}:{error.lineno}") from error
        observed.update(_static_names(path, tree))
        references.update(_references(path, tree, root))
    listed = set(catalog_names)
    missing = sorted(observed - listed)
    stale = sorted(listed - observed)
    unknown = sorted(({"name": entry["name"],
                       "reason": entry.get("unresolved_reason"),
                       "source_refs": entry.get("source_refs")}
                      for entry in entries
                      if isinstance(entry, dict) and entry.get("status") == "unknown"),
                     key=lambda item: item["name"])
    status = "DRIFT" if missing or stale or duplicates else "REVIEW" if unknown else "MATCH"
    return {"check_id": "RF-301.RUNTIME_ENVIRONMENT_CATALOG",
            "hook": "python tools/verify_runtime_environment.py",
            "status": status,
            "observed_count": len(observed), "catalog_count": len(listed),
            "missing": missing, "stale": stale, "duplicates": duplicates,
            "malformed": [], "unknown": unknown,
            "source_references": {name: references[name] for name in sorted(observed) if name in references}}


def status_exit_code(status: str) -> int:
    return {"MATCH": 0, "DRIFT": 1, "REVIEW": 3}[status]


def main() -> int:
    try:
        result = inspect_catalog()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        code = str(error)
        status = "SOURCE_ERROR" if code.startswith("SOURCE_") else "ERROR"
        print(json.dumps({"check_id": "RF-301.RUNTIME_ENVIRONMENT_CATALOG",
                          "hook": "python tools/verify_runtime_environment.py",
                          "status": status, "code": code}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return status_exit_code(result["status"])


if __name__ == "__main__":
    raise SystemExit(main())
