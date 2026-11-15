"""links 그림자 시험 도우미: 합성 시나리오 JSON으로 board DB 파일을 만든다(합성 자료만).

    python -I links_python.py build <scenario.json> <db>
    python -I links_python.py rows <db>
    python -I links_python.py build-many <manifest.json>   # [{"scenario","db","rows"?}, ...]
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from tools.core_bridge.synthetic import scenario_db  # noqa: E402


def build(scenario_path, target):
    scenario = json.loads(Path(scenario_path).read_text(encoding='utf-8'))
    with scenario_db(scenario) as source:
        src = sqlite3.connect(source)
        dst = sqlite3.connect(target)
        src.backup(dst)
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.commit()
        dst.close()
        src.close()


def rows_json(db):
    """The JSON the Python adapter sends to `links refund --rows-stdin` for this database."""
    from app import core_links
    conn = sqlite3.connect(db)
    try:
        return json.dumps(core_links.row_dicts(core_links.fetch_rows(conn)))  # ASCII escapes: stdout encoding is not UTF-8 on Windows
    finally:
        conn.close()


def rows(db):
    print(rows_json(db))


def build_many(manifest_path):
    """One process for many cases: build each DB and, when `rows` is given, write its rows JSON there."""
    for item in json.loads(Path(manifest_path).read_text(encoding='utf-8')):
        build(item['scenario'], item['db'])
        if item.get('rows'):
            Path(item['rows']).write_text(rows_json(item['db']), encoding='ascii')


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == 'rows':
        rows(sys.argv[2])
    elif sys.argv[1] == 'build-many':
        build_many(sys.argv[2])
