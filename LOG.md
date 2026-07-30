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

## 2026-07-29 포인터 — ★main의 이 파일은 최신이 아니다

**진짜 최신 세션 핸드오프(2026-07-29 세션 종료 블록)는 미병합 브랜치
`origin/codex/linux-migration-2026-07-27` 의 `LOG.md` 맨 아래에 있다**
(origin/main 대비 branch-only 26 / main-only 0, tip 2026-07-29; local main
`a0b46cf` 대비 branch-only 26 / main-only 1). 새 세션은 반드시
`git rev-list --left-right --count origin/main...origin/codex/linux-migration-2026-07-27`
및
`git rev-list --left-right --count a0b46cf...origin/codex/linux-migration-2026-07-27`
로 미병합 작업을 확인하고
그 브랜치의 LOG.md 최신 블록을 먼저 읽어라.

주의 — 수치 이원화: main 계열(v2 DB 1,833건·320,752,342원·역사 기준선 p05) vs
브랜치 계열(classified_v14 1,838행·319,483,680원·p07 후보 기준선). p05는 APA
누락 상태의 역사 기준선이며 p07은 fresh provenance manifest와 7-gate report 전까지
전환 기준이 아니다. 두 수치를 섞어 회귀 실패로 오판하지 말 것.
미병합 원격 ref는 총 5개(linux-migration, resolve-all-pending=PR #13 draft,
fix/post-0613-review-and-assignments=PR #12, desktop-migration-2026-07-26,
settlement-integrity-handoff)이나, settlement-integrity-handoff는
desktop-migration의 선조이고 desktop-migration은 resolve-all-pending의 선조다.
따라서 독립 tip은 linux-migration, resolve-all-pending(PR #13),
fix/post-0613-review-and-assignments(PR #12)의 3개이며 자동 병합 금지 — 감사 후
목적 단위 선별 이식은 `docs/브랜치감사_2026-07-29.md`를 참조한다.
이 포인터는 브랜치 통합 시 제거한다.

---

## 2026-07-30 세션 핸드오프 — P07 direct candidate first slice

### 0. 판정

- 작업 브랜치: `codex/p07-canonical-cutover-candidate`
- 구현 전 기준 HEAD: `377d4bf` (`docs: audit canonical cutover branch lineage`)
- 코드 심사: **PASS**
- 실데이터 expected-fail 계약: **PASS**
- 운영 cutover: **FAIL** — `legacy_path_remains_authoritative`
- 외부 push·PR·merge·배포·Drive/Gmail·운영 데이터 변경은 수행하지 않았다.
- 사용자 선행 수정 `STATUS.md`는 건드리지 않았고 SHA-256
  `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`
  를 보존했다.

### 1. 구현

기존 v1/legacy 파일과 데이터·기준선을 수정하지 않고 다음 6개 파일만 추가했다.

- `ledger/domain/direct_projection_schema.sql`
- `ledger/domain/direct_projection.py`
- `ledger/domain/transition_gates_v2.py`
- `ledger/domain/p07_manifest.py`
- `ledger/tests/test_direct_projection.py`
- `ledger/tests/test_transition_gates_v2.py`

핵심 계약:

- 카드 RAW 5개 파일을 직접 결제 후보로 투영하고, 수기장부·OTA는 provenance/evidence로만
  적재한다. manual/OTA가 candidate payment를 생성하지 않는다.
- 7개 물리 입력의 raw/LF/byte/record/key-set/parser hash를 고정하고 경로 이탈·빈 입력·
  중복키·동일키 내용충돌을 실패 처리한다.
- candidate DB는 임시 DB에서 생성·게이트 평가한다. PASS 시에도
  `building DB 설치 → report directory 원자 게시 → DB passed 활성화 →
  manifest candidate_ready_for_shadow 원자 교체` 순서를 지키며, 어느 단계의 예외도
  새 DB·report·WAL/SHM을 롤백한다.
- 소비자 view는 `status='passed'`인 run만 노출한다.
- report self-hash, manifest 입력/code bundle/comparator/파생 상태, PASS DB의 run 상태·
  실제 projection semantic hash·노출 건수를 다시 계산해 교차검증한다.
- Gate 6은 저장소 내부 path/role/raw hash가 검증된 baseline descriptor만 읽지만,
  event-level diff가 구현되기 전에는 그 기준선도 PASS시키지 않는다.

### 2. 모델 라우팅·상호검증

- 고추론 설계·적대검증: Claude Fable 5 medium과 GPT-5.6 Sol medium이 독립 판단 후
  상호 검증·반박·항목별 수용/기각을 수행했다.
- 저추론 구현 라우팅: AGY Gemini 3.6 Flash High는 503으로 사용할 수 없었고,
  AGY Sonnet 4.6도 사용 불가/응답 정지였다. 최종 폴백 GPT-5.6 Luna low가 초기 구현을
  맡았으며, 발견된 결함은 coordinator가 수정하고 Fable/Sol이 다시 적대검증했다.
- 수용한 반례: PASS 게시 원자성, manifest input/code/state/approval/파생값 변조,
  검증되지 않은 3필드 baseline dict, 게시 후 PASS DB business row 변조.
- 기각한 경로: legacy import/FK 재사용, manual/OTA payment 생성, aggregate·magic-number
  승인, 검증되지 않은 baseline PASS, report만 맞고 실제 DB 내용을 재검증하지 않는 방식.
- 최종 독립 판정은 양쪽 모두
  `REVIEW=PASS / REAL_EXPECTED_FAIL=PASS / CUTOVER=FAIL`이다.

### 3. 최종 검증

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  ledger.tests.test_direct_projection \
  ledger.tests.test_transition_gates_v2
# Ran 34 tests — OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s ledger/tests -p 'test_*.py'
# Ran 63 tests in 184.608s — OK
```

코드 동결 뒤 실데이터 실행:

```text
output root                 /tmp/cost-p07-final-freeze.EI6VDi
exit code                  1
input_manifest_sha256      e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199
candidate_semantic_sha256  83019057f38782c44be9187f7d427ed62b47bcda9d419f70b18b04fde334ece9
gate_report_sha256         f15174cc8e036e9d815acb358431337dd8233cee0458d06e165e1a34ca31175f
artifact_state             not_published
candidate DB               없음
Gate 1 source provenance   PASS (7 physical inputs)
Gate 2 projection          FAIL (identity collision 8)
Gate 3 legacy leakage      PASS
Gate 4 amount relations    FAIL (positive cancellation/sign issue 157)
Gate 5 allocation/decision FAIL (unresolved 5,328)
Gate 6 semantic regression FAIL (direct baseline unavailable, integrity true)
Gate 7 report freshness    PASS
```

`git diff --check`, Python compile 검증, 기존 data/baseline/runtime 파일 무변경 대조도
통과했다.

### 4. 다음 우선순위

1. identity collision 8건의 원천키·이벤트 ID 생성 규칙을 행 단위로 분석하고 수정한다.
2. positive cancellation/sign issue 157건의 카드사별 원천 부호 의미를 확정한다.
3. direct candidate 5,328건의 allocation/decision을 event lineage 기반으로 구현한다.
4. 승인 계보(`approved_by/approved_at/source_run_id`)가 있는 direct event-level baseline과
   strict event-key diff/approval을 구현한다.
5. 네 blocker가 모두 해소되고 동일 7-gate·artifact 검증이 다시 통과하기 전에는
   legacy 경로를 정본으로 유지한다.

---

## 2026-07-30 세션 핸드오프 — 원격 브랜치 R6 정리

### 0. 실행 결과

- P07 작업 커밋 `8cdab8e`는
  `origin/codex/p07-canonical-cutover-candidate`에 push 완료했다.
- `codex/settlement-integrity-handoff`(`9ee6866`)는 annotated tag
  `archive/pre-unify-settlement-9ee6866`을 먼저 원격에 push하고 peeled SHA가
  `9ee6866d09dad0d15471fb22fd59e73bf9b96679`인지 확인한 뒤 원격 브랜치를 삭제했다.
- `codex/desktop-migration-2026-07-26`(`0aa4fd9`)도 annotated tag
  `archive/pre-unify-desktop-0aa4fd9`의 peeled SHA
  `0aa4fd9dbf258f22398cf3a8e6098bdfb6b75071`을 원격에서 확인한 뒤 삭제했다.
- 두 삭제 브랜치는 열린 PR, check run, deployment가 없었고,
  `settlement ⊂ desktop ⊂ resolve-all` 조상관계를 삭제 직전에 다시 확인했다.
- 남은 원격 작업 브랜치는 4개다:
  `linux-migration`(`9379850`), `resolve-all-pending`(`53ef5c8`, PR #13 draft),
  `fix/post-0613-review-and-assignments`(`2a7aa3a`, PR #12),
  `p07-canonical-cutover-candidate`(R6 문서 커밋의 parent code checkpoint `8cdab8e`).

복구가 필요하면 exact SHA를 기존 ref로 push한다.

```bash
git push origin \
  9ee6866d09dad0d15471fb22fd59e73bf9b96679:refs/heads/codex/settlement-integrity-handoff
git push origin \
  0aa4fd9dbf258f22398cf3a8e6098bdfb6b75071:refs/heads/codex/desktop-migration-2026-07-26
```

### 1. 브랜치별 검증 판정

- `fix/post`: 독립 archive에서 31/31 PASS(236.175초). 고유 guard·정책 목적이 남아 유지.
- `linux`: 29개 중 1개 FAIL. `KBD-1046` 여행자보험 8,110원이 최신 보험기간 근거로
  `기타비용 → 0613_북해도` 이동했지만 p07 회귀 기준선은 이동 전 상태라
  `unexplained_differences=2`가 됐다. magic amount 면제가 아니라 event-level evidence와
  승인 계보 또는 귀속 원복으로 해소해야 한다.
- `resolve-all`: 테스트 메서드 258개 전수 실행이 제한시간 안에 끝나지 않아
  PASS로 판정하지 않았다. 고유 receipt/evidence/foundation 목적이 남아 유지.
- `p07`: 실제 Git worktree에서 기존 targeted 34/34·전체 63/63 PASS.
  운영 cutover는 계속 FAIL이고 legacy 경로가 정본이다.

### 2. Fable/Sol 상호검증 합의와 다음 순서

- Claude Fable 5 medium과 GPT-5.6 Sol medium은 독립 감사 후 상호 반박해
  `삭제 2 / 유지 4 / whole-branch merge 금지`에 합의했다.
- 기존 P07 브랜치를 유일한 control branch로 유지한다.
- 목적별 이식 순서는 `resolve foundation → fix/post guards →
  linux evidence/tools → P07 code-final`이다. 각 단계에서 P07 code bundle,
  input manifest, semantic hash, 7 gates를 다시 계산한다.
- P07 draft PR은 두 검토의 의견이 갈렸고, 이번 사용자 지시는 push·브랜치 정리가
  중심이므로 생성하지 않았다. main merge와 cutover도 수행하지 않았다.
- 사용자 변경 `STATUS.md` SHA-256
  `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`를 보존했다.

---

## 2026-07-30 세션 핸드오프 — R7 승인 봉투 보강·브랜치 검증

### 0. 반영 결과

- 통합 control branch `codex/p07-canonical-cutover-candidate`에
  `abdd5a0`(`fix: harden p07 approval envelope`)을 반영했다.
- 변경 범위는 `ledger/domain/transition_gates_v2.py`와
  `ledger/tests/test_transition_gates_v2.py` 두 파일뿐이다.
- direct event-level 승인 입력은 13개 필수 필드, 단일 안정 event key,
  lowercase SHA-256 7종, source run/candidate semantic 결합, 중복 소비 금지,
  known-offset 승인 시각을 모두 만족해야 한다.
- `transition_id`와 lineage hash의 길이·non-hex·대문자, legacy event key,
  0/2개 event, stale run, wrong candidate hash, duplicate transition/event,
  supersession, 불가능한 날짜·시간을 fail-closed로 거부한다.
- 승인 시각의 숫자 offset은 시 00~23·분 00~59로 제한한다. RFC3339 문법상
  offset 미상을 뜻하는 `-00:00`도 accountable approval lineage에서는 거부하고,
  `Z`·`+00:00`·`±23:59`는 허용한다.
- 완전한 승인 봉투가 있어도 event-level baseline diff가 미구현이면 Gate 6은
  `direct_baseline_event_diff_unimplemented`로 FAIL한다. baseline 자체가 없으면
  승인 1건을 검증한 뒤에도 `direct_baseline_unavailable`로 FAIL한다. 새 PASS 경로는 없다.

### 1. 모델 라우팅·상호검증

- 설계·검증은 Claude Fable 5 medium과 GPT-5.6 Sol medium이 독립 검토 후
  상호 반박했다.
- 최초 구현의 비해시 `transition_id`, 달력 검증 없는 timestamp,
  잘못된 supersession 필드와 owner-test 누락은 두 모델의 반려를 수용해 보완했다.
- 1차 보완 후 Fable은 PASS였으나 Sol이 `+09:60`이 Python 파서에서
  `+10:00`으로 정규화되는 반례를 찾았다. Fable이 이를 직접 재현해 기존 PASS를
  철회했고, 두 모델은 offset 범위 제한과 `-00:00` 거부를 수용했다.
- 최종 재심사는 양쪽 모두 `REVIEW=PASS`; 남은 기각 항목은 없다.
- 저추론 구현은 AGY Gemini 3.6 Flash High를 먼저 호출했으나
  `GEMINI_API_KEY` 부재로 추론 전에 실패했다. AGY Sonnet 4.6 호출 수단도 없어
  최종 폴백 GPT-5.6 Luna low가 두 파일을 구현·보완했다.

### 2. 검증

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  ledger.tests.test_transition_gates_v2
# Ran 29 tests — OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s ledger/tests -p 'test_*.py'
# Ran 75 tests in 146.394s — OK
```

`git diff --check`, Python compile, 88자 초과 신규 행 검사도 통과했다.

control commit에서 실데이터를 다시 실행한 결과:

```text
output root                 /tmp/cost-r7-control.mGMm7f
exit code                  1
code_commit                abdd5a0148b4b3022ce0ab7ae89dc13ca0549d34
code_bundle_sha256         fc4bd152064384bad3b961dc5f3a57eb655320ffa4068c0600d5fce2111eeab3
input_manifest_sha256      e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199
candidate_semantic_sha256  83019057f38782c44be9187f7d427ed62b47bcda9d419f70b18b04fde334ece9
gate_report_sha256         982b335b2819f77d61a5b4ebcf05a86c4e8b77056a660be98d88b39877c43895
artifact_state             not_published
candidate DB               없음
Gate 1 source provenance   PASS (7 physical inputs)
Gate 2 projection          FAIL (identity collision 8)
Gate 3 legacy leakage      PASS
Gate 4 amount relations    FAIL (sign issue 157)
Gate 5 allocation/decision FAIL (unresolved 5,328)
Gate 6 semantic regression FAIL (direct baseline unavailable, integrity true)
Gate 7 report freshness    PASS
```

따라서 `REAL_EXPECTED_FAIL=PASS / CUTOVER=FAIL`이며
`legacy_path_remains_authoritative`를 유지한다.

### 3. 남은 브랜치 판정과 다음 순서

- `resolve-all-pending` tip의 실제 전수 실행은 258 tests 중
  failures 2·errors 7로 FAIL했다. 7 errors는 미커밋
  `ledger/data/ota_mail_index.json` 및 OTA checkpoint DB 의존이 주원인이고,
  `test_legacy_verified_link_import` 2건은 기대한 `conflict`/match와 실제
  `proposed`/unavailable가 불일치한다. whole-branch 이식 금지를 유지한다.
- 남은 목적별 순서는 `resolve foundation의 재현 가능한 최소 단위 →
  fix/post guards → linux evidence/tools → P07 code-final 재검증`이다.
- `KBD-1046` 8,110원은 event-level evidence와 승인 계보가 완성되기 전에는
  승인하지 않는다. `KBD-0380` 163,788원의 후속 행사 분할은 사용자 선택 2번을
  보존하지만, 비율 근거가 확정되기 전에는 데이터 변경하지 않는다.
- 사용자 `STATUS.md` SHA-256
  `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`
  를 보존했다.

---

## 2026-07-30 세션 핸드오프 — R8 resolve 최소 목적 이식

### 0. 반영 결과

- 통합 control branch `codex/p07-canonical-cutover-candidate`에
  `c100da5`(`feat: add scoped JPY receipt validation`)을 반영했다.
- `origin/codex/resolve-all-pending`의 receipt 목적을 전체 cherry-pick하지 않고
  다음 3개 파일로 재구현했다.
  - `ledger/receipt_pipeline/__init__.py`
  - `ledger/receipt_pipeline/validator.py`
  - `ledger/tests/test_receipt_pipeline.py`
- 실행 범위는 합성 입력 전용 JPY batch v1이다. 통화는 `JPY`, 변환 정책은
  `fixed_convenience_rate`, 환율은 bool이 아닌 정수 `10 KRW/JPY`만 허용한다.
  EUR 등 다른 통화·정책·환율은 조용히 건너뛰지 않고 `ReceiptBatchError`로 거부한다.
- 실제 영수증/OCR/분류 데이터, schema, DB projection, P07 runtime, baseline은
  추가하지 않았다. period-recognition은 A0 여행 귀속과 실제 consumer를 함께
  재설계해야 하므로 이식하지 않았다.

### 1. 검증

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  ledger.tests.test_receipt_pipeline
# Ran 11 tests — OK

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s ledger/tests -p 'test_*.py'
# Ran 86 tests in 143.275s — OK
```

별도 27개 malformed probe는 non-object element, 공백·중복 ID, unknown ref,
under/over bijection, bool/float count·rate, bool/음수 amount, unknown status,
불가능한 날짜, exact-True가 아닌 auto-assignment signal, EUR을 모두 fail-closed로
거부했다. `py_compile`, 신규 행 88자 검사, `git diff --check`도 통과했다.

커밋 상태의 실데이터 P07 재실행:

```text
output root                 /tmp/cost-r8-control.6obsOk
exit code                  1
code_commit                c100da5bd9b8e2f98ea1770599a936755f5e67d1
code_bundle_sha256         fc4bd152064384bad3b961dc5f3a57eb655320ffa4068c0600d5fce2111eeab3
input_manifest_sha256      e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199
candidate_semantic_sha256  83019057f38782c44be9187f7d427ed62b47bcda9d419f70b18b04fde334ece9
gate_report_sha256         12da7789d1492366473d3ac233045894446c9fa521d20100c204ea06b3cb13ca
artifact_state             not_published
candidate DB               없음
Gate 1 source provenance   PASS (7 physical inputs)
Gate 2 projection          FAIL (identity collision 8)
Gate 3 legacy leakage      PASS
Gate 4 amount relations    FAIL (sign issue 157)
Gate 5 allocation/decision FAIL (unresolved 5,328)
Gate 6 semantic regression FAIL (direct baseline unavailable, integrity true)
Gate 7 report freshness    PASS
```

새 receipt package는 아직 P07 consumer가 아니므로 runtime code bundle은 R7과
동일하다. 판정은 `REVIEW=PASS / REAL_EXPECTED_FAIL=PASS / CUTOVER=FAIL`이며
`legacy_path_remains_authoritative`를 유지한다.

### 2. 모델 라우팅·상호검증

- 저추론 구현은 AGY Gemini 3.6 Flash High를 먼저 호출했으나
  `GEMINI_API_KEY` 부재로 추론 전에 실패했다. AGY Sonnet 4.6 callable 수단도 없어
  GPT-5.6 Luna low가 정확히 3개 파일을 구현했다.
- Claude Fable 5 medium과 GPT-5.6 Sol medium은 receipt와 period 후보를 독립 검토한
  뒤 상호 반박했다. 최종 수용안은 receipt 3파일뿐이며, period 2파일 이식과 generic
  FX 일반화는 기각·보류했다.
- 구현 재심 중 Sol은 오래된 NO-PORT 초안을 최신 합의로 오인해 절차상 FAIL을 냈지만,
  그 문서 이후 Sol이 보낸 exact ACCEPT 메시지를 대조한 v2에서 기존 FAIL을 철회하고
  `REVIEW=PASS`, 남은 코드 blocker 없음으로 확정했다.
- Fable 서비스는 파일 대조 뒤 네트워크 재시도 상태가 되어 규칙에 따라 Opus 5 medium이
  대체 검증했다. Opus도 현재 파일과 11/86/27 검증 근거를 독립 대조해
  `REVIEW=PASS`, 남은 blocker 없음으로 판정했다.

### 3. 남은 브랜치와 다음 순서

- 이번 목적 이식만으로 `resolve-all-pending`은 삭제하지 않는다. receipt
  projection/persistence, privacy allowlist, OTA checkpoint/mail evidence,
  reconciliation/source-loss 등 고유 목적과 기존 2 failures·7 errors가 남아 있다.
- 다음 목적 단위는 기존 합의대로 `fix/post guards`다. whole-branch merge가 아니라
  owner test가 있고 P07/원장 정책과 충돌하지 않는 최소 guard만 다시 설계·검증한다.
- 실제 receipt artifact 수집·분류 승인·DB projection은 별도 권한과 provenance
  설계 전에는 진행하지 않는다.
- 사용자 `STATUS.md` SHA-256
  `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`
  를 보존했다.

---

## 2026-07-30 세션 핸드오프 — R9 fix/post 목적 감사

### 0. 반영 결과

- 통합 control branch `codex/p07-canonical-cutover-candidate`에
  `2029077`(`docs: restore p18 p19 ledger policy`)을 반영했다.
- `origin/fix/post-0613-review-and-assignments` tip
  `2a7aa3a4e02c949cf58591dfb0bdf5df88c31cde`에서 P18/P19 사용자 확정 정책만
  standing-instruction 원장으로 복원했다.
- donor 코드, 테스트, CSV, 6월 귀속, note/confidence, baseline,
  regression whitelist, P07 runtime은 이식하지 않았다.
- 최종 목적 판정은
  `DOC PORT / CODE NO-PORT / DATA NO-PORT / BRANCH KEEP`이다.

### 1. 검증·기각 근거

- donor guard는 invalid Decimal을 0으로 취급하고, source key 누락을 통과시키며,
  중복·공백 UID 삭제와 근거 없는 confidence/note/UID tie-break를 허용한다.
- package import에서 bare import가 실패하고, 실제 소비자는 legacy
  `patch_v14.py`뿐이다. P07 Gate 2는 이미 직접 cardinality를 검사하며 현재
  collision 8행은 donor가 겨냥한 KBO 중복이 아니라 Hana 승인식별자 재사용이다.
- donor 정규화 기준 source-missing은 167 key·183행이며 165행은 공란
  `post_date`다. 더 엄격한 fingerprint는 459건이어서 비교 스키마 계약 없이
  fail-closed audit을 배선하면 정상 legacy 빌드가 상시 실패한다.
- ANA/GASUTO projection 중복은 재현했지만 GASUTO 동률은 서로 다른 여행 bucket이라
  자동 삭제할 수 없다. `classified_v14.csv` 총액 `-694,652`, baseline,
  expected total은 바꾸지 않았다.
- 문서 전용 변경이므로 코드 테스트와 P07 실데이터 실행은 반복하지 않았다.
  직전 R8 control 검증 86/86 PASS와 expected-fail 판정을 유지하며
  `git diff --check`와 exact-file 검사를 수행했다.

### 2. 모델 라우팅·상호검증

- 저추론 inventory는 AGY Gemini 3.6 Flash High가 `GEMINI_API_KEY` 부재로
  추론 전 실패했고 AGY Sonnet 4.6 callable 수단도 없어 GPT-5.6 Luna low가
  수행했다.
- Claude Fable 5 medium과 GPT-5.6 Sol medium은 독립 설계 뒤 상호 반박했다.
  Fable은 Sol의 소비자 부재·상시 실패·tie-break 반례를 수용해 guard 즉시 이식을
  철회했고, Sol은 Fable의 standing-instruction 보존 논거를 수용해 P18/P19 문서
  이식에 동의했다.
- 최종 합의는 `DOC PORT NOW; AUDIT DESIGN DEFER; DATA NO-PORT; BRANCH KEEP`이다.

### 3. 보호 상태와 다음 순서

- 사용자 `STATUS.md` SHA-256
  `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`
  와 `AGENTS.md` SHA-256
  `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`
  를 보존했다.
- `classified_v14.csv` SHA-256
  `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`,
  `patch_v14.py` SHA-256
  `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`
  를 보존했다.
- `fix/post-0613-review-and-assignments`는 실패 구현의 반례와 미이식 evidence
  narrative가 남아 있어 유지한다. 삭제를 다시 검토할 때는 tip `2a7aa3a...`를
  immutable recovery ref로 먼저 보존한다.
- 다음 목적 단위는 `origin/codex/linux-migration-2026-07-27`의 portability/tool
  후보 감사다. evidence·생성 데이터·OTA 판정은 whole-branch로 이식하지 않는다.

---

## 2026-07-30 세션 핸드오프 — R10 Linux migration 브랜치 정리

### 0. 반영 결과

- `origin/codex/linux-migration-2026-07-27` tip
  `937985085c95f8136c332b49edb59e29afd65f69`의 26개 고유 커밋을 목적별로
  전수 감사했다.
- 최종 판정은 `CODE NO-PORT / DATA NO-PORT / ARCHIVE-TAG+DELETE`다.
- archive ref는 `archive/pre-delete-linux-9379850`이다. remote peeled SHA를
  exact tip과 대조했고 named Linux branch를 삭제한 뒤 원격 ref 부재를 확인했다.
- 코드, 테스트, CSV, workbook, baseline, P07 runtime은 변경하지 않았다.

### 1. 계보 정정과 NO-PORT 근거

- 초기 inventory가 Linux 후보로 셌던 `ee54757`은 Linux tip에서 도달할 수 없고
  `origin/codex/resolve-all-pending`에만 속한다.
- Linux lineage의 실제 portability commit `a4c9771`이 변경한 9개 파일은 current
  control에 모두 없다. Hana XLS, Google Workspace/Gmail, OTA 도구는 외부 입력,
  자격증명, network, 생성 artifact 또는 판단 state에 결합돼 있어 path hunk만
  신규 반입하지 않는다.
- Linux branch의 보험기간 parser, OTA 대사 chain, 그룹배정 gate, 임의배정 강등
  guard, KBD-1046 8,110원 및 KBD-0380 163,788원 data/evidence도 provenance와
  승인 계보 없이 이식하지 않는다.
- `test_domain_ledger.py`의 동적 expected total은 회귀 기준을 자기 인증하므로
  영구 기각했다.

### 2. 모델 라우팅·상호검증

- 저추론 inventory는 AGY Gemini 3.6 Flash High가 `GEMINI_API_KEY` 부재로
  추론 전 실패했고 AGY Sonnet 4.6 callable 수단도 없어 GPT-5.6 Luna low가
  수행했다.
- Claude Fable 5 medium과 GPT-5.6 Sol medium은 독립 감사 뒤 상호 반박했다.
  Fable은 Sol이 재현한 repo-root `cardindex.load("F")` 실패와 process-global
  CWD 의존을 독립 재현해 latent API 결함을 수용했다.
- 양쪽은 `R10 code scope=None`, exact donor hunk 기각,
  explicit input-root 4파일 재구현을 즉시 R11 resolve 목적 단위로 분리,
  Linux branch는 archive-tag+delete에 합의했다.
- Sol의 current targeted 검증은
  `test_direct_projection + test_p6_adapters` 18/18 PASS였다.

### 3. archive inventory와 복구

archive tag에 다음 미이식 이력이 그대로 보존된다.

- 여행자보험 가입기간 parser와 KBD-1046 8,110원 근거
- OTA 대사 chain, 그룹배정 승격 gate, 임의배정 유래 17건 강등 guard
- KBD-0380 163,788원 미배정과 사용자 선택 2번, 비율·기간 근거 미확정 상태
- Gmail raw index overwrite 사고와 생성 artifact 의존 실패 이력
- Linux/Windows 경로 대안 `a4c9771`

복구 명령:

```bash
git push origin \
  937985085c95f8136c332b49edb59e29afd65f69:refs/heads/codex/linux-migration-2026-07-27
```

`origin/codex/resolve-all-pending`과
`origin/fix/post-0613-review-and-assignments`는 각각 open PR과 미완 목적이 있어
유지한다.

### 4. 보호 상태와 다음 순서

- 사용자 `STATUS.md` SHA-256
  `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`,
  `AGENTS.md` SHA-256
  `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`,
  `classified_v14.csv` SHA-256
  `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`,
  `patch_v14.py` SHA-256
  `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`
  를 보존했다.
- 다음 R11은 `resolve/card-input-root` 목적이다. `ledger/cardindex.py`,
  `ledger/domain/direct_sources.py`, `ledger/domain/direct_projection.py`,
  신규 `ledger/tests/test_cardindex_paths.py`만 접촉하고, parser 의미·data·baseline은
  바꾸지 않는다.

## 2026-07-30 R11 세션 핸드오프 — explicit card input-root

`096127cd3e713b8e2c94883b9ac3f461c0fdc173`은 네 파일만의 R11 구현이다:
`ledger/cardindex.py`, `ledger/domain/direct_sources.py`,
`ledger/domain/direct_projection.py`, `ledger/tests/test_cardindex_paths.py`.
keyword-only `ledger_dir`와 module-root default, 두 consumer의 명시 root forwarding,
process-global `chdir` 제거, workbook `try/finally` close를 포함한다.

검증: targeted `26/26`; full `94/94` (coordinator 147.913s, Fable 153.421s,
Sol 155.434s); py_compile/diff-check PASS. parser는 A/E/F/G/H=`174/1679/1287/221/1876`,
합계 5,237, compact SHA=`e3fb99099f41f46747351e799e7c9e14dbe3b8249b03f143f76bc4fe1684dcc7`.
FD는 GC disabled에서 pre `0→25`, post `0→0`; 최종 Fable/Sol `REVIEW=PASS`다.
AGY Gemini 3.6 Flash High는 GEMINI_API_KEY 부재, AGY Sonnet 4.6은 unavailable,
GPT-5.6 Luna low가 구현·작성했다. 설계·검증은 Claude Fable 5 medium과 GPT-5.6 Sol
medium이 수행했다.

post-commit P07은 exit 1, `code_commit=096127c`, bundle
`6cb1a6bb471dbcbeebbe7c075d31e9a9418fe0a22825e7819694fd836cd8b0ed`, input manifest
`e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199` unchanged,
semantic `83019057f38782c44be9187f7d427ed62b47bcda9d419f70b18b04fde334ece9` unchanged,
report `fb67a8818cda07abe05cc9e5ada86f1bf83bd240f11d1ca1f15aaeeb19dc975c`다.
Gate 1/3/7 PASS; Gate 2/4/5/6은 각각 collision 8/sign 157/unresolved 5328/direct
baseline unavailable(integrity true)로 FAIL했다. artifact `not_published`, candidate DB 없음,
legacy authoritative, `REAL_EXPECTED_FAIL=PASS/CUTOVER=FAIL`이다.

STATUS/AGENTS/classified_v14/patch_v14 보호 hash는 각각
`a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc` /
`3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4` /
`8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989` /
`1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`로 유지한다.

R12 다음 후보는 high review 전 `candidate_selection` pure helper이며, OTA/evidence/data/
schema/DB/policy cluster는 NO-PORT다.

## 2026-07-30 R12 세션 핸드오프 — binding closure

resolve donor tip `53ef5c89261fd182d1711a50cca11279f72d5560`의 후보
`candidate_selection.py`와 `test_candidate_selection.py`는 최종 **NO-PORT / 0파일 /
read-only**로 종결했다. current helper consumer는 없고 donor test 3개는 missing과
bidirectional success를 다루지 않는다. duplicate item key overwrite/reverse-count
undercount의 순서 의존 `missing↔bidirectional_unique`, shared-candidate fail-open,
기본 `id`의 clone 이중선택·memory-address key, 부정확한 동일 TypeVar 서명을 재현했다.
`1a527e7`은 19파일/2,666 insertion 혼합 commit이며 branch deletion leverage도 없다.

향후 binding negative invariants는 donor 원형 재사용 금지, 명시 semantic key 필수,
duplicate item key 무탐지 통과 금지, dedupe-to-unique 금지, 고립된 1:1만 자동선택이다.
consumer·error/status·files 선택은 non-binding이며 owner가 실제 consumer를 정한 별도
review에서 다시 결정한다. Sol/Fable hypothetical spec은 승인 명세가 아니다.

라우팅: AGY Gemini 3.6 Flash High는 GEMINI_API_KEY 부재로 pre-inference 실패,
AGY Sonnet 4.6 unavailable, GPT-5.6 Luna low가 inventory/writing을 담당했다.
Claude Fable 5 medium과 GPT-5.6 Sol medium은 독립 검토·반박 후 binding-only closure를
수용했다. 코드/data 불변이므로 R12 tests/P07 재실행은 없고 R11 94/94와 P07 expected-fail이
최신 code evidence다. PR13 resolve draft와 PR12 fix/post는 open이므로 branch는 유지한다.

STATUS/AGENTS/classified_v14/patch_v14 보호 hash는 각각
`a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc` /
`3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4` /
`8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989` /
`1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`로 유지한다.

## 2026-07-30 R13 세션 핸드오프 — period recognition closure

resolve tip `53ef5c89261fd182d1711a50cca11279f72d5560`의
`period_recognition.py` + `test_period_recognition.py`와 모든 consumer/docs/data는
**NO-PORT / 0파일 / read-only**로 종결했다. control production 참조는 0이고 donor
consumer는 ledger_db/DB/schema/reconciliation/workbook NO-PORT cluster다. helper는
donor-dead이며 donor 3 tests는 통과하지만 integration에는 return 뒤 assertion 두 블록이
있다. `5f36877`은 55파일/17,281 insertion 혼합 commit이고 fixed Q2_CLOSE_ON,
invalid cutoff silent false, compact/week date implicit acceptance, whitespace/type
불일치가 있다. KBD-1029 exact 1,299,640원은 이미 `0827_군산` bucket에 처리됐다.

P18 compatible/insufficient, P19 neutral, A0/P16 authority와 explicit user-confirmed
period policy 원문 부재, R8 defer 유지다. P20–P25는 이번 R13 밖 non-binding 별도
doc-audit 후보다. Flash→Sonnet unavailable→Luna low routing과 Fable 5 medium/Sol
medium 독립·cross 검토를 보존한다. 코드/data 불변으로 재실행은 없고 R11 94/94 및
P07 expected-fail이 최신 evidence다. PR12/13 open branch는 유지한다.

binding verdict **NO-PORT / 0파일 / read-only**. 보호 hash는 STATUS
`a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc` / AGENTS
`3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4` / classified_v14
`8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989` / patch_v14
`1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`로 불변이다.

## 2026-07-30 R14 세션 핸드오프 — policy closure

donor `origin/codex/resolve-all-pending` tip은 `53ef5c89261fd182d1711a50cca11279f72d5560`이며 donor P18/P19와 current P18/P19 번호가 충돌한다. 판정은 donor P18 **DEFER**(P5/P10 포함 OTA evidence hierarchy), P19 **DEFER**(output/publication), P20 **NO-PORT**, P21 **PORT → current P20**, P22 **DEFER**(승인된 OTA checkpoint/runbook), P23 **PORT → current P21**, P24 **NO-PORT**, P25 원문 **NO-PORT + 일반 tail DEFER**다.

donor P21 사용자 확정 원문은 “현지 영수증 사진의 물리 전표 보존(2026-07-26 사용자 확정): 이면지에 부착된 영수증 사진에서 노이즈는 이면지의 다른 인쇄·필기 텍스트이며, 부착된 영수증끼리 중복되는 것은 아니다. 사진에 보이는 각 물리 영수증을 별도 실거래 후보로 보존하고 같은 날짜·가맹점·금액이라는 이유로 병합·제거하지 않는다. 이면지 본문·뒤집힌 문자·양식선은 OCR 배경으로 제외하며, 영수증 수·합계의 전단사 검증 후에만 구조화한다.”이다.
donor P23 사용자 확정 원문은 “현지 영수증의 여행탭 이중검증(2026-07-26 사용자 확정): 사진 최상단의 지역명·기간을 기존 장부 탭명과 유사도 매칭해 1차 여행 후보로 삼고, 각 물리 영수증의 날짜·가맹점 지역을 2차로 대조한다. 두 신호가 일치할 때만 자동 귀속하고, 충돌하면 상단 표기를 강제 적용하지 말고 개별 전표 증거를 우선해 검토상태로 둔다.”이다. current P20/P21 재작성은 이 원문을 대체한 것이 아니라, N:1과 4,768 JPY 중복계상 반례를 반영하고 비권한 guard를 결합한 목적 이식이다.

문서 N:거래 1 결정과 4,768 JPY 중복계상 반례로 guarded purpose rewrite를 채택했고 current P1–P19는 불변이다. policy commit은 control `78879ab`, temp `df76b40`이다. code/data/STATUS/AGENTS는 무접촉이며 receipt 11/11과 diff-check 통과, docs-only라 P07 미재실행, R11 expected-fail/cutover-fail을 유지한다.

라우팅은 AGY Gemini 3.6 Flash High missing key → AGY Sonnet 4.6 unavailable → GPT-5.6 Luna low였고, Claude Fable 5 medium과 GPT-5.6 Sol medium 독립+cross 뒤 closure 둘 다 ACCEPT다. 수용은 guarded current P20/P21 이식과 DEFER 대장이고, 기각은 donor P18/P19/P22/P24/P25 원문 이식 및 실제 적재·분류·projection·정본·원장·CSV 변경 승인이다. 보호 hash는 STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`, AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`, classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`, patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`이다. PR12/draft PR13 및 두 branch는 유지한다. 다음 R15는 donor P19 output/publication만 감사하고 P18/P22는 승인된 OTA 목적까지 대기한다.

## 2026-07-30 R15 세션 핸드오프 — output/publication closure

donor tip `53ef5c89261fd182d1711a50cca11279f72d5560`, source `9ee6866d09dad0d15471fb22fd59e73bf9b96679`; P19 원문은 “사용자가 명시하기 전에는 워크북·CSV 등 산출물을 생성하거나 출력하지 않는다. 조사 중에는 dry-run·DB·테스트만 사용하고, 단건 오류의 근본원인→일반화된 알고리즘 수정→검증식→회귀테스트 순으로 처리한다.”이다. 원문은 NO-PORT, guarded purpose rewrite는 current P22 PORT다.

라우팅은 AGY Gemini 3.6 Flash High missing key → AGY Sonnet 4.6 unavailable → GPT-5.6 Luna low였고, Claude Fable 5 medium과 GPT-5.6 Sol medium이 독립 판단 → cross 검증·반박 → closure를 수행했다. guarded current P22는 수용했고 donor 원문 그대로의 이식, P07 구현 세부사항 과적합, DB 변경 권한 추정은 기각했다.

R14 guarded purpose mechanism과 owner review로 ambiguity를 해소했다. bare DB mutation inference를 막고 불변 입력·격리 temp·기존 승인 게이트 비대체를 명시했으며 root-cause는 code/pipeline defect에만, source fact/user decision은 일반화하지 않는다. P1–P21 byte unchanged, P07-specific policy language 없음. Luna DEFER는 기각, Fable/Sol 독립+cross는 guarded P22 ACCEPT다. 46 tests PASS, docs-only P07 미재실행, `REAL_EXPECTED_FAIL=PASS / CUTOVER=FAIL` 유지, code/data/baseline/output/STATUS/AGENTS 무접촉이다.

보호 hash STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`, AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`, classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`, patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`; policy `5f83aa8`, control `03305d0`, PR12/draft PR13/branch 유지. 잔여 DEFER P18 OTA hierarchy·P22 OTA checkpoint/runbook·P25 general tail·P20 2025 fragment, R16은 P25 small-amount principle, OTA는 authorization 대기.

## 2026-07-30 R16 세션 핸드오프 — P23 guarded policy closure

policy temp `3293155`, control `9e3b20a`, donor tip `53ef5c89261fd182d1711a50cca11279f72d5560`, source `4997b2298ae1defe148260134d33255be2073453`.

> **P25. 우라반다이 물산관 2건 분류와 소액 현지구매 일반화 한계(2026-07-26
> 사용자 확정):** 2026-07-03 `裏磐梯物産館` 현금 영수증 11,550엔·6,600엔은
> `0630_오제 / 여행원가 / 여행 식재료·소모품`으로 확정하고 P11 편의환율로
> 각각 115,500원·66,000원을 기재한다. 단, **금액이 작다는 이유만으로
> 업무관련성을 자동 인정하지 않는다.** 향후에도 여행기간·지역·실물 영수증·
> 구매 목적이 결속되는 소액 현지구매만 같은 계정으로 자동 제안하며,
> 개인사용·고객접대·선물 가능성 또는 여행 신호 충돌이 있으면 자동 전기하지
> 않는다.

우라반다이/date/amount/account 사실은 photo hash·evidence identity·approval lineage 부재로 NO-PORT, same-account 일반화도 NO-PORT, guarded general tail만 current P23 PORT다. 미래 evidence-backed item purpose는 donor port가 아닌 별도 목적이다. 네 신호는 필요조건이지 충분조건이 아니며 travel conflict는 proposal, adverse signal은 posting을 차단한다. venue category만으로 auto-include/auto-exclude하지 않고 data/system authority도 부여하지 않는다.

Routing: Flash missing key → Sonnet unavailable → Luna low. Fable/Sol 독립 후 cross: Fable은 Sol 반박 뒤 same-account propagation·overbroad adverse proposal block을 철회, Sol은 Fable bidirectional venue guard 수용, Fable은 Sol §3 exact P23 수용. 57 tests PASS, diff-check PASS, docs-only·P07 미재실행, REAL_EXPECTED_FAIL=PASS/CUTOVER=FAIL 유지. P1–P22 byte unchanged; P23 item strings 없음, `0630_오제`는 기존. 보호 hash: STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`, AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`, classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`, patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`.

code/data/baseline/output/STATUS/AGENTS untouched; PR12/draft PR13/branches kept. Residual DEFER: donor P18 OTA hierarchy, P22 OTA checkpoint/runbook pending authorized OTA purpose, P20 2025-scope fragment; P25 tail removed. Next R17 residual closure audit only; no automatic OTA/data action.

## 2026-07-30 R17 세션 핸드오프 — guarded P24 closure

policy temp/control `1fbb274`; donor tip `53ef5c89261fd182d1711a50cca11279f72d5560`, source `9ee6866d09dad0d15471fb22fd59e73bf9b96679`. Routing: Flash missing key → Sonnet unavailable → Luna low; Fable/Sol independent → cross → closure. Fable independently first marked donor P18 DEFER; Sol rebutted and rewrote a guarded current P24; Fable exact acceptance: **“ACCEPT — Sol cross §3의 개정 P24 문단을 byte 그대로 binding hunk로 채택한다. 안전 차단 수정 없음.”** Both closures exact: **“P24는 §3 문구 그대로 binding이며, P22는 DEFER, pre-2025 조각은 final NO-PORT, PR12는 ANA/GASUTO 결정 전 KEEP, PR13은 지금 KEEP이고 두 PR의 모든 미래 archive/close/delete는 별도 명시 권한 사항이다.”**

Donor P18 exact quote (source `9ee6866d09dad0d15471fb22fd59e73bf9b96679`):

> **P18. 인증된 OTA 포털 직접조회가 OTA측 최상위 증거(2026-07-26 사용자 확정):**
> 로그인된 Agoda·Booking.com·Trip.com 예약 상세는 공급자가 현재 보유한
> 예약번호·상태·숙박/탑승일·원통화 금액·카드 끝자리를 직접 보여 주고,
> 메일 반송·누락·파서 실패의 영향을 받지 않으므로 OTA측 증거 중 가장 높다.
> 카드사 RAW는 실제 카드 이벤트의 최상위 증거다. 인증 포털과 카드 RAW의 비교
> 가능한 교집합이 모두 일치할 때 전체 매칭의 최강 증거로 확정하고, 하나라도
> 충돌하면 기존 메일·수기·하드코딩보다 우선하여 강한 확정을 차단한다.

Original P18 is **NO-PORT**; guarded current P24 is exact **PORT**. P24 preserves the no-portal P5/P10 default; applies only to a separately authorized, already lawfully acquired, provenance-bound observation; authorizes no new acquisition; separates OTA observation-time facts from card payment/cancellation/refund authority; treats missing/non-comparable fields as not a match; routes conflict to review without overwriting either source; and has the full nonauthority tail: no OTA login/browsing/collection, Gmail/Drive access, checkpoint/DB creation, matching/classification/posting, canonical/ledger/CSV change.

Donor P22 source `4997b2298ae1defe148260134d33255be2073453` remains the sole residual **DEFER / NO-PORT**, pending explicit OTA purpose plus checkpoint owner/privacy/schema/retention/recovery/import gates. Donor P20 exact fragment — **“2025년 이전 거래는 부가세 신고기한이 끝났으므로 현재 우선범위에서 제외한다.”** — is final **NO-PORT** and removed from residual.

PR12/fix-post and draft PR13/resolve remain **KEEP/NO-MERGE**: PR12 awaits ANA/GASUTO user decision; PR13 preserves sole evidence. No archive/tag/close/delete is scheduled or authorized without separate explicit user authorization. Safe donor policy ports are exhausted; next paths require user ANA/GASUTO or OTA approval, or a separate control-native Gate 2 Hana redesign.

Verification: 63 tests PASS and diff-check PASS; docs-only, no P07 rerun; `REAL_EXPECTED_FAIL=PASS / CUTOVER=FAIL` remains; P1–P23 byte unchanged. Full protected hashes: STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`, AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`, classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`, patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`. No code/data/baseline/output/STATUS/AGENTS/OTA/Gmail/Drive/PR/ref action.

## 2026-07-30 R18 세션 핸드오프 — Gate 2 control-native closure

Code temp commit `24bfc65e17df94ffb58c563511ac4801a1462a61`; control `ecbb923`. Root cause was Hana approval reuse: four pairs/eight rows — card 4595 approval `00107633` H:191/H:223, `00407242` H:270/H:315, `00305072` H:302/H:331, and card 6741 approval `00122440` H:1708/H:1783 — while the current key omitted occurrence date.

Fable initially proposed a dataset-dependent date+amount two-pass. After Sol rebuttal, Fable withdrew it because of retroactive ID instability, amount-correction phantom splitting, and invalid `approval_reuse` schema. Binding implementation is Sol’s row-local `card-event-v2`: strict `occurred_on`; missing/invalid dates become `legacy_fallback`; Gate 2 blocks both `collision` and `legacy_fallback`; same-day exact reuse remains collision; amount, merchant, posting date, UID, and locator stay outside identity. Routing was Flash missing key → Sonnet unavailable → Luna low; Fable/Sol independent → cross → implementation reviews both PASS.

Exact scope was five files, `+132/-3`; no data/baseline/output/STATUS/AGENTS/OTA/Gmail/Drive/PR/ref change. Targeted tests `58/58`, full suite `99/99`, and diff-check PASS.

Real isolated P07 run `661097aaefd047b68d3ae4be756d74c8`: input manifest `e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199` unchanged; code bundle `ab6d16b22173a49a03a5de50f52eac5f8b814e3753d0df3235d5e375259e83ce`; intentional semantic hash `eb100d3d6b1fbfd31118b71076d88091aed3b0e5f7e480f3920bba875e710e2c`; verified report `ef71ee2e1ec8c1e1a1a8b24207e7a4b8a892fc7731b3c7de2c4cc7ee3d4235f0`. Gate 1/2/3/7 PASS; Gate 2 `5328=5328`, collision/fallback/duplicate `0`; Gate 4 FAIL sign `157`; Gate 5 FAIL unresolved `5328`; Gate 6 unavailable. Exit `1`, `artifact_state=not_published`, candidate DB absent, legacy authoritative.

PR12/13 remain KEEP. Next R19 is a control-native Gate 4 redesign for 149 KBO `취소매출` plus 8 CORP `취소또는할인`; no automatic data mutation. Protected hashes remain STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`, AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`, classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`, patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`.
