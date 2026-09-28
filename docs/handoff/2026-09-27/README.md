# 2026-09-27 세션 인계

상태: PARTIAL_HANDOFF. 로컬 웹 장부 구현과 운영 서비스 완성을 구분한다.

## 새 채팅 재개 정보 — 2026-09-27 최신

새 채팅은 이 문서와 `docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`의 맨 위 최신
인계 블록을 먼저 읽는다. 현재 기준 커밋은 `1486a37`이며 작업트리는 아직
커밋되지 않았다. 다음 파일이 이번 구현 범위에 들어가 있다.

- 신규 모듈: `webapp/access_control.py`, `webapp/migration.py`, `webapp/ops.py`,
  `webapp/provider_transport.py`, `webapp/provider_config.py`,
  `webapp/rule_text.py`
- 신규 검사: `webapp/tests/test_access_control_phase7.py`,
  `webapp/tests/test_migration_phase8.py`, `webapp/tests/test_ops_phase9.py`,
  `webapp/tests/test_provider_boundary.py`
- 기존 수정: `webapp/ledger_board.py`, `webapp/ledger_design.py`,
  `webapp/ledger_store.py`, `webapp/dialog_turn.py`, `webapp/cli.py`,
  `webapp/tests/test_ledger_design.py`, `webapp/tests/test_dialog_turns.py`,
  `webapp/tests/test_classification_rules.py`
- 누적 기록: 이 문서와 `docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`

현재 확인한 좁은 검사는 다음과 같다.

- Phase 7: `40 passed`
- Phase 8: `18 passed`
- Phase 9: `64 passed, 2 subtests passed`
- Phase 6 제공자 경계: `97 passed, 57 subtests passed`
- 전체: `708 passed, 85 subtests passed in 360.29s`(최신 권위 실행)
- 구현 파일 `py_compile` 통과

위 목록의 좁은 수치와 "전체" 한 줄은 **같은 실행**의 값이며, 그다음
"전체 suite 재실행"을 **[역사 지시 — 현재는 완료]** 로 표시한 것은 그 지시가
이미 끝났다는 뜻이다. 현재 작업트리의 모든 변경을 합친 전체 검사를 반복해
실행했고, 마지막 값은 `708 passed, 85 subtests passed in 360.29s`다. 위의
`383 passed`와 중간의 `465 passed`, `610 passed`, `619 passed`는 통합 당시의
과거 실행 결과이며 최신 증거로 재사용하지 않는다. 실행 명령과 좁은 재실행
결과는 아래 "최신 전체 검증값" 절에 있고, 요구사항별 판정의 단일 출처는
`docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`의 `## 요구사항 매트릭스 감사` 절이다.

감사에서 발견해 고친 실제 결함은 아래 두 절에 항목별로 적어 두었다. 그 외에
오류 코드 4종(`AUTH_REQUIRED`/`ACTION_FORBIDDEN`/`RESOURCE_NOT_FOUND`/
`TEMPORARILY_UNAVAILABLE`), 키보드·오류 안내 계약 12.3, 그리고 Phase 6 제공자
경계(전송 계층·비밀 저장소·owner 전용 설정·실패 분류·fallback/대기/복구·
자연어→후보 규칙 변환)를 구현했다.


Paseo 구현자는 `36982862-21d6-4f6b-b51c-921d4c981881`이며 제목은
`SpaceBunny`, 모델은 `opencode/space-bunny-free`이다. 기존 세션을 재사용하고
새 구현자를 만들지 않는다. 5분 감시 항목은 `cost-web-ledger-implementer-watch`
이며 heartbeat ID는 `1de97732`이다. 새 채팅에서 감시가 보이지 않으면 먼저
해당 agent의 상태와 이 heartbeat를 확인한다.

구현과 검증은 합성 입력만 사용했다. 실제 Google OAuth, 예약 API, 운영 DB,
실제 Google 기준 자료, 고객 원본, 유료 자원, 실제 배포, commit, push는 하지
않았다. 외부 조건 여섯 가지는 `webapp/ops.py`의 `EXTERNAL_CONDITIONS`와
아래 Phase 9 기록을 기준으로 미완료 상태를 유지한다.

## 이어서 시작할 위치

현재 저장소의 `webapp/`은 기존 main 64862ac 이후 작업한 Phase 6 통합 후보다.
규칙 이력, 합성 AI 대화와 공급자 전환, 프로세스 소유권, A/Ramp/Pretendard 화면을 포함한다.
42개 후보 파일의 원천과 SHA-256은 `candidate-manifest.json`에 있다.
복사 직전에 모든 해시가 일치했고 기존 파일은 로컬 보관함에 백업했다.
이 manifest는 반영 당시 후보의 기록이며 이후 파일 변경에 자동 갱신되지 않는다.

```powershell
python -m pip install -r webapp/requirements.txt
python run_candidate.py --port 8765
```

`http://127.0.0.1:8765/board`에서 확인한다. 기본 DB는 `runtime/board.sqlite`이며
합성 데이터로 시작한다. 운영 DB 경로를 지정하지 않는다.
`/rules`는 단독 접근하면 사례가 없어 404다. 행에서 규칙 변경을 저장한 후 대화 링크로 들어간다.

## 검증

[역사] 이전 후보 보고: 383 passed, 21 subtests passed. 이번 본 저장소 실행 결과는
아래 최종 검증 절에 별도로 기록한다. 과거 결과를 현재 실행으로 재사용하지 않는다.

브라우저 검사는 pytest와 Playwright 및 Chromium이 필요하다.
`python -m pytest webapp/tests -q -p no:cacheprovider`로 실행한다.

## 390 실제 클릭 검증과 최소 수정 — 2026-09-27 추가

기준은 본 저장소 HEAD `1486a37`이고 실행 모델은 `opencode/space-bunny-free`
(입력·출력 비용 0)이다. 유료 모델로 대체하지 않았다. [역사] 전체 383 검사는 반복하지
않았다. 자세한 수치와 판정 근거는
[구현 기록](../../WEB_LEDGER_IMPLEMENTATION_LOG.md)의 같은 날짜 절에 있다.

### 반영한 최소 수정 2건

1. `webapp/ledger_design.py` — 390 편집 패널에서 저장/취소 footer가 화면 밖으로
   밀려 두 번째 저장이 불가능하던 결함. 저장 `<form>`이 flex column을 넘기지 않아
   `.p-bd`가 스크롤되지 않았다. 수정 전 버튼 top 853·bottom 897이 viewport 844
   밖에 있었고, 수정 후 top 788·bottom 832로 안에 남으며 `.p-bd`가 실제로
   스크롤된다. 회귀 검사는 실제 click 두 번 연속 저장과 `revision +2`를 확인한다.
2. `webapp/ledger_board.py` — `/import`의 은행 업로드가 4xx를 `완료`로 표시하던
   결함. 잘못된 열의 CSV는 이제 `실패:`와 사유를 보여 주고 결과 블록을 만들지
   않는다. 정상 CSV는 `원본 1행 · 새 입금 1건 · 제외 0건`으로 마무리된다.

### 390에서 새로 실제 클릭으로 확인한 경로

