# AGENTS.md — 어느 에이전트로 열든 먼저 읽을 진입점

이 저장소는 여러 에이전트(Claude Code, Antigravity, Gemini CLI, Cursor 등)로 열릴 수 있다.
**Antigravity 등은 `CLAUDE.md`를 자동 로드하지 않으므로 이 파일이 공통 진입점이다.**

## 모델 라우팅·상호검증 규칙 (2026-07-29 사용자 지시, 최우선)

이 절은 `CLAUDE.md`를 포함한 과거 모델 위임 규칙과 충돌할 때 우선한다.

1. **기본 초안·설계 모델은 GPT-5.6 Luna max**로 둔다. 필요한 실질 작업에는
   **GPT-5.6 Sol medium의 별도 문맥 독립 반박·검증**을 붙이되, 검토는 기본적으로
   백그라운드에서 병렬 진행한다. 일반 작업의 실행·진행·중간 보고는 Sol 결과를 기다리지 않는다.
2. **저추론·쓰기·웹검색·구현**에서 AGY는 Paseo의 `agy` provider
   (`AGY (Antigravity CLI)`, local ACP bridge)를 통해서만 호출한다. 에이전트 위임은
   `mcp__paseo__create_agent`에 `provider: "agy"`를 지정하고, 후속 작업은 같은 agent에 보낸다.
    직접 Gemini API 경로(`tools/gemini.mjs`·`GEMINI_API_KEY`)는 사용하지 않는다 — 해당 스크립트는
    2026-08-24 삭제됐고 AGY(ACP) 호출이 유일한 Gemini 경로다.
   Paseo `agy` provider가 unavailable이면 `AGY_ACP_UNAVAILABLE`로 기록하고 GPT-5.6 Luna max로 즉시 폴백한다.
   ACP를 실제로 사용하지 않았다면 AGY를 사용했다고 보고하지 않는다.
3. **사용자 판단이 필요해 보이는 사안**도 Luna 초안을 먼저 진행하고 Sol medium 검토를
   병렬로 붙인다. Sol 결과가 늦어도 실행 가능한 작업은 계속한다. 외부 게시·전기·배포·결제·
   보안 변경처럼 되돌리기 어렵거나 고위험인 최종 확정만 독립 검토 PASS를 게이트로 삼는다.
4. 미완료 작업은 안전성·의존성·효과를 기준으로 우선순위화하고, 되묻지 않고 실행 가능한
   읽기·분석·로컬 구현·검증을 순서대로 자동 수행한다.
5. 위 자동 진행 규칙은 파괴적 작업, 운영 데이터 변경, 외부 메시지 전송, 배포, 결제 또는
   새 권한 부여를 묵시적으로 허가하지 않는다. 그런 작업은 정확한 대상과 복구 경로를 확인하고,
   저장소의 기존 승인 게이트와 실행 환경의 안전 규칙을 따른다.
6. 모델 호출·폴백·상호검증 결과는 최종 보고나 최신 `LOG.md` 세션 핸드오프에 사용 모델,
   수용·기각한 핵심 판단, 미완료 사유가 드러나도록 기록한다.

## 여행기간·행사기간 권위 규칙 (2026-08-24 전역 적용)

1. 서비스 사실과 여행 일정은 서로 다른 축이다. 카드 `occurred_on`은 결제일이지
   행사일이 아니며, 결제일·가맹점 지역명·월일 템플릿만으로 여행 대상을 만들지 않는다.
2. 최종 배정·대사·allocation·전기는 `trip_schedule`의 명시 권위 행만 읽는다. 권위 행에는
   `event_year`, 명시 시작일, 명시 종료일, `end_semantics`, `authority_kind`,
   `authority_status=authoritative`, 원천 `source_sha256`가 모두 있어야 한다. 원천 누락·
   digest 불일치·연도 불일치·복수 일정 충돌이면 해당 행은 보류한다.
