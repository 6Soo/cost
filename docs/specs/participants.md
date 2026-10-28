# 여행 교정·AI 학습·참가자

**상세 계약·참고 자료.** 아래 절의 작성 시점별 구현/배포 표시는 현재 상태가 아니다. 최신 사용자 정책과 현재 상태를 먼저 확인하고 필요한 절만 읽는다.

[시작 안내](../COST_V3_START_HERE.md) · [현재 상태](../session_handoff.md) · [운영 기록](../operations.md)

> **2026-10-28 현재 연동 감사·개선 요구:** [Travel INS 명단 수신, 참가자 DB 경로 동일성, 여행별 보험 명단 조회 명세](insurance-participant-integration-20261028.md). 기존 14명 수신 이력/합성 대조 통과는 당시 로컬 결과이며, 결제 재개 함수 계약·운영 웹 DB 동일성·여행 탭 UI는 별도 미결이다. 문서 링크만으로 구현 완료를 선언하지 않는다.

> **2026-10-28 최신 사용자 확정:** [보험가입 확정 명단 중심 수입 대조·드래그 연결](participant-income-authority-and-drag-link-20261028.md)이 이 문서의 과거 독립 명단 화면·조회 방식보다 우선한다. 수입 먼저/닉네임 입금/동명이인/공동입금이 일반적인 업무이며, 수입표의 `보험 등록` 상태와 보험 참가자 카드를 같은 여행 화면에 둔다. 읽기 전용 원본과 수동 연결 감사 경계는 유지한다. 실제 구현은 SPEC_ONLY.

## 내용

