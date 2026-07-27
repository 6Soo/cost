# LOG — 세션 핸드오프 기록

> 이 파일은 **에이전트 간 인수인계 로그**다. 새 세션/새 에이전트는 **맨 아래 최신 블록**을 먼저 읽고,
> 그다음 `CLAUDE.md`(모델·브리지 규칙)와 `docs/비용분류_지시사항_원장.md`(비용분류 전 규칙·교훈 이력)를 읽어라.
> 과거 상태 요약은 `STATUS.md`(Apps Script 엔진 이력)도 참조.

---

## 2026-07-24 세션 핸드오프 — 비용분류 엔진 재작성 + 저장소 정본화

### 0. 한 줄 요약
㈜숲길여행 **2분기(4~6월) 매출확인자료** 산출 파이프라인의 분류 엔진을 재작성해 "반복 누락"의
구조적 원인을 제거하고, 스크래치패드에만 있던 실행 파이프라인 전체를 저장소(`ledger/`)로 정본화했다.
**산출물 전달은 사용자 지시로 보류 중**(git 커밋은 완료, 사용자에게 파일 전달만 안 함).

### 1. 이번 세션에 한 일 (파일·결정 단위)
- **엔진 재작성 `ledger/build_v13_trip.py`** (사용자 지시 "Q2 필터 없애버려 / 순액처리원칙 어디갔어 / 1번으로 가야해"):
  - **① 승인일 Q2경계 필터(14일 근접창) 제거**: 선결제는 승인이 여행보다 수개월~1년 전일 수 있음
    (예: mercure 국민8835 **2/6·2/8 승인 → 묘코 6월 여행**). 매칭 카드가 4/1 이전 승인이면 간격 무제한 선결제 인정.
  - **② 순액처리 복원**: 취소(-)행은 Q2경계 skip 블록을 무조건 통과(`and a>=0`)시켜 항상 편입.
  - **③ 옵션① — 미매칭 실카드 → `여행_미배정`**: base·수기 어디서도 소비 안 된 Q2승인 카드를 날짜근접
    자동귀속(사용자가 ②안 기각) 없이 미배정 탭에 담아 대표 검토. 실측 **11건 +1,478,413**(국민3·하나8).
  - **④ 대사 게이트**: Q2승인 카드가 base·수기·미배정 어디에도 없으면 ⚠누락경고 → 리빌드 후 **누락 0 통과**.
- **신규 `ledger/patch_v14.py`**: 엔진이 재현 못하는 "수기 마스터"(P15) 잔여건만 재주입 — 팔레즈 241,350(무카드
  현금영수증)·mercure Q1선결제 342,280+556,929(국민8835, NEW 부재 검증)·단체항공 1인취소 -293,400×2
  (수기 r75/r76)·말라르 예약번호 노트(KBO-2882). **전용진 4,280,000·진에어 30,000은 엔진이 자동편입
  (TRIP-0218/TRIP-0346)하므로 재주입 안 함**(이중계상 방지). RF-TOYOKO(-94,641)는 net0 완전상쇄쌍
  양쪽이 리빌드서 함께 빠져 순액 불변 → 미복원.
- **신규 `ledger/cardindex.py`**: `fix_v14.py`가 `from cardindex import build_cards`로 의존하는데 저장소에
  누락돼 있던 것을 편입(이게 없으면 fix_v14 실행 불가였음).
- **`ledger/gen_april_rev.py`·`gen_mayjun_rev.py`**: C열 너비 2.5배(사용자 지시)·`wb68=v76` 반영.
- **`docs/비용분류_지시사항_원장.md`**: 이력(E) 최상단에 엔진 재작성 교훈 블록 추가.
- **`ledger/data/`·`ledger/newcard/conv/` 신설**: 실행에 필요한 입력·중간상태·현재 산출물을 저장소로 편입(3.6). 
- **저장소 정본화**: 작업 브랜치 `claude/code-review-branch-cleanup-lky6nc`(main보다 71 커밋 앞섬)를
  `main`에 병합. main 고유 4커밋(CLAUDE.md·tools/gemini.mjs·tools/llm-bridge.mjs·apps-script/LeaderPaymentSync.gs)
  은 보존됨. `.gitignore` add/add 충돌만 있어 union으로 해소.

### 2. 현재 상태 수치 (검증용)
- `ledger/data/classified_v14.csv` **1,705행**, krw합 310,719,899.
- 워크북 `ledger/data/숲길여행_2분기_비용분류_AI_v76.xlsx` 36시트, 상세 1,705행, 전탭 합 315,972,035.
- 주요 Q2 여행탭 순액: 0620_묘코 43,833,604 · 0424_알펜루트 52,303,306 · 0417_아오모리 36,529,870 ·
  0616_레분토&리시리 23,419,072 · 5월_유럽 20,722,872 · 0408_교토 17,253,592.
- 산출물 3종: `매출확인자료_4월_rev_v8.xlsx` · `매출확인자료_5-6월_rev_v5.xlsx` · `매출확인자료_2분기_통합_v5.xlsx`.

