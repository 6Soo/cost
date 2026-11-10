# OTA 포털 직접 수집 절차 (ego lite) — 2026-11-10

> 상태: 2026-11-10 사용자 지시로 Agoda·Trip.com·Booking.com을 ego lite 로그인 세션에서 직접 조사했다. 이 문서는 그때 실제로 수행·검증한 절차와 결과이며, 다음 에이전트가 같은 수집을 반복할 때의 실행 정본이다. 기존 "Agoda는 Paseo IAB 전용" 규칙보다 이 사용자 결정이 우선한다. 범위는 **읽기 전용 조회**뿐이다.

## 1. 원칙

- 예약 변경·취소·결제·메시지 전송·쿠폰 사용 등 쓰기 동작은 하지 않는다. 화면 버튼은 예약 상세 진입(조회)까지만 누른다.
- 사이트가 화면을 그릴 때 쓰는 **같은 로그인 세션의 내부 API**를 같은 탭에서 `page.fetch()` / `fetch()`로 호출한다. 화면 텍스트보다 구조화돼 있고 재현 가능하다. 새 계정 로그인·우회·보안 확인 통과 시도는 하지 않는다. 로그인이 필요하면 `task.handOff()`로 사용자에게 넘긴다.
- 재시도 한도: 목록 요청 5회, 상세 요청 3회(지수 대기). 실패가 30건을 넘으면 중단한다. 동시 요청은 6개 이하.
- 원본 응답은 비공개 `C:/AX/cost/.local-archive/ota-portal-<날짜>/` 아래에만 둔다. 예약번호·투숙객·카드 끝자리 등 고객 식별자는 Git·PR·문서에 넣지 않는다(건수와 원인만).
- 운영 저장소 반영은 **코드 경로(수입 도구)로만** 한다. 사람이 장부 행을 고치는 것은 근거가 명확한 항목·여행 교정에 한한다(카드 행의 이용일은 화면에서 직접 고칠 수 없다).

## 2. 준비

1. `ego-browser skill`을 읽고 따른다(Windows는 UTF-8 `.mjs` 파일을 `ego-browser nodejs -e "await import('file:///…')"`로 실행).
2. TaskSpace 하나를 만들어 끝까지 재사용한다. 예: `taskSpace("ota portal audit <YYYYMMDD>")`. 스크립트는 `C:/Users/kkokk/ego/ota-portal-audit-<YYYYMMDD>/round-NN.mjs`로 매 회차 새 파일.
3. 로그인 확인(사이트별 아래 절). 로그인이 안 됐거나 **다른 계정**이면 `await task.handOff()` 후 사용자에게 "예약에 쓴 계정으로 로그인"을 요청하고 멈춘다.
4. 요청 형식은 화면에서 한 번 실제 요청을 CDP로 잡아 그대로 재사용한다: `page.cdp("Network.enable")` → 화면 이동 → `page.events()`에서 `Network.requestWillBeSent`의 URL·본문, `Network.getResponseBody`로 응답. 토큰·헤더를 추측해 만들지 않는다.

## 3. Agoda (구현·운영 반영 대상)

| 단계 | 요청 | 비고 |
|---|---|---|
| 로그인 확인 | `https://www.agoda.com/ko-kr/account/bookings.html` | 화면에 "모든 예약"·회원명이 보이면 로그인 상태 |
| 목록 | `POST /api/ko-kr/mmbc/v2/GetBookingsList` | 화면 요청 본문 재사용. `bookingPhase`: `Upcoming`/`Completed`/`Cancelled`, `pageIndex` 1부터, `pageSize` 40, `includeArchive: true`, `pagination.totalPages`까지. 응답 `bookings[]`에 `bookingId`, `itineraryId`, `bookingDate`, 숙박일, `legacyBookingToken` |
| 상세 | `POST /api/ko-kr/mmbc/eb/details` 본문 `{BookingToken: <legacyBookingToken>, isApp: false, token: <화면 요청의 token>}` | 응답 `BookingDetails.BookingQueryData.CancellationReasonData.BookingID`가 목록 `bookingId`와 같아야 저장 |

