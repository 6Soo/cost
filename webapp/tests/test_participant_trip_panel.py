from webapp import participant_trip_panel as panel


def sample_state(count=25):
    rows = [{"ref": f"main|synthetic|{i + 6}", "row": i + 6,
             "name": f"payer-{i}", "nickname": "", "amount": 1000 + i,
             "cells": {"B": "2026-10-28"}} for i in range(count)]
    people = [{"participant_id": f"person-{i}", "display_name": f"person {i}",
               "active": True, "state": "confirmed"} for i in range(count)]
    return {"trip_id": "trip-synthetic", "configured": True,
            "input_fingerprint": "synthetic-fingerprint", "income_rows": rows,
            "participants": [], "unlinked_income": rows,
            "counts": {"roster_confirmed": count, "linked": 0,
                       "unlinked_income_rows": count},
            "google": {"available": True},
            "roster": {"scope": "partial", "participants": people}}


def test_projection_shows_all_income_rows_but_keeps_participants_bounded():
    projected = panel.project(sample_state())
    assert len(projected["rows"]) == 25
    assert len(projected["participants"]) == 20
    assert not projected["rows_more"] and projected["participants_more"]
    second = panel.project(sample_state(), income_offset=20, participant_offset=20)
    assert [row["row"] for row in second["rows"]] == list(range(6, 31))
    assert len(second["participants"]) == 5


def test_virtual_projection_keeps_source_rows_and_amounts_unchanged():
    state = sample_state(2)
    before = [(row["ref"], row["amount"], dict(row["cells"])) for row in state["income_rows"]]
    html = panel.render(state, csrf="synthetic-csrf")
    after = [(row["ref"], row["amount"], dict(row["cells"])) for row in state["income_rows"]]
    assert after == before
    assert "<table" not in html
    assert "participant-income-status" in html
    assert "미연결 · 보험 미가입을 뜻하지 않음" in html
    assert "1000원" not in html


def test_names_are_escaped_and_links_require_the_reconciliation_fingerprint():
    state = sample_state(1)
    state["roster"]["participants"][0]["display_name"] = "<script>alert(1)</script>"
    html = panel.render(state, csrf="synthetic-csrf")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "action='/api/participants/link'" in html
    assert "name='input_fingerprint' value='synthetic-fingerprint'" in html
    assert "name='csrf' value='synthetic-csrf'" in html


def test_unavailable_source_does_not_become_zero_or_unlinked():
    state = sample_state(1)
    state["google"]["available"] = False
    html = panel.render(state)
    assert "수입 자료 확인 필요" in html
    assert "미연결 · 보험 미가입을 뜻하지 않음" not in html


def test_row_identity_is_canonical_source_sheet_row():
    rows = [{"row": 9}]
    result = panel.attach_row_refs(rows, source="archive", sheet="synthetic-tab")
    assert result[0]["participant_income_ref"] == "archive|synthetic-tab|9"
    assert rows == [{"row": 9}]


def test_paging_encodes_identity_and_preserves_other_offset():
    from urllib.parse import urlsplit, parse_qs
    import html as html_module
    import re
    state = sample_state(50)
    state['trip_id'] = '여행 &/opaque'
    markup = panel.render(state, income_offset=0, participant_offset=20)
    hrefs = re.findall("href='([^']+)'", markup)
    queries = [parse_qs(urlsplit(html_module.unescape(href)).query) for href in hrefs
               if urlsplit(html_module.unescape(href)).path == '/board']
    assert all(query['tab'] == [state['trip_id']] for query in queries)
    assert any(query.get('participant_offset') == ['40'] and
               'participant_income_offset' not in query for query in queries)
    assert '수입 다음 20건' not in markup
    # All unlinked people remain selectable; only the cards are paginated.
    assert "data-participant='person-49'" not in markup
    assert "value='person-49'" in markup


def test_unconfirmed_or_inactive_roster_entries_are_not_draggable_options():
    state = sample_state(3)
    state['roster']['participants'][0]['state'] = 'pending'
    state['roster']['participants'][1]['active'] = False
    markup = panel.render(state)
    assert 'person 0' not in markup
    assert 'person 1' not in markup
    assert 'person 2' in markup


def test_linked_people_are_filtered_before_paging_without_changing_links():
    import copy
    state = sample_state(45)
    state['participants'] = [{'participant_id': f'person-{i}', 'display_name': f'person {i}',
                              'links': [{'income_ref': state['income_rows'][i]['ref'], 'method': 'manual'}]}
                             for i in range(25)]
    before = copy.deepcopy(state)
    data = panel.project(state)
    assert [p['participant_id'] for p in data['participants']] == [f'person-{i}' for i in range(25, 45)]
    assert data['unlinked_participant_count'] == 20 and not data['participants_more']
    assert panel.project(state, participant_offset=40)['participant_offset'] == 0
    markup = panel.render(state)
    assert "data-participant='person-0'" not in markup
    assert "<option value='person-0'>" not in markup
    assert "name='participant_id' value='person-0'" in markup  # Unlink protection stays available.
    assert "data-participant='person-25'" in markup
    assert state == before


def test_all_linked_empty_state_has_no_connect_form_and_keeps_income_status():
    state = sample_state(1)
    state['participants'] = [{'participant_id': 'person-0', 'display_name': 'person 0',
                              'links': [{'income_ref': state['income_rows'][0]['ref'], 'method': 'manual'}]}]
    markup = panel.render(state)
    assert '모든 참가자가 수입에 연결되어 있습니다.' in markup
    assert "action='/api/participants/link'" not in markup
    assert "action='/api/participants/unlink'" in markup
    assert "class='participant-income-status'" in markup