### 3. 배포/런타임 상태
- **Apps Script**(카드→장부 자동전기 엔진, `apps-script/`): scriptId
  `1myWv5UqHslTv13K_bDll7tbvxROpVFvwFUdWddSSqNn0-6iQDk9fROCX`, `.clasp.json`에 기록. 소유·실행 계정
  **kkokkohero6@gmail.com 단일**(메일함 + 시트 전부 소유). 배포/자동실행은 `AUTO_DRAIN=false`로 수동.
  clasp push는 이 계정 OAuth 재인증 필요(클라우드 세션에선 구글 접근 정책상 차단 — 코드만 여기서 작성).
- **Google Sheets 원장(장부)**: fileId `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU`
  ("(주)숲길따라 감성여행_아슬란", 여행탭 41개 + `2분기_기타비용`). 비용분류 파이프라인은 이 시트를
  다운로드(`ledger_current.xlsx`/`ledger_latest.xlsx`)해 오프라인 대조.
- **LLM 브리지**(`tools/gemini.mjs`·`tools/llm-bridge.mjs`): Gemini·GLM 등 저비용 모델 호출용. 키는 리포
  루트 `.env`(GEMINI_API_KEY·GLM_API_KEY 등, git에 없음). 클라우드 세션은 `NODE_USE_ENV_PROXY=1` 접두 필요.
- **크론/트리거**: 이 저장소 기준으로 설정된 스케줄 트리거·크론 없음(Apps Script 측 time-driven 트리거는
  스크립트 프로젝트에서 별도 확인). PR 구독(webhook) 없음.
- **배포 소스 브랜치**: Vercel 등 외부 배포 없음. 기본 브랜치 = `main`(origin/HEAD도 main, 정상).

### 4. 비용분류 파이프라인 실행 순서 (재현)
`ledger/`에서 CWD 주의 — 처음 세 단계는 `ledger/`에서, 워크북·rev는 `ledger/data/`에서 실행.
```
cd ledger
python3 build_v13_trip.py       # newcard/conv/EFGHA + data/classified_v12 + manual_v3/v4 → data/classified_v13.csv
python3 fix_v14.py              # data/classified_v13 (+cardindex, data/ledger_current.xlsx) → data/classified_v14.csv
python3 patch_v14.py            # 수기 마스터 잔여 재주입 (data/classified_v14.csv in place, data/manual_special_rows.json)
cd data
python3 build_workbook_v76.py   # classified_v14 + booking_info/fixes/trips/... → 숲길여행_2분기_비용분류_AI_v76.xlsx
python3 gen_april_rev.py        # v76 + ledger_latest.xlsx + /tmp/april_inc·evid.json → 매출확인자료_4월_rev_v8.xlsx
python3 gen_mayjun_rev.py       # → 매출확인자료_5-6월_rev_v5.xlsx
python3 consolidate_2q.py       # rev 2종 → 매출확인자료_2분기_통합_v5.xlsx (최종 통합본)
```
⚠ `gen_april_rev.py`/`gen_mayjun_rev.py`는 `/tmp/april_inc.json`·`/tmp/april_evid.json`·
`/tmp/mayjun_inc.json`·`/tmp/mayjun_evid.json`을 읽는다. 핸드오프용 사본을 `ledger/data/`에 뒀으니
실행 전 `cp ledger/data/april_inc.json /tmp/`(4개) 하거나 스크립트 경로를 상대경로로 바꿔라.

### 5. 미결·다음 할 일
- **산출물 최종 전달**: 사용자가 "출력하라" 지시하면 위 rev·통합본을 전달(현재 보류). 엔진은 이미 이 산출물 기준으로 재생성 완료.
- **`여행_미배정` 11건 대표 검토**: 옵션①로 격리한 미매칭 실카드(LOONG AGE 421,101·SICILY BY CAR 584,193·
  HERTZ 543,947·AVIS 366,794·트립닷컴_이니시스 152,358 등). 대표가 여행탭 귀속/판관비 판정 필요.
- **Q1 선결제 미매칭 잔여**: 옵션①은 **Q2승인 카드만** 격리한다. 승인이 Q1(예: 2월 mercure)인 미매칭 선결제는
  대응 여행탭이 불명해 자동격리 대상이 아니며, 현재는 patch_v14의 수기대조 수동주입으로만 편입된다.
  구조적 해결(예약번호/가맹→여행탭 귀속) 필요 시 별도 설계.
- **PR #4**(`claude/code-review-branch-cleanup-lky6nc` → main, draft): main 병합으로 내용은 반영됨.
  브랜치·PR 정리 방침은 §7 참조.

### 6. 함정·비자명한 사실 (이번 세션에 확인)
- **band-aid 수동주입 = 엔진버그의 신호**. 팔레즈·mercure·진에어를 매번 손으로 넣던 것은 엔진의 Q2필터/순액
  누락 때문이었다. 근본교정 후에는 재현 불가한 "수기 마스터"만 patch로 남긴다.
