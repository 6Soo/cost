# 남은 미결 전체 구현 · Luna low 병렬 실행

2026-10-30 사용자 “나머지 모든 미결사항 다수의 luna low에게 위임구현”, 후속 “ㄱ”을 실행 기준으로 삼는다. 이 문서가 이번 작업 인덱스이며 완료 기능은 재구현하지 않는다. 과거 상태표를 최신 코드·완료 커밋·실제 검사와 대조해 남은 부분만 구현한다.

| 작업 | 범위 | 단독 소유 영역 |
| --- | --- | --- |
| 호출 지도·도구 경계 | RF-001/109 | tools/refactor_call_map.py, runtime_dependency_catalog.py, cost_audit.py, 관련 config/검사 |
| 실패 기준선 | RF-004 | tools/classify_regression_failures.py, 기존 실패가 재현된 테스트 fixture와 관련 검사 |
| 백엔드 상태·대사 | RF-002/103/104/105 | 카드 여행 authority, review_context, OTA core·trace·읽기 projection의 남은 실제 경계 |
| 공통 디자인 | RF-201~205 | 공통 CSS·shell·검토 UI와 합성 시각/접근성 검사 |
| 외부 adapter·설정 | RF-107/301 | provider 계층·환경 계약·의존성 생성/검증 |
| DB·관측·성능 | RF-108/302 | 측정 도구·비식별 공통 계측·측정 근거가 있는 읽기 최적화 |
| 클라우드 메일 전환 | PEND-04 | 기존 cloud_mail와 preview/apply gate, 합성 검증; 실제 전환은 감독자만 |
| 보험·참가자 수입 | COST-INS-01/03/05·PIR | 기존 참가자 runtime/roster/income/panel·readonly 수락 경계 |
| 현재 미병합 수정 | PR #366/#367 | cards_all/card_transactions·분기 귀속·내부 코드 노출 교정의 실제 PR 통합 검수 |
| 외부 근거 미결 | PEND-01 및 실제 보험/금융 수락 | 감독자가 기존 근거·필수 사실·현재 접근 상태를 확인. 사실을 창작하지 않는다. |

작업자는 격리 worktree에서 소유 파일만 구현·표적 검사·커밋하고 실제 diff/커밋/검사·잔여를 반환한다. card_flow.py/ledger_board.py/run_candidate.py와 공통 문서·PR·push·main·배포는 감독자 소유다. 다른 worker 영역은 먼저 충돌을 보고하고 독립 부분을 계속한다. 재귀 위임은 하지 않는다.

운영 DB·고객 원문·인증·Google·실제 금융/여행/분류·명단/보험 쓰기는 작업자에게 배정하지 않는다. 실제 원문을 외부 모델/fixture/Git에 보내지 않는다. Google 최종 장부 자동 쓰기 금지와 국민/하나 카드 수집·업로드 보류를 유지한다. 배포와 외부 효과는 감독자가 단일 작성자·필요한 복구·원자성 게이트를 적용한다.

숲나들e PR #368의 기존 별도 승인은 중복 배정하지 않는다. 담당자 한도 중단 시 실제 진행 프로세스·작업 상태·보호·인계 파일을 먼저 확인한다. 이미 실행 중인 배포를 중복 실행하거나 성공으로 추정하지 않는다. 원본 관측 적재와 MailCollect 전환은 해당 기존 승인과 복구 게이트 안에서만 이어간다.

완료는 실제 구현·표적/보호 검사·감독자 검토·정상 병합·필요한 고정 배포로 판정한다. 실자료/물리기기·외부 근거·인증이 없으면 그 수락만 별도 대기와 재확인 조건으로 남긴다. 큐·작업자·실제 근거·다음 행동은 통합 worktree `.local-archive/all-pending-luna-20261030/queue.json`에 유지한다.
