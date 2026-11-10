# OTA 수집 스크립트 사용법 — `collect_ota_portals.mjs`

상태: 2026-11-11 SPEC §7 "OTA 포털 3곳(Agoda, Booking.com, Trip.com)" 수집 스크립트 산출물.
범위: **읽기 전용 포털 조회**와 합성 fixture 검증. 실제 조회는 사용자의 로그인 세션이 있는 브라우저에서만 한다.

## 무엇을 하는가

`tools/collect_ota_portals.mjs`(순수 함수·계획 CLI)와 `tools/ota_collection/entry-runner.mjs`(명시적 ego-browser 진입)로 나뉜다.
import만으로는 TaskSpace나 브라우저가 기동하지 않는다. 진입점은 스킬 규칙대로 목표 단위 TaskSpace를 한 번 만들고
이후 회차에 재사용하며, 기존 ID 주입/재사용과 사용자 소유 이름 충돌 시 실패 보고를 따른다. 같은 TaskSpace에서
공급자별 관측 entry로 페이지를 이동한 뒤 조회하고(공급자 origin 정합성은 코드로 검사), 원자료를 새 보호 디렉터리에,
요청 한도를 지킨다. 실제 운영 반영은 하지 않는다. 수입은 기존 저장 형식을 그대로 써서 사용자가 별도로 돌린다.

- 원자료: 새 실행 디렉터리 아래 `provider/...` (기본 `.local-archive/ota-portal/<시각>/run-<무작위>/`,
  `--archive` 또는 `OTA_ARCHIVE_DIR`로 지정 가능). 기존 파일 덮어쓰기를 시도하지 않고 거부한다(신규 파일 생성만).
- 요약/manifest: 건수·상태·원인 코드만. 예약번호를 포함하는 원본 파일목록은 요약에 기록하지 않는다. 자격증명·계정 식별자·요청 헤더/본문·관측 토큰/쿼리는 기록하지 않는다.
- 한도 준수: 동시 요청 ≤ 6(현재 공급자 실행은 순차), 목록 요청 공급자당 재시도 포함 ≤ 5, 상세 시도 ≤ 3(지수 백오프).
  재시도를 소진한 요청 실패와 상세 응답 검증 실패를 실행 전체에서 누적하여 31번째 실패에서 중단한다.

## 실행

```
ego-browser nodejs -e "const { mainEgo } = await import('file:///C:/절대/path/tools/ota_collection/entry-runner.mjs'); await mainEgo({ taskSpace: globalThis.taskSpace })"
```

Git Bash/WSL 등에서는 대응 명령으로 같은 명시적 호출을 평가한다. Windows PowerShell 5.1에서
`-e` 문장에 따옴표/여러 줄이 들어가면 깨지므로 위처럼 UTF-8 `.mjs` 파일로 둔다. 이 문서는 실행 장소를
명시적으로 지정한다: import만으로는 아무 일도 일어나지 않고(무부수효과), `mainEgo`와 `runEgoJob`은
제작자가 주입한 page/fetch/task로도 호출할 수 있다.

- TaskSpace는 목표 단위로 하나 만들고 재사용한다(기본 안정 이름). 이미 있는 TaskSpace ID/핸들을 주입하면 그것을 재사용한다.
  사용자 소유 이름 충돌(EGO_TASK_SPACE_NAME_IN_USE) 등은 실패로 보고하며 다른 이름으로 우회 만들지 않는다.
- `taskSpace` 생략 시 ego 환경의 전역 taskSpace를 해석해 쓴다; 그마저 없으면 명확한 오류로 멈춘다.
  공급자 문서에 없는 URL/도메인은 쓰지 않는다.
- 스크립트를 다시 돌리면 새 실행 디렉터리가 생기므로 원자료가 겹치지 않는다.
- 계획만 보려면: `node tools/collect_ota_portals.mjs --plan [--provider agoda,trip,booking]`
- 합성 fixture 검증(실제 포털/세션 없음): `node --test "tests/ota_collection/*.test.mjs"`

## 공급자와 재개점(관측 필요 vs 미지원)

- **Agoda**: 목록 `POST /api/ko-kr/mmbc/v2/GetBookingsList`, `bookingPhase` Upcoming/Completed/Cancelled 선택, pageIndex 1부터, pageSize 40, `includeArchive: true`, `pagination.totalPages`까지.
  상세 `POST /api/ko-kr/mmbc/eb/details`는 화면에서 관측한 상세 token이 필요하다. 미지정이면 `CAPTURE_REQUIRED`이고 토큰을 추측하지 않는다.
  저장 형식은 `tools/import_agoda_api_details.py`가 읽는 `{observed_at, list, detail}` 문서 집합과 같다.
- **Trip.com**: 로그인 entry는 `https://kr.trip.com/account/signin`, 목록은 `POST https://online.trip.com/restapi/soa2/26974/getAllOrders.json`(OrderStatusClassify All, Count 20, 날짜 조건 비움), 응답 `Offset`으로 페이지네이션.
  상세 `POST https://kr.trip.com/restapi/soa2/27453/GetOrderDetailOnline`은 `orderId`와 목록 `OrderActions[].ActionURLH5`의 `tripsignature`가 필요하다.
  다음 페이지 요청 필드는 화면에서 관측한 이름을 `opts.tripOffsetField`로 제공한다. 응답 커서는 그 이름으로 다음 본문에 넣는다.
  필드를 관측하지 못했으면 다음 페이지를 요청하지 않고 `PARTIAL`로 남긴다(추측 금지). 각 API의 host와 path는 서로 바꿔 쓸 수 없다.
  저장 형식은 `tools/import_trip_api_details.py`가 읽는 문서+orders 형식과 같다.
