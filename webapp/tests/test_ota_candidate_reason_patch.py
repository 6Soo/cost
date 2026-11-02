"""Candidate reasons use production code without exposing unverified identities."""
import json
import re
import shutil
import subprocess

from webapp.card_flow import page


def test_candidate_reason_only_returns_reason_without_booking_or_period():
    source = page('synthetic-csrf')
    helper = re.search(r"const otaCandidateReason=(note=>\{.*?\});", source).group(1)
    node = shutil.which('node')
    assert node, 'Node is required for the production renderer regression'
    harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const reason = vm.runInNewContext('('+HELPER+')');
assert.equal(reason('OTA 후보(미확정): SYNTHETIC-BOOKING-ID · HOLD_DATE_UNKNOWN · 금액 근거가 달라 결제 검증 필요'),
             '금액 근거가 달라 결제 검증 필요');
for (const note of ['SYNTHETIC-BOOKING-ID', '예약 추론 연결 · 결제는 검증되지 않았습니다. · SYNTHETIC-BOOKING-ID · 숙박 2026-10-01~2026-10-03']) {
  assert.ok(!reason(note).includes('SYNTHETIC-BOOKING-ID'));
  assert.ok(!reason(note).includes('2026-10'));
}
'''.replace('HELPER', json.dumps(helper))
    result = subprocess.run([node, '-e', harness], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
