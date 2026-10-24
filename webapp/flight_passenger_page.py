"""Owner-only, COST-local flight passenger candidate review; reservation reads only."""

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs

from app import flight_passenger_matching, reservation_authority

ROUTES = ('/flight-passengers', '/api/flight-passengers/candidates', '/api/flight-passengers/assign')
FEATURE_FLAG = 'WEBLEDGER_FLIGHT_PASSENGER_MATCHING'
DB_ENV = 'WEBLEDGER_FLIGHT_PASSENGER_DB'


def owns_route(path):
    return path in ROUTES


def enabled():
    return os.environ.get(FEATURE_FLAG) == '1'


def _db_path():
    value = os.environ.get(DB_ENV, '').strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve(strict=False) if path.is_absolute() else None


def _send(handler, body, status=200):
    handler._send_json(body, status)


def _page(csrf):
    token = json.dumps(str(csrf or ''), ensure_ascii=True)
    return """<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>항공권 참가자 후보</title><main style='max-width:760px;margin:32px auto;font:16px system-ui;color:#243129'>
<h1>항공권 참가자 후보</h1><p>검증된 항공권 영문 이름과 예약 정본의 후보를 비교합니다. 선택을 저장해도 실제 탑승 확인이나 예약 정본 변경은 하지 않습니다.</p>
<form id='search'><label>예약 번호 <input name='booking_ref' required></label> <label>여행 정본 ID <input name='tour_id' required></label> <button>후보 조회</button></form>
<p id='status' role='status'></p><section id='results'></section></main><script>
const csrf=""" + token + """;
const form=document.querySelector('#search'), status=document.querySelector('#status'), root=document.querySelector('#results');
form.addEventListener('submit',async event=>{event.preventDefault();root.replaceChildren();status.textContent='후보를 확인하고 있습니다.';
const values=new FormData(form), booking_ref=String(values.get('booking_ref')||''), tour_id=String(values.get('tour_id')||'');
try{const response=await fetch('/api/flight-passengers/candidates?booking_ref='+encodeURIComponent(booking_ref)+'&tour_id='+encodeURIComponent(tour_id));
const data=await response.json();if(!response.ok)throw Error(data.code||'후보를 불러오지 못했습니다.');
for(const passenger of data.passengers||[]){const article=document.createElement('article'), title=document.createElement('h2');
if(passenger.assignment){const saved=document.createElement('p');saved.textContent=passenger.assignment.stale?'저장된 COST 연결이 있지만 예약 참가자 자료가 바뀌어 다시 확인해야 합니다.':'저장된 COST 연결: '+(passenger.assignment.candidate?.name_kr||'참가자')+' · 사용자가 확인했습니다.';article.append(saved)}
title.textContent=passenger.passenger_name_en+' · '+passenger.status;article.append(title);
if(!passenger.candidates.length){const empty=document.createElement('p');empty.textContent='일치 후보가 없습니다. 이름만으로 새 고객을 만들지 않습니다.';article.append(empty)}
if(passenger.candidates.length>1){const warning=document.createElement('p');warning.textContent='같은 영문 이름의 예약 참가자가 '+passenger.candidates.length+'명 있습니다. 자료를 확인해 직접 선택해 주세요.';article.append(warning)}
for(const [index,candidate] of passenger.candidates.entries()){const label=document.createElement('label'), radio=document.createElement('input');radio.type='radio';radio.name=passenger.proposal_id;radio.value=candidate.reference_id;
const kind=candidate.kind==='lead'?'예약자':candidate.kind==='companion'?'동행인':'안내자';
label.append(radio,document.createTextNode(' '+(passenger.candidates.length>1?kind+' 후보 '+(index+1):kind)+' · '+candidate.name_kr));article.append(label,document.createElement('br'))}
if(passenger.candidates.length){const button=document.createElement('button');button.type='button';button.textContent='선택한 COST 연결 저장';button.addEventListener('click',async()=>{const selected=article.querySelector('input:checked');if(!selected){status.textContent='후보를 선택해 주세요.';return}button.disabled=true;
try{const saved=await fetch('/api/flight-passengers/assign',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({booking_ref,tour_id,proposal_id:passenger.proposal_id,candidate_reference_id:selected.value})});const result=await saved.json();if(!saved.ok)throw Error(result.code||'저장하지 못했습니다.');status.textContent='COST 연결을 저장했습니다. 실제 탑승 여부는 확인되지 않았습니다.'}
catch(error){status.textContent=error.message;button.disabled=false}});article.append(button)}root.append(article)}status.textContent=(data.passengers||[]).length?'후보 목록입니다. 사용자 확인 전에는 연결을 저장하지 않았습니다.':'항공권 탑승자 자료가 없습니다.'}
catch(error){status.textContent=error.message}});
</script></html>"""


