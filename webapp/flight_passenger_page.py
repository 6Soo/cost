"""Owner-only, COST-local flight passenger candidate review; reservation reads only."""

import json
import unicodedata
import os
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs

from app import flight_passenger_matching, reservation_authority

ROUTES = ('/flight-passengers', '/api/flight-passengers/candidates', '/api/flight-passengers/assign', '/api/flight-passengers/name-search')
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
    """Name-first, read-only flight booking verification UI (owner only)."""
    token = json.dumps(str(csrf or ''), ensure_ascii=True).replace('<', r'\u003c')
    return "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>항공권 예약 확인</title>\n<style>\n:root{--bg:#f8fafc;--paper:#fff;--ink:#0f172a;--mut:#475569;--line:#e2e8f0;--hover:#f1f5f9;--focus:#2563eb;--good:#047857;--warn:#a16207}\n@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--paper:#1e293b;--ink:#f8fafc;--mut:#cbd5e1;--line:#334155;--hover:#334155;--focus:#93c5fd;--good:#6ee7b7;--warn:#fbbf24}}\n*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,\"Malgun Gothic\",sans-serif}\n#flight-booking-page{max-width:1080px;margin:32px auto;padding:0 22px 64px}\n#flight-booking-page h1{font-size:26px;margin:0 0 6px}#flight-booking-page h2{font-size:17px;margin:0 0 12px}\n#flight-booking-page p{margin:0 0 14px}.fb-muted{color:var(--mut)}.fb-panel{border:1px solid var(--line);border-radius:14px;background:var(--paper);padding:20px;margin-top:18px}\n#flight-booking-page form{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}#flight-booking-page label{display:grid;gap:6px;flex:1 1 250px;font-weight:650}\n#flight-booking-page input{font:inherit;min-height:44px;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--paper);color:var(--ink);min-width:0;width:100%}\n#flight-booking-page button{font:inherit;min-height:44px;padding:10px 16px;border:1px solid var(--line);border-radius:9px;background:var(--hover);color:var(--ink);font-weight:650;cursor:pointer}\n#flight-booking-page button:disabled{opacity:.55;cursor:wait}#flight-booking-page button:focus-visible,#flight-booking-page input:focus-visible{outline:2px solid var(--focus);outline-offset:2px}\n.fb-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.fb-field{min-width:0}.fb-field small{display:block;color:var(--mut)}.fb-field strong{overflow-wrap:anywhere}\n.fb-status{font-size:12px;display:inline-block;border:1px solid var(--line);border-radius:100px;padding:3px 9px;margin:0 0 10px;color:var(--mut)}\n.fb-ticket{border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:14px;background:var(--paper)}\n.fb-ticket h3{font-size:17px;margin:0 0 12px}.fb-section{border-top:1px solid var(--line);margin-top:15px;padding-top:14px}\n.fb-note{border-left:3px solid var(--warn);padding:9px 12px;background:var(--hover);color:var(--ink);font-size:13px}\n#fb-status{min-height:24px;margin-top:12px}#fb-results{margin-top:16px}\n@media(max-width:600px){#flight-booking-page{margin:18px auto;padding:0 12px 36px}.fb-grid{grid-template-columns:minmax(0,1fr)}.fb-panel{padding:14px}#flight-booking-page form{display:grid}#flight-booking-page h1{font-size:22px}}\n</style></head><body><main id=\"flight-booking-page\">\n<h1>항공권 예약 확인</h1><p class=\"fb-muted\">탑승객 이름으로 항공권 예약과 연결된 카드 결제 내역을 확인합니다.</p>\n<section class=\"fb-panel\" aria-label=\"항공권 조회\">\n<form id=\"fb-search\"><label for=\"fb-name\">탑승객 이름<input id=\"fb-name\" name=\"name\" placeholder=\"영문 또는 한글 이름\" autocomplete=\"off\" required maxlength=\"100\"></label><button type=\"submit\" id=\"fb-submit\">예약 조회</button></form>\n<p class=\"fb-muted\" id=\"fb-status\" role=\"status\" aria-live=\"polite\">이름을 입력해 예약 내역을 조회해 주세요.</p></section>\n<section id=\"fb-results\" aria-label=\"예약 조회 결과\"></section></main>\n<script>\nconst CSRF=__CSRF__;\nconst form=document.getElementById('fb-search'),resultRoot=document.getElementById('fb-results'),status=document.getElementById('fb-status'),submit=document.getElementById('fb-submit');\nfunction text(parent,tag,value,klass){const e=document.createElement(tag);if(klass)e.className=klass;e.textContent=String(value??'');parent.append(e);return e}\nfunction field(parent,label,value){const wrap=document.createElement('div');wrap.className='fb-field';text(wrap,'small',label);text(wrap,'strong',value||'확인되지 않음');parent.append(wrap)}\nfunction showBooking(b){\nconst card=document.createElement('article');card.className='fb-ticket';\ntext(card,'span',b.cancelled?'취소·변경 근거 확인 필요':b.conflict?'원본 충돌 · 확인 필요':'예약 근거 확인','fb-status');\ntext(card,'h3',(b.booking_ref||'예약번호 미확인')+' · '+(b.passenger_name||'이름 미확인'));\nconst grid=document.createElement('div');grid.className='fb-grid';\nfield(grid,'항공권 예약번호',b.booking_ref);field(grid,'탑승객',b.passenger_name);\nfield(grid,'예약일','확인되지 않음');field(grid,'원본 근거',b.source_verified?'최신 항공권 자료':'근거 확인 필요');\ncard.append(grid);\nconst segments=document.createElement('div');segments.className='fb-section';text(segments,'h2','탑승권·여정 정보');\nif(Array.isArray(b.legs)&&b.legs.length){for(const leg of b.legs){const line=document.createElement('div');line.className='fb-grid';const entries=Object.entries(leg||{}).filter(([k,v])=>['flight_number','flight_no','origin','destination','departure','arrival','departure_date','arrival_date'].includes(k)&&v);for(const [k,v] of entries)field(line,({flight_number:'편명',flight_no:'편명',origin:'출발',destination:'도착',departure:'출발',arrival:'도착',departure_date:'출발일',arrival_date:'도착일'})[k],v);if(entries.length)segments.append(line)}}\nif(segments.children.length===1)text(segments,'p','확인된 상세 여정 정보가 없습니다.','fb-muted');card.append(segments);\nconst linked=document.createElement('div');linked.className='fb-section';text(linked,'h2','연결된 카드 결제');text(linked,'p','이 조회에서는 확정된 카드 연결 근거를 아직 검증할 수 없습니다. 카드 거래가 없거나 미결제라는 뜻은 아닙니다.','fb-note');card.append(linked);\nconst candidates=document.createElement('div');candidates.className='fb-section';text(candidates,'h2','예약일의 카드 거래 후보');text(candidates,'p','원본에 확인된 항공권 예약일이 없어 동일 날짜의 카드 거래를 안전하게 조회할 수 없습니다. 결제일이나 이메일 수신일을 예약일로 추정하지 않습니다.','fb-muted');card.append(candidates);\nreturn card}\nform.addEventListener('submit',async e=>{e.preventDefault();resultRoot.replaceChildren();submit.disabled=true;status.textContent='항공권 예약 내역을 찾고 있습니다.';\ntry{const response=await fetch('/api/flight-passengers/name-search',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF},body:JSON.stringify({name:form.elements.name.value.trim()}),cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(({'INVALID_NAME':'탑승객 이름을 확인해 주세요.','CSRF_REQUIRED':'페이지를 새로고침한 뒤 다시 조회해 주세요.','FEATURE_DISABLED':'현재 이용할 수 없습니다.','STORE_UNAVAILABLE':'항공권 원본 자료를 불러올 수 없습니다.'})[data.code]||'항공권 조회에 실패했습니다.');\nfor(const booking of data.reservations||[])resultRoot.append(showBooking(booking));status.textContent=(data.reservations||[]).length?'확인된 예약 '+data.reservations.length+'건. 카드 결제 연결은 별도 검증이 필요합니다.':'일치하는 항공권 예약이 없습니다. 영문 이름 표기와 원본 수집 상태를 확인해 주세요.';}\ncatch(error){status.textContent=error.message}finally{submit.disabled=false}});\n</script></body></html>" .replace('__CSRF__', token)

