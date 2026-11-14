# 운영 기록

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

## 2026-11-13 22:00 창 — `db848712` 배포·Booking 132건·증분 P2 첫 실행

- **배포:** `dc6e9631` → `db8487129318900c0d324dcd241f4d3211fbcbfb`(#845·#847·#826·#852·#853·#856·#851·#854), 23:18:44 KST, Board 8752. 공식 도구 1회 성공분 기준 파일 1,762·blob 불일치 0, health/ready 200, 비인증 API 401, 보호 13표 불변, 배포 뒤 5분 readyz 10/10. 검수는 PR별 claude opus·sonnet, codex gpt-6.1-sol medium APPROVE(CI 결제 한도).
  - 1차 22:28:37 시작은 22:34:32 `PREPARED_BACKEND_NOT_READY`로 실패했고 도구가 자동 롤백했다(경로 pause 전 단계라 공개 중단 없음). 원인은 CPU 100% 지속으로 후보 백엔드가 대기 한도 안에 준비되지 않은 것이다. 23:06:25 재시도에서 성공했다. 전환 중 경로 pause 구간 길이는 측정하지 않았다.
  - 창 단위 묶음 영향 검사(`run_quality_checks --base dc6e9631 --head db848712`)는 부하로 51%에서 중단했다(중단 전 실패 표시 없음). 통과로 보지 않는다.
- **Booking 여행 화면 가져오기**(#826 도구): 경로 유지·Board/Worker 정지 23:50:32~00:17:36(약 27분, 백업·복원 확인 00:12:39). 추가 132·중복 0·충돌 0, 삽입 132, 재실행 추가 0·중복 132. 재시작 뒤 00:21:07까지와 00:25:40~00:28:35에 readyz가 15~30초 시간 초과였다.
- **증분 P2 첫 실제 실행:** 00:32:27~00:40:00, `--propose-only`. 대상 4가맹점·4행, 모델 호출 1·성공 1, 제안 4건 모두 기존 항목 유지, 반영 0. 실행 성공률 1.0(분모 1). apply는 소유자 로그인 페이지(CSRF)를 확보하지 못해(로그인 홈이 Cloudflare 502) 실행하지 않았다.
- **3분기 장부 행 없는 4건:** 반영 0. 구매 2건은 AI 검수 판정(`quarter:2026:3`)으로 운영 DB 사본 예행만 했다(ready 1·기록 1·재실행 0, 건별). 운영 반영은 다음 창이다. 취소 2건은 규칙 개정 대기다.
- **3분기 붙여넣기 묶음:** `quarter-review-2026Q3/paste-pack-20261114-0049/`. 탭 합계 22/22 일치, 보류 0, 완결성 `mismatch`(NO_LEDGER_ROW 4).
- 근거: `D:/WebLedgerHost/data/backups/`의 `deploy-db848712/`, `booking-import-20261113/`, `p2-incremental-20261114/`, `no-ledger-row-2026Q3/quarter-rehearsal.json`, `releases/continuous-switch-db848712….failure.json`.

## 2026-11-13 배포 6회·운영 반영 4묶음

- **운영 방식 결정(소유자, 2026-11-13):** 운영 배포·자료 반영은 하루 1~2회 정해진 창(예: 06:00, 필요하면 22:00)으로 묶는다. 운영 장애 수정만 즉시 한다. 2026-10-15의 "변경마다 자동 배포" 지시를 대체한다.
- 배포는 모두 공식 `deploy_verified_release.ps1` 1회씩이다. 매번 blob 불일치 0, runtime/listener SHA 일치, health/ready 200, 비인증 API 401, 보호 13표 불변이다. 코드 배포라 fresh_backup_restore=false다. 검수는 PR별 Claude opus/sonnet APPROVE다(CI 결제 한도, 소유자 승인 대체 2026-11-13).

| 완료(KST) | 이전 → 운영 | 포트 | 포함 PR | 영향 검사 |
| --- | --- | --- | --- | --- |
| 02:37 | `335b9eda` → `4eaed971874d7732a455303fb47fc8163f667785` | 8752 | #819, #818, #824 | 790 pass·skip 0 |
| 03:28 | `4eaed971` → `d8c785cbca3ed7b3188920fb8b768918758dc158` | 8751 | #820, #823, #827 | 571 pass·skip 0 |
| 07:48 | `d8c785cb` → `a1954ce23507b18d4aea09813c4eebb0ff99ffa7` | 8752 | #825, #828~#831, #833~#836 | 566 pass·skip 0 |
| 09:41 | `a1954ce2` → `68b5ec4ab0f72dccf13e1bde3f6066d2d95402eb` | 8751 | #832, #837~#840 | 569 pass·skip 0 |
| 13:47 | `68b5ec4a` → `96fb90e8096bc42a205515e9bc470b5ce9ca3fe4` | 8752 | #822, #841~#844 | 539 pass·skip 0 |
| 14:57 | `96fb90e8` → `dc6e9631100c97aff52dca1e533ec00b8c714a2f` | 8751 | #846, #848 | 575 pass·skip 0 |

- 배포 뒤 readyz 관찰 로그는 `dc6e9631`만 있다(5분 10표본 중 200이 8). 나머지 배포의 전환 중 중단 시간은 측정 기록이 없다.
- **준비비 없음 정리**(#819 도구, 릴리스 `4eaed971`): 중단 02:49:34~03:16:15(경로 pause, 약 27분). 백업·복원 확인 02:57:02. 열린 여행 행 2,017 중 이동 14·보존 2,003(제외: 준비 미입증 1,767·수동/사용자 예외 208·닫힌 카드 기간 23·예약/예외 근거 4·환불 불가 구성원 1). digest `8d53400e…` APPLIED, 재실행 변화 0.
- **3분기 일괄 소유자 확인 교정 302 + AI 검수 교정 185**(#833·#829 도구, 릴리스 `a1954ce2`): 1차 08:01:08~08:09:14는 경로 pause 상태라 일괄 반영이 `ROUTE_INVALID`로 쓰기 전에 실패해 복귀했다(약 8분 중단, 변경 0). 2차 08:10:43~08:25:41은 경로를 유지하고 Board·Worker만 멈췄다(약 15분 중단). 백업 1(08:17:30) 뒤 일괄: 소유자 표시 421행 중 교정 302, 제외 수동/사용자 예외 117·개별 표시 2, digest `5214fbbe…`. 백업 2(08:24:15) 뒤 AI: 목록 198행 중 185 반영(항목만 43·여행→분기 100·여행→여행 42, 환불 이동 6행/3묶음), 제외 귀속 불일치 12·환불 불가 구성원 1, digest `1fd9e489…`. 두 재실행 모두 변화 0.
- **하나카드 이중 수입 정리**(#832 도구, 릴리스 `68b5ec4a`): 중단 09:52:03~09:58:42(경로 유지·Board/Worker 정지, 약 7분). 백업 09:57:14. 확정 쌍 308 중 191쌍 중복 표시·장부 해제 191, 이동 0, 제외 원본 보호 108·가맹점 불일치 4·환불 짝 3·수동 교정 2. digest `23360c21…` APPLIED, 재실행 변화 0. 반영 전 사본 예행 4회.
- **화순 일정 개정**(TRIP-098 소유자 결정, #841 도구, 릴리스 `96fb90e8`): 13:49:56 `trip-authority.json`의 `0823_화순` 종료일을 하루 늘렸다(권한 파일 sha `d6ff4666…` → `09ac7a6e…`). 서버 정지 기록 없음.
- 숲 귀속·근거(#812), dist141 출처 정정(#813), 닫힌 기간 741건(#815)은 11-12 반영이며 아래 11-12 절에 있다.
- 증분 P2는 이날 dry-run만 했다(14:27~14:37 KST, 실제 호출·반영 0). 운영 SHA `dc6e9631` 뒤 #845·#847·#826은 병합됐으나 미배포다.
- 근거: `D:/WebLedgerHost/data/backups/`의 `deploy-<sha>/`(review·deploy-evidence·protection), `no-preparation-cost-20261112/`, `ai-quarter-review-2026Q3/apply*/`, `hana-double-import-20261113/apply/`, `trip-schedule-revision-20261113/receipt/`의 preview·applied·replay·run.log, `D:/WebLedgerHost/releases/deploy-evidence-*.json`.

## 2026-11-12 밤 #815 배포·완료 기간 정리 운영 기록

- #815 병합 `335b9eda56b73fd65e201f39a1ffdefd82c955f3`를 22:46~22:47 KST 배포했다(Board 8751). 배포 근거는 22:47:36 KST health/ready 200·보호13표 불변이며 배포 중단은 없었다.
- 완료 기간 정리741건 반영(2025년739·2026Q1 2), 하쿠산 귀속 −739·세토우치 −2. 기존 장부·화면 행 변화0, 재실행 `REPLAYED`·이동0·실행변경0이다. preview/applied/replay의 digest와 건수를 직접 대조했다.
- 반영 중 헤드 호출 세션의 실행이 끊겨 22:57:41~23:14:40 KST 공개 장부가 중단됐다(시작은 헤드 전달 시각). 분리 프로세스가 남은 반영을 완료했고 resume.log에서 23:14:33 반영·재실행 성공, 23:14:39 Board ready, 23:14:40 route resume·Worker 시작을 확인했다.
- 직접 확인 근거: `D:/WebLedgerHost/data/backups/closed-period-grouping-20261112/`의 `preview.json`·`applied.json`·`replay.json`·`resume.log`·`backup-restore.json`·`operating-release/deploy-evidence.json`. 신선 백업5DB·44파일의 복원·원본 불변·review binding 동등 확인과, 코드 배포의 fresh_backup_restore=false는 서로 다른 기록이다.

## 2026-11-12 #813 배포·dist141 출처 정정 반영

- 09:48:08~09:49:10 KST 헤드가 정식 배포 도구로 `9b019761` → `43acce8768a4b990776d7acb34a539915a3628e2` 전환. Board 8752, Worker 같은 SHA, readyz 200(로컬·공개), 비로그인 API 401, 보호 표 13개 불변.
- 정정 반영은 서버 정지가 필요하다. 1차(10:07:11~10:09:40)는 `verify_operational_backup_restore.py`가 실패해 변경 0건으로 복귀했다. 원인: Gateway가 `config/ledger-gateway-status.json`을 수 초마다 갱신해 백업 전후 파일 해시가 달라진다. 2차(10:11:15~10:20:55)는 경로 pause → Worker·Board 정지 → **Gateway 정지** → 백업·복원 검증(약 4분) → `--apply`(약 5분) → Gateway·Board 재시작 → resume → Worker 순으로 통과했다. 공개 장부 중단은 두 구간 합계 약 12분이다. 1차의 불완전한 백업 폴더는 삭제했다.
- 결과: 정정 78(열린 74·닫힌 4), 귀속·항목 변경 24, 닫힌 분기 변경 0, `board.sqlite` quick_check ok. 실화면 이용일 경고 70 → 58. 건수 외 자료는 비공개 `forest-portal/link108-provenance/`에 있다.

## 2026-11-12 #812 전환 복구·산림 근거 수입

- #812 병합 직후 담당 세션이 종료되어 08:26~08:29:30 KST 공개 장부 응답이 중단됐다. 헤드가 전환 스크립트의 남은 단계를 이어서 완료했다. 운영 SHA는 `9b019761479b03f380133746a208c198ace33864`, Board 8751, readyz 200이며 `releases/deploy-evidence-9b019761….json`이 근거다.
- 전후 보호 표 13개는 불변이다. 산림 포털 예약 55건을 수입하고 충돌 1건은 기존 행을 보존했다. 귀속 18건은 기존 교정 경로로 반영했다. 수입 뒤 실화면 이용일 경고는 70건이며, 귀속 교정과 이용기간 확인을 구분한다.
- 후속 LINK-108·dist141 출처 정정은 별도 PR의 사본 예행·검수까지만 승인됐다. 그 PR의 병합·배포·운영 `--apply`는 헤드의 후속 작업이다. 기존 미푸시 문서 `ce418dae`는 내용 보존하여 이 브랜치에 가져왔다.
- 후속 사본 예행은 기간 표시 13/18(공통12·정확1), 오부착0·대상 밖 새 부착0이다. dist141 정정 대상78(열린74·닫힌4), 이후 결정/override 등 보존 제외63, P1 귀속·항목 변경24·닫힌 변경0, 원복78·보호 표 불변이다. 이는 운영 실화면 측정이 아니다. 실제 운영 반영 명령과 복구 게이트는 [절차서](playbooks/dist141-provenance-repair.md)에 있다.

## 2026-11-12 OTA 마무리 — 69건 읽기 전용 조사

- Fable이 실화면69건을 새 기준으로 확정하고 이전148건 기준과 추가 수집을 종료했다. 포털18건은 정확금액/예약번호 일치 없음13·취소환불 결제 미검증2·기연결 취소 기간 표시 제외1·Booking 수입 경로 없음2다. 미반영 충돌10은 상태+금액 구성4·상태만2·상태+끝자리 신규 관측4이며 기간 차이와18건 관련 정확 대조는0이다.
- 나머지51건은 산림휴양시설19·결제대행/실업종 미확인14·항공 관련6(항공사 식별5·관련 법인1)·업종 미확인10·플랫폼2다. 이번 마무리의 추가 수집·근거/연결 쓰기·모델 판정·운영 코드 변경·배포는0이다. 조사 방법·개별 비식별 기록·수집 가능성 의견은 [69건 조사 기록](agents/artifacts/ota-portal-warning-diagnostics-20261112.md)에 있다.
- 원문 보호 폴더를 `D:/WebLedgerHost/data/backups/ota-portal-20261112-collection-private/`에 보존했고1,175파일·79,881,285bytes의 파일별해시가 일치한다. 수입 전 운영 백업·별도 복원 DB는 그대로 보존한다. 이 아래148건 효과/추가 수집 관련 기록은 당시 이력이며 재개 과제가 아니다.

## 2026-11-12 OTA 포털 조회·신규 근거 23건 추가 — 전체 수집·148건 효과는 PARTIAL

- 세 사이트의 기존 로그인 예약 목록을 확인했다. 로그인 입력·계정 전환·예약 변경·취소·결제·Google 쓰기·AI 판정·서버 코드 수정·배포는 0이다. 수집 원본은 작업 폴더 `.local-archive/ota-portal-20261112/`에만 보존했다.
- Agoda 목록 900건 중 상세894건 저장·형태 미확인6건, 그중 지정 범위498건은 이용기간498·금액/통화 구성198·카드 관측492·결제일0·취소199다. 처음 받은 오래된 완료·취소396건은 범위 밖으로 제외했다. Trip 호텔 목록100·상세100·이용기간100·취소36건을 저장했다. Booking 지난/취소 목록각50·범위 내 여행 화면12건을 저장했으며 예약 파서/공식 가져오기 경로가 없어 반영하지 않았다. 모든 사이트에 페이지/상품 범위 제한이 있어 전체 수집 완료가 아니다.
- 운영 읽기 전용 대조: 대상598건 = 중복565 + 충돌10 + 신규23. 기존 원천 재수입은 현재 revision 갱신을 만들므로 제외하고 신규만 별도 분리했다. 중복565건은 이전 원문 관측의 Agoda 통화/수치 금액·Trip 주문 통화/총액도 같음을 추가 대조했다. 기존 공식 수입 도구의 격리 리허설23건·오류0·기존 원천 불변·삭제/덮어쓰기0을 확인했다. 미리보기 단계에는 운영 저장소 전체 사본을 만들지 않았다.
- 신규 전용 리허설 뒤 06:01 KST에 대상 OTA DB만 SQLite backup API로 신선 백업·별도 복원했다. 두 사본 quick_check=ok, 스키마/13표 행수·파일SHA 동등이다. 06:03:13~06:03:30 KST 운영 릴리스 `0da7e052`의 기존 공식 가져오기 도구로 Agoda20·Trip3을 추가했다. source/revision/booking/evidence 각각+23, raw_entries+92, blobs+69; 기존 source 값 전부 불변, 삭제·덮어쓰기0이다.
- 가져오기 전후 보호13표 지문(카드 원문이 든 transactions·수동 교정 관련 표 포함) 불변 PASS. backup 전후와 apply 후 backend8752·Gateway8790 ready 모두200이며 apply 직후0.004/0.007초다. 새 Agoda 근거는 결제 예정19·결제 상태 미확인 취소1건으로, 기간 존재를 실제 결제 연결로 간주하지 않는다.
- 재계산 06:03:34~06:11:51 KST, 496.76초·generation932→933 게시를 확인했다. 자동/그룹/수동 MATCHED 결과1,060건 전체와 수동 연결이 동일하며 신규 정확0·추론0·해제0, NICE 신규 연결/결제일 검증 연결0이다. NOT_CARD_CHARGE만3건 증가했다. 기존148건 고정 대상 ID는 이 작업 폴더에 없으므로 **148→사후 건수는 미측정**이며 다른 조건의 경고 수를 대입하지 않는다. 절차의 실제 관측값과 범위 제한은 [포털 절차서](playbooks/ota-portal-collection.md)에 기록했다.
- 별도 인증 GET 실화면 대조는 같은1,699개 행에서 이용일 표시 변경0, 미확인69→69다. 그69건은 NICE26·기타23·Agoda11·Booking5·Trip2·Klook1·Skyticket1이다. 원래148건이나 NICE57건의 분포로 대체하지 않는다. 새 snapshot 게시 후에도 보호13표 불변 PASS, ready8752/8790 200(0.042/0.005초), 담당 TaskSpace 종료 완료다. 문서만 변경했으므로 코드 테스트·재배포는 하지 않는다. 독립 검수·병합은 Fable에 인계한다.
## 2026-11-12 #810 P2 오프라인도구·AI출처 표시 공식배포 완료

- 최종76cb14de 독립gpt-6.1-sol/medium APPROVE(직접80+41pass) 뒤 병합·운영0da7e052d861a90b58ee52ee58dc2886e4d0a667, 이전8644e873. 공식도구1회·파일1665/blob불일치0·Board/Worker일치·8752/unpaused·health/ready200·보호API401·보호13표불변. P2/full=false, 추가데이터반영/Google/롤백0.
- ready관찰31표본모두200, 직후/5/15분0.051/0.015/0.006초·최대1.199초. 배포전후같은레포Fable세션알림. 신선전체백업은코드배포라미실행, 기존검증백업과복원본보존.
- 영향512pass/44subtests/skip0·compile/data guardPASS, 390/1440합성AI판정출처/상세펼침/넘침0. CI job130781421054결제한도step0미시작은통과가아니다. 운영로그인시각검사/실기기검사미실행.
- 근거 `.local-archive/p2-final-20261112/`의review/deploy-evidence/monitor-result/cleanup-verification. 민감임시파일삭제·집계/해시보존목록과후속OTA수집은 [현재 상태](session_handoff.md) 맨위. 이종료문서변경은재배포하지않는다.


## 2026-11-12 #809·wave3 단일 배포와 P2 367건 반영 완료

- 최종7ca80c96 독립sol/medium APPROVE·릴리스HTTP1pass 후 #809 병합8644e873, 이전68fbe0dd. 공식 `deploy_verified_release.ps1`1회, 파일1646/blob불일치0·runtime/Board/Worker SHA일치·backend8751/unpaused·health/ready200·보호API401·배포전후보호13표불변. 배포전후같은레포Fable세션알림완료. 추가배포/롤백0, P2/full=false.
- 00:26:12~00:41:12 KST ready31표본전부200, 직후0.132초/5분1.335초/15분0.006초·최대7.016초. owner/CSRF 운영preview20건200·쓰기0. 익명브라우저7주요주소401, CSS/JS는별도URL없는인라인이므로실제파일포함확인, 폰트/아이콘200. 로그인시각검사는사용자영역이다.
- 신선변경전값파일과367건사본복원/불변검증뒤20→50×6→47로367건반영(기록227/미기록140),8묶음모두검증통과. 원본·금액·귀속·ID·보호관계·수동/비대상불변, 감사/AI실행정보/장부화면동반변경확인. 첫묶음의`AI`라벨가정오탐은독립검토와20건전부API근거대조로분리했고, 실제3화면의펼친AI근거도확인했다. 금융되돌리기0·Google0·P1등록0이다.
- 최종00:54:20 KST ready200/0.045초. 귀속불일치109건(후보중1건)은분기검수목록에유지한다. 비공개배포/반영/복구/표시검증근거는 `.local-archive/p2-import-fix-20261112/`, 상세검사와항목전환표는 [현재 상태](session_handoff.md) 맨위다. 전체영향QA699pass/기존8fail/skip0이며CI PASS로표시하지않는다.

## 2026-11-12 P2 반영 시도 — 미리보기 API 502, 쓰기 전 중단

- 기존68fbe0dd를 유지했고 추가배포는 없다. 귀속 불일치1건 제외 후367건의 사본 불변/복원 검증은 통과했다. 첫20건의 서버preview는502였고, 운영 로그의ledger_board.py:4720에서 webapp.classification_correction ImportError를 확인했다. apply API 미호출, 운영반영·되돌리기·Google0이다.
- 신선 후보367건/비대상3표/보호13표 구성 불변 확인. 2026-11-12 00:05:27 KST 외부 `/readyz` 200/0.110초. 실패는반영 API 진입점이며 readyz 장애와 구분한다. 서버 수정·배포 지시 전 반영은 차단이다. 근거는 `.local-archive/p2-stage2-deploy/run367/`, 자세한 재개 조건은 [현재 상태](session_handoff.md)다.

## 2026-11-11 P2 #807 배포와 반영 전 안전 중단

- 공식 검증 배포: `68fbe0ddb3543f96bfe5a7d1fc74ea737465b1a8`, 이전 `8b116b98ccbacdc49c702e370031be2da45f5ef9`. 독립 sol/high 최종0de29030 APPROVE 후 병합했다. 배포 근거는 `.local-archive/p2-stage2-deploy/deploy-evidence.json`이다. 23:38:03 KST 파일1577·blob불일치0·runtime/listener 일치·backend8752·health/ready200·비인증API401·보호13표 불변이다. 공식 도구의fresh_backup_restore=false는 이번 백업 옵션 미사용이며 후보별 변경 전 값 복구 검증과 별개다.
- 5분 준비 응답10회 모두200. 이후16회도200이나 한도로 관찰 루프가 끊겼다. 재개23:52:28 200/0.221초, 배포15분 이후23:53:57 200/0.168초를 별도 측정했으며 끊긴 구간을 연속 관찰 성공으로 보완하지 않는다.
- 후보368건 변경 전 세 행 전체를 파일 보존하고 메모리 사본에서 적용·재전송·파일 복원을 검증했다. 368건 복원 일치, 사본1건에서 장부귀속 두 열의 변경을 발견해 운영 반영 전에 중단했다. 실제 반영0·실제 되돌리기0·Google0. 준비시점 대비 대상368건/관련14표 불변이다.
- Board·Worker68fbe0dd·route8752/unpaused·P2/full=false 유지. 최근 검증된 전체 백업14:36과 후보별 복구 파일을 보존했다. 중단 원인·다음 조건은 [현재 상태](session_handoff.md) 맨 위다. 후속 배포의PreviousSha는 실행 전 실제 운영과 다시 대조한다.

## 2026-11-11 #805 재개 결과 — 5건 시범 중단, P2 off 유지

- **COMPLETE(수정·배포):** 전체 원문 충돌/base64 보존·포털 중첩 판정 필드 projection을 최종 `aee08a8b`의 별도 `gpt-6.1-sol / medium` APPROVE 후 #805로 병합했다. 운영 완료 커밋은 `8b116b98ccbacdc49c702e370031be2da45f5ef9`다. 공식 배포 도구 exit0, 릴리스1570파일/blob불일치0, Board·Worker·listener SHA 일치/backend8751, health/ready200·비인증API401·보호13표 불변이다. 사전 SQLite API 신선백업5DB와 별도복원 quick_check/schema/행수 검증 PASS(공식 도구의 BackupProducts 스위치는 별도 미사용).
- **검증:** 표적17 passed. 최종 코드8279f6ad 영향602 passed/1 failed/4 subtests/skip0·204.24초, compile PASS. 실패는 `test_split_prompts_count_all_assembled_cases_toward_first_fifty`의40 !=30이며 정확 운영기준5248d129에서도31 passed/동일1 failed로 재현했다. 테스트·기대값 불변, 전체 QA PASS 아님. 최종 문서 SHA aee08a8b 검수·병합 트리 동일 확인. CI 최종 head job130346428325는 결제 한도로 시작되지 않았다. 기존 사용자 QA3파일은 SHA256 확인 후 복원했다.
- **COMPLETE(P2 off 관찰):** 14:42:02~14:57:27 KST,15분 창+종료측정925.255초. ready32회 모두200, P2 호출0/대상0/실행이벤트0, 보호지문 불변, route sampled unavailable 최대0.8924초다.
- **FAILED(5건 운영 수락):** 14:57:49~15:02:12 KST,262.379초에 gateway8790 ready15.006초 timeout으로 즉시자동off. 후보3075/선정5/조립시작5·완료0/근거읽기시도2/모델시도0·성공0·실패0/preview0/반영0(각 회차 최댓값). `P2_SOURCE_RECORD_TOO_LARGE` 조립 실패가 두 회차에 기록됐다. 원본 레코드 중 어느 구조가 상한을 넘었는지는 이번 시범으로 확정하지 않았다. route최대18.133초는 중단선78.477초 이내였으며 직접 중단 조건은 ready timeout이다.
- **안전 종료:** 보호지문 불변, 진행중 모델호출0, P2/full=false, route8751 unpaused. 종료 후 health/ready는8751 200/200(0.110/8.896초),8790 200/200(0.008/0.013초)이다. 원본·수동교정·Google 변경 없음. 50건·전체확대·E2·wave3·세 번째 재시범은 실행하지 않았다.
- **미검증:** 운영에서 조립 완료·모델 입력이0건이므로 메일 절단 비율과 절단 후 예약번호/금액/날짜 구간 보존율은 측정할 수 없다. 합성 tail 구간 보호 검사는 통과했지만 운영 증거로 대체하지 않는다. dcbe4894의2000건/1.100GB/245.09초/합성3호출50반영은 메일 전용 합성 근거이며 포털 운영 수락이 아니다.
- **다음:** 승인된 중단 보고 지점에 도달해 Fable에 보고하고 멈춘다. 운영은8b116b98/P2 off 유지. 추가 원인 수정·재시범은 후속 지시에서 판단한다. 비공개 근거 `.local-archive/p2-staged-resume-20261111/`의 `resume805-deploy/`, `resume805-off15m/result.json`, `resume805-pilot5/{result,stage-summary,post-ready}.json`, `resume805-final-{summary.json,pytest.log,junit.xml}`, `resume-baseline-split.json`. 정확한 재개 확인 명령은 `Get-Content -LiteralPath .local-archive/p2-staged-resume-20261111/resume805-pilot5/stage-summary.json -Encoding UTF8`다. 이번 종료 기록은 로컬 커밋으로 보존하며 기록만을 위한 새 문서 PR·재배포를 만들지 않는다.

## 2026-11-11 #805 중단 작업 재개 — 최종 검수 준비

- 현재 작업은 #805의 근거 크기 수정과 승인된 단계별 재시범뿐이다. 전체 반영·E2·wave3는 실행하지 않는다. 운영 읽기전용 확인: P2/full=false, route8752 unpaused.
- 전체 메일로 원본 충돌을 검사한 뒤 P2 조립 경계에서만 20KiB 관련 구간을 발췌한다. 포털은 실제 `_read_records`의 중첩 `payload_json`에서 판정 필드와 price_components만 선택하며 raw 자료는 검색·출력하지 않는다. 실제 SQLite loader 합성·원본 불변·잘못된 JSON 보호 포함 표적17 passed.
- `dcbe4894` 규모 합성: 후보2000·근거1,100,346,849B·메일9174, 245.09초·고유조립50·합성모델3호출/50건·반영50, 근거읽기 첫1,102,565,348B/이후0. 조립은 route/runtime/board/DB쓰기 잠금 밖, 경쟁 DB쓰기 최대대기0.0079초. 실제 모델 호출이나 운영 반영 증거는 아니다.
- 영향검사 `dcbe4894`: 599 passed/1 failed/4 subtests. 실패는 `test_split_prompts_count_all_assembled_cases_toward_first_fifty`(40 != 30); 정확 운영 기준5248d129에서도 동일 1 failed/31 passed로 재현했다. 검사와 기대값은 고치지 않았다. 전체 통과로 표시하지 않는다. 최종8279f6ad 영향검사602 passed/동일1 failed/4 subtests/skip0·204.24초이며 py_compile 통과. 정확 기준 실패 근거는 resume-baseline-split.json이다. 최종 SHA 별도 sol medium 승인 전 병합/배포 없음.
- 기존 큰 합성의 provider0은 실행기 미구성이 아니라 base64 clipping의 ValueError였다. 이전5건의 route unavailable 5.096초는 P2 off 기준선 최대39.238초 안이다. 재시범 중단선은78.477초이며 ready 연속2실패·보호변화·preview없는 반영 시 즉시 off다. 조립 뒤 모델시도0이면50건으로 가지 않는다.
- 비공개 증거: `.local-archive/p2-staged-resume-20261111/`의 `resume-large-on.log`, `resume-impact-final.log`, `review805-resume.md`, `checkpoint.md`. 다음은 최종 영향검사→별도 sol medium 최종SHA 승인→#805 병합→공식 P2 off 배포→15분 관찰→5건10분→실제호출/안전 확인 시50건60분→보고·중단이다.

## 2026-11-11 P2 단계별 재배포 승인 — 배포 전 준비

- Fable이 #804에 대해 조건부 단계별 재배포를 승인했다. 회차별 후보·선정·조립시작/완료·모델호출시도/반환성공/실패사유·preview통과/반영·소요/중단사유를 먼저 기록한 뒤 최종SHA 독립 sol medium 검수, off 배포와15분 관찰, 최대5건/10분, 안전하며 실제호출이 있었을 때만 최대50건/60분 순서다. 전체 미해결 건 반영은 승인되지 않았다.
- 저장 코드49cff716은 고객내용 없는 상관ID 단계이벤트와 finally 요약, 선택적1~50건 시범상한, UTC절대마감 만료/잘못된값 차단을 추가했다. source_read_attempts는 논리적 근거 작업 시도이며 물리I/O가 아니다. assembly는 케이스×시도(추가조회·신선도재조립포함), model_successes는 provider 반환이며 형식·preview성공과 구분한다. 기존 고유50건 예약보호를 유지하므로 첫5건 이후에는 추가최대45건이다.
- 재개 읽기전용 관측: 운영965bca05/8751, P2/fullfalse; ready8751 200/1.016초·8790 200/0.260초. BoardPID2460 연속약10초구간 읽기0과55,107,598bytes(약5.35MB/s), Win32_Process.ReadTransferCount다. 비공개 근거 `.local-archive/p2-staged-resume-20261111/pre-ready.json`, `pre-board-read.json`.
- 이전 시범의 호출0건 직접 원인은 당시 live stack·단계별 계수 부족으로 **미확정**이다. 이번 계측으로 그 역사적 원인을 확정했다고 보지 않는다. 이번 배포·실제호출·보호대조 결과는 아직 없다. 관리자 표적147pass/21.66초, 영향31파일702pass/기존3fail/4subtests/skip0·141.17초다. 기준455a723d 동일3fail 재현 근거를 유지하며 전체검사 통과가 아니다. 최종 규모실측·독립검수 진행 중이다.

> 이 문서는 현재 유효한 운영 절차와 2026-11-08 이후 배포 기록만 둔다. 2026-11-07 이전 기록은 [10/28~11/07](history/operations-20261028-20261107.md), 2026-10-27까지는 [운영 이력](history/operations-through-20261027.md)에 원문 그대로 보관한다. 2026-11-09 작업공간 통합 정리 상태는 [현재 상태](session_handoff.md)를 본다.

- 단계0 관리자 검증: 표적147pass/21.66초, 영향31파일702pass/기존3fail/4subtests/skip0·141.17초(기준455a723d 동일실패근거 유지). 계측 추가 후 같은2000건/1,100,346,849bytes 합성 off0.773초/P2근거조립호출0; on106.138초/고유50조립·합성3호출·50반영/근거첫1,100,591,362bytes 이후0·경쟁DB쓰기최대0.0012초. 실제모델/운영판정 미실행이며 최종SHA 독립검수 전이다. 기존QA3파일은 원해시로 복원했다.

## 2026-11-11 P2 근거 크기·route 기준선 조사 — 재시범 전

- 운영은 `5248d129`·P2 off·full rollout off·route8752 unpaused를 유지한다. 이전 5건 시범 중단은 유지하며 재배포/재시범은 새 PR의 독립 검수 전 실행하지 않는다.
- 운영 읽기전용 크기 분포(원문 미출력): 메일 10,085건, 중앙값45,610B·p95 208,995B·최대425,242B. 포털 `ota_raw_entries` 최초78,720건은 length(TEXT) 집계였다. UTF-8 바이트 재집계79,288건(수집 증가), 중앙값/p95 86B·최대3,955,511B다. 포털 raw payload는 조립 대상에서 제외하고 판정 필드 allowlist만 쓴다.
- 최초 수정의 payload clipping은 독립 검수에서 반려됐다. 최종 수정은 전체 메일로 충돌을 비교한 뒤 evidence 조립 경계에서만 정리·발췌한다(메일 본문20KiB, 전체 evidence24KiB·전체 prompt256KiB 상한). 포털 evidence는 booking/service/status/payment/card/lifecycle 등 판정 필드만 포함한다. source record가 상한을 넘었다는 이유만으로 전체 사건을 실패시키지 않는다. 신규·기존 표적 149 passed, skip0.
- 기존 큰 레코드 합성 `staged-large-on`의 성공 해석을 철회한다. 로그는 `ai_retry:ValueError=50`, provider0·반영0이며 조립3은 `Repository.select` 진입 수다. on 실행기는 합성 provider를 주입하므로 호출 미구성이 아니다. 이전 메일 payload clipping이 base64 뒤에 한글 생략 표시를 붙여 decode에서 `ValueError`를 내는 경로를 합성 재현했다. 최종 SHA의 재측정은 최신 재개 절에 기록한다.
- P2 off route 잠금 30분 기준선: 비차단 probe17,934회·unavailable run246, 최대39.238초·p95 11.971초·중앙값6.223초. 따라서 다음 시범의 route 중단 기준은 `max(2×39.238,15)=78.477초`다. 기준선은 route/config 쓰기 없이 측정했으며 probe의 one-byte 획득은 즉시 해제한다.
- M1의 2,113 후보와 현재 시범 3,075 후보 차이는 detection SQL 변경이 아니라 운영 DB 상태가 M1 이후 변한 결과로 기록한다. 현재 읽기전용 집계 base3269, source_general3269, refund·board/manual 보호를 적용한 시범 후보3075다.
## 2026-11-11 단계별 시범 결과 — 5건 단계에서 중단

- `5248d129b713f70210f5dc64e83f85574566042e`를 공식 `tools/deploy_verified_release.ps1`로 `965bca05`에서 배포했다. Board/Worker SHA와 listener는 5248d129, backend8752, route unpaused, health/ready200, 비인증 API401, 보호13표 불변이다. 첫 시도는 릴리스 파일 누락으로 `RELEASE_AUDIT_FAILED` 안전중단했고 운영은 바뀌지 않았으며, Git blob 재구성·audit0 후 재시도했다.
- P2 off 15분 관찰: ready8752/8790 30회 모두200, 호출·대상·예약0, 보호지문 불변, P2 off 유지. Board ReadTransferCount 표본은 5분 1.94MB/s·946.5MB/s, 15분 0·1.31GB/s로 변동해 기존 재계산 경로와 구분한다.
- 최대5건 시범은 route 잠금 샘플 연속 unavailable 5.096초로 즉시 중단했다. P2는 자동 off, full rollout false, route unpaused, ready8752 200/2.821초·8790 200/0.027초, 보호13표 PASS다.
- 시범 계수: 후보3075, 선정5, 조립시작5·완료0, source_read_attempts2, 모델시도0·반환성공0·실패0, preview0·반영0. `P2_SOURCE_RECORD_TOO_LARGE`로 호출 예약 outcome unavailable, 최종 호출0/대상0 집계와 구분해 기록한다. route 중단 조건이 먼저 발생했으므로 50건 단계로 진행하지 않는다.
- 결과 근거 `.local-archive/p2-staged-resume-20261111/off-15m/result.json`, `pilot-5/result.json`, `deploy-exit.json`, `deploy-evidence/`. 전체 미해결 건·E2·wave3는 실행하지 않았다. 다음은 Fable의 원인 수정·재시범 승인 판단이다.
## 2026-11-11 P2 시범 중 준비 응답·배포 잠금 장애 — 965bca05 롤백 완료

- **현재 운영은 `965bca058a74a54bf69bc4d70a0d05f8997786c3`**, 공식 롤백 완료 06:13:42 KST, 이전 `bd4646a1`이다. 다음 공식 배포의 `-PreviousSha`는 `965bca05`다. Board·Worker·listener SHA 일치, 파일1,503개·blob 불일치0·운영 backend8751을 확인했다. 8751과 Gateway8790의 health/ready는 모두200, 비인증 OTA API는401이다. 보호13표와 원본7,336·수동교정 대상255·관련14표의 비공개 지문은 모두 불변이다. P2/전체확대 플래그는 off다.
- **읽기량 평상 기준선은 미검증**이다. 06:14:47~06:15:08 KST 같은 Board PID2460의 10초 간격 두 구간 읽기 증가가 약123.3MB/s·355.4MB/s였다. 이후 06:15:41~06:16:01은 약5.35MB/s·0B/s, 06:17:19~06:17:40은 약5.54MB/s·395B/s로 줄었다. 초기 증가가 시작 후 준비 작업인지는 미확정이고 평상 기준선 없이 완전 정상화를 단정하지 않는다. 06:03:54 준비 실패 실측부터 공식 롤백의 응답 정상 확인까지는 최소9분48초다. 실제 장애 시작과 읽기량 증상의 정확한 종료는 미확정이다.
- **965 재시작 후 기준선 1회 기록:** PID2460 생성은 06:13:16.304 KST다. 아래 값은 `Win32_Process.ReadTransferCount`의 증가율이며 물리 디스크 읽기만 분리한 수치가 아니다. 놓친 시점은 미측정으로 남기고 재시작을 반복하지 않았다.

| 요청 시점 | 실제 측정 시점(KST)과 재시작 후 경과 | 연속 두 약10초 구간 읽기량 | 확인 범위 |
| --- | --- | --- | --- |
| 0분 | 미측정. 별도 보존 실측06:14:47~06:15:08(+1분31초~1분52초) | 123.26MB/s·355.44MB/s | 재시작 직후 0분값으로 대체하지 않음 |
| 5분 | 미측정. 가까운 별도 실측06:17:19~06:17:40(+4분03초~4분24초) | 5.54MB/s·395B/s | 정확 5분값으로 대체하지 않음 |
| 15분 | 예약 실측06:28:17.221~06:28:37.789(+900.917~921.485초) | 117.42MB/s·5.36MB/s | 같은 운영8751·Gateway8790 ready200, 운영 파일 쓰기0 |

15분에도 읽기 증가가 한 구간에 나타나므로 낮은 단일 구간만으로 평상 읽기를 정의하지 않는다. 원인 분석은 P2 조립과 기존 재계산 경로를 구분한다. 비공개 근거는 `incident-rollback/post-verification.json`, `read-final.json`, `baseline-965-15min.json`이다.

- 대상 릴리스 `bd4646a1b4c1d0b6acf11af886e4f86dfe3ea64c`. 05:04:16 KST 제한 제어 시작 후 호출은 0건이었고, 05:59:19 제어 종료와 P2 비활성화 뒤에도 Board PID34256의 디스크 읽기가 계속 증가했다. 06:03:54 관리자 실측에서 `/healthz`는 200, `/readyz`는 3초 시간 초과였고, 06:08 Fable은 15초 시간 초과와 초당 약116MB·누적 약207GB 읽기를 확인해 운영 장애로 판단했다. 준비 응답 장애의 실제 시작 시각은 미확정이다.
- **확인된 것:** 준비 응답 불능, route lock 장기 보유와 공식 배포의 잠금 획득 대기, 지정 Board의 예약 작업 중지 후 잠금 해제와 롤백 뒤 응답 정상화다. 구 코드에서 `sweep_once()`의 `active_writer` 범위가 조립·호출까지 이어지고 off가 진행 중인 조립을 즉시 취소하지 않는 구조를 확인했다. 그러나 당시 운영 live stack과 잠금별 보유 시간을 측정한 것은 아니다.
- **미확정인 것:** 높은 읽기량의 직접 원인이다. 근거 반복 읽기 경로는 코드에 있으나 직전 릴리스965도 재시작 후 +1분31초~1분52초에 약123~355MB/s를 읽었고 +4분대에 약5MB/s로 내려갔으나, +15분에 한 구간 117.42MB/s로 다시 올랐다. 따라서 bd의 시간당 약207GB가 P2 조립 때문인지, 재시작 뒤 정상 재계산이 잠금 때문에 완료되지 못하고 반복된 것인지 확정하지 않는다. 호출0의 직접 원인도 선정·조립·실행기 단계별 합성 재현과 운영 관측의 한계를 구분해 조사한다. `83d87f88`만으로 장애가 해결됐다고 보지 않는다.
- Fable의 명시적 장애 복구 지시로 대기 중인 `83d87f88` 배포는 전환 전에 취소했다. 정상 취소 옵션이 없어 관리자가 시작한 배포 프로세스와 그 자식만 정체성 대조 후 종료했고, 같은 배포가 만든 Prepared 예약 작업을 중지·등록 해제했다. 기존 운영 route와 Gateway는 유지했다.
- 06:10:35~06:11:21 KST에 **5개 운영 DB를 SQLite backup API로 백업하고 별도 DB로 복원**했다. 모두 `quick_check=ok`, 복원 스키마·모든 테이블 행수 동등이다. 원본 DB 파일의 파일시스템 복사·운영 DB 쓰기·복원 서버 시작은 0이다. 이 검사는 전체 셀값의 재해시 검사와 구분한다. 비공개 근거: `.local-archive/manager-resume-20261111/incident-rollback/backup-result.json`.
- P2 off·전체확대 false와 PID/예약 작업/SHA를 확인하고 `WebLedger-Board`만 중지해 지정된 PID34256의 종료와 route lock 해제를 확인했다. 잠금 파일 삭제·우회는 하지 않았다. 06:12:08 KST 같은 SHA를 비활성 상태로 재시작한 뒤 공식 도구로 직전 검증 릴리스 `965bca058a74a54bf69bc4d70a0d05f8997786c3` 롤백을 완료했다. `-PreviousSha`는 `bd4646a1`이며 신선 보호13표 기준과 이전 검증 릴리스 근거를 사용했다. 복구의 고객 데이터 변경·모델 호출·Google 쓰기는 0이다. 읽기량 감소 실측과 평상 기준선 미검증을 구분한다.
- 공식 증거는 `D:/WebLedgerHost/releases/deploy-evidence-965bca058a74a54bf69bc4d70a0d05f8997786c3.json`, 비공개 추가 근거는 `.local-archive/manager-resume-20261111/incident-rollback/`의 `post-verification.json`, `raw-manual-after.json`, `protection-before.json`, `protection-after.json`이다. 이전 965 배포 증거는 `prior-965-deploy-evidence.json`으로 보존했다. 공식 배포의 `fresh_backup_restore=false`는 `BackupProducts` 미사용이고 별도 SQLite 백업·복원 검증 성공과 구분한다.
- **P2 재배포 금지:** 운영 밖에서 off 시 조립/근거 읽기 방지, 첫묶음50의 회차 제한, 조립/모델 호출의 route/DB 쓰기 잠금 분리, 색인 조회와 건당/회차당 읽기·시간 예산, 시범 창 종료 시 진행 회차 중단을 해결한다. 후보2,000건 이상·근거1GB 이상 합성 자료에서 off/on 읽기량·소요·잠금 시간을 실측하고 독립 검수 및 Fable 승인을 받기 전 P2 코드를 다시 운영에 올리지 않는다.

## 2026-11-11 도구 없는 P2 코드 배포 — 첫 묶음 가동 전

- 운영 `bd4646a1b4c1d0b6acf11af886e4f86dfe3ea64c`([PR #797](https://github.com/6Soo/cost/pull/797)), 이전 `965bca058a74a54bf69bc4d70a0d05f8997786c3`, 전환 완료 2026-11-11 04:56:02 KST. `tools/deploy_verified_release.ps1`의 정확 SHA 배포이며 파일 1,543개·blob 불일치 0, Board·Worker와 listener SHA 일치, backend 8752다. 다음 배포 `-PreviousSha`는 `bd4646a1`이다.
- health/ready 200, 인증 없는 OTA API 두 경로와 합성 환불 미리보기 API 401, 보호 테이블 13개 전체 불변. 금융 반영·Google 쓰기·고객 P2 호출은 이 배포에서 하지 않았다. P2는 `autonomous_ai_review=false`, `autonomous_p2_full_rollout=false`로 배포했다.
- 직전 백업·복원 검증은 04:51:58 KST 완료: DB 5개·파일 45개, DB의 모든 테이블/열·원본 파일 해시·복원 review binding 동등, 운영 상태 불변, 복원 서버 시작·실제 가져오기·요청 replay는 미실행이다. 첫 백업 실패는 상태 파일의 동시 갱신 경로를 확인하고 기록을 보존했다. v2 검증 중 관리 중인 Board·Worker·Gateway를 잠시 정지하고 모두 원래 SHA로 복구한 뒤 코드 배포를 수행했다.
- continuous code 배포 도구의 `fresh_backup_restore=false`는 `BackupProducts` 미사용을 뜻한다. 별도 `restore-evidence-v2.json`의 신선 백업·복원 통과와 구분한다. 이 값을 임의로 변경하지 않는다.
- 배포 증거: `D:/WebLedgerHost/releases/deploy-evidence-bd4646a1b4c1d0b6acf11af886e4f86dfe3ea64c.json`. 비공개 로컬 근거: `.local-archive/manager-resume-20261111/p2-release/`의 `restore-evidence-v2.json`, `safety-ready-v2.json`, `review-evidence.json`, `protection-before.json`, `protection-after.json`, `deploy-evidence.json`.
- 05:04 KST에 첫 50건 제한 제어를 시작했다. 비활성 상태로 배포하면 `enabled_for()`가 Worker를 생성하지 않으므로, 독립 sol medium 검수를 통과한 제어가 gateway drain 뒤 같은 배포의 Board 예약 작업만 재시작하고 ready·route resume을 확인했다. 고유 사건 50건·호출 예산 60회·야간 22~06시·한도/인증 오류 종료·finally 비활성화·원본/수동/금융 보호 전후 대조를 유지한다. 고객 결과와 종료는 아직 미확정이다.
- 별도 OTA 코드 PR #798은 main에 병합했으나 이 운영 릴리스에는 포함하지 않았다. 첫 50건 가동·표본 검수·종료 결과는 별도 기록하며, 전체 미해결 건으로 확대하지 않는다.

## 2026-11-11 M1 읽기 전용 기준선

[통합 명세 §10 M1](SPEC.md#10-로드맵)의 집계다. 재현 도구는 [m1-baseline-20261111.py](agents/artifacts/m1-baseline-20261111.py)이며 저장소 루트에서 다음 명령을 실행한다. SQLite는 모두 URI `mode=ro`와 `query_only=ON`으로 열고, 집계 연결에는 읽기 트랜잭션을 둔다. 도구는 고객 원문·금액·원본 식별자를 출력하지 않는다. 파일 쓰기·네트워크·외부 프로세스 호출은 프로세스 내 가드로 거절한다. 운영 앱·Worker를 시작하거나 운영 데이터를 갱신하지 않는다.

```powershell
python -I docs/agents/artifacts/m1-baseline-20261111.py --data-root D:/WebLedgerHost/data
```

측정 대상은 `board.sqlite`, `ota-evidence.sqlite`, 기존 수집·Google·OTA 상태 JSON이다. 집계는 **2026-11-11 00:58:32 +09:00 시작, 01:10:54 +09:00 완료 확인**, 종료 코드 0이다. 서로 다른 파일 전체의 한 시점 스냅샷은 아니며 SQLite별 읽기 트랜잭션과 OTA 입력 지문 비교로 경계를 명시한다. 아래 수집 시각은 각 파일에 저장된 시각이며 이 명령이 새 수집을 수행했다는 뜻이 아니다. 판정 정답률·Google 반영 여부·P2 실행 성공률을 측정하는 명령도 아니다.

### 판정 상태·주체와 정상 거래

카드 거래 전체 **7,336건**이다. 저장 분류 상태는 `classified` **7,329건**, 기존 `needs_review` **7건**이다. 후자는 모두 원본 충돌 표시가 있으며 새 확인 대기 상태를 만든 것이 아니다.

| 판정 주체 | 건수 |
| --- | ---: |
| 자동 | 2,559 |
| 코드 추론 | 4,514 |
| 직접 | 255 |
| AI 추론 | 1 |
| 출처 미확인 | 7 |

주체는 [classification_provenance.origin](../app/classification_provenance.py)의 우선순위(`decided_at` 또는 수동 source 우선)를 따른다. 따라서 source 문자열 개수와 다르다. source별로는 `rule` 1,623, `inference` 4,474, `refund_original` 473, `user_decision` 153, `user_exception` 31, `owner_card_residual` 376, `code_inference` 107, `ai_inference` 1, `card_category` 78, `pattern` 13, `booking_evidence_needed` 7건이다. 저장 AI 판정 1건으로 P2 실행 성공률이나 새 실행기의 가동 여부를 추정하지 않는다.

- 정상 구매 **6,610건**: `purchase`, 양의 정수 원화 금액, 중복·원본 충돌·파싱 오류 없음, 기존 검토 보류·회사비용 제외 대상 아님. 환불은 이 정상 구매 분모에서 제외하며 원본에서 삭제하거나 재분류하지 않았다.
- 저장 판정 요건 미충족 **15건**, 그중 정상 구매 **0건**. 요건은 `classified`·항목 존재·여행 목적지 존재이며, 기존 코드의 `분기 기타비용`과 `guide_airfare_evidence`는 여행 목적지 예외로 인정한다([기존 배정 누락 조건](../webapp/card_classification_completion.py)). 15건 중 13건에 원본 충돌 표시가 있다. 저장 목적지는 현재 Google 여행 권위까지 재검증한 값이 아니다.
- 별도 지표인 [자율 정리 Worker 후보](../webapp/autonomous_cleanup_worker.py)는 한 번의 `LIMIT 400` 조회 **400행/서로 다른 거래 400건**, 제한 제거 시 **2,113행/서로 다른 거래 2,113건**이다. 가져오기 행 중복 때문에 행수와 거래수를 별도로 센다. 이 후보는 일반 항목(`기타경비`·`현지경비`·`여행경비`) 재검토까지 포함하고 수동 결정·기록 완료·환불 짝 등 기존 보호를 제외하므로 위 0건과 다른 지표다. **0건을 통합 명세의 정책상 판정 완료나 M2 종료로 해석하지 않는다.**

### 이용기간 미확인

**현재 입력의 표시 계산 재현: 147행 미확인**(`MEASURED_CURRENT_INPUT_RECONSTRUCTION`). 삭제되지 않은 여행(보관 여행 포함)의 양수 저장 지출 757행을 기존 표시 함수로 계산했다. 숙박비 653행 중 확인 548·미확인 **105**, 항공료 74행 중 확인 35·미확인 **39**, 렌터카 30행 중 확인 27·미확인 **3**, `항공권` 항목은 0행이다.

기존 `CoreOtaPaymentBackend._data()`가 현재 OTA 원문을 읽어 이벤트 7,638건·카드 7,336건을 메모리에서 대조하고, `ledger_stay_evidence._build_index()`와 항공 이용일 근거를 구성한다. 여행 추천 문구를 만드는 단계는 최소 읽기 어댑터에 여행 조회 메서드를 제공하지 않아 생략하며 이용일 판정에는 관여하지 않는다. 수동 `service_period` 교정과 여행 기간을 읽기 메모에 넣고 기존 `_service_date_labels()`를 호출했다. `OtaStore` 생성자·운영 앱·스냅샷 Worker·게시/저장 함수는 실행하지 않았다. 메모리 재현 전후 OTA 등록 원천의 내용 지문이 동일했다(`source_stamps_unchanged=true`).

**실행 중 운영 프로세스의 마지막 완결 표시 세대는 직접 검증하지 않았다**(`runtime_generation_verified=false`). 따라서 147행은 현재 입력의 재현 기준선이며 운영 화면을 직접 읽은 현재 경고 수라고 주장하지 않는다. 과거의 132건도 현재 측정값으로 사용하지 않는다. 이 범위는 재현 JSON의 `service_period_display.scope`와 상태 필드로 구분한다.

보조 지표인 저장 `service_period`는 삭제되지 않은 여행(보관 여행 포함)의 양수 저장 지출 행 중 숙박비 653행에서 누락 431·유효 220·무효 2, 항공료 74행에서 누락 64·유효 10, 렌터카 30행에서 누락 29·무효 1이다. `항공권` 항목은 0행이다. **저장 누락 524행 또는 무효 포함 527행은 화면 미확인 건수가 아니다.** 화면은 [이용일 표시 함수](../webapp/ledger_design.py)의 OTA 근거·항공 여정·수동 빈값 교정·현장 결제·사전승인·취소 처리를 함께 사용한다.

### 여행별 내부 미기록

거래 ID가 `ledger_entries`에도, `card-<거래 ID>` 형태의 `board_rows`에도 없으면 내부 미기록으로 센다. 두 집합의 합집합으로 판정하므로 중복 합산하지 않는다. 전체 카드 **3,792건**, 그중 정상 구매 **3,290건**이며 삭제되지 않은 여행 목적지 **3,759건**, 그 밖의 목적지 **33건**, 삭제 여행 **0건**이다. 환불·보호 대상도 전체 건수에는 남긴다. Google 장부 대조의 `NEW_EXPENSE`와는 다른 정의이며, 실제 Google 미기록 건수는 이 집계로 알 수 없다.

가명은 `trip_tabs.tab_id` 정렬 순서의 T001~T077이다. 대응표·실제 여행명·원본 ID는 남기지 않는다. 재현 시 여행 추가·삭제로 순번이 바뀔 수 있다. 저장 `display_tab_id`로 묶었고 `trip_id`와 서로 다른 비어 있지 않은 값은 0건이었다.

| 여행 가명 | 내부 미기록 |
| --- | ---: |
| T003 | 4 |
| T005 | 98 |
| T010 | 4 |
| T012 | 16 |
| T024 | 2 |
| T025 | 1 |
| T027 | 3 |
| T028 | 255 |
| T029 | 3 |
| T032 | 109 |
| T035 | 205 |
| T039 | 16 |
| T040 | 3 |
| T042 | 18 |
| T047 | 3 |
| T053 | 213 |
| T057 | 2 |
| T059 | 161 |
| T060 | 762 |
| T061 | 136 |
| T062 | 18 |
| T064 | 1,705 |
| T067 | 18 |
| T069 | 1 |
| T072 | 2 |
| T076 | 1 |

삭제되지 않은 나머지 여행 T001·T002·T007·T008·T009·T011·T013·T014·T015·T016·T017·T018·T019·T020·T021·T023·T026·T031·T033·T034·T036·T037·T041·T043·T044·T045·T046·T048·T050·T052·T054·T055·T058·T063·T065·T066·T070·T071·T073·T074·T075·T077은 각각 0건이다. 삭제 표시된 T004·T006·T022·T030·T038·T049·T051·T056·T068도 각각 0건이며 원본을 삭제한 것이 아니다.

### 원천별 마지막 수집 관측

발급사 3곳의 이름과 **마지막 거래일(승인일)**을 확인했다. 아래 가져오기 접수일은 `import_batches.received_at` 최댓값이며 카드사 사이트에서 내려받은 시각과 다르다. 실제 카드사 다운로드 실행 시각은 저장 자료에서 확인하지 못했으므로 `NOT_MEASURED`다.

| 발급사 | 거래 수 | 마지막 승인일 | 마지막 매입일 | 마지막 가져오기 접수(UTC) |
| --- | ---: | --- | --- | --- |
| 국민 | 4,110 | 2026-10-28 | 2026-10-29 | 2026-10-31 03:57:09 |
| 하나 | 3,008 | 2026-10-31 | 2026-10-31 | 2026-11-04 03:38:49 |
| 기업 | 218 | 2026-11-01 | 2026-11-01 | 2026-11-02 02:26:17 |

| 원천 | 마지막 수집 관측 | 의미·한계 |
| --- | --- | --- |
| Gmail | 2026-11-11 01:07:15 (호스트 현지 시각) | `ota-mail/collection.json:last_run`; [수집기](../app/mail_collect.py)는 시간대 없는 `datetime.now()`를 저장한다. 메일 DB의 마지막 현재 리비전 가져오기는 2026-11-10 15:08:22.213214 UTC로 별도 관측이다 |
| Agoda 직접 관측 | 2026-11-10 05:16:55.336 UTC | 현재 `direct_observation`의 fact `observed_at`; DB 가져오기는 05:54:58.236935 UTC. 별도 `direct_capture` 경로의 마지막 관측은 2026-10-21 20:42:12.683 UTC, 가져오기는 21:28:00.872105 UTC |
| Trip.com 직접 관측 | 2026-11-10 07:09:16.366 UTC | 현재 `direct_observation`의 fact `observed_at`; DB 가져오기는 08:07:39.408971 UTC |
| Booking.com 직접 관측 | NOT_MEASURED | 현재 통합 DB의 직접 관측·수집 근거에서 시각을 찾지 못했다. 수집한 적이 없다고 단정하지 않는다 |
| Google `main`·`andre_main`·`archive` | 모두 2026-11-11 00:07:14.108374 +09:00 | `google-authority/snapshot.json:sources.*.last_ok_at`, 저장 상태 모두 `ok`, `stale=false`; 지금 접속해 동기화한 결과가 아니다 |

OTA 공개 스냅샷 저장 시각은 2026-11-10 15:31:13 UTC다. 이는 수집 시각이 아니라 대조 결과 생성 시각이다.

### 검증·남은 범위

집계 도구의 [합성 하위 프로세스 안전성 검사](../tests/test_m1_baseline_readonly.py)는 **9 passed·skip 0**이다. 허용된 읽기와 SQL 쓰기·일반/쓰기 URI 연결·파일 쓰기/삭제·네트워크·하위 프로세스/셸 호출 거절을 검사하며 운영 경로와 고객 자료를 사용하지 않는다. [영향 매핑](../config/test-impact-map.json)에 새 도구와 새 검사만 전용 그룹으로 연결했다. 커밋 전 영향 QA의 `NO_CHANGES`·0건은 통과로 세지 않았다.

코드 커밋 `f3703981`에서 `python tools/run_quality_checks.py --base origin/main --run`은 **PASSED, 92 passed·skip 0**, 컴파일·추적 데이터 보호 통과다. 선택 대상은 새 안전성 검사와 기존 영향 선택/QA 검사 4파일뿐이다. 후속 변경은 이 절의 실측 결과 확정과 도구 설명 문자열의 읽기 트랜잭션 범위 정정이며 계산·가드 동작은 같다. 수집 시각 집계 최적화 전후 포털 시각과 카드·여행 집계가 일치했다. 제품 동작을 수정하지 않았다.

운영 앱·브라우저·서버 재시작·재계산 반영·원본/금융/Google 쓰기·배포는 실행하지 않았다. 제품 기능 회귀나 운영 UI 수락을 이 도구 검사로 대신하지 않는다. 집계 도구가 계산한 상태·주체 합계, 여행 합계, 발급사 합계의 불변식은 통과했다. 진행 중이던 메모리 대조의 성공 결과를 재사용했으며 표시 로직을 바꾸지 않은 후속 가드 기록·진행 표시·수집 시각 집계 최적화를 이유로 운영 원문 대조를 반복하지 않았다.

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
| 9 | `895a412eabc19fecda37d34245f0cd0e42e32649` | 9ad0a454 | #783(Agoda 상세 API 포털 근거)·#781(문서) | PASS 05:48Z, 1,498 blobs mismatch0. 이후 별도 단계로 OTA 저장소 백업→Agoda 상세 1,418건 수입 |
| 10 | `998dd46100a8bd11304532f741e15f162fd9c3c6` | 895a412e | #784(동일 객실 표시) | PASS 06:22Z |
| 11 | `374462fe922a67b53758d7e1d8bb46c5e4eedaf6` | 998dd461 | #787(Trip 주문·사전승인)·#785/#786(문서) | PASS 08:06Z, 1,501 blobs mismatch0. 이후 OTA 저장소 백업→Trip 상세 502건 수입 |
| 12 | `965bca058a74a54bf69bc4d70a0d05f8997786c3` | 374462fe | #790(현장결제 전날·렌터카 중개사)·#791(아시아나·에어비앤비·Klook 이용일, PARSER_VERSION 17) | PASS 11:07Z, 1,503 blobs mismatch0, health/ready 200·보호 API 401·보호13표 불변. 첫 시도는 릴리스 폴더 `DEPLOYED_COMMIT` 누락으로 전환 전 중단(운영 무변경) → 마커 작성 후 재실행. 스냅샷 재계산 11:18Z 완료, 경고 145→132 |

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
- OTA 동일 합성 입력80개·4범위320관측에서 본문 보존320→80, catalog peak private503,541,760→450,428,928 bytes, reconcile507,183,104→453,758,976 bytes(약11%)이며 결과/원본 해시가 동일했다. catalog wall time은 단일 표본에서 개선되지 않았다. [재현 명세](history/specs-20261110/ota-mail-load-lifetime-20261109.md). 운영 warm 중 private1,826.7MiB(db7)→1,019.3MiB(d96), warm 완료 후296.9MiB·10프로세스·소유자1·CPU0.015625초/12.6256초로 수렴했다. 이는 같은 입력을 통제한 운영 효과율이나 장기 누수 완치 증명이 아니며 venv 부모/자식 쌍을 중복 보드로 세지 않는다.
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

- 사용자 최신 교정에 따라 한 파일 내 최초~최종 거래일 전체를 기본 조회기간으로 간주한다. 내부 무거래일은 공백이 아니며 같은 카드사 파일들의 범위를 합친 뒤 파일 사이 빈 구간만 공백으로 표시한다. 예: 1~10일·15~20일 두 파일이면 공백11~14일 한곳, 같은 카드사 다른 카드 파일10~15일을 추가하면 공백0이다. [현행 명세](history/specs-20261110/card-transaction-date-gaps-20261108.md), [PR #745](https://github.com/6Soo/cost/pull/745).
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

- 사용자 `미커밋 변경사항까지 모두 검토해서 배포`와 `모두 확인해서 메인으로 병합 운영배포해` 범위. [PR #735](https://github.com/6Soo/cost/pull/735), 검수 HEAD `1ee5c6983f11e59bb1a2b52f3df90f1eab487165`, 운영 SHA `d043892777dc50d1e61d3478440f4148719fd39f`. [28파일 판정·수락 기록](history/specs-20261110/review-all-uncommitted-release-20261108.md). 원래 로컬8커밋의 이력과 미커밋25·미추적3파일을 모두 검토했다. 유효 변경은 통합하고 원본/권한/환불 보호 제거는 제외·보존했다. 영수증 PR733도 같은 SHA로 운영 반영했다.
- 어드벤처코리아 항공료, 여행 관리 단일 집계, 모바일 수입/보험/금액, 실제 OPEN 사용자 작업, 행별 지출 복사, 정상 구매의 유효한 결제 분기 fallback을 반영했다. 조회 실패를 0건으로 숨기지 않고 정상 P1/P2를 사용자 업무로 만들지 않는다. 메일 캐시의 disabled-gate 의존성과 짧은 보험 문구에서 긴 날짜/이름이 겹치는 결함도 수정했다.
- 최종 Windows 영향 QA **1166 passed +133 subtests, skip0, 필수 브라우저 72/72, compile PASS**. 초기6실패와 모바일 겹침 red는 보존했고 최종 고정SHA에서 교정 후 통과했다. 독립 실제 `gpt-6.1-sol / medium` 정확SHA 승인·interface-review Approve. CI42411351988/job128519990700은 결제/사용 한도로 steps0에서 차단돼 기존 승인 예외를 적용했으며 CI 녹색으로 보고하지 않는다.
- 공식 SHA 고정 git archive·tracked blob mismatch0, 단일 배포 lock·PREVIEW/APPLY 완료. 이전 `d97158484d17f974668dafffafdb1a7b462a7249`에서 전환했고 runtime/task/process SHA 일치, loopback backend, health/ready200·보호 API401·보호 테이블13개 불변을 확인했다. 운영 분류/여행 교정·재처리·원본/금융/Google 쓰기·마이그레이션은 실행하지 않았다.
- 인증 GET 수락: 카드·여행·영수증 영향 화면 main/heading 및 coverage API200 확인. 고객 원본 파일 확인 POST는 실행하지 않았다. 합성 1440/390/320 동일크기 전후 및 짧은 보험 stress에서 페이지 넘침0·텍스트 행 침범0, 키보드 포커스와 light7.5777:1/dark5.7053:1 대비 확인. 전체 고객 화면 시각 수락·실제 기기·스크린리더 음성·RTL/OS확대는 미검증이다. 과거 고객 영수증 파일을 복구했다고 주장하지 않는다.
- root main은 보존 stash `484adc3acd41374568e1ac39e4f18d4d0d2a8b60` 생성 후 정상 fast-forward했다. 기존 stash6개와 원본28파일 snapshot은 모두 보존했다. 비공개 근거 `.local-archive/uncommitted-release-20261108/` 및 `.local-archive/all-main-review-20261108/`. 이 후속 기록은 문서 전용이며 재배포하지 않는다.

## 2026-11-08 카드 내역 거래일자 공백 전환 #731 운영 완료

- 최신 사용자 결정에 따라 조회기간 대시보드·확인/관리 시작일 폼을 폐기하고 실제 거래일 사이 공백으로 전환했다. 카드사·끝4자리 표시 그룹별 첫/마지막 거래일 내부만 계산하며, 정상 미사용일일 수 있으므로 자료 누락으로 단정하지 않는다. [수락 계약](history/specs-20261110/card-transaction-date-gaps-20261108.md), [PR #731](https://github.com/6Soo/cost/pull/731).
- 정확한 검수 HEAD `4c2120fd6ab0d9f2a06a9f35d6b78b2e35b50fae`: Windows 영향 QA **503 passed +100 subtests, skip0, browser35/35, compile/데이터 보호 PASS**. 초기 red3은 기준 커밋에도 존재하는 오래된 브라우저 테스트명2와 구 조회기간 표시를 기대한 인증 HTTP 검사1이며, 검사를 제외하지 않고 현재 동작·보호 계약에 맞게 고쳐 green으로 재검증했다.
- Sol `gpt-6.1-sol` / `medium`의 실제 Paseo runtimeInfo를 확인하고 위 HEAD 최종 PASS 및 병합 SHA 동일 트리 검수를 받았다. GitHub run42407181997/job128507289518은 결제 실패/지출 한도로 steps0에서 차단됐다. 2026-11-07 사용자 승인 예외를 적용했고 CI를 녹색으로 표시하지 않는다.
- 운영 SHA **`d97158484d17f974668dafffafdb1a7b462a7249`**, 이전 `3dfcd72405d602504b6b8842d53e957aba31f929`. 승인 HEAD와 병합 SHA tree `a1e3a385e328c2aaca4a89bfa35b35468927de2b` 동일. 공식 PREVIEW→APPLY 1회, 1,435 tracked blobs mismatch0/list mismatch0. 단일 task/process SHA 일치, Gateway8790→loopback8752, health/ready200·보호API401, 보호13표 전후 불변. 롤백 릴리스와 task 복구점 유지. 운영 DB/원본/분류/환불/Google 쓰기·스키마 변경 없음, financial_apply NOT_RUN.
- ego-browser 합성 전후1440/390/320px, 긴 파일명·22구간 접기/펼치기·공백→업로드·포커스/Escape·빈 상태/오류 재시도 PASS, 다크 요약 라벨 대비4.04→9.90:1 수정. 720 CSS px의200% 상당 reflow 확인; 실제 브라우저 확대·스크린리더·실기기·RTL 미검증.
- 인증된 운영 GET/API·DOM에서 **23파일/27표시그룹/515공백/날짜없는파일0**, 거래일자 상태·coverage panel 및 구 조회기간/관리 시작일 폼0 확인. 운영 DB mode=ro 사전 집계156ms. 이는 전체 고객 화면의 독립 시각 수락·전후 운영 진입성능 측정 완료를 뜻하지 않는다. 고객 파일명·거래 원문은 보고서/Git에 넣지 않았다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-d97158484d17f974668dafffafdb1a7b462a7249.json`, 비공개 `C:/AX/cost/.local-archive/transaction-gaps-20261108/`의 배포/사후 smoke/보호표·QA·독립 검토·브라우저 기록. 기존 main의 다른 미배포 로컬 커밋8개는 포함하지 않고 보존했다. 이 운영 기록 등 문서-only 후속은 재배포하지 않는다.
- 2026-11-10 17:06 KST Gmail 수집 토큰 만료(테스트 상태 OAuth 앱 7일) → 재인증·프로덕션 게시로 복구. 수집이 HTTP 400으로 실패하면 운영 릴리스에서 `python -m app.mail_collect --authorize …`로 재인증한다(현재 상태 문서 참고).
