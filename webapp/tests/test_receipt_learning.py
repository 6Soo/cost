import importlib
import json
import sys
from unittest.mock import patch

import pytest

from app import receipt_vision as vision
from app import receipt_learning as rl
from webapp import receipt_review as rr
from webapp import receipt_vision_jobs as jobs

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
SHA = 'c' * 64
TRIP = 'trip-syn'
LESSON = '작은 승선권도 별개의 지출 증빙인지 확인할 것.'


@pytest.fixture
def learning_file(tmp_path, monkeypatch):
    path = tmp_path / 'receipt_learning.jsonl'
    monkeypatch.setenv('WEBLEDGER_RECEIPT_LEARNING', str(path))
    return path


@pytest.fixture
def muse_ready(tmp_path, monkeypatch):
    image = tmp_path / 'slip.png'
    image.write_bytes(PNG)
    monkeypatch.setenv('WEBLEDGER_CLAUDE_EXE', sys.executable)
    monkeypatch.setattr(vision, 'enabled', lambda: True)
    return str(image)


def reading(merchant, date, amount, payment='cash', currency='JPY'):
    return {'merchant': merchant, 'date': date, 'total': amount, 'currency': currency, 'payment': payment,
            'confidence': 1.0, 'box': None}


def done_job(receipts, lesson, job_id='f' * 32):
    return {'job_id': job_id, 'image': SHA, 'status': 'done',
            'result': {'receipts': receipts, 'lesson': lesson, 'label': 'Muse'}}


def test_without_a_learning_file_nothing_is_saved_and_muse_is_unaffected(monkeypatch):
    monkeypatch.delenv('WEBLEDGER_RECEIPT_LEARNING', raising=False)
    assert rl.notes_for_prompt() == [] and rl.guidance() is None
    assert rl.remember_lesson(LESSON)['status'] == 'disabled'


def test_a_lesson_must_stay_general(learning_file):
    assert rl.valid_lesson(LESSON)
    assert not rl.valid_lesson('820엔 승선권을 확인할 것')
    assert not rl.valid_lesson('2026-10-01 영수증은 날짜를 확인')
    assert not rl.valid_lesson('고객 연락처를 확인할 것')
    assert not rl.valid_lesson('test@example.com 을 확인할 것')
    assert not rl.valid_lesson('SHOP A 영수증은 따로 볼 것', names=['SHOP A'])
    assert not rl.valid_lesson('짧음')
    assert not rl.valid_lesson(None) and not rl.valid_lesson(['목록'])
    assert rl.remember_lesson('820엔 승선권을 확인할 것')['status'] == 'refused'
    assert not learning_file.exists()


def test_a_saved_lesson_is_kept_once(learning_file):
    assert rl.remember_lesson(LESSON)['status'] == 'saved'
    assert rl.remember_lesson(LESSON)['status'] == 'duplicate'
    assert [n['text'] for n in rl.list_notes()] == [LESSON]


def test_only_the_newest_three_distinct_lessons_are_used(learning_file):
    for text in (LESSON, '겹친 표는 따로 확인할 것.', '세금 줄은 총액이 아님을 확인할 것.', '한국어 상호를 그대로 적을 것.'):
        rl.remember_lesson(text)
    assert len(rl.list_notes()) == 4
    assert len(rl.notes_for_prompt()) == 3


def test_a_lesson_survives_a_restart(learning_file):
    rl.remember_lesson(LESSON)
    importlib.reload(rl)
    assert rl.notes_for_prompt() == [LESSON]


def test_records_written_before_this_change_are_still_read(learning_file):
    old = {'id': 'old1', 'key': 'k', 'created': '2026-10-13T00:00:00+00:00', 'text': '[업체]의 작은 승선권을 찾을 것'}
    learning_file.write_text(json.dumps(old, ensure_ascii=False) + '\n', encoding='utf-8')
    assert rl.notes_for_prompt() == ['[업체]의 작은 승선권을 찾을 것']


def test_the_next_muse_call_carries_the_lesson_and_the_photo_stays_the_source(learning_file, muse_ready):
    rl.remember_lesson(LESSON)
    commands = []

    def runner(command, *, cwd, env, timeout, input_bytes):
        commands.append(_prompt(input_bytes))
        return _event('{"receipts":[]}')
    vision.recognize(muse_ready, runner=runner, guidance=rl.guidance(notes=rl.notes_for_prompt()))
    prompt = commands[0]
    assert LESSON in prompt and prompt.startswith(vision.playbook_prompt())
    assert 'the attached photo is the source of truth' in prompt


