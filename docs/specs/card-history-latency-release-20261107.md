# COST 카드 내역 로딩 최적화 #714: 운영 반영·실측·인계 단일 실행 명세 (2026-11-07)

> **2026-11-07 최신 운영 후보 우선 정정:** #714 단독 배포가 아니라 **#714 + #717을 한 번에** 배포한다. 검증된 마지막 제품 코드 SHA는 #717 merge **`fbda50cbe01d5021ab341ed82337badb2e8c59a0`**이고, #714 성능 최적화는 그 조상이다. #717 PR CI run **42299212267 SUCCESS**(239 passed + 26 subtests), main run **42299550620 SUCCESS**. 기존 아래 #714 전용 후보·`main 1bf39...` 설명은 당시 스냅샷이므로 **현재 배포 지시가 아니다**. [수집 현황 CVR-01~08](card-coverage-pending-review-ux-20261107.md) 추가 수락 필요. 이 문서 갱신 자체는 운영 미배포 상태이다.
>
> **2026-11-07 실제 운영 결과:** 지정 SHA `fbda50cbe01d5021ab341ed82337badb2e8c59a0`를 이전 `ceb014f1ca716792e9df7eaee591cc00294aa866`에서 공식 스크립트로 단일 전환했다. 1,429 tracked blobs mismatch0, task/process SHA 일치, Gateway8790→8752, health/ready200, 보호 API401, 보호13표 전후 불변 PASS, financial apply NOT_RUN. **인증된 사용자 화면·성능은 `AUTH_UI_BLOCKED`**: 실제 화면과 request-metrics endpoint가 익명 요청에 401을 반환해 카드별 화면·23개 파일·390/1440·cold/warm 카드 진입시간 및 lock/query 지표를 측정하지 못했다. 세부 내용은 [운영 기록](../operations.md)과 비공개 로컬 `C:/AX/cost/.local-archive/card-history-release-20261107/`에 있다. 이 문서 후속은 재배포 근거가 아니다.
>
> **운영 호스트 실행 추가 게이트:** 실제 current runtime SHA, single writer, restore point, release-audit 전체 Git tree blob mismatch0, candidate exact SHA ReviewEvidence PASS, 보호 13표 pre/post, authenticated `/cards/all?panel=coverage`의 실제 파일 23개 읽기/접힌 카드별 그룹/확인 링크, 390/1440 UI와 업로드 원본 확인 폼은 **GET 읽기 검증만**. 23개를 자동 확정하거나 `POST /coverage/confirm`을 시험 삼아 실행 금지. 배포 전후 같은 인증/기간/필터의 TTFB·db_lock_wait/card_query·화면 표시 실측은 #714 LAT-01~08 그대로 수행. 인증 불가면 UI는 미검증. `deploy_verified_release.ps1` 필수 3인자 preview와 `-Apply`는 실제 검증·단일 writer 보장 시에만 사용. 이미 후보 SHA 런타임이면 재배포하지 않는다.

> **현재 상태: CODE_MERGED / PR_CI_PASS / MAIN_CI_PASS / PROD_DEPLOYED / AUTH_UI_AND_PERFORMANCE_ACCEPTANCE_BLOCKED.**
> 제품 코드는 운영 반영됐지만 인증된 화면·속도는 아직 수락되지 않았다. 인증 없이 확인할 수 없는 항목은 통과로 보고하지 않는다. 이전 시점의 '카드 내역 통합 미구현' 및 'CI 최소화 미구현' 명세보다 **이 상태 표가 우선**한다. **COST만** 범위에 포함하며 다른 저장소를 수정하지 않는다.

## 1. 현재 확정 사실 (GitHub 2026-11-07 기준)

