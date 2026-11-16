# 운영 기록

## 2026-11-17 — M3 추출기 기준 출력 생산 (읽기 전용, 운영 배포 없음)

- **실행:** M3 마지막 산출물(설계 §3.4 facts 기준 출력)을 origin/main `750e4a65aea5f5603fc04199046d5e64e8a7e45c`(PR980) detached worktree `C:/AX/cost-m3-baseline`에서 `python -I tools/core_bridge/cli.py extract-baseline`으로 생산했다. `ok=true`·python_sha `750e4a65…`·input_digest `1e9613ebe30aacde13a647de81d9f662d03939d2909764f9621b273f45539f7b`·**events 7,965건**·**baseline sha256 `a26d446510faabe4cbdfd5d8cf114b0903e6b87b8453fdb3380d529e605cbaf6`**. events.json 28,637,104B·stderr 0B. 디스크 해시==보고 해시·건수 7,965 일치 독립 검증.
- **보호/원본 불변:** 고객 기준 출력은 `D:/WebLedgerHost/data/backups/extractor-baseline-main-20261117/events.json` 보호 경로에만. 입력은 라이브 아닌 완전 스냅샷 사본(1,761,828,864B)이며 `is_live=false`로 라이브 무접근. 라이브 `D:/WebLedgerHost/data/ota-evidence.sqlite`는 같은 크기·2026-11-15 23:20 불변 → 스냅샷==보존 원본. 운영 DB·금융·Google 장부 쓰기 없음, 운영 포트(8751/8752/8790) 접근 없음. 이전 시도 `extractor-baseline-20261117/`는 response 0B(중단)로 성공 생산은 main 디렉터리뿐.
- **canonical/검사:** `app/ota_payments.py` root·main·worktree 바이트 동일, 의존 16모듈은 PR980 변경 9파일 밖. 표적 `tests/test_core_bridge_extract_baseline.py` 8 passed. 도구 4파일+기록을 main 기반 브랜치 커밋(병합·배포는 별도 게이트, 읽기 전용 생산이라 운영 반영 불필요).
- **근거/인수:** [생산 기록](agents/artifacts/m3-extractor-baseline-20261117.md), 보호 디렉터리 `request.json`·`response.json`·`events.json`·`stderr.log`. 이 고정값이 M6 Rust 추출기 병합 수락 기준표. 매일 Python 대조는 M6까지 회귀 안전망(주기 축소 소유자 결정 전 유지). 고객 원문은 Git·보고서에 넣지 않았다.

## 2026-11-17 03:05 — Plush UI 전수 감사 수정 운영 배포 완료

- **배포:** 공식 도구 exit0, actual `4cd76d2b05231f1197fbe5c94ffa99ffea1081b6`, Previous `9af204148b1b6450f7bb9c6ec1185c5f2f3aa852`, continuous 모드 backend 8751→8752·gateway8790. 추적1885파일 blob불일치0·dist 3파일 복사 전후 SHA-256 일치·runtime SHA verified·listener1·보호14표 전환 후 불변·health/ready200·비인증 보호API401. 금융 apply NOT_RUN·마이그레이션·Google 자동 쓰기 없음. code-only라 full-backup 옵션 미사용(이전 릴리스 자산 보존).
- **후보/검수:** 검수 PASS한 UI(`b7308aee`→`fe773fe8`, 13건 수정)+정책 문서 `90da8c42` 위에 PR980 main(`750e4a65`)을 clean merge한 `4cd76d2b`. 부모 변경 파일 교집합 없음·UI는 fe773fe8과 동일·PR980 소득표시/원문기장경로·백엔드/Rust/설정은 main 및 운영9af와 동일. 독립 gpt-6.1-sol medium 정확 SHA PASS(MEDIUM0·LOW 비차단 문구1). 후보 HEAD에서 npm ci·typecheck·build, 전체 vitest 17파일88테스트, 영향검사 Plush Python45 통과. 검수자 독립 재실행 5파일24테스트.
- **자산/화면:** 릴리스 dist 온디스크 해시3파일 release-audit 일치. 비인증 `/`·`/ui/`·자산·폰트 401(인증 활성). 인증 화면 렌더링은 로그인 필요로 미수행(인증 우회 금지) — 익명 거부와 감사 당시 로컬 합성 프리뷰 렌더링을 구분.
- **정책/조율:** 소유자 결정 2026-11-17 "혼자 개발·관리 레포는 검수 PASS 후 언제나 배포"를 `AGENTS.md`에 명시(`90da8c42`). 회계감사 후임 Accounts AGY(`20acee6b`) 기장 완료·소유권 해제 후 배포. PR979 병합 `10b2a39d`(main 트리=배포 후보 트리).
- **근거:** `D:/WebLedgerHost/releases/deploy-evidence-4cd76d2b05231f1197fbe5c94ffa99ffea1081b6.json`·`release-audit-4cd76d2b….json`, 작업공간 `.local-archive/plush-ui-audit-20261116/deploy-4cd76d2b/`의 review-evidence·protection-before/after·stage_release·verify_deploy·PR_DEPLOY_COMMENT. 고객 원문/화면은 Git에 넣지 않았다. 문서 후속 때문에 재배포하지 않는다.

## 2026-11-17 02:31 — 몽골 항공료 실제 기장·수입 표시 완료

