from copy import deepcopy
from unittest.mock import patch

from webapp import ledger_board as board, ledger_design


def trip(key, starts_on, **extra):
    return dict(tab_id=key, display_key=key, destination="Synthetic", starts_on=starts_on,
                ends_on=starts_on, **extra)


def render(trips, selected="", query="", role="owner", allowed=()):
    with patch.object(board, "live_trips", return_value=trips), \
         patch.object(board, "current_role", return_value=role), \
         patch.object(board, "viewer_visible_tabs", return_value=set(allowed)), \
         patch.object(board, "current_request_session", return_value=None), \
         patch.object(board, "_unclassified_rows", return_value=[]):
        return ledger_design.nav_region(selected, query)


def test_previous_and_archived_trips_are_removed_from_shared_sidebar():
    trips = [trip("early", "2026-04-01"), trip("boundary", "2026-06-25"),
             trip("later", "2026-06-26"), trip("next-year", "2027-06-25"),
             trip("unknown", ""), trip("invalid", "2026-02-31"),
             trip("old-archived", "2026-06-01", archived=True),
             trip("deleted", "2026-06-20", deleted=True)]
    before = deepcopy(trips)
    html = render(trips)
    for key in ("early", "boundary", "old-archived", "deleted"):
        assert f"tab={key}" not in html
    for key in ("later", "next-year", "unknown", "invalid"):
        assert f"tab={key}" in html
    assert "이전 여행" not in html
    assert "보관 목록" not in html
    assert "여행 전체 보기" in html
    assert trips == before


def test_sidebar_lists_active_trips_and_current_quarter_only():
    markup = render([trip("old-1", "2026-05-01")])
    assert "old-1" not in markup
    assert "이번 분기 기타비용" in markup
    assert "<details" not in markup


def test_shared_sidebar_does_not_render_refund_section():
    markup = render([trip("current-1", "2026-10-01")])
    assert "nv-icon" in markup
    assert "<span class='nm'>환불</span>" not in markup


def test_viewer_sees_only_allowed_active_trips_without_history_drawer():
    trips = [trip("allowed-active", "2027-06-25"), trip("secret-active", "2027-06-24"),
             trip("allowed-old", "2026-06-25"), trip("secret-old", "2026-06-24")]
    html = render(trips, selected="allowed-active", role="viewer", allowed=("allowed-active", "allowed-old"))
    assert '<details' not in html
    assert 'secret-old' not in html
    assert 'allowed-old' not in html
    assert 'tab=allowed-active' in html
    assert 'secret-active' not in html
    assert "aria-current='page'" in html
    html = render(trips, query="allowed-old")
    assert '<details' not in html
    assert 'tab=secret-old' not in html
