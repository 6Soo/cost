# M3 Rust 새 코어 — 착수용 설계안

> **상태:** 제안(2026-11-14). 소유자가 §9의 결정과 착수를 승인하면 §7의 작업 단위를 그대로 배정한다. 승인 전에는 코드·도구 설치를 하지 않는다.
> **근거:** [통합 명세](../SPEC.md) §10 M3(`SPEC.md:318`)·§11.1(`SPEC.md:328-335`), 계획 원문 `C:\Users\kkokk\.claude\plans\unified-chasing-muffin.md`의 D8~D11 보완 조건(`:105-130`, `:94-103`). 판정 규칙은 [판정 규칙집](../DECISION_POLICY.md)이 정본이며 이 문서는 규칙을 새로 정하지 않는다.
> **기준 SHA:** `origin/main` `0bdce8ca`. 이 문서의 `파일:줄`은 이 SHA 기준이다.

## 0. 한 줄 요약

M3는 **판정을 한 테이블(`decisions`)에 모으는 Rust 코어를 현 Python 옆에 그림자로 세우고**, 같은 입력에서 현 Python P1과 결과가 같거나 차이가 모두 설명될 때만 P1 생산자를 Rust로 바꾸는 단계다. 수집·추출·연결(환불 짝·OTA M:N)은 Python 어댑터가 계속 맡고, 화면·클라우드·Rust 추출기는 하지 않는다.

## 1. 범위와 비범위

### 1.1 M3에서 하는 것

| # | 내용 | 근거 |
| --- | --- | --- |
| S1 | 판정 모델: 판정 1건의 Rust 타입, 판정 주체 우선순위, 금융 불변식의 타입 강제 | `SPEC.md:112-131`, `SPEC.md:330` |
| S2 | 코어 저장소 `core.sqlite`: decisions·decision_history·overrides·jobs·agent_runs 등. 운영 `board.sqlite`는 읽기 전용으로 읽는다 | `SPEC.md:145`, `SPEC.md:332` |
| S3 | P1 규칙 엔진: 데이터형 규칙 표 + 현 `app/classify.py`·`app/rules.py`·`app/automatic_classification.py` 이관 | `SPEC.md:158`, 계획 `:110` |
| S4 | 파이프라인 중 **귀속·게시** 단계의 Rust 구현. 수집·추출·연결은 Python 어댑터(하위 프로세스) 호출 | `SPEC.md:318`, `SPEC.md:333` |
| S5 | 작업 큐와 P2 실행기(현 `tools/p2_batch/`의 모델 호출·검증·저널 계승) | `SPEC.md:331`, 계획 `:98-99` |
| S6 | 병행(그림자) 실행과 차이 보고, 골든 회귀, 평가 사례 재실행 | `SPEC.md:333-335` |
| S7 | 운영 전환 도구(투영 쓰기)와 전환·되돌림 절차서. **전환 실행 자체는 별도 승인** | `SPEC.md:383` |

### 1.2 M3에서 하지 않는 것

| 하지 않는 것 | 언제·누가 | 이유 |
| --- | --- | --- |
| JSON API, React 화면, Claude Design | M4 | `SPEC.md:319`, §11.2 |
| 클라우드 서버·보조 노드 분리, 원격 작업 가져오기 | M5 | `SPEC.md:320`. 단 작업 큐는 임대(lease) 구조로 만들어 M5에 그대로 쓴다(계획 `:97`) |
| Rust 추출기, Python 폐기 | M6 | `SPEC.md:321`. M3는 추출기 **기준 출력 생성**까지만 한다(§3.4) |
| 연결 단계 재작성(환불 짝 `app/partial_refund.py`, OTA M:N `app/ota_payments.py`) | M3 뒤 별도 단계(§9 결정 D-7) | 금융 보호(`SPEC.md:391`)를 다루는 코드라 재작성 위험이 가장 크다. M3는 결과를 어댑터로 읽어 `links`에 담기만 한다 |
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

- 현 Python의 `needs_review`·`rule_conflict`·`inference_conflict`·`travel_location_hold`·`booking_evidence_needed`(`app/classify.py:396-460`, `app/automatic_classification.py:53-54`)는 Rust에서 **판정 상태가 아니라 P1 내부 결과**다. P1은 이 경우에도 공통 추론으로 최선 판정(`Actor::P1Inferred`)을 내고(`app/automatic_classification.py:416-429`의 분기 기타비용 종결과 같은 뜻), 별도로 `P2Hint`를 붙여 P2 작업을 만든다. 게시 함수는 `Decision`만 받는다.
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
- 이 표 전체를 속성 기반 테스트로 고정한다(§6.3).

### 2.4 금융 불변식을 타입으로

