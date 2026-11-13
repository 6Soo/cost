"""Synthetic-only tests: case aggregation hides identifiers; re-evaluation compares every corrected field."""
import json
import sqlite3

import pytest

from app import ai_review_repair as repair
from tests.test_ai_review_repair import add_projection, correction_for, make_manifest, prepare
from tools.quarter_review import eval_cases
from webapp.tests.test_automatic_classification_completion import setup, TRIPS  # noqa: F401

REVIEW_ID = 'ai-quarter-review-2026Q3'
NAME = '홍길동'  # a synthetic Korean customer name inside reviewer free text
CODED = 'TRIP-044 · 예약 이용기간 근거 없음 · 결제일 분기 기타비용 · ' + NAME + ' 고객 숙박'
PLAIN = 'TRIP-029 · ' + NAME + ' 고객 건 사유'


def corrected(setup, *, row2_item='식비'):
    """Five AI-review corrections whose re-judgment outcomes differ.

    0: 09-30 -> quarter bucket; code picks the quarter and item  -> MATCH
    1: 09-30 -> trip B; code says quarter                        -> attribution + item mismatch
    2: 10-03 B -> A, item unchanged ('식비'); attribution agrees,
       item is not what the code derives                         -> ITEM_DIFFERS only (attribution-only fix)
    3: 10-03 item-only fix whose old source was an import rule   -> item not re-evaluated, never MATCH
    4: 10-03 A -> B; code keeps A                                -> trip + item mismatch
    """
    board, batch, rows = setup[0], setup[2], setup[3]
    c = board.conn
    prepare(c)
    ids = [r['transaction_id'] for r in rows]
    c.execute("UPDATE transactions SET approval_date='2026-10-03' WHERE transaction_id IN (?,?,?)", ids[2:])
    c.execute("UPDATE transactions SET trip_id='B',display_tab_id='B' WHERE transaction_id=?", (ids[2],))
    c.execute("UPDATE transactions SET classification_source='rule' WHERE transaction_id=?", (ids[3],))
    c.commit()
    plan = [(0, 'quarter:2026:3', '식비', CODED), (1, 'B', '식비', CODED), (2, 'A', row2_item, CODED),
            (3, 'A', '교통비', PLAIN), (4, 'B', '식비', PLAIN)]
    for i, *_ in plan:
        add_projection(c, ids[i], batch)
    manifest = make_manifest([correction_for(c, ids[i], tab, item=item, basis=basis)
                              for i, tab, item, basis in plan])
    preview = repair.preview(c, TRIPS, manifest)
    assert preview['summary']['to_apply'] == 5, preview['summary']
    repair.apply(c, preview, TRIPS, manifest, request_id=REVIEW_ID)
    return c, ids


def public_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from public_strings(k)
            yield from public_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from public_strings(v)


def test_case_file_has_types_and_counts_but_no_identifiers(setup):
    c, ids = corrected(setup)
    cases = eval_cases.collect_cases(c, REVIEW_ID)
    assert len(cases) == 5
    payload = eval_cases.build_case_file(cases, REVIEW_ID)
    text = json.dumps(payload, ensure_ascii=False)
    forbidden = list(ids)
    for row in c.execute('SELECT source_hash,merchant,amount_krw,approval_number,approval_date,card_tail FROM transactions'):
        forbidden += [str(v) for v in row if v not in (None, '') and len(str(v)) >= 4]
    assert any(v.startswith('SYNTHETIC') for v in forbidden)
    for value in forbidden:
        assert value not in text, value
    assert NAME not in text and '고객' not in text
    assert payload['total'] == 5 and sum(t['count'] for t in payload['types']) == 5
    assert payload['by_rule']['TRIP-044'] == 3
    codes = {code for t in payload['types'] for code in t['reason']}
    assert {'NO_BOOKING_PERIOD_EVIDENCE', 'QUARTER_OTHER_COST', eval_cases.INDIVIDUAL_REASON} <= codes
    assert {t['attribution'] for t in payload['types']} == {'trip→quarter', 'trip→trip', 'unchanged'}
    assert all(set(t) == {'rules', 'reason', 'before_source', 'item', 'attribution', 'count'}
               for t in payload['types'])
    eval_cases.validate_public(payload['types'])


def test_reviewer_free_text_never_reaches_the_file_even_when_repeated(setup):
    """Same Korean name in many reasons (and in item/source fields) must not survive aggregation."""
    c, ids = corrected(setup)
    c.execute("UPDATE change_log SET detail_json=replace(detail_json,'교통비',?) WHERE kind='card.ai_review_corrected'",
              (NAME + '상회',))
    c.execute("UPDATE change_log SET detail_json=replace(detail_json,'\"classification_source\": \"rule\"',"
              "'\"classification_source\": \"" + NAME + "\"')")
    payload = eval_cases.build_case_file(eval_cases.collect_cases(c, REVIEW_ID), REVIEW_ID)
    assert NAME not in json.dumps(payload, ensure_ascii=False)
    assert '기타(목록 밖)' in json.dumps(payload, ensure_ascii=False)
    # every published string value is drawn from a fixed vocabulary
    allowed = (eval_cases.REASON_VOCABULARY | eval_cases.SOURCE_VOCABULARY | {'other', 'unchanged'}
               | eval_cases.ITEM_VOCABULARY | {'기타(목록 밖)'} | eval_cases.ATTRIBUTION_VOCABULARY)
    for t in payload['types']:
        for field in ('reason', 'rules'):
            for v in t[field]:
                assert v in allowed or eval_cases.RULE_VOCABULARY.fullmatch(v)
        for v in (t['before_source'], *t['item'].split('→'), *t['attribution'].split('→')):
            assert v in allowed, v


