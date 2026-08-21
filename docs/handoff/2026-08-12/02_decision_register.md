# 이번 세션 결정 등록부

이 문서의 `SESSION_CONCLUSION`은 사용자 소유 데이터에 대한 새로운 owner 확정 결정이
아니라, 이번 후보 실행에서 적용한 안전한 분류·게이트 결론이다.

| ID | 결정 | 상태 | 적용 범위 |
|---|---|---|---|
| D-017 | 혼합국가 활동창에서 국가 marker가 없는 현재 해외 이용행은 별도 `UNKNOWN/미상` 임시활동으로만 보존한다. | IMPLEMENTED | 목적지·국가·서비스기간 추정 금지 |
| D-018 | KBO 7건과 CARPISA 1건은 임시활동으로 이동하되 `needs_review`/비최종 상태를 유지한다. | IMPLEMENTED | account/cost/target final, allocation, posting, refund inheritance 없음 |
| D-019 | NICE 국내 PG 환불은 원 구매의 서비스기간·대상이 확정되지 않았으므로 `여행_미배정`에 남긴다. | IMPLEMENTED | 구매행에서 비용축을 상속하지 않음 |
| D-020 | Gate5 travel-unassigned 수용 상한은 유일 key 5건이며, 5/6 경계를 테스트한다. | SUPERSEDED_BY_D-023 | 과거 후보의 운영 수용 규칙; 현재는 advisory queue SLO |
| D-021 | `travel_open_count`와 `nonfinal_count`는 임시활동 이동으로 감소시키지 않는다. | IMPLEMENTED | 최신값 각각 3,144 |
| D-022 | Gate5 통과만으로 게시·전기·배포를 진행하지 않는다. Gate6 baseline과 HAN equality 권한이 필요하다. | BLOCKED | 현재 전체 후보 `passed=false` |
| D-023 | Gate5의 5건·10그룹 수치는 correctness acceptance가 아니라 advisory queue SLO로 사용한다. | IMPLEMENTED | 초과 경고는 보존하되 triage를 단독 실패시키지 않음 |
| D-024 | `shadow_ready`와 `release_ready`를 분리하고, 호환 필드 `passed`는 release 수준을 유지한다. | IMPLEMENTED | `passed == release_ready`; P07 activation 의미 불변 |
| D-025 | 비최종 행의 confirmed decision·plan·allocation·journal·posting·reversal derivation/inheritance는 0이어야 Gate5 triage가 통과한다. | IMPLEMENTED | 수량 완화와 무관한 hard invariant |

## 금지된 해석

- `UNKNOWN/미상`을 목적지 확정으로 해석하지 않는다.
- 카드 결제일을 OTA·PG 서비스일로 바꾸지 않는다.
- NICE 환불을 서비스기간 미확정 구매에 연결해 자동 상속하지 않는다.
- `question_queue`의 표시 그룹 0을 Gate5 미배정 0으로 해석하지 않는다.
- 이전 후보의 `literal travel_unassigned=2`와 최신 후보의 `actual=1`을 합산하지 않는다.
