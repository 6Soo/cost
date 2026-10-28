"""Canonical read-only reason classification for the expense cleanup queue."""

REASONS = ('all', 'no_item', 'no_trip', 'protected', 'other_review')


def card_reason_sql(alias='t'):
    """Return the mutually exclusive reason expression for a cleanup card row."""
    t = alias
    return (
        f"CASE WHEN {t}.transaction_direction='cancellation'"
        f" OR COALESCE({t}.conflict_reason,'')!='' OR COALESCE({t}.parse_error,'')!=''"
        f" OR EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id={t}.transaction_id)"
        " THEN 'protected'"
        f" WHEN COALESCE({t}.item,'')='' THEN 'no_item'"
        f" WHEN COALESCE({t}.display_tab_id,'') IN ('','unclassified') THEN 'no_trip'"
        " ELSE 'other_review' END"
    )


def card_reason_filter(reason, alias='t'):
    """Return a safe SQL predicate for a validated reason, or an empty predicate."""
    if reason not in REASONS:
        raise ValueError('invalid cleanup reason')
    return '' if reason == 'all' else f' AND ({card_reason_sql(alias)})=?'


def card_reason_params(reason):
    if reason not in REASONS:
        raise ValueError('invalid cleanup reason')
    return () if reason == 'all' else (reason,)