| 대상 | 상태 | 정확한 근거 |
| --- | --- | --- |
| 카드 등록 #712 | 병합·운영 배포 기록 완료 | PR #712 merge SHA `4611305d82156301f5ce32e46942d45de46baed4` |
| 카드 내역/업로드/수집 현황 IA #713 | 병합·운영 배포 기록 완료 | PR #713 merge SHA **`ceb014f1ca716792e9df7eaee591cc00294aa866`**, 로컬 합성 `interface-review` PASS, PR/main CI 성공, 보호 13표 불변; 운영 인증 브라우저는 **401로 인해 미확인** |
| 카드 내역 초기 조회 성능 #714 | **코드 병합·PR/main CI 성공, 미배포** | PR #714 merge SHA **`c4e87bfa745f6590d9bd024d0713c8864f935e7d`**, PR run `42274285504` SUCCESS, main run `42274512661` SUCCESS |
| 최근 기록 문서 #715 | 병합·문서 변경만 | main **`1bf39df19c3f2c1720cda8852b27f047c0be414a`**, run `42274783804` SUCCESS. #714 성능 코드 포함하지만 문서 커밋을 운영 기능 배포 증거로 취급 금지 |
| GitHub 열린 PR | **0 (확인 시점)** | 작업 직전 최신 GitHub와 Windows 실제 런타임을 다시 조회 |
| 알려진 운영 앱 SHA | **`ceb014f1ca716792e9df7eaee591cc00294aa866`** (마지막 검증 기록) | `docs/operations.md`, `docs/session_handoff.md`; **현재 호스트 읽기 확인 전에는 여전히 이 SHA라고 가정 금지** |

**핵심:** #714를 다시 개발하거나 #712·#713을 다시 병합하면 안 된다. #714에서 `card_transactions.year_summary()`의 연도별 12개월+미날짜 13개 집계 쿼리를 **한 개의 GROUP BY 집계 SQL**로 통합하고, `search_for_year`·`undated_list`에 이미 계산한 해당 필터의 `known_total`을 전달해 중복 COUNT를 없앴다. 원본/스키마/금융 쓰기는 없다. 별도 API는 기존 계산 계약 유지. 실제 CPU/디스크/락 기여도와 운영 체감 개선율은 미측정이다.

## 2. 에이전트가 이번 작업에서 실제 할 일

**유일한 1순위**: #714 변경을 포함하는 검증된 **정확한 코드 SHA**를 Windows 운영에 안전하게 전환하고, 동일 사용자 여정의 **배포 전후 응답 지연을 측정**해 사용자가 느낀 '카드 내역 진입이 느림' 문제가 해결됐는지 판단한다.

**수정하지 않을 범위**: IA·영수증 UI·메뉴·카드 7881·P1/P2/P3 업무 로직·여행/환불/OTA 회계/Google·업로드 데이터/원본·API 권한/스키마 및 다른 저장소. 이 문서 변경을 이유로 새 코드 PR, DB 마이그레이션, 작업 큐 재처리, 브라우저/AI 설정 업데이트를 하지 않는다.

## 3. 실행 사전 게이트 (읽기 전용)

1. `AGENTS.md`의 Windows **단일 작성자 및 로컬 미커밋/미추적 파일 보존** 정책을 읽는다. `docs/operations.md`, `tools/deploy_verified_release.ps1`, `tools/switch_verified_release.ps1`, `tools/verify_protected_release_state.py`, 이전 릴리스 증거 파일의 형식·SHA를 대조한다. 운영 사용자 파일/로컬 보관 기록 삭제·reset·clean·force-push 금지.
2. GitHub 최신 main·PR/open·각 SHA의 CI 결과를 다시 확인. **배포 후보로 #714 병합 코드 SHA `c4e87bfa745f6590d9bd024d0713c8864f935e7d`를 우선 고려**한다. 현재 main이 그 후속의 **문서-only commit만** 포함하면 #714 코드 SHA 배포가 가능한지 현행 배포 정책과 전체 tracked blob 감사로 확인한다. 현재 main에 더 새로운 **제품 코드 변경**이 있으면 후보 SHA를 임의 결정하지 말고 그 영향·CI/리뷰를 검증해 별도로 기록한다.
3. Windows의 실제 scheduled task `WebLedger-Board` 실행 SHA, 프로세스 명령줄, gateway `8790`→단일 loopback `8751/8752`, `D:/WebLedgerHost/releases`의 현재 릴리스/복구점·잠금/기타 작성자 여부를 **읽기 전용**으로 확인한다. 마지막 기록은 `ceb014f1...`지만 실제 다른 SHA가 배포돼 있을 수 있다. **이미 후보 SHA가 운영이면 재배포하지 말고 측정만 수행**한다.
4. 시작 전에 운영 `/healthz`·`/readyz` 200, 인증 없는 보호 API 401, 추적 파일/실제 task/process SHA 동일, 원본·Google·금융/환불 보호 13표의 **전 상태 증거**를 준비한다. 고객 원문/카드번호/토큰/SQL 원문/개별 거래는 GitHub/로그에 올리지 않는다.
5. **배포 전 지연 baseline (가능한 경우):** 같은 인증 권한·필터·기간·데이터 양/캐시/네트워크 기준 `/cards/all` 진입의 서버 TTFB, 사용자가 콘텐츠를 볼 때까지의 browser 시간, 별도 `app.request_metrics` `first_render.card_query` / `first_render.db_lock_wait` / `card_render` 집계를 기록한다. 첫 요청(cold)과 반복 요청(warm)을 **각각 5회 이상** 분리하고 중앙값·p95 또는 범위를 표시한다. 운영 세션 접근이 없다면 인증되지 않은 401로 UI 성능을 측정했다고 주장하지 말고 `AUTH_UI_BLOCKED`로 기록하고 허용되는 서버/합성 측정만 남긴다. 신규 모델·비밀번호·고객 데이터 접근 우회 금지.

