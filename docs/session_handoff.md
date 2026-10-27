# 현재 상태와 남은 일

기준: 2026-10-28 세션 `7c022586` → `2ac4764d`의 승인 작업을 현재 Supervisor가 인수했다. 이전 계정 한도 종료 기록과 실제 파일·배포 evidence를 대조했으며 이전 Supervisor에게 메시지하거나 재개하지 않았다. main·병합·배포·현재 상태 작성자는 현재 Supervisor 하나다.

## 현재 승인된 실행 큐

최신 사용자 승인은 새 리팩터링/OTA 성능 명세의 단계별 구현과 중단된 임시 구현의 검수·통합·배포·공식 보관이다. 지정 위임 순서는 Anus Free Auto → OpenRouter Free Router → AGY Gemini 3.8 medium → AGY Opus 4.6 thinking → GPT-6 Luna low였다. 기존 위임과 변경을 재사용했으며 Opus/일부 Codex 한도 및 Free Router 제공자 오류 이력이 있다. 아래 미완료 항목을 과거 완료 기능과 구별한다.

| 작업 | 현재 근거 / 다음 작업 |
| --- | --- |
| Trip.com 통화 비교·카드 필터·장부 표시 | **COMPLETE / DEPLOYED** — PR #200, 코드 `8e5eb76`, 병합·운영 `44e1e6bb90105e5d65c1b954f0c9808f4266b407`. 190 passed, 인접 125 passed/2 failed. 같은 127개 묶음에서 기준 main `0b9ebf4`도 동일 2 failed: 부분 그룹 fixture HOLD_NO_CARD와 후속 스키마 준비 오류. 실패를 통과로 계산하지 않았다. 운영 925 blobs 일치·health/ready200·보호API401·13표 동일, 실제 필터와 여행 복사 버튼 확인. worktree 고유커밋0·dirty0·터미널0·잔여 임시는 합성DB만임을 확인하고 `wks_7bc6650d01ff72da` 공식 archive 완료. |
| 카카오 환불 실제 경로 | **COMPLETE / DEPLOYED（코드 범위）** — PR #193 병합 `819c4ba`, 운영 `bff4ffd`. 선행178 passed와 최신 main 통합 후29+6+117+26 passed. 실제 추론2묶음의 기장 보류/환급 미완료 표시 확인. 원승인 없는 실제11건의 확정 연결·환급 수락은 별개다. |
| RF-001 쓰기 경계 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #202 병합. SQL 원문 비출력·오류 JSON·대표6경로 지도, 4 passed. 간접 persistence/audit·권한 체인은 `refactor-write-boundaries.md`의 OPEN_QUESTION으로 남음. 다음: 주입 backend·Google read·여행 수동 결정 경계를 소스에서 연결한다. |
| RF-001 엔트리포인트 지도 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #204 병합, 정적 AST 호출/route 후보·소유 모듈 지도, 3 passed. 미완성 API 분기는 main에 넣지 않고 `.local-archive/refactor-review-20261028/rf001-unfinished-api.patch`로 보존. 실제 runtime activation·간접 call target 증명은 아직 아님. |
| RF-003 자료 보호 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #203 병합, 합성 repo16 passed. 정책 JSON·staged 차단 exit code·경로 검증 보완. Git 메타데이터 inventory이며 기존 고객 파일 내용의 민감도·운영 소비자 분류와 배포 allowlist 완료는 아님. |
| RF-004 테스트 영향도 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #205 병합, 7 passed. 핵심 매핑·미매칭 안전 최소 검사와 실패 코드 유지. 모든 OS/실DB/전체 collection 기준선 완료로 확대하지 않는다. |
| RF-005/109 의존성 후보 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #206 병합, 8 passed. 상대 import·외부 root·오류·읽기/쓰기 후보 분류 수정. 실제 호스트 호출 전체 수락·배포 entrypoint 통합은 남음. |
| Toyoko 메일 | **COMPLETE / DEPLOYED（코드 범위）** — PR #207/#208, 최종 `570978b`. 제목 탐색·낮은 신뢰와 인증 경로 분리·불량 헤더 격리. 105+6 passed, 통합42 passed, 추가 회귀8 passed. 운영 실메일 재수집·고객 예약 개별 수락은 미실행. |
| 여행 귀속 계약 조사 | **R0 PARTIAL / TOOL_DEPLOYED** — PR #209, `764c82d`, 5 passed. Google authority·기간·수동 우선 정의 위치와 합성 AST 경계 확인. 위치 발견은 동작 검증/실자료 원인 확정이 아니다. |

