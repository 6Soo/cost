# COST 전면 리팩토링 마스터 명세 · 아키텍처/화면/개발 프로세스

> **사용자 지시:** 그때그때 붙인 기능으로 인해 생긴 구조적 비효율·중복·디자인 불일치를 저장소 전반에서 재정비한다. 에이전트는 이 문서를 구현 백로그·품질 게이트로 사용한다.
>
> **작성일:** 2026-10-27  
> **상태:** REPOSITORY_AUDIT_AND_SPEC_ONLY. 이 문서만으로 소스 리팩토링·테스트 통과·배포가 완료된 것은 아니다.  
> **검토 기준:** GitHub main 1deb4cbc4d431bafad0e366c9f31cf9defc0cfde의 전체 Git 트리 917개 파일(트리 누락 없음)을 파일/크기/경로 단위로 확인하고, 핵심 모듈과 설정 파일을 선별해 소스를 직접 확인했다. **917개 파일 각각의 함수와 실행 경로를 모두 동적 분석·테스트한 것은 아니다.** 식별된 구조적 증거와 추가 검증이 필요한 가설을 구분한다.  
> **중요 기존 문서:** [작업 지침](../../AGENTS.md), [진입점](../COST_V3_START_HERE.md), [현재 상태](../session_handoff.md), [운영 경계](../operations.md), [OTA 정책](ota.md), [금융 정책](finance.md), [UI 기존 계약](ui.md), [OTA 보류 대기열·성능 설계](ota-review-queue-performance-20261027.md).
>
> **전체 목표:** 제품 기능/원본/운영 제약을 유지하면서 레이어·상태·디자인·테스트·배포의 **소유권을 하나로 정리**한다. “전면 리팩토링”은 **저장소 전체 범위의 단계적 개선**을 뜻하며, 운영 DB와 배포판을 한 번에 갈아엎는 big-bang rewrite를 뜻하지 않는다.

---

> **전체 파일 인벤토리:** [917개 Git 추적 경로별 owner/후속 감사 분류](refactor-file-inventory-20261027.tsv). TSV의 PARTIAL_SOURCE_REVIEW 표기는 해당 기능 **영역에서 표본 코드 검토가 있었다는 뜻**으로, 그 행의 파일을 개별적으로 끝까지 읽거나 실행 검증했다는 뜻이 아니다. 전체 이슈 발견을 보장할 수 없으므로 RF-001 전수 호출·쓰기 경로 실사와 각 RF 항목의 후속 소스 감사를 필수로 한다.

## 0. 에이전트가 반드시 지킬 실행 지침

1. 이번 문서의 작업은 코드가 아니라 **실행 가능한 설계**다. 다음 에이전트는 최신 main, 미병합 PR, 운영 SHA를 먼저 재확인하고 실제와 다른 항목을 기록한 뒤 구현한다. 기준 브랜치가 달라졌다면 차이를 먼저 비교한다.
2. 사용자 최신 결정, AGENTS.md, 현재 상태와 운영 기록, 기능별 상세 정책을 우선한다. 과거 세션의 오래된 “READY/미구현” 표기를 실행 큐로 착각하지 않는다.
3. **한 PR은 하나의 변경 축/소유 모듈만 다룬다.** 동작 보존성 리팩토링과 새로운 정책 변경을 섞지 않는다. 공통 기반 PR → 이식 PR → 레거시 정리 PR로 분할한다. 기능도 함께 바뀌면 변경된 정책·회귀 근거를 별도 명시한다.
4. 작성자가 한 파일/DB/운영 자원의 단독 소유권을 갖는다. 다른 에이전트가 같은 파일을 동시에 수정하지 않는다. 기존 미추적 자료, 운영 DB, 복구 사본, stash, 사용자 교정을 보존한다.
5. 금융 원문·Google 장부·실제 환급·여행 배정에 대한 기존 안전 계약을 **경쟁적 자동화를 위해 완화하지 않는다**. 추론, 증빙 확인, 금융 확정, 실제 환급, 장부 기장, Google 반영은 각각 독립 상태다. 원승인번호 기반 1:N 환불과 수동 우선/원본 증빙 보호를 유지한다.
6. read-only 진단과 쓰기 작업을 분리한다. 고객 원문·개인정보·카드 끝자리·인증 토큰·비공개 원본을 보고서/Git/외부 모델에 복사하지 않는다. 이미 추적된 산출물을 임의 삭제하거나 Git 히스토리를 force rewrite하지 않는다.
7. 테스트·병합·배포·운영 실자료 수락은 별도 상태로 기록한다: SPEC_ONLY / CODE_WRITTEN / TEST_PASSED / MERGED / DEPLOYED / REAL_DATA_ACCEPTED.
8. 사용자에게 다른 메뉴로 이동해 처리하라고 전가하지 않는다. 단일 거래·예약의 핵심 판정, 근거, 충돌/재시도, 허용된 편집은 같은 컨텍스트에서 확인·실행하도록 설계한다.
9. 새 프레임워크·ORM·마이크로서비스·중복 데이터베이스 도입은 **필수 조건이 아니다**. 가장 작은 변경으로 기존 계약을 통일한다. 성능은 계측 후 개선한다.

## 1. 저장소 현황과 감사 범위

### 1.1 파일 트리 실측 (Git 추적 파일)

