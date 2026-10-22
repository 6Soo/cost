# COST V3 — 단일 개발 진입점 및 통합 계약

> **상태:** 2026-10-23 사용자 확정 *목표 설계* · main/운영에 일괄 구현된 상태가 아님. 새 코딩 에이전트는 반드시 이 문서부터 읽는다.  
> **목적:** 이 문서만으로 작업 우선순위·현재 vs 미래·위험 경계·권위·진입 파일을 결정한다. 세부 구현은 **두 개의 부속 명세**를 참조하되 과거 문서의 목표·TODO를 구현 지시로 혼용하지 않는다.

## 1. 문서 권위와 충돌 해결

**최신 목표 정책의 우선순위(위→아래):**
1. 사용자 2026-10-23 확정 운영 정책: 본 문서의 \`§2~§5\`와 [OTA–카드 A 정책 세부 구현](ota-card-reconciliation-policy-a-v3.md).
2. [COST V3 AI·참가자·여행 추론 명세](cost-v3-inference-ai-passenger-nm-test-architecture.md). 동일한 OTA readiness 항목이 충돌하면 **1번 우선**.
3. [Google 정본 목표 업무 계약](target-workflow-google-authority.md), [Google B:H 7열 구조 실측](google-workbook-layout.md): Google 최종 정본, 수입·이체는 사용자 직접 Google 작성, 카드·영수증은 COST 작성→사용자 복사, Google 직접 쓰기 금지.
4. [사용자 확정 여행·금융 불변조건](reconciliation-rules.md), [업무 규칙](business_rules.md), [카드 처리 기준](card_pipeline.md): **금액·중복·취소·환불·여행 기간·사용자 결정 보호를 계속 보존**. 단 “낮은 추론→미배정” 및 “OTA 링크 미확정→정상 카드 내부 준비 차단”은 최신 사용자 정책으로 **대체**.
5. [AGENTS.md](../AGENTS.md): 실행 방식/권한/테스트/배포 제한 요약. AGENTS의 구형 예시나 기록보다 이 문서의 최신 목표 정책이 우선.
6. [README](../README.md), [기존 운영 코드·로그](operations.md): **현재 실제로 배포된 동작·검증 기록의 사실적 근거**. 목표 명세만으로 배포 완료를 주장하지 않는다.

\`docs/archive/ota-legacy-20261023/\`의 파일과 \`docs/history/\`, 날짜 있는 실험·이전 세션 기록은 **역사적 근거만** 제공한다. 과거의 \`HOLD_DATE_UNKNOWN\`, \`ota_authority_unresolved\`, 구형 \`exact_gate\`가 “원하는 최종 정책”이라는 의미가 아니다. 코드가 아직 해당 정책으로 실행 중일 수 있으므로 리팩터링 때는 회계 안전과 동작 비교를 반드시 확인한다.

## 2. 제품 목표: 거래 100건을 더 적은 사용자 작업으로 처리

- **최초 진실은 실제 카드 매입 원행**: 중복, 원본 불일치, 승인만 있고 매입이 없거나 취소·환불의 금융 검증이 불완전하면 내부 비용 준비 불가. OTA 예약 존재만으로 비용 1건 추가 생성하지 않음.
- **OTA 링크와 지출표 준비는 독립**: 원본 카드가 금융상 유효하면 OTA 예약이 \`EXACT\`, \`INFERRED\`, \`UNLINKED\`여도 최선의 **존재하는** 여행에 우선 귀속시키고 내부 비용 작성/미리보기를 허용한다. 이용기간이 존재하면 결제일보다 우선. 신뢰가 낮더라도 근거를 표시한다.
- **사용자의 행 이동이 최고 권위**: 거래가 여행 A로 자동 분류된 후 사용자가 B로 옮기면 즉시 저장/표시되고, 재수집·모델 결과·승인된 미래 규칙도 B를 무단으로 바꾸지 않는다.
- **AI 학습은 사후**: 이동 후 AI가 이유 예상 답변 1·2 + 직접 답변 3을 제시한다. 필요 시 짧게 추가질문하고, 조건·적용범위·영향을 보여준 뒤 사용자의 명시 승인으로 재사용 규칙 생성. AI 실패가 카드 저장·이동을 롤백하거나 장기간 차단해서는 안 됨.
- **항공권 영문 탑승자**: 한글 이름 후보·해당 여행 참가자 연결을 최대한 자동화하되 음차를 실명 신원/실탑승 사실로 확정하지 않는다. 기존 reservation/guide 정본·개인정보/보험 필드는 보호.
- **N:M 동일 금액 카드 대사**: 카드 2실거래와 OTA 2실결제는 그룹 정합성이 있으면 2:2로 처리; 개별 카드↔예약 식별은 별도 근거가 있을 때만 확정. 2:3의 그룹 수량 불일치는 확정 금지. 카드 비용은 실제 원행별 1행.
- **Google은 유일 최종 정본**: COST의 준비, 미리보기, 복사 버튼이 Google 반영 완료라는 뜻이 아니다. 사용자 직접 Google에 붙여넣고 COST는 읽기 전용. 추정 예약번호는 Google F열에 임의 기입하지 않는다.

### 서로 다른 상태 축(섞지 않는다)

| 상태 축 | 허용 예 | 기능 |
| --- | --- | --- |
| 카드 회계 검증 | ELIGIBLE, DUPLICATE, REFUND_UNRESOLVED, PARSE_CONFLICT | 비용 발생·이중 기장 보호 |
| OTA 연결 근거 | EXACT, GROUP_RECONCILED, INFERRED, UNLINKED, CONFLICT | 예약 식별 확실성 |
| 여행 귀속 | AUTO_EVIDENCED, AUTO_INFERRED, USER_ASSIGNED | 어느 여행에 나타낼지 |
| 내부 준비 | READY_FOR_INTERNAL_SAVE, BLOCKED_FINANCIAL, NEEDS_AUTHORIZED_TRIP | COST에 기록·복사 준비 가능한지 |
| Google 확인 | NOT_COPIED, POSTED_UNKNOWN, CONFIRMED_IN_GOOGLE | 최종 회계 정본 확인 |

**유효 카드라도 authoritative 여행 후보가 전혀 없으면** 여행을 창작하지 말고 \`NEEDS_AUTHORIZED_TRIP\`으로 남긴다. 하지만 신뢰도가 낮거나 후보가 복수라는 이유만으로 기본 미배정하지 않는다. 사용자 확정이 있다면 언제나 그 여행 유지.

## 3. 구현 순서 — 반드시 R0부터

1. **R0: Read-only 전수 진단.** 운영 소스 manifest·Agoda/메일 관측·카드 실원행·기존 pin·legacy 게이트·snapshot을 단계별로 비식별 집계. 실제 운영 DB/원문 변경 0. 이 단계 전에는 자동 정확연결 범위를 늘리지 않는다.
2. **R1: source lineage 및 파서 누락 근거.** 동일 \`record_id\`를 다른 DB가 갖는 충돌을 분리; 과거 DB 복원본을 새로운 별개 결제로 중복 생성 금지; 기존 이벤트 ID와 사용자 pin을 crosswalk.
3. **R2: 독립 후보 검색.** \`paid_on=None\`이어도 카드·금액·업체 alias·통화·증거로 후보를 만들고 날짜 UNKNOWN과 명시 불일치를 구분. 승인된 NICE 등 OTA alias를 중앙에서 사용.
4. **R3: 한 개의 전역 대사 결과.** 기존 \`app/ota_payments.py\` N:M/전역 점유 solver를 재사용하고 legacy\`match_mail→extend_report→apply_gate\` 경로는 shadow 비교 후 단계적으로 제거. 사용자 고정·환불/중복 보호.
5. **R4: A 정책 카드 금융 readiness와 OTA 독립화.** \`ota_authority_unresolved\`만으로 정상 카드 내부 비용 준비를 중지하지 않음. 카드 자체의 환불·중복·오류는 계속 막고 Google 자동 쓰기 금지.
6. **R5: 여행 이동·대화형 AI 학습** (V3 명세의 1/2/3 답변, 추가질문, 승인 규칙) 및 항공권 영문명→한글 후보의 별도 작은 PR.
7. **R6: 구형 경로 제거/운영 단계 전환.** \`off→shadow→read→enforce\`에서 결과 비교/기존 링크 보존 확인 후 별도 배포 승인. rollback 가능한 마이그레이션.

**하지 말 것:** 초반부터 광범위한 장부 rewrite, 전체 DB 재수집, 실Google 쓰기, 기존 사용자 매칭 재고정, 공개 무료 모델에 고객 원문 전송, R0도 하지 않고 “현재 50% 매칭 실패”라고 단정하기.

### 각 PR/에이전트 작업 루프

\`DISCOVER → CONTRACT → IMPLEMENT → TARGETED TEST → REVIEW → COMMIT/PR → NEXT\`.

한 PR은 **한 도메인 경계**만 변경. 수정 파일→표적 테스트를 연결하며 불명확한 영향은 필요한 인접 계약만 추가. 원본·금액·환불·idempotency·사용자 확정·권한과 실제 장부 write path 보호는 영향받을 때 생략하지 않음. 코드 수정보다 테스트량을 늘리는 것이 성과가 아니며 **100건 중 사용자가 수정한 건수/실매칭 누락 이유/Google 복사까지 작업시간**이 제품 KPI다.

## 4. 실 코드/설계 현황을 혼동하지 않는다

| 종류 | 현재 확인 근거 | 의미 |
| --- | --- | --- |
| 배포·운영 사실 | [operations.md](operations.md)와 실제 운영에서 확인된 release SHA | 당시 구현/배포 증거. 최신 현재값은 현장 재확인 |
| 기존 OTA 코어 | \`app/ota_payments.py\`, \`app/ota_portal.py\`, \`app/ota_mail.py\` | 날짜가 없는 charge의 후보를 차단하는 이전 코드가 있음 |
| 기존 기록 게이트 | \`app/ota_exact.py\`, \`webapp/card_flow.py::_ota_group_holds_base\` | 일부 OTA 미확정 자체가 장부 기록을 막는 운영 구현이 있음 |
| 기존 검토 | \`webapp/ota_payment_review.py\`, \`webapp/ota_snapshot.py\`, \`webapp/ledger_store.py\` | 수동 pin·안전/비동기/기록 보호. 보존하고 진단 연결 |
| **PR #87** | [PR #87](https://github.com/6Soo/cost/pull/87) | 문서와 \`30000\`/\`30000.00\` Decimal N:M 수정을 push했으나 main 미병합, 합성 표적 pytest 미실행 |
| R0~R6 | 상세 명세에 계획 | **아직 신규 통합 엔진/정책 A 런타임 구현 아님** |

이것은 소스 코드 자체를 변경하는 지침이 아니다. 코드의 실제 보호 체크와 위 목표가 충돌하면 **금융 데이터 보존·사용자 결정 우선의 구현**을 설계하고 합성 테스트로 새 변경을 점진 적용한다.

## 5. 기능별 정확한 세부 명세 진입점

| 작업 | **읽을 유일한 세부 명세** | 보조 권위 |
| --- | --- | --- |
| R0~R4: OTA↔카드 미매칭, 소스 충돌, N:M, 비용 준비 | [OTA–카드 통합 A 정책](ota-card-reconciliation-policy-a-v3.md) | 실제 \`app/ota_payments.py\` 등 현재 코드 |
| R5: 여행 자동 배정, 사용자 A→B, AI 1/2/3 대화 규칙 | [COST V3 구현](cost-v3-inference-ai-passenger-nm-test-architecture.md) | \`webapp/ledger_store.py\` 사용자 override |
| 항공권 영어 이름/여행 참가자 | [COST V3 구현 §4](cost-v3-inference-ai-passenger-nm-test-architecture.md) | \`6Soo/reservation\` 실제 schema/API |
| Google 수입/지출/B:H/권한 | [Google 정본 목표](target-workflow-google-authority.md) | [실측 B:H 열](google-workbook-layout.md) |
| 카드 원본/취소/환불 안전 | [확정 업무 규칙](business_rules.md), [원행 처리](card_pipeline.md) | 기존 보호 테스트·운영 코드 |
| 정확한 사용자 확정 예외/여행 종료일 | [사용자 확정 규칙](reconciliation-rules.md) | \`tests/test_owner_rules.py\` |
| 어떤 것이 실제 배포됐나 | [운영 이력](operations.md) | 검증 가능한 live 상태·git SHA |

## 6. 레거시 문서 처리 원칙

- 과거 OTA 코어·파일별 매칭·승인 defaults 제안·UI pilot·검증 계획·이전 에이전트 플레이북은 \`docs/archive/ota-legacy-20261023/\`에 **원문 그대로** 보존하고 이전 경로에는 이 문서/원문을 가리키는 얇은 안내만 둔다.
- 과거 정밀한 실측 보고서(\`ota-first-verification-report.md\`), 운영 기록(\`operations.md\`)은 삭제하지 않고 **역사 자료임을 상단에 명기**. 숫자는 그 날짜의 snapshot에만 해당한다.
- 기능별 여전히 실제로 유효한 규칙(\`reconciliation-rules.md\`, \`business_rules.md\`, \`target-workflow-google-authority.md\`)은 보존하되 이 문서의 **최신 사용자 결정과 충돌하는 범위**를 명시.
- 문서의 교정은 코드/운영 검증이나 사용자 결제를 완료했다고 주장할 근거가 아니다.
