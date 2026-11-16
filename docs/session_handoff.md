# 2026-11-17 02:31 — 몽골 항공료 실제 기장·Google 수입 표시 완료

- **실제 결과:** 운영 worker가 항공료8건·6,500,202원을 표준 경로로 기장했다. 각 ledger/board 정확1회·귀속/이용기간/원문 해시 일치. 유효 몽골 보드는 **14건·6,767,151원**이다. 원문·금액·날짜·ID·수동 교정·대상 밖 금융/core 결정·나머지 보호표 불변. 같은8건 큐 재처리 후 모든 보호 금융표와 core 전체 상태 동일, pending0·recorded8/failures0.
- **수입:** 인증 브라우저에서 **14행(금액13+합계빈1), 표시합17,337,200원**과 미확인1·잠정 안내를 확인했다. 390/1440px 가로넘침0. 원장 빈 합계를 수정하지 않았으므로 수입·차액10,570,049원은 잠정값이다. Google 최종 장부 쓰기0.
- **운영/검사:** 공식배포 exit0, actual9af204148b1b6450f7bb9c6ec1185c5f2f3aa852/8751, Previous8888230d. 1883파일 blob불일치0·코드배포 보호14표 불변·health/ready200·보호API401. Rust/rust·기존888bin·설정 해시 보존. 신선4DB 백업복원 후 배포했고 프로세스 임대 기록 변경을 설치 게이트가 감지하자 postdeploy board/core 백업복원도 다시 통과한 뒤 보호원문 설치·기존 큐만 등록했다. 직접 금융 SQL은 사용하지 않았다.
- **검수/다음:** 정확코드9af 공식1101+30subtests/skip0·관련합성21·frontend79/type/build PASS. 독립 gpt-6.1-sol medium 코드9af/docs-only46cbed24와 설치 스크립트 APPROVE. 최종 PR SHA 판정은 PR980에 기록한다. 실제 기장·표시·배포·재처리 검증은 완료했으며 PR980 검수/병합과 소유권 해제 통지를 마무리한다. 문서 때문에 재배포하지 않는다. 기존 라쿠텐/어드벤처 수동 보드 교정에 따른 raw ledger16건7793532원과 유효보드14건은 구분해 보존했다. [상세 근거](agents/artifacts/reviewed-booking-income-20261117.md).

# 2026-11-17 — cgpflix232 계정으로 작업 인계

- 사용자 지시에 따라 진행 과정을 저장하고 Accounts AGY의 cgpflix232 계정으로 원래 작업 전체를 이어간다. 코드 후보 `9af204148b1b6450f7bb9c6ec1185c5f2f3aa852`, PR980(draft/pushed), 독립 gpt-6.1-sol medium APPROVE, 표적21건·frontend79건·타입·빌드 PASS。9af 공식 영향 검사1101건+30subtests PASS/skip0를 마지막에 회수했다. 신선4DB 백업/복원은 아직 결과 회수 전이다. 앞선 f547 검사 결과를 최종SHA 근거로 대신 쓰지 않는다.
- **운영 미완료:** actual8888230d/rust writer/rust links/기존bin을 유지한다. 이번 변경 배포·검수원문 설치·8건 기장 등록은 아직 실행하지 않았다. 보호 사본에서만 항공료8건6500202원 신규 기장→유효board14건6767151원 예행을 확인했다. 실제 수입은 숫자13행+빈합계1행=14행,17337200원 잠정 합계다.
- 전체 실행 기록·중복 실행 방지 PID·검수 결과·정확한 다음 명령·원본 경로·보호 경계는 해당 작업공간의 Git 제외 파일 `.local-archive/accounting-deploy-20261116/HANDOFF-CGPFLIX232.md`와 `checkpoint.md`에 보존했다. 기존 root/다른 세션 변경은 보존했다. 이 절은 저장·인계 상태이며 금융 반영 완료 선언이 아니다.

# 2026-11-17 — 몽골 실제 기장·수입 표시 보완 진행

