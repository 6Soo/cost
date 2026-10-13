import importlib
import json
from unittest.mock import patch

import pytest

from app import opencode_receipt_vision as vision
from app import receipt_learning as rl
from webapp import receipt_review as rr
from webapp import receipt_vision_jobs as jobs

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
SHA = 'c' * 64


@pytest.fixture
def learning_file(tmp_path, monkeypatch):
    path = tmp_path / 'receipt_learning.jsonl'
    monkeypatch.setenv('WEBLEDGER_RECEIPT_LEARNING', str(path))
    return path


def reading(merchant, date, amount, payment='cash', currency='JPY'):
    return {'merchant': merchant, 'date': date, 'total': amount, 'currency': currency, 'payment': payment,
            'confidence': 1.0, 'box': None}


def test_without_a_learning_file_muse_runs_exactly_as_before(monkeypatch, tmp_path):
    monkeypatch.delenv('WEBLEDGER_RECEIPT_LEARNING', raising=False)
    monkeypatch.setenv('WEBLEDGER_RECEIPT_VISION', 'opencode-muse-free')
    assert rl.rules_for_prompt() == [] and rl.guidance(rules=[]) is None
    image = tmp_path / 'slip.png'
    image.write_bytes(PNG)
    seen = []

    def runner(command, *, cwd, env):
        seen.append(command)
        return _event('{"receipts":[]}')
    result = vision.recognize(str(image), runner=runner)
    assert result['receipts'] == []
    assert seen[0][-1] == vision.PROMPT


def test_a_confirmed_general_note_becomes_one_rule_and_repeats_are_not_stored_twice(learning_file):
    first = rl.add_feedback(note_type='SMALL_TICKET_MISSED', scope='general', note='작은 승선권이 빠졌음')
    assert first['status'] == 'active'
    assert rl.add_feedback(note_type='SMALL_TICKET_MISSED', scope='general', note='작은 승선권이 빠졌음') == {'status': 'duplicate'}
    assert rl.add_feedback(note_type='SMALL_TICKET_MISSED', scope='general', note='다른 메모')['status'] == 'merged'
    assert [r['status'] for r in rl.list_records()] == ['active', 'merged']
    assert len(rl.rules_for_prompt()) == 1


def test_a_single_photo_note_and_free_text_never_become_rules_and_numbers_are_removed(learning_file):
    rl.add_feedback(note_type='IDENTICAL_MERGED', scope='this_photo', note='820엔 2026-10-01 test@example.com')
    rl.add_feedback(note_type='OTHER', scope='general', note='메모만')
    records = rl.list_records()
    assert all(r['rule'] is None and r['status'] == 'recorded' for r in records)
    assert rl.rules_for_prompt() == []
    note = records[0]['note']
    assert '820' not in note and '2026' not in note and 'test@example.com' not in note


def test_rules_survive_a_restart(learning_file):
    rl.add_feedback(note_type='KOREAN_MERCHANT_MISSED', scope='general', note='')
    importlib.reload(rl)
    assert rl.rules_for_prompt() == [rl.RULES['KOREAN_MERCHANT_MISSED']]