def test_validate_public_rejects_values_outside_the_allow_list():
    good = dict(rules=['TRIP-044'], reason=['QUARTER_OTHER_COST'], before_source='inference',
                item='unchanged', attribution='trip→quarter', count=1)
    eval_cases.validate_public([good])
    for bad in (dict(good, reason=['자유 문장']), dict(good, rules=[NAME]), dict(good, before_source=NAME),
                dict(good, item='식비→' + NAME), dict(good, attribution='trip→' + NAME)):
        with pytest.raises(ValueError, match='PUBLIC_VALUE_NOT_ALLOWED'):
            eval_cases.validate_public([bad])


def test_invalid_review_id_is_rejected(setup):
    c, _ = corrected(setup)
    with pytest.raises(ValueError, match='REVIEW_ID_INVALID'):
        eval_cases.build_case_file(eval_cases.collect_cases(c, REVIEW_ID), NAME)


def test_reevaluation_compares_every_field_and_is_read_only(setup):
    c, ids = corrected(setup)
    dump = list(c.iterdump())
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    assert list(c.iterdump()) == dump  # nothing written, projections untouched
    assert report['cases'] == 5
    assert (report['matched'], report['mismatched'], report['item_not_reevaluated'],
            report['not_rejudged']) == (1, 3, 1, 0)
    assert report['matched'] + report['mismatched'] + report['item_not_reevaluated'] \
        + report['not_rejudged'] == report['cases']
    assert report['by_reason'] == {'ATTRIBUTION_QUARTER_VS_TRIP': 1, 'ATTRIBUTION_TRIP_DIFFERS': 1,
                                   'ITEM_DIFFERS': 3}
    assert report['item_not_reevaluated_by_reason'] == {'ITEM_FROM_IMPORT_RULE_NOT_REEVALUATED': 1}
    text = json.dumps(report, ensure_ascii=False)
    assert not any(i in text for i in ids) and NAME not in text


def test_attribution_only_correction_with_wrong_item_is_not_a_match(setup):
    """Regression (review of fde62f05): before/after item equal, attribution right, judged item wrong."""
    c, ids = corrected(setup)
    cases = {x['tid']: x for x in eval_cases.collect_cases(c, REVIEW_ID)}
    case = cases[ids[2]]
    assert case['before']['transaction']['item'] == case['after']['transaction']['item'] == '식비'
    result = eval_cases.rejudge(c, TRIPS, [case])[0]
    assert result['outcome'] == 'MISMATCH' and result['reasons'] == ['ITEM_DIFFERS']


def test_import_rule_item_is_not_inherited_from_the_correction(setup):
    """Regression (review of fde62f05): an item whose old source was an import rule must not
    be fed back as the answer and counted as MATCH."""
    c, ids = corrected(setup)
    case = next(x for x in eval_cases.collect_cases(c, REVIEW_ID) if x['tid'] == ids[3])
    assert case['before']['transaction']['classification_source'] == 'rule'
    assert case['after']['transaction']['item'] == '교통비'
    result = eval_cases.rejudge(c, TRIPS, [case])[0]
    assert result['outcome'] == 'ITEM_NOT_REEVALUATED'
    # and the corrected value really never reaches the P1 input: a correction that happens to
    # equal the derived item ('기타경비') is a genuine MATCH only because it was derived afresh
    c2 = c.execute("SELECT detail_json FROM change_log WHERE subject=? AND kind=?",
                   (ids[3], eval_cases.KIND)).fetchone()[0]
    detail = json.loads(c2)
    detail['after']['transaction']['item'] = '기타경비'
    case['after'] = detail['after']
    assert eval_cases.rejudge(c, TRIPS, [case])[0]['outcome'] == 'MATCH'


def test_reevaluation_reports_zero_when_every_correction_agrees(setup):
    c, ids = corrected(setup, row2_item='기타경비')
    # drop the corrections the code does not reproduce: only agreeing ones remain
    c.execute("DELETE FROM change_log WHERE kind='card.ai_review_corrected' AND subject IN (?,?,?)",
              (ids[1], ids[3], ids[4]))
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    assert (report['cases'], report['matched'], report['mismatched'], report['by_reason'],
            report['item_not_reevaluated'], report['not_rejudged']) == (2, 2, 0, {}, 0, 0)