3. `ends_on`은 사람이 사후 보정으로 입력하는 필드가 아니다. 정식 행사 원천이 포괄적
   마지막 행사일을 주면 그 날짜를 보존하고, OTA 숙박 원천이 `service_start_on`과
   체크아웃 제외형 `service_end_on`을 주면 시스템 공통 정규화기가 `service_end_on - 1일`을
   권위 일정의 포괄적 마지막 이용일로 만든다. 두 의미를 섞지 않는다.
4. 레거시 `mm/dd/window`는 원문 보존·후보 생성·누락/중복 감사 설명에만 사용한다.
   `window`를 행사기간, 여행 대상, allocation, 전기의 근거로 승격하지 않는다. 권위 일정에
   명시 날짜가 없으면 결과를 `검토필요`/`여행_미배정`으로 남기고 재무 부작용을 만들지 않는다.
5. 후보 분류기는 레거시 window를 설명용으로 참조할 수 있지만 결과는 `candidate_only`다.
   후보를 확정하는 경계에서는 반드시 `load_authoritative_trip_schedule`을 다시 읽어야 한다.
   이 규칙은 Agoda, OTA 예약, 숙박, 항공, 현지사용, 취소·환불 및 모든 미래 연도에 동일하다.
6. 사용자용 `기간` 표시는 별도 표현 규칙이다. 숙박·렌트는 실제 예약/이용기간이 없으면
   공란이며 행사 전체기간을 채우지 않는다. 보험은 보장기간 우선, 행사기간 fallback은
   화면 표시만 가능하고 분류·대사·전기 근거가 아니다.

## 병렬 실행·Sol 검토 격리 규칙 (2026-08-21 사용자 확정)

Sol 독립 검토는 품질 게이트이지 실행 워커가 아니다. 다음 규칙은 과거의 권한 폭주,
해시 재검토 루프, 브라우저 작업 중복, 잘못된 Paseo 알림이 다시 발생하지 않도록 한다.

1. 실행 워커와 Sol 검토자는 같은 로컬 workspace, 같은 dirty working tree, 같은 SQLite/DB,
   같은 브라우저 세션·탭을 공유하지 않는다. 검토에는 실행 시작 시점의 immutable snapshot 또는
   별도 `worktree`를 사용한다. 고정 snapshot을 만들 수 없으면 검토를 시작하지 말고
   `review_deferred`로 기록한다.
2. Sol 검토자는 read-only 역할이다. 파일 편집·생성, DB/JSON/output 쓰기, 브라우저·UIA 조작,
   외부 서비스 호출, 다른 agent/terminal/schedule 실행·종료를 하지 않는다. 테스트가 필요하면
   반드시 격리 snapshot에서 실행하며 실행 워커의 작업공간에는 `__pycache__`·임시파일도 만들지 않는다.
3. 검토자는 실행 워커의 critical path가 아니다. 실행 워커는 검토의 권한 요청·지연·실패를 기다리지
   않는다. 검토 결과에는 snapshot digest, 검토 범위, `PASS`/`FAIL` 또는 `BLOCKED` 하나와 근거를
   한 번만 남긴다. 같은 명령·같은 requestId의 재요청은 반복하지 않는다.
4. 읽기 전용 명령에 권한이 필요하면 허용된 명령을 한 번에 묶어 요청한다. 권한이 거부·만료되면
   한 번만 `review_blocked`로 끝내며, 권한 요청을 재귀적으로 만들거나 사용자에게 연쇄 알림을 보내지 않는다.
5. 동일 scope의 실행 agent가 이미 있으면 새 실행 agent나 새 검토 agent를 추가하지 않는다. 먼저
   `list_agents`와 pending permission을 확인하고 기존 agent의 상태를 재사용한다. idle/blocked 상태를
   새 prompt와 권한 요청으로 무한 재개하지 않는다.
6. 검토 agent 생성 시 `notifyOnFinish=false`를 사용하고 user-facing desktop notification을
   기본적으로 만들지 않는다. 필요한 완료 보고는 부모 agent의 단일 결과로 전달하고, 알림이
   불가피하면 task scope와 agent 역할을 제목에 명시한다.
   원문 assistant message나 과거 task의 본문을 현재 작업명·알림 본문으로 재사용하지 않는다.
