"""Synthetic-only tests: case aggregation hides identifiers; re-evaluation detects reverted judgments."""
import json
import sqlite3

import pytest

from app import ai_review_repair as repair
from tests.test_ai_review_repair import add_projection, correction_for, make_manifest, prepare
from tools.quarter_review import eval_cases
from webapp.tests.test_automatic_classification_completion import setup, TRIPS  # noqa: F401

REVIEW_ID = 'ai-quarter-review-2026Q3'
COMMON = 'TRIP-044 · 반복되는 합성 사유'
RARE_WITH_DIGITS = 'TRIP-029 · 드문 합성 사유 20260930'
RARE = 'TRIP-062 · 한 건뿐인 합성 사유'


def corrected(setup):
    """Five AI-review corrections: three agree with today's code, two do not."""
    board, batch, rows = setup[0], setup[2], setup[3]
    c = board.conn
    prepare(c)
    ids = [r['transaction_id'] for r in rows]
    # 0: 09-30, no trip contains it -> code picks the quarter bucket = correction (MATCH)
    # 1: 09-30 corrected into a trip -> code says quarter (MISMATCH, quarter vs trip)
    # 2: 10-03 held in B, corrected to A -> code picks A by the tie rule (MATCH)
    # 3: 10-03 item-only correction the vocabulary cannot derive (MISMATCH, item)
    # 4: 10-03 corrected A -> B, code keeps A (MISMATCH, trip differs)
    c.execute("UPDATE transactions SET approval_date='2026-10-03' WHERE transaction_id IN (?,?,?)", ids[2:])
    c.execute("UPDATE transactions SET trip_id='B',display_tab_id='B' WHERE transaction_id=?", (ids[2],))
    c.commit()
    plan = [(0, 'quarter:2026:3', '식비', COMMON), (1, 'B', '식비', COMMON), (2, 'A', '식비', COMMON),
            (3, 'A', '교통비', RARE_WITH_DIGITS), (4, 'B', '식비', RARE)]
    for i, *_ in plan:
        add_projection(c, ids[i], batch)
    manifest = make_manifest([correction_for(c, ids[i], tab, item=item, basis=basis)
                              for i, tab, item, basis in plan])
    preview = repair.preview(c, TRIPS, manifest)
    assert preview['summary']['to_apply'] == 5, preview['summary']
    repair.apply(c, preview, TRIPS, manifest, request_id=REVIEW_ID)
    return c, ids


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
    assert payload['total'] == 5 and sum(t['count'] for t in payload['types']) == 5
    assert payload['by_rule']['TRIP-044'] == 3
    reasons = {t['reason'] for t in payload['types']}
    # a phrase shared by >=3 rows is published; digits or rare phrasing never is
    assert '반복되는 합성 사유' in reasons
    assert all('20260930' not in r and '한 건뿐인' not in r for r in reasons)
    assert eval_cases.GENERIC_REASON in reasons
    attributions = {t['attribution'] for t in payload['types']}
    assert attributions == {'trip→quarter', 'trip→trip', 'unchanged'}
    assert all(set(t) == {'rules', 'reason', 'before_source', 'item', 'attribution', 'count'}
               for t in payload['types'])


def test_unknown_item_names_are_not_published(setup):
    c, ids = corrected(setup)
    c.execute("UPDATE change_log SET detail_json=replace(detail_json,'교통비','SYNTHETIC-SECRET-ITEM') "
              "WHERE kind='card.ai_review_corrected'")
    text = json.dumps(eval_cases.build_case_file(eval_cases.collect_cases(c, REVIEW_ID), REVIEW_ID),
                      ensure_ascii=False)
    assert 'SYNTHETIC-SECRET-ITEM' not in text and '기타(목록 밖)' in text


def test_reevaluation_detects_mismatches_with_reasons_and_is_read_only(setup):
    c, ids = corrected(setup)
    dump = list(c.iterdump())
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    assert list(c.iterdump()) == dump  # nothing written, projections untouched
    assert report['cases'] == 5 and report['matched'] == 2 and report['mismatched'] == 3
    assert report['by_reason'] == {'ATTRIBUTION_QUARTER_VS_TRIP': 1, 'ATTRIBUTION_TRIP_DIFFERS': 1,
                                   'ITEM_DIFFERS': 1}
    text = json.dumps(report, ensure_ascii=False)
    assert not any(i in text for i in ids)
    assert sum(t['count'] for t in report['by_type']) == 3


def test_reevaluation_reports_zero_when_every_correction_agrees(setup):
    c, ids = corrected(setup)
    # drop the three disagreeing corrections: only cases the code reproduces remain
    c.execute("DELETE FROM change_log WHERE kind='card.ai_review_corrected' AND subject IN (?,?,?)",
              (ids[1], ids[3], ids[4]))
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    assert (report['cases'], report['matched'], report['mismatched'], report['by_reason']) == (2, 2, 0, {})


def test_restored_corrections_are_not_cases(setup):
    c, ids = corrected(setup)
    entry = c.execute("SELECT entry_id FROM change_log WHERE kind='card.ai_review_corrected' AND subject=?",
                      (ids[0],)).fetchone()[0]
    c.execute("INSERT INTO change_log(at,kind,subject,detail_json) VALUES ('x',?,?,?)",
              (eval_cases.RESTORE_KIND, ids[0], json.dumps(dict(release_entry_id=entry))))
    assert len(eval_cases.collect_cases(c, REVIEW_ID)) == 4


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
    import tools.complete_card_classification as legacy
    monkeypatch.setattr(legacy, 'load_context', lambda conn, host_root: (TRIPS, {}))
    monkeypatch.setattr(legacy, 'load_review_evidence', lambda conn, host_root, trips, cache=None: ({}, {}))
    capsys.readouterr()
    assert eval_cases.main(['eval', '--host-root', str(host)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'EVALUATED' and out['mismatched'] == 3 and out['type_counts_match_case_file'] is True
    assert not any(i in json.dumps(out) for i in ids)
    assert eval_cases.main(['eval', '--host-root', str(host), '--fail-on-mismatch']) == 2
    assert db.read_bytes() == before


def test_case_folder_cannot_be_inside_repository_or_outside_host_backups(setup, tmp_path, capsys):
    host = host_with_copy(setup, tmp_path)
    for folder in (eval_cases.REPO_ROOT / 'docs' / 'cases', tmp_path / 'elsewhere'):
        assert eval_cases.main(['build', '--host-root', str(host), '--cases-dir', str(folder)]) == 1
        assert json.loads(capsys.readouterr().out)['status'] == 'FAILED'
        assert not folder.exists()


def test_rows_protected_after_the_review_are_reported_separately_not_as_mismatches(setup):
    c, ids = corrected(setup)
    # e.g. a later duplicate cleanup marks a corrected row; P1 must not judge it
    c.execute("UPDATE transactions SET duplicate_of='synthetic-original' WHERE transaction_id=?", (ids[1],))
    c.commit()
    report = eval_cases.evaluate(c, TRIPS, review_id=REVIEW_ID)
    assert report['not_rejudged'] == 1
    assert report['not_rejudged_by_reason'] == {'NOT_REJUDGED_SOURCE_PROTECTED': 1}
    assert report['mismatched'] == 2 and 'ATTRIBUTION_QUARTER_VS_TRIP' not in report['by_reason']
    assert report['matched'] + report['mismatched'] + report['not_rejudged'] == report['cases']