## 4. 배포 후보 준비·공식 실행 (Windows 승인된 단일 writer만)

- **현재 CLI의 진짜 매개변수:** `tools/deploy_verified_release.ps1`은 `-CandidateSha`, `-PreviousSha`, `-ReviewEvidence` 3개가 **필수**, `-Apply`가 없으면 **PREVIEW만** 반환한다. `-BackupProducts`는 별도 명시 옵션이며 기본적으로 사용하지 않는다.
- 후보 코드 디렉터리와 기존 현재 릴리스의 `DEPLOYED_COMMIT`를 실제 정확한 SHA로 준비한다. 단순히 새 main에 `git checkout`하는 것으로 운영 릴리스 준비/복구점이 만들어지는 것이 아니다.
- candidate의 **전 tracked 파일 개수·Git blob SHA 일치**를 확인한 `release-audit-<CandidateSha>.json`, `ReviewEvidence` JSON(`status=PASS`, 해당 `candidate_sha`, 실제 테스트 증거), 동일 디렉터리의 `protection-before.json`(**정확히 13개 보호 테이블**), 기존 운영 릴리스 `deploy-evidence-<PreviousSha>.json`을 확보한다. 재사용 증거의 SHA 불일치/만료/소스 변경 시 새로 감사·검증한다.
- **비변경 파일은 이전 검증 릴리스에서 가져오고 #714의 추적 파일만 정확한 Git 후보 blob에서 가져오되, 결과물은 반드시 전체 후보 Git tree와 해시 일치해야 한다.** 사용자 미추적/로컬 자료·운영 DB 및 시크릿을 복사본 덮어쓰기하지 않는다.
- **CLI 형식 참고**(대괄호 값은 실행 전 검증해 실제 경로·정확한 SHA로 치환):
  ```powershell
  & .\tools\deploy_verified_release.ps1 -CandidateSha "<검증된_40자리_후보_SHA>" -PreviousSha "<실제_운영_40자리_SHA>" -ReviewEvidence "<검증된_리뷰_증거_JSON_경로>"
  # 위 PREVIEW가 기대와 일치하고 단일 작성자·배포 감사·보호 조건이 PASS일 때만:
  & .\tools\deploy_verified_release.ps1 -CandidateSha "<검증된_40자리_후보_SHA>" -PreviousSha "<실제_운영_40자리_SHA>" -ReviewEvidence "<검증된_리뷰_증거_JSON_경로>" -Apply
  ```
- 스크립트의 실제 릴리스 잠금 `D:/WebLedgerHost/config/verified-release.lock`, 게이트·원자 전환, 전환 후 task/process SHA·단일 listener·health/ready·보호 API·`verify_protected_release_state.py --phase after`를 변경하지 않는다. 실패 시 스크립트의 이전 릴리스 rollback 검증을 수행하고 안정 상태에서 멈춘다. **재부팅·서비스 재설치·DB 백업/복원·재분류·금융 apply는 승인되지 않았다.**

## 5. 배포 후 성능·정합성 확인

