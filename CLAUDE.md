# CLAUDE.md

## 모델·에이전트 라우팅 (2026-07-28 개정)

**전역 정책(`~/.claude/CLAUDE.md`)을 그대로 따른다.** 이 리포 고유의 예외는 없다.
요약: 고추론 설계·감사는 Codex `gpt-5.6-sol`(medium) ↔ Opus 5(medium)의 반박·수용·보완 루프,
저추론 구현은 agy `gemini-3.6-flash-high` → agy `claude-sonnet-4-6` → Codex `gpt-5.6-luna`(low)
순서로 쿼터 폴백. 실행은 `~/.local/bin/cycle.sh`.

*(2026-07-22 "GLM 서브에이전트 우선" 지시는 위 정책으로 대체됨 — 저추론 1순위는 GLM이 아니라
agy다. 폐지 배경과 실측 이력은 foresttour 리포 CLAUDE.md 참조.)*

**보조 도구(여전히 유효, 단 라우팅 1순위는 아님)**: `tools/gemini.mjs`(기본 모델
gemini-3.1-pro-preview — 무료 등급 없어 결제 연결 필요, 무료는 `--model=gemini-3.6-flash`) ·
`tools/llm-bridge.mjs --provider=glm|kimi|grok`(GLM 무료 등급 glm-4.7-flash 확인,
Kimi·Grok는 키는 유효하나 잔액 충전 필요). 키는 리포 루트 `.env`에서 자동 로드.
클라우드 세션에서는 명령 앞에 `NODE_USE_ENV_PROXY=1` 필요. 이 브리지들을 굳이 쓸 때
래퍼 실행 모델은 sonnet 최저 effort(예외: 맥락 거의 없는 1회성 짧은 호출은 직접 처리 무방).
