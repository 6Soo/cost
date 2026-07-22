# 셋업 런북 — 전체 켜는 순서 (kkokkohero6 계정)

모든 것은 `kkokkohero6@gmail.com` 한 계정에서 돈다(메일함·시트 소유 동일).

## STEP 1. Apps Script 설치 (엔진)
1. `kkokkohero6` 로 로그인 → **진행 장부 스프레드시트** 열기.
2. 상단 **확장 프로그램 → Apps Script**.
3. 이 리포의 파일을 그대로 붙여넣기:
   - `apps-script/Code.gs` → 편집기의 `Code.gs`
   - `apps-script/GmailIngest.gs` → **+ → 스크립트** 로 새 파일 추가
   - `apps-script/appsscript.json` → ⚙ 프로젝트 설정 → "매니페스트 표시" 후 내용 반영
4. **저장** → 아무 함수나 **실행** → 권한 승인 팝업에서 스프레드시트·Gmail 접근 **허용**.
5. 장부 스프레드시트 **새로고침** → 상단에 **"비용처리" 메뉴** 생성 확인.

## STEP 2. Gmail 라벨 + 필터 (메일 자동 태깅)
1. Gmail → 왼쪽 **라벨 만들기**: `결제데이터`, (하위) `3820`·`아슬란`, 그리고 `처리완료`.
   - `3820` = 본인(kkokko-hero) 유입, `아슬란` = 대표가이드 계정 유입.
2. Gmail 검색창 **필터 만들기** — 아래 발신자에 `결제데이터` 자동 부여:
   ```
   from:(trip.com OR agoda.com OR easypay.co.kr OR booking.com OR navercorp.com OR kakaocorp.com OR tosspayments.com)
   ```
   → "필터 만들기" → **라벨 적용: 결제데이터** 체크.
   > ⚠️ 네이버페이는 `naverpayadmin_noreply@**navercorp.com**`, 카카오는 `**kakaocorp.com**`에서 발송(naver.com/kakao.com 아님).
   >   기존 필터가 `naver.com`이면 네이버페이 결제메일이 라벨 안 붙으니 위처럼 `navercorp.com`으로 잡고 **"기존 대화에도 적용"** 체크.
3. `3820`(본인 hanmail 유입) 식별 필터: 검색 `to:kkokko-hero@hanmail.net`
   → 필터 만들기 → 라벨 `결제데이터` + `3820`.
4. `아슬란`(대표가이드 계정 유입) 식별 필터: 검색 `to:(대표가이드 한메일주소)`
   → 필터 만들기 → 라벨 `결제데이터` + `아슬란`.

## STEP 3. hanmail(`kkokko-hero@hanmail.net`) → gmail 유입
자세한 화면 순서는 `email-integration.md` 참조. 요약:
- **앞으로 오는 메일** = Daum **자동전달**: Daum메일 ⚙환경설정 → 자동전달 →
  `kkokkohero6@gmail.com`, 원본보관 체크.
- **이미 쌓인 과거분** = Gmail **POP3 가져오기**: Daum에서 POP3 ON →
  Gmail ⚙ → 계정 및 가져오기 → "다른 계정에서 메일 확인" → `pop.daum.net` 포트 `995` SSL,
  가져온 메일 라벨 `3820`.
- **대표가이드 계정**도 동일 방식으로 추가(자동전달/POP3), 단 **라벨은 `아슬란`**.
  (POP3는 Gmail당 최대 5계정, 자동전달은 무제한 — 계정마다 반복)

## STEP 4. 자동 실행 트리거
Apps Script 편집기 → 왼쪽 **⏰ 트리거** → **트리거 추가**:
- 함수 `ingestPaymentEmails` · 이벤트 **시간 기반** · **6시간마다** (메일 → '메일수집' 탭).
- (선택) 함수 `runReconciliation` · 시간 기반 6시간마다, 또는 **메뉴에서 수동 실행**.

## STEP 5. 평소 운영 루틴
1. 카드사에서 사용내역 다운로드 → RAW 시트에 붙여넣기(흰색 = 미분류).
2. 장부 메뉴 **비용처리 → 정산 실행** (또는 트리거 자동).
   - 확정분: 실제 여행 탭의 '지출 내용' 섹션에 직접 기록 + RAW 완료색(옛 `_C` 비교탭 방식은 폐기).
   - 매출취소: 매출취소색.
   - 애매: `학습대기` 탭에 distinct 축적.
3. `학습대기` 탭에서 **계정과목만 입력** → 메뉴 **비용처리 → 학습대기 → 규칙 반영**.
   - 이후 같은 가맹점은 자동 분류(두 번 안 물음).

## 데이터 흐름 요약
```
카드 다운로드 ─▶ RAW 시트(수동 붙여넣기)
결제/예약 메일 ─▶ Gmail(라벨) ─▶ GmailIngest ─▶ '메일수집' 탭(구조화)
                                                     │
RAW(미분류) ─▶ runReconciliation ─(금액/예약번호 매칭)─┘
   ├─ 확정 ─▶ 실제 여행탭 / '기타비용' 탭 지출 섹션에 직접 전기 + RAW 완료색
   ├─ 취소 ─▶ RAW 매출취소색
   └─ 보류 ─▶ '학습대기' 탭 ─(사람 1회 입력)─▶ '분류규칙' ─▶ 이후 자동
```