기존 구현 묶음은 모두 검수·병합했으며 임시 worktree 공식 archive를 완료했다. 마지막3개는 고유커밋0·dirty0·미추적0·터미널0·무시 경로는 캐시만임을 확인했다. 공유 stash·사용자 미추적 자료는 보존했다. 다음 단계는 R0 미확인 경계의 소스 근거 보완이며, R1 DTO/전면 리팩터링 전체 완료나 실자료 수락을 뜻하지 않는다. 종료된 세션은 재개하지 않는다. 이번 배포/브라우저/보호 증거는 `.local-archive/refactor-runtime-release-20261028/` 및 [운영 기록](operations.md)에 있다.

### 완료한 RF-001/004 후속 묶음

- **COMPLETE / DEPLOYED（이번 묶음）** — PR #211, 코드 `b2d8a06`, main/운영 `f7df4bc29d4e9dc87b2f6ddd68b8853c7be9be3a`. 최종 합성6 passed·guard 차단0/삭제0·배포942 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 CLI도 exit0·정의 후보3,957·오류0이다. 독립 개발 도구/문서 변경이므로 전체 회귀와 브라우저는 생략했다. 근거는 `.local-archive/r0-boundary-baseline-20261028/`와 운영 기록이다.
- 두 구현자 결과를 검수·통합했다. RF-001 소스 근거 커밋은 `1187954`이며 실제 Google sync CLI 호출·public/ADC 선택과 여행 검증기/change_log sink를 확인했다. RF-004 초기5 passed/CLI 파싱 오류를 최종 통과로 계산하지 않았고, 보완 후6 passed·staging/배포본 CLI exit0으로 수락했다. R0 전체 완료를 뜻하지 않는다.

### 완료한 RF-003 자료 참조 후보

- **COMPLETE / DEPLOYED（선택적 참조 조사 범위）** — PR #213, 코드 `ef91e4a`, main/운영 `44421df083f6eb7447bbfe4dc0ad10e4fb4039ca`. 보호21개 검사 근거（20 passed 후 fixture 교정한 추가1 passed）·guard 차단0/삭제0·942 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 CLI도 metadata942·소스504·정확참조99·오류0, exit0이다. 근거는 `.local-archive/rf003-source-references-20261028/`와 운영 기록이다.
- 같은 호스트/기존 local workspace의 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`（Luna low）를 재사용했다. 소유 파일은 `tools/check_tracked_data.py`, `tests/test_tracked_data_guard.py`뿐이다. commit/PR/병합/운영은 Supervisor 소유다.
- 추가 옵션 `--source-references`에서만 허용된 추적 Python 소스 AST와 Git 자료 경로 metadata를 대조한다. 고객 자료 본문·SQL·시크릿 출력 없이 명시적 읽기/쓰기/참조 후보를 기록하며 기존 기본 metadata-only·차단·보존 계약을 유지한다. 후보만으로 producer/consumer/active_use·민감도 안전을 확정하지 않는다.
- 검수에서 일반참조 누락·receiver/내용 문자열 혼동을 교정했고 Supervisor가 내부 symlink 차단·scan0 집계를 보완했다. 초기19 passed와 확장 fixture 준비 실패를 최종 통과로 과장하지 않는다. 실제 자료 분류/삭제·Git 역사 재작성은 실행하지 않았다. 동적 경로·간접 소비자·운영 활성 여부는 미확인이다.

### 완료한 RF-005/109 운영 호출 지도 보완

- 브랜치 `docs/rf003-release-and-runtime-map-20261028`, 같은 local workspace에서 구현자 `46ede148-c8a7-43b9-b783-1a89a671be40`（Luna low）가 `docs/specs/refactor-runtime-catalog.md`만 작성한다. Supervisor는 상태/운영 기록과 PR을 소유한다. 문서전용이며 테스트·빌드·브라우저·재배포 없음.
- Supervisor는 scheduler metadata에서 Board의 SHA 고정 start_web_ledger_host 참조와 SourceRefresh의 `tools/watch_review_source.ps1` 이름/저장소 cwd 참조를 확인했다. 원문 인자·비밀값은 출력하지 않았다. 담당자는 repo 안의 실제 호출·외부 dependency·쓰기/복구 게이트를 소스 경로/줄로 추적하며 repo 밖 파일/DB/설정은 읽지 않는다.
- **COMPLETE（이번 문서 범위） / R0 전체 PARTIAL** — Board launcher→run_candidate, SourceRefresh wrapper→collect/activate→bundle/config/status, 임시 복사본 DB probe·별도 복원 target·dry-run manifest의 소스 참조를 대조했다. 전달된 scheduler metadata와 source-only 근거를 분리했고, PR #213 이후 최종 SHA/health 미확인 문구는 이미 검증된 운영 기록 참조로 교정했다. 원문 인자·환경/인증·외부 호스트 코드·DB는 열지 않았다. diff/참조/링크만 확인하며 테스트·빌드·브라우저·재배포는 하지 않는다. 외부 wrapper 전체 동작·실제 SourceRefresh 활성 결과는 미확인이다.

### 완료한 RF-002 거래 상태 계약의 독립 기반

- 기준 main `37cf912`（PR #214 문서 병합）, 브랜치 `refactor/rf002-transaction-state-contract-20261028`. 운영은 계속 `44421df`다. R0 정적 지도·보호·표적검사 기준선은 확보했으며 외부 운영 OPEN_QUESTION은 유지한다.
- 같은 local workspace의 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`（Luna low）가 새 `app/transaction_contract.py`, `tests/card_pipeline/test_transaction_contract.py`만 작성한다. 실제 런타임 경로에 연결하지 않는 순수 DTO·mapping 변환의 합성 계약부터 시작한다.
- 기존 거래 원본/금액/통화/ID·사용자 결정·독립 상태 축과 알 수 없는 값·필드/누락/None을 보존한다. 새로운 금융·환급·기장·여행 정책을 계산하거나 런타임/DB/Google을 변경하지 않는다. 입력/출력 alias 오염·정확 roundtrip을 새 합성 검사로 확인한다.
- **COMPLETE / DEPLOYED（독립 거래 DTO 기반）** — PR #215, 코드 `77e2c0f`, main/운영 `179acb59dbe22dc28b982c8a2d16f5c7de8ed05c`. 최종13 passed·guard 차단0/삭제0·추적944 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 합성 import/roundtrip/입력변경 차단 스모크도 통과했다. 아래 검수 대기·미병합 문구는 과거 이력이며 현재는 수락·병합·배포 완료다. 기존 런타임에는 연결하지 않았고 전체 RF-002 완료가 아니다.
- 검수에서 최초7/10 passed 이후 발견한 mutable 객체·public 생성·timezone/key 노출을 교정했다. 최종13 passed로 수락했으며 지원 domain에서 누락/None·unknown 상태/추가값·금액/통화/ID 왕복과 불변성을 확인했다. 미지원 객체·cycle은 원문 없는 오류로 거부한다. 실제 transactions 필드와 axis 목록을 대조했고 미래/runtime 필드는 extras로 보존한다. 전체 RF-002 채택이나 R0 운영 미확인 해소는 아니다.

