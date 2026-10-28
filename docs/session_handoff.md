# 현재 상태와 남은 일

## 계정 전환 후 통합 검수 (2026-10-28)

후속 담당은 `a8dba9f3-3e50-4a26-b113-ab754767883e`다. 이전 담당에게 메시지를 보내거나 재개하지 않는다. 잠정 배정 최종 `494761842aa6da982133a8548edc660b9d11b65a`를 최신 main `9c7580d8d12e869dc23dee8f3f822033d28389d2`에 정상 통합했다. 통합본 새 화면·금융 보호 226 passed, 권한·환불·우선배정·OTA 페이지/스냅샷 227 passed, 변경 Python 12개 compile 및 diff 검사 통과. 선택기 미매핑0, metadata guard 차단0/삭제0. 실제 브라우저 검사는 합성 자료를 사용하며 운영 실자료 수락과 구별한다.

현재 운영은 검증된 `61211012a0bbd250ab5e5fa6b629e3af9e672324`다. 다음은 이 통합 PR 정상 병합 → 병합 SHA와 검수 소스 일치 확인 → 기존 Windows 절차의 새 백업·별도 복원 검증 → 고정 SHA 배포 → health/ready·보호 API·보호13표 불변 확인이다. 실제 재배정·일괄 처리·보험 명단 전송·Google 쓰기·마이그레이션은 실행하지 않는다. PA-01 실자료 기준선과 PA-06 실자료 수락은 미측정이다. 기존 여섯 CardFlow 실패는 작업자 기준 `61211012`에서도 같은 node로 재현한 별도 기록이며 통과 수에 포함하지 않는다.

기존 27개 큐는 과거 수락 경계를 보존한다. 새 managed run은 `07264b89-75e8-4748-9ab5-9f7ae4d3035a`, generation 1이며 checkpoint는 같은 run 디렉터리의 `checkpoint.json`이다. 운영 배포 결과는 아래 후속 기록을 우선한다.

