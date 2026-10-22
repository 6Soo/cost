# COST V3 구현 명세 — 추론 우선배정·사후 AI 대화학습·항공권 참가자·N:M 대사·테스트 독립화

> **2026-10-23 사용자 최신 우선 규칙.** 실행 대상: `6Soo/cost`; 참가자 원장과 예약 API 수정 대상: `6Soo/reservation`.  
> **우선순위:** 이 문서의 *여행 귀속 추론 정책*은 COST 문서·코드의 종전 「낮은 추론이면 미배정/HOLD」와 충돌하는 범위에서 최신 사용자 요구로 우선한다. 반면 금액·취소·환불·원본 오류·중복·인증·고객 신원과 관련한 안전 조건은 그대로 유지한다.  
> **구현/배포 상태:** 이 문서는 후속 구현을 위한 상세 설계이며 A·대화학습·아키텍처 개편은 아직 운영 적용된 기능이 아니다. 이번 브랜치의 B 변경은 `app/ota_payments.py` 숫자 동일성 버그와 표적 테스트 3개. 테스트 실행·배포 사실을 별도로 확인할 것.  
> **개발 원칙:** 무료 모델/코딩 에이전트가 독립적으로 구현 가능하도록 코드 경로, 데이터 계약, 알고리즘, 사례, 테스트, 단계별 완료 기준을 고정한다. 실제 개인정보를 모델에 제공하지 않는다.

## 1. 제품 목표와 절대적인 사용자 경험

### 1.1 기존 HOLD 중심에서 「배정→수정→질문→학습」으로 전환

새 최상위 업무 순서:

1. 원본 카드 매입·여행·예약 증거를 수집한다. 원본 오류, 실제 중복, 환불·취소 상태는 먼저 검사한다.
2. 회계상 실제 비용이면서 시스템이 유효한 여행 후보를 **하나 이상** 갖고 있다면, 증거가 약해도 **최선의 후보 여행 1개로 자동 배정**한다. 예: 가장 개연성 높은 A. 근거/점수/불확실성을 숨기지 않고 기록하되 화면에서 미배정 더미로 몰지 않는다.
3. 사용자는 **여행 A 화면에 들어가서 개별 결제 행을 여행 B로 즉시 옮긴다.** 사용자가 이동을 저장하는 데 AI 응답·규칙 작성·질문 답변은 필요 없다. 화면은 이동 직후 B에 즉시 표시한다.
4. 시스템은 사용자 변경을 **원본을 덮어쓰지 않는 수동 귀속 결정**으로 보존한다. 이후 자동 재수집·재분류·AI 추론은 이 결정에 우선하지 못한다.
5. 비동기 AI 작업이 `A→B` 변경을 발견하고 해당 행의 **대화형 사후 학습 스레드**를 연다. “왜 이 비용을 B로 이동했나요?”에 대해 **예상 답변 1**, **예상 답변 2**, **직접 입력 3**을 제공한다.
6. 사용자는 1·2를 고르거나 3에 자유롭게 작성한다. AI는 기존 예약·여행·카드 근거 및 사용자 설명을 다시 살펴 **재사용 규칙의 초안**을 생성한다. 일반화에 꼭 필요한 조건이 부족하면 추가 질문을 할 수 있다.
7. AI는 조건·효과·적용 범위(이 거래만/향후/기존 미확정 포함)·예상 영향 건수/금액·충돌 예시를 보여 준다. **사용자 승인 시** 규칙을 활성화한다. 이전에 수동 이동한 거래는 이후 학습 규칙으로 재배정하지 않는다.
8. 대화가 지연·중단·모델 실패·오프라인이더라도 사용자 이동은 유지한다. “학습 보류”이지 “여행 이동 취소”가 아니다.

사용자가 COST 웹사이트에서 AI와 다회차로 문답하고, 예외를 교정해, 미래 자동 분류의 품질을 높이는 것이 **핵심 제품 흐름**이다. 불필요한 장시간 대사 조사·전체 재학습·전수 회귀가 한 행 이동을 차단해서는 안 된다.

### 1.2 사용자가 실제로 보게 될 화면 사례

여행 A > 지출 > `트립닷컴 89,000원` (시스템 자동 배정, 추론 낮음; 단서: 카드 사용일 9/21, B 여행 9/20~9/24, A 여행 9/19~9/22) > **[여행 이동]** > B 선택 > **[저장]**.

즉시: A 목록에서 제거, B 목록에 추가, 원거래 금액/날짜/ID·비용 항목 유지, 상단에 “내가 B로 이동” 표시, 이전 귀속과 이동 시각 및 근거 보존. 이미 Google에 붙여넣은 행인지 모호하면 **재복사/중복 기록 경고**를 별도로 표시하되 **COST의 표시·검토 귀속 이동 자체는 유지**한다. 실제 Google 시트는 자동 변경하지 않는다.

