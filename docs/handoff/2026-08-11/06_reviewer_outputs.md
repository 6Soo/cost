# 독립 검토 결과

이 문서는 현재 대화에서 확인 가능한 검토 판정과 핵심 근거를 보존한다.
역사적 검토의 요약, 새로 읽기 전용으로 재실행한 replay, Kimi의 내부 사고 필드를
제거한 보이는 이벤트 로그를 서로 구분한다. replay는 역사적 원래 반환값의 복사본이
아니다.

## Phase 1 Sol high 최종검증

- 범위: Phase 1 연도 무결성 변경과 baseline 비교
- 결론: `VERDICT: PASS`
- 핵심 확인:
  - 연도 없는 OTA MMDD는 보류
  - 2025 행사일은 2026 일정에 연결되지 않음
  - 2025 결제·2026 ISO 행사일 경로 유지
  - Gmail·현지 결제일·클러스터·지역·숙박·예약·fallback 전파 확인
  - 원본 key/hash 유지, service_year는 파생값
  - 4,645 prediction key 동일
  - 67건 보류와 1건 신규 final 수치 일치
  - 관련 테스트 60개 통과

## Phase 2 Sol high 설계검증

- 범위: 대만 `current_card_geography_context_exact_2026` 승격 설계
- 결론: `VERDICT: FAIL`
- 핵심 반박:
  - 실제 후보는 57건이 아니라 65건
  - `0107_대만`은 canonical schedule이 아니라 context target
  - 새 배분 경로를 별도로 정의해야 함
  - OTA·항공·결제대행·선결제 예약형 제외 조건 부족
  - 2025·기간 밖·취소·환불·TWD-only·표식 없음 음성 테스트 필요

## Kimi K2.7 전체 검토

- 모델 선택 첫 시도: `kimi-k2.5` 설정 부재로 실패
- 재시작: Kimi K2.7 Coding
- 결론: `KIMI_VERDICT: FAIL`
- 핵심 반박:
  - provisional이라는 이름만 바꾸는 것은 해결이 아님
  - Yakushima 2 card : 1 candidate는 자동 확정 금지
  - Mongolia 1 card : 2 candidates는 자동 확정 금지
  - 0616 동일금액 3건은 공통 대상 불변 M:N 사례
  - 0813 일부 서비스일은 2025년

## 인계 패키지 제한적 복원검사

- 독립 검토자는 인계 폴더 문서만 읽음
- 결론: 제한적 상태 재구성 가능
- 결론: 채팅 export는 완료했지만 Sol/Kimi 전체 출력 및 전체 테스트 최종 로그가 없으므로 무손실은 아님
- 판정: `HANDOFF_RECONSTRUCTION: PASS`
- 발견된 보완사항:
  - prediction 4,645행과 Gate 5 5,328 payment의 모집단 차이 명시 필요
  - stable artifact의 축약 경로 제거 필요
  - 전체 unittest 최종 출력 보존 필요
  - Sol/Kimi 전체 원문 export 필요

## 최신 독립 복원검사

- agent: `019fef68-aea6-7313-b7e2-465eda3acbd0` (GPT-5.6 Sol, 이전 문맥 없음)
- 결과: Phase 1 수치·모집단, Gate 4/6 차단, Sol/Kimi 판정, 대만 65건 제약,
  Yakushima/Mongolia/0616/0813 반례, 41/40 worktree, transcript SHA, 중단 테스트 로그를 복원함
- 판정: `PARTIAL_HANDOFF`
- 제한: Sol/Kimi 전체 독립 검토 출력은 여전히 별도 원문으로 보존되지 않았고,
  full unittest discover는 `INTERRUPTED`, `exit_code=130`임
- 최종 줄: `HANDOFF_RECONSTRUCTION: PASS`

## 보강 후 보호 보관된 검토 artifact

### Kimi visible event logs

- 첫 모델 선택 실패와 재시작을 포함한 이전 세션 보이는 이벤트:
  `C:/AX/cost-handoff-archive/2026-08-11/reviewers/kimi-session_485d98b6-f3ac-479e-b963-25a37a2c8646-visible.jsonl`
  - SHA256: `a8b38188ca1b2e2e27c7bee7a7d22c83129e5be8f607dff15a822cc36b134620`
