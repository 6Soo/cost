"""Google income read projection with the existing canonical-copy and grant rules."""
from decimal import Decimal, InvalidOperation
import re


def _amount(value):
    if value in (None, '') or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).replace(',', ''))
        return int(number) if number.is_finite() and number == number.to_integral_value() else None
    except (InvalidOperation, ValueError):
        return None


def load(tab_id, *, owner, session, visible_tabs):
    from . import google_ledger_page as page, read_scope
    empty = dict(available=False, verified=False, rows=[], total=None, reason='NOT_CONNECTED')
    if not page.enabled() or not tab_id or tab_id == 'unclassified':
        return empty
    if not owner and tab_id not in visible_tabs:
        return dict(empty, reason='FORBIDDEN')
    try:
        path = page.snapshot_path()
        mapping = read_scope.remember(('plush_income_mapping', str(path)), lambda: page.load_mapping(path))
        keys = [key for key, target in mapping.items() if target == tab_id]
        if len(keys) != 1:
            return dict(empty, reason='MAPPING_AMBIGUOUS' if keys else 'NOT_CONNECTED')
        key = keys[0]
        if not owner:
            grants = page.load_grants(path)
            if key not in page.viewer_allowed_keys(grants, session.user_id, mapping, visible_tabs):
                return dict(empty, reason='FORBIDDEN')
        # Authorization precedes loading private names and source amounts.
        snapshot, sources = read_scope.remember(
            ('plush_income_sources', str(path)), lambda: page._load_consistent_measured(path, page.rows_path()))
        payload = page.owner_payload(page.snapshot_for_display(snapshot), page.load_choices(path))
        matches = [trip for trip in payload['trips'] if trip['key'] == key]
        if len(matches) != 1:
            return dict(empty, reason='SOURCE_UNAVAILABLE')
        trip = matches[0]
        source = trip.get('chosen_source')
        if source not in page.google_authority.SPREADSHEET_IDS:
            return dict(empty, reason='COPY_UNRESOLVED')
        detail = page.owner_rows(sources, key, source)
        if detail is None:
            return dict(empty, reason='SOURCE_UNAVAILABLE')
        state = (payload.get('sources') or {}).get(source) or {}
        block = ((trip.get('copies') or {}).get(source) or {}).get('income') or {}
        verified = bool(block.get('verified') and state.get('status') == 'ok' and not state.get('stale')
                        and not set(trip.get('review') or []) & page.OWNER_CHOICE_BLOCKERS)
        rows = []
        total = 0
        # The numeric rows intentionally omit blank/formula-error H cells.
        # The same-generation private index preserves those participant rows.
        raw_rows = {raw['row']: raw for raw in detail['income']}
        names = page.owner_income_names(sources, key, source)
        if names and names.get('available'):
            for indexed in names['rows']:
                if indexed['row'] in raw_rows:
                    continue
                cells = indexed.get('cells') or {}
                # Older private indexes include the layout's footer: its B cell
                # says total and C contains the amount, rather than a person.
                if re.fullmatch(r'(?:총\s*금액|합계|총계|total)(?:\s*\([A-Z]\))?',
                                str(cells.get('B') or '').strip(), re.I):
                    continue
                raw_rows[indexed['row']] = dict(row=indexed['row'], date=cells.get('B'),
                    name=indexed.get('name') or cells.get('C'), nickname=indexed.get('nickname') or cells.get('D'),
                    deposit=cells.get('E'), balance=cells.get('F'), extra=cells.get('G'), amount=indexed.get('amount'))
        for raw in sorted(raw_rows.values(), key=lambda row: row['row']):
            if page.is_unconfirmed_income_row(raw):
                continue
            amount = _amount(raw.get('amount'))
            if amount is None:
                verified = False
            else:
                total += amount
            parts = {name: (str(_amount(raw.get(field))) if _amount(raw.get(field)) is not None else '')
                     for name, field in (('예약금', 'deposit'), ('잔금', 'balance'), ('추가금', 'extra'))}
            # Store original display components as text; never treat a blank total as zero.
            rows.append(dict(row_id=f"google-income|{tab_id}|{source}|{raw['row']}",
                row_kind='income', display_tab_id=tab_id, occurred_on=page.format_transaction_date(raw.get('date')),
                customer_name=str(raw.get('name') or raw.get('nickname') or ''),
                nickname=str(raw.get('nickname') or ''), income_kind='Google 수입',
                description=' · '.join(f'{label} {value}원' for label, value in parts.items() if value),
                amount_krw=amount, source_kind='Google', evidence_type='Google 수입 장부',
                source_event_id=f'{source}:{key}:{raw["row"]}', revision=None,
                google_income=True, amount_missing=amount is None))
        if block.get('total') is not None and _amount(block['total']) != total:
            verified = False
        return dict(available=True, verified=verified, rows=rows, total=str(total),
                    reason='' if verified else 'INCOME_UNVERIFIED', source=source)
    except (OSError, ValueError, KeyError, TypeError):
        return dict(empty, reason='SOURCE_UNAVAILABLE')
