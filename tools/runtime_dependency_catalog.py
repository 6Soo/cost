#!/usr/bin/env python3
"""Read-only static catalog of tracked runtime and maintenance entrypoints."""
from __future__ import annotations
import argparse, json, re, subprocess
import ast
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
        if rel.parts and rel.parts[0].lower() in {"tools", "app", "webapp"} and rel.suffix.lower() in EXTENSIONS:
            paths.append(root / rel)
        elif rel.name.lower() in {"run_candidate.py", "run_candidate.ps1", "start.cmd", "start.bat"}:
            paths.append(root / rel)
    return paths

def safe_text(path: Path) -> str:
    try: return path.read_text(encoding="utf-8", errors="replace")
    except OSError: return ""

def classify(path: Path, text: str) -> tuple[str, str, float]:
    rel = path.as_posix().lower()
    try:
        rel = path.relative_to(ROOT).as_posix().lower()
    except ValueError:
        pass
    low = text.lower()
    if rel.startswith("tests/") or "/tests/" in rel or "/fixtures/" in rel:
        return "TEST_FIXTURE", "Tracked test/fixture path", .99
    if any(x in rel for x in ("history", "archive", "legacy", "old_", "fix_r", "migrate_safe")):
        return "HISTORICAL", "Historical naming/path evidence only; runtime use unverified", .55
    guarded = any(x in low for x in ("write_text(", "write_bytes(", "shutil.copy", "subprocess.run", "deploy", "delete", "unlink(", "commit(", "os.replace"))
    if guarded:
        return "ACTIVE_WRITE_GUARDED", "Static write/deploy/process marker; invocation and safeguards require confirmation", .58
    if rel in {"run_candidate.py", "webapp/cli.py"} or rel.startswith("tools/"):
        return "UNKNOWN", "Entrypoint-like location; active operational use is not established by name", .4
    return "UNKNOWN", "No reliable runtime-use evidence in this file", .2

def refs(path: Path, text: str) -> list[dict]:
    out=[]
    for n,line in enumerate(text.splitlines(),1):
        if re.search(r"(?i)(entry.?point|scheduler|worker|deploy|rollback|subprocess|powershell|\.ps1|\.py)",line):
            # Emit only source location, never source text, arguments, or environment values.
            out.append({"source":path.relative_to(ROOT).as_posix(),"line":n})
            if len(out)>=40: break
    return out

def static_dependencies(path: Path, text: str, known: set[str]) -> list[dict]:
    """Return source locations for literal imports and tracked script-path mentions."""
    found = {}
    rel = path.relative_to(ROOT).as_posix()
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
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
    entries=[]
    paths = tracked_paths(root)
    known = {p.relative_to(root).as_posix() for p in paths}
    for path in paths:
        text=safe_text(path)
        category,reason,confidence=classify(path,text)
        entries.append({"path":path.relative_to(root).as_posix(),"classification":category,"confidence":confidence,"evidence":reason,"references":refs(path,text),"dependencies":static_dependencies(path,text,known)})
    return {"schema_version":1,"mode":"static_read_only","entries":entries,"open_questions":[
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
    return 0
if __name__=="__main__": raise SystemExit(main())