- 앞선 운영 코드 배포는 금융 반영 완료가 아니었다. 원문 조사에서 확인한 몽골 항공료 8건은 운영 ledger/board에 없었다. 공급자 파서 밖의 보관 원문 검수 결과를 원본 SHA·카드 원천 해시·날짜/금액 다중집합·실제 여행기간으로 검증해 기존 미기장 복구와 표준 기장 worker에 전달하도록 보완했다. [절차](playbooks/reviewed-bookings.md).
- 운영 보호 사본에서 현재 Rust 바이너리로 8건·6,500,202원 신규 기장과 board 14건·6,767,151원, 카드 원문·금액·날짜 불변을 확인했다. 실제 운영 반영은 아직 하지 않았으며 신선 백업·복원과 독립 검수·공식 배포 뒤에 진행한다.
- Plush 수입은 내부 board 행만 읽어 Google 원장 13행을 누락했다. 기존 canonical source·여행 연결·열람 grant를 적용해 읽기 전용 projection으로 연결했다. 합계가 빈 행은 미확인으로 표시하고 수입·차액은 대사가 끝나기 전 잠정 금액임을 알린다. Google 원장은 수정하지 않는다.

# 2026-11-17 — 회계 대사 코드 운영 배포 완료

- **운영 반영 상태:** `50823317` 회계 대사·예약 복구·메일 범위·수입 구성요소 검증을 최신 main과 통합한 `8888230deb1a5bd09d826da7e66034e2091ba0a1`을 공식 배포했다. 이전 실제 SHA `41d8e8efde542b9611a1f8a83eea3861bcfaaa4e` → backend8752, 도구 exit0. 보호14표 불변·1876파일 blob불일치0·runtime SHA 일치·health/ready200·비인증 보호API401을 확인했다.
- **실행 원칙:** 구현사항은 표적 검사·영향 검사·독립 검수와 데이터 보호 게이트를 통과한 뒤, 승인된 `tools/deploy_verified_release.ps1` 절차로 운영 반영한다. 배포 전후 실제 SHA·보호 테이블·health/ready·비인가 경로를 확인하고, 금융 원본·Google 장부 쓰기는 별도 승인 없이는 실행하지 않는다.
- **검증/커밋:** `50823317` 구현, `fa2c2962` 영향 매핑, `8888230d` Rust 포맷 보완. 최종 공식 영향 Python1015+2subtests/Rust191·fmt/clippy/release build, 프런트78·타입·빌드 통과(skip0/known0). 독립 gpt-6.1-sol medium이 정확 배포 SHA를 APPROVE했다. CI 두 job은 해당 SHA의 결제 한도로 시작 전 차단됨을 annotation으로 확인했다. 기존 기준선 비교2건은 main과 동일 실패로 구분했으며 테스트를 완화하지 않았다.
- **데이터/완료:** 금융 apply·스키마 변경·Google 쓰기 없음. 읽기 전용 대사 database_changes=0. 코드 배포 시 card-flow.json 해시와 기존 바이너리 경로를 보존한 뒤 Rust 감독 `4dedee2e`에게 배포 소유권을 넘겼다. 감독이 같은 SHA의 `costcore-8888230d.exe`로 전환했고 Board/Worker 모두 rust writer/rust links·health/ready200을 재확인했다. 새 planner의 전환 후 대조는 원문7336건·Python/Rust대상4/4·목록밖차이0·PASS다. 연결 첫 창도 OTA7965/7965·환불486/486·목록밖차이0·PASS를 확인했고 감독이 소유권을 해제했다. 이번 회계 코드 운영 활성화와 검증은 완료다. 이후 배포는 두 Rust flags와 새 바이너리 경로를 보존한다. PR978에 코드·배포 결과를 함께 기록하며 문서 때문에 재배포하지 않는다. [검증 기록](agents/artifacts/accounting-release-20261117.md).

## 2026-11-17 00:26 — Rust 2차 연결 운영 전환·첫 창 대조 완료