AI 인앱 대화:
- AI: “이 지출을 A에서 B로 이동한 이유가 무엇인가요?”
- 선택지 1: “B 여행의 실제 이용기간/예약번호에 해당하는 결제예요.”
- 선택지 2: “B 여행의 대장·가이드 업무 경비이며 A는 날짜가 우연히 겹친 거예요.”
- 선택지 3: “직접 설명하기” (자유 텍스트 + 전송)
- 사용자: 3 선택, “B 여행을 위해 하루 전 예약한 숙박이고 체크아웃은 B 시작일이에요.”
- AI: “그럼 B의 준비 숙박에 해당하나요? (예/아니오/추가 설명)” — **조건이 부족할 때만** 질문.
- AI: “규칙 초안: 검증된 숙박 체크아웃이 B 여행 시작일 이하이고 중간에 다른 여행의 숙박 기간과 겹치지 않을 때 B에 우선 귀속; 현재/향후 후보 4건 영향 예상. [미리보기] [적용 승인] [이번 건만] [취소].”

선택지 1·2는 **모델이 현재 거래의 실제 근거를 기반으로 동적으로 생성하는 예상 설명**이다. 사용자 확정 이전에는 단지 제안이며 AI 답변이 실제 사실인 양 저장하면 안 된다. 하나의 고정 템플릿을 모든 거래에 반복 제시하는 구현은 미완료로 본다. 선택지 자체에 근거가 부족하면 “예약번호를 확인했나요?” 같은 검증 질문을 분기할 수 있다.

## 2. 여행 자동 귀속: 낮은 추론도 적용하는 구체 알고리즘

### 2.1 상태와 권위의 분리

**회계 검증 상태**와 **여행 귀속 상태**를 독립적인 축으로 취급한다:

- `financial_eligibility`: `VALID_EXPENSE | REFUND_PENDING | DUPLICATE | CONFLICT | EXCLUDED | UNVERIFIED`
- `assignment_status`: `AUTO_EVIDENCED | AUTO_INFERRED | USER_ASSIGNED | NEEDS_CANDIDATE | NO_TRIP_AUTHORITY`
- `confidence`: `high | medium | low` + 선택 근거·경쟁 후보·규칙 버전·증거 지문.
- `ledger_export_status`: `READY | REVIEW_REQUIRED | ALREADY_COPIED | POSTED_UNKNOWN` — 귀속 상태와 혼동 금지.

**중요:** 유효한 여행 후보가 존재하고 회계 원본이 유효하면 `low`여도 `AUTO_INFERRED`로 A에 붙인다. `HOLD` 또는 `unclassified`를 기본 출력으로 쓰지 않는다. 반대로 **존재하지 않는 여행**을 만들거나 고객 신원을 추측해 생성하는 건 금지다. 여행 authority 자체가 전혀 없으면 `NO_TRIP_AUTHORITY`; 후보가 0개면 `NEEDS_CANDIDATE`로 남긴다. 이는 ‘낮은 추론이니 HOLD’와 다른 상태다.

### 2.2 추천이 아닌 실제 배정

우선순위(높음→낮음):
1. 사용자가 그 **거래 ID에 대해 직접 이동/귀속**한 `USER_ASSIGNED` (해제/수정은 사용자만).
2. 그 거래에 대한 다른 명시적 사용자 확정·기존 수동 예외.
3. 실제 예약번호·결제 근거·서비스 이용기간·검증된 여행일과 일치하는 정확 귀속.
4. 사용자 승인 재사용 규칙.
5. 후보 여행의 이용기간 중복/가까운 시작·종료/실제 이동 경로/담당자/기존 같은 업체의 결정 사례 등 검증 가능한 특징을 사용한 점수 기반 추론.

후보 점수 함수는 순수 함수 `rank_trip_candidates(transaction, evidence, authoritative_trips, approved_rules)`로 분리한다. 날짜 겹침·이용기간·여행 담당자·유사 과거 결정 등 **사용된 신호 목록과 가중치 버전**을 결과에 포함한다. 기존 여행 종료일 공식·OTA 이용기간 우선·준비 숙박 특례는 재사용한다. 숫자 점수는 제품 정책이지 신원/예약의 증명이 아니다. 점수가 동률이거나 격차가 극히 작아도 (1) 근거를 비교하고 (2) 일관된 타이브레이커로 후보 한 개를 골라 **AUTO_INFERRED/low**로 표시한다. 동일한 입력이면 순서에 상관없이 동일한 결과가 나와야 한다. 특정 여행에 돈이 부족하다는 이유만으로 금액을 재분배하는 새 정책은 만들지 않는다.

**회계 무결성은 추론 강행의 예외다:** 중복 여부 불명, 미확정 취소/환불 짝, 금액 충돌, 파싱 오류, 다른 거래에 예약이 이미 고정된 상황은 비용 기록 보호를 계속한다. 추론 여행 표시는 가능해도 **불확실한 실제 금액을 Google 확정 지출로 자동 반영하는 행동은 금지**한다. 한 거래가 사용자 이동으로 여행 B에 들어가더라도 원본 카드 거래/환불은 보존한다.

### 2.3 이동의 저장 계약

