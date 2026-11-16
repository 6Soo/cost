# 현재 작업판

정본은 [통합 명세](../SPEC.md), 판정은 [규칙집](../DECISION_POLICY.md), 실제 완료·운영 상태는 [현재 상태](../session_handoff.md)와 [운영 기록](../operations.md)을 따른다.

## 현재 승인 범위

| 항목 | 상태 | 실제 근거 / 다음 행동 |
| --- | --- | --- |
| PLUSH UI-0~6 | IN_PROGRESS | 최신 사용자 승인: 모든 작업 재개와 운영 배포. UI/API 통합, 프런트 10건·Python 30건 통과, 합성 390/1440px 두 테마 확인. B/D/C/E 계약 보완·영수증 선행 배포 SHA 통합·영향 검사·최종 SHA 독립 검수·배포 대기. [실행 계약](artifacts/plush-ui-implementation-contract-20261116.md), [검증 현황](artifacts/plush-ui-validation-20261116.md). 고객 원본 변경 제외 |
| RCP-A: Paseo runtime | PARTIAL (Terra 실제 판독 성공·새 기본값 배포 전) | 후속 사용자 지시로 기본 codex/gpt-6.1-terra high. 합성 사진의 실제 판독·스키마 검증·동일 handle 복구·archive 성공, tool event0. 운영은11267cd0이며 새 기본값 영향 검사·독립 검수·배포 진행 |
| RCP-B: 영속 작업·장부 | COMPLETE (구현·검사·운영 배포) | 영속 결과·revision·원자적 반영·멱등·인증 API를11267cd0로 배포. 실제 고객 장부 apply는 미실행 |
| RCP-C: 웹 UI | COMPLETE (구현·합성 검수·운영 배포) | 모델 선택·사진/결과 교정·복귀·선택 반영·PDF 원본 UI 통합. 기존 TaskSpace44 합성 근거 보존, 현재 사용자 제어라 재조작 없음 |
| RCP-Q: 통합·검수 | COMPLETE (배포 게이트) | broad1443+107subtests, receipt delta217, release guard delta32, 실패0/skip0; 정확 SHA별 sol medium APPROVE. 실모델 성공은 RCP-A 외부 차단 |
| 영수증 변경 요구와 질문 | COMPLETE | 사용자 요청·3개 답변 반영. 승인된 사진 지원 구독 모델·관리 프롬프트·선택 내역 일괄 반영 확정 |
| 영수증 흐름 설계 | COMPLETE (구현 승인) | [설계](../design/receipt-paseo-workflow-20261116.md): 동적 목록·사진 첨부·영속 작업·복귀 검수·실제 장부 반영·수락 기준. 사용자가 다수 Luna xhigh 병렬 구현을 승인했으며 실제 구현 상태는 RCP-A~Q를 따른다 |
| 판정 규칙·정본 연결 | COMPLETE (문서 작성) | SPEC §7.1, RCPT-020·022 개정/031 신설, CODE_GAPS에 현 코드 차이와 미구현 상태 기록 |
| 영수증 운영 배포 | COMPLETE | PR970·972, 공식 도구로11267cd0/8752 배포. 별도 신선 범위 백업·복원 PASS, 보호14표 불변,1764파일 blob불일치0, health/ready200·비인증 영수증API401. 첫 시도 실패와 공식 rollback은 운영 기록에 명시 |

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
