import json

from webapp.ota_snapshot import OtaSnapshotService


def test_display_context_keeps_generation_freshness_and_error_together_without_work(tmp_path):
    clock = [0]
    key = ['first']
    failure = [False]
    calls = []

    def reconcile():
        calls.append(key[0])
        if failure[0]:
            raise ValueError('private source path must not appear in display state')
        return {'data': {'events': []}, 'results': [], 'public': {}, 'links': {}}

    service = OtaSnapshotService(key_fn=lambda: key[0], reconcile_fn=reconcile,
                                 clock=lambda: clock[0], start=False)
    current, state = service.display_context()
    assert current is None and state['status'] == 'loading' and not calls

    service.check_now()
    first, state = service.display_context()
    assert state['fresh'] and state['generation'] == first['generation'] == 1

    clock[0] = 151
    current, state = service.display_context()
    assert current is first and state['status'] == 'refreshing' and not state['fresh']
    assert calls == ['first']  # 표시 조회는 대사를 실행하지 않는다.

    key[0] = 'second'
    failure[0] = True
    service.check_now()
    current, state = service.display_context()
    assert current is first and state['status'] == 'error' and not state['fresh']
    assert state['error_code'] == 'ValueError' and 'private' not in json.dumps(state)

    failure[0] = False
    key[0] = 'third'
    service.check_now()
    current, state = service.display_context()
    assert current is not first and state['fresh'] and state['generation'] == 2
    assert first['generation'] == 1  # 이미 확보한 요청의 세대는 갱신되지 않는다.

    # 디스크 복구본은 대사 시각이 최근이어도 전체 근거가 없어 최신으로 승격하지 않는다.
    service._current = dict(current, data=None)
    current, state = service.display_context()
    assert current['generation'] == 2 and state['status'] == 'refreshing' and not state['fresh']
    assert calls == ['first', 'second', 'third']
