# 운영 기록

> 이 문서는 현재 유효한 운영 절차와 2026-11-08 이후 배포 기록만 둔다. 2026-11-07 이전 기록은 [10/28~11/07](history/operations-20261028-20261107.md), 2026-10-27까지는 [운영 이력](history/operations-through-20261027.md)에 원문 그대로 보관한다. 2026-11-09 작업공간 통합 정리 상태는 [현재 상태](session_handoff.md)를 본다.
## 데이터·호스트

- 현재 Windows 운영 데이터는 `D:/WebLedgerHost/data` 아래의 기존 설정·DB·원본을 사용한다. 호스트 실행은 기존 SHA 고정 Windows 릴리스 절차를 따른다. 문서 정리 때문에 새 서버·인프라·마이그레이션을 만들지 않는다.
- 호스팅 설정의 `WEBLEDGER_DATA_ROOT`는 **절대 경로**인 지속 마운트여야 한다. 플랫폼 설정의 예시 경로는 `/srv/web-ledger/data`다. 이 예시는 Windows 운영이 해당 Linux 경로로 이전됐다는 뜻이 아니다. 작업 디렉터리 안에 새 운영 DB를 만들지 않는다.
- 실제 카드·OTA·장부 DB·인증·Google 원본을 보호한다. 파생 색인 갱신과 금융 쓰기는 구분한다. 소스/사용자 결정/원문 ID·금액을 합계만으로 검증했다고 주장하지 않는다.

## 일반 코드 배포 순서

1. 원격 최신 main·관련 열린 PR·고유 diff·현재 릴리스와 기존 복구 사본/복원 검증 근거를 확인한다.
2. 변경 기능의 표적 검사와 필요한 금융·권한 보호를 통과한 뒤 정상 PR 병합한다. 미검증 PR을 일괄 병합하거나 force push하지 않는다.
3. 검증된 기존 Windows 절차로 배포 SHA를 고정한다. 작업 XML·이전 릴리스·보호 자료를 보존하며 임의로 보호 파일을 덮지 않는다.
4. 작업/프로세스/리스너 SHA, health/ready, 보호 API와 변경 경로 최소 스모크를 한 번 확인한다. 금융 영향이 있는 변경은 적절한 통합 경계에서 원본/결정 보호도 확인한다.
5. SHA·실제 결과·미실행·실패/차단을 이 문서와 현재 상태에 기록한다. 실패를 성공으로 보고하지 않고 안전하게 가능한 이전 검증 릴리스 롤백만 수행한다.

DB/Google/원본/금융 상태 직접 쓰기·마이그레이션·대량 재처리·새 유료 자원은 일반 자동 배포 승인에 포함되지 않는다. 호스트 접근이 없으면 `DEPLOY_BLOCKED_NO_HOST_ACCESS`와 정확한 SHA·다음 명령을 남긴다.

## 공식 코드 배포 진입점 (RF-005, 2026-10-28)

검증된 SHA 릴리스와 이전 검증 릴리스, review.json 및 보호13표 기준선을 준비한 뒤 저장소 루트에서 `tools/deploy_verified_release.ps1`을 사용한다. 기본 호출은 `PREVIEW`와 `executed:[]`만 반환하고 host/task/review에 접근하지 않는다. 실제 전환은 기존 코드 배포 승인과 게이트를 충족한 경우에만 같은 인자에 `-Apply`를 명시한다. 필수 인자는 `-CandidateSha`, `-PreviousSha`, `-ReviewEvidence`다. 동일 SHA나 불완전 SHA는 전환 전에 거부한다.

기준선은 `python tools/verify_protected_release_state.py --evidence-dir <검수디렉터리> --phase before`로 준비하며 이 도구는 운영DB를 mode=ro로 연다. 배포기는 새 백업·별도 복원 검증 후에만 `switch_verified_release.ps1`로 task를 전환한다. 작업/프로세스/단일loopback listener와 health/ready·보호API, 보호13표를 확인한 근거는 기존 `deploy-evidence-<SHA>.json` 형식으로 남긴다. 실패 시 검증된 이전 릴리스 복귀 경계를 유지한다. 스키마 변경·원문 적재·금융/Google/명단 쓰기·대량 재처리용 진입점이 아니다. 기존 역사적 lightweight DB전환 스크립트는 이 코드 배포 경로와 구별한다.

## 제한된 코드 배포물 preview (RF-003)

`python tools/code_release_manifest.py --sha <정확한40자SHA>`는 메타데이터 preview만 수행한다. `--output <새ZIP경로>`를 명시하면 Git의 해당 SHA blob에서만 코드·승인 정적 자산·공통 규칙 설정을 새로 묶으며 기존 경로는 덮지 않는다. 원본/과거 출력/비공개 호스트 설정/테스트는 패키지에서 제외하고 저장소에는 그대로 보존한다. 알려진 라이선스 폰트는 경로·blob·크기가 모두 일치할 때만 대용량 예외를 허용한다.

이 산출물의 표시는 `BUILT_NOT_RUNTIME_ACCEPTED`다. source 안의 비밀값 검사나 동적 운영 의존성의 완전한 수락을 의미하지 않으며 `CODE_RELEASE.json`도 `runtime_accepted:false`를 유지한다. 공식 운영 릴리스 교체 전에는 격리 통합과 실제 런타임 입력 경계를 별도로 검증한다. 과거 전체 Git 릴리스의 검증 기록을 새 제한 패키지의 수락으로 대체하지 않는다.

## 문서만 바꾸는 경우

diff·링크·현재/과거 구분·실제 문서 참조 경로만 확인한다. 코드 테스트·빌드·브라우저·운영 DB 확인·백업·재배포·서버 재시작은 하지 않는다. 이전 기록의 유효한 검증을 단순 안심 목적으로 반복하지 않는다.

## 과거 근거 찾기

