"""Owner-only, read-only listing of stored card transactions across all imports."""
import html
import json
import re
from urllib.parse import urlencode

from app.db import decided_sql

from . import ui_icons

PAGE_SIZE = 50
STATES = {'booked': '완료', 'excluded': '제외'}
TRADE_DATE = "COALESCE(NULLIF(t.approval_date,''),t.posting_date)"

from .card_catalog_assets import CATALOG_SCRIPT, CATALOG_STYLE



def catalog(board, query):
    value = lambda key: str((query.get(key) or [''])[0]).strip()
    q, card, state = value('q'), value('card'), value('state')
    month = value('month')
    if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', month):
        month = ''
    order = 'DESC' if value('sort') == 'desc' else 'ASC'
    try:
        page = max(1, int(value('page') or 1))
    except ValueError:
        page = 1
    columns = ('transaction_id', 'batch_id', 'approval_date', 'posting_date', 'issuer', 'card_tail',
               'transaction_direction', 'transaction_kind', 'merchant', 'amount_krw', 'foreign_amount',
               'foreign_currency', 'item', 'description', 'classification_state', 'decided',
               'duplicate_of', 'conflict_reason', 'parse_error', 'display_tab_id', 'classification_source', 'decided_at', 'classification_basis')
    from .history_policy import cutoff
    boundary = cutoff()
    base = f"({TRADE_DATE} IS NULL OR {TRADE_DATE}='' OR {TRADE_DATE}>=?)" if boundary else ''
    where, params = ([base], [boundary]) if base else ([], [])
    if q:
        where.append("(instr(lower(t.merchant || ' ' || t.item || ' ' || t.description || ' ' || "
                     "t.approval_number || ' ' || COALESCE(p.display_key,'')),lower(?))>0)")
        params.append(q)
    if card:
        where.append('t.card_tail=?')
        params.append(card)
    from app.classification_provenance import origin, LABELS
    selected_origin = value('origin')
    if selected_origin in LABELS:
        where.append('COST_CLASSIFICATION_ORIGIN(t.classification_source,t.decided_at,t.classification_basis)=?')
        params.append(selected_origin)
    from .refund_tab import groups
    complete = {r['transaction_id'] for group in groups(board) for r in group}
    state_sql = ("CASE WHEN EXISTS (SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id) THEN 'booked'"
        " WHEN COALESCE(t.duplicate_of,'')!='' OR COALESCE(e.excluded,0)=1"
        " OR t.transaction_id IN (SELECT value FROM json_each(?)) THEN 'excluded'"
        " WHEN COALESCE(t.conflict_reason,'')!='' OR COALESCE(t.parse_error,'')!='' THEN 'review'"
        " WHEN EXISTS (SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id=t.transaction_id"
        " AND h.source_hash=t.source_hash AND h.kind='existing_ledger') THEN 'booked' ELSE 'review' END")
    if state in STATES:
        where.append('(' + state_sql + ')=?')
        params.extend((json.dumps(sorted(complete)), state))
    elif state == 'classified':  # Existing bookmarks remain usable.
        where.append("t.classification_state='classified'")
    if month:
        where.append(f"strftime('%Y-%m',{TRADE_DATE})=?")
        params.append(month)
    clause = ' WHERE ' + ' AND '.join(where) if where else ''
    source = (' FROM transactions t LEFT JOIN trip_tabs p ON p.tab_id=t.display_tab_id'
              ' LEFT JOIN transaction_company_exclusions e ON e.transaction_id=t.transaction_id')
    with board._lock:
        board.conn.create_function('COST_CLASSIFICATION_ORIGIN', 3,
            lambda source, decided_at, basis: origin(dict(classification_source=source,
                decided_at=decided_at, classification_basis=basis)), deterministic=True)
        if not board.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transactions'").fetchone():
            return {'rows': [], 'total': 0, 'all_count': 0, 'cards': [], 'months': [], 'page': 1, 'pages': 1}
        all_count = board.conn.execute('SELECT COUNT(*) FROM transactions t' +
            (' WHERE ' + base if base else ''), [boundary] if base else []).fetchone()[0]
        total = board.conn.execute('SELECT COUNT(*)' + source + clause, params).fetchone()[0]
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        records = board.conn.execute('SELECT ' + ','.join(decided_sql('t') if c == 'decided' else 't.' + c for c in columns)
            + ',COALESCE(p.display_key,\'\'),COALESCE(e.excluded,0)' + source + clause
            + f" ORDER BY ({TRADE_DATE} IS NULL OR {TRADE_DATE}=''),{TRADE_DATE} {order},t.transaction_id"
            + ' LIMIT ? OFFSET ?', [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        cards = [r[0] for r in board.conn.execute('SELECT DISTINCT card_tail FROM transactions t' +
            (' WHERE ' + base if base else '') + ' ORDER BY card_tail', [boundary] if base else [])]
        months = [r[0] for r in board.conn.execute(
            f"SELECT DISTINCT strftime('%Y-%m',{TRADE_DATE}) AS month FROM transactions t "
            'WHERE month IS NOT NULL' + (' AND ' + base if base else '') + ' ORDER BY month ASC',
            [boundary] if base else [])]
    rows = [dict(zip((*columns, 'trip_name', 'company_excluded'), row)) for row in records]
    for row in rows:
        if row['transaction_id'] in complete:
            row['trip_name'] = '환불'
    from app.review_holds import active_holds
    from .card_actions import next_action
    holds = active_holds(board.conn)
    booked = {r[0] for r in board.conn.execute('SELECT transaction_id FROM ledger_entries')}
    for row in rows:
        row['review_hold'] = holds.get(row['transaction_id'])
        row['next_action'] = next_action(
            row,
            {'already_booked': row['transaction_id'] in booked},
        )
    if any(re.search(r'toyoko|토요코인', row.get('merchant') or '', re.I) for row in rows):
        from .card_flow import CardFlow
        notes = CardFlow(board)._ota_candidate_notes(rows)
        for row in rows:
            row['ota_candidate_notes'] = notes.get(row['transaction_id'], [])
    return {'rows': rows,
            'total': total, 'all_count': all_count, 'cards': cards, 'months': months, 'page': page, 'pages': pages}


def render_html(data, query, *, csrf=''):
    """Compatibility document for the retired duplicate catalog interface."""
    kept = {}
    for key in ('year','month','card','q','sort','origin'):
        value = query.get(key)
        if isinstance(value,(tuple,list)):
            value = value[0] if value else ''
        if value:
            kept[key] = str(value)
    target = '/cards/all' + ('?' + urlencode(kept) if kept else '')
    escaped = html.escape(target,quote=True)
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>카드 내역</title></head><body><main><h1>카드 내역</h1>"
            f"<p><a href='{escaped}'>카드 내역 열기</a></p></main></body></html>")