def test_a_saved_lesson_can_be_deleted_and_damaged_lines_are_kept(learning_file):
    learning_file.write_text('not json\n', encoding='utf-8')
    rl.remember_lesson(LESSON)
    note_id = rl.list_notes()[0]['id']
    rl.delete_note(note_id)
    assert rl.list_notes() == [] and 'not json' in learning_file.read_text(encoding='utf-8')
    with pytest.raises(KeyError):
        rl.delete_note(note_id)


def test_a_damaged_file_gives_no_notes_and_never_blocks_muse(learning_file):
    learning_file.write_text('{broken', encoding='utf-8')
    assert rl.notes_for_prompt() == []


def test_the_recognition_contract_gains_an_optional_lesson_only_on_reanalysis(muse_ready):
    receipts = [{'merchant': 'SHOP', 'date': '2026-10-01', 'amount': 820, 'currency': 'JPY', 'payment': 'cash',
                 'category_hint': None, 'note': None}]
    commands = []

    def runner_with(payload):
        def runner(command, *, cwd, env, timeout, input_bytes):
            commands.append(_prompt(input_bytes))
            return _event(json.dumps(payload, ensure_ascii=False))
        return runner
    plain = vision.recognize(muse_ready, runner=runner_with({'receipts': receipts}))
    assert 'lesson' not in plain and commands[-1] == vision.playbook_prompt()
    lessoned = vision.recognize(muse_ready, runner=runner_with({'receipts': receipts, 'lesson': LESSON}), lesson=True)
    assert lessoned['lesson'] == LESSON and len(lessoned['receipts']) == 1
    assert vision.LESSON_INSTRUCTION in commands[-1]
    broken = vision.recognize(muse_ready, runner=runner_with({'receipts': receipts, 'lesson': ['not', 'text']}),
                              lesson=True)
    assert broken['lesson'] is None and len(broken['receipts']) == 1


