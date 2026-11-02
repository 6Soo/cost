"""Presentation integration: primary tasks remain reachable in every page shell."""
from html.parser import HTMLParser

from webapp.card_flow import page


class WorkspaceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}
        self.tabs = []
        self.stack = []
        self.tab_ancestors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids
            self.ids[attrs['id']] = (tag, attrs)
        if attrs.get('role') == 'tab':
            self.tabs.append(attrs)
            self.tab_ancestors.append(list(self.stack))
        if tag not in ('meta', 'input', 'link', 'br', 'hr', 'img', 'path', 'line', 'circle', 'polyline', 'rect'):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]


def test_tasks_are_top_level_tabs_with_unique_reachable_panels():
    parser = WorkspaceParser()
    parser.feed(page('synthetic-token'))
    assert len(parser.tabs) == 4
    assert all('details' not in ancestors for ancestors in parser.tab_ancestors)
    assert sum(tab['aria-selected'] == 'true' for tab in parser.tabs) == 1
    for tab in parser.tabs:
        _, panel = parser.ids[tab['aria-controls']]
        assert panel['role'] == 'tabpanel'
        assert panel['aria-labelledby'] == tab['id']
    for target in ('upload', 'file', 'status', 'summary', 'preview', 'questions', 'ruleform', 'rule-panel'):
        assert target in parser.ids
    assert '<!--EXPENSE_CLEANUP-->' in page('synthetic-token')


def test_workspace_keeps_csrf_as_script_data_and_does_not_create_forms():
    markup = page('quote" and unicode 한글')
    assert 'const csrf="quote\\" and unicode \\ud55c\\uae00"' in markup
    parser = WorkspaceParser()
    parser.feed(markup)
    assert parser.ids['ruleform'][0] == 'form'
    assert parser.ids['file'][1]['multiple'] is None
    assert '카드 자료 관리</summary>' not in markup
