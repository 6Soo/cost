"""Expense text for lodging and flights: stay dates and passenger names, shown only from evidence.

Every name and date here is synthetic.
"""
from copy import deepcopy
import pytest

from app import flight_evidence
from app.google_tsv import expense_tsv
from webapp import ledger_design as design
from webapp import ota_payment_review
from webapp.read_scope import scoped


def row(row_id, item, **values):
    base = dict(row_id=row_id, row_kind='expense', item=item, occurred_on='2026-10-01',
                amount_krw=1200, description=item, source_merchant='Synthetic merchant',
                reservation_no='', service_period='', operator_note='Preserved note')
    base.update(values)
    return base


def sub(values, passengers=None):
    """The party sub-line for one row, with a passenger index installed for the render."""
    index = passengers or {}
    original = design._load_flight_passengers
    design._load_flight_passengers = lambda: index
    try:
        return design._row_party_sub(values)
    finally:
        design._load_flight_passengers = original


def stay(values):
    return design._stay_text(values)


def lab(value):
    import datetime
    day = datetime.date.fromisoformat(value)
    return f"{day.month}월 {day.day}일({'월화수목금토일'[day.weekday()]})"


class TestLodgingText:
    @pytest.mark.parametrize('segment', ['9/30~10/1', '09/30 ~ 10/01',
                                        '2026-09-30 ~ 2026-10-01'])
    def test_repeated_period_is_only_hidden_in_description(self, segment):
        value = row('stay', '숙박비', reservation_no='SYNTHETIC-R',
                    service_period='2026-09-30 ~ 2026-10-01',
                    description=f'SYNTHETIC-R · {segment} · 조식 포함')
        before = deepcopy(value)
        assert sub(value) == '예약번호 SYNTHETIC-R · 조식 포함'
        assert '1박' in stay(value)
        assert value == before

    @pytest.mark.parametrize('period', ['', '2026-02-30~2026-03-01',
                                      '2026-10-01~2026-09-30', '2026-01-01~2028-01-01',
                                      '2026-09-29~2026-10-01'])
    def test_unknown_or_different_period_keeps_description(self, period):
        value = row('stay', '숙박비', service_period=period,
                    description='9/30~10/1 · 조식 포함')
        assert '9/30~10/1' in sub(value)

    def test_legacy_code_inference_and_ai_provenance_are_distinct(self):
        value = row('stay', '숙박비', reservation_no='SYNTHETIC-R',
                    description='SYNTHETIC-R · 추론 연결 · AI 추론 · 결제일 미확인')
        before = deepcopy(value)
        assert sub(value) == '예약번호 SYNTHETIC-R · 코드 추론 · AI 추론 · 결제일 미확인'
        assert value == before

    def test_a_confirmed_stay_shows_its_dates_and_nights_not_the_reservation(self):
        text = stay(row('stay', '숙박비', reservation_no='664206015', service_period='2026-10-14~2026-10-16'))
        assert text == f"{lab('2026-10-14')} ~ {lab('2026-10-16')} · 2박"
        assert '664206015' not in text

    def test_a_stay_that_crosses_a_year_shows_the_years(self):
        text = stay(row('stay', '숙박비', service_period='2026-12-30~2027-01-02'))
        assert text == '2026년 12월 30일(수) ~ 2027년 1월 2일(토) · 3박'

    def test_a_stay_without_a_period_is_unknown_even_with_a_reservation_number(self):
        text = stay(row('stay', '숙박비', reservation_no='664206015', service_period=''))
        assert text == '이용일 확인 필요'

    def test_a_reversed_or_implausibly_long_period_is_unknown(self):
        assert stay(row('a', '숙박비', service_period='2026-10-16~2026-10-14')) == '이용일 확인 필요'
        assert stay(row('b', '숙박비', service_period='2026-01-01~2027-06-01')) == '이용일 확인 필요'

    def test_a_long_stay_with_a_clear_period_is_not_an_error(self):
        assert stay(row('c', '숙박비', service_period='2026-09-01~2026-10-31')) == f"{lab('2026-09-01')} ~ {lab('2026-10-31')} · 60박"

    def test_an_invalid_calendar_date_is_unknown(self):
        assert stay(row('c', '숙박비', service_period='2026-02-30~2026-03-02')) == '이용일 확인 필요'

    def test_the_card_date_is_never_used_as_the_stay(self):
        text = stay(row('d', '숙박비', occurred_on='2026-10-20', service_period=''))
        assert '10/20' not in text and text == '이용일 확인 필요'

    def test_a_typed_description_is_kept_verbatim_beside_the_stay(self):
        text = stay(row('e', '숙박비', description='팀 숙소 2박', service_period='2026-10-14~2026-10-16'))
        assert text == f"{lab('2026-10-14')} ~ {lab('2026-10-16')} · 2박"
        assert '팀 숙소 2박' in sub(row('e', '숙박비', description='팀 숙소 2박', service_period='2026-10-14~2026-10-16'))