기존 managed run 정본은 [리팩토링 마스터](specs/refactor-master-20261027.md)와 아래 27개 ID다. 이후 사용자가 명시 선택한 명세 대기 기능의 코드 구현·검증 배포 승인은 아래 최신 진행 기록에 추가한다. 과거 ACTIVE/READY 전체를 자동 재실행하지 않는다. 상세 과거 근거는 [보관 기록](history/product-and-handoffs.md#rf-generation5-queue-archive), 배포는 [운영 기록](operations.md)을 참조한다.

- runId: `e0197439-1c34-4348-a14d-7a870c3d69b5`.
- Supervisor: `3cebc37b-17d7-4b47-9689-a2bf6f50a01c`, generation **5**, workspace `C:/AX/cost`.
- 운영 확인 SHA: **ad117015a13e6cb440d3fb03d7e5c1a9b66e09a0**. 정상 배포·보호 검사 근거는 아래 최신 진행 기록과 운영 기록을 따른다. 실제 단일 환불 그룹 적용은 owner 인증 대기다.
- 사용자 작업 사본은 `C:/AX/cost`이며 사용자 미추적 파일·stash와 미수락 결과를 보존한다. 정리·통합 브랜치 근거는 `.local-archive/merge-cleanup-20261028/`에 기록한다.

## 승인 전체 ID와 실제 수락 경계

부분 추출의 병합을 전체 RF 완료로 승격하지 않는다. pending에도 기존 부분 구현은 있으며 완료 근거를 재사용한다. complete는 아래 두 PEND와 문서 정리 범위만이다.

| ID | 상태 | 검증된 범위 / 다음 경계 |
| --- | --- | --- |
| PEND-01 | blocked | 원결제 또는 명시 결제 증명 부재. 기존 진단 완료, 금융 연결을 창작하지 않는다. 아래 외부 자료 차단 참조. |
| PEND-02 | complete | 합성 browser3 passed와 운영 Aside 4조건·20행·넘침0의 확대/키보드/오류·재조회 수락. 물리적 모바일 검사는 아니다. |
| PEND-03 | complete | 클라우드 수집/가져오기 PR #256/d37b33c 및 전용 수집기 배포. 수집20/인증14·importer32/browser3 근거 재사용. 실제 전환은 PEND-04. |
| PEND-04 | running | bounded batch 코드 PR #291/main9c3a88b와 51개 표적 검사 수락, 원문 적재/작업 전환은 미실행. 최신 read-only Drive manifest는 3,710 stored·48 pending·has_next_page=true·complete=false로 후속 enumeration 진행 중이다. 전체 batch preview는 enumeration 완료 후 재시도한다. 현재 상태 근거 `.local-archive/all-pending-20261028/cloud-backfill-state.json`. |
| RF-001 | running | 정적 호출 지도 `config/refactor-call-map.json`·도구 PR #294/main `8e479de` 병합, 경로 영향 매핑 PR #296/main `ba74ab8` 병합. 표적/선택기 18건 통과. RF-001 및 RF-101 통합 101 passed/3 subtests; 전체 gate는 12개 모듈에서 OTA `inferred_link` KeyError 1건으로 실패했고 기준 SHA `355eaea`에서도 같은 assertion 재현. 전체 Route→service→repository→table→external-effect와 권한 수락은 미완료. |
| RF-002 | pending | 좁은 OTA 읽기 계약은175c3a2에서 이미 채택됨을 확인, 중복 구현하지 않았다. helper 실행 AST 동일·golden/canonical27 passed·입력 불변. 전체 상태 소비 수락은 부분 완료. |
| RF-003 | running | 기존 tracked-data inventory/guard 재사용. 전체 producer/consumer와 배포 원본 제외 수락은 남음. 기존 자료 삭제/역사 재작성 금지. |
| RF-004 | running | HTTP/idempotency/flight/requirements/change-validation/provider 영향 매핑 보완·선택기8 passed. OS/실DB/known-failure 전체 기준선 수락은 남음. |
| RF-005 | running | 고정 SHA 배포/복구와 runtime catalog 재사용. 중복 배포 진입점·호스트 의존성 수렴은 부분 완료. |
| RF-101 | complete | 입력 정규화 `9930b42`·동적 콜백 교정 `5f0ac83` 포함 PR #294/main `8e479de` 병합. 스토어 정규화·idempotency·audit·allocation·schema·records·change-validation·store·income_bank 및 RF-001 검사 101 passed/3 subtests; 호출 동적 재바인딩·SQL/audit/revision/idempotency 계약을 유지. |
| RF-102 | complete | 필요한 helper와 façade 분리는 최신 main에 이미 반영되어 있다. main SHA 355eaea 기준 HTTP/render/read/export/dialog 표적 49 passed. 임시 RF102 브랜치와의 유일한 소스 차이인 query fallback은 호출 타입 계약을 불필요하게 넓혀 채택하지 않았고 원본 브랜치는 증거 보존 후 정리한다. |
| RF-103 | running | 카드 근거·환불 query·OTA 투영·cleanup PR #261/#268/#269/#276 검수/병합/배포. 여행 authority/decision/background 전체 수락은 남음. |
| RF-104 | running | 중앙 대사·예약 그룹/페이지·증분 성능 기존 구현 재사용. 전체 consumer의 같은 세대/링크/trace 수락을 대조하고 solver를 재구현하지 않는다. |
| RF-105 | blocked | PR #295 `496cbbe` 운영 배포 완료. 1,051 tracked blobs 일치, task/process SHA 고정, listener 1개, health/ready 200, 보호 API 401, 새 백업·별도 복원 검증과 보호 13표 불변. owner 화면은 AUTH_REQUIRED로 승인된 단일 환불 그룹 적용 미실행. 실제 관측 그룹은 같은 import batch이므로 교차 배치 실행 증거로 표현하지 않는다. 환불/금융 표적 74 passed; 넓은 검사 실패 13건은 ba74ab8에서도 동일 node ID로 재현. PR #297 개별 그룹 UI/API는 e1a6c7b로 병합했으며 운영 배포 여부는 아래 최신 진행 기록을 따른다. |
| RF-106 | running | 검색 projection PR #286/ab85215 병합. Supervisor71 passed·selector8. query 정규화1회·IO 전 검증·lazy status·linked_cards None/identity·revision 보존. 운영 배포 대기. |
| RF-107 | running | provider schema/masking PR #289/d1180f1 병합. 필수 signature·ConfigError 동일성·기존 순수/저장소/service AST 동일, Supervisor135 passed/105subtests. 전체 adapter 수렴은 남음. |
| RF-108 | pending | schema/additive/복원/snapshot 기존 기반 재사용. 쿼리 plan·P95·메모리 측정 후 최적화. 실제 DB migration은 별도 게이트. |
| RF-109 | running | runtime catalog 정적616후보·8검사 재사용. 활성 호출/인자·guard 분류와 중복 CLI 수렴은 부분 완료. |
| RF-201 | running | 자산 배포, geometry 단일 소유2559ef7 및 실제 CSS zoom/baseline 검사8798569 회수. 작업자 전체4 passed(99.88초), Supervisor 인접20 passed/1 deselected. native/standalone·8폭·양테마·CSS1/2배는 합성 수락이며 실기기 검사가 아니다. PR #290/322ef3f 배포. |
| RF-202 | running | 공통 셸 조립 PR #277/자산 PR #282 배포. URL/DOM·테마1개 보존. 전체 화면 수락과 구별한다. |
| RF-203 | running | 검토 문서 PR #265·guidance16검사·template byte 동일성 배포. 전체 폼/지출 컴포넌트 채택 수락은 남음. |
| RF-204 | running | 기존 OTA/환불/항공권 정보 구조 개선 재사용. 전체 동일 상태/인라인 근거/접근성 수락은 남음. |
| RF-205 | running | 기존 responsive/keyboard/theme 근거와 RF-201 합성 baseline matrix 재사용. 인증 운영 화면·실기기 포괄 수락은 미실행. |
| RF-301 | running | requirements 단일 생성/검증 PR #283/9f6eec7 배포. 선언5개 동일·기본 읽기·원자적 mirror.51검사+selector8. 환경/비밀/feature flag 전체 정리는 남음. |
| RF-302 | running | 기존 관측·OTA 성능 근거 재사용. 공통 request/snapshot/rule/fingerprint·단계 지연 및5경로 p50/p95/bytes/memory 전체 수락은 남음. |
| RF-303 | complete | PR #293 merged as 355eaea5c8476f153bc43ff5320b572f7fb27c4f. Fail-closed schema/selector validation, sanitized errors, preview/run separation and self-impact mapping accepted. Supervisor: 31 tests passed; preview PREVIEW with executed=[]; --run PASSED (guard blocked_count 0, py_compile, targeted pytest). Operating deploy is grouped after the remaining approved integrations. |
| RF-304 | complete | 단일 문서 진입점·승인27개 큐 압축/보관 PR #287/fc2e44b 병합, 새 상대링크 누락0. 새 한글 인코딩 손상은 UTF-8 파이프 bytes 검증 후 현재 큐/해당 운영 절/새 보관 기록에서 복구했다. 문서만으로 앱 검사/배포를 반복하지 않는다. |

## 현재 작성권

main PR·배포·공통 문서·COST 임시 공간 보관은 Supervisor `3cebc37b`만 담당한다. PA04/05/06 화면·승인 API는 `4c407a16`가 기존 assignment worktree의 단독 작성자다. 최신 main `61211012`를 정상 merge한 중간 53검사 통과 보고까지 수신했으며, 최종 browser·금융 보호 검수 결과는 아직 기다린다. cleanup 공간은 보존한다. 참가자·항공·OTA는 PR #300으로 병합·배포했고 공식 보관 결과는 아래 최신 기록을 따른다. 다른 저장소 보험 sender 코어 21검사는 실제 가입·명단 전달 승인이나 실행 근거가 아니다.

## 이전 작업자 인계 이력

다음 표는 종료·교체된 작업자의 과거 기록이며 재개 지시가 아니다. ANUS 이후 사용자 Luna 병렬 위임 결과도 회수했으며, 실제 quota로 유료 대체·작업자 반복 생성은 하지 않는다.

사용자 최신 지시는 **ANUS free(auto)** 위임이다. 기존 AGY의 완료 커밋/미커밋/작업공간을 보존해 재사용하고 실행 제공자만 사용자 지정으로 전환한다. 두 작업자의 실제 Individual quota reached(약2시간29분 후 reset)와 자동 continuation alias의 같은 오류를 확인해 반복 위임하지 않는다. 자동 복구로 실행된 Codex 현재 owner5319cc4c/ceed86f8을 중단한 뒤 Anus 작업자2명을 같은 workspace에 배정했다. 확인한 제공자 anus의 모델 ID는 anus/free(무료 자동 회전)이며 유료 대체·재위임·운영 접근은 금지했다. 작업자 재위임·push·PR·배포·운영/고객 원문 접근은 금지한다. 공통 문서/운영/인증/원문은 Supervisor만 작성하며 같은 파일/DB/외부 효과 작성자는 하나다.

| 실제 child agentId | worktree suffix / 현재 소유권 |
| --- | --- |
| `98cc885f-5d8c-4c99-8d5e-01ccfe57a6ea` | `cost-rf102-board`: 초기화 실패2회·error·activeTurn없음·clean. 새 변경 없음, 재개하지 않고 기존 결과 보존. |
| `e253fa73-485c-4e55-b87f-22f56208b323` (Anus) | `cost-rf101-store`: d1dfd42/3afc1d7 보존 결과 검수 후 RF001 tools/refactor_call_map.py·독립검사·비식별 config 구현. 기존 AGY/Codex 실행은 중단, 파일 보존. |
| `bce73f79-9de8-4f22-8c1e-04ab8ab6efd1` | `cost-rf103-evidence`: app/cloud_mail.py·합성 검사만으로 PEND04 bounded batch 구현. 원문/운영 실행 금지. |
| `9b367736-16e9-40c2-8516-21acec02ae32` (Anus) | `cost-rf201-assets`: tools/run_targeted_checks.py·독립검사 fail-open 교정. 기존 미커밋2파일을 보존해 이어간다. UI는 PR290 배포 완료라 재구현하지 않는다. |

worktree root는 `C:/Users/kkokk/.paseo/worktrees/28lt5mey/`다. 실행 중 child에 같은 과제를 다시 보내지 않는다. provider stream/초기화 오류는 로컬 실행 실패이며 외부 권한 차단으로 바꾸지 않는다. 완성 커밋은 실제 diff·검사를 대조해 회수한다.

## 배포와 검증 근거

- **322ef3f 고정 배포 완료**: PR #286 항공권/#288 변경 검증/#289 provider/#290 토큰·UTF-8 교정 포함.1,041 Git blob 일치·작업/프로세스SHA·단일loopback listener·health/ready200·보호API401·보호13표 불변. 이전9f6eec7 복구점과 검증된 복원 사본 보존. PEND04 원문 적재/작업 전환 미포함.

- 이전 운영 **9f6eec7**: PR #280~#285 포함. 이전 검증535b6dd3178758a5a442eb6a8e7b0d60517a5cb3 복구점 보존.1,034 Git blob 불일치0·작업/프로세스SHA·단일loopback listener·health/ready200·OTA 보호API401·보호13표 내용/스키마 불변. data guard base 차단0/삭제0. 기존 검증 백업/별도 복원 근거 재사용.
- 최근 Supervisor: HTTP98, 멱등성66/3subtests, requirements51, selector8, 항공권71, 변경 검증70/3subtests, provider135/105subtests, 토큰 인접20/1deselected. 단위는 pytest tests/subtests이며 서로 다른 실행 건수를 합산해 전체 회귀처럼 보고하지 않는다.
- 멱등성의145개 메서드 집합/SQL 동일·139개 AST 불변, 변경 검증은 _validate 외144개 AST 불변. 작업자 모듈별 실제 통과와 공개 baseline differential 근거를 재사용한다. 무관한 전체 회귀는 반복하지 않았다.
- 로컬 `.local-archive/refactor-parallel-20261028/`의 equivalence/review/protection JSON과 호스트 동일SHA release-audit/deploy-evidence가 근거다. 개인정보·원문·계정/폴더ID·인증값은 Git/보고서에 넣지 않는다.

## PEND-04 실제 게이트

[클라우드 전환 명세](specs/cloud-mail-cutover.md)의 기존 승인만 수행한다. 전용 프로젝트·사용자 직접 Apps Script/Drive 동의·callback·전용 ADC·Drive 소유자/비공개 확인은 완료했다. 재동의나 기존 인증 교체는 하지 않는다.

`cloud-backfill-state.json`에서3,704건/pending0/has_next_page=false/query=null/last_complete 존재로 초기 전체탐색 완료를 확인했다. last_complete는 탐색 시작 watermark이며 관측 완료시각과 다르다. 단일 반복기는 완료 후 정상 종료했다. Drive size294,501,933B 때문에 기존 무제한 읽기 preview를 중지했고 안전100MiB를 유지한 bounded batch 합성 보완 중이다.

기존 `WebLedger-MailCollect`는 직접 Gmail 수집/Ready이며 호스트 원문 적재·운영DB import·작업 전환은 미실행이다. 다음 순서:

1. 배치 코드/보호 검사를 통과하고 모든 batch preview의 내용 검증·전체 indexed=existing+new·enumeration_complete를 확인한다.
2. 기존 작업 XML/명령/상태 보존→직접 writer disabled/idle·동시쓰기0→신선한 원문/통합DB/보호DB 백업·별도 복원 동등성→보호13표 기준선.
3. 승인된 원문 append/import→기존 원문/헤더·금융/수동결정 불변→반복 appended0/DB 불변→COST/worker 새 원문 반영 수락.
4. 클라우드 후속 예약 실행1회와 Drive 전달 수락 후에만 Gmail 작업을 Drive 전달 전용으로 전환한다. 실패 시 검증된 이전 작업만 복원하고 원문은 보존한다.

로컬 준비 실행기는 `apply_verified_cloud_mail.py`, `verify_imported_cloud_source.py`, `cloud_relay_runner.py`다. 실제 single-writer/backup/restore 확인 없이 환경 문자열만 넣어 실행하지 않는다. Board가 Windows에 있으므로 완전한 로컬 의존 제거라고 보고하지 않는다. Board 릴리스와 원문 적재는 외부 효과를 직렬화한다.

## 외부 자료 차단과 범위 밖 보존

- **PEND-01 external_data**: 카카오39취소 중29연결/10미연결, Agoda76중73/3, Trip전체186중171/15. Trip15중12는 원승인번호가 있으나 DB/보관/추가 탐색에서 원결제를 찾지 못했다. 원결제 원본 또는 명시 결제 증명이 필요하다. 금융/원문/수동결정 쓰기0. `.local-archive/all-pending-20261028/refund-evidence-summary.json` 및 recovery summaries 근거 유지.
- **SPEC_ONLY, 실행 제외**: [오너 결정](specs/owner-product-decisions-20261028.md), [보험 참가자/수입](specs/participant-income-authority-and-drag-link-20261028.md), [잠정배정 검토](specs/provisional-assignment-review-first-20261028.md), [지출 상태 필터](specs/expense-cleanup-status-filter-actions-20261028.md), [여행 항공권](specs/trip-flight-booking-overview-20261028.md), [Travel INS 연동](specs/insurance-participant-integration-20261028.md). 과거 미구현 표기는 새 RF 기능 승인이 아니다.
- 별도 카드 전체 내역 과밀 개선 PR #273은 구현/배포 완료, 인증된 운영 화면 수락만 남은 이전 범위다. 과거 ALL/R0/R1은 보관 근거이며 새 큐가 아니다.
- 사용자 미추적 `apps-script/CloudMail.gs`, `docs/superpowers/`, `scratch/`, `webapp/tests/tmp71q0k16e/`, `webapp/tests/tmp_dfqgw61/`와 기존 stash/기존 workspace를 보존한다.

## 다음 실행과 인계

각 결과마다 해당 행/근거를 갱신하며 세션별 전체 큐 사본을 새로 만들지 않는다. 최신 사용자 결정이 과거 문서보다 우선한다. 고객 원본/수동결정 보존, 인증 우회·강제 push·자료 삭제·미승인 과금 금지, Google 최종 장부 읽기 전용을 유지한다.

공통 checkpoint: `C:/Users/kkokk/.paseo/paseo-accounts/work-runs/e0197439-1c34-4348-a14d-7a870c3d69b5/checkpoint.json`. Publisher: `.local-archive/refactor-parallel-20261028/publish_checkpoint.py`. 승인27개 ID·queue bytes SHA256·generation5 실제 agentId를 원자 갱신한다. family results-ack는 검수한 이벤트만 누적한다.

정확한 다음 행동: RF201 표적/차등 수락→직렬 PR/main·검수 묶음 고정 SHA 배포/health/auth/보호 최소 스모크. 동시에 반환 normalization/gate/batch의 실제 diff·표적 검사를 수행하고 PEND04 현재 원격 manifest 완료를 확인한 뒤 읽기 전체 preview 및 single-writer/복원 게이트를 준비한다. 준비된 독립 항목은 계속 진행한다.

<!-- integration-progress-start -->
## 2026-10-28 최신 병합·정리 진행

- 사용자 최신 지시로 검증된 PR·브랜치 통합과 운영 코드 배포를 진행한다. 금융 데이터 적용은 기존 단일 환불 그룹 승인과 정상 owner 인증 범위다.
- PR #297 `e1a6c7b`, RF 통합 PR #298 `fe12cf4`, 지출 필터 PR #299 `ad11701` 정상 병합. 환불 83개·인접 보호 38개, RF 통합 99개와 26 subtests, 최종 필터/환불 통합 21개를 각각 통과했다. 서로 다른 검사를 합산해 전체 회귀로 표현하지 않는다.
- 로컬 병합 브랜치 97개 정리, 원격 병합 브랜치 93. 모든 삭제 대상 커밋은 `refs/archive/20261028/`에 보존하고 main·사용 중 브랜치·stash는 보존한다.
- 별도 원본 이력인 로컬 6개·원격 명세 8개는 과거 버전을 main에 다시 합치지 않고 `refs/archive/20261028/historical/` 및 검증된 `historical-branches.bundle`에 보관했다. 미병합 이력을 병합 완료로 표현하지 않는다. 옛 rf102 통합 공간의 변경 문서 2개도 `450f626` checkpoint와 파일 사본으로 보존했다.
- 통합·사용 종료 작업 공간 11개 공식 보관 및 디렉터리 제거 확인. 정리 처리 중 0개. RF201의 최초 API 300초 시간 초과는 공식 CLI 재확인 후 디렉터리 제거까지 확인해 해소했다. 검증이 끝난 임시 baseline worktree 2개도 보관 참조를 남기고 정상 제거했다. 활성 작업 공간과 미커밋 자료는 보존한다.
- 운영 확인 SHA: `61211012a0bbd250ab5e5fa6b629e3af9e672324`. 후속 PR #300은 `61211012a0bbd250ab5e5fa6b629e3af9e672324`로 병합했으며 실제 배포 완료 여부는 호스트 deploy-evidence를 따른다. RF 사전 점검·공통 UI·검사 게이트는 검증된 하위 묶음이며 전체 RF 완료가 아니다.
- 다른 세션의 사용자 명시 선택인 “명세 대기 기능까지 모두 포함”이 질문 이벤트와 응답 전달 `ab4efea4-875b-400e-82ad-7e0aa69a5a69`로 확인됐다. 추가 기능의 코드 구현·정상 검증 배포에 적용하며 실제 금융/여행/명단/보험/Google 쓰기 게이트를 확대하지 않는다. 기존 managed run의 27개 ID는 유지하고 추가 명세 작업은 별도 작업자 근거와 대조한다.
- 로컬 근거: `.local-archive/merge-cleanup-20261028/`의 refs/workspaces/progress 기록. 금융 적용은 AUTH_REQUIRED로 미실행이다.
- 참가자·항공 bundle `43588d9`(항공 `0cd571f` 포함)와 OTA `53d25fe`는 PR #300으로 통합했다. 통합 347 passed/31 subtests·인접 34 passed·선택기 48 passed. 기존 signed-session 6건과 폐기 Google/고정 자산 기준 26건 실패는 main `ad117015`에서 동일 재현했으며 통과에 포함하지 않는다. 데이터 guard 차단0·선택기 미매핑0·변경 Python20개 컴파일·diff 검사 통과. 잠정 배정 PA UI/API는 기존 부모 `4c407a16`가 단독 작성하며 새 작업 공간·유료 모델 전환 없이 이어간다.
- PR #300 고정 SHA `61211012` 배포는 1,077 blobs 불일치0·fresh backup/별도 복원·task/process SHA·loopback listener1·health/ready200·보호 API401·보호13표 전후 불변으로 수락했다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-61211012a0bbd250ab5e5fa6b629e3af9e672324.json`이다. 문서 후속 병합만으로 재배포하지 않는다.
<!-- integration-progress-end -->

## 이전 GitHub 감사와 후속 확인

[18:30 구현 감사](specs/implementation-status-audit-20261028.md)와 [동일 화면 환불 복구 명세](specs/refund-inline-existing-repair-20261028.md)는 당시 코드·운영 차이를 남긴 기록이다. 이후 PR #297~#300 검수·배포 근거는 위 최신 진행 기록이 대체한다. 기존 거래 자동 소급처리나 단일 환불 그룹 실제 적용은 수행하지 않았으며, 원문 오류·수동 보류·승인번호 미확인 건은 보호한다. [제품 오너 결정](specs/owner-product-decisions-20261028.md)의 미완료 기능은 사용자 후속 명시 승인에 따라 단계별 구현 중이며 전부 완료된 것으로 표시하지 않는다.
