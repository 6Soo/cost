import copy
import datetime as dt

import pytest

from app import google_authority as ga
from webapp import google_ledger_page as gl
from webapp.tests.test_google_ledger_page import snapshot_doc

NOW = dt.datetime(2026, 10, 11, 12, 0, tzinfo=ga.KST)


@pytest.mark.parametrize('stamp', [(NOW - dt.timedelta(hours=3)).isoformat(),
                                 (NOW + dt.timedelta(hours=1)).isoformat(), None, 'invalid'])
def test_old_missing_or_future_source_is_not_a_confirmed_total(stamp):
    snapshot = snapshot_doc()
    for source in snapshot['sources'].values():
        source['last_ok_at'] = stamp
    before = copy.deepcopy(snapshot)
    display = gl.snapshot_for_display(snapshot, now=NOW)
    assert snapshot == before
    assert all(t['verified'] is False and t['income_total'] is None and t['net'] is None for t in display['trips'])
    assert all('SOURCE_STALE' in t['review'] for t in display['trips'])
    assert all(s['stale'] is True for s in display['sources'].values())


def test_recent_snapshot_keeps_verified_figures():
    snapshot = snapshot_doc()
    for source in snapshot['sources'].values():
        source['last_ok_at'] = (NOW - dt.timedelta(minutes=60)).isoformat()
        source.update(status='ok', stale=False, error_code=None)
    display = gl.snapshot_for_display(snapshot, now=NOW)
    assert display['trips'] == snapshot['trips']


def test_detail_with_unverified_amount_does_not_crash_or_claim_a_final_total():
    detail = {'key': 'synthetic', 'source': 'main', 'verified': False,
              'income': [dict(row=6, date='2026-10-11', name='SYN', nickname='',
                              deposit=None, balance=None, extra=None, amount=None)], 'expense': []}
    text = gl.render_rows_html(detail)
    assert '미확인' in text
    assert '미검증' in text