규칙 대화 미바인딩 대기, 규칙 대화 양쪽 공급자 실패(전환 1회, 채택 없음),
은행 가져오기 오류·정상, 보관 후 서랩 `보기`·`복원`(nav를 먼저 연 뒤). 이 경로들은
저장소 수준과 1440에만 검증이 있었고 390 실 클릭이 없었다.

### 여전히 미검증

아래 목록은 **외부 자원에 의존해 닫히지 않은 것**이다. 로컬 구현이
미완인 항목은 이 목록에 없다. 전체 요구사항 감사 결과는 이 문서가 아니라
[`docs/WEB_LEDGER_IMPLEMENTATION_LOG.md`](../../WEB_LEDGER_IMPLEMENTATION_LOG.md)
의 `## 요구사항 매트릭스 감사 — 2026-09-27 (최종)` 절(및 그 뒤의
`## 구현 검토 8~10절 항목별 판정`, `## 명세 전수 대조 감사` 절)에
proven / incomplete-local / external-only로 나누어 적었다. 이 README에는
매트릭스 표가 없고, 요구사항별 판정의 단일 출처는 그 로그 파일이다.

- 실물 휴대폰과 실제 Excel 인쇄. 390은 합성 Chromium 뷰포트다.
- 실제 AI 공급자 호출. `provider_transport.py`는 요청·응답 형식, 응답 파싱,
  실패 분류, 모델 목록 조회, 연결 테스트, 제한된 재시도를 모형화했고
  전송 계층만 주입형이라 실제 네트워크 호출은 하지 않는다. 실제 키·유료 승인
  없이는 호출 자체가 불가능하다.
- 실제 키. `provider_config.py`의 비밀 저장소는 로컬 파일이며
  `is_real_secret_store = False`다. 실제 키를 넣지 않았다.
- Google AI Studio의 실제 프로젝트 등급 확인. 앱에는 등급과 확인 시점을
  기록하는 상태 모델과 `setting-required` 상태만 있고, 실제 확인은 사람이
  외부에서 한다.
- 실제 Google OIDC 로그인과 실 예약 API 바인딩은 여전히 외부 조건이다.
  (합성 세션과 뷰어 권한 경계는 로컬에서 검증했다.)
- 운영 DB, 실제 고객 원천, 외부 AI 연결, 배포. 모두 이번 범위 밖이다.

## Phase 7 로그인·담당 배정과 Phase 8 이관 — 2026-09-27 추가

실제 Google OIDC, 예약 API, 운영 DB, 고객 원본, 배포는 연결하지 않았다.
합성 identity와 합성 원천으로만 검증했다. 실행 모델은 `opencode/space-bunny-free`
(입력·출력 비용 0)이다.

### Phase 7 — 역할과 담당 배정

`webapp/access_control.py`를 추가하고 `webapp/ledger_board.py`의 실제 경로에
연결했다. 계정 역할은 서버에서 판정하고, 소유자는 지정된 한 명이며 최초 로그인
계정을 승격하지 않는다. 직원 신청은 pending·approved·rejected·withdrawn,
계정 연결은 active·revoked로 나누고, 같은 `client_request_id`는 재사용되고
내용이 다르면 거부한다. 배정은 스냅샷 revision에 대해 단조 적용하므로 더 오래된
활성 배정이 최신 해제를 되살리지 못한다. 유효기간은 인자 없이 무기한이 될 수
없고 해제 지연 상한을 넘으면 거절한다. viewer는 배정 여행의 허용 필드와
분리된 증빙 미리보기만 읽고, 다른 여행·행·증빙은 404이며 내부 메모·변경 이력·
AI 대화·xlsx 생성·작업 조회·다운로드·원본 증빙은 막힌다. 합성 세션 어댑터는
명시적으로 바인딩하지 않으면 어떤 세션도 만들지 않는다.

[역사 수치 — 대체됨] 전용 검사 25개 통과.
현재 전용 검사 **40개** 통과(`--collect-only`로 확인). owner 경로 회귀는
`test_ledger_design.py`를 포함한 묶음으로 확인했다.

### Phase 8 — 로컬 합성 이관

`webapp/migration.py`를 추가했다. 기존 `snapshot_descriptor`와 `comparator`를
재사용해 두 합성 원천을 read-only snapshot으로 봉인·검증하고, 명시 source
identity로만 연결하며, 다섯 상태를 따로 집계하고, 필드별 명시 선택만 적용하며,
원천 금액·날짜 불일치를 provenance에 함께 보존하고, 결정을 좌우 입력 hash에
결속하며, 별도 migration DB에만 idempotent하게 적용한다. 보고는 unresolved 수,
이관 사건 수, 부호 합계, 누락 업무 필드, memo·evidence·provenance 보존 상태를
함께 낸다.

전용 검사 18개 통과.

### 여전히 미검증

- 실제 AI 공급자 호출과 실제 키 등록. 로컬 경계(전송 계층 주입, 비밀
  저장소, owner 전용 설정 화면, 실패 분류, fallback·대기·복구 계약,
  자연어→후보 규칙 변환)는 구현·검증됐고 실제 자격 증명만 없다.
- 실제 Google OIDC 인증과 실 예약 API 바인딩.
- 실제 Google 기준 워크북과 실제 예약 API를 읽은 이관.
- 실물 휴대폰과 실제 Excel 인쇄.
- 운영 DB 연결과 배포. 모두 이번 범위 밖이다.

## Phase 9 로컬 운영 준비 — 2026-09-27 추가

Oracle, Google OAuth, 예약 API, 운영 DB, 실제 고객 원본, 유료 자원, 실제
배포는 사용하지 않았다. 합성 경로에서만 검증했다. 실행 모델은
`opencode/space-bunny-free`(입력·출력 비용 0)이다.

### 구현과 검증 결과

`webapp/ops.py`를 추가했다. durable config는 개발 기본값·상대 경로·운영용 임시
데이터 루트를 fail-closed로 거절하고 비밀은 존재 여부만 남긴다. 백업은 DB와
불변 원천·증빙·출력 메타의 해시 묶음이고, 복원은 별도 경로에서 사건·배분·정정·
요청 멱등성·권한 상태를 다시 확인한다. 재시작 생존은 합성 DB로 실제로 실행해
확인했다. health/readiness는 DB 경로·무결성·스키마·여유 공간·필수 비밀을 각각
독립 항목으로 보고 실패를 숨기지 않는다. 배포는 매니페스트와 dry run, runbook까지만
만들고 적용하지 않는다. 백업은 최근 7개와 동일 해시 중복을 제거한다.

[역사 수치 — 대체됨] 전용 검사 25개 통과. Phase 7·Phase 8 43개와 390·장부
묶음 71개로 회귀를 확인했고 [역사] 전체 383 suite는 반복하지 않았다.
현재 전용 검사 **64개** 통과(`--collect-only`로 확인).

### 전체 요구사항 감사를 위한 상태

- Phase 7 `webapp/access_control.py` + `webapp/ledger_board.py` 연결, **40개 통과**.
- Phase 8 `webapp/migration.py`, **18개 통과**.
- Phase 9 `webapp/ops.py`, **64개 통과**.
- Phase 6 `webapp/provider_transport.py`·`provider_config.py`·`rule_text.py`,
  **97개 통과**.
- 합성 기준 narrow pytest 누적(현재): 40 + 18 + 64 + 97 = **219개 통과**.
  수치는 `python -m pytest webapp/tests/test_access_control_phase7.py
  test_migration_phase8.py test_ops_phase9.py test_provider_boundary.py
  --collect-only -q`로 언제든 다시 확인할 수 있다.
