#!/usr/bin/env python3
"""Read-only static catalog of tracked runtime and maintenance entrypoints."""
from __future__ import annotations
import argparse, json, re, subprocess
import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {".py", ".ps1", ".cmd", ".bat", ".xml", ".yml", ".yaml", ".json", ".toml"}

def tracked_paths(root: Path) -> list[Path]:
    raw = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True).stdout
    paths = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        rel = Path(item.decode("utf-8", "surrogateescape"))
        if rel.parts and rel.parts[0].lower() in {"tools", "app", "webapp", "tests"} and rel.suffix.lower() in EXTENSIONS:
            paths.append(root / rel)
        elif rel.name.lower() in {"run_candidate.py", "run_candidate.ps1", "start.cmd", "start.bat"}:
            paths.append(root / rel)
    return paths

def safe_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")

def classify(path: Path, text: str, root: Path = ROOT) -> tuple[str, str, float]:
    rel = path.as_posix().lower()
    try:
        rel = path.relative_to(root).as_posix().lower()
    except ValueError:
        pass
    low = text.lower()
    if rel.startswith("tests/") or "/tests/" in rel or "/fixtures/" in rel:
        return "TEST_FIXTURE", "Tracked test/fixture path", .99
    if any(x in rel for x in ("history", "archive", "legacy", "old_", "fix_r", "migrate_safe")):
        return "HISTORICAL", "Historical naming/path evidence only; runtime use unverified", .55
    guarded = any(x in low for x in ("write_text(", "write_bytes(", "shutil.copy", "subprocess.run", "deploy", "delete", "unlink(", "commit(", "os.replace"))
    if guarded:
        return "UNKNOWN", "Static marker only; invocation, write capability and safeguards unverified", .3
    if rel in {"run_candidate.py", "webapp/cli.py"} or rel.startswith("tools/"):
        return "UNKNOWN", "Entrypoint-like location; active operational use is not established by name", .4
    return "UNKNOWN", "No reliable runtime-use evidence in this file", .2

def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False

def _repo_rel(value: str) -> bool:
    candidate = Path(value)
    return (bool(value) and not candidate.is_absolute() and ".." not in candidate.parts
            and candidate.as_posix() == value and "\\" not in value)

def _literal_reference(source_path: Path, source_line: int, target_rel: str, root: Path) -> bool:
    """Require an import or exact tracked script path at the declared source line."""
    try:
        lines = source_path.read_text(encoding="utf-8-sig").splitlines()
        line = lines[source_line - 1]
    except (OSError, UnicodeError, IndexError):
        return False
    if source_path.suffix.lower() == ".py":
        try:
            tree = ast.parse("\n" * (source_line - 1) + line)
        except SyntaxError:
            tree = None
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    target_module = target_rel[:-3] if target_rel.endswith(".py") else target_rel
                    if any(target_module == alias.name.replace(".", "/")
                           for alias in node.names):
                        return True
                elif isinstance(node, ast.ImportFrom):
                    package = list(source_path.parent.relative_to(root).parts)
                    if node.level:
                        package = package[:max(0, len(package) - node.level + 1)]
                    else:
                        package = []
                    module_parts = ([node.module] if node.module else [])
                    module_path = "/".join(package + module_parts)
                    candidates = {f"{module_path}.py", f"{module_path}/__init__.py"}
                    if target_rel in candidates:
                        return True
                    if any(f"{module_path}/{alias.name}.py" == target_rel
                           or f"{module_path}/{alias.name}/__init__.py" == target_rel
                           for alias in node.names if alias.name != "*"):
                        return True
    # Script references must be exact repo-relative literals, not arbitrary prose.
    token_pattern = re.compile(r"(?<![\w.])([\w./\\-]+\.(?:py|ps1|cmd|bat|xml))(?![\w])", re.I)
    return any(match.group(1).replace("\\", "/").lower() == target_rel.lower()
               for match in token_pattern.finditer(line))

def load_evidence(root: Path) -> dict:
    """Load only digest-bound, tracked source references with a real invocation edge."""
    root = root.resolve()
    config = root / "config" / "runtime-dependency-evidence.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if (not isinstance(data, dict) or data.get("schema") != "runtime-dependency-evidence/v1"
            or not isinstance(data.get("evidence"), list)):
        return {}
    try:
        tracked_result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                                        check=True, capture_output=True).stdout
        tracked = {item.decode("utf-8", "surrogateescape").replace("\\", "/")
                   for item in tracked_result.split(b"\0") if item}
    except (OSError, subprocess.CalledProcessError, ValueError):
        return {}
    accepted = {}
    for item in data["evidence"]:
        if not isinstance(item, dict):
            continue
        target, source = item.get("path"), item.get("source")
        line, category = item.get("line"), item.get("classification")
        if (not isinstance(target, str) or not isinstance(source, str)
                or not _repo_rel(target) or not _repo_rel(source)
                or not isinstance(line, int) or isinstance(line, bool) or line <= 0
                or category not in {"ACTIVE_SAFE_READ", "ACTIVE_WRITE_GUARDED"}
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()
                or (category == "ACTIVE_WRITE_GUARDED" and item.get("guard") is not True)):
            continue
        target_path, source_path = root / target, root / source
        if (target not in tracked or source not in tracked
                or not _inside_root(target_path, root) or not _inside_root(source_path, root)
                or target_path.is_symlink() or source_path.is_symlink()):
            continue
        try:
            target_bytes = target_path.read_bytes()
            source_bytes = source_path.read_bytes()
            if (hashlib.sha256(target_bytes).hexdigest() != item.get("target_sha256")
                    or hashlib.sha256(source_bytes).hexdigest() != item.get("source_sha256")):
                continue
        except OSError:
            continue
        if not _literal_reference(source_path, line, target, root):
            continue
        accepted[target] = item
    return accepted

