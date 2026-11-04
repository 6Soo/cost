"""Synthetic date/route search regressions; no customer data or external writes."""
from copy import deepcopy
import json
import os
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

from webapp import flight_booking_projection as projection, flight_passenger_page as page
from webapp.tests.test_flight_booking_name_search import Handler


def _booking(city='시즈오카', airport='FSZ', start='2026-11-20', end='2026-11-24'):
    return {'source_digests': ['synthetic'], 'digest': 'synthetic',
            'passengers': [{'surname': 'KIM', 'given_name': 'ALPHA'}],
            'legs': [{'departure_on': start, 'origin_city': '서울', 'destination_city': city,
                      'segments': [{'departure_airport': 'ICN', 'arrival_airport': airport}]},
                     {'departure_on': end, 'origin_city': city, 'destination_city': '서울',
                      'segments': [{'departure_airport': airport, 'arrival_airport': 'ICN'}]}]}


@pytest.mark.parametrize('query', ['22일 시즈오카', '시즈오카 22일', '11/22 FSZ', '11.22 shizuoka',
    '11월 22일', '2026-11-22', '2026년 11월 22일 시즈오카', '２０２６-１１-２２',
    '20일', '24일', 'alpha 시즈오카 22일', 'KIM ALPHA', 'ICN'])
def test_searches_inclusive_travel_period_and_combined_terms(query):
    evidence = _booking()
    before = deepcopy(evidence)
    result = projection.query_booking_reservations({'SYNTH': evidence}, query)
    assert result['total'] == 1
    assert evidence == before


@pytest.mark.parametrize('query', ['19일', '25일', '10/22', '2027-11-22', '22일 fuk',
                                  '22일 beta', 'alph', '김알파', '22일 시즈오카 fuk'])
def test_all_query_terms_must_match(query):
    assert projection.query_booking_reservations({'SYNTH': _booking()}, query)['total'] == 0


@pytest.mark.parametrize('query', ['fuk', 'FUK', '후쿠오카', 'fukuoka', '22일 fuk'])
def test_airport_and_city_aliases(query):
    # Either explicit city or airport evidence can supply the alias.
    for city, airport in [('후쿠오카', ''), ('', 'FUK')]:
        result = projection.query_booking_reservations({'SYNTH': _booking(city, airport)}, query)
        assert result['total'] == 1


@pytest.mark.parametrize('start,end,yes,no', [
    ('2026-11-30', '2026-12-02', '1일', '3일'),
    ('2026-12-30', '2027-01-02', '2027-01-01', '2026-01-01'),
    ('2028-02-28', '2028-03-01', '2/29', '3/2'),
    ('2097-03-01', '2104-02-29', '2/29', '2100-02-29'),
    ('2026-11-22', '', '22일', '23일'),
])
def test_month_year_leap_and_one_way_boundaries(start, end, yes, no):
    index = {'SYNTH': _booking(start=start, end=end)}
    assert projection.query_booking_reservations(index, yes)['total'] == 1
    if no == '2100-02-29':
        with pytest.raises(ValueError, match='INVALID_NAME'):
            projection.query_booking_reservations(index, no)
    else:
        assert projection.query_booking_reservations(index, no)['total'] == 0


def test_unknown_dates_never_use_booking_or_payment_dates_and_unverified_sources_stay_hidden():
    evidence = _booking(start='', end='invalid')
    evidence.update(reserved_on='2026-11-22', booking_card_day='2026-11-22')
    assert projection.query_booking_reservations({'SYNTH': evidence}, '22일')['total'] == 0
    assert projection.query_booking_reservations({'SYNTH': evidence}, '시즈오카')['total'] == 1
    evidence.pop('source_digests')
    assert projection.query_booking_reservations({'SYNTH': evidence}, '시즈오카')['total'] == 0


def test_conflict_and_cancellation_warnings_preserved_without_inferred_conflict_range():
    evidence = _booking()
    evidence.update(conflict=True, cancellation_status='CANCELLED')
    assert projection.query_booking_reservations({'SYNTH': evidence}, '22일')['total'] == 0
    result = projection.query_booking_reservations({'SYNTH': evidence}, '20일 시즈오카')
    assert result['reservations'][0]['conflict'] is True
    assert result['reservations'][0]['cancelled'] is True


def test_revision_is_bound_to_query_even_when_results_identical():
    index = {f'SYNTH-{n}': _booking() for n in range(3)}
    first = projection.query_booking_reservations(index, '22일', limit=1)
    second = projection.query_booking_reservations(index, '22일', limit=1, offset=1, revision=first['revision'])
    assert second['reservations'][0]['booking_ref'] == 'SYNTH-1'
    with pytest.raises(LookupError, match='SOURCE_CHANGED'):
        projection.query_booking_reservations(index, '시즈오카', offset=1, revision=first['revision'])


@pytest.mark.parametrize('query', ['32일', '2/30', '2026-02-29', '0000-11-22', '13월 22일'])
def test_invalid_dates_rejected_before_source_access(query):
    with patch('webapp.flight_booking_index.passenger_index_for') as source:
        with pytest.raises(ValueError, match='INVALID_NAME'):
            page._name_search(object(), query)
        source.assert_not_called()


def test_owner_api_accepts_combined_query_without_changing_write_contract():
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1'}), patch(
        'webapp.flight_booking_index.passenger_index_for', return_value={'SYNTH': _booking()}), patch(
        'webapp.flight_passenger_page._confirmed_card_index', return_value={}):
        handler = Handler()
        page.dispatch(handler, urlsplit('/api/flight-passengers/name-search'), is_owner=True,
                      board=object(), csrf='synthetic-csrf', raw=json.dumps({'name': '22일 시즈오카'}).encode())
        assert handler.response[0] == 200
        assert handler.response[1]['total'] == 1
