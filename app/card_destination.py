"""Read-only card destination labels; legacy workflow states are not a UI model."""
from datetime import date
import re

from .quarter_costs import quarter_of


def trip_payment_source(conn, row):
    """Source payment dates for trip eligibility; a refund uses its verified original."""
    if (row.get('transaction_direction') not in ('refund', 'cancellation')
            and not (isinstance(row.get('amount_krw'), (int, float)) and row['amount_krw'] < 0)):
        return row
    from .partial_refund import refund_links
    link = refund_links(conn, [row['transaction_id']]).get(row['transaction_id'])
    if not link or link.get('inferred') or link.get('status') not in ('full', 'partial'):
        return None
    source = conn.execute('SELECT approval_date,posting_date,transaction_direction,amount_krw '
                          'FROM transactions WHERE transaction_id=?', (link['original_id'],)).fetchone()
    if not source or source[2] != 'purchase' or source[3] <= 0:
        return None
    return dict(approval_date=source[0], posting_date=source[1],
                transaction_direction=source[2], amount_krw=source[3])


def observed_quarter(row):
    """Use source dates only. An invalid payment date never becomes today's date."""
    # A date attached to a row whose source is already known to be malformed
    # is evidence, not a safe basis for inventing a completed destination.
    if row.get('parse_error') or row.get('conflict_reason'):
        return None
    raw = row.get('approval_date') or row.get('posting_date') or ''
    try:
        day = date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None
    year, quarter = quarter_of(day)
    return f'quarter:{year}:{quarter}', f'{year}년 {quarter}분기 기타비용'


def display_destination(row, trip_names=None):
    """Project a destination without changing original, manual or financial facts."""
    names = trip_names or {}
    for key in ('display_tab_id', 'trip_id'):
        identity = row.get(key) or ''
        match = re.fullmatch(r'quarter:(\d{4}):([1-4])', identity)
        if match:
            return f'{match[1]}년 {match[2]}분기 기타비용'
        if identity and identity in names:
            name = names[identity]
            return str(name.get('name') or name.get('display_key') or identity) if isinstance(name, dict) else str(name)
    name = row.get('trip_name') or ''
    if name and name not in ('환불', '미배정', '미분류', 'unclassified'):
        return str(name)
    quarter = observed_quarter(row)
    return quarter[1] if quarter else '기타비용'