def _passenger_evidence(board, booking_ref):
    from .ota_payment_review import passenger_index_for
    index = passenger_index_for(board)
    evidence = index.get(booking_ref)
    if not isinstance(evidence, dict) or not evidence.get('source_digests'):
        return None
    return evidence


def _candidate_result(board, booking_ref, tour_id, *, candidate_fetch=None):
    evidence = _passenger_evidence(board, booking_ref)
    if evidence is None:
        raise LookupError('VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND')
    fetch = candidate_fetch or reservation_authority.fetch_passenger_candidates
    snapshot = fetch(tour_id)
    result = flight_passenger_matching.match_booking_passengers(evidence, snapshot)
    evidence_digest = result.get('evidence_digest')
    result['assignments'] = _assignments_for(booking_ref, tour_id, result['source_revision'], evidence_digest)
    # Link assignments by proposal_id for accurate matching
    by_proposal = {item.get('proposal_id'): item for item in result['assignments']}
    for passenger in result['passengers']:
        assignment = by_proposal.get(passenger.get('proposal_id'))
        if assignment:
            assignment = dict(assignment)
            assignment['candidate'] = next((candidate for candidate in passenger['candidates']
                                            if candidate.get('reference_id') == assignment.get('candidate_reference_id')), None)
        passenger['assignment'] = assignment
    return result


def _assignments_for(booking_ref, tour_id, source_revision, evidence_digest=None):
    """Read COST confirmations and mark them stale when reservation evidence changes."""
    path = _db_path()
    if path is None or not path.is_file():
        return []
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='flight_passenger_assignments'").fetchone()
        if not table:
            return []
        rows = conn.execute(
            'SELECT assignment_json FROM flight_passenger_assignments '
            'WHERE booking_ref=? AND tour_id=? ORDER BY created_at,rowid',
            (booking_ref, tour_id)).fetchall()
    finally:
        conn.close()
    values = []
    for (encoded,) in rows:
        try:
            assignment = json.loads(encoded)
        except (TypeError, json.JSONDecodeError):
            continue
        stale = (str(assignment.get('source_revision') or '') != str(source_revision or '')
                 or not assignment.get('candidate_reference_id'))
        # Also mark stale if evidence_digest changed
        if evidence_digest and assignment.get('evidence_digest'):
            if str(assignment.get('evidence_digest') or '') != str(evidence_digest or ''):
                stale = True
        assignment['stale'] = stale
        values.append(assignment)
    return values


