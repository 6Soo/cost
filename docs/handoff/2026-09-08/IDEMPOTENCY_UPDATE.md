# 추가 인계 — 사용자 판단과 여러 에이전트의 멱등 실행

사용자는 모호한 판단이 있었는지 확인하고, 여러 에이전트가 같은 목표와 멱등 실행 기준을 따르도록 요청했다. 앞선 [전체 점검 인계](README.md)의 스냅샷과 해시는 그대로 보존한다. 이후의 문서·코드 변경과 검증은 이 추가 인계에서 구분한다.

## 사용자 판단

실제 질문한 항목은 `Q-SCHEDULE-001`이다. 일반 일정 충돌 보류와 시작일 우선 선택의 적용 범위가 명확하지 않다. 기존 확인 예외만 범위를 고정해 보존하고 나머지는 검토 대기로 두는 방안을 추천했다. 아직 선택 답변을 받지 않았으며 “계속해”는 독립 작업의 계속으로 기록했다. 해당 매칭 코드와 기존 실패 테스트의 기대값을 바꾸지 않았다.

멱등성의 업무 의미 기준, 여행 종료일 보존, 양식 정정, 구매와 취소·환불 분리, 후보와 전기 권위 구분은 이미 근거가 있다. 다시 사용자에게 승인받을 문제로 만들지 않았다. [결정 등록부](../../DECISION_REGISTER.md)에 확정 근거·미결정·구현 절차를 구분했다.

## 에이전트 공통 문서

- [실행 규약](../../AGENT_EXECUTION_CONTRACT.md): 목표, 파일 해시와 의미 해시, 재시도·중복 효과, 단독 작성자, 단계별 재개, 작업 명세, 최소 수용 검사를 정의했다. 요구 조건과 실제 구현 완료를 구분한다.
- `AGENTS.md`: 공통 목표, 읽기 순서, 미답변 질문, 최신 양식을 연결했다.
- `CLAUDE.md`: 독자적인 업무 지침 복제를 제거하고 `AGENTS.md`로 연결했다. 기존 공통 본문은 `AGENTS.md`에 보존돼 있다.
- 비용 규칙 원장: 옛 P28과 잘못된 열 설명에 명시된 후속 정정을 연결했다. 지출 C열 고객명 매핑 작업을 반복하지 않게 했다.

문서만으로 동시 작성 잠금이나 원격 중복 전기가 구현됐다고 보고하지 않는다. 실행기 지원이 검증되지 않은 경로는 단일 작성자를 사용한다.

## 이전 테스트 생략 원인 확인

`ledger/tests/_platform.py`를 읽어 `allow_pin_drift`가 단순 실행 활성화 스위치임을 확인했다. `COST_ALLOW_PIN_DRIFT=1`은 테스트 기대값이나 고정 해시를 바꾸지 않는다.

```powershell
$env:COST_ALLOW_PIN_DRIFT='1'
python -W error -m pytest ledger/tests/test_direct_verified_ota_lodging.py -q
```

실행 결과는 **10 passed**다. [원본 실행 기록](pin-diagnostic-full.xml)을 보존했다. 기존 생략 8건은 이 모듈에서 사용자 업무 판단이 필요한 승인 문제가 아니었다. 다른 모듈의 권위 기준값이나 준비된 원천을 요구하는 검사까지 통과한 것으로 확대하지 않는다. 전역 환경 설정이나 기준값은 변경하지 않았다.

## 구현 범위와 경계

Reserve Max에는 v5 shadow의 버전 명시 의미 해시와 반복 실행 회귀 검사를 맡겼다. 파일 무결성 해시를 유지하면서 서로 다른 경로와 입력 행순서에서 같은 업무 결과가 나오는지 검증한다. 일정 정책, 실제 원장, 외부 쓰기는 이 작업에 포함하지 않는다.

구현과 통합 검증을 마쳤다. 새 감사 JSON은 `semantic_schema_version`과 `semantic_sha256`을
기록하며, 최종 DB에서 재계산해 검증한다. 의미 표현은 명시된 규칙 버전과 batches/lines의
업무 필드를 포함하고 행순서를 정규화한다. 생성 시각·경로·파일 해시·자기참조 manifest는
제외한다. 파일 전체 해시 검증은 별도로 유지한다.

v1의 열 계약을 명시해 새로운 업무 열이나 필수 열 누락이 있으면
`semantic_schema_mismatch`로 거부한다. 새 필드가 의미 비교에서 조용히 누락될 수 없다.
금액·예약번호·서비스 날짜·배정 여행의 단독 변경, 서로 다른 경로와 반대 행순서,
동일 출력 재호출의 입력·출력 보존을 합성 자료로 확인했다.

`ledger/tests/_platform.py`의 생략 안내는 승인 대기라는 표현에서 실행 스위치 안내로
고쳤다. 함수명·환경 변수·활성화 조건·테스트 기대값은 유지했다.

현재 v5 출력 경로의 재호출은 기존 파일을 보존하고 충돌 오류로 종료한다. 자동 성공 NOOP·작업 재개 실행기·원격 전기의 중복 방지는 별도 구현과 검증이 필요한 상태다. 이 추가 인계로 `PARTIAL_HANDOFF`나 `release_eligible=false`를 승격하지 않는다.

## 최종 검증

- 전체 대상 검사: **118 passed, 1 failed, 8 skipped, 경고 0건**. [실행 기록](idempotency-tests.xml).
- v5 shadow 검사는 위 통과 수에 포함된 **38개**다.
- 실패 1건은 `Q-SCHEDULE-001`과 연결된 기존 일정 겹침 테스트다. 사용자 답변 대기 상태를 테스트 수정으로 숨기지 않았다.
- 생략 8건은 구조화 숙박의 준비된 원천을 요구한다. 필요한 기본 경로의 `cost-r25-manual-v4.csv`가 실제로 없는 것도 확인했다. 빈 디렉터리를 지정하거나 기준값을 바꿔 통과시키지 않았다.
- [최신 구조 진단](pipeline-audit-idempotency.json)은 기존 자료의 감사 불일치 때문에 여전히 `blocked`다. 현행 진입점 해시는 검사 당시 코드의 해시이며, 오래된 산출물을 그 코드로 생성했다는 증명이 아니다.
- 원본 DB 4개와 워크북의 해시 보존, 변경 코드·규약·검증 자료의 해시는 [검증 manifest](idempotency-validation.json)에 기록한다. 이전 manifest는 과거 스냅샷으로 유지한다.

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:COST_ALLOW_PIN_DRIFT='1'
python -W error -m pytest ledger/tests/test_pipeline_audit.py ledger/tests/test_agoda_journal_shadow_v5_ota.py ledger/tests/test_direct_trip_schedule_authority.py ledger/tests/test_direct_ota_reservation_authority.py ledger/tests/test_direct_accounting_shadow.py ledger/tests/test_direct_verified_ota_lodging.py ledger/tests/test_direct_structured_lodging_evidence.py webapp/tests -q --tb=short -rs --timeout=45 --timeout-method=thread
```

실제 구현 에이전트의 적용 모델과 추론 설정은 [확인 기록](idempotency-agent.json)에 보존했다.
