# 카드사 로그인 자동화

- 목적: 카드사 3곳(국민 기업카드·하나카드·IBK 기업은행 카드)의 법인/기업 이용내역 조회 로그인을, 등록된 자격 증명으로 사이트당 1회 시도하는 모듈로 만든다. 수집 스크립트는 "로그인 확인 → 안 돼 있으면 이 모듈 호출 → 실패하면 handOff 후 멈춤"으로 붙는다.
- 실행 주체: 스크립트(`tools/card_login/`, ego-browser `.mjs`) + 에이전트(ego-browser 보조 단계) + 사용자(자격 증명 등록·추가 인증 승인·시도 가드 해제)
- 주기: 수집 스크립트가 로그인 만료를 감지할 때
- 개정 이력:
  - 2026-11-13 · 최초 작성 · 소유자 결정("카드사 로그인 자동화 계획 위임 및 착수", "로그인 시도·비밀번호 입력 허용") 반영. 통합 명세 §7의 "카드사 로그인은 자동화하지 않는다"를 이 결정으로 바꾼다.
  - 2026-11-13 · 하이브리드(스크립트+에이전트 보조) 반영 · 소유자 결정("필요한 부분은 에이전트가 ego로 진행할 수 있게 섞는다"). 고정 단계는 스크립트, 막히는 단계(가상키패드·인증서 선택·변화하는 팝업)는 에이전트 보조로 넘긴다. §9 추가.
  - 2026-11-13 · 독립 검수(REQUEST_CHANGES) 결함 수정 · (1) named pipe 접근 제한(현재 사용자 SID만 허용 DACL + 클라이언트 PID 검증, fail closed) (2) 사이트당 1회 시도 가드를 디스크에 영속(`attempts.json` + `reset_attempt.ps1`). 회귀 테스트 추가(§6).
  - 2026-11-13 · 독립 검수(REQUEST_CHANGES 2차) 수정 · 시도 직전 `attempting` 선기록(비정상 종료로 남으면 차단)·성공 시 `verified` 전환, 저장소 fail-closed(깨짐·읽기/쓰기 실패 시 미시도)·원자적 쓰기(임시 파일 후 교체), 키패드 입력 글자 수 누출 제거("입력 완료"만). 회귀 테스트 추가(§6).

> 근거: [통합 명세](../SPEC.md) §7·§13, [카드 원본 수집 안내](card-downloads.md), [하나·기업 조사 기록](card-login-research-20261111.md). 비밀 값·고객 원문은 이 문서에 적지 않는다.

## 1. 사이트별 조사 결과 (2026-11-13)

확인 방법: 국민은 ego-browser로 로그인 화면 DOM을 직접 관찰(입력·제출 없음). 하나·기업은 공개 웹 정보 기반이며 **라이브 화면 미확인(NOT_VERIFIED)** 이다. 브라우저 작업 공간이 사용자 제어로 전환되어 하나·기업 라이브 조사와 실제 로그인 검증은 이번 단계에서 수행하지 못했다.

| 발급사 | 로그인 진입점 | 로그인 방식 | 보안 프로그램 요구 | 자동 입력 가능 경로 | 막히는 지점 |
| --- | --- | --- | --- | --- | --- |
| 국민 기업카드 | `biz.kbcard.com/CXERCZZC0001.cms` | 아이디 탭(`doIdLoginA`) / 공동인증서 탭(Wizvera Delfino G3, `doCertLoginA`) | AhnLab ASTx2 키보드보안(`secuKeyASTx2`), 가상키패드(`secukeyPad`), Delfino G3, ASKD2 | 공동인증서(PC 인증서 + 인증서 비밀번호) 경로가 현실적 후보 | 아이디·비밀번호 입력란이 `readonly` — 가상키패드/키보드 보안이 직접 입력을 차단. 공식 키보드 전환 가능 여부는 라이브 미확인 |
| 하나카드 | `www.hanacard.co.kr` 기업카드 영역 로그인(`OCY65301000M.web`), 기업 전용 `biz.hanacard.co.kr` 언급 | 아이디 / 공동인증서 / 간편인증 탭, 키패드 입력 | 통합설치 Veraport, 공동인증서 WiziN-Delfino G3, 키보드보안 ASTx, 로그수집 IPInside | 간편인증(사용자 휴대폰 승인 대기) + 공동인증서(법인공동인증서) | 키패드 입력 방식이라 ID/PW 직접 입력 차단. 법인 전 직원 내역은 관리책임자/총괄관리자 등록 필요. 라이브 미확인 |
| IBK 기업은행 카드 | `kiup.ibk.co.kr/uib/jsp/online/main/main_login.jsp` (기업인터넷뱅킹) | 공동인증서(WizIN-Delfino G3) + 아이디/비밀번호 병행 | Delfino G3, 보안프로그램 설치 안내 | 공동인증서 + ID/PW 경로 후보 | OTP·씨크리트카드 추가 인증 가능. ONE 비밀번호 3회 오류 시 로그인 제한. 이용내역 메뉴 경로 라이브 미확인 |

