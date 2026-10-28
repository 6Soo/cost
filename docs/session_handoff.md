# 현재 상태와 남은 일

## 2026-10-28 제품 오너 추가 결정: 수입-보험 통합·우선 잠정 배정 (SPEC_ONLY)

[오너 결정 5개](specs/owner-product-decisions-20261028.md)를 확정했다. [보험 확정 참가자 중심의 수입 표 드래그 연결 상세](specs/participant-income-authority-and-drag-link-20261028.md)의 **PIR-01~06**, [소수 근거 여행 우선 잠정 귀속·검토/교정](specs/provisional-assignment-review-first-20261028.md)의 **PA-01~06**을 신규 개발 큐에 추가한다. 여행 탭 순서는 **수입 → 보험가입내역 → 지출**(항공권 보조 영역), 수입의 `보험 등록` 체크는 검증 참가자와 연결된 경우에만, 실명 보험 명단과 닉네임 선입금은 드래그/키보드로 owner가 연결한다. 오래된 OTA 미해결을 90일 등 연령 기준으로 자동 숨기거나 완료 처리하지 않는다. **Trip.com부터 항공권 조회 확대·owner-only 보험 열람·기존 Travel INS 로컬 전송 유지**가 승인된 기본안이다. 기존 RF-101/102/103/201/202 병렬 개발 파일 소유권을 확인하고 충돌 없이 이어 구현해야 한다. 이번 PR은 **명세만 변경**, 데이터/앱/테스트/운영 배포·실자료 수락은 미실행이다.


## 2026-10-28 신규 지출 정리 상태 필터 (SPEC_ONLY)

현재 `/import` 상단 `항목 미분류`, `여행 미배정`, `보류·오류`는 `webapp/card_flow.py::render_expense_cleanup`에서 `<span>`으로 출력되는 비동작 표시다. 사용자 요청에 따라 [지출 정리 상태 칩 클릭 필터 상세 명세](specs/expense-cleanup-status-filter-actions-20261028.md)를 작성했다. **ECF-01~04 미구현**: 전체/카테고리 서버 쿼리, 20건 필터별 페이지, 선택·건수/이동·저장 뒤 갱신, 보호/기타 검토 정확성, 브라우저/회계 안전 수락. RF-103 `card_flow.py` 작업자 소유권과 충돌하므로 현 PR/작업자 진행을 먼저 확인해 단일 작성자로 구현한다. **이번 PR은 문서만 수정**했고 실제 버튼 기능·테스트·운영 배포 완료는 아니다.

## 2026-10-28 사용자 재지시 — 전면 리팩토링 병렬 실구현

최신 지시: Supervisor는 단일 백필 대기에 매달리지 않고 **AGY Gemini 3.8 Flash Medium** 작업자에게 대량 구현을 병렬 위임한다. 실행 정본은 [리팩토링 마스터](specs/refactor-master-20261027.md)이며 아래 기존 완료 구현은 재사용한다. 별도 SPEC_ONLY 항공권/보험 명세를 이번 지시만으로 새 기능 구현에 포함하지 않는다. 기존 PEND-04 클라우드 전환도 승인 범위 안에서 계속 수행한다.

- 시작 SHA `2384cfd`, 열린 PR 없음, 사용자 미추적 5경로 보존. 지정 모델의 실제 ID `antigravity/gemini-3.8-flash-medium`과 full-access 실행 가능을 확인했다. 기존 무료 우선순서보다 최신 사용자 지정이 우선한다.
- 각 작업자는 별도 Paseo worktree의 단독 작성자이며 운영 데이터/인증/고객 원문을 읽거나 수정하지 않는다. Supervisor만 통합·공통 기록·PR·배포·운영 검증을 수행한다. 작업자 재위임·push·PR·배포는 하지 않는다.

| 작업 | 단독 작성자 / 파일 소유권 | 상태·완료 기준 |
| --- | --- | --- |
| RF-101 저장소 읽기·투영 책임 추출 | `bf74bc49-d0d8-41be-886e-3255dca226fe`, `ledger_store.py`와 새 모듈·독립 테스트 | 읽기 PR #263 병합. 스키마 원형 추출599204d 검수 중, 다음 순수 배분 검증 분리 배정. 쓰기·감사 실행 순서 보존. |
| RF-102 보드 읽기·표시 책임 추출 | `98cc885f-5d8c-4c99-8d5e-01ccfe57a6ea`, `ledger_board.py`와 새 투영/표시 모듈·독립 테스트 | 렌더 헬퍼 PR #267/main091e49a 병합. 최종11검사·통합15검사 통과, Handler/detail_page AST 불변. 다음 읽기 투영 구현 중. |
| RF-201/202 공통 UI 책임 정리 | `995ccfb3-16d8-4dfe-82fd-65ca02fc4091`, 지정 UI 소유 모듈·독립 테스트 | 장부 자산 PR #262 배포4e53776, 검토 문서 PR #265·카탈로그 PR #266 병합. 다음 기존 theme/shell 중복 소비 정리 배정. |
| RF-103 카드 OTA·환불 근거 표시 분리 | `bce73f79-9de8-4f22-8c1e-04ab8ab6efd1`, `card_flow.py`와 새 근거/조회/표시 모듈·독립 테스트 | 렌더러 PR #261/main7fbf1b0 병합. 최신 main 통합28 passed. 쿼리8c5d263·OTA 투영053f0cb 검수/통합 중, 다음 순수 목록 마크업 분리 배정. |
| PEND-04 기존 클라우드 전환 | Supervisor, 기존 all-pending 로컬 실행기 | 마지막 확인2777건, 탭 소멸로 runner 중단. 기존 프로젝트 탭 복구 중. 전체 탐색→백업/복원·단일 작성자→원문 적재/반복 불변→worker·예약 수집·전달 전환 순서 유지. |

통합은 변경 축별 직렬 PR로 수행하고 작업자 구현/테스트·Supervisor 수락·병합·실제 배포를 따로 기록한다. R0/R1 기존 PARTIAL 및 외부 근거 미확인을 완료로 승격하지 않는다. 각 작업 완료 후 마스터의 의존성과 최신 소스를 대조해 다음 준비 항목을 바로 배정한다.

### 첫 병렬 결과 검수와 연속 배정

- RF-004 추출 모듈별 기능 검사 매핑은 PR #260, 코드 `52df69d`, main `afedabd`로 병합했다. 선택기8 passed·staged guard 차단0/삭제0. 런타임 변경이 없어 Board 재배포/재시작하지 않았다.
- RF-201/202 장부 자산 추출은 **TEST_PASSED / SUPERVISOR_REVIEWED**다. 작업자 `958ce31`→`4a94ace`→`73368af`를 검수했고, 미소비 토큰/새 palette·미사용 API·폰트 캐시 동작 변경을 제거했다. 최종은 기존 STYLE/SCRIPT만 import 시 읽는 CSS/JS 파일로 분리한다. Supervisor가 공개 기준 `2384cfd` 모듈을 별도 실행해 STYLE32,235B·SCRIPT21,055B와 생성 HTML의 정확한 동일성을 확인했다(문자 수와 byte 수를 구별). 자산5/인접55 passed 근거를 재사용한다. source-theme 검사4 passed/2 failed는 같은 기준 실패이며, source 파일 읽기 결합만 런타임 상수로 바꾸고 단언은 보존했다. 아직 이 상태를 배포 완료로 보고하지 않는다.
- RF-103 카드 표시 교정은 빈 dict/필수키/None/불확실성의 원래 계약을 복원한 `38b78ed`까지 검수해 PR #261/main7fbf1b0에 병합했다. 표적45 passed·변경 없는 환불 코어150 passed. Supervisor 추가64 passed+28 subtests/6 failed이며, 실패6개는 기준 `2384cfd`의 원래 card_flow로 같은 ID/원인이 재현됐다. 최신 store/board와 합친 검사28 passed. 쿼리 `8c5d263`은 UI 역의존 제거·공개 baseline 교정을 완료해 순차 통합 중이다.
- RF-101은 초기 금액 Decimal→int 변환과 동적 메서드 우회를 거부하고 `496fe23` 교정을 받았다. RF-102는 전역 fallback/분기 문구/불필요한 여행 선조회와 원래 동적 호출 보존을 교정 중이다. 이 두 묶음은 아직 Supervisor 최종 수락/병합/배포 전이다.
- 자산 담당자는 다음 독립 묶음으로 기존 real_review_ui의 정적 문서 분리를, 카드 담당자는 읽기 쿼리 분리를 이어 수행한다. 새로운 금융 정책·보험/여행 항공권 기능은 추가하지 않는다. PEND-04는 브라우저 탭 소멸로 로컬 runner가 멈춘 사실을 확인하고 기존 수집 상태에서 복구했다. 운영 원문 적재·스케줄 전환은 아직 미실행이다.

## 2026-10-28 Travel INS → COST 보험가입 명단 연동 감사 (SPEC_ONLY)

양쪽 실제 코드 분석 내용을 [보험 명단 수신·운영 DB·여행별 참가자 조회 구현 명세](specs/insurance-participant-integration-20261028.md)에 추가했다. 기존 COST 수신기/참가자 전용 SQLite/owner 전용 `/participants`/Google 수입 대조는 구현됨. Travel INS `tools/payment_pause.py`에서 필수 `confirmation_reference` 누락과 미지원 `owner_attested` 전달로 실제 `finish_registration` 호출이 실패할 수 있는 **미수정 P0 결함**, 웹 `WEBLEDGER_PARTICIPANT_DB`와 로컬 전달기의 파일 동일성 **운영 미확인 P0**, 보험사 확인 후 공통 전달 흐름과 여행별 보험 참가자 표시 **부분 구현/미구현**을 각각 기록했다. 이번 커밋은 문서만 수정한다. 운영 참가자 DB·보험/금융 원본·기존 완료 작업은 변경하지 않고, 테스트·배포·실자료 수락은 수행하지 않았다.


## 2026-10-28 “미결작업 모두 진행” 후속 실행

현재 지시는 미결 항목 전부 진행이다. 이미 끝난 대사 코드를 재실행하지 않고 미연결의 추가 원본 탐색, 미수락 UI 경계, 실제 클라우드 수집 전환 공백을 처리했다. 현재 추가 실행 계약은 [클라우드 전환 절차](specs/cloud-mail-cutover.md)이며 금융/OTA의 기존 보호 계약을 유지한다.

| ID | 상태 | 실제 결과 / 남은 게이트 |
| --- | --- | --- |
| PEND-01 미연결 근거 복구 | DIAGNOSED / BLOCKED_ORIGINAL_NOT_AVAILABLE | 카카오39취소 중29연결/10미연결, Agoda76중73/3, Trip 카드 취소 전체186중171/15다. 과거 Trip1은 특정 사례 범위이며 전체 취소 수가 아니다. Trip 미연결15중12는 원승인번호가 있지만 DB 원결제0이고 보관 원본8개와 추가 로컬 파일628개의 고유 카드 파일1개에서도 대응 승인 원결제를 찾지 못했다. 나머지 번호 없는 건은 현재 근거/후보가 부족하다. 카드/원문/결정 쓰기0. |
| PEND-02 확대·키보드·오류 수락 | COMPLETE / TARGETED_ACCEPTED | 새 합성 matrix3 passed. 긴 예약번호/가맹점과 실제 펼친 카드 후보의375/1280·light/dark·100/200% CSS zoom, 키보드 선택/테마 focus, members409의 stale 행 제거와 최신 summary 재조회,400 BAD_CURSOR 표시를 검증했다. 실제 운영Aside의1425px·두테마·100/200%4조건도20행·가로 넘침0·테마1개다. 물리적 모바일 장치 검수는 아니다. |
| PEND-03 클라우드 수집/가져오기 코드 | COMPLETE / TARGETED_TESTED / COLLECTOR_DEPLOYED | 기존 코드 85817d1과 PR #256 main d37b33c. 수집기20·별도 Drive 인증14 passed, 기존 importer23+mail9/browser3 근거 재사용. 전용 프로젝트의 원격 source/manifest 일치를 확인했다. 기본 수동 실행은 읽기 전용 상태 조회다. 사용자 미추적 초안과 기존 장부 프로젝트를 보존했다. |
| PEND-04 실제 클라우드 전환 | APPROVED / BACKFILL_RUNNING | 전환·인증·원문 적재·스케줄 전환 승인을 받았다. 전용 프로젝트/Apps Script 동의/비공개 원문 폴더/수집 트리거 생성 완료. Gmail API 오류 수정 후 초기화 261.337초 정상 완료, 원문76·last_complete=null·시간당 트리거1 확인. 호스트 별도 Drive 동의 콜백·전용 ADC 저장·실제 Drive 읽기와 소유자 검증을 완료했다. 최초 미리보기는76건 모두 기존 원문/new0·append0이었다. 전체 Gmail 탐색 대상3,704건을 확인하고 단일 수집 배치를 순차 재개 중이다. 전체 탐색과 호스트 인증이 끝나기 전 원문 적재·스케줄 전환은 하지 않는다. |

