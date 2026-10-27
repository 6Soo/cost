import importlib.util
import json
from pathlib import Path
import subprocess
import sys


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
    sql = [x for x in result["findings"] if x["kind"].startswith("sql_")]
    assert [x["kind"] for x in sql] == ["sql_write", "sql_read_or_other"]
    assert [(x["verb"], x["table"]) for x in sql] == [("UPDATE", "records"), ("SELECT", "records")]
    assert "statement" not in str(result)


def test_sql_comments_ctes_and_batches_are_unknown_without_literals():
    source = '''
def query(conn):
    conn.execute("UPDATE secret_table SET note='CUSTOMER_NAME' -- annotation")
    conn.execute("WITH q AS (SELECT 1) UPDATE records SET x=2")
    conn.executescript("UPDATE records SET x=1; DELETE FROM records")
'''
    result = audit.analyze_source(source)
    sql = [x for x in result["findings"] if x["kind"].startswith("sql_")]
    assert len(sql) == 3 and all(x["status"] == "OPEN_QUESTION" for x in sql)
    encoded = json.dumps(result)
    assert "CUSTOMER_NAME" not in encoded and "secret_table" not in encoded


def test_cli_uses_root_for_relative_paths_and_emits_json_errors(tmp_path):
    (tmp_path / "ok.py").write_text('def f():\n    return 1\n', encoding="utf-8")
    outside = tmp_path.parent / "outside-rf001.py"
    outside.write_text("def outside(): pass\n", encoding="utf-8")
    broken = tmp_path / "broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")
    invalid = tmp_path / "invalid.py"
    invalid.write_bytes(b"\xff")
    cli = Path(__file__).parents[1] / "tools" / "audit_write_boundaries.py"

    valid_run = subprocess.run([sys.executable, str(cli), "--root", str(tmp_path), "ok.py"], capture_output=True, text=True)
    valid = json.loads(valid_run.stdout)
    assert valid_run.returncode == 0 and valid["files"][0]["path"] == "ok.py"

    failed = subprocess.run([sys.executable, str(cli), "--root", str(tmp_path), "broken.py", "invalid.py", str(outside)], capture_output=True, text=True)
    payload = json.loads(failed.stdout)
    assert failed.returncode == 2
    assert {item["code"] for item in payload["errors"]} == {"SYNTAX_ERROR", "SOURCE_READ_ERROR", "PATH_OUTSIDE_ROOT"}


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
