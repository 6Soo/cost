# 운영 기록과 실행 경계

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
