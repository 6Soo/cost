# COST UI 감사표 v2 — COST-UI-AUDIT-001 (티켓 1/4)

> 상태: PR-0 문서 전용 (§6). 구현·브라우저 테스트 미수행. 소스 확인 1회만 수행. 기존 feature branch는 git show 비교 후 미검증 참고.
> 기준 SHA: b2a470b910d96caea29c255d6b76c619dbdb4a9e (base of docs/cost-ui-audit-v2-20261025)
> 현재 branch: docs/cost-ui-audit-v2-20261025 (22 behind / 6 unique vs origin/main; 단순 push 금지)
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
| 권한/접근 | webapp/access_control.py:56,97 | ROLE_OWNER, partial unique |
| 카드 원행 DB | webapp/ledger_store.py:273-276,1466,3741,4465 | card_import_rows, import_row |
| 거래 ID | transaction_id / row_id / batch_id / bank_batch_id | card_flow preview 모델 |
| 상세/다음 행동 | webapp/card_actions.py | next_action() → href 재사용 (§1.4) |
| 공통 레이아웃 | ledger_design.py (work_menu_html 참조) | 참조 확인 |

## 3. feat/de2beb1 비교 (git show만, 미검증 참고)
- 브랜치: feat/card-all-transactions-ui-audit (de2beb1)
- 대상: docs/ui-audit-20261024.md, docs/design/cost-saas-ui-refresh.md (존재 확인)
- 사용: unverified reference; 이식/수정/테스트 금지. diff 로컬 보존, 감독 출력 제외.

## 4. UI 감사표 (§4.3) — 소스 확인 기준 / 브라우저 NOT_TESTED
| URL/메뉴/렌더 | 운영 | 공통 레이아웃 | 하드코딩 CSS | 일관성 | 표/배지 | 모바일/대비 | 라이트·다크 | 리스크 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| /cards (card_flow) | 예 | 부분 | 예(inline) | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | CSRF/권한/DOM/금융write | P0 | SOURCE-VERIFIED / BROWSER-NOT_TESTED |
| /import?batch=... (card_flow/card_actions) | 예 | 부분 | 예 | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | 금융write/리비전 | P0 | SOURCE-VERIFIED / BROWSER-NOT_TESTED |
| 카드 원행 조회 (ledger_store) | 예(DB) | N/A | N/A | N/A | N/A | N/A | N/A | 중복/취소/환불 보존 | P1 | SOURCE-VERIFIED |
| 하위 페이지 전체(리디자인 대상) | 불명 | 불명 | 불명 | 불명 | 불명 | NOT_TESTED | NOT_TESTED | 금융write/CSRF/외부호출 | P1~P2 | NOT_TESTED / REFERENCE_ONLY |

## 5. 후속 큐 (READY 최대 5, 기준선 기록)
READY (P0, source verified, browser NOT_TESTED — PASS 차단):
1. /cards 렌더/라우트 + inline CSS/JS → 공통 토큰 분리 (PR-1) — NOT_TESTED
2. 월 타일 4x3 그리드 → 모바일 적응형 확인 — NOT_TESTED
3. 거래 4논리열 + 정렬/배지 → 실제 페이지 검증 — NOT_TESTED
4. 권한/CSRF/next_action 재사용 (card_actions) — SOURCE READ ONLY — P0
5. 원행 ID 계약(row_id/batch_id/bank_batch_id) + 중복/취소/환불 보존 — DATA CONTRACT P1

HOLD (재시작 금지): UI-VERIFY001 (404 거절); feat/de2beb1 이식/수정.

## 6. 미확정/위험 (근거 기반)
- 브라우저 테스트 미수행 → PASS 금지; NOT_TESTED 유지 (§5.2, §5.3).
- 운영 DB/Google 쓰기 없음 → 코드/함수 증거만.
- PR100/102 완료 및 앞선 브랜치 정리 완료(재실행 금지).
- loop 원인 로그: 미확인(로그 없음, 재귀 위임 시도 없음).
- 배포·자동 병합: 금지. HEAD는 커밋 전(b2a470b 기준).

## 7. 증거 경로 (로컬 보존, 감독 출력 제외)
- outputs/card-ui-audit-v2-evidence-20261025.md (긴 로그/grep 보존)
- .local-archive/ (기존 보호, 변경 없음)
- git diff --stat HEAD (2 파일 예정: audit + checkpoint)