| 범위 | 파일 수 | 확인된 구조적 의미 |
| --- | ---: | --- |
| 전체 트리 | 917 | 소스·테스트·도구·문서·과거 출력·샘플/원본 데이터가 섞여 있음 |
| webapp | 274 | HTTP/UI/장부/접근 제어/운영 기능 및 테스트가 집중 |
| tools | 200 | 개발·진단·배포·검증용 목적별 스크립트가 다수 |
| tests | 98 | 독립 카드/OTA 파이프라인 회귀 테스트 |
| app | 59 | 분류, 대사, 금융, OTA 원본 수집, 참가자 도메인 |
| ledger | 75 | 도메인 구현 외에 data/에 스냅샷·CSV·XLSX 등이 공존 |
| outputs | 74 | 과거 리포트·Excel·JSON·SQLite 산출물이 Git 추적 중 |
| .paseo-session-migration-work-20260826 | 91 | 과거 세션 이관 자료·텍스트 전사 |
| docs | 18 | 2026-10-27 통합 문서 체계(시작, 현재, 운영, 기능별 specs, history) |

파일 수는 작성한 기능 수가 아니며, 중복 산출물·fixture·과거 기록을 포함한다. 특히 이미 추적 중인 산출물은 현재 .gitignore에 규칙이 있어도 제거되지 않는다.

### 1.2 직접 확인한 핵심 모듈의 크기와 결합 징후

| 경로 | 확인된 약 줄 수 | 현재 맡고 있는 책임 및 주요 위험 |
| --- | ---: | --- |
| webapp/ledger_store.py | 6,991 | SQLite 저장/스키마/리비전/감사 장부 등 170개 수준 정의. 변경 영향이 매우 넓음 |
| webapp/ledger_board.py | 5,722 | 페이지·HTTP·런타임/보드 조립, 아직 예전 synthetic 전용 설명 존재 |
| webapp/card_flow.py | 3,446 | 카드 분류·여행 귀속·OTA·지출 검토 UI·여러 SQL 및 캐시 |
| webapp/ledger_design.py | 2,657 | 화면 마크업·CSS·JS·실제 장부 화면 동작 혼합 |
| webapp/ops.py | 2,318 | 백업·복원·런타임/운영 점검·설정 및 자동화 |
| webapp/access_control.py | 2,258 | 권한, 인증, 직원 링크 등. 일부 docstring이 synthetic 시절을 설명 |
| webapp/ota_payment_review.py | 2,192 | OTA 백엔드/대사 projection, 격리 저장, HTTP dispatch, CSS/JS 렌더링 |
| app/ota_payments.py | 1,794 | OTA 파싱/매칭·그룹 배정·검증 결과를 소유 |
| webapp/migration.py | 1,227 | 마이그레이션/스냅샷 관련 흐름 |
| webapp/real_review_ui.py | 1,238 | UI 마크업/JS가 큰 템플릿으로 구성 |
| webapp/google_ledger_page.py | 1,067 | Google 정본 읽기 화면과 상호작용 |
| webapp/flight_passenger_page.py | 655 | 별도 상세 페이지에 독립 스타일·모바일 규칙 |

**확인 가능한 문제:** 여러 2천~7천 줄짜리 단일 모듈; 마크업과 스타일이 Python 문자열에 포함됨; 일부 설명이 실제 운영 범위를 반영하지 못함. **추가 입증이 필요한 가설:** 이 모듈 크기가 특정 응답 지연이나 금융 오매칭의 직접 원인인지, 어떤 내부 함수가 중복 구현인지, 일부 스크립트가 실제 완전히 미사용인지. 구현 전 콜그래프·실행계측으로 확정한다.

### 1.3 공통 UI/운영 문제의 직접 확인 근거

- webapp/site_shell.py, webapp/site_theme.py에 공통 헤더와 토글이 있으나 ledger_design.py, flight_passenger_page.py, real_review_ui.py, ota_payment_review.py 등에 별도 CSS가 존재한다.
- 화면별로 @media(max-width:550px), @media(max-width:600px), @media(width < 760px), @media(max-width:820px), @media(max-width:390px) 등을 사용한다. 같은 의미의 모바일 폭이 불일치한다.
- site_shell.py에도 여러 색상 코드가 있고, flight_passenger_page.py, ledger_design.py, ota_payment_review.py는 각각 수십 개의 하드코딩된 색상을 포함한다. 테마 토큰의 단일 소유권이 불명확하다.
- webapp/ui_icons.py는 별도 아이콘 렌더러를 제공한다. 새로 임의 Unicode 기호와 인라인 SVG를 혼용하기보다 승인된 공통 아이콘 API로 통일해야 한다.
- webapp/ota_payment_review.py에는 GET 전체 이벤트 공개 스냅샷·상세 후보 별도 조회가 공존한다. OTA 대기열 상세 최적화는 [별도 설계](ota-review-queue-performance-20261027.md)를 따른다.
- webapp/ota_payment_review.py::_transactions는 전체 카드 행을 SELECT *로 읽는다. 실제 CPU/메모리 비용은 측정이 필요하다.
- tools/select_targeted_tests.py와 config/test-impact-map.json은 변경 영향에 따른 표적 pytest 대상을 선택한다. 그러나 정의된 그룹은 카드 흐름, OTA, 항공권, 카드 수집, 테스트 선택 등에 한정된다. 새 파일의 테스트 영향 누락 방지가 필요하다.
- 저장소 트리에는 .github/workflows 경로가 보이지 않는다. GitHub Actions 자동 CI가 없다면 기존 Windows 호스트 검증 절차와 별도로 안전한 PR 게이트 설계가 필요하다. 다른 외부 CI가 없다고 단정하지 않는다.
- 루트 requirements.txt와 webapp/requirements.txt에 동일 런타임 의존을 중복 선언하며 이미 동일성 검사 계약이 있다. **통합 계획은 기존 동일성 검사를 먼저 보존**한다.
- config/pipeline_inventory.json은 current/legacy/candidate/external 스테이지와 예전 산출물 경로를 함께 보관한다. “candidate” 코드나 과거 산출물을 운영 실행 근거로 혼동하지 않게 관리한다.
- docs/handoff 아래는 일부만 추적되지만 tools/deploy_lightweight.py는 오래된 선택 스케줄 경로를 참조하는 구문이 있다. 실행 호스트에 파일이 존재할 수 있으므로 삭제/고장이라고 단정하지 말고 의존성 검증이 필요하다.

