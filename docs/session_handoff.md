# 2026-11-17 — 수기 장부 전수 재대조·TRIP-099 구현, 운영 반영 미완료

- **현재 승인 범위/상태:** 사용자 재지시 “이행해”에 따른 전체 재대조와 [TRIP-099](policy/trip.md)의 구현·검증을 진행했다. 아래 08:00의 완료는 이전 1건 처리이며 전체 조사 완료를 뜻하지 않는다. 현재 코드 `6d2630a8392126a9de85584759d8a09248bca370`, 독립 `gpt-6.1-sol` medium 정확 SHA APPROVE. 운영은 기존 `9399d8cb`이며 이번 배포·실제 기장 교정·바이너리 전환은 **미실행**이다.
- **실제 조사 근거:** 전체 4,222건(상반기 귀속 4,135·6/30 경계 87), 기장 1,343·미기장 2,879. 현재 상반기 기장 중 수기 장부와 불일치하는 116건(매입 77·환불 39)을 행별로 판정했다. 검증된 하반기 수기 일치·이용기간 근거를 추가 발견하지 못했으며, 실제 하반기 비용이 없다고 확정한 것은 아니다. 비카드 1건은 기존 사용자 원행과 4월 예약 근거를 보존했다. 미기장 하반기 수기 후보 22건·완료 Q1 환불 투영 차이 5건은 별도 관찰로 남겼다.
- **원본 비교 정정:** 카드 원본 7개 해시와 핵심 결제 필드 4,222건 일치. 매입일 156건 차이와 그중 승인번호 F 표기 5건 차이를 별도 기록했다. **비교한 모든 필드가 같은 것은 4,066건**이다. 이전의 4,217건 비교에는 매입일이 없었다. 원문·저장된 날짜·금액·ID를 바꾸지 않았다.
- **검사/사본:** 실 Rust 바이너리 환불 표적 127 PASS, 구형 읽기 스키마·기한 검사 21 PASS. 독립 검수에서 발견한 판정 저장 우회·전액취소 정규화 차단·환불 연결 반복 분석을 실패 재현 후 보완했다. 구매 3건의 사본 교정·3투영 일치·원본/대상 밖/금융 불변·재실행 0 PASS. 사본 7,336건 재판정 Python/Rust 대상 2,152/2,152·목록 밖 차이 0 PASS, 환불 연결 486/486 PASS. 실제 금융 반영 증거를 대신하지 않는다.
- **차단/다음:** 초기 공식 영향 검사(SHA `9185f8cc`)는 Python 1,605 PASS·7 FAIL/32 subtests, Rust fmt/clippy/test PASS. 기준 `origin/main`에서 같은 구형 스키마 1실패를 확인하고 테스트 수정 없이 코드로 해결했다. 나머지 6건은 새 정책과 반대되는 과거 여행 배정을 기대한다. 사용자 “권장안대로 처리해” 승인으로 6개 검사 안에서 합성 카드 승인일·매입일을 여행에 맞추고 예약 연계 모의 자료 및 후속 입력의 날짜를 일치시켰다. 공용 CARD와 기존 assert는 유지했으며 6건 모두 통과했다. 최종 SHA 영향 검사·독립 검수·공식 배포·신선 백업/복원·구매 3건 실제 교정·새 바이너리 경로 전환·서비스 재개·후검증은 아직 남았다. 실패를 검수 승인으로 면제하지 않는다.
- **보호 근거/조율:** `D:/WebLedgerHost/data/backups/full-q12-manual-reconciliation-20261116T230618Z/`의 요약·행별 판정·원본 차이·전수 대조 XLSX 및 `code-repair/` 사본 근거. 정확한 다음 명령과 실행 전 스크립트는 기존 worktree의 `.local-archive/full-q12-checkpoint.md`에 있다. 다른 M5/M6 세션과 운영 보류를 조율했다. 사용자 답변 대기 동안 이번 운영 쓰기 계획이 없어 보류 해제를 통지했으며, 재개 시 운영 SHA와 소유권을 다시 확인한다. 고객 원문 Git/보고서·Google 쓰기 0.

# 2026-11-17 08:00 — 수기 원문 재대조 공통코드·실제 기장 교정 완료

- **승인/결과:** 사용자 “기장도 코드를 변경해서 변경하도록” COMPLETE. 금액과 (날짜 또는 식별력 있는 업체명 일부)가 일치하는 유일한 하반기 수기 원행을 검증하는 공통 경로로 과거 자동 귀속 1건을 교정했다. 거래·장부·보드의 여행·항목·설명을 함께 반영하고 변경 전 값과 감사 이력을 보존했다. 일반 업체명만의 오연결·복수 후보·상반기 원행 중복은 거부하며 실제 수동 교정/P2·중복/환불 보호를 유지한다.
- **코드/검수:** reviewed/deployed `9399d8cb40095b38715bd997f1123dfc6a620620`, PR988 병합 `29354f6abd189d0a999a722de3e68f6fac4f68cd`. 독립 gpt-6.1-sol medium 정확 SHA APPROVE·표적208 PASS, 최종 공식 영향815 passed/skip0/known failure0·compile/costcore build PASS. GitHub 2job은 결제 문제로 시작 전 차단(annotation 확인)으로 지침의 독립 검수+로컬 검사 예외를 적용했다.
- **운영/보호:** 공식 deploy_verified_release.ps1 exit0, Previous fddbb8c6 → actual9399d8cb/backend8752·gateway8790. 추적1904 blob불일치0·보호14표 불변·health/ready200·보호API401·Board/Worker Rust/Rust 정렬·기존 e4e5 바이너리/설정 해시 보존. 별도 관리 프로세스에서 board/core 신선 scoped 백업·복원 검증 → APPLIED1 → REPLAYED 변경0 → 3투영 일치·원문/대상밖/금융/core불변·Python/Rust 재판정대상0·새 이용기간0 확인. 금융 교정 검증/서비스 복구 모두 true, paused=false. 서비스 재개 후 23:00:26Z 읽기전용 재검증도 PASS, 검증 DB쓰기0·Google쓰기0.
- **근거/잔여:** 보호 경로 `D:/WebLedgerHost/data/backups/q12-auto-additions-20261116T181539Z/amount-or-merchant-audit-20261116T222100Z/code-repair/`의 financial-backup-restore/applied/replay/final-validation/maintenance-lifecycle JSON·증거 XLSX. 원문과 행별 금액은 Git 밖에만 보존. 이번 승인 범위의 남은 구현·검사·운영 반영/차단 없음. 운영 소유권 해제 통지 완료, 다음 PreviousSha=9399d8cb(실제값 재확인). 기존 사용자 미커밋 변경 보존. 완료 기록 때문에 문서 전용 PR·재배포하지 않는다.

# 2026-11-17 — M4 UI-0 완전 종료: 수락 검증·간극 종결·병합·운영 배포 완료

- **요청/결과:** “m3닫고 m4도 진행해”의 M4를 닫았다. React 프런트는 이미 main에 있어 화면 재작성이 아니라 **수락 검증 보강·소수 간극 수정**이었고, 13결함 핵심 수락 기준을 시험(브라우저 렌더 포함)으로 검증·간극을 종결·병합·배포했다.
- **병합/배포:** PR983 병합(main merge `aa9c45e1`), reviewed 후보 `fddbb8c6`(M4 본문 4d338374 + main df636b90 M3 clean re-merge). 공식 `deploy_verified_release.ps1 -Apply` exit0, **actual fddbb8c6/backend8751**·gateway8790(continuous code-only, Previous d5b77717). 추적1902 blob불일치0·dist 3파일 해시 일치·보호14표 불변·health/ready200·보호API401·worker 전환·core writers VERIFIED·금융/Google 쓰기0. Rust costcore-e4e5dd67.exe(1224058b…)·links/rust·config 보존. **다음 PreviousSha=fddbb8c6, 소유권 자유·보류 없음.**
- **검수/간극 종결:** 독립 gpt-6.1-sol medium 최종 SHA PASS(findings0). #6 화면별 고유 `<title>`(AppShell document.title MutationObserver, 6화면)·#3 셀 수준 전체값 접근 간극을 **1·2·3차 독립검수 FAIL→genuine 강화로 종결**(시험 약화 아님): overflow-wrap 속성만 보고 인정하지 않고 실제 줄바꿈(white-space)·클리핑·스크롤 공개(셀·중간 조상 hidden 클리핑 부재+컨테이너 실제 overflow)·title 전체 값 포함 시만 인정, 잘림 반례 회귀 5변별. #3 잘림 수정(320px totals 1열). 표적 vitest 23파일141·타입0·build·브라우저16·백엔드26·M3 기준8 통과.
- **검증 구분:** on-disk dist==빌드 해시 일치. 익명 자산 401(인증 활성) — 인증 화면 렌더는 로그인 필요로 미수행, 합성 미리보기 브라우저 수락(16종)과 구분. 고객 원문 Git/보고서 없음(완전 합성 fixture).
- **근거/남은 일:** [운영 기록](operations.md) 맨 위·[계약 지도](design/m4-ui0-contract-map-20261117.md). worktree `.local-archive/m4-ui-deploy-20261117/`(review-evidence·protection-before/after·verify_deploy). **잔여(부가)**: 동적 제목 화면 전체 고유성·모바일 브랜드 중복·화면별 본문 크기·초점 가둠·빈 상태 문장 수·OTA 상세 링크 데이터·P-03 합계/복사/내보내기 서버 대조·P-04 영수증 서버·스크린리더/실기기. 문서 후속 때문에 재배포하지 않는다.
- **교훈:** paseo run 검수 위임은 `--cwd`만으로 워크트리 고정 안 됨(호출자 워크스페이스서 실행 가능) — 셸 directory를 워크트리로 두고 프롬프트에 `cd /d` 명시해야 정확 SHA 검수. staging은 검증된 `stage_release.py` 재사용.


