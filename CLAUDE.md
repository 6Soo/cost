# CLAUDE.md

## 모델 라우팅 규칙 (2026-08-04)

- 기본 초안·설계·운영 판단: GPT-5.6 Luna max
- 모든 실질 답변의 독립 반박·검증: GPT-5.6 Sol medium
- 저추론·단순 구현·일반 웹검색: AGY Gemini 3.6 Flash low
- AGY 실패 시 Codex Luna max로 폴백

실질적인 작업은 `Luna 초안`을 먼저 실행하고 `Sol 독립 반박`을 백그라운드로 병렬 진행한다.
일반 실행·중간 보고는 Sol을 기다리지 않는다. 외부 게시·전기·배포·결제·보안 변경 같은
고위험 최종 확정만 Sol PASS를 게이트로 삼는다. 단순 인사·상태 확인·모델 프로브는 반박을
생략할 수 있다. 비용·카드·고객정보가 포함된 작업은 PII 규칙과 증거 원칙을 먼저 적용하며,
원문 고객 데이터를 외부 모델에 전달하지 않는다.

## Sol 검토 격리·권한 규칙

Sol은 실행 워커와 같은 workspace·dirty tree·DB·브라우저를 공유하지 않는다. 실행 시점의
immutable snapshot 또는 별도 worktree가 없으면 검토를 보류한다. Sol 검토는 read-only이며
파일·DB·output·브라우저·UIA·외부 서비스·다른 agent를 변경하지 않는다.

검토는 실행 워커의 critical path가 아니다. `background=true`로 시작한다. 읽기 명령 권한은 한 번에 묶고, 거부·만료 시
`review_blocked` 한 건으로 끝낸다. 동일 명령·requestId를 반복 요청하지 않으며, 검토 agent는
`notifyOnFinish=false`로 만들고 user-facing 알림을 만들지 않는다. 브라우저 오류나 session ownership/UIA ambiguity는 같은
경로를 반복하지 않고 단일 failure code로 보존한다.

Agoda 예약 수집의 브라우저 공급자는 Paseo IAB로 고정한다. Edge, Windows UIA/CDP 및 `msedge`
supervisor로 폴백하지 않으며, Paseo IAB unavailable/timeout은 단일 failure code로 종료한다.
예약 상세 경로 외의 고객센터·도움말·지원/문의 버튼은 클릭하거나 호출하지 않는다.

저추론 위임은 `python ~/.orca/bin/route-b.py "<프롬프트>" --task "<작업 설명>"`을 사용하고,
전체 설계·구현·검증 사이클은 `bash ~/.orca/bin/cycle.sh <워크트리> "<과제>"`를 사용한다.
