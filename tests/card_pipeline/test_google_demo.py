from app.google_demo import build_demo

SYNCED = "2026-10-11T10:00:00+09:00"


def trip(key, net, **overrides):
    base = {"key": key, "closure": "closed", "closure_current": True, "canonical_source": "archive",
            "income_total": net + 100, "expense_total": 100, "net": net, "verified": True,
            "copies": {}, "review": []}
    base.update(overrides)
    return base


def snap(trips, *, status="ok"):
    sources = {"main": {"status": status}, "archive": {"status": "ok"}}
    return {"synced_at": SYNCED, "sources": sources, "trips": trips}


def test_top_three_closed_verified_by_net_without_titles():
    demo = build_demo(snap([trip("A-SECRET-TITLE", 500), trip("B", 900), trip("C", 700), trip("D", 300)]))
    assert demo["status"] == "published" and demo["stale"] is False
    assert [e["net"] for e in demo["entries"]] == [900, 700, 500]
    assert [e["rank"] for e in demo["entries"]] == [1, 2, 3]
    assert "SECRET" not in str(demo) and "key" not in demo["entries"][0]


def test_open_unverified_and_stale_closure_are_excluded():
    trips = [trip("OPEN", 999, closure="open"),
             trip("UNVERIFIED", 998, verified=False),
             trip("STALE", 997, closure_current=False),
             trip("GOOD1", 100), trip("GOOD2", 90), trip("GOOD3", 80)]
    demo = build_demo(snap(trips))
    assert [e["net"] for e in demo["entries"]] == [100, 90, 80]


def test_fewer_than_three_is_partial_never_padded():
    demo = build_demo(snap([trip("A", 10)]))
    assert demo["status"] == "partial" and len(demo["entries"]) == 1


def test_tie_inside_top_three_or_at_cutoff_keeps_previous():
    previous = build_demo(snap([trip("A", 300), trip("B", 200), trip("C", 100)]))
    tied = build_demo(snap([trip("A", 300), trip("B", 200), trip("C", 200), trip("D", 50)]), previous)
    assert tied["stale"] is True and tied["reason"] == "TIE_UNDECIDED"
    assert [e["net"] for e in tied["entries"]] == [300, 200, 100]


def test_failed_source_keeps_last_safe_projection_and_marks_stale():
    previous = build_demo(snap([trip("A", 300), trip("B", 200), trip("C", 100)]))
    failed = build_demo(snap([trip("A", 999), trip("B", 1), trip("C", 1)], status="error"), previous)
    assert failed["stale"] is True and failed["reason"] == "SOURCE_NOT_CURRENT"
    assert failed["as_of"] == SYNCED and [e["net"] for e in failed["entries"]] == [300, 200, 100]


def test_no_snapshot_without_previous_is_preparing_not_real_data():
    demo = build_demo(None)
    assert demo == {"status": "preparing", "stale": True, "reason": "NO_SNAPSHOT", "entries": []}
