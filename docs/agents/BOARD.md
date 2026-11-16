# 현재 작업판

정본은 [통합 명세](../SPEC.md), 판정은 [규칙집](../DECISION_POLICY.md), 실제 완료·운영 상태는 [현재 상태](../session_handoff.md)와 [운영 기록](../operations.md)을 따른다.

## 현재 승인 범위

| 항목 | 상태 | 실제 근거 / 다음 행동 |
| --- | --- | --- |
| RUST-OTA | VERIFIED (합성) | ExaOne 2.5 medium: 기존 e2a43e10/f5c91d95 확인, 새 red 없음·변경0. 감독 재실행 Rust 회귀7 통과. 실제 사본 재측정 미완 |
| RUST-REFUND | VERIFIED (합성, 최종검사 중) | ExaOne 초안 후 감독 완성056253df, Python a55de0c6. 실제 바이너리56/CLI4/core1·Python25 통과, 최종영향/독립검수 대기 |
| RUST-PREFLIGHT | VERIFIED (합성) | ExaOne 31feca83 → 통합 a360f055, 감독 보완 c391d415. 표적25 passed/skip0, 실제 CLI READY(환불1=1·OTA1=1); 원래 fixture WAL은 BLOCKED로 거부 |
| RUST-BRIDGE | VERIFIED (합성) | ExaOne60492d7d → 통합437125da. child 환경만 Python으로 고정. 작업자shadow CLI8/fmt/clippy 통과, 감독 환경회귀1통과/skip0 |
| RUST-INTEGRATION | RUNNING | 감독 별도 worktree, 실제 diff·표적 검사·영향 검사·최종 SHA 독립 검수 대기. 운영 전환 없음 |
| PLUSH UI-0~6 | COMPLETE (운영 배포) | eacc3bc7/8752 공식배포 exit0,1858파일 blob불일치0·보호14표불변·health/ready200. 독립 sol medium 정확SHA APPROVE. 운영4화면 오류/넘침0·자산3해시일치. 프런트72·최종영향45/skip0. 결과문서는 동일PR971 검수/통합. [검증 현황](artifacts/plush-ui-validation-20261116.md) |
| RCP-A: Paseo runtime | COMPLETE (Terra high 운영 기본값·실제 합성 판독 검증) | 1f436426 배포. 운영 catalog Codex/Terra/high/selectable=true. 합성 사진 실제 판독·스키마 검증·동일 handle 복구·archive 성공, tool event0. 일반 Codex/기존 Claude 이력 보존 |
| RCP-B: 영속 작업·장부 | COMPLETE (구현·검사·운영 배포) | 영속 결과·revision·원자적 반영·멱등·인증 API를11267cd0로 배포. 실제 고객 장부 apply는 미실행 |
| RCP-C: 웹 UI | COMPLETE (구현·합성 검수·운영 배포) | 1f436426에서 선택 모델/추론과 과거 작업 실제값을 동적으로 표시. 기존 사진/결과 교정·복귀·선택 반영·PDF 원본 UI 유지. TaskSpace44 사용자 제어 보존, 신규 동작은 JS 실행 합성 검증 |
| RCP-Q: 통합·검수 | COMPLETE (Terra 배포 게이트) | 표적51, 기준 영향524+26subtests, 최종delta83, 실패0/skip0; 최종1f436426 sol medium APPROVED. 실제 합성Terra high 성공·native 도구차단 확인 |
| 영수증 변경 요구와 질문 | COMPLETE | 사용자 요청·3개 답변 반영. 승인된 사진 지원 구독 모델·관리 프롬프트·선택 내역 일괄 반영 확정 |
| 영수증 흐름 설계 | COMPLETE (구현 승인) | [설계](../design/receipt-paseo-workflow-20261116.md): 동적 목록·사진 첨부·영속 작업·복귀 검수·실제 장부 반영·수락 기준. 사용자가 다수 Luna xhigh 병렬 구현을 승인했으며 실제 구현 상태는 RCP-A~Q를 따른다 |
| 판정 규칙·정본 연결 | COMPLETE (문서 작성) | SPEC §7.1, RCPT-020·022 개정/031 신설, CODE_GAPS에 현 코드 차이와 미구현 상태 기록 |
| 영수증 운영 배포 | COMPLETE | 최신 PR973, 공식 도구로1f436426/8751 배포. 보호14표 불변,1767파일 blob불일치0, health/ready200·비인증 영수증API401. 이전 배포/복구·백업 근거는 운영 기록 보존 |

## 이전 요청 완료

임시 작업공간·브랜치·전체 문서 정리는 [PR #969](https://github.com/6Soo/cost/pull/969)·main `9e2d66a3`에서 완료했다. worktree23→1, 로컬/원격 main만 유지, 복구 ZIP6개·2,142파일 복원 검증, Markdown216개·참조1,645건·끊김0. 정리용 PR 브랜치 삭제까지 완료했으며 그 기록을 새 작업으로 재실행하지 않는다. 상세 근거는 [통합 기록](../history/workspace-integration-20261116.md)에 있다. 위의 새 영수증 명세 브랜치는 현재 작업용이다.

## 별도 승인·차단 경계

| 항목 | 상태 | 재개 조건 |
| --- | --- | --- |
| Rust 1차 운영 전환 | 승인 ① 대기 | 백업/복원·사본 되돌림 예행 승인 후 절차서 순서. 이번 정리 요청을 전환 승인으로 해석하지 않음 |
| Rust 2차 연결 전환 | 보류 | 목록 밖 OTA 차이 해소와 별도 전환 검증 |
| 카드 수집 라이브 인증·다운로드 | 미검증 | 계정 자격·실사이트 접근 등 실제 수집 조건 확인. 합성 검사와 구분 |
| 오래된 실패 검사·중단 실험 | 미병합 보존 | [통합 기록](../history/workspace-integration-20261116.md)의 반려 근거·복구 참조 유지. 정리를 위해 실패를 통과로 바꾸거나 철회 코드를 재활성화하지 않음 |

이전 배정·모델 기록은 [정리 전 작업판](../history/BOARD-through-20261116.md)에 원문 보존한다. 기록 안의 진행/대기는 현재 실행 큐가 아니다.