- 엔드포인트(설계안): `PATCH /api/expense-assignments/{transaction_id}`; 요청 `{target_trip_id, expected_revision, client_request_id}`.
- 서버 검사: owner 권한, same-origin/CSRF, 비용 거래 ID 실존, 대상이 authoritative 여행이고 수동 이동 가능, 현재 revision 일치, 중복 요청 ID 검사.
- 한 SQLite 트랜잭션 안에서 `expense_assignment_decisions`에 `transaction_id` 유일 결정, `assignment_audit`에 `from_trip_id,to_trip_id,source='user',actor,revision,created_at,reason_status='pending_ai'`를 저장한다. 카드 raw transactions를 수정하지 않는다.
- `client_request_id` 중복 호출은 기존 동일 결과를 돌리고 다른 페이로드 재사용은 오류. 충돌/오류 시 전부 rollback.
- 사용자 수동 이동 후 `posthoc_learning_jobs` 큐에 idempotent 작업 한 건을 생성한다. **AI 실행과 네트워크 호출은 커밋 바깥에서 수행**한다.
- 사용자 다시 B→C 이동 시 이전 학습 작업은 기록으로 남기되 *현재 이동 사유를 대표하지 않도록* superseded 처리한다. 대화의 원거래와 각 revision은 보존한다.
- 기존 `webapp/ledger_store.py` revision/수동 override 구조와 `webapp/card_flow.py`의 실제 카드 귀속 저장 경로를 조사 후 하나의 정본 write path에 붙인다. 별도 조용한 경쟁 작성자를 만들지 않는다.
- Google은 최종 장부이며 COST에서 자동 쓰지 않는다. Google 반영/마감 거래의 충돌 경고를 표시하되 가짜로 Google이 수정됐다고 표시하지 않는다.

## 3. 웹 내 AI 대화·규칙 학습: 무료 모델용 완전 계약

### 3.1 기존 코드 재사용 (새 프레임워크 금지)

- `webapp/dialog_turn.py`: 기존 provider-neutral 다회차/회복·대기·fallback 정책과 대화 ID 계약 조사.
- `webapp/provider_transport.py`, `webapp/provider_config.py`: 서버 지정 프로바이더만 허용. 클라이언트가 URL·모델·키 임의 결정 금지.
- `webapp/rule_text.py`, `app/rule_proposals.py`, `webapp/classification_rules.py`: 구조화 제안/허용 스키마/미리보기/충돌 검사/승인 재사용. `app/rule_proposals.py`는 고정 패턴의 결정론적 파서이므로 다회차 자연어 이해를 그 정규식 몇 개로 대체했다고 주장하지 않는다.
- `webapp/ledger_store.py`: 승인·revision·audit/idempotency. 기존 규칙의 source key는 불변 카드 근거이고 설명 문구 수정은 조건으로 쓰지 않는다.
- `webapp/card_actions.py`, `webapp/real_review_ui.py`, `webapp/card_flow.py`: 실제 카드 행에서 여행 이동과 사후 질문으로 들어가는 UI.
- 기존에 실제 프로바이더 연결이 구성되지 않았다면 **대화 메시지와 사용자 이동은 로컬에 안전하게 보존하고 AI는 대기**. 합성 모델 결과를 실제 AI 응답으로 보고 금지.

### 3.2 스레드·메시지·규칙안 데이터

`assignment_conversations`: `conversation_id PK, transaction_id, originating_audit_id, origin_revision, state(open|awaiting_user|awaiting_ai|draft_ready|applied|superseded|closed), created_at, updated_at`.  
`assignment_messages`: `message_id PK, conversation_id, turn_index, role(user|assistant|system), kind(question|suggested_option|user_answer|followup|draft_preview|error), body, provider_attempt_id nullable, created_at`. 개인 정보/비밀은 외부 모델로 전달 전 제거하며 저장 DB에는 기존 개인정보 최소화 정책 적용.  
`assignment_rule_drafts`: `draft_id PK, conversation_id, based_on_revision, conditions_json, effects_json, applicability, evidence_digest, state, created_at`.

API 설계(기존 중복 API가 있으면 확장하되 최종 계약을 하나만 선택):
- `GET /api/assignment-conversations?transaction_id=...` — 기존 스레드와 미답 질문, 불필요한 재질문 금지.
- `POST /api/assignment-conversations/{id}/answers` — `{choice:'option_1'|'option_2'|'custom', answer_text?, expected_turn, client_request_id}`. 3인 경우 `answer_text` 필수. 서버에서 제공한 선택지만 유효. 예상 답변 1·2라도 사용자가 선택하기 전에는 사용자 확정 취급 금지.
- `POST /api/assignment-conversations/{id}/retry` — 명시적 재시도/대기 해제; 같은 턴 이중 적용 금지.
- `GET /api/assignment-conversations/{id}/draft` — 현재 규칙 초안·근거·충돌·적용 대상 개수·총액(서버 계산)·영향받을 여행 목록·미확정/기존 사용자 확정 제외 건수.
- `POST /api/assignment-rule-drafts/{id}/approve` — owner 인증·revision 및 evidence hash 확인 후 기존 규칙 승인 경로 사용. AI 텍스트·모델 추정 영향 수치를 그대로 쓰지 않는다.

### 3.3 에이전트 입력/출력의 최소 JSON 계약

서버→모델은 원문 카드번호·고객명·연락처·예약번호·메모를 제외하고 `{conversation_id, transaction_pseudonym, assignment_from, assignment_to, candidate_trip_windows, relative_payment_day, merchant_category, expense_category, validated_evidence_flags, existing_rule_summaries, allowed_effects, previous_qa}` 정도로 **최소화**. 이름이나 원 예약번호를 넣지 않아도 판단 가능한지 우선 검토한다. 공개 무료 API로 비식별 전 거래 원문을 전송하지 않는다. 모델은 승인 없는 다른 API/DB에 접근 불가.

