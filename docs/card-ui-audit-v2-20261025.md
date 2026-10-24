# COST UI 감사표 v2 — COST-UI-AUDIT-001 (티켓 1/4)

> 상태: PR-0 문서 전용 (§6). 구현·브라우저 테스트 미수행. 소스 확인 1회만 수행. 기존 feature branch는 git show 비교 후 미검증 참고.
> 기준 SHA: b2a470b910d96caea29c255d6b76c619dbdb4a9e (base of docs/cost-ui-audit-v2-20261025)
> 현재 branch: docs/cost-ui-audit-v2-20261025 (base b2a470b; 이전 22 behind/6 unique; 현재 HEAD=69e46e8; 현재 origin/main..HEAD=1 ahead; origin/main..feat/card-all-transactions-ui-audit=13 ahead; 단순 push 금지; supervisor PR 승인, implementer push/PR 금지)
> 모델: Inkling Small Free (무료 제공)만 사용; 모델 전환/CLI 전환/재귀 위임 금지

## 1. 감사 기준 및 출처
- 명세: docs/card-all-transactions-and-ui-design-system-spec-v1.md §1, §4.3, §6
- 범위: 메뉴/URL/렌더/CSS/JS/권한/카드 원행 데이터 출처/상세 ID 경로 추적. 운영 자료 읽지 않음.
- 브라우저: NOT_TESTED (UI-VERIFY001 HOLD; 재시작 금지)
- 테스트/빌드/배포: 금지 (§5.3, AGENTS.md)

## 2. 소스 확인 (1회, 실제 경로)
| 항목 | 경로/함수 | 증거 |
|---|---|---|
| 메뉴/라우트 | webapp/card_flow.py:1996,2007 | grep 확인 (path /cards, /import) |
| 렌더/네비 | card_flow.py:419-423, 2945-2963 | inline nav/work_menu_html |
| 인라인 CSS | card_flow.py:3001 | inline style block 확인 |
| 인라인 JS | card_flow.py:3038,3055 | el(), innerHTML, rule-propose |
| 권한/접근 | webapp/access_control.py:56 (ROLE_OWNER 상수), 97 (partial unique index) | 권한 증거; 카드 row ID 아님 (주의: 상수 존재 ≠ 거래 ID) |
| 카드 원행 DB | webapp/ledger_store.py:273-276 (card_import_rows 테이블: row_id, bank_batch_id, bank_row_index), 1466/1472 (batch_id order), 3741 (import_row), 4465 (link_bank_source) | 실제 DB 스키마/함수 확인; 거래 안정 ID는 row_id + bank_batch_id + bank_row_index |
| 거래 ID (카드 원행) | card_flow.py: preview.rows.find(r=>r.transaction_id); ledger_store card_import_rows row_id | 거래 ID 증거; ROLE_OWNER는 해당 없음 |
| 상세/다음 행동 | webapp/card_actions.py | next_action() → href 재사용 (§1.4) |
| 공통 레이아웃 | ledger_design.py (work_menu_html 참조) | 참조 확인 |

## 3. feat/de2beb1 비교 (git show만, 미검증 참고)
- 브랜치: feat/card-all-transactions-ui-audit (de2beb1)
- 대상: docs/ui-audit-20261024.md, docs/design/cost-saas-ui-refresh.md (존재 확인)
- 사용: unverified reference; 이식/수정/테스트 금지. diff 로컬 보존, 감독 출력 제외.

