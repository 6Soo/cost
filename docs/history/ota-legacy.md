# 구형 OTA 정책·실험 기록

**보관 기록 / ARCHIVED.** 아래 내용은 작성 당시 원문이다. 과거 TODO·READY·미구현·배포 SHA는 현재 작업 지시나 운영 상태가 아니다.

[시작 안내](../COST_V3_START_HERE.md) · [현재 상태](../session_handoff.md) · [운영 기록](../operations.md)

## 내용

- [COST 구형 OTA·개발 문서 보관함 (2026-10-23)](#src-docs-archive-ota-legacy-20261023-readme-md)
- [구조](#src-docs-archive-ota-legacy-20261023-architecture-md)
- [자율 개발 체크포인트](#src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md)
- [COST 장시간 자율 구현 실행계획](#src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md)
- [OTA 결제 검토 코어](#src-docs-archive-ota-legacy-20261023-ota-first-core-md)
- [Isolated OTA review pilot 실행 기록](#src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md)
- [OTA 결제 보류 검토 UI](#src-docs-archive-ota-legacy-20261023-ota-first-ui-md)
- [OTA-first verification plan](#src-docs-archive-ota-legacy-20261023-ota-first-verification-plan-md)
- [OTA 매칭 규칙 기본 설정](#src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md)
- [OTA 결제와 카드 거래의 용어와 정확 매칭 기준](#src-docs-archive-ota-legacy-20261023-ota-matching-terms-md)
- [OTA 메일 분류와 대조](#src-docs-archive-ota-legacy-20261023-ota-mail-md)
- [미결 작업과 다음 세션 인계](#src-docs-archive-ota-legacy-20261023-session-handoff-md)
- [이전 자율 실행 체크포인트 — 역사 자료](#src-docs-autonomous-cycle-checkpoint-md)
- [이전 문서 — autonomous-implementation-playbook.md](#src-docs-autonomous-implementation-playbook-md)
- [이전 문서 — ota-first-core.md](#src-docs-ota-first-core-md)
- [이전 문서 — ota-first-isolated-review-pilot.md](#src-docs-ota-first-isolated-review-pilot-md)
- [이전 문서 — ota-first-ui.md](#src-docs-ota-first-ui-md)
- [이전 문서 — ota-first-verification-plan.md](#src-docs-ota-first-verification-plan-md)
- [OTA 기준 대조 구현과 읽기 전용 검증](#src-docs-ota-first-verification-report-md)
- [이전 문서 — ota-matching-rule-defaults.md](#src-docs-ota-matching-rule-defaults-md)
- [이전 문서 — ota-matching-terms.md](#src-docs-ota-matching-terms-md)
- [이전 문서 — ota_mail.md](#src-docs-ota-mail-md)

---

<a id="src-docs-archive-ota-legacy-20261023-readme-md"></a>

## README

통합 전 경로: `docs/archive/ota-legacy-20261023/README.md`

<a id="src-docs-archive-ota-legacy-20261023-readme-md--cost-구형-ota개발-문서-보관함-2026-10-23"></a>
### COST 구형 OTA·개발 문서 보관함 (2026-10-23)

> **이 디렉터리의 모든 파일은 역사 자료입니다. 새 기능의 구현 지시, 최신 비즈니스 규칙, 배포 상태로 사용하지 마세요.** 11개 문서는 기존 텍스트·실행 기록을 보존한 사본입니다. 이동 이후 정상 탐색을 위해 **일부 상대 링크 경로만 수정**했습니다.

<a id="src-docs-archive-ota-legacy-20261023-readme-md--지금-개발할-때-읽을-문서"></a>
#### 지금 개발할 때 읽을 문서

- **단일 현행 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **OTA 매칭·readiness·R0~R6:** [OTA–카드 정책 A](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **여행 추론·사용자 교정·AI 대화·항공권:** [V3 기능 명세](specs-20261110/participants.md#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md)
- **실제 운영 이력:** [operations.md](../operations.md)

<a id="src-docs-archive-ota-legacy-20261023-readme-md--변경하지-않고-보존한-원본-11개"></a>
#### 변경하지 않고 보존한 원본 11개

| 파일 | 당시 내용 | 취급 |
| --- | --- | --- |
| [ota-first-core.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-core-md) | 초기 OTA-first 코어·HOLD 계약 | 구형 설계 |
| [ota-first-isolated-review-pilot.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md) | 10월 9일 격리 파일럿 | 역사 검증 |
| [ota-first-ui.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-ui-md) | 구형 검토 UI 계약 | 구형 설계 |
| [ota-first-verification-plan.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-verification-plan-md) | 10월 8일 실험 계획 | 완료/과거 계획 |
| [ota-matching-terms.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-matching-terms-md) | 결제일 exact gate·날짜 규칙 | 구형 규칙 |
| [ota-matching-rule-defaults.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md) | 업체별 매칭 defaults 제안·계약 | 구형 설계/역사 |
| [ota_mail.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-mail-md) | OTA 메일 조사·검증 진행 기록 | 과거 실행 |
| [autonomous-implementation-playbook.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md) | 예전 구현 작업 지시 | 실행 금지/역사 |
| [autonomous-cycle-checkpoint.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md) | 이전 에이전트 누적 체크포인트 | 실행 금지/역사 |
| [architecture.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-architecture-md) | 구형 패키지/정본 설명 | 구형 구조 |
| [session_handoff.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-session-handoff-md) | 정리 이전 누적 인계 | 과거 이력 |

**원본 보존 확인:** 최초 아카이브 생성 시 11개 원본과 보관본의 Git blob SHA 일치를 검증했습니다. 이후 8개 보관본의 **상대 링크 28곳만 새 위치에 맞춰 교정**했으므로 현재 보관본의 blob SHA는 일부 변경됐습니다. 최초 무변경 원본은 squash 병합 커밋 [f8ccd13](https://github.com/6Soo/cost/commit/f8ccd13aecdbc00b116c52bb8e4b3bb6f94c9a50)의 Git 이력으로 복원할 수 있습니다. 업무 규칙/실행 증거/원본 내용은 재작성하지 않았습니다.

사진 파일 `docs/ota-first-ui-desktop.png`, `docs/ota-first-ui-mobile.png`은 바이너리이고 구형 UI 기록에 부속한 자료이므로 기존 경로에서 유지한다. 현재 구현 요구로 오인하지 않는다.

**링크 점검:** 문서를 옮긴 후 끊어진 상대 링크(운영 기록·AGENTS·OTA 검증 보고서·UI 스크린샷 및 과거 인계)를 현재 경로로 보정했습니다. 보관 문서 내부의 과거 TODO/코드 버전/금액은 최신 상태로 해석하지 않습니다.

---

<a id="src-docs-archive-ota-legacy-20261023-architecture-md"></a>

## architecture

통합 전 경로: `docs/archive/ota-legacy-20261023/architecture.md`

<a id="src-docs-archive-ota-legacy-20261023-architecture-md--구조"></a>
### 구조

<a id="src-docs-archive-ota-legacy-20261023-architecture-md--현재-ota-자료-연결"></a>
#### 현재 OTA 자료 연결

메일·포털·과거 조사 자료는 운영 `ota-sources.json`에 등록해 함께 조회한다. 자료 내용 변경을 감지하고 미연결 사유를 구분하는 수정까지 적용했다. 현재 연결 수와 남은 항목, 실제 검증 범위는 [OTA 문서](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-mail-md)의 최신 항목을 따른다.

Import → Normalize → Classify → Review unresolved → Preview → Commit ledger.

app/의 여덟 Python 파일이 카드 처리의 핵심이며 OTA 메일, 여행 수집과 보류 처리는 같은 패키지의 별도 모듈이 담당한다.

```text
app/
  __init__.py       처리 흐름 연결
  import_card.py    실제 카드 양식과 원본 보존
  normalize.py      날짜와 금액 정규화
  classify.py       규칙과 명확한 업종 적용
  rules.py          재사용 규칙 관리
  review.py         답변과 수정 충돌 검사
  ledger.py         미리보기와 중복 없는 기록
  db.py             저장과 변경 이력
  ota_mail.py       예약 메일 분류와 카드 대조
  ota_portal.py     보존 Agoda 포털 근거의 읽기 전용 대조
  reserve_trips.py  출발 예정 여행 수집
  review_holds.py   취소·환불과 확인 대기 보호
webapp/
  card_flow.py      기존 로그인과 연결한 카드 처리 화면
  ledger_design.py  거래 테이블·모바일 목록·편집 패널
  ledger_board.py   기존 장부 API·수입·배분·출력
  ledger_store.py   장부 정본과 저장 충돌·중복 방지
tests/card_pipeline/
```

운영 DB는 D:/WebLedgerHost/data/board.sqlite 하나다. board_rows가 현재 장부이며 ledger_entries는 최초 기록 영수증이다. 장부 수정은 현재 장부와 수정 이력에 저장한다. 영수증을 별도 수정 가능한 장부로 사용하지 않는다.

카드 처리의 기본 테이블은 import_batches, import_batch_rows, transactions, cost_classification_rules, review_decisions, ledger_entries, change_log, requests다. transaction_review_holds는 취소·환불과 확인 대기를 보호한다. 원본 파일과 거래 내용, 분류 결과와 사용자 답변을 구분한다. 거래와 감사 이력과 장부 반영은 같은 DB 트랜잭션에서 처리한다.

기존 여행 관리, 입금, 로그인, 권한, 출력 기능의 호환 테이블은 유지한다. 운영 DB 전체가 네 테이블로 줄었다고 주장하지 않는다. 과거 검토 답변과 감사 이력은 이 DB에 이관했다. 이전 DB 파일은 복구용으로 보존하며 현재 쓰기 경로로 사용하지 않는다.

파일 fingerprint, stable transaction key, source hash와 기록 여부가 중복 방지의 핵심이다. 별도 shadow, baseline, 전환 gate 없이 처리한다. 명시 일정과 원본 hash 검증은 잘못된 여행 배정을 막기 때문에 유지한다.

AI 호출은 새 카드 처리 흐름에 없다. 규칙과 이전 사용자 결정, 명확한 업종으로 분류하고 나머지를 사람에게 질문한다.

<a id="src-docs-archive-ota-legacy-20261023-architecture-md--현재-실행과-중복-방지"></a>
#### 현재 실행과 중복 방지

2026-10-08 기준으로 운영 카드 흐름은 기존 단일 DB를 사용한다. `app.ledger.recordable_rows()`는 blocked·already_booked를 제외한 고유 거래를 반환하며 미리보기 ready와 홈 집계가 함께 사용한다. 출력 화면과 작업 조회는 읽기 전용 SELECT를 사용한다. 장부 projection은 거래 ID를 먼저 검사하고 거래 ID가 없는 과거 행에만 카드사·카드·승인번호·일자·부호 있는 금액·거래 종류를 함께 비교한다. 승인과 취소를 같은 거래로 합치지 않는다.

명시 일정의 원본과 최신 근거가 맞지 않으면 기록을 차단한다. 서버 정상 여부와 모든 여행 일정의 검증 완료 여부는 별개다. 최신 운영 수치와 미결 항목은 [운영 문서](../operations.md)를 따른다.

---

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md"></a>

## autonomous-cycle-checkpoint

통합 전 경로: `docs/archive/ota-legacy-20261023/autonomous-cycle-checkpoint.md`

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--자율-개발-체크포인트"></a>
### 자율 개발 체크포인트

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--현재-운영-반영-2026-10-12"></a>
#### 현재 운영 반영: 2026-10-12

- 최신 운영 코드는 `124b33734456819c670c20ff01548385a1a0cebd`다. 메뉴·OTA 아이콘 구현 `1ff5404`, 표적 검사 `0d429ee`를 검토하고 Google 상세 검사의 모호한 여행명 선택자를 수정했다. 해당 실패 검사는 수정 후 `1 passed`다. 사이드 여행 목록은 COST 수입 금액 대신 날짜를 표시하며 초기·자동 갱신에 같은 렌더러를 사용한다. OTA 예약 상태·여행 배정·기간 경고·빈 결과에 아이콘을 넣고 긴 여행명을 줄바꿈한다. 기존 Windows 호스트 배포의 health/ready와 Board·SourceRefresh 실행을 확인했다. 실제 owner 390px OTA에서 50행의 여행 상태 표시, 수입 0원 badge 0개, 중복 업무 메뉴 0개, 가로 넘침 없음을 확인했다. DB·스키마·Google 쓰기·전체 회귀 반복은 없다.
- 0원 표시 원인은 Google 수입이 아니라 COST 내부 수입 합계를 여행 목록에 표시한 것이다. 읽기 전용 조사에서 COST 수입 행은 0개, Google 여행 연결은 19개였고 메인·보관 동기화는 정상이다. OTA 1,177건 중 저장 여행 연결 53건, 미배정 1,124건이다. 미배정 중 단일 기간 958건, 기간 없음 156건, 기간 충돌 10건이며 취소 관측 116건은 앞 분류와 중복이다. 예약 DB 여행 연결 154건은 모두 proposed다. OTA 목록은 확정 예약 연결 또는 예약번호가 있는 장부 행을 읽고 카드의 여행 배정 자체는 직접 읽지 않는다. 제안이나 날짜만으로 여행을 확정하지 않았다. 익명 집계 근거는 원본 작업 트리의 `.local-archive/ota-assignment-summary-20261012.json`에 보존했다.

- 직전 배포 코드는 `eca52c89fed7ff291977bb126bd4bd6b85997bcf`다. 사용자 지정 2026-09-19~09-24 카드 3820 사용내역 13건을 새 `0919_0924_싱가포르` 여행에 배정했다. 새 표적 8 passed와 분기 규칙·사용자 일정 인접 11 passed를 확인했다. 복구 사본의 원본 필드·대상 밖 거래·보호 테이블 보존 및 재시도 검사 후, 관리 쓰기 중단·백업 복원 검증·적용·기존 서버 전환을 수행했다. 적용 근거는 `D:/WebLedgerHost/data/backups/singapore-exception-20261012T075647961050Z/result.json`이다. 사용자 확정·장부 기록·Google 쓰기·스키마 변경은 없고 전체 회귀는 반복하지 않았다.

- 메뉴 통합·카드 검토 스크립트 복구를 `56867150de2db90a3f4e0152a685f2d1c50466c3`로 배포했다. OTA 메뉴 하나와 페이지 내 전체 예약·여행 미배정 전환, 카드 내역 명칭 통일, 모바일 홈 작업 메뉴 축약을 적용했다. 목록·메뉴·브라우저 검사에서 17 passed / 5 subtests 후 카드 자료 이동 실패를 수정해 해당 검사 1 passed다. 카드 검토 인접 검사 54 passed / 41 subtests 후 모바일 홈 실패를 수정했고 해당 검사와 서명 카드 권한 검사 2 passed다. 범위가 겹치므로 합산하지 않는다. 전체 회귀·운영 백업 재실행은 생략하고 기존 데이터 보존·복원 근거를 재사용했다. DB·회계 저장·스키마 변경은 없다.

- OTA 전체·미배정 조회를 `374cebc1fba2594111d1d55801cceb3c37db8aa8`로 기존 Windows 호스트에 배포했다. 공통 메뉴의 `/ota`, `/ota?state=unassigned`와 owner 전용 `/api/ota`는 등록된 예약 DB·메일만 읽는다. 같은 제공자·예약번호를 한 예약으로 모으되 기간 충돌을 표시하고, 저장된 여행 연결만 배정 근거로 쓴다. 카드 대사와 여행 미배정을 구분하며 원본·사용자 결정·회계 금액·스키마는 변경하지 않는다.
- OTA 구현·서명 HTTP·카드 목록·공통 셸 인접 검사: 27 passed / 37 subtests. 합성 Chromium 390·1440px 메뉴·전체/미배정·검색·재조회·정렬·월 필터: 1 passed / 2 subtests. 앞선 아이콘 UI를 함께 배포하므로 이전 검증이 없던 Google·영수증 인접 검사도 85 passed / 15 subtests로 확인했다. 실제 운영에서 카드 검토 XLSX를 SQLite로 읽으려던 잘못된 가정을 발견해 제거했고, 복수 메일 디렉터리 파싱 캐시가 필터 요청마다 비워지는 문제를 재현해 수정했다. 후속 OTA·브라우저 검사: 9 passed / 2 subtests. 예약 목록에서 결제 재대사를 하지 않는 검사도 포함한다. 범위가 겹치므로 합산하지 않는다. 전체 회귀는 반복하지 않았다.
- 운영 health/ready는 배포 스크립트에서 200, 비로그인 OTA API는 401/no-store였다. 실제 owner 사이트의 390px 전체·미배정 전환, 사이드 메뉴 하나, 오류 안내 없음, 가로 넘침 없음을 확인했다. 첫 조회는 재시작 직후 약 42.7초, 이후 미배정 전환은 약 3.6초였다. 합성 검증을 실제 단말 검사라고 표시하지 않는다. 기존 원본 작업 트리의 수정 파일 1개·미추적 파일 4개와 stash를 보존했고 SourceRefresh 작업과 기존 Tunnel을 유지했다. main 병합·DB 마이그레이션·Google 쓰기·신규 과금은 없다.

- 카드 표의 별도 드롭다운을 제거하고 거래일·카드·상태 제목 버튼으로 정렬·필터 메뉴를 여는 UI를 `c26b1b8cfe57de6427a8638de0884ebf33075715`로 운영 반영했다. 선택 조건을 제목 옆에 표시하고 검색 입력과 기존 조건을 함께 보존한다. 조회·브라우저 6 passed / 3 subtests, 상태 메뉴·입력 보존·화면 경계를 추가한 브라우저 후속 1 passed / 3 subtests다. 합성 375px·390px·1440px에서 메뉴 조작·Escape·새로고침·월·카드·상태 선택을 검증했다. 실제 운영 390px의 제목 메뉴 열기·오름차순 적용·선택 표시·사이드 메뉴·health/ready 200을 확인했다. 서버 조회·DB·스키마 변경은 없으며 전체 회귀를 반복하지 않았다.
- 사이드 메뉴 외형이 화면마다 달라지던 문제와 전체 카드 상단 버튼을 `e14c4316a9e9531427fd50ff52b9cbedc9254e46`로 수정·배포했다. 공통 메뉴 CSS를 통일하고 카드 CSS를 작업 영역에 한정했다. 주요 버튼은 녹색, 보조 버튼은 테두리형이며 검색 영역과 목록 간격을 정돈했다. 메뉴 외형 비교는 수정 전 390px·1440px에서 실패를 재현했고 수정 후 1 passed / 2 subtests다. 카드·공통 메뉴 브라우저 표적 검사에서 다른 4개 검사와 12 subtests가 통과했다. 공통 메뉴 설명을 접으면서 중복된 링크 이름은 기존 검사의 작업 영역 선택자로 구분했고 해당 검사 1개도 통과했다. 실제 운영 390px에서 장부 → 전체 카드 이동 후 메뉴 외형 동일, 상단 버튼 3개·검색 강조·월 필터·가로 넘침 없음·health/ready 200을 확인했다. DB·API·스키마 변경과 전체 회귀 반복은 없다.
- 전체 카드 내역에 거래일 오름차순·내림차순과 월별 조회를 추가하고 `79e0a5551e7cfb9893adddea272dcebadfad397b`로 운영 배포했다. 거래일·카드·상태 헤더의 드롭다운 선택 시 즉시 적용한다. 검색·페이지 이동·새로고침에서도 조건을 유지하며 모바일에서도 헤더 필터를 표시한다. 표적 명령 `python -m pytest webapp/tests/test_card_catalog.py webapp/tests/test_card_catalog_browser.py webapp/tests/test_site_shell_browser.py -q --tb=short`: 8 passed / 11 subtests. 합성 390px·1440px과 실제 운영 390px의 월 조회·오름차순·사이드 메뉴·가로 넘침 없음·health/ready 200을 확인했다. 읽기 전용 변경이며 DB·스키마·회계 원본 변경과 전체 회귀 반복은 없다.
- 공통 사이드 메뉴를 `22f1867450ff0e67c45260dd519fad8a3f20d90b`로 운영 배포했다. 카드 검토·전체 카드·영수증·Google·예약 연결·여행·계정 화면에서도 같은 메뉴를 표시한다. PC 고정 메뉴, 모바일 접이식 메뉴, 현재 메뉴 표시와 메뉴 스크롤·최근 여행 선택 복구를 지원한다. DB·스키마·회계 원본은 변경하지 않았다.
- 이번 표적 검증: 공통 화면·브라우저 5 passed / 9 subtests, 서명 세션·viewer·수입·기존 장부 인접 42 passed / 39 subtests, PC 가로 넘침 1 passed / 9 subtests. 실제 운영 owner 브라우저에서 전체 카드 → 카드 검토 이동, 390px 메뉴 조작·가로 넘침 없음, health/ready 200을 확인했다. 전체 pytest와 유효한 백업·복원 검사는 반복하지 않았다.
- 후속 요청을 `5d89c7d`로 배포했다. 홈·카드 검토·장부 업무 메뉴에 `/cards` 전체 카드 내역을 추가했다. DB의 전체 거래를 원본 거래별로 조회하며 업로드·검토 기간으로 제외하지 않는다. 검색·카드·분류 상태 필터, 50건 단위 페이지 이동, 취소·환불·중복·회사 제외 표시와 원래 업로드 검토 화면 이동을 지원한다. 조회는 CardFlow 생성·분류·DDL·장부 쓰기를 수행하지 않는다. 실제 owner 사이트에서 전체 6,037건, 첫 페이지·다음 페이지 50건씩, 390px 가로 넘침 없음, health/ready 200을 확인했다.
- 사용자의 여행 자동 연결 지시에 따라 단일 전체 이름·일정이 일치하는 후보만 연결하는 owner POST를 추가하고 운영 여행 19개를 연결했다. 기존 수동 연결·정본 선택·viewer grant를 보존하고 중복·사본·연도 충돌은 건너뛴다. 문서에 확정된 2027년 여행 예외도 보호한다. 연결된 실제 여행 장부에서 미연결 표시가 사라지고 수입 영역이 정상 조회되는 것을 확인했다. 이전 0건 기록은 연결 전 상태다. 원본 Google 쓰기나 회계 DB 변경은 없다.
- 표적 검사: 전체 카드·브라우저·자동 연결 12 passed, 카드·정본 인접 및 실제 페이지 이동 59 passed / 39 subtests, 서명 쿠키 HTTP의 owner·viewer·익명 접근 및 새 쓰기 경계 2 passed / 24 subtests, 초기 Google·수입·자동 연결 50 passed. 전체 pytest는 반복하지 않았다. 원본 dirty 파일 5개와 기존 stash는 동일하다.
- 예약 메뉴·수입 연결 요청: `0750eed`, `00dec30`을 구현·배포했다. 메뉴는 ‘예약 명단·여행 연결’이며 예약 명단의 행사와 COST 여행 연결 → 연결 저장 → 명단 적용의 목적을 설명한다. 카드 대사나 수입 확정 메뉴와 구분한다. 여행 장부에는 명시적 Google 연결·현재 정본 기준 수입내역을 표시하며 예약금·잔금·추가금·원본 상세를 조회한다. 미연결·조회 실패·정본 미선택·미검증을 실제 0원과 구분하고 COST 수입 행을 새로 만들지 않는다. viewer의 현재 여행 접근·Google grant를 모두 검사한다. 연결 설정에서는 현재 여행을 미리 선택하고 가져온 여행의 이름을 표시한다.
- 이번 검증: Google·정본·탐색·수입 표적 65 passed, 수입·브라우저·화면 후속 11 passed / 2 subtests, 모바일 머리글 넘침 후속 4 passed / 8 subtests, 설정 없음·여행 없음 후속 3 passed. 최종 연결 문맥·수입·Google 표적 `python -m pytest webapp/tests/test_trip_google_income.py webapp/tests/test_trip_google_income_browser.py webapp/tests/test_google_ledger_page.py -q --tb=short`는 43 passed다. 합성 Chromium 390px에서 연결 저장 → 여행 복귀 → 새로고침 → 수입 상세까지 완주했고 COST 수입 행 추가가 없음을 확인했다. 검사 범위는 겹치므로 합산하지 않는다. 기존 회귀·인접 근거를 재사용하고 전체 pytest는 실행하지 않았다.
- 실제 사이트 owner 읽기 스모크: 새 예약 메뉴, 여행 수입 영역, 현재 여행이 미리 선택된 연결 화면과 여행 복귀 링크가 정상이며 health/ready 200이다. 실제 여행 연결은 아직 0건이다. 서로 같은 여행인지 사용자가 선택·저장해야 수입을 표시하며 자동 추측 연결이나 Google 쓰기는 수행하지 않았다. DB·스키마·기존 확정 변경 없이 코드만 전환했고 아래 기존 복원 근거를 재사용했다. 원본 dirty 파일 5개와 stash `fbb1226e4659e4a2b75216cd556b51687db7d73e`를 보존했다.
- 카드 상세의 운영 timeout은 `review_mail_evidence`가 요청 잠금 안에서 메일 전체를 다시 읽는 경로로 재현됐다. `6397447`에서 OTA 워커가 활성화된 경우 안내 문구는 기존 OTA 검토 화면으로 연결해 중복 대사를 제거했다. 미리보기·확정의 기존 스냅샷 보호는 유지한다. 재현 검사 포함 카드·3820 정책 53 passed / 39 subtests, OTA authority·report reuse 16 passed다. 수정 배포 후 실제 owner 세션의 국내 카드 상세는 200, 약 3.6초이며 해당 자료의 정책 적용 159건과 health 200을 확인했다. 전체 자료의 정책 적용은 177건이다. 일시 진단용 런처 변경은 원래 내용으로 복원했고 새 운영 프로세스에는 적용하지 않았다. 최신 백업·복원 근거는 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T115405/restore-evidence.json`이다. 아래 최초 timeout 기록은 후속 수정으로 해소됐다.
- 카드 3820 신설 규칙: `725e16d`와 매입 구분 후속 수정 `899821f`를 운영 반영했다. 기존 대사 후 미처리 매입만 분기 기타비용으로 분류한다. 최초 표적 50 passed / 39 subtests, 회사 제외 인접 12 passed, 실제 일시불매입 형식 후속 52 passed / 39 subtests다. 운영 잔여 177건(2026년 2분기 15, 3분기 157, 4분기 5)을 기존 대사 결과에서 선별해 한 트랜잭션으로 분류하고 거래별 감사 이력을 남겼다. 모든 거래의 분류 외 원본 필드, 비대상 전체 행, 장부·사용자 결정·기타 기존 테이블 지문이 보존됐다. 자동 확정·장부 기록·Google 쓰기는 하지 않았다. 분기 비용을 여행으로 추측 배정하지 않는다. 운영 백업·복원은 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T114203/restore-evidence.json`을 사용했다. 공개 사이트 후속 브라우저 호출은 도구 timeout으로 완료하지 못했으며 새 배포의 localhost health/ready는 정상이다.
- 운영 배포 SHA는 `c26b1b8cfe57de6427a8638de0884ebf33075715`다. PR #85의 `integration/cost-final`에서 개발했고 main은 병합하지 않았다. 이후 문서 전용 커밋은 운영 코드와 구분한다.
- 기존 주소 `https://ledger.foresttour.kr`, Windows PC, Cloudflare Tunnel, `127.0.0.1:8751`, 데이터 루트 `D:/WebLedgerHost/data`를 유지한다. `WebLedger-Board`는 `D:/WebLedgerHost/releases/<배포 SHA>/tools/start_web_ledger_host.ps1`에 고정됐다. 운영 원본 `C:/AX/cost`는 갱신하거나 초기화하지 않았다. 예전 `restart_real_review_host.ps1`로 원본 checkout에 되돌리지 말고 현재 예약 작업의 고정 경로를 사용한다.
- 새 기능: 설치돼 있던 Windows 일본어·한국어 OCR을 영수증 사진과 연결했다. 글자와 제한된 날짜·일본어 합계 제안만 제공하고 사용자 확정 없이 비용을 만들지 않는다. 기존 localhost:8088 AI는 결정론적 해석이 실패할 때 사용자 문장만 받아 규칙 초안을 제안한다. 향후 반복 규칙은 기존 규칙 저장 화면에서 별도 확인한다. Google 여행 연결과 viewer 허용·철회 화면을 추가했다. 기존 여행 권한과 정본 검사를 우회하지 않는다.
- 모바일 장부 작업 메뉴를 접이식 여행 탐색 영역으로 옮겨 첫 거래가 화면 아래로 밀리던 문제를 수정했다. 실제 사이트 375px 영수증·Google, 390px 카드·장부, 데스크톱 약 1440px 장부에서 가로 넘침 없는 접근을 확인했다. 실기기 검증은 아니다. 운영 거래를 새로 확정하거나 영수증을 실제 DB에 시험 등록하지 않았다.
- 실제 owner Google OIDC 세션, 공개 주소 health/ready 200, 비로그인 카드 API 401 및 Google API 403을 확인했다. 실제 viewer 계정의 로그인 완주는 아직 검증하지 않았다. 합성 세션 검사와 구분한다.
- 실제 Google 메인·보관 읽기는 기존 공개 링크 XLSX 방식으로 성공했다. ADC 환경변수·기본 credential·refresh token은 없었다. ADC 성공이라고 보고하지 않는다. `WebLedger-GoogleAuthority`는 매시 정각 KST, 중복 실행 금지, 읽기 전용 public 모드로 등록했고 수동 시작 1회 결과 0을 확인했다. 이 작업은 동기화 코드가 같은 `2a330ca` release에 고정돼 있다. 기존 `WebLedger-SourceRefresh`의 300초 수집 주기를 유지한다. Google 원본·공유권한은 변경하지 않았다.
- 운영 백업·복원 증거: `D:/WebLedgerHost/data/backups/v2-deploy-20261012T004430/restore-evidence.json`. DB 4개와 설정·영수증·Google 세대 파일 33개를 복원해 비교했다. 비밀 파일은 기존 위치에 보존했고 이 묶음에는 복사하지 않았다. 격리 복원본 스키마 리허설 후 운영에는 `transaction_company_exclusions`만 통제된 트랜잭션으로 추가했다. 원래 77개 테이블 중 재시작 lease 행 추가 외 원본 행 지문은 동일했다. 첫 시도는 백업의 빈 WAL sidecar 때문에 마이그레이션 전에 차단됐고 기존 서비스로 복귀했다. 백업 대상만 DELETE 모드로 바꾸는 수정 후 성공했다.
- 전체 검사 1회: 시작 `a2075d66dbc031cdfe80a331d5e66e8fbd524ebd`, 종료 `fdd5308d5bb9542975498d69af42604b3c4504c2`, **23 failed / 3203 passed / 3 skipped / 2431 subtests**. 최종 SHA 전체 통과 기록이 아니다. 원인은 모바일 거래 위치와 생산 모드 거부 검사의 환경변수 누출이었다. 제품 보호 조건은 유지했다. 실패 영역의 순서 있는 후속 검사 112 passed / 53 subtests와 누락 import 수정 후 해당 검사 1 passed로 해결했다.
- 추가 표적 근거: 영수증 50 passed / 15 subtests, 규칙 33 passed / 1 skipped / 12 subtests, 실제 로컬 AI 관련 4 passed, 백업·리허설 16 passed. Google 설정·매핑·페이지·서명 HTTP 묶음은 62 passed / 35 subtests와 신규 검사의 CSS 문자열 기대 1건 실패였다. DOM 요소 존재로 기대를 바로잡고 설정 화면 최종 배치 후 신규 실제 브라우저 포함 2 passed다. 중복 범위는 합산하지 않는다. 과거 3107 passed 기준선은 과거 SHA의 증거로만 보존한다.
- 사용자 원본 dirty 5개(`tools/verify_lightweight_runtime.py`, `edit_card_flow.py`, 두 pending-card-evidence patch, SQLite checkpoint JSON)와 stash `fbb1226e4659e4a2b75216cd556b51687db7d73e`를 보존했다. 테스트가 바꾼 추적 화면 캡처 2개만 `.local-archive/deploy-regression-20261012`에 보관하고 원래 추적 버전으로 돌렸다.
- 후속 구현 `de684eb`: 원화 영수증 통화 선택 → 금액 수정 → 여행 배정 → 확정 → 새로고침 → 실제 7열 클립보드 복사를 합성 Chromium 390px에서 완주했다. KRW 원금은 환산하지 않고 `total_original`에 보존하며 `total_jpy`는 null이다. 늦게 들어온 국내 법인카드는 현금 영수증 복사를 차단하고, 증빙으로 연결하면 추가 비용을 만들지 않는다. 기존 JPY 자료는 읽기·TSV로 재작성하지 않는다. 기존 영수증·후보와 신규 원화 검사 58 passed / 15 subtests, 최종 원화·무결성·서명 HTTP 39 passed / 35 subtests다.
- 원화 반영 직전 새 백업 `D:/WebLedgerHost/data/backups/v2-owner-ui-20261012T010720/restore-evidence.json`에서 DB 4개와 파일 34개의 복원·원본 불변·설정 연결 비교가 통과했다. DB DDL은 추가하지 않았다. 실제 사이트 375px에서 통화 선택·원화 안내·OCR 버튼·ready 200을 확인했다. 운영에 합성 영수증을 기록하지 않았다. 원화 후보가 저장된 이후에는 KRW를 읽지 못하는 이전 release로 단순 코드 롤백하지 말고 호환 코드를 유지해야 한다. 복구를 이유로 새 사용자 기록을 덮지 않는다.
- 남은 실제 기능 범위: PDF 입력과 자동 복수 영역 분리는 미구현이다. 일본어·한국어 OCR은 글자를 읽지만 지급처·통화·결제수단·영역을 모두 자동으로 확정하지 않는다. 사진 OCR은 전체 사진을 읽으며 영역별 자동 OCR이라고 표시하지 않는다. 실제 ADC와 viewer 계정 검증, 실제 모바일 단말 검증은 외부 자원이 필요하다. 실제 회계 top3 공개는 비활성이고 별도 게시 승인이 필요하다.
- 다음 구현 시작점: `tools/windows_receipt_ocr.ps1`, `app/local_receipt_ocr.py`, `webapp/receipt_review.py`에서 Windows 기본 PDF 렌더링 지원을 격리 합성 자료로 확인하고 원본 보존·페이지별 사진 후보 연결을 구현한다. 자동 복수 영역 추출은 별도 작업이다. 운영을 이전 원본 경로로 재시작하지 않는다.

이하 항목은 이전 실행 기록이며 위 운영 배포 상태를 덮지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--현재-작업-기본-업무-화면과-모바일-ui"></a>
#### 현재 작업: 기본 업무 화면과 모바일 UI

- 시작 HEAD `457b03b2a40e7888440e8b7e1f3558a6dc53ca49`. 이번 구현은 홈·장부 업무 메뉴, 로컬 수입과 Google 정본 구분, 모바일 Google·영수증 화면, 인증 상태의 바이너리 업로드, 확정 일정의 불필요한 XLSX 서비스 의존성 제거다. 최신 SHA는 PR #85와 Git을 따른다.
- 실제 Chromium 375·390·1440px에서 여행 선택·영수증 진입·입력 버튼 배치·Google 수입/순수익 표시를 검사했다. 장부 모바일 및 홈 인접 검사 7 passed / 10 subtests, 수입 안내 후속 3 passed / 3 subtests, Google 표적 50 passed / 3 subtests, 일정 원본 인접 20 passed / 10 subtests, 영수증 및 무결성 74 passed / 15 subtests. 범위가 겹치므로 합산하지 않는다.
- 인증을 켜면 사진과 XLSX를 폼으로 먼저 해석해 422로 거부하던 실제 결함을 수정했다. 서명 쿠키의 사진·XLSX 후속 2 passed / 7 subtests에서 owner 성공, viewer·익명 차단, CSRF 및 원화 금액 보존을 확인했다.
- Google 동기화 자료가 없거나 손상된 경우 HTML에는 다시 확인 화면, API에는 기존 503 JSON을 유지한다. 신규 브라우저 복구 검사는 통과했다. 기존 HTML의 JSON 기대 검사 1건은 새 화면 계약과 API 오류 코드 보존을 함께 확인하도록 수정했고 후속 1 passed다.
- 합성 미리보기: `python -m tools.run_synthetic_preview --port 8795`, `http://127.0.0.1:8795/preview`. 임시 DB·합성 일정/Google 자료만 사용하고 외부 서비스·운영 환경변수를 사용하지 않는다. 종료하면 예시 입력도 삭제된다. 신규 실제 브라우저 검사 1 passed: 카드 확정·7열 복사 → 사진 업로드·수동 확정·중복 복사 경고 → Google 정본 선택·수입 900,000원/순수익 780,000원. 인증·일정 검증을 테스트 대역으로 바꾸지 않았다.
- 실제 미리보기에서 수동 등록 여행이 홈에 나타나지 않던 문제도 수정했다. 출발 예정 여행이 없으면 활성 여행을 `등록된 여행`으로 표시한다. 홈 여행 선택부터 위 업무까지 완주한 신규 검사와 기존 홈 인접 검사 2개가 3 passed다. 일정 상태나 거래를 변경하지 않는다.
- 운영 사이트 읽기 요청은 Cloudflare 403으로 거부됐다. 로그인 뒤 화면과 실행 SHA는 미확인이다. 문서상 운영 코드 경로 `C:/AX/cost`는 현재 `main`의 `8472729`이며 통합 worktree와 다르다. 운영 코드를 반영하지 않았다. 실제 Google/OIDC 인증·OCR 추론은 완료로 표시하지 않는다.
- 다음 작업: 미리보기에서 사용자 화면을 확인한 뒤 운영 반영 승인을 받으면 배포 대상 SHA·운영 연결 설정과 DB 요구사항을 점검한다. 그 전에는 운영 배포·DB·Google 원본 변경 없이 재현된 기본 업무 장애만 수정한다. 전체 회귀는 이번 UI 작업에서 실행하지 않았다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--2026-10-11-운영-인수-위험-해소"></a>
#### 2026-10-11 운영 인수 위험 해소

- 시작 HEAD `e3feb4ce7a648674648d2614a754e8da46d85f41`, 브랜치 `integration/cost-final`. 코드·검사 커밋 8개: `79231b5`, `bc2d437`, `335071e`, `2fed028`, `85a3a2c`, `d0034dc`, `1f0f8ab`, `fddf635`. 이후 기록 SHA는 Git과 PR #85를 따른다.
- 시작 실패: 접근제어·OIDC·예약 동기화 초기화 실패에서 워커·소켓·DB·전역 바인딩을 정리한다. 포트 충돌·워커 시작 실패는 기존 저장소 바인딩을 교체하지 않는다. 예상하지 못한 초기화·파일 I/O 오류는 원문 대신 고정 코드로 종료한다.
- DB 종료를 추가한 구현의 경합도 검사했다. 진행 중인 쓰기보다 먼저 DB를 닫는 문제를 확인해 요청 잠금으로 보완했다. 현재 쓰기는 완료한 뒤 연결을 닫고 대기 요청은 `503 SERVER_STOPPING`으로 거부한다. 합성 SQLite에서 실제 트랜잭션의 보존을 확인했다. 실제 운영 서버 재시작 검증은 아니다.
- Windows 실행기는 상속된 예약 동기화 활성 값을 지우고 이번 설정 파일의 명시적 opt-in만 사용한다. 운영 실행이나 스케줄러 활성화는 하지 않았다.
- 상대 데이터 루트를 먼저 절대 경로로 바꿔 검사를 우회하던 문제를 수정했다. 영수증·Google 스냅샷·비공개 행 파일도 두 운영 실행기에서 상대·임시·소스 체크아웃 내부 경로를 거부한다. 선택 기능을 새로 켜거나 기존 파일을 이동하지 않는다.
- Google: 실제 ADC 내보내기 어댑터에 합성 인증·전송을 주입했다. 손상된 XLSX의 마지막 정상 행 보존, 다른 원본 정상 갱신, 지연 후 복구, 읽기 전용 scope·리다이렉트 금지·응답 정리·원문 비노출을 확인했다. 실제 Google 인증 성공 증거는 아니다.
- 캐시: 실제 서명 쿠키 HTTP에서 owner·viewer·익명의 Google·영수증 HTML/API 허용·거부 응답에 `no-store`를 확인했다. 이미 사용자에게 전달된 자료를 원격 삭제한다는 뜻은 아니다.

검사 결과는 범위가 겹치므로 합산하지 않는다.

| 실제 검사 범위 | 결과 |
| --- | --- |
| `test_runtime_lifecycle.py`, `test_cp949_startup.py`, `test_schema_gate.py` | 초기 정리 수정에서 20 passed |
| `test_runtime_lifecycle.py`, `test_platform_start.py` | 서버 생성 실패 수정에서 33 passed |
| `test_runtime_lifecycle.py`, `test_batch_concurrency.py` | 종료 중 쓰기 보존 수정에서 12 passed |
| `test_signed_session_http.py` | 요청 경계 수정 후 8 passed / 28 subtests. 이후 신규 `-k never_cache`는 1 passed |
| `test_google_authority.py -k adc_corrupt_xlsx` | 1 passed |
| `test_launch_ota_review.py`, `test_schema_gate.py` | 설정 활성화 수정에서 21 passed |
| `test_ops_safety.py -k 'relative_data_root_is or direct_config_refuses or ConfiguredRoot'` | 7 passed |
| `test_ops_hosting_bind.py::DurableDataRootIsNotInsideTheCheckout`, `::TheEntryPointRefusesCleanly` | 10 passed / 4 subtests |
| `test_runtime_lifecycle.py -k 'optional or path_refusal'` | 12 passed |
| `test_runtime_lifecycle.py -k data_root_io_failure` | 실패 재현 후 수정, 1 passed |
| cp949 고정 문자열·운영 합성 세션 거부·운영 OIDC 합성 바인딩 거부 | 3 passed |

- 실패는 위 코드 수정으로 해소했다. 신규 캐시 검사의 초기 잘못된 상태 코드 기대값은 기존 계약(익명 Google 403, viewer 영수증 404)에 맞췄다. 보호 조건을 삭제하지 않았다. 전체 pytest와 기존 6개 브라우저 완주는 재실행하지 않았으며 이전 근거를 최신 HEAD 전체 통과로 바꾸지 않는다.
- `tools/rehearse_cost_schema.py --help`로 `--source-copy`, `--expected-sha256`, `--confirm-isolated-copy`, `--check-only`를 확인했다. 승인된 실제 사본 경로가 지정되지 않아 실제 사본 검증은 하지 않았다. 기존 합성 리허설·원자성·WAL·복구 검사를 재사용한다. 백업 래퍼는 프로세스 중단·재시작이 있어 실행하지 않았다.
- ADC 기본 파일·지정 파일과 현재 필수 OIDC 설정이 없는 것을 값 비노출로 확인했다. 승인된 시험 자격증명, 승인된 복구 사본, 기존 회계 정책 결정, 운영 반영 승인은 HOLD다. CODE READY는 위 수정·비운영 검증 범위이며 INTEGRATION VERIFIED·OPERATIONAL VERIFIED로 상향하지 않는다.
- 다음 시작: `git -C C:/AX/cost-integration status --short`. 사본 제공 시 위 CLI 옵션과 승인 해시로 읽기 전용 진단을 진행한다. 시험 계정 제공 시 OIDC·ADC 실제 읽기와 철회·만료를 검증한다. 병합·배포가 승인되면 그 게이트에서 시작 SHA와 종료 HEAD를 기록해 필요한 전체 회귀를 실행한다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--2026-10-11-최종-업무-흐름-브라우저-검증"></a>
#### 2026-10-11 최종 업무 흐름 브라우저 검증

- 시작 HEAD: `1b3edbd5d5b308f50922b4fd3619c4bacf92d188`. 코드·검사 커밋은 `753e861`, `97819e5`이며 이후 기록 커밋은 Git과 PR #85를 따른다.
- 제품 수정: 영수증 후보 수정 화면의 결제수단을 현금·개인카드·법인카드로 표시한다. 저장값과 금액 계산은 유지한다. 기존 화면의 영문 코드 노출을 재현한 뒤 수정했다.
- 실제 Chromium, loopback HTTP, 임시 DB·합성 파일을 사용한 375px 검사 7개가 최종적으로 통과했다. 아래 결과는 서로 겹치는 재실행을 합산한 수치가 아니다.

| 흐름 | 실제 화면 조작과 저장 결과 |
| --- | --- |
| 카드 | CSV 업로드·분류 → 항목·여행·설명 입력 → 확정 → 새로고침 → 7열 클립보드 복사. 원본 37,000원과 사용자 확정을 DB에서 확인했다. 복사가 COST 장부 쓰기를 만들지 않는다. |
| 영수증 | PNG 업로드 → 영역 등록 → 여행·금액 수정 → 확정 → TSV 복사. 별도 검사에서 결제수단 변경 시 확정을 해제하고 재확정·새로고침 후 값을 보존한다. 나중에 수집된 동일 카드 근거가 있으면 복사를 보류하고 클립보드와 영수증 원본 파일을 유지한다. |
| 회사 경비 | 자연어 제외 제안 → 실제 저장 후 응답 유실 → 같은 요청 재시도 → 새로고침 → 제외 취소 → 새로고침. 두 제외 요청이 같고 거래 원본이 보존되는 것을 확인했다. |
| 부분환불 | 실제 합성 카드 XLSX 업로드 → 원결제 확정 → 같은 파일 재업로드 → 환불 쌍 기록 → 새로고침 → TSV 복사. 원결제 1,000,000원과 환불 -700,000원을 각각 보존하며 장부 2행·순액 300,000원, TSV 2행을 확인했다. |
| Google 정본 | 합성 메인·보관 스냅샷 → owner의 archive 선택 → viewer 상세 → 권한 철회 후 같은 URL에서 404. 비공개 행이 거부 화면에 남지 않는다. 브라우저 역할은 합성 주입이며 실제 로그인 성공 증거가 아니다. |
| 자연어 승인 | 제안 → 승인 DB 저장 후 응답 유실 → 동일 request_id로 재시도 → 결정 이력 1건 → 새로고침 후 화면·DB의 확정값 확인. |

실제 실행 명령과 결과:

- `python -m pytest webapp/tests/test_card_google_copy.py webapp/tests/test_receipt_review.py webapp/tests/test_company_exclusion_http.py webapp/tests/test_google_canonical_workflow.py webapp/tests/test_rule_review.py -k 375 -q --tb=short`: 처음 3 passed / 2 failed. 실패는 새 검사의 금액 기대값 오류와 JavaScript 불리언·숫자 엄격 비교 오류였다. 아래 표적 재실행으로 모두 수정 확인했다.
- `python -m pytest webapp/tests/test_card_google_copy.py webapp/tests/test_rule_review.py -k 375 -q --tb=short`: 2 passed.
- `python -m pytest webapp/tests/test_card_google_copy.py -k mobile_375_partial -q --tb=short`: 1 passed.
- `python -m pytest webapp/tests/test_receipt_review.py -k payment_review_and_late_card -q --tb=short`: 결제수단 표시 assertion 실패를 먼저 확인했다. 표시 수정 뒤 새 검사의 존재하지 않는 confirmed 필드를 실제 payee/category 계약으로 고쳤고 최종 1 passed.
- `python -m pytest webapp/tests/test_receipt_review.py -k mobile_375_photo -q --tb=short`: 표시 수정 후 1 passed.
- `git diff --check`: 통과. 기존 390px·1440px 브라우저, 서명 쿠키 HTTP, 회계 원자성·환불·중복 보호 검사는 기존 증거를 재사용했다. 변경은 표시 문구와 검사이므로 전체 pytest는 실행하지 않았다. 과거 전체 회귀를 최신 HEAD의 통과로 표시하지 않는다.

운영 경계와 다음 시작점:

- 승인된 실제 복구 사본이 없어 `tools/rehearse_cost_schema.py --check-only` 실측은 HOLD다. 운영 원본 DB를 열지 않았다. 실제 ADC/OIDC 인증, OCR 엔진, 운영 배포·병합은 실행하지 않았다.
- 실계정·실제 Google 연동·OCR 추론은 브라우저 완주에 포함하지 않는다. 회사 제외의 확정·기록 거래 정책과 중복 의심 영수증 인정 정책은 기존 HOLD를 유지한다.
- 다음에는 승인된 복구 사본이 제공되면 `docs/schema-rehearsal.md`의 필수 인자를 확인해 `--check-only`를 실행한다. 별도 비운영 계정이 제공되면 OIDC·ADC와 실제 여행 매핑을 검증한다. 운영 반영 승인 후에만 병합·배포 게이트를 실행한다.
- 사용자 `C:/AX/cost`의 dirty 1개, 미추적 4개, stash `fbb1226e4659e4a2b75216cd556b51687db7d73e` 목록을 보존했다. 내용 해시까지 비교한 것은 아니다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--2026-10-11-최대-구현-실행--후속-수정"></a>
#### 2026-10-11 최대 구현 실행 — 후속 수정

- 출발점은 `1eec6d7d39f78c1456524b5c09050978afeaf10a`이며 브랜치는 `integration/cost-final`이다. 구현 커밋 20개를 추가했고 코드 HEAD는 `f052fcaee7d300c1aaefbf0e99171f381aa423cf`다. 이후 기록 커밋의 SHA는 Git과 PR #85를 따른다. 제품·테스트 15개 파일을 변경했다.
- 영수증: 미저장 금액·여행으로 확정하거나 미저장 검토값 대신 저장값을 복사하는 경로를 막았다. 화면의 후보 지문을 쓰기 시 비교하며, 마지막 저장과 정확히 같은 재시도만 결과를 재사용한다. 기존 버전 없는 내부 호출은 호환한다. 저장·복사 중 입력과 중복 요청을 잠그고 실패 후 복구한다. 한 행의 저장은 다른 행과 영역 입력을 지우지 않으며, 사진·영역 등록 전에는 미저장 검토를 보호한다.
- 파일: 사진은 임시 파일 완성 후 교체하고 기존 사진의 내용과 ID가 다르면 제공·재등록을 거부한다. 파일 교체 실패·JSON 오류·잘못된 레코드 구조는 원본을 초기화하지 않고 안전한 503으로 처리한다. 비정상 HTTP 응답은 원문 대신 재로그인·저장 여부 확인을 안내한다.
- 카드·영수증 복사는 이력 읽기 차단 시 중복 위험을 확인받은 뒤 진행한다. TSV는 보류·오류 사본도 중복 ID의 근거로 사용하며 카드 어댑터도 그 근거를 제거하지 않는다. 무관한 행과 기존 보류 사유는 유지한다.
- 자연어 승인: 여행·설명·검토 전 분류·상호를 지문에 포함했다. 별도 DB 연결의 변경은 쓰기 트랜잭션 안에서도 원본 상태와 비교한다. 환불 미리보기의 상속값과 원본을 구분하며 중간 충돌은 앞선 결정과 요청 기록까지 롤백한다.
- Google 동기화: 손상된 재시도 상태는 원본 조회 전에 거부하고 마지막 정상 스냅샷을 보존한다. 잠금 초기화 실패 시 핸들을 닫고 파일 접근 오류는 안전한 코드로 반환한다. 잘못된 시간·크기 제한값은 파일 생성 전에 거부한다.

실제 검사 근거는 아래와 같다. 범위가 겹치므로 합산하지 않는다.

| 실제 명령 또는 범위 | 결과와 적용 시점 |
| --- | --- |
| `python -m pytest webapp/tests/test_receipt_review.py webapp/tests/test_receipt_integrity.py tests/card_pipeline/test_receipt_candidates.py -q --tb=short` | 공통 파일 오류 처리 변경에서 75 passed / 12 subtests. 뒤의 레코드 구조 검사 변경은 해당 HTTP 표적 5 passed와 `test_receipt_integrity.py` 24 passed로 검증했다. |
| `python -m pytest tests/card_pipeline/test_google_tsv.py tests/card_pipeline/test_receipt_candidates.py tests/card_pipeline/test_company_expense_integration.py webapp/tests/test_card_google_copy.py -q --tb=short` | TSV 공통 수정에서 47 passed / 4 subtests. 뒤의 어댑터 수정은 어댑터·회사 제외 통합 12 passed로 검증했다. |
| `python -m pytest tests/card_pipeline/test_sync_schedule.py tests/card_pipeline/test_google_adc_export.py -q --tb=short` | 재시도 상태 변경에서 36 passed. 뒤의 잠금 경로 11 passed, 안전한 파일 오류 1 passed, 제한값·기존 CLI 경로 9 passed를 별도로 확인했다. |
| `python -m pytest webapp/tests/test_rule_review.py tests/card_pipeline/test_rule_proposals.py -q --tb=short` | 지문 수정에서 45 passed / 12 subtests. 쓰기 경합 변경은 규칙·DB 동시성 30 passed / 12 subtests와 중간 롤백 1 passed로 확인했다. 마지막 원본·미리보기 구분은 관련 HTTP 7 passed와 DB 동시성 3 passed로 확인했다. |

- 전체 pytest는 실행하지 않았다. 아래 3107 passed / 3 skipped / 2456 subtests 기준선은 과거 SHA의 근거로 유지한다. 이번 HEAD 전체 회귀 통과를 뜻하지 않는다. 모든 신규 결함은 실패 재현 후 수정했고 보호 assertion을 약화하지 않았다.
- 사용자 작업 트리의 수정 1개·미추적 4개와 기존 stash 목록은 시작·후속 확인에서 같았고 건드리지 않았다. 운영 DB·Google 원본·공유 설정·스케줄러·main·배포 설정은 변경하지 않았다. 생성한 임시 worktree나 에이전트는 없다.
- 다음 첫 명령은 `git -C C:/AX/cost-integration status --short`다. 독립적인 새 결함 근거가 없다면 통과 검사를 반복하지 않는다. 실제 인수의 다음 세 단계는 승인된 복구 사본의 `tools/rehearse_cost_schema.py --source-copy <승인된 사본> --confirm-isolated-copy --check-only`, 승인된 ADC/OIDC 계정의 읽기·만료·철회 검증, main 병합 또는 운영 배포가 승인됐을 때 시작 SHA와 종료 HEAD를 기록하는 전체 회귀다. 현재는 해당 운영 승인·자원이 없어 HOLD다. OCR 엔진과 기록·확정 거래 제외 정책도 기존 HOLD를 유지한다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--2026-10-11-검증-정책-변경"></a>
#### 2026-10-11 검증 정책 변경

- [AGENTS.md](product-and-handoffs.md#src-agents-md--검증-최소화재검증-금지-작업-우선-원칙)에 표적·인접 통합 검사 중심 정책과 전체 회귀의 실행 조건을 반영했다. 기능 완료나 커밋 누적을 이유로 전체 회귀를 반복하지 않는다.
- 아래 **3107 passed / 3 skipped / 2456 subtests passed**는 과거 기준선으로 보존한다. 새 HEAD의 전체 회귀 통과를 뜻하지 않는다. 이번 변경은 작업 규칙 문서뿐이므로 diff와 링크만 검토하고 코드 테스트는 실행하지 않는다.
- 작업 브랜치는 `integration/cost-final`이며 정책 변경 전 HEAD는 `ccf6352fc22f12d9f579bcc08d0e6d2dce9959d7`다. 정확한 최신 SHA는 Git과 PR #85를 따른다. 다음 코드 작업은 실제 결함의 영향 범위부터 정하고 관련 표적 검사만 실행한다. 운영 HOLD는 해제하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--2026-10-11-cost-v2-통합-안정화"></a>
#### 2026-10-11 COST V2 통합 안정화

- 작업 브랜치는 `integration/cost-final`이며 시작 HEAD는 `bcb1f514629a8f4d3402c977ebaba9b3d8bff29e`다. 코드 커밋 9개를 작성했다. 현재 코드 HEAD는 `4e74f43`이며 문서 이후의 정확한 SHA는 PR과 Git을 따른다.
- 새 결함 수정: 이전 자료의 조회·자동 갱신·업로드·규칙 제안·장부 확정·회사 제외 응답이 최신 안내를 덮는 문제, 저장 뒤 조회 실패를 전체 롤백으로 잘못 알리는 문제, 응답 유실 후 승인·답변 재시도의 요청 번호가 달라지는 문제, 클립보드 복사 뒤 이력 저장 실패를 복사 실패로 알리는 문제를 수정했다. 운영 환경에서 합성 세션 어댑터를 연결할 수 있던 경로도 DB 접근 전에 거부한다.
- 실제 표적 근거: 카드·규칙·제외·카드 HTTP·회사 제외 통합 88 passed / 55 subtests; 후속 제안 오류 1 passed; 운영 실행·스키마 게이트 인접 83 passed / 16 subtests; 답변 재시도와 핵심 카드 브라우저 23 passed / 6 subtests; 복사 영향 8 passed; 장부 확정 응답 2 passed; 마지막 회사 제외 HTTP·통합 12 passed와 카드 핵심 브라우저 9 passed / 2 subtests. 범위와 시점이 겹치므로 합산하지 않는다.
- 이후 환불 묶음 경로 5 passed와 늦은 환불 요청 브라우저 1 passed, 규칙 저장 후 재분류·조회 실패 2 passed, 정상 규칙 편집·모바일 흐름 2 passed도 통과했다. 후속 오류만 한정해 검증했고 기대값이나 회계 보호를 약화하지 않았다.
- 같은 자료에서 새 답변을 저장한 뒤 이전 자동 갱신 오류가 성공 안내를 덮는 문제도 재현했다. 요청 시작 당시 화면 버전까지 비교하도록 수정한 후 조회·자동 갱신 브라우저 4 passed / 4 subtests를 확인했다.
- 대표 실제 명령: `python -m pytest webapp/tests/test_card_google_copy.py webapp/tests/test_rule_review.py webapp/tests/test_company_exclusion_http.py webapp/tests/test_card_flow.py tests/card_pipeline/test_company_expense_integration.py -q --tb=short` → 88 passed / 55 subtests; `python -m pytest webapp/tests/test_platform_start.py webapp/tests/test_ops_hosting_bind.py webapp/tests/test_cp949_startup.py tests/card_pipeline/test_schema_gate.py -q --tb=short` → 83 passed / 16 subtests; `python -m pytest webapp/tests/test_refund_group_commit.py -q --tb=short` → 5 passed.
- 전체 회귀는 코드 `ae8c056`에서 `python -m pytest -q --tb=short`로 한 번 시작해 **3107 passed, 3 skipped, 2456 subtests passed, 실패 0**, 1689.47초, 종료 코드 0으로 끝났다. 로그는 `C:/AX/cost-v2-regression-20261011.log`다. 실행 중 추가한 운영 인증 차단·답변 재시도·복사 이력·확정/제외/환불 선택 가드·규칙 저장·같은 자료의 자동 갱신 경합은 위 후속 표적으로 검증했다. 전체 회귀 수집 이후 추가한 테스트를 전체 결과에 포함했다고 주장하지 않으며 최종 HEAD 전체 회귀를 다시 수집하지 않았다. 건너뜀 3개는 비공개 Agoda 자료 의존 2개와 Windows chmod 권한 재현 1개다.

| 검토 범위 | 확인한 안전 경계와 인수 조건 |
| --- | --- |
| 운영 스키마와 진입점 | `Procfile`은 `run_candidate.py --environment production`을 사용한다. Windows 실행기는 `tools/launch_web_ledger.py`를 사용한다. 두 경로는 카드 스키마 `require`와 읽기 전용 사전 검사를 강제한다. 개발용 직접 서버는 운영 진입점으로 사용하지 않는다. 운영에 복사된 실행기 파일도 배포 전에 승인된 절차로 대조해야 한다. |
| 리허설과 복구 | 합성 검사와 기존 통과 근거에서 잘못된 DB, 원본 지문, 자동 증가 이력, WAL 복사 경쟁, 반복 적용, 호출자 트랜잭션과 실패 롤백을 확인했다. `--check-only`는 복제본에도 마이그레이션하지 않는다. 게이트는 다른 장부 모듈의 모든 DDL을 승인하지 않는다. 실제 복구 사본·복원·재시작은 미실행이다. |
| 원본·제외·환불·장부 | 원본 거래와 사용자 결정은 제외로 바꾸지 않는다. 기록·확정·환불 보호와 늦은 환불 보류를 유지한다. 저장 후 상태 읽기 실패는 저장 결과와 구분하며 같은 요청을 재실행해 중복 결정·장부 행을 만들지 않는다. |
| Google 인증·권한 | 지정 원본만 ADC 읽기를 허용하고 리다이렉트·공개 폴백을 거부한다. 초기 인증 실패와 부분 장애도 정상 스냅샷을 보존하면서 stale로 표시한다. 403의 알려진 요청 한도와 접근 거절을 구분한다. viewer 상세는 현재 권한·여행 매핑·선택 정본을 모두 요구한다. HTML·JSON은 `no-store`다. |
| 영수증·TSV | 카드 연결 근거·원문 금액·JPY 환산 조건·행별 보류·7열 순서를 유지한다. 복사 이력 쓰기 실패도 실제 클립보드 성공을 취소로 표시하지 않는다. 복사는 Google 기록 완료가 아니다. |
| 스케줄·파일·데모 | 동기화는 OS 잠금과 실패 지연을 사용하며 현재/이전 세대만 참조한다. 정리 대상은 형식과 메타데이터가 일치하는 생성 파일로 제한한다. 스케줄 예시는 비활성이고 익명 데모는 합성 플래그가 있는 입력만 허용한다. |

- 검토는 main 대비 변경 파일 64개 목록을 분류하고 위 고위험 제품 경로와 연결 테스트를 중심으로 수행했다. 이번 변경은 제품 코드 4개, 테스트 6개, 이 문서에 한정된다. 기술적으로 코드 통합 검토 후보이며 발견된 미해결 테스트 실패는 없다. 최종 코드 이후 문서만 변경했고 코드 검사를 추가하지 않았다. 테스트·문서 변경을 운영 실측 완료로 해석하지 않는다. main 병합과 운영 인수 완료는 여전히 승인되지 않았다.
- HOLD: 검증된 실제 복구 사본의 읽기 전용 진단·복원 리허설과 운영 DB 변경 승인, 실제 ADC/OIDC 계정·여행별 매핑 확인, 기록·확정 거래 제외 및 중복 의심 영수증 정책, 승인된 OCR 엔진, 운영 배포·스케줄·Render 승인이다. Google의 기존 링크 공유 제한은 인증 전환 검증과 별도 권한 승인이 필요하다.
- 사용자 `C:/AX/cost`의 변경 1개·미추적 4개와 stash `fbb1226e4659e4a2b75216cd556b51687db7d73e`를 보존했다. 운영 DB·Google 원본·공유 설정·스케줄·main은 변경하지 않았다.
- 회귀가 생성한 OTA 화면 캡처 두 개는 `.local-archive/regression-v2-20261011-192337`에 보관하고 해당 추적 파일만 실행 전 HEAD 상태로 복구했다. GitHub Actions와 등록된 deployments는 게시 전 각각 0개였으며 배포 설정을 변경하지 않았다.
- 다음 첫 명령은 `git -C C:/AX/cost-integration status --short`다. 이어 PR #85의 HEAD를 비교하고 새 실패 근거가 있을 때만 관련 표적을 재개한다. 운영 인수는 승인된 복구 사본 경로가 제공된 뒤 `tools/rehearse_cost_schema.py --source-copy <승인된 사본 경로> --confirm-isolated-copy --check-only` 진단부터 진행한다. 현재 운영 원본에 연결하지 않는다. 독립적인 새 결함은 이번 검토에서 더 재현하지 못했으며 완료한 검사를 관성적으로 반복하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--2026-10-11-실제-windows-저장소-후속-개발"></a>
#### 2026-10-11 실제 Windows 저장소 후속 개발

- 후속 수정: 보류 영수증의 원문 통화 표시, 잘못된 TSV ID·증빙·날짜의 행별 보류, 승인·답변 저장 응답의 이전 자료 복귀 방지, 같은 자료의 오래된 거래·제외 버전 거부를 추가했다. 이 문서 커밋까지 이번 실행의 신규 커밋은 19개다. 최신 HEAD는 PR #85와 `git rev-parse HEAD`를 따른다.
- 추가 실제 검사: TSV·카드 어댑터·회사 제외 통합·영수증 무결성 47 passed; 통화 표시 4 passed; 승인 후 선택 유지·기존 모바일/데스크톱 규칙 작업 3 passed; 카드 복사·규칙 인접 25 passed / 12 subtests; 핵심 업로드·답변·기록·출력 브라우저 9 passed / 2 subtests; 마지막 거래·제외 버전 가드의 카드 복사·핵심 브라우저 19 passed / 2 subtests. 새 실패는 재현 후 수정했고 미해결 테스트 실패는 없다. 검사 범위가 겹치므로 합산하지 않는다.
- 다음 첫 명령: `git -C C:/AX/cost-integration status --short`. 통과한 검사를 반복하지 않는다. 후속 검토가 필요하면 `webapp/card_flow.py`의 비동기 오류 상태 표시부터 조사하고, 새 재현이 있을 때만 수정한다. 운영 인수검증은 승인된 복구 사본의 `tools/rehearse_cost_schema.py --check-only` 진단과 실제 ADC/OIDC 계정 확인으로 이어간다. 원본 운영 DB와 Google 원본은 여전히 HOLD다.

- 작업 위치: `C:/AX/cost-integration`, 브랜치 `integration/cost-final`. 출발점 `b9ef086`, 중간 점검 코드 `a392d4e`까지 신규 커밋 12개였으며 이후 작업은 위 후속 수정에 기록했다. 정확한 최신 HEAD는 `git rev-parse HEAD`와 PR #85에서 확인한다.
- 스키마: 잘못된 board 모양과 복사 중 WAL 생성 거부, 자동 증가 이력 보존, 반복 리허설, 오류 코드만 출력, `--check-only` 진단을 구현했다. 운영 실행기 두 경로는 카드 스키마를 읽기 전용으로 사전 확인하고 이후 Store도 `require` 정책을 강제한다. 개발 기본 생성은 유지하며 운영 원본에는 연결하지 않았다.
- ADC: 초기 인증 실패도 마지막 정상 행을 유지하면서 stale 상태를 게시한다. 영구 토큰 갱신 실패·일시 장애·403 요청 한도를 구분하고 응답 정리 오류가 비밀을 노출하지 않도록 수정했다. 부분 장애와 복구를 실제 세대 파일로 검사했다.
- 영수증: 카드에 연결된 원래 식별 근거를 유지해 상호·날짜 수정이나 카드 일시 소실 후 현금 재계상을 거부한다. 보류 입력과 이미지 영역을 보존하고 늦은 카드 연결의 보류를 이력으로 옮긴다. 반복 수정은 확인과 이력을 중복 변경하지 않는다.
- UI: 바뀐 선택과 맞지 않는 규칙 제안·카드 자료·자동 갱신 응답을 버린다. 카드 복사의 중복 클릭과 오래된 자료의 클립보드 쓰기를 막고 영수증 복사 중 여행 선택을 잠근다. 오류·빈 결과 후 입력과 버튼은 복구한다.
- 실제 검사: 시작 표적 29 passed; 초기 스키마·리허설 13 passed; Store 영향 카드 파이프라인·카드 웹·실행기 인접 708 passed / 39 subtests; 게이트 9 passed와 이후 WAL 동시성 1 passed; ADC·정본·스케줄 66 passed와 추가 부분 장애 복구 1 passed; 마지막 ADC 13 passed; 마지막 리허설 13 passed; 실행기 71 passed / 16 subtests; 영수증 무결성·브라우저 49 passed / 12 subtests; 규칙 HTTP·브라우저 15 passed / 12 subtests; 최신 카드·영수증 복사 브라우저 37 passed / 12 subtests. 중간 겹치는 범위는 합산하지 않는다. 새 재현 실패는 수정했으며 남은 실패는 없다.
- 과거 전체 회귀 3035 passed / 3 skipped / 2452 subtests는 `189b804` 시점 증거다. 영향 없는 전체 회귀·OTA 재대사·운영 스모크를 반복하지 않았다. 최신 HEAD 전체 회귀로 주장하지 않는다.
- 사용자 `C:/AX/cost`의 변경 1개·미추적 4개와 stash `fbb1226e4659e4a2b75216cd556b51687db7d73e`를 확인하고 보존했다. 실제 SQLite·운영 설정·Google 원본·공유권한·스케줄러·main은 변경하지 않았다.
- HOLD: 검증된 실제 복구 사본과 운영 마이그레이션 승인, 실제 ADC/OIDC 계정과 여행별 매핑 확인, 기록·확정 거래 제외 및 중복 의심 영수증 정책, 승인된 OCR 엔진, 운영 배포·스케줄 활성화·Render 이전 승인.
- 통화 표시와 TSV 입력 형식 검토는 위 후속 수정으로 처리했다. 따옴표의 Google 붙여넣기 해석을 추정해 TSV 규격을 다시 작성하지 않았다. 실제 Google 붙여넣기는 이 세션에서 수행하지 않았다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--2026-10-11-후속-세션--안전한-추가-구현"></a>
#### 2026-10-11 후속 세션 — 안전한 추가 구현

- 최신 통합 작업은 **PR #85 / integration/cost-final**에 계속 커밋했다. 정확한 원격 HEAD는 GitHub PR에서 다시 확인한다. handoff/session-20261011-cost는 문서용 별도 브랜치다.
- **DB 리허설 신규 구현:** tools/rehearse_cost_schema.py + tests/card_pipeline/test_schema_rehearsal.py + docs/schema-rehearsal.md. **검증된 복구 사본**을 별도 임시 파일로 복제한 뒤 Store DDL을 적용하고 입력 파일 불변, 과거 스키마/행 지문 불변, 회사 제외 테이블 설치를 검사한다. 빈·잘못된 DB, WAL, 해시 불일치 등은 거부한다. 실제 운영 DB 연결/변경은 없음.
- **Google 인증 읽기 선택형 구현:** app/google_adc_export.py + tests/card_pipeline/test_google_adc_export.py, tools/google_authority_sync.py의 --google-auth adc. 허용된 메인/보관 파일만 Google Drive API의 읽기 전용 내보내기를 사용하고, 외부 리다이렉트·무인증 폴백을 하지 않는다. 운영 자격증명은 설정·실행하지 않았다.
- **합성 시험:** 이 세션의 별도 격리 Python 하네스(실제 repo 전체가 아닌 핵심 Store 계약 대역)에서 schema rehearsal 7개, Google 인증 adapter 7개가 통과했다. Google 계정 인증 실측, PR HEAD의 실제 저장소 pytest와 전체 회귀는 **실행하지 않음**. 이전 전체 회귀 3035 passed는 기존 HEAD 근거만이다.
- **실제 Google 읽기 전용 실측:** 연결된 Google Drive에서 보관 26개/메인 43개 탭, 양식_rev의 수입·지출 B:H 헤더·합계 수식과 실제 여행 3개 탭 헤더를 확인했다. 계정/파일 권한은 변경하지 않았다. 현재 양 원본에 **anyone/reader, allowFileDiscovery=false**가 있어 링크 보유자 열람 위험이 확인됐다. 자세한 상태는 docs/google-authority-sync-readiness.md 9절 참고. 제한 전 인증형 읽기와 사업 권한 승인이 필수다.
- **Windows 환경:** 이 세션 도구에서는 C:/AX/cost 및 C:/AX/cost-integration에 접근할 수 없으므로 로컬 dirty·stash·운영 프로세스는 현재 상태 재검증 불가. 접근하거나 변경한 적 없다. 사용자/운영 파일 삭제, main 병합, 서버 재시작, 스케줄러 활성화, 운영 DB 마이그레이션, Google 원본 수정, 외부 실정보 공개는 수행하지 않았다.
- **다음 실제 코드 검증 명령:** 격리 worktree에서 HEAD/dirty 확인 후 `python -m pytest tests/card_pipeline/test_schema_rehearsal.py tests/card_pipeline/test_google_adc_export.py tests/card_pipeline/test_sync_schedule.py -q --tb=short`로 새 코드와 인접 경로를 한 번 검증한다. 추가 결함이 있으면 표적 수정. 그 다음 승인된 복구본 스키마 리허설·실제 ADC/장부 접근 실험만 별도 승인과 함께 수행한다.


- 작업 위치는 `C:/AX/cost-integration`, 브랜치는 `integration/cost-final`이며 해당 기록 시점의 코드 HEAD는 `a6cd496`이었습니다. 정확한 HEAD와 미커밋 상태는 `git status --short`와 `git rev-parse HEAD`로 확인합니다. 사용자 작업 위치 `C:/AX/cost`의 변경과 미추적 `webledger.work.operator.sqlite.checkpoint.json`은 보존하며 게시하지 않습니다.
- 이번 요청에서 viewer의 여행 권한과 선택된 정본 source를 함께 검사하도록 수정했습니다. 정본 미선택, 선택되지 않은 사본, 선택된 사본 소실, 철회 후 직접 상세 URL은 거부합니다. owner는 남은 사본을 명시적으로 다시 선택할 수 있습니다.
- `Store` 생성의 자동 DDL을 저장점으로 묶어 중간 실패 전체 롤백과 호출자 트랜잭션 보존을 구현했습니다. 첫 `CardFlow` 조회도 선택된 DB의 신규 테이블 생성 시점일 수 있습니다. 운영 DB에는 연결하거나 적용하지 않았습니다.
- 회사 경비 제외 통합 테스트는 미리보기·확정·TSV·되돌리기·원문과 사용자 결정 보존·환불 보호·DB 오류 후 동일 요청 재시도를 검증합니다. 제외 후 별도 파일의 환불 도착도 단독 기록과 TSV를 차단합니다.
- 표적 검증은 스키마와 카드 인접 경로 96 passed / 39 subtests passed, 첫 CardFlow 생성 1 passed, 정본·서명 HTTP 경로 52 passed / 28 subtests passed, 회사 제외 통합 4 passed와 추가 환불 1 passed입니다. 시점과 범위가 다르므로 합산하지 않습니다.
- 전체 회귀는 `189b804`에서 `python -m pytest -q --tb=short`로 시작해 3035 passed, 3 skipped, 2452 subtests passed, 실패 0으로 끝났습니다. 실행 시간은 1328.21초이며 로그는 `C:/AX/cost-full-regression-20261011.log`에 있습니다. 건너뜀은 과거 비공개 Agoda 자료 의존 검사 2건과 Windows chmod 권한 재현 검사 1건입니다. 실행 중 추가한 사본 소실 수정과 환불 테스트는 위의 별도 표적 결과로 검증했습니다. 변경되지 않은 전체 범위를 다시 실행하지 않았습니다.
- 전체 회귀가 생성한 OTA 화면 캡처는 `.local-archive/regression-20261011`에 보관하고 추적 파일은 실행 전 상태로 복원했습니다. 사용자 작업 트리는 보존했습니다. main 대비 변경은 54개 파일입니다.
- 이번 코드 작업은 세 커밋 `189b804`, `5dc47cf`, `a6cd496`입니다. PR #85의 최신 SHA와 결과는 GitHub 본문에 기록합니다. 문서 커밋이 추가되므로 정확한 최종 HEAD는 `git rev-parse HEAD`로 확인합니다.
- 다음 세션의 첫 명령은 `git -C C:/AX/cost-integration status --short`입니다. 새로운 결함 근거 또는 아래 운영 승인에 따라 재개하며, 현재 통과한 검사를 이유 없이 반복하지 않습니다. 운영 승인 전 수행할 독립 코드 결함은 이번 범위에서 더 발견하지 못했습니다.
- 남은 운영 HOLD는 main 병합, 배포·재시작, 자동 스키마 생성을 포함한 운영 DB 변경 승인과 복구 사본 검증, 실제 계정·여행 매핑 검증입니다. 이미 기록·확정된 거래의 신규 제외 정책과 별도 영수증으로 인정할 중복 의심 후보 정책도 별도 결정이 필요합니다. 승인된 로컬 OCR 엔진이 없어 수동 입력을 유지합니다. 실제 Google 원본 쓰기와 외부 OCR 전송은 수행하지 않습니다.

---

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md"></a>

## autonomous-implementation-playbook

통합 전 경로: `docs/archive/ota-legacy-20261023/autonomous-implementation-playbook.md`

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--cost-장시간-자율-구현-실행계획"></a>
### COST 장시간 자율 구현 실행계획

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--현재-적용되는-검증-정책"></a>
#### 현재 적용되는 검증 정책

2026-10-11 사용자 변경에 따라 [AGENTS.md의 검증 정책](product-and-handoffs.md#src-agents-md--검증-최소화재검증-금지-작업-우선-원칙)을 우선 적용한다. 기본 흐름은 **DISCOVER → IMPLEMENT → TARGETED TEST → REVIEW → COMMIT → NEXT**다. 매 수정에는 표적 검사와 필요한 인접 통합 검사만 수행하며, 전체 회귀는 병합·배포 전 검증, 광범위한 아키텍처 변경, 구체적인 회귀 위험이 있을 때만 추가한다. 과거 실행 기록은 재실행 지시가 아니다. 운영 승인 경계는 그대로 유지한다.

> 작성 기준: 2026-10-11. 대상: `6Soo/cost`. 이것은 **실제 실행 작업자용 상세 runbook**이며 운영 배포·기존 장부 변경·개인정보 공개 허가는 아니다.
> 목표: 사용자가 자리를 비운 동안 가능한 많은 **기능 구현, 표적 검증, 검토 가능한 PR**을 완료한다. 계획·보고만 반복하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md---최우선-실행-규약-판단-보류--구현-중단-2026-10-11-강화"></a>
#### ⚠ 최우선 실행 규약: 판단 보류 ≠ 구현 중단 (2026-10-11 강화)

**이 절은 후속 0~16절보다 우선한다. 이전 실행에서 A/B/D/E/F/I 중 작은 유틸만 구현하고 C/G/H 전부를 BLOCKED로 종료한 사례를 재발시키지 않기 위한 지시다. 회계·보안·배포 금지는 결코 완화하지 않는다.**

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--1-필수-루프--split--hold--switch--implement--revisit"></a>
##### 1. 필수 루프 — SPLIT → HOLD → SWITCH → IMPLEMENT → REVISIT

1. 어떤 판단·권한·실제 엔진·브라우저 문제가 생겨도 **세션 전체 또는 기능 전체를 즉시 BLOCKED로 종료하지 않는다.** 문제와 직접 연결된 최소 동작만 HOLD한다.
2. 그 기능의 미차단 하위 작업을 나누어 **실제로 동작하는 최소 코드와 표적 테스트까지 구현**한다. 예를 들어 최종 viewer 매핑이 미정이어도 owner 전용 화면, 경로·API 인증 차단, 합성 계정 테스트는 만들 수 있다.
3. 같은 기능에서 안전한 하위 작업마저 없다면 **다른 독립 작업으로 즉시 전환**한다. 사용자 답변을 기다리지 않는다. 분석·계획·TODO만 늘리지 않는다.
4. 매 PR 완료 직후 **다음 미완료 작업 코드를 실제로 수정/테스트**한다. 단순히 '다음 작업을 하겠다'는 메시지만 남기고 종료하지 않는다.
5. 다른 작업을 끝낸 뒤 이전 HOLD가 현재 코드나 새 정보로 풀릴지 한 번 재검토한다. 승인/인증비밀/실데이터 공개 등 사용자만 결정 가능한 동작만 남겨 둔다.
6. **최종 보고는 안전하게 가능한 모든 독립 하위 작업을 시도·구현한 뒤에만 제출**한다. 환경 종료·호출/토큰 한도 등 현실적 제약은 예외이며 정확한 다음 실행 위치를 남긴다.

**BLOCKED는 기능 이름이 아닌 최소 결손에만 붙인다.** 예: 'C 전체 BLOCKED' 금지, 'C owner 합성 UI DONE / viewer용 실제 탭 매핑 HOLD / 운영 로그인 E2E 미검증'으로 보고한다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--2-자주-등장한-차단-사유와-강제-우회-경로"></a>
##### 2. 자주 등장한 차단 사유와 강제 우회 경로

| 차단 사유 | HOLD할 최소 부분 | 반드시 계속 구현할 부분 |
| --- | --- | --- |
| Google 탭과 COST tab_id 매핑 불명 | 확인되지 않은 실제 viewer 권한 연결 | 합성 owner 장부 UI·HTTP 라우트, 서버 기본 거부, 명시적 매핑 어댑터/fixture/권한 테스트. 기존 ID와 원본 규칙을 먼저 조사 |
| 기존 item/description ↔ Google C/D 의미 불명 | 근거 없는 행별 자동 매핑 | 기존 webapp/sheets_export.py·app/ledger.py·source_merchant·분류 item을 조사. Google C=지급처, D=분류에 대응하는 **검증 가능한 거래만** 어댑터로 TSV+기존 UI 복사 구현; 모호한 행만 HOLD |
| 실제 로그인 브라우저 연결 불가 | 운영 로그인 E2E 검증 | 로컬 synthetic 계정·HTML/HTTP 테스트, 390px/1440px용 UI 템플릿 및 비운영 브라우저 가능 범위 검증 |
| OCR 엔진 없음 | 실제 이미지 추론 엔진 호출 | 합성 A4 여러 영수증 입력, 지역/개별 영수증 후보 편집·확인, 중복 검토, 비용 후보→TSV 통합 |
| 로컬 AI 엔진 미확인 | 실제 AI 추론 및 외부 전송 | 결정론적 최소 명령 파서 또는 mock 제안 엔진, 검토 UI, 사용자 승인·변경 이력 및 미확정 후보 적용 테스트 |
| 데모 동률 판단 미정 | 미확정 동률의 실제 공개 순위만 | 동률 없는 합성 상위 3건, 자동 교체, 안전한 익명 payload, 로컬 합성 페이지·API·보안 검사 |
| Google 공유 설정 변경/인증키 없음 | 실제 공유권한 변경·신규 인증키 발급 | 기존 읽기 경로 분리, 인증된 Google 조회 어댑터의 합성 구현, 무권한 오류 표시, 기존 읽기-only 기능 테스트 |
| PR 종속/리베이스 충돌 | 충돌 브랜치 변경만 | 다른 브랜치와 무관한 D/G/H/I의 코드 작업. 강제 push·사용자 dirty tree 삭제 금지 |

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--3-이번-실행에서-반드시-다시-찾아서-진행할-구체적-잔여-작업"></a>
##### 3. 이번 실행에서 반드시 다시 찾아서 진행할 구체적 잔여 작업

**시작 전에 실제 최신 PR/코드 상태를 확인한다.** 이전 관찰에는 #71, #73, #74, #75, #76, #77이 open이었으며, 이미 구현된 부분을 재작성하지 않는다.

1. **P0 #73: 두 파일 스냅샷 일관성.** 실제 개인정보가 담긴 rows JSON과 집계 JSON을 순차 교체하면 중간 실패 시 세대가 달라진다. 공통 generation ID·원자적인 manifest 전환 또는 복구 경로를 구현하고 실패 주입 테스트. 두 JSON을 비로그인 API에 직접 노출하지 않는다. '공개 스냅샷'에도 여행명·수익 합계가 있다.
2. **P0 #71: 회계·신원 검증.** 오류 합계와 유효 합계를 분리하고 보관 사본/연도 없는 네 자리 이름의 동일 여행 확인이 모호하면 공개 후보 HOLD. 원본 Google 자동 수정 금지.
3. **P1 #74: 실 카드 거래→Google 지출 7열 연결.** 순수 TSV 생성기는 존재한다. 실제 record의 검증된 가맹점·분류·거래일·금액을 어댑터로 연결하고 기존 검토 UI에 복사 진입점 추가. 근거 부족한 거래만 HOLD. C 지급처를 무조건 기존 item으로, D 분류를 무조건 description으로 매핑하지 말 것.
4. **P1 C/E: 실제 인증 통합 이전 owner 전용 Google 장부 페이지.** 합성/비운영 자료로 여행 목록·행 상세·금액·동기화 오류·중복 대조 화면을 만들고, 서버에서 미승인 viewer/익명 조회는 차단. 안정적 탭 ID 대응표는 owner 승인까지 실제 권한 부여만 HOLD.
5. **P1 #75: 합성 데이터 기반 데모 라우트·페이지.** 현재 함수는 순위/금액만 산출한다. 실제 개인정보가 노출되지 않는 허용 필드 projection과 synthetic UI/HTTP 검증까지 구현. 실Google 자료를 누구나 접근 가능한 URL에 게시하지 말 것.
6. **P2 G: OCR 엔진 미확인이어도 A4 여러 영수증을 개별 후보로 처리하는 업로드·수정·검토·TSV 경로를 합성 데이터로 완성.** 실제 OCR 엔진만 HOLD.
7. **P2 H: AI 엔진 미확인이어도 기존 분류 규칙과 연결할 최소 메시지 해석·승인·적용·감사·HOLD 흐름을 합성 데이터로 구현.** 원본 거래값/사용자 확정을 AI가 직접 수정하는 기능 금지.
8. **P2 I: #77 문서 작성으로 단계 종료하지 말 것.** 운영 부작용 없는 단일 실행 잠금·실패 시 지연 상태·비활성 scheduler 예시를 코드/테스트로 준비. 실제 운영 스케줄러 활성화 금지.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--4-보고-및-종료의-엄격한-조건"></a>
##### 4. 보고 및 종료의 엄격한 조건

- 작업 하나가 BLOCKED라면 **왜 바로 옆의 안전한 하위 작업도 구현할 수 없는지** 판단하고 가능한 하위 작업은 실제 구현해라.
- 합성·모의 데이터만으로 동작 검증할 수 있는 기능은 **브라우저 로그인, 실제 OCR, AI, 실제 계정, 운영 배포가 없어도** 최대한 구현한다. 단, 동작하지 않는 스텁과 TODO만 늘리는 것은 성과가 아니다.
- 최종 보고 전 위 1~8 각각을 DONE / 하위 기능 DONE+일부 HOLD / 실제 전체 BLOCKED 중 하나로 분류하고, **DONE을 주장한 항목에는 구현 파일·표적 테스트·PR 링크**가 있어야 한다.
- 긴 진행 상황 보고보다 코드 작성에 시간을 쓰고, 체크포인트에 현재 PR head/다음 파일/다음 구체적 명령/미결 사항만 짧게 남긴다.
- 실자료 유출·원본 회계 수정·운영 DB/Google 쓰기·무단 공개 배포처럼 안전을 깨야만 가능한 동작은 진행하지 않는다. **그 동작만 HOLD하고 다른 코드를 개발한다.**
- '이제 질문에 답해 달라'로 종료하지 않는다. 유효한 다른 개발 작업이 실제로 남았다면 이를 먼저 실행한다. 실제 도구/사용량/시간 한도로 막힌 경우에만 정직하게 종료하고 정확한 재개 지점 기록.

---

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--0-최우선-실행-원칙"></a>
#### 0. 최우선 실행 원칙

**코드 조사 → 최소 변경 → 표적 테스트 → diff 검토 → 결함 수정 → 커밋/PR → 다음 안전한 독립 작업**을 반복한다. 사용자 답변 없이 할 수 있는 일은 끝까지 한다. PR 하나를 만들었다고 멈추지 않는다.

- **허용:** 격리 worktree 개발, 합성 테스트, 읽기 전용·최소 메타 실측, 코드 리뷰, 기능별 PR 및 브랜치, 안전한 개발용 UI 검증.
- **금지:** `main` 자동 병합, 운영 배포/재시작, 스케줄러 활성화, 운영 SQLite·OTA DB 쓰기/migration/reset, Google 원본 쓰기·이동·수식 수정, 실제 회계자료·개인정보의 인터넷 공개, 무단 외부 AI 전송, 원격 강제 push, 사용자 dirty tree 삭제·reset·stash·clean.
- PR이나 preview CI가 **실제 자료를 공개하거나 자동 배포**할 수 있으면 이를 확인하기 전 PR 트리거를 중단하고 격리 로컬 작업을 계속한다.
- 명세 미정 부분은 사용자 결정을 가장하지 말고 HOLD하고 다른 독립 작업으로 넘어간다. 개인 데이터·회계 신뢰성·권한·운영 변경에 위험이 있으면 해당 단계만 차단한다.
- 컨텍스트 압축, 세션 재개, 호출 한도와 로컬 PC 절전 등 실행 한계는 우회할 수 없는 실제 제약이다. 작업을 재개할 수 있게 기록하며 무한 백그라운드 실행을 약속하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--1-권위와-시작-시-재확인"></a>
#### 1. 권위와 시작 시 재확인

다음 순서로 저장소의 실제 파일을 읽고 해당 파일이 없으면 정직하게 보고한다.

1. `AGENTS.md`, `README.md`. `CLAUDE.md`는 **해당 작업환경에 있을 때만** 참고한다(2026-10-11 GitHub main에는 없었음).
2. `docs/target-workflow-google-authority.md`, `docs/google-workbook-layout.md`, `docs/access-and-top3-demo.md` — 최신 사용자 확정 사항.
3. `docs/business_rules.md`, `docs/card_downloads.md`, `docs/architecture.md` — 거래 무결성과 현재 엔진.
4. `docs/operations.md`, `docs/session_handoff.md` — 운영 상태 및 이전 체크포인트. 과거 수치/서버 PID가 지금도 참이라고 추측하지 않는다.

작업 시작 직전에 `git status`, 원격 최신 `main`, worktree 목록, 충돌·미커밋 파일, 열린 PR을 확인한다. 과거 보고상 로컬 `main`은 원격보다 뒤처졌고 사용자 dirty tree가 있었으며, 별도 `C:/AX/cost-wt-readonly`에서 `feature/google-authority-readonly-sync`와 PR #71을 작업했다. **전부 재조회 필요**.

PR #71: https://github.com/6Soo/cost/pull/71 . 선행 작업을 버리지 말고 가장 먼저 최신 head·변경 파일·실제 테스트를 확인한다. 누군가 이미 수정했다면 중복 작업 대신 차이만 처리한다.

**작업 시작 전에 내부적으로** 각 단위의 `목표 / 변경 행동 / 직접 영향 범위 / 필요한 한 번의 검증 / 완료 조건`만 정한다. 긴 분석 메모보다 실행에 시간을 쓴다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--2-회계제품-정책-불변조건"></a>
#### 2. 회계·제품 정책 불변조건

- Google 메인과 과거 보관의 여행별 시트가 **최종 회계 정본**이다. COST→Google API **자동 쓰기 금지**. 수입·은행이체는 사용자가 Google에 직접 입력; 카드·현지영수증은 COST 검토/복사 후 사용자가 Google에 붙여넣는다.
- 공식 신규 여행 양식은 `매출자료 양식_rev` 하나. 수입 헤더 B:H와 지출 헤더 B:H는 유지하지만 데이터 행의 절대 번호는 고정하지 않는다. 예전 레이아웃을 위한 범용 호환·자동 수식 정비·양식 변환기 금지.
- 지출 C열 `항목`=결제처·가맹점·지급처, D열 `내용`=숙박비·항공료 등의 분류. **실제 카드/영수증 결제 한 건→지출 한 행**, 다른 결제 묶음 금지. 법인카드 매입 영수증은 그 거래의 증빙이며 두 번째 비용이 아니다.
- 지출이 취소·환불·부분환불된 원거래 관계, 거래 ID, 사용자가 이미 확정한 배정, OTA 신원·일정 권위는 보존한다.
- 개인카드 사후 상환 이체 중복 방지는 사용자가 Google 내역을 보고 수동 관리한다. 은행 이체 자동 정산/대사 기능을 새로 만들지 않는다.
- 일본 현지 **현금·개인카드** 비용 환산 1 JPY=10 KRW. 법인카드 실제 KRW 매입/수수료는 보존하고 이 임의 환산으로 덮지 않는다.
- 여행의 **마감 완료**는 해당 실제 여행 시트를 메인에서 **보관 장부로 이동**한 경우. 보관 확인→마감, 메인에만 존재→미마감. 양쪽 동시 존재→마감 완료지만 회계 정본은 **메인 우선 + 확인 대상 + owner 수동 조정**. 단 한 사본만 집계한다.
- 여행명이 유사하다거나 `의 사본`이라는 말이 붙는다고 동일 여행으로 자동 간주하지 않는다. 연도와 실제 여행 identity가 모호하면 HOLD.
- Google 표시 합계와 행 계산이 다르거나 수식 범위/캐시가 불명확하면 플래그로 드러낸다. 계산 불가를 0원이나 확정 순수익으로 꾸미지 않는다. 원본 Google 수식 임의 수정 금지.
- 전체 장부 기본 접근 owner 전용. 다른 계정은 owner가 **여행별 읽기 권한**을 지정했을 때만 조회.
- 비로그인 공개 데모 목표: **마감 완료된 실제 여행 중 회사수익인식 KRW 상위 3건**, Google 정상 동기화 시 자동 재선정, 실금액 유지, 이름·닉네임·결제식별 정보 등 **서버 측 비식별화**. 실제 자료를 인터넷으로 공개하거나 운영 배포하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--3-pr-전략--단계-의존성"></a>
#### 3. PR 전략 / 단계 의존성

| ID | 우선 | 작업 | 산출물 | 선행 |
| --- | --- | --- | --- | --- |
| A | P0 | PR #71 무결성 결함 수정 | PR #71 수정 + 회귀 테스트 | 즉시 |
| B | P0 | Google 정본 행 단위 읽기 계약 | 새 PR, 안전한 내부 데이터 투영 | A |
| C | P1 | 확정 장부 웹 화면·정본 선택 | 새 PR, owner UI | B |
| D | P1 | Google 7열 TSV·지출 검토 연계 | 새 PR, 복사 UX | 기존 카드 엔진; B와 일부 독립 |
| E | P1 | 기존 owner/viewer 권한의 새 조회 통합 | 새 PR, 권한 경계 테스트 | B/C 인터페이스 |
| F | P2 | 실데이터 비공개·합성 공개 데모 구현 | 새 PR, 익명화/랭킹 검증 | A/B/E 인터페이스 |
| G | P2 | 일본 A4 다중 영수증 OCR | 새 PR, 합성 OCR/검토 | 기존 업로드·D |
| H | P3 | 자연어 거래 규칙 수정 | 새 PR, 승인·감사·HOLD 검증 | 기존 규칙 엔진 |
| I | P3 | 주기 실행·Render 이전 **준비만** | 비활성 설정/런북 PR | A/B 안정화 |

A를 먼저 수행한다. 의존 기능은 선행 PR의 head에서 개발하거나 명확히 의존 PR을 명시한다. B/C가 막히면 D/G 등 안전한 독립 작업을 추진한다. 구현 불필요한 이미 있는 기능은 재작성하지 말고 실제 차이만 보완한다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--4-a--pr-71-결함-수정-최우선"></a>
#### 4. A — PR #71 결함 수정 (최우선)

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--여행-identity--보관-판정"></a>
##### 여행 identity / 보관 판정

- `app/google_authority.py`의 `COPY_SUFFIX` 등 이름 정규화가 여행을 조용히 동일화하지 않도록 수정한다. 원본 파일/탭명/출처와 안정된 여행 identity를 구분한다. 임의 유사도 매칭이나 범용 여행 신원 플랫폼 추가 금지.
- 특정 원본의 사본이 동일 여행이라는 **검증 가능한 연결**이 없다면 후보/양쪽 중복을 확인 대상으로 둔다. 이름만 비슷한 다른 연도 여행을 병합하지 않는다.
- 메인/보관에 실제 동일 여행이 확인된 경우에만 `closed` + 메인 정본 우선 + 중복 한 번 집계. archive만 있으면 closed, 메인만 있으면 open. 보관 스냅샷이 실패·stale이면 최신 마감이라고 주장하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--합계파서"></a>
##### 합계·파서

- Google 합계 셀(`sheet_total`)과 해당 거래 행 합계(`row_sum`), 채택/검증 가능 금액, 플래그를 구분해 보존한다.
- `TOTAL_MISMATCH`, `TOTAL_RANGE_MISMATCH`, `TOTAL_FORMULA_UNCLEAR`, `TOTAL_NOT_CACHED`, `AMOUNT_INVALID`, `FORMULA_ERROR` 등은 개별 의미를 유지한다. 총합 수식이 유효하지 않을 때 행 합계를 **검증된 확정 수익**으로 조용히 대체하지 않는다.
- 실측 사례: 메인 `0630_오제`는 지출 SUM(H47:H75)가 H76의 3,472,049원을 포함하지 않는다. 보관 `0413_…의 사본`에는 2,200원 차이가 보고됐다. 오류 플래그로 보고하고 Google 원본은 수정하지 않는다.
- `SUM(H8)` 단일 셀, 지출 합계 수식 이후의 텍스트, 헤더를 포함하는 SUM 구간, 수입 H열 내부 계산 등 공식 양식 내 예외만 최소 처리한다. 구형 시트 자동 호환은 범위 밖이다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--스냅샷-안전"></a>
##### 스냅샷 안전

- 메인/보관 각각 `checked_at`, `last_ok_at`, `status`, `stale`, 지문·원본 변경 여부를 구별한다. 일부 실패 시 마지막 정상 스냅샷을 보존하되 이번 정상 갱신과 섞지 않는다.
- 빈 다운로드/HTML 로그인·접근 거부/파싱 실패/스냅샷 손상/재시도에서 빈 값으로 덮어쓰지 않는다. 공개 순위에 오래된 확정값을 최신으로 위장하지 않는다.
- 파일은 저장소 외부, 원자적 쓰기, 최소 JSON 메타데이터; 개인정보·원본 거래행/카드 정보는 이 단계에 저장하지 않는다.

**A 합격:** 기존 18개 표적 테스트를 보존하고 (a) 다른 연도/사본 이름 충돌 (b) 동시 양쪽 존재 (c) 수식 오류·범위 누락·캐시 누락 (d) 0원과 None (e) 부분 읽기 실패 (f) 빈/손상 스냅샷 관련 테스트를 추가. PR #71을 업데이트하되 **main 병합하지 않고 B로 이동**.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--5-b--google-확정-장부-거래-행-읽기"></a>
#### 5. B — Google 확정 장부 거래 행 읽기

- 공식 수입 B:H: 거래일자/이름/닉네임/예약금/잔금/추가금/금액(원). 공식 지출 B:H: 거래일자/항목/내용/기간/예약번호/증빙유형/금액(원). C 지급처와 D 분류의 의미를 혼동하지 않는다.
- 템플릿 B5:H5, B21:H21은 **현재 기본 양식의 관측치**이며 모든 실여행의 고정 행번호가 아니다. 헤더·동적 행 삽입·합계 수식에서 범위를 구한다.
- 거래행에 원본 파일·시트·행 위치와 실제 값/검증 상태를 연결한다. 개인식별 필드는 서버 비공개 데이터 경로에만 보존하고 화면·API마다 최소 필드로 내려보낸다. GitHub·로그·외부 모델에 원문 전송 금지.
- 합계와 거래별 실제 값 차이를 대조하고 확정/미확정 분리. 구형 양식은 `LAYOUT_NOT_STANDARD`로 표시하고 자동 변환하지 않는다.
- OAuth/권한/Google 조회 기존 코드가 있으면 가능한 한 재사용하며 새로운 라이브러리나 DB를 필요 없이 추가하지 않는다.

**B 합격:** 합성 워크북에서 행별 정확성·B:H 계약·변동 행·음수 환불·출처·합계·오류·중복 정본을 검사. 읽기 전용이며 운영 DB를 수정하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--6-c--기존-cost-웹-ui와-연계"></a>
#### 6. C — 기존 COST 웹 UI와 연계

- 기존 UI shell/장부/로그인 재사용. owner: 여행 목록, 선택한 여행의 Google 확정 수입·지출 행, 합계·회사수익, 출처, open/closed, 동기화 오류·검증 HOLD.
- 작업 중 카드/영수증 후보와 **Google 확정 장부**는 제목과 금액 영역을 명확히 구분. 아직 Google에 없는 비용을 확정수익에 혼합하지 않는다.
- 동일 여행 메인/보관 동시 존재 시 메인 기본 정본으로 보여 주고 owner가 두 사본 비교 후 정본을 내부적으로 선택할 수 있게 한다. 선택·변경 이력을 유지하되 Google에 기록하지 않는다.
- 모바일 390px와 PC 1440px에서 핵심 조회·정본 선택을 최소 1회 확인; 현재 화면을 전면 재작성하지 않는다.

**C 합격:** 원본별 금액·출처·중복 차이, owner/일반계정 경계, UI 오류 표시, 선택한 정본만 집계, 변경 복구 표적 검증.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--7-d--카드영수증-지출-검토-및-google-7열-복사"></a>
#### 7. D — 카드·영수증 지출 검토 및 Google 7열 복사

- 기존 KB 카드 대사·분류·환불·취소·OTA 연결·미확정 검토 경로를 **재사용**. 동일 실제 거래 1건당 Google 지출 1행. 승인 증거와 법인카드 영수증을 별도 비용으로 기록하지 않는다.
- TSV는 B 날짜, C 지급처(`항목`), D 비용분류(`내용`), E 기간, F 예약/증빙번호, G 증빙유형, H 원화 금액의 7열. 사용자 수입/이체 기입/합계 수식 셀은 침범하지 않는다.
- 미리보기에는 대상 여행, 행수, 합계, 원화 단위, HOLD 거래, 레거시 비표준 여부 표시. 구형 장부에 무조건 붙여넣기 허용 금지.
- 복사는 사람의 클립보드만 변경; Google API 자동 기록 없음. 실제 반영 여부는 이후 Google 읽기에서 검증 가능한 범위만 표시하고 거래 ID가 없어 동일성 모호하면 HOLD.

**D 합격:** 지출 1건=1행, 취소/환불, 법인카드 영수증 중복, 반복 업로드, 정확한 7열 순서와 서식, 안전한 복사/미반영 상태 표적 테스트.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--8-e--계정별-열람-권한"></a>
#### 8. E — 계정별 열람 권한

- `webapp/access_control.py`의 owner/viewer·여행 allowlist·회수·활성 상태를 재사용. owner 전체, viewer는 승인된 여행별 확정 장부만 조회. 신규계정 기본 차단.
- HTML/JSON/API/검색/export/자동 새로고침/캐시 및 타 여행 직접 URL에 **매 요청 서버 권한 검증**. 클라이언트에서 메뉴만 숨기는 방법은 금지.
- viewer에게 내부 카드 원본, 영수증 사진, AI 대화, 개인정보 포함 관리 메모·비밀값은 제공하지 않는다. 권한 철회 후 이전 URL/캐시 접근도 차단.

**E 합격:** owner/viewer/익명 격리, 여행 권한 부여·철회, 직접 URL·다운로드 우회 차단, 비인가 제목·합계 유출 부재를 합성 계정으로 검증.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--9-f--비로그인-데모-실데이터-비공개-구현"></a>
#### 9. F — 비로그인 데모 (실데이터 비공개 구현)

- **안전한 서버 측 데모 projection**에서만 HTML/API를 생성한다. 보관 시트 이동으로 `closed` 확인된 여행만, 정본 순수익 KRW 내림차순 상위 최대 3건, 성공한 Google 동기화 후 자동 재선정.
- 두 파일에 동일 여행이면 한 번만 계산; 식별 모호·합계 오류·비표준/계산 불가·개인정보 마스킹 실패 후보는 제외. 3건 미만은 가짜 여행으로 보충하지 않는다. stale이면 마지막 안전 스냅샷/확인 시각으로 표시.
- 실명/닉네임/전화/이메일/주소/계좌/카드/예약번호/여권/거래ID/원본 Google 링크/메모/영수증 이미지와 지급처·자유텍스트에 섞인 신원을 제거한다. **브라우저에 원문 JSON을 전송한 후 별표 처리 금지**.
- 여행명·날짜·드문 지급처만으로 간접 식별 가능하면 일반화·제외. 실제 수익 숫자는 위변조하지 않는다. 상세 내역을 제외한 금액 합계와의 불일치를 설명하거나 위험 후보를 공개하지 않는다.
- 수익 동률 시 보조 정렬 규칙은 미확정. 결정 가능한 안전한 표시만 개발하고 실제 순위 변경/공개를 사용자 승인 없이 확정하지 않는다.
- **중요:** 실제 Google 자료를 공개 URL, PR preview, CDN, Render에 게시하거나 미승인 비로그인 endpoint로 노출하면 안 된다. 합성 fixture로 로컬 격리 검증한다.

**F 합격:** 3건 제한/동기화 순위 변경/폐쇄 여부/중복/금액 오류/각종 PII·자유입력 텍스트/API/툴팁/캐시/다운로드 보안 경계 테스트.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--10-g--일본-다중-영수증-ocr"></a>
#### 10. G — 일본 다중 영수증 OCR

- 기존 파일 업로드·분류 UX를 사용. A4 한 장의 서로 다른 영수증을 개별 거래 후보로 분리. 한 영수증을 품목별 복수 지출로 기본 분해하지 않는다.
- 날짜·결제처·통화·최종 지급금액·결제수단 추출; 현금 거스름돈·세금·취소·할인·결제 총액 구별. 잘림/겹침/불명확할 때 HOLD.
- 현금·개인카드/법인카드 분리. 현금·개인카드의 JPY×10, 법인카드는 매입 KRW 보존. 법인카드 영수증은 매입의 증빙 연결, 신규 비용 두 번 생성 금지.
- 외부 OCR/AI 서비스에 실제 영수증을 보내지 말 것. 로컬 엔진이 없다면 합성 이미지 기반 업로드/영수증 분리/수정/검토 연동을 구현하고 엔진만 BLOCKED.

**G 합격:** 복수 영수증, 오염·겹침, 금액 오인 방지, 재업로드 멱등성, 결제수단 구분, 최종 7열 TSV 연결 테스트.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--11-h--자연어-거래-규칙-제안수정"></a>
#### 11. H — 자연어 거래 규칙 제안·수정

- 기존 카드 분류/사용자 수정 엔진과 로컬 AI 구성을 먼저 확인한다. '이 건 숙박비', '이 상호 앞으로 차량비', '이 거래 다른 여행', '회사 경비 아님' 같은 지시를 우선 처리.
- 제안→영향 미리보기→사용자 승인→미확정 후보만 재분류→변경 감사 이력. 원본 거래일·금액·ID·기존 사용자 확정을 AI가 직접 바꾸지 않는다.
- 실제 로컬 AI가 외부 클라우드 모델인지 확인되지 않으면 개인정보 실데이터 추론 요청을 차단하고 mock/synthetic으로 UX·규칙 인터페이스만 구현한다.

**H 합격:** 사용자 승인 없이는 불변, 변경 대상 범위와 근거 표시, 규칙 충돌·HOLD, 승인 후 멱등 적용, 확정·환불 원본 보호.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--12-i--주기-동기화와-render-이전은-사전-준비만"></a>
#### 12. I — 주기 동기화와 Render 이전은 사전 준비만

- 정본 Google 읽기는 **Asia/Seoul 매시 정각**이 목표. `tools/refresh_review_source.py --watch`의 기존 검토용 30초 다운로드와 충돌 여부·실제 운영 사용 상태를 먼저 확인.
- 안전한 1회 실행·파일 지문·불필요한 재파싱 방지·중복 실행 억제·마지막 성공 시각·오류 상태를 구현하고, 스케줄러는 **미활성 구성/런북만** 제출. 운영 등록/켜기 금지.
- Render 계획은 Linux·인증·OAuth·파일 스냅샷 지속성·백업·개인정보의 호스팅 지역과 국외 이전·비용을 검토. PostgreSQL 강제 이전이나 운영 데이터 마이그레이션 금지.

**I 합격:** 운영 배포 없는 개발용 설정·검증 결과·실행 전 승인이 필요한 체크리스트 PR.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--13-pr-작업-규칙--장시간-자율-진행"></a>
#### 13. PR 작업 규칙 — 장시간 자율 진행

1. A 수정은 PR #71에 추가한다. B~I는 **작은 기능별 PR**. 선행 PR 미병합 상태라면 후속 PR의 base/의존 관계를 본문에 명확히 기록한다. 리베이스·충돌 해결 시 최신 원격 변경을 보호한다.
2. 독립 작업이 막히면 후속 의존 단계만 HOLD하고 별개 D/G/H 또는 I의 안전한 부분으로 이동한다. 추정·정책 생성으로 억지로 완료하지 않는다.
3. 한 파일/공유 DB의 작성자는 한 명/한 실행 경로. 서브에이전트와 임시 worktree 남발 금지; 분산 작업은 코드/합성데이터 등 충돌 없는 범위만.
4. AGENTS.md 기준 **직접 영향받은 표적 테스트 + 인접 회계 무결성 한 번**을 우선하고 통과한 검증을 관성적으로 반복하지 않는다. 테스트 실패를 우회·삭제하고 성공이라고 쓰지 않는다.
5. PR을 올려도 사용자 승인 전 `main` 병합·운영 반영 없음. 새 브랜치 CI/프리뷰가 실제 자료를 외부로 싣지 않게 한다.
6. 사용자 dirty 파일과 원본·기존 로그를 삭제하지 말 것. 자신이 만든 임시 서버만 안전하게 정리하고 worktree/프로세스 목록을 남긴다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--14-개인정보실측회계-방어선"></a>
#### 14. 개인정보·실측·회계 방어선

- GitHub PR/fixture·console/log/스크린샷에 실제 성명·닉네임·예약ID·계좌·카드·고객 영수증·재무 거래 행·비밀값을 넣지 않는다. 테스트는 합성 데이터.
- 허가된 읽기 전용 실측에서는 필요한 헤더·합계 수식·상태/건수만 제한적으로 확인한다. 고객 자료를 로컬 임시 파일에 쓰면 파일 접근권한과 삭제/보존 필요성을 명확히 한다.
- 원본 DB/결제자/환불·OTA 확정·장부와의 차이가 발견되어도 운영 사실을 고쳐 맞추지 말고 오류/불일치로 보고한다.
- 개인정보 또는 실자료를 공개하는 라우트·JSON·캐시가 생성되면 배포 전에 반드시 차단하여 **공개 자료는 합성 테스트에만 한정**한다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--15-세션-압축재개-체크포인트"></a>
#### 15. 세션 압축·재개 체크포인트

각 작업 사이에 안전한 격리 로컬 체크포인트를 갱신하라(실제 고객·금전 원문 금지). 다음 내용을 항상 포함한다.

- 현재 `main` SHA, 격리 worktree·브랜치·dirty 목록·작업 중 HEAD
- 완료 A~I 단계, 변경 파일, 실제 테스트 명령/결과, 실패 원인
- PR 번호·URL·base/head SHA, 의존·충돌·검토/병합 가능 상태
- 가장 먼저 이어갈 **정확한 다음 작업**, BLOCKED 위험/사용자 질문
- 실제 운영 배포/Google 쓰기/원본 고객데이터 공개가 없었다는 확인 범위와 미검증 사실

컨텍스트 압축·새 세션에서 처음부터 같은 검증을 반복하지 않는다. 이 문서와 체크포인트를 읽고 현재 Git/PR 상태를 다시 확인한 후 미완료 작업을 이어간다. 실행 자원이나 도구가 종료되면 최종 상태를 정직하게 남긴다.

<a id="src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md--16-최종-보고-형식"></a>
#### 16. 최종 보고 형식

반드시 표로 `작업 A~I / DONE·PARTIAL·BLOCKED / 실제 기능 / PR URL·head SHA / 검증 근거`를 정리한다. 이어서 **병합 가능한 PR**, 수정 필요한 PR, 사용자 결정이 필요한 최소 정책, Git 충돌/dirty 보존, 실제 브라우저 검증 결과 및 의도적으로 생략한 테스트를 구분한다.

최종 보고는 **운영 배포하지 않음 / main 병합하지 않음 / Google 원본 쓰지 않음 / 사용자 dirty tree 보존** 여부를 명시한다. 코드와 표적 검증이 실제 끝난 경우에만 DONE이다. 분석 계획만 끝났다면 DONE으로 표시하지 않는다.

**종료 조건:** 도구·시간·계정 사용량이 허용하는 한 안전하고 독립적인 다음 단계 구현을 계속한다. 더 이상 안전한 진행이 불가능하면 지금까지 만든 모든 PR과 재개 지점을 남기고 종료한다.

---

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md"></a>

## ota-first-core

통합 전 경로: `docs/archive/ota-legacy-20261023/ota-first-core.md`

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--ota-결제-검토-코어"></a>
### OTA 결제 검토 코어

운영 자료의 읽기 전용 비교와 최종 통합 검사는 [검증 보고서](ota-legacy.md#src-docs-ota-first-verification-report-md)를 따릅니다. 아래 합성 검증 기록은 코어 담당자의 작업 범위입니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--범위와-실행-경계"></a>
#### 범위와 실행 경계

이 문서는 코드 전용 격리 작업공간의 코어 API 계약을 기록한다. 운영 레포, 운영 데이터베이스, 고객 원문에는 접근하지 않았다. 검증에는 합성 입력과 이미 존재하는 메일·포털 검증 함수만 사용했다. 운영 패리티와 전체 회귀는 코디네이터가 별도로 실행한다.

코어 구현은 `app/ota_payments.py`, `app/ota_review.py`에 있다. UI 전용 연결 코드는 이 작업에서 수정하지 않았다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--결제-이벤트-만들기"></a>
#### 결제 이벤트 만들기

`build_ota_payment_events({"mail_directories": ..., "portal_databases": ...})`는 카드 거래를 받지 않고 인증된 메일과 검증된 포털 자료만 읽는다. 예약 참조 하나에 여러 실제 결제 이벤트를 둘 수 있다.

입력에 source registry의 `missing` 또는 `diagnostics`가 있거나, 등록된 경로가 빠졌거나, mail·portal·reference loader가 읽기 오류를 내면 `OtaSourcesError`를 발생시킨다. 이때 일부 source만으로 만든 이벤트 목록을 반환하지 않아 새 자동 연결 후보가 만들어지지 않는다. reference 문서는 결제 근거로 쓰지 않지만, 등록된 문서를 읽지 못하면 inventory가 불완전하므로 같은 가드를 적용한다. 오류로 이벤트 재생성이 중단되어도 검토 DB의 manual·legacy snapshot 링크는 건드리지 않는다.

- 메일 이벤트 ID는 안정된 메일 메시지 ID에서 만든다. 금액, 결제일, 카드 끝자리, 예약 참조, 원문 digest는 이벤트 ID에 넣지 않는다.
- 포털 이벤트 ID는 안정된 원본 레코드 ID와 지급 식별자 또는 레코드 안의 지급 순번에서 만든다. 데이터베이스 경로와 mutable 예약 참조는 ID에 넣지 않는다.
- `identity_source_ids`는 이벤트 정체성에 쓰고, `source_ids`와 정렬된 `source_digests`는 출처와 현재 근거를 기록한다. `source_digest`는 단일 근거 digest이거나 digest 목록의 안정 집계값이다.
- 동일 원본 포털 레코드의 복구 사본은 원본 레코드 ID와 결제 근거가 같을 때만 합친다. 같은 payload hash라도 원본 레코드 ID가 다르면 별도 이벤트로 둔다. 같은 예약·금액만으로는 합치지 않는다.
- 메일·포털 교차 출처는 공통 검증 `payment_id` 또는 명시 `source_binding_ids` 증거가 있을 때만 합친다. 날짜·금액·통화·카드 끝자리 일치만으로는 합치 않고, 두 사건을 보존해 전역 matcher가 충돌로 보류한다. 같은 portal 원본 record ID의 복구 사본 합치는 유지한다.
- 결제일은 원문에 명시된 값만 쓴다. 포털 `observed_at`, 서비스 기간, 카드 승인일로 추정하지 않는다. 외화 금액을 환율로 KRW 환산하지 않는다.
- 예약 확정, 취소 알림, 결제 문의는 `event_type=reservation`, `evidence_status=not_card_charge`로 분류한다. 예정 결제는 `scheduled_charge`와 `scheduled`로 분류한다. 실제 결제는 `charge`와 `paid_verified`, 명시 완료 환불은 별도 `refund`와 `refund_verified`로 표시한다. 취소 알림은 기존 charge를 지우거나 환불로 바꾸지 않는다.
- `ota_mail`의 인증 헤더, 본문, 발송일, 서비스 기간, 통화 금액 검증 헬퍼와 기존 숙박 영수증의 결제 제목·금액 label 정규식을 재사용한다. 조사 포함 `결제가 완료`, 영어 `payment ... received/successful` 제목과 `결제 완료` 금액 label도 합성 fixture로 확인한다. `ota_portal`의 원본 해시·근거 역할·결제 검증기도 재사용한다. 메일 추출에는 카드 목록을 전달하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--카드-탐색과-자동-연결"></a>
#### 카드 탐색과 자동 연결

`same_date_cards(event, transactions, links=None)`는 merchant와 금액으로 행을 미리 걸러내지 않고 결제일과 같은 날짜의 모든 카드 행을 반환한다. 결과의 `already_linked_event_id`로 기존 점유를 표시한다.

`match_ota_payment_events(events, transactions, existing_links=None, rules=None)`는 전체 입력 안에서 1:1 배정을 확인한다. 모든 기존 링크가 현재 이벤트 목록에 없어도 거래를 점유한다. 중복 점유 링크가 있으면 해당 이벤트를 `HOLD_AMBIGUOUS`로 보낸다.

지원 상태는 `MATCHED_AUTO`, `MATCHED_USER`, `HOLD_NO_CARD`, `HOLD_AMBIGUOUS`, `HOLD_AMOUNT_MISMATCH`, `HOLD_DATE_UNKNOWN`, `HOLD_EVIDENCE_CONFLICT`, `PENDING_PAYMENT`, `NOT_CARD_CHARGE`다. 실제 결제일이 확인되지 않은 검증 charge는 `HOLD_DATE_UNKNOWN`이다. 예약·예정 결제는 실제 결제 수로 집계하지 않는다. `_event_is_paid(event)`가 charge와 명시 완료 refund만 실제 금전 이벤트로 판정한다.

KRW charge는 정확 금액만 자동 연결하며, refund는 signed 카드 원금의 절댓값과 refund 방향을 함께 확인한다. 외화는 원문 통화와 카드의 `foreign_currency` 및 `foreign_amount`가 정확히 일치해야 한다. 승인된 좁은 규칙의 `amount_delta_krw`는 부호를 포함한 `card amount - OTA amount`와 정확히 같아야 한다. booking 참조 하나만으로 보조 근거를 만들지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--기존-exact-연결-보존"></a>
#### 기존 exact 연결 보존

`bind_legacy_portal_links(events, legacy_links)` 입력은 기존 검증기가 exact로 판정한 binding이어야 한다. binding은 `verified_exact`, `evidence_kind`, `booking_ref`, `source_digest`, `transaction_id`, `card_last4`, `amount`, `currency`를 제공한다. source와 예약·카드·금액이 유일하게 맞는 canonical event만 binding한다. 새 포털 이벤트를 만들거나 결제일을 추정하지 않는다.

matcher의 `existing_links`는 `ota_event_id -> {transaction_id, status, source_digest, legacy_exact, source_digests}` 형태를 받는다. legacy 링크는 현재 이벤트가 실제 결제이고 digest와 source digest가 겹치며 금액·통화·방향·카드 끝자리가 모두 맞을 때만 보존한다. legacy 날짜가 없는 이벤트는 신규 자동 연결 대상이 아니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--수동-검토와-source-변경"></a>
#### 수동 검토와 source 변경

`OtaReviewStore(path)`는 호출자가 지정한 별도 검토 데이터베이스만 연다. 파일이 없으면 생성하지 않고, 기존 파일도 `ota_review_` 표 이외의 표가 있으면 거부한다. `links()`, `active_rules()`, `proposals()`, `preview()`는 읽기 전용이며 스키마를 만들지 않는다. `confirm()`, `answer_proposal()` 및 변경 상태를 기록할 필요가 있는 `refresh()`만 초기화를 수행한다.

수동 연결은 이벤트·카드 snapshot과 안정 event ID로 저장한다. 다음 refresh에서 같은 source identity의 금액·날짜·카드·예약 참조 또는 digest가 바뀌어도 `MATCHED_USER`와 카드 점유를 유지하고 `evidence_changed` 경고를 남긴다. 원본이 사라지거나 더는 이벤트를 검증하지 못하면 저장 snapshot을 반환하고 `evidence_missing`을 표시한다. 누락된 manual event의 카드도 다른 이벤트에 배정하지 않는다.

`refresh(..., changed_transaction_ids=..., changed_event_ids=...)`는 바뀐 이벤트, 해당 카드에 이미 연결된 이벤트, 날짜·방향·보조 식별 근거가 맞는 변경 카드 후보만 반환한다. 이는 incremental import와 source-targeted refresh의 계약이다.

`confirm()`은 preview digest가 현재 입력과 다르면 `STALE_PREVIEW`를 돌려준다. 현재 paid 근거와 명시 refund 검증, 안정 ID, 전역 카드 미점유를 요구한다. 호출자는 최신 전체 점유 snapshot을 `allocations`로 반드시 전달한다. 생략하거나 `None`을 전달하면 `GLOBAL_ALLOCATIONS_REQUIRED`로 거부하며, 전체 점유를 확인한 뒤 전달한 명시 `{}`는 허용한다. 확인은 한 번의 연결만 만들고 새 규칙은 제안 상태로 둔다.

규칙 레코드는 `rule_id`, `conditions`, `source_event_id`, `source_transaction_id`, `approved_by`, `user_confirmation`, `created_at`, `version`, `active`를 보존한다. `once`는 규칙을 만들지 않는다. 편집은 새 pending 제안만 만들며 자동 활성화하지 않는다. 명시 승인된 좁은 조건만 active 목록에 반환한다. 지원 조건은 provider·item과 merchant 또는 issuer·card 끝자리로 범위를 제한하고, 날짜 차이는 최대 7일, signed KRW 차이는 -10000부터 10000까지 허용한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--인터페이스-변경-기록"></a>
#### 인터페이스 변경 기록

- 서로 다른 원본의 mail·portal 이벤트는 공통 검증 `payment_id` 또는 명시 `source_binding_ids` 증거가 있을 때만 합친다. 날짜·금액·통화·카드 끝자리가 같다는 조건만으로는 합치지 않으며, 두 이벤트를 보존해 전역 matcher가 충돌로 보류한다. 같은 portal 원본 record ID의 복구 사본 병합은 유지한다.
- `OtaReviewStore.event_snapshots()`는 GET용 읽기 전용 API다. 반환값은 `{event_id: event_snapshot}`이고 각 snapshot에 `_evidence_missing`, `_evidence_changed`를 붙인다. `links()`의 점유 상태와 조합해 sourcegone 경고를 그린다. GET에서 `refresh()`를 호출하지 않는다.
- `confirm(..., allocations=...)`에는 전체 최신 자동·기존·수동 점유 snapshot을 반드시 전달한다. 인자를 생략하거나 `None`이면 `GLOBAL_ALLOCATIONS_REQUIRED`로 거부한다. 호출자가 전체 현재 점유를 확인한 뒤 보낸 명시 빈 `{}`는 유효하다.
- `confirm()` 응답과 `proposals()`는 `proposal_conditions` 또는 `conditions`, `proposal_review_warnings` 또는 `review_warnings`를 제공한다. 검증된 KRW charge의 제안은 signed `amount_delta_krw = card - OTA`와 양방향 절댓값 날짜 간격 `date_lag_days`를 담는다. 범위 밖 금액·날짜, 외화, 또는 검증되지 않은 값은 warning을 반환하고 승인 전에 편집을 요구한다. `once`는 다음 이벤트에 규칙을 적용하지 않는다.

- 카드 검색 API는 전체 같은 날짜 행을 반환하고 기존 점유 event ID를 추가한다. 이전 UI의 금액·merchant 사전 필터 가정은 사용할 수 없다.
- 이벤트 결과에는 `identity_source_ids`, `source_digests`, `evidence_status`, `event_type`을 제공한다. `ota_event_id`는 mutable 증거 값과 분리했다.
`confirm()`은 preview digest가 현재 입력과 다르면 `STALE_PREVIEW`를 돌려준다. 현재 paid 근거와 명시 refund 검증, 안정 ID, 전역 카드 미점유를 요구한다. 호출자는 최신 전체 점유 snapshot을 `allocations`로 반드시 전달한다. 생략하거나 `None`을 전달하면 `GLOBAL_ALLOCATIONS_REQUIRED`로 거부하며, 전체 점유를 확인한 뒤 전달한 명시 `{}`는 허용한다. 확인은 한 번의 연결만 만들고 새 규칙은 제안 상태로 둔다.
- `links()`는 기존 `transaction_id`와 `status`에 evidence warning 필드를 보탠다. `event_snapshots()`는 저장 event와 warning bit를 읽기 전용으로 제공한다.
- 규칙 조건 이름은 UI가 보내는 `amount_delta_krw`를 사용한다. 제안 질문은 조건과 warning을 `confirm()` 응답 또는 `proposals()`에서 읽을 수 있다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-core-md--합성-검증"></a>
#### 합성 검증

matcher는 `active=False` 또는 `status=inactive|revoked`인 규칙을 승인자 기록보다 우선해 거부한다. `approved_by`가 있어도 비활성 규칙은 적용되지 않는다.

규칙은 `approved_by`, `user_confirmation`, `approved=True` 가운데 명시 승인 증거가 있어야 한다. `status=active`만으로 승인으로 보지 않는다. 검토 제안과 matcher는 같은 내부 범위 검사기를 사용하며, provider·item에 merchant 또는 issuer·card 끝자리가 있어야 한다.

최종 보완에서 실행한 좁은 회귀:

```powershell
python -m pytest tests/card_pipeline/test_ota_review.py -q
python -m pytest tests/card_pipeline/test_ota_payments.py::test_signed_approved_amount_delta_matches_but_absolute_or_unapproved_delta_does_not tests/card_pipeline/test_ota_payments.py::test_same_date_and_amount_mail_portal_claims_without_identity_proof_stay_separate tests/card_pipeline/test_ota_payments.py::test_mail_and_portal_same_payment_id_merge_source_digests_once tests/card_pipeline/test_ota_payments.py::test_portal_snapshot_copies_with_only_observed_at_change_deduplicate -q
python -m py_compile app/ota_payments.py app/ota_review.py
```

이 targeted 검증은 review 25개와 payment 관련 4개가 통과했다. 운영 자료 패리티와 전체 회귀는 실행하지 않았다.

핵심 targeted 테스트 명령:

```powershell
python -m pytest tests/card_pipeline/test_ota_payments.py tests/card_pipeline/test_ota_review.py -q
```

검증기 재사용 호환 확인:

```powershell
python -m pytest tests/card_pipeline/test_ota_portal.py::test_source_hash_and_evidence_roles_are_required tests/card_pipeline/test_booking_mail.py::test_duplicate_message_enrichment_is_allowed_but_changed_body_is_rejected -q
python -m py_compile app/ota_payments.py app/ota_review.py
```

위 targeted 테스트는 source inventory 누락과 mail·portal·reference loader 오류에서 새 이벤트 권한이 막히는지, 기존 manual snapshot 보존, source 변경·삭제·결제 근거 상실 후 카드 점유, 원본 복구 사본 중복, 여러 결제, 결제일 미확인, 외화 정확 비교, signed refund/delta, 규칙 승인, preview stale, incremental refresh, Booking 결제 영수증의 16가지 합성 제목·금액 label 조합을 확인한다. 운영 자료 패리티, 실제 old 200 연결 결과, 전체 회귀는 이 작업에서 실행하지 않았다.

---

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md"></a>

## ota-first-isolated-review-pilot

통합 전 경로: `docs/archive/ota-legacy-20261023/ota-first-isolated-review-pilot.md`

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md--isolated-ota-review-pilot-실행-기록"></a>
### Isolated OTA review pilot 실행 기록

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md--2026-10-09-실제-실행-결과"></a>
#### 2026-10-09 실제 실행 결과

기준 코드는 `main`의 `90296d69180e40266e8b553ea36d595c4ef66af6`이며 시작 시 원격 `origin/main`과 같았다. 운영 DB를 SQLite `mode=ro`와 `PRAGMA query_only=ON`으로 열고, 저장은 저장소 밖의 새 로컬 전용 pilot SQLite에만 수행했다. 운영 checkout과 production 프로세스는 갱신하지 않았다.

시작 기준은 정확 연결 200건, HOLD 183건, 장부 734행이다. 업무 테이블은 74개이며 SQLite 시스템 테이블을 포함하면 75개다. 기존 사용자 결정은 27건, 기존 review hold는 16건이었다. 원본과 manifest를 포함한 파일 963개의 digest, 모든 테이블의 행 digest, schema digest와 DB 파일 지문을 로컬에 보존했다. 원문과 거래 식별자, SQLite 파일, 화면 캡처는 Git에 포함하지 않는다.

대표 HOLD 8건을 선정했다. `HOLD_NO_CARD` 4건은 같은 결제일 카드 목록과 수동 검토를 확인하기 위해, `HOLD_DATE_UNKNOWN` 4건은 날짜가 없을 때 후보를 만들지 않는지 확인하기 위해 골랐다. 이번 실제 결과에는 다른 HOLD 유형이 없어 사례를 만들지 않았다. 390×844와 1440×900의 실제 Chromium 화면에서 날짜가 있는 각 사례의 카드 32행을 모두 표시했고, 날짜 미확인 사례는 카드 0행이었다. 두 화면의 가로 넘침과 JavaScript 오류는 0이었다.

격리 loopback HTTP 프로세스에서 기존 `render_import_section`, OTA `dispatch`와 실제 `CoreOtaPaymentBackend`를 실행했다. 운영 서버 전체를 시작한 것이 아니며 운영 장부 쓰기 경로와 worker는 연결하지 않았다. 대표 사례의 필터만 적용하고 카드 후보를 merchant나 금액으로 줄이지 않았다.

사용자가 앞서 허용한 동일 조건 거래의 승인번호 순서 배정 사례 1건을 실제 core backend의 preview와 confirm 경로로 저장했다. 개별 결제 증빙으로 두 거래를 구분했다고 주장하지 않는다. 별도 review DB의 manual link는 1건, proposal은 1건, active rule과 frozen group은 각각 0건이다. 새 backend와 화면 재조회에서 수동 연결과 proposal이 유지됐고, 검토 화면은 8건에서 7건으로 줄었다. 전체 읽기 전용 계산의 남은 HOLD는 182건이며 운영 HOLD와 운영 authority는 변경하지 않았다.

실제 이미 점유된 카드의 preview와 confirm은 서버에서 모두 거부했다. 실제 운영 거래의 `duplicate_of`, `parse_error`, `conflict_reason` 행은 각각 0건이므로 세 상태를 실제 자료로 검증했다고 표현하지 않는다. 각 상태의 표시·선택 비활성·서버 거부는 합성 회귀에서 검증했다. 실제 full/partial group 사례도 이번 표본에 없어 frozen group을 생성하지 않았다.

proposal은 provider·숙박 항목·가맹점·카드사·카드 끝자리·KRW charge·차액 0원·날짜 차이 0일로 제한된다. 메모리에서만 승인 표시를 주어 dry-run한 결과, 범위에 들어오는 HOLD event는 16건이고 기존 수동 연결 외에 새 자동 연결은 1건이었다. 범위에 들어온 16건 모두를 연결하는 규칙이 아니다. 기존 exact 변경과 중복 카드 배정은 0건이며 실제 규칙 활성화는 수행하지 않았다. 동일 날짜·동일 금액 거래의 개별 대응은 결제 원문만으로 증명되지 않을 수 있으므로 이 분석을 실제 연결 정답의 증명으로 해석하지 않는다.

기존 exact 200건의 OTA event identity, provider, booking, transaction ID와 evidence digest를 직접 비교해 200/200 동일, 변경 0, 누락 0을 확인했다. 각 카드 source hash도 로컬 pair 기록에 보존했다. 수동 연결 재조회는 성공했고 중복 카드 배정과 기존 exact 재사용은 0건이다.

검증 로그와 원본 비교 근거는 저장소 밖의 `C:/AX/ota-review-pilot-local-20261009`에만 보존한다. 이 경로의 review DB와 자료는 로컬 운영 증거이며 배포하거나 commit하지 않는다.

수동 저장과 dry-run 뒤에도 업무 테이블의 전체 행 digest, schema, 사용자 결정, 기존 hold, 장부 734행, 운영 DB 파일 지문과 원본 963개 파일 digest가 모두 같았다. 운영 DB 변경과 원본 변경은 0건이다. 별도 review DB에만 링크 1건과 미승인 제안 1건이 남는다. production authority 전환과 production 재시작은 수행하지 않았다.

OTA 관련 검사 254개와 하위 검사 4개가 통과했다. 새 격리 DB 수명주기 검사와 최종 변경된 UI·서버 검사 묶음은 34개와 하위 검사 4개가 통과했다. 기존 브라우저 fixture의 정확 금액 후보는 새 부분 묶음 보호 경계에 들어가 수동 선택이 차단됐으므로, 수동 연결·이번 건만·규칙 승인 검사의 fixture를 서로 다른 카드 힌트와 확인 가능한 금액 차이 사례로 바꿨다. 부분 묶음 보호 assertion을 약화하지 않았으며 오래된 점유 사유 기대값 두 개만 현재 식별자와 맞췄다.

저장소에는 기존 typecheck 설정이나 frontend build 명령이 없다. 저장소 밖에 mypy를 설치해 변경된 테스트 파일 3개를 `--check-untyped-defs --follow-imports=skip --ignore-missing-imports`로 검사했다. 이 검사는 변경된 테스트 코드의 검사이며 전체 production 코드의 타입 검사로 주장하지 않는다. Python production 실행 경로는 `compileall`로 컴파일했고 생성물은 저장소 밖에 두었다. 별도 frontend production bundle은 사용하는 구조가 아니다.

전체 기존 검증 명령 `python -m pytest -q -ra`의 결과는 **2426 passed / 3 skipped / 2386 subtests passed**, 종료 코드 0, 소요 시간 1211.78초다. skip은 기존 비공개 Agoda 자료 부재 2건과 Windows 파일 권한 제약 1건이다. 새 수명주기 검사는 전체 검사 수집 시작 뒤 추가했으므로 위 전체 건수에는 포함하지 않고 별도로 통과한 최종 targeted 34건에 포함했다. 변경된 테스트 파일 3개의 mypy 검사, Python 실행 코드 `compileall`, `git diff --check`도 종료 코드 0으로 통과했다. 테스트와 문서 외 제품 코드, 설정, 운영 데이터는 변경하지 않았다.

pilot의 저장·재조회·기존 정확 연결 보존과 운영 데이터 불변 검증은 완료했다. 실제 자료에 없는 세 오류 상태와 group의 실제 확인은 실행했다고 주장하지 않는다. 미승인 proposal 1건은 그대로 남겨 두며 다음 사용자 응답 없이 활성화하거나 나머지 HOLD를 처리하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md--2026-10-08-최초-git-병합-기록"></a>
#### 2026-10-08 최초 Git 병합 기록

이 절은 최초 병합 당시의 기록이다. 이후 OTA 매칭 기본 규칙이 main에 병합됐으며 이번 pilot 기준은 위의 `90296d69180e40266e8b553ea36d595c4ef66af6`이다. 아래의 실행 금지 범위와 이전 검사 수치는 당시 단계에만 해당하며 2026-10-09의 실제 pilot 결과를 대신하지 않는다.

2026-10-08에 검토를 통과한 `feature/ota-first-review-20261008`의 `ba1c12b4773ad23af55e4f4cb49d6ac35d099b68`을 기존 main `37bd457341d68185d533a243eada64162537f943`에서 fast-forward로 병합했습니다. 병합 당시 feature는 3 commits ahead / 0 behind였고 충돌은 없었습니다. 추가 코드는 수정하지 않았으며 추가 테스트도 실행하지 않았습니다. 이 계획 문서만 별도 커밋합니다.

Git main 병합은 운영 배포나 OTA-first authority 전환을 뜻하지 않습니다. 운영 체크아웃 `C:/AX/cost`는 기존 `37bd457341d68185d533a243eada64162537f943`에 detached HEAD로 고정하고 미커밋 변경과 사용자 파일을 보존합니다. main Git 작업은 기존 격리 worktree `C:/AX/cost-ota-first-review-20261008`에서 진행합니다. 운영 재시작, 운영 DB 쓰기, review DB 생성, OTA 재대사, source refresh, reclassification은 이번 단계에서 실행하지 않습니다.

기존 수치와 검증을 재사용합니다. 아래 수치는 이번 단계에서 다시 실행한 결과가 아닙니다.

- 실제 OTA payment: 383건, matched: 200건, HOLD: 183건입니다.
- 기존 exact 200건은 동일 카드에 고정됐고 duplicate assignment는 0건입니다.
- 기존 ledger rows 734건과 사용자 확정, 보류, 원본을 보존했습니다.
- 기존 core/UI targeted는 84 passed입니다.
- merge safety targeted는 7 passed / 2 subtests passed입니다.
- full regression은 2394 passed / 1 known unrelated doc failure / 3 skipped / 2398 subtests passed입니다. 해당 문서는 복구했고 해당 test만 1 passed로 확인했습니다. 전체 회귀는 반복하지 않습니다.

상세 기록은 [기존 검증 보고서](ota-legacy.md#src-docs-ota-first-verification-report-md)를 따릅니다. 보고서의 main과 검토 브랜치 상태는 병합 전 기록이며, 이번 병합의 경계는 이 문서를 따릅니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md--다음-단계의-목적과-시작-조건"></a>
#### 다음 단계의 목적과 시작 조건

아래는 최초 pilot 계획과 보호 조건이다. 2026-10-09 사용자의 실행 지시에 따라 별도 pilot 프로세스와 review DB를 만들고 위 실행 결과를 확인했다. OTA-first를 production authority로 전환하지 않았다.

기존 정확 연결 200건을 유지하고 HOLD 183건만 검토 대상으로 표시합니다. 운영 장부 DB는 읽기 전용으로 사용하고, 수동 연결과 proposal은 운영 장부와 분리된 pilot review DB에만 저장하는 경계를 먼저 확인합니다. pilot 환경 설정은 기존 `WEBLEDGER_OTA_REVIEW_MODE=isolated`와 별도 `WEBLEDGER_OTA_REVIEW_DB`를 사용합니다. 실제 경로와 접근 방식은 pilot 시작 전에 정하며, 이 문서에는 고객 자료나 비밀값을 넣지 않습니다.

pilot 시작 전에는 복구 사본과 읽기 전용 접근을 확인하고 기존 exact 링크, 사용자 확정, 보류, 전체 업무 테이블과 원본의 비교 기준을 로컬에 보존합니다. 원본을 재수집하거나 새 분류를 실행하지 않습니다. 합계만 같다는 이유로 보존을 판정하지 않습니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md--대표-hold-선택"></a>
#### 대표 HOLD 선택

처음에는 5~10건만 선택합니다. 목표는 가능한 경우 8건을 네 유형에서 고르게 고르는 것이며, 실제 사례 수에 맞춰 조정합니다. 현재 HOLD 전체는 카드 없음 90건, 날짜 미확인 59건, 모호 21건, 금액 불일치 13건입니다.

| 유형 | 초기 선택 목표 | 확인할 내용 |
| --- | ---: | --- |
| HOLD_NO_CARD | 2건 | 같은 날짜의 모든 카드 표시 또는 거래 없음 안내를 확인합니다. 적절한 거래가 없으면 연결하지 않습니다. |
| HOLD_DATE_UNKNOWN | 2건 | 결제일 미확인 안내와 선택 불가를 확인합니다. 날짜를 추정하거나 억지 연결하지 않습니다. |
| HOLD_AMBIGUOUS | 2건 | 후보를 숨기지 않고 표시하는지 확인하고, 사용자가 실제 거래를 확인한 경우에만 수동 연결합니다. |
| HOLD_AMOUNT_MISMATCH | 2건 | 미리 보기의 실제 부호 있는 차액과 사용자 확정을 확인합니다. 차액을 할인으로 단정하지 않습니다. |

수동 연결 후 실제 rule proposal을 확인할 수 있는 사례를 우선 포함합니다. 대표 사례에 중복·파싱 오류·거래 충돌 행이 있으면 표시와 선택 차단도 확인합니다. 실제 자료에 없는 유형을 만들기 위해 원본이나 거래를 수정하지 않습니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md--pilot-확인-순서"></a>
#### pilot 확인 순서

1. 실제 UI의 HOLD queue가 183건인지 확인합니다. 기존 exact 200건이 같은 카드에 고정됐는지 별도로 확인하며, 서로 다른 집계인 과거 카드 미연결 177건과 혼동하지 않습니다.
2. 결제일이 있는 대표 OTA마다 같은 결제일의 모든 카드 거래가 표시되는지 확인합니다. merchant나 금액으로 숨기지 않습니다. 결제일이 없으면 설명만 확인합니다.
3. 이미 연결된 카드와 `duplicate_of`, `parse_error`, `conflict_reason`이 있는 카드는 표시되지만 선택할 수 없어야 합니다. 각각 연결 표시 또는 중복 거래, 파싱 오류, 거래 충돌 사유가 보여야 합니다. 정상 거래는 선택할 수 있어야 합니다.
4. 사용자가 선택한 카드의 preview에서 OTA 금액, 카드 금액, 실제 차액, 날짜, 거래 방향을 확인합니다. 사용자가 명시적으로 확정한 경우에만 분리 review DB에 수동 연결을 저장합니다.
5. 수동 연결 뒤 MATCHED_USER가 유지되고 proposal만 생성되는지 확인합니다. 사용자의 규칙 승인 전에는 active rule이 생성되면 안 됩니다. 에이전트는 proposal의 사실과 좁은 조건을 사용자에게 질문하며, 할인이나 날짜 차이의 원인을 단정하지 않습니다.
6. 사용자가 “이번 건만”을 선택한 사례는 이후 OTA에 규칙으로 적용되지 않는지 확인합니다. “규칙 저장”을 명시 승인한 사례만 좁은 동일 조건의 다음 OTA에 적용되는지 확인합니다. 맞는 후속 사례가 없으면 미확인으로 기록하며 거래를 만들어내지 않습니다.
7. 390×844와 1440×900에서 거래 목록, 선택 상태, 차액, 확정, proposal 상태와 가로 넘침을 확인합니다.
8. pilot 전후 기존 exact 링크와 카드 점유, 사용자 확정, 보류, 장부와 원본을 비교합니다. 기존 exact 재연결, 카드 중복 배정, 사용자 확정 덮어쓰기 또는 운영 데이터 변경이 발견되면 pilot을 중단하고 로컬 근거를 남깁니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md--pilot-결과와-다음-결정"></a>
#### pilot 결과와 다음 결정

대표 사례별로 확인한 UI 동작, 사용자의 수동 선택과 답변, proposal 상태, 승인된 규칙의 범위, 이후 사례 적용 여부를 로컬에 기록합니다. 미확인 항목과 실제 검증한 결과를 구분하며 고객 원문과 실제 식별자는 Git에 넣지 않습니다.

pilot을 마쳐도 전체 HOLD를 일괄 처리하거나 production authority로 자동 전환하지 않습니다. 대표 5~10건의 결과를 사용자에게 보고한 뒤 나머지 검토와 별도 production cutover 여부를 결정합니다.

---

<a id="src-docs-archive-ota-legacy-20261023-ota-first-ui-md"></a>

## ota-first-ui

통합 전 경로: `docs/archive/ota-legacy-20261023/ota-first-ui.md`

<a id="src-docs-archive-ota-legacy-20261023-ota-first-ui-md--ota-결제-보류-검토-ui"></a>
### OTA 결제 보류 검토 UI

운영 자료의 읽기 전용 비교와 최종 통합 검사는 [검증 보고서](ota-legacy.md#src-docs-ota-first-verification-report-md)를 따릅니다. 아래 표적 검사 기록은 화면 담당자의 작업 범위입니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-ui-md--범위와-활성화-조건"></a>
#### 범위와 활성화 조건

이 화면은 기존 카드 가져오기 화면의 opt-in 영역입니다. 다음 설정이 모두 있어야 `/import`에 영역이 나타나고 `/api/imports/ota` 경로가 활성화됩니다.

- `WEBLEDGER_CARD_FLOW=1`
- `WEBLEDGER_OTA_REVIEW_MODE=isolated`
- 절대 경로를 지정한 `WEBLEDGER_OTA_REVIEW_DB`

기본 자료 읽기는 `board.path.parent`에서 `ota-sources.json`을 찾고 기존 `app.ota_sources.resolve_sources` 계약을 사용합니다. 기본 메일 위치는 `WEBLEDGER_OTA_MAIL_DIR` 또는 `ota-mail`, 포털 기본 위치는 기존 `WEBLEDGER_AGODA_PORTAL_DB`와 `evidence_path` 규칙입니다. manifest의 등록 자료와 기존 기본 경로를 함께 사용합니다. `WEBLEDGER_OTA_SOURCES_JSON`은 합성 검증용 명시 override입니다. 키는 `mail_directories`, `portal_databases`, `reference_documents`입니다. UI adapter는 `app.ota_payments.build_ota_payment_events`, `match_ota_payment_events`, `same_date_cards`와 `app.ota_review.OtaReviewStore`를 호출합니다. 검토 DB는 카드 장부 DB와 같은 파일이면 거부합니다.

기본 설정은 기능을 끈 상태입니다. adapter는 일반 카드 흐름과 분리되어 있고 코어 파일을 변경하지 않습니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-ui-md--읽기와-쓰기-경계"></a>
#### 읽기와 쓰기 경계

첫 GET과 POST preview는 코어가 기존 검토 DB를 읽기 전용으로 엽니다. DB 파일이 없으면 연결을 만들지 않습니다. UI GET은 `links`, `event_snapshots`, `active_rules`, `proposals` 같은 조회만 사용합니다. `refresh`는 GET에서 호출하지 않으며, 새 근거와 기존 source digest 차이는 현재 읽은 자료로 계산합니다. 근거가 사라지거나 결제 확인이 무효가 된 수동 연결은 저장된 이벤트 snapshot과 `evidence_missing` 경고를 보여 줍니다. 해당 거래의 재선택을 막고, GET 때문에 저장소 디렉터리·DB·스키마를 만들거나 변경하지 않습니다.

POST 쓰기 경로는 명시적 사용자 동작만 처리합니다. 카드 가져오기 뒤에는 해당 가져오기 batch에 새로 생긴 `transaction_id`만 `refresh_after_import`에 전달합니다. 저장된 수동 연결의 source digest가 달라졌다면 관련 `event_id`도 전달합니다. 코어의 `refresh`는 기존 `MATCHED_USER` evidence 변경 상태를 보존합니다. 수동 연결은 분리된 검토 DB에 기록하며 카드 장부 board에는 기록하지 않습니다.

기존 카드 흐름의 읽기 전용 `match_mail` → `extend_report` 비교 결과를 카드 상태가 바뀔 때 한 번 계산해 board 메모리에 exact 연결 snapshot으로 둡니다. 실제 report의 `matches`에는 제공자, 예약 참조, source hash와 digest, 거래 ID, 방향, 항목·기간·근거 종류가 포함될 수 있지만 카드 끝자리·통화·금액은 없을 수 있습니다. 따라서 report에서 카드 사실을 만들어내지 않습니다. report digest와 canonical event digest의 교집합, 제공자·예약 참조·source hash·방향이 맞는지 확인한 뒤, 연결된 원본 거래 행의 직접 필드에서 원화 금액 또는 외화 금액·통화, 카드 끝자리와 방향을 canonical event와 대조합니다. 각 이벤트와 거래의 유일한 연결만 pin합니다. canonical event에 다른 근거 digest가 더 있어도 report digest가 교집합에서 검증되면 기존 exact 연결을 보존합니다. 수동 연결이 우선하며 source 변경 뒤 legacy 거래를 새 카드로 다시 추론하지 않습니다.

카드 연결은 미리 보기와 명시적 확정의 두 단계입니다. 확정 때 최신 이벤트, 카드 점유, preview digest를 다시 검사하고, 코어 `confirm`에 현재의 모든 자동·수동·legacy 점유를 `allocations`로 전달합니다. 점유가 없어도 `allocations={}`를 명시합니다. 자동 일치 또는 기존 수동 연결 거래는 목록에 남기되 이유를 표시하고 선택을 막습니다. 비어 있는 CSRF 설정이나 요청 헤더는 OTA POST에서 허용하지 않습니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-ui-md--표시-및-개인정보"></a>
#### 표시 및 개인정보

API snapshot은 allowlist로 만듭니다. 카드 거래는 `transaction_id`, `issuer`, `card_kind`, `card_tail`, `approval_date`, `posting_date`, `merchant`, `amount_krw`, `foreign_amount`, `currency`, `approval_number`, `direction`, 환불·취소 상태, 연결 ID와 안전한 연결 사유만 내보냅니다. OTA 이벤트는 제공자, 예약 참조, 이벤트 종류, 결제일, 금액·통화, 이용 기간, 항목, 상태·사유, 환불 상태와 `evidence_changed`, `evidence_missing`만 내보냅니다. 원본 row JSON, 비공개 분류 자료, 경로, source inventory, source digest는 내보내지 않습니다.

OTA 원본에 결제일이 없으면 화면에 `미확인`으로 표시하고 카드 선택·미리 보기·확정에 사용하지 않습니다. 날짜 검색값을 결제일로 추정하거나 저장하지 않습니다. 같은 결제일의 카드 거래는 가맹점이나 금액으로 숨기지 않습니다.

제안 질문은 실제 조건의 제공자·항목·가맹점 또는 카드 식별값, signed `amount_delta_krw`, `date_lag_days`를 보여 줍니다. 예를 들어 카드 금액이 OTA 금액보다 4,000원 적은 조건이면 할인이라고 단정하지 않고 그 차이와 조건을 다음 결제에도 적용할지 묻습니다. 원화 금액이 없으면 0원이 아니라 `미확인`으로 표시합니다. 제안은 `이번 건만`, `규칙 저장`, `조건 수정`으로 답할 수 있습니다. 승인·수정 규칙에는 제공자와 항목, 그리고 가맹점 정규형 또는 카드사와 카드 끝 네 자리가 필요합니다. `amount_delta_krw`는 부호 있는 정수이며 -10000부터 10000까지 허용합니다. 예를 들어 카드 275013원에서 OTA 279013원을 뺀 -4000원도 허용합니다. `date_lag_days`는 별도 정수로 0부터 7까지 허용합니다. 불리언, 실수, 숫자 문자열은 허용하지 않습니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-ui-md--http-경로"></a>
#### HTTP 경로

- `GET /api/imports/ota`: allowlist snapshot을 읽습니다.
- `POST /api/imports/ota/preview`: 선택 후보의 차이를 미리 봅니다.
- `POST /api/imports/ota/confirm`: 최신 preview를 명시적으로 확정합니다.
- `POST /api/imports/ota/proposal`: 제안에 답합니다.
- `POST /api/imports`: 기존 카드 가져오기가 성공한 뒤 새 거래 ID만 검토 adapter에 알려줍니다.

모든 POST는 로그인한 owner와 일치하는 비어 있지 않은 CSRF token이 필요합니다. stale preview는 409로 응답합니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-first-ui-md--targeted-검증"></a>
#### Targeted 검증

격리 체크아웃 루트에서 다음 명령만 실행합니다. 전체 회귀는 실행하지 않습니다.

```powershell
python -m unittest webapp.tests.test_ota_payment_review
python -m unittest webapp.tests.test_ota_payment_review_browser
```

브라우저 검증은 로컬 합성 HTTP server와 Playwright Chromium을 사용합니다. 390x844와 1440x900에서 합성 카드 12건, 승인일·매입일·승인 번호·환불 상태, 이미 연결된 거래의 선택 차단과 사유, 차이 preview, 수동 확정, 대기 제안을 확인하고 가로 넘침이 0인지 확인합니다. 별도 실 브라우저 경로는 실제 기본 adapter와 실제 검토 store로 수동 확정, 이번 건만 처리, 규칙 승인을 거친 뒤 카드 입력 DB와 source-gone GET의 검토 DB hash가 유지되는지 확인합니다. 캡처와 자료는 합성 데이터만 포함합니다.

- [모바일 합성 화면](../ota-first-ui-mobile.png)
- [데스크톱 합성 화면](../ota-first-ui-desktop.png)

---

<a id="src-docs-archive-ota-legacy-20261023-ota-first-verification-plan-md"></a>

## ota-first-verification-plan

통합 전 경로: `docs/archive/ota-legacy-20261023/ota-first-verification-plan.md`

<a id="src-docs-archive-ota-legacy-20261023-ota-first-verification-plan-md--ota-first-verification-plan"></a>
### OTA-first verification plan

1. Development runs targeted synthetic tests only.
2. Operational verification runs locally, with SQLite mode=ro and query_only.
3. Before verification, record all operating transaction/user-confirmation/hold/ledger tables and all registered source file digests. Legacy exact baseline contains 200 unique card transactions and 734 ledger rows.
4. Extract canonical OTA events from source evidence independently of card transactions. Build migration links only after event identity/source digest/provider/booking/amount/direction have been checked against the already verified legacy exact link. Preserve these links, do not recompute different cards.
5. Verify all 200 bindings reproduced, incorrect replacements=0, global duplicate assignments=0. A failed parity gate forbids production authority cutover. Report genuine evidence gaps without making up payment dates or monetary events.
6. Count all events by actual charge/refund/pending/noncharge. Count OTA event HOLD states independently from old unmatched card rows. Reconcile each of the 177 old unmatched card rows to an evidence-backed event or to an explicit no-monetary-evidence residual. Never assert 177 cards = 177 payments without proof.
7. Verify manual confirmation, preview digest stale protection, original inputs unchanged, linked-card reuse blocked, manual links persist across refreshed evidence, no automatic active rules, narrow explicit rule approval, once-only choice, incremental new-card/source refresh in synthetic tests.
8. At 390x844 and 1440x900, a local synthetic HTTP browser test checks all 12 same-date rows, original columns, connected-card labels, preview difference, manual confirmation, proposal status, and zero horizontal overflow. Real customer browser sessions are not part of this task.
9. After the final targeted tests and read-only parity pass, execute full regression once in isolated checkout. Preserve exact log/exit code. No repeated full regression.
10. Compare operating code/protected files/source digests/business tables after all work. Record production cutover=false, commit=false, push=false. Current production checkout remains 37bd457341d68185d533a243eada64162537f943 plus preserved unrelated working changes.

---

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md"></a>

## ota-matching-rule-defaults

통합 전 경로: `docs/archive/ota-legacy-20261023/ota-matching-rule-defaults.md`

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--ota-매칭-규칙-기본-설정"></a>
### OTA 매칭 규칙 기본 설정

2026-10-08 대화에서 직접 선택한 규칙과, 남은 질문에 추천값을 선택하라는 사용자 지시를 기록한다. 이후 실제 사례를 보며 변경할 수 있다.

이 문서는 규칙 설정의 기준이다. 현재 실행 코드와 운영 규칙 저장소에 모두 적용됐다는 뜻은 아니다. 이번 작업은 격리 worktree의 코드와 합성 테스트, 이 문서만 변경한다. 운영 DB와 실제 검토 DB는 변경하지 않는다. 기존 정확 연결 200건과 장부 734건의 보존 경계 및 production authority 전환 금지를 유지한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--사용자가-직접-선택한-규칙"></a>
#### 사용자가 직접 선택한 규칙

- 실제 결제 완료 또는 실제 환불 완료 근거가 있는 금전 이벤트만 카드 매칭 대상으로 삼는다. 예약 확정, 예정 결제, 환불 예정은 실제 결제로 승격하지 않는다.
- 같은 예약의 복수 결제와 환불은 각각 별도 이벤트로 보존한다. 취소 안내만으로 환불 이벤트를 만들거나 원 결제를 지우지 않는다.
- OTA 결제일과 카드 승인일을 비교한다. 매입일은 참고 정보다. 결제일이 없으면 카드 후보를 표시하지 않고 날짜 근거부터 확인한다.
- 승인한 업체별 날짜 차이만 허용하며, 빠름과 늦음의 방향도 지킨다. 검토 화면은 당일 및 승인한 방향과 범위 안의 모든 카드 거래를 표시한다.
- OTA 카드 끝자리가 있으면 반드시 일치해야 한다. 카드사 정보도 있으면 카드사와 끝자리를 모두 확인한다. 동일 끝자리의 여러 카드사가 후보이고 OTA 카드사를 모르면 HOLD로 둔다.
- OTA 카드 끝자리가 없으면 날짜, 정확 금액, 유일 후보, 업체 근거와 사용자 승인 merchant alias를 요구한다. 아래 동일 거래 묶음의 명시적 예외는 따로 적용한다.
- 승인한 merchant alias는 해당 OTA 업체 전체 상품에 적용한다. 이것만으로 비용 항목이나 여행을 정하지 않는다.
- 양쪽의 비교 가능한 승인번호가 있으면 일치해야 한다. 카드 끝자리, 승인번호, 날짜, 금액이 모두 맞으면 merchant 표기가 달라도 연결을 허용한다.
- 메일과 포털의 같은 결제 근거가 충돌하면 한쪽을 임의로 우선하지 않고 HOLD로 둔다.
- 외화는 원문 통화와 외화 금액을 정확히 비교한다. 외화가 같으면 원화 청구액 차이만으로 연결을 막지 않는다.
- 환불은 카드 취소·환불 방향 거래에만 연결한다. 원 결제와 환불을 서로 섞지 않는다.
- 실제 결제 근거가 있으나 카드 거래가 없으면 HOLD_NO_CARD로 유지한다. 새 카드 거래가 들어오면 관련 HOLD만 다시 대조한다.
- 수동 연결과 이미 확정된 배정은 근거가 바뀌어도 유지한다. 차이 또는 근거 변경 경고를 표시하고 사용자 확인 후 수정한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--tripcom-항공권-차액"></a>
#### Trip.com 항공권 차액

- 항공권 결제에만 적용한다. 숙박, 다른 상품, 환불에는 적용하지 않는다.
- 카드 청구액이 OTA 결제액보다 1,000원부터 10,000원까지 적은 경우를 허용한다.
- 차액은 정확히 1,000원 단위여야 한다. 허용 차액은 -1000, -2000, -3000, -4000, -5000, -6000, -7000, -8000, -9000, -10000원이다.
- 행사 기간과 결제수단 제한 없이 재사용한다. 나머지 카드, 날짜, 통화, 방향, 충돌 검사 조건은 충족해야 한다.
- 실제 할인 원인이 확인됐다고 표시하지 않는다. 사용자 승인 Trip.com 항공권 차액 규칙으로 표시한다.
- 정확 금액 연결을 먼저 배정하고 남은 거래에만 차액 규칙을 적용한다.
- 그 밖의 고정 차액 또는 할인율과 한도 규칙은 검증 가능한 근거와 승인한 조건 안에서만 적용한다. 포인트 적립은 청구액 할인으로 취급하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--동일-거래-묶음"></a>
#### 동일 거래 묶음

- 서로 다른 금액을 임의로 합산하는 방식이 아니다. 동일 날짜, 동일 금액 또는 승인 차액, 동일 통화, 동일 업체, 동일 상품 종류, 동일 카드와 동일 거래 방향의 반복 결제를 묶는다.
- 업체, 상품 종류, 카드사와 카드 끝자리, 결제와 환불 방향이 다르면 묶음을 분리한다. 이용기간이 달라도 묶을 수 있지만 예약별 이용기간은 따로 보존한다.
- 카드 끝자리가 없는 OTA도 나머지 동일 묶음 근거와 승인 alias가 충분하고 카드 후보가 하나의 카드로 한정되면 포함한다. 원본의 빈 카드 끝자리는 채워 넣지 않는다.
- 조건과 건수가 같으면 자동 완전 묶음 연결을 허용한다. 승인된 차액과 방향 있는 날짜 차이 규칙도 묶음에 적용한다.
- 건수가 다르면 특정 예약이나 카드를 임의로 고르지 않고 부분 대응 수량을 기록한다. OTA 3건과 카드 2건은 2건 대응, OTA 1건 미해결로 표시한다. OTA 2건과 카드 3건은 2건 대응, 카드 1건 미해결로 표시한다.
- 부분 묶음의 개별 여행 및 장부 배정은 구분 근거가 확보될 때까지 보류한다. 묶음에 포함된 카드는 다른 연결에 중복 사용하지 않는다.
- 부족한 카드가 추가되어 완전 묶음이 되면 다른 연결과 충돌하지 않는 범위에서 자동 전환한다. 기존 확정 연결은 유지한다.
- 완전 묶음에서 근거로 구분할 수 없는 개별 대응은 OTA 예약번호와 카드 승인번호 오름차순으로 배정한다. 예약번호가 같으면 OTA 이벤트 ID, 승인번호가 없거나 같으면 원본 카드 거래 ID 오름차순으로 보완한다.
- 위 정렬 대응은 사용자 승인 순서 배정으로 표시한다. 개별 결제 근거가 확인된 정확 연결로 표시하지 않는다. 각 예약의 검증된 이용기간을 사용한다.
- 나중에 실제 개별 대응이 확인돼 순서 배정과 다르면 기존 배정을 유지하고 차이를 표시하며 사용자 확인 후 변경한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--남은-질문에-선택한-추천-기본값"></a>
#### 남은 질문에 선택한 추천 기본값

아래 값은 이번 사용자 지시에 따라 선택한 추천 설정이다. 과거에 직접 답변한 사실로 표시하지 않는다.

- 메일과 포털의 중복 결제 증거는 공통 결제 식별값이나 명시 출처 연결 근거가 있을 때만 합친다. 같은 예약, 날짜, 금액, 카드라는 이유만으로 합치지 않는다.
- OTA 내부 결제 ID와 카드 승인번호는 서로 다른 식별 체계일 수 있다. 같은 의미와 체계로 검증된 값만 비교한다. 비교 불가능한 서로 다른 ID를 단순 문자열 비교해 충돌로 판정하지 않는다.
- 카드 점유는 전체 연결과 묶음에 걸쳐 확인한다. 기존 정확 연결과 사용자 연결은 우선 보존하고, 이미 다른 연결에 쓰인 카드의 재사용은 차단한다.
- duplicate_of, parse_error, conflict_reason이 있는 카드도 검토 화면에 표시하되 선택과 자동 배정에서 제외한다. 서버에서도 같은 조건을 검사한다.
- 후보 정렬이나 화면 표시만으로 자동 연결하지 않는다. 승인 규칙 적용 후에도 여러 서로 다른 묶음 구성이 가능하면 HOLD로 둔다.
- 할인율 규칙은 업체, 상품, 결제수단, 적용 기간, 최소 결제액, 할인율, 한도, 원 단위 계산 방식이 확인된 경우에만 제안한다. 부족한 조건을 임의로 채우지 않는다. Trip.com 항공권의 명시 차액 규칙은 위 별도 조건을 따른다.
- 새 수동 연결은 해당 연결만 저장하고 규칙은 제안 상태로 둔다. 이번 기본값 선택은 아직 발생하지 않은 모든 제안을 승인한 것으로 취급하지 않는다.
- 제안은 이번 건만, 규칙 저장, 조건 수정으로 답한다. 이번 건만은 이후 거래에 적용하지 않는다. 비활성 또는 철회 규칙은 승인 이력이 있어도 적용하지 않는다.
- 제안 질문은 확인된 차액과 날짜 차이, 카드, 업체, 상품, 적용 범위를 보여 준다. 할인 원인이나 결제수단을 추측해 사실로 적지 않는다.
- 원본 날짜, 금액, 통화, 거래 ID, 예약번호, 이용기간은 규칙으로 바꾸지 않는다. 자료 읽기 실패와 근거 부재를 구분하고 불완전한 자료로 신규 자동 연결하지 않는다.
- 새로운 자료나 새 규칙으로 사용자 확정, 보류, 기존 장부를 자동 변경하지 않는다. 미리보기의 근거가 바뀌면 다시 확인하게 한다.
- 규칙 변경은 버전과 변경 이유를 남긴다. 기존 확정에 소급 적용하지 않고, 미해결 및 이후 이벤트에 우선 적용한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--실행-상태"></a>
#### 실행 상태

2026-10-08 구현이 격리 worktree에 반영됐다. 기본 설정은 `config/ota-matching-defaults.json`에 두고 `app/ota_matching_defaults.py`가 설정을 읽는다. 업체 전체 merchant alias와 좁은 승인 규칙을 분리했다. Trip.com 항공권 차액 기본값은 카드 금액이 OTA보다 1,000원부터 10,000원까지 적고 1,000원 단위인 실제 결제에만 적용한다. 할인 원인을 확인한 사실로 표시하지 않는다. 정확 금액 후보를 먼저 평가한다.

매칭은 실제 결제 완료 또는 환불 완료 근거, OTA 결제일, 거래 방향, 통화 금액, 카드 끝자리와 카드사, 비교 가능한 같은 체계의 승인번호, 승인된 날짜 방향과 범위를 검사한다. 날짜 차이는 카드 승인일에서 OTA 결제일을 뺀 부호 있는 값으로 저장한다. 결제일이 없으면 카드 후보를 반환하지 않는다. 기존 연결은 전체 거래에서 먼저 점유시킨다. 자료 읽기 오류와 상충 근거는 새 자동 연결을 차단한다.

반복 거래는 provider, 상품, 결제 유형, 날짜, 금액 또는 승인 차액, 통화로 먼저 분리하고, 실제 카드 후보의 발급사·끝자리·방향별로 다시 나눈다. 금액을 임의 합산하지 않는다. 부분 묶음은 양쪽 건수와 ID 전체를 보존하고 개별 연결·장부 배정을 차단한다. OTA 2건과 카드 1건의 기존 HOLD_AMBIGUOUS 상태도 유지하면서 2:1 건수, 대응 수와 카드 예약을 표시한다. 건수가 같으면 예약 번호와 OTA 이벤트 ID, 승인번호와 카드 거래 ID 순으로 정렬해 사용자 승인 순서 배정으로 표시한다. 동일 최적해가 여러 개인 단건 전역 배정은 임의로 고르지 않고 HOLD한다. 개별 결제 근거와 구분하고 예약별 이용 기간은 그대로 보존한다.

기존 확정 링크와 frozen 그룹 카드 ID는 이벤트 원문이 현재 입력에 없거나 그룹 조건이 바뀌어도 전체 자동 후보, 수동 연결, 장부 후보에서 계속 점유한다. frozen 그룹은 이벤트·카드 전체 자료와 후보 edge의 지문도 고정한다. 매핑 카드가 현재 후보여도 evidence 지문이나 후보 edge가 달라지면 정상 연결로 표시하지 않고 재확인 경고와 HOLD를 유지한다.

기존 분리 검토 저장소 흐름을 사용한다. 새 연결만 저장하고, 규칙 제안은 사용자가 승인하기 전까지 비활성으로 둔다. 이번 건만 처리는 이후 거래에 적용하지 않는다. 합성 pin 검증은 200개 및 734개 기존 연결 크기 각각에서 연결 ID와 원문 금액이 유지되는지만 확인했다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--추가-acceptance-전의-이전-targeted-결과"></a>
##### 추가 acceptance 전의 이전 targeted 결과

- 후속 관련 파일 targeted 명령: `python -m pytest tests/card_pipeline/test_ota_matching_defaults.py tests/card_pipeline/test_ota_review.py tests/card_pipeline/test_ota_payments.py tests/card_pipeline/test_review_holds.py webapp/tests/test_ota_payment_review.py webapp/tests/test_card_flow.py -q`
- 결과: 171 passed, 37 subtests passed.
- 합성 Chromium 브라우저에서 390×844와 1440×900 화면을 확인했다. 후속 추가 acceptance의 최신 브라우저 결과는 아래 검증 섹션을 따른다.
- 임시 SQLite 저장소에서 요청 재시도 멱등성, 요청 ID 재사용 충돌, 바뀐 순서의 명시적 재확인, GET 조회의 무기록을 확인한다. 장부 경계는 부분 묶음 hold가 preview·commit과 projection 호출 차단까지 이어지는지 합성 검사한다.
- Python 문법, 설정 JSON과 `git diff --check`가 통과했다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--미검증"></a>
##### 미검증

- 운영 DB·운영 규칙 저장소 반영, production authority 전환, 재대사, 재분류, 장부 기록, 재시작과 자료 새로고침은 수행하지 않았다.
- 실제 200건 정확 연결과 장부 734건의 운영 parity를 다시 실행하지 않았다. 위 검사는 합성 입력만 사용했으며 운영 숫자를 새 검증 결과로 주장하지 않는다.
- 모든 OTA 원천에서 카드사와 승인번호 체계가 제공되는지는 검증하지 않았다. 비교 체계를 확인할 수 없는 ID는 서로 비교하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--2026-10-08-검토-보완-반영"></a>
#### 2026-10-08 검토 보완 반영

| 검토 계약 | 상태 | 코드와 검증 |
|---|---|---|
| 날짜 범위의 양쪽 부호와 중간 날짜 전체 표시 | 구현·합성 검증 | `same_date_cards`가 승인된 signed lag 범위의 날짜를 전부 표시한다. |
| signed lag의 저장소·API·화면 계약 | 구현·합성 검증 | core, 질문 생성기, UI와 API parser가 -7부터 +7까지 같은 계약을 쓴다. 음수 approve/edit를 실제 localhost HTTP 테스트로 확인한다. |
| 부분 묶음 전역 카드 예약과 장부 차단 | 구현·합성 검증 | 예약 ID가 전체 검토 snapshot, 수동 선택 API, 카드 흐름 preview·commit hold로 전달된다. 합성 장부에서 ready 0, projection 0회, ledger row 0건을 확인한다. |
| 카드 정보가 없는 반복 거래와 부분 건수 | 구현·합성 검증 | 반복 signature에서 OTA 카드 필드를 제외한다. 부분 건수와 양쪽 ID 전체를 보존하고, 동일 카드 조건을 만족하는지 검사한다. |
| 정확 금액 우선 전체 배정 | 구현·합성 검증 | 승인된 모든 edge를 유지하고 전체 배정에서 exact edge를 우선한다. exact와 할인 허용액이 경쟁하는 반복 사례를 확인한다. |
| 그룹과 singleton 후보의 전역 충돌 | 구현·합성 검증 | 겹치는 카드 후보를 사전 검사해 그룹 입력 순서와 무관하게 충돌 전체를 HOLD한다. |
| frozen 순서와 재확인 | 구현·합성 검증 | 분리 SQLite 저장소에 그룹 ID, 매핑, 정렬 근거, 승인자와 버전을 저장한다. GET은 쓰지 않는다. 재시도는 멱등이며 본문이 다른 request ID 재사용은 거부한다. 변경된 완전 그룹은 확인 전 HOLD하고 새 제안 확인 후에만 교체한다. |
| 장부 차단 경계 | 구현·합성 검증 | 화면 문구뿐 아니라 preview·commit의 hold projection과 web adapter 연결을 확인한다. |
| payment ID와 issuer 모호성 | 구현·합성 검증 | 같은 명시 scheme을 가진 payment ID만 비교한다. issuer 미상에서 같은 끝자리의 복수 issuer 후보는 HOLD한다. |
| provider·issuer 별칭 | 구현·합성 검증 | `AGODA.COM`은 승인 출처·버전이 있는 명시 record다. 이전 정적 alias는 사용자 승인으로 승격하지 않는다. 동적 별칭은 화면과 HTTP API에서 명시 승인 후 저장·적용한다. |
| 할인율·한도와 원 단위 계산 | 구현·합성 검증 | 좁은 규칙에 할인율, 한도, 최소액, 반올림 방식, 결제수단과 기간을 요구한다. 확인되지 않은 행사 값은 활성화하지 않는다. 기본 활성 할인은 승인된 Trip.com 항공 charge 단계 차액뿐이다. |

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--총괄-재현-회귀"></a>
##### 총괄 재현 회귀

- `test_stable_group_tiebreak_uses_approval_order_after_booking_order`: 예약 A의 e1을 승인번호 A인 카드 z에, 예약 B의 e2를 승인번호 Z인 카드 a에 연결한다.
- `test_card_claimed_by_an_absent_linked_event_is_excluded_from_repeated_group`: 없는 기존 이벤트가 점유한 카드 a를 제외한다. 두 새 이벤트와 남은 카드 b는 2:1 HOLD_AMBIGUOUS이며 대응 건수 1과 b 예약을 보존한다.
- `test_repeated_events_with_distinct_known_cards_form_separate_groups`: 끝자리 2042인 e1은 카드 a, 9999인 e2는 카드 b에 각각 연결한다.
- `test_equal_optimum_singleton_candidates_across_signatures_hold_as_a_component`: 서로 다른 항목의 단건 후보가 같은 최적 배정을 만들면 모든 연관 이벤트와 카드 후보를 HOLD한다.
- frozen 그룹의 source 누락·signature 변경·후보 edge 변경 테스트는 고정 카드 예약과 재확인 경고를 확인한다. review adapter 테스트는 source가 사라진 pin 카드도 수동 선택과 장부 preview·commit에서 막는지 확인한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--남은-제한"></a>
##### 남은 제한

- 고정 그룹에 건수 차이를 만드는 카드나 OTA 이벤트가 추가되면 계속 HOLD한다. 완전한 일대일 제안이 생기기 전에는 새 배정을 확정할 수 없다.
- 여러 OTA 업체의 임의 행사 조건을 자동으로 찾거나 활성화하지 않는다. 사용자가 출처와 조건을 승인한 할인 규칙만 저장할 수 있다.
- 운영 데이터의 payment ID scheme, merchant와 issuer 분포는 확인하지 않았다. 운영 parity와 실제 자료 검증은 미실행 상태다.



<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--추가-acceptance-계약-및-검증-상태"></a>
#### 추가 acceptance 계약 및 검증 상태

- 날짜 규칙은 `date_lag_min_days`와 `date_lag_max_days`를 함께 저장하며 양 끝을 포함한다. -1부터 +2까지면 -1, 0, +1, +2일을 후보로 표시하고 -2와 +3일은 제외한다. 기존 `date_lag_days`는 양수면 0부터, 음수면 해당 일수부터 0까지의 범위로 읽는다. 새 범위와 기존 scalar를 한 규칙에 함께 저장하지 않는다.
- 부분 그룹의 후보 카드 점유는 화면과 API 요청 처리 중에만 유지한다. 부분 그룹은 검토 저장소의 영구 allocation이나 개별 link로 저장하지 않는다. 저장 거부 뒤 합성 데이터베이스에 관련 row가 없어야 한다. 전체 그룹을 사용자가 확인하면 하나의 고정 그룹 allocation으로 저장하고 그 카드 전부를 다른 그룹의 자동·수동 후보에서 막는다.
- 카드 끝자리가 없는 이벤트는 자동 반복 그룹에 일반화하지 않는다. 실제 대응은 별도 사용자 확인 경로로 저장할 수 있으며, 원문에 없는 카드 힌트를 만들지 않는다.
- 승인된 차액 조건은 만족하는 event-card edge에만 적용한다. exact와 차액 후보를 구분하고, 서로 다른 업체·상품·사용자 규칙 조건을 한 범위로 넓히지 않는다. 제안 승인 전 활성 규칙 수는 0이다. 승인 뒤에도 업체, 상품, merchant, 카드, 적용 날짜, 통화, 환불 여부와 단계 금액의 승인 범위를 벗어난 거래에는 재사용하지 않는다.
- 합성 보존 검사는 synthetic 200개 연결과 수동 연결 snapshot의 ID, 원문 금액, 날짜, 근거 원문을 비교한다. overwrite 수는 0이어야 한다. 이 검사는 운영 200건 parity를 다시 실행한 결과가 아니다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--이번-추가-acceptance-실행-결과"></a>
##### 이번 추가 acceptance 실행 결과

아래 명령은 추가 조건에 필요한 targeted subset만 실행했다. 전체 회귀는 실행하지 않았다.

| acceptance | 관찰 테스트 | 실행 결과 |
|---|---|---|
| 1 | `test_acceptance_01_partial_group_is_temporary_and_never_written_to_allocation_store` | HTTP/API targeted 묶음 통과 |
| 2, 3 | `test_acceptance_02_03_full_group_confirmation_persists_one_group_and_blocks_all_card_reuse` | HTTP/API targeted 묶음 통과 |
| 4, 5, 8 | `test_acceptance_04_05_signed_lag_range_round_trips_over_http_sqlite_and_matcher` | 승인 전 활성 규칙 0, -1..+2 SQLite 저장과 매처 적용 확인 |
| 6 | `test_acceptance_06_blank_hint_group_needs_ui_confirmation_and_persists_only_the_confirmed_mapping`; `test_acceptance_06_blank_card_hint_requires_confirmation_then_stores_actual_group` | HTTP/API와 매처 targeted 명령 통과 |
| 7, 9 | `test_acceptance_07_approved_delta_is_limited_to_its_full_edge_scope`; `test_acceptance_07_item_scoped_rule_exposes_exact_and_delta_edges_separately`; `test_acceptance_07_saved_delta_rules_keep_exact_and_delta_edges_in_their_own_scope` | 매처와 저장소 targeted 명령 통과 |
| 10 | `test_acceptance_10_refresh_never_overwrites_two_hundred_manual_source_snapshots` | 합성 200개, snapshot overwrite 0 확인 |
| 화면 | `test_synthetic_browser_group_candidates_disabled_proposal_and_overflow`; `test_synthetic_browser_submits_signed_lag_range_without_legacy_scalar` | Chromium 합성 브라우저에서 390x844와 1440x900 검증 통과 |

- `python -m pytest tests/card_pipeline/test_ota_matching_defaults.py -k 'acceptance_04 or acceptance_06 or acceptance_07 or acceptance_10 or group_signature_ignores_missing_ota_card_facts' -q` — 6 passed, 37 deselected.
- `python -m pytest tests/card_pipeline/test_ota_review.py::test_acceptance_07_saved_delta_rules_keep_exact_and_delta_edges_in_their_own_scope -q` — 1 passed.
- `python -m pytest webapp/tests/test_ota_payment_review.py -k 'acceptance_01 or acceptance_02_03 or acceptance_04_05 or acceptance_06' -q` — 4 passed, 26 deselected.
- `python -m pytest webapp/tests/test_ota_matching_defaults_browser.py -k 'signed_lag_range or group_candidates_disabled_proposal_and_overflow' -q` — 3 passed, 1 deselected.
- 총 14개 targeted 테스트가 통과했다. 합성 입력과 임시 SQLite 결과이며 운영 자료나 운영 parity를 검증하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--실제-운영-자료-읽기-전용-parity--2026-10-08"></a>
#### 실제 운영 자료 읽기 전용 parity — 2026-10-08

합성 acceptance 이후 현재 feature 코드로 운영 자료를 읽기 전용 대조했다. 기존 exact pair의 OTA 이벤트 ID, provider, booking_ref, transaction_id, source/evidence digest와 카드 source_hash를 개별 비교했다.

- 기존 실제 exact 200건 중 200건 모두 동일 이벤트와 카드 거래로 유지됐다. 변경 0, 누락 0, 근거 또는 카드 원문 해시 차이 0이다.
- 카드 중복 배정 0, 사용자 확정·수동 연결 overwrite 0, 기존 exact 카드 재사용 0, 기존 1:1 exact의 묶음 전환 0이다.
- 전체 이벤트 1,304건, actual payment 383건, matched 200건, HOLD 183건이다. 새 auto match 0건, 새 그룹 연결·후보 0건이다. HOLD는 카드 없음 124건, 결제일 미확인 59건으로 계산됐다.
- 운영 전체 테이블 75개와 schema를 실행 전후 비교했다. 변경 0이며 장부 734건을 유지했다. 등록·보존 원본 파일 963개와 운영 코드, 보호 사용자 파일도 변경 0이다.
- SQLite 연결은 mode=ro와 query_only로 제한했고 쓰기 연결을 실행 중 거부하도록 했다. review DB·폴더 생성 0, 운영 자료 폴더의 새 파일 0이다. 새 결과를 운영에 저장하지 않았다.
- 운영 재시작, source refresh, 재수집, 재분류, production authority 전환을 수행하지 않았다. 기존 targeted 14 passed 결과를 재사용했고 추가 테스트·전체 회귀는 실행하지 않았다.

상세 pair 비교와 계산 결과는 `C:/AX/cost/.local-archive/ota-defaults-parity-20261008/`에만 보존한다. 실제 예약·거래 식별자와 원문 자료는 Git에 포함하지 않는다. 앞선 미검증 항목 중 운영 parity는 이 단계에서 확인했으며, 운영 배포와 실제 검토 저장은 여전히 미실행이다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--tripcom-항공료-표기와-정확-가맹점-보정--2026-10-09"></a>
#### Trip.com 항공료 표기와 정확 가맹점 보정 — 2026-10-09

기존에 승인된 Trip.com 항공 차액 규칙이 실제 운영 표기를 놓치고 있어 설정 두 곳만 보정했다. 새 -4,000원 전용 규칙은 만들지 않았다.

- `trip_flight_charge_delta.item_values`에 `항공료`를 추가했다. 기존 `항공`, `항공권`, `flight`, `airfare`는 그대로 유지한다. 항목 동의어 보정이며 새 할인 규칙이 아니다.
- `provider_merchant_alias_records.trip`에 정확 문자열 `대표_카카오페이-트립닷컴`을 `approved`, version 2, source `user-approved-trip-airfare-exact-descriptor-2026-10-09`로 추가했다.
- 기존 `trip.com`, `trip.com korea` alias는 candidate 그대로 둔다. 넓은 `트립닷컴`은 승인하지 않았다. 사전 dry-run에서 넓은 별칭은 후보 40건과 HOLD_AMBIGUOUS 2건, 묶음 관련 HOLD 19건을 만들어 영향 범위가 크다고 판단했다.
- OTA 원천에 카드 끝자리가 없으면 미확인으로 유지한다. 카드 측 후보의 끝자리를 OTA 사실로 승격하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--검증"></a>
##### 검증

- 직접 관련 targeted: `python -m pytest -q tests/card_pipeline/test_trip_airfare_descriptor.py tests/card_pipeline/test_ota_matching_defaults.py` — 77 passed. 전체 회귀는 실행하지 않았다.
- 새 테스트(`test_trip_airfare_descriptor.py`)는 `항공료` 포함 5개 항목값, 정확 alias의 버전·출처, 다른 Trip.com 표기의 승인 비상속, -1,000~-10,000원 1,000원 단위 유지와 범위 밖 HOLD, 숙박·환불·다른 업체 비적용, 정확 금액 우선, 복수 후보 HOLD, 기존 exact 카드 재사용 금지, OTA 카드 끝자리 미생성을 합성 입력으로 확인한다.
- 운영 읽기 전용 parity(변경된 실제 설정으로 계산, 운영 DB·review DB 해시 전후 동일):

| 항목 | 결과 |
|---|---|
| 기존 exact 200건 변경 / 누락 | 0 / 0 |
| 카드 중복 배정 | 0 |
| 수동 연결 overwrite | 0 |
| 신규 MATCHED_AUTO | 3 (모두 Trip.com 항공료, 날짜 차이 0일, 차액 -4,000원, 후보 1개, OTA 카드 끝자리 미확인) |
| HOLD | 182 → 179 (HOLD_NO_CARD 120, HOLD_DATE_UNKNOWN 59) |
| 신규 HOLD_AMBIGUOUS / 신규 그룹 연결 | 0 / 0 |
| 다른 할인 차액의 신규 연결 | 0 |

- 신규 3건은 모두 기존 `approved_trip_flight_delta` 규칙으로 연결됐다. 같은 날짜 카드 거래를 전부 대조했고 기존 exact·수동 카드와의 충돌은 없었다.
- 운영 DB 쓰기, review DB 쓰기, production authority 전환, 재시작은 수행하지 않았다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md--2026-10-14-사용자-승인-반영"></a>
#### 2026-10-14 사용자 승인 반영

- 트립닷컴 카드 가맹점명 `트립닷컴(구)_NICE`를 정확 문자열 별칭으로 승인했다(`user-approved-trip-card-descriptor-2026-10-14`, version 1). 넓은 `트립닷컴` 표기는 승인하지 않았다. 이 별칭으로 같은 금액·날짜·방향의 카드 거래가 있던 트립 예약 31건이 연결 후보가 되었다. 반복 결제가 겹치는 건은 자동 연결하지 않고 묶음 확인으로 보낸다.
- 카드 거래는 있으나 별칭이 승인되지 않아 연결하지 못한 경우의 사유를 `exact_card_needs_descriptor_approval`로 분리했다. "맞는 카드 거래 없음"과 구분해 표시한다.
- 클룩 "전액을 결제 완료했습니다 / 추가 결제 금액은 없습니다" 양식은 "결제 금액" 값을 실제 결제액으로 읽는다. 포인트를 뺀 값이다. 클룩 가맹점 별칭 `klook`은 아직 승인하지 않았다.
- 아고다 선결제(포털 prepaid) 자료는 아직 결제 근거로 인정하지 않는다. 결제일이 자료에 없어 날짜 근거가 먼저 필요하다.

---

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md"></a>

## ota-matching-terms

통합 전 경로: `docs/archive/ota-legacy-20261023/ota-matching-terms.md`

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--ota-결제와-카드-거래의-용어와-정확-매칭-기준"></a>
### OTA 결제와 카드 거래의 용어와 정확 매칭 기준

이 문서는 카드 거래와 OTA 결제를 연결할 때 쓰는 날짜·금액·식별 용어를 한 곳에 정리한다. 같은 말을 문서·코드·화면에서 다른 뜻으로 쓰지 않는다. 구현은 `app/ota_payments.py`의 `pair_check`와 `app/ota_exact.py`의 게이트이며, 2026-10-16 기준이다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--1-날짜-용어"></a>
#### 1. 날짜 용어

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--카드-쪽"></a>
##### 카드 쪽

| 용어 | 뜻 | 저장 위치 | 대사에 쓰는가 |
|---|---|---|---|
| 이용일 | 명세에 적힌 실제 사용일 | `transactions.approval_date` (명세에 이용일 열이 있을 때) | 예. 카드 날짜의 1순위 |
| 승인일 | 카드사가 결제를 승인한 날 | `transactions.approval_date` (이용일이 없을 때) | 예. 카드 날짜의 2순위 |
| 매입일(정산일) | 카드사가 가맹점에 대금을 정산한 날. 승인 뒤 보통 1~4일 뒤 | `transactions.posting_date` | 아니오. 참고만 한다 |

- `approval_date` 칸에는 이용일 또는 승인일이 들어간다. 열 이름과 달리 "카드 원본의 사용 날짜"다(`app/import_card.py` 열 별칭, `app/reconciliation.py`의 `card_use_date`).
- 승인일이 없는 행은 매입일을 처리 날짜로만 쓴다. 승인일 칸을 채워 만들지 않는다(`docs/card_pipeline.md`).

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--ota-쪽"></a>
##### OTA 쪽

| 용어 | 뜻 | 근거와 저장 | 대사에 쓰는가 |
|---|---|---|---|
| 실제 결제일 | OTA가 고객 카드에 실제로 청구한 날 | 결제 완료 메일의 발송일(한국 시간, `app/ota_mail.py`의 `sent_day`). 포털에 명시된 날짜가 있을 때만 그 날짜 | 예. 카드 승인일과 비교하는 기준 |
| 예정 결제일 | 메일에 명시된 자동 결제 예정일, 포털의 자동결제 예정일 | `scheduled_charge_day`, 포털 `future_due:auto_charge_scheduled_*`. 결제 완료가 아니다 | 아니오. 다만 카드 원행의 이용일이 예정일과 같고 금액·카드가 맞을 때만 결제로 인정한다(§5 결정 2) |
| 이용기간 | 숙박 체크인~체크아웃, 항공 출발~도착 | `period`, `service_period` | 여행 배정에만 쓴다 |
| 예약일 | 예약을 만든 날 | 메일 본문 | 아니오 |
| 관측 시각 | 포털 페이지를 읽은 시각(`observed_at`) | 포털 기록 | 아니오 |
| 취소 기한 | "9월 24일부터 환불 불가" 같은 정책 문구의 날짜 | 포털 상세 페이지 | 아니오. 결제일이 아니다 |
| "오늘 결제됨" | 포털 결제 상태 문구 | `portal_payment_state` | 아니오. 날짜가 아니다 |

- 포털 결제에는 실제 결제일이 없다. 그래서 현재 포털 근거만으로는 결제일 조건을 채울 수 없다(§4 설정 참조).
- 원화 결제는 카드 승인일과 실제 결제일이 **같은 날**이어야 한다. 외화 결제는 하루까지 날짜 차이를 허용한다(소유자 2026-10-16). 그 밖의 날짜 차이는 업체별로 승인된 범위만 허용한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--2-금액과-식별-용어"></a>
#### 2. 금액과 식별 용어

- **원화 금액**: 카드 `amount_krw`와 OTA 원화 청구액이 정확히 같아야 한다. 할인이 확인되지 않은 차액은 허용하지 않는다. 승인된 Trip.com 항공 차액 규칙만 예외다.
- **외화 금액**: 통화 코드와 금액이 모두 정확히 같아야 한다. 환율로 환산하지 않는다. 외화 결제는 카드 날짜와 결제일이 하루까지 달라도 된다(`foreign_date_lag_days`).
- **카드 끝자리·카드사**: OTA 원문에 끝자리가 있으면 카드 끝자리가 같아야 한다. 카드사 정보가 있으면 카드사도 같아야 한다.
- **승인번호**: 양쪽이 같은 체계로 비교될 때만 쓴다. 체계가 다르면 비교하지 않는다.
- **업체 근거**: 카드 끝자리가 없는 OTA 결제는 승인된 가맹점 별칭, 또는 승인된 규칙이 있어야 한다. 트립닷컴은 2026-10-15 승인에 따라 날짜·금액·유일 후보로 판단한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--3-정확-매칭-판정-순서"></a>
#### 3. 정확 매칭 판정 순서

`app/ota_payments.py`의 `pair_check(event, row)`가 이 순서로 한 쌍을 검사한다. 통과하면 `None`, 막히면 사유 코드를 돌려준다.

| 순서 | 검사 | 막힐 때 사유 코드 | 화면 문구 |
|---|---|---|---|
| 0 | 카드 행에 중복·파싱 오류·원본 충돌이 없다 | `row_flagged` | 중복이나 오류가 있는 카드 거래 |
| 1 | 실제 결제일이 있다(포털 결제는 설정에 따라) | `payment_date_unknown` | 결제일 근거 없음 · 날짜 확인 필요 |
| 2 | 카드 끝자리와 카드사가 맞다 | `card_identity` | 카드 끝자리나 카드사가 맞지 않음 |
| 3 | 거래 방향이 맞다(구매↔결제, 환불↔환불) | `direction` | 거래 방향이 맞지 않음 |
| 4 | 원화 금액 또는 외화 통화·금액이 정확히 맞다 | `amount` | 카드 금액과 결제 금액이 맞지 않음 |
| 5 | 원화는 같은 날, 외화는 하루까지, 그 밖은 승인된 업체별 차이만 허용 | `date` | 카드 날짜와 결제일이 맞지 않음 |
| 6 | 카드 끝자리 재확인 | `card_identity` | 카드 끝자리나 카드사가 맞지 않음 |
| 7 | 업체 근거(끝자리, 승인번호, 승인된 별칭·규칙, 트립닷컴 예외) | `corroboration` | 업체 근거(승인된 가맹점 별칭) 없음 |

1:1 점유와 중복 후보는 기존 전역 대사(`extend_report`, `match_ota_payment_events`)가 맞춘다. 같은 날짜·금액의 반복 결제 묶음은 **여행 단위로만** 배정하고 예약번호를 한 행에 고르지 않는다(`docs/business_rules.md` 81행). 단, 포털 동일 묶음의 1:1 예약 연결(`app/ota_portal.py` `_identical_group_matches`)은 아직 예약번호를 행마다 붙인다. §5의 5번 항목이다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--4-적용-범위와-실패-방향"></a>
#### 4. 적용 범위와 실패 방향

- **게이트 대상**: 기존 OTA 대사가 "연결"로 보는 거래 중, 아직 장부에 기록되지 않았고 사용자·소유자 결정이 없고 보존 상태가 아닌 거래(`app/ota_exact.py`의 `open_transaction_ids`). 기록된 거래의 배정은 건드리지 않는다.
- **막힌 연결**: 자동 배정하지 않고 사유와 함께 미연결로 둔다. 장부 기록은 하지 않는다. 이용기간을 아는 행은 막힌 연결의 추론 배정도 막는다(결제 월로 다른 여행을 고르지 않는다, 2026-10-03 추론 규칙). 이미 저장된 행별 추론 규칙은 건드리지 않는다.
- **근거를 못 읽을 때**: OTA 원천을 읽지 못하면 열린 거래의 연결을 모두 막는다(닫힌 쪽으로 실패).
- **끄는 방법**: 환경변수 `WEBLEDGER_OTA_EXACT_GATE=0`(재시작 필요).
- **포털 결제일 설정**: `config/ota-matching-defaults.json`의 `portal_payment_date_required`. 기본값은 `true`다.
- **포털 예정 결제 설정**: `portal_scheduled_card_date_enabled`. 기본값은 `true`다. 끄면 §5 결정 2 연결을 만들지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--5-2026-10-16-소유자-결정-반영"></a>
#### 5. 2026-10-16 소유자 결정 반영

1. **기록된 OTA 거래 283건**: 재검토로 되돌렸다. 소유자 결정 40건(사용자 결정 30, 소유자 규칙 7, 사용자 예외 3)과 환불·취소 짝 등은 유지했다. 이동 대상은 189건이다. 장부 행과 금액은 그대로이고 미배정 탭으로 옮겼다. 이 행들은 재분류가 덮어쓰지 않는다. 이력은 `board_revisions`와 `change_log`에 남았다.
2. **1015_오제 8건**: 결제일 근거가 없어서 재검토 대상에 포함했다. 이 8건은 제가 스크립트로 넣은 배정이라 "사용자 결정"으로 표시돼 있었다.
3. **포털 결제일**: 소유자가 모른다고 답했다. 기본값(결제일 필수, `portal_payment_date_required: true`)을 유지한다.
4. **외화 하루 차이**: 허용했다(`foreign_date_lag_days: 1`). 원화는 같은 날만 허용한다.
5. **가맹점 별칭**: `AGODA`, `AGODA_NICE-Agoda`, `BOOKING.COM`을 승인했다(`config/ota-matching-defaults.json`, 출처 `owner-approved-2026-10-16-*`).
6. **포털 동일 묶음의 예약번호**: 새 분류부터 행마다 예약번호를 고르지 않고 묶음 건수만 남긴다. 기존 기록은 바꾸지 않았다.
7. **자동결제 예정일 = 카드 이용일 (결정 2, 코드 반영)**: 포털에 실제 결제일이 없고 `future_due:auto_charge_scheduled_YYYY-MM-DD`로만 예정된 예약은, 카드 원행의 이용일이 그 날짜와 같고 총액(KRW)·카드 끝자리·아고다 가맹점이 맞을 때만 그 원행과 연결한다. 예약은 확정이고 취소·환불이 없어야 하며, 원행과 예약이 일대일로만 맞아야 한다. 예약 상태가 예정에서 확정으로 바뀐 충돌(`upcoming`→`confirmed`)만 허용하고 다른 충돌은 막는다. 검사는 `app/ota_portal.py` `scheduled_card_date_matches`와 `app/ota_exact.py` `_scheduled_card_reason`이다. 이 규칙으로 연결된 예약은 이용기간 여행으로 배정된다. 장부 기록은 분류 실행 때 따로 이뤄진다. 운영 authority 모드에서는 최신 스냅샷의 `scheduled_card_ids`에 든 카드 원행을 OTA-first 확정으로 본다(2026-10-16 소유자 결정 A).

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--6-2026-10-16-적용-결과"></a>
#### 6. 2026-10-16 적용 결과

- 운영 데이터에서 열린 거래를 기준으로 계산한 결과, 게이트가 막는 대상은 아고다 포털 7건(결제일 없음), 부킹닷컴 외화 2건(날짜 차이)이다. 트립닷컴 17건과 클룩 2건은 통과한다.
- 기록된 연결 중 같은 기준으로 막힐 항목은 아고다 포털 107건과 연결 이벤트가 없는 1건, 부킹닷컴 17건이다. 바꾸지 않고 소유자 결정으로 넘긴다.
- 2026-10-16에 직접 배정한 카드 8건(8835 카드 9월 24일 결제, 1015_오제 숙박비)은 결제일 근거가 없다. 금액과 숙박일이 맞지만 같은 기준으로 보면 확인이 필요하다. 기록은 그대로 두었다.
- 운영 적용(커밋 `1d83102`): 미기록 거래 중 2개 배치의 5건만 분류가 바뀌었다(추론 배정 4건, 환불 1건). 기록된 거래는 바뀌지 않았다. 기존 아고다 7건은 소유자의 저장된 행별 추론 규칙이 여행을 유지한다.
- 권한 가드: 운영 서버는 OTA 검토 권한 모드(`authority`)로 돌아간다. 코어가 확정하지 않은 OTA 거래는 새로 기록하지 않는다. 이 문서 작성 시점에 기록된 OTA 거래 552건 중 283건은 코어 확정 결과가 없다. 기록 가드는 신규 기록에만 적용되므로 이 기존 기록은 소유자 검토가 필요하다.

<a id="src-docs-archive-ota-legacy-20261023-ota-matching-terms-md--7-관련-코드와-테스트"></a>
#### 7. 관련 코드와 테스트

- 판정: `app/ota_payments.py` `pair_check`, `portal_payment_date_required`
- 게이트: `app/ota_exact.py` `apply_gate`, `open_transaction_ids`
- 분류 연결: `webapp/card_flow.py` `_compute_ota_report`, `_review_rules`, `_link_diagnosis_label`
- 테스트: `tests/card_pipeline/test_ota_exact_gate.py`. 이전 설계를 명시적으로 검사하는 기존 테스트는 `portal_payment_date_required`를 끄고 돌린다.

---

<a id="src-docs-archive-ota-legacy-20261023-ota-mail-md"></a>

## ota_mail

통합 전 경로: `docs/archive/ota-legacy-20261023/ota_mail.md`

<a id="src-docs-archive-ota-legacy-20261023-ota-mail-md--ota-메일-분류와-대조"></a>
### OTA 메일 분류와 대조

<a id="src-docs-archive-ota-legacy-20261023-ota-mail-md--2026-10-08-ota-자료-통합"></a>
#### 2026-10-08 OTA 자료 통합

운영 데이터 폴더의 `ota-sources.json`에 메일 디렉터리 5곳, 포털 데이터베이스 11개, 과거 조사와 예약 후보 문서 53개를 등록했다. 메일 원문은 중복을 제외하면 1,670건이다. 포털 사본은 예약 근거를 개별 비교했으며 모두 기존 원본과 같거나 그 일부였다. 원본을 옮기거나 삭제하지 않고 함께 조회한다.

현재 대조는 `app/ota_sources.py`에서 등록 목록을 읽고, `app/ota_mail.py`와 `app/ota_portal.py`에서 전체 자료를 함께 판단한다. 같은 메일 ID의 다른 본문은 충돌로 처리한다. 포털은 데이터베이스마다 따로 연결하지 않고 전체 예약과 카드 거래의 일대일 관계를 확인한다. 결제 예정과 실제 결제, 예약 확정과 이용 완료를 구분한다. 과거 조사 문서는 참고 자료이며 결제 또는 여행 배정 권위로 자동 승격하지 않는다.

등록 목록과 자료 내용의 해시가 바뀌면 캐시를 다시 계산한다. 명시 등록한 자료를 읽지 못하면 오류를 표시하고 새 OTA 분류와 권위 메타데이터 사용을 막는다. 미연결 표시에는 결제 근거 미검증, 결제 예정, 같은 카드 예약 후보와 금액 불일치, 기간 미확인, 예약 충돌과 거래 모호성을 구분한다. 자료 경로와 고객 원문은 화면에 출력하지 않는다.

운영 읽기 전용 대조에서 기존 정확 연결 198건을 모두 보존했고, 과거 포털 결제 표현에서 누락됐던 2건을 추가로 확인해 전체 기간의 정확 연결은 200건이다. 현재 검토 기간의 OTA 결제 375건은 정확 연결 178건, 비용 항목 후보 20건, 미연결 177건으로 구분한다. 미연결을 모두 해결한 것으로 보고하지 않는다.

146,018원 거래에는 예약 근거가 표시된다. 이는 실제 이용 완료를 뜻하지 않으며 기존 사용자 보류는 유지한다. 64,814원의 과거 후보는 96,842원 및 결제 예정 자료와 맞지 않아 확정 연결하지 않는다. 재수집이나 사용자에게 같은 자료를 다시 요청하지 않고 보존 자료와 차이를 먼저 확인한다.

표적 검증 결과는 `158 passed, 41 subtests passed in 29.69s`다. 등록 목록 적용 전에는 운영 데이터베이스의 전체 75개 테이블이 사본과 같았다. 서버 재시작 후에는 프로세스 실행 이력인 `rule_process_leases`만 추가·갱신됐고 나머지 74개 테이블과 스키마는 같았다. 같은 대조 요청의 결과도 동일했다. 기존 장부 734건과 사용자 확정·보류·원본 금액·날짜·ID는 유지했다. 코드와 등록 목록을 운영에 적용하고 상태 경로를 확인했으며 실제 로그인 브라우저 검증과 구분한다. 상세 근거는 `.local-archive/ota-integration-20261008/`에 보존한다.

<a id="src-docs-archive-ota-legacy-20261023-ota-mail-md--현재-연결과-미결-확인"></a>
#### 현재 연결과 미결 확인

<a id="src-docs-archive-ota-legacy-20261023-ota-mail-md--자료-등록과-진단-확인"></a>
##### 자료 등록과 진단 확인

기본 등록 파일은 운영 데이터 폴더의 `ota-sources.json`이다. 별도 파일을 쓰려면 `WEBLEDGER_OTA_SOURCES`로 절대 경로를 지정한다. 등록 파일이 없으면 기존 기본 메일 디렉터리와 포털 DB를 사용하지만, 환경변수로 명시한 등록 파일이 없으면 오류로 처리한다.

등록 형식은 `schema_version: ota-sources-v1`이며 `mail_directories`, `portal_databases`, `reference_documents`에 절대 경로 목록을 넣는다. 새 메일은 등록한 디렉터리에 저장하면 다음 조회에서 읽힌다. 새 포털 DB나 과거 조사 문서는 해당 목록에 추가한다. 참고 문서에 해시가 적혀 있어도 실제 원문과 인증 근거를 대조하지 않은 내용은 결제 권위가 아니다.

대조 보고서의 `ota_source_inventory`는 등록 위치와 누락 자료를, `ota_source_errors`는 읽기 실패를, `portal_diagnoses`와 `unmatched_reason_counts`는 미연결 원인을 기록한다. 같은 사유가 화면과 보고서에 반영된다. 조사 결과와 근거 파일을 먼저 확인하고, 이미 수집한 자료를 사용자에게 반복 요청하지 않는다.

2026-10-08 기준으로 보존 메일과 기존 Agoda 전수조사 포털 DB를 함께 읽는다. 메일 검색이 없다는 이유로 포털 근거까지 없다고 판단하지 않는다. 신규 메일 발송이나 예약 생성 없이 현재 원행의 정확 금액·카드·기간·취소 근거를 대조한다. `app/ota_portal.py`는 완료 예약의 정규 결제 양식과 예약 확정·결제 성공이 명시된 과거 양식을 구분해 읽으며, 모두 필수 근거 다섯 종류와 원문 해시를 확인한다. 전수조사의 모든 예약이 자동 연결되는 것은 아니다.

146,018원은 전수조사에서 결제·카드 끝자리·08-27~08-29 기간을 확인했다. 포털 상태는 예약 확정·결제 성공이며 실제 이용 완료가 아니다. 기존 위약금·환불 가능 안내와 사용자 보류를 보존한다. 64,814원은 과거 proposed 예약의 포털 금액이 96,842원이고 결제 예정 안내라서 확정 연결할 수 없다. 기존 조사 원문을 다시 확인한 결과는 [운영 문서](../operations.md)에 기록했다. 전수조사 미수행이나 예약 자체 부재로 표시하지 않는다.

OTA 메타데이터 전달 코드는 운영에 적용됐으며 현재 장부는 734건이다. 최신 일정 원본과 차단 내역은 [인계 문서](ota-legacy.md#src-docs-archive-ota-legacy-20261023-session-handoff-md)를 따른다. 아래 날짜가 붙은 검증·미반영 문구는 각 작업 시점의 기록이다.

<a id="src-docs-archive-ota-legacy-20261023-ota-mail-md--이전-구현과-검증-기록"></a>
#### 이전 구현과 검증 기록

메일 처리는 `app/ota_mail.py` 한 곳에 있고 보존 포털 근거는 `app/ota_portal.py`에서 읽는다. `tools/match_booking_mail.py`는 메일의 읽기 전용 실행 명령과 기존 호출 호환만 담당한다. `tools/recover_history_rules.py`가 메일 결과를 원행에 묶인 분류 규칙과 추론 후보로 연결한다. 근거 대조 자체는 장부에 기록하거나 사용자의 답변을 변경하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-ota-mail-md--2026-10-07-예약-메타데이터의-장부-전달"></a>
#### 2026-10-07 예약 메타데이터의 장부 전달

코드 commit `9c4dbdac2ab9e6f5f854b07a5ac3fc2f215005ed`는 기존 report의 확정 사실을 `ledger_metadata()`로 전달한다. 새로운 matcher나 DB 스키마는 추가하지 않았다. 유일한 활성 예약이 원행과 항목에 연결되고 근거 digest가 있으면 예약번호를 전달한다. 숙박은 검증된 이용기간도 있어야 한다. 개별 예약이 모호하면 예약번호를 고르지 않고 matcher가 검증한 `shared_period`만 전달한다. 취소·환불 확인 대기·근거 확인 대기·예약 연결 충돌·기간 충돌은 확정 메타데이터로 전달하지 않는다. 공통 기간을 검증하지 못한 후보도 빈값을 유지한다.

전달 경로는 OTA report → preview entry → preview digest → commit의 preview 재계산 → `CardFlow.project()` → `board_rows`다. 기간 문자열은 `YYYY-MM-DD~YYYY-MM-DD`를 사용한다. 미리보기에는 OTA 예약 근거로 표시하며 카드 원본 값으로 취급하지 않는다. 예약번호·기간·OTA provenance를 모두 digest로 보호하고, 숙박 report에는 결제 근거뿐 아니라 해당 예약의 기간 근거 digest도 포함한다. evidence 변경으로 digest가 달라지면 `PREVIEW_STALE`로 거절하며 projection에서는 OTA를 다시 조회하거나 판단하지 않는다.

정확한 예약, 모호한 예약번호, 공통 기간, 취소·기간 충돌, evidence 변경, 멱등성, projection rollback을 합성 자료로 검증했다. 관련 검사 152개와 하위 검사 39개가 통과했고 실제 Chromium 390×844·1440×900에서 미리보기 표시와 HTTP 기록, 가로 넘침 0을 확인했다. 이번 단계에서는 전체 회귀·운영 배포·운영 DB 쓰기·OTA 재수집을 실행하지 않았다. 아래 운영 자료 관련 기록은 과거 작업의 결과이며 이 commit의 운영 반영 증거가 아니다.

2026-10-04 사용자 추가 답변을 운영에 반영했다. 아고다 가맹점 그룹은 숙박비이며 비용 항목과 여행·예약번호 연결을 분리한다. POP3 수신 메일도 공식 발신 도메인과 정렬된 서명이 확인되면 사용하며 수신 지연을 예약일 또는 결제일로 바꾸지 않는다. 예약 하나당 한 번 결제하는 기준에 따라 합산·분할·할인 금액을 만들어 맞추지 않는다. 명시 자동 결제 예정일과 실제 카드 거래의 통화·금액이 유일하게 일치하는 대사는 예정일 근거로 표시하고 결제 완료 영수증이라고 부르지 않는다.

전체 메일함을 `in:anywhere after:2026/04/01 before:2026/10/05`와 공급자 발신 조건으로 모든 페이지에서 조회해 1,616개 메일 ID를 확인했다. 기존 보존 자료에 없던 520개를 추가해 다른 보존 원천을 포함한 메일 1,670개를 대조했다. 기존 운영 카드의 정확한 연결 106건을 모두 유지하고 2건을 추가해 108건이 됐다. 새 다운로드의 연결은 82건, 상품 종류만 확인은 13건이며 예약 연결 대기는 388건이다. 이 중 아고다 표기 326건의 구매 용도는 사용자 답변으로 숙박비가 확인됐지만 예약번호 연결을 완료했다고 표시하지 않는다.

운영 DB에는 `owner-agoda-lodging-20261004` 규칙을 한 번 저장했고 원행 403건을 반복 대사 후 반영했다. 최종 여행 배정 제안은 375건이며 이번 전체 메일 보완으로 분류 필드가 바뀐 거래는 2건이다. 사용자 확정·원본·기존 규칙·장부 기록을 보존했고 새 다운로드 파일을 운영 거래로 가져오거나 전기하지 않았다. 관련 검사 139개와 운영 DB 무결성·공개 상태 확인이 통과했다. 검증 자료는 `.local-archive/card-downloads/20261004-reconciliation/ota-application-pop3-complete.json`, `ota-owner-answers-verification.json`에 보존했다. 완전 조회 원본과 범위는 `.local-archive/card-downloads/20261004-pop3-complete`에 있다.

흐름은 보존 메일 읽기 → 발신 인증 확인 → 예약·결제·기간 추출 → 예약번호별 근거 결합 → 카드 원행 대조 → 상품 분류와 여행 후보 생성이다. 여행 후보와 장부 기록은 별도 단계다.

- 트립닷컴과 클룩은 실제 온라인 원화 결제액과 같은 날의 승인 거래를 대조한다. 렌터카 현장 결제분과 무료 티켓 수령 안내를 실제 온라인 결제액에 더하지 않는다.
- 아고다와 부킹닷컴은 결제 완료 메일에서 확인한 원화 또는 외화 통화·금액을 대조한다. 원화는 같은 날, 외화는 하루 이내의 결제일을 허용하며 환율 근삿값은 사용하지 않는다.
- 같은 금액으로 여러 예약이나 실제 카드 거래가 남으면 특정 예약을 고르지 않는다. 후보 상품 종류가 모두 같은 경우에만 상품 분류를 제안한다.
- 이용기간은 명시 체크인·체크아웃에서 읽으며 체크아웃 날짜를 하루 줄이지 않는다. 같은 예약의 이용기간이 충돌하면 첫 메일을 고르지 않고 여행 배정을 보류한다.
- 취소된 예약을 실제 이용 여행의 근거로 사용하지 않는다. 원결제와 카드 환불은 별도로 보존한다. 메일만으로 환불 장부 행을 생성하지 않는다.
- 같은 메일 ID의 첨부 정보 보완은 허용하되 본문이나 인증 헤더가 다르면 충돌로 중단한다. 발신 인증 도메인의 뒤 경계를 확인해 비슷한 이름을 허용하지 않는다.
- 외화 소수점과 천 단위 구분을 구별하고 모호한 금액은 대조에서 제외한다.

보고서는 메일 역할, 정확한 예약 대조, 상품 종류만 확인한 거래, 미연결 거래, 취소 예약과 기간 충돌을 구분한다. 미연결 거래가 곧 여행 미배정 거래는 아니다. 과거 원행과 사용자 허용 추론으로 이미 배정된 거래도 메일 연결은 없을 수 있다.

메일 수집 범위와 카드 조회 범위를 함께 확인한다. `collection.json`에는 조회 시작·종료 조건, 페이지 조회 완료 여부와 수집 건수를 보존한다. 수집이 끝났다는 사실과 특정 거래의 예약 근거가 있다는 사실은 다르다. 미연결 거래는 정확한 결제 증거 부족, 원화 매입 또는 같은 통화 영수증 필요로 구분하며 예약 자체가 없다고 표시하지 않는다.

2026-10-06에 실제 보존 자료로 매칭 누락을 재현했다. 부킹닷컴의 `결제 완료` 다음 통화·금액 양식을 읽도록 보완했고, 유일한 결제 연결과 이용기간 검증을 분리했다. 이용기간이 없거나 서로 다르거나 예약이 취소되어도 검증된 원결제 연결은 보존하되 여행 근거로 사용하지 않는다. `취소됨` 제목도 취소 완료로 판독하며 취소 정책 안내는 제외한다. 발신 인증, 정확한 통화·금액·결제일, 실제 복수 거래의 모호성 검사는 유지한다.

카드 조회 시작일보다 예약 메일이 먼저 도착할 수 있다. 결제 연결에 이용기간이 없으면 읽기 전용 대조 보고서의 `booking_evidence_gaps`에 공급자·예약번호와 누락 이유를 남긴다. 해당 예약번호로 지정 메일함을 날짜 제한 없이 추가 조회해야 하며, 이용기간을 결제일로 대체하지 않는다. 실제 운영 보존 사본에서 기존 정확 연결 108건을 유지하고 12건을 추가했다. 예약번호 추가 조회로 빠져 있던 1~3월 메일 11개를 찾았으며 신규 연결 11건의 이용기간을 보완했다. 이 중 9건은 사본의 여행 기간 후보가 하나이고, 2건은 여행 기간이 겹치며, 나머지 1건은 취소 예약이다. 운영 DB 재분류·장부 기록·서버 재시작은 수행하지 않았다.

아고다는 메일 수신 오류로 7~8월 이전 결제 메일이 누락되어 사용자가 이미 예약 페이지 전수조사를 수행했다. `outputs/agoda-paseo-staging-20260822.sqlite`와 기존 전수조사 검증 자료는 로컬에 보존되어 있다. 경량화 후 실행 경로가 메일만 읽고 이 포털 근거를 읽지 않아, 기록이 있는 예약도 연결되지 않았다. 메일 검색 결과만으로 예약 근거가 없다고 판단하지 않는다.

`app/ota_portal.py`는 기존 포털 DB를 읽기 전용으로 대조한다. 예약 식별·이용기간·실제 결제액·카드 관찰·예약 상태의 다섯 근거, 원문 hash, 완료 예약과 실제 결제 상태를 검증한다. 카드 끝자리와 정확한 통화·금액이 양쪽에서 일대일로 일치할 때만 현재 원행에 연결한다. 총액만 맞추거나 환율을 계산하거나 카드 결제일을 이용일로 사용하지 않는다. 취소·환불·근거 충돌·실제 복수 거래는 자동 연결하지 않는다. 메일과 포털이 다른 예약이나 기간을 제시하면 연결 확인을 요구하며 과거 추론 여행을 다시 적용하지 않는다.

현재 카드 보존 사본 5,328건과 원본 포털 자료를 읽기 전용으로 대조해 78건을 연결했다. 이 중 현재 검토 기간의 신규 연결은 57건이며 나머지는 내부 보존 기간이다. 메일 120건의 기존 거래·예약·항목 연결을 모두 유지한 통합 결과는 전체 198건, 현재 검토 기간 177건이다. 2026-07-11 아고다 1,301,996원과 2026-07-12 아고다 273,560원도 카드 끝자리·결제액·예약번호·이용기간으로 연결된다. 전자는 사본의 노리쿠라 명시 일정에 포함되지만 후자의 08-05~08-06 이용기간은 여행 종료일 08-05를 넘으므로 여행을 자동 확정하지 않는다. 64,814원은 이 기준으로 연결되지 않아 보류한다. 포털 연결은 `예약 근거 있음`으로 표시하며 메일이 존재한다고 표시하지 않는다. 메일 대조와 결합할 때 기존 연결과 사용자 직접 확정을 보호하고, 상품·여행 제안과 실제 장부 기록을 분리한다. 원본 포털 DB와 카드 사본의 hash가 변경되지 않았으며 운영 재분류·장부 기록·서버 재시작은 수행하지 않았다.

최종 관련 검사는 177개와 하위 검사 2개가 통과했다. 실제 HTTP와 Chromium 390×844·1440×900에서 포털 근거 표시, 분류 결과, 가로 넘침 없음을 확인했다. 전체 활성 회귀는 2,175개와 하위 검사 2,332개 통과, 기존 건너뜀 4개, 실패 0개다. 최초 검증 때 운영 설정 파일 접근이 거부되었으며, 이후 일반 작업 계정의 읽기 권한을 복구했다. 권한 복구와 운영 코드 반영은 구분하며 운영 적용을 완료한 것으로 보고하지 않는다.

카드 조회와 업로드·답변 후 재분류에서도 보존 메일과 포털 근거를 대조한다. 기본 메일 경로는 운영 DB 폴더의 `ota-mail`이며 `WEBLEDGER_OTA_MAIL_DIR` 또는 운영 설정 `ota_mail_dir`로 명시 경로를 지정할 수 있다. 포털 DB는 `WEBLEDGER_AGODA_PORTAL_DB`, 운영 DB 폴더의 `agoda-portal.sqlite`, 위 보존 전수조사 경로 순으로 읽는다. 과거 파이프라인이나 DB 구조 전체를 복구하지 않으며 원본 자료를 Git에 추가하지 않는다. 대사 근거는 해당 원행에만 적용한다. 재분류 때문에 사용자 규칙을 새로 만들거나 덮어쓰지 않고 사용자 확정 답변과 완료 기간을 보호한다. 메일 수집은 별도 인증된 조회로 수행하며 웹 요청에서 외부 메일을 보내거나 새로운 예약을 만들지 않는다.

현재 원행의 예약 증거는 수정되지 않은 과거 자동 복원 규칙보다 먼저 적용한다. `history-recovery-20261003`의 첫 버전만 이 대상이며 사용자 수정 버전과 사용자 확인 규칙은 충돌 검사를 유지한다. 취소 완료·기간 충돌·공통 이용기간이 없는 예약 후보는 과거 추론 배정이 다시 붙지 않도록 막는다. 여행 권위 검증은 각 분류 호출에서 새로 확인하며 같은 호출의 메일 후보끼리만 검증 결과를 공유한다.

요일이 붙은 영어 체크인·체크아웃 날짜와 표준 Gmail 본문 인코딩을 읽는다. 같은 거래의 같은 원문이 두 번 전달되면 한 번만 대사하지만 서로 다른 거래는 계속 모호한 후보로 남긴다. 원화가 비어 있어도 검증된 외화 통화와 금액은 대조할 수 있으며 환율로 원화 금액을 만들지 않는다. 서명된 발송 날짜와 수신 지연을 구분하고, 공급자 공식 하위 도메인의 일치하는 서명도 검증한다. 취소 조건과 위약금 안내는 취소 완료로 처리하지 않는다.

같은 금액의 숙박 후보가 모두 같은 이용기간을 가리키면 공통 기간과 후보 수를 보존한다. 개별 예약번호는 고르지 않으며 여행은 명시 일정이 유일하게 검증될 때만 배정한다. 취소 후보나 이용기간 충돌이 있으면 공통 기간을 사용하지 않는다.

현재 지원하는 발신 도메인은 트립닷컴·클룩·아고다·부킹닷컴과 유럽 일정 보존용 아고다 숙소 메시지다. 인증이 확인되지 않거나 지원하지 않는 원천은 집계하고 자동 근거로 사용하지 않는다. 항공·철도 이용일, 첨부 바우처와 공급자의 새로운 메일 양식은 자동 추출 범위 밖이면 별도 확인이 필요하다.

2026-10-03 보존 메일 631개와 카드 원행을 재생해 기존 예약 대조 106건의 거래·예약·상품 식별이 동일함을 확인했다. 상품 종류만 확인한 거래는 20건이며, 취소 메일이 있는 연결 예약은 12건이다. 취소 표시는 새 분석 결과에 적용했고 운영 거래의 기존 분류와 사용자 답변은 일괄 변경하지 않았다. 유럽 일정의 명시 기간과 취소 제외 후 숙박 12건도 유지했다. 카드 파이프라인 검사 107개가 통과했고 운영 재시작 후 장부 데이터의 모든 기존 테이블이 프로세스 상태 테이블을 제외하고 같았다. 실제 로그인 세션에서 준비 상태와 카드 조회가 정상 응답하고 검토 카드 1,676건이 유지됨을 확인했다.

검증 자료는 `.local-archive/lightweight-20261003/ota-mail-refactor/verification.json`과 `replay-final.json`에 보존했다. 새 메일 결과를 기존 비용에 반영할 때는 사용자 수정 규칙과 이미 확정한 거래를 보호하고, 운영 복구 사본과 대상 원행 범위를 먼저 검증해야 한다.

2026-10-04에는 기존 메일 수집 종료가 7월 21일인데 새 카드 조회는 10월 4일까지인 차이를 확인했다. 지정 Gmail 계정에서 7월 20일 이후 공급자 메일 530개를 모든 페이지에서 조회하고 기존 보존 자료와 합쳐 메일 1,150개를 대조했다. 새 국민·하나 다운로드의 OTA 원결제 483건 중 정확한 예약 연결은 27건에서 82건으로 늘었고 상품 종류만 확인된 거래는 13건이다. 남은 388건은 정확한 결제 근거 부족 320건, 같은 통화 영수증 또는 원화 매입내역 필요 68건이다. 기존 카드 원행의 정확한 예약 연결 106건은 모두 유지했다.

운영 DB의 미확정 OTA 원행 403건을 대상으로 사본에서 반복 대사를 확인한 뒤 반영했다. 최종 분류 제안은 403건이며 여행 배정 제안은 376건이다. 원래 상태와 비교해 분류 필드가 바뀐 거래는 70건이고 취소·기간 충돌·공통 기간 부재로 과거 추론 여행을 해제한 거래는 14건이다. 사용자 확정 거래와 규칙, 원본 파일·금액, 여행 일정, 장부 기록은 보존했다. 새 다운로드 파일을 운영 거래로 가져오거나 장부에 전기하지는 않았다. 관련 검사 136개가 통과했고 운영 재시작 후 로컬·공개 주소의 `/healthz`, `/readyz`는 모두 정상 응답했다. 로그인 이후 화면 조작은 이번 검증에 포함하지 않았다.

이번 반영의 복구 사본과 반복 대사 검증 결과는 `.local-archive/card-downloads/20261004-reconciliation`의 `board-before-ota-apply.sqlite`, `ota-application-resolved.json`, `ota-final-verification.json`에 보존했다. 새 다운로드의 상세 대사 결과는 같은 폴더의 `OTA재대사결과.html`에서 검색할 수 있다. 외부 메일 조회는 별도 실행이므로 앞으로의 카드 조회 기간이 보존 메일 수집 기간을 넘어서는지 다시 확인해야 한다.

읽기 전용 대조 명령:

```powershell
python tools/match_booking_mail.py --mail-dir <보존메일폴더> --database <장부SQLite> --output <별도보고서경로>
```

실행 결과를 표준 출력에는 집계만 내보내고 상세 근거와 규칙 후보는 로컬 보고서에 저장한다. 새 메일 수집이나 메일 발송은 이 명령의 기능이 아니다. 보고서 출력으로 원본 메일이나 장부 DB를 덮어쓸 수 없다.

---

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md"></a>

## session_handoff

통합 전 경로: `docs/archive/ota-legacy-20261023/session_handoff.md`

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--미결-작업과-다음-세션-인계"></a>
### 미결 작업과 다음 세션 인계

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-23-확정-ota카드-매칭-a-정책-및-r0-시작점-운영-미반영"></a>
#### 2026-10-23 확정 OTA–카드 매칭 A 정책 및 R0 시작점 (운영 미반영)

새 최우선 정책: **카드 실제 매입이 정상이고 중복·원본 충돌·미해결 취소·환불이 없다면 OTA 예약 연결 정확도가 낮거나 미연결이어도 최선 여행에 자동 배정하고 내부 경비 기록 준비/미리보기를 허용한다.** Google 자동 쓰기 금지, 추정 예약번호 Google 출력 F열은 공란, 사용자 여행 A→B 이동은 AI·재대사로 덮어쓰지 않는다. 카드 원본/금액/수동 링크/부분환불 보호는 유지.

[OTA 매칭 정책 A 최종 구현 명세](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md) **먼저 읽기**: 실제 코드의 결제일 미기록 후보 전면 배제, `paid_today` 및 카드4자리 미존재 시 결제 이벤트 누락, 서로 다른 포털 DB 간 동일 record ID 충돌, NICE alias/OTA 판별 불일치, legacy vs OTA-first 이중 대사 및 readiness와 OTA hold 혼재에 대한 원인 추적·설계·API/SQL/테스트·rollout 계약이 기록돼 있다.

**다음 개발 과제는 R0: 읽기 전용 P0 전수 진단 CLI, ExtractionOutcome·MatchTrace 및 합성 표적 테스트만.** 실행 가능한 운영 원본은 이 GitHub 문서에 없다. 운영 DB를 읽어 실제 몇 건이 미매칭인지 확인한 결과는 아직 없다. R1~R6는 작은 별도 PR로 구현·검증 후 단계적으로 적용하며, 기존 PR #87 B의 Decimal 정규화 코드는 push했으나 아직 pytest 검증·병합·배포되지 않았다. 이번 작업은 문서·지침 갱신만이며 실제 동작 변경은 없다.


<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-23-cost-v3-최신-사용자-요구--pr-87-운영-미반영"></a>
#### 2026-10-23 COST V3 최신 사용자 요구 / PR #87 (운영 미반영)

새 최상위 정책은 **유효한 여행 후보가 하나 이상일 때 낮은 추론도 실제 여행으로 우선 배정**, 사용자가 거래를 여행 A에서 B로 즉시 이동한 뒤 **웹 내 AI가 예상 답안 1·2/사용자 자유답 3으로 이유를 확인, 필요시 추가질문 후 재사용 규칙을 승인받아 학습**하는 방식이다. 수동 이동은 모든 추론보다 우선하고 AI 실패 시에도 B에 유지한다. 기존 카드·환불·중복·Google 정본·고객 신원 안전은 유지한다.

세부 API/SQL/알고리즘/테스트/단계 계획은 [V3 구현 명세](specs-20261110/participants.md#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md)를 반드시 먼저 읽는다. A의 항공권 영어 이름→한글 후보 및 reservation 참가자 연동, B의 N:M 대사, 테스트 경계 축소 설계가 모두 포함돼 있다. B의 `30000` vs `30000.00` Decimal 금액 정규화 코드와 합성 테스트 3개는 [PR #87](https://github.com/6Soo/cost/pull/87)에 push된 상태이며, **테스트 미실행·미병합·미배포**다. 최신 main 운영 동작에 이미 반영됐다고 쓰지 말 것. A와 대화학습/구조 개편은 구현 명세 단계다. 현행 운영 배포 확인은 계속 operations.md를 따른다.


<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--최신-채팅-세션-인계-진입점"></a>
#### 최신 채팅 세션 인계 진입점

2026-10-20 사용자의 “이 채팅 세션 내용 handoff 후 push” 요청에 따라 [세션 인계](implementation-and-audits.md#src-docs-handoff-session-20261020-booking-evidence-md)에 대화 배경, 이번 수정 원인, 코드·운영 릴리스, 표적 검사, 배포 근거, 실패한 브라우저 확인과 다음 단계를 정리했다. 운영 코드는 `f5e27d3`이며 남은 확인은 정상 로그인 브라우저에서 예약 자료 미연결 안내를 읽기 전용으로 보는 작업이다. 과거 요구 목록을 새 개발 과제로 재실행하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-20-예약-자료-미연결-안내-수정"></a>
#### 2026-10-20 예약 자료 미연결 안내 수정

`f5e27d3a06ad010656dd43f8d01af2ccc42cb5b5`를 main에 push하고 운영 배포했다. 잘못된 “예약 근거를 카드 자료에서 확인” 안내를 현재 연결된 예약 자료가 없다는 설명과 예약번호·이용기간 확인 안내로 바꿨다. 격리 DB에서 수정 전 실패·수정 후 표적 테스트 1 passed, 거래 필드 불변, 릴리스 Git 객체 일치, 백업·복원·배포 PASS를 확인했다. 운영 거래 변경이나 전체 회귀는 수행하지 않았다. 현재 요청의 문구 수정·배포는 완료했으며 브라우저 실화면 확인은 PARTIAL이다. Aside 새 탭이 빈 상태로 반환되고 유지되지 않았다. 다음 단계는 정상 로그인 브라우저에서 `/import`의 아고다 상세 검토 문구를 읽기 전용으로 확인하는 작업뿐이다. Python HTTP 시간 초과와 별개로 PowerShell의 health 200·비로그인 import 401은 확인했다. 자세한 근거는 [운영 문서](../operations.md) 첫 절을 따른다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-19-아고다-규칙-제안-배포-완료"></a>
#### 2026-10-19 아고다 규칙 제안 배포 완료

인계받은 아고다 자연어 분류 제안 수정 5개 파일은 `d90bef2e8370c4bca065328dc0df64df7a24616e`에 커밋·push됐고 고정 운영 릴리스에 배포됐다. 변경 기능 표적 테스트 5개 통과, `OWNER_UI_DEPLOYMENT_PASS`, DB 4개·파일 55개 백업 및 복원 검증, Board·SourceRefresh Running, 로컬 health/ready 200, 로그인된 운영 카드 화면 263건 중 20건 표시를 확인했다. 변경되지 않은 기능의 전체 회귀 검증은 수행하지 않았다. 운영 거래 승인이나 장부 기록은 실행하지 않았다.

현재 분류 제안은 아고다 가맹점의 비용 항목 변경만 미리 보여 주고, 실제 적용에는 별도 승인이 필요하다. 여행 이용기간 해석과 복수 여행 충돌은 기존 승인 규칙을 유지하고 제안에 안내한다. 배포 근거와 한계는 [운영 문서](../operations.md) 첫 절을 따른다. 별도 요청 없이 새 여행 배정 엔진을 만들거나 운영 데이터를 수정하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-18-지출-정리-ui-변경-완료-및-실화면-확인"></a>
#### 2026-10-18 지출 정리 UI 변경 완료 및 실화면 확인

사용자 첨부 시안을 참고한 거래별 검토 카드·자연어 규칙 제안·별도 승인·상세 검토와 여행 수정은 `e59cb1c0a7deaab46bdf4d8a4025341fcf47564b`에서 구현·표적 검사·push·운영 배포 완료했다. 로그인된 실제 운영 데스크톱에서 263건 중 한 페이지 20개 카드, 규칙 입력과 제안 버튼, 펼친 상세 검토의 여행 선택·비용 항목·수정 버튼이 표시됨을 확인했다. 운영 데이터를 바꾸는 동작은 수행하지 않았다. 운영 백업·복원 검증, health/ready 및 실행 서비스 검증이 완료됐다. 자세한 근거는 [운영 문서](../operations.md) 첫 절을 따른다.

향후 거래 규칙은 제안 후 별도로 승인·저장하며, 예약 이용기간을 해석하는 새로운 자연어 여행 규칙 엔진은 구현하지 않았다. OTA 이용일 우선·보류·충돌·중복·환불·원본·사용자 확정 보호는 유지한다. 현재 UI 요청에서 남은 구현은 없으며 실제 모바일 기기에서의 추가 확인은 수행하지 않았다. 과거 요청을 재실행하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-13-카드-ux-요청-완료"></a>
#### 2026-10-13 카드 UX 요청 완료

마지막 운영은 `b3c6432`이며 필요한 예약번호·이용일 안내 문구 `350b6ba`까지 반영했다. 실제 예약 연결 영역은 직전 스냅샷을 표시 중으로 연결 확정은 수행하지 않았다. 최신 예약 근거가 준비된 후 기존 검증 경로에서 연결할 수 있으며 UX 완료를 예약 연결 완료로 해석하지 않는다.

현재 운영은 `b3c6432`다. 자동 기록·행별 다음 행동·실제 보류 사유 우선·해당 거래 이동·문제 있는 묶음과 정상 거래의 처리 분리는 구현·검사·운영 반영까지 COMPLETE다. 정상 17건이 실제 기록됐고 기존 원문·장부·확정·보류·제외 행은 모두 보존됐다. 두 사진 거래의 실제 문제는 예약 결제 연결 미확정으로, 각각 ‘예약 연결 확인’과 이유가 표시되며 보호를 우회하지 않았다. 원래 14건의 여행 지정이나 예약 연결을 UX 작업의 완료로 해석하지 않는다.

핵심 구현 `9da6610`과 후속 수정, 운영 `b9dbb95`, 통합 `4864c70` 및 PR #85 최신 HEAD를 따른다. 계속 요청 사이 현재 운영에 추가돼 있던 `1ce47f6`의 성능 수정도 통합해 보존했다. 최신 근거는 [운영 문서](../operations.md) 첫 절, 적용 규칙은 [업무 규칙](specs-20261110/finance.md#src-docs-business-rules-md) 첫 절이다. 이 요청의 남은 코드 작업은 없으며 다음 요청에서 과거 과제를 자동 재실행하지 않는다. 사용자 checkout의 기존 변경 5개와 stash는 보존한다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-13-환불과거-내역-요청"></a>
#### 2026-10-13 환불·과거 내역 요청

현재 운영은 `6615ebf`다. 전액 환불 107쌍·219행의 환불 탭 표시, 부분 환불의 기존 여행과 잔액 유지, 카드·OTA 과거 자료 제외는 구현·검사·운영 반영까지 COMPLETE다. 구현 `b0d9732`와 시간 포함 날짜 수정 `9ff42cd`, PR #85의 `integration/cost-final` 최신 HEAD를 따른다. [운영 문서](../operations.md)의 첫 절과 [업무 규칙](specs-20261110/finance.md#src-docs-business-rules-md)의 첫 절에 기준을 기록했다. 원본과 장부·결정·보류의 전체 행 해시는 배포 전후 동일하다.

PARTIAL은 여행을 지정하지 않은 부분 환불 원결제 14건의 새로운 여행 지정이다. 공통 경비·분기 비용·사용자 확정이 포함돼 기존 결정을 덮거나 결제일만으로 여행을 지정하지 않았다. 재개할 때 `.local-archive/refund-tab-history-20261013/partial-refund-awaiting-trip.json`과 현재 자료를 대조한 뒤 여행 비용에 해당하는 자료의 이용기간 또는 사용자가 지정한 여행을 받아 원결제와 환불을 함께 처리한다. 이미 구현한 탭·표시 정리를 반복하지 않는다. 사용자 checkout의 기존 변경과 stash를 보존한다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-13-계속-요청의-후속-화면-정리-완료"></a>
#### 2026-10-13 계속 요청의 후속 화면 정리 완료

출력의 중복 집계·구현 설명, Google 정상 기술 상태 목록, 원본 검토의 반복 설명과 규칙 버튼의 잘못된 합성 표시를 정리했다. 구현·표적 검사·운영 반영까지 COMPLETE다. 구현 `caa1673`, 운영 `b0ed017`, 통합 `9160749`와 PR #85의 최신 HEAD를 따른다. 최신 검사·백업·운영 화면 근거는 [운영 문서](../operations.md)의 첫 절에 기록했다. 현재 승인 요청에 남은 구현은 없다. 금액·원본·결정·환불·OTA 연결과 영수증 환산·외부 전송 동의를 유지했다. 원래 사용자 checkout·보호 파일·stash를 보존한다. 새 기능 요청이 생기면 최신 HEAD에서 새 Paseo 작업 공간을 만들며 이전 ACTIVE 과제를 자동 실행하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-13-화면-정리-요청-완료"></a>
#### 2026-10-13 화면 정리 요청 완료

빈 COST 수입 영역 제거·Google 수입 제목 통일·지출 투명 배경·사이트 고정 장문 설명 제거·사용 불가 기능 자리표시자 제거를 구현·표적 검증·운영 반영까지 완료했다. 구현 `c863197`, 운영 `b4e1ec1`, PR #85의 `integration/cost-final` 최신 HEAD를 따른다. 기존 실제 수입·지출과 편집·복사·오류·보류·외부 전송 동의는 유지했다. [운영 문서](../operations.md)의 첫 절이 최신 근거다. 이번 활성 요청의 남은 구현은 없으며, 원래 사용자 checkout·보호 파일·stash를 유지한다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-13-내역-오름차순-요청-완료"></a>
#### 2026-10-13 내역 오름차순 요청 완료

OTA·카드·카드 검토·여행 장부·Google 수입/지출 상세의 날짜 오름차순을 구현·표적 검증·운영 반영까지 완료했다. 구현 `832275a`, 운영 `23e8b93`, PR #85의 `integration/cost-final` 최신 HEAD를 따른다. 기존 정렬 선택·필터와 회계 데이터는 유지했다. 최신 근거는 [운영 문서](../operations.md)의 첫 절이다. 이번 활성 요청의 남은 구현은 없다. 원래 사용자 checkout과 보호 파일·stash는 유지한다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-13-최신-작업-완료"></a>
#### 2026-10-13 최신 작업 완료

분기 기타비용 탭 지원과 모바일 수입표 요청을 구현·표적 검증·운영 반영까지 완료했다. 운영 `68b0fee`, 구현 `4b0c8e7`, PR #85의 `integration/cost-final` 최신 HEAD를 따른다. 실제 3분기 탭은 읽기·연도·지출 합계가 검증됐다. 2·4분기 탭 없음과 1분기 구형 양식은 복사 차단으로 표시하며 Google 원본에 새 탭을 만들지 않았다. 모바일 날짜·이름/닉네임·총액과 아이콘을 적용했다. 최신 검사·배포·실제 브라우저 한계는 [운영 문서](../operations.md)의 첫 절에 기록했다.

현재 활성 요청에 미완료 구현은 없다. 존재하지 않는 분기 Google 탭을 사용자가 준비하면 다음 정기 읽기로 감지한다. 원본 양식을 임의로 변환하거나 Google에 자동 쓰지 않는다. 기존 사용자 checkout의 보호 파일·dirty·stash는 유지했다. 이전 인계에 적힌 release SHA를 최신으로 사용하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-12-세션-인수-후-최신-상태"></a>
#### 2026-10-12 세션 인수 후 최신 상태

`f49a35a1-aabd-4917-bc3c-1b6906211ffe`의 대화와 남긴 작업을 인수했다. 마지막 카드 검토 화면 개선·수입 중복 표시 정리·Google 원본 직접 링크는 구현·표적 검증·운영 반영까지 COMPLETE다. 구현 `873797f`, 운영 `adaa50b`, 통합 브랜치 `integration/cost-final`과 PR #85에 보존한다. [운영 문서](../operations.md)의 첫 절과 [인수 기록](implementation-and-audits.md#src-docs-session-takeover-20261012-md)을 따른다.

사용자 checkout의 보호 파일과 기존 변경 5개는 그대로 보존했다. 예약 알림톡 수정은 reservation PR #18 `0a66d6e`의 OPEN·운영 미반영 상태로 보존한다. 이전 PDF·자동 영역 분리·실제 ADC·viewer 검증·인프라 이전은 완료로 바꾸지 않는다. 아래 재개 위치와 운영 SHA는 과거 기록이다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--최신-운영과-재개-위치"></a>
#### 최신 운영과 재개 위치

2026-10-12에 기존 운영 사이트를 COST V2 `639744742537711e9fba9ab644e03c6fb8901aa9`로 전환했다. 배포 경로·검증·원본 보호·미완성 기능·다음 코드 작업은 [현재 체크포인트](ota-legacy.md#src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md--현재-운영-반영-2026-10-12)를 따른다. 아래 운영 SHA와 승인 대기는 과거 기록이며 현재 상태로 해석하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--이전-상태-2026-10-10"></a>
#### 이전 상태 (2026-10-10)

- 운영 코드(최신): COST PR #53(`2291e7d`) 반영, 호스트 PID 40124, `/healthz`·`/readyz` 200, 비로그인 루트 401. 변경 내용은 웹 업로드의 이진 `.xls` 직접 읽기(xlrd 2.0.2, 운영 venv와 `runtime-requirements.lock.txt`에 추가), 본인 수정에서 규칙 초안 자동 생성, 보드 규칙의 미래 카드 입력 연결(같은 가맹점 기존 카드 규칙 대체)이다. 승인 파일은 `APPROVAL_FILE_NOT_ACQUIRED`로 거부한다.
- 반영 후 운영 점검: 로그인·`/board`·`/import`·`/export` 읽기 200, `/rules`는 사례 ID 없이 404(기존 동작). 실제 장부 export(0630_오제, 85행)는 보드와 행 단위로 일치했고 장부 736행·73,998,707원·보류 15건은 변하지 않았다. 보호 기준선 게이트 재실행 결과 278건 모두 동일(변경·누락·중복·수동 덮어쓰기 0), 사용자 결정 28건.
- 알려진 입력 한계: 해외 KB 전체 이력 `.xls`를 올리면 이미 장부에 있는 거래가 "다른 파일에 승인번호 없는 유사 거래"로 대량 차단되어(당시 764건 중 709건) 검토 목록이 길어진다. 이중 기록은 아니며, 같은 파일의 반복 업로드는 기존 묶음을 돌려준다. 운영에서는 새 기간분만 올린다.
- 운영 코드: COST PR #45(`e05bde5`)가 운영에서 실행 중이다(이후 main은 문서 PR 포함). PID 38140, 리스너 하나, `/healthz`·`/readyz` 200, 비로그인 루트 401이다. reservation은 PR #11·#12가 배포돼 있다. 반영 전 백업은 `D:\WebLedgerHost\backups\pre-reservation-authority-20261010`이다.
- OTA 모드: `authority`. `config/card-flow.json`의 `ota_review.mode`와 review DB 경로(`D:\WebLedgerHost\data\ota-review\ota-review.sqlite`)를 따른다.
- 장부: 736행, 순액 73,998,707원. 이전 734행·73,702,707원에서 부분 환불 한 쌍(원결제 1,056,200원, 환불 -760,200원, 순액 296,000원, 0801_노리쿠라 항공료)이 추가됐다.
- 사용자 확정 28건, 확인 필요 보류 15건. 게이트 실행 중 장부·확정·보류는 모두 변하지 않았다.
- 보호 기준선은 고정 숫자가 아니라 게이트가 매번 현재 데이터에서 다시 계산한다. 현재 결과는 legacy 정확 일치 277 + 수동 1 = 278이며, 278건 모두 보존됐다(exact_same 278, changed 0, missing 0, 중복 배정 0, 수동 덮어쓰기 0). 과거 기준 200은 당시 측정치로만 남긴다.
- 신규 자동 4건: 68ca3ad3·306ea544는 이미 장부에 있어 출처 연결만 추가됐고 장부 변화는 없다. cb9f03e7·a77c71ff는 보류다(아래 참조).
- OTA 스냅샷 구조: 미리보기·확정은 워커가 만든 스냅샷만 읽는다. 요청 경로에서는 메일 전체 파싱과 전체 대사를 하지 않는다. 스냅샷 세대와 입력 지문이 일치하지 않으면 `409 STALE_PREVIEW`로 거부하고 조용히 다시 계산하지 않는다. 스냅샷이 준비되지 않았으면 `409 OTA_SNAPSHOT_NOT_READY`를 준다.
- 확정은 원자적이다. 쓰기 직전에 지문을 다시 확인하며, 이미 기록된 요청 ID는 기존 결과를 돌려준다.
- 스냅샷 워커는 명시적으로 시작·중지한다. `stop()`은 스레드를 join하고 반복 호출해도 안전하며, 중지 뒤에는 재계산하지 않는다. 디스크에는 화면용 공개 결과와 지문만 저장하고 전체 데이터는 메모리에만 둔다.
- 운영 로그(`D:\WebLedgerHost\data\ota-review\ota-snapshot.log`)에서 초기 대사는 약 92~103초 한 번이었고 이후에는 확인만 반복된다.
- 화면: 1440×900·390×844 모두 가로 넘침 0. 확정 POST 경로는 테스트로 검증했지만 운영에서는 실행하지 않았다.
- 표적 검증만 수행했다. 전체 회귀는 다시 돌리지 않았다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--대장가이드-항공권-귀속-2026-10-10-reservation-authority-기준"></a>
##### 대장·가이드 항공권 귀속 (2026-10-10, reservation authority 기준)

- **authority 구조**: 대장 신원·항공권 영문명·대장→여행 배정은 reservation이 정본이고 COST는 읽기 전용 소비자다. COST의 여행 일정 권위와 비용 귀속은 COST가 유지한다. PR #43 당시의 "COST 내부 담당자·`guide-identities.json`" 방식은 historical이며 현재 코드는 쓰지 않는다.
- **구현**: reservation에 `guides.flight_name_en`, 관리자 입력란, `GET /api/internal/guides`, tours의 `leader_guide_id`·`include_past=1`을 추가했다. COST는 스냅샷 워커에서만 이를 읽고(`app/reservation_authority.py`), reservation 대장과 COST authoritative 여행을 fldid 또는 정확한 코드+날짜로 브리지해 PR #43의 귀속 엔진에 넣는다. 지문·STALE·개인정보 투영·`guide_airfare_evidence` 분류는 유지했다.
- **운영 데이터 상태**: 대장 13명 중 항공권 영문명 등록 0명(실명 4명), reservation 여행의 `code`는 전부 비어 있다. COST 여행 40건 중 16건만 reserve fldid로 연결되고 15건이 날짜까지 일치하며 24건은 안정 키가 없어 브리지하지 않는다.
- **결과**: 매칭된 항공료 27건은 모두 `HOLD_GUIDE_IDENTITY_UNCONFIRMED`다. 장부 736행·73,998,707원, 보류 15건, 확정 28건은 반영 전후 같다. 보호 기준선은 현재 데이터에서 다시 계산해 277+1=278, 변경·누락·중복·수동 덮어쓰기 0이다.
- **쓰기 보호(2026-10-10)**: reservation authority가 degraded·unavailable이거나 마지막 성공이 90초를 넘으면 새 귀속과 기록이 모두 막힌다. 10분 유예는 화면 표시용이다.
- **master data 입력**: reservation 관리자의 `대장 항공권 정보 확인 필요` 큐에서 영문명을 등록한다(후보는 `과거 자료 후보 사용`을 눌러야 저장). 현재 대장 13명 중 등록 0, 후보 유일 1, 없음 12. 여행 `tours.code`는 127건 모두 비어 있고 모집글에도 명시 코드가 없어 backfill 대상이 0이며, `여행 코드 입력 필요` 큐에서 운영자가 입력한다. 1115 날짜 불일치는 원글만 정본을 갱신하도록 동기화를 고친 뒤 정상 경로로 정상화했다. 브리지는 fldid 16건이 열려 있고 24건은 안정 키가 없다(수동 코드 필요 8, 원천 없음 14, 날짜 충돌 1, 모호 1). 진단은 `tools/guide_bridge_report.py`로 읽기 전용 확인한다.
- **재개 조건**: reservation 관리자 `대장 관리`에서 대장의 항공권 영문명을 한 번 등록하면 다음 스냅샷에서 자동 재평가된다. 개별 거래마다 확인하지 않는다. 기록은 대장 일치·배정 여행의 COST 브리지 성공·일정 완전·귀속 유일 등 모든 조건을 통과한 건만 정상 미리보기→기록 경로로 한다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--cb9f03e7-964400원--hold"></a>
###### cb9f03e7 (964,400원) — HOLD

- 탑승자 2명이며 reservation 대장과 일치 0명(영문명 미등록이라 신원 미확인)이다. 예약자 이름은 탑승자가 아니다.
- 등록된 메일에 결제 완료 안내만 있고 확정(전자항공권) 메일이 없어 연도 없는 월·일뿐이다. 일정을 확정하지 않았다.
- 니가타 여행 authority는 없고 지명만으로 여행을 만들지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--a77c71ff-1081000원--hold"></a>
###### a77c71ff (1,081,000원) — HOLD

- 탑승자 2명이며 reservation 대장과 일치 0명(영문명 미등록이라 신원 미확인)이다.
- 구간은 완전하다(6/16 ICN→CTS, 6/21 CTS→ICN). 대장 일치가 없어 어떤 여행에도 귀속하지 않는다.


<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--ota-통합-후-다음-확인"></a>
#### OTA 통합 후 다음 확인

메일·포털·과거 조사 자료를 명시 등록해 함께 읽는 수정은 운영에 적용했다. 현재 결과와 검증은 [OTA 문서](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-mail-md)의 최신 항목을 따른다. 등록 자료가 바뀌면 다음 조회에서 내용 해시로 대조를 갱신한다. 새로운 수집 자료는 이미 등록한 메일 디렉터리에 저장하거나 `ota-sources.json`에 절대 경로를 추가한다. 후보 문서는 참고 자료로 등록하며 원문 검증 없이 자동 확정하지 않는다.

기존 국민 XLS 1,780개 행을 보존 원본에서 CSV로 변환하고 금액·부호·승인일·매입일·카드 끝자리를 모두 비교했다. 복구 사본 가져오기는 반복 실행 시 전체 테이블이 동일했다. 국내 매입 1,016행은 2026-10-09에 운영으로 가져왔다(신규 482건, 기존 일치 534건, 충돌 0건). 해외 764행은 승인번호가 없지만 카드 끝자리·승인일·통화·외화 금액·가맹점 첫 토큰·총청구액과 원금+수수료 관계를 사용해 재대조했다. 기존과 동일 464건(복수 후보 34건 포함), 안전 신규 227건, 취소 70건, 현금서비스 등 특수 3건으로 구분했고 안전 신규 227건만 복구 사본에서 충돌 0·재수신 동일을 확인한 뒤 운영에 가져왔다. 전체 해외 파일은 다시 가져오지 않고 취소·특수 행은 별도 검토한다. 조사 근거와 복구 사본은 운영 문서의 최신 절을 따른다.

OTA-first 격리 pilot은 성공했고 Trip.com 항공료 표기와 정확 가맹점 보정을 main에 병합했다([규칙 문서](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md)). 운영 matcher를 OTA-first로 바꾸는 전환 코드는 아직 없다. 전환하려면 별도 설계와 검증이 필요하다. 활성 규칙은 0건이며 review DB의 미승인 proposal 1건은 "이번 건만"으로 처리했다.

2026-10-10 운영 기준 main과 `C:/AX/cost`의 runtime code는 PR #22 병합 SHA `d8f8b22fa32b900adbdb921133a0d86068d7e8d8`로 맞췄다. 반영 전에 `D:/WebLedgerHost/backups/board-before-main-sync-20261010.sqlite`를 만들고 장부 734행과 SQLite 무결성을 확인했다. 보호 파일 4개는 그대로 보존했다. `tools/restart_real_review_host.ps1`로 재시작했고 PID는 9384→36740, 8751 리스너는 하나, `/healthz`·`/readyz`는 200, 비로그인 보호 루트는 401, DB 무결성은 ok다. OTA authority 환경 변수는 켜지 않아 운영은 `legacy` 모드다.

2026-10-09 기준이다. 현재 수치는 [운영 문서](../operations.md)를 따른다. 과거 단계별 실행과 검증은 [과거 인계](operations-through-20261027.md#src-docs-history-handoff-through-20261007-md)에 보존했다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--현재까지-완료"></a>
#### 현재까지 완료

승인·취소 중복 판정, ready 의미 통일, 출력 조회의 쓰기 의존 제거, 여행 목록 수입 안내와 OTA 메타데이터 전달을 적용했다. 최초 615건과 최신 일정 원본으로 검증한 추가 119건을 운영 장부에 기록해 총 734건, 순액 73,702,707원이다. 일정 근거는 최신 원본을 기준으로 정리한다. 과거 일정 사본으로 권위를 우회하지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--남은-작업과-재개-조건"></a>
#### 남은 작업과 재개 조건

| 항목 | 조사 결과와 다음 조치 |
| --- | --- |
| 여행 시트 누락 13개 | 최신 운영 원본에는 해당 시트가 없다. 읽기 전용 Drive 재조사에서 에히메·교토·나가센도·아오모리·오사카·알펜루트·부산·6월 북해도·레분토와 리시리·묘코·아키타 11개는 `(주) 숲길따라 감성여행_아슬란_26Q1` 보관 워크북에서 찾았고 기존 권위 날짜와 일치했다. 그러나 모두 사본 자료이므로 historical corroborating evidence로만 보존하며 일정 authority나 장부 차단 해제 근거로 승격하지 않는다. 도고·야쿠시마는 추가 Drive 검색에서도 명시 시트를 찾지 못했다. |
| 몽골·8월 북해도 2개 | 명시 종료일의 authoritative source를 아직 찾지 못했다. 결제일·파일명·과거 사본으로 종료일을 추론하지 않는다. 최신 원본 또는 동등한 공식 일정 근거가 확보될 때만 등록한다. |
| 항공권 부분 환불 | PR #22에서 원결제·환불 pair 연결, 파생 순액, stale preview, rollback/idempotency 보호를 구현했다. 실제 카드 근거는 원결제 1,056,200원과 환불 -760,200원, 순액 296,000원이다. 2026-10-10 정상 commit 경로로 기록을 마쳤다(장부 734→736행, 순액 296,000원 증가). 원본 두 금액은 수정하지 않았다. |
| Agoda 146,018원 | 기존 전수조사에서 실제 결제·카드·기간 근거를 찾았다. 이용 완료나 취소 완료 자료와는 구분하며 기존 사용자 보류를 유지한다. 기존 메일·포털을 다시 조사하지 않고 보존된 상세 결과부터 읽는다. |
| Agoda 64,814원 | 카드 원장에 같은 날 동일 승인번호(41909645)의 전액 취소 쌍이 있어 카드 회계상 순액 0원이다. 96,842원 후보는 별개의 8/23 결제다. 비용 전기는 필요 없지만, 이 카드 취소 확인을 과거 proposed OTA 예약 연결의 확정으로 해석하지 않는다. |
| 국민 원본 XLS 반영 | 국내 매입 신규 482건과 해외 매입 안전 신규 227건을 운영에 가져왔다. 해외 764행의 나머지는 기존과 동일 464건, 취소 70건, 현금서비스 등 특수 3건으로 구분한다. 전체 해외 파일을 다시 import하지 않으며 취소·특수 행은 일반 비용으로 자동 처리하지 않는다. 바이너리 XLS의 직접 웹 업로드 지원은 여전히 별도 과제다. |
| 신규 국내·해외 709건 | 앱 분류 함수로 처리해 자동 분류 331건, 사용자 검토 377건(예약 근거 필요 250, 여행지 보류 126, 기타 1), 보존 1건으로 나눴다. 사용자 확정이나 장부 기록은 만들지 않았다. 검토 대상은 카드 검토 화면에서 확인한다. |
| 카드 무인 로그인 | 기존 공식 자동입력의 입력란 탐지 실패 상태다. 암호를 출력하거나 외부 제품·보안 설정을 우회하지 않는다. 재부팅·복구·재설치는 하지 않는다. |
| 실제 로그인 브라우저 | 이번 도구 환경에는 로그인된 브라우저가 없었다. 현재의 서버·렌더러 검사와 구분해 남긴다. |

여행 시트 누락 목록은 에히메, 교토, 나가센도, 아오모리, 오사카, 알펜루트, 부산, 6월 북해도, 레분토와 리시리, 묘코, 아키타, 도고, 야쿠시마다. 앞의 11개는 보관용 26Q1 워크북에서 corroborating evidence를 찾았지만 운영 authority로 쓰지 않는다. 도고·야쿠시마는 추가 Drive 검색에서도 명시 시트를 찾지 못했다. 보관 워크북 SHA-256은 `4d073fba4a95c10fb9a821ae98e3880a1781c1c9291a627220dcebaa953f72c2`다. Drive 연결은 읽기 전용이었고 쓰기는 하지 않았다. 일정 차단 926건과 기존 보류 16건은 이 자료만으로 해제하지 않는다. 보류 해제나 새 환불 행 생성은 기존 [업무 규칙](specs-20261110/finance.md#src-docs-business-rules-md)을 따른다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--바로-읽을-로컬-증거"></a>
#### 바로 읽을 로컬 증거

- `latest-schedule/plan.json`: 최신 원본과 기존 날짜가 같은 여행 6개의 변경 계획이다.
- `latest-schedule/candidate-result.json`, `live-result.json`: 복구 사본과 운영 추가 기록의 개별 비교·반복 실행 결과다.
- `pending-audit.json`, `latest-schedule-comparison.json`: 일정과 현재 차단 내역이다.
- `refund-link-check.json`, `refund-review.md`: 실제 카드 부분 취소 연결 근거와 검토안이다.
- `agoda-target-portal-records.json`, `agoda-target-mail-evidence.json`: 146,018원 포털·메일 근거다.
- `agoda-64814-prior-link.json`, `agoda-64814-portal.json`: 과거 후보와 금액 불일치의 근거다.

위 파일은 모두 `.local-archive/pending-docs-20261008/` 아래에 있으며 고객 원본이나 상세 자료를 Git 또는 외부 에이전트에 보내지 않는다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--코드와-테스트-관리"></a>
#### 코드와 테스트 관리

현재 작업 폴더에는 이번 작업과 이전에 승인된 미커밋 변경이 함께 있다. reset·revert·stash·clean으로 없애지 않는다. 코드와 합성 자료만 담은 `C:/AX/cost-zero-code-20261007`에서 구현한 뒤 오류 수정·검증·통합·운영 반영을 수행했다. 최종 격리 코드도 동기화했다. 같은 파일·운영 DB의 작성자는 하나로 유지한다.

이전 전체 회귀는 종료됐다. `2222 passed, 2 failed, 3 skipped, 2384 subtests passed`이며 로그는 `.local-archive/partial-fixes-20261007/full-regression.log`다. 이후에는 바뀐 범위의 표적 검증만 수행한다. 과거 숫자를 현재 통과 결과로 재사용하거나 전체 회귀를 반복하지 않는다.

사용자 파일 네 개는 수정·삭제·stage하지 않는다.

- `edit_card_flow.py`
- `pending-card-evidence-utf8.patch`
- `pending-card-evidence.patch`
- `webledger.work.operator.sqlite.checkpoint.json`

운영 조치는 검증된 복구 사본과 적용 전 상태 비교 후 수행한다. 날짜·금액·ID·원본·사용자 확정을 보존한다. 현재 수정과 실행 결과를 먼저 확인하고 Git에는 코드와 문서만 필요한 파일을 명시해 추가한다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-10-배포-후-남은-운영-확인"></a>
#### 2026-10-10 배포 후 남은 운영 확인

PR #22 통합 revision의 전체 회귀는 **2516 passed / 3 skipped / 2400 subtests passed, 실패 0**이었다. skip은 비공개 Agoda 산출물 부재 2건과 Windows chmod 제약 1건이다. 운영 재시작 후 기본 화면 로그인은 확인했으며 장부 734건, 카드 자료 2,384건, 확인 필요 471건, 분류대기 238건이었다.

이 절은 당시 상태의 기록이다. 부분 환불 기록, OTA 검토 화면 확인, authority 전환은 위 "현재 상태" 절에서 완료된 것으로 본다.

<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--최신-표적-검증"></a>
#### 최신 표적 검증

기존 루트 DB 존재에 의존하던 호스팅 검사를 임시 작업 폴더로 격리했고, 출력 HTTP spy 검사는 배경 카드 worker를 멈춘 뒤 worker 없는 서버에서 실행하도록 보완했다. 운영 검사 도구는 일정 보류와 서버 장애를 분리하며 미조회 경로는 검사 미완료로 표시하고 실패 시 비정상 종료한다.

통합 저장소의 호스팅·출력·운영 검사 묶음은 91개와 하위 검사 26개가 통과했다. 운영 읽기 전용 검사도 성공했으며 734개 장부 행, 유효 일정 25개·대기 일정 15개를 구분해 보고한다. 운영 데이터 렌더러는 여행 12개 탭 496건과 분류대기 238건을 확인했다.


<a id="src-docs-archive-ota-legacy-20261023-session-handoff-md--2026-10-11-kb-3채널-대사와-배포"></a>
#### 2026-10-11 KB 3채널 대사와 배포

격리 SQLite 복사본에서 승인 2,124행, 국내 매입 1,016행, 해외 매입 764행을 웹 카드 처리 경로의 수신 단계로 대사했다. 결과는 `outputs/kb-three-channel-reconcile-result.json`에 저장했다. 입력 순서 두 가지의 의미 결과가 같았고, 같은 파일 재입력은 재사용됐다. 기존 거래 ID, 장부, 확정, 환불 보류와 OTA 연결은 보존됐다. 해외 매입 신규 후보 56건은 모두 취소이며 신규 일반 매입과 특수 거래는 0건이다.

과거 709건 경고는 당시 DB 지문과 입력 해시가 없어 직접 비교할 수 없다. 같은 현재 초기 DB에서 과거 경고 규칙은 710건, 현재 유사 후보는 0건이었다. 승인 파일은 비용 행 없이 증거로 저장되며, 카드 검토 화면에 승인 행과 연결 요약을 보이도록 했다. 합성 표적 검사 10건이 통과했다.

대사 자체는 읽기 전용 운영 DB의 격리 복사본에서만 실행했다. 이후 PR #56 배포 시 승인 증거용 빈 표 두 개가 운영 DB에 생성됐으며, KB 행은 넣지 않았다. 거래 6,037건, 장부 736행과 73,998,707원, 확정 28건, 보류 15건, 접수 묶음 7건은 유지됐다. OTA 검토 DB도 변하지 않았다. 복구 사본과 재시작 후 스모크 결과는 `docs/operations.md`의 2026-10-11 절을 따른다.

---

<a id="src-docs-autonomous-cycle-checkpoint-md"></a>
<a id="src-docs-autonomous-cycle-checkpoint-md--현재-운영-반영-2026-10-12"></a>

## autonomous-cycle-checkpoint

통합 전 경로: `docs/autonomous-cycle-checkpoint.md`

<a id="src-docs-autonomous-cycle-checkpoint-md--이전-자율-실행-체크포인트--역사-자료"></a>
### 이전 자율 실행 체크포인트 — 역사 자료

> 이 파일은 과거 에이전트 실행/긴 체크포인트의 보관 경로입니다. **후속 개발을 지시하는 활성 TODO가 아닙니다.**

- **현재 구현 진입:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **정확한 작업 범위와 테스트:** [OTA–카드 정책 A 구현](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **변경 전 전체 실행 기록:** [autonomous-cycle-checkpoint.md 원문](ota-legacy.md#src-docs-archive-ota-legacy-20261023-autonomous-cycle-checkpoint-md)
- **당시 운영 증거:** [operations.md](../operations.md)

과거 체크포인트의 코드/브랜치 상태는 당시 기록입니다. 배포 여부는 main 및 실제 운영 SHA로만 판단하세요.

---

<a id="src-docs-autonomous-implementation-playbook-md"></a>

## autonomous-implementation-playbook

통합 전 경로: `docs/autonomous-implementation-playbook.md`

<a id="src-docs-autonomous-implementation-playbook-md--이전-문서--autonomous-implementation-playbookmd"></a>
### 이전 문서 — autonomous-implementation-playbook.md

> **과거 구현·정책 기록입니다. 최신 COST V3 구현 지시가 아닙니다.** 현재 목표 정책과 다른 `HOLD`/자동배정/전체 검증 지시가 포함될 수 있습니다.

- **공식 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **최신 OTA–카드 A 정책과 R0~R6:** [OTA 대사 통합 명세](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **V3 여행 귀속·AI·참가자:** [V3 상세 명세](specs-20261110/participants.md#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md)
- **보존한 과거 원문:** [autonomous-implementation-playbook.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-autonomous-implementation-playbook-md)

이전의 정책 표·실험 TODO와 당시 운영 건수를 최신 요구로 사용하지 마세요. **현재 코드의 실행 사실**은 해당 코드와 [운영 이력](../operations.md)에서 확인합니다. 승인된 가맹점·날짜 허용·수동 결정의 실제 실행 값은 `config/ota-matching-defaults.json`과 저장된 사용자 규칙을 검증한 다음 새 명세에 따라 개편합니다.

---

<a id="src-docs-ota-first-core-md"></a>

## ota-first-core

통합 전 경로: `docs/ota-first-core.md`

<a id="src-docs-ota-first-core-md--이전-문서--ota-first-coremd"></a>
### 이전 문서 — ota-first-core.md

> **보관된 과거 설계/실행 기록 (2026-10-08~10-16); 신규 개발의 최종 요구사항 아님.** 과거 OTA-first 코어의 단독 설계·합성 검사 결과입니다. 현재 `COST V3`에서는 낮은 추론도 여행에 우선 배정하고, 카드 원본이 금융적으로 유효하면 OTA 링크가 미확정이어도 내부 경비 준비를 허용합니다. 원본·환불·수동 확정 보호는 유지합니다.

- **현재 단일 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **현행 목표 OTA 대사 계약:** [OTA–카드 A 정책](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **삭제하지 않고 보관한 전문:** [ota-first-core.md 원문](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-core-md)
- **당시 운영·검증 사실:** [운영 이력](../operations.md)

이 경로의 구형 HOLD/결제일·검증 TODO·실험 지시는 **역사적 사실로만 읽고 구현 과제로 자동 실행하지 마세요.** 실제 운영 구현은 여전히 구형 코드일 수 있으며 신규 정책을 구현·배포했다고 주장하지 않습니다.

---

<a id="src-docs-ota-first-isolated-review-pilot-md"></a>

## ota-first-isolated-review-pilot

통합 전 경로: `docs/ota-first-isolated-review-pilot.md`

<a id="src-docs-ota-first-isolated-review-pilot-md--이전-문서--ota-first-isolated-review-pilotmd"></a>
### 이전 문서 — ota-first-isolated-review-pilot.md

> **보관된 과거 설계/실행 기록 (2026-10-09); 신규 개발의 최종 요구사항 아님.** 2026-10-09 격리 OTA 검토 파일럿의 실제 실행 증거입니다. 현재 `COST V3`에서는 낮은 추론도 여행에 우선 배정하고, 카드 원본이 금융적으로 유효하면 OTA 링크가 미확정이어도 내부 경비 준비를 허용합니다. 원본·환불·수동 확정 보호는 유지합니다.

- **현재 단일 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **현행 목표 OTA 대사 계약:** [OTA–카드 A 정책](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **삭제하지 않고 보관한 전문:** [ota-first-isolated-review-pilot.md 원문](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-isolated-review-pilot-md)
- **당시 운영·검증 사실:** [운영 이력](../operations.md)

이 경로의 구형 HOLD/결제일·검증 TODO·실험 지시는 **역사적 사실로만 읽고 구현 과제로 자동 실행하지 마세요.** 실제 운영 구현은 여전히 구형 코드일 수 있으며 신규 정책을 구현·배포했다고 주장하지 않습니다.

---

<a id="src-docs-ota-first-ui-md"></a>

## ota-first-ui

통합 전 경로: `docs/ota-first-ui.md`

<a id="src-docs-ota-first-ui-md--이전-문서--ota-first-uimd"></a>
### 이전 문서 — ota-first-ui.md

> **보관된 과거 설계/실행 기록 (2026-10); 신규 개발의 최종 요구사항 아님.** 구형 OTA HOLD 중심 검토 UI 명세·실행 기록입니다. 현재 `COST V3`에서는 낮은 추론도 여행에 우선 배정하고, 카드 원본이 금융적으로 유효하면 OTA 링크가 미확정이어도 내부 경비 준비를 허용합니다. 원본·환불·수동 확정 보호는 유지합니다.

- **현재 단일 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **현행 목표 OTA 대사 계약:** [OTA–카드 A 정책](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **삭제하지 않고 보관한 전문:** [ota-first-ui.md 원문](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-ui-md)
- **당시 운영·검증 사실:** [운영 이력](../operations.md)

이 경로의 구형 HOLD/결제일·검증 TODO·실험 지시는 **역사적 사실로만 읽고 구현 과제로 자동 실행하지 마세요.** 실제 운영 구현은 여전히 구형 코드일 수 있으며 신규 정책을 구현·배포했다고 주장하지 않습니다.

---

<a id="src-docs-ota-first-verification-plan-md"></a>

## ota-first-verification-plan

통합 전 경로: `docs/ota-first-verification-plan.md`

<a id="src-docs-ota-first-verification-plan-md--이전-문서--ota-first-verification-planmd"></a>
### 이전 문서 — ota-first-verification-plan.md

> **보관된 과거 설계/실행 기록 (2026-10); 신규 개발의 최종 요구사항 아님.** 과거 OTA-first 검증 체크리스트입니다. 현재 `COST V3`에서는 낮은 추론도 여행에 우선 배정하고, 카드 원본이 금융적으로 유효하면 OTA 링크가 미확정이어도 내부 경비 준비를 허용합니다. 원본·환불·수동 확정 보호는 유지합니다.

- **현재 단일 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **현행 목표 OTA 대사 계약:** [OTA–카드 A 정책](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **삭제하지 않고 보관한 전문:** [ota-first-verification-plan.md 원문](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-first-verification-plan-md)
- **당시 운영·검증 사실:** [운영 이력](../operations.md)

이 경로의 구형 HOLD/결제일·검증 TODO·실험 지시는 **역사적 사실로만 읽고 구현 과제로 자동 실행하지 마세요.** 실제 운영 구현은 여전히 구형 코드일 수 있으며 신규 정책을 구현·배포했다고 주장하지 않습니다.

---

<a id="src-docs-ota-first-verification-report-md"></a>

## ota-first-verification-report

통합 전 경로: `docs/ota-first-verification-report.md`

<a id="src-docs-ota-first-verification-report-md--ota-기준-대조-구현과-읽기-전용-검증"></a>
### OTA 기준 대조 구현과 읽기 전용 검증

> **과거 시점의 검증 보고서 (2026-10-08).** 수치는 해당 당시 원본/코드 스냅샷에만 해당하며 최신 운영 매칭률·현재 개발 지시가 아니다. 2026-10-23 사용자 최종 목표는 [COST V3 단일 진입점](../COST_V3_START_HERE.md)과 [OTA 정책 A](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)이다. 본문 원래 검증 기록은 역사 증거로 유지한다.


2026-10-08에 확인했습니다. 운영 대조 권위를 바꾸지 않았으며, 운영 코드·데이터베이스·원본 자료도 수정하지 않았습니다. 운영 자료 검증은 로컬에서 읽기 전용으로 수행했습니다.

<a id="src-docs-ota-first-verification-report-md--1-ota-사건"></a>
#### 1. OTA 사건

정규화 결과는 1,304건입니다. 실제 결제가 검증된 charge는 383건, 환불 완료가 검증된 refund는 0건입니다. 예정·비결제·결제 미검증은 921건이며, 그중 결제 예정은 83건입니다. 예약이나 미검증 자료를 실제 카드 청구로 승격하지 않았습니다.

기존에 등록된 메일 폴더 5곳, 포털 데이터베이스 11개, 참고 문서 53개를 사용했습니다. 재수집하지 않았습니다. 참고 문서는 결제 권위로 승격하지 않습니다. 등록 자료를 읽을 수 없으면 부분 자료로 신규 자동 연결을 생성하지 않습니다.

실제 결제 사건 383건의 결과는 다음과 같습니다.

| 상태 | 건수 |
| --- | ---: |
| 정확 연결 | 200 |
| 카드 없음 | 90 |
| 후보 모호 | 21 |
| 금액 불일치 | 13 |
| 결제일 미확인 | 59 |
| 근거 충돌 | 0 |

OTA 보류는 총 183건입니다. 결제가 확인되지 않은 예약은 이 보류 건수에 포함하지 않습니다.

<a id="src-docs-ota-first-verification-report-md--2-기존-정확-연결-비교"></a>
#### 2. 기존 정확 연결 비교

기존 정확 연결 200건 모두 같은 카드 거래로 유지됐습니다. 누락 0건, 다른 카드로 변경 0건, 고정 연결 충돌 0건, 카드 중복 배정 0건입니다. 코어 대조와 실제 화면 연결부에서 각각 확인했습니다.

기존 연결을 삭제한 뒤 다시 추론하지 않습니다. 기존 보고서의 제공자·예약·원본 다이제스트·카드 원문 해시·방향을 확인하고, 기존에 연결된 카드 원행의 금액·통화·카드 정보를 비교해 유일한 사건에 고정합니다. 보고서에 없는 사실을 채우지 않습니다. 기존 카드 기준 대조는 임시 비교 경로로 남아 있습니다.

<a id="src-docs-ota-first-verification-report-md--3-기존-미연결-177건"></a>
#### 3. 기존 미연결 177건

기존 177건은 카드 거래 집계입니다. OTA 결제 사건 177개로 바꿔 만들지 않았습니다.

| 분류 | 카드 거래 수 |
| --- | ---: |
| 카드 없음 | 0 |
| 후보 모호 | 0 |
| 금액 불일치 | 13 |
| 결제일 미확인 | 19 |
| 근거 충돌 | 0 |
| 대응하는 검증된 금전 사건 근거가 없음 | 145 |
| 합계 | 177 |

마지막 145건은 예정·예약·참고 자료를 실제 결제로 추정해 연결하지 않은 결과입니다. OTA 사건 전체 보류 183건과 위 카드 177건의 분해는 서로 다른 집계입니다.

<a id="src-docs-ota-first-verification-report-md--4-수동-검토-화면"></a>
#### 4. 수동 검토 화면

390×844와 1440×900에서 같은 날짜의 합성 카드 거래 12건을 모두 표시했습니다. 가맹점이나 금액으로 숨기지 않습니다. 카드사·승인일·매입일·가맹점·원화·외화·통화·승인번호·취소 및 환불 상태·기존 연결을 확인했습니다. 연결된 카드는 표시하되 선택을 막습니다.

미리 보기에서 차이를 보여 주고 명시 확인을 거쳐 수동 연결합니다. 실제 코어·HTTP 연결부·분리 검토 저장소를 사용한 합성 브라우저 검사도 통과했습니다. 가로 넘침은 두 화면 크기 모두 0입니다. 근거가 사라진 수동 연결은 읽기 전용 스냅샷과 경고로 표시하며 카드 점유를 유지합니다.

첫 조회와 미리 보기는 저장소 폴더·데이터베이스·스키마를 생성하거나 변경하지 않습니다. 실제 운영 자료를 조회한 검증에서도 검토 저장소 생성 0건과 장부 테이블 변경 0건을 확인했습니다.

<a id="src-docs-ota-first-verification-report-md--5-규칙-제안"></a>
#### 5. 규칙 제안

합성 자료에서 수동 연결 저장, 제안 생성, 승인 전 활성 규칙 0개, 명시 승인 뒤 다음 사건 적용, 이번 건만 선택 뒤 다음 사건 미적용을 확인했습니다. 실제 운영 수동 연결은 저장하지 않았습니다.

제안은 실제 원화 차이와 날짜 차이를 기록하고 좁은 제공자·항목·가맹점 또는 카드 조건을 묻습니다. 금액 차이를 할인으로 단정하지 않습니다. 범위를 벗어나거나 검증되지 않은 조건은 수정 확인이 필요합니다. 단순 활성 표시·비활성 규칙·제공자와 항목만 있는 넓은 규칙은 자동 대조에 사용하지 않습니다. 사용자 연결은 자동 대조로 덮어쓰지 않습니다.

<a id="src-docs-ota-first-verification-report-md--6-검사"></a>
#### 6. 검사

- 최종 코어 표적 검사: 63 passed.
- 검토 브랜치 화면 및 브라우저 표적 검사: 21 passed, 2 subtests passed.
- 브라우저: 합성 자료로 두 화면 크기와 실제 코어 연결 흐름을 확인했습니다.
- 전체 회귀를 한 번 실행했습니다. `2394 passed, 1 failed, 3 skipped, 2398 subtests passed`, 1296.80초이며 종료 코드는 1입니다. 전체 통과로 표시하지 않습니다.
- 실패는 새 OTA 코드가 아니라 기존 문서 정리에서 `docs/operations.md`의 `WEBLEDGER_DATA_ROOT`, 절대 경로, 지속 마운트 예시 안내가 빠진 데서 발생했습니다. 문서 원본을 로컬 보존한 뒤 기존 안내를 복원했고 해당 문서 검사만 `1 passed`로 확인했습니다. 실행 코드와 테스트 코드는 바꾸지 않았으며 전체 회귀를 반복하지 않았습니다.

전체 회귀 공간은 운영 체크아웃의 기존 미커밋 수정과 새 기능을 함께 포함한 격리 사본입니다. 검토 브랜치에는 기존의 다른 수정은 옮기지 않았습니다. 기존 검증 시점의 새 실행 코드와 테스트 파일은 두 공간에서 바이트 단위로 같았으며, 카드 흐름 파일에는 같은 OTA 변경만 적용했습니다. 검토 브랜치 자체의 화면·브라우저 검사와 운영 읽기 전용 비교는 별도로 통과했습니다.

merge 전 선택 안전성과 거래 방향 표시 보완은 관련 표적 검사만 실행해 `7 passed, 2 subtests passed in 5.44s`로 확인했습니다. 같은 날짜의 중복·파싱 오류·충돌 거래는 모두 표시하되 선택을 막으며, 세 상태의 직접 HTTP 확정 요청도 거부합니다. 정상 거래의 선택과 확정은 유지합니다. 방향 표시는 `transaction_direction`, `direction`, `미확인` 순서를 따릅니다. 합성 브라우저의 390×844와 1440×900에서 선택 차단 사유와 정상 거래 선택을 확인했고 가로 넘침은 0입니다. 기존 표적 검사 합계 84건과 위 전체 회귀 결과는 이전 검증 기록으로 유지하며, 전체 회귀와 운영 자료 대조는 다시 실행하지 않았습니다.

<a id="src-docs-ota-first-verification-report-md--7-데이터-보존"></a>
#### 7. 데이터 보존

장부 734건, 사용자 확정, 보류, 원본 카드 거래를 보존했습니다. 검증 전후 전체 테이블 내용과 스키마가 같으며, 이전 안전 스냅샷과 비교한 업무 테이블 변경도 없습니다. 마지막 검사에서 테이블 75개와 원본 파일 224개를 비교했습니다. 등록된 원본 파일 변경 0건, 운영 코드 변경 0건, 보호 대상 사용자 파일 4개 변경 0건입니다. 합계만 비교한 결과가 아닙니다.

원본과 상세 검증 자료는 운영 저장소의 `.local-archive/ota-first-20261008/`에 로컬 보존합니다. 고객 원본·운영 데이터베이스·실제 연결 식별자·상세 원문을 Git 변경에 포함하지 않습니다.

<a id="src-docs-ota-first-verification-report-md--8-운영"></a>
#### 8. 운영

운영 전환을 하지 않았습니다. 기본 기능은 비활성화 상태입니다. 운영 재시작·운영 데이터베이스 쓰기·재수집·자료 갱신·재분류를 실행하지 않았습니다. 별도 승인 전에는 새 대조기를 운영 권위로 전환하지 않습니다.

<a id="src-docs-ota-first-verification-report-md--9-git"></a>
#### 9. Git

기준 main은 `37bd457341d68185d533a243eada64162537f943`입니다. 운영 HEAD와 origin/main은 이 기준을 유지합니다. 검토 브랜치는 `feature/ota-first-review-20261008`, 위치는 `C:/AX/cost-ota-first-review-20261008`입니다. 기존 검증 변경은 `f96bcf2488c480bc7977bce34d057810501c207c`로 커밋하고 같은 원격 feature 브랜치에 푸시했습니다. main 병합과 운영 전환은 하지 않았습니다.

이번 선택 안전성과 방향 표시 보완 코드 커밋은 `41d15d1715ac2eed20428239f19a34a455746928`입니다. 코드 커밋 뒤 이 SHA와 표적 검사 결과를 기록하는 문서 커밋을 별도로 남깁니다. 이번 변경은 `webapp/ota_payment_review.py`, 관련 테스트 두 파일, 이 보고서에만 포함되며, 나머지 기존 기능 파일과 화면 캡처는 변경하지 않았습니다. 최종 브랜치 HEAD는 문서 커밋을 포함합니다.

변경 파일은 다음 14개입니다.

- `app/ota_payments.py`
- `app/ota_review.py`
- `webapp/ota_payment_review.py`
- `webapp/card_flow.py`
- `tests/card_pipeline/test_ota_payments.py`
- `tests/card_pipeline/test_ota_review.py`
- `webapp/tests/test_ota_payment_review.py`
- `webapp/tests/test_ota_payment_review_browser.py`
- `docs/ota-first-core.md`
- `docs/ota-first-ui.md`
- `docs/ota-first-verification-plan.md`
- `docs/ota-first-verification-report.md`
- `docs/ota-first-ui-mobile.png`
- `docs/ota-first-ui-desktop.png`

사용자 파일 4개와 이전의 다른 작업 변경은 검토 브랜치에 포함하지 않았습니다.

전체 회귀가 발견한 문서 누락은 기존 운영 체크아웃의 `docs/operations.md`와 격리 회귀 사본에서 배포 안내만 복원했습니다. 최신 OTA 수치와 기존 업무 내용을 보존했습니다. 검토 브랜치 기준 Git 문서에는 해당 안내가 이미 있어 이 기존 문서 수정은 새 OTA 기능 변경 14개에 포함하지 않았습니다. 원본 문서와 복원한 단락의 패치는 로컬 검증 보관소에 보존했습니다.

---

<a id="src-docs-ota-matching-rule-defaults-md"></a>

## ota-matching-rule-defaults

통합 전 경로: `docs/ota-matching-rule-defaults.md`

<a id="src-docs-ota-matching-rule-defaults-md--이전-문서--ota-matching-rule-defaultsmd"></a>
### 이전 문서 — ota-matching-rule-defaults.md

> **과거 구현·정책 기록입니다. 최신 COST V3 구현 지시가 아닙니다.** 기존 업체별 승인 규칙 및 실험 제안 이력을 기록하던 파일이며, 현재 목표 정책과 다른 `HOLD`/자동배정/전체 검증 지시가 포함될 수 있습니다.

- **공식 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **최신 OTA–카드 A 정책과 R0~R6:** [OTA 대사 통합 명세](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **V3 여행 귀속·AI·참가자:** [V3 상세 명세](specs-20261110/participants.md#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md)
- **보존한 과거 원문:** [ota-matching-rule-defaults.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-matching-rule-defaults-md)

이전의 정책 표·실험 TODO와 당시 운영 건수를 최신 요구로 사용하지 마세요. **현재 코드의 실행 사실**은 해당 코드와 [운영 이력](../operations.md)에서 확인합니다. 승인된 가맹점·날짜 허용·수동 결정의 실제 실행 값은 `config/ota-matching-defaults.json`과 저장된 사용자 규칙을 검증한 다음 새 명세에 따라 개편합니다.

---

<a id="src-docs-ota-matching-terms-md"></a>

## ota-matching-terms

통합 전 경로: `docs/ota-matching-terms.md`

<a id="src-docs-ota-matching-terms-md--이전-문서--ota-matching-termsmd"></a>
### 이전 문서 — ota-matching-terms.md

> **과거 구현·정책 기록입니다. 최신 COST V3 구현 지시가 아닙니다.** 기존 정확 매칭/결제일 용어와 과거 HOLD 정책을 기록하던 파일이며, 현재 목표 정책과 다른 `HOLD`/자동배정/전체 검증 지시가 포함될 수 있습니다.

- **공식 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **최신 OTA–카드 A 정책과 R0~R6:** [OTA 대사 통합 명세](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **V3 여행 귀속·AI·참가자:** [V3 상세 명세](specs-20261110/participants.md#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md)
- **보존한 과거 원문:** [ota-matching-terms.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-matching-terms-md)

이전의 정책 표·실험 TODO와 당시 운영 건수를 최신 요구로 사용하지 마세요. **현재 코드의 실행 사실**은 해당 코드와 [운영 이력](../operations.md)에서 확인합니다. 승인된 가맹점·날짜 허용·수동 결정의 실제 실행 값은 `config/ota-matching-defaults.json`과 저장된 사용자 규칙을 검증한 다음 새 명세에 따라 개편합니다.

---

<a id="src-docs-ota-mail-md"></a>

## ota_mail

통합 전 경로: `docs/ota_mail.md`

<a id="src-docs-ota-mail-md--이전-문서--ota_mailmd"></a>
### 이전 문서 — ota_mail.md

> **과거 구현·정책 기록입니다. 최신 COST V3 구현 지시가 아닙니다.** 과거 OTA 메일 대사 구조와 기간별 처리 현황을 기록하던 파일이며, 현재 목표 정책과 다른 `HOLD`/자동배정/전체 검증 지시가 포함될 수 있습니다.

- **공식 개발 진입점:** [COST V3 START HERE](../COST_V3_START_HERE.md)
- **최신 OTA–카드 A 정책과 R0~R6:** [OTA 대사 통합 명세](specs-20261110/ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)
- **V3 여행 귀속·AI·참가자:** [V3 상세 명세](specs-20261110/participants.md#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md)
- **보존한 과거 원문:** [ota_mail.md](ota-legacy.md#src-docs-archive-ota-legacy-20261023-ota-mail-md)

이전의 정책 표·실험 TODO와 당시 운영 건수를 최신 요구로 사용하지 마세요. **현재 코드의 실행 사실**은 해당 코드와 [운영 이력](../operations.md)에서 확인합니다. 승인된 가맹점·날짜 허용·수동 결정의 실제 실행 값은 `config/ota-matching-defaults.json`과 저장된 사용자 규칙을 검증한 다음 새 명세에 따라 개편합니다.
