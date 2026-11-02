"""Independent boundary checks for query coverage, using synthetic data only."""

import sqlite3

from app.card_upload_coverage import CoverageStore, Period, find_gaps, parse_iso_date


def test_constructing_a_coverage_reader_never_creates_database_objects():
    with sqlite3.connect(':memory:') as conn:
        before = conn.execute('SELECT type,name,sql FROM sqlite_master').fetchall()
        CoverageStore(conn)
        assert conn.execute('SELECT type,name,sql FROM sqlite_master').fetchall() == before


def test_invalid_calendar_dates_cannot_become_coverage_boundaries():
    for value in ('2026-02-31', '20260231', '2026.02.31', '2026-13-01'):
        assert parse_iso_date(value) is None


def test_gaps_stay_inside_management_start_and_through():
    periods = [Period('2026-04-01', '2026-04-10'),
               Period('2026-05-01', '2026-05-10')]
    # test_gaps doesn't use CoverageStore, it just uses the Period class and find_gaps
    gaps = find_gaps(periods, '2026-04-20', '2026-04-25')
    assert [(gap.start, gap.end) for gap in gaps] == [('2026-04-20', '2026-04-25')]


def test_coverage_after_the_requested_window_cannot_create_future_gaps():
    periods = [Period('2026-05-01', '2026-05-10')]
    gaps = find_gaps(periods, '2026-04-01', '2026-04-10')
    assert [(gap.start, gap.end) for gap in gaps] == [('2026-04-01', '2026-04-10')]
