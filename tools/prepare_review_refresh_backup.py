"""Back up the current review config and choices into the protected host root."""
import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from webapp.real_review import BoundInputs, load_manifest


def main():
    config = Path(r"D:\WebLedgerHost\config\real-review.json")
    manifest = load_manifest(str(config))
    inputs = BoundInputs(manifest)
    db = Path(manifest["decisions_db_path"])
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(r"D:\WebLedgerHost\data\backups") / ("review-refresh-" + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "real-review.json").write_bytes(config.read_bytes())
    source = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(backup / "real-review.sqlite")
    try:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("BACKUP_INTEGRITY_FAILED")
        row = target.execute(
            "SELECT revision, choices_json FROM review_choice_sets WHERE binding=?",
            (inputs.binding,),
        ).fetchone()
        choices = json.loads(row[1]) if row else {}
        result = {
            "backup_directory": str(backup),
            "integrity_ok": True,
            "binding": inputs.binding,
            "revision": row[0] if row else 0,
            "selected": sum(value not in ("", "REJECT") for value in choices.values()),
            "rejected": sum(value == "REJECT" for value in choices.values()),
            "actual_import_performed": False,
        }
    finally:
        target.close()
        source.close()
    (ROOT / "docs/handoff/2026-10-01/source-refresh-backup.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("REVIEW_REFRESH_BACKUP_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
