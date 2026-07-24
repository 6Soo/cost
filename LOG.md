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

### 3.1 [2026-07-24 추가발견] 정본화 직후 발생했던 회귀 — 수정 완료
저장소 정본화(위 §1) 당시 데이터는 `ledger/data/`로 옮겼는데 후속 스크립트 4개
(`build_workbook_v76.py`·`gen_april_rev.py`·`gen_mayjun_rev.py`·`consolidate_2q.py`)는
실수로 `ledger/` 루트에 남겨뒀다. 이 스크립트들은 상대경로로 파일을 여는데, `build_workbook_v76.py`는
`booking_info.json`이 없으면 **경고 없이 조용히 빈 딕셔너리로 대체**하는 코드가 있어 — 스크립트·데이터
위치가 어긋난 채 실행하면 예약번호→호텔명·기간 보강(예: "트립닷컴_하시다테 베이 호텔/숙박_0410_0411"이
"트립닷컴"으로 조용히 퇴화)이 통째로 사라지는 회귀가 있었다. **조치**: 스크립트 4개를 `ledger/data/`로
이동(§4 레시피와 실제 위치 일치) + `booking_info.json`·`booking_pins.json`·`trip_flight_links.json`
누락 시 ⚠경고 출력 추가(조용한 실패 방지). 전체 파이프라인 재실행으로 1,705행/310,719,899원, 워크북
전탭합 315,972,035 재현 확인함.

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
