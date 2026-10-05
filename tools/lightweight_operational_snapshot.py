"""운영 DB를 읽기 전용으로 열어 로컬 복구 사본을 만든다."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def main():
    root = Path('D:/WebLedgerHost')
    output = Path('C:/AX/cost/.local-archive/lightweight-20261003/operational')
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((root/'config/real-review.json').read_text(encoding='utf-8-sig'))
    paths = [root/'data/board.sqlite', root/'data/board.operator.sqlite', Path(config['decisions_db_path'])]
    result = {'databases':[], 'source_paths':{k:v for k,v in config.items() if k.endswith('_path')},
              'source_hashes':{k:v for k,v in config.items() if k.endswith('_sha256')}}
    for index, source in enumerate(paths):
        if not source.is_file():
            continue
        dest = output/f'{index}-{source.name}'
        if dest.exists():
            raise RuntimeError('SNAPSHOT_ALREADY_EXISTS')
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old:
            with closing(sqlite3.connect(dest)) as new:
                old.backup(new)
                if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('BACKUP_INTEGRITY_FAILED')
                tables = [r[0] for r in new.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                counts = {t:new.execute('SELECT COUNT(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
        result['databases'].append({'source':str(source),'copy':str(dest),'counts':counts,
                                    'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    (output/'snapshot.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OPERATIONAL_SNAPSHOT_OK')


if __name__ == '__main__':
    main()