- **선결제 매칭에 승인일 근접창 금지** — 승인이 여행보다 1년 앞설 수 있다.
- **취소(-)행은 어떤 경계필터도 통과**시켜 순액을 보존한다.
- **CWD 불일치**: build_v13/fix_v14는 `ledger/`에서, build_workbook/gen_rev는 `ledger/data/`에서 돌아간다(스크래치패드 관습 그대로).
- **`cardindex.py`는 fix_v14의 필수 의존성**인데 그간 저장소에 없었다(이제 편입).
- 국민해외(E) 8835 카드의 AGODA MERCURE는 6건인데(779,680/195,029/214,248/174,668/556,929/342,280) 앞 4건은
  엔진이 자동편입, 뒤 2건(2/6·2/8 Q1승인)은 patch로만 편입 — 재대사 시 이 6건 매핑 주의.
- **P15(2026-07-23 확정)**: '영수증/현금/비카드'는 수기장부가 마스터 — 카드 대조 dedup 대상 아님.

### 7. 새 컨테이너/에이전트 부트스트랩 체크리스트 (git에 없어 다시 세워야 하는 것)
- **비용분류 파이프라인 실행**: `pip install openpyxl`. 입력·데이터는 `ledger/data/`·`ledger/newcard/conv/`에
  커밋돼 있어 추가 다운로드 없이 위 §4 순서로 재현 가능. 단 원장 최신본이 필요하면(P8) Google Drive에서
  fileId `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU` 재다운로드(→ `ledger/data/ledger_current.xlsx`).
- **Apps Script 배포**: `npm i -g @google/clasp` → `clasp login`(kkokkohero6@gmail.com) → `cd apps-script && clasp push`.
  clasp 토큰·구글 OAuth는 git에 없음.
- **LLM 브리지**: 리포 루트 `.env`에 `GEMINI_API_KEY`·`GLM_API_KEY` 등 필요(git에 없음). 클라우드 세션은
  명령 앞 `NODE_USE_ENV_PROXY=1`.
- **메일/드라이브/캘린더/GitHub**: MCP 커넥터 필요(§AGENTS.md의 MCP 설정 참조). 없으면 코드 작업은 되나
  메일·드라이브·시트 접근은 수동.

### 8. 에이전트 차이 (중요)
- **Claude 전용 기능은 다른 에이전트로 넘어가지 않는다**: 서브에이전트 위임(Agent/Task), Skill, 백그라운드
  워크플로우(Workflow), PR 웹훅 구독 등은 Claude Code 고유. CLAUDE.md의 "GLM 서브에이전트/모델 위임" 규칙도
  Claude 세션 안에서만 성립한다(Antigravity·Gemini CLI 등에는 해당 오케스트레이션 계층이 없음).
- 다른 에이전트에서는 `tools/llm-bridge.mjs`·`tools/gemini.mjs`를 **직접 셸로 호출**해 저비용 모델을 쓰는
  방식으로 대체하라(위임 자동화는 없음).

---

## 2026-07-25 세션 핸드오프 — OTA 확정결합 + 무손실 카드거래원장

- `apps-script/Code.gs`의 OTA 메일 매칭을 `EXACT/PROBABLE/HOLD`로 분리했다. 동일 OTA 브랜드·정확한
  통화/금액·결제일 ±3일·카드 끝번호 무충돌·예약번호/실사용일·후보 유일성이 모두 성립하는 `EXACT`만 전기한다.
- 모든 비어 있지 않은 카드 RAW 행에 `card_event_id`를 부여하고 `카드거래원장`에 원본 JSON과 상태를 1:1 보존한다.
  색상은 표시만 담당하며 처리 여부로 사용하지 않는다.
- 취소/환불도 `취소환불` 탭에 음수 거래로 전기하고 원장에 개별 보존한다. HOLD는 가맹점별 병합 없이
  `card_event_id`별로 `학습대기`에 기록한다. 파싱실패·범위외·전기차단도 모두 원장 상태로 남는다.
- 검증: `node tests/test_ota_matching.js` 11개 시나리오 통과, Apps Script 문법 검사 통과.
- Apps Script 배포 완료: 버전 `@2`, deployment
  `AKfycbzK2BQouRaSzmMoj9t59G2r9U3BjKd0XV8zd4ikXMTaof7UF6UR35xQN7hgPkNfLStt`.
  원격 재다운로드 후 5개 `.gs` 파일 로컬 일치 확인. 실제 `runReconciliation()`은 장부 변경을 피하려고
  배포 검증 중 실행하지 않았으며, 다음 수동 정산부터 `카드거래원장`이 생성된다.

---

## 2026-07-25 세션 핸드오프 — 최신 수기장부·2분기 산출물 재생성