모델→서버는 *allowlist JSON*:
```json
{
  "kind": "question | rule_draft | no_safe_generalization",
  "question": "왜 B에 해당하나요?",
  "suggestions": [
    {"id": "option_1", "text": "이용기간이 B와 맞기 때문"},
    {"id": "option_2", "text": "B 대장 경비이기 때문"}
  ],
  "followup_needed": false,
  "missing_facts": [],
  "draft": {
    "conditions": {"merchant_normalized": "example"},
    "effects": {"display_tab_id": "trip-B"},
    "applicability": "future"
  },
  "explanation": "..."
}
```
- 서버가 `kind`·`suggestions` 정확히 2개·유효한 조건과 효과·여행 정본·메시지 크기·중복/무한 루프를 검증한다. 검증 실패는 *대기/재질문* 처리; AI 내용을 곧바로 SQL/코드로 실행 금지.
- 질문은 원인 설명의 필수 조건이 불명확할 때만 추가하며 최대 회차 제한(예: 3회, 설정으로 변경)과 “모르겠음/이번 거래만/나중에” 종료를 제공한다.
- 같은 거래 이동은 **1회 사용자 답변을 받으면 가능하면 곧바로 초안**을 제안한다. 추가질문을 이유로 사용자가 이미 저장한 B 배정을 대기 상태로 변경 금지.
- 대화 컨텍스트는 DB의 원본 Q/A가 정본; 요약은 캐시이며 요약이 없어져도 대화를 복원한다. 모델 내부 숨겨진 CoT를 저장·연속 유지한다고 주장하지 않는다.
- 미래 적용 규칙의 효과는 분류/여행/설명만. 금액·날짜·카드 원문·개인정보·고객 연결은 불변. AI가 생성한 규칙이 다른 수동 귀속과 충돌할 경우 수동 귀속 우선.
- 승인 뒤에도 모델이 나중에 재추론한 결과로 사용자가 지정한 B를 되돌릴 수 없다. 사용자 단일 거래 귀속의 취소/변경은 명시적 UI 동작으로만 가능.

### 3.4 AI 제공자 비용과 장애

기존 프로바이더 계약을 우선 사용하고 실제 설정 가능한 무료 모델만 별도로 확인한다. 모델 교체/무료 할당량 실패는 메시지 **queued/waiting**으로 유지한다. 유료 API 자동 업그레이드·제3자 비밀 전송 금지. 재시도할 때 같은 `conversation_id`, `origin_revision`, `expected_turn`을 보내 늦은 응답이 새 결정에 덮어쓰지 못한다. 질문 1·2는 모델 출력으로 제안하고, UI의 옵션 3은 언제나 서버에서 제공하는 사용자 자유입력 버튼이다.

## 4. A — 항공권 영문 탑승자→한글 이름 및 실제 해당 여행 참가자 등록

### 4.1 반드시 구분하는 세 가지 사실

1. *영문명 추출*: 서명 검증된 항공권/전자항공권/예약 발권 문서에 `KIM/JI WON`이 등장한다. 이는 해당 문서에 이름이 있다는 증거다.
2. *한글명·고객 동일성*: 영문 표기로 한글 이름을 단정할 수 없다. `KIM JI WON`은 김지원/김지원을 비롯해 다양한 후보를 만든다. 영→한 음차만으로 `customers` 특정 인물 또는 `reservations`의 신원을 **확정 금지**.
3. *실제 여행 참가/탑승*: 항공권 발권 사실은 실제 항공편 탑승 또는 여행 참여 완료의 증거가 아니다. **COST UI에서 추정 참가자로 우선 연결**할 수는 있지만 ‘실제 탑승 확인’ 상태는 추가 원천 사실(여행 참가 확인, 가이드 명단의 확인, 탑승 근거 등)이 있을 때만 확정한다.

사용자 목적은 사람이 영문명을 일일이 등록하지 않고 최대한 자동화하며, 나중에 UI에서 잘못 연결된 사람·여행을 쉽게 고치는 것이다. 이 목표를 *추정/확정의 표시를 분리하는 방식*으로 구현한다.

### 4.2 검증한 현재 연동 구조

`reservation/src/app/api/internal/roster/route.ts`는 `travel_ins`의 보험 가입 참가자 확정 자료용이며 `travel_insurance=1`을 설정하고 예약을 만들므로 항공권 전용 호출에 사용하지 않는다.  
`reservation/src/app/api/internal/customers/route.ts`는 주민번호가 포함될 수 있으므로 항공권 추론에 사용하지 않는다.  
`reservation/src/lib/customerDb.ts`의 기존 `normalizeEn`(공백·하이픈 제거/소문자화), `reservation/src/app/api/internal/guides/route.ts`의 가이드 `flight_name_en`, `src/app/api/admin/customer-match-queue/route.ts`의 기존 수동 고객 후보 검토 개념을 재사용한다.

### 4.3 권장 구현 단계

