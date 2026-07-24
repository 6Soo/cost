# AGENTS.md — 어느 에이전트로 열든 먼저 읽을 진입점

이 저장소는 여러 에이전트(Claude Code, **Codex**, Antigravity, Gemini CLI, Cursor 등)로 열릴 수 있다.
**Antigravity·Codex 등은 `CLAUDE.md`를 자동 로드하지 않으므로 이 파일이 공통 진입점이다.**
2026-07-24 세션은 Claude Code에서 Codex로 이관됐다 — 프롬프트 없이 이 파일부터 읽고 이어갈 것.

## 시작 시 반드시 읽을 순서
1. **`LOG.md` 맨 아래 최신 "세션 핸드오프" 블록**(2026-07-24 ⑪번, 가장 최근) — 지금 무엇이 끝났고
   다음에 뭘 할지, 특히 §2(보안 인시던트)·§4(다음 세션 체크리스트)는 반드시 읽을 것.
2. **`CLAUDE.md`** — 모델 위임·LLM 브리지 규칙(Claude 세션 한정 규칙 포함 — Codex에선 해당 없음,
   대신 아래 "에이전트 차이" 참조).
3. **`docs/비용분류_지시사항_원장.md`** — 비용분류의 전 규칙·원칙(P2~P19)·교훈 이력. 비용/장부 작업
   전 필독 — 특히 P17(가맹명 완전일치만)·P18(타사카드 확인)·P19(고객정보 외부LLM 금지)는 2026-07-24
   보안 인시던트·오차단 사고 직후 추가된 규칙이라 꼭 확인.
4. (배경) **`STATUS.md`** — Apps Script 자동전기 엔진의 과거 상태.

## 이 저장소가 하는 일
㈜숲길여행 법인카드 비용처리 자동화. 두 축:
- **비용분류 파이프라인**(`ledger/`, Python): 카드 4장 + 수기장부 → 분류·대사 → 2분기 매출확인자료 산출.
  실행 순서는 `LOG.md` §4.
- **Apps Script 엔진**(`apps-script/`, GAS): 카드 RAW → 장부 자동전기. scriptId·계정은 `LOG.md` §3.

## 에이전트 차이 (넘어가지 않는 것)
Claude Code 고유 기능은 **다른 에이전트로 이전되지 않는다**: 서브에이전트 위임(Agent/Task), Skill,
백그라운드 Workflow, PR 웹훅 구독. `CLAUDE.md`의 "GLM 서브에이전트/모델 위임"도 Claude 세션 안에서만
성립한다. 다른 에이전트에서는 `tools/llm-bridge.mjs`·`tools/gemini.mjs`를 **직접 셸 호출**해 대체하라.

---

## Antigravity 동등 MCP 설정

이 세션(Claude Code)이 쓰는 MCP 커넥터를 Antigravity에서 재현하려면:

### 이 세션이 사용한 MCP 서버
- **Gmail** — 메일 검색/조회/라벨/초안(OTA 예약·결제 메일 대사).
- **Google Drive** — 원장 시트 다운로드/조회(fileId `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU`).
- **Google Calendar** — 일정(보조).
- **GitHub** — PR·이슈·커밋(이 저장소 `6Soo/cost`).

### Antigravity 설정 위치·형식
- 설정 파일: `~/.gemini/antigravity/mcp_config.json` — 또는 IDE 에이전트 패널 **"···" → MCP Servers →
  View raw config**.
- 형식(`mcpServers` 맵). 로컬 stdio 서버:
  ```json
  {
    "mcpServers": {
      "google-workspace": {
        "command": "npx",
        "args": ["-y", "@aaronsb/google-workspace-mcp"],
        "env": { "GOOGLE_OAUTH_CLIENT_ID": "...", "GOOGLE_OAUTH_CLIENT_SECRET": "..." }
      },
      "github": {
        "command": "npx",
        "args": ["-y", "@github/github-mcp-server"],
        "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "..." }
      }
    }
  }
  ```
  원격 HTTP 서버는 `{ "serverUrl": "https://...", "headers": { "Authorization": "Bearer ..." } }` 형식.

### 동등 서버 후보
- **Gmail·Drive·Calendar** → 구글 공식 **Google Workspace MCP**, 또는 `aaronsb/google-workspace-mcp`.
  OAuth는 반드시 **업무 계정 `kkokkohero6@gmail.com`**으로 인증해야 원장 시트·메일함에 접근된다(이 계정이 전부 소유).
- **GitHub** → 공식 **`github/github-mcp-server`**. PAT 또는 OAuth는 `6Soo/cost` 접근 권한 필요.

### 설정 안 하면
코드/파이프라인 작업(Python 재현·워크북 생성)은 **MCP 없이도 가능**(입력이 `ledger/data/`에 커밋돼 있음).
그러나 **메일 대사·드라이브 원장 최신화·초안 저장은 수동**이 된다. 참고로 이 세션이 만든 메일 초안 등
산출물은 계정별 위치(예: **Gmail 임시보관함**)에 있을 수 있으니 인수 시 확인하라.
