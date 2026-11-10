# 도구 없는 P2 런타임 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. 현재 본체 작성자는 sol 한 명이며 합성 스키마·픽스처만 EXAONE에 분리한다.

**Goal:** Worker가 고객 원문과 규칙을 직접 주입하고 코드가 검증하는 P2를 기존 금융 보호 경로에 연결한다.

**Architecture:** Worker가 사건 자료를 조립하고 빈 cwd의 도구 없는 Codex에 stdin으로 보낸다. 모델의 JSON은 스키마·후보·요청 지문·실제 실행 정보·신선도·금융 보호 검증 후 기존 원자적 교정 경로로 반영한다. 추가 조회는 Worker의 허용된 repository만 실행한다.

**Tech Stack:** Python, SQLite, 기존 jsonschema, Codex CLI, Windows PowerShell.

**Spec:** [통합 명세 §6](../../SPEC.md#6-p2-런타임), 2026-11-11 Fable D1 결정. 이 문서는 해당 승인 범위의 구현 순서이며 별도 정책 정본이 아니다.

## 공통 제약

- 고객 원문은 구독 프론티어 P2에만 제공한다. 무료 작업자는 코드와 순수 합성 자료만 사용한다.
- 파일·셸·네트워크 도구 실행 불가, read-only/never 유지, full-access/bypass 대체 금지. OS 격리 성공을 주장하지 않는다.
- 원문·금액·부호·ID·수동 교정·정확 연결·환불·중복·원본 충돌 보호, Google 자동쓰기 금지를 유지한다.
- 프롬프트 상한은 262144 UTF-8 bytes, 필수 CORE/스키마 보존, 근거 절단 사실 표시. 초기 196608 bytes는 link·refund가 함께 필요한 단건의 필수 정책 본문 207124 bytes도 담지 못해 독립 검수 후 상향했다. 추가 조회·문의는 최대 2회.
- 본체 sol 소유: app/p2_case.py, app/frontier_agent_provider.py, 기존 provider/분류/Worker 연결과 관련 신규 검사. EXAONE 소유: app/p2_output.schema.json, tests/fixtures/p2_tool_free/, tests/test_p2_output_schema_fixtures.py. 공유 명세·BOARD·handoff는 관리자만 쓴다.

## 검수 초점

- 근거 원문 속 명령·URL·프롬프트 지시를 데이터로만 취급하고 모델 도구 실행이나 임의 Worker 조회로 연결하지 않는다.
- 긴 근거가 필수 규칙·스키마·대상 거래를 밀어내지 않으며 절단을 숨기지 않는다.
- 추가 근거 요청과 최종 판정을 구분하고 대상 누락·중복·가짜 실행 정보는 적용하지 않는다.
- 조회 중 수동 교정·여행·규칙이 바뀌면 재조립하며 원자 반영을 깨지 않는다.
- 400건 넘는 대상·한도·타임아웃·예약 로그온 맥락에서도 누락 없는 재개와 소유 프로세스 종료를 확인한다.

## D2: 사건 조립과 합성 스키마

**Files:** app/p2_case.py, app/p2_output.schema.json, tests/test_p2_case.py, tests/test_p2_output_schema_fixtures.py, tests/fixtures/p2_tool_free/.

**Interfaces:** `assemble(conn, trips, request, *, repository=None, max_bytes=262144)`는 기존 `ai_classification.prepare` 요청을 보존한다. repository의 `select(case, raw_transaction)`와 `lookup(kind, query, transaction_id)`는 `{ref,kind,content,transaction_id}` 목록을 반환한다.

- [ ] 합성 원문·CORE/영역 선택·프롬프트 상한/절단·악성 문자열을 검증하는 실패 테스트부터 작성한다.
- [ ] 최소 조립기를 구현하고 `python -m pytest tests/test_p2_case.py -q`로 확인한다.
- [ ] 스키마의 모든 object는 additionalProperties=false, 속성 전부 required. 유효 최종/추가조회 전용과 잘못된 타입·추가키·조회종류 fixture를 검증한다.
- [ ] `python -m pytest tests/test_p2_output_schema_fixtures.py -q`와 diff check 후 분리 커밋을 본체에 통합한다.

## D3: 실행·검증·반영

**Files:** app/frontier_agent_provider.py, app/connected_agent_provider.py, app/ai_classification.py, 필요한 classification_correction 연결, webapp/autonomous_cleanup_worker.py, 관련 신규 표적 테스트.

**Interfaces:** `run_agent(request, *, bundle, repository=None, runner=None, model='gpt-6.1-sol', timeout=180)`. runner는 `(command, cwd, env, timeout, input_bytes)`로 stdin을 받으며 기존 `_run_bounded` 호출 호환을 유지한다. Worker에는 `evidence_repository`를 생성자 주입한다.

- [ ] stdin·빈 cwd·read-only/never·도구 이벤트 거부·잘못된/누락된 JSON·가짜 실행 정보·최대 2회 조회·소유 프로세스 종료 테스트를 작성한다.
- [ ] 직접 CLI 어댑터와 Worker 연결을 구현하고 새 표적 테스트 및 기존 provider/prepare/preview/apply 보호 검사를 실행한다.
- [ ] schema 통합 뒤 최소 합성 호출로 도구 미실행·JSON 완료를 관찰한다. 검증되지 않은 Claude/Paseo 대체를 등록하지 않는다.
- [ ] 요청 신선도·후보·날짜·근거·정확한 대상 수를 검증하고 기존 correction 단일 트랜잭션과 변경 전 이력을 사용한다. 표적 검증 후 커밋한다.

## D4: 전체 탐지와 실행 예산

**Files:** webapp/autonomous_cleanup_worker.py 및 관련 신규 Worker 테스트·전용 영향 매핑.

- [ ] 400건을 넘는 합성 대상에서 중복·누락 없는 페이지 순회, 수동/정확 연결 보호, 첫 50건 중단, 예산·야간 시간·quota 대기 테스트를 작성한다.
- [ ] 기존 P1 선게시를 유지하며 제한과 재개를 구현하고 표적 검증 후 커밋한다.
- [ ] 관리자가 실제 통과 조건과 `python tools/run_quality_checks.py --base origin/main --run`을 실행한다. 기준선 실패는 같은 SHA와 비교하며 0건·skip을 통과로 삼지 않는다.

## D5: 실제 Worker 검증과 첫 묶음

- [ ] 실제 예약 Worker 맥락에서 순수 합성 사건의 조립→CLI→검증→종료를 확인한다. 개발 셸 호출 결과로 대체하지 않는다.
- [ ] 독립 sol medium 이상이 정확 최종 SHA를 검수하고 정상 PR 병합 게이트를 통과한다.
- [ ] 운영 적용 전에 현재 SHA·신선 백업·복원 확인과 보호 지표를 대조하고 배포 전후 같은 레포 세션에 알린다.
- [ ] `tools/deploy_verified_release.ps1 -PreviousSha <실제현재SHA>`로 배포하고 승인된 첫 약 50건만 실행한다. 결과·보호 불변을 표본 검수한 뒤 **반드시 멈추고** Fable에 15줄 이내 보고한다. 전체 미해결 건으로 확대하지 않는다.