### 완료한 RF-002 OTA 상태 계약의 독립 기반

- 기준 main `d4718a8`（PR #216 문서 병합）, 브랜치 `refactor/rf002-ota-state-contract-20261028`의 같은 local workspace에서 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`（Luna low）가 새 `app/ota_state_contract.py`, `tests/card_pipeline/test_ota_state_contract.py`만 작성한다. Supervisor가 branch/문서/PR/운영을 소유한다.
- 관측된 event/result/snapshot 필드에 근거해 예약관계·카드검증·여행귀속·내부기록·실제환급을 분리한다. 기존 공개 FieldSlot을 재사용하고 알 수 없는 값·누락/None·수동/exact/inferred·취소/stale·ID/금액통화를 정확히 보존한다. 원문에 없는 기장·환급확정·여행을 만들지 않고 기존 runtime helper에는 연결하지 않는다.
- **COMPLETE / DEPLOYED（독립 OTA 기반）** — PR #217, 코드 `0ad04bd`, main/운영 `361d012d495f9a3a245e092933e4102967689642`. 최종16 passed·guard 차단0/삭제0·추적946 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변。배포본 합성 import/왕복·명시적 종류에 따른 상태 분리·입력 변경 차단·기장/환급확정 비창작 스모크 통과.
- 검수에서 초기13/15 passed 이후의 shape 추정·core_link 오분류·상위 예약축 직렬화 누락을 교정했다. `kind`를 호출자가 명시하고 카드 status·snapshot freshness·예약관계 상태를 분리한다. `core_link`는 projection 근거이며 내부기장 축은 비어 있다. unknown/None/누락·ID/금액·수동/exact/inferred/stale·예약 추가필드·중첩 불변성을 확인했다. 기존 runtime 미연결이고 실제 대사·배정·기장·Google 쓰기는 없다.

### 진행 중인 RF-002 실제 읽기 경로 채택 조사

