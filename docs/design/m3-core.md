# M3 Rust 새 코어 — 착수용 설계안

> **상태:** 착수(2026-11-14). 소유자가 §9의 D-1·D-2·D-4·D-7·D-9를 결정했고 U1·U4가 이미 착수했다. D-7은 권장안과 달리 **연결 단계(환불 짝·OTA↔카드)도 M3에서 Rust로 재작성**하기로 정해져 §1·§3.1·§7·§8에 반영했다. **2026-11-14 축소 개정**(과설계 검토 권장안 채택, §9 D-5·D-11~D-13): 18단위 → 14단위, 전환 두 번(판정 먼저, 연결 나중), 전환 조건 6 → 3개, 작업공간 크레이트 2개, 수락 조건은 "운영에 실재하는 입력에서 최종 결과가 같음", 전환 전 Rust PR 검수 1회. Python 판정 규칙 개선은 하루 한 묶음으로 계속한다. D-6(승인자)·D-8·D-10은 미결, D-3은 사용자 방침으로 사실상 결정됨(§9).
> **근거:** [통합 명세](../SPEC.md) §10 M3(`SPEC.md:318`)·§11.1(`SPEC.md:328-335`), 계획 원문 `C:\Users\kkokk\.claude\plans\unified-chasing-muffin.md`의 D8~D11 보완 조건(`:105-130`, `:94-103`). 판정 규칙은 [판정 규칙집](../DECISION_POLICY.md)이 정본이며 이 문서는 규칙을 새로 정하지 않는다.
> **기준 SHA:** `origin/main` `0bdce8ca`. 이 문서의 `파일:줄`은 이 SHA 기준이다. 단 2026-11-14 결정 반영 때 새로 단 연결 단계 근거(§1.1 S8, §3.1 연결 입력, §7 옛 U15~U18(현 U12~U14), §8 추가 행)는 `origin/main` `8dcc0c06` 기준이다. 축소 개정에서 새로 단 근거는 `origin/main` `b8520f48`과 열린 PR #873·#874·#876·#877의 2026-11-14 상태 기준이다.

## 0. 한 줄 요약

M3는 **판정을 한 테이블(`decisions`)에 모으는 Rust 코어를 현 Python 옆에 그림자로 세우고**, 같은 입력에서 현 Python P1과 결과가 같거나 차이가 모두 설명될 때만 P1 생산자를 Rust로 바꾸는 단계다. 연결(환불 짝·OTA↔카드 M:N 대사)도 Rust로 재작성한다(소유자 결정 D-7, 2026-11-14). 전환은 두 번이다: **1차는 판정**(연결은 Python 어댑터 출력을 그대로 입력), **2차는 연결**(§3.3). 수집·추출(메일·포털에서 OTA 결제 사건을 만드는 일 포함)과 P2 실행은 Python이 계속 맡고, 작업 큐·P2 실행기 재작성·화면·클라우드·Rust 추출기는 하지 않는다.

## 1. 범위와 비범위

### 1.1 M3에서 하는 것

| # | 내용 | 근거 |
| --- | --- | --- |
| S1 | 판정 모델: 판정 1건의 Rust 타입, 판정 주체 우선순위, 금융 불변식의 타입 강제 | `SPEC.md:112-131`, `SPEC.md:330` |
| S2 | 코어 저장소 `core.sqlite`: decisions·decision_history·overrides·jobs·agent_runs 등. 운영 `board.sqlite`는 읽기 전용으로 읽는다 | `SPEC.md:145`, `SPEC.md:332` |
| S3 | P1 규칙 엔진: 데이터형 규칙 표 + 현 `app/classify.py`·`app/rules.py`·`app/automatic_classification.py` 이관 | `SPEC.md:158`, 계획 `:110` |
| S4 | 파이프라인 중 **연결·귀속·게시** 단계의 Rust 구현. 수집·추출은 Python 어댑터(하위 프로세스) 호출 | `SPEC.md:318`, `SPEC.md:333`, D-7 |
| S8 | **연결 단계 재작성**(D-7). (가) 환불 짝: 원승인번호 1:N 연결·외화 금액 연결·동액 추론 연결과 전역 유일성·점유(`app/partial_refund.py:66-81`, `:146-381`, 설정 `config/refund-pairing.json`), 환불 묶음 판정(상속·보류·초과 환불·파일 간 부분환불 확장·PROC-072 완료 기간 제외, `app/ledger.py:367-465`, `app/partial_refund.py:114-133`, 묶음 미완 거부 `app/ledger.py:557-567`). (나) OTA↔카드: 후보 탐색·쌍 검사(`app/ota_payments.py:1002-1670`), M:N 배정·반복 금액 묶음·고정 그룹·전역 점유·옛 정확 연결 고정(`app/ota_payments.py:1671-2441`), 결제일 없는 아고다 1:1 추론(`app/ota_inference.py:43`). 규칙은 `docs/policy/refund.md`의 RFND-*(특히 RFND-004·RFND-018·RFND-025·RFND-029 개정, `docs/policy/refund.md:33`, `:156`, `:218`, `:251-262`)와 `docs/policy/link.md`의 LINK-003·LINK-028·LINK-032·LINK-038(`docs/policy/link.md:32`, `:289`, `:325`, `:384`) | `SPEC.md:157`, `SPEC.md:391`, D-7 |
| S6 | 병행(그림자) 실행과 차이 보고, 골든 회귀, 평가 사례 재실행 | `SPEC.md:333-335` |
| S7 | 운영 전환 도구(투영 쓰기)와 전환·되돌림 절차서. 전환은 판정(1차)과 연결(2차) 두 번. **전환 실행 자체는 별도 승인** | `SPEC.md:383`, D-11 |

S5(작업 큐와 P2 실행기)는 2026-11-14 축소 개정(D-11)으로 M5로 옮겼다(§1.2, §5).

### 1.2 M3에서 하지 않는 것

| 하지 않는 것 | 언제·누가 | 이유 |
| --- | --- | --- |
| JSON API, React 화면, Claude Design | M4 | `SPEC.md:319`, §11.2 |
| 클라우드 서버·보조 노드 분리, 원격 작업 가져오기 | M5 | `SPEC.md:320` |
| 작업 큐·임대·일일 예산(옛 U12), P2 실행기 재작성(옛 U13) | M5 착수 때 | D-11(2026-11-14). 임대 구조는 M5(클라우드)를 위한 선행 설계이고, P2는 현 Python 경로(`tools/p2_batch/`)를 그대로 쓴다(§5) |
| Rust 추출기, Python 폐기 | M6 | `SPEC.md:321`. M3는 추출기 **기준 출력 생성**까지만 한다(§3.4) |
| OTA 결제 사건 생성(메일·포털·예약 자료 파싱과 사건 병합, `app/ota_payments.py:57-1000`의 `build_ota_payment_events` `:915` 등) | M6(추출기와 함께) | 추출이다. M3에서는 Python 어댑터가 사건을 `facts`로 넘기고, Rust는 그 사건과 카드 원행 사이의 대사만 한다(S8) |
| 연결 결과의 저장소·화면 이전(`ota_review_links`·`ota_review_group_pins` 등 `app/ota_review.py:172-197`, 환불 탭 화면) | M4 이후 | 2차 전환 전까지 Rust 연결은 `core.sqlite`의 `links`에만 쓰고, 현 저장소·화면은 Python 연결 결과를 계속 읽는다 |
| 새 장부 행 만들기(환불 묶음 기록의 `ledger_entries` 삽입) | 현 Python 기록 경로 유지 | §3.1의 `ledger_entries` "새 행을 만들지 않는다"와 같은 범위다. D-7은 짝 맞추기와 연결의 재작성이지 기록 경로 재작성이 아니라고 해석했다(가정). Rust 환불 묶음 판정(U12)은 묶음과 보류 사유를 내고, 기록 자체는 현 `app/ledger.py` 경로가 한다. 2차 전환 뒤 묶음 게시(`publish_group`, U14)는 묶음 단위 원자성만 보장한다 |
| Google 장부 쓰기 | 영구 금지 | `SPEC.md:393`. 코어에 Google 쓰기 의존성을 두지 않는다 |
| 새 공급자 파서, 증상별 패치 | 동결 | `SPEC.md:363-367` |
| 화면(`webapp/`) 변경 | M4 | 전환 뒤에도 현 화면은 `transactions` 열을 그대로 읽는다(§3.3) |
| 무료 모델 P2 | 선택 단계 | `SPEC.md:353-359` |
| 운영 예약 작업 등록·배포 | 전환 승인 뒤 | `SPEC.md:381` |
| Board 내장 P2 런타임 제거 | M2 후속 작업 | `docs/session_handoff.md:6`. M3와 무관하게 진행 |

## 2. 판정 모델

### 2.1 판정 1건의 구조

`SPEC.md:114-123`의 여덟 항목을 그대로 타입으로 옮긴다. 아래는 계약이며 구현자는 이름만 바꿀 수 있다.

```rust
pub struct Decision {
    pub subject: Subject,              // 무엇에 대한 판정인가
    pub attribution: Attribution,      // 어디에 귀속되는가
    pub item: Item,                    // 비용 항목
    pub description: String,           // 장부 설명(현 transactions.description)
    pub service_period: ServicePeriod, // 이용기간
    pub evidence: Vec<EvidenceRef>,    // 연결된 근거
    pub actor: Actor,                  // 판정 주체
    pub basis: Basis,                  // 근거 문장(비어 있을 수 없음)
    pub uncertainty: Vec<Uncertainty>, // 확인하지 못한 것
    pub policy_refs: Vec<PolicyRef>,   // 적용한 규칙집 ID (DECISION_POLICY.md:16)
}

pub enum Subject {
    CardTxn { transaction_id: TxnId, source_hash: SourceHash, revision: u32 },
    Receipt { receipt_id: ReceiptId },          // M3는 타입만, 생산은 M4 이후
    CashUse { use_id: CashUseId },              // ITEM-019, SPEC.md:440
}

pub enum Attribution {
    Trip(TripId),                       // Google 시트 탭에만 존재하는 여행(SPEC.md:63)
    QuarterOther { year: u16, quarter: Quarter }, // 결제일 기준 분기 기타비용
    RefundPair(RefundGroupId),          // 전액 환불 쌍(SPEC.md:117)
}

pub enum ServicePeriod {
    Known { starts_on: Date, ends_on: Date },   // ends_on >= starts_on 생성자에서 검사
    Unknown { reason: UnknownPeriodReason },    // "모르면 비워 두고 그 사실을 적는다"(SPEC.md:119)
}

pub enum Actor {
    Manual { event: ManualEventRef },                       // 수동 교정
    P1Exact { rule_id: RuleId, rule_version: u32 },         // 예약번호·원승인번호 등 정확 근거
    AiReview { run_id: RunId, model: ModelName },           // 분기 검수 교정
    P2 { run_id: RunId, model: ModelName },
    P1Inferred { rule_id: RuleId, rule_version: u32, confidence: Confidence },
}
```

- `Item`은 닫힌 enum이 아니라 **허용 목록으로만 만들 수 있는 newtype**이다. 허용 목록은 데이터(현 운영 장부 실사용 항목, `tools/p2_batch/scope.py:48-50`)에서 읽는다. 항목이 늘어도 코드 변경이 없다(계획 `:110`).
- `Basis`는 비어 있으면 생성되지 않는다. P2·AI 검수 근거의 길이·개인 식별값 검사(`tools/p2_batch/layer1.py:164-167`)는 생성자에 둔다.
- 장부 표기와의 대응: `Attribution::Trip(t)` ↔ `display_tab_id=t, trip_id=t`, `QuarterOther` ↔ `display_tab_id='quarter:Y:Q', trip_id=''`(`app/automatic_classification.py:232-236`, `app/classification_correction.py:146-147`), `RefundPair` ↔ `display_tab_id='refunds'`(`app/automatic_classification.py:302-305`).

### 2.2 판정 상태 타입 — "대기" 상태가 없다

