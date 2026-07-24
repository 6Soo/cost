# -*- coding: utf-8 -*-
"""회귀 테스트(2026-07-24, 사용자 지시 "3번 적용"): 이번 세션에 발견된 '문제였던 행'들을
고정 케이스로 박아두고, 파이프라인을 고칠 때마다 먼저 이걸 돌려 같은 버그가 재발하지 않는지
확인한다. classified_v14.csv 재생성 직후 실행: `python3 test_regression.py`.
실패하면 종료코드 1 — 사람이 워크북을 열어보기 전에 여기서 먼저 잡는 게 목적이다."""
import csv, sys

FAILS = []
def check(name, cond, detail=''):
    if cond:
        print('  ✓', name)
    else:
        print('  ✗', name, '—', detail)
        FAILS.append(name)

rows = list(csv.DictReader(open('data/classified_v14.csv', encoding='utf-8')))
by_uid = {r['uid']: r for r in rows}
notes_all = ' '.join(r['note'] or '' for r in rows)

print('== RESIDHOTEL(마르세유) 승인취소 유령거래 회귀 ==')
check('MISC-0008(RESIDHOTEL 유령거래) 제거됨', 'RESIDHOTEL' not in ' '.join(
    r['merchant'] for r in rows if r['bucket'] in ('카드사용내역_미배정', 'OTA_미배정') and float(r['krw'] or 0) < 0),
    '카드사용내역_미배정/OTA_미배정에 RESIDHOTEL 음수건이 남아있음')
if 'HAN-3328' in by_uid:
    check('HAN-3328(RESIDHOTEL 승인취소) krw=0 유지', float(by_uid['HAN-3328']['krw'] or 0) == 0,
          by_uid['HAN-3328']['krw'])

print('== 승인취소(미매입) 유령거래 클래스 전체 회귀 ==')
GHOST_MERCHANTS = ['카카오T택시_가승인', 'TOTAL                    MARSEILLE 6  FR',
                   'AVIS BUDGET MARSEILLE APTMARIGNANE CEDFR']
for m in GHOST_MERCHANTS:
    hit = [r for r in rows if r['merchant'] == m and float(r['krw'] or 0) < 0
           and r['bucket'] in ('카드사용내역_미배정', 'OTA_미배정')]
    check(f'{m.strip()} 유령 음수건 없음', not hit, hit)

print('== 무쓰그랜드호텔(KBD-0782/0783) 취소환불 페어링 회귀 ==')
if 'KBD-0782' in by_uid and 'KBD-0783' in by_uid:
    a, b = by_uid['KBD-0782'], by_uid['KBD-0783']
    check('둘 다 취소환불 버킷', a['bucket'] == '취소환불' and b['bucket'] == '취소환불')
    check('금액 상쇄(net0)', float(a['krw']) + float(b['krw']) == 0)

print('== KBO-0360(Lotte Arai 예약1740166023) 미입력 stale 태그 회귀 ==')
CONFIRMED_UIDS = ['KBO-0360', 'KBD-0377', 'KBD-0384', 'HAN-0512']
for uid in CONFIRMED_UIDS:
    if uid in by_uid:
        check(f'{uid} 미입력 태그 없음', '미입력' not in (by_uid[uid]['note'] or ''),
              by_uid[uid]['note'])

print('== 트립닷컴_하시다테 베이 호텔(예약1400823535413714) 배치 회귀 ==')
if 'TRIP-0016' in by_uid:
    r = by_uid['TRIP-0016']
    check('0408_교토 탭 유지', r['bucket'] == '0408_교토', r['bucket'])
    check('예약번호 note 보존', '1400823535413714' in (r['note'] or ''))

