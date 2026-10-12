"""Owner 카드 검토에서 검증된 분기 Google 탭을 조회·복사한다."""
from urllib.parse import quote
from app import google_authority, google_tsv_adapter, quarter_costs
from . import google_ledger_page as google


def targets(originals):
    destinations = {d['id']: d for row in originals if (d := quarter_costs.destination(row))}
    if not destinations:
        return []
    payload = {'trips': []}
    if google.enabled():
        try:
            payload = google.owner_payload(google.snapshot_for_display(
                google_authority.load_snapshot(google._snapshot_path())), google.load_choices(google._snapshot_path()))
        except (google_authority.SnapshotError, OSError, ValueError, KeyError):
            pass
    results = []
    for d in destinations.values():
        matches = [t for t in payload['trips'] if t['key'] == d['sheet'] and t.get('kind') == 'quarter']
        chosen = matches[0] if len(matches) == 1 else {}
        source = chosen.get('chosen_source')
        copy = (chosen.get('copies') or {}).get(source) or {}
        current = (source in ('main', 'archive') and chosen.get('verified')
                   and copy.get('layout') == 'rev' and copy.get('ledger_year') == d['year'])
        href = (f"https://docs.google.com/spreadsheets/d/{google_authority.SPREADSHEET_IDS[source]}"
                f"/edit#range={quote(chr(39) + d['sheet'] + chr(39) + '!B6', safe='')}"
                if current else '')
        results.append({**d, 'available': bool(current), 'source': source if current else None,
                        'transaction_ids': [r['transaction_id'] for r in originals
                                            if (quarter_costs.destination(r) or {}).get('id') == d['id']],
                        'href': href, 'reason': '' if current else '해당 연도·분기의 원본 탭과 지출 합계를 확인해야 합니다.'})
    return results


def export(state, target):
    matching = [d for d in targets(state['rows']) if d['id'] == target]
    if len(matching) != 1 or not matching[0]['available']:
        raise ValueError('QUARTER_SHEET_NOT_READY')
    scoped = quarter_costs.scope(state['rows'], state['preview']['rows'], target)
    return {**google_tsv_adapter.tsv_for_tab(scoped, target), 'destination': matching[0]}