def _name_key(value):
    """Only normalize spelling and token order, never infer Korean transliteration."""
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    tokens = [''.join(ch for ch in part if ch.isalnum()) for part in text.replace('/', ' ').replace(',', ' ').split()]
    return tuple(sorted(token for token in tokens if token))


def _name_search(board, name):
    """Read the already-verified fresh passenger index without requiring tour ID."""
    from .ota_payment_review import passenger_index_for
    query = _name_key(name)
    if not query:
        return {'reservations': []}
    index = passenger_index_for(board, require_fresh=True)
    results = []
    for booking_ref, evidence in index.items():
        if not isinstance(evidence, dict) or not evidence.get('source_digests'):
            continue
        passengers = evidence.get('passengers') or []
        for person in passengers:
            if not isinstance(person, dict):
                continue
            full_name = ' '.join((str(person.get('surname') or ''), str(person.get('given_name') or ''))).strip()
            if _name_key(full_name) != query:
                continue
            results.append({'booking_ref': str(booking_ref), 'passenger_name': full_name,
                            'legs': evidence.get('legs') or [], 'cancelled': evidence.get('cancellation_status', 'NONE') != 'NONE',
                            'conflict': bool(evidence.get('conflict')), 'source_verified': True})
            break
    return {'reservations': results[:100], 'truncated': len(results) > 100}


