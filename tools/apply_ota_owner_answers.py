"""확인된 이번 OTA 답변만 복구 사본에서 검증한 뒤 운영에 반영한다."""
import datetime
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.ota_mail import load_messages, extract_mail, shared_lodging_period
from tools.recover_history_rules import current_rows
from tools.verify_operational_backup_restore import backup_database, database_state
from tools.verify_lightweight_runtime import configured_readonly_flow
from ledger.domain.direct_trip_schedule_authority import validate_document, SCHEMA_VERSION, END_SEMANTICS
from webapp.ledger_store import LedgerStore
from app import Pipeline

HOST=Path('D:/WebLedgerHost')
OUTPUT=ROOT/'.local-archive/ota-rematch-20261004'
MAIL=ROOT/'.local-archive/lightweight-20261003/rule-recovery'


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')


def schedule_sources():
    source=ROOT/'.local-archive/lightweight-20261003/remaining-assignment/reserve-public-tours-20261003.json'
    tours=json.loads(source.read_text(encoding='utf-8'))['tours']
    result=[]
    for fldid,region,code,start,end in (
        ('fMgt','노리쿠라','0801_노리쿠라','2026-08-01','2026-08-05'),
        ('fONv','군산','0827_군산','2026-08-27','2026-08-29'),
        ('fMlf','가루이자와','0722_가루이자와','2026-07-22','2026-07-26'),
        ('','화순','0823_화순','2026-08-23','2026-08-25')):
        record=dict(trip_code=code,event_year=2026,starts_on=start,ends_on=end,region=region,
                    authority_kind='explicit_trip_registry' if fldid else 'user_confirmed_schedule',
                    authority_status='authoritative',end_semantics=END_SEMANTICS)
        if fldid:
            matches=[t for t in tours if t['fldid']==fldid]
            if len(matches)!=1 or (matches[0]['date'],matches[0]['returnDate'])!=(start,end):
                raise RuntimeError('RESERVE_SCHEDULE_CONFLICT')
            basis={'source_file_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                   'source_url':matches[0]['url'],'fldid':fldid,'starts_on':start,'ends_on':end}
        else:
            basis={'answered_on':'2026-10-04','question':'8월 23~25일, 모두 화순 여행인가요?',
                   'answer':'ㅇㅇ','starts_on':start,'ends_on':end}
        snapshot={'schema_version':'owner-trip-schedule-v1','schedule':record,'basis':basis}
        raw=encoded(snapshot);digest=hashlib.sha256(raw).hexdigest()
        path=HOST/'data/evidence'/('owner-schedule-'+digest[:24]+'.json')
        result.append((dict(record,source_locator=str(path)+'#schedule',source_sha256=digest),path,raw))
    return result


def answer_plan(rows):
    report=json.loads((MAIL/'mail-matches.json').read_text(encoding='utf-8'))
    by_source={m['source_hash']:m for m in report['matches']}
    facts=[f for m in load_messages(MAIL).values() if (f:=extract_mail(m))]
    windows=[('0801_노리쿠라','2026-08-01','2026-08-05'),
             ('0827_군산','2026-08-27','2026-08-29'),
             ('0823_화순','2026-08-23','2026-08-25'),
             ('0722_가루이자와','2026-07-22','2026-07-26')]
    result=[]
    for row in rows:
        if row['user_confirmed'] or row['classification_state']=='preserved' or row['trip_id']:
            continue
        if not any(x in row['merchant'].upper() for x in ('TRIP.COM','트립닷컴','AGODA','BOOKING')):
            continue
        match=by_source.get(row['source_hash'],{})
        if match.get('reservation_status')=='cancelled' or match.get('period_conflict'):
            continue
        shared=None
        period=match.get('period')
        if not period and any(x in row['merchant'].upper() for x in ('TRIP.COM','트립닷컴')):
            shared=shared_lodging_period(facts,paid_on=row['approval_date'],amount_krw=row['amount_krw'])
            period=shared['period'] if shared else None
        if not period or match.get('item', '숙박비')!='숙박비':
            continue
        targets=[code for code,start,end in windows if start<=period['starts_on']<=period['ends_on']<=end]
        if len(targets)!=1:
            continue
        basis=('같은 결제일·금액 후보 모두의 이용기간과 숙박 종류가 일치. 예약번호 연결은 보류.'
               if shared else '인증된 예약 메일의 명시 이용기간과 여행 일정 대조.')
        result.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
                           expected_revision=row['revision'],trip_code=targets[0],period=period,
                           item='숙박비',description='숙박 · 예약번호 연결 보류' if shared else row['description'],
                           note='2026-10-04 사용자 답변 적용. '+basis,
                           evidence_digests=shared['source_digests'] if shared else match.get('evidence_digests',[match.get('source_sha256')]),
                           booking_number_held=bool(shared)))
    flight_messages=load_messages(OUTPUT)
    flight_facts=[f for m in flight_messages.values() if (f:=extract_mail(m))]
    for day,amount,reference in [('2026-06-08',1056200,'1400827452750459'),
                                 ('2026-07-15',1472600,'1400828335448251')]:
        candidates=[r for r in rows if r['approval_date']==day and r['amount_krw']==amount
                    and any(x in r['merchant'].upper() for x in ('TRIP.COM','트립닷컴'))]
        receipts=[f for f in flight_facts if f['booking_ref']==reference and f['paid_on']==day
                  and f['paid_amount_krw']==amount+4000 and f['item']=='항공료']
        if len(candidates)!=1 or len(receipts)!=1:
            raise RuntimeError('CONFIRMED_FLIGHT_DISCOUNT_EVIDENCE_MISMATCH')
        row=candidates[0]
        if row['user_confirmed']:continue
        result.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
                           expected_revision=row['revision'],trip_code='0801_노리쿠라',
                           period={'starts_on':'2026-08-01','ends_on':'2026-08-05'},item='항공료',
                           description='서울↔고마쓰 왕복 · 예약 '+reference,
                           note='2026-10-04 사용자 확인: 노리쿠라 항공권, 카드 할인 4,000원. '
                                '메일 총액 '+str(amount+4000)+'원, 실제 카드 결제 '+str(amount)+'원. '
                                '원본 결제액 보존. 메일 근거 '+receipts[0]['source_sha256'],
                           evidence_digests=[receipts[0]['source_sha256']],booking_number_held=False))
    return result