- 브랜치 `docs/rf002-ota-release-and-adoption-20261028`. 같은 local workspace의 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`（Luna low）가 `docs/specs/refactor-master-20261027.md`만 수정한다. 가장 작은 실제 읽기 소비경계·입출력 shape·caller/authority/freshness·복사비용·합성 동등성 검사 범위를 소스 근거로 좁힌다.
- **COMPLETE（소스 조사）** — 실제 caller의 freshness gate와 helper의 좁은 입력 shape를 대조했다. 전체 DTO freeze/thaw는 전량 복사를 늘리므로 채택하지 않는다. 다음 구현은 `project_card_ota_statuses` 실행 본문을 유지하고 필요한 필드를 별도 `TypedDict` 정적 읽기 계약으로 선언·입력 annotation에 연결하는 최소 범위다. 기존 금융/여행/Google 쓰기 authority는 그대로 유지한다. 이 문서전용 검수는 diff/참조/링크만 확인하며 테스트·빌드·브라우저·운영 재검사는 하지 않았다.

### 완료한 RF-002 OTA 상태 조회의 정적 읽기 계약

- PR #218 문서 병합 후 브랜치 `refactor/rf002-ota-status-read-contract-20261028`. 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 새 `app/ota_status_read_contract.py`, 기존 `app/ota_core_projection.py`만 작성한다.
- helper가 읽는 필드의 `TypedDict`와 입력 annotation만 연결하고 상태 계산 본문·순서·원본 identity·caller freshness는 유지한다. wrapper/factory·복사·원문변환·새 정책/쓰기 경로를 추가하지 않는다. 타입 선언은 runtime 검증/불변 snapshot을 제공하지 않는다.
- **COMPLETE / DEPLOYED（해당 읽기 계약）** — PR #219, 코드 `175c3a2`, main/운영 `42999afa15373014c35be9ee10fda308a6dd1e3c`. 표적3파일28 passed·compile/diff·본문AST동일. 합성1000결과+1000후보 출력 동일; 30회 중앙값 baseline0.052944s/변경0.053033s·peak156,994/156,946B. 제품 지연 개선 주장은 없다.
- guard 차단0/삭제0·947 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 annotation 해석·exact/group/reservation/None 스모크 통과. 전체 회귀/브라우저는 실행본문 불변의 타입 변경이므로 생략했다. 근거는 `.local-archive/rf002-ota-status-read-20261028/`와 운영 기록이다.

### 완료한 RF-002 거래 배치 조회의 정적 읽기 계약

- 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 새 `app/transaction_read_contract.py`, 기존 `app/review.py`, `app/__init__.py`만 작성한다. 현재 브랜치는 Supervisor 소유 `docs/rf002-ota-status-read-release-20261028`이며 구현자는 branch/commit/PR/운영을 변경하지 않는다.
- 실제 `get_batch/_row_dict/_counts` 출력과 facade의 return annotation만 연결한다. SQL/실행본문·권한·금액/ID·상태 계산·원본 JSON·호출 순서를 유지하고 DTO 복사·cast/factory·새 runtimecall을 추가하지 않는다. 실제 출력 필드의 독립 축과 nullable 값·future state counts를 TypedDict로 명시한다.
- **COMPLETE / DEPLOYED（해당 읽기 계약）** — PR #220, 코드 `a8d28dd`, main/운영 `b3cabe8b38b2956381a8827327445cfa30b64c35`. 합성pipeline 지정 범위3 passed/42 deselected·4함수 실행AST동일·compile/diff 통과. Supervisor는 동적 counts를 `dict[str,int]` alias로, 실제 출력 키는 required/nullable value로 교정했다. SQL/실행본문/원행/ID·금액/사용자결정/권한/반환 순서가 같으며 새 wrapper/복사/runtime 검증은 없다.
- guard 차단0/삭제0·948 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. 배포본 annotation/required키/합성fake-store batch/nullable/미지 상태counts 스모크 통과. 전체 회귀/브라우저는 실행본문 불변의 타입 변경이므로 생략했다. 근거는 `.local-archive/rf002-transaction-read-20261028/`와 운영 기록이다. 전체 RF-002 완료는 아니다.

### 진행 중인 RF-201 기존 디자인 토큰 조사

- 같은 local workspace에서 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`（Luna low）가 `docs/specs/refactor-master-20261027.md`만 수정한다. 현재 Supervisor 브랜치는 `docs/rf002-transaction-read-release-20261028`이다. 마스터가 허용한 독립 토큰 조사이며 기존 RF-002 금융/OTA 경계를 변경하지 않는다.
- site_theme/site_shell/ledger_design의 이미 통합된 토큰·shell/theme owner를 소스와 기존 검사에 대조하고 실제 중복/누락만 찾는다. 기존 표시 값을 유지하는 최소 토큰 정리 후보 하나와 영향 페이지/필수 검사를 제시한다. 수동 테마 아이콘1개·기존 URL/DOM을 유지한다.
- **IN_PROGRESS / NOT_VERIFIED** — 문서전용 source/diff 참조 조사이며 테스트·빌드·브라우저·호스트 재검사·시각 변경은 하지 않는다. 완료 알림 후 `git diff -- docs/specs/refactor-master-20261027.md`를 검수한다. 실제 모바일/200%/모든 화면 수락을 주장하지 않는다.
- **COMPLETE（소스 조사）** — 공통 색상과 단일 토글이 이미 통합돼 있음을 소스/기존 검사에 대조했다. wrap_document는 전체 STYLE와 root palette를 함께 삽입하고 fragment는 유지한다. 다음 최소 구현은 두 파일의 테마 버튼44px 반복을 공통 CSS 토큰으로 모으는 범위로 결정했다. token owner/fallback/기존 computed-size 검사 근거를 master에 기록했다. 문서 diff/source 참조만 검수했고 운영·브라우저를 다시 확인하지 않았다.

