# 현재 상태

## 2026-11-10 장부 이용일 경고 근본 원인 수정·성능 회복 — 현재 정본

- **운영:** Board·Worker는 `9ad0a454ae323cb6ee61c2a4827dca3bf34caa15`(아래 PR과 다른 세션의 UI 1차 #779 포함)로 공식 단일 코드 배포됐다. 이번 작업의 배포 순서: 2ef58a92 → 4151d805 → 7334f1ae → cee973fb → 086acc67 → 094e52c9 → f5758929 → 9ad0a454(이전 검증 복구점 f5758929). 9ad0a454는 다른 세션(UI/UX)과 조율해 이 세션이 단일 작성자로 배포했다. 각 배포: tracked blob mismatch0, health/ready200, 보호 API401, 보호13표 전후 불변, `worker_switched=true`. 근거: `D:/WebLedgerHost/releases/deploy-evidence-<SHA>.json`, `continuous-switch-<SHA>.json`, 비공개 `.local-archive/service-date-row-audit-20261109/deploy-<SHA8>/`.
- **병합 PR(모두 독립 `codex/gpt-6.1-sol`·`medium` 최종 SHA APPROVE, 호스팅 CI는 결제 한도로 미시작=NOT_GREEN, 2026-11-07 예외):**
  - [#772](https://github.com/6Soo/cost/pull/772) 장부 이용일 인덱스를 스냅숏 세대당 1회 계산(운영 규모 257.6s→약 8s, 결과 동일 325쌍).
  - [#774](https://github.com/6Soo/cost/pull/774) 렌더당 `board_rows` 1회 스캔(`display_tab_id` 무인덱스로 탭 55개 각각 전체 스캔하던 1.2s→0.04s), 커밋된 부분환불 분석을 변경(total_changes/data_version) 전까지 재사용(페이지당 0.68s). 운영 실측: 여행 장부 3.5–9s(잠금 대기 p50 1.2s·p95 52s) → **약 1s**(p50 0.003ms·p95 0.2s). 영향 QA 483 passed/10 failed — 10건(`test_card_flow_browser.py` 9, `test_read_scope_and_probe.py::test_store_lock_wait_is_recorded_for_real_http_request` 1)은 **기준 main에서 동일 재현되는 기존 실패**로 별도 과제.
  - [#775](https://github.com/6Soo/cost/pull/775) ① OTA 재계산(5–9분, 잦은 `SOURCE_CHANGED_DURING_RECONCILIATION` 실패) 동안 장부 OTA 이용일이 전부 사라지던 결함 → 마지막 완결 세대를 화면 표시용으로 유지(쓰기·연결 경로는 계속 fresh 요구). ② 여행 기간 안의 직접 가맹점 숙박·렌터카 카드 결제는 `MM.DD 현장 결제`로 카드 이용일 기준임을 표시(예약·PG·국내 여행사·마켓·ARS 채널 제외, 숙박 일수 추론 없음).
  - [#776](https://github.com/6Soo/cost/pull/776) ① 기간 없는 Booking.com 결제 이벤트가 같은 예약번호의 유일한 유효 예약 기간을 표시(낡은 링크·digest 불일치·취소/환불 관측이 하나라도 있으면 보류). ② **어드벤처코리아(skyticket) 736,240원 근본 원인**: 실제 원본 본문이 CRLF라 `합계` 줄 정규식이 금액을 못 읽음 → 줄 끝 정규화(운영 원본 재추출로 금액·출발/귀국일 복구 확인).
  - [#777](https://github.com/6Soo/cost/pull/777) 4월 이후 숙박을 그 전에 예약한 확정 메일 미수집(예: 4월 중순 숙박의 Booking 확정 메일이 1월 초 수신) → 일일 과거 대조에 2025-04-01~2026-04-01 **공급사 발신 메일만** 보충 창 추가. 첫 운영 실행에서 보충 대상이 5,073건(미보유 4,848건, 1건 약 0.76–1.5초)이라 작업 제한 1800초에 걸려 진행분을 모두 잃는 결함을 발견 → [#778](https://github.com/6Soo/cost/pull/778) 200건 묶음 원자 저장·강제 종료 임시 파일 정리. 이후 매시간 실행마다 이어 받아 2026-11-10 06:29 KST에 완료(`history-reconciliation.json`: `supplier_after 2025-04-01`, 대조 9,259건, 마지막 실행 848건 추가, 통합 저장소 가져오기 완료). 이후 정상 실행은 미보유분만 받으므로 3–4분에 끝난다.
  - [#782](https://github.com/6Soo/cost/pull/782) 재기동 직후 완결 세대가 없을 때 메일 보충 등으로 입력이 바뀌면 재계산 결과를 매번 버려 장부 이용일이 장시간 비던 결함(경고 222→377) → 첫 세대만 입력이 바뀌어도 메모리에 표시용으로 게시(fresh 아님·디스크/콜백 게시 없음·즉시 재계산). 운영에서 `refresh_done … outdated_by` 확인.
  - [#780](https://github.com/6Soo/cost/pull/780) 이용일 근거가 없는 환불·취소(음수) 행은 경고 대신 `취소·환불`로 표시(이미 날짜가 있는 행·양수 행·내보내기/Google 복사 경로 영향 없음).
- **장부 교정(인증 UI 저장, 수동 교정 이력 보존):** 어드벤처코리아 카드 3행 항목 `여행상품비→항공료`. 전액 환불·취소된 Rakuten 예약 1건은 환불 탭으로 이동(이용일 미표시가 정상).
- **장부 이용일 경고(인증 ego-browser 68여행·2,859행 전수, fresh 스냅숏 기준):** 최초 519 → 440 → 344 → **222**(cee973fb) → **183**(9ad0a454, 2026-11-09T20:4xZ, 숙박비 138·항공료 40·렌터카 5). 보충 완료·OTA 재계산(2026-11-10T02:44Z) 뒤 최종 **182**(숙박비 137·항공료 40·렌터카 5). 보충으로 직접 해소된 행은 1건(Booking은 #776으로 이미 27→12)이며, 나머지는 아래 원인별 잔여다. 재계산 창과 겹친 집계(425)는 원인①의 증상이었다.
- **남은 경고 원인(코드로 단정 불가·수집 공백):** Agoda 35(확정 메일이 이 메일함에 오지 않고 포털 수집은 10/21이 마지막 — 전용 Paseo IAB 수집 필요), Trip 38(같은 금액 카드 2장↔예약 2건 등 카드별 대응 근거 없음·예약 근거 없음), Booking 11(같은 예약번호의 어떤 메일에도 숙박 기간 없음), 나머지 98 중 숲나들e/산림휴양시설 약 20(사전 예약 결제, 이용일 원문 없음), 결제일이 여행 기간 밖인 직접 결제 16, 항공 직접/고투게이트 등 35(예약 확정서 미수집 또는 확정서에 일정 없음), 취소·환불된 skyticket 예약 3건은 날짜 미표시가 정상. 행·예약 식별자는 비공개 `.local-archive/service-date-row-audit-20261109/`에만 둔다.
- **프로세스 점검 결과:** 운영 상시 프로세스는 Board 1(Gateway 8790→8751/8752)·Worker 1(mail-collect 매시 30분 약 1.5–3.5분, review-source·roster·google-authority 감시). OTA 스냅숏 재계산은 Board 안에서 60초마다 입력 지문(원천 약 1.2GB SHA-256 2회)을 계산하고 입력 변경 시 5–9분 재계산한다. 원본 내용 기반 지문은 기존 계약(크기·시각 같아도 내용 변경 감지) 때문에 유지했다. 재기동 직후에는 디스크에 공개 요약만 있어 첫 재계산 완료(약 7–15분)까지 OTA 이용일이 비어 보인다 — 후속 과제.
- **Gateway:** `WebLedger-Gateway` 작업은 `releases/f7ff4ec4…/tools/ledger_gateway.py`를 실행한다. 이후 `ledger_gateway.py` 변경이 없어(diff 0) 동작상 문제는 없으나, 7일 보존 정리에서 이 릴리스 폴더는 실행 중 자산으로 보존해야 한다.
- **운영 장애 1건(복구 완료):** 2026-11-10 04:00–04:06 KST 다른 Claude 세션의 합성 미리보기(`run_synthetic_preview --port 8790`)가 운영 Gateway 포트를 차지하고 운영 Gateway(PID 9964)가 종료돼 공개 장부 인증 요청이 401이었다. 미리보기 프로세스만 종료하고 `WebLedger-Gateway` 작업을 재시작해 복구(Gateway PID 19504, 인증 장부 200). 해당 세션에 운영 포트(8790/8751/8752) 사용 금지를 전달했고 확인 답신을 받았다. healthz는 미리보기도 200이라 인증 GET으로 확인해야 한다.
- **미검증/후속:** 재기동 직후 OTA 이용일 공백, 재계산 실패 원인 입력 성분 미확정, 기존 실패 테스트 10건, 실기기·스크린리더.

## 2026-11-09 작업공간 통합 정리 — 당시 정본(최신은 위 2026-11-10 절)

- **코드 기준:** `origin/main`은 [PR #763](https://github.com/6Soo/cost/pull/763) 병합 `00499a52`(코드 트리는 검수 SHA `2723125a`와 동일)다. 작성 시점(2026-11-09 오후)에 열린 PR은 이 정리 PR([#764](https://github.com/6Soo/cost/pull/764))과 다른 담당의 코드 PR [#765](https://github.com/6Soo/cost/pull/765)(skyticket 해외 구매 메일·항공료 일수)뿐이다. 호스팅 CI는 결제 한도로 시작되지 못해 녹색이 아니며, 2026-11-07 승인 예외(`sol medium` 이상의 최종 SHA 독립 검수)로 병합했다.
- **운영 기준:** Board task는 `d67a1312d6e592648db0ed6ea95e49ff5aa9d053`(PR #764 병합, #763 코드 포함)로 단일 코드 배포됐다(이전 `c202fe6e`). 1,459 blobs mismatch0·health/ready200·보호 API401·보호13표 불변. 상세는 [운영 기록](operations.md) 맨 위 절이다. 아래 11월 9일 절의 배포 전 표현은 당시 상태다.
- **정리 결과:** 병합 완료된 로컬·원격 브랜치와 임시 worktree 6곳(`cost-copy-docs`, `cost-copy-qa`, `cost-release-date`, Paseo 2곳, 기준선 사본), 오래된 stash 7개를 제거했다. 미커밋 변경·미추적 스크립트·stash 내용은 삭제하지 않고 비공개 `C:/AX/cost/.local-archive/cleanup-20261109/`에 patch·zip·목록으로 보관했다(복원 방법: patch는 `git apply`, 미추적은 zip/폴더 복사).
- **보존한 미병합 작업(병합 승인 아님):** (1) `fix/flight-passenger-names-20261108`(원격 유지, 11커밋): 항공 탑승객 한글 표기·공유 숙박 기간 근거·카드 레거시 날짜 등. 이 중 `5e14e8d2`는 main에 이미 반영됐고 나머지는 오래된 기준(`91dbc581`)에서 갈라져 main 변경과 겹치므로 영향 QA 없이 병합하지 않는다. (2) `fix/mobile-income-single-line-20261109`(로컬 전용, 1커밋): 모바일 수입 연결 상태 한 줄 CSS와 worktree의 미커밋 CSS/테스트 변경(patch 보관). 두 브랜치는 `unmerged-branches.bundle`로도 보관했다. 둘 다 별도 검증된 PR로만 병합한다.
- **진행 중인 별도 작업:** 이용일 경고 402행 개별 조사·어드벤처코리아 항공료 표시는 다른 담당이 `C:/AX/cost`에서 계속 진행한다. 그 작업의 미커밋 코드 변경은 이번 정리 대상에서 제외했고 `fix/ota-rental-source-period-20261109` 로컬 브랜치도 그 작업이 쓰므로 삭제하지 않았다.
- **여전히 미검증:** 인증 운영 화면(`AUTH_UI_BLOCKED`)의 카드 진입 성능·복사 붙여넣기·68장부 이용일 경고 감소, 실기기/Safari/스크린리더. 완료로 보고하지 않는다.
- **문서 구조:** 이 문서와 [운영 기록](operations.md)에는 2026-11-08 이후 절과 운영 절차만 남겼다. 2026-11-07 이전 인계는 [이전 인계](history/session_handoff-through-20261107.md), 운영 기록은 [운영 기록 10/28~11/07](history/operations-20261028-20261107.md)과 [10/27까지](history/operations-through-20261027.md)에 원문 그대로 있다. 과거 ACTIVE/READY/대기 표시는 새 개발 과제가 아니다.
## 2026-11-09 이용일 근본 원인 수정 배포 / 원문 개별 조사는 계속

- 최신 실행 지시: **단순 연결에 그치지 않고 원문 조사에서 근본 원인을 찾을 때마다 코드 수정·회귀 검증**. 전체 402행의 개별 원문 조사·교정은 진행 중이다. 아래 과거의 `조사 완료`·Draft·미배포 설명은 당시 상태이며 현재 전체 완료 근거가 아니다.
- [PR #762](https://github.com/6Soo/cost/pull/762), 검수 코드 `7a2b126a063d8032bcba18b5d9b60bc7636ae866`, 운영 `c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a`. 항공 확정서 일정이 결제 문맥에 전달되지 않던 결함, 일반 예약 파서에 가려진 명시 완료 환불, 예약번호 공란인 기존 카드의 검증된 항공 날짜 표시를 수정했다. 환불 처리 중·예정·부정·요청 표현의 잘못된 완료 판정도 독립 검토에서 재현·수정했다.
- 최종 영향 QA **697 passed +47 subtests, skip0, compile PASS**. 독립 최종 SHA 검수 **210 passed / APPROVE**, 추가 부정11·완료5 파이프라인 PASS. Paseo runtimeInfo로 검수자의 `codex/gpt-6.1-sol`·`medium` 확인. 호스팅 run42555491219/job128960134984는 Billing/spending limit·steps0 시작 불가였으며 CI 녹색이 아니다. 기존 2026-11-07 승인 예외와 정확 SHA/로컬 QA로 병합했다.
- 공식 단일 코드 배포: 1,454 blobs mismatch0, task/process/runtime SHA 일치, Gateway8790→loopback8751·listener1·health/ready200·보호 API401·보호13표 전후 불변. 이전 검증 운영 d96f0880 복구점 보존. 기존 #759/#761 병합 코드도 이 배포에 포함됐다. 금융/Google/원문/여행 배정 쓰기·마이그레이션·대량 재처리0.
- 실제 보존 원문을 배포 릴리스의 호스트 Python으로 재추출해 항공 일정·완료 환불의 금액/일정 복구 확인. PC1440/모바일390 합성 before/after 날짜 표시·넘침0, 독립 코드/화면 검수. **인증 운영 68장부의 경고 감소·전체 402행 해소·실기기/스크린리더는 미검증**이며 완료로 보고하지 않는다.
- 다음 개별 원문에서 렌터카의 새 제목·통화 접두 선결제액·인수/반납일 추출 누락을 재현해 별도 코드 수정 중이다. `parser16`에서 유일한 정수 KRW 온라인 선결제액만 읽고 실패·미완료·예정은 결제 완료로 승격하지 않는다. 렌터카 기간을 박수 대신 인수·반납일로 표시한다.
- 라쿠텐은 인증 예약 확인서의 예약 ID와 공급자 예약 번호를 구분하고 기간·예약일·할인 후 예약금액·카드 끝자리를 보존한다. 공급자·예약일·원금액·끝자리가 일치하면 읽기 전용 기간 추론에만 사용한다. `paid_on=None`·`payment_event_id=None`·`RESERVATION_ONLY`, 수수료 포함 KRW 청구액의 금융 비교 계약 유지. 공급자 목록 누락과 일반 결제 확정 UI의 오표시도 수정 중이다. 실제 보존 원문의 두 사례 재추출 PASS·금융 쓰기0. 이 후속은 아직 최종 SHA 검수·병합·배포 전이다.
- 최신 상세 체크포인트는 비공개 `.local-archive/service-date-row-audit-20261109/individual-investigation-checkpoint.md`; 고객 원문·식별자는 Git/PR에 포함하지 않는다. 기존 ego-browser TaskSpace10이 없어 실시간 브라우저 재개는 사용자 응답 대기이며 저장된 원문 조사와 코드 수정은 계속한다.
- 배포 근거: `D:/WebLedgerHost/releases/deploy-evidence-c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a.json`, 비공개 `deploy-flight-refund-c202fe6edd4841b94e4dcc5ba20d6064c39e6d4a/`. 문서만의 후속으로 재배포하지 않는다.

## 2026-11-09 여행 장부 이용일 경고 — 초기 조사·Draft 당시 기록

- 최신 요청 `이용일 확인필요라고 떠있는건들 조사`의 대상은 카드 목록 날짜 경고가 아닌 여행 장부다. 인증 ego-browser GET으로 여행68개·지출2860행을 전수 확인해 숙박비353행/항공료49행 경고를 조사했다. [원인별 집계·수정·검증 한계](specs/ledger-service-date-investigation-20261109.md).
- [Draft PR #759](https://github.com/6Soo/cost/pull/759), 코드 SHA `221849f10f80b24e482a58cf2cfa8902ad56c2c2`: M:N 동일 이용기간과 항목 메타데이터 누락의 표시 보완. 표적71pass·독립64pass/정확SHA 코드APPROVE·합성1440/390/320 전후 넘침0. 금융·원본·예약 연결·여행 배정·Google 쓰기 없음.
- **필수 영향 QA245pass/1fail·skip0·compilePASS**. 기존 `test_toyoko_reconciliation.py`85행이 호환 링크 화면에 예약번호를 기대하며 기준 모듈에서도 실패한다. 테스트 제외나 범위 밖 수정 없음. 실제 실패에 CI 인프라 예외를 적용하지 않았으며 병합·배포·재시작 미실행이다.
- 보관 worker 입력 기준73행은 표시 보완 후보(새 경로71행 추가)지만 운영 snapshot과 세대가 달라 운영 해결 건수로 주장하지 않는다. 나머지 원인과 항공료49행도 개별 조사 기록에 보존했다. 운영은 조사 당시 `d96f08809b8201238e8399d053140ab20e3a91fc`이며 이전 카드 날짜0건 보고는 이 요구의 완료 근거가 아니다.
- 정확한 재개점: 비공개 `C:/AX/cost/.local-archive/service-date-investigation-20261109/CHECKPOINT.md`. 기존 검사 실패 별도 처리→필수 영향QA→최종SHA검수/정상병합→공식 단일배포→같은68장부 실제감소 수락이 남았다. 배포 보호 경계 유지.

## 2026-11-09 산림치유원 NICE 메일 — 운영 수집 전환·누락 원문 복구 완료

- [PR #752](https://github.com/6Soo/cost/pull/752)의 수집·파서 수정은 통합 운영 SHA `d96f08809b8201238e8399d053140ab20e3a91fc`에 포함되어 있다. 제품 검수 HEAD `d337121f45335a3fdd1486afb97e7ad53ba1d1d8` 영향 QA411 passed·skip0·compile PASS·필수 브라우저1/1, 독립 gpt-6.1-sol/medium 승인 근거를 유지한다. CI는 결제/사용 한도의 steps0 차단으로 녹색이 아니었다.
- 통합 배포와 최종 보호13표 구간 종료·잠금 해제 통지를 받은 뒤 전용 자료 복구 구간을 실행했다. 기존 hourly 수집의 정상 종료를 기다려 MailCollect working directory를 구43907dd에서 d96 고정 릴리스로 전환했다. 실행파일·인자·인증 파일을 보존했고 작업은 Enabled/Ready로 복구했다.
- 인증 Gmail API로 정확30개 ID 집합과 원본 payload digest30/30을 재검증했다. OTA 백업과 별도 복원본의 내용/무결성 동등성을 확인한 뒤 기존 원문을 덮어쓰지 않고 **누락30건을 원자 추가**했다. 기존 원문/원본 blob/원본 entry 행 해시 보존, 반복 import 쓰기0, 수집 watermark 불변, 금융 보호13표 불변 PASS. 금융 원행·수동 결정·환급 확정·Google 최종 장부 쓰기는 하지 않았다.
- 실제 운영 d96 모듈로 읽기 수락: 복구 원문30/30 존재·이벤트30개·0원 오인식0, 대상 7월 결제11건 중 취소 안내6건을 대조해 잔여5건 확인. 은행 환급 완료나 예약 유지 확정으로 승격하지 않는다. Gateway health/ready200·보호 API401 확인, 서버 재배포/재시작은 하지 않았다.
- **최신 사용자 지시: 숙박일 추가 질문 없이 지리적으로 가까운 기존 여행에 배정한다.** 진안고원산림치유원은 전북 진안/호남권이므로 해당 7월 거래는 기존 `1115_호남` 여행에 귀속 완료다. 운영 읽기 검사에서 원결제·취소가 같은 여행에 code_inference/classified로 귀속되고 미배정0임을 확인했다. 이미 올바른 귀속이라 금융·수동 이력을 다시 쓰지 않았다. 과거 숙박일을 필수 사용자 사실로 둔 차단은 철회하며 여행 귀속을 미완료로 되돌리지 않는다. 실제 이용일이나 예약 유지를 창작하지 않는다. 인증 고객 화면의 독립 시각 수락은 미실행이며 이 귀속 확인과 구분한다.
- 비공개 실제 근거는 `C:/AX/cost/.local-archive/forest-receipts-20261108/`의 source-recovery-evidence.json, post-recovery-acceptance.json, mail-task-release-evidence.json과 checkpoint.md다. 백업/별도 복원본은 `D:/WebLedgerHost/data/backups/forest-mail-20261108T201146Z/`에 보존했다. 아래 이전 복구 대기 문구는 실행 전 역사 기록이며 현재 복구 상태가 아니다. 이 문서 전용 후속은 재배포하지 않는다.

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

## 2026-11-09 산림치유원 NICE 메일 — 코드 병합 완료 / 운영 복구 대기

- 사용자 요청은 메일 조사에서 발견한 문제 전체 해결이다. [PR #752](https://github.com/6Soo/cost/pull/752), 검수 SHA `d337121f45335a3fdd1486afb97e7ad53ba1d1d8`, 정상 main 병합 `25d41ff933a35fc42122e2d4da6264a6a6f4a45f`(동일 tree). Windows/CloudMail 검색의 산림치유원 누락, NICE 취소금액·취소요청일시 파싱을 교정하고 수수료와 결제금액 구분 및 과거 forest-only 복구 경로를 검증했다. 금융 원행·수동 결정·환급 확정·Google 최종 장부는 변경하지 않았다.
- 정확 검수 SHA의 영향 QA **411 passed, skip0, compile PASS, 필수 브라우저1/1**. 독립 실제 `gpt-6.1-sol / medium`은 제품 HIGH/MEDIUM 결함 없음·CI 예외 병합 승인을 기록했다. CI42492278382/job128767045020은 billing/spending-limit으로 steps0에서 차단됐으며 녹색 CI가 아니다.
- 대상 누락 원문30건은 인증 Gmail 읽기와 정확 ID 집합·원본 payload digest 재열람30/30으로 확인했다. 보관소 추가 복구·운영 배포·예약 작업 변경은 **미실행**이다. 과거 `pg_mail_index.json`은 운영 입력이 아니며 고객 자료를 Git에서 수작업으로 덮어쓰지 않는다.
- 실제 운영 Windows Job/mutex 감독기 정식 통합과 단일 배포 순서를 조정 중이다. 기존 기동 보호를 제거하거나 구 배포 경로로 우회하지 않는다. 통합 코드 배포의 보호13표 전후 확인 종료 후 MailCollect의 구버전 working directory를 검증 릴리스로 고정한다. 그 뒤 별도 자료 복구 보호 구간에서 OTA 백업·별도 복원 동등성·단일 작성자·기존 원문 불변·반복0쓰기·watermark 불변을 확인해30건만 추가한다.
- 실제 숙박일은 보관자료와 별도 예약메일 검색에서 근거를 찾지 못해 사용자에게 필수 사실을 질문한 상태다. 결제일/주문번호를 숙박일/예약번호로 만들지 않는다. 코드 병합을 실자료 복구·은행 환급·예약 유지·이용일 확정 완료로 보고하지 않는다.
- 비공개 인계: `C:/AX/cost/.local-archive/forest-receipts-20261108/checkpoint.md`에 QA/JUnit·독립 검수·원본 동등성 manifest·복구/사후 수락 명령을 보존했다. 임시 작업공간은 후속 운영 복구에 사용 중이며 루트의 다른 작업·미추적 파일은 보존했다. 이 상태 기록은 문서 전용이며 재배포하지 않는다.

## 2026-11-08 여행 지출 복사 포커스 오류 복구 — 당시 운영 배포 / 후속 복사 수락으로 대체 예정

- [PR #749](https://github.com/6Soo/cost/pull/749) 운영 SHA `068de5da50611255dd4ef23d12f2a8272fe4b616`, 검수 코드 `4cc5ac3699948c828885fd46d84597e842618a71`와 webapp/tests tree 동일. 이전 운영 SHA `e1c60ad037eb6651d68058ea90ac57327e64ce20`. 아래 #744의 포커스 복원만으로 해결되지 않던 `Document is not focused` 오류에 대한 후속이다.
- 두 클립보드 API가 모두 거부해도 전체 TSV를 선택된 읽기 전용 입력에 남기고 직접 복사하거나 새 클릭으로 재시도할 수 있다. 재시도는 서버 재조회 없이 준비된 내용을 사용하고 성공 여부를 실제 결과대로 표시한다. 제외된 거래의 일자·가맹점·금액·상세 링크도 같은 최신 GET 응답에서 갱신한다. Google 대조·복사 대상 규칙, API 계약과 금융 처리는 변경하지 않았다.
- 정확한 코드 SHA의 영향 QA **305 passed +69 subtests, skip0, 필수 browser22/22, compile PASS**. TSV 경계 추가10건 통과. 실제 독립 `gpt-6.1-sol / medium` 최종 APPROVE 및 HIGH/MEDIUM 없음. CI run42473632476/job128709986234는 결제/사용한도 annotation·steps0 시작 차단으로 녹색이 아니며 2026-11-07 사용자 승인 예외를 적용했다.
- 합성 ego1440/390/320 동일 크기 전후·실제 운영 테마 초기화와 두 테마·키보드·페이지 넘침0 확인. 두 API 강제 거부 뒤 선택 텍스트 보존, 새 클릭 재시도 뒤 native Ctrl+V 내용 일치, TSV GET1회·POST0 확인. 실제 측정 안내문 대비 light7.5777/dark5.7053 이상. 초기 테마 적용이 잘못된 캡처는 근거에서 제외하고 재생성했다.
- 공식 보호 배포 증거: 1,447 tracked blobs mismatch0, runtime SHA verified, listener1·backend8752, health/ready200·보호 API3개401, 보호13표 전후 불변, financial_apply NOT_RUN. 완료 시각 2026-11-08 23:04 KST. 코드 전용 배포로 원본/금융/Google 쓰기·재처리·마이그레이션 없음. 중단 후 증거를 확인했으므로 재배포하지 않았다.
- **AUTH_UI_BLOCKED:** 재개 시 이전 인증 TaskSpace18이 `task space not found: 18`로 없어 운영 화면의 최종 복사→native 붙여넣기 해시 비교와 운영1440/390 캡처는 실행하지 못했다. 위 합성 검증을 인증 운영 수락으로 대체하지 않는다. 실기기/Safari·스크린리더 음성·실제200%확대·RTL도 미검증이다. 남은 작업은 허가된 인증 ego 세션에서 운영 GET/복사·붙여넣기 일치와 화면 확인이며 코드 재구현·재배포는 필요 없다.
- 근거: `D:/WebLedgerHost/releases/deploy-evidence-068de5da50611255dd4ef23d12f2a8272fe4b616.json`, 비공개 `.local-archive/expense-copy-actionable-20261108/`의 deploy-evidence/release-audit/quality-final/junit-final/deploy-review 및 ego 결과. 고객 원문은 추적 문서에 포함하지 않는다. 후속 문서 전용 변경은 코드 검사·배포·서버 재시작을 반복하지 않는다.

## 2026-11-08 수집 현황·빈 기간 업로드 UX — 운영 완료

- 최신 요청 “제발 의도에맞게 UX UI 좀 신경쓰라고”의 대상은 카드 수집 기간 확인→빈 기간 자료 업로드 흐름이다. 빈 기간이 있는 카드사를 먼저 보여주고 날짜 옆에 `이 기간 업로드`를 배치했다. 네 개 집계 타일·반복 계산 설명을 없애고 카드사별 기간을 짧은 목록으로, 업로드 파일은 모든 기간 요약 아래 한곳의 접힌 목록으로 정리했다. 파일 처리 결과 접근은 유지한다.
- [PR #747](https://github.com/6Soo/cost/pull/747), 운영 SHA `e1c60ad037eb6651d68058ea90ac57327e64ce20`, 검증 코드 `e905a0d6a8324f048ce249197e447e65113d15e8`와 tree 동일. 영향 검사 **238 passed +70 subtests·skip0·browser20/20·compile PASS**, 실제 독립 `gpt-6.1-sol / medium` 정확한 운영 SHA 코드·interface-review APPROVE. CI run42469738253은 결제/사용한도 steps0 시작 실패로 녹색이 아니며 기존2026-11-07 승인 예외를 적용했다.
- 합성 예외 상태 및 **인증 운영 화면** 전후1440/390, 운영1440/390/320·두 테마·파일23개 접힘/키보드 펼침·Enter 업로드의 기간 맥락/파일 입력 포커스·넘침0 PASS. 운영 GET200·카드사3/파일23/공백1 및 기간/공백 projection SHA-256이 배포 전후 동일하다. 실측 라벨 대비17.0629/9.8968, 업로드5.3097/7.6095. 고객 원문과 화면은 비공개 증거에만 보존한다.
- 공식 단일 코드 전용 배포:1,446 blobs mismatch0·task/process/runtime SHA 일치·Gateway8790→loopback8751·health/ready200·보호 API401·보호13표 불변·financial_apply NOT_RUN. 단일 작성자 잠금을 기다린 뒤 정상 전환했다. 원본/금융/Google 쓰기·실제 업로드 POST·재처리·스키마 변경 없음. 이전 검증 릴리스/task XML을 복구점으로 보존했다.
- 호스트 `D:/WebLedgerHost/releases/deploy-evidence-e1c60ad037eb6651d68058ea90ac57327e64ce20.json`, 비공개 `.local-archive/coverage-intent-ux-20261108/`의 QA·리뷰·ego-final·production-after·보호 snapshot이 근거다. 남은 필수 작업 없음. 실기기/Safari·스크린리더 음성·실제 브라우저200%확대·RTL은 미검증이다. 후속 문서만으로 검사·배포·재시작을 반복하지 않는다.

## 2026-11-08 파일별 기본 조회기간·파일 사이 공백 교정 — 운영 완료

- 최신 사용자 결정: 거래일자는 자료의 조회기간 공백을 메우는 근거다. **한 파일의 최초~최종 거래일 전체**를 기본 조회기간으로 삼고 내부 무거래일은 공백으로 세지 않는다. 같은 카드사의 모든 카드 파일 범위를 합친 뒤 파일 사이 빈 구간만 표시한다. 아래 #742와 과거 거래일별 공백 계산을 이 기준이 대체한다. [현행 계약](specs/card-transaction-date-gaps-20261108.md).
- [PR #745](https://github.com/6Soo/cost/pull/745), 운영 SHA `a0d257c45fef1767d25d5269bbac0007c22e4f2e`, 검증 코드 `20df129ec70f29d2c298cc9179edb7afa2e14580`와 tree 동일. 영향 QA **236 passed +70 subtests, skip0, 필수 browser19/19, compile PASS**. 독립 실제 `gpt-6.1-sol / medium` 정확한 병합 SHA APPROVE. CI는 steps0 결제/사용한도 차단으로 녹색이 아니며 기존 승인 예외를 적용했다.
- ego 합성 전후1440/390/320에서 넘침0, 내부 빈 날짜 제외·파일사이 공백1·같은 카드사 다른 카드 파일로 해소 후0, 빈자료·오류 복구·키보드 포커스·업로드 맥락 확인. 인증 운영 고객 화면·실기기/Safari·스크린리더 음성·실제 브라우저200%확대·RTL은 미검증이다.
- 공식 고정 SHA 배포: 1,445 blobs mismatch0, task/process/runtime SHA 일치, Gateway8790→loopback8752, health/ready200, 영향 coverage API/화면과 보호 API401, 보호13표 전후 불변, `financial_apply=NOT_RUN`. 고객 원본·DB/금융/Google 쓰기·재처리·마이그레이션 없음. 호스트 증거 `D:/WebLedgerHost/releases/deploy-evidence-a0d257c45fef1767d25d5269bbac0007c22e4f2e.json`, 비공개 `.local-archive/card-file-span-20261108/`. 후속 문서 변경은 재배포하지 않는다.

## 2026-11-08 Google 장부 지출내용 복사 대조·클립보드 오류 — 운영 완료

- PR #744 병합·운영 SHA `aa7d6a648118c907421e32234ca3837cc11c42a9`, 이전 실제 runtime `8341f266531a389a406eb8ce6486759366f03e87`. `Google 장부 일치`는 이미 대조된 `MATCHED_MANUAL`/`MATCHED_EXISTING`, `Google 대조 보류`는 `REVIEW_CONFLICT`로 안전한 단일 Google 행을 확정하지 못한 후보다. 보류 사유별 펼침 정보를 추가했고 `NEW_EXPENSE`만 복사한다.
- 클립보드 문서 포커스 오류에 버튼 포커스 복원과 textarea 선택 fallback을 추가했다. 표적 `19 passed·skip0`, health/ready200, 보호 API401, 보호13표 불변, `financial_apply=NOT_RUN`. Google 최종 장부 쓰기와 고객 원본·금융 데이터 변경은 없었다.
- 배포 evidence는 `D:/WebLedgerHost/releases/deploy-evidence-aa7d6a648118c907421e32234ca3837cc11c42a9.json`, 상세 근거는 `.local-archive/google-expense-copy-fix-20261108/`다. impact-checks는 billing/infrastructure steps0으로 녹색이 아니며 이를 성공으로 보고하지 않는다.

## 2026-11-08 카드사별 거래일자 합집합 공백 — 운영 완료

- PR #742 병합·운영 SHA `8341f266531a389a406eb8ce6486759366f03e87`. 같은 카드사의 모든 카드 거래일자를 합집합해 카드사별 조회기간과 공백을 계산한다.
- 커버리지 표적 49 passed·skip0, blob mismatch0, health/ready200, 보호 API401, 보호13표 불변, 금융 적용 미실행. 배포 evidence는 `D:/WebLedgerHost/releases/deploy-evidence-8341f266531a389a406eb8ce6486759366f03e87.json`이다.

## 2026-11-08 여행 장부 독립 메뉴 제거 — 운영 완료

- PR #740 병합·운영 SHA `43f49f91ecdd189c962e094f4bc671e76a72b86f`. 전역 `여행 장부` 메뉴를 제거하고 `여행 관리`에서 여행을 선택하는 구조로 바꿨다. `/board` 기능은 유지한다.
- 표적 42 passed·skip0, 브라우저 2 passed·9 subtests. 공식 배포 evidence는 `D:/WebLedgerHost/releases/deploy-evidence-43f49f91ecdd189c962e094f4bc671e76a72b86f.json`이며 보호13표 불변·health/ready200·보호 API401·금융 적용 미실행이다.

## 2026-11-08 카드 최종 귀속·P3 작업 기능 폐지 — 운영 완료

- PR #737 병합 SHA와 운영 SHA는 `e90c4b6c0e718e0d98da65ed44f5bb29257cc3cd`다. 카드 P3 작업함·분류 대기 UI/답변 경로를 폐지하고 실제 여행 또는 결제일·매입일 기준 기타비용 귀속을 적용했다.
- 121 passed·skip0, compileall/diff-check PASS. 공식 배포는 이전 실제 runtime `d043892777dc50d1e61d3478440f4148719fd39f`에서 전환했으며 blob mismatch0·health/ready200·보호 API401·보호13표 불변·financial_apply NOT_RUN이다. GitHub impact-checks는 steps0 billing 차단으로 녹색이 아니며 승인 예외 근거를 보존했다.
- 배포 증거는 `D:/WebLedgerHost/releases/deploy-evidence-e90c4b6c0e718e0d98da65ed44f5bb29257cc3cd.json` 및 `.local-archive/card-destination-ux-20261108/`에 있다. 고객 원본/Google/금융 쓰기와 스키마 변경은 실행하지 않았다.

## 2026-11-08 카드 최종 귀속·P3 작업 기능 폐지 — IMPLEMENTING

- 최신 사용자 지시: UX/UI 최우선으로 미배정/확인필요/처리필요/미분류와 관련 P3 기능·UI 잔재를 삭제하고 P1/P2 이후 여행 또는 결제일 분기 기타비용으로 종결한다. [단일 실행 정본](specs/card-destination-only-ux-20261108.md).
- 이전 #735 통합은 11월8일04:24 KST 별도 사용자 원문을 수집하지 못해 과거 작업함 유지 계약으로 제거 변경을 제외했다. 코드 배포·보호 검사는 성공했지만 최신 제품 계약 수락은 미완료였다. 이번 변경은 그 요구 누락을 교정한다. 기존 보호13표·원본·수동교정·환불·권한은 유지한다.
- 현재 브랜치 `fix/card-destination-ux-20261108`, 기준 `d6d22a94415da70f83c88d770067775675b79ca9`. 구현·합성 전후·표적/영향 QA·독립 검수·단일 배포를 수행 중이며 아직 완료를 주장하지 않는다.

## 2026-11-08 미커밋 전체 검토·통합 운영 배포 — 기술 배포 COMPLETE / 최신 제품 계약 누락은 위 후속 참조

- 사용자 `미커밋 변경사항까지 모두 검토해서 배포`와 `모두 확인해서 메인으로 병합 운영배포해` 범위. [PR #735](https://github.com/6Soo/cost/pull/735), 검수 HEAD `1ee5c6983f11e59bb1a2b52f3df90f1eab487165`, 운영 SHA `d043892777dc50d1e61d3478440f4148719fd39f`. [28파일 판정·수락 기록](specs/review-all-uncommitted-release-20261108.md). 원래 로컬8커밋의 이력과 미커밋25·미추적3파일을 모두 검토했다. 유효 변경은 통합하고 원본/권한/환불 보호 제거는 제외·보존했다. 영수증 PR733도 같은 SHA로 운영 반영했다.
- 어드벤처코리아 항공료, 여행 관리 단일 집계, 모바일 수입/보험/금액, 실제 OPEN 사용자 작업, 행별 지출 복사, 정상 구매의 유효한 결제 분기 fallback을 반영했다. 조회 실패를 0건으로 숨기지 않고 정상 P1/P2를 사용자 업무로 만들지 않는다. 메일 캐시의 disabled-gate 의존성과 짧은 보험 문구에서 긴 날짜/이름이 겹치는 결함도 수정했다.
- 최종 Windows 영향 QA **1166 passed +133 subtests, skip0, 필수 브라우저 72/72, compile PASS**. 초기6실패와 모바일 겹침 red는 보존했고 최종 고정SHA에서 교정 후 통과했다. 독립 실제 `gpt-6.1-sol / medium` 정확SHA 승인·interface-review Approve. CI42411351988/job128519990700은 결제/사용 한도로 steps0에서 차단돼 기존 승인 예외를 적용했으며 CI 녹색으로 보고하지 않는다.
- 공식 SHA 고정 git archive·tracked blob mismatch0, 단일 배포 lock·PREVIEW/APPLY 완료. 이전 `d97158484d17f974668dafffafdb1a7b462a7249`에서 전환했고 runtime/task/process SHA 일치, loopback backend, health/ready200·보호 API401·보호 테이블13개 불변을 확인했다. 운영 분류/여행 교정·재처리·원본/금융/Google 쓰기·마이그레이션은 실행하지 않았다.
- 인증 GET 수락: 카드·여행·영수증 영향 화면 main/heading 및 coverage API200 확인. 고객 원본 파일 확인 POST는 실행하지 않았다. 합성 1440/390/320 동일크기 전후 및 짧은 보험 stress에서 페이지 넘침0·텍스트 행 침범0, 키보드 포커스와 light7.5777:1/dark5.7053:1 대비 확인. 전체 고객 화면 시각 수락·실제 기기·스크린리더 음성·RTL/OS확대는 미검증이다. 과거 고객 영수증 파일을 복구했다고 주장하지 않는다.
- root main은 보존 stash `484adc3acd41374568e1ac39e4f18d4d0d2a8b60` 생성 후 정상 fast-forward했다. 기존 stash6개와 원본28파일 snapshot은 모두 보존했다. 비공개 근거 `.local-archive/uncommitted-release-20261108/` 및 `.local-archive/all-main-review-20261108/`. 이 후속 기록은 문서 전용이며 재배포하지 않는다.

## 2026-11-08 영수증 업로드 응답 유실 복구 — 통합 운영 반영 COMPLETE

- 사용자 다량 영수증 업로드 경로 조사 후 `수정해` 범위. [수락·검증 기록](specs/receipt-upload-recovery-20261108.md). [PR #733](https://github.com/6Soo/cost/pull/733) 병합 `6ddbc7ef9feb796e444704a87ab7733cde8a8e82`, 검수 HEAD `859e74837fc40a5f2a1bbae9c7ac36060efa569d`와 tree 동일. 사진/PDF 실제 전송 SHA로 저장 결과를 복구하고 본문 유실·Safari 형식 오류·일괄 처리·재시도를 보완했다. 고객의 과거 파일을 실제 복구한 것으로 보고하지 않는다.
- 최종 Windows 영향 **307 passed +32 subtests, skip0, browser37/37, compile PASS**. 실제 Sol medium 최종 SHA APPROVE·독립 Luna medium APPROVE. CI42408750254/job128512087070은 결제/사용 한도로 steps0 차단되어 기존 사용자 승인 예외를 적용했고 녹색으로 보고하지 않는다. 합성 ego390/1440 동일 크기 전후·320/390/1440 넘침0·키보드 직접 입력/미리보기 확인; 고객 업로드·실기기/Safari·스크린리더·200% 실제 확대·다크 테마 미검증.
- **운영 반영 COMPLETE:** PR735 통합 릴리스 `d043892777dc50d1e61d3478440f4148719fd39f`에 포함해 단일 작성자로 배포했다. 통합 QA1166+133·skip0·browser72 및 보호13표 불변·health/ready200·보호API401·인증 `/receipts` GET 화면의 업로드 입력 확인. 고객 과거 파일의 실제 복구/업로드 POST는 실행하지 않았다. 상세는 위 통합 배포 기록이며 영수증만 별도 재배포하지 않는다.

## 2026-11-08 남은 작업공간 4곳 통합·정리

- 사용자 후속 `4곳도 진행해` 범위: root·card-coverage·pr683·pr685의 변경 판정 및 통합/정리. [판정·검증·보존 계약](specs/remaining-workspace-integration-20261108.md). root 수입표는 #723, 카드 대안들은 #713/714/717로 대체됐으며 초기 queue 누락=0 fallback은 최신 오류 계약과 충돌해 제외했다.
- pr683의 유효한 오류 메뉴 문구를 접근성 이름과 통일했다. 첫 영향 검사에서 발견된 PC 사이드바11px 넘침을 해당 문구 전용 줄바꿈으로 수정했다. 제품 SHA `ea80f7d90a3fda526e9f36d16adf725ac27fd29f`: 298개 검사·skip0·필수 브라우저21개 전건실행·compile 통과. 표적14+2subtests 통과. 합성1440/390/320·두테마·키보드 진입/포커스·CSS200%·대비17.06 확인. 실제 운영 UI/물리기기/스크린리더/번역·RTL 미검증.
- 별도 실제 `gpt-6.1-sol / medium` 제품 검수 APPROVE. 문서 후속 최종 SHA별 판정과 병합 상태는 PR 댓글/merge 기록으로 확정한다. CI 인프라 차단 예외는 최신 사용자 승인대로 적용하고 실제 실패를 녹색으로 간주하지 않는다.
- 모든 파일/미추적·무시 파일·Git 이력의 복구 사본 및 SHA256 대조 후 세 임시 worktree를 정리하고 기본 root main 하나를 남기는 범위다. stash6개 보존. 실제 정리 영수증과 최종 SHA는 비공개 `.local-archive/remaining-four-20261108/summary.json`에 기록한다. 아래의 4곳 보존 설명은 이번 통합 전 스냅샷이다.
- 이번 요청의 운영 배포/서버 재시작·DB/원본/금융/Google 쓰기0. 기존 미배포·미검증 수락을 그대로 유지한다.

## 2026-11-08 카드 내역 거래일자 공백 전환

최신 요청과 수락 계약: [거래일자 공백 전환](specs/card-transaction-date-gaps-20261108.md). 조회기간 기반 대시보드를 폐기하고 실제 거래일 사이 공백으로 전환한다. PR #731 병합 및 운영 SHA `d97158484d17f974668dafffafdb1a7b462a7249` 배포 완료. 최종 영향 QA503+100 subtests, skip0/browser35, Sol medium 검수 PASS. health/ready200·보호API401·보호13표 불변. 인증 운영 API·DOM으로23파일/27표시그룹/515공백 및 구 폼0 확인; 전체 고객 화면 시각 수락은 미검증이다. 실제 작업 근거는 운영 기록에 보존하며 문서-only 후속은 재배포하지 않는다. 기존 main의 다른 로컬 커밋8개는 별도 보존한다.