| ID | 실제 확인 | PASS / 미확인 기준 |
| --- | --- | --- |
| LAT-01 | 현재 운영 SHA·잠금/단일 writer 확인 | 수행 전·후 SHA 증거가 있고 이미 반영됐다면 불필요한 재배포 0 |
| LAT-02 | 후보 파일/리뷰/QA·복구점 완전성 | 릴리스 전체 파일 Git 일치, mismatch0, QA·CI/ReviewEvidence candidate SHA 일치 |
| LAT-03 | 공식 deploy script | preview→apply, 정확한 SHA task/process, listener1, Gateway, health/ready200 |
| LAT-04 | 고객 데이터 보호 | 인증 없는 보호 API401, 보호 **13표** schema/content 전후 불변, 금융 apply·Google·원본/스키마 쓰기 0 |
| LAT-05 | 카드 조회 정합성 | 2026 연/월·날짜 미확인·다른 연도·카드/검색/미배정/커서·환불/중복/상세·업로드 기존 링크 계약 유지 |
| LAT-06 | 사용자 진입 성능 | **같은 조건 전/후** cold/warm TTFB·화면 표시 시간, 측정 수/중앙값/p95·날짜·SHA·부하 맥락 기록. 운영 화면 인증 불가면 `AUTH_UI_BLOCKED` |
| LAT-07 | 잠금 vs SQL 병목 | 개인정보 없는 `db_lock_wait`와 `card_query`/렌더링 관측. 개선이 작거나 사용자가 여전히 느리다면 정확한 병목 확인 후 **별도 P1 성능 PR** 계획 |
| LAT-08 | 후속 기록 | 운영 `docs/operations.md`·`docs/session_handoff.md`에 증거 SHA·검사·배포/미배포·성능 수치 및 한계 기록. 후속은 문서-only, 재배포 0 |

**성능 판정:** 기존 #714의 **SQL 집계 개선**과 **전체 웹페이지 로딩 개선**은 다른 지표다. 운영 전후 비교 표본이 없으면 '10배 빨라졌다'나 '완전 해결'이라고 보고하지 않는다. baseline 없이 배포 후만 재면 `CURRENT_ONLY`라고 표기. DB 잠금 대기가 지배적일 때는 조회 최적화가 전체 응답을 해결하지 못할 수 있다. 권한 제약·로그 없음은 측정 불가로 기록하고, 임의 성능 수치를 만들지 않는다.

## 6. 종료·인계 정책

- **완료:** 배포 후보·이전 SHA/복구점·보호 13표·CI와 리뷰 증거 모두 검증, 실제 운영에 #714 코드가 포함됐음이 task/process SHA로 확인, `LAT-01~08`을 근거로 보고하고 가능한 범위의 사용자 진입 속도 확인. 기존 배포와 새 코드가 같다면 새 배포 없이 상태 검증으로 종료 가능.
- **차단:** Windows 접근 권한/리뷰 증거/릴리스 후보/인증 환경/락이 없다면 `DEPLOY_BLOCKED` 또는 `AUTH_UI_BLOCKED`로 정확히 표기, **GitHub PR 성공을 운영 배포로 속이지 않는다**. CI/운영 재배포를 재시작하지 않은 상태의 작업만 문서로 남긴다.
- **안전:** 이미 완료된 #710/#712/#713을 재구현하지 않고, #714 최적화가 반영된 이후에도 사용자 체감 로딩이 느리면 먼저 실제 `db_lock_wait`·카드 SQL·렌더링·프록시를 구분한 별도 이슈/PR로만 추가 최적화한다.

## 7. 에이전트에게 PR 링크와 함께 보낼 실행 지시

> COST 최신 main 및 Windows **실제 운영 SHA**를 다시 확인하고 본 명세만 기준으로 #714 카드 내역 초기 로딩 최적화 **배포·실측 수락**을 실행하라. #712/#713 및 #710은 완료된 것으로 보존하고, #714 코드를 재구현하거나 고객 DB·Google·금융 자료를 쓰지 마라. 코드 후보 `c4e87bfa745f6590d9bd024d0713c8864f935e7d`와 현재 main의 차이를 확인해 안전한 SHA를 정하고, 먼저 운영 지연 baseline·락/SQL 계측, 복구점/13표/코드 파일 해시/리뷰 JSON 확인을 수행하라. `deploy_verified_release.ps1`의 실제 필수 인자를 사용해 preview 후 승인된 단일 writer 방식으로 apply, task/process 정확 SHA·health/ready·보호 API·보호 13표를 검증하라. 배포 후 같은 조건의 로그인된 카드 내역 진입시간·db_lock_wait·card_query를 재측정하라. 401이면 인증 운영 화면 수락 미검증으로 표시하고, 개선 효과 불명확하면 실제 병목만 읽기 진단해 별도 PR로 분리하라. 운영 기록을 갱신하되 **문서-only 후속 커밋은 재배포하지 말라**. 최종 사용자 보고는 ELI10으로 전/후 측정·배포 SHA·보호·미검증 항목을 분리해 제출하라.
