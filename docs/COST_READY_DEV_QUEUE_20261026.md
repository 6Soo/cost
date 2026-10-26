# COST 검증 가능한 개발 큐 — 2026-10-26

> 상태: **구현 PR #114 병합 및 운영 코드 배포 완료**. 현행 런타임은 `36f6cb32ac09805079e5ddb5641fe01032088fa7`이며, OTA 응답 최적화 후속 배포를 포함한다. OZE 운영 데이터·HTML 생성과 로그인 브라우저의 수입 35행 실제 표시를 확인했다. 과거 사용자 표시 실패 원인은 미확정이며 V21 전체 UI 수락은 PARTIAL이다. 최신 확인은 [인계 §0.18](COST_V3_CURRENT_HANDOFF.md)을 따른다.
> 기준: PR #114는 2026-10-25 UTC 17:33경(2026-10-26 KST 02:33경) 병합됐다. 같은 날 UTC 17:35경(KST 02:35경) 운영 작업·listener·릴리스 표식이 일치했고 health/ready 및 비인증 경계 검사가 통과했다. 최신 런타임과 OTA 응답 최적화 증거는 [operations.md](operations.md) 및 [현재 인계 §0.18](COST_V3_CURRENT_HANDOFF.md)을 본다.
> 범위: 구현된 코드의 배포는 완료했지만, OZE 과거 표시 실패 원인 확정과 V21 전체 로그인 브라우저 수락은 미완료다. 운영 DB·Google 원본·실고객 자료는 변경하지 않았다.
> 권위: [AGENTS.md](../AGENTS.md) → [진입점](COST_V3_START_HERE.md) → [현재 인계 §0.14](COST_V3_CURRENT_HANDOFF.md) → 본 READY 큐 → 각 상세 명세/금융 보호 규칙.

## 최신 합의·실행 큐 정본 (2026-10-26)

[**COST 통합 제품 결정·개발 인계**](COST_PRODUCT_DECISIONS_AND_DEV_BACKLOG_20261026.md)를 읽고 현재 main·open PR과 비교한다. #120 사이드바 UI는 병합·런타임 확인 기록이 있으므로 재구현하지 않는다. #116/#118은 명세 병합, #119는 항공권 이름검색 코드 미병합, #117은 스크롤 코드 충돌, #108은 카드 API 중복/충돌 상태다. 우상단 수동 테마는 **설명 없는 해/초승달 아이콘 하나**만 제공한다. 명세/코드/테스트/배포는 서로 별개의 상태로 기록한다.

## 신규 사용자 승인: THEME-TOGGLE-01 (2026-10-26)

**READY / SPEC_ONLY / CODE_NOT_IMPLEMENTED.** [통합 UI 명세 v1.3 §13](card-all-transactions-and-ui-design-system-spec-v1.md)을 따라 모든 로그인 업무 화면 우상단에 **아이콘 하나**로 라이트(해) ↔ 다크(초승달)를 즉시 전환한다. 첫 방문은 시스템 테마, 사용자가 선택한 뒤엔 localStorage 한 키에 `light|dark`를 보존하고 다른 화면에서도 적용. **기존 '수동 테마 금지' 정책은 이 신규 승인으로 폐기**한다. 기본 V21 다크모드·메뉴 코드는 재구현하지 않는다. 합성 Chromium에서 dark 시스템 + light 선택, light 시스템 + dark 선택, 아이콘·접근성·선택 유지·모바일을 검증. 기존 금융/Google/DB 데이터 변경 금지. 우선순위 **P1 (새 승인 기능)**. 운영 배포·운영 브라우저 수락은 별도 게이트.

## 신규 승인: 항공권 예약 확인 (2026-10-26)

사용자가 기존 **'항공권 참가자 연결'**을 **'항공권 예약 확인'** 업무 보조 메뉴로 전환하도록 승인했다. [전용 명세](flight-booking-verification-spec-20261026.md)의 순서는 `FLIGHT-VERIFY-DATA-01` → `FLIGHT-VERIFY-API-01` + `FLIGHT-VERIFY-CARD-01` → `FLIGHT-VERIFY-UI-01`이다. **탑승객 이름 하나**로 검색하고 항공권 근거·검증된 카드 관계를 표시한다. 미연결 카드 후보는 검증된 예약일을 확인했을 때만 모든 당일 카드 원행을 보여준다. 예약일이 확인되지 않으면 임의 날짜 후보를 만들지 않는다. 기존 참가자 연결은 보조 기능으로 보존한다. **SPEC_ONLY / CODE_PENDING**.

