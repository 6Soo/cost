"""시저장 OTA 카탈로그 투영 대조 도구의 계약을 합성 자료로 검사한다.

`measure(path, *, repeats=5)`는 저장 `ota_catalog_rows`와 보존 원문 재구성
(`_catalog_read_rows`)을 비교해 `match`·`stored_rows`·`reconstructed_rows`·
`stored_ms`·`reconstructed_ms`를 돌려준다. CLI는 일치하면 exit 0, 차이나
실패·양쪽 0행이면 nonzero로 집계 JSON만 출력하고 DB를 쓰지 않는다.
"""
import json

import pytest

from app.ota_store import OtaStore, commit_state, packed, unpacked
from tests.card_pipeline.test_ota_portal import portal_database
from tools.measure_ota_catalog_projection import main, measure

REQUIRED_KEYS = {'match', 'stored_rows', 'reconstructed_rows', 'stored_ms', 'reconstructed_ms'}


@pytest.fixture
def store(tmp_path):
    source = portal_database(tmp_path / 'synthetic-portal.sqlite', [
        {'booking_number': 'synthetic-first'},
        {'booking_number': 'synthetic-second',
         'service_start_on': '2026-09-01', 'service_end_on': '2026-09-02'},
    ])
    ota = OtaStore(tmp_path / 'synthetic-ota.sqlite')
    try:
        assert ota.import_portal(source)
        yield ota
    finally:
        ota.close()


def test_current_projection_matches_and_nothing_is_written_or_printed(store, capsys):
    before_file = store.path.read_bytes()
    before_state = commit_state(store.path)
    report = measure(str(store.path))
    # typing이 없으므로 고정 필수 키와 형태만 확인한다.
    assert REQUIRED_KEYS <= set(report)
    assert isinstance(report['match'], bool) and report['match'] is True
    assert report['stored_rows'] == report['reconstructed_rows'] == 2
    assert report['stored_ms'] >= 0 and report['reconstructed_ms'] >= 0
    assert store.path.read_bytes() == before_file
    assert commit_state(store.path) == before_state

    assert main(['--db', str(store.path), '--repeats', '2']) == 0
    out = capsys.readouterr().out
    assert REQUIRED_KEYS <= set(json.loads(out))
    # 출력에 합성 원문·경로·예외 본문이 없다.
    for sentinel in ('synthetic-first', 'synthetic-second', 'synthetic-portal', str(store.path), 'Traceback'):
        assert sentinel not in out


def test_tampered_projection_is_nonzero_mismatch(store, capsys):
    row = store.conn.execute(
        'SELECT row_no,payload_json FROM ota_catalog_rows ORDER BY row_no LIMIT 1').fetchone()
    payload = unpacked(row['payload_json'])
    payload['status'] = 'tampered'
    store.conn.execute('UPDATE ota_catalog_rows SET payload_json=? WHERE row_no=?',
                       (packed(payload), row['row_no']))
    store.conn.commit()

    report = measure(store.path)
    assert REQUIRED_KEYS <= set(report)
    assert report['match'] is False
    assert report['stored_rows'] == report['reconstructed_rows'] == 2

    assert main(['--db', str(store.path)]) == 2
    out = capsys.readouterr().out
    assert json.loads(out)['match'] is False
    for sentinel in ('synthetic-first', str(store.path), 'Traceback'):
        assert sentinel not in out


def test_empty_projection_is_not_a_pass(tmp_path, capsys):
    """비교할 행이 없는 양쪽 0행은 일치(exit 0)로 세지 않는다."""
    empty = OtaStore(tmp_path / 'synthetic-empty.sqlite')
    empty.close()
    assert main(['--db', str(empty.path)]) != 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert set(payload) == {'error'}
    assert payload['error'] and payload['error'] != str(empty.path)
    assert 'synthetic-empty' not in out and 'Traceback' not in out