## 4. UI 감사표 (§4.3) — 소스 확인 기준 / 브라우저 NOT_TESTED
| URL/메뉴/렌더 | 운영 | 공통 레이아웃 | 하드코딩 CSS | 일관성 | 표/배지 | 모바일/대비 | 라이트·다크 | 리스크 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| /cards (card_flow.py:1996/2007, nav 419, inline CSS 3001, JS 3038/3055) | 예 | 부분 | 예(inline) | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | CSRF/권한/DOM/금융write | P0 | SOURCE-VERIFIED(라우트/렌더) / BROWSER-NOT_TESTED |
| /import?batch=... (card_flow/card_actions next_action) | 예 | 부분 | 예 | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 금융write/리비전/권한 | P0 | SOURCE-VERIFIED(경로/함수) / BROWSER-NOT_TESTED |
| 카드 원행 조회 (ledger_store card_import_rows: row_id, bank_batch_id, bank_row_index) | 예(DB) | N/A | N/A | N/A | N/A | N/A | N/A | 중복·취소·환불·충돌 보존 | P1 | SOURCE-VERIFIED(ID 계약) / BROWSER-NA |
| 실제 owner 메뉴 목록 (확인 가능) | /cards, /import (card_flow); work_menu_html (ledger_design 참조); 권한: access_control ROLE_OWNER | - | - | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 권한/CSRF/금융write | P0~P1 | SOURCE-VERIFIED(메뉴/권한) / BROWSER-NOT_TESTED |
| 하위 페이지 전체 / PR0 전수 메뉴 누락 | 불명/미검증 | 불명 | 불명 | NOT_VERIFIED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 금융write/CSRF/외부호출 | P1~P2 | NOT_VERIFIED / NOT_TESTED / REFERENCE_ONLY |

## 4.1 실제 owner 메뉴 항목 (work_menu_html 기반, 최종 추가 8행)
| URL (메뉴 href 원문) | 핸들러/렌더 파일·함수 (line) | 공통/전용 CSS·JS | 읽기/쓰기/권한 경계 | source 검증 | 브라우저 | 다음 조치 |
|---|---|---|---|---|---|---|
| /board (work_menu_html line 1003, ledger_board allowed 1070, card_flow 421) | webapp/ledger_board.py (route /board, 렌더 HTML 67/797/1070/1407/1482 등) | ledger_design.py .work-menu / site-links (125/135/191/980~1021); 카드 인라인 CSS card_flow 3001 별도 | 읽기(주요) + 쓰기(탭/검색/수정 via /row 등); 권한: access_control ROLE_OWNER + allowed paths | SOURCE VERIFIED (함수/경로 1회 확인) | NOT_TESTED | P0: 공통 레이아웃/메뉴 일관성 + 표적 검증 |
| /import (work_menu_html 1004) | webapp/card_flow.py (path /import 1996), webapp/card_actions.py (next_action) | ledger_design site-links 공통; card_flow 인라인 JS/CSS 별도 | 쓰기(업로드/분류/규칙 제안); CSRF/revision 보호; 권한 owner | SOURCE VERIFIED | NOT_TESTED | P0: 권한/CSRF/금융 write 경로 재검증 |
| /ota (work_menu_html 1005) | webapp/card_flow.py / ota_payment_review / ota_reconcile_child 참고; ledger_board 1070 allowed | 공통 site-links | 읽기/쓰기(OTA 결제 검토/재대사); 외부 호출 금지 | SOURCE VERIFIED (경로 존재) | NOT_TESTED | P1: OTA 정확 연결/환불/중복 보호 확인 |
| /receipts (work_menu_html 1007) | webapp/ledger_board.py / receipt 관련(참조 확인) | 공통 site-links | 읽기(영수증 조회); 쓰기 제한 | SOURCE VERIFIED (메뉴 href 존재; 상세 렌더 미완료) | NOT_TESTED | P1: 상세 렌더/표면 확인 필요 |
| /trips (work_menu_html 1011) | webapp/card_flow.py (line 427; /trips 링크); ledger_board 1070 allowed | 공통 site-links | 읽기(여행 목록); 쓰기(이동/배정 via 사용자 확정) | SOURCE VERIFIED | NOT_TESTED | P1: 여행 배정/이동 경로 안정성 |
| /reserve-links (work_menu_html 1012) | webapp/ledger_board.py / reserve-links 참고 | 공통 site-links | 읽기/쓰기(링크 관리) | SOURCE VERIFIED (메뉴 존재; 상세 미검증) | NOT_TESTED | P2: 저빈도; 상세 렌더 확인 후 순차 |
| /flight-passengers (work_menu_html 1014) | webapp/flight_passenger_page.py | 공통 site-links | 읽기/쓰기(탑승자) | SOURCE VERIFIED (파일 존재) | NOT_TESTED | P1: 개인정보/권한 경계 확인 |
| /access/admin (work_menu_html 1017, ledger_board 458) | webapp/access_control.py (ROLE_OWNER 56, 97); ledger_board /access/admin 경로 | 공통 site-links | 관리자 쓰기/권한 변경; 인증/로그/캐시 | SOURCE VERIFIED | NOT_TESTED | P0: 권한/접근 제어 재검증 |
| /rules (work_menu_html 780 reference; ledger_board 1070 allowed) | webapp/card_flow.py (rule-propose/approve 3054), ledger_design 780 | 인라인(JS) + 공통 | 쓰기(규칙 제안/승인); AI/재분류 경로; CSRF | SOURCE VERIFIED | NOT_TESTED | P1: AI 제안/승인 안전성 |