def test_a_lesson_is_saved_only_when_a_new_receipt_is_registered(learning_file, tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    rr.scan(path, {'image': SHA, 'regions': [reading('SHOP A', '2026-10-01', 820)]})
    confirmed, = rr.load(path)['candidates']
    rr.edit(path, identity=confirmed['identity'], changes={'payee': 'SHOP A', 'category': '교통비'})
    six = [{'merchant': 'SHOP A', 'date': '2026-10-01', 'amount': 820, 'currency': 'JPY', 'payment': 'cash'},
           {'merchant': None, 'date': '2026-10-02', 'amount': 500, 'currency': 'JPY', 'payment': 'cash'}]
    with patch.object(jobs, 'lookup', return_value=done_job(six, LESSON)):
        assert rl.list_notes() == []
        found = rr.vision_new(path, image=SHA, job_id='f' * 32)
        assert len(found['new']) == 1
        new, = found['new']
        rr.scan(path, {'image': SHA, 'regions': [{**reading('', '2026-10-02', 500), 'merchant': None,
                                                   'ordinal': new['ordinal'], 'reading': new['reading']}]})
        assert rr.learn_from_job(path, image=SHA, job_id='f' * 32)['status'] == 'saved'
        assert rr.learn_from_job(path, image=SHA, job_id='f' * 32)['status'] == 'duplicate'
    assert [n['text'] for n in rl.list_notes()] == [LESSON]
    after = {c['identity']: c for c in rr.load(path)['candidates']}
    assert after[confirmed['identity']]['payee'] == 'SHOP A'
    assert after[confirmed['identity']]['category'] == '교통비'
    assert after[confirmed['identity']]['total_jpy'] == 820


def test_a_lesson_naming_a_photo_merchant_or_a_missing_lesson_saves_nothing(learning_file, tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    named = [{'merchant': 'SHOP A', 'date': '2026-10-01', 'amount': 820, 'currency': 'JPY', 'payment': 'cash'}]
    with patch.object(jobs, 'lookup', return_value=done_job(named, 'SHOP A 영수증을 따로 볼 것.')):
        assert rr.learn_from_job(path, image=SHA, job_id='f' * 32)['status'] == 'refused'
    with patch.object(jobs, 'lookup', return_value=done_job(named, None)):
        assert rr.learn_from_job(path, image=SHA, job_id='f' * 32)['status'] == 'no_lesson'
    with patch.object(jobs, 'lookup', return_value=None):
        assert rr.learn_from_job(path, image=SHA, job_id='f' * 32)['status'] == 'no_lesson'
    assert not learning_file.exists()


def test_registration_leaves_the_ledger_export_unchanged(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    rr.scan(path, {'image': SHA, 'regions': [reading('SHOP A', '2026-10-01', 820)]})
    before = rr.tsv(path, TRIP)
    done = done_job([{'merchant': 'NEW STOP', 'date': '2026-10-05', 'amount': 700, 'currency': 'JPY',
                      'payment': 'cash'}], LESSON)
    with patch.object(jobs, 'lookup', return_value=done):
        new, = rr.vision_new(path, image=SHA, job_id='f' * 32)['new']
    rr.scan(path, {'image': SHA, 'regions': [{**reading('NEW STOP', '2026-10-05', 700), 'ordinal': new['ordinal'],
                                              'reading': new['reading']}]})
    after = rr.tsv(path, TRIP)
    assert after['tsv'] == before['tsv'] and after['row_count'] == before['row_count']


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


def test_a_recognised_receipt_takes_its_merchant_as_payee_and_needs_an_item_only_when_none_is_suggested(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    rr.scan(path, {'image': SHA, 'regions': [reading('SHOP', '2026-10-01', 820)]})
    candidate, = rr.load(path)['candidates']
    assert candidate['payee'] == 'SHOP' and candidate['category'] is None
    assert candidate['hold'] is None


def test_the_learning_routes_are_owner_routes(monkeypatch):
    for route in ('/api/receipts/learn', '/api/receipts/learn/delete', '/api/receipts/vision/rescan',
                  '/api/receipts/vision/new'):
        assert rr.owns_route(route)


def _event(text):
    lines = [{'type': 'system', 'subtype': 'init', 'tools': ['StructuredOutput'], 'mcp_servers': []},
             {'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': json.loads(text)}]
    return type('Proc', (), {'returncode': 0, 'stderr': b'',
                             'stdout': '\n'.join(json.dumps(line, ensure_ascii=False) for line in lines).encode('utf-8')})()


def _prompt(input_bytes):
    return json.loads(input_bytes)['message']['content'][1]['text']


def test_repeat_analysis_with_shifted_box_does_not_duplicate_existing_receipt(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    first = {**reading('SHOP A', '2026-10-01', 820), 'box': [0.1, 0.1, 0.4, 0.4]}
    second = {**first, 'box': [0.11, 0.1, 0.41, 0.4]}
    assert rr.scan(path, {'image': SHA, 'regions': [first]})['added'] == 1
    assert rr.scan(path, {'image': SHA, 'regions': [second]})['added'] == 0
    assert len(rr.load(path)['candidates']) == 1


def test_boxed_analysis_does_not_duplicate_legacy_unboxed_receipt(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    original = reading('SHOP A', '2026-10-01', 820)
    assert rr.scan(path, {'image': SHA, 'regions': [original]})['added'] == 1
    result = rr.scan(path, {'image': SHA, 'regions': [{**original, 'box': [0.1, 0.1, 0.4, 0.4]}]})
    assert result['added'] == 0
    assert len(rr.load(path)['candidates']) == 1


def test_rescan_matches_existing_box_before_identical_new_ticket(tmp_path):
    path = tmp_path / 'receipts.json'
    rr._save(path, {'images': [SHA], 'candidates': [], 'holds': []})
    original = {**reading('FERRY', '2026-10-01', 820), 'box': [0.1, 0.1, 0.4, 0.4]}
    assert rr.scan(path, {'image': SHA, 'regions': [original]})['added'] == 1
    base = {'merchant': 'FERRY', 'date': '2026-10-01', 'amount': 820, 'currency': 'JPY', 'payment': 'cash'}
    new_box = [0.6, 0.1, 0.9, 0.4]
    job = done_job([{**base, 'box': new_box}, {**base, 'box': original['box']}], None)
    with patch.object(jobs, 'lookup', return_value=job):
        result = rr.vision_new(path, image=SHA, job_id='f' * 32)
    assert result['already'] == 1
    assert [item['box'] for item in result['new']] == [new_box]
