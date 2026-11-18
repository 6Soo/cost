# 소유자 결정 대기 7건 — 사실과 선택지 (2026-11-19)

이 문서는 **결정을 대신하지 않는다.** 소유자가 고를 수 있도록 (1) 지금 실제로 어떻게 동작하는지, (2) 그 동작을 고정하는 시험이 있는지, (3) 각 선택의 결과와 되돌리기 난이도, (4) 결정이 없을 때 무엇이 막히는지를 적는다. 파일·행 번호와 측정값은 이 작업 폴더(`analysis/policy-decisions-20261119`, base `3d8e8791`)에서 직접 확인한 값이다. 확인하지 못한 것은 "미확인"으로 적었다. 원자료는 `C:/AX/cost/.local-archive/policy-decisions-20261119/`(`notes.md`, `kind_filter_probe.json`, `period_parity_probe.json`, `filters_stage_probe.py`)에 있다.

## 0. 먼저 인계 전제 두 개가 낡았다

| 인계 문서의 전제 | 실제 |
| --- | --- |
| "main `3d8e8791`을 `90ea51ff` 위로 배포하는 것이 결정 대기 1번" | **이미 배포됐다.** `origin/main`의 `docs/operations.md` 첫 절 "2026-11-19 05:20 창 — 3d8e8791 운영 배포"(Previous `90ea51ff`). `D:/WebLedgerHost/releases/deploy-evidence-3d8e8791….json`도 실재. 내가 읽기 전용으로 확인: 백엔드는 `releases\3d8e8791…\launch_web_ledger.py --port 8752`, 8751 리스너 없음, `/healthz`·`/readyz` 200. 그 뒤 main은 문서 5파일만 더 진행(`374a6c88`). |
| "M6 `ledger` 테이블 생성이 운영 스키마 결정 대기" | **표는 이미 있다.** 운영 `board.sqlite`에 `ledger` 표 3,378행(읽기 전용 조회). DDL 41컬럼이 PR #1013의 `app/db.py` `LEDGER_SCHEMA_SQL`과 이름·순서 동일. 다만 **지금 배포된 코드는 이 표를 읽지도 쓰지도 않는다**(`FROM ledger`/`INSERT INTO ledger` SQL 0곳). |

## 1. 한눈에 보는 표

