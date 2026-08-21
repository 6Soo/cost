# 현재 상태

> 후속 코드 보정(2026-08-12): Gate5 queue 크기 5건·10그룹은 advisory SLO로
> 전환했고, `shadow_ready`/`release_ready`를 분리했다. 이 문서 아래의 후보 수치와
> `accepted_with_auto_provisional_queue`는 보정 전 최신 전체 후보의 측정 이력이다.
> 새 코드는 표적 시험 후 별도 후보를 재실행하기 전까지 그 수치를 덮어쓰지 않는다.

## Gate5 triage·release 분리 후속 검증

- Gate5의 유일 미배정 5건·사용자 질문 10그룹은 `advisory_only` queue SLO로
  전환했다. 초과 경고는 보존하지만 triage correctness를 단독 실패시키지 않는다.
- hard 조건은 전체 lane 완전성·상호배타성, `untriaged_nonfinal=0`, 비최종 행의
  confirmed decision·plan·allocation·journal·reversal derivation/inheritance 0이다.
- `report.passed == report.release_ready`를 builder와 P07에서 강제한다. 분석 성공은
  별도 `shadow_ready`이며 shadow-only 산출물은 candidate DB를 설치하지 않는다.
- 격리 재실행 `/tmp/cost-shadow-readiness-20260812-final1/artifacts/72961a7c3a334e6ea3cb5bf4cf88719b-68726a34736e`는
  5,328건에 대해 `pipeline_status=TRIAGE_PASS`, `shadow_ready=true`,
  `release_ready=false`, `passed=false`, `output_db=null`을 냈다. Gate5는
  `nonfinal_count=3,144`, `nonfinal_side_effect_invariant=true`였다.
- P07 재검증은 `artifact_state=not_published`, candidate DB reference 없음으로
  통과했다. Gate6 baseline과 HAN equality는 release 차단 상태를 유지한다.
- 회귀: `test_transition_gates_v2` 60/60, `test_direct_projection` 32/32,
  `py_compile`, `git diff --check` PASS.
- 별도 GPT-5.6 Sol high 최종 검증: `VERDICT: PASS`.

작성 기준: `2026-08-12`, `Asia/Seoul`

## 한 줄 상태

미완료 여행 배정 지표는 9건에서 1건으로 줄었다. 여덟 건은 근거 보존형
`UNKNOWN/미상` 임시활동 검토 lane으로 이동했고, NICE 국내 PG 환불 한 건은 미배정으로
남았다. Gate5는 통과했지만 Gate6 승인 baseline이 없어 후보 전체는 fail-closed다.

## 저장소 상태

- 저장소: `C:/AX/cost`
- 브랜치: `codex/p07-canonical-cutover-candidate`
- 기준 HEAD: `243fb8240eddbbcd71133c0788f8561064c5a2e4`
- worktree: dirty; 기존 사용자 변경을 보존한다.
- 최신 인계 패키지: `docs/handoff/2026-08-12/README.md`

## 이번 세션이 기록하는 코드 변경

### UNKNOWN 임시활동 보정

`ledger/domain/direct_trip_cluster_registry.py`의 혼합국가 분할 함수는 명시적 국가가
있는 행을 국가별로 나눈 뒤, 남은 markerless 행을 별도 `UNKNOWN/미상` 활동창으로
보존한다. 이는 bounded foreign-card use window일 뿐 목적지·국가·서비스기간을 생성하지
않는다. 레지스트리 membership 중복은 예외로 차단한다.

대상 결과:

- KBO: 2025-08-18~19 해외 이용 7건 → `UNKNOWN/미상` 임시활동
- CARPISA: 2026-05-29 1건 → `UNKNOWN/미상` 임시활동에 포함
- NICE: 국내 PG 환불 1건 → `여행_미배정` 유지

### Gate5 수용조건

`ledger/domain/transition_gates_v2.py`에 유일 travel-unassigned key 기준의
`TRAVEL_UNASSIGNED_ACCEPTANCE_LIMIT=5`를 연결했다. Gate5는 다음을 모두 계속 보고한다.

- `final_count=2184`
- `auto_nonfinal_count=3081`
- `auto_provisional_count=3143`
- `nonfinal_count=3144`
- `travel_open_count=3144`
- `travel_unassigned_count=1`

임시활동을 만들었다고 `nonfinal_count`나 `travel_open_count`를 줄이지 않는다.

## 최신 후보 산출물

재현 명령:

```bash
python3 -m ledger.domain.direct_projection \
  --output-db /tmp/cost-gate-current-20260812c/candidate.db \
  --output-dir /tmp/cost-gate-current-20260812c/artifacts \
  --ledger-dir ledger \
  --han-equality-output /tmp/cost-gate-current-20260812c/han-equality
```

후보는 5,328 payment를 읽었고 최신 Gate 보고서는 다음과 같다.

| 게이트 | 결과 | 이유 |
|---|---|---|
| Gate 1~4 | PASS | source/cardinality/leakage/sign 관계 검사 통과 |
| Gate 5 | PASS | `accepted_with_auto_provisional_queue` |
| Gate 6 | FAIL | `direct_baseline_unavailable` |
| Gate 7 | PASS | report freshness |

Gate6 실패로 실행 전체의 `passed=false`이며, 후보 DB를 운영 정본으로 승격하지 않았다.
HAN equality 산출물도 `applied=false`, `authority_status=unattested`, `posting_status=blocked`다.

## 검증

- `py_compile`: 변경된 registry·Gate·테스트 파일 통과
- `git diff --check`: 통과
- 대상 테스트: `Ran 106 tests in 99.707s — OK`
  - `test_direct_trip_cluster_registry`
  - `test_direct_high_coverage_classifier`
  - `test_transition_gates_v2`
- Gate5 경계 테스트: 유일 키 5건 PASS, 6건 FAIL, 중복 키 중복집계 방지 PASS
- 독립 Sol high 최종검증: `VERDICT: PASS`

전체 후보 명령의 비영(非零) 종료는 Gate6 baseline 부재에 따른 의도된 fail-closed 결과이며,
Gate5·코드·대상 테스트의 실패로 기록하지 않는다.

## 표시용 질문 큐의 주의점

최신 `question_queue.json`은 화면 표시용 owner/metadata 질문 묶음을 만들기 때문에
`travel_unassigned` 표시 그룹이 0으로 보일 수 있다. authoritative 값은 Gate5
`actual.travel_unassigned_count=1`이며, 이를 질문 UI 그룹 수로 대체하지 않는다.

## 모델·검증 이력

- AGY Gemini 3.6 Flash low: `GEMINI_API_KEY` 부재로 호출 실패
- Luna max: 설계 수용·코드 반영·후보 재산출
- Sol high 설계 1차: FAIL 후 수정
- Sol high 설계 2차: PASS
- Sol high 최종 독립검증: PASS
