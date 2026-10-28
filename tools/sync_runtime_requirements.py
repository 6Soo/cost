"""Generate the package requirements mirror from the root runtime declaration.

Default invocation only checks the mirror. --write replaces only the generated
webapp file; this tool never installs or resolves dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    "# Generated from ../requirements.txt; edit the root declaration.\n"
    "# Refresh: python tools/sync_runtime_requirements.py --write\n"
    "# Verify: python tools/sync_runtime_requirements.py\n"
)


def synchronize(root: Path, *, write: bool = False) -> dict:
    source = root / "requirements.txt"
    destination = root / "webapp" / "requirements.txt"
    if destination.is_symlink():
        raise ValueError("MIRROR_SYMLINK")
    declarations = []
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        # Relative include/editable/file paths change meaning under webapp/.
        # Refuse them rather than generate a mirror with different semantics.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~][A-Za-z0-9.,*+!<>=~_-]+)?", value):
            raise ValueError("UNSUPPORTED_REQUIREMENT")
        declarations.append(value)
    if not declarations:
        raise ValueError("EMPTY_REQUIREMENTS")
    expected = (HEADER + "\n".join(declarations) + "\n").encode("utf-8")
    matches = destination.exists() and destination.read_bytes() == expected
    if not matches and write:
        descriptor, name = tempfile.mkstemp(prefix=".requirements-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(expected)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return {"status": "MATCH" if matches else "GENERATED" if write else "DRIFT",
            "declarations": len(declarations)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = synchronize(ROOT, write=args.write)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "code": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}))
        return 2
    print(json.dumps(result))
    return 1 if result["status"] == "DRIFT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