| 불변식 | 근거 | 타입·모듈 강제 방법 |
| --- | --- | --- |
| 카드 원문·금액·부호·ID를 바꾸지 않는다 | `SPEC.md:389`, `app/rules.py:124-128` | `SourceTxn`은 읽기 전용 구조체(필드 비공개, getter만). `Decision`에는 금액·부호·승인번호 필드가 **없다**. 저장 계층의 `UPDATE` 문은 정해진 열 목록 상수에서만 만들고, 그 목록에 원천 열이 없음을 테스트로 고정한다 |
| 금액 해석 실패를 0원으로 쓰지 않는다 | `SPEC.md:389` | `Amount = Readable(KrwAmount(i64)) \| Unreadable(ParseError)`. `Unreadable`은 `Judgement::Protected`로만 간다. `Default` 구현 금지 |
| 수동 교정이 항상 우선 | `SPEC.md:390` | §2.3 `supersede`. 수동 신호(§3.1의 overrides) 판별은 한 함수에만 둔다 |
| 중복·환불 짝·초과 환불·원본 충돌 보호를 풀지 않는다 | `SPEC.md:391` | `RefundGroup`은 연결 단계 모듈 밖에서 생성 불가(생성자 비공개). 게시는 `publish_group(RefundGroup, Vec<Decision>)`로 **묶음 전체를 한 트랜잭션**에 쓰거나 아무것도 쓰지 않는다 |
| P2는 금액·부호·원승인 관계·환불 짝·새 장부 기록을 쓰지 않는다 | `SPEC.md:162`, `SPEC.md:196` | `P2Proposal`은 귀속·항목·이용기간·근거·불확실성만 가진다. `P2Proposal → Decision` 변환은 `Actor::P2`만 만들 수 있고 `Attribution::RefundPair`를 거부한다 |
| 열린 분기만 자동 교정 | `SPEC.md:203-204`, `app/classification_correction.py:18-37` | `OpenScope` 토큰은 열린 분기·열린 여행 판별 함수만 만든다. P2·AI 검수 교정 적용 함수는 이 토큰을 인자로 요구한다 |
| 여행을 만들어내지 않는다 | `SPEC.md:63` | `TripId`는 Google 탭 스냅숏(`trip_tabs`)에서 읽은 값으로만 생성된다. 문자열에서 바로 만드는 생성자 없음 |
| 규칙이 여행을 자동 배정하지 않는다(가맹점 규칙) | `app/rules.py:245-246` | 가맹점 항목 규칙의 효과 타입에 귀속 필드가 없다 |

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
| `ota-evidence.sqlite` (`app/ota_store.py:16-51`) | **직접 열지 않음.** Python 어댑터가 근거 사실을 만들어 넘긴다(`tools/complete_card_classification.py:47`) | 같음 | facts·links 입력 |

### 3.2 새 테이블 — `core.sqlite`

`SPEC.md:332`의 목표 목록을 따르되, M3에서는 **별도 파일 `core.sqlite`** 에 둔다(운영 `board.sqlite` 스키마 변경을 피하기 위해, §9 D-4). 단일 파일 통합은 Python이 퇴역하는 M6에서 한다.

| 새 테이블 | 내용 | 현 위치(대응) |
| --- | --- | --- |
| `schema_meta` | 스키마 버전, 이관 기록 | 없음 |
| `evidence` | 원본 참조: 종류, sha256, 원 위치(테이블·키). **원문 사본은 두지 않는다** | `import_batches.content_bytes`, `ota_raw_blobs` |
| `facts` | 어댑터가 낸 구조화 사실(예약 이용기간, 결제일, 예약번호 해시 등) + 생산자·Python SHA | `tools.complete_card_classification.load_review_evidence` 결과, `ota_bookings` 등 |
| `links` | 환불 짝·OTA↔카드 연결(정확/추론 구분, 상태 full/partial/excess) | `app/partial_refund.py:99` `refund_links`, `ota_review_*` |
| `trips` | `trip_tabs` 스냅숏(읽은 시각·digest) | `trip_tabs` |
| `decisions` | 거래당 현재 `Judgement` 1행(§2) | `transactions` 판정 열 7개 |
| `decision_history` | 판정 변경 전후 값·주체·요청 ID | `change_log`의 `card.*` 종류들, `board_revisions` |
| `overrides` | 수동 교정·사용자 예외 | `review_decisions`, `board_manual_overrides`, `decided_at`, 수동 출처 값 |
| `rules_builtin` | 코드에 박혀 있던 규칙의 데이터판(§4.1) | `app/classify.py:49-101`, `:417-442`, `app/automatic_classification.py:114-134` |
| `jobs`, `budgets` | 작업 큐·일일 예산(§5) | `D:/WebLedgerHost/data/p2-incremental.json`(`tools/p2_batch/run_incremental.py:24`) |
| `agent_runs`, `p2_proposals` | P2 실행 기록·검증된 제안 | 같은 저널, 보호 경로의 `proposals.jsonl` |
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

### 3.3 병행 실행과 운영 전환

**그림자 실행(M3 전 기간).**

1. 입력 고정: 운영 DB를 `mode=ro`로 짧게 읽어 스냅숏 digest를 만든다. 실데이터 대조는 보호 경로(`D:/WebLedgerHost/data/backups/` 아래, Git 밖)의 신선 백업 사본에서 한다.
2. 같은 사본에 대해 세 값을 얻는다.
   - **A. 현재 저장값**: `transactions` 판정 열.
   - **B. Python 재판정**: `app.automatic_classification.plan`(`:457-544`)과 `app.classify.classify_transaction`(`:120-208`)을 Python 다리(§4.3)로 실행한 결과.
   - **C. Rust 재판정**: 코어의 P1.