### 완료한 RF-201 테마 버튼 치수 토큰

- PR #221 문서 병합 후 브랜치 `refactor/rf201-theme-control-token-20261028`. 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 `webapp/site_theme.py`, `webapp/site_shell.py`만 작성한다. Supervisor가 branch/문서/PR/배포를 소유한다.
- 버튼 소유 `site_theme.STYLE`에 `--shell-theme-control-size:44px`을 선언하고 두 파일의 해당 버튼 width/min-width/height/min-height만 동일44px fallback으로 연결한다. 색상/sidebar/타버튼/DOM/JS/테마정책은 변경하지 않는다.
- **COMPLETE / DEPLOYED（해당 토큰）** — PR #222, 코드 `72781a6`, main/운영 `d230e124b27f268de8e8e3812abe53885e5e2212`. 지정 두 파일의4개 치수/44px 선언만 검수했다. 기존 manual-theme/mobile-topbar5 passed·익명CSS24조건 동일（375/1280·light/dark·100/200%·combined/개별fallback）. 결합44×44/확대88×88px·개수·색 동일. 실제 기기 미실행이고 전체 RF-201 완료가 아니다.
- guard 차단0/삭제0·948 blobs 일치·실행 SHA·health/ready200·보호API401·보호13표 불변. Aside 같은-origin GET200에서 token44px·8소비·단일버튼 확인, 사용자 페이지 탐색/입력/테마 변경 없음. 근거는 `.local-archive/rf201-theme-control-20261028/`와 운영 기록이다. 국소 token 추출로 전체 회귀는 생략했다.

### 진행 중인 RF-202 공통 shell 응답 경로 조사