- Drive 원장(fileId `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU`, 업무계정
  `kkokkohero6@gmail.com`) 최신본을 내려받아 `ledger_current.xlsx`와 `ledger_latest.xlsx`를 갱신했다.
  원장 SHA-256은 `CEA581D142C0B62F3398F97699600CF3E2AB048105D36117524319821CC524DC`.
- 누락돼 있던 재현용 `ledger/parse_ledger_v4.py`를 추가했다. 헤더 기반으로 병합형/연속열형을 모두 읽고,
  Google Sheets에 생긴 동일명 `(1)` 복제 탭은 이중 계상 방지를 위해 제외한다. 구 원장에 적용했을 때
  기존 `manual_v4.csv` 1,335행을 완전 재현했고, 최신본에서는 1,380행을 추출했다.
- 파이프라인 경로 결함을 교정했다: `build_workbook_v76.py`가 실제 데이터 디렉터리를 사용하도록 했고,
  rev 생성기의 `/tmp/*.json` 의존을 `ledger/data/*.json` 상대경로로 바꿨다.
- 최신 산출: `classified_v14.csv` 1,684행, 원화 합계 310,130,982원. 카드 승인 누락 가드는 0건.
  상설 무결성 감사는 12건(B 워크북중복 2, C 카드표기상충 8, D 장부중복의심 2)을 보고했으며 원자료는
  임의 수정하지 않았다.
- 최종 파일 4개를 `outputs/20260725_latest_q2/`에 출력했다. Artifact Tool로 50개 사용자 시트를 전부
  렌더링했고, 4개 파일 모두 수식 오류 토큰 0건·정상 개방을 확인했다. `test_cardindex` 2건 통과.

---

## 2026-07-25 세션 핸드오프 — OTA 예약기간 복원·항공 기간 규칙

- 최신 Drive 원장에서 일반화되어 사라진 `숙박_체크인_체크아웃` 설명은 거래분류 입력과 분리된
  `manual_periods.csv`에만 과거 검증값을 승계한다. 원본 `manual_v3/v4.csv`는 변경하지 않아 분류·중복제거
  결과(1,684행, 310,130,982원)가 흔들리지 않는다.
- `booking_periods_verified.json`을 추가했다. Gmail OTA 원문에서 직접 확인한 Agoda 4건, Trip.com 숙박 7건,
  렌터카 1건의 예약번호별 기간을 기록했다. 같은 탭·동일 항목에서 확정 기간이 하나뿐인 예약번호 건은
  그 기간을 승계하며, 복수 기간이면 추측하지 않는다.
- `rev_periods.py`에 공통 규칙을 추가했다. `항공_MMDD_이름`은 편도 출발일, `항공_MMDD_MMDD_이름`은
  왕복 출발일_도착일을 기간 열에 기록한다. 숙박·렌트도 같은 형식으로 내용/기간을 분리한다.
- 검증: `test_rev_periods` 6건 + `test_cardindex` 2건 통과. 통합본에서 예약번호가 있는 숙박·항공·렌트의
  기간 공란은 0건이며, Artifact Tool로 사용자 시트 50개 렌더 성공·수식 오류 토큰 0건·4개 파일 정상 개방.
- 최종 파일은 `outputs/20260725_ota_period_rules/`에 출력했다.

---

## 2026-07-25 세션 핸드오프 — Google Workspace MCP·여행자보험 기간

- `@aaronsb/google-workspace-mcp@4.0.1`을 전역 설치하고 Codex의
  `~/.codex/config.toml`에 `google-workspace` MCP로 등록했다. 서버 구동은 확인했으나 현재 Google Cloud
  Desktop OAuth Client ID/Secret과 등록 계정이 없어, Codex 재시작 후 자격증명 등록·업무계정
  `kkokkohero6@gmail.com` 인증이 남아 있다.
- Gmail 원문 확인 결과 고마가네 프리몬트 호텔은 OTA 데이터가 존재한다. 2026-02-28 Trip.com 확정메일에
  예약번호 `1400824130566434`, 체크인 2026-04-14, 체크아웃 2026-04-15가 명시되어 기존 `0414_0415`와 일치한다.
- 트래블로버 66,710원은 `4/13~16 일본 여행자보험 가입내역 -12명` 메일과 금액이 일치한다.
  표시용 `manual_periods.csv`를 `여행자보험_0413_0416`으로 보강하고 `rev_periods.py`가 여행자보험도
  내용/기간으로 분리하도록 했다.
- 테스트 9건 통과. 4월본·통합본의 해당 행은 `여행자보험 / 0413_0416`으로 출력된다.
  Artifact Tool 수식 오류 0건, 사용자 시트 50개 렌더 성공. 최종 파일은
  `outputs/20260725_travelover_period_mcp/`에 출력했다.

---

## 2026-07-25 세션 핸드오프 — 오제산장 고액 이체 반영

- 사용자 확정 거래 `2026-07-16 모인_주식회사 3,472,049 오제산장숙박비`를 비카드 수기 마스터
  `MAN-OZE-LODGE-3472049`로 추가했다. 귀속은 `0630_오제`, 항목 `오제산장`, 내용 `숙박`,
  계정 `숙박비`, 증빙유형 `이체`, 원가구분 `여행원가`다.
