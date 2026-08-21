# 2026-08-12 세션 인계 패키지 — 미완료 여행 배정 9건 → 1건

> 상태: `PARTIAL_HANDOFF_REINFORCED`
>
> 이 패키지는 이번 Codex 세션의 저장소·후보 산출물·검증 결과를 요약한다. 전체 채팅
> transcript와 역사적 검토 원문을 새로 export한 것은 아니므로 `LOSSLESS_HANDOFF`로
> 승격하지 않는다. 후보 게시·정본 반영·장부 전기·배포는 수행하지 않았다.

## 다음 세션의 시작점

1. `AGENTS.md`와 이 파일을 읽는다.
2. `01_current_state.md`에서 최신 수치와 후보 보고서 경로를 확인한다.
3. `02_decision_register.md`와 원장 규칙의 2026-08-12 보정 절을 적용한다.
4. `05_next_actions.md`의 Gate 4·Gate 6 복구 순서를 따른다.
5. `LOG.md` 맨 아래 이 세션의 핸드오프 블록을 확인한다.

## 세션 결론

> 후속 보정: Gate5의 5건·10그룹은 이제 advisory queue SLO이며, Gate5는
> `TRIAGE_PASS`와 release finality를 분리한다. `shadow_ready`는 분석 성공만,
> `release_ready`와 호환 필드 `passed`는 게시·전기 가능성만 뜻한다. 아래 기존
> 후보 수치와 당시 Gate5 문구는 2026-08-12 측정 이력으로 보존한다.

후속 격리 검증은 5,328건에서 `TRIAGE_PASS`, `shadow_ready=true`,
`release_ready=false`, `passed=false`, `output_db=null`을 확인했다. Gate6·HAN 차단과
미게시 상태는 유지됐고, transition 60건·projection/P07 32건 및 별도 Sol high 최종
검증이 모두 PASS했다. 상세값은 `01_current_state.md`의 후속 검증 절을 따른다.

- 이전 격리 후보에서 `travel_unassigned` 9건은 KBO 7건, CARPISA 1건, NICE 국내 PG 환불
  1건이었다.
- KBO 7건과 CARPISA 1건은 국가·목적지·서비스기간을 추정하지 않는 `UNKNOWN/미상`
  임시활동 레지스트리로 이동했다. 이 이동은 `needs_review`/비최종 상태만 바꾸며,
  세 축 확정·배분·전기·환불 비용축 상속을 만들지 않는다.
- NICE 국내 PG 환불은 원 구매의 서비스기간이 확인되지 않아 `여행_미배정`에 남겼다.
- 최신 후보 Gate5 실제값은 `travel_unassigned_count=1`, `travel_open_count=3144`,
  `nonfinal_count=3144`다. 수용 상한은 유일 키 기준 5건이다.
- Gate5는 `accepted_with_auto_provisional_queue`로 통과했지만 Gate6은
  `direct_baseline_unavailable`로 실패했다. 전체 후보는 차단 상태이며 cutover PASS가 아니다.
- 독립 Sol high 최종검증은 `VERDICT: PASS`였다.

## 이전 기록과의 수치 차이

기존 `docs/handoff/2026-08-11`의 2026-08-12 보강 기록에는 다른 후보·측정 시점의
literal `travel_unassigned=2`가 남아 있다. 이 패키지의 최신 전체 후보 보고서
(`/tmp/cost-gate-current-20260812c`)가 그 이후의 authoritative 측정이며, `1`을 사용한다.
두 후보를 합산하거나 같은 실행의 값으로 해석하지 않는다.

## 문서 구성

| 파일 | 내용 |
|---|---|
| `README.md` | 이번 세션의 결론·보존 범위·시작점 |
| `01_current_state.md` | 최신 코드·수치·게이트·검증·산출물 |
| `02_decision_register.md` | 이번 세션에 적용한 분류·수용·차단 결정 |
| `04_artifact_manifest.md` | 후보 보고서·해시·재현 명령 |
| `05_next_actions.md` | 다음 실행 순서와 금지사항 |
| `06_structural_rule_admission.md` | 건별 승인 금지와 구조적 실패요인별 규칙 요청 계약 |

## 최신 package-b 격리 실행 결과

목표 검증을 위해 `--structural-rule-package package-b`를 명시한 최신 shadow 실행에서는
네 범위를 실제 분류 경로로 적용했다. 결과는 `final=5,238`, `nonfinal=90`,
`untriaged=0`, Gate5 `TRIAGE_PASS`, `shadow_ready=true`였다. 적용된 3,054건의
allocation plan·cost allocation·posting·reversal inheritance는 모두 0건이다.

다만 Gate4 HAN equality와 Gate6 baseline이 없어 `release_ready=false`, `passed=false`,
`output_db=null`이다. 따라서 운영 반영·게시·전기는 하지 않았다. 이 실행은 목표 수치가
가능한지 확인한 격리 결과이며, 네 범위는 건별 승인이 아닌 하나의 run-scoped package 선택으로
적용됐다. 기본 실행은 여전히 `package=none`이다.

## 최신 package-c 격리 실행 결과

임시분류 상한 검증을 위해 `--structural-rule-package package-c`를 명시했다. package-b에
지리 문맥 65건, 수기 환불 정확 연결 13건, 수기 환불 다대일 안전 연결 5건을 추가해
`auto_provisional=5`, `human_question_nonfinal=2`, `nonfinal=7`, `untriaged=0`을 만들었다.
Gate5는 `TRIAGE_PASS`, `shadow_ready=true`였고, 적용된 83건의 plan·allocation·posting·
reversal inheritance는 모두 0건이다.

Gate4 HAN equality와 Gate6 baseline이 없어 `release_ready=false`, `passed=false`다.
따라서 운영 반영·게시·전기는 하지 않았다. 이 결과는 임시분류 5건 이하를 확인한 격리
실행이며, 건별 승인이 아닌 공통 path 묶음 선택으로 적용됐다.

## 보존 규칙

- `/tmp` 후보 보고서에는 민감한 원장·카드 값이 포함될 수 있으므로 저장소에 복사하거나
  커밋하지 않는다.
- Gate5 통과를 전체 성공으로 말하지 않는다.
- `auto_provisional`, `UNKNOWN/미상`을 `final`로 세지 않는다.
- `question_queue.json`의 표시용 `travel_unassigned` 그룹 수와 Gate5의 권위 있는
  `actual.travel_unassigned_count`를 혼동하지 않는다.
