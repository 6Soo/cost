# 현재 상태와 남은 일

## 2026-10-29 카드 3820 자동분류 충돌 수정·운영 배포

- COMPLETE — [PR #335](https://github.com/6Soo/cost/pull/335), 수정 `dc2aaf3`, 운영 SHA `78cb6ad4a7ead4ecaff39671eb0a32090b4c8021`. 공통 자동분류에도 기존 3820 정책을 적용한다. 2026-09-19~24 유효한 싱가포르 여행 하나를 우선하고, 나머지 국내 매입은 거래일의 분기 기타비용으로 분류한다. 사용자 결정·완료 행과 해외/날짜 불명/취소·환불 보호를 유지한다.
- 정확한 배포 archive에서 자동분류 완료·3820 Singapore/residual/reconcile 38 passed. 운영 Python 합성 smoke 5개 PASS(2025년 거래→2025년 4분기 포함). 운영 venv에는 pytest가 없어 개발 Python으로 archive를 검사했다. 최초 stdin smoke는 PowerShell 한국어 전달 손실로 실패했으며 UTF-8 파일 실행으로 교정했다. 이전 인접 34 passed 근거는 재사용했고 전체 회귀·실제 owner UI·실자료 재분류는 미실행이다.
- 1110 Git blobs 불일치0·새 백업/별도 복원·task/process 고정 SHA·단일 loopback listener·health/ready200·OTA/환불/2025 카드 조회 비인증401·보호13표 내용/스키마 불변. Board/SourceRefresh Running. 이전 검증 `dccd3af6d12a52a3f9eb50a647979527ac5cc1f7`과 복구 사본 보존. 실제 분류/여행/금융/Google 쓰기·마이그레이션·대량 재처리0.
- 근거: `.local-archive/card3820-deployment-20261029/`의 checkpoint/runtime-smoke/auth-smoke, `.local-archive/deploy-78cb6ad4a7ead4ecaff39671eb0a32090b4c8021/`와 호스트 동일 SHA release-audit/deploy-evidence. 기존 사용자 변경·미추적 파일 보존. 현재 요청의 남은 구현/배포·차단0이며 다음 명령은 없다. 후속 문서만으로 검사·재배포·재시작하지 않는다.

## 2026-10-29 최신 요청 — 원승인번호 없는 취소·환불 쌍 인정

- 사용자 지시: 원승인번호는 취소·환불 쌍의 필수조건이 아니다. 동일 발급사·카드·가맹점·이용일·동액의 상호 유일 대응과 기존 카카오 계열/14일·외화 대응을 연결 완료로 인정한다. 자동 출처와 대조 근거를 표시하고 원승인번호 부재만으로 기록을 막지 않는다.
- 구현: 원화 유일 대응의 `inferred` 보류를 해제하고 승인번호와 독립된 대조 근거를 표시한다. 수동 보류 사유가 묶음 보류로 덮이지 않도록 보존한다. 원본·중복·후보 경합·점유·초과환불·불완전 묶음·원자 기록·재기록 보호를 유지한다. 양수 원행 없는 미매입 취소는 연결하지 않는다.
- COMPLETE — [PR #332](https://github.com/6Soo/cost/pull/332), 운영 SHA `dccd3af6d12a52a3f9eb50a647979527ac5cc1f7`. 검수 소스 `558712946f499a0b12a7523acd0d4faae15cdcbf`와 merge tree 동일. 핵심144·환불 UI/원자성/owner/cross-batch89·CardFlow3·카드 목적지6, 서로 다른 표적242 passed. 기존 baseline 비교2건 및 inline stale 기대1건은 기준d753f45에서도 실패해 제외했다. 전체 회귀·실제 owner 화면 수락은 미실행이다.
- 배포:1110 Git blobs 불일치0·새 백업/별도 복원·task/process SHA·단일loopback listener·health/ready200·보호API401·금융/사용자13표 내용/스키마 불변. 호스트 Python 배포본의 원승인번호 없는 유일 대응·조회 원본 불변·합성 원자 기록 smoke PASS. 이전 검증de2aada와 복구 사본을 보존한다. 실제 고객 DB 분류/기장·Google/은행 환급 쓰기·대량 재처리·스키마 변경0. 근거는 `.local-archive/refund-reference-optional-20261029/`와 `.local-archive/deploy-dccd3af6d12a52a3f9eb50a647979527ac5cc1f7/`, 호스트 동일SHA deploy-evidence/release-audit다. 구현/배포 남은 작업·차단0이며 후속 문서만으로 재배포·재시작하지 않는다. 다른 UI 병렬 변경은 보존했다.

## 2026-10-29 최신 요청 — 카드 행 상세·배지 제거·날짜와 폭 압축

- 현재 범위는 ‘원본 보존’ 표시 제거, 상세 버튼/열 제거 후 행 클릭으로 상세 이동, 셀 간격과 전체 폭 축소, 선택 기간과 중복되는 날짜 제거다. 날짜는 연도 조회 `3월 5일`, 월 조회 `5일`이며 시간은 붙이고 원본/title은 유지한다. 이전 원본 보존 배지·상세 열 유지 검사는 대체한다.
- COMPLETE — [PR #331](https://github.com/6Soo/cost/pull/331), 운영 `de2aada07320de57aee6935c7617f6d3102f017a`, 검수 소스 `4e8588a58eb262a2206fd5a7ce13a1bfe48f5292`와 merge tree 동일. 표4열·고정 열 폭·모바일 최소380px·셀5/4px, 중복 날짜 접두사 생략을 적용했다. 행의 날짜/금액/여행 셀 클릭은 기존 상세 URL로 이동하며 가맹점 이름의 실제 링크로 키보드/새 탭/JavaScript 없는 탐색을 유지한다. 환불 링크는 독립 동작하고 텍스트 선택 중에는 행 이동을 하지 않는다. 원본 보존은 내부 상태 그대로이며 배지만 제거한다.
- 최종 커밋 Git archive에서 카드/필터/환불 목적지/브라우저43 passed(동시 편집 중인 별도 금융 변경 제외).320/390/600/759/760/1280·두 테마·200% 확대·행 클릭/키보드·환불 독립 링크·텍스트 선택·날짜/title·원본 날짜 불변·표 폭 검증. 초기 신규 날짜 검사 의존성은 표준 re로 교정했다. compile/diff·metadata6파일 차단0/삭제0. 실제 인증 owner 화면/실기기·전체 회귀는 미실행이다.
- 1110 Git blobs 불일치0·새 전체 백업/별도 복원·task/processSHA·단일loopback listener·health/ready200·보호 API/연월/상세/환불URL401·금융/사용자13표 내용/스키마 불변. 배포본/호스트 Python의 단일 연월·4열/380px·배지/상세 열 부재·행 링크/스크립트·한국어 날짜/title·환불 링크·원행 불변 합성 smoke PASS. Board/SourceRefresh Running. 이전 검증 `537aa3bca7cec79debad4db92d67e94baa6934e6` 및 복구 사본 보존.
- 근거는 `.local-archive/card-row-navigation-20261029/`의 checkpoint/validation-source/runtime-smoke/auth-smoke와 합성 이미지·검증 archive, `.local-archive/deploy-de2aada07320de57aee6935c7617f6d3102f017a/`의 review/protection-before/protection-after/deploy-evidence, 호스트 동일 SHA release-audit/deploy-evidence다. 실제 DB/분류/금융/여행/Google 쓰기·스키마 변경0. 기존 사용자/다른 작업 변경 보존, 남은 구현/배포 작업·차단0. 후속 문서만의 변경에 검사/배포/재시작을 반복하지 않는다.

## 2026-10-29 최신 요청 — 카드 모바일 UI·연월 선택 통합

- 현재 승인 범위는 카드 전체 내역 모바일 개선과 누락됐던 월별 카드 제거·연월 선택 통합이다. 최신 교정은 **단일 거래 카드가 아닌 이전 표 방식 유지·내용 압축·간격 축소**다. 월 타일 유지와 모바일 세로 카드 검사는 이번 사용자 지시로 대체한다.
- COMPLETE — [PR #329](https://github.com/6Soo/cost/pull/329), 운영 SHA `537aa3bca7cec79debad4db92d67e94baa6934e6`, 검수 소스 `6f581aa3dd12e2a1797e24c8243068def6f77ae3`와 merge tree 동일. 월별 카드와 별도 연도 폼을 제거하고 단일 조회 기간 선택에 `2026년 전체 / 2026년 1월 …`을 제공한다. 기간 변경/검색 제출 시 카드·검색어·미배정 조건을 함께 보낸다. 연도 전체도 검색어 없이100건씩 즉시 조회하며 기존 year/month 링크·커서와 조회 API를 유지한다. 결과는 조회 조건 바로 아래에 나온다.
- 759px 이하도 실제 표/행/열 헤더를 유지한다. 최소 폭560px·셀 여백6/8px·글자12px·간격1.35, 이름 두 줄 압축·원문/title 보존·중복 날짜 그룹 숨김·표 내부 가로 스크롤을 적용했다. 부호/통화·여행/취소환불 상태·상세 링크와 검색/선택 입력16px·접이식 안내를 유지한다.
- 최신 표 구현의 카드/필터/환불 목적지/모바일42 passed. 실제 Chromium에서320/390/600/759/760/1280폭·두 테마·200% 확대·키보드 포커스에 의한 표 스크롤·긴 이름/title·환불 링크·행 높이110px 이하·페이지 가로 넘침 부재를 검증했다. 최종 합성 PNG는 `.local-archive/card-history-compact-table-20261029/`에 보존한다. 실제 인증 화면/실기기·전체 회귀는 미실행이다.
- 중간 릴리스 PR #328/`b933bdd84cf79d6c64e6f1d5093bc8b648865c7a`는 새 백업/별도 복원·1110 blobs 일치·health/ready200·보호API401·보호13표 불변으로 배포됐지만, 세로 카드이므로 최신 표 요청의 완료로 계산하지 않는다. 현재 표 구현을 검증 후 후속 배포한다.
- 최종 배포 수락:1110 Git blobs 불일치0·새 전체 백업/별도 복원·task/process SHA·단일 loopback listener·health/ready200·OTA/환불/연월 조회 URL 보호401·금융/사용자13표 내용/스키마 불변. 호스트 Python으로 실제 배포본의 압축 표 CSS·단일 연월 선택·연도/월 목록·월 타일 부재·환불 링크·원행 불변 합성 smoke PASS. Board/SourceRefresh Running. 이전 검증b933bdd 복구점과 백업 보존.
- 근거는 `.local-archive/deploy-537aa3bca7cec79debad4db92d67e94baa6934e6/`의 review/protection-before/protection-after/deploy-evidence, `.local-archive/card-history-compact-table-20261029/`의 checkpoint/runtime-smoke/auth-smoke와 호스트 동일 SHA release-audit/deploy-evidence다. 실제 DB/분류/여행/금융/Google 쓰기·재처리·스키마 변경0, 기존 사용자 변경 보존. 남은 구현/배포 작업·차단0. 후속 기록은 문서만 변경하므로 검사/배포/재시작을 반복하지 않는다.

## 2026-10-29 최신 승인 — 원본 보존·취소/환불 표시 교정

- 사용자 질문 후 “ㄱ”으로 승인한 표시 수정과 운영 배포 범위다. 카드 원행·분류·여행·금융/Google 값은 쓰지 않는다.
- COMPLETE — [PR #326](https://github.com/6Soo/cost/pull/326), 운영 SHA `558c55e445902ebf0cc7e9031f88bd25e88794f8`, 검수 소스 `b6b2e4b28d3fdf75fced1fc5f503b2cd7b51c18d`와 tree 동일. 기존 환불 연결의 순액 0원 묶음을 카드 목록의 여행 미배정보다 우선 표시하고 취소·환불 탭으로 연결한다. 동일 묶음은 미배정 필터/건수에서 제외한다. 보존 기간이라는 이유만으로 읽기 전용 환불 이력을 숨기지 않는다. 원본 보존의 의미와 실제 환급/장부 기록의 구분을 안내한다. 부분환불·초과환불·원본 충돌·원결제 중복의 기존 경계를 유지한다.
- 표적 카드 88 passed, 환불/원자 기록 보호 24 passed. 초기 결합 수집의 schema=require 설정과 환불 fixture 충돌은 pytest 프로세스를 분리해 해소했다. 전체 회귀·실제 owner 화면 수락은 미실행. `.local-archive/card-refund-destination-20261029/checkpoint.json`에 범위·검증·다음 단계를 기록했다.
- 배포 수락: 1,109 Git blobs 불일치0, 새 전체 백업·별도 복원, task/process 고정 SHA·단일 loopback listener·health/ready200·보호 API401·보호13표 내용/스키마 불변. 호스트 Python의 실제 배포본 합성 smoke에서 보존 기간 전액 상쇄 그룹·카드 링크·검색·미배정 필터/건수·원행 불변을 확인했다. 이전 검증 `9db468d42333979862b961fa26c822eb66260257` 복구점과 백업을 보존한다.
- 실제 금융/분류/여행/Google 쓰기·마이그레이션·재처리0. 기존 사용자 미커밋/미추적 파일 보존. 배포 근거는 `.local-archive/deploy-558c55e445902ebf0cc7e9031f88bd25e88794f8/` 및 호스트 동일 SHA deploy-evidence/release-audit, 영향 경로 근거는 `.local-archive/card-refund-destination-20261029/runtime-smoke.json`, `auth-smoke.json`이다. 남은 구현/배포 작업·차단0. 이 후속 문서만으로 테스트·재배포·재시작을 반복하지 않는다.

## 2026-10-29 최신 결정 — 개별 검토 재발 방지와 재개점

- 실행 정본은 [개별 거래 검토 실행 계약](specs/finance.md#review-execution-contract-20261029)과 AGENTS.md다. 근거로 결정 가능한 변경은 재승인 없이 처리한다. 소수 여행 이동은 변경 전 값·revision/이력으로 되돌리고, 별도 전체 백업·복원 리허설·서비스 중지를 기본 절차로 사용하지 않는다. 아래 토와다소2건의 백업/중지는 **실제로 수행했던 과도한 절차의 기록**이며 이후 단순 이동의 의무가 아니다.
- 완료: 기존 북큐슈 카드2건은 예약 연결·내부 장부 기록까지 반영됐다. 아오모리는 Google 현재1103(11/3~8)으로 통합했고 기존18개 장부/15개 화면행을 이동했다. 토와다소230,106원 및 추가2건920,509원은1103·숙박비 교정 완료다. **추가2건은 금융 링크/장부 추가 쓰기0**이며 예약 유지 여부를 사용자가 직접 확인한 것으로 쓰지 않는다. 메일 파서 수정은PR #322/운영9db468d로 완료됐다.
- 마지막 조회에서 아고다625,280원과-625,280원은 같은 카드의 원승인번호로 기존 전액취소 연결을 확인했다. 트립닷컴122,224원과-122,224원도 원승인번호가 일치했고 토요코인 대구 동성로10/4~5 예약·9/24 취소 메일을 확인했다. 둘 다 순액0이며 추가 사실 질문은 없다. **이번 확인은 읽기 전용이고 새 장부 기록은 하지 않았다.** 이 두 묶음을 새로 기장한 것으로 완료 처리하지 않는다.
- 다음은 기존53건 개별 검토의 나머지이며 전체 완료 건수를 새로 계산하지 않았다. 마지막 기준/확인 건은 로컬 `.local-archive/trip-candidate-review-20261029/next-item.json`에 보존했다. 기존 정상 연결·완료 교정은 재질문하지 않고, 실제 기록 여부와 남은 다음 거래를 구분해 진행한다. 이번 문서화는 코드/운영 데이터 변경 없이 문서 diff·링크·경로/상태만 확인하며 테스트·백업·재배포·서버 재시작을 하지 않는다.

## 2026-10-29 최신 결정 — 판단 가능한 변경의 재승인 불필요

- 사용자는 근거/규칙 부족으로 필수 사실을 묻는 것과 단순 변경 승인을 구분하며, 후자는 필요 없다고 지시했다. 기존 승인·데이터 안전 게이트 안에서 판단 가능한 분류/여행 교정은 바로 처리한다. 이 결정은 실제 예약 유지·환급 완료를 사용자 확인 사실로 만드는 권한이 아니다.
- 호텔 토와다소의 같은날 카드 원행·인증 예약 사전승인액이 일치하는 추가2건(합계920,509원)을11/7~8 숙박 기간과 현재 Google 여행에 따라1103_아오모리·숙박비로 교정했다. 개별 유지 여부를 확인받았다는 근거는 남기지 않았다. 새 백업·별도 복원·복사본 리허설·두 번째 건 실패 시 전체 롤백·동일 요청 재실행 불변 수락 후 Board/SourceRefresh를 정지하고 기존 atomic review 경로로 적용했다. 원본/금액/ID/범위 밖 행/스키마·기존 이력 보존. Google/환급/금융 링크/장부 추가 쓰기0. 근거 `.local-archive/towadaso-correction-20261029/` 및 `D:/WebLedgerHost/data/backups/towadaso-correction-20261029T045227214813Z/`. 전체53건 완료를 의미하지 않는다.

## 2026-10-29 최신 승인 — 아오모리 일정 변경 통합·예약 메일 누락 방지

- **통합 운영 적용 COMPLETE:** 사용자 확인으로 1104 아오모리는 1103으로 변경된 같은 여행이다. Google 활성 원본 metadata의 `1103_아오모리`(sheetId 514604255)와 B2:H3 제목을 직접 읽어 **2026-11-03~08**을 확인했다. 현재 원본에는 1104 탭이 없다. COST의 현재 1103 여행으로 이전 장부18건/6,425,040원·화면15행을 이동하고 이전 1104 여행은 삭제 없이 보관했다. 검토 중 취소 숙박 카드1건도 사용자 수동 결정으로1103에 교정했다. 실제 환급 완료·Google 반영을 창작하지 않았다.
- 새 백업/별도 복원·실패 주입 전체 롤백·복사본 리허설 후 Board/SourceRefresh를 정지해 단일 작성자로 같은 트랜잭션을 적용했다. 원본/금액/ID/범위 밖 행·기존 교정/감사 이력·전체 스키마 불변, 감사 체인·integrity_check PASS. Board/SourceRefresh 재개 및 health/ready200 확인. 고객 원문·과거 결정 삭제0, Google/환불/OTA 연결 쓰기0. 사전 검증과 실제 적용 근거는 호스트 `data/backups/aomori-merge-20261029T042712496764Z/`의 rehearsal/apply JSON과 복원 사본, 로컬 `.local-archive/aomori-merge-20261029/`다.
- **예약 메일 수정 COMPLETE:** PR #322 구현 `babd4df`·운영 `9db468d42333979862b961fa26c822eb66260257`. 온라인 사전 결제 문구가 없는 숙박도 예약 기간을 보존하고 사전승인액을 별도 필드로 읽는다. 같은 날·정확한 금액의 정상 카드 후보를 진단하며 사전승인만으로 실제 결제/환급/금융 연결을 확정하지 않는다. 수신 날짜가 잘못된 인증 취소 메일도 취소 사실·환불 요청을 보존한다. parser9로 기존 snapshot을 무효화한다. 표적105 passed, 인접 추론/상태/API82 passed, 최종 후보 조건 단순화10 passed. 원래 문제의 보관 메일2건도 readonly로 재확인해 사전승인액/이용기간·취소 추출을 수락했다. 검수/병합 tree 동일,1108 blobs 불일치0·새 전체 백업/별도 복원·task/processSHA·health/ready200·보호API401·보호13표 불변. 배포본/호스트 Python 합성 smoke PASS, 재기동 후 통합18건/6,425,040원·15행·대상카드 교정 유지, Board/SourceRefresh Running. 초기 합성 smoke의 PowerShell 파이프 한글 손실은 UTF-8 파일 실행으로 교정했다. 전체 회귀·인증 운영 화면은 미실행이며 실제 재처리/Google/환급 쓰기0. 근거 `.local-archive/trip-preauth-deploy-20261029/`와 호스트 동일SHA 배포 JSON. 기존53건 전체 완료를 의미하지 않으며 남은 개별 건은 사용자 검토 흐름으로 이어간다. 이 문서 후속 병합에는 재배포하지 않는다.

## 2026-10-29 동일일·동액 OTA 연결 및 사용자 확인 2건 반영

- **COMPLETE:** 사용자 최신 승인으로 동일 결제일·동일 통화 원문 금액이면 카드 끝자리/결제 ID/승인 별칭 없이도 연결한다. 명시된 카드·공급자 충돌/중복/오류/점유/부분 묶음 보호는 유지한다. 원문 외화액만 있는 사용자 확인 연결도 원화액을 창작하지 않고 저장한다. PR #320 구현 `2b2ea98`, main/운영 `f60e1a7225f834445491cab34f846622ec9ba120`, matcher version4. 관련214 passed + 별도 snapshot/authority32 passed, 보호13표 배포 전후 동일, health/ready200·보호 API401·1108 blobs 불일치0·새 백업/별도 복원 수락.
- **2건 실제 완료:** 사용자가 확인한 Trip 숙박 결제 2건만 기존 북큐슈 여행의 숙박비로 수동 교정·예약 연결·내부 장부 기록했다. 각 거래/장부행1개, 원문/ID/카드 끝자리·외화/원화 금액 보존·schema/범위 밖 행 불변을 복사본과 운영에서 검증했다. 동일 조건 2:2의 예약번호/승인번호 안정 순서 배정임을 근거에 기록했으며 개별 대응 독립 증거로 꾸미지 않았다. Google/은행 환급 쓰기0. 이는 기존53건 전체 완료가 아니다.
- **끝자리 조사:** 카드 원행에는 끝자리가 정상 존재한다. 해당 예약 메일은 VISA만 표시하며 마스킹 번호/끝자리 자체가 없고 보관된 예약 상세에도 없다. 파서 누락으로 보고하거나 예약 원문에 카드 끝자리를 역주입하지 않는다.
- 실제 근거: `D:/WebLedgerHost/releases/deploy-evidence-f60e1a7225f834445491cab34f846622ec9ba120.json`, `D:/WebLedgerHost/data/backups/trip-confirm-20261029T041040263786Z/`의 rehearsal/apply-evidence 및 보존/복원 사본. 로컬 복사본은 `.local-archive/ota-same-day-amount-20261029/`. 최초 복사본에서 검토 API의 부수적인 테이블 생성을 발견해 운영 미적용했고 기존 스키마 경로로 재검증했다. 최초 운영 시도의 DELETE journal 전환 잠금은 금융 데이터 원복 확인 후 기존 journal 유지로 해결했다. 최종 Board/SourceRefresh Running 및 인증 Aside 카드 화면의 대상2건/새 여행/끝자리 표시를 수락했다.
- 후속: 이 최신2건 범위는 완료다. 남은 개별 거래 검토는 사용자와 이어가며 과거 queue/완료 보고를 새 승인으로 확장하지 않는다. 이전 인계의 환불 `4fbff06` 로컬 커밋은 이번 PR에 포함하지 않았고 이 기록만으로 배포 완료를 주장하지 않는다. 후속 문서 변경은 재배포하지 않는다.

## 2026-10-29 최신 요청 — 카드 검색 결과·금액 검색·배치

- 현재 범위는 검색 0건 안내, 금액 검색, 월 선택 없는 즉시 결과, 좁은 화면 필터 배치의 네 항목이다. 과거 금융/환불·전체 미결 큐를 이번 변경에 포함하지 않는다.
- 네 요구사항 모두 COMPLETE — [PR #318](https://github.com/6Soo/cost/pull/318), 운영 SHA `0c285e14bb87d4a843d1860159cc2be35ed2aa8a`. 검수 소스 `2989613f9e837c02bd353d19135f1eb79da013d5`와 병합 tree가 동일하다. 검색어가 있고 월이 없으면 해당 연도의 날짜 있는 거래를 100건씩 표시한다. 0건도 검색어와 결과 영역을 표시한다. 월 선택 상태는 해당 월의 검색 범위를 유지하고 날짜 확인 필요 목록은 기존 별도 경계를 유지한다.
- 원화/외화 금액의 쉼표 유무와 승인번호를 검색하며, 검색 결과도 여행명·미배정 표시·카드 마스킹·필터/커서 보존 규칙을 따른다. 검색창에 금액 검색을 안내하고 모바일 필터를 세로 배치한다.
- 검증: cards_all_filters/cards_all/card_transactions 81 passed와 신규 browser 선택기 오류 1 failed 후, 페이지 안의 별도 여행 검색창과 구별하도록 선택기를 한정해 해당 browser 1 passed/25 deselected. 합성 Chromium에서 검색 제출→즉시 1건→0건, 긴 여행명, 320/390/760/1280폭과 기존 확대 검사를 확인했다. DB 원행 전후 동일·연도/카드/미배정/페이지 경계 검사를 포함하며 전체 회귀는 범위 밖이다.
- 기존 브랜치의 미병합 환불 커밋과 미커밋 card_flow/OTA browser 수정·사용자 미추적 파일은 보존한다. 이번 검색 PR에는 포함하지 않는다. diff/compile·metadata guard5파일 차단0/삭제0, 정상 main 병합·고정SHA 배포 완료. 1,107 Git blobs 불일치0, fresh backup/별도 복원, task/processSHA·단일loopback listener·health/ready200·보호API/검색URL401·보호13표 전후 불변, Board/SourceRefresh Running을 확인했다. 배포본/호스트 Python 합성 smoke도 금액/외화/승인번호·즉시/0건·HTML escape·원행 불변 PASS다. 초기 합성 smoke의 임시 SQLite 정리 잠금은 연결 종료를 보완해 해소했다. 실제 owner 인증 화면/물리기기 수락·전체 회귀는 미실행이며 금융/Google 쓰기·재처리·마이그레이션0이다. 근거는 `.local-archive/card-search-20261029/`의 review/runtime-smoke/auth-smoke/protection-before/protection-after/deploy-evidence JSON 및 호스트 동일SHA release-audit/deploy-evidence다. 남은 검색 작업·차단0. 후속 문서만의 병합에는 재배포하지 않는다.


## 2026-10-29 최신 승인 — 이미지의 프로젝트 전체 미결을 Luna low 병렬 구현

- **DEPLOYED — PR #316:** 검수 소스 `a6b73ae5c01403c0ff41ea133bf0a9cec5100b0e`와 운영 `1beba48bdd4f0aa20999326689d7c766c921c576`의 tree가 동일하다.1,107 blobs 불일치0, 새 전체 백업/별도 복원, task/process SHA, 단일 loopback listener, health/ready200, 참가자 state/trip-panel·OTA groups 등 보호 API401, 금융/사용자13표 내용·스키마 불변을 실제 확인했다. Board/SourceRefresh Running. 직전 검증9b190e9 복구점 보존. 실제 분류/금융 재처리·명단 실전송·Google 쓰기·메일 원문 다운로드·마이그레이션0. 아래 미배포/다음 배포 표기는 이 수락으로 대체한다.
- **남은 실자료 경계:** latest manifest 재확인 `2026-10-29T01:58:27Z`도3,710 stored/48 pending/다음 페이지 있음/미완료다. 전환 재확인 조건은 pending0·다음페이지 없음·query없음·유효 last_complete 및 실제 원문/복원/단일 작성자 게이트다. 현재 보험 구성의 참가DB 파일 부재·실제 웹 프로세스 DB 동일성/등록 영수증·운영 화면 수락은 미해결이며, 실제 등록 영수증과 현재 연결 DB가 확인되면 readonly 진단으로 재개한다. 외부 결제 증빙 없는 Kakao 금융 연결을 창작하지 않는다. 보험 가입·결제·실명단 전송은 별도 기존 권한을 유지한다.
- **완료 범위와 미완료 구분:** 보험 재개 계약, 참가자 진단/CLI 불일치 보호, 전체 메일 전환 gate, 여행권위3메서드 분리, OTA 공통 스타일, 실패 진단 도구의 이번 구현은 병합/배포됐다. 전체 백엔드·전체 화면·전체 회귀·실제 참가자/수입 수락 완료를 의미하지 않는다. 기준8cfe391에서도 재현한 browser11 실패는 통과로 계산하지 않으며 후속 검수 기록으로 남긴다. 정확한 운영 근거는 `.local-archive/deploy-1beba48bdd4f0aa20999326689d7c766c921c576/`의 review/protection-before/protection-after/deploy-evidence/affected-path-smoke JSON와 `D:/WebLedgerHost/releases/deploy-evidence-1beba48bdd4f0aa20999326689d7c766c921c576.json`. 이 기록만으로 테스트·DB 확인·재배포를 반복하지 않는다.

- **최신 검수 체크포인트:** COST PR #316, 구현 `7944826`·`5f8c0c9`·`d1dc436`·`6c3e1cc`·`7f055e8`. 아래 진행 중 표기는 이 체크포인트로 대체한다. 추가 browser session23926은 **30 passed / 11 failed / 18 subtests passed**로 종료했다. 격리 Git archive 기준 `8cfe391`의 카드/OTA browser도 동일 node/subcase **11 failed / 18 passed / 2 subtests passed**(323.72초)이며 shell/assets 12개를 포함하는 현행 묶음과 구별한다. 기존 실패를 pass로 숨기지 않는다. 폐기된 별도 기록 버튼·수동 질문·배치 선택/전체조회·예전 문구와 canonical snapshot 준비 문제는 기존 실패로 기록한다. 금융 보호는 그대로다.
- 진단 도구는 SUBFAILED별 중복 제거/건수 및 PowerShell UTF-16 redirect를 추가 처리하며 최종 **7 passed**다. 최종 참가자 schema/손상 영수증 검사는5 passed, OTA 검토 API39 passed다. 실제 근거 `.local-archive/wide-pending-20261029/validation.json`, `baseline-browser.txt`, `baseline-browser.xml`.
- 중단 WIP는 통합본과 구별하는 `refs/archive/20261029/wide-luna-*`로 보존했다. managed workspace6개 모두 clean/보존 참조 확인 후 공식 archive·디렉터리 제거 수락. 실제 증거 `workspace-preservation.json`. COST는 아직 미배포이며 다음은 최종 diff/guard→PR #316 정상 main 병합→검증 SHA 고정 배포다. Travel INS PR #10/main은 이미 병합 완료다. 현재 ready 구현을 실제 보험/명단·메일 전환·전체 리팩토링 완료로 확대하지 않는다.

- 사용자가 미결표를 제시한 뒤 다수 Luna low에게 바로 구현하라고 명시 지시했다. 범위를 자동분류/환불로만 축소하던 해석을 교정한다. 대상은 보험 전달/운영 DB 동일성/참가자·수입 수락 준비, 원결제 외부 근거, 클라우드 메일 전환, 백엔드 구조, 공통 디자인, 실패 원인 정리다. 이미 완료한 기능은 재사용한다. 실제 보험 가입·결제·명단 실전송·Google 쓰기·원문/운영DB 변경은 기존 승인·복원·단일 작성자 경계를 유지한다.
- Supervisor 브랜치 `feat/wide-pending-integration-20261029`, 기준 main `8cfe391`, 현재 운영 `9b190e9a70511581629f4378290220512358b48c`. 공통 문서·통합·PR·배포·운영 읽기 전용 수락은 Supervisor 단독 소유다. 이전 Luna 작업3개는 완료/공식 보관돼 재생성하지 않았으며, 아래는 새로 승인된 더 넓은 범위의 작업자다.

| 미결 / 기존 참조 | 실제 담당 | 상태·다음 검증 |
| --- | --- | --- |
| 보험 결제 재개→COST 계약 / COST-INS-02 | Travel INS `77ca711a-d0bc-4aac-a35e-a79697ab5544`, `wide-luna-insurance-20261029` | 코드/합성검증/병합 COMPLETE. 실제 pause→실제 finish_registration 경계 포함20 passed, PR #10 운영 작업 사본 main `ec2b73300fe1dbe8c62d958282c929ef3bd80f6a`. 실제 가입/전송0. |
| 웹/CLI 참가자 DB 동일성·참가자/수입 / COST-INS-01/03/05·PIR | COST `0f8fa7db-b66b-47a5-b132-843b665326a3`→Supervisor | 429 retry limit로 중단한 미완성 파일을 인계받아 기존 CLI를 깨뜨리는 기본 preview 변경은 불수락했다. 웹/CLI resolver 공유·명시 웹DB 불일치 차단·readonly schema/file identity/등록 영수증 대조를 구현, 참가자/수입/패널66 passed. 현재 Travel INS 구성의 참가DB 파일 부재를 실제 readonly 확인했고 COST archive/TravelINS local/호스트 data의 참가/roster SQLite 이름 탐색도0건이다. 과거14명 이력을 현재 운영 수락으로 인정하지 않는다. Aside openTab URL빈값·후속snapshot page null로 운영 화면 미수락. |
| 원결제 외부 근거 / PEND-01 | Supervisor | 실제 원본/명시 결제 증거가 없는 금융 연결은 창작 금지. 기존 진단 근거 재사용, 별도 외부 자료 경계 유지. 여행/항목 분류 완료와 구별. |
| 전체 메일 수집·전환 / PEND-04 | COST `59bcb9e4-d3d3-4b00-a4f8-8b393c61c00d`→Supervisor | 429 후 인계. 끊긴 원문 검증 본문을 복구하고 pending/페이지/빈 watermark가 있으면 batch/일반 apply 모두 거부한다. 전체 coverage/실제 manifest-entry digest/count 검증 CLI는 PREVIEW_VERIFIED일 뿐 운영 전환 승인이 아니다. 최신 readonly manifest `2026-10-29T01:25:29Z`:3,710 stored/48 pending/has_next_page=true/complete=false. 실제 원문 다운로드·쓰기·스케줄 전환0. 재확인 조건 pending0/다음페이지없음/query없음/last_complete존재. |
| 백엔드 구조 / RF-103의 여행 authority 경계 | COST `9ec3fe54-5fd2-4533-b394-66fd13857554`→Supervisor | 429 후 인계. 남은 self 참조 오류를 고치고 여행권위/소매/숙박3메서드를 별도 service로 추출, facade·기존 동적 callback 유지. 정규화 실행본문 AST3개 동일, 여행/자동분류23 passed. 전체 결정/worker/HTTP 수락과 구별한다. |
| 모바일·데스크톱 공통 디자인 / RF-201~205 | COST `c506be38-ddbe-4fa1-b729-ebebd4f14f1f`→Supervisor | `4f756a50` OTA 공통 토큰/44px/좁은폭/포커스 채택을 검수하고 중복 rule 제거. 실제 Chromium 합성4검사에서320/390/760/1440·light/dark·zoom1/2·키보드 수락. 추가 기존 shell/카드/OTA browser 묶음은 아래 실제 실행 세션으로 확인 중. 물리기기·실제 인증 화면 수락과 구별한다. |
| 실패 원인 정리 / RF-004 | COST `34abb032-959e-4998-8d15-cbdd9af81fac`→Supervisor | `aaa1ca0e`·`1ca4586`를 검수했다. 추가 실행은 모델 capacity로 중단돼 인계. 빈/collection-only 증거를 pass로 보고하던 parser와 parameter-ID 노출/건수 축소를 수정했다. 실제 CardFlow6 실패는 잘못된 제공자 fixture·요약API 전체카드 기대·request scope 캐시·금융증명 없는 취소/낡은 문구였으며 제품 금융 보호를 유지해 교정했다. CardFlow/OTA96 passed+28subtests, parser5 passed. 전체5천검사 실행/모든 known-failure 완료를 주장하지 않는다. |

- 결과 알림을 받아 실제 최종 파일·diff·표적 검사·원본/금융/권한 보호를 검수하고, 독립 ready 항목을 직렬 통합·정상 PR/main·검증 SHA 배포까지 이어간다. 완료·미검증·외부 의존·진짜 승인 필요를 각각 기록한다. 이전 자동분류 완료 보고는 프로젝트 전체 미결 완료가 아니다. 사용자의 기존 미추적 파일·stash·원래 workspace를 보존한다.
- 추가 실제 검사: 초기통합61 passed(인계 후 오류 복구), 최종 참가자66 passed, cloud/진단41 passed, entrypoint/검증gate33 passed, 환불/정확OTA/권한105 passed. 실행별 중복이 있어 합산하지 않는다. 신규 런타임9개 compile·AST3개 동일·staged guard16파일 차단0/삭제0. 현재 추가 browser 프로세스 session23926 진행 중이며 결과 전 통과로 보고하지 않는다. 최신 증거는 `.local-archive/wide-pending-20261029/`의 cloud-manifest-recheck·participant-default/configured-paths·participant-database-discovery 및 AST 검사다. 아직 COST 묶음은 미커밋/미배포이며 다음은 browser 결과 검수→guard/compile/link→commit/PR/main/고정 배포다.

## 2026-10-29 최신 요청 — Luna low 병렬 구현·통합

- 사용자가 다수 Luna low 구현 위임과 주 에이전트의 지휘를 명시 지시했다. 최신 자동분류/환불쌍 범위의 실제 미결을 확인해 수정하며 과거 RF 전체를 자동 재실행하지 않는다. PR #312의 실제 분류 적용 완료는 유지한다.
- `codex/gpt-6-luna`·`low` 실제 제공을 확인하고 독립 managed worktree 3개로 분리했다. 환불 재전송 `ed69722b-cabc-43f4-bdee-8d6948c05624`는 `app/ledger.py`와 focused tests, 입력 추론 `8e8f91af-96dc-402e-be91-a7a829fca781`는 `app/automatic_classification.py`·completion과 tests, 화면 완료 `2d619e80-8aec-4f60-a52e-590fd256bc35`는 review/evidence UI와 focused tests를 담당한다. 공통 `card_flow.py`·문서·PR·배포·실자료는 Supervisor 단독 작성이다. 재귀 위임·작업자 운영 접근 금지.
- **COMPLETE — 구현·통합·운영 배포:** 환불 최종 `9eb4910`의 정확한 요청 범위·잠금 내 성공 후 digest/실제 장부 fingerprint 검증을 수락했다. Supervisor가 부분 기기록 묶음의 완료 후 재전송·새 환불 멤버/명시 보류/여러 요청 반복 검사를 보완했다. 화면 `a727950`의 빈 이력=의도적 미배정 제거·환불 완료·금융 보류 분리를 수락하고 환불 선택값/미배정 필터·자동 추론 출처·사용자 보류 표시를 통합했다. 추가 OTA `8c9a0f7`도 같은 빈 이력·자동 추론 출처 규칙을 읽기 전용 투영에 적용한다. 실제 수동 여행·금융 연결·권한 보호는 유지한다.
- 추론의 잘못된 일괄 환불 탭 이동은 불수락했고 최종 `a1d2bc8`에서 기준 main 대비 diff0을 확인했다. 기존 추론18검사 통과 근거를 보존한다. 추론 감사는 COMPLETE이며 코드 변경이 없다. 해당 managed workspace는 clean·보존 참조 확인 후 공식 보관했다.
- 실제 검증: 통합 환불/부분환불/화면54 passed, 인접 자동기록/환불표시30 passed, 최종 화면/OTA출처17 passed(합성 browser 포함), OTA 권한·수동연결4 passed/35 deselected. 실행간 중복이 있어 전체 회귀로 합산하지 않는다. 변경 Python6개 compile·diff 검사 통과. 운영 금융 재처리·Google 쓰기·마이그레이션은 포함하지 않는다.
- [PR #314](https://github.com/6Soo/cost/pull/314) 정상 병합, 검수 소스 `cf3670606107c61a08e1e1232c35a3f23fcfbb73`와 운영 고정 `9b190e9a70511581629f4378290220512358b48c`의 tree 동일.1,098 Git blobs 불일치0, fresh 전체 백업·별도 복원, task/process 고정SHA·loopback listener1·health/ready200·보호13표 내용/스키마 불변으로 실제 배포 수락했다. 영향 trip-review GET·환불그룹 commit POST를 포함한 보호API는 비인증401이다. Board/SourceRefresh 모두 Running이며 이전 `a1b1dcaf21d5398ed3519a402191d0129173a6f7` 복구점 보존. 실제 금융 재처리·Google 쓰기·마이그레이션0.
- 근거는 `.local-archive/luna-followups-20261029/validation.json`, `.local-archive/deploy-9b190e9a70511581629f4378290220512358b48c/`의 review/protection-before/protection-after/deploy-evidence/affected-path-smoke JSON, 호스트 같은 SHA의 release-audit/deploy-evidence다. 정확한 재확인 명령은 `Get-Content -LiteralPath 'D:/WebLedgerHost/releases/deploy-evidence-9b190e9a70511581629f4378290220512358b48c.json' -Encoding UTF8`다.
- 현재 승인 범위의 구현·검증·배포 ready 항목과 실제 대기는 없다. 아래 과거 절의 기존 환불 재전송 baseline 실패는 이번 PR로 해소했다. 세 작업자의 최종 커밋·실제 clean·stash/사용 참조를 확인하고 `refs/archive/20261029/luna-*`로 보존한 뒤 managed workspace3개 모두 공식 보관·디렉터리 제거를 확인했다. 기존 사용자 미추적 파일·stash·원래 workspace는 보존했다. 결과 이벤트는 실제 검수 근거로 개별 ack한다. 이 후속 문서만으로 코드 테스트·운영DB 확인·백업·재배포·서버 재시작을 반복하지 않는다.

## 2026-10-29 최신 요청 — 미분류 카드 0건까지 공통 추론 적용

- 사용자가 근거 부족·오분류 가능성을 허용하고 에이전트가 공통 규칙을 코드로 만들어 현재 미분류 카드에 적용하라고 명시 승인했다. 개별 사례별 질문이나 추가 규칙 승인 대기를 두지 않는다. 실제 원본/금융 링크/사용자 결정 보존 및 백업·복원·단일 작성자 게이트는 유지한다. 정본은 [자동분류 완료 계약](specs/finance.md#자동분류-완료-계약-2026-10-29)이다.
- 최신 교정: 사용자가 미배정으로 정한 적이 없다고 명시했다. 203건을 이력/override 표시만으로 수동 미배정이라고 해석한 판단을 폐기했다. 실제 재대조 결과187건은 유효 여행 복원(현재 장부1·최근 저장31·기존 장부155),11건은 기존 환불 탭,5건은 새 여행 추론 대상이다. 원래 항목과 실제 유효 여행은 유지하며 빈 값에만 근거를 복원/추론한다. 결정/override 이력은 삭제하거나 새 사용자 선택으로 위조하지 않는다.
- 현재 구현: 업종/서비스 용도/해외 사용/기타경비 공통 기본값, 실제 여행 최선 후보·동률 해소, 검증된 원결제 항목/여행 상속, 과거 authority 상태 완료. 새 업로드에도 같은 마지막 분류 단계를 사용하며 메일 자료 장애를 비용 미분류 이유로 삼지 않는다. 기존 유효 장부 배정·항목·회사 제외·보류·원본 오류를 보호한다.
- **COMPLETE — 실제 운영 적용:** 미분류 구매195→0, 전체 방향 미분류226→0, 여행 미배정377→0. 분류/배정441건을 실제 DB에 원자 적용했고, 종전 제외203건도 전부 포함했다. 백업 원본과 실제 반영 후 자료를 다시 대조해203건의 기존 여행 복원187·환불 탭 복원11·새 추론5, 기존 항목/원본 불변을 확인했다. 원본/과거 결정/금융 링크 불변·새 장부 행0·Google0·재실행 변경0.
- 최신 정정 후 표적/금융/업로드/교정60 passed, 빈 기본값/이력 복원·금액/금융 링크 보호·원자성/재실행 포함. 추가 API/근거10 passed, 변경 Python8 compile·PowerShell parse0·문서 링크 누락0·metadata guard12파일 차단0/삭제0. 과거 전체 HTML의 `location.reload()` 금지 assertion은 해당 bulk 자동정리 컨트롤의 부재 검사로 좁혔다. 환불 API의 기존 새 요청+이전 digest 실패는 별도 기존 미결이며 금융 보호를 약화하지 않는다.
- [PR #312](https://github.com/6Soo/cost/pull/312) 정상 병합·운영 고정 SHA `a1b1dcaf21d5398ed3519a402191d0129173a6f7`. 검수 소스 `f11b447e8970934985bf4f953801edc078762d71`와 merge tree 동일,1,097blobs 불일치0. 코드 배포 전후 보호13표 동일. 이후 별도 새 백업/복원·정지된 단일 작성자·digest 일치·분류 적용·보호 검증·재실행0을 통과했다. 분류 테이블3개에는 승인된 항목/여행/상태 보완만 허용했고, 나머지 금융/사용자10표는 내용·스키마가 백업과 동일했다. Board/SourceRefresh Running·health/ready200·보호API401로 복구했다.
- 실제 적용 근거는 `D:/WebLedgerHost/data/backups/card-classification-20261029T040917088/`의 `backup-restore.json`, `preview.json`, `applied.json`, `repeat-preview.json`, `post-verification.json`, `financial-relations-verification.json`이다. 코드 배포 근거는 같은 SHA의 호스트 deploy-evidence/release-audit와 `.local-archive/deploy-a1b1dcaf21d5398ed3519a402191d0129173a6f7/`다. [운영 기록](operations.md#2026-10-29-pr-312-미분류-카드-자동추론과-203건-재분석실제-적용) 참조.
- 현재 사용자 승인 범위의 ready 항목과 실제 대기는 없다. 과거 RF 큐와 기존 환불 재전송 baseline 실패를 새 과제로 재실행하지 않는다. 사용자 미추적 파일·stash 보존. 정확한 증거 재확인 명령은 `Get-Content -LiteralPath 'D:/WebLedgerHost/data/backups/card-classification-20261029T040917088/post-verification.json' -Encoding UTF8`다. 문서 후속 병합으로 코드 테스트·운영 DB 확인·백업·재배포·서버 재시작을 반복하지 않는다.

## 2026-10-29 현재 사용자 요청 — 자동분류 완료와 환불쌍

- 현재 직접 승인 범위는 취소·환불 미분류 원인 수정·검증·배포, 사례 36건을 바탕으로 가맹점별 예외가 아닌 공통 규칙을 구현하는 것, 그리고 별도 확정/미확정 단계를 없애는 것이다. 최신 계약은 [금융 명세](specs/finance.md#자동분류-완료-계약-2026-10-29)다. 과거 RF/PA 큐 전체를 재실행하지 않는다. 새 승인 작업 ID는 만들지 않는다.
- 후속 담당 `16089281-ddee-44a0-8f5e-1572550ad28b`가 기존 `C:/AX/cost`를 재사용한다. 이전 부모에게 메시지·재개 없음. 인계 family의 자식/결과 이벤트는 0개이며 새 위임 없음. 기존 사용자 미추적 파일·stash는 보존한다.
- 인수 HEAD `68ef66b7b58b5733ca5532688fed893bc0cdc0fb`는 원격 main보다 3커밋 앞서며, `8ddee29` 환불쌍 분류 저장·`04a2958` 예약 여행 추론·`68ef66b` 답변 재사용 규칙이 이미 실제 고정 배포됐음을 호스트/local deploy-evidence에서 확인했다. 코드 배포를 36건 실자료 해결 완료로 해석하지 않는다.
- 구현·검증: 분류 완료 DTO/화면을 `CLASSIFIED`와 자동·수동 출처로 통합하고 추가 확정 요구를 제거했다. 분류가 이미 저장됐는데 내부 기록이 `NOT_RECORDED`이면 전체 API를 409로 반환하던 오류를 고쳐 `saved=true`·`classification_state=classified`와 별도 `ledger_recording=held`를 반환한다. 기록 보류 중에는 다른 거래의 재분류/자동 기록을 실행하지 않는다. 수동 결정·환불·원본·권한 보호는 유지한다.
- 실제 검사: 최초 표적39 passed/64 deselected, 환불·자동 기록·여행 통합62 passed/1 failed, 후속 변경의 자동 기록·교정21 passed, 결정 API·여행 이동·근거10 passed/84 deselected, OTA 권한/공개자료6 passed/33 deselected, 낮은 신뢰도 브라우저 교정1 passed. 최신 여행 화면 browser는21개 묶음에도 포함되며 별도 브라우저에서 분류 완료/추가 확인창 없음·4폭·확대 검증을 수행했다. 변경 Python9개 compile·diff·현재 로컬 문서 링크 누락0.
- 기존 실패: `test_refund_group_commit.py::RefundGroupCommitTests::test_group_route_books_only_the_pair_and_repeats_are_noops`의 새로운 요청 ID+이전 미리보기 재전송 오류는 변경 전 `68ef66b`에서 동일 `KeyError: result` 재현. 상속된 cleanup 검사도4 passed/1 failed이며 `test_bulk_classification_survives_booking_failure_without_changing_protected_data`의 전체 HTML `location.reload()` 부재 assertion이 같은 기준에서 재현됐다. 통과로 계산하거나 미리보기/금융 보호를 약화하지 않았다. 근거 `.local-archive/automatic-classification-20261029/baseline-refund-retry.txt`와 `baseline-cleanup-reload.txt`. 과거 브라우저 fixture의 숨겨진 배치·폐기된 수동 기록 버튼/문구는 현재 계약에 맞게 교정 후 통과했다.
- **COMPLETE — 코드·명세·승인된 배포:** [PR #310](https://github.com/6Soo/cost/pull/310), 구현 `a1b5af2da158d6016f62c150171a91e78599852c`, 운영 고정 `b75c37887c354255f0bf877eb8d1e47451c9684d`. fresh backup/별도 복원·1,092blobs 일치·task/process SHA·listener1·health/ready200·보호 API401·13표 내용/스키마 불변. 검수 소스와 merge tree 동일. Board/SourceRefresh 모두 Running. 배포본 순수 합성 smoke도 자동/수동 완료·출처·공개자료 제한 통과. 상세는 [운영 기록](operations.md#2026-10-29-pr-310-자동분류-완료환불쌍-저장-배포) 참조.
- **미실행 범위:**36건 일괄/개별 실제 저장·새 업무 규칙 활성화·Google 쓰기·마이그레이션 없음. 기존 업종·현지 사용 공통 규칙은 유지한다. 인증된 Aside COST 탭이 없어 운영 owner 실자료 UI 수락은 미실행이며 합성 browser 수락을 대신 실자료 완료로 표현하지 않는다. 코드 배포 완료를36건 실자료 완료로 확대하지 않는다.
- 현재 분류 완료/환불쌍 코드의 ready 항목은 남지 않았다. 신규 공통 규칙의 아직 논의되지 않은 업무 의미를 임의로 정하지 않는다. 사용자와 거래 사례에서 공통 조건·항목이 정해지면 그 범위의 규칙을 구현하고, 실자료 저장은 기존 원본/복구/단일 작성자 게이트로 처리한다. owner 화면 수락의 재확인 조건은 정상 인증된 COST 세션 확보이며 인증을 우회하지 않는다. 기존 실패2개는 현재 변경의 통과 근거와 별도 미결이다. 정확한 배포 증거 재확인 명령: `Get-Content -LiteralPath 'D:/WebLedgerHost/releases/deploy-evidence-b75c37887c354255f0bf877eb8d1e47451c9684d.json' -Encoding UTF8`. 문서 후속 병합만으로 재배포하지 않는다.

## 계정 전환 후 통합 검수 (2026-10-28)

후속 담당은 `a8dba9f3-3e50-4a26-b113-ab754767883e`다. 이전 담당에게 메시지를 보내거나 재개하지 않는다. 잠정 배정 최종 `494761842aa6da982133a8548edc660b9d11b65a`를 최신 main `9c7580d8d12e869dc23dee8f3f822033d28389d2`에 정상 통합했다. 통합본 새 화면·금융 보호 226 passed, 권한·환불·우선배정·OTA 페이지/스냅샷 227 passed, 변경 Python 12개 compile 및 diff 검사 통과. 선택기 미매핑0, metadata guard 차단0/삭제0. 실제 브라우저 검사는 합성 자료를 사용하며 운영 실자료 수락과 구별한다.

현재 운영은 PR #308의 검증된 `9ab2471f91b6b210ac79985a43e507743f5870d9`다. 정상 병합·검수 소스 일치·새 백업·별도 복원·고정 SHA 배포·health/ready·보호 API·보호13표 불변 확인을 완료했다. 실제 재배정·일괄 처리·보험 명단 전송·Google 쓰기·마이그레이션은 실행하지 않았다. PA-01 실자료 기준선과 PA-06 실자료 수락은 미측정이다. 기존 여섯 CardFlow 실패는 작업자 기준 `61211012`에서도 같은 node로 재현한 별도 기록이며 통과 수에 포함하지 않는다. 현재 병합·코드 배포 요청은 완료했으며 실자료 수락은 별도 경계로 유지한다.

기존 27개 큐는 과거 수락 경계를 보존한다. 새 managed run은 `07264b89-75e8-4748-9ab5-9f7ae4d3035a`, generation 2이며 checkpoint는 같은 run 디렉터리의 `checkpoint.json`이다. 운영 배포 결과는 아래 후속 기록을 우선한다.

기존 managed run 정본은 [리팩토링 마스터](specs/refactor-master-20261027.md)와 아래 27개 ID다. 이후 사용자가 명시 선택한 명세 대기 기능의 코드 구현·검증 배포 승인은 아래 최신 진행 기록에 추가한다. 과거 ACTIVE/READY 전체를 자동 재실행하지 않는다. 상세 과거 근거는 [보관 기록](history/product-and-handoffs.md#rf-generation5-queue-archive), 배포는 [운영 기록](operations.md)을 참조한다.

- runId: `e0197439-1c34-4348-a14d-7a870c3d69b5`.
- 이전 run Supervisor: `3cebc37b-17d7-4b47-9689-a2bf6f50a01c`, generation **5**. 현 담당은 위 후속 run/generation1이며 workspace는 `C:/AX/cost`다.
- 운영 확인 SHA: **c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661**. 정상 배포·보호 검사 근거는 아래 최신 진행 기록과 운영 기록을 따른다. 실제 단일 환불 그룹 적용은 owner 인증 대기다.
- 사용자 작업 사본은 `C:/AX/cost`이며 사용자 미추적 파일·stash와 미수락 결과를 보존한다. 정리·통합 브랜치 근거는 `.local-archive/merge-cleanup-20261028/`에 기록한다.

## 승인 전체 ID와 실제 수락 경계

부분 추출의 병합을 전체 RF 완료로 승격하지 않는다. pending에도 기존 부분 구현은 있으며 완료 근거를 재사용한다. complete는 아래 두 PEND와 문서 정리 범위만이다.

| ID | 상태 | 검증된 범위 / 다음 경계 |
| --- | --- | --- |
| PEND-01 | blocked | 원결제 또는 명시 결제 증명 부재. 기존 진단 완료, 금융 연결을 창작하지 않는다. 아래 외부 자료 차단 참조. |
| PEND-02 | complete | 합성 browser3 passed와 운영 Aside 4조건·20행·넘침0의 확대/키보드/오류·재조회 수락. 물리적 모바일 검사는 아니다. |
| PEND-03 | complete | 클라우드 수집/가져오기 PR #256/d37b33c 및 전용 수집기 배포. 수집20/인증14·importer32/browser3 근거 재사용. 실제 전환은 PEND-04. |
| PEND-04 | blocked | 2026-10-28T14:35:59Z 기존 전용 Drive readonly 자격으로 manifest 재확인:3,710 stored/48 pending/has_next_page=true/complete=false. 원격 탐색 미완료로 전체 bounded preview 수락을 진행할 수 없다. 원문 다운로드/원격·로컬 원문/운영DB 쓰기0. 재확인 조건은 pending0·다음페이지없음·query없음·last_complete존재다. 근거 `.local-archive/merge-cleanup-20261028/cloud-manifest-recheck.json`. 코드/51검사 근거를 유지하며 실제 적재/작업전환의 별도 데이터 게이트는 확대하지 않는다. |
| RF-001 | running | 정적 호출 지도 `config/refactor-call-map.json`·도구 PR #294/main `8e479de` 병합, 경로 영향 매핑 PR #296/main `ba74ab8` 병합. 표적/선택기 18건 통과. RF-001 및 RF-101 통합 101 passed/3 subtests; 전체 gate는 12개 모듈에서 OTA `inferred_link` KeyError 1건으로 실패했고 기준 SHA `355eaea`에서도 같은 assertion 재현. 전체 Route→service→repository→table→external-effect와 권한 수락은 미완료. |
| RF-002 | pending | 좁은 OTA 읽기 계약은175c3a2에서 이미 채택됨을 확인, 중복 구현하지 않았다. helper 실행 AST 동일·golden/canonical27 passed·입력 불변. 전체 상태 소비 수락은 부분 완료. |
| RF-003 | complete | PR #307의 코드 패키지 경계와 PR #308의 화면 문구 제거·검증된 원결제/환불 원자 기록 경로를 병합·배포했다. 60개 합성 환불/정리 검사를 통과했고, 1,092 blobs·health/ready200·보호API401·보호13표 불변을 확인했다. 운영 SHA는 `9ab2471f91b6b210ac79985a43e507743f5870d9`이며 실제 금융/여행/Google 쓰기는 실행하지 않았다.
| RF-004 | running | Windows/Python3.14.7의 실제 pytest collection 5,255건(exit0)과 정적 환경 감사 오류0을 확인했다. 수집은 본문 실행과 구별하며 import/hook 실행 사실을 표시한다. audit의 명시적 --collect는 원문 stdout을 공개하지 않고 요약·해시만 남기며 실패/timeout을 통과로 처리하지 않는다. 표적24 passed. 전체 known-failure 분류와 간접 실DB 의존 감사는 남음. |
| RF-005 | complete | PR306의 공식 tools/deploy_verified_release.ps1로 b34a96a를 실제 배포했다. 기본PREVIEW실행0/명시적Apply·review/blob/검증이전릴리스/task/process/listener·fresh backup/별도복원·health/ready200·API401·보호13표불변을 확인했다.1090blobs일치, 이전c1bf76ce복구점보존. switch는 LF정규화외동일, 표적27passed·PS2parse. 호스트4예약task는 기존기동/동기화경로이며 오래된DB전환배포기를호출하지않음을 이름/인자명만으로확인했다. RF003의배포콘텐츠분류는독립미결이다. |
| RF-101 | complete | 입력 정규화 `9930b42`·동적 콜백 교정 `5f0ac83` 포함 PR #294/main `8e479de` 병합. 스토어 정규화·idempotency·audit·allocation·schema·records·change-validation·store·income_bank 및 RF-001 검사 101 passed/3 subtests; 호출 동적 재바인딩·SQL/audit/revision/idempotency 계약을 유지. |
| RF-102 | complete | 필요한 helper와 façade 분리는 최신 main에 이미 반영되어 있다. main SHA 355eaea 기준 HTTP/render/read/export/dialog 표적 49 passed. 임시 RF102 브랜치와의 유일한 소스 차이인 query fallback은 호출 타입 계약을 불필요하게 넓혀 채택하지 않았고 원본 브랜치는 증거 보존 후 정리한다. |
| RF-103 | running | 카드 근거·환불 query·OTA 투영·cleanup PR #261/#268/#269/#276 검수/병합/배포. 여행 authority/decision/background 전체 수락은 남음. |
| RF-104 | running | 중앙 대사·예약 그룹/페이지·증분 성능 기존 구현 재사용. 전체 consumer의 같은 세대/링크/trace 수락을 대조하고 solver를 재구현하지 않는다. |
| RF-105 | blocked | PR #295 `496cbbe` 운영 배포 완료. 1,051 tracked blobs 일치, task/process SHA 고정, listener 1개, health/ready 200, 보호 API 401, 새 백업·별도 복원 검증과 보호 13표 불변. owner 화면은 AUTH_REQUIRED로 승인된 단일 환불 그룹 적용 미실행. 실제 관측 그룹은 같은 import batch이므로 교차 배치 실행 증거로 표현하지 않는다. 환불/금융 표적 74 passed; 넓은 검사 실패 13건은 ba74ab8에서도 동일 node ID로 재현. PR #297 개별 그룹 UI/API는 e1a6c7b로 병합했으며 운영 배포 여부는 아래 최신 진행 기록을 따른다. |
| RF-106 | complete | PR #286의 공통 항공권 근거/검색 projection은322ef3f 및후속c1bf76ce에 배포됐다. source의(provider,booking_ref)→공통 collect→검색/guide/index 소비를 확인했고 추출 전후 핵심4파일 변경0. 보관 인증 근거210건의149질의·stale/cursor447건 읽기 전용 shadow가9f6eec7과동일, 원본/입력불변. 표적106 passed와 아래 수정browser2 passed, 최초수신일/index11 passed. 외부 예약 checkout 통합1 skip은 미실행으로 별도 보존하며 실제 사람/카드 연결을 수락한 것으로 표현하지 않는다. 명시일/최초수신일·시차·왕복·취소/변경·권한은 해당 표적으로 확인했다. |
| RF-107 | running | provider schema/masking PR #289/d1180f1 병합. 필수 signature·ConfigError 동일성·기존 순수/저장소/service AST 동일, Supervisor135 passed/105subtests. 전체 adapter 수렴은 남음. |
| RF-108 | pending | schema/additive/복원/snapshot 기존 기반 재사용. 쿼리 plan·P95·메모리 측정 후 최적화. 실제 DB migration은 별도 게이트. |
| RF-109 | running | runtime catalog 정적741후보(UNKNOWN379/TEST_FIXTURE359/HISTORICAL3) 확인. tools/cost_audit.py는 기존 환경·runtime·call-map·write-boundary·tracked-data 진단5개의 읽기 전용 공통 진입점이며 기본PREVIEW, 명시적 --run과 고정 인자만 허용한다. writer/collection/임의 인자 차단·종료코드 보존 포함 표적24 passed. 운영 호출·전체 guard 분류와 write CLI 수렴은 남음. |
| RF-201 | running | 자산 배포, geometry 단일 소유2559ef7 및 실제 CSS zoom/baseline 검사8798569 회수. 작업자 전체4 passed(99.88초), Supervisor 인접20 passed/1 deselected. native/standalone·8폭·양테마·CSS1/2배는 합성 수락이며 실기기 검사가 아니다. PR #290/322ef3f 배포. |
| RF-202 | running | 공통 셸 조립 PR #277/자산 PR #282 배포. URL/DOM·테마1개 보존. 전체 화면 수락과 구별한다. |
| RF-203 | running | 검토 문서 PR #265·guidance16검사·template byte 동일성 배포. 전체 폼/지출 컴포넌트 채택 수락은 남음. |
| RF-204 | running | 기존 OTA/환불/항공권 정보 구조 개선 재사용. 전체 동일 상태/인라인 근거/접근성 수락은 남음. |
| RF-205 | running | 기존 responsive/keyboard/theme 근거와 RF-201 합성 baseline matrix 재사용. 항공권의 낡은 OS색상전환 assertion1실패를 최신 단일 수동 아이콘 계약으로 교정하고 실제 예약/기존 참가자2화면×8폭·200%·키보드·수동선택 유지 browser2 passed. 초기106pass/1fail과 교정후2pass를 구별한다. 인증 운영 화면·실기기 포괄 수락은 미실행. |
| RF-301 | running | requirements 단일 생성/검증 PR #283/9f6eec7 배포. 선언5개 동일·기본 읽기·원자적 mirror.51검사+selector8. 환경/비밀/feature flag 전체 정리는 남음. |
| RF-302 | running | 기존 관측·OTA 성능 근거 재사용. 공통 request/snapshot/rule/fingerprint·단계 지연 및5경로 p50/p95/bytes/memory 전체 수락은 남음. |
| RF-303 | complete | PR #293 merged as 355eaea5c8476f153bc43ff5320b572f7fb27c4f. Fail-closed schema/selector validation, sanitized errors, preview/run separation and self-impact mapping accepted. Supervisor: 31 tests passed; preview PREVIEW with executed=[]; --run PASSED (guard blocked_count 0, py_compile, targeted pytest). Operating deploy is grouped after the remaining approved integrations. |
| RF-304 | complete | 단일 문서 진입점·승인27개 큐 압축/보관 PR #287/fc2e44b 병합, 새 상대링크 누락0. 새 한글 인코딩 손상은 UTF-8 파이프 bytes 검증 후 현재 큐/해당 운영 절/새 보관 기록에서 복구했다. 문서만으로 앱 검사/배포를 반복하지 않는다. |

## 현재 작성권

main PR·배포·공통 문서·COST 임시 공간 보관은 Supervisor `3cebc37b`만 담당한다. PA04/05/06 화면·승인 API는 `4c407a16`가 기존 assignment worktree의 단독 작성자다. 최신 main `61211012`를 정상 merge한 중간 53검사 통과 보고까지 수신했으며, 최종 browser·금융 보호 검수 결과는 아직 기다린다. cleanup 공간은 보존한다. 참가자·항공·OTA는 PR #300으로 병합·배포했고 공식 보관 결과는 아래 최신 기록을 따른다. 다른 저장소 보험 sender 코어 21검사는 실제 가입·명단 전달 승인이나 실행 근거가 아니다.

## 이전 작업자 인계 이력

다음 표는 종료·교체된 작업자의 과거 기록이며 재개 지시가 아니다. ANUS 이후 사용자 Luna 병렬 위임 결과도 회수했으며, 실제 quota로 유료 대체·작업자 반복 생성은 하지 않는다.

사용자 최신 지시는 **ANUS free(auto)** 위임이다. 기존 AGY의 완료 커밋/미커밋/작업공간을 보존해 재사용하고 실행 제공자만 사용자 지정으로 전환한다. 두 작업자의 실제 Individual quota reached(약2시간29분 후 reset)와 자동 continuation alias의 같은 오류를 확인해 반복 위임하지 않는다. 자동 복구로 실행된 Codex 현재 owner5319cc4c/ceed86f8을 중단한 뒤 Anus 작업자2명을 같은 workspace에 배정했다. 확인한 제공자 anus의 모델 ID는 anus/free(무료 자동 회전)이며 유료 대체·재위임·운영 접근은 금지했다. 작업자 재위임·push·PR·배포·운영/고객 원문 접근은 금지한다. 공통 문서/운영/인증/원문은 Supervisor만 작성하며 같은 파일/DB/외부 효과 작성자는 하나다.

| 실제 child agentId | worktree suffix / 현재 소유권 |
| --- | --- |
| `98cc885f-5d8c-4c99-8d5e-01ccfe57a6ea` | `cost-rf102-board`: 초기화 실패2회·error·activeTurn없음·clean. 새 변경 없음, 재개하지 않고 기존 결과 보존. |
| `e253fa73-485c-4e55-b87f-22f56208b323` (Anus) | `cost-rf101-store`: d1dfd42/3afc1d7 보존 결과 검수 후 RF001 tools/refactor_call_map.py·독립검사·비식별 config 구현. 기존 AGY/Codex 실행은 중단, 파일 보존. |
| `bce73f79-9de8-4f22-8c1e-04ab8ab6efd1` | `cost-rf103-evidence`: app/cloud_mail.py·합성 검사만으로 PEND04 bounded batch 구현. 원문/운영 실행 금지. |
| `9b367736-16e9-40c2-8516-21acec02ae32` (Anus) | `cost-rf201-assets`: tools/run_targeted_checks.py·독립검사 fail-open 교정. 기존 미커밋2파일을 보존해 이어간다. UI는 PR290 배포 완료라 재구현하지 않는다. |

worktree root는 `C:/Users/kkokk/.paseo/worktrees/28lt5mey/`다. 실행 중 child에 같은 과제를 다시 보내지 않는다. provider stream/초기화 오류는 로컬 실행 실패이며 외부 권한 차단으로 바꾸지 않는다. 완성 커밋은 실제 diff·검사를 대조해 회수한다.

## 배포와 검증 근거

- **322ef3f 고정 배포 완료**: PR #286 항공권/#288 변경 검증/#289 provider/#290 토큰·UTF-8 교정 포함.1,041 Git blob 일치·작업/프로세스SHA·단일loopback listener·health/ready200·보호API401·보호13표 불변. 이전9f6eec7 복구점과 검증된 복원 사본 보존. PEND04 원문 적재/작업 전환 미포함.

- 이전 운영 **9f6eec7**: PR #280~#285 포함. 이전 검증535b6dd3178758a5a442eb6a8e7b0d60517a5cb3 복구점 보존.1,034 Git blob 불일치0·작업/프로세스SHA·단일loopback listener·health/ready200·OTA 보호API401·보호13표 내용/스키마 불변. data guard base 차단0/삭제0. 기존 검증 백업/별도 복원 근거 재사용.
- 최근 Supervisor: HTTP98, 멱등성66/3subtests, requirements51, selector8, 항공권71, 변경 검증70/3subtests, provider135/105subtests, 토큰 인접20/1deselected. 단위는 pytest tests/subtests이며 서로 다른 실행 건수를 합산해 전체 회귀처럼 보고하지 않는다.
- 멱등성의145개 메서드 집합/SQL 동일·139개 AST 불변, 변경 검증은 _validate 외144개 AST 불변. 작업자 모듈별 실제 통과와 공개 baseline differential 근거를 재사용한다. 무관한 전체 회귀는 반복하지 않았다.
- 로컬 `.local-archive/refactor-parallel-20261028/`의 equivalence/review/protection JSON과 호스트 동일SHA release-audit/deploy-evidence가 근거다. 개인정보·원문·계정/폴더ID·인증값은 Git/보고서에 넣지 않는다.

## PEND-04 실제 게이트

[클라우드 전환 명세](specs/cloud-mail-cutover.md)의 기존 승인만 수행한다. 전용 프로젝트·사용자 직접 Apps Script/Drive 동의·callback·전용 ADC·Drive 소유자/비공개 확인은 완료했다. 재동의나 기존 인증 교체는 하지 않는다.

`cloud-backfill-state.json`에서3,704건/pending0/has_next_page=false/query=null/last_complete 존재로 초기 전체탐색 완료를 확인했다. last_complete는 탐색 시작 watermark이며 관측 완료시각과 다르다. 단일 반복기는 완료 후 정상 종료했다. Drive size294,501,933B 때문에 기존 무제한 읽기 preview를 중지했고 안전100MiB를 유지한 bounded batch 합성 보완 중이다.

기존 `WebLedger-MailCollect`는 직접 Gmail 수집/Ready이며 호스트 원문 적재·운영DB import·작업 전환은 미실행이다. 다음 순서:

1. 배치 코드/보호 검사를 통과하고 모든 batch preview의 내용 검증·전체 indexed=existing+new·enumeration_complete를 확인한다.
2. 기존 작업 XML/명령/상태 보존→직접 writer disabled/idle·동시쓰기0→신선한 원문/통합DB/보호DB 백업·별도 복원 동등성→보호13표 기준선.
3. 승인된 원문 append/import→기존 원문/헤더·금융/수동결정 불변→반복 appended0/DB 불변→COST/worker 새 원문 반영 수락.
4. 클라우드 후속 예약 실행1회와 Drive 전달 수락 후에만 Gmail 작업을 Drive 전달 전용으로 전환한다. 실패 시 검증된 이전 작업만 복원하고 원문은 보존한다.

로컬 준비 실행기는 `apply_verified_cloud_mail.py`, `verify_imported_cloud_source.py`, `cloud_relay_runner.py`다. 실제 single-writer/backup/restore 확인 없이 환경 문자열만 넣어 실행하지 않는다. Board가 Windows에 있으므로 완전한 로컬 의존 제거라고 보고하지 않는다. Board 릴리스와 원문 적재는 외부 효과를 직렬화한다.

## 외부 자료 차단과 범위 밖 보존

- **PEND-01 external_data**: 카카오39취소 중29연결/10미연결, Agoda76중73/3, Trip전체186중171/15. Trip15중12는 원승인번호가 있으나 DB/보관/추가 탐색에서 원결제를 찾지 못했다. 원결제 원본 또는 명시 결제 증명이 필요하다. 금융/원문/수동결정 쓰기0. `.local-archive/all-pending-20261028/refund-evidence-summary.json` 및 recovery summaries 근거 유지.
- **SPEC_ONLY, 실행 제외**: [오너 결정](specs/owner-product-decisions-20261028.md), [보험 참가자/수입](specs/participant-income-authority-and-drag-link-20261028.md), [잠정배정 검토](specs/provisional-assignment-review-first-20261028.md), [지출 상태 필터](specs/expense-cleanup-status-filter-actions-20261028.md), [여행 항공권](specs/trip-flight-booking-overview-20261028.md), [Travel INS 연동](specs/insurance-participant-integration-20261028.md). 과거 미구현 표기는 새 RF 기능 승인이 아니다.
- 별도 카드 전체 내역 과밀 개선 PR #273은 구현/배포 완료, 인증된 운영 화면 수락만 남은 이전 범위다. 과거 ALL/R0/R1은 보관 근거이며 새 큐가 아니다.
- 사용자 미추적 `apps-script/CloudMail.gs`, `docs/superpowers/`, `scratch/`, `webapp/tests/tmp71q0k16e/`, `webapp/tests/tmp_dfqgw61/`와 기존 stash/기존 workspace를 보존한다.

## 다음 실행과 인계

각 결과마다 해당 행/근거를 갱신하며 세션별 전체 큐 사본을 새로 만들지 않는다. 최신 사용자 결정이 과거 문서보다 우선한다. 고객 원본/수동결정 보존, 인증 우회·강제 push·자료 삭제·미승인 과금 금지, Google 최종 장부 읽기 전용을 유지한다.

공통 checkpoint: `C:/Users/kkokk/.paseo/paseo-accounts/work-runs/e0197439-1c34-4348-a14d-7a870c3d69b5/checkpoint.json`. Publisher: `.local-archive/refactor-parallel-20261028/publish_checkpoint.py`. 승인27개 ID·queue bytes SHA256·generation5 실제 agentId를 원자 갱신한다. family results-ack는 검수한 이벤트만 누적한다.

정확한 다음 행동: RF201 표적/차등 수락→직렬 PR/main·검수 묶음 고정 SHA 배포/health/auth/보호 최소 스모크. 동시에 반환 normalization/gate/batch의 실제 diff·표적 검사를 수행하고 PEND04 현재 원격 manifest 완료를 확인한 뒤 읽기 전체 preview 및 single-writer/복원 게이트를 준비한다. 준비된 독립 항목은 계속 진행한다.

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

## 이전 GitHub 감사와 후속 확인

[18:30 구현 감사](specs/implementation-status-audit-20261028.md)와 [동일 화면 환불 복구 명세](specs/refund-inline-existing-repair-20261028.md)는 당시 코드·운영 차이를 남긴 기록이다. 이후 PR #297~#300 검수·배포 근거는 위 최신 진행 기록이 대체한다. 기존 거래 자동 소급처리나 단일 환불 그룹 실제 적용은 수행하지 않았으며, 원문 오류·수동 보류·승인번호 미확인 건은 보호한다. [제품 오너 결정](specs/owner-product-decisions-20261028.md)의 미완료 기능은 사용자 후속 명시 승인에 따라 단계별 구현 중이며 전부 완료된 것으로 표시하지 않는다.

## 2026-10-28 PR #302 잠정 여행 배정 검토 배포 완료

[PR #302](https://github.com/6Soo/cost/pull/302)은 `c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661`로 정상 병합·고정 배포했다. owner의 잠정 배정 검토와 20건 페이지, 명시적 보류, 저장된 원본별 교정 제안의 재검증·승인을 추가했다. 수동 결정·환불·원본 보호와 기존 결정 API를 유지한다.

통합 검수는 새 화면/금융 보호 226 passed, 권한/환불/우선배정/OTA 페이지·스냅샷 227 passed다. 변경 Python12개 compile·diff 검사 통과, 선택기 미매핑0, metadata guard 차단0/삭제0. 기존 CardFlow6개 실패는 작업자의 기준61211012 재현 근거를 보존하며 통과 수에 포함하지 않는다. 합성 HTTP/브라우저의 수락을 운영 실자료·실기기 수락으로 표현하지 않는다.

1,084 Git blobs 일치, 새 백업·별도 복원 검증, 작업/프로세스SHA·loopback listener1·health/ready200·보호API401·보호13표 전후 불변을 확인했다. 추가된 trip-review/proposals/hold 경로도 익명401이다. 이전 검증61211012 복구점을 보존했다. 배포 근거는 `D:/WebLedgerHost/releases/deploy-evidence-c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661.json`, 로컬 `.local-archive/merge-cleanup-20261028/deploy-c1bf76ce3e6e6973dc92e6a3e1c2a145c5e4e661/`다.

실제 금융/여행 재배정·대량 재처리·명단 전달/보험가입·Google 쓰기·마이그레이션은 실행하지 않았다. PA-01 실자료 기준선 및 PA-06 실자료 shadow/수락은 미측정으로 남긴다. 단일 환불 그룹 적용의 정상 owner 인증 대기는 유지한다. 최종 확인 시 열린 PR은0개다. 후속 문서만의 병합에는 재배포하지 않는다.