- [역사 수치 — 대체됨] 이전 기록은 Phase 7 25개, Phase 9 25개, 누적
  25 + 18 + 25 = 68개였다. Phase 9 구현 이전 값이므로 쓰지 않는다.
- [역사 — 대체됨] "전체 suite 재실행이 필요하면 383 기준으로 한 번 돌리면 된다.
  이 인계 이후 코드 변경은 새 모듈 3개와 그 검사 3개, `ledger_board.py`,
  `ledger_design.py`(390 패널 수정), `test_ledger_design.py`에 국한된다"는
 당시 기록이다. 이후 변경 범위는 훨씬 넓었다. 현재 수정 파일은
  `webapp/cli.py`, `dialog_turn.py`, `ledger_board.py`, `ledger_design.py`,
  `ledger_store.py`, `sheets_export.py`과 검사 8개, 신규 모듈 6개
  (`access_control`, `migration`, `ops`, `provider_transport`,
  `provider_config`, `rule_text`)와 신규 검사 4개다. `git status`로 확인한다.

### 코드 성공과 분리해 남기는 외부 조건

로컬 준비가 통과해도 아래는 미완이며 사용자 결정이 필요하다. 상세는
`ops.EXTERNAL_CONDITIONS`와
[구현 기록](../../WEB_LEDGER_IMPLEMENTATION_LOG.md)의 같은 날짜 절에 있다.

- 호스팅 자원: 미 provisioned. 승인·계정 필요.
- Google OAuth 클라이언트와 콜백: 없음. 지금은 합성 세션 어댑터만 있다.
- 예약 API 담당 배정: 미 연결. 지금은 합성 배정 스냅샷만 있다.
- 운영 DB와 실제 Google 기준본 이관: 미 이관.
- 유료 전환: 승인 없음.
- 실제 배포: 하지 않음.

## 전체 요구사항 감사 완료 — 2026-09-27 최신

기준 커밋 `1486a37`, 작업트리 미커밋. 실행 모델 `opencode/space-bunny-free`
(입력·출력 비용 0). 외부 Google OAuth·예약 API·운영 DB·실제 고객 자료·유료
자원·실제 배포와 commit·push는 사용하지 않았다.

### 최신 전체 검증값

- **전체 1회: `624 passed, 85 subtests passed in 190.57s`, 종료 코드 0**
  (인계 정합성·매트릭스 증거 보강·구현 검토 8~10절 판정까지 반영한 현재 값.
  R09 수식 차단 결함 3건을 고치고 검사를 추가한 뒤 실행했다.)
- 그 이전 실행값(역사): `610 passed, 80 subtests passed in 187.96s`,
  `465 passed, 21 subtests passed in 194.71s`
- 감사 착수 전 값: `452 passed, 21 subtests passed in 156.37s`
- 좁은 묶음(이번 실행과 함께 돌린 것):
  - 수입·분류 규칙·은행 원천·저장소·카드:
    `177 passed, 3 subtests passed in 24.12s`
  - Phase 9·Phase 8·제공자 경계·Phase 7:
    `219 passed, 59 subtests passed in 33.86s`
  - 명세 전수 대조에서 추가한 검사 5건은 위 두 묶음에 포함돼 있다.
- `py_compile` 48개 파일 통과, DBG/TODO/breakpoint 잔여 0건, 잔여 프로세스 0
- 매트릭스가 인용한 검사 이름 101개를 실제 파일과 대조했고 없는 이름은 0개다.

### 감사에서 고친 실제 결함 3건

1. `Session.session_generation`과 `cache_namespace`이 정의만 있고 쓰이지 않아
   SPEC 15.3의 세대 결속이 적용되지 않았다. 계정에 세대 열을 추가하고 연결
   해제·계정 비활성화 시 세대를 올려 이전 세대를 `SESSION_STALE` 401로
   거절한다.
2. 철회된 신청을 승인할 때 사람 충돌 코드가 났다. 신청 상태를 먼저 보고
   거절해 SPEC 16.5의 "거절·철회·해제·비활성화를 같은 오류로 뭉치지 않는다"를
   지켰다.
3. Phase 9 runbook의 명령이 실제로 존재하지 않았다. `webapp/cli.py`에
   `ops health|backup|restore|dry-run|readiness`를 연결했다. 실행해 보니
   `keep_backups` 인자 결함으로 4개 명령이 죽었고 고쳤다. fail-closed 거절은
   JSON과 종료 코드 2로 보고된다.

`/access/logout`도 추가해 세션 종료와 클라이언트가 비워야 할 목록을 알려준다.

### 정상으로 확인되어 수정하지 않은 것

보관 여행의 담당 권한 유지, 행 이동 시 즉시 권한 적용, owner의 export 연속성,
잘못된·비어 있는 세션 헤더의 401 처리, owner 로그아웃 후 viewer의 export 차단.

### 남은 외부 조건 (로컬로 닫을 수 없음)

호스팅 자원, Google OAuth 클라이언트·콜백, 예약 API, 운영 DB와 실제 Google
기준본 이관, 유료 전환 승인, 실제 배포 — 여섯 항목 모두 `ops.EXTERNAL_CONDITIONS`
기준 미완이다. 전체 요구사항 감사는 이 상태에서 더 진행할 로컬 항목이
남지 않았음을 확인한 결과다.

## 우선순위 1b — proven 매트릭스 행 단위 재검증 (2026-09-27 최신)

`docs/WEB_LEDGER_IMPLEMENTATION_LOG.md` 의 `## 요구사항 매트릭스 감사` 절이
단일 출처다. 이번엔 그 proven 33행을 하나씩 훑으면서, 각 행마다 **그 요구의
실제 제품 경로가 무엇인지**를 먼저 적고 그 표면 위에서 단정하는 테스트가
있는지 다시 확인했다.

### 무엇이 잘못되어 있었나

이전 표는 `명세 요구 | 구현 | 검사` 세 칸뿐이어서 **어느 층에서 단정하는지**
적혀 있지 않았다. 그래서 명세가 화면과 저장 요청을 요구하는 행이, 저장소
함수만 부르는 테스트만 인용된 것처럼 보였다.

실제로는 다른 파일에 그 요구의 표면 검사가 있었고 **인용만 누락**돼 있었다.
전수 스위트의 하네스를 분류해 보니(Playwright Chromium 62건, 실제 HTTP 91건,
저장 계층 331건, CLI 36건, 순수 함수 70건) 화면·HTTP 검사가 이미 존재했다.

### 바로잡은 행

| 요구 | 실제 제품 경로 | 정정 후 검증 표면 |
| --- | --- | --- |
| REFINEMENT 8.1 여행 탭 삭제 | `GET /trips` | 화면(브라우저) |
| REFINEMENT 8.1~8.2 삭제 저장 경계 | `trip_delete` + `DELETE_PREVIEW_STALE` | 저장 계층 + 화면 |
| REFINEMENT 9 되돌리기 (배분) | `POST /api/rows/{id}` + `GET /row` | HTTP |
| REFINEMENT 10 입금 분할 | `GET /income/new` | 화면(브라우저) |
| REFINEMENT 12~14 작성일·담당자 | `POST /api/trips/{tab_id}` + `GET /trips` | 화면 + 저장 계층 |
| DETAILED 6.2~6.3 규칙 적용 | `POST /api/classification/rules/*` | HTTP + 저장 계층 |
| APP_SPEC 9.3 fallback 스위치 | `POST /access/providers` | HTTP + 저장 계층 |
| APP_SPEC 7 권한·공개 범위 | `/access/*` | HTTP |
| DETAILED 12.3 키보드 안내 | `GET /board` HTML | 화면(브라우저) |
| 390 뷰포트 | `GET /board` 390px | 화면(브라우저) |

