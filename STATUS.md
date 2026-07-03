# 진행 상황 · 세션 핸드오프

주식회사 숲길여행 법인카드 비용처리 자동화. 이 문서는 **다음 세션이 이어받기 위한 요약**이다.
설계 근거는 `docs/`, 구현은 `apps-script/`.

## 한 줄 요약
카드내역(RAW) → 자동 분류 → 여행별 `_C` 탭에 전기 + RAW 색칠까지의 엔진과,
결제/예약 **이메일 파싱** 계층, **학습 루프**가 코드·문서로 완성됨.
현재는 **실제 배포/검증 직전** 단계.

## 확정된 핵심 결정
1. **실행 환경 = Google Apps Script**, 계정 `kkokkohero6@gmail.com` **단일 계정**.
   - 이 계정이 메일함 + 시트 5개를 **모두 소유** → 추가 공유 0회.
   - (이 개발 샌드박스는 구글 접근이 정책상 차단 → 코드만 여기서 작성, 실행은 Apps Script.)
2. **프로세스**: 1단계(카드 다운로드→RAW 붙여넣기)만 수동. 2·3·4단계는 "정산 실행" 1회로 통합, 멱등(흰색 행만).
3. **장부 구조**: 진행 장부는 **여행별 탭**(`출발일_지역`, 예 `0630_오제`). 각 탭 오른쪽에
   **비교본 `{탭}_C`** 를 만들어 자동결과 기록(사람이 나란히 대조). 비여행 국내건 → `기타비용_C`.
4. **분류 기준(2단계)**:
   - 실사용일이 **여행 기간(출발일~약7일) 안이면 여행건**(식비/숙박비/교통비/입장료/여비교통비),
     밖의 국내건은 **기타비용**(표준 IFRS 계정: 회의비/복리후생비/소모품비/지급수수료).
   - 해외는 항상 여행. OTA(트립/아고다/부킹)·PG(KCP/페이)는 **이메일 매칭**으로 실사용일·계정 확보.
5. **학습 루프**: HOLD된 건 → `학습대기` 탭(distinct) → 사람이 계정 1회 입력 →
   "학습대기 → 규칙 반영" 메뉴 → `분류규칙` 승격 → 이후 자동. **두 번 안 물음.**
6. 김주형 국내카드 = **`3820`**. (카드 주인별 분류 성향은 `CONFIG.CARD_PROFILES` 참조)
7. **카드 주인별 성향(prior)**: `CONFIG.CARD_PROFILES`(뒷4자리 키). 강한 신호(날짜·키워드·메일매칭)가
   다 빠진 '미상' 건에만 적용되는 기본값 — 확정 분류는 안 덮음.
   - 본인 `3820` = 기타비용 위주, 큰 금액(≥`bigThreshold`)은 항공료 → **여비교통비**.
   - **대표가이드**(별도 한메일 유입) = 숙박비 등 여행성 → 미상 건은 기타로 안 넣고 **여행 귀속 보류**.
     카드 뒷4자리 확인 후 `CARD_PROFILES` 슬롯 활성화 예정.

## 대상 시트 (스프레드시트 ID)
| 역할 | ID |
|---|---|
| RAW 카드내역 ①②③ | `1nYxV9UM9rMRjEhnhdc8evE2xb3z6RxgWd5f5ci6PPdE`, `11jjbN882fdQDcIexuzX-l0yBw02VgIna1jhnJNMkN_o`, `1SiOftobiUJSxSdvBEKL9AmxgQkjzkzDjs2O_8SBoyh4` |
| 26년 1분기 완료 장부(학습) | `1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8` |
| 26년 진행 장부(기록 대상) | `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU` |

## RAW 3포맷 (자동 감지)
- **OVERSEAS_A**(삼성 해외, 5585…): 통화(JPY)·환율 있음. 이용일=2열, 가맹점=8열, 원화=17열.
- **DOMESTIC**(국내, 5585…3820/9800): 시각·업종·사업자 있음. 이용일=2열, 업종=9열, 가맹점=8열, 금액=12열.
- **OVERSEAS_B**(4336…): 순번·결제일 있음, 통화열 없음. 순번=1열, 이용일=2열, 가맹점=8열, 원화=6열.

