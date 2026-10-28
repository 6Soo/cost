"""Owner-only, bounded trip review; financial writes use the existing decision API."""
from __future__ import annotations

import hashlib
import json
import re

from app.provisional_assignment import card_trip_candidates, rank_trip_candidates, POLICY_VERSION


FILTERS = {
    "all": "1=1",
    "provisional": "t.classification_source='inference' AND COALESCE(t.trip_id,'')!=''",
    "unassigned": "COALESCE(t.trip_id,'')=''",
    "manual": "t.classification_source='user_decision'",
}


def authoritative_trips(flow):
    return [dict(trip, trip_id=trip["tab_id"]) for trip in flow.board.list_trips()
            if flow.trip_valid(trip["tab_id"])]


def read_page(flow, batch_id, *, offset=0, state="all", generation=""):
    conn = flow.pipeline.store.conn
    if conn.execute("SELECT 1 FROM import_batches WHERE batch_id=?", (batch_id,)).fetchone() is None:
        raise ValueError("BATCH_NOT_FOUND")
    trips = authoritative_trips(flow)
    from .card_flow import _google_nets
    nets = _google_nets()
    financial_holds = flow.ota_group_holds()
    trip_ids = {trip["trip_id"] for trip in trips}
    watermark = conn.execute("SELECT COALESCE(MAX(entry_id),0) FROM change_log").fetchone()[0]
    token = hashlib.sha256(json.dumps([batch_id, watermark, trips, nets, POLICY_VERSION],
                                      sort_keys=True, default=str).encode()).hexdigest()
    if generation and generation != token:
        raise ValueError("SOURCE_CHANGED")
    where = (" FROM transactions t JOIN import_batch_rows b USING(transaction_id) WHERE b.batch_id=? "
             "AND t.classification_state!='preserved' AND " + FILTERS[state])
    total = conn.execute("SELECT COUNT(*)" + where, (batch_id,)).fetchone()[0]
    measured = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(json_extract(c.detail_json,'$.changed')),0) FROM change_log c "
        "WHERE c.kind='trip_assignment.reviewed' AND EXISTS "
        "(SELECT 1 FROM import_batch_rows b WHERE b.batch_id=? AND b.transaction_id=c.subject)", (batch_id,)).fetchone()
    fields = ("transaction_id", "source_hash", "revision", "merchant", "approval_date", "item",
              "description", "trip_id", "display_tab_id", "classification_source", "classification_basis")
    values = conn.execute("SELECT " + ",".join("t." + field for field in fields) + where +
                          " ORDER BY COALESCE(t.approval_date,''),t.transaction_id LIMIT 20 OFFSET ?",
                          (batch_id, offset)).fetchall()
    from app.review import correction_protection_reason
    items = []
    for value in values:
        row = dict(zip(fields, value))
        protection = correction_protection_reason(flow.pipeline.store, row["transaction_id"], row["source_hash"])
        protection = protection or ("OTA_FINANCIAL_HOLD" if row["transaction_id"] in financial_holds else "")
        manual = row["classification_source"] in ("user_decision", "user_exception", "owner_booking")
        target = row["trip_id"] or ""
        decision = rank_trip_candidates(card_trip_candidates(row, trips, nets=nets), trips=trips,
                                         financial_hold=bool(protection))
        if manual:
            decision = dict(decision, status="USER_CONFIRMED" if target else "MANUAL_UNASSIGNED", trip_id=target,
                            reason="사용자 결정 보호" + (" · 보류 사유 유지" if protection else ""))
        elif protection:
            decision = dict(decision, status="FINANCIAL_HOLD", trip_id="", reason="금융·원본 보호 유지")
        elif target in trip_ids:
            decision = dict(decision, status="AUTO_PROVISIONAL" if row["classification_source"] == "inference"
                            else "AUTHORITY_VERIFIED", trip_id=target,
                            reason=row["classification_basis"] or "기존 여행 배정")
        elif target:
            decision = dict(decision, status="CONFLICT_REVIEW", trip_id="", reason="배정된 여행 권위 확인 필요")
        else:
            # A read never assigns. Candidate evidence and persisted attribution are separate.
            decision = dict(decision, status="CONFLICT_REVIEW" if decision["status"] == "CONFLICT_REVIEW"
                            else "UNASSIGNED_NO_VALID_TRIP", trip_id="",
                            reason="아직 저장된 여행 배정 없음 · 후보를 검토해 선택해 주세요")
        row.pop("source_hash")
        row.update(decision=decision, protected=bool(protection),
                   can_propose=row["classification_source"] == "user_decision" and not protection and target in trip_ids)
        items.append(row)
    return {"items": items, "total": total, "offset": offset, "has_more": offset + 20 < total,
            "generation": token, "trips": [{"id": trip["trip_id"], "name": trip["display_key"]} for trip in trips],
            "metrics": {"reviewed_provisional": measured[0], "corrected_provisional": measured[1],
                        "correction_rate": measured[1] / measured[0] if measured[0] else None,
                        "scope": "observed_owner_reviews_only"},
            "policy_version": POLICY_VERSION}


