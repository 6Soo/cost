"""Run-local provider caching must preserve alias authority and concurrency."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch

import pytest
from app import ota_matching_defaults as matching


@pytest.fixture
def policy(monkeypatch):
    value = {'provider_merchant_aliases': {'first': ['same'], 'short': ['hotel'],
        'long': ['hotel.com'], 'korean': ['합성휴양']},
        'provider_merchant_alias_records': {'approved': [
            {'alias': 'signed', 'status': 'approved', 'version': 1, 'source': 'synthetic'},
            {'alias': 'pending', 'status': 'candidate', 'version': 1, 'source': 'synthetic'},
            {'alias': 'unversioned', 'status': 'approved', 'source': 'synthetic'}],
            'second': [{'alias': 'same', 'status': 'approved', 'version': 1, 'source': 'synthetic'}]}}
    monkeypatch.setattr(matching, 'load_defaults', lambda: value)
    return value


def test_cached_and_uncached_results_and_alias_precedence_agree(policy):
    before = deepcopy(policy)
    merchants = ['same', 'HOTEL.COM room', 'hotel room', '합성휴양 결제', 'SIGNED', 'pending',
                 'unversioned', 'unknown', '', None]
    expected = ['first', 'long', 'short', 'korean', 'approved', None, None, None, None, None]
    assert [matching.provider_for_merchant(m) for m in merchants] == expected
    with patch.object(matching, '_resolve_provider', wraps=matching._resolve_provider) as resolve:
        with matching.provider_resolution_scope():
            assert [matching.provider_for_merchant(m) for m in merchants] == expected
            with matching.provider_resolution_scope():
                assert [matching.provider_for_merchant(m) for m in merchants] == expected
            assert resolve.call_count == 8
    assert policy == before


def test_policy_reload_invalidates_cached_positive_and_negative_results(policy, monkeypatch):
    current = [policy]
    monkeypatch.setattr(matching, 'load_defaults', lambda: current[0])
    with matching.provider_resolution_scope():
        assert matching.provider_for_merchant('same') == 'first'
        assert matching.provider_for_merchant('new') is None
        current[0] = {'provider_merchant_aliases': {'replacement': ['same', 'new']}}
        assert matching.provider_for_merchant('same') == 'replacement'
        assert matching.provider_for_merchant('new') == 'replacement'


def test_pinned_candidate_read_does_not_gain_a_policy_file_dependency(monkeypatch):
    from app import ota_payments
    def unavailable():
        raise ValueError('synthetic invalid policy')
    monkeypatch.setattr(matching, 'load_defaults', unavailable)
    with matching.provider_resolution_scope():
        assert matching.provider_for_merchant('') is None
    result = ota_payments.search_card_candidates({'ota_event_id': 'manual'}, [],
                                                existing_links={'manual': 'original-card'})
    assert result['status'] == 'USER_PINNED'


def test_cache_ends_with_scope_and_exception(policy):
    with patch.object(matching, '_resolve_provider', wraps=matching._resolve_provider) as resolve:
        with pytest.raises(RuntimeError):
            with matching.provider_resolution_scope():
                matching.provider_for_merchant('same')
                raise RuntimeError('synthetic')
        matching.provider_for_merchant('same')
        with matching.provider_resolution_scope():
            matching.provider_for_merchant('same')
        assert resolve.call_count == 3


def test_threads_have_separate_scopes(policy):
    barrier = Barrier(2)
    def work(_):
        with matching.provider_resolution_scope() as scope:
            barrier.wait(timeout=3)
            assert matching.provider_for_merchant('same') == 'first'
            return scope
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(work, [1, 2]))
    assert one is not two
    assert matching._provider_ctx.get() is None


def test_async_tasks_have_separate_scopes(policy):
    async def work():
        with matching.provider_resolution_scope() as scope:
            await asyncio.sleep(0)
            assert matching.provider_for_merchant('same') == 'first'
            return scope
    async def run():
        return await asyncio.gather(work(), work())
    one, two = asyncio.run(run())
    assert one is not two
    assert matching._provider_ctx.get() is None
