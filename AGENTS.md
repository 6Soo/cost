# AGENTS.md — 어느 에이전트로 열든 먼저 읽을 진입점

> Apply global agent rules from `C:\AX\AGENTS.md` first; keep only project-specific rules here.

이 저장소는 여러 에이전트(Claude Code, Antigravity, Gemini CLI, Cursor 등)로 열릴 수 있다.
**Antigravity 등은 `CLAUDE.md`를 자동 로드하지 않으므로 이 파일이 공통 진입점이다.**

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
4. 레거시 `mm/dd/window`는 현행 파이프라인에서 읽지 않는다. 과거 원문과 산출물은
   재현·감사용으로만 보존하며, 행사기간·여행 대상·allocation·전기의 입력으로 사용하지
   않는다. 권위 일정에 명시 날짜가 없으면 결과를 `검토필요`/`여행_미배정`으로 남긴다.
5. 현행 후보·확정 경계는 명시 권위 일정과 다음 권위 여행 시작일에서 계산한 전날 경계만
   사용한다. `load_authoritative_trip_schedule`을 다시 읽어 권위 여부를 확인한다.
   이 규칙은 Agoda, OTA 예약, 숙박, 항공, 현지사용, 취소·환불 및 모든 미래 연도에 동일하다.
6. 사용자용 `기간` 표시는 별도 표현 규칙이다. 숙박·렌트는 실제 예약/이용기간이 없으면
   공란이며 행사 전체기간을 채우지 않는다. 보험은 보장기간 우선, 행사기간 fallback은
   화면 표시만 가능하고 분류·대사·전기 근거가 아니다.

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
## 최신 세션 인계

작업을 이어받을 때는 `LOG.md`보다 먼저 가장 최근 날짜의
`docs/handoff/YYYY-MM-DD/README.md`를 읽는다. 현재 최신 인계 패키지는
`docs/handoff/2026-08-12/README.md`다.

인계 패키지의 상태가 `PARTIAL_HANDOFF`이면 검토 원문·최종 테스트 등 일부 보존이 끝난 것이
아니므로, `LOSSLESS_HANDOFF`로 승격하기 전까지 게시·전기·배포를 확정하지 않는다.

<!-- Migrated from CLAUDE.md; AGENTS.md is canonical -->

## Legacy CLAUDE.md content preserved

# CLAUDE.md

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

