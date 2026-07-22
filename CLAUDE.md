# CLAUDE.md

## 모델 위임 규칙 (2026-07-22)

메인 세션 모델은 그대로 두고, 하위 작업을 Agent로 위임할 때는 작업 성격에 따라
모델을 고른다:

- 기획·카피·메일 문구·전략적 판단 → fable 위임
- 코드/스크립트 구현, 반복적 데이터 작업 → 위임 없이 메인 세션이 직접 처리
- 복잡한 아키텍처 결정이나 리스크 큰 작업(배포 전략, 보안 판단 등) 검토 → opus 위임

판단 기준이 애매하면 직접 처리하고, 명백히 위 범주에 해당할 때만 위임한다.

---

## 모델 우선순위 (사장 지시 2026-07-22, 전사 공통)

되도록 많은 작업(코딩 포함)을 **GLM 서브에이전트**에 맡기고, 결과에는 "GLM이 작성/분석함"을 명시한다.
저수준·반복 작업은 **Gemini Flash 3.6**을 활용하고 역시 "Gemini(3.6 Flash)"임을 명시한다.
Claude 토큰은 최대한 아끼되, **지휘·최종 검증은 1순위 Opus, 2순위 Fable**이 담당한다
(메인 세션 모델은 사람이 /model로 선택 — Claude가 스스로 전환하는 기능은 없음).

**기술적 한계**: GLM·Gemini는 Claude의 Agent 시스템에 못 앉는 순수 텍스트 API라 파일·git·bash
접근이 없다 — "GLM 서브에이전트"의 실체는 (a) 저비용 Claude(sonnet, 최소 추론) 래퍼 에이전트가
`tools/llm-bridge.mjs --provider=glm`(또는 `tools/gemini.mjs`)로 프롬프트를 보내고 (b) 받은
코드/텍스트를 그 래퍼가 파일에 적용·커밋하는 구조다. Claude 토큰 절약은 "내용 생성"을
GLM/Gemini로 옮기는 데서 나오는 것이지, 조율 자체를 없애는 게 아니다.

도구: `tools/gemini.mjs`(Gemini, 기본 모델 gemini-3.1-pro-preview — API 무료 등급 없어 결제
연결 필요, 무료로 쓰려면 --model=gemini-3-flash-preview 또는 gemini-3.6-flash) ·
`tools/llm-bridge.mjs --provider=glm|kimi|grok`(GLM은 무료 등급 확인됨 glm-4.7-flash, Kimi·Grok는
키는 있으나 잔액 충전 필요). 키는 리포 루트 .env에서 자동 로드(GEMINI_API_KEY·GLM_API_KEY 등).
클라우드 세션에서는 명령 앞에 `NODE_USE_ENV_PROXY=1` 필요. ▸ 래퍼 실행 모델은 항상 sonnet 최저 effort(예외: 맥락 거의 없는 1회성 짧은 호출은 메인 세션 직접 처리 무방).
상세 배경·실측 이력은 foresttour
리포 CLAUDE.md 참조.