3. 비교는 B↔C가 회귀 판정, A↔C는 참고(전환 시 실제로 바뀔 행 수)다. 결과는 `shadow_diffs`에 **유형 키**(필드, 이전 출처, 항목 전환 어휘, 귀속 종류 전환)와 건수로만 남긴다. 유형 키는 `tools/quarter_review/eval_cases.py:117-146`의 허용 목록 방식(`validate_public`)을 그대로 따른다. 거래 ID·금액·가맹점은 보호 경로의 비공개 파일에만 둔다(`SPEC.md:397`).
4. 설명된 차이는 `config/core-known-diffs.txt`에 유형 키와 근거(규칙집 ID 또는 `docs/policy/CODE_GAPS.md`의 줄)로 적는다. 형식과 운영은 `config/known-test-failures.txt:1-3`과 같다: **목록 밖 차이 1건이라도 있으면 실패, 목록에 있지만 사라진 차이는 '해소됨'으로 보고하고 줄을 지운다.**
   - 예: CODE_GAPS의 TRIP-044(겹치는 해외 여행의 사용 국가, `docs/policy/CODE_GAPS.md:13`)처럼 **규칙집이 맞고 Python이 틀린** 곳을 Rust가 규칙집대로 구현하면 B↔C 차이가 생긴다. 이 차이는 해당 규칙 ID와 함께 목록에 올리고, 평가 사례(§4.4)에서 Rust가 더 맞음을 보여야 한다.

**운영 전환 조건**(모두 충족, 판단은 §9 D-6의 승인자).

| # | 조건 |
| --- | --- |
| T1 | 합성 골든(§4.4) 100% 일치, `cargo test`·`cargo clippy -D warnings` 통과 |
| T2 | 실데이터 그림자 실행에서 B↔C의 목록 밖 차이 0건. **7일 이상 간격의 서로 다른 스냅숏 2개**에서 연속 충족 |
| T3 | 평가 사례 재실행(§4.4)에서 Rust의 일치 건수 ≥ Python, 그리고 Python이 맞힌 사례 중 Rust가 틀린 것 0건 |
| T4 | 투영 쓰기(§7 U14) 동등성: 같은 대상에 대해 Rust 투영 쓰기와 `app.automatic_classification.apply`(`:547-614`)가 DB 사본에 남기는 변경이 행·열 단위로 같다 |
| T5 | 신선 백업·복원 확인(`SPEC.md:383`)과 되돌림 예행(§8) 완료 |
| T6 | 전환 동안 같은 DB에 판정 쓰기를 하는 작성자는 하나: Python 자동 분류 경로를 설정 플래그로 끄고 Rust만 쓴다(AGENTS.md "같은 파일·DB·배포의 작성자는 하나다") |

**전환 뒤.** 현 화면은 계속 `transactions` 판정 열을 읽는다. Rust는 `decisions`에 먼저 쓰고 같은 트랜잭션 안에서 투영 쓰기로 `transactions`·`ledger_entries`·`board_rows`를 맞춘다. 두 DB 사이의 원자성은 SQLite `ATTACH` 단일 트랜잭션으로 얻는다(같은 연결에서 `core.sqlite`와 `board.sqlite`를 함께 연다).

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

**Python 다리.** Rust는 Python을 라이브러리로 부르지 않고 `python -I -m tools.core_bridge <명령>`을 하위 프로세스로 부른다. 표준 입출력은 JSON Lines, 각 응답에 `python_sha`(git HEAD)와 입력 digest를 담는다. 명령: `snapshot`(입력 투영 읽기), `facts`(근거 사실), `links`(환불·OTA 연결), `plan`(골든 B 생산), `extract`(§3.4). 다리는 읽기 전용이며 운영 DB를 `mode=ro`로만 연다.

### 4.4 골든 회귀와 평가 사례

| 층 | 무엇과 비교 | 어디에 | 게이트 |
| --- | --- | --- | --- |
| 합성 골든 | 현 Python 함수 출력(B)을 합성 입력에 대해 만든 JSONL | `core/golden/synthetic/` (Git, 고객 자료 없음) | 모든 PR, 100% 일치 |
| 실데이터 그림자 | 신선 백업 사본의 B↔C | 보호 경로 | 규칙 엔진 PR은 헤드가 실행해 집계만 PR에 붙임. 전환 조건 T2 |
| 평가 사례 | AI 검수자 교정(정답) ↔ C | 보호 경로 | 전환 조건 T3, 규칙 개정마다 |