- 저장 형식: 예약 하나당 파일 `agoda/details/<bookingId>.json` = `{"observed_at": ISO(시간대 포함), "list": 목록 항목, "detail": 상세 응답}`.
- 대상: 장부 범위(예약일 2025-10-01 이후 또는 숙박 시작 2026-03-01 이후). 2026-11-10 실측 1,418건, 동시 6건으로 약 5분.
- 해석 규칙(`app/agoda_api_capture.py`):
  - 결제: `NonCancelledPaymentDetails.Payments` 중 카드 줄. 음수 줄(부분 환급·조정)이 있으면 결제로 쓰지 않고 환불 검토로 보류.
  - 결제 예정: 상태 문구 "자동 결제 예정" 또는 `PayLaterInfo` 존재 → 청구 아님. 청구가 끝나면 `PayLaterInfo`가 사라지고 **청구일은 API 어디에도 없다** → 결제일은 비워 두고 카드 끝자리·정확 금액 상호 유일 추론에만 맡긴다.
  - `PaymentModel = pay-hotel`: 숙소 현장 결제. Agoda 청구가 아니다.
  - 취소: `CancelledPaymentDetails.TotalAmountCharged`(청구액), `CancellationFee`, `YourRefund`. 환불이 있으면 보류, 수수료로 전액 남으면 취소 예약의 실제 비용.
  - 엔화 요금을 나중결제로 원화 카드에 청구하면 카드 금액은 청구일 환율의 원화라 상세 금액과 정확히 일치하지 않는다.
- 운영 반영:
  1. `python tools/import_agoda_api_details.py --directory <details>` (요약만, 오류 0 확인)
  2. 정기 `mail-collect`(Worker, 매시 실행) 시간을 피해, `D:/WebLedgerHost/data/ota-evidence.sqlite`를 같은 폴더에 날짜 사본으로 백업
  3. 운영 릴리스의 같은 도구로 `--apply --store D:/WebLedgerHost/data/ota-evidence.sqlite` (계정 키 `aside-u0` = 기존 화면 캡처와 같은 계정. 같은 관측 재수입은 무변경)
  4. Board의 OTA 재계산 `refresh_done` 후 장부 경고 재집계(인증 GET, `ledger-recount` 스크립트)

## 4. Booking.com (조사 완료, 자동 반영은 후속)

| 단계 | 요청 | 비고 |
|---|---|---|
| 로그인 확인 | `https://secure.booking.com/mytrips.ko.html` | 회원명·Genius 표시 |
| 여행 목록 | `POST /dml/graphql?lang=ko` `operationName: UserTrips` | 화면 요청의 query 재사용. `tripFilter`는 `PAST`/`CANCELLED`만 유효(`UPCOMING`은 오류). 두 번째 페이지 커서 요청이 서버 오류를 내므로 `first` 50으로 한 번에 받는다 |
| 여행별 예약 | `https://secure.booking.com/mytrips.ko.html?tid=<trip id>&tab=bookings` 화면 텍스트 | 서버 렌더링. 예약별 숙소/항공, 기간, 상태(완료·취소됨), 원화 표시 요금. 일부만 `confirmation.ko.html?auth_key=…` 링크가 있다 |

- 결과: 카드 가맹점 `Booking.com<숫자 11자리>`(원화) 결제는 **Booking.com에서 산 항공권**이었다(숙박비로 잘못 분류). `BKG*BOOKING.COM HOTEL`(엔화)은 숙소 결제이며, 화면의 원화 표시 요금은 환산값이라 카드 금액과 정확히 맞지 않는다 → 정확 대사에는 숙소 통화 금액이 있는 확인 페이지가 필요하다.
- 후속: Booking 항공권 확정 메일/확인 페이지에서 출발일을 읽는 파서, `Booking.com\d{11}` 가맹점의 항공료 분류 규칙.

## 5. Trip.com (조사 완료, 자동 반영은 후속)

| 단계 | 요청 | 비고 |
|---|---|---|
| 로그인 | `https://kr.trip.com/account/signin` → 이메일 입력 → "이메일 계정으로 계속하기" | 비밀번호 없이 **예약 계정 이메일로 인증번호**가 온다. 에이전트는 번호를 요청만 하고, 사용자가 알려 준 번호를 입력한다. 다른 계정이 로그인돼 있으면 화면에 "이미 다음의 계정으로 로그인하셨습니다"가 나오며 그 아래 이메일 로그인으로 진행한다. `membersinfo/profile/`에서 연동 이메일을 확인 |
| 주문 목록 | `POST https://online.trip.com/restapi/soa2/26974/getAllOrders.json` | 화면 요청 본문 재사용. `OrderStatusClassify: "All"`, `Count` 20, 날짜 조건 비움, 응답 `Offset` 토큰으로 다음 페이지. 2026-11-10 실측 1,002건(호텔 736·항공 241·렌터카 18 등). 주문의 `OrderActions[].ActionURLH5`(OrderDetail)에 `tripsignature`가 있다 |
| 호텔 주문 상세 | `POST https://kr.trip.com/restapi/soa2/27453/GetOrderDetailOnline` | 화면 요청 본문의 `orderId`와 `FrontHead.sign`(=tripsignature)만 바꿔 호출. 장부 범위 호텔 주문 502건, 동시 6건 |