def test_the_next_muse_call_carries_the_active_rule_but_the_photo_stays_the_source(learning_file, tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_RECEIPT_VISION', 'opencode-muse-free')
    rl.add_feedback(note_type='SMALL_TICKET_MISSED', scope='general', note='')
    image = tmp_path / 'slip.png'
    image.write_bytes(PNG)
    commands = []

    def runner(command, *, cwd, env):
        commands.append(command)
        return _event('{"receipts":[]}')
    guidance = rl.guidance(rules=rl.rules_for_prompt(record_use=True))
    vision.recognize(str(image), runner=runner, guidance=guidance)
    prompt = commands[0][-1]
    assert rl.RULES['SMALL_TICKET_MISSED'] in prompt and prompt.startswith(vision.PROMPT)
    assert 'the attached photo is the source of truth' in prompt
    assert rl.list_records()[0]['applied'] == 1


def test_a_disabled_rule_is_not_sent_and_can_be_enabled_again(learning_file):
    rl.add_feedback(note_type='TOTAL_CONFUSED', scope='general', note='')
    rule_id = rl.list_records()[0]['id']
    rl.set_status(rule_id, 'disable')
    assert rl.rules_for_prompt() == []
    rl.set_status(rule_id, 'enable')
    assert rl.rules_for_prompt() == [rl.RULES['TOTAL_CONFUSED']]
    rl.set_status(rule_id, 'delete')
    assert rl.list_records() == []


def test_unreadable_lines_do_not_stop_rules_and_are_kept_on_write(learning_file):
    learning_file.write_text('not json\n', encoding='utf-8')
    rl.add_feedback(note_type='OVERLAPPING_SLIPS', scope='general', note='')
    assert rl.rules_for_prompt() == [rl.RULES['OVERLAPPING_SLIPS']]
    assert 'not json' in learning_file.read_text(encoding='utf-8')
    learning_file.write_text('{broken', encoding='utf-8')
    assert rl.rules_for_prompt() == []


def test_a_known_receipt_is_never_offered_again_and_a_new_one_is_offered_once(learning_file, tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    five = [reading('SHOP A', '2026-10-01', 820), reading('FERRY', '2026-10-01', 820),
            reading('CAFE', '2026-10-02', 1200, currency='JPY'), reading('MART', '2026-10-03', 500),
            reading('BUS', '2026-10-04', 300)]
    rr.scan(path, {'image': SHA, 'regions': five})
    before = {c['identity']: dict(c) for c in rr.load(path)['candidates']}
    assert len(before) == 5
    six = [{'merchant': r['merchant'], 'date': r['date'], 'amount': r['total'], 'currency': r['currency'],
            'payment': r['payment']} for r in five] + [
        {'merchant': 'NEW STOP', 'date': '2026-10-05', 'amount': 700, 'currency': 'JPY', 'payment': 'cash'}]
    done = {'job_id': 'f' * 32, 'image': SHA, 'status': 'done', 'result': {'receipts': six}}
    with patch.object(jobs, 'lookup', return_value=done):
        found = rr.vision_new(path, image=SHA, job_id='f' * 32)
    assert found['already'] == 5 and [n['merchant'] for n in found['new']] == ['NEW STOP']
    new, = found['new']
    result = rr.scan(path, {'image': SHA, 'regions': [{**reading(new['merchant'], new['date'], new['amount']),
                                                       'ordinal': new['ordinal'], 'reading': new['reading']}]})
    assert result['added'] == 1
    after = {c['identity']: c for c in rr.load(path)['candidates']}
    assert set(before) <= set(after)
    for identity, original in before.items():
        assert after[identity]['merchant'] == original['merchant'] and after[identity]['total_jpy'] == original['total_jpy']
    with patch.object(jobs, 'lookup', return_value=done):
        assert rr.vision_new(path, image=SHA, job_id='f' * 32)['new'] == []


def test_identical_tickets_are_separate_and_only_the_missing_copy_is_offered(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    rr.scan(path, {'image': SHA, 'regions': [reading('FERRY', '2026-10-01', 820)]})
    twins = [{'merchant': 'FERRY', 'date': '2026-10-01', 'amount': 820, 'currency': 'JPY', 'payment': 'cash'}] * 2
    done = {'job_id': 'e' * 32, 'image': SHA, 'status': 'done', 'result': {'receipts': twins}}
    with patch.object(jobs, 'lookup', return_value=done):
        found = rr.vision_new(path, image=SHA, job_id='e' * 32)
    assert found['already'] == 1 and [n['ordinal'] for n in found['new']] == [1]
    new, = found['new']
    assert rr.scan(path, {'image': SHA, 'regions': [{**reading('FERRY', '2026-10-01', 820),
                                                     'ordinal': 1, 'reading': new['reading']}]})['added'] == 1
    assert len(rr.load(path)['candidates']) == 2


def test_new_candidates_stay_unconfirmed_until_a_person_confirms(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    rr.scan(path, {'image': SHA, 'regions': [reading('SHOP', '2026-10-01', 820)]})
    assert all('payee' not in c or c.get('payee') is None for c in rr.load(path)['candidates'])
    assert all(c.get('category') is None for c in rr.load(path)['candidates'])


def test_the_learning_routes_are_owner_routes(monkeypatch):
    for route in ('/api/receipts/learn', '/api/receipts/learn/status', '/api/receipts/vision/rescan',
                  '/api/receipts/vision/new'):
        assert rr.owns_route(route)


def _event(text):
    return type('Proc', (), {'returncode': 0, 'stderr': b'', 'stdout': (json.dumps({
        'type': 'text', 'part': {'type': 'text', 'text': text}}, ensure_ascii=False) + '\n').encode('utf-8')})()