공통 결론: 세 곳 모두 ID/PW 직접 입력은 키보드 보안·가상키패드로 막힐 가능성이 높고, 공동인증서(Delfino G3) 또는 간편인증 경로가 현실적이다. 보안 프로그램 설치는 하지 않으며 필요 여부만 기록한다(사용자 PC에 이미 설치되어 있을 가능성 높음 — 과거 로그인 이력).

자동화 가능 여부(화면 구조 기준 잠정): **국민 부분 / 하나 부분 / 기업 부분** — 모두 라이브 검증 필요. ID/PW 자동 입력은 보안 입력 차단으로 미확인, 인증서·간편인증 경로는 추가 인증에서 사람이 남는다.

## 2. 비밀정보 저장 설계

- 저장: DPAPI **사용자 범위** 암호화 파일. 위치 `D:/WebLedgerHost/secrets/card-login/<issuer>.json` (`kb`·`hana`·`ibk`). 평문은 파일·로그·인자·환경 변수·채팅에 남기지 않는다. 같은 Windows 사용자만 복호화할 수 있다.
- 등록: `tools/card_login/register_credentials.ps1 -Issuer <kb|hana|ibk>`. 입력은 `Read-Host -AsSecureString`(화면 미표시). 아이디·비밀번호·인증서 비밀번호(선택)를 받는다.
- 읽기: `tools/card_login/read_credentials.ps1`가 복호화 후 **일회성 named pipe**로만 전달한다. 파이프 이름은 비밀이 아닌 임의 식별자(매 실행 무작위). `.mjs`는 `credentials.mjs::readCredentials`로 파이프 클라이언트 접속해 메모리로만 받는다. 비밀 값은 프로세스 인자·환경 변수·stdout·디스크 평문으로 내보내지 않는다.
- 파이프 접근 제한(검수 결함 수정): 파이프 생성 시점 DACL(`New-CardLoginPipeSecurity`)이 **현재 사용자 SID에만** FullControl을 허용한다. 다른 계정·Everyone·익명에는 허용 규칙이 없어 접근이 거부된다. 연결 1회 후 즉시 닫는다. 서버는 `GetNamedPipeClientProcessId`로 연결한 클라이언트 PID를 조회해 호출자가 넘긴 기대 PID(`-ClientPid`, Node 부모 프로세스)와 다르면 **값을 보내지 않고 닫는다(fail closed)**. stdin/stdout 전달 대신 이 경로를 택한 이유: 비밀이 Node 부모로 향하므로 stdin 방향이 맞지 않고, ACL+PID 검증으로 결함을 정면 해결하면서 stdout에 비밀이 남지 않는다.
- 미등록이면 로그인 시 없이 `registration_required`("사용자 등록 필요")로 멈춘다.
- 모듈: `tools/card_login/CardLoginSecrets.psm1`(등록/읽기/왕복), `register_credentials.ps1`(대화형 등록), `read_credentials.ps1`(pipe 전달), `credentials.mjs`(Node 클라이언트 + 마스킹).

## 3. 로그인 모듈 인터페이스

수집 스크립트가 붙는 진입점: `tools/card_login/common.mjs::ensureCardLogin({ task, page, site, statusDir, ... })`.