def _save_assignment(path, assignment):
    if path is None:
        raise ValueError('FLIGHT_PASSENGER_STORE_NOT_CONFIGURED')
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS flight_passenger_assignments(
            assignment_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE,
            booking_ref TEXT NOT NULL, tour_id TEXT NOT NULL, source_revision TEXT NOT NULL,
            assignment_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        current = conn.execute(
            'SELECT assignment_id,assignment_json FROM flight_passenger_assignments WHERE proposal_id=?',
            (assignment['proposal_id'],)).fetchone()
        encoded = json.dumps(assignment, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if current:
            if current[0] != assignment['assignment_id'] or current[1] != encoded:
                raise ValueError('PASSENGER_ASSIGNMENT_ALREADY_CONFIRMED')
            conn.commit()
            return assignment
        conn.execute('''INSERT INTO flight_passenger_assignments
            (assignment_id,proposal_id,booking_ref,tour_id,source_revision,assignment_json)
            VALUES(?,?,?,?,?,?)''',
            (assignment['assignment_id'], assignment['proposal_id'], assignment['booking_ref'],
             assignment['tour_id'], assignment['source_revision'], encoded))
        conn.commit()
        return assignment
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dispatch(handler, parsed, *, is_owner, board, raw=None, csrf='', query=None,
             candidate_fetch=None):
    if not owns_route(parsed.path):
        return False
    if not enabled():
        _send(handler, {'code': 'FEATURE_DISABLED'}, 404)
        return True
    if not is_owner:
        _send(handler, {'code': 'ACTION_FORBIDDEN'}, 403)
        return True
    if board is None:
        _send(handler, {'code': 'STORE_UNAVAILABLE'}, 503)
        return True
    query = query or parse_qs(getattr(parsed, 'query', '') or '')
    if parsed.path == ROUTES[0] and raw is None:
        handler._send(_page(csrf))
        return True
    if parsed.path == ROUTES[1] and raw is None:
        booking_ref = str((query.get('booking_ref') or [''])[0]).strip()
        tour_id = str((query.get('tour_id') or query.get('tourFldid') or [''])[0]).strip()
        if not booking_ref or not tour_id:
            _send(handler, {'code': 'INVALID_VALUE'}, 422)
            return True
        try:
            result = _candidate_result(board, booking_ref, tour_id, candidate_fetch=candidate_fetch)
        except LookupError:
            _send(handler, {'code': 'VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND'}, 404)
        except reservation_authority.AuthorityUnavailable as exc:
            _send(handler, {'code': 'RESERVATION_AUTHORITY_' + exc.code.upper()}, 503)
        except (TypeError, ValueError):
            _send(handler, {'code': 'PASSENGER_AUTHORITY_INVALID'}, 503)
        else:
            _send(handler, result)
        return True
    if parsed.path != ROUTES[2] or raw is None:
        _send(handler, {'code': 'METHOD_NOT_ALLOWED'}, 405)
        return True
    if not csrf or handler.headers.get('X-CSRF-Token') != csrf:
        _send(handler, {'code': 'CSRF_REQUIRED'}, 403)
        return True
    try:
        payload = json.loads(raw.decode('utf-8'))
        booking_ref = str(payload.get('booking_ref') or '').strip()
        tour_id = str(payload.get('tour_id') or '').strip()
        proposal_id = str(payload.get('proposal_id') or '').strip()
        candidate_reference_id = str(payload.get('candidate_reference_id') or '').strip()
        result = _candidate_result(board, booking_ref, tour_id, candidate_fetch=candidate_fetch)
        proposal = next((item for item in result['passengers']
                         if item['proposal_id'] == proposal_id), None)
        if proposal is None:
            raise ValueError('PASSENGER_CANDIDATE_REQUIRED')
        assignment = flight_passenger_matching.build_user_assignment(
            proposal, candidate_reference_id=candidate_reference_id, actor='owner',
            current_source_revision=result['source_revision'])
        saved = _save_assignment(_db_path(), assignment)
    except LookupError:
        _send(handler, {'code': 'VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND'}, 404)
    except reservation_authority.AuthorityUnavailable as exc:
        _send(handler, {'code': 'RESERVATION_AUTHORITY_' + exc.code.upper()}, 503)
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        code = str(exc) if str(exc).startswith('PASSENGER_') or str(exc).startswith('FLIGHT_') else 'INVALID_VALUE'
        _send(handler, {'code': code}, 409 if code != 'INVALID_VALUE' else 422)
    else:
        _send(handler, {'code': 'OK', 'assignment': saved})
    return True