| # | 항목 | 현재 동작 (레거시 ↔ React) | 고정 시험 | 되돌리기 | 없으면 막히는 것 |
| --- | --- | --- | --- | --- | --- |
| 1 | 운영 배포 | **완료**(`90ea51ff`→`3d8e8791`, 2026-11-19 05:20) | 배포 도구 게이트(`tools/deploy_verified_release.ps1:15-97`) | 되돌림 = 이전 릴리스 재전환(도구가 실패 시 자동 수행, `:87-95`) | 없음 |
| 2 | M6 `ledger` 표 | 표 3,378행 존재, **낡음 661행**(`board_rows.revision`이 1 높음). 코드는 미사용 | PR #1013의 `tests/card_pipeline/test_ledger_{schema,parity,store_sync,correction_sync}.py`·`test_booked_predicate_pair.py`(브랜치에만) | 이관 `--apply`는 추가만 함 → `DROP TABLE ledger`로 원복 가능(PR 본문). 낡은 표를 정본으로 전환한 뒤엔 백업 복원 | #1013 병합 여부 |
| 3 | 기간 표시 (`label \|\| period`) | **2,494/3,378행 글자가 다름**: 2,362행 레거시 빈칸↔React "기간 근거 없음", 131행 레거시 "취소·환불"↔React "이용일 미확인", 1행 React만 원문 ISO | `frontend/src/features/ledger/index.test.tsx:91-106`(서버 값 그대로), `webapp/tests/test_ledger_parity_spec_11_2_1.py`(기간 칸 미검사) | 코드 1줄(`index.tsx:64`) → **되돌리기 가장 쉬움** | M4 수락 기준 "두 경로 같은 기간 표시" |
| 4 | KPI 문구 | 레거시 **`—`**(`ledger_design.py:258-262`) ↔ React **`미확인`**(`plush_projection.py:81,84`) | 양쪽 다 고정: `incomeSourceTab.test.tsx:159-193`, `test_ledger_parity_spec_11_2_1.py:126-136` | 문구 1곳(서버 또는 화면) 변경, **쉬움** | 없음. 다만 **오늘 모든 여행의 수입·차액이 갈려 보인다**(운영 수입행 0건·여행 72개) |
| 5 | 기본 정렬 | 레거시 **날짜 오름차순**(`ledger_design.py:1779-1782`·`:2031`) ↔ React **최신순**(`index.tsx:178`, `plush_api.py:315`) | 레거시만: `test_ledger_display_updates.py:42-49` | 기본값 1곳, **쉬움** | 없음 |
| 6 | PR #993 | main 대비 **48파일 +6,649/−59**, **충돌 24경로**, base 이후 main이 만든 34파일을 조용히 되돌림 | PR 본문상 24+75건 등, 최종 영향 검사 미완(본문 자체가 "진행 중") | 통째 병합 금지 — 항목별 분리만 안전 | M3/M4/M5 잔여 보완 |
| 7 | `#kind` 즉시 적용 | 레거시 툴바 셀렉트에 onchange 없음(`ledger_design.py:295-298`), 버튼(`#q-go` `:299`)만 적용. `onchange` 있는 `_bar_html`(`:551-571`)은 **호출자 0** | 원래 시험이 있었으나 **알려진 실패 등록**(`known-test-failures.txt:40`) → 내가 단독 실행 **103 failed / 1 passed**, `_filters` 스테이지 **NO NAVIGATION** 재현 | onchange 1개 추가, **쉬움**(단 검색 도구 존치가 전제) | 없음(불편만) |

## 2. 항목별 상세

### 2.1 운영 배포 — **결정 없음, 이미 완료**