흐름:
1. `site.isLoggedIn(page)` — 이미 로그인되어 있으면 시도 없이 `logged_in`.
2. 자격 증명 읽기 — 미등록이면 `registration_required`로 멈춤(시도 없음).
3. **영속 시도 가드(fail-closed)** — `attempts.json`이 깨졌거나 읽을 수 없으면 시도하지 않고 멈춘다(`error`). 실패·잠금 경고·추가 인증/에이전트 보조 대기, 비정상 종료로 남은 `attempting` 기록이 있으면 사용자 해제(`reset_attempt.ps1`) 전까지 재실행해도 시도하지 않는다(`attempt_blocked_until_reset`). 성공 기록은 다음 시도를 막지 않는다.
4. 프로세스 내 1회 가드 — 같은 실행에서 재시도 없음(영속 가드와 별개의 이중 보호).
5. **시도 전 기록(fail-closed)** — 로그인 입력 직전에 `attempting`을 먼저 기록한다. 기록이 실패하면 시도하지 않고 멈춘다(`error`). 쓰기는 원자적(임시 파일에 쓴 뒤 교체).
6. `site.login(page, creds)` 1회 — 성공/실패/추가인증/에이전트 보조 반환.
7. 에이전트 보조(`agent_assist`) → 화면 캡처 + handoff 상태 파일을 남기고 `task.handOff()` 후 `agent_assist_required`로 멈춤(§9). 에이전트가 보조 단계를 수행한다.
8. 추가 인증 → `task.handOff()` 후 `additional_auth_required`로 멈추고 무엇을 승인해야 하는지 보고.
9. 실패 → 재시도 없이 `login_failed`. 비밀번호 오류 횟수 경고가 보이면 즉시 멈춤.
10. 성공 → 기록을 `verified`로 바꾸고, 이용내역 조회 화면 진입까지만 확인(`confirmUsageScreen`) 후 로그아웃 → `verified`. 결제·한도·설정·카드 신청 화면에는 들어가지 않는다.

각 시도의 결과(결과 코드·시각·사유 코드, 비밀 없음)는 `D:/WebLedgerHost/data/card-login/attempts.json`에 영속한다(`attempts.mjs`). 시도 직전 `attempting`을 먼저 남기므로 프로세스가 중간에 죽어도 재실행 시 시도하지 않는다. 사유에 비밀 값이 섞여도 마스킹해 저장한다.

상태는 비밀 값 없이 `statusDir`에 `<issuer>-login-status.json`으로 남긴다(상태 화면 "로그인 필요" 연결용). 반환 상태: `logged_in` / `verified` / `registration_required` / `additional_auth_required` / `agent_assist_required` / `login_failed` / `error`.

사이트 모듈: `kb.mjs`(DOM 확인 선택자 반영, 보안 입력 readonly는 우회 않고 `agent_assist`로 넘김), `hana.mjs`·`ibk.mjs`(공개 정보 기반 틀, URL·선택자·성공 판정 NOT_VERIFIED). 진입점 `entry.mjs::mainEgo`, 레지스트리 `SITES`.

## 4. 사람이 남는 부분

- 자격 증명 등록(최초 1회, 사용자가 직접 명령 실행).
- 추가 인증: 휴대폰·OTP·간편인증 승인(모듈이 handOff 후 멈추면 사용자가 승인).
- 보안 프로그램 미설치 시 설치(사용자 작업; 모듈은 설치하지 않고 필요 여부만 보고).
- 하나 법인 전 직원 내역 열람 권한(관리책임자/총괄관리자)이 없으면 권한 설정(사용자 작업).

## 5. 자동화가 불가능한 경로와 대안

