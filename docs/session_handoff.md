# 현재 상태

## 2026-11-16 — Plush UI 운영 배포 요청 재개 (진행 중)

- **현재 승인:** 사용자 지시 “모든 작업 재개하고 운영배포까지해”. 실행 명세는 [Plush 설계](design/m4-plush-ui-20261116.md)와 [실행 계약](agents/artifacts/plush-ui-implementation-contract-20261116.md)이다. Rust 전환·고객 원본 변경·Google 자동 쓰기는 포함하지 않는다.
- **작업 폴더:** `C:/Users/kkokk/.paseo/worktrees/28lt5mey/plush-ui-integration-20261116`, `integration/plush-ui-20261116`. 승계 감독은 기존 C Google/D API/E 보조 후속 소유권과 미커밋 자료를 보존한다. 영수증 운영 `11267cd0`의 보호 수정은 `8d39ef5a`, 완료 기록은 `a9c31f7e`로 통합했다. 원본 폴더의 사용자·성능 작업은 변경하지 않는다.
- **검증:** 기존 broad `b46e4a92`는 1,475 passed·기존 간헐 실패1·106 subtests passed·skip0(품질 도구 요약 PASSED, pytest exit1). 해당 업로드 복구 검사는 같은 구현/테스트 blob인 현재 통합본과 기준 main에서 각각 1 passed·2 subtests passed로 재확인했다. 기대값이나 코드를 변경하지 않았다. 후속 `a9c31f7e` 영향 검사62건·skip0/새 실패0, 별도 서버/배포 표적41건, 프런트18건·타입·빌드 통과. [검증 현황](agents/artifacts/plush-ui-validation-20261116.md)에 범위와 근거를 구분한다.
- **브라우저:** TaskSpace53, 합성 DB1,003행. 앞선 390/1440 light/dark·viewer·검색·정확 합계·응답 유실/충돌/선택 반영 근거 보존. 승계 후 원본 너비 키보드50%·확대 Tab/ShiftTab/Esc/초점 복귀·320/390/720/1440 가로 넘침0을 직접 재확인했다. 실제 기기·스크린리더 실청취·실모델 판독 성공은 주장하지 않는다.
- **추가 영수증 계약:** 별도 영수증 감독이 전달한 사용자 요청에 따라 React에 서버 기본 provider/model·effective thinking과 영속 batch의 실제 모델/추론을 표시했다(`8d332330`, 표적2건·타입·빌드 통과). 서버 Terra high 기본 계약과 최종 SHA는 해당 감독 소유이며 통합 대기다. 모델 목록 조회나 기본 선택으로 실행하지 않는다.
- **남은 일/다음 행동:** 기존 C Google 비교·연결·복사, D 실제 원천/편집/보조 projection, E 규칙 대화·내보내기 후속을 통합한다. 최종 영향 검사와 정확 SHA 독립 검수 뒤 PR971 병합·검증 배포·운영 smoke를 수행한다. 현재 운영은 선행 영수증11267cd0이며 Plush 배포는 미실행이다. 배포 직전 실제 운영 SHA와 다른 배포 세션을 재확인한다.
- **복구:** `.agents/plush-integration-checkpoint.json`, `.agents/quality-b46-preserved/`, `.agents/*v8*`, `quality-artifacts/`. graphify graph/CLI가 이 worktree에 없어 query/update를 실행하지 못했다. 현재 실행 가능한 후속 작업을 계속하며 전체 완료로 표시하지 않는다.

## 2026-11-16 20:14 — 영수증 구현·운영 배포 완료, 실모델 판독은 로그인 차단