- 근거: `origin/main` `docs/operations.md` 첫 절, `releases/deploy-evidence-3d8e8791….json`(`recorded_at 2026-11-18T20:22:27Z`), `continuous-switch-3d8e8791….json`(`status PASS`, `drained`, `core_writers VERIFIED`).
- 보호 14표 전후 불변·`financial_apply=NOT_RUN`(배포 기록).
- 배포 이후 `origin/main`은 `374a6c88`까지 왔고 그 차이는 `docs/operations.md`·`docs/playbooks/m3-exit-rehearsal.md`·`docs/policy/{item,trip}.md` **문서 5파일**뿐이다(`git diff --stat 3d8e8791 origin/main`).
- 소유자 결정이 필요한 것은 "다음 배포"(예: #1013·#1015 등)이고, 그 `-PreviousSha`는 `3d8e8791`이다.

### 2.2 M6 `ledger` 표 — 표는 있고 코드는 안 쓴다

**측정(운영 사본 읽기 전용)**

| 사실 | 값 |
| --- | --- |
| `ledger` 행 | 3,378 (수기 4행은 `transaction_id` NULL) |
| `ledger_entries` ↔ `ledger` ↔ `board_rows` 카드행 | 3,374 / 3,374 / 3,374, **1:1 완전 일치**(서로 빠진 것 0) |
| 항목·금액·탭 값 불일치 | **0행** |
| revision 불일치 | **661행**(`board_rows.revision` = `payload.revision` + 정확히 1), 그 661행의 `ledger.revision`은 `payload.revision`과 같다 |
| 마지막 `ledger` 갱신 | `created_at` 최댓값 2026-11-17T13:04Z (= 이관 시점) |

**코드 상태**

- 배포 코드(`90ea51ff`·`3d8e8791`·`origin/main`)에 `FROM ledger`/`INSERT INTO ledger` **0곳**.
- `ledger_is_authoritative`·`booked_sql`·`sync_ledger_from_record`·`write_ledger_row`는 **PR #1013 브랜치(`fix/m6-file-placement-test-20261119`)에만** 있다.
- 그래서 표는 **현재 낡은 사본**이다. 배포 게이트의 보호 14표(`tools/verify_protected_release_state.py:13-19`)에 `ledger`가 없어 **게이트가 이 낡음을 감지하지 못한다**.

**#1013이 하는 일과 위험**

- #1013은 기장 판정을 `ledger`까지 읽는 **합집합**으로 바꾸고(`booked_sql`, 브랜치 `webapp/ledger_store_records.py`), 쓰기 경로 16곳 + 기장·교정 5경로에 이중 쓰기를 붙인다.
- 즉 병합 후에는 표가 **정본의 일부**가 된다. 지금 낡은 661행은 revision만 1 낮고 값은 같으므로, 병합 **전에** 이관 도구를 다시 돌려 맞추거나(멱등), 병합 직후 첫 쓰기가 덮게 두는 두 가지가 가능하다. **어느 쪽이 안전한지는 합성 실행 없이 단정하지 않는다(미확인).**
- 되돌리기: 이관은 추가만 하고 옛 두 표를 지우지 않으므로 `DROP TABLE ledger`로 즉시 원상(PR 본문 "롤백" 절). 정본 전환 뒤에는 신선 백업 복원.

### 2.3 기간 표시 — `label || period`가 만드는 실제 차이

- 레거시 칸(`ledger_design.py:1053`)은 **숙박비·항공료·렌터카**만 라벨을 만들고 나머지는 **빈 문자열**.
- React(`index.tsx:64`)는 `label`이 비면 `period`(원문 ISO)로 대체하고, 둘 다 없으면 `:74`에서 **"기간 근거 없음"**.
- 실측 차이(운영 사본):

| 차이 | 행수 | 예 |
| --- | --- | --- |
| 레거시 빈칸 ↔ React "기간 근거 없음" | 2,362 | 현지경비 817, 분기 기타비용 526, 식비 469, 교통비 130 |
| 레거시 "취소·환불" ↔ React "이용일 미확인" | 131 | 숙박 116, 항공 13, 렌터카 2 (모두 음수) |
| 레거시 빈칸 ↔ React 원문 ISO | 1 | 분기 기타비용 `2026-06-20~2026-06-25` |

- **`label ?? period` 제안의 효과**: 서버는 `period_label`을 빈 문자열로도 항상 보내므로(`plush_api.py:358-362`, `plush_projection.py:139-142`), `??`로 바꾸면 **1행만** 바뀐다. 2,362행은 label도 period도 비어 여전히 "기간 근거 없음"이다. 즉 **핵심은 `||`/`??`가 아니라 "빈칸을 무엇이라 부를지"**다.
- 고정 시험: `index.test.tsx:91-106`이 "서버 값 그대로, 화면이 다시 만들지 않음"을 고정. 라벨 없는 행이 원문을 그대로 찍는 것도 `:98-100`이 확인한다. 이 시험은 **코드만 보면 `label ?? period`로 바꿔도 깨지지 않는다**(실행 확인은 안 했다 — 코드 수정 금지).

### 2.4 KPI 문구 — `—` vs `미확인`

- 레거시 `ledger_design.py:258-262`: 값 `—`, 각주 "장부 확인 필요"/"수입을 확인하면 계산됩니다".
- React: 서버 `plush_projection.py:81,84`가 `"미확인"`, 화면 `amount-format.ts`가 비숫자를 글자 그대로 통과시켜 단위 없이 "미확인".
- 양쪽 다 시험이 있다: `incomeSourceTab.test.tsx:159-193`(React 단어·단위 금지), `test_ledger_parity_spec_11_2_1.py:126-136`·`test_m4_income_source_parity.py:28`(레거시 `—`).
- 운영 실태: `board_rows` 수입행 **0건**, 활성 `income_allocations` **0건**, 여행 **72개** → **오늘 72개 여행 전부가 이 차이를 보인다**.

### 2.5 기본 정렬 방향

- 레거시 `ledger_design.py:1779-1782`(지출)·`:2031`(수입) 모두 **오름차순**, 같은 날은 항목 순서(`_expense_category_rank`).
- React `index.tsx:178`·서버 `plush_api.py:315` 기본 **`date_desc`(최신순)**.
- 고정: 레거시만 `test_ledger_display_updates.py:42-49`. React 기본값 시험 없음.
- 둘 다 URL로 상태를 보존하므로(`urlState.ts:45-78`) 사용자가 한 번 고르면 유지된다.

### 2.6 PR #993 — 숫자가 인계와 다르고, 병합하면 최신 작업을 되감는다

| 측정 | 값 |
| --- | --- |
| 3점 비교(main...PR) | **48파일 +6,649/−59**(PR 본문과 일치) |
| 2점 비교(main..PR) | 121파일 +3,526/−12,096 → "삭제 34" |
| 그 34개의 정체 | **전부 base(`259bc187`) 이후 main이 새로 만든 파일** (3점 비교의 진짜 삭제 0) |
| `git merge-tree` 충돌 | **24경로**(add/add 8, content 16) |
| PR 내용의 상당수 | **이미 main에 있음**(`jobs/mod.rs`, `m5_runtime.py`, `m5_p2_adapter.py`, `m5_backup.py`, `p2.rs`) |

브랜치를 그대로 병합하면 main의 최신 파일(`webapp/ledger_periods.py`, `frontend/src/components/amount-format.test.ts` 등 34개)이 조용히 사라지고, `tools/m5_backup.py`가 336줄 줄어드는 등 **최근 수정을 되감는다**. 통째 병합은 금지 전제가 맞고, 이유는 "충돌 15"보다 **base가 낡아 생긴 역방향 삭제**다.

### 2.7 `#kind` 즉시 적용 — 재현 완료

- 화면 툴바: `ledger_design.py:283-305`. `#kind` 셀렉트(`:295-298`)에 **onchange 없음**, 적용은 `#q-go`(`:299`).
- `onchange="this.form.submit()"` 있는 셀렉트는 `:551-571 _bar_html`인데 **호출자 0곳**(저장소 전체 grep).
- 원인: `8cd0e58b`(2026-11-10)이 `_bar_html` → `_expense_toolbar_html`로 바꾸면서 onchange를 옮기지 않았다(`git log -S` 확인).
- 재현(합성 저장소 + 실제 Chromium, `kind_filter_probe.json`):
  - `#kind`만 "지출"로 → **이동 없음, 6행 그대로**
  - `#q-go` 클릭 → **이동, 3행(`kind=ex`)**
- 시험: `test_ledger_breakpoints.py:240-256`이 이동을 기대하지만 `known-test-failures.txt:40`에 등록돼 늘 실패한다. 단독 실행 **103 failed / 1 passed**, `_filters` 스테이지 **NO NAVIGATION** 재현.
- 도달 범위: 운영 `/board`는 React를 먼저 제공(`launch_web_ledger.py:258` `WEBLEDGER_PRIMARY_UI=1`, `plush_ui.py:45-55`). 레거시 툴바는 **React 서랍의 "기존 화면에서 교정"(`legacy=1`) 경로**에서 보인다. React 장부 탭은 **즉시** 적용(`index.tsx:369`).
- **미확인**: 환불 탭 `#refund-kind`는 `refund_tab_ui.py:38-47`에서 `in`→빈 목록, `ex`→여과 없음으로 비대칭. 의도인지 확인 못 했다.

## 3. 감독이 소유자에게 물을 질문 (항목마다 1개, 선택지 2~3개)

**Q1. 운영 배포** — "3d8e8791은 2026-11-19 05:20에 이미 배포됐습니다. 다음 배포를 무엇으로 잡을까요?"
- A. 지금은 배포하지 않고 #1013·#1015 검수·병합 뒤 한 번에 (권장: 현재 main 추가분은 문서뿐)
- B. 문서 5파일만 먼저 배포
- C. 특정 PR만 먼저 배포 (번호 지정)

**Q2. M6 `ledger` 표** — "`ledger` 표는 이미 3,378행으로 있고 값은 맞지만 revision 661행이 낡았고, 지금 코드는 이 표를 쓰지 않습니다. 이 표를 정본으로 전환할까요?"
- A. #1013 병합 전에 이관 도구를 다시 돌려 661행을 맞춘 뒤 병합 (권장: 병합 후 표가 정본이 됨)
- B. #1013을 병합하고 첫 쓰기가 덮게 둔다 (이관 재실행 안 함)
- C. 지금은 전환하지 않고 표만 남겨 둔다 (코드 미사용 유지)

**Q3. 기간 표시** — "지금 React는 보통 지출의 이용기간 칸에 '기간 근거 없음'을 찍고 레거시는 빈칸입니다(2,362행). 어느 쪽을 기준으로 할까요?"
- A. 레거시처럼 **빈칸**으로 (React에서 안내 문구 제거) — 화면 차이 0이 되지만 "모름"이 덜 드러난다
- B. React처럼 **'기간 근거 없음'** 문구로 (레거시도 문구 추가)
- C. 숙박·항공·렌터카만 표시하고 나머지는 **양쪽 다 빈칸**, 취소·환불만 "취소·환불"

**Q4. KPI 문구** — "수입을 모를 때 레거시는 `—`, React는 `미확인`입니다. 하나로 통일할까요?"
- A. `미확인`으로 통일 (뜻이 분명)
- B. `—`로 통일 (기존 레거시 화면과 동일)
- C. 두 화면 각자 유지 (지금 상태 그대로, 차이를 감수)

**Q5. 기본 정렬** — "레거시는 날짜 오름차순, React는 최신순입니다. 기본을 무엇으로 할까요?"
- A. React 최신순 유지 (최근 지출을 먼저 본다)
- B. 레거시처럼 오래된순 (기존 습관 유지, 두 경로 동일)

**Q6. PR #993** — "이 브랜치는 base가 낡아 병합하면 main의 최신 34파일이 사라집니다. 어떻게 할까요?"
- A. 닫고, 남은 가치만 PR #1013·#1015 등으로 개별 분리 (권장)
- B. 최신 main 위로 rebase해 다시 검수한 뒤 병합
- C. 지금은 닫지 않고 보류

**Q7. `#kind` 즉시 적용** — "레거시 장부 툴바에서 구분을 바꿔도 '조회'를 눌러야만 적용됩니다. 고칠까요?"
- A. 고친다 (`#kind`에 onchange 1개 추가, `#q-go`는 유지)
- B. 고치지 않는다 (검색 도구를 곧 없앨 예정이면 그때 함께)
- C. 검색 도구 자체를 없애고 React 탭만 쓴다 (선행 결정 필요)

## 4. 확인한 것 / 확인하지 못한 것

**확인함(근거 있음)**: 배포 완료(문서·증거 파일·실제 프로세스), `ledger` 표 존재·행수·불일치 0·낡은 661행, 배포 코드의 `ledger` 미사용, 기간 칸 차이 2,494행(사본 전수 대조), KPI 문구 양쪽, 정렬 양쪽, #993 파일·충돌·역방향 삭제 34, `#kind` 미적용(실제 Chromium 재현), 그 결함 시험의 알려진 실패 등록.

**확인하지 못함**: 제안 변경(코드 수정 금지)을 적용한 뒤의 실제 결과, 로그인된 React 화면의 눈으로 본 모습, #1013 병합이 낡은 표로 판정을 바꾸는 실제 영향(합성 실행 안 함), 환불 탭 `kind` 비대칭의 의도, AGY 검수(`agy.exe`가 이 PC에 없음 — 사실 대조는 내가 `file:line` 재확인으로 대신했다).
