# COST 구조 — 현재/목표 분리

> **2026-10-23 정리.** [COST V3 단일 개발 진입점](COST_V3_START_HERE.md)을 먼저 읽으세요. **구조 설명은 목표 설계이며 main/운영 코드가 모두 전환된 상태가 아닙니다.** [기존 구조 전문](archive/ota-legacy-20261023/architecture.md)은 역사 자료입니다.

## 현재 구현 코드 진입

| 관심사 | 코드 |
| --- | --- |
| 카드 원본 수집·매입/승인·중복 | `app/import_card.py`, `app/reconciliation.py`, `app/normalize.py` |
| OTA 메일·포털 사실 | `app/ota_mail.py`, `app/ota_portal.py`, `app/ota_sources.py` |
| 현재 OTA 전역/그룹 매칭 | `app/ota_payments.py`, `app/ota_review.py` |
| 예전/병존 exact 경로 | `app/ota_exact.py`, `webapp/card_flow.py::_compute_ota_report` |
| 검토 스냅샷·수동 링크/그룹 | `webapp/ota_payment_review.py`, `webapp/ota_snapshot.py` |
| 카드 화면·내부 준비 | `webapp/card_flow.py`, `webapp/card_actions.py` |
| 장부 거래·수정 이력 | `webapp/ledger_store.py`, `webapp/ledger_board.py` |
| Google 읽기 정본·출력 | [Google 권위 계약](target-workflow-google-authority.md) 및 실제 webapp 코드 확인 |

## 목표 구조와 개발 우선순위

```text
카드 원본/OTA 메일·포털 원본
    → 출처 계보·파싱 결과/탈락 사유
    → 결제 관측(날짜 미상 유지)
    → 후보 검색(날짜 null 가능, alias 공유)
    → 단일 전역 대사/N:M/수동 links 보존
    → 금융 검증과 OTA 증거 별도 출력
    → 여행 우선 추론 + 사용자 override
    → COST 내부 지출 준비 / AI 사후 학습
    → 사용자 직접 Google B:H 복사 (Google API 쓰기 금지)
```

작업은 **[R0~R6 통합 구현 명세](ota-card-reconciliation-policy-a-v3.md)**부터. 전체 전면 rewrite 금지, 원본·거래 ID·실금액·환불·기록된 장부·사용자 결정을 보존합니다.

운영 중 실제 상태는 [operations.md](operations.md)와 해당 배포 SHA를 따릅니다. 과거 구조 문구의 “shadow 없이 처리” 등은 V3 목표 정책이 아닙니다.