**A0 — 읽기 전용 발견 및 원본 인덱스.** COST `app/flight_evidence.py`와 `app/ota_mail.py` 등의 검증된 발권/여정에서 탑승자 `passenger_name_en`, 예약/티켓 출처 SHA, 예약 날짜/이용 날짜/노선/탑승자 수/운임의 근거를 추출한다. 서로 다른 탑승자와 중복 메일을 구분한다. 전처리 `NFKC`, 대소문자·구두점·슬래시·공백 정리, `SURNAME/GIVEN MIDDLE`을 분리한 뒤 원문도 보존. 미승인 텍스트/본문만 있는 증거는 참가자 확정에 사용 금지.

**A1 — 권위 참가자 후보 조회.** reservation에 **새 read-only 내부 엔드포인트** `GET /api/internal/passenger-candidates?tourFldid=...` (설계안)를 구현한다. `INTERNAL_API_TOKEN` 인증·최소 필드만 허용; 해당 여행의 취소되지 않은 `reservations` 대표자/복호화한 companions의 **표시명·영문명·예약/동행인 opaque ref**와 가이드의 별도 `guide_id`만 제공한다. 주민번호, 전화, 계좌, 암호문, 토큰, 전체 고객 데이터 반환 금지. 리턴 형식 `{tour_id, source_revision, candidates:[{kind:'lead'|'companion'|'guide',reference_id,name_kr,name_en?,status}]}`. 실제 컬럼 존재/권한을 소스에서 검증 후 조정한다. 고객 동일성 보강을 위한 기존 전사 원장 조회도 안전한 내부 API에 **동일 최소 필드**로 추가할 수 있으나 다른 여행의 고객 개인정보를 대량 유출하지 않는다.

**A2 — 우선 매칭/음차.** 다음 근거 우선순위: (a) 기존 예약 대표자/동행인의 정확 영문명 + 해당 여행 ID + 유일한 고객 ref, (b) 기존 `flight_name_en`이 유일하게 같은 가이드 + 그 여행 실제 담당 근거, (c) 이미 사용자 검증을 거친 영→한 별칭 사전, (d) 국문 이름과 영문명의 발음 후보 + 동일 여행의 다른 근거, (e) 로컬 음차/무료 AI가 제안한 2~3개 한글 표기. 단계 (d),(e)는 **추정**, 확정된 실제 신원이 아니다. 비교 시 성/이름 역순, 공백/하이픈, 음절 분리, 외국 국적 이름, 동명이인 처리. 단순 문자열 유사도 1등이라는 이유로 기존 사람을 잘못 덮어쓰지 않는다.

**A3 — 여행 귀속은 최대 자동화.** 항공권 여정/여행의 authoritative 일정/공항/담당자를 기준으로 최선 여행 하나를 `AUTO_INFERRED`로 선택하고 낮은 신뢰도도 그 여행의 *추정 참가자* 영역에 나타내되 후보/근거를 보존. 여행 후보 0이면 참조할 여행이 없음을 표시한다. 직원/대장/일반 참가자 구분은 분리한다. 인원이 다수인 한 장의 예약은 탑승자별 별도 연결 후보를 생성하되 실제 예약·카드 비용을 임의 인원수로 분할하지 않는다.

**A4 — 쓰기 분리.** COST에는 `flight_passenger_candidates` 및 `passenger_trip_assignments`(원천 SHA + 승객키 + 여행키의 idempotent 키, status, source_revision, evidence digest) 테이블/조회 UI를 추가하고, **reservation 정본에 자동 신규 예약을 만들기 전에** 새 내부 API `POST /api/internal/flight-passenger-links` (설계안)를 설계한다. 인증 + revision + 독립 idempotency + user provenance를 요구. **정확한 기존 reservation 참조가 검증된 경우에만** 실제 고객 연결/영문명 보완; 단지 음차만 있는 경우 reservation `reservations`에 임의 실명 고객/신규 예약 생성 금지, *provisional passenger* 별도 테이블에 적재. provisional은 실제 참가 확인 전에도 내부 여행별 명단에서 보이며 수정할 수 있다. 확정/해제는 owner 동작 또는 권위 참가 확인 근거로만. `travel_insurance`, `payment_status`, `customer_id`, RRN 등 다른 예약 업무 필드 불변. 취소된 여행/항공권/예약은 자동 확정 제외.

**A5 — 교정 후 학습.** “이 탑승자는 김지원, 여행 B의 실제 고객이다”라는 owner 이동/신원 선택은 `USER_ASSIGNED` 기록 후 사후 AI 스레드에 넣는다. AI가 “왜 B 여행 참가자인가?” 근거 옵션 1/2/3을 만들고 다음에 재사용할 **영문명 별칭/해당 고객/여행 귀속 규칙**의 후보를 만든다. *동일 영문명=영원히 동일 한글 고객* 같은 전역 규칙은 동명이인 위험이 있어 source-scoped 또는 확인된 customer ID에만 적용한다. 다른 여행의 고객 레코드를 조용히 병합 금지.

### 4.4 A의 최소 인수 테스트

