"""운영 DB와 파일을 읽기만 하며 통합 결과를 집계한다.

집계와 판정은 분리되어 있다. `collect_runtime_status` 는 관측치만 모으고,
`failed_checks` 는 언제나 실패로 봐야 하는 조건만 판정한다. 건수나 문서 대조
결과는 관측으로 남기되 그 자체로 실패 조건이 아니다. 여행 권위 원본이 실제로
다시 확인되지 않은 여행은 런타임 결함이 아니라 대기 상태로 보고되어야 하기
때문이다.

이 모듈의 운영 접근은 진입 경로에만 있다. `configured_readonly_flow`, `http_status`,
`main` 은 운영 파일과 네트워크를 실제로 읽고, `collect_runtime_status`,
`count_valid_trips`, `failed_checks` 는 넘겨받은 값만 다룬다. 후자의 동작은
합성 대역(mock)으로만 검증한다.
"""
import json
import os
import sqlite3
import sys
import threading
import argparse
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from webapp.ledger_store import LedgerStore
from webapp.card_flow import CardFlow
from webapp import real_review


# 비로그인 상태로도 열리면 안 되는 경로. 공개 상태 코드만 허용한다.
HEALTH_ROUTES={'/healthz':200,'/readyz':200,'/import':401,'/api/imports':401}
RUNTIME_BASE='https://ledger.foresttour.kr'


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


def http_status(route, *, base=RUNTIME_BASE, opener=urllib.request.urlopen):
    """한 경로의 비로그인 상태 코드. 실패하면 상태 코드 자체를 돌려준다."""
    request=urllib.request.Request(base+route,headers={'User-Agent':'Mozilla/5.0'})
    try:
        with opener(request,timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def validated_trip_ids(flow, trips):
    """각 여행이 이번 호출에서 유효한지 한 번씩만 재고 되돌린다.

    같은 판단을 두 번 하지 않는다. 원본을 다시 읽는 판단이므로 호출마다 새로
    확인되지만, 한 번의 집계 안에서 같은 여행을 중복 조회하지는 않는다.
    """
    return {trip['tab_id']:bool(flow.trip_valid(trip['tab_id'])) for trip in trips}


def count_valid_trips(valid_by_id):
    """한 번의 검증 결과를 개수로 바꾼다."""
    verified=sum(1 for known in valid_by_id.values() if known)
    return verified, len(valid_by_id)-verified


def collect_runtime_status(flow, *, config, authority_path='', review_from='',
                           routes=(), probe=None):
    """읽기 전용 관측치를 모은다. 여기에는 실패 판정이 없다."""
    board=flow.board
    trips=board.list_trips()
    valid_by_id=validated_trip_ids(flow,trips)
    verified,invalid=count_valid_trips(valid_by_id)
    batches=[row[0] for row in board.conn.execute(
        "SELECT b.batch_id FROM import_batches b JOIN import_batch_rows x ON x.batch_id=b.batch_id "
        "JOIN transactions t ON t.transaction_id=x.transaction_id "
        "GROUP BY b.batch_id")]
    visible=sum(len(flow.state(batch)['rows']) for batch in batches)
    database=Path(board.path)
    status={
        'review_uses_board':Path(config['decisions_db_path']).resolve()==database.resolve(),
        'trip_count':len(trips),
        'verified_trip_count':verified,
        'invalid_trip_count':invalid,
        # 권위 원본 확인이 끝났다는 사실과, 그 결과로 대기 중인 여행이 있다는
        # 사실은 함께 보고된다. 대기 중인 여행이 있다고 검증이 실패한 것은 아니다.
        'schedule_validation_complete':invalid==0,
        'waiting_trips':[tab_id for tab_id,known in sorted(valid_by_id.items()) if not known],
        'input_events':board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],
        'import_batches':board.conn.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0],
        'posted_rows':board.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],
        'classification_counts':dict(board.conn.execute(
            'SELECT classification_state,COUNT(*) FROM transactions GROUP BY classification_state')),
        'saved_guidance':board.conn.execute('SELECT COUNT(*) FROM review_source_guidance').fetchone()[0],
        'saved_audit_events':board.conn.execute('SELECT COUNT(*) FROM decision_events').fetchone()[0],
        'visible_input_events':visible,
        'review_from':review_from or os.environ.get('WEBLEDGER_REVIEW_FROM',''),
        'integrity':board.conn.execute('PRAGMA integrity_check').fetchone()[0],
        'unauthenticated_http':{},
    }
    for route in routes:
        status['unauthenticated_http'][route]=(probe or http_status)(route)
    # 조회를 마치기 전까지는 전체 검증이 아니다. 확인해야 하는 경로와 실제
    # 관측된 경로가 같아야만 전체 검증이다. 일부만 조회했거나 조회가 아예
    # 없으면 미완료로 읽힌다.
    observed_routes=status['unauthenticated_http']
    status['probed_routes']=sorted(observed_routes)
    status['runtime_verification_complete']=(
        set(observed_routes)==set(HEALTH_ROUTES) and bool(authority_path))
    if authority_path:
        from ledger.domain.direct_trip_schedule_authority import load_document
        records,_=load_document(Path(authority_path))
        # 문서와 장부의 여행 대조는 관측이다. 어느 쪽이 기준인지는 런타임이 정하지 않는다.
        status['authority_records']=len(records)
        status['authority_trip_codes']=sorted({record.trip_code for record in records
                                               if record.is_authoritative})
        status['board_trip_codes']=sorted({trip['display_key'] for trip in trips})
        status['authority_matches_board']=(status['authority_trip_codes']
                                           ==status['board_trip_codes'])
    return status