---

## 2. 목표 구조와 책임 경계 (기존 Python·SQLite 유지)

~~~text
webapp/routes / server adapters
  └─ session · auth · CSRF · validation · HTTP errors
webapp/pages + shared design system
  └─ semantic HTML · common CSS tokens/components · JS controllers
app/services (application use cases)
  └─ card import · classification · OTA reconciliation · trip assignment
     · refund evidence · expense readiness · reservation/flight search
app/domain (pure decisions + contracts)
  └─ card identity · booking identity · state enums · matching rules
app/infrastructure (adapters)
  └─ SQLite repositories · Gmail/OTA readers · Google readonly adapter
     · snapshots · file formats · audit & backup
ops/commands
  └─ one CLI registry · one deploy entrypoint · rollback, diagnostics
~~~

경계 계약:

- HTTP route는 응답·인증·입력검증만 소유하고 금융 분류 알고리즘을 복사하지 않는다.
- UI는 read projection을 소비한다. 화면에서 서로 다른 “자동 매칭/완료” 기준을 새로 결정하지 않는다.
- 도메인 순수 함수는 DB 커넥션·HTML·global cache에 의존하지 않는다.
- 사용자 확정/회계/여행 이동 write는 기존 ledger_store + 승인된 단일 감사 write path가 우선이며, 새 저장소로 복제하지 않는다.
- 읽기 조회에서는 승인 데이터에 부작용을 발생시키지 않는다. background reconcile과 GET 경계를 분리한다.
- 모든 외부 원본은 lineage, source digest, freshness, derivation을 가진 읽기 전용 입력이다.
- 공통 UI는 계층별 중복 wrapper 없이 단일 shell에서 구성한다.
- 코드 추출 후에도 기존 API URL, HTML 폼 필드, DOM id/data attribute, 저장 JSON 계약, 승인·수정 기록을 회귀 테스트로 보존한다.

디렉터리는 **제안 구조**다. 사용처가 많은 파일을 첫 PR에서 물리적으로 모두 이동시키지 않는다. 우선 현재 파일 안에서 순수 함수를 추출하고 작은 adapter를 두어 기존 import path를 유지하며 단계적으로 이관한다.

---

## 3. 구현 백로그: 에이전트별 수락 가능한 작업 단위

각 항목의 ID를 PR 제목/본문, 테스트 및 현재 상태 문서에 사용한다. 작업은 우선순위와 의존성을 따라 진행하며, 같은 파일을 동시에 수정하지 않는다.

### P0: 안전성·기준선·운영 불변조건

**RF-001 전체 동작 기준선 및 호출 지도**
- 대상: run_candidate.py, webapp/ledger_board.py, webapp/ledger_store.py, webapp/card_flow.py, webapp/ota_payment_review.py, webapp/ops.py, app/, ledger/domain/.
- 작업: 화면/HTTP endpoint/백그라운드 worker/DB writer/일괄 import/외부 연동의 엔트리포인트를 자동 검색해 “Route → Service → Repository → Table → External effect” 매핑 작성. 모든 쓰기 함수와 audit sink를 추출. 실제 실행 기능, shadow, synthetic, dead code 후보 구분.
- 산출물: 코드에서 자동 추출 가능한 module ownership map, endpoint inventory, write-path inventory, 주기 작업·배포 의존성 그래프.
- 합격: 대표 카드 저장, OTA 미리보기/확정, 여행 이동, 환불, 로그인, Google 읽기 등 모든 쓰기 경로가 한 소유자와 권한 체크를 가진다. 미확인 부분은 TODO가 아닌 OPEN_QUESTION과 재현 명령을 기록한다.

**RF-002 금융·여행 상태 계약 고정**
- 대상: app/db.py, app/classify.py, app/reconciliation.py, app/partial_refund.py, app/ota_payments.py, app/ota_inference.py, app/ota_exact.py, webapp/ledger_store.py, webapp/card_flow.py, docs/specs/finance.md, docs/specs/ota.md.
- 작업: 거래 방향·승인번호/원승인번호·매입 여부·중복·보류·1:N 환불, OTA 매칭, 여행 추론, 비용 준비, Google 정본을 독립 typed DTO/state로 고정. 기존 필드/값과 직렬화 변환기를 정의하고 실행 경로의 중복 판정 발견 시 코어에 수렴.
- 필수 회귀: 1:N 부분환불, 초과 환불 HOLD, 중복 원결제, 환불 추론과 실제 환급 분리, 높은 추론이지만 여행 ID 없음, 사용자 교정 후 재수집, 취소/예약 변경, 다른 공급자·카드 점유, 시차·통화 불일치, Google 무단 쓰기 없음.
- 합격: 카드/OTA/여행/장부 UI가 동일한 상태 ID와 reason code를 표현한다. 재처리 전후 원본 금액·통화·ID 불변. 기존 승인된 자동화가 조용히 보류로 후퇴하지 않는다.

