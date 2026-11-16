"""Which `board_manual_overrides` records are real manual corrections.

A record stops counting only when the save that wrote it is recorded with a non-person actor (anything but
`owner`, `owner-*`: batch tools, the automatic writer) and no person ever changed that field of the row in a later
revision than its creation. Such records stay in the table (source preserved) but are not manual (TRIP-033).
A record without a known save (pending `event_id=''`, or no revision) stays manual.
The Rust core (`store/plan_input.rs`) uses the same SQL; keep them identical.
"""


def is_human_actor(actor) -> bool:
    return actor == 'owner' or str(actor or '').startswith('owner-')


def human_sql(alias='o'):
    """SQL condition: override row `alias` was not written by a tool or the automatic writer."""
    return (f"(NOT EXISTS(SELECT 1 FROM board_revisions hr WHERE hr.row_id={alias}.row_id"
            f" AND hr.event_id={alias}.event_id AND {alias}.event_id!=''"
            f" AND NOT (hr.actor='owner' OR hr.actor LIKE 'owner-%'))"
            f" OR EXISTS(SELECT 1 FROM board_revisions hp WHERE hp.row_id={alias}.row_id AND hp.revision>1"
            f" AND (hp.actor='owner' OR hp.actor LIKE 'owner-%')"
            f" AND json_extract(hp.prev_json,'$.'||{alias}.field) IS NOT json_extract(hp.new_json,'$.'||{alias}.field)))")


def _has_revisions(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_revisions'").fetchone() is not None


def filter_sql(conn, alias='o'):
    """`human_sql`, or always-true when the database has no revision history to tell (all records stay manual)."""
    return human_sql(alias) if _has_revisions(conn) else '1=1'


def exists_sql(conn, row_expr, field=None, alias='mo'):
    """SQL `EXISTS(...)`: the row has a real manual override (optionally of one field)."""
    field_sql = f" AND {alias}.field='{field}'" if field else ''
    return (f"EXISTS(SELECT 1 FROM board_manual_overrides {alias} WHERE {alias}.row_id={row_expr}{field_sql}"
            f" AND {filter_sql(conn, alias)})")


def manual_fields(conn):
    """{(row_id, field)} of real manual overrides."""
    if not _has_revisions(conn):
        return {(r[0], r[1]) for r in conn.execute('SELECT row_id, field FROM board_manual_overrides')}
    # Equivalent to human_sql, but scan history once per set instead of twice
    # per override. Operational copies may have no board_revisions indexes.
    # Materialization also prevents SQLite from inlining the correlated work.
    return {(r[0], r[1]) for r in conn.execute(
        """WITH tool_saves AS MATERIALIZED (
            SELECT DISTINCT row_id,event_id FROM board_revisions
            WHERE NOT (actor='owner' OR actor LIKE 'owner-%')
        ), human_changes AS MATERIALIZED (
            SELECT DISTINCT o.row_id,o.field
            FROM board_revisions hp JOIN board_manual_overrides o ON o.row_id=hp.row_id
            WHERE hp.revision>1 AND (hp.actor='owner' OR hp.actor LIKE 'owner-%')
              AND json_extract(hp.prev_json,'$.'||o.field)
                  IS NOT json_extract(hp.new_json,'$.'||o.field)
        )
        SELECT o.row_id,o.field FROM board_manual_overrides o
        LEFT JOIN tool_saves ts ON ts.row_id=o.row_id AND ts.event_id=o.event_id AND o.event_id!=''
        LEFT JOIN human_changes hc ON hc.row_id=o.row_id AND hc.field=o.field
        WHERE ts.row_id IS NULL OR hc.row_id IS NOT NULL""")}


def manual_rows(conn):
    """Row ids with any real manual override."""
    if not _has_revisions(conn):
        return {r[0] for r in conn.execute('SELECT row_id FROM board_manual_overrides')}
    return {row_id for row_id, _ in manual_fields(conn)}
