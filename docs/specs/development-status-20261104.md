# COST 개발 현황·미결·명세 정본 안내 (2026-11-04)

**이 문서는 새로운 실행 큐가 아닌 현재 상태의 탐색 지도다.** 정본은 [시작 안내](../COST_V3_START_HERE.md), [시점별 최신 인계](../session_handoff.md), [실제 운영 증거](../operations.md), [AGENTS.md](../../AGENTS.md) 및 아래 분야별 명세다. PR 병합과 운영 적용, 합성 테스트와 고객 실자료 수락은 구분한다.

## 최신 구현과 운영 기록

| 영역 | 최신 확인 | 근거/주의 |
| --- | --- | --- |
| 다중 카드 파일 접수 후 백그라운드 분류·이동/복귀 | **구현·운영 배포 기록 완료**, [#627](https://github.com/6Soo/cost/pull/627), 운영 `804eac60`; [#629](https://github.com/6Soo/cost/pull/629) 문서 | 12개 합성 접수·이동/복귀, 영향 QA498, 보호13표 불변. **실제 고객 다중 업로드는 수행하지 않음.** [계약](card-upload-background-navigation-20261104.md) |
| 항공권 누락 탑승객·제주 여정·모바일 밀도 | **구현·배포 기록 완료**, [#626](https://github.com/6Soo/cost/pull/626), 운영 `96b978bf` | 보관 메일 읽기 검증, 390px 인증 화면 및 보호 검사. 모든 메일/실기기 검증 아님. [명세](flight-coverage-mobile-density-20261104.md) |
| FUKUTAKE·항공권 UI 우선순위 | **구현·배포 기록 완료**, [#624](https://github.com/6Soo/cost/pull/624), 운영 `f680e7e0` | 원본 재분류/Google 쓰기 없음. [계약](expense-flight-priority-fix-20261104.md) |
| 항공권 날짜·행선지·공항 검색 | **구현·운영 기록**, [#622](https://github.com/6Soo/cost/pull/622)·[#623](https://github.com/6Soo/cost/pull/623) | 최신 운영 확인은 인계/operations 우선 |
| 핵심 회계 중심 UI 간소화/가운데 레이아웃 | **병합**, [#620](https://github.com/6Soo/cost/pull/620)·[#618](https://github.com/6Soo/cost/pull/618)·운영 기록 [#621](https://github.com/6Soo/cost/pull/621) | 메뉴·내비게이션 회귀는 영향 브라우저 수락 필요 |
| 지출 인라인 편집·체크박스 없는 파란 다중 선택·원자 여행변경 | **병합·이전 운영 배포 기록**, [#549](https://github.com/6Soo/cost/pull/549)·[#555](https://github.com/6Soo/cost/pull/555). 밀도/애니메이션 [#571](https://github.com/6Soo/cost/pull/571)·[#609](https://github.com/6Soo/cost/pull/609) 병합 | [명세](inline-bulk-expense-edit-20261102.md)에는 운영 편집 흐름 전체 수락 미확인이 남아 있음. 최신 화면 수정과 실운영 편집 수락을 혼동하지 않는다 |
| 카드 조회 구간 증빙 및 미확인 기간 | [#479](https://github.com/6Soo/cost/pull/479) 명세, [#510](https://github.com/6Soo/cost/pull/510) 구현·운영 기록 | 실제 고객 파일/기간 확인은 미수행. [검증 기록](card-upload-coverage-implementation-20261102.md) |
| 능동 QA·영향 기반 검증 | [#513](https://github.com/6Soo/cost/pull/513), [#530~539](https://github.com/6Soo/cost/pull/539) 등 적용 기록 | 전체 실기기/모든 운영 데이터 시나리오가 완료된 뜻 아님. [계약](autonomous-qa-20261102.md) |

**SHA 주의:** 위 SHA는 각 작업의 *당시 배포 기록*이다. 이 문서 작성 시 운영 호스트의 현재 프로세스 SHA를 독립 조회하지 않았다. 가장 최근 기록된 PR #627 배포와 다른 기능의 개별 SHA가 동시에 나타날 수 있으므로 마지막 실제 상태는 단일 호스트의 task/process·health/ready·route 확인으로 확정한다.

## 현재 확인 가능한 미결/중복 작업

- [**열린 PR #607**](https://github.com/6Soo/cost/pull/607): 항공권 예약 화면 compact SPA 개선 **명세 PR**. 최신 #610·#622·#626 구현과 요구가 겹치는지 대조 후 유지·축소·종료를 판단한다. 명세가 열려 있다는 이유로 기존 개선을 중복 구현하지 않는다.
- [**열린 PR #567**](https://github.com/6Soo/cost/pull/567): 11/03 통합 지도 제안. 이 문서와 **목적이 중복**되므로 병합 전 내용 차이를 확인하고 하나만 정본으로 채택한다. #567은 아직 병합되지 않았으므로 그 신규 지도 파일은 main에 없다.
- 지출 인라인 편집의 **운영 읽기 UI 동선 수락과 실제 데이터 쓰기 수락은 별개**다. 합성 저장/모바일 QA로 운영 고객 거래 저장 완료라고 보고하지 않는다.
- 고객 파일 다중 업로드, 전체 실기기, 전체 운영 end-to-end는 PR별 검증 근거에 따라 미검증 범위를 유지한다. 최신 업무 요청이 없는 과거 작업 큐는 자동 재개하지 않는다.

## 문서 정리 규칙 / 정확한 정본

1. **시작점:** [COST 시작 안내](../COST_V3_START_HERE.md) → [현재 인계](../session_handoff.md) → (배포 시) [operations](../operations.md). 이번 지도는 짧은 현황/주제별 경로용이며 또 다른 상태 원장을 만들지 않는다.
2. **업무 계약:** [금융·카드·여행](finance.md) · [OTA](ota.md) · [Google 장부](google-ledger.md) · [참가자](participants.md) · [영수증](receipts.md) · [UI](ui.md).
3. **최근 세부 계약:** [지출 인라인 UX](inline-bulk-expense-edit-20261102.md) · [업로드 커버리지](card-upload-coverage-implementation-20261102.md) · [다중 업로드](card-upload-background-navigation-20261104.md) · [항공권 밀도](flight-coverage-mobile-density-20261104.md).
4. **검증 이력:** 개별 PR/운영 기록/기존 명세의 세부 실험·실패 재현은 보존한다. 오래된 `PARTIAL`, `BLOCKED`, 과거 배포 SHA를 삭제하거나 최신 상태로 오인하지 않고, 맨 위에 새로운 근거를 추가한다.
5. **중복 억제:** 같은 사실을 새 파일들에 다시 복사하지 않는다. 향후 구현 PR에서 관련 명세 상태를 갱신하고 가능하면 별도 문서 PR 남발 없이 한 번에 검증·인계한다. 문서 전용 병합으로 서버 재시작·재배포 금지.
6. **금융 보호:** 카드 원본·수동 교정·중복·환불·권한 보존. Google Sheets는 최종 장부이며 COST에서 자동 쓰지 않는다. 분류 완료·내부 기록·Google 반영·실제 환급을 각각 구분한다.