- **요청/결과:** “전환 수행해”, “모두 진행해”의 남은 2차 전환 COMPLETE. 운영 코드 `8888230deb1a5bd09d826da7e66034e2091ba0a1`에서 Board·Worker 모두 `classification_writer=rust`, `links_producer=rust`를 적용했다. 회계 대사 수정까지 포함한 같은 SHA에서 빌드한 `D:/WebLedgerHost/bin/costcore/costcore-8888230d.exe`를 사용한다(SHA-256 `98433d9144447f4f153d86d73c1166c09fc5f4b1b02caa53487b36d121f76ca4`). 코드 공식 배포는 회계 감독이 수행했고, 이 세션은 게이트 검증과 스위치 전환을 맡았다.
- **실제 검증:** 전환 전 최종 C1 판정·연결 PASS, C2 185사례에서 Python plan+Rust 연결 및 Rust plan+Rust 연결 모두 Python 기준과 차이 0. C3 4DB 신선 백업·복원과 Python→Rust→Python 왕복의 연결 해시 동일 PASS. 전환 후 새 사본의 첫 창도 분류 7,336행·OTA 7,965/7,965·환불 연결 486/486, 두 그림자 exit0/PASS·목록 밖 차이 0. 두 역할 적용 기록·살아 있는 PID·릴리스 확인, health/ready 200·보호 API 401.
- **과거 차이/복구:** 과거 OTA 1,648건은 `individual_payment_evidence=false`가 빠진 수정 전 바이너리의 측정분이었다. `e2a43e10`의 원본 필드 덮어쓰기 보존이 이미 반영돼 새 패치는 하지 않았다. ExaOne low 작업자 조사·합성 검사를 재사용했다. 첫 관리 재시작은 종료 중 CIM 명령행이 null인 경합으로 실패해 원설정·Python 연결로 복구했고, 종료 확인 보완 후 같은 게이트로 재시도해 성공했다.
- **근거/경계:** `D:/WebLedgerHost/data/backups/links-rust-20261116/`의 `final-links.out.json`, `final-classification.out.json`, `final-fa2/c2-final.json`, `final-fa2/c3-final.json`, `switch-evidence.json`, `switch-first-failed.json`, `first-window/evidence.json`. `final-fa2/`는 보관 폴더명이며 그 안의 C2·C3 최종 결과는 내부 release_sha가 `8888230d`다. 백업 근거는 `c3-links-rust-20261116.json`. 추가 운영 스크립트는 독립 gpt-6.1-sol medium APPROVE. 고객 원문은 보호 호스트 경로에만 보관했고 config 변경은 `costcore_bin`·`links_producer` 두 키뿐이다. 금융 apply·Google 장부 직접 쓰기는 실행하지 않았다. 이번 승인 범위의 남은 전환·검사·차단은 없으며 배포 소유권을 해제했다.


## 2026-11-16 — Rust 미결 구현·합성 검사 완료

