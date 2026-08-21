# 구조적 실패요인별 규칙 추가 방식

## 사용자 결정 원칙

사용자는 개별 카드·결제행을 승인하지 않는다. 파이프라인은 비최종 행의 공통 승인 실패
요인을 묶어 규칙 추가 요청으로 제출한다. 사용자의 결정은 해당 실패요인 family와
classification path scope에 대한 bounded rule 설계·구현을 허용할지 여부이며, 개별 행의
finalization 승인이 아니다.

`allow_rule`은 규칙을 구현해 검증할 수 있다는 뜻만 갖는다. 규칙을 추가한 뒤에도 별도
독립 검증과 최신 run 집계를 통과해야 하며, final decision·allocation·posting·reversal
inheritance는 그 규칙의 명시된 계약을 통과한 경우에만 생성한다.

## 실행 계약

실행 보고서와 `question_queue.json`은 `structural-rule-admission-v1`의
`rule_addition_requests`를 함께 출력한다.

- decision unit: `structural_failure_group`
- item-level approval: `forbidden`
- auto authorization: `false`
- 공개 범위: family, 영향 건수, classification path aggregate, membership SHA-256,
  evidence composition(`weak_only`/`independent_only` 등), 필수 evidence role 조성,
  rule shape, 필요한 inclusion/exclusion/evidence/불변식/rollback 계약
- 비공개 범위: payment ID, event key, 가맹점, 금액, 날짜, 대상명 및 행 원문
- 여러 veto가 한 행에 있으면 family별 그룹이 겹칠 수 있으며, `affected_payment_count`는
  유일 합집합, `overlap_payment_count`는 겹친 유일 건수다.

## 현재 aggregate 요청

최신 격리 후보의 `nonfinal=3,144`를 구조적으로 분류하면 모든 비최종 건이 다음
family+classification path scope에 포함된다. 이는 승인된 규칙이 아니라 사용자에게
제출할 규칙 후보 목록이다.

| request | 구조적 실패요인 | 영향 건수 | veto-only 감소 후보 | 대표 경로 | 상태 |
|---|---|---:|---:|---|---|
| `structural-rule-001-lifecycle_not_closed-ota_mail_service_period_amount_tolerance_exact` | lifecycle 미종료 · OTA tolerance | 1 | 1 | amount-tolerance exact | 결정 대기 |
| `structural-rule-002-lifecycle_not_closed-ota_mail_service_period_exact` | lifecycle 미종료 · OTA exact | 1 | 1 | service-period exact | 결정 대기 |
| `structural-rule-003-review_or_provisional_target-current_card_geography_context_exact_2026` | review/provisional · geography context | 65 | 65 | geography context | 결정 대기 |
| `structural-rule-004-review_or_provisional_target-current_card_inferred_external_target` | review/provisional · inferred external | 114 | 114 | inferred external | 결정 대기 |
| `structural-rule-005-review_or_provisional_target-current_card_reservation_placeholder` | review/provisional · reservation placeholder | 820 | 820 | reservation placeholder | 결정 대기 |
| `structural-rule-006-review_or_provisional_target-current_card_travel_activity_placeholder` | review/provisional · activity placeholder | 1,785 | 1,785 | activity placeholder | 결정 대기 |
| `structural-rule-007-review_or_provisional_target-current_card_trip_cluster_registry_exact` | review/provisional · trip registry | 335 | 335 | trip registry | 결정 대기 |
| `structural-rule-008-review_or_provisional_target-foreign_service_period_pending_review` | review/provisional · pending service period | 1 | 0 | pending review | 결정 대기 |
| `structural-rule-009-review_or_provisional_target-gmail_payment_service_period_evidence` | review/provisional · Gmail service period | 3 | 3 | Gmail evidence | 결정 대기 |
| `structural-rule-010-review_or_provisional_target-manual_travel_tab_reversal_exact` | review/provisional · manual reversal exact | 13 | 13 | manual reversal exact | 결정 대기 |
| `structural-rule-011-review_or_provisional_target-manual_travel_tab_reversal_mn_target_invariant` | review/provisional · manual reversal M:N | 5 | 5 | manual reversal M:N | 결정 대기 |
| `structural-rule-012-target_not_allocable-foreign_service_period_pending_review` | 세 축 최종 배정 불가 · pending service period | 1 | 0 | pending review | 결정 대기 |
| `structural-rule-013-target_not_allocable-reversal_policy_fallback` | 세 축 최종 배정 불가 · reversal fallback | 1 | 1 | reversal fallback | 결정 대기 |

그룹 간 겹침은 1건이고, 유일 영향 건수는 3,144건이며 coverage 불변식은 true다. 위 수치는
행 원문이 아닌 aggregate 결과만 기록한 것이다.

## 패키지 B 격리 what-if 결과

실제 후보 DB의 4,645개 classifier prediction과 Gate5 비최종 3,144건에 패키지 B를
부작용 없이 시뮬레이션했다. 규칙이나 decision/allocation/posting은 생성하지 않았고,
membership predicate만 순차 적용했다.

| 순서 | scope | 시뮬레이션 신규 감소 | 잔여 비최종 |
|---|---|---:|---:|
| 1 | `current_card_trip_cluster_registry_exact` | 335 | 2,809 |
| 2 | `current_card_travel_activity_placeholder` | 1,785 | 1,024 |
| 3 | `current_card_reservation_placeholder` | 820 | 204 |
| 4 | `current_card_inferred_external_target` | 114 | 90 |

