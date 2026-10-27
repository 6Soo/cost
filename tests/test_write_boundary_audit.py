import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "audit_write_boundaries.py"
SPEC = importlib.util.spec_from_file_location("audit_write_boundaries", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_methods_decorators_and_literal_sql_are_classified():
    result = audit.analyze_source('''
@login_required
@owner_only
def save_record(conn, value):
    conn.execute("UPDATE records SET value=?", (value,))
    return conn.execute("SELECT value FROM records")
''', "synthetic.py")
    callable_row = next(x for x in result["findings"] if x["kind"] == "callable")
    assert callable_row["signals"] == ["login_required", "owner_only"]
    assert [x["kind"] for x in result["findings"] if x["kind"].startswith("sql_")] == ["sql_write", "sql_read_or_other"]


def test_dynamic_sql_and_indirect_writer_remain_open_questions():
    result = audit.analyze_source('''
def change(conn, table, payload):
    conn.execute(f"UPDATE {table} SET value=?", (payload,))
    store.apply(payload)
    target(payload)
''')
    statuses = [x["status"] for x in result["findings"] if x["kind"] in ("sql_unknown", "write_like_call")]
    assert statuses == ["OPEN_QUESTION", "OPEN_QUESTION"]
    assert "target" not in [x.get("call") for x in result["findings"]]
