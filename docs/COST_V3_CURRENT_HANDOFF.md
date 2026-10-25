# COST V3 — CURRENT HANDOFF / RESUME FROM GITHUB

> **최신 개발 재개 기준(2026-10-26):** 아래 **0.14절**, [COST READY DEV QUEUE](COST_READY_DEV_QUEUE_20261026.md) 및 실제 최신 `main` SHA를 우선한다. **PR #105/#110/#111/#112는 모두 `main`에 병합됐다.** 이들은 명세 문서 PR이며 해당 신규 기능이 코드로 구현되었다는 뜻이 아니다. 이전 0.13절의 '미병합 문서 PR' 문구는 **2026-10-25 당시 이력**이다. 최신 확인된 운영 배포 증거는 아래 0.12절의 OTA·지출 정리 표시 복구뿐이며, V21 코드 병합을 운영 배포로 혼동하지 않는다.
> 새 채팅·새 PC·다른 모델은 이전 대화를 재요구하지 말고 이 문서, [COST V3 진입점](COST_V3_START_HERE.md), [COST AGENTS](../AGENTS.md), 아래 두 저장소의 최신 원격 상태만으로 재개한다.
> 최신 사용자 승인 정책과 실제 코드·CI·배포 증거가 과거 요약보다 우선한다. 기준시각 이후의 커밋·배포·설정은 반드시 다시 조회한다.

## 0.14 2026-10-26 문서 PR 병합 완료 및 구현 준비 큐 (현재 우선)