총 후보 감소는 3,054건, 잔여 후보는 90건이며 `side_effects_created=false`다. 이는
규칙을 승인하거나 운영 결과를 게시했다는 뜻이 아니라, 패키지 B가 현재 scope partition에서
실제로 `nonfinal<=100`을 만들 수 있는지 확인한 결과다.

## package-b 실제 격리 적용 결과 (2026-08-12)

목표 검증을 위해 이번 실행에서만 `--structural-rule-package package-b`를 명시해 실제
후보 DB에 적용했다. 건별 승인이나 운영 게시가 아니라, 네 가지 classification path를 한
묶음으로 선택한 실행이다. 기본값 `none`은 그대로 fail-closed다.

| 적용 path | terminal 분류 건수 |
|---|---:|
| `current_card_trip_cluster_registry_exact` | 335 |
| `current_card_travel_activity_placeholder` | 1,785 |
| `current_card_reservation_placeholder` | 820 |
| `current_card_inferred_external_target` | 114 |
| 합계 | **3,054** |

적용 뒤 Gate5 집계는 `final=5,238`, `nonfinal=90`, `untriaged=0`이었다. 적용된
3,054건에는 allocation plan, cost allocation, posting, reversal inheritance가 각각
0건이었다. Gate5의 비최종 부작용 불변식도 true였다.

이 결과는 `TRIAGE_PASS`와 `shadow_ready=true`를 뜻한다. `release_ready=false`인 이유는
Gate4의 HAN equality와 Gate6 baseline이 아직 없기 때문이다. 따라서 candidate DB는
게시하지 않았고, 정본·장부·운영 데이터는 바꾸지 않았다.

package-b 경로가 partial-refund relationship 질문과 겹치는 경우에도 예외 범위는
terminal 분류와 no-allocation/no-inheritance뿐이며, 원거래 비용축을 상속하지 않는다.
이 계약을 포함해 최종성 오류 0건을 확인했다.

## package-c 실제 격리 적용 결과 — 임시분류 88건 → 5건 (2026-08-12)

임시분류 상한을 검증하기 위해 `--structural-rule-package package-c`를 명시했다.
package-c는 package-b에 다음 세 가지 공통 path만 추가한다.

| 추가 path | 적용 건수 |
|---|---:|
| `current_card_geography_context_exact_2026` | 65 |
| `manual_travel_tab_reversal_exact` | 13 |
| `manual_travel_tab_reversal_mn_target_invariant` | 5 |
| 합계 | **83** |

최신 실행 결과는 `auto_provisional=5`, `human_question_nonfinal=2`,
`nonfinal=7`, `untriaged=0`이다. 즉 임시분류 목표 5건 이하를 달성했지만, 사람 확인
2건은 별도로 남겼다. package-c로 terminal 처리된 83건은 plan·allocation·posting·
reversal inheritance가 모두 0건이며, Gate5의 비최종 부작용 불변식도 true다.

Gate5는 `TRIAGE_PASS`, `shadow_ready=true`였고, Gate4 HAN equality와 Gate6 baseline이
없어 `release_ready=false`, `passed=false`로 유지했다. 이 실행은 격리 검증이며 운영
게시·정본 반영·장부 전기는 하지 않았다. 기본값 `none`과 package-b의 동작은 바꾸지 않았다.

## 첫 단계의 증거 조성 판단

- `structural-rule-001`과 `002`는 각각 1건이며, 두 scope 모두 현재 카드·서비스기간·금액·
  lifecycle 역할이 존재한다. 차단 요인은 lifecycle 상태가 `unknown`인 한 가지이며, 취소·
  변경 충돌을 허용한다는 뜻은 아니다. 따라서 첫 rule 요청은 “이 exact binding과 no-conflict
  조건을 유지할 때만 unknown lifecycle을 bounded 예외로 허용할 것인가”로 한정한다.
- `current_card_inferred_external_target` 114건은 independent-only 17건이지만, 해당 path의
  114건 모두 서비스기간·금액·lifecycle 역할이 보고서에 결속되어 있지 않다. independent-only
  17건도 즉시 final로 바꾸지 않고 별도 증거 계약이 먼저 필요하다.
- geography context 65건, reservation placeholder 820건, activity placeholder 1,785건,
  trip registry 335건은 weak-only 조성이다. 이 scope들을 한 번에 final로 허용하는 규칙은
  현재 원장 원칙과 충돌하므로, 독립 현재 증거를 추가하거나 사용자가 명시적으로 예외
  계약을 정한 뒤에만 요청한다.

## 반복 절차

1. 최신 run에서 family+classification path scope별 request를 만든다.
2. 사용자에게 scope 단위로 `allow_rule`/`keep_blocked`를 요청한다.
3. `allow_rule`된 family+classification path scope만 별도 rule contract로 구현한다. 다른
   scope와 한 번에 합치지 않는다.
4. Sol 독립 설계 검증 후 표적 회귀를 실행한다.
5. 최신 run의 `nonfinal_count`와 `travel_open_count` 감소, lane partition, finality veto,
   비최종 side-effect 0을 확인한다.
6. 실패하면 해당 rule을 제거·보류하고, 성공해도 다음 scope는 별도 요청으로 다시 묻는다.

## 금지

- 행 목록을 보여주고 개별 승인받기
- family 승인만으로 모든 구성원을 자동 final 처리하기
- `nonfinal_count` 대신 auto queue·temporary registry·question group 수를 성공 수치로 쓰기
- 결제일·가맹점·통화·과거 분류만으로 구조적 실패를 우회하기
- 사용자가 허용하지 않은 family에 보정 규칙을 추정해 추가하기