규칙집은 확인함·질문 대기·보류·미분류 상태를 금지한다(`DECISION_POLICY.md:33`). 그래서 거래 하나의 상태는 셋 중 하나이고, **"판정 대기" 변형을 두지 않는다**.

```rust
pub enum Judgement {
    Decided(Decision),                    // 모든 정상 거래(PROC-001, DECISION_POLICY.md:32)
    Protected(ProtectionReason),          // 정상 거래가 아님: 날짜·금액 파손, 중복, 원본 충돌(PROC-005, DECISION_POLICY.md:37)
    Preserved(CompletedPeriod),           // PROC-072 완료 기간 자료(DECISION_POLICY.md:32, app/closed_period.py:56-66)
}
```

- 현 Python의 `needs_review`·`rule_conflict`·`inference_conflict`·`travel_location_hold`·`booking_evidence_needed`(`app/classify.py:396-460`, `app/automatic_classification.py:53-54`)는 Rust에서 **판정 상태가 아니라 P1 내부 결과**다. P1은 이 경우에도 공통 추론으로 최선 판정(`Actor::P1Inferred`)을 내고(`app/automatic_classification.py:416-429`의 분기 기타비용 종결과 같은 뜻), 별도로 `P2Hint`를 붙인다(M3에서는 그림자 차이 보고용이고 P2 대상 선정은 현 Python 경로, §5). 게시 함수는 `Decision`만 받는다.
- 이로써 "판정 없는 정상 거래 0건"(`SPEC.md:306`)이 타입으로 보장된다: 정상 거래에 대해 `Decided`가 아닌 값을 만들 경로가 없다.

### 2.3 판정 주체 우선순위

`SPEC.md:127` / `DECISION_POLICY.md:24`의 순서를 `Actor::rank()`로 두고, 덮어쓰기는 한 함수만 허용한다.

```rust
pub fn supersede(existing: &Decision, proposed: Decision) -> Result<Decision, OverrideDenied>;
```

| 기존 \ 제안 | Manual | P1Exact | AiReview | P2 | P1Inferred |
| --- | --- | --- | --- | --- | --- |
| Manual | 허용(새 수동) | 거부 | 거부 | 거부 | 거부 |
| P1Exact | 허용 | 허용(같은 규칙 재평가) | **거부 + `RaiseCause`**(`SPEC.md:130`) | 거부 | 거부 |
| AiReview | 허용 | 허용 | 허용 | 거부 | 거부 |
| P2 | 허용 | 허용 | 허용 | 허용(새 실행) | 거부 |
| P1Inferred | 허용 | 허용 | 허용 | 허용 | 허용 |

- P1이 이미 기록된 P2 판정을 조용히 덮지 않는 현 보호(`app/automatic_classification.py:487-490`, `app/classify.py:544-547`)는 이 표의 "P2 행 × P1Inferred 열 = 거부"와 같다.
- `AiReview`는 금융 보호를 덮지 못한다(`SPEC.md:130`): 금융 보호는 `Protected`이므로 애초에 `Decision`이 아니어서 `supersede` 대상이 될 수 없다.
- 이 표 25칸 전부를 나열한 표 테스트로 고정한다(§6.3). 같은 표에 대한 속성 테스트는 중복이므로 두지 않는다(D-12).

### 2.4 금융 불변식을 타입으로

| 불변식 | 근거 | 타입·모듈 강제 방법 |
| --- | --- | --- |
| 카드 원문·금액·부호·ID를 바꾸지 않는다 | `SPEC.md:389`, `app/rules.py:124-128` | `SourceTxn`은 읽기 전용 구조체(필드 비공개, getter만). `Decision`에는 금액·부호·승인번호 필드가 **없다**. 저장 계층의 `UPDATE` 문은 정해진 열 목록 상수에서만 만들고, 그 목록에 원천 열이 없음을 테스트로 고정한다 |
| 금액 해석 실패를 0원으로 쓰지 않는다 | `SPEC.md:389` | `Amount = Readable(KrwAmount(i64)) \| Unreadable(ParseError)`. `Unreadable`은 `Judgement::Protected`로만 간다. `Default` 구현 금지 |
| 수동 교정이 항상 우선 | `SPEC.md:390` | §2.3 `supersede`. 수동 신호(§3.1의 overrides) 판별은 한 함수에만 둔다 |
| 중복·환불 짝·초과 환불·원본 충돌 보호를 풀지 않는다 | `SPEC.md:391` | `RefundGroup`은 `cost-core`의 `links::refund` 모듈(환불 묶음 판정, U12) 밖에서 생성 불가(필드 비공개, 생성 함수는 같은 모듈). 추론 연결은 정확 연결과 다른 타입이라 묶음 확장 입력이 될 수 없다(RFND-044). 게시는 `publish_group(RefundGroup, Vec<Decision>)`로 **묶음 전체를 한 트랜잭션**에 쓰거나 아무것도 쓰지 않는다 |
| P2는 금액·부호·원승인 관계·환불 짝·새 장부 기록을 쓰지 않는다 | `SPEC.md:162`, `SPEC.md:196` | `P2Proposal`은 귀속·항목·이용기간·근거·불확실성만 가진다. `P2Proposal → Decision` 변환은 `Actor::P2`만 만들 수 있고 `Attribution::RefundPair`를 거부한다 |
| 열린 분기만 자동 교정 | `SPEC.md:203-204`, `app/classification_correction.py:18-37` | `OpenScope` 토큰은 열린 분기·열린 여행 판별 함수만 만든다. P2·AI 검수 교정 적용 함수는 이 토큰을 인자로 요구한다 |
| 여행을 만들어내지 않는다 | `SPEC.md:63` | `TripId`는 Google 탭 스냅숏(`trip_tabs`)에서 읽은 값으로만 생성된다. 문자열에서 바로 만드는 생성자 없음 |
| 규칙이 여행을 자동 배정하지 않는다(가맹점 규칙) | `app/rules.py:245-246` | 가맹점 항목 규칙의 효과 타입에 귀속 필드가 없다 |