# 2026-11-17 06:00 — 분기 밖 비용의 과거 자동 귀속 3건 운영 교정 완료

- **현재 요청/완료:** 사용자 “ㅇㅇ 찾은것 코드로 교정해”의 좁은 범위 완료. 앞선 Q2 내부77건은 이번 성과에서 제외한다. 명시적 원문 재대조 경로만 사용해 자동3건을 교정했고 owner 최초기장1건은 보존했다. 목적지는 기존 날짜/지역 규칙의 최선 추론이며 실제 숙박일·보험기간을 확정하거나 새로 생성하지 않았다.
- **코드/검사:** 코드 `d5b77717ccfb9d50242b6e29464f8bd59766a71c`, PR984 병합 `9f0cdc3a2d5805f8a0f89d4942269b5abfc54b9f`. 인계된 정확SHA 독립 gpt-6.1-sol medium APPROVE와 공식609건 PASS/skip0/known0·costcore build를 대조했다. GitHub2job은 결제 문제로 시작전 차단(annotation 직접확인). graphify 파일/CLI 없음은 기존 확인 결과를 재사용한다.
- **실제 배포/반영:** 공식 도구 exit0, actual d5b77717/backend8752·gateway8790, Previous e4e5dd67. 추적1890 blob불일치0·코드배포 보호14표 불변·health/ready200·비인증 보호API401. Rust/rust·e4e5 바이너리 및 설정 해시 보존. 이후 별도 hidden 프로세스에서 board/core 신선 백업·복원 검증→exact3 apply→REPLAYED 변경0→3투영 일치·원문/대상밖/금융/core불변을 확인했다. 서비스 재시작 후21:00:20Z 읽기전용 재검증도 PASS, Python/Rust 후속대상0·검증DB쓰기0·Google쓰기0다.
- **실패 구분:** 초기 운영 wrapper의 Worker 파일 동일성 검사와 백업 scope 인자 오류는 실제 쓰기 전 게이트에서 중지됐으며 각각 runtime 복구를 확인했다. 역할별 실행파일 검증과 `--scope board core.sqlite`로 수정해 통과했다. 실패를 성공으로 집계하지 않는다. 보호 호스트의 최종 financial_verified/runtime_restored 모두 true.
- **근거/남은 일:** 보호 `D:/WebLedgerHost/data/backups/q12-auto-additions-20261116T181539Z/q34-leakage/code-repair/`의 financial-backup-restore/applied/replay/final-validation/maintenance-lifecycle JSON과 실제교정 증거 XLSX. source/금융 원문은 Git 밖에만 보존했다. 승인 범위의 남은 구현·검사·운영반영 없음. 운영 소유권 해제 통지 후 다른 세션이 다음 배포를 맡는다. 문서 때문에 재배포하거나 문서전용 PR을 만들지 않는다.
# 2026-11-17 — 분기 밖 비용의 과거 자동 귀속 교정 구현·사본 검증, 운영 반영 준비

- **사용자 승인:** “ㅇㅇ 찾은것 코드로 교정해”. PROC-073에 원문 재대조의 좁은 Q2 자동 귀속 예외를 반영했다. 기존 분기 검수의 미리보기/digest·백업·3투영 원자 교정·감사 원복 도구에 원본 카드 파일 재파싱·원문 해시·이전 귀속·자동 생성 이력을 검증하는 `--source-review` 경로를 추가했다. 일반 P1 조회/재시작에는 연결하지 않았다.
- **반영 대상:** 자동3건238643원은 현행 날짜/지역 규칙과 원문 검토에 따라 0625_아키타→0704_야마가타167223원,0620_묘코→0712_몽골65420원,0501_부산→3분기_기타비용6000원으로 계획했다. 호텔은 같은호텔6월예약과 정확금액/결제관계가미일치, 보험은실제가입기간자료없음이므로 최선추론과불확실성을명시하고 이용기간은생성하지않는다.
- **보호 제외:** 377604원은 최초actorowner·confirmed_byowner의 실제기장이어서자동으로승격하지않고보존한다. 이후취소된10월예약을실제숙박으로만들거나환불메일을음수카드원행으로만들지않는다. 취소자동예약의공통분기종결경로도원문두종·같은예약참조와보호조건을통과할때만지원한다.
- **완료/남은 일:** 표적202건PASS·실제보호사본3건적용/3투영일치/원문·대상밖·금융불변/재실행0/owner1건제외PASS. graphify파일없음·CLI미설치로update불가(실제명령실패기록). 아직운영쓰기0. 보호근거 `D:/WebLedgerHost/data/backups/q12-auto-additions-20261116T181539Z/q34-leakage/code-repair/`. 정확SHA독립검수·공식영향검사·PR병합·공식배포·신선백업/복원·기존도구실제반영·Rust재실행보존검증이남았다. 운영조율통지했고UI세션쓰기보류확인. Rust/rust·현재e4e5바이너리·설정·고객원본·Google쓰기금지보호를유지한다.

# 2026-11-17 05:17 — 사용자 범위 정정: 3·4분기 비용의 1·2분기 추가 기장 조사

- **정정:** 사용자가 원한 것은 수기 장부에 추가된3·4분기 비용의1·2분기 오귀속이다. 앞선77건은 주로2분기 내부 귀속 교정이므로 이 요청의 성과에서 제외한다. 아래04:42절은 실행 이력이며 현재 요청의 완료 선언이 아니다. 당시 미기장4건도 이미추가기장된사례와 구분한다. 기존77건을 근거없이 자동 되돌리지 않는다.
- **재대조 결과:** 양수 기장1292행(0630경계 포함), distinct예약근거12211개와 보존메일10157개를 읽기전용 조사했다. 4분기 이용원문1건377604원은 현재0616_레분토&리시리, 실제10/15~16/1015_오제 예약이며 수기Q1/Q2 동일금액행 없음. 다만9/24취소 및 전액환불 안내가 있어 순비용미확정, 최초actorowner라 자동신규 생성도 미입증이다. 자동신규가확인된7월결제3건238643원(호텔167223·보험65420·경찰공제회6000)은 실제이용분기미확정 후보다. 호텔에는6/28~29숙박원문도 있어 결제일만으로3분기로단정하지않는다. 보험결제메일은 승인번호까지대조했지만이용기간근거없음.
- **제외/상태:** 수기원장에이미있는AGODA72894원과0630경계63행은추가오류집계에서제외·별도보존. 보호 `D:/WebLedgerHost/data/backups/q12-auto-additions-20261116T181539Z/q34-leakage/`의 REPORT.md·targeted-summary.json·재조사엑셀·원문증거에 저장했다. 이번 재조사 운영/Google쓰기0·추가코드수정0. 이용분기미확정3건과취소거래의순비용을확정하거나전체회계교정을완료했다고보고하지않는다. 현재범위추가교정의안전근거는아직충분하지않다.

# 2026-11-17 04:42 — 원행 대조·공통 코드 수정·81건 운영 반영 완료（이전 실행 범위 기록）

- **현재 요청:** 사용자 지시 “행 원본 자료 대조해서 직접 확인하고 코드수정”에 따라 이전 읽기 전용 조사에서 구현·운영 교정으로 진행했다. 카드 원본 업로드4개를 재파싱해81행을 대조하고, Google 실제 원장77행을 직접 확인했다. 고객 원문은 보호 호스트에만 보존했다.
- **구현/검사 완료:** 구형I열·표준H열·유럽G열 원행 판독, 원본 지문과 일대일 대응에 근거한 수기 원장 귀속 판정, Python/Rust 공통 planner와 거래·장부·보드의 일관된 교정을 구현했다. GGL-045에 사용자 결정을 반영했다. 정확코드 `e4e5dd67c72ee3b9aa3201167b797010cbb97997` 공식 영향974건·skip0/known0, Rust fmt/clippy/workspace tests/release build PASS. 독립 gpt-6.1-sol medium 정확 SHA APPROVE, CI 시작 전 결제 한도 차단 확인 후 PR982 병합 `a88776e6`.
- **운영 완료분:** 공식 배포 exit0, actual e4e5dd67/backend8751/gateway8790. 신선4DB 백업·복원과 배포후 board/core 백업·복원을 통과한 뒤 독립 검수된 스크립트로77건·7,813,974원 귀속 교정 완료. 거래·장부·보드 일치, 원본·수동·환불·대상 밖 상태 불변, 재계획0건. `costcore_bin`만 새 e4e5 바이너리로 전환했고 Rust/rust 및 기존888 바이너리와 나머지 설정을 보존했다.
- **신규 기장/완료:** 예약 원문 이용기간에 따라4건·2,518,357원을 기존 worker가 실제 기장했다(recorded4/failures0/pending0). 오제2건2,077,580원·야마가타145,436원·다테시나295,341원이며 ledger/board 각각 정확1회다. 04:42KST 최종 읽기 전용 검증 PASS:81건 귀속·이용기간·원문 지문 일치, 원본/대상밖 보호 해시 불변,77건 재계획0·검증 DB변경0·Google 쓰기0. 보호 근거 `D:/WebLedgerHost/data/backups/q12-auto-additions-20261116T181539Z/source-recheck/`의 `final-validation.json`, `FINAL-EVIDENCE.md`, `행원본대조_코드교정_운영반영증거.xlsx`에 저장했다. 승인된 요청의 남은 구현·검사·운영 반영 없음. 문서 후속 때문에 재배포하지 않는다.

# 2026-11-17 — M3 완전 종료: 추출기 기준 출력 생산·검증 완료

