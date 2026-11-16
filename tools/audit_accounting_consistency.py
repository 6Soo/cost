"""Read a consistent SQLite snapshot; print aggregate accounting discrepancies.

No initializers, migrations, imports, financial writers or Google writes run.
Use the returned codes with the source originals before correcting a judgement.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from app.accounting_audit import audit_cards
from app.manual_overrides import manual_fields


def audit(path):
    conn=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        tables=('transactions','ledger_entries','board_rows','trip_tabs')
        data={name:[dict(r) for r in conn.execute('SELECT * FROM '+name)] for name in tables}
        report=audit_cards(*(data[name] for name in tables),manual_fields=manual_fields(conn))
        report['database_changes']=conn.total_changes
        return report
    finally:
        conn.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-db',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        report=audit(args.board_db)
        # Source identifiers and individual findings remain local to callers.
        print(json.dumps({k:v for k,v in report.items() if k!='findings'},ensure_ascii=False))
        return 0
    except (OSError,sqlite3.Error,ValueError,TypeError):
        print(json.dumps(dict(available=False,reason='AUDIT_SOURCE_UNAVAILABLE')))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