## 이메일 파서 현황 (`apps-script/GmailIngest.gs`)
| 발신자 | 상태 |
|---|---|
| `KR_HTL_NoReply@trip.com` 트립호텔 | ✅ 체크인·금액·카드·환불 |
| `kr_flt_noreply@trip.com` 트립항공 | ⚠ 탑승일 OK, 금액은 첨부PDF→카드매칭 |
| `KR-SERVICE@agoda.com` 아고다 | ✅ Arrival·금액(JPY)·환불 |
| `easypay_noreturn@easypay.co.kr` KICC | ✅ 상호·상품·금액 |
| booking.com / 네이버페이 / 카카오페이 | ⏳ **샘플 미확보 → 파서 미완성** |

## 지금까지의 실제 진행 (사용자 액션)
- ✅ hanmail(`kkokko-hero@hanmail.net`) → Gmail **POP3 가져오기 성공**
  (`pop.daum.net:995 SSL`, 앱 비밀번호, 라벨 `3820`). backlog 수집 중(수시간~2일).
  - 실패 원인이었던 것: **SSL 체크박스** 꺼짐 → 켜서 해결.

## 다음 세션이 할 일 (우선순위 순)
1. **Gmail 필터**: `from:(trip.com OR agoda.com OR easypay.co.kr OR booking.com OR naver.com OR kakao.com)`
   → 라벨 `결제데이터`, **"기존 대화에도 적용" 체크**(POP로 들어온 과거메일 태깅). 파서 쿼리가 `label:결제데이터`.
2. **Daum 자동전달** 켜기(앞으로 오는 3820 메일 실시간).
3. **STEP 1: Apps Script 설치** (`docs/setup.md`) → 첫 `정산 실행`을 **복사본/새 탭에서 검증**.
4. **미완 파서 채우기**: 사용자에게 booking / 네이버페이 / 카카오페이 샘플메일(발신자+제목+본문) 1통씩 받기.
5. RAW 시트 실제 **헤더 유무(HEADER_ROWS)** 및 첫 데이터행 확인해 CONFIG 확정.
6. **대표가이드 두 번째 한메일 유입**: `kkokkohero6`에 POP3/자동전달로 추가(계정별 라벨),
   대표가이드 **카드 뒷4자리** 확인 → `CARD_PROFILES` 슬롯 활성화. (`docs/email-integration.md` 참조)

## 열린 이슈 / 확인 필요
- RAW 시트에 헤더행이 있는지(현재 `HEADER_ROWS=1` 가정).
- 완료 장부(학습)의 정확한 열/빈열 구조 — 현재 `rebuildKnowledgeBase`는 휴리스틱 파싱.
- 아고다 금액은 JPY라 카드(원화) 금액매칭이 약함 → 예약번호 보강 여지.
- 여행 기간 기본 7일(`TRIP_WINDOW_DAYS`) — 실제 여행별 기간과 대조 필요.
- 배포 검증은 **원본 복사본/새 탭**에서 먼저(데이터 안전).

## 파일 맵
```
README.md              개요·아키텍처
STATUS.md              (이 문서) 핸드오프
docs/design.md         프로세스 재설계·장부 스키마·분류 규칙·여행 라우팅·학습 루프
docs/email-integration.md  Gmail/hanmail 연동 상세
docs/setup.md          전체 켜는 순서 런북
docs/roadmap.md        후속(이메일 인제스천 통합) 로드맵
apps-script/Code.gs        엔진(분류·라우팅·학습·전기·색칠)
apps-script/GmailIngest.gs 결제/예약 메일 파서
apps-script/appsscript.json 매니페스트
```

## 브랜치
`claude/expense-processing-automation-ivhg7j` (이 브랜치에 계속 작업/푸시).