## 1. PR 정리·기준선 (중복 개발 금지)

| 구분 | GitHub 확인 상태 | 실행 원칙 |
| --- | --- | --- |
| PR #103, #104, #109 | 병합됨. 공통 테마/카드 전체 내역/API/항공권·영수증 화면 원형이 `main`에 존재 | 기능 전체 재작성 금지; 미검증 UI·회귀만 표적 검사 |
| PR #111 | 병합됨. 개발 현황·인계 당시 기준 문서 | 이 문서와 인계 §0.14가 더 최신인 경우 우선 |
| PR #110 | 병합됨. [오제 수입·거래 대조 명세](trip-income-visibility-and-ledger-match-spec-20261025.md) | **명세만 완료, 코드 미구현** |
| PR #105 | 병합됨. [통합 UI 명세 §12](card-all-transactions-and-ui-design-system-spec-v1.md#12-지출-정리-화면의-전체-지출-자동-정리-버튼-개선-계약-2026-10-25-결정) | **명세만 완료, 코드 미구현** |
| PR #112 | 병합됨. [통합 UI 명세 §4.5~4.7](card-all-transactions-and-ui-design-system-spec-v1.md) | **명세만 완료, 코드 미구현** |
| PR #106 / #107 | 기존 항공권·영수증 초안, ahead 0(현재 main 조상)로 **중복 초안 종료**, 브랜치 삭제하지 않음 | 추가 병합/동일 코드 재구현 금지 |
| PR #108 | 아직 독자 커밋 존재, 최신 main과 충돌 | **HOLD**. `ledger_board.py` 및 거래 날짜 테스트 차이를 검토할 뿐, 전체 병합/복구로 최신 기능 되돌리지 않음 |

## 2. 안전한 구현 순서

작업 독립성과 금융 위험에 따라 다음 순서를 사용한다. 구현 담당이 다른 에이전트를 재귀 호출하는 것은 금지한다.