- **합성 골든 생산:** 현 판정 테스트(`webapp/tests/test_classification_rules.py`, `webapp/tests/test_automatic_classification_completion.py`, `webapp/tests/test_automatic_plan_refactor.py`, `tests/test_classify_regression_failures.py`, `tests/card_pipeline/test_merchant_family_classify.py`, `tests/card_pipeline/test_guide_airfare_classify.py` 등)의 합성 입력과, 내장 규칙 표에서 만든 조합 입력을 Python 다리로 돌려 기대 출력을 고정한다. 기대값은 Python이 낸 값이며 손으로 고치지 않는다. Python 판정 코드가 바뀌면 골든을 다시 만들고 그 PR에 차이 유형을 적는다.
- **PR #855 `eval_cases.py` 활용:** `tools/quarter_review/eval_cases.py`는 AI 검수 교정(`change_log` `card.ai_review_corrected`, `:31`)을 사례로 모으고, 교정된 행을 새로 수입된 상태로 되돌린 뒤(`FRESH`, `:67-68`, `:179-186`) 현재 P1 `plan`으로 재판정해 MATCH/MISMATCH/ITEM_NOT_REEVALUATED/NOT_REJUDGED로 센다(`:201-248`). M3는 여기에 **재판정기 선택**을 더한다: `--planner python|rust`. `rust`는 메모리 사본 대신 보호 경로의 임시 파일 사본을 만들어 `costcore plan`에 넘긴다(`_cases_dir`의 보호 경로 검사 `:251-259` 재사용). 두 실행의 사례별 결과를 비교해 T3을 판정한다. 사례 파일·출력의 공개값 허용 목록(`:134-146`)은 그대로 둔다.
- **`config/known-test-failures.txt` 활용:** (1) M3의 Python 쪽 변경(다리, `eval_cases.py` 옵션)은 이 목록 밖 실패를 만들면 안 된다(`tools/run_quality_checks.py:361`). (2) Rust 쪽은 알려진 실패 목록을 두지 않는다 — 새 코어는 처음부터 녹색이다(계획 `:148`). (3) 같은 형식을 `config/core-known-diffs.txt`(§3.3)에 차용한다.

## 5. 작업 큐와 P2 실행기

### 5.1 작업 큐

```sql
CREATE TABLE jobs (
  job_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,            -- p1.rejudge | p2.layer1 | p2.layer2 | eval.cases | shadow.run | adapter.extract
  dedupe_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,    -- 식별값만. 고객 원문은 보호 경로 파일 참조
  state TEXT NOT NULL,           -- queued | leased | succeeded | failed | dead
  priority INTEGER NOT NULL DEFAULT 0,
  not_before TEXT NOT NULL,
  lease_owner TEXT, lease_until TEXT,
  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
  last_error_code TEXT,
  budget_key TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE budgets (budget_key TEXT, day TEXT, used INTEGER NOT NULL, limit_calls INTEGER NOT NULL,
                      PRIMARY KEY (budget_key, day));
```

- **임대.** 실행자는 `lease_until`이 지난 작업만 가져간다. 현 파일 잠금의 "죽은 PID·2시간 초과 잠금 자동 인수"(`tools/p2_batch/README.md:23`, `tools/p2_batch/run_incremental.py:26`, `:73-115`)를 임대 만료로 대체한다. M5에서 보조 노드가 같은 테이블을 HTTPS로 임대하게 된다(계획 `:97`).
- **예산·한도.** 호출 상한(기본 최대 30묶음·모델 1회, `tools/p2_batch/README.md:21`)과 일일 예산은 `budgets`로 센다. 실패 호출도 상한에 포함한다(같은 줄). 구독 한도를 개발 세션과 공유하므로(계획 `:118`) 한도 오류는 `not_before`를 미뤄 다음 회차로 넘긴다.
- **P1 먼저.** P2 작업이 밀려도 P1 판정은 먼저 게시된다(계획 `:98`).
- **상태 요약.** `costcore status --json`이 현 공개 요약(`tools/p2_batch/run_incremental.py:25`, `:42-58`)과 같은 필드(실행별 성공/실패 집계, 실패 사유 코드)를 낸다. 상태 화면(`SPEC.md:303`)은 이 파일을 읽는다.

### 5.2 P2 실행기 인터페이스

```rust
pub trait P2Runner {
    fn run(&self, request: &P2Request) -> Result<P2RawAnswer, P2Error>;
}
pub struct P2Request {
    pub kind: P2Kind,              // Layer1Merchants | Layer2Case
    pub run_id: RunId,
    pub request_digest: Sha256,    // 입력 JSON의 정렬 직렬화 sha256 (layer1.py:176)
    pub prompt: String,            // 신뢰하지 않는 자료 경고 + 자료 JSON (layer1.py:178-186)
    pub output_schema: serde_json::Value,
    pub timeout: Duration,         // 기본 240초 (layer1.py:195)
}
```

| 구현 | 쓰임 |
| --- | --- |
| `CodexExec` | 운영. 현 명령과 같은 인자: `exec --ignore-user-config --ignore-rules --strict-config --ephemeral --skip-git-repo-check --sandbox read-only --model <M> --output-schema <파일> --json ... -c model_reasoning_effort="medium" -` (`tools/p2_batch/layer1.py:190-192`). 빈 임시 cwd, stdin으로 자료 전달(`SPEC.md:186`). 소유 프로세스 시간 제한·종료는 `_run_bounded`(`app/connected_agent_provider.py:127`)와 같은 Windows 작업 개체 방식 |
| `Replay` | 테스트. 기록된 합성 응답을 돌려준다. **테스트에서 실제 모델을 부르지 않는다** |
| (예약) `Paseo`, 과금 API | 계획 D9의 Paseo 경로(`:116`)와 이식성 조건(`:120`)을 위한 자리. M3에서 구현하지 않는다 |

