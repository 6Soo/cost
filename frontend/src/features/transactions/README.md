# E 기능 지도: 거래·관리·보조

이 지도는 `feat/plush-secondary-20261116`의 E 소유 화면 범위와 현재 `webapp/` 서버 코드를 대조한 기록이다. UI는 `/api/plush/transactions`, `/api/plush/admin`, `/api/plush/auxiliary`의 인증된 JSON 응답과 구조화 동작 설명자를 사용한다. 기존 HTML을 iframe에 넣거나 파싱하지 않는다. 아래 기존 경로와 API는 동작의 출처이며 새 UI는 React 화면 안에서 읽기·쓰기 요청을 처리한다.

## 거래 허브

| 화면·기존 주소 | 실제 기능/API 근거 | 새 화면 연결 |
| --- | --- | --- |
| 카드 `/cards/all` | `webapp/cards_all.py`, `GET /api/cards/transactions` 및 `years`, `summary`, `day`, `undated`, `detail`; 업로드와 기존 카드 수집 작업은 `webapp/card_flow.py`의 `/api/imports`, `/api/imports/upload-batch`, 업로드 상태·배치 API | `view=cards`; D 응답의 서버 페이지·열·행·동작을 표시. 업로드는 설명자의 실제 파일 동작으로만 제공. 카드 분류를 새 승인 대기 목록으로 바꾸지 않음 |
| OTA `/ota` | `webapp/ota_catalog.py`: `GET /api/ota`, `/api/ota-refresh-state`, `/ota/booking`; 예약·카드 근거 작업은 `webapp/card_flow.py` `/api/imports*` | `view=ota`; 예약·카드 관계와 서버가 준 상태를 그대로 표시 |
| 환불 `/board?tab=refunds` | 장부 `refunds` 탭 및 카드 흐름의 기존 환불 관계/원자 반영 API (`/api/imports/{batch}/refund-groups/{group}/commit`) | `view=refunds`; 원결제·부분/전체 환불 관계와 원본 부호·금액을 보존하고, UI에서 상계·짝을 추정하지 않음 |
| 항공권 `/flight-passengers` | `webapp/flight_passenger_page.py`: `GET /api/flight-passengers/candidates`, owner-only `POST /api/flight-passengers/name-search`, `POST /api/flight-passengers/assign`; 카드 상세·날짜 근거 API | `view=flights`; 후보 검색/기존 COST 내부 연결 동작을 실제 서버 결과와 함께 제공. 내부 연결을 탑승 사실로 표시하지 않음 |

## 관리

| 화면·기존 주소 | 실제 기능/API 근거 | 새 화면 연결 |
| --- | --- | --- |
| 계정·권한 `/access/admin` | `webapp/ledger_board.py` 및 `webapp/access_control.py`: `/access/me`, `/access/admin`, `/access/applications`, `/access/decision`, `/access/assignments`; 소유자 세션·여행별 권한 검사 | `view=accounts`; owner 전용 메뉴와 서버의 대상별 권한 결과 사용. viewer에게 owner 자료/숫자/API를 요청하지 않음 |
| 기본 정보 `/access/admin?view=profile` | 기존 HTML 폼 `POST /api/owner-profile`; `expected_revision`, `client_request_id`, `company_name`, `assignee_name` 사용 | `view=profile`; descriptor가 제공하는 현재 값·revision으로 폼 제출, 반환 결과에서 성공/실패 표시 |
| Google 비교·복사 `/google-ledger` | `webapp/google_ledger_page.py`, `webapp/google_ledger_actions.py`: `GET /api/google-ledger`, `/rows`, `/source`; owner write는 choice/grants/mapping/auto-mapping 및 sync; 행 조회와 서버 생성 복사 결과 | `view=google`; 비교·원본 확인·클립보드 복사를 제공하되 Google 최종 장부 자동 쓰기는 제공하지 않음 |
| AI 분기 검수 결과 `/review` | `webapp/real_review_ui.py`: `GET /api/review/model`, `POST /api/review/export`; 기존 `/api/review/decisions`, `/api/review/apply`는 owner write | `view=review`; 완료 결과·집계·산출물만 표시. 거래별 사용자 판정·확인 동작을 새 화면에서 제공하지 않음 |

## 보조 화면

| 화면·기존 주소 | 실제 기능/API 근거 | 새 화면 연결 |
| --- | --- | --- |
| 참가자·수입 대조 `/participants` | `webapp/participant_income_page.py`: state, trip-panel, link/unlink, participant; 쓰기는 소유자 전용·화면 지문 및 수입 원행 검증 사용 | `view=participants`; 참가자 연결·기존 이름/별칭 보정만 서버 설명자에 있는 범위로 표시. 여행자 생성은 추가하지 않음 |
| 보험 대조 `/participants/insurance-match` | HTML 페이지는 정리되어 410; 실제 경로는 owner-only `GET /api/participants/insurance-match` 하나이며 쓰기 API는 없음 | `view=insurance`; 조회 전용. API의 미설정/권한/원천 오류를 빈 결과나 성공으로 합치지 않음 |
| 예약 연결 `/reserve-links` | `webapp/reserve_link_ui.py`, `ledger_board.py`: GET `/api/reserve-link/plan`, `/state`; POST `/links`, `/apply` | `view=reserve-links`; 서버 계획·revision·저장 응답을 따라 실제 동작 수행 |
| 수기 지출 `/expense/new` | 실제 등록 `POST /api/expenses/manual` (가시 폼은 `ledger_board.py`) | `view=expense-new`; 서버 필드/정밀 금액 문자열을 보존해 제출 |
| 수기 수입 `/income/new` | 실제 등록 `POST /api/income` (가시 폼은 `ledger_board.py`) | `view=income-new`; 서버 필드/정밀 금액 문자열을 보존해 제출 |
| 내보내기 `/export` | `POST /api/exports/xlsx`, job 조회 `GET /api/exports/{job_id}`, 다운로드 `GET /api/exports/{job_id}/download` | `view=export`; 서버가 만든 전체 집합·건수·합계·작업 상태 및 실제 다운로드를 사용 |
| 규칙 `/rules` | `/api/classification/rules`, `/api/classification/rules/{id}`, dialog/conversation 및 규칙 작성·검토·적용 API | `view=rules`; 명세가 허용하는 기존 규칙 보조 기능만 연결. 건별 분류 결정·AI 검수 대기함은 추가하지 않음 |

## API 계약 빈틈 기록

- 기존 쓰기는 JSON+`X-CSRF-Token`, urlencoded form+CSRF hidden field, multipart upload 등 전송 형식이 다르다. 계약의 `ActionDescriptor`에는 인코딩/CSRF 전달 방식/반환 형식이 없다. D가 같은-origin JSON 제출을 정규화하거나 descriptor에 요청 인코딩과 반환 형식을 명시해야 실제 성공과 실패를 구분할 수 있다.
- `/participants/insurance-match`에는 기존 HTML 페이지가 없고 조회 API도 하나뿐이다. 새 기능/API를 가정하지 않는다.
- Google·분기 검수 결과는 기존 API에 쓰기 동작도 있으나, 쓰기 설명자만으로 사람이 분기 판정을 확정하도록 UI를 노출하지 않는다.
- 현 저장소 HEAD에는 `frontend/`와 Plush `/api/plush/*`가 아직 없다. E 화면은 계약에 있는 페이지 props와 API type/client가 통합되는 것을 전제로 작성한다.
