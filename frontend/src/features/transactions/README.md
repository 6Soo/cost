# E 기능 지도: 거래·관리·보조

이 지도는 `feat/plush-secondary-20261116`의 E 소유 화면 범위와 현재 `webapp/` 서버 코드를 대조한 기록이다. UI는 `/api/plush/transactions`, `/api/plush/admin`, `/api/plush/auxiliary`의 인증된 JSON 응답과 구조화 동작 설명자를 사용한다. 기존 HTML을 iframe에 넣거나 파싱하지 않는다. 아래 기존 경로와 API는 동작의 출처이며 새 UI는 React 화면 안에서 읽기·쓰기 요청을 처리한다.

## 거래 허브

| 화면·기존 주소 | 실제 기능/API 근거 | 새 화면 연결 |
| --- | --- | --- |
| 카드 `/cards/all` | `webapp/cards_all.py`, `GET /api/cards/transactions` 및 `years`, `summary`, `day`, `undated`, `detail`; legacy 화면은 `year`, `month` 또는 `period`, `card`, `q`, `cursor`, `undated_cursor`, `undated`를 읽음. 새 URL에 `card_kind`가 있으면 함께 전달 | owner 전용. `view=cards`; URL 조건을 첫 API 조회까지 보존하고 카드 기본 페이지 크기 100건을 사용. React 페이지 이동은 연도·월·카드·검색 조건을 유지하고 offset `page`로 이동하며 오래된 cursor는 초기화. 통합 API는 `period`, 카드 키, cursor/undated 조건과 500건 초과 전체 페이지를 아직 처리하지 않으므로 D API 보완이 필요함. 업로드는 설명자의 실제 파일 동작으로만 제공하고 카드 분류를 새 승인 대기 목록으로 바꾸지 않음 |
| OTA `/ota` | `webapp/ota_catalog.py`: `GET /api/ota`, `/api/ota-refresh-state`, `/ota/booking`; 예약·카드 근거 작업은 `webapp/card_flow.py` `/api/imports*` | `view=ota`; 예약·카드 관계와 서버가 준 상태를 그대로 표시 |
| 환불 `/board?tab=refunds` | 장부 `refunds` 탭 및 카드 흐름의 기존 환불 관계/원자 반영 API (`/api/imports/{batch}/refund-groups/{group}/commit`) | `view=refunds`; 원결제·부분/전체 환불 관계와 원본 부호·금액을 보존하고, UI에서 상계·짝을 추정하지 않음 |
| 항공권 `/flight-passengers` | `webapp/flight_passenger_page.py`: `GET /api/flight-passengers/candidates`, owner-only `POST /api/flight-passengers/name-search`, `POST /api/flight-passengers/assign`; 카드 상세·날짜 근거 API | `view=flights`; 후보 검색/기존 COST 내부 연결 동작을 실제 서버 결과와 함께 제공. 내부 연결을 탑승 사실로 표시하지 않음 |

## 관리

| 화면·기존 주소 | 실제 기능/API 근거 | 새 화면 연결 |
| --- | --- | --- |
| 계정·권한 `/access/admin` | `webapp/ledger_board.py` 및 `webapp/access_control.py`: `/access/me`, `/access/admin`, `/access/applications`, `/access/decision`, `/access/assignments`; 소유자 세션·여행별 권한 검사 | `view=accounts`; owner 전용 메뉴와 서버의 대상별 권한 결과 사용. viewer에게 owner 자료/숫자/API를 요청하지 않음 |
| 기본 정보 `/access/admin?view=profile` | 기존 HTML 폼 `POST /api/owner-profile`; `expected_revision`, `client_request_id`, `company_name`, `assignee_name` 사용 | `view=profile`; descriptor가 제공하는 현재 값·revision으로 폼 제출, 반환 결과에서 성공/실패 표시 |
| Google 비교·복사 `/google-ledger` | `webapp/google_ledger_page.py`, `webapp/google_ledger_actions.py`: `GET /api/google-ledger`, `/rows`, `/source`; owner write는 choice/grants/mapping/auto-mapping 및 sync | `view=google`; 서버가 비교·원본·복사 payload를 구조화 응답으로 제공할 때만 표시. `sync`, `write`, `push`, `auto-mapping`, `grant`, `final-ledger` 동작은 숨겨 Google 최종 장부 자동 쓰기를 제공하지 않음. 통합 API `088b1731`의 현재 projection은 연결 여부만 반환하므로 비교·복사 기능은 D 후속 API 응답으로 재확인 필요 |
| AI 분기 검수 결과 `/review` | `webapp/real_review_ui.py`: `GET /api/review/model`, `POST /api/review/export`; 기존 `/api/review/decisions`, `/api/review/apply`는 owner write | `view=review`; 완료 결과·집계·산출물만 표시. 거래별 사용자 판정·확인 동작을 새 화면에서 제공하지 않음 |

