# 다음 작업

## 우선순위

0. **완료:** Gate5 triage/release 분리의 전체 표적 회귀와 격리 shadow 후보를
   검증했다. `shadow_ready=true`, `release_ready=false`, `passed=false`, DB 미게시와
   P07 `not_published`를 확인했다.

0-A. **운영 방식 확정:** 비최종 축소는 건별 승인으로 진행하지 않는다. 최신
`structural_rule_requests`를 family+분류경로 단위로 사용자에게 제출하고, `allow_rule`된 scope만
별도 계약·검증·재집계한다. 상세 계약은 `06_structural_rule_admission.md`와 원장 지시문의
최신 절을 따른다.

1. 승인된 Gate6 baseline을 복구하거나 생성하고, 현재 code bundle·input manifest에
   결속한다.
2. HAN equality 권한 있는 입력을 확보해 `applied=true`가 되는지 별도 확인한다.
3. 두 조건이 준비되면 최신 후보를 한 번 재실행하고 Gate1~7 전체 결과를 확인한다.
4. NICE 국내 PG 환불은 독립적인 서비스기간·원거래 evidence가 생길 때만 재평가한다.
   현재는 `여행_미배정`과 환불 상속 금지를 유지한다.
5. KBO/CARPISA의 실제 목적지·서비스기간을 확인할 독립 근거 또는 owner 결정을 확보한
   경우에만 `UNKNOWN/미상` 레지스트리를 후속 승격 검토한다. 현재 임시활동은 final이 아니다.
6. 대만 Phase 2는 기존 Sol 설계 `FAIL` 상태를 유지하며, 이번 세션 결과를 근거로 자동
   확정하지 않는다.

## 중단 조건

- baseline 또는 HAN equality가 없으면 게시·정본 반영·장부 전기·배포를 하지 않는다.
- 임시활동을 줄이기 위해 `final` 또는 confirmed decision을 임의 생성하지 않는다.
- 결제일·통화·가맹점명만으로 국가·목적지·서비스기간을 만들지 않는다.
- 전체 후보 보고서의 `actual.travel_unassigned_count`, `travel_open_count`,
  `nonfinal_count`를 질문 큐 표시값으로 대체하지 않는다.