> **GitHub 직접 실행 결과:** PR [#111](https://github.com/6Soo/cost/pull/111) merge SHA `5e602419d2356b540a3eb4917bb2a55eea29cace`, [#110](https://github.com/6Soo/cost/pull/110) `fcad2e662a10c732b4b216b14c955f2093f2dee7`, [#105](https://github.com/6Soo/cost/pull/105) `bc466fb541bf2683b25ac35fb1aa79045c4c7778`, [#112](https://github.com/6Soo/cost/pull/112) `9d83430f3cb1a574e3d3ae1078a514deec38029f` **모두 MERGED**. 이 문서 정리 브랜치 생성 직전 최신 `main`은 **`9d83430f3cb1a574e3d3ae1078a514deec38029f`**. 이 문서 자체가 후속 병합되면 SHA가 바뀌므로 실행 시 반드시 재조회한다.

**필독 실행 큐:** [docs/COST_READY_DEV_QUEUE_20261026.md](COST_READY_DEV_QUEUE_20261026.md). 사용자는 **명세 기반으로 실제 개발을 시작할 수 있도록** PR 병합·문서 최신화를 요청했다. 상태 `SPEC_MERGED / IMPLEMENTATION_PENDING`을 유지한다.

| 대상 | 현재 main 상태 | 구현 재개 위치 |
| --- | --- | --- |
| 공통 다크모드 사이드메뉴 | 구현 커밋 `a8206df`: 공통 root 토큰을 네이티브/standalone 문서에 적용. 표적 검사 통과 | **CODED / TESTED**. 실제 computed style의 시스템 전환·대비 브라우저 확인은 미완료 |
| 항공권 참가자 연결 화면 메뉴 소실 | 구현 커밋 `a8206df`: 명시적 head/body와 wrapper 통합; 메뉴·본문·모바일 메뉴 중복 없음 표적 검사 | **CODED / TESTED**. 375~1280px·200% 확대 브라우저 확인은 미완료 |
| 항공권 화면 UI/한국어 문구 | 구현 커밋 `a8206df`: 제목·필드·상태별 문구, stale/취소/충돌/저장 오류 처리 | **CODED / TESTED**. 전체 상태·반응형/키보드 브라우저 수락은 미완료 |
| 일괄 지출 정리 버튼 | `#cleanup-reclassify`·서버 POST/금융 쓰기 로직 **현행 유지**. PR #105 명세 §12 병합 | `EXPENSE-BULK-AUDIT-01` → `EXPENSE-BULK-UI-01` → `EXPENSE-BULK-MAINT-01` |
| `0630_오제` 수입 표시 | 커밋 `396c30f`: 선택 사본의 수입 블록만으로 표시 판단, 지출/전체 미검증 경고 유지. 17개 표적 검사 통과 | `OZE-INCOME-DIAG-01`은 운영 자료 권한·실행을 확인하지 않아 **UNVERIFIED** |
| Google 기존 장부 ↔ COST 웹 장부 볼드 거래 대조 | 커밋 `396c30f`: owner의 동일 여행·선택된 fresh source만 읽고 금액 및 날짜/가맹점/분류/예약번호 대조, 복수 후보·접근성 안내. 4개 합성 표적 테스트 통과 | 실제 운영 데이터·브라우저 표시 미검증; Google 쓰기 없음 |
| 카드 전체 내역 · 기본 공통 테마 · 항공권/영수증 기존 기능 | V21 `main` 구현 존재. 별도 브라우저 통합/운영 배포는 미확인 | **재구현 금지**, `V21-UI-ACCEPTANCE-01`만 표적 검증 |

**2026-10-26 구현 재개 기록:** 작업 브랜치 `feat/cost-spec-implementation-20261026`은 기준 `6f6e4d1`에서 시작했고 최신 구현 커밋은 `396c30f`. `a8206df`는 SIDEBAR-DARK-01, FLIGHT-SHELL-01, FLIGHT-UX-COPY-01을 포함하며 관련 표적 검사 23개가 통과했다. `396c30f`는 INCOME-VIEW-01과 LEDGER-MATCH-READ/UI-01을 포함하며 수입·대조 검사 21개가 통과했다. 운영 Google/DB 자료는 읽지 않았고, 실제 브라우저·운영 배포는 하지 않았다.

**EXPENSE-BULK-AUDIT-01 소스 확인:** 일반 `/import`의 `render_expense_cleanup()`이 버튼과 `CLEANUP_SCRIPT`를 렌더한다. owner+CSRF가 있는 `POST /api/imports/reclassify-pending`은 `reclassify_cleanup()`을 직접 실행해 `CardFlow._classify()`, `_auto_record_locked()` 및 `assign_existing_local_expenses()`를 호출할 수 있다. 함수는 거래/장부 분류·기장·기존 행의 여행 귀속을 변경하고, OTA 보고서/스냅샷 의존도 사용한다. 미리보기 전용 엔드포인트, preview digest 검증, 적용 감사 기록은 발견되지 않았다. 그래서 UI 버튼 제거와 기존 POST 차단은 함께 설계되어야 하며, 유지보수 경로의 읽기 전용 미리보기·최신성 검증은 아직 구현하지 않았다.

다음 실행 항목은 `V21-UI-ACCEPTANCE-01`의 남은 확대 상호작용 검증과 배포 전 보호 확인이다. `OZE-INCOME-DIAG-01`은 아래 0.15절에서 승인된 읽기 전용 진단을 진행했으나 대상 여행 행을 찾지 못해 원인을 확정하지 못했다. 유지관리 일괄 적용은 운영 자료로 실행하지 않았다.

**2026-10-26 후속 구현:** `EXPENSE-BULK-UI-01`에서 일반 지출 화면의 일괄 실행 버튼과 전용 JS를 제거하고, 건별 업무를 유지했다. 기존 `POST /api/imports/reclassify-pending`은 owner·CSRF 검증 뒤에도 `410 MAINTENANCE_FLOW_REQUIRED`를 반환해 호출만으로 재분류·장부 기록·여행 변경을 일으키지 않도록 닫았다. 합성 표적 검사 `test_cleanup_reclassification.py` 4개 통과. 세 테스트 파일 실행은 36개 통과, 2개 실패였으며, 실패는 이번 diff에서 바뀌지 않은 기존 문자열 검증 두 건이다. 기준 HEAD의 해당 코드/기대값은 변경 전부터 존재함을 확인했으며 기준 커밋에서 재실행하지는 않았다.

**2026-10-26 유지관리 구현:** `/maintenance/expense-bulk` owner 전용 화면과 preview/apply API를 추가했다. 미리보기는 데이터베이스의 일관된 메모리 복제본에서 기존 재분류·기장·기존 지출 여행 배정 흐름을 시뮬레이션하며, 등록 OTA 자료는 읽기 전용으로 확인하고 worker 갱신을 시작하지 않는다. preview 응답에는 예상 대상 ID/종류·건수·보류·실패, OTA refresh 필요 여부가 포함된다. 적용은 5분 유효한 일회용 무작위 preview ID, 전체 DB·등록 자료·일정/Google 입력 지문, owner·CSRF, 명시 확인 및 범위(OTA 갱신이 필요하면 그 범위 포함)를 확인한다. 변경/재전송은 거절하거나 같은 결과를 돌려준다. 작업 시작/완료/실패와 실제 변경 대상 ID는 기존 `change_log`에 비밀값·원문 없이 남긴다. 오래된 `/api/imports/reclassify-pending`은 계속 410으로 닫혀 있다.

표적 검사 `test_expense_bulk_maintenance.py`와 `test_cleanup_reclassification.py`는 11개 통과했다. 이 검사는 메모리 미리보기의 실제 저장소 무변경, preview 뒤 변경 거부, 명시 확인, OTA 갱신 동의 범위, owner/CSRF, 적용 재전송 멱등성을 확인한다. 실제 브라우저·운영 데이터·운영 배포는 검증하지 않았다. `OZE-INCOME-DIAG-01`은 운영 원본 접근·실행을 하지 않아 미검증이고, `V21-UI-ACCEPTANCE-01`의 실제 브라우저 확인도 남아 있다.

**2026-10-26 브라우저 부분 확인:** Aside Browser의 합성 로컬 앱에서 owner 세션으로 `/flight-passengers`를 열었고, 1440px 기본 창·현재 light 설정의 접근성 트리에 공용 메뉴와 항공권 입력 화면이 표시됐다. 이후 탭 간 synthetic session이 유지되지 않아 나머지 페이지를 확정하지 않았다. Aside CLI의 페이지 객체에는 `setViewportSize`와 `emulateMedia`가 없어 375/759/1280px, dark 전환, 200% 확대, 키보드 전체 흐름은 **NOT_TESTED**다. 이를 브라우저 수락 완료로 해석하지 않는다.

**2026-10-26 후속 표적 검증:** 로컬 Chromium/Playwright로 공통 셸을 적용한 합성 문서를 실제 렌더링했다. light/dark 시스템 설정의 계산된 배경색, 375/759/1280px 메뉴 버튼 노출, 모바일 Enter 열기·Escape 닫기·포커스 복귀를 `webapp/tests/test_site_shell.py` 브라우저 검사로 확인했고 10개 검사가 통과했다. OTA 스냅샷 경합 방지는 커밋 `6ecde4f`에 반영했으며 관련 유지관리 검사 11개와 구문 검사가 통과했다. 이 증거는 공통 셸 동작만 확인하며 `/cards/all`·영수증·항공권 전체 화면의 200% 확대와 화면별 반응형 수락을 대신하지 않는다.

`/cards/all`은 합성 카드 DB로 전체 화면을 렌더링해 Chromium에서 375/759/1280px 가로 넘침 없음, light/dark 토큰 전환, 200% 확대에서 월 타일 표시와 키보드 초점을 확인했다(`webapp/tests/test_cards_all.py::test_browser_cards_all_fits_required_viewports_with_system_theme`). 기존 해당 테스트 파일 22개 통과 기록에 더해 이 브라우저 검사도 통과했다. 영수증 화면은 합성 자료 기반 Chromium 검사에서 같은 세 폭의 가로 넘침 없음, light/dark 토큰 전환, 200% 확대에서 상호 입력·수정 버튼 표시와 입력 초점을 확인했다(`webapp/tests/test_receipt_design_contract.py::test_browser_receipt_screen_fits_required_viewports`). 항공권은 실제 공통 wrapper를 적용한 합성 문서에서 375/390/759/760/1280px 가로 넘침 없음, 시스템 light/dark 메뉴 배경 전환, 200% 확대 후 메뉴와 제목 표시, Enter 열기·Escape 닫기·초점 복귀를 확인했다(`webapp/tests/test_flight_passenger_page.py::test_browser_wrapped_flight_page_responsive_theme_and_zoom`). 거래 행 전체, 영수증 수정/복사 흐름의 확대 상태 및 API 오류 상태 전체는 미검증이다.

**2026-10-26 후속 수락 검사 커밋:** `7c4e905` 영수증 Chromium 화면 검사, `eb05f09` 항공권 wrapper 뷰포트/테마/확대 검사, `004b5f5` 일괄 유지관리 owner 화면의 합성 브라우저 미리보기→명시 확인→적용 요청 검사. `004b5f5` 검사에서 CSRF, preview ID, 적용 scope를 확인했고 API 응답은 네트워크 stub으로 대체해 DB/운영 효과를 발생시키지 않았다. 후속 표적 검사에서 항공권 통합 문서의 Enter 메뉴 열기·Escape 닫기·초점 복귀도 통과했다. 검증의 추가 범위는 큐에 기록했으며, 운영 배포와 OZE 실제 자료 원인 진단은 여전히 미완료다.

## 0.15 2026-10-26 후속 브라우저 검사와 승인된 OZE 읽기 전용 진단

`webapp/tests/test_cards_all.py::test_browser_cards_all_fits_required_viewports_with_system_theme`에서 `/cards/all` 합성 페이지를 실제 경로로 라우팅하도록 보강했다. Chromium에서 375/759/1280px 가로 넘침 없음, 시스템 테마 색상, 3월 타일 Enter로 상세 열기·Enter 재입력으로 닫기, 200% 확대에서 세 합성 거래 행과 상세 링크, 월 타일 초점을 확인했다. `webapp/tests/test_receipt_design_contract.py::test_browser_receipt_screen_fits_required_viewports`는 200% 확대 상태에서 수정 API 응답 반영과 Google 7열 클립보드 복사를 합성 응답으로 확인했고, 수정 전후 입력·버튼 노출도 확인했다. `webapp/tests/test_flight_passenger_page.py::test_browser_wrapped_flight_page_responsive_theme_and_zoom`은 200% 확대에서 예약번호 입력란의 노출·초점을 확인했다. 세 표적 검사 모두 통과했다. API 응답은 테스트 안에서 stub 처리했고 실제 서버 저장은 검증하지 않았다.

추가로 `webapp/tests/test_synthetic_preview.py::test_preview_completes_card_and_manual_receipt_without_operational_files`를 실행했으나, 기존 카드 입력 흐름의 `/import` 화면에서 `form[data-index]` 안 입력란이 보이지 않아 30초 timeout으로 실패했다. 영수증 수정·복사 단계 전 실패했고, 해당 파일의 진단용 수정은 되돌렸다. 동일 실패를 반복하거나 무관 경로를 고치지 않는다.

사용자가 `0630_오제` 진단을 운영 호스트에서 읽기 전용으로 승인했다. 운영 DB는 읽기 전용 연결로 확인했고 정확한 `display_key` 행, Google snapshot key, Google mapping key, 여행 이력의 대상 키 흔적은 모두 없었다. 같은 시작일·연도인 활성 trip 행 1건은 `needs_review`였고 그 행의 `tab_id`는 다른 Google key 1개가 참조하고 있었다. 이를 대상 여행으로 단정하지 않는다. 런타임 스냅샷과 해당 generation의 비공개 행 파일 로드는 성공했고 메인·보관 source는 모두 `status=ok`, `stale=false`였다. 대상 Google 키 자체가 snapshot에 없어 선택 사본·대상 행 개수·표시 차단 원인은 확인할 수 없다. `ROOT_CAUSE_UNVERIFIED` 유지.

운영 프로세스 코드 SHA는 `d4c5934de07543e1c27232dbd53b297f2d8fa387`로 확인됐다. 설정·스냅샷·Google 원본·운영 DB를 변경하거나 동기화/API 호출을 하지 않았다. 이 SHA와 현재 작업/배포 기준의 관계는 별도 배포 검증 때 확인해야 한다. 다음 조치는 `0630_오제` 여행 행이 존재하는 승인된 운영 DB/호스트를 사용자에게서 확인하거나 운영 데이터가 복구된 뒤 같은 범위로 다시 판정하는 것이다. 이번 검사에서 임의로 다른 저장소를 찾거나 매핑을 고치지 않는다.

**PR 관리:** [#106](https://github.com/6Soo/cost/pull/106), [#107](https://github.com/6Soo/cost/pull/107)은 최신 `main` 대비 **ahead 0**의 중복 초안이므로 **CLOSED, NOT_MERGED** 처리(작업 코드는 기존 V21 통합 main에 보존, 브랜치 삭제하지 않음). [#108](https://github.com/6Soo/cost/pull/108)은 **OPEN / divergent / 독자 변경 존재**이므로 충돌 해결 없이 병합하지 않고 `CARD-PR108-RECONCILE`로 HOLD, 기존 차이 보존.

**개발 계약:** 먼저 `SIDEBAR-DARK-01` → `FLIGHT-SHELL-01`. 상용 프론티어 감독 에이전트는 티켓 배정·검증 결과·위험 판단만 수행하고 구현/표적 테스트/코드 조사는 저비용 에이전트에 위임한다. Paseo 네이티브 Skill/위임이 진짜 독립 실행 가능한지 확인 전에는 성공으로 보고하지 않으며, CLI 자동 대체는 사용자 승인 필요. 작업별 재작업 2회/세션당 신규 구현 4티켓·하위 호출 12회/무진전 2회 HOLD. 운영 DB·Google 원본·실제 고객 기록·운영 배포는 별도 허가 없이는 금지.

**검증 범위:** 위 PR 병합 및 이 문서 상태는 **GitHub 원격 코드/명세 기준**. 신규 브라우저 기능 테스트·원본 실수입 진단·코드 패치·운영 배포를 수행하지 않았다. 최신 배포/검증 증거 없이 `IMPLEMENTED/TESTED/DEPLOYED`로 표시하지 않는다.

## 0.13 2026-10-25 최신 main vs 명세 구현 대조 (소스/PR 읽기 전용 감사)

> **고정 관측 기준:** GitHub `6Soo/cost`의 `main` = `d4c5934de07`(2026-10-25 UTC 11:42경), 이번 감사에서 확인한 브랜치·PR·코드 상태. 이후 새 커밋/PR/운영 배포가 있으면 새 기준으로 확인한다. **이번 절은 소스·PR·기존 기록 대조이지 신규 기능 테스트, 실제 Google/운영 DB·웹 브라우저 실측이 아니다.**
>
> **상태 용어:** `MAIN_CODE_PRESENT`=코드/라우트가 main에 존재, `TARGETED_TEST_REPORTED`=해당 PR이 표적 검사 통과를 보고함(이번 재실행 아님), `BROWSER_NOT_TESTED`=이번 감사에서 실제 렌더/반응형 측정 없음, `DEPLOYMENT_UNVERIFIED`=V21의 운영 SHA/배포 증거 확인 없음, `SPEC_PR_OPEN`=명세가 PR에만 존재, `ROOT_CAUSE_UNVERIFIED`=현장 스냅샷으로 특정 원인 미확인.

### 0.13.1 최신 통합 사실과 명세 대조

| 대상 / 정본 | 소스·GitHub 검증 사실 | 현재 판정 / 다음 행동 |
| --- | --- | --- |
| 기존 UI·라우트 감사 PR [#103](https://github.com/6Soo/cost/pull/103) | **MERGED** 2026-10-25. `docs/card-ui-audit-v2-20261025.md`, `docs/COST_SUPERVISOR_V2_CHECKPOINT.md`는 당시 기준 SHA/예전 미검증 실행 기록을 담는다. | `MAIN_CODE_PRESENT`(감사 문서). 과거 체크포인트의 READY 과제를 현재 실행 명령으로 다시 사용하지 말 것. |
| 시스템 테마 PR [#104](https://github.com/6Soo/cost/pull/104) | **MERGED**. `webapp/ledger_design.py`에 `prefers-color-scheme: dark` 공통 변수와 라이트 기본 토큰, `webapp/flight_passenger_page.py`·`receipt_review.py`에 관련 CSS 확인. 수동 테마 토글은 사용자 계약상 필요 없음. | `MAIN_CODE_PRESENT / TARGETED_TEST_REPORTED / BROWSER_NOT_TESTED`. 별도 독립 UI 접근성·실제 브라우저 측정은 **완료로 선언하지 말 것**. 공통 CSS의 중복 dark media 블록은 실제 부작용 여부 표적 조사 후보. |
| V21 코드 통합 PR [#109](https://github.com/6Soo/cost/pull/109) | **MERGED** 2026-10-25, 27개 파일 변경, 통합 과정에서 원본 main 자산 복구 기록. PR 설명에 표적 합성 검사 **133 passed + 70 passed**(서로 다른 묶음), 전체 회귀/브라우저 검증 **미실행**. | `MAIN_CODE_PRESENT / TARGETED_TEST_REPORTED / BROWSER_NOT_TESTED / DEPLOYMENT_UNVERIFIED`. 이미 통합된 카드/테마/영수증/항공/OTA UI를 다시 구현하지 말 것. 실제 운영 배포는 별도 승인이 필요. |
| 카드 전체 내역(통합 UI 명세 v1.1 §2,5,9) | `webapp/ledger_design.py` 메뉴 **'카드 전체 내역'**, `webapp/ledger_board.py` GET `/cards/all` 및 `/api/cards/transactions/{years,summary,undated}`·월 조회, `webapp/cards_all.py` 2026 기본/12월 타일/월별 상세/날짜 확인 필요/상세 링크, `webapp/card_transactions.py` 저장 카드 원행 읽기 투영, 합성 검사 파일 확인. | `MAIN_CODE_PRESENT / TARGETED_TEST_REPORTED`. 명세의 개별 AC 전체를 이번 감사로 확정하지 않는다. 실제 375px/시스템 테마 전환/키보드/운영 저장소 조회는 `NOT_TESTED`. 새 기능 구현보다 남은 **검증 격차** 조사 우선. |
| 카드 원행 API PR [#108](https://github.com/6Soo/cost/pull/108) | **OPEN**, `main...head`는 **ahead 1 / behind 48**. 주요 `card_transactions.py` API는 **이미 main에 존재**하고, 현재 diff는 `webapp/ledger_board.py`, `webapp/tests/test_card_transactions.py` 2개 파일에만 차이. main에는 추가 `/cards/all` 라우트/최신 검증·날짜 테스트가 있다. | `RECONCILE_BEFORE_MERGE`. PR #108 전체를 단순 병합/리베이스하여 최신 라우트·회귀 검사를 되돌리지 말 것. 차이의 유효성만 별도 검토하고 중복 PR 정리 판단. |
| 항공권 [#106](https://github.com/6Soo/cost/pull/106), 영수증 [#107](https://github.com/6Soo/cost/pull/107) | 두 PR 모두 **OPEN/DRAFT**지만 각각의 브랜치는 현재 `main` 대비 **ahead 0 / behind 50**. 즉 PR 브랜치의 커밋은 이미 main 계보에 포함되어 있다. UI 코드도 main에 존재. | `MAIN_CODE_PRESENT / DUPLICATE_DRAFT_REVIEW`. 브랜치가 최신 main보다 뒤처져 있으므로 추가 코드 병합이 아니라 PR 중복 정리·실제 UI 검증 근거 확인. PR 자동 종료/삭제는 하지 않는다. |
| 전체 지출 자동 정리 제거 [#105](https://github.com/6Soo/cost/pull/105) | **OPEN, 문서 전용**. main `webapp/card_flow.py`에는 여전히 버튼 `#cleanup-reclassify`, POST `/api/imports/reclassify-pending`, 내부 재분류·장부 기록/여행 배정 함수가 존재한다. PR #105는 통합 UI 명세를 v1.2/§12로 확장하는 **미병합 제안**. | `SPEC_PR_OPEN / CODE_NOT_IMPLEMENTED`. 일반 UI 버튼 제거, 별도 owner 유지보수 화면, 읽기 전용 dry-run/명시 승인/감사·중복 보호는 아직 완료가 아니다. PR #105 검토 후 AUDIT→UI→MAINT 소형 작업으로 나눌 것. |
| `0630_오제` 수입 표시·장부 볼드 대조 [#110](https://github.com/6Soo/cost/pull/110) | **OPEN, 문서 전용**. 해당 명세에는 사용자 확정 **`0625_아키타`=2분기 마지막, `0630_오제`=3분기 첫 여행** 및 금액+날짜/가맹점/분류/예약번호 중 1개 일치 시 거래 후보 볼드 조건을 포함. main에는 아직 이 매칭 UI가 없다. | `SPEC_PR_OPEN / CODE_NOT_IMPLEMENTED / ROOT_CAUSE_UNVERIFIED`. Google 메인에 0630 탭이 있었다는 사실은 **2026-10-11 당시 기록**이며, 2026-10-25 실시간 시트·운영 비공개 스냅샷·매핑은 이 감사에서 읽지 않았다. |
| `0630_오제` 코드상 표시 차단 후보 | `webapp/google_ledger_page.py:trip_income_html()`의 `show_rows = bool(trip.get('verified')) and not numeric_gap`. `trip.verified`는 수입 **및 지출** 검증을 포함하므로 지출 오류만으로 수입표가 숨겨질 수 있음. 매핑 유일성·선택 원본·동기화 stale도 차단 조건. | `SOURCE_CONFIRMED_POTENTIAL_BUG`이지만 **오제 실운영 원인 확정 아님**. 수입·지출 검증 분리와 정확한 현장 원인 코드가 필요. 사용자 원본/금액을 외부 모델·Git로 복사 금지. |
| 분기 표시/회계 경계 | `webapp/ledger_design.py:previous_trip()`의 과거 여행 구분은 시작일 `2026-06-25` 이하; `_quarter_of()`는 시작 **월** 기준 달력 분기 계산. | 6월 30일 오제는 일반 목록에서는 3분기 활성 여행이지만, 다른 분기 그룹 재사용 시 2분기 오인 가능. 수입 조회는 `_quarter_of()`가 아니라 Google 매핑·검증 조건을 쓰므로 **원인 혼동 금지**. |

### 0.13.2 Git / CI / 운영 배포의 서로 다른 증거

- 이번 감사 시점 **open PR: #105, #106, #107, #108, #110 (5개)**. #103, #104, #109는 2026-10-25 `MERGED`, #101 및 #100/#102는 과거 병합·운영 문서 참조. `feat/card-all-transactions-ui-audit`, `docs/cost-ui-audit-v2-20261025`, `feat/cost-system-theme-v2-20261025`, 항공권·영수증 초안 브랜치는 `main`의 조상이므로 고유 코드 없이 뒤처진 상태. `deploy/ota-unified-20261021`은 **ahead 25 / behind 306**, 고유 변경 있음: 삭제/자동 병합 금지.
- GitHub Actions `main` 최근 실행 조회 결과는 **workflow runs 0건**, `d4c5934de07` 상태는 **pending / status context 0개 / check-run 0개**. 이는 CI 통과도 실패도 증명하지 않는다. PR 설명의 표적 검사 보고와 CI를 별도로 표시한다.
- **운영:** 과거 0.12절에서 확인한 실제 OTA·지출 정리 표기 배포 `1fcbc1ee60809fd10c7764cd8f93aeaa3701a608`은 보존된 운영 이력이다. V21 통합 `d4c5934de07`이 운영 호스트에 배포됐다는 증거는 이번 읽기 전용 GitHub 감사에서 **없음**. 운영 PC 작업 스케줄러·host·백업·DB·Google에 접근하거나 변경하지 않았다.
- 브라우저 375px, 라이트/다크 전환, 접근성 및 기능 전체 수락은 **이번 감사에서 NOT_TESTED**. PR #109의 표적 테스트 수치는 **PR에 보고된 실행 결과**이지 이번 문서 수정 세션이 재실행한 결과가 아니다.

### 0.13.3 명세 우선순위와 실제 다음 작업 (중복 재개 금지)

1. **상태 기준 우선:** `main` 실제 코드 및 병합 SHA → 통합 UI 명세 v1.1(현재 `main`) → **열린 문서 PR #105(§12, v1.2 제안)** / **#110(오제·거래 볼드 제안)**을 구분한다. 열린 PR 내용을 main에 이미 병합된 규칙이라고 쓰지 않는다.
2. **PR 중복 정리:** #108과 main 간 정확한 2개 파일 diff를 재검토하고 유효 내용만 별도 반영 여부를 판단한다. #106/#107은 현재 main에 커밋이 포함되었는지 재확인 후 초안 정리. 사용자가 승인하지 않은 강제 삭제·무조건 병합 금지.
3. **V21 검증 격차:** 이전 표적 합성 테스트를 재활용하되 실제 가능한 브라우저(시스템 dark/light, 375px, 키보드)와 owner 접근을 한 번 표적 검증한다. 새 기능을 다시 만들지 않는다. 운영 배포는 별도 승인.
4. **PR #105 후속:** 일반 '전체 지출 자동 정리' 버튼만의 노출 제거를 목표로 하기 전에 서버 쓰기 경계·기존 호출자·유지보수 dry-run을 독립 티켓으로 검토한다. 버튼 숨김과 안전 완료를 혼동하지 않는다.
5. **PR #110 후속:** `0630_오제` 실운영 원인 코드 확인은 **승인된 로컬 읽기 전용 운영 진단**에서만 수행; 수입과 지출 검증 분리/읽기 전용 Google↔웹 장부 시각적 볼드(동일 금액+1근거)를 합성 테스트로 구현한다. 출발일이 6월이어도 사용자가 정한 회계 3분기 경계 유지.
6. **감독 운영 최신 사용자 지시:** 상용 프론티어 모델은 짧은 티켓 배정·위임 결과·증거 심사·HOLD 판정에 집중하고, 실제 코드 조사/구현/표적 검증은 검증된 저비용 하위 에이전트에 분담한다. Paseo 네이티브 Skill/위임을 **우선 검증**하되, Skill 문서 로딩만으로 별도 실행이 됐다고 주장하지 않는다. 과거 Anus CLI 성공은 **Paseo Skill 성공의 증거가 아님**. 사용자 승인 없이 CLI로 자동 폴백하지 않는다. 반복 루프 방지: 작업당 재수정 최대 2회, 한 실행당 구현 티켓 4개/총 하위 호출 12회, 무진전 시 HOLD.

**이 절은 진단/현황 정리로, 문서 작성이나 PR만으로 버튼 제거·오제 수입 복구·볼드 매칭·V21 운영 배포 완료를 선언하지 않는다. 과거 0.12 이하의 운영 사실을 현재 V21 배포 증거로 소급 재해석하지 말 것.**

## 0.12 2026-10-24 실제 OTA 미결 진단과 지출 정리 표시 복구

사용자의 새 명세는 실제 거래 A/B/C의 원본→중앙 대사→경비 미리보기→화면 안내를 추적하고 확인된 표시 결함을 수정하는 작업이다. 시작 main은 새로 조회한 `4fb4e701d055555f82c6654028d146349eee3ca4`이며 작업 브랜치는 `fix/expense-ota-status-20261024`다. 처음에는 표적 검사와 PR 작성까지 승인됐고, 이후 사용자가 병합·배포를 명시 승인해 완료했다. 실제 고객 거래 수정·기장·Google 쓰기는 이번 배포에 포함하지 않았다.

목적은 실제 미결 원인을 정확히 안내하는 것이다. 변경 대상은 지출 정리의 중앙 상태 투영·금융/여행 사유·환불 연결 표시와 원자적인 스냅샷 표시 조회다. 매칭 허용 오차·금융 보호·장부 쓰기·사용자 결정은 바꾸지 않는다. 검증은 변경 표시 경로의 합성 표적 테스트와 직접 인접 계약으로 한정한다. 확인된 원인 기록·합성 재현 수정·표적 검사·자기 검토·PR 병합과 승인된 운영 배포를 완료했다. 표시 복구 완료와 실제 미결 거래의 추가 근거 확보는 구별한다.

| 작업 ID | 상태 | 근거와 다음 항목 |
| --- | --- | --- |
| TRACE-ABC | COMPLETE | [세 거래 진단](expense-cleanup-ota-diagnosis-20261024.md)에 단계별 근거를 기록했다. A/B는 등록된 결제 사건 부재·카드 식별/금액 거절과 여행 권위 부족이다. C는 원결제 연결 완료지만 원결제의 여행 확인 자동 보류로 `refund_pair_incomplete`다. |
| DISPLAY-OTA | 구현·표적 검증·운영 반영 COMPLETE | 한 요청의 중앙 결과·후보·거절 사유·신선도를 투영한다. 복수 후보를 보존하며 stale/error를 정확 연결이나 예약 부재로 승격하지 않는다. 금융·여행 보류는 별도 표시한다. |
| DISPLAY-REFUND | 구현·표적 검증·운영 반영 COMPLETE | 원결제 부재/모호/연결·기록 대기/완료/충돌·초과 환불을 구분한다. 원결제 연결과 금융 보호를 함께 표시하며 금융 판정은 보존한다. |
| TEST-PR | COMPLETE | [PR #100](https://github.com/6Soo/cost/pull/100), 구현 커밋 `98f07cf7aaf98247214b8d673540d452d33baedb`. 지출 정리 25건, 중앙 표시 계약 11건, 환불 표시 6건, 스냅샷 표시 1건, 기존 인접 계약 3건이 각 변경 영향 범위에서 통과했다. 전체 pytest는 수행하지 않았다. PR은 MERGED이며 병합 SHA는 `1fcbc1ee60809fd10c7764cd8f93aeaa3701a608`이다. |
| DEPLOY-SMOKE | COMPLETE | 같은 SHA의 release 925개 파일 대조, DB 5개·보호 파일 59개 백업·별도 복원·전후 보존 PASS. 외부 health/ready 200, 비인증 OTA/import 401, Aside 소유자 화면 확인 완료. [운영 기록](operations.md)을 따른다. |

진단 당시 로컬 자료 경로는 `.local-archive/spec-completion/three-ota-cards/`였다. 2026-10-25 재개 환경에서는 해당 경로가 없어 재사용하지 않았고, 호스트에 남은 배포·복원·보존 결과를 확인했다. 원문을 다시 수집하거나 경로 부재의 원인을 추측하지 않는다. `private-*`는 고객 원문을 포함하므로 외부 모델·Git·로그에 전달하지 않는다. 원본 조회 중 SQL 변경은 0건이었다. 이번 배포 runtime은 `1fcbc1ee60809fd10c7764cd8f93aeaa3701a608`이다. 이전 runtime `d9c5adcbd6d5bce52229a218535283e841567e5a`와 복구 증거는 `D:/WebLedgerHost/data/backups/expense-cleanup-20261024T225203/`에 기록했다.

실제 세 거래를 캡처한 generation 261과 읽기 전용 DB로 로컬 렌더링했다. 세 거래 모두 표시됐고 A/B의 여행 권위 보류, C의 원결제 연결·금융 보류가 함께 안내됐다. 세 페이지의 중앙 결과 조회는 각 1회였고 DB 변경·쓰기 시도는 0건이었다. 이 로컬 렌더링 근거와 후속 운영 HTTP·소유자 화면 스모크 근거는 구별한다. 이후 후보 표시 라벨과 환불 후보 분기 변경은 해당 합성 표적 검사로 확인했다. 원래 사용자 main의 미커밋 두 파일·stash와 운영 원본은 보존했다.

위임은 사용자 지정 순서로 시도했다. Anus Free auto는 최초 표시 계약 8건 실패로 중단했다. DeepSeek V4.1 Flash Free는 제공자의 무료 사용 한도 초과, GPT-6 Luna low는 계정 사용 한도 오류로 중단했다. 다른 계정·유료 대체 없이 Supervisor가 수정·검증을 마무리했다. 완료한 검사·진단·배포를 반복하지 않는다. 배포 기록 문서만 반영하므로 추가 코드 테스트·빌드·재시작을 생략한다. 실제 거래 처리는 진단 문서의 추가 근거와 개별 보호 사유가 해결된 뒤 별도 승인 범위에서 진행한다.

## 0.11 2026-10-24 미결 사항 처리

사용자가 미결 개발·검증·안전한 운영 확인과 실제 미확정 거래의 근거 기반 처리를 승인했다. 과거 문서의 선택적 제품 구상 전체를 자동 구현하거나, 사용자 선택이 필요한 참가자·복수 예약 관계를 대신 확정하는 승인은 아니다.

| 작업 | 현재 상태와 근거 |
| --- | --- |
| 실제 참가자 API 최소 읽기 | COMPLETE. 등록 여행 두 건에 각 1회 조회했다. 첫 여행 후보 0명, 최근 출발 여행 후보 1명이며 영문명이 있다. HTTP 200, `no-store, private`, `Vary: Authorization`, revision과 허용 최소 필드만 존재함을 로컬에서 확인했다. 이름·여행 식별자·토큰은 보고서와 Git에 기록하지 않았다. 실제 신원 연결이나 원본 변경은 수행하지 않았다. |
| 기존 비브라우저 실패 7건 | 수정 후 모두 표적 통과. OTA 테스트 4건은 합성 manifest를 명시해 없는 개발 PC 기본 파일 의존을 제거했다. 통합 저장 검사는 원래 포털 출처·관측 ID가 바뀌는 실제 결함을 찾아 수정했고 명시 lineage 및 원본 삭제 뒤 동일성·충돌 보존도 확인했다. 여행 화면 검사는 현재 홈의 조회 안내와 고정 날짜를 사용한다. Windows CP949 검사는 stdin 대기 전에 확장 모듈을 초기화해 NumPy import 경합을 제거했다. |
| 카드 검색 브라우저 검사 | 접힌 상세 영역을 여는 단계를 검사에 추가했다. 이전 Aside 합성 펼치기·검색·원본 검토 근거를 재사용하며 Playwright 실행은 하지 않는다. |
| 실제 미결 지출 | PARTIAL. 최신 53건의 운영 복사본에서 정상 분류·기록 경로를 실행했다. 23건 처리·기록 0·기존 장부/원문/보호 표 보존을 확인했다. 항목 미분류가 3→19건으로 늘어 이 분류 변경은 운영에 적용하지 않았다. 실제 운영은 항목 3·여행 20·보호 검토 30의 53건이며 거래 변경·Google 쓰기는 0건이다. |
| 항공권 운영 연결 | COMPLETE. PR #96에서 명시 기능 활성화·호스트 내 영구 DB·기존 보호 토큰을 연결했다. 표시용 이름만 있던 색인에 최소 검증 근거를 보존하고, 후보 API는 신선한 결과만 사용한다. 실제 색인과 기존 소유자 세션의 화면 표시를 확인했다. 실제 사람 선택·저장은 수행하지 않았다. |
| 예약 정본의 실제 신원 쓰기 | 개별 원본과 해당 여행의 정확한 인물 연결을 확인한 사용자 선택이 필요하다. 후보 조회 성공만으로 사람을 대신 선택하거나 새 예약·보험·결제·실탑승 사실을 만들지 않는다. |

코드 변경은 OTA 통합 출처 보존과 항공권 운영 연결 및 직접 검사다. 카드 원문·금액·사용자 결정·환불·장부 쓰기 경계는 수정하지 않았다. 파서/색인 버전을 입력 지문에 포함해 기존 snapshot을 재검증한다. 전체 pytest는 반복하지 않았고 전체 회귀 통과로 보고하지 않는다.

**코드·배포 COMPLETE:** [PR #95](https://github.com/6Soo/cost/pull/95), main 및 운영 SHA `56f1a976148df89fa25233af3fff55e27e643e49`. release 파일 921개 대조, DB 5개·보호 파일 59개 백업·별도 복원·배포 후 보존을 확인했다. 복구 경로는 `D:/WebLedgerHost/data/backups/toyoko-reservation-20261024T164250/`다. health/ready 200과 비인증 OTA·예약 관계 preview 401, 관리 작업의 원래 Enabled/실행 상태 복구를 확인했다. 실제 운영 DB 마이그레이션·거래 재기장·Google 쓰기는 이 배포에 포함하지 않았다.

**실제 외부 의존성:** Trip.com의 기존 계정으로 직접 연결되지 않는 예약은 예약 이메일 검색의 인증 코드가 필요하다. Aside에서 `/passport/ordersearch`의 이메일·인증코드 받기 화면을 확인했고 사용자에게 직접 인증을 요청했다. 코드를 읽거나 대신 입력하지 않는다. 인증 전 해당 상세 수집만 BLOCKED이며 다른 작업은 진행한다. 토큰 종류 UNKNOWN은 정상 조회에 문제가 없어 새로운 작업이나 토큰 교체 사유가 아니다. L4 추가 solver 분해는 확인된 운영 비용이나 결함이 없어 이번 미결 처리에 필요하지 않으며 기존 복구 fallback을 유지한다.

**항공권 후속 운영 배포 COMPLETE:** [PR #96](https://github.com/6Soo/cost/pull/96), 최종 runtime SHA `d9c5adcbd6d5bce52229a218535283e841567e5a`. 관련 표적 7건은 기능 opt-in/영구 DB·비활성화 시 백업, 보호 토큰·비노출, 실제 색인→후보 API·stale 거부, 기존 표시 호환·저장 멱등·owner/CSRF를 확인했다. 기존 합성 브라우저 근거는 재사용했다. release 파일 921개와 launcher 일치, DB 5개·보호 파일 59개 백업·별도 복원·배포 후 보존을 확인했다. 설정은 `flight_passengers.enabled=true`만 변경했고 다른 설정과 자료는 같았다. launcher와 설정의 원래 사본을 복구 경로 `D:/WebLedgerHost/data/backups/flight-host-20261024T165551/`에 보존했다. health/ready 200, 비인증 화면/후보 API/저장 API 401을 확인했다. GET이나 기능 활성화만으로 연결 DB를 생성하거나 실제 사람을 저장하지 않는다.

실제 워커 generation 253에서 `ota-passengers-v2`와 현재 snapshot key의 일치, 항공 예약 근거 177건·승객 표기 67개에 필요한 원본 식별자/내용 지문 및 최소 필드만 존재함을 로컬에서 확인했다. 이 집계는 확인된 실제 고객 67명이나 새 연결 67건을 뜻하지 않는다. 이후 사용자의 로그인 진행 지시에 따라 Aside의 기존 소유자 세션에서 `/flight-passengers`를 열어 예약 번호·여행 정본 ID·후보 조회가 표시되는 실제 화면을 확인했다. 새 비밀번호를 읽거나 입력하지 않았고 실제 참가자를 선택·저장하지 않았다.

**53건의 정확한 잔여 경계:** 주 사유는 취소 원행 25건·비용 항목 미확인 3건·여행 근거 미확인 20건·기존 여행/권위 보호 재검토 3건·명시 사용자 보류 2건이다. 직접 미리보기에서는 분류 미완료 22·여행 무효 3·환불 pair 불완전 5·사용자 보류 2·추가 OTA/자동 기록 보호 대상 21이었다. 두 집계는 서로 다른 축이므로 더하지 않는다. 기존 장부와 거래 ID 또는 엄격한 구형 금융 키가 같아 단순히 정리 목록에서 제외할 수 있는 거래는 0건이었다. 원본과 실제 여행 근거·원결제/환불 연결·사용자 보류 결정을 확인하지 않고 새 기장이나 보류 해제를 하지 않는다.

복사본 검증의 `PASS`는 원문·기존 회계·보호 표 보존을 뜻한다. 53건의 미결 해소나 분류 품질 개선을 뜻하지 않는다. 로컬 근거는 `.local-archive/spec-completion/pending-trial-20261024T163948/result.json`, `pending-financial-audit.json`, `flight-host-production-smoke.json`, `flight-index-production-verification.json`에 보존하며 개인정보·토큰을 Git에 추가하지 않는다. 다음 실행은 사용자 인증 완료 후 해당 예약의 추가 원문 확인과 개별 근거/보류 결정이 확보된 거래만 재개한다. 이미 통과한 검사·배포·API 인증·소유자 화면 확인은 반복하지 않는다.

**다음 메일 로그인 COMPLETE:** 사용자가 직접 로그인한 뒤 Aside에서 해당 메일함 접근을 확인했다. 비밀번호·인증 코드는 조회하거나 Git에 기록하지 않았다. Trip.com의 별도 예약 검색 인증 완료와 메일함 로그인 완료는 구분한다.

**보존된 Trip.com 예약 관측 4건 운영 추가 COMPLETE:** 앞서 직접 확인해 로컬에 보존한 이용 완료 숙박 2건과 취소 숙박 2건을 현재 운영 `ota-evidence.sqlite`에 추가했다. 사본에서 추가·기존 행 보존·허용된 메타데이터 표 외 보존·반복 수집 무변경을 확인한 뒤, 적용 직전 기준선 일치와 실제 추가 후 같은 보호 검사를 통과했다. 백업의 별도 복원 및 integrity 검사도 통과했다. MailCollect만 잠시 중지하고 원래 Enabled/Ready 상태로 복구했다. 복구 경로는 `D:/WebLedgerHost/data/backups/trip-observations-20261024T175631/`, 로컬 결과는 `.local-archive/spec-completion/trip-observations-applied-result.json`이다. 같은 추가 스크립트를 재실행하지 않는다.

추가한 원문은 숙박 이용 완료와 예약 취소 화면의 관측이며 카드별 결제·환불 확정이 아니다. 이용 완료 2건의 이용기간은 2026-09-30~10-01, 각 JPY 9,737이다. 현장 세금과 적립 Trip Coins를 카드 비용이나 포인트 사용액으로 합산하지 않는다. 이용일 2026-09-25의 85,621원 카드 2건은 외화 원문과 개별 결제 연결이 없고, 해당 숙박 기간과 일치하는 검증 여행도 확인되지 않았다. 환산 추정으로 예약번호·여행을 확정하지 않았다. board 전체 상태는 같으며 카드 장부·Google 쓰기 0건, 코드 배포·서버 재시작도 없다.

**메일 추가 대조:** 로그인된 다음 메일에서 2026-09-20~10-02의 `trip.com` 발신자 검색으로 09-25 결제 완료 안내 2건을 찾았다. 제목만 `Trip.com`으로 검색한 결과 0건은 메일 부재 근거가 아니다. 각 메일과 첨부 영수증의 예약번호·JPY 9,737이 보존 원문의 서로 다른 예약에 일치했다. 영수증 2건의 VISA 마스킹 카드 끝자리는 같았고 두 미결 카드 모두와도 같았다. 원화 청구액과 카드 원문의 외화 금액은 없어 이 결과를 개별 결제 확정으로 승격하지 않았다. 추가 확인 자료는 Aside 로컬 세션 `2026-10-24_PghppNds8zfRzY8Y/artifacts/`의 `payment1-private.txt`, `payment2-private.txt`, `trip-payment1-private.pdf`, `trip-payment2-private.pdf`와 비식별 summary에 보존했다. 인증 메일을 열거나 코드를 대신 입력하지 않았다. 다음 처리는 카드사의 외화 승인·청구 식별 근거와 해당 숙박 기간의 Google 권위 일정, 또는 확인된 개별 원문을 확보한 뒤 진행한다. 같은 기간의 반복 검색·환율 추정으로 이를 대체하지 않는다.

## 0.10 2026-10-24 토요코인 예약 관계와 결제 검증 분리

사용자가 예약 관계의 자동 추론과 사용자 확인, 금액 미확인 표시, 정상 카드 지출 준비의 독립 유지를 승인했다. 실행 명세는 [토요코인 예약 관계 계획](superpowers/plans/2026-10-24-toyoko-reservation-links.md)이다. 앞선 토요코인 구현은 예약 수집과 후보 표시까지였으며, 실제 예약 관계 연결 완료를 뜻하지 않았다.

운영 자료를 읽기 전용으로 확인한 시점에는 토요코인 카드 50건 중 29건에 후보가 있었고 21건에는 없었다. 이 중 18건의 외화 금액과 통화가 비어 있었다. 국내 원화 거래까지 포함한 외화 필드 누락 28건의 원본도 확인했으며, 25건의 XLSX 및 3건의 CSV 모두 해당 외화 열이 없었고 재파싱으로 복구되지 않았다. 누락값을 환산액으로 창작하지 않는다. 이 수치는 조사 시점의 집계이며 현재 예약 건수로 해석하지 않는다.

중앙 예약 관계 계산 및 별도 사용자 확인 저장, 카드·OTA 화면 표시와 확인 UI, 금융 및 점유 보호의 표적 검사와 검토를 거쳐 승인된 병합·배포를 수행했다. 기존 결제 확정 링크에 예약을 결제 완료로 넣지 않는다. 예약 관계만으로 장부 행을 추가하거나 추론 예약번호를 Google 복사 F열에 넣지 않는다. 사용자 확정 여행과 원본은 보존한다. 개발 검증과 실제 운영 반영 근거를 아래에 구분해 기록한다.

개발 코드는 `1487b34915fca4bdf76f08e8be5cbb588baa4fb7`까지 반영했다. 서로 유일한 지점·숙박기간·금액 근거는 자동 예약 추론 관계로 표시하고, 지점 또는 금액 미확인과 복수 후보는 사용자 확인 경로에서 설명한다. 확인 관계는 전용 review DB의 별도 표와 이력에 보존하고, 기존 결제·그룹 및 다른 예약 관계의 점유를 즉시 쓰기 트랜잭션 안에서 재검사한다. 자동 paid solver도 사용자가 확인한 예약 관계 카드를 재사용하지 않는다. 근거가 바뀌거나 소실되면 원래 선택을 삭제하지 않고 재확인 필요로 표시한다.

표적 검사 105개 범위를 한 번 실행해 99개가 통과했으며, 후보 검색을 제공하지 않는 주입 백엔드의 공통 점유 집합 초기화 누락으로 6개가 실패했다. `229754d`에서 공통 점유 계산을 옮겨 해당 6개가 모두 통과했다. 코어·공개 응답·원문 및 수동 여행 보존 통합 6개와 이후 UI 변경의 문법·통합 검사 2개도 각 기록한 HEAD에서 통과했다. 105개 전체 및 전체 pytest를 반복하거나 최종 HEAD의 전체 회귀 통과로 보고하지 않는다. Aside 최종 합성 화면은 `1487b34` 고정 사본에서 확인했으며 예약 관계만 1건 저장되고 결제 links는 0건, 카드 모든 열이 그대로였다. 국내 금액 차이와 저장된 가맹점·날짜·금액 표시 및 다른 예약의 점유 안내도 확인했다.

**병합·운영 배포:** [PR #92](https://github.com/6Soo/cost/pull/92)는 `587db6316444f843b971a189e7523a5529f424b8`에 병합됐고 같은 SHA를 `D:/WebLedgerHost/releases/587db6316444f843b971a189e7523a5529f424b8`에서 실행한다. 파일 921개를 archive와 대조했으며, 복구 근거는 `D:/WebLedgerHost/data/backups/toyoko-reservation-20261024T120518/`에 있다. DB 5개·보호 파일 59개의 백업 및 별도 복원, 배포 후 기존 DB 표·schema와 파일 보존 검사가 통과했다. healthz·readyz 200과 비인증 import·ota·신규 예약 관계 preview 경로의 401을 확인했다. 실제 사용자 관계를 대신 저장하거나 원행을 재기장하지 않았다. Google 쓰기도 없다. Board·SourceRefresh는 Running, MailCollect·GoogleAuthority는 Ready, 모두 Enabled다. 이후 문서 전용 커밋은 운영 코드 변경이 아니다.

**최종 운영 SHA는 `3a94dbe589b9f9fbb9cb2b36774c08b9bbb1cf24`다.** 첫 운영 결과에서 후보도 저장 관계도 없는 과거 예약이 기본 검토에 노출되는 표시 회귀를 발견해 [PR #93](https://github.com/6Soo/cost/pull/93)으로 한 조건만 수정했다. 중앙 예약·결제 계산과 전체 예약 목록은 그대로이며, 실제 후보와 추론·사용자 확인·근거 변경 관계 및 취소·충돌 보류를 보존한다. 해당 합성 통합 검사 1개와 diff 검사가 통과했다. 같은 보호 절차로 재배포했으며 최종 복구 근거는 `D:/WebLedgerHost/data/backups/toyoko-reservation-20261024T121451/`다. DB 5개·파일 59개 백업·별도 복원 및 배포 후 기존 상태 보존, 새 실행 경로 신원과 최소 외부 스모크가 통과했다.

첫 배포의 실제 운영 스냅샷 generation 245에서는 토요코인 카드 50건 중 45건에 예약 관계 후보가 있었고 자동 추론은 0건이었다. 지점·숙박기간·원문 금액이 일치한 관계 29개도 카드 한 건을 동시에 가리켜 서로 유일한 대응이 아니었다. 예약 후보를 임의로 결제 확정하지 않고 사용자 확인 경로를 제공한다. 남은 5건은 후보가 없으며 연결 완료로 보고하지 않는다. 자동 추론 규칙의 합성 검증 통과와 실제 자료의 자동 연결 수는 구분한다.

## 0.9 2026-10-24 사용자 승인 병합과 운영 배포 완료

사용자가 개발 완료 후 main 병합과 운영 배포를 명시 승인했다. [PR #91](https://github.com/6Soo/cost/pull/91)은 `a3474a8f481590ed2189449c5d2113c7a2e933ff`에 merge됐고, 포함된 PR #88·#89·#90도 MERGED 상태다. 별도 저장소 Travel INS PR #5는 이번 COST 배포 대상이 아니다.

- **실제 운영 코드:** `a3474a8f481590ed2189449c5d2113c7a2e933ff`, `D:/WebLedgerHost/releases/a3474a8f481590ed2189449c5d2113c7a2e933ff`. Git archive의 파일 918개를 추출 사본과 대조했다. merge tree는 검토 후보 `329b2ec`와 같고, 329b2ec의 추가 변경은 테스트 teardown 한 줄뿐이다. 이후 인계 문서 전용 main 커밋은 운영 코드 변경이 아니다.
- **보호 게이트:** 관리 작성자를 잠시 중지하고 기존 도구로 DB 5개·파일 59개의 백업과 별도 복원을 검증했다. 복구 binding과 원본 불변 검사는 통과했다. 근거는 `D:/WebLedgerHost/data/backups/spec-integration-20261024T095950/`의 restore-evidence.json, protection-result.json, deployment.json이다. 고객 원문·비밀값은 Git에 넣지 않는다.
- **전환:** 사용자 main의 미커밋 두 파일과 stash를 그대로 보존하고 Board 관리 작업의 실행 checkout만 위 release로 바꿨다. MailCollect의 인증·인자·주기는 유지하고 working directory만 같은 release로 바꿨으며 추가 수집을 즉시 실행하지 않았다. SourceRefresh와 GoogleAuthority의 기존 action은 유지했다.
- **배포 후 보호:** 프로세스 생존 정보 rule_process_leases만 제외하고 DB 표·schema가 기존 상태와 같았다. 원본·영수증·Google 읽기 자료·host config 파일도 같았다. 운영 마이그레이션·재기장·Google 직접 쓰기는 수행하지 않았다.
- **실행 확인:** Board와 SourceRefresh는 Running, GoogleAuthority와 MailCollect는 Ready이며 모두 Enabled로 복구됐다. 8751 listener는 1개이고 실제 launcher command line과 Board action이 새 release를 가리킨다. 외부 `/healthz`·`/readyz`는 200, 비인증 `/import`·`/ota`·`/flight-passengers`는 401로 한 번 확인했다. 실제 고객 후보 payload나 로그인된 운영 화면을 검증한 결과는 아니다.
- **병합 검사 한계:** 37ee832의 비브라우저 전체 회귀는 테스트가 직접 connection을 닫아 Windows 접근 위반으로 중단됐다. 329b2ec에서 기존 board.close 경계를 사용하도록 고쳐 해당 nodeid 1 passed를 확인했다. 비브라우저 실패 7개는 fe34048 기준에서도 같은 실패였다. 제외 조건이 놓친 기존 브라우저 검사 1개는 접힌 상세 영역을 열지 않고 내부 링크를 기다렸다. page·렌더 분기·검사 파일은 기준과 같았고 Aside에서 펼치기→전체 카드 검색→합성 3건 표시를 확인했다. 전체 회귀는 재실행하지 않았으며 전체 통과라고 주장하지 않는다.

**현재 승인 큐:** 개발·병합·운영 배포·최소 스모크는 완료했다. 기존 기준선 실패 7개는 이번 변경으로 생긴 실패가 아니며 별도 요청 없이 재구현·반복 검사하지 않는다. 실고객 참가자 조회·정본 신원 쓰기·L4 solver 추가 개편은 이번 배포로 승인·검증됐다고 보지 않는다. 새 요청이나 새로운 장애 근거가 있을 때만 해당 범위를 이어간다. 재개 시 최신 main 문서 커밋과 실제 runtime SHA를 구분하고 사용자 로컬 main을 강제 동기화하지 않는다.

## 0.8 2026-10-24 개발 후보 인수와 후속 구현 (병합 전 기록)

현재 개발 후보는 [COST 초안 PR #91](https://github.com/6Soo/cost/pull/91)의 `integration/cost-v3-spec-completion` 브랜치다. 원격 main 기준은 `fe340481ed5783d23f678d6a3df542ae8e6ce437`이며 main 병합과 운영 배포는 이번 범위에 포함하지 않는다. 구현자는 사용자 최신 지시에 따라 GPT-6 Luna low로 전환했다. 이전 ANUS 무료 제공자는 실제 일일 한도 429로 중단됐으며 재시도하지 않았다.

| 작업 | 개발 상태와 실제 근거 |
| --- | --- |
| 원 세션 및 완료 하위 작업 인수 | 완료. COST [PR #88](https://github.com/6Soo/cost/pull/88) `9968963`, [#89](https://github.com/6Soo/cost/pull/89) `dbc23e4`, [#90](https://github.com/6Soo/cost/pull/90) `66ddf95`를 보존했다. 별도 [Travel INS PR #5](https://github.com/6Soo/travel_ins/pull/5) `d8d2639`와 기존 합성 17 passed도 인수했다. 모두 확인 당시 open이며 자동 병합하지 않았다. |
| T1a 통합 | `f86690b`. Toyoko 후보와 L1 상태·설명 helper의 충돌을 수동 통합했다. Toyoko 2·우선배정 3·관련 메일/예약 28·사용자 규칙 7 passed를 인수했다. 금융 solver·원장·snapshot·store 경계는 그대로이며 읽기 검토의 중대 지적은 없었다. |
| T1b L2 | `48e4c73`, `e443a25`, `d6401fc`. 이미 판정된 후보 선택을 순수 규칙 집계 helper로 분리했다. 실제 BASE 메서드 frozen fixture와 현재 wrapper의 출력·nets 호출·여행 유효성 호출·입력 불변성을 단일 nodeid에서 비교해 1 passed. 마지막 유효성 재확인과 None snapshot을 포함한다. 읽기 검토 잔여 지적 0. |
| T2 L3 | `f14b65e`. 두 자동 기록 호출을 유지하고 목적 주석만 추가했다. 실제 dispatch와 임시 SQLite의 표적 nodeid 1 passed. 첫 기록 1·후속 0 및 합성 hold 해제 첫 0·후속 1, 재업로드 멱등과 수동 이동 보존을 확인했다. 실제 모든 OTA 상태의 불필요성은 증명하지 못했으며 합성 hold 전환을 실제 OTA 정책 검증으로 보고하지 않는다. 별도 환불 fixture는 dispatch 환불 검사와 구분한다. |
| T3 항공권 G1~G4 | `fe97a1e`, `6591084`, `4901f06`, `3ac0ae2`. 권위 후보 이름의 공백·제한 역순 비교, 원본 내용 digest와 proposal 결속, 오래된 연결 보존·재확인, 정확한 승객 proposal별 연결, 취소·여정 충돌 확정 차단을 보완했다. 후속 영향 검사 10 passed, 예약 단위 경고 보완 2 passed, 조건부 취소 문장 보완 1 passed. 합성 Aside에서 저장→원본 변경→재확인→승객 없는 취소의 이력 보존을 확인했고 취소 경고만 추가 확인했다. |
| T4 지연 여행 이동 G5 | `4252690`. 저장된 요청의 transaction ID·originating revision과 현재 수동 결정·대상을 기존 공유 RLock 안에서 확인한다. 늦은 B 후처리와 학습은 superseded로 반환해 최신 C를 되돌리지 않는다. B→C→B에서도 옛 요청은 거부하며 최신 요청 재시도는 유지한다. 새 경합·기존 정상 API 이동·AI 초기화 실패의 표적 검사 3 passed. 독립 읽기 검토 잔여 지적 0. |

이 표의 코드와 검사는 개발 브랜치의 근거다. 운영 DB·실제 고객·Google·서비스 재시작·배포·운영 인증 재시험은 수행하지 않았다. 과거 정상 인증 404와 기존 CI·운영 증거는 그대로 재사용한다. 전체 디렉터리 검사를 시도한 이전 작업자는 중단했으며 잘린 출력은 전체 통과 근거로 인정하지 않는다.

이번 승인 개발 큐 T1~T4는 완료했다. 항공권은 `46e9977`에 충돌 없이 통합했다. merge 결과의 항공권 6개 파일은 검토받은 flight HEAD와 같고 CardFlow는 검토받은 통합 부모와 같다. 금융 solver·원장·분류·사용자 결정 저장·snapshot·store·Google 복사 파일은 f86690b와 바이트가 같아 기존 유효 검사를 반복하지 않았다. 최종 문서 커밋과 원격 HEAD는 PR #91에서 확인한다. 완료된 R0~R6와 기존 PR 작업을 재구현하지 않는다. L4 중앙 solver 추가 분해·legacy fallback 삭제·운영 cutover는 A 정책 16.9절의 별도 범위로 남긴다. 운영 실고객 참가자 조회는 별도 개인정보 접근 승인 전 수행하지 않는다. 전용 토큰 종류의 UNKNOWN은 정상 인증을 반복 검사할 이유가 아니다.

로컬 main의 미커밋 항공권 파일과 미추적 stop-gate 자료는 사용자 변경으로 보존했다. 새 세션은 위 브랜치와 PR의 실제 HEAD·상태를 확인하고 이 문서에서 미완료인 항목만 이어간다. 로컬 보고서나 과거 채팅이 없어도 원격 커밋·테스트 파일·PR로 재개할 수 있다.

## 0.1 2026-10-23 실행 갱신 (당시 기록 — 이후 검증은 0.3~0.5 참조)

- COST `main`과 `origin/main`은 `15cdccc5536bd3b4b6af97e595a12af49fcb8456`으로 같았다. 작업 트리의 기존 미추적 `.claude/stop-gate/`는 보존했다.
- 운영 코드 체크아웃 `C:\AX\cost`에서 보호 백업·별도 복원 검증을 실행했다. 데이터베이스 5개와 파일 59개의 비교, 원본 상태 불변, 복원 연결 일치를 확인했다. 실제 요청 재실행, 운영 자료 가져오기, 비밀 파일 복사는 하지 않았다.
- 호스트 작업 재시작 후 `127.0.0.1:8751/healthz`와 `/readyz`가 모두 정상 응답했다. 현재 코드는 승인된 `main` 체크아웃에서 제공된다. 자동화된 직접 재시작 스크립트는 예약 작업 인자 형식 검사에서 `SUPERVISOR_IDENTITY_UNVERIFIED`로 종료했지만, 보호 절차가 예약 작업을 다시 시작했고 서비스 정상 응답을 확인했다. 해당 검사 우회는 하지 않았다.
- 최신 `main`의 읽기 전용 런타임 검증은 `LIGHTWEIGHT_RUNTIME_VERIFIED`로 통과했다. DB 무결성 `ok`, 인증 없는 `/healthz`·`/readyz`는 200, `/import`·`/api/imports`는 401이었다. 여행 62개 중 20개는 검증됐고 42개는 일정 권위 확인 대기다. 원본 6,395건과 장부 행 2,564건은 조회만 했다. 근거 파일은 로컬 `.local-archive/lightweight-20261003/runtime-verification.json`에 있으며, 해당 파일은 Git에 추가하지 않는다.
- 참가자 API에 COST의 기존 보호 토큰 파일을 사용해 합성 식별자 한 건만 읽기 요청했다. 응답은 `401 Unauthorized`였고 후보 자료는 반환되지 않았다. 이 파일은 Reservation의 현재 `INTERNAL_API_TOKEN`과 일치하지 않거나 더 이상 유효하지 않다. 토큰 값은 읽거나 출력하지 않았고 교체·발급도 하지 않았다. 따라서 COST↔Reservation 인증 읽기와 화면의 실제 원본 연결은 여전히 차단 상태다.
- 오래된 `deploy/ota-unified-20261021`은 최신 `main`과 통합하면 V3 코드·검사를 포함한 107개 경로에서 약 11,700줄을 삭제한다. 이 브랜치 병합은 중단했고 `main`에는 해당 삭제를 반영하지 않았다.
- **당시 다음 작업(현재 폐기됨):** 보호 토큰과 내부 API의 인증 불일치를 조사해야 했다. 이후 0.3의 합성 404로 인증 통과가 확인됐다. **현재 인증 재시험·무조건 토큰 교체 금지.**

## 0.2 2026-10-23 추가 확인 — 참가자 전용 내부 토큰 인증 불일치 수정

- 기존 Reservation `src/lib/internalAuth.ts`는 `INTERNAL_API_TOKEN` 및 `COST_INTERNAL_API_TOKEN`을 모두 허용했으나 참가자 후보 라우트만 `INTERNAL_API_TOKEN`을 단독 비교하고 있었다. 이 불일치는 COST 호스트 파일에 정당한 COST 전용 토큰이 있어도 401을 만드는 **가능한 원인**이다. 호스트 실제 토큰 내용을 보지 않았으므로 유일한 실제 원인으로 확정하지 않는다.
- [Reservation PR #25](https://github.com/6Soo/reservation/pull/25) → `main` **3296255e07e0c654c41b48e347095c2aedd8443e**: 참가자 라우트가 공용 상수시간 내부 토큰 검증을 사용하도록 정렬. 무인증·미설정 fail-closed, DB 조회 전 401, `no-store, private`, auth 토큰 종류와 관계없이 동일한 후보 HMAC revision 유지. 바뀐 파일은 `src/lib/internalAuth.ts`, `src/lib/passengerCandidateRoute.ts`, `tests/passengerCandidateRoute.test.ts` 3개만.
- [Preview dpl_GVUxx8AKW5xoxxeK6nJsn6wydn2K](https://vercel.com/6soos-projects/reservation/GVUxx8AKW5xoxxeK6nJsn6wydn2K) READY, [main Actions run 39953733785](https://github.com/6Soo/reservation/actions/runs/39953733785) **unit 270/270 PASS, smoke PASS**, [Production dpl_DQGvxo765hwryWWURP2XFVDdXkkm](https://vercel.com/6soos-projects/reservation/DQGvxo765hwryWWURP2XFVDdXkkm) **READY**. 이 결과는 인증 로직/배포 검증이며 실제 운영 호스트의 인증 성공·실고객 읽기 성공 증거는 아니다.
- COST `webapp/reservation-passenger.env.example`을 `13705183` 문서 커밋으로 갱신: 호스트의 `RESERVATION_INTERNAL_API_TOKEN` 또는 보호된 파일은 **Reservation의 `COST_INTERNAL_API_TOKEN`(권장 COST 전용) 또는 기존 `INTERNAL_API_TOKEN`과 동일해야 한다**. `TURSO_READONLY_AUTH_TOKEN`은 Reservation DB에만 사용하며 호스트 내부 HTTP 토큰으로 사용 금지.
- **당시 P1 재개 지침(이후 0.3/0.4/0.5가 우선):** 보호된 COST 토큰과 Reservation 내부 토큰 중 무엇이 일치하는지 구별되지 않았다. 합성 404 인증 성공과 합성 브라우저 검증 이후에는 전용 토큰 일치 여부만 별도 확인하며, 인증 재시험이나 변경은 관성적으로 하지 않는다.

## 0.3 2026-10-23 후속 실행 — 합성 인증 요청 및 호스트 상태

- COST `origin/main`과 작업 디렉터리를 `1a094bbfec1ee06fcfe011969893e38836fee182`로 맞췄다. 직전 COST 커밋에서 `origin/main`까지는 handoff·진입점·환경 예시 문서만 포함한 3개 fast-forward 커밋이었으며, 앱 코드는 바뀌지 않았다. 기존 미추적 `.claude/stop-gate/`는 보존했다.
- Reservation `origin/main`은 `3296255e07e0c654c41b48e347095c2aedd8443e`로 원격 조회했고, 로컬 작업 디렉터리는 `da6a1e82...`의 별도 브랜치에서 사용자 수정 파일을 그대로 보존했다. 해당 디렉터리를 전환·수정하지 않았다.
- COST Windows 작업 `WebLedger-Board`는 `Running`이며 실행 인자는 승인된 `C:\AX\cost` 체크아웃을 가리킨다. 현재 `/healthz`와 `/readyz` 모두 200이다.
- `app/reservation_authority.py`의 토큰 순서는 환경변수 `RESERVATION_INTERNAL_API_TOKEN` → 환경변수 파일 경로 `RESERVATION_INTERNAL_API_TOKEN_FILE` → 호출자가 넘긴 보호 기본 파일이다. 현재 검증 프로세스와 사용자/시스템 환경에는 첫 번째 변수가 설정되지 않았고, 작업 정의에도 해당 변수를 인자로 지정하지 않았다. 보호 파일 경로에서만 인증값을 읽어 검증했으며 실제 실행 프로세스의 환경 메모리를 직접 덤프하지 않았다.
- 보호 파일 토큰으로 `https://reserve.foresttour.kr/api/internal/passenger-candidates`에 합성 여행 ID GET **1회**를 보냈고 응답은 **404**였다. 이는 PR #25의 Production 코드에서 인증을 통과했고 합성 여행이 없음을 뜻한다. 401이 아니므로 기존 보호 파일 값은 Reservation이 허용하는 두 내부 토큰 중 하나와 일치한다. Vercel 비밀값은 조회하지 않아 `COST_INTERNAL_API_TOKEN`과 `INTERNAL_API_TOKEN` 중 어느 이름의 값과 일치하는지는 구분하지 않았다. 인증 성공이 확인되어 별도 비밀값 변경은 하지 않았다.
- Reservation `3296255e`의 실제 코드 계약을 읽기 전용으로 검토했다. 응답은 `tour_id`, HMAC `source_revision`, 후보의 `kind`, 불투명 `reference_id`, 한글/영문 이름, 상태로 제한되며 고객 식별번호·연락처·결제/예약 원문은 응답에 없다. 저장된 이름 및 동반자 필드는 서버 내부에서만 복호화해 후보 최소 필드로 만든다. 응답은 `no-store, private`, `Pragma: no-cache`, `Vary: Authorization`을 지정하고 취소·삭제 상태를 제외한다. 인증 전에는 DB를 조회하지 않으며 데이터 접근/복호화 오류는 503으로 닫힌다.
- COST 표적 검사는 `python -m pytest webapp/tests/test_passenger_cross_repo_integration.py webapp/tests/test_flight_passenger_page.py -q`에서 **6 passed, 1 skipped**였다. 화면·저장·재조회·stale 재확정 단위 경계는 통과했다. 교차 저장소 브라우저 통합 검사는 Reservation 사용자 작업 디렉터리에 테스트 전용 `tests/fixtures/passengerCandidatesHttpFixture.ts`가 없어 skip됐다. 미커밋 Reservation 파일을 건드리지 않았다. 과거 handoff의 교차 저장소 합성 E2E 통과 보고는 이력으로 보존하되 이번 실행에서 재현했다고 간주하지 않는다.
- Reservation Production은 `3296255e`에서 `READY`, GitHub Actions run `39953733785`는 `main` SHA `3296255e`에서 `success`다. 이전에 확인된 같은 run의 unit 270/270 및 smoke 성공을 재사용했다.
- **남은 운영 P1:** 성공한 404는 COST 호스트의 보호 파일 값으로 API 인증이 된 증거이나, 두 Vercel 변수 중 구체적으로 어느 값과 일치하는지나 유효한 실제 여행의 후보 payload를 확인한 증거는 아니다. 개인정보 확인을 위해 실제 참가자 응답을 가져오지 않았다. 실제 고객 후보 데이터·source revision의 운영값과 원본 변경 뒤 stale 재확정은 승인된 비파괴 실데이터 검증이 아직 없다. Google, DB 쓰기, 비밀 변경, 배포는 수행하지 않았다.

## 0.4 2026-10-23 합성 교차 저장소 브라우저 재검증

- 0.3에서 사용한 Reservation 로컬 작업 브랜치에는 테스트 fixture가 없었지만, 원격 `main=3296255e`에는 `tests/fixtures/passengerCandidatesHttpFixture.ts`가 이미 포함돼 있었다. 사용자 변경을 보존하기 위해 main을 별도 격리 worktree로 열고 저장소의 원래 fixture를 수정 없이 사용했다.
- `COST_R5B_RESERVATION_ROOT=C:\AX\reservation-v3-synthetic-329` 설정으로 `python -m pytest webapp/tests/test_passenger_cross_repo_integration.py -q`를 실행해 **1 passed**를 확인했다. 실제 Reservation 핸들러 → HTTP → COST adapter → 브라우저 후보 선택 → COST SQLite 저장과 재조회 → 합성 원본 변경 → stale 표시 → 사용자 재확정 흐름이 통과했다. API 응답에 `source_revision`과 최소 후보 필드가 있고, 저장 결과에서 원본 예약 ID와 주민 식별번호 표본이 제외되는 검사도 통과했다.
- 격리 worktree에서 fixture를 바꿔 실행한 첫 시도는 원본 검증 근거로 쓰지 않았다. fixture를 `3296255e`의 원래 내용으로 복원한 후 성공 결과를 얻었다. 격리 worktree는 검사 후 제거했고 Reservation 사용자 작업 공간은 수정하지 않았다.
- 0.3의 **6 passed, 1 skipped**는 fixture가 없는 로컬 브랜치에서의 최초 기록이다. 원격 main의 공식 합성 fixture로 교차 저장소 브라우저 흐름을 재검증했다. 운영 실제 여행 후보 payload와 실자료 `source_revision`은 읽지 않았다. 따라서 P1 코드/합성 통합 검증은 완료했고, 운영 실자료 검증은 미수행으로 남는다.
## 0.5 2026-10-23 최신 재확인 — 합성 404 인증 성공 재사용·전용 토큰 일치 여부 미확인

- GitHub 원격 HEAD는 COST `678d97a617b19dd9618e2fb4cb40babd9b29f10d`, Reservation `3296255e07e0c654c41b48e347095c2aedd8443e`로 확인했다. Vercel Reservation Production의 **비밀값이 아닌 이름과 대상**만 조회해 `COST_INTERNAL_API_TOKEN`, `INTERNAL_API_TOKEN`, `TURSO_READONLY_AUTH_TOKEN`, `TURSO_READONLY_DATABASE_URL` 설정을 확인했다. 어떠한 secret 원문도 조회·복호화하지 않았다.
- **합성 운영 API의 404는 이미 인증 성공(0.3)을 증명한다.** 이번 검증에서는 호출하지 않았다. 합성 교차 저장소 브라우저 1 passed(0.4)도 재실행하지 않았다. 과거 401은 PR #25 이전 이력이다. 404로는 COST 보호 토큰이 전용 `COST_INTERNAL_API_TOKEN`인지 기존 `INTERNAL_API_TOKEN`인지 구별할 수 없다.
- **보안 운영자의 선택적 관리 점검:** 먼저 실제 실행 서비스의 COST 토큰 소스 우선순위(환경변수 `RESERVATION_INTERNAL_API_TOKEN` → `RESERVATION_INTERNAL_API_TOKEN_FILE` → 보호 기본 파일)를 확인한다. 승인된 비밀 관리 기능에서 두 저장소 값의 메모리 내 동등성만 비교하고, 외부 결과는 `dedicated_match=true/false/unknown`과 점검 시각만 남긴다. Vercel 저장된 Secret 값을 보호된 방식으로 확인할 수 없다면 `unknown`으로 남기고 비교를 강행하지 않는다. 값·해시·복사 파일을 채팅/콘솔/로그/Git/CI에 남기지 않는다.
- **비밀 변경 기본 금지:** 현재 인증은 성공한다. 전용 토큰 일치 여부가 unknown인 것만으로 토큰을 새로 만들거나 Vercel/호스트를 재배포하지 않는다. 불일치가 실제 확인되고 전용화 변경이 별도로 승인되면 기존 소비자를 보호하며 최소 Secret·호스트 설정만 동기화한다. 범용 `INTERNAL_API_TOKEN`은 무단 변경 금지.
- **남은 P1:** 운영 실제 여행 후보 payload, 실제 `source_revision`, 실데이터 원본 변경에 따른 stale 재확정은 개인정보 접근이 수반되므로 별도 승인 전 **UNVERIFIED/BLOCKED**. 운영 DB/Google 쓰기, 실제 고객자료 조회, 추가 합성 인증 요청, 작업 공간 변경 없음.


## 0.6 2026-10-23 최신 상태 — 실행 토큰 출처와 전용 토큰 비교

- COST 원격 `main`은 `d3b106c4654ed96b04db4bd47903488508e228e8`였고 로컬은 문서 변경을 fast-forward해 같은 기준에 맞췄다. 변경 전 COST 작업 공간의 기존 미추적 `.claude/stop-gate/`는 보존했다. Reservation 원격 `main`은 `3296255e07e0c654c41b48e347095c2aedd8443e`이며 기존 로컬 사용자 수정은 그대로 두었다.
- Vercel Reservation Production은 `dpl_DQGvxo765hwryWWURP2XFVDdXkkm`, `READY`, SHA `3296255e`로 재확인했다. 환경변수 메타데이터는 값 복호화 없이 조회했다. 전용 `COST_INTERNAL_API_TOKEN`은 Production 대상, 기존 `INTERNAL_API_TOKEN`은 Preview와 Production 대상이다. GitHub CI, 이전 합성 404, 브라우저 E2E는 요청대로 재실행하지 않았다.
- 실제 COST 작업 `WebLedger-Board`는 `Running`, 사용자 `kkokk`의 대화형 최고 권한으로 `C:\AX\cost\tools\start_web_ledger_host.ps1`를 실행한다. 작업 인자와 시작 스크립트에는 `RESERVATION_INTERNAL_API_TOKEN` 또는 `RESERVATION_INTERNAL_API_TOKEN_FILE` 지정이 없고, 두 변수 모두 현재 Process/User/Machine 환경에서 설정되지 않았다. `app/reservation_authority.py` 우선순위와 보호 파일 경로를 함께 대조하면 현재 구성은 `D:\WebLedgerHost\secrets\reservation-internal-token.txt` 기본 파일을 사용한다. 보호 파일 존재만 확인했으며 내용을 읽거나 복사하지 않았다. 별도 프로세스 환경 메모리를 덤프하지는 않았다.
- **전용 토큰 비교 결과: `UNKNOWN` (2026-10-23).** Vercel 연결에서 secret 복호화를 사용하지 않았고, COST 보호 파일 값과 Reservation `COST_INTERNAL_API_TOKEN`을 비교하는 승인된 양쪽 비밀 저장소의 메모리 비교 수단도 현재 제공되지 않는다. 이전 합성 404는 이 파일의 자격증명이 Reservation이 허용하는 두 변수 중 하나와 맞는다는 증거지만 전용 변수와의 일치 여부는 밝히지 않는다. 인증 장애나 `MISMATCH`로 판정하지 않는다.
- **운영자용 안전 절차:** 권한 있는 관리자가 승인된 비밀 관리 도구에서 두 값을 파일·클립보드·콘솔·로그·Git에 내보내지 않고 메모리에서만 비교한다. 관리 도구가 이 비교를 지원하지 않으면 `UNKNOWN`을 유지한다. 기록할 값은 `MATCH`, `MISMATCH`, `UNKNOWN` 중 하나와 점검 시각뿐이며 토큰·부분 문자열·길이·해시를 기록하지 않는다. `MISMATCH`가 실제 확인돼도 현재 서비스는 인증되므로 무조건 변경하지 않는다. 전용 토큰화가 별도 승인된 경우에만 기존 `INTERNAL_API_TOKEN` 소비자 영향을 검토하고 COST 전용 범위만 최소 변경한다.
- 이번 실행에서는 합성 요청, 운영 참가자 조회, 비밀값 변경, 서비스 재시작, 배포, CI/브라우저 검사를 수행하지 않았다. 이전의 합성 404 및 격리 합성 브라우저 1 passed가 현재 증거로 유지된다.
## 0.7 2026-10-23 종료 판정 정책 — 최신 사용자 지시

- 승인된 실행 가능 작업이 있으면 후속 프롬프트를 만들지 말고 현재 실행에서 직접 수행한다. 완료 보고는 자동 재개 신호가 아니다. 명시적 세션 인계, 새 독립 작업, 사용자 요청이 있을 때만 후속 프롬프트를 작성한다.
- 이미 통과한 검사·배포·인증은 새 결함 증거가 없으면 재실행하지 않는다. 종료 시 COMPLETE, BLOCKED, DEFERRED만 구분한다. `UNKNOWN`은 그 자체로 오류가 아니다.
- 현재 작업 상태: **COMPLETE** — Reservation 인증 코드와 Production 배포, 합성 API 404 인증 성공, 교차 저장소 브라우저 검증, COST 런타임 토큰 출처 확인. 기존의 통과 증거를 재사용하며 다시 호출하지 않는다.
- **DEFERRED** — COST 전용 토큰과 Reservation 전용 토큰의 값 일치 여부는 `UNKNOWN`이다. 실제 인증이 정상이며 현재 승인된 비밀 저장소 간 비노출 비교 수단이 없어 선택 점검으로 보류한다. 토큰·해시·부분 문자열을 만들거나 기록하지 않고, 불일치를 추정하지 않는다.
- **BLOCKED** — 운영 참가자 실자료와 실제 source revision을 조회하는 일은 별도 개인정보 접근 승인이 필요하다. 승인 전에는 조회하지 않는다.
- 로컬 `.claude/TASK_QUEUE.json`의 `R5B-LIVE-AUTH`는 위 완료 증거를 반영해 COMPLETE로 고쳤다. 과거 PR #25 전 401을 현재 차단 사유로 다시 선택하지 않는다. DEFERRED 점검은 실행 큐에 넣지 않는다. 기존 Stop hook과 보호 설정은 유지하며 삭제·우회하지 않는다.
- 실행 가능한 신규 승인 작업이나 결함 근거가 없으면 여기서 종료한다. 같은 차단을 재조사하거나 문서 갱신만을 후속 작업으로 만들지 않는다.
## 0. 새 에이전트용 즉시 실행 계약

**목표:** OTA↔실제 카드 대사, 여행 우선 배정, 사용자 이동·AI 규칙 승인, 한/영 참가자 연결, N:M 그룹, 금융 중복·환불 보호, Google 수동 붙여넣기까지 **승인된 COST V3를 실사용 가능하게 마무리**한다. 코드가 이미 있는 기능을 재작성하지 않고 **남은 미검증 경계와 실제 결함**부터 해결한다. 조사만 하고 끝내지 않는다.

1. **가장 먼저:** 6Soo/cost와 6Soo/reservation의 origin/main, 작업 트리, 열린 PR, GitHub Actions, 실제 Vercel 대상 SHA를 조회한다. 원격 SHA를 고정값으로 믿지 않는다. 로컬 미커밋·미추적·stash, 사용 중인 worktree를 보존한다.
2. **읽기 순서:** 이 문서 → [COST V3 진입점](COST_V3_START_HERE.md) → [OTA A 정책](ota-card-reconciliation-policy-a-v3.md) → [추론/AI/참가자/N:M 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md) → 해당 기능의 실제 소스와 검증. 필요할 때만 [Google 정본 계약](target-workflow-google-authority.md), [정본 회계 규칙](reconciliation-rules.md), [운영 이력](operations.md)을 읽는다.
3. **실행 흐름:** 승인 명세 기준 갭 확인 → 안전한 코드 구현 → 직접 영향 테스트 및 종단 검사 → diff/개인정보 확인 → 허용된 Git 반영 → 다음 실행 가능 항목. 작은 단위 완료나 최종 보고가 전체 종료 조건이 아니다.
4. **BLOCKED 판정:** 실제로 필요한 비밀정보/운영 권한만 차단한다. 그러한 권한 없이도 가능한 CI 원인 분석, 코드·계약 수정, 합성/Preview 검증, 문서 정리는 계속한다. 과금·운영 DB 변경·고객자료 전송을 자동 승인받은 것으로 간주하지 않는다.
5. **작업 큐와 종료:** 아래 우선순위 표는 이 문서의 과거 상태 기록이다. 최신 상태와 재개 기준은 0.9절을 따른다. 로컬 작업 큐는 필수 전제조건이 아니다. 완료 항목을 다시 선택하지 않고, DEFERRED 점검을 실행 큐에 올리지 않는다. 실행 가능한 승인 작업이 없으면 COMPLETE/BLOCKED/DEFERRED 상태를 기록하고 종료한다. 후속 프롬프트는 명시적 인계나 새 사용자 요청에만 작성한다.

## 1. 마지막 검증된 Git 및 배포 기준점

| 표면 | GitHub/플랫폼에서 확인한 사실 | 구분 |
| --- | --- | --- |
| COST 앱 코드 기준 | [6Soo/cost main](https://github.com/6Soo/cost/commits/main); V3 앱 코드 기준 **0bd6e933ab** | V3 앱 기준 뒤의 main 추가 커밋은 문서-only다. 운영 호스트 릴리스는 별개이며 main 전체 배포가 아니다. |
| Reservation 앱 코드 기준 | [6Soo/reservation main](https://github.com/6Soo/reservation/commits/main) **3296255e07** (2026-10-23 확인) | PR #22 참가자 API, PR #23 KST 테스트 날짜 고정, PR #24 오류 응답 캐시 방지, [PR #25](https://github.com/6Soo/reservation/pull/25) COST 전용 토큰 공통 인증 정합화 |
| Reservation Vercel | [Production dpl_DQGvxo765hwryWWURP2XFVDdXkkm](https://vercel.com/6soos-projects/reservation/DQGvxo765hwryWWURP2XFVDdXkkm) — target=production, state=READY, sha=**3296255e07** | PR #25 인증 정합화 배포 READY. c315c17 때의 무인증 401/no-store 검증은 이력이며, 새 호스트 인증 성공은 아직 미검증 |
| Reservation Actions | [PR #25 main workflow](https://github.com/6Soo/reservation/actions/runs/39953733785): **unit 270/270 SUCCESS, smoke SUCCESS** | **P0 완료 유지.** COST 전용 토큰 인증/기존 토큰 동등 응답/인가 실패 시 DB 미조회 회귀를 추가했으며 새 커밋 CI 통과 |
| COST 배포 | 운영 보고상 승인된 `main` 앱 코드가 `C:\AX\cost`에서 실행되고 `LIGHTWEIGHT_RUNTIME_VERIFIED`·health/ready 200 확인 | 구형 운영 릴리스 `6bda111`은 과거 이력. `deploy/ota-unified-20261021`의 자동 병합은 V3 대량 삭제를 유발하므로 금지. 외부 GitHub 연결만으로 Windows 프로세스를 직접 재검증하지 않음 |
| 로컬 작업 공간 | 에이전트 보고상 COST 미추적 .claude/stop-gate/, reservation 사용자 미커밋 변경 보존 | GitHub에서 로컬 상태를 확인할 수 없음. 새 실행 시 로컬에서 재확인 필수 |

**수치 주의:** 과거 에이전트의 “94%”는 **17개 자체 정의 체크 중 16개 확인**이라는 추정 지표이며 독립적인 명세 전체 완료율·운영 준비율이 아니다. 저장소 구현·합성 종단 검증은 상당 부분 완료됐으나 실제 운영 기능 검증과 별도로 취급한다. 새 에이전트가 임의로 백분율을 다시 만들지 않는다.

### 실제 배포와 기능 동작의 구분

- Reservation 최신 확인 Production은 `3296255e` [dpl_DQGvxo765hwryWWURP2XFVDdXkkm](https://vercel.com/6soos-projects/reservation/DQGvxo765hwryWWURP2XFVDdXkkm) READY, [main Actions unit 270/270·smoke](https://github.com/6Soo/reservation/actions/runs/39953733785) SUCCESS. 기존 `70b00859`는 과거 기록이다.
- 사용자 승인으로 Turso 읽기 전용 DB 자격증명 `TURSO_READONLY_AUTH_TOKEN`, `TURSO_READONLY_DATABASE_URL`이 Reservation Production에 저장됐고 제공자 권한 claim `a=ro`(기록상 만료 2026-12-22T11:01:37Z)를 검증했다. 이후 Production 재배포도 READY. COST 보호 토큰은 합성 tour 404로 인증 통과했으나 어떤 허용 토큰과 일치하는지는 미확인(0.3~0.5).
- 과거 unit 실패는 로그에서 정확히 `tests/masterDataQueue.test.ts`의 기대 3/실제 2로 확인됐고, [PR #22 이전 기준선](https://github.com/6Soo/reservation/actions/runs/39639564867)에서도 같았다. GET route만 실제 오늘(KST)을 쓰고 test fixture는 2026-10-10 기준이라 2026-09-20 종료 여행이 실행일에 따라 30일 범위를 벗어난 것이 원인. [PR #23](https://github.com/6Soo/reservation/pull/23)에서 해당 테스트에만 Node 22 `t.mock.method(Date,'now',...)` 적용 후 CI 녹색.
- 실제 운영 여행의 **참가자 후보 응답**은 개인정보 승인 없이 조회하지 않았다. 합성 없는 여행 ID로 404 인증 통과만 확인했다(0.3). 과거 데이터 표/권한 설정 점검 이력은 0.3 이전 당시 기록이며 운영 DB 행·스키마 변경/내보내기는 없었다. 선택은 COST 내부 연결일 뿐 실제 탑승·보험 확정이 아니다.

## 2. 구현된 범위 — 우선 재사용할 근거

| 모듈 | 구현·테스트 근거(대표) | 여전히 구별할 사항 |
| --- | --- | --- |
| R0 진단/R1 계보·수동 pin 보존 | tools/audit_ota_card_coverage.py; 원본 재수집·저장소 재열기·crosswalk·중복 ID 표적 검증 | 실제 운영 전체 소스에 대한 전수 정확도 분석은 별도 작업 |
| R2 날짜 누락·후보 | OTA 날짜 없는 거래 후보와 merchant alias 및 카드 유효성 분리 | 미확정 예약번호를 확정값으로 올리지 않음 |
| R3 중앙 대사 | app/ota_payments.py, webapp/ota_snapshot.py, webapp/ota_payment_review.py, webapp/card_flow.py; COST 30b29fd 등에서 API/카드/귀속/준비 같은 발행 세대 종단 검증 | stale fallback은 복구용. 분류·재분류에서 구형 엔진이 중앙 정본을 덮지 못하도록 유지 |
| R4 금융 readiness | 실제 카드 원행 기준 경비 준비; COST cbc1c9a 120,000원 OTA 미확정→웹 저장→Google 복사 예약번호 공란. 중복·환불·원본 충돌 보류 | 실제 운영 장부 자동 대량 재기장 금지 |
| R5 사용자 이동·AI 학습 | 여행 A→B 즉시 수동 저장, 선택지 1/2/직접 답변3, 규칙 미리보기·승인·미래 거래 반영, 브라우저 합성 검증 | 모델 장애에도 사용자 배정 유지, 규칙은 승인 전 미적용 |
| R5-B 참가자 후보 | COST owner 화면/HTTP adapter/SQLite 저장/재조회·stale 재확정; Reservation PR #22/#25; 원격 main 원본 fixture 기반 교차 저장소 합성 브라우저 `1 passed`(0.4) | Production READY, 합성 tour 404로 인증 통과. 전용/범용 어떤 토큰인지 UNKNOWN. 운영 실자료 후보·revision·stale는 미검증. 신원 자동 확정·실탑승 아님 |
| R6 레거시 소비 정리 | COST f52533e 대량 재분류 중앙 _ota_report, 268f7d8 stale fallback 경합 방지; 중앙 결정 권한 우선 | 오래된 스냅샷 복구용 fallback과 진단 전용 순수 비교 함수는 보존. 의미 없는 제거 금지 |
| N:M 그룹 | 2:2·2:3 그룹 제안, 결제일·금액/승인일·가맹점 증거 표시, 카드 원행 1건 1회 기록, 개별 대응 확정 금지 | 그룹 제안은 카드별 예약번호/이용기간/장부 날짜 확정의 근거가 아님 |

**검사 기록(에이전트 보고):** COST webapp/tests/test_card_flow.py 전체 67 tests + 28 subcases 통과; reservation API/snapshot 약 7개 표적 검사·TypeScript·ESLint 및 Preview 통과; 양 저장소 실제 합성 HTTP handler→COST adapter→owner browser→SQLite→stale 재확정 1개 통과. 이 문서 작성자는 해당 명령을 로컬에서 재실행하지 않았다. 최종 HEAD에서 변경 영향이 생긴 경우만 필요한 검사 재실행.

**직접 진입할 테스트:**
- COST: webapp/tests/test_passenger_cross_repo_integration.py, test_flight_passenger_page.py, test_card_flow.py, test_card_flow_browser.py, test_ota_payment_review_browser.py, test_cleanup_reclassification.py, test_targeted_test_selector.py (전부 webapp/tests 아래).
- Reservation: tests/passengerCandidateRoute.test.ts, tests/passengerCandidateSnapshot.test.ts, tests/masterDataQueue.test.ts, .github/workflows/smoke.yml.
- 구현 파일: COST webapp/flight_passenger_page.py, webapp/reservation-passenger.env.example, webapp/card_flow.py, webapp/ota_snapshot.py, webapp/ota_payment_review.py; Reservation src/app/api/internal/passenger-candidates/route.ts, src/lib/passengerCandidateRoute.ts, src/lib/passengerCandidateSnapshot.ts, src/lib/db.ts.

## 3. 미완료·미검증 작업 큐 (재개 우선순위)

### P0 — Reservation GitHub Actions unit 실패 복구 (**COMPLETE**)

**2026-10-23 실제 확인:** PR #22 이전 기준선 [workflow 39639564867](https://github.com/6Soo/reservation/actions/runs/39639564867)과 cc4e325/ dd734e0의 CI에서 동일한 `tests/masterDataQueue.test.ts` 기대 3/실제 2 실패를 로그로 확인했다. 테스트 fixture는 `TODAY='2026-10-10'`이지만 실제 GET route는 실행 시점의 KST 날짜를 계산해 2026-09-20 귀국 여행이 30일 조건에서 탈락했다. 운영 로직/기대 건수는 정상이고 테스트 실행 날짜 격리만 누락된 문제였다.

- [Reservation PR #23](https://github.com/6Soo/reservation/pull/23), squash main `70b00859e50a3239038f469ce1d07c006a9f78c5`: `tests/masterDataQueue.test.ts` **1파일**, +4/-1, scoped Date.now mock. 코드/DB/PII/.env 변경 없음.
- [main workflow 39939654895](https://github.com/6Soo/reservation/actions/runs/39939654895): **unit SUCCESS, smoke SUCCESS**. 반복 전체 테스트 불필요.
- [Production 수동 재배포](https://vercel.com/6soos-projects/reservation/36njAr5b7hTsGsZLgAFeHt96ZWzR): target=production, sha=70b00859, state=READY. 저장된 Production 설정을 적용했다. 후속 PR #24는 아래 현재 배포 항목에서 확인한다.
- [PR #24](https://github.com/6Soo/reservation/pull/24), squash main `c315c17a0fa3a0705530506345534e76d4004860`: 참가자 API의 200/400/401/404/503 응답을 `Cache-Control: no-store, private`, `Pragma: no-cache`, `Vary: Authorization`으로 통일. `tests/passengerCandidateRoute.test.ts`의 인증 실패·읽기 전용 설정 누락 응답 검사 추가.
- [PR #24 Preview](https://vercel.com/6soos-projects/reservation/5GAnS7yH31yD1VHTPvd2Az1W72C7): READY. Reservation 표적 Node 검사 3 passed, ESLint 통과, GitHub Actions unit/smoke 모두 SUCCESS.
- [현재 Production 배포](https://vercel.com/6soos-projects/reservation/7dNPpkvC5sWHtkPGn8gWfAns6GU1): target=production, sha=c315c17, state=READY. 무인증 요청 결과 `401`, `Cache-Control: no-store, private`, `Vary: Authorization`, 본문 `Unauthorized`. 후보 자료는 조회되지 않았다.
- **재개 규칙:** 같은 P0를 다시 구현·검사하지 않는다. 미래에 새로운 실패 로그/변경 SHA가 확인될 때만 새로운 영향 범위를 조사한다.

### P1 — R5-B 실서비스 읽기 연동 안전성 검증 (실제 운영 설정 권한은 별도)

**최신 상태(0.3~0.5): 코드 구현 COMPLETE / Turso readonly 설정·Production READY / 합성 운영 API 인증 PASS(404) / 원격 main 합성 브라우저 PASS(1) / 전용 vs 범용 토큰 일치 UNKNOWN / 실자료 후보·운영 revision UNVERIFIED.** 과거 401은 PR #25 이전 이력. 토큰 값을 조회하지 않았으며 승인 없이 비밀 변경하지 않는다. 운영 실제 후보 조회는 개인정보 접근 승인 전 수행하지 않는다.

1. Vercel Reservation의 현재 Production `3296255e` READY와 도메인/환경을 확인했다. 운영 환경변수는 **이름·대상 환경만** 확인하고 값은 출력·복사·로그하지 않는다. 과거 `c315c17` 배포는 기록으로 보존한다.
2. Reservation의 내부 API: /api/internal/passenger-candidates?tourFldid=... ; 보호 Bearer 인증. 서버측 읽기 전용 전용 DB 클라이언트가 기존 getDb() schema 초기화·PII 마이그레이션을 사용하지 않는 구조임을 유지.
3. 필요한 설정 **Reservation**: INTERNAL_API_TOKEN(기존 내부 소비자 영향 검토), TURSO_READONLY_AUTH_TOKEN(해당 단일 DB read-only scope 필수), 선택 TURSO_READONLY_DATABASE_URL. **COST**: RESERVATION_INTERNAL_BASE_URL, RESERVATION_INTERNAL_API_TOKEN 또는 보호된 토큰 파일 경로(정확한 변수 이름은 webapp/reservation-passenger.env.example에서 재확인).
4. 변수 이름에 READONLY라고 적힌 것만으로 DB 권한을 증명하지 않는다. 운영 DB에 INSERT/CREATE를 시험하지 않는다. 격리 비운영 DB의 동일 권한 정책으로 조회 허용·쓰기 거부를 확인하거나 제공자 권한 표시를 검증한다.
5. 운영에서 사용자 승인 범위 내 **비파괴 읽기/비식별 결과 검증**: 비인가 요청 차단(401), 누락된 설정 실패 폐쇄(503), 승인된 범위의 tour 한 건에 한정된 최소 데이터, source_revision, 고객 ID/RRN/전화/여권 비노출, COST 후보 화면→사용자 확인→내부 저장/재조회→원본 변경 stale. 실제 고객명·토큰을 문서·채팅·CI artifact에 남기지 않는다.
6. 운영 비밀설정/인증 접근권이 없으면 **이 운영 단계만 BLOCKED**. 코드·테스트/CI 문제는 독립 진행. 실제 credentials를 요청하거나 채팅으로 붙여넣게 하지 않는다. 사용자가 Vercel 및 COST의 비밀 저장소에 직접 설정하도록 정확한 변수명과 권한 절차만 안내한다.

**완료 증거:** 실제 접근 대상 서비스 SHA/환경, 비밀값 없는 HTTP 상태/경로별 결과, 권한 범위·PII 최소화, 원본 변경 시 stale 및 사용자 확정 보존 여부. 읽기만 하고 운영 DB 변경 금지.

### P2 — COST V3 전역 실사용 갭 및 운영 배포 경계 (오해 방지)

**최신 상태(0.3~0.5): COST `main` 앱 코드 운영 배포 COMPLETE / health·ready COMPLETE / 합성 운영 참가자 API 인증 PASS(404) / 운영 실자료 미검증.** 기존 보호 백업·복원 검증 후 승인된 메인 코드에서 서비스가 실행됐다. 초기 401은 PR #25 이전 이력이며 수정 후 합성 404를 확인했다. 운영 후보·실데이터 화면 종단 동작은 미검증이고 Google·운영 DB는 변경하지 않았다.

**보호할 실제 사용자 수용 기준:** 유효한 카드의 OTA 날짜/매칭 미확정→존재하는 실제 여행으로 추론 귀속→COST 내부 비용 준비→Google B:H 수동 복사 F 예약번호 공란; 중복·환불·원본 충돌은 비용 생성 금지; 2:2 그룹은 개별 예약 결제 동일시 금지/2:3 보류; 수동 여행 A→B 영구 우선; 승인 없는 AI 규칙 미적용; 참가자 한/영 후보는 사용자가 확인해야만 COST 연결, 원본 갱신 stale; 운영 Google 자동 쓰기 0. 필요한 실제 운영 시연에는 계정/운영 데이터 권한과 비파괴 범위를 먼저 확인한다.

**참고:** Google 정본 기반 전체 향후 제품 구상에는 별도 미확정 의사결정/선택 기능이 [목표 업무 명세](target-workflow-google-authority.md)에 있다. 이것을 'V3에서 이미 구현됐음'으로 표시하거나 새 승인 없이 자동 개발 큐에 넣지 않는다.

### P3 — 일부러 유지한 R6 복구 경로 (무작정 미완료 아님)

최신 중앙 정본이 존재하면 legacy가 결정을 덮지 못하고, stale/old snapshot 복구에는 fallback이 필요하므로 **남겨두는 것이 안전한 설계**다. 호출 그래프에 결정 권한을 우회하는 신규 실사용 경로가 확인되면 수정. 미사용 코드를 없애기 위해 기존 안전 경로를 제거하지 않는다.

### 별도 운영 문제 (본 V3 코드 재구현 작업과 구분)

[operations.md](operations.md) 및 [지출 정리 기록](cleanup-resolution-20261023.md)에는 과거 운영에서 근거 확인 대상 161건(항목 3, 여행 근거 125, 보호 33), 인증 대기 Trip.com 예약, 실제 장부 자동 기장 결과가 기록돼 있다. 이 수치는 **그 날짜의 운영 스냅샷**이며 V3 Git main 테스트와 다르다. 운영 후처리에서 오류를 반환한 **5건 자동 기장 스크립트는 실제 5건 기록에 성공했으므로 재실행 금지**. 자세한 복구 증거는 문서 내 로컬 경로를 참고하되 로컬 파일이 없으면 임의로 재생성·재기장하지 않는다. 인증코드·고객원본·취소 결제 근거는 외부로 전달하지 않는다.

## 4. 고정된 안전·업무 계약 (명세 전체를 읽지 않고도 보존)

- **실제 금융 원행이 비용의 원천**이다. OTA 예약만으로 카드 비용을 생성하거나 같은 카드 원행을 두 번 기록하지 않는다. 원본 충돌·중복·환불·취소 보호 우선.
- **여행은 Google 탭 기반 권위 있는 기존 여행만 사용**, 새 여행을 추론으로 생성하지 않는다. 신뢰 낮아도 유효 카드+후보 여행이면 AUTO_INFERRED 우선 귀속; 근거/불확실성 노출. 같은 조건 동률이면 검증된 수입-비용 차액 규칙. 사용자 고정 여행은 재분류·AI보다 상위.
- OTA 사용기간이 카드 승인일/OTA 결제일보다 우선인 조건을 지키고, 원문에 없는 예약번호·결제일·서비스 기간은 추정 확정하지 않는다.
- 카드 2실결제↔OTA 2실결제의 그룹 총량 일치는 개별 카드↔예약 ID 일치 증거가 아니다. 2:3은 개별 연결 미확정. 카드비용은 실거래당 1회.
- 항공권 영문 이름은 한글 예약자 후보를 보여 주되 자동 신원 병합, 고객 신설, 보험 입력, 실탑승 확정 금지. 개인정보 최소화, 비밀정보·고객 원본 외부 모델 전송 금지.
- **Google 최종 장부에 COST 자동 쓰기 금지.** COST 내부 기록/미리보기/복사가 Google 반영 완료라는 뜻이 아니다.
- 실제 운영 DB/고객정보 무단 변경 금지. 원본·사용자 확정·기존 수동 연결·기장 내역 보존. Git force-push 금지. 실제 운영 배포·새 유료 호출·공개는 별도 승인 범위를 따른다.
- COST와 Reservation의 기존 로컬 사용자 미커밋 변경을 보존. Reservation은 민감한 PII 저장소이며 자동 stage/add-all 및 무검토 push 금지.

## 5. 세션/로컬 도구 인계 (GitHub에 없는 상태를 허위 재생하지 말 것)

과거 개발 PC에 Paseo + Codex Stop hook이 연결됐다. hook은 로컬 TASK_QUEUE.json이 승인한 미완료 항목이 있을 때 한 턴 안에서 다음 작업을 선택하도록 시험됐고, 관련 합성 A→B→C 및 31개 검사가 통과했다고 보고됐다. **이 설정·큐·로그는 GitHub 정본이 아니다.** 새 PC/새 에이전트에서 자동으로 존재한다고 가정하거나 필수 자료로 요구하지 않는다. 현재 승인 작업은 0.9절과 최신 사용자 요청을 기준으로 판단하며, 과거 P0~P3를 새 실행 큐로 복원하지 않는다.

- 로컬 설정 참고 경로(해당 PC에 존재할 때만): C:\AX\agent-policy\local-backups\cost-continuation-20261023, COST 로컬 stop-gate.json/TASK_QUEUE.json, 미추적 .claude/stop-gate/.
- 이전 10분 반복 태스크 ID 5e75876d는 종료 단계에서 삭제 성공을 보고했다. schedule 조회는 'Schedule not found'를 반환했으므로 삭제 전후의 실행 로그와 상태를 새 환경에서 재확인한다. **재등록 금지**, 업무가 완료됐는데 스케줄이 다시 실행되면 공식 인터페이스에서 소유 관계를 확인하고 중지. Codex hook과 이벤트 기반 재개/Heartbeat를 중복 설치하지 않는다.
- GitHub 문서가 현재 작업의 재개 근거이므로 **이 채팅·로컬 파일·별도 기억 없이** 다음 에이전트가 0.9절에서 현재 상태와 남은 승인 범위를 판단할 수 있어야 한다. 완료된 P0/P1을 다시 시작하지 않는다. 비밀 토큰, 인증코드, 사용자 DB, 실제 개인정보는 GitHub에 기록하지 않는다.

## 6. 새 세션에서 바로 수행할 검증·작업 예시

시작 단계:
- 0.9절의 병합 main과 실제 runtime SHA, 해당 작업트리부터 확인한다. 기존 CI·배포·운영 인증은 변경이나 실패 근거가 있을 때만 다시 확인하며 과거 시작 절차를 자동 실행하지 않는다.
- **P0 완료:** Actions 39939654895 unit/smoke 모두 SUCCESS, PR #23 main 70b00859, Production READY. 새 실패 근거 없으면 재실행하지 않는다.
- **P1 설정·배포·무인증 경계·합성 404 인증·원격 main 합성 브라우저 확인 완료 / 실자료 검증 별도 승인 대기:** Reservation Production의 `TURSO_READONLY_*` Secret 적용 및 PR #25 `3296255e` Production READY. 합성 API 요청 404로 인증 성공, 교차 저장소 원격 main fixture 브라우저 1 passed. 정확히 전용 `COST_INTERNAL_API_TOKEN`인지 범용 `INTERNAL_API_TOKEN`인지 미확인. 실운영 후보·revision·stale는 미검증이며 운영 DB 쓰기 금지.
- 실운영 개인정보 접근이 필요한 P1 검증만 별도 승인 대기 상태로 유지하고 나머지 승인 작업은 계속한다. 운영 토큰 변경/회전은 일치 불일치가 실제 확인되고 별도 승인된 경우에만 한다.

표적 검사 예시 (로컬 의존성 설치와 실제 환경을 확인한 후):
- COST: python -m pytest webapp/tests/test_passenger_cross_repo_integration.py -q
- COST: python -m pytest webapp/tests/test_card_flow.py -q  (**과거 67개 통과 근거가 이번 변경에 의해 무효화됐을 때만**)
- Reservation: 실제 package.json의 test 실행기를 확인한 뒤 tests/passengerCandidateRoute.test.ts, tests/passengerCandidateSnapshot.test.ts 및 실패한 tests/masterDataQueue.test.ts만 실행.
- 문서만 고치면 diff·링크·표현 정합성만 확인하며 운영 서버 재시작·DB 조회·전체 테스트를 관성적으로 실행하지 않는다.

### 보고 계약

**구현 상태 / Git 반영 / CI / Preview / Production 배포 / 실제 운영 API 인증 / 실제 PII 보호 검증**을 분리해 보고한다. COMPLETE/FAILED/BLOCKED의 근거 URL·커밋·테스트를 남기고, 미완료를 성공으로 바꾸지 않는다. 한 단위 구현 후 다음 승인 항목으로 이동하되 실제 외부 자격증명이 필요한 단계에서는 사용자가 비밀 저장소에 입력할 정확한 항목만 요청한다.

> **인계 게시 변경 범위:** 이 문서 신설, COST docs/COST_V3_START_HERE.md · docs/session_handoff.md · AGENTS.md 진입점 교정, Reservation AGENTS.md에 COST 조건부 참조. **앱 소스/DB/비밀키/운영 토큰 내용은 수정하지 않음.** Reservation 문서 커밋 dd734e0은 Vercel 자동 Production 배포를 시작해 최종 READY로 확인됐다. 다음 세션에서도 최신 배포와 실제 API 인증 여부는 다시 조회한다.

## 7. 이 문서의 생명주기

- 사용자 승인 명세의 원칙은 [COST V3 진입점](COST_V3_START_HERE.md)과 두 세부 명세가 권위이며, **이 문서는 작업 진행 상태와 검증·재개 순서의 권위**다.
- 새 기능이 끝나면 이 문서의 P0~P3와 증거를 업데이트하고 완료 항목을 '재구현 금지'로 표시. 과거 전문과 운영 이력을 삭제하거나 숫자를 현재값처럼 재해석하지 않는다.
- 새 세션에서 이 문서가 오래됐다는 이유로 무조건 R0부터 다시 구현하지 않는다. 현재 Git 증거/테스트/로그로 먼저 비교한다.
