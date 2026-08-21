# 2026 임시 결제 family 승인 요청

## 한 번에 승인할 범위

- 대상: `unresolved_2026_purchase_clearing`
- 결제 건수: **1,253건**
- 금액: **189,627,699원**
- 목적: 여행 확정이 아닌 `미확정 여행원가` 회계 대기계정
- 상태: **사용자 결정 대기**

## 허용되는 효과

- 회계 후보·대기계정으로만 처리
- 기존 결제 ID와 lineage를 유지
- 차변·대변 균형과 재실행 멱등성 유지

## 허용하지 않는 효과

- 여행 확정
- 행사기간·여행코드·예약번호 추정
- 기존 journal 또는 외부 회계시스템 전기
- Gate6·HAN 승인 전 posting

## 선택

`허용` 또는 `보류`로 결정해 주세요.

원본 승인 요청 JSON: [family-approval-request-unresolved-2026-v1.json](outputs/2026-08-14-accounting-shadow-v2/family-approval-request-unresolved-2026-v1.json)

Preflight: [release-preflight-report.json](outputs/2026-08-14-accounting-shadow-v2/release-preflight-report.json)
