"""중지된 운영 작성자를 전제로 단일 DB와 카드 처리 경로로 전환한다."""
import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_operational_backup_restore import backup_database, database_state
from webapp.db_merge import merge_review_database
from webapp.ledger_store import LedgerStore
from ledger.domain.direct_trip_schedule_authority import load_document
from app import Pipeline


def main():
    if os.environ.get('WEBLEDGER_MAINTENANCE') != 'LIGHTWEIGHT':
        raise RuntimeError('WRITERS_MUST_BE_STOPPED')
    host = Path('D:/WebLedgerHost')
    config_path = host/'config/real-review.json'
    options_path = host/'config/card-flow.json'
    launch_path = host/'bin/launch_web_ledger.py'
    db = host/'data/board.sqlite'
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    validation = json.loads((ROOT/'docs/handoff/2026-10-01/selected-review-schedule-validation.json').read_text(encoding='utf-8'))
    authority = Path(validation['validated_artifact'])
    if hashlib.sha256(authority.read_bytes()).hexdigest() != validation['validated_artifact_sha256']:
        raise RuntimeError('SCHEDULE_ARTIFACT_CHANGED')
    source_hash = hashlib.sha256(Path(config['snapshot_path']).read_bytes()).hexdigest()
    if source_hash != config['snapshot_sha256'] or source_hash != validation['source_sha256']:
        raise RuntimeError('CURRENT_SCHEDULE_SOURCE_CHANGED')
    records,_ = load_document(authority)
    if any(not r.is_authoritative or r.source_sha256 != source_hash for r in records):
        raise RuntimeError('SCHEDULE_NOT_AUTHORITATIVE')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = host/'data/backups'/('lightweight-'+stamp)
    backup.mkdir(parents=True,exist_ok=False)
    originals = {'board.sqlite':db,'board.operator.sqlite':db.with_suffix('.operator.sqlite'),
                 'real-review.sqlite':Path(config['decisions_db_path'])}
    if any(not path.resolve().is_relative_to((host/'data').resolve()) for path in originals.values()):
        raise RuntimeError('DATABASE_PATH_OUTSIDE_HOST')
    old_states={}
    for name,path in originals.items():
        old_states[name] = database_state(path)
        backup_database(path,backup/name)
        if database_state(backup/name) != old_states[name]:
            raise RuntimeError('RESTORE_VERIFICATION_FAILED')
    for path in (config_path,launch_path,options_path):
        if path.is_file():
            shutil.copy2(path,backup/path.name)
    store = None
    try:
        os.environ['WEBLEDGER_UNIFIED_DB']='1'
        store = LedgerStore(db,seed_demo=False)
        merge_review_database(db,Path(config['decisions_db_path']))
        pipe=Pipeline(store.conn)
        imported=[]
        for path in sorted((ROOT/'ledger/newcard/conv').glob('*.xlsx')):
            received=pipe.receive(path.read_bytes(),path.name)
            pipe.classify_batch(received['batch_id'])
            imported.append({k:received[k] for k in ('filename','batch_id','row_count')})
        after=database_state(db)
        for table in ('board_rows','board_revisions','owner_profile','trip_tabs'):
            if table in old_states['board.sqlite'] and after[table] != old_states['board.sqlite'][table]:
                raise RuntimeError('EXISTING_USER_DATA_CHANGED')
        store.close()
        store=None
        config['decisions_db_path']=str(db)
        config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        options_path.write_text(json.dumps({'enabled':True,'trip_authority_path':str(authority)},indent=2),encoding='utf-8')
        shutil.copy2(ROOT/'tools/launch_web_ledger.py',launch_path)
        result={'status':'deployed','backup':str(backup),'imports':imported,
                'existing_board_preserved':True,'unconfirmed_entries_posted':0,
                'source_of_truth':'board.sqlite','database_count':1}
        (ROOT/'.local-archive/lightweight-20261003/deployment.json').write_text(
            json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('LIGHTWEIGHT_DEPLOYMENT_OK')
    except Exception:
        if store:
            store.close()
        for path in originals.values():
            for suffix in ('-wal','-shm'):
                side=Path(str(path)+suffix)
                if side.is_file():
                    side.unlink()
        for name,path in originals.items():
            backup_database(backup/name,path)
        for path in (config_path,launch_path,options_path):
            saved=backup/path.name
            if saved.is_file():
                shutil.copy2(saved,path)
            elif path == options_path and path.exists():
                path.unlink()
        raise


if __name__=='__main__':
    main()