- **요청/범위:** “rust관령 미결작업 exaone 다수에게 위임하여 구현”. SPEC M3 / `design/m3-core.md` U12~14를 기준으로 완료된 과제를 재구현하지 않았다. 별도 `integration/rust-exaone-20261116`에서 최신 main `ee118935`를 보존했고 원래 root 사용자 변경·UI 라우팅·운영 서비스는 수정하지 않았다.
- **위임:** `opencode/exaone/k-exaone_v2.5` 3명, build/medium(high 조사 반복 후 조정), 합성 자료만 사용. 사전검사와 기준선 결함 수정은 작업자 완료물을 통합했다. 환불 작업자는 초안을 작성했으나 컴파일/검증이 지연되어 쓰기 소유권을 회수하고 감독이 완성했다. 중복 위임·유료 모델 전환은 없었다.
- **환불 배선:** 감독 Python `a55de0c6` + Rust CLI `056253df`. 실제 `apply_pairs`·`check_groups`·`scope_group`·비공개 `issue_group`을 소비한다. 금액/ID/원문은 응답 수정 대상이 아니며, 기존 Python 트랜잭션에서 묶음의 최종 권한 상실은 전부 롤백한다. 실바이너리 기존 골든53+게시/멱등/권한상실3 = **56 passed**, CLI4/core1 passed. Python 환불·기존 검사25 passed.
- **사전검사:** ExaOne `31feca83` → 통합 `a360f055`, 감독 경계 보완 `c391d415`. 표적25 passed/skip0. 실제 합성 fixture의 WAL 거부를 확인하고 원본 보존 후 별도 DELETE-mode 사본에서 최종 바이너리 READY(환불1=1·OTA1=1, 입력/설정 불변)를 확인했다. 운영 승인·실자료 비교·백업/복원 증거를 대신하지 않는다.
- **Python 기준선:** ExaOne `60492d7d` → `437125da`. Rust 부모 설정 상속으로 Python 기준까지 Rust를 호출하던 결함을 child 환경 고정으로 수정했다. 감독 실제 회귀1 passed, 작업자 shadow CLI8/fmt/clippy 통과. 부모 환경은 바꾸지 않는다.
- **OTA:** 기존 `e2a43e10`·`f5c91d95`가 과거 1,648건 측정 뒤 main에 반영된 사실을 확인했다. 감독 Rust 골든7 passed, 작업자 합성 differential9/9. 새 OTA 계산 코드 변경 없이 검증했으며 **실자료 1,648건의 최신 재측정은 미완**이다.
- **최종 검사 중 발견/보완:** 공식 영향 검사에서 기존 `manual_rows`의 row_id-only 구형 스키마 계약 2실패가 나왔다. origin/main과 성능 이전 코드에도 동일한 문제가 있어 성능 회귀가 아님을 확인했다. 담당과 소유권을 조정해 `8fbf60f0`로 원행 ID만 읽도록 보완했고, 새 red→기존 포함8 passed. 기존 테스트를 완화하지 않았다. 공식 재검사는 Python923/Rust191 passed·skip0/known0, build/fmt/clippy exit0. 독립 sol medium 코드 검수 APPROVE·표적42 passed. 최신 UI main 통합 뒤 실제 환불/Plush 교차 검사97 passed. [검증 근거](agents/artifacts/rust-exaone-validation-20261116.md)에 SHA와 한계를 기록했다. 최종 SHA 검수 판정은 동일 PR에 남긴다.
- **운영/남은 일:** Rust 전환·배포 없음. 다른 세션이 UI 기존 URL 연결/배포를 맡으며 현재 전달받은 운영 SHA는 `c77eaa2bcfd04d8a553122330ebbda914a78cef0`. UI main `d088e1cb`를 통합 `ddc22536`에 보존했다. 코드·합성 검증은 완료했고 PR 최종 검수/병합을 진행한다. C1/C2/승인①②·운영 전환은 별도 미완이다. graphify update는 CLI 미설치로 실행 불가했다.

# 2026-11-16 — 전체 회계 대사 경로 보강·전수 감사 도구

- **요청/범위:** 0712 몽골 누락을 계기로 전체 원문·기장·보드의 회계 불일치를 찾고, 같은 원인이 재발하지 않도록 코드·규칙을 보강했다. 운영 DB·Google 장부·고객 원문은 쓰지 않았다.
- **구현:** 완료 기간의 미기장 거래는 원문 해시와 실제 예약 이용기간이 일치하는 정식 예약 근거가 있을 때만 열린 여행으로 복구하도록 Python/Rust 판정 경로를 맞췄다. 전달 메일·소유자 증거 라벨의 과거 수집 범위를 보강했고, Google 수입 행의 예약금·잔금·추가금 구성요소 불일치를 합계 미검증으로 표시한다. `app/accounting_audit.py`와 `tools/audit_accounting_consistency.py`로 수동 교정 포함 원문·ledger·board 대사를 읽기 전용으로 수행하며 장부·보드 귀속 분리와 누락 원문 식별자도 보고한다.
- **커밋:** `50823317` (`fix: reconcile unrecorded bookings and audit projections`).
- **검사:** 신규·직접 영향 Python 24건 통과, Rust `plan_judgement` 5건 통과, 운영 `D:/WebLedgerHost/data/board.sqlite` 읽기 전용 대사 `database_changes=0`. 대사 집계는 원문 7,336건·기장 3,359건·보드 3,359건, 미기장 3,678건(완료기간 3,653·열린 기간 25), 귀속 차이 694건, 환불 원문 확인 필요 109건이다. 완료기간 미기장 대부분은 과거 보호 경계에 속하므로 자동 기장하지 않았다.
- **검증 한계:** 기존 `webapp/tests/test_automatic_plan_refactor.py`의 합성 기준선 비교 2건은 현재 HEAD에 이미 존재한 예약근거 동작 차이로 실패했으며 이번 변경의 완료기간 복구 분기와 무관하다. 운영 재배포·금융 반영·Google 쓰기는 실행하지 않았다.
- **다음 작업:** 운영 반영 전 독립 검수와 승인된 배포 절차를 거친다. 재개 시 이 커밋의 표적 검사와 읽기 전용 대사를 먼저 재실행한다.