print('== 0413_나가센도 고마가네 다객실 동일가 dedup 오제거 회귀(2026-07-24 사용자 지적) ==')
# 예약번호도 없고 desc_core도 같아("숙박") 구분자가 전혀 없는 다객실 동일가 항목(62,496원 2건,
# 수기29·30행)이 ①B dedup에서 "동일 중복"으로 오판돼 1건 삭제됐었다 — 수기 원본 행번호를 키에
# 포함해 물리적으로 다른 행은 절대 안 지우게 고쳤다.
komagane = [r for r in rows if r['bucket'] == '0413_나가센도' and r['merchant'] == '트립닷컴_고마가네'
            and abs(float(r['krw'] or 0) - 62496) < 1]
check('고마가네 62,496원 2건 모두 보존(다객실 동일가, 예약번호 없음)', len(komagane) == 2,
      [(r['uid'], r['note']) for r in komagane])

print('== PG 결제대행 동일가맹명 오병합 회귀(2026-07-24 사용자 "전수조사한거아니었어" 지적) ==')
# ①TRIP중복→병합 단계가 가맹명+금액(±2%)만으로 병합 판정하던 버그 — KCP(결제대행) 같은 PG는
# 서로 다른 실거래도 가맹명이 동일하게 찍혀, 승인번호가 다른데도(TRIP-0094 appr30057417 vs
# KBD-0777 appr30057653, 각각 3/22·4/14 별개 트래블로버 보험 결제) 하나로 오병합됐었다.
if 'TRIP-0094' in by_uid and 'KBD-0777' in by_uid:
    check('트래블로버 2건(3/22·4/14) 둘 다 보존(승인번호 다른 별개 실거래)', True)
else:
    check('트래블로버 2건 둘 다 보존', False, f"TRIP-0094={'TRIP-0094' in by_uid}, KBD-0777={'KBD-0777' in by_uid}")

print('== 수기장부 재생성 이중계상 회귀(2026-07-24, 원장이 patch_v14 확정건을 자연 편입할 때) ==')
# 원장이 갱신돼 manual_v3.csv가 patch_v14의 RESTORE 대상과 같은 실거래를 자연스럽게 잡아내면
# uid는 다르지만(TRIP-NNNN) 같은 예약, 같은 탭·금액으로 두 번 잡힐 위험이 있다(실측: 롯데
# 아라이 1740166023이 KBO-0360과 TRIP-0393로 이중계상될 뻔함, 팔레즈 241,350이 TRIP-0233과
# MAN-FALAISE로 이중계상될 뻔함). 탭+금액 조합의 등장 횟수로 이중계상을 감시한다.
DUP_WATCH = [('0620_묘코', 227340, '롯데 아라이(예약1740166023)'), ('0620_묘코', 230782, '롯데 아라이(카드매칭 변형)'),
             ('5월_유럽', 241350, '호텔 데 팔레이즈(예약1400826104512972)')]
for bucket, amt, label in DUP_WATCH:
    hits = [r for r in rows if r['bucket'] == bucket and abs(float(r['krw'] or 0) - amt) < 1]
    check(f'{label} 탭+금액 중복 없음(1건 이하)', len(hits) <= 1,
          [(h['uid'], h['krw']) for h in hits])

print('== 전체 합계 스냅샷(참고용 — 의도적 변경이면 아래 EXPECTED만 갱신) ==')
total = sum(float(r['krw'] or 0) for r in rows)
EXPECTED_TOTAL = 318_134_680
EXPECTED_ROWS = 1819
print(f'  현재: {len(rows)}행 {total:,.0f}원 / 기준: {EXPECTED_ROWS}행 {EXPECTED_TOTAL:,}원')
if total != EXPECTED_TOTAL or len(rows) != EXPECTED_ROWS:
    print('  ⚠ 기준과 다름 — 의도된 변경이면 이 스크립트의 EXPECTED_TOTAL/EXPECTED_ROWS를 갱신할 것')

print()
if FAILS:
    print(f'❌ 회귀 실패 {len(FAILS)}건:', FAILS)
    sys.exit(1)
else:
    print('✅ 회귀 테스트 전부 통과')
