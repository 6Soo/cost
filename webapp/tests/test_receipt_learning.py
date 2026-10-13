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
    assert rl.notes_for_prompt() == [] and rl.guidance() is None
    assert rl.remember('작은 승선권 찾아', names=[]) == {'status': 'disabled'}
    image = tmp_path / 'slip.png'
    image.write_bytes(PNG)
    seen = []

    def runner(command, *, cwd, env):
        seen.append(command)
        return _event('{"receipts":[]}')
    assert vision.recognize(str(image), runner=runner)['receipts'] == []
    assert seen[0][-1] == vision.PROMPT


def test_feedback_is_generalised_so_one_slip_cannot_leak_its_values(learning_file):
    rl.remember('SHOP A 의 820엔 승선권이 빠졌어 test@example.com 2026-10-01', names=['SHOP A'])
    note, = rl.list_notes()
    assert 'SHOP A' not in note['text'] and '820' not in note['text']
    assert '2026' not in note['text'] and 'test@example.com' not in note['text']
    assert '[업체]' in note['text'] and '[숫자]' in note['text']


def test_a_note_is_kept_once_and_only_the_newest_three_distinct_notes_are_used(learning_file):
    assert rl.remember('작은 승선권을 찾아 주세요', names=[])['status'] == 'saved'
    assert rl.remember('작은 승선권을 찾아 주세요', names=[])['status'] == 'duplicate'
    for text in ('겹친 표를 따로 보세요', '세금 줄은 총액이 아닙니다', '한국어 상호를 그대로 적으세요'):
        rl.remember(text, names=[])
    assert len(rl.list_notes()) == 4
    assert len(rl.notes_for_prompt()) == 3


def test_notes_survive_a_restart(learning_file):
    rl.remember('작은 승선권을 찾아 주세요', names=[])
    importlib.reload(rl)
    assert rl.notes_for_prompt() == ['작은 승선권을 찾아 주세요']


def test_the_next_muse_call_carries_the_note_as_guidance_only(learning_file, tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_RECEIPT_VISION', 'opencode-muse-free')
    rl.remember('작은 승선권을 찾아 주세요', names=[])
    image = tmp_path / 'slip.png'
    image.write_bytes(PNG)
    commands = []

    def runner(command, *, cwd, env):
        commands.append(command)
        return _event('{"receipts":[]}')
    vision.recognize(str(image), runner=runner, guidance=rl.guidance(notes=rl.notes_for_prompt()))
    prompt = commands[0][-1]
    assert '작은 승선권을 찾아 주세요' in prompt and prompt.startswith(vision.PROMPT)
    assert 'the attached photo is the source of truth' in prompt
    assert '--pure' in commands[0] and not any('permission' in arg for arg in commands[0])


def test_a_saved_note_can_be_deleted_and_damaged_lines_are_kept(learning_file):
    learning_file.write_text('not json\n', encoding='utf-8')
    rl.remember('겹친 표를 따로 보세요', names=[])
    note_id = rl.list_notes()[0]['id']
    assert rl.notes_for_prompt() == ['겹친 표를 따로 보세요']
    rl.delete_note(note_id)
    assert rl.list_notes() == [] and 'not json' in learning_file.read_text(encoding='utf-8')
    with pytest.raises(KeyError):
        rl.delete_note(note_id)


def test_a_damaged_file_gives_no_notes_and_never_blocks_muse(learning_file):
    learning_file.write_text('{broken', encoding='utf-8')
    assert rl.notes_for_prompt() == []


def test_the_feedback_reaches_the_rescan_prompt_with_the_known_receipts(learning_file):
    text = rl.guidance(known=['SHOP A | 2026-10-01 | 820 JPY'], feedback='작은 승선권 하나 더 찾아')
    assert 'Already found' in text and 'SHOP A | 2026-10-01 | 820 JPY' in text
    assert 'Owner feedback for this photo: 작은 승선권 하나 더 찾아' in text


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
    for route in ('/api/receipts/learn', '/api/receipts/learn/delete', '/api/receipts/vision/rescan',
                  '/api/receipts/vision/new'):
        assert rr.owns_route(route)


def _event(text):
    return type('Proc', (), {'returncode': 0, 'stderr': b'', 'stdout': (json.dumps({
        'type': 'text', 'part': {'type': 'text', 'text': text}}, ensure_ascii=False) + '\n').encode('utf-8')})()
