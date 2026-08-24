# CLAUDE.md

## 모델 라우팅 규칙 (2026-08-04)

- 기본 초안·설계·운영 판단: GPT-5.6 Luna max
- 모든 실질 답변의 독립 반박·검증: GPT-5.6 Sol medium
- 저추론·단순 구현·일반 웹검색: Paseo의 `agy` provider(로컬 ACP bridge)로만 AGY 호출
- Paseo `agy` provider unavailable 시 `AGY_ACP_UNAVAILABLE`을 기록하고 Codex Luna max로 폴백
- Gemini 호출은 AGY(ACP) 경로만 유효 — 구 `tools/gemini.mjs`·API 키 직접 호출은 금지(스크립트는 2026-08-24 삭제됨)

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
supervisor로 폴백하지 않으며, Paseo IAB unavailable/timeout은 동일 전용 세션에서만
bounded backoff 재시도(목록/페이지 최대 5회, 상세 진입 전 최대 3회)를 적용한다.
새 세션·새 워커·중복 탭으로 우회하거나 무한 재시도하지 않고, 소진 시 `RETRY_EXHAUSTED`로
종료한다.
예약 상세 경로 외의 고객센터·도움말·지원/문의 버튼은 클릭하거나 호출하지 않는다.
     `booking-button` 순번이나 전체 DOM 버튼 index/range로 예약 상세를 선택하지 않으며,
     `blp-booking-item-button-edit` 또는 명시적인 `예약 확인/변경하기`만 허용한다. 고객센터
     패널이 보이면 즉시 fail-closed한다. 카드에 기본으로 존재하는
     `blp-booking-item-agoda-customer-service`, `iris-chat-prompt-button`,
     `고객센터에 연락하기` control은 패널 자체가 아니며 존재만으로 중단하지 않는다.
     실제로 보이는 chat dialog/root와 입력 안내문 `요청 사항을 선택하거나 직접 입력해
     주세요`가 함께 있을 때만 `CUSTOMER_CENTER_PANEL_VISIBLE`로 기록한다.
     Agoda 수집에서는 snapshot 일반 ref를 사용하는 `browser_click`을 금지한다. 예약 ID로
     카드와 동일 예약을 증명한 뒤 `browser_evaluate`에서 해당 카드 내부의
     `data-element-name="blp-booking-item-button-edit"`만 선택·클릭한다.

Agoda 인증 세션은 에이전트 전용으로 소유한다. 브라우저 상태가 workspace 단위로 공유될 수
있으므로 병렬 수집에서는 에이전트마다 별도 Paseo workspace를 만들고 workspace당 에이전트
하나만 붙인다. 하나의 Paseo IAB 인증 세션·브라우저 호스트·탭을 여러 에이전트가 공유하지
않으며, 다른 에이전트의 `browserId`를 재사용하거나 그 세션에 새 탭을 추가하지 않는다.
세션 소유권이 확인되지 않거나 다른 Agoda 탭이 보이면 `SESSION_OWNERSHIP_UNKNOWN`으로
     중단한다. 각 워커는 전용 세션 하나에서 예약을 순차 처리하고, 예약별 선택 control·현재 URL·
     패널 상태·시각·failure code를 기록한다. 클릭 후 URL/상태가 불명확하면 재클릭하지 않고
     `NAVIGATION_STATE_UNKNOWN`으로 종료한다. `browser_new_tab` timeout 후에는 먼저
     `browser_list_tabs`로 실제 생성 여부를 확인하며, 확인 전 중복 `browser_new_tab`을
     호출하지 않는다. 브라우저 워커와 백그라운드 검토 워커는
`notifyOnFinish=false`를 사용하고 부모가 단일 요약을 전달한다.

저추론 위임은 `mcp__paseo__create_agent`에 `provider: "agy"`를 지정해 Paseo local ACP bridge를 사용한다.
Paseo `agy` provider가 없으면 `AGY_ACP_UNAVAILABLE`을 기록하고 Luna max로 폴백한다. 구 브리지
스크립트(`tools/gemini.mjs` 등)는 2026-08-24 삭제됐으며 어떤 경로로도 부활시키지 않는다.
