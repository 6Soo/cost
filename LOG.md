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
  뒤 두 원격 작업 브랜치를 삭제했다. 열린 PR은 0개, 원격 브랜치는 `main`만 남았다.