- 현재 브랜치 `docs/rf201-theme-control-release-20261028`, 같은 local workspace 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`가 `docs/specs/refactor-master-20261027.md`만 작성한다. 이미 통합된 wrapper/단일 테마를 재구현하지 않는다.
- HTTP HTML 응답 writer→wrap_document→주요 private renderer의 source 경로와 auth/public/API/fragment 예외를 매핑한다. 실제 우회가 있을 때만 최소1개 후보를 제시하고 native nav/main 소유권·URL/폼/JS/ID·테마 아이콘1개를 보존한다.
- **IN_PROGRESS / NOT_VERIFIED** — 문서전용 source/diff 참조 조사이며 테스트·빌드·브라우저·호스트/DB 재검사를 하지 않는다. 실제 기기/200% 전체 수락이나 저장소 전수 완료로 확대하지 않는다. 다음 명령은 완료 알림 후 `git diff -- docs/specs/refactor-master-20261027.md`다.
- **COMPLETE（소스 조사）** — Handler._send→wrap_document와 카드/Google/항공권/OTA/영수증·native ledger·fragment/auth/public/API 경로를 대조했다. 표본 범위에서 private 전체HTML 우회는 발견하지 못했고 기존 의도 예외를 새 작업으로 만들지 않는다. 동적 문서 전수·실제 기기/200% 수락은 미확인이다. 문서 diff/source 참조만 확인했다.

### 진행 중인 OTA 대기열/페이지네이션 기준선

- 기준 main `0512d80`（PR #223 문서 병합）, 브랜치 `refactor/ota-queue-baseline-20261028`. 같은 local workspace 문서 담당자 `46ede148-c8a7-43b9-b783-1a89a671be40`가 `docs/specs/ota-review-queue-performance-20261027.md`만 작성한다. 기존 API/public allowlist·snapshot publish/freshness·summary/events/cursor 기존 구현 여부·순수 queue projection 입력을 소스에서 조사한다.
- Supervisor의 인증 같은-origin GET8회 기준선:200·응답899,499B·같은세대1·공개이벤트1,072·카드후보map0. p50 205ms/표본p95 1,750ms이나 측정 중 refreshing/stale이므로 ready/warm 성능이나 server-only p95가 아니다. 공개목록 subset을 전체 정본 건수로 보고하지 않는다. 사용자 페이지 탐색/입력/테마와 금융/Google 상태를 바꾸지 않았다.
- 원문 없이 알려진 status별 집계·경고 개수·bytes/time만 `.local-archive/ota-queue-baseline-20261028/current-api-baseline.json`에 보존했다. **SOURCE_AUDIT_PENDING** — 완료 알림 후 순수 queue/summary의 최소 구현 범위를 결정한다. 기존 solver·manual/exact link·원승인/복수환불·여행/금융 쓰기와 legacy route는 유지한다. 다음 명령은 `git diff -- docs/specs/ota-review-queue-performance-20261027.md`다.
- **SOURCE_AUDIT_REVIEWED** — 별도summary/events/cursor 미구현과 기존 lazy-card GET·worker freshness/last-good·public allowlist를 소스 대조했다. public 목록은 holds subset이므로 전체 canonical summary 입력과 구분하도록 교정했고 검증된 예약 그룹 계약 전에는 singleton fallback만 허용한다. 다음은 route/UI 미연결 순수 queue classification/summary이며 금융 상태 변경이나 완료/성능 개선을 주장하지 않는다.

### 진행 중인 OTA 순수 queue/summary projection

- PR #224 문서 병합 후 브랜치 `feat/ota-queue-pure-projection-20261028`. 같은 local workspace 구현자 `0ee2f107-8e89-40d3-be2b-42999b6550e3`가 새 `app/ota_queue_projection.py`, `tests/test_ota_queue_projection.py`만 작성한다. route/GET/UI/solver/store에는 연결하지 않는다.
- 명시적 canonical/public_subset coverage·freshness·유효한 source 상태/근거·경고를 바탕으로 display queue만 계산한다. completed는 대사검토 범위이며 기장/실환급/여행 확정이 아니다. unknown/changed/missing/manual-warning·duplicate/missing identity와 stale 등은 완료로 올리지 않는다. 검증된 예약 그룹 계약 전에는 singleton fallback이며 input event를 버리거나 합치지 않는다.
- **IN_PROGRESS / NOT_VERIFIED** — 원문/ID/금액이 없는 safe summary·event/group count·비authoritative 상태·입력불변성과 합성10k/100k precompute 비용을 확인한다. 금융/Google/고객 원본 쓰기와 실제 API 조회는 구현자에게 허용하지 않는다. 다음 명령은 완료 알림 후 `git diff -- app/ota_queue_projection.py tests/test_ota_queue_projection.py`다. 운영은 `d230e12`로 유지한다.

## 2026-10-27 전면 리팩토링 명세 작성 이력 (작성 당시 SPEC_ONLY)

사용자 지시에 따라 [아키텍처·UI·데이터·운영 전면 리팩토링 마스터](specs/refactor-master-20261027.md), [917개 추적 파일 경로 인벤토리](specs/refactor-file-inventory-20261027.tsv), [OTA 보류 대기열/성능 계약](specs/ota-review-queue-performance-20261027.md)을 추가했다. 전체 Git 트리 메타데이터와 핵심 코드 횡단 표본 감사에 기반한 **구현 가능한 에이전트 백로그**다. 각 파일 개별 함수의 전수 코드 감사 완료를 뜻하지 않으며, 후속 RF-001 코드/호출 경로·데이터 감사가 우선이다. 이번 PR은 DOCS_ONLY: 런타임 변경·pytest·운영 재배포·실자료 수락은 없다. 문서 작성 시점 이후의 활성 PR 및 운영 릴리스는 매번 최신 재조회하고, 기존 완료 작업을 반복하지 않는다.

## 마지막 확인된 릴리스

운영 코드 SHA는 **`d230e124b27f268de8e8e3812abe53885e5e2212`**다. PR #222 테마 버튼 치수 토큰을 검수·병합·고정 배포했다. 기존 병합 기능도 보존했다. 문서 커밋을 앱 배포 SHA로 표시하지 않는다.

이번 근거: 추적 파일948개 blob 일치, 작업/프로세스 SHA 일치, 단일 loopback listener, health/ready200·보호API401, 2DB/13개 보호 표 내용·스키마 동일. 운영HTML GET200·token44px/8소비/단일버튼 스모크 통과, 사용자 페이지/입력/테마 변경 없음. 실제 환불121묶음·추론2묶음의 보류/환급 미완료 표시 수락은 `bff4ffd` 근거다. 세부 검사·기존 실패·근거 경로는 [운영 기록](operations.md)에 있다. 추가 수집·금융/Google 직접 쓰기 없음.

## 2026-10-28 활성 세션 인수 상태

- **COMPLETE — 여행 탭 지출 복사:** 세션 `af475563`의 사용자 최신 요구는 각 여행별 탭 하단에만 복사 기능 제공이다. 코드 `a3e0316`을 검수하고 `75aa984`에서 공통 TSV 검증·실제 여행 확인·필터 일치·복사 실패 처리를 보완했다. 알 수 없는 증빙을 카드로 바꾸지 않고 잘못된 날짜/금액·중복·보류 건은 제외 수를 알린다. PR #198 병합 및 위 SHA 운영 배포 완료.
- 실제 검사: 복사·수입 브라우저·live-sync 59 passed, 4 subtests passed. 최종 API/공통 TSV/adapter 28 passed. 합성 실제 클립보드의 7열·부호·증빙, 비로그인401·viewer 거부 확인. 전체 회귀는 국소 읽기·클립보드 변경이므로 생략. 운영 DB·Google·원본 쓰기 및 운영 클립보드 변경 없음.
- **COMPLETE — 이전 Cost V35 인계:** 중단 구현은 Trip.com/카카오/Toyoko/여행 감사로 분리 검수·보완해 위 PR과 릴리스에 통합했다. 이전 세션 알림 대기는 종료했으며 임시 workspace 공식 보관을 마쳤다. 개별 실자료 미결은 아래에서 별도 유지한다.
- 배포/보호/브라우저 근거는 `.local-archive/session-review-20261028/` 및 운영 릴리스 감사 JSON에 보존한다. 기존 미추적 파일·stash·다른 worktree는 보존했다.

## 완료한 주요 흐름

| 항목 | 확인된 범위 |
| --- | --- |
| 여행 장부 수입·지출 | Google 수입 읽기 전용, 상단 수입/지출/차액, 표 하단 수입 합계, 중복 지출 헤더 제거. 불일치/미검증 검색에서도 전체/검색 지출을 구별하고 미검증 수입 금액·차액은 숨긴다. |
| 지출 검토 지연조회 | 닫힌 상세는 조회하지 않음. OTA 최상위 검토는 기본 접힘·펼칠 때 조회·닫힌 동안 polling 중단·재펼침 갱신. 운영 초기 API0건·펼침200 확인. |
| 항공권 이름 검색 | 완전 이름 구성요소 검색, 인증된 평탄화 메일 파싱, 메일 전용 색인, 최초 수신일 기준. 실제 대상 예약1건·여정2편 표시 수락. 당일 카드0건은 미결제나 결제 연결 확정이 아니다. |
| 원승인번호 복수 환불 | 1:N 링크·합계·순액 표시, 공백 정규화와 원결제 중복 보호. 실제 확정2건 패널 수락 근거가 있다. 실제 기장/환급 완료와 구분한다. |
| 일반 UI | 사이드바·스크롤·아이콘 수동 테마·항공권 화면·수입 표시의 코드/표적 검증 및 배포 이력이 있다. 실기기·모든 오류 상태의 포괄 수락을 뜻하지 않는다. |
| 문서 정리 | 시작/상태/운영의 역할을 분리하고 상세 명세는 주제별로 통합했다. 과거 결정·테스트·배포 기록은 [보관함](history/README.md)에 보존했다. |

## 남은 확인과 차단

| 항목 | 현재 근거·다음 경계 |
| --- | --- |
| 카카오 미연결 취소11건 | 모두 원승인번호가 없다. 기존 후보/진단 표시는 배포됐지만 자동 금융 연결로 승격하지 않는다. 원결제 대응을 증명하는 카드사/가맹점 근거가 필요하다. |
| PR #193 이후 실제 수락 | [카카오 금액 추론·환불 표시 PR](https://github.com/6Soo/cost/pull/193)은 이제 검수·병합·배포됐다. 원승인 없는 실제11건의 확정 연결/실제 환급 해결을 의미하지 않는다. 추론 표시와 기장 보류를 보존한다. |
| Agoda 미연결 취소3건 | 원승인번호가 없으며 원문 외화 대조 근거도 부족하다. 기존 연결73건과 구별한다. 임의 상쇄·기장 금지. |
| Agoda 20,532 JPY 등 자동 추론 | 기존 자동 추론 게이트가 있다. 특정 사례의 실패 원인·자동 해결 완료는 보관 근거로 확인되지 않았다. 인증·원문 금액/통화·끝자리·기간·전역 유일성·보류/기장 상태를 읽기 전용으로 진단해야 한다. 날짜 창작·수동확인을 자동화 성공으로 보고하지 않는다. |
| 파라타항공 취소·과거 여행 귀속·항목 팝업 | 진단 코드/표시 보완과 개별 실자료 원인 해결을 구별한다. 사례별 최종 수락 근거가 없으면 미확인으로 둔다. 옛 감사표의 미병합 상태는 현재 PR 상태가 아니다. |
| 실제 기기·200%·오류 상태 수락 | 합성 Chromium·DOM 스모크를 실제 기기/본창 확대 전체 수락으로 확대하지 않는다. 필요한 경로만 추가 확인한다. |
| 메일 수집 창 비노출 | 예약 작업 `pythonw.exe` 전환은 확인됐다. 다음 예약 실행의 무창 동작·수집 성공 수락은 **NOT_RUN**이다. 추가 수집을 실행한 것으로 보고하지 않는다. |

## 보존할 로컬 자료

- `apps-script/CloudMail.gs`: 미추적 클라우드 수집 초안. 배포·활성화 완료가 아니다.
- `docs/superpowers/plans/2026-10-26-cost-open-work-plan.md`: 사용자 기존 미추적 계획. 이번 통합의 원본 목록·새 실행 큐에 넣지 않는다.
- `.local-archive/`의 고객 근거·보호 기준선·복구/배포 스크립트와 기존 stash를 보존한다. Git 문서의 숫자만으로 실자료를 변경하지 않는다.

새 작업 인계에는 변경 범위, 완료 커밋, 실행한 표적 검사, 생략한 검사, 실제 배포 SHA 또는 차단 원인, 다음 명령만 갱신한다. 세션별 상태 문서를 새로 늘리지 않는다.

## 2026-10-27 OTA 자동 배정·사후 교정

- 현재 요청: 색 대비 수정과 여행 자동 배정 후 사용자 교정. 취소·해제는 미배정 검토 집계에서 분리하며 전체 목록/별도 필터에 보존한다.
- 구현: 전체 검증 여행으로 준비 숙박을 계산한다. 기간 포함·겹침 일수·차액·시작일·고정 순서로 최선 후보를 `AUTO_INFERRED` 표시하고 근거·확신·준비 숙박 간격을 표시한다. 이용기간 누락·충돌·취소·사용자 해제를 자동 배정하지 않는다. 수동 교정은 별도 근거/기간 밖 확인과 기존 owner·CSRF·revision·기기장 보호를 거친다.
- 검증: OTA 목록/예약 배정/테마/오염 공급자 검사 38개, 인접 우선 배정·예약 분류 8개, 목록 브라우저 2개(390/1440 및 긴 이름) 통과. 브라우저 초기 비동기 적재를 기다리도록 검사 수정. 실제 테마 전환 안내문 대비 4.5:1 이상. 전체 회귀는 단일 OTA 화면·파생 색인 범위이므로 생략했다.
- 운영 실측: 전체 2,271건·자동 추론896건·미배정170건(후보 없음73·기간 없음88·기간 충돌9)·취소/해제 제외974건. 기존 색인 비교에서 준비 숙박45건을 추가 배정하며 기존 기간 충돌9건은 보류한다. 운영 색인 ready, 실제 테마 전환, 수정 화면의 여행62개·현재 선택1개·근거 입력·다른 여행 접힘을 확인했다. 실자료 배정 저장/해제·금융/원본/Google 쓰기·대량 재분류는 실행하지 않았다.
- 완료: 코드 `55f57bb96ba02cea7ab193c03b8449a3cc379e6c`, PR #195 병합/배포 `a56b53da170b8e7ae8bf20f8899199c2b8cf8c18`. 요구사항별 색 대비·자동 배정/집계·사후 교정은 COMPLETE. 근거는 `.local-archive/ota-auto-trip-20261027/`의 `projection.json`, `browser-smoke.json`, `protection-before/after.json`, 배포 스크립트에 보존한다. 다음 명령은 필요 시 `gh pr view 195`와 `aside repl`의 `/ota` 읽기 전용 확인이며 추가 DB 쓰기는 없다. 기존 미추적 파일·별도 PR #193은 포함하지 않았다.