행도 층에 맞춰 쪼갰다. 삭제를 화면과 저장 경계로, 되돌리기를 배분과 일반
편집으로, 10절을 분할 화면과 배분 정합성으로, 12~14를 작성 정보와 출력
수식 방어로 나눴다. proven 표는 33행에서 **36행**이 됐다.

인용한 테스트 이름은 전부 실제 존재를 확인하고 넣었다(없으면 넣지 않음).

### 층을 올려 부풀리지 않은 행

`DETAILED 7` AI 대화와 `IMPL 7.1.1` 전송 계층 10행은 이 웹앱에 해당 화면이
없다. 명세가 요구하는 것이 대화 저장 경계와 전송 계층 동작이므로
`저장 계층`·`단위` 표기가 요구사항과 일치한다. `REFINEMENT 8.9~8.10` 이관은
별도 이관 DB가 제품 경로라 파일 계층이고, `REFINEMENT 17.2~17.4` 백업·복구·
조치 필요는 명세가 운영 경로를 운영 CLI로 두므로 `CLI` 가 맞다.

### 1b에서 새로 확인한 미완료 3건 (전부 닫힘)

**[역사]** 이 세 건은 그 시점에 로그의 `incomplete-local` 절에 등록했고
우선순위 2와 3의 시작 목록이었다. **셋 다 닫혔다** — 아래 "우선순위 2"와
"우선순위 3" 절과 로그의 proven 표를 보라. 현재 incomplete-local 은 0건이다.
아래 세 항목은 당시의 발견 내용 그대로다.

1. **APP_SPEC 3절 `새 탭 추가` 경로가 아예 없다.** 생성 라우트·저장 함수·
   화면·검사가 모두 없다. `GET /trips` 는 기존 탭 나열과 삭제 미리보기뿐이다.
2. **`POST /api/expenses/manual` 에 검사가 0건이다.** 라우트는
   `webapp/ledger_board.py:2623` 에 있고 `/expense/new` 화면이 이 경위로
   POST 하지만 테스트 스위트 어디에서도 호출하지 않는다.
3. **REFINEMENT 9 일반 편집 되돌리기 화면이 미검증이다.** 배분은 HTTP로
   검증되지만 메모 등 일반 편집은 저장 계층만 proven이다.

### 1b 실행값

- 읽기 전용 감사였다. 제품 코드(`webapp/**.py`) 변경 **0건**.
- 매트릭스 인용 대조: 인용한 검사 이름 전부 존재 확인, 없는 이름 0개.
- 표면 분포(36행): HTTP 12행, 화면(브라우저) 6행, 저장 계층 19행, 단위 2행,
  CLI 2행.


## 우선순위 2~4 — 2026-09-27 최신

**판정은 여기서 새로 만들지 않는다.**
`docs/WEB_LEDGER_IMPLEMENTATION_LOG.md` 의 `## 요구사항 매트릭스 감사` 절이
단일 출처이고 proven / incomplete-local / external-only 를 한 곳에만 적는다.
아래는 그 절에 무엇이 생겼는지에 대한 요약과 링크다.

### 우선순위 2 — 소유자 전용 여행 탭 생성

`incomplete-local` 1번을 닫았다. 3절과 4.2절을 그대로 구현했다.

- 생성 라우트 `POST /api/tabs` 와 저장 함수 `LedgerStore.create_trip`,
  화면(왼쪽 레일의 `+ 탭 추가`와 `/trips` 의 대화창), 그리고 검사를 추가했다.
- `날짜`·`행선지` 필수, 내부 `tab_id` 는 서버가 만든다.
  같은 날짜·행선지가 있으면 새 행을 만들지 않고 그 여행을 돌려주며
  병합 여부는 결정하지 않는다(`merge_decided: false`).
- 3절의 5필드(`event_year`·`tab_kind`·`authority_status`·`source_sha256`·
  `sort_order`)를 `trip_tabs` 에 열로 더했다. `archived`/`deleted` 로부터
  파생하는 `tab_lifecycle` 은 따로 저장하지 않았다.
- 4.2절대로 권위 근거가 없는 탭은 `authoritative` 가 아니라 `needs_review` 다.
  탭을 만들었다는 사실만으로 권위가 생기지 않는다.
- 소유자 경계는 새 우회로가 아니다. `POST /api/tabs` 는 세션 없는 호출에
  401, viewer에 403을 주며, 본문을 읽기 전에 결정된다. 이 경로 전용 게이트를
  새로 만들지 않았다.

### 우선순위 3 — 검증 공백 3건

`incomplete-local` 2·3번을 닫고, 3-3을 명세와 대조해 다시 판정했다.

- `POST /api/expenses/manual` 에 HTTP 검사를 붙였다(저장·멱등·검증 실패·
  권한 거부·화면 폼 경로).
- REFINEMENT 9 일반 편집 되돌리기를 `POST /api/rows/{id}/revert` 로 증명했다.
  배분 되돌리기는 이미 HTTP proven이었다.
- 명세가 실제로 요구한다고 확인되어 새로 만든 것:
  `GET /api/rows/{row_id}/lineage`, `GET /api/audit/changes`,
  `GET /api/tabs`, `GET /api/tabs/{tab_id}/rows` (모두 APP_SPEC 10절),
  출력 대화창의 `검토필요` 건 수(APP_SPEC 8절).
- 요약 라벨 `has_key`/`has_model`/`configured` 분리는 이미 구현되어 있었고
  화면 인용을 확인했다. 새로 추가하지 않았다.
- **[역사] 닫히지 않았던 것 1건이었고, 지금은 닫혔다**: APP_SPEC 8절이 요구하는
  `충돌` 행 수. 그 시점에는 저장 충돌이 `EDIT_CONFLICT` 로만 답하고 장부에
  남지 않아 "미해결 충돌을 가진 행"이라는 상태가 없다고 판단했다. 재심해서
  APP_SPEC 9절·6절과 DETAILED 3.2를 다시 읽고, `board_revisions`에
  `kind='conflict'` 한 줄만 덧붙이는 가장 좁은 구현으로 닫았다. 현재
  incomplete-local 은 0건이다.

### 우선순위 4 — 절 번호 정합성

매트릭스 각 행이 가리키는 절 번호를 원문 명세와 전수 대조했다.
**53개 절 참조 중 어긋난 것 0개.** 다만 실제로 문제가 1건 있었다.

- `REFINEMENT 8.9~8.10 이관` — 그 절은 어떤 명세에도 존재하지 않았다.
  로그에만 있던 인용이었다. 실제 근거는 `DETAILED 11.2 최초 이관 차이 선택`
  이므로 그쪽으로 고쳤다.

### 이번 턴 실행값

