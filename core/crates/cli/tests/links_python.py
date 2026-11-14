"""links 그림자 시험 도우미: 합성 시나리오 JSON으로 board DB 파일을 만든다(합성 자료만).

    python -I links_python.py build <scenario.json> <db>
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


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build(sys.argv[2], sys.argv[3])