- 유효한 영문명 + 같은 여행의 유일한 확인된 영어 이름 → 정확한 기존 참가자에 매칭, 신규 예약 0.
- `LEE MIN SU` 여러 명·음차 표기 상충 → 여행 추정 참가자는 표시하지만 **고객 확정 연결/병합 0**, 확인 UI 노출.
- 발권 전/취소 예약·서명 없는 메일 → 확정 참가자 생성 0.
- 대장/가이드 정확 이름 → 가이드 후보로 표시, 고객 손님과 중복 삽입 0.
- 동일 메일·발권 원본 재처리 3회 → 후보/예약/감사 이력 멱등, 중복 0.
- 원본 승객 수 3·카드 일괄 결제 1 → 승객 후보 3 / 카드 비용 원본 1.
- API 무토큰/잘못된 role/CSRF → 거부; 응답·로그에 개인정보·원문·RRN 미노출.
- A 사용자 강제 B 이동 후 새 수집 → B 유지, 대화 큐가 지연돼도 B 유지.
- 예약의 여행·고객 ref·원천 SHA 변경 → stale 재검토, 구 연결 조용한 재해석 금지.

## 5. B — 같은 금액 N:M 거래 자동 대사

### 5.1 현행 기능과 이번 코드 보완

기존에 `app/ota_payments.match_ota_payment_events`는 결제 이벤트 및 카드 거래들의 전역 후보 그래프를 구성해 최대수 매칭, 반복금액 그룹을 안정 정렬하며 **N개 OTA 이벤트 = M개 실제 카드 원행**이면 자동 매칭한다. `app/ota_portal._identical_group_matches`에도 유사 수량 대사 경로가 존재한다. 중복 기능을 세 번째 모듈로 재구현하지 않는다.

**이번 수정:** `_event_group_signature`가 `30000`과 `30000.00`을 문자열이 다르다는 이유로 다른 그룹으로 나누던 오류를 `Decimal`의 유효 양수/무반올림 정규형으로 고쳤다. `NaN`, `Infinity`, 0, 음수, 잘못된 문자는 동등 금액으로 인식하지 않는다. 함께 추가한 표적 테스트: 2:2 다르게 표시된 동등 금액/입력 순서 독립성, 2:3 보류, 숫자 이상치.

### 5.2 개별 신원 증명과 수량 정합성을 혼동하지 않음

- 예: OTA 예약 A/B가 각각 50,000원이고 카드 매입도 실제 서로 다른 승인 원행 2건이 각각 50,000원이면 **2:2 유효 수량 매칭**이다. 원행 2건을 하나로 합치지 않고 한 건씩 기록한다.
- 개별 예약번호↔카드 승인번호 연결 근거가 없다면 정렬을 통한 출력은 *회계상 수량 대응*이지 *고유 예약 결제의 정밀 증명*이 아니다. `individual_payment_evidence=false`와 후보 그룹 식별자/근거를 남기고 각 예약 고유 사실을 창작하지 않는다.
- 2 OTA : 3 카드 또는 3 OTA : 2 카드면 총액이 우연히 같더라도 누락/중복 가능성이 있으므로 그룹 상태 `HOLD_PARTIAL_GROUP`. 고유 연결할 증거가 있는 일부 행은 그 증거의 유효성에 따라 별도 확정하지만 나머지는 자동 임의 흡수하지 않는다.
- 카드 원행이 원래 두 장인데 **동일 파일 재업로드**로 두 줄씩 보이는 것은 2건 결제가 아니므로 `duplicate_of`를 제외한 고유 실거래 수만 센다.
- 결제일·통화·카드 issuer/끝4·가맹점 확인·명시 금액/승인된 할인 차이·정확 결제 여부 등 필수 간선 유효성은 유지한다. 다른 여행이거나 서비스 이용기간이 충돌하면 **카드 대응은 그룹으로 유지하되 여행 배정은 2절 추론 규칙에 따라 별개 결정**. 예약 단위 사실을 확정이라고 위장 금지.
- **환불**은 `app/partial_refund.py`의 독립된 구매↔취소 결제 방향/금액/기간 및 원본 보존 계약을 따른다. 구매 N:M 규칙을 같은 날 발생한 환불 2건에 임의 적용하지 말고 분리 테스트로 확장한다. 전액/부분 환불·해외 환율 차액 원문 수정 금지.
- 스냅샷·기존 사용자가 고정한 그룹·이미 기록한 거래를 재정렬하지 않는다. 그룹 구성원/카드 승인번호/결제일이 변하면 `HOLD_GROUP_CHANGED`를 유지한다.

### 5.3 표적 테스트와 완료 기준

`tests/card_pipeline/test_ota_payments.py`의 새 테스트 3개 + 기존 `test_ota_payments.py` 관련 그룹 테스트 + `test_portal_identical_bookings.py`·`test_same_day_lodging_group.py` 중 변경 영향 범위만 1회. 테스트 선택 예: `python -m pytest -q tests/card_pipeline/test_ota_payments.py -k "repeated_nm"`. 프로덕션 데이터 연결 없이 합성 fixture 사용. 테스트가 실패하면 변경한 기능과 관련된 실패만 고치고 무관한 전체 대사/운영 백업을 반복하지 않는다. 검증 미실행 시 "테스트 완료"라고 쓰지 않는다.

## 6. 구조 개편 — 테스트 실행 범위를 줄이는 것이 목적

### 6.1 현재 문제

대형 `webapp/card_flow.py`, `webapp/ledger_store.py`, `webapp/ledger_board.py`에 서로 다른 책임과 부수효과가 집중돼 있어 단순 UI/규칙 변경의 영향 범위가 불명확해진다. 업무 분류·자동 여행 추론·사후 학습 대화·증거 대사·장부 쓰기·Google 읽기를 분리하지 않으면 작은 수정마다 전체 DB/브라우저/OTA 재수집 검증이 유혹이 된다.