- 상세 해석:
  - `orderCommonInfo.checkInDate/checkOutDate`(YYYYMMDD), `orderStatusCode`(2003 확정·2005 체크아웃 완료·2006 취소 등)
  - `priceInfo.tripPriceDetail.additionalInfo.payType` 5 = **현장 결제 + 카드 보증**. 이때 `preAuthorizationInfo`(KRW 금액)가 카드에 잡히는 **사전승인**이고, `priceSummary`의 `현장 결제 JPY…`가 실제 숙박비(호텔이 현장에서 받음)다.
  - `paymentDetailInfo.subItemList`: 카드사·금액(KRW). `refundInfo.refundDetialInfo.itemInfo`: 환불 카드 끝자리·금액·`환불 완료`(SUCCESS).
  - 엔화 요금을 Trip이 원화로 받는 경우 같은 날 주문들은 같은 환율이 적용된다(실측 8.8971).
- 결과: 장부의 Trip "숙박비" 경고 중 23행은 숙박비가 아니라 **카드 사전승인**이며 대부분 체크아웃 후 환불 완료(취소 주문은 일부 환불·잔액 존재). 카드 원행에는 승인일만 있어 장부가 이를 숙박비로 분류하고 있었다.
- 자동 보강안(후속 구현): 상세를 `trip-api-v1` 사실로 바꿔 `OtaStore.import_direct(provider='trip')`로 넣고, 결제 대사에서 `payType=5`의 사전승인을 "보증(환불 예정/완료)"으로, 같은 금액의 카드 취소 원행과 짝지어 표시한다. 장부에는 "카드 사전승인 · 숙박 MM.DD–MM.DD 현장 결제 · 환불 완료"처럼 표시하고 숙박비 합계에서 순액 0이 되게 한다. 실제 숙박비는 호텔 현장결제 카드 원행(현장 결제 표시 규칙)이 담당한다.

## 6. 2026-11-10 결과 요약 (식별자 없음)

| 공급자 | 장부 경고 행 | 결과 |
|---|---|---|
| Agoda | 33(카드) + 캐시 사용 수동행 2 | 18행을 상세 근거로 특정(청구 후 미갱신된 나중결제 10, 취소 예약의 청구 8). 15행(주로 다른 카드의 원화 청구)은 이 계정 예약 어디에도 금액·환산율이 맞지 않음 → 다른 계정 예약 추정, 미해결 |
| Booking.com | 11 | 원화 3행은 항공권(그중 2행 항목·여행 교정 완료), 0613 2행은 이미 연결됐지만 묶음 연결 조건으로 미표시, 나머지 엔화 숙소 결제는 정확 금액 근거 필요 |
| Trip.com | 38 | 예약 계정 로그인 후 조회: 23행은 현장결제 호텔의 카드 사전승인(대부분 환불 완료), 3행은 실제 Trip 결제, 12행은 항공·렌터카 또는 범위 밖 주문 |

- 근본 원인: 포털 근거가 2026-10-21 화면 캡처에서 멈춰 있어, 이후 청구된 나중결제·취소 예약 결제가 대사되지 않았다. 이 절차를 주기적으로(예: 주 1회, 또는 나중결제 청구 시점 이후) 반복하고 수입 도구로 넣으면 자동 보강된다.

## 7. 운영 반영 결과 (2026-11-10)

- [#783](https://github.com/6Soo/cost/pull/783) 배포(`895a412e`) 후 `D:/WebLedgerHost/data/backups/ota-evidence-before-agoda-api-20261110.sqlite`(무결성 ok) 백업 → 상세 1,418건 단일 트랜잭션 수입(오류 0, 1,418 삽입) → OTA 재계산.
- 결과: 단일 결제 3건 자동 연결과 같은 기간 2객실 묶음 2건 표시로 Agoda 5행이 해소됐고, 같은 시점 집계의 Agoda 경고는 35 → 31(전체 182 → 178, 다른 행 1건이 새로 경고)이었다. 같은 금액·같은 기간 객실 N개를 카드 N장으로 결제한 경우는 1:1 유일성이 없어 남았고, [#784](https://github.com/6Soo/cost/pull/784)(`998dd461`)의 표시 전용 동일 객실 규칙으로 3건 추가 해소 → Agoda 28, 전체 장부 경고 182 → 175.
- 남은 Agoda 28: 취소 예약의 청구(전액 환불 또는 취소 수수료) 8행은 취소 예약이라 숙박 이용일이 없다 — "취소된 예약" 표시 규칙은 후속. 나머지는 이 계정 예약에 금액·환산율이 맞는 근거가 없다(다른 계정 추정).
- 반복 주기: 나중결제는 청구 뒤에야 결제 근거가 생기므로, 주 1회 또는 큰 여행 직후 이 절차(목록 → 상세 → 수입)를 다시 실행한다. 이미 받은 예약도 상태가 바뀌었을 수 있어 다시 받는다(같은 내용은 수입 시 무변경).
