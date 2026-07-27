# -*- coding: utf-8 -*-
"""마스터의 '기록여부'를 워크북(classified_v10.csv)과 대조해 갱신.
워크북에 반영된 Q2 거래는 Y+uid, 미반영은 N. 해외는 현지금액, 국내는 승인번호/금액으로 매칭."""
import csv, re, os
from domain.master_linking import (
    balanced_ambiguous_master_keys,
    balanced_master_links,
)
HERE=os.path.dirname(os.path.abspath(__file__))
MASTER=os.path.join(HERE,'master_ledger.csv')
CLS=os.path.join(HERE,'..','data','classified_v10.csv')
def rn(x):
    try:return round(float(str(x).replace(',','')))
    except:return 0
def na(a): return re.sub(r'\.0$','',str(a)).lstrip('0')
def ff(x):
    try:return str(round(float(str(x).replace(',','')),2))
    except:return ''
def q2(d): return '2026-04'<=str(d)[:7]<='2026-06'
def main():
    m=list(csv.DictReader(open(MASTER,encoding='utf-8-sig')))
    cls=list(csv.DictReader(open(CLS,encoding='utf-8')))
    balanced_links=balanced_master_links(m, cls)
    ambiguous_group_keys=balanced_ambiguous_master_keys(m, cls)
    cls_by_uid={r['uid']:r for r in cls}
    by_cda={};by_fx={}
    for r in cls:
        by_cda.setdefault((str(r['card4'])[-4:],str(r['use_date'])[:10],abs(rn(r['krw']))),[]).append(r)
        if r.get('foreign') and ff(r['foreign']) not in ('','0.0'):
            by_fx.setdefault((str(r['card4'])[-4:],str(r.get('currency','')),ff(r['foreign'])),[]).append(r)
    rec=0
    for r in m:
        d=r['승인일'] or r['매입일']
        if not q2(d): r['기록여부']=r['기록여부'] or 'N'; continue
        hit=cls_by_uid.get(balanced_links.get(r['거래키'],''))
        if not hit and r['구분']=='해외' and ff(r['현지금액']) not in ('','0.0'):
            candidates=by_fx.get((r['카드4'],r['통화'],ff(r['현지금액']))) or []
            hit=candidates[0] if len(candidates)==1 else None
        if not hit:
            candidates=by_cda.get((r['카드4'],d,abs(rn(r['원화금액'])) or abs(rn(r['현지금액'])))) or []
            hit=candidates[0] if len(candidates)==1 else None
        if hit: r['기록여부']='Y'; r['워크북참조']=hit['uid']; rec+=1
        elif r['거래키'] in ambiguous_group_keys:
            r['기록여부']='N'; r['워크북참조']=''
            marker='ambiguous_group: 승인번호 재적재 후 개별 링크'
            if marker not in (r.get('비고') or ''):
                r['비고']=((r.get('비고') or '')+' | '+marker).strip(' |')
        else: r['기록여부']='N'
    with open(MASTER,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(m[0].keys())); w.writeheader(); w.writerows(m)
    q2r=[r for r in m if q2(r['승인일'] or r['매입일'])]
    print(f'기록여부 갱신: 전체 {len(m)} | Q2 {len(q2r)}(기록Y {rec}/미기록N {len(q2r)-rec}) | 비Q2 {len(m)-len(q2r)}')
if __name__=='__main__': main()