# 현재 상태

# 현재 상태

## 2026-11-16 — Plush UI 운영 배포 완료

- **현재 승인:** “모든 작업 재개하고 운영배포까지해”. [설계](design/m4-plush-ui-20261116.md)와 [실행 계약](agents/artifacts/plush-ui-implementation-contract-20261116.md)을 실행했다. 작업 폴더는 지정 `plush-ui-integration-20261116`, PR971이다. 원본 폴더의 사용자·성능 작업과 별도 Rust 후속을 혼합하지 않는다.
- **코드:** `a92c0b8773971d9abb71db131e070e46482c1f4f`. 전체 Plush 셸·여행/장부·거래·영수증·관리/보조를 실제 인증 API에 연결했다. Google·계정·규칙·항공권·참가자/예약·내보내기의 실제 계약/상태 오류와 누락을 보완했다. OTA 예약 교정·환불 원문·참가자 추가 교정은 명시한 기존 인증 업무 화면 접근을 보존하며 React 편집으로 새로 이식했다고 주장하지 않는다.
- **검사:** 전체 프런트72건/13파일·타입·빌드 통과. 마지막 영향45건, 그 전173건/565건+26subtests/778건+35subtests 모두 실패0/skip0/exit0. 이전 broad의 간헐 실패1건과 현재/main 재실행은 [검증 기록](agents/artifacts/plush-ui-validation-20261116.md)에 별도 보존했다. 독립 sol medium의 발견 사항을 수정하고 정확 배포 SHA 승인 후 전환했다.
- **브라우저:** 합성 영수증 복귀/응답 유실/충돌/원자 반영·PDF/키보드/모션 감소/320~1440px, 실제 XLSX ZIP 다운로드, 계정 승인→연결→해지 오류0, 마지막 참가자/예약/항공권390/1440px 넘침0 확인. 기존공간53이 닫혀 Task54를 사용했고 사용자 공간44는 보존했다. 실제 기기·스크린리더·실사용 paint 성능은 한계를 구분한다.
- **운영 완료:** 독립 `gpt-6.1-sol medium`이 정확 SHA `eacc3bc73104425202cfeece0ec52e6b4e1b7aa8`를 APPROVE했다. 공식 `deploy_verified_release.ps1` exit0, `1f436426`→`eacc3bc7`, backend8752·runtime SHA 검증, 1858파일 blob 불일치0·보호14표 불변·health/ready200·비인증 API401. 로그인 운영 UI/영수증/Google/계정 화면은 오류·넘침0, bootstrap/글꼴200. JS·CSS·HTML3개 모두 운영 응답과 릴리스 SHA-256 일치. 비로그인 curl은 `/ui/`·bootstrap401, Python urllib은 edge403으로 구분했다. 고객 값·운영 화면 캡처·금융 apply 없음. [운영 기록](operations.md)과 [검증 기록](agents/artifacts/plush-ui-validation-20261116.md)에 근거를 남겼다.
- **통합/남은 일:** 기능·운영 요청 COMPLETE, 별도 구현 차단 없음. 배포 결과 문서만 같은 PR971에서 독립 검수·병합한다. 문서만을 위한 재배포는 하지 않는다. 별도 Rust 작업은 포함하지 않았으며 다음 배포 PreviousSha는 다른 전환이 없으면 `eacc3bc7`이다.
- **보호/복구:** 고객 원문·수동 교정·Google 자동 쓰기 금지 유지, 실제 금융 apply 미실행. `.agents/plush-integration-checkpoint.json`과 단계별 `quality-*` 근거 보존. graph.json/CLI가 없어 graphify update는 명령 미발견으로 실패했다.

