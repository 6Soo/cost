# 현재 상태와 남은 일

> **GitHub 최신 코드 감사(2026-10-28 18:30 KST):** [현재 구현현황·명세 차이·후속 완료 조건](specs/implementation-status-audit-20261028.md). 당시 `main 9c3a88b`에 #288(RF-101 변경 검증), #289(RF-107 provider), #290(RF-201 shell 토큰), #291(PEND-04 배치 수집 보호)이 **병합**됐고 열린 COST PR은 0개였다. **#291은 안전한 대량 배치 코드의 병합일 뿐 실제 원문 적재·메일 작업 전환 완료가 아니다.** 마지막 운영 수락 SHA 기록 `9f6eec7`과 최신 `main`의 차이를 유지한다. 아래 generation5 로컬 작업자/브랜치/테스트 행은 작성 당시 checkpoint로 보존하며 현재 프로세스 상태를 실시간 보증하지 않는다. [제품 오너 D-01~05](specs/owner-product-decisions-20261028.md), PIR/PA/ECF/TF/TI-COST는 **명세 확정·실제 기능 구현 미완료**를 유지한다. 이 문서 PR은 코드/운영 DB/실행 중 작업자를 변경하지 않는다.


실행 정본은 [리팩토링 마스터](specs/refactor-master-20261027.md)와 아래 승인 27개 ID다. 과거 ACTIVE/READY 및 별도 SPEC_ONLY를 실행 과제로 되살리지 않는다. 상세 과거 근거는 [보관 기록](history/product-and-handoffs.md#rf-generation5-queue-archive), 배포는 [운영 기록](operations.md)을 참조한다.

- runId: `e0197439-1c34-4348-a14d-7a870c3d69b5`.
- Supervisor: `3cebc37b-17d7-4b47-9689-a2bf6f50a01c`, generation **5**, workspace `C:/AX/cost`.
- 운영 SHA: **9f6eec7a66be1fae7ee4b8d761c5c4e81d070b1e**. 최신 검수 main은 **d1180f1**(PR #286/#287/#288/#289 포함)이며 아직 운영과 다르다.
- 당시 로컬 branch checkpoint는 `refactor/rf201-tokens-reviewed-20261028`였다. 해당 토큰 변경은 이제 PR **#290 병합 완료**. 실제 로컬 작업자/현재 branch 재확인은 별도 필요.

## 승인 전체 ID와 실제 수락 경계

부분 추출의 병합을 전체 RF 완료로 승격하지 않는다. pending에도 기존 부분 구현은 있으며 완료 근거를 재사용한다. complete는 아래 두 PEND와 문서 정리 범위만이다.

| ID | 상태 | 검증된 범위 / 다음 경계 |
| --- | --- | --- |
| PEND-01 | blocked | 원결제 또는 명시 결제 증명 부재. 기존 진단 완료, 금융 연결을 창작하지 않는다. 아래 외부 자료 차단 참조. |
| PEND-02 | complete | 합성 browser3 passed와 운영 Aside 4조건·20행·넘침0의 확대/키보드/오류·재조회 수락. 물리적 모바일 검사는 아니다. |
| PEND-03 | complete | 클라우드 수집/가져오기 PR #256/d37b33c 및 전용 수집기 배포. 수집20/인증14·importer32/browser3 근거 재사용. 실제 전환은 PEND-04. |
| PEND-04 | running · **code_merged** | 전용 클라우드 수집/전수 탐색 3,704건·약281MiB는 기존 검사 근거. **#291/9c3a88b 병합 완료**: 1..100 배치, metadata 전체 선검증, 미완료 배치 apply 금지, Supervisor51 passed. **운영 원문 배치 적재·writer 전환·Gmail 예약작업 교체는 여전히 미실행**. Windows 단독 작성/백업·복원/보호13표 사전게이트 유지. |
| RF-001 | waiting_child | 기존 쓰기/간접호출 지도 재사용. 보드 작업자는 두 번 초기화 실패/error·activeTurn없음·clean을 확인했다. 실제 미진행 과제를 기존 저장소 작업자에게 이전해 순차 구현한다. |
| RF-002 | pending | 좁은 OTA 읽기 계약은175c3a2에서 이미 채택됨을 확인, 중복 구현하지 않았다. helper 실행 AST 동일·golden/canonical27 passed·입력 불변. 전체 상태 소비 수락은 부분 완료. |
| RF-003 | pending | 기존 tracked-data inventory/guard 재사용. 전체 producer/consumer와 배포 원본 제외 수락은 남음. 기존 자료 삭제/역사 재작성 금지. |
| RF-004 | running | HTTP/idempotency/flight/requirements/change-validation/provider 영향 매핑 보완·선택기8 passed. OS/실DB/known-failure 전체 기준선 수락은 남음. |
| RF-005 | pending | 고정 SHA 배포/복구와 runtime catalog 재사용. 중복 배포 진입점·호스트 의존성 수렴은 부분 완료. |
| RF-101 | waiting_child | 읽기·schema·배분·감사·멱등성 배포. 변경 검증 PR #288/f877629 병합, Supervisor70 passed/3subtests·SQL 동일·다른144메서드 AST 불변. 다음 입력 정규화 d1dfd42 반환, 검수 전. |
| RF-102 | running | 렌더·읽기·export·dialog·HTTP shape PR #267/#278/#284 병합, HTTP까지9f6eec7 배포. session/auth/lifecycle/route 전체 분리 수락은 남음. |
| RF-103 | running | 카드 근거·환불 query·OTA 투영·cleanup PR #261/#268/#269/#276 검수/병합/배포. 여행 authority/decision/background 전체 수락은 남음. |
| RF-104 | running | 중앙 대사·예약 그룹/페이지·증분 성능 기존 구현 재사용. 전체 consumer의 같은 세대/링크/trace 수락을 대조하고 solver를 재구현하지 않는다. |
| RF-105 | running | 원승인번호1:N 보호와 환불 UI PR #281 배포. 캐시/단일/목록/기장 전체 경계 수락은 남음. |
| RF-106 | running | 검색 projection PR #286/ab85215 병합. Supervisor71 passed·selector8. query 정규화1회·IO 전 검증·lazy status·linked_cards None/identity·revision 보존. 운영 배포 대기. |
| RF-107 | running | provider schema/masking PR #289/d1180f1 병합. 필수 signature·ConfigError 동일성·기존 순수/저장소/service AST 동일, Supervisor135 passed/105subtests. 전체 adapter 수렴은 남음. |
| RF-108 | pending | schema/additive/복원/snapshot 기존 기반 재사용. 쿼리 plan·P95·메모리 측정 후 최적화. 실제 DB migration은 별도 게이트. |
| RF-109 | pending | runtime catalog 정적616후보·8검사 재사용. 활성 호출/인자·guard 분류와 중복 CLI 수렴은 부분 완료. |
| RF-201 | running · **subtask_merged** | #290/322ef3f 병합: 공통 geometry/터치 토큰, 8폭·양테마·CSS100/200% 합성 matrix4 passed, Supervisor20 passed/1 deselected. 공통 palette bridge 유지, 터치 높이44px. **전체 디자인 시스템·실물 모바일 수락은 미완료**. 운영 SHA 재검증 필요. |
| RF-202 | running | 공통 셸 조립 PR #277/자산 PR #282 배포. URL/DOM·테마1개 보존. 전체 화면 수락과 구별한다. |
| RF-203 | running | 검토 문서 PR #265·guidance16검사·template byte 동일성 배포. 전체 폼/지출 컴포넌트 채택 수락은 남음. |
| RF-204 | pending | 기존 OTA/환불/항공권 정보 구조 개선 재사용. 전체 동일 상태/인라인 근거/접근성 수락은 남음. |
| RF-205 | pending | 기존 responsive/keyboard/theme 근거와 RF-201 합성 baseline matrix 재사용. 인증 운영 화면·실기기 포괄 수락은 미실행. |
| RF-301 | running | requirements 단일 생성/검증 PR #283/9f6eec7 배포. 선언5개 동일·기본 읽기·원자적 mirror.51검사+selector8. 환경/비밀/feature flag 전체 정리는 남음. |
| RF-302 | pending | 기존 관측·OTA 성능 근거 재사용. 공통 request/snapshot/rule/fingerprint·단계 지연 및5경로 p50/p95/bytes/memory 전체 수락은 남음. |
| RF-303 | waiting_child | 기존 selector/guard 재사용. 로컬 gate f78c75c는 malformed JSON/누락도구/no-target 등 fail-open을 발견해 교정 중. CI/type/lint/dependency/security 전체 수락은 남음. 신규 유료 인프라 금지. |
| RF-304 | complete | 단일 문서 진입점·승인27개 큐 압축/보관 PR #287/fc2e44b 병합, 새 상대링크 누락0. 새 한글 인코딩 손상은 UTF-8 파이프 bytes 검증 후 현재 큐/해당 운영 절/새 보관 기록에서 복구했다. 문서만으로 앱 검사/배포를 반복하지 않는다. |

## 현재 작성권과 재사용할 에이전트

기존 **AGY Gemini 3.8 Flash Medium** 4명을 재사용한다. 작업자 재위임·push·PR·배포·운영/고객 원문 접근은 금지한다. 공통 문서/운영/인증/원문은 Supervisor만 작성하며 같은 파일/DB/외부 효과 작성자는 하나다.

| 실제 child agentId | worktree suffix / 현재 소유권 |
| --- | --- |
| `98cc885f-5d8c-4c99-8d5e-01ccfe57a6ea` | `cost-rf102-board`: 초기화 실패2회·error·activeTurn없음·clean. 새 변경 없음, 재개하지 않고 기존 결과 보존. |
| `bf74bc49-d0d8-41be-886e-3255dca226fe` | `cost-rf101-store`: normalization d1dfd42의 _canonical 동적 위임 교정 후 RF001 tools/refactor_call_map.py·독립검사·비식별 config로 작성권 이전. |
| `bce73f79-9de8-4f22-8c1e-04ab8ab6efd1` | `cost-rf103-evidence`: app/cloud_mail.py·합성 검사만으로 PEND04 bounded batch 구현. 원문/운영 실행 금지. |
| `995ccfb3-16d8-4dfe-82fd-65ca02fc4091` | `cost-rf201-assets`: tools/run_targeted_checks.py·독립검사 fail-open 교정. 기존 UI 결과는 Supervisor 검수/통합. |

worktree root는 `C:/Users/kkokk/.paseo/worktrees/28lt5mey/`다. 실행 중 child에 같은 과제를 다시 보내지 않는다. provider stream/초기화 오류는 로컬 실행 실패이며 외부 권한 차단으로 바꾸지 않는다. 완성 커밋은 실제 diff·검사를 대조해 회수한다.

## 배포와 검증 근거

- 운영 **9f6eec7**: PR #280~#285 포함. 이전 검증535b6dd3178758a5a442eb6a8e7b0d60517a5cb3 복구점 보존.1,034 Git blob 불일치0·작업/프로세스SHA·단일loopback listener·health/ready200·OTA 보호API401·보호13표 내용/스키마 불변. data guard base 차단0/삭제0. 기존 검증 백업/별도 복원 근거 재사용.
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

정확한 다음 행동: RF201 표적/차등 수락→직렬 PR/main·검수 묶음 고정 SHA 배포/health/auth/보호 최소 스모크. 동시에 반환 normalization/gate/batch의 실제 diff·표적 검사를 수행하고 PEND04 single-writer/복원 게이트를 준비한다. 준비된 독립 항목은 계속 진행한다.