- 재생성 시 유실되지 않도록 `manual_special_rows.json`과 `patch_v14.py`의 RESTORE 대상에 함께 넣었다.
- `build_workbook_v76.py`가 모든 MAN 건을 `영수증`으로 덮어 이체를 오분류하던 결함을 수정했다.
  이제 MAN 건은 원천 `extra`의 `이체/현금/영수증`을 그대로 보존한다.
- 반영 후 `classified_v14.csv`는 1,685행, 원화 합계 313,603,031원. `0630_오제` 지출합계는
  9,529,293원에서 13,001,342원으로 증가했다.
- 워크북·5~6월본·2분기 통합본을 재생성했고 세 파일 모두 `0630_오제`에 오제산장 3,472,049원,
  증빙 `이체`가 표시된다. Artifact Tool 수식 오류 토큰 0건·시각 렌더 확인.
  최종 파일은 `outputs/20260725_oje_lodge_transfer/`에 출력했다.
- Google Workspace MCP OAuth는 앱이 테스트 상태인데 업무계정이 테스트 사용자에 없어 403이 발생했다.
  Google Cloud Audience 설정 탭을 열었으나 Chrome 세션에서 업무계정 비밀번호 입력이 필요해 사용자 인계 상태다.

---

## 2026-07-25 세션 핸드오프 — OTA 예약번호·동액 실카드 오삭제 교정

- 사용자 지적으로 `0413_나가센도` 고마가네 OTA 7건을 재검증했다. 기존 출력은 62,496원 수기행 2건 중
  1건을 중복으로 삭제해 6건만 남겼으나, 카드 원본에는 승인번호 `30096534`·`30096556`의 서로 다른
  정상 거래 2건이 존재한다. 삭제가 잘못됐음을 확정하고 두 건 모두 보존했다.
- 원인은 `fix_v14.py` ①B가 예약번호 공란 상태에서 동탭·동액·동일 설명만으로 먼저 제거한 뒤
  ①C 카드 원본 건수 검증을 수행한 순서였다. 카드 원본이 존재하는 행은 ①B에서 선삭제하지 않고,
  ①C가 `(카드사, 정확금액, 취소여부)` 원본 건수까지만 보존하도록 수정했다.
- 같은 결함으로 오삭제된 실카드 3건도 함께 복원했다: `0616_레분토&리시리` 336,292원 2건
  (각 승인번호 상이), `0625_아키타` 341,394원 1건(동액 2건의 승인번호 상이). 총 복원액은
  1,076,474원이며, 그중 고마가네 복원액은 62,496원이다.
- 고마가네 7건 전부에 Gmail Trip.com 확정 예약번호 `1400824130566434`, 기간 `0414_0415`를 연결했다.
  고마가네 그룹은 7건·합계 1,133,680원·승인번호 7개로 검증된다.
- 회귀테스트 `test_dedup_card_events.py`를 추가했다. 고마가네 62,496원 2건, 레분토 336,292원 3건,
  아키타 341,394원 2건의 행 수와 승인번호 유일성, 고마가네 7건 예약번호를 상설 검증한다.
- 워크북·4월본·5~6월본·2분기 통합본을 재생성했다. Artifact Tool 검사에서 고마가네 예약번호가
  워크북 G7:G13, 4월본/통합본 F26:F32에 7건 모두 존재하고 수식 오류 토큰은 0건이다.
  최종 파일은 `outputs/20260725_ota_booking_dedup_fix/`에 출력했다.

---

## 2026-07-25 세션 핸드오프 — 렌터카 기간 규칙

- `rev_periods.py`의 렌터카 표시 규칙을 명시했다. OTA 예약에서 인수일·반납일이 모두 확인된 경우에만
  내용은 `렌트`, 기간은 `MMDD_MMDD`로 기록한다.
- `렌터카_MMDD_MMDD`·`렌트_MMDD_MMDD` 입력은 기간을 분리한다. 인수일만 있는 불완전한 값이나
  OTA 검증값이 `MMDD` 하나뿐이면 기간을 채우지 않아 추측을 방지한다.
- 렌터카 인수·반납 기간의 내장형/OTA 검증형/불완전값 거부 테스트를 추가했고 `test_rev_periods.py`
  11건이 통과했다.
- 사용자 지시대로 규칙과 테스트만 수정했으며 워크북·매출확인자료는 재생성하지 않았다.

---

## 2026-07-25 세션 핸드오프 — 카드 환불 불변 보존·OTA 그룹키

- `fix_v14.py`의 거래 병합 기준을 승인번호 우선으로 변경했다. 양쪽 승인번호가 있으면 같은 승인번호일
  때만 병합하며, 승인번호가 빠진 경우에도 근사금액이 아닌 정확금액만 후보로 인정한다.
