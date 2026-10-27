# 운영 기록과 실행 경계

## 마지막 확인된 운영 코드

**`f7df4bc29d4e9dc87b2f6ddd68b8853c7be9be3a`**, 2026-10-28 [PR #211](https://github.com/6Soo/cost/pull/211). RF-004 테스트 환경 정적 조사 CLI와 RF-001 간접 경계 소스 근거를 추가했다. 애플리케이션 런타임 구현·스키마·금융 규칙 변경은 없다.

- 합성6 passed. staging 후 조사와 배포본 CLI 스모크 exit0: Python3.14.7, 추적 테스트 소스294개·정의 후보3,957개·오류0. pytest.ini 포함295개 중 환경 근거83·UNVERIFIED212이며 collection/실행 통과 수가 아니다. 전체 회귀·브라우저는 독립 개발 도구/문서 변경이므로 생략했다. 추적자료 guard4파일·차단0·삭제0.
- 추적942개 blob 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 직전 `bff4ffd`와 작업 XML·게이트 사본·기존 검증 복원 사본 보존. 배포 후2DB/13표 내용·스키마 동일. 운영 DB/Google/원본/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-f7df4bc29d4e9dc87b2f6ddd68b8853c7be9be3a.json`, 같은 SHA release-audit, `.local-archive/r0-boundary-baseline-20261028/`의 고정 배포·보호 전후. 이번 산출물은 R0 일부 근거이며 전체 리팩터링·실자료 수락 완료가 아니다. 이후 문서 전용 갱신으로 재배포하지 않는다.

## 직전 환불·Toyoko·R0 도구 릴리스

**`bff4ffde1ef7bb381f0b3da611f78a7dda5e2d1b`**, 2026-10-28. PR #193 카카오 환불 추론/표시·기장 보류 보호, PR #207/#208 Toyoko 제목 탐색/인증 메일 유지/불량 헤더 격리, PR #202~#206/#209 R0 정적 도구를 검수·병합한 고정 릴리스다. 인수 시 배포가 이미 완료돼 있었으며 재배포하지 않고 남은 사후 검증을 마쳤다.

- 배포 evidence: 추적940개 blob 일치·불일치0, 작업/프로세스 SHA 일치, Running·단일 loopback listener, health/ready200·비인증 보호API401. 직전 `44e1e6b` 릴리스·작업 XML·게이트 사본과 기존 검증 복원 사본 보존.
- 인수 후 읽기 전용 비교에서 2DB/13개 보호 표 내용·스키마 전후 동일. Aside CLI 실제 환불 화면121개 묶음, 추론2개에 **기록 보류 · 환급 완료 아님** 표시, 검토 링크·가로넘침 없음 확인 후 원래 화면 복귀. 실제 환급·개별 고객 사례 해결·Toyoko 실메일 재수집 수락으로 확대하지 않는다. DB/Google/원본/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음.
- 기존 유효 검사 재사용: 환불 통합 후29+6+117+26 passed(선행178 passed), Toyoko105+6 passed·통합42 passed·헤더/인증 회귀8 passed, R0 호출3/쓰기4/자료16/선택기7/의존성8/여행감사5 passed. 기존 기준선 backend2 failed와 Windows 묶음 SQLite 정리6 errors는 통과로 계산하지 않는다. 분리 표적 검사는 통과했으며 전체 회귀는 재실행하지 않았다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-bff4ffde1ef7bb381f0b3da611f78a7dda5e2d1b.json`, 같은 SHA release-audit, `.local-archive/refactor-runtime-release-20261028/`의 보호 전후·브라우저 집계. 남은3개 구현 worktree는 고유커밋0·dirty0·미추적0·터미널0·무시 파일은 캐시만임을 확인하고 공식 archive 완료. 공유 stash와 사용자 미추적 자료 보존.
- R0 정적 도구 배포는 전면 리팩터링 완료가 아니다. 간접 저장/audit·권한 및 데이터 분류의 OPEN_QUESTION은 현재 상태에서 계속 추적한다. 뒤따르는 문서 전용 변경은 재배포하지 않는다.

## 직전 Trip.com 릴리스

**`44e1e6bb90105e5d65c1b954f0c9808f4266b407`**, 2026-10-28 [PR #200](https://github.com/6Soo/cost/pull/200). 코드 `8e5eb76`의 Trip.com 동일 통화 근거 비교/FX 근거 부족 표시, OTA 확정 라벨, 카드 미배정·카드·검색 필터, 여행 장부 이용일/수입 계산 안내를 검수 후 SHA 고정 배포했다. 기존 PR #198 복사를 보존했다.

- 925개 추적 blob 일치, 작업/프로세스 SHA 일치, WebLedger-Board Running·단일 loopback listener. health/ready200·비인증 보호API401. 이전 `b860398` 릴리스·작업 XML·게이트 사본·검증 복원 사본 보존.
- 보호 대상 2DB/13표 내용·스키마 전후 동일. 실제 여행 복사 버튼1개·총수입−지출 안내, 카드 미배정 체크·카드/검색 필터·월 상세·마스킹 식별 표시·페이지 가로넘침 없음 확인 후 원래 화면 복귀. 고객 원문·끝자리·금액을 보고서로 저장하지 않았다. DB/Google/원본/금융 상태/운영 클립보드 쓰기·마이그레이션·대량 재처리 없음.
- 표적/인접190 passed. 추가 카드조회/OTA backend/projection/여행유효성125 passed·2 failed. 기준 main `0b9ebf4`에서 동일127개 묶음 실행으로 두 실패 재현(부분 그룹 fixture HOLD_NO_CARD/정리 시 Windows 열린DB 및 후속 스키마 준비 오류). 실패를 통과로 계산하지 않았고 범위 밖 수정은 하지 않았다. 전체 회귀는 국소 비교/읽기 표시 변경이므로 생략.
- 근거: `D:/WebLedgerHost/releases/release-audit-44e1e6bb90105e5d65c1b954f0c9808f4266b407.json`, 같은 SHA의 배포 evidence, `.local-archive/refactor-review-20261028/`의 배포/보호 스크립트·전후 해시·브라우저 집계. Aside CLI를 사용했다. 코드 미통합 임시 worktree와 PR #193은 이번 배포에 포함하지 않았다. 뒤따르는 문서만의 갱신으로 재배포하지 않는다.

## 직전 여행 복사 릴리스

**`b8603980aabee7143f0481a8751c0c6b4a210044`**, 2026-10-28 [PR #198](https://github.com/6Soo/cost/pull/198) 여행 탭 하단 지출 복사. 인계 코드 `a3e0316`에 검수 보완 `75aa984`를 추가했다. 실제 여행의 현재 표시 지출만 공통 B:H TSV 보호 로직으로 복사하며 날짜·금액·증빙·중복 오류는 제외 건수를 표시한다. Google 자동 쓰기는 없다.

- 추적921개 blob 일치, 작업/프로세스 SHA 일치, 단일127.0.0.1 listener, health/ready200·비인증 보호API401. 직전 `a56b53d` 릴리스와 기존 복구 사본·복원 검증 근거를 보존했다.
- 2DB/13개 보호 표 내용·스키마 전후 동일. 실제 여행 하단 버튼과 읽기 전용 TSV200·28건·전 행7열·보류0건, 비여행 버튼0개 확인 후 원래 여행 화면 복귀. 실제 고객 원문은 보고·Git에 저장하지 않았고 운영 클립보드도 쓰지 않았다.
- 표적·인접 검사59 passed 및4 subtests, 최종 API/TSV/adapter28 passed. 합성 클립보드 값과 owner/viewer/비로그인 보호 검증. 전체 회귀는 국소 읽기·복사 변경이므로 생략했다. DB/원본/Google/금융 상태 쓰기·마이그레이션·대량 재처리 없음.
- 근거: `D:/WebLedgerHost/releases/release-audit-b8603980aabee7143f0481a8751c0c6b4a210044.json`, 같은 SHA의 `deploy-evidence-*.json`, `.local-archive/session-review-20261028/`의 배포 스크립트·보호 전후·브라우저 집계. PR #197은 문서만 추가한 선행 main 변경이며 새 리팩터링 실행 과제가 아니다. PR #193 및 미완료 Cost V35 worktree는 미포함. 뒤따르는 증거 문서 갱신으로 재배포하지 않는다.

## 2026-10-27 OTA 배포 기록

**`a56b53da170b8e7ae8bf20f8899199c2b8cf8c18`**, 2026-10-27 [PR #195](https://github.com/6Soo/cost/pull/195) OTA 자동 배정·사후 교정·테마 대비 개선. 코드 커밋은 `55f57bb96ba02cea7ab193c03b8449a3cc379e6c`다.

| 검사 | 이번 실제 결과 |
| --- | --- |
| 릴리스·실행 | Git 추적917개 blob 일치, 작업/프로세스 SHA 일치, WebLedger-Board Running·127.0.0.1 단일 listener |
| 상태·인증·복구 | health/ready200·보호API401. 직전183d813 고정 릴리스와 기존 검증 복원 사본 보존 |
| 금융 보존 | 2DB/13개 보호 표 내용·스키마 전후 동일. 원본·장부·금융 분류·Google 쓰기·실자료 배정 저장/해제·대량 재분류 없음 |
| OTA 실제 집계 | 색인 ready. 전체2,271·자동추론896·미배정170·취소/해제 제외974. 미배정: 기간 없음88·후보 없음73·기간 충돌9 |
| 변경 영향 | 기존 색인 비교에서 준비 숙박45건 추가, 원본 기간 충돌9건 자동배정 보류. 실제 수정 화면에 현재 여행 선택·다른 여행 목록·근거 입력 확인 |
| 색·검증 | 실제 밝은/어두운 안내 상자 배경/글자 확인·원래 테마 복귀. 합성 수동 전환 대비4.5:1 이상. OTA38·인접8·목록브라우저2 통과, 전체 회귀는 단일 파생 화면 범위로 생략 |

근거: `D:/WebLedgerHost/releases/release-audit-a56b53da170b8e7ae8bf20f8899199c2b8cf8c18.json`, 같은 SHA의 `deploy-evidence-*.json`, `.local-archive/ota-auto-trip-20261027/`의 읽기 전용 집계·브라우저·보호 비교·배포 스크립트. 갱신 중 화면과 최종 ready를 구분해 확인했다. 사용자 수정의 실제 저장은 합성 DB에서 검증했고 운영 자료를 저장해 시험하지 않았다. 별도 미검증 PR #193은 병합하지 않았다. 이어지는 문서 반영은 문서 전용이며 재배포하지 않는다.

## 직전 배포 기록

**`183d813301a4fcc4cab78d52a8d7e2ff2074be63`**, 2026-10-27 [PR #189](https://github.com/6Soo/cost/pull/189)/[#190](https://github.com/6Soo/cost/pull/190) 통합 배포. 문서 정리 과정에서 런타임을 다시 확인하거나 배포하지 않았다. 이후 문서 전용 커밋은 운영 코드 SHA를 바꾸지 않는다.

| 검사 | 보관된 결과 |
| --- | --- |
| 고정 릴리스 | Git 추적982개 blob 일치·불일치0 |
| 실행 신원 | WebLedger-Board Running, 작업·리스너 프로세스 SHA 일치, 127.0.0.1:8751 단일 listener |
| 상태·인증 | health/ready200, 비인증 보호 API401 |
| 금융 보존 | 2DB/13개 보호 표의 내용·스키마 해시 전후 동일 |
| 복구 기준 | 이전 `84e602ee76f4b50a072e43520af3cd886cebb423` 고정 릴리스와 기존 검증 복원 사본 보존 |
| 변경 경로 | 로그인 `/import` OTA 초기 접힘·API0건, 펼침200·재접힘. 장부 검색의 전체/결과 지출 구분 및 원래 화면 복귀 |
| 표적 검증 | 수입 요약9·인접 불일치 브라우저1·OTA 계약/선택 보존2·직접 링크2 통과. 인접 기존 실패는 기준 main에서도 동일 재현 |

배포 증거는 `D:/WebLedgerHost/releases/release-audit-183d813301a4fcc4cab78d52a8d7e2ff2074be63.json`, 같은 SHA의 `deploy-evidence-*.json`, `.local-archive/income-summary-fix-20261027/`의 보호 전후·기준 실패 비교·`release-smoke.json`·`browser-smoke.json`이다. 경고 상태 두 가지는 배포 모듈의 합성 입력으로 검증했으며 실제 고객 자료에 경고를 만들지 않았다.

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

## 문서만 바꾸는 경우

diff·링크·현재/과거 구분·실제 문서 참조 경로만 확인한다. 코드 테스트·빌드·브라우저·운영 DB 확인·백업·재배포·서버 재시작은 하지 않는다. 이전 기록의 유효한 검증을 단순 안심 목적으로 반복하지 않는다.

## 과거 근거 찾기

- [운영·검증 전문](history/operations-through-20261027.md): 이전 `operations.md` 전체와 10월7일 이전 기록, 메일 조사.
- [구현·검토·계획](history/implementation-and-audits.md): 각 변경의 표적 명령·실패 비교·화면 수락 경계.
- [제품 결정·옛 인계](history/product-and-handoffs.md): 이전 상태표와 정책 변경 당시 기록.
- [옛 경로별 위치](history/README.md#옛-경로-찾기): 통합 전 파일명으로 검색.

과거 기록의 운영 SHA·미구현·HOLD는 해당 시점의 근거다. 현재 런타임 또는 새 개발 권한으로 해석하지 않는다. 콘솔 창 다음 예약 실행 수락은 여전히 NOT_RUN이다.
