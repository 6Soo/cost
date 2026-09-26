# AGENTS.md — 어느 에이전트로 열든 먼저 읽을 진입점

> 최신 세션 인계: [2026-09-27](docs/handoff/2026-09-27/README.md).
> 아래 과거 인계 날짜보다 이 링크를 먼저 읽는다. 로컬 구현과 운영 전환은 별개다.

> Apply global agent rules from `C:\AX\AGENTS.md` first; keep only project-specific rules here.

이 저장소는 여러 에이전트(Claude Code, Antigravity, Gemini CLI, Cursor 등)로 열릴 수 있다.
**Antigravity 등은 `CLAUDE.md`를 자동 로드하지 않으므로 이 파일이 공통 진입점이다.**

## 공통 목표와 실행 기준

목표는 실제 비용 이벤트를 누락·증폭·중복 없이 보존하고, 검증된 관계와 명시 일정에서
같은 업무 결과를 재현하는 것이다. 에이전트가 달라지거나 재실행해도 비용·전표가 늘어나면 안 된다.

- [공통 실행 규약](docs/AGENT_EXECUTION_CONTRACT.md)과
  [결정 등록부](docs/DECISION_REGISTER.md)를 적용한다. 업무 규칙은 이곳과 비용 규칙 원장에서
  관리하며 `CLAUDE.md`에 다시 복제하지 않는다.
- `Q-SCHEDULE-001`은 2026-09-19 사용자 답변으로 확정됐다. 일정 겹침은 결정 등록부의
  일반 선택 규칙을 적용하고 끝까지 동률이면 보류한다. “계속해”를 새 선택지의 동의로 기록하지 않는다.
- 같은 입력·규칙·스키마·적용 결정은 같은 업무 의미를 만들어야 한다. 파일 전체 해시는
  파일 무결성, 의미 해시는 반복 계산 결과를 검증한다. 생성 시각을 같게 만들거나 합계만
  비교해서 멱등성을 주장하지 않는다.
- 같은 파일·DB·외부 효과의 작성자는 하나다. 독립 구현은 격리하고 코디네이터가 통합한다.
  기존 출력 거부는 안전한 재시도이며, 성공 NOOP나 외부 중복 방지가 구현됐다는 뜻은 아니다.
- 최신 양식은 `매출자료 양식_rev`다. 지출 C열은 항목이며 고객명 매핑 대상이 아니다.
  비용 규칙 원장의 옛 P28 양식 설명은 9월 2일 정정으로 대체되었다.

## 여행기간·행사기간 권위 규칙 (2026-08-24 전역 적용)

1. 서비스 사실과 여행 일정은 서로 다른 축이다. 카드 `occurred_on`은 결제일이지
   행사일이 아니며, 결제일·가맹점 지역명·월일 템플릿만으로 여행 대상을 만들지 않는다.
2. 최종 배정·대사·allocation·전기는 `trip_schedule`의 명시 권위 행만 읽는다. 권위 행에는
   `event_year`, 명시 시작일, 명시 종료일, `end_semantics`, `authority_kind`,
   `authority_status=authoritative`, 원천 `source_sha256`가 모두 있어야 한다. 원천 누락·
   digest 불일치·연도 불일치·복수 일정 충돌이면 해당 행은 보류한다.
3. `ends_on`은 사람이 사후 보정으로 입력하는 필드가 아니다. 정식 행사 원천이 포괄적
   마지막 행사일을 주면 그 날짜를 보존하고, OTA 숙박 원천이 `service_start_on`과
   체크아웃 제외형 `service_end_on`을 주면 시스템 공통 정규화기가
   **워크북 제목의 `MMDD_MMDD` 패턴이 마지막 이용일이라는 사용자 확인에 따라
   `ends_on = end_exclusive` 그대로 보존**한다. (`-1일` 자동 적용 안 함, 2026-08-29 사용자 확인)
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
1. **가장 최근 날짜의 `docs/handoff/YYYY-MM-DD/README.md`**와 `LOG.md` 맨 아래 최신
   "세션 핸드오프" 블록 — 완료 범위, 실제 검증값, 남은 작업을 확인한다.
2. **`docs/AGENT_EXECUTION_CONTRACT.md`와 `docs/DECISION_REGISTER.md`** — 공통 목표,
   멱등성의 수용 기준, 사용자 답변 대기를 확인한다. `CLAUDE.md`를 다시 읽는 순환은 만들지 않는다.
3. **`docs/비용분류_지시사항_원장.md`** — 비용/장부 작업 전 해당 규칙과 명시 정정을 읽는다.
   과거 기록의 "최신"·"사용자 확정"이라는 제목만 보고 후속 정정을 무시하지 않는다.
4. (배경) **`STATUS.md`** — Apps Script 자동전기 엔진의 과거 상태.
5. Codex Cloud 세션이면 **`docs/CODEX_CLOUD_HANDOFF.md`** — 재현 명령, 현재 검증값,
   미병합 PR과 외부 연결 조건.

## 도구 사용

도구 가용성은 실제 호출로 확인한다. 과거 세션의 인증·설치 기록을 현재 접근 보장으로 취급하지 않는다.
비용 처리 코드와 외부 연결 상태를 구분하고, 외부 오류가 독립적인 로컬 작업을 막지 않게 한다.

## 이 저장소가 하는 일
㈜숲길여행 법인카드 비용처리 자동화. 두 축:
- **비용분류 파이프라인**(`ledger/`, Python): 카드 4장 + 수기장부 → 분류·대사 → 2분기 매출확인자료 산출.
  실행 순서는 `LOG.md` §4.