**RF-003 데이터·산출물·개인정보 보존 감사**
- 대상: ledger/data/, outputs/, .paseo-session-migration-work-20260826/, docs/history/, .gitignore, tools/ 등.
- 확인: outputs/ 아래 수십 MB SQLite 2개, 여러 JSON/XLSX, ledger/data의 여러 snapshot/index, 과거 세션 transcript 등 현재 Git 추적 파일이 존재한다. 개인/금융 정보가 들어 있는지는 **내용을 외부로 출력하지 않는 격리된 로컬 점검**으로만 판단한다.
- 작업: tracked-data inventory (경로/크기/민감도 미판정/프로듀서/소비자/활성 여부/보관 정책)를 생성. 새 민감 산출물 커밋 차단 preflight 작성. 기존 내용의 삭제·Git 역사 재작성은 사용자 별도 승인과 복구 계획 없이는 금지. 재현 가능한 합성 fixture와 운영 DB를 구조적으로 분리.
- 합격: 현재 추적 자료의 처리 방안이 분류됨. 운영 필수 파일을 잘못 지우지 않고 배포 패키지에는 허가되지 않은 원본/출력물이 포함되지 않는다. 민감정보를 보고서에 포함하지 않는다.

**RF-004 테스트 게이트·품질 기준선**
- 대상: pytest.ini, config/test-impact-map.json, tools/select_targeted_tests.py, webapp/tests, tests/card_pipeline, tools/ 테스트.
- 작업: Python 버전, test collection, known flaky/failing, OS 의존, 실제 DB 필요 여부를 구분한 기준선 실행. 단위/계약/통합/브라우저/운영 스모크 그룹 선언. 테스트 영향 매핑에 모든 활성 핵심 모듈을 연결하고 매칭 불가 파일은 안전한 최소 회귀 묶음을 선택한다.
- 합격: PR 변경 파일과 대응 테스트가 자동 산출되고, 실패한 테스트는 신규/기존을 구별한다. “pytest를 못 돌렸는데 PASS”로 보고하는 경로가 없다.