def test_restored_corrections_are_not_cases(setup):
    c, ids = corrected(setup)
    entry = c.execute("SELECT entry_id FROM change_log WHERE kind='card.ai_review_corrected' AND subject=?",
                      (ids[0],)).fetchone()[0]
    c.execute("INSERT INTO change_log(at,kind,subject,detail_json) VALUES ('x',?,?,?)",
              (eval_cases.RESTORE_KIND, ids[0], json.dumps(dict(release_entry_id=entry))))
    assert len(eval_cases.collect_cases(c, REVIEW_ID)) == 4


def test_rows_protected_after_the_review_are_reported_separately_not_as_mismatches(setup):
    c, ids = corrected(setup)
    # e.g. a later duplicate cleanup marks a corrected row; P1 must not judge it
    c.execute("UPDATE transactions SET duplicate_of='synthetic-original' WHERE transaction_id=?", (ids[1],))
    c.commit()
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    assert report['not_rejudged'] == 1
    assert report['not_rejudged_by_reason'] == {'NOT_REJUDGED_SOURCE_PROTECTED': 1}
    assert report['mismatched'] == 2 and 'ATTRIBUTION_QUARTER_VS_TRIP' not in report['by_reason']
    assert report['matched'] + report['mismatched'] + report['item_not_reevaluated'] \
        + report['not_rejudged'] == report['cases']


def host_with_copy(setup, tmp_path):
    host = tmp_path / 'host'
    (host / 'data').mkdir(parents=True)
    target = sqlite3.connect(host / 'data/board.sqlite')
    setup[0].conn.backup(target)
    target.close()
    return host


def test_commands_write_only_private_case_file_and_open_database_read_only(setup, tmp_path, monkeypatch, capsys):
    c, ids = corrected(setup)
    c.commit()
    host = host_with_copy(setup, tmp_path)
    db = host / 'data/board.sqlite'
    before = db.read_bytes()
    assert eval_cases.main(['build', '--host-root', str(host)]) == 0
    case_file = host / eval_cases.CASES_SUBPATH / ('cases-' + REVIEW_ID + '.json')
    assert case_file.is_file() and not any(i in case_file.read_text(encoding='utf-8') for i in ids)
    assert NAME not in case_file.read_text(encoding='utf-8')
    import tools.complete_card_classification as legacy
    seen = {}

    def fake_evidence(conn, host_root, trips, cache=None):
        seen['cache'] = cache
        return {}, {}
    monkeypatch.setattr(legacy, 'load_context', lambda conn, host_root: (TRIPS, {}))
    monkeypatch.setattr(legacy, 'load_review_evidence', fake_evidence)
    capsys.readouterr()
    assert eval_cases.main(['eval', '--host-root', str(host)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'EVALUATED' and out['mismatched'] == 3 and out['type_counts_match_case_file'] is True
    assert out['evidence_mode'] == 'booking_and_mail' and set(out['timings_seconds']) == {'context', 'evidence', 'rejudge'}
    assert 'elapsed_seconds' in out
    # evidence cache sits beside, never inside, the case folder
    assert seen['cache'] == host / eval_cases.EVIDENCE_CACHE
    assert not seen['cache'].resolve().is_relative_to((host / eval_cases.CASES_SUBPATH).resolve())
    assert not any(i in json.dumps(out) for i in ids)
    assert eval_cases.main(['eval', '--host-root', str(host), '--fail-on-mismatch']) == 2
    assert db.read_bytes() == before


def test_case_folder_cannot_be_inside_repository_or_outside_host_backups(setup, tmp_path, capsys):
    host = host_with_copy(setup, tmp_path)
    for folder in (eval_cases.REPO_ROOT / 'docs' / 'cases', tmp_path / 'elsewhere'):
        assert eval_cases.main(['build', '--host-root', str(host), '--cases-dir', str(folder)]) == 1
        assert json.loads(capsys.readouterr().out)['status'] == 'FAILED'
        assert not folder.exists()


def test_stale_evidence_cache_is_rebuilt_once_and_reported(setup, tmp_path, monkeypatch, capsys):
    c, _ = corrected(setup)
    c.commit()
    host = host_with_copy(setup, tmp_path)
    import tools.complete_card_classification as legacy
    cache = host / eval_cases.EVIDENCE_CACHE
    cache.parent.mkdir(parents=True)
    cache.write_text('{}', encoding='utf-8')
    calls = []

    def fake_evidence(conn, host_root, trips, path=None):
        calls.append(path.is_file())
        if path.is_file():
            raise ValueError('EVIDENCE_CACHE_STALE')
        return {}, {}
    monkeypatch.setattr(legacy, 'load_context', lambda conn, host_root: (TRIPS, {}))
    monkeypatch.setattr(legacy, 'load_review_evidence', fake_evidence)
    assert eval_cases.main(['eval', '--host-root', str(host)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert calls == [True, False] and out['evidence_cache'] == 'rebuilt_stale'
