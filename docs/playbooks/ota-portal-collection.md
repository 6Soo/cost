# OTA 포털 직접 수집 절차 (ego lite) — 2026-11-10

> 상태: 2026-11-10 사용자 지시로 Agoda·Trip.com·Booking.com을 ego lite 로그인 세션에서 직접 조사했다. 이 문서는 그때 실제로 수행·검증한 절차와 결과이며, 다음 에이전트가 같은 수집을 반복할 때의 실행 정본이다. 기존 "Agoda는 Paseo IAB 전용" 규칙보다 이 사용자 결정이 우선한다. 범위는 **읽기 전용 조회**뿐이다.

## 1. 원칙

- 예약 변경·취소·결제·메시지 전송·쿠폰 사용 등 쓰기 동작은 하지 않는다. 화면 버튼은 예약 상세 진입(조회)까지만 누른다.
- 사이트가 화면을 그릴 때 쓰는 **같은 로그인 세션의 내부 API**를 같은 탭에서 `page.fetch()` / `fetch()`로 호출한다. 화면 텍스트보다 구조화돼 있고 재현 가능하다. 새 계정 로그인·우회·보안 확인 통과 시도는 하지 않는다. 로그인이 필요하면 `task.handOff()`로 사용자에게 넘긴다.
- 재시도 한도: 목록 요청 5회, 상세 요청 3회(지수 대기). 실패가 30건을 넘으면 중단한다. 동시 요청은 6개 이하.
- 원본 응답은 비공개 `C:/AX/cost/.local-archive/ota-portal-<날짜>/` 아래에만 둔다. 예약번호·투숙객·카드 끝자리 등 고객 식별자는 Git·PR·문서에 넣지 않는다(건수와 원인만).
- 운영 저장소 반영은 **코드 경로(수입 도구)로만** 한다. 사람이 장부 행을 고치는 것은 근거가 명확한 항목·여행 교정에 한한다(카드 행의 이용일은 화면에서 직접 고칠 수 없다).

## 2. 준비

> 2026-11-12 마무리 결정: 이번 실제 수집은 종료했다. 실화면 경고69건의 [읽기 전용 진단](../agents/artifacts/ota-portal-warning-diagnostics-20261112.md)을 남겼으며 이전148건 기준이나 아래 후속 확인 항목을 추가 수집 지시로 실행하지 않는다. 원문 최종 보존 경로는 `D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/`다. 아래 worktree 보호 경로는 수집 당시 위치이며 preservation-manifest.json으로 최종 위치에 대응된다.

### 2026-11-12 실제 화면·응답 확인

아래 8항목의 실제 관측은 이번 작업 폴더의 비공개 `.local-archive/ota-portal-20261112/`에 보존했다. 로그인·API 토큰·서명·계정 식별값은 문서에 옮기지 않는다. 이번 지시는 로그인 시도와 `task.handOff()`를 금지했으므로 기존 로그인 세션에서 조회만 했으며, 운영 코드 수정·배포는 하지 않았다.

| 항목 | 실제 확인과 남은 제한 |
| --- | --- |
| 1. 로그인·계정 | 세 사이트 모두 예약 목록을 확인했다. Trip은 `/account/signin`에서 기존 로그인 표시를 읽기만 하고, `/membersinfo/profile/`의 `My 예약` → `호텔`로 `/order/hotel`에 진입했다. 로그인 입력·계정 전환은 하지 않았다. |
| 2. 요청 원형 | 아래 표의 API origin/path를 실제 요청으로 확인했다. 요청 본문 전체는 보호 폴더에만 저장하고 필요한 예약 ID·페이지 입력만 바꿨다. Agoda 상세에는 기존 세 필드 외 `isRequiredSignIn`, Trip 상세에는 `retToken`, `token`, `FrontHead`, `head`가 있었다. |
| 3. Agoda 토큰·정렬 | 상세 조회에서 관측한 token을 사용했다. 화면 초기값 `BookingStartDate`/`Ascending`은 오래된 완료·취소 예약부터 반환했다. 화면의 정렬 메뉴에서 **예약 날짜**를 선택하여 `sortBy: BookingDate`, `sortOrder: Descending`을 확인한 뒤 최근 완료·취소를 추가 수집했다. 세 phase 모두 조회했다. |
| 4. Trip 다음 페이지 | 실제 목록 본문에 최상위 `Offset` 문자열이 있었다. 화면 Count는 5, 이번 수집은 기존 절차의 Count 20으로 5페이지·100건을 받았다. 관측된 `BizTypes`는 `Hotel`, `Tuan`으로 호텔 범위이며 항공·렌터카 전체 수집이 아니다. 날짜 조건은 비어 있었다. |
| 5. Trip 상세 | `ActionCode: OrderDetail`의 상대 URL을 실제 `kr.trip.com` origin에 결합했다. 목록 링크의 `tripsignature`와 상세 요청 `FrontHead.sign`, 목록 주문과 상세 요청 주문의 일치를 확인했다. 상세 100건은 기존 도구의 응답 주문 동일성 검사도 통과했다. |
| 6. Booking query·variables | 실제 `UserTrips` query와 `variables: {first: 50, filter: {tripFilter: PAST 또는 CANCELLED}, sortBy: DATE_DESC}`를 재사용했다. 두 목록 모두 50건·`pageInfo.hasNextPage: true`이므로 전체 완료가 아니다. 범위 내 여행 화면 12건을 `tid`/`tab=bookings` 조회로 보존했으며 예약 사실 파서·공식 가져오기 경로는 없어 운영 반영하지 않았다. |
| 7. 배열·완전성 | Trip의 실제 배열은 **`OrderEnities`**이며 도구가 예상한 `OrderList`와 달랐다. 비공개 실행 어댑터가 원본을 별도 보존하고 기존 수집기에 배열 이름을 연결했다. Booking 배열은 `data.userTrips.edges[].node`다. Agoda 완료·취소와 Trip은 실행당 목록 5회 한도에 도달했으므로 모두 부분 수집이다. Agoda 상세 형태 미확인 6건은 성공으로 세지 않았다. |
| 8. 저장·가져오기 | 원본은 새 보호 폴더에 저장했다. Agoda 894건 중 범위 내 498건, Trip 100건을 대조하여 중복 565·충돌 10건은 제외했다. 신규 Agoda 20·Trip 3건만 분리해 기존 수입 도구로 리허설한 뒤 운영 릴리스의 같은 도구로 추가했다. 기존 원천 값 불변, 삭제·덮어쓰기 0, 보호13표 불변이다. 이번 실사이트 실행에서 기존 파일 덮어쓰기 거부를 별도로 재시도하지는 않았다. |

