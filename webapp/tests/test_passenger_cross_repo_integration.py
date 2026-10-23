import json
import os
import sqlite3
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app import reservation_authority
from webapp import flight_passenger_page as page


@pytest.fixture(scope='module')
def reservation_api():
    root = Path(os.environ.get('COST_R5B_RESERVATION_ROOT', '')).resolve()
    fixture = root / 'tests' / 'fixtures' / 'passengerCandidatesHttpFixture.ts'
    tsx = root / 'node_modules' / 'tsx' / 'dist' / 'cli.mjs'
    if not fixture.is_file() or not tsx.is_file():
        pytest.skip('Set COST_R5B_RESERVATION_ROOT to the isolated reservation checkout with dependencies installed.')
    token = 'synthetic-r5b-internal-token-only'
    env = dict(os.environ, INTERNAL_API_TOKEN=token)
    process = subprocess.Popen(['node', str(tsx), str(fixture)], cwd=root, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert process.stdout is not None
        ready = json.loads(process.stdout.readline())
        assert ready['tour_id'] == 'tour-synthetic-r5b'
        yield f"http://127.0.0.1:{ready['port']}", token, ready['tour_id']
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_real_reservation_route_http_adapter_cost_confirmation_and_stale_reconfirm(tmp_path, reservation_api):
    base_url, token, tour_id = reservation_api
    db_path = tmp_path / 'passenger-assignments.sqlite'
    evidence = {'booking_ref': 'SYNTH-R5B-500', 'source_digests': ['synthetic-flight-source-sha'],
                'passengers': [{'surname': 'KIM', 'given_name': 'SYNTHETIC PASSENGER'}]}
    env = {page.FEATURE_FLAG: '1', page.DB_ENV: str(db_path),
           reservation_authority.BASE_URL_ENV: base_url, reservation_authority.TOKEN_ENV: token}
    with patch.dict(os.environ, env), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={evidence['booking_ref']: evidence}):
        class CostHandler(BaseHTTPRequestHandler):
            def _send(self, body, status=200):
                if isinstance(body, str):
                    encoded, content_type = body.encode('utf-8'), 'text/html; charset=utf-8'
                else:
                    encoded, content_type = json.dumps(body, ensure_ascii=False).encode('utf-8'), 'application/json'
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _send_json(self, body, status=200):
                self._send(body, status)

            def do_GET(self):
                parsed = urlsplit(self.path)
                handled = page.dispatch(
                    self, parsed, is_owner=True, board=object(), csrf='csrf-synth',
                    query=parse_qs(parsed.query), candidate_fetch=reservation_authority.fetch_passenger_candidates)
                if not handled:
                    self._send_json({'code': 'NOT_FOUND'}, 404)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                handled = page.dispatch(
                    self, urlsplit(self.path), raw=raw, is_owner=True, board=object(), csrf='csrf-synth',
                    candidate_fetch=reservation_authority.fetch_passenger_candidates)
                if not handled:
                    self._send_json({'code': 'NOT_FOUND'}, 404)

            def log_message(self, *_args):
                pass

        cost_server = ThreadingHTTPServer(('127.0.0.1', 0), CostHandler)
        server_thread = threading.Thread(target=cost_server.serve_forever, daemon=True)
        server_thread.start()
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as api:
                browser = api.chromium.launch(headless=True)
                try:
                    browser_page = browser.new_page()
                    browser_page.goto(f'http://127.0.0.1:{cost_server.server_address[1]}/flight-passengers')
                    browser_page.locator('input[name=booking_ref]').fill(evidence['booking_ref'])
                    browser_page.locator('input[name=tour_id]').fill(tour_id)
                    browser_page.get_by_role('button', name='후보 조회').click()
                    browser_page.get_by_text('김합성참가자').wait_for()
                    browser_page.locator('input[type=radio]').check()
                    browser_page.get_by_role('button', name='선택한 COST 연결 저장').click()
                    browser_page.get_by_text('실제 탑승 여부는 확인되지 않았습니다.').wait_for()

                    browser_page.reload()
                    browser_page.locator('input[name=booking_ref]').fill(evidence['booking_ref'])
                    browser_page.locator('input[name=tour_id]').fill(tour_id)
                    browser_page.get_by_role('button', name='후보 조회').click()
                    browser_page.get_by_text('사용자가 확인했습니다.').wait_for()

                    request = urllib.request.Request(base_url + '/__test/source', data=json.dumps(
                        {'name': '김합성참가자변경'}).encode(),
                        headers={'Content-Type': 'application/json'}, method='POST')
                    with urllib.request.urlopen(request, timeout=3) as response:
                        assert response.status == 204
                    browser_page.get_by_role('button', name='후보 조회').click()
                    browser_page.get_by_text(
                        '예약 참가자 자료가 바뀌어 다시 확인해야 합니다.').wait_for()
                    browser_page.get_by_text('김합성참가자변경').wait_for()
                    browser_page.locator('input[type=radio]').check()
                    browser_page.get_by_role('button', name='선택한 COST 연결 저장').click()
                    browser_page.get_by_text('실제 탑승 여부는 확인되지 않았습니다.').wait_for()
                    browser_page.get_by_role('button', name='후보 조회').click()
                    browser_page.get_by_text('저장된 COST 연결: 김합성참가자변경 · 사용자가 확인했습니다.').wait_for()
                    assert browser_page.get_by_text(
                        '예약 참가자 자료가 바뀌어 다시 확인해야 합니다.').count() == 0
                finally:
                    browser.close()
        finally:
            cost_server.shutdown()
            cost_server.server_close()
            server_thread.join(timeout=5)

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute('SELECT source_revision, assignment_json FROM flight_passenger_assignments').fetchall()
        assert len(rows) == 2
        assert 'private-row-id-fixture' not in json.dumps(rows)
        assert all('0000000000000' not in row[1] for row in rows)
    finally:
        connection.close()