**RF-005 릴리스·백업·되돌리기 계약**
- 대상: webapp/ops.py, run_candidate.py, tools/deploy_*.py, tools/*deployment*.ps1, docs/operations.md.
- 작업: 현 Windows SHA 고정 배포를 유지하고 중복 배포 스크립트를 감사. 절차를 단일 entrypoint + 안전한 하위 명령으로 합치며 preview/preflight/backup/stop writers/deploy/health/auth/DB hash/rollback을 단계로 분리.
- 합격: 기존 검증 복구 사본 보존, 프로세스 SHA·작업 스케줄러·리스너 일치, /healthz·/readyz 200, 비인증 보호 API 401, 보호 DB/테이블 내용·스키마 변조 없음. 문서만 병합할 때 불필요한 앱 재배포를 하지 않는다.
- 주의: 실제 배포·운영 파일 쓰기는 승인된 운영 접근과 기존 권한을 필요로 한다.

### P1: 응용 계층 / 백엔드 책임 분리

**RF-101 ledger_store 분해 (고위험, 가장 먼저 계약 테스트)**
- 대상: webapp/ledger_store.py (약 6,991줄), webapp/operator_ledger.py, webapp/ledger_apply.py, webapp/ledger_board.py.
- 작업: LedgerStore 공개 인터페이스와 사용처부터 추적한다. schema/migrations, row read projections, validated write commands, revision/idempotency, audit append/replay, manual overrides, trip data, import reconciliation을 별도 파일로 추출하고 façade를 유지한다.
- 합격: 공개 import/SQL 스키마/write 순서, revision, idempotency key, append-only audit, ledger-pending 재시도, 사용자 확정 precedence가 전후 동등. “모듈 줄 수 감소”만으로 완료 금지.

**RF-102 ledger_board/HTTP 런타임 분해**
- 대상: webapp/ledger_board.py (약 5,722줄), run_candidate.py, webapp/server.py.
- 작업: route table, handlers, session/auth middleware, HTML rendering, read projection, background jobs, lifecycle/locks를 파일·객체별로 분리. 기존 경로를 adapter로 유지. 실제 동작과 다른 synthetic-only docstring은 검증된 사실로 고친다.
- 합격: 동일 HTTP 상태·권한·CSRF·세션 만료·에러 응답, 로그인 후 동일 URL/폼 동작, thread safety, 단일 운영 listener 유지.

**RF-103 카드 분류·여행 귀속·지출 UI 분리**
- 대상: webapp/card_flow.py (약 3,446줄), app/classify.py, app/reconciliation.py, webapp/review_context.py, webapp/expense_bulk_maintenance.py.
- 작업: 카드 입력, 여행 authority/period, 카드 분류, OTA evidence projection, refund state, review decisions, expense readiness, HTML UI, background refresh를 서로 분리. 규칙/권한은 서비스 레이어에, 렌더러는 허용된 DTO만 사용.
- 합격: 동일 입력 원본·사용자 교정에서 카드/여행/장부 판단 전후 일치. 별도 메뉴에 가야 확인되는 OTA 근거는 같은 카드 상세에서 읽기 전용 표시. 읽기 경로의 불필요한 전체 OTA 계산 없음.

**RF-104 OTA 단일 대사 코어·후보 trace 수렴**
- 대상: app/ota_payments.py, app/ota_inference.py, app/ota_exact.py, app/ota_review.py, app/reconcile/*, webapp/ota_payment_review.py, webapp/ota_snapshot.py.
- 작업: 이벤트 추출, candidate trace, matcher/solver, 사용자 pin, review projection, snapshot, UI 액션을 구분하고 일관된 result/reason DTO를 사용. 여러 병렬 solver가 서로 다른 ‘매칭 완료’ 결과를 내지 않도록 검증. 기존 고정/수동 관계를 유지한다.
- 세부 구현 계약: [OTA 보류 큐·페이지네이션·예약 그룹화·증분 대사](ota-review-queue-performance-20261027.md)를 별도 스토리로 수행한다. 기존 접힘/지연 조회는 재구현하지 않는다.
- 합격: 같은 스냅샷 세대에서는 OTA 목록, 카드 상세, 비용 준비, 예약 상세가 동일 링크·근거를 참조. 전체 대사 전후 보류/해결 상태가 해석 가능한 diff로 제공된다.

**RF-105 카드 취소/환불 매칭 단일화**
- 대상: app/partial_refund.py, webapp/card_flow.py, webapp/refund_tab.py, config/refund-pairing.json, tests/card_pipeline/test_kakao_amount_inferred.py.
- 작업: 번호 기반 확정 1:N, 외화 정밀 기준, 승인된 카카오 별칭·동액 추론 경로를 명시적으로 구별. UI 목록·detail·캐시·원결제 그룹·기장 준비가 동일 판정 서비스를 쓰도록 한다.
- 중요 현재 미결: 2026-10-27 점검 시 PR #193 ‘카카오 금액 추론 복구’가 열려 있었고 운영 반영/테스트 증거는 없었다. **PR #193를 사전 검증 없이 이 문서 PR에 섞어 병합하지 않는다.** 최신 상태 재확인 후 RF-105와 충돌·중복을 해결한다.
- 합격: 캐시/비캐시·전체 목록/단일 카드·원결제/환불 각각 동일한 연결 결과, 허위 환급 완료 표시 0건, 실제 운영 원행 변경 없음.

**RF-106 예약·항공권 근거 공통화**
- 대상: app/flight_evidence.py, app/booking_evidence.py, app/reservation_authority.py, app/flight_passenger_matching.py, webapp/flight_passenger_page.py, webapp/flight_booking_index.py.
- 작업: 공급자별 예약번호/이름/여정/최초 메일 수신일·타임존 DTO; 중복·변경 메일 계보; 검색과 UI의 동일 예약 키 사용.
- 합격: 인증된 원본 내 최초 수신일과 예약 명시일의 우선순위, 왕복 2편, 취소·변경, 이름 구성요소 검색, 개인정보 접근 제어 유지.

**RF-107 Google·외부 소스 adapter 계층**
- 대상: app/google_authority.py, webapp/google_ledger_page.py, webapp/live_sync.py, webapp/provider_transport.py, webapp/provider_config.py, app/ota_mail.py, app/ota_portal.py, apps-script/.
- 작업: 외부 서비스 인터페이스, timeout/retry/backoff, source digest/lineage/freshness, 오류 코드, last-good snapshot을 표준화. Google 읽기와 운영자가 수행하는 수동 B:H 붙여넣기를 구분.
- 합격: 외부 원본 오류가 ‘매칭 완료’나 ‘여행 삭제’로 바뀌지 않음; 재시도·중복 수집 시 데이터 멱등성; Google 자동 쓰기 금지 유지.

**RF-108 DB 스키마·마이그레이션 및 성능**
- 대상: webapp/ledger_store.py, webapp/migration.py, app/db.py, webapp/db_merge.py, webapp/ota_snapshot.py, webapp/card_transactions.py.
- 작업: 활성 DB·테이블과 source of truth를 목록화. schema version, additive migration, 백업/복구, SQLite 인덱스, transaction/lock 범위, 대사 snapshot invalidation을 통일. 전체 SELECT·반복 N+1 조회는 측정 후 최적화.
- 합격: rollback 가능한 additive schema, 읽기 전용 shadow diff, 실제 쿼리 계획 전후 측정, P95 및 메모리 비교. 금전 정보가 바뀌는 데이터 마이그레이션 금지.

**RF-109 도구/작업 스크립트 카탈로그**
- 대상: tools/ 200개, config/pipeline_inventory.json, 구형 루트 fix_r55.py·fix_r57.py·migrate_safe.py.
- 작업: 모든 스크립트를 ACTIVE_SAFE_READ / ACTIVE_WRITE_GUARDED / TEST_FIXTURE / HISTORICAL / UNKNOWN으로 분류하고 entrypoint·입력·출력·부작용·실제 운영 의존성을 기록. 중복 check_ota*, check_mail*, deploy*, verify* 등은 공통 CLI의 독립 하위 명령으로 수렴.
- 합격: 운영에서 호출되는 스크립트의 실행 경로·인자 계약과 회귀 테스트 확인. 과거 실행 증거와 사용되지 않는 파일도 임의 삭제하지 않음. 문서/코드 참조 수가 0이고 복원 방법이 확보된 뒤 별도 승인으로 정리.

### P1: 전면 UI·UX 디자인 시스템 구축

**RF-201 디자인 토큰 단일화**

새 프론트엔드 프레임워크 없이 기존 server-rendered HTML을 유지하면서 공통 스타일 계층을 만든다.

제안 구조:
- webapp/static/css/tokens.css — 브랜드/상태/배경/표면/텍스트/테두리/spacing/typography/radius/shadow/z-index/모션 토큰
- webapp/static/css/base.css — reset, semantic typography, input/button 기본, focus-visible
- webapp/static/css/layout.css — single app shell, navbar/sidebar, content widths, sticky header, mobile spacing
- webapp/static/css/components.css — 버튼, 배지, 카드, field, select, modal, tabs, accordion, empty/loading/error, toast, table
- webapp/static/css/pages/*.css — 공통 토큰에서 정말 페이지별로 필요한 예외만

**상태 색상은 의미로 결정**한다: neutral, info, success, warning, danger, inferred/uncertain. 예: MATCHED 확정과 INFERRED 추론은 동일 초록색으로 표시하지 않는다. 검증 없는 결제/환급을 ‘완료’ 색상으로 표시하지 않는다.

**토큰 계약 초안(최종 수치는 디자인 QA에서 고정):**
- 간격: 4/8/12/16/24/32px 리듬
- 필드·버튼 최소 높이: 모바일 44px
- 테두리 반경: small/medium/large 8/12/16px 계층
- 헤더 높이, 사이드바 폭, 콘텐츠 max-width, 카드 간격을 공통 토큰으로 관리
- 글자 크기: 캡션/보조/본문/소제목/제목으로 계층을 줄임; browser zoom 200%를 가정
- light/dark는 공통 CSS 변수 전환만 허용하고 각 화면에서 새 테마 엔진을 만들지 않음
- 상태 아이콘은 webapp/ui_icons.py가 승인한 SVG 이름을 사용하고 aria-label/role·포커스·스크린리더 문구를 유지
- 통화·날짜·시각대 포맷은 화면마다 직접 문자열을 조립하지 않고 공통 표시 유틸리티 사용
- 인라인 스타일, 페이지별 하드코딩 hex, 무제한 !important 누적 금지; 예외는 사유와 TODO 포함

**RF-202 앱 셸·메뉴·테마 통합**
- 대상: webapp/site_shell.py, site_theme.py, ledger_design.py, ledger_board.py, flight_passenger_page.py, google_ledger_page.py.
- 작업: 상단 메뉴·테마 토글·화면 제목·breadcrumb·알림·반응형 컨테이너의 DOM은 단일 조립 지점이 책임진다. 이미 DOM에 있는 토글을 페이지별로 복제/별도 행에 삽입하지 않는다.
- 합격: iPhone Safari/Chromium Android/desktop, 320/375/390/600/760/1024/1440px, 200% zoom에서 버튼 겹침·가로 스크롤·sticky 헤더 잘림 없음. 메뉴/테마 전환 유지.

**RF-203 폼·지출 검토 컴포넌트 통일**
- 대상: card_flow.py, ledger_design.py, real_review_ui.py, receipt_review.py, review_guidance_ui.py, cards_all.py.
- 작업: 비용 항목, 여행 배정, 내용, 수정 이유, 반복 규칙, 저장 버튼을 일관된 label/help/validation/disabled/dirty 상태로 만든다. 자동 배정이 가능한 근거가 있으면 결과를 같은 카드에 표시하고 다른 화면으로 이동시키지 않는다.
- 합격: 승인된 입력값·저장 API·revision 경쟁 제어 유지. dropdown이 텍스트 없이 비어 보이지 않고 오류 메시지는 해당 field에 연결. 저장 중 중복 클릭과 성공/실패 UI 구분.

**RF-204 OTA·환불·항공권 정보 구조 통일**
- 대상: ota_payment_review.py, card_flow.py, flight_passenger_page.py, guide_airfare_review.py.
- 작업: 공통 ‘예약 요약 → 상태/근거 → 결제/취소/환불 → 카드 후보 → 여행 귀속’ 정보 계층을 적용한다. OTA는 기본 20건 페이지 + 예약 그룹, 상세는 인라인. 승인번호와 환불 근거를 혼동하지 않는다. 항공권은 가는/오는편 카드와 예약 근거의 동일한 정보 밀도 유지.
- 합격: 접힘이 스크롤만 숨기지 않고 실제 초기 조회/DOM 비용을 줄임. 한 카드의 대사 상태와 환불 상쇄/여행 귀속 배지가 서로 모순되지 않음.

**RF-205 UI 시각 회귀·접근성 자동화**
- 대상: 기존 webapp/tests/*_browser.py와 CSS/컴포넌트 테스트.
- 작업: 공통 스크린샷 골든, light/dark, small viewport, text zoom, 긴 상호/예약번호, 선택·로딩·stale·권한 실패를 테스트. contrast, focus order, accessible name, keyboard-only, reduced-motion을 검사.
- 합격: 디자인 토큰을 바꾸면 전체 핵심 화면이 비교되고, 시각 변화는 승인된 골든 업데이트 기록을 요구한다. 스크린샷 차이만으로 금융 동작 회귀 통과를 대체하지 않는다.

### P2: 생산성·관측·지속 가능한 개발

**RF-301 환경/설정·의존성 정리**
- 루트와 webapp requirements 중복은 단일 근거에서 생성/검증하되 기존 배포·동일성 테스트와 호환.
- .env.example, data-root, Windows/로컬 synthetic, 원본 경로·권한, feature flag 및 API 비밀값의 역할 분리.
- 비밀값은 코드/Docs/테스트 fixture가 아닌 runtime secret 경로에만 존재해야 한다.

**RF-302 구조화된 관측·성능**
- request_id, snapshot_generation, rule_version, data fingerprint, elapsed 단계별 지표를 공통 계측.
- 금융 원문/PII는 로그 금지; 이유 코드와 익명 건수·지연만 남김.
- OTA snapshot 계산, 지출 정리 첫 렌더, 카드 검색, Google 정본 조회, DB 대기 lock의 p50/p95, payload bytes, peak memory를 측정.

**RF-303 테스트·CI·코드 품질 자동 게이트**
- GitHub 연결에서 자동 CI를 확인할 수 없다면 신규 PR 게이트를 설계: import/compile, pytest unit/contract, targeted+full nightly, type/lint 단계적 도입, dependency/security review, secret/data tracking guard.
- Windows 경로/브라우저/운영 DB 필요한 테스트는 별도 runner나 승인된 호스트에서 실행하고, CI PASS를 운영 검증으로 오인하지 않음.
- 타입·lint는 기존 900+ 파일 전체에 일괄 적용하지 않고 새/수정 코드 우선 적용 후 점진 확대.

**RF-304 문서·작업 인계 축소**
- 현재 docs/COST_V3_START_HERE.md → docs/session_handoff.md → docs/operations.md → 주제별 specs 단일 진입점 유지.
- 디자인/아키텍처 의사결정은 짧은 ADR로 남기고, 세션마다 별도 “미결 전체 복제본”을 만들지 않는다.
- PR에서 user requirement, code location, failure reproduction, exact tests, deployed SHA, real-data acceptance를 별도 필드로 남긴다. “문구만 변경”을 기능 완료로 보고하지 않는다.

---

## 4. 단계적 실행 순서 (작업 오케스트레이션)

| 단계 | 선행 조건 | 구현 묶음 | 잠금/주의점 | 단계 종료 게이트 |
| --- | --- | --- | --- | --- |
| R0 | 최신 main/운영 SHA 확인 | RF-001, RF-003, RF-004의 **읽기 전용 실사** | 개인정보/DB/산출물 비변경 | endpoint/write-path inventory, 테스트 기준선, 보존 범위 |
| R1 | R0 | RF-002: 도메인 상태/DTO·golden tests | 금융/여행 원본과 Google 불변 | 기존 입출력 동등, 모호성 정책 회귀 |
| R2 | R1 | RF-201/202: shell, tokens, 공통 UI 기반 | 상단 메뉴·테마·기존 URL/DOM 보존 | 모바일/200%/light-dark 시각·상호작용 |
| R3 | R1 | RF-101/102: 저장·HTTP 런타임 분리 | SQLite writer 및 audit 경계 단독 소유 | write replay·revision·idempotency·API 회귀 |
| R4 | R1, R3 | RF-103/104/105/106/107: 기능별 순차 분리 | OTA/카드/여행 정책을 한 PR에서 동시에 변경 금지 | 기능별 synthetic + real read-only shadow equivalence |
| R5 | R2, R4 | RF-203/204/205 + OTA 예외 대기열 | UI/금융 작업을 기능 단위로 조정 | 20건 목록/인라인 상세/중복 없는 카드, E2E |
| R6 | R3, R4 | RF-108/302: DB/성능 병목 최적화 | migration backup + rollback | p95/SQL plan/financial hashes |
| R7 | R0~R6 | RF-005/109/301/303/304: 도구·CI·운영/문서 수렴 | 오래된 script·artifact 무단 삭제 금지 | 반복 가능한 release + 테스트 영향도 |
| R8 | 각 단계 | 운영 SHA 고정 배포와 실제 화면 수락 | 데이터 변경 권한 명확화 | health/auth + DB 보호 + 실제 모바일/예약/환불 수락 |

개발 병렬화 원칙: RF-201 UI tokens와 RF-001 읽기 전용 지도 작성처럼 파일 소유권이 겹치지 않는 작업은 병렬 진행 가능. ledger_store/card_flow/ledger_board/ota_payment_review를 2개 에이전트가 동시에 고치는 것은 금지. R3와 R4의 실제 merge는 직렬화한다.

## 5. 컴포넌트·API·DB의 변경 방침

### 5.1 UI 계약

- 공통 server-rendered HTML은 명시적 label, unique id, aria attributes, esc 처리, 키보드 작동을 포함한다.
- 동적 사용자/원본 문자열은 HTML escape 또는 textContent로 처리하고, trusted template fragment만 HTML로 주입한다.
- 공통 JS controller는 DOM 이벤트 바인딩과 화면 상태를 소유하고, 금전 판단·사용자 권한은 서버가 확정한다.
- 페이지별 CSS를 제거할 때 기존 data-*와 폼 이름을 테스트로 보호한다.
- 내비게이션은 한 번만 생성하며 테마 버튼도 하나만 존재해야 한다.

### 5.2 서비스·저장 계약

- 모든 저장 요청은 actor, permission, revision, idempotency key, before/after, source_id, audit_event를 갖고 검증된다.
- 레거시 SQL은 typed repository method로 감싸고 SQL semantics가 바뀌지 않도록 golden query comparison을 수행한다.
- background worker가 제공하는 snapshot version을 read-only UI가 사용한다. stale/refreshing/error를 빈 결과 또는 완료로 오인하지 않는다.
- 자동 여행 배정은 기존 유효 여행 authority를 사용한다. 카드 금융 적격이면 OTA 예약 미확정만을 이유로 비용 준비를 막지 않는다. 사용자의 직접 여행 A→B 이동은 자동 분류보다 우선한다.
- 원결제 1:N은 취소/환불 개별 금액을 유지하고 gross/refunds_total/net을 파생한다.
- Google 수입·이체는 읽기 전용이다. 카드·영수증은 COST 내부 승인 흐름 후 사용자가 Google에 붙여넣는다.

### 5.3 스키마·배포 계약

- DB schema change는 additive/버전 명시/rollback plan/backup 확인 후 적용한다.
- SQLite 트랜잭션 경계와 board audit append/replay 순서는 변경 전후 동등해야 한다.
- 저장된 source digest와 user confirmation을 코드 리팩토링 이유로 무효화하지 않는다.
- 운영 환경과 synthetic/local 환경의 데이터 루트·인증을 분리한다.
- 배포 후 실제 프로세스 SHA를 확인하지 않은 ‘배포 완료’ 주장은 금지한다.

## 6. PR 템플릿 · 에이전트 실무 계약

~~~text
Refactor-ID:
Base main SHA / target files / one writer:
Problem / evidence (file, function, reproducible case):
No-change contracts (finance, trip, Google, API, UI, data):
Proposed change and explicit non-goals:
Affected routes / DB tables / snapshots / CSS components:
Synthetic tests added:
Targeted tests actually executed (command, counts):
Existing failures compared against unchanged base:
Browser+200%+dark/light proof:
Read-only real-data shadow results (if accessible):
Migration / rollback / backup / deployment plan:
Result: CODE_WRITTEN | TEST_PASSED | MERGED | DEPLOYED | REAL_DATA_ACCEPTED
Open blockers / next exact command:
~~~

PR이 테스트와 실측 없이 CODE_WRITTEN까지만 도달하면 다음 에이전트가 검증 단계부터 이어받는다. 새로운 문서를 만들거나 동일 기능을 다시 쓰지 않는다.

## 7. 공통 품질 게이트와 수락 기준

**G0 문서/동작 비교:** 최신 사용 계약, 호출 지도, API/DB 변경 영향, 복구 가능성 확인.

**G1 금융 안전:** 전체 금액/부호/승인번호/원승인번호/통화/원본 ID가 동일; 사용자 확정·1:N 환불·초과환불 HOLD·Google 수입 읽기 전용이 유지됨.

**G2 인증/동시성:** 비로그인·비owner·CSRF·stale preview/revision·double-submit·idempotency·multi-thread 접근 보호.

**G3 프론트:** 320/375/390/600/760/1024/1440px, 200% zoom, light/dark, focus-visible, 오류/빈 값/로딩/긴 텍스트, reduced motion.

**G4 성능:** 대사/렌더/DB를 분리해 baseline p50/p95, payload, memory, query plan 측정. 개선 목표는 사용자 화면과 실제 서버 측 병목이 각각 검증될 때 통과.

**G5 운영:** 정식 SHA 고정, 통합된 보호 데이터 해시, 단일 listener, health/ready 200·보호 API 401, rollback point, 실제 기능별 smoke.

**G6 회귀/인수:** 사용자 기존 문제 (카카오 환불 자동 매칭, Agoda 625,280원 표시와 여행 상태, Agoda 결제일 미상, 높은 추론의 자동 여행 배정, 파라타항공 취소, 항공권 모바일 UI, 불필요한 Google 복사 버튼, OTA 과다 목록)가 해결됐다고 주장하려면 해당 **실제 사례의 읽기 전용 근거 및 사용자의 권한 내 수락 증거**가 따로 필요하다. 리팩토링 코드 병합은 이 문제들의 해결을 자동으로 의미하지 않는다.

## 8. 남겨 둘 결정·검증 질문

1. 어떤 기존 페이지가 여전히 예전 독립 shell을 사용하는가? 실제 route → renderer 지도를 완성할 것.
2. 카드/OTA/여행 상태를 중복 판정하는 함수들이 어디에서 서로 다른 결과를 내는가? 동일 입력 differential test로 입증할 것.
3. tracked outputs/와 ledger/data 파일의 운영 의존성과 민감도는 무엇인가? 격리된 로컬 감사 없이는 삭제/공개 금지.
4. 어떤 tools/ 스크립트가 Windows 스케줄러·배포 엔트리포인트에서 직접 호출되는가? 경로 제거 전 실제 호스트 확인.
5. 어떤 데이터 조회·캐시·worker 단계가 화면 지연의 가장 큰 원인인가? 프로파일링 전 “초대형 파일이 문제”라고 단정하지 말 것.
6. 모바일 디자인의 최종 색상/타이포그래피·공통 상태 배지 용어는 기존 브랜드와 최신 사용자 결정에 맞춰 토큰/시각 회귀로 확정할 것.
7. GitHub Actions 외 다른 CI와 운영 스모크 자동화가 있는가? 호스트 접근 시 확인.
8. 여러 DB/스크립트가 가리키는 정본은 어느 것인가? 현재 원본 authority와 연결 프로토콜을 먼저 문서화할 것.
9. 실제 기능을 해결하지 않은 문구 개선·진단만의 PR은 무엇인가? 최신 현재 상태·PR별 diff를 대조해 중복 개발을 막을 것.
10. 과거 항공권/예약/카드 원본의 timezone, vendor alias, 고정 pin, ID crosswalk가 새로운 DTO 이동 후에도 호환되는가?

## 9. 완료 정의

전면 리팩토링 **완료**는 이 문서 PR의 병합이 아니다. RF-001~304 작업별 테스트·호환·성능·운영 검증이 끝나고, 각 모듈의 단일 소유권과 공통 디자인 시스템이 실제 화면에 반영됐으며, 보호된 데이터가 이전과 일치하는 상태다.

이번 산출물은 다음 구현 에이전트가 가져갈 **전체 실행 방향과 검증 가능한 작업 목록**이다. 구현에 착수할 때에는 R0 기준선부터 시작하고, 완료/미완료를 테스트·배포 증거와 함께 문서 한 곳에 갱신한다.