def apply_answers(db, plan, authority_path):
    flow=configured_readonly_flow(db,authority_path=authority_path)
    trips={t['display_key']:t['tab_id'] for t in flow.board.list_trips()}
    pipe=Pipeline(sqlite3.connect(db,isolation_level=None))
    try:
        for entry in plan:
            row=pipe.store.conn.execute('SELECT source_hash,revision,user_confirmed FROM transactions WHERE transaction_id=?',
                                        (entry['transaction_id'],)).fetchone()
            if row!=(entry['source_hash'],entry['expected_revision'],entry.get('expected_confirmed',0)):
                raise RuntimeError('OWNER_ANSWER_SOURCE_CHANGED')
            target=trips[entry['trip_code']] if entry['trip_code'] else ''
            pipe.save_decision(entry['transaction_id'],entry['expected_revision'],item=entry['item'],
                               description=entry['description'],trip_id=target,display_tab_id=target or 'unclassified',
                               note=entry['note'],reuse_rule=False,
                               request_id=entry.get('request_prefix','ota-owner-20261004-')+entry['transaction_id'],
                               trip_validator=flow.trip_valid,tab_validator=flow.tab_valid)
        after=current_rows(db)
        for batch, in pipe.store.conn.execute('SELECT batch_id FROM import_batches').fetchall():
            pipe.classify_batch(batch,trip_resolver=flow.retail_trip,review_from='2026-04-01',
                                transaction_ids=[p['transaction_id'] for p in plan])
        if after!=current_rows(db):
            raise RuntimeError('CONFIRMED_ANSWERS_NOT_STABLE')
        if any(not flow.trip_valid(t) for t in trips.values()):
            raise RuntimeError('TRIP_EVIDENCE_INVALID')
    finally:
        pipe.store.conn.close();flow.board.conn.close()