- [COST V3 구현 명세 — 추론 우선배정·사후 AI 대화학습·항공권 참가자·N:M 대사·테스트 독립화](#src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md)
- [보험가입 명단 기반 참가자 확정과 수입 대조 명세](#src-docs-participant-income-reconciliation-spec-md)

---

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md"></a>

## cost-v3-inference-ai-passenger-nm-test-architecture

통합 전 경로: `docs/cost-v3-inference-ai-passenger-nm-test-architecture.md`

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--cost-v3-구현-명세--추론-우선배정사후-ai-대화학습항공권-참가자nm-대사테스트-독립화"></a>
### COST V3 구현 명세 — 추론 우선배정·사후 AI 대화학습·항공권 참가자·N:M 대사·테스트 독립화

> **문서 탐색·정책 충돌/현재 구현 여부:** 반드시 [COST V3 단일 개발 진입점](../COST_V3_START_HERE.md)을 먼저 참조. 이 문서는 해당 기능의 세부 계약이며 과거 ETA/HOLD·운영 실측·아카이브 문서의 지시보다 2026-10-23 사용자 확정 정책을 우선한다.

> **2026-10-23 확정 OTA 매칭 정책 A:** [OTA–카드 진단·통합 대사·readiness 구현 명세](ota.md#src-docs-ota-card-reconciliation-policy-a-v3-md)가 본 문서의 OTA 연결 및 비용 기록 준비에 관한 최신 세부 규격이다. **카드 원본이 금융적으로 정상이고 기존 유효 여행에 배정됐다면 OTA 정확 매칭 실패·결제일 누락·추정 상태만으로 내부 경비 기록 준비를 막지 않는다.** 중복·원본 충돌·미해결 취소/환불 보호는 유지하며, 추정 예약번호는 Google 복사본에서 비운다. COST가 Google에 자동 쓰기하지 않는다. 기존 문서에 남은 보수적 OTA HOLD 서술은 이 규격과 충돌하는 범위에서 효력을 상실한다. 해당 기능은 설계 단계이며 운영 반영이 아니다.

> **2026-10-23 사용자 최신 우선 규칙.** 실행 대상: `6Soo/cost`; 참가자 원장과 예약 API 수정 대상: `6Soo/reservation`.  
> **우선순위:** 이 문서의 *여행 귀속 추론 정책*은 COST 문서·코드의 종전 「낮은 추론이면 미배정/HOLD」와 충돌하는 범위에서 최신 사용자 요구로 우선한다. 반면 금액·취소·환불·원본 오류·중복·인증·고객 신원과 관련한 안전 조건은 그대로 유지한다.  
> **구현/배포 상태:** 이 문서는 후속 구현을 위한 상세 설계이며 A·대화학습·아키텍처 개편은 아직 운영 적용된 기능이 아니다. 이번 브랜치의 B 변경은 `app/ota_payments.py` 숫자 동일성 버그와 표적 테스트 3개. 테스트 실행·배포 사실을 별도로 확인할 것.  
> **개발 원칙:** 코드 경로, 데이터 계약, 알고리즘, 사례, 테스트, 단계별 완료 기준을 고정한다. 실제 개인정보를 모델에 제공하지 않는다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--1-제품-목표와-절대적인-사용자-경험"></a>
#### 1. 제품 목표와 절대적인 사용자 경험

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--11-기존-hold-중심에서-배정수정질문학습으로-전환"></a>
##### 1.1 기존 HOLD 중심에서 「배정→수정→질문→학습」으로 전환

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

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--12-사용자가-실제로-보게-될-화면-사례"></a>
##### 1.2 사용자가 실제로 보게 될 화면 사례

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

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--2-여행-자동-귀속-낮은-추론도-적용하는-구체-알고리즘"></a>
#### 2. 여행 자동 귀속: 낮은 추론도 적용하는 구체 알고리즘

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--21-상태와-권위의-분리"></a>
##### 2.1 상태와 권위의 분리

**회계 검증 상태**와 **여행 귀속 상태**를 독립적인 축으로 취급한다:

- `financial_eligibility`: `VALID_EXPENSE | REFUND_PENDING | DUPLICATE | CONFLICT | EXCLUDED | UNVERIFIED`
- `assignment_status`: `AUTO_EVIDENCED | AUTO_INFERRED | USER_ASSIGNED | NEEDS_CANDIDATE | NO_TRIP_AUTHORITY`
- `confidence`: `high | medium | low` + 선택 근거·경쟁 후보·규칙 버전·증거 지문.
- `ledger_export_status`: `READY | REVIEW_REQUIRED | ALREADY_COPIED | POSTED_UNKNOWN` — 귀속 상태와 혼동 금지.

**중요:** 유효한 여행 후보가 존재하고 회계 원본이 유효하면 `low`여도 `AUTO_INFERRED`로 A에 붙인다. `HOLD` 또는 `unclassified`를 기본 출력으로 쓰지 않는다. 반대로 **존재하지 않는 여행**을 만들거나 고객 신원을 추측해 생성하는 건 금지다. 여행 authority 자체가 전혀 없으면 `NO_TRIP_AUTHORITY`; 후보가 0개면 `NEEDS_CANDIDATE`로 남긴다. 이는 ‘낮은 추론이니 HOLD’와 다른 상태다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--22-추천이-아닌-실제-배정"></a>
##### 2.2 추천이 아닌 실제 배정

우선순위(높음→낮음):
1. 사용자가 그 **거래 ID에 대해 직접 이동/귀속**한 `USER_ASSIGNED` (해제/수정은 사용자만).
2. 그 거래에 대한 다른 명시적 사용자 확정·기존 수동 예외.
3. 실제 예약번호·결제 근거·서비스 이용기간·검증된 여행일과 일치하는 정확 귀속.
4. 사용자 승인 재사용 규칙.
5. 후보 여행의 이용기간 중복/가까운 시작·종료/실제 이동 경로/담당자/기존 같은 업체의 결정 사례 등 검증 가능한 특징을 사용한 점수 기반 추론.

후보 점수 함수는 순수 함수 `rank_trip_candidates(transaction, evidence, authoritative_trips, approved_rules)`로 분리한다. 날짜 겹침·이용기간·여행 담당자·유사 과거 결정 등 **사용된 신호 목록과 가중치 버전**을 결과에 포함한다. 기존 여행 종료일 공식·OTA 이용기간 우선·준비 숙박 특례는 재사용한다. 숫자 점수는 제품 정책이지 신원/예약의 증명이 아니다. 점수가 동률이거나 격차가 극히 작아도 (1) 근거를 비교하고 (2) 일관된 타이브레이커로 후보 한 개를 골라 **AUTO_INFERRED/low**로 표시한다. 동일한 입력이면 순서에 상관없이 동일한 결과가 나와야 한다. **기존 사용자 확정 규칙 6에 따라 동일 조건의 여행이 둘 이상이면 수입-비용 차액이 큰 여행을 우선 배정**하되, 그 이유와 당시 정본 금액 지문을 기록한다. 그마저 구분이 안 되면 안정적인 여행 ID로 결정적 타이브레이커를 적용한다. 특정 여행에 돈이 부족하다는 이유만으로 금액을 재분배하는 새 정책은 만들지 않는다.

**회계 무결성은 추론 강행의 예외다:** 중복 여부 불명, 미확정 취소/환불 짝, 금액 충돌, 파싱 오류, 다른 거래에 예약이 이미 고정된 상황은 비용 기록 보호를 계속한다. 추론 여행 표시는 가능해도 **불확실한 실제 금액을 Google 확정 지출로 자동 반영하는 행동은 금지**한다. 한 거래가 사용자 이동으로 여행 B에 들어가더라도 원본 카드 거래/환불은 보존한다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--23-이동의-저장-계약"></a>
##### 2.3 이동의 저장 계약

- 엔드포인트(설계안): `PATCH /api/expense-assignments/{transaction_id}`; 요청 `{target_trip_id, expected_revision, client_request_id}`.
- 서버 검사: owner 권한, same-origin/CSRF, 비용 거래 ID 실존, 대상이 authoritative 여행이고 수동 이동 가능, 현재 revision 일치, 중복 요청 ID 검사.
- 한 SQLite 트랜잭션 안에서 `expense_assignment_decisions`에 `transaction_id` 유일 결정, `assignment_audit`에 `from_trip_id,to_trip_id,source='user',actor,revision,created_at,reason_status='pending_ai'`를 저장한다. 카드 raw transactions를 수정하지 않는다.
- `client_request_id` 중복 호출은 기존 동일 결과를 돌리고 다른 페이로드 재사용은 오류. 충돌/오류 시 전부 rollback.
- 사용자 수동 이동 후 `posthoc_learning_jobs` 큐에 idempotent 작업 한 건을 생성한다. **AI 실행과 네트워크 호출은 커밋 바깥에서 수행**한다.
- 사용자 다시 B→C 이동 시 이전 학습 작업은 기록으로 남기되 *현재 이동 사유를 대표하지 않도록* superseded 처리한다. 대화의 원거래와 각 revision은 보존한다.
- 기존 `webapp/ledger_store.py` revision/수동 override 구조와 `webapp/card_flow.py`의 실제 카드 귀속 저장 경로를 조사 후 하나의 정본 write path에 붙인다. 별도 조용한 경쟁 작성자를 만들지 않는다.
- Google은 최종 장부이며 COST에서 자동 쓰지 않는다. Google 반영/마감 거래의 충돌 경고를 표시하되 가짜로 Google이 수정됐다고 표시하지 않는다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--3-웹-내-ai-대화규칙-학습-무료-모델용-완전-계약"></a>
#### 3. 웹 내 AI 대화·규칙 학습: 무료 모델용 완전 계약

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--31-기존-코드-재사용-새-프레임워크-금지"></a>
##### 3.1 기존 코드 재사용 (새 프레임워크 금지)

- `webapp/dialog_turn.py`: 기존 provider-neutral 다회차/회복·대기·fallback 정책과 대화 ID 계약 조사.
- `webapp/provider_transport.py`, `webapp/provider_config.py`: 서버 지정 프로바이더만 허용. 클라이언트가 URL·모델·키 임의 결정 금지.
- `webapp/rule_text.py`, `app/rule_proposals.py`, `webapp/classification_rules.py`: 구조화 제안/허용 스키마/미리보기/충돌 검사/승인 재사용. `app/rule_proposals.py`는 고정 패턴의 결정론적 파서이므로 다회차 자연어 이해를 그 정규식 몇 개로 대체했다고 주장하지 않는다.
- `webapp/ledger_store.py`: 승인·revision·audit/idempotency. 기존 규칙의 source key는 불변 카드 근거이고 설명 문구 수정은 조건으로 쓰지 않는다.
- `webapp/card_actions.py`, `webapp/real_review_ui.py`, `webapp/card_flow.py`: 실제 카드 행에서 여행 이동과 사후 질문으로 들어가는 UI.
- 기존에 실제 프로바이더 연결이 구성되지 않았다면 **대화 메시지와 사용자 이동은 로컬에 안전하게 보존하고 AI는 대기**. 합성 모델 결과를 실제 AI 응답으로 보고 금지.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--32-스레드메시지규칙안-데이터"></a>
##### 3.2 스레드·메시지·규칙안 데이터

`assignment_conversations`: `conversation_id PK, transaction_id, originating_audit_id, origin_revision, state(open|awaiting_user|awaiting_ai|draft_ready|applied|superseded|closed), created_at, updated_at`.  
`assignment_messages`: `message_id PK, conversation_id, turn_index, role(user|assistant|system), kind(question|suggested_option|user_answer|followup|draft_preview|error), body, provider_attempt_id nullable, created_at`. 개인 정보/비밀은 외부 모델로 전달 전 제거하며 저장 DB에는 기존 개인정보 최소화 정책 적용.  
`assignment_rule_drafts`: `draft_id PK, conversation_id, based_on_revision, conditions_json, effects_json, applicability, evidence_digest, state, created_at`.

API 설계(기존 중복 API가 있으면 확장하되 최종 계약을 하나만 선택):
- `GET /api/assignment-conversations?transaction_id=...` — 기존 스레드와 미답 질문, 불필요한 재질문 금지.
- `POST /api/assignment-conversations/{id}/answers` — `{choice:'option_1'|'option_2'|'custom', answer_text?, expected_turn, client_request_id}`. 3인 경우 `answer_text` 필수. 서버에서 제공한 선택지만 유효. 예상 답변 1·2라도 사용자가 선택하기 전에는 사용자 확정 취급 금지.
- `POST /api/assignment-conversations/{id}/retry` — 명시적 재시도/대기 해제; 같은 턴 이중 적용 금지.
- `GET /api/assignment-conversations/{id}/draft` — 현재 규칙 초안·근거·충돌·적용 대상 개수·총액(서버 계산)·영향받을 여행 목록·미확정/기존 사용자 확정 제외 건수.
- `POST /api/assignment-rule-drafts/{id}/approve` — owner 인증·revision 및 evidence hash 확인 후 기존 규칙 승인 경로 사용. AI 텍스트·모델 추정 영향 수치를 그대로 쓰지 않는다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--33-에이전트-입력출력의-최소-json-계약"></a>
##### 3.3 에이전트 입력/출력의 최소 JSON 계약

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

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--34-ai-제공자-비용과-장애"></a>
##### 3.4 AI 제공자 비용과 장애

기존 프로바이더 계약을 우선 사용하고 실제 설정 가능한 무료 모델만 별도로 확인한다. 모델 교체/무료 할당량 실패는 메시지 **queued/waiting**으로 유지한다. 유료 API 자동 업그레이드·제3자 비밀 전송 금지. 재시도할 때 같은 `conversation_id`, `origin_revision`, `expected_turn`을 보내 늦은 응답이 새 결정에 덮어쓰지 못한다. 질문 1·2는 모델 출력으로 제안하고, UI의 옵션 3은 언제나 서버에서 제공하는 사용자 자유입력 버튼이다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--4-a--항공권-영문-탑승자한글-이름-및-실제-해당-여행-참가자-등록"></a>
#### 4. A — 항공권 영문 탑승자→한글 이름 및 실제 해당 여행 참가자 등록

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--41-반드시-구분하는-세-가지-사실"></a>
##### 4.1 반드시 구분하는 세 가지 사실

1. *영문명 추출*: 서명 검증된 항공권/전자항공권/예약 발권 문서에 `KIM/JI WON`이 등장한다. 이는 해당 문서에 이름이 있다는 증거다.
2. *한글명·고객 동일성*: 영문 표기로 한글 이름을 단정할 수 없다. `KIM JI WON`은 김지원/김지원을 비롯해 다양한 후보를 만든다. 영→한 음차만으로 `customers` 특정 인물 또는 `reservations`의 신원을 **확정 금지**.
3. *실제 여행 참가/탑승*: 항공권 발권 사실은 실제 항공편 탑승 또는 여행 참여 완료의 증거가 아니다. **COST UI에서 추정 참가자로 우선 연결**할 수는 있지만 ‘실제 탑승 확인’ 상태는 추가 원천 사실(여행 참가 확인, 가이드 명단의 확인, 탑승 근거 등)이 있을 때만 확정한다.

사용자 목적은 사람이 영문명을 일일이 등록하지 않고 최대한 자동화하며, 나중에 UI에서 잘못 연결된 사람·여행을 쉽게 고치는 것이다. 이 목표를 *추정/확정의 표시를 분리하는 방식*으로 구현한다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--42-검증한-현재-연동-구조"></a>
##### 4.2 검증한 현재 연동 구조

`reservation/src/app/api/internal/roster/route.ts`는 `travel_ins`의 보험 가입 참가자 확정 자료용이며 `travel_insurance=1`을 설정하고 예약을 만들므로 항공권 전용 호출에 사용하지 않는다.  
`reservation/src/app/api/internal/customers/route.ts`는 주민번호가 포함될 수 있으므로 항공권 추론에 사용하지 않는다.  
`reservation/src/lib/customerDb.ts`의 기존 `normalizeEn`(공백·하이픈 제거/소문자화), `reservation/src/app/api/internal/guides/route.ts`의 가이드 `flight_name_en`, `src/app/api/admin/customer-match-queue/route.ts`의 기존 수동 고객 후보 검토 개념을 재사용한다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--43-권장-구현-단계"></a>
##### 4.3 권장 구현 단계

**A0 — 읽기 전용 발견 및 원본 인덱스.** COST `app/flight_evidence.py`와 `app/ota_mail.py` 등의 검증된 발권/여정에서 탑승자 `passenger_name_en`, 예약/티켓 출처 SHA, 예약 날짜/이용 날짜/노선/탑승자 수/운임의 근거를 추출한다. 서로 다른 탑승자와 중복 메일을 구분한다. 전처리 `NFKC`, 대소문자·구두점·슬래시·공백 정리, `SURNAME/GIVEN MIDDLE`을 분리한 뒤 원문도 보존. 미승인 텍스트/본문만 있는 증거는 참가자 확정에 사용 금지.

**A1 — 권위 참가자 후보 조회.** reservation에 **새 read-only 내부 엔드포인트** `GET /api/internal/passenger-candidates?tourFldid=...` (설계안)를 구현한다. `INTERNAL_API_TOKEN` 인증·최소 필드만 허용; 해당 여행의 취소되지 않은 `reservations` 대표자/복호화한 companions의 **표시명·영문명·예약/동행인 opaque ref**와 가이드의 별도 `guide_id`만 제공한다. 주민번호, 전화, 계좌, 암호문, 토큰, 전체 고객 데이터 반환 금지. 리턴 형식 `{tour_id, source_revision, candidates:[{kind:'lead'|'companion'|'guide',reference_id,name_kr,name_en?,status}]}`. 실제 컬럼 존재/권한을 소스에서 검증 후 조정한다. 고객 동일성 보강을 위한 기존 전사 원장 조회도 안전한 내부 API에 **동일 최소 필드**로 추가할 수 있으나 다른 여행의 고객 개인정보를 대량 유출하지 않는다.

**A2 — 우선 매칭/음차.** 다음 근거 우선순위: (a) 기존 예약 대표자/동행인의 정확 영문명 + 해당 여행 ID + 유일한 고객 ref, (b) 기존 `flight_name_en`이 유일하게 같은 가이드 + 그 여행 실제 담당 근거, (c) 이미 사용자 검증을 거친 영→한 별칭 사전, (d) 국문 이름과 영문명의 발음 후보 + 동일 여행의 다른 근거, (e) 로컬 음차/무료 AI가 제안한 2~3개 한글 표기. 단계 (d),(e)는 **추정**, 확정된 실제 신원이 아니다. 비교 시 성/이름 역순, 공백/하이픈, 음절 분리, 외국 국적 이름, 동명이인 처리. 단순 문자열 유사도 1등이라는 이유로 기존 사람을 잘못 덮어쓰지 않는다.

**A3 — 여행 귀속은 최대 자동화.** 항공권 여정/여행의 authoritative 일정/공항/담당자를 기준으로 최선 여행 하나를 `AUTO_INFERRED`로 선택하고 낮은 신뢰도도 그 여행의 *추정 참가자* 영역에 나타내되 후보/근거를 보존. 여행 후보 0이면 참조할 여행이 없음을 표시한다. 직원/대장/일반 참가자 구분은 분리한다. 인원이 다수인 한 장의 예약은 탑승자별 별도 연결 후보를 생성하되 실제 예약·카드 비용을 임의 인원수로 분할하지 않는다.

**A4 — 쓰기 분리.** COST에는 `flight_passenger_candidates` 및 `passenger_trip_assignments`(원천 SHA + 승객키 + 여행키의 idempotent 키, status, source_revision, evidence digest) 테이블/조회 UI를 추가하고, **reservation 정본에 자동 신규 예약을 만들기 전에** 새 내부 API `POST /api/internal/flight-passenger-links` (설계안)를 설계한다. 인증 + revision + 독립 idempotency + user provenance를 요구. **정확한 기존 reservation 참조가 검증된 경우에만** 실제 고객 연결/영문명 보완; 단지 음차만 있는 경우 reservation `reservations`에 임의 실명 고객/신규 예약 생성 금지, *provisional passenger* 별도 테이블에 적재. provisional은 실제 참가 확인 전에도 내부 여행별 명단에서 보이며 수정할 수 있다. 확정/해제는 owner 동작 또는 권위 참가 확인 근거로만. `travel_insurance`, `payment_status`, `customer_id`, RRN 등 다른 예약 업무 필드 불변. 취소된 여행/항공권/예약은 자동 확정 제외.

**A5 — 교정 후 학습.** “이 탑승자는 김지원, 여행 B의 실제 고객이다”라는 owner 이동/신원 선택은 `USER_ASSIGNED` 기록 후 사후 AI 스레드에 넣는다. AI가 “왜 B 여행 참가자인가?” 근거 옵션 1/2/3을 만들고 다음에 재사용할 **영문명 별칭/해당 고객/여행 귀속 규칙**의 후보를 만든다. *동일 영문명=영원히 동일 한글 고객* 같은 전역 규칙은 동명이인 위험이 있어 source-scoped 또는 확인된 customer ID에만 적용한다. 다른 여행의 고객 레코드를 조용히 병합 금지.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--44-a의-최소-인수-테스트"></a>
##### 4.4 A의 최소 인수 테스트

- 유효한 영문명 + 같은 여행의 유일한 확인된 영어 이름 → 정확한 기존 참가자에 매칭, 신규 예약 0.
- `LEE MIN SU` 여러 명·음차 표기 상충 → 여행 추정 참가자는 표시하지만 **고객 확정 연결/병합 0**, 확인 UI 노출.
- 발권 전/취소 예약·서명 없는 메일 → 확정 참가자 생성 0.
- 대장/가이드 정확 이름 → 가이드 후보로 표시, 고객 손님과 중복 삽입 0.
- 동일 메일·발권 원본 재처리 3회 → 후보/예약/감사 이력 멱등, 중복 0.
- 원본 승객 수 3·카드 일괄 결제 1 → 승객 후보 3 / 카드 비용 원본 1.
- API 무토큰/잘못된 role/CSRF → 거부; 응답·로그에 개인정보·원문·RRN 미노출.
- A 사용자 강제 B 이동 후 새 수집 → B 유지, 대화 큐가 지연돼도 B 유지.
- 예약의 여행·고객 ref·원천 SHA 변경 → stale 재검토, 구 연결 조용한 재해석 금지.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--5-b--같은-금액-nm-거래-자동-대사"></a>
#### 5. B — 같은 금액 N:M 거래 자동 대사

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--51-현행-기능과-이번-코드-보완"></a>
##### 5.1 현행 기능과 이번 코드 보완

기존에 `app/ota_payments.match_ota_payment_events`는 결제 이벤트 및 카드 거래들의 전역 후보 그래프를 구성해 최대수 매칭, 반복금액 그룹을 안정 정렬하며 **N개 OTA 이벤트 = M개 실제 카드 원행**이면 자동 매칭한다. `app/ota_portal._identical_group_matches`에도 유사 수량 대사 경로가 존재한다. 중복 기능을 세 번째 모듈로 재구현하지 않는다.

**이번 수정:** `_event_group_signature`가 `30000`과 `30000.00`을 문자열이 다르다는 이유로 다른 그룹으로 나누던 오류를 `Decimal`의 유효 양수/무반올림 정규형으로 고쳤다. `NaN`, `Infinity`, 0, 음수, 잘못된 문자는 동등 금액으로 인식하지 않는다. 함께 추가한 표적 테스트: 2:2 다르게 표시된 동등 금액/입력 순서 독립성, 2:3 보류, 숫자 이상치.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--52-개별-신원-증명과-수량-정합성을-혼동하지-않음"></a>
##### 5.2 개별 신원 증명과 수량 정합성을 혼동하지 않음

- 예: OTA 예약 A/B가 각각 50,000원이고 카드 매입도 실제 서로 다른 승인 원행 2건이 각각 50,000원이면 **2:2 유효 수량 매칭**이다. 원행 2건을 하나로 합치지 않고 한 건씩 기록한다.
- 개별 예약번호↔카드 승인번호 연결 근거가 없다면 정렬을 통한 출력은 *회계상 수량 대응*이지 *고유 예약 결제의 정밀 증명*이 아니다. `individual_payment_evidence=false`와 후보 그룹 식별자/근거를 남기고 각 예약 고유 사실을 창작하지 않는다.
- 2 OTA : 3 카드 또는 3 OTA : 2 카드면 총액이 우연히 같더라도 누락/중복 가능성이 있으므로 그룹 상태 `HOLD_PARTIAL_GROUP`. 고유 연결할 증거가 있는 일부 행은 그 증거의 유효성에 따라 별도 확정하지만 나머지는 자동 임의 흡수하지 않는다.
- 카드 원행이 원래 두 장인데 **동일 파일 재업로드**로 두 줄씩 보이는 것은 2건 결제가 아니므로 `duplicate_of`를 제외한 고유 실거래 수만 센다.
- 결제일·통화·카드 issuer/끝4·가맹점 확인·명시 금액/승인된 할인 차이·정확 결제 여부 등 필수 간선 유효성은 유지한다. 다른 여행이거나 서비스 이용기간이 충돌하면 **카드 대응은 그룹으로 유지하되 여행 배정은 2절 추론 규칙에 따라 별개 결정**. 예약 단위 사실을 확정이라고 위장 금지.
- **환불**은 `app/partial_refund.py`의 독립된 구매↔취소 결제 방향/금액/기간 및 원본 보존 계약을 따른다. 구매 N:M 규칙을 같은 날 발생한 환불 2건에 임의 적용하지 말고 분리 테스트로 확장한다. 전액/부분 환불·해외 환율 차액 원문 수정 금지.
- 스냅샷·기존 사용자가 고정한 그룹·이미 기록한 거래를 재정렬하지 않는다. 그룹 구성원/카드 승인번호/결제일이 변하면 `HOLD_GROUP_CHANGED`를 유지한다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--53-표적-테스트와-완료-기준"></a>
##### 5.3 표적 테스트와 완료 기준

`tests/card_pipeline/test_ota_payments.py`의 새 테스트 3개 + 기존 `test_ota_payments.py` 관련 그룹 테스트 + `test_portal_identical_bookings.py`·`test_same_day_lodging_group.py` 중 변경 영향 범위만 1회. 테스트 선택 예: `python -m pytest -q tests/card_pipeline/test_ota_payments.py -k "repeated_nm"`. 프로덕션 데이터 연결 없이 합성 fixture 사용. 테스트가 실패하면 변경한 기능과 관련된 실패만 고치고 무관한 전체 대사/운영 백업을 반복하지 않는다. 검증 미실행 시 "테스트 완료"라고 쓰지 않는다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--6-구조-개편--테스트-실행-범위를-줄이는-것이-목적"></a>
#### 6. 구조 개편 — 테스트 실행 범위를 줄이는 것이 목적

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--61-현재-문제"></a>
##### 6.1 현재 문제

대형 `webapp/card_flow.py`, `webapp/ledger_store.py`, `webapp/ledger_board.py`에 서로 다른 책임과 부수효과가 집중돼 있어 단순 UI/규칙 변경의 영향 범위가 불명확해진다. 업무 분류·자동 여행 추론·사후 학습 대화·증거 대사·장부 쓰기·Google 읽기를 분리하지 않으면 작은 수정마다 전체 DB/브라우저/OTA 재수집 검증이 유혹이 된다.

**목표는 테스트 개수를 무조건 줄이는 것이 아니라 변경 영향 경계를 좁히는 것**이다. 실제 회계 금액/원본/사용자 확정/환불/보안의 보호를 제거하지 않는다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--62-최소-변경-중심-모듈-경계안"></a>
##### 6.2 최소 변경 중심 모듈 경계(안)

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

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--63-변경-영향필수-테스트-매트릭스"></a>
##### 6.3 변경 영향→필수 테스트 매트릭스

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

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--64-작업을-분리하는-최소-pr-제안"></a>
##### 6.4 작업을 분리하는 최소 PR 제안

- PR-A1: reservation 읽기 전용 탑승자 후보 API + 합성 신원 테스트.
- PR-A2: COST 탑승자 정규화·근거 인덱스/음차 후보·추정 참가 UI(기존 장부 무수정).
- PR-A3: reservation provisional link API 및 승인된 정확 신원만 확정·idempotency.
- PR-C1: `trip_ranker` 순수 함수 + 최신 low-confidence 배정 정책.
- PR-C2: owner 거래 이동 저장 + 즉시 목록 변경 + 오버라이드 감사.
- PR-C3: async 사후 AI 대화 1/2/3 + 추가 질문 + 규칙 초안/승인, 기존 provider 모듈 재사용.
- PR-T1: 테스트 임팩트 매핑 및 도메인 경계 추출(기존 기능 보존). 장부 엔진 대규모 일괄 리팩터링 금지.
- PR-B: OTA 2:2 반복 결제 숫자 동일성 버그픽스/표적 테스트(이번 브랜치). 간선 정책·기존 환불 기능 불변.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--7-구현-실행-절차-절대-멈추지-않고-안전한-부분만-진행"></a>
#### 7. 구현 실행 절차 (절대 멈추지 않고 안전한 부분만 진행)

1. **DISCOVER:** 해당 repo `main`과 작업 브랜치 SHA, `git status`, 위 0절 파일, 관련 API·테스트를 실제로 읽고 결과를 짧게 기록한다. 이미 구현된 기능을 다시 만들지 않는다. 현재 사용자 checkout의 dirty 파일/기존 stash/운영 데이터 수정 금지.
2. **CONTRACT FIRST:** 기능별 DTO/오류코드·SQL 테이블·idempotency·오버라이드 우선순위·테스트 사례를 최소 파일로 명세한다. 미정 원본 필드명은 실제 DB schema 확인 후만 고른다.
3. **IMPLEMENT VERTICAL SLICE:** 최소 사용 가능 한 경로(예: A→B 이동 + 사후대화 1회)를 먼저 완성. 로그인·실AI·실데이터가 없어도 합성 스텁 테스트 가능하지만 실제 완성이라고 보고 금지.
4. **TARGETED TEST:** 그 기능의 표적 테스트 + 바뀐 안전 경계만 1회. 재현된 문제 없는 전체 테스트/전수 OTA 재계산 반복 금지.
5. **REVIEW:** 안전한 변경인지, 기존 사용자 지정·기록·원문을 덮지 않는지 diff에서 검증. 명세·실행 결과·미검증/보류 분리.
6. **COMMIT/PR:** 작은 PR, 파일 소유권 분리. 메인 자동 병합·운영 릴리스·Google 쓰기·예약 실제 신원 확정은 별도 배포 권한/검증 없이 하지 않는다.
7. **NEXT:** 다른 안전한 세부 구현으로 계속. 모델이 모호한 판단을 못 하면 **그 판단만** pending/provisional 처리하고 나머지 경로를 실제 작동하게 구현한다.

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--8-종합-인수-조건--사용자-중심-kpi"></a>
#### 8. 종합 인수 조건 — 사용자 중심 KPI

- 실제 유효 여행 후보가 있는 카드 비용 100건: **낮은 신뢰도까지 여행 배정 후 표시**되며, 미배정 0건이 목표(단 권위 여행 후보 전혀 없음·원본/환불 보호 예외는 따로 집계).
- 사용자는 여행 A에서 개별 결제건을 B로 이동하는 데 **단 한 번의 저장**만 필요하고, API/AI 실패 이후에도 B에 머무른다.
- 이동 후 AI가 이유 예상 **두 가지 + 사용자의 직접 답안 1개**를 노출하고, 추가질문·규칙 미리보기/승인 및 규칙 재활용이 웹 안에서 완결된다.
- 사용자가 B를 지정했다면 어떤 백그라운드 처리도 B를 A로 되돌릴 수 없고 기존 원금·이용일·결제 ID도 바뀌지 않는다.
- 이름 변환은 후보 제안을 최대한 자동화하되 기존 예약·탑승객의 신원을 함부로 합치지 않으며, 실제 참가 확정 여부와 추정 연결을 명확히 구분한다.
- 동일 실결제 두 건 + 동액 예약 두 건은 2:2 수량 대사하되 원본 거래 두 건을 보존하고 예약 ↔ 결제 고유 사실을 위조하지 않는다.
- 변경 범위를 좁힌 PR마다 선택 이유와 실행한 표적 테스트·보호 검사를 보고하며, 무관한 전체 회귀를 반복하지 않는다.
- 제품 KPI: 거래 100건 중 사용자가 실제 이동/수정한 건수, 이유 답변 한 번으로 규칙화한 비율, 같은 오류의 다음 배치 재발률, 신규 원본부터 Google 복사 가능한 지출표까지 걸린 사용자 작업 시간. **커밋 수·코드 줄 수·테스트 횟수는 제품 성공지표가 아니다.**

<a id="src-docs-cost-v3-inference-ai-passenger-nm-test-architecture-md--중요-구현-확인이-필요한-기존-정책-충돌"></a>
##### 중요: 구현 확인이 필요한 기존 정책 충돌

- 종전 `AGENTS.md`와 `docs/business_rules.md`에는 자동 여행 귀속에 보수적 HOLD 규칙이 존재한다. **이 문서가 최신 사용자 의사결정이다.** C1 구현 전 기존 테스트의 기대값을 낮은 추론일 때 `AUTO_INFERRED`로 바꾸되, 원본 결함·환불·신원·정본 여행 부재 HOLD까지 일괄 제거하지 않는다.
- `docs/target-workflow-google-authority.md`는 Google 최종 정본·COST 검토/복사 역할을 유지한다. `AUTO_INFERRED`는 Google 기록 성공이 아니다.
- 기존 `reservation` 보험 명단 ingest는 다른 목적의 API다. 항공권 매칭으로 보험 가입·결제 완료·실제 탑승을 조작하지 않는다.

---

<a id="src-docs-participant-income-reconciliation-spec-md"></a>

## participant-income-reconciliation-spec

통합 전 경로: `docs/participant-income-reconciliation-spec.md`

<a id="src-docs-participant-income-reconciliation-spec-md--보험가입-명단-기반-참가자-확정과-수입-대조-명세"></a>
### 보험가입 명단 기반 참가자 확정과 수입 대조 명세

> 버전: 1.0 / 작성일: 2026-10-20 KST
> 상태: 계획·명세 작성 COMPLETE. 구현(P0~P4) COMPLETE(2026-10-20, [작업 인덱스](../history/implementation-and-audits.md#src-docs-participant-income-task-index-md)). 실명 전사·실제 여행 연결·운영 적용은 미실행.
> 승인 범위: 사용자가 요청한 계획·명세 작성과 후속 P0~P4 구현. 이 문서는 운영 배포 승인을 뜻하지 않는다.
> 실행 진입점: [이 기능의 작업 인덱스](../history/implementation-and-audits.md#src-docs-participant-income-task-index-md). 회계 정본과 수입 읽기 경계는 [Google 목표 명세](google-ledger.md#src-docs-target-workflow-google-authority-md)와 [시트 열 계약](google-ledger.md#src-docs-google-workbook-layout-md)을 따른다.

<a id="src-docs-participant-income-reconciliation-spec-md--1-목적과-사용자-요청"></a>
#### 1. 목적과 사용자 요청

다른 에이전트가 전달한 보험가입 명단을 해당 여행의 실제 참가 기록으로 받아, 참가자와 기존 수입 명단의 관계를 확정한다. 사용자는 보험가입 명단을 실제 참가 기록으로 인정했다. 이 자료를 단순 신청자 후보로 낮추지 않는다.

사용자 요청으로 확정된 동작은 다음과 같다.

1. 여행에 연결된 보험가입 명단의 사람은 그 여행의 확정 참가자로 인식한다.
2. 기존 수입 내용에 해당 사람이 없으면 이름만 추가한다.
3. 기존 수입 내용에 해당 이름이 있으면 참가 확정 표시를 붙인다.
4. 참가 명단과 입금내역의 연결 결과를 보존해 여행별 참가 인원과 수입 기록을 대조한다.

이 명세에서는 **이름 추가와 참가 표시를 COST의 참가·수입 통합 대조표에 저장하는 방식**으로 구체화한다. 기존 Google 수입 직접 입력 원칙에 맞춘 설계 기본값이며, Google 수입 행이나 금액을 자동 생성·수정하는 의미는 아니다. 이름만 있는 행은 수입 사건으로 저장하지 않는다. 사용자가 Google 반영까지 별도로 요청하면 이 경계를 명시적으로 변경해야 한다.

<a id="src-docs-participant-income-reconciliation-spec-md--2-범위와-제외-범위"></a>
#### 2. 범위와 제외 범위

첫 구현은 에이전트가 전사한 구조화 명단 수신, 기존 여행 연결, 참가 확정 저장, Google 수입 읽기, 자동 이름 대조, 예외 수정, 여행별 대조표에 한정한다. 카드 입력 → 웹 검토·규칙 수정 → XLSX 출력 경로를 바꾸지 않는 독립 기능으로 둔다.

- 여행은 기존 Google 여행 탭에서만 선택한다. 보험의 행사명·기간이나 파일명으로 여행을 만들거나 기존 여행 날짜를 고치지 않는다.
- 입력 명단을 신뢰하는 것과 손글씨를 정확히 읽는 것은 별개다. 판독 불명 이름이나 여행 연결만 해당 항목에서 보류하고, 읽을 수 있고 연결이 확실한 참가자는 처리한다.
- 여행 수입 금액은 선택된 Google 정본에서만 읽는다. 은행 신규 수집, 수입 자동 기장, 미납액 계산, 참가비 추정, 자동 환불·상계, 기존 수입 분할은 포함하지 않는다.
- 이미지 직접 OCR, 외부 AI 전송, 보험사 연동, Render 이전, 별도 고객 관리 시스템은 첫 구현의 전제조건으로 두지 않는다.
- 첨부 사진의 실명·생년월일·전화번호·식별번호는 이 문서와 Git에 옮기지 않는다. 사진의 정확한 여행과 전체 페이지 수는 이번 작업에서 확인하지 않았다.

<a id="src-docs-participant-income-reconciliation-spec-md--3-권위와-상태를-분리한다"></a>
#### 3. 권위와 상태를 분리한다

| 판단 대상 | 근거 | 화면 표시와 제한 |
| --- | --- | --- |
| 실제 참가 여부 | 사용자가 인정한 보험가입 명단과 명시적 정정 이력 | `참가 확정`으로 표시한다. 입금이 없어도 참가 확정은 유지한다. |
| 누구의 수입 행인지 | 같은 여행의 이름 일치 또는 사용자 확정 연결 | `이름 일치` 또는 `수동 연결`과 원본 행을 표시한다. |
| 수입 명단에 이름이 있는지 | 정상적으로 읽은 Google 수입 영역의 이름·닉네임 | 금액이 없어도 `수입 명단 있음`으로 표시한다. |
| 입금 금액 | Google의 예약금·잔금·추가금·총액과 원본 상태 | 실제 값을 그대로 표시한다. 전액 납부 여부는 확정하지 않는다. |
| 여행 전체 확정 인원 | 전체 명단임이 확인된 자료와 중복·누락 해결 | 일부 페이지만 있으면 `확인된 참가자 N명 · 전체 명단 미완료`로 표시한다. |
| 여행 회계 마감 | 기존 Google 마감 규칙 | 참가 대조 완료를 회계 마감으로 간주하지 않는다. |

대장·가이드도 명단에 있으면 실제 참가자로 보존한다. 전체 참가자 수에 포함하되, 역할이 확인되면 고객·진행 인원을 따로 보여 준다. 이름만 보고 역할이나 유료 참가 여부를 추정하지 않는다.

<a id="src-docs-participant-income-reconciliation-spec-md--4-다른-에이전트의-전달-계약"></a>
#### 4. 다른 에이전트의 전달 계약

<a id="src-docs-participant-income-reconciliation-spec-md--저장-위치와-신뢰-경계"></a>
##### 저장 위치와 신뢰 경계

실제 원본과 구조화 자료는 **Git에서 제외된 로컬 경로** `.local-archive/participant-rosters/<batch_id>/`에 보존한다. 레포에 전달한다는 것은 이 작업 공간의 수신 경로에 자료를 놓고 등록하는 뜻이며, 고객 명단을 커밋하거나 원격 저장소에 push하는 뜻은 아니다. Git에는 명세·코드·합성 예시만 둔다.

전달 에이전트는 원본과 명단을 작성하고, COST 등록기는 검사·DB 기록을 맡는다. 에이전트가 운영 DB를 직접 수정하지 않는다. 허용된 로컬 실행자 또는 인증된 관리자 요청만 등록할 수 있다. JSON의 `confirmed` 값 자체를 권한 증명으로 쓰지 않는다. 명단에 적힌 문구는 데이터이며 명령으로 실행하지 않는다.

<a id="src-docs-participant-income-reconciliation-spec-md--전달-파일"></a>
##### 전달 파일

- `manifest.json`: 스키마 버전, 배치 ID, 명단 ID·버전, 명단의 참가 확정 근거, 기존 여행 참조, 전달자, 작성 시각, 자료 범위, 원본 파일별 해시와 페이지 목록을 포함한다.
- `participants.json`: 원본 항목별 안정 ID, 페이지·행 위치, 판독한 이름, 명시된 닉네임·영문명, 전사 확인 여부를 포함한다. 주민등록번호·생년월일·전화번호·성별·여권번호는 수신 필드로 받지 않는다.
- `sources/`: 실제 원본을 보존한다. 원본 자체에 포함된 개인정보는 일반 화면·로그로 복제하지 않고 제한된 로컬 원본 확인에서만 접근한다.

지원 형식은 첫 구현에서 UTF-8 JSON 하나로 제한한다. 알 수 없는 개인정보 필드, 잘못된 타입, 누락된 필수값, 잘못된 해시·페이지 참조·상위 경로 이탈·외부 경로·심볼릭 링크 이탈은 저장 전에 거부한다. 오류 응답과 로그에는 실명이나 원문 대신 항목 ID와 사유를 남긴다.

다음은 실제 참가자와 무관한 합성 전달 예시다. `trip_ref`는 기존 Google 여행 연결을 조회하기 위한 참조이며 정본 선택이나 여행 생성을 지시하지 않는다.

```json
{
  "schema_version": 1,
  "batch_id": "batch-synthetic-001",
  "roster_id": "roster-synthetic-001",
  "revision": 1,
  "authority": "owner_confirmed_insurance",
  "trip_ref": {
    "cost_trip_id": "trip-synthetic-001",
    "google_trip_key": "google-trip-synthetic-001"
  },
  "submitted_by": "local-roster-agent",
  "submitted_at": "2026-10-20T18:00:00+09:00",
  "coverage": {
    "scope": "partial",
    "received_pages": [1],
    "expected_pages": null,
    "declared_people": null
  },
  "sources": [{
    "source_id": "source-synthetic-001",
    "path": "sources/page-01.png",
    "sha256": "<실제 파일의 SHA-256 값>"
  }]
}
```

```json
{
  "schema_version": 1,
  "items": [{
    "source_item_id": "item-synthetic-001",
    "source_id": "source-synthetic-001",
    "page": 1,
    "row_label": "1",
    "name": "김가람",
    "nickname": null,
    "english_name": null,
    "transcription_status": "verified"
  }]
}
```

`authority`의 위 값은 이 사용자 요청으로 인정된 보험 참가 기록에만 쓴다. `transcription_status`는 `verified` 또는 `unreadable`이며 `verified`에는 비어 있지 않은 이름이 필요하다. 영문명만 확실하면 영문명을 이름으로 보존하고 한글 이름을 추측하지 않는다. 예시의 해시 자리표시는 실제 등록에서 허용되지 않는다.

`scope`는 `partial` 또는 `complete`다. 전체 명단은 예상 페이지 수·명단 인원과 실제 원본·행을 대조할 수 있어야 한다. 일부 사진의 행 번호가 8~17이라고 해서 앞선 사람이나 총인원을 생성하지 않는다. 이름을 읽지 못한 원본 항목도 누락하지 않고 판독 대기로 남긴다.

<a id="src-docs-participant-income-reconciliation-spec-md--여행-연결과-등록-결과"></a>
##### 여행 연결과 등록 결과

1. 기존 COST 여행과 Google 여행 키가 같은 여행을 가리키는지 검사한다. 없거나 서로 다르거나 연도·동일명 여행이 모호하면 `TRIP_MAPPING_REQUIRED`로 둔다.
2. 명확한 여행 연결과 신뢰할 수 있는 참가 근거·전사가 있으면 재승인을 요구하지 않고 참가 확정을 저장한다. 사용자는 이후 잘못 연결한 여행이나 이름을 정정할 수 있다.
3. 수입 조회가 실패해도 참가 확정은 저장한다. 수입 대조만 대기하며 이름 추가 대상이라고 단정하지 않는다.
4. 반환값에는 배치 ID, 적용 명단 버전, 신규 참가자 수, 재수신 수, 판독 대기·충돌 항목 ID, 수입 대조 가능 여부를 담는다. 실패 항목과 정상 적용 항목을 구분한다.

<a id="src-docs-participant-income-reconciliation-spec-md--5-중복정정과-인원수"></a>
#### 5. 중복·정정과 인원수

- `batch_id`와 정규화한 전달 내용의 지문이 모두 같으면 기존 결과를 반환한다. 같은 배치 ID에 다른 내용이 오면 `SOURCE_ID_CONFLICT`로 보류한다.
- 같은 `roster_id + source_item_id`는 버전이 달라도 같은 원본 항목을 가리킨다. 이름을 ID로 쓰지 않는다. 전달 에이전트는 재촬영·순서 변경에도 항목 ID를 유지한다.
- 같은 항목의 바뀐 이름·여행·삭제 표시는 새 버전의 정정 제안으로 기록한다. 기존 사용자 수동 확정은 자동으로 덮지 않는다. 변경 전후와 정정 사유를 남긴다.
- 새 배치에서 이전 사람이 빠졌다는 이유로 기존 참가자를 삭제하지 않는다. 명시적 철회·불참 정정은 이력으로 남기고 이전 근거도 보존한다.
- 명단 ID를 바꿔 같은 원본을 재전달하면 파일 해시·원본 위치로 재수신을 찾는다. 다른 사진·중첩 페이지에서 동일인이 의심되지만 안정 ID가 없으면 중복 확인으로 두고 인원을 확정 집계하지 않는다.
- 같은 이름의 별도 항목은 실제 동명이인일 수 있다. 이름만으로 합치지 않는다. 반대로 같은 사람의 복수 보험 가입·추가 명단은 증거 항목 여러 개를 참가자 ID 하나에 연결할 수 있어야 한다.
- 확정 인원은 활성 참가자 ID의 고유 개수다. 보험 행 수·수입 행 수·입금 횟수를 인원수로 쓰지 않는다. 미해결 중복은 따로 표시하며 근거 없이 정확한 총인원을 선언하지 않는다.

<a id="src-docs-participant-income-reconciliation-spec-md--6-google-수입-조회-계약과-기존-코드의-보완점"></a>
#### 6. Google 수입 조회 계약과 기존 코드의 보완점

현재 `app/google_authority.py`의 `_sum_block`은 H열 금액이 유효한 숫자인 행만 비공개 상세 자료에 넣는다. H열이 빈 이름 행은 빠질 수 있다. `webapp/google_ledger_page.py`의 `owner_rows`와 `trip_income_html`은 그 상세 자료를 사용한다. 따라서 현재 금액 행 목록만 대조하면 이미 Google에 이름만 있는 사람을 신규 누락자로 오인할 수 있다.

구현할 때는 수입 영역에서 **이름·닉네임이 있는 행을 별도 대조 자료로 보존**한다. 회계 합계·수입 건수의 기존 계약은 유지하고, 이름만 있는 행을 금액 0원의 수입으로 새로 추가하지 않는다. 기존 H열 수식 오류·캐시 누락·금액 오류를 숨기거나 검증된 금액으로 바꾸지 않는다. 과거 스냅샷에 이 대조 자료가 없으면 `INCOME_INDEX_UNAVAILABLE`로 표시하고 다음 정상 읽기 전까지 누락 판정을 보류한다.

읽기 계약은 다음과 같다.

- B:H 수입 열은 거래일자·이름·닉네임·예약금·잔금·추가금·금액이다. 이름 행의 날짜·금액 공란과 실제 0원은 구분한다.
- 여행별 선택된 Google 사본 하나만 대조한다. 메인과 보관본을 합치지 않고 기존 정본 선택·중복 경고를 따른다.
- 데이터 행 범위는 수입 헤더와 합계·지출 구간으로 판별한다. 제목·합계·수식만 있는 빈 템플릿 행을 사람으로 수집하지 않는다. 실제 금액 행의 이름이 비어 있으면 미연결 수입으로 보존한다.
- 정본 파일·탭·스냅샷 세대·원본 행 위치·셀 내용 지문을 연결 근거에 포함한다. 행 번호만 영구 ID로 쓰지 않는다. 행 삽입·정렬·수정 시 원본 연결을 재검증한다.
- 최신 정상 스냅샷과 이름 인덱스가 함께 있어야 `수입 명단 없음`을 새로 확정한다. 오래된 자료·동기화 실패·비표준 양식에서는 마지막 대조 결과와 시각을 보이고 현재 상태는 확인 대기로 둔다.
- 이름 행은 읽을 수 있지만 금액 검증에 문제가 있으면 이름 연결과 금액 상태를 분리한다. 해당 금액을 확정 입금액으로 표시하지 않는다.

<a id="src-docs-participant-income-reconciliation-spec-md--7-자동-대조-규칙"></a>
#### 7. 자동 대조 규칙

우선순위는 **기존 수동 결정 → 같은 여행의 명시적 참가자 연결 → 안전한 이름 일치 → 미연결**이다. 기존 사용자 결정을 재처리나 새 명단이 덮어쓰지 않는다.

이름은 원문을 보존하고 비교값에만 유니코드 NFC, 앞뒤 공백 제거, 연속 공백 정리, 영문 대소문자 통일을 적용한다. 한글 내부 공백 삭제·유사 발음·성만 일치·자동 영문 역변환·부분 문자열 일치는 자동 연결 근거로 쓰지 않는다. 원본에 적힌 별칭이나 사용자가 확인한 한글·영문명 관계만 사용한다.

| 조건 | 동작 | 표시 |
| --- | --- | --- |
| 같은 여행에서 참가자와 이름을 유일하게 연결할 수 있는 수입 행이 하나 있음 | 기존 행에 참가 확정 연결을 붙인다. 수입 행은 복제하지 않는다. | `참가 확정 · 이름 일치` |
| Google에 이름만 있는 행이 이미 있음 | 그 행에 연결하고 금액은 공란으로 둔다. | `참가 확정 · 수입 명단 있음 · 입금액 미기재` |
| 최신 정상 이름 인덱스에 일치하는 사람이 없음 | COST 대조표에 이름만 표시한다. | `참가 확정 · 수입 명단 없음` |
| 동명이인·같은 이름 복수 수입 행·이름과 닉네임의 상충 | 해당 연결만 보류한다. 원본과 후보를 보여 준다. | `참가 확정 · 연결 확인 필요` |
| 동일 참가자 ID 또는 수동 결정으로 여러 수입 행의 관계가 이미 증명됨 | 여러 행을 참가자 한 명에 연결한다. 실제 각 수입 행은 보존한다. | `참가 확정 · 연결된 수입 여러 건` |
| 수입 이름은 있으나 현재 보험 명단에서 연결되지 않음 | 기존 수입을 남겨 별도 구역에 보여 준다. | `명단에서 확인 안 됨` |
| 다른 여행에만 같은 이름이 있음 | 현재 여행의 연결로 쓰지 않는다. | 현재 여행의 미연결 상태 유지 |

같은 이름의 수입 행이 여러 개면 분할입금인지 동명이인인지 이름만으로 판단하지 않는다. 수동으로 같은 참가자임을 확인한 뒤에만 한 사람의 수입 목록으로 묶는다. 이름 일치는 이 명세에서 허용한 대조 기준이며 법적 본인 확인을 의미하지 않는다.

<a id="src-docs-participant-income-reconciliation-spec-md--대리입금동반자환불"></a>
##### 대리입금·동반자·환불

- 입금자 한 사람이 여러 참가자를 대신 낸 경우 참가자 여러 명과 원본 수입 한 행의 연결을 수동으로 기록할 수 있다. 금액을 각 참가자에게 복제하거나 균등 분배하지 않는다. 개인별 금액은 `공동 입금 · 개인별 금액 미확정`으로 표시한다.
- 여행 합계와 연결 수입 합계는 고유 원본 수입 행을 각각 한 번만 센다. H열 총액과 E:G 구성액을 함께 더하지 않는다. 복수 행 연결도 같은 원본 행을 중복 집계하지 않는다.
- 취소·환불·추가입금·0원 행은 Google에 있는 그대로 보존한다. 수입 취소가 참가 확정을 자동 취소하지 않고, 참가 확정이 환불을 숨기지 않는다.
- 이름만 추가한 참가자에는 거래일·예약금·잔금·추가금·총액을 모두 비워 둔다. 보험 식별 숫자를 날짜나 금액으로 해석하지 않는다.
- 입금내역이 없다는 사실은 미납의 증거가 아니다. 현금·대리입금·별도 정산일 수 있으므로 `미납`, `완납`을 자동 표시하지 않는다.

<a id="src-docs-participant-income-reconciliation-spec-md--8-화면과-완료-판정"></a>
#### 8. 화면과 완료 판정

기존 여행 상세의 수입 영역에 `참가자 대조`를 추가한다. 기본 목록은 기존 Google 수입 행을 유지하고 참가 상태를 붙인다. 연결되지 않은 확정 참가자는 같은 대조표에 이름만 표시한다. 이름만 추가된 행과 기존 수입 행은 출처로 구별한다. 참가자 ID가 확인된 복수 입금은 한 사람 아래 원본 행을 펼쳐 볼 수 있게 하되 원본 행을 없애지 않는다.

표에는 이름·닉네임, 참가 상태, 수입 연결 상태, Google 예약금·잔금·추가금·총액, 근거 확인을 보여 준다. 원본에 없는 닉네임과 금액은 비운다. 원본 행의 날짜 정렬은 유지하고, 거래일이 없는 참가자는 명단 순서로 별도 이어 표시한다. 합계는 Google 회계 합계이며 명단에서 만든 금액이 아니다.

상단에는 확인된 참가자 수, 전체 명단 수신 여부, 수입 연결 인원, 이름만 있는 인원, 연결 확인 대상, 명단과 미연결된 수입 행 수, 마지막 Google 확인 시각을 표시한다. 공동입금 참여자를 여러 명으로 세더라도 입금 행 수는 따로 표시한다.

관리자는 이름 정정, 여행 연결 수정, 같은 사람 확인, 별칭 확인, 대리입금 연결, 잘못 연결한 수입 해제를 할 수 있다. 변경은 원본 수정이 아닌 별도 결정과 이력으로 저장한다. 다른 여행까지 적용되는 전역 이름 규칙을 자동 만들지 않는다.

다음 조건을 모두 만족하면 해당 세대에 대해 `참가·수입 대조 완료`로 표시한다.

1. 전체 페이지·행을 확인했고 자료 범위가 `complete`다.
2. 판독·여행 연결·중복 인원 문제가 모두 해결됐다.
3. 모든 참가자가 수입 연결 또는 `수입 명단 없음`으로 분류됐고 모호한 연결이 없다.
4. 미연결 수입 행도 대리입금·참가 여부 미확인 등 명시적 검토 결정으로 분류됐다. 자료가 일부인데 불참으로 일괄 확정하지 않는다.
5. 사용한 Google 세대와 명단 버전이 유효하고 관련 입력 변경이 없다.

완료는 참가·수입 관계를 분류했다는 뜻이다. 수입 없는 참가자가 있어도 그 사실을 확인하면 대조는 끝낼 수 있다. 전액 수금이나 회계 마감 완료를 뜻하지 않는다. 새 명단·Google 변경으로 결과가 달라지면 영향을 받는 항목만 다시 대조하고 이전 완료 이력을 보존한다. `수입 명단 없음`은 새 수입이 생기면 자동으로 다시 평가한다.

<a id="src-docs-participant-income-reconciliation-spec-md--9-저장과-동시-실행-설계"></a>
#### 9. 저장과 동시 실행 설계

새 테이블은 기존 수입·카드 회계 테이블과 분리한다. 아래는 논리 모델이며 실제 모듈·DDL 세부사항은 구현자가 기존 저장 경계에 맞춰 정한다.

| 자료 | 저장할 핵심 내용 |
| --- | --- |
| 명단 배치·버전 | 배치/명단 ID, 지문, 여행 참조, 범위, 페이지 목록, 등록 상태·시각·전달자 |
| 명단 원본 항목 | 안정 항목 ID, 원본 해시·위치, 판독한 최소 이름 필드, 전사 상태, 변경 이력 |
| 여행 참가자 | 참가자 ID, 여행 ID, 표시 이름·확인된 별칭, 참가 확정 근거, 역할, 활성 여부 |
| 항목과 참가자 연결 | 여러 원본 항목과 참가자 한 명의 관계, 중복 확인 근거 |
| 수입 연결·검토 결정 | 참가자/원본 수입 참조, 연결 방식, 사용자 결정·사유·버전, 공동입금 여부 |
| 대조 실행·완료 기록 | 명단 버전, Google 세대·정본, 규칙 버전, 결과 지문, 예외·완료 시각 |

수신 등록은 명단 단위 트랜잭션으로 수행한다. 구조·권한·원본 무결성이 깨진 배치는 쓰지 않는다. 유효한 배치 내부의 판독 대기는 원본 항목과 보류 상태를 함께 저장할 수 있다. 동시 재수신은 유일 키로 막고, 요청 ID 재시도에는 같은 결과를 돌려준다.

사용자 수정은 참가자/결정 리비전과 입력 지문을 확인한다. 오래된 화면의 확정은 `409 STALE_RECONCILIATION`으로 거절하고 현재 차이를 보여 준다. 자동 작업과 사용자 결정이 경합하면 기존 수동 결정을 보존한다. Google 행 위치가 달라졌을 때 대응을 유일하게 증명할 수 없으면 연결 재확인으로 두고 다른 사람에게 옮기지 않는다.

<a id="src-docs-participant-income-reconciliation-spec-md--10-개인정보와-권한"></a>
#### 10. 개인정보와 권한

기본은 관리자 전용이다. 기존 여행 장부 열람 권한만으로 보험 명단·실명 대조 결과를 새로 공개하지 않는다. 별도 명단 열람 권한이 승인되기 전까지 일반 열람자·공개 데모·기존 장부 XLSX·기존 API 응답에는 새 실명·참가 표시·원본 경로를 넣지 않는다. 직접 주소 요청에도 같은 권한을 검사한다.

비공개 스냅샷과 DB는 승인된 로컬 저장 경계 안에 둔다. 원본 확인은 원본의 다른 개인정보까지 볼 수 있는 제한된 관리자에게만 허용한다. 외부 OCR·모델·Render로의 전송은 별도 승인 없이는 구현하지 않는다. 이번 기능은 이름 대조만 사용하며 생년월일·전화번호로 자동 동일인 판정을 확장하지 않는다.

이 문서는 개인정보의 새로운 수집·공개·국외 이전 근거를 확정하지 않는다. 실제 서비스 범위를 넓혀야 할 때 해당 단계의 근거와 권한을 별도로 확인한다. 기존 로컬 자료를 이용한 설계·합성 구현과 구분한다.

<a id="src-docs-participant-income-reconciliation-spec-md--11-단계별-실행-계획"></a>
#### 11. 단계별 실행 계획

각 단계는 DISCOVER → IMPLEMENT → TARGETED TEST → REVIEW → COMMIT 순서로 진행한다. 아래 테스트 이름은 2026-10-20 구현에서 만든 표적 테스트의 실제 파일과 `-k` 선택이며, 실행 결과는 [작업 인덱스](../history/implementation-and-audits.md#src-docs-participant-income-task-index-md)에 기록했다.

| 단계 | 목적과 바뀌는 동작 | 직접 영향 범위 | 필요한 한 번의 검증 | 종료 조건 |
| --- | --- | --- | --- | --- |
| P0 전달·저장 | 검증된 구조화 명단으로 여행 참가자를 등록한다. | 새 수신 도구·참가자 저장 모듈·독립 스키마 | `tests/card_pipeline/test_participant_roster.py`에서 여행 연결, 부분/전체, 판독 보류, 재수신·충돌·정정·경합·경로 제한을 확인한다. | 명확한 항목은 자동 참가 확정되며 재수신으로 인원이 늘지 않는다. |
| P1 수입 인덱스 | 금액 없는 기존 이름 행도 대조에 제공한다. | `app/google_authority.py`, 비공개 자료 계약 | `tests/card_pipeline/test_google_authority.py -k participant`에 이름만 있는 행·0원·수식 오류·세대 일치 사례를 추가하고 기존 금액 행·합계·오류 상태 불변을 확인한다. | 이름 행 누락 없이 회계 집계 계약이 유지된다. |
| P2 대조·결정 | 안전한 이름 일치와 수동 연결을 저장한다. | 새 대조 모듈·결정 저장소 | `tests/card_pipeline/test_participant_income.py`에서 동명이인·복수입금·공동입금·환불·수동 결정·원본 변경을 검증한다. | 참가/수입/판독 상태가 분리되고 원본 수입은 불변이다. |
| P3 화면 | 기존 수입 행 표시와 이름만 있는 참가자 행을 통합한다. | `webapp/google_ledger_page.py`와 제한된 새 관리자 경로 | `webapp/tests/test_participant_income.py`에서 표시·미조회·오래된 자료·권한 거부를 검사하고 변경 흐름 하나만 합성 브라우저로 확인한다. | 관리자에게 명확한 대조 상태를 보여 주며 기존 일반 열람 경로로 정보가 새지 않는다. |
| P4 통합 검토 | 수신부터 수정·재대조까지 연결한다. | 새 기능과 기존 Google 읽기 경계 | 합성 자료로 수신 → 표시 → 수동 연결 → 재수신 → Google 변경을 한 번 확인하고 영향받은 기존 수입/결정 필드의 전후 동일성을 비교한다. | 아래 수용 기준을 충족하고 정확한 코드·검증 근거가 남는다. |

수입 이름 인덱스 변경은 회계 읽기 경계에 닿으므로 합계뿐 아니라 기존 원본 행·금액·오류 상태의 보존을 확인한다. 카드·OTA 연결이나 회계 쓰기를 변경하지 않는 한 전체 카드 회귀·OTA 전수 대사는 추가하지 않는다. 새 영향이 발견되면 그 근거와 필요한 검사 범위를 먼저 기록한다.

구현 요청을 받으면 P0부터 시작한다. 운영 배포·운영 스키마 변경은 현재 계획 작성 범위에 포함되지 않는다. 이후 승인된 배포에서는 복구 사본·복원 확인과 변경 경로의 최소 확인을 수행한다.

<a id="src-docs-participant-income-reconciliation-spec-md--12-합성-수용-기준"></a>
#### 12. 합성 수용 기준

| 상황 | 기대 결과 |
| --- | --- |
| 김가람이 명단과 수입 1행에 유일하게 있음 | 기존 행에 참가 확정 표시만 추가되며 수입 행·금액은 같다. |
| 이나래가 명단에만 있음 | 이름만 표시하고 날짜·금액은 공란이며 수입 합계는 같다. |
| Google에 박다온 이름만 있고 금액은 비어 있음 | 기존 이름 행에 연결하며 같은 이름을 새로 추가하지 않는다. |
| 같은 이름 참가자 두 명 또는 수입 두 행이 있음 | 자동 병합·합산 없이 연결 확인으로 남는다. |
| 김가람의 예약금·잔금 두 행을 사용자가 연결함 | 참가자는 한 명이며 실제 수입 두 행과 원래 금액은 보존된다. |
| 수입 한 행을 참가자 두 명의 공동입금으로 연결함 | 참가자는 두 명, 수입은 한 행으로 집계하며 개인별 금액은 미확정이다. |
| 수입에만 이름이 있음 | `명단에서 확인 안 됨`으로 남고 삭제나 불참 확정을 하지 않는다. |
| 명단 사진이 일부이거나 이름 하나를 읽을 수 없음 | 확실한 참가자는 등록하되 정확한 여행 전체 인원·대조 완료를 선언하지 않는다. |
| 같은 배치/항목을 재전달하거나 두 등록기가 동시에 처리함 | 같은 결과를 돌려주며 사람·수입·결정이 중복되지 않는다. |
| 같은 ID로 다른 원문이 전달되거나 다른 여행으로 바뀜 | 충돌·정정으로 보류하며 기존 확정을 보존한다. |
| 다음 명단에서 이전 참가자가 빠짐 | 기존 참가 기록은 유지되고 명시적 정정 없이는 철회되지 않는다. |
| Google 조회 실패·과거 스냅샷·이름 인덱스 미지원 | 마지막 결과와 확인 시각을 보이고 새로운 누락 판정을 하지 않는다. |
| 정렬·행 삽입·정본 이동·수입 원문 변경 발생 | 영향을 받은 연결만 재검증하고 불확실한 연결과 대조 완료 표시를 갱신한다. |
| 보험 확정 뒤 환불이 존재함 | 참가 확정과 원본 환불이 모두 보이며 완납으로 바꾸지 않는다. |
| 일반 열람자 또는 공개 데모가 명단 API를 직접 요청함 | 새 개인정보를 반환하지 않고 권한을 거절한다. |

<a id="src-docs-participant-income-reconciliation-spec-md--13-이번-작업-결과와-재개-위치"></a>
#### 13. 이번 작업 결과와 재개 위치

이 문서를 쓴 단계에서 완료한 범위는 요구사항 정리, 기존 수입 파서·화면 경계 확인, 전달 계약·대조 규칙·저장·화면·검증 계획 작성이다.

2026-10-20 후속 요청으로 P0~P4 구현을 완료했다. 구현 위치와 실제 실행한 검증은 [작업 인덱스](../history/implementation-and-audits.md#src-docs-participant-income-task-index-md)를 따른다. 구현 후에도 첨부 사진의 개인정보 전사·전체 인원 확정·실제 여행 매핑·운영 DB 변경·Google 쓰기·배포는 수행하지 않았다.

이름만 추가하는 위치와 참가 표시 방식은 기존 정본 원칙에 맞춘 설계 기본값이다. 첫 구현은 개인정보 없는 합성 자료로 시작할 수 있다. 첨부 명단을 실제로 등록할 때만 해당 Google 여행 참조와 원본 전체 여부가 필요하며, 일부 자료만 전달되면 부분 명단으로 처리할 수 있다. 글씨를 읽지 못한 항목만 전사 확인이 필요하다.

다음 작업자는 [이 기능의 작업 인덱스](../history/implementation-and-audits.md#src-docs-participant-income-task-index-md)를 읽고 구현이 요청됐는지 먼저 확인한다. 계획 작성만 요청된 상태에서 P0 이후를 자동 실행하지 않는다.