**검증은 실행기 밖의 한 함수**가 한다(현 `layer1.validate`, `tools/p2_batch/layer1.py:148-168`와 같은 오류 코드): 요청 digest·run_id 결속, 대상 누락·중복, 허용 항목, 확신 값, 근거 길이 600자, 개인 식별값 패턴. 이벤트 스트림에서 도구 실행이 보이면 결과를 거부한다(`app/frontier_agent_provider.py:78`, `SPEC.md:187`).

**재시도 분류**(`tools/p2_batch/README.md:36`): 용량·형식 오류는 최대 3회, 30/60초 간격. 인증·도구 실행 오류는 즉시 중단(작업 `dead`, 상태 화면에 표시). 완료 묶음은 요청 digest가 같을 때만 재사용한다.

**대상 선정 계승.** 열린 분기·보호 사유 판정은 `tools/p2_batch/scope.py:81-148`의 순서와 사유 코드(`COMPLETED_PERIOD`, `CLOSED_QUARTER_REVIEW_REQUIRED`, `PROJECTION_ATTRIBUTION_DISAGREEMENT`, `manual`, `PARSE_ERROR`, `DUPLICATE_OR_CONFLICT`, `CANCELLATION_OR_REFUND`, `REVIEW_HOLD`, `COMPANY_EXCLUDED`, `ORIGINAL_WITH_REFUND`)를 그대로 Rust로 옮기고, 같은 투영에서 같은 대상·같은 사유 건수가 나오는지 골든으로 비교한다. 단계 2 정리(`tools/p2_batch/layer1.py:29-94`, `SPEC.md:198`)도 모델 재호출 없는 후처리로 옮긴다.

**반영 경로.** M3 동안 P2 제안의 운영 반영은 **현 Python 경로를 그대로 쓴다**(인증 API의 교정 경로·미리보기 digest·요청당 50행, `tools/p2_batch/README.md:25`, `app/classification_correction.py:46-186`). Rust 실행기는 검증된 제안을 `p2_proposals`에 쓰고, 다리 명령으로 기존 반영 단계에 넘긴다. 새 쓰기 경로를 만들지 않는다. 운영 전환(§3.3) 뒤에는 `supersede`(§2.3)와 `OpenScope`(§2.4)를 거쳐 코어가 직접 반영한다.

## 6. 크레이트·빌드·테스트 게이트

### 6.1 구성

```
core/                       Cargo 작업공간 (레포 안, 새 폴더)
  Cargo.toml  rust-toolchain.toml  clippy.toml
  crates/
    domain/    cost-domain    판정 타입·우선순위·불변식. 외부 의존: serde 계열만
    store/     cost-store     core.sqlite 스키마·이관, board.sqlite 읽기 전용 투영, 투영 쓰기
    rules/     cost-rules     규칙 표 형식·정규화·평가·내장 규칙 적재
    pipeline/  cost-pipeline  귀속 단계(P1 조립), 그림자 실행, 차이 집계
    jobs/      cost-jobs      작업 큐·임대·예산
    p2/        cost-p2        P2Runner, CodexExec, Replay, 검증
    bridge/    cost-bridge    Python 하위 프로세스 프로토콜
    cli/       costcore       실행 파일: shadow | plan | eval | worker --once | status | migrate
  rules/builtin/*.json      내장 규칙(§4.1)
  golden/synthetic/*.jsonl  합성 골든(§4.4)
tools/core_bridge/          Python 다리(읽기 전용)
```

- 의존 방향: `domain` ← `rules` ← `pipeline`; `domain` ← `store`, `jobs`, `p2`; `cli`만 전부를 안다. `domain`은 DB·프로세스·네트워크를 모른다.
- 외부 크레이트 후보(§9 D-2 승인 대상): `rusqlite`(bundled), `serde`·`serde_json`, `thiserror`, `regex`, `sha2`, `time`, 개발용 `proptest`. JSON 스키마 검증은 출력 스키마가 작으므로 직접 구현을 우선한다.
- 운영 포트 8751·8752·8790을 쓰지 않는다(`SPEC.md:396`). M3의 코어는 서버를 띄우지 않는다.

### 6.2 빌드 전제

- 이 PC에는 Rust 도구가 없다(`SPEC.md:335`, 계획 `:129`). 설치 대상은 `rustup` + 안정판 도구 모음 + Windows용 링커(MSVC 빌드 도구 또는 GNU 대상). 무엇을 쓸지와 버전 고정은 §9 D-1에서 정한다.
- 작업 폴더(worktree)마다 `target/`이 생기면 디스크를 크게 쓴다. 공용 `CARGO_TARGET_DIR`을 쓸지는 착수 때 디스크 여유를 보고 정한다. 이 PC가 감당할 병렬 빌드 수는 아직 모른다(계획 `:92`) — U1에서 측정한다.

### 6.3 게이트

