"""Same read-only state and row population, with fewer repeated SQL reads."""
import ast
import re
import subprocess

import pytest

from webapp import card_flow, ledger_board
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows, unassigned_row

BASELINE = '55e304ad493a4f8cdcf1eddf4188e931cb3e1af7'


def baseline_renderer():
    source = subprocess.check_output(['git', 'show', BASELINE + ':webapp/card_flow.py']).decode('utf-8')
    tree = ast.parse(source)
    # Retain the old population implementation too: the comparison must not
    # accidentally exercise the new aggregation on both sides.
    names = {'render_expense_cleanup', '_cleanup_counts'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    from types import SimpleNamespace
    from webapp import card_actions
    namespace = dict(vars(card_flow))
    # The baseline renderer predates PR #737, which retired the old reason
    # categories. Keep those labels only inside this historical renderer so
    # its population and query-count paths remain comparable.
    namespace["REASON_LABELS"] = {
        **card_actions.REASON_LABELS,
        "classification": "Synthetic classification",
        "recording": "Synthetic recording",
        "manual": "Synthetic manual",
        "": "Synthetic no reason",
    }
    for node in nodes:
        node.body = [child for child in node.body if not (
            isinstance(child, ast.ImportFrom) and child.level == 1 and child.module == "card_cleanup_ui")]
        for child in ast.walk(node):
            if isinstance(child, ast.ImportFrom) and child.module == "card_actions":
                child.names = [alias for alias in child.names if alias.name != "REASON_LABELS"]
    legacy_ui = SimpleNamespace(**vars(card_flow.card_cleanup_ui))
    render_section = legacy_ui.render_cleanup_section
    def render_legacy_section(**kwargs):
        return render_section(action_summary_html="", diagnostics_open=True, **kwargs)
    legacy_ui.render_cleanup_section = render_legacy_section
    namespace["card_cleanup_ui"] = legacy_ui
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<baseline-cleanup>', 'exec'), namespace)
    return namespace['render_expense_cleanup']


@pytest.fixture
def population(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'cleanup-refactor.sqlite', seed_demo=False)
    ledger_board.bind_store(board)
    flow, batch, rows = card_rows(board, 45)
    monkeypatch.setattr(card_flow, '_ota_entries_by_card', lambda *a, **kw: {})
    board.conn.execute("UPDATE transactions SET classification_source='inference'")
    board.conn.execute("UPDATE transactions SET item='' WHERE transaction_id=?", (rows[1]['transaction_id'],))
    board.conn.execute("UPDATE transactions SET conflict_reason='conflict' WHERE transaction_id=?", (rows[2]['transaction_id'],))
    board.conn.execute("INSERT INTO transaction_review_holds(transaction_id,source_hash,kind,reason) VALUES (?,?,?,?)",
                       (rows[3]['transaction_id'], rows[3]['source_hash'], 'evidence_pending', 'synthetic hold'))
    # A refund whose original may be off-page, preserving source identifiers.
    board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-5000,original_approval_number=? WHERE transaction_id=?",
                       (rows[0]['approval_number'], rows[4]['transaction_id']))
    unassigned_row(board)
    board.conn.commit()
    try:
        yield board
    finally:
        ledger_board.bind_store(None)
        board.close()


def render_with_queries(renderer, board, **options):
    statements = []
    board.conn.set_trace_callback(statements.append)
    try:
        html = renderer(board, 'synthetic-token', **options)
    finally:
        board.conn.set_trace_callback(None)
    return html, [q for q in statements if q.lstrip().upper().startswith('SELECT')]


@pytest.mark.parametrize('reason,page', [('all', 1), ('all', 2), ('all', 3), ('classification', 1),
                                       ('evidence', 1), ('finance', 1), ('manual', 2), ('invalid', 1)])
def test_cleanup_keeps_financial_state_and_row_population_with_fewer_reads(population, reason, page):
    board = population
    tables = [r[0] for r in board.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    def snapshot():
        return {name: board.conn.execute('SELECT * FROM "' + name + '"').fetchall() for name in tables}
    before = snapshot()
    previous, old_queries = render_with_queries(baseline_renderer(), board, reason=reason, page=page)
    actual, new_queries = render_with_queries(card_flow.render_expense_cleanup, board, reason=reason, page=page)
    assert re.findall(r"data-transaction='([^']+)'", actual) == re.findall(r"data-transaction='([^']+)'", previous)
    assert "\uac70\ub798\u00b7\uc7a5\ubd80 \uc0c1\ud0dc \uc0c1\uc138" in actual
    assert "\uc0ac\uc6a9\uc790 \uc694\uccad \uc544\ub2d8" in actual
    assert "\ucc98\ub9ac \ud544\uc694\ud55c \uac70\ub798" not in actual
    assert snapshot() == before
    assert len(new_queries) < len(old_queries)