- **Apps Script 엔진**(`apps-script/`, GAS): 카드 RAW → 장부 자동전기. scriptId·계정은 `LOG.md` §3.

## 최신 세션 인계

웹 장부 명세의 최신 재개 안내는 `LOG.md`의 2026-09-25 세션 핸드오프와
`docs/IMPLEMENTATION_PROMPT_WEB_LEDGER_APP.md`다. 명세 완료와 구현 완료를 구분한다.
구현 재개 지시를 받은 작업자는 `docs/WEB_LEDGER_IMPLEMENTATION_REVIEW.md` 7절의
수정 A부터 기존 결과를 보완하며 Phase 1을 처음부터 다시 만들지 않는다.

작업을 이어받을 때는 `LOG.md`보다 먼저 가장 최근 날짜의
`docs/handoff/YYYY-MM-DD/README.md`를 읽는다. 현재 최신 인계 패키지는
`docs/handoff/2026-09-08/README.md`다 (`PARTIAL_HANDOFF`, 전체 파이프라인 점검,
Reserve Max 통합 진단·shadow 금액/감사 검증·일정 종료일 보존 수정).

직전 인계 패키지: `docs/handoff/2026-09-01/README.md` (9월 2~3일 정정 포함).

인계 패키지의 상태가 `PARTIAL_HANDOFF`이면 검토 원문·최종 테스트 등 일부 보존이 끝난 것이
아니므로, `LOSSLESS_HANDOFF`로 승격하기 전까지 게시·전기·배포를 확정하지 않는다.

## 권위 일정 외부 소스 (2026-08-29 추가)

워크북 탭에 명시 일정이 없거나 1분기/4분기처럼 워크북에 직접 없는 권위 일정은
다음 외부 소스에서 가져온다. **이 경로는 Paseo IAB/Gmail/Drive MCP가 unavailable이어도
공개 링크 export로 우회 가능**하다 (예: 2026-08-29 세션에서 1분기 11개 여행 일정 수집에 사용).

### Q1 매출 확인자료 (2026년 1분기, 11개 여행)

- 파일 ID: `1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8`
- 공개 export URL (xlsx):
  `https://docs.google.com/spreadsheets/d/1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8/export?format=xlsx`
- 13개 시트: `0107_대만`, `0118_호남`, `0124_아키타`, `0203_다카야마`, `0214_조신에쓰`,
  `2월_미야코지마`, `2월_아마미`, `3월_오키나와`, `0307_이즈반도`, `0312_세토우치`,
  `0318_금오도`, `1분기_기타비용`, `1분기_행사경비총괄표`
- 일정 추출: 셀 `2026년 M월 매출 확인자료_<지역>_<MMDD>_<MMDD>`에서 `MMDD_MMDD` 패턴
  (워크북 제목의 MMDD는 마지막 이용일, `-1일` 적용 안 함 — 사용자 확인 2026-08-29)
- 수집 스크립트: `tools/download_q1.py`, `tools/extract_q1_titles.py`

### 우회 다운로드 패턴 (MCP 미인증 시)

1. 공개 URL `https://docs.google.com/spreadsheets/d/<FILE_ID>/export?format=xlsx`로
   `urllib.request.urlopen(headers={"User-Agent": "Mozilla/5.0"})` 사용
2. `C:\Users\kkokk\AppData\Local\Temp\opencode\q1.xlsx`로 저장
3. `openpyxl.load_workbook(path, read_only=True, data_only=True)`로 13개 시트 직접 파싱
4. 각 시트의 row 2 (제목)에서 `MMDD_MMDD` 패턴 추출

## 정식 OTA 파이프라인 (2026-08-29 추가)

`ledger/domain/direct_verified_ota_lodging.py` (72KB)는 정식 OTA 검증·투영 모듈이지만
`project_verified_lodging_decisions`는 `TRIP_MERCHANT_CONTRACTS`가 KBD/KBO/HAN/CORP의
**Trip.com 패턴만** 등록하므로 Booking.com/KLOOK/AIRBNB는 자동 매칭되지 않는다.
`prepare_external_lodging_facts`는 24개 active fact를 만들었으나 `project_...`가 0개
authority를 만들었기 때문에 `tools/build_links_from_verified.py`로 verified fact의
`target_code`를 직접 사용해 카드 매칭을 우회했다. 다음 세션이 TRIP_MERCHANT_CONTRACTS를
확장하거나 별도 `direct_ota_reservation_authority` 파이프라인을 작성해야 한다.

## 매칭 tie-break 규칙 (2026-08-29 추가)

`ledger/domain/direct_trip_schedule_authority.py`의 `match_service_period()`는 여러 여행이
매칭될 때 다음 우선순위를 적용한다. 이 규칙은 사용자 확인(레분토 시작일=레분토, 유럽 시작=
유럽)을 반영한 것이며 일반화 규칙이 아니다.

1. `record.starts_on == period.service_start_on` (체크인일이 여행 시작일과 일치)
2. `record.starts_on` 최신 (most recent trip)
3. `record.ends_on` 최신 (longest/outer trip)

## HI Design / 부산 패턴 (2026-08-29 수동 결정)

`AGODA.COM HI DESIGN` (`1715470826`, 04/29~05/01, 80,241원)은 알펜루트~부산 사이 갭.
사용자가 "국내 예약건, 부산 일정 사전 이동"으로 결정하여 `0501_부산`을 05/01 → **04/29**로
수동 확장했다. `source_locator`에 `#manual_extension=04-29_for_HI_Design_pre_trip` 메모.
**이 패턴은 일반화하지 않는다** — DB에 위치 정보가 없어 가맹점명 기반 자동 판정 불가.