| 순번 | 티켓 | 입력 명세 | 실행·수락 핵심 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | `SIDEBAR-DARK-01` | 통합 UI §4.5/§4.7, SIDE-01~03 | `site_shell.py` 공통 root 색상 토큰으로 네이티브/standalone 메뉴에 시스템 테마 적용 | **CODED, DEPLOYED `4726412`, PASS. 2026-10-26 Chromium 합성 브라우저에서 시스템 light/dark computed style, 375/759/1280px 메뉴 노출, 모바일 키보드 열기·Escape·포커스 복귀 확인. 운영 화면 수락은 미검증** |
| 2 | `FLIGHT-SHELL-01` | 통합 UI §4.5/§4.7, FLIGHT-01~03·05~07 | `_page` 문서 구조와 실제 `Handler._send → wrap_document` 통합, 메뉴·본문·모바일 버튼 및 CSS 격리 | **CODED, DEPLOYED `4726412`; integration tests PASS; 운영 로그인 브라우저 미검증** |
| 3 | `FLIGHT-UX-COPY-01` | 통합 UI §4.6/§4.7, FLIGHT-04 | 제목·필드·상태 안내, 복수 후보/stale/취소·충돌/오류·저장 피드백 | **CODED, DEPLOYED `4726412`; targeted tests PASS; 운영 화면 전체 상태·반응형 미검증** |
| 4 | `EXPENSE-BULK-AUDIT-01` | 통합 UI §12 | 버튼·스크립트·POST 호출과 분류·자동 기장·기존 여행 귀속 및 owner/CSRF 경계를 소스에서 추적 | **READ_ONLY AUDIT COMPLETE; 보호된 유지관리 코드 DEPLOYED `4726412`; 운영 자료 동작 미검증** |
| 5 | `EXPENSE-BULK-UI-01` | 통합 UI §12 | 일반 지출 정리 화면에서 버튼/전용 JS 제거, 기존 건별 업무 유지. **서버 쓰기 경계 위험**이 존재하므로 유지보수 보호 계획 없이는 '안전한 전체 제거 완료' 주장 금지 | **CODED, DEPLOYED `4726412`; targeted tests PASS; legacy POST는 owner+CSRF 이후 410으로 변경 차단** |
| 6 | `EXPENSE-BULK-MAINT-01` | 통합 UI §12 | owner 전용 유지보수, 진짜 읽기 전용 dry-run, 변경 전 재검증·CSRF·멱등성·감사 기록; 운영 대량 재처리는 별도 승인 | **CODED, DEPLOYED `4726412`; synthetic targeted tests PASS: 별도 owner 화면·메모리 복제 dry-run·5분 일회용 preview·변경 지문 확인·명시적 적용 범위·중복 방지·감사 기록. Chromium 합성 UI 흐름에서 preview→확인 체크→apply, CSRF와 요청 범위 확인. 운영 데이터 미검증** |
| 7 | `OZE-INCOME-DIAG-01` | 오제 명세 §1.2 | `0630_오제` 메인 Google 장부 탭 ↔ COST `tab_id`, 선택 사본/수입행/수입·지출 검증/동기화 상태를 **허용된 운영 현장 읽기 전용**으로 대조, 실제 원인 하나로 단정하지 않음 | **PARTIAL / `DATA_AND_RENDER_PATH_VERIFIED` / `LIVE_BROWSER_VISIBILITY_VERIFIED (1375px)`: 2026-10-26 11:00 세대 Google 키 존재, COST 매핑 유일, 선택 사본 main(auto), fresh, identity blocker 없음. 수입 verified=True, 지출 verified=False, 전체 검증=False. 수입 35행·지출 30행, 수입 상세 합계 일치. `trip_income_html()`의 수입 패널·테이블 생성 성공. 기존 키 부재 진단은 PowerShell의 한글 인코딩 오류가 원인이며 [인계 §0.18](COST_V3_CURRENT_HANDOFF.md)에 최신 증거를 기록. 운영 로그인 브라우저에서 Google 수입 패널 open, 수입 35행, display/visibility 및 양수 크기를 확인했다(1375×1026). 이 인증 세션의 수입 표시는 확인됐으나 과거 사용자 표시 실패 원인은 ROOT_CAUSE_UNVERIFIED. 데이터 쓰기·동기화 없음** |
| 8 | `OZE-INCOME-VIEW-01` | 오제 명세 §1.3·§3 | 수입 블록과 지출 검증 분리, 전체 회계 경고 유지, Google 정본 읽기 전용 표기 | **CODED, DEPLOYED `4726412`; 17 targeted tests PASS; 운영 로그인 화면 1375px 수입 가시성 PASS; 다른 폭·200% 미검증** |
| 9 | `LEDGER-MATCH-READ-01` | 오제 명세 §2.1·§2.3 | 선택된 최신 Google 사본과 같은 여행의 웹 지출을 정확 비교하는 읽기 전용 후보 계산 | **CODED, DEPLOYED `4726412`; synthetic tests PASS** |
| 10 | `LEDGER-MATCH-UI-01` | 오제 명세 §2.2·§3 | 대응 웹 행 굵게 표시, 접근성 근거, 복수 후보 표시, stale 시 강조 해제 | **CODED, DEPLOYED `4726412`; desktop/mobile render tests PASS; 운영 로그인 브라우저 미검증** |
| 11 | `V21-UI-ACCEPTANCE-01` | 통합 UI §2~5·§9 | 이미 구현된 `/cards/all`, light/dark, 항공권·영수증에 대해 실제 브라우저 **375/759/1280px, 키보드, 200% 확대**와 변경 영향 구간만 표적 테스트 | **PARTIAL: `/cards/all` 실제 경로를 모사한 Chromium 합성 렌더에서 375/759/1280px 넘침 없음, light/dark 전환, 타일 Enter 열기·재입력 닫기, 200% 확대 후 세 거래 행/상세 링크 노출과 월 타일 초점 확인. 영수증은 375/759/1280px 넘침 없음, 테마 전환, 200% 확대에서 수정 저장 후 응답값 반영과 구글 7열 복사·클립보드 결과를 API stub으로 확인. 항공권은 375/390/759/760/1280px 넘침 없음, 테마 전환, 200% 확대에서 메뉴·제목·예약번호 입력란 초점, Enter 열기·Escape 닫기·초점 복귀 확인. 화면별 표적 검사 통과. `test_synthetic_preview` 통합 합성 흐름도 375px에서 카드 입력·장부 복사·영수증 수동 입력/수정/복사와 Google 수입의 COST 내부 기록 분리 표시까지 통과. 운영 브라우저 수락은 NOT_TESTED** |
| 12 | `CARD-PR108-RECONCILE` | 인계 §0.14 | 독자 커밋 및 `ledger_board.py`·날짜 테스트 확인. 최신 main 유지가 우선; 별도 가치 없으면 중복 상태 정리 | **READ_ONLY REVIEW: 최신 `origin/main` `6f6e4d1`과 PR #108 HEAD `326ea3b` 비교. 차이는 공백/빈 줄뿐이며 `git diff --ignore-all-space --ignore-blank-lines` 기준 실질 코드 차이 없음. 독자 동작 변경이 없으므로 PR은 열어 둔 채 HOLD, 강제 갱신·닫기·브랜치 삭제 안 함** |

