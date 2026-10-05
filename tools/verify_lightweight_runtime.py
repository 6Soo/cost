"""운영 DB와 파일을 읽기만 하며 통합 결과를 집계한다."""
import json
import os
import sqlite3
import sys
import threading
import urllib.request
import urllib.error
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from webapp.ledger_store import LedgerStore
from webapp.card_flow import CardFlow
from webapp import real_review


def configured_readonly_flow(database='D:/WebLedgerHost/data/board.sqlite', *, authority_path=None):
    host=Path('D:/WebLedgerHost')
    db=Path(database)
    config=json.loads((host/'config/real-review.json').read_text(encoding='utf-8-sig'))
    options=json.loads((host/'config/card-flow.json').read_text(encoding='utf-8'))
    os.environ['WEBLEDGER_TRIP_AUTHORITY']=str(authority_path or options['trip_authority_path'])
    if options.get('review_from'):
        os.environ['WEBLEDGER_REVIEW_FROM']=options['review_from']
    os.environ['WEBLEDGER_REVIEW_CONFIG']=str(host/'config/real-review.json')
    decisions=real_review.DecisionsStore.__new__(real_review.DecisionsStore)
    decisions.path=str(db)
    decisions._lock=threading.Lock()
    decisions._connect=lambda:sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,isolation_level=None)
    real_review.bind_real_review(real_review.RealReviewService(config,store=decisions))
    board=LedgerStore.__new__(LedgerStore)
    board.conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,isolation_level=None)
    board.path=db
    board._lock=threading.RLock()
    return CardFlow(board)


def main():
    host=Path('D:/WebLedgerHost')
    db=host/'data/board.sqlite'
    config=json.loads((host/'config/real-review.json').read_text(encoding='utf-8-sig'))
    flow=configured_readonly_flow(db)
    board=flow.board
    try:
        trips=board.list_trips()
        active_batches=[row[0] for row in board.conn.execute("SELECT b.batch_id FROM import_batches b JOIN import_batch_rows x ON x.batch_id=b.batch_id JOIN transactions t ON t.transaction_id=x.transaction_id WHERE t.classification_state!='preserved' GROUP BY b.batch_id")]
        visible=sum(len(flow.state(batch)['rows']) for batch in active_batches)
        result={'review_uses_board':Path(config['decisions_db_path']).resolve()==db.resolve(),
                'trip_count':len(trips),'verified_trip_options':sum(flow.trip_valid(t['tab_id']) for t in trips),
                'input_events':board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],
                'import_batches':board.conn.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0],
                'posted_rows':board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],
                'classification_counts':dict(board.conn.execute('SELECT classification_state,COUNT(*) FROM transactions GROUP BY classification_state')),
                'saved_guidance':board.conn.execute('SELECT COUNT(*) FROM review_source_guidance').fetchone()[0],
                'saved_audit_events':board.conn.execute('SELECT COUNT(*) FROM decision_events').fetchone()[0],
                'visible_input_events':visible,'review_from':os.environ.get('WEBLEDGER_REVIEW_FROM',''),
                'integrity':board.conn.execute('PRAGMA integrity_check').fetchone()[0],
                'unauthenticated_http':{}}
        for route in ('/healthz','/readyz','/import','/api/imports'):
            request=urllib.request.Request('https://ledger.foresttour.kr'+route,headers={'User-Agent':'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(request,timeout=10) as response:
                    result['unauthenticated_http'][route]=response.status
            except urllib.error.HTTPError as exc:
                result['unauthenticated_http'][route]=exc.code
        assert result['review_uses_board']
        assert result['verified_trip_options']==result['trip_count']
        if result['review_from']=='2026-04-01':
            assert result['visible_input_events']==1676
            assert result['classification_counts'].get('preserved')==3652
            from ledger.domain.direct_trip_schedule_authority import load_document
            records,_=load_document(Path(os.environ['WEBLEDGER_TRIP_AUTHORITY']))
            assert result['trip_count']>=24
            assert {t['display_key'] for t in trips}=={r.trip_code for r in records if r.is_authoritative}
        assert result['input_events']==5328
        assert result['integrity']=='ok'
        assert result['unauthenticated_http']=={'/healthz':200,'/readyz':200,'/import':401,'/api/imports':401}
        (ROOT/'.local-archive/lightweight-20261003/runtime-verification.json').write_text(
            json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('LIGHTWEIGHT_RUNTIME_VERIFIED')
    finally:
        board.conn.close()


if __name__=='__main__':
    main()