- **[역사 실행값]** `python -m pytest webapp/tests -q -p no:cacheprovider`
  → `682 passed, 85 subtests passed in 279.52s`
  (그 시점에 `624 passed` 에서 신규 58건 증가. 회귀 없음.
   최신 권위값은 아래 "이번 최종 검증" 절의 값이다.)
- 신규 검사 파일: `webapp/tests/test_trip_create.py` (28건),
  `webapp/tests/test_spec_named_paths.py` (30건)
- 매트릭스 인용 검사 이름 115개 전부 실제 존재 확인, 없는 이름 **0개**
- 매트릭스 proven 행 45행(인용 있는 행), 절 참조 53개
- 변이 검사: 우선순위 2에서 6건, 우선순위 3에서 4건, 총 10건 전부 실패로
  탐지됐고 소스 복구를 확인했다.
- 문서 U+FFFD **0건**

### 여전히 external-only

`ops.EXTERNAL_CONDITIONS` 여섯 항목이 그대로다. 실제 Google OIDC, 실제
예약 API, 실제 AI 호출·키·등급 확인, 운영 DB, 호스팅 자원, 실제 배포와 실물
Excel 인쇄. 이번 턴은 이 항목에 손대지 않았고, 외부 조건을 로컬 구현으로
적지 않았다.

## 재심 판정 — 마지막 1건과 경로 문제 (2026-09-27 최신)

**판정은 여기서 새로 만들지 않는다.** 단일 출처는
`docs/WEB_LEDGER_IMPLEMENTATION_LOG.md` 의 `## 요구사항 매트릭스 감사` 절이고
**incomplete-local 은 이제 0건**이다. 아래는 요약과 링크다.

### APP_SPEC 8절 `충돌` 행 수 — 닫음

이전 턴은 "장부에 충돌 상태가 없다"를 이유로 세지 않았다. 재심해서 명세를
다시 읽으니 그 상태를 두어야 한다고 되어 있었다. 근거는 세 곳이다.

- APP_SPEC 9절 "아래 상태는 **DB와 행 상세에서 구분한다**" + `충돌` 정의
- DETAILED 3.2 행 편집 상태 표의 `충돌` 행과 복구 방법
- APP_SPEC 6절 "기존 append-only 변경 원장을 **재사용한다**", "테이블을 모두
  새로 복제하라는 뜻이 아니다"

구현은 가장 좁게 했다. 새 테이블 없이 이미 있는 `board_revisions`에
`kind='conflict'` 한 줄을 덧붙이고, 저장이 롤백된 뒤 **별도 트랜잭션**으로
쓴다. 행의 값·revision·합계는 건드리지 않으므로 REVIEW R01의 1트랜잭션
보장은 그대로다. 다음 저장이 성공하면 가장 최근 사건이 `save`가 되어
충돌이 풀린다.

### `POST /api/tabs` — canonical 로 정합

8개 문서를 전수 대조했다. `/api/tabs`를 명명한 곳은 `WEB_LEDGER_APP_SPEC`
10절 한 곳이고(`/api/trips`를 명명한 곳은 **없다** — handoff의 언급은 이번에
제가 쓴 것), 같은 10절의 `POST /api/rows/{id}/save`·`revert`는 기존 코드가
이미 그 이름으로 라우팅하고 있었다. 즉 이 코드베이스는 행에서 이미 10절
이름 규칙을 따르고 있었다.

그래서 `POST /api/tabs`가 생성의 유일한 경로다. 중복 동작을 만들지 않기
위해 `POST /api/trips` 는 더 이상 만들지 않고 404를 답하고, 이미 proven인
`/api/trips/{id}/meta`·`/delete` 는 그대로 뒀다. "동작 하나가 두 URL에
답하지 않는다"를 검사로 고정했다.

### 이번 턴 실행값

- 신규 `webapp/tests/test_conflict_state.py` **26건**
- 변이 7건(기록 미작성, 상세 표시, 다음 저장으로 해소, 출력 집계, 집계
  문구, 탭 집계, 생성 경로 이중화) 전부 실패로 탐지되고 소스 복구 확인
- 매트릭스 proven 행 45 → **52행**, 인용 검사 전부 실존
- 문서 U+FFFD **0건**

최신 권위 suite 값은 아래 "이번 최종 검증" 절의 fresh 실행값을 따른다.

## 2026-09-27 · 운영 준비 재감사 (외부 전환 준비도)

사용자 요청으로 `incomplete-local 0`과 `external-only 6`을 **현재 작업트리에서
다시 검증**했다. 문서를 믿지 않고 8개 영역을 실제 합성 실행으로 돌려 본 뒤,
그 실행에서 드러난 결함만 고쳤다.

### 재감사한 8개 영역과 관측 결과

| 영역 | 조작한 것 | 관측 결과 |
| --- | --- | --- |
| ops readiness | `readiness_report` 호출 | `waiting_turns`가 실측과 무관하게 항상 0 → **결함** |
| 배포 환경변수 | 6개 거부 경로 + `dry_run_deploy` | 6개 모두 정상 거부, `dry run ok=True` |
| OIDC 설정 경계 | `session_adapter()`·`ensure_owner` 호출처 전수 조사 | `UnboundSessionAdapter`가 `None` 반환(정상 거부), `ensure_owner`는 로그인 경로에서 호출되지 않음 → 16.1/17.3 4항 충족 |
| 예약 API 어댑터 경계 | `apply_assignment_snapshot` 합성 호출 | 합성 스냅샷만 존재, 실연결 없음 (external-only 유지) |
| AI provider 경계 | 어댑터 인스턴스 확인 | `is_real_call=False`, `HttpTransport` 부재 → 의도대로 |
| 운영 DB 이관 dry-run | Phase 8 합성 경로 | 합성 기준본만 존재, 실데이터 없음 (external-only 유지) |
| backup/restore | 손상 DB·해시 부재·만료 파일 3종 | **해시 부재 시 통과 + 미처리 예외 → 결함** |
| production-like fail-closed | 6개 거부 경로 | 전부 정상 거부 |

### 고친 결함 5건

1. **복구가 fail-open이었다.** `restore_bundle`이
   `if expected and actual != expected`로 해시 비교를 걸러, manifest에 db 해시가
   없으면 비교를 건너뛰었다. 그 결과 DB 파일이 아닌 것을 복구 대상으로 복사하고
   `sqlite3.DatabaseError`로 예외가 터졌다. 이제 해시 부재는 거부이고, 열지
   못한 DB는 보고이며, 남은 파일은 조용히 지우지 않고 "대상 디렉터리가 깨끗하지
   않다"고 말한다 (`ops.py` `_discard_restored`가 Windows 파일 잠금까지 고려).
2. **readiness가 측정하지 않은 수치를 0으로 말했다.** `waiting_turns = 0`이
   아무 일도 하지 않는 분기 안에 하드코딩돼 있었다. 이제 실측값을 읽고, 실측이
   없으면 0이 아니라 "측정 안 됨"을 낸다 (`waiting_turns_measured`).
3. **명세 17.2가 요구한 회복 수치가 runbook에 없었다.** `최대 잃을 수 있는 최근
   입력 범위`, `시험 복구에 걸린 시간`, `저장 비용과 보관 기간`,
   "무손실/무중단 운영을 약속하지 않는다"가 모두 없었다. `recovery_figures`로
   실제 측정해 넣었고, `ops drill` 명령으로 시험 복구와 수치 산출이 한 번에
   돌아간다.