- 기존 Apps Script는 `.local-archive/all-pending-20261028/cloud-remote/`에 읽기 복사본만 보존했다. 기존 Google프로젝트·장부·예약작업·운영DB·고객원문은 변경하지 않았다. 보관 카드 원본은 현재 파서로 읽기만 재생했고 출력은 비식별 집계다. 추가파일628개는 중복/비카드 파일을 포함하며628개의 새 카드 원본을 뜻하지 않는다.
- 카카오10건 중7건은 같은카드/공급자 동액 구매0이고3건의 동액 구매는 기존14일 범위를 벗어난다. Agoda3건은 외화2건에 같은카드/통화/외화금액 원결제0, 원화1건은6구매 경합이다. 이를 금액만으로 확정하지 않으며 원승인번호가 있는Trip12건도 원결제 없는 상태로 확정하지 않는다. 추가 카드 원본 또는 명시 결제 증명이 필요하다.
- 위임자의 초기 느슨한 assertion/미실행 경로/409 BAD_CURSOR 결함 주장은 수락하지 않았다. 실제 API는BAD_CURSOR400이며 Supervisor가 새 테스트를 실제구성원조회·오류문구·시간제어 후 재조회·펼친 카드·각테마/viewport/zoom/키보드 경계로 검수 보완해 최종3 passed만 근거로 삼았다. 제품 UI 변경은 없다.
- 실제실행: Node수집기18 passed, Pythoncloud23+기존메일9=32 passed, 최종browser3 passed, compile/diff·stagedguard차단0/삭제0. 기존 금융solver를 바꾸지 않았고 선택형 새 수집경로는 아직 활성화하지 않아 전체 회귀·Board재배포·재시작은 하지 않는다. 기존운영Board는`9d5ddd5`, MailCollect는`e15fd5e`다. 새 코드의 운영 활성화는완료가 아니다.
- 로컬근거: `.local-archive/all-pending-20261028/refund-evidence-summary.json`, `original-card-recovery-summary.json`, `additional-card-recovery-summary.json`, `responsive-production.json`, `drive-readonly-access.json`, `cloud-release-reviewed/`이다. 원문·개인식별자·인증값·실제계정/프로젝트/폴더ID를 추적문서에 넣지 않는다.
- 다음정확한행동: 이미 생성한 전용 프로젝트와 승인 상태를 재사용한다. 초기 전체탐색→호스트 Drive 읽기 동의→읽기 미리보기→검증백업/복원·단일작성자→원문적재→보호표/반복불변→후속 예약수집/Drive전달을 수락한 뒤에만 기존 Gmail 직접수집을 중지한다. 프로젝트 재생성·기존 Apps Script 동의 재요청은 하지 않는다.


### PEND-04 재시작 후 실제 실행 / 다음 게이트

| 단계 | 상태 / 근거 |
| --- | --- |
| 전용 프로젝트·Apps Script 동의·Gmail API 설정 | COMPLETE. 기존 프로젝트 재사용, Gmail 고급 서비스 반영, 원격 소스/manifest 일치. 초기화 실행 정상 완료. |
| 비공개 Drive 원문·초기 전체탐색 | RUNNING_REMOTE / BACKFILL_PENDING. 상태 조회 원문76·last_complete=null·시간당 트리거1. 전체탐색 완료로 표시하지 않는다. 다음 클라우드 실행은 기존 체크포인트에서 이어간다. |
| 호스트 별도 Drive 읽기 인증 | COMPLETE. 사용자 직접 동의 후 별도 readonly ADC 저장·실제 Drive about200/계정 일치·비공개 폴더/원문 목록 검증 통과. 기존 자격 증명은 변경하지 않았다. 최초20분 요청은 만료됐고 새 요청의 콜백을 정상 수신했다. |
| 전체 Drive 미리보기·백업/별도복원·운영 원문 적재·반복불변 | WAITING_FOR_BACKFILL. 아직 미실행. 전체탐색과 host ADC 확인 후 단일작성자·신선한 복구 사본·보호13표 게이트를 적용한다. |
| 후속 예약 수집·Drive 전달·기존 Gmail 직접수집 중지 | WAITING_FOR_INGEST_ACCEPTANCE. 기존 WebLedger-MailCollect를 유지했다. 최종 Google 장부·금융/여행 수동 결정 쓰기0. |

- 현재 main 구현 PR #256은 d37b33c, 후속 기본 함수 순서 변경은 상태조회 우선으로만 조정했다. Board와 MailCollect 배포/재시작은 하지 않았다. 사용자 미추적5경로와 동시 세션의 SPEC_ONLY 문서를 보존했다.
- 로컬 실행 근거: cloud-live-deployment-evidence.json, cloud-status-initial.txt 및 Aside 세션의 실행 목록. 원문·계정·프로젝트/폴더 ID·OAuth URL/코드는 추적 기록에 넣지 않는다.
- 다음 명령: `python .local-archive/all-pending-20261028/verify_cloud_live.py`는 원격 pull 후 소스 비교용이다. 호스트 동의 콜백이 끝나면 전용 ADC 존재/Drive 읽기를 검증하고, 초기 last_complete와 전체 index를 확인한 뒤 본 명세 전환순서 4~6을 이어간다. 인증 도우미 만료 시 기존 자격 증명을 덮지 않고 새 request-file로만 재시작한다.

## 2026-10-28 신규 여행별 항공권 예약 조회 (SPEC_ONLY)

[출발 여행 귀속·여행 탭 항공권 조회 명세](specs/trip-flight-booking-overview-20261028.md)를 작성했다. 연속 여행 시 귀국일이 첫 여행을 초과해도 **최초 출발 여행에 예약 전체를 귀속**, 기존 확정 회계 관계/사용자 결정을 우선 재사용하고 수입·지출과 독립된 항공권 목록을 같은 여행에서 확인한다. **명세 작성만 완료:** 코드/테스트/운영 배포·실자료 수락은 미실행이다. 기존 ALL 작업의 완료 상태를 변경하지 않는다.

## 2026-10-28 전체 진행 재지시 — 현재 실행 큐

사용자가 “모두 진행하라니까 왜 자꾸 다음작업을 남겨?”라고 지시했다. 기존 승인 요구를 작은 읽기/UI 묶음으로 축소해 종료한 판단을 정정한다. 완료 구현은 재실행하지 않고 실제 남은 대사·귀속·보류 축소·성능·수락까지 이어간다. 이 큐를 종료 전에 확인하고 실행 가능한 항목이 있으면 계속한다. 과거 ACTIVE/RUNNING 표시는 실행 큐가 아니다.

| ID | 남은 결과와 완료 기준 | 상태/현재 근거 |
| --- | --- | --- |
| ALL-01 | 숲나들e 원문 활용·카드 후보·예약 관계 검토·영수증 연결 | COMPLETE / DEPLOYED / UI_ACCEPTED. PR #250의 NICE 원문3건 적재는 백업·복원 동등성·멱등성·원문6표 한정 변경을 확인했다. 426세대 안내46건 중 후보 안내7건/후보44개·여행 근거4건, 영수증 결제2건 MATCHED_AUTO·취소안내1건 NOT_CARD_CHARGE. 화면 후보5개 표본에서 시설/금액 미확인과 결제 검증 분리를 확인했다. 실제 예약 관계·여행/Google 쓰기는 하지 않았다. |
| ALL-02 | 실제 큐 분류·예약 그룹·상위 보류 사유 수락 | COMPLETE / RUNTIME_ACCEPTED. 426세대3,799사건→3,222그룹(577개/15.19% 표시 감소), 기존3,794건 금융 판정 동일. needs_action43·waiting_source820·evidence_missing2740·completed196사건이다. 그룹 축소를 보류 해결/실제 환급으로 해석하지 않는다. Trip 그룹2구성원·개별 상세와 private 필드 비노출을 확인했다. |
| ALL-03 | worker/summary/page 병목 개선·동등성·성능 수락 | COMPLETE / MEASURED. 최종 worker261.89초(이전396.43초 대비33.9% 감소), ready/fresh426. 인증 왕복 각20회 summary p95 134.04ms/842B, groups157.10ms/22,318B, events139.32ms/7,656B. 예비150/300ms·150KB 목표 충족. 조회 burst의 반복 지문 검사를 PR #251로 제한했고 기존 쓰기 직전 최신성 보호는 유지했다. |
| ALL-04 | 카카오/Agoda/Trip·여행 귀속·Toyoko 수락 공백 해소 | PARTIAL / BLOCKED_EXTERNAL_EVIDENCE（미연결 확정）. 구현·진단·화면 수락은 완료했다. 카카오10·Agoda3·Trip1은 원승인번호 미제공, Agoda는 같은 카드1개에 두 청구가 경합하며 유일한 결제 identity/binding이 없다. 현 자료로 가능한 후보/불확실성을 표시했고 금액만으로 확정하지 않는다. 숲나들e 여행 AUTO_INFERRED/수동 유지·퇴실일 미확인, Toyoko 예약 관계와 결제 검증 분리를 실제 화면에서 확인했다. |
| ALL-05 | 인접 검사 교정·병합·고정배포·보호/화면 수락 | COMPLETE / DEPLOYED / ACCEPTED. PR #250/#251, 최종 Board `9d5ddd521272acdebb294357d18a763d89ccfc60`, 수집기 `e15fd5e2ab03ebf493cd90b24b3b6eeebfe2281d`. 기존409 passed·144 passed+4 subtests·41 passed 및 후속89 passed 근거를 재사용했다. 968 blobs일치·실행SHA·단일loopback·health/ready200·보호API401·화면 후13표 내용/스키마 불변. 첫/다음20그룹 중복0, 화면6경로·테마1개 수락. |

### 2026-10-28 계정 한도 인계 후 최종 수락

- 이전 Paseo `d398635e-dd3c-4a0b-8d81-3786ab05c951`의 로그와 현재 main을 대조했다. 이미 병합·배포된 코드는 재구현/재배포하지 않았고 이전 에이전트에는 메시지를 보내지 않았다. 실제 작업은 최종 ready 세대의 읽기 검수와 기록 정리다.
- 최종426세대에서 기존3,794건의 status·transaction_id·reserved_card_ids·allocation_basis·inferred_link·inference_basis·payment_date_verified가 동일하다. 최초423세대의 추가3건은 결제2/비금전취소안내1이며, 이후 정상 수집의 비금전 관측2건이 더해져 최종3,799건이다. 보호13표의 스키마·내용은 화면 수락 후에도 배포 전과 같다.
- 숲나들e 예약·여행 후보·승인번호 결제·취소안내, Trip 그룹/개별 상세, Toyoko 상세의6개 화면을 실제 Aside로 확인했다. 필터 debounce 이전 펼침/자동 구성원 로드와 경합하던 검수 스크립트 및 Windows 전달 중의 선택자 인용을 교정했으며 제품 코드 변경은 없다. 갱신 중 첫 조회와 실패한 검수 시도는 최종 통과 근거로 계산하지 않았다.
- 완료 근거는 로컬 `.local-archive/cost-v34-resume-20261028/resume-runtime-report.json`, `resume-financial-comparison.json`, `resume-ui-report.json`, `resume-events-pagination.json`, `protection-resume-after-ui.json` 및 호스트 `deploy-evidence-9d5ddd521272acdebb294357d18a763d89ccfc60.json`이다. 고객 원문/식별자는 Git에 추가하지 않는다.
- 실행 가능한 승인 구현·배포·읽기 수락은 완료했다. 남은 확정 연결은 위 원승인번호 또는 경합을 해소할 명시 결제 근거가 필요하다. 실제 예약 관계/여행/금융/Google 결정 쓰기는 이번 수락에서 수행하지 않았다. 실기기·200% 전 화면 검수는 이번에 새로 실행하지 않았으며 기존 모바일/합성 검사의 근거와 구분한다.
- 다음 작업은 새 사용자 요청 또는 위 결제 근거가 들어오면 해당 건의 읽기 진단부터 시작한다. 최종 코드 SHA는 위와 같고 문서 커밋은 별도 정상 PR/main 병합한다. 문서 정리 때문에 테스트·빌드·재배포·재시작하지 않는다. 기존 미추적5경로를 보존했다.

## 2026-10-28 숲나들e 업무 목적에 따른 재대사 (현재 승인 작업)

