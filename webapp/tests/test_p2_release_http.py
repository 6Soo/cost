"""Exercise the committed release tree, without imports from the source checkout."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


# A fresh isolated interpreter is essential: ordinary correction tests import the
# app service directly and never execute the HTTP handler's lazy import.
RELEASE_HTTP = r'''
import csv, io, json, os, sys, threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
release, data = map(Path, sys.argv[1:3])
sys.path.insert(0, str(release))
os.environ.update(WEBLEDGER_UNIFIED_DB='1', WEBLEDGER_CARD_FLOW='1')
from webapp import ledger_board as board, access_control, google_oidc
from webapp.card_flow import CardFlow
from app import classification_correction
assert Path(board.__file__).is_relative_to(release)
assert Path(classification_correction.__file__).is_relative_to(release)
assert not any(Path(p).resolve() == Path(sys.argv[3]).resolve() for p in sys.path if p)
server = board.serve(port=0, db_path=data/'synthetic.sqlite', with_worker=False, seed_demo=False)
store=server.card_store
trip=store.create_trip(starts_on='2026-10-01', ends_on='2026-10-05', destination='SYNTHETIC', client_request_id='trip')
trip_id=trip['tab_id']
flow=CardFlow(store)
csvfile=io.StringIO(); writer=csv.writer(csvfile)
writer.writerow(['Issuer','Card No','Card Type','Type','Merchant','Amount','Foreign Amount','Currency','Amount KRW','Date','Post Date','Authorization Code','Cancel','Status'])
writer.writerow(['SYNTHETIC BANK','****1234','CREDIT','PURCHASE','SYNTHETIC CAFE',1000,'','',1000,'2026-10-03','2026-10-04','SYNTHETIC-1','','OK'])
batch=flow.pipeline.receive(csvfile.getvalue().encode('utf-8-sig'),'synthetic.csv')['batch_id']
source=flow.pipeline.get_batch(batch)['rows'][0]; tid=source['transaction_id']; conn=store.conn
conn.execute("UPDATE transactions SET trip_id=?,display_tab_id=?,item='현지경비',classification_source='code_inference' WHERE transaction_id=?",(trip_id,trip_id,tid))
conn.execute("INSERT INTO ledger_entries(transaction_id,batch_id,item,description,display_tab_id,trip_id,amount_krw,merchant,occurred_on,transaction_direction,source_hash,committed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
    (tid,batch,'현지경비','',trip_id,trip_id,source['amount_krw'],source['merchant'],source['approval_date'],'purchase',source['source_hash'],'synthetic'))
payload=dict(item='현지경비',display_tab_id=trip_id,trip_id=trip_id,amount_krw=source['amount_krw'],source_event_id=tid)
conn.execute("INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,'expense',?,1,?)",('card-'+tid,trip_id,json.dumps(payload)))
conn.commit()
access=access_control.attach_to_ledger_store(store);access.ensure_schema();access.ensure_owner('synthetic-owner')
cfg=google_oidc.OIDCConfig.from_env({google_oidc.ENV_CLIENT_ID:'synthetic.apps.googleusercontent.com',google_oidc.ENV_CLIENT_SECRET:'synthetic-secret',google_oidc.ENV_SESSION_SECRET:'k7Qm2Zx9Tb4Nq8Vr3Ls6Wy1Pd5Gj0Hf7Ce2Ui4Ok8Mn1',google_oidc.ENV_PUBLIC_BASE_URL:'https://synthetic.test',google_oidc.ENV_OWNER_SUB:'synthetic-owner'})
oidc=google_oidc.connect_oidc(cfg,access);board.bind_access(access);board.bind_oidc(oidc)
account=access.account('synthetic-owner')
cookie=oidc.adapter.issue_cookie({'sub':'synthetic-owner','name':'Synthetic','email':'owner@synthetic.test'},generation=account['session_generation'])
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
def request(path, payload, *, authenticated=True, csrf=True):
    headers={'Content-Type':'application/json'}
    if authenticated:headers['Cookie']=google_oidc.COOKIE_NAME+'='+cookie
    if csrf:headers['X-CSRF-Token']=board.CSRF_TOKEN
    req=Request('http://127.0.0.1:'+str(server.server_address[1])+path,data=json.dumps(payload).encode(),headers=headers)
    try:response=urlopen(req,timeout=10)
    except HTTPError as exc:response=exc
    with response:return response.status,json.loads(response.read())
tables=('transactions','ledger_entries','board_rows')
def state():return [list(conn.execute('SELECT * FROM '+table)) for table in tables]
before=state()
execution=dict(kind='connected_agent',provider='synthetic',model='synthetic',run_id='release-http-synthetic')
fix=dict(transaction_id=tid,source_hash=source['source_hash'],revision=source['revision'],trip_id=trip_id,item='식비',basis='synthetic cafe evidence',classification_source='ai_inference',execution=execution)
try:
    prefix='/api/p2-batch/corrections/'
    assert request(prefix+'preview',{'corrections':[fix]},authenticated=False)[0]==401
    assert request(prefix+'preview',{'corrections':[fix]},csrf=False)[0]==403
    status,preview=request(prefix+'preview',{'corrections':[fix]})
    assert status==200,(status,preview)
    assert preview['count']==1 and preview['recorded_targets']==1 and preview['projection_pairs']==1
    assert state()==before,'preview wrote data'
    body=dict(corrections=[fix],request_id='synthetic-release-http',preview_digest=preview['digest'])
    status,result=request(prefix+'apply',body)
    assert status==200 and result==dict(applied=1,replay=False),(status,result)
    after=state()
    assert conn.execute('SELECT item,trip_id,amount_krw,classification_source FROM transactions').fetchone()==('식비',trip_id,1000,'ai_inference')
    assert conn.execute('SELECT item,trip_id,amount_krw FROM ledger_entries').fetchone()==('식비',trip_id,1000)
    projected=json.loads(conn.execute('SELECT payload_json FROM board_rows').fetchone()[0])
    assert projected['item']=='식비' and projected['classification_source']=='ai_inference' and projected['trip_id']==trip_id and projected['amount_krw']==1000
    audit=json.loads(conn.execute("SELECT detail_json FROM change_log WHERE kind='card.classification_corrected'").fetchone()[0])
    assert audit['execution']==execution and audit['previous_ledger']['item']=='현지경비' and audit['previous_board']['payload_json']
    assert request(prefix+'apply',body)==(200,dict(applied=0,replay=True))
    assert state()==after,'replay wrote data'
    print(json.dumps(dict(preview=200,apply=200,replay=True,release_only=True,port=server.server_address[1])))
finally:
    server.shutdown();server.server_close();thread.join(5);store.close()
'''


def test_p2_http_preview_and_apply_from_exact_release(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    # Same exact-commit git archive/extraction used by the release staging scripts.
    archive = subprocess.check_output(['git', 'archive', '--format=zip', sha], cwd=repo)
    release = tmp_path / 'release'
    release.mkdir()
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        package.extractall(release)
    (release / 'DEPLOYED_COMMIT').write_text(sha, encoding='ascii')
    data = tmp_path / 'data'; data.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('WEBLEDGER_', 'PYTHONPATH'))}
    env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    result = subprocess.run([sys.executable, '-I', '-c', RELEASE_HTTP, str(release), str(data), str(repo)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report['preview'] == report['apply'] == 200 and report['release_only']
    assert report['port'] not in (8751, 8752, 8790)