- **배포:** 공식 도구 exit0, actual9af204148b1b6450f7bb9c6ec1185c5f2f3aa852, Previous8888230deb1a5bd09d826da7e66034e2091ba0a1, backend8751/gateway8790. 1883파일 blob불일치0·코드배포 보호14표 불변·health/ready200·보호API401. Board/Worker Rust/rust·기존costcore-8888230d.exe·card-flow.json 해시 보존. 배포 도구의 financial_apply=NOT_RUN은 코드 배포 단계만 가리킨다.
- **안전 게이트:** 신선4DB 백업/복원 exit0·원본/범위 밖 불변·복원 binding 동일. 첫 설치가 프로세스 임대 기록 변경(rule_process_leases2351→2354)을 감지해 원문/큐 설치 전에 중단됐다. 게이트를 완화하지 않고 postdeploy board/core 백업/복원을 새로 통과했다. 범위 밖 OTA/원본 폴더 불변. 독립 승인된 설치 스크립트를 배타 lock 아래 실행해 보호 원문과 정확8건의 기존 queue_batch만 등록했다. 직접 금융 SQL 없음.
- **금융/화면:** 기존 worker가 전체 근거 대조 후 항공료8건6500202원을 표준 기장(recorded8/failures0/pending0). ledger/board 각각 정확1회·귀속/이용기간/원문 해시 일치. 유효 몽골 보드14건6767151원. 원본·수동·대상 밖 금융/core 결정·나머지 보호표 불변. 같은8건 큐 재처리 후 모든 보호 금융표와 core 전체 상태 동일. 실제 인증 브라우저 지출14건/항공료8건과 수입14행17337200원·미확인1·잠정 안내 확인. 수입390/1440px 가로넘침0. 차액10570049원은 잠정이며 Google 최종 장부 쓰기0.
- **검사/근거:** 정확코드9af 공식1101+30subtests/skip0·frontend79/type/build PASS, gpt-6.1-sol medium 독립 APPROVE. CI 결제 한도 차단은 실제 annotation 확인. 보호 호스트 data/backups/reviewed-mongolia-20261117/의 백업·기장·재처리·실제 화면 증거와 releases/deploy-evidence-9af204148b1b6450f7bb9c6ec1185c5f2f3aa852.json에 저장했다. 고객 원문/화면은 Git에 넣지 않았다. [상세 기록](agents/artifacts/reviewed-booking-income-20261117.md), PR980. 문서 후속 때문에 재배포하지 않는다.

## 2026-11-17 00:26 — Rust 2차 연결 전환 및 최종 바이너리 활성화

- **실행:** 회계 감독의 공식 코드 배포 `8888230deb1a5bd09d826da7e66034e2091ba0a1` 완료·소유권 해제 후, 같은 릴리스에서 costcore release 빌드. `costcore_bin`을 `D:/WebLedgerHost/bin/costcore/costcore-8888230d.exe`(SHA-256 `98433d9144447f4f153d86d73c1166c09fc5f4b1b02caa53487b36d121f76ca4`)로 고정하고 `links_producer=rust` 적용. 기존 `classification_writer=rust` 유지. 공식 배포와 같은 배타 잠금 아래 사전 `--check` 통과 후 Board·Worker 관리 재시작, 두 역할 release888·Rust/Rust 적용 및 `--verify-applied --require-worker` 확인. 운영 backend8752/gateway8790, health/ready200·비인증 보호API401.
- **게이트:** 전환 전 최종 C1 판정·환불·OTA PASS/목록 밖0. C2 185사례에서 Python plan+Rust 연결 및 Rust plan+Rust 연결 모두 Python 기준과 차이0. C3 `c3-links-rust-20261116.json`은 board/core/OTA evidence/review 4DB 백업·복원·live/out-of-scope unchanged PASS. 사본의 Python→Rust→Python 왕복도 환불·OTA 해시가 모두 같았다. 추가 harness/전환 스크립트는 독립 gpt-6.1-sol medium 검수 APPROVE.
- **첫 창:** 전환 후 신선4DB 사본·OTA 입력 포착 뒤 분류 `shadow` 7,336행 PASS/unlisted0, `shadow-links` OTA7965/7965·환불486/486·private_details0·types[]·unlisted0, 두 명령 exit0. 회계 planner Rust 변경도 새 바이너리로 활성화됐다.
- **실패/복구:** 첫 재시작은 종료 중 CIM 프로세스의 null 명령행 조회로 실패했다. 원설정 복귀·Board/Worker Python 연결 적용·health/ready200을 확인했고, null 프로세스 종료 대기를 보완해 재시도 성공했다. 첫 실패를 성공으로 집계하지 않았다. 과거 OTA1648건은 `e2a43e10` 수정 전 측정분으로 확인돼 새 소스 패치·추가 PR은 만들지 않았다.
- **근거/보존:** `D:/WebLedgerHost/data/backups/links-rust-20261116/`의 `final-classification.out.json`, `final-links.out.json`, `final-fa2/c2-final.json`, `final-fa2/c3-final.json`, `switch-evidence.json`, `switch-first-failed.json`, `first-window/evidence.json` 및 상세 파일. `final-fa2/`는 보관 폴더명이고 최종 검사 내부 release_sha는888이다. 추가 검수·실행 스크립트는 `.local-archive/rust-links-cutover-20261116/`에 보존. 카드 원문·금액·부호·ID·수동 교정 보호 유지, 금융 apply·Google 장부 직접 쓰기 없음. 운영 소유권 해제. 이후 PreviousSha는 다른 배포가 없으면 `8888230deb1a5bd09d826da7e66034e2091ba0a1`이며 두 Rust 스위치·바이너리 경로를 보존한다.

## 2026-11-17 00:14 — 회계 대사 보강 코드 운영 배포 완료

