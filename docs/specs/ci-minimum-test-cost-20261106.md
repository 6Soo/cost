# COST GitHub Actions 최소 테스트 범위·분당 사용량 절감 계약 (2026-11-06)

> **2026-11-06 최신 정정(이전 'CI_ONLY_PR_PENDING'보다 우선): CODE_MERGED, CI_PASS, BILLABLE_EFFECT_UNVERIFIED.** [#710](https://github.com/6Soo/cost/pull/710) main `dd2c8bea24a31b44d5144fabd10d0d6ceab0ec50` 및 Actions 42227886027 SUCCESS. 실제 `.github/workflows/quality.yml`에는 주 1회 월요일 03:30 UTC 감사, PR merge-tree 기준 검사, main 동일 tree/증거 artifact 기반 재사용·실패 시 영향 테스트 fallback, docs-only 패키지/Chromium/artifact 절감, PR만 취소/main 보존이 **구현됨**. 기존 상단 'CI_ONLY_PR_PENDING' 문장은 병합 전 기록. 이전 기획 프롬프트 재실행 금지. 계정 과금 데이터 권한 부족으로 7/30일 실제 청구분 절감률은 아직 미확인. [후속 구현 범위 정본](cost-pr-only-implementation-brief-20261106.md#6-ci-710-구현-상태-남은-일과-잘못된-재작업-방지).


> **2026-11-06 구현 상태: CI_ONLY_PR_PENDING.** PR #709의 문서 결정에 따라 workflow를 수정했다: 주간 audit, PR에서 GitHub merge-branch tree 검사, 동일 tree·실제 PR artifact·0 skip 증거가 확인될 때만 main의 중복 테스트 재사용, 불일치·만료·API 실패 시 기존 영향 검사 실행, 문서 전용 성공 시 패키지/Chromium 설치와 artifact 업로드 생략. PR만 취소하고 main/schedule/manual 검사는 서로 취소하지 않는다. 최종 Actions 절감률은 저장소별 billable minutes API가 404여서 아직 측정할 수 없다. CI 전용 변경이며 운영 Windows 호스트·금융 DB·Google은 건드리지 않는다.


> **정본: 사용자 승인 실행 명세.** 아래 설계·검증 계약은 현재 구현 상태를 판정하는 기준이다. Git 병합이나 Actions 경과시간만으로 실제 billable 사용량 절감을 주장하지 않는다.

## 1. 실제 baseline과 가장 큰 낭비

- **변경 전 기준:** `.github/workflows/quality.yml`은 `pull_request`, `main push`, **월~금 03:30 UTC 정기 `--audit`**, `workflow_dispatch`에서 실행했다. 최근 PR #706 검사 약 14분 41초와 병합 뒤 main 검사 약 4분 55초가 각각 실행됐고 비슷한 크기의 quality artifact를 남겼다. 이 값은 경과시간이며 billable runner minutes가 아니다.
- 현재 영향 선택은 이미 `run_quality_checks.py` + `select_targeted_tests.py` + `test-impact-map.json`에 구현돼 있으며 문서-only는 `DOCS_ONLY`, 변경 없음은 `NO_CHANGES`, 알려진 코드 경로는 `SELECTED`, 예외/미등록 경로는 fail-closed로 구분한다. **영향 테스트 선택 시스템을 다시 만들지 않는다.**
- 일부 업무 파일(예: `webapp/card_flow.py`, `webapp/ledger_board.py`)은 여러 영향 그룹에 매칭되어 하나의 가벼운 UI 변경에도 방대한 테스트 및 브라우저 설치가 선택될 수 있다. 테스트 그룹은 안전 경계를 기준으로 중복 제거하고, 근거 없는 `safe_fallback` 전체 실행 대신 누락 경로는 `UNKNOWN_IMPACT`로 차단한 뒤 매핑을 추가한다.
- `Install Chromium`, pip 설치, 아티팩트 업로드는 **실제로 해당 검사 실행이 필요한 때에만** 한다. 문서-only는 Node/Chromium/pytest/서버 시동 없이 변경 문서 참조·링크와 diff/비밀값 점검만 한다.
- GitHub 알림 **1,800/2,000분은 계정 전체** 무료 Actions 분량의 약 90%이며 COST 단독 분량이라고 추측하지 않는다. Actions API의 경과시간과 실제 billable runner-minute는 다르다. 7일/30일 기준 실행 건수·billable 사용량을 계정 차원에서 확인할 수 있을 때만 절감률을 산출한다.

## 2. 변경 유형별 최소 필수 검사

| 변경 종류 | CI/로컬에서 꼭 할 것 | 기본으로 하지 않을 것 |
| --- | --- | --- |
| **문서·README·AGENTS만** (`.md`, 관리 TSV 등 안전한 문서) | diff 유효성, 실제 경로·앵커·문서 정본/비밀 유출 검사. 필수 job 성공 컨텍스트는 유지 | Python 패키지 설치, pytest, Playwright, 전체 `--audit`, 앱 배포·DB 조회 |
| **정적 UI/CSS·문구·특정 화면** | 해당 화면 테스트, 공유 셸 최소 호환 검사, 변경 화면의 320/390/1440 중 영향을 받는 viewport·라이트/다크·키보드 확인 | 전 화면·전 기능 스크린샷, Windows 호스트 전체 회귀, 무관한 금융/항공/OCR 테스트 |
| **카드 업로드·영수증·OTA 한 기능** | 변경 모듈 단위/실제 인접 회귀 + owner/CSRF/원본/중복 보호 중 **해당 경계**; 변경한 사용자 여정 1개 E2E | 전 기능·전 브라우저 크기 반복, 전체 호스트 배포 리허설 |
| **금융/환불/Google/권한/운영 DB 쓰기** | 해당 입력·보호·원자성·중복·원본·권한 표적 테스트 + 변경 범위의 통합 경계. Google 최종 장부 자동 쓰기 금지 확인 | 위험과 무관한 모든 UI 검수. 필수 보호를 생략하거나 skip 처리하는 절감 |
| **공통 라우팅/저장소/인증·배포 도구/의존성·매핑 변경** | 실제 영향 그룹 + 공통 안전 smoke + 필요한 범위의 폭넓은 회귀/검증 | 반대로 단일 테스트만으로 통과 선언 |
| **영향 경로 미등록·검사 미실행/skip** | 안전하게 FAIL/BLOCKED 및 명시적 mapping 보완·재실행. 변경된 테스트 파일 포함 | fallback으로 무관한 수백 건 무조건 실행, '0 tests passed'로 완료 선언 |

**중요:** 바뀐 코드의 새/수정 테스트와 정확한 관련 보호 테스트는 제외하지 않는다. 성능 최적화는 매핑 정밀화·중복 제거·캐시·불필요한 설치 축소이지 인위적인 skip/xfail/timeout 조정으로 녹색을 만드는 것이 아니다.

## 3. CI 이벤트·중복 실행 최적화

1. **PR이 기능 수락의 주검사:** 정확한 PR head SHA와 base SHA/merge base, 영향 파일 집합, 실제 실행 pytest target·브라우저 선택, 결과/skip/JUnit을 기록한다. 동일 diff의 재실행은 실패·변경이 없으면 반복하지 않는다.
2. **main 병합의 목표:** 별개의 squash SHA에서 무조건 같은 무거운 검사를 재수행하지 않는다. 다만 이미 검사한 코드와 **동일한 tree·의존성·설정 및 입력 범위**임이 검증된 경우에만 재사용 근거를 기록하고, main에서는 필수 경량 보호 검사·배포 가능성 확인만 수행한다. **서로 다른 tree/의존성·base 업데이트·충돌 수정·unknown이면 영향 검사를 다시 수행한다.** GitHub 필수 checks는 skip으로 소멸시키지 않고 명확한 결론(재사용/실행)을 발행한다.
3. **정기 감사:** 월~금 무조건 정기 audit 대신 **주 1회** 및 명시적 `workflow_dispatch audit=true`, 또는 금융·인증·배포 공통 변경 시 실제 위험 기반 검사를 명세에 따라 실행하도록 개선한다. 마지막 PASS와 이후 변경 SHA가 같다면 audit 기록 재사용 가능 범위를 표시하되 새로운 입력/정책·시간 의존 검사는 재확인한다.
4. **동시 실행:** PR별 `concurrency cancel-in-progress`의 기존 취지를 유지하고 PR에 새 commit이 들어오면 오래된 PR 검증만 취소한다. **운영 배포·롤백/복구 작업을 취소하거나 중복 배포시키지 않는다.** checkout/branch SHA와 현재 head가 같은지 검증한다.
5. **비용:** 문서-only는 가급적 유료 러너 0분에 가까운 초경량 job으로 종료하되, 필수 status context가 사라지지 않도록 job 구조를 유지한다. 불필요한 Chromium 설치·전체 pip cache miss·large artifact upload를 없앤다. 아티팩트는 실패 또는 실제 수락 증거가 필요한 경우만 제한적으로 보존한다.
6. **로컬과 CI 분담:** 개발 에이전트는 변경 타깃만 1회 검증하고, 호스팅 CI와 같은 코드·동일 픽스처에서의 반복을 목적 없이 다시 수행하지 않는다. 최종 CI의 사실을 로컬 테스트 완료로 꾸미지 않는다. 운영 Windows SHA 고정 배포는 **기존 단일 작성자·health/ready/보호 API·보호 13표/금융 쓰기 게이트**를 유지하되, 무관한 단위 테스트는 배포 직후 다시 실행하지 않는다.
7. **명세만 변경한 PR:** `DOCS_ONLY` 결과와 문서 검사 완료면 종료. 운영 배포·서버 재시작·실제 DB/Google 쓰기 금지. 이 정책 문서 PR 자체를 계기로 전면 감사/Windows 재배포하지 않는다.

## 4. 구현 순서(실행 명세)

- **C1 계측(읽기 전용):** COST 최근 7/30일 이벤트별 PR/push/schedule 횟수·job별 실제 billable minute·top 소비 테스트와 중복률을 분리 측정. 전체 계정 비용과 저장소 소비를 구분. 과금 권한이 없으면 분량 미확인으로 기록.
- **C2 매핑 정밀화:** 변경된 UI 파일의 왜 여러 그룹이 선택되는지 시뮬레이션하고 근거 있는 작은 `test-impact-map` 경로/검사로만 분리. 공통 금융·권한·라우트 변경은 폭넓게 유지. 최신 test selector 자체의 합성·회귀도 추가.
- **C3 workflow 최소화:** PR/main/schedule의 증빙·캐시·경로 게이트·조건부 설치/업로드/브라우저를 보정하되, status check 및 fail-closed를 유지. 주간 감사와 수동 AUDIT는 지속.
- **C4 비교 검증:** 대표 fixtures에서 변경전/후 **선택된 test 명단과 위험 커버리지**, 문서-only·UI-only·환불·인증·unknown·base drift·squash 케이스를 1:1로 대조. 실제 금융 데이터는 테스트에서 쓰지 않는다. 정상 PR/CI 성공 뒤 기존 승인된 배포 게이트에 따라 단계적 적용.

## 5. 완료 판정 (CI-COST-01~10)

| ID | 시나리오 | 통과 기준 |
| --- | --- | --- |
| 01 | 문서-only PR 및 main | 필수 status 생성·문서 검사 성공, 앱/브라우저/전체 QA/배포 0 |
| 02 | 단일 UI 텍스트 변경 | 관련 UI + 최소 공통 셸만, 자동 금융·항공·OCR 회귀 0 |
| 03 | 카드/환불 보호 변경 | 관련 금융 보호·원자성·원본·중복/권한 검사 **모두 실행**, skip 0 |
| 04 | auth/Google/DB 및 공통 모듈 | 공통 경계 포함, 임의 검사 미선택·권한 하향 0 |
| 05 | 테스트/영향 매핑 자체 변경 | 새/변경 테스트와 selector/CI 자체 회귀 수락 |
| 06 | 매핑 없는 코드·기준 SHA 변경 | 명시 fail-closed 또는 재검증. 허위 성공/무관한 전체 fallback 0 |
| 07 | PR→main 재검증 | 동일 tree·설정 증빙 없으면 반드시 영향 재실행; 재사용 시 정확한 PR evidence/SHA 기록 |
| 08 | 자동/정기/수동 실행 | 오래된 PR 취소, 감사 주간/수동, 필수 프로덕션 작업 미취소 |
| 09 | 앱 배포 시 | 검증 고정 SHA·health/ready·금융 보호·역할 검사 유지. 위험 미검증을 CI 녹색으로 속이지 않음 |
| 10 | 실제 소비 측정 | 변경전/후 7일/30일 billable minutes+run 수+실제 실패 검출을 보고. 측정 불가면 절감률 미확인 |

**종료 조건:** 동일 위험에 필요한 검증을 1회만 실행한다. 실제 보호 문제는 계속 fail-closed이고, 문서/단순 UI 수정이 금융 전체 QA 또는 반복 Windows 배포를 촉발하지 않는다. **현재 이 문서 작성 단계는 명세 변경뿐이며 실제 Actions 분 사용 감소는 아직 입증되지 않았다.**

## 6. 후속 에이전트 시작 명령

> COST 최신 main·열린 PR/배포·Actions 설정을 읽고 이 명세와 `AGENTS.md`·`run_quality_checks.py`·impact map을 대조하라. 기존 영향 기반 선택을 재사용하고 불필요한 여러 그룹·PR/main 중복·평일 매일 audit/불필요한 Playwright 설치를 줄여라. 문서-only/단순 UI는 초경량, 금융·권한·DB·환불은 실제 영향 통합 보호를 반드시 수행하라. 모든 CI context, fail-closed, 기존 단일 작성자 배포·보호13표·Google 금지는 지키고 CI-COST-01~10 증거로 수락하라. 변경한 코드와 테스트가 없으면 Actions 절감 완료라 보고하지 말라.