def refs(path: Path, text: str, root: Path = ROOT) -> list[dict]:
    out=[]
    for n,line in enumerate(text.splitlines(),1):
        if re.search(r"(?i)(entry.?point|scheduler|worker|deploy|rollback|subprocess|powershell|\.ps1|\.py)",line):
            # Emit only source location, never source text, arguments, or environment values.
            out.append({"source":path.relative_to(root).as_posix(),"line":n})
    return out

def static_dependencies(path: Path, text: str, known: set[str], root: Path = ROOT) -> list[dict]:
    """Return source locations for literal imports and tracked script-path mentions."""
    found = {}
    rel = path.relative_to(root).as_posix()
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    package = list(Path(rel).parent.parts)
                    if node.level:
                        if node.level > len(package):
                            continue
                        package = package[:len(package) - node.level + 1]
                    else:
                        package = []
                    prefix = '.'.join(package + ([node.module] if node.module else []))
                    modules = ([prefix] if prefix else []) + [
                        '.'.join(filter(None, (prefix, alias.name))) for alias in node.names if alias.name != '*']
                else:
                    continue
                for module in modules:
                    stem = module.replace(".", "/")
                    for candidate in (stem + ".py", stem + "/__init__.py"):
                        if candidate in known and candidate != rel:
                            found.setdefault(candidate, node.lineno)
    known_lower = {item.lower(): item for item in known}
    path_literal = re.compile(r"(?i)[\w./\\-]+\.(?:py|ps1|cmd|bat|xml)")
    for line_no, line in enumerate(text.splitlines(), 1):
        for mention in path_literal.findall(line):
            candidate = known_lower.get(mention.replace("\\", "/").lower())
            if candidate and candidate != rel:
                found.setdefault(candidate, line_no)
    return [{"target": target, "source": rel, "line": line} for target, line in sorted(found.items())]

def build_catalog(root: Path = ROOT) -> dict:
    root = root.resolve()
    entries=[]
    errors = []
    try:
        paths = tracked_paths(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"schema_version":1,"mode":"static_read_only","entries":[],
                "errors":[{"code":"GIT_METADATA_ERROR","error_type":type(exc).__name__}],"open_questions":[]}
    known = {p.relative_to(root).as_posix() for p in paths}
    evidence = load_evidence(root)
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            errors.append({"path":rel,"code":"INDIRECT_SOURCE_PATH"})
            continue
        try:
            text=safe_text(path)
        except (OSError, UnicodeError) as exc:
            errors.append({"path":rel,"code":"SOURCE_READ_ERROR","error_type":type(exc).__name__})
            continue
        if path.suffix.lower() == '.py':
            try:
                ast.parse(text)
            except SyntaxError as exc:
                errors.append({"path":rel,"code":"SYNTAX_ERROR","line":exc.lineno})
        category,reason,confidence=classify(path,text,root)
        proof = evidence.get(rel)
        if proof:
            category = proof["classification"]
            reason = f"Digest-bound runtime reference at {proof['source']}:{proof['line']}"
            confidence = .9
        entries.append({"path":rel,"classification":category,"confidence":confidence,"evidence":reason,
                        "references":refs(path,text,root),"dependencies":static_dependencies(path,text,known,root)})
    return {"schema_version":1,"mode":"static_read_only","entries":entries,"errors":errors,"open_questions":[
        "Which tracked scripts are actually invoked by the production Windows scheduler, launcher, deployment, or rollback process?",
        "What are the supported argument contracts and protected input/output paths for each operational entrypoint?",
        "Which apparent write-capable scripts are guarded by verified authorization, backup, and recovery procedures?"
    ]}

def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format",choices=("json","summary"),default="json")
    args=parser.parse_args(argv)
    catalog=build_catalog()
    if args.format=="summary":
        from collections import Counter
        print(json.dumps({"count":len(catalog["entries"]),"classifications":dict(Counter(x["classification"] for x in catalog["entries"])),"open_questions":catalog["open_questions"]},ensure_ascii=False,indent=2))
    else: print(json.dumps(catalog,ensure_ascii=False,indent=2))
    return 2 if catalog['errors'] else 0
if __name__=="__main__": raise SystemExit(main())
