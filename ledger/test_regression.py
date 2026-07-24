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

print('== 전체 합계 스냅샷(참고용 — 의도적 변경이면 아래 EXPECTED만 갱신) ==')
total = sum(float(r['krw'] or 0) for r in rows)
EXPECTED_TOTAL = 311_627_192
EXPECTED_ROWS = 1702
print(f'  현재: {len(rows)}행 {total:,.0f}원 / 기준: {EXPECTED_ROWS}행 {EXPECTED_TOTAL:,}원')
if total != EXPECTED_TOTAL or len(rows) != EXPECTED_ROWS:
    print('  ⚠ 기준과 다름 — 의도된 변경이면 이 스크립트의 EXPECTED_TOTAL/EXPECTED_ROWS를 갱신할 것')

print()
if FAILS:
    print(f'❌ 회귀 실패 {len(FAILS)}건:', FAILS)
    sys.exit(1)
else:
    print('✅ 회귀 테스트 전부 통과')