| 게이트 | 명령 | 언제 |
| --- | --- | --- |
| 형식 | `cargo fmt --all --check` | 모든 Rust PR |
| 정적 검사 | `cargo clippy --workspace --all-targets -- -D warnings` | 모든 Rust PR |
| 테스트 | `cargo test --workspace` (합성 골든 포함) | 모든 Rust PR |
| 속성 테스트 | §2.3 우선순위 표, §2.4 불변식(원천 열 미변경, 묶음 원자성, 0원 금지) | `domain`·`store` 변경 |
| Python 영향 | `python tools/run_quality_checks.py --base origin/main --run` — `known-test-failures.txt` 밖 실패 0 | Python 다리·`eval_cases.py` 변경 |
| 실데이터 그림자 | `costcore shadow` → 목록 밖 차이 0, 집계만 PR에 | 규칙 엔진 PR(헤드 실행), 전환 |
| 평가 사례 | `python -m tools.quarter_review.eval_cases eval --planner rust` | 전환, 규칙 개정 |

- **CI 결제 한도.** CI가 시작되지 못하는 동안(`SPEC.md:380`) 위 명령의 **로컬 실행 출력**을 PR에 붙이고, 다른 모델 세션이 최종 SHA를 검수·승인한 PR만 병합한다. 실제 검사 실패는 이 예외로 통과시키지 않는다. U1에서 `.github/workflows/quality.yml`에 Rust 작업을 추가해 두되(결제가 풀리면 바로 돈다), 지금의 게이트는 로컬 실행이다.
- `tools/run_quality_checks.py`가 `core/` 변경을 감지하면 위 cargo 명령을 함께 돌리도록 U1에서 연결한다.
- 작업자가 테스트나 골든 기대값을 고쳐 통과시키지 않는다(`SPEC.md:379`). 골든 재생성은 Python 판정 코드가 바뀐 PR에서만 하고 차이 유형을 적는다.

## 7. 작업 분할

14개 단위. 각 단위는 PR 하나이며, 위 게이트와 아래 수락 조건을 모두 만족해야 병합한다. 권장 모델은 사용자 방침(Luna 구현 → Claude 검수, Sonnet 구현 → Sol 검수)과 위험도별 검수 기준(판정·금융·운영 자료는 Claude opus 검수)을 따랐다. 고객 원문은 어느 작업자에게도 주지 않는다: 모든 단위는 합성 자료로 개발하고, 실데이터 그림자·평가 사례 실행은 원문 접근이 허용된 실행자(`SPEC.md:375`, `:397`)가 하며 PR에는 집계만 남긴다.

