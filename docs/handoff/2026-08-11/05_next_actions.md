# 다음 작업

## 시작 전

1. 이 폴더의 모든 문서를 읽는다.
2. `04_artifact_manifest.md`의 안정 보관본과 SHA256을 확인한다.
3. `git status --short`와 snapshot을 비교한다.
4. 기존 변경을 reset/checkout하지 않는다.
5. 보호된 Kimi visible log와 Sol replay의 결과·해시를 먼저 확인한다.
6. 대화 continuation과 최초 transcript snapshot을 합쳐 최신 사용자 결정을 복원한다.

## Phase 2 재설계

Sol Phase 2 설계 FAIL 사유를 먼저 해결한다.

- 대만 후보 65건의 구성 차이를 설명한다.
- 65건(분류기), 57건(`overseas_default`), 66건(별도 Agoda 앵커 포함)을 별도 모집단으로 유지한다.
- `0107_대만`을 일반 geographic context와 분리한다.
- canonical allocation에 허용할 별도 경로를 명시한다.
- OTA·항공·결제대행·선결제 예약형을 새 경로에서 제외한다.
- 2025년·기간 밖·취소·환불·TWD-only·표식 없는 행을 음성 테스트로 추가한다.

Sol 설계 `VERDICT: PASS` 전에는 Phase 2를 구현하지 않는다.

## 실행·검증 순서

1. Phase 2 코드와 테스트 구현
2. targeted tests
3. 전체 후보 1회 실행
4. baseline 대비 final 유지·신규 final·되돌림·잔여 unresolved 측정
5. Sol high 최종검증
6. Gate 4·Gate 6 확인
7. 모든 게이트와 독립검증 PASS 후에만 게시·전기 검토

## 금지사항

- unresolved 숫자만 줄이기 위해 provisional을 final로 승격하지 않는다.
- 0107_대만 65건을 일괄 확정하지 않는다.
- Yakushima 2:1, Mongolia 1:2 M:N을 자동 확정하지 않는다.
- 결제일만으로 OTA 행사일을 만들지 않는다.
- 수기장부를 카드 거래 영수증처럼 사용하지 않는다.
- Gate 5 통과만으로 cutover PASS라고 말하지 않는다.
- Gate 4 equality와 Gate 6 baseline을 생략하지 않는다.
- 역사적 검토 요약과 새 replay 원문을 같은 출처로 합치지 않는다.