**봉인의 수준(D-12, 2026-11-14).** 봉인 타입 `RefundGroup`·`OpenScope`·`TripId`·`Subject`는 필드를 비공개로 두고 생성 함수를 `pub(crate)` 이하로 둔다. 작업공간을 `cost-core` 라이브러리 하나로 합쳤으므로(§6.1) **크레이트 밖(`costcore` 실행 파일·통합 테스트)에서의 생성은 컴파일러가 막는다.** 이것을 `compile_fail` 문서 테스트 4개(타입마다 외부 생성 1개)로 고정한다. 크레이트 안에서는 타입과 생성 함수를 같은 모듈에 두는 것을 원칙으로 한다(`RefundGroup` → `links::refund`, `OpenScope` → `dates`). 크레이트 사이 발급 기능 플래그(`refund-issuer`·`scope-issuer`)와 소스 문자열 허용 목록 스캔 테스트는 두지 않는다 — Rust 기능 플래그는 작업공간 전체에서 합쳐져 보호가 되지 않았고(#873 1회차 지적), 문자열 스캔은 우회가 재현됐다. "`Default`가 없다"·"`From`이 없다"처럼 없는 구현을 확인하는 `compile_fail` 시험도 두지 않는다.

### 2.7 이용기간은 판정과 함께 저장한다 — 렌더 시점 계산 폐지 (U9a)

**원칙(소유자 지적 2026-11-14).** 한 번 분류된 비용은 판정 함수가 바뀌기 전에는 다시 분류할 필요가 없다. 분류와 이용일을 따로 계산해 화면이 볼 때마다 이용기간을 근거로 다시 만드는 것은 설계 결함이다(현 Python: 분류는 기록 시점에 저장, 이용기간은 `webapp/ledger_design.py` 렌더마다 `ledger_stay_evidence.period_for`로 재계산, OTA 대조 60초 스냅숏). Rust에서는 이용기간이 `Decision.service_period`의 일부이며, **화면·붙여넣기는 저장된 값만 읽고 렌더 시점에 계산하지 않는다**(화면 쪽 연결은 U11 전환 도구).

- **규칙 이관.** `cost_core::period`가 `verified_period_for`(= `period_for`에서 화면 전용 추론을 뺀 것, DATE-109)와 그 근거 인덱스의 검증 경로(`_build_index` 본 줄기 + `ledger_metadata`)를 순수 함수로 옮겼다. 저장 값이 있으면 그 값, 없으면 검증된 연결의 기간, 추론·근거 없음은 공란이다. 판정이 낼 수 있는 값은 `Known` 또는 사유 있는 `Unknown`(근거 없음·모호·해당 없음)뿐이다. `period`는 `plan`·`store`를 모르는 평문 입력(후보 목록 JSON, 화면 행 문자열)만 받는다.
- **입력 근거.** 예약 사실·연결은 2차 전환 전까지 Python 다리 `tools/core_bridge periods`가 거래별 후보 목록으로 넘긴다(`card_matches` 결과와 이벤트·카드의 규칙이 읽는 칸만, 원문 없음). 2차 전환 뒤에는 Rust 연결이 같은 자리에 선다.
- **저장.** core.sqlite 이관 2: `decisions.evidence_digest`·`period_fn_version`. `service_period_json`은 알면 `starts_on`·`ends_on`, 모르면 `unknown` 사유. 저장 함수 `store::decisions::save_decision`은 **U11 적용 경로가 유일한 쓰기 호출자**이고, 이 단위는 저장 함수·재판정 선택·시험까지다.
- **재계산 규칙.** 근거 digest = sha256(판정 함수 버전, 화면 행의 저장 기간·예약번호, 규칙이 읽는 칸의 후보 사실). 거래의 digest가 저장값과 다르거나 저장된 함수 버전이 현재와 다를 때만 그 거래를 다시 판정한다. `costcore rejudge --changed`가 바뀐 거래만 고르고(쓰지 않음, 공개 출력은 건수), 계획은 `PeriodEvidence.changed`의 거래를 **판정 7칸이 같아도** 새 `Decision`으로 낸다(`targets`에는 넣지 않는다). 규칙을 고치면 `PERIOD_FN_VERSION`을 올려 전부 한 번 재판정한다.
- **검증.** 골든 `golden/synthetic/period.jsonl`(생산기가 Python `verified_period_for`를 직접 호출, `covers` 자체 점검)을 Rust가 100% 재현한다. 운영 사본 그림자 비교는 `tools/core_bridge/period_shadow.py`(Python 기대값)와 `costcore periods`(Rust)의 차이 건수로 낸다.

## 3. 데이터

### 3.1 현 `board.sqlite`에서 코어가 읽는 것과 쓰는 것

M3 동안 코어는 운영 DB를 **`mode=ro` + `PRAGMA query_only=ON`의 짧은 일관 읽기**로만 연다(현 방식: `tools/p2_batch/scope.py:26-54`). 쓰기는 전환 승인 뒤의 투영 쓰기(§3.3)뿐이다.

| 테이블(정의 위치) | M3 그림자 | 전환 뒤 | 코어에서의 뜻 |
| --- | --- | --- | --- |
| `transactions` (`app/db.py:53-87`) | 읽기 | 판정 열만 쓰기: `classification_state`·`classification_source`·`classification_basis`·`item`·`description`·`display_tab_id`·`trip_id`·`revision`(`app/automatic_classification.py:16-17`, `:565-567`) | 원천 열 → `SourceTxn`, 판정 열 → 기존 판정의 투영 |
| `trip_tabs` (`webapp/ledger_store_schema.py:249`) | 읽기 | 읽기 | `TripId`의 유일한 출처 |
| `cost_classification_rules` (`app/db.py:89-101`) | 읽기 | 읽기 | 데이터 규칙(P1 승격 211개 포함, `SPEC.md:228`). M3 동안 규칙 쓰기는 기존 `save_rule`·API 경로 유지(`app/rules.py:349-390`) |
| `review_decisions` (`app/db.py:103-113`) + 해제 이력(`app/decision_provenance.py:19-31`) | 읽기 | 읽기 | 수동 결정 → overrides |
| `board_manual_overrides` (`webapp/ledger_store_schema.py:38-43`) | 읽기 | 읽기 | 수동 교정 → overrides |
| `transaction_review_holds` (`app/db.py:115-120`), `transaction_company_exclusions` (`app/db.py:24-31`) | 읽기 | 읽기 | 보호 사유 |
| `ledger_entries` (`app/db.py:122-135`) | 읽기 | 빈 항목·빈 귀속만 채움(`app/automatic_classification.py:570-573`) | 기록된 장부 행. 새 행을 만들지 않는다 |
| `board_rows`, `board_revisions` (`webapp/ledger_store_schema.py:9-29`) | 읽기 | 화면 행 payload 동기화 + 이력(`app/automatic_classification.py:577-597`) | 화면 투영 |
| `change_log` (`app/db.py:137-143`) | 읽기(`card.ai_review_corrected`, `card.classification_corrected`, 닫힌 분기 검수 표시 `app/decision_provenance.py:40-44`) | 추가만 | 판정 이력의 원천 |
| `import_batches`·`import_batch_rows` (`app/db.py:33-52`) | 읽기 | 읽기 | 원본 파일(`content_bytes`)과 묶음 범위 → evidence 참조 |
| `requests` (`app/db.py:145`) | 읽기 | 추가만 | 요청 멱등성(`app/classification_correction.py:125-129`) |
| `ota-evidence.sqlite` (`app/ota_store.py:16-51`) | **직접 열지 않음.** Python 어댑터가 근거 사실과 OTA 결제 사건(`build_ota_payment_events`, `app/ota_payments.py:915`)을 만들어 `facts`로 넘긴다(`tools/complete_card_classification.py:47`) | 같음 | facts 입력. 연결(`links`)은 Rust가 만든다(D-7) |
| OTA 검토 DB의 `ota_review_links`·`ota_review_rules`·`ota_review_group_pins`·`ota_review_event_crosswalk` (`app/ota_review.py:172-196`, 운영 DB와 분리 검사 `:161`) | 읽기(어댑터 `snapshot`) | 읽기 | 대사 입력: 기존 수동·고정 연결은 **점유**(LINK-028, `docs/policy/link.md:289`), 승인 규칙은 쌍 검사 규칙, 고정 그룹은 `frozen_groups`(`app/ota_payments.py:2408-2417`). Rust는 여기에 쓰지 않는다 |
| `transactions`의 환불 관련 원천 열(`transaction_direction`·`original_approval_number`·`approval_number`·`issuer`·`card_tail`·`foreign_amount`·`foreign_currency`·`duplicate_of`·`conflict_reason`·`parse_error`) | 읽기 | 읽기 | 환불 짝 도출 입력(`app/partial_refund.py:154-186`, `:228-233`, `:324-332`). 설정은 `config/refund-pairing.json`(Git) |

### 3.2 새 테이블 — `core.sqlite`

`SPEC.md:332`의 목표 목록을 따르되, M3에서는 **별도 파일 `D:/WebLedgerHost/data/core.sqlite`** 에 둔다(운영 `board.sqlite` 스키마 변경을 피하기 위해, §9 D-4 결정 2026-11-14). 이 파일은 운영 백업과 7일 보존 대상에 들어간다. 단일 파일 통합은 Python이 퇴역하는 M6에서 한다.

| 새 테이블 | 내용 | 현 위치(대응) |
| --- | --- | --- |
| `schema_meta` | 스키마 버전, 이관 기록 | 없음 |
| `evidence` | 원본 참조: 종류, sha256, 원 위치(테이블·키). **원문 사본은 두지 않는다** | `import_batches.content_bytes`, `ota_raw_blobs` |
| `facts` | 어댑터가 낸 구조화 사실(예약 이용기간, 결제일, 예약번호 해시 등) + 생산자·Python SHA | `tools.complete_card_classification.load_review_evidence` 결과, `ota_bookings` 등 |
| `links` | **Rust가 만든** 환불 짝·OTA↔카드 연결(정확/추론 구분, 근거 종류 `basis`, 상태 full/partial/excess, M:N 성분 ID, 생산 규칙 버전). 그림자 기간에는 같은 스냅숏의 Python 연결(다리 `links` 명령)도 비교용으로 함께 담는다(`producer = rust \| python`) | `app/partial_refund.py:99` `refund_links`(링크 모양 `:202-207`, `:276-281`, `:374-380`), `match_ota_payment_events` 결과(`app/ota_payments.py:2408`), `ota_review_*` |
| `refund_groups` | 환불 묶음 판정: 원결제·구성원 전부·순잔액·상태·파일 간 확장 여부·보류 사유 코드(`refund_exceeds_original`, `refund_pair_mismatch`, `refund_completed_period`, `refund_unclean_member`, `refund_original_unattributed` 등, `app/ledger.py:383-456`) | 없음(`_apply_refund_pairs`가 미리보기마다 계산) |
| `trips` | `trip_tabs` 스냅숏(읽은 시각·digest) | `trip_tabs` |
| `decisions` | 거래당 현재 `Judgement` 1행(§2) | `transactions` 판정 열 7개 |
| `decision_history` | 판정 변경 전후 값·주체·요청 ID | `change_log`의 `card.*` 종류들, `board_revisions` |
| `overrides` | 수동 교정·사용자 예외 | `review_decisions`, `board_manual_overrides`, `decided_at`, 수동 출처 값 |
| `rules_builtin` | 코드에 박혀 있던 규칙의 데이터판(§4.1) | `app/classify.py:49-101`, `:417-442`, `app/automatic_classification.py:114-134` |
| `jobs`, `budgets` | 작업 큐·일일 예산. **U3에서 만들어 두고 M3 동안 비워 둔다**(§5, M5) | `D:/WebLedgerHost/data/p2-incremental.json`(`tools/p2_batch/run_incremental.py:24`) |
| `agent_runs`, `p2_proposals` | P2 실행 기록·검증된 제안. **M3 동안 비워 둔다**(§5, M5) | 같은 저널, 보호 경로의 `proposals.jsonl` |
| `shadow_runs`, `shadow_diffs` | 병행 실행 결과와 **유형별 집계** 차이(§3.3) | 없음 |

**판정 출처 대응표**(`transactions.classification_source` → `Actor`). 값 목록은 `app/classification_provenance.py:5-8`, `app/decision_provenance.py:15-16`, `tools/p2_batch/scope.py:16-18`에서 모았다.

| 현 값 | Rust | 비고 |
| --- | --- | --- |
| `user_decision`, `manual`, `previous_decision`, `decided_at` 있음 | `Manual` | `app/classification_provenance.py:14-15` |
| `user_exception`, `owner_booking` | `Manual`(사용자 예외로 표시) | 교정 경로가 보호(`app/classification_correction.py:84`) |
| `refund_original`, `guide_airfare_evidence`, 예약 이용기간 원본 결속 규칙(`origin` = `ota-mail-live`·`ota-portal-live`·`auto-ota-period` 이고 `source_hash` 결속) | `P1Exact` | `app/reconciliation.py:18-21`, `app/classify.py:369-376` |
| `owner_card_residual` | `P1Inferred`(사용자 예외 규칙 ID) | `app/classify.py:298-301` |
| `rule`, `pattern`, `card_category`, `provider_default`, `inference`, `code_inference`, `auto_inferred` | `P1Inferred` | |
| `ai_inference` + 근거가 `AI_REVIEW · `로 시작 | `AiReview` | `tools/quarter_review/eval_cases.py:66` |
| `ai_inference` 그 밖 | `P2` | `app/classification_correction.py:139` |
| `rule_conflict`, `inference_conflict`, `travel_location_hold`, `booking_evidence_needed`, `unreadable`, 빈 값 | 판정 없음 → 그림자 실행이 새로 판정 | 2.2절 |
| `manual_hold` | `Manual`이되 **원 출처 값을 함께 보존**하고 기록 불가로 취급(사용자 보류) | `tools/p2_batch/scope.py:16`(보호), `app/automatic_classification.py:53`(`CLASSIFICATION_SOURCE_CONFLICT`), `docs/policy/record.md:209`. 저장 계층 `Mapping.raw_source`·`is_manual_hold()` |
| `auto` | 대응 없음(`Unrecognized`) → 판정으로 취급하지 않고 보고 | `app/classification_provenance.py:8` `AUTOMATIC_SOURCES`에만 있고 이 표에 없던 값. 표에 없는 값은 모두 같은 처리 |

### 3.3 병행 실행과 운영 전환

**그림자 실행(M3 전 기간).**

1. 입력 고정: 운영 DB를 `mode=ro`로 짧게 읽어 스냅숏 digest를 만든다. 실데이터 대조는 보호 경로(`D:/WebLedgerHost/data/backups/` 아래, Git 밖)의 신선 백업 사본에서 한다.
2. 같은 사본에 대해 세 값을 얻는다.
   - **A. 현재 저장값**: `transactions` 판정 열.
   - **B. Python 재판정**: `app.automatic_classification.plan`(`:457-544`)과 `app.classify.classify_transaction`(`:120-208`)을 Python 다리(§4.3)로 실행한 결과.
   - **C. Rust 재판정**: 코어의 P1.
   - **연결 단계**도 같은 방식으로 비교한다: B는 다리 `links` 명령이 낸 Python 환불 짝·환불 묶음 판정·OTA 대사 결과, C는 Rust 연결(U12~U14). 비교 대상은 **최종 연결**(카드↔사건·원결제↔취소 쌍, 상태, 묶음·성분 구성, 보류 여부)이며 후보 목록·거절 사유 코드·점유 집합 같은 중간 산출물은 비교하지 않는다(D-12). 연결 차이 유형 키는 연결 종류(`refund_number`·`refund_foreign`·`refund_amount_inferred`·`ota_exact`·`ota_mn_group`·`ota_undated_inferred`), 상태 전환(full/partial/excess/보류 사유), 성분 크기 전환이다.
3. 비교는 B↔C가 회귀 판정, A↔C는 참고(전환 시 실제로 바뀔 행 수)다. 결과는 `shadow_diffs`에 **유형 키**(필드, 이전 출처, 항목 전환 어휘, 귀속 종류 전환)와 건수로만 남긴다. 유형 키는 `tools/quarter_review/eval_cases.py:117-146`의 허용 목록 방식(`validate_public`)을 그대로 따른다. 거래 ID·금액·가맹점은 보호 경로의 비공개 파일에만 둔다(`SPEC.md:397`).
4. 설명된 차이는 `config/core-known-diffs.txt`에 유형 키와 근거(규칙집 ID 또는 `docs/policy/CODE_GAPS.md`의 줄)로 적는다. 형식과 운영은 `config/known-test-failures.txt:1-3`과 같다: **목록 밖 차이 1건이라도 있으면 실패, 목록에 있지만 사라진 차이는 '해소됨'으로 보고하고 줄을 지운다.**
   - 예: CODE_GAPS의 TRIP-044(겹치는 해외 여행의 사용 국가, `docs/policy/CODE_GAPS.md:13`)처럼 **규칙집이 맞고 Python이 틀린** 곳을 Rust가 규칙집대로 구현하면 B↔C 차이가 생긴다. 이 차이는 해당 규칙 ID와 함께 목록에 올리고, 평가 사례(§4.4)에서 Rust가 더 맞음을 보여야 한다.

**운영 전환은 두 번이다**(D-11, 2026-11-14).

| 전환 | 바꾸는 것 | 그대로 두는 것 | 선행 단위 |
| --- | --- | --- | --- |
| 1차(판정) | P1 자동 분류의 판정 열 작성자: Python `app.automatic_classification.apply` → Rust 투영 쓰기(U11) | 연결 입력은 U9의 연결 트레이트 뒤에서 Python 어댑터 `links`를 그대로 쓴다. 환불 묶음 기록(`app/ledger.py`)과 화면 연결 저장소도 Python | U9, U10, U11 |
| 2차(연결) | 연결 트레이트를 Python 어댑터 → Rust 연결(U12~U14)로 바꿔 끼우고, 환불 묶음 게시를 `publish_group`(§2.4)으로 | 환불 묶음의 장부 행 삽입은 계속 Python 기록 경로(§1.2) | U12, U13, U14 |

두 전환 모두 수동 교정과 P2·AI 검수 교정은 지금처럼 인증 API 교정 경로(`app/classification_correction.py:46-186`)가 쓴다. 전환이 바꾸는 것은 **P1 자동 분류의 작성자 하나**이고, Rust는 교정 경로가 쓴 값을 기존 판정으로 읽어 `supersede` 표(§2.3)대로 덮지 않는다.

**전환 조건**(전환마다 셋 모두 충족, 판단은 §9 D-6의 승인자).

| # | 조건 |
| --- | --- |
| C1 | 신선 스냅숏 **1개**에서 실데이터 그림자 B↔C의 목록 밖 차이 0건. 1차는 판정, 2차는 판정과 최종 연결 |
| C2 | 평가 사례 재실행(§4.4)에서 Rust의 일치 건수 ≥ Python, 그리고 Python이 맞힌 사례 중 Rust가 틀린 것 0건 |
| C3 | 신선 백업·복원 확인(`SPEC.md:383`)과 설정 플래그 되돌림 예행(§8) 완료 |

옛 조건 T1~T6의 처리: T1(골든·`cargo` 게이트)은 모든 PR의 게이트(§6.3)라 전환 조건에서 뺐다. T4(투영 쓰기 동등성)는 U11의 수락 조건으로 옮겼다. T6(작성자 하나)은 조건이 아니라 아래 전환 절차다. T2의 "7일 이상 간격 스냅숏 2개"는 달력 대기만 만들므로 없애고, 전환 뒤 매일 대조와 즉시 되돌림으로 대신한다.

**전환 절차.** 같은 DB에 P1 판정을 쓰는 작성자는 하나다: 설정 플래그 하나로 Python 자동 분류 경로를 끄고 Rust만 쓴다(AGENTS.md "같은 파일·DB·배포의 작성자는 하나다"). 2차 전환은 같은 방식의 두 번째 플래그(연결 생산자)다. 절차서는 `docs/playbooks/core-cutover.md`(U11이 1차, U14가 2차 부분을 쓴다).

**전환 뒤.** 현 화면은 계속 `transactions` 판정 열을 읽는다. Rust는 `decisions`에 먼저 쓰고 같은 트랜잭션 안에서 투영 쓰기로 `transactions`·`ledger_entries`·`board_rows`를 맞춘다. 두 DB 사이의 원자성은 SQLite `ATTACH` 단일 트랜잭션으로 얻는다(같은 연결에서 `core.sqlite`와 `board.sqlite`를 함께 연다). 운영 담당은 배포 창(하루 1~2회)마다 **A↔C 대조**(DB 판정 열과 `decisions`의 일치)와 **B↔C 그림자**를 돌린다. 목록 밖 차이가 1건이라도 나오면 즉시 해당 플래그를 Python으로 되돌리고, 원인을 고친 뒤 C1~C3을 다시 잰다. 매일 대조는 Python 판정·연결 코드를 퇴역할 때까지 계속한다.

### 3.4 추출기 기준 출력

`SPEC.md:333`대로 M3 착수 시 기존 Python 추출기를 보존 원본에 돌려 **facts 기준 출력**을 만든다. M3는 이 출력을 코어의 `facts` 입력으로 쓰고, M6의 Rust 추출기 병합 조건으로 보존한다. 기준 출력은 고객 자료이므로 보호 경로에만 두고 Git에는 생산 명령·Python SHA·건수만 남긴다.

## 4. P1 규칙 엔진

### 4.1 데이터형 규칙 표 형식

기존 `cost_classification_rules`의 조건/선택 조건/효과 분리(`app/rules.py:119-121`)를 그대로 유지하고, **코드에 박힌 규칙을 같은 모양의 데이터로 옮긴다.** 새 "규칙 종류"만 코드 변경이다(계획 `:110`).

```json
{
  "rule_id": "P1-PAT-GS25",
  "version": 1,
  "kind": "merchant_pattern",
  "strength": "inferred",
  "stage": 40,
  "policy_refs": ["ITEM-0xx"],
  "conditions": { "merchant": { "equals_or_prefix": "gs25" } },
  "scope": { "direction": "purchase" },
  "effects": { "item": "편의점", "description": "편의점 구매" },
  "attribution": "verified_local_trip",
  "origin": "builtin:app/classify.py:52"
}
```

| 필드 | 뜻 |
| --- | --- |
| `kind` | `merchant_exact`(현 DB 규칙), `merchant_pattern`(`app/classify.py:49-101`), `card_category`(`:417-435`), `provider_default`(`:436-442`), `owner_exception`(`:211-236`, `:273-301`, 후쿠타케 `:134-143`), `inferred_assignment`(`:150-208`), `item_keyword`(`app/automatic_classification.py:114-134`) |
| `strength` | `exact` → `Actor::P1Exact`, `inferred` → `Actor::P1Inferred` |
| `stage` | 평가 순서. 현 코드의 순서를 숫자로 고정한다(§4.2). 같은 단계에서 효과가 다르면 충돌 |
| `scope` | 카드 끝자리·기간·방향·국가 등 사용자 예외의 적용 범위(`DECISION_POLICY.md` §5) |
| `attribution` | `none`, `verified_local_trip`(`app/classify.py:104-117`), `quarter_of_payment`, `owner_trip`(예: 싱가포르 예외), `inferred_trip_id` |
| `origin` | 출처. 데이터 규칙은 DB의 `origin`, 내장 규칙은 원래 코드 `파일:줄` |

- 내장 규칙은 `core/rules/builtin/*.json`(고객 자료 아님, Git 포함)에 둔다. 운영 데이터 규칙은 계속 `cost_classification_rules`에서 읽어 **규칙 저장소가 둘로 갈라지지 않게** 한다.
- 정규화 검사는 `normalize_rule`(`app/rules.py:135-258`)과 같은 거부 조건을 Rust에서 같은 오류 코드로 낸다. 특히 원천 필드 금지(`:147-148`), 가맹점 조건 필수(`:168-169`), 전체 가맹점 규칙의 현지 사용 제한(`:183-184`), 추론 배정의 원본 결속(`:187-196`), 가맹점 규칙의 여행 배정 금지(`:245-246`).

### 4.2 현 평가 순서(이관의 정답)

Rust 엔진은 아래 순서를 `stage`로 재현한다. 순서를 바꾸는 것은 규칙집 개정이 있을 때만이다.

| stage | 현 코드 | 결과 |
| --- | --- | --- |
| 0 | 완료 기간 제외 `closed_period.excluded` (`app/classify.py:124-129`, `app/closed_period.py:56-66`) | `Preserved` |
| 5 | 파싱 오류 (`app/classify.py:310-315`) | `Protected` |
| 10 | 이전 결정 (`:317-325`) | `Manual` 유지 |
| 20 | 가맹점 규칙 + 국가·예약기간 조건 + 우선순위 필터(원본 결속 OTA > 옛 복원 규칙, 공급자 기본값) (`:332-407`) | 규칙 효과 / 충돌 |
| 25 | 여행 확인 실패 보류 (`:409-414`) | P1 내부 결과 → 공통 추론 + P2 힌트 |
| 30 | 카드사 업종 (`:417-435`) | 항목 (+검증된 현지 여행) |
| 35 | 공급자 기본값 skyticket (`:436-442`) | 항목 |
| 40 | 가맹점 패턴 (`:443-450`) | 항목 (+검증된 현지 여행) |
| 45 | 전체 가맹점 현지 기본값 (`:454-455`) | |
| 50 | 예약·온라인 근거 필요 (`:457-460`) | P1 내부 결과 |
| 60 | 외곽 규칙: 후쿠타케(`:134-143`), 3820 싱가포르(`:144-147`), 추론 배정 규칙의 출처 우선(`:162-208`), 3820 잔여(`:159-160`, `:273-301`) | |
| 70 | 공통 추론: 항목 `infer_item`(`app/automatic_classification.py:104-134`), 여행 `infer_trip`(`:146-179`), 분기 종결(`:416-429`) | `P1Inferred` |
| 80 | 환불 원거래 상속 `pair_refunds`(`app/classify.py:243-270`), 검증된 원결제 상속(`app/automatic_classification.py:373-378`) | `P1Exact` |

`plan`의 보호 순서(`app/automatic_classification.py:479-502`): 완료 기간 → 보류·제외·파싱/중복/충돌 → 기록된 P2(`ai_inference`) 건너뜀 → 완료된 환불 상속 → 3820 수동 결정 → 닫힌 분기 검수. 이 순서도 그대로 옮긴다.

### 4.3 이관 순서

의존이 적고 순수한 것부터 옮겨 골든을 일찍 녹색으로 만든다.

| 순서 | 대상 | 이유 |
| --- | --- | --- |
| 1 | `app/rules.py` `normalize_rule`·`rule_matches`·`transaction_region`·`merchant_country`·`is_booking_or_online` (`:27-321`) | 순수 함수, DB 규칙 211개를 즉시 검증 가능 |
| 2 | `app/classify.py`의 내장 규칙 → 데이터: `CLEAR_PATTERNS`·`_pattern_for`·업종 묶음·skyticket (`:49-101`, `:417-442`) | 순수, 표로 옮기기만 |
| 3 | `_classify_transaction` 순서·충돌 판정 (`:304-466`) | 1·2를 조립 |
| 4 | 날짜·분기·완료 기간·열린 범위: `app/quarter_costs.py`, `app/closed_period.py`, `app/reconciliation.py:27-104`, `app/classification_correction.py:18-37` | 순수, 여행 추론의 전제 |
| 5 | 사용자 예외·추론 배정 출처 우선(`app/classify.py:120-301`) | 판정 위험이 큰 데이터화 |
| 6 | 여행 추론: `infer_trip`, `provisional_assignment.card_trip_candidates`(`app/provisional_assignment.py:21`), `trip_selection`, `reconciliation.stay_trip`(`:116`) | 의존이 가장 많다 |
| 7 | `plan` 조립: 보호·이력 복원(`app/automatic_classification.py:289-313`)·신규 판정(`:316-454`)·digest(`:536-539`) | 1~6 + 어댑터 `links`·`facts` |
| 8 | 투영 쓰기(`apply`, `:547-614`) | 전환 직전, 동등성 시험 대상 |

**Python 다리.** Rust는 Python을 라이브러리로 부르지 않고 `python -I -m tools.core_bridge <명령>`을 하위 프로세스로 부른다. 표준 입출력은 JSON Lines, 각 응답에 `python_sha`(git HEAD)와 입력 digest를 담는다. 명령: `snapshot`(입력 투영 읽기), `facts`(근거 사실·OTA 결제 사건), `links`(Python 환불 짝·환불 묶음 판정·OTA 대사 — 2차 전환 전에는 코어의 연결 입력, 그 뒤에는 그림자 비교 B와 골든 생산에만 쓴다), `plan`(골든 B 생산), `extract`(§3.4). 다리는 읽기 전용이며 운영 DB를 `mode=ro`로만 연다.

### 4.4 골든 회귀와 평가 사례

| 층 | 무엇과 비교 | 어디에 | 게이트 |
| --- | --- | --- | --- |
| 합성 골든 | 현 Python 함수 출력(B)을 합성 입력에 대해 만든 JSONL | `core/golden/synthetic/` (Git, 고객 자료 없음) | 모든 PR, 100% 일치 |
| 실데이터 그림자 | 신선 백업 사본의 B↔C | 보호 경로 | **주 게이트.** 규칙 엔진·연결 PR은 헤드가 실행해 집계만 PR에 붙임. 전환 조건 C1 |
| 평가 사례 | AI 검수자 교정(정답) ↔ C | 보호 경로 | 전환 조건 C2, 규칙 개정 묶음마다 |

**"Python과 같음"의 범위(D-12, 2026-11-14).** 모든 단위의 "Python과 같음"은 **운영에 실재하는 입력 범위에서 최종 결과가 같음**을 뜻한다. 최종 결과는 판정(`Judgement`의 귀속·항목·설명·이용기간·주체 종류)과 최종 연결(§3.3)이다. 중간 산출물(후보 목록, 거절 사유 코드, 점유 집합, 내부 정렬)은 맞추지 않는다. 운영에 없는 입력 형태(예: `YYYY-MM-DD`가 아닌 날짜 문자열, 공백이 붙은 숫자열)는 Python의 우연한 동작을 베끼지 않고 `Judgement::Protected`로 **닫힌 쪽으로 실패**시킨다. Rust가 Python보다 느슨해지는 방향의 차이는 허용하지 않는다. 합성 골든은 이 범위의 사례와 경계값만 두고, 실제 경로를 전부 지나는 실데이터 그림자를 주 게이트로 삼는다. 차등 퍼즈는 한 번 확인하는 도구로만 쓰고 게이트로 반복하지 않는다.

**Python 규칙 개선 묶음과 골든 재생성(D-5, 2026-11-14).** 1차 전환 전까지 Python 판정 규칙 개선을 계속한다(2차 전환 전까지 연결 코드도 같다).

1. 판정·연결 규칙 개선은 **하루 한 묶음** 브랜치·PR에 모은다. 평가 사례 실행 1회(근거 없는 실행이 기본, 근거 포함 실행은 묶음당 1회·배포 창 직전), 검수 1회(판정·금융이므로 Claude opus), 배포 창 1회. PR 본문에 묶음 전체의 합산 일치 수를 직전 기준선과 함께 적는다.
2. 같은 PR에서 `python -m tools.core_bridge.golden write`로 합성 골든을 다시 만들고 `python -m tools.core_bridge.golden check`가 통과해야 한다. 기대값은 손으로 고치지 않는다. 바뀐 사례 수를 차이 유형(영역·필드·전환 어휘)별로 PR 본문에 적는다.
3. 바뀐 골든이 **이미 main에 병합된 Rust 단위**의 영역이면, 같은 묶음 PR에 Rust 추종 변경을 넣어 `cargo test`가 녹색인 채로 병합한다(골든과 Rust가 한 PR에서 함께 움직인다). 추종 변경을 그날 넣지 못하면 그 규칙을 묶음에서 빼고 다음 묶음으로 넘긴다.
4. 진행 중인 Rust 단위 PR은 병합 직전 main의 최신 골든 위로 다시 올려 녹색을 확인한다. 단위 PR은 Python 판정 코드를 바꾸지 않는 한 골든을 다시 만들지 않는다.
5. 1차 전환 뒤 판정 규칙 개선은 Rust(규칙 표·코드)에 하고 Python 판정 코드는 바꾸지 않는다. 그 개선이 만드는 B↔C 차이는 규칙집 ID와 함께 `config/core-known-diffs.txt`에 올린다. 2차 전환 뒤 연결 코드도 같다.

- **합성 골든 생산:** 현 판정 테스트(`webapp/tests/test_classification_rules.py`, `webapp/tests/test_automatic_classification_completion.py`, `webapp/tests/test_automatic_plan_refactor.py`, `tests/test_classify_regression_failures.py`, `tests/card_pipeline/test_merchant_family_classify.py`, `tests/card_pipeline/test_guide_airfare_classify.py` 등)의 합성 입력과, 내장 규칙 표에서 만든 조합 입력을 Python 다리로 돌려 기대 출력을 고정한다. 기대값은 Python이 낸 값이며 손으로 고치지 않는다. Python 판정 코드가 바뀌면 골든을 다시 만들고 그 PR에 차이 유형을 적는다.
- **PR #855 `eval_cases.py` 활용:** `tools/quarter_review/eval_cases.py`는 AI 검수 교정(`change_log` `card.ai_review_corrected`, `:31`)을 사례로 모으고, 교정된 행을 새로 수입된 상태로 되돌린 뒤(`FRESH`, `:67-68`, `:179-186`) 현재 P1 `plan`으로 재판정해 MATCH/MISMATCH/ITEM_NOT_REEVALUATED/NOT_REJUDGED로 센다(`:201-248`). M3는 여기에 **재판정기 선택**을 더한다: `--planner python|rust`. `rust`는 메모리 사본 대신 보호 경로의 임시 파일 사본을 만들어 `costcore plan`에 넘긴다(`_cases_dir`의 보호 경로 검사 `:251-259` 재사용). 두 실행의 사례별 결과를 비교해 C2를 판정한다. 사례 파일·출력의 공개값 허용 목록(`:134-146`)은 그대로 둔다.
- **`config/known-test-failures.txt` 활용:** (1) M3의 Python 쪽 변경(다리, `eval_cases.py` 옵션)은 이 목록 밖 실패를 만들면 안 된다(`tools/run_quality_checks.py:361`). (2) Rust 쪽은 알려진 실패 목록을 두지 않는다 — 새 코어는 처음부터 녹색이다(계획 `:148`). (3) 같은 형식을 `config/core-known-diffs.txt`(§3.3)에 차용한다.

## 5. 작업 큐와 P2 실행기 — M5로 이월

2026-11-14 축소 개정(D-11)으로 M3에서 뺐다. P2는 월 100건 안팎이고 현 `tools/p2_batch`가 2026-11-13에 처음 실제로 돌았다. 다시 써도 소유자가 얻는 것이 없고, 임대 구조는 M5(클라우드 보조 노드)를 위한 선행 설계다.

- M3 동안과 두 전환 뒤에도 P2 실행·검증·반영은 **현 Python 경로를 그대로 쓴다**(`tools/p2_batch/`, 반영은 인증 API 교정 경로·미리보기 digest·요청당 50행, `tools/p2_batch/README.md:25`, `app/classification_correction.py:46-186`). Rust는 반영된 P2 판정을 기존 판정으로 읽고 `supersede` 표(§2.3)대로 P1이 덮지 않는다.
- P1이 내는 `P2Hint`(§2.2)는 M3에서 그림자 차이 보고에만 쓴다. P2 대상 선정은 계속 `tools/p2_batch/scope.py`가 한다.
- `core.sqlite`의 `jobs`·`budgets`·`agent_runs`·`p2_proposals`는 U3에서 만들어 두고 M3 동안 비워 둔다.
- 원안(작업 큐 테이블과 임대·예산, `P2Runner`·`CodexExec`·`Replay`, 검증·재시도 분류, 대상 선정 계승)은 이 문서의 `b8520f48` 판 §5에 있다. M5 착수 때 그 시점의 P2 운영 기록과 함께 다시 검토한다.

## 6. 크레이트·빌드·테스트 게이트

### 6.1 구성

```
core/                       Cargo 작업공간 (레포 안)
  Cargo.toml  rust-toolchain.toml  clippy.toml
  crates/
    core/      cost-core      라이브러리. 모듈로 나눈다(아래)
    cli/       costcore       실행 파일: shadow | plan | eval | migrate
  rules/builtin/*.json      내장 규칙(§4.1)
  golden/synthetic/*.jsonl  합성 골든(§4.4)
tools/core_bridge/          Python 다리(읽기 전용)
```

| `cost-core` 모듈 | 내용 | 소유 단위 |
| --- | --- | --- |
| `domain` | 판정 타입·우선순위·불변식. DB·프로세스·네트워크를 모른다 | U2 |
| `store` | `core.sqlite` 스키마·이관, `board.sqlite` 읽기 전용 투영, 투영 쓰기 | U3, U11 |
| `dates` | 날짜·분기·완료 기간·열린 범위, `OpenScope` 생성 | U7 |
| `rules` | 규칙 표 형식·정규화·평가·내장 규칙 적재, 사용자 예외 | U5, U6 |
| `trips` | 여행 귀속 추론 | U8 |
| `links` | `refund`(환불 짝·환불 묶음, `RefundGroup`의 유일한 생성처), `ota`(OTA↔카드 대사·점유). DB를 모르고 `store`가 읽은 투영과 어댑터 사건만 받는다 | U12, U13, U14 |
| `pipeline` | P1 조립, 그림자 실행, 차이 집계 | U9, U10 |
| `bridge` | Python 하위 프로세스 프로토콜 | U4의 Rust 쪽(필요한 단위가 추가) |

- **크레이트는 둘이다**(D-12, 2026-11-14). 처음 설계의 9개 크레이트는 봉인 타입의 타입과 발급을 다른 크레이트에 두게 만들었고, 그 틈을 메우려고 발급 기능 플래그와 허용 목록 스캔이 생겼다. 하나의 라이브러리로 합치면 크레이트 밖 생성은 가시성(`pub(crate)`)이, 크레이트 안 다른 모듈의 생성은 비공개 필드가 막는다(§2.4 봉인의 수준). 작업 큐(`jobs`)·P2(`p2`) 크레이트는 M5로 빠졌다(§5).
- 모듈 사이 의존 방향은 원칙으로 유지한다: `domain`은 다른 모듈을 모르고, `links`·`rules`·`trips`·`dates`는 `store`를 부르지 않으며, `pipeline`이 조립한다. 검수자가 `use` 문을 읽어 확인하고, 위반은 차단 사유가 아니라 후속 목록이다(§7.4).
- 소유권: 같은 파일을 두 단위가 고치지 않게 모듈(폴더) 단위로 나눈다. `lib.rs`의 모듈 선언 한 줄처럼 공유 파일의 충돌은 다시 올리기(rebase)로 푼다.
- 외부 크레이트(§9 D-2, **2026-11-14 승인**): `rusqlite`(bundled), `serde`·`serde_json`, `thiserror`, `regex`, `sha2`, `time`, 개발용 `proptest`. 이 밖의 추가는 PR마다 검수자가 확인한다. D-2의 "7개"는 외부 라이브러리 수이며 작업공간 크레이트 수와 무관하다. 외화 금액 비교(`Decimal`, `app/partial_refund.py:211-216`, `app/ota_payments.py:1224`)는 새 크레이트 없이 정수 최소 단위 고정소수로 직접 구현한다.
- 운영 포트 8751·8752·8790을 쓰지 않는다(`SPEC.md:396`). M3의 코어는 서버를 띄우지 않는다.

### 6.2 빌드 전제

- Rust 도구 설치 완료(§9 D-1, 2026-11-14): `rustc 1.100.0` 안정판 `stable-x86_64-pc-windows-msvc`, `clippy 0.1.100`, `rustfmt 1.11.0`, MSVC 빌드 도구는 `D:\BuildTools`. 2026-11-14에 `%USERPROFILE%\.cargo\bin`의 실행 파일로 버전을 확인했다. 새로 연 셸에 따라 `PATH`에 이 폴더가 없을 수 있으니 U1의 게이트 스크립트는 경로를 명시한다. `rust-toolchain.toml`은 `1.100.0`으로 고정한다.
- 작업 폴더(worktree)마다 `target/`이 생기면 디스크를 크게 쓴다. 공용 `CARGO_TARGET_DIR`을 쓸지는 착수 때 디스크 여유를 보고 정한다. 이 PC가 감당할 병렬 빌드 수는 아직 모른다(계획 `:92`) — U1에서 측정한다.

### 6.3 게이트

| 게이트 | 명령 | 언제 |
| --- | --- | --- |
| 형식 | `cargo fmt --all --check` | 모든 Rust PR |
| 정적 검사 | `cargo clippy --workspace --all-targets -- -D warnings` | 모든 Rust PR |
| 테스트 | `cargo test --workspace` (합성 골든, `compile_fail` 문서 테스트 4개 포함) | 모든 Rust PR |
| 표·속성 테스트 | §2.3 `supersede` 25칸 표 테스트, §2.4 불변식(원천 열 미변경, 묶음 원자성, 0원 금지), 환불·OTA 점유 속성 테스트 | `domain`·`store`·`links` 변경 |
| Python 영향 | `python tools/run_quality_checks.py --base origin/main --run` — `known-test-failures.txt` 밖 실패 0 | `.py`가 바뀐 PR만(다리·`eval_cases.py`·규칙 개선 묶음) |
| 실데이터 그림자 | `costcore shadow` → 목록 밖 차이 0, 집계만 PR에 | 규칙 엔진·연결 PR(헤드 실행), 전환(C1), 전환 뒤 매일 |
| 평가 사례 | `python -m tools.quarter_review.eval_cases eval --planner rust` | 전환(C2), 규칙 개선 묶음 |

- **CI 결제 한도.** CI가 시작되지 못하는 동안(`SPEC.md:380`) 위 명령의 **로컬 실행 출력**을 PR에 붙이고, 다른 모델 세션이 최종 SHA를 검수·승인한 PR만 병합한다. 실제 검사 실패는 이 예외로 통과시키지 않는다. U1에서 `.github/workflows/quality.yml`에 Rust 작업을 추가해 두되(결제가 풀리면 바로 돈다), 지금의 게이트는 로컬 실행이다.
- `tools/run_quality_checks.py`가 `core/` 변경을 감지하면 위 cargo 명령을 함께 돌린다(U1에서 연결함).
- 게이트는 구현자가 돌려 출력을 PR에 붙인다. 검수자는 그 출력과 `cargo test` 한 번으로 확인하고 전부 다시 돌리지 않는다(§7.4).
- 작업자가 테스트나 골든 기대값을 고쳐 통과시키지 않는다(`SPEC.md:379`). 골든 재생성은 Python 판정 코드가 바뀐 PR(하루 한 묶음)에서만 하고 차이 유형을 적는다(§4.4 D-5 절차).

## 7. 작업 분할

14개 단위(2026-11-14 축소 개정 D-11). 처음 18개에서 작업 큐(옛 U12)와 P2 실행기(옛 U13)를 M5로 빼고, 그림자 실행과 평가 사례 연결(옛 U10·U11), 환불 짝과 환불 묶음(옛 U15·U16)을 각각 합쳤다. U1~U9의 번호는 그대로이고 U10부터 다시 매겼다(옛 번호는 표의 "옛 ID"). 각 단위는 PR 하나이며 §6.3 게이트, §7.1 공통 기준, 아래 수락 조건을 만족해야 병합한다. 고객 원문은 어느 작업자에게도 주지 않는다: 모든 단위는 합성 자료로 개발하고, 실데이터 그림자·평가 사례 실행은 원문 접근이 허용된 실행자(`SPEC.md:375`, `:397`)가 하며 PR에는 집계만 남긴다.

### 7.1 공통 수락 기준(D-12)

- "Python과 같음"은 §4.4의 범위다: 운영에 실재하는 입력에서 최종 결과가 같음. 중간 산출물은 맞추지 않고, 운영에 없는 입력 형태는 `Protected`로 닫는다.
- 봉인 타입은 §2.4 "봉인의 수준"대로: 비공개 필드 + `pub(crate)` 이하 생성 함수, `compile_fail` 문서 테스트는 `RefundGroup`·`OpenScope`·`TripId`·`Subject` 외부 생성 4개만. 발급 기능 플래그·허용 목록 스캔·없는 구현을 확인하는 시험은 두지 않는다.
- 합성 골든은 그 단위가 다루는 경로가 실제로 실행되는 사례만 센다(사례 이름만 있고 경로가 실행되지 않으면 거짓 통과). 빠진 경계는 그 경계를 다루는 단위의 PR에서 추가한다.

### 7.2 단위

| ID | 단위 | 옛 ID | 의존 | 권장 구현 → 검수 | 수락 조건 |
| --- | --- | --- | --- | --- | --- |
| U1 | 작업공간 골격·게이트 | U1 | — | Sonnet → Sol | **완료**(#871, 후속 #872). 크레이트 통합은 U2가 한다 |
| U2 | 판정 도메인 타입 + 크레이트 통합 | U2 | U1 | Luna → Claude sonnet | §2의 타입 전부. `supersede` 25칸 표 테스트. `Amount::Unreadable`이 `Decision`이 될 수 없음. `compile_fail` 4개(§7.1). 작업공간을 `cost-core` + `costcore`로 통합(§6.1), 발급 기능 플래그·허용 목록 스캔 삭제 |
| U3 | 저장 계층 | U3 | U2 | Luna → Claude sonnet | `cost-core::store`. `core.sqlite` 스키마(§3.2)와 이관 번호. `board.sqlite` 읽기 전용 투영이 `mode=ro`·`query_only`·짧은 트랜잭션으로 `scope.read_projection`(`tools/p2_batch/scope.py:26-54`)과 같은 열을 읽음. 출처 대응표(§3.2) 전 값 매핑 테스트. 쓰기 열 목록에 원천 열이 없음을 테스트로 고정 |
| U4 | Python 다리·합성 골든 생산기 | U4 | U1 | Sonnet → Sol | `tools/core_bridge`의 `snapshot`·`facts`·`links`·`plan`·`extract` 명령(읽기 전용, `python -I`). `links`는 환불 짝, 환불 묶음 판정 결과, OTA 대사 결과를 낸다(U12~U14의 골든 B, 비교 대상은 최종 연결). 기존 판정 테스트의 합성 입력과 조합 입력으로 `core/golden/synthetic/` 생성. 고객 자료가 골든에 들어가지 않음을 검사하는 테스트. Python 품질 검사 목록 밖 실패 0 |
| U5 | 규칙 표 형식·엔진 1단계 | U5 | U2, U4 | Luna → Claude sonnet | §4.1 형식, `normalize_rule`과 같은 거부 조건·오류 코드, `rule_matches` 이관, 내장 패턴·업종·skyticket 데이터화(§4.3 순서 1~3). `_classify_transaction` 합성 골든(여행 해석기 없음) 100% 일치. 운영 규칙 211개가 오류 없이 적재됨(헤드가 집계 확인) |
| U6 | 사용자 예외·추론 배정 데이터화 | U6 | U5 | Luna → Claude sonnet | 후쿠타케·3820 싱가포르·3820 잔여·추론 배정 출처 우선(§4.2 stage 60)을 `owner_exception`·`inferred_assignment` 규칙으로. 각 규칙에 `DECISION_POLICY.md` §5의 ID. `classify_transaction` 합성 골든 100%. Python 쪽이 아직 자주 바뀌는 영역이라 판정 단계에서 가장 늦게 시작한다 |
| U7 | 날짜·분기·완료 기간·열린 범위 | U7 | U2 | Sonnet → Sol | `cost-core::dates`. `quarter_costs`, `closed_period`(`app/closed_period.py:11-66`), `reconciliation` 날짜 함수(`app/reconciliation.py:27-104`), `_open_p2_tab`(`app/classification_correction.py:18-37`)의 Rust판과 `OpenScope` 생성. 날짜는 **`YYYY-MM-DD`만** 받고 그 밖의 값은 날짜 파손으로 `Protected`. Python 날짜 해석과의 바이트 동등은 요구하지 않는다. 경계일(2025 전체, 2026Q1, 2026-06-30, 분기 끝) 골든 100%와 비정형 입력이 거부되는 사례 |
| U8 | 여행 귀속 추론 | U8 | U7, U4 | Luna → Claude sonnet | `cost-core::trips`. `infer_trip`·`card_trip_candidates`·`trip_selection`·`stay_trip` 이관. 동률 고정 순서(`app/automatic_classification.py:166-169`) 재현. 합성 골든 100%. CODE_GAPS의 TRIP-044 등 규칙집과 다른 곳은 Python 동작을 재현하고 차이 후보로 표시만 한다. U6과 같은 이유로 늦게 시작한다 |
| U9 | P1 계획 조립·보호 | U9 | U3, U5, U6, U8 | Luna → Claude sonnet | `plan` 이관: 보호 순서(`app/automatic_classification.py:479-502`), 이력 복원, 신규 판정, `links`·`facts` 사용, digest. 연결 입력은 하나의 트레이트 뒤에 두어 어댑터 `links`(2차 전환 전)와 Rust 연결(2차 전환 뒤)을 바꿔 끼운다. 결과는 `Judgement`이며 정상 거래에 `Decided` 외 값이 없음. `plan` 합성 골든 100% |
| U10 | 그림자 실행·평가 사례 연결 | U10+U11 | U3, U4(엔진은 U9 전까지 대역). `--planner rust` 실행 확인은 U9 뒤 | Sonnet → Sol | `costcore shadow`: A·B·C 세 값, 유형 키 집계, 허용 목록 검사(`eval_cases.validate_public` 방식), `config/core-known-diffs.txt` 형식과 판정(목록 밖 1건이면 실패, 해소 보고), 비공개 파일은 보호 경로 밖에 쓰면 거부. `eval_cases.py`에 `--planner rust`와 사례별 Python/Rust 비교 출력(공개값 허용 목록 유지), 기존 `tests/test_quarter_review_eval_cases.py` 통과 + 새 합성 사례 테스트 |
| U11 | 투영 쓰기·1차 전환 도구·절차서 | U14 | U3, U9, U10 | Luna → **Claude opus**(전환 지점) | `apply`와 같은 쓰기(행 revision 결속, 장부 행 빈 칸만 채움, 화면 행 payload·이력, change_log)와 미리보기 digest. 연결 입력은 어댑터 `links`. 합성 DB와 운영 사본에서 Python `apply`와 결과 DB 차이 0(옛 T4). 설정 플래그로 판정 작성자 전환·되돌림. `docs/playbooks/core-cutover.md`의 1차 부분. **운영 DB에 실행하지 않는다** |
| U12 | 환불 짝·환불 묶음 판정 | U15+U16 | U2, U3, U4, U7, U9, U10 | Luna → **Claude opus** | `cost-core::links::refund`. ① 짝 도출: `app/partial_refund.py`의 원승인번호 1:N(`_number_links` `:146-208`, RFND-004·005), 외화 금액 연결과 날짜순 점유(`:226-282`, `config/refund-pairing.json`, RFND-011~016), 남는 외화 취소 개수 보류(`:70-78`, `:384-389`, RFND-014), 동액·카카오 추론 연결과 전역 유일성·점유(`:313-381`, RFND-007~009), 연결 순서(번호 → 외화 → 추론, `:66-81`). ② 묶음 판정: `app/ledger.py` `_apply_refund_pairs`(`:367-465`)의 추론 연결 기록 보류, 초과 환불 보류(RFND-018), 한쪽 기기록 보완(RFND-026), 한쪽 보류 시 둘 다 보류, 부분환불 분류 충돌(RFND-020), 전액 상쇄의 환불 탭 이동(RFND-022); 파일 간 부분환불 확장(RFND-029 개정, PROC-072 완료 기간 제외가 먼저, `app/partial_refund.py:108-133`), 원결제 유효 귀속 필수(`app/ledger.py:438-444`), 묶음 미완 기록 거부(`:557-567`). 결과는 `RefundGroup`(같은 모듈 생성) 또는 보류 사유. **수락:** 최종 연결과 묶음 판정(쌍·상태·순잔액·구성·보류 여부)이 운영 범위 합성 골든 100%. 보호 불변식: 깨끗하지 않은 행은 원결제가 될 수 없음, 원결제 후보 2개 이상이면 연결 없음, 한 구매가 두 취소에 점유되지 않음(속성 테스트), 추론 링크는 `RefundGroup` 확장 입력이 될 수 없음(타입), 초과 환불·구성원 누락·완료 기간 구성원·깨끗하지 않은 구성원으로 `RefundGroup`을 만들 경로 없음, 수동 귀속을 덮지 않음, 원천 금액 변경 경로 없음. 실데이터 그림자 최종 연결 차이 0 또는 known-diffs 등재 |
| U13 | OTA↔카드 후보 탐색·쌍 검사 | U17 | U2, U3, U4, U10 | Luna → **Claude opus** | `cost-core::links::ota`. `app/ota_payments.py:1002-1670` 이관: 방향·결제 여부·금액, 가맹점 표기·승인 규칙 범위, 금액 비교·승인 차액·날짜 지연, 카드 식별·같은 날 동액·공급자 호환·보강 근거, `pair_check`(`:1492`), `search_card_candidates`(`:1542`), 사전승인 후보(`:1640-1669`). **수락:** 쌍 검사 통과·불통과가 운영 범위 합성 골든 100%(`tests/card_pipeline/test_ota_payments.py`, `test_ota_matching_defaults.py`, `test_ota_matching_refactor.py`의 입력). 후보 목록 순서와 거절 사유 코드는 맞추지 않는다. 보호 불변식: 점유된 카드(기존 수동·고정·옛 연결)를 후보로 내는 경로 없음, 방향·끝4·통화가 다른 행은 후보가 될 수 없음(속성 테스트), 카드 원천 값 변경 경로 없음. 실데이터 비교는 U14의 최종 연결에서 한다 |
| U14 | OTA M:N 배정·점유·고정 그룹 + 2차 전환 도구 | U18(+옛 U14의 연결 부분) | U11, U12, U13 | Luna → **Claude opus**(전환 지점) | `match_ota_payment_events`(`app/ota_payments.py:2408-2417`) 이관: 상태 준비·고정 그룹 검증, 반복 금액 묶음 명세·해소·배정, 정확 연결 우선 단건 배정과 모호 최적 단건, 고정 연결, 결과 조립. M:N 성분 보존(LINK-003), 부분·경합 그룹 보존(LINK-032). 기존 수동·고정·옛 포털 연결은 다시 계산하지 않고 **점유된 입력으로 읽기만** 하며, Rust는 점유되지 않은 카드·사건의 새 연결만 계산한다. 옛 포털 정확 연결 고정(`bind_legacy_portal_links` `:2420-2440`, LINK-040)과 결제일 없는 아고다 1:1 추론(`app/ota_inference.py:43`)은 헤드가 호출 경로를 확인해 어댑터 출력으로 남길 수 있으면 이 단위에서 뺀다. `publish_group`(§2.4)과 연결 생산자 설정 플래그, `docs/playbooks/core-cutover.md`의 2차 부분. **수락:** 최종 연결(쌍·상태·성분 구성)이 운영 범위 합성 골든 100%(`tests/card_pipeline/test_ota_mn_relations.py`와 U13의 입력). 보호 불변식: 한 카드 원행이 두 성분·두 사건에 점유되지 않음(LINK-028, 속성 테스트), 고정 그룹·수동 연결을 바꾸는 경로 없음, 입력에서 사라진 사건의 저장 연결도 점유 유지, 추론 연결은 정확 연결과 다른 타입(RFND-044), 묶음 일부만 게시하는 API 없음. 실데이터 그림자 최종 연결 차이 0 또는 known-diffs 등재. **운영 DB에 실행하지 않는다** |

### 7.3 순서

동시에 3~4개까지(계획 `:90`). **쌓아 올린 PR은 만들지 않는다**: 의존 단위가 main에 병합된 뒤 착수한다.

| 단계 | 단위 | 비고 |
| --- | --- | --- |
| 기반 | U1(완료), U2, U3, U4, U7 | 진행 중(§7.5). U3·U7은 U2 병합 뒤 main 위로 다시 올려 병합 |
| 판정 | U5, U10, U6, U8, U9 | U5 ← U2·U4, U10 ← U3·U4. U6·U8은 가장 늦게(Python 판정이 아직 바뀌는 영역). U13은 U10 뒤 이 단계와 나란히 시작할 수 있다 |
| 1차 전환 | U11 → C1~C3 측정 → 승인 → 1차 전환 | 전환 뒤 매일 대조(§3.3) |
| 연결 | U12, U13 → U14 → C1~C3 측정 → 승인 → 2차 전환 | U12 ← U9·U10, U14 ← U11·U12·U13 |

임계 경로는 U2 → U3 → U9 → U11(1차 전환)과 U10 → U13 → U14(2차 전환)이다. U9는 U5 → U6, U7 → U8도 기다린다.

### 7.4 검수 규칙(D-13)

| # | 규칙 |
| --- | --- |
| 1 | **전환 전 Rust PR(U2~U10)은 검수 1회**, Claude sonnet 또는 Sol(구현자와 다른 모델: Luna 구현 → Claude sonnet, Sonnet 구현 → Sol). 차단 사유는 셋뿐이다: 게이트 실패, 골든·그림자 불일치, 레포에 실제로 있는 코드가 금융 불변식을 깨는 경로. "가상의 다른 코드가 위조할 수 있다"는 차단이 아니라 후속 목록이다 |
| 2 | **Claude opus는 연결 단위(U12~U14)와 전환 지점(U11, C1~C3 측정 결과, 전환 실행)에만** 쓴다. Python 규칙 개선 묶음 PR(§4.4)은 판정·금융이므로 opus 1회 |
| 3 | **재검수는 차단 항목의 diff만** 본다. 새 지적을 더하지 않는다. 두 번째 변경 요청이 나오면 구현자를 바꾸기 전에 헤드가 수락 조건이 과한지 먼저 본다(왕복 상한 2회) |
| 4 | 검수자는 게이트를 전부 다시 돌리지 않는다. 구현자 출력 + `cargo test` 한 번. `.py`가 바뀌지 않은 PR은 Python 품질 검사를 건너뛴다 |
| 5 | 운영 사본 측정(실데이터 그림자·평가 사례)은 운영 담당(헤드)이 한 번 하고, 구현자와 검수자가 각각 다시 재지 않는다 |

### 7.5 진행 중 단위 매핑(2026-11-14)

| 옛 단위 | 새 단위 | PR | 상태 | 이 PR이 맞출 변경 |
| --- | --- | --- | --- | --- |
| U1 | U1 | #871, #872 | 병합됨 | 없음. 빈 크레이트 정리는 U2가 한다 |
| U2 | U2 | #873 | 변경 요청 2회 | 3회차 검수로 가지 않는다. `refund-issuer`·`scope-issuer` 기능, `tests/issuer_allowlist.rs`, 기능에 딸린 lib 수준 `compile_fail` 2개를 지운다. `compile_fail`은 `RefundGroup`·`OpenScope`·`TripId`·`Subject` 외부 생성 4개만 남긴다(`Default`·`From` 부재 시험 삭제). 작업공간을 `crates/core`(`cost-core`) + `crates/cli`(`costcore`)로 합친다: `crates/domain` → `crates/core/src/domain/`, 빈 크레이트(`store`·`rules`·`links`·`pipeline`·`bridge`·`jobs`·`p2`) 삭제, 발급 함수는 `pub(crate)`. 1회차 지적 2·4의 수정(금액 파손 행으로 `Decision` 생성 불가, 범위 토큰 없는 P2 판정 불가)은 유지. 재검수는 남은 차단 2건(R1 포함)이 장치 삭제로 사라졌는지 diff만, Claude sonnet 또는 Sol |
| U3 | U3 | #876 | 승인(검토서 기준), U2 위에 쌓임 | U2 병합 뒤 main 위로 다시 올린다. `crates/store` → `crates/core/src/store/` 모듈로 옮기고, U2 파일(`crates/domain/**`) 변경분을 PR에서 빼며, 임시 `ActorKind` 중복을 지우고 `domain` 모듈 타입을 쓴다. `jobs`·`budgets`·`agent_runs`·`p2_proposals` 테이블은 그대로 두고 비워 둔다(§5). 이 PR의 설계 문서 §3.2 두 줄(`manual_hold`·`auto`)은 그대로 둔다. 재검수는 이동 diff만 |
| U4 | U4 | #877 | 변경 요청 | 검수 지적 1~6만 고친다. "빠진 경계"는 U12~U14에서 추가한다고 PR 본문에 적는다. `links` 골든에서 Rust가 맞출 대상은 최종 연결(쌍·상태·묶음 구성·보류 여부)이라고 프로토콜 문서에 적는다(후보 목록·거절 사유는 출력에 남아도 비교 대상이 아님) |
| U7 | U7 | #874 | 변경 요청 | U2 병합 뒤 main 위로 다시 올려 `crates/rules/src/{dates,closed_period,open_scope}.rs` → `crates/core/src/dates/` 모듈로 옮긴다. `parse_iso`는 `YYYY-MM-DD`만 받고 그 밖은 오류로 돌려 호출부가 날짜 파손 `Protected`로 보낸다. Python 3.14 바이트 동등 구현과 그에 딸린 골든 재생성을 멈춘다. 골든은 경계일 사례(수백 건)와 비정형 입력 거부 사례만 남기고, 차등 퍼즈는 게이트에서 뺀다(`tools/core_dates_golden.py`·`tests/test_core_dates_golden.py`도 그만큼 줄인다). `OpenScope` 생성 함수는 `dates` 모듈에 두고 크레이트 밖 생성 불가 `compile_fail` 1개는 U2의 것을 유지. 한 번 재확인 후 병합 |
| U5~U9 | U5~U9 | 없음 | 미착수 | 번호와 내용 그대로, 검수만 Claude sonnet 또는 Sol |
| U10, U11 | U10 | 없음 | 미착수 | 합침 |
| U12, U13 | — | 없음 | M5로 이월 | 착수하지 않는다 |
| U14 | U11 | 없음 | 미착수 | 1차 전환(판정) 도구로 범위 축소 |
| U15, U16 | U12 | 없음 | 미착수 | 합침 |
| U17 | U13 | 없음 | 미착수 | 중간 산출물 비교 삭제 |
| U18 | U14 | 없음 | 미착수 | 2차 전환 도구 포함 |

## 8. 위험과 되돌림

| 위험 | 근거 | 대응 | 되돌림 |
| --- | --- | --- | --- |
| 재작성 회귀 | 계획 `:125` | 합성 골든·실데이터 그림자·평가 사례 3중 비교(주 게이트는 실데이터 그림자). 전환 전 운영 쓰기 없음 | 전환 전에는 되돌릴 것이 없다(`core.sqlite`만 버리면 됨) |
| 아키텍처와 언어 동시 변경 | 계획 `:125` | M3는 판정 열 7개와 1:1로 대응하는 모델에서 시작하고, 추출은 Python 유지. 연결은 D-7로 재작성하지만 최종 연결 모양(`app/partial_refund.py:202-207`)과 대사 결과 모양을 재현한 뒤에만 바꾼다. 전환을 판정·연결 두 번으로 나눠 한 번에 바뀌는 범위를 줄인다 | 전환별 설정 플래그 되돌림 |
| **연결 재작성 회귀(D-7)** — 환불 짝·OTA 대사는 금융 보호 코드이고 분량이 크다(`app/ota_payments.py` 2,455줄 중 대사 약 1,440줄 `:1002-2441`, `app/partial_refund.py` 435줄) | `SPEC.md:391`, 이 문서의 기존 권장(연결은 M3 뒤) | 연결 단위를 셋(U12~U14)으로 나누고 모두 opus 검수. 각 단위가 운영 범위 합성 골든 + 보호 불변식 타입·속성 테스트 + 최종 연결 그림자 차이 0. 과거 연결은 다시 계산하지 않고 점유 입력으로 읽는다. 2차 전환 전까지 Rust 연결은 `core.sqlite`의 `links`·`refund_groups`에만 쓰고 운영 기록·화면은 Python 연결을 계속 쓴다 | 2차 전환 전에는 되돌릴 것이 없다. 1차 전환은 연결과 무관하게 어댑터 `links`로 진행된다. 2차 전환 뒤에는 연결 생산자 플래그를 Python으로 되돌린다 |
| **판정·연결 규칙이 M3 동안 계속 바뀜** — 3분기 AI 검수 교정 185건 중 현 P1 일치 108건(58%)이고 2026-11-14에도 개선 PR 5건이 들어왔다. 연결도 RFND-029 개정과 PR #861이 들어왔다 | 과설계 검토(2026-11-14) §0, PR #855·#866~#870 본문, `docs/policy/refund.md:251-262` | D-5: 개선은 계속하되 하루 한 묶음 PR에 모으고, 그 PR이 골든을 다시 만들며 이미 이관된 영역이면 Rust 추종 변경을 함께 넣는다(§4.4). Rust는 덜 바뀌는 부분(날짜·저장·환불 짝)부터 옮기고 U6·U8은 가장 늦게 시작한다. 1차 전환 뒤 판정 개선은 Rust에 한다 | 해당 묶음 PR 되돌리기 |
| **두 연결 생산자의 불일치가 판정에 섞임** — 그림자 기간에 Python 연결과 Rust 연결이 공존 | §3.2 `links.producer` | 판정(`plan`)이 어느 생산자의 연결을 읽었는지 `shadow_runs`에 기록하고, 한 실행 안에서 두 생산자를 섞지 않는다 | 연결 트레이트를 어댑터로 되돌림 |
| **날짜 형식을 닫아 보호 행이 늘어남** — Rust는 `YYYY-MM-DD`만 받는다(U7) | D-12 | 1차 전환 전 헤드가 운영 DB에서 이 형식이 아닌 날짜 값 건수를 읽기 전용으로 한 번 센다. 있으면 그 차이를 PROC-005 근거로 `config/core-known-diffs.txt`에 올리고 원본 확인을 남긴다 | 1차 전환 플래그 되돌림 |
| 규칙집과 Python이 다른 곳 | `docs/policy/CODE_GAPS.md:8-30` | Rust는 먼저 Python을 재현하고, 규칙집 쪽으로 바꾸는 것은 known-diffs 등재 + 평가 사례 개선을 보이는 별도 PR | 해당 PR 되돌리기 |
| 고객 자료가 Git·PR·작업자에게 샘 | `SPEC.md:397` | 합성 자료만 Git, 공개값 허용 목록 검사, 보호 경로 밖 쓰기 거부, 실데이터 실행자 제한 | 노출 시 해당 커밋을 공개 전에 제거(강제 push는 하지 않는다 — 소유자 판단) |
| 구현 모델의 Rust 숙련도 | 계획 `:125` | 작은 단위, 타입 먼저(U2), 컴파일러가 막는 봉인(§2.4), 다른 모델 검수 | 두 번째 변경 요청이면 헤드가 수락 조건부터 본 뒤 다른 모델로(§7.4, 계획 `:86`) |
| 검수 왕복이 진행을 막음 — U2는 opus 변경 요청 2회, 차단 사유가 모두 발급 기능 플래그·허용 목록 스캔이었다 | #873 댓글, 과설계 검토 §0 | 크레이트 통합으로 장치 자체를 없애고, 전환 전 Rust PR은 검수 1회·차단 사유 3개·재검수는 diff만(§7.4) | — |
| 빌드 환경·디스크·빌드 시간 | `SPEC.md:335` | 도구는 설치됨(§6.2). 크레이트 통합 뒤 빌드 시간 변화는 U2 PR에 적는다 | 도구 설치 제거(소유자 승인 범위) |
| CI 결제 한도 | `SPEC.md:380` | 로컬 게이트 + 독립 검수 | — |
| 전환 뒤 두 작성자 | AGENTS.md 작성자 단일 원칙 | 전환마다 설정 플래그 하나로 Python과 Rust 중 하나만 P1 판정(2차는 연결)을 쓴다(§3.3 전환 절차) | 플래그를 Python으로 되돌림. `decision_history`·`change_log`의 변경 전 값으로 소수 행 원복, 대량이면 전환 직전 신선 백업 복원(`SPEC.md:383`) |
| 7일 대기를 없애 드문 경우를 놓침 | D-6 | 전환 뒤 배포 창마다 A↔C 대조와 B↔C 그림자, 목록 밖 차이 1건이면 즉시 되돌림(§3.3) | 플래그 되돌림 |
| 두 DB 사이 불일치 | §3.3 | `ATTACH` 단일 트랜잭션, 전환 뒤 매일 A↔C 대조 | 불일치 시 플래그 되돌림 |

## 9. 소유자 결정

2026-11-14 소유자 결정을 반영했다. "상태" 열이 결정 여부다.

| # | 결정 | 기본 제안(당초) | 상태 | 막히는 단위 |
| --- | --- | --- | --- | --- |
| D-1 | **Rust 도구 설치 승인**: `rustup`·안정판 도구 모음·Windows 링커 | 승인. MSVC 빌드 도구는 라이선스 조건 확인 후, 아니면 GNU 대상 | **결정·완료(2026-11-14).** `rustc 1.100.0` 안정판 MSVC 대상, clippy·rustfmt, 빌드 도구 `D:\BuildTools`(§6.2) | 없음 |
| D-2 | 외부 크레이트 사용 승인(crates.io 내려받기) | 목록 승인, 추가는 PR마다 검수자 확인 | **결정(2026-11-14).** 7개 승인: `rusqlite`(bundled), `serde`, `serde_json`, `thiserror`, `regex`, `sha2`, `time` + 개발용 `proptest`. 추가는 PR마다 검수자 확인(§6.1). 외부 라이브러리 수에 대한 결정이며 작업공간 크레이트 수(D-12)와 무관하다 | 없음 |
| D-3 | **병렬 작업 조직 재개**: 현 명세는 담당 1 + 최종 검수 1이며 병렬 조직을 쓰지 않는다(`SPEC.md:371-374`, `SPEC.md:409`). 또 Luna 사용 중단 결정(D26, `SPEC.md:446`)과의 관계 | 병렬 재개(동시 3~4개), Luna 사용 재개를 명세 부록에 기록 | **미결 — 사실상 결정됨.** 사용자 방침(2026-11-13: Luna 구현 → Claude 검수, Sonnet 구현 → Sol 검수, 최대 병렬)이 이미 병렬·Luna 사용을 전제하며 §7은 이를 따른다. 명세(`SPEC.md:371-374`, `:409`, `:446`)와의 문구 정리는 남아 있다 | 방침대로 진행 |
| D-4 | `core.sqlite` 별도 파일과 위치, 백업·7일 보존 대상 포함 | 승인 | **결정(2026-11-14).** 판정 데이터는 별도 파일 `D:/WebLedgerHost/data/core.sqlite`, 백업·7일 보존 대상(§3.2) | 없음 |
| D-5 | M3 동안 Python 판정·연결 코드 변경 범위 | 규칙집 개정과 CODE_GAPS 정정만 허용, 각 PR이 골든 차이를 적음(연결 코드 포함) | **결정(2026-11-14) — 당초 제안과 다름.** Python 판정 규칙 개선을 계속한다(정답률 58%인 판정을 얼려 베끼지 않는다). 하루 한 묶음 PR(평가 1회·검수 1회·배포 창 1회), Rust 합성 골든은 묶음마다 다시 만들고 이미 이관된 영역은 같은 PR에서 Rust를 추종시킨다. 1차 전환 뒤 판정 개선은 Rust에, 2차 전환 뒤 연결 개선도 Rust에 한다. 절차 §4.4 | 없음 |
| D-6 | 운영 전환 조건의 수치와 **전환 승인자**(Fable 또는 소유자) | 수치 승인, 전환은 Fable 승인 + 소유자 통보 | **조건은 결정(2026-11-14):** 전환 두 번, 조건 C1~C3(신선 스냅숏 1개 차이 0, 평가 사례 일치 감소 0, 백업·되돌림 예행), 7일 대기 없음, 전환 뒤 매일 대조·플래그 되돌림(§3.3). **승인자는 미결** | 1차·2차 전환 |
| D-7 | 연결 단계(환불 짝·OTA M:N)를 M3에서 재작성할지 | 재작성하지 않고 Python 어댑터로 둠(M3 뒤 별도 단계) | **결정(2026-11-14) — 권장안과 다름.** 환불 짝 맞추기와 OTA↔카드 연결도 M3에서 Rust로 재작성한다. §1.1 S8, §1.2, §3.1·§3.2, §7 U12~U14, §8에 반영. D-11은 이 결정을 유지한 채 연결 전환을 2차로 나눈다 | 범위 확정 |
| D-8 | 실데이터 그림자·평가 사례를 누가 실행하는가(고객 원문 접근 허용 범위 `SPEC.md:375`, `:397`) | 운영 담당 헤드 세션이 보호 경로에서 실행, 작업자에게는 집계만 | 미결(§7.4 규칙 5는 이 제안을 전제로 쓴다) | U5 이후 PR 검수(연결 단위 U12~U14 포함), 전환 |
| D-9 | M3 착수 시점: M2 종료 조건(`SPEC.md:305-308`, `docs/session_handoff.md:3`) 충족 전 착수 허용 여부 | M2 종료 선언 뒤 착수. 단 D-1 설치와 U1은 먼저 허용 | **결정(2026-11-14).** M2 종료를 기다리지 않고 즉시 착수. U1·U4 착수함 | 없음 |
| D-10 | CI에 Rust 작업 추가(결제가 풀리면 비용 증가) | 추가하되 `core/` 변경 시에만 실행 | 미결 | 없음(U1은 워크플로를 추가해 둠) |
| D-11 | **M3 범위 축소** | 과설계 검토(2026-11-14) 권장안 | **결정(2026-11-14).** 18 → 14단위: 작업 큐(옛 U12)·P2 실행기(옛 U13)는 M5로, 옛 U10+U11, 옛 U15+U16을 합침. 순서는 기반 → 판정 → 1차 전환 → 연결(2차 전환) 4단계(§7.3). 전환은 판정(1차)과 연결(2차) 두 번(§3.3) | — |
| D-12 | **수락 조건 완화** | 과설계 검토 권장안 | **결정(2026-11-14).** 작업공간 크레이트 9개 → `cost-core` + `costcore` 2개(§6.1), 봉인은 가시성(`pub(crate)`)과 비공개 필드로(§2.4). 발급 Cargo 기능·허용 목록 스캔 테스트 삭제, `compile_fail` 12개 → 핵심 4개. 날짜는 `YYYY-MM-DD`만 받고 그 밖은 보호로 닫음(Python 바이트 동등 삭제). "Python과 같음"은 운영에 실재하는 입력에서 최종 결과가 같음(§4.4). 유지: 봉인 타입, `supersede` 25칸 표, 대기 없는 `Judgement`, 실데이터 그림자 비교, `eval_cases` 평가 | — |
| D-13 | **검수 규칙** | 과설계 검토 권장안 | **결정(2026-11-14).** 전환 전 Rust PR은 Claude sonnet 또는 Sol 검수 1회, Claude opus는 연결 단위(U12~U14)와 전환 지점(U11, 전환 측정·실행)만, 재검수는 차단 항목 diff만(§7.4) | — |

## 10. 확인한 것과 하지 않은 것

- 확인: 이 문서의 `파일:줄`은 `0bdce8ca`에서 파일을 읽어 확인했다. 운영 DB는 열지 않았다.
- 2026-11-14 결정 반영: 연결 단계 근거(S8, §3.1 연결 입력, 옛 U15~U18, §8 추가 행)는 `8dcc0c06`에서 파일을 읽어 확인했다. Rust 도구 버전은 `%USERPROFILE%\.cargo\bin`의 `rustc`·`cargo clippy`·`rustfmt`·`rustup show active-toolchain` 출력으로, `D:\BuildTools`는 폴더 존재로만 확인했다.
- 2026-11-14 축소 개정: 과설계 검토서(보호 경로 밖 임시 파일, 레포 미포함)의 권장안을 옮겼다. 진행 중 PR(#873·#874·#876·#877)은 `gh pr view`의 상태와 바뀐 파일 목록으로만 확인했고 코드는 읽지 않았다. 골든 재생성 명령은 #877의 `docs/core-bridge-protocol.md`(미병합)에서 확인했다. `origin/main` `b8520f48`의 `core/crates/`에 크레이트 폴더 9개가 있음을 확인했다.
- 하지 않음: 코드 작성, 실데이터 실행, 운영 DB의 비정형 날짜 건수 확인(§8), 옛 포털 연결 고정·아고다 추론의 호출 경로 확인(U14), 크레이트 통합 뒤 빌드 시간 측정(U2), 크레이트 버전·라이선스 조사, `0bdce8ca` 기준 기존 `파일:줄`의 재확인.