def dispatch(handler, parsed, *, board, query, raw, csrf):
    match = re.fullmatch(r"/api/imports/([^/]+)/trip-review(?:/(proposals|hold))?", parsed.path)
    if not match:
        return False
    from . import ledger_board
    if ledger_board.current_role() != "owner":
        handler._send_json({"code": "OWNER_ONLY"}, 403)
        return True
    method = getattr(handler, "command", "POST" if raw is not None else "GET")
    if method not in ("GET", "POST") or (raw is not None and not match[2]):
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    if raw is not None and (not csrf or handler.headers.get("X-CSRF-Token") != csrf):
        handler._send_json({"code": "CSRF_REQUIRED"}, 403)
        return True
    from .card_flow import CardFlow
    from app import trip_correction_review
    try:
        batch_id = match[1]
        offset_values = query.get("offset") or ["0"]
        offset = int(offset_values[0])
        if len(offset_values) != 1 or not 0 <= offset <= 100000:
            raise ValueError("INVALID_OFFSET")
        flow = CardFlow(board)
        store = flow.pipeline.store
        if raw is None:
            if match[2] == 'hold':
                handler._send_json({'code': 'METHOD_NOT_ALLOWED'}, 405)
                return True
            if match[2] == 'proposals':
                result = trip_correction_review.pending_proposals(store, batch_id, offset=offset)
            else:
                states = query.get("state") or ["all"]
                generations = query.get("generation") or [""]
                if len(states) != 1 or states[0] not in FILTERS or len(generations) != 1:
                    raise ValueError("INVALID_FILTER")
                result = read_page(flow, batch_id, offset=offset, state=states[0], generation=generations[0])
        else:
            payload = json.loads(raw.decode("utf-8"))
            if match[2] == 'hold':
                if payload.get('confirmed') is not True:
                    raise ValueError('EXPLICIT_APPROVAL_REQUIRED')
                identity = str(payload.get('transaction_id') or '')
                if identity in flow.ota_group_holds():
                    raise ValueError('CORRECTION_STALE_OR_PROTECTED')
                result = trip_correction_review.hold_for_review(store, batch_id,
                    transaction_id=identity, revision=payload.get('revision'), request_id=payload.get('request_id'))
            elif payload.get("action") == "propose":
                result = trip_correction_review.propose_from_current_decisions(
                    store, batch_id, payload.get("transaction_ids"), protected_transaction_ids=flow.ota_group_holds())
            elif payload.get("action") == "approve" and payload.get("confirmed") is True:
                result = trip_correction_review.approve_stored_proposal(
                    store, batch_id, str(payload.get("proposal_id") or ""),
                    approved_by="owner", trips=authoritative_trips(flow), protected_transaction_ids=flow.ota_group_holds())
            else:
                raise ValueError("EXPLICIT_APPROVAL_REQUIRED")
        handler._send_json(result)
    except (ValueError, KeyError, TypeError) as exc:
        code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[A-Z_:]+", str(exc)) else "INVALID_INPUT"
        handler._send_json({"code": code}, 409 if code in ("SOURCE_CHANGED", "CORRECTION_STALE_OR_PROTECTED") else 422)
    return True