- 예약번호/OTA 주문번호/PNR은 결제·환불의 그룹키로만 사용한다. 거래 PK는 `uid`와 승인 이벤트이며,
  동일 예약의 분할결제·부분환불을 각각 독립 행으로 보존한다.
- 원거래 양수 건을 찾지 못한 취소/환불 9건을 삭제하던 규칙을 폐기했다. 모두
  `연결대기 환불(원거래 미확인·삭제금지)` 상태로 남긴다.
- 카드 원환불 보존으로 중복이 된 과거 임시행 `RF-AIR1/2` 복원을 제거했다. 최종 분류자료에서
  원 카드 환불 `TRIP-0374/0375`만 남는 것을 확인했다.
- Gmail 원문 검증값을 UID별로 연결하는 `data/ota_event_links_verified.json` 경로를 추가했다.
  실제 검증 전에는 예약번호나 기간을 추측해 채우지 않는다.
- 항공 항목명에 일정이 명시된 경우(예: `트립닷컴_0417_0429`) 기간 `0417_0429`를 읽도록 했다.
- 회귀테스트 18건(거래보존 4, 카드인덱스 2, 기간규칙 12)과 관련 Python 구문검사가 통과했다.
  사용자 요청 범위에 따라 워크북·2분기 파일은 출력하지 않았다.
---

## 2026-07-25 세션 핸드오프 — Gmail OTA 전체 대사 1차

- 업무 계정 Gmail에서 2025-08-01~2026-07-31 OTA 관련 메일 1,720건을 읽어
  `ledger/data/ota_mail_index.json`에 로컬 검색 인덱스를 만들었다. 원본 메일은 변경하거나 삭제하지 않았다.
- `ledger/reconcile_ota_index.py`로 OTA 카드 이벤트 546건을 대사했다. 동일 예약번호의 확인·변경·전달 메일은
  서로 다른 후보가 아니라 하나의 예약 근거로 합쳤다.
- 기존 수동 검증 12건에 더해 금액·결제일·여행일·승객명 근거가 강한 28건을 자동 확정하여
  `ledger/data/ota_event_links_verified.json`에 총 40건이 연결됐다.
- 남은 건은 후보 충돌/근거 부족 308건, 후보 메일 없음 198건이다. 사용자에게는 영향도가 큰 10건만
  우선 질문하고 답을 받아 순차 확정한다.
- `fix_v14.py`와 `patch_v14.py`를 다시 적용했으며 테스트는 19 passed, 10 subtests passed다.
  사용자 지시에 따라 워크북·2분기 출력 파일은 생성하지 않았다.
## 2026-07-27 세션 핸드오프 — Linux 환경 이전

- 모든 Codex 서브에이전트와 비용처리 작업을 중단했다. 동결 시점에 실행 중인 비용처리 프로세스는 없다.
- Linux 이전 브랜치는 `codex/linux-migration-2026-07-27`이다.
- 최우선 인계서는 `docs/CODEX_LINUX_MIGRATION_HANDOFF_2026-07-27.md`이며, 완료·미완료 수치, OTA HOLD 9건,
  Linux 첫 실행 순서, 외부 연결, 민감자료 별도 이전 목록을 기록했다.
- OTA 546건 중 기존 확정 68건, 로컬 신규 병합 가능 7건, 미확정 471건이다. 이는 OTA 사이트 전수 완료가 아니라
  로컬 상태 전수 집계다. Agoda SQLite의 저장 예약은 0건이다.
- 하나카드 XLS 825건은 재검증했고 신규 취소 2건을 원장에 병합했다. 3건은 기존 렌터카 이벤트의 최종 청구액
  스냅숏 충돌이며, 승인번호 없는 취소 -56,666원 1건은 HOLD다.
- 인건비 3건 1,350,000원은 반영 확인했고 전용진 카드이용대금 4,280,000원 이체는 제외했다.
- Git에 원시 Gmail 색인, OAuth/`.env`, Agoda 로컬 DB, `outputs/`는 올리지 않는다. Linux로 암호화 별도 이전해야 한다.
- 동결 검증: 카드/중복/기간 테스트 19 passed + 10 subtests, Apps Script OTA 엔진 11 passed, OTA 감사 재현 성공.
  도메인 테스트는 현재 1,835행인데 1,705행을 기대하는 고정 fixture 때문에 1 failed, 2 passed이며 인계서에 기록했다.
- 다음 세션은 인계서의 §5 순서로 환경을 검증하고, 신규 OTA 링크 7건의 가드 병합부터 재개한다.

---

## 2026-07-27 세션 핸드오프 — OTA 로그인 후 직접증거 대사

- 사용자가 Agoda·Trip.com·Booking.com 로그인을 완료했다. 인증 URL·PIN·메일 원문은 저장하지 않았다.
- Booking.com 결제완료 메일 26건을 개인정보 허용목록 JSON으로 적재했다. 카드 RAW와 결제일·통화·
  외화금액·카드끝4(메일에 있는 경우)를 교차해 **17건을 고유 강일치**로 확정했고
  `ota_event_links_verified.json`을 68→85건으로 append-only 병합했다.
