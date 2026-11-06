# COST PR 단독 실행 명세: 최신 구현 상태·카드 내역 통합·잔여 안전검증 (2026-11-06)

> **2026-11-07 상태 갱신: 이 문서는 #713 CARD-IA 구현 이전의 과거 실행 명세다.** #713이 검증·병합·운영에 배포돼 당시 P0은 **COMPLETE**, #710 CI도 구현 완료, #712 카드 7881도 완료. **현재 미결은 #714 카드 내역 초기 로딩 최적화의 Windows 운영 배포·실측**이다. [#714 최신 단일 실행 계약](card-history-latency-release-20261107.md)을 먼저 읽어라. 아래 'CARD-IA 첫 코드 PR로 구현' 등의 문장은 당시 요구/수락 기록이지 현재 개발 큐가 아니다. 신규 코드 PR을 만들거나 #713을 재구현하면 안 된다.

> **문서 상태: IMPLEMENTATION_BRIEF / SPEC_ONLY.** 이 문서를 포함한 PR은 **코드 구현 PR이 아니다**. 후속 에이전트가 **이 PR 본문과 이 파일만 읽어도 구현의 목표·기술 위치·테스트·종료 기준을 알 수 있게** 만든 단일 진입점이다. 저장소와 운영 SHA는 작업 직전에 재확인해야 한다. 사용자 요청에 따라 다른 저장소는 범위 밖이며, **COST `6Soo/cost`만 다룬다**.

## 0. 에이전트가 반드시 먼저 알아야 할 결론

