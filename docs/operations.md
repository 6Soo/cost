## 2026-11-06 여행 항공권 예약 UI 개선 — COMPLETE

- [PR #695](https://github.com/6Soo/cost/pull/695) 병합·운영 SHA `658aeeefbe867d0ae81bd4f108f2bc29d54fd3e7` (이전 `5ede21297b93c648fb631c111b3150bcdc6df739`). 경로 우선 전체 행 선택·선택됨 표시, 넓은 패널 목록/상세 병렬 배치, 모바일 세로 배치, 가는편/오는편·탑승객·근거 구분. 금융·원본·분류·여행 배정·환불·Google 쓰기 없음.
- Windows 영향 QA123 passed·skip0·필수 브라우저 전부 실행 at `333c5b783a762469b5443a07a511cf9fe43d75cd`; 별도 표적42 passed·최종 브라우저8 passed. PR CI42053458285/main CI42053848046 SUCCESS. 독립 interface-review MEDIUM 수정·재검토 완료, 잔여 HIGH/MEDIUM0. 합성1363/680/390/320px·다크·200% CSS 확대·키보드·대비 검증.
- 공식 단일 작성자 배포: 1,417 blobs 불일치0·task/process SHA 일치·Gateway8790→8751·health/ready200·보호API401·보호13표 불변·금융apply NOT_RUN. 코드 전환이며 별도 전체DB 백업/복원·마이그레이션·대량 재처리 없음.
- 인증 운영 브라우저 PC/모바일에서 예약3건·선택1건·새 workspace 표시·상세 정상·가로 넘침0 확인. 배포 전 source unavailable 및 최초 접속 timeout은 재시도/워밍 후 해소됐으며 실제 예약 조회까지 수락했다. 고객 화면은 비공개 로컬에만 보존.
- [수락·검증 기록](specs/flight-booking-panel-ui-20261106.md), 비공개 증거 `.local-archive/flight-ui-20261106/` (impact-summary/log, junit, interface-review, 합성 전후/운영 화면, production-browser, deploy-evidence). 물리기기·수동 스크린리더·RTL/번역 미검증. 이번 요청의 남은 작업/차단 없음. 후속 기록은 문서 전용이며 재배포하지 않는다.

## 2026-11-05 여행 헤더 출력 전용·본문 작업 이동 — COMPLETE

- 최신 사용자 결정 **헤더에는 XLSX 출력만, 나머지는 본문 작업 영역으로 이동**을 [PR #690](https://github.com/6Soo/cost/pull/690)으로 구현·병합·운영 반영했다. 마감·여행 관리·예약·참가자는 본문 `여행 작업`으로 이동하고 기존 기능/권한/CSRF/revision/여행 맥락을 유지한다. [상세 명세·검증](specs/trip-header-alignment-20261105.md).
- Windows 최종 영향 base8095d8ec → headb4e3903c: **387 passed+99 subtests, skip0·필수브라우저29전건·compile PASS**. 첫 `--base origin/main --run`은 병합 후 NO_CHANGES였으므로 통과 근거로 사용하지 않고 원래 base SHA를 고정해 재실행했다. PR CI42044031101·병합 CI42044789877 SUCCESS. 독립 interface-review Approve 및 최종 테스트4줄 변경 후 승인 유지. 합성320/390/760/1440px×라이트/다크8조건·200%·키보드 확인.
- 23:36 KST 공식 단일 작성자 배포: 운영 **`5ede21297b93c648fb631c111b3150bcdc6df739`**, 이전6a6095bd. 1415blobs불일치0/runtimeSHA일치/listener1/Gateway8790→8752/healthready200/보호API3개401/보호13표전후불변. 금융 apply NOT_RUN, Google/원본/분류/여행 배정/환불/스키마 쓰기 없음.
- 인증 운영1440/390px에서 헤더XLSX단독·본문관리/예약/마감·가로넘침0·키보드열닫/포커스 확인. 운영1440px 시각 확인 완료. 운영390px 저장 이미지는 리사이즈 직후 이전 프레임이 남은 캡처여서 시각 수락 근거에서 제외하며, 해당 폭은 DOM/키보드 결과와 합성390px 시각 근거로 구분한다. 물리기기·수동 스크린리더 미검증.
- 비공개 증거 `.local-archive/trip-header-align-20261105/`의 placement-run-summary/junit/final-quality/interface-review/results, production-browser.json, deploy-evidence.json; 호스트 `D:/WebLedgerHost/releases/deploy-evidence-5ede21297b93c648fb631c111b3150bcdc6df739.json`. 고객 원문/화면은 Git에 넣지 않는다. 배포 잠금 반납·현재 요청 미결0·다음 기능 명령 없음. 이 문서 기록으로 재배포하지 않는다.

## 2026-11-05 보험 명단 텍스트 동작·행 높이 복구 운영 배포 — COMPLETE

- [PR #689](https://github.com/6Soo/cost/pull/689) 병합a88257a8, 운영 `6a6095bdf3ede9f16d5c6d075d35ef6ee1a011df`(이전ae64bd19). 파란 강조·테두리 박스 제거·동작/포커스 유지·표 행 높이45→36px/모바일93→72px. [상세 근거 및 미검증](specs/insurance-plain-actions-20261105.md).
- Windows 영향208+36subtests·skip0·필수browser20/compile통과, 표적22·Ego8조합/키보드/hover/CSS200%/긴이름·독립리뷰Approve. PR CI42036622325 SUCCESS. a882 push CI취소는통과아님; 문서3개차이의최종main6a6095bd CI42037790866 SUCCESS와 코드blob동일성으로SHA고정.
- 22:43 KST 공식단일작성자전환:1414blobs불일치0/runtimeSHA일치/listener1/Gateway8790→8751/healthready200/보호API401/보호13표전후불변/financialapply NOT_RUN. 금융·Google·원본·연결데이터·스키마·대량처리없음. 증거 `.local-archive/insurance-plain-20261105/deploy-evidence.json`, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-6a6095bdf3ede9f16d5c6d075d35ef6ee1a011df.json`. 잠금/작성권반납, 이 기록은재배포하지않음.

## 2026-11-05 여행 장부 항공 이용일 누락 수정 — COMPLETE

## 2026-11-05 항공권 여행 그룹·탑승객 중심 UI #684 — 운영 완료

- 사용자 요청: 배정된 여행별 그룹·탑승객 중심 항공권 결과·구체적인 원본 확인/카드 조회 동선, 이후 `fix/flight-passenger-grouped-release-20261105` 병합·정리. [상세 명세](specs/flight-passenger-trip-grouping-20261105.md).
- [PR #684](https://github.com/6Soo/cost/pull/684) 최종 코드 `c02244d2edb66afb684657213bbe66407464dbe3`, 병합·운영 SHA `ae64bd19c29f6a5347212f53c25408f870e283ac`. PR CI42036009335·main CI42036639901 SUCCESS. 초기 Linux 확대 실패를 검사 제외 없이 본문 container 재배치·버튼 nowrap 교정으로 해결했다. 독립 리뷰의 버튼 잘림 Block도 수정 후 Approve로 해소했다.
- 최종 Windows 영향 검사: `python tools/run_quality_checks.py --base origin/main --run`, base `4c2e9656f4674a378da6dda6369697b4f4793f10` → head `c02244d2edb66afb684657213bbe66407464dbe3`, **324 passed + 16 subtests, skip0·필수 browser 누락0·compile PASS**. 같은 입력390/1440px 전후 화면,320/390/760/1440px·200% 확대(745≤760px), 독립 interface-review Approve. 화면 상태·명암·키보드 기존 검증은 상세 명세와 로컬 근거에 보존한다.
- 공식 `deploy_verified_release.ps1 -Apply` 단일 작성자 전환: 이전 `bd75f63f380d7bcd0e4424ade74fb1360cfe541e` → `ae64bd19c29f6a5347212f53c25408f870e283ac`, gateway8790→8752, 1,413 tracked blobs 불일치0·runtime SHA 일치·listener1·health/ready200·보호 API3개401·금융 보호13표 내용/스키마 전후 불변. 금융 apply NOT_RUN·Google/원본/스키마/실제 여행 배정 쓰기0. 인증된 실제 `/flight-passengers` 읽기 스모크에서 검색 입력·예약 조회 버튼·최종 container CSS 확인.
- 보존·정리: 해당 임시 workspace만 정리하는 범위이며 타 작업공간·미커밋·stash6개는 유지한다. 미추적 QA3파일61,678bytes를 기본 폴더에 SHA256 검증 복사했다. 공식 workspace archive와 병합된 코드/기록 브랜치 정리는 이 기록 병합 후 진행하며, 최종 결과는 로컬 checkpoint에 기록한다.
- 근거: `.local-archive/flight-passenger-ux-20261105/`의 `preserved-worktree/manifest.json`, `review-final.md`, `container-checks.json`, `production-smoke.json`, `deploy-evidence.json`; 호스트 `D:/WebLedgerHost/releases/deploy-evidence-ae64bd19c29f6a5347212f53c25408f870e283ac.json`. 수동 스크린리더·물리기기·실고객 카드조회·예약처 외부 로그인은 미실행. 보관 메뉴 질문은 읽기 설명만 수행했고 메뉴/여행 보관값은 변경하지 않았다. 병렬 #689/#690은 이 운영 SHA에 포함하지 않았으며 그 완료를 주장하지 않는다.


- 원인: 이용일 출력이 숙박비로 제한돼 항공 예약 여정이 수집돼도 항공료는 공란이었다. [PR #686](https://github.com/6Soo/cost/pull/686)으로 저장 기간 우선·검증된 fresh 여정 출발일 보완 및 PC/모바일 표시를 수정했다. 금액·결제일·예약 관계·분류·여행·원본·Google 쓰기 없음.
- 최종 제품/배포 SHA `bd75f63f380d7bcd0e4424ade74fb1360cfe541e` (이전 `1b8aafc06ef3d692b6f7e8f691bb16a755ab2263`). 1,412 blobs 불일치0, task/process SHA 일치, Gateway8790→8751, health/ready200·보호API401·보호13표 불변. 공식 단일 작성자 전환 성공, 금융 apply NOT_RUN.
- 검증: 표적99 passed, 최종 Windows 영향303 passed+64 subtests·skip0·필수브라우저19전건실행·compile 통과. PR CI42032276925/main CI42033651257 SUCCESS. 앞선 검사2실패는 실행 도중 main 변경으로 메모리/디스크 자산이 달라진 검사이며 고정757f8e06에서 전체 영향 검사를 다시 통과했다. 독립 UI 리뷰 Approve, 합성1440/390/320px·다크/200%·키보드 및 운영1440/390px 수락. 물리기기·수동 스크린리더·번역/RTL 미검증.
- 인증 운영 장부: 저장 예약 연결이 있는 항공료1행에서 `06.30 · 07.04` 및 전체날짜 툴팁/모바일 표시 확인·가로 넘침0. 최초 배포 직후는 예약 근거 워밍 중으로 미확인, fresh 갱신 후 표시를 확인했다. 나머지 항공료/환불2행은 설명에 번호만 있고 저장 reservation_no가 공란이므로 이용일 미확인 유지. 설명을 예약 관계로 승격하거나 환불/금융 연결을 변경하지 않았다.
- 상세: [항공 이용일 명세](specs/ledger-flight-service-dates-20261105.md). 비공개 증거 `.local-archive/flight-service-dates-20261105/`의 final-impact-summary/log, interface-review, production-browser.json, production-*-target.png, deploy-evidence.json 및 호스트 동일 SHA deploy-evidence. 고객 원문/화면은 Git에 포함하지 않았다. 이번 요청의 표시 수정 미결0. 후속 문서 커밋으로 재배포하지 않는다.

## 2026-11-05 보험 명단 버튼 UI 통일 운영 배포 — COMPLETE

- [PR #682](https://github.com/6Soo/cost/pull/682), 운영 SHA `1b8aafc06ef3d692b6f7e8f691bb16a755ab2263`, 이전 `aaa96c5c8eef567d76f8e6f9da28be2e5587642f`. 공식 `deploy_verified_release.ps1 -Apply` 단일 작성자 전환 완료, 1,409 blobs 불일치0·task/process SHA 일치·Gateway8790→backend8752·health/ready200·보호API401·보호13표 불변·금융apply NOT_RUN. 잠금/작성권 반납 완료.
- 표적21·별도 카드업로드 인접24 통과, 합성 ego8폭/테마 조합·키보드·독립 UI 리뷰 Approve, PR CI42029891492/main CI42031450310 SUCCESS. Windows 영향QA는209통과+36subtests·기존배치실패1·skip0/필수브라우저21전건실행이며 기존 실패를 전체통과로 보고하지 않는다. 변경 전에도 같은 실패를 재현했다. [상세 검증·미검증·증거](specs/insurance-button-ui-consistency-20261105.md).
- 증거 `D:/WebLedgerHost/releases/deploy-evidence-1b8aafc06ef3d692b6f7e8f691bb16a755ab2263.json`, `.local-archive/button-ui-20261105/`. 실제 고객 데이터/Google/참가자 연결/스키마 쓰기와 대량 재처리 없음. 후속 문서는 재배포하지 않는다.

## 2026-11-05 PR·임시 작업공간·브랜치 통합 정리 — COMPLETE

- 사용자 “임시워크스페이스, 브랜치, pr등 모두 병합하고 운영배포 후 삭제” 범위 완료. [PR676](https://github.com/6Soo/cost/pull/676) 병합 `48e246cdc92532e4dbd653c588883aae97537b56`; 기존 #567·#607·#630·#651 모두 MERGED, 열린 PR0. 날짜별 문서는 보관 상태로 구분하고 최신 구현을 보존했다. [상세 기록](specs/merge-cleanup-20261105.md).
- 임시 worktree26개 정리(Paseo 소유1개는 공식 archive), 기본 `C:/AX/cost`만 유지. 로컬 임시 브랜치104개·원격113개 삭제, 양쪽 main만 유지. 이전에 archive된 작업공간의 잔여 폴더9개는 파일 해시를 확인해 로컬 보관함으로 이동했다.
- 원본·QA·미커밋 사본7,603개/402,099,913 bytes 해시 확인, Git bundle·보관 ref와 기존 stash5개 유지. 기본 폴더의 미커밋 변경은 추가 복구 stash와 파일/patch로 보존했다. 자동 재적용으로 최신 구현을 덮지 않았다. 복구 위치 `.local-archive/merge-cleanup-20261105/preserved/`, stash ID `user-stash-sha.txt`, 전체 ref `before-cleanup.bundle`.
- 운영 앱 `aaa96c5c8eef567d76f8e6f9da28be2e5587642f` 유지. 비문서 blobs1,298개 불일치0, main과 차이는 Markdown뿐이므로 앱 재배포/재시작 없이 task/process SHA·단일 loopback8751·health/ready200·보호API401 확인. 기존 공식 배포의 보호13표 불변 근거를 재사용하며 이번 문서 정리로 DB를 새로 읽거나 쓰지 않았다.
- 마지막 빈 임시 폴더를 잡은 기존 cloudflared30624는 새 임시 replica의4연결·ready200 확인 후 종료했다. 공식 Board 감독자의 새 tunnel4844가4연결/ready200으로 인계받은 뒤 임시 replica24328도 종료했다. 공개 ledger.foresttour.kr health/ready200·보호API401 확인, 빈 폴더 삭제 완료. Board/Gateway Running, 앱 서버 재시작·설정/DB/Google/원본 변경 없음.
- 검증: 문서 영향 검사 DOCS_CHECKED·diff/링크/상태 확인, PR CI42005627007·main CI42006033443 SUCCESS. 새 코드 테스트·빌드·브라우저·DB 검사는 문서 전용 변경이므로 미실행. 증거 `.local-archive/merge-cleanup-20261105/`의 inventory/preservation/runtime/code-equivalence/worktree-cleanup/remnants/tunnel-handover 결과. 과거 별도 기능 PARTIAL·미검증은 이번 정리로 완료로 바꾸지 않는다. 현재 정리 요청 미결0·다음 기능 명령 없음.

## 2026-11-05 PR #665 통합 사용자 확인함 구현 및 운영 배포 — 완료

- [PR #665](https://github.com/6Soo/cost/pull/665) 설계 명세에 따라 통합 사용자 작업함 기반, 카드 비용 항목 도메인 어댑터, 분산 보류 UX 제거를 구현하고 [PR #674](https://github.com/6Soo/cost/pull/674)로 정상 main 병합 및 운영 전환을 완료했다.
- 병합 및 공식 배포 SHA: `aaa96c5c8eef567d76f8e6f9da28be2e5587642f` (이전 운영 SHA: `01e9db6427c7afe9a89b04c48f70a1c3a1f4a039`).
- `deploy_verified_release.ps1 -Apply`를 통한 공식 단일 작성자 연속 전환:
  - 1,403 tracked blobs 일치 (blob_mismatches: 0)
  - task 및 runtime SHA 일치 (`aaa96c5c8eef567d76f8e6f9da28be2e5587642f`)
  - Gateway 8790 → backend 8751 단일 loopback listener 무중단 전환 (`ledger-route.json`: port 8751, paused: false)
  - `/healthz`: 200, `/readyz`: 200, 보호 API 3개: 401
  - 금융 보호 13개 테이블 불변 검증 PASS (`unchanged: true`, `tables: 13`)
  - 금융/Google 원본 자동 쓰기 및 DB 마이그레이션: 0건 (`financial_apply: NOT_RUN`)
- 검증 근거:
  - Windows 영향 QA: **948 passed · 60 subtests passed · skip 0 · 필수 브라우저 38개 전건 실행 통과**
  - GitHub Actions CI (PR #674, run `41994267844`): SUCCESS
  - 배포 증빙: `D:/WebLedgerHost/releases/deploy-evidence-aaa96c5c8eef567d76f8e6f9da28be2e5587642f.json` 및 `C:/AX/cost/.local-archive/unified-action-queue-20261105/deploy-evidence.json`

## 2026-11-05 업로드 결과 복구·정렬 UI 배포 — 완료

- [PR668](https://github.com/6Soo/cost/pull/668)의 `f9b6a2e7` 배포 후 실자료 상세 조회 약97초를 확인해 [PR672](https://github.com/6Soo/cost/pull/672)에서 소유자 전용 진행 API의 별도 read-only SQLite 집계로 보완했다. 최종 운영 `01e9db6427c7afe9a89b04c48f70a1c3a1f4a039`는 이전 검증 `f9b6a2e7bc33403a848d7750f2268643c5071f66`에서 공식 단일 작성자 전환했다. 중간에 반영된 사이드바 릴리스도 보존했다.
- Git1,399 blobs 일치·task/process SHA·Gateway8790→backend8752·health/ready200·보호API3개401·보호13표 전후 불변. 이전 릴리스/task XML을 보존한 코드 전용 배포이며 전체DB 백업/복원·금융/원본/분류/여행/환불/Google 쓰기·스키마 변경·재처리0.
- Windows 영향 UI334+46 subtests, 집계327+30 subtests·skip0 및 후속 표적18 passed(겹침 합산 안 함). PR CI41980944714/41982482852 성공. 실제174건 query-only 집계 약12ms·Ego27 인증 복구313ms/상세 링크/체크포인트0/가로 넘침0. 실제 사용자12건의 분류·기장을 완료한 것으로 표시하지 않는다.
- [상세 실행 기록](specs/upload-results-recovery-20261105.md), `.local-archive/upload-results-20261105/durable-deploy/deploy-evidence.json`, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-01e9db6427c7afe9a89b04c48f70a1c3a1f4a039.json`. 요청 미결0. 문서 후속으로 재배포·재시작·DB 검사하지 않는다.

## 2026-11-05 단일 계정 메뉴의 불필요한 관리 접기 제거 — 완료

- [PR #667](https://github.com/6Soo/cost/pull/667), 코드 `6760276a`, 병합·운영 `936fdc14d6f897416d837a23d806a21ad9f7a9a5`. 여행 관리·예약 연결이 여행 화면으로 이동한 뒤 계정 하나만 감싸던 ‘관리’ 제목과 접기를 제거했다. 계정은 기존 주요 메뉴의 직접 링크가 되며 전용 CSS·자동 펼침 JS도 제거했다.
- 발생 이력과 이전 `better-ui`/종합 검토 누락은 [원인·검증 기록](specs/sidebar-singleton-management-20261105.md)에 정리했다. 실제 메뉴를 대체하지 않는 회귀 검사에서 수정 전 9개 조건 실패, 수정 후 통과. Windows 영향 QA **226 passed·42 subtests·skip0·필수 브라우저 누락0**, PR CI `41980136732` 및 병합 CI `41980825360` 성공. 검사한 PR과 병합본의 전체 Git tree 동일.
- 2026-11-05 15:35 KST 공식 전환 성공. 1,398 blobs 일치, task/process SHA·단일 listener·Gateway8790→8752·health/ready200·보호 API3개401·보호13표 불변. `8e435e48` 복구 릴리스 보존. 금융/배정/Google/원본/스키마 쓰기 및 재처리 없음. 자동 분류의 진행 중 provider 작업이 제한시간 뒤 잠금을 놓을 때까지 기다렸으며 강제 해제하지 않았다.
- Ego26 합성 장부·계정·활성 항공의320/390/1440px·200%·테마·Tab/Enter, 동일1440×900/390×844 전후 캡처 확인. 운영 로그인 계정 화면의 직접 계정 메뉴·현재 표시와390px 리플로를 확인하고 정적 메뉴 부분만 캡처했다. 운영 항공 및 추가 장부 재탐색은 시간 초과로 수락하지 않았다. 수동 스크린리더·물리 기기·RTL/번역은 미검증. 이후 별도 PR668의 공식 배포 `f9b6a2e7`이936fdc14를 포함하며 같은 메뉴 수정은 유지된다.
- 근거 `.local-archive/sidebar-structure-20261105/`의 `run-summary.json`, `junit.xml`, `interface-review.md`, `after.json`, `contrast.json`, `live.json`, `live-mobile.json`, `deploy-evidence.json` 및 호스트 동일SHA release/deploy audit. 이번 메뉴 교정·배포 미결0. 문서 후속에는 재검사·재배포·재시작하지 않는다.

## 2026-11-05 기본 미마감 여행 선택 및 CI 검사 복구 — 완료

- [PR #664](https://github.com/6Soo/cost/pull/664), 운영 SHA `8e435e48e67987f3e0bb9140bf2066172ac77096`. 장부 기본 진입은 사이드바 첫 미마감 여행을 선택하며 지난 여행·보관·삭제 여행을 제외한다. 후보가 없으면 미분류 화면을 열고 명시적으로 선택한 여행은 유지한다. 브라우저가 기억한 여행이 현재 장부의 선택 표시와 복귀 링크를 덮지 않는다.
- 기존 CI 실패는 UIR01에서 제거한 전체 집계 배지를 옛 검사가 요구하던 문제였다. 실제 건수 계산·실제 자료의 배지 숨김·합성 자료 경고를 검증하도록 수정했으며 검사 제외 없이 통과했다. 최종 Windows 영향 검사 `4387eb01`: 547 passed·62 subtests·skip0, 병합 SHA 인접 검사 43 passed·16 subtests·skip0. PR CI `41971962067`, main CI `41973283929` 성공.
- 공식 배포기의 잠금 대기 중 최초 프로세스가 종료됐다. 기존 운영 서버를 유지하고 단일 배포 잠금 아래 신원을 확인한 준비용 후보만 정리한 뒤 공식 배포기를 재실행했다. 카드 업로드와 자동 정리 작업이 잠금을 놓은 후 2026-11-05 14:45 KST 전환 완료. 최초 배포 프로세스 종료 원인은 확인되지 않았으며 성공으로 취급하지 않는다.
- 최종 배포: Git blobs 1,393개 일치·runtime SHA 일치·Gateway8790→backend8751·health/ready200·보호 API3개401·보호13표 전후 불변. 이전 검증 `b3b1bb9098b2c88d23ba5653bcd7e90afd684135` 보존. 본 배포의 금융/여행 배정·원본·Google·스키마 쓰기 및 재처리 없음.
- 운영 수락: 배포본+운영 DB query-only 기본 여행/목록 순서 일치, DB 변경0. 기존 Ego21 인증 `/board`에서 첫 미마감 여행·장부 제목·선택 표시·기억된 여행 일치 및 가로 넘침0 확인 후 작업 공간 종료. 근거 `.local-archive/default-open-trip-20261105/`의 `deploy-evidence.json`, `live-default-readonly.json`, `live-browser-final.json`, `run-summary.json`, `merged-integration-meta.json`; 호스트 `D:/WebLedgerHost/releases/deploy-evidence-8e435e48e67987f3e0bb9140bf2066172ac77096.json`. 이 요청 미결0. 기록만의 후속에는 재배포하지 않는다.

## 2026-11-05 PR #658 결함 묶음 회귀 수정·배포

- 운영 DB의 읽기 전용 집계에서 PR #631에서 이미 해결한 날짜 alias 충돌 108건이 #652 결함 탐지기에 `pending_code_fix`로 다시 분류되는 것을 발견했다. 고객 원문은 출력하지 않고 opaque SHA-256 지문과 건수만 대조했다.
- 회귀 수정 PR [#658](https://github.com/6Soo/cost/pull/658)은 이 확인된 과거 충돌 지문만 코드 결함 묶음에서 제외하며 거래 원행·충돌 표시·금융 결정은 변경하지 않는다. 같은 PR의 합성 통합 검사는 Gateway 응답 중 워커 실패→재시도→복구, 금액/거래 수 및 보호 테이블 불변을 확인한다.
- 검증: 타깃 검사 4 passed. 영향 QA `242 passed`, skip 0, base `8e1d1db9`, 검사 SHA `15cdc9dd2f9338c4d39917b38e457998c7435ef0`. PR CI `41943273672` 및 main CI `41943503301` 성공. 병합 SHA `b3b1bb9098b2c88d23ba5653bcd7e90afd684135`.
- 배포: `deploy_verified_release.ps1` 공식 단일 작성자 전환 완료. 1,383 tracked files·blob mismatch 0·runtime SHA 일치·Gateway 8790→backend 8752·health/ready 200·보호 API 401·13개 보호 테이블 불변. 이전 SHA `79a3c57340cfadeb227e3748966a4baf0fd6ca63`를 보존했고 금융 apply는 `NOT_RUN`.
- 배포본의 지문 규칙을 사용한 읽기 전용 운영 재평가에서 반복 충돌 그룹 1개(108건)가 제외되고 미해결 transaction conflict 그룹은 0개였다. 원본·충돌 플래그·기존 번들 기록을 쓰거나 삭제하지 않았다. 근거: `D:/WebLedgerHost/releases/deploy-evidence-b3b1bb9098b2c88d23ba5653bcd7e90afd684135.json`, `C:/AX/cost/.local-archive/autonomy-defect-fix-20261105/`, 배포 후 read-only query.
- HDD 수락 재분석: 비교 구간 NTFS USN에서 `gateway-status.json` 6,202→216, `ota-snapshot.log` 82→44, `flight-search.log` 90→44, 자율정리 status 222→147 기록. 물리 D: 전체 쓰기는 132.9→221.0 MB, 평균 busy 0.672→0.945%로 증가해 디스크 전체 개선은 입증되지 않았다. 측정 세부는 통합 명세를 따른다.
- **미완료:** P2 실제 적용은 0건이며 정상 provider 경로 timeout이 해소되지 않았다. Google Sheets·금융 원본 쓰기, 인증/프록시 우회, 한도 초기화 및 강제 재처리는 수행하지 않았다. process별 쓰기 바이트 전후 측정도 남아 있다.

## 2026-11-05 PR #659 문서 통합 및 격리 Gateway I/O 재측정

- 문서 최신화 PR [#659](https://github.com/6Soo/cost/pull/659)은 main SHA `7ee7d1b6f2828a521696db277b3e5b272e5aead2`로 병합됐고 impact CI `41945397409` 성공. 문서 전용이므로 앱 재배포는 하지 않았다.
- D: `D:/WebLedgerHost/scratch-io-ab-20261105-0105/status-count-ab.json`에 격리 idle A/B를 기록했다. 같은 60초 동안 구형 Gateway status 파일 mtime 변경 58회, 신형 30초 heartbeat 2회(-96.6%). 각기 별도 loopback 포트·scratch route/status를 썼고 운영 8790/8752 listener는 유지됐다.
- 같은 격리 구간의 Windows process `IOWriteBytes`는 두 버전 모두 0으로 보고돼 프로세스 write bytes 계측에 사용할 수 없었다. 이전 실제 호스트 15분 PhysicalDisk 비교도 D: 쓰기 132.9→221.0 MB, busy 0.672→0.945%로 증가했다. 따라서 Gateway status 갱신 감소는 재현됐지만 process별 HDD bytes 및 전체 물리 디스크 감소는 미입증이다.
- 소스 검토에서 OTA·항공권 snapshot은 content-hash 입력 키가 같으면 held 결과를 재발행하지 않고, 키 변경이나 writer role 전환 때 발행함을 확인했다. #646는 OTA check 로그를 상태 변경/시간 heartbeat로 제한하고 회전시킨다. 이 코드는 불필요한 반복 snapshot/log I/O를 줄이지만 물리 write-byte 실측은 아니다.
- 호스트의 read-only 상태는 `state=running`, `passes=41`, `p2_applied=0`, `ai_retry=98`, `ai_dead=200`, `blocked=120`, `candidates=400`, `due=200`, `failures=0`이었다. 상태 파일 최종 갱신은 2026-11-05 00:50:32 UTC로 현재 관측 시점보다 오래됐으며 최신 무인 P2 성공 증거가 아니다. 허용된 provider 경로 timeout은 해소되지 않았다. 우회·cap reset·금융 재처리는 하지 않았고 P2는 BLOCKED 유지.

## 2026-11-05 PR #636·#644 통합 실행 — PARTIAL

- PR #646 정상 병합 `40ea7f9d`; 통합 복구 PR #652 정상 병합 `f7ff4ec41093d7e983bd8970bb3bf437e30d0718`. PR #652 Windows 영향 QA 550 passed·35 subtests·skip 0, PR CI `41933059071`, main CI `41933524311` 성공. 앱 운영 SHA는 PR #653 `79a3c57340cfadeb227e3748966a4baf0fd6ca63`; 이후 문서 PR #654/#655/#656 반영 후 최신 main은 `015312c4fb1c313021eca6dbf6e3c7360d315e94`.
- #652는 긴 P2 요청 임시 파일 전달, 실행 오류 분류, 코드 결함 묶음 및 판단 코드 변경 후 자동 재평가 fingerprint를 추가했다. 뒤이은 호스트 확인에서 Board는 descendant main `79a3c573`를 실행하고 관련 핵심 파일 해시가 main과 일치했다. P2 정상 연결 호출은 timeout됐고 보호된 대기열 이력은 그대로다.
- 운영 설정은 `automatic_card_completion=true`, `autonomous_ai_review=true`. 08:53 KST 마지막 상태 파일은 `state=idle`, `passes=333`, `p2_applied=0`, `ai_retry=18`, `ai_dead=20`, `blocked=400`, `candidates=400`, `due=0`, `failures=0`; 이후 갱신은 관측되지 않았다. 격리 synthetic OpenCode 호출은 정상 네트워크 경로에서 timeout. 프록시 우회·한도 초기화·금융 원본 재처리는 하지 않았다.
- `f7ff4ec4` 코드 전용 릴리스 후보 1,345 tracked blobs 일치. 첫 `deploy_verified_release.ps1 -Apply`는 8751 점유 검사에서 후보 준비 전 fail-closed했으나, 이어진 PR #653의 공식 배포가 `79a3c57340cfadeb227e3748966a4baf0fd6ca63`로 완료됐다. 호스트 evidence는 1,383 tracked files·blob mismatch 0·runtime SHA 확인·단일 listener·8751·health/ready 200·보호 API 401·13표 불변을 기록한다. 자율정리 worker·AI 분류·Gateway·OTA 4개 핵심 파일도 `origin/main`과 SHA-256 일치하고, 별도 현재 비교 `protection-check-79a3-20261105`도 13표 동일이다. Gateway는 8790에서 응답한다.
- `WebLedger-Gateway` 작업의 다음 실행 경로를 정식 릴리스 `f7ff4ec4`로 갱신했다. 현재 PID는 바꾸지 않았으며 실행 중 Gateway 코드 SHA-256이 릴리스와 일치한다. principal·trigger·settings·interpreter·working directory·route와 현재 PID는 유지됐다.
- 실제 D: HDD에서 격리 Gateway 15분 구형/신형 A/B를 측정했다. status 원자 교체는 886→31회(-96.5%), NTFS USN 관련 기록은 6,202→216건. 물리 D: 전체 쓰기는 132.9→221.0 MB, 평균 busy 0.672→0.945%여서 전체 HDD 감소를 입증하지 못했다. 상세 수치·범위는 [유휴 HDD 명세](specs/webledger-idle-io-optimization-20261105.md#2026-11-05-구현운영실측-결과), 원시 수락 자료는 `C:/AX/cost/.local-archive/autonomy-io-20261105-acceptance/`에 있다. 소음은 측정하지 않았다.
- 브라우저 구조 검사에서 320/390px 가로 넘침은 없었으나 인증 지출정리 화면이 브라우저 세션에 없어 실제 로그인 UI와 지출 검토 목록은 미검증이다. Google Sheets 및 금융 원본 쓰기 0.
- **남은 차단:** 실제 무인 P2 적용과 결함 자동 재처리 성공이 관측되지 않았고, 상태 파일은 08:53:56 KST 이후 갱신되지 않았다. 승인된 네트워크 경로에서 P2 요청·반영을 증명해야 한다. 상세 단계는 [현재 인계](session_handoff.md)와 통합 계획을 참조한다.

## 2026-11-05 지출 정리 문구·인라인 편집 및 여행 장부 뷰어 UI 개편 배포 완료

- COMPLETE — 사용자 “검토필요 장부기록가능이 대체 무슨 정보를 제공하는지 알수가없고 여행항목수정 버튼을 눌러서 단 두 줄의 버튼만 제공할거면 왜 만들었으며 UI까지 다 박살냄” 피드백 해결.
- PR: [PR #638](https://github.com/6Soo/cost/pull/638), [PR #640](https://github.com/6Soo/cost/pull/640), [PR #639](https://github.com/6Soo/cost/pull/639).
- 운영 전환 SHA: `37b82e5829a7b8a062e7a7e2a9fff7081bd3a737`, 이전 운영: `465760ba7cbc23ab46fe61eaa20eb06999510c70`.
- 주요 변경 사항:
  1. **지출 정리(Cleanup) 상태 문구 모순 해소**: 혼란을 유발하던 '장부기록가능' 문구를 “여행·항목이 지정되어 있습니다. COST 내부 비용 기록은 아직 없습니다.”로 수정하여 미기록 상태와 현재 연결 정보를 정확하게 안내.
  2. **지출 정리 인라인 편집기 개편**: 숨겨진 2줄 `<summary>` 버튼을 제거하고, 행 클릭 시 `<label>여행<select>`, `<label>비용 항목<input>`, `<button>변경 저장</button>`이 포함된 직관적인 인라인 그리드 폼 노출.
  3. **여행 상세 페이지 UI 복구 및 액션바 단일화**:
     - 상단 헤더 복구: 불필요한 import 버튼 노출을 배제하고 `XLSX 출력`만 `.act`에 남겨 반응형 뷰포트 오버플로우 방지.
     - 숙박 이용일 압축: 테이블 내 긴 이용기간을 `09.22–09.23 · 1박` 형식으로 요약하고 상세 날짜·요일·추론 근거는 툴팁에 보존.
     - 여행 작업 버튼군 일원화: `수기 지출 추가`, `보험가입내역`, `여행 검토`를 `.trip-actions` 단일 행 툴바(44px 보장, 단일 수평 정렬)로 모으고 `#trip-review-panel` 드로어를 통해 현재 여행에 귀속된 보험 후보·지출 복사·영수증·보류 거래 상세를 제공.
- 실제 검증:
  - Windows 영향 QA: 341 passed (29개 브라우저 케이스 포함), skip 0.
  - 최신 main 통합 테스트: 71 passed, skip 0 (`latest-main-integration.xml`).
  - GitHub Actions CI: PR #639 CI(`41906688103`) 및 main push CI(`41907354625`) 통과.
  - 배포 후 테스트: `test_trip_review_actions.py` (1 passed, 5 subtests passed), `test_core_ui_disclosure.py` (3 passed).
- 배포:
  - `tools/deploy_verified_release.ps1 -Apply` 성공.
  - 1,343 tracked blobs 일치 (blob_mismatches: 0).
  - task/process 고정 SHA 검증 (`37b82e5829a7b8a062e7a7e2a9fff7081bd3a737`).
  - gateway 8790 → backend 8752 연속 전환 완료 (`ledger-route.json`: port 8752, paused: false).
  - `/healthz`: 200, `/readyz`: 200, 보호 API (`/api/imports/ota`, `/api/imports/ota/summary`, `/api/maintenance/refund-pair/synthetic/preview`): 401.
  - 금융 보호 13개 테이블 불변 검증 PASS (`unchanged: true`).
  - 실제 금융·Google 장부 쓰기 0건.
- 근거: `C:/AX/cost/.local-archive/trip-review-20261105/` 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-37b82e5829a7b8a062e7a7e2a9fff7081bd3a737.json`.

## 2026-11-05 여행 탭에서 마감·여행 관리 및 예약 연결 통합 완료

- COMPLETE — 사용자 “여행관리가 왜 여행 탭이 아니라 별도 메뉴로 존재해야하지? 예약명단 여행연결이란 메뉴가 왜 필요하지? -> 바로 진행해” 반영. [PR #642](https://github.com/6Soo/cost/pull/642), 머지 `465760ba7cbc23ab46fe61eaa20eb06999510c70`, 고정 운영 `465760ba7cbc23ab46fe61eaa20eb06999510c70`, 이전 운영 `73075112214a81151e07b54bb02a0615b9833b86`.
- 여행 상단 액션바에 '마감' 버튼과 '여행 관리' 메뉴(표시 이름, 작성일, 담당자 수정, 보관)를 통합하고, 여행 화면 본문에 '예약·참가자 여행 연결' 섹션을 배치하여 개별 여행 안에서 모든 맥락 작업을 수행할 수 있도록 개편. 사이드바의 독립 관리 메뉴 2종은 제거(URL 직접 접근 호환성은 보존).
- 검증: Windows 영향 QA 692 passed·88 subtests·skip 0, PR CI 41899301788 success. `test_trip_context_management.py`, `test_reserve_navigation.py`, `test_reserve_navigation_browser.py`, `test_ledger_design.py` 통과.
- 배포: `deploy_verified_release.ps1 -Apply` 성공. 1,338 tracked blobs 일치, task/process SHA 일치, gateway 8790 → backend 8751 전환, healthz/readyz 200, 보호 API 401, 보호 13개 테이블 불변 PASS. 금융·원문·Google 업무 쓰기 없음.
- 근거: `C:/AX/cost/.local-archive/trip-context-deploy-20261105/` 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-465760ba7cbc23ab46fe61eaa20eb06999510c70.json`.

## 2026-11-05 제주항공·Traveloka 항공권 OTA 수집 보완

- [PR #634](https://github.com/6Soo/cost/pull/634), 운영 `43907dd375bffa860a3415e2330082d12948e8fe`, 이전 `2e911f3f6fdb853f1635f720ea259f6191541008`. 상세 [실행 결과](specs/airline-mail-collection-20261105.md#2026-11-05-운영-반영-결과).
- Windows 영향509 passed·4 subtests·skip0, CI41890085930 success, 병합 인접14 passed.1333 blobs 일치·task/processSHA·단일 backend8751·health/ready200·보호API401·보호13표 불변. 첫 gateway 상태 읽기 충돌은 기존 운영 복구 확인 후 재시도 성공했다.
- 백업/격리 복원 검증 후 새 원문138건·기존3건 직접 수집 출처를 원자 추가했다. 새 운영 복구 사본·기존 원문 전체/스키마 불변·integrity_check PASS. 운영 재파싱 제주128메일/102예약·Traveloka11메일/5예약 PASS. 실제 금융 결제·환급·탑승 확인과 구분한다.
- MailCollect를 새 SHA와 명시 제주항공 owner-domain 옵션에 연결하고 Ready 확인. 클라우드 query 보완은 저장소 코드에 한하며 원격 Apps Script 업로드/전환 미실행, 새 메일 도착 후 정기 실행 미관측. 금융·여행·Google 쓰기/스키마 변경0.
- 비공개 근거 `C:/AX/cost/.local-archive/airline-audit-20261105/`, 복구 사본 `D:/WebLedgerHost/data/backups/airline-mail-20261105-private/`, 호스트 `deploy-evidence-43907dd375bffa860a3415e2330082d12948e8fe.json`. 문서 후속으로 재배포·재시작하지 않는다.

## 2026-11-05 카드 업로드 후속 처리 오류

- COMPLETE — [PR #633](https://github.com/6Soo/cost/pull/633), 구현 `6279dae4`·검사 fixture 수정 `2bbaa5379f94d1165da0b53be30d65fa99ee44f6`, 고정 운영 `2e911f3f6fdb853f1635f720ea259f6191541008`, 이전 검증 `94ccd9b334220bc14b11b1c50decd7f13606fa92`. [명세/수락](specs/upload-audit-recovery-20261105.md).
- 운영 DB 읽기 전용 격리 사본에서 classify→sync_ledger_rows→save→감사 append 실패를 재현했다. projection revision은 올라갔으나 감사 stream이 없는 행을 correct로 기록하려던 문제다. 실제 stream으로 최초/후속 기록을 결정한다. 최초 감사/연속 교정·멱등성·원본/수동 결정·감사 체인 보호 회귀2건은 수정 전 red, 수정 후 green이다. 401/403 안내를 구분하며 기존 파일 체크포인트를 유지한다. 과거 인증 만료의 직접 원인은 재현하지 못했다.
- 검증: 초기 표적36 passed·44 subtests, 최종 Windows 영향 QA401 passed·33 subtests·skip0·필수 브라우저 누락0, PR CI41889472534 success. 기존 relay fixture의 암묵적 저장 방식 실패는 baseline에서도 재현됐고 의도한 분리 모드를 명시했다. 검사/병합 runtime blobs 동일, 병합 시 독립 문서 차이만 검토. 전체 회귀는 국소 변경으로 미실행.
- 공식 연속 전환은 2026-11-05 03:47 KST PASS, candidate 사전 준비·기존 요청 drain 후 gateway8790→backend8752. 이전 agent의 사용량 제한 후 successor가 원래 보호 기준·현재 task/processSHA·loopback listener1·health/ready200·보호API3경로401·보호13표 내용/스키마 동일·Board/Gateway/SourceRefresh Running을 검증하고 최종 deploy-evidence를 기록했다. 1,329 tracked blobs 불일치0. 전환 반복/재시작 없음. 첫 후속 HTTP 검증 호출의 실패는 정상 완료로 취급하지 않았으며 독립 상태 조회와 이후 최종 검사에서 정상 응답을 확인했다. 당시 응답코드/원인은 확보하지 못했다.
- 기존 Ego2/p1 인증 수락: 업로드 화면 새401/403 분기 확인·저장 상세GET200(327행, classified320/needs_review7)·없는 작업GET404/UPLOAD_STATUS_EXPIRED·가로넘침0. TaskSpace 정상 종료. 읽기 검증상12파일 모두 저장/배치 classified·파싱 오류0이며7행은 원본 충돌 보호를 유지한다. 실제 고객 재업로드/운영 재처리·실기기 확인은 미실행이다.
- 코드 전용으로 이전 검증 릴리스/task XML을 보존하고 전체DB 백업/복원을 반복하지 않았다. 금융/분류/여행/환불/Google/원본/스키마 업무 쓰기0. 근거 `C:/AX/cost/.local-archive/upload-fix-20261105/`의 review/received-state/resume-checkpoint/live-browser/protection-before/after/deploy-evidence, `C:/AX/cost-upload-fix/quality-artifacts/`, 호스트 동일SHA continuous-switch/release-audit/deploy-evidence. 미결0. 문서 후속만으로 재배포·재시작하지 않는다.

## 2026-11-05 지출 정리 거짓 원문 충돌 108건 교정

- COMPLETE — [PR #631](https://github.com/6Soo/cost/pull/631), 구현 `c70dff8d`·원본 파일 해시 보호 `157a8439`, 운영 `94ccd9b334220bc14b11b1c50decd7f13606fa92`. 이전 검증 `804eac6023ddcddb90c7959b66fce970bb656ef2`. [실행 범위](specs/cleanup-export-conflicts-20261105.md).
- 원인: 인증 운영 화면118건 중108건은2026-11-04 재수집 시 생성된 동일 원행의 거짓 충돌이다. 원본CSV는 명시 매입일 헤더가 없는데 parser가 이용일로 대체했고, 새 하나 이용내역은 실제 매입일을 제공했다. 카드/발급사·승인번호·이용일·금액이 일치하며94건은 가맹점명도 같다. 나머지14건은 가맹점명의 확장/축약과 동일한 명시 가맹점번호를 원본 파일에서 검증했다. 명시 매입일 누락과 파일 해시 변경의 회귀를 red 재현했다.
- 변경: 원본 bytes의 저장SHA256·행 source_hash·parser/header를 대조한 근거로만 기본 날짜를 허용한다. 가맹점 차이는 부분 명칭과 같은 명시 가맹점번호까지 요구한다. 미래 업로드는 같은 승인 원행을 재사용한다. 기존108개 행은 원본/ID/충돌 플래그/분류/수동 결정/장부를 바꾸지 않고 지출 대기열의 중복 작업에서만 제외한다. 실제 명시 날짜·금액·가맹점 차이, 복수 원결제 후보, 원문 오류·수동 결정/보류·장부 기록은 보호한다.
- 검증: 최종 검사 `157a8439c136815b54840a3de479afaf34fdd921`, Windows 영향 QA483 passed·42 subtests·skip0·필수 브라우저 누락0, CI41886588452 success, 검사/병합 tree 동일. 재사용/멱등성·원문/수동/중복·부분환불·OTA exact·권한·대기열 집계/목록/필터/render 읽기 전용 검사를 포함한다. 선행482검사와 후속483검사를 합산하지 않는다. 초기 hosted CI41885527350은 Chromium 설치 지연 중 새 커밋으로 대체돼 중단했으며 최종 근거가 아니다.
- 배포: 1,328 Git blobs 일치·task/process 고정SHA·loopback listener1·gateway8790→backend8751·health/ready200·보호API401·영향3경로401·보호13표 내용/스키마 전후 동일. 최초 drain30초 시간 초과 시 새 릴리스를 활성화하지 않고 이전 라우트 재개/준비 작업 정리·보호13표 동일을 확인했다. 활성 연결이 자연 종료돼0인 상태에서 동일 공식 배포기를 정상 재실행했다. 요청 강제 종료·drain 게이트 우회 없음. 이전 검증 릴리스/task 복구점을 보존하고 코드 전용이라 전체DB 백업/복원은 반복하지 않았다.
- 운영 수락: 호스트 Python과 실제 배포 파일을 사용하고, store initializer 없이 mode=ro/query_only 연결·운영 Google snapshot/일정 권한·실제 trip_valid로 전체10건·목록10행·금융6/기록4/근거충돌0을 확인했다. 검사 중 DB total_changes0. 이는 배포본 업무 코드의 읽기 대조이며 인증 브라우저 화면 확인으로 보고하지 않는다. Ego50은 배포 전118건 읽기 수락 후 소실됐다. 새 공간/다른 사용자 또는 다른 에이전트 공간으로 우회하지 않았으며 배포 후 인증 GUI/실제 업로드/실기기 확인은 미실행이다.
- 근거: `.local-archive/cleanup-count-20261105/`의 baseline/candidate/compare·windows-final·review/deploy-evidence·protection-before/after·impact-auth-smoke·runtime-acceptance·checkpoint, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-94ccd9b334220bc14b11b1c50decd7f13606fa92.json`. 운영 원본/금융/분류/여행/Google 업무 쓰기·삭제·마이그레이션0. 문서 후속만으로 재검사·재배포·서버 재시작하지 않는다.

## 2026-11-04 다중 파일 접수·백그라운드 분류 UX

- [PR #627](https://github.com/6Soo/cost/pull/627) 정상 병합·운영 `804eac6023ddcddb90c7959b66fce970bb656ef2`, 이전 검증 `96b978bfe7f161ccd9c9de090fd635c4b85a6a51`. 전체 파일의 원본 검증·저장·durable queue 등록을 먼저 완료하고 분류를 시작한다. 접수 직후 이동 가능 안내·버튼 활성·복귀 시 병렬 상태 복구를 제공한다. 단일 파일 API·개별20MiB·중복/환불/수동/원본/owner/CSRF 보호·금융 쓰기 직렬화는 유지한다.
- Windows 영향 QA 498건 통과·skip0·필수 브라우저 누락0. 최초 baseline 실패2건은 사용자 승인 후 테스트 계약을 고쳐 red→green 확인. PR CI 41771130622 성공, 검사본/병합본 운영 코드 동일(문서 차이 검토). 합성 ego12개 접수→다른 페이지→복귀12개 상태 복구·활성 버튼·가로넘침0 PASS.
- 공식 `deploy_verified_release.ps1` 단일 작성자 전환, gateway8790→backend8752. 1326 tracked blobs 불일치0·task/process 고정SHA·단일listener·health/ready200·보호API401·보호13표 내용/스키마 불변. 이전 검증 릴리스/task XML 복구점 보존, 코드 전용으로 전체 자료 백업/복원·마이그레이션·업무 재처리를 반복하지 않았다.
- 첫 전환 시도는 active 요청1건의 DRAIN_TIMEOUT으로 안전 중단·기존96b978bf/route 복구·health200·보호13표 불변을 확인했다. 검증용 ego 화면을 about:blank로 옮겨 자동 조회를 멈춘 뒤 active0을 확인하고 같은 공식 drain 게이트로 재시도했다. 최초 실패를 성공으로 처리하거나 요청을 강제 종료하지 않았다. 상세 `failed-deploy.json`과 최종 `deploy-evidence.json`을 구분한다.
- 인증 운영 업로드 화면에서 새 접수 후 이동 안내·multiple 파일 선택·일괄 접수 endpoint 코드·활성 버튼·가로 넘침0을 읽기 수락했다. 새 endpoint 익명 GET401도 확인했다. TaskSpace49 종료. 결과 `.local-archive/upload-background-20261104/live-result.json`. 실제 고객 업로드·금융/여행/Google/원본/스키마 업무 쓰기0. 실제 업로드 성능·전체 회귀·실기기는 미검증이다.
- 근거 `.local-archive/upload-background-20261104/`의 final-impact/·auth-fixed.xml·baseline-failures.xml·baseline-order-full.xml·browser-resumed.png·review/release-audit/deploy-evidence·protection-before/after·live-result.json 및 호스트 동일SHA deploy evidence. 요청 미결0·다음 명령 없음. 기존 사용자 변경을 보존하며 문서 후속 재배포/재시작 없음.

## 2026-11-04 항공권 누락·모바일 정보 밀도 개선

- COMPLETE — [PR #626](https://github.com/6Soo/cost/pull/626), 구현 `f86acff6`·복수 예약 보호 `e31d392b`, 운영 `96b978bfe7f161ccd9c9de090fd635c4b85a6a51`. 이전 검증 `f680e7e0b8b6ce6d98cdc30949fa0e2e6d63f99f`. [요청별 실행 범위](specs/flight-coverage-mobile-density-20261104.md).
- 요청1: 보관3,499메일(최신 수신일2026-11-04)을 읽기 대조했다. 시즈오카는 기존 Trip3예약·이름4명분에 제주1예약이 추가돼 4예약·5이름 표기다. 전원을 고유인원 또는 유효 항공권으로 확정하지 않는다. 취소/충돌 표시가 있는 예약1건을 포함하며 운영 화면의 기존 경고2개를 유지했다. 조회용 투영만 확장하고 금융 Trip 색인/기존 소스 digest 연결을 보존한다. 인증된 여정만 포함하고 예약자 인사·위장 도메인·복수 예약번호의 모호한 노선은 제외한다. 추가 복수예약 회귀는 red 재현 후 coverage8 passed로 교정했다.
- 요청2: Google Flights 실제 검색 목록과 Xero 공식 지출 기능·모바일 앱 예시를 직접 탐색했다. 실제 Xero 고객 장부 사용으로 보고하지 않으며 Zoho 데모는 DNS 실패로 채택하지 않았다. 여정 시간·도시·공항을 같은 행에 모으고 동반 탑승객을 목록에 표시했다. 합성4폭×두테마 밀도 근거와390px 왕복 하단537.4px를 보존한다. 재개 후 실제 테마 버튼으로 라이트/다크 배경 차이와 배치를 확인하고 라이트 스크린샷도 육안 검토했다.
- 요청3: 카드100행의 자동 아이콘/전용 버튼 충돌·최소44px, 모바일 기간/카드 필터 같은 행 배치, 상단과 동일한 제목만 숨김, 지출0건 필터·반복 집계·무관 OTA 문구와 개별 중첩 틀을 정리했다. 운영390px `/board`, `/import`, `/cards/all`, `/ota`, `/receipts`, `/trips`, `/flight-passengers`에서 넘침/장식오류/중복제목/작은 카드버튼/불필요0필터0 및 필터 같은 행을 수락했다. 최초 재개 브라우저 검사는 viewport 재설정 누락으로 desktop에서 대기 실패했으며 새 실행에서390px를 명시해 교정했다. 제품 실패나 통과로 혼동하지 않는다.
- 검증: Windows 영향 QA590 passed·62 subtests·skip0·필수 브라우저 누락0, CI41769141167 success. 검사SHA `e31d392b2265b15abb3651003b501e75f55d50b5`와 병합 tree 동일. 중단된 이전 QA는 근거에서 제외했다. 운영 검색 `예약 4건`·2명 그룹1개·기존 경고/닫힌 결제 상세 유지, 실제 두 테마 배경 차이와 summary 배치 통과.
- 배포: 1,325 Git blobs 일치·task/process 고정SHA·loopback listener1·health/ready200·보호API401·영향4경로401·보호13표 내용/스키마 전후 동일. 코드 전용 전환으로 이전 검증 릴리스/task 복구점을 보존했고 새 전체DB 백업/복원은 반복하지 않았다. 금융/원본/분류/여행/Google 업무 쓰기·마이그레이션0. 파생 조회 캐시만 갱신한다. 실기기·모든 상태 조합·전체 계정 추가수집은 미실행이다.
- 근거: `.local-archive/flight-coverage-20261104/`의 coverage-summary/collection-scope·windows-final·review/deploy-evidence·protection-before/after·impact-auth-smoke·live-search-acceptance/live-path-acceptance. 호스트 `D:/WebLedgerHost/releases/deploy-evidence-96b978bfe7f161ccd9c9de090fd635c4b85a6a51.json`. Ego47 정상 종료, 소유8876 합성 서버는 commandline 확인 후 종료. 문서 후속만으로 재배포·재시작하지 않는다.

## 2026-11-04 FUKUTAKE·항공권 정보 우선순위/버튼 수정

- [PR #624](https://github.com/6Soo/cost/pull/624) 운영 `f680e7e0b8b6ce6d98cdc30949fa0e2e6d63f99f`, 이전 검증 `8ce17a9a6d37ef4959b34811a3e5fa9469594f88`. [요구사항 F1~F3](specs/expense-flight-priority-fix-20261104.md)를 구현했다. FUKUTAKE 입장료 규칙은 자동 현지경비보다 우선하고 환불 대기는 실제 연결/승인번호/금액통화날짜 후보로 좁힌다. 모호 후보·원본 오류·수동 결정을 보호한다.
- 항공권 결과는 행선지·여행 날짜·탑승객을 먼저 보여주고 여정을 펼친다. 중복 예약번호/hero·상시 안내/장문 집계를 제거하고 예약/결제 도구는 닫힌 상세로 이동했다. 오염된 도시/날짜 문장은 조회 DTO에서 배제해 공항 코드로 대체하고 원문·충돌/취소 경고를 유지한다. 버튼 깨짐은 페이지 block 스타일과 공통 자동 아이콘/chevron 충돌이 원인이며 해당 disclosure가 flex·단일 화살표를 소유하도록 수정했다.
- 최종 검사 `52c0fd60b6951bcd87ef20624af367831a834b53`와 병합 tree 동일. Windows 영향 QA573 passed·32 subtests·skip0·필수 브라우저 누락0, PR CI41764424619 success. 기존 항목 교정/수동 보존·실제 환불/모호 후보/원본 오류 보호·오염 문장/긴 이름/키보드/정보 순서/버튼 computed style 회귀를 포함한다.
- 공식 단일 작성자 배포: 1,321 blobs 불일치0·런타임SHA 일치·listener1·health/ready200·보호API401·보호13표 내용/스키마 전후 불변. gateway8790→backend8752. 이전 검증 릴리스/작업 복구 수단 유지. 실제 항목 일괄 재분류·금융/원본/Google 업무 쓰기·마이그레이션 없음.
- 합성4폭×두테마8조건 넘침/summary배치오류0 및 실제390px 이미지 육안 확인. 운영 인증 시즈오카3건·오염 문장0·메타 기본닫힘·중복hero0·첫 여정 상단458.4px, 상세 펼친390/1440px 배치/넘침오류0. 지출 정리 화면 FUKUTAKE4건 확인(기존 불필요14건 제외·실제환불4건 보호). 실기기·모든 자료 조합은 미검증. Ego46 및 소유 합성8876 서버 종료.
- 근거 `C:/AX/cost/.local-archive/fukutake-check-20261104/`의 windows-final/·final-layout.json·final-mobile.png·live-flight.json·live-details-expenses.json·review.json·deploy-evidence.json, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-f680e7e0b8b6ce6d98cdc30949fa0e2e6d63f99f.json`. 문서 후속으로 재배포하지 않는다.

## 2026-11-04 항공권 날짜·행선지 검색

- [PR #622](https://github.com/6Soo/cost/pull/622) 운영 `8ce17a9a6d37ef4959b34811a3e5fa9469594f88`, 이전 검증 `2663f08e9fd478adba52cba2218a5a528046aa81`. 항공권 단일 검색창에서 이름·도시·공항 코드·여정 기간 중 날짜를 조합한다. 날짜 미상은 예약일/카드일로 추정하지 않으며 충돌 자료는 명시 날짜만 검색한다. [상세 계약](specs/flight-route-date-search-20261104.md).
- 최종 검사 `10b92ca8bde80e263590aec22a2d177d7522049c`와 병합 tree 동일. Windows 영향 QA386 passed·16 subtests·skip0·필수 브라우저 누락0, PR CI41761912476 success. 이름 검색·페이지 넘김·검색조건별 커서·소유자/CSRF와 기존 금융 보호를 검사했다.
- 공식 단일 작성자 배포: 1,319 blobs 불일치0·런타임 SHA 일치·listener1·health/ready200·보호API401·보호13표 내용/스키마 전후 불변. gateway8790→backend8751. 이전 검증 릴리스와 작업 복구 수단 유지. 금융/원본/Google 업무 쓰기·마이그레이션·대량 재처리는 수행하지 않았다.
- 합성5검색 및 모바일 단일 입력/버튼·넘침0 확인. 운영 인증 읽기 `22일 시즈오카`3건·`fuk`8건 조회, 모바일390px 넘침0. 실기기·모든 예약 조합·실제 금융 저장은 미검증. Ego45 종료, 소유 합성 서버8876 종료.
- 근거 `C:/AX/cost/.local-archive/flight-route-search-20261104/`의 windows-final/·synthetic-browser.json·live-acceptance.json·review.json·deploy-evidence.json, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-8ce17a9a6d37ef4959b34811a3e5fa9469594f88.json`. 문서 후속만으로 재배포하지 않는다.

## 2026-11-04 핵심 기능 중심 UI 축소

- [PR #620](https://github.com/6Soo/cost/pull/620) 운영 `2663f08e9fd478adba52cba2218a5a528046aa81`, 이전 검증 `4758fe63386c10a3cf1f255e7448d3a21c55fdfe`. 제목 옆 전체 집계·상시 저장 시각·홈 중복 링크·카드 소개/중복 요약·항공권 반복 정보를 제거했다. 장부 추가 작업·여행 마감/상세 필터·지출 자료/규칙·OTA 진단은 접이식으로 옮기고 영수증은 자료가 있는 단계만 표시한다. [요구사항별 결과](specs/core-ui-reduction-20261104.md).
- 최종 검사 `1bd604ee11dd9d3bf5f4ad6510385ad37c381d64`와 병합 tree 동일. Windows 영향 QA 1,009 passed·121 subtests·skip 0·필수 브라우저 누락 0, PR CI 41711523569 성공. 새 접근 경로·키보드·딥링크·입력 보존·편집/복사와 기존 금융 보호를 검사했다. 기존 CSV 테스트 모드·누적 성능 측정의 기준 실패는 독립 추출본에서 재현하고 테스트 조건만 격리했다.
- 공식 단일 작성자 배포 1,316 blobs 불일치 0·런타임 SHA·listener 1·health/ready 200·보호 API 401·보호 13표 내용/스키마 전후 불변. gateway8790→backend8752. 코드 전용으로 이전 검증 릴리스와 작업 복구 수단을 유지했으며 금융/Google/원본 업무 쓰기·마이그레이션·대량 재처리는 실행하지 않았다.
- 운영 인증 PC 11경로에서 가로 넘침 0, 전체 집계 배지 제거, 마감·자료/규칙·OTA·PDF의 기본 접힘과 펼친 뒤 접근을 확인했다. 모바일 390px 6경로 가로 넘침 0·테마 버튼 각 1개. 합성 7화면×두 폭×두 테마 28조건과 마지막 영향8조건도 확인했다. 실제 마감/금융 저장·고객 파일 업로드·실기기·모든 데이터 상태 조합은 미검증이다. Ego44 종료, 소유 합성 서버8876 종료.
- 근거 `C:/AX/cost/.local-archive/core-ui-20261104/`의 windows-final/·acceptance-themes.json·final-affected.json·live-acceptance.json·live-mobile.json·review.json·deploy-evidence.json, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-2663f08e9fd478adba52cba2218a5a528046aa81.json`. 문서 후속만으로 재배포하지 않는다.

## 2026-11-04 넓은 화면 본문 중앙 정렬

- [PR #618](https://github.com/6Soo/cost/pull/618), 운영 `4758fe63386c10a3cf1f255e7448d3a21c55fdfe`, 이전 `7c0be270a6ef770973efd797be00a9922dbd9210`. 홈·여행 관리 등 공통 제목과 본문을 최대 1180px로 정렬하고 영수증의 바깥 폭 제한을 해제해 960px 본문을 중앙에 배치했다. 기존 홈의 지출 정리 강조 및 장부·항공권 등 기존 작업 폭을 유지한다.
- 검사 SHA `ea3567eb0adc8a6c8b8b2935ccdb2033b01dbed0`와 병합 트리 동일. Windows 영향 QA 208 passed·27 subtests·skip 0, PR CI 41703516776 성공. 합성 1920/390px 정렬·가로 넘침 검사 및 운영 읽기 PC 1920px 주요 7화면 가로 넘침 0. 실기기와 모든 화면 상태는 미검증.
- 공식 단일 작성자 배포 1,314 blobs 불일치 0·런타임 SHA·listener 1·health/ready 200·보호 API 401·보호 13표 전후 불변. 금융/Google/원본 업무 쓰기 없음. 근거 `C:/AX/cost/.local-archive/centered-layout-20261104/`, `D:/WebLedgerHost/releases/deploy-evidence-4758fe63386c10a3cf1f255e7448d3a21c55fdfe.json`.

## 2026-11-04 PC 여행·항공권 버튼과 아이콘 점검

- [PR #616](https://github.com/6Soo/cost/pull/616) 운영 `7c0be270a6ef770973efd797be00a9922dbd9210`, 이전 검증 `efaf49a319f25e4c40c9c18ae9b10d8c187fbb81`. 여행 관리 마감/해제 아이콘을 상태별 체크/복원으로 구분하고 항공권 메뉴에 비행기 아이콘을 적용했다. 폼·권한·상태 처리 변경 없음.
- 운영 PC 1440×900에서 여행 관리·여행 장부·항공권 화면 및 주요 펼침 상태를 점검했다. 합성 예약 조회·펼침, 합성 여행 마감→해제, 두 테마의 아이콘 및 가로 넘침을 확인했다. 표적 22 passed, Windows 영향 484 passed·46 subtests·skip 0, PR CI 41700622159 성공. 검사 SHA `ee5e34f4de67517f2e7861b710cda22a704ebdda`와 병합 tree 동일.
- 1,313 blobs 불일치 0·런타임 SHA·단일 listener·health/ready 200·보호 API 401·보호 13표 전후 동일. 배포 후 인증 PC에서 마감 체크와 항공권 비행기 아이콘 확인. 실제 마감·금융 쓰기와 모든 거래 상태 조합은 미검증. 근거 `C:/AX/cost-pr609/.local-archive/pc-buttons-20261104/`, `D:/WebLedgerHost/releases/deploy-evidence-7c0be270a6ef770973efd797be00a9922dbd9210.json`.

## 2026-11-04 카드 검토 모바일 터치 영역 개선

- [PR #614](https://github.com/6Soo/cost/pull/614) 병합·운영 `efaf49a319f25e4c40c9c18ae9b10d8c187fbb81`, 이전 검증 `fd7f7fb468486a5e006faa6202a56c277ca41ea2`. 카드 전체 내역의 모바일 처리 필요 링크를 높이 21px에서 44px로 늘렸다. 이동 대상과 금융 처리 동작은 유지한다.
- 합성 거래에서 변경 전 21px 재현, 변경 후 44px 및 정확한 거래 편집 화면 이동 통과. 320/390/1440px 합성 가로 넘침 0. Windows 영향 QA 121 passed·skip 0, 필수 브라우저 검사 3건 실행; GitHub Actions 41695541815 성공. 검사 SHA `fb78269aea3c3b86626e8dd12a0593da14a8961a`와 병합 tree 동일.
- 배포 파일 1,313개 불일치 0, 런타임 SHA·단일 listener 확인, health/ready 200, 보호 API 401, 보호 테이블 13개 전후 동일. 운영 인증 화면 390px에서 링크 높이 44px·가로 넘침 0. 실제 금융 쓰기와 실기기 검증은 미실행. 근거 `C:/AX/cost-pr609/.local-archive/card-review-touch-20261104/` 및 `D:/WebLedgerHost/releases/deploy-evidence-efaf49a319f25e4c40c9c18ae9b10d8c187fbb81.json`.

## 2026-11-04 항공권 조회 갱신 안내 반복 수정 배포

- 사용자 이미지 진단: `flight-search.log`의 첫 준비2026-11-03 15:46:45→15:47:29 UTC/44.39초. 첫 방문에서만 항공권 색인이 시작됐고 LOADING 응답마다 UI 안내가 다시 공지됐다. finally가 대기 중 버튼을 활성화해 재클릭 시60회 한도를 초기화했으며 검색마다 worker를 강제로 깨웠다. 이후 같은 이름의 운영 조회 예약2건 정상도 확인해 영구 갱신 실패로 단정하지 않았다.
- [PR #605](https://github.com/6Soo/cost/pull/605), 구현50b355ba·추가 회귀a2a19334, 병합/운영 `097d7dabe787816244ddf8df03eb759032f84672`. 서버 시작 시 기능 활성화된 항공권 색인 사전 준비·worker 정상 검사 간격·안정된 안내/대기 상태·120초/60회 자동 대기·15초 요청 제한을 적용했다. Windows 영향273 passed/16 subtests/skip0, 추가 응답 지연1·시작/진입점8 passed. PR CI41668924366 최종274 cases/skip0 PASS, 최종head와 병합tree 동일.
- 공식 `tools/deploy_verified_release.ps1`로 이전 검증 `46339830d9ab7e93be38529094d106b49c2a9036`에서 전환(2026-11-03 16:00:47 UTC). gateway8790→backend8752/paused=false, 1,312 Git blobs 일치·task/processSHA·단일backend listener·health/ready200·보호API3개401·보호13표 내용/스키마 전후불변 PASS. 이전 릴리스/task XML 복구점 보존. code-only로 전체DB백업/복원을 반복하지 않았다.
- 새 기동의 독립 색인 준비는 첫 브라우저 방문 전에 시작됐고 검증된 동일 입력 캐시로0.9초 완료. Ego34 인증 읽기에서 새 스크립트·동일 검색 예약2건·약1.391초·busy=false/버튼복구·가로넘침0 확인 후 공간 종료. 이는 재수집 원문 파싱 전체의 성능 보장이 아니다. 금융·여행·Google·원본·스키마 업무 쓰기/재처리 없음.
- 로컬 근거 `C:/AX/cost-deploy-qa-20261103/.local-archive/flight-refresh-20261104/`의 checkpoint/Windows 및 hosted QA XML/summary/release-audit/protection-before/after/deploy-evidence/live-flight-search JSON. 호스트 `D:/WebLedgerHost/releases/deploy-evidence-097d7dabe787816244ddf8df03eb759032f84672.json`. 이 요청 미결0. 후속 문서 병합으로 재배포·재시작하지 않는다.

## 2026-11-04 UI/UX 검토 개선 배포

- UR01~UR09 구현 [PR #602](https://github.com/6Soo/cost/pull/602) 병합 SHA `46339830d9ab7e93be38529094d106b49c2a9036`을 `d26b43e9cc9f66ef89d2385d163b67ef7f04bba4`에서 공식 절차로 전환했다 (2026-11-03 15:25:39 UTC). 모바일 메뉴 포커스, 영수증 입력, 지출 상태 집계, OTA 검색·진단, 모바일 밀도, 공통 헤더·타이포, 홈 집계 명칭을 개선했다.
- 테스트 SHA `5c76c29b9906bb9e16d599b12617c7fa4a0ed3a8`와 병합 tree 동일. Windows 영향 QA 836 passed·87 subtests·skip 0·필수 브라우저 누락 0, PR CI 41661493005 및 main CI 41662501155 성공.
- 릴리스 1,312 blob 불일치 0, 런타임 SHA 및 단일 listener 확인, health/ready 200, 보호 API 3개와 /board·/import·/receipts 비인증 401, 보호 13표 전후 불변. 금융 적용·Google 쓰기·마이그레이션 없음. 근거 `D:/WebLedgerHost/releases/deploy-evidence-46339830d9ab7e93be38529094d106b49c2a9036.json`, `C:/AX/cost/.local-archive/ux-review-20261103/`.
- 후속 수락: 합성 PDF 선택 취소와 서버 오류 뒤 재시도 상태 정상. OTA 검색은 운영 390×844에서 top 123.6px로 첫 화면에 위치. 동일 합성 카드 20건에서 마지막 행까지 휠 11→10회, scrollY 5192→4655px, 첫 행 top 552.5→425.3px. 지출·OTA·영수증·장부의 320/390/1440과 양 테마 24조건에서 제목·테마 버튼 표시 및 가로 넘침 없음을 확인했다. 지출 화면의 각 크기 캡처를 확인했고 실제 테마 전환 후 원래 테마로 복귀했다. 근거 `C:/AX/cost/.local-archive/ux-review-20261103/acceptance-01.mjs`~`acceptance-07.mjs`, `acceptance-matrix-actual.json`. 실기기 검증은 미실행이다.
## 2026-11-03 잔존 프로세스 복구 및 후속 main 고정 배포

- 사용자 “운영배포해”에 따라 `33bf47e7dbc3788a6eeb4082ad120d221c8cabc7`→`d26b43e9cc9f66ef89d2385d163b67ef7f04bba4` 공식 전환 완료(2026-11-03T14:49:37Z). PR582~600의 Google 표시·감독자 수명·OTA 커서/스냅샷 신선도·항공권 권위/취소 이력·지출 날짜 근거 등 병합된 후속 코드를 포함한다. Windows 최종 영향338 passed/4 subtests/skip0와 개별 변경 근거 및 main CI41636631694 success를 확인했다.
- 배포 전 후보8752/진입56069를 점유한 잔존713 릴리스 및33 중복 준비 감독자를 SHA·PID·생성시각·부모 관계·스크립트/역할/loopback 포트로 식별했다. 두 공식 배포 잠금과 gateway 요청/writer drain 아래 정리하고 기존 backend42372 유지·33 진입 서버 복구·health/ready200·보호13표 불변을 확인했다. 영수증 인식 임시 상태는 재시작 만료 계약이며 저장 원본과 장부를 보존한다. 임의 제3 포트나 신원 검사 우회는 사용하지 않았다.
- `C:/AX/cost-demo-sync-20261103/tools/deploy_verified_release.ps1 -CandidateSha d26b43e9cc9f66ef89d2385d163b67ef7f04bba4 -PreviousSha 33bf47e7dbc3788a6eeb4082ad120d221c8cabc7 -ReviewEvidence C:/AX/cost/.local-archive/deploy-resume-20261103/review.json -Apply` PASS. gateway8790→backend8752/paused=false, Board Running/고정SHA, Prepared 제거, 단일 loopback backend, entry56069 및 gateway8790 유지. 1,312 blobs 불일치0·health/ready200·보호API3개401·보호13표 내용/스키마 전후불변. 전환 중 표본196요청 실패0/최대7.099초이며 전 구간 무중단 보장과 구분한다.
- 이전 검증 릴리스/task XML 복구점 보존. 코드 전용으로 별도 전체DB백업·복원·마이그레이션·금융/여행 대량 재처리·Google 쓰기 없음. 직접 입력 유지 결정에 따라 새 모델 연결/거래 근거 전송 없음. 새 인증 브라우저·실제 금융 저장·전체 회귀는 이번 배포에서 반복하지 않았다.
- 근거 `C:/AX/cost/.local-archive/deploy-resume-20261103/` 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-d26b43e9cc9f66ef89d2385d163b67ef7f04bba4.json`, `continuous-switch-d26b43e9cc9f66ef89d2385d163b67ef7f04bba4.json`. 사용자 미추적 파일·기존 작업 공간 보존. 문서 후속 재배포/재시작 없음.

## 2026-11-03 항공권 여정 개편·예약 이용기간 교정·업로드 재시작 검증 운영 배포

- PR #574 (항공권 여정/탑승객 개편 `71340078`), PR #578 (예약 이용기간 교정 `cc9d31cb`), PR #576 (업로드 재시작 검증 `33bf47e7dbc3788a6eeb4082ad120d221c8cabc7`) 정상 병합 및 호스팅 CI 41598022768 성공.
- 공식 `deploy_verified_release.ps1 -CandidateSha 33bf47e7dbc3788a6eeb4082ad120d221c8cabc7 -PreviousSha 71340078bc66028704e9eddae813f517be3237f9 -ReviewEvidence C:/AX/cost/.local-archive/deploy-main-33bf47e7/review.json -Apply` 성공.
- 전환 결과: gateway8790→backend8751, 1,312 tracked blobs 불일치 0, runtime SHA 일치, 단일 loopback listener, health/ready 200, 보호 API 401, 보호 13표 불변 PASS (2026-11-03T07:54:39Z).
- 배포 중 업무 DB/Google/원본/스키마 쓰기 0. 코드 전용이며 이전 검증 릴리스 및 task XML 보존.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-33bf47e7dbc3788a6eeb4082ad120d221c8cabc7.json`, `continuous-switch-33bf47e7dbc3788a6eeb4082ad120d221c8cabc7.json`, `release-audit-33bf47e7dbc3788a6eeb4082ad120d221c8cabc7.json`.

## 2026-11-03 토요코인 수집 점검 및 예약 근거 추론 배포

- PR #575 정상 병합 `bcd4e5bf5fd4e51516f5a026f3c41308ad64e311`, PR CI 41594203986 및 main CI 성공. 검증 코드 검사 495 passed·13 subtests·skip0 및 표적 106 passed를 재사용하고 후속 문서만으로 검사를 반복하지 않았다.
- 공식 `deploy_verified_release.ps1 -CandidateSha bcd4e5bf5fd4e51516f5a026f3c41308ad64e311 -PreviousSha d57675a512f3c1446d0d3c9d3966114637640220 -ReviewEvidence C:/AX/cost/.local-archive/toyoko-audit-20261103/review.json -Apply` 성공. gateway8790→backend8751, 1,309 tracked blobs 불일치0·task/process SHA 일치·단일 loopback listener·health/ready 200·보호 API 401·보호 13표 불변 PASS(2026-11-03T07:20:15Z). 배포 중 업무 DB/Google/원본/스키마 쓰기 0.
- Google 수집 계정(kkokkohero6@gmail.com) Ego 재인증 완료 및 토큰 원자적 교정. `WebLedger-MailCollect` 예약 작업 수동 트리거 및 정상 완료(exit code 0, 100건 신규 수집). ego-browser 운영 UI 수락(`1002_영남` `tab=trip-86714d1ca408`)에서 창원 2행 '10월 2일(금) ~ 10월 4일(일) · 2박 · 예약 근거 추론' 표시 및 overflow: false 확인. 실제 결제 승격·금융 저장 없음.
- 근거 `C:/AX/cost/.local-archive/toyoko-audit-20261103/` (`deploy-evidence.json`, `reauth-audit.json`, `live-pc.json`, `actual-display.json`) 및 [명세](specs/toyoko-collection-audit-20261103.md) 참조.

## 2026-11-03 트립닷컴 날짜 중복·OTA 출처 문구 배포

- [PR #572](https://github.com/6Soo/cost/pull/572), 구현 `dbb7487c`, 비교 검사 기준 교정 `3c661999`, 병합 `2c0616a27470e73c66b568cae80b639a95f0e1fd`를 포함한 합동 `d57675a512f3c1446d0d3c9d3966114637640220` 배포 완료(07:15:21Z). 동일 숙박기간의 설명 중복만 숨기고 OTA 코드 추론 출처를 표시한다. 미상·오류·다른 기간/메모/원본/예약번호/AI 추론 표시는 보존한다.
- 정확2c061 Windows 영향 QA478 passed·43 subtests·skip0, PR CI41592175031/main CI41592668337 성공. 근거 `.local-archive/expense-date-inference-20261103/final-windows-quality/`의 run-summary/JUnit/pytest.log 및 ci/ 원본. 초기 dbb QA의 과거 비교 기준2실패와 최종 통과를 구별한다.
- 공식 단일 작성자650fe1e1이 `044b535c`→`d57675a5` 전환. `D:/WebLedgerHost/releases/deploy-evidence-d57675a512f3c1446d0d3c9d3966114637640220.json`: 1308 tracked blobs 불일치0, runtime SHA 확인, backend8752, listener1, health/ready200, 보호API3개401, 보호13표 내용/스키마 불변. 코드 전용이며 금융/Google/원본/여행 쓰기·스키마/대량 재처리 없음. 기존 검증 릴리스/작업 복구 수단을 유지하며 전체DB백업을 반복하지 않았다.
- 첫 인증 운영 board의 main·43행·`코드 추론`4건 확인. 추가 여행 이동과 동일공간 reload/p2는 browser timeout으로 미완료다. 운영 날짜 전후 비교·세 여행 전체 검증 완료를 주장하지 않는다. 브라우저 오류 상태 Ego17을 보존했으며 추가 읽기 수락만 남았다. 문서 후속만으로 코드 테스트·재배포·서버 재시작하지 않는다.

## 2026-11-03 제주항공 OTA·카드 제한 배포

- PR #566 정상 병합 `f1b1ff63b5eaefcbea914808f3022ec6044e3a1e`, PR CI41578660810·main CI41579009582 성공. 원래 코드 검사573 passed·34 subtests·skip0를 재사용하고 후속 문서만으로 코드 검사를 반복하지 않았다.
- 공식 `deploy_verified_release.ps1 -CandidateSha f1b1ff63b5eaefcbea914808f3022ec6044e3a1e -PreviousSha 35ec72b8cb0fe5547dfd80cef01772f6ab2b7e3b -ReviewEvidence C:/AX/cost/.local-archive/jeju-resume-20261103/review.json -Apply` 성공. 두 공식 배포 잠금·기존 창 없는 래퍼 보존, 준비 후보 ready 후 drain/전환, gateway8790→backend8752. 1,307 tracked blobs 불일치0·task/processSHA·단일loopback listener·health/ready200·보호API3개401·보호13표 불변 PASS(2026-11-03T06:19:02Z).
- 코드 전용으로 이전 검증 릴리스/task XML을 보존했으며 새 전체 자료 백업·복원·마이그레이션·데이터 교정·원문 적재·Google 쓰기를 반복하지 않았다. 기존 안전 게이트를 통과한 원문2건 적재·여행62건 교정 요약을 확인했고 운영DB 읽기에서 제주4813 3건·타카드0을 재확인했다. 사용자 승인으로 기존 소실 Ego9 대신 Ego13에서 읽기 수락했다. 카드 대사421.1초·generation663 및 색인 갱신 완료 후 제주항공 예약1행·중복 없는 카드2건(311,600원/85,600원)·0806 여행 배정·제주 지출3건 PASS, Ego13 종료. 실제 환급·사용자 수동 확정·Google 반영 완료로 해석하지 않는다.
- 근거 `C:/AX/cost/.local-archive/jeju-resume-20261103/`와 호스트 `D:/WebLedgerHost/releases/deploy-evidence-f1b1ff63b5eaefcbea914808f3022ec6044e3a1e.json`. [실행 기록](specs/jeju-ota-card-scope-20261103.md) 참조.

## 2026-11-03 게이트웨이·보험 순차 고정 SHA 배포

- 사용자 “배포해”에 따라 `a9b0617a`→`ac2eed16`→`6d7c4f59`→`e75f0b96`를 공식 `deploy_verified_release.ps1`으로 직렬 전환했다. 이 범위의 마지막 SHA `e75f0b9699bd87fe951ea307712258db974a8677`, route8752/paused=false, gate PASS. 게이트웨이 설치와 선행 지출 인라인/일괄 편집·영수증 PDF/영역 검토 및 보험 두 글자 이름/후보 보기 코드의 운영 반영 근거다. 이후 별도 여행 마감 PR #561 담당자가 e75→`35ec72b8cb0fe5547dfd80cef01772f6ab2b7e3b`/8751로 전환한 호스트 deploy-evidence PASS(04:22:40Z)를 관측했으며 최신 런타임을 보존한다.
- 기존 설치기의 주석 URL 중복 오인은 [PR #563](https://github.com/6Soo/cost/pull/563)으로 실제 `service:` 행만 검사하도록 수정했다. 3개 회귀 검사와 영향65 passed/skip0, CI41576154132 성공. 검증 후보 `43b7492c`에 이 수정만 포함한 `ac2eed1635bd8b807abdee2e6dbcd382ef969225` 1,304blobs 불일치0. 누적 QA1,175+96/skip0 근거를 재사용했다. 설치된 gateway/route를 후속 배포가 재사용하므로 후속 구버전 설치기는 재실행하지 않았다.
- 543f7490·5d342163 사용량 오류로 배포를 시작하지 못해 successor36e9f713가 준비된 review/검사 근거를 인수했다. 두 글자 이름 [PR #559](https://github.com/6Soo/cost/pull/559) Windows/CI465+16/skip0 및 mainCI41573831949, 후보 보기 [PR #560](https://github.com/6Soo/cost/pull/560) Windows/CI361+25/skip0 및 mainCI41574755063 성공을 확인했다. 각 단계 별도 보호 baseline/사후 비교를 통과했고 보호13표 내용·스키마가 동일했다.
- 각 SHA1304blobs 일치·task/process SHA·단일loopback listener·health/ready200·보호API401. Board/Gateway/SourceRefresh Running, Prepared 제거. 선행 재개 전환 모니터508요청 실패0/최대6.973초. 공개health/ready200, 영향 `/board`·`/import`·`/receipts`·`/flight-passengers` 익명401. 재전송·실제 고객 업로드·금융/Google/원본/스키마 업무 쓰기·마이그레이션·대량 재처리 없음. 이전 검증 릴리스/task XML 보존, 코드 배포에 전체DB백업/복원을 반복하지 않았다.
- 후속 두 전환의 loopback8790 연속 health/ready874요청 실패0/최대9.393초. 샘플 범위는 `.local-archive/deploy-main-20261103/followup-continuity.json`이며 선행508요청과 별도다. 지연시간을 무지연 보장으로 표현하지 않는다.
- 기존 Ego6의 최종 API 읽기에서200·규칙v3-two-character·대상1명 name_match/자동 이름 연결1개, 수입13행 digest 동일/대상 날짜·금액 보존을 확인했다. `/board`·`/import`·`/receipts`·`/flight-passengers` 인증main/가로넘침0/암호화면없음, 글자 일치 없음 후보 모달9명 표시·닫기PASS. 연결된 수입행 상세를 열어 자동 이름 연결 문구/넘침0까지 확인했다. `.local-archive/insurance-two-character-20261103/acceptance-after.json`·`acceptance-ui.json`·`acceptance-ui-final.json`에 원문 없는 결과 보존, Ego6 finish완료. 자동 대조를 사용자 확인이나 보험 가입/환급 완료로 해석하지 않는다.
- 별도 창 억제 승인 담당992b3fe4가 배포 후 잠금을 인수해 Gateway task Execute만 pythonw로 변경했다. 인수/작업 디렉터리와 XML Principal/Triggers/Settings 보존·현재PID29480 유지·재시작0·health/ready200. 근거 `.local-archive/gateway-console-20261103/applied.json`·변경 전후XML. Board/SourceRefresh는 다음 담당1f27f10c에게 직렬 인계했다.
- Board/SourceRefresh 창 억제 등록도 완료했다. 중간 `cost-windowless-result.json`은 Board 내부 실행 경로 오류로 폐기됐으며, 정확한 PowerShell 단일 경로 교정 후 `C:/AX/pc-manager/ops/startup-console-fix-20261103/board-repair-result.json` PASS가 이를 대체한다. 두 작업 원본 인수·작업 디렉터리·XML 설정과 내부 실행파일 존재를 검증했고 route/프로세스 보존·재시작0. 최종 `.local-archive/deploy-main-20261103/final-windowless-checkpoint.json`(04:32:49Z)은 운영35ec72b8/8751, gateway8790/backend8751 health/ready200, 보호API3개401, 배포lock FREE를 기록한다. PowerShell의 미지원 옵션으로 실패한 보호API 검사는 제외하고 curl.exe의 AUTH_REQUIRED 응답으로 교정했다. 다음 예약 시작 설정을 확인했으며 재부팅·새 래퍼 프로세스 기동 검증은 실행하지 않았다.
- 호스트 근거: `D:/WebLedgerHost/releases/deploy-evidence-ac2eed1635bd8b807abdee2e6dbcd382ef969225.json`, `deploy-evidence-6d7c4f59834fa2f245d759ede54dba554e0741d3.json`, `deploy-evidence-e75f0b9699bd87fe951ea307712258db974a8677.json` 및 같은 SHA의 `continuous-switch-*.json`. 로컬 `.local-archive/deploy-main-20261103/`·`.local-archive/insurance-two-character-20261103/`·`.local-archive/insurance-no-match-20261103/`에 review·보호 비교·연속 요청 근거 보존. 기존 Ego4 없음으로 인증 화면 수락은 보험 담당자의 기존 Ego6 읽기 수락과 구분한다. 전체 회귀·실기기·실제 금융 저장을 실행한 것으로 표현하지 않는다.

## 2026-11-02 연속 배포 구현 병합·운영 전환 정책 차단

- 요청: 개발·배포 중 운영 502 해결을 “적용해”. [PR #547](https://github.com/6Soo/cost/pull/547), 병합 SHA `6207dd3092c40adb5f0ce0fafb687f0141c916c2`; 검사 `7afec0f1`와 동일 트리. 게이트웨이 8790→8751/8752, 후보 readiness/인증 보호 선검사, 요청 drain과 대기, 금융 요청 재전송 금지, 카드 자동 완료·여행 내부 동기화의 역할/프로세스 잠금, 실패 시 기존 서버 유지/복구를 구현했다.
- 실제 검증: `python tools/run_quality_checks.py --base origin/main --run` 257 passed·skip 0. 포함된 게이트웨이/실제 PowerShell 스크립트 합성 검사 10 passed는 정상 인계·준비 실패·drain 실패·인계 실패 복구를 확인한다. 과거 호스트 검사 실패 1건은 현재 커밋 재검사 1 passed. 호스팅 PR CI [41439813479](https://github.com/6Soo/cost/actions/runs/41439813479), main CI [41440047572](https://github.com/6Soo/cost/actions/runs/41440047572) 성공. 전체 회귀·인증 브라우저는 배포 제어 범위에 추가하지 않았다.
- 로컬 고정 릴리스 `D:/WebLedgerHost/releases/6207dd3092c40adb5f0ce0fafb687f0141c916c2`의 1,300 tracked blobs를 Git SHA-1과 대조해 불일치 0. 이전 검증 릴리스 보존, 보호 13표 사전 aggregate snapshot PASS. 고객 행·비밀값은 보고하지 않았다. 코드 전용이며 새 전체 DB 백업·복원·마이그레이션·업무 재처리를 하지 않았다.
- `DEPLOY_BLOCKED_TOOL_POLICY`: 공개 health/ready 읽기 모니터 시작과 `tools/install_ledger_gateway.ps1 -Apply`를 포함한 셸 호출이 `CreateProcess ... Rejected ... blocked by policy`로 거부됐다. 구체적 사유는 반환되지 않았다. 해당 프로세스가 시작되지 않았으므로 설치/터널/작업 변경은 미실행이며 다른 경로로 재시도하지 않았다. 이후 읽기 확인: 기존 운영 SHA `a9b0617a132be8ea83328a8ac6a9345514efeffc`의 Board task Running, 후보 SHA 미설정, route 파일 없음, loopback 8751 health/ready 각각 200. 전환 연속 요청·후보 runtime·배포 후 보호 13표 비교는 미실행이다.
- 차단 해소 후 다음 순서: 실제 운영 SHA/작업·단일 작성자 재확인 → 보호 사전 snapshot 갱신 → 위 고정 릴리스의 `tools/install_ledger_gateway.ps1 -Apply` → 새 터널 ready와 기존 연결 정리 확인 → `tools/deploy_verified_release.ps1 -CandidateSha 6207dd3092c40adb5f0ce0fafb687f0141c916c2 -PreviousSha <재확인한 운영 SHA> -ReviewEvidence C:/AX/cost/.local-archive/continuous-deploy-20261102/review.json -Apply` → 연속 요청·health/ready·보호 API·13표 불변·gateway/Board task 및 프로세스 SHA 확인. 정책 거부가 유지되는 동안 이 명령을 우회 실행하지 않는다.
- 증거: `.local-archive/continuous-deploy-20261102/`의 `checkpoint.json`, `impact-summary.json`, `impact.xml`, `switch-contract.xml`, `host-recheck.xml`, `review.json`, `protection-before.json`; 호스트 `release-audit-6207dd3092c40adb5f0ce0fafb687f0141c916c2.json`. 완료 상태는 구현·검증·병합만이며 운영 적용은 BLOCKED다. 단일 Windows 호스트·게이트웨이 자체 장애까지 무중단을 보장하지 않는다.

## 2026-11-02 항공권 운영 화면 후속 확인

- 사용자 지시에 따라 새 ego-browser 작업 공간에서 운영 `/flight-passengers`의 인증 화면·검색 입력을 확인했다. 합성 영문 이름 조회는 예약 없음으로 응답했고 입력 유지·가로 넘침 없음을 확인했다. 실제 예약 결과의 새 탭 클릭은 수행하지 않았으며 해당 동작은 PR #536 합성 브라우저 검사로 확인했다. 고객 금융·Google 장부 쓰기 없음. 로컬 근거 `.local-archive/autonomous-qa-20261102/flight-live-resume-valid.mjs`, `flight-live-resume-status.mjs`.

## 2026-11-02 카드 업로드 대기 개선 배포

- [PR #541](https://github.com/6Soo/cost/pull/541), 운영 `828e56db310e41fab864410e2dacb7049ed503a3`, 이전 검증 릴리스 `d878234c2ca90ab6c1362f7a007f284060562e88`. 영향 QA 207 passed·30 subtests 및 GitHub Actions 41431463759 통과.
- 1,293개 파일 해시 일치, health/ready 200, 보호 API 401/403, 보호 테이블 13개 전후 불변. 인증 운영 업로드 화면 읽기 확인. 실제 업로드와 성능 개선율은 미측정이며 서버 처리에는 공유 잠금이 유지된다. 근거 `.local-archive/autonomous-qa-20261102/upload-speed-release/deploy-evidence.json`.

## 2026-11-02 항공권 검색 결과 유지 배포

- [PR #536](https://github.com/6Soo/cost/pull/536), 코드 `4303ca66`, 운영 `d878234c2ca90ab6c1362f7a007f284060562e88`. 카드 원행을 안내와 함께 새 탭에서 열어 검색 결과를 유지한다. 이름이나 예약 정보를 URL·브라우저 저장소에 새로 기록하지 않는다.
- 합성 항공 검색 12 passed, 영향 QA 260 passed·16 subtests·skip 0, GitHub Actions 41423166983 통과. 운영 1,293 blobs 일치, health/ready 200, 보호 API 401/403, 보호 13표 전후 불변. 직전 `38d31b89a202d0b7da30bb1bf08f0bd2340b6c2a` 보존. 배포 당시 기존 TaskSpace 63을 찾지 못했으며 후속 운영 화면 확인은 위에 기록했다. 실제 금융·Google 쓰기 없음. 근거 `.local-archive/autonomous-qa-20261102/flight-detail-release/deploy-evidence.json`.

## 2026-11-02 카드 자료 전환 상태 보호 배포

- [PR #528](https://github.com/6Soo/cost/pull/528), 검증 코드 `ec92540c`, 운영 `38d31b89a202d0b7da30bb1bf08f0bd2340b6c2a`. 업로드 중 다른 자료를 선택하면 이전 응답이 현재 상태를 덮지 않도록 고쳤고 파일별 결과는 보존했다. 카드 복사 검사를 현행 경로로 복구했다.
- 카드 복사 모듈 21 passed·4 subtests; 영향 QA 227 passed·34 subtests·skip 0, GitHub Actions 41413669138 통과. 운영 1,292 blobs 일치, health/ready 200, 보호 API 401/403, 보호 13표 전후 불변. 직전 릴리스 `58557f389bde6e67d59f7de3041e0d96b9fd6942` 보존. 인증 운영 카드 자료 화면에서 두 탭·버튼과 가로 넘침 없음을 읽기 전용 확인했다. 실제 업로드·금융·Google 쓰기는 하지 않았다. 근거 `.local-archive/autonomous-qa-20261102/card-copy-release/deploy-evidence.json`, `card-copy-live-new.mjs`.

## 2026-11-02 여행 정보 입력 라벨 배포

- [PR #524](https://github.com/6Soo/cost/pull/524), 코드 `51805911b6997a3eb58849d22b04b29b92043ad6`, 운영 `58557f389bde6e67d59f7de3041e0d96b9fd6942`. 여행 관리의 표시 이름·작성일·담당자 입력을 각 라벨에 연결했다. [PR #523](https://github.com/6Soo/cost/pull/523)은 합성 브라우저의 여행 정보 충돌·입력 보존 검사를 추가했다.
- 영향 QA 423 passed·35 subtests, skip 0; GitHub Actions 41408383202 통과. 운영 1,292 blobs 일치, health/ready 200, 보호 API 401/403, 보호 13표 전후 불변. 직전 `82d818fcb86d1059db1413749f54f042a239a87f` 보존. 인증 운영 화면에서 67개 여행의 세 입력 모두 라벨 0/67→67/67, ID 유일·가로 넘침 없음 확인. 근거 `.local-archive/autonomous-qa-20261102/trip-labels-release/deploy-evidence.json`, `trip-labels-before.mjs`, `trip-labels-after.mjs`.

## 2026-11-02 영수증·예약 연결 본문 접근성 배포

- [PR #521](https://github.com/6Soo/cost/pull/521), 코드 `48a607ef86c3c4f0b670acc313d3dfb98cf592a4`, 운영 `82d818fcb86d1059db1413749f54f042a239a87f`. 두 화면의 제목과 업무 영역에 본문 랜드마크를 추가했다.
- 영향 QA 189 passed·15 subtests, skip 0; GitHub Actions 41405062332 통과. 운영 1,292 blobs 일치, health/ready 200, 보호 API 401/403, 보호 13표 전후 불변. 이전 릴리스 `73eae23873323a7ffdd9f3bbe19dbf148ba5b4e4` 보존. 인증 운영 두 화면에서 랜드마크·제목·업무 영역과 가로 넘침 없음을 읽기 전용 확인했다. 근거 `.local-archive/autonomous-qa-20261102/landmarks-release/deploy-evidence.json`, `landmarks-live.mjs`.

## 2026-11-02 저장 파일 상세 이동 배포

- [PR #516](https://github.com/6Soo/cost/pull/516), 검증 코드 `1bf142bd0b6c0cc07ae70ecf2b14679ee0e675e6`, 배포 `41c66b8b7e17b150391ad7898aed09956a472120`. 상세 결과를 페이지 새로고침 없이 불러오고 후속 처리 오류 안내를 명확히 했다.
- 영향 QA 230 passed·30 subtests, skip 0, GitHub Actions 41399400683 통과. 배포 파일 1,292개 일치, health/ready 200, 보호 API 및 보호 13표 불변. 이전 검증 릴리스 `20da556e174c66570a856324c770e05ad422aa69` 보존. 근거 `.local-archive/upload-detail-20261102/deploy-evidence.json`. 운영 인증 화면 수동 확인 미실행.

## 2026-11-02 능동 QA·다중 업로드 배포

- [PR #513](https://github.com/6Soo/cost/pull/513), [PR #514](https://github.com/6Soo/cost/pull/514)를 검증 후 병합하고 `20da556e174c66570a856324c770e05ad422aa69`를 고정 배포했다. 이전 검증 릴리스 `a7aa8c7ff23af9574ccbf42301803687b788d64d`와 task 복구점을 유지했다.
- #513 PR 검사 825 passed/86 subtests, 정기 감사 704 passed/86 subtests; #514 영향 검사 280 passed/30 subtests, 필수 skip·누락 0. PR 검사 트리와 병합 트리 동일. 실행 간 중복은 합산하지 않는다.
- 배포 검사 1,292 blobs 불일치 0, task/process SHA 및 단일 loopback 확인, health/ready 200, 보호 API 401/403, 보호 13표 내용·스키마 전후 불변. 실제 금융·분류·여행·Google·원본·스키마 업무 쓰기 0. 자세한 증거 `.local-archive/autonomous-qa-20261102/deploy-evidence.json`.
- 인증된 운영 브라우저 재수락은 기존 TaskSpace 21을 찾지 못해 미실행이다. 합성 브라우저와 Windows OCR의 기존 증거는 이 운영 화면 수락을 대신하지 않는다. 문서 변경에 따른 재배포는 하지 않는다.

## 2026-11-03 두 글자 보험 이름 자동 연결 운영 확인

- [PR #559](https://github.com/6Soo/cost/pull/559) 병합 `6d7c4f59834fa2f245d759ede54dba554e0741d3`를 V124 단일 작성자가 검증된 `ac2eed16`에서 배포하고 후속 PR #560의 `e75f0b9699bd87fe951ea307712258db974a8677`까지 직렬 전환했다. 두 배포 모두 1,304 blobs 불일치 0·runtime SHA·health/ready 200·보호 API 401·보호 13표 불변 PASS, 해당 배포 완료 시 route 8752/paused false다. 기존 릴리스/task XML 복구점 유지, 코드 전용으로 전체 DB 백업·복원을 반복하지 않았다. 이후 별도 PR #561의 운영 전환과 구분하며 아래 수락은 e75 기준이다.
- 기존 ego TaskSpace 6에서 실제 대상의 자동 연결 0→1, `name_match`/`masked_name_match`, 기존 수입 날짜·금액 보존을 읽기 확인했다. 실제 수입 행의 `1명 연결`을 펼쳐 `자동 · 이름 글자 일치` 근거·가로 넘침 0을 확인하고 작업 공간을 정상 종료했다. 후속 배포 전후 수입 13행 digest 동일. Windows와 CI 각각 영향 QA 465 passed·16 subtests·skip 0 근거를 재사용했다. 실제 금융/Google/원본/수동 연결 쓰기·대량 재처리는 없다.
- 근거: `.local-archive/insurance-two-character-20261103/acceptance-after.json`과 같은 폴더의 checkpoint/review/windows-qa/ci, 호스트 `D:/WebLedgerHost/releases/deploy-evidence-6d7c4f59834fa2f245d759ede54dba554e0741d3.json` 및 `deploy-evidence-e75f0b9699bd87fe951ea307712258db974a8677.json`. 문서 후속만으로 코드 검사·재배포·재시작하지 않는다.

## 2026-11-02 보험 연결 표시 간소화·미연결 연결 버튼 완료

- COMPLETE — 사용자 “일단 연결이 되면 크게 수정할 필요가 없는 부분이야. 버튼이 도드라지지않고 자연스럽게 글자위주로 변경하고, 미연결 부분을 버튼으로 만들어서 기능을 추가해.” [PR #505](https://github.com/6Soo/cost/pull/505), 구현 `447ebb16c4b97cdf8c865be1de7db7003a3466fc`, 병합·고정 배포 `c0d45b46b10726ea9ce660ba92c62f79e3e998f5`, 이전 검증 `ec2a37ab4c2b9a6d9e41a23de64e2b09869d0870`.
- 연결된 보험은 보조색 글자·작은 펼침 화살표로 표시하고 기존 상세/수정 경로를 유지한다. 미연결은 버튼으로 전환해 해당 수입을 미리 선택한 기존 보호 연결 폼을 열고 참가자 선택란으로 이동한다. 클릭만으로 저장하지 않으며 확인 후 연결한다. 연결 후보가 없으면 안내와 보험 명단 상세 경로를 제공한다.
- 검증: 표적87 passed/2 deselected, 최신 main 통합5 passed·JS 문법 PASS. ego-browser 합성320/390/1440px×밝음/어두움6건·키보드·실제 합성HTTP 연결/취소/확인·후보 없음 PASS. 합성 연결1→2, 취소 시1 유지, 원본 수입 불변. 운영 읽기 수락에서 정확한 수입 선택·참가자란 focus·폼 표시 PASS, 연결 글자400/테두리0·44px 터치 영역·행 높이 동일·가로 넘침0. 실제 운영 연결 저장은 누르지 않았다. 기존 보험 패널 header 테두리0·아이콘 및 workflow 공통 장식 제외도 확인했다.
- 배포1,269 blobs 불일치0·runtime SHA 검증·단일 listener·health/ready200·보호API401/403·금융보호13표 전후 불변 PASS. 이전 검증 릴리스/task 복구점 보존. 코드 전용으로 새 전체DB백업/복원은 반복하지 않았다. 금융/참가자 연결/Google/원본/스키마 쓰기0. 전체 회귀·실기기는 국소 UI 변경으로 미실행이다.
- 근거 `.local-archive/insurance-connect-action-20261102/`의 targeted/integrated XML·review/release-audit/deploy-evidence·browser-layout/browser-connect/browser-no-candidates·live-final.json·live-after.png·checkpoint.json. 재개 시 배포/운영 수락 근거를 대조하고 남은 문서만 완료했다. 해당 이름의 활성 ego TaskSpace 없음 확인. 기존 사용자/병행 변경을 보존하고 별도 index로 본 문구만 커밋한다. 요청 미결/차단0·다음 기능 명령 없음. 문서 후속으로 재검사·재배포·서버 재시작하지 않는다.

## 2026-11-02 카드 조회기간 증빙·미확인 구간 구현 완료

- COMPLETE — 열린 PR의 미구현을 ANUS Free Auto 2개에 위임하라는 요청의 대상 #479를 [PR510](https://github.com/6Soo/cost/pull/510)으로 구현·병합·배포했다. [수락9개·검사·한계](specs/card-upload-coverage-implementation-20261102.md). 원명세 #479도 병합됐다. 당시 #477은 이미 구현된 UI 변경이고 이후 #484는 이번 실행 범위가 아니다.
- 기존 업로드의 파일별 결과에서 조회 기준·기간·관리 시작일을 확인하고, 원본/카드 맥락과 연결한 조회 확인·미확인·재확인 구간을 표시한다. 거래 min/max 역산·과거 소급·끝4만 같은 파일 합치기를 금지하며 제한/부분/파싱/조회조건 충돌은 사용자 확인으로 승격하지 않는다. 기존 비동기 업로드·원행/수동/중복/환불/OTA 보호를 유지하고 기존 변경 로그만 사용해 스키마 변경이 없다.
- 최신 통합52 passed/7 subtests, 인접보호62 passed. 기존 업로드 UI fixture1 timeout은 변경 전699eb8ed의 page()로 동일 재현했으며 통과에 포함하지 않는다. ego 합성320/390/1440px 넘침0·44px·파일별 저장·CSRF·HTML 삽입0, 실제 signed HTTP의0건 업로드/소유자 확인/조회 PASS. 전체 회귀·실기기·실제 고객 업로드는 미실행이다.
- 운영 `a7aa8c7ff23af9574ccbf42301803687b788d64d`, 직전 검증 `699eb8ed6b2c796b1da7841e4605db7c0ef38fc2`. 검사/병합 트리 동일·1,282blobs 불일치0·task/processSHA·단일loopback8751·health/ready200·신규/기존 보호API401/403·금융보호13표 내용/스키마 불변 PASS. task 인수/SourceRefresh 상태와 이전 검증 릴리스/task XML 복구점 보존, 코드 전용이라 새 전체DB 백업/복원은 반복하지 않았다.
- 호스트venv 격리 합성의0건 증빙·공백·멱등·비변경 PASS. 인증ego 운영/import의 카드 업로드 탭/조회기간API200·390/1440px 넘침0·버튼44px 수락, 조회확인0/재확인0으로 과거 자동소급 없음 확인. TaskSpace19/20 정상 종료. 실제 금융/분류/여행/환불/Google/원본/스키마 쓰기0.
- 근거 `C:/AX/cost/.local-archive/card-upload-coverage-final-20261102/`의 checkpoint·browser-evidence·live-browser·deployed-smoke·review/release-audit·protection-before/after·deploy-evidence 및 호스트 동일SHA 감사 기록. 사용자·병행 변경·stash 보존. 요청 미결/차단0·다음 기능 명령 없음. 결과 문서 후속에는 재검사·재배포·서버 재시작을 하지 않는다.

## 2026-11-02 자동분류 성능 최적화 운영 반영 완료

- COMPLETE — [PR507](https://github.com/6Soo/cost/pull/507) 병합·고정 운영 `699eb8ed6b2c796b1da7841e4605db7c0ef38fc2`; 이전 검증 `c0d45b46b10726ea9ce660ba92c62f79e3e998f5`. [동일 입력 Python/Rust 비교·검증 한계](specs/expense-performance-20261102.md). 최신 지출 UI·보험 연결·기업검색·비동기업로드·PR498 SQL 개선 보존.
- 계획당 여행 기간 검증 결과 재사용. 운영 읽기6,895행/64여행·Google 잔액 조건의 중앙값2.612→1.046초(59.9% 단축), Rust혼합0.998초이나 범위 중첩·다른 조건에서는 더 느려 Python 채택. 변환/호출 포함 Rust 후보 선택은 Python보다 느렸다. 전체출력/digest 동일. 메모리·DB조회·정적복잡성 개선 주장 없음; 실제 적용/업로드/HTTP 속도와 구분한다.
- 표적79·보호109 passed·최신통합37 passed(중복 포함). 검사fdeebfc0→최종SHA 차이는 문서뿐.1,275Git blobs불일치0·task/processSHA·단일loopback8751·health/ready200·보호API401/403·금융보호13표 내용/스키마 불변 PASS. 배포본호스트venv 합성80행/8여행 plan/render무쓰기PASS·인증ego/import4탭/가로넘침0 수락/TaskSpace16종료.
- 코드 전용 직렬 전환, 이전 검증 릴리스·task XML 복구점 보존. 새 전체DB백업/복원 반복없음·Rust운영의존성/DDL/운영분류·여행·금융·환불·Google·원본 쓰기0. 근거 `.local-archive/expense-performance-20261102/`의 측정JSON·검사XML·review/release-audit/deploy-evidence·protection-before/after·deployed-smoke·browser-after 및 호스트 동일SHA deploy-evidence. 후속coverage 담당자에게 host/gate 해제통지. 전체회귀/실제 재처리/실기기 미실행. 문서 후속만으로 재검사·재배포·재시작하지 않는다.

## 2026-11-02 지출 정리 가로 탭·전체 UI/UX 개선 완료

- COMPLETE — 사용자 “해당 메뉴들을 가로로 배치하면 하위메뉴로 두지 않아도될거같은데. 지출정리 페이지의 uiux전체를 개선해”. [PR #504](https://github.com/6Soo/cost/pull/504), 구현 `8feee6d9bde29d91b383bda62033072d282df84c`, 병합·고정 운영 `ec2a37ab4c2b9a6d9e41a23de64e2b09869d0870`, 이전 검증 `959c139c850b9f86d570cca2b7cc7d2842737db2`.
- 카드 자료 관리의 중첩 메뉴를 정리할 지출·저장된 자료·카드 업로드·분류 규칙의 최상위 가로 탭으로 전환했다. 상태 필터·PC 두 열/모바일 한 열 카드·파일 목록·업로드 영역·규칙 폼을 개선하고, 키보드 방향키/Home/End·선택 URL·새로고침·뒤로가기·편집값 유지를 지원한다. 업로드에서는 이전 파일 거래를 숨기며 재개 오류와 현재 업로드 결과를 표시한다. 기존 금융·수동·환불·업로드·CSRF 처리기를 재사용한다.
- 검증: 표적125 passed/기존3 failed는 변경 전 동일 재현, 보호39 passed, 최종 인접11 passed(중복 포함). ego-browser 합성320/390/768/1440px×4탭 가로배치·넘침0, 밝음/어두움·키보드/URL·업로드 재개·편집값 유지 수락. 추가375px·가로 화면·큰 글자 넘침0. 로그인된 운영 화면 네 탭 및390px 가로배치·넘침0 수락, TaskSpace14 정상 종료. 전체 회귀·실기기·실제 파일 업로드는 국소 화면 변경으로 미실행이다.
- 배포1,268 blobs 불일치0·검사/병합 tree 동일·task/process 고정SHA·단일loopback listener·health/ready200·보호API401/403·금융보호13표 전후 불변 PASS. 이전 검증 릴리스/task XML 복구점을 보존했으며 코드 전용으로 새 전체DB백업/복원은 반복하지 않았다. 실제 금융/분류/여행/환불/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/expense-ux-20261102/`의 targeted/baseline/protection/final-adjacent XML·browser-results/browser-adjacent·live.json·review/release-audit/deploy-evidence/checkpoint. 사용자·병행 변경을 보존하고 별도index로 본 변경만 커밋했다. 요청 미결/차단0·다음 기능 명령 없음. 문서 후속만으로 재검사·재배포·재시작하지 않는다.

## 2026-11-02 웹 텍스트 액션 버튼 전역 정리 완료

- COMPLETE — [조사·판단·검증 범위](specs/action-buttons-audit-20261102.md). 중복 카드 검색 진입점 제거, 카드 자료 관리 제목 정리, 필요한 액션의 아이콘·테두리·focus·모바일44px·비동기 갱신 공통화. 데이터 링크·테마 아이콘·핸들러·권한 유지. 복합 메뉴 이중 테두리·보험행 높이 회귀 보정.
- PR493·495·497·503, 최종 검증/운영 `959c139c850b9f86d570cca2b7cc7d2842737db2`, main 병합 `05755753b4a2fcd81447e91dacd10d594f66b2dc`. 직전3b72d0e의 기업검색·업로드·PR498 읽기 개선 보존. 정확한 후보36 passed/기존실패1 deselected, 보험행 별도25 passed. 기존실패는 변경 전 재현.
- 기존 주요9화면×1440/390/320px×라이트/다크의 넘침/대상누락0. 최종보정 후 지출정리3폭의 아이콘·모바일44px·키보드·중복프레임0, 실제보험패널2폭의border0/margin0·아이콘·행공통장식0 PASS. 기존 출력화면 `/export` GET 지연으로 실제 화면 수락은 제외하며 소스조사만 완료. 전체 회귀·실기기 미실행.
- 1,263 Git blobs 일치·task/processSHA·단일loopback·health/ready200·보호401/403·금융13표 불변 PASS. 분류/배정/Google/원본/스키마 쓰기0. 근거 `.local-archive/button-ux-20261102/`의 source/live감사·polish-targeted.xml·polish-evidence·polish-live.json. TaskSpace17 정상finish, host/gate작성권 해제. 문서 후속은 재배포/재시작하지 않는다.

## 2026-11-02 카드 전체 내역 기업카드 검색 누락 수정 완료

- COMPLETE — 사용자 “처리가 됐는데 왜 기업카드 내역이 조회안되지?” 및 카드 전체 내역 화면이라는 답변. [PR #500](https://github.com/6Soo/cost/pull/500), 구현 `b89647cd8847d5e020f4dbb026568555b7ce4d09`, 운영 `3b72d0e541f271241ffaa647862f132699a35a8b`, 이전 검증 `114af50de6f1a28f19186d9b3cc35c89a92c1be4`.
- 원인 재현: 기업카드218행이 저장돼 있으나 기존 검색의 카드사명 누락으로 `기업`은 국민카드의 가맹점 일치1행만 조회됐다. 개별 카드 선택은 정상이며8972는145행이다. 조회 조건에 issuer/유효한 마스킹 끝4자리와 기업카드·기업은행·IBK 별칭을 추가했다. 가맹점 등 기존 문자/금액 검색은 유지하고 카드/기간/미배정과 교집합을 취한다. 화면 검색 안내도 갱신했다. 원본/금융/분류/여행/환불/Google 쓰기0.
- 검증66 passed/기존2 failed는 변경 전114af50d에서도 동일 재현 후 제외했다(미배정 목적지 판정·삭제된 안내문 계약). 통과에 포함하지 않는다. 발급사/끝4·별칭·무날짜 취소·월/연 합계·페이지 커서·SQL 삽입 문자·잘못 저장된PAN 끝자리 검색 차단·원본 불변 포함. 운영 DB 읽기 전용 비교에서 기업카드218행/3페이지·중복/누락0·월 합계 일치. 전체 회귀는 국소 읽기 조건 변경으로 미실행이다.
- 인증ego 운영 실제폼 조회: `기업카드` 검색218건·첫100행·기업4971/4985/8972만 표시·다음cursor 검색어 유지·390px 가로넘침0 수락. TaskSpace12 정상 종료. 기업 일반 검색은 기존 가맹점 문자 일치도 유지하므로 기업카드 전체를 보려면 `기업카드`/`IBK`로 검색한다.
- 배포1,263 blobs 불일치0·검사후보/배포코드동일(차이는기존결과문서뿐)·task/process 고정SHA·단일loopback listener·health/ready200·검색영향경로/보호API401/403·금융보호13표전후불변 PASS. 이전114af50d의성능·UI·업로드async를보존했다. 코드전용이라이전검증릴리스/task XML 복구점을보존하고새전체DB백업/복원은반복하지않았다. 실제자료재업로드·금융재처리·Google쓰기는하지않았다.
- 근거 `.local-archive/ibk-query-20261102/`의 state.json·targeted.xml·baseline-existing.xml·actual-query.json·live.json·review/release-audit/deploy-evidence/checkpoint. 사용자/타작업변경보존. 서버/gate쓰기종료를후속UI·최적화담당자에게통지했다. 이 요청미결/차단0·다음기능명령없음. 문서후속만으로검사/재배포/재시작하지않는다.

## 2026-11-02 지출 정리·환불 읽기 성능 최적화 완료

- COMPLETE — 사용자 “코드 살펴보면서 발견된 부분들을 최적화, 가능하면 Rust”. [성능·Rust 판단·재현 명세](specs/cleanup-read-performance-20261102.md), [PR #498](https://github.com/6Soo/cost/pull/498). 실행 병목2개인 취소 상관 OR 전체조회와 환불별 전체 구매 순회를 SQLite 문장별 IN집합·정확 발급사/끝4/금액 후보색인으로 교체했다. 원본/유일성/수동/중복/환불·NULL 의미를 유지한다. Rust는 주 병목이 네이티브SQL과탐색횟수이고 도구체인도없어 미도입했다.
- 동일 입력·전체결과·워밍후5회 중앙값: 운영 읽기 묶음2.235→0.514초(4.35배), 환불0.625→0.248초(2.52배),486링크전체·목록/건수동일·쓰기0. 합성5,000구매/500취소는38.80배/16.47배이며 운영/HTTP개선율과구별한다. 검사144+40+47 passed, 후속NULL4는40과중복이다. 전체회귀/실기기는국소읽기변경으로미실행.
- 구현 `c82d86b7`·검사 `2e3a6935`, main병합/고정운영 `114af50de6f1a28f19186d9b3cc35c89a92c1be4`, 이전검증 `e95a82392be716f488e1175d8ed621c2ac6cd8ec`. UI단일작성자handoff후직렬배포했고이전UI·비동기업로드코드를보존했다.1,262blobs불일치0·task/processSHA·단일loopback8751·health/ready200·보호API401/403·금융13표내용/스키마불변PASS. 이전검증릴리스/task복구점보존, 새전체DB백업/복원반복없음. 금융/분류/여행/장부/Google/원본/스키마쓰기0.
- 인증ego/import수락:총1·GAMSGO제외·원결제미연결아고다취소유지PASS,TaskSpace13종료. 준비중외부502는앞선UI전환중관측이며본배포후정상수락과구별한다. 근거 `.local-archive/read-performance-20261102/`의 profile/real-differential/synthetic-benchmark·검사XML·review/release-audit/deploy-evidence·browser-final·protection-before/after. 호스트작성권을후속담당자에게해제통지했고이후문서만처리한다. 이요청미결/차단0·다음기능명령없음. 사용자/타작성자변경보존·문서후속재배포없음.

## 2026-11-02 보험 연결 행 높이·과도한 버튼 테두리 회귀 수정 완료

- COMPLETE — 사용자 첨부의 연결 행만 높아지는 문제를 재현했다. 직전 국내여행 보험 대상 아님 PR488은 해당 연결 버튼을 변경하지 않았다. 이후 공통 버튼 장식 PR493이 `.participant-link-details > summary`에도 class·아이콘·상하8px margin을 부여해 연결60.4px/미연결·환불45px로 커진 것이 원인이다. 해당 summary만 공통 장식에서 제외하고 기존 chevron·focus·44px 터치 영역을 보존한다. PR495 복합 버튼 보호도 함께 유지한다.
- [PR #497](https://github.com/6Soo/cost/pull/497), 구현 `455384c0c07493880906a68ce5155e749922fe6b`, 병합·운영 `e95a82392be716f488e1175d8ed621c2ac6cd8ec`. 공통 버튼 담당65f011e가 직전 검증 운영 `61188520fe1758a18230bcdbf6563ee6cc70a1c0`에서 PR495+497을 통합해 단일 배포했다. 동시 host/gate 전환 없음.
- 검증: 실제 panel.render+site_shell 합성에서 초기·비동기 연결/미연결/환불 행을 비교,320/390/1440px×밝음/어두움6건 모두 같은 높이(PC45px/모바일 전체행93px),추가 margin0·가로 넘침0·키보드 펼침/접힘 PASS. Python 관련25 passed. 같은 조건의 브라우저 회귀 테스트를 추가했으며 본 작업의 실제 브라우저 실행은 ego-browser다. 인증 운영 화면의 연결 행과 미연결/환불 행 높이·장식 제거를 live-final.json에서 확인했다.
- 운영 SHA·health/ready·보호API 및 금융 보호13표 내용/스키마 불변은 host 동일SHA deploy-evidence와 배포 담당 근거를 사용한다. 금융/참가자 연결/Google/원본/스키마 쓰기0. 전체 회귀·실기기는 국소 장식 수정으로 미실행. 기존 미커밋 소스 보존,격리 archive/별도 index 사용.
- 근거 `.local-archive/insurance-row-regression-20261102/`의 browser-result.json·targeted.xml·live-final.json·checkpoint.json 및 호스트 동일SHA 배포 기록. 요청 미결/차단0·다음 기능 명령 없음. 문서 전용 후속 재배포/재시작 없음.

## 2026-11-02 카드 업로드 지연·실패 표시 수정 완료

- COMPLETE — 사용자 첨부 XLSX 처리 지연·연결 실패 개선. [PR #494](https://github.com/6Soo/cost/pull/494), 구현 `25d1bca9`·통합 검증 `e9ec14bd`, 운영 `61188520fe1758a18230bcdbf6563ee6cc70a1c0`, 이전 검증 `697eb8f064e1bccccc07276d943958260c68f06f`. [실행 계약](specs/card-upload-latency-20261102.md).
- UI 요청은 검증·원본 접수·내구 큐 저장 직후202를 반환하고 기존 분류→OTA 갱신→기록→전수 검증을 서버에서 직렬 실행한다. 소유자 전용 상태 조회는 금융DB/작성자 잠금을 사용하지 않는다. 진행 단계·경과 시간·연결 재시도·새로고침 재개·저장된 파일 링크를 제공하고, 저장 후 오류를 업로드 실패로 세지 않는다. 처리 중 새로고침에는 DB 없는 UI shell을 제공한다. 원문·수동 결정·중복·환불 보호 및 기존 동기 API를 유지하며 불필요한 중간 화면 조립2회를 제거했다. 총 분류/OTA 처리 시간이나 운영 개선 배수는 미측정이다.
- 검증: 최신 통합 트리 표적/보호82 passed. 느린 분류를 중지한 채202·상태GET·새로고침HTML 응답, 같은 파일 재접수·OTA 갱신 전후 기록·부분환불·수동 이동·내구 복구·전수 대조 포함. 별도 인접33·HTTP/UI5 passed는 중복을 포함하므로 합산하지 않는다. ego-browser 합성 새로고침/완료/접수 후 오류/상세 링크/390px 넘침0 수락. 전체 회귀·운영 실파일 재업로드는 미실행이며 금융 재처리를 하지 않았다.
- 첨부 원본은 읽기 전용 조사에서44행이 이미 저장되어 있었고43행 분류/내부 기록 완료·취소1행needs_review임을 확인했다. 특정 프록시 타임아웃 로그는 확보하지 않았다. 취소행 보호 유지, 재업로드·실제은행환급·Google 반영을 수행/확정하지 않았다. 인증 운영 화면에서 같은batch의44행과 새 async 코드·상태복구 함수 정상 표시 수락. TaskSpace8 정상 종료.
- 배포1,259 blobs 불일치0·검사/배포 트리 동일·task/process 고정SHA·단일loopback listener·health/ready200·새 상태API/화면401 및 기존보호API401/403·금융보호13표 전후 불변 PASS. 기존 task 인수와 SourceRefresh 상태 보존. 코드 전용으로 이전 검증 릴리스/task XML 복구점을 보존했으며 새 전체DB백업/복원은 반복하지 않았다. 실제 금융/분류/여행/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/upload-speed-20261102/`의 merged-targeted.xml·final-adjacent.xml·saved-upload-state.json·live.json·review/release-audit/deploy-evidence/checkpoint. 사용자/타 작업 변경 보존. 후속UI 배포 담당자에게61188520 보존과 서버/게이트 쓰기 종료를 전달했다. 이 요청 미결·차단0·다음명령 없음. 문서 후속으로 재검사·재배포·재시작하지 않는다.

## 2026-11-02 분류 완료 거래의 반복 검토 요구 수정 완료

- COMPLETE — 사용자 첨부 GAMSGO 반복 검토 원인 수정. 구버전 `complete-card-inference-v1` 문구만 완료로 인정하던 지출 정리 SQL에 현재 여행 권한으로 검증한 저장 분류 완료 조건을 추가했다. 낮은 신뢰도/분류 출처와 무관하게 여행·항목이 완료되면 목록·필터·건수에서 재확인을 요구하지 않는다. 내부 장부 미기록은 분류 미완료로 간주하지 않는다. 원본 오류·보류·환불 후보·원결제 미연결은 보존한다. 권한이 상실된 여행은 다시 표시한다.
- PR #489·#491 정상 main 병합. 최종 구현·고정 운영 `859c3af426451ef2284bf436dcce9c3ccf9fe74b`, 병합 `b504526d`, 이전 검증 `b7c60927dddf110fe616699a07cf65ea5e8cdcea`. 검토 중 섞인 독립 제목 두 줄은 후속에서 기존 main 문구로 복구했고 workspace의 다른 작성자 변경은 보존했다. 과거 기기록 여행 전체를 매번 검증하지 않도록 미기록 후보만 검증한다.
- 검증: 최종 후보 지출 목록/필터/분류 완료·원본/수동보류·환불/원자 기록/유지보수 77 passed. 별도 소스 문구 계약 1 failed는 기준 main에서 동일 재현; 통과에 포함하지 않는다. 운영 DB 읽기 전용 대조 쓰기0. 전체 회귀·실기기는 국소 읽기 판정 변경으로 미실행이다.
- 실제 ego-browser 인증 GET 수락: 처리필요 2→1·분류배정0·결제환불1, GAMSGO 제외·원결제 미연결 아고다 취소 보존. 해당 취소의 동일 카드 원결제는 현재 수집 자료에서 찾지 못했으며 원결제 원본/참조가 필요하다. 가맹점명·소액만으로 링크나 환급 완료를 만들지 않았다. TaskSpace7 정상 종료.
- 배포 1,255 blobs 불일치0·검사 후보와 동일·task/process 고정SHA·단일loopback8751·health/ready200·보호API401/403·금융보호13표 내용/스키마 불변 PASS. 코드 전용이므로 이전 검증 릴리스/task 복구점 보존, 새 전체DB백업·복원은 반복하지 않았다. 금융/분류/여행/장부/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/cleanup-root-20261102/`의 verified-final.xml·baseline-protection.xml·actual-readonly.json·browser-final.json·review/release-audit/deploy-evidence·protection-before/after. 요청된 코드 수정/배포 미결0·다음 기능 명령 없음. 아고다 미연결은 원결제 자료 의존이며 자동 연결/완료 처리하지 않는다. 문서 후속으로 재배포하지 않는다.

## 2026-11-02 국내여행 보험 대상 아님 UI 완료

- COMPLETE — 사용자 “국내여행은 보험을 가입하지 않기 때문에 보험명단이 없다” 및 제안 실행 승인. 기존 `trip_region()`의 destination 정확 일치 판별에서 KR인 실제 여행만 국내여행 배지·중립적인 “국내여행 · 보험 가입 대상 아님” 안내를 표시한다. 보험 명단 열/대조 패널/후보 비교를 숨기고 lazy 대조 요청을 생략한다. 해외·지역 미상은 기존 UI 유지, 지역명 목록 확대·여행/참가자/수동 연결 변경 없음.
- [PR #488](https://github.com/6Soo/cost/pull/488), 구현 `d6a4cfaeb7dc4eefcaaac991f8d55c0e5eb25a95`, 운영 `b7c60927dddf110fe616699a07cf65ea5e8cdcea`, 이전 검증 `752eff0c667ddd8e4e661ec6b069d2d8c49e85ad`. 관련 묶음93 passed/기존 코드 문자열 검사1 failed/2 deselected, 해당 검사를 실제 HTML 헤더 검사로 변경 후 개별1 passed. 신규 국내/해외/미상·삭제/중복 여행·소유자/열람 권한·조회 생략·수입/원본 불변 포함. 전체 회귀·실기기는 국소 표시 변경으로 미실행.
- ego-browser 합성3분류×320/390/1440px9건 PASS. 인증 운영 통영·야마가타 각각390/1440px4건 PASS: 통영은 배지/안내·보험 열/패널/후보 없음·자동 보험 요청0, 야마가타는 기존 보험 열/패널/후보 유지·자동 보험 요청1. 수입 표와 합계 유지·문서 가로 넘침0 확인. 합성 모바일 스크린샷의 배치도 확인했으며 운영 모바일 캡처에는 기존 탐색 서랍이 열려 있었으므로 전체 화면의 가림 없음까지 통과로 주장하지 않는다. 브라우저 작업 공간은 정상 종료.
- 배포1,254 blobs 불일치0·검사본/병합본 동일 tree·task/process 고정 SHA·단일loopback8751·health/ready200·보호API401/403·새 영향패널 비로그인401·금융보호13표 내용/스키마 불변 PASS. 기존 SourceRefresh 상태·전체 task 인수 보존. 코드 전용으로 기존 검증 릴리스·task XML 복구 수단을 보존하고 별도 전체DB백업/복원은 반복하지 않았다. 금융/분류/여행/참가자/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/domestic-insurance-20261102/`의 targeted.xml·updated-contract.xml·browser-synthetic.json·review.json·release-audit.json·deploy-evidence.json·live-final.json·checkpoint.json. 공유 작업 트리의 기존 소스 변경을 보존하고 격리 archive 후보/독립 index로 커밋했다. 미결/차단0·다음 기능 명령 없음. 문서 후속 재배포/재시작 없음.

## 2026-11-02 PR458 후속 리팩토링·기존20실패 정비 배포

- [PR483](https://github.com/6Soo/cost/pull/483)·[PR486](https://github.com/6Soo/cost/pull/486) 정상 병합, 검사 `d750ee7e`와 동일 트리의 `752eff0c667ddd8e4e661ec6b069d2d8c49e85ad` 고정 배포. 이전 검증 `46e00f8d4bcd5ca0c3f7d3cc7861eae6bfb45acb`. 1,252 Git blobs 불일치0·task/process SHA·단일127.0.0.1:8751·health/ready200·OTA/카드/board401·Google action403·보호13표 내용/스키마 불변 PASS. 기존 task 인수/ParticipantSyncConfig·SourceRefresh 상태를 보존했다.
- 자동분류 책임 분리, 지출정리 집계 재사용·근거 일괄 읽기·렌더 호출 중복 제거, HTML 여행정보 충돌의 입력값 보존을 포함한다. 기존 실패20건의 현행 계약 검증과 통합348 passed, 권한/거절15 passed·26 subtests·기준 재현 별도3실패, 합성 ego-browser PC/390px·충돌/XSS PASS. 배포본 호스트venv 격리 자동분류/cleanup/조회무쓰기 PASS. 상세 [비교·20건별 판정·미개선 항목](specs/python-refactor-followup-results-20261102.md).
- 실행 코드량83,809행·동일본문중복2·실행 import 집합 동일, 분기21,674→21,670·큰함수102→101. SELECT58→35·합성 지출정리148.30→133.46ms, 자동분류 시간은 사실상 동일이다. 새 추론 helper90행82분기와 cleanup304행은 남아 있으며 전면 복잡성 해소로 보고하지 않는다. 운영 전체 성능·전체회귀·실기기·새 인증 운영UI는 미실행이다.
- 첫 재개에서 원 c5ee972d를 놓쳐 중복 자동분류 분해를 PR483으로 먼저 통합했고, 이후 원 worktree/검증 결과를 복구해 PR486에서 합쳤다.55e304ad 준비 시 PowerShell 바이너리 파이프 손상은 미활성 후보에서 중단·정리했다. 이어 전체백업 배포기 실행도 사용자 중단으로 task46e00f8d 유지·완료증거 없음이었다. 성공은752eff0c의 실제 최종 기록으로만 판정한다. 강제 push가 있었던 이전 재개 행동은 현재 금지 규칙에 맞지 않았으며 이후 정상 merge/push만 사용했다.
- 코드 전용 전환으로 검증 이전 릴리스·task XML 복구점을 보존하고 전체DB백업/복원·서버 DB전환은 반복하지 않았다. 금융/분류/여행 재처리·Google 최종장부·고객 원본·스키마 쓰기0. 근거 `.local-archive/refactor-followup-20261102/`의 review.json·release-audit.json·deploy-evidence.json·protection-before/after.json·released-smoke.json, 호스트 `releases/deploy-evidence-752eff0c667ddd8e4e661ec6b069d2d8c49e85ad.json`, task 복구점 `data/backups/v2-owner-ui-20261102T100655/board-task.xml`. 호스트/gate 작성권 해제 통지 완료. 문서 후속만으로 재배포/재시작하지 않는다.

## 2026-11-02 장부 숙박 이용일 표시 누락 수정 완료

- COMPLETE — 사용자 “왜 이용일 확인 필요로 되어있지? 조사해서 수정”. 기존 카드 장부 행의 빈 이용기간만 읽고 현재 OTA 검증 기간을 표시하지 않던 경로를 읽기 전용 투영으로 수정했다. [PR #482](https://github.com/6Soo/cost/pull/482), 구현·운영 `46e00f8d4bcd5ca0c3f7d3cc7861eae6bfb45acb`, 병합 `f1e6453dfa48edd8cdd02fbc4e01f1a79300f15b`, 이전 검증 `ce61fea6ca09546c838602c530308850b9cade30`. 병합 SHA에는 독립 PR481의 분류 변경이 함께 있어, main에 포함된 이번 검증 구현 커밋만 고정 배포했다.
- 검증: 표적42 passed·OTA 투영/동일 세대 신선도 보호12 passed, 실행 파일은 검사 후보와 모두 동일, Git diff check PASS. 저장 기간·수동 빈값·예약 충돌·stale·취소/환불·원본/중복 보호 유지. 전체 회귀·실기기는 국소 표시 변경으로 미실행.
- 인증 ego-browser 운영 수락: 재시작 뒤 OTA 대사 갱신 중에는 미확인 표시 유지, 정상 갱신 완료 뒤 실제 야마가타 장부의 문제4행이 각각6/26~28·7/5~7(2행)·6/28~29로 표시됨을 확인했다. 카드 날짜는 그대로다. 저장 대조 자료의4행 투영과 실제 신선한 운영 화면 수락을 구별한다. 개별 기간 근거가 없는 행은 날짜를 창작하지 않는다.
- 배포1,243 blobs 불일치0·task/process 고정 SHA·단일loopback8751·health/ready200·보호API401/403·금융보호13표 내용/스키마 불변 PASS. 코드 전용이므로 별도 전체DB백업/복원 대신 이전 검증 릴리스·task XML 복구점을 보존했다. 분류/여행/장부/Google/원본/스키마 쓰기0.
- 근거 `.local-archive/stay-date-20261102/`의 targeted.xml·protection-tests.xml·actual-projection.json·review.json·release-audit.json·deploy-evidence.json·live-final.json·resume-checkpoint.json. 사용자/타 작업 미커밋 변경 보존. 요청 미결/차단0·다음 기능 명령 없음. 문서 후속만으로 재배포/재시작하지 않는다.

## 2026-11-02 원본 상세 탭 이동·수동 Google 동기화 완료

- COMPLETE — 사용자 요청 2개를 [PR #478](https://github.com/6Soo/cost/pull/478)로 구현·병합·배포했다. 구현 `178b5b9558e0bf9f449ccfb1b6be8dae7d32d39c`, 운영 `ce61fea6ca09546c838602c530308850b9cade30`, 이전 검증 `6bfeee7b34d6eab551394b73d87bedfa29000bc1`. 원본 상세는 현재 여행 접근 권한·선택 사본·정확한 탭 제목을 확인하고 Google 읽기 전용 탭 색인에서 실제 gid를 찾아 새 창으로 연다. 장부 관리의 제거된 과거 페이지는 재활성화하지 않는다.
- 동기화는 실제 버튼이며 소유자/CSRF 확인 후 백그라운드 읽기 작업과 상태 조회를 연결했다. 기존 스케줄러와 같은 OS 잠금·실패 backoff·원자 세대 저장·이전 세대 보존을 사용한다. 실행 중 중복 클릭을 막고 진행/실패/재시도 표시, 성공 후 새로고침을 제공한다. 현재 운영 GoogleAuthority task의 public 읽기 모드와 일치하며 ADC 설정 지원도 유지한다. Google 최종 장부·금융 DB·분류·여행 교정·원본·스키마 쓰기는 없다. 승인된 실제 동기화로 로컬 Google 읽기 캐시만 갱신했다.
- 검증: 정확한 후보 트리 표적105 passed/기존 화면 문구 검사1 deselected, 스케줄/ADC 보호47 passed, JS 구문 PASS. 탐색 최초106 passed와 기존 문구 기대4 subtests 실패를 혼동하지 않는다. 기준 `a0f5d1edbe15467f5a530755bfbd07e3664187ca`에서도 같은4 실패 재현. 실제 HTTP worker/CSRF/완료 후 reload/실패 후 재시도/원본302 및 모바일390px 검사 포함. 전체 회귀·실기기는 범위가 제한되어 미실행이다.
- 배포:1241 blobs 불일치0, task/process 고정SHA·단일loopback8751·health/ready200·기존 보호API401·새 Google action API403, 금융보호13표 내용/스키마 불변 PASS. 첫 시도는 새API의 올바른 비로그인403을 점검 스크립트가401로 기대해 자동 이전 릴리스 복구; 점검 기대값만 수정 후 동일 코드 재배포 성공. 별도 전체DB백업/복원은 반복하지 않고 기존 검증 릴리스·task XML을 보존했다.
- 로그인된 ego-browser 운영 수락: 원본 버튼이 선택된 스프레드시트의 실제 `gid=1091731289`로 이동, 실제 동기화 클릭→진행/중복방지→성공 새로고침→시각03:00→03:58, 연결3개 소스 모두status=ok 확인. 재배포 전 화면의 이전CSRF는 거부됐고 최신 화면을 열어 성공한 근거를 구별한다. 금융 보호13표는 실제 동기화 뒤에도 불변이다. TaskSpace10은 결과 화면을 유지하고 종료했다.
- 근거 `.local-archive/ledger-sync-20261102/`의 checkpoint/candidate.xml/baseline.xml/protection.xml/review/release-audit/deploy-evidence/protection-before·after/browser-final.json 및 호스트 동일SHA 감사. 사용자/다른 작업의 미커밋 변경은 보존했다. 요청 미결·차단0, 다음 기능 명령 없음. 문서 후속만으로 재배포/재시작하지 않는다.

## 2026-11-02 보험 명단 행 간격·모바일 수입 표 조정 완료

- COMPLETE — 첨부 화면의 보험 명단 행 높이 차이를 CSS로 교정했다. 연결/미연결/환불완료 행은 PC45px, 모바일57px로 통일하고 펼침 화살표·hover·focus를 정리했다. 모바일 table/section의 기본 표 배치 때문에 각 수입 행이 전체 너비의 일부로 축소되던 문제와 합계 정렬도 수정했다. [PR #475](https://github.com/6Soo/cost/pull/475), 구현 `6f8b9a61`, 운영 SHA `6bfeee7b34d6eab551394b73d87bedfa29000bc1`, 이전 검증 `e448f34851cfaf122e4646585ea0a4c93589e37b`.
- 검증: 병합 트리와 동일한 후보의 수입/보험 연결 표적 50 passed/브라우저3 deselected. ego-browser 인증 운영 GET에서 PC1440·모바일390/320px의 동일 높이·행/표 너비 일치·합계 잘림0·가로 넘침0·마우스/키보드 펼침 PASS. TaskSpace8 정상 종료. 전체 회귀·실기기는 국소 CSS 변경으로 미실행. 분류/금융/수입/참가자/Google/원본/스키마 쓰기0.
- 배포: 1,237 Git blobs 불일치0·task/process 고정SHA·단일 loopback listener·health/ready200·보호5경로401·보호13표 내용/스키마 불변 PASS. 기존 task 인수/SourceRefresh 상태 보존. 코드 전용으로 새 전체DB백업/복원은 반복하지 않고 이전 검증 릴리스와 task XML 복구점을 보존했다. 근거 `.local-archive/insurance-density-20261102/`의 candidate-tests.xml·browser/live.json·release-audit/review/deploy-evidence 및 호스트 동일SHA 기록. 요청 미결/차단0·다음 명령 없음. 문서 후속은 재배포/재시작하지 않는다. 기존 사용자 미커밋 변경은 보존했다.

## 2026-11-02 기업·하나 다운로드 업로드 형식 복구 PR470 배포

- 구현 `b289b96e`·보호 보완 `9efd2b08`, 병합/운영 `e448f34851cfaf122e4646585ea0a4c93589e37b`. 기업 비표준 XLSX 스타일·잘못된 dimension과 하나 이용/해외 이용 헤더를 지원한다. 원행/승인번호 보존, 원문 열의 청구금액/수수료/부분취소 사용, 없는 매입일 공란, 명시 매입일·금액·가맹점·외화 충돌 및 수동·취소 보호를 검증했다.
- 최종 병합 트리53 passed/14 deselected·4 권한/CSRF subtests. 실제13파일/1,254행 읽기와 격리 메모리 DB 리허설 PASS: 기존6,851행·수동/장부/보류 불변, 신규 정상683·기존422·충돌149, 취소 다중성 유지·구매 앵커 중복0·모든 재수신 멱등. 충돌은 덮어쓰거나 운영 적용하지 않았다. ego-browser 합성3파일 HTTP200·파일별 링크·PC/390px 넘침0, 운영 인증 업로드 화면 GET PASS. 합성 환경의 분류 미완료와 파싱 성공은 구별한다.
- 최초 배포 전제 검사에서 병행 배포의 runtime 변경을 감지해 쓰기0으로 중단했다. 검증된598bf14f를 이전 릴리스로 갱신한 뒤1,237 blobs 일치·task/process SHA·단일127.0.0.1 listener·health/ready200·영향/보호4경로401·보호13표 내용/스키마 불변·task 인수/SourceRefresh 상태 보존 PASS. 코드전용으로 기존 릴리스/task XML 복구점을 사용하고 새전체DB백업/복원은 반복하지 않았다.
- 근거 `C:/AX/cost/.local-archive/upload-format-20261102/`의 merged-targeted.xml·actual-after.json·actual-rehearsal.json·resume-browser-final.json·http-smoke.json·live-browser.json·review/release-audit/deploy-evidence 및 `D:/WebLedgerHost/releases/deploy-evidence-e448f34851cfaf122e4646585ea0a4c93589e37b.json`. 실제 원본 운영 업로드/금융/여행/Google/원본/스키마 쓰기0. 전체 회귀/실기기는 미실행, 요청 미결/차단0·다음명령 없음. 문서후속 재배포/재시작 없음.

## 2026-11-02 알펜루트 배정 표시 누락 교정 완료

- COMPLETE — 사용자 “왜 알펜루트로 배정안됐지?” 조사 결과 해당 10/24 거래는 이미 `1020_알펜루트`(10/20~24)의 현지경비로 자동 추론 배정됐고 내부 장부에는 미기록이었다. 지출 정리 카드가 저장된 여행·항목을 보여주지 않아 혼동을 일으켰다. 유효한 현재 여행과 항목을 카드 본문에 표시하며, 무효 여행·보류·금융 보호 판단은 유지한다. [PR #471](https://github.com/6Soo/cost/pull/471), 구현 `13c7a3ed`, 운영 SHA `598bf14f8bd0b70241c03e6a10968969a31b66a5`, 이전 검증 `13b02d22388383271db8f254cca2dfb6dbb30279`.
- 검증: 표적 35 passed/기존 문구 계약 실패 4건 deselected(기준 `9835a769` 동일 재현). 활성/무효 여행 표시·escaping·조회 무쓰기 포함. 병합 시 추가된 두 운영 문서 외 실행 코드는 검사본과 동일하다. 인증된 운영 화면에서 현재 여행·현지경비·장부 기록 가능 표시와 PC/모바일390px 넘침0을 확인했다. TaskSpace7 정상 종료. 전체 회귀·실기기는 국소 표시 변경으로 미실행이다.
- 배포: 1,234 Git blobs 불일치0·task/process 고정SHA·단일 loopback listener·health/ready200·영향/보호5경로401·보호13표 내용/스키마 불변 PASS. 기존 task 인수/SourceRefresh 상태 보존. 코드 전용으로 새 전체DB백업/복원은 반복하지 않고 이전 검증 릴리스와 task XML 복구점을 보존했다. 분류/여행/장부/Google/원본/스키마 쓰기0. 근거 `.local-archive/gamsgo-alpen-20261102/`의 baseline/targeted-final/candidate.xml·review/release-audit/deploy-evidence·browser-final.json 및 호스트 동일SHA 감사 기록. 이 질문과 표시 교정 미결/차단0·다음 명령 없음. 문서 후속은 재배포/재시작하지 않는다.

## 2026-11-02 OTA 근거 카드의 여행 복구 누락·출처 표시 수정 완료

- COMPLETE — [원인·수락 근거](specs/ota-missing-trip-completion-20261102.md). 업종만 분류되고 여행이 빈 정상 구매를 자동 작업자/기록 복구 SQL이 누락하던 경로를 공통 미완료 판정과 OTA 우선 복구로 수정했다. 구현 `2fcfafaf`, [PR #462](https://github.com/6Soo/cost/pull/462), 배포 `62bfa07b77e56716b141230f2bdfb4962cd91055`. 병합 릴리스60 passed, 기준 회귀2건 실패 재현, OTA/환불/권한11 passed 근거를 보존한다.
- 승인 단건은 신선한 Board 백업·별도 복원 동등성/무결성·사본 재실행0 후 자동처리 완료. `1015_오제 / 숙박비 / 9,906원` 내부기록1건, 원본/수동/기존 장부·금융 링크/다른 행/스키마 보존, Google 쓰기0. 이후 금융 보호용 decided를 수동 출처로 오인하던 표시도 구현 `9835a769`·[PR #466](https://github.com/6Soo/cost/pull/466)·운영 `13b02d22388383271db8f254cca2dfb6dbb30279`로 수정했다. 표시/읽기6 passed·보호13표 불변.
- 최종 task/process SHA·단일 loopback8751·health/ready200·OTA/카드 보호401 확인. 이전 인증 브라우저 GET의 여행/항목/기록완료/장부보기 수락과, 출처 수정 후 읽기 전용 운영 catalog의 `기록 완료 · 자동 추론`/추가 확인 불필요/내부기록1/남은후보0을 구별한다. 출처 수정 후 브라우저 재검사·전체 회귀·실기기는 미실행이다.
- 근거 `.local-archive/ota-trip-gap-20261102/`의 release/source-release-tests·backup-restore·activation-protection·source-label/deploy-evidence·source-live-projection·resume-runtime. 인계의8000번 미응답은 서비스 포트 확인이 아니었으며 현재13b02d22와 배포 근거가 일치해 재배포/재처리하지 않았다. 요청 미결/차단0·다음명령 없음. 문서 후속 재배포/재시작 없음. 다른 작업자의 미커밋 변경은 보존한다.

# 운영 기록과 실행 경계

## 2026-11-02 항공권 예약 조회 오류·UIUX 개선 완료

- COMPLETE — 사용자 “문제수정 및 uiux개선”의 항공권 영역. [PR #465](https://github.com/6Soo/cost/pull/465), 구현 `cbc8e7a3`, 검증 배포 `5cf30d5c68ae626af9cf07d64aee425eb06467f7`. 선택 수동 여행 배정 테이블이 없는 정상 격리 저장소를 배정 없음으로 읽는다. 파일 누락·손상·부분 스키마는 계속 차단하며 GET 읽기 전용과 수동 배정 보호를 유지한다. 한국어 배정 상태, 예약 카드, 오류별 안내·재시도, 목록 갱신·페이지 이동, 상세 접힘과 긴 거래 설명 줄바꿈을 개선했다.
- 검증: 표적82 passed, 병합본 API/서명 권한26 passed, 원본 보호2 passed. 별도 실행82건 중 OTA catalog1건 실패는 단독 재검사1 passed로 구분한다. 합성 ego-browser의 목록/상세 재시도·generation 변경·빈 목록·페이지 이동·escaping, 320/390/1440px 두 테마·버튼44px·넘침0 근거를 보존했다. 실행 간 중복은 합산하지 않는다.
- 실제 인증 운영에서 세 여행 API200/빈 목록, 별도 예약이 있는 여행의 목록3건·확인 탑승객4명과 상세 여정·예약일 표시·접힘을 수락했다. PC1440/모바일390px 페이지/항공권 영역 넘침0·버튼44px 확인 후 기존 TaskSpace2를 정상 종료했다. 접힘 검사는 Chromium의 숨겨진 details 자식에 남는 레이아웃 크기 대신 실제 visibility로 확인했다. 전체 회귀·실기기 검사는 미실행이다.
- 배포: 1,233 blobs 일치·task/process 고정SHA·단일listener·health/ready200·영향/보호 API401·보호13표 불변 PASS. 직전 검증355a059b/task XML 복구점 보존, 코드 전용으로 새 전체DB 백업/복원은 반복하지 않았다. 후속 카드 표시 PR466의 실제 운영 `13b02d22388383271db8f254cca2dfb6dbb30279`에도 이번 수정이 포함됨을 ancestry·호스트 배포 근거·예약 실조회로 확인했다. 금융/분류/여행/Google/원본/스키마 쓰기0.
- 근거: `C:/AX/cost/.local-archive/flight-ux-20261102/`의 XML·browser.json·live-api.json·live-inventory.json·live-browser-final.json·review/deploy-evidence와 호스트 동일SHA 배포 기록. 원문/실명 캡처는 Git 제외 로컬에만 보존했다. 이 요청의 미결/차단0·다음 명령 없음. 병행 사용자 변경과 기존 workspace를 보존하며 문서 후속에는 재배포/재시작하지 않는다.

## 2026-11-02 수입 보험 명단 환불완료 표시 완료

- COMPLETE — 사용자 요청 두 항목 반영. [PR #464](https://github.com/6Soo/cost/pull/464), 구현 `0515370d`, 고정 운영 SHA `355a059ba5808151a8780409a09b06508427f2f3`, 이전 검증 `62bfa07b77e56716b141230f2bdfb4962cd91055`. 미연결의 `보험 미가입을 뜻하지 않음` 문구를 제거하고, 수입 행 총액이 0원 이하이면 보험 명단 열을 `환불완료`로 대체한다. 금액 미상은 환불완료로 추정하지 않는다. 최초 렌더·보험 비동기 로딩/성공/실패에서도 표시를 유지하며 기존 보험 연결·수입 원본/금액은 보존한다.
- 검증: 병합 트리와 동일한 후보에서 수입/보험 명단/연결·권한 보호 80 passed/브라우저 등 5 deselected. ego-browser 합성 0원·음수·양수 로딩/성공/실패 PASS. 인증된 운영 여행의 수입13행 중 0원1행 `환불완료`, 양수 행 오표시0·삭제 문구0을 확인하고 TaskSpace4를 정상 종료했다. 전체 회귀·실기기는 미실행(국소 표시 변경). 금융/참가자/Google/원본/스키마 쓰기0.
- 배포: 1,233 Git blobs 불일치0·검사본/병합본 트리 동일·task/process 고정SHA·단일 loopback listener·health/ready200·영향/보호4경로401·보호13표 내용/스키마 불변 PASS. 기존 task 인수/SourceRefresh 상태 보존. 코드 전용이므로 새 전체 DB 백업/복원은 반복하지 않았으며 이전 검증 릴리스/task XML 복구점을 보존했다. 근거 `.local-archive/income-refund-label-20261102/`의 targeted.xml·browser.json·live.json·review/release-audit/deploy-evidence 및 호스트 동일SHA 감사 기록. 이 요청의 미결/차단0, 다음 명령 없음. 후속 문서는 재배포/재시작하지 않는다.

## 2026-11-02 첨부 카드8건 조사·취소 표시 교정

- COMPLETE — [PR461](https://github.com/6Soo/cost/pull/461), 운영 `efefafc43dd13134c61c85c9fd1d171c8523142c`, 이전 검증 `d206cab71cf02843fcd38be5340cf3e04ff4d75f`. [거래별 조사·범위·미확인 사실](specs/eight-card-review-20261102.md). 취소7건의 목록/상세/미배정필터/집계·정산탭 표시를 교정하고 명시 이용 확인 보류1건을 보존했다. 금융 연결·금액·분류·장부·Google·원본·스키마 쓰기0.
- 병합본65 passed/기준624ceec9 재현 기존실패2 deselected.1,232 blobs 불일치0·task/process 고정SHA·단일loopback listener·health/ready200·영향/보호4경로401·보호13표 내용/스키마 불변·SourceRefresh 상태와 기존task 인수 보존. 기존 검증 릴리스/task XML로 복구 가능하며 코드전용이라 새전체DB백업/복원은 반복하지 않았다.
- 인증ego-browser8건(취소표시7·이용확인보류1)·395,000원 상세·미배정 필터 제외·모바일390px 가로넘침0 수락, TaskSpace1 정상종료. 최초Aside 실행파일 부재 및 검수스크립트의 snapshot root/버튼포함 비교 오류는 교정 후 재검수했다. 실제은행환급/현재Gmail전체검색·전체회귀·실기기 미실행. 로컬 `.local-archive/eight-card-review-20261102/`와 호스트 동일SHA release/deploy audit에 근거 보존. 요청 조사/코드/배포 미결0, 다음명령 없음. 문서후속 재배포/재시작 없음.

## 2026-11-01 모든 비용 준비기간·Python 기능군 리팩토링 완료

- COMPLETE — [PR458](https://github.com/6Soo/cost/pull/458), 구현 `26e7b9c4`, 고정 운영 SHA `d206cab71cf02843fcd38be5340cf3e04ff4d75f`(직전 검증 `34835792`). [실행 명세](specs/python-refactor-20261101.md)·[수치/한계/재현](specs/python-refactor-results-20261101.md). 숙박 외 교통·식비·항공·기타/현지경비도 여행 사이 빈 기간이면 가장 가까운 다음 검증 여행의 준비 비용으로 추론한다. 실제 이용기간·수동 배정·3820 국내 잔여/사용자 예외·원본/환불/중복 보호를 유지하며 날짜·여행 기간을 바꾸지 않는다.
- 전체 추적 Python835개를 조사한 뒤 여행 기간/후보, OTA 매칭, 카드/은행 CSV·원본 검증, 회사명, 스냅샷/합계 읽기를 공통화했다. 병렬 에이전트의 초기 OTA/권한 재작성은 검토에서 거절하고 최종 동등성이 검증된 변경만 통합했다. Rust는 도입하지 않았다. 실행 중복 사본6→2, AST 분기21,376→21,356, OTA 진입 함수434→10행. 실행 코드82,788→82,886행으로 **98행 증가**하여 전체 코드량 감소는 달성하지 않았다. 전체100행 초과 함수 수는102로 동일하다. 합성 OTA3.67배, 여행 커널2.25~31.4배, 선택 SQLite 조회237배는 운영 응답시간 개선율이 아니다.
- 표적/보호: 여행금융110·OTA120·입력34·권한은행84·스냅샷합계59 passed(중복 포함), 준비기간17/작업자2 passed. 합성OTA200사례 및 성능 입력 전체 결과 동일. OTA13·담당자 안내1·화면 상태6 실패는 기준bc723cfa에서도 같은 항목으로 재현했다. 전체 회귀·실기기·운영 부하 시험은 미실행이다.
- 배포 전 수집기3개 상태를 저장·일시 중지하고 기존 자동 완료 설정을 잠시 껐다. 5DB/99파일 복구 사본과 격리 복원에서 전체 테이블/열/파일·원본 binding 일치를 확인했다. 1,227 blobs 불일치0·검증 트리 일치·task/processSHA·단일127.0.0.1 listener·health/ready200·보호/영향6경로401·코드 전환 전후13표 불변 PASS. 기존 ParticipantSyncConfig 등 task 인수는 SHA 외 동일하다.
- 복구 게이트 후 기존 `automatic_card_completion:true`를 복원하고 같은 검증 코드로 재시작했다. **사용자 추가 요청 없이** 3건 분류·내부기록3건/29,186원으로 사본 예측과 일치했다. 전액 취소 원결제1건 보호 유지, 실패0. 전체 테이블 비교에서 허용된3건/기록·감사·요청 외 원본/수동/기존 기록/금융 링크/다른 행 불변과 스키마 불변을 확인했다. 실제 은행 환급·Google 반영을 뜻하지 않는다. Google 쓰기0. 사본의 추가 sweep 기록0도 확인했다.
- 최종 Board/SourceRefresh Running, GoogleAuthority/MailCollect Ready 및 기존 enabled 상태 복구 PASS. 근거 `.local-archive/python-refactor-20261101/`의 `review.json`, `backup-restore.json`, `deploy-evidence.json`(코드 전환), `final-deployment.json`(별도 데이터 적용), `activation-protection.json`, `task-options.json`. 복구 원본은 호스트 전용 디렉터리에 보존했다. 현재 승인 큐 PY01~PY05 완료, 새 개발/승인 대기0. 문서 후속 병합으로 재배포하지 않는다.

## 2026-11-01 카드 자동처리 누락 재발 방지·운영 활성화 완료

- COMPLETE — 최신 지시 “해당 문제 자체를 재발안하도록 수정해”. [PR #455](https://github.com/6Soo/cost/pull/455)·[PR #456](https://github.com/6Soo/cost/pull/456), 구현 `2475abee`·`bb4271e9`, 최종 운영 SHA `348357929d9e3eb248b357a19efecc28a5d5a29e`. [실행 계약](specs/card-completion-recurrence-20261101.md). 이전 PR453은 소유자의 후속 요청이 있어야 복구했으므로 무요청 재발 방지까지 완료된 것은 아니었다. 접수 직후 기존 requests의 전용 scope에 정확한 작업 ID를 저장하고, 단일 작업자가 시작·업로드 깨움·주기 확인으로 재개한다. 원본 접수 뒤/분류 뒤/기록 중 중단과 재시작을 처리하며 성공한 분류는 항목·배정·강한 근거를 유지하고 기록만 재개한다. 새 스키마·외부 큐·유료 자원은 없다.
- 실제 미분류 정상 구매와 저장된 작업만 최대50건씩 처리한다. 과거 분류 완료 미기록 내역 전체는 재처리하지 않는다. 요청과 같은 runtime/store 잠금, 현재 정책·게시 OTA 근거, 원자 기록을 사용하고 원문 전체 파싱/네트워크 대사를 잠금 안에서 실행하지 않는다. 실패5~300초 백오프와 다른 거래 계속 처리, 근거 갱신 재평가·종료 정리를 검증했다. GET은 읽기 전용이고503은 실제 실행 중인 작업자가 있을 때만 재업로드 없는 자동 복구를 안내한다. 수동·기기록·원본/중복·명시보류/제외·환불 및 원승인번호 환불 원결제를 보호한다.
- 검사: 표적60 passed, 기록/예약/환불 보호52 passed(중복 포함), 최종 강한 근거 보존을 포함한 인접51개에서50 passed/Windows 임시 DB 잠금 정리 실패1건은 같은 항목 단독1 passed. 작업자13개는 최종 인접 검사에서 모두 통과했다. 별도 기존 생명주기20 passed/1 failed는 기준 `242ef999`에서도 SimpleNamespace.path 누락으로 재현했으며 통과로 세지 않았다. 최초 넓은 후보/느린 조회는 운영 사본에서 발견해 완료된 과거 자료 제외·정확한 저장 작업·환불 키 일괄 조인·범위 내 기록으로 교정했고 실제 적용하지 않았다. 분류/기록 중단·무요청 HTTP503 복구·재시작·잠금·범위/원본 보존·원자 실패/재시도·중복0·근거 갱신·활성화 경계를 검증했다. 전체 회귀/실기기·새 UI 브라우저 검수는 미실행이다(화면 변경 없음).
- 운영 사본 최종 리허설: 미완료5건을 평가해 기록 가능한1건/380,203원 내부 기록, 기존 정책/권위 조건4건 유지, 실패0·재실행 무변경·다른 행/원본/수동/기존 장부/링크 보존·스키마 불변 확인(검증 포함5.47초). 백업 원문은 보호 호스트에만 보관했다. 첫 코드 `7c8ed5c1`는 미활성 상태로1,218 blobs·task/processSHA·단일listener·health/ready200·영향/보호8경로401·보호13표 불변을 확인했다.
- 별도 데이터 활성화 게이트: Board/SourceRefresh/GoogleAuthority/MailCollect의 상태·task XML을 보존하고 작성자를 멈춘 뒤 운영5DB/99파일 백업과 격리 복원·전체 테이블/열·파일 해시·review binding·live 불변 검증을 통과했다. 보호 복구본 `D:/WebLedgerHost/data/backups/operational-20261101T060854934832Z/`, 별도 설정/task 복구 근거는 같은 호스트의 `card-completion-activation-20261101T150828432/`. 기존 card-flow.json에 `automatic_card_completion:true`만 추가하고 다른 설정은 보존했으며 작업 활성/Running/Ready 상태를 복구했다. Google/원본/인증/금융 링크 쓰기·스키마 변경0.
- **실제 사용자 요청 없이** 재시작한 운영 작업자가1건/380,203원을 자동 내부 기록했다. 실제5건의 분류 필드 변경과1건의 기록 외 다른 거래·원본·수동·기존 장부·링크는 사본/실제 DB 비교로 불변 확인했다. 서버 재시작의 process lease는 기존 행 보존과 정상 추가를 별도로 확인했다. 최종 `34835792`의 저장 근거 보존 후속 배포도1,218 blobs 일치·runtimeSHA/단일listener·health/ready200·보호8경로401·13표 불변. 최종 작업자 실패0·정책 조건4건 유지·추가 기록0이며 자동 활성화는 재시작 후에도 유지된다. 전체 거래가0건 미결이라고 보고하지 않는다. Google 최종 장부와 실제 환급 사실은 변경/확정하지 않았다.
- 근거 `.local-archive/card-completion-recurrence-20261101/`의 targeted-final.xml·final-protection.xml·resume-protection-final.xml·ota-resume-rerun.xml·lifecycle.xml·lifecycle-baseline.xml·rehearsal.json·activation-backup-restore.json·activation-protection.json·runtime-final.json·최초/`resume/` 최종 review/protection/deploy-evidence, 호스트 동일SHA release/deploy audit. 재발 방지 요청 미결/차단0, 다음 명령 없음. 완료 문서 후속에는 재배포하지 않는다.

## 2026-11-01 기존 Booking 카드 미분류 복구 완료

- COMPLETE — [PR #453](https://github.com/6Soo/cost/pull/453), 구현 `52f1050c`, 운영 SHA `b4e7e2fb897b017667f94dde87119d36d6a7c0fc`. 기본 분류에서 예약 근거 대기로 남은 과거 거래를 자동 기록 요청이 그대로 미리보기에 넘기던 복구 누락을 수정했다. 소유자의 쓰기 요청에서 현재 배치의 미완료 구매만 골라 기존 예약 근거 우선 분류·최종 추론을 먼저 실행한다. 신규 원행 전체·다른 배치·기기록·수동 결정/override·보류/제외·중복/원본 오류는 보호하고 GET은 읽기 전용으로 유지한다. 새로운 백그라운드 일괄 처리나 Google 자동 쓰기를 추가하지 않았다.
- 운영 읽기 진단: 사용자 스크린샷의3건은 `needs_review/booking_evidence_needed`·revision1·항목/배정 공란이며 원본 오류/중복/수동 보류/결정이 없었다. 기존 배치의 기본 분류 로그는 있으나 해당3행의 완료 추론은 반영되지 않은 상태였다. 가져오기 당시 중단의 정확한 외부 원인까지 확인한 것은 아니다. 현재 중앙 대사 공개 결과에 해당 예약번호/거래ID가 없고, 기존3820 잔여 규칙으로3건 모두2026년4분기 기타비용 처리 가능함을 확인했다. 보관 메일 자체가 없다고 단정하지 않았다.
- 검증: 자동 기록/완료/GET/권한·원본/타배치 보존·재실행39 passed, 예약 귀속/환불 그룹/복구23 passed(복구3중복). 초기 새 합성 회귀는 승인 원행을 매입으로 가정해 실패해 매입 fixture를 교정했고, 기록 뒤 `decided`는 사용자 답변만을 뜻하지 않아 `decided_at`/review_decisions로 출처 검증을 교정했다. 신규 미분류 원행 전체로 범위를 넓힌 첫 시도는 기존 부분환불 준비 검사를 깨뜨려, 이미 분류를 시도한 구매 출처와 보호 조건으로 복구 대상을 한정했다. 최종 보호 검사 모두 통과. 전체 회귀/실기기 미실행이다.
- 코드 배포는 검수/병합tree동일·1,215 blobs 일치·task/processSHA·단일listener·health/ready200·영향/보호8경로401·보호13표 불변·SourceRefresh 유지. 이전 검증 `10aee46d`/task XML 복구점을 보존했고 코드 전환 자체는 운영 데이터 쓰기0이다. 문서 후속으로 재배포하지 않는다.
- 별도 승인된 해당3건 교정: 격리 SQLite 사본에서 분류/내부기록3건·합계1,371,632원·재실행0을 검증한 뒤, 보호 호스트의 SQLite 복구 사본·integrity_check·변경 전 행·source/revision을 확인해 기존 원자 분류/분기 기록 경로로 실제 적용했다. 분류3·내부기록3, 다른 모든 행/원본·수동/금융 관계 불변. 별도 전체 재처리/마이그레이션/예약·결제 링크/Google 쓰기/실제 환급 확인0. 이 소수 교정만을 위해 서버나 수집기를 중지하지 않았다. 보호 복구본 `D:/WebLedgerHost/data/backups/selected-booking-completion-20261101T053813576827Z/`에 원문을 보관했고 Git에는 원문/고객 ID를 넣지 않았다.
- 실제 인증 운영 PC1440/모바일390에서 배치GET의 분류완료/기기록3건·미분류 목록에서3건 제거·넘침0을 확인했다. 쓰기 중 열린 첫 화면은 이전 목록이 남았으나 적용 완료 후 새 GET으로 갱신해 수락했다. Aside 앱 실행 파일 부재로 ego-browser를 사용했다. 근거 `.local-archive/booking-auto-completion-20261101/`의 diagnostic/history·targeted-final.xml·protection.xml·selected-rehearsal/applied.json·live-browser.json·review/protection/deploy-evidence 및 호스트 동일SHA audit. 이 스크린샷3건 요청 미결/차단0이며 다른 미결 전체를 완료했다고 보고하지 않는다.

## 2026-11-01 카드 업로드 UI·여러 파일 순차 처리 완료

- COMPLETE — [PR #451](https://github.com/6Soo/cost/pull/451), 구현 `bf9ad2b4`·`635da5cc`, 최종 검사 `614f4ede`, 운영 SHA `10aee46d228a7bbab58e900ce268d1f7c116d874`. 업로드 영역의 파일 목록·드롭·키보드 선택과 XLS/XLSX/CSV 여러 파일 순차 요청을 추가했다. 중간 오류 후 다음 파일을 처리하며 파일별 결과·상세 링크를 보존하고, 전송 성공과 분류 검증 완료를 구분한다. 처리 중 파일 선택 잠금·자료 전환 시 남은 요청 중단·모바일 숨김 입력란 넘침을 교정했다. 기존 파일별 API·CSRF·금융/중복 보호를 재사용한다.
- 표적 검사4 passed, 최종 키보드/드롭/큐2 passed(앞 검사와 중복), 기존 브라우저 진입/중복 보호2 passed. 실제 ego-browser 합성 DB에서 정상→오류→동일 원문 재업로드3파일을 처리해 결과2링크·실패1파일·거래1건 유지, 1440/390/320 넘침0·버튼44px 확인. 최초 추가 키보드 검사는 자동으로 열린 패널을 테스트가 닫아 실패했으며 패널 진입을 교정한 최종2검사가 통과했다. 첫 합성 브라우저에서 PC버튼34px을 발견해44px로 수정했다. 서버 재기동 뒤 캐시된 합성 페이지의 CSRF 오류는 새 페이지로 재검증했다. Aside 앱 실행 파일 부재로 ego-browser를 사용했다. 전체 회귀·실기기·실제 운영 파일 업로드는 미실행이다.
- 운영: 검수/병합tree동일·1,215 blobs 일치·task/process 고정SHA·단일loopback listener·health/ready200·영향/보호8경로401·보호13표 내용/스키마 불변·SourceRefresh 상태 유지. 인증된 운영 PC1440/모바일390에서 업로드 패널·multiple·드롭 영역·결과 컨테이너·44px 버튼·넘침0을 GET만으로 확인했다. 이전 검증 `35a6263b`와 task XML 복구점을 보존한 코드 전용 전환이며 새 전체DB 백업/복원은 반복하지 않았다. 실제 금융/분류/여행/명단/원본/Google/스키마 쓰기0.
- 근거 `.local-archive/card-multi-upload-20261101/`의 targeted-final.xml·queue-final.xml·browser-regression.xml·browser-evidence.json·live-browser.json·review.json·protection-before/after.json·deploy-evidence.json 및 호스트 동일SHA release/deploy audit. 요청 미결·차단0, 다음 실행 명령 없음. 후속 문서만으로 재배포하지 않는다.

## 2026-11-01 김동언(안드레) 여행 장부 추가 완료

- COMPLETE — [PR #447](https://github.com/6Soo/cost/pull/447), 구현 `93fb4182`, 운영 SHA `35a6263b9cd876091ccadaae66fda8f056e0fe5c`. [실행 명세](specs/andre-multi-owner-ledger-20261101.md)의 담당자별 원본·여행 식별, 기간 추론 분리, 수동 이름/종료일 보존, 여행 관리 담당자 필터, 수입·참가자·보험 참조 및 지출 중복 검토를 반영했다. 카드 소유자만으로 여행을 재배정하지 않았다.
- 실제 안드레 원본은 최초3개 확인 후 작업 중5개로 증가했다. 최종 `1022_홍천`, `1031_양평`, `1105_용인`, `1107_강화`, `1111_철원`을 모두 생성·연결했고, 새 원본까지 정기 읽기 대상이다. Google 원본3개/장부항목70(아슬란65+안드레5)·운영 수입 요약5개 조회 PASS. 보관 장부가 없어 안드레 마감은 미상이며 금융/환급 완료를 추정하지 않는다.
- 검증: 같은 원본으로 기존/신규 파서를 비교해 아슬란65개 금액·기간·마감·원본 차이0. 별도 SQLite 사본의 전체 snapshot import에서 신규5·기존61·기존 근거 보류1, 기존 여행 행 변화0·재실행 신규0. 표적 원본/ADC·동명/연도 분리·수동 교정·매핑·참가자/보험 참조·지출 보호 통과. 통합 UI59 passed/2 subtests, 최종 PR448 포함28 passed/2 subtests, 저장/UI 보호34 passed/8 subtests, 지출 보호33 passed, 참조15 passed, 매핑26 passed이며 서로 중복되므로 합산하지 않는다. 기존 안내 문구1개·폐기 Google 라우트23개/별도 변형6개의 실패는 기준 `f05f599d`에서 재현했고 통과로 세지 않았다.
- 배포: 1,213 Git blobs 불일치0·검증/병합 tree 동일·task/process SHA·단일 loopback listener·health/ready200·영향/보호 경로401·금융/수동 보호13표 불변. 직전 검증 `3d991339`와 task XML·Google 원본 generation·SQLite 복구 사본/격리 import 검증을 보존했다. 기존 서버를 정지한 동일 전환 안에서 snapshot/rows를 원자 게시하고 정상 startup writer만 신규 여행을 생성했다. 실패 시 이전 코드 기동 전에 원본 snapshot을 복원하도록 전환 훅을 검토했다. 신규 마이그레이션·금융 재처리 없이 전체 원본 백업/서버 복원 리허설은 반복하지 않았다.
- `WebLedger-GoogleAuthority`의 기존 실행·인증·트리거를 보존하고 코드만 같은 SHA로 고정했다. 실제 예약 작업 실행은 Ready/LastTaskResult0, 다음 정기 실행 유지. SourceRefresh 상태와 ParticipantSyncConfig 인수 보존. 실제 변경은 새 읽기 원본/snapshot·여행5개/자동 연결5개이며 Google 쓰기·카드 재분류·환불·원문 수정0이다.
- Luna medium과 ANUS Free Auto를 병렬 위임했다. ANUS 편집 오류는 취소 후 Luna로 인계했고 검증되지 않은 통과 주장은 사용하지 않았다. 최신 보험/수입 UI 후속 PR448도 함께 배포했다. 해당 담당자가 별도로 수행한 실제 인증 PC1440/모바일390 검색·초기화·목록/버튼 수락은 [보험·수입 UI 명세](specs/insurance-income-workflow-ux-20261101.md)에 기록한다. 안드레 자체의 검증은 실제 원본/운영 자료 조회와 합성 PC/모바일 필터이며 인증 운영 브라우저 검수·전체 회귀·실기기는 미실행이다.
- 근거: `C:/AX/cost/.local-archive/andre-ledger-20261101/`의 validation·same-input-acceptance·rehearsal/full-rehearsal·검사XML·release-audit/runtime-ready/deploy-evidence·source-activation/operating-read/google-task-status, 호스트 같은 SHA release/deploy evidence. 고객 원문/사본은 Git 제외 로컬에만 보존한다. 현 요청 미결·차단0. 이 후속 문서만으로 재배포·재시작하지 않는다.

## 2026-11-01 보험 명단 열 가독성·모바일 배치 개선 완료

- COMPLETE — 최신 사용자 스크린샷의 보험 명단 열 UIUX 개선. [PR #442](https://github.com/6Soo/cost/pull/442), 구현 `62f75767`·`02c6779f`, 운영 SHA `89f09d9b457167ed0cc028181bdb77914d00ba52`. 말줄임을 해제하고 연결 이름·인원은 기본 표시, 연결 근거·개별 해제는 펼침으로 정리했다. 모바일은 수입 행 아래에 보험 상태를 넓게 표시한다. 접힌 패널의 연결 선택과 해제 확인창이 보이지 않던 문제도 수정했다. 기존 API·CSRF·fingerprint·확인 절차와 실제 데이터는 유지한다.
- 검증: 배포와 동일 tree의 참가자/보험 검사18 passed. 병행 수입 전체행 변경을 포함한 작업본의 인접 검사50 passed는 별도 근거이며 해당 병행 변경은 이 PR에서 제외했다. 최초 인접49 pass/1 paging 실패는 병행 수정 중 발생했고 최신 작업본에서 해소됐다. 합성 실제 ego-browser 320/390/844/1440, 밝은/어두운 테마·동작 줄이기·연결 근거 펼침·해제 취소·접힌 패널에서 연결 선택 통과. 보험 영역 기본57px·조작44px 이상·페이지 가로 넘침0. Aside 실행 파일 부재로 ego-browser를 사용했다. 전체 회귀·실기기는 미실행이다.
- 운영: 인증된 PC1440/모바일390에서 보험 상태20행·연결 펼침10행·버튼44px·문구 줄바꿈·페이지 가로 넘침0 확인(GET만). 검수/병합tree 동일·1,208 blobs 불일치0·task/process 고정SHA·단일loopback listener·health/ready200·영향/보호8경로401·보호13표 내용/스키마 불변·SourceRefresh 상태 보존. 금융/명단/Google/원본/스키마 쓰기0. 코드만 전환했으므로 전체DB 백업/복원은 반복하지 않았고 이전 검증 f05f599d와 task XML 복구점을 보존했다.
- 근거 `.local-archive/insurance-cell-ux-20261101/`의 exact-final.xml·targeted-final.xml·browser-evidence.json·live-browser.json·review.json·protection-before/after.json·deploy-evidence.json 및 호스트 동일SHA release/deploy audit. 이번 UI 요청 미결·차단0, 다음 명령 없음. 수입 전체행 병행 변경과 기존 미추적 파일·stash는 보존한다. 이 완료 기록은 문서 전용으로 재검사·재배포·서버 재시작하지 않는다.

## 2026-11-01 카드 4850 이름 표기 교정

- COMPLETE — 사용자 최신 교정에 따라 4850은 `•••• 4850 김동언`으로 표시한다. ‘대장’은 카테고리이며 이름에 붙이지 않는다. 카드사·끝자리 기준 국내/해외 통합 조회는 유지하고 카테고리·금융 자료는 쓰지 않았다. [PR #439](https://github.com/6Soo/cost/pull/439), 구현 `684e00de`, 운영 SHA `5ba6955a9f2f72488e3996e07e39a15798a95a47`.
- 기존 통합 조회 합성 검사 1 passed, 운영 Python 배포본의 표시명·통합 필터·페이지 이동·원본 불변 smoke PASS. 1,206 Git blobs 불일치0, task/process SHA·단일 loopback listener·health/ready200·카드/OTA 보호 경로401·보호13표 불변·ParticipantDb 인수/수집 작업 상태 보존. 이전 검증 `eb1c408c`와 task 복구본 보존. 코드 전용 교체로 전체 데이터 백업/복원·전체 회귀·인증 운영 브라우저 검수는 수행하지 않았다. 근거 `.local-archive/card-label-correction-20261101/`. 남은 작업·차단 없음. 후속 문서 변경만으로 재배포하지 않는다.


## 2026-11-01 보험 수신기·웹 참가자 DB 경로 고정

- DEPLOYED — [PR #433](https://github.com/6Soo/cost/pull/433), 검수 `8adeae963289e137e59a6a580ebd4f1296fdb85d`와 운영 `f52e019ad145eb0f7aaa21fde5ebb6d0c74fd958` tree 동일. 이전 검증 운영 `9e0ff03c464e98373b5cd591a19a3885fcf9ccf4`에서 전환했다. 예약 작업의 `-ParticipantDb`로 기존 수신 DB를 지정해 release별 빈 기본 경로를 읽던 문제를 복구했다. 경로는 다음 SHA 교체와 자식 재시작에도 유지된다.
- host63 passed/23 subtests·참가자12 passed·PS parse/data guard PASS. 1,202 blobs 일치·task/processSHA·단일loopback listener·health/ready200·참가자 및 기존 보호API401. 금융 보호13표·참가자8표 전후 동일. 실제 금융/원본/참가자/Google/스키마 쓰기0, 새 전체DB 백업/복원 없음, 이전 릴리스와 task XML 복구점 보존.
- 인증 운영 조회 `0630_오제`31명·`1030_닛코`7명 configured=true, 여행 화면 명단 펼침 loaded=true·오류 없음. autoLoad=0인 화면을 자동 로딩으로 기다렸던 첫30초 timeout은 펼침 동작 후 해소했다. 기존 수입 연결을 보존했으며 명단 표시와 수입 수동 연결·보험사 가입 확인은 구분한다. 수신기/SourceRefresh Running. 전체 회귀·실기기는 미실행.
- 근거: `C:/AX/cost/.local-archive/continuation-20261101/`의 review·검사XML·production-after·participant/protection-before/after·deploy-evidence, 호스트 동일SHA release-audit/deploy-evidence. 현재 명단 연결 작업 미결0. 문서 후속만으로 재배포·재시작하지 않는다.

## 2026-11-01 전체 업무 UX 감사·개선 완료

- COMPLETE — 현재 사용자 요청의 UX01~UX10. [감사·업무 목적·전후 비교](specs/full-ux-audit-20261101.md), [124개 경로/206개 핸들러](specs/full-ux-route-inventory-20261101.md). [PR429](https://github.com/6Soo/cost/pull/429)·[PR430](https://github.com/6Soo/cost/pull/430)·[PR431](https://github.com/6Soo/cost/pull/431), 최종 운영 `9e0ff03c464e98373b5cd591a19a3885fcf9ccf4`. 여행 맥락 전달·검색/상태 조건·개별 편집 접기·영수증 묶기/해제·빈 버튼 잠금·출력 선택 도구·중복 홈/헤더/카드 설명·규칙 화면 복귀·404 Google 링크를 정리했다.
- 실제 동일 합성 시나리오의 영수증 진입2→1조작(여행 재선택1→0), 현재 여행 하나의 출력 준비3→1조작. 각각 화면 이동은1→1이다. `/review`의 기존 지출 정리 통합을 유지하고 원본/예약/명단/권한 조회는 근거 확인 목적이 있어 유지했다.
- 검사38 passed/9 subtests·영수증 보호5 passed·후속shell11 passed·Google 라우트회귀1 passed. 기존 보호91 passed/1 failed는 기준본에서도 동일 재현했고 통과로 세지 않았다. 최초142개 검사와 기준 재현의 기존 영수증 계약/화면 실패는 상세 문서에 남겼다. 전체 회귀·실기기는 미실행이다.
- 실제 ego-browser PC1440/모바일390에서 여행 검색·무결과·URL 유지, 합성 영수증 직접입력/묶기→복사→해제, 모바일 수기지출 저장→같은 여행 복귀를 확인했다. 운영 읽기 전용으로 영수증 여행선택/복귀·관리의현재여행·출력단일선택/선택0잠금·수기선택·항공권무결과와 보조 메뉴를 확인했다. 운영 저장·권한승인·명단연결·AI 전송·Google 쓰기0.
- 배포1,202 Git blobs 불일치0·검수/병합tree동일·task/process 고정SHA·단일loopback listener·health/ready200·기존 보호경로 및 영향7경로401·보호13표 내용/스키마 불변, 두 task Running. 코드 전용 전환으로 새 전체DB 백업/복원은 반복하지 않았고55e2612/76f33ab8 릴리스와 task XML 복구점을 보존했다. 실제 금융/분류/여행/원본/Google/스키마 쓰기0.
- 초기76f33ab8은 설정과 제거된 라우트를 혼동한 Google 링크 때문에 UX08 운영스모크에 실패했다. PR431에서 라우트 확인을 보강한 최종9e0ff03c로 수락했다. 첫 출력 로딩은 브라우저 기본15초 제한을 넘겼으나 로드완료를 확인하고 후속 흐름을 통과했다. 첫 추가 비인증 요청의 일시 시간초과는 별도 재확인에서 health/ready200·영향7경로401로 해소했다. 이를 새 성능 개선이나 첫 시도의 통과로 꾸미지 않는다.
- 근거: `C:/AX/cost/.local-archive/full-ux-audit-20261101/`의 검사XML·baseline비교·interaction-comparison·responsive/receipt/manual/trip-context/live-after-browser·affected-auth-smoke·review·protection-before/after·deploy-evidence, 호스트 동일SHA release/deploy audit. 고객 원문/실명 캡처는 Git 제외 로컬에만 보존한다. 현재 승인 범위 미결·차단0, 다음 명령 없음. 기존 `C:/AX/cost`의 사용자 변경은 보존했다. 이 후속은 문서 전용이므로 코드검사·재배포·재시작하지 않는다.

## 2026-10-31 PR #427 중복 여행 자동분류 메뉴·문구 제거

- [PR #427](https://github.com/6Soo/cost/pull/427), 운영 `55e2612fc3c0a5e5229f59b31858219d5de12838`. `/import`의 카드 검토와 중복되는 여행 자동분류 메뉴와 완료 설명을 제거했다. 저장/규칙 적용 메시지와 여행 없음 근거를 줄였으며 보호 API와 거래별 근거·보류 상태는 유지한다.
- 관련50개 통과. 화면 회귀9개는 수정 전 `6ac4af43`에서도 재현한 기존 실패이며 통과로 세지 않았다. 독립 컴포넌트 브라우저 검사에서 CSRF 전달을 복구해 재검증했다. 전체 회귀·운영 owner 브라우저·실기기 미실행.
- 검수/병합 tree 동일·1,199 blobs 불일치0·task/process SHA·단일loopback listener·health/ready200·`/import`/카드/장부/예약/OTA/환불 보호경로401·보호13표 불변. 코드 전환만 수행해 별도 DB 백업/복원과 실제 금융/분류/여행/Google/원본 쓰기0. 이전 검증 `d2b4394634f9eab85c356291e909509560dac9eb`와 task XML 복구점을 보존했다.
- 근거: `.local-archive/copy-cleanup-continuation-20261031/`의 review·검사·baseline 비교·protection-before/after·deploy-evidence와 호스트 동일 SHA release-audit/deploy-evidence. 이 문서 후속으로 재배포·재시작하지 않는다.

## 2026-10-31 PR #424 Google 지출 비교·수기 추가 모달 배포

- 운영 고정 `d2b4394634f9eab85c356291e909509560dac9eb`, [PR #424](https://github.com/6Soo/cost/pull/424). 합계 수식 오류와 개별 행 비교를 분리하되 완전한 정수 원화 행·snapshot 행 합계 일치를 요구한다. 실제 readonly 대조49여행 가능/합계경고2/비표준12/DB changes0. strict export·권한·금융 보호는 유지한다.
- 수기 추가는 현재 여행의 native dialog, 오류 입력 유지·중복 제출 차단·Escape/닫기/포커스 복원·저장 후 새로고침. 모달 browser1 passed/2폭 subtests, 비교 통합37·최종사유14·export22·경고5·권한9·수기보호2 passed는 중복되는 실행이며 합산 회귀가 아니다.
- 1199 Git blobs 일치·task/processSHA·listener1·health/ready200·보호 API와 영향 경로 비인증401·보호13표 불변·두 task Running. 호스트 Python 합성 모달·선택여행·음수저장·동일 요청 재전송 PASS. 이전 검증 `05d09ce6c0791d7d5ea66414b6def94dcac8109a`와 task XML 보존, CODE_ONLY_NO_DATA_WRITES로 새 전체 백업/복원은 생략했다. 운영 금융/Google/원본/스키마 쓰기0. 실제 owner의 배포 후 모달 저장·전체 회귀는 미실행이다.
- 근거: `.local-archive/deploy-d2b4394634f9eab85c356291e909509560dac9eb/`의 review/protection-before/protection-after/deploy-evidence/affected-path-smoke/auth-smoke와 호스트 같은SHA release-audit/deploy-evidence. 현 요청 미결0이며 문서 후속만으로 재배포하지 않는다.

## 2026-10-31 웹 안내 문구 정리 배포

- COMPLETE — [PR #420](https://github.com/6Soo/cost/pull/420)·[PR #423](https://github.com/6Soo/cost/pull/423), 구현 `f9ef9f3`·`1e79213`, 배포 `05d09ce6c0791d7d5ea66414b6def94dcac8109a`. 장부의 “기록된 거래”·수입 계산식과 카드/수입/사이드바/예약 연결/여행 검토/항공권의 반복 설명을 제거했다. 실제 오류·금액·원본 링크·조작·접근성 설명은 유지한다.
- 통합 금액/필터/수입/자산/지출 중복75 passed·3 subtests, 모바일/장부/예약 연결 browser16 passed·6 subtests, 최종 통합 장부2 passed·4 subtests, 추가 여행/항공권28 passed 및 문구 assertion 교정 후1 passed. 실행 간 중복을 합산하지 않는다. 기준본 재현 카드 성능 시간 하한1실패는 별도 보존. 전체 회귀·전체 인증 운영 화면·실기기는 미실행.
- 1,198 blobs 불일치0·검사본/배포본 코드 동일(문서만 차이)·task/process SHA·단일 loopback listener·health/ready200·보호 API/영향 화면401·보호13표 불변·호스트 Python 합성 smoke PASS. 이전 검증18978698과 task XML 복구점 보존, 코드 전용이므로 새 전체DB 백업/복원은 반복하지 않았다. 금융/분류/여행/Google/원본/스키마 쓰기0. 동시 작업자와 직렬화했으며 배포 종료 통지 완료.
- 근거: `.local-archive/copy-cleanup-20261031/` 및 `D:/WebLedgerHost/releases/deploy-evidence-05d09ce6c0791d7d5ea66414b6def94dcac8109a.json`. 현재 요청 미결·차단0. 이 문서 후속 병합에는 재배포하지 않는다.

## 2026-10-31 수기지출 중복대조 메뉴를 여행 지출표로 통합

- COMPLETE — 사용자 “수기지출중복대조 이게 대체 뭘 하라는 메뉴인데? 왜 존재해야해?” 및 “진행해”에 따라 별도 화면/메뉴를 제거했다. [PR419](https://github.com/6Soo/cost/pull/419), 구현 `03c9ea06`, 배포 SHA `1897869876a210b2b859afb6546de97bbaa83ddc`.
- 여행 지출표의 각 행에 장부에 있음·복사 가능·중복 확인 필요를 표시하고 기존 복사 버튼에 복사 가능 건수/금액·제외 건수를 통합했다. 장부에 있는 거래/중복 후보/기존 보류는 복사에서 제외한다. Google 비교 실패 시 행별 비교 불가 표시를 반복하지 않고 표 아래 안내 한 곳과 비활성 복사 버튼으로 표시한다. 기존 대조 URL은 여행/검색 조건을 보존해 지출표 복사 영역으로 이동한다. 최신 원본 재검증·수동 연결·owner/CSRF·Google 최종 장부 쓰기 금지는 유지한다.
- 검증: 표적 UI/API/통합68 passed, 중복/연결 보호41 passed. 동시 병합 PR418 국내/해외 규칙을 포함한 최종 배포본 관련54 passed. 중복 실행을 합산하지 않는다. 모바일320/390/760/1280·두 테마·상태표시·원본불변·escaping 포함. 전체 회귀/실기기는 미실행이다.
- 배포:1198 Git blobs 일치·task/process 고정SHA·단일loopback listener·health/ready200·보호API401·보호13표 내용/스키마 불변 PASS. 직전 검증25cc2910 릴리스/task XML 복구점을 보존했다. 코드 전용 전환으로 새 전체DB 백업/복원은 반복하지 않았으며 실제 금융/분류/여행/원본/Google/스키마 쓰기0이다.
- 실제 인증 ego-browser 여행 화면에서 별도 대조 링크0·복사 영역1·가로넘침 없음·예전주소 이동을 확인했다. 해당 여행의 Google 비교 자료는 사용 불가여서 통합 안내1개와 복사 잠금을 확인했다. 실제 자료의 정상 비교/복사 성공을 확인한 것으로 꾸미지 않으며, 자료 무결성 문제 수정은 별도 담당 범위다. 브라우저 TaskSpace22는 종료했다.
- 근거: `C:/AX/cost/.local-archive/expense-dedup-integrated-20261031/`의 targeted/protection/merged XML·live-smoke·checkpoint와 `C:/AX/cost/.local-archive/deploy-1897869876a210b2b859afb6546de97bbaa83ddc/` 및 호스트 동일SHA release/deploy evidence. 기존 사용자 workspace 변경은 보존했다. 이번 메뉴 통합의 남은 작업/차단0, 다음 명령 없음. 후속 문서만으로 재검사·재배포·재시작하지 않는다.

## 2026-10-31 전액 환불 완료와 나머지 입력 요청 분리

- [PR416](https://github.com/6Soo/cost/pull/416), 운영 `8ebb4d8b495631e18d8c2d5b37a10c12e8257082`, 이전 검증5cab519d 복구점 보존. 실제 환불쌍2건은 이미 기기록이며 아래 입력요청11건은 별개임을 인증 GET으로 확인했다. 완료된 전액 상쇄만 별도 완료 카드와 추가 입력 없음으로 표시하고 비용/여행/비활성 기록 버튼과 일반 표 중복을 제거했다. 부분/보류/미기록은 유지한다.
- 합성390/1440·4사례 및 병합본 같은4사례 통과(중복 합산하지 않음), 환불 연결/기록 보호36 passed.1196 blobs 불일치0·고정task/processSHA·단일listener·health/ready200·보호API401·보호13표 불변 PASS. 코드만 바꿔 이전 검증 릴리스/task XML 복구를 사용하고 전체백업/복원은 반복하지 않았다. 실제 금융/분류/연결/명단/Google/스키마 쓰기0.
- 실제 ego-browser 완료 환불1묶음·추가 입력 없음·그 외11행/별도수정11건·넘침 없음 확인. 근거 `C:/AX/cost/.local-archive/zero-refund-review-20261031/`, `deploy-8ebb4d8b495631e18d8c2d5b37a10c12e8257082/`와 호스트 동일SHA deploy-evidence. 전체회귀/실기기 미실행, 문서 후속 재배포 없음.

## 2026-10-31 검토 상태 조치·조회 재시도 UX 배포

- [PR414](https://github.com/6Soo/cost/pull/414)·운영 `5cab519de4a7993017b787ad7bfa6d9d5546072c`, 검증 `e4a3869b27114fc1533316c9b61f414cbfab3e9f`와 tree 동일. [조사 범위](specs/actionable-review-ux-audit-20261031.md)의 카드 거래별 수정·OTA/항공권 재시도·여행/참가자 자료 확인 동선을 배포했다.
- 카드/모바일/읽기79 passed, 인접141 passed와 발견한 여행 화면 import 오류1건 수정 후 새 동작/권한7 passed, 환불·분류44 passed. 검사 간 중복을 합산하지 않는다. compile/diff/data guard·Ego 합성 표시·호스트 모듈 smoke PASS. 전체 회귀/운영 owner 전 화면/실기기 미실행.
- 1195 Git blobs 불일치0, task/process 고정SHA·단일loopback listener·health/ready200·영향 화면/보호API401·보호13표 전후 내용/스키마 불변. SourceRefresh 상태 유지. 이전 검증29ecb215 릴리스·작업 XML 보존, 코드 전용 전환으로 새 전체 데이터 백업/복원은 반복하지 않았다. 금융/원본/분류/여행/환불/명단/Google 쓰기와 migration0.
- 근거 `C:/AX/cost/.local-archive/actionable-ux-20261031/` 및 `D:/WebLedgerHost/releases/deploy-evidence-5cab519de4a7993017b787ad7bfa6d9d5546072c.json`, 동일SHA release-audit. 후속 문서 전용 병합으로 재검사·재배포·재시작하지 않는다.

## 2026-10-31 예약 명단·여행 연결 UX 배포

- [PR412](https://github.com/6Soo/cost/pull/412), 운영 `29ecb215d63169e913e7f14a4959587436b68586`; 검증31b0f4cb와 tree 동일. 이름/여행명·검색·필터·10건 페이지·전체 연결 해제·저장 전 취소를 추가했다. main 밖에서 이미 운영 중이던74325e69의 로딩/업로드 수정도 정상 merge로 보존했다. 최초 이전SHA 게이트 거부는 실제 전환으로 세지 않는다. 실제 직전 검증18f3e747을 복구점으로 사용했다.
- 1193 blobs 불일치0, task/process 고정SHA·단일loopback listener·health/ready200·보호API401·보호13표 내용/스키마 불변 PASS. 코드만 변경해 기존 검증 릴리스·task XML로 복구하고 새 전체백업/복원은 반복하지 않았다. 금융/연결/명단/Google/스키마 쓰기0.
- 표적 화면36/38subtests·보호65/26subtests·통합6 통과. 추가 넓은 인접 검사는 중단·실패로 남겼으며 첫 실패는 기존74325e69에서도 재현했다. 상세 범위·미실행은 현재 상태 참조. 실제 인증 ego-browser `/reserve-links`에서 이름100행·가시10행·검색 무결과·2/10 페이지·넘침 없음 확인, 운영 저장/적용0. 근거 `C:/AX/cost/.local-archive/reserve-link-ux-20261031/`, `deploy-29ecb215d63169e913e7f14a4959587436b68586/` 및 호스트 동일SHA evidence. 문서 후속은 재배포하지 않는다.

## 2026-10-31 보험 후보·여행 검토 UX 운영 수락

- [PR409](https://github.com/6Soo/cost/pull/409), 검증 `db789b6cfa079dbce3cd29f848b1ca855f42d4e6`, 운영 `1ecd2aa00d09f8bee7d9af7f09802cd506870c5c`, tree 동일. [실행 계약](specs/insurance-trip-review-ux-20261031.md): 명단 로딩/재시도·행별 후보 비교·여행별 작업3개와 전체 도구4개. 관련64/최종JS43/수동 버튼1검사 통과(중복 실행 합산 금지).
- 1190 blobs 일치·task/process SHA·단일 listener·health/ready200·보호API401·보호13표 내용/스키마 불변. 직전 검증b99d01a7 릴리스/task 복구 보존, 읽기 전용 코드 변경으로 신규 전체 백업/복원 없음. 금융/명단/원본/Google 쓰기·마이그레이션·스케줄 변경0.
- 기존 로그인 Ego 실화면 첫20/20·다음12/12 상태,14개 후보 버튼·후보2행 비교·동일 근거·포커스 복귀, 여행 작업3개·접힌 전체 도구·명단 쓰기form0 확인. 최초 포인터 초기포커스 검사는 BODY 관찰로 실패했고, 후속 키보드 진입의 닫기 초기포커스·Tab·Escape/닫기·복귀 검사를 별도로 통과했다. 원래 실패 기록 보존. Ego 공간10 finish 완료. 전체 회귀/실기기 미실행. 실제 확정 명단/등록 증빙 대기 유지.
- 근거 `C:/AX/cost/.local-archive/insurance-actionable-20261031/`와 `.local-archive/deploy-1ecd2aa00d09f8bee7d9af7f09802cd506870c5c/`. 후속 명세/상태 문서만 병합하며 코드 재검사·재배포·서버 재시작하지 않는다.

## 2026-10-31 PR405/406/407 insurance integration and panel recovery

- Existing masked review data now appears in trip-income cells and an inline contract-history panel even when the confirmed participant DB is absent. Compatible root markup fixes the generic loading error; confirmed manual links, canonical generation checks, trip scope and bounded-candidate uncertainty are preserved. Duplicate footer navigation is consolidated into the inline panel.
- PR405 first deployed480e9ca6, PR406 generation guard deployed817b6178, and PR407 final pagination correction deployed `b99d01a78d96e28352657c47f0a3030bba18832e`. Final tested54e9d04f/merged trees identical. Authenticated817b6178 QA exposed13/20 populated cells; final deployed source-backed render covers20/20 and12/12, database changes0 and no write forms. Final authenticated browser not repeated; synthetic browser and actual rendering evidence remain distinct.
- Test phases60/25/8/17 plus isolated manual-link check pass, overlap not summed. Four pre-existing income-badge subfailures reproduced on baseline1f3729c0; transient browser/test-call errors corrected/rechecked separately.1190 blobs match, fixed task/processSHA, listener1, health/ready200, protected participant and other APIs401,13 protected tables unchanged. Verified prior817b6178 code/task rollback preserved; no repeated full backup/restore for read-only code/UI changes.
- Evidence `.local-archive/insurance-panel-integration-20261031/` and `.local-archive/deploy-b99d01a78d96e28352657c47f0a3030bba18832e/`; host `D:/WebLedgerHost/releases/deploy-evidence-b99d01a78d96e28352657c47f0a3030bba18832e.json`. No financial/source/participant/Google writes, new registrations, migration, downloads or scheduler changes. Text matches/candidates do not establish identity, active insurance or payment receipt. See [current status](session_handoff.md).

## 2026-10-31 PR403 trip review icon-card design

- [PR403](https://github.com/6Soo/cost/pull/403) normal merge; testedc0326bf8 and runtime `6c4bb1cfbb08938dbe706f6d94c95e556e90bb42` trees match. Scoped markup/CSS adds summary and seven link icons, complete clickable cards, responsive3/2/1 layout and theme/focus/motion handling; existing links and source-derived review facts unchanged.
- 12 targeted tests passed; synthetic desktop/mobile light/dark visuals,320px200% no overflow, seven icons and keyboard toggle accepted. Ego task finished. Authenticated owner-page/physical-device acceptance was not repeated.1189 blobs match, task/process SHA, listener1, health/ready200, protectedAPI/affected-page401 and13 protected financial tables unchanged. Prior verifiedf98e401f release/task rollback remains available; no new full data backup/restore for reversible UI-only deployment.
- Evidence `.local-archive/trip-review-design-20261031/` and `.local-archive/deploy-6c4bb1cfbb08938dbe706f6d94c95e556e90bb42/`; host sameSHA release audit/deploy evidence. No financial/source/participant/Google data, schema or scheduler writes. Insurance integration diagnosis is recorded separately in [current status](session_handoff.md), not claimed as fixed by this design change.

## 2026-10-30 PR400 card phase metrics and protected diagnostics

- [PR400](https://github.com/6Soo/cost/pull/400) merged normally. Tested `208eb6faa122c0b3929e22f6369f758986d6fada` and runtime `f98e401fe9b2777e93c6342293d287af4b12804b` trees match. Existing request metrics now separate card connection/query/labels/render stages and expose bounded aggregate diagnostics to the owner. Data-load timings include connection/materialization and are not additive SQLite CPU timings.
- 6 focused,126 adjacent and24 telemetry/isolated first-render tests passed (overlap; no full-regression claim). Output/database byte equivalence and anonymous/staff/owner HTTP protection verified. Deployment1189 blobs match, fixed task/process SHA, listener1, health/ready200, protected APIs401 and13 protected tables unchanged. Previous verified1ce4fe6d release/task rollback preserved; no new full data backup/restore for this reversible code-only change.
- Existing authenticated Aside session observed3 card GETs200 and aggregate GET200/no-store;10 aggregate stage groups recorded. Anonymous aggregate endpoint401; staff403 covered by actual synthetic HTTP tests. The samples establish working instrumentation, not representative performance SLA or real-device acceptance. Source/input/manual-paste acceptance gates remain independent of implementation completion.
- Evidence `.local-archive/core-workflow-20261030/stage-*.xml`, code-gap-review.json and `.local-archive/deploy-f98e401fe9b2777e93c6342293d287af4b12804b/`; host `D:/WebLedgerHost/releases/deploy-evidence-f98e401fe9b2777e93c6342293d287af4b12804b.json`. No financial/roster/source/Google writes, card collection/upload, new billing or scheduler changes. See [current status](session_handoff.md) for the eight-item code/acceptance distinction and recheck conditions.

## 2026-10-30 PR398 archived-trip comparison and Google reader cutover

- [PR398](https://github.com/6Soo/cost/pull/398) merged normally; tested `f847dcf3ce3f2d1095c07641871f65cc8ee49766` and runtime `1ce4fe6dbe645c8e788b45e89b067cb15cb18bc3` trees match. Read-only M:N trip lookup includes archived trips while default review/write lookup scope is preserved.
- 21 focused and35 adjacent protection tests passed.1188 release blobs match; task/process SHA, single loopback listener, health/ready200, protected APIs and affected trip page401,13 protected table contents/schema unchanged. Prior verified58cfa0aa release and task XML provide code rollback. No full data backup/restore was repeated for this reversible code-only change; no data/schema/Google writes.
- Separately approved Google reader switch was already executed successfully:4b4d10fb to58cfa0aa, task result0, both sources normal at16:55:17+09:00, execution times/authentication/settings unchanged. Board deployment does not change that independent action.
- Full recovered audit remains47/62 comparable.12 layout issues,2 formula/total issues and1 archived COST trip absent from current Google source remain unavailable. Actual deployed lookup now reaches GOOGLE_TRIP_UNAVAILABLE instead of incorrectly rejecting its COST archive state. Archive unchanged, database changes0; no false matched result was introduced.
- Local evidence: `.local-archive/core-workflow-20261030/` and `.local-archive/deploy-1ce4fe6dbe645c8e788b45e89b067cb15cb18bc3/`; host evidence `D:/WebLedgerHost/releases/deploy-evidence-1ce4fe6dbe645c8e788b45e89b067cb15cb18bc3.json`. Remaining external gates and exact recheck conditions are in [current status](session_handoff.md). No new card collection or financial/participant/source writes.

## 2026-10-30 16:43 Google comparison incident recovery

- User reported all Google expense comparisons unavailable. Same actual source reproduced SOURCE_NOT_VERIFIED on both prior d0d73f8a and deployed58cfa0aa. Cause was the16:00 main-reader SOURCE_UNREACHABLE, not demonstrated code regression.
- Retried the existing scheduled readonly reader ONCE after its normal backoff expired; task result0, both main/archive normal with last_ok_at2026-10-30T16:43:03.212344+09:00. Schedule/runner unchanged. This supersedes the earlier current-failure observation, but does not activate PR395 generation optimization in the old scheduled runner.
- Authenticated actual recovered trip GET200:35 matched cells and0 unavailable. Another currently viewed trip remains unavailable for a REAL source formula gap: H47:H75 excludes amount row76; directly inspected workbook in memory, cached total differs from all expense rows. No Google source edit or validation bypass. Another trip has LAYOUT_NOT_STANDARD. These individual source issues must not be reported as an ongoing global outage.
- Evidence `.local-archive/core-workflow-20261030/google-recovery.json` and `sheet-range-diagnostic.json`; original values/names were not logged. No financial/roster/Google writes, server restart or redeploy. User edits the Google source formula/format, then the existing normal reader must refresh before rechecking those specific trips.


## 2026-10-30 CORE PR394/395 implementation and verified deployment

- Approved specification [PR394](https://github.com/6Soo/cost/pull/394) and implementation [PR395](https://github.com/6Soo/cost/pull/395) merged normally. Tested commit `6387b915deb22dc55cdefd45feac3e0415863163`, runtime SHA `58cfa0aa0949a1ad2d83ad691a64c9d7abae5b5e`; tested and merged trees identical.
- Existing trip page now has a collapsed review disclosure with seven existing navigation paths: card sources, holds, OTA/refunds, receipts, Google manual review, closure and insurance. Closure requires current archive evidence; unknown sources stay unknown. No new matcher, stored workflow state or Google writes.
- Google unchanged private rows reuse their generation while checked timestamps advance; previous distinct generation remains available for inflight readers. Per-request source reuse supports the existing GEMN audit; OTA coverage reuses existing provider policy scope. The scheduled Google reader is STILL pinned to old4b4d10fb with latest result1. No schedule switch or forced sync was executed; activation and actual recovery require the separate schedule gate.
- Targeted evidence: core34696 passed, workflow/receipt18 passed, protection134 passed, copy/trace84 passed, alias/refund84 passed, workflow-final12 passed. Counts overlap and must not be summed. Four obsolete copy fixtures and one alias fixture also failed on baseline; synthetic inputs were corrected to use canonical source/current matching rules without weakening financial protection. Full regression and physical Safari/Android acceptance were not run.
- Actual readonly evidence: eight import source blobs with no fingerprint mismatch;62 actual trips,47 comparable/15 unavailable and DB changes0. OTA audit3914 events,228 MATCHED_AUTO/3 MATCHED_USER are observed existing decisions; new approvals/owner-decision changes0. Between the two audits source events increased3909 to3914 and NOT_CARD_CHARGE1107 to1112; these are NOT same-input equivalence/performance evidence. Scoped audit took590.842sec; scoped/unscoped equivalence and fewer resolver calls were verified using identical synthetic input. Participant DB and actual receipt store remain absent.
- Deployment:1188 tracked blobs match; fixed task/process SHA, one loopback listener, health/ready200, protected APIs401,13 protected financial tables unchanged. Reversible code-only deployment used previous verified d0d73f8a release/task XML rollback; no new full backup/restore rehearsal was claimed. No financial/roster/source/Google writes, migrations or schedule cutover.
- Existing authenticated Aside trip page accepted: initially collapsed, expands to7 links, write forms0, no page overflow, real unavailable/unknown closure states and correct Google manual-review link. Five authenticated cards/all GETs all200:1527-2042ms, median1742ms. This includes network and is not production p95, internal phase or physical-device acceptance. ADB devices0.
- Evidence: `.local-archive/core-workflow-20261030/` XML, aggregate JSON, queue/checkpoint; `.local-archive/deploy-58cfa0aa0949a1ad2d83ad691a64c9d7abae5b5e/` and host deploy evidence. User pause on card collection/upload remains. Real Google manual paste, source payment proof, roster/registration receipt, actual receipt images and physical devices remain external gates. Verified artifacts are preserved before official temporary workspace archive; actual cleanup is recorded in final.json. Documentation-only followup does not trigger redeployment.


## 2026-10-30 PR382 마스킹 보험 이름·기존 수입 글자 대조 배포

- [PR #382](https://github.com/6Soo/cost/pull/382) 정상 병합, 운영 SHA `6338146ecfd0f48cd89aafb61c63f46a07e94f25`, 이전 검증 `c9336e978eca8ec60f8dccac50284700744f1eab` 복구점 보존. 소유자 GET 화면/API와 같은 세대의 Google 수입 원행을 연결하고, 별도 이름 인덱스 없는 자료도 대조한다.159행의 결과는 단일 후보41·복수 후보20·일치 없음98이며 신원/등록/가입/실제 입금 확정과 구별한다.
- 검증84 passed(실제 HTTP 권한/GET-only/no-store/오류 상태·후보 충돌·원본 fallback·필터·세대·Chromium320/390/760/1280·설정 경계). 검수/merge tree 동일·1,167 blobs 일치·새 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·보호API401·보호13표 불변. Board/SourceRefresh Running. 기존 Aside 로그인 탭에서 실제 화면 요약과 API200/OK/no-store 확인.
- 로컬 명단 manifest 연결만 launcher/card-flow 설정으로 활성화하고 변경 전 설정을 배포 근거에 보존했다. 원본 PDF/사진은 배포/Git/웹 응답에 넣지 않았다. 금융/참가자 DB/Google/원문 쓰기·재처리·마이그레이션0. 기존 외부 수락·카드 수집/업로드 중지는 유지한다.
- 근거: `C:/AX/cost/.local-archive/masked-income-match-20261030/targeted.xml`, `live-smoke.json`, `.local-archive/deploy-6338146ecfd0f48cd89aafb61c63f46a07e94f25/` 및 `D:/WebLedgerHost/releases/deploy-evidence-6338146ecfd0f48cd89aafb61c63f46a07e94f25.json`. 전체 회귀/실기기는 미실행이며 문서 후속으로 재배포하지 않는다.

## 2026-10-30 전체 미결 후속 PR380 고정 배포

- [PR #380](https://github.com/6Soo/cost/pull/380) 정상 병합·운영 SHA `c9336e978eca8ec60f8dccac50284700744f1eab`, 이전 검증 `dbead7d3b46e991f41a8ce6a39ff9bea8ae4c2e1`. 검수/병합 tree 동일,1,159 blobs 불일치0·새 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·보호API401·보호13표 불변 PASS. Board/SourceRefresh Running. 금융 적용·명단 등록·원문 재처리·Google 쓰기0.
- 실제 확인: 참가자 인증 API200이나 configuredfalse/STORE_UNAVAILABLE, Drive readonly manifest3710/pending48/페이지·query진행중이므로 실제 참가자·메일 전환 수락은 미완료다. 원결제 증거·물리 모바일 기기·권한 유효 token/실사용 성능도 별도 수락이다. 실행 wrapper 절대 경로/서명과 제한된 broad SID ACE 확인을 전체 권한 보증으로 쓰지 않는다.
- 인증 카드 초기 GET1회27,432ms·합성 검색 GET1회1,412ms가 관측돼 별도 Luna low에게 후속을 배정했다. 실제6,395건 분리 결과 연결/등록1,593ms·연도 쿼리21.7/19.5ms·결과 동일, 환불 그룹 약462ms였다. 최초16초 연도 조회는 재현되지 않아 금융/날짜 의미와 캐시를 바꾸는 최적화는 하지 않았다. 단일 원격 수치를 backend render·p95·SLA로 표시하지 않는다. 근거는 root `.local-archive/remaining-acceptance-20261030/` 및 `D:/WebLedgerHost/releases/deploy-evidence-c9336e978eca8ec60f8dccac50284700744f1eab.json`이다. 문서만 바뀐 후속은 재배포·재시작하지 않는다.

## 2026-10-30 임시 브랜치 검토·병합·정리 및 운영 고정

- 사용자 “임시워크스페이스 및 브랜치 병합 및 정리 운영배포”, 후속 “보존하지말고 확인하고 병합해”에 따라 [PR #378](https://github.com/6Soo/cost/pull/378)로 검토된 이력을 main에 병합했다. 미병합으로 보이던45 refs/90 commits 중61개는 main과 stable patch가 같고29개는 후속 구현·최신 정책 대체를 확인했다. [검토 기록](branch-integration-audit-20261030.md)에 이유를 남겼으며, 현재 tree를 유지하는 명시적 `ours` 병합으로 중복·구형 로직을 되살리지 않았다. 별도 보관 브랜치 대신 병합 후 삭제했다.
- 요청된 운영 고정 SHA는 `dbead7d3b46e991f41a8ce6a39ff9bea8ae4c2e1`이며 이전 `10b95b802c879e83dd93d9030aa333f7f348cf38`을 복구 릴리스로 유지했다. 대상 코드가 이전 검증 본과 동일함을 확인하고 보호 검사108 passed를 재사용했다. 1,156 blobs 불일치0·새 백업/별도 복원·task/processSHA·health/ready200·보호API401·보호13표 전후 불변 PASS. 금융 적용·원문 재처리·Google 쓰기0.
- 완료된 별도 Git worktree3개를 정리했고 마지막 Paseo 통합 worktree는 운영 검증 기록을 주 작업 폴더로 이동한 뒤 공식 archive 절차로 닫는다. 원격은 main만, 로컬은 main과 미커밋 사용자 변경이 있는 기존 작업 브랜치만 남긴다. 사용자 변경과 stash는 원본 해시로 불변 확인했다. 근거: `C:/AX/cost/.local-archive/workspace-branch-cleanup-20261030/` 및 호스트 같은 SHA deploy-evidence. 이 기록의 문서 후속은 재배포 대상이 아니다.

## 2026-10-30 미결 구현·PR370 단계 통합 배포

- 정상 병합 PR #371~#375의 최종 운영 SHA는 `10b95b802c879e83dd93d9030aa333f7f348cf38`이다. 이전 검증 릴리스 `d09596d0242416af2889b4a0514abd0509c60561`을 보존했다. [현재 상태](session_handoff.md)와 [실행 인덱스](specs/all-pending-execution-20261030.md)에 구현·부분 수락을 구분했다.
- Git 고정 릴리스 1,154 blobs 불일치0, 새 운영 백업/별도 복원, task/process SHA 일치, 단일 loopback listener, health/ready200, 보호 API401, 보호13표 배포 전후 불변 PASS. `D:/WebLedgerHost/releases/deploy-evidence-10b95b802c879e83dd93d9030aa333f7f348cf38.json` 및 통합 worktree `.local-archive/all-pending-luna-20261030/deploy/`에 근거를 보관했다. Board/SourceRefresh 정상 복구. 금융 적용·원문 재처리·Google 쓰기는 실행하지 않았다.
- Aside 인증 `/cards/all`에서 단일 수동 테마·문서 가로 overflow 없음·내부 분류 코드 비노출을 확인했다. 참가자 상태 API200, configured=false/complete=false는 준비된 실제 명단 저장소가 없다는 미완료 근거다. 클라우드 manifest pending48/complete=false로 전환하지 않았다. 카드 다운로드/업로드 보류와 실제 금융/보험/실기기 수락 경계를 유지했다.
- 문서 후속은 재배포·DB 확인·서비스 재시작을 요구하지 않는다. 합성 query 감소 5→3회는 실제 운영 SLA가 아니며, R5 제품 삭제와 전면 컨트롤러 축소·문서 history 정리를 완료로 표시하지 않는다.

## 2026-10-30 숲나들e 정규 관측 적재·수집 코드 전환

- [PR #368](https://github.com/6Soo/cost/pull/368)을 정상 병합하고 `d09596d0242416af2889b4a0514abd0509c60561`을 고정 배포했다. 이전 검증 릴리스 `241cd452abd6c4da4ac59b4f3d534e4e4b2177a6`과 복구 사본을 보존한다. 코드 배포, 운영 관측 적재, MailCollect 전환을 별도 검증했다.
- 최종 표적 검사96 passed/2 subtests, 병합 tree 일치·1,140 blobs 불일치0. 새 전체 백업/별도 복원·task/process SHA·단일loopback·health/ready200·보호API401·보호13표 배포 전후 불변을 확인했다. 무관한 전체 회귀는 반복하지 않았다.
- 실제 원본 사본 리허설 후 운영 원본을 잠근 상태에서 새 백업·별도 복원과 전 표 digest 동등성을 검사하고 관측 표 추가/46행 append만 원자 적용했다. 원래 전 표·기존 관측 보존, 재실행 추가 쓰기0, 새 금융 링크0. 원문 번호 없는46건에 공급자 예약번호를 만들지 않았으며 원문은 그대로다.
- `WebLedger-MailCollect`가 idle임을 확인하고 일시 비활성화한 뒤 보호 작업을 직렬 실행했다. 실행파일/인수를 유지하고 WorkingDirectory만 위 고정 릴리스로 바꾼 후 기존 활성 상태를 복구했다. 실제 새 메일 수집을 수동 실행하지 않았다. SourceRefresh 경로 변경0. 카드 업로드는 사용자 지시로 계속 보류한다.
- 운영 읽기 수락: 정규 관측46·현재 일반 목록16(수집됨12/취소4)·과거30보존·가짜 공급자 번호0·조회 DB쓰기0. 수집 task XML의 트리거/권한/설정 동일. Aside owner 목록/API16개 고유 키·상세200·`원문 미제공`/종료일 미확인·내부 키 비노출을 확인했다. 목록 인덱스 ready. 중앙 카드/예약 대사는 generation505·ready/fresh·stale=false로 갱신 완료했다. 목록의 이전 대조 대기 경고는 새 대사 세대에 맞춰 인덱스가 갱신되는 동안의 캐시 표시이며 공급자 표기 오류7건 경고는 유지한다. 금융 대사의 추가 확정/Google 반영은 실행하지 않았다.
- 근거: root `.local-archive/forest-provider-audit-20261030/`의 final-targeted.xml·rehearsal.json·applied.json·mail-task-before/after.xml·mail-task-transition.json, `.local-archive/deploy-d09596d0242416af2889b4a0514abd0509c60561/` 및 호스트 같은 SHA deploy-evidence. 금융/장부/수동/여행·두 건의 기존 교정·Google쓰기금지를 보존했다. 후속 문서만으로 재배포/재시작하지 않는다.

## 2026-10-30 수기 Google 지출 중복 방지 배포·읽기 전용 수락

- COMPLETE — [PR #364](https://github.com/6Soo/cost/pull/364), 운영 SHA `241cd452abd6c4da4ac59b4f3d534e4e4b2177a6`. 여행/업로드 복사 전에 수기 지출 대조와 원자 연결·revision/멱등 재검증을 적용했다. 사용자 교정·원본/환불/카드/금액/통화·점유 보호를 유지하며 Google 최종 장부 자동 쓰기는 금지한다. 직전 검증 `bc02ea4a1fb15523e0fcfd9d92f9c5bed37d6b21`과 두 건의 운영 교정값 보존.
- 1137 blobs 불일치0·새 백업/별도 복원·작업/프로세스SHA·단일loopback listener·health/ready200·보호API401·보호13표 전후 불변. 새 대조 경로의 익명403을 확인했다. 운영 분류/금융/여행/연결 메타데이터/Google 쓰기0.
- 운영 읽기 전용61여행 중47개 원본 검증 가능·수기 연결 후보121건, 검증 불가14개 여행은 복사 보류. DB변경0·Google snapshot 불변. 실제 owner API200/원본검증불가503·요약5개·50행 페이지·320px overflow0을 Aside CLI로 확인했다. 자동 동일성 판정과 실제 연결 저장·Google 입력은 구분하며 운영 POST를 실행해 시험하지 않았다.
- 표적 검사 통합70/main47/최종 카드·여행·HTTP·복사JS8/UI21/replay1/matcher26 passed는 서로 중복된다. 인접91 passed/5 failed의 두 실패 유형은 기존 기준 `e149d82`에서 동일 재현했고 통과로 계산하지 않았다. metadata guard 차단0/삭제0, 구문·diff 통과. 전체 회귀·실제 Google 쓰기는 미실행이다.
- 근거: 통합 `.local-archive/open-pr-20261029/`와 호스트 동일SHA release-audit/deploy-evidence. 운영 작성권을 별도 숲나들e 작업자에게 해제 통보했다. 이후 완료 문서만으로 재배포·DB검사·재시작을 반복하지 않는다.

## 2026-10-29 카드 업로드 전수 대조 운영 수락·배포

- COMPLETE — 사용자 “모든 명세가 구현되었나? 되었다면 운영수락”에 따라 최신 main의 P2 변경을 통합·검증하고 [PR #355](https://github.com/6Soo/cost/pull/355)를 정상 병합했다. 운영 SHA `a69c0ae7389789a65d2ed01f3028c0348f52eb1f`, 직전 검증 릴리스 `3860a822efe3a6f2d6c1349e824b193ac7309a7b` 및 복구 사본 보존. [명세](specs/card-upload-full-reconciliation-20261029.md)의 CUV-01~07 구현·격리/운영 읽기 전용 수락 완료이며 실제 은행 환급·Google 반영 완료와 구분한다.
- 운영 원본 대조 중 정상 XLSX 2개의 빈칸 `-` 4,120개를 수식으로 오인하는 결함을 발견해 `19f9edb`에서 교정했다. 하이픈 placeholder/음수 숫자를 허용하고 `=`, `+`, `@`, `-CMD` 등 수식 차단·XLSX scan fail-closed를 유지한다. 최신 main 통합 검사117 passed/fixture 의존 실패1은 전역 store fixture 복원으로 수정했고 관련 결합8 passed, placeholder/원천 대조27 passed를 확인했다. 유효한 나머지 통과 근거는 반복하지 않았다.
- 실카드 검증은 운영 DB mode=ro → 격리 메모리 백업에서 원본8개를 사전검사·동일 파일 재대조했다. 원천 행6,929(E=6,929/N=0/H=0/P=0), 파일 오류0, 복사본 원본/분류/금융 표 불변, 운영 connection total_changes=0. 분류 C=6,026/U=903, 취소 원결제 경고R=112는 실제 데이터 상태이며 금융 완료로 승격하지 않는다. 파일 간 겹침을 포함한 원천 행 집계이므로 고유 거래 수로 보고하지 않는다. 실제 운영 재업로드 POST·분류 재처리·Google/은행 쓰기0.
- 릴리스1,122 Git blobs 불일치0, 병합 코드 tree 일치·추가14파일 메타데이터 차단0/삭제0·새 백업/별도 복원 PASS. 공식 배포기를 통해 task/process SHA·단일 loopback listener·health/ready200·보호API401, 배포 및 인증 조회 전후 보호13표 불변, Board/SourceRefresh Running을 확인했다.
- 인증 Aside `/import`의 파일/업로드 컨트롤·50건 페이지/시스템 오류 코드와 저장 자료8개 API200을 확인했다. 익명 `/import`, `/api/imports`, `/api/imports/rules`, POST `/api/imports`는401이다. 모바일·두 테마·키보드/포커스는 최종 합성 브라우저5 passed 근거를 재사용했다. 실기기/Safari와 운영 재업로드·실제 금융 변경은 미실행이다. 대량 응답27.5MB/동기 처리라는 기존 성능 제한은 명세에 보존한다.
- 근거: 통합 worktree `.local-archive/cuv-operating-20261029/`의 acceptance-checkpoint·real-source-acceptance·review·release-audit·protection-before/after·deploy-evidence·upload-http-smoke·owner-ui-smoke 및 호스트 `D:/WebLedgerHost/releases/deploy-evidence-a69c0ae7389789a65d2ed01f3028c0348f52eb1f.json`. root 사용자 변경과 기존 workspace 보존. 해당 운영 수락 범위 남은 구현/배포0. 이 기록 후속은 문서 전용이며 재검사/백업/재배포/재시작하지 않는다.


## 2026-10-29 P2 카드 재검토 배포와 실제 분류 반영

- [PR #357](https://github.com/6Soo/cost/pull/357), 구현7ecf023·운영 `3860a822efe3a6f2d6c1349e824b193ac7309a7b`. 명시적 재검토 모드로 이전 완료 자동분류도 예약 이용기간/업종/용도와 대조한다. 원문/ID는 Git/외부 모델에 전송하지 않으며 추론 결과를 사용자 확인으로 기록하지 않는다.
- 코드 배포: tree동일·1113 Git blobs 불일치0·신선 백업/별도 복원·task/processSHA·단일listener·health/ready200·보호API401·보호13표 불변. 이후 데이터 적용은 사용자의 별도 “p2 재진행” 지시에 따른다. 이전 검증3c8c970 릴리스와 복구 사본 보존.
- 실제 P2 적용: 전체6395 점검·보호57 유지·5451건 분류/근거 갱신, 정상 결제 미배정1821→0. 항목70·귀속2047 변경(중복3), 근거만3337. 예약 대조393·이용기간 근거183·해당 근거가 있는 귀속 변경40, 자료 누락/오류0. 등록 여행2026~27·기존2025년 미배정1420을 포함하며, 날짜거리90일 초과670건은 낮은 추론으로 표시한다. 예약 결제 연결·실제 환급·사용자 확인을 창작하지 않는다.
- 신선 백업/별도 복원·단일 작성자·동일 상태/digest 복사본 검증·원자 저장·원본/금융/수동 결정 보호·재실행0·서비스 복구 PASS. 사후 독립 readonly 감사에서 수동/교정 이력559건 전체 거래행·원본/금액/ID·보류/결정/override·금융 링크·스키마·장부 행 수 불변. 신규 장부/금융 링크/Google/은행 쓰기0. 최종6395 classified·보호 제외 미분류/정상 결제 미배정0·readonly쓰기0·health/ready200·카드/OTA API401·Board/SourceRefresh Running.
- 검증: P2/분류/환불 보호76 passed·추가 캐시 원본 변경 거부1 passed, compile/PowerShell/diff/data guard 통과. 초기 복사본의 재생 근거 불일치는 실패로 기록하고 교정 후 실제 자료에서 통과했다. 전체 회귀/실기기/인증 owner 화면 수락 미실행. `.local-archive/p2-rerun-20261029/`, 동일 SHA 로컬/호스트 deploy evidence 및 `D:/WebLedgerHost/data/backups/card-classification-20261029T223551095/`의 backup-restore/preview/applied/repeat가 근거다. 문서만의 후속으로 재배포/재처리하지 않는다.

## 2026-10-29 보존 분류 상태 제거 배포

- [PR #354](https://github.com/6Soo/cost/pull/354), 구현a44c38c·운영 SHA `3c8c970da271b665feb99a89fad661b7399ef6d7`. 과거 카드에 preserved 상태를 생성하거나 해당 상태로 분류/조회/여행 검토/대사를 제외하지 않는다. 원본/수동 결정/금융 보호와 명시적 조회 기간 필터는 유지한다. 상세 최신 계약은 [금융 명세](specs/finance.md)에 기록했다.
- 검수 tree=merge tree,1112 Git blobs 일치·새 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·보호API와 카드 summary/years401·보호13표 내용/스키마 불변·Board/SourceRefresh Running. 호스트 venv 합성 과거/legacy 분류·일반 추론·기간 필터·원본/금액/ID 불변과 장부쓰기0 PASS. 이전 검증f9b71d2 릴리스와 복구 사본 보존.
- 운영 사전 readonly: classified6395·preserved0·legacy 완료기간 출처0·쓰기0. 운영 마이그레이션/재분류·금융/여행/Google 쓰기0. 상태 제거를 개별 P2 재검토 완료로 표현하지 않는다. 분류/OTA/조회·여행·환불/원자성 표적 근거는 현재 상태와 로컬 checkpoint에 기록했다. OTA history1 실패는 기준f96cd8f에서 재현했고 전체 회귀/실기기/인증 owner 수락은 미실행이다.
- 근거: `.local-archive/remove-preserved-20261029/`, `.local-archive/deploy-3c8c970da271b665feb99a89fad661b7399ef6d7/`, `D:/WebLedgerHost/releases/deploy-evidence-3c8c970da271b665feb99a89fad661b7399ef6d7.json`. 문서 후속만으로 재배포·재시작하지 않는다.

## 2026-10-29 보존 카드 분류 완료·지출 정리 목록 표시 수정·운영 배포

- COMPLETE — 과거 보존 카드 3,653건의 분류 완료와 지출 정리 조회 조건 보완을 완료했다. [PR #351](https://github.com/6Soo/cost/pull/351), 구현 `0f97623ad4b4e1d5b0e4776c67b8769b28a0a4d8`, 운영 SHA `f9b71d2f2b6a749fd6137855d7e4ff0582c68bbb`.
- 과거 유효 여행 기간 밖의 보존 거래는 현재/미래 여행으로 억지 배정하지 않고 `등록된 유효 여행 없음 · 비용 항목 분류 완료`로 보존 완료했다. 검증된 원결제의 분류를 상속한 환불 행도 재추론을 건너뛰도록 보호했다.
- 지출 정리(`_cleanup_card_where`) 조회에서 완료 정책(`complete-card-inference-v1`) 또는 원결제 상속(`refund_original`)으로 완료된 정상 분류 행을 제외했다. 항목 누락·구문 오류·충돌 사유·명시적 사용자 보류(`transaction_review_holds`)가 있는 거래는 정리 목록에 계속 표시한다.
- 검증: 표적 및 보호 테스트 37 passed (`test_card_cleanup_queries.py`, `test_automatic_classification_completion.py`, `test_refund_group_commit.py`), UI 9 passed (`test_card_cleanup_ui.py`). 실운영 DB(6,395건 전체 `classified`) 조회 검증 결과 정리 대상 카드 3,695→0건, 보류 4건 안전 보존 확인.
- 배포: 1,112 Git blobs 일치(불일치 0), 새 백업(`operational-20261029T122609435227Z`, `v2-owner-ui-20261029T212558`) 및 복원 검증(`restore-evidence.json`), task/process 고정 SHA 일치, 단일 loopback listener, health/ready 200, 보호 API 401, 보호 13개 테이블 내용/스키마 불변(`protection-after.json`). WebLedger-Board 및 WebLedger-SourceRefresh Running 정상 확인. 이전 검증 릴리스 `160f4cd93301b469183c6c243f98ab2a2ad2effc` 및 복구 사본 보존. 신규 금융/Google/은행 쓰기 0.
- 근거: `.local-archive/deploy-f9b71d2f2b6a749fd6137855d7e4ff0582c68bbb/`의 review.json, gate-before.json, protection-before.json, protection-after.json, deploy-evidence.json 및 `D:/WebLedgerHost/releases/deploy-evidence-f9b71d2f2b6a749fd6137855d7e4ff0582c68bbb.json`.

## 2026-10-29 전체 화면 내부 설명 정리·카드 행 정렬

- COMPLETE — 사용자 “모든 페이지 전체에 있는 이런 내부 문구 모두 삭제”와 직전 모바일 정렬 교정을 이어서 완료했다. [PR #343](https://github.com/6Soo/cost/pull/343)·[PR #347](https://github.com/6Soo/cost/pull/347), 문구 최종 검수 `ab4fa61e76eb220533fa07369b6ab5f35123fa09`, 운영 SHA `160f4cd93301b469183c6c243f98ab2a2ad2effc`.
- 카드 목록·지출 정리·장부 상세/원천 미리보기·여행·OTA·예약 연결·계정·항공권·영수증·검토 화면의 반복적인 원행/보존/읽기 전용/기장 분리 설명과 revision·digest 안내를 정리했다. 장부 저장 성공은 “저장했습니다”로 표시한다. 거래별 오류/보류·원본 정보·금융 상태·확인/전송 동의·hidden revision 및 동시 수정 보호는 유지한다. 모바일 가맹점 버튼의 공통44px 높이를 해제해 이름과 카드 정보를 붙이고 셀을 위로 정렬한다.
- 검증 archive: 카드/모바일28 passed(320/390/600/759/760/1280·두 테마·200% 확대·행64px 이하·이름/카드 간격3px 이하·가로 넘침/펼침/스피너). 화면 묶음130 passed/40 subtests, 보호 경계91 passed. 삭제한 설명을 요구하던 source/refund 검사는 새 계약으로 교정했고 source/refund/장부 인접76 passed. 이후 저장 문구/규칙 대화13개 검사는12+모바일 저장1 passed. 실행 간 중복이 있어 전체 합계로 세지 않는다.
- 기존 실패: 증거UI schema2건·OTA snapshot/정리3건(폭별 subcase 포함5)은 기준 `fa087d3` archive에서도 재현했다. 결합 fixture 순서로 발생한 cleanup/OTA4건은 독립 검사3 passed/2 subtests로 확인했다. 테스트 보호를 완화하지 않았고 기존 실패를 통과로 세지 않는다. 전체 회귀·운영 owner 화면·Safari/실기기 수락은 미실행이다.
- 배포: 변경 blobs 병합본 일치·1112 Git blobs 불일치0·호스트 Python 합성 원본 상세/이스케이프/마스킹/펼침/스피너/DB불변 PASS. 새 백업·별도 복원·task/process 고정SHA·단일loopback listener·health/ready200·보호API/카드/상세/규칙 URL401·보호13표 내용/스키마 불변·Board/SourceRefresh Running. 이전 검증 `297a5ef0f0a882314f65c0372492d4886e6e2820`과 복구 사본 보존. 실제 고객 금융/분류/여행/Google 쓰기·마이그레이션0.
- 근거: `.local-archive/internal-ui-copy-20261029/`의 checkpoint·검증 archive/XML·baseline-output 및 `.local-archive/deploy-160f4cd93301b469183c6c243f98ab2a2ad2effc/`와 호스트 동일 SHA release-audit/deploy-evidence. 기존 workspace 브랜치/사용자 변경/미추적 파일 보존. 현재 승인 범위의 미결·차단0, 다음 명령 없음. 후속 문서만으로 검사·재배포·재시작하지 않는다.

## 2026-10-29 일반 지출정리20건 완료·환불 확인중19건 보존

- [PR #344](https://github.com/6Soo/cost/pull/344), 구현 `1a552ba`, 운영 `297a5ef0f0a882314f65c0372492d4886e6e2820`. 검토 후 refunds로 분류한 미연결/비영점 취소를 환불 화면의 취소 정산 확인중 목록에 표시한다. 원문·미기록·실제 환급 미확인·보류 사유를 보존하고 기존 전액상쇄 묶음과 중복 표시하지 않는다. settlement/read-only/escaping/refund-tab/inline21 passed·merge tree 동일·metadata2파일 차단/삭제0·1112 blobs 일치.
- 코드 배포는 새 백업/별도 복원·작업/프로세스SHA·단일loopback listener·health/ready200·보호API401·13표 불변을 통과했다. 이전6b63f78 및 복구 사본 보존. 코드 배포 단계의 자료 쓰기0이며 아래 실제 자료 적용과 구분한다.
- 실제 적용: 정상 결제1,345,388원1건만 내부 장부/화면에 추가. 미매입 취소17건과 취소 예약2건은 원문 근거의 분류 교정19건을 기존 atomic review 경로로 적용했다.19건의 금융 기장/새 링크/보류 해제0, 기존금액/ID/원본/사용자 변경/장부/스키마/링크/보류 보존. 실제 은행 환급/Google 쓰기0.395,000원-355,000원의40,000원은 단순 원행 차액이며 수수료 확정 아님;152,358원은 대응 카드 환불 미확인이다.
- 최근 백업 재사용은 실제 DB 불일치 검증으로 거부됐다. 새 백업/별도 복원·단일 작성자·동일 상태/digest 메모리 리허설 후 실제 적용했다. 정상 카드의 선택적 OTA 메타데이터 보강은 범위 밖 전체 재대사 비용을 피하기 위해 생략했으며 새 예약 링크를 만들지 않았다. 정상 단건 기록과19건 분류 원자성은 각각의 기존 경로이며 전체20건 단일 트랜잭션으로 보고하지 않는다. 재실행은 분류/장부 무쓰기다.
- 인증 Aside 화면에서 `/import`20→0건, `/board?tab=refunds` 취소 정산 확인중19건을 확인했다.19건을 금융/환급 완료로 보고하지 않는다. Board/SourceRefresh Running·health/ready 정상. 근거는 `.local-archive/remaining20-20261029/`, 해당SHA 배포 폴더 및 `data/backups/remaining20-20261029T191324616/`의 복원/리허설/실제 적용 JSON이다. 새 원결제/카드취소 등 증거가 금융 재검토 조건이며 사용자에게 개별 환급 확인을 다시 묻는 승인 대기는 없다. 문서 후속 재배포/재시작 없음.

## 2026-10-29 카드 모바일 5항목 — 구분선·폭·원본 상세·펼침·스피너

- 5항목 모두 COMPLETE — [PR #340](https://github.com/6Soo/cost/pull/340), 검증 구현 `78469c2c8102f7726d026faec39fbab08b7fa745`, 운영 SHA `6b63f78b8779c97a6f9066e03d0b26dc9803b721`. 행 구분선을 제거하고 모바일 최소380px/데스크톱560px을 없애 실제 가용 폭에 맞춘다. 긴 내용은 줄바꿈하며 표와 페이지 모두 가로 넘침이 없다. 행/가맹점 버튼은 별도 페이지 이동 대신 바로 아래 상세를 열고 닫는다. 로딩 스피너·실패/지연 안내·재시도·Enter/Space/Escape·aria-expanded/busy·텍스트 선택·기존 환불 링크를 보존했다. 기간/검색 제출 및 일반 링크 이동도 스피너로 표시하며 뒤로가기 복귀 시 해제한다.
- 장부행 전용 `card-…` 링크 때문에 원본만 있는 거래가 “없는 거래예요”로 표시되던 원인을 수정했다. `/api/cards/transactions/detail?id=…`는 원본 카드 고정 필드를 mode=ro·파라미터 SQL로 읽고 escaped HTML/no-store를 반환한다. 비로그인401·직원403을 원본 조회 전에 적용한다. 기존 장부 URL도 원본이 존재하면 소유자에게 읽기 전용 상세를 보여준다. 원본/금액/배정/분류/환불/Google/스키마는 쓰지 않는다.
- 정확한 통합 Git archive에서 카드·모바일·원본 상세·환불 목적지·조회 API·실제 HTTP 권한 86 passed, 별도 인접 환불12 passed. 320/390/600/759/760/1280·두 테마·200% 확대·열림 전후 표/페이지 가로 넘침 부재·행 경계0·대기 스피너·실패 후 재시도·원본 전후 dump 동일성·카드 마스킹/HTML escape·원본 전용 과거 URL 수락. 전체 회귀·인증 운영 owner 화면/실기기는 미실행이다.
- 병합 tree 동일·1111 Git blobs 불일치0·운영 Python 합성 smoke PASS. 별도 환불 세션의 승인된 작업이 종료된 뒤 새 보호 상태를 기록해 순차 배포했다. 새 백업/별도 복원·task/process 고정SHA·단일loopback listener·health/ready200·보호API 및 상세/카드 URL401·보호13표 내용/스키마 불변, Board/SourceRefresh Running. 이전 검증 릴리스와 복구 사본을 보존했다. 이 UI 작업에서 운영 금융/여행/분류/Google 쓰기·마이그레이션·재처리0이며 별도 세션의 금융 작업과 구분한다.
- 근거: `.local-archive/card-inline-details-20261029/`의 checkpoint/통합 archive/합성 이미지, `.local-archive/deploy-6b63f78b8779c97a6f9066e03d0b26dc9803b721/`의 review/runtime-smoke/auth-smoke/protection-before/protection-after/deploy-evidence 및 호스트 동일 SHA release-audit/deploy-evidence. 기존 사용자·다른 작업 변경/미추적 파일 보존. 현재 5항목의 남은 작업·차단0, 다음 명령 없음. 후속 문서만으로 검사·재배포·재시작하지 않는다.

## 2026-10-29 전액상쇄 환불 기록 완료·부분 기기록 보호 교정

- [PR #339](https://github.com/6Soo/cost/pull/339), 구현 `02cb163`, 운영 `8b91aeb622106af38935dce49da4c10bb7ddc37e`. 기존 장부가 있는 묶음 멤버의 파생 existing_ledger 보류가 빠진 쪽까지 막던 문제를 교정했다. 실제 ledger_entries가 있는 멤버만 제외하고 legacy 투영/수동/금융/중복/인증 보호를 유지한다. inline/cross-batch/refund-inference44 passed, merge tree 동일·metadata2파일 차단0/삭제0.
- 코드 배포:1110 Git blobs 일치·새 백업/별도 복원·task/processSHA·단일listener·health/ready200·보호API401·13표 불변. 이전5297a0d와 복구 사본 보존. 코드 배포 때 금융 쓰기는0이며 아래 승인된 자료 적용과 구분한다.
- 실제 적용: 점검된22묶음/46원행에 한정해 빠진44개 ledger_entries와 대응 board_rows/revisions를 기존 guarded commit/project로 추가했다. 전체 미기록20묶음과 일부 기기록2묶음을 완료했다. 기존 장부·원본/금액/ID·수동 결정·범위 밖 표·보존237묶음·스키마 불변, 각 묶음순액0·재요청 무쓰기 검증. Google/은행 쓰기0. 별도 신선 백업·복원·동일 상태/digest의 메모리 리허설 후 단일 작성자로 적용했다.
- 초기 리허설은 sqlite_sequence 정상 증가를 검증기가 거부해 실제 쓰기 전 중단/서비스 복구했다. 승인된 append 표의 카운터만 단조 증가를 허용하도록 보완한 뒤 리허설·실제 적용을 통과했다. 실제 기록은 묶음별 원자성이고 전체22묶음을 하나의 트랜잭션으로 처리했다고 주장하지 않는다.
- readonly audit 및 인증 Aside `/import`: 대상28행 제거·카드 지출정리48→20건, 남은20건은 별도 미연결/보류 거래다. Board/SourceRefresh Running·health/ready 정상. 전체 회귀/실기기는 미실행. 근거는 `.local-archive/refund-zero-audit-20261029/`, `.local-archive/deploy-8b91aeb622106af38935dce49da4c10bb7ddc37e/`, 호스트 동일SHA 배포 근거 및 `data/backups/refund-zero-20261029T185028294/`의 복원/리허설/실제 적용 JSON이다. 문서 후속으로 재배포/재시작하지 않는다.

## 2026-10-29 카드 목록 배정·분기·취소환불 문구 정리

- COMPLETE — [PR #336](https://github.com/6Soo/cost/pull/336), 구현 `e141289640e92409c3a9312c5f11bc991e4247b9`, 운영 SHA `5297a0daee012809f17dfb0d045283284f9b977e`. 카드 목록 열 제목을 `배정`으로 줄였다. 분기 배정은 내부 ID 대신 `2026년 3분기 기타비용`처럼 표시하며 내부 ID/title은 보존한다. 취소·환불 목록의 반복 부연 설명을 제거하고 기존 링크를 유지했다. 앞선 인계의 “quarter는 내부 ID이고 이미 분기로 표시” 설명은 카드 목록의 fallback 경로를 누락했으므로 이 기록으로 교정한다.
- 정확한 구현 archive의 카드·모바일·환불 목적지 34 passed. 320/390/600/759/760/1280·두 테마·200% 확대·행/환불 링크·원본 불변 검증 포함. merge tree 동일·1110 Git blobs 불일치0·운영 Python의 분기1~4/연도·배정 제목·환불 링크·원본 불변 smoke PASS. 인접 장부 UI 실패6건은 기준 main에서 재현해 범위 밖으로 유지했다. 결합 검사에서 분기 브라우저 임시 DB 정리 실패1건이 있었으나 기준 main 독립 실행에서는 통과했다. 전체 회귀·실제 owner 화면/실기기는 미실행이다.
- 새 백업/별도 복원·task/process 고정SHA·단일loopback listener·health/ready200·보호API401·금융/사용자13표 내용/스키마 불변 확인. Board/SourceRefresh Running. 이전 검증 `78cb6ad4a7ead4ecaff39671eb0a32090b4c8021` 보존. 실제 분류/금융/여행/Google 쓰기·마이그레이션·재처리0.
- 근거: `.local-archive/card-assignment-label-20261029/`의 checkpoint/baseline-failures 및 `.local-archive/deploy-5297a0daee012809f17dfb0d045283284f9b977e/`의 review/runtime-smoke/auth-smoke/protection-before/protection-after/deploy-evidence, 호스트 동일 SHA release-audit/deploy-evidence. 기존 사용자·다른 작업 변경과 미추적 자료 보존. 현재 요청의 남은 구현/배포·차단0, 다음 실행 명령 없음. 후속 문서만으로 테스트·재배포·재시작하지 않는다.

## 2026-10-29 카드 3820 공통 자동분류 정책 배포

- [PR #335](https://github.com/6Soo/cost/pull/335), 수정 `dc2aaf3`, 운영 SHA `78cb6ad4a7ead4ecaff39671eb0a32090b4c8021`. 공통 자동분류에 기존 싱가포르 기간 예외와 국내 잔여 매입의 거래일 기준 분기 기타비용 정책을 적용했다. 사용자 결정·완료 행·해외/날짜 불명·취소/환불 보호를 유지한다.
- 정확한 Git archive의 자동분류 완료·3820 표적38 passed, 호스트 Python 합성5검사 PASS(2025년 거래의2025년4분기 포함). 호스트 pytest 부재로 개발 Python에서 archive를 검사했다. 초기 stdin 한국어 전달 실패는 UTF-8 파일 실행으로 해결했다. 기존 인접34 passed 재사용, 전체 회귀/실제 owner UI/실자료 재분류는 미실행이다.
- 1110 blobs 일치·새 전체 백업/별도 복원·작업/프로세스SHA·단일loopback listener·health/ready200·OTA/환불/2025 카드 조회 보호401·13표 내용/스키마 동일. Board/SourceRefresh Running. 이전 검증 `dccd3af6d12a52a3f9eb50a647979527ac5cc1f7`과 복구 사본 보존. 실제 분류/금융/여행/Google 쓰기·마이그레이션·대량 재처리0.
- 근거: `.local-archive/card3820-deployment-20261029/`, `.local-archive/deploy-78cb6ad4a7ead4ecaff39671eb0a32090b4c8021/`, 호스트 동일SHA release-audit/deploy-evidence. 기존 사용자 변경 보존. 후속 문서 변경으로 재배포/DB 확인/재시작하지 않는다.

## 2026-10-29 카드 행 이동·날짜/폭 압축 배포

- [PR #331](https://github.com/6Soo/cost/pull/331), 운영 SHA `de2aada07320de57aee6935c7617f6d3102f017a`, 검수 소스 `4e8588a58eb262a2206fd5a7ce13a1bfe48f5292`와 tree 동일. ‘원본 보존’ 배지와 상세 열을 제거하고 행 셀 클릭으로 기존 상세 URL을 연다. 네이티브 가맹점 링크의 키보드/새 탭/JavaScript 없는 탐색·환불 링크 독립 동작·텍스트 선택 보호를 유지한다. 모바일4열·최소380px·셀5/4px이며 연도 선택 `3월 5일`, 월 선택 `5일`과 시간·원본 날짜/title을 표시한다.
- 별도 금융 작업의 동시 변경을 포함하지 않은 정확한 커밋 archive에서 카드/필터/환불 목적지/브라우저43 passed.320~1280 여섯 폭·두 테마·200% 확대·행 클릭·키보드·독립 환불 링크·선택 보호·날짜/title·원행 불변·표 폭/페이지 넘침을 검증했다. 초기 날짜 검사 의존성은 표준 re로 교정, compile/diff·metadata6파일 차단0/삭제0. 전체 회귀·실제 인증 owner UI/실기기는 미실행이다.
- 1110 Git blobs 일치·새 전체 백업/별도 복원·task/processSHA·단일 loopback listener·health/ready200·보호 API/연월/상세/환불URL401·보호13표 내용/스키마 불변. 호스트 Python에서 실제 배포본의 단일 기간·4열/380px·배지/상세 열 부재·행 링크/스크립트·한국어 날짜/title·환불 링크·원행 불변 합성 smoke PASS. Board/SourceRefresh Running, 직전537aa3b 및 복구 사본 보존. 금융/분류/여행/Google 쓰기·스키마 변경·재처리0.
- 근거: `.local-archive/card-row-navigation-20261029/`, `.local-archive/deploy-de2aada07320de57aee6935c7617f6d3102f017a/` 및 호스트 동일 SHA release-audit/deploy-evidence. 후속 문서만의 변경은 검사·DB 확인·재배포·재시작하지 않는다.

## 2026-10-29 연월 통합·모바일 압축 표 최종 배포

- [PR #329](https://github.com/6Soo/cost/pull/329), 운영 SHA `537aa3bca7cec79debad4db92d67e94baa6934e6`, 검수 소스 `6f581aa3dd12e2a1797e24c8243068def6f77ae3`와 tree 동일. 최신 사용자 교정대로 모바일도 기존 표 방식이며, 560px 최소 폭·6/8px 셀 여백·12px 글자·두 줄 이름·원문/title 보존·표 내부 스크롤로 압축한다. 월별 카드 제거·연월 선택 하나·즉시 연도/월 조회·필터/커서 호환은 PR #328에서 유지한다.
- 카드/필터/환불 목적지/모바일42 passed, Chromium320/390/600/759/760/1280·두 테마·200% 확대·키보드에 따른 표 스크롤·행 높이110px 이하·원문/title·부호/통화·환불 링크·페이지 가로 넘침 부재 확인. compile/diff·metadata guard4파일 차단0/삭제0. 실제 인증 owner 화면/실기기·전체 회귀는 미실행이다.
- 1110 Git blobs 불일치0, 새 전체 백업·별도 복원, task/processSHA·단일loopback listener·health/ready200·보호 API/연월 조회401·보호13표 내용/스키마 불변·Board/SourceRefresh Running을 확인했다. 배포본/호스트 Python의 압축 표 CSS·단일 연월 선택·연도/월 조회·월 타일 부재·환불 링크·원행 불변 합성 smoke PASS. 실제 금융/분류/여행/Google 쓰기·재처리·마이그레이션0.
- 직전 PR #328/`b933bdd84cf79d6c64e6f1d5093bc8b648865c7a`의 세로 카드 배포도 백업/복원·보호 불변으로 완료됐지만 최신 표 요청 수락과 구별한다. b933bdd와 복구 사본을 보존했다. 최종 근거는 호스트 동일 SHA release-audit/deploy-evidence, `.local-archive/deploy-537aa3bca7cec79debad4db92d67e94baa6934e6/` 및 `.local-archive/card-history-compact-table-20261029/`다. 문서 후속 병합에 검사·재배포·재시작을 반복하지 않는다.

## 2026-10-29 동일일·동액 OTA 연결 배포 및 확인된 두 결제 반영

- [PR #320](https://github.com/6Soo/cost/pull/320), 구현 `2b2ea98`, 검증 main/Windows SHA `f60e1a7225f834445491cab34f846622ec9ba120`. 동일일·동일 통화 정확 금액의 추가 단서 요구를 없애고 명시 충돌/전역 점유/부분 반복 묶음은 보호한다. 사용자 수동 외화 연결은 원문 외화와 카드 원화값을 보존하며 환율/미관측 끝자리를 만들지 않는다. matcher4로 기존 snapshot을 무효화한다.
- 관련214 passed, snapshot-action/authority32 passed. staged metadata6파일 차단/삭제0. 새 전체 백업·별도 복원,1108 Git blobs 일치, task/processSHA·단일 loopback listener·health/ready200·보호 API401·보호13표 배포 전후 동일. 배포본을 호스트 Python으로 import한 matcher smoke PASS. 코드 배포 단계의 실제 금융 쓰기0이며 이후 사용자 개별 확인 적용과 구별한다.
- 사용자 확인 두 숙박 거래만 기존 북큐슈 여행/숙박비로 교정·명시 예약 연결·내부 장부에 각1회 기록했다. 복사본에서 기존 스키마/원문/금액/ID/기존 행/범위 밖 표 보존을 검증하고 단일 작성자로 게시했다. 동일 조건2:2의 안정 순서 연결이라는 불확실성을 보존했다. 최종 readonly 확인 및 실제 인증 Aside 카드 화면2건/교정 여행/카드 끝자리 표시를 수락했고 Board/SourceRefresh Running·health/ready를 확인했다. Google 쓰기/실제 은행 환급0.
- 예약 원문에는 카드사 브랜드만 있고 끝자리가 없어 파서 손실이 아니었다. 최초 복사본의 부수적 테이블 생성과 최초 게시의 journal 전환 잠금은 성공으로 계산하지 않았다. 운영 금융 원복·복사본 재검증 후 기존 journal을 유지하는 최종 게시만 APPLIED_VERIFIED로 기록했다.
- 근거: 호스트 해당SHA deploy-evidence/release-audit, `D:/WebLedgerHost/data/backups/trip-confirm-20261029T041040263786Z/`의 rehearsal/apply-evidence 및 원본/별도 복원 사본, 로컬 `.local-archive/ota-same-day-amount-20261029/`. 이후 이 문서 전용 변경은 테스트/백업/재배포/재시작하지 않는다.

## 2026-10-29 PR #318 카드 검색 즉시 결과·금액 검색 배포

- **COMPLETE:** [PR #318](https://github.com/6Soo/cost/pull/318), 운영 `0c285e14bb87d4a843d1860159cc2be35ed2aa8a`, 검수 소스 `2989613f9e837c02bd353d19135f1eb79da013d5`와 tree 동일. 월 선택 없이 선택 연도 검색 결과를 즉시 표시하고 0건을 명시한다. 원화/외화 금액의 쉼표 유무·승인번호 검색, 결과의 여행명/미배정 표시와 필터/커서 보존, 좁은 화면 필터 배치를 보완했다.
- **검증:** 카드 조회/필터/렌더 81 passed. 최초 합성 browser의 중복 검색창 선택기 실패를 카드 폼으로 한정해 교정한 뒤 해당 browser 1 passed/25 deselected. 검색 제출·0건·금액·긴 여행명·320/390/760/1280폭 및 기존 확대 경계를 확인했다. compile/diff·guard5파일 차단0/삭제0. 원행 전후 불변·마스킹·연도/필터/페이지 경계를 확인했다. 배포본/호스트 Python의 별도 합성 smoke는 금액/외화/승인번호·즉시/0건·HTML escape·원행 불변 PASS. 초기 smoke 정리 단계의 SQLite 잠금은 연결 종료 후 해소했다.
- **운영 수락:** 1,107 Git blobs 일치·새 전체 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·OTA/환불 보호API401·검색 URL 2개 비인증401·보호13표 내용/스키마 전후 동일. Board/SourceRefresh Running. 이전 검증 `1beba48bdd4f0aa20999326689d7c766c921c576` 복구점 보존. 금융/여행 재처리·Google 쓰기·마이그레이션0. 실제 owner 인증 화면/물리기기 수락·전체 회귀는 실행하지 않았으며 합성 검사와 구별한다.
- **근거/보존:** `.local-archive/card-search-20261029/`의 review/runtime-smoke/auth-smoke/protection-before/protection-after/deploy-evidence JSON, 호스트 동일SHA release-audit/deploy-evidence. 기존 미병합 환불 커밋·다른 browser WIP·사용자 미추적 파일은 그대로 보존했고 검색 PR에는 포함하지 않았다. 남은 검색 작업·차단0이며 후속 문서만으로 재배포하지 않는다.

## 2026-10-29 PR #316 프로젝트 미결 병렬 구현·검증 경계 배포

- **DEPLOYED:** Luna low6명에게 보험/참가자/메일/여행 구조/화면/실패 진단을 위임했다. 429·capacity로 중단한3개 구현과 추가 진단은 Supervisor가 실제 파일을 인계해 수리·검수했다. 미완성 WIP를 그대로 병합하지 않았다. [COST PR #316](https://github.com/6Soo/cost/pull/316) 소스 `a6b73ae5c01403c0ff41ea133bf0a9cec5100b0e`와 운영 `1beba48bdd4f0aa20999326689d7c766c921c576` tree 동일. 별도 [Travel INS PR #10](https://github.com/6Soo/travel_ins/pull/10)은 main `ec2b73300fe1dbe8c62d958282c929ef3bd80f6a`에 병합됐고 실제 pause→실제 등록 함수 경계 합성 검사를 포함20 passed다. 실제 보험 가입/결제/명단 전송은 실행하지 않았다.
- **변경:** readonly 참가자 DB 경로/파일 identity/schema/등록 영수증 대조와 명시 웹DB 불일치 선차단, 수집 미완료 시 batch/일반 apply 차단, digest/coverage/건수 기반 오프라인 전환 preview를 구현했다. preview는 운영 전환을 승인하지 않는다. 여행권위·소매·숙박3메서드 추출은 실행 AST동일성과 기존 동적 callback을 보존한다. OTA 공통 토큰·44px·좁은폭·포커스를 적용했다. 진단 도구는 parameter/subtest 원문을 감추고 PowerShell UTF-16 로그를 읽으며 collection-only/기존 실패를 pass로 숨기지 않는다.
- **검증:** 참가자/수입/패널66 passed, 금융/환불/정확OTA/권한105 passed, CardFlow/OTA96 passed+28subtests, 여행/자동분류23 passed, cloud/진단41 passed, runtime/entrypoint33 passed, OTA API39 passed,4폭·2테마·2배율 합성 디자인4 passed, 최종 참가자5 passed/진단7 passed. 중복이 있어 합산 전체 회귀가 아니다. 추가 shell/assets/카드/OTA browser는30 passed/11 failed/18subtests이며 격리 기준8cfe391에서도 동일11 실패node/subcase를 재현했다. 폐기된 추가 기록/수동질문·배치/문구 기대와 canonical snapshot 준비 문제를 별도 실패로 기록했다. 제품 금융 보호는 완화하지 않았다. guard19파일 차단0/삭제0·미매핑0·Python compile·diff검사 통과.
- **운영 수락:**1,107 Git blobs 일치, 새 전체 백업·별도 복원, task/process SHA, 단일 loopback listener, health/ready200, 참가자 state/trip-panel·OTA groups/summary 등 비인증 보호API401,13표 내용·스키마 전후 동일. Board/SourceRefresh Running. 직전 검증 `9b190e9a70511581629f4378290220512358b48c` 복구점 보존. 실제 분류/금융 재처리·마이그레이션·Google 쓰기0.
- **미완료/재개 조건:** manifest readonly 재확인 `2026-10-29T01:58:27Z`는3,710 stored/48 pending/has_next_page=true다. pending0·다음페이지 없음·query없음·last_complete 존재 후에만 전환 자료 gate 재개. 보험 전달 구성의 참가DB가 없어 DB 동일성/실등록 영수증·운영 참가자/수입 화면 수락은 미완료다. 외부 원결제 증빙 부족 거래·전체 리팩토링/전체 화면 수락/전체 회귀도 이번 배포만으로 완료하지 않는다.
- **증거:** `.local-archive/wide-pending-20261029/validation.json`·baseline-browser.txt/xml·cloud-manifest-recheck.json·participant-*.json, `.local-archive/deploy-1beba48bdd4f0aa20999326689d7c766c921c576/`의 review/protection-before/protection-after/deploy-evidence/affected-path-smoke JSON, 호스트 같은SHA release-audit/deploy-evidence. 작업자6개 managed workspace는 clean·보존ref 확인 후 공식 archive/디렉터리 제거했고 사용자 미추적 자료·stash는 보존했다. 문서 후속만으로 재배포/DB 확인/서버 재시작하지 않는다.

## 2026-10-29 PR #314 Luna low 병렬 구현·환불 재전송·분류 완료 표시

- **COMPLETE:** 사용자 지정 `codex/gpt-6-luna`·`low` 작업자3명에게 환불 재전송·추론 경로·화면 표시를 분리 위임하고 Supervisor가 실제 diff 검수·추가 보호 수정·통합·배포를 맡았다. [PR #314](https://github.com/6Soo/cost/pull/314) 검수 소스 `cf3670606107c61a08e1e1232c35a3f23fcfbb73`와 운영 고정 `9b190e9a70511581629f4378290220512358b48c`의 tree 동일. 추론 작업자의 모든 취소를 환불 탭으로 보내는 변경은 검수에서 거부하고 완전 철회(diff0)했다. 완료된 추론 엔진을 재구현하거나 실제 카드 분류를 다시 실행하지 않았다.
- **수정:** 환불쌍 내부 기록 성공 후 같은 digest/새 요청ID 재전송이 잘못 실패하던 기존 baseline 결함을 해결했다. 잠금 안에서 정확한 성공 요청 범위·성공 직후 미리보기·전체 멤버 revision·실제 장부 fingerprint를 재검증한 경우만 applied0으로 반환한다. 부분 기기록 묶음을 완성한 뒤의 반복도 지원한다. 원본/장부 금액·사용자 결정·묶음 멤버 변경·명시 보류·임의 digest는 차단한다. 과거 성공 증명 없는 응답을 추정으로 허용하지 않는다.
- **화면:** 빈 여행 이력을 사용자 미배정 의도로 표시하지 않는다. 정상 환불 탭은 분류 완료이고 환불 선택값·미배정 필터도 일치한다. 금융/사용자 보류는 별도로 표시하고 교정/금융 쓰기 보호를 유지한다. 자동 추론 여행을 수동 교정 출처·규칙 학습 근거로 취급하지 않는다. OTA 읽기 전용 투영도 같은 출처 규칙을 적용하며 실제 수동 여행·금융 exact/manual link는 보존한다.
- **검증:** 통합 환불/부분환불/화면54 passed, 인접 자동기록/환불표시30 passed, 최종 화면/OTA출처17 passed(합성 browser 포함), OTA 권한/수동연결4 passed/35 deselected, 실제 수동 여행을 다른 후보보다 우선하는 강화 검사3 passed. 실행 간 중복이 있어 합산 전체 회귀가 아니다. 변경 Python6개·호스트 Python 런타임3개 compile, diff/문서 링크, 데이터 guard8파일 차단0/삭제0, 선택기 미매핑0. 영향이 없는 전체 회귀는 반복하지 않았다.
- **운영 수락:**1,098 Git blobs 불일치0·fresh 전체 백업/별도 복원·task/process 고정SHA·단일loopback listener·health/ready200·보호13표 내용/스키마 전후 동일. trip-review GET와 환불그룹 commit POST를 포함한 보호API는 비인증401. Board/SourceRefresh 모두 Running. 직전 검증 `a1b1dcaf21d5398ed3519a402191d0129173a6f7` 복구점과 새 백업/복원 사본 보존. 금융 재처리·Google 쓰기·마이그레이션 미실행.
- **증거/정리:** 호스트 같은 SHA의 release-audit/deploy-evidence, 로컬 `.local-archive/deploy-9b190e9a70511581629f4378290220512358b48c/`와 `.local-archive/luna-followups-20261029/validation.json`. 최종 커밋·clean·stash/사용 참조 확인 후 생성한 managed workspace3개를 공식 보관했고 디렉터리 제거까지 확인했다. 결과는 `refs/archive/20261029/luna-*`로 보존했고 사용자 workspace·미추적 파일·기존 stash는 그대로다. 후속 문서만으로 재배포하지 않는다.

## 2026-10-29 PR #312 미분류 카드 자동추론과 203건 재분석·실제 적용

- **코드·배포 COMPLETE:** [PR #312](https://github.com/6Soo/cost/pull/312), 운영 고정 `a1b1dcaf21d5398ed3519a402191d0129173a6f7`, 검수 소스 `f11b447e8970934985bf4f953801edc078762d71`와 merge tree 동일. 업종→서비스 용도→현지경비/기타경비 공통 규칙과 실제 여행의 최선 후보·동률 해소를 마지막 분류 단계로 연결했다. OTA 자료 읽기 실패도 비용 미분류로 남기지 않으며 미래 업로드에 같은 코드를 사용한다. 확정 단계를 추가하지 않는다.
- **사용자 의도 오인 정정 COMPLETE:** 사용자는 미배정으로 정한 적이 없다고 명시했다. 분류 이력·override 표시·기본 빈 여행만으로 수동 미배정이라고 간주하던 해석을 폐기했다. 203건을 재대조한 결과 실제 유효 여행 복원187건(현재 장부1·최근 저장31·기존 장부155), 기존 환불 탭11건, 새 여행 추론5건이었다. 현재 장부의 유효 여행은 날짜 추론보다 우선한다. 실제로 지정된 여행·항목은 보존하고 빈 필드에만 근거를 복원/추론한다. 과거 결정/override를 삭제하거나 자동 추론을 새 사용자 교정으로 학습하지 않는다.
- **실자료 적용 COMPLETE:** SHA 고정 `tools/apply_card_classification.ps1`에서 Board/SourceRefresh 정지·프로세스 검증→신선 전체 백업·별도 복원→운영 사본 미리보기와 현재 digest 일치→원자 분류→원본/사용자/금융 링크 보호→재실행 변경0→서비스 복구를 실제 수행했다.441건의 분류/배정을 보완했다. 미분류 구매195→0, 취소/환불 포함 전체 미분류226→0, 여행 미배정377→0. 앞서 제외했던203건도 실제 반영됐음을 백업과 live 자료로 재대조했다. 해당203건의 기존 비용 항목·source hash·금액·이용일/매입일은 그대로다.
- **데이터 보호:** 새 장부 행0·새 금융 연결0·Google 쓰기0·스키마 변경0. 기존 장부 행에는 비어 있던 분류/여행 필드만 보완했다. 과거 결정·override·보류·회사 제외와 원본 필드를 보호했다. 코드 전환만 했을 때13개 보호 표 불변을 확인했고, 별도 승인된 실제 분류 후에는 분류 대상3표의 허용 필드 외 원본/사용자 값 불변 및 나머지 금융/사용자10표 내용·스키마 동일을 확인했다. 실제 은행 환급·Google 반영을 창작하지 않는다.
- **검증:** 표적/금융/업로드/교정60 passed, 최신 추론/복원18 passed, 인접 bulk 포함22 passed, API/근거10 passed. 실행 간 중복이 있으므로 합산 전체 회귀가 아니다. 변경 Python8 compile·PowerShell parse0·diff/문서 링크·metadata guard12파일 차단0/삭제0. 미래 업로드·근거 부족·동률·빈 기본값/이력·기존 배정·부분환불·수동 항목·금액/링크 보호·rollback·재실행을 검사했다. 기존 old-digest+새 request 환불 재전송 실패는 이전 기준에서 재현된 별도 미결이며 금융 보호를 약화하지 않았다. 과거의 무관한 전체 HTML reload 금지 assertion은 해당 bulk 컨트롤 부재 검사로 교정했다. 전체 회귀는 이 변경의 영향 경계 밖이어서 반복하지 않았다.
- **운영 수락:**1,097 Git blobs 일치·task/process 고정SHA·단일 loopback listener·health/ready200·비인증 trip-review/OTA 등 보호API401. 실제 적용 후 Board/SourceRefresh 모두 Running. 직전 `b75c37887c354255f0bf877eb8d1e47451c9684d` 코드 복구점과 새 전체 백업/별도 복원 사본을 보존했다.
- **증거:** 코드 `D:/WebLedgerHost/releases/deploy-evidence-a1b1dcaf21d5398ed3519a402191d0129173a6f7.json`와 release-audit, 적용 `D:/WebLedgerHost/data/backups/card-classification-20261029T040917088/`의 backup-restore/preview/applied/repeat-preview/post-verification/financial-relations-verification JSON. 적용은 `APPLIED`, 재실행은 `to_classify=0`,203건 재대조는187/11/5·원본/항목 불변으로 PASS다. 고객 원문·거래 ID를 Git/보고서에 넣지 않았다. 문서 후속 기록만으로 재배포·서버 재시작하지 않는다.

## 2026-10-29 PR #310 자동분류 완료·환불쌍 저장 배포

- [PR #310](https://github.com/6Soo/cost/pull/310)을 `b75c37887c354255f0bf877eb8d1e47451c9684d`로 정상 병합·고정 배포했다. 검수 소스 `a1b5af2da158d6016f62c150171a91e78599852c`와 merge tree가 동일하다. 인계의 기존 `8ddee29` 환불쌍 분류 저장·`04a2958` 여행 authority 추론·`68ef66b` 답변 재사용을 함께 main에 통합했다.
- 분류되면 완료라는 최신 사용자 결정을 금융 명세·진입점·상위 지침에 기록했다. 자동·수동 배정 결과는 `CLASSIFIED`, 출처는 별도 필드다. 잠정 후 확정 요구·완료 분류의 확인 권장 문구를 없앴다. 분류 저장 후 내부 기록의 여행 요건이 부족하면 저장 자체를 409 실패로 반환하던 경로를 성공+별도 기록 보류 사유로 고쳤다. 수동 결정·원본 금액/ID·중복·환불 원자성·권한을 유지한다.
- 실제 검증: 초기 표적39 passed, 환불/여행/자동 기록62 passed+기존1 failed, 최신 자동 기록/교정21 passed, 결정 API/여행 이동/근거10 passed, OTA 권한/공개자료6 passed, 낮은 신뢰도 browser1 passed. 상속된 cleanup 검사4 passed+기존1 failed. 이 실행들은 일부 겹치며 합산 전체 회귀가 아니다. 최신 브라우저는 분류 완료·추가 교정 확인창 없음·4폭·확대·수동 결정/보류 보존을 확인했다. Python9개 compile·diff·문서 링크 누락0·metadata guard15파일 차단0/삭제0. 국소 변경이므로 전체 회귀는 실행하지 않았다.
- 기존 실패2개는 변경 전 `68ef66b`에서도 동일 재현했다. `test_refund_group_commit`의 새 요청 ID+이전 digest 재전송 `KeyError: result`, `test_cleanup_reclassification`의 전체 HTML에 `location.reload()`가 없어야 한다는 과거 assertion이다. 통과로 계산하거나 미리보기/금융 보호를 약화하지 않았다.
- 새 전체 백업·별도 복원 검증 통과, 추적1,092 Git blob 불일치0, task/process SHA 일치·loopback listener1·health/ready200·보호 OTA/환불/신규 trip-review/import API401·보호13표 내용/스키마 전후 동일. Board와 SourceRefresh 모두 Running으로 복귀했다. 직전 검증된 `68ef66b7b58b5733ca5532688fed893bc0cdc0fb`와 복구 근거를 보존했다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-b75c37887c354255f0bf877eb8d1e47451c9684d.json`, 같은 SHA release-audit, `.local-archive/deploy-b75c37887c354255f0bf877eb8d1e47451c9684d/`의 보호 전후·검수·배포본 순수 smoke, `.local-archive/automatic-classification-20261029/baseline-*.txt`. 배포본을 호스트 Python으로 직접 import한 합성 smoke에서 자동/수동 모두 완료·출처 분리·공개 필드 제한을 검증했으며 DB에 접근하지 않았다.
- 운영 일괄 재처리·36건 개별 저장·신규 업무 규칙 활성화·Google 쓰기·마이그레이션은 실행하지 않았다. 기존 업종·현지 사용 공통 규칙을 재사용한다. Aside에서 인증된 COST 탭이 없어 운영 owner 화면의 실자료 수락은 실행하지 않았으며 합성 browser 수락과 구별한다. 코드/명세/배포 완료를36건 실자료 완료로 확대하지 않는다. 이 후속 운영 기록만으로 재배포·서버 재시작하지 않는다.

## 2026-10-29 PR #308 환불 묶음 기록 안내 정리 배포

- PR #308을 `9ab2471f91b6b210ac79985a43e507743f5870d9`로 정상 병합하고 운영에 고정 배포했다. 지출 정리 화면의 전액 상쇄 안내 문구를 제거하고 버튼을 `원결제·환불 묶음 기록`으로 정리했다. owner·CSRF·preview digest 재검증·원자 commit 경계는 유지된다.
- 합성 금융 경계 검사 60건 통과, 새 백업·별도 복원 통과, 추적 1,092 blobs 불일치0, task/process SHA·loopback listener1·health/ready200·보호 API401·보호13표 전후 불변을 확인했다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-9ab2471f91b6b210ac79985a43e507743f5870d9.json`이다.
- 실제 금융·여행·Google 쓰기는 실행하지 않았다. 합성 apply에서 검증된 원결제+환불 2건만 순액 0원으로 기록되고 무관 행은 기록되지 않음을 확인했다.

## 2026-10-28 카드 여행 열 정보 밀도 개선 배포

- [PR #273](https://github.com/6Soo/cost/pull/273), main/운영 SHA `b54ca37c068ae8e830220652fe91978821978231`. 여행 열에는 이름·배정 출처만, 카드 식별은 가맹점 아래, 상태는 금액 아래, 상세는 별도 5번째 열로 분리했다. Luna low 초안 후 usage limit으로 Supervisor가 검수 보완했다. 통합 카드/필터/조회78 passed·인접15 passed·긴 이름/다섯 viewport/두테마/200%/키보드 검사 통과.
- 1009 Git blob 불일치0·task/process SHA·단일 loopback listener·health/ready200·OTA 기존/summary/events/groups401·보호13표 내용/스키마 전후 동일. 검증된 복구/별도 복원 근거와 직전 `22e134b4c98c60a68057b7caa8b14bf9f0b4b24b` 보존. 첫 배포 preflight는 동시 배포의 prior 변경으로 TASK_MISMATCH에서 쓰기 전 중단, 단일 작성자 조율 뒤 성공했다. 원본/금융/Google/여행 결정 쓰기·마이그레이션은 없다.
- 배포본의 전체 shell/테마를 포함한 합성 desktop/mobile light/dark 렌더·가로스크롤 후 상세 키보드 focus PASS. 실제 Aside 인증 UI는 AUTH_REQUIRED로 **NOT_ACCEPTED_AUTH_REQUIRED**이며 성공으로 계산하지 않는다. 근거: 호스트 해당 SHA release/deploy audit, 로컬 `.local-archive/card-trip-density-20261028/` 보호 전후·합성 HTML/PNG. 후속 운영 기록은 문서만 변경하므로 테스트·백업·재배포·재시작을 반복하지 않는다.

## 2026-10-28 미결 근거·반응형 검수와 클라우드 전환 준비

- 코드 `85817d1`은 전용 `cloud-mail/CloudMail.gs`, 명시 scope manifest, Drive 읽기·새 원문만 추가하는 `app/cloud_mail.py`, 분리 배포 준비 도구와 합성 검사를 추가했다. 기존 `apps-script/CloudMail.gs` 사용자 초안의 바이트/미추적 상태는 보존했다. 원문 전체·소유/비공개·SHA-256·부분재개·반복불변·원자적 무덮어쓰기·기존 importer 재시도·타 트리거/스키마/비관련 표 보존을검사했다. Node18 passed, cloud23+기존mail9=32 passed, 실제펼친 긴본문/카드·375/1280·두테마·100/200% CSSzoom·키보드·members409재조회/400오류 최종browser3 passed. UI제품코드/금융solver는 변경하지 않았다.
- 기존AppsScript를 별도폴더로clasp pull한 결과 CloudMail은미배포이고 기존GmailIngest자동수집은OFF다. 새 수집기는 기존 장부 프로젝트의 권한을 넓히지 않도록 **별도 프로젝트용 패키지로만 준비**했다. Windows Drive읽기ADC probe는`DefaultCredentialsError`다. 새 프로젝트/Drive폴더/권한·운영원문적재는 별도게이트를 통과하지 않아 아직미실행이며 기존Windows수집/Board를유지했다. 이는클라우드전환완료가아니다. [실행/복구 절차](specs/cloud-mail-cutover.md)를 기록했다.
- 실제운영Aside1425px·light/dark·100/200% CSSzoom4조건에서 각20행·문서가로넘침0·테마1개를 확인하고 기존테마를복원했다. Aside의viewport변경API는지원되지않아 물리적모바일/운영모바일viewport로과장하지않는다. 모바일viewport는위합성브라우저375px검사다.
- 환불추가읽기진단: 카카오39취소중29연결/10미연결, Agoda76중73/3, Trip카드취소전체186중171/15. Trip15중원승인번호12건의대응원결제는DB·보관원본8개·추가로컬628파일중고유카드파일1개에서발견되지않았다. 이전Trip1수치는특정사례로전체수치와구분한다. 원본/고객결정/금융/Google/예약작업쓰기는0이다. 로컬근거는`.local-archive/all-pending-20261028/`의집계파일이며 개인정보/원문은추적하지않는다.
- 이새경로는활성화전이므로 기존운영Board`9d5ddd5`·수집기`e15fd5e`를유지한다. Board동작을바꾸지않는선택형수집경로/테스트/문서추가를이유로Board재시작·재배포·전체회귀는하지않았다. 코드병합/합성검증·패키지준비와실제인증/클라우드활성화·원문적재/스케줄전환을구분한다.

## 2026-10-28 전체 대사·성능 최종 운영 수락

- [PR #250](https://github.com/6Soo/cost/pull/250)의 전체 대사 구현과 [PR #251](https://github.com/6Soo/cost/pull/251)의 조회 반복 검사 제한을 병합했다. 최종 Board 고정 SHA는 `9d5ddd521272acdebb294357d18a763d89ccfc60`, 수집기는 `e15fd5e2ab03ebf493cd90b24b3b6eeebfe2281d`다. 968 추적 blobs 일치·task/프로세스 SHA·단일 loopback listener·health/ready200·기존/summary/events/groups 비인증401의 배포 근거를 확인했다. 검증된 복구 사본과 이전 릴리스를 보존했다.
- NICE 영수증 원문3건은 검증된 백업·별도 복원 동등성·재입력 멱등성·스키마 동일·원문 저장6표 한정 변경으로 적재됐다. 원승인번호/날짜/금액/정상 카드 유일성으로 결제2건이 연결되고 취소 안내1건은 비금전 관측이다. 수집기 인자/일정을 보존했으며 강제 예약 실행은 하지 않았다. 이는 금융·여행·Google 결정 쓰기와 구분된다.
- 최종426세대 ready/fresh는 worker261.89초로 게시됐다(기존396.43초 대비33.9% 감소). 3,799사건을3,222그룹으로 표시하며577개/15.19% 줄었다. needs_action43·waiting_source820·evidence_missing2740·completed196사건, 경고29다. 최초423세대 이후 정상 수집 비금전2건이 더해졌고 기존3,794건의 금융 판정7필드는 동일하다. 그룹 축소는 보류/기장/실제 환급 해결 건수가 아니다.
- 인증 브라우저 왕복 각20회에서 summary p95 134.04ms/842B, groups157.10ms/22,318B, events139.32ms/7,656B를 측정했다. 예비 목표 summary150ms·page300ms·150KB를 충족했다. 첫/다음20그룹은 같은426세대·HTTP200·중복0이었다. server-only 또는 실기기 측정으로 확대하지 않는다.
- 실제 `/import`6경로: 숲나들e 예약 관계 후보5개 표본과 시설/금액 미확인·결제 분리, 여행 AUTO_INFERRED/수동 유지·퇴실일 미확인, 영수증 명시 승인번호와 카드 원행 연결, 취소안내의 실제 환급 분리/금융확정 버튼0, Trip2구성원과 개별 상세, Toyoko 예약 관계/결제 분리를 확인했다. 테마 버튼1개, 공개 forest49건 private 필드 노출0이다. 검수 스크립트의 선택자/필터 debounce 경합은 교정했으며 실패 시도는 통과로 세지 않았다. 화면 후에도 보호13표 내용/스키마는 배포 전과 같다.
- 기존 표적409 passed, PG/수집/브라우저144 passed+4 subtests, 마지막 국소41 passed, 조회 lifecycle/쓰기 보호89 passed 근거를 재사용했다. 코드 변경 없이 운영 수락과 문서만 정리했으므로 테스트·빌드·재배포·재시작을 반복하지 않았다. 실기기·200% 전 화면 검수는 새로 실행하지 않았다. 카카오10·Agoda3·Trip1의 미제공 원승인번호와 Agoda 카드 경합은 외부 근거가 필요한 잔여이며 금액만으로 확정하지 않았다.
- 로컬 증거: `.local-archive/cost-v34-resume-20261028/resume-runtime-report.json`, `resume-financial-comparison.json`, `resume-ui-report.json`, `resume-events-pagination.json`, `protection-resume-after-ui.json`, `forest-receipts-production-summary.json`, `mail-collector-receipt-deploy-summary.json`; 호스트 release/deploy evidence. 고객 원문·식별자는 추적 문서에 포함하지 않는다.

## 2026-10-28 숲나들e 본문 기반 예약 대사

- [PR #248](https://github.com/6Soo/cost/pull/248), 코드 `af8c0f7`, main/Board 고정 `3e59cf72b1ad41bbe3f8ea501362d97384fd10f5`. 사용자 최신 지시에 따라 DKIM 부재를 업무 보류로 삼던 표시를 정정했다. 직접 수집한 메일의 시설·객실·이용 시작일·명시 예약번호/금액을 읽으며 발신 인증은 참고 메타데이터다. 퇴실일·실제 결제일을 창작하지 않는다. 시설/주소 지자체·날짜 카드 후보와 기존 검증 여행 후보는 읽기 전용이고 수동 결정·금융 연결·Google 쓰기는 유지한다.
- 실제 보관47건 로컬 재생: 안내46건 중 시설/객실/시작일45건·주소 지자체26건·여행 후보가 있는 안내4건·카드 후보0건. 금액/번호/퇴실일 명시0건이다. 원문 해시 불변·query_only DB changes0을 확인했다. 고유 예약 수·카드 관계 확정·실제 환급 수락이 아니다. 누락 필드와 남은 미연결은 그대로 표시한다.
- 검증: forest/toyoko/core/detail85 passed(기존 partial-group1 제외), forest worker/수동 결정 보호/모바일 browser3 passed, 기존 queue browser 포함20 passed, 나머지 toyoko/candidate-read6 passed. 인접 실패3개는 분리 `beb7ca4`에서도 같은 문구 assertion/partial-group HOLD_NO_CARD·WinError32/과거 events-only browser fixture timeout으로 재현했다. 통과로 계산하지 않으며 원인 범위를 확대하지 않았다. compile/diff·staged guard 차단0/삭제0. 전체 회귀·실기기는 국소 읽기 변경이므로 미실행이다.
- 963 Git blobs 일치·배포 task/프로세스 SHA·단일 loopback listener·health/ready200·비인증 기존/summary/events/groups401·배포 직후 보호13표 내용/스키마 불변을 확인했다. 기존 검증 복구 사본과 이전 `787f00c`를 보존했다. 원문 재적재·수집기 변경·스키마 변경·금융/여행/Google 직접 쓰기는 없다. worker는01:51:57UTC 시작→01:58:34UTC 완료(396.43초),420세대 ready/fresh를 게시했다. 인증 groups/detail46건에서 시작일45·퇴실일 미확인45·여행 후보 안내4·인증 참고46·발신 미검증 문구0·카드 후보/연결0·private 필드 노출0을 확인했다. 실제 `/import` 상세의 본문·시작일·퇴실일 미확인·여행 후보·인증 참고·결제 미확정 표시, 카드미조회1개를 수락했다. 첫 테마 진단의 잘못된 selector0은 수정 진단 `#site-theme-toggle`1개로 구별하며 화면 후 보호13표도 배포 전과 동일하다.
- 로컬 근거: `forest-reconciliation-preview.json`, `protection-forest-reconcile-before/after-deploy/final.json`, `forest-reconcile-runtime-report.json`, `forest-reconcile-ui-report.json`, `forest-reconcile-theme-report.json`, release/deploy evidence JSON 및 Aside `artifacts/forest-reconcile-20261028/`. 읽기 기능/배포/필수 수락은 COMPLETE이며 카드 실제 관계·환급·귀속 저장 완료로 확대하지 않는다. 최종 기록만 갱신하므로 재배포/서버 재시작은 하지 않는다.


## 2026-10-28 숲나들e 예약 안내 관측 표시

- **최종 READY_UI_ACCEPTED（419세대）:** 실제 `/import`에서 첫20DOM·다음20DOM·페이지 변경·인라인 상세1개·카드 후보 미조회1개·theme1을 확인하고 임시 탭을 닫았다. 숲나들e needs_action/provider=forest API200·총46/첫20개·전원 발신 미검증 표시/RESERVATION_ONLY·금액/결제일/예약번호 없음, detail200·이용기간 미확정·카드 미연결을 수락했다. 미검증 evidence는 보수적으로 needs_action이며 evidence_missing 필터0은 누락이 아니다.419세대 실제 사건/그룹3,794/3,794·축소0이다. 원문·금융/Google 확정·테마 변경·카드 후보 조회는 하지 않았다. 세 번째 정상 계산은400.27초에 완료됐고 후속 동일key/held를 확인했다. 근거는 로컬 final-ui-report/final-forest-report와 post-ui-observation 보호13표 불변이다.

- [PR #246](https://github.com/6Soo/cost/pull/246), 코드 `8ef9566`, 최종 Board 고정 `787f00c05d0d0c46254ce6b448260eebdb93a01b`(아래 예약 그룹 포함). 기존 보관 메일에서 숲나들e 예약/결제 안내를 비금전 예약 관측으로 읽는다. 발신 도메인 경계를 검사하고 인증 미충족을 화면에 표시하며 예약번호/금액/이용기간/결제일은 생성하지 않는다. 추적 ID를 예약번호로 쓰거나 다른 안내의 취소를 전파하지 않는다.
- 합성 forest/toyoko39 passed·최종 발신 표시6 passed·compile/diff·staged guard 차단0/삭제0. 기존 보관47건 로컬 재생에서 안내46건·발신검증0/미검증46·RESERVATION_ONLY46·카드연결/생성 금액/예약번호/기간0·원문 해시 불변. 고유 예약46건이나 실제 결제 검증을 뜻하지 않는다. 누락된 예약 식별·금액·기간 확정에는 신뢰할 수 있는 추가 확인서가 필요하다.
- 962 Git blobs 일치·작업/프로세스SHA·단일 loopback listener·health/ready200·기존/summary/events/groups 비인증401·보호13표 내용/스키마 동일. 이전 `271f7e8`·task/gate·검증된 복구 사본을 유지했다. 원문 재적재·금융/Google 쓰기·스키마 변경·대량 재처리·메일 수집 작업 변경은 하지 않았다. 배포 중 남은 이전 release의 계산 자식은 부모 서버 부재·release/PID 계보를 확인한 뒤 해당 두 프로세스만 정리했고 현재 계산은 유지했다.
- **초기 배포 확인（이력）:** 새 worker가 계산 중일 때 인증 summary200/generation416/refreshing·groups409/SNAPSHOT_NOT_READY를 확인했다. 강제 재대사나900초 제한 변경은 하지 않았다. 실기기·전체 제품p95는 미확인이다. 근거는 해당 SHA release/deploy audit, 로컬 protection-forest-notice-before/after·forest-notice-preview-summary 및 Aside forest-deploy-smoke다.
- **READY_API_ACCEPTED（417세대）/ 아래419세대에서 UI 수락:** ready/fresh summary200·첫/다음 groups200 각20개·중복0·첫14,770B·detail200·private 필드없음, 검증된 그룹의 members200/같은세대/1개/preview1을 확인했다. 같은 세대의 브라우저 인증 왕복20회 표본p95는 summary191ms/groups213ms다. summary 예비150ms 목표는 미달이며 server-only/전체 제품SLA 수치가 아니다. 저장된418세대 집계는 사건3,794/그룹3,794로 실제 축소0이다. API 검증은 그룹 축소·보류 해결 완료를 뜻하지 않는다.
- 화면 수락 시 입력 key가 `8c629d33668e`→`db2767d1a932`(10:10:18)→`0c297902b27f`(10:17:26)로 바뀌어 정상 갱신 대기를 확인했다.417/418 계산은408.85/423.32초에 완료됐으며 금융13표는 화면 확인 후에도 불변이다. 정상 MailCollect 마지막 실행10:09:25/결과0은 확인했으나 각 key 변경의 전체 원인을 단정하지 않는다. 공개 legacy holds의 forest0은 기존 subset 계약이며 새 canonical queue 검증과 구분한다. API 최종 근거는 로컬 `aside-final-read-smoke.json`, `aside-member-smoke.json`이다.

## 2026-10-28 검증된 OTA 예약 그룹

- [PR #245](https://github.com/6Soo/cost/pull/245), 코드 `9be1479`, Board 고정 `271f7e827b7697d55a9eeaa38bdb53af709e68ad`. producer의 검증된 포털 출처만 예약 컨테이너로 묶고 기존 결제/환불 사건·ID·금액·수동 상태는 유지한다. 같은 세대의 summary/group/member index를 worker에서 계산한다. 목록/구성원 최대20개·미리보기 최대3개, singleton 직접 상세와 중복/누락 ID 차단, private provenance 공개/저장 제외를 연결했다.
- 지정 route/snapshot/group64 passed(구현자 근거 검수), queue browser8 passed, 기존 payment browser9 passed 및4 subtests, 금융/권한 인접74 passed. HTTP 플래그 UI2 failed 중 모바일1개는 분리한 `ccc2e40`에서도 동일 timeout을 재현했다. 실패를 통과로 계산하지 않았고 범위 밖 수정은 하지 않았다. compile/diff·staged guard 차단0/삭제0.
- 960 Git blobs 일치·작업/프로세스SHA·단일 loopback listener·health/ready200·비인증 기존/summary/events/groups401·보호13표 내용/스키마 동일. 이전 `f7c27c2`와 task/gate·검증된 복원 사본을 보존했다. 금융/Google/원문 직접 쓰기·마이그레이션·대량 재처리는 하지 않았다. MailCollect 고정 SHA는 `3b8bf15`로 유지한다.
- **초기 배포 확인（이력）:** 최초 인증 summary200은 generation416/refreshing, groups는409/SNAPSHOT_NOT_READY다. 새 private index가 준비되기 전 대기 표시가 유지된다. 초기 ready UI 대기는 위419세대 수락으로 해소했다. 실기기·전체 제품p95는 미확인이다. 로컬 근거 `.local-archive/cost-v34-resume-20261028/`의 protection-groups-before/after, release/deploy audit 및 Aside `artifacts/ota-groups-20261028/initial-smoke.json`.
- **Gmail 조사 정정:** 앞선 '46 iframe이 실제 본문' 추정은 응답 script 대조로 철회했다. iframe은 target URL 없는 열람 추적 코드다. 원래 Gmail HTML에 객실/날짜 문장이 있으며 원문 자체 분석으로 전환했다. 다른 공급자 정렬이 없는 DKIM pass만으로 숲나들e 인증 통과를 주장하지 않는다.

## 2026-10-28 숲나들e Gmail 원문과 상시 수집

- [PR #243](https://github.com/6Soo/cost/pull/243), 수집 작업 고정 릴리스 `3b8bf15581289ec83f1202a3bf11e62cafe53eb5`: forest.go.kr/foresttrip.go.kr 발신 검색 추가. 표적 9 passed, 957 blobs 일치와 배포본 query smoke 통과. WebLedger-MailCollect의 WorkingDirectory를 변경하고 기존 실행 파일·인자·계정·state 및 활성 상태를 보존했다. 이전 작업 XML·릴리스는 복구용으로 유지한다. Board는 아래 f7c27c2를 유지하며 이 변경으로 재시작하지 않았다.
- 기존 계정의 Gmail API full 메시지 47건을 전 페이지 수집했다. 본래 헤더·MIME·internalDate를 로컬 원문으로 보존했다. Aside Gmail 검색은 sync 준비 시간 초과로 실패했으며 기존 읽기 전용 API 설정을 사용했다. 신규 인증·비밀 변경은 없었다.
- 운영과 분리한 DB에서 47건 신규 적재·동일 입력 재적재 전체표 해시 불변, 별도 복원본 integrity/해시 일치를 확인했다. MailCollect 단일 작성자 게이트에서 검증 백업 후 운영 원문을 적재했다. 메시지는 3,226→3,273, 예약·예약증거·포털·카탈로그 행 불변, 스키마 불변이며 전체표 해시 변화는 원문 저장 6개 표에 한정됐다. 수집 작업 활성 복구를 확인했다.
- Gmail 본문은 47건 strict UTF-8 성공·대체문자 0이나 46건에 외부 본문 프레임이 있다. 프레임 내용 확인과 숲나들e 예약 파싱/표시는 아직 미완료다. 모든 메일의 인증 통과·예약 생성·결제 연결·여행 배정을 주장하지 않는다. 이전 다음메일 원문 4건과 Gmail 47건을 출처별로 구분한다.
- 로컬 근거: `.local-archive/cost-v34-resume-20261028/`의 gmail-forest-collection/preflight/preview/production/body 관련 집계, 검증 백업·복원본, mail-task-before-recurring-deploy.xml, mail-collector-deploy-summary.json. 고객 원문·계정·경로/ID는 Git에 추가하지 않았다.

## 직전 확인된 운영 코드

**`f7c27c240576e4fa0bb1dfa8f053cb7a4c451332`**, 2026-10-28. 분류자 Cost V34의 요구를 재개해 [PR #237](https://github.com/6Soo/cost/pull/237)의 Agoda 경쟁 원문 오류 유일성 보호, [PR #238](https://github.com/6Soo/cost/pull/238)의 명시 메일 입력 0건/잘못된 형식 쓰기 전 거부, [PR #239](https://github.com/6Soo/cost/pull/239)의 진단 출력 유한 코드·기존 파일 보존, [PR #240](https://github.com/6Soo/cost/pull/240)의 카드 검색 공통 버튼·아이콘 및 화면 수락 보완을 병합·고정 배포했다.

- 실제 검사: 금융 표적/인접 170 passed(일부 통화 검사 중복 포함), 메일 적재 18 passed, 진단 출력 52 passed, 카드/장부 81 passed, 수입 통합 21 passed 및 3 subtests, 수동 테마/날짜·가맹점 비중첩/375·1280·200% 보완 browser 1 passed. Supervisor는 diff·기존 보호 검사 근거를 검수했고 유효한 검사를 반복하지 않았다. 실기기·제품 p95는 NOT_RUN이다.
- 먼저 `6386e354cdf2f1bbb263b5569cb3a4e2fbae96b2`로 PR #237을 배포하고 956 blobs·health/ready200·보호 API401·실행SHA·단일 listener·13표 불변을 확인했다. 이후 현재 SHA의 957 blobs·같은 운영 경계·13표 내용/스키마 동일을 확인했다. 복구 사본/복원 검증 근거와 직전 task/gate를 보존했다. 초기 후보 archive 완료 전 preflight는 audit 파일 부재로 쓰기 없이 중단됐으며 archive 완료 후 정상 배포했다.
- Aside 인증 `/cards/all` GET200에서 공통 조회 버튼·SVG 아이콘·테마버튼1개를 확인했다. 실제 원문/금융/Google/여행 결정 쓰기·스키마 변경·대량 재처리는 하지 않았다. 보관4건이 인증 메일이 아닌 UI 캡처라는 사실을 확인했으며 이를 Gmail 입력으로 위장하지 않았다.
- 실제 카드 취소 읽기 전용 대조: Agoda 76건 중 확정73/미연결3, 카카오39건 중 확정28/추론1/미연결10. 두 공급자의 미연결건은 모두 원승인번호가 없다. 이 집계는 원결제 부재나 실제 환급 완료를 뜻하지 않는다. SQLite `mode=ro`/`query_only=ON`, `total_changes=0`. 기존 “카카오 미연결11”은 이 조회에서 10이며 코드/실자료 시점 차이를 보존한다.
- 근거: 각 SHA의 `D:/WebLedgerHost/releases/release-audit-<SHA>.json`, `deploy-evidence-<SHA>.json`, `.local-archive/cost-v34-resume-20261028/`의 보호 전후·읽기 진단 집계. 예약 그룹 runtime은 별도 진행 중이며 이 릴리스에 포함하지 않았다. 아래 PR #233은 직전 완료 릴리스 이력이다.

**`94ed610fd5393c1ff2d4329ac4f7f301009e729a`**, 2026-10-28 [PR #233](https://github.com/6Soo/cost/pull/233), 코드 `63dd532`. 실제 `/import` 검토 패널을 canonical summary와 기본20건 페이지에 연결했다. 상세/카드 후보는 인라인 lazy 조회이며, 제안은20개씩 읽는다. worker private detail map과 제한된 그룹 순서 대응 근거는 같은 generation에 게시하고 인증 detail GET은 O(1)로 읽는다. 원문·카드 후보 목록·private map/signing key를 공개 snapshot이나 persistence에 추가하지 않는다.

- 상세/UI/lazy/preview-race20 passed, 마지막 경합/세대/cursor3 passed, 기존 browser9 passed와4 subtests, 카드후보4 passed. 인접검사115 passed/2 failed 중 candidate browser fixture는 새 API 계약으로 교정 후4 passed; 기존 partial-group HOLD_NO_CARD/WinError32는 기준 `a6f4abc` 재현 근거를 유지하고 통과로 계산하지 않았다. compile/diff와 staged guard 차단0/삭제0. 전체 회귀는 국소 조회/UI 변경으로 생략했다.
- 한국어 표시·미확인 집계·singleton fallback 안내·세대 불일치 폐기/재조회·필터 되돌림과 미저장 제안/예약 선택·늦은 polling 응답 보호를 검수했다. 합성375/1280·수동light/dark·200% reflow/키보드 focus와 실제 코어 preview/confirm/once/approve·원거래 불변을 검사했다. 실제 기기·제품p95·보류 solver 개선/전면 리팩터링 완료는 아니다.
- 956 blobs 일치·작업/프로세스SHA·단일loopback listener·health/ready200·보호API401·2DB/13표 내용/스키마 동일. 직전 `af42ea0`와 task/gate·검증 복원 사본 보존. 금융/Google/원본 직접 쓰기·마이그레이션·대량 재처리는 하지 않았다.
- 배포 전 `af42ea0`의 generation405 ready에서 첫/다음 페이지 각20개HTTP200을 확인했다. 배포 직후는 persisted405/refreshing이며 새 private index가 준비되기 전 화면의 대기 표시를 확인했다. **COMPLETE / READY_UI_ACCEPTED** — generation406 ready/fresh에서 첫/다음페이지HTTP200·각20개·같은세대·ID교집합0·첫응답7,658B, detail200/같은세대·제안200/0개를 확인했다. 실제UI도20DOM→다음20DOM·페이지변경·상세lazy/카드미조회·전체holds API호출없음·theme버튼1개를 수락했다. 문자열 탐지 신호는 실제JSON key 경로로 재확인해 비공개필드없음을 확인했으며, 미지원 Aside wait API로 중단된 초기 smoke 대신 `ready-smoke-final.txt`를 최종근거로 삼는다. 실제확정/테마변경 없이 임시탭을 닫았다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-94ed610fd5393c1ff2d4329ac4f7f301009e729a.json`, 같은SHA release-audit, `.local-archive/ota-paged-ui-20261028/` 보호 전후·aggregate-only smoke. 기존 사용자 미추적3경로와 stash를 보존했고 새 worktree를 만들지 않았다. 병행 인계 구현자 `26175585`는 같은 파일 중복 작성을 중지시켰고 이전 Supervisor에게 메시지/재개하지 않았다. 문서 후속만으로 재배포하지 않는다.

## 직전 OTA page API 릴리스

**`af42ea097a9a9c9b242b0a630421b42ca8b7ff0d`**, 2026-10-28 [PR #230](https://github.com/6Soo/cost/pull/230). canonical summary와 같은 join 행을 worker에서 분류·정렬해 메모리 index로 게시하고 인증된 `/api/imports/ota/events`는 기본 needs_action20개를 반환한다. HMAC cursor는 세대·snapshot·필터·limit에 묶인다. GET에서 재대사·분류·index 생성·후보 조회는 하지 않는다.

- 통합 paging/route/summary/snapshot74 passed, 최종 페이지21 passed（조회 전 malformed query400 추가4개）, 기존 holds/cards/auth 선택2 passed. compile/diff·guard 차단0/삭제0. 기존 partial-group baseline 실패는 재실행하지 않았다. UI 미연결의 조회 변경이라 전체 회귀·UI 브라우저는 생략했다.
- 추적954 blobs 일치·작업/프로세스SHA·단일loopback listener·health/ready200·기존/events 비인증401·보호13표 동일. 직전 `bcb2b7c`·task/gate·검증 복원 사본 보존. 금융/Google/원본 직접 쓰기·마이그레이션·대량 재처리는 실행하지 않았다.
- 초기 Aside 인증 events GET409·138B·SNAPSHOT_NOT_READY（generation403/refreshing）를 확인했다. 실제 ready20개/cursor 연속 조회 수락은 새 세대 게시 후 확인한다. 합성100k precompute10.43s/page0.0026s/peak156,787,065B/payload6,034B는 제품p95가 아니다. q는선택index O(n)검색, index/key는메모리전용이고 restore 직후409·restart구cursor400이 가능하다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-af42ea097a9a9c9b242b0a630421b42ca8b7ff0d.json`, 같은SHA release-audit, `.local-archive/ota-queue-pages-20261028/` 보호 전후·aggregate-only GET. UI 및 제품 성능 수락은 남아 있다. 문서 갱신으로 재배포하지 않는다.

## 직전 OTA canonical summary 릴리스

**`bcb2b7cfbfc28e536f2727bda677268237ab248c`**, 2026-10-28 [PR #228](https://github.com/6Soo/cost/pull/228). Worker의 full canonical source/result를 보수적으로 결합해 queue summary를 미리 계산·세대와 함께 저장하고, 인증된 `/api/imports/ota/summary`는 저장 집계만 읽는다. 원본 경고·digest 변경·중복/누락/orphan 및 solver 필드 누락은 완료로 올리지 않는다. 기존 holds/lazy cards/POST 경계를 유지한다.

- 통합 지정3파일73 passed/1 failed. partial-group fixture의 HOLD_NO_CARD 판정 차이와 임시DB WinError32는 변경 전 `a6f4abc`에서도 동일 단일검사로 재현했다. 실패를 통과로 계산하지 않았다. 최종 신규 summary24 passed·compile/diff·staged guard 차단0/삭제0. 전체 회귀·UI browser는 국소 조회 변경이며 UI 미변경이라 생략했다.
- 추적951 blobs 일치, 작업/프로세스SHA·단일loopback listener·health/ready200·기존 및 summary 비인증API401·보호13표 동일. 직전 `a6f4abc`와 task/gate·검증 복원 사본 보존. 금융/Google/원본 직접 쓰기·마이그레이션·대량 재처리는 실행하지 않았다.
- 초기 Aside 인증 GET200·477B, generation402는 refreshing 중이며 이전 persisted snapshot에 summary가 없어 unavailable/counts=null/non-authoritative를 반환했다. 이는 새 canonical 집계의 ready 수락이나 제품 성능 측정이 아니다. Aside의 직접 로컬파일 저장은 경로 제한으로 거부되어 응답의 안전한 집계 필드만 Supervisor 셸로 보존했다. 사용자 페이지 탐색·입력·테마 변경 없음.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-bcb2b7cfbfc28e536f2727bda677268237ab248c.json`, 같은 SHA release-audit, `.local-archive/ota-canonical-summary-20261028/` 보호 전후 및 aggregate-only GET 기록. 페이지/cursor/UI와 ready 성능 수락은 남아 있다. 문서 갱신으로 재배포하지 않는다.

## 직전 OTA 순수 queue projection 릴리스

**`a6f4abc12f23ff2fdc50c7a26f4f26ce1dfd7b6d`**, 2026-10-28 [PR #225](https://github.com/6Soo/cost/pull/225). 독립 순수 OTA queue classification/summary 모듈을 추가했다. freshness·경고·충돌·유효 identity와 알려진 성공 근거로만 대사 검토 완료를 분류하며 canonical/public_subset coverage와 singleton fallback을 명시한다. API/UI·solver·store에는 연결하지 않았다.

- 지정 합성60 passed·compile/diff·staged guard 차단0/삭제0. 배포본 합성 complete/warning/stale duplicate/subset 스모크 통과. 합성10k 0.2368s/2,287,945B·100k 2.7025s/24,632,608B는 구현자 계측이며 제품 p95가 아니다. 국소 독립 모듈이므로 전체 회귀·브라우저는 생략했다.
- 추적950개 blobs 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 직전 `d230e12`와 작업 XML·게이트·기존 검증 복원 사본을 보존했다. 배포 전후2DB/13표 내용·스키마 동일. 금융/Google/고객 원본 직접 쓰기·마이그레이션·대량 재처리는 실행하지 않았다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-a6f4abc12f23ff2fdc50c7a26f4f26ce1dfd7b6d.json`, 같은 SHA release-audit, `.local-archive/ota-queue-projection-20261028/`의 보호 전후. summary/events API·pagination·UI 및 성능 목표 달성은 미완료다. 문서 갱신으로 재배포하지 않는다.

## 직전 RF-201 테마 버튼 릴리스

**`d230e124b27f268de8e8e3812abe53885e5e2212`**, 2026-10-28 [PR #222](https://github.com/6Soo/cost/pull/222). 두 공통 스타일의 테마 버튼 크기를 `--shell-theme-control-size:44px`로 모았다. 각 소비의 fallback도44px이며 색상·우선권·DOM/JS·단일 아이콘 테마 동작은 유지한다.

- manual-theme/mobile-topbar5 passed, 익명 baseline/current CSS24조건（375/1280px·light/dark·100/200%·결합/개별fallback）동일. 결합 스타일은44×44px/확대88×88px, 버튼 개수·색상도 동일. diff 검수·guard3파일 차단0/삭제0. 실제 기기 수락은 미실행이다.
- 추적948개 blobs 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 직전 `b3cabe8`와 작업 XML·게이트·기존 복원 검증 사본 보존. 배포 후2DB/13표 내용·스키마 동일. Aside 인증 탭의 같은-origin GET200에서 token기본44px·8개 소비·테마버튼1개 확인. 사용자 페이지를 탐색/새로고침하거나 입력·테마를 바꾸지 않았고 고객 본문은 보고서에 기록하지 않았다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-d230e124b27f268de8e8e3812abe53885e5e2212.json`, 같은 SHA release-audit, `.local-archive/rf201-theme-control-20261028/`의 보호 전후·`deployed-render-smoke.json`. 국소 CSS token 추출이므로 전체 회귀는 생략했다. 원본/Google/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음. 전체 RF-201/202 완료나 실제 기기·200% 전체 화면 수락이 아니다. 문서 갱신으로 재배포하지 않는다.

## 직전 RF-002 거래 읽기 릴리스

**`b3cabe8b38b2956381a8827327445cfa30b64c35`**, 2026-10-28 [PR #220](https://github.com/6Soo/cost/pull/220). 거래 batch/summary/row 반환 구조의 정적 타입 계약을 연결했다. 실제 출력 키는 required·nullable 값은 별도로 표현하고, counts는 미래 상태 문자열을 허용한다. SQL·조회/변환/집계 본문과 facade 동작은 그대로다.

- 합성pipeline 표적3 passed/42 deselected·4함수 실행AST동일·compile/diff 통과. Supervisor가 required/nullable 구분과 열린 count alias를 교정했다. guard5파일·차단0/삭제0（이전 운영 기록 포함）. 배포본 annotation 해석·required 키·합성 fake-store 배치/금액/선행0 ID/nullable/미지 상태 counts 스모크 통과. 스모크의 DB 접근은 없다.
- 추적948개 blobs 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 직전 `42999af`와 작업 XML·게이트·기존 복원 검증 사본 보존. 배포 후2DB/13표 내용·스키마 동일. 운영 DB/Google/원본/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음. 본문 불변의 정적 타입 변경이므로 전체 회귀·브라우저는 생략했다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-b3cabe8b38b2956381a8827327445cfa30b64c35.json`, 같은 SHA release-audit, `.local-archive/rf002-transaction-read-20261028/`의 보호 전후·`deployed-smoke.json`. 전체 RF-002 DTO/정책 채택과 실제 사례 수락 완료를 뜻하지 않는다. 문서 갱신으로 재배포하지 않는다.

## 직전 RF-002 OTA 상태 읽기 릴리스

**`42999afa15373014c35be9ee10fda308a6dd1e3c`**, 2026-10-28 [PR #219](https://github.com/6Soo/cost/pull/219). OTA 상태 helper의 입력 필드를 좁은 TypedDict 읽기 계약으로 명시했다. 실행 본문·상태 순서·caller freshness gate는 그대로이며 wrapper·snapshot 복사·정책 변경은 없다. 타입 선언은 runtime 검증이나 불변 snapshot을 제공하지 않는다.

- 표적 projection/golden/canonical28 passed·compile/diff 통과, docstring 제외 실행 AST 동일. 합성1000결과+1000후보 출력 동일; 30회 중앙값 baseline0.052944s/변경0.053033s·peak156,994/156,946B. 제품 지연 개선을 주장하지 않는다. guard3파일·차단0/삭제0. 배포본 annotation 해석·exact/group/reservation 상태/None 스모크 통과.
- 추적947개 blobs 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 직전 `361d012`와 작업 XML·게이트·기존 복원 검증 사본 보존. 배포 후2DB/13표 내용·스키마 동일. 운영 DB/Google/원본/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음. 실행 본문이 같은 정적 계약 변경이므로 전체 회귀·브라우저는 생략했다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-42999afa15373014c35be9ee10fda308a6dd1e3c.json`, 같은 SHA release-audit, `.local-archive/rf002-ota-status-read-20261028/`의 보호 전후·배포본 스모크. 전체 RF-002나 사용자 개별 사례 해결 완료가 아니다. 뒤따르는 문서 갱신으로 재배포하지 않는다.

## 직전 RF-002 OTA 계약 릴리스

**`361d012d495f9a3a245e092933e4102967689642`**, 2026-10-28 [PR #217](https://github.com/6Soo/cost/pull/217). RF-002 독립 OTA 상태/근거 DTO다. 호출자가 event/result/snapshot/projection 종류를 명시하고 예약관계·카드검증·여행·core-link 근거·환불근거를 분리한다. 내부 기장 상태는 만들지 않으며 기존 runtime에는 연결하지 않았다.

- 최종 합성16 passed. 검수에서 모양 기반 의미 추정·core_link의 기장 오분류·예약 축 추가필드 누락을 교정했다. guard3파일·차단0·삭제0. 배포본 합성 import/왕복·명시적 종류에 따른 상태 분리·입력 변경 차단·기장/환급확정 비창작 스모크 통과.
- 추적946개 blobs 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 이전 `179acb5`와 작업 XML·게이트·기존 복원 검증 사본 보존. 배포 후2DB/13표 내용·스키마 동일. DB/Google/원본/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음. 미연결 순수 adapter이므로 전체 회귀·브라우저는 생략했다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-361d012d495f9a3a245e092933e4102967689642.json`, 같은 SHA release-audit, `.local-archive/rf002-ota-contract-20261028/`의 보호 전후·`deployed-smoke.json`. 실제 읽기 경로 채택과 전체 RF-002 완료는 다음 단계이며 문서 갱신으로 재배포하지 않는다.

## 직전 RF-002 거래 계약 릴리스

**`179acb59dbe22dc28b982c8a2d16f5c7de8ed05c`**, 2026-10-28 [PR #215](https://github.com/6Soo/cost/pull/215). RF-002 거래 상태 DTO와 mapping adapter의 독립 기반이다. 원본/무결성/분류/사용자결정/revision을 분리하고 지원 값의 정확한 왕복·불변 snapshot을 제공한다. 기존 실행 경로에는 연결하지 않았으며 실제 금융·여행 정책 채택 완료가 아니다.

- 최종 합성13 passed. 공개 생성자·중첩 가변 입력·bytearray·custom type/cycle·key/timezone 경계를 검수했다. guard3파일·차단0·삭제0. 배포본을 직접 import해 합성 원행의 왕복·입력 변경 차단·정확한 모듈 SHA 경로 스모크 통과.
- 추적944개 blobs 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 이전 `44421df`와 작업 XML·게이트·기존 복원 검증 사본 보존. 배포 후2DB/13표 내용·스키마 동일. 고객 원본/DB/Google/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음. 런타임에 연결하지 않은 순수 모듈이므로 전체 회귀·브라우저는 생략했다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-179acb59dbe22dc28b982c8a2d16f5c7de8ed05c.json`, 같은 SHA release-audit, `.local-archive/rf002-transaction-contract-20261028/`의 고정 배포·보호 전후. RF-002 전체 채택·R0 미확인 운영 경계 해소로 확대하지 않는다. 다음 문서 전용 갱신으로 재배포하지 않는다.

## 직전 RF-003 소스 참조 릴리스

**`44421df083f6eb7447bbfe4dc0ad10e4fb4039ca`**, 2026-10-28 [PR #213](https://github.com/6Soo/cost/pull/213). RF-003 보호 도구에 선택적 소스 참조 조사를 추가했다. 기본 metadata-only preflight와 애플리케이션 런타임·스키마·금융 규칙은 유지한다.

- 기존19개 보호 검사에 내부 symlink/scan0 경계를 추가했다. 확장 실행20 passed/1 fixture 준비 실패 후 fixture 교정·해당1 passed로21개 근거 확보. 미해결 assertion 실패 없음. guard3파일·차단0·삭제0. 배포본 CLI exit0: metadata942·소스504·정확참조99·source 오류0. 자료 본문·SQL·관계없는 문자열 비출력, 내부/외부 간접 경로 읽기 차단. 정적 후보만으로 producer/consumer/active_use·민감도 안전을 확정하지 않는다.
- 추적942개 blob 일치, 작업/프로세스 SHA 일치·단일 loopback listener, health/ready200·보호API401. 직전 `f7df4bc`와 작업 XML·게이트·기존 검증 복원 사본 보존. 배포 후2DB/13표 내용·스키마 동일. DB/Google/원본/금융 상태 직접 쓰기·마이그레이션·대량 재처리 없음. 독립 도구 변경이므로 전체 회귀·브라우저는 생략했다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-44421df083f6eb7447bbfe4dc0ad10e4fb4039ca.json`, 같은 SHA release-audit, `.local-archive/rf003-source-references-20261028/`의 보호 전후·배포본 CLI 집계. 고객 자료 분류·운영 활성 여부 확정 및 전면 리팩터링 완료가 아니다. 이후 문서 변경으로 재배포하지 않는다.

## 직전 RF-001/004 후속 릴리스

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

## 공식 코드 배포 진입점 (RF-005, 2026-10-28)

검증된 SHA 릴리스와 이전 검증 릴리스, review.json 및 보호13표 기준선을 준비한 뒤 저장소 루트에서 `tools/deploy_verified_release.ps1`을 사용한다. 기본 호출은 `PREVIEW`와 `executed:[]`만 반환하고 host/task/review에 접근하지 않는다. 실제 전환은 기존 코드 배포 승인과 게이트를 충족한 경우에만 같은 인자에 `-Apply`를 명시한다. 필수 인자는 `-CandidateSha`, `-PreviousSha`, `-ReviewEvidence`다. 동일 SHA나 불완전 SHA는 전환 전에 거부한다.

기준선은 `python tools/verify_protected_release_state.py --evidence-dir <검수디렉터리> --phase before`로 준비하며 이 도구는 운영DB를 mode=ro로 연다. 배포기는 새 백업·별도 복원 검증 후에만 `switch_verified_release.ps1`로 task를 전환한다. 작업/프로세스/단일loopback listener와 health/ready·보호API, 보호13표를 확인한 근거는 기존 `deploy-evidence-<SHA>.json` 형식으로 남긴다. 실패 시 검증된 이전 릴리스 복귀 경계를 유지한다. 스키마 변경·원문 적재·금융/Google/명단 쓰기·대량 재처리용 진입점이 아니다. 기존 역사적 lightweight DB전환 스크립트는 이 코드 배포 경로와 구별한다.

## 제한된 코드 배포물 preview (RF-003)

`python tools/code_release_manifest.py --sha <정확한40자SHA>`는 메타데이터 preview만 수행한다. `--output <새ZIP경로>`를 명시하면 Git의 해당 SHA blob에서만 코드·승인 정적 자산·공통 규칙 설정을 새로 묶으며 기존 경로는 덮지 않는다. 원본/과거 출력/비공개 호스트 설정/테스트는 패키지에서 제외하고 저장소에는 그대로 보존한다. 알려진 라이선스 폰트는 경로·blob·크기가 모두 일치할 때만 대용량 예외를 허용한다.

이 산출물의 표시는 `BUILT_NOT_RUNTIME_ACCEPTED`다. source 안의 비밀값 검사나 동적 운영 의존성의 완전한 수락을 의미하지 않으며 `CODE_RELEASE.json`도 `runtime_accepted:false`를 유지한다. 공식 운영 릴리스 교체 전에는 격리 통합과 실제 런타임 입력 경계를 별도로 검증한다. 과거 전체 Git 릴리스의 검증 기록을 새 제한 패키지의 수락으로 대체하지 않는다.

## 문서만 바꾸는 경우

diff·링크·현재/과거 구분·실제 문서 참조 경로만 확인한다. 코드 테스트·빌드·브라우저·운영 DB 확인·백업·재배포·서버 재시작은 하지 않는다. 이전 기록의 유효한 검증을 단순 안심 목적으로 반복하지 않는다.

## 과거 근거 찾기

- [운영·검증 전문](history/operations-through-20261027.md): 이전 `operations.md` 전체와 10월7일 이전 기록, 메일 조사.
- [구현·검토·계획](history/implementation-and-audits.md): 각 변경의 표적 명령·실패 비교·화면 수락 경계.
- [제품 결정·옛 인계](history/product-and-handoffs.md): 이전 상태표와 정책 변경 당시 기록.
- [옛 경로별 위치](history/README.md#옛-경로-찾기): 통합 전 파일명으로 검색.

과거 기록의 운영 SHA·미구현·HOLD는 해당 시점의 근거다. 현재 런타임 또는 새 개발 권한으로 해석하지 않는다. 콘솔 창 다음 예약 실행 수락은 여전히 NOT_RUN이다.

## 2026-10-28 전용 클라우드 수집 실제 초기화

- 사용자 승인 아래 기존 전용 프로젝트를 재사용했다. 최초 Gmail 403 accessNotConfigured를 Gmail v1 고급 서비스 manifest로 수정했고 원격 소스/manifest 일치를 확인했다. PR #256 main d37b33c, Node20·인증 Python14 passed. 기존 importer32/browser3의 통과 근거를 재사용했다.
- Apps Script 초기화는 13:57:18 시작, 261.337초 정상 완료. 14:07 상태 조회에서 configured=true·원문76·last_complete=null·트리거1을 확인했다. 소유자/비공개 검증도 통과했다. 초기 전체탐색은 완료되지 않았다.
- 별도 host Drive readonly 인증은 Google 미확인 앱 동의 화면에서 사용자 직접 동의 대기다. 전용 ADC는 아직 없으며 기존 인증 파일을 덮지 않았다. 사용자에게 필요한 실제 인증만 요청했다.
- 기존 Gmail 예약 수집은 유지했다. 호스트 원문 적재·DB 변경·금융/여행 결정·최종 Google 장부 쓰기·작업 전환·Board 재시작은 수행하지 않았다. 백업/복원 게이트는 실제 적재 직전에 새로 적용한다. 전체 전환 완료로 보고하지 않는다.
- 로컬 근거는 Git 제외 all-pending-20261028의 cloud-live-deployment-evidence.json·cloud-status-initial.txt다. 소유자/프로젝트/폴더 ID와 OAuth 원문은 게시하지 않는다.

## 2026-10-28 호스트 Drive 인증 수락·백필 준비

전용 Drive readonly ADC를 새 파일로 저장하고 실제 Drive about200/소유자 일치·비공개 폴더 목록을 검증했다. 최초76건은 모두 기존 로컬 원문으로 미리보기 new0/appended0, 전체탐색은 미완료다. 전체 대상3,704건에 대해 클라우드 수집 배치를 순차 재개했다. 기존 자격 증명을 덮지 않았다. 호스트 전달기는70f247e의980 Git blob 일치·전용 실행기의 preview를 확인했으며, 기존 MailCollect 작업/운영 DB/장부는 아직 변경하지 않았다.

백필의 원문별 반복 Drive 검색/manifest 쓰기를 줄이는 보완은 Node24 passed로 검증했다. 원문 설치 후 checkpoint를 묶되 페이지·시간 종료·실패에서 flush하며, 미완료 그룹과 orphan 원문을 재검증한다. 초기76건/261.337초와 실제 개선 배치 측정은 구분한다. 초기 부적절한 비동기 브라우저 runner는 AbortError를 확인해 중지하고, 현재는 한 번에 한 UI 명령/클라우드 실행만 수행한다. Google 원문/프로젝트·폴더ID/자격 증명은 추적하지 않는다.

## 2026-10-28 RF-201 장부 자산 책임 분리 배포

- PR #262, main/운영 SHA `4e537766fa201ff4c2e58e9117efc5162e6e92c7`, 이전 검증 릴리스 `9d5ddd521272acdebb294357d18a763d89ccfc60` 보존. STYLE/SCRIPT를 CSS/JS 파일과 import 시 1회 읽는 소유 모듈로 분리했다. 폰트/OTA 자산 함수와 테마·DOM·palette·렌더 결과는 그대로다.
- 수집된 검사: 자산5·인접55 passed, 선택기8 passed. Supervisor가 공개 기준 원래 모듈과 STYLE32,235B/SCRIPT21,055B 및 생성 HTML의 정확한 동일성을 확인했다. source-theme4 passed/2 failed는 기준과 같은 실패다. 전체 회귀/브라우저 matrix는 바이트 동등성 때문에 반복하지 않았다.
- 실제 배포: 984 Git blob 불일치0, 작업/프로세스 SHA와 단일 loopback listener 일치, health/ready200·보호 API401. 보호13표의 내용·스키마 전후 불변. 실제 배포본 Python에서 STYLE/SCRIPT import·해시 smoke 통과. 기존 검증 백업/별도 복원 근거와 이전 릴리스를 재사용했다.
- 운영 HTML의 Aside 확인은 CDP `DOM.enable` timeout으로 미수락이며 성공으로 계산하지 않는다. 배포 자체의 SHA/health/auth/보호 검사와 구별한다. 운영 DB·금융/여행/Google 결정 쓰기·클라우드 원문 적재·수집 스케줄 전환은 이 배포에서 하지 않았다.
- 근거: `.local-archive/refactor-parallel-20261028/assets-supervisor-equivalence.json`, `protection-assets-before.json`, `protection-assets-after.json`, 호스트 `release-audit-4e537766fa201ff4c2e58e9117efc5162e6e92c7.json` 및 동일 SHA deploy-evidence. 고객 원문·계정·폴더 ID는 추적 기록에 넣지 않는다.


## 2026-10-28 RF 병렬 추출 통합 배포

PR #263/#265~#270/#272의 저장소·보드·카드·검토 문서 책임 분리를 검수 후 Board SHA 22e134b4c98c60a68057b7caa8b14bf9f0b4b24b로 배포했다. 이전 검증 릴리스 4e537766fa201ff4c2e58e9117efc5162e6e92c7 보존. 통합108 passed/3 subtests, 기존 개별 동등성 근거 재사용, guard 차단0/삭제0. 1,009 Git blob 일치·작업/프로세스SHA·단일listener·health/ready200·보호API401·보호13표 불변 확인. 실제 고객 원문 적재·금융/여행/Google 결정 쓰기·마이그레이션 없음. 원격 백필만 재개했으며 수집 전환은 미완료. 근거는 .local-archive/refactor-parallel-20261028/protection-before.json 및 protection-after.json, 호스트의 동일 SHA release-audit/deploy-evidence JSON이다. 운영 화면 수락은 별도 후속 검사다.


## 2026-10-28 RF 통합 후보 배포 실패와 복귀

후보535b6dd3178758a5a442eb6a8e7b0d60517a5cb3(1018 blobs 일치)는 배포 entrypoint OWNER_UI_ROLLED_BACK으로 종료했다. 이전 검증 b54ca37c068ae8e830220652fe91978821978231 작업 인자·health/ready200 복귀와 보호13표 불변을 확인했다. 성공 배포로 계산하지 않는다. 후보 시작 로그가 없고 포괄 catch로 최초 원인이 감춰져 작업 시작/준비 단계 진단을 진행한다. 원문/금융/여행/Google 쓰기 없음.


## 2026-10-28 RF 통합 후보 재검증 배포 성공

535b6dd3178758a5a442eb6a8e7b0d60517a5cb3 재배포 성공:1018 blobs 일치,실행SHA·단일listener·health/ready200·보호API401·보호13표 불변. 이전 b54ca37 복구점 보존. 최초 실패/복귀 기록 유지. IgnoreNew 종료 상태 확인과 준비 대기/실패단계 기록을 보완한 로컬 observed 실행기를 사용했고 호스트 원래 배포기는 미변경. 최초 원인을 확정하지 않는다. 호스트 동일 SHA deploy-evidence 및 .local-archive/refactor-parallel-20261028/protection-before.json/after.json 근거. PR280/281은 이 릴리스 뒤의 검수 병합이며 아직 미포함. 원문/금융/여행/Google 쓰기 없음.


## 2026-10-28 generation 5 검수 통합 배포

main/운영9f6eec7a66be1fae7ee4b8d761c5c4e81d070b1e 고정 배포 완료(PR #280~#285 포함). 이전 검증535b6dd 보존. requirements51·HTTP98·멱등성66/3subtests·selector8과 기존 개별 동등성 근거 재사용.1,034 Git blob 일치·작업/프로세스SHA·단일loopback listener·health/ready200·OTA 보호API401·보호13표 전후 불변, data guard base 차단0/삭제0. 기존 검증 백업/별도 복원 근거 재사용. 원문/금융/수동 여행/Google 결정 쓰기·마이그레이션 없음. 운영 인증 화면·실기기 수락 및 전체 RF 완료와 구별한다. 호스트 동일SHA release-audit/deploy-evidence와 로컬 protection-before/after.json이 근거다. 항공권 PR #286 이후와 PEND04 실제 클라우드 전환은 이 배포에 미포함이다.

초기 generation5 기록의 새 한글 문구가 PowerShell 기본 파이프에서 ASCII 물음표로 바뀐 것을 발견했다. 기존 문서는 보존됐으며 해당 새 운영 절과 현재 큐를 UTF-8로 복구했다. 코드/금융/원문 데이터 변경과 관련 없는 문서 인코딩 교정이다.


## 2026-10-28 후속 검수 릴리스 322ef3f 배포

322ef3f62ec3ec631f551b8b805ccb848e65feb1 고정 배포 완료(PR #286/#288/#289/#290 포함).1,041 blobs 일치·task/processSHA·단일loopback listener·health/ready200·OTA 보호API401·보호13표 내용/스키마 불변. 이전9f6eec7 복구점과 기존 검증 백업/별도 복원 보존. 항공권71·변경 검증70/3subtests·provider135/105subtests·토큰 인접20/1deselected와 작업자 baseline CSS matrix4검사 근거 재사용. 원문/금융/수동 여행/Google 쓰기·마이그레이션 없음. PEND04 bounded CLI PR #291은9c3a88b 별도 전달 릴리스로1041blob 검증 후 읽기 전용 전체 preview를 시작했으며 원문 적재/작업 전환은 아직 미실행이다. 호스트 동일SHA deploy-evidence/release-audit 및 로컬 protection-before/after.json이 배포 근거다.

## 2026-10-28 PR #295 운영 배포와 단일 환불 적용 대기

PR [#295](https://github.com/6Soo/cost/pull/295)은 `496cbbe9778e002bc4265f28b50da704d28f042c`로 정상 병합·운영 배포했다. 릴리스 파일 1,051개가 Git blob과 일치하고 task/process SHA, loopback listener 1개, health/ready 200, 보호 API 401을 확인했다. 새 백업·별도 복원 검증이 통과했고 배포 전후 보호 테이블 13개는 동일하다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-496cbbe9778e002bc4265f28b50da704d28f042c.json`과 `.local-archive/refactor-parallel-20261028/protection-before.json`, `protection-after.json`이다.

사용자는 검증된 단일 환불 그룹만 적용하도록 승인했다. Aside owner 화면은 AUTH_REQUIRED여서 미리보기·적용은 수행하지 않았다. 정상 owner 로그인 뒤 정확히 승인된 두 행만 대상으로 하고 다른 분류·기록·여행 배정이 없음을 확인한 경우에만 적용한다. 관측한 두 행은 같은 import batch이므로 교차 배치 경로의 운영 실행 근거가 아니다. 운영 장부·고객 원문·Google 장부에는 쓰지 않았다.

환불·금융 표적 74개 통과 근거를 재사용했다. 넓은 검사 묶음의 실패 13개 node ID는 기준 SHA ba74ab8에서도 모두 실패했으며 통과로 간주하지 않는다. 상세 기록은 `.local-archive/refactor-parallel-20261028/pr295-review.json`에 있다.

<!-- integration-progress-start -->
## 2026-10-28 최신 병합·정리 진행

- 사용자 최신 지시로 검증된 PR·브랜치 통합과 운영 코드 배포를 진행한다. 금융 데이터 적용은 기존 단일 환불 그룹 승인과 정상 owner 인증 범위다.
- PR #297 `e1a6c7b`, RF 통합 PR #298 `fe12cf4`, 지출 필터 PR #299 `ad11701` 정상 병합. 환불 83개·인접 보호 38개, RF 통합 99개와 26 subtests, 최종 필터/환불 통합 21개를 각각 통과했다. 서로 다른 검사를 합산해 전체 회귀로 표현하지 않는다.
- 로컬 병합 브랜치 97개 정리, 원격 병합 브랜치 93. 모든 삭제 대상 커밋은 `refs/archive/20261028/`에 보존하고 main·사용 중 브랜치·stash는 보존한다.
- 별도 원본 이력인 로컬 6개·원격 명세 8개는 과거 버전을 main에 다시 합치지 않고 `refs/archive/20261028/historical/` 및 검증된 `historical-branches.bundle`에 보관했다. 미병합 이력을 병합 완료로 표현하지 않는다. 옛 rf102 통합 공간의 변경 문서 2개도 `450f626` checkpoint와 파일 사본으로 보존했다.
- 통합·사용 종료 작업 공간 11개 공식 보관 및 디렉터리 제거 확인. 정리 처리 중 0개. RF201의 최초 API 300초 시간 초과는 공식 CLI 재확인 후 디렉터리 제거까지 확인해 해소했다. 검증이 끝난 임시 baseline worktree 2개도 보관 참조를 남기고 정상 제거했다. 활성 작업 공간과 미커밋 자료는 보존한다.
- 운영 확인 SHA: `61211012a0bbd250ab5e5fa6b629e3af9e672324`. 후속 PR #300은 `61211012a0bbd250ab5e5fa6b629e3af9e672324`로 병합했으며 실제 배포 완료 여부는 호스트 deploy-evidence를 따른다. RF 사전 점검·공통 UI·검사 게이트는 검증된 하위 묶음이며 전체 RF 완료가 아니다.
- 다른 세션의 사용자 명시 선택인 “명세 대기 기능까지 모두 포함”이 질문 이벤트와 응답 전달 `ab4efea4-875b-400e-82ad-7e0aa69a5a69`로 확인됐다. 추가 기능의 코드 구현·정상 검증 배포에 적용하며 실제 금융/여행/명단/보험/Google 쓰기 게이트를 확대하지 않는다. 기존 managed run의 27개 ID는 유지하고 추가 명세 작업은 별도 작업자 근거와 대조한다.
- 로컬 근거: `.local-archive/merge-cleanup-20261028/`의 refs/workspaces/progress 기록. 금융 적용은 AUTH_REQUIRED로 미실행이다.
- 참가자·항공 bundle `43588d9`(항공 `0cd571f` 포함)와 OTA `53d25fe`는 PR #300으로 통합했다. 통합 347 passed/31 subtests·인접 34 passed·선택기 48 passed. 기존 signed-session 6건과 폐기 Google/고정 자산 기준 26건 실패는 main `ad117015`에서 동일 재현했으며 통과에 포함하지 않는다. 데이터 guard 차단0·선택기 미매핑0·변경 Python20개 컴파일·diff 검사 통과. 잠정 배정 PA UI/API는 기존 부모 `4c407a16`가 단독 작성하며 새 작업 공간·유료 모델 전환 없이 이어간다.
- PR #300 고정 SHA `61211012` 배포는 1,077 blobs 불일치0·fresh backup/별도 복원·task/process SHA·loopback listener1·health/ready200·보호 API401·보호13표 전후 불변으로 수락했다. 근거는 `D:/WebLedgerHost/releases/deploy-evidence-61211012a0bbd250ab5e5fa6b629e3af9e672324.json`이다. 문서 후속 병합만으로 재배포하지 않는다.
<!-- integration-progress-end -->

## 2026-10-28 PR #302 잠정 여행 배정 검토 배포 완료

[PR #302](https://github.com/6Soo/cost/pull/302)은 `c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661`로 정상 병합·고정 배포했다. owner의 잠정 배정 검토와 20건 페이지, 명시적 보류, 저장된 원본별 교정 제안의 재검증·승인을 추가했다. 수동 결정·환불·원본 보호와 기존 결정 API를 유지한다.

통합 검수는 새 화면/금융 보호 226 passed, 권한/환불/우선배정/OTA 페이지·스냅샷 227 passed다. 변경 Python12개 compile·diff 검사 통과, 선택기 미매핑0, metadata guard 차단0/삭제0. 기존 CardFlow6개 실패는 작업자의 기준61211012 재현 근거를 보존하며 통과 수에 포함하지 않는다. 합성 HTTP/브라우저의 수락을 운영 실자료·실기기 수락으로 표현하지 않는다.

1,084 Git blobs 일치, 새 백업·별도 복원 검증, 작업/프로세스SHA·loopback listener1·health/ready200·보호API401·보호13표 전후 불변을 확인했다. 추가된 trip-review/proposals/hold 경로도 익명401이다. 이전 검증61211012 복구점을 보존했다. 배포 근거는 `D:/WebLedgerHost/releases/deploy-evidence-c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661.json`, 로컬 `.local-archive/merge-cleanup-20261028/deploy-c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661/`다.

실제 금융/여행 재배정·대량 재처리·명단 전달/보험가입·Google 쓰기·마이그레이션은 실행하지 않았다. PA-01 실자료 기준선 및 PA-06 실자료 shadow/수락은 미측정으로 남긴다. 단일 환불 그룹 적용의 정상 owner 인증 대기는 유지한다. 최종 확인 시 열린 PR은0개다. 후속 문서만의 병합에는 재배포하지 않는다.
# 2026-10-29 아오모리 일정 변경 통합

> **후속 사용자 결정:** 아래의 실제 백업·중지 이력은 보존하되 단순 여행 이동의 반복 절차로 삼지 않는다. 소수 귀속 교정은 변경 전 값·이력과 원자 저장으로 되돌린다. 별도 전체 백업/복원·서비스 중지는 복구가 어려운 작업에만 위험에 맞춰 적용한다. 현재 실행 기준은 [개별 거래 검토 실행 계약](specs/finance.md#review-execution-contract-20261029)이다.

- 사용자 지시와 Google 원본 metadata/제목 읽기로1103_아오모리,2026-11-03~08을 확정했다. 이전1104 여행의 장부18건6,425,040원·화면15행을 현재 여행으로 이동하고 이전 여행은 보관했다. 검토 중 취소 숙박 카드1건의 여행도 수동 교정했다. 여행/금액/카드 원본/기존 이력 삭제·Google 쓰기·은행 환급 확정은 없다.
- 후속 사용자 지시로 단순 변경 재승인을 생략하고, 같은날·금액이 일치하는 토와다소 예약 추가2건920,509원의 여행을1103으로 교정했다. 백업/복원/원자성 실패/멱등 리허설 후 기존 atomic review 경로로 적용했으며 원본/금액/범위 밖/스키마·과거 이력을 보존했다. 새 예약 유지 확인·금융 연결·장부 추가·실제 환급·Google 쓰기로 확대하지 않았다. `data/backups/towadaso-correction-20261029T045227214813Z/`의 rehearsal/apply JSON에 근거를 보존했다.
- 새 백업 및 별도 복원 동일성, 의도적 실패 전체 롤백, 복사본 rehearsal 후 운영 작성자를 정지하고 단일 SQLite 트랜잭션으로 적용. 스키마·범위 밖 데이터·금액/원본/ID·과거 감사/교정 이력 보존, 감사 체인/integrity PASS. 실제 runtime health/ready200·Board/SourceRefresh Running. 근거 `D:/WebLedgerHost/data/backups/aomori-merge-20261029T042712496764Z/` 및 로컬 `.local-archive/aomori-merge-20261029/`. 코드 배포와 구별한다.
- 후속 예약 메일 누락 방지 PR #322를 `9db468d42333979862b961fa26c822eb66260257`로 고정 배포했다. 검수 tree 동일·1108 blobs 불일치0·새 전체 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·보호API401·보호13표 전후 동일. parser/payment105·인접82·최종 후보10 tests passed, 원래 메일2건 readonly 추출 및 배포본/호스트 Python 합성 smoke PASS. 배포 후 위 통합 상태 유지·두 작업 Running. 최초 합성 smoke의 파이프 한글 손실은 UTF-8 파일 실행으로 수정했다. 실제 금융 재처리/Google/환급 쓰기0, 인증 운영 화면·전체 회귀 미실행. `.local-archive/trip-preauth-deploy-20261029/` 및 호스트 `releases/deploy-evidence-9db468d42333979862b961fa26c822eb66260257.json`에 근거를 보존했다. 문서 후속 병합만으로 재배포하지 않는다.
## 2026-10-29 취소·환불 표시와 보존 이력 배포

- [PR #326](https://github.com/6Soo/cost/pull/326), 운영 SHA `558c55e445902ebf0cc7e9031f88bd25e88794f8`. 검수 소스 `b6b2e4b28d3fdf75fced1fc5f503b2cd7b51c18d`와 merge tree 동일. 순액 0원 환불 묶음을 카드의 미배정보다 우선 표시·링크하고 미배정 필터/건수에서 제외한다. 정리 완료 기간의 원행도 읽기 전용 취소·환불 이력에서 표시한다. 부분환불·초과환불·원본 충돌·원결제 중복의 기존 보호를 유지한다.
- 카드 표적88 passed, 환불/원자 기록 보호24 passed. 결합 수집 시 카드 검사 모듈의 schema=require 환경 설정이 환불 fixture 초기화를 막았으며 별도 pytest 프로세스에서 통과했다. compile/diff·metadata guard 차단0/삭제0. 전체 회귀·실제 owner 인증 화면/실기기는 미실행이다.
- 1,109 blobs 불일치0, 새 전체 백업·별도 복원, task/process SHA·단일 loopback listener·health/ready200·보호 API401·금융/사용자13표 내용/스키마 불변을 확인했다. 호스트 Python으로 배포본의 보존 기간 전액 상쇄 그룹·카드 링크·검색·미배정 필터/건수·원행 불변 합성 smoke PASS. 이전 검증 `9db468d42333979862b961fa26c822eb66260257`와 복구 사본 보존. 금융/분류/여행/Google 쓰기·마이그레이션·재처리0.
- 근거: 호스트 동일 SHA release-audit/deploy-evidence, `.local-archive/deploy-558c55e445902ebf0cc7e9031f88bd25e88794f8/`의 검수/보호 전후/배포 evidence 및 `.local-archive/card-refund-destination-20261029/`의 checkpoint/runtime-smoke/auth-smoke. 후속 기록은 문서만 바꾸므로 재배포·재시작을 하지 않는다.

## 2026-10-29 원승인번호 없는 취소·환불 쌍 인정 배포

- [PR #332](https://github.com/6Soo/cost/pull/332)를 `dccd3af6d12a52a3f9eb50a647979527ac5cc1f7`로 고정 배포했다. 검수5587129와 merge tree 동일,1110 blobs 불일치0. 원승인번호 없이도 같은 발급사·카드·가맹점·이용일·동액의 상호 유일 대응과 기존 카카오 계열/기간 대조를 연결 완료로 인정한다. 자동 출처·근거를 표시하고 원본 오류·중복·경합·점유·초과환불·수동 보류·묶음 원자성·재기록 보호를 유지한다. 수동 보류 사유가 묶음 보류 사유로 덮이지 않도록 보존했다.
- 표적242 passed(핵심144·환불UI/owner/원자성/cross-batch89·CardFlow3·카드 목적지6), compile/diff 및 metadata guard 차단0/삭제0. baseline 비교2건·inline stale 기대1건은 기준d753f45에서 동일 실패했고 통과로 세지 않았다. 전체 회귀·실제 owner 인증 화면 수락은 미실행이다.
- 새 전체 백업/별도 복원·task/process SHA·단일loopback listener·health/ready200·OTA/환불 보호API401·보호13표 내용/스키마 불변. 호스트 Python 배포본에서 원승인번호 없는 대응·조회 원본 불변·합성 원자 기록 smoke PASS. 이전 검증de2aada와 복구 사본 보존. 실제 분류/기장/여행/Google/은행 환급 쓰기·재처리·스키마 변경0. 근거는 `.local-archive/refund-reference-optional-20261029/`, `.local-archive/deploy-dccd3af6d12a52a3f9eb50a647979527ac5cc1f7/`, 호스트 동일SHA release-audit/deploy-evidence다. 후속 문서만으로 재배포·재시작하지 않는다.

## 2026-10-30 카드 이용일·OTA 근거 교정

- [PR #361](https://github.com/6Soo/cost/pull/361)·[PR #362](https://github.com/6Soo/cost/pull/362), 운영 SHA `bc02ea4a1fb15523e0fcfd9d92f9c5bed37d6b21`. 현지 사용은 명시 국가와 이용일 거리를 지역명보다 먼저 평가하고 예약 이용기간/항공권 OTA 용도를 3820 잔여 분기 분류보다 앞세운다. 기존 수동 결정·원결제 환불·금융 보호는 유지한다.
- 두 행의 실제 교정은 별도 소수 교정 경계에서 source/revision/digest 및 단일 DB 트랜잭션을 검증하고 기존 거래/장부/화면 귀속을 함께 수정했다. 변경 전 값과 에이전트 근거를 기록했다. 실시간 Gmail의 결제/확정·같은 주문 PDF 영수증 확인을 사용자 확인으로 위장하지 않는다. 원본·금액·날짜·ID·범위 밖 행·기존 수동/금융/이력·스키마 불변, 새 장부행/금융 링크/Google 쓰기 0, 재요청 무쓰기 PASS. 사본 검증의 첫 카운터 오탐은 실제 적용 전에 교정했으며 실패를 통과로 세지 않는다.
- 결합 99 passed·호스트 합성 3 PASS. 배포본 1,126 blobs 일치·새 백업/별도 복원·task/process SHA·listener 1·health/ready 200·보호 API 401·보호 13표 코드 배포 전후 불변. 이후 인증 Aside 카드 상세 GET 2건으로 귀속/항목 표시 수락. Board/SourceRefresh Running. 전체 회귀·실기기는 미실행이다.
- 근거는 `.local-archive/classification-correction-20261030/`와 호스트 `D:/WebLedgerHost/releases/deploy-evidence-bc02ea4a1fb15523e0fcfd9d92f9c5bed37d6b21.json`이다. 이전 검증 `a69c0ae7389789a65d2ed01f3028c0348f52eb1f` 복구점을 보존했다. 카드 수집/업로드는 사용자 요청으로 보류했다. 후속 문서 변경만으로 재배포/재시작하지 않는다.


## 2026-10-30 여행 지출 금액 그룹·카드 화면·진단 입력 제한 배포

- PR384/385/386/387 정상 병합, 최종 운영 `509392e1558e3df1c31ccdbd2dfe676f5498051b`(이전 검증28853255). GEMN74·카드32·최종 후속25검사 통과; 인접56통과/10실패는 기준fc1e2022와 동일 실패로 구분했다. 원천 비교 불가를0건으로 취급하거나 상세 없는 버튼을 표시하던 실제 화면 문제를 보완했다.
- 1179 Git blobs 일치·검수/병합tree 동일·새 백업/격리 복원·task/process SHA·listener1·health/ready200·보호API401·보호13표 전후 불변. 실제 기존 Aside 인증 화면에서 정상 그룹 상세 열기와 미검증 원천 확인 불가/트리거0 수락. 운영 금융/Google/명단/원본 쓰기0.
- 근거: `.local-archive/open-pr-development-20261030/`와 `.local-archive/deploy-509392e1558e3df1c31ccdbd2dfe676f5498051b/`, 호스트 같은SHA deploy-evidence. OpenRouter free 오류 초안은 보존/감독자 검증, ANUS 결과는 통합. 실기기·전체 회귀·외부자료 대기는 미완료로 유지한다. 이 후속 문서 변경만으로 재배포·재시작하지 않는다.


## 2026-10-30 대조 안내·Google 행 기본 정렬·보험 후보 수정

- PR389/390 운영 `5ef006edb00a1b955520a07023e6c3fd7eb005bd`(이전 검증c2b4531e). 상단/하단 반복 안내와 상시 그룹 목록 제거·상태 클릭 상세 창, PC 일치/부분/미기록 및 첫 Google 행 기준 안정 정렬. 열린 상세 창의 모바일 전환 시 숨은modal 차단도 재현/교정했다. 복사 순서/원본/금융/수입 불변.
- 연속 가림 문자 길이 미확인 후보와 기간 추정 밖 다른 여행 후보를 구분했다. 실제159행의 단일41 유지·검토70·미일치48. PR389 기존 Aside 화면/API·owner/no-store·지출 정렬/상세 창 수락 재사용. 최종SHA 실제 화면 재수락은 Aside 미실행으로 대기이며 합성 반응형8검사는 통과. 표적78 passed·후속8 passed(겹침 합산 안 함).1180 blobs 일치·새 백업/격리 복원·고정task/process SHA·health/ready200·보호API401·보호13표 불변.
- `.local-archive/ledger-sort-insurance-20261030/` 및 `.local-archive/deploy-5ef006edb00a1b955520a07023e6c3fd7eb005bd/`·호스트 동일SHA 근거. 금융/명단/Google/원본 쓰기0, 실기기/전체 회귀 미실행. 후속 문서만으로 재배포/재시작하지 않는다.


## 2026-10-30 PR392 참가자 수입 화면 복구·모바일 카드 목록

- 운영 `d0d73f8aebed53674e2754dae665eb4dc30748ed`, 이전 검증5ef006ed. body/공통 셸·모바일 내부 스크롤·별도 이름 인덱스 없는 원본 수입·저장소 없는15행 조회를 복구하고, PR392의2줄 카드 목록을 검수/보완했다. 참가 명단 미연결을0명이나 완료로 해석하지 않는다.
- 묶음81통과/기존p50실패1·최종 참가자37통과(중복 합산 안 함), 기준main58통과/동일1실패·독립1통과.1181 blobs 일치·task/process SHA·health/ready200·보호API401·보호13표 불변. 데이터/스키마 쓰기 없는 code-only 배포로 전체 자료 백업은 반복하지 않았고 검증 이전 릴리스/task XML 복구 수단을 유지했다. 금융/원본/명단/Google 쓰기0.
- 기존 Aside 실제 참가자 화면15행/API200/no-store·카드32행·영향3경로 비인증401 수락. 근거는 `.local-archive/participant-mobile-20261030/`와 같은SHA deploy 근거다. 실제 참가DB/명단 등록·실기기는 미해결이며 문서 후속만으로 재배포/재시작하지 않는다.
# 2026-10-31 국내·해외 구분 여행 배정

- [PR #418](https://github.com/6Soo/cost/pull/418), 구현 `2b5fc5c4`, 고정 배포 `25cc29108cb44752b453832dca8e854747966558`. 해외 사용 국가와 여행 국가의 일치를 요구하지 않고 국내·해외 구분과 여행 기간으로 배정한다. 기존 수동/예약/금융 보호는 유지한다.
- 여행/분류50·보호88·추가 호환/원자성8 passed(중복 포함), 병합 tree 동일·1,197 blobs 일치. task/process SHA·loopback listener1·health/ready200·보호 API401·보호13표 불변. 이전 검증8ebb4d8b 복구점 보존. 코드 배포는 DB 무쓰기이므로 전체 백업/복원을 반복하지 않았다.
- 승인된 보류 거래2건 중10/24 1건만 `1020_알펜루트`로 실제 자동 추론 배정했다.10/25는 종료일 밖으로 보존했다. 단건 교정은 변경 전 값 로컬 보존·메모리 리허설·SQLite 단일 작성자 잠금·원자 저장으로 실행했다. 원본/금액/ID·금융/환불 링크·사용자 결정·범위 밖·스키마 불변, 감사 이력 보존/1건 추가·재실행0 확인. 초기 검증 오류는 쓰기 전에 중단했고 최종 검사 통과 후 적용했다. 장부 추가/Google/은행 쓰기0, 실제 환급 확인과 구별한다.
- 근거: `.local-archive/domestic-overseas-trip-20261031/`의 검사 XML·applied/http-smoke JSON, 같은 SHA deploy 디렉터리 및 호스트 release-audit/deploy-evidence. 복구 값은 호스트 `data/backups/domestic-overseas-trip-20261031/before.private.json`에만 보존한다. 전체 회귀·실기기·인증 owner 화면은 미실행. 두 작업 Running·영향 경로 익명401 수락. 요청 완료·미결0이며 문서 후속으로 재배포/재시작하지 않는다.


## 2026-11-01 OTA 결제일 미상·M:N 연결 배포 완료

- COMPLETE — 사용자 지적4건의 원인 조사·공통 수정·배포 OM01~OM05 완료. [명세·수락 근거](specs/ota-undated-many-to-many-20261101.md), [PR #435](https://github.com/6Soo/cost/pull/435)·[PR #438](https://github.com/6Soo/cost/pull/438), 구현 `1f070bb7`·`60cdacc2`, 운영 `eb1c408c1eac96f536b77f74bb489c54c024a63e`.
- 무날짜도 가맹점/확장명·정확 금액/통화·끝4 일치로 연결하며 조건 일치 관계를 M:N으로 보존한다. 카드 원행은 한 번만 집계하고 동일 예약의 관측을 결제 여러 건으로 더하지 않는다. 152,358원·395,000원은 기존에도 연결돼 있었으며 여행/환불 보류를 미연결로 설명한 오류와 취소 예약 카드 건수 누락을 바로잡았다.
- 정책312·인접 기장/환불90·최종 선택 보호2 passed 근거 재사용, 후속 게시 통합192 passed. 최초1131d2a0는 실제 갱신 실패 후f52e019a로 복귀했으며 최종 후보에서 수정·재수락했다. 배포본 전체 읽기 입력3,921이벤트/6,851카드에서5예약·6관측 관계 동일, 운영 ego-browser PC1440/모바일390×5예약 연결·무날짜/M:N/취소 표시·넘침0 수락. 기존 재현 실패6개는 통과에 포함하지 않으며 전체 회귀/실기기 미실행이다.
- 1,206 blobs 일치·task/processSHA·단일listener·health/ready200·보호API401·보호13표 불변. 기존ParticipantDb 유지, 이전f52e019a/task XML 복구점 보존. 원본/금융/여행/환불/기장/Google 쓰기·마이그레이션0. 코드전용이라 전체DB백업/복원 반복 없음. 미결0·다음 명령 없음. 로컬 근거 `.local-archive/ota-mn-policy-20261101/`; 문서만의 후속 병합에 재배포하지 않는다.

## 2026-11-02 항공권 여정 누락 교정 배포

- [PR #544](https://github.com/6Soo/cost/pull/544) 병합 SHA `a9b0617a132be8ea83328a8ac6a9345514efeffc`를 이전 검증 릴리스 `41843c45625a33d268c9d1540cf47b6a5fd756da`에서 공식 절차로 전환했다. 단일 항공편의 출발·도착 라벨을 해석하며 모호한 여정과 기존 수동 결정을 보호한다.
- 영향 QA 260건·skip 0, 호스팅 impact-checks 통과. 릴리스 1,293개 blob 일치, 새 백업·분리 복원 검증, health/ready 200, 보호 API 401, 보호 테이블 13개 불변. 배포 증거 `D:/WebLedgerHost/releases/deploy-evidence-a9b0617a132be8ea83328a8ac6a9345514efeffc.json`.
- 대상 카드 1건은 배포 전 AI 추론 경로로 원자 교정했고 거래·장부의 여행 및 출처를 읽기 전용으로 재확인했다. 색인 갱신 완료 후 인증 여행 화면에서 해당 출발일의 예약 1건을 확인했다. OTA 연결은 자동대사이며 사용자 확정이나 실제 환급을 뜻하지 않는다. Google 장부 쓰기는 수행하지 않았다.
## 2026-11-05 COST 관리자 UI/UX 종합 개선 배포 완료

- [PR #653](https://github.com/6Soo/cost/pull/653) 병합 커밋 `79a3c57340cfadeb227e3748966a4baf0fd6ca63`를 운영 반영했다. 이전 운영 SHA는 `37b82e5829a7b8a062e7a7e2a9fff7081bd3a737`이다. 반응형 관리자 화면의 레이아웃·타이포그래피·접근성·문구를 기존 디자인 시스템과 컴포넌트에 맞춰 개선했다.
- 영향 QA 699 passed·61 subtests·skip 0, PR CI `41935646283` 성공. 데스크톱/모바일 전후 화면 증거와 예외 상태 검토를 작업 archive에 보존했다.
- 운영 전환 결과: 1,383 tracked files, blob mismatch 0, task/process SHA 일치, gateway 8790 → backend 8751, 단일 loopback listener, health/ready 200, 보호 API 401. 보호 테이블 13개 전후 불변 PASS. `WebLedger-SourceRefresh`는 기존 `Ready` 상태로 유지됐다.
- 코드 전용 반영이며 금융/Google/원본 데이터 쓰기·DB 변경·마이그레이션·재처리 없음. 배포 중 활성 라우트 밖에 남아 있던 이전 릴리스 감독 프로세스를 SHA와 포트 소유자로 검증해 정리한 뒤 무중단 전환을 완료했다.
- 근거: 호스트 `D:/WebLedgerHost/releases/deploy-evidence-79a3c57340cfadeb227e3748966a4baf0fd6ca63.json`, 로컬 `.local-archive/admin-ui-ux-deploy-20261105/`.