- ID/PW 직접 입력이 키보드 보안·가상키패드로 끝내 막히는 경우: 공동인증서(인증서 비밀번호 자동 입력) 또는 간편인증(휴대폰 승인 대기)으로 전환. 그래도 막히면 수집 스크립트는 `login_required`로 멈추고 상태만 표시한다.
- 완전 무인(추가 인증까지 제거)은 카드사 자료 전송 서비스나 유료 수집 서비스가 필요하다. 요금·조건은 조사 항목으로만 둔다(통합 명세 §14 #8). 과금 승인 없이 진행하지 않는다.
- 대안: 카드사 이메일 명세 수신 설정(이용내역을 메일로 받아 기존 메일 수집기로 처리). 로그인 자동화가 막힐 때의 보완 경로.

## 6. 검증 상태 (2026-11-13)

- 합성 검사 통과(모두 임시 폴더 격리, 운영 저장소·상태 파일 접근 없음):
  - 자격 증명 DPAPI 왕복·암호화 파일 평문 부재·named pipe 전달·미등록 경로(`tests/test_card_login_credentials.py`).
  - 로그인 로직·마스킹·영속 가드·추가인증 handOff·상태 파일 평문 부재(`tests/card_login/test_login_logic.mjs`).
  - 영속 시도 가드: 실패/대기 후 재시도 차단·reset 후 허용·성공 비차단·사유 비밀 마스킹·`reset_attempt.ps1` 실제 실행, 시도 전 `attempting` 선기록(비정상 종료 시 재시도 차단)·성공 시 `verified` 전환·깨진/스키마 불일치/읽기 불가/쓰기 불가 저장소 → 미시도(fail-closed)·원자적 쓰기(`tests/card_login/test_attempt_guard.mjs`).
  - 에이전트 보조 헬퍼: 키패드 좌표/선택자 클릭(비밀·글자 수 미출력)·누락 키 일반 오류·DOM 키패드 관찰·assistKeypadEntry 상태·캡처/handoff 평문 부재·agent_assist 흐름(`tests/card_login/test_assist_logic.mjs`).
  - 파이프 보안 회귀(검수 결함): DACL 현재 사용자 SID만 허용(타 계정·Everyone·익명·합성 타 사용자 SID 거부)·기대 PID 수용·예상 밖 PID 거부(`tests/test_card_login_pipe_security.py`).
- **실제 로그인 검증 미실행**: 운영 자격 증명 저장소 미등록 + 브라우저 작업 공간 사용자 제어. 사용자가 등록 후 라이브 검증이 필요하다.
- 국민 입력 단계 코드는 보안 입력(readonly)을 우회하지 않고 `agent_assist`(가상키패드 보조)로 넘기도록 구현됨. 하나·기업 입력 단계는 URL·선택자 확정 전까지 실행되지 않는 틀.

## 7. 하지 않는 것

- 로그인 우회·보안 프로그램 우회·반복 인증 제출. 사이트당 시도 1회, 실패 시 재시도 없음.
- 비밀 값의 채팅·문서·Git·로그·명령 인자·환경 변수 기록. 인증서 개인키·원문 식별자 조회.
- 결제·한도·설정 변경·카드 신청 화면 진입. 운영 DB 쓰기. 보안 프로그램 설치.
- 고객 거래 원문 출력. 운영 포트(8751/8752/8790) 사용. 내가 시작하지 않은 프로세스 종료.

## 8. 사용자가 할 일 (쉬운 한국어)

1. **비밀번호 등록(한 번만):** 아래 명령을 카드사마다 실행하고, 화면에 보이지 않는 입력란에 아이디·비밀번호·인증서 비밀번호를 차례로 입력합니다. 입력값은 암호화되어 컴퓨터에만 저장되며 화면·로그·대화 어디에도 남지 않습니다.
   - 국민: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/card_login/register_credentials.ps1 -Issuer kb`
   - 하나: `... -Issuer hana`
   - 기업: `... -Issuer ibk`
2. **휴대폰 인증 대기:** 로그인 중 휴대폰·OTP·간편인증 승인이 뜨면 프로그램이 멈추고 알려줍니다. 그때 휴대폰에서 승인하면 됩니다.
3. **보안 프로그램:** 컴퓨터에 카드사 보안 프로그램이 없으면 설치가 필요하다고 알려줍니다. 설치는 사용자가 직접 합니다.
4. 등록을 마치면 담당자가 사이트마다 실제 로그인을 한 번씩 시도해 결과를 보고합니다. 실패·잠금 경고·추가 인증 대기로 끝나면 다시 시도하지 않고 멈춥니다(계정 잠금 방지). 이 멈춤은 컴퓨터에 기록되어, 프로그램을 다시 실행해도 자동으로 재시도하지 않습니다.
5. **다시 시도 허용(필요할 때만):** 멈춘 사이트를 다시 시도하려면 아래 명령으로 해당 사이트 기록을 해제합니다. 해제 전에는 재시도하지 않습니다. 성공한 사이트는 막히지 않으므로 해제할 필요가 없습니다.
   - 국민: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/card_login/reset_attempt.ps1 -Issuer kb`
   - 하나: `... -Issuer hana` / 기업: `... -Issuer ibk`

## 9. 하이브리드: 스크립트 단계 / 에이전트 보조 단계

원칙: **고정된 단계는 스크립트**, **막히거나 변화하는 단계는 에이전트가 ego-browser로 보조**한다. 보안 프로그램을 끄거나 입력 속성을 변조하지 않는다. 사이트가 제공하는 공식 가상키패드·인증서 선택 창을 정상 사용자 경로로 조작한다.

### 9.1 사이트별 단계 구분

| 발급사 | 스크립트 단계(고정) | 에이전트 보조 단계(막힘/변화) |
| --- | --- | --- |
| 국민 기업카드 | 로그인 화면 진입·아이디 탭 선택·입력란 readonly 감지·성공/실패/추가인증 문구 판정·조회 화면 확인·로그아웃 | 가상키패드 비밀번호 입력(ASTx가 합성 키 차단 시 좌표 클릭), Delfino G3 인증서 선택 창, 변화하는 팝업·공지 |
| 하나카드 | (URL·선택자 확정 후) 화면 진입·입력란 감지·문구 판정·조회 화면 확인·로그아웃 | 키패드 입력, 간편인증 승인 대기 안내, Veraport/Delfino G3 인증서 선택, 변화하는 팝업 |
| IBK 기업은행 | (URL·선택자 확정 후) 화면 진입·입력란 감지·문구 판정·조회 화면 확인·로그아웃 | Delfino G3 인증서 선택, OTP·씨크리트카드 추가 인증 대기, 변화하는 팝업 |

스크립트가 막히는 지점에서 `login()`이 `{outcome:'agent_assist', step, detail, agentAction}`을 반환하면, `ensureCardLogin`이 화면 캡처 + handoff 상태 파일을 남기고 `task.handOff()` 후 `agent_assist_required`로 멈춘다. 에이전트는 이 상태를 읽고 보조 단계를 수행한다.

### 9.2 에이전트 보조 절차

1. **상태 읽기:** `statusDir`의 `<issuer>-agent-handoff.json`(`handoff.mjs::readAgentHandoff`)에서 `issuer`·`step`·`reason`·`screenshot`·`agentAction`을 읽는다. 캡처는 비공개 폴더(`D:/WebLedgerHost/data/backups/card-login-20261113/assist`)에 있다.
2. **화면 관찰:** ego-browser snapshot으로 현재 화면 구조를 확인한다. 변화하는 팝업·공지가 있으면 닫거나 공식 경로를 따라간다.
3. **가상키패드 입력:**
   - DOM 키패드: `keypad.mjs::observeDomKeypad(page, containerSelector)`가 한 글자 버튼의 중심 좌표로 문자→좌표 배치를 만든다(배치는 비밀 아님).
   - 캔버스/이미지 키패드: 에이전트가 스크린샷에서 키 좌표를 읽어 `keyMap`으로 넘긴다.
   - 입력 실행: `keypad.mjs::assistKeypadEntry(page, {issuer, field, keyMap|containerSelector})`가 **DPAPI 저장소에서 비밀을 함수 내부에서만 읽어** 좌표 클릭 순서를 만들고 실행한다. 반환은 `{status:'entered'}`뿐 — 에이전트 대화에는 "입력 완료"만 남기고 글자 수는 남기지 않는다(길이 누출 방지).
4. **인증서 선택(Delfino G3):** 인증서 선택 HTML 창을 snapshot으로 관찰해 공식 선택·확인 버튼을 클릭한다. 인증서 비밀번호가 필요하면 `assistKeypadEntry(..., {field:'certPassword'})`로 내부 입력한다.
5. **추가 인증:** 휴대폰·OTP·간편인증은 에이전트가 대신 승인하지 않는다. `additional_auth_required`로 멈추고 사용자에게 무엇을 승인해야 하는지 알린다.
6. **복귀:** 보조 단계가 끝나면 스크립트 흐름(성공 판정·조회 화면 확인·로그아웃)으로 돌아간다. handOff로 사용자 제어가 넘어간 작업 공간은 에이전트가 자동으로 되찾지 않는다(스킬 규칙).

### 9.3 비밀 취급 규칙(하이브리드 공통)

- 비밀 값은 **스크립트 함수 내부에서만** DPAPI 저장소에서 읽는다(`credentials.mjs::readCredentials` → 일회성 파이프). 에이전트가 비밀 문자열을 직접 읽거나 다루지 않는다.
- 에이전트는 **클릭 좌표만 계산**하고 입력 문자열(비밀)은 출력·로그·대화·상태 파일·캡처 파일명에 남기지 않는다. 키패드 클릭 순서 자체가 비밀이므로 순서를 설명하지 않는다.
- 에이전트 대화에 남는 것은 "입력 완료"(`{status}`)뿐이며 글자 수는 남기지 않는다(길이 누출 방지). 누락 키 오류도 어떤 문자가 누락됐는지 노출하지 않는 일반 코드(`KEYPAD_KEY_MISSING`)다.
- 캡처·handoff 상태 파일은 비공개 폴더에만 저장하며 파일명·내용에 비밀을 넣지 않는다(`handoff.mjs`).
- 보안 프로그램(ASTx·Delfino G3·Veraport 등)을 끄거나 우회하지 않는다. 공식 가상키패드·인증서 창을 정상 사용자 경로로 조작한다.
