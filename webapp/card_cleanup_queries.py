"""Canonical read-only reason classification for the expense cleanup queue."""

REASONS = ('all', 'classification', 'recording', 'evidence', 'finance', 'manual')
OWNERS = ('all', 'user', 'auto')
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
        f" WHEN COALESCE({t}.item,'')!='' AND COALESCE({t}.display_tab_id,'') NOT IN ('','unclassified') THEN 'recording'"
        " ELSE 'classification' END"
    )


def card_owner_action_sql(alias='t'):
    """Return 'user' for rows only a person can settle, else 'auto' (P1/P2 will act)."""
    return (
        "CASE WHEN ({}) IN ('manual','finance','evidence') THEN 'user' ELSE 'auto' END"
        .format(card_reason_sql(alias))
    )


def card_owner_filter(owner, alias='t'):
    if owner not in OWNERS:
        raise ValueError('invalid cleanup owner')
    return '' if owner == 'all' else f' AND ({card_owner_action_sql(alias)})=?'


def card_owner_params(owner):
    if owner not in OWNERS:
        raise ValueError('invalid cleanup owner')
    return () if owner == 'all' else (owner,)


def card_reason_filter(reason, alias='t'):
    """Return a safe SQL predicate for a validated reason, or an empty predicate."""
    if reason not in REASONS:
        raise ValueError('invalid cleanup reason')
    return '' if reason == 'all' else f' AND ({card_reason_sql(alias)})=?'


def card_reason_params(reason):
    if reason not in REASONS:
        raise ValueError('invalid cleanup reason')
    return () if reason == 'all' else (reason,)


def completed_assignment_sql(board):
    """Persisted classification completes review regardless of its rule version.

    Classification is separate from recording. Keep unresolved financial pairs
    visible, and validate destinations with the same authority as write previews.
    Only memoize within the current read render; later reads see corrections.
    """
    from . import read_scope
    from .card_flow import CardFlow
    from app.partial_refund import refund_review_originals

    def destinations():
        flow = CardFlow(board)
        targets = board.conn.execute(
            "SELECT DISTINCT display_tab_id FROM transactions"
            " WHERE classification_state='classified' AND COALESCE(item,'')!=''"
            " AND COALESCE(display_tab_id,'') NOT IN ('','unclassified')"
            " AND NOT EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=transactions.transaction_id)"
            " AND NOT EXISTS(SELECT 1 FROM board_rows b WHERE b.row_id='card-'||transactions.transaction_id)"
            " AND COALESCE(classification_basis,'') NOT LIKE '%complete-card-inference-v1%'"
            " AND classification_source!='refund_original'").fetchall()
        return [target for (target,) in targets if flow.trip_valid(target)]

    valid = read_scope.remember(('cleanup-completed-trips', id(board)), destinations)
    protected = read_scope.remember(('cleanup-refund-originals', id(board)), lambda: refund_review_originals(board.conn))
    protected_sql = ','.join("'" + tid.replace("'", "''") + "'" for tid in protected) or "SELECT NULL WHERE 0"
    quoted = ','.join("'" + target.replace("'", "''") + "'" for target in valid) or "SELECT NULL WHERE 0"
    return (
        "(t.transaction_direction='purchase' AND t.amount_krw>0"
        f" AND COALESCE(t.display_tab_id,'') IN ({quoted})"
        f" AND t.transaction_id NOT IN ({protected_sql}))"
    )