- **요청/결과:** “m3닫고 m4도 진행해”의 M3 마지막 산출물(설계 §3.4 **facts 기준 출력**)을 생산·검증해 **M3를 닫았다**. 판정(1차)·연결(2차) 운영 전환은 이미 완료·검증됐고(C1~C3·첫 창 OTA 7,965/7,965·환불 486/486 PASS), 남은 기준 출력을 보존 원본에 대해 생산했다.
- **생산(검증됨):** origin/main `750e4a65aea5f5603fc04199046d5e64e8a7e45c`(PR980) detached worktree `C:/AX/cost-m3-baseline`에서 `python -I tools/core_bridge/cli.py extract-baseline` 실행. `ok=true`, **events 7,965건**, **baseline sha256 `a26d446510faabe4cbdfd5d8cf114b0903e6b87b8453fdb3380d529e605cbaf6`**, input_digest `1e9613eb…`, events.json 28,637,104B·stderr 0B. 디스크 해시==보고 해시·건수 일치 독립 검증.
- **보호/원본:** 고객 기준 출력은 보호 경로 `D:/WebLedgerHost/data/backups/extractor-baseline-main-20261117/events.json`에만. 입력은 라이브 아닌 완전 스냅샷 사본(1.76GB)이며 라이브 OTA evidence DB는 같은 크기·2026-11-15 23:20 불변 → 스냅샷==보존 원본, 운영 무접근 읽기 전용. `app/ota_payments.py`는 root/main/worktree 바이트 동일·의존 16모듈 PR980 변경 9파일 밖 → canonical. Git에는 명령·SHA·건수·해시만(고객 원문 없음).
- **검사/커밋:** 표적 `tests/test_core_bridge_extract_baseline.py` 8 passed. 도구 4파일(cli·commands·extract_baseline·test)+기록을 main 기반 브랜치에 커밋. [생산 기록](agents/artifacts/m3-extractor-baseline-20261117.md).
- **M6 인수/남은 일:** 이 고정값(7,965·`a26d4465…`·python_sha `750e4a65`)이 **M6 Rust 추출기 병합 수락 기준표**. 매일 Python 대조는 M3 완료 조건이 아니라 M6까지 회귀 안전망이며 주기 축소는 소유자 정책 결정 전 유지. 병합·운영 배포는 별도 게이트(이 생산은 읽기 전용이라 운영 반영 불필요). M4는 React 프런트가 이미 main에 존재해 UI-0 계약·기능 지도·수락 갭 평가와 검증 테스트를 완료했으며(별도 worktree `cost-m4-ui0`, 121 tests), 남은 렌더 검증·간극 2건(#10 서버 404·#12 용어집)을 이어간다.

# 2026-11-17 — 1·2분기 P1/P2 자동 추가 조사 완료（읽기 전용·이전 요청 기록）

- **현재 요청:** 사용자가 수기로 적은1·2분기 Google 장부를 높은 신뢰도의 기준으로 두고, P1/P2가 추가한 자료를 찾았다. 수정·재분류·금융 반영·Google 쓰기는 하지 않았다. 기존 항공료 배포는 PR980/merge750e4a65로 완료된 과거 작업이며 재실행하지 않는다.
- **결과:** 0630 이전 여행과1·2분기 기타비용에서 자동 생성 이력이 명확한 실제 기장836건(1분기 음수 환불9건,2분기827건)을 확인했다. 수동교정107건을 보호하고 나머지729건을 수기 원본과 대조했다. 그중77건·7813974원(순액)은 날짜·금액·지급처·발급사와 유일한 원행이 일치하면서 Google 수기 원장과 P1 귀속이 달랐다. 전체836건을 오류로 단정하지 않았다. 초기owner표시416행도 실제 사용자 입력으로 단정하지 않고 별도 보존했다.
- **몽골과 같은 사례:** 1분기 자동귀속이 남았지만 원문 이용기간은7·8월인 미기장4건·2518357원을 확인했다. 결제일/금액·예약 메일 본문을 직접 대조했고 ledger/board0건·원승인 환불 원행0·원본 충돌/중복/실제 수동결정 없음이다. 0630오제2건2077580원,0704야마가타145436원,0806다테시나295341원. 아직 기장하거나 이동하지 않았다.
- **범위/검증:** 6/30출발 오제는 열린 분기 경계로 별도 집계했다(자동 생성 후 수동교정2건, 기존행P2교정14건). 이를 새 P2기장14건으로 세지 않았다. 구형1분기 원본I열·표준H열·유럽G열을 직접 읽어 수집기0행을 원본0행으로 오인하지 않았다. 상세836행·불일치77행·미기장4행 및전체미기장2883행을 포함한9시트 엑셀을 재개봉 검증했다. 코드 변경0으로 테스트/빌드/배포는 하지 않았다.
- **산출물/남은 일:** 보호 경로 `D:/WebLedgerHost/data/backups/q12-auto-additions-20261116T181539Z/REPORT.md`, `1_2분기_P1_P2_자동추가_조사.xlsx`, `summary.json`, 원문 사본·근거를 보존했다. 이번 요청인 식별·근거 확인·결과 정리는 완료다. 새로 발견한 거래의 실제 교정/기장은 이번 읽기 전용 조사에서 실행하지 않았다. 신규 문서 PR·재배포 없이 조사 상태만 기록한다.

# 2026-11-17 03:05 — Plush UI 전수 감사 수정 운영 배포 완료

- **실제 결과:** Plush UI/UX 전수 감사 수정 13건(아이콘·팝오버·모바일 터치 레이아웃·홈 카드 grid)+경로 변경 팝오버 닫힘 회귀 테스트를 운영 배포했다. 공식 도구 exit0, actual `4cd76d2b05231f1197fbe5c94ffa99ffea1081b6`/backend8752·gateway8790, Previous9af. 추적1885 blob불일치0·보호14표 불변·health/ready200·비인증 API401. 금융 apply·마이그레이션·Google 쓰기 없음.
- **후보/검수:** UI(`b7308aee`→`fe773fe8`)+정책문서 `90da8c42`+PR980 main clean merge `4cd76d2b`. 독립 gpt-6.1-sol medium 정확 SHA PASS(MEDIUM0·LOW 비차단 문구1). 후보 HEAD typecheck·build·vitest 17파일88·영향 Plush Python45 통과. PR980 소득표시/원문기장경로 보존. PR979 병합 `10b2a39d`(main 트리=배포 후보 트리).
- **정책:** 소유자 결정 "혼자 개발·관리 레포는 검수 PASS 후 언제나 운영 배포"를 `AGENTS.md`에 명시(`90da8c42`). 회계감사 후임 Accounts AGY(`20acee6b`) 기장 완료·소유권 해제 후 배포했다.
- **다음/한계:** 인증 화면 렌더링은 로그인 필요로 미수행(익명 거부401 확인, 감사 당시 로컬 합성 프리뷰 렌더링과 구분). 문서 때문에 재배포하지 않는다. 이후 PreviousSha는 다른 배포가 없으면 `4cd76d2b`. 근거 `.local-archive/plush-ui-audit-20261116/deploy-4cd76d2b/`·`releases/deploy-evidence-4cd76d2b….json`. [운영 기록](operations.md).

# 2026-11-17 02:31 — 몽골 항공료 실제 기장·Google 수입 표시 완료

- **실제 결과:** 운영 worker가 항공료8건·6,500,202원을 표준 경로로 기장했다. 각 ledger/board 정확1회·귀속/이용기간/원문 해시 일치. 유효 몽골 보드는 **14건·6,767,151원**이다. 원문·금액·날짜·ID·수동 교정·대상 밖 금융/core 결정·나머지 보호표 불변. 같은8건 큐 재처리 후 모든 보호 금융표와 core 전체 상태 동일, pending0·recorded8/failures0.
- **수입:** 인증 브라우저에서 **14행(금액13+합계빈1), 표시합17,337,200원**과 미확인1·잠정 안내를 확인했다. 390/1440px 가로넘침0. 원장 빈 합계를 수정하지 않았으므로 수입·차액10,570,049원은 잠정값이다. Google 최종 장부 쓰기0.
- **운영/검사:** 공식배포 exit0, actual9af204148b1b6450f7bb9c6ec1185c5f2f3aa852/8751, Previous8888230d. 1883파일 blob불일치0·코드배포 보호14표 불변·health/ready200·보호API401. Rust/rust·기존888bin·설정 해시 보존. 신선4DB 백업복원 후 배포했고 프로세스 임대 기록 변경을 설치 게이트가 감지하자 postdeploy board/core 백업복원도 다시 통과한 뒤 보호원문 설치·기존 큐만 등록했다. 직접 금융 SQL은 사용하지 않았다.
- **검수/다음:** 정확코드9af 공식1101+30subtests/skip0·관련합성21·frontend79/type/build PASS. 독립 gpt-6.1-sol medium 코드9af/docs-only46cbed24와 설치 스크립트 APPROVE. 최종 PR SHA 판정은 PR980에 기록한다. 실제 기장·표시·배포·재처리 검증은 완료했으며 PR980 검수/병합과 소유권 해제 통지를 마무리한다. 문서 때문에 재배포하지 않는다. 기존 라쿠텐/어드벤처 수동 보드 교정에 따른 raw ledger16건7793532원과 유효보드14건은 구분해 보존했다. [상세 근거](agents/artifacts/reviewed-booking-income-20261117.md).

# 2026-11-17 — cgpflix232 계정으로 작업 인계

- 사용자 지시에 따라 진행 과정을 저장하고 Accounts AGY의 cgpflix232 계정으로 원래 작업 전체를 이어간다. 코드 후보 `9af204148b1b6450f7bb9c6ec1185c5f2f3aa852`, PR980(draft/pushed), 독립 gpt-6.1-sol medium APPROVE, 표적21건·frontend79건·타입·빌드 PASS。9af 공식 영향 검사1101건+30subtests PASS/skip0를 마지막에 회수했다. 신선4DB 백업/복원은 아직 결과 회수 전이다. 앞선 f547 검사 결과를 최종SHA 근거로 대신 쓰지 않는다.
- **운영 미완료:** actual8888230d/rust writer/rust links/기존bin을 유지한다. 이번 변경 배포·검수원문 설치·8건 기장 등록은 아직 실행하지 않았다. 보호 사본에서만 항공료8건6500202원 신규 기장→유효board14건6767151원 예행을 확인했다. 실제 수입은 숫자13행+빈합계1행=14행,17337200원 잠정 합계다.
- 전체 실행 기록·중복 실행 방지 PID·검수 결과·정확한 다음 명령·원본 경로·보호 경계는 해당 작업공간의 Git 제외 파일 `.local-archive/accounting-deploy-20261116/HANDOFF-CGPFLIX232.md`와 `checkpoint.md`에 보존했다. 기존 root/다른 세션 변경은 보존했다. 이 절은 저장·인계 상태이며 금융 반영 완료 선언이 아니다.

# 2026-11-17 — 몽골 실제 기장·수입 표시 보완 진행

- 앞선 운영 코드 배포는 금융 반영 완료가 아니었다. 원문 조사에서 확인한 몽골 항공료 8건은 운영 ledger/board에 없었다. 공급자 파서 밖의 보관 원문 검수 결과를 원본 SHA·카드 원천 해시·날짜/금액 다중집합·실제 여행기간으로 검증해 기존 미기장 복구와 표준 기장 worker에 전달하도록 보완했다. [절차](playbooks/reviewed-bookings.md).
- 운영 보호 사본에서 현재 Rust 바이너리로 8건·6,500,202원 신규 기장과 board 14건·6,767,151원, 카드 원문·금액·날짜 불변을 확인했다. 실제 운영 반영은 아직 하지 않았으며 신선 백업·복원과 독립 검수·공식 배포 뒤에 진행한다.
- Plush 수입은 내부 board 행만 읽어 Google 원장 13행을 누락했다. 기존 canonical source·여행 연결·열람 grant를 적용해 읽기 전용 projection으로 연결했다. 합계가 빈 행은 미확인으로 표시하고 수입·차액은 대사가 끝나기 전 잠정 금액임을 알린다. Google 원장은 수정하지 않는다.

# 2026-11-17 — 회계 대사 코드 운영 배포 완료

- **운영 반영 상태:** `50823317` 회계 대사·예약 복구·메일 범위·수입 구성요소 검증을 최신 main과 통합한 `8888230deb1a5bd09d826da7e66034e2091ba0a1`을 공식 배포했다. 이전 실제 SHA `41d8e8efde542b9611a1f8a83eea3861bcfaaa4e` → backend8752, 도구 exit0. 보호14표 불변·1876파일 blob불일치0·runtime SHA 일치·health/ready200·비인증 보호API401을 확인했다.
- **실행 원칙:** 구현사항은 표적 검사·영향 검사·독립 검수와 데이터 보호 게이트를 통과한 뒤, 승인된 `tools/deploy_verified_release.ps1` 절차로 운영 반영한다. 배포 전후 실제 SHA·보호 테이블·health/ready·비인가 경로를 확인하고, 금융 원본·Google 장부 쓰기는 별도 승인 없이는 실행하지 않는다.
- **검증/커밋:** `50823317` 구현, `fa2c2962` 영향 매핑, `8888230d` Rust 포맷 보완. 최종 공식 영향 Python1015+2subtests/Rust191·fmt/clippy/release build, 프런트78·타입·빌드 통과(skip0/known0). 독립 gpt-6.1-sol medium이 정확 배포 SHA를 APPROVE했다. CI 두 job은 해당 SHA의 결제 한도로 시작 전 차단됨을 annotation으로 확인했다. 기존 기준선 비교2건은 main과 동일 실패로 구분했으며 테스트를 완화하지 않았다.
- **데이터/완료:** 금융 apply·스키마 변경·Google 쓰기 없음. 읽기 전용 대사 database_changes=0. 코드 배포 시 card-flow.json 해시와 기존 바이너리 경로를 보존한 뒤 Rust 감독 `4dedee2e`에게 배포 소유권을 넘겼다. 감독이 같은 SHA의 `costcore-8888230d.exe`로 전환했고 Board/Worker 모두 rust writer/rust links·health/ready200을 재확인했다. 새 planner의 전환 후 대조는 원문7336건·Python/Rust대상4/4·목록밖차이0·PASS다. 연결 첫 창도 OTA7965/7965·환불486/486·목록밖차이0·PASS를 확인했고 감독이 소유권을 해제했다. 이번 회계 코드 운영 활성화와 검증은 완료다. 이후 배포는 두 Rust flags와 새 바이너리 경로를 보존한다. PR978에 코드·배포 결과를 함께 기록하며 문서 때문에 재배포하지 않는다. [검증 기록](agents/artifacts/accounting-release-20261117.md).

## 2026-11-17 00:26 — Rust 2차 연결 운영 전환·첫 창 대조 완료

- **요청/결과:** “전환 수행해”, “모두 진행해”의 남은 2차 전환 COMPLETE. 운영 코드 `8888230deb1a5bd09d826da7e66034e2091ba0a1`에서 Board·Worker 모두 `classification_writer=rust`, `links_producer=rust`를 적용했다. 회계 대사 수정까지 포함한 같은 SHA에서 빌드한 `D:/WebLedgerHost/bin/costcore/costcore-8888230d.exe`를 사용한다(SHA-256 `98433d9144447f4f153d86d73c1166c09fc5f4b1b02caa53487b36d121f76ca4`). 코드 공식 배포는 회계 감독이 수행했고, 이 세션은 게이트 검증과 스위치 전환을 맡았다.
- **실제 검증:** 전환 전 최종 C1 판정·연결 PASS, C2 185사례에서 Python plan+Rust 연결 및 Rust plan+Rust 연결 모두 Python 기준과 차이 0. C3 4DB 신선 백업·복원과 Python→Rust→Python 왕복의 연결 해시 동일 PASS. 전환 후 새 사본의 첫 창도 분류 7,336행·OTA 7,965/7,965·환불 연결 486/486, 두 그림자 exit0/PASS·목록 밖 차이 0. 두 역할 적용 기록·살아 있는 PID·릴리스 확인, health/ready 200·보호 API 401.
- **과거 차이/복구:** 과거 OTA 1,648건은 `individual_payment_evidence=false`가 빠진 수정 전 바이너리의 측정분이었다. `e2a43e10`의 원본 필드 덮어쓰기 보존이 이미 반영돼 새 패치는 하지 않았다. ExaOne low 작업자 조사·합성 검사를 재사용했다. 첫 관리 재시작은 종료 중 CIM 명령행이 null인 경합으로 실패해 원설정·Python 연결로 복구했고, 종료 확인 보완 후 같은 게이트로 재시도해 성공했다.
- **근거/경계:** `D:/WebLedgerHost/data/backups/links-rust-20261116/`의 `final-links.out.json`, `final-classification.out.json`, `final-fa2/c2-final.json`, `final-fa2/c3-final.json`, `switch-evidence.json`, `switch-first-failed.json`, `first-window/evidence.json`. `final-fa2/`는 보관 폴더명이며 그 안의 C2·C3 최종 결과는 내부 release_sha가 `8888230d`다. 백업 근거는 `c3-links-rust-20261116.json`. 추가 운영 스크립트는 독립 gpt-6.1-sol medium APPROVE. 고객 원문은 보호 호스트 경로에만 보관했고 config 변경은 `costcore_bin`·`links_producer` 두 키뿐이다. 금융 apply·Google 장부 직접 쓰기는 실행하지 않았다. 이번 승인 범위의 남은 전환·검사·차단은 없으며 배포 소유권을 해제했다.


## 2026-11-16 — Rust 미결 구현·합성 검사 완료

- **요청/범위:** “rust관령 미결작업 exaone 다수에게 위임하여 구현”. SPEC M3 / `design/m3-core.md` U12~14를 기준으로 완료된 과제를 재구현하지 않았다. 별도 `integration/rust-exaone-20261116`에서 최신 main `ee118935`를 보존했고 원래 root 사용자 변경·UI 라우팅·운영 서비스는 수정하지 않았다.
- **위임:** `opencode/exaone/k-exaone_v2.5` 3명, build/medium(high 조사 반복 후 조정), 합성 자료만 사용. 사전검사와 기준선 결함 수정은 작업자 완료물을 통합했다. 환불 작업자는 초안을 작성했으나 컴파일/검증이 지연되어 쓰기 소유권을 회수하고 감독이 완성했다. 중복 위임·유료 모델 전환은 없었다.
- **환불 배선:** 감독 Python `a55de0c6` + Rust CLI `056253df`. 실제 `apply_pairs`·`check_groups`·`scope_group`·비공개 `issue_group`을 소비한다. 금액/ID/원문은 응답 수정 대상이 아니며, 기존 Python 트랜잭션에서 묶음의 최종 권한 상실은 전부 롤백한다. 실바이너리 기존 골든53+게시/멱등/권한상실3 = **56 passed**, CLI4/core1 passed. Python 환불·기존 검사25 passed.
- **사전검사:** ExaOne `31feca83` → 통합 `a360f055`, 감독 경계 보완 `c391d415`. 표적25 passed/skip0. 실제 합성 fixture의 WAL 거부를 확인하고 원본 보존 후 별도 DELETE-mode 사본에서 최종 바이너리 READY(환불1=1·OTA1=1, 입력/설정 불변)를 확인했다. 운영 승인·실자료 비교·백업/복원 증거를 대신하지 않는다.
- **Python 기준선:** ExaOne `60492d7d` → `437125da`. Rust 부모 설정 상속으로 Python 기준까지 Rust를 호출하던 결함을 child 환경 고정으로 수정했다. 감독 실제 회귀1 passed, 작업자 shadow CLI8/fmt/clippy 통과. 부모 환경은 바꾸지 않는다.
- **OTA:** 기존 `e2a43e10`·`f5c91d95`가 과거 1,648건 측정 뒤 main에 반영된 사실을 확인했다. 감독 Rust 골든7 passed, 작업자 합성 differential9/9. 새 OTA 계산 코드 변경 없이 검증했으며 **실자료 1,648건의 최신 재측정은 미완**이다.
- **최종 검사 중 발견/보완:** 공식 영향 검사에서 기존 `manual_rows`의 row_id-only 구형 스키마 계약 2실패가 나왔다. origin/main과 성능 이전 코드에도 동일한 문제가 있어 성능 회귀가 아님을 확인했다. 담당과 소유권을 조정해 `8fbf60f0`로 원행 ID만 읽도록 보완했고, 새 red→기존 포함8 passed. 기존 테스트를 완화하지 않았다. 공식 재검사는 Python923/Rust191 passed·skip0/known0, build/fmt/clippy exit0. 독립 sol medium 코드 검수 APPROVE·표적42 passed. 최신 UI main 통합 뒤 실제 환불/Plush 교차 검사97 passed. [검증 근거](agents/artifacts/rust-exaone-validation-20261116.md)에 SHA와 한계를 기록했다. 최종 SHA 검수 판정은 동일 PR에 남긴다.
- **운영/남은 일:** Rust 전환·배포 없음. 다른 세션이 UI 기존 URL 연결/배포를 맡으며 현재 전달받은 운영 SHA는 `c77eaa2bcfd04d8a553122330ebbda914a78cef0`. UI main `d088e1cb`를 통합 `ddc22536`에 보존했다. 코드·합성 검증은 완료했고 PR 최종 검수/병합을 진행한다. C1/C2/승인①②·운영 전환은 별도 미완이다. graphify update는 CLI 미설치로 실행 불가했다.

# 2026-11-16 — 전체 회계 대사 경로 보강·전수 감사 도구

- **요청/범위:** 0712 몽골 누락을 계기로 전체 원문·기장·보드의 회계 불일치를 찾고, 같은 원인이 재발하지 않도록 코드·규칙을 보강했다. 운영 DB·Google 장부·고객 원문은 쓰지 않았다.
- **구현:** 완료 기간의 미기장 거래는 원문 해시와 실제 예약 이용기간이 일치하는 정식 예약 근거가 있을 때만 열린 여행으로 복구하도록 Python/Rust 판정 경로를 맞췄다. 전달 메일·소유자 증거 라벨의 과거 수집 범위를 보강했고, Google 수입 행의 예약금·잔금·추가금 구성요소 불일치를 합계 미검증으로 표시한다. `app/accounting_audit.py`와 `tools/audit_accounting_consistency.py`로 수동 교정 포함 원문·ledger·board 대사를 읽기 전용으로 수행하며 장부·보드 귀속 분리와 누락 원문 식별자도 보고한다.
- **커밋:** `50823317` (`fix: reconcile unrecorded bookings and audit projections`).
- **검사:** 신규·직접 영향 Python 24건 통과, Rust `plan_judgement` 5건 통과, 운영 `D:/WebLedgerHost/data/board.sqlite` 읽기 전용 대사 `database_changes=0`. 대사 집계는 원문 7,336건·기장 3,359건·보드 3,359건, 미기장 3,678건(완료기간 3,653·열린 기간 25), 귀속 차이 694건, 환불 원문 확인 필요 109건이다. 완료기간 미기장 대부분은 과거 보호 경계에 속하므로 자동 기장하지 않았다.
- **검증 한계:** 기존 `webapp/tests/test_automatic_plan_refactor.py`의 합성 기준선 비교 2건은 현재 HEAD에 이미 존재한 예약근거 동작 차이로 실패했으며 이번 변경의 완료기간 복구 분기와 무관하다. 운영 재배포·금융 반영·Google 쓰기는 실행하지 않았다.
- **다음 작업:** 운영 반영 전 독립 검수와 승인된 배포 절차를 거친다. 재개 시 이 커밋의 표적 검사와 읽기 전용 대사를 먼저 재실행한다.

# 현재 상태

# 현재 상태

## 2026-11-16 — Plush UI 운영 배포 완료

- **현재 승인:** “모든 작업 재개하고 운영배포까지해”. [설계](design/m4-plush-ui-20261116.md)와 [실행 계약](agents/artifacts/plush-ui-implementation-contract-20261116.md)을 실행했다. 작업 폴더는 지정 `plush-ui-integration-20261116`, PR971이다. 원본 폴더의 사용자·성능 작업과 별도 Rust 후속을 혼합하지 않는다.
- **코드:** `a92c0b8773971d9abb71db131e070e46482c1f4f`. 전체 Plush 셸·여행/장부·거래·영수증·관리/보조를 실제 인증 API에 연결했다. Google·계정·규칙·항공권·참가자/예약·내보내기의 실제 계약/상태 오류와 누락을 보완했다. OTA 예약 교정·환불 원문·참가자 추가 교정은 명시한 기존 인증 업무 화면 접근을 보존하며 React 편집으로 새로 이식했다고 주장하지 않는다.
- **검사:** 전체 프런트72건/13파일·타입·빌드 통과. 마지막 영향45건, 그 전173건/565건+26subtests/778건+35subtests 모두 실패0/skip0/exit0. 이전 broad의 간헐 실패1건과 현재/main 재실행은 [검증 기록](agents/artifacts/plush-ui-validation-20261116.md)에 별도 보존했다. 독립 sol medium의 발견 사항을 수정하고 정확 배포 SHA 승인 후 전환했다.
- **브라우저:** 합성 영수증 복귀/응답 유실/충돌/원자 반영·PDF/키보드/모션 감소/320~1440px, 실제 XLSX ZIP 다운로드, 계정 승인→연결→해지 오류0, 마지막 참가자/예약/항공권390/1440px 넘침0 확인. 기존공간53이 닫혀 Task54를 사용했고 사용자 공간44는 보존했다. 실제 기기·스크린리더·실사용 paint 성능은 한계를 구분한다.
- **운영 완료:** 독립 `gpt-6.1-sol medium`이 정확 SHA `eacc3bc73104425202cfeece0ec52e6b4e1b7aa8`를 APPROVE했다. 공식 `deploy_verified_release.ps1` exit0, `1f436426`→`eacc3bc7`, backend8752·runtime SHA 검증, 1858파일 blob 불일치0·보호14표 불변·health/ready200·비인증 API401. 로그인 운영 UI/영수증/Google/계정 화면은 오류·넘침0, bootstrap/글꼴200. JS·CSS·HTML3개 모두 운영 응답과 릴리스 SHA-256 일치. 비로그인 curl은 `/ui/`·bootstrap401, Python urllib은 edge403으로 구분했다. 고객 값·운영 화면 캡처·금융 apply 없음. [운영 기록](operations.md)과 [검증 기록](agents/artifacts/plush-ui-validation-20261116.md)에 근거를 남겼다.
- **통합/남은 일:** 기능·운영 요청 COMPLETE, 별도 구현 차단 없음. 배포 결과 문서만 같은 PR971에서 독립 검수·병합한다. 문서만을 위한 재배포는 하지 않는다. 별도 Rust 작업은 포함하지 않았으며 다음 배포 PreviousSha는 다른 전환이 없으면 `eacc3bc7`이다.
- **보호/복구:** 고객 원문·수동 교정·Google 자동 쓰기 금지 유지, 실제 금융 apply 미실행. `.agents/plush-integration-checkpoint.json`과 단계별 `quality-*` 근거 보존. graph.json/CLI가 없어 graphify update는 명령 미발견으로 실패했다.

## 2026-11-16 21:05 — 영수증 기본 Terra high·선택 모델 동적 표시 운영 완료

- **최신 요청:** Claude 대신 `codex/gpt-6.1-terra` high를 기본으로 하고 선택 모델을 UI에 동적으로 표시한다. catalog의 기본값·모델별 실제 추론 수준으로 초기 선택과 버튼/상태를 표시하며, 기존 작업은 저장된 provider/model/thinking을 보존한다. 목록 로딩 경쟁·새로고침은 분석을 자동 실행하지 않는다.
- **실제 판독:** 합성 사진으로 Terra high start→스키마 검증 완료→새 bridge에서 동일 handle 복구→archive 성공, tool event 0, 금융 apply 없음. Claude 로그인 차단은 새 기본 경로의 차단 사유가 아니다. 근거 `.local-archive/receipt-terra-20261116/live-summary.json`.
- **실행 보호:** 일반 Codex 설정을 바꾸지 않는 영수증 전용 Paseo alias와 로컬 launcher를 추가했다. 구독 인증·OpenAI provider를 강제하고 파일/셸/웹/MCP/플러그인/다중 에이전트 도구를 끈다. native config/read 예행에서 기존 MCP 항목이 실제 비활성화됨을 확인했다. 단순 read-only를 도구 차단으로 취급하지 않는다.
- **실행 결함 수정:** SDK의 workspaceId는 기존 작업공간 참조이므로, 임의 ID를 만들던 대신 daemon이 반환한 작업공간 ID와 경로를 검증해 보존한다. 기존 불확실 실행은 재전송하지 않는다. SDK config의 options 필드로 native 제약을 전달한다.
- **완료 코드/검사:** `7ee0b311`·`1f43642605e72794452b71e38337829a9983c202`, PR [#973](https://github.com/6Soo/cost/pull/973)(병합 `dd1d005d`). 표적 **51 passed**, 기준 영향 **524 passed +26 subtests**, 최종 보완분 영향 **83 passed**, 모두 실패0/skip0. Rust costcore release build 통과. 최종 SHA 독립 `gpt-6.1-sol medium` APPROVED, 독립 회귀3건 통과. GitHub 두 job은 결제 한도로 시작 전에 실패했으며 실제 검사 실패를 우회한 것이 아니다. 검사는 중복 합산하지 않는다.
- **운영:** 공식 배포 exit0, `11267cd0`→`1f436426`, Board8751·Worker·core writers 전환 확인. 릴리스1,767파일 blob불일치0, 보호14표 불변, 금융 apply 없음. 추가 점검 health200(0.073초)·ready200(0.006초), 비인증 영수증3경로401. 운영 릴리스의 catalog에서 Codex/Terra/high/selectable=true와 동적 UI 소스를 확인했다. 스키마·고객 자료 변경 없는 코드 배포여서 full-backup 옵션은 사용하지 않았다.
- **마무리/범위:** 이번 요청은 COMPLETE이며 남은 차단 없음. 실제 로그인된 브라우저 재검수는 사용자 제어 TaskSpace44를 보존해 미실행했으며, 동적 선택·이력·새로고침은 합성 JS 실행으로 검증했다. React 화면 변경은 별도 Plush 감독이 같은 DTO 계약으로 통합 중이다. 검사 근거는 `.local-archive/receipt-terra-20261116/`에 보존했고 검증 workspace/임시 검증 branch는 공식 archive 후 정리했다. 사용자·성능 세션 변경과 기존 영수증 결과는 보존했다. graphify CLI·graph.json 부재로 그래프 갱신은 미실행이다.

## 2026-11-16 20:14 — 영수증 구현·운영 배포 완료, 실모델 판독은 로그인 차단

- **최신 요청/범위:** “영수증 관련 작업은 끝난건가? 이쪽 먼저 구현하고 배포해”에 따라 영수증을 우선 구현·배포했다. 영속 작업·복귀·사진/결과 교정·선택 내역 원자적 반영·PDF 원본 조회·Paseo 연결·운영 workflow 활성화를 통합했다. 성능 개선·Plush·Rust 전환은 이번 배포에 포함하지 않았다.
- **완료 코드/PR:** 최종 운영 SHA `11267cd012e074a0b89d28adb93a4dd736f64079`. 영수증 PR [#970](https://github.com/6Soo/cost/pull/970)(코드 `e977e235`, 병합 `921159ab`)와 보호 검사 수정 PR [#972](https://github.com/6Soo/cost/pull/972)(코드 `11267cd0`, 병합 `2a2ba33e`). 코드와 최종 SHA는 각각 독립 `gpt-6.1-sol medium` APPROVE. GitHub CI는 결제 한도로 작업 시작 전 실패했음을 정확 SHA의 annotation으로 확인했다.
- **검사:** 광범위 기준 `85ac8bcc` **1,443 passed +107 subtests**, 최종 영수증 변경분 `e977e235` **217 passed**, 배포 검사 수정 `11267cd0` **32 passed**, 전부 skip0·실패0. Rust costcore release build 통과. 별도 검수자는 보호 검사 표적11건과 추가 합성 불변조건29건 통과. 중복 집계하지 않는다.
- **첫 배포 실패와 복구:** `e977e235` 첫 배포는 새 빈 `receipt_evidence_links`가 추가돼 보호 표가 13→14개가 되자 개수 고정 검사가 실패했다. 공식 도구는 이전 `77865bfa`/8751로 롤백했고 health/ready200을 확인했다. 원래13표 변경0·삭제0, 추가표0행이었다. `11267cd0`는 원래 필수 표의 이름과 기존 모든 표의 내용·스키마를 검증하며, 명시 승인된 빈 추가 표만 허용한다.
- **운영 완료 근거:** 공식 `tools/deploy_verified_release.ps1` exit0. `77865bfa`→`11267cd0`, Board8752·Worker 전환 및 core writers 정합성 확인, Gateway8790. 릴리스1,764파일 Git blob 불일치0, 보호14표 불변, financial apply NOT_RUN. 별도 재점검 health200(0.423초)·ready200(0.045초), 비인증 `/receipts`·모델목록·workflow API401. 설정 workflow=true와 신규3표 존재 확인. 상세는 [운영 기록](operations.md) 맨 위 절이다.
- **백업/복원:** 첫 시도 전과 롤백 후 재시도 전 모두 board/core 범위 백업·복원 확인. 최신 `D:/WebLedgerHost/data/backups/receipt-deploy-retry-20261116-restore-evidence.json`(live/out-of-scope unchanged, binding equal). 사본 스키마 예행에서 기존78표 불변·빈3표 추가 확인. 연속 배포 도구의 `fresh_backup_restore=false`는 도구 내부 full-backup 옵션을 사용하지 않았다는 뜻이며, 위 별도 범위 백업/복원은 실제 수행했다.
- **남은 외부 차단:** 실제 사진 판독 성공만 PARTIAL/BLOCKED. 마지막 실제 Paseo 진단에서 Claude loggedIn=false·subscriptionAuth=false, 목록은 연결되지만 선택 차단. 사용자 로그인 복구 후 합성 사진의 start→완료→저장·복귀만 재검증한다. 실제 판독 성공을 주장하지 않으며 자동 유료 전환은 없다. 브라우저 TaskSpace44는 사용자 제어 중이라 takeover/대체공간을 만들지 않았고 기존 합성 검수 근거를 보존했다.
- **보존/후속:** 사용자 AGENTS.md·.codex/·.qwen/·review-size-attempt4.md와 성능 세션 변경 보존. 성능 후속 `0a1e359f`/`fix/ledger-first-load-20261116`는 운영 미반영(기록 당시 SQL48.307→0.187초, 로컬home57.405→1.874초, 표적158건); 후속 검수·배포·공개 재측정은 해당 세션 범위다. `graphify update .`는 CLI 미설치로 실패했으며 graph.json도 없어 갱신하지 못했다. 검증 worktree의 증거는 `.local-archive/receipt-deploy-20261116/`에 보존하고 공식 archive로 정리한다.

## 2026-11-16 — 영수증 Paseo 흐름 통합 검수 완료(운영 배포 전)

- **통합 커밋:** `291c44a7` (`feat(receipts): add local Paseo SDK bridge`). 로컬 Paseo provider/model catalog, 승인된 사진 입력 모델 필터, 고정 프롬프트·스키마 해시, 사진 첨부, run-key 멱등·복구, timeline 결과 회수·도구 차단·archive를 `tools/receipt_paseo_bridge.mjs`로 연결했다. `webapp/receipt_workflow.py`의 trailing whitespace도 제거해 diff 게이트를 통과시켰다.
- **직접 검사:** `node --check tools/receipt_paseo_bridge.mjs` 통과. 영수증 표적 검사 **42 passed**(runtime, HTTP acceptance, backend, UI). 영향 기반 `python tools/run_quality_checks.py --base origin/main --run` 통과: **1,253 passed, 107 subtests passed**, Rust `costcore` release build 성공. 문서 diff/link 검사도 통과했다.
- **실제 Paseo 확인:** catalog가 연결됨을 확인했고 provider 11개와 승인 가능한 Claude 사진 모델 5개를 읽었다. 합성 PNG로 `start → inspect → archive`를 실행했으며 provider가 `PASEO_PROVIDER_ERROR`를 반환했다. 로컬 timeline의 원인은 Claude 구독 결제 미납/갱신 필요였고, 코드·입력 오류가 아니다. 재호출하지 않고 차단 상태로 남긴다. 고객 원본·운영 DB·운영 포트는 사용하지 않았다.
- **브라우저 검수:** 이전 C 작업자의 TaskSpace 44 합성 검수에서 retry/revision/재분석 링크/입력 보존을 확인한 증거를 보존한다. 현재 TaskSpace 44는 사용자 제어 상태라 ego-browser가 takeover를 거부했으며, 이 세션에서 재검수하지 않았다. C 소유 합성 preview PID 27156은 종료하지 않았다.
- **상태/남은 일:** 승인된 범위의 코드·검사는 완료했지만 실제 provider 결과 검증은 구독 결제 상태가 해결될 때까지 PARTIAL이다. 운영 배포·push·PR·고객 자료 변경은 하지 않았다. 다음 재개 명령은 구독 상태 확인 후 합성 PNG로 `python` start/inspect를 다시 실행하고, 사용자가 TaskSpace 44 제어를 넘긴 경우에만 브라우저 검수를 재개하는 것이다. 사용자 미추적 `.qwen/`, `review-size-attempt4.md`, `.codex/`, AGENTS.md 변경은 보존한다.

## 2026-11-16 — Plush UI 전체 화면 설계 (문서 완료)

- **현재 요청/답변:** 사용자가 Dominik Martin의 Plush UI를 특정한 뒤 COST 전체 UI 설계를 요청했다. 주 사용 환경은 PC 장부 업무, 모바일은 조회·영수증 등록이다. 시각 선택지의 차이를 설명한 뒤 Plush의 외형·탄성 조작과 촘촘한 장부 표를 결합하는 기본안을 작성했다. 사용자가 선택지 1을 명시 승인했다고 기록하지 않는다.
- **산출물/완료 커밋:** `73bd96be` — [M4 Plush UI 설계](design/m4-plush-ui-20261116.md), SPEC §11.2와 문서 지도 연결. 정보구조·주소/권한 호환·PC/모바일 배치·두 테마 토큰·컴포넌트·모션·화면별 동선·API 요구·UI-0~6 이행·P-01~10 수락 기준을 포함했다. 이 절은 그 커밋 이후의 완료 기록이다.
- **직접 근거:** upstream `125a22ce151b719077637da38ffe9ec06a1a08c5`의 registry·tokens·README와 COST 코드/수락 기준 대조. Plush는 라이트 전용이며 표·셸·서랍과 COST 다크 테마는 확장이 필요하다. 일부 색쌍 정적 대비 계산 완료. 변경 문서 3개의 로컬 링크 114건·끊김 0, 요구/수락 ID 존재·diff check 확인.
- **범위/다음:** 설계 문서만 완료, 필수 미답 질문 없음. React 구현·패키지 설치·앱 검사·새 미리보기·push/PR·배포·고객 자료 변경은 미실행. 구현 요청 시 설계 §9의 UI-0(현 API/경로/권한/산출물 기능 지도)부터 시작한다. 기존 영수증 병렬 구현과 M3 운영 전환의 범위·상태는 아래 기록을 보존하며 이 문서로 변경하지 않는다.
- **작업공간:** 기존 `C:/AX/cost`, `integration/receipt-paseo-20261116` 재사용. 설계 관련 파일만 커밋했고 사용자 `.qwen/`·`review-size-attempt4.md` 및 다른 세션의 코드 변경은 보존했다. 별도 workspace·브랜치·서버는 생성하지 않았다.

## 2026-11-16 — 영수증 Paseo 병렬 구현·감독

- **감독 승계:** Paseo `77abc586-a18e-4b57-94f7-c9c8c3fa210e`가 인계 기록과 실제 worktree를 대조했다. 아래 최초 A/B native 작업자는 사용 한도로 실패했다. 복구 native `/root/receipt_runtime_recovery`, `/root/receipt_backend_recovery`도 초기화 대기에 머물러 중단한 뒤, 동일 worktree를 실제 실행 중인 Paseo Luna xhigh A `985d6162-2527-489c-991a-8d3165fc3013`, B `59274ce4-4e19-450a-8bb1-e98f64b99163`에 넘겼다. UI의 현재 소유자는 이어진 Paseo `1c99e24a-c577-488a-a0d4-48f8bea45095`다. 원래 폴더와 B의 미커밋 6개를 보존했다. 통합 HEAD는 아래 후속 커밋을 따르며 아직 신규 구현을 통합하지 않았다. 완료 검수·PR·배포를 주장하지 않는다.
- **후속 승계(17:17 KST):** Paseo A/B도 구독 한도로 중단돼 A `0d567726-1e72-41b0-bd75-3c67971a6cc9`, B `5a6024c1-248f-47a4-8ee5-e15ffa9fe7c1`로 자동 이어졌다. 실제 running·Luna xhigh·동일 worktree를 확인했다. 실패한 세션을 다시 실행하거나 새 작업자를 중복 배정하지 않는다.
- **감독 추가 검사:** A의 Python API·관리 지시/스키마 해시·합성 단위검사 커밋 `4521c51d`를 통합 `2b2b292d`로 반영했고 감독 직접 **8 passed, skip0**를 확인했다. 실제 SDK bridge·사진 실호출은 아직 구현 중이다. HTTP 수락 검사는 현재 20건으로, 사진별 성공·실패·0건, 원본 불일치, 장부 커밋 후 workflow 응답 유실/GET 전 교정 차단, 법인카드 증빙·청구금액 불변, 두 번째 비용 쓰기 도중 오류 시 전체 rollback을 포함한다(`ee063e3f`). 실제 CardFlow 합성 원행·장부행 seed만 별도로 확인했고 HTTP 본 검사는 B/C 통합 전이다. UI 검수에서 revision 고정·저장 실패 무한 재전송·재분석 버튼 누락을 지적해 C가 수정 중이다. ego-browser TaskSpace `44`, C 합성 preview `8799`(C 소유 PID27156)를 유지한다. 감독의 통합 preview 스크립트는 `.local-archive/receipt-paseo-implementation-20261116/supervisor_preview.py`에 준비했다(미실행). 상세 다음 명령·소유자는 같은 폴더의 `SUPERVISOR_CHECKPOINT.md`에 남긴다.
- **최신 승인:** 사용자가 작성 명세의 빠른 구현과 다수 Luna xhigh 병렬 위임을 지시했다. 이전의 문서까지만 범위는 갱신됐다. 이번에는 구현·합성 검사·PR 검수까지 진행하며 운영 배포·실제 고객 원본/운영 DB 변경은 하지 않는다.
- **기준/통합:** 명세 완료 `7b0a37ef`, 병렬 계약 `33ef9112`, 통합 branch `integration/receipt-paseo-20261116`. 실행 명세는 [영수증 처리 변경](design/receipt-paseo-workflow-20261116.md), [파일/API 계약](agents/artifacts/receipt-paseo-implementation-contract-20261116.md)이다.
- **A runtime:** native 협업 `/root/receipt_runtime_luna`, gpt-6-luna/xhigh, 공식 workspace `wks_543d5980ddf9a7e5`, branch `feat/receipt-paseo-runtime-20261116`. 동적 목록·사진 첨부·제한 실행·결과 회수 담당.
- **B backend:** native 협업 `/root/receipt_backend_luna`, gpt-6-luna/xhigh, 공식 workspace `wks_74534362dd92d88a`, branch `feat/receipt-paseo-backend-20261116`. 영속 작업·revision·복구·장부 원자성/멱등·인증 API 담당.
- **C UI:** Paseo agent `53231308-cb0e-419b-bdc9-10976f0ba7cb`, codex/gpt-6-luna/xhigh, 공식 workspace `wks_e6095e9982b526cd`, branch `feat/receipt-paseo-ui-20261116`. 모델 선택·사진/결과 검수·이탈/복귀·선택 반영 UI 담당. native 추가 thread 생성 한도에 따라 같은 계정 공식 Paseo 경로로 생성했다. 동시에 활동하는 구현자는 셋이다.
- **감독:** 주 세션이 docs·영향 맵·직접 검증·통합과 별도 최종 SHA 검수를 맡는다. 현재 코드 통합/전체 수락/배포 완료를 주장하지 않는다. 고객 원문·운영 포트·운영 DB는 작업자에게 주지 않는다. 원본 `.qwen/`·미추적 사용자 파일을 보존한다.
- **초기 확인:** runtime의 available는 사진/구독/격리 지원 증거가 아니어서 실제 제한·첨부·결과 회수 경로 검증이 필요하다. backend의 기존 manual expense API는 단건 트랜잭션이므로 선택 묶음/멱등 결과를 같은 장부 트랜잭션으로 묶어야 한다. 작업자들이 이 경계에 맞춰 구현 중이다.

## 2026-11-16 — 영수증 Paseo 동적 선택·영속 처리 명세 작성

- **현재 요청/범위:** 영수증 처리 변경의 명세 작성과 필요한 질문. 구현·실제 모델 호출·운영 변경은 요청하지 않았다. [설계 초안](design/receipt-paseo-workflow-20261116.md)을 작성하고 SPEC §7.1에 연결했다.
- **확정된 사용자 답변:** 승인된 구독 모델 중 사진 입력 가능한 모델만 선택; 관리되는 기본 판독 지시만 사용; 원본과 결과를 나란히 검수한 뒤 선택 내역만 COST 장부에 한 번에 반영. RCPT-020·RCPT-022를 개정하고 RCPT-031로 결과 보존·사용자 검수 요구를 기록했다. 카드 P1/P2·분기 AI 검수·Google 수동 붙여넣기는 변경하지 않는다.
- **설계:** 이 PC의 Paseo 모델 목록 조회 → 모델 선택과 동시에 실제 사진 첨부 → 서버 영속 작업·결과 → 다른 페이지/탭 이용 후 복귀 → 교정·선택 → 멱등·원자성을 갖춘 COST 장부 반영. 고정 프롬프트만 사용하며 미지원 모델의 OCR·다른 모델 대체는 새 흐름에 넣지 않는다.
- **직접 확인:** 현재 코드의 고정 Qwen OCR 경로·메모리 큐/1시간 TTL·브라우저 draft 저장 의존·후보 파일/TSV 출력 경계를 읽었다. 로컬 CLI 0.16.0-beta.2의 run/send `--image`와 데몬 provider/model 목록을 조회했다. provider available만으로 사진 지원·인증·한도를 확정할 수 없었다.
- **남은 기술 검증:** 운영 실행 계정의 같은 데몬 접속, 모델별 사진/도구 차단 지원, 비동기 종료 결과 회수, 기존 자료를 보존하는 영속 저장소, 실제 장부 쓰기 연결. 명세에 미검증으로 표시했으며 사용자에게 내부 구현 결정을 넘기지 않는다.
- **검증/다음:** 문서 작성 완료 커밋 `4af855bb083bd03e6f0a34e3b652182081408353`, 이후 이 완료 인계만 추가했다. Markdown217개·로컬 참조1,657건·끊김0, diff check PASS 및 코드 인용 대조. 앱 테스트·브라우저·실제 모델·운영 DB·배포 미실행. 질문3건은 모두 반영했고 추가 필수 질문은 없다. 설계 전체는 사용자 검토 전 초안으로, 문서 브랜치를 로컬에 저장했으며 PR/push/병합은 하지 않았다. 다음 구현 요청 전 코드를 바꾸지 않는다. 새 요청은 이 설계 §6 기술 확인부터 시작한다.
- **작업공간:** 기존 `C:/AX/cost` 재사용, `docs/receipt-paseo-workflow-20261116` 브랜치. 사용자 `.qwen/`·`review-size-attempt4.md` 및 기존 ignored 자료 보존. 이전 정리는 PR #969·main `9e2d66a3`에서 완료됐고 과거 절의 후속 병합·브랜치 삭제도 모두 끝났다. 아래는 이전 작업 근거다.

## 2026-11-16 — 임시 작업공간 정리 완료·주 작업 폴더 통합

- **현재 사용자 요청:** 모든 임시 워크스페이스·브랜치 병합·정리와 전체 문서 정리. 반려·철회된 변경의 재구현, 운영 배포, Rust 전환은 이번 실행 범위에 추가하지 않는다.
- **코드 통합:** #850·#966·#967·#968은 이미 병합됐다. 완료 코드 병합은 `d470eee2fc0e4da6481ad409a41944e102d40216`, 이번 정리 기준 main은 `9896a89ef9b487f013e4974bded5de5e51c79e8d`다. 카드 수집 352/352·skip0와 영수증 경로의 기존 검수·검사 근거는 [통합 기록](history/workspace-integration-20261116.md)에 보존했다. 이번에는 코드 변경이나 앱 검사를 추가하지 않았다.
- **브랜치:** 남아 있던 브랜치 4개의 tip이 모두 main의 조상임을 확인하고 복구 참조 보존 후 제거했다. 오래된 PR 검수 추적 참조 7개도 `refs/archive/20261116-final/review-tracking/`으로 보관했다. 정리용 문서 PR 브랜치는 검수·병합 뒤 제거한다. 원격 작업 브랜치는 없다.
- **작업공간:** worktree **23→1**(이번 후속에서 5→1), 원본 `C:/AX/cost`만 유지한다. Paseo 임시 workspace는 앞선 12개와 이번 3개를 공식 archive했다. 다른 프로젝트와 원본 폴더의 기존 local workspace 등록 2개는 보존했다.
- **프로세스:** 사용자가 명시 승인한 임시 프로세스 7개를 PID·생성 시각·작업 폴더로 재확인해 종료했다. 합성 미리보기 8797·8798과 관련 도구만 대상이다. 공용 Codex 서버·다른 프로젝트에서 재사용된 부모 PID·운영 서비스는 보존했다. 작업 폴더를 사용하는 프로세스가 없음을 확인한 뒤 제거했다.
- **사용자 변경:** 원본 폴더의 미커밋 15개 파일은 정리 전 ZIP과 파일별 SHA-256을 검증하고 실제 복원·해시 대조까지 마쳤다. 코드 2건은 main의 확장된 구현에 포함됨을 확인했다. 오래된 로컬 인계·감사 원문은 비공개 사본에 보존하고 최신 main 문서로 맞췄다. `.qwen/`, 기존 검사 산출물, `review-size-attempt4.md`는 원래 위치에 유지한다. 사용자 파일은 새 커밋에 포함하지 않는다.
- **미병합 보존:** Booking 예약 소실, 승객 이름의 최신 수동 별칭 덮어쓰기, 모바일 실패 검사, 중단된 P2·철회·대체 코드는 archive refs와 bundle에 보존했다. 이 기능들이 구현·병합 완료됐다는 뜻이 아니다. 결함 재현과 복원 방법은 [통합 기록](history/workspace-integration-20261116.md)을 따른다.
- **문서:** 저장소의 추적 Markdown **216개**, 로컬 파일·절 참조 **1,645건**을 검사해 끊어진 참조 **0건**을 확인했다. 기술 README의 현행 기준을 규칙집에 연결하고, 과거 설계·제안의 시점과 실제 실행·배포를 구분했다. 영수증 공급자·카드/OTA 수집기·증분 P2 첫 실행 안내도 근거 문서에 맞췄다. 최종 문서 SHA·독립 검수·병합은 이번 PR 기록을 따른다. 외부 웹 링크 검증·테스트·브라우저·운영 재배포는 실행하지 않았다.
- **복구 근거:** 앞선 `D:/CostWorkspaceArchive/20261116/`와 이번 `D:/CostWorkspaceArchive/20261116-final/`에 Git bundle·복구 ZIP·실제 복원 결과를 보존한다. 실행 기록은 `.local-archive/workspace-cleanup-final-20261116/`이다. 민감 자료와 로컬 검수 원문은 Git·PR에 넣지 않는다. 정리 요청에 남은 기능 개발·운영 작업은 없으며, 새 개발은 최신 사용자 지시에서 시작한다.
- **완료 커밋·인계:** 문서 정리 구현 `976db71b`, 이후 이 인계 문구만 추가했다. 남은 절차는 최종 SHA 독립 검수·문서 PR 병합·정리용 브랜치 삭제이며 이번 세션이 이어 수행한다. 이번 변경에는 추가 앱 검사·배포가 필요하지 않고 기능 개발 차단 사항도 없다. 반려 변경의 재개는 위 통합 기록과 비공개 bundle에서 시작하며, 운영 전환은 아래 승인 경계를 유지한다.

## 운영과 Rust 전환

- **운영:** 배포 증거 기준 `77865bfadce7cc96336cf751d1dbd41964549388`, Board 8751, readyz 200, 보호 13표 불변. 이 수치는 마지막 배포 기록이며 문서 정리를 위한 새 운영 검사가 아니다. 실제 배포 근거는 [운영 기록](operations.md) 맨 위 절.
- **Rust 1차 전환:** C1 신선 사본 7,336행, Python/Rust 그림자 차이 0·목록 밖 0. C2 185사례 두 방식 모두 동일. 과거 교정 대조 일치 131·불일치 40·원천 보호 제외 14. 전환 전 상태는 Python 작성자이며 전환 키 3개가 없다.
- **승인 ① 대기:** 이번 정리 요청은 Rust 운영 전환 승인이 아니다. [전환 절차서](playbooks/core-cutover.md)의 승인 ① → 신선 백업·복원 확인·사본 되돌림 예행 → 승인 ② → 설정 전환·Board/Worker 재시작·첫 창 대조 순서를 유지한다. 운영 `core.sqlite`는 11/15 생성분을 유지하며 백업 범위에 계속 포함한다.
- **Rust 2차(연결):** 11/15 OTA 목록 밖 차이 1,648건이 남아 별도 보류. 이번 요청에서 전환하지 않는다.
- **단계:** M2 종료, M3 진행. 구현 정본은 [SPEC](SPEC.md), 판정 정본은 [규칙집](DECISION_POLICY.md)과 `policy/`다. 이후 Rust·React·클라우드 순서와 데이터 보호는 그대로 유지한다.

이전 상세 인계와 완료 근거는 [정리 전 인계](history/session_handoff-through-20261116.md), [과거 배정표](history/BOARD-through-20261116.md), [문서 지도](README.md)에서 찾는다.
## 2026-11-16 — Plush UI 구현 통합 체크포인트

- **승인 범위:** 사용자가 Plush 전체 UI 구현을 병렬 위임하고 중단 후 재개를 지시했다. 설계 `73bd96be` 이후 공용 React 기반, 인증 API 클라이언트, 홈·여행·장부·거래·관리·영수증 화면을 통합 worktree `integration/plush-ui-20261116`에 반영했다.
- **실제 반영:** `frontend/src` 공용 컴포넌트·토큰·AppShell, `frontend/src/api` DTO/클라이언트, feature 폴더와 `main.tsx`의 `/ui/*` 경로 라우팅을 통합했다. 타입 호환 수정과 GET action 필드 순서·blob 응답 처리를 반영했다.
- **검증 근거:** `npm run typecheck` 통과, `npm run build` 통과(폰트 경로는 런타임 `/ui/fonts/...`로 남음). Vitest는 8건 중 7건 통과, blob fixture 1건은 Windows Node/jsdom Response가 Blob 본문을 `[object Blob]`로 직렬화하는 환경 불일치로 실패했다.
- **미완료/차단:** `webapp/plush_ui.py`는 정적 셸만 제공하고 `/api/plush/*` dispatcher가 아직 없다. 통합 HTTP 테스트는 `dist` fixture를 찾지 못해 4건이 setup error이며, API 구현 부재 검증까지 진행하지 못했다. 인증·ledger·receipt 서버 API와 운영 배포는 미완료다.
- **다음 명령:** D 작업 결과에서 실제 `plush_api` 서버 dispatcher를 찾아 `ledger_board` GET/POST hook에 통합한 뒤, frontend build 산출물로 `pytest -q webapp/tests/test_plush_integration.py`를 재실행한다. API가 없으면 해당 범위를 별도 구현 작업으로 기록하고 배포하지 않는다.

## 2026-11-16 — Plush projection API 통합 갱신

- D worktree의 미커밋 산출물 `webapp/plush_api.py`, `webapp/plush_projection.py`, `webapp/tests/test_plush_api.py`를 확인해 통합했다. `ledger_board._phase7_get`에서 인증 세션 확인 뒤 Plush GET projection dispatcher를 호출하도록 연결했다.
- 커밋 `670cc2ad`; API 단위 검사 `pytest -q webapp/tests/test_plush_api.py`는 6건 통과했다.
- 통합 HTTP 검사는 4건 중 2건 통과, 2건 실패했다. viewer 합성 fixture가 active connection을 만들지 않아 `visible_tabs`가 빈 집합을 반환하는 테스트 설정 문제이며, 권한 보호를 약화시키지 않고 보류한다. 운영 배포는 하지 않았다.
# 2026-11-17 — 수기 장부 행 원문 대조·공통 귀속 경로 수정 진행

- **현재 요청:** “행 원본 자료 대조해서 직접 확인하고 코드수정”. 직전 읽기 전용 조사의 제한을 대체한다. 카드 업로드 원본 4개를 재파싱해 81행의 날짜·금액·지급처·발급사·카드·거래방향이 모두 일치함을 확인했고, Google 불일치 77행도 XLSX 실제 셀과 다시 대조했다. 원문은 보호 경로 `D:/WebLedgerHost/data/backups/q12-auto-additions-20261116T181539Z/source-recheck/`에 보존했다.
- **구현:** 구형 I열·표준 H열·유럽 G열의 지출 원문을 원래 열에서 읽는다. 비표준 양식의 행을 읽더라도 수입·합계 검증 완료로 표시하지 않는다. 검수한 보관 원본의 해시·전체 시트 범위·실제 여행 연결을 고정하고 날짜·금액·지급처·발급사의 양방향 유일 대조로 수기 귀속을 공통 Python/Rust 판정에 공급한다(GGL-045). 자동 기록의 명시적 재판정에서만 거래·장부·보드를 함께 교정하고 기존 귀속 불일치·실제 수동·P2·완료 1분기·환불 보호를 지킨다. 예약기간·금융 연결은 만들어내지 않는다.
- **검증/남은 일:** 신규 합성 15건, 기존 Google/booking/core_writer 관련 검사 132건과 Rust plan_judgement 6건 통과를 확인했다. 실제 77행의 공통 plan이 모두 교정 대상으로 좁혀졌다. 실제 사본의 Python/Rust 교정·멱등 검증, 최종 SHA 독립 검수·공식 영향 검사·공식 배포가 진행 중이다. 현재 이 절 시점에서 운영 금융 변경·Google 쓰기는 없다. graphify update는 CLI 미설치로 실행하지 못했다. 앞선 조사 완료는 코드·운영 반영 완료를 뜻하지 않는다.