7. 브라우저·외부 시스템이 `ERR_BLOCKED_BY_CLIENT`, session ownership, UIA target ambiguity 등으로
   막히면 동일 경로를 반복 실행하지 않고 정확한 failure code 하나로 중단한다. Sol 검토를 추가로
   띄워 브라우저를 재시도하게 하지 않는다.
8. Sol 검토는 항상 `background=true`로 시작하고 부모 실행을 block하지 않는다. 부모는 검토 완료를
   기다리거나 반복 polling하지 않으며, 실행 결과가 먼저 나오면 `review_pending` 상태로 보고할 수
   있다. 검토 결과는 다음 안전한 경계에서 한 번만 수용·기각한다.
9. Sol 검토가 권한·추가 입력·브라우저 접근을 요구하면 그 검토만 `review_blocked`로 남기고
   본 작업은 계속한다. 검토를 재개하기 위해 본 작업을 멈추거나 사용자에게 권한 승인 루프를
   전가하지 않는다.

10. Agoda 예약 목록·상세 수집은 이 작업공간에서 Paseo IAB 브라우저 도구만 사용한다. Edge,
    Windows UIA/CDP, 기존 `msedge` supervisor, 또는 다른 브라우저로 폴백하지 않는다. Paseo
    IAB가 unavailable/timeout이면 `PASEO_BROWSER_UNAVAILABLE` 또는 구체적인 failure code를
    기록하고, 같은 전용 세션에서만 bounded backoff 재시도(목록/페이지 로딩 최대 5회,
    상세 진입 전 최대 3회)를 허용한다. 새 에이전트·새 세션·중복 탭으로 우회하거나 무한
    재시도하지 않으며, 소진 시 `RETRY_EXHAUSTED`로 종료한다. 수집 중 예약 상세의 `예약 확인/변경하기` 경로만
    허용하며, `고객센터`, 도움말, 지원/문의 버튼과 그 텍스트를 클릭·호출하지 않는다.
     `booking-button` 순번, 전체 DOM 버튼 index, 위치 기반 range는 예약 상세 선택에 사용할 수
     없다. Agoda 상세 control은 `blp-booking-item-button-edit` 또는 동일 예약의 명시적인
     `예약 확인/변경하기`만 허용하고, 고객센터 패널이 보이면 즉시 fail-closed한다.
     Agoda 수집에서는 `browser_click`을 사용하지 않는다. 상세 진입은 예약 ID로 카드를
     먼저 증명한 뒤 그 카드 내부의 `data-element-name="blp-booking-item-button-edit"`
     하나만 `browser_evaluate`에서 선택·클릭한다. snapshot의 `@e23` 같은 일반 ref,
     카드/버튼의 순번·좌표·텍스트 부분일치는 금지한다.
     단, 예약 카드에 기본으로 렌더링되는 `blp-booking-item-agoda-customer-service`,
     `iris-chat-prompt-button`, `고객센터에 연락하기` 같은 지원 control의 존재만으로는
     패널 오픈으로 판정하지 않는다. `display/visibility/opacity`와 bounding box를 확인한
     실제 chat dialog/root 및 그 안의 입력 안내문(`요청 사항을 선택하거나 직접 입력해
     주세요`)이 동시에 보일 때만 `CUSTOMER_CENTER_PANEL_VISIBLE`이다. control 존재는
     `CUSTOMER_CENTER_CONTROL_PRESENT`로 기록하는 비차단 관찰값이다.
11. Agoda 인증 세션은 에이전트 전용으로 소유한다. 브라우저 상태가 workspace 단위로
    공유될 수 있으므로, 병렬 수집에서는 에이전트마다 별도의 Paseo workspace를 만들고
    그 workspace에 에이전트 하나만 붙인다. 하나의 Paseo IAB 인증 세션·브라우저 호스트·탭을
    두 에이전트가 공유하지 않으며, 한 에이전트가 다른 에이전트의 `browserId`를 사용하거나
    그 세션에 새 탭을 추가하지 않는다. 세션 소유권이 확인되지 않거나 다른 Agoda 탭이
    보이면 `SESSION_OWNERSHIP_UNKNOWN`으로 중단한다.