가져오기 비교는 같은 예약의 이용기간·상태·결제 상태·환불 상태·카드 관측·금액 구성·결제일을 사용했다. 중복565건은 이전 원문 관측의 Agoda 통화/수치 금액과 Trip 주문 통화/총액도 같음을 대조했다. 관측 시각이 다른 기존 원천을 그대로 재수입하면 `current_revision` 갱신이 생기므로 **기존 예약은 재수입 대상에서 제외**했다. 충돌 10건은 이번 추가 대상에 넣지 않았다. Agoda 신규 20건은 결제 예정 19·결제 상태 미확인 취소 1건이고, Trip 신규 3건은 예약 기간·사전승인 사실이다. 새 예약 기간이 있다는 사실을 새 카드 결제 연결로 간주하지 않는다.

수입 도구가 정규화한 범위 내 사실은 Agoda 기간498·카드492·금액/통화 구성198·결제일0·취소199, Trip 기간100·카드36·결제일0·취소36이다. Trip의 기존 사실 형식은 일반 결제 금액을 정규화하지 않고 기간·사전승인·환불을 보강하므로 원문 결제 정보의 부재로 해석하지 않는다. 수집기 실행 소요 합계는 Agoda651.263초·Trip75.884초이며 Booking 전체 소요는 별도 계측하지 않았다. 재계산 generation933 게시 후 신규 정확/추론 카드 연결은 모두0이었다.

### 후속 실행에서 확인할 것

수집 구현은 [`tools/collect_ota_portals.mjs`](../../tools/collect_ota_portals.mjs), 실행 설정은 [OTA 스크립트 사용법](ota-script-usage.md)을 따른다. #798로 main에 통합됐다. 아래 항목은 새 세션에서 재확인할 계약이다. 위 실제 관측은 보호 폴더의 실행 어댑터에만 반영했고 저장소 도구 코드는 변경하지 않았다.

1. 각 포털의 예약 계정·로그인 상태와 같은 TaskSpace/Page를 확인하여 실행 대상에 연결한다. 계정 식별자나 로그인 자료를 Git·보고서에 쓰지 않는다.
2. 화면에서 발생한 목록·상세 요청의 URL과 본문을 비공개 설정에 보존한다. URL은 공급자별뿐 아니라 API별 origin/path도 일치해야 한다. Trip 목록은 `online.trip.com`, 상세는 `kr.trip.com`이며 서로 바꿀 수 없다.
3. Agoda의 상세 요청 `token`을 실제 화면 요청에서 읽어 `agodaDetailToken`에 넣고 조회 상태를 `agodaBookingPhase`로 선택한다. 기본은 Completed이므로 다른 상태도 필요하면 별도 실행한다.
4. Trip 다음 목록 요청에서 실제 Offset 입력 필드명을 확인해 `tripOffsetField`에 넣는다. 응답 필드명으로 추측하지 않는다. 목록 요청 5회 상한에 도달하면 PARTIAL이며 전체 수집 완료가 아니다.
5. Trip 상세의 `FrontHead.sign`과 목록 OrderDetail 링크 `tripsignature`, 응답 `orderCommonInfo.orderId`가 서로 맞는지 관측한다. 현재 도구는 목록 링크의 서명과 주문번호만 구성하므로 추가 필수 필드가 생기면 요청 형태를 확인하고 코드를 조정한다.
6. Booking의 화면 `UserTrips` query를 `bookingQuery`에 넣는다. 현재 구현은 빈 variables로 첫 목록만 요청하므로 화면 query가 변수를 요구하면 해당 요청 템플릿 연결이 추가로 필요하다. 여행별 화면 상세·확인 링크 수집은 미구현이고 PARTIAL로 남는다.
7. API 응답의 목록 배열·페이지 토큰·상세 ID 위치와 화면 총건수를 대조한다. Agoda phase/Trip 페이지 상한·Booking 첫 페이지 범위를 포함해 완전성을 확인한다.
8. 보호 폴더에 응답·manifest가 저장되고 재실행 덮어쓰기가 거부되는지 확인한다. 가져오기는 별도 수입 도구로 수행하며 수집 성공을 운영 반영 완료로 쓰지 않는다.

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
