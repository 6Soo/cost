"""Income connection action is available without changing source or saved links."""
from copy import deepcopy
from html.parser import HTMLParser
import pytest
from webapp import participant_trip_panel as panel,google_ledger_page as google
from webapp.tests.test_participant_trip_panel import sample_state


class Templates(HTMLParser):
    def __init__(self):
        super().__init__();self.ref=None;self.data={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='template' and 'data-income-ref' in attrs:
            self.ref=attrs['data-income-ref'];self.data[self.ref]=[]
        elif self.ref:self.data[self.ref].append((tag,attrs))
    def handle_endtag(self,tag):
        if tag=='template':self.ref=None


@pytest.mark.parametrize('available',[True,False])
def test_unlinked_action_is_only_offered_for_current_income(available):
    state=sample_state(2);state['google']['available']=available
    state['income_rows'][1]['amount']=0
    before=deepcopy(state);view=Templates();view.feed(panel.render(state))
    ref=state['income_rows'][0]['ref'];refund=state['income_rows'][1]['ref']
    assert any('data-connect-income' in attrs for tag,attrs in view.data[ref])==available
    assert not any('data-connect-income' in attrs for tag,attrs in view.data[refund])
    assert state==before


def test_linked_status_keeps_names_and_existing_unlink_protection_without_connect_action():
    state=sample_state(1);ref=state['income_rows'][0]['ref']
    state['participants']=[{'participant_id':'person-0','display_name':'합*성',
                            'links':[{'income_ref':ref,'method':'manual'}]}]
    before=deepcopy(state);body=panel.render(state,csrf='synthetic-csrf')
    assert '<summary><span>1명 연결 · 합*성</span></summary>' in body
    assert 'data-connect-income' not in body
    assert "action='/api/participants/unlink'" in body
    assert "value='synthetic-csrf'" in body and "value='synthetic-fingerprint'" in body
    assert state==before


def test_no_selectable_roster_keeps_action_and_explains_missing_form_without_inventing_people():
    state=sample_state(1);state['roster']['participants']=[]
    body=panel.render(state)
    assert 'data-connect-income' in body
    assert 'participant-connect-notice' in body
    assert "class='participant-keyboard-link'" not in body
    assert '/participants/insurance-match' not in body


def test_initial_income_cell_uses_same_action_and_refund_stays_status_only():
    assert 'data-connect-income' in google._participant_insurance_cell({'amount':1000},{})
    assert google._participant_insurance_cell({'amount':0},{})=='환불완료'
