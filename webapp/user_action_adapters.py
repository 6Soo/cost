"""Retired card P3 adapter compatibility; historical audit records are retained.

No active caller registers or consumes card questions. These old import names
return zero without reading or writing either the card store or task history.
"""


def register_card_item_tasks(conn, rows, job_loader):
    return 0


def apply_card_item_answers(conn, flow):
    return 0