- Booking.com 반복금액은 임의 배정하지 않았다. Nezame JPY 15,510 4예약×4카드가 N:M 충돌이며,
  직접메일 중 카드 교차가 없는 5건도 HOLD다.
- Agoda 인증 포털 직접증거는 기존 4건에 사용자 확인 6건을 더해 10건으로 보존하고,
  `ota_checkpoints_agoda.db`에 예약별 즉시 커밋·재조회했다. Gmail 결제영수증 4건도 별도
  허용목록 JSON으로 적재했다. 동일금액 중복 영수증은 1:1로 추정하지 않는다.
- OTA 546건 전수 disposition 보고서 결과: 기존확정 68 + 신규직접확정 17 = **확정 85**,
  증거부족/충돌 **HOLD 461**. 공급자별 HOLD는 Agoda 206, Trip.com 193, Booking.com 16,
  Mytrip 19, Travelrover 27이다. 보고서는 `outputs/20260727_all_pending_review/`에 생성했다.
- 비 OTA 잔여 `KBD-0403`은 기타비용/주차비 2,400원, `CORP-2005`는 0원 취소정산으로 확정했다.
  하나카드 최종청구 스냅숏 3건과 승인번호 없는 -56,666원 취소는 별도 HOLD로 유지한다.
- 직접 카드 링크가 legacy canonical 결제를 가리킬 때도 RAW `card_event_id`를 강한 매칭 계보로
  인정하도록 교정했다. P05 회귀차이 8건은 P3 재배분·신규 취소 이벤트의 정확한 키/금액만
  허용하는 명시적 전환으로 분류해 `unexplained_differences=0`을 복원했다.
- `patch_v14.py`로 OTA 링크 85건을 재주입한 정본은 **1,835행 / 320,055,642원**이다.
  전체 build_v13 재생성은 현재 입력 조합에서 1,556행으로 축소되는 원천손실 가드가 작동해
  결과를 폐기하고 검증된 1,835행 정본을 복원했다. 이 재현 불일치는 해결 전까지 HOLD다.
- 최종 XLSX 재출력은 현재 세션에 필수 Artifact Tool 런타임이 없어 중단했다. 기존 XLSX를
  openpyxl로 다시 쓰지 않았으며, Artifact Tool이 제공되는 세션에서 정본 v14를 입력으로
  새 버전 파일을 만들고 전 시트 렌더·수식 오류 검사를 수행해야 한다.

---

## 2026-07-28 세션 핸드오프 — 무손실 재개·P0 릴리스 게이트·OTA 의미 교정

- 승인 정본 `classified_v14.csv`를 P0 기준선으로 동결했다. 기준은 1,835행,
  320,055,642원, SHA-256
  `187cd7b7a7dfed48c1eda11ecf258229920ab7c9a8ecec1d5a4a7b680a3a403e`이며,
  `ledger/baselines/p0_current_canonical_20260728/manifest.json`에 원천별·버킷별·환불
  census와 필수 입력 해시를 기록했다. 구 v76 워크북과 2026-07-27 OTA 보고서는
  `release_blocks.json`에서 배포 차단 상태다.
- `build_v13_trip.py`→`fix_v14.py` 실제 재빌드를 별도 `/tmp` 후보로 수행했다.
  결과는 1,552행·250,233,365원이었다. `patch_v14.py` 적용 후에도 기준 정본 대비
  누락·추가·불변필드 변조가 있었고 254,845,973원으로 65,209,669원 부족했다.
  P0 canonical reproduction gate가 이를 예외로 차단했고 최종 후보 파일은 쓰지 않았다.
  기존 `ledger/data/classified_v14.csv`는 변경하지 않았다.
- 모든 빌드 스크립트의 기본 출력을 `outputs/` 신규 버전 후보로 바꾸고 입력=출력 및 기존
  파일 덮어쓰기를 금지했다. 환불/취소 원거래 선택은 복수 후보에서 첫 행을 고르지 않고
  전체 양방향 1:1 고유 후보일 때만 연결하도록 공통 selector를 적용했다. 순차 처리 중 먼저
  본 환불이 원거래를 소비하는 used-set 방식과 파생 버킷 우선 선택을 제거했다. 최종 P0 gate는
  정본의 실제 SHA·바이트와 22개 사실/세무 필드를 확인하며 note/extra/confidence/tax_conf만
  표시 보강 대상으로 허용한다.
- OTA 보고는 `ota_event_links_verified.json` 포함 여부를 확정으로 승격하지 않는다.
  append-only 현재 결정만 확정/충돌로 인정하며, 실제 충돌만 HOLD, 미처리·제안은 PENDING으로
  분리한다. Booking과 Agoda 직접증빙 매처는 카드 원천의 공급자·통화·외화금액·카드끝4와
  가용 결제일이 양방향 고유할 때만 강확정한다. 동일 `message_id` 중복 증빙은 동일 내용이면
  1건으로 접고, 내용이 다르면 실패한다. 카드 이벤트 identity를 모두 후보에 포함해 반복금액
  N:M 카드가 누락되지 않게 했다.