def render(csrf):
    return """<details id="provisional-trip-review"><summary>잠정 여행 배정 · 검토와 교정</summary>
<p>여행 배정과 결제·환불 확정은 별도입니다. 보류 사유는 유지됩니다.</p>
<label>카드 자료 <select data-trip-batch></select></label>
<label>검토 상태 <select data-trip-state><option value="all">전체</option><option value="provisional">자동 잠정</option><option value="unassigned">미배정·충돌</option><option value="manual">사용자 확정</option></select></label>
<p data-trip-message role="status"></p><ol data-trip-items></ol>
<button type="button" data-trip-prev>이전 20건</button><button type="button" data-trip-next>다음 20건</button>
<button type="button" data-trip-propose>선택한 교정으로 제한 규칙 제안</button><div data-trip-proposals></div>
</details><style>
#provisional-trip-review{margin:16px 0;border:1px solid var(--shell-line);border-radius:12px;padding:16px}
#provisional-trip-review [data-trip-items]{list-style:none;padding:0;display:grid;gap:12px}
#provisional-trip-review li{border:1px solid var(--shell-line);border-radius:12px;padding:12px;min-width:0}
#provisional-trip-review h3,#provisional-trip-review p{overflow-wrap:anywhere}
#provisional-trip-review form{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
#provisional-trip-review input,#provisional-trip-review select{min-width:0;max-width:100%}
#provisional-trip-review form input,#provisional-trip-review form select{flex:1 1 140px}
#provisional-trip-review button{min-height:44px;white-space:normal}
</style>""" + CLIENT_SCRIPT.replace("__CSRF__", json.dumps(csrf))


