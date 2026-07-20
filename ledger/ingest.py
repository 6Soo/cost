# -*- coding: utf-8 -*-
"""AI-Native 카드거래 마스터 증분 적재기.
사용: python3 ingest.py <xlsx파일...>   (원본이 .xls면 먼저 libreoffice로 xlsx 변환)
동작: 파일 형식 자동판별 → 정본 정규화 → master_ledger.csv에 '거래키' 기준 신규건만 병합
      (기존 행의 기록여부/워크북참조 보존). 일자 겹쳐도 중복은 자동 제외."""
import openpyxl, csv, re, os, sys
HERE=os.path.dirname(os.path.abspath(__file__)); MASTER=os.path.join(HERE,'master_ledger.csv')
FIELDS=['거래키','카드사','카드4','구분','승인일','매입일','가맹점','원화금액','현지금액','통화','승인번호','취소여부','출처','적재일','기록여부','워크북참조','비고']
def rn(x):
    try:return round(float(str(x).replace(',','').replace('원','').strip()))
    except:return 0
def d10(s):
    m=re.search(r'(\d{4})[.\-](\d\d)[.\-](\d\d)',str(s)); return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else ''
def mk(m): return re.sub(r'[^A-Z0-9가-힣]','',str(m).upper())[:10]
def load(f):
    wb=openpyxl.load_workbook(f,read_only=True); ws=wb[wb.sheetnames[0]]
    return [[('' if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]

def detect(rows):
    flat=' '.join(rows[0])+' '+(' '.join(rows[5]) if len(rows)>5 else '')
    if '승인취소금액' in flat and '승인번호' in flat: return '하나승인'
    if '통화코드' in flat and '현지이용금액' in flat: return '국민해외매입'
    if '부가세' in flat and '승인금액' in flat and '매입일' in flat: return '국민국내매입'
    if rows and rows[0] and rows[0][0] in ('원화','외화','취소또는할인'): return '기업승인'
    return None

def norm(rows, src, today):
    out=[]
    def emit(카드사,c4,구분,승,매,가맹,krw,fx,cur,ap,cx):
        ap=re.sub(r'\.0$','',str(ap)).lstrip('0')
        if ap: key=f'{카드사}|{c4}|A{ap}|{"취소" if cx else "정상"}|{abs(krw)}'
        else:  key=f'{카드사}|{c4}|{승 or 매}|{abs(krw) or fx}|{mk(가맹)}|{"취소" if cx else "정상"}'
        out.append(dict(거래키=key,카드사=카드사,카드4=c4,구분=구분,승인일=승,매입일=매,가맹점=가맹,원화금액=krw,
            현지금액=fx,통화=cur,승인번호=ap,취소여부='취소' if cx else '정상',출처=src,적재일=today,기록여부='N',워크북참조='',비고=''))
    if src=='기업승인':
        for r in rows:
            if len(r)>13 and re.match(r'\d{4}-\d\d-\d\d',r[2] or ''):
                cx=(r[0]=='취소또는할인'); cur='JPY' if 'JPY' in (r[7] or '') else ''
                emit('기업',r[3][-4:],'해외' if r[0]=='외화' else '국내',r[2][:10],'',r[5],rn(r[6])*(-1 if cx else 1),rn((r[7] or '').split()[0] if r[7] else 0),cur,r[13],cx)
    elif src=='하나승인':
        for r in rows[6:]:
            if r and r[0] and r[0]!='NO' and '-' in (r[3] or ''):
                gu='해외' if '해외' in (r[11] if len(r)>11 else '') else '국내'
                emit('하나',r[3][-4:],gu,d10(r[1]),'',r[7],rn(r[5]),0,'',r[4],False)
                if rn(r[6]): emit('하나',r[3][-4:],gu,d10(r[1]),'',r[7],rn(r[6]),0,'',r[4],True)
    elif src=='국민국내매입':
        for r in rows[1:]:
            if len(r)>11 and re.match(r'\d{4}\.\d\d',r[1] or ''):
                a=rn(r[11]); emit('국민',r[5][-4:],'국내',d10(r[1]),d10(r[0]),r[7],a,0,'','',a<0)
    elif src=='국민해외매입':
        for r in rows[1:]:
            if len(r)>12 and re.match(r'\d{4}\.\d\d',r[0] or ''):
                emit('국민',r[4][-4:],'해외','',d10(r[0]),r[7],0,rn(r[11]),r[10],'',r[6]=='취소매출')
    return out

PRESERVE={'거래키','기록여부','워크북참조'}   # 병합해도 절대 안 덮는 필드(기록상태 보존)
def merge_into(ex, new):
    """있는 건 병합: 새 행의 값으로 기존 빈 필드를 채움(보강). 바뀐 게 있으면 True."""
    changed=False
    for k,v in new.items():
        if k in PRESERVE: continue
        v=('' if v is None else str(v)).strip()
        exv=('' if ex.get(k) is None else str(ex.get(k))).strip()
        if v and not exv:
            ex[k]=v; changed=True
    return changed

def main(files, today='2026-07-20'):
    master=list(csv.DictReader(open(MASTER,encoding='utf-8-sig'))) if os.path.exists(MASTER) else []
    index={r['거래키']:r for r in master}
    added=merged=same=0
    for f in files:
        rows=load(f); src=detect(rows)
        if not src: print(f'  ⚠ 형식판별 실패: {f}'); continue
        recs=norm(rows,src,today); a=m2=s=0
        for r in recs:
            ex=index.get(r['거래키'])
            if ex is None:                      # 없는 건 → 채워넣기
                index[r['거래키']]=r; master.append(r); a+=1
            elif merge_into(ex,r):              # 있는 건 → 병합(보강)
                m2+=1
            else:                               # 같은 건 → 버림
                s+=1
        added+=a; merged+=m2; same+=s
        print(f'  {os.path.basename(f)} [{src}] {len(recs)}건 → 신규 {a} / 병합 {m2} / 동일버림 {s}')
    with open(MASTER,'w',encoding='utf-8-sig',newline='') as fo:
        w=csv.DictWriter(fo,fieldnames=FIELDS); w.writeheader(); w.writerows(master)
    print(f'== 마스터 {len(master)}건 (이번 신규 {added} / 병합 {merged} / 동일버림 {same}) ==')

if __name__=='__main__':
    if len(sys.argv)<2: print('사용: python3 ingest.py <xlsx...>'); sys.exit(1)
    main(sys.argv[1:])