class TestFlightText:
    def test_one_passenger_is_named(self):
        index = {'1400827192926537': {'names': ['KIM ALPHA'], 'conflict': False}}
        assert sub(row('f1', '항공료', reservation_no='1400827192926537'), index) == '탑승자: KIM ALPHA'

    def test_several_passengers_show_the_first_and_the_count(self):
        index = {'R-9': {'names': ['KIM ALPHA', 'LEE BETA', 'PARK GAMMA'], 'conflict': False}}
        assert sub(row('f2', '항공료', reservation_no='R-9'), index) == '탑승자: KIM ALPHA 외 2명'

    def test_no_evidence_or_a_conflict_is_unknown_not_guessed(self):
        assert sub(row('f3', '항공료', reservation_no='R-X'), {}) == '탑승자 확인 필요'
        index = {'R-Y': {'names': ['KIM ALPHA'], 'conflict': True}}
        assert sub(row('f4', '항공료', reservation_no='R-Y'), index) == '탑승자 확인 필요'

    def test_the_payer_name_is_never_used_as_a_passenger(self):
        """Only the names in the index appear; a card holder or booker has no place in it."""
        index = {'R-Z': {'names': ['KIM ALPHA'], 'conflict': False}}
        text = sub(row('f5', '항공료', reservation_no='R-Z', source_merchant='LEE BETA 결제'), index)
        assert text == '탑승자: KIM ALPHA'
        assert 'LEE BETA' not in text

    def test_a_typed_flight_note_is_kept_and_a_bare_category_is_not_repeated(self):
        index = {'R-Q': {'names': ['KIM ALPHA'], 'conflict': False}}
        assert sub(row('f6', '항공료', reservation_no='R-Q', description='항공료'), index) == '탑승자: KIM ALPHA'
        assert sub(row('f7', '항공료', reservation_no='R-Q', description='인천-도쿄'), index) == \
            '탑승자: KIM ALPHA · 인천-도쿄'

    def test_a_flight_without_a_reservation_number_keeps_the_existing_text(self):
        assert sub(row('f8', '항공료', reservation_no='', description='Synthetic note')) == 'Synthetic note'


class TestPassengerIndex:
    def test_the_index_keeps_trip_passengers_and_drops_other_providers(self, monkeypatch):
        evidence = {
            ('trip', 'R-1'): {'passengers': [{'surname': 'KIM', 'given_name': 'ALPHA'}],
                              'conflict': False},
            ('other', 'R-2'): {'passengers': [{'surname': 'LEE', 'given_name': 'BETA'}],
                               'conflict': False},
        }
        monkeypatch.setattr(flight_evidence, 'collect_flight_evidence', lambda directories: evidence)
        assert ota_payment_review._passenger_index([]) == {'R-1': {'names': ['KIM ALPHA'], 'conflict': False}}

    def test_a_mail_read_failure_leaves_the_index_empty(self, monkeypatch):
        def broken(directories):
            raise OSError('synthetic read failure')
        monkeypatch.setattr(flight_evidence, 'collect_flight_evidence', broken)
        assert ota_payment_review._passenger_index([]) == {}


class TestStoredValue:
    def test_the_reservation_number_stays_on_the_row_and_in_the_seven_column_copy(self):
        lodging = row('g1', '숙박비', reservation_no='664206015', service_period='2026-10-14~2026-10-16')
        before = deepcopy(lodging)
        sub(lodging)
        assert lodging == before
        seven = dict(transaction_id='T-1', date='2026-10-14', payee='Synthetic merchant', category='숙박비',
                     period='2026-10-14~2026-10-16', reservation_no='664206015', evidence='card',
                     amount_krw=120000, status='ready')
        tsv = expense_tsv([seven], layout='rev')['tsv']
        assert '664206015' in tsv.split('\t')


class TestPassengerVisibility:
    def test_without_a_refreshed_snapshot_the_name_is_unknown(self, monkeypatch):
        monkeypatch.setattr(ota_payment_review, 'enabled', lambda: False)
        assert design._load_flight_passengers() == {}
        assert sub(row('h1', '항공료', reservation_no='R-7')) == '탑승자 확인 필요'

    def test_the_render_scope_reads_the_index_once(self, monkeypatch):
        calls = []

        def load():
            calls.append(1)
            return {}

        monkeypatch.setattr(design, '_load_flight_passengers', load)

        @scoped
        def render():
            design._flight_passengers()
            design._flight_passengers()

        render()
        assert len(calls) == 1