12. Agoda 비교 실행의 각 워커는 전용 세션 하나에서만 순차적으로 작업하고, 예약별로
    `booking_id`, 선택 control, 현재 URL, 고객센터 패널 상태, 시작·종료 시각, failure code를
    기록한다. 작업 완료 알림은 부모 에이전트의 단일 요약으로만 전달하며, 브라우저 워커와
    백그라운드 검토 워커는 `notifyOnFinish=false`를 사용한다. 재시도는 동일 세션에서만
     수행하고, 클릭 후 URL/상태가 불명확하면 재클릭하지 않고 `NAVIGATION_STATE_UNKNOWN`으로
     종료한다. `browser_new_tab`이 timeout이면 즉시 재호출하지 말고 먼저
     `browser_list_tabs`로 결과를 확인한다. 새 tab이 있으면 그 tab만 사용하고, 없다는
     확정이 없으면 `NAVIGATION_STATE_UNKNOWN`으로 종료한다. 추가 워커·중복 탭은 만들지 않는다.

## 시작 시 반드시 읽을 순서
1. **`LOG.md` 맨 아래 최신 "세션 핸드오프" 블록** — 지금 무엇이 끝났고 다음에 뭘 할지.
2. **`CLAUDE.md`** — 모델 위임·LLM 브리지 규칙(Claude 세션 한정 규칙 포함).
3. **`docs/비용분류_지시사항_원장.md`** — 비용분류의 전 규칙·원칙(P8~P15)·교훈 이력. 비용/장부 작업 전 필독.
4. (배경) **`STATUS.md`** — Apps Script 자동전기 엔진의 과거 상태.
5. Codex Cloud 세션이면 **`docs/CODEX_CLOUD_HANDOFF.md`** — 재현 명령, 현재 검증값,
   미병합 PR과 외부 연결 조건.

## 이 저장소가 하는 일
㈜숲길여행 법인카드 비용처리 자동화. 두 축:
- **비용분류 파이프라인**(`ledger/`, Python): 카드 4장 + 수기장부 → 분류·대사 → 2분기 매출확인자료 산출.
  실행 순서는 `LOG.md` §4.
- **Apps Script 엔진**(`apps-script/`, GAS): 카드 RAW → 장부 자동전기. scriptId·계정은 `LOG.md` §3.

## 에이전트 차이 (넘어가지 않는 것)
Claude Code 고유 기능은 **다른 에이전트로 이전되지 않는다**: 서브에이전트 위임(Agent/Task), Skill,
백그라운드 Workflow, PR 웹훅 구독. `CLAUDE.md`의 "GLM 서브에이전트/모델 위임"도 Claude 세션 안에서만
성립한다. 다른 에이전트에서도 AGY는 Paseo의 `agy` provider(local ACP bridge)를 우선 사용한다.
직접 Gemini API 호출(`tools/gemini.mjs`·`GEMINI_API_KEY`)은 금지 — 스크립트 자체도 2026-08-24 삭제됐고
Gemini의 유일 경로는 Paseo `agy` provider(local ACP bridge)다.
ACP 도구가 없으면 `AGY_ACP_UNAVAILABLE`을 남기고 Luna max로 폴백한다.

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

---

## 최신 세션 인계

작업을 이어받을 때는 `LOG.md`보다 먼저 가장 최근 날짜의
`docs/handoff/YYYY-MM-DD/README.md`를 읽는다. 현재 최신 인계 패키지는
`docs/handoff/2026-08-12/README.md`다.

인계 패키지의 상태가 `PARTIAL_HANDOFF`이면 검토 원문·최종 테스트 등 일부 보존이 끝난 것이
아니므로, `LOSSLESS_HANDOFF`로 승격하기 전까지 게시·전기·배포를 확정하지 않는다.