| ID | 단위 | 의존 | 권장 구현 → 검수 | 수락 조건 |
| --- | --- | --- | --- | --- |
| U1 | 작업공간 골격·게이트 | §9 D-1·D-2 승인 | Sonnet → Sol | `core/` 작업공간과 8개 빈 크레이트, 도구 모음 고정, fmt·clippy·test 녹색, `run_quality_checks.py`가 `core/` 변경 시 cargo 실행, `quality.yml`에 Rust 작업 추가, `.gitignore`에 `target/`. 빌드 시간·디스크·병렬 빌드 수 측정값을 PR에 기록 |
| U2 | 판정 도메인 타입 | U1 | Luna → Claude opus | §2의 타입 전부. `supersede` 표(§2.3)의 25칸 전부를 테스트로 고정. `Amount::Unreadable`이 `Decision`이 될 수 없음, `RefundGroup`·`TripId`·`OpenScope` 외부 생성 불가를 컴파일 실패 테스트(`trybuild` 또는 문서 테스트)로 고정 |
| U3 | 저장 계층 | U2 | Luna → Claude opus | `core.sqlite` 스키마(§3.2)와 이관 번호. `board.sqlite` 읽기 전용 투영이 `mode=ro`·`query_only`·짧은 트랜잭션으로 `scope.read_projection`(`tools/p2_batch/scope.py:26-54`)과 같은 열을 읽음. 출처 대응표(§3.2) 전 값 매핑 테스트. 쓰기 열 목록에 원천 열이 없음을 테스트로 고정 |
| U4 | Python 다리·합성 골든 생산기 | U1(프로토콜 문서만) | Sonnet → Sol | `tools/core_bridge`의 `snapshot`·`facts`·`links`·`plan`·`extract` 명령(읽기 전용, `python -I`). 기존 판정 테스트의 합성 입력과 조합 입력으로 `core/golden/synthetic/` 생성. 고객 자료가 골든에 들어가지 않음을 검사하는 테스트. Python 품질 검사 목록 밖 실패 0 |
| U5 | 규칙 표 형식·엔진 1단계 | U2, U4 | Luna → Claude opus | §4.1 형식, `normalize_rule`과 같은 거부 조건·오류 코드, `rule_matches` 이관, 내장 패턴·업종·skyticket 데이터화(§4.3 순서 1~3). `_classify_transaction` 합성 골든(여행 해석기 없음) 100% 일치. 운영 규칙 211개가 오류 없이 적재됨(헤드가 집계 확인) |
| U6 | 사용자 예외·추론 배정 데이터화 | U5 | Luna → Claude opus | 후쿠타케·3820 싱가포르·3820 잔여·추론 배정 출처 우선(§4.2 stage 60)을 `owner_exception`·`inferred_assignment` 규칙으로. 각 규칙에 `DECISION_POLICY.md` §5의 ID. `classify_transaction` 합성 골든 100% |
| U7 | 날짜·분기·완료 기간·열린 범위 | U2 | Sonnet → Sol | `quarter_costs`, `closed_period`(`app/closed_period.py:11-66`), `reconciliation` 날짜 함수(`app/reconciliation.py:27-104`), `_open_p2_tab`(`app/classification_correction.py:18-37`)의 Rust판과 `OpenScope` 생성. 경계일(2025 전체, 2026Q1, 2026-06-30) 골든 100% |
| U8 | 여행 귀속 추론 | U7, U4 | Luna → Claude opus | `infer_trip`·`card_trip_candidates`·`trip_selection`·`stay_trip` 이관. 동률 고정 순서(`app/automatic_classification.py:166-169`) 재현. 합성 골든 100%. CODE_GAPS의 TRIP-044 등 규칙집과 다른 곳은 Python 동작을 재현하고 차이 후보로 표시만 한다(바꾸는 것은 U9 이후 별도 PR + known-diffs 등재) |
| U9 | P1 계획 조립·보호 | U3, U5, U6, U8 | Luna → Claude opus | `plan` 이관: 보호 순서(`app/automatic_classification.py:479-502`), 이력 복원, 신규 판정, 어댑터 `links`·`facts` 사용, digest. 결과는 `Judgement`이며 정상 거래에 `Decided` 외 값이 없음. `plan` 합성 골든 100% |
| U10 | 그림자 실행·차이 보고 | U3, U4 (엔진은 U9 전까지 대역) | Sonnet → Sol | `costcore shadow`: A·B·C 세 값, 유형 키 집계, 허용 목록 검사(`eval_cases.validate_public` 방식), `config/core-known-diffs.txt` 형식과 판정(목록 밖 1건이면 실패, 해소 보고). 비공개 파일은 보호 경로 밖에 쓰면 거부 |
| U11 | 평가 사례 재실행 연결 | U9, U10 | Sonnet → Sol | `eval_cases.py`에 `--planner rust`, 사례별 Python/Rust 비교 출력(공개값 허용 목록 유지). 기존 `tests/test_quarter_review_eval_cases.py` 통과 + 새 합성 사례 테스트 |
| U12 | 작업 큐 | U3 | Sonnet → Sol | §5.1 테이블, 중복 방지, 임대·만료 인수, 재시도 지연, 일일 예산, `costcore worker --once`, `status --json`이 현 공개 요약 필드와 같음. 동시 실행자 2개 테스트에서 같은 작업 이중 실행 0 |
| U13 | P2 실행기 | U2, U12 | Luna → Claude opus | `P2Runner`·`CodexExec`·`Replay`, 검증 함수가 `layer1.validate`와 같은 입력에 같은 오류 코드, 같은 요청에 같은 digest(합성 골든), 도구 이벤트 거부, 시간 초과 시 프로세스 트리 종료, 재시도 분류. `scope.select`와 같은 대상·사유 건수(합성). 테스트에서 실제 모델 호출 0 |
| U14 | 투영 쓰기·전환 도구·절차서 | U9, U3 | Luna → Claude opus | `apply`와 같은 쓰기(행 revision 결속, 장부 행 빈 칸만 채움, 화면 행 payload·이력, change_log)와 미리보기 digest. 합성 DB에서 Python `apply`와 결과 DB 차이 0(T4). 설정 플래그로 작성자 전환·되돌림. `docs/playbooks/core-cutover.md`(전환·되돌림·백업 확인 절차). **운영 DB에 실행하지 않는다** |

**병렬 순서.** 동시에 3~4개까지(계획 `:90`).

| 물결 | 단위 | 비고 |
| --- | --- | --- |
| 0 | U1 | 소유자 승인 직후 |
| 1 | U2, U4 | 서로 독립 |
| 2 | U3, U5, U7 | U2 뒤 |
| 3 | U6, U8, U10, U12 | |
| 4 | U9, U13 | |
| 5 | U11, U14 | 그 뒤 전환 조건 T1~T6 측정 → 전환 승인 요청 |

같은 파일을 두 단위가 고치지 않게 크레이트 단위로 소유권을 나눈다. 공유 계약(U2의 타입, U4의 다리 프로토콜)이 바뀌면 그 단위의 후속 PR로만 고친다.

## 8. 위험과 되돌림

