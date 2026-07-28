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

## 2026-07-29 세션 핸드오프 — Windows 재개·OTA 링크 7건 병합·APA 표현충돌 발견

### 0. 환경 정정
- 인계서는 Linux 이전을 전제했으나 **실제 재개 환경은 원본 Windows 머신**이다. `.env`만 부재하고
  `outputs/`(13개 디렉터리)·`ota_mail_index.json`(29MB)·`ota_checkpoints_agoda.db`는 로컬에 그대로 있다.
  따라서 인계서 §6의 "암호화 별도 이전"은 이번 재개에 해당하지 않는다. (`.env` 부재로 LLM 브리지만 불가)
- Windows 절대경로 감사(`ledger`·`tools`·`tests`) 결과 하드코딩 `D:\`·`C:\Users\`·`DownLoad` **0건**.
  인계서 §5의 경로 이식 과제는 이미 해소된 상태다.

### 1. 이번 세션에 한 일
- **인계서 §4-1/§12-7 첫 실행과제 완료 — OTA 검증링크 7건 가드 병합(68 → 75)**.
  대상: `TRIP-0039`·`TRIP-0040`·`KBO-2647`·`KBO-2650`·`KBO-2651`·`KBO-2705`·`KBO-2706`.
  가드 결과: 기존 링크 overwrite **0건**, 대상 uid 전건 `classified_v14` 실재 확인, 수량검산 68+7=75,
  백업 → 임시파일 → 원자적 rename → read-back → 기존 68건 무변형 확인까지 통과.
  재현 스크립트 **`ledger/merge_verified_ota_links.py`** 신설(`--apply` 없으면 dry-run).
- 병합 후 OTA 감사 재실행: 확정 75 · 병합대기 **0** · HOLD 9(불변) · 카드이벤트 546건 불변.
  공급사별 확정은 agoda 6 / trip 49 / booking 5 / mytrip 15 / travelrover 0.

### 2. 검증 결과 (재현값)
- `ledger/` CWD `pytest test_cardindex.py test_dedup_card_events.py test_rev_periods.py -q` → **19 passed, 10 subtests**.
- 루트 `node tests/test_ota_matching.js` → **11 passed**.
- 루트 `node tools/audit-ota-reconciliation.mjs` → 정상, 위 수치 재현.
- 루트 `pytest ledger/tests/test_domain_ledger.py -q` → **2 failed, 8 passed**(220s).
  실패 2건 모두 fixture 고정값(1,705행 / 310,719,899원)이 현재 1,835행 / 320,055,642원과 어긋난 것이며
  `validation_report(...)["valid"]`는 통과했다. **fixture는 아직 갱신하지 않았다**(아래 §3 미해결 때문).
- 현재 `classified_v14.csv` 자체 무결성: 1,835행 · 320,055,642원 · uid 중복 0 · 빈 uid 0 · 음수행 73건(-21,646,773).

### 3. ★미해결 — APA HOTEL 571,962 표현충돌 (대표 판단 필요)
인계서 §12-6의 "행 수를 먼저 검증한 후 fixture를 고친다"를 이행하다 발견했다.
1,705행 기준본과 현재 1,835행본을 업무키(card4·use_date·krw)로 대조하면 구본에만 있는 행이 21건이다.
그중 18건은 손실이 아니다:
- **SMILE 무일자 3행(3,516,000)** → 수기 재파싱본의 실일자·실금액 3행(810,666+1,242,168+1,474,398=3,527,232)으로 **교체**됨.
- **RF-AIR1/2(-586,800)** → 카드 원환불 `TRIP-0374`/`TRIP-0375`(-293,400×2)로 대체(2026-07-25 기록된 의도적 제거).
- **트립닷컴 취소환불 12행** → KBO(+)·MAN(-) 완전상쇄쌍, 순액 영향 0.

남은 **APA HOTEL 571,962 4행**이 진짜 쟁점이다.
- 수기 마스터 `manual_v3/v4.csv`에는 `0424_알펜루트` 탭에 571,962원 4행이 **서로 다른 Agoda 예약번호**로 존재한다:
  `1721756989`(하나)·`1721758806`(하나)·`1721757952`(기업)·`1721761805`(기업).
- 카드 원본(base `classified_v12`)에는 이 4건에 대응하는 **합산청구 1건** `KBO-2755` 2,287,848원
  (2026-04-26, APAHOTEL, 현재 귀속 `0417_아오모리`)이 있다. 4×571,962 = 2,287,848로 정확히 일치한다.
- **구 1,705행본**: 4행 + 합산청구 1행을 모두 계상 → 2,287,848원 **이중계상**.
- **현 1,835행본**: 합산청구 1행 + 분할 1행(`TRIP-0166`, appr 03228812)만 남음
  → 571,962원 **초과계상**이고 예약번호 3건(`1721758806`·`1721757952`·`1721761805`)은 **표현 자체가 소멸**.
- 즉 인계서 §9.10이 "사본 누락 3건/1,715,886원"으로 기록한 회귀는 실재하나, 구본도 정답이 아니었다.
- 탈락 지점은 `fix_v14`가 아니라 엔진 `build_v13_trip.py`다(`classified_v13`에서 이미 1건).
  원인은 수기행 순회 중 `sd>='2026-04-01' and a>=0`이면서 선결제 카드매칭에 실패하면
  "base에 이미 존재"로 간주해 `continue` 하는 블록이다. 그러나 이 4개 예약번호는 `book_in`(base 예약참조)에
  **없음**을 실측 확인했으므로, 이 skip은 해당 건에 대해 근거 없이 적용된다.
- **자동 확정 금지**: 불변규칙 1(카드이벤트 삭제금지)·4(예약번호는 그룹키)와 원장 표기가 충돌하며,
  귀속 탭도 카드행 `0417_아오모리` vs 수기행 `0424_알펜루트`로 갈린다. 대표 판단 후 처리한다.

### 4. 다음 할 일
1. **APA 571,962 표현방식 대표 확정** → 확정안대로 `build_v13_trip.py` skip 블록 교정 후 리빌드.
2. 위 확정·리빌드 후에야 `ledger/tests/test_domain_ledger.py` 고정 기대값(1,705/310,719,899) 갱신.
3. 인계서 §4-2 공급사별 잔여 대사: trip 191 → booking 28 → mytrip 19 / travelrover 27, Agoda 206은
   Edge 다중세션 + SQLite 1건씩 영속화로 별도 진행.
4. 브랜치 통합: 현재 `codex/linux-migration-2026-07-27`은 `origin/main` 대비 **2 ahead / 18 behind**.
   충돌 12개 중 CSV·문서 다수는 CRLF 아티팩트지만, `ledger/domain/*`은 `origin/main` 쪽이 실질적으로
   앞서 있다(`ledger_db.py` +1,660행, `schema.sql` +233행, `test_domain_ledger.py` +413행 상당).
   `ledger_current.xlsx`/`ledger_latest.xlsx`도 양쪽 해시가 다르다(HEAD `cea581d1…`=2026-07-25 기록된 원장,
   main `76e839c5…`=P0.5 커밋). **병합 전 어느 쪽이 최신 원장인지 확인 필요.**

---

<!-- 아래 블록은 origin/main 계열(도메인 모델 v2·P0~P6) 세션 기록이다.
     2026-07-29 브랜치 통합 시 양쪽 이력을 모두 보존했다. -->

## 2026-07-25 세션 핸드오프 — 비용분류 도메인 모델 v2 기반 구축

### 0. 한 줄 요약
결제 한 행에 원천·예약·여행귀속·계정·증빙·신뢰도를 모두 넣던 구조를 해소하기 위해
`feat/domain-separated-ledger-model` 브랜치에서 SQLite 기반 도메인 분리 모델을 병렬 구축했다.
기존 v14/v76 산출 경로는 변경하지 않았다.

### 1. 구현
- `ledger/domain/schema.sql`: 원천, 결제, 취소관계, 예약, 여행, 배분대상, 근거, 판정,
  버전형 배분계획, 장부전기를 독립 테이블로 분리.
- `ledger/domain/ledger_db.py`: DB 초기화, `classified_v14.csv` 멱등 이관, 합계 불변식 검증,
  분류 품질 검토 리포트 CLI.
- `allocation_plans`: 한 결제를 여러 예약·여행으로 나누는 1:N 배분을 plan 단위로 버전 관리.
- `ledger/tests/test_domain_ledger.py`: 기존 정본 이관, 멱등성, 도메인 경계, 취소·예약 관계,
  1:N 배분, 외래키, 검토 리포트 총 7개 테스트.
- `docs/비용분류_도메인모델_v2.md`: 설계·실행법·전환 게이트 문서화.
- 지시사항 원장에 P16(결제 도메인 분리·병렬검증 후 전환) 추가.

### 2. 이관 검증
- 원천 1,705행 → 결제 1,705건 → 활성 배분 1,705건.
- 결제합 = 배분합 = **310,719,899원**, 결제별 배분 차이 0.
- 예약 371건, 여행 34건, 배분대상 30개, 독립 판정 8,525건.
- 취소/환불 관계 58건 중 원거래 연결 51건, 미연결 7건.
- 테스트 7개 전부 통과.

### 3. 새 모델이 드러낸 기존 분류 품질 이슈
- 현재 `여행_미배정` 실제값은 **19건 2,734,540원**.
- 기존 핸드오프의 **11건 1,478,413원**은 v13이 생성한 `MISC-*` 집합이며,
  이 중 1건은 이후 `취소환불`로 이동했다. 따라서 “현재 미배정”과 “신규 격리 생성분”은 다른 지표다.
- 금액 0원 결제 9건, 원거래 미연결 7건, 공급자 미확정 예약 112건.
- `confidence=상`이지만 근거 문구에 `추정·유사·불명·확인 필요`가 있는 결제 **196건**.
- 저신뢰 결제 87건. 이 항목들이 다음 재분류 우선 검토 큐다.

### 4. 실행
```bash
python3 ledger/domain/ledger_db.py import-legacy
python3 ledger/domain/ledger_db.py validate
python3 ledger/domain/ledger_db.py review-report
python3 -m unittest discover -s ledger/tests -p 'test_*.py'
```
기본 DB `ledger/data/ledger_v2.db`는 로컬 생성물이며 gitignore 대상이다.

### 5. 다음 단계
1. 196건의 “상 신뢰도/추정 근거”를 규칙별로 묶어 실제 검토 큐와 재판정 명령 구현.
2. 미연결 취소 7건과 provider 미확정 예약 112건의 연결 규칙 보강.
3. 카드·메일·수기 원본을 `classified_v14` 경유 없이 각 source adapter로 직접 적재.
4. v2 배분 결과로 기존 워크북을 생성하는 read-only 어댑터를 만들고 여행별·계정별 회귀 대조.
5. 전환 게이트 통과 전에는 기존 v14/v76을 정본으로 유지.

---

## 2026-07-25 세션 핸드오프 — v2 정합성 개선 P0 검토 기반 구현

### 0. 한 줄 요약
정합성 개선 작업의 첫 단계(P0)로 집계 리포트의 모든 품질 지표를 행 단위로
재현하고, 실행 간 추가·해소·잔존 건과 v14 회귀 합계를 비교할 수 있는
`review-snapshot` 명령을 구현했다.

### 1. 구현
- `ledger/domain/ledger_db.py`
  - 8개 상세 검토 큐: 미배정, 엔진 격리, 0원, 취소관계 미연결,
    공급자 미확정, 예약 복수귀속, 고신뢰/불확실 근거, 저신뢰.
  - 모든 큐에 자연키와 결제·예약·배분대상·현재 판정·규칙·신뢰도·근거 문맥 포함.
  - 입력 원천 SHA-256, 규칙 버전 `p0-v1`, semantic SHA-256을 가진 기준선 manifest 생성.
  - 배분대상·여행·계정별 건수/금액 회귀 기준 생성.
  - `--compare-to` 이전 스냅샷 대비 추가·해소·잔존 자연키를 `diff.json`으로 생성.
- `ledger/tests/test_domain_ledger.py`
  - 집계-상세 건수/금액 일치, 자연키 유일성, 회귀 총액, 반복 실행 안정성,
    CSV/manifest/diff 산출 검증 추가. 전체 10개 테스트 통과.
- `ledger/README.md`, `docs/비용분류_v2_정합성개선_실행계획.md`
  - 실행법과 산출 구조를 기록하고 P0 완료 표시.

### 2. 검증 결과
- 상세 큐 건수: 미배정 19, 엔진 격리 11, 0원 9, 미연결 취소 7,
  공급자 미확정 112, 복수귀속 0, 고신뢰/불확실 196, 저신뢰 87.
- 미배정 상세합 2,734,540원, 엔진 격리 상세합 1,478,413원으로 기존 집계와 일치.
- 동일 DB 반복 실행 semantic SHA-256 일치, 비교 결과 added/resolved 전부 0.
- 배분대상별 합계와 계정별 합계가 각각 결제 총액 310,719,899원과 일치.

### 3. 실행
```bash
python3 ledger/domain/ledger_db.py review-snapshot \
  --output ledger/data/review-snapshots/baseline

python3 ledger/domain/ledger_db.py review-snapshot \
  --output ledger/data/review-snapshots/after-p1 \
  --compare-to ledger/data/review-snapshots/baseline
```

### 4. 다음 단계
P1에서 `high_confidence_uncertain_rationale.csv` 196건을 문구·규칙별로 묶고,
상 신뢰도 허용조건을 충족하지 않는 판정을 `needs_review`로 새 버전 생성한다.
## 2026-07-25 세션 핸드오프 — v2 P0.5~P6 완료·전환 게이트 통과

- 작업 브랜치 `codex/pr8-plan-hardening`에서 최신 Drive 원장과 OTA/퇴사자 원천을
  다시 적재했다. 최신 기준선은 결제 1,833건·320,115,617원이며 원장 해시는
  `76E839C5C001F67D8CB94A266B9F0E42EFF5164E93591163D15B474B6B37FA56`다.
- P0.5: 안정 카드 이벤트 ID, 버전 원장, OTA 허용목록 개인정보 제거, 금액 대사,
  기간 정밀도, DB 백업·복원과 빈 DB 재생성을 구현했다.
- P1: 고신뢰·불확실 결제 203건의 판정 1,015개를 버전 교체했다. 49건 확정,
  154건은 중/검토필요로 낮췄고 잔여 충돌은 0건이다.
- P2: 최신 미연결 환불 15건을 조회기간 밖 10건과 자료부족 5건으로 설명했다.
  원인 없는 미연결은 0건이며 환불 이벤트는 모두 보존한다.
- P3: 미배정 19건을 전부 검토사유로 분류했고 쓰루오카 18,755원 1건만
  `0625_아키타`로 확정 이동했다. 나머지는 정산/중복대기 9건, 근거부족 9건이다.
- P4: 공급자 unknown 98건 중 가맹점 실증 44건을 확정했다. 잔여 54건은 번호
  형식만으로 단정하지 않고 사유 있는 검토상태로 유지한다.
- P5: 저신뢰 87건은 전부 자동전기 차단, 0원 9건은 취소 표현으로 비용인식 0원을
  확정했다.
- P6: 카드 RAW 5,237행·수기 1,379행·OTA 1,720행 직접 적재가 멱등임을 확인했다.
  병렬 워크북은 1,833행·320,115,617원이며 legacy와의 유일한 금액 차이
  18,755원 이동은 의도된 P3 개선이다. 전환 게이트 7개 모두 통과했다.
- **운영 전환은 아직 하지 않았다.** 사용자 승인 전까지 기존 v14/v76이 정본이다.
  게이트 결과는 `ledger/baselines/p6_transition_gate_report.json`, 전체 계획과
  단계별 결과는 `docs/비용분류_v2_정합성개선_실행계획.md`를 참조한다.

---

## 2026-07-25 세션 핸드오프 — 하나카드 동일 행 승인·취소 분리

- 하나카드 RAW의 `승인금액`과 `승인취소금액`이 한 행에 함께 있는 경우를 하나의
  0원/취소 행으로 축약하지 않고 `approval`과 `cancellation` 두 불변 이벤트로
  정규화하도록 수정했다. 직접 소스 5,237행은 결제 이벤트 5,328건으로 전개되며,
  동일 원천행과 승인번호로 관계가 유지된다.
- legacy 변환에서 `0원 원행 + 음수 MISC`로 잘못 분리된 전액취소 4쌍
  (10,100원·90,415원·178,948원·357,262원)은 원행의 양수 승인을 새 버전으로
  복원하고 음수 취소와 확정 연결했다. 삭제된 행은 없으며 복구 총액은 636,725원이다.
- 미연결 취소 15건 중 위 4건은 자동 해소됐다. 현재 상태는 조회기간 밖 10건,
  원천자료 부족 1건(`TRIP-0419`)이며 설명 없는 건은 0건이다.
- 여행 미배정 검토 입력은 19건에서 15건으로, 잔여 미배정은 14건으로 줄었다.
  0원 감사 대상은 9건에서 5건으로 줄었다.
- 결제·배분 합계는 모두 320,752,342원이고 행별 배분 불일치는 0건이다.
  과거 누락 복구 636,725원과 아키타 재배분 18,755원은 회귀 보고서에서 별도
  설명되며, 7개 전환 게이트가 모두 통과했다.
- 전체 테스트 29개 통과(223.347초).

---

## 2026-07-25 세션 핸드오프 — Codex Cloud 이전 준비

- `docs/CODEX_CLOUD_HANDOFF.md`를 신설해 PR #8/#9 전체 변경, v2 아키텍처,
  하나카드 승인·취소 복원, 검증값, 재현 명령, 보안·OAuth 조건을 한 문서로 정리했다.
- `AGENTS.md` 시작 순서에 Cloud 인계서를 추가했다.
- PR #8과 #9는 순서대로 `main`에 병합 완료했다. merge commit은 각각
  `2882af5`, `7cf6070`이며 `feat/domain-separated-ledger-model`,
  `codex/pr8-plan-hardening` 원격 브랜치를 삭제했다.
- PR #7은 최신 원장·워크북 파이프라인 변경 17개가 있는 별도 계보다. v2의
  “승인·취소 모두 보존” 원칙과 PR #7의 과거 “승인취소 스킵” 구현을 조정해야 하므로
  자동 병합·삭제하지 않는다.
- PR #5는 충돌 상태의 draft이며 PR #7과 완전 포함 관계가 아니다. Cloud 세션에서
  고유 변경을 대조한 뒤에만 종료·브랜치 삭제한다.
- Cloud 세션 첫 진입점은 최신 `main`의 `AGENTS.md` → `LOG.md` 최신 블록 →
  `docs/CODEX_CLOUD_HANDOFF.md` 순서다.

---

## 2026-07-25 세션 핸드오프 — 코드 구조 파악·브랜치 기준 정리

- 루트 README의 오래된 `STATUS.md` 우선 안내를 공통 진입점인 `AGENTS.md` 우선으로
  교정하고, Apps Script·레거시 비용분류·v2 도메인 경로를 구분했다.
- `docs/REPOSITORY_STRUCTURE.md`에 디렉터리별 책임, 운영 정본과 v2 병렬 경로의 경계,
  재현 명령, 브랜치 생성·병합·삭제 기준을 기록했다.
- GitHub 관리자 인증 후 PR #5/#7을 감사했다. 두 PR 모두 최신 `main`과 충돌하며
  고유 변경이 남아 있어 자동 병합하지 않았다.
- PR #5 tip `c3751a3`은 `archive/pr-5-pre-cleanup`, PR #7 tip `47a1761`은
  `archive/pr-7-pre-cleanup` 태그로 원격 보존했다. 각 PR에 감사 근거를 남기고 닫은
  뒤 두 원격 작업 브랜치를 삭제했다. 기존 장기 draft PR은 0개이며, 감사 문서 변경은
  `chore/repository-structure` 브랜치의 PR #11에서 검토한다.

---

## 2026-07-29 (이어서) — origin/main 통합·APA 귀속 반박검증·원문 색인 사고

### 1. 브랜치 통합 완료
`codex/linux-migration-2026-07-27` ← `origin/main` 병합(커밋 `67b95fb`). 이제 origin/main 대비 0 behind.
충돌 16건 해소 근거는 병합 커밋 메시지 참조. 요지:
- **HEAD 채택**: `classified_v13/v14.csv`(main의 상위집합 — 하나카드 취소 2건 추가) ·
  `ota_event_links_verified.json`(75) · `ledger_current/latest.xlsx`(48시트 9,424행 vs main 43시트 8,688행,
  SHA `cea581d1…`가 LOG 기록 Drive 다운로드본과 일치) · `manual_periods.csv`(기간표기 보존).
- **main 채택**: `ledger/domain/*`(ledger_db.py 3,161행) · `tests/test_domain_ledger.py` ·
  `docs/비용분류_v2_정합성개선_실행계획.md`.
- **양쪽 병합**: `.gitignore`(합집합) · `AGENTS.md` · `LOG.md`(세션기록 18개 전부) ·
  `manual_v3/v4.csv`(HEAD 기반 + main의 고마가네 예약번호 `1400824130566434` 7건 보강) ·
  `cardindex.py`(main의 `raw_record_id`·`approval/cancel/purchase_amount` + HEAD의 `build_trip_cards()` 복원).
  ★`cardindex.py`는 단순 택일 불가였다 — main 버전은 `build_trip_cards()`를 삭제했는데
  `build_v13_trip.py`·`test_cardindex.py`가 의존하고, main의 하나 G/H 가드 완화(`len(r)>17`)는
  같은 블록의 `r[18]`(부가세) 접근과 충돌해 IndexError 위험이 있어 `>18`을 유지했다.

### 2. APA 귀속탭 — 반박검증 절차 결과: `0424_알펜루트`
사용자 지시로 fable과 gpt-5.6-sol(high)에게 **동일 근거 브리프**로 1차 판정 → 상호 반박 라운드를 거쳤다.
- 1차: 양측 독립적으로 `0424_알펜루트`.
- 반박 라운드(아오모리 지지 논거를 실제로 구성해 공격): 양측 모두 **결론 유지**.
  fable 확신도 **상**, gpt-5.6-sol 확신도 **중**.
- 채택된 핵심 근거: ① 수기 4행 합계 2,287,848이 카드 합산청구와 1원 단위 일치, ② 명시 숙박일
  `0426_0428`이 알펜루트 탭 조밀구간(4/24~29) 내부이고 아오모리 탭 활동 종료 이후, ③ 4/26 당일 동반거래가
  겐로쿠엔·카타마치·몽벨 다테야마 등 전부 알펜루트 권역.
- 기각된 반박: 선결제/후결제론(숙박일이 명시돼 무력), 순환논증 지적(수기 기재를 빼도 ②③만으로 성립),
  아오모리 연장코스설(두 팀 동시운행이라는 미입증 가정 필요).
- 남은 유일한 실질 반박은 전표 note의 `⇄수기[0417_아오모리]` **과거 대사 이력**이며, "수기장부는 정정됐는데
  카드 귀속이 따라가지 못한 잔재"라는 더 단순한 설명이 있어 결정력이 없다고 판단했다.
- **뒤집기 조건(양측 공통)**: Agoda 예약 4건(`1721756989`·`1721758806`·`1721757952`·`1721761805`)의
  호텔 지점이 아오모리로 확인되면 즉시 번복. 로컬 Gmail 색인에는 이 4건 메일이 **0건**이라 현재 반증 불가 —
  Agoda 사이트 대사(인계서 §4-3) 때 최우선 확인 항목으로 남긴다.
- 부수 확인 필요: 같은 날 별건 `APAHOTEL` 279,916원도 동일 논리의 오분류 후보다(본건 결론에는 영향 없음).

### 3. ★사고 — 로컬 원문 Gmail 색인 덮어쓰기
`ledger/data/ota_mail_index.json`은 우리 브랜치에서 **미추적(gitignore)** 이었으나 `origin/main`은 같은 경로에
**편집본을 추적**하고 있었다. gitignore는 추적 파일을 보호하지 않으므로 병합이 로컬 원문본을 덮어썼다.
- 이전 29,054,822 bytes(2026-07-25 02:59, `rawText` 포함) → 현재 903,658 bytes(`rawText` 0건, `redactionVersion` 보유).
- 레코드 수는 양쪽 모두 1,720건. **손실분은 메일 본문 원문(rawText)뿐**이고 예약번호·PNR·여행일·금액 메타데이터는 남았다.
- 영향: 감사의 `evidenceContainsBooking`이 rawText를 요구해 전건 실패 → HOLD 9 → 16.
  늘어난 7건은 이미 병합된 링크(`rowFound`/`mailFound`=true, `existingLinkConflict`=false)로 링크 자체는 정상이다.
- **구조 수정(커밋 `dbf931d`)**: 원문본 경로를 `ledger/data/ota_mail_index.raw.json`으로 분리·gitignore 추가.
  `tools/ota-mail-batch.mjs`가 그리로 기록하고(하드코딩 repoRoot도 `import.meta.url` 유도로 교체),
  `audit-ota-reconciliation.mjs`·`reconcile_ota_index.py`는 `.raw.json` 우선·편집본 폴백.
- **복구 경로**: ① OneDrive 버전 기록(저장소가 `D:\OneDrive\문서\AX\cost` 아래라 이전 버전 복원 가능)에서
  29MB본을 되살려 `ota_mail_index.raw.json`으로 저장, 또는 ② `tools/ota-mail-batch.mjs` 재실행(업무계정 Gmail 필요).
  복구하면 HOLD는 9로 돌아온다.

### 4. 정정 — 하드코딩 Windows 경로
앞 블록에서 "하드코딩 경로 0건"이라 적은 것은 grep 이스케이프 오류였다. 실제로는 **`tools/` 8개 파일에 존재**한다
(`ledger`·`tests`에는 없음): `analyze_hana_xls_3_5.py`·`reparse_hana_q1q2_events.py`·`revalidate_hana_q1q2.py`의
`D:\DownLoad`, `google-workspace-mcp-*.mjs`·`ota-email-extract.mjs`·`ota-mail-batch.mjs`의
`C:\Users\kkokk\...`(MCP SDK·OAuth 경로). `ota-mail-batch.mjs`의 repoRoot만 이번에 교체했고 나머지는 미처리다.
Windows에서 계속 작업하는 동안은 동작하나, 이식 시 정리 대상이다.

---

## 2026-07-29 (이어서 2) — APA 합산청구 정정 완료·잔여 후보 전수확인

### 1. APA 가나자와 처리 완료 (커밋 `9e86dd5`·`1edc1da`)
사용자 확정안(수기 4행 유지 + 합산청구 연결)과 반박검증 판정(`0424_알펜루트`)을 그대로 반영했다.
- 누락 3건 `APA-1721758806`·`APA-1721757952`·`APA-1721761805`를 `manual_special_rows.json`에 추가하고
  `patch_v14.py`의 `RESTORE`로 복원. `1721756989`는 엔진이 `TRIP-0166`으로 이미 편입.
- 합산청구 카드이벤트 `KBO-2755`는 **삭제하지 않고** `krw=0`·`status=합산청구_연결`로 두고
  원 청구액·외화를 `extra`(`card_krw=2287848;foreign=241920.0 JPY`)에 보존(불변규칙 1).
- 귀속 탭은 분해행·합산행 모두 `0424_알펜루트`로 통일.
- 결과: **1,835행/320,055,642원 → 1,838행/319,483,680원**(차 -571,962 = 제거된 초과계상).
  APA 그룹 계상 = 571,962×4 = 2,287,848로 카드 합산청구와 정확히 일치(이중계상 0·초과계상 0).
- 예약 4건을 중앙 링크파일에 가드 병합(**75 → 79**, overwrite 0). agoda 확정 6 → 10.
- 회귀테스트 `ledger/test_apa_combined_billing.py` 5건 신설(수기 마스터 4행 존재 · 예약별 정확히 1행 ·
  합산행 미삭제 및 금액 0 · 그룹 계상액 일치 · 탭 통일). 전체 **24 passed, 10 subtests**.

### 2. 엔진 일반수정을 하지 않은 근거 (중요)
`build_v13_trip.py`의 skip 블록(`sd>=2026-04-01 and not is_prepay` → "base에 이미 존재"로 간주)을
일반 수정하려 했으나, 같은 조건에 걸리면서 **예약번호를 보유한**(=base 부재가 입증되는) 수기행을
전수 조사한 결과 **19건 중 APA 4건 외 15건은 누락 0건**이었다. 15건 모두 이미 다른 uid로 표현돼 있다
(예: `1720063662`→`CORP-2010/2012`, `5973810974`→`CORP-2007`, `F3KVR6`→`KBD-0806`).
일반 수정을 했다면 8,982,009원을 무분별 편입해 새 이중계상을 만들었을 것이다.

**근본 패턴**: 이 skip이 실패하는 것은 **합산청구**(카드 1건 ↔ 수기 N행)일 때뿐이다. 개별 수기행 금액이
카드 승인액과 매칭될 수 없기 때문이다. 앞으로 같은 증상이 보이면 "수기 N행의 합 = 카드 1건 금액"을
먼저 검산하라. 지금까지 확인된 합산청구는 APA 가나자와 1건이다.

### 3. 남은 확인 항목
- 같은 날(4/26) 별건 `KBO-2754` APAHOTEL 279,916원은 여전히 `0417_아오모리`다. 두 판정자 모두
  동일 논리의 오분류 후보로 지목했으나 본건 결론에는 영향이 없어 미변경으로 뒀다. 대응 수기행·지점 확인 필요.
- APA 4건의 Agoda 예약확인서(호텔 지점)는 반박검증 판정의 **유일한 뒤집기 조건**이다.
  로컬 Gmail 색인에 해당 메일 0건 → Agoda 사이트 대사 때 최우선 확인.

---

## 2026-07-29 (이어서 3) — 원문 Gmail 색인 전량 복구

### 1. 복구 완료 — 부분이 아니라 1,720건 전량
OneDrive 버전 기록·섀도 복사본·휴지통은 모두 막혔거나 비어 있었다(`vssadmin`은 권한 부족,
`D:\OneDrive` 15MB 초과 JSON 스캔 0건, OneDrive 로컬 캐시에 파일 저장소 없음).
대신 **원문본이 git object DB에 blob으로 남아 있어** 거기서 추출했다.
- blob `fab411ff21bc31701777368562fcd52695d81a27`, **29,054,822 bytes**(유실 전 크기와 정확히 일치).
- `ledger/data/ota_mail_index.raw.json` 으로 복원(임시파일 → 원자적 rename → read-back).
- 실측 검증: `generatedAt` `2026-07-24T17:59:44.511Z` · 레코드 **1,720** · `rawText` 보유 **1,720/1,720** ·
  고유 messageId 1,720 · 편집본 messageId 중 원문본에 없는 것 **0건**(완전 포함).
- `git check-ignore` 로 무시 확인, `git status` 청결 — 커밋하지 않았다.
- **감사 HOLD 16 → 9 복귀.** 오탐이던 7건(TRIP-0039/0040·KBO-2647/2650/2651/2705/2706) 전부 소멸.

### 2. ★정정 — 원격 노출은 없다
복구 과정에서 "원문본이 커밋 `e894aa1`에 들어 있어 원격 push 시 개인정보가 노출된다"는 보고가 있었으나
**사실이 아니다**. 직접 검증한 결과:
- `e894aa1:ledger/data/ota_mail_index.json` 의 실제 blob은 `2384364e`, **874,515 bytes(편집본)** 다.
- 29MB blob `fab411ff` 가 도달 가능한 ref는 **`refs/codex/turn-diffs/captures/…` 로컬 캡처 ref 하나뿐**이다.
- `origin/main` 및 모든 `refs/remotes/*` 에서 도달 불가 — **원격에는 원문이 없다**.
- 따라서 히스토리 재작성은 불필요하다. 원격에 있는 것은 `rawText` 없는 편집본이다
  (다만 편집본에도 subject·예약번호·PNR·여행일·금액은 있으므로 이 자체의 공개 범위는 별도 판단 사항).

### 3. 복구 경로의 취약성
`fab411ff` 는 Codex의 로컬 turn-diff 캡처 ref에만 매달려 있다. Codex가 그 ref를 정리하거나 `git gc` 가
돌면 사라진다. **지금은 디스크의 `ota_mail_index.raw.json`(29MB)이 유일한 내구 사본**이므로,
이 파일을 암호화 채널로 별도 백업해 두는 것이 안전하다(인계서 §6 대상 자료).

### 4. 부수 확인
- Agoda 체크포인트 DB(`ota_checkpoints_agoda.db`)는 여전히 스키마만 있고 예약 행 **0건**.
- `reconcile_ota_index.py` dry-run(편집본 기준): autoLinked 0 · ambiguous 281 · unresolved 189.
  원문 복구 후 재평가해야 의미가 있다.

---

## 2026-07-29 (이어서 4) — fixture 갱신·OTA HOLD 3건 해소·감사 보고 정확화

### 1. 도메인 fixture 갱신 (인계서 §12-6 이행 완료)
무손실 검증을 마친 뒤에만 기대값을 옮겼다.
- `test_domain_ledger.py`: 1,833행/320,115,617 → **1,838행/319,483,680**.
  도메인 임포터 실측이 CSV와 정확히 일치(transactions=allocations=1,838, 총액 양쪽 동일,
  `allocation_mismatches` 0, `valid` True).
- `test_p6_adapters.py`: `direct_records` 8,336 → **8,337**.
  구성 실측 = cards 5,237 + manual 1,380 + ota 1,720. **+1은 origin/main 병합 때 채택한
  `manual_v4` 한 행(0404_에히메 커피빈 10,500원)**이다(우리 1,380 vs main 1,379).
  APA 정정과는 무관하다 — APA 행은 `classified_v14` 소속이라 `direct_source_records`에 안 들어온다.
- 두 파일 모두 갱신 근거를 코드 주석으로 남겼다.

### 2. OTA HOLD 9건 개별 재검토 → 3건 해소 (링크 79 → **82**)
원문 색인 복구 후 수기장부 마스터와 원문 메일을 대조했다.
- **해소**: `KBO-2645`(847,256 Nezame 예약6475326931) · `KBO-2646`(278,865 Nezame 예약6635102370)
  — 수기 r34/r35 예약번호와 카드 note 기존 기재가 일치하고 동액 카드이벤트가 없어 교집합 유일.
  `CORP-2007`(1,181,775 Hiratakan 예약5973810974) — 수기 r159 예약번호를 **Gmail 원문 5건이 본문에서 참조**
  (2026-04-18~23, 4/20 "결제가 완료되었습니다"). **인계서 §3 HOLD #9의 "예약번호도 대응 메일도 없음"은 뒤집혔다.**
- **유지 6건**: 트립닷컴 부분환불 3건(거래단위 환불증빙 필요) ·
  `KBO-2648`/`KBO-2649`/`KBO-2652` 각 150,970(네자메 ¥15,510 동일가 4실 중 카드이벤트 3건에
  알려진 예약번호는 `6851343288` 하나뿐 — N:M 충돌, 불변규칙 3에 따라 자동확정 금지).

### 3. 감사 도구 보완 — HOLD 해소 반영
`audit-ota-reconciliation.mjs`는 정적 체크포인트 파일의 HOLD를 그대로 보고해, 이후 중앙 링크가 생겨
해소된 건도 계속 HOLD로 세고 있었다. 이제 중앙 링크와 대조해 분리 보고한다:
`hold_records`(미해소) · `hold_records_declared` · `hold_records_resolved_by_central_link`.
목록에서 지우지 않고 `02b_holds_resolved_by_central_link.json`으로 남겨 추적 가능하게 했다.
현재 **미해소 6 · 선언 9 · 해소 3**.

### 4. reconcile_ota_index 재평가 결과
원문 색인 복구 후에도 dry-run 수치는 동일하다(autoLinked 0 · ambiguous 281 · unresolved 189).
이 스크립트의 점수 산정은 **메타데이터(subject·bookingRefs·amounts·travelDates)만 쓰고 `rawText`를
보지 않기** 때문이다(원문을 쓰는 것은 감사 도구뿐). 잔여 281건을 진전시키려면 rawText 기반 대사기가
필요하다 — 다음 세션의 실질 과제다.

### 5. 인계서 정정
`docs/CODEX_LINUX_MIGRATION_HANDOFF_2026-07-27.md` 최상단에 "동결본이며 수치는 갱신됨" 경고와
현재 수치 대조표를 넣었다. 본문은 이력 보존을 위해 손대지 않았다.

---

## 2026-07-29 (이어서 5) — 회귀 기준선 교체·`unexplained_differences` 전건 규명

### 1. `test_p6_adapters`의 `unexplained_differences: 4`는 실제 오류가 아니었다
고정 상수를 맞춘 뒤 남은 이 실패는 P0.5 기준선 대비 여행탭·계정 총액 회귀 검사다. 4건 전부 규명했다.

| 차이 | 금액 | 원인 |
|---|---:|---|
| `0417_아오모리` | −2,287,848 | APA 합산청구 정정(탭 이동) |
| `0424_알펜루트` | +1,715,886 | APA 합산청구 정정(+2,287,848 −571,962) |
| `취소환불` | −59,975 | 하나카드 취소 2건 `HAN-9111` −52,954 + `HAN-9112` −7,021 |
| `숙박비` | +4,788 | `resolve_hana_split_cancellations` 보정 **+636,725** + 데이터 변경 **−631,937** |

**숙박비 +4,788은 혼동하기 쉽다.** CSV 기준 숙박비 변화는 −631,937인데 어댑터는 +4,788을 보고한다.
단계별 실측 결과 차이는 전부 `resolve_hana_split_cancellations` 한 단계에서 발생하며 그 단계에서
숙박비가 정확히 +636,725 오른다(다른 계정·다른 단계는 불변):
`CSV 174,464,547 → 임포트직후 174,464,547 → 하나분리후 175,101,272 → p1~p5후 175,101,272`.
이는 하나카드 동일 RAW 행의 승인·취소를 분리 보존하는 **기존 보정**이며 버그가 아니다.
`regression_report`도 `hana_legacy_correction`으로 이 보정을 알지만, **보정분과 실제 데이터 변경이
섞인 차이**는 단순 등식 비교로 분류하지 못해 `v2_error`로 떨어뜨린다. 분류기의 한계다.

### 2. ★구 기준선은 "APA 누락 상태"를 정답으로 고정하고 있었다
`p05_latest_20260725`의 `0424_알펜루트` 값 **49,990,557**은, 사용자가 인계서 §9.10에서
"사본에 APA HOTEL 3건 / 1,715,886원이 빠졌다"고 지적한 **49,990,561**과 같은 상태다.
따라서 구 기준선에 면제 규칙을 덧대 `unexplained_differences`를 0으로 만드는 것은
**잘못된 상태를 영구화**하는 선택이므로 하지 않았다.

### 3. 조치 — 기준선 교체(구본 보존)
`write_review_snapshot(..., compare_to=p05_latest_20260725)`로 새 기준선
**`ledger/baselines/p07_apa_corrected_20260729/`** 를 생성했다(불변규칙 9: 같은 이름 덮어쓰기 금지).
- 구 기준선은 **삭제하지 않고** 그대로 둔다.
- `diff.json`에 구본 대비 변경이 기록된다(semantic sha `088eac3f…` → `99f2fd8c…`).
- 차이는 위 4건 + 구 분류기도 이미 인정하던 2건(`0625_아키타` +18,755 `intended_improvement`,
  `여행_미배정` +617,970 `legacy_error_correction_and_intended_improvement`) = 총 6건이며 전건 규명됐다.
- 근거·재생성 방법·숙박비 분해는 새 기준선 폴더의 `README.md`에 적었다.
- `test_p6_adapters.py`가 새 기준선을 보도록 바꾸고 전환 근거를 코드 주석에 남겼다.

### 4. 정정 — 앞서 "테스트 격리 결함"이라 한 것은 틀렸다
`test_import_is_idempotent_for_same_snapshot`이 전체 스위트에서만 실패한 원인은 origin/main 테스트의
격리 결함이 아니라, **내가 스위트 실행 중에 `patch_v14.py`를 돌려 `classified_v14.csv`를 덮어쓴 것**이다.
`setUpClass`가 읽은 스냅숏과 테스트가 다시 읽은 스냅숏이 달라져 `repeated_snapshot`이 깨졌다.
`test_domain_ledger.py` 단독 실행은 **22 passed**로 통과한다.
**교훈: 도메인 스위트가 도는 동안 `ledger/data/` 를 건드리지 마라.**
