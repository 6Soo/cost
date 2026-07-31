"""Shared, history-inclusive integrity checks for polymorphic decisions."""
from __future__ import annotations

import sqlite3


DECISION_ORPHAN_SQL = """
SELECT d.id, d.target_type, d.target_id
FROM classification_decisions d
WHERE (d.target_type='payment' AND NOT EXISTS
       (SELECT 1 FROM payment_transactions p WHERE p.id=d.target_id))
   OR (d.target_type='booking' AND NOT EXISTS
       (SELECT 1 FROM bookings b WHERE b.id=d.target_id))
ORDER BY d.target_type, d.target_id, d.id
"""


def decision_integrity(db: sqlite3.Connection) -> dict[str, object]:
    orphan_rows = db.execute(DECISION_ORPHAN_SQL).fetchall()
    allocation_count = int(db.execute(
        "SELECT COUNT(*) FROM classification_decisions WHERE target_type='allocation'"
    ).fetchone()[0])
    invalid_rows = db.execute(
        """SELECT id, target_type, target_id FROM classification_decisions
           WHERE target_type NOT IN ('payment','booking','allocation') ORDER BY id"""
    ).fetchall()
    return {
        "orphan_count": len(orphan_rows),
        "orphan_sample": [list(row) for row in orphan_rows[:10]],
        "invalid_target_type_count": len(invalid_rows),
        "invalid_target_type_sample": [list(row) for row in invalid_rows[:10]],
        "allocation_target_binding_unconfirmed": allocation_count > 0,
        "allocation_target_binding": "undefined" if allocation_count else None,
        "allocation_decision_count": allocation_count,
    }
