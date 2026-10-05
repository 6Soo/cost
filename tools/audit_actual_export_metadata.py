"""Check one authorized operational export without copying identities out."""
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import openpyxl


def main():
    reports = Path(__file__).resolve().parents[1] / 'docs/handoff/2026-10-01'
    job_id = json.loads((reports / 'actual-export-request.json').read_text(encoding='utf-8'))['jobId']
    conn = sqlite3.connect('file:D:/WebLedgerHost/data/board.sqlite?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        job = conn.execute('SELECT * FROM ledger_export_jobs WHERE job_id=?', (job_id,)).fetchone()
        if job is None:
            raise RuntimeError('EXPECTED_EXPORT_JOB_NOT_FOUND')
        root = Path(__file__).resolve().parents[1]
        stored_path = Path(job['output_path'])
        path = (stored_path if stored_path.is_absolute() else root / stored_path).resolve()
        allowed = (Path('D:/WebLedgerHost').resolve(), (root / 'webledger-exports').resolve())
        if not any(path.is_relative_to(directory) for directory in allowed):
            raise RuntimeError('EXPORT_PATH_OUTSIDE_PROTECTED_HOST')
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        profile = conn.execute('SELECT company_name,assignee_name FROM owner_profile').fetchone()
        tab_ids = json.loads(job['tab_ids_json'])
        rows = [conn.execute('SELECT display_key,prepared_on,prepared_by_name FROM trip_tabs WHERE tab_id=?', (tab_id,)).fetchone()
                for tab_id in tab_ids]
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
        try:
            matches = {'company': 0, 'assignee': 0, 'title': 0, 'prepared_on': 0}
            for sheet, row in zip(workbook.worksheets, rows):
                matches['company'] += int(sheet['B2'].value == profile['company_name'])
                matches['assignee'] += int(sheet['H4'].value == row['prepared_by_name'] == profile['assignee_name'])
                matches['title'] += int(sheet['C2'].value == row['display_key'])
                matches['prepared_on'] += int(sheet['E4'].value == row['prepared_on'])
            result = dict(recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          read_only=True, identities_exported=False, job_id=job_id, job_status=job['status'],
                          output_sha_matches=actual_sha == job['output_sha256'], output_sha256=actual_sha,
                          file_bytes=path.stat().st_size, selected_tabs=len(tab_ids), sheet_count=len(workbook.worksheets),
                          metadata_matches=matches,
                          cost_rows=conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],
                          nonempty_cost_export_verified=False)
        finally:
            workbook.close()
    finally:
        conn.close()
    (reports / 'actual-export-metadata-audit.json').write_bytes((json.dumps(result, indent=2) + '\n').encode('utf-8'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        safe_codes = {'EXPECTED_EXPORT_JOB_NOT_FOUND', 'EXPORT_PATH_OUTSIDE_PROTECTED_HOST'}
        result = {'success': False, 'error_type': type(exc).__name__,
                  'error_code': str(exc) if str(exc) in safe_codes else 'AUDIT_FAILED'}
        reports = Path(__file__).resolve().parents[1] / 'docs/handoff/2026-10-01'
        (reports / 'actual-export-metadata-audit.json').write_bytes((json.dumps(result, indent=2) + '\n').encode('utf-8'))
        raise