4. **명세 17.3 2항가 금지한 "합계만 같아도 통과"가 그대로였다.**
   `verify_restored_state`가 5개 행 개수만 비교했다. 개수는 같은데 금액·여행
   배정·규칙 버전이 다른 DB를 복구가 통과할 수 있었다. `business_state_digest`로
   명명된 업무 컬럼의 내용을 해시해 함께 비교하고, 어느 테이블이 달랐는지
   이름으로 보고한다.
5. **`HEALTH_SCHEMA_TABLES`에 죽은 `if False else`가 있었다.** 실효 값은 맞았지만
   운영 표면에 의미 없는 분기가 남아 있었다. 제거했다.

### 변이로 검사 effectiveness 확인

새 회귀 검사 23건에 대해 변이 13건을 다시 넣어 전건 실패로 확인했다. A~M 전부
`CAUGHT`다. 이 과정에서 **검사 자체의 결함도 2건 고쳤다.** 하나는 한국어 리터럴을
직접 옮겨 쓰다 어긋나(않**어**요/않**아**요) 실제로는 통과하던 검사와, 다른 하나는
`ops.recovery_lines` 출력을 그대로 기대값으로 써서 **함수를 자기 자신과 비교하는**
무의미한 검사가 된 것이었다. 기대 줄을 검사 쪽에서 figures 값으로 독립 구성하도록
바꿨다.


external-only 6항목의 **필요한 외부 입력 · 실행 명령 · 성공 판정 근거**는
구현 로그의 `### external-only` 절에 항목별로 적어 두었다. 요약하면:

| 항목 | 필요한 외부 입력 | 실행 명령 | 성공 근거 한 줄 |
| --- | --- | --- | --- |
| HOSTING-RESOURCE | 계정·카드, VM, 영속 디스크, 실제 경로 | `ops health --environment production` | `ok:true`, 임시 루트면 `TEMP_DATA_ROOT`로 거부 |
| GOOGLE-OIDC-CLIENT | 클라이언트 ID·시크릿, 콜백 주소, 소유자 `sub` | `ops health` | `synthetic_sessions.ok:true`, 첫 로그인은 owner 아님 |
| RESERVATION-API | 엔드포인트, 인증 방식, 배정 페이로드 형태 | `ops actions` + owner `/api/tabs` | 담당 해제 반영, 종료 여행 조회 유지 |
| PRODUCTION-DB | 실제 기준 워크북, 운영 DB 경로, 이관 범위 | `ops drill --target <별도> --runbook` | `recoverable:true`, `content_compared:true` |
| PAID-RESOURCE | 사용자 승인 | (없음 — 요건이 없음) | `state:not_approved` 유지 |
| DEPLOY | 위 전부와 배포 승인 | `ops dry-run --runbook` | `ok:true`, `applied:false`, 수치 수록 |

### 이 감사 이후의 판정

- **incomplete-local 0건.** 8개 영역을 합성 실행으로 점검했고, 그 실행에서 나온
  결함 5건을 닫았다.
- **external-only 6항목 유지.** 아래 표에 각각 필요한 외부 입력·실행 명령·성공
  판정 근거를 적었다.

## 이번 최종 검증 (권위, 2026-09-27)

코디네이터가 확인한 직전 권위값(360.29s)과, 그 뒤 세 결함을 더 닫고
돌린 현재 권위값을 함께 적는다.

```
# 코디네이터 확인값 (이번 코드 변경 전)
python -m pytest webapp/tests -q -p no:cacheprovider
  → 708 passed, 85 subtests passed in 360.29s

# 운영 준비 감사 이후 (ops.py·cli.py 수정 후)
python -m pytest webapp/tests -q -p no:cacheprovider --timeout=180
  → 791 passed, 104 subtests passed in 271.84s
```

이번 턴에 새로 닫은 세 결함: APP_SPEC 4.1 전역 영역(미저장 건수·마지막
저장 시각·이탈 확인), DETAILED 12.2 전체/검색 결과 합계 이름 분리, DETAILED 15
수기 지출 추가 버튼 위치. 근거와 변이 표기는 로그의 해당 절에 있다.

- 신규 26건(충돌 상태·경로 정합) 포함, 회귀 0건
- 매트릭스 proven 77행 · 인용 검사 215개 전부 실존 · 절 참조 82개 전부 일치
- **incomplete-local 0건**, external-only 6항목 유지
- U+FFFD 0 · 디버그 계측 0 · 산출물 0 · 잔여 프로세스 0
- 상세 근거와 자기 오류 기록은
  `docs/WEB_LEDGER_IMPLEMENTATION_LOG.md` 의 마지막 절

## 남은 작업


새 채팅의 우선 순서는 다음과 같다.

1. 현재 작업트리와 이 문서의 최신 재개 정보를 대조한다.
2. Phase 7, Phase 8, Phase 9 전용 검사와 관련 회귀 결과를 보존한다.
3. [역사 지시 — 현재는 완료] 현재 변경을 합친 전체 웹 장부 검사 383건을 한 번 실행한다.
   실제로 여러 번 실행했고 최종 값은 아래 "최신 전체 검증값" 절의
   `624 passed, 85 subtests passed`다.
4. Phase 7~9와 상세 계약의 요구사항을 항목별로 감사하고, 증거가 약한 항목은
   완료로 표시하지 않는다.
5. 실제 외부 연결은 사용자의 별도 결정 전까지 보류하고, 로컬 구현 완료와
   운영 연결 미완료를 분리해 기록한다.

아래 목록은 **현재 상태**다. 2026-09-27 요구사항 매트릭스 감사 결과를 반영했고,
로컬 구현이 미완인 항목은 없다. 닫히지 않은 것은 외부 자원에 의존하는 것뿐이다.

- [완료] 후보 기준 클릭 흐름: 합성 Chromium 1440/390에서 업로드·출력·규칙 질문
  경로를 검사했다. `test_ledger_design.py` 21건(390 지정 3건 포함, 3회 연속 통과),
  `test_rule_dialog_screen.py`, `test_replay_ui.py`. 부족한 경로가 발견되면 그
  경로만 추가로 검사한다.
- [완료] 키 관리와 owner 전용 비밀 설정: `GET/POST /access/providers`,
  `type='password'` 입력, 값 미반환, `sha256:` 지문만 노출, 별도 비밀 저장소.
  검사 `test_the_screen_uses_a_password_field_and_never_echoes_a_key`,
  `test_a_write_never_returns_the_value`, `test_the_key_never_reaches_the_ledger_database`.
- [완료] 인증과 직원 권한: 서버 측 role 판정, viewer 403/404 정책, 세대 결속,
  로그아웃, 증빙 미리보기 경계. 검사 `webapp/tests/test_access_control_phase7.py` 40건
  중 권한 경계를 직접 단정하는 항목
  (`test_a_viewer_is_refused_the_screen_and_the_write`,
  `test_a_viewer_sees_only_its_own_trip_and_other_trips_are_404`,
  `test_a_stale_session_is_refused_after_a_permission_change`,
  `test_logout_ends_the_session_and_names_what_the_client_must_clear`).
  **단, 실제 Google OIDC 로그인은 미완이다**(external-only, 아래 참조).
