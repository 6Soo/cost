# 과거 작업 기록

2026-10-08에 현재 상태 문서에서 분리한 기록이다. 아래 실행 시점의 수치·제한·미완료 상태를 현재 상태로 해석하지 않는다. 최신 상태는 [운영 문서](../operations.md)와 [인계 문서](../session_handoff.md)를 따른다.

# 다음 세션 인계

## 2026-10-07 0원 문제 수정과 실제 장부 반영

사용자의 “필요한 작업 조치해” 지시에 따라 이번 카드 장부 문제에 필요한 운영 반영을 수행했다. 아래 이전 운영 변경 금지 기록은 이번에 승인된 작업의 실행 전 상태이며, 다른 운영 작업까지 승인된 뜻은 아니다.

승인번호가 같은 결제와 취소를 중복으로 처리하던 오류를 수정했다. 거래 ID를 먼저 확인하고, 거래 ID가 없는 과거 장부 행에만 카드사·카드 끝자리·승인번호·일자·부호 있는 금액·거래 종류를 함께 비교한다. 원문 해시만으로 실제 복수 거래를 합치지 않는다. 변경 파일은 `webapp/card_flow.py`와 `webapp/tests/test_card_flow.py`이며 기존 미반영 수정도 보존했다.

운영 DB의 검증된 복구 사본에서 먼저 실행한 뒤 운영 장부에 615건, 취소를 포함한 순액 54,802,879원을 기록했다. 여행 7개 탭에 377건, 분류대기 장부에 238건이 표시된다. 일정 권위 검증에 걸린 1,045건과 기존 보류 16건은 기록하지 않았다. 일부 과거 여행 시트가 최신 일정 파일에 없으므로 일정 검증을 우회하거나 거래를 새 여행으로 배정하지 않았다. 모든 여행의 0원 상태가 해소된 것은 아니다.

원본 거래 5,328건의 금액·날짜·ID와 나머지 필드를 개별 비교했다. 기록된 거래의 기존 확정 상태 변경 외 원본 필드 변경은 없었다. 변경 대상 외 68개 테이블은 행별 해시가 같고 스키마도 동일하다. 무결성 검사와 외래 키 검사를 통과했다. 같은 기록 요청을 재실행한 뒤 변경 대상 6개 테이블의 모든 행 해시가 동일함을 확인했다.

격리 사본과 통합 저장소에서 각각 카드 흐름·브라우저 관련 검사 52개 및 하위 검사 41개가 통과했다. 이번 작업에서는 전체 회귀를 다시 실행하지 않았다. 서버 프로세스에 수정 코드를 적용했고 감독 작업과 원본 갱신 작업은 Running이며, 장부는 127.0.0.1:8751에서 단일 프로세스로 응답한다. 내부·공개 healthz/readyz는 200, 비로그인 import는 401이다. 운영 DB를 읽는 화면 렌더러에서 여행 탭과 분류대기 합계를 검증했다. 로그인된 실제 브라우저 검증은 수행하지 못했다.

복구 사본과 실행 증거는 `.local-archive/zero-amount-20261007/post-20261007-224740/`에 로컬 보존했다. 주요 파일은 `before.sqlite`, `backup-verification.json`, `candidate-result.json`, `live-result.json`, `runtime-after.json`이다. 실패했던 첫 복구 사본 실행도 `candidate-first-attempt.sqlite`로 보존했다. 원본과 운영 DB를 삭제하지 않았고 고객 자료를 외부 에이전트에 보내지 않았다.

## 시작 상태

