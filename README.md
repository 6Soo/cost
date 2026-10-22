# COST — 숲길여행 비용 자동화

**개발 또는 에이전트 작업은 반드시 [COST V3 단일 구현 진입점](docs/COST_V3_START_HERE.md)에서 시작합니다.** 이전 OTA-first 실험·문서의 `HOLD` 규칙과 10월 8~16일의 스냅샷 숫자는 최신 구현 지시가 아닙니다.

## 현재 운영과 목표를 구분합니다

- **현재 운영 코드:** 카드 업로드·정규화·환불/취소·여행 배정·OTA 대사·사용자 검토 및 SQLite 기반 저장 경로가 존재합니다. 최신 실제 운영 릴리스·검증 증거는 [운영 이력](docs/operations.md)과 해당 배포 SHA로 확인합니다.
- **V3 목표:** 카드 매입 원본이 유효하면 OTA 예약 연결이 추정/미연결이어도 여행 우선배정 및 COST 내부 비용 준비를 허용합니다. 사용자가 A→B로 옮긴 거래는 보존하고 AI는 사후에 질문·규칙 학습합니다. 원본 금액·실제 중복·환불·사용자 결정의 안전성은 유지합니다.
- **Google 목표:** 사용자에게 최종 회계 정본은 Google 시트이며 COST는 카드·영수증 지출 후보를 검토·정리하고 **사용자 직접 복사/붙여넣기**를 제공합니다. COST의 Google 자동 쓰기는 금지됩니다.
- **현재 구현 여부:** [PR #87](https://github.com/6Soo/cost/pull/87)의 V3 명세와 N:M Decimal 정규화 코드가 **2026-10-23 main 커밋 `f8ccd13`으로 병합됐습니다**. 다만 R0~R6 대사/비용 준비 개편과 사후 AI 대화는 **아직 구현·운영 배포되지 않았으며**, N:M 신규 표적 테스트 실행 결과도 확인되지 않았습니다.

[운영 장부](https://ledger.foresttour.kr/) · [카드 검토](https://ledger.foresttour.kr/import)

## 문서 인덱스 (현재 유효한 용도)

| 읽는 목적 | 문서 |
| --- | --- |
| **첫 진입, 모든 구현 우선순위·충돌 해결** | [COST V3 START HERE](docs/COST_V3_START_HERE.md) |
| OTA↔카드 미매칭 R0~R6, 금융 readiness | [OTA–카드 통합 정책 A](docs/ota-card-reconciliation-policy-a-v3.md) |
| 여행 자동 귀속·A→B 이동·AI 대화·항공권 탑승자 | [V3 AI 및 참가자 명세](docs/cost-v3-inference-ai-passenger-nm-test-architecture.md) |
| Google B:H 출력, 업무 정본·읽기 권한 | [Google 목표](docs/target-workflow-google-authority.md), [실측 열](docs/google-workbook-layout.md) |
| 보존되는 회계·여행 사용자 결정 | [규칙](docs/reconciliation-rules.md), [업무 보호](docs/business_rules.md), [카드 입력](docs/card_pipeline.md) |
| 현재 코드 구조 / 새 세션 | [구조](docs/architecture.md), [인계](docs/session_handoff.md), [에이전트 지침](AGENTS.md) |
| 과거 실행·검증 증거 | [운영 기록](docs/operations.md), [2026-10-08 OTA 검증](docs/ota-first-verification-report.md) |
| 은퇴시킨 구형 OTA/병렬 개발 문서 전문 | [레거시 문서 보관함](docs/archive/ota-legacy-20261023/) |

## 로컬 합성 개발 예시

**실제 운영 DB와 다른 경로**로만 실행합니다. 다음 옵션은 로컬 합성 세션을 전제로 한 기존 개발 진입 예시이며, 운영 서버 실행 명령이 아닙니다.

```powershell
$env:WEBLEDGER_CARD_FLOW='1'
$env:WEBLEDGER_UNIFIED_DB='1'
python run_candidate.py --data-root C:\AX\cost-dev-data --port 8765 --environment local-synthetic --synthetic-sessions
```

## 작업 절차

`DISCOVER → CONTRACT → IMPLEMENT → TARGETED TEST → REVIEW → COMMIT/PR → NEXT`. 새 대사 개발은 **R0 읽기 전용 원본·미매칭 전수 진단**부터. 운영 원문을 공개 무료 모델에 올리지 않으며, 문서만 바꾼 경우에는 코드 실행이나 재배포를 수행하지 않습니다.