CLIENT_SCRIPT = r"""<script>(()=>{
const root=document.querySelector('#provisional-trip-review');if(!root)return;
const csrf=__CSRF__,batch=root.querySelector('[data-trip-batch]'),filter=root.querySelector('[data-trip-state]'),list=root.querySelector('[data-trip-items]'),message=root.querySelector('[data-trip-message]'),proposals=root.querySelector('[data-trip-proposals]');
let offset=0,generation='',busy=false,loaded=false,version=0,tripNames=new Map();
function setBusy(value){busy=value;batch.disabled=value;filter.disabled=value;}
const text=(tag,value)=>{const node=document.createElement(tag);node.textContent=value;return node};
async function call(url,body){const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{});const value=await response.json();if(!response.ok)throw Error(value.code||'UNAVAILABLE');return value}
const endpoint=()=>'/api/imports/'+encodeURIComponent(batch.value)+'/trip-review';
function fail(error){message.textContent=error.message==='SOURCE_CHANGED'?'자료가 갱신됐습니다. 첫 페이지에서 다시 확인해 주세요.':error.message;if(error.message==='SOURCE_CHANGED'){offset=0;generation='';list.replaceChildren();loaded=false}}
async function load(){if(busy||!batch.value)return;setBusy(true);const current=++version,url=endpoint();message.textContent='불러오는 중입니다.';try{const data=await call(url+'?'+new URLSearchParams({offset,state:filter.value,generation}));if(current!==version)return;generation=data.generation;tripNames=new Map(data.trips.map(trip=>[trip.id,trip.name]));list.replaceChildren();for(const row of data.items){const item=document.createElement('li');item.dataset.transaction=row.transaction_id;const label={AUTO_PROVISIONAL:'자동 잠정 · 검토 필요',USER_CONFIRMED:'사용자 확정',MANUAL_UNASSIGNED:'사용자 미배정 유지',FINANCIAL_HOLD:'보류 · 참고 후보',CONFLICT_REVIEW:'충돌 · 선택 필요',UNASSIGNED_NO_VALID_TRIP:'여행 미배정',AUTHORITY_VERIFIED:'기존 여행 배정'}[row.decision.status]||'검토 필요';item.append(text('h3',row.merchant),text('p',label),text('p',row.decision.reason));const evidence=document.createElement('details');evidence.append(text('summary','근거와 대안 후보'));for(const candidate of row.decision.candidates||[]){const trip=data.trips.find(t=>t.id===candidate.trip_id);evidence.append(text('p',(trip?.name||'여행 확인 필요')+' · '+candidate.basis))}item.append(evidence);const form=document.createElement('form'),select=document.createElement('select');select.setAttribute('aria-label','다른 여행 선택');select.append(new Option('여행 미배정','unclassified'));for(const trip of data.trips)select.append(new Option(trip.name,trip.id));select.value=row.display_tab_id||'unclassified';const category=document.createElement('input');category.value=row.item||'';category.required=true;category.setAttribute('aria-label','비용 항목');const save=text('button','여행 확인·교정');save.type='submit';save.disabled=row.protected;form.append(select,category,save);form.addEventListener('submit',async event=>{event.preventDefault();if(busy||row.protected||!window.confirm('선택한 여행과 항목을 이 거래의 사용자 결정으로 저장할까요?'))return;setBusy(true);save.disabled=true;try{await call(url.replace(/\/trip-review$/,'/decision'),{transaction_id:row.transaction_id,revision:row.revision,item:category.value,description:row.description||'',display_tab_id:select.value,request_id:crypto.randomUUID(),reuse_rule:false,resolve_hold:false});generation='';setBusy(false);await load()}catch(error){fail(error)}finally{setBusy(false);save.disabled=row.protected}});item.append(form);const hold=text('button','검토 보류');hold.type='button';hold.disabled=row.protected;hold.addEventListener('click',async()=>{if(busy||!window.confirm('이 거래의 잠정 여행 검토를 보류할까요?'))return;setBusy(true);try{await call(url+'/hold',{transaction_id:row.transaction_id,revision:row.revision,request_id:crypto.randomUUID(),confirmed:true});generation='';setBusy(false);await load()}catch(error){fail(error)}finally{setBusy(false)}});item.append(hold);if(row.can_propose){const label=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.value=row.transaction_id;checkbox.dataset.tripCorrection='';label.append(checkbox,document.createTextNode('이 확정 교정을 제안에 포함'));item.append(label)}list.append(item)}message.textContent=data.total+'건 · '+(data.total?offset+1:0)+'–'+(offset+data.items.length)+'건 표시';root.querySelector('[data-trip-prev]').disabled=offset===0;root.querySelector('[data-trip-next]').disabled=!data.has_more;loaded=true;await loadProposals(url)}catch(error){fail(error)}finally{setBusy(false)}}
async function loadProposals(url,proposalOffset=0){const data=await call(url+'/proposals?offset='+proposalOffset);proposals.replaceChildren();for(const proposal of data.items){const article=document.createElement('article');article.append(text('p',proposal.corrections.length+'건의 원본에만 적용되는 항목·여행 교정 규칙'),text('p',proposal.scope.merchant_normalized+' · '+proposal.scope.item+' · '+(tripNames.get(proposal.scope.trip_id)||'여행 권위 확인 필요')));for(const row of proposal.review_rows||[])article.append(text('p',(row.date||'이용일 미확인')+' · '+row.merchant+' · '+(typeof row.amount_krw==='number'?row.amount_krw.toLocaleString('ko-KR')+'원':'금액 확인 필요')+(row.stale?' · 자료 변경됨':'')));const approve=text('button','범위를 확인하고 승인');approve.type='button';approve.disabled=proposal.stale;approve.addEventListener('click',async()=>{if(busy||!window.confirm('이 거래 원본에만 적용되는 제한 규칙을 승인할까요?'))return;setBusy(true);approve.disabled=true;try{await call(url+'/proposals',{action:'approve',proposal_id:proposal.id,confirmed:true});await loadProposals(url);message.textContent='제한 규칙을 저장했습니다. 거래 재분류나 금융 확정을 실행하지 않았습니다.'}catch(error){fail(error)}finally{setBusy(false);approve.disabled=false}});article.append(approve);proposals.append(article)}for(const [label,next] of [['이전 제안 20건',proposalOffset-20],['다음 제안 20건',proposalOffset+20]]){if(next<0||(next>proposalOffset&&!data.has_more))continue;const button=text('button',label);button.type='button';button.addEventListener('click',async()=>{if(busy)return;setBusy(true);try{await loadProposals(url,next)}catch(error){fail(error)}finally{setBusy(false)}});proposals.append(button)}}
root.addEventListener('toggle',async()=>{if(!root.open||loaded||busy)return;if(!batch.options.length){try{const data=await call('/api/imports');for(const entry of data.batches)batch.append(new Option(entry.display_name||entry.batch_id,entry.batch_id));const requested=new URLSearchParams(location.search).get('batch');if([...batch.options].some(option=>option.value===requested))batch.value=requested}catch(error){fail(error);return}}await load()});
batch.addEventListener('change',()=>{if(busy)return;offset=0;generation='';load()});filter.addEventListener('change',()=>{if(busy)return;offset=0;generation='';load()});
root.querySelector('[data-trip-prev]').onclick=()=>{if(!busy){offset=Math.max(0,offset-20);load()}};root.querySelector('[data-trip-next]').onclick=()=>{if(!busy){offset+=20;load()}};
root.querySelector('[data-trip-propose]').onclick=async()=>{if(busy)return;const ids=[...root.querySelectorAll('[data-trip-correction]:checked')].map(node=>node.value);if(ids.length<2){message.textContent='같은 범위의 확정 교정을 2건 이상 선택해 주세요.';return}setBusy(true);try{await call(endpoint()+'/proposals',{action:'propose',transaction_ids:ids});await loadProposals(endpoint());message.textContent='제안을 저장했습니다. 승인 전에는 규칙이 적용되지 않습니다.'}catch(error){fail(error)}finally{setBusy(false)}};
})();</script>"""