- **사용자 최신 승인:** Cost V41의 마지막 지시 “좋아. 다시 목표를 잡고 진행해.”를 Paseo 로그에서 확인했다. 직접 수집한 메일의 시설·객실·날짜·예약·취소를 업무 근거로 읽고 기존 카드·여행 후보를 찾는다. DKIM 부재를 별도 업무 보류 조건으로 삼지 않으며, 인증 헤더는 참고 메타데이터다. 이전의 “추가 인증 자료가 있어야 본문을 활용할 수 있다”는 제한은 이 최신 결정으로 정정한다.
- **목적/동작/영향/검증/종료:** 빈 필드 고정 생산자를 실제 본문 파서와 읽기 전용 후보 검색으로 교체한다. 숲나들e 생산자·카드 진단 분기·같은 worker의 여행 후보와 상세 UI만 영향받는다. 합성 원문→worker→후보→공개 상세에서 원본/ID·금액·취소·수동 결정·선택 금지 경계를 검증하고 정상 PR/main 병합·고정 SHA 배포·운영 읽기 수락을 종료 조건으로 삼는다. 금융/Google/원문/여행 배정 직접 쓰기·재적재·새 수집은 수행하지 않는다.
- **COMPLETE / DEPLOYED / READY_UI_ACCEPTED（420세대）:** [PR #248](https://github.com/6Soo/cost/pull/248), 코드 `af8c0f7`, main/Board `3e59cf72b1ad41bbe3f8ea501362d97384fd10f5`.  예약 문장의 시설·객실·시작일, 명시 예약번호·금액·체크인/아웃을 읽는다. 결제기한과 추적 URL ID는 예약 필드에 넣지 않는다. 시작일만 있으면 퇴실일은 null이고 단일 날짜의 여행 후보만 찾는다. 기존 메일별 event ID·digest는 보존하며 번호 없는 안내를 확정 병합하거나 취소를 전파하지 않는다. 시설명 또는 안내문 주소의 지자체청과 발송/이용일 7일 이내 카드는 낮은 확신의 진단 후보이고 명시 금액 일치/차이/미확인을 분리한다. 카드 점유·금융 연결 권한은 부여하지 않는다.
- **실자료 읽기 진단:** 보관 원문47건→안내46건 중 시설/객실/시작일45건·주소 지자체26건·기존 검증 여행 후보가 있는 안내4건·카드 후보0건·금액/번호/퇴실일 명시0건이다. 고유 예약 수·실제 카드 관계/환급 해결을 뜻하지 않는다. `forest-reconciliation-preview.json`은 원문 해시 불변·DB query_only/changes0을 기록하며 기존 점유 제거 전 진단 범위다. 원문과 고객 식별자는 Git/보고서에 추가하지 않는다.
- **검사:** forest/toyoko/core/detail 85 passed(기존 partial-group 검사1개 제외), forest worker/수동보호/모바일 browser3 passed, 기존 queue browser 포함 실행20 passed, 나머지 toyoko 및 candidate-read6 passed. 인접 실패3개는 분리 `beb7ca4` archive에서 동일하게 재현했다: Toyoko의 과거 버튼 문구 assertion, partial-group HOLD_NO_CARD/Windows 잠금 정리, candidate-read browser의 events→groups 미전환 fixture timeout. 통과로 계산하지 않고 범위 밖 수정하지 않는다. 전체 회귀·실기기 검사는 국소 읽기 변경이므로 생략한다.
- **배포/최종 수락:** 963 Git blobs·작업/프로세스 SHA·단일 loopback listener·health/ready200·비인증 보호API401·배포 직후 보호13표 내용/스키마 불변을 확인했다. 원래 검증 복구 사본과 이전 `787f00c` 릴리스를 보존했다. worker가396.43초에 정상 계산을 마쳐420세대 ready/fresh를 게시했다. 인증 groups/detail 전46건에서 시작일45·퇴실일 미확인45·여행 후보 안내4·인증 참고46·발신 미검증 문구0·카드 연결/후보0·private 필드 노출0을 확인했다. 실제 `/import` 상세의 본문·시작일 해석·여행 후보·인증 참고·결제 미확정 표시와 카드미조회1개를 수락했다. 테마의 첫 진단 selector는 잘못돼0이었고 실제 `#site-theme-toggle`은1개다. 화면 확인 후 최종 보호13표도 배포 전과 내용/스키마가 같다. 코드와 읽기 수락은 완료이며 실제 카드 관계/환급/여행 배정 쓰기는 수행하지 않았다. 기존 미추적 파일·stash를 보존했고 이전 에이전트에 메시지/재개하지 않았다. 이전 종료 판단은 최신 사용자의 “모두 진행” 재지시로 정정한다. 아래 전체 작업 큐의 실제 미완료를 이어가며 작은 릴리스 완료를 전체 종료 조건으로 삼지 않는다. 실제 금융/귀속 쓰기는 기존 별도 데이터 안전 게이트를 따른다.

## 2026-10-28 Cost V41 인계 후 검수

- **운영 API/UI READY_ACCEPTED（419세대）:** 최종 Board `787f00c`의417세대 ready/fresh에서 첫/다음 groups 각20개·중복0·첫14,770B·detail200·members200/같은세대·private 필드없음을 확인했다.419세대에서 실제 `/import` 첫20DOM→다음20DOM·페이지 변경·인라인 상세1개·카드후보 미조회1개·theme1을 수락했다. 숲나들e는 미검증 근거이므로 needs_action에서46건/첫20개/상세200·발신 미검증 표시·예약전용 상태·금액/번호/이용기간/카드연결 없음이다.20회 인증 브라우저 왕복 표본p95는 summary191ms/groups213ms로 summary예비150ms는 미달이다.419세대 집계는 사건/그룹 각3,794로 실제 그룹 축소0이다. 보류 감소/전체 성능 목표/실제 예약·결제 확정은 미완료다.
- **예약 그룹 DEPLOYED / API_UI_ACCEPTED:** [PR #245](https://github.com/6Soo/cost/pull/245), 코드 `9be1479`, 최초 main/Board `271f7e827b7697d55a9eeaa38bdb53af709e68ad`. 960 blobs 일치, 작업/프로세스 SHA·단일 loopback listener·health/ready200·기존/summary/events/groups 비인증401, 보호13표 내용/스키마 동일. 첫 인증 조회는 summary200/generation416/refreshing, groups409/SNAPSHOT_NOT_READY이며 새 worker index가 준비되기 전임을 확인했다. 첫 배포의 ready UI 대기는 위419세대 수락으로 해소했다. MailCollect는 기존 `3b8bf15`를 유지한다.
- **숲나들e 개별 관측 DEPLOYED / NOTICE_READ_ACCEPTED:** [PR #246](https://github.com/6Soo/cost/pull/246), 코드 `8ef9566`, 최종 main/Board `787f00c05d0d0c46254ce6b448260eebdb93a01b`(예약 그룹 포함). `forest_mail.collect`는 숲나들e 발신 예약/결제 안내를 메시지별 비금전 `RESERVATION_ONLY`로 투영한다. 예약번호·금액·이용기간·카드 결제는 생성하지 않고 서로 다른 안내를 합치거나 취소로 다른 예약을 지우지 않는다. 동일 sender-domain/owner-collected 인증 정책을 사용하며 미검증 발신은 화면 item에도 표시한다. 합성 forest/toyoko 보호39 passed·최종 label6 passed. 보관 원문47건 로컬 재생에서는 안내46건·검증 발신0/미검증46·카드연결0·생성 금액/예약번호/기간0·원문해시 불변이다. 기존 auth_pass_header_count42는 공급자 도메인 정렬 통과를 뜻하지 않는다. 실제 고유 예약 건수나 결제 수락으로 확대하지 않는다. 962 blobs·작업/프로세스SHA·health/ready200·보호API401·보호13표 불변. 원문 재적재·운영 금융 쓰기·메일 수집 작업 변경은 하지 않았다. 로컬 `forest-notice-preview-summary.json` 참조.
- Supervisor `a61ba8ab-9186-43aa-af75-aede3adbb9e8`가 이전 `77d8365a`와 `0623c63d`의 로그·작업 트리를 대조했다. 이전 에이전트에 메시지/재개하지 않았다. 예약 그룹 후속 구현자 `622a8dd8`는 idle이며 Git/통합/배포는 Supervisor가 이어받는다. 사용자 미추적 파일과 기존 stash를 보존한다.
- **예약 그룹 검수 근거:** 검증된 포털 출처 attestation만 그룹화하고 원래 금융 이벤트·ID·금액·환불·수동 결정을 보존한다. worker에서 동일 세대 summary/group/member index를 게시하며 그룹 목록·구성원은 최대20개, 목록 미리보기는 최대3개다. private attestation은 공개 snapshot/persistence에서 제외한다. singleton은 event detail을 직접 읽고 중복/누락 ID는 상세를 차단한다.
- 구현자의 지정 route/snapshot/group 검사64 passed 근거를 재사용했다. Supervisor는 browser fixture의 detail_available와 그룹 펼침의 비동기 계약을 교정했고 queue UI8 passed, 기존 결제 browser9 passed 및4 subtests를 확인했다. 금융/권한 인접74 passed, 기존 HTTP 플래그 표시2 failed; 그 중 모바일1개는 기준 `ccc2e40` 분리 archive에서도 동일 timeout을 재현했다. 실패를 통과로 계산하지 않는다. compile/diff 통과. 전체 회귀·실기기·제품 p95는 미실행이다.
- **Gmail 구조 조사 완료 / 실제 예약 필드 미확정:** 46개 iframe의 query와 응답 script를 확인한 결과 예약 본문이 아니라 열람 추적 코드이며 target URL도 없다. 앞선 '외부 프레임이 실제 본문' 추정은 철회한다. 원래 Gmail HTML에는 객실·날짜 문장이 있다. 예약번호/결제금액 표시는 확인되지 않으므로 결제·예약 관계를 확정하지 않는다. 외부 추적 코드 수집은 종료했고 원래 HTML의 구조를 로컬에서 분석했다. 날짜의 이용기간 의미나 예약 식별은 추정 기입하지 않았다. 원문47건 재적재와 수집기 재배포는 하지 않는다.
- 합성 scale: 10k사건→1k그룹 projection0.1937s/index0.0495s, 100k→10k그룹 projection2.2754s/index0.6352s, 첫20개 약22KB/0.0009s·첫/다음 중복0. 이는 합성 in-process 계측이며 제품p95가 아니다. 초기 측정 스크립트는 날짜 미상 큐를 needs_action으로 잘못 선택해 assertion으로 중단했고, 전체 큐 선택으로 교정한 로컬 `group-synthetic-scale.json`만 최종 근거로 사용한다.
- 로컬 근거는 `.local-archive/cost-v34-resume-20261028/`와 Aside `artifacts/forest-gmail-resume/`, `artifacts/ota-groups-20261028/`다. 원문/계정/예약 ID는 Git·보고서에 추가하지 않는다. 완료 코드 커밋은 `9be1479`/`8ef9566`, 운영 SHA는 `787f00c`다. 다음 실제 예약 식별·이용기간·금액 확정은 해당 필드와 발신 신뢰 근거가 있는 추가 확인서가 필요하며 현재 안내만으로 확정하지 않는다. 재개 시 `git status --short`와 본 절을 대조하고, 새 확인서가 있는 경우에만 별도 복사본에서 파싱·중복·권한 경계를 검증한다. 기존 원문 적재·배포·통과 검사를 반복하지 않는다.

## 2026-10-28 Cost V34 분류자 전체 요구 재개

사용자가 지시한 분류자 세션은 **Cost V34**, `bf7c2051-cd25-4f4c-892a-7884b16c858f`다. 기존 세션 자체는 인수 후 보관했으며 아래 새 실행이 요구사항을 이어받는다. 완료된 코드를 재구현하지 않고 각 요구의 실제 미결·수락 공백을 확인한다. Supervisor가 Git/통합/배포/본 문서를 단독 소유한다.

| 요구 묶음 | 실제 재개 세션 / 상태 |
| --- | --- |
| 카카오 환불, Agoda 상쇄쌍·취소 원결제 탐색·단순 매칭 실패, Trip.com 통화 비교·OTA 후보 연결, 여행 미배정 및 예약 연결 후 귀속 누락 | `2a8b0bf6-dce3-4c79-80bf-76204199cc5b` / RUNNING. 기존 PR #193/#200/#209와 사례 수락을 구분해 소스·보호 경계를 검수하고 허용된 app 환불/추론 범위의 결함을 수정·합성 검증한다. 실자료 탐색은 원문을 넘기지 않고 Supervisor용 로컬 읽기 진단을 구체화한다. |
| 버튼 디자인·아이콘, 불필요 문구, 월별 미배정 필터/집계, 거래처 폭·이용일, 마스킹 카드 식별·카드별 필터, 정본 읽기 전용 문구 제거, 수입/차액 용어 및 글자 크기 | `975afc81-fb6a-466d-95c4-69b5d5be961a` / RUNNING. cards_all/card_transactions/google_ledger_page/ledger_design와 해당 검사만 소유한다. 후속 수입·지출·차액 계약과 기존 검증을 보존하고 남은 결함만 수정한다. |
| 숲나들e 발신 메일 조사→OTA 반영, 제목 기준 토요코인 메일 파싱·대사 | `b5643853-0f58-4b01-bad1-ac41cb6e8d43` / RUNNING. 숲나들e 홈페이지 직접 조사는 보류한다. 실제 원문은 작업자에게 제공하지 않으며 적재/중복/미리보기/복구 경계의 정확한 로컬 실행 절차를 준비한다. 토요코인 코드 배포와 실제 수집 수락은 분리한다. |
| 앞서 재개한 OTA 예약 그룹 | `7cb1ea6c-77ec-4d48-88ea-2b20d72f2dd9` / REVIEW_PENDING. 신규 순수 모듈·합성 테스트 두 파일과 6 passed 보고를 수신했다. Supervisor 검수·생산자/worker/API/UI 연결·보호 검사·배포는 미완료다. |

각 완료 알림은 해당 묶음의 검수·남은 구현·표적 검증·병합·배포로 이어간다. 조사 완료나 이 보고를 전체 작업 종료 조건으로 취급하지 않는다. 기존 사용자 미추적 파일과 stash를 보존한다.

### 위 재개 작업의 최신 수락

- **Gmail 원문 적재·상시 수집 COMPLETE / 예약 추출 미완료:** 사용자의 Gmail 재개 지시에 따라 기존 수집 계정의 Gmail API full 형식으로 숲나들e 발신 메일 47건을 전 페이지 조회했다. 47건 모두 원래 Authentication-Results 헤더·MIME·internalDate를 보존했다. 복사본 반복 적재 전체표 불변·별도 복원본 무결성/해시 일치를 확인한 뒤 단일 작성자 게이트와 검증 백업 아래 운영에 신규 47건을 저장했다. 메시지는 3,226→3,273이며 예약·예약증거·포털·카탈로그 행과 스키마는 불변이다. 전체표 해시 변화는 원문 저장용 6개 표에 한정됐다. 예약 생성·결제 연결·여행 배정 완료를 뜻하지 않는다.
- **상시 수집 릴리스:** [PR #243](https://github.com/6Soo/cost/pull/243), MailCollect 고정 SHA `3b8bf15581289ec83f1202a3bf11e62cafe53eb5`. forest.go.kr/foresttrip.go.kr 검색 추가, 합성 9 passed. 957 Git blobs 일치·배포본 query smoke 통과 후 예약 작업의 WorkingDirectory만 변경했다. 실행 파일·인자·계정·기존 state를 보존했고 활성 상태를 복구했다. 강제 수집 실행과 Board 재배포는 하지 않았다. Board는 아래 f7c27c2를 유지한다. 구현 세션 `fe8ec536-ea41-4125-9a8b-cd4d0c49a152`은 인수 후 보관했다.
- **Gmail 본문 후속 IN_PROGRESS:** UTF-8 strict 판독은 47건 모두 성공하고 대체문자는 없지만 46건은 실제 내용을 외부 iframe으로 표시한다. 메일에 포함된 본문 프레임을 별도 로컬 관측으로 확인 중이며 Gmail native 원문이나 인증된 예약 근거와 혼동하지 않는다. 기존 다음메일 원문 4건은 별도 출처로 보존한다. 홈페이지의 일반 기능 조사는 계속 보류다. 근거는 Git 제외 `.local-archive/cost-v34-resume-20261028/`의 gmail-forest 집계·백업·복원 검증과 mail-collector-deploy-summary다.
- **읽기 진단 COMPLETE / 실사례 확정 미완료:** coverage 입력은 카드 6,395행·OTA 3,748건, 자동 확정 0·기존 사용자 결정 변경 0·중복 지출 증가 0이다. Agoda 20,532 JPY 사례는 두 OTA 결제 주장이 동일한 단일 카드 후보를 가리키지만 결제 사건 ID와 출처 binding이 없어 상호 유일성이 성립하지 않는 것으로 확인했다. 예약번호·금액만으로 두 사건을 합치지 않는다. 아래의 coverage 실행 중·다음메일 수집 중 문구는 과거 체크포인트다.
- **COMPLETE / DEPLOYED（수정 코드·합성 범위）:** PR #237~#240, 운영 `f7c27c240576e4fa0bb1dfa8f053cb7a4c451332`. Agoda 경쟁 오류 원행을 유일성 검사에서 숨기지 않도록 보호했고, 명시 메일 입력 0건 성공·진단 원문 문자열/덮어쓰기·카드 검색 버튼 스타일/아이콘 결함을 수정했다. 금융170·메일18·진단52·카드/장부81·통합21 및3 subtests·보완browser1 통과 근거를 검수했다. 957 blobs·실행SHA·단일 listener·health/ready200·API401·13표 불변, 인증 카드 화면 버튼/아이콘/theme1을 수락했다. 실기기 NOT_RUN. 세부/전후 근거는 운영 기록 참조.
- **실사례 진단 계속:** 카드 DB 읽기 전용 재조회에서 Agoda 미연결3, 카카오 미연결10(확정28/추론1)을 확인했다. 모두 원승인번호가 없다. 원결제가 없다는 뜻이나 환급 수락 완료로 확대하지 않는다. 전체 OTA coverage는 고정 `73ffb77`의 안전 출력 도구를 별도 프로세스로 실행 중이다. 결과 폴더 `.local-archive/cost-v34-resume-20261028/coverage-real-01`의 summary 게시 전에는 완료로 표시하지 않는다.
- **숲나들e 수집 진행:** 기존 Aside 다음메일 로그인 세션에서 원문 보기로 로컬 원문을 보존했다. 첫 실제 본문을 로컬에서 디코딩했지만 예약번호·이용기간·금액 필드는 확인되지 않고 결제기한 안내만 확인했다. 인증 결과를 창작하지 않고 `authentication_verified=false`로 유지한다. 다른 메일 본문 수집과 구조 대조가 남았으며 홈페이지는 계속 보류다. 원본은 Git 제외 폴더에만 보존한다.
- **예약 그룹 IN_PROGRESS:** producer private attestation과 projector 기반은 검수 보완했고 기존 collapse/금융 이벤트 계약을 유지하도록 수정했다. 같은 구현자에게 canonical worker·동일세대 summary/page·인라인 UI까지 연결하도록 소유 범위를 부여했다. 제품 완료/배포 전이며 private 출처 노출·기존 event ID/수동/환불/권한 보호를 검수해야 한다.
- **복사본 수락 / 운영 미반영:** 숲나들e 기존 UI 캡처4건의 참고 문서 적재를 SQLite backup API로 만든 별도 preview DB에서 검사했다. integrity=ok·원문 revision 생성·동일입력 재적재 후 전체 테이블 해시 동일이다. 메일/예약/결제 생성 수락으로 확대하지 않으며 운영 DB는 쓰지 않았다. 로컬 근거 `forest-reference-preview-summary.json`. 원문 수집 스크립트와 coverage 진단은 실행 중이므로 같은 명령을 중복 실행하지 않고 현재 프로세스 결과를 먼저 확인한다. 완료된 금융/UI/메일 도구 담당 세션 세 개는 결과 인수 후 공식 보관했고 예약 그룹 담당은 계속 실행 중이다.

## 2026-10-28 전체 세션 인수

- 현재 담당 세션은 `0623c63d-f549-4cba-b19b-b06be1854757`이다. 사용자 요청으로 COST workspace 세션 45개(현재 포함)를 조사했다. 인수가 확인된 기존 활성 목록의 16개를 공식 archive했고, 기존 보관 27개는 유지했다. 세션 보관은 미완료 제품 요구의 완료 처리가 아니다.
- **PARTIAL — 전체 이력 인수:** 기존 44개 중 40개의 text timeline을 Git 제외 `.local-archive/session-takeover-20261028/`에 보존했다. `1c31c7a0`는 없는 제공자 `codex-account2` 때문에 activity/log 조회가 모두 실패하여 보관하지 않았다. 이미 보관된 `dd4201c1`, `31f49529`, `bdc8e49e`도 제공자 부재로 전체 text 조회가 실패했다. 조회 가능한 최근 activity와 후속 인계는 참고했지만 네 세션의 전체 원문 인수 완료로 표시하지 않는다. 제공자 설정을 변경하거나 인증을 우회하지 않았다.
- main `9cab9b05c11c279e6d27b474cf40ebb73f8c68ba`와 열린 PR 0개를 확인했다. 마지막 검증 운영 SHA는 계속 `94ed610fd5393c1ff2d4329ac4f7f301009e729a`다. 이번은 인수/문서 작업으로 앱 테스트·빌드·재배포·운영 DB 검사를 하지 않았다. 사용자 미추적 세 경로와 기존 stash는 보존했다.
- **미결 복원 — 숲나들e:** `bf7c2051`의 최신 지시는 홈페이지 조사를 보류하고 숲나들e 발신 메일을 조사해 OTA DB에 반영하는 것이다. 이전 수집자 `e7888847`의 조회와 로컬 `messages.json` 존재만 확인했으며 내용은 열지 않았다. tracked Python에서 해당 공급자 지원 근거를 찾지 못했다. 후속 `1c31c7a0` 조회 실패 때문에 실제 적재/파싱 완료를 단정하지 않으며 중복 적재하지 않는다. 다음은 후속 기록/기존 적재 여부의 읽기 전용 확인 후 기존 백업·미리보기 게이트를 적용하는 것이다.
- **미결 복원 — 클라우드 메일 수집:** `36cb16fd`의 로컬 의존 축소 요청은 조사 중 종료됐다. `apps-script/CloudMail.gs`는 여전히 사용자 미추적 초안이며 실제 배포·전환 완료가 아니다. 원문·인증 헤더·중복 보호와 현재 수집 기능을 보존하는 설계/현황 대조가 남았다. 기존 로컬 작업을 임의 중지하지 않는다.
- **재개 — OTA 예약 그룹:** PR #233의 UI/detail 완료 다음 단계인 검증된 예약 identity/lineage 기반 그룹 projection을 source-only로 조사하도록 새 작업자 하나를 시작했다. 파일 수정·실자료·테스트·외부 접근은 허용하지 않았고 결과 검수 전 구현 완료로 표시하지 않는다. 다음은 조사 보고의 경로/필드 근거를 검수하고 최소 구현과 합성 금융 보호 검사를 정하는 것이다. 기존 summary/paging/UI 배포를 반복하지 않는다.
- **COMPLETE（위 소스 조사） / 예약 그룹 구현은 미완료:** 조사자 `458d8b5c`의 보고를 실제 소스와 대조했다. `app/ota_payments.py:115`의 source/identity와 `:132`의 메일 lineage는 출처 추적이며, portal lineage도 `:331`의 원본 위치 계보다. 공통 예약 동일성 검증 계약으로 사용할 근거는 없다. `app/ota_queue_projection.py:13`의 singleton fallback 및 `:231`의 이벤트별 집계, UI의 “예약 그룹 수 아님” 표시는 현 계약과 일치한다. 보고의 snapshot_from 링크에 있던 잘못된 `app/ota_payment_review.py` 경로는 실제 `webapp/ota_payment_review.py`로 정정해 인수했다. 조사 세션은 공식 보관했다. 다음 설계는 provider별 명시 예약 identity 검증·출처 충돌 판정과 미검증 singleton 유지 계약부터 정의하며, 이름/금액/날짜/solver group만으로 합치지 않는다. 이를 worker의 같은 generation에서 summary/page에 반영하고 exact/manual·취소/환불·unknown 보호를 합성 검증해야 한다. 이 조사에서 코드·테스트·실자료·운영은 변경/실행하지 않았다.
- 조회 실패 재개 명령: `paseo logs 1c31c7a0-265c-415a-bbf5-94503f7fe5dc --filter text --tail 10000 --json`. 제공자가 복구되지 않으면 같은 실패를 반복하지 않는다. 전체 세션/보관 대상 ID는 로컬 manifest에 보존했다.

기준: 2026-10-28 세션 `7c022586` → `2ac4764d`의 승인 작업을 현재 Supervisor가 인수했다. 이전 계정 한도 종료 기록과 실제 파일·배포 evidence를 대조했으며 이전 Supervisor에게 메시지하거나 재개하지 않았다. main·병합·배포·현재 상태 작성자는 현재 Supervisor 하나다.

## 현재 승인된 실행 큐

최신 사용자 승인은 새 리팩터링/OTA 성능 명세의 단계별 구현과 중단된 임시 구현의 검수·통합·배포·공식 보관이다. 지정 위임 순서는 Anus Free Auto → OpenRouter Free Router → AGY Gemini 3.8 medium → AGY Opus 4.6 thinking → GPT-6 Luna low였다. 기존 위임과 변경을 재사용했으며 Opus/일부 Codex 한도 및 Free Router 제공자 오류 이력이 있다. 아래 미완료 항목을 과거 완료 기능과 구별한다.

| 작업 | 현재 근거 / 다음 작업 |
| --- | --- |
| Trip.com 통화 비교·카드 필터·장부 표시 | **COMPLETE / DEPLOYED** — PR #200, 코드 `8e5eb76`, 병합·운영 `44e1e6bb90105e5d65c1b954f0c9808f4266b407`. 190 passed, 인접 125 passed/2 failed. 같은 127개 묶음에서 기준 main `0b9ebf4`도 동일 2 failed: 부분 그룹 fixture HOLD_NO_CARD와 후속 스키마 준비 오류. 실패를 통과로 계산하지 않았다. 운영 925 blobs 일치·health/ready200·보호API401·13표 동일, 실제 필터와 여행 복사 버튼 확인. worktree 고유커밋0·dirty0·터미널0·잔여 임시는 합성DB만임을 확인하고 `wks_7bc6650d01ff72da` 공식 archive 완료. |
| 카카오 환불 실제 경로 | **COMPLETE / DEPLOYED（코드 범위）** — PR #193 병합 `819c4ba`, 운영 `bff4ffd`. 선행178 passed와 최신 main 통합 후29+6+117+26 passed. 실제 추론2묶음의 기장 보류/환급 미완료 표시 확인. 원승인 없는 실제11건의 확정 연결·환급 수락은 별개다. |
| RF-001 쓰기 경계 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #202 병합. SQL 원문 비출력·오류 JSON·대표6경로 지도, 4 passed. 간접 persistence/audit·권한 체인은 `refactor-write-boundaries.md`의 OPEN_QUESTION으로 남음. 다음: 주입 backend·Google read·여행 수동 결정 경계를 소스에서 연결한다. |
| RF-001 엔트리포인트 지도 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #204 병합, 정적 AST 호출/route 후보·소유 모듈 지도, 3 passed. 미완성 API 분기는 main에 넣지 않고 `.local-archive/refactor-review-20261028/rf001-unfinished-api.patch`로 보존. 실제 runtime activation·간접 call target 증명은 아직 아님. |
| RF-003 자료 보호 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #203 병합, 합성 repo16 passed. 정책 JSON·staged 차단 exit code·경로 검증 보완. Git 메타데이터 inventory이며 기존 고객 파일 내용의 민감도·운영 소비자 분류와 배포 allowlist 완료는 아님. |
| RF-004 테스트 영향도 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #205 병합, 7 passed. 핵심 매핑·미매칭 안전 최소 검사와 실패 코드 유지. 모든 OS/실DB/전체 collection 기준선 완료로 확대하지 않는다. |
| RF-005/109 의존성 후보 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #206 병합, 8 passed. 상대 import·외부 root·오류·읽기/쓰기 후보 분류 수정. 실제 호스트 호출 전체 수락·배포 entrypoint 통합은 남음. |
| Toyoko 메일 | **COMPLETE / DEPLOYED（코드 범위）** — PR #207/#208, 최종 `570978b`. 제목 탐색·낮은 신뢰와 인증 경로 분리·불량 헤더 격리. 105+6 passed, 통합42 passed, 추가 회귀8 passed. 운영 실메일 재수집·고객 예약 개별 수락은 미실행. |
| 여행 귀속 계약 조사 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #209, `764c82d`, 5 passed. Google authority·기간·수동 우선 정의 위치와 합성 AST 경계 확인. 위치 발견은 동작 검증/실자료 원인 확정이 아니다. |

기존 구현 묶음은 모두 검수·병합했으며 임시 worktree 공식 archive를 완료했다. 마지막3개는 고유커밋0·dirty0·미추적0·터미널0·무시 경로는 캐시만임을 확인했다. 공유 stash·사용자 미추적 자료는 보존했다. 다음 단계는 R0 미확인 경계의 소스 근거 보완이며, R1 DTO/전면 리팩터링 전체 완료나 실자료 수락을 뜻하지 않는다. 종료된 세션은 재개하지 않는다. 이번 배포/브라우저/보호 증거는 `.local-archive/refactor-runtime-release-20261028/` 및 [운영 기록](operations.md)에 있다.

### 완료한 RF-001/004 후속 묶음

- **COMPLETE / DEPLOYED（이번 묶음）** — PR #211, 코드 `b2d8a06`, main/운영 `f7df4bc29d4e9dc87b2f6ddd68b8853c7be9be3a`. 최종 합성6 passed·guard 차단0/삭제0·배포942 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 CLI도 exit0·정의 후보3,957·오류0이다. 독립 개발 도구/문서 변경이므로 전체 회귀와 브라우저는 생략했다. 근거는 `.local-archive/r0-boundary-baseline-20261028/`와 운영 기록이다.
- 두 구현자 결과를 검수·통합했다. RF-001 소스 근거 커밋은 `1187954`이며 실제 Google sync CLI 호출·public/ADC 선택과 여행 검증기/change_log sink를 확인했다. RF-004 초기5 passed/CLI 파싱 오류를 최종 통과로 계산하지 않았고, 보완 후6 passed·staging/배포본 CLI exit0으로 수락했다. R0 전체 완료를 뜻하지 않는다.

### 완료한 RF-003 자료 참조 후보

- **COMPLETE / DEPLOYED（선택적 참조 조사 범위）** — PR #213, 코드 `ef91e4a`, main/운영 `44421df083f6eb7447bbfe4dc0ad10e4fb4039ca`. 보호21개 검사 근거（20 passed 후 fixture 교정한 추가1 passed）·guard 차단0/삭제0·942 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 CLI도 metadata942·소스504·정확참조99·오류0, exit0이다. 근거는 `.local-archive/rf003-source-references-20261028/`와 운영 기록이다.
- 같은 호스트/기존 local workspace의 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`（Luna low）를 재사용했다. 소유 파일은 `tools/check_tracked_data.py`, `tests/test_tracked_data_guard.py`뿐이다. commit/PR/병합/운영은 Supervisor 소유다.
- 추가 옵션 `--source-references`에서만 허용된 추적 Python 소스 AST와 Git 자료 경로 metadata를 대조한다. 고객 자료 본문·SQL·시크릿 출력 없이 명시적 읽기/쓰기/참조 후보를 기록하며 기존 기본 metadata-only·차단·보존 계약을 유지한다. 후보만으로 producer/consumer/active_use·민감도 안전을 확정하지 않는다.
- 검수에서 일반참조 누락·receiver/내용 문자열 혼동을 교정했고 Supervisor가 내부 symlink 차단·scan0 집계를 보완했다. 초기19 passed와 확장 fixture 준비 실패를 최종 통과로 과장하지 않는다. 실제 자료 분류/삭제·Git 역사 재작성은 실행하지 않았다. 동적 경로·간접 소비자·운영 활성 여부는 미확인이다.

### 완료한 RF-005/109 운영 호출 지도 보완

- 브랜치 `docs/rf003-release-and-runtime-map-20261028`, 같은 local workspace에서 구현자 `46ede148-c8a7-43b9-b783-1a89a671be40`（Luna low）가 `docs/specs/refactor-runtime-catalog.md`만 작성한다. Supervisor는 상태/운영 기록과 PR을 소유한다. 문서전용이며 테스트·빌드·브라우저·재배포 없음.
- Supervisor는 scheduler metadata에서 Board의 SHA 고정 start_web_ledger_host 참조와 SourceRefresh의 `tools/watch_review_source.ps1` 이름/저장소 cwd 참조를 확인했다. 원문 인자·비밀값은 출력하지 않았다. 담당자는 repo 안의 실제 호출·외부 dependency·쓰기/복구 게이트를 소스 경로/줄로 추적하며 repo 밖 파일/DB/설정은 읽지 않는다.
- **COMPLETE（이번 문서 범위） / R0 전체 PARTIAL** — Board launcher→run_candidate, SourceRefresh wrapper→collect/activate→bundle/config/status, 임시 복사본 DB probe·별도 복원 target·dry-run manifest의 소스 참조를 대조했다. 전달된 scheduler metadata와 source-only 근거를 분리했고, PR #213 이후 최종 SHA/health 미확인 문구는 이미 검증된 운영 기록 참조로 교정했다. 원문 인자·환경/인증·외부 호스트 코드·DB는 열지 않았다. diff/참조/링크만 확인하며 테스트·빌드·브라우저·재배포는 하지 않는다. 외부 wrapper 전체 동작·실제 SourceRefresh 활성 결과는 미확인이다.

### 완료한 RF-002 거래 상태 계약의 독립 기반

- 기준 main `37cf912`（PR #214 문서 병합）, 브랜치 `refactor/rf002-transaction-state-contract-20261028`. 운영은 계속 `44421df`다. R0 정적 지도·보호·표적검사 기준선은 확보했으며 외부 운영 OPEN_QUESTION은 유지한다.
- 같은 local workspace의 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`（Luna low）가 새 `app/transaction_contract.py`, `tests/card_pipeline/test_transaction_contract.py`만 작성한다. 실제 런타임 경로에 연결하지 않는 순수 DTO·mapping 변환의 합성 계약부터 시작한다.
- 기존 거래 원본/금액/통화/ID·사용자 결정·독립 상태 축과 알 수 없는 값·필드/누락/None을 보존한다. 새로운 금융·환급·기장·여행 정책을 계산하거나 런타임/DB/Google을 변경하지 않는다. 입력/출력 alias 오염·정확 roundtrip을 새 합성 검사로 확인한다.
- **COMPLETE / DEPLOYED（독립 거래 DTO 기반）** — PR #215, 코드 `77e2c0f`, main/운영 `179acb59dbe22dc28b982c8a2d16f5c7de8ed05c`. 최종13 passed·guard 차단0/삭제0·추적944 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 합성 import/roundtrip/입력변경 차단 스모크도 통과했다. 아래 검수 대기·미병합 문구는 과거 이력이며 현재는 수락·병합·배포 완료다. 기존 런타임에는 연결하지 않았고 전체 RF-002 완료가 아니다.
- 검수에서 최초7/10 passed 이후 발견한 mutable 객체·public 생성·timezone/key 노출을 교정했다. 최종13 passed로 수락했으며 지원 domain에서 누락/None·unknown 상태/추가값·금액/통화/ID 왕복과 불변성을 확인했다. 미지원 객체·cycle은 원문 없는 오류로 거부한다. 실제 transactions 필드와 axis 목록을 대조했고 미래/runtime 필드는 extras로 보존한다. 전체 RF-002 채택이나 R0 운영 미확인 해소는 아니다.

### 완료한 RF-002 OTA 상태 계약의 독립 기반

- 기준 main `d4718a8`（PR #216 문서 병합）, 브랜치 `refactor/rf002-ota-state-contract-20261028`의 같은 local workspace에서 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`（Luna low）가 새 `app/ota_state_contract.py`, `tests/card_pipeline/test_ota_state_contract.py`만 작성한다. Supervisor가 branch/문서/PR/운영을 소유한다.
- 관측된 event/result/snapshot 필드에 근거해 예약관계·카드검증·여행귀속·내부기록·실제환급을 분리한다. 기존 공개 FieldSlot을 재사용하고 알 수 없는 값·누락/None·수동/exact/inferred·취소/stale·ID/금액통화를 정확히 보존한다. 원문에 없는 기장·환급확정·여행을 만들지 않고 기존 runtime helper에는 연결하지 않는다.
- **COMPLETE / DEPLOYED（독립 OTA 기반）** — PR #217, 코드 `0ad04bd`, main/운영 `361d012d495f9a3a245e092933e4102967689642`. 최종16 passed·guard 차단0/삭제0·추적946 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변。배포본 합성 import/왕복·명시적 종류에 따른 상태 분리·입력 변경 차단·기장/환급확정 비창작 스모크 통과.
- 검수에서 초기13/15 passed 이후의 shape 추정·core_link 오분류·상위 예약축 직렬화 누락을 교정했다. `kind`를 호출자가 명시하고 카드 status·snapshot freshness·예약관계 상태를 분리한다. `core_link`는 projection 근거이며 내부기장 축은 비어 있다. unknown/None/누락·ID/금액·수동/exact/inferred/stale·예약 추가필드·중첩 불변성을 확인했다. 기존 runtime 미연결이고 실제 대사·배정·기장·Google 쓰기는 없다.

### 진행 중인 RF-002 실제 읽기 경로 채택 조사

- 브랜치 `docs/rf002-ota-release-and-adoption-20261028`. 같은 local workspace의 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`（Luna low）가 `docs/specs/refactor-master-20261027.md`만 수정한다. 가장 작은 실제 읽기 소비경계·입출력 shape·caller/authority/freshness·복사비용·합성 동등성 검사 범위를 소스 근거로 좁힌다.
- **COMPLETE（소스 조사）** — 실제 caller의 freshness gate와 helper의 좁은 입력 shape를 대조했다. 전체 DTO freeze/thaw는 전량 복사를 늘리므로 채택하지 않는다. 다음 구현은 `project_card_ota_statuses` 실행 본문을 유지하고 필요한 필드를 별도 `TypedDict` 정적 읽기 계약으로 선언·입력 annotation에 연결하는 최소 범위다. 기존 금융/여행/Google 쓰기 authority는 그대로 유지한다. 이 문서전용 검수는 diff/참조/링크만 확인하며 테스트·빌드·브라우저·운영 재검사는 하지 않았다.

### 완료한 RF-002 OTA 상태 조회의 정적 읽기 계약

- PR #218 문서 병합 후 브랜치 `refactor/rf002-ota-status-read-contract-20261028`. 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 새 `app/ota_status_read_contract.py`, 기존 `app/ota_core_projection.py`만 작성한다.
- helper가 읽는 필드의 `TypedDict`와 입력 annotation만 연결하고 상태 계산 본문·순서·원본 identity·caller freshness는 유지한다. wrapper/factory·복사·원문변환·새 정책/쓰기 경로를 추가하지 않는다. 타입 선언은 runtime 검증/불변 snapshot을 제공하지 않는다.
- **COMPLETE / DEPLOYED（해당 읽기 계약）** — PR #219, 코드 `175c3a2`, main/운영 `42999afa15373014c35be9ee10fda308a6dd1e3c`. 표적3파일28 passed·compile/diff·본문AST동일. 합성1000결과+1000후보 출력 동일; 30회 중앙값 baseline0.052944s/변경0.053033s·peak156,994/156,946B. 제품 지연 개선 주장은 없다.
- guard 차단0/삭제0·947 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 annotation 해석·exact/group/reservation/None 스모크 통과. 전체 회귀/브라우저는 실행본문 불변의 타입 변경이므로 생략했다. 근거는 `.local-archive/rf002-ota-status-read-20261028/`와 운영 기록이다.

### 완료한 RF-002 거래 배치 조회의 정적 읽기 계약

- 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 새 `app/transaction_read_contract.py`, 기존 `app/review.py`, `app/__init__.py`만 작성한다. 현재 브랜치는 Supervisor 소유 `docs/rf002-ota-status-read-release-20261028`이며 구현자는 branch/commit/PR/운영을 변경하지 않는다.
- 실제 `get_batch/_row_dict/_counts` 출력과 facade의 return annotation만 연결한다. SQL/실행본문·권한·금액/ID·상태 계산·원본 JSON·호출 순서를 유지하고 DTO 복사·cast/factory·새 runtimecall을 추가하지 않는다. 실제 출력 필드의 독립 축과 nullable 값·future state counts를 TypedDict로 명시한다.
- **COMPLETE / DEPLOYED（해당 읽기 계약）** — PR #220, 코드 `a8d28dd`, main/운영 `b3cabe8b38b2956381a8827327445cfa30b64c35`. 합성pipeline 지정 범위3 passed/42 deselected·4함수 실행AST동일·compile/diff 통과. Supervisor는 동적 counts를 `dict[str,int]` alias로, 실제 출력 키는 required/nullable value로 교정했다. SQL/실행본문/원행/ID·금액/사용자결정/권한/반환 순서가 같으며 새 wrapper/복사/runtime 검증은 없다.
- guard 차단0/삭제0·948 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 annotation/required키/합성fake-store batch/nullable/미지 상태counts 스모크 통과. 전체 회귀/브라우저는 실행본문 불변의 타입 변경이므로 생략했다. 근거는 `.local-archive/rf002-transaction-read-20261028/`와 운영 기록이다. 전체 RF-002 완료는 아니다.

### 진행 중인 RF-201 기존 디자인 토큰 조사

- 같은 local workspace에서 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`（Luna low）가 `docs/specs/refactor-master-20261027.md`만 수정한다. 현재 Supervisor 브랜치는 `docs/rf002-transaction-read-release-20261028`이다. 마스터가 허용한 독립 토큰 조사이며 기존 RF-002 금융/OTA 경계를 변경하지 않는다.
- site_theme/site_shell/ledger_design의 이미 통합된 토큰·shell/theme owner를 소스와 기존 검사에 대조하고 실제 중복/누락만 찾는다. 기존 표시 값을 유지하는 최소 토큰 정리 후보 하나와 영향 페이지/필수 검사를 제시한다. 수동 테마 아이콘1개·기존 URL/DOM을 유지한다.
- **IN_PROGRESS / NOT_VERIFIED** — 문서전용 source/diff 참조 조사이며 테스트·빌드·브라우저·호스트 재검사·시각 변경은 하지 않는다. 완료 알림 후 `git diff -- docs/specs/refactor-master-20261027.md`를 검수한다. 실제 모바일/200%/모든 화면 수락을 주장하지 않는다.
- **COMPLETE（소스 조사）** — 공통 색상과 단일 토글이 이미 통합돼 있음을 소스/기존 검사에 대조했다. wrap_document는 전체 STYLE와 root palette를 함께 삽입하고 fragment는 유지한다. 다음 최소 구현은 두 파일의 테마 버튼44px 반복을 공통 CSS 토큰으로 모으는 범위로 결정했다. token owner/fallback/기존 computed-size 검사 근거를 master에 기록했다. 문서 diff/source 참조만 검수했고 운영·브라우저를 다시 확인하지 않았다.

### 완료한 RF-201 테마 버튼 치수 토큰

- PR #221 문서 병합 후 브랜치 `refactor/rf201-theme-control-token-20261028`. 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 `webapp/site_theme.py`, `webapp/site_shell.py`만 작성한다. Supervisor가 branch/문서/PR/배포를 소유한다.
- 버튼 소유 `site_theme.STYLE`에 `--shell-theme-control-size:44px`을 선언하고 두 파일의 해당 버튼 width/min-width/height/min-height만 동일44px fallback으로 연결한다. 색상/sidebar/타버튼/DOM/JS/테마정책은 변경하지 않는다.
- **COMPLETE / DEPLOYED（해당 토큰）** — PR #222, 코드 `72781a6`, main/운영 `d230e124b27f268de8e8e3812abe53885e5e2212`. 지정 두 파일의4개 치수/44px 선언만 검수했다. 기존 manual-theme/mobile-topbar5 passed·익명CSS24조건 동일（375/1280·light/dark·100/200%·combined/개별fallback）. 결합44×44/확대88×88px·개수·색 동일. 실제 기기 미실행이고 전체 RF-201 완료가 아니다.
- guard 차단0/삭제0·948 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. Aside 같은-origin GET200에서 token44px·8소비·단일버튼 확인, 사용자 페이지 탐색/입력/테마 변경 없음. 근거는 `.local-archive/rf201-theme-control-20261028/`와 운영 기록이다. 국소 token 추출로 전체 회귀는 생략했다.

### 진행 중인 RF-202 공통 shell 응답 경로 조사

- 현재 브랜치 `docs/rf201-theme-control-release-20261028`, 같은 local workspace 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`가 `docs/specs/refactor-master-20261027.md`만 작성한다. 이미 통합된 wrapper/단일 테마를 재구현하지 않는다.
- HTTP HTML 응답 writer→wrap_document→주요 private renderer의 source 경로와 auth/public/API/fragment 예외를 매핑한다. 실제 우회가 있을 때만 최소1개 후보를 제시하고 native nav/main 소유권·URL/폼/JS/ID·테마 아이콘1개를 보존한다.
- **IN_PROGRESS / NOT_VERIFIED** — 문서전용 source/diff 참조 조사이며 테스트·빌드·브라우저·호스트/DB 재검사를 하지 않는다. 실제 기기/200% 전체 수락이나 저장소 전수 완료로 확대하지 않는다. 다음 명령은 완료 알림 후 `git diff -- docs/specs/refactor-master-20261027.md`다.
- **COMPLETE（소스 조사）** — Handler._send→wrap_document와 카드/Google/항공권/OTA/영수증·native ledger·fragment/auth/public/API 경로를 대조했다. 표본 범위에서 private 전체HTML 우회는 발견하지 못했고 기존 의도 예외를 새 작업으로 만들지 않는다. 동적 문서 전수·실제 기기/200% 수락은 미확인이다. 문서 diff/source 참조만 확인했다.

### 진행 중인 OTA 대기열/페이지네이션 기준선

- 기준 main `0512d80`（PR #223 문서 병합）, 브랜치 `refactor/ota-queue-baseline-20261028`. 같은 local workspace 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`가 `docs/specs/ota-review-queue-performance-20261027.md`만 작성한다. 기존 API/public allowlist·snapshot publish/freshness·summary/events/cursor 기존 구현 여부·순수 queue projection 입력을 소스에서 조사한다.
- Supervisor의 인증 같은-origin GET8회 기준선:200·응답899,499B·같은세대1·공개이벤트1,072·카드후보map0. p50 205ms/표본p95 1,750ms이나 측정 중 refreshing/stale이므로 ready/warm 성능이나 server-only p95가 아니다. 공개목록 subset을 전체 정본 건수로 보고하지 않는다. 사용자 페이지 탐색/입력/테마와 금융/Google 상태를 바꾸지 않았다.
- 원문 없이 알려진 status별 집계·경고 개수·bytes/time만 `.local-archive/ota-queue-baseline-20261028/current-api-baseline.json`에 보존했다. **SOURCE_AUDIT_PENDING** — 완료 알림 후 순수 queue/summary의 최소 구현 범위를 결정한다. 기존 solver·manual/exact link·원승인/복수환불·여행/금융 쓰기와 legacy route는 유지한다. 다음 명령은 `git diff -- docs/specs/ota-review-queue-performance-20261027.md`다.
- **SOURCE_AUDIT_REVIEWED** — 별도summary/events/cursor 미구현과 기존 lazy-card GET·worker freshness/last-good·public allowlist를 소스 대조했다. public 목록은 holds subset이므로 전체 canonical summary 입력과 구분하도록 교정했고 검증된 예약 그룹 계약 전에는 singleton fallback만 허용한다. 다음은 route/UI 미연결 순수 queue classification/summary이며 금융 상태 변경이나 완료/성능 개선을 주장하지 않는다.

### 진행 중인 OTA 순수 queue/summary projection

- PR #224 문서 병합 후 브랜치 `feat/ota-queue-pure-projection-20261028`. 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 새 `app/ota_queue_projection.py`, `tests/test_ota_queue_projection.py`만 작성한다. route/GET/UI/solver/store에는 연결하지 않는다.
- 명시적 canonical/public_subset coverage·freshness·유효한 source 상태/근거·경고를 바탕으로 display queue만 계산한다. completed는 대사검토 범위이며 기장/실환급/여행 확정이 아니다. unknown/changed/missing/manual-warning·duplicate/missing identity와 stale 등은 완료로 올리지 않는다. 검증된 예약 그룹 계약 전에는 singleton fallback이며 input event를 버리거나 합치지 않는다.
- **IN_PROGRESS / NOT_VERIFIED** — 원문/ID/금액이 없는 safe summary·event/group count·비authoritative 상태·입력불변성과 합성10k/100k precompute 비용을 확인한다. 금융/Google/고객 원본 쓰기와 실제 API 조회는 구현자에게 허용하지 않는다. 다음 명령은 완료 알림 후 `git diff -- app/ota_queue_projection.py tests/test_ota_queue_projection.py`다. 운영은 `d230e12`로 유지한다.
- **REVIEW_FIX_PENDING** — 구현자의 초기31 passed·compile/diff와 합성10k/100k 계측 보고를 수신했으나 최종 수락하지 않았다. 현재 파일 검수에서 명시적 `fresh=False` 미반영, 경고/충돌보다 대기 분기가 앞서는 우선순위, 잘못된 freshness metadata의 원문 반환, stale 중 duplicate 처리의 전역 gate 덮어쓰기를 확인했다. 같은 구현자에게 지정 두 파일의 회귀 검사와 보완을 요청했다. 완료에는 유효한 transaction identity도 요구한다. 보완 알림 후 파일·지정 테스트를 검수하며 API/UI 성능 완료나 운영 반영으로 보고하지 않는다.
- **REVIEWED / RELEASE_PENDING** — 구현자 보완51 passed 후 Supervisor가 conflict evidence와 waiting/missing 상태의 우선순위9개 회귀를 추가해 지정60 passed·compile/diff를 확인했다. metadata는 JSON-safe primitive만 반환하고 fresh/enabled 부정·malformed envelope는 전역 auto_recheck, duplicate는 이를 덮지 않는다. 합성10k 0.2368s/2,287,945B·100k 2.7025s/24,632,608B는 구현자 계측이며 제품 p95가 아니다. 다음은 지정 두 코드 파일과 상태 기록만 commit/PR/병합하고 검증된 SHA를 배포한다. API/UI·pagination은 미구현 상태다.

- **COMPLETE / DEPLOYED（순수 projection 범위）** — PR #225, 코드 `522e55e`, main/운영 `a6f4abc12f23ff2fdc50c7a26f4f26ce1dfd7b6d`. 지정60 passed·compile/diff·guard 차단0/삭제0·950 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변·배포본 합성 스모크 통과. 근거는 `.local-archive/ota-queue-projection-20261028/`와 운영 기록이다. 기존 API/UI에 연결하지 않았으므로 제품 성능 개선이나 전체 OTA 명세 완료가 아니다.
- **NEXT_SOURCE_AUDIT_PENDING** — 기존 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`가 `docs/specs/ota-review-queue-performance-20261027.md`만 조사한다. canonical event/result 결합·worker precompute·last-good freshness·public sanitization·summary와 세대/필터 바인딩 cursor API의 가장 작은 연결 범위 및 수락 검사를 제시한다. 코드/테스트/브라우저/DB/배포는 실행하지 않는다. 완료 알림 후 해당 문서 diff/source 참조를 검수한다.

### 진행 중인 OTA canonical summary 연결

- PR #227 source audit 문서 병합 후 main `513b9bb`, 브랜치 `feat/ota-canonical-queue-summary-20261028`. 기존 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 `webapp/ota_payment_review.py`, `webapp/ota_snapshot.py`, 새 `webapp/tests/test_ota_queue_summary.py`만 소유한다. Supervisor가 git/문서/검수/배포를 소유한다.
- worker에서 full canonical source/result를 중복·누락·orphan 보호 하에 결합하여 aggregate만 precompute/persist하고 `/api/imports/ota/summary`는 같은 세대 저장값만 읽는다. missing/ambiguous join과 manual/source 변경은 완료 차단, nonready는 완료 집계를 전역 auto_recheck로 표시하고 authoritative=false다. 기존 holds GET/cards lazy/POST 권한·금융 상태는 유지한다. events/cursor/UI는 이번 범위에 넣지 않는다.
- **IN_PROGRESS / NOT_VERIFIED** — 완료 알림 후 지정3파일 diff와 합성 freshness/restore/auth/GET 계산0회/원본 불변 검사를 검수한다. 실제 DB/Google/고객 원본 쓰기·브라우저·운영 접근은 구현자에게 허용하지 않는다. 운영은 `a6f4abc12f23ff2fdc50c7a26f4f26ce1dfd7b6d`다.
- **REVIEWED / RELEASE_PENDING** — 구현자 지정29 passed·기존 보호5 passed 후 Supervisor가 누락 solver 필드의 source fallback 차단, source evidence conflict 보존, 세대 불일치 finite tag를 보완했다. 통합3파일73 passed/1 failed: 기존 partial-group fixture가 HOLD_NO_CARD이며 임시DB 정리 WinError32를 동반한다. 변경 전 운영 `a6f4abc`의 동일 단일 검사에서도 동일 실패를 재현했고 통과로 계산하지 않았다. 최종 신규 summary24 passed（추가7개 경계 포함）·compile/diff 통과. 다음은 지정3파일과 기록만 PR/정상병합/고정SHA배포하고 보호13표·health/auth·인증 summary 최소 읽기를 확인한다. 페이지/cursor/UI는 남아 있다.
- **DEPLOYED / READY_ACCEPTANCE_PENDING** — PR #228, 코드 `b28202d`, main/운영 `bcb2b7cfbfc28e536f2727bda677268237ab248c`. 951 blobs 일치·실행 SHA·health/ready200·기존 및 summary 비인증API401·보호13표 동일. Aside 인증 summary200·477B는 현재 generation402/refreshing이며 summary없는 이전 persisted cache를 unavailable/counts=null/non-authoritative로 표시했다. 후속1회도 동일했고 ready 성능/정본 건수 수락은 아직 미실행이다. worker log의 안전 metadata에서 새 배포 후 refresh_start를 확인했으며 기존 child timeout900초를 변경하거나 강제 재대사하지 않았다. 다음 독립 paging 작업 중 새 세대 게시 후 summary 집계만 다시 확인한다. 근거 `.local-archive/ota-canonical-summary-20261028/` 및 운영 기록.

### 진행 중인 OTA page index/cursor

- main `926814a`, 브랜치 `feat/ota-queue-page-index-20261028`. 기존 구현자가 신규 `app/ota_queue_paging.py`, `tests/test_ota_queue_paging.py`만 작성한다. worker/GET 연결은 이 부품 검수 후 같은 브랜치에서 이어가며 독립 부품만 별도 릴리스하지 않는다.
- worker용 stable singleton index와 bounded queue/provider/search/limit, generation/filter/limit/snapshot nonce에 바인딩한 HMAC cursor를 구현한다. 원문 ID/검색어는 cursor에 넣지 않고 page allowlist만 반환한다. 날짜 미상/중복·누락 ID는 버리거나 합치지 않는다. 금융 상태 재분류·solver/UI/실자료 쓰기는 금지한다.
- **IN_PROGRESS / NOT_VERIFIED** — 완료 알림 후 지정 두 파일과 합성 연속페이지/변조/세대·필터불일치/입력불변·출력제한 검사를 검수하고 worker/route 연결을 진행한다. 동시에 기존 summary의 새 세대 게시 후 aggregate-only ready 수락을 확인한다. 운영은 `bcb2b7c`다.
- **INDEX_REVIEWED / ROUTE_IN_PROGRESS** — 초기18 passed 후 Supervisor가 missing/invalid provider의 전체목록 중복계수, amount 문자열 비수치값 노출, 검색 전체 hit-list 메모리를 보완해20 passed. 같은 구현자에게 이 두 파일 및 `webapp/ota_payment_review.py`, `webapp/ota_snapshot.py`, 새 `webapp/tests/test_ota_queue_pages.py`만 소유권을 부여해 worker index/인증 events GET을 연결하도록 했다. index는 실제 snapshot generation과 lock 밖에서 준비하고 원자 게시한다. nonready/restored-before-rebuild page는409, GET에서 재계산하지 않는다. signing key는 메모리에만 두고 restart 이전 cursor는400이 가능하며 같은 process의 세대/필터불일치는409다. 부품만 별도 배포하지 않는다.
- **SUMMARY_READY_ACCEPTED（기본 응답 범위）** — 기존 운영 `bcb2b7c`의 인증 GET200·765B·generation403·ready/authoritative, 큐 event/group 합계3,748（needs_action1,622/waiting820/missing1,112/completed194）·상태태그없음을 확인했다. singleton 집계이며 금융 기장·실제환급 완료가 아니다. 원문없는 근거 `.local-archive/ota-canonical-summary-20261028/auth-summary-smoke-ready.json`. 단일 GET 수락으로 제품p95는 주장하지 않는다. 이전 READY_ACCEPTANCE_PENDING은 이 기본응답에 한해 해소됐다.
- **ROUTE_REVIEWED / RELEASE_PENDING** — 구현자5파일 연결을 검수했다. 통합 paging/route/summary/snapshot74 passed 후 Supervisor가 invalid filter/limit의 snapshot 조회 전400 경계4개를 추가해 페이지21 passed·compile/diff를 확인했다. 기존 holds/cards/auth 선택2 passed 근거를 재사용한다. 합성10k precompute0.813s/page0.0018s/peak15,683,865B/payload6,033B·100k10.43s/0.0026s/156,787,065B/6,034B는 제품p95가 아니다. q는O(n) 검색이고 query cache는 없다. index/key는메모리에만 보관, restore 후 재계산 전409이며 source scalar snapshot으로 입력mutation을 차단한다. 다음은 지정5파일과 기록만 PR/병합/배포하고 새 세대의20개 응답·cursor연속/거절·auth·보호13표를 확인한다. UI는 아직 미연결이다.

- **COMPLETE / PAGE_READY_ACCEPTED** — PR #230 코드 `deb9245`, 당시 main/운영 `af42ea0`의 954 blobs·health/ready200·실행SHA·단일listener·비인증401·보호13표를 확인했다. 초기403/refreshing의409 이후 generation405 ready에서 인증 첫/다음 각20개HTTP200을 수락해 기존 pending을 해소했다. 현재 배포는 아래 PR #233이며 과거 배포를 반복하지 않는다.
- **COMPLETE（소스 조사）** — 문서 담당자의 `docs/specs/ota-review-queue-performance-20261027.md` 조사와 실제 source를 검수해 PR #232로 병합했다. 전체holds client slice를 피하고 generation-bound detail GET이 필요한 gap을 확인했으며, 그 구현/검증/배포는 아래 PR #233 묶음에서 완료했다.

### OTA paged UI/detail 검수 및 릴리스

- PR #232 source audit 병합 후 main `4802a02`, 브랜치 `feat/ota-paged-review-ui-20261028`. 기존 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 `webapp/ota_payment_review.py`, `webapp/ota_snapshot.py`, 새 `webapp/tests/test_ota_queue_detail.py`, 새 `webapp/tests/test_ota_queue_ui_browser.py`, 기존 `webapp/tests/test_ota_payment_review_browser.py`만 소유한다. Supervisor는 문서/git/검수/배포를 맡는다.
- worker의 같은 세대 private detail map 및 인증 generation-bound 단일event GET을 추가하고, 실제 render_import_section을 summary+20건페이지로 연결한다. 상세/카드는 펼칠 때만 읽고 전체holds GET/client slice를 금지한다. 기존수동/예약/그룹/규칙제안 controls·unsaved선택·닫힘pollstop·단일theme를 보존한다. 규칙제안은 bounded cache read 등 최소기능보존 계약을 선택하며 미완료는 숨기지 않는다.
- **COMPLETE / DEPLOYED / READY_UI_ACCEPTED** — PR #233 코드 `63dd532`, main/운영 `94ed610fd5393c1ff2d4329ac4f7f301009e729a`. 956 blobs·실행SHA·health/ready200·비인증401·보호13표 불변. 이전 Supervisor `4e49282a`의 로그·실제 diff를 대조해 인수했다. 동시에 이어진 구현자 `26175585`의 동일 파일 작성이 확인되어 해당 세션만 interrupt하고 변경을 합쳐 검수했다. 이전 Supervisor에게 메시지/재개하지 않았다. 한국어 문구·집계 미확인·세대 불일치 폐기/재조회·필터 되돌리기·제안/예약 입력 및 늦은 polling 응답의 미저장 선택 보호를 보완했다. 그룹 순서 대응의 예약/카드 근거는 worker의 제한 projection으로 보존하고 후보는 lazy GET으로 유지한다.
- 실제 검사: 상세/UI/lazy/preview-race 20 passed, 마지막 경합/세대/cursor 3 passed, 기존 브라우저 9 passed 및 4 subtests, 카드 후보 경계 4 passed. 인접 page/summary/snapshot/actions/legacy 115 passed/2 failed 중 후보 browser fixture는 새 조회 계약으로 교정 후 통과했다. 나머지 partial-group HOLD_NO_CARD/임시DB WinError32는 운영 기록에 이미 기준 `a6f4abc` 재현 근거가 있는 기존 실패이며 통과로 계산하지 않고 범위를 확대하지 않는다. compile/diff 통과. 실제 기기와 제품 p95·보류 solver 개선 완료는 아니다.
- 배포 전 기존 운영 `af42ea0` 인증 조회에서 generation405 ready/fresh 및 첫/다음 페이지 각20개 HTTP200을 확인했다. 고객 원문/ID는 출력하지 않았다. 배포 및 보호 검사와 generation406 ready 수락을 완료했다. 인증 첫/다음20개HTTP200·같은세대·교집합0·detail200/비공개키없음·제안200/0개, 실제20DOM→다음20DOM·상세lazy/카드미조회·전체holds미호출·theme1개를 확인했다. 근거 `.local-archive/ota-paged-ui-20261028/ready-smoke-final.txt`와 운영기록. 이번 UI/detail 묶음에 남은 필수 검사는 없다. 다음 독립 단계는 승인 명세의 예약 그룹 projection/보류 solver 보강이며 이번 완료로 확대하지 않는다. 금융/Google/원본 직접 쓰기·마이그레이션·실제 확정은 하지 않는다.

## 2026-10-27 전면 리팩토링 명세 작성 이력 (작성 당시 SPEC_ONLY)

사용자 지시에 따라 [아키텍처·UI·데이터·운영 전면 리팩토링 마스터](specs/refactor-master-20261027.md), [917개 추적 파일 경로 인벤토리](specs/refactor-file-inventory-20261027.tsv), [OTA 보류 대기열/성능 계약](specs/ota-review-queue-performance-20261027.md)을 추가했다. 전체 Git 트리 메타데이터와 핵심 코드 횡단 표본 감사에 기반한 **구현 가능한 에이전트 백로그**다. 각 파일 개별 함수의 전수 코드 감사 완료를 뜻하지 않으며, 후속 RF-001 코드/호출 경로·데이터 감사가 우선이다. 이번 PR은 DOCS_ONLY: 런타임 변경·pytest·운영 재배포·실자료 수락은 없다. 문서 작성 시점 이후의 활성 PR 및 운영 릴리스는 매번 최신 재조회하고, 기존 완료 작업을 반복하지 않는다.

## 마지막 확인된 릴리스

운영 코드 SHA는 **`94ed610fd5393c1ff2d4329ac4f7f301009e729a`**다. PR #233 paged UI와 generation-bound lazy detail/proposal GET을 검수·병합·고정 배포했다. 기존 병합 기능도 보존했다. 문서 커밋을 앱 배포 SHA로 표시하지 않는다.

이번 근거: 추적 파일956개 blob 일치, 작업/프로세스 SHA 일치, 단일 loopback listener, health/ready200·보호API401, 2DB/13개 보호 표 내용·스키마 동일. 운영HTML GET200·token44px/8소비/단일버튼 스모크 통과, 사용자 페이지/입력/테마 변경 없음. 실제 환불121묶음·추론2묶음의 보류/환급 미완료 표시 수락은 `bff4ffd` 근거다. 세부 검사·기존 실패·근거 경로는 [운영 기록](operations.md)에 있다. 추가 수집·금융/Google 직접 쓰기 없음.

## 2026-10-28 활성 세션 인수 상태

- **COMPLETE — 여행 탭 지출 복사:** 세션 `af475563`의 사용자 최신 요구는 각 여행별 탭 하단에만 복사 기능 제공이다. 코드 `a3e0316`을 검수하고 `75aa984`에서 공통 TSV 검증·실제 여행 확인·필터 일치·복사 실패 처리를 보완했다. 알 수 없는 증빙을 카드로 바꾸지 않고 잘못된 날짜/금액·중복·보류 건은 제외 수를 알린다. PR #198 병합 및 위 SHA 운영 배포 완료.
- 실제 검사: 복사·수입 브라우저·live-sync 59 passed, 4 subtests passed. 최종 API/공통 TSV/adapter 28 passed. 합성 실제 클립보드의 7열·부호·증빙, 비로그인401·viewer 거부 확인. 전체 회귀는 국소 읽기·클립보드 변경이므로 생략. 운영 DB·Google·원본 쓰기 및 운영 클립보드 변경 없음.
- **COMPLETE — 이전 Cost V35 인계:** 중단 구현은 Trip.com/카카오/Toyoko/여행 감사로 분리 검수·보완해 위 PR과 릴리스에 통합했다. 이전 세션 알림 대기는 종료했으며 임시 workspace 공식 보관을 마쳤다. 개별 실자료 미결은 아래에서 별도 유지한다.
- 배포/보호/브라우저 근거는 `.local-archive/session-review-20261028/` 및 운영 릴리스 감사 JSON에 보존한다. 기존 미추적 파일·stash·다른 worktree는 보존했다.

## 완료한 주요 흐름

| 항목 | 확인된 범위 |
| --- | --- |
| 여행 장부 수입·지출 | Google 수입 읽기 전용, 상단 수입/지출/차액, 표 하단 수입 합계, 중복 지출 헤더 제거. 불일치/미검증 검색에서도 전체/검색 지출을 구별하고 미검증 수입 금액·차액은 숨긴다. |
| 지출 검토 지연조회 | 닫힌 상세는 조회하지 않음. OTA 최상위 검토는 기본 접힘·펼칠 때 조회·닫힌 동안 polling 중단·재펼침 갱신. 운영 초기 API0건·펼침200 확인. |
| 항공권 이름 검색 | 완전 이름 구성요소 검색, 인증된 평탄화 메일 파싱, 메일 전용 색인, 최초 수신일 기준. 실제 대상 예약1건·여정2편 표시 수락. 당일 카드0건은 미결제나 결제 연결 확정이 아니다. |
| 원승인번호 복수 환불 | 1:N 링크·합계·순액 표시, 공백 정규화와 원결제 중복 보호. 실제 확정2건 패널 수락 근거가 있다. 실제 기장/환급 완료와 구분한다. |
| 일반 UI | 사이드바·스크롤·아이콘 수동 테마·항공권 화면·수입 표시의 코드/표적 검증 및 배포 이력이 있다. 실기기·모든 오류 상태의 포괄 수락을 뜻하지 않는다. |
| 문서 정리 | 시작/상태/운영의 역할을 분리하고 상세 명세는 주제별로 통합했다. 과거 결정·테스트·배포 기록은 [보관함](history/README.md)에 보존했다. |

## 남은 확인과 차단

| 항목 | 현재 근거·다음 경계 |
| --- | --- |
| 카카오 미연결 취소11건 | 모두 원승인번호가 없다. 기존 후보/진단 표시는 배포됐지만 자동 금융 연결로 승격하지 않는다. 원결제 대응을 증명하는 카드사/가맹점 근거가 필요하다. |
| PR #193 이후 실제 수락 | [카카오 금액 추론·환불 표시 PR](https://github.com/6Soo/cost/pull/193)은 이제 검수·병합·배포됐다. 원승인 없는 실제11건의 확정 연결/실제 환급 해결을 의미하지 않는다. 추론 표시와 기장 보류를 보존한다. |
| Agoda 미연결 취소3건 | 원승인번호가 없으며 원문 외화 대조 근거도 부족하다. 기존 연결73건과 구별한다. 임의 상쇄·기장 금지. |
| Agoda 20,532 JPY 등 자동 추론 | 기존 자동 추론 게이트가 있다. 특정 사례의 실패 원인·자동 해결 완료는 보관 근거로 확인되지 않았다. 인증·원문 금액/통화·끝자리·기간·전역 유일성·보류/기장 상태를 읽기 전용으로 진단해야 한다. 날짜 창작·수동확인을 자동화 성공으로 보고하지 않는다. |
| 파라타항공 취소·과거 여행 귀속·항목 팝업 | 진단 코드/표시 보완과 개별 실자료 원인 해결을 구별한다. 사례별 최종 수락 근거가 없으면 미확인으로 둔다. 옛 감사표의 미병합 상태는 현재 PR 상태가 아니다. |
| 실제 기기·200%·오류 상태 수락 | 합성 Chromium·DOM 스모크를 실제 기기/본창 확대 전체 수락으로 확대하지 않는다. 필요한 경로만 추가 확인한다. |
| 메일 수집 창 비노출 | 예약 작업 `pythonw.exe` 전환은 확인됐다. 다음 예약 실행의 무창 동작·수집 성공 수락은 **NOT_RUN**이다. 추가 수집을 실행한 것으로 보고하지 않는다. |

## 보존할 로컬 자료

- `apps-script/CloudMail.gs`: 미추적 클라우드 수집 초안. 배포·활성화 완료가 아니다.
- `docs/superpowers/plans/2026-10-26-cost-open-work-plan.md`: 사용자 기존 미추적 계획. 이번 통합의 원본 목록·새 실행 큐에 넣지 않는다.
- `.local-archive/`의 고객 근거·보호 기준선·복구/배포 스크립트와 기존 stash를 보존한다. Git 문서의 숫자만으로 실자료를 변경하지 않는다.

새 작업 인계에는 변경 범위, 완료 커밋, 실행한 표적 검사, 생략한 검사, 실제 배포 SHA 또는 차단 원인, 다음 명령만 갱신한다. 세션별 상태 문서를 새로 늘리지 않는다.

## 2026-10-27 OTA 자동 배정·사후 교정

- 현재 요청: 색 대비 수정과 여행 자동 배정 후 사용자 교정. 취소·해제는 미배정 검토 집계에서 분리하며 전체 목록/별도 필터에 보존한다.
- 구현: 전체 검증 여행으로 준비 숙박을 계산한다. 기간 포함·겹침 일수·차액·시작일·고정 순서로 최선 후보를 `AUTO_INFERRED` 표시하고 근거·확신·준비 숙박 간격을 표시한다. 이용기간 누락·충돌·취소·사용자 해제를 자동 배정하지 않는다. 수동 교정은 별도 근거/기간 밖 확인과 기존 owner·CSRF·revision·기기장 보호를 거친다.
- 검증: OTA 목록/예약 배정/테마/오염 공급자 검사 38개, 인접 우선 배정·예약 분류 8개, 목록 브라우저 2개(390/1440 및 긴 이름) 통과. 브라우저 초기 비동기 적재를 기다리도록 검사 수정. 실제 테마 전환 안내문 대비 4.5:1 이상. 전체 회귀는 단일 OTA 화면·파생 색인 범위이므로 생략했다.
- 운영 실측: 전체 2,271건·자동 추론896건·미배정170건(후보 없음73·기간 없음88·기간 충돌9)·취소/해제 제외974건. 기존 색인 비교에서 준비 숙박45건을 추가 배정하며 기존 기간 충돌9건은 보류한다. 운영 색인 ready, 실제 테마 전환, 수정 화면의 여행62개·현재 선택1개·근거 입력·다른 여행 접힘을 확인했다. 실자료 배정 저장/해제·금융/원본/Google 쓰기·대량 재분류는 실행하지 않았다.
- 완료: 코드 `55f57bb96ba02cea7ab193c03b8449a3cc379e6c`, PR #195 병합/배포 `a56b53da170b8e7ae8bf20f8899199c2b8cf8c18`. 요구사항별 색 대비·자동 배정/집계·사후 교정은 COMPLETE. 근거는 `.local-archive/ota-auto-trip-20261027/`의 `projection.json`, `browser-smoke.json`, `protection-before/after.json`, 배포 스크립트에 보존한다. 다음 명령은 필요 시 `gh pr view 195`와 `aside repl`의 `/ota` 읽기 전용 확인이며 추가 DB 쓰기는 없다. 기존 미추적 파일·별도 PR #193은 포함하지 않았다.

### 2026-10-28 병렬 감독 후속 병합·배포 갱신

- 장부 자산 추출 PR #262는 main/운영 `4e53776`으로 배포했다. 984 blobs 일치·실행SHA·단일 listener·health/ready·보호API·13표 불변·배포본 import 해시 확인. 운영 HTML Aside 확인만 CDP DOM.enable timeout으로 미수락이며 전체 RF-201/202나 실기기 수락 완료가 아니다.
- 저장소 읽기 추출 PR #263은 main `949e3ed`에 병합했다. 최종 교정본9+21 passed, Supervisor 수입/카드·환불기장·서버저장소격리10 passed. 읽기17메서드 외130메서드 AST 불변·SQL 고유 literal 동일. 운영 배포는 다음 통합 릴리스에 대기한다. 작업자는 SCHEMA_SQL/기존 ensure 함수의 동작보존 분리를 별도 커밋으로 구현 중이며 새 마이그레이션을 만들지 않는다.
- real_review_ui 정적 문서 추출 `c023e37`은 Supervisor가 공개 기준의 템플릿51,876B와 render/escape 함수 AST가 정확히 동일함을 확인했다. 작업자5+기존소비38 passed, Supervisor guidance16 passed. PR/배포 전이다. 카탈로그 자산 `6d73793`과 카드 쿼리/OTA 표시 투영 `8c5d263`/`053f0cb`는 반환됐고 검수/통합 대기, RF-102 보드 교정은 진행 중이다.
- PEND-04 백필은 독립 실행 중이며 운영 원문 적재·작업 전환은 아직 하지 않았다. 위임 결과의 보고 SHA·문자/byte 수는 실제 Git/파일에서 확인한 값으로 기록한다. 테스트·병합·배포·브라우저 미실행을 서로 구별한다.

### 현재 승인 전체 ID와 후속 경계 (작업 지속 등록 정본)

이 목록은 최신 사용자 리팩토링 병렬 실구현 지시와 기존 PEND 승인만 포함한다. 과거 ALL 완료 작업과 별도 SPEC_ONLY 보험·여행 항공권·지출 상태 필터 신규 기능을 재개하지 않는다. 등록 runId는 `e0197439-1c34-4348-a14d-7a870c3d69b5`, 실제 Supervisor agentId는 `cb52e22c-33e9-4087-9084-be9a5b74caf5`이며 현재 경로는 `C:/AX/cost`다. 세부 완료/부분 완료 근거는 위 기존 절과 마스터를 재사용한다.

| 승인 ID | 전체 요구 상태 / 다음 경계 |
| --- | --- |
| PEND-01 | BLOCKED_EXTERNAL_DATA. 대응 원결제 원본/명시 결제 증명 부재; 기존 진단 완료, 금융 연결을 창작하지 않는다. |
| PEND-02, PEND-03 | COMPLETE. 기존 UI 확대/오류 수락과 클라우드 수집·가져오기 코드 검증/수집기 배포 근거 유지. |
| PEND-04 | RUNNING. 전체 백필 후 백업/복원·단일 작성자·원문 적재/반복 불변·worker·예약 수집·전달 수락과 직접 Gmail 작업 전환. |
| RF-001, RF-003, RF-004, RF-005 | PARTIAL. 기존 호출/자료/테스트/운영 지도와 guard를 재사용하고 남은 실제 호출·소비자·환경 기준선·단일 배포 진입점 경계를 확인한다. RF-004 영향 매핑은 후속 추출마다 보완한다. |
| RF-002 | PARTIAL. 거래/OTA DTO·읽기 계약 기반은 배포 완료; 전체 상태 계약의 실제 소비/동등성 채택은 남아 있다. |
| RF-101 | RUNNING. 읽기17메서드 분리 병합, 기존 schema/ensure 추출599204d 반환 확인 대상. 저장·감사·revision 책임 전체 분해 완료가 아니다. |
| RF-102 | RUNNING. fallback·문구·선조회 교정7849b7b와11검사 반환; Supervisor 통합/권한 경계 확인 대기. HTTP 런타임 전체 분리 완료가 아니다. |
| RF-103, RF-104 | RUNNING. 카드 표시·읽기 쿼리·OTA 표시 투영 결과 반환/검수 중. 기존 중앙 대사/예약 그룹/성능 수락을 재구현하지 않는다. |
| RF-105, RF-106, RF-107, RF-108, RF-109 | PARTIAL/PENDING. 기존 환불·예약·외부 소스·DB·도구 카탈로그의 완료 근거를 대조하고 남은 실제 책임 경계/중복을 기능별로 분리한다. 실제 DB 마이그레이션/금융 확정은 별도 승인 경계다. |
| RF-201, RF-203 | RUNNING. 장부 CSS/JS는4e53776 배포, 검토 문서PR #265/카탈로그PR #266 병합. 공통 토큰/폼 전체 채택 완료와 구별한다. |
| RF-202, RF-204, RF-205 | PARTIAL/PENDING. 기존 shell·단일 테마·OTA 정보 구조·반응형 수락 재사용, 새 추출이 실제 영향을 주는 화면·접근성 경계만 검증한다. 실제기기 포괄 수락은 미실행이다. |
| RF-301, RF-302, RF-303, RF-304 | PARTIAL/PENDING. 환경/의존·관측·자동 게이트·문서 진입점의 기존 구현을 대조하고 남은 실제 중복/누락만 처리한다. 신규 유료 CI/인프라·계약은 자동 승인하지 않는다. |

전체 RF ID는 해당 세부 수락 기준이 충족되기 전 COMPLETE로 승격하지 않는다. 코드 추출 한 묶음의 병합/배포를 저장소 전면 완료로 확대하지 않는다. 현재 child4개를 재사용하며 새 작업자 생성은 하지 않는다. provider stream 중단 같은 로컬 실행 오류는 외부 자료 차단과 구별하고 보존된 실제 커밋/검사부터 복구한다.