- **상태/실제 SHA:** 회계 대사·완료기간 예약 복구·메일 수집·Google 수입 검증 보강을 `8888230deb1a5bd09d826da7e66034e2091ba0a1`로 공식 배포했다. PreviousSha는 직전 실제 `41d8e8efde542b9611a1f8a83eea3861bcfaaa4e`, backend8752·gateway8790. `tools/deploy_verified_release.ps1 -Apply` exit0, 기록 시각 `2026-11-16T15:13:59Z`.
- **반영 원칙:** 구현사항은 표적/영향 검사와 독립 검수, 보호 데이터 게이트를 통과한 뒤 `tools/deploy_verified_release.ps1`로 운영 반영한다. 배포 전후 실제 SHA·보호 테이블·health/ready·비인가 경로를 확인한다. 금융 원본과 Google 최종 장부에는 별도 승인 없이 쓰지 않는다.
- **게이트/운영 smoke:** 추적1876파일 blob불일치0, frontend3파일 복사 전후 SHA-256 일치, runtime SHA verified, listener1, 보호14표 내용/스키마 불변. health/ready200·보호API401. 추가 비인증 `/`·`/ui/`·bootstrap·영수증 모델API401; health0.056초·ready0.007초. 금융 apply NOT_RUN. 인증 브라우저 UI 재검수는 UI 변경 없는 배포이므로 미실행했다.
- **검증/복구:** 정확 SHA 독립 gpt-6.1-sol medium APPROVE, 공식 영향 Python1015+2subtests/Rust191 통과·skip0/known0, fmt/clippy/build 통과, frontend78·타입·빌드 통과. 첫 영향 검사의 Rust fmt 실패를 수정 후 전체 재검사했다. 기존 refactor 비교2건은 현재 main과 동일 결과/digest의 실패로 별도 보존했다. CI는 결제 한도로 시작 전 차단, 실제 검사 실패를 우회하지 않았다. Rust 감독의 선행 scoped4DB 백업/복원 검증과 writer 보류 인계 후 배포했으며, 도구의 fresh_backup_restore=false는 code-only 배포의 full-backup 옵션 미사용을 뜻한다.
- **근거/후속:** `D:/WebLedgerHost/releases/deploy-evidence-8888230deb1a5bd09d826da7e66034e2091ba0a1.json`, 같은 위치 release-audit 파일, 작업공간 `.local-archive/accounting-deploy-20261116/`의 최종 검사·검수·보호·config 해시·deploy.log. 코드 배포 시 card-flow.json·기존 바이너리 경로 불변과 rust writer/python links 정합성을 확인했다. 이후 소유권을 받은 Rust 감독이 `costcore-8888230d.exe`(SHA-256 `98433d9144447f4f153d86d73c1166c09fc5f4b1b02caa53487b36d121f76ca4`)와 rust links로 전환했다. 두 서비스의 SHA/설정 정렬·health/ready200 및 planner 첫 창 원문7336·대상4/4·목록밖차이0·PASS를 재확인했다. 첫 재시작은 CIM 종료중 null 조회로 원설정 복귀 후 대기 보완·재시도 PASS였다. 연결 첫 창도 OTA7965/7965·환불486/486·private_details0·types空·목록밖차이0·PASS이며 감독이 운영 소유권을 해제했다. 근거 `D:/WebLedgerHost/data/backups/links-rust-20261116/switch-evidence.json`과 `first-window/{evidence,shadow.out,shadow-links.out}.json`. 이후 배포에서도 두 Rust flags와 새 바이너리 경로를 보존한다. [검증 기록](agents/artifacts/accounting-release-20261117.md), PR978에서 결과 문서 통합 후 재배포하지 않는다.

## 2026-11-16 22:01 — Plush UI 운영 배포 완료

- **실제 SHA:** `eacc3bc73104425202cfeece0ec52e6b4e1b7aa8` (이전 `1f43642605e72794452b71e38337829a9983c202`), backend8752. 정확 SHA 독립 `gpt-6.1-sol medium APPROVE` 후 공식 `tools/deploy_verified_release.ps1 -Apply` exit0.
- **배포 게이트:** tracked1858·Git blob불일치0·runtime SHA verified·listener1·보호14표 내용/스키마 불변·health/ready200·비인증 보호API401. 금융 apply NOT_RUN. 스키마/금융 원본 변경 없는 코드 배포이며 full-backup 옵션은 사용하지 않았다.
- **근거:** `D:/WebLedgerHost/releases/deploy-evidence-eacc3bc73104425202cfeece0ec52e6b4e1b7aa8.json`, 같은 위치 `release-audit-eacc3bc73104425202cfeece0ec52e6b4e1b7aa8.json`; integration `.agents/deploy-eacc-v12/deploy.log`, `review.json`, `production-smoke.json`. JS/CSS/HTML3파일 운영 응답 SHA-256이 패키지와 일치했다.
- **운영 읽기 전용 smoke:** 로그인 브라우저 `/ui/`·영수증·Google·계정 화면 main/heading/nav 정상·오류 알림0·가로 넘침0. bootstrap/ready/글꼴200. 비로그인 curl UI·bootstrap401; urllib 요청은 edge403이어서 인증 결과와 구분했다. 운영 고객 값·화면 캡처·고객 장부 apply·Google 쓰기는 미실행.
- **검사/통합:** 프런트72/13파일·타입·빌드, 최종영향45/skip0/실패0 및 선행 범위별 검사 근거는 [검증 기록](agents/artifacts/plush-ui-validation-20261116.md). CI 두 job 시작 전 결제 한도 차단은 정확 SHA annotation으로 확인했고 승인된 독립 검수 예외를 적용했다. 결과 문서는 같은 PR971에서 검수·통합하며 문서 때문에 재배포하지 않는다. 배포 소유권 해제·별도 Rust 감독에게 actual SHA 전달 완료.
- **제한:** 자동화 paint 목표200ms 미달, 실기기·스크린리더 실청취 미검증. OTA/환불/참가자 일부 교정은 기존 인증 화면 링크 보존 범위다.