| 위험 | 근거 | 대응 | 되돌림 |
| --- | --- | --- | --- |
| 재작성 회귀 | 계획 `:125` | 합성 골든·실데이터 그림자·평가 사례 3중 비교. 전환 전 운영 쓰기 없음 | 전환 전에는 되돌릴 것이 없다(`core.sqlite`만 버리면 됨) |
| 아키텍처와 언어 동시 변경 | 계획 `:125` | M3는 판정 열 7개와 1:1로 대응하는 모델에서 시작하고, 연결·추출은 Python 유지 | — |
| M3 동안 Python P1이 계속 바뀜(골든이 움직임) | `docs/session_handoff.md:6` 진행 중 작업 | 다리 출력에 `python_sha`를 담고 골든을 SHA마다 다시 만든다. 판정 코드 변경 PR은 골든 차이 유형을 적는다. §9 D-5 | — |
| 규칙집과 Python이 다른 곳 | `docs/policy/CODE_GAPS.md:8-30` | Rust는 먼저 Python을 재현하고, 규칙집 쪽으로 바꾸는 것은 known-diffs 등재 + 평가 사례 개선을 보이는 별도 PR | 해당 PR 되돌리기 |
| 고객 자료가 Git·PR·작업자에게 샘 | `SPEC.md:397` | 합성 자료만 Git, 공개값 허용 목록 검사, 보호 경로 밖 쓰기 거부, 실데이터 실행자 제한 | 노출 시 해당 커밋을 공개 전에 제거(강제 push는 하지 않는다 — 소유자 판단) |
| 구현 모델의 Rust 숙련도 | 계획 `:125` | 작은 단위, 타입 먼저(U2), 컴파일 실패 테스트, 다른 모델 검수 | 두 번 반려되면 다른 모델로(계획 `:86`) |
| 빌드 환경·디스크·빌드 시간 | `SPEC.md:335` | U1에서 측정 후 병렬 수 조정 | 도구 설치 제거(소유자 승인 범위) |
| CI 결제 한도 | `SPEC.md:380` | 로컬 게이트 + 독립 검수 | — |
| 구독 한도 공유·대화형 로그온 의존 | 계획 `:118-119` | 예산·지연 재시도, 인증 오류 즉시 중단과 상태 표시 | 실행기 작업 중지(큐 `state=dead`) |
| 전환 뒤 두 작성자 | AGENTS.md 작성자 단일 원칙 | 설정 플래그 하나로 Python 자동 분류와 Rust 중 하나만 쓴다(T6) | 플래그를 Python으로 되돌림. `decision_history`·`change_log`의 변경 전 값으로 소수 행 원복, 대량이면 전환 직전 신선 백업 복원(`SPEC.md:383`) |
| 두 DB 사이 불일치 | §3.3 | `ATTACH` 단일 트랜잭션, 전환 뒤 매일 A↔C 대조 | 불일치 시 플래그 되돌림 |

## 9. 소유자 결정이 필요한 것

| # | 결정 | 기본 제안 | 막히는 단위 |
| --- | --- | --- | --- |
| D-1 | **Rust 도구 설치 승인**: `rustup`·안정판 도구 모음·Windows 링커(MSVC 빌드 도구 또는 GNU 대상) 설치 | 승인. MSVC 빌드 도구는 라이선스 조건 확인 후, 아니면 GNU 대상 | U1(전부) |
| D-2 | 외부 크레이트 사용 승인(crates.io 내려받기, §6.1 후보 목록) | 목록 승인, 추가는 PR마다 검수자 확인 | U1 |
| D-3 | **병렬 작업 조직 재개**: 현 명세는 담당 1 + 최종 검수 1이며 병렬 조직을 쓰지 않는다(`SPEC.md:371-374`, `SPEC.md:409`). §7의 분할은 병렬 배정을 전제한다. 또 Luna 사용 중단 결정(D26, `SPEC.md:446`)과 2026-11-13 방침(Luna 구현 → Claude 검수)의 관계 확인 | 병렬 재개(동시 3~4개), Luna 사용 재개를 명세 부록에 기록 | 물결 1 이후 |
| D-4 | `core.sqlite` 별도 파일과 위치(`D:/WebLedgerHost/data/core.sqlite`), 백업·7일 보존 대상 포함 | 승인 | U3 |
| D-5 | M3 동안 Python P1 판정 코드 변경 범위 | 규칙집 개정과 CODE_GAPS 정정만 허용, 각 PR이 골든 차이를 적음 | U5~U9 |
| D-6 | 운영 전환 조건 T1~T6의 수치(스냅숏 2개·7일 간격 등)와 **전환 승인자**(Fable 또는 소유자) | 수치 승인, 전환은 Fable 승인 + 소유자 통보 | 전환 |
| D-7 | 연결 단계(환불 짝·OTA M:N)를 M3에서 재작성하지 않고 Python 어댑터로 둠 | 승인. 재작성은 M3 뒤 별도 단계로 다시 계획 | 범위 |
| D-8 | 실데이터 그림자·평가 사례를 누가 실행하는가(고객 원문 접근 허용 범위 `SPEC.md:375`, `:397`) | 운영 담당 헤드 세션이 보호 경로에서 실행, 작업자에게는 집계만 | U5 이후 PR 검수, 전환 |
| D-9 | M3 착수 시점: M2 종료 조건(`SPEC.md:305-308`, `docs/session_handoff.md:3`) 충족 전 착수 허용 여부 | M2 종료 선언 뒤 착수. 단 D-1 설치와 U1은 M2 운영 작업과 겹치지 않으므로 먼저 허용 | 전체 |
| D-10 | CI에 Rust 작업 추가(결제가 풀리면 비용 증가) | 추가하되 `core/` 변경 시에만 실행 | U1 |

## 10. 확인한 것과 하지 않은 것

- 확인: 이 문서의 `파일:줄`은 `0bdce8ca`에서 파일을 읽어 확인했다. 운영 DB는 열지 않았다.
- 하지 않음: 코드·도구 설치, 실데이터 실행, 빌드 시간·디스크 측정(U1에서 측정), 크레이트 버전·라이선스 조사(D-2 때 확인), MSVC 빌드 도구 라이선스 확인(D-1 때 확인).
