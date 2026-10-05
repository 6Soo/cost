"""Compatibility imports; OTA processing lives in app.ota_mail."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.ota_mail import body_text, extract_mail, match_mail, lodging_mail_matches, europe_stays


def main():
    import argparse
    import json
    import sqlite3
    from pathlib import Path
    parser=argparse.ArgumentParser(description='보존 OTA 메일을 카드와 읽기 전용으로 대조한다')
    parser.add_argument('--mail-dir',required=True)
    parser.add_argument('--database',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    database=Path(args.database).resolve()
    conn=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        report=match_mail(args.mail_dir,[dict(row) for row in conn.execute('SELECT * FROM transactions')])
    finally:
        conn.close()
    output=Path(args.output)
    if output.resolve()==database:
        raise ValueError('OTA_REPORT_CANNOT_REPLACE_DATABASE')
    if output.resolve().is_relative_to(Path(args.mail_dir).resolve()):
        raise ValueError('OTA_REPORT_CANNOT_REPLACE_SOURCE_FILES')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('matches','rules','type_only_candidates','unmatched_transactions')},ensure_ascii=False))


if __name__=='__main__':
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    main()