- [완료] 자연어에서 규칙으로 변환: `webapp/rule_text.py`가 제공자 산문을
  `normalize_draft` 검증을 통과한 후보로 바꾸고, `applied: False`와
  `requires_owner_confirm: True`를 함께 반환한다. 여행·연도·효과 문안은
  owner 선택값이나 행의 `occurred_on`에서만 오며 모델이 정한 rule_id·version·scope·
  금액은 버리거나 거부한다. 검사
  `test_provider_prose_reaches_a_validated_candidate_and_stops_there`,
  `test_a_model_cannot_set_its_own_rule_id_version_or_scope`,
  `test_the_candidate_can_then_be_confirmed_and_previewed`.
- [완료] 실제 AI 어댑터 경계: `provider_transport.py`가 두 제공자의 요청 형식,
  응답 파싱, 실패 분류(1:1 매핑), 모델 목록 조회, 연결 테스트, 제한 재시도를
  모형화했다. 전송 계층만 주입형이고 `is_real_call`은 언제나 False다.
  검사 `webapp/tests/test_provider_boundary.py` 97건.
- [external-only] 실제 AI 호출과 실제 키, 유료 승인, Google AI Studio 실제 프로젝트
  등급 확인. `HttpTransport`는 일부러 구현하지 않았고 `is_real_secret_store`는 False다.
- [external-only] 실제 운영 데이터 연결, 실제 Google OIDC, 실제 예약 API,
  호스팅 자원, 실제 배포, 실물 휴대폰, 실제 Excel 인쇄.
  `ops.EXTERNAL_CONDITIONS`의 여섯 항목은 미완료 상태를 유지한다.
- [역사 지시 — 현재는 완료] 실제 AI 어댑터, 키 관리, 인증과 직원 권한,
  자연어에서 규칙으로 변환은 아직 완료되지 않았다. 위 4개 항목으로 해소됐고,
  실제 자격 증명만 external-only로 남았다.
- [역사] 실제 운영 데이터 연결, 외부 AI 호출, 운영 배포는 이번 정리와 Git
  게시에 포함하지 않았다. Git 게시는 하지 않았다(커밋·푸시·배포 없음).
- 비용 파이프라인은 2026-09-08 인계의 PARTIAL 상태와 후속 결정 등록부를 함께 읽는다.

사용자는 쉬운 설명, 변화 없는 상태 알림 생략, A/Ramp/Pretendard 디자인을 선택했다.
승인된 작업은 불필요한 재승인 없이 진행하며 같은 파일의 작성자는 하나로 유지한다.

## 저장소 정리와 로컬 보존

Git 내부를 제외한 1,408개 파일의 경로, 크기, 수정 시각을 순회했다.
전체 코드 의미 감사나 모든 문서의 사실 검증을 완료했다는 뜻은 아니다.

- `.local-archive/cleanup-20260927/inventory-before.json`: 정리 전 파일 목록.
- 같은 보관함의 `bank-identity-5f500eea/`, `r08/`, `temp_func.py`: 원본 루트에 있던 임시 작업물을 이동했다. 삭제하지 않았다.
- `before-integration/`: 후보 반영 전 웹앱 파일.
- `paseo_bdf58685_full_transcript.local.md`: 로컬에서 변경된 과거 긴 대화 기록의 백업.
- 원본 DB, 워크북, 감사 산출물은 유지했다. 새 `outputs/` 파일과 실행 DB, 로컬 보관함은 Git 게시에서 제외한다. 이미 추적 중인 출력은 추적 상태를 유지한다.
- Python과 pytest 캐시는 재생성 가능하지만 이번 실행에서는 삭제하지 않았다.

로컬 보관함과 원본 자료는 Git clone으로 복원되지 않는다. 다른 컴퓨터로 옮길 때는
필요한 원천 자료를 별도로 안전하게 전달해야 한다. Git에는 실행 코드, 명세, 인계와 합성 테스트를 보존한다.

기존 대화 기록의 대규모 변경은 이번 코드 게시에 포함하지 않는다.
해당 로컬 변경은 백업 해시 일치를 확인한 뒤 작업 경로를 기존 Git 버전으로 복원했다.
과거 명세의 설계 전용이나 Phase 5 정지 문구는 작성 당시 기록이며 이후 사용자의
구현, 디자인 반영, Git 게시 지시를 취소하는 현재 지시로 해석하지 않는다.

## 이번 최종 검증 (통합 당시 기록, 아래 최신 값으로 대체됨)

아래 값은 Phase 6 후보를 본 저장소에 통합했을 때의 실행 결과다. 이후 390 화면
수정과 Phase 7~9 구현, 요구사항 감사가 추가되었으므로 **최신 값은
`465 passed, 21 subtests passed in 194.71s`**다. 이 절은 당시 기록을 보존한다.

- [역사 실행값] 본 저장소 웹앱 전체: `383 passed, 21 subtests passed in 184.00s`, 종료 코드 0.
- 비용 파이프라인 관련 검사: `83 passed in 9.57s`, 종료 코드 0.
  대상은 `test_pipeline_audit`, `test_agoda_journal_shadow_v5_ota`,
  `test_direct_trip_schedule_authority`, `test_reservation_schedule_export`다.
  전체 비용 파이프라인 테스트나 실제 원천 대사를 모두 실행한 것은 아니다.
- 신규 게시 대상에 DB, XLSX, 토큰 파일 없음. 추가된 텍스트에서 대표적인 키 형식 5종의 일치 없음.
  모든 종류의 비밀값이 없음을 보증하는 검사는 아니다.
- 변경 공백 검사 통과. 원형을 보존한 과거 검사 XML 3개와 폰트 라이선스의 줄 끝 공백은 제외했다.
- 캐시 삭제를 포함한 첫 통합 명령은 실행 정책이 거부하여 미실행이다.
  후속 정리는 삭제 없이 개별 백업과 이동으로 완료했고 캐시는 그대로 보존했다.

기능 코드는 새 모델에 재작성시키지 않고 기존 후보를 해시로 검증해 통합했다.
이번 세션은 파일 정리, 문서 수정, 로컬 검증과 Git 게시만 수행했다.

## Phase 6 제공자 경계 — 2026-09-27 추가

`docs/WEB_LEDGER_PHASES.md` Phase 6의 3~5항과 상세 계약 7절이 요구하는
"실제 호출 없이 닫을 수 있는 경계"를 구현했다. 실제 네트워크 호출과 실제
자격 증명은 여전히 하지 않았고, 하지 못한 이유를 코드와 테스트가 함께 기록한다.

### 새로 추가한 모듈

- `webapp/provider_transport.py`: `MuseAdapter`, `GeminiAdapter`,
  `RecordingTransport`, `TransportResponse`, `TransportUnavailable`.
  각 제공자의 요청 형식(OpenAI 호환 채팅 / `generateContent`)과 응답 파싱,
  그리고 `reason_for_status`·`classify_exception`의 실패 분류를 모형화했다.
  `HttpTransport`는 일부러 구현하지 않았다. 반쪽짜리 네트워크 클라이언트를
 shipping하면 실제 호출이 나가지 않은 turn을 `is_real_call = True`로
  기록할 수 있기 때문이다.
