"""보존된 카드 원본으로 분류용 업종만 보완한다. 금액과 사용자 답변은 바꾸지 않는다. 쓰는 DB는 board.sqlite 하나라 백업 확인은 `verify_operational_backup_restore.py --scope board`로 충분하다."""
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import Pipeline
from app.db import decided_sql
from app.import_card import parse_card_file
from app.review import transaction_identity,source_hash_of
from webapp.ledger_store import LedgerStore


def main():
    os.environ['WEBLEDGER_UNIFIED_DB']='1'
    store=LedgerStore('D:/WebLedgerHost/data/board.sqlite',seed_demo=False)
    try:
        pipe=Pipeline(store.conn)
        updates=[]
        batches=store.conn.execute('SELECT batch_id,content_bytes,filename FROM import_batches').fetchall()
        for batch_id,content,filename in batches:
            for row in parse_card_file(content,filename,use_cache=False).rows:
                identity=transaction_identity(row)
                current=store.conn.execute('SELECT source_hash,'+decided_sql()+' FROM transactions WHERE transaction_id=?',
                                           (identity,)).fetchone()
                if current is None or current[0] != source_hash_of(row):
                    raise RuntimeError('FINANCIAL_SOURCE_CHANGED')
                if not current[1]:
                    updates.append((row.description_raw,identity,current[0]))
        store.conn.execute('BEGIN IMMEDIATE')
        try:
            for description,identity,digest in updates:
                store.conn.execute('UPDATE transactions SET description_raw=? WHERE transaction_id=? '
                                   'AND source_hash=? AND NOT '+decided_sql(),(description,identity,digest))
            for batch_id,_,_ in batches:
                pipe.classify_batch(batch_id)
            counts=dict(store.conn.execute('SELECT classification_state,COUNT(*) FROM transactions GROUP BY classification_state'))
            pipe.store.log_change('source.categories_refreshed','card-files',{'counts':counts})
            store.conn.commit()
        except Exception:
            store.conn.rollback()
            raise
        (ROOT/'.local-archive/lightweight-20261003/category-refresh.json').write_text(
            json.dumps({'counts':counts,'financial_source_unchanged':True,'confirmed_answers_protected':True},indent=2),encoding='utf-8')
        print('CARD_CATEGORIES_REFRESHED')
    finally:
        store.close()


if __name__=='__main__':
    main()