- 저장소는 `C:\AX\cost`, 원격은 `6Soo/cost`, 작업 branch는 `main`이다.
- 세 항목 수정 시작 시 HEAD와 origin/main은 문서 commit `9de5ccde91a1e6dea8dbe3f8163d024a1de8eb7f`로 일치했다. OTA 기능 코드 기준은 `9c4dbdac2ab9e6f5f854b07a5ac3fc2f215005ed`이며 이번에 OTA 로직을 수정하지 않았다. 최종 수정은 이 문서를 포함한 commit에 기록하므로 다음 세션에서는 실제 최신 `origin/main`을 다시 확인한다.
- 운영 배포는 금지되어 있다. 운영 DB 쓰기, 장부 commit, 재분류, source refresh, OTA 재수집과 재시작을 실행하지 않는다. 테스트의 장부 commit은 임시 합성 DB에서만 수행한다.

```powershell
Set-Location C:\AX\cost
git fetch origin
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

예상하지 않은 tracked 변경이 있으면 작업을 중단한다. 원격이 전진했다면 diff를 확인하고 최신 코드에 맞춰 판단하며 무조건 reset/rebase하지 않는다. 이 환경의 PowerShell은 `&&`를 지원하지 않아 명령을 줄바꿈으로 실행한다.

다음 사용자 untracked 파일은 수정·삭제·stage하지 않는다.

- `edit_card_flow.py`
- `pending-card-evidence-utf8.patch`
- `pending-card-evidence.patch`
- `webledger.work.operator.sqlite.checkpoint.json`

## 완료한 코드

`b60e54aa489c6eb0d232533659cb5c65950a4ed6`은 홈 장부 반영 대기의 권위 검증·batch 중복 제거·이미 기록된 거래 제외와 계산 실패 `-` 표시를 검증했다. 관련 결과는 31 passed, 23 subtests passed였으며 합성 Chromium 390×844·1440×900에서 overflow 0을 확인했다.

`9c4dbdac2ab9e6f5f854b07a5ac3fc2f215005ed`는 OTA 메타데이터 전달 하나만 수정했다. 격리 worktree에서 ledger 연결과 의미 테스트를 구현하고 통합·보완·검증했다.

- `app/ota_mail.py`: 기존 report의 exact 또는 shared-period 결과를 `ledger_metadata()`로 읽는다. 취소·충돌·근거 불확실 상태는 확정값으로 전달하지 않는다. 숙박 report에 기간 근거 digest를 보존한다.
- `app/ledger.py`, `app/__init__.py`: 선택적 `entry_metadata` callback을 preview와 commit에 연결한다. 허용 필드는 `booking_ref`, `service_period`, `ota_evidence`뿐이며 원문 금액·날짜·ID나 eligibility를 변경하지 않는다. preview 버전은 `ledger-preview-v2`다.
- `webapp/card_flow.py`: 요청별 lazy resolver가 기존 `_ota_report()`를 한 번 읽는다. state와 HTTP commit은 각각 새 resolver를 사용한다. preview의 digest가 보호한 행을 그대로 projection하며 OTA 출처와 digest는 기존 장부 `classification_basis`에 보존한다. 미리보기에도 예약번호·기간을 표시한다.
- `webapp/tests/test_card_flow.py`, `webapp/tests/test_card_flow_browser.py`: 실제 기존 matcher와 합성 fixture로 전체 전달 경로, 모호성·취소·기간 충돌, stale preview, 멱등성, rollback과 HTTP 기록을 검증한다.

새 DB table/column, matcher, evidence store, workflow 또는 UI 재설계는 추가하지 않았다. `ledger_entries`는 기존 영수증 역할을 유지하고 예약번호·기간은 `board_rows` payload에 저장한다.

## 최신 검증

다음 명령의 최종 결과는 **152 passed, 39 subtests passed**다.

```powershell
python -m pytest webapp/tests/test_card_flow.py webapp/tests/test_card_flow_browser.py tests/card_pipeline/test_pipeline.py tests/card_pipeline/test_review_holds.py tests/card_pipeline/test_booking_mail.py tests/card_pipeline/test_ota_refresh.py tests/card_pipeline/test_ota_portal.py -q
```

Chromium 390×844·1440×900에서 OTA 값이 기록 전에 표시되고 HTTP commit 후 장부의 값과 일치하며 horizontal overflow는 0이었다. 모두 임시 합성 DB를 사용했다. 운영 브라우저·현재 운영 health/ready·실제 데이터 aggregate는 이번 작업에서 검증하지 않았다.

2026-10-07 `9de5ccde91a1e6dea8dbe3f8163d024a1de8eb7f`에서 baseline 확보용 `python -m pytest -q -ra`를 완료했다. 결과는 **2216 passed, 1 failed, 3 skipped, 2382 subtests passed**, 총 **1006.11초**다. 실패는 `webapp/tests/test_ops_hosting_bind.py::TheBoardServerAcceptsAHostAndKeepsLoopback::test_serve_actually_binds_the_address_it_is_given` 한 개다. 주소 바인딩 검사는 통과했지만 557행에서 저장소 루트의 `webledger.work.sqlite`가 없어야 한다는 검사가 실패했다. 해당 파일은 실행 전부터 존재했다. `webapp/DESIGN_REVIEW.md`에 같은 실패의 clean baseline 재현 이력이 있고 해당 테스트 파일은 OTA 변경에 포함되지 않는다. 이번 세션에서 clean baseline을 다시 실행하지 않았으며 신규 regression은 발견하지 않았다. 기존 DB를 삭제하거나 관련 없는 코드를 수정하지 않았다.

건너뛴 검사는 비공개 Agoda 합성 검증용 자료 부재 두 개와 Windows에서 chmod로 읽기 전용 권한을 강제할 수 없는 검사 한 개다. 과거 회귀 숫자를 이번 결과로 재사용하지 않는다.

### 회귀 실행 원칙

2026-10-07 사용자 지시에 따라 baseline 전체 회귀는 위 실행 한 번으로 마친다. 이후 조사·수정 과정에서는 각 변경의 targeted 테스트만 실행한다. 모든 선택된 변경을 통합한 최종 revision에서 full regression을 단 한 번 실행하며 개별 수정마다 전체 회귀를 반복하지 않는다. 이번 조사와 문서 기록만으로 전체 회귀를 다시 실행하지 않는다.

### 수정 전 기준선의 후속 항목 조사

- hold 별도 표시: **DONE**. `webapp/card_flow.py`의 보류 전용 영역은 종류·이유·건수를 표시하고 일반 질문에서 보류 행을 제외한다. `app/ledger.py`는 `review_hold`로 기록을 차단한다. `tests/card_pipeline/test_review_holds.py`와 `webapp/tests/test_card_flow_browser.py`에 관련 검증이 있다.
- sidebar 지출과 staging 구분: **PARTIAL**. 현재 `webapp/ledger_design.py`의 여행 목록 금액은 지출이 아니라 `totals['income']`이며 금액에 수입이라는 설명이 없다. `webapp/ledger_store.py::tab_totals`는 장부 행과 수입 배분만 집계하므로 staging을 합산하지 않는다. 홈에서는 장부 반영 대기와 기록을 구분하지만 sidebar에는 미기록 상태 안내가 없다. 데이터 혼합보다 표시 의미의 문제이며 기존 sidebar 지출이라는 전제는 최신 화면에 맞지 않는다.
- active export의 legacy importer 의존 제거: **PARTIAL**. XLSX 생성 API와 `webapp/sheets_export.py`는 장부 행을 직접 읽지만 실제 `/export` 화면은 `webapp/ledger_board.py::export_page`에서 `CardImporter`를 생성해 과거 batch 진행 상태를 조회한다. 생성자는 schema SQL을 실행하므로 단순 dead compatibility path가 아니다. 기존 출력 HTTP·브라우저 검증은 있으나 경량 카드 처리에서 importer를 호출하지 않는 검증은 확인하지 못했다.
- ready 숫자 의미 통일: **PARTIAL**. 홈은 거래 ID로 중복을 제거하고 이미 기록된 거래를 제외하며, import 미리보기 화면도 `already_booked`를 제외한다. 반면 `app/ledger.py::preview`의 `ready`는 이미 기록된 사용자 확정 거래도 포함한다. 메모리 합성 DB에서 한 거래를 확정·기록한 뒤 API ready는 1, 같은 응답에 화면 필터를 적용한 기록 가능 건수는 0으로 재현했다. 홈 제외 검증과 기록 멱등성 검증은 있으나 기록 후 API ready와 화면 건수 일치 검증은 확인하지 못했다. 이번 조사에서는 코드를 수정하지 않았다.

## 후속 범위 판단

OTA 전달과 hold 표시는 완료된 기존 기능이다. 위 기준선 조사 후 사용자가 지정한 세 PARTIAL 항목만 최소 수정했다. 자동 전기·authority 완화·분류 개선·UI 재설계로 범위를 넓히지 않는다. 운영 반영은 사용자가 코드와 회귀 결과를 확인한 후 별도로 지시해야 한다.

### 세 PARTIAL 항목의 수정과 targeted 검증

- ready 의미 통일: **DONE**. `app/ledger.py::recordable_rows`가 blocked·already_booked를 제외한 고유 transaction을 반환하며 API ready와 홈 집계에 재사용된다. 기존 SQL이 한 batch 내 동일 transaction을 한 번만 읽고 홈은 여러 batch의 ID를 다시 중복 제거한다. 기록 전후·여러 source의 공유 transaction·blocked 제외를 확인했다. 실제 HTTP와 Chromium에서 API ready와 화면 기록 가능 행 수가 일치한다. eligibility·digest·OTA·hold·분류 규칙은 수정하지 않았다.
- export runtime 의존 제거: **DONE**. `export_page`는 `CardImporter`를 생성하지 않고 기존 batch status를 SELECT로 읽는다. 함께 호출되는 `get_job`·`list_jobs`도 스키마 SQL을 실행하지 않도록 수정했다. 테이블이 없으면 빈 결과, 과거 output_path 열이 없으면 null을 반환하며 DB는 변경하지 않는다. importer·schema·XLSX 형식·출력 기록 경로는 유지한다. 생성자 spy·SQL trace·schema 비교와 기존 출력 검증으로 확인했다.
- sidebar 의미 명확화: **DONE**. 기존 수입 금액 앞에 `수입`을 붙이고 장부에 기록된 수입 합계이며 미기록 거래를 포함하지 않는다고 안내한다. 소유자에게만 `장부 반영 대기 확인` 링크를 제공해 기존 카드 검토로 연결한다. 새 건수나 추정 금액은 표시하지 않는다. 집계·색상·배치는 유지했다. Chromium 390px·1440px에서 가로 넘침 0과 여행 이동을 확인했다.

targeted 결과는 ready 묶음 86 passed·37 subtests passed, 기존 export 묶음 80 passed·5 subtests passed, sidebar 화면 묶음 22 passed·2 subtests passed다. 추가 읽기 전용 job 두 검사와 sidebar 한 검사 묶음은 3 passed·2 subtests passed, 새 ready HTTP 브라우저 검사는 1 passed다. 개발 중 새 브라우저 테스트의 준비 단계에 빠진 validator는 기존 validator를 전달해 해결했다.

통합 상태의 최종 전체 회귀는 실행 중이며 종료 후 결과를 기록한다. 소스·테스트는 실행 전에 통합 검토하고 고정했다. 실행 로그는 `.local-archive/partial-fixes-20261007/full-regression.log`에 로컬 보존한다.

사용자 원본·비밀값은 외부로 전송하지 않는다. 같은 파일·DB의 작성자는 하나로 유지한다. 문서 갱신 후에도 운영 변경 금지는 유지한다. Git stage는 관련 파일을 명시하며 `git add .`를 사용하지 않는다.
