# 회계 대사 코드 운영 검증 — 2026-11-17

## 실행 범위와 상태

사용자 “반영해” 승인에 따라 `50823317` 구현을 최신 main과 통합해 운영 배포했다. 코드 배포·독립 검수·운영 smoke와 새 Rust planner 활성화는 COMPLETE, 금융 재처리·Google 쓰기는 미실행이다. 코드 배포 중 기존 Rust 바이너리 경로를 보존한 뒤 소유권을 받은 별도 Rust 감독이 같은 SHA 바이너리를 활성화했다. 해당 판정과 연결의 전환 후 대조도 PASS로 확인했다.

| 대상 | 실제 근거 |
| --- | --- |
| 배포 SHA | `8888230deb1a5bd09d826da7e66034e2091ba0a1` |
| 직전 SHA | `41d8e8efde542b9611a1f8a83eea3861bcfaaa4e` |
| 코드 | `50823317` 구현, `fa2c2962` 영향 매핑, `8888230d` Rust 포맷 |
| 독립 검수 | gpt-6.1-sol medium, 정확 배포 SHA APPROVE; 이전 실질 검수+최종 포맷 diff 확인 |
| 공식 영향 검사 | Python1015 +2subtests, Rust191, skip0·known0, fmt/clippy/release build 모두 통과 |
| 프런트 | 78 passed, typecheck/build 통과; 마지막 빌드는 최종 SHA에서 수행 |
| 릴리스 | Git archive 독점 생성, 추적1876파일 blob불일치0, dist3파일 SHA-256 복사 전후 일치 |
| 공식 배포 | deploy_verified_release.ps1 exit0, backend8752·gateway8790, runtime SHA verified |
| 데이터 보호 | 14표 내용/스키마 불변, card-flow.json SHA-256 불변, 금융 apply NOT_RUN |
| 운영 확인 | health/ready200, 보호API401, 추가 비인증 기본주소/UI/bootstrap/영수증 모델API401 |

## 실패와 검사 한계

처음 공식 검사는 새 파일4개 영향 매핑 누락으로 실행 전에 중단돼 매핑을 추가했다. 다음 검사의 Python/Rust 테스트와 clippy는 통과했으나 Rust fmt가 실패했다. cargo fmt만 반영한 최종 SHA에서 공식 검사를 다시 실행해 전부 통과했다. 실패 근거도 로컬에 보존했다.

`webapp/tests/test_automatic_plan_refactor.py` 별도8건 중2건은 실패한다. 독립 검수자가 현재 origin/main 구현으로 동일 합성 fixture를 실행해 같은 실패와 결과/digest를 확인했다. 후보 회귀와 구분하며, 전체 레포 모든 테스트 통과를 주장하지 않는다. 기존 테스트는 수정·삭제하지 않았다.

GitHub의 정확 배포 SHA 두 job annotation은 결제/사용 한도로 작업이 시작되지 않았다고 명시한다. 저장소의 독립 검수 예외를 적용했다. 실제 실패를 이 예외로 통과시키지 않았다. UI 소스는 최신 main 그대로이며 인증 브라우저 재검수는 수행하지 않았다. graphify CLI와 graph.json이 없어 update를 실행할 수 없었다.

## 원본 보존과 인계

운영 감사는 SQLite mode=ro/query_only/BEGIN으로 실행, database_changes=0. 고객 원문·금액·ID·수동 이력·Google 장부를 수정하지 않았다. 감사 결과의 누락·귀속 차이 집계는 자동 교정 완료 건수가 아니다.

배포 전 Rust 감독이 scoped4DB 백업/복원 검증(live_state_unchanged/restored_review_binding_equal/out_of_scope_unchanged=true) 완료와 배포 소유권을 인계했다. 배포 도구는 code-only로 실행해 full-backup 옵션은 사용하지 않았다. 배포 후 기존 rust writer/python links를 Board·Worker에 보존한 verify-applied가 통과했다. 실제 SHA·포트·보호 결과를 Rust 감독과 UI 세션에 통지하고 배포 소유권을 넘겼다.

후속 전환에서 감독은 `costcore-8888230d.exe`(SHA-256 `98433d9144447f4f153d86d73c1166c09fc5f4b1b02caa53487b36d121f76ca4`)와 rust links를 적용했다. 독립 읽기 전용 확인에서 Board/Worker 모두 같은 배포 SHA·rust writer/rust links, 바이너리 해시 일치·health/ready200이었다. 전환 후 신선 사본의 planner 대조는 원문7336건·Python/Rust대상4/4·unlisted0·PASS다. `switch-evidence.json`, `first-window/shadow.out.json`의 집계와 로컬 `final-runtime.json`, `rust-planner-verification.json`으로 확인했다. 첫 관리재시작은 CIM null 조회 오류로 원설정 복귀 후 대기 보완·재시도 PASS였으며 이를 첫 시도 성공으로 보고하지 않는다. 연결 첫 창도 OTA7965/7965·환불486/486·private_details0·types空·unlisted0·PASS였고 `first-window/evidence.json`과 `shadow-links.out.json` 집계를 직접 확인했다. 로컬 `rust-first-window-evidence.json`, `rust-first-window-links-summary.json`에 근거를 보존했으며 감독이 운영 소유권을 해제했다.

로컬 근거: `.local-archive/accounting-deploy-20261116/`의 `quality-final-summary.json`, `quality-final.log`, `independent-review.md`, `review-evidence.json`, `protection-before.json`, `protection-after.json`, `core-config-before.json`, `core-config-after.json`, `deploy.log`, `deploy-evidence.json`. 운영 근거는 `D:/WebLedgerHost/releases/deploy-evidence-8888230deb1a5bd09d826da7e66034e2091ba0a1.json`과 `release-audit-8888230deb1a5bd09d826da7e66034e2091ba0a1.json`이다.