- [10월28일~11월7일 배포 기록](history/operations-20261028-20261107.md): 직전 릴리스별 SHA·검증 전문.
- [운영·검증 전문](history/operations-through-20261027.md): 이전 `operations.md` 전체와 10월7일 이전 기록, 메일 조사.
- [구현·검토·계획](history/implementation-and-audits.md): 각 변경의 표적 명령·실패 비교·화면 수락 경계.
- [제품 결정·옛 인계](history/product-and-handoffs.md): 이전 상태표와 정책 변경 당시 기록.
- [옛 경로별 위치](history/README.md#옛-경로-찾기): 통합 전 파일명으로 검색.

과거 기록의 운영 SHA·미구현·HOLD는 해당 시점의 근거다. 현재 런타임 또는 새 개발 권한으로 해석하지 않는다. 콘솔 창 다음 예약 실행 수락은 여전히 NOT_RUN이다.

## 2026-11-10 장부 이용일·성능 코드 배포 연속 기록 — COMPLETE

| 순서 | 운영 SHA | 이전 | 포함 PR | 결과 |
|---|---|---|---|---|
| 0 | `3dd0750e…` | d67a1312 | #767(백엔드 작업 Worker 통합) | PASS 2026-11-09T08:55Z |
| 1 | `2ef58a9242e8fdf1687b729a91a1f36558ec00af` | 3dd0750e | #768/#769(메일 재시도·동일 원본 비교, 워커 전환 보강) | PASS 13:26Z, 1,465 blobs mismatch0 |
| 2 | `4151d805b577ea2f1206e94c239fb56d6dd2322c` | 2ef58a92 | #770/#771(skyticket 해외 구매·Trip 가격 변경 근거, 자식 교환 파일 정리) | PASS, 이후 장부 12–46s 지연 발견. 2ef58a92 롤백 시도는 HTTP 스모크 실패로 자동 복귀(4151d805 유지) |
| 3 | `7334f1ae2c20e04e60348a4898a54b5ab08e7d00` | 4151d805 | #772(이용일 인덱스 세대당 1회) | PASS |
| 4 | `cee973fbacc8137c3f3552c4329caf9d53166535` | 7334f1ae | #774/#775/#776 | PASS 18:07Z, 1,485 blobs mismatch0 |
| 5 | `086acc679ea4639ef96793ae2be39d1a63de8ea9` | cee973fb | #777 | PASS 18:43Z |
| 6 | `094e52c9929843fb0b9b17b07e482eaf1c95ce6c` | 086acc67 | #778 | PASS 19:31Z |
| 7 | `f5758929bf091b4fd4a43b4227709e8ad4197596` | 094e52c9 | #780 | PASS 19:54Z, 1,485 blobs mismatch0 |
| 8 | `9ad0a454ae323cb6ee61c2a4827dca3bf34caa15` | f5758929 | #779(다른 세션 UI 1차, 검수 ff198354)·#782 | PASS 20:27Z, 1,494 blobs mismatch0, 다른 세션과 조율해 단일 작성자 배포 |

- 공통: 후보 릴리스 자체의 `tools/deploy_verified_release.ps1 -Apply`, 사전 `verify_protected_release_state.py --phase before`, 보호13표 전후 불변, runtime SHA 일치, listener1, health/ready200, 보호 API401, `continuous-switch-<SHA>.json`의 `worker_switched=true`(단, 0번 3dd0750e는 `false` — #767 시점 Worker 전환 도구 결함으로, #769 이후 1~8번은 모두 `true`). 금융 적용·고객 원본 쓰기·Google 쓰기·마이그레이션 없음.
- 성능 수락(인증 ego-browser, 같은 3개 여행 장부): 7334f1ae 3.2–9.6s(1건 502/38s), 요청 지표 잠금 대기 p50 1,211ms·p95 51,959ms → cee973fb 0.9–1.0s, 잠금 대기 p50 0.003ms·p95 197ms, first_render p50 777ms.
- 진단 방법: Python 3.14 `sys.remote_exec`로 운영 Board 프로세스에 읽기 전용 스택 샘플러·스냅숏 진단 스레드를 주입했다(데이터 쓰기 없음, 결과는 비공개 scratch에만 저장). 한 번 주입이 다음 주입에 덮여 실행되지 않은 사례가 있어, 주입 간 결과 파일 생성을 확인한 뒤 다음 주입을 해야 한다.
- 재기동 직후 OTA 스냅숏은 공개 요약만 디스크에 있어 첫 재계산(이번 7분 9초, 직전 1회 SOURCE_CHANGED 실패 포함 약 16분)까지 장부 OTA 이용일이 비어 보인다. 배포 직후 경고 집계는 `refresh_done` 이후에 한다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-<SHA>.json`, 비공개 `C:/AX/cost/.local-archive/service-date-row-audit-20261109/deploy-<SHA8>/`(review.json, protection-before, apply.log).
- Worker 재시작(배포)은 실행 중 `mail-collect`를 끊는다. #778 이후에는 저장된 200건 묶음이 보존되고 재시작 직후 수집이 다시 시작된다.
- Gateway 포트 점유 장애(04:00–04:06 KST)와 복구 절차는 [현재 상태](session_handoff.md) 2026-11-10 절.

## 2026-11-09 작업공간 통합 정리 + #763 코드 단일 운영 배포 — COMPLETE

- [PR #764](https://github.com/6Soo/cost/pull/764) 병합 `d67a1312d6e592648db0ed6ea95e49ff5aa9d053`(트리는 #763 검수 SHA `2723125a85fc95625b92114a5feb3e7c49468f78`과 docs·AGENTS.md 외 동일)를 이전 검증 `c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a`에서 공식 단일 코드 배포했다(`tools/deploy_verified_release.ps1` PREVIEW→`-Apply`). #763의 렌터카 선결제 구분·라쿠텐 예약 근거 수정이 운영에 반영됐다.
- 결과: 1,459 tracked blobs mismatch0, task/process/runtime SHA 일치, listener1(127.0.0.1:8752)·Gateway8790 경유 health/ready200·보호 API401, 보호13표 전후 불변, financial_apply NOT_RUN. 독립 재확인에서도 Board task 인자·8752 listener 프로세스에 배포 SHA가 있고 Gateway/SourceRefresh Running, MailCollect Ready였다. 이전 검증 릴리스와 task XML을 복구점으로 유지했고 전체 DB 백업/복원은 코드 전용이라 생략했다.
- 검수: 2723125a 영향 QA 729 passed·skip0·compile PASS, #763 독립 검수 APPROVE, 문서 통합분은 `codex/gpt-6.1-sol`·medium의 최종 SHA 검수 APPROVE. 호스팅 CI는 결제 한도로 시작되지 못해 녹색이 아니며 2026-11-07 승인 예외를 적용했다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-d67a1312d6e592648db0ed6ea95e49ff5aa9d053.json`, 비공개 `.local-archive/cleanup-20261109/deploy-d67a1312d6e592648db0ed6ea95e49ff5aa9d053/`(review/protection/zip). 미검증: 인증 운영 화면, 실기기, 이용일 경고 402행의 실제 감소. 이 문서 전용 후속은 재배포하지 않는다.
- 호스트의 `releases/2723125a85fc95625b92114a5feb3e7c49468f78`는 다른 세션이 준비한 미감사 후보 폴더다(전환 이력 없음). 롤백 보존 정책이 정해질 때까지 삭제하지 않았다.
## 2026-11-09 산림치유원 NICE 메일 — 전용 자료 복구 수락 완료

- 운영 통합 SHA `d96f08809b8201238e8399d053140ab20e3a91fc`의 최종 보호13표 검사와 잠금 해제 후 별도 원문 복구 구간을 실행했다. [PR #752](https://github.com/6Soo/cost/pull/752) 파서의 실제 운영 blob 동등성을 확인했고 MailCollect를 구43907dd에서 d96 릴리스 working directory로 고정했다. 실행파일·인자·자격증명은 보존했고 기존 hourly 수집 정상 종료 후 전환, 최종 Enabled/Ready를 확인했다.
- 인증 Gmail API 정확 집합·원본 payload digest30/30 재검증 → OTA 백업 및 별도 복원 내용/무결성 동등성 → 기존 원문 불변 원자 추가30건 → 반복 import 쓰기0·watermark 불변·금융 보호13표 불변 PASS. 원본 메시지/원본 blob/원본 entry의 기존 행 해시를 보존했다. 금융 원행·수동 결정·환불 확정·Google 최종 장부 쓰기0.
- 운영 d96 모듈의 읽기 수락은 원문30/30·추출30·금액0 오인식0 및 대상 결제11/취소 안내6/잔여5 대조 PASS. 실제 은행 환급이나 예약 유지를 확정하지 않는다. health/ready200·보호 API401, 수집 Enabled/Ready 확인. 추가 서버 배포·재시작 없음. 실제 고객 화면의 독립 시각 수락은 미실행이다.
- 최신 사용자 지시에 따라 숙박일 필수 질문을 철회하고 지리적 귀속을 완료로 확인했다. 전북 진안/호남권 근거로 해당 7월 거래는 기존 `1115_호남`에 code_inference/classified로 귀속되어 있으며, 원결제·취소 동일 여행·미배정0을 읽기 검증했다. 이미 올바른 귀속이라 추가 금융/원문/수동 이력 쓰기는 하지 않았다. 실제 숙박일·예약 유지·은행 환급 사실을 만들지 않는다. 비공개 귀속 근거 `C:/AX/cost/.local-archive/forest-trip-geography-20261109/`, 원문 복구 근거 `C:/AX/cost/.local-archive/forest-receipts-20261108/`, 백업/별도 복원 `D:/WebLedgerHost/data/backups/forest-mail-20261108T201146Z/`. 아래 대기 기록은 실행 전 이력이며 현재 명령이 아니다. 이 문서 전용 후속은 재배포하지 않는다.

## 2026-11-09 여행 지출 실제 복사·Job 수명주기·OTA 메모리 — 운영 수락 완료

- 최신 사용자 `해결을 해`의 운영 복사 오류를 해결했다. 준비된 TSV를 먼저 선택해 동기 복사를 시도하고 선택적 비동기 클립보드 응답은 1.5초로 제한한다. 응답이 없거나 거부되면 원문 선택·재복사 경로와 활성 버튼을 유지한다. 요청 안에서만 행 조회를 재사용하며 원본 검증·Google 대조·기존 7열/중복 제외 계약을 유지한다. Google 최종 장부 쓰기는 실행하지 않았다.
- 최종 운영 SHA **`d96f08809b8201238e8399d053140ab20e3a91fc`**, 이전 검증 `db7ce9954bcdd4e9a858035e99d23c683ec82349`. [복사 #751](https://github.com/6Soo/cost/pull/751), [수명주기 #754](https://github.com/6Soo/cost/pull/754), [OTA 메모리 #756](https://github.com/6Soo/cost/pull/756), [종료 경합·복귀 보호 #757](https://github.com/6Soo/cost/pull/757)를 포함한다. 최종 main tree는 검수 `3d859e9c0d1195b69b03ebbcb6a8fb11fa62ec4a`와 동일하다. 원문 복구 #752와 날짜 #755의 기존 병합도 보존했다.
- 정확한 소스별 영향 검사: 복사 **425 passed +85 subtests·필수 browser43/43**, OTA **424 passed +4 subtests·browser10/10**, 합본 교차 **23 passed**, 배포 종료 보호 **100 passed**. 각 검사 skip0·compile PASS이며 서로 중복된 검사를 합산한 고유 검사 수로 표시하지 않는다. 폐기된 제안 UI/분류 대기 기대는 현행 DEST 검사로 대체하고 API 권한·금융 원본·원자성·멱등성 보호는 유지했다. 초기 red 결과는 별도로 보존했다.
- 실제 독립 `gpt-6.1-sol / medium`이 후보·합본·정확 main SHA를 검수해 승인했다. CI run42516114312/job128839384202(copy union), run42515451899/job128837348189(OTA), run42517410150/job128843348971(종료 보호)는 각 정확 SHA에서 runner0/steps0 결제·사용 한도 미시작이다. **CI는 NOT_GREEN**이며 2026-11-07 사용자 승인 예외를 적용했다. 실행된 검사 실패를 예외로 통과시키지 않았다.
- **인증 운영 native 수락 PASS:** ego-browser의 실제 1440px·390px에서 각각 **17행·7열** 준비 값과 OS Ctrl+V 결과가 정확히 일치했다. 버튼 활성 복귀·오류 없음·페이지 넘침0, 키보드 실행을 확인했다. 복사부터 붙여넣기 비교까지 각각 2,728ms·2,828ms인 단일 표본이며 이전 다른 여행/상태의 지연과 같은 입력 성능 비교라고 주장하지 않는다. 동일 크기 운영 전후 캡처와 합성 1440/390/320·두 테마 전후·예외 상태 근거를 보존했다. 고객 원문/화면은 비공개 산출물에만 둔다. TaskSpace0을 마치고 사용자 결과 탭은 유지했다.
- 공식 코드 전용 배포: **1,453 tracked blobs mismatch0**, task/process/runtime SHA 일치, Gateway8790→loopback8752·listener1·health/ready200·보호 API401. fresh 보호13표 전후 불변과 운영 재기동/복사 뒤 최종 불변을 확인했고 단일 작성자 잠금을 해제했다. 실제 운영 stop/start 두 회차에서 이전 프로세스14개가 매번 전부 종료되고 새 소유자1개가 유지됐다. Running 중 추가 시작도 같은 소유자를 유지했다. 자식 crash/descendant kill/mutex 재사용·경쟁은 별도의 실제 Windows 합성 Job 검사로 검증했으며 운영 자식을 의도적으로 crash한 것은 아니다.
- 첫 후보 `c2f7bdd7`의 전환은 **FAILED**였고 이전 db7 서비스·ready200·보호13표 불변으로 복구했다. 기존 도구가 첫 예외를 가려 실제 최초 원인은 미확정이다. 합성으로 확인한 stale TCP/CIM 조회, 검증 직후 PID 종료, 후보 cleanup 오류의 복귀 건너뜀, 실패 기록 쓰기의 복귀 차단을 수정해 새 불변 릴리스 d96을 배포했다. 실패 c2를 수정하거나 성공으로 재분류하지 않았다. unknown/reused PID 종료 금지는 유지한다.
- OTA 동일 합성 입력80개·4범위320관측에서 본문 보존320→80, catalog peak private503,541,760→450,428,928 bytes, reconcile507,183,104→453,758,976 bytes(약11%)이며 결과/원본 해시가 동일했다. catalog wall time은 단일 표본에서 개선되지 않았다. [재현 명세](specs/ota-mail-load-lifetime-20261109.md). 운영 warm 중 private1,826.7MiB(db7)→1,019.3MiB(d96), warm 완료 후296.9MiB·10프로세스·소유자1·CPU0.015625초/12.6256초로 수렴했다. 이는 같은 입력을 통제한 운영 효과율이나 장기 누수 완치 증명이 아니며 venv 부모/자식 쌍을 중복 보드로 세지 않는다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-d96f08809b8201238e8399d053140ab20e3a91fc.json`; 비공개 `.local-archive/copy-paste-resume-20261109/`의 `production-copy-acceptance.json`, `release-d96f0880/`, `runtime-before.json`, `runtime-after.json`, `runtime-after-warm.json`; 합성 계측은 `.local-archive/webledger-root-20261109/`. PC 담당에게 A–F 최종 결과를, 원문 복구 담당에게 최종 SHA·after13 PASS·lock release를 전달했다. 원문30건 복구는 그 담당의 별도 승인 구간이며 이번 코드 배포의 완료 범위로 꾸미지 않는다.
- 남은 필수 복사/배포 작업은 없다. 실기기/Safari·스크린리더 음성·실제200% 확대와 장시간 운영 누수 검증은 미실행이다. 이 후속 문서 변경으로 코드 검사·재배포·서버 재시작을 반복하지 않는다. 아래 11월8일 AUTH_UI_BLOCKED 기록은 당시 이력이며 현재 복사 수락 상태를 대체하지 않는다.

## 2026-11-09 산림치유원 NICE 원문 복구 — 코드 병합 / 운영 미실행

- [PR #752](https://github.com/6Soo/cost/pull/752)의 main `25d41ff933a35fc42122e2d4da6264a6a6f4a45f`는 검수 HEAD `d337121f45335a3fdd1486afb97e7ad53ba1d1d8`와 tree가 같다. 검색·결제/취소 추출·범위 제한 복구 및 영향 지도를 수정했다. 정확 HEAD 영향 QA411 passed·skip0·compile PASS·필수 브라우저1/1, 독립 실제 gpt-6.1-sol/medium 코드 병합 승인. CI42492278382/job128767045020은 결제/사용 한도로 steps0이며 사용자 승인 예외로 병합했고 CI 녹색으로 표시하지 않는다.
- Windows Job/mutex 감독기 정식 통합과 단일 배포 순서 확정 전이므로 이번 배포·MailCollect 작업 변경·운영 자료 쓰기는 하지 않았다. 마지막 확인 Board는 `068de5da50611255dd4ef23d12f2a8272fe4b616`이며 이후 통합 배포의 현재 SHA를 대신하지 않는다. 기존 기동 보호를 해제하거나 구 전환 경로로 후보기동을 강행하지 않는다.
- 대상 원문30건은 인증 Gmail API 재열람 동등성30/30으로 복구 입력만 검증했다. 실제 추가 적재·백업/별도 복원 실행·자료 복구 보호13표 전후 확인·재실행 불변·운영 화면 수락은 미실행이다. 코드 배포의 보호 구간과 원문 복구 보호 구간을 분리하며 원본·금융·수동 결정·Google 최종 장부를 보존한다.
- 이용일 필수 사실은 미응답이다. 예약번호/숙박일/은행 환급 사실을 창작하지 않는다. 상세는 [현재 인계](session_handoff.md), 비공개 근거는 `C:/AX/cost/.local-archive/forest-receipts-20261108/`다. 이 문서 전용 후속은 코드 테스트·재배포·재시작을 유발하지 않는다.

## 2026-11-09 항공 이용일·완료 환불 근본 원인 수정 배포

- [PR #762](https://github.com/6Soo/cost/pull/762)의 최종 검수 코드 `7a2b126a063d8032bcba18b5d9b60bc7636ae866`를 병합한 `c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a`를 이전 검증 `d96f08809b8201238e8399d053140ab20e3a91fc`에서 공식 단일 코드 배포했다. 이전 #759/#761의 병합 코드도 포함된다. 항공 예약 일정 문맥·기존 카드의 날짜 표시·명시 완료 환불 추출을 수정하며, 처리 중/예정/부정 환불을 완료로 승격하지 않는다.
- 영향 QA697 passed+47 subtests·skip0·compile PASS, 독립 검수210 passed/APPROVE 및 부정11/완료5 추가 파이프라인 PASS. 검수 runtimeInfo의 `codex/gpt-6.1-sol`·`medium`과 정확 SHA를 기록했다. CI run42555491219/job128960134984는 Billing/spending limit로 steps0 시작 불가였고 기존 2026-11-07 예외로 병합했다. 녹색 CI 또는 실제 실행 통과로 보고하지 않는다.
- 1,454 tracked blobs mismatch0, task/process/runtime SHA 일치, Gateway8790→loopback8751·listener1·health/ready200·보호 API401, 보호13표 전후 불변 PASS. 코드 전용이므로 전체 백업/복원은 반복하지 않았고 이전 릴리스/작업 복구점을 보존했다. 금융/Google/원문/여행 배정 쓰기·마이그레이션·대량 재처리0.
- 배포 릴리스의 호스트 Python으로 보존 원문 재추출 PASS. 날짜 표시 합성 PC1440/모바일390 before/after·넘침0과 독립 source/screenshot 검수 근거를 보존했다. 인증 운영 68장부의 실제 경고 감소·전체402행 원문 조사 완료·실기기/스크린리더는 미검증이다. 다음 원문의 렌터카 양식 누락은 별도 수정 중이며 이번 배포 완료에 포함하지 않는다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a.json`; 비공개 `.local-archive/service-date-row-audit-20261109/`의 최종 SHA 검수/실행모델 증명/QA/합성 화면/`deploy-flight-refund-c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a/`. 문서 전용 후속에는 재배포/재시작하지 않는다.

## 2026-11-08 여행 지출 복사 포커스 오류 복구 — 당시 운영 배포 / 후속 복사 수락으로 대체 예정

- [PR #749](https://github.com/6Soo/cost/pull/749) 운영 SHA `068de5da50611255dd4ef23d12f2a8272fe4b616`, 검수 코드 `4cc5ac3699948c828885fd46d84597e842618a71`와 webapp/tests tree 동일. 이전 운영 SHA `e1c60ad037eb6651d68058ea90ac57327e64ce20`. 아래 #744의 포커스 복원만으로 해결되지 않던 `Document is not focused` 오류에 대한 후속이다.
- 두 클립보드 API가 모두 거부해도 전체 TSV를 선택된 읽기 전용 입력에 남기고 직접 복사하거나 새 클릭으로 재시도할 수 있다. 재시도는 서버 재조회 없이 준비된 내용을 사용하고 성공 여부를 실제 결과대로 표시한다. 제외된 거래의 일자·가맹점·금액·상세 링크도 같은 최신 GET 응답에서 갱신한다. Google 대조·복사 대상 규칙, API 계약과 금융 처리는 변경하지 않았다.
- 정확한 코드 SHA의 영향 QA **305 passed +69 subtests, skip0, 필수 browser22/22, compile PASS**. TSV 경계 추가10건 통과. 실제 독립 `gpt-6.1-sol / medium` 최종 APPROVE 및 HIGH/MEDIUM 없음. CI run42473632476/job128709986234는 결제/사용한도 annotation·steps0 시작 차단으로 녹색이 아니며 2026-11-07 사용자 승인 예외를 적용했다.
- 합성 ego1440/390/320 동일 크기 전후·실제 운영 테마 초기화와 두 테마·키보드·페이지 넘침0 확인. 두 API 강제 거부 뒤 선택 텍스트 보존, 새 클릭 재시도 뒤 native Ctrl+V 내용 일치, TSV GET1회·POST0 확인. 실제 측정 안내문 대비 light7.5777/dark5.7053 이상. 초기 테마 적용이 잘못된 캡처는 근거에서 제외하고 재생성했다.
- 공식 보호 배포 증거: 1,447 tracked blobs mismatch0, runtime SHA verified, listener1·backend8752, health/ready200·보호 API3개401, 보호13표 전후 불변, financial_apply NOT_RUN. 완료 시각 2026-11-08 23:04 KST. 코드 전용 배포로 원본/금융/Google 쓰기·재처리·마이그레이션 없음. 중단 후 증거를 확인했으므로 재배포하지 않았다.
- **AUTH_UI_BLOCKED:** 재개 시 이전 인증 TaskSpace18이 `task space not found: 18`로 없어 운영 화면의 최종 복사→native 붙여넣기 해시 비교와 운영1440/390 캡처는 실행하지 못했다. 위 합성 검증을 인증 운영 수락으로 대체하지 않는다. 실기기/Safari·스크린리더 음성·실제200%확대·RTL도 미검증이다. 남은 작업은 허가된 인증 ego 세션에서 운영 GET/복사·붙여넣기 일치와 화면 확인이며 코드 재구현·재배포는 필요 없다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-068de5da50611255dd4ef23d12f2a8272fe4b616.json`, 비공개 `.local-archive/expense-copy-actionable-20261108/`의 deploy-evidence/release-audit/quality-final/junit-final/deploy-review 및 ego 결과. 고객 원문은 추적 문서에 포함하지 않는다. 후속 문서 전용 변경은 코드 검사·배포·서버 재시작을 반복하지 않는다.

## 2026-11-08 수집 현황·빈 기간 업로드 UX — 운영 배포 COMPLETE

- [PR #747](https://github.com/6Soo/cost/pull/747) 운영 SHA **`e1c60ad037eb6651d68058ea90ac57327e64ce20`**, 이전 검증 `a0d257c45fef1767d25d5269bbac0007c22e4f2e`. 빈 기간→업로드를 우선 배치하고 카드사별 기간을 짧은 목록으로 정리했다. 집계 타일·반복 설명·동일 높이 두 열을 제거하고 파일은 모든 기간 요약 아래 접었다. API·파일별 최초~최종일/카드사별 합집합 계산·DB·금융·owner/CSRF·Google 계약은 그대로다.
- 검증 코드 `e905a0d6a8324f048ce249197e447e65113d15e8`와 merge tree 동일. 영향 QA **238 passed +70 subtests·skip0·browser20/20·compile PASS**, 실제 독립 `gpt-6.1-sol / medium` 정확한 병합 SHA 코드/interface-review APPROVE. 초기 다크 라벨4.038:1 결함은 기존 ink 토큰으로9.8968:1로 고치고 두 테마 회귀를 추가했다. 초기 중단 QA를 통과로 세지 않았다. GitHub run42469738253/job128697483478는 결제/사용한도 annotation·steps0 시작 실패다. 기존2026-11-07 승인 예외를 적용했고 CI 녹색으로 보고하지 않는다.
- 합성 ego1440/390/320·두 테마·긴 파일명·공백해소/빈자료/날짜없음/불가/다수기간/오류복구·키보드 PASS. **인증 운영** 전후1440/390 및 배포후1440/390/320·두 테마에서 빈 기간 우선·파일23개 접힘·키보드 펼침·Enter 업로드의 기간 맥락/입력 포커스·넘침0 확인. 전후 GET200·카드사3/파일23/공백1 및 기간/공백 projection SHA-256 동일. 운영 대비light/dark 라벨17.0629/9.8968, 업로드5.3097/7.6095. 실제 기기/Safari·AT음성·실제200%확대·RTL은 미검증이다.
- 공식 PREVIEW→단일 APPLY:1,446 blobs mismatch0·task/process/runtime SHA 일치·Gateway8790→단일loopback8751·health/ready200·보호 API401·보호13표 불변·financial_apply NOT_RUN. 배포기는 기존 단일 작성자 잠금 해제를 기다린 뒤 전환했고 기존 처리 강제 종료나 잠금 우회를 하지 않았다. 코드 전용으로 이전 릴리스/task XML을 유지하고 전체 DB 백업/복원 반복은 생략했다. 원본/금융/Google 쓰기·운영 업로드 POST·마이그레이션·재처리 없음.
- 근거:호스트 `D:/WebLedgerHost/releases/deploy-evidence-e1c60ad037eb6651d68058ea90ac57327e64ce20.json`, 같은 SHA release-audit/continuous-switch, 비공개 `.local-archive/coverage-intent-ux-20261108/`의 quality-green·independent-review·production-baseline/after·동일크기 전후·보호 snapshot. 고객 원문/스크린샷은 추적 기록에서 제외한다. 후속 문서 전용 변경은 재검사·재배포·재시작하지 않는다.

## 2026-11-08 파일별 기본 조회기간·파일 사이 공백 — 운영 배포 COMPLETE

- 사용자 최신 교정에 따라 한 파일 내 최초~최종 거래일 전체를 기본 조회기간으로 간주한다. 내부 무거래일은 공백이 아니며 같은 카드사 파일들의 범위를 합친 뒤 파일 사이 빈 구간만 공백으로 표시한다. 예: 1~10일·15~20일 두 파일이면 공백11~14일 한곳, 같은 카드사 다른 카드 파일10~15일을 추가하면 공백0이다. [현행 명세](specs/card-transaction-date-gaps-20261108.md), [PR #745](https://github.com/6Soo/cost/pull/745).
- 코드 `20df129ec70f29d2c298cc9179edb7afa2e14580`: 영향 QA **236 passed +70 subtests·skip0·browser19/19·compile PASS**. 초기234통과/2실패는 구 내부공백 기대값이었으며 skip/제외 없이 새 계약과 파일 연결 회귀로 교정했다. 실제 독립 `gpt-6.1-sol / medium` 정확한 운영 병합 SHA **`a0d257c45fef1767d25d5269bbac0007c22e4f2e` APPROVE**, 검증 코드와 merge tree 동일.
- GitHub run42467211707/job128689384202는 결제/사용한도 annotation·steps0으로 시작 실패했다. CI 녹색으로 보고하지 않고2026-11-07 사용자 승인 예외(실제 Sol medium 정확SHA 승인·로컬 검증)를 적용했다.
- 실제 ego 합성 전후1440/390/320에서 페이지·패널 넘침0, 파일 범위/공백1→연결파일 후0, 빈자료·오류 재시도·키보드 포커스·공백 업로드 맥락을 확인했다. 두테마 안내문 대비 최소5.7053/7.5777이다. 독립 source interface와 별도 렌더링 검수 범위를 구분했다. 인증 고객 운영 시각 수락·실기기/Safari·AT음성·실제200%브라우저 확대·RTL은 미검증이다.
- 이전 실제 runtime `aa7d6a648118c907421e32234ca3837cc11c42a9`에서 공식 PREVIEW→APPLY 전환. 1,445 tracked blobs mismatch0·task/process/runtime SHA 일치, Gateway8790→loopback8752·health/ready200·보호 API401·보호13표 전후 불변·financial_apply NOT_RUN. 배포 코드의 합성 인메모리 범위/GET불변과 coverage API·화면 익명401도 PASS. 원본/금융/고객DB/Google 쓰기·재처리·스키마 변경 없음.
- 호스트 근거 `D:/WebLedgerHost/releases/deploy-evidence-a0d257c45fef1767d25d5269bbac0007c22e4f2e.json`, 비공개 `.local-archive/card-file-span-20261108/`의 quality-green·independent-review·ui-review·ego evidence·release-impact-smoke·보호 snapshot. 이전 검증 릴리스/task XML을 복구점으로 유지했고 코드 전용이므로 전체 DB 백업/복원 반복은 생략했다. 이 문서 후속으로 재배포하지 않는다.

## 2026-11-08 Google 장부 지출내용 복사 대조·클립보드 오류 — 운영 배포 COMPLETE

- 사용자 화면의 `장부에 있음`/`확인 필요`가 서로 다른 의미를 섞어 보이던 문제를 `Google 장부 일치`와 `Google 대조 보류`로 명확히 나눴다. `Google 장부 일치`는 `MATCHED_MANUAL` 또는 `MATCHED_EXISTING`으로 이미 Google 행과 확인된 건이고, `Google 대조 보류`는 `REVIEW_CONFLICT`로 후보가 여러 개이거나 금액·날짜·가맹점·승인번호만으로 Google 한 행을 안전하게 확정할 수 없는 건이다. 보류 건은 중복 복사를 막기 위해 제외하며 화면에서 사유별 건수를 펼쳐 볼 수 있다. `NEW_EXPENSE`만 복사 대상으로 유지한다.
- 브라우저가 포커스를 잃었을 때 `navigator.clipboard.writeText`가 `Document is not focused`로 실패하던 오류를 버튼 포커스 복원과 textarea 선택·`execCommand('copy')` fallback으로 수정했다. COST는 Google 장부에 쓰지 않는다.
- [PR #744](https://github.com/6Soo/cost/pull/744), 구현·운영 SHA **`aa7d6a648118c907421e32234ca3837cc11c42a9`**, 이전 실제 runtime `8341f266531a389a406eb8ce6486759366f03e87`. 표적 검사 `19 passed·skip 0`, tracked blobs 1,445·mismatch0, runtime/task/process SHA 일치, Gateway8790→loopback8751, health/ready200, 보호 API401, 보호 테이블13개 전후 불변, `financial_apply=NOT_RUN`이다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-aa7d6a648118c907421e32234ca3837cc11c42a9.json`, 비공개 `.local-archive/google-expense-copy-fix-20261108/`. GitHub impact-checks는 결제·인프라 제한으로 steps0에서 시작하지 못해 녹색으로 보고하지 않았다. 고객 원본·금융·Google 장부 쓰기·스키마 변경은 실행하지 않았다.

## 2026-11-08 카드사별 거래일자 합집합 공백 — 운영 배포 COMPLETE

- 사용자 결정에 따라 거래일자 공백의 그룹 기준을 카드 끝4자리에서 카드사로 변경했다. 같은 카드사의 모든 카드 거래일자를 합집합하고, 카드사 그룹의 최소·최대 거래일 사이를 공백으로 계산한다. [PR #742](https://github.com/6Soo/cost/pull/742).
- 커버리지/API/UI 표적 **49 passed, skip0**, compileall·diff-check PASS. 같은 카드사의 서로 다른 끝4자리 합성 거래가 하나의 카드사 그룹과 공백으로 합쳐지는 회귀를 확인했다. GitHub impact-checks는 billing 차단으로 steps0이어서 CI 녹색으로 보고하지 않았다.
- 운영 SHA **`8341f266531a389a406eb8ce6486759366f03e87`**, 이전 `43f49f91ecdd189c962e094f4bc671e76a72b86f`. 공식 PREVIEW→APPLY 완료, tracked blobs 1,445·mismatch0, runtime/task/process SHA 일치, Gateway8790→loopback8752, health/ready200, 보호 API401, 보호 테이블13개 전후 불변, `financial_apply=NOT_RUN`.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-8341f266531a389a406eb8ce6486759366f03e87.json`, 비공개 `.local-archive/issuer-date-union-20261108/`. 고객 원본·금융·Google 쓰기와 스키마 변경은 실행하지 않았다.

## 2026-11-08 여행 장부 독립 메뉴 제거 — 운영 배포 COMPLETE

- 사용자 결정에 따라 `여행 장부`를 전역 메뉴에서 제거하고 `여행 관리`를 여행 선택 진입점으로 사용한다. `/board`와 여행별 비용·수입·지출·환불·출력 기능은 유지하며, 항공권·영수증·예약 연결·Google 복귀 문구를 `여행별 비용`으로 통일했다. 카드 폐지 질문 UI 후속도 함께 반영했다. [PR #740](https://github.com/6Soo/cost/pull/740).
- 표적 QA **42 passed, skip0**, 공통 사이드바 브라우저 **2 passed + 9 subtests**, compileall/diff-check PASS. GitHub impact-checks는 billing 차단으로 steps0이어서 CI 녹색으로 보고하지 않고 승인 예외를 적용했다.
- 운영 SHA **`43f49f91ecdd189c962e094f4bc671e76a72b86f`**, 이전 `e90c4b6c0e718e0d98da65ed44f5bb29257cc3cd`. 공식 PREVIEW→APPLY 완료, tracked blobs 1,445·mismatch0, task/process/runtime SHA 일치, Gateway8790→loopback8751, health/ready200, 보호 API401, 보호 테이블13개 전후 불변, `financial_apply=NOT_RUN`.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-43f49f91ecdd189c962e094f4bc671e76a72b86f.json`, 비공개 `.local-archive/trip-management-ledger-20261108/`. 실제 금융·Google·고객 원본 쓰기와 스키마 변경은 실행하지 않았다.

## 2026-11-08 카드 최종 귀속·P3 작업 기능 폐지 — 운영 배포 COMPLETE

- 최신 실행 정본에 따라 카드의 미배정·확인필요·처리필요·미분류 작업 UI와 P3 질문/답변 경로를 폐지하고, 실제 여행 또는 결제일·매입일 기준 기타비용 귀속을 적용했다. 원본 오류·충돌·중복·환불·수동 교정·owner/CSRF 보호와 감사 이력은 유지했다.
- PR [#737](https://github.com/6Soo/cost/pull/737), 병합·운영 SHA `e90c4b6c0e718e0d98da65ed44f5bb29257cc3cd`, 이전 실제 runtime `d043892777dc50d1e61d3478440f4148719fd39f`. 영향 QA 121 passed·skip0, compileall·diff-check PASS. GitHub impact-checks는 billing/infrastructure로 steps0에서 실패해 CI 녹색으로 보고하지 않고 승인된 예외를 적용했다.
- 공식 `deploy_verified_release.ps1` PREVIEW→APPLY 완료. 1,445 tracked blobs mismatch0, task/process SHA와 runtime SHA 일치, Gateway8790→loopback8752, health/ready200, 보호 API401, 보호 테이블13개 전후 불변, `financial_apply=NOT_RUN`. 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-e90c4b6c0e718e0d98da65ed44f5bb29257cc3cd.json`, 비공개 `.local-archive/card-destination-ux-20261108/`.
- 첫 APPLY는 문서상의 이전 SHA가 실제 task SHA와 달라 `TASK_SHA_INVALID`로 전환 전 중단됐고, 현재 task/runtime을 재확인한 실제 이전 SHA로 재시도해 통과했다. 고객 원본·Google 장부·금융 적용·스키마 변경은 실행하지 않았다. 이 기록 후속 문서 변경으로 재배포하지 않는다.

## 2026-11-08 미커밋 전체 검토·통합 운영 배포 — COMPLETE

- 사용자 `미커밋 변경사항까지 모두 검토해서 배포`와 `모두 확인해서 메인으로 병합 운영배포해` 범위. [PR #735](https://github.com/6Soo/cost/pull/735), 검수 HEAD `1ee5c6983f11e59bb1a2b52f3df90f1eab487165`, 운영 SHA `d043892777dc50d1e61d3478440f4148719fd39f`. [28파일 판정·수락 기록](specs/review-all-uncommitted-release-20261108.md). 원래 로컬8커밋의 이력과 미커밋25·미추적3파일을 모두 검토했다. 유효 변경은 통합하고 원본/권한/환불 보호 제거는 제외·보존했다. 영수증 PR733도 같은 SHA로 운영 반영했다.
- 어드벤처코리아 항공료, 여행 관리 단일 집계, 모바일 수입/보험/금액, 실제 OPEN 사용자 작업, 행별 지출 복사, 정상 구매의 유효한 결제 분기 fallback을 반영했다. 조회 실패를 0건으로 숨기지 않고 정상 P1/P2를 사용자 업무로 만들지 않는다. 메일 캐시의 disabled-gate 의존성과 짧은 보험 문구에서 긴 날짜/이름이 겹치는 결함도 수정했다.
- 최종 Windows 영향 QA **1166 passed +133 subtests, skip0, 필수 브라우저 72/72, compile PASS**. 초기6실패와 모바일 겹침 red는 보존했고 최종 고정SHA에서 교정 후 통과했다. 독립 실제 `gpt-6.1-sol / medium` 정확SHA 승인·interface-review Approve. CI42411351988/job128519990700은 결제/사용 한도로 steps0에서 차단돼 기존 승인 예외를 적용했으며 CI 녹색으로 보고하지 않는다.
- 공식 SHA 고정 git archive·tracked blob mismatch0, 단일 배포 lock·PREVIEW/APPLY 완료. 이전 `d97158484d17f974668dafffafdb1a7b462a7249`에서 전환했고 runtime/task/process SHA 일치, loopback backend, health/ready200·보호 API401·보호 테이블13개 불변을 확인했다. 운영 분류/여행 교정·재처리·원본/금융/Google 쓰기·마이그레이션은 실행하지 않았다.
- 인증 GET 수락: 카드·여행·영수증 영향 화면 main/heading 및 coverage API200 확인. 고객 원본 파일 확인 POST는 실행하지 않았다. 합성 1440/390/320 동일크기 전후 및 짧은 보험 stress에서 페이지 넘침0·텍스트 행 침범0, 키보드 포커스와 light7.5777:1/dark5.7053:1 대비 확인. 전체 고객 화면 시각 수락·실제 기기·스크린리더 음성·RTL/OS확대는 미검증이다. 과거 고객 영수증 파일을 복구했다고 주장하지 않는다.
- root main은 보존 stash `484adc3acd41374568e1ac39e4f18d4d0d2a8b60` 생성 후 정상 fast-forward했다. 기존 stash6개와 원본28파일 snapshot은 모두 보존했다. 비공개 근거 `.local-archive/uncommitted-release-20261108/` 및 `.local-archive/all-main-review-20261108/`. 이 후속 기록은 문서 전용이며 재배포하지 않는다.

## 2026-11-08 카드 내역 거래일자 공백 전환 #731 운영 완료

- 최신 사용자 결정에 따라 조회기간 대시보드·확인/관리 시작일 폼을 폐기하고 실제 거래일 사이 공백으로 전환했다. 카드사·끝4자리 표시 그룹별 첫/마지막 거래일 내부만 계산하며, 정상 미사용일일 수 있으므로 자료 누락으로 단정하지 않는다. [수락 계약](specs/card-transaction-date-gaps-20261108.md), [PR #731](https://github.com/6Soo/cost/pull/731).
- 정확한 검수 HEAD `4c2120fd6ab0d9f2a06a9f35d6b78b2e35b50fae`: Windows 영향 QA **503 passed +100 subtests, skip0, browser35/35, compile/데이터 보호 PASS**. 초기 red3은 기준 커밋에도 존재하는 오래된 브라우저 테스트명2와 구 조회기간 표시를 기대한 인증 HTTP 검사1이며, 검사를 제외하지 않고 현재 동작·보호 계약에 맞게 고쳐 green으로 재검증했다.
- Sol `gpt-6.1-sol` / `medium`의 실제 Paseo runtimeInfo를 확인하고 위 HEAD 최종 PASS 및 병합 SHA 동일 트리 검수를 받았다. GitHub run42407181997/job128507289518은 결제 실패/지출 한도로 steps0에서 차단됐다. 2026-11-07 사용자 승인 예외를 적용했고 CI를 녹색으로 표시하지 않는다.
- 운영 SHA **`d97158484d17f974668dafffafdb1a7b462a7249`**, 이전 `3dfcd72405d602504b6b8842d53e957aba31f929`. 승인 HEAD와 병합 SHA tree `a1e3a385e328c2aaca4a89bfa35b35468927de2b` 동일. 공식 PREVIEW→APPLY 1회, 1,435 tracked blobs mismatch0/list mismatch0. 단일 task/process SHA 일치, Gateway8790→loopback8752, health/ready200·보호API401, 보호13표 전후 불변. 롤백 릴리스와 task 복구점 유지. 운영 DB/원본/분류/환불/Google 쓰기·스키마 변경 없음, financial_apply NOT_RUN.
- ego-browser 합성 전후1440/390/320px, 긴 파일명·22구간 접기/펼치기·공백→업로드·포커스/Escape·빈 상태/오류 재시도 PASS, 다크 요약 라벨 대비4.04→9.90:1 수정. 720 CSS px의200% 상당 reflow 확인; 실제 브라우저 확대·스크린리더·실기기·RTL 미검증.
- 인증된 운영 GET/API·DOM에서 **23파일/27표시그룹/515공백/날짜없는파일0**, 거래일자 상태·coverage panel 및 구 조회기간/관리 시작일 폼0 확인. 운영 DB mode=ro 사전 집계156ms. 이는 전체 고객 화면의 독립 시각 수락·전후 운영 진입성능 측정 완료를 뜻하지 않는다. 고객 파일명·거래 원문은 보고서/Git에 넣지 않았다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-d97158484d17f974668dafffafdb1a7b462a7249.json`, 비공개 `C:/AX/cost/.local-archive/transaction-gaps-20261108/`의 배포/사후 smoke/보호표·QA·독립 검토·브라우저 기록. 기존 main의 다른 미배포 로컬 커밋8개는 포함하지 않고 보존했다. 이 운영 기록 등 문서-only 후속은 재배포하지 않는다.