- **최신 확인 main (2026-11-06 22:51 KST): `dd2c8bea24a31b44d5144fabd10d0d6ceab0ec50`**, 열린 PR 0, Actions push run **42227886027 SUCCESS**. main은 작업 중 변할 수 있으므로 구현 PR을 만들 때 최신 HEAD/동시 작업자/로컬 미커밋·stash 확인 후 base SHA를 고정할 것.
- **CI 비용 최적화는 이미 #710으로 구현·병합**: 월~금 audit → **월요일 03:30 UTC** 주간 audit, PR의 merge-tree 검사, 증명된 동일 tree + PASS/skip0 + artifact 조건일 때 main에서 무거운 검사 재사용, 결손·불일치 때 영향 검사 fallback, 문서-only 경량 처리. 실제 `.github/workflows/quality.yml` 및 `tools/reuse_quality_evidence.py`에서 확인됨. **다시 만드는 일 금지**. 계정 billable minutes 조회 권한이 없어 **비용 절감률은 UNVERIFIED**. 다음 개발에서는 기존 CI로 대상 검사만 수행하며 무의미한 재실행 금지.
- **지출 업무 0건 vs 금융 원행 6건의 UI 구분은 #699로 코드 구현·운영 배포**(합성 320/390/1440 및 기록된 운영 읽기). 이를 '처음부터 미구현'으로 취급하지 말 것. 단, 환불·OTA·영수증 등 **전 도메인 P3 작업 등록 완결은 별도 PARTIAL**.
- **사진/PDF 영수증 단일 업로드·복구는 #700/#703 코드 구현 후 운영 배포**. iPhone 물리 Safari·HEIC·실제 OCR·실고객 자료 쓰기 검증은 아직 별도. 기존 완료 UX를 중복 개발하지 않는다.
- **진짜 즉시 구현 미완료 P0은 카드 내역 정보구조(IA) 통합**: `webapp/ledger_design.py` 메뉴에 `/import 지출 정리`, `/cards/all 카드 전체 내역` 둘 다 존재하고 `webapp/cards_all.py` 제목도 옛 이름이다. `/cards/all`은 조회, `/import`는 업로드·결과·수집기간·금융 진단으로 분리되어 있다.
- **기존 카드 IA 시도는 검사 42 failed/655 passed+93 subtests로 미병합·기존 운영 배포에서 제외**된 기록이 있다(`docs/session_handoff.md`). 실패 브랜치를 무조건 통합/병합하거나 테스트 42개를 제외하여 녹색으로 만들지 않는다. 먼저 각 실패의 현행 main 재현 여부를 확인하고 원인을 분류한다.
- **P2 무료 연결 AI 무인 처리**는 마지막 운영 기록상 timeout/`p2_applied=0`으로 **PARTIAL**. 재시도 정책·실거래/원본·스키마를 함부로 변경하지 말고, **카드 IA PR과 별개**로 읽기 진단 → 격리 합성 → 필요한 최소 수정/권한 수락을 진행한다.
- 확인된 최신 **운영 Windows 앱 SHA**는 `fd8a8995989ed56565f6d9b858ef132a953543e2` (#706)이며 코드 main의 문서·CI 커밋과 다르다. `docs/operations.md` 재확인. **문서/CI-only PR을 계기로 운영 앱 재배포 금지**.

## 1. 구현할 결과물과 PR 분할: 한 번에 뒤섞지 말 것

**첫 번째 코드 PR(CARD-IA, P0):** `지출 정리` 메뉴 삭제 → `카드 전체 내역`은 `카드 내역`으로 표기 → 카드 내역 안에서 이미지와 상관없는 **카드 원본 파일 업로드/진행·수집현황·거래 상세·필요한 조치**까지 완결. OTA와 동일한 명명/컴포넌트 패턴, 기존 금융·업로드 API/딥링크 호환 보존. 반드시 카드 PR에 실제 브라우저·인수 테스트.

**두 번째 별도 PR(P2-AUTONOMY, P1):** 현재 Provider timeout/P2 0건의 원인을 읽기 전용 계측·격리 합성으로 재현. 환경/비밀/운영 권한이 없으면 `BLOCKED_EXTERNAL`로 정확히 기록하고 다른 구현 항목은 계속. 유료 모델/기존 설정 우회/금융 쓰기 확대 금지.

**세 번째 선택적 PR(CI-FOLLOWUP, P2):** #710 기능을 우선 보존하고 실제 로그와 billable minutes 측정 권한 범위에서만 문제를 확인할 것. 결함 재현 증거가 없는 상태로 영향 매핑·CI 전체를 또 갈아엎지 말 것. 필요한 최소 selector 보정/비용 대시보드만 별도 PR.

한 PR에 위 세 도메인 코드·테스트를 섞지 않는다. **첫 구현 에이전트가 먼저 완료할 범위는 CARD-IA만**이다.

## 2. CARD-IA 제품 요구: 사용자의 한 가지 목표에 한 화면

### 2.1 메뉴/기본 페이지

| 지금 | 목표 | 정확한 제약 |
| --- | --- | --- |
| `내 확인 필요 N건` | **유지** | `user_action_queue.open_snapshot` 기준 OPEN **사람 작업만**. 실패 시 임의 0 금지 |
| `여행 장부` | **유지** | 기존 `/board` |
| `지출 정리` | **기본 탐색에서 제거** | 기능 삭제가 아닌 UI/책임 재배치. 홈/모바일/빈 화면/상세/`/rules` 복귀 링크도 점검 |
| `카드 전체 내역` | **카드 내역** | URL은 호환을 위해 `/cards/all` 그대로, HTML title/h1/사이드바/홈 action/화면 낭독 이름 포함 |
| `OTA 내역` | **유지** | 목록 제목·상태·필터·빈 화면·로딩·CTA 일관성. 예약과 카드 거래의 데이터셋은 섞지 않음 |
| `영수증 처리`·항공권·계정/권한 | **유지** | PR #700/#703 등 이미 완료 흐름 수정 금지 |

**주요 화면 `/cards/all` 상단 구성:** 제목 `카드 내역`, **카드 업로드**(주 CTA), **수집 현황**(보조 CTA). 이후 연/월, 카드, 미배정, 검색, 거래 목록/상세. 모바일 1열, 데스크톱 긴 검색/필터와 목록이 잘리지 않아야 한다. 금융 `처리 필요 6건` 같은 두 번째 사용자 대기열을 기본 화면에 만들지 않는다.

### 2.2 업로드는 단순 링크가 아니라 동일 화면의 기능

`webapp/cards_all.py`의 읽기 전용 조회 페이지에 **접근 가능한 패널/서브뷰**를 붙여 기존 업로드 기능의 **프런트엔드 재사용**을 제공한다. `/import`에 새 창/전체 페이지로 보내는 링크만 추가하는 구현은 FAIL.

입력 흐름(실제 서버 사실에 따른 단계만):
`파일 선택(다중 가능) → 클라이언트 유효성/권한 검사 → durable 업로드 접수 → 파일별 진행/오류·재시도 → 기존 분류 작업과 서버 상태 조회 → 저장/조회기간 갱신 확인 → 카드 내역 재조회`.

- 현재 endpoint는 코드 기준 `POST /api/imports`, `POST /api/imports/upload-batch` 및 `/api/imports/{batch_id}`, 관련 `card_upload_jobs`를 **재사용**한다. 먼저 운영/코드 응답 계약과 owner/CSRF/revision을 읽고 신규 API·중복 worker를 만들지 않는다.
- 업로드 성공 메시지는 `파일 저장/접수 성공`, 자동 분류 성공은 별개의 상태다. 저장과 금융 장부 기장 또는 Google 최종 시트 반영을 혼동하지 않는다.
- 같은 화면 내 결과 영역에 각 파일의 접수·진행·분류/실패·중복/원본 보호·다음 행동을 표시한다. 업로드 중 다른 화면/탭으로 이동했다 돌아오거나 재시작해도 서버 상태를 재조정한다. 브라우저 메모리에만 성공을 보존하지 않는다.
- 업로드 중 불필요한 중복 클릭 방지, 실패 파일만 안전한 재시도, 다른 파일 성공 사실 보존. 네트워크/권한/세션 만료·예외에도 가짜 `완료`를 보여주지 않는다.
- 선택한 `year`, `month`, `card`, `unassigned`, `q` 및 거래 상세 선택/스크롤 맥락을 가능한 한 유지하고, 패널 닫기·뒤로가기·ESC 시 초점을 버튼으로 복귀시킨다. 인증 쿠키/CSRF를 URL로 옮기지 않는다.

### 2.3 카드 수집 현황과 누락 기간

`#679` 기존 카드 조회기간 증빙 엔진/API를 사용하여 **수집 현황**을 같은 `/cards/all`에서 연다. 카드별·조회축별 관리 시작일, 실제 근거로 확정된 기간, 미수집 gap, 조회 0건 파일, 중복·불명확 카드, 기존 파일을 **한 곳**에서 확인한다.

- `gap 업로드` 버튼은 현재 카드/기간/조회축 문맥을 **같은 카드 업로드 패널**로 전달하고, 처리 후 서버에서 정확히 재계산한다.
- 거래 최소/최대 발생일로 조회기간 전체를 확정했다고 꾸미지 않는다. 명시된 전체 조회/원본 metadata 신뢰 정책과 관리 시작일 보호를 유지한다.
- 업로드 결과 미리보기/긴 파일명/조회기간·카드 식별 불명확 처리 등 #679의 미완료 고도화는 **별도 결함이 실제 재현될 경우** 대응한다. IA 개편 PR에서 원본 변환기/금융 계산 엔진의 광범위 리팩터링은 금지한다.

### 2.4 거래 상세, 내부 금융 진단과 사용자 작업 분리

- `webapp/cards_all.py`는 `_review_action`·`_status_badges` 등에서 지금 `/import?batch=...&transaction=...` 링크를 만들어 분류·보호 문제를 확인한다. 새 `카드 내역`에서는 **동일 거래의 상세/검토 상태**를 기본으로 보여주되, 보호된 실제 수정 동작은 기존 owner/CSRF/revision 핸들러를 재사용할 것.
- `webapp/card_flow.py`의 `render_expense_cleanup` 및 `card_cleanup_ui.py`는 **금융 원행/환불 근거에 대한 읽기 진단**을 이미 분리했다. 이를 다시 `사용자가 해야 할 6건` 목록/중복 편집 폼으로 노출하지 않는다.
- 원결제↔취소/부분환불 관계, 순액, 내부 기록, 실제 카드 환급 완료는 서로 다른 사실이며 **실제 환급/장부 기록 완료로 자동 단정 금지**. 기존 미배정/중복/충돌/수동 보호 유지. 새로운 P3 질문은 **사람만 답할 수 있는 구체적인 사실이 있고 재검증/안전 소비 경로가 있을 때만** `/my-actions`에 단일 그룹으로 등록한다.
- `내 확인 필요 0건`과 금융 대사 원행 6건은 합법적으로 공존한다. 서로 다른 숫자를 같게 맞추려고 임의 P3 6개 생성, 금융 행 삭제, 조회 필터를 속이는 처리는 실패다.
- 카드/OTA 상세에서는 같은 데이터 표현을 공유해도 두 소스의 집계·등록 권위는 섞지 않는다.

### 2.5 구형 링크/HTTP 호환: 삭제하지 마라

다음 진입점을 조사하고 **기존 파라미터의 의미·권한·반환 데이터를 유지**한 뒤 점진적 화면 라우팅을 이관한다:

- `GET /import` 기본·`?scope=all`·`?batch=<id>&transaction=<id>`·`?cleanup_reason=...&cleanup_page=...`, `/import#newupload`, `/import#preview`, 오래된 `/review`→`/import` 경로, `/rules` 복귀 링크.
- 브라우저 `#newupload` 같은 fragment는 HTTP 서버에 전달되지 않는다. 서버에서 무조건 302/303만 하면 해시 정보가 사라질 수 있으므로 **프런트 호환**(조건부 anchor/패널 오픈·검색 맥락)을 반드시 설계/테스트한다.
- `/api/imports` 업로드·batch 상태·규칙·coverage 및 `/api/tabs/.../tsv` 등 **기존 API 계약을 제거하지 않는다**. 읽기 GET으로 분류·원장·P3 작업 DB 쓰기가 발생하면 안 된다.
- 외부 복사 링크/로그/오래된 북마크가 기본 화면만 열리고 선택한 거래·파일을 잃는 경우 FAIL. 지원할 수 없는 오래된 매개변수는 owner에게 회복 가능한 안내를 제공하고 보수적 호환 경로를 유지한다.

## 3. CARD-IA 구현 지도: 실제 확인된 현재 소스 위치

| 파일 | 최신 main에서 확인한 구조 | 원하는 최소 변화 |
| --- | --- | --- |
| `webapp/ledger_design.py` | `work_menu_html()`에 `카드 전체 내역`, `_nav_html()`에 `/import 지출 정리` + `/cards/all 카드 전체 내역` | 보이는 메뉴·홈·모바일/기존 작업 CTA 의미 통일, 중복 제거 |
| `webapp/cards_all.py` | `cards_all_page/_cards_all_page`, `CARD_ALL_STYLE/SCRIPT`, 카드 필터·목록·`card_detail_html`, 화면 제목 옛 이름 | 카드 내역 title/heading, 업로드·coverage 패널·진행/완료 및 상세/필터 유지 |
| `webapp/card_flow.py` | `dispatch`에서 `/import` upload page·`scope=all`, `/api/imports` POST·조회/규칙, `render_expense_cleanup` | 기존 durable worker·조작부·금융 읽기 진단 재사용, 카드 화면에서 동작하도록 접합 |
| `webapp/ledger_board.py` | `/cards/all` 카드 페이지 라우팅, `/import`와 `/review` 호환, `/rules` 복귀, upload route 권한 | 신규 공개 위험 없이 호환 URL·패널 동작 연결. viewer/owner 경계 불변 |
| `webapp/card_upload_jobs.py` / `webapp/card_upload_coverage.py` (실제 소스 확인 후) | 업로드 작업/조회기간 엔진 | 기존 데이터 모델·API·멱등/재시작 복구를 사용 |
| `webapp/card_cleanup_ui.py` / `webapp/card_cleanup_queries.py` | 읽기 금융 상태 UI, 0/6 분리 | 두 번째 사용자 대기열 재도입 금지, 거래 상세의 보조 근거 유지 |
| `webapp/user_action_queue.py` / `webapp/user_action_adapters.py` | OPEN 사용자 작업, 현재 주로 카드 항목 어댑터 | P3 숫자/의미 유지. 첫 CARD-IA PR에서 전체 도메인 어댑터 재설계 금지 |
| `config/test-impact-map.json` | 변경 파일별 영향 검사 선택 이미 존재 | 필요한 최소 매핑만, 금융·권한·card-coverage 연관 보호 제외 금지 |

과거 고장 난 CARD-IA 시도(`67eb55c4` 관련 기록)는 **참고만**. 깨진 브랜치를 그대로 병합하지 말고 해당 diff를 현재 main과 비교해 유효 부분만 엄격히 발췌한다.

## 4. 테스트·UX 수락: PR에 실제 수행 증거 필수

### 4.1 최소 검사 전략

- 변경 직전 최신 `origin/main` SHA 고정. PR diff 범위에서 **`python tools/run_quality_checks.py --base <고정-base-SHA> --head HEAD --plan-json`**으로 선택 파일을 먼저 확인. 실제 실행은 **`--run`**으로 1회 수행. 더 가벼운 표적 테스트는 먼저 `python -m pytest -q <실제 수정 영역 파일>`로 수행.
- 기존 검사 파일 중 **실제로 영향 있는** `webapp/tests/test_cards_all.py`, `test_cards_all_filters.py`, `test_card_flow.py`, `test_card_upload_jobs.py`, `test_card_upload_coverage_ui.py`, `test_card_upload_coverage_api.py`, `test_card_upload_management.py`, `test_ledger_design.py`, `test_user_action_queue.py`, `test_card_flow_browser.py`, `test_site_shell_browser.py`, `test_cleanup_refund_display.py`, `test_card_refund_query.py`를 선별 활용. 모든 파일을 무조건 돌리거나 필요한 보호 테스트를 제외하지 않는다.
- **영향지도의 대형 묶음 매칭이 일어날 때**는 왜 해당 금융/라우트/업로드 경계가 선택됐는지 검토하되, 예상보다 오래 걸린다는 이유로 skip/xfail하거나 테스트에서 보호 assertion을 삭제하지 않는다.
- UI는 합성 owner/viewer와 **320/390/768/1440px**, 라이트/다크, 키보드·ESC/포커스 복귀, 200% 확대에서 직접 브라우저 실행 및 정렬·겹침·가로 스크롤 점검. 시각 점검을 selector 존재 단언으로 대신하지 않는다. 실제 물리 Safari/고객 원본은 접근 권한이 없다면 `UNVERIFIED`로 남겨 정직하게 보고한다.
- GitHub CI는 #710의 재사용 기능을 존중한다. 무거운 검증이 이미 같은 tree·근거에 대해 통과했고 정책상 재사용 가능한 경우 목적 없이 재실행하지 않는다. main 병합 SHA와 Windows 운영 SHA는 다른 단계를 명확히 기록한다.

### 4.2 CARD-IA-01~16 수락 매트릭스

| ID | 재현 | PASS 조건 |
| --- | --- | --- |
| 01 | owner 데스크톱/모바일 메뉴/홈 | `지출 정리` 메뉴·홈 대기열0, `카드 내역` / `OTA 내역` 대칭 |
| 02 | `/cards/all` 기본·월 선택·검색 | 제목/필터/결과·0건 상태/오류 재시도 유지, 업로드/수집 현황 상단 |
| 03 | 카드 업로드 클릭 | `/import`로 페이지 이동 없이 **같은 화면**에서 파일 선택·업로드 접수 |
| 04 | 카드 다중 파일 혼합 상태 | 성공/실패 개별 카드·원본 증빙·재시도·결과 지속 |
| 05 | 업로드 후 탐색·새로고침·서버 재시작 | durable 작업의 실제 서버 상태 재조회·복구, 거짓 완료0 |
| 06 | 조회기간 관리 시작일·0건 파일·여러 조회축 | #679 증빙 의미 보존, 빈 날짜를 실제 조회 완료로 위장0 |
| 07 | gap에서 업로드 | 카드·기간·축 유지해 업로드 패널 오픈, 서버 재계산 |
| 08 | 0 P3 / 회계 원행 6 | 전역 사용자 업무0, 거래의 읽기 전용 금융 상태6 유지 |
| 09 | 원결제+부분/복수 환불 | 원본·원승인/금액/환불 그룹·보호 보존, 중복 입력 폼0 |
| 10 | 카드/OTA/영수증 링크 | 동일 사용자 질문은 /my-actions, 거래 상세/원본 링크는 소실0 |
| 11 | `/import` 상세, scope, cleanup filter, batch, fragment | 실제 목적지/파라미터 회복, 기존 계약·권한·메시지 동일 |
| 12 | owner/viewer/비로그인/CSRF 실패 | viewer·비인증 업로드 불가, 읽기 범위/403 유지, CSRF·revision 경계 유지 |
| 13 | stale revision·중복 업로드·재접수 | 멱등·보호·충돌 안내, 수동/원본·환불 불변 |
| 14 | 카드 vs OTA 비교 / 320·390·768·1440 | 제목·필터·상태·빈 화면 밀도 일치, 44px 버튼·가로 넘침0 |
| 15 | 200% 확대·키보드·ESC·다크 | overlay/CTA 겹침0·포커스 복귀·aria 상태·스크린리더 구조 |
| 16 | 배포 수락 | 영향/브라우저/CI PASS, 정확한 SHA·health/ready·보호 API 401·보호 13표 불변, 고객 DB/Google 임의 쓰기0 |

**완료 선언 금지 조건:** 메뉴명만 바꿈, `/import` 이동 버튼만 추가, 업로드 결과가 사라짐, 0/6 숫자를 억지로 합침, 레거시 딥링크 손실, 독립 UI 리뷰 없이 '예쁘다'고만 평가, 테스트 실패를 skip/삭제, CI 성공만으로 운영 수락을 완료라고 단정.

### 4.3 과거 42개 실패 재발 방지

기존 CARD IA 작업점에서 42 failed 기록이 있다. 최신 main 재현/현행 의도 변경/진짜 regressions를 **분리한 표**를 PR에 첨부: 테스트명 → 정확한 실패 원인 → 대상 계약 → 수정한 코드 → 재검증. 기존 메인에서도 실패하면 baseline defect로 표시하고 별도 이슈/PR 후보로 분리. **현재 요구와 맞지 않는 구형 DOM 테스트는 사용자 동작·금융 보호를 잃지 않는 동등한 수락 테스트로 교체**하며, 근거 없이 삭제 금지.

## 5. P2-AUTONOMY 별도 구현 PR 계약 (이번 CARD-IA PR에는 넣지 않음)

- `webapp/autonomous_cleanup_worker.py`, `app/connected_agent_provider.py`, `webapp/provider_config.py`, `webapp/user_action_adapters.py` 및 `docs/specs/autonomous-expense-cleanup-20261105.md` / `autonomy-io-unified-followup-20261105.md`의 현재 진입·상태/한도·키 경계를 읽는다.
- 운영 상태에서 **read-only**로 worker 실제 프로세스/상태파일 timestamp/Provider 선택/실제 timeout 한도/재시도·dead-letter·opt-in 여부를 확인. 오래된 status를 현재 실행 성과로 읽지 않는다. 보호/개인/비밀 원문 외부 전송 금지.
- 격리 합성으로 `새 카드 업로드 → P1 규칙 → P2 실제 선택 provider 연결(허용된 테스트 환경에서만) → preview/안전 apply → 재시도/실패 복구 → 남은 P3`를 검증. 타임아웃/용량 제한/새로고침/동시 작성/수동/환불 충돌 포함.
- **새로운 유료 모델·외부 시크릿·실고객 자동 분류/대량 재처리/금액 수정은 사용자 승인 없이 금지**. 정상 모델 호출 권한이 없으면 `BLOCKED_EXTERNAL_PROVIDER`, 실제 적용 성공0이라면 완료0으로 보고. 격리 합성 성공과 실제 운영 성공을 별도로 기록.
- 동작 미확인 시 P2를 '자동 해결됨'이라고 주장하지 않고 P1 안전 처리/진짜 P3만 노출. 비용과 I/O 개선도 실제 검증치 없이 추정하지 않는다.

## 6. CI #710 구현 상태: 남은 일과 잘못된 재작업 방지

**코드 병합·CI 성공 (COST #710):** `.github/workflows/quality.yml`의 주 1회 감사/PR 최신 run 취소, `tools/reuse_quality_evidence.py`의 증거 묶음/동일 tree 검증, `docs-only` 선택 시 패키지·Chromium·아티팩트 회피. `tools/run_quality_checks.py`의 기존 impact plan을 계속 사용한다. 문서 #709/인수 #05a11은 최초 설계/당시 상태이다. **현재 'CI 코드 미구현'이라고 쓰인 옛 명세를 근거로 #710을 다시 구현하는 것은 오류.**

**검증·계측이 남음:** 실제 계정 billable 7/30일 사용량, cache/PR merge-tree 증거 재사용률, 문서-only 평균 경과시간, 보호 검사 누락 여부. GitHub API 토큰 접근 404는 `UNAVAILABLE`로 표시하며 임의 절감률 산출 금지. 만약 CI 자체에 실제 회귀가 나타나면 `tests/test_quality_checks.py`/`tools/reuse_quality_evidence.py` 관련 검증을 추가하는 **좁은 별도 PR**로 수정한다.

## 7. 후속 에이전트의 수행 순서 및 종료 증거

1. PR 본문과 **이 파일**을 읽는다. 필요한 때만 아래 참조 정본을 확인: `AGENTS.md`, `docs/session_handoff.md`, `docs/operations.md`, `docs/specs/unified-expense-action-queue-20261105.md`, `docs/specs/card-upload-management-ux-20261105.md`, `docs/specs/ci-minimum-test-cost-20261106.md`.
2. 최신 main/실제 운영 SHA/열린 PR 및 로컬 미커밋·stash/동시 writer를 다시 읽는다. **명세 PR이 이미 병합됐는지와 구현 PR이 새로 필요한지 구분**. 운영 데이터·시크릿·미추적 자료는 덮어쓰지 않는다.
3. CARD-IA만 새 소규모 코드 PR로 구현한다. 사용자 동선이 한 화면에서 끝나도록 실제 업로드→완료 결과·coverage·거래 상세를 연결한다. 가능한 기존 컴포넌트/엔드포인트 재사용하고 난이도 핑계로 다른 화면 이동 버튼만 두지 않는다.
4. 단위/표적→영향 선택→선택된 영향 검사/브라우저→독립 UI 반례 검토를 실행. 42개 실패의 사유·수정·확인 결과를 표로 남긴다. 테스트 범위는 실제 위험에 맞게 작게 유지하고 금융/권한 보호는 꼭 실행한다.
5. code PR에는 **변경 파일/일반 사용자 여정/호환 라우트 표/보호 게이트/실행 테스트/PR exact SHA/CI run/남은 위험**을 기록한다. CI 성공일 때만 병합, 운영 코드 배포는 현행 `AGENTS.md`/`operations.md`의 **검증된 단일 writer·정확한 고정 SHA** 계약에 따라 진행한다.
6. 최종 사용자가 볼 보고는 **ELI10**: 무엇이 바뀌었는지, 어디서 실제 되는지, 테스트/운영 여부, 못 확인한 것은 무엇인지. PR 생성/문서 변경·CI와 운영 실사용을 다른 상태로 기록.

**CARD-IA 작업 최종 종료:** `CARD-IA-01~16 전부 근거 있는 PASS`(권한 없는 실자료/물리기기 항목은 별도 `UNVERIFIED`), 진짜 UI 동선 완결, 관련 보호/호환 불변, CI green, 운영 배포가 수행됐다면 SHA/health/ready/13표/대표 브라우저 증거. 운영 배포를 하지 못했다면 `CODE_MERGED_DEPLOY_BLOCKED` 등 정확한 상태와 필요한 최소 실행 명령으로 보고한다.

---
### 이 PR만 읽고 구현을 시작하는 단일 명령문

> `6Soo/cost` 최신 main을 인수하고 **본 PR의 파일 `docs/specs/cost-pr-only-implementation-brief-20261106.md`**와 본문을 구현 계약으로 삼아라. **#710 CI는 완료**, **#699 0/6 분리와 #700/#703 영수증 업로드는 이미 구현**, **P0 카드 내역 통합만 새 코드 PR로 구현**하라. `/cards/all`에서 카드 조회·업로드·진행 결과·조회기간/gap·거래 상세가 완결되게 구성하고 `지출 정리` 메뉴 제거/`카드 내역` 명칭 통일, `/import`·기존 API/해시·금융/원본·수동/환불·Google·권한 보호를 유지한다. 기존 42 failed는 이유를 조사하여 skip 없이 해결한다. `CARD-IA-01~16`을 브라우저/선택 영향 QA/보호 검사로 검증하고 정확한 PR/CI/운영 SHA를 인계하라. P2/provider 조사와 CI 계측은 **별도 PR/작업**으로 남긴다. 문서만 수정했거나 링크 버튼만 만든 상태에서는 COMPLETE를 보고하지 마라.
