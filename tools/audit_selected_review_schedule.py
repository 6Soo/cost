"""Inspect explicit titles in the configured immutable review workbook."""
import collections
import datetime
import hashlib
import json
from pathlib import Path
import re

from openpyxl import load_workbook


def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads(Path('D:/WebLedgerHost/config/real-review.json').read_text(encoding='utf-8-sig'))
    source = Path(config['snapshot_path'])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != config['snapshot_sha256']:
        raise RuntimeError('SELECTED_SNAPSHOT_DIGEST_MISMATCH')
    book = load_workbook(source, read_only=True, data_only=True)
    counts = collections.Counter()
    records = []
    try:
        for sheet in book:
            titles = [cell.value for row in sheet.iter_rows(min_row=2, max_row=2) for cell in row
                      if isinstance(cell.value, str) and '매출 확인자료' in cell.value]
            matching = []
            for title in titles:
                years = re.findall(r'(?<!\d)(\d{4})\s*년', title)
                periods = re.findall(r'(?<!\d)(\d{4})_(\d{4})(?!\d)', title)
                if len(years) != 1 or len(periods) != 1:
                    continue
                year = int(years[0])
                start, end = periods[0]
                try:
                    starts = datetime.date(year, int(start[:2]), int(start[2:]))
                    ends = datetime.date(year, int(end[:2]), int(end[2:]))
                except ValueError:
                    continue
                if ends < starts:
                    continue
                matching.append((year, starts.isoformat(), ends.isoformat()))
            if len(set(matching)) != 1:
                counts['held_no_unique_explicit_title'] += 1
                continue
            year, starts, ends = matching[0]
            counts['explicit_title_rows'] += 1
            records.append({'trip_code': sheet.title, 'event_year': year,
                            'starts_on': starts, 'ends_on': ends,
                            'source_sha256': digest,
                            'source_locator': str(source) + '#' + sheet.title,
                            'authority_status': 'candidate_only',
                            'reason': 'EXPLICIT_TITLE_AWAITING_AUTHORITY_VALIDATION'})
    finally:
        book.close()
    directory = Path('D:/WebLedgerHost/review/schedule-inspection')
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / ('selected-title-candidates-' + digest[:16] + '.json')
    body = json.dumps({'records': records, 'source_sha256': digest}, ensure_ascii=False, indent=2) + '\n'
    if artifact.exists() and artifact.read_text(encoding='utf-8') != body:
        raise RuntimeError('SCHEDULE_INSPECTION_ARTIFACT_CONFLICT')
    if not artifact.exists():
        artifact.write_text(body, encoding='utf-8')
    result = {'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'source_read_only': True, 'source_sha256': digest,
              'source_digest_matches_active': True, 'sheet_count': sum(counts.values()),
              'counts': dict(counts), 'event_year_counts': dict(collections.Counter(r['event_year'] for r in records)),
              'candidate_artifact': str(artifact), 'candidate_artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
              'operational_trip_targets_created': False, 'authority_activated': False,
              'actual_import_performed': False}
    (root / 'docs/handoff/2026-10-01/selected-review-schedule-title-audit.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
