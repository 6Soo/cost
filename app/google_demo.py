"""Anonymous top-three projection for the public demo. Builds data only; serves nothing.

Input is the public Google snapshot view, which holds totals and check codes and no names.
Output holds rank and amounts only: no trip title, no dates, no sheet or row references.
A demo is never published from unverified, unclosed or stale figures, and when the ranking
cannot be decided it keeps the previous safe projection instead of guessing.
"""

from __future__ import annotations

PUBLISHABLE_CLOSURE = "closed"
TOP = 3


def _eligible(trip: dict) -> bool:
    return (trip["closure"] == PUBLISHABLE_CLOSURE
            and trip["closure_current"]
            and trip["verified"]
            and trip["net"] is not None
            and trip["income_total"] is not None
            and trip["expense_total"] is not None)


def build_demo(snapshot: dict | None, previous: dict | None = None) -> dict:
    """Returns the public demo payload, or the previous safe payload marked stale."""
    if snapshot is None:
        return _kept(previous, reason="NO_SNAPSHOT")
    sources = snapshot.get("sources", {})
    if any(source.get("status") != "ok" for source in sources.values()):
        return _kept(previous, reason="SOURCE_NOT_CURRENT")
    candidates = sorted((t for t in snapshot.get("trips", []) if _eligible(t)),
                        key=lambda t: t["net"], reverse=True)
    head = candidates[:TOP + 1]
    if any(a["net"] == b["net"] for a, b in zip(head, head[1:])):
        # Ties inside the top three or across the cut-off have no approved tie-break.
        return _kept(previous, reason="TIE_UNDECIDED")
    entries = [{"rank": index, "income_total": t["income_total"], "expense_total": t["expense_total"],
                "net": t["net"]} for index, t in enumerate(candidates[:TOP], start=1)]
    return {"status": "published" if len(entries) == TOP else "partial", "stale": False,
            "as_of": snapshot.get("synced_at"), "entries": entries}


def _kept(previous: dict | None, *, reason: str) -> dict:
    if previous is None:
        return {"status": "preparing", "stale": True, "reason": reason, "entries": []}
    return {**previous, "stale": True, "reason": reason}