- 최신 결정권위 보고서는 `outputs/20260728_decision_authoritative_review_v8/`이다.
  OTA 546건 중 최종 확정 16건(Booking 14, Agoda 2), 실제 충돌 HOLD 9건(Booking),
  PENDING 521건이다. 직접매처 자체는 적격증빙 31건을 확정 19 + 충돌 6 + 정확교차 없음
  6으로 보존하며, 외화금액이 없는 Agoda 원화증빙 2건은 `ineligible_records`로 별도 표시한다.
  동일 결제에 legacy 충돌과 직접확정이 병존한 3건은 보수적으로 HOLD가 우선하므로 최종 확정이
  19→16건이다. 보고서는 schema 2, 코드/정본/검증링크 SHA provenance를 가지며 기존 경로는
  `x` 모드로 덮어쓰지 않고 staging 디렉터리에서 완성한 뒤 원자적으로 발행한다. 상태는
  `audit_only_blocked`로 명시해 완료된 릴리스로 오인하지 않게 했다.
  따라서 과거 “확정 85/HOLD 461”은 결정 상태와 조사대기 상태를 섞은 수치로 폐기한다.
- 워크북 소스는 요약에서 `전기예약_환불`을 포함하고 건수·금액의 범위를 일치시켰으며,
  입력 SHA·행수·합계·커밋·생성시각 `_provenance` 시트를 추가했다. 출력은 v77 신규 후보만
  허용한다. 다만 이 세션에는 Spreadsheet Skill이 요구하는 Artifact Tool 런타임이 없어
  XLSX 생성·렌더·수식 오류 검증은 수행하지 않았고 기존 XLSX도 건드리지 않았다.
- 회귀검증은 최신 핵심 P0/OTA/환불/계보/워크북 대상 103건이 통과했다. 변경 중간시점의
  전체 Python 도메인 테스트도 250건 통과했으며, 최신 변경분은 103건으로 다시 검증했다.
  JavaScript 런타임이 없어 `.cjs` 테스트는 실행하지 못했다.

---

## 2026-07-28 세션 핸드오프 — Trip·Booking·Agoda 로그인 포털 병렬 수집

- 로그인된 Chrome에서 Trip.com, Booking.com, Agoda를 공급자별 독립 작업·체크포인트로
  병렬 조사했다. 인증코드·PIN·쿠키·비밀번호·승객명·주소·전화·전체 URL 토큰은 산출물에
  저장하지 않았고, 전체 직접증빙 JSON의 금지 필드/URL·이메일 문자열 검사는 0건이었다.
- Trip.com은 포털 예약 10건을 저장했다. 2건은 결제일까지 명시적으로 확인됐고 8건은
  포털에 결제일이 없어 추정하지 않았다. `ota_checkpoints_trip.db`의 current 10건과
  `trip_direct_browser_evidence.json` 10건이 일치하며 DB 무결성은 `ok`다.
- Booking.com은 이메일 증빙 26건 중 포털 직접증빙 19건(73.1%)을 확보했다. 최초 13건은
  정확일치 6건·JPY 표시금액 충돌 7건이고, 이메일 인증 후 추가한 6건은 결제일 충돌 5건·
  결제상태 충돌 1건이다. 나머지 7건은 예약 소유권 인증 경로가 없어 미완료다.
  JSON/DB current는 각각 19건이고 DB 무결성은 `ok`다.
- Agoda는 기존 10건을 보존하면서 페이지별 append-only 샤드를 사용했다. 메인/페이지3/
  페이지4/페이지3~5 목록/페이지4~5 상세 샤드의 current 234행을 예약번호 기준으로 병합해
  메인 `agoda_direct_browser_evidence.json`과 `ota_checkpoints_agoda.db`를 고유 233건으로
  통합했다. importer 필수필드 기준 complete 219건, incomplete 14건이며 DB 무결성은 `ok`다.
  2페이지 마지막 5건은 `ERR_BLOCKED_BY_CLIENT`로 상세 미수집이다.
- `ledger/tools/merge_ota_checkpoint_shards.py`를 추가했다. 공급자 샤드를 메인 DB에 append-only
  병합하고 메인 JSON을 current 행으로 원자 재생성한다. 동일 입력 재실행 결과 신규 삽입 0건,
  메인 current 233건으로 멱등성을 확인했다. 샤드 원본은 삭제하지 않았다.
- `classified_v14.csv`와 기존 정본·워크북은 변경하지 않았다. OTA 결정 상태 546건 재산정과
  비용 정본 반영은 이번 수집과 별도 단계다. Python 구문검사와 SQLite/JSON 독립 검증은
  통과했으나 전체 `test_ota_checkpoint`는 실행 환경에 `openpyxl`이 없어 import 단계에서
  중단됐다.
