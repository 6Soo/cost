"""Shared final inference stage for current and future imported card transactions."""
from app import automatic_classification as policy


def missing_assignment_sql(alias='t'):
    """An automatic category alone cannot complete an ordinary trip expense."""
    return (f"({alias}.classification_state='classified'"
            f" AND COALESCE({alias}.item,'') NOT IN ('','분기 기타비용')"
            f" AND COALESCE({alias}.classification_source,'')!='guide_airfare_evidence'"
            f" AND COALESCE({alias}.display_tab_id,'') IN ('','unclassified')"
            f" AND COALESCE({alias}.trip_id,'') IN ('','unclassified'))")


def context(flow):
    from .card_flow import _google_nets
    trips = [dict(trip, trip_id=trip['tab_id']) for trip in flow.board.list_trips()
             if flow.trip_valid(trip['tab_id'])]
    return trips, _google_nets()


def complete(flow, batch_id, transaction_ids=None):
    selected = {row[0] for row in flow.board.conn.execute(
        'SELECT transaction_id FROM import_batch_rows WHERE batch_id=?', (batch_id,))}
    if transaction_ids is not None:
        selected.intersection_update(transaction_ids)
    return complete_scope(flow, selected)


def complete_scope(flow, selected=None):
    with flow.board._lock:
        trips, nets = context(flow)
        preview = policy.plan(flow.board.conn, trips, nets=nets, transaction_ids=selected)
        return policy.apply(flow.board.conn, preview, trips, nets=nets, transaction_ids=selected)