- `webapp/provider_config.py`: `SecretStore`(로컬 파일, 소유자 전용 권한 시도),
  `ProviderConfig`(서버 측 읽기 전용 뷰), `ProviderConfigService`(owner 전용
  쓰기 경로), `redact`, `fingerprint`.
- `webapp/rule_text.py`: 제공자 산문을 구조화된 규칙 *후보*로 바꾸는 로컬 계약.

### 닫은 요구사항

1. 설정·비밀 경계. 키는 owner 전용 화면(`GET /access/providers`)과
   `POST /access/providers`로만 등록된다. `type='password'` 입력이고, 응답에는
   값이 절대 돌아오지 않으며 `sha256:` 지문만 보인다. 비밀 저장소는 장부 DB
   밖의 별도 파일이라 백업·출력·이관에 섞이지 않는다. `is_real_secret_store`는
   False다. 요청 본문은 제공자나 키를 고를 수 없다.
2. 전송 계약. 주입형 transport 위에서 프로토콜·요청·응답 파싱과 timeout,
   connection, auth, rate, quota, service 실패의 정확한 1:1 매핑을 검증한다.
   실제 호출 여부는 `is_real_call`로 항상 False이며 테스트가 확인한다.
3. 전환·대기·복구. Muse PC 꺼짐(연결 거부)·timeout은 설정된 Gemini으로 정확히
   한 번 전환한다. auth 실패도 전환 대상이다. 반면 무료 한도 소진·예산 소진·
   미설정은 `WAITING_FAILURES`라 전환을 쓰지 않고 대기하며, 행·규칙 초안·
   질문 답변이 보존된다. 늦은 응답은 채택 또는 거부가 기록되고, Muse가 복귀하면
   다음 턴부터 다시 쓰인다. 한 턴에 adopt되는 응답은 하나뿐이다.
4. owner 전용 비밀 설정 API. viewer는 화면과 쓰기 모두 403
   `ACTION_FORBIDDEN`이다. 바인딩되지 않은 설정 표면은 503으로 거절해 관대한
   기본값으로 새지 않는다.
5. 자연어→규칙. 제공자 산문은 `rule_text.rule_candidate`를 거쳐
   `normalize_draft` 검증을 통과한 **후보**가 된다. 후보는 `applied: False`,
   `requires_owner_confirm: True`를 함께 반환하고, 여행·연도·효과 문안은
   owner가 고른 값(또는 행의 `occurred_on` 연도)에서만 온다. 모델이 스스로
   정한 rule_id·version·scope·금액은 버리거나 거부한다. 영향 건수·합계는
   후보에 실리지 않고 미리보기 API에서만 나온다.

### 이 과정에서 고친 실제 결함

- `dialog_turn.WAITING_FAILURES`가 정의만 있고 쓰이지 않아, 무료 한도 소진
  때문에 정상인 fallback이 달라도 전환해 버렸다. 상세 계약 7은 대기를 요구한다.
- `TRANSPORT_REASONS`가 `not_configured` 등을 몰라, owner가 키를 지운 뒤
  `service_error`로 뭉개져 fallback을 소모했다.
- `SecretStore.get`이 `str`만 반환해, `set_provider(timeout=15)`가 저장한
  15.0이 빈 문자열로 읽혀 20.0 기본값으로 되돌아갔다. 회귀 테스트를 추가했다.
- `_phase7_refuse`가 예기치 않은 예외를 404로 위장했다. AttributeError가
  404 "없음"으로 보여 원인을 찾을 수 없었다. 이제 500 `INTERNAL_ERROR`가 되고
  예외 종류만 로그에 남는다.
- `provider_transport.redact`가 토큰을 소문자로 접은 뒤 대소문자 접두사를
  비교해, `AIza`로 시작하는 실제 키를 걸러 내지 못했다.
- `rule_text`의 여행 ID 정규식이 뒤에 `\b`를 요구해, 한국어 바로 뒤에 오는
  `trip-demo-b로` 형태를 놓쳤다.

### 여전히 외부 조건

실제 제공자 호출, 실제 키와 유료 승인, 실제 Google OIDC 로그인, 실 예약 API,
운영 DB와 실제 Google 기준본 이관, 호스팅 자원, 실제 배포. 이들은 실제 자격
증명이나 사용자 승인 없이는 닫을 수 없으며 `ops.EXTERNAL_CONDITIONS`에 남아 있다.

## 2026-09-27 · HOSTING 준비 완료 (사용자 계속 요청)

**바인딩.** `127.0.0.1` 하드코딩은 없어졌다. 기본값은 그대로 루프백이므로
기존 동작은 바뀌지 않는다. 정답은 reverse proxy 였다 — 명세 19.2가
"외부에는 HTTPS 앱 경로만 제공하고 SQLite·원천 디렉터리·작업자 관리 포트는
공개하지 않는다"고 정하고, 이 서버는 TLS를 끝내지 않기 때문이다.

```
# 기본(권장): 루프백 + 같은 머신의 HTTPS 프록시
python -m webapp.cli serve --snapshot ... --host 127.0.0.1

# 컨테이너 안의 프록시: 반드시 명시해야 한다
python -m webapp.cli serve --snapshot ... --host 0.0.0.0 --behind-proxy
```

`--host 0.0.0.0` 을 단독으로 주면 `UNSAFE_BIND` 로 거절된다(종료 코드 2).
`ops dry-run` 도 같은 규칙을 쓰고, 승인 없이는 `app_port_not_exposed_without_tls`
로 실패한다.

**영속 경로.** `run_candidate.py` 가 장부를 `<checkout>/runtime/` 아래에 두던
기본값을 제거했다. `--data-root` 또는 `WEBLEDGER_DATA_ROOT` 가 필수이며,
운영 환경에서 체크아웃 내부를 고르면 `CHECKOUT_DATA_ROOT` 로 거절한다.
레이아웃은 `data/{board.sqlite,exports,evidence,source}` 이고 서비스와
health·readiness·drill 이 같은 설정 객체를 읽는다.

**서비스 예시.** `ops dry-run --unit <경로>` 가 systemd 단위를 **파일에만** 쓴다.
설치·시작하지 않는다. 루프백 바인딩, `WorkingDirectory`/`ReadWritePaths` 는
데이터 루트, 비밀 값 없음(`EnvironmentFile` 지시), 확인 명령 주석 포함.

**확인 절차** (runbook `## 운영 확인 절차` 절에도 있음):

```
python -m webapp.cli ops health  --environment production --secret MUSE_KEY
python -m webapp.cli ops actions
python -m webapp.cli ops drill  --target <운영과 다른 경로> --runbook RUNBOOK.md
python -m webapp.cli ops dry-run --secret MUSE_KEY --runbook RUNBOOK.md
```

`health.failed` 가 비어 있고 `drill.recoverable` 과
`drill.restore.state.content_compared` 가 true일 때만 전환을 검토한다.

**이 턴에 고친 결함 5건**: 바인딩 하드코딩 2곳, `dry-run` 이 public bind 를
통과시키던 fail-open, 진입점의 체크아웃 상대 기본값, 진입점 거절의 traceback,
health 문면의 자기모순. 변이 15건 전건 탐지 확인, 검사 자체 결함 3건도 고쳤다.

**하지 않은 것**: 계정 생성, 결제, VM 자원, 실제 배포, commit, push.
`HOSTING-RESOURCE` 은 external-only 로 남는다.
