"""Canonical read-only reason classification for the expense cleanup queue."""

REASONS = ('all', 'classification', 'evidence', 'finance', 'manual')
LEGACY_REASONS = {'no_item': 'classification', 'no_trip': 'classification',
                  'protected': 'evidence', 'other_review': 'classification'}


def card_reason_sql(alias='t'):
    """Return the mutually exclusive reason expression for a cleanup card row."""
    t = alias
    return (
        f"CASE WHEN COALESCE({t}.conflict_reason,'')!='' OR COALESCE({t}.parse_error,'')!='' THEN 'evidence'"
        f" WHEN {t}.transaction_direction IN ('cancellation','refund')"
        f" OR EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id={t}.transaction_id AND h.kind IN ('refund_pending','cancelled'))"
        f" OR (COALESCE({t}.approval_number,'')!='' AND ({t}.issuer,{t}.card_tail,{t}.approval_number) IN"
        " (SELECT r.issuer,r.card_tail,r.original_approval_number FROM transactions r"
        " WHERE r.transaction_direction IN ('cancellation','refund'))) THEN 'finance'"
        f" WHEN EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id={t}.transaction_id"
        f" AND h.source_hash={t}.source_hash AND h.kind IN ('manual','manual_hold','owner_hold','user_hold','review_hold')) THEN 'manual'"
        f" WHEN EXISTS(SELECT 1 FROM transaction_review_holds h WHERE h.transaction_id={t}.transaction_id"
        " AND h.kind NOT IN ('trip_needed','classification_needed','existing_ledger')) THEN 'evidence'"
        " ELSE 'classification' END"
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