## 보조 화면

| 화면·기존 주소 | 실제 기능/API 근거 | 새 화면 연결 |
| --- | --- | --- |
| 참가자·수입 대조 `/participants` | `webapp/participant_income_page.py`: state, trip-panel, link/unlink, participant; 쓰기는 소유자 전용·화면 지문 및 수입 원행 검증 사용 | `view=participants`; 참가자 연결·기존 이름/별칭 보정만 서버 설명자에 있는 범위로 표시. 여행자 생성은 추가하지 않음 |
| 보험 대조 `/participants/insurance-match` | HTML 페이지는 정리되어 410; 실제 경로는 owner-only `GET /api/participants/insurance-match` 하나이며 쓰기 API는 없음 | `view=insurance`; 조회 전용. API의 미설정/권한/원천 오류를 빈 결과나 성공으로 합치지 않음 |
| 예약 연결 `/reserve-links` | `webapp/reserve_link_ui.py`, `ledger_board.py`: GET `/api/reserve-link/plan`, `/state`; POST `/links`, `/apply` | `view=reserve-links`; 서버 계획·revision·저장 응답을 따라 실제 동작 수행 |
| 수기 지출 `/expense/new` | 실제 등록 `POST /api/expenses/manual` (가시 폼은 `ledger_board.py`) | `AuxiliaryPage`가 `view=expense-new`로 해석. D projection이 이 view와 실제 필드를 제공할 때만 서버 필드/정밀 금액 문자열을 보존해 제출 |
| 수기 수입 `/income/new` | 실제 등록 `POST /api/income` (가시 폼은 `ledger_board.py`) | `AuxiliaryPage`가 `view=income-new`로 해석. D projection이 이 view와 실제 필드를 제공할 때만 제출 |
| 내보내기 `/export` | `POST /api/exports/xlsx`, job 조회 `GET /api/exports/{job_id}`, 다운로드 `GET /api/exports/{job_id}/download` | `view=export`; 서버가 만든 전체 집합·건수·합계·작업 상태 및 실제 다운로드를 사용 |
| 규칙 `/rules` | `/api/classification/rules`, `/api/classification/rules/{id}`, dialog/conversation 및 규칙 작성·검토·적용 API | `AuxiliaryPage`가 `view=rules`로 해석. D projection이 실제 규칙 계약을 제공할 때만 명세가 허용하는 보조 기능을 표시하고, 건별 분류 결정·AI 검수 대기함은 추가하지 않음 |

## API 계약 빈틈 기록

- `ActionDescriptor`는 서버가 제공하는 `encoding`, `csrf`, `response`를 그대로 사용한다. E 화면은 설명자에 없는 필드를 만들거나 서버 주소를 조합하지 않는다.
- 같은 출처 동작 주소는 `/api/`와 계정 업무의 고정 JSON POST 세 경로(`/access/applications`, `/access/decision`, `/access/logout`)만 허용한다. 이 세 경로는 HTML 화면을 호출하는 링크가 아니며, 기존 handler 계약대로 CSRF header를 보낸다. 임의 `/access/*` 경로와 legacy HTML 경로는 비활성화한다.
- 빈 `client_request_id`는 화면에서 한 번 생성해 실패 재시도 동안 유지하고 성공 응답 뒤 새 요청 ID로 교체한다. `tab_ids`는 bootstrap이 허용한 여행 선택값을 반복 필드로 보내 배열 payload를 만든다.
- `/participants/insurance-match`에는 기존 HTML 페이지가 없고 조회 API도 하나뿐이다. 새 기능/API를 가정하지 않는다.
- Google·분기 검수 결과는 기존 API에 쓰기 동작도 있으나, 서버 설명자가 허용한 범위를 넘는 거래별 사용자 판정이나 확인함을 새 화면에 노출하지 않는다.
- 통합 API `088b1731`에서 거래·관리 projection은 owner-only다. 직접 viewer URL은 해당 조회를 요청하지 않고 전용 안내를 보여 준다. viewer-safe Google projection이 추가되면 그 권한 경계에 맞춰 별도 재검토한다.
- 화면은 원문·금액·식별자를 합성 fixture로 대체하지 않으며, 서버가 반환한 권한·빈 상태·원천 미설정·오류를 서로 다른 상태로 표시한다.