- **Booking.com**: 목록 `POST https://secure.booking.com/dml/graphql?lang=ko` `operationName: UserTrips`이며 query 텍스트는 화면 관측이 필요하다(미지정 시 `CAPTURE_REQUIRED`).
  관측 절차상 두 번째 커서 페이지 요청이 서버 오류를 내므로 1페이지까지만 수집하고 이후를 성공으로 표시하지 않는다.
  여행 상세(tab=bookings 화면 텍스트·일부 confirm 링크)는 안정 템플릿이 없어 `CAPTURE_REQUIRED`/지원 안 함으로 정직하게 상태화하며 성공으로 표시하지 않는다.

## 로그인 만료·의존

- 로그인/재인증(필요 시 이메일 인증번호 포함)은 **사용자 작업**이다. 스크립트는 자격증명·쿠키·OTP를 읽거나 자동화하지 않고,
  포털 화면 로그인만 시도하지 않는다.
- 세션 만료/인증 신호는 `LOGIN_REQUIRED`로 멈추고 상태만 남긴다. 중단 상태는 멈춤이지 실패 판정이 아니며, 같은 값을 성공한 횟수로 바꾸지 않는다.
  앞선 페이지·상세에서 얻은 원자료는 보존하고, 미시도 상세는 `details_skipped`, 이후 공급자는 `INTERRUPTED`로 기록한다.
- 로그인 유예·우회·계정 전환 시도 금지. 예약 변경·취소·결제·메시지 전송·쿠폰 사용 금지(읽기만).
- 요청은 공급자 origin 정합성 검사를 통과해야 한다. 문서화된 entry/템플릿 밖의 URL·도메인 전환은 코드상 허용되지 않는다.
- 어댑터가 login 상태를 직접 판정할 수 없는 제공자는 `AUTH_UNKNOWN`으로 남긴다(성공으로 표시하지 않음).

## 입력과 출력 경계

- 운영 DB apply, 예약 작업 등록, 배포, 과금 없음. 대시보드/장부 쓰기 없음.
- 수집과 수입은 분리되어 있다. 원자료를 실제로 쓰려면 사용자가 기존 importers로 별도 실행한다:
  Agoda `tools/import_agoda_api_details.py`, Trip `tools/import_trip_api_details.py`, 저장 스키마·구매자 계약은 해당 파일과 `app/*_api_capture.py`를 따른다.
- 목적지 폴더/원본 파일/합치는 판단이 필요한 경우 사용자에게 확인한다(스크립트 단독 결정 금지).

## 상태 요약

manifest `status`는 가장 나쁜 공급자 상태를 쓴다(로그인 5 > 중단 4 > 캡처필요/인증미확인 3 > 부분 2 > 실패/잘못된ID 1 > 성공/건너뜀 0).
요약 줄 예: `agoda: CAPTURE_REQUIRED listed=... details_saved=... details_capture=...`.
미지원/미관측 경로를 성공으로 바꾸지 않는다.

## 검증

합성 fixture 테스트가 만료·인증·잘못된 ID·pagination·재시도 한도·민감값 미기록·덮어쓰기 거부를 실제 실행으로 확인한다:
`node --test "tests/ota_collection/*.test.mjs"`(모의 fetch만 사용, 실제 포털/로그인/고객 자료 없음).
영향 기반 검사는 `python tools/run_quality_checks.py --base origin/main --run`이며, 결과(성공·건너뜀·미매핑)를 그대로 기록한다.

### 2026-11-11 E1 재검수 변경 기록

- 요구사항별 구현 완료: ID 전체 검증(문자열 또는 안전한 정수), 저장 경로의 논리적 containment와 물리적 junction/symlink 거부, 관측된 Trip 다음 페이지 본문, 실행 전체 실패 한도, 로그인 즉시 중단.
- 공개 API 합성 회귀 11건은 제품 수정 전 11 fail·0 skip, 수정 후 통과했다. 목록 2페이지 인증 만료, 기존 원본 덮어쓰기 거부와 부분 저장 집계도 포함한다.
- 추가 합성 경계: 재시도를 포함한 목록 한도, 상세 검증 실패 누적, 공급자 간 실패 누적, 실제 진입 함수의 page.fetch 응답, run ID 경로 탈출, 탐색 실패 후 요청 금지, manifest 민감값 제외, API별 정확한 host/path, Windows junction·파일 hard link, 페이지 간 invalid 집계·includeArchive.
- 기존 테스트 변경 예외는 한 줄이다. test ID `an injected TaskSpace page is navigated per provider before its requests`의 `allowedHosts`: old `[www.agoda.com, kr.trip.com, secure.booking.com]` → new `[www.agoda.com, kr.trip.com, online.trip.com, secure.booking.com]`.
  근거: [정본 관측 절차](ota-portal-collection.md)의 목록 API host는 `online.trip.com`, 로그인·상세는 `kr.trip.com`. Fable의 명시 승인을 관리자가 전달했다. main 원래 테스트나 나머지 기존 단언은 수정하지 않았다. 새 회귀는 host 교환·외부 도메인·다른 path·userinfo를 모두 거부하는지 확인한다.
- 실사이트·로그인·브라우저·운영 DB·고객 자료·유료 API·모델 호출·push·배포는 실행하지 않았다. 실제 세션 응답과 인증 인계, 실제 수입 도구와의 end-to-end 동작은 미검증이다.