## 2026-11-16 21:05 창 — 영수증 Terra high `1f436426` 운영 배포

- **전환:** PR [#973](https://github.com/6Soo/cost/pull/973), 검수 코드 `1f43642605e72794452b71e38337829a9983c202`, 병합 `dd1d005d`. 공식 `tools/deploy_verified_release.ps1` exit0, PreviousSha `11267cd012e074a0b89d28adb93a4dd736f64079`. Board8751·Worker 동일 릴리스, core writers VERIFIED, Gateway8790. 신규 분석 기본은 Codex 구독 Terra/high이며 UI는 선택 모델·추론 수준과 저장된 작업의 실제 실행값을 표시한다.
- **실행 설정:** 일반 Codex를 유지하고 전용 `cost-receipt-codex` alias만 좁은 config RPC로 등록했다. 안정 launcher는 Windows 사용자 LocalAppData의 `Cost/receipt-paseo/launcher/receipt_codex_launch.mjs`이며 Git 릴리스와 동일 바이트임을 확인했다. API endpoint/key 상속 차단, ChatGPT 구독/OpenAI 강제, 도구 feature·상속 MCP 차단을 native config/read로 확인했다. daemon을 재시작하거나 인증 파일을 직접 변경·복사하지 않았으며 추가 과금 경로를 사용하지 않았다.
- **검증/안전:** 표적51, 기준 영향524+26subtests, 최종delta83 모두 실패0/skip0. 정확 SHA 독립 sol medium APPROVED(독립3건). 실제 합성사진 Terra/high 판독·스키마 검증·동일 handle 복구·archive 통과, tool event0. 릴리스1,767파일 불일치0·runtime SHA verified·보호14표 불변·financial apply NOT_RUN. 스키마/금융 변경 없는 코드 배포로 full-backup 옵션은 사용하지 않았다. CI는 정확 SHA의 두 job이 billing 한도로 미시작임을 확인했다.
- **전환 후:** 공식 health/ready200·기존 비인증API401. 별도 smoke health200(0.073초), ready200(0.006초), `/receipts`·모델목록·workflow401. 운영 릴리스에서 별도 CODEX_HOME 환경 없이 catalog의 Codex/Terra/high/selectable=true와 동적 UI 소스를 확인했다. 로그인된 브라우저 재검수·고객 영수증 장부 반영·Google 쓰기는 하지 않았다.
- **근거/다음:** `D:/WebLedgerHost/releases/deploy-evidence-1f43642605e72794452b71e38337829a9983c202.json` 및 `continuous-switch-1f43642605e72794452b71e38337829a9983c202.json`, `.local-archive/receipt-terra-20261116/`의 broad-quality·delta-quality·final-review.md·live-summary.json·native-config-evidence.json·candidate-catalog.json·production-smoke.json·deploy.log. Plush 감독에게 완료를 통지하고 배포 소유권을 해제했다. 다른 배포가 없으면 다음 PreviousSha는 `1f436426`이다.

## 2026-11-16 20:14 창 — 영수증 `11267cd0` 운영 배포

- **전환:** PR [#970](https://github.com/6Soo/cost/pull/970)·[#972](https://github.com/6Soo/cost/pull/972). 검수된 코드 SHA `11267cd012e074a0b89d28adb93a4dd736f64079`를 공식 `tools/deploy_verified_release.ps1`로 배포, exit0. PreviousSha `77865bfadce7cc96336cf751d1dbd41964549388`. Board8752·Worker 같은 릴리스, Gateway8790, core writers VERIFIED. workflow=true를 원본 설정 백업 후 명시 활성화했다.
- **안전:** 릴리스1,764파일 blob불일치0, 보호14표 배포 전후 불변, financial apply NOT_RUN. 별도 board/core 신선 범위 백업·복원 확인(최신11:10:57 UTC), 기존78표 불변/빈3표 추가 사본 예행 통과. 연속배포 도구 자체의 full-backup 플래그는 사용하지 않아 deploy evidence의 fresh_backup_restore는 false이며, 별도 백업/복원 근거를 함께 사용한다.
- **점검:** 공식 health/ready200, 비인증 기존API401. 추가 영수증 smoke health200(0.423초), ready200(0.045초), `/receipts`·`/api/receipts/paseo/models`·`/api/receipts/workflow`401. workflow 활성화·새 영수증3표 존재 확인. 합성 검사 broad1443+107subtests, 최종영수증delta217, 배포검사delta32 모두 실패0/skip0. 독립 최종SHA 검수 gpt-6.1-sol medium APPROVE. GitHub CI는 결제 한도로 job/step 미시작.
- **실패 이력:** 먼저 배포한 `e977e235`는 빈 receipt_evidence_links로 보호 표 수가13→14가 되면서 고정 개수 검사에 실패했다. 도구는 이전77865bfa/8751로 공식 rollback했고 health/ready200, 원래13표 동일/추가표0행을 확인했다. 11267cd0에서 필수 identity·기존 표 해시를 유지하고 명시 승인된 빈 추가만 허용하도록 수정해 재배포했다. 첫 전환 중 별도 health/ready8초 점검은 시간초과였으며 첫 시도를 성공으로 기록하지 않는다.
- **기능 제한:** Claude 구독 로그아웃으로 실제 모델 판독 성공은 미검증. catalog 연결은 확인됐지만 실행 선택은 차단된다. 로그인 복구 후 합성 사진으로 재검증한다. 사용자 제어 중 TaskSpace44는 조작하지 않았다. 운영 원본·수동 교정·Google 최종 장부 변경 및 Rust 전환은 수행하지 않았다.
- **근거:** `D:/WebLedgerHost/releases/deploy-evidence-11267cd012e074a0b89d28adb93a4dd736f64079.json`, `continuous-switch-11267cd012e074a0b89d28adb93a4dd736f64079.json`; `D:/WebLedgerHost/data/backups/receipt-deploy-retry-20261116-restore-evidence.json`; 로컬 `.local-archive/receipt-deploy-20261116/`의 broad-quality·delta-quality·guard-quality·독립검수2개·deploy-first-failed.log·deploy-retry.log·production-smoke.json. 다음 배포 PreviousSha는 다른 배포가 없으면11267cd0다.

## 2026-11-16 04:38·05:14 창 — `25966b21`·`77865bfa` 배포, 1차 전환 재측정 C1·C2 통과

- **배포 1단계(#963):** `e2164607` → `25966b217e243b5896a007453bd613594eefdb2d`(OTA 대사 시간 제한 1,800초 상향·동일 입력 실행 공유로 재판정 차단 해소), Board 8752, 보호 13표 불변, readyz 200, 릴리스 1,730파일 blob 불일치 0, 런타임 SHA 검증. 독립 검수 antigravity Claude Opus 4.6 Thinking(high) APPROVE — CI 결제 한도 미시작 예외, 표적 130건 재실행·영향 게이트 765건 확인.
- **C2 측정 실패와 회귀 수정(#964):** 첫 재측정(`c1c2-20261116/`)에서 C1은 통과했으나 C2가 증거 캐시 재빌드 중 `webapp/card_flow.py` stamps 정렬의 `None['path']` TypeError로 실패. 근본 원인은 회귀 `8c5e618d`(통합 OTA 저장소 WAL을 의도적으로 제외한 `content_stamp`의 None 반환에 인라인 정렬 필터 누락). 수정 `eae080e94cb0c4ca8a05e887d3a6a66cdacd4b80`(정렬 `if stamp` 필터 + 회귀 테스트 2건), 영향 게이트 532건 통과, 독립 검수 APPROVE(표적 115건+28 subtests 재실행).
- **배포 2단계(#964):** `25966b21` → `77865bfadce7cc96336cf751d1dbd41964549388`, Board 8751, 보호 13표 불변, readyz 200, 릴리스 1,731파일 blob 불일치 0, 런타임 SHA 검증.
- **재측정 통과(`c1c2-20261116b/`, 신선 사본 7,336행 quick_check ok):** C1 그림자 PASS — B↔C 차이 0, 목록 밖 0(A↔B·C 4행은 반영 전 계획, 11/15와 동일). C2 PASS — 185사례 Rust·Python 전부 동일(same 185, different 0), 과거 검수 교정 대조 일치 131·불일치 40(11/15와 동일)·원천 보호 not_rejudged 14, 증거 재빌드 443.8초·재판정 26.1초.
- **전환 상태:** 소유자 승인 ① 대기. `card-flow.json`에 전환 키 없음(Python 작성자 유지), 운영 `core.sqlite`는 11/15 생성분 유지. 승인 ① → C3 신선 백업·복원 확인·되돌림 예행 → 승인 ② → `costcore migrate`·전환 키 3개 추가·`core_switch_config.py --check`·Board/Worker 재시작·첫 창 대조([전환 절차서](playbooks/core-cutover.md)). 되돌림은 키 제거+재시작(Rust가 쓴 행 보존). 2차 전환(연결)은 OTA 목록 밖 차이 1,648건(11/15 측정) 해소 전까지 별도 보류.
- 근거: `D:/WebLedgerHost/data/backups/`의 `c1c2-20261116/`(첫 측정, C2 실패 로그)·`c1c2-20261116b/`(재측정 PASS), `D:/WebLedgerHost/releases/deploy-evidence-25966b21….json`·`deploy-evidence-77865bfa….json`, 검수 보고서 `C:/AX/cost-wt-ota-perf/.local-archive/review-963-70b7c759.md`·`review-964-eae080e9.md`.

## 2026-11-16 02:40 창 — `e2164607` 영수증 UI/UX 통합 배포

- **배포:** #961 병합 `e2164607c110d4c57240fec7b5c5a68e5d74ea95`를 `tools/deploy_verified_release.ps1`로 배포 완료 (Previous SHA: `aa803824b30737a97bc760c352c6cb8a897e6045`).
- **상태:** Board 8751, Worker 동일 SHA, Gateway 8790 정상 라우팅. `readyz` 200 OK (0.007초), 비인가 `/receipts` 401 Unauthorized 검증.
- **안전성:** 보호 13개 표 스키마 및 내용 불변(`unchanged: true`). 릴리스 패키지 1,726개 파일 대조 및 blob 불일치 0건.
- **영수증 기능:** R1~R11 UI/UX 개선 및 #957 여행 헤더 통합 완료. 분석 완료/재분석 시의 상태 문구 계약 정합성 보존 및 필수 브라우저 41건 통과.

## 2026-11-15 장애 창 — 장부 25초 지연, 색인, `f3051419`·`c36665ae` 배포, 1차 전환 되돌림

- **장애 측정(15:21 KST, 소유자 세션):** `/` TTFB 22~40초, 여행 탭 4~20초, `/cards/all` 10~37초. 기반 경로는 정상(백엔드 readyz 0.03~0.4초, 공개 0.5~1.4초). `/` 요청 하나가 Board에서 CPU 19.6초·읽기 2.95GB. 사본 프로파일로 `app/closed_period.py` `manual_ids`가 15.1초(색인 없는 `change_log`를 `review_decisions` 행마다 전수 조회)임을 찾았다. Rust 작성자·OTA 재계산·Defender는 원인이 아니었다(11/14 00:2x 전환 전에도 홈 502).
- **색인(장애 수정):** 범위 백업(board+core, 72초, 서버 무정지) 뒤 15:41:45 `idx_change_log_kind_subject ON change_log(kind, subject)` 생성(잠금 대기 0초, 0.051초, ANALYZE 안 함). 15:41 이전 백업으로 board를 복원하면 이 색인을 먼저 만든다(#942 이후 릴리스가 요구).
- **1단계 `f3051419`**(#929·#931~#935), 18:08:52 KST, 8751, 보호 13표 불변, readyz 10/10. 범위 백업(Board·Worker 정지 56.6초, 백업 40.2초, 18:15:12). `tools/core_rejudge.py --dry-run` 2회가 OTA 대사 자식 프로세스 900초 제한 초과(`OtaReconcileChildError`, 906·907초)로 실패해 재판정은 보류했다(쓰기 0, decisions 0).
- **2단계 `c36665ae`**(#930·#936~#946), 18:55:15 KST, 8752, 보호 13표 불변, readyz 10/10. #944 키 변경 스냅숏 재생성 18:55~19:04(570.6초). Board OTA 대사 1회 소요는 오늘 554~712초, 2회 900초 초과.
- **1차 전환 미적용 발견과 되돌림:** #928 키 처리는 저장소 `tools/launch_web_ledger.py`에 있으나 Board 작업은 호스트 `D:\WebLedgerHost\bin\launch_web_ledger.py`(10/30, 키 처리 없음)를 실행해 08:11 이후에도 Board는 Python 작성자였다(Worker만 Rust 설정). 전환 뒤 자동 분류 기록 0·decisions 0으로 작성자 혼합은 없었다. 19:08 `card-flow.json`의 세 키를 제거하고(원본 백업) Worker를 재시작해 두 프로세스 모두 Python으로 맞췄다. `core.sqlite`는 유지한다(범위 백업 core 포함 계속). 재전환은 배포 도구의 호스트 런처 갱신과 대사 900초 문제 수정 뒤에 한다.

| 화면 TTFB(3회) | 15:21 처음 | 색인 뒤 15:4x | 2단계 뒤 19:0x |
| --- | --- | --- | --- |
| `/` | 22.2·30.3·39.8초 | 21.8·19.6·21.8초 | 5.7·5.7·11.5초 |
| 여행 탭 | 19.5·14.5·4.2초 | 6.4·1.9·6.9초 | 14.4·3.4·2.7초 |
| `/cards/all` | 17.1·10.2·36.8초 | 26.2·15.2·16.9초 | 8.0·7.8·7.9초 |

- 근거: `D:/WebLedgerHost/data/backups/`의 `perf-20261115/`(sampler·index-fix·사본 프로파일), `deploy-f3051419/`, `deploy-c36665ae/`, `cutover-20261115/rejudge/`, `cutover-20261115/card-flow.json.before-*`.

## 2026-11-15 05:44·08:02 창 — `fda02183`·`ae121694` 배포, 1차 전환(P1 자동 분류 작성자 Rust)

- **05:44 창(정규):** `77edf137` → `fda0218369441b0ae23b0d7f0939331e2314dc45`(#922~#926), 05:47:06 KST, 8751, 보호 13표 불변, readyz 10/10. 첫 실행은 #923 검수 근거 누락으로 시작 전 멈췄다(변경 0). 작업 우선순위 Normal(4)을 이 재시작부터 적용했다(Board·Worker 확인). 1차 전환 5단계는 Board 전용 환경 변수 장치가 없어 보류했다(전역 변수 미사용, #928로 해소).
- **08:02 창(소유자 예외 승인):** `fda02183` → `ae121694c21eb25f2656cfe05012d4680998cb56`(#925·#927·#928), 08:04:26 KST, 8752, 보호 13표 불변, readyz 10/10. `costcore` 빌드 1.2분, 바이너리를 `D:\WebLedgerHost\bin\costcore\costcore-ae121694.exe`로 고정(sha256 `EFEAA754…8BAD`). Gateway 재시작으로 Normal 적용, 로컬 준비 응답 끊김 2.1초.
- **1차 전환(소유자 승인 ①·②):** C3 신선 board 백업·복원 동등(78표, quick_check ok). 08:10:32 `costcore migrate`로 운영 `core.sqlite` 생성(버전 0→2, 이때부터 #906 범위 백업에 core 포함). `card-flow.json`에 `classification_writer=rust`·`costcore_bin`·`core_db` 추가(원본 백업, BOM 없음), `core_switch_config.py --check` ok 확인 뒤 Board 재시작(준비 응답 끊김 14초), Worker 재시작(거부 없음). `links_producer`는 넣지 않았다.
- **전환 직후 대조:** ① A↔C decisions 0·불일치 0(전환 뒤 Python 기록 0). ② 신선 사본 그림자 PASS(7,336행, B↔C 0, 목록 밖 0; A↔B 4행은 반영 전 계획). ③ 전환 뒤 `card.automatic_classification` 기록 0. 카드 완료 대기가 0건이라 첫 자동 분류 apply는 아직 없다. 첫 apply를 감시해 대조 ①~③을 자동으로 돌리고, 차이 1건이면 키 제거·재시작으로 Python에 복귀하는 감시를 24시간 띄웠다(`cutover-20261115/watch.log`).
- **확인하지 못한 것:** ④ `skipped_mismatch`는 운영에서 볼 수 없다(`app/core_writer.py`가 Rust 응답의 `result`만 돌려주고 `written`·`skipped_mismatch`를 버림). Rust와 Python은 같은 종류·요약으로 `change_log`를 쓰므로 ③은 "전환 뒤 자동 판정 행이 모두 core decisions에 있는가"로 판정한다.
- 되돌림: `card-flow.json`의 `classification_writer`(와 `costcore_bin`·`core_db`) 제거 → Board·Worker 재시작. Rust가 쓴 행은 지우지 않는다.
- 근거: `D:/WebLedgerHost/data/backups/`의 `deploy-fda02183/`, `deploy-ae121694/`, `cutover-20261115/`(gateway-restart·board-restart·migrate·c3·verify-baseline·watch 로그, card-flow.json.before), `task-priority-20261115/`.

## 2026-11-15 창 — `77edf137` 배포, #905 인덱스 장애 수정, 전환 측정 C1·C2

- **창 보호:** 01:29:46~01:47:41 mail-collect 제외(`worker.json` 일시 변경, 원본 복원 확인). 창 종료 재시작에서 이전 Worker가 아직 잠금을 쥐어 새 Worker가 `ALREADY_RUNNING`으로 거부돼 01:48~01:52 Worker가 멈췄다(재시작 스크립트에 이전 Worker 종료 대기를 추가함).
- **배포** `060a7239` → `77edf137460f865182e17f327b6753f88353a288`(#887~#921 범위, #905 OTA 근거 중복 기록 중단 포함): 01:34 첫 시도는 `PREPARED_SUPERVISOR_NOT_STARTED`로 자동 롤백(경로 pause 전, 공개 중단 0, CPU 91~100%). 재시도 01:40:25 성공, 8752, 보호 13표 불변, 배포 뒤 5분 readyz 10/10. `costcore` release 빌드 3분 16초(빌드 폴더 `D:\cargo-target\release-77edf137`, 운영 스위치는 켜지 않음, 운영 `core.sqlite` 미생성).
- **mail-collect 30분 제한 초과와 인덱스 장애 수정:** 실행 소요가 11/14 저녁 210~540초 → 22:08·23:11 1,080·1,291초 → 00:20·01:22(배포 전)·02:25·03:30 시간 초과(1,800초)로 늘었다. 02:25 실행은 #905 인덱스 생성 도중 종료돼 인덱스가 없었고(WAL 93→194MB), 그동안 근거 DB 읽기가 최대 65초 막혔다. 헤드 지시로 02:38~02:58 Worker를 멈추고(mail-collect 제외, Board 무관) 근거 DB 사본(backup API, quick_check ok)을 만든 뒤 두 인덱스를 만들었다: `ota_booking_evidence_fact_lookup` 27.76초, `ota_reservation_observations_lookup` 0.16초. 체크포인트 TRUNCATE는 같은 시간의 긴 읽기(측정용 평가 실행) 때문에 680초 뒤 busy였다. 원복 뒤 02:58:48 mail-collect도 03:30:55 시간 초과였다(인덱스 있음, 읽기 2.8GB·쓰기 0·CPU 53초). 02:25·03:30 실행은 측정 작업의 대량 읽기와 겹쳤다.
- **1차 전환 측정(신선 사본 `c1c2-20261115/`, 운영 쓰기 0):** C1 판정 그림자 PASS(7,336행, B↔C 차이 0, 목록 밖 0; A↔B·C 4행은 아직 반영 전인 3820 카드 분기→여행 등). C2 PASS(평가 185사례에서 Rust·Python 결과 모두 같음, 일치 131, Python만 맞힌 사례 0).
- **2차 전환 측정(같은 사본):** 환불 짝 PASS(486=486, 목록 밖 0). OTA 연결 FAIL(사건 7,927, B↔C 차이 1,648: `RESERVATION_ONLY` 1,646·`HOLD_EVIDENCE_CONFLICT` 2, 목록 밖). 입력 포착 10.2분, 그림자 24.1분.
- **전환 차단 결함:** `tools/core_bridge/cli.py`의 `python_sha`가 `git rev-parse HEAD`라 운영 릴리스 폴더(Git 아님)에서 빈 값이 되어 `costcore` 다리가 `ENVELOPE_MISMATCH`로 실패한다. 측정은 같은 SHA의 Git 작업 폴더를 `--repo-root`로 써서 했다.
- 근거: `D:/WebLedgerHost/data/backups/`의 `deploy-77edf137/`(run.log, costcore-build.log), `ota-index-20261115/`, `c1c2-20261115/measure.log`, `window-guard.log`.

## 2026-11-14 3번째 창(소유자 예외 승인) — `060a7239` 배포, 부분환불 취소 4건, 3분기 붙여넣기 complete

- **배포** `edc85f72` → `060a7239a3b3f26da2507215a18a8c02f2407772`(#865~#886 범위, #886 완료 기간 자동기록 차단 포함), 13:23:07 KST, 8751, 보호 13표 불변, 배포 뒤 5분 readyz 10/10. 13:18 첫 시도는 경로 제어(`gateway_route.py`) 오류로 전환이 자동 롤백됐다(CPU 85~100%, healthz가 순간 5초 초과). 재시도에서 성공했다. #867(승인 `b5ea78d1`, head `a4802d99`), #876(조건부 승인 `2d95e312`, head `82ed7a73`, 헤드 범위 확인 병합), #872(검수 댓글 없음, 헤드 확인 병합)는 근거가 이 상태 그대로다.
- **파일 간 부분환불 취소 4건 기록**(묶음 기록 경로 `refund_cleanup_action._group_context` → digest 대조 → `pipeline.commit`, 전 배치 자동기록 미사용):
  - 1회차 정지 13:29:01~14:02:58: 첫 묶음 `3ce0cb3f3e0f`(취소 `131b5c3404aa`)만 기록한 뒤 Python이 출력 없이 끝났다. 같은 시간 다른 에이전트가 `Get-Process python | Stop-Process`를 실행했다는 보고가 있다.
  - 2회차 정지 14:05:00~14:50:07(백업 10.7분): 남은 3묶음(`8e0b0ad0f7a2`·`e2193dae1674`·`e52341713bab`)을 묶음당 1건 기록했다. digest는 사본 예행과 같다.
  - 합계: 장부 3,355→3,359, 화면 행 3,359→3,363, 거래 7,336건·revision 합 19,554 불변, 재미리보기 0. 귀속은 원결제 여행(3분기 여행 2, 4분기 여행 2)이다.
- **3분기 붙여넣기 묶음** `quarter-review-2026Q3/paste-pack-20261114-1450/`: 완결성 **complete**(exit 0), NO_LEDGER_ROW 0, 탭 합계 22/22, 보류 0. `--with-ota-evidence`는 장부 DB를 쓰기 가능으로 열므로 운영 DB의 backup API 사본(`paste-host-20261114-1450/`, quick_check ok, `ota-sources.json`을 사본 근거 DB로 재지정)에서 실행했다. 검증 근거로 채운 이용기간 44, 남은 공란 1,167(저장 기간 없음 1,163·근거 읽기 실패 4; 숙박비 173·항공료 23·분기 기타비용 333).
- #870 영향 관찰: 배포 뒤 15:10까지 3820 카드 10/15 구매 10건의 귀속 변화 0(카드 완료 Worker 대기 0).
- 근거: `D:/WebLedgerHost/data/backups/`의 `deploy-060a7239/`, `window-20261114-offline/`(run.log, partial2-*, q3820-*), `quarter-review-2026Q3/paste-pack-ota-20261114-1450.log`.

## 2026-11-14 1차·2차 창 — `8d0ba4cf`·`edc85f72` 배포, 3분기 구매 2·4분기 정정 15·AI 교정 77

- **1차 배포** `db848712` → `8d0ba4cfd2be4895250af9190059760ef5b68ad3`(#855·#857~#860·#862~#864): 전환은 01:39:04 KST PASS(8751)였다. 그 뒤 도구의 전환 후 검사가 실패해(기록 없음. 같은 시각 healthz가 14.8초라 8초 HTTP 점검 초과로 추정) `db848712` 롤백을 시도했고, 롤백은 01:39:48~01:41:49에 Python 오류로 실패해 후보를 되살렸다. 운영 담당이 같은 검사(health/ready 200, 비인증 API 401, 보호 13표 불변, 실행 SHA)를 다시 돌려 통과를 확인하고 `deploy-evidence`를 수동 검증으로 표시해 남겼다. 롤백 시도 중 경로 pause 구간은 측정하지 않았다.
- **1차 반영**(Board·Worker 정지, 경로 유지): 첫 시도 01:46:51~01:48:49는 백업 도구가 즉시 실패해 변경 0으로 복귀했다(원인 미확정, 정지 직후 남은 하위 프로세스 의심). 둘째 시도 01:53:26~02:35:54(약 42분), 단계별 백업 8.1·6.8·6.8분.
  - 3분기 구매 2건 → `quarter:2026:3`(AI 검수 판정, 항목 분기 기타비용·설명에 숙박비), digest `4890a94b…`·`a78306a7…`, 건별 기록 1·재실행 0.
  - 4분기 일괄 소유자 확인 표시 정정 15(제외 수동 18), digest `ab0a4f78…`, 재실행 반영 0.
  - 4분기 중간 AI 검수 교정 77(여행→여행 41·여행→분기 18·분기→여행 2·항목만 16), digest `aabdcdb7…`(검수자 미리보기와 같음), 재실행 반영 0.
- **2차 배포** `8d0ba4cf` → `edc85f72d6613644752735b6fe39b4e30eb25ea8`(#861·#868·#869), 02:39:43 KST, 8752, 보호 13표 불변, 배포 뒤 5분 readyz 10/10. #868은 opus REQUEST_CHANGES(`f92efe13`) 뒤 수정 `8cb058f2`를 헤드가 확인했고 재승인 댓글은 없다.
- **파일 간 부분환불 취소 4건: 반영 0.** 정지 02:45:20~03:21:38(약 36분, 백업 6.3분). 정지 사본에서 전 배치 자동기록을 돌리자 9개 배치에서 3,626개 거래의 장부가 바뀌어(2025년·완료 기간 포함) 기대 4건과 달라 운영 쓰기 전에 중단했다. #861 검수의 4건은 기준 코드와의 차이이고 이 경로의 절대 변경량이 아니다.
- **3분기 붙여넣기 묶음** `quarter-review-2026Q3/paste-pack-20261114-0322/`: 탭 합계 22/22, 보류 0, 완결성 `mismatch`(NO_LEDGER_ROW 2, 부분환불 취소).
- 근거: `D:/WebLedgerHost/data/backups/`의 `deploy-8d0ba4cf/`, `deploy-edc85f72/`, `window-20261114-offline/`(run.log, 단계별 preview·applied·replay·backup), `releases/continuous-switch-db848712….failure.json`.

이전 기록: [operations-through-20261113](history/operations-through-20261113.md)
