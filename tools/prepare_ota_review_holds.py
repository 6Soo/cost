"""이번에 검토한 OTA 보류 16건을 기존 거래 변경 없이 저장한다."""
import datetime,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import Pipeline
from app.review_holds import active_holds
from tools.recover_history_rules import current_rows
from tools.verify_operational_backup_restore import backup_database,database_state
from tools.verify_lightweight_runtime import configured_readonly_flow


def main():
    db=Path('D:/WebLedgerHost/data/board.sqlite')
    out=ROOT/'.local-archive/ota-rematch-20261004'
    evidence=json.loads((ROOT/'docs/handoff/2026-10-01/operational-backup-restore-evidence.json').read_text(encoding='utf-8'))
    age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(evidence['recorded_at'])).total_seconds()
    if not 0<=age<=300 or not evidence['live_state_unchanged']:raise RuntimeError('FRESH_VERIFIED_BACKUP_REQUIRED')
    before=database_state(db)
    rows=current_rows(db)
    matches=json.loads((ROOT/'.local-archive/lightweight-20261003/rule-recovery/mail-matches.json').read_text(encoding='utf-8'))['matches']
    cancelled={m['source_hash'] for m in matches if m.get('reservation_status')=='cancelled'}
    plan=[]
    for row in rows:
        if row['trip_id']:continue
        if not any(x in row['merchant'].upper() for x in ('TRIP.COM','트립닷컴','AGODA','KLOOK')):continue
        if row['source_hash'] in cancelled:
            kind='cancelled';reason='취소 메일이 확인된 예약입니다. 원결제와 실제 카드 환불을 대조해 정산하며 여행 비용에서는 분리합니다.'
        elif (row['approval_date'],row['amount_krw'])==('2026-07-11',119965) and row['decided']:
            kind='cancelled';reason='사용자가 취소한 결제라고 확인했습니다. 여행에서 분리하고 원결제와 실제 환불을 대조합니다.'
        elif (row['approval_date'],row['amount_krw'])==('2026-06-08',1056200) and row['decided']:
            kind='refund_pending';reason='일부 탑승객만 취소했습니다. 메일의 환불액은 760,200원이지만 실제 환불은 미확인입니다. 환불 원행 확인 후 잔여 이용 비용을 나눕니다.'
        elif (row['approval_date'],row['amount_krw'])==('2026-06-11',146018) and row['decided']:
            kind='user_hold';reason='사용자가 실제 이용 여부를 기억하지 못해 보류했습니다. 50% 위약금 안내만으로 취소나 환불을 확정하지 않습니다.'
        elif (row['approval_date'],row['amount_krw'])==('2026-07-14',760344):
            kind='evidence_pending';reason='같은 금액의 호텔 카드 사전승인과 취소 메일은 있지만 실제 결제 연결이 미확정입니다. 카드 결제·취소 원행을 확인합니다.'
        else:raise RuntimeError('UNREVIEWED_OTA_ROW')
        plan.append((row['transaction_id'],row['source_hash'],kind,reason))
    if len(plan)!=16:raise RuntimeError('REVIEW_HOLD_SCOPE_CHANGED')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=db.parent/'backups'/('ota-holds-'+stamp);folder.mkdir()
    backup_database(db,folder/'board.sqlite');clone=folder/'rehearsal.sqlite';backup_database(db,clone)
    if database_state(folder/'board.sqlite')!=before:raise RuntimeError('BACKUP_MISMATCH')
    conn=sqlite3.connect(clone,isolation_level=None);pipe=Pipeline(conn)
    try:
        conn.execute('BEGIN IMMEDIATE')
        for entry in plan:
            old=conn.execute('SELECT transaction_id,source_hash,kind,reason FROM transaction_review_holds WHERE transaction_id=?',(entry[0],)).fetchone()
            if old and old!=entry:raise RuntimeError('EXISTING_HOLD_CHANGED')
            conn.execute('INSERT OR IGNORE INTO transaction_review_holds VALUES (?,?,?,?)',entry)
        conn.commit()
        first=active_holds(conn)
        for entry in plan:conn.execute('INSERT OR IGNORE INTO transaction_review_holds VALUES (?,?,?,?)',entry)
        if active_holds(conn)!=first:raise RuntimeError('REPEATED_HOLD_CHANGED')
    finally:conn.close()
    after=database_state(clone)
    if any(after.get(k)!=v for k,v in before.items()):raise RuntimeError('EXISTING_TABLE_CHANGED')
    flow=configured_readonly_flow(clone)
    try:
        seen={}
        for batch, in flow.board.conn.execute('SELECT batch_id FROM import_batches'):
            for row in flow.pipeline.preview(batch,review_from='2026-04-01',trip_validator=flow.trip_valid,tab_validator=flow.tab_valid)['rows']:
                if row['transaction_id'] in first:seen[row['transaction_id']]=row.get('blocked')
        if len(seen)!=16 or set(seen.values())!={'review_hold'}:raise RuntimeError('HELD_ROW_COULD_BE_BOOKED')
    finally:flow.board.conn.close()
    if database_state(db)!=before:raise RuntimeError('LIVE_WRITER_CHANGED_DATA')
    try:
        backup_database(clone,db)
        if database_state(db)!=after:raise RuntimeError('DEPLOYED_DATABASE_DIFFERS')
    except Exception:
        backup_database(folder/'board.sqlite',db);raise
    result={'status':'deployed','holds':16,'cancelled':sum(p[2]=='cancelled' for p in plan),
            'backup':str(folder),'all_existing_tables_unchanged':True,'held_rows_blocked_in_preview':True,'new_ledger_entries':0}
    (out/'review-holds-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