def main():
    db=HOST/'data/board.sqlite';authority=HOST/'config/trip-authority.json'
    proof=json.loads((ROOT/'docs/handoff/2026-10-01/operational-backup-restore-evidence.json').read_text(encoding='utf-8'))
    age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(proof['recorded_at'])).total_seconds()
    if not 0<=age<=300 or not proof['live_state_unchanged']:
        raise RuntimeError('FRESH_VERIFIED_BACKUP_REQUIRED')
    before=database_state(db);old_rows=current_rows(db)
    hold='--hold-refunded-flight' in sys.argv
    followup='--followup-answers' in sys.argv
    if followup:
        plan=[]
        for day,amount,description,note in (
            ('2026-06-08',1056200,'항공권 일부 취소 · 환불 원행 확인 대기',
             '2026-10-04 사용자 확인: 일부 탑승객만 취소, 나머지는 노리쿠라에서 사용. '
             '환불 완료 메일은 760,200원. 실제 환불 금액과 카드 환불 원행 확인 대기. '
             '잔여 이용 비용과 취소·환불 부분을 나누기 전 전체 여행 배정은 보류. 원결제 보존.'),
            ('2026-07-11',119965,'숙박 취소 · 여행에서 분리',
             '2026-10-04 사용자 확인: 이 119,965원은 취소한 숙박 결제. 여행에서 분리. '
             '같은 금액의 예약 후보 두 개 중 개별 예약번호는 확정하지 않음. 원결제와 환불 별도 보존.'),
            ('2026-06-11',146018,'Agoda 숙박 · 실제 이용 여부 확인 보류',
             '2026-10-04 사용자 선택: 실제 이용 여부가 불확실하여 보류. 군산 8월 27~29일 예약의 '
             '50% 위약금과 73,009원 환불 가능 안내는 취소 완료 증거가 아님. '
             '사용자 재확인 전 여행 자동 배정 금지. 원결제 146,018원 보존.')):
            candidates=[r for r in old_rows if r['approval_date']==day and r['amount_krw']==amount
                        and any(x in r['merchant'].upper() for x in ('트립닷컴','AGODA'))]
            if len(candidates)!=1:raise RuntimeError('FOLLOWUP_CARD_ROW_AMBIGUOUS')
            row=candidates[0]
            if row['description']==description:continue
            if row['user_confirmed'] and row['description']!='항공권 취소·환불 확인 · 여행 배정 보류':
                raise RuntimeError('EXISTING_OWNER_EDIT_PROTECTED')
            plan.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
                expected_revision=row['revision'],expected_confirmed=row['user_confirmed'],
                trip_code='',item=row['item'],description=description,note=note,
                booking_number_held=True,request_prefix='ota-followup-20261004-'))
    elif hold:
        from app.ota_mail import authenticated_headers,body_text
        import unicodedata,re
        message=load_messages(OUTPUT)['19fba21da8354e2f']
        auth=authenticated_headers(message,('trip.com',))
        text=''.join(c for c in body_text(message['payload']) if unicodedata.category(c)!='Cf')
        if not auth or '환불 완료' not in auth[0]['subject'] or '1400827452750459' not in text or not re.search(r'760,200\s*원',text):
            raise RuntimeError('REFUND_SOURCE_NOT_VERIFIED')
        candidates=[r for r in old_rows if r['approval_date']=='2026-06-08' and r['amount_krw']==1056200
                    and '트립닷컴' in r['merchant']]
        if len(candidates)!=1:raise RuntimeError('REFUNDED_CARD_ROW_AMBIGUOUS')
        row=candidates[0]
        if row['description']=='항공권 취소·환불 확인 · 여행 배정 보류':
            print(json.dumps({'status':'noop'}));return
        with sqlite3.connect(db) as conn:
            decision=conn.execute('SELECT note FROM review_decisions WHERE transaction_id=? AND revision=?',
                                  (row['transaction_id'],row['revision'])).fetchone()
        if not decision or not decision[0].startswith('2026-10-04 사용자 확인: 노리쿠라 항공권, 카드 할인'):
            raise RuntimeError('EXISTING_OWNER_EDIT_PROTECTED')
        plan=[dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
                   expected_revision=row['revision'],expected_confirmed=1,trip_code='',item='항공료',
                   description='항공권 취소·환불 확인 · 여행 배정 보류',booking_number_held=False,
                   request_prefix='ota-refund-hold-20261004-',
                   note='예약 1400827452750459: 8월 1일 760,200원 환불 완료 메일 확인. '
                        '전부 취소 또는 일부 탑승객 취소인지 사용자 답변 대기. 취소·환불을 여행에서 분리하라는 '
                        '사용자 원칙에 따라 배정 보류. 실제 카드 환불 원행은 현재 미확보. 원결제 1,056,200원 보존.')]
    else:
        plan=answer_plan(old_rows)
    if not plan:
        print(json.dumps({'status':'noop','new_ledger_entries':0}));return
    if (not hold and not followup and (len(plan)!=23 or sum(p['booking_number_held'] for p in plan)!=6)) or (hold and len(plan)!=1) or (followup and not 1<=len(plan)<=3):
        raise RuntimeError('ANSWER_SCOPE_DIFFERS_FROM_REVIEWED_ROWS')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=HOST/'data/backups'/('ota-answers-'+stamp);backup.mkdir()
    backup_database(db,backup/'board.sqlite')
    if database_state(backup/'board.sqlite')!=before:
        raise RuntimeError('BACKUP_MISMATCH')
    original_authority=authority.read_bytes();(backup/'trip-authority.json').write_bytes(original_authority)
    document=json.loads(original_authority);sources=schedule_sources()
    created_sources=[]
    try:
        for record,path,raw in sources:
            existing=[r for r in document['records'] if r['trip_code']==record['trip_code']]
            if existing and existing!=[record]:
                raise RuntimeError('EXISTING_SCHEDULE_CONFLICT')
            if path.exists() and path.read_bytes()!=raw:
                raise RuntimeError('SCHEDULE_SOURCE_CONFLICT')
            if not path.exists():path.write_bytes(raw);created_sources.append(path)
            if not existing:document['records'].append(record)
        validate_document(document)
        staged=backup/'authority-staged.json';staged.write_bytes(encoded(document))
        clone=backup/'rehearsal.sqlite';backup_database(db,clone)
        os.environ['WEBLEDGER_UNIFIED_DB']='1'
        board=LedgerStore(clone,seed_demo=False)
        try:
            for record,_,_ in sources:
                board.create_trip(starts_on=record['starts_on'],ends_on=record['ends_on'],
                    destination=record['region'],display_key=record['trip_code'],source_sha256=record['source_sha256'],
                    client_request_id='ota-schedule-20261004-'+record['trip_code'],actor='owner')
        finally:board.close()
        apply_answers(clone,plan,staged)
        after_rows={r['transaction_id']:r for r in current_rows(clone)}
        scope={p['transaction_id'] for p in plan}
        mutable={'classification_state','classification_source','classification_basis','item','description',
                 'display_tab_id','trip_id','user_confirmed','revision','decided_at'}
        for old in old_rows:
            new=after_rows[old['transaction_id']]
            fields=set(old)-mutable if old['transaction_id'] in scope else set(old)
            if any(old[k]!=new[k] for k in fields):raise RuntimeError('SOURCE_OR_PROTECTED_TRANSACTION_CHANGED')
        after=database_state(clone)
        for table in ('board_rows','board_revisions','owner_profile','ledger_entries','review_source_guidance',
                      'import_batch_rows','cost_classification_rules'):
            if before.get(table)!=after.get(table):raise RuntimeError('PROTECTED_TABLE_CHANGED:'+table)
        with sqlite3.connect(backup/'board.sqlite') as original, sqlite3.connect(clone) as proposed:
            columns=[r[1] for r in original.execute('PRAGMA table_info(import_batches)') if r[1]!='parsed_at']
            query='SELECT '+','.join(columns)+' FROM import_batches ORDER BY batch_id'
            if original.execute(query).fetchall()!=proposed.execute(query).fetchall():
                raise RuntimeError('ORIGINAL_IMPORT_BATCH_CHANGED')
        with sqlite3.connect(clone) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('INTEGRITY_FAILED')
        if database_state(db)!=before:raise RuntimeError('LIVE_WRITER_CHANGED_DATA')
        authority.write_bytes(encoded(document));backup_database(clone,db)
        if database_state(db)!=after:raise RuntimeError('DEPLOYED_DATABASE_DIFFERS')
        result=dict(status='deployed',assigned=0 if hold or followup else len(plan),booking_numbers_held=0 if hold or followup else 6,
                    new_trips=0 if hold or followup else 4,refund_confirmation_pending=hold or followup,
                    backup=str(backup),source_rows_unchanged=True,outside_scope_unchanged=True,
                    repeated_classification_stable=True,new_ledger_entries=0)
        prefix='followup-answers' if followup else 'refund-hold' if hold else 'owner-answers'
        (OUTPUT/(prefix+'-plan.json')).write_bytes(encoded(plan))
        (OUTPUT/(prefix+'-result.json')).write_bytes(encoded(result));print(json.dumps(result))
    except Exception:
        backup_database(backup/'board.sqlite',db);authority.write_bytes(original_authority)
        if database_state(db)!=before:raise RuntimeError('ROLLBACK_FAILED')
        # 미사용 근거 파일은 원본 보존 원칙에 따라 유지한다.
        raise


if __name__=='__main__':main()