- 최종 Kimi K2.7 전체 파이프라인 검토 보이는 이벤트:
  `C:/AX/cost-handoff-archive/2026-08-11/reviewers/kimi-session_e441a4af-05d6-4a85-8743-64000580ca81-visible.jsonl`
  - SHA256: `cab3f9802dac7aed2c83807d2e7c1368cc35f588eb1dad6b6073c80991126807`
- 두 파일 모두 `think`, `reasoning`, `systemPrompt` 키와 해당 이벤트를
  제거했다. 따라서 Kimi의 숨은 사고를 보존한 것이 아니라 사용자에게 표시된 이벤트와
  도구 메타데이터를 보존한 것이다.
- 최종 보이는 보고서의 판정은 `KIMI_VERDICT: FAIL`이다.

### Sol Phase 2 Taiwan replay

- 보호 artifact:
  `C:/AX/cost-handoff-archive/2026-08-11/reviewers/sol-phase2-taiwan-replay-20260811.md`
- SHA256: `a25996cbe5605da74062ff4ad8435907d35435ad7ce60b665854a28868672cb1`
- 판정: `VERDICT: FAIL`
- 이는 65/57/66 모집단 불일치와 `0107_대만` context-only 경계,
  OTA·항공·PG·선결제 제외 및 음성 회귀 누락을 확인한 읽기 전용 재현본이다.
- 역사적 Phase 2 Sol 원래 출력과 동일하다고 주장하지 않는다.

### Sol Phase 1 replay

- 보호 artifact:
  `C:/AX/cost-handoff-archive/2026-08-11/reviewers/sol-phase1-replay-20260811.md`
- SHA256: `c1284198894bc5ba8a782f171079ce21f1a0eff5c5c657dc706a9550083a7d13`
- 판정: `VERDICT: PASS`
- 이는 Phase 1 구현·수치·Gate 4/6·비게시 상태를 읽기 전용으로 재현한 보고서다.
- 최초 300초 대기 시간초과 시도도 별도 artifact로 남겼다:
  `C:/AX/cost-handoff-archive/2026-08-11/reviewers/sol-phase1-replay-20260811.timeout.md`
  (SHA256 `4328c7f6757cd786409eaa26536490860130c8df6cf102c040f21d8e31ddfbd0`).
- 역사적 Phase 1 Sol `VERDICT: PASS` 요약과 이 재현본을 동일시하지 않는다.

## 남은 한계

- 앱 thread export는 Sol 호출 내부 반환값 전체를 별도 item으로 노출하지 않았다.
- 따라서 역사적 Sol Phase 1·Phase 2 전체 원문을 정확히 복원했다고 말할 수 없다.
- 전체 `unittest discover`도 PASS가 아니라 `INTERRUPTED / exit_code=130`이다.
- 이 한계를 숨기지 않고 `PARTIAL_HANDOFF_REINFORCED`로 유지한다.

## 최신 독립 복원검사 최종 결과

- 보호 artifact:
  C:/AX/cost-handoff-archive/2026-08-11/reviewers/handoff-restoration-final-verification-20260811.md
- SHA256: `65e512bcd40237fdbff01f80889555a60a4995eb29bb40e75ce52d462ee75c2e`
- 독립 복원검사 당시 archive manifest: 24/24 OK. 이후 최종 점검 로그와 redaction 기록을
  추가했으며 현재 archive manifest는 26/26 artifact를 검증한다.
- handoff-files manifest: 8/8 OK
- 핵심 수치·게이트·대만 65/57/66·M:N 사례·worktree·다음 작업 복원: 일치
- 최종 판정: `HANDOFF_RECONSTRUCTION_FINAL: FAIL`
- FAIL 원인:
  1. 역사적 Sol 원래 전체 반환값은 앱 export에 노출되지 않았고 replay만 보존됨
  2. `67건 = 55+12` 세부 분해가 보존 DB에서 재현되지 않음
  3. 전체 unittest는 `INTERRUPTED / exit_code=130`이며 PASS가 아님
- 따라서 이 패키지는 새 채팅에서 작업을 이어갈 수 있을 만큼 보강됐지만,
  역사적 내부 검토 반환값까지 무손실이라고 표시하지 않는다.