def _passenger_evidence(board, booking_ref):
    from .ota_payment_review import passenger_index_for
    index = passenger_index_for(board, require_fresh=True)
    evidence = index.get(booking_ref)
    if not isinstance(evidence, dict) or not evidence.get('source_digests'):
        return None
    return evidence


def _candidate_result(board, booking_ref, tour_id, *, candidate_fetch=None):
    evidence = _passenger_evidence(board, booking_ref)
    if evidence is None:
        raise LookupError('VERIFIED_FLIGHT_EVIDENCE_NOT_FOUND')
    if candidate_fetch is not None:
        snapshot = candidate_fetch(tour_id)
    else:
        from .guide_airfare_review import _token_file
        token_file = _token_file(board) if hasattr(board, 'path') else None
        snapshot = reservation_authority.fetch_passenger_candidates(
            tour_id, token=reservation_authority.configured_token(token_file))
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
        passenger['cancellation_status'] = evidence.get('cancellation_status', 'NONE')
        passenger['evidence_conflict'] = bool(evidence.get('conflict'))
    result['stale_assignments'] = [item for item in result['assignments'] if item.get('stale')]
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
                 or not assignment.get('candidate_reference_id') or not assignment.get('evidence_digest'))
        # Also mark stale if evidence_digest changed
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
    if parsed.path == ROUTES[3]:
        if raw is None:
            _send(handler, {'code': 'METHOD_NOT_ALLOWED'}, 405)
            return True
        if not csrf or handler.headers.get('X-CSRF-Token') != csrf:
            _send(handler, {'code': 'CSRF_REQUIRED'}, 403)
            return True
        try:
            payload = json.loads(raw.decode('utf-8'))
            name = payload.get('name')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
                raise ValueError('INVALID_NAME')
            result = _name_search(board, name.strip())
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            _send(handler, {'code': 'INVALID_NAME'}, 422)
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
        if proposal.get('cancellation_status') != 'NONE':
            raise ValueError('PASSENGER_CANDIDATE_REQUIRED')
        assignment = flight_passenger_matching.build_user_assignment(
            proposal, candidate_reference_id=candidate_reference_id, actor='owner',
            current_source_revision=result['source_revision'],
            current_evidence_digest=result.get('evidence_digest'))
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
