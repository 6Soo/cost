"""과거 분류를 현재 카드 원행과 대조해 검토 가능한 규칙으로 만든다."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.normalize import normalize_merchant

OUTPUT = ROOT / '.local-archive/lightweight-20261003/rule-recovery'


def readonly(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def current_rows(path):
    conn = readonly(path)
    try:
        from app.db import decided_sql
        return [dict(row) for row in conn.execute(f'SELECT t.*, {decided_sql("t")} AS decided FROM transactions t')]
    finally:
        conn.close()


def key(row, *, historical=False):
    if historical:
        source = row['source_system']
        issuer = {'CORP':'기업', 'KBD':'국민', 'KBO':'국민', 'HAN':'하나'}.get(source, source)
        return (issuer, str(row.get('card_tail') or ''), str(row['occurred_on'])[:10],
                normalize_merchant(row['merchant']), row['amount_krw'],
                'cancellation' if row['transaction_type'] in ('refund','cancellation') else row['transaction_type'])
    return (row['issuer'], row['card_tail'], row['approval_date'] or row['posting_date'], row['merchant_normalized'],
            row['amount_krw'], row['transaction_direction'])


def known_item(merchant):
    """명확한 업종만 제안한다. PG와 혼합 상품 공급자는 여기에 넣지 않는다."""
    m = normalize_merchant(merchant).upper()
    if any(x in m for x in ('TRIP.COM','트립닷컴','KLOOK','클룩','PARTNERS ON BOOKING')):
        return None
    if any(x in m for x in ('AGODA','아고다','BOOKING.COM HOTEL','HOTEL AT BOOKING',
                            'BKG*HOTEL','BKG*BOOKING.COM','TOYOKO INN','MERCURE','IBIS HOTEL',
                            'RYOKAN','HOSTEL')):
        return '숙박비'
    if any(x in m for x in ('고투게이트','GOTOGATE','제주항공','대한항공','아시아나','진에어',
                            '티웨이항공','에어부산','AIR SEOUL','KOREAN AIR','JEJU AIR',
                            'ANA ALL NIPPON','PEACH AVIATION')):
        return '항공료'
    if '트래블로버' in m:
        return '여행자보험'
    if any(x in m for x in ('핀다이렉트','와이드모바일','KT유선상품자동납부','LGUPLUS 통신요금자동이체')):
        return '통신비'
    if any(x in m for x in ('ENEOS','IDEMITSU','JA-SS')):
        return '주유비'
    if any(x in m for x in ('HIGHWAY TOLL','HIGASHINIHONKOUSOKUDOURO',
                            'NISHINIHONKOUSOKUDOURO','ESCOTA VINCI')):
        return '통행료'
    if (m.startswith(('JR EAST','JR CENTRAL','SNCF','FLIXBUS')) and
            not any(x in m for x in ('SHOP','STORE','RESTAURANT'))):
        return '교통비'
    if any(x in m for x in ('카카오T일반택시','카카오_택시','철도승차권','카카오T택시')):
        return '교통비'
    if any(x in m for x in ('MITSUIS REPARK','타임즈주차','TIMES PARKING','카카오T주차')):
        return '주차비'
    if any(x in m for x in ('NIPPON RENT','TOYOTA RENT','닛폰렌터카','쏘카')):
        return '렌터카'
    if m.startswith(('SUSHIRO','STARBUCKS','SUKIYA','MCDONALD')):
        return '식비'
    return None


def proposal_group(merchant):
    m = normalize_merchant(merchant).upper()
    if m.startswith(('FAMILYMART','SEVEN-ELEVEN','LAWSON','SEICOMART','GS25','CU ',
                     'BOSSFOODSMARKET','LIONDOR','CARREFOUR','MONOPRIX')):
        return 'convenience_food', '식비'
    if m.startswith('FUKUTAKE FOUNDATION'):
        return 'foundation', '입장료'
    return 'history_only', None


def confirmed_drafts(report):
    """명확한 공급자와 이번 사용자 답변만 활성화한다."""
    result = list(report.get('booking_rules', []))+list(report.get('user_rules', []))
    result.append(dict(conditions={'merchant_normalized':'*','transaction_direction':'purchase'},
                       optional={'travel_country':'local'},effects={'item':'현지경비'},
                       origin='history-recovery-20261003',
                       note='2026-10-03 사용자 확인: 여행 중 현지 거래는 현지경비로 제안하고 예외 수정. 구체적 규칙·예약·온라인 공급자를 우선한다.'))
    bound_sources = {d['optional']['source_hash']:d['effects']['item'] for d in result if 'source_hash' in d.get('optional',{})}
    for draft in report.get('mail_rules', []):
        identity = draft['optional']['source_hash']
        if identity in bound_sources:
            if draft['effects']['item'] != bound_sources[identity]:
                raise RuntimeError('BOOKING_PRODUCT_CONFLICT')
            continue
        result.append(draft)
    for candidate in report['candidates']:
        if candidate['safe'] or candidate['group'] == 'foundation':
            draft = candidate['draft']
            if candidate['group'] == 'foundation':
                draft = dict(draft,effects={'item':'입장료','description':'미술관 입장권'},
                             note='2026-10-03 사용자 확인: 모두 미술관 입장료')
            result.append(draft)
        elif candidate['group'] == 'convenience_food':
            result.append(dict(candidate['draft'], optional={'travel_country':'local'},
                               note='2026-10-03 사용자 확인: 사용 장소와 여행이 일치할 때 해당 여행의 식비'))
        elif candidate['group']=='history_only' and candidate['history_sources'].get('overseas_default'):
            m = candidate['merchant'].upper()
            if not any(x in m for x in ('AGODA','BOOKING','TRIP','KLOOK','NICE','PAY','이니시스','KCP')):
                result.append(dict(candidate['draft'],optional={'travel_country':'local'},
                                   effects={'item':'현지경비'},
                                   note='2026-10-03 사용자 확인: 여행 중 현지 거래는 현지경비로 먼저 제안하고 예외 수정'))
    for draft in result:
        body = json.dumps({k:v for k,v in draft.items() if k!='rule_id'},sort_keys=True,
                          ensure_ascii=False,separators=(',',':'))
        draft['rule_id'] = 'history-' + hashlib.sha256(body.encode()).hexdigest()[:24]
    result.extend(report.get('inferred_rules', []))
    return result


def inferred_drafts(rows, flow, mail_matches):
    """사용자가 허용한 추론을 현재 원행에만 묶는다. 여행 일정은 만들거나 늘리지 않는다."""
    import datetime
    from app.rules import merchant_country, is_booking_or_online
    trips=[t for t in flow.board.list_trips() if flow.trip_valid(t['tab_id'])]
    by_code={t['display_key']:t for t in trips}
    mail_by_source={m['source_hash']:m for m in mail_matches}
    europe=by_code.get('5월_유럽')
    common_items={'사무용품비','소모품비','통신비','수수료','지급수수료','세금과공과',
                  '소프트웨어구독료','선물비','기부금','법무비','복리후생비','회의비'}
    location_words={
        '에히메':('DOGO','MATSUYAMA','UWAJIMA'), '교토':('KYOTO','HASHIDATE'),
        '나가센도':('NEZAME','KOMAGANE'), '아오모리':('AOMORI','MUTSU'),
        '오사카':('OSAKA','KOBE'), '알펜루트':('HAKUBA','TOYAMA','TATEYAMA'),
        '북해도':('HOKKAIDO','AKAN','RYOKUSEISOU','PARKWAY'),
        '레분토&리시리':('REBUN','RISHIRI','KITAGUNI'), '묘코고원':('MYOKO','NIIGATA'),
        '아키타':('AKITA','YOKOTE','TAZAWAKO','SENBOKU'),
        '야마가타':('YAMAGATA','SHOUNAI','SUIDEN','SENAMI'), '몽골':('ULAANBAATAR','MONGOL'),
        '야쿠시마':('YAKUSHIMA',), '가루이자와':('KARUIZAWA',),
        '유럽':('PARIS','MARSEILLE','MARIGNANE','FRANC','BOLOGNA','MAZZIN','VIENNA','SICILY'),
    }
    def day(value):
        return datetime.date.fromisoformat(value)
    def resolve_old(code):
        # 같은 시작일의 행사명이 과거 출력에 다르게 남은 확인 가능한 한 가지 경우.
        return by_code.get({'0704_아키타':'0704_야마가타'}.get(code,code))
    def distance(t, occurred):
        start,end=day(t['starts_on']),day(t['ends_on'])
        return 0 if start<=occurred<=end else min(abs((occurred-start).days),abs((occurred-end).days))
    def family(row):
        m=row['merchant_normalized'].upper()
        for label,words in (
            ('TRIP',('TRIP.COM','트립닷컴')),('KLOOK',('KLOOK','클룩')),
            ('AGODA',('AGODA','아고다')),('BOOKING',('BOOKING.COM','BKG*'))):
            if any(w in m for w in words):return label
        return m
    result=[]
    for row in rows:
        if (row['decided'] or row['trip_id']
                or row['classification_source'] in ('inference','user_exception')
                or row['parse_error'] or row['conflict_reason'] or row['duplicate_of']
                or (row['approval_date'] or row['posting_date'])<'2026-04-01'):
            continue
        row=dict(row,raw_row=json.loads(row['raw_row_json']))
        m=row['merchant_normalized'].upper()
        occurred=day(row['approval_date'] or row['posting_date'])
        old=row.get('_history',[])
        explicit_old=[h for h in old if h.get('account') not in ('',None,'비용제외')
                      and h.get('classification_source')!='overseas_default']
        accounts=collections.Counter(h['account'] for h in explicit_old)
        item=row['item'] if row['item'] and row['item']!='현지경비' else ''
        confidence='중간'
        basis=[]
        target=None
        old_targets={h.get('allocation_target') for h in explicit_old if resolve_old(h.get('allocation_target'))}
        historical_common=bool(explicit_old) and all(h.get('allocation_target')=='기타비용' for h in explicit_old)
        if len(old_targets)==1:
            target=resolve_old(next(iter(old_targets)))
            basis.append('카드 원행과 날짜·카드·부호 있는 금액이 일치하는 과거 장부의 여행 배정을 재사용')
            confidence='높음'
        if len(accounts)==1 and not item:
            item=next(iter(accounts))
            basis.append('같은 원행의 과거 비용 항목을 참고')
        # 공급자 전체에 적용하지 않고 현재 원행의 목적만 추론한다.
        for candidate,words in (
            ('소프트웨어구독료',('ANTHROPIC','CLAUDE SUB','OPENAI','CHATGPT','MICROSOFT','카카오 MY 구독')),
            ('통신비',('휴대폰메시지','승인안내','통신요금','와이드모바일','핀다이렉트')),
            ('주차비',('주차','PARKING','REPARK','MITSUINOREPARK')),
            ('주유비',('ENEOS','IDEMITSU','SINOOIL','TOTAL ')),
            ('통행료',('VINCI','TANCARVILLE','TOLL','고속도로')),
            ('식비',('SOBAFUKU','MENYA7TEN','COFFEE','CAFE','BACKEREI','SUPERMARKET','SUPER U','HOFER','LIONDOR','ORI NABIJI','NIKORA','SEICOMART','FAMILYMART','LAWSON','GS25')),
            ('렌터카',('AVIS','BUDGET','DISCOVERCARS','NIPPON RENT','TOYOTA RENT','닛폰렌터카','SICILY BY CAR','HERTZ')),
            ('항공료',('ANAAIR','ANA AIR','SKYTICKET','항공','GOTOGATE','고투게이트')),
            ('여행상품비',('어드벤처코리아','하나투어','TRAVELOKA')),
            ('여행자보험',('트래블로버',)),
            ('선물비',('선물하기',)),('기부금',('유니세프',)),('법무비',('전자소송',)),
            ('소모품비',('ALIEXPRESS','쿠팡','11번가','G마켓','오케이파츠')),
            ('지급수수료',('예스닉','도메인','취급수수료','보험개발원')),
        ):
            if any(w in m for w in words):
                # 이미 정확한 예약 자료로 항목을 확인한 거래는 종류를 바꾸지 않는다.
                if row['source_hash'] not in mail_by_source:
                    item=candidate
                basis.append('가맹점의 구체적 상품·업종으로 비용 항목을 추론')
                break
        if not item and any(w in m for w in ('HOTEL','RYOKAN','RESIDHOTEL','AIRBNB','RAKUTENTRAVEL','AGODA','BOOKING','KIRIAD','RAKUTEN TRAVEL')):
            item='숙박비';basis.append('숙박 공급자 거래로 추론')
        # 음식점의 RAKUTENPAY는 여행 예약 공급자가 아니다.
        if 'SOBAFUKU' in m or 'MENYA7TEN' in m:
            item='식비'
        match=mail_by_source.get(row['source_hash'])
        period=match.get('period') if match else None
        if match:
            item=match['item']
            if match.get('basis'):
                basis.append(match['basis'])
            period=match.get('period')
            if period:
                options=[t for t in trips if t['starts_on']<=period['starts_on']<=period['ends_on']<=t['ends_on']]
                if len(options)==1:
                    target=options[0];confidence=match.get('confidence','높음')
                    basis.append('예약 메일의 실제 이용기간이 명시 여행과 일치')
                elif not options:
                    basis.append('예약 이용기간 '+period['starts_on']+'~'+period['ends_on']+'은 현재 여행기간과 불일치')
                    confidence='낮음'
                    if target and distance(target,day(period['starts_on']))>7:
                        target=None
        if row['transaction_direction']=='cancellation':
            purchases=[p for p in rows if p['transaction_direction']=='purchase'
                       and p['issuer']==row['issuer'] and p['card_tail']==row['card_tail']
                       and family(p)==family(row) and p['amount_krw']==abs(row['amount_krw'])
                       and (p['approval_date'] or p['posting_date'])<=occurred.isoformat()]
            choices={h.get('allocation_target') for p in purchases for h in p.get('_history',[])
                     if resolve_old(h.get('allocation_target'))}
            items={p['item'] for p in purchases if p['item'] and p['item']!='현지경비'}
            if len(choices)==1:
                target=resolve_old(next(iter(choices)))
                basis.append('같은 카드·공급자·반대 부호 금액의 결제 여행을 참고한 환불 배정이며 원거래 연결 확정은 아님')
            if len(items)==1 and not item:item=next(iter(items))
        if not item and family(row) in ('TRIP','KLOOK'):
            item='여행상품비'
            basis.append('혼합 예약 공급자로 항공·숙박·교통 중 세부 상품은 아직 확인되지 않음')
            confidence='낮음'
        country=merchant_country(row)
        online=is_booking_or_online(row) or item in ('항공료','여행자보험','여행상품비','숙박비','렌터카')
        travel_telecom=item=='통신비' and any(w in m for w in ('와이드모바일','도시락','ESIM','이심'))
        if (item in common_items and not travel_telecom) or historical_common:
            target=None;basis.append('공통 업무 경비로 배정')
        elif not target:
            direct=flow.retail_trip(row,country) if country and not online else ''
            if direct:
                target=next(t for t in trips if t['tab_id']==direct)
                basis.append('원본 국가와 승인일이 명시 여행에 일치')
            elif not period and europe and country in ('AT','IT','FR','DE','ES','CZ','GE','KZ','TR','GB') and datetime.date(2026,5,1)<=occurred<=datetime.date(2026,6,12):
                target=europe
                basis.append('5~6월 유럽 및 경유지의 카드 사용 흐름을 같은 여행 경비로 추론')
                confidence='중간'
            elif period:
                service_day=day(period['starts_on'])
                nearby=[] if match.get('strict_service_period') else [t for t in trips if distance(t,service_day)<=7]
                if len(nearby)==1:
                    target=nearby[0]
                    basis.append('실제 예약 이용일이 가까운 여행의 사전·후속 일정으로 추론')
                    confidence='낮음'
            elif online and item not in common_items:
                located=[t for t in trips if any(w in m for w in location_words.get(t['destination'],()))]
                if located:
                    target=min(located,key=lambda t:(distance(t,occurred),t['starts_on'],t['tab_id']))
                    basis.append('숙박·여행 공급자의 지역과 가까운 명시 여행으로 추론')
                elif item in ('항공료','숙박비','렌터카','여행자보험','여행상품비','교통비'):
                    upcoming=[t for t in trips if occurred<=day(t['starts_on'])<=occurred+datetime.timedelta(days=120)]
                    if country=='JP' and item=='숙박비':upcoming=[t for t in upcoming if t['destination'] not in ('부산','유럽','몽골')]
                    if upcoming:
                        target=min(upcoming,key=lambda t:(t['starts_on'],t['tab_id']))
                        basis.append('예약 근거가 부족해 결제 뒤 가까운 여행의 사전 비용으로 추론')
                        confidence='낮음'
        # 국내 현장 구매는 해외 여행에 붙이지 않는 기존 사용자 지시를 유지한다.
        physical=not is_booking_or_online(row) and item not in ('항공료','여행자보험','여행상품비')
        if target and country=='KR' and physical and not match and target['destination']!='부산':
            target=None;basis.append('국내 현장 거래이므로 해외 여행 배정에서 제외')
        if not item:
            item='현지경비' if country and country!='KR' and not online else '기타경비'
            basis.append('구매 상세가 없어 '+item+'로 임시 분류');confidence='낮음'
        if row['amount_krw']==37300 and 'KLOOK' in m:
            target=europe;confidence='낮음'
            basis.append('바우처 이용일은 6월 29일로 여행기간과 다르지만 5월 결제한 이탈리아 이동비로 배정; 이용일 원문은 보존')
        unresolved_codes={h.get('allocation_target') for h in old
                          if h.get('allocation_target') not in ('기타비용','취소환불',None,'')
                          and not str(h.get('allocation_target')).startswith('임시') and not resolve_old(h.get('allocation_target'))}
        if unresolved_codes and not old_targets and not match:
            target=None;confidence='낮음'
            basis.append('과거 여행 '+', '.join(sorted(unresolved_codes))+'의 현재 여행 탭이 없어 여행 미배정으로 보존')
        if match and match.get('period_conflict'):
            target=None;confidence='낮음'
            basis.append('같은 예약의 메일 이용기간이 서로 달라 여행 배정을 보류')
        if match and match.get('reservation_status')=='cancelled':
            target=None;confidence='낮음'
            basis.append('취소 메일이 있는 예약이므로 실제 이용을 근거로 한 배정을 보류; 원결제와 환불은 별도 보존')
        if row['transaction_direction']=='cancellation':
            target=None
            basis.append('사용자 지시: 취소·환불은 여행에서 분리해 관리')
        if not target and item not in common_items and not historical_common:
            basis.append('맞는 여행 근거가 부족해 여행 미배정으로 유지')
        description=row['description'] or item
        if unresolved_codes and not target:description+=' · 여행 후보 '+', '.join(sorted(unresolved_codes))
        inference=dict(trip_id=target['tab_id'] if target else '',confidence=confidence,
                       basis='; '.join(dict.fromkeys(basis))[:1500])
        exception=country in ('GE','KZ') and europe and datetime.date(2026,5,1)<=occurred<=datetime.date(2026,6,12)
        if exception:
            inference.update(trip_id=europe['tab_id'],confidence='높음',
                             basis='사용자 지정 예외: 조지아·카자흐스탄 거래를 유럽 여행에 배정. '+inference['basis'])
        draft=dict(conditions={'merchant_normalized':row['merchant_normalized'],'card_kind':row['card_kind'],
                               'transaction_direction':row['transaction_direction']},
                   optional={'source_hash':row['source_hash'],'inferred_assignment':inference},
                   effects={'item':item,'description':description},
                   origin='owner-country-exception-20261003' if exception else 'owner-authorized-inference-20261003',
                   note='2026-10-03 사용자 지시: 최대한 추론해 배정하고 나중에 수정 가능. 해당 원행에만 적용하며 사용자 확정은 아님.')
        body=json.dumps(draft,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        draft['rule_id']='inference-'+hashlib.sha256(body.encode()).hexdigest()[:24]
        result.append(draft)
    return result


def refined_drafts(rows, flow, mail_matches):
    """추가 근거로 최초 추론만 보완한다. 사용자가 고친 규칙과 거래는 유지한다."""
    from app.rules import normalize_rule
    existing={r['optional'].get('source_hash'):r for r in flow.pipeline.list_rules()
              if r.get('origin')=='owner-authorized-inference-20261003'
              and r['optional'].get('inferred_assignment') and r['version']==1}
    mail_by_source={match['source_hash']:match for match in mail_matches}
    reconsider={}
    for row in rows:
        if (row.get('classification_source')!='inference' or row['decided']
                or row['source_hash'] not in existing):
            continue
        mail=mail_by_source.get(row['source_hash'],{})
        stronger_evidence=bool(mail.get('period') or mail.get('period_conflict')
                               or mail.get('reservation_status')=='cancelled')
        if row['trip_id'] and not row['classification_basis'].startswith('추론 배정 · 낮음 ·') and not stronger_evidence:
            continue
        reconsider[row['source_hash']]=dict(row,trip_id='',classification_source='')
    result=[]
    working=[reconsider.get(row['source_hash'],row) for row in rows]
    for draft in inferred_drafts(working,flow,mail_matches):
        if draft['optional']['source_hash'] not in reconsider:
            continue
        prior=existing[draft['optional']['source_hash']]
        normalized=normalize_rule(draft)
        fields=('conditions','optional','effects')
        if all(normalized[f]==prior[f] for f in fields):
            continue
        draft['rule_id']=prior['rule_id']
        result.append({'draft':draft,'expected_rule_hash':prior['rule_hash'],
                       'expected_version':prior['version']})
    return result


def owner_answer_drafts(transactions):
    """구매 목적 답변의 실제 적용 범위를 원본 거래와 묶는다."""
    result=[dict(rule_id='owner-agoda-lodging-20261004',
                 conditions={'merchant_normalized':'agoda'},optional={'merchant_family':'agoda'},
                 effects={'item':'숙박비'},origin='owner-confirmed-20261004',
                 note='사용자 확인: 아고다 구매는 모두 숙박. 여행 배정과 취소·환불은 별도로 처리하며 원본 금액과 날짜는 변경하지 않음.')]
    office_conditions=set()
    adventure_dates={('2026-07-08',736240),('2026-05-27',-325866),
                     ('2026-05-27',1983330),('2026-05-04',-324912),
                     ('2026-05-08',389906),('2026-04-05',340013)}
    for row in transactions:
        merchant=normalize_merchant(row['merchant'])
        conditions={'merchant_normalized':merchant,'card_kind':row['card_kind'],
                    'transaction_direction':row['transaction_direction']}
        if merchant in ('아성다이소','(주)아성다이소'):
            identity=tuple(conditions.values())
            if identity in office_conditions:
                continue
            office_conditions.add(identity)
            result.append(dict(conditions=conditions,effects={'item':'사무용품비','display_tab_id':'unclassified'},
                               origin='owner-confirmed-20261003',
                               note='2026-10-03 사용자 확인: 다이소는 일반 사무용품으로 공통 경비 처리. 여행 배정 없음.'))
        elif (merchant=='인터넷상거래_1-주식회사 어드벤처코리아' and
              (row['approval_date'],row['amount_krw']) in adventure_dates):
            result.append(dict(conditions=conditions,optional={'source_hash':row['source_hash']},
                               effects={'item':'여행상품비','description':'여행·관광 상품'},
                               origin='owner-confirmed-20261003',
                               note='2026-10-03 사용자 확인: 질문한 결제 네 건과 취소·환불 두 건은 여행·관광 상품. 여행 배정은 예약 자료로 별도 확인.'))
    return result


def booking_rules(db, source_by_payment, live):
    """후보 연결을 믿지 않고 원본 예약과 현재 결제를 다시 대조한다."""
    live_index = collections.defaultdict(list)
    for row in live:
        live_index[key(row)].append(row)
    facts = []
    for row in db.execute("SELECT payload_json,source_sha256 FROM direct_source_records WHERE source_kind='ota_lodging_fact'"):
        payload = json.loads(row['payload_json'])
        expected = hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if expected != row['source_sha256']:
            raise RuntimeError('BOOKING_SOURCE_HASH_MISMATCH')
        if payload.get('eligibility_status')=='eligible' and payload.get('message_class')=='confirmation':
            facts.append((payload,row['source_sha256']))
    targets = {str(row['booking_ref']):row['target_code'] for row in db.execute('SELECT booking_ref,target_code FROM direct_verified_lodging_facts')}
    result = []
    for payment in db.execute("SELECT p.*,b.booking_number,b.provider FROM payment_booking_links x "
                              "JOIN payment_transactions p ON p.id=x.payment_id JOIN bookings b ON b.id=x.booking_id "
                              "WHERE b.provider='trip' AND b.product_type='lodging'"):
        payment = dict(payment)
        payment['card_tail'] = str(source_by_payment[payment['id']].get('card4') or '')[-4:]
        current = live_index[key(payment,historical=True)]
        if len(current)!=1:
            continue
        compatible = [(f,sha) for f,sha in facts if f.get('provider') in ('trip','trip.com','Trip.com')
                      and f.get('paid_total_krw')==payment['amount_krw']
                      and str(f.get('seoul_sent_on'))==str(payment['occurred_on'])]
        identities = {(str(f['booking_ref']),f['check_in'],f['check_out']) for f,_ in compatible}
        if len(identities)!=1:
            continue
        fact,digest = compatible[0]
        reference = str(fact['booking_ref'])
        if reference!=str(payment['booking_number']) or reference not in targets:
            continue
        row = current[0]
        result.append({'conditions':{'merchant_normalized':row['merchant_normalized'],
                                    'card_kind':row['card_kind'],'transaction_direction':row['transaction_direction']},
                       'optional':{'source_hash':row['source_hash'],'booking_period':{
                           'starts_on':fact['check_in'],'ends_on':fact['check_out'],
                           'target_code':targets[reference],'source_sha256':digest}},
                       'effects':{'item':'숙박비','description':'숙박 예약 '+reference},
                       'origin':'history-recovery-20261003',
                       'note':'원본 예약번호·결제금액·결제일·카드 원행을 다시 대조. 명시 일정과 이용기간이 맞아야 여행 확정.'})
    return result


def apply_rules(board_path, report, *, flow=None):
    """호출자가 백업과 작성자 중지를 확인한 DB에 원자적으로 분류만 반영한다."""
    from app import Pipeline
    from app.rules import save_rule, normalize_rule
    from app.db import canonical
    before_rows = current_rows(board_path)
    conn = sqlite3.connect(board_path,isolation_level=None,timeout=30)
    pipe = Pipeline(conn)
    try:
        derived = {'classification_state','classification_source','classification_basis',
                   'item','description','display_tab_id','trip_id','decided'}
        frozen = sorted(set(before_rows[0])-derived)
        source_before = {r['transaction_id']:tuple(r[name] for name in frozen) for r in before_rows}
        protected_before = {r['transaction_id']:r for r in before_rows if r['decided']}
        protected_tables = ('board_rows','board_revisions','owner_profile','trip_tabs',
                            'review_decisions','ledger_entries','review_source_guidance','decision_events')
        available = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables_before = {table:conn.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
                         for table in protected_tables if table in available}
        originals_before = conn.execute('SELECT batch_id,content_sha256,content_bytes FROM import_batches ORDER BY batch_id').fetchall()
        conn.execute('BEGIN IMMEDIATE')
        for draft in confirmed_drafts(report):
            existing = conn.execute('SELECT origin,rule_hash FROM cost_classification_rules WHERE rule_id=?',
                                    (draft['rule_id'],)).fetchone()
            if existing and existing[0] != draft['origin']:
                raise RuntimeError('EXISTING_RULE_OWNERSHIP_CONFLICT')
            if existing:
                continue
            save_rule(pipe.store,draft)
        for update in report.get('refined_rules',[]):
            draft=update['draft']
            normalized=normalize_rule(draft)
            desired=hashlib.sha256(canonical({k:normalized[k] for k in ('conditions','optional','effects')}).encode()).hexdigest()
            current=conn.execute('SELECT origin,version,rule_hash FROM cost_classification_rules WHERE rule_id=?',
                                 (draft['rule_id'],)).fetchone()
            if current and current[2]==desired:
                continue
            if current!=(draft['origin'],update['expected_version'],update['expected_rule_hash']):
                raise RuntimeError('INFERENCE_RULE_CHANGED_DURING_REFINEMENT')
            if draft['origin']!='owner-authorized-inference-20261003':
                raise RuntimeError('INFERENCE_RULE_REFINEMENT_NOT_ALLOWED')
            save_rule(pipe.store,draft)
        for batch_id, in conn.execute('SELECT batch_id FROM import_batches').fetchall():
            pipe.classify_batch(batch_id,trip_resolver=flow.retail_trip if flow else None,review_from='2026-04-01',
                                transaction_ids=report.get('ota_transaction_ids'))
        source_after = {r[0]:r[1:] for r in conn.execute('SELECT transaction_id,'+','.join(frozen)+' FROM transactions')}
        if source_before != source_after:
            raise RuntimeError('SOURCE_CHANGED_DURING_CLASSIFICATION')
        for identity,old in protected_before.items():
            conn.row_factory = sqlite3.Row
            new = dict(conn.execute('SELECT * FROM transactions WHERE transaction_id=?',(identity,)).fetchone())
            if old != new:
                raise RuntimeError('CONFIRMED_ANSWER_CHANGED')
        conn.row_factory = None
        for table, original in tables_before.items():
            if conn.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall() != original:
                raise RuntimeError('PROTECTED_TABLE_CHANGED:'+table)
        if originals_before != conn.execute('SELECT batch_id,content_sha256,content_bytes FROM import_batches ORDER BY batch_id').fetchall():
            raise RuntimeError('ORIGINAL_FILE_CHANGED')
        counts = dict(conn.execute('SELECT classification_state,COUNT(*) FROM transactions GROUP BY classification_state'))
        pipe.store.log_change('history.rules_applied','history-20261003',{'counts':counts})
        conn.commit()
        result = {'counts':counts,'original_sources_unchanged':True,'confirmed_answers_protected':True,
                  'new_ledger_entries':0,'rule_count':len(confirmed_drafts(report))}
        (OUTPUT/'applied.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def analyze(board_path, history_path, history_db_path, *, infer=False):
    live = current_rows(board_path)
    wb = openpyxl.load_workbook(history_path, read_only=True, data_only=True)
    iterator = wb['전체결과'].values
    headers = next(iterator)
    history = [dict(zip(headers, row)) for row in iterator]
    wb.close()
    db = readonly(history_db_path)
    try:
        source_by_payment = {}
        for r in db.execute('SELECT x.payment_id,s.payload_json,s.source_sha256 FROM '
                            'direct_payment_projection_links x JOIN direct_normalized_payments n '
                            'ON n.id=x.direct_payment_id JOIN direct_source_records s '
                            'ON s.id=n.source_record_id'):
            payload = json.loads(r['payload_json'])
            digest = hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,
                                               separators=(',',':')).encode()).hexdigest()
            if digest != r['source_sha256']:
                raise RuntimeError('HISTORICAL_SOURCE_HASH_MISMATCH')
            source_by_payment[r['payment_id']] = payload
        booking_drafts = booking_rules(db,source_by_payment,live)
    finally:
        db.close()
    by_key = collections.defaultdict(list)
    for row in history:
        source = source_by_payment.get(row['payment_id'], {})
        row['card_tail'] = str(source.get('card4') or '')[-4:]
        row['_source'] = source
        by_key[key(row, historical=True)].append(row)
    groups = collections.defaultdict(list)
    match_counts = collections.Counter()
    for row in live:
        old = by_key.get(key(row), [])
        row['_history'] = old
        # 같은 원행이 여러 개면 분류 후보 집합만 비교한다. 개별 연결을 만들어 내지 않는다.
        match_counts['exact_source_match' if old else 'not_matched'] += 1
        groups[(row['merchant_normalized'],row['card_kind'],row['transaction_direction'])].append(row)
    candidates = []
    merchant_accounts = collections.defaultdict(set)
    for row in history:
        if row['account'] not in ('','비용제외',None):
            merchant_accounts[normalize_merchant(row['merchant'])].add(row['account'])
    for (merchant, kind, direction), rows in sorted(groups.items()):
        previous = {r['payment_id']:r for t in rows for r in t['_history']}.values()
        accounts = collections.Counter(r['account'] or '' for r in previous)
        sources = collections.Counter(r['classification_source'] or '' for r in previous)
        item = known_item(merchant)
        group, question_item = proposal_group(merchant)
        # 분명한 공급자 특성은 현재 카드와 과거 후보가 충돌하지 않아야 한다.
        valid_accounts = set(accounts) - {'','비용제외'}
        acceptable = {item} if item else set()
        if item == '주유비': acceptable.add('교통비')
        if item == '통신비': acceptable.add('기타비용')
        support = valid_accounts or merchant_accounts[merchant]
        corroborated = bool(support) and support <= acceptable
        safe = bool(item and corroborated and all(t['_history'] for t in rows))
        draft = {'conditions':{'merchant_normalized':merchant,'card_kind':kind,
                               'transaction_direction':direction},
                 'effects':{'item':item or question_item or next(iter(valid_accounts), '확인필요')},
                 'origin':'history-recovery-20261003',
                 'note':'과거 계정 후보와 현재 가맹점 업종 대조. 여행 배정과 비용 제외는 승계하지 않음.'}
        candidates.append({'merchant':rows[0]['merchant'],'rows':len(rows),
                           'currently_unresolved':sum(t['classification_state']=='needs_review' for t in rows),
                           'history_accounts':dict(accounts),'history_sources':dict(sources),
                           'group':'safe_vendor' if safe else group,'safe':safe,'draft':draft,
                           'transaction_ids':[t['transaction_id'] for t in rows]})
    from app.ota_mail import match_mail
    mail = match_mail(OUTPUT,live)
    travel_matches=mail['matches']+[dict(candidate,period=candidate['shared_period'],
        strict_service_period=True,confidence='중간',
        basis='같은 금액의 숙박 후보가 동일한 이용기간을 가리킴. 개별 예약번호는 선택하지 않음')
        for candidate in mail.get('type_only_candidates',[]) if candidate.get('shared_period')]
    from app.ota_mail import europe_stays
    europe = europe_stays(OUTPUT)
    if europe:
        europe_refs={s['booking_ref'] for s in europe['stays']}
        matches_by_source={match['source_hash']:match for match in mail['matches']}
        for draft in mail['rules']:
            match=matches_by_source.get(draft['optional']['source_hash'])
            if not match:
                continue
            if (match['item']=='숙박비' and match['period'] and match['booking_ref'] in europe_refs
                    and europe['starts_on']<=match['period']['starts_on']<=match['period']['ends_on']<=europe['ends_on']):
                draft['optional']['booking_period']=dict(match['period'],target_code='5월_유럽',
                                                         source_sha256=match['source_sha256'])
    (OUTPUT/'mail-matches.json').write_text(json.dumps(mail,ensure_ascii=False,indent=2),encoding='utf-8')
    report = {'history_rows':len(history),'current_rows':len(live),
              'history_status':dict(collections.Counter(r['result_status'] for r in history)),
              'source_matches':dict(match_counts),
              'input_sha256':{str(history_path):hashlib.sha256(Path(history_path).read_bytes()).hexdigest(),
                              str(history_db_path):hashlib.sha256(Path(history_db_path).read_bytes()).hexdigest()},
              'group_counts':dict(collections.Counter({g:sum(c['rows'] for c in candidates if c['group']==g)
                                  for g in {c['group'] for c in candidates}})),
              'safe_rules':sum(c['safe'] for c in candidates),
              'newly_classifiable':sum(c['currently_unresolved'] for c in candidates if c['safe']),
              'booking_rule_count':len(booking_drafts),
              'booking_rules':booking_drafts,
              'user_rules':owner_answer_drafts(live),
              'mail_rules':mail['rules'],
              'mail_summary':{k:v for k,v in mail.items() if k not in ('matches','rules','type_only_candidates','unmatched_transactions')},
              'europe_summary':{k:v for k,v in (europe or {}).items() if k not in ('messages','stays')},
              'candidates':candidates}
    if infer:
        from tools.verify_lightweight_runtime import configured_readonly_flow
        flow=configured_readonly_flow(board_path)
        try:
            report['inferred_rules']=inferred_drafts(live,flow,travel_matches)
            existing_sources={rule['optional'].get('source_hash') for rule in flow.pipeline.list_rules()
                              if rule['optional'].get('inferred_assignment')}
            report['inferred_rules']=[draft for draft in report['inferred_rules']
                                      if draft['optional']['source_hash'] not in existing_sources]
            report['refined_rules']=refined_drafts(live,flow,travel_matches)
            report['inference_summary']={
                'source_bound_proposals':len(report['inferred_rules']),
                'confidence':dict(collections.Counter(d['optional']['inferred_assignment']['confidence']
                                                     for d in report['inferred_rules'])),
                'trip_proposals':sum(bool(d['optional']['inferred_assignment']['trip_id']) for d in report['inferred_rules']),
                'refined_proposals':len(report['refined_rules']),
            }
        finally:
            flow.board.conn.close()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('candidates','input_sha256','booking_rules','mail_rules','user_rules')},ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--board',default='D:/WebLedgerHost/data/board.sqlite')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--infer',action='store_true')
    parser.add_argument('--ota-only',action='store_true',help='OTA 원행만 다시 대조하고 분류한다')
    args = parser.parse_args()
    if args.ota_only and not args.infer:
        parser.error('--ota-only requires --infer')
    report = analyze(args.board,ROOT/'outputs/2026-08-12-package-c/full_results.xlsx',
                      ROOT/'outputs/agoda-card-link-candidate-v5-20260826.sqlite',infer=args.infer)
    if args.ota_only:
        rows=current_rows(args.board)
        sources={row['source_hash'] for row in rows
                 if not row['decided']
                 and any(marker in row['merchant'].upper() for marker in
                         ('AGODA','BOOKING','TRIP','KLOOK','AIRBNB','아고다','트립닷컴','클룩','부킹닷컴','에어비앤비'))}
        report['inferred_rules']=[draft for draft in report.get('inferred_rules',[])
                                  if draft['optional'].get('source_hash') in sources]
        report['refined_rules']=[update for update in report.get('refined_rules',[])
                                if update['draft']['optional'].get('source_hash') in sources]
        report['ota_refinement_scope']=dict(source_hashes=len(sources),updates=len(report['refined_rules']))
        report['ota_transaction_ids']=[row['transaction_id'] for row in rows if row['source_hash'] in sources]
    if args.apply:
        import os
        if os.environ.get('WEBLEDGER_MAINTENANCE') != 'HISTORY_RULES':
            raise RuntimeError('WRITERS_MUST_BE_STOPPED')
        deploy_rules(Path(args.board),report)


def add_europe_trip(board_path, europe, source_digest):
    from webapp.ledger_store import LedgerStore
    import os
    os.environ['WEBLEDGER_UNIFIED_DB']='1'
    board=LedgerStore(board_path,seed_demo=False)
    try:
        old=board.conn.execute('SELECT * FROM trip_tabs ORDER BY tab_id').fetchall()
        existing=[t for t in board.list_trips() if t['display_key']=='5월_유럽']
        if existing and any((t['starts_on'],t['ends_on'],t['source_sha256']) !=
                            (europe['starts_on'],europe['ends_on'],source_digest) for t in existing):
            raise RuntimeError('EXISTING_EUROPE_SCHEDULE_CONFLICT')
        result=board.create_trip(starts_on=europe['starts_on'],ends_on=europe['ends_on'],
                                 destination='유럽',display_key='5월_유럽',source_sha256=source_digest,
                                 client_request_id='history-europe-schedule-20261003',actor='owner')
        new={r[0]:r for r in board.conn.execute('SELECT * FROM trip_tabs')}
        if any(new[r[0]]!=r for r in old):
            raise RuntimeError('EXISTING_TRIP_CHANGED')
        return result['tab_id']
    finally:
        board.close()


def deploy_rules(db, report):
    import datetime
    import os
    import shutil
    from tools.verify_operational_backup_restore import backup_database,database_state
    from tools.verify_lightweight_runtime import configured_readonly_flow
    from app.ota_mail import europe_stays
    from ledger.domain.direct_trip_schedule_authority import load_document,validate_document,SCHEMA_VERSION,END_SEMANTICS
    host=Path('D:/WebLedgerHost')
    if db.resolve()!=(host/'data/board.sqlite').resolve():
        raise RuntimeError('OPERATIONAL_DATABASE_PATH_REQUIRED')
    evidence=json.loads((ROOT/'docs/handoff/2026-10-01/operational-backup-restore-evidence.json').read_text(encoding='utf-8'))
    age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(evidence['recorded_at'])).total_seconds()
    if not 0<=age<=300 or not evidence['live_state_unchanged']:
        raise RuntimeError('FRESH_VERIFIED_BACKUP_REQUIRED')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=host/'data/backups'/('history-rules-'+stamp)
    backup.mkdir(parents=True,exist_ok=False)
    before=database_state(db)
    with readonly(db) as original:
        old_events={tuple(row) for row in original.execute('SELECT * FROM decision_events')}
    backup_database(db,backup/'board.sqlite')
    if database_state(backup/'board.sqlite')!=before:
        raise RuntimeError('RESTORE_VERIFICATION_FAILED')
    options_path=host/'config/card-flow.json'
    authority_path=host/'config/trip-authority.json'
    source_path=host/'data/evidence/europe-booking-mails.json'
    launcher=host/'bin/launch_web_ledger.py'
    originals={}
    for path in (options_path,authority_path,source_path,launcher):
        originals[path]=path.read_bytes() if path.is_file() else None
        if originals[path] is not None:
            (backup/path.name).write_bytes(originals[path])
    try:
        options=json.loads(options_path.read_text(encoding='utf-8'))
        records,_=load_document(Path(options['trip_authority_path']))
        europe=europe_stays(OUTPUT)
        if not europe:
            raise RuntimeError('EUROPE_BOOKING_SOURCE_REQUIRED')
        source_bytes=json.dumps(europe,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        digest=hashlib.sha256(source_bytes).hexdigest()
        source_path.parent.mkdir(parents=True,exist_ok=True)
        source_path.write_bytes(source_bytes)
        existing=[r.as_dict() for r in records if r.trip_code!='5월_유럽']
        record=dict(trip_code='5월_유럽',event_year=2026,starts_on=europe['starts_on'],ends_on=europe['ends_on'],
                    region='유럽',authority_kind='explicit_trip_registry',authority_status='authoritative',
                    source_locator=str(source_path)+'#confirmed_lodging_periods',source_sha256=digest,end_semantics=END_SEMANTICS)
        document={'schema_version':SCHEMA_VERSION,'records':existing+[record]}
        validate_document(document)
        authority_path.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
        options.update(review_from='2026-04-01',trip_authority_path=str(authority_path))
        options_path.write_text(json.dumps(options,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copy2(ROOT/'tools/launch_web_ledger.py',launcher)
        clone=backup/'rehearsal.sqlite'
        backup_database(db,clone)
        add_europe_trip(clone,europe,digest)
        flow=configured_readonly_flow(clone)
        try:
            kyoto=next(t for t in flow.board.list_trips() if t['destination']=='교토')
            probe=dict(merchant='SYNTHETIC LOCAL SHOP',issuer='국민',card_kind='해외',
                       approval_date=kyoto['starts_on'],raw_row={'c8':'JP'})
            if flow.retail_trip(probe,'JP')!=kyoto['tab_id']:
                raise RuntimeError('MULTIPLE_TRIP_LOCATION_MATCH_FAILED')
            rehearsal=apply_rules(clone,report,flow=flow)
            first=current_rows(clone)
            repeat=apply_rules(clone,report,flow=flow)
            if rehearsal['counts']!=repeat['counts'] or first!=current_rows(clone):
                raise RuntimeError('REPEATED_CLASSIFICATION_CHANGED_RESULT')
        finally:
            flow.board.conn.close()
        if database_state(db)!=before:
            raise RuntimeError('LIVE_DATABASE_CHANGED_DURING_REHEARSAL')
        europe_trip_id=add_europe_trip(db,europe,digest)
        flow=configured_readonly_flow(db)
        try:
            result=apply_rules(db,report,flow=flow)
        finally:
            flow.board.conn.close()
        if result['counts']!=rehearsal['counts']:
            raise RuntimeError('OPERATIONAL_CLASSIFICATION_DIFFERS')
        after=database_state(db)
        for table in ('board_rows','board_revisions','owner_profile','review_decisions',
                      'ledger_entries','review_source_guidance'):
            if before.get(table)!=after.get(table):
                raise RuntimeError('EXISTING_USER_DATA_CHANGED:'+table)
        with readonly(db) as current:
            events=list(current.execute('SELECT * FROM decision_events'))
            if not old_events<={tuple(row) for row in events}:
                raise RuntimeError('EXISTING_AUDIT_EVENT_CHANGED')
            added=[row for row in events if tuple(row) not in old_events]
            if len(added)>1 or any(row['stream_id']!='trip-'+europe_trip_id or row['action']!='propose'
                                   or row['actor_local_id']!='owner' for row in added):
                raise RuntimeError('UNEXPECTED_AUDIT_EVENT_ADDED')
        result.update(backup=str(backup),rehearsal_verified=True,repeated_classification_stable=True,
                      europe_period={k:europe[k] for k in ('starts_on','ends_on','countries')},
                      europe_stays=len(europe['stays']),review_from='2026-04-01',status='deployed')
        result.update(existing_audit_events_preserved=len(old_events),new_trip_audit_events=len(added))
        (OUTPUT/'applied.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    except Exception:
        backup_database(backup/'board.sqlite',db)
        if database_state(db)!=before:
            raise RuntimeError('OPERATIONAL_ROLLBACK_FAILED')
        for path,original in originals.items():
            if original is not None:
                path.write_bytes(original)
            elif path.exists():
                if not path.resolve().is_relative_to(host.resolve()):
                    raise RuntimeError('ROLLBACK_PATH_OUTSIDE_HOST')
                path.unlink()
        (OUTPUT/'applied.json').write_text(json.dumps({'status':'rolled_back'}),encoding='utf-8')
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/'failure.json').write_text(json.dumps({'type':type(exc).__name__,'code':str(exc),
                                                     'traceback':traceback.format_exc()},indent=2),encoding='utf-8')
        print('HISTORY_RULE_RECOVERY_FAILED:'+type(exc).__name__)
        raise SystemExit(2) from None