**목표는 테스트 개수를 무조건 줄이는 것이 아니라 변경 영향 경계를 좁히는 것**이다. 실제 회계 금액/원본/사용자 확정/환불/보안의 보호를 제거하지 않는다.

### 6.2 최소 변경 중심 모듈 경계(안)

```text
raw adapters: card / mail / ota / receipt     [입력 파서만; 외부 side-effect 경계]
    ↓ immutable source facts, evidence digest
domain/reconciliation (순수 함수)              [동일 실거래, 수량/환불 보호]
    ↓ candidate facts
domain/trip_ranker (순수 함수)                 [고/중/저 모두 실제 여행 우선배정]
    ↓ AssignmentProposal + trace
domain/manual_override (검증 + 유일 write)    [사용자 이동만 우선 확정]
    ↓ immutable audit + async job
domain/learning_conversation (상태 전이)       [1/2/3 대화, Q/A, 컨텍스트]
    ↓ allowlist draft
domain/rules (순수 함수 + 승인 경계)           [미리보기, 승인 적용]
    ↓
app service orchestration                     [트랜잭션, idempotency, auth]
    ├─ web ui                                 [A/B 여행 목록, move, chat]
    ├─ google read-only projection            [정본 금액 조회와 복사 상태 확인]
    └─ reservation gateway (typed boundary)  [참가자 후보, 최소 신원 API]
```

기존 모듈을 한 번에 이름 변경/전면 재작성 금지. 이미 쓰이는 `app/ota_payments.py`와 `app/reconciliation.py` 등은 기능별로 얇은 인터페이스를 내고 **새 기능이 필요한 경계만 추출**한다. 단일 작성자, 분리된 도메인 순수 함수, 버전된 입출력 DTO를 우선한다.

### 6.3 변경 영향→필수 테스트 매트릭스

| 변경 부위 | 기본 필수 검사(합성·표적) | 추가 검사 조건 |
| --- | --- | --- |
| 문서, 카피, CSS | diff/문구·해당 UI 확인 1회 | 회계·API 불변이면 DB 검사 금지 |
| 영어/한글 이름 정규화 | A 이름 정규화 단위 테스트 | reservation 쓰기 adapter 변경 시 예약 연동 테스트 |
| 순수 여행 후보 점수 | ranker fixture + tie-break/override 테스트 | 쓰기/실장부 연결 시 귀속 write contract |
| 수동 여행 이동 | 수정 전·후 revision/idempotency/우선권 테스트 | 장부 기록·Google 복사 영향 시 해당 boundary 계약 |
| AI 질문 UI | 1/2/3 + 추가 질문 + late response 테스트 | provider transport 변경 시 재시도/비밀 차단 계약 |
| 규칙 초안/승인 | allowlist·영향/충돌·규칙 버전 검사 | 대량 적용·금액/예약 자료 건드리는 수정은 차단+필수 보호 검사 |
| OTA 금액 정규화 | 반복결제 그룹 매칭 표적 테스트 | graph/scoring 변경 시 OTA 그룹 E2E 합성 |
| 환불 기록·원거래 identity | 구매↔취소·원자성·중복 방지 계약 | 배포 전 보호 기준선 + 운영 원본 불변 검증 |
| Google 읽기/확정 장부 | 읽기 projection + Google 정본 충돌 검사 | 실제 권한/수식/금액 영향 시 권한·금액 보호 |
| 인증/쓰기 권한 | owner/거부/CSRF/idempotency | 프로덕션 배포 시 보안 스모크 |

**테스트 선택을 자동화할 구현:** `config/test-impact-map.json`에 파일 globs→테스트 그룹 맵을 선언하고 `tools/select_targeted_tests.py`가 `git diff --name-only BASE...HEAD` 결과로 해당 표적 목록을 출력. glob이 없거나 변경 파일을 분류 못하면 "테스트 없음=통과"가 아니라 `UNKNOWN_IMPACT`로 보고 관련 하위 시스템 계약 검사를 1회 추가. 기존 성공 결과는 기준 SHA·변경 집합이 유효한 경우 재사용한다. 테스트를 통과한 SHA와 배포 SHA를 분리하지 않는다.

추가 과제: 각 순수 함수 경계에 1) 스키마/불변조건 단위 테스트, 2) SQLite 임시 DB 쓰기 계약 테스트, 3) 원본 읽기·외부 API 계약 테스트만 둔다. 실예약/실카드 데이터 대사, 전체 브라우저 테스트, 서버 재시작, 실Google 권한 검사는 구조상 해당 boundary를 변경한 때만 시행한다. 평가 지표: **표적 테스트 wall-clock, 변경당 실행된 통합 경계 수, 100건 자동 귀속 후 사람이 수정한 건수**.

### 6.4 작업을 분리하는 최소 PR 제안