| 13 | `OTA-SNAPSHOT-SCALE-01` | 인계 §0.18 | 512.4MB snapshot에서 이벤트별 후보 응답을 분리하고 후보 근거를 보존 | **CODED, DEPLOYED `36f6cb3`; targeted test 39/39 PASS; health/ready 200, unauthenticated OTA API 401. Authenticated OTA screen smoke NOT_RUN; `V21-UI-ACCEPTANCE-01` remains PARTIAL** |

## 3. 중요한 안전·정본 조건

- **실제 개발 ≠ 문서 PR 병합 ≠ 합성 테스트 PASS ≠ 운영 배포.** 각 상태 따로 기록.
- 합성 fixture만 코드 테스트에 사용. 고객 이름·예약번호·원본 금액을 GitHub PR/모델에 전달하지 않는다.
- `0630_오제`는 **2026년 회계 3분기 첫 여행**. 출발일 6월 30일을 기계적으로 2분기로 분류하지 않는다. 구글 스냅샷을 실제로 읽지 못했다면 `ROOT_CAUSE_UNVERIFIED` 기록.
- 볼드 후보는 **화면 시각적 후보**이지 실제 정본 일치·사용자 확정·중복 지출 제거·장부 이관의 권한이 아니다.
- 기존 여행 사용자 수동배정, 환불/취소/중복/보류·예약 정본·Google 직접 쓰기 금지 규칙 유지.
- 로컬 운영 DB/Google 실원본 쓰기, 운영 배포/마이그레이션/강제 branch 삭제는 사용자 별도 승인 전 금지.
- GitHub 열린/병합된 브랜치 기준은 **매 실행 새로 확인**. 코드 브랜치를 따로 나눠 관련 합성 테스트만 실행.

## 4. 상용 프론티어 감독 + 저비용 구현/검증

1. 감독은 `AGENTS.md`, 이 큐 및 **해당 티켓 상세 섹션만** 읽는다. 대규모 소스·로그·전체 명세 재독은 저비용 조사 에이전트에 위임한다.
2. Paseo 네이티브 Skill/위임이 실제 독립 실행을 지원하는지 1회 확인. **Skill 문서 읽기는 서브에이전트 실행 증거가 아님**. 기존 Anus CLI `anus/free` 실행 성공도 네이티브 Skill 성공의 증거가 아님. CLI 전환은 사용자 허가 필요.
3. 구현 담당은 **티켓 하나만** 변경하고 요약·diff·테스트 출력 경로 제출. 읽기 전용 독립 검증 에이전트가 SHA 고정 검증. 감독은 `PASS/REWORK/HOLD`만 결정한다.
4. 구현 재작업 티켓당 **최대 2회**, 무진전 2회 `HOLD`; 실행당 신규 구현 티켓 최대 **4개**, 하위 에이전트 호출 최대 **12회**. 토큰/비용 실측치 없으면 꾸며내지 않는다.
5. 파일·write scope 충돌 없는 경우에만 독립 worktree에서 최대 3개 저비용 에이전트 병렬 허용. 민감정보/코드 전체를 외부 에이전트에 무차별 전송하지 않는다.
6. 완료 보고 9개 항목: `TICKET, BASE_SHA, HEAD_SHA, FILES, TEST_COMMAND/RESULT, REVIEW_EVIDENCE, STATUS, PR, NEXT_READY`. 감독에게 로그 전문 자동 재전송 금지.

## 5. 실행 종료/다음 재개 계약

1. **첫 티켓 = `SIDEBAR-DARK-01`**, 이어 `FLIGHT-SHELL-01`. 이 둘을 최우선 P0로 처리한다.
2. 성공한 코드 커밋·작은 PR/표적 테스트/읽기 전용 독립 검증을 실제로 확인한다. 화면을 고쳤다고 임의 배포하지 않는다.
3. 처리된 티켓의 상태만 이 큐 또는 최신 인계 §0.14에 업데이트한다. 이전 운영 사건/재무 정본 문서의 장문 이력을 덮어쓰지 않는다.
4. 실행 상한에 도달하면 `NEXT_READY`와 차단 이유·필요한 권한만 기록하고 **즉시 종료**한다.
