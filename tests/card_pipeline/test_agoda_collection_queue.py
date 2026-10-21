"""검증 목록에 없는 예약과 여러 상태에 걸린 예약은 자동 진입하지 않는다."""
import pytest

from tools.collect_agoda_aside import collect_jobs


def test_queue_requires_verified_account_and_unique_list_membership():
    manifest = {'status': 'PASS', 'account_key': 'aside-u0', 'pages': [
        {'list_status': 'completed', 'booking_numbers': ['1234567890', '2345678901']},
        {'list_status': 'cancelled', 'booking_numbers': ['2345678901']},
    ]}
    priorities = {'bookings': [{'booking_number': n} for n in
                              ['1234567890', '2345678901', '3456789012', '1234567890']]}
    jobs, unavailable = collect_jobs(manifest, priorities)
    assert jobs == [('1234567890', 'completed')]
    assert {x['booking_number'] for x in unavailable} == {'2345678901', '3456789012'}
    with pytest.raises(ValueError, match='VERIFIED_LIST_MANIFEST_REQUIRED'):
        collect_jobs({**manifest, 'account_key': 'other'}, priorities)
    with pytest.raises(ValueError, match='INVALID_BOOKING'):
        collect_jobs(manifest, {'bookings': [{'booking_number': '../1234567890'}]})