- PR-A1: reservation 읽기 전용 탑승자 후보 API + 합성 신원 테스트.
- PR-A2: COST 탑승자 정규화·근거 인덱스/음차 후보·추정 참가 UI(기존 장부 무수정).
- PR-A3: reservation provisional link API 및 승인된 정확 신원만 확정·idempotency.
- PR-C1: `trip_ranker` 순수 함수 + 최신 low-confidence 배정 정책.
- PR-C2: owner 거래 이동 저장 + 즉시 목록 변경 + 오버라이드 감사.
- PR-C3: async 사후 AI 대화 1/2/3 + 추가 질문 + 규칙 초안/승인, 기존 provider 모듈 재사용.
- PR-T1: 테스트 임팩트 매핑 및 도메인 경계 추출(기존 기능 보존). 장부 엔진 대규모 일괄 리팩터링 금지.
- PR-B: OTA 2:2 반복 결제 숫자 동일성 버그픽스/표적 테스트(이번 브랜치). 간선 정책·기존 환불 기능 불변.

## 7. 무료 모델/코딩 에이전트 실행 절차 (절대 멈추지 않고 안전한 부분만 진행)

1. **DISCOVER:** 해당 repo `main`과 작업 브랜치 SHA, `git status`, 위 0절 파일, 관련 API·테스트를 실제로 읽고 결과를 짧게 기록한다. 이미 구현된 기능을 다시 만들지 않는다. 현재 사용자 checkout의 dirty 파일/기존 stash/운영 데이터 수정 금지.
2. **CONTRACT FIRST:** 기능별 DTO/오류코드·SQL 테이블·idempotency·오버라이드 우선순위·테스트 사례를 최소 파일로 명세한다. 미정 원본 필드명은 실제 DB schema 확인 후만 고른다.
3. **IMPLEMENT VERTICAL SLICE:** 최소 사용 가능 한 경로(예: A→B 이동 + 사후대화 1회)를 먼저 완성. 로그인·실AI·실데이터가 없어도 합성 스텁 테스트 가능하지만 실제 완성이라고 보고 금지.
4. **TARGETED TEST:** 그 기능의 표적 테스트 + 바뀐 안전 경계만 1회. 재현된 문제 없는 전체 테스트/전수 OTA 재계산 반복 금지.
5. **REVIEW:** 안전한 변경인지, 기존 사용자 지정·기록·원문을 덮지 않는지 diff에서 검증. 명세·실행 결과·미검증/보류 분리.
6. **COMMIT/PR:** 작은 PR, 파일 소유권 분리. 메인 자동 병합·운영 릴리스·Google 쓰기·예약 실제 신원 확정은 별도 배포 권한/검증 없이 하지 않는다.
7. **NEXT:** 다른 안전한 세부 구현으로 계속. 모델이 모호한 판단을 못 하면 **그 판단만** pending/provisional 처리하고 나머지 경로를 실제 작동하게 구현한다.

## 8. 종합 인수 조건 — 사용자 중심 KPI

- 실제 유효 여행 후보가 있는 카드 비용 100건: **낮은 신뢰도까지 여행 배정 후 표시**되며, 미배정 0건이 목표(단 권위 여행 후보 전혀 없음·원본/환불 보호 예외는 따로 집계).
- 사용자는 여행 A에서 개별 결제건을 B로 이동하는 데 **단 한 번의 저장**만 필요하고, API/AI 실패 이후에도 B에 머무른다.
- 이동 후 AI가 이유 예상 **두 가지 + 사용자의 직접 답안 1개**를 노출하고, 추가질문·규칙 미리보기/승인 및 규칙 재활용이 웹 안에서 완결된다.
- 사용자가 B를 지정했다면 어떤 백그라운드 처리도 B를 A로 되돌릴 수 없고 기존 원금·이용일·결제 ID도 바뀌지 않는다.
- 이름 변환은 후보 제안을 최대한 자동화하되 기존 예약·탑승객의 신원을 함부로 합치지 않으며, 실제 참가 확정 여부와 추정 연결을 명확히 구분한다.
- 동일 실결제 두 건 + 동액 예약 두 건은 2:2 수량 대사하되 원본 거래 두 건을 보존하고 예약 ↔ 결제 고유 사실을 위조하지 않는다.
- 변경 범위를 좁힌 PR마다 선택 이유와 실행한 표적 테스트·보호 검사를 보고하며, 무관한 전체 회귀를 반복하지 않는다.
- 제품 KPI: 거래 100건 중 사용자가 실제 이동/수정한 건수, 이유 답변 한 번으로 규칙화한 비율, 같은 오류의 다음 배치 재발률, 신규 원본부터 Google 복사 가능한 지출표까지 걸린 사용자 작업 시간. **커밋 수·코드 줄 수·테스트 횟수는 제품 성공지표가 아니다.**

### 중요: 구현 확인이 필요한 기존 정책 충돌

- 종전 `AGENTS.md`와 `docs/business_rules.md`에는 자동 여행 귀속에 보수적 HOLD 규칙이 존재한다. **이 문서가 최신 사용자 의사결정이다.** C1 구현 전 기존 테스트의 기대값을 낮은 추론일 때 `AUTO_INFERRED`로 바꾸되, 원본 결함·환불·신원·정본 여행 부재 HOLD까지 일괄 제거하지 않는다.
- `docs/target-workflow-google-authority.md`는 Google 최종 정본·COST 검토/복사 역할을 유지한다. `AUTO_INFERRED`는 Google 기록 성공이 아니다.
- 기존 `reservation` 보험 명단 ingest는 다른 목적의 API다. 항공권 매칭으로 보험 가입·결제 완료·실제 탑승을 조작하지 않는다.