def failed_checks(status):
    """어떤 데이터에서도 실패로 봐야 하는 조건의 이름만 돌려준다.

    건수나 문서 대조는 여기에 들어가지 않는다. 값이 달라진 것을 숨기지 않고
    관측으로 남기되, 그 자체로 런타임을 unhealthy로 만들지는 않는다.
    """
    failed=[]
    if not status.get('review_uses_board'):
        failed.append('review_uses_board')
    if status.get('integrity')!='ok':
        failed.append('db_integrity')
    # 실제 본 경로가 기대한 상태 코드와 다르면 보호가 깨진 것이다. 경로를
    # 아직 보지 못한 것은 여기서 실패가 아니고 미완료로 따로 표시된다.
    observed=status.get('unauthenticated_http') or {}
    if any(HEALTH_ROUTES.get(route)!=code for route,code in observed.items()):
        failed.append('unauthenticated_http_protected')
    return failed


def parse_cli_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--preflight',action='store_true',help='run metadata-only preflight without opening runtime data')
    mode.add_argument('--live',action='store_true',help='run the legacy live read-only verification (default)')
    parser.add_argument('--oauth-file',help='optional secret path for metadata-only preflight')
    parser.add_argument('--session-secret-file',help='optional secret path for metadata-only preflight')
    return parser.parse_args(argv)


def main(argv=None):
    args=parse_cli_args(argv)
    if args.preflight:
        from tools.runtime_preflight import check
        result=check(oauth_file=args.oauth_file,session_secret_file=args.session_secret_file)
        print(json.dumps(result,ensure_ascii=False))
        result['ok']=result['status']=='READY'
        return result
    host=Path('D:/WebLedgerHost')
    db=host/'data/board.sqlite'
    config=json.loads((host/'config/real-review.json').read_text(encoding='utf-8-sig'))
    flow=configured_readonly_flow(db)
    board=flow.board
    try:
        # 판정 전에 전체 경로를 모두 조회한다. 권한 문서도 함께 본다.
        result=collect_runtime_status(flow,config=config,
            authority_path=os.environ.get('WEBLEDGER_TRIP_AUTHORITY',''),
            routes=tuple(HEALTH_ROUTES))
        result['failed_checks']=failed_checks(result)
        if not result['runtime_verification_complete']:
            result['failed_checks'].append('runtime_verification_incomplete')
        result['ok']=not result['failed_checks']
        # 실패한 관측도 보고서에 그대로 남긴다. 성공 때만 기록하던 대로 숨기지 않는다.
        (ROOT/'.local-archive/lightweight-20261003/runtime-verification.json').write_text(
            json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        if result['ok']:
            print('LIGHTWEIGHT_RUNTIME_VERIFIED')
        else:
            print('LIGHTWEIGHT_RUNTIME_UNHEALTHY '+json.dumps(result['failed_checks']))
        return result
    finally:
        board.conn.close()


def cli_exit_code(result):
    """CLI는 실패한 검증에 0 이 아닌 코드로 끝난다."""
    return 0 if result.get('ok') else 1


if __name__=='__main__':
    raise SystemExit(cli_exit_code(main()))