## 2026-11-16 21:05 — 영수증 기본 Terra high·선택 모델 동적 표시 운영 완료

- **최신 요청:** Claude 대신 `codex/gpt-6.1-terra` high를 기본으로 하고 선택 모델을 UI에 동적으로 표시한다. catalog의 기본값·모델별 실제 추론 수준으로 초기 선택과 버튼/상태를 표시하며, 기존 작업은 저장된 provider/model/thinking을 보존한다. 목록 로딩 경쟁·새로고침은 분석을 자동 실행하지 않는다.
- **실제 판독:** 합성 사진으로 Terra high start→스키마 검증 완료→새 bridge에서 동일 handle 복구→archive 성공, tool event 0, 금융 apply 없음. Claude 로그인 차단은 새 기본 경로의 차단 사유가 아니다. 근거 `.local-archive/receipt-terra-20261116/live-summary.json`.
- **실행 보호:** 일반 Codex 설정을 바꾸지 않는 영수증 전용 Paseo alias와 로컬 launcher를 추가했다. 구독 인증·OpenAI provider를 강제하고 파일/셸/웹/MCP/플러그인/다중 에이전트 도구를 끈다. native config/read 예행에서 기존 MCP 항목이 실제 비활성화됨을 확인했다. 단순 read-only를 도구 차단으로 취급하지 않는다.
- **실행 결함 수정:** SDK의 workspaceId는 기존 작업공간 참조이므로, 임의 ID를 만들던 대신 daemon이 반환한 작업공간 ID와 경로를 검증해 보존한다. 기존 불확실 실행은 재전송하지 않는다. SDK config의 options 필드로 native 제약을 전달한다.
- **완료 코드/검사:** `7ee0b311`·`1f43642605e72794452b71e38337829a9983c202`, PR [#973](https://github.com/6Soo/cost/pull/973)(병합 `dd1d005d`). 표적 **51 passed**, 기준 영향 **524 passed +26 subtests**, 최종 보완분 영향 **83 passed**, 모두 실패0/skip0. Rust costcore release build 통과. 최종 SHA 독립 `gpt-6.1-sol medium` APPROVED, 독립 회귀3건 통과. GitHub 두 job은 결제 한도로 시작 전에 실패했으며 실제 검사 실패를 우회한 것이 아니다. 검사는 중복 합산하지 않는다.
- **운영:** 공식 배포 exit0, `11267cd0`→`1f436426`, Board8751·Worker·core writers 전환 확인. 릴리스1,767파일 blob불일치0, 보호14표 불변, 금융 apply 없음. 추가 점검 health200(0.073초)·ready200(0.006초), 비인증 영수증3경로401. 운영 릴리스의 catalog에서 Codex/Terra/high/selectable=true와 동적 UI 소스를 확인했다. 스키마·고객 자료 변경 없는 코드 배포여서 full-backup 옵션은 사용하지 않았다.
- **마무리/범위:** 이번 요청은 COMPLETE이며 남은 차단 없음. 실제 로그인된 브라우저 재검수는 사용자 제어 TaskSpace44를 보존해 미실행했으며, 동적 선택·이력·새로고침은 합성 JS 실행으로 검증했다. React 화면 변경은 별도 Plush 감독이 같은 DTO 계약으로 통합 중이다. 검사 근거는 `.local-archive/receipt-terra-20261116/`에 보존했고 검증 workspace/임시 검증 branch는 공식 archive 후 정리했다. 사용자·성능 세션 변경과 기존 영수증 결과는 보존했다. graphify CLI·graph.json 부재로 그래프 갱신은 미실행이다.

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
