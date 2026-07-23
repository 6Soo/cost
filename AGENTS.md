# AGENTS.md — 에이전트 진입점 (cost)

> **어느 에이전트로 열든(Antigravity·Cursor·Claude 등) 가장 먼저 이 파일을 읽으세요.**
> Claude Code는 `CLAUDE.md`를 자동 로드하지만 Antigravity 등은 자동 로드하지 않습니다 —
> 그래서 이 파일이 공통 진입점입니다.

## 0. 먼저 읽을 순서
1. **CLAUDE.md** (리포 루트) — 모델 정책. **STATUS.md** — 비용처리엔진 상세 핸드오프(가장 중요).
2. **LOG.md** 맨 아래 "세션 핸드오프" 블록 — 최신 세션이 한 일 / 배포·런타임 상태 / 미결 / 함정 / 부트스트랩.
3. `docs/비용분류_지시사항_원장.md`(표준 지시사항 원장 — 매 산출물 전 재확인), `docs/`.

## 1. 실행 환경 (필독 — git↔실행 자동연결 없음)
이 리포는 **Google Apps Script** 코드다. 코드는 여기(git)에 있지만 **실제 실행은 script.google.com에
사람이 붙여넣어야** 반영된다(자동 배포 아님). 실행 계정 = **kkokkohero6@gmail.com 단일**(메일함+시트 5개 소유).
→ 코드를 고쳐도 Apps Script 편집기에 붙여넣기 전엔 아무것도 안 바뀐다.

## 2. MCP 설정 — Antigravity 동등 구성
Claude 세션이 쓴 MCP: **GitHub**(공식 `github/github-mcp-server`), **Gmail·Drive·Calendar**(구글 공식
Google Workspace MCP 또는 `aaronsb/google-workspace-mcp`), **claude-code-remote**(Claude 전용, §4).
**Antigravity 설정 위치**: `~/.gemini/antigravity/mcp_config.json`, 또는 IDE 패널 `···` → **MCP Servers →
View raw config**. 형식: 로컬 `command`/`args`/`env`, 원격 `serverUrl`/`headers`.
```json
{ "mcpServers": {
  "github": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": { "GITHUB_TOKEN": "<토큰>" } },
  "google-workspace": { "command": "uvx", "args": ["google-workspace-mcp"], "env": { "GOOGLE_OAUTH_CLIENT_ID": "...", "GOOGLE_OAUTH_CLIENT_SECRET": "..." } }
} }
```
**OAuth 계정**: Gmail·Drive·Calendar = **kkokkohero6@gmail.com**. GitHub = **6Soo** 접근 계정.
**설정 안 하면**: 코드/문서 작업은 되나 메일/드라이브는 수동.

## 3. Gemini/GLM 브리지
`tools/gemini.mjs`(기본 `gemini-3.6-flash`) · `tools/llm-bridge.mjs --provider=glm`. Claude 세션에선 저비용
sonnet 래퍼가 호출·적용. 키는 `.env`(GEMINI_API_KEY·GLM_API_KEY, gitignore). 클라우드 세션은 명령 앞에
`NODE_USE_ENV_PROXY=1`. Antigravity/Cursor에선 그 에이전트 기본 모델이 직접 수행하면 됨.

## 4. 에이전트 차이 — Claude 전용 기능은 안 넘어감
- **서브에이전트 병렬 위임**(Opus+sonnet+gemini/glm/fable): Claude 전용.
- **claude-code-remote**(send_later·PR 구독·트리거): Claude 세션 바인딩. 대체 = OS 크론 / GitHub Actions.
- **Artifact·SendUserFile**: Claude UI 전용.
→ 코드/문서는 이어받되, 조율·자동화·전달 계층은 재구성 필요.