> 추가 행 수: 9개 메뉴 항목 (/board, /import, /ota, /receipts, /trips, /reserve-links, /flight-passengers, /access/admin, /rules). /cards는 기존 §4 표에 별도 행 있음(중복 제외하여 실제 menu 항목 9개 추가). bank_batch_id는 카드 원행 DB 스키마 증거로만 사용; 거래 ID 증거는 card_flow transaction_id / ledger_store row_id 사용. 없음: /cards/all 별도 라우트 확인 미완료(§2.1 권장 경로는 실제 코드에서 /cards로 처리됨).

## 5. 후속 큐 (READY 최대 5, 기준선 기록)
READY (최대 3 새 후속 구현 티켓; 기존 완료/검증 HOLL 유지, 재시작 구분):
1. 공통 테마 토큰 최소 구축(PR-1 방향, 시스템 prefers-color-scheme) — 안전 의존성(기존 기능 깨지지 않음) 필수; NOT_TESTED 유지
2. 시스템 테마 영향 표적 검사(공통 CSS 변경 → 기존 핵심 페이지 표적 검증) — UI-VERIFY001 HOLL과 구별; 재시작 아님
3. 카드 전체 조회 구현(PR-2, 월 그리드/4논리열/정렬/상세 링크) — 기존 검증 HOLL(UI-VERIFY001)의 재시작과 구별; 안전 의존성 필수

(기존 P1~P2 하위 페이지, 데이터 계약, 권한 재사용은 HOLD/미검증 상태 유지; 새로운 일반화 규칙은 사용 승인 전 적용 금지)

HOLD (재시작 금지): UI-VERIFY001 (404 거절); feat/de2beb1 이식/수정.

## 6. 미확정/위험 (근거 기반)
- 브라우저 테스트 미수행 → PASS 금지; NOT_TESTED 유지 (§5.2, §5.3).
- 운영 DB/Google 쓰기 없음 → 코드/함수 증거만.
- PR100/102 완료 및 앞선 브랜치 정리 완료(재실행 금지).
- loop 원인 로그: 미확인(로그 없음, 재귀 위임 시도 없음).
- 배포·자동 병합: 금지. HEAD는 커밋 전(b2a470b 기준).

## 7. 실제 검사 명령/결과 (1회, 출력을 문서에 기록; 긴 로그는 로컬 보존, 감독 출력 제외)
- `ls outputs/card-ui-audit-v2-evidence-20261025.md`: exit=1 (존재하지 않음 → 잘못된 인용 삭제함)
- `git diff --check`: exit=0 → 문서 공백 검사 통과(기능 PASS 아님; 브라우저/구현 검증 아님)
- `git ls-tree -r --name-only de2beb1 | grep -E 'ui-audit|cost-saas-ui-refresh'`: docs/ui-audit-20261024.md, docs/design/cost-saas-ui-refresh.md 확인 → 정확 경로 사용; 미검증 참고 유지
- `git rev-parse HEAD`: 69e46e8 (이전 감사 커밋); 현재 HEAD는 이 커밋 참조(자기참조 문제 피함; base b2a470b 별도 기록)
- `python -c "import os; print('evidence=',os.path.exists('outputs/card-ui-audit-v2-evidence-20261025.md'))"`: evidence=False
- `git rev-list --count origin/main..HEAD`: 1; `origin/main..feat/card-all-transactions-ui-audit`: 13

## 8. 증거 경로 (로컬 보존, 감독 출력 제외)
- outputs/ (아래 새 증거 파일 없음; 명령 결과는 본 문서 §7에 기록)
- .local-archive/ (기존 보호, 변경 없음)
- git diff --cached --stat (2개 파일): audit + checkpoint (커밋 69e46e8)
- 기능 PASS/구현 완료: 없음 (NOT_TESTED 유지)
