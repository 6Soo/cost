from app.automatic_classification import infer_trip
from app.provisional_assignment import card_trip_candidates
from app.trip_selection import card_trip_allowed


JEJU = dict(trip_id='jeju', display_key='0909_제주', destination='제주',
            starts_on='2026-09-09', ends_on='2026-09-15')
SEJONG = dict(trip_id='sejong', display_key='0912_세종', destination='세종',
              starts_on='2026-09-12', ends_on='2026-09-14')


def test_jeju_card_scope_excludes_other_cards_before_ranking_and_existing_trip():
    row = dict(card_tail='8835', approval_date='2026-09-12', merchant='택시',
               trip_id='jeju', display_tab_id='jeju')
    assert infer_trip(row, [JEJU, SEJONG])[0] == 'sejong'
    assert {r['trip_id'] for r in card_trip_candidates(row, [JEJU, SEJONG])} == {'sejong'}


def test_4813_is_eligible_but_not_forced_to_jeju_and_other_trips_unchanged():
    assert card_trip_allowed({'card_tail': '4813'}, JEJU)
    assert card_trip_allowed({'card_tail': '8835'}, SEJONG)
    assert card_trip_allowed({'card_tail': '8835'}, dict(JEJU, starts_on='2027-09-09'))
    assert not card_trip_allowed({}, JEJU)
    row = dict(card_tail='4813', approval_date='2026-09-12', merchant='택시', trip_id='sejong')
    assert infer_trip(row, [JEJU, SEJONG])[0] == 'sejong'