- **최신 요청/범위:** “영수증 관련 작업은 끝난건가? 이쪽 먼저 구현하고 배포해”에 따라 영수증을 우선 구현·배포했다. 영속 작업·복귀·사진/결과 교정·선택 내역 원자적 반영·PDF 원본 조회·Paseo 연결·운영 workflow 활성화를 통합했다. 성능 개선·Plush·Rust 전환은 이번 배포에 포함하지 않았다.
- **완료 코드/PR:** 최종 운영 SHA `11267cd012e074a0b89d28adb93a4dd736f64079`. 영수증 PR [#970](https://github.com/6Soo/cost/pull/970)(코드 `e977e235`, 병합 `921159ab`)와 보호 검사 수정 PR [#972](https://github.com/6Soo/cost/pull/972)(코드 `11267cd0`, 병합 `2a2ba33e`). 코드와 최종 SHA는 각각 독립 `gpt-6.1-sol medium` APPROVE. GitHub CI는 결제 한도로 작업 시작 전 실패했음을 정확 SHA의 annotation으로 확인했다.
- **검사:** 광범위 기준 `85ac8bcc` **1,443 passed +107 subtests**, 최종 영수증 변경분 `e977e235` **217 passed**, 배포 검사 수정 `11267cd0` **32 passed**, 전부 skip0·실패0. Rust costcore release build 통과. 별도 검수자는 보호 검사 표적11건과 추가 합성 불변조건29건 통과. 중복 집계하지 않는다.
- **첫 배포 실패와 복구:** `e977e235` 첫 배포는 새 빈 `receipt_evidence_links`가 추가돼 보호 표가 13→14개가 되자 개수 고정 검사가 실패했다. 공식 도구는 이전 `77865bfa`/8751로 롤백했고 health/ready200을 확인했다. 원래13표 변경0·삭제0, 추가표0행이었다. `11267cd0`는 원래 필수 표의 이름과 기존 모든 표의 내용·스키마를 검증하며, 명시 승인된 빈 추가 표만 허용한다.
- **운영 완료 근거:** 공식 `tools/deploy_verified_release.ps1` exit0. `77865bfa`→`11267cd0`, Board8752·Worker 전환 및 core writers 정합성 확인, Gateway8790. 릴리스1,764파일 Git blob 불일치0, 보호14표 불변, financial apply NOT_RUN. 별도 재점검 health200(0.423초)·ready200(0.045초), 비인증 `/receipts`·모델목록·workflow API401. 설정 workflow=true와 신규3표 존재 확인. 상세는 [운영 기록](operations.md) 맨 위 절이다.
- **백업/복원:** 첫 시도 전과 롤백 후 재시도 전 모두 board/core 범위 백업·복원 확인. 최신 `D:/WebLedgerHost/data/backups/receipt-deploy-retry-20261116-restore-evidence.json`(live/out-of-scope unchanged, binding equal). 사본 스키마 예행에서 기존78표 불변·빈3표 추가 확인. 연속 배포 도구의 `fresh_backup_restore=false`는 도구 내부 full-backup 옵션을 사용하지 않았다는 뜻이며, 위 별도 범위 백업/복원은 실제 수행했다.
- **남은 외부 차단:** 실제 사진 판독 성공만 PARTIAL/BLOCKED. 마지막 실제 Paseo 진단에서 Claude loggedIn=false·subscriptionAuth=false, 목록은 연결되지만 선택 차단. 사용자 로그인 복구 후 합성 사진의 start→완료→저장·복귀만 재검증한다. 실제 판독 성공을 주장하지 않으며 자동 유료 전환은 없다. 브라우저 TaskSpace44는 사용자 제어 중이라 takeover/대체공간을 만들지 않았고 기존 합성 검수 근거를 보존했다.
- **보존/후속:** 사용자 AGENTS.md·.codex/·.qwen/·review-size-attempt4.md와 성능 세션 변경 보존. 성능 후속 `0a1e359f`/`fix/ledger-first-load-20261116`는 운영 미반영(기록 당시 SQL48.307→0.187초, 로컬home57.405→1.874초, 표적158건); 후속 검수·배포·공개 재측정은 해당 세션 범위다. `graphify update .`는 CLI 미설치로 실패했으며 graph.json도 없어 갱신하지 못했다. 검증 worktree의 증거는 `.local-archive/receipt-deploy-20261116/`에 보존하고 공식 archive로 정리한다.

## 2026-11-16 — 영수증 Paseo 흐름 통합 검수 완료(운영 배포 전)

- **통합 커밋:** `291c44a7` (`feat(receipts): add local Paseo SDK bridge`). 로컬 Paseo provider/model catalog, 승인된 사진 입력 모델 필터, 고정 프롬프트·스키마 해시, 사진 첨부, run-key 멱등·복구, timeline 결과 회수·도구 차단·archive를 `tools/receipt_paseo_bridge.mjs`로 연결했다. `webapp/receipt_workflow.py`의 trailing whitespace도 제거해 diff 게이트를 통과시켰다.
- **직접 검사:** `node --check tools/receipt_paseo_bridge.mjs` 통과. 영수증 표적 검사 **42 passed**(runtime, HTTP acceptance, backend, UI). 영향 기반 `python tools/run_quality_checks.py --base origin/main --run` 통과: **1,253 passed, 107 subtests passed**, Rust `costcore` release build 성공. 문서 diff/link 검사도 통과했다.
- **실제 Paseo 확인:** catalog가 연결됨을 확인했고 provider 11개와 승인 가능한 Claude 사진 모델 5개를 읽었다. 합성 PNG로 `start → inspect → archive`를 실행했으며 provider가 `PASEO_PROVIDER_ERROR`를 반환했다. 로컬 timeline의 원인은 Claude 구독 결제 미납/갱신 필요였고, 코드·입력 오류가 아니다. 재호출하지 않고 차단 상태로 남긴다. 고객 원본·운영 DB·운영 포트는 사용하지 않았다.
- **브라우저 검수:** 이전 C 작업자의 TaskSpace 44 합성 검수에서 retry/revision/재분석 링크/입력 보존을 확인한 증거를 보존한다. 현재 TaskSpace 44는 사용자 제어 상태라 ego-browser가 takeover를 거부했으며, 이 세션에서 재검수하지 않았다. C 소유 합성 preview PID 27156은 종료하지 않았다.
- **상태/남은 일:** 승인된 범위의 코드·검사는 완료했지만 실제 provider 결과 검증은 구독 결제 상태가 해결될 때까지 PARTIAL이다. 운영 배포·push·PR·고객 자료 변경은 하지 않았다. 다음 재개 명령은 구독 상태 확인 후 합성 PNG로 `python` start/inspect를 다시 실행하고, 사용자가 TaskSpace 44 제어를 넘긴 경우에만 브라우저 검수를 재개하는 것이다. 사용자 미추적 `.qwen/`, `review-size-attempt4.md`, `.codex/`, AGENTS.md 변경은 보존한다.

## 2026-11-16 — Plush UI 전체 화면 설계 (문서 완료)

- **현재 요청/답변:** 사용자가 Dominik Martin의 Plush UI를 특정한 뒤 COST 전체 UI 설계를 요청했다. 주 사용 환경은 PC 장부 업무, 모바일은 조회·영수증 등록이다. 시각 선택지의 차이를 설명한 뒤 Plush의 외형·탄성 조작과 촘촘한 장부 표를 결합하는 기본안을 작성했다. 사용자가 선택지 1을 명시 승인했다고 기록하지 않는다.
- **산출물/완료 커밋:** `73bd96be` — [M4 Plush UI 설계](design/m4-plush-ui-20261116.md), SPEC §11.2와 문서 지도 연결. 정보구조·주소/권한 호환·PC/모바일 배치·두 테마 토큰·컴포넌트·모션·화면별 동선·API 요구·UI-0~6 이행·P-01~10 수락 기준을 포함했다. 이 절은 그 커밋 이후의 완료 기록이다.
- **직접 근거:** upstream `125a22ce151b719077637da38ffe9ec06a1a08c5`의 registry·tokens·README와 COST 코드/수락 기준 대조. Plush는 라이트 전용이며 표·셸·서랍과 COST 다크 테마는 확장이 필요하다. 일부 색쌍 정적 대비 계산 완료. 변경 문서 3개의 로컬 링크 114건·끊김 0, 요구/수락 ID 존재·diff check 확인.
- **범위/다음:** 설계 문서만 완료, 필수 미답 질문 없음. React 구현·패키지 설치·앱 검사·새 미리보기·push/PR·배포·고객 자료 변경은 미실행. 구현 요청 시 설계 §9의 UI-0(현 API/경로/권한/산출물 기능 지도)부터 시작한다. 기존 영수증 병렬 구현과 M3 운영 전환의 범위·상태는 아래 기록을 보존하며 이 문서로 변경하지 않는다.
- **작업공간:** 기존 `C:/AX/cost`, `integration/receipt-paseo-20261116` 재사용. 설계 관련 파일만 커밋했고 사용자 `.qwen/`·`review-size-attempt4.md` 및 다른 세션의 코드 변경은 보존했다. 별도 workspace·브랜치·서버는 생성하지 않았다.

## 2026-11-16 — 영수증 Paseo 병렬 구현·감독

- **감독 승계:** Paseo `77abc586-a18e-4b57-94f7-c9c8c3fa210e`가 인계 기록과 실제 worktree를 대조했다. 아래 최초 A/B native 작업자는 사용 한도로 실패했다. 복구 native `/root/receipt_runtime_recovery`, `/root/receipt_backend_recovery`도 초기화 대기에 머물러 중단한 뒤, 동일 worktree를 실제 실행 중인 Paseo Luna xhigh A `985d6162-2527-489c-991a-8d3165fc3013`, B `59274ce4-4e19-450a-8bb1-e98f64b99163`에 넘겼다. UI의 현재 소유자는 이어진 Paseo `1c99e24a-c577-488a-a0d4-48f8bea45095`다. 원래 폴더와 B의 미커밋 6개를 보존했다. 통합 HEAD는 아래 후속 커밋을 따르며 아직 신규 구현을 통합하지 않았다. 완료 검수·PR·배포를 주장하지 않는다.
- **후속 승계(17:17 KST):** Paseo A/B도 구독 한도로 중단돼 A `0d567726-1e72-41b0-bd75-3c67971a6cc9`, B `5a6024c1-248f-47a4-8ee5-e15ffa9fe7c1`로 자동 이어졌다. 실제 running·Luna xhigh·동일 worktree를 확인했다. 실패한 세션을 다시 실행하거나 새 작업자를 중복 배정하지 않는다.
- **감독 추가 검사:** A의 Python API·관리 지시/스키마 해시·합성 단위검사 커밋 `4521c51d`를 통합 `2b2b292d`로 반영했고 감독 직접 **8 passed, skip0**를 확인했다. 실제 SDK bridge·사진 실호출은 아직 구현 중이다. HTTP 수락 검사는 현재 20건으로, 사진별 성공·실패·0건, 원본 불일치, 장부 커밋 후 workflow 응답 유실/GET 전 교정 차단, 법인카드 증빙·청구금액 불변, 두 번째 비용 쓰기 도중 오류 시 전체 rollback을 포함한다(`ee063e3f`). 실제 CardFlow 합성 원행·장부행 seed만 별도로 확인했고 HTTP 본 검사는 B/C 통합 전이다. UI 검수에서 revision 고정·저장 실패 무한 재전송·재분석 버튼 누락을 지적해 C가 수정 중이다. ego-browser TaskSpace `44`, C 합성 preview `8799`(C 소유 PID27156)를 유지한다. 감독의 통합 preview 스크립트는 `.local-archive/receipt-paseo-implementation-20261116/supervisor_preview.py`에 준비했다(미실행). 상세 다음 명령·소유자는 같은 폴더의 `SUPERVISOR_CHECKPOINT.md`에 남긴다.
- **최신 승인:** 사용자가 작성 명세의 빠른 구현과 다수 Luna xhigh 병렬 위임을 지시했다. 이전의 문서까지만 범위는 갱신됐다. 이번에는 구현·합성 검사·PR 검수까지 진행하며 운영 배포·실제 고객 원본/운영 DB 변경은 하지 않는다.
- **기준/통합:** 명세 완료 `7b0a37ef`, 병렬 계약 `33ef9112`, 통합 branch `integration/receipt-paseo-20261116`. 실행 명세는 [영수증 처리 변경](design/receipt-paseo-workflow-20261116.md), [파일/API 계약](agents/artifacts/receipt-paseo-implementation-contract-20261116.md)이다.
- **A runtime:** native 협업 `/root/receipt_runtime_luna`, gpt-6-luna/xhigh, 공식 workspace `wks_543d5980ddf9a7e5`, branch `feat/receipt-paseo-runtime-20261116`. 동적 목록·사진 첨부·제한 실행·결과 회수 담당.
- **B backend:** native 협업 `/root/receipt_backend_luna`, gpt-6-luna/xhigh, 공식 workspace `wks_74534362dd92d88a`, branch `feat/receipt-paseo-backend-20261116`. 영속 작업·revision·복구·장부 원자성/멱등·인증 API 담당.
- **C UI:** Paseo agent `53231308-cb0e-419b-bdc9-10976f0ba7cb`, codex/gpt-6-luna/xhigh, 공식 workspace `wks_e6095e9982b526cd`, branch `feat/receipt-paseo-ui-20261116`. 모델 선택·사진/결과 검수·이탈/복귀·선택 반영 UI 담당. native 추가 thread 생성 한도에 따라 같은 계정 공식 Paseo 경로로 생성했다. 동시에 활동하는 구현자는 셋이다.
- **감독:** 주 세션이 docs·영향 맵·직접 검증·통합과 별도 최종 SHA 검수를 맡는다. 현재 코드 통합/전체 수락/배포 완료를 주장하지 않는다. 고객 원문·운영 포트·운영 DB는 작업자에게 주지 않는다. 원본 `.qwen/`·미추적 사용자 파일을 보존한다.
- **초기 확인:** runtime의 available는 사진/구독/격리 지원 증거가 아니어서 실제 제한·첨부·결과 회수 경로 검증이 필요하다. backend의 기존 manual expense API는 단건 트랜잭션이므로 선택 묶음/멱등 결과를 같은 장부 트랜잭션으로 묶어야 한다. 작업자들이 이 경계에 맞춰 구현 중이다.

## 2026-11-16 — 영수증 Paseo 동적 선택·영속 처리 명세 작성

- **현재 요청/범위:** 영수증 처리 변경의 명세 작성과 필요한 질문. 구현·실제 모델 호출·운영 변경은 요청하지 않았다. [설계 초안](design/receipt-paseo-workflow-20261116.md)을 작성하고 SPEC §7.1에 연결했다.
- **확정된 사용자 답변:** 승인된 구독 모델 중 사진 입력 가능한 모델만 선택; 관리되는 기본 판독 지시만 사용; 원본과 결과를 나란히 검수한 뒤 선택 내역만 COST 장부에 한 번에 반영. RCPT-020·RCPT-022를 개정하고 RCPT-031로 결과 보존·사용자 검수 요구를 기록했다. 카드 P1/P2·분기 AI 검수·Google 수동 붙여넣기는 변경하지 않는다.
- **설계:** 이 PC의 Paseo 모델 목록 조회 → 모델 선택과 동시에 실제 사진 첨부 → 서버 영속 작업·결과 → 다른 페이지/탭 이용 후 복귀 → 교정·선택 → 멱등·원자성을 갖춘 COST 장부 반영. 고정 프롬프트만 사용하며 미지원 모델의 OCR·다른 모델 대체는 새 흐름에 넣지 않는다.
- **직접 확인:** 현재 코드의 고정 Qwen OCR 경로·메모리 큐/1시간 TTL·브라우저 draft 저장 의존·후보 파일/TSV 출력 경계를 읽었다. 로컬 CLI 0.16.0-beta.2의 run/send `--image`와 데몬 provider/model 목록을 조회했다. provider available만으로 사진 지원·인증·한도를 확정할 수 없었다.
- **남은 기술 검증:** 운영 실행 계정의 같은 데몬 접속, 모델별 사진/도구 차단 지원, 비동기 종료 결과 회수, 기존 자료를 보존하는 영속 저장소, 실제 장부 쓰기 연결. 명세에 미검증으로 표시했으며 사용자에게 내부 구현 결정을 넘기지 않는다.
- **검증/다음:** 문서 작성 완료 커밋 `4af855bb083bd03e6f0a34e3b652182081408353`, 이후 이 완료 인계만 추가했다. Markdown217개·로컬 참조1,657건·끊김0, diff check PASS 및 코드 인용 대조. 앱 테스트·브라우저·실제 모델·운영 DB·배포 미실행. 질문3건은 모두 반영했고 추가 필수 질문은 없다. 설계 전체는 사용자 검토 전 초안으로, 문서 브랜치를 로컬에 저장했으며 PR/push/병합은 하지 않았다. 다음 구현 요청 전 코드를 바꾸지 않는다. 새 요청은 이 설계 §6 기술 확인부터 시작한다.
- **작업공간:** 기존 `C:/AX/cost` 재사용, `docs/receipt-paseo-workflow-20261116` 브랜치. 사용자 `.qwen/`·`review-size-attempt4.md` 및 기존 ignored 자료 보존. 이전 정리는 PR #969·main `9e2d66a3`에서 완료됐고 과거 절의 후속 병합·브랜치 삭제도 모두 끝났다. 아래는 이전 작업 근거다.

## 2026-11-16 — 임시 작업공간 정리 완료·주 작업 폴더 통합

- **현재 사용자 요청:** 모든 임시 워크스페이스·브랜치 병합·정리와 전체 문서 정리. 반려·철회된 변경의 재구현, 운영 배포, Rust 전환은 이번 실행 범위에 추가하지 않는다.
- **코드 통합:** #850·#966·#967·#968은 이미 병합됐다. 완료 코드 병합은 `d470eee2fc0e4da6481ad409a41944e102d40216`, 이번 정리 기준 main은 `9896a89ef9b487f013e4974bded5de5e51c79e8d`다. 카드 수집 352/352·skip0와 영수증 경로의 기존 검수·검사 근거는 [통합 기록](history/workspace-integration-20261116.md)에 보존했다. 이번에는 코드 변경이나 앱 검사를 추가하지 않았다.
- **브랜치:** 남아 있던 브랜치 4개의 tip이 모두 main의 조상임을 확인하고 복구 참조 보존 후 제거했다. 오래된 PR 검수 추적 참조 7개도 `refs/archive/20261116-final/review-tracking/`으로 보관했다. 정리용 문서 PR 브랜치는 검수·병합 뒤 제거한다. 원격 작업 브랜치는 없다.
- **작업공간:** worktree **23→1**(이번 후속에서 5→1), 원본 `C:/AX/cost`만 유지한다. Paseo 임시 workspace는 앞선 12개와 이번 3개를 공식 archive했다. 다른 프로젝트와 원본 폴더의 기존 local workspace 등록 2개는 보존했다.
- **프로세스:** 사용자가 명시 승인한 임시 프로세스 7개를 PID·생성 시각·작업 폴더로 재확인해 종료했다. 합성 미리보기 8797·8798과 관련 도구만 대상이다. 공용 Codex 서버·다른 프로젝트에서 재사용된 부모 PID·운영 서비스는 보존했다. 작업 폴더를 사용하는 프로세스가 없음을 확인한 뒤 제거했다.
- **사용자 변경:** 원본 폴더의 미커밋 15개 파일은 정리 전 ZIP과 파일별 SHA-256을 검증하고 실제 복원·해시 대조까지 마쳤다. 코드 2건은 main의 확장된 구현에 포함됨을 확인했다. 오래된 로컬 인계·감사 원문은 비공개 사본에 보존하고 최신 main 문서로 맞췄다. `.qwen/`, 기존 검사 산출물, `review-size-attempt4.md`는 원래 위치에 유지한다. 사용자 파일은 새 커밋에 포함하지 않는다.
- **미병합 보존:** Booking 예약 소실, 승객 이름의 최신 수동 별칭 덮어쓰기, 모바일 실패 검사, 중단된 P2·철회·대체 코드는 archive refs와 bundle에 보존했다. 이 기능들이 구현·병합 완료됐다는 뜻이 아니다. 결함 재현과 복원 방법은 [통합 기록](history/workspace-integration-20261116.md)을 따른다.
- **문서:** 저장소의 추적 Markdown **216개**, 로컬 파일·절 참조 **1,645건**을 검사해 끊어진 참조 **0건**을 확인했다. 기술 README의 현행 기준을 규칙집에 연결하고, 과거 설계·제안의 시점과 실제 실행·배포를 구분했다. 영수증 공급자·카드/OTA 수집기·증분 P2 첫 실행 안내도 근거 문서에 맞췄다. 최종 문서 SHA·독립 검수·병합은 이번 PR 기록을 따른다. 외부 웹 링크 검증·테스트·브라우저·운영 재배포는 실행하지 않았다.
- **복구 근거:** 앞선 `D:/CostWorkspaceArchive/20261116/`와 이번 `D:/CostWorkspaceArchive/20261116-final/`에 Git bundle·복구 ZIP·실제 복원 결과를 보존한다. 실행 기록은 `.local-archive/workspace-cleanup-final-20261116/`이다. 민감 자료와 로컬 검수 원문은 Git·PR에 넣지 않는다. 정리 요청에 남은 기능 개발·운영 작업은 없으며, 새 개발은 최신 사용자 지시에서 시작한다.
- **완료 커밋·인계:** 문서 정리 구현 `976db71b`, 이후 이 인계 문구만 추가했다. 남은 절차는 최종 SHA 독립 검수·문서 PR 병합·정리용 브랜치 삭제이며 이번 세션이 이어 수행한다. 이번 변경에는 추가 앱 검사·배포가 필요하지 않고 기능 개발 차단 사항도 없다. 반려 변경의 재개는 위 통합 기록과 비공개 bundle에서 시작하며, 운영 전환은 아래 승인 경계를 유지한다.

## 운영과 Rust 전환

- **운영:** 배포 증거 기준 `77865bfadce7cc96336cf751d1dbd41964549388`, Board 8751, readyz 200, 보호 13표 불변. 이 수치는 마지막 배포 기록이며 문서 정리를 위한 새 운영 검사가 아니다. 실제 배포 근거는 [운영 기록](operations.md) 맨 위 절.
- **Rust 1차 전환:** C1 신선 사본 7,336행, Python/Rust 그림자 차이 0·목록 밖 0. C2 185사례 두 방식 모두 동일. 과거 교정 대조 일치 131·불일치 40·원천 보호 제외 14. 전환 전 상태는 Python 작성자이며 전환 키 3개가 없다.
- **승인 ① 대기:** 이번 정리 요청은 Rust 운영 전환 승인이 아니다. [전환 절차서](playbooks/core-cutover.md)의 승인 ① → 신선 백업·복원 확인·사본 되돌림 예행 → 승인 ② → 설정 전환·Board/Worker 재시작·첫 창 대조 순서를 유지한다. 운영 `core.sqlite`는 11/15 생성분을 유지하며 백업 범위에 계속 포함한다.
- **Rust 2차(연결):** 11/15 OTA 목록 밖 차이 1,648건이 남아 별도 보류. 이번 요청에서 전환하지 않는다.
- **단계:** M2 종료, M3 진행. 구현 정본은 [SPEC](SPEC.md), 판정 정본은 [규칙집](DECISION_POLICY.md)과 `policy/`다. 이후 Rust·React·클라우드 순서와 데이터 보호는 그대로 유지한다.

이전 상세 인계와 완료 근거는 [정리 전 인계](history/session_handoff-through-20261116.md), [과거 배정표](history/BOARD-through-20261116.md), [문서 지도](README.md)에서 찾는다.
## 2026-11-16 — Plush UI 구현 통합 체크포인트

- **승인 범위:** 사용자가 Plush 전체 UI 구현을 병렬 위임하고 중단 후 재개를 지시했다. 설계 `73bd96be` 이후 공용 React 기반, 인증 API 클라이언트, 홈·여행·장부·거래·관리·영수증 화면을 통합 worktree `integration/plush-ui-20261116`에 반영했다.
- **실제 반영:** `frontend/src` 공용 컴포넌트·토큰·AppShell, `frontend/src/api` DTO/클라이언트, feature 폴더와 `main.tsx`의 `/ui/*` 경로 라우팅을 통합했다. 타입 호환 수정과 GET action 필드 순서·blob 응답 처리를 반영했다.
- **검증 근거:** `npm run typecheck` 통과, `npm run build` 통과(폰트 경로는 런타임 `/ui/fonts/...`로 남음). Vitest는 8건 중 7건 통과, blob fixture 1건은 Windows Node/jsdom Response가 Blob 본문을 `[object Blob]`로 직렬화하는 환경 불일치로 실패했다.
- **미완료/차단:** `webapp/plush_ui.py`는 정적 셸만 제공하고 `/api/plush/*` dispatcher가 아직 없다. 통합 HTTP 테스트는 `dist` fixture를 찾지 못해 4건이 setup error이며, API 구현 부재 검증까지 진행하지 못했다. 인증·ledger·receipt 서버 API와 운영 배포는 미완료다.
- **다음 명령:** D 작업 결과에서 실제 `plush_api` 서버 dispatcher를 찾아 `ledger_board` GET/POST hook에 통합한 뒤, frontend build 산출물로 `pytest -q webapp/tests/test_plush_integration.py`를 재실행한다. API가 없으면 해당 범위를 별도 구현 작업으로 기록하고 배포하지 않는다.

## 2026-11-16 — Plush projection API 통합 갱신

- D worktree의 미커밋 산출물 `webapp/plush_api.py`, `webapp/plush_projection.py`, `webapp/tests/test_plush_api.py`를 확인해 통합했다. `ledger_board._phase7_get`에서 인증 세션 확인 뒤 Plush GET projection dispatcher를 호출하도록 연결했다.
- 커밋 `670cc2ad`; API 단위 검사 `pytest -q webapp/tests/test_plush_api.py`는 6건 통과했다.
- 통합 HTTP 검사는 4건 중 2건 통과, 2건 실패했다. viewer 합성 fixture가 active connection을 만들지 않아 `visible_tabs`가 빈 집합을 반환하는 테스트 설정 문제이며, 권한 보호를 약화시키지 않고 보류한다. 운영 배포는 하지 않았다.
