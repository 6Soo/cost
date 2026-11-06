"""Presentation integration: primary tasks remain reachable in every page shell."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import pytest

from webapp.card_flow import page
from webapp.card_flow import PAGE
from webapp.expense_workspace import decorate


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


def test_core_tasks_are_primary_and_management_is_disclosed_with_reachable_panels():
    parser = WorkspaceParser()
    parser.feed(page('synthetic-token'))
    assert len(parser.tabs) == 4
    assert [tab['data-expense-view'] for tab in parser.tabs] == ['cleanup', 'upload', 'saved', 'rules']
    assert all('details' not in ancestors for ancestors in parser.tab_ancestors[:2])
    assert all('details' in ancestors for ancestors in parser.tab_ancestors[2:])
    assert sum(tab['aria-selected'] == 'true' for tab in parser.tabs) == 1
    for tab in parser.tabs:
        _, panel = parser.ids[tab['aria-controls']]
        assert panel['role'] == 'tabpanel'
        assert panel['aria-labelledby'] == tab['id']
    for target in ('upload', 'file', 'status', 'summary', 'preview', 'questions', 'ruleform', 'rule-panel'):
        assert target in parser.ids
    assert re.search(r'<label for="rule-text">분류 지시</label>\s*<textarea id="rule-text"', page('synthetic-token'))
    assert '<!--EXPENSE_CLEANUP-->' in page('synthetic-token')


def test_workspace_keeps_csrf_as_script_data_and_does_not_create_forms():
    markup = page('quote" and unicode 한글')
    assert 'const csrf="quote\\" and unicode \\ud55c\\uae00"' in markup
    parser = WorkspaceParser()
    parser.feed(markup)
    assert parser.ids['ruleform'][0] == 'form'
    assert parser.ids['file'][1]['multiple'] is None
    assert '카드 자료 관리</summary>' not in markup


def test_decorator_accepts_heading_and_attribute_variants_without_losing_source_markup():
    source_heading = re.search(r'<h1\b[^>]*>.*?</h1>', PAGE, re.S).group()
    variant_heading = re.sub(
        r'<h1\b([^>]*)>(.*?)</h1>',
        lambda match: '<h1 class="source-heading" data-owner="legacy"' + match.group(1)
        + '>  ' + match.group(2).strip() + ' </h1>',
        source_heading,
        count=1,
    )
    source = PAGE.replace(source_heading, variant_heading, 1)
    source = source.replace('<details id="saved-materials">', '<details data-kind=saved id=saved-materials role=group>', 1)
    source = source.replace('<p id="status" role="status"></p>', '<p role=status id=status data-fixture=kept>synthetic status</p>', 1)
    source = source.replace('</style><body>', '</style> \n<body data-fixture="variant">', 1)
    result = decorate(source, page_title='카드 거래 상세')

    assert '<h1 class="source-heading" data-owner="legacy">  카드 거래 상세 </h1>' in result
    assert '<details data-kind=saved id=saved-materials role="tabpanel" aria-labelledby="expense-tab-saved">' in result
    assert '<p role=status id=status data-fixture=kept>synthetic status</p>' in result
    assert '<body data-fixture="variant">' in result
    assert result.count('<!--EXPENSE_CLEANUP-->') == 1
    assert result.count('<section id="expense-transactions"') == 1
    assert 'const csrf=__CSRF__' in result
    parser = WorkspaceParser()
    parser.feed(result)
    assert parser.stack == []
    assert parser.ids['saved-materials'][1]['data-kind'] == 'saved'
    assert parser.ids['expense-tab-cleanup'][1]['aria-controls'] == 'expense-overview'


@pytest.mark.parametrize('mutation', ['heading', 'duplicate-heading', 'panel', 'status', 'main', 'style-body', 'marker'])
def test_decorator_fails_closed_when_a_required_mount_point_is_missing_or_ambiguous(mutation):
    source = PAGE
    if mutation == 'heading':
        source = re.sub(r'<h1\b[^>]*>.*?</h1>', '', source, count=1, flags=re.S)
    elif mutation == 'duplicate-heading':
        heading = re.search(r'<h1\b[^>]*>.*?</h1>', source, re.S).group()
        source = source.replace(heading, heading + heading, 1)
    elif mutation == 'panel':
        source = source.replace('id="saved-materials"', 'id="saved-materials-missing"', 1)
    elif mutation == 'status':
        source = source.replace('id="status"', 'id="status-missing"', 1)
    elif mutation == 'main':
        source = source.replace('</main>', '', 1)
    elif mutation == 'style-body':
        source = source.replace('</style><body>', '</style><html>', 1)
    elif mutation == 'marker':
        source += '<!--EXPENSE_CLEANUP-->'

    with pytest.raises(ValueError, match='expense workspace'):
        decorate(source)


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is unavailable for the non-browser DOM harness')
def test_navigation_script_handles_partial_dom_keyboard_deep_links_history_and_loader():
    script = json.dumps((Path(__file__).parents[1] / 'static' / 'js' / 'expense_workspace.js').read_text(encoding='utf-8'))
    harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const source = SCRIPT_SOURCE;
// A tab-only fragment previously reached MutationObserver.observe(null).
const partialTab = {dataset: {expenseView: 'cleanup'}};
assert.doesNotThrow(() => vm.runInNewContext(source, {
  document: {querySelectorAll: () => [partialTab], getElementById: () => null},
}));
function makeWorld(initialHash = '') {
  const windowEvents = {};
  const observers = [];
  function element(view = '') {
    const events = {};
    return {
      dataset: view ? {expenseView: view} : {}, attrs: {}, events,
      open: false, hidden: false, disabled: false, tabIndex: 0,
      addEventListener(name, callback) { events[name] = callback; },
      setAttribute(name, value) { this.attrs[name] = value; },
      focus() { this.focused = true; },
      querySelector() { return null; },
      contains() { return false; },
    };
  }
  const tabs = [element('cleanup'), element('saved'), element('upload')];
  const nodes = new Map([
    ['card-review-detail', element()], ['expense-overview', element()],
    ['saved-materials', element()], ['newupload', element()], ['upload', element()],
  ]);
  nodes.get('upload').disabled = true;
  const location = {pathname: '/import', search: '', hash: initialHash};
  Object.defineProperty(location, 'href', {get() { return 'https://cost.test' + this.pathname + this.search + this.hash; }});
  const stack = [location.href];
  let position = 0;
  function setLocation(value) {
    const url = new URL(value, 'https://cost.test');
    location.pathname = url.pathname; location.search = url.search; location.hash = url.hash;
  }
  const history = {
    pushState(_state, _title, value) {
      stack.splice(position + 1); stack.push(new URL(value, 'https://cost.test').href); position++;
      setLocation(stack[position]);
    },
    replaceState(_state, _title, value) { setLocation(value); stack[position] = location.href; },
    traverse(next) { position = next; setLocation(stack[position]); windowEvents.popstate(); windowEvents.hashchange(); },
    get position() { return position; },
  };
  const document = {
    querySelectorAll(selector) { return selector === '[data-expense-view]' ? tabs : []; },
    getElementById(id) { return nodes.get(id) || null; },
  };
  class MutationObserver {
    constructor(callback) { this.callback = callback; }
    observe(target) { assert.ok(target); observers.push(this); }
  }
  let loaderCalls = 0;
  const window = {addEventListener(name, callback) { windowEvents[name] = callback; }};
  vm.runInNewContext(source, {
    document, window, location, history, URL, URLSearchParams, MutationObserver,
    startCardReview() { loaderCalls++; },
  });
  return {tabs, nodes, location, history, observers, loaderCalls: () => loaderCalls};
}

// Optional containers are absent, while the three navigable tabs and their
// panels remain. The loader is disabled until an async upload completes.
const world = makeWorld();
world.tabs[2].events.click();
assert.equal(world.location.hash, '#newupload');
assert.equal(world.loaderCalls(), 0);
world.nodes.get('upload').disabled = false;
world.observers.find(observer => observer.callback).callback();
assert.equal(world.loaderCalls(), 1);
world.history.traverse(0); // Back: popstate and hashchange describe one move.
assert.equal(world.tabs[0].attrs['aria-selected'], 'true');
world.history.traverse(1); // Forward restores the deep-linked upload tab.
assert.equal(world.tabs[2].attrs['aria-selected'], 'true');
assert.equal(world.loaderCalls(), 2); // The production loader itself is idempotent.
world.tabs[2].events.keydown({key: 'Home', preventDefault() { this.prevented = true; }});
assert.equal(world.tabs[0].attrs['aria-selected'], 'true');
assert.equal(world.location.hash, '#expense-cleanup');

// Direct deep links work even when review-only DOM nodes are omitted.
const deep = makeWorld('#saved-materials');
assert.equal(deep.tabs[1].attrs['aria-selected'], 'true');
'''.replace('SCRIPT_SOURCE', script)
    result = subprocess.run([shutil.which('node'), '-e', harness], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
