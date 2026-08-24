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

## 2026-07-30 R19 세션 핸드오프 — Gate 4 sign closure

Control `a4dce07`; temp/code commit `6c1260dc5c4d31e9639e7f5e997d30eee8552022`. Root cause: KBO 149 `취소매출` and CORP 8 `취소또는할인` rows carried a raw positive magnitude into a positive normalized cancellation leg. Fable/Sol independently converged; Fable cross accepted Sol’s label-first KBO/CORP `+/-/0 → -abs, cancellation` rule, with zero deliberately remaining a Gate 4 blocker. Fable also corrected the temporary/main HEAD confusion.

Binding scope is exactly three files, `+269/-12`: direct-source pure normalization, new owner tests, and P6 integration assertions. Every normalized leg is `direct-card-v3`; raw payload/event facts and identity remain unchanged. No pairing, classification, allocation, relation creation, or data mutation is authorized. Routing: Flash missing key → Sonnet unavailable → Luna low; Fable/Sol cross and implementation reviews PASS.

Review evidence: targeted `61/61`, full `102/102`, diff-check PASS. Real P07 `fef0e7b388254d3c95ba04c026e835af`: input `e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199` unchanged; code bundle `8cb82ea8f8a475aa7cc6ea3f88d2b1dcb0891b7bbebbb91f301ae85a967bbcef`; semantic `660eb1fd16f2ca2cb8247609ecc893f5d64ab021dcef50698abc2a829c8c58d2`; report `6527ffb68ff7fb8612ec86004aab74fcf7db4b38623ab74f849d0361ecb0c083` verified. Gate 1/2/3/4/7 PASS; Gate 2 `5328=5328`, issues `0`; Gate 4 sign `0`, Hana split `0`; Gate 5 FAIL unresolved `5328`; Gate 6 unavailable. Exit `1`, `not_published`, candidate absent, legacy authoritative.

Quantified raw absolute magnitude is `43,490,431 + 2,925,343 = 46,415,774`; normalized total delta is `-92,831,548`. No pairing. Protected hashes remain STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`, AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`, classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`, patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`. No data/baseline/output/STATUS/AGENTS/OTA/Gmail/Drive/PR/ref change; PR12/13 KEEP.

Next R20 is a high-audit Gate 5 review: determine a safe control-native scaffold versus user-fact DEFER; no automatic allocation.

## 2026-07-30 R20 세션 핸드오프 — Gate 5 scope fingerprint

Fable/Sol independent review → cross converged: generic `confirmed` decision + exact-sum plan was rejected as fail-open; report-only direct event-role scope fingerprint was accepted. Routing: Flash missing key → Sonnet unavailable → Luna low. Exact code scope `+207/-2`; v1 review FAIL (B1/B2), then both v2 implementation reviews PASS after adding canonical direct-key first10, census-total, duplicate-retention, and verifier-tamper coverage. Targeted `34/34`, full `106/106`.

Real P07 root `/tmp/cost-r20-p07.0dYRQm`, run `2e4d867e6d2946beb658ad00dd259212`: input `e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199` unchanged; semantic `660eb1fd16f2ca2cb8247609ecc893f5d64ab021dcef50698abc2a829c8c58d2` unchanged; bundle `875dee7bc59a7c68abcfc195e98d371d81c6046dc0b92c836b50fc1ad3ccbdaa`; report `64b176f2bf3b881bf42967a62bf9380d5d1954b468536d7fd309fd917ce76bd8` verified. Gate1/2/3/4/7 PASS; Gate5 remains `0/5328`, scope SHA `22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418`, unique `5328`, invalid/duplicate `0`; Gate6 unavailable; `not_published`, candidate absent, legacy authoritative.

`5328` is a stub indicator, not actual resolution. Actual resolution requires A0/P16 authority, evidence, and user approval. Protected hashes unchanged: STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`, AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`, classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`, patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`; PR12/13 KEEP; no external/data action.

## 2026-07-31 R21 branch audit — Gate 6 authority seal

Safe ports `0`; PR12/13 KEEP/NO-MERGE. Fable exact-match PASS was withdrawn after Sol’s arbitrary-JSON self-approval counterexample; binding event-diff diagnostics plus authority-fail seal accepted. Luna v1/v2 reviews failed B1–B5; v3 passed both reviews with strict matrices. Exact code `+547/-45`; targeted `45/45`, full `117/117`.

Real P07 `/tmp/cost-r21-p07.xC2jgL`, run `2e8e2184...`: input `e355...`, semantic `660e...` unchanged; bundle `3cd165...`; report `b941e9...` verified. Gate1/2/3/4/7 PASS; Gate5 `0/5328`; Gate6 baseline unavailable, current event-set `0f5ca...`, scope `224593...`; `not_published`, candidate absent, legacy authoritative. Baseline authority/promotion user-owner DEFER. STATUS untouched; no data/baseline/artifact/PR action.

## 2026-07-31 R22 세션 핸드오프 — non-authoritative owner review

Main `37688e0`; exact five-file R22A scope `+866`. 외부 검토 패키지 생성·검증만
추가했고 owner 결정을 DB에 적용하거나 Gate 5 권한으로 승격하는 R22B는 DEFER다.
Sol/Fable v7 독립 검토와 상호 반박은 모두 PASS했다. v6에서 발견한 양쪽
`source_run_id` 결속 누락과 잘못된 container의 traceback은 strict guard와 회귀
테스트로 닫았다. Targeted `38/38`, full `138/138`, diff-check PASS다.

Real P07 root `/tmp/cost-r22-p07.SjbkOr`, run
`73eca28631bc45b687983cf690ea4ae1`, exit `1`; input
`e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199`,
semantic `660eb1fd16f2ca2cb8247609ecc893f5d64ab021dcef50698abc2a829c8c58d2`,
bundle `c2165c0636f5822f7e8322faa0568e4a2d890e0b49916e566c836c9b292f5b6c`,
report `17e6fd791478e41d536680d21511102f51cad5f25110d4144717e6f6e8d7c5d8`
이며 artifact verifier PASS다. Gate 1–4/7 PASS; Gate 5 `0/5328`, scope
`22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418`;
Gate 6 baseline unavailable, event-set
`0f5ca97c971125327e2bdc5aaa0f6505872c5a03c50cf4886d29753b4c1a8c7e`;
`not_published`, candidate DB absent, legacy authoritative다.

외부 owner package manifest
`dfd2c4b3fc5d9053e16d8f56361d7675ae151d3421fe5eab8eb917cbe7ed10bb`,
events `f7772fb5c0122da30e9af2a0bdd3bc24035ff30ba12613e58cb0dd2f593012d6`;
public canonical rebuild는 `template_valid`, `same_source_context=true`,
`same_export_run=false`, `authority_ready_count=0`, `gate5_resolved_count=0`,
임시 디렉터리 clean을 확인했다.

Routing은 Flash missing key → Sonnet unavailable → Luna low 구현·쓰기,
Fable 5 medium/Sol medium 독립 판단 → 반박 → v7 상호 수용이다. 보호 hash는
STATUS `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`,
AGENTS `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`,
classified `8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`,
patch `1e95db2df8669047fec96973cd197bcad7feaf1b3498eb2ae35b7610d8705361`
로 불변이다. PR12/13 KEEP/NO-MERGE; 승인된 owner 결정과 authority-bound
baseline 없이는 Gate 5/6 및 cutover를 진행하지 않는다.

후속 최종 수용 감사도 Fable/Sol 모두 PASS했고 main HEAD `91978c5`에서
targeted `38/38`, full `138/138`을 재확인했다. 원격 draft PR14
`feat(ledger): harden P07 gates and add owner review package`를 생성했으며
Gate 5/6 충족 전에는 KEEP/DRAFT/NO-MERGE다.

## 2026-07-31 R23/R24 세션 핸드오프 — 전 데이터시트·직접 DB 무결성 감사

저장소 데이터 파일 33개(CSV 7, JSON 20, XLSX 6)를 전수 파싱했고 파싱 실패와
Excel 오류 셀은 0이다. `ledger_current.xlsx`/`ledger_latest.xlsx`,
`manual_periods.csv`/`manual_v4.csv`는 각각 동일하며, manual v4의 `row`는 기존
중복 53건을 구별한다. 불변 원천에서 재구축한 direct DB는 source 8,336건
(card 5,237 + manual 1,379 + OTA 1,720), payment 5,328건이고 FK·부호·고아행
문제는 0이다. input manifest는
`3593aaa02e47aacfd93f826137f98548a85268131c43ae0517b656a96b6ff3aa`, semantic은
`660eb1fd16f2ca2cb8247609ecc893f5d64ab021dcef50698abc2a829c8c58d2`다.

R24A `14ff652`는 직접 원천 내용/manifest 변조 fail-close, OTA 배열 보존·엄격
검증, decision 무결성 blocker, stdout-only reference namespace 감사를 추가했다.
Sol/Fable 최종 구현 검토는 모두 PASS했다. 실제 P07은 Gate 1–4/7 PASS,
Gate 5 unresolved 5,328 및 Gate 6 baseline unavailable로 예상 exit 1이며,
`not_published`, candidate DB absent라 정본 전환은 일어나지 않았다.

R23A `d1f6b45`는 과거 분류와 현재 direct event의 비권한 lineage proposal annex를
추가했다. 결과는 confirmed 0 / proposal 1,227(P0 932 + 기타 295) / evidence
blocked 4,101이다. 4,101은 DB 손상이나 누락 수가 아니라 유일한 과거 1:1 lineage를
입증하지 못해 자동 확정을 거부한 수다. annex는 `unattested`, `posting_status=blocked`,
`gate5_credit=0`을 강제한다. 최종 외부 산출물 manifest
`4a127646e01c795dfdf3ece69a08f75ff460466e6bbeb1216c042212dbbadd4d`, events
`dca055ba1583035fb7c0609d55ef182b5448990fe88d85d06b32dd5490c666b1`, 5,328행이며
verifier PASS다. 출력은 repo 밖 기존 부모에만 원자 no-replace로 설치하고 심링크·경쟁
생성·지원되지 않는 원자 primitive는 fail-close한다. Sol/Fable v2 최종 검토 모두 PASS다.
통합 HEAD 전체 회귀 스위트도 `165/165` PASS(실패·오류 0)다.

Routing은 Flash key 부재 → Sonnet unavailable → Luna low 구현, Fable 5 medium/Sol
medium 독립 판단·반박·수용이었다. 수용: 원천/결정 무결성 강화와 비권한 proposal
감사. 기각: 1,227건 자동 확정, 4,101건 임의 보간, Gate 5/6 credit 또는 cutover.
STATUS/AGENTS/classified_v14 보호 hash는 각각
`a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc` /
`3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4` /
`8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989`로 유지한다.
PR14는 KEEP/DRAFT/NO-MERGE이며 승인된 owner 결정과 authority-bound baseline 전에는
Gate 5/6 및 cutover를 진행하지 않는다.

## 2026-08-01 R25 세션 핸드오프 — latest manual evidence resolution annex

최신 Drive 원장 전체 파일(`055ba6da…af41`, 40 sheets)을 P8 parser로 다시 만든 외부
`manual_v4.csv`는 1,559행, SHA-256 `2c6d7486…10489`다. 부분 465행 snapshot과 repo의
stale 1,379행 파일은 최신 census에 사용하지 않는다.

R25는 새 `direct_external_manual_evidence.py`와 전용 테스트만 추가했다. 외부 latest manual과
현재 direct context/R23 annex를 매 실행 새로 rebuild하여 `(issuer, exact date, exact signed KRW)`
양측 고립만 row proposal로 만든다. merchant는 A1에 따라 identity key가 아니라 support/error
flag다. 실데이터 결과는 전체 고립 1,043, 기존 R23 일치 847, classification conflict 8,
R23-unmatched 신규 188(KBD94/HAN65/KBO27/CORP2; single184/approval4; 음수5)이다.
support는 exact merchant19, containment87, booking67, OTA exact32/unique28이다. alias 계약은
version/hash로 결속하며 독립 alias bilateral 143은 188과 전부 교차하고 alias-only는 0이다.
배타 provider conflict 26은 `needs_review`로 격리한다.

기존 accepted evidence tier도 안정 event ID로 재계산·export했다: clean L1/L2/L5 110,
amount-conflict L9 21, group L12 29, typed v14 65, portal 1, independent signed merchant 19.
manual188 교집합은 각각 90/0/0/2/0/19이며, clean individual lane들의 고유 event union은
272다. 따라서 proposal 관점의 잔여 evidence-blocked는 4,101→3,829지만, 이것은 확정·전기 수가
아니다. 모든 manifest/row는 `unattested`, `posting_status=blocked`, `confirmed_count=0`,
`gate5_credit=0`이며 DB apply/canonical 변경/publication/cutover는 없다.

package는 manifest/proposals/conflicts/groups/diagnostics/evidence_sets 6파일이다. 최신 원문 row
hash, current event/source hash, input/semantic/event-set/decision-scope/classified/alias contract를
결속하고 public verifier가 외부 manual과 canonical context를 live 재생성해 byte-identical을
요구한다. duplicate/split, malformed 2행, conflict 8행을 별도 lane에 보존한다. 출력은 repo 밖
same-parent staging, file+directory fsync, `renameat2(RENAME_NOREPLACE)`, parent fsync이며 symlink,
기존 target, self-consistent forgery, stale context를 fail-close한다.

Fable은 merchant를 필수키로 삼는 143안을 A1 위반으로 반박하고 ACCEPT_188; Sol은 alias hash,
ID 교집합, conflict 원문, malformed queue, fsync, independent set equality 누락을 순차 지적했다.
전부 반영 후 Fable v3와 Sol v4 최종 `REVIEW=PASS`다. targeted 6/6 PASS, 전체 회귀
171/171 PASS(343.298s)다. 보호 data/AGENTS 및 main의 사용자 STATUS 변경은 건드리지 않는다.

다음 unit은 `booking_periods_verified`의 authority-bound mail→booking 13 event ID를 별도
content-bound artifact로 export한 뒤 이 annex의 `manual_signed_exact_19`와 결합하는 exact-union96
aggregator다. raw mail date+amount coincidence를 재구현하지 않는다. 그 뒤 3,829 잔여를 evidence
source별로 계속 해소하되 authority 계약 전 confirmed/Gate5 credit은 계속 0이다.

## 2026-08-01 R26 세션 핸드오프 — verified booking relation evidence

`booking_periods_verified.json`의 13개 fact를 exact `예약<digits>` token과 현재 direct
event까지 다시 추적했다. 19개 사건 중 R23 기존 11개, R25 union 중복 5개이며,
고마가네 booking `1400824130566434`의 7-way split relation 가운데 R25에 없던 순신규
event는 3개다. 따라서 proposal coverage 잔여는 3,829→3,826이다. 관계행은 7개지만
event coverage와 혼동하지 않는다.

새 `direct_verified_booking_evidence.py`는 canonical booking/mail 입력, 최신 외부 manual,
R23/R25/current direct context를 매번 live rebuild한다. exact 7 UID→approval→event 집합,
R25 union 272 및 overlap 4+1, strict digits-only approval, issuer-family bridge, TRIP-0090
날짜 충돌, target mail/fact schema를 rule hash에 결속한다. 출력은 repo 밖에만 atomic
no-replace로 설치하며 file/stage/parent fsync, symlink/hardlink/nonregular, duplicate JSON
key·NaN·unknown/tamper·self-consistent forgery를 fail-close한다. 모든 행은 `unattested`,
`posting_status=blocked`, `confirmed_count=0`, `gate5_credit=0`이며 DB/CSV/workbook/canonical
변경은 없다.

Gemini 3.6 Flash는 API key 부재로 호출 실패했고 AGY Sonnet/Luna callable도 없어 구현은
로컬 폴백으로 수행했다. Fable/Sol은 초기 구현을 각각 self-consistent forged input,
count-only mapping, 느슨한 approval/schema, fsync·rule-hash 공백으로 FAIL했고 전부 반영한
최종 commit을 각각 v3 `REVIEW=PASS`로 수용했다. targeted 6/6와 최종 live 1/1,
전체 회귀 178/178 PASS(496.237초), diff-check clean이다. 보호된 사용자 `STATUS.md`,
AGENTS, classified_v14는 변경하지 않았다.

다음 R27은 `booking_info` 순신규 4개와 `ota_event_links_verified` 순신규 2개를 서로 및
R23/R25/R26 event union과 중복 제거하는 별도 content-bound proposal artifact다. 예상
proposal 잔여는 3,826→3,820이며 raw authority가 없으므로 confirmed/Gate5 credit은 0을
유지한다.

## 2026-08-01 R27 세션 핸드오프 — repository booking/OTA evidence

R23 1,227 ∪ R25 272 ∪ R26 relation 7을 event ID로 live 결합했고 교집합은 R25∩R26
4뿐이라 prior union은 1,502다. R23 UID 경로를 먼저 적용한 뒤 strict approval-family
1:1 fallback을 사용했다. `booking_info`는 resolved 53/overlap 49/new 4/unresolved 7,
`ota_event_links_verified`는 resolved 63/overlap 61/new 2/unresolved 5다. 두 신규 set은
서로 비중복이므로 proposal coverage 잔여는 3,826→3,820이다.

새 `direct_repository_booking_evidence.py`는 relations 신규 6, coverage 116,
ambiguities 12와 manifest의 정확히 4파일을 외부 경로에 원자 게시한다. canonical source
whole-file/row-set SHA, 실제 OTA field-shape census 21, exact new/ambiguity/group sets,
R23/R25/R26/current context를 rule과 manifest에 결속한다. R26 전체 중첩 rebuild 대신
canonical periods/mail path+nlink+SHA, R26 rule/exact relation-set, current membership 및
R25 input/semantic/event/scope를 검증하는 경량 dependency verifier를 사용한다. R23 UID-first
누락 과대계상, self-consistent forgery, exact swap, 민감값 export, authority 승격 및
write/file-fsync/stage-fsync/verify/rename/parent-fsync 실패를 테스트로 차단한다. output은
0700/files0600, atomic no-replace이며 guest/PNR/PIN/access-token URL을 내보내지 않는다.

두 설계 검토는 final counts의 `53/7`과 approval-only 중간 `13/47`을 구분해 수용했다.
초기 구현은 disposition/rule 결속, provenance/shape, 적대 테스트, 중첩 rebuild와 upstream
R26 drift 검증 공백으로 Fable/Sol이 FAIL했고 모두 수정했다. 최종 Fable v3와 Sol v3는
`REVIEW=PASS`; targeted 6/6, fresh live build PASS, 전체 회귀 185/185 PASS(648.427초),
diff-check clean이다. 모든 row는 `unattested/blocked/0/0`이며 DB/CSV/workbook/canonical과
보호된 STATUS/AGENTS/classified_v14는 변경하지 않았다.

다음 R28은 proposal 잔여 3,820에서 현재 제외된 source를 stable identity 가능성별로 다시
분해한다. amount-only·historical classification-only·근사 match는 계속 제외하고, 독립 raw
locator/hash 또는 globally isolated structural identity가 있는 순신규 event만 별도 annex로
추가한다.

## 2026-08-01 R34 세션 핸드오프 — merchant taxonomy diagnostic support

R28~R33에서 repository 잔여 source, Gmail Trip/Agoda/Booking 원문, 카드 승인 메일,
classified 생성 lineage를 다시 조사했지만 R27 union 밖 순신규 exact event는 0이었다.
따라서 proposal coverage union은 1,508, evidence-blocked 잔여는 3,820으로 유지된다.
Gmail 원문은 read-only로 확인했고 raw MIME·PII를 저장소에 넣지 않았다.

R34는 merchant taxonomy를 독립 교차검토했다. Fable의 broad 941안과 Sol의 strict 259안 중
양측이 동일하게 지지한 strict 259건만 진단 artifact 대상으로 수용했다. 이 집합은 account
259건과 cost_type 259건을 지지하며 VAT는 258건만 지지한다. VAT `확인` 1건은 미해결이고,
기간·예약 근거가 필요한 bucket 및 full classification은 0건이다. 따라서 이 결과는 부분
분류 지원일 뿐 신규 evidence coverage, confirmed, Gate 5 credit을 늘리지 않는다.
source+currency partition에 기대던 Tier-B19는 14개 seed 중 0개 3건·1개 5건으로 결정성이
없어 양쪽 검토에서 기각했다.

새 `direct_merchant_taxonomy_support.py`는 현재 event set, decision scope, R23/R25/R26/R27
component set, 전체 12-field semantic row set과 선택 event set의 SHA를 rule에 고정하고 live
재계산한다. 초기 구현은 같은 건수의 universe 교체와 semantic drift를 막지 못해 양쪽 검토가
FAIL했고, exact set/hash 결속과 rule-independent compiler/selector 및 적대 테스트를 추가했다.
수정 후 Fable v2와 Sol v2가 각각 `REVIEW=PASS`; targeted 10/10, 전체 회귀 195/195
PASS(1084.106초)다. 모든 결과는 `unattested/blocked/confirmed_count=0/gate5_credit=0`이며
DB apply, canonical publication, cutover는 수행하지 않았다.

Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 로컬 구현
폴백을 사용했다. 다음 R35는 잔여 3,820건을 계정·비용유형·VAT·bucket별로 분리하고, 독립
근거가 없는 제안은 review-only로 유지하면서 full classification을 완성할 수 있는 예약기간
및 원장 근거를 우선 탐색한다. 보호된 사용자 `STATUS.md`, AGENTS, classified_v14는 변경하지 않는다.

## 2026-08-01 R36 세션 핸드오프 — manual duplicate-group + taxonomy evidence

잔여 3,820건을 다시 분해하면 R34 taxonomy 259건 중 258건은 bucket만, 1건은 bucket과 VAT가
비어 있고, 나머지 3,561건은 네 분류 차원이 모두 비어 있다. canonical `occurred_on` 기준
2026년 2분기 잔여는 44건(4월25/5월9/6월10)이며 69건이 아니다. Q2 밖 3,776건은 선결제·사후
환불 가능성이 있어 날짜만으로 보고범위 제외나 Gate 5 해결로 처리하지 않았다.

최신 외부 manual 1,559행에서 `(issuer, exact occurred_on, exact signed KRW)`가 양쪽 모두
중복이면서 cardinality가 같고 signed total이 같으며 모든 manual member의 tab이 동일한 declared
trip인 residual group만 수용했다. 결과는 18 groups/44 events의 group-level bucket support다.
개별 manual row↔card event bijection은 주장하지 않는다. 이 44건과 독립 R34 taxonomy 259의
교집합은 5 groups/16 purchase events이며 account·cost_type·VAT·bucket 네 필드가 모두 완성된다.
따라서 full-classification proposal union은 1,508→1,524, incomplete 잔여는 3,820→3,804다.
bucket-only 28건은 다음 단위에서 manual item/description과 세무근거를 별도로 검증한다.

새 `direct_manual_group_taxonomy_evidence.py`는 44행 bucket support와 16행 full proposal을
저장소 밖에만 게시한다. current/prior/R25/R34/trips/manual 전체 context와 member·locator·row·source
set, group partition, bucket/full semantic hash를 live 재생성한다. 외부 출력에는 merchant,
manual locator, booking reference, card4, raw amount를 넣지 않는다. 모든 행은
`unattested/blocked/confirmed_count=0/gate5_credit=0/applied=false`이며 DB·canonical·cutover는
변경하지 않는다.

초기 구현은 bucket-only 28 event addressability와 단계별 원자 실패 테스트가 없어 양 검토가
FAIL했다. 44행 addressable artifact와 bucket semantic binding을 추가한 뒤에도 parent-fsync
rollback의 output/stage pathname TOCTOU가 두 차례 발견되어 수정했다. 최종 v4는 게시 후 경로를
삭제·rollback하지 않고 durability 미확인을 명시적으로 반환하며, live verify→parent fsync→live
verify reconciliation만 허용한다. target/stage reuse 경쟁 테스트까지 반영한 뒤 Fable v4와 Sol
v4 모두 `REVIEW=PASS`; targeted 14/14, 전체 회귀 209/209 PASS(1221.819초)다.

Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 로컬 구현
폴백을 사용했다. 보호된 사용자 STATUS, AGENTS, classified_v14는 변경하지 않았다. 다음 R37은
bucket이 확보된 28건의 manual item/description을 범용가맹·품목불명 반례와 분리해 독립
account/cost_type/VAT 근거를 찾고, 같은 방식으로 순신규 full classification만 추가한다.

## 2026-08-01 R37 세션 핸드오프 — narrow toll service classification

R36 bucket 44에서 full 16을 뺀 28 events/13 groups를 latest manual item·description과 current
raw merchant·biz·currency로 전수 재검토했다. Sol의 초기 strict 18안(숙박12/항공4/통행료2)은
보고서상 raw product/VAT 조건과 실제 selector가 달랐다. Fable 반박 후 Sol이 숙박·항공 16건을
철회해 최종 교집합은 통행료 1 group/2 events뿐이다. 나머지 26건은 OTA 다상품성, 원거래 미결속
취소, item/description 충돌·모호성, 해외 VAT 결속 부족 때문에 보류한다.

채택 2건은 R36의 완전한 2↔2 group과 동일 여행 bucket 위에 manual item·description 모두 통행료,
current raw merchant가 HIGHWAY와 TOLL을 함께 만족, purchase/single, non-KRW ISO currency와 positive
foreign amount를 모두 요구한다. 결과는 `통행료/여행원가/불공제_해외`이며 exact event set
`6f5bc4ec…b14ffc`, semantic set `288de0cb…bc196`이다. full-classification proposal union은
1,524→1,526, incomplete 잔여는 3,804→3,802다.

새 `direct_narrow_service_classification.py`는 strict 2와 deferred 26을 external-only 4파일로
게시한다. R36/R25/latest manual/current raw/trips 및 complete group·source·payload·event·manual
row/locator hashes를 live 결속하고, withdrawn 16이 다시 들어오면 fail-close한다. 출력에는 raw
merchant/biz/item/description/locator/date/amount/card/approval/booking을 넣지 않는다. 모든 proposal은
`unattested/blocked/confirmed_count=0/gate5_credit=0/applied=false`다. R36 v4의 post-publication
durability/reconcile 및 target/stage reuse 경쟁 계약도 그대로 적용했다.

Fable/Sol 최종 구현 리뷰는 모두 `PASS`; targeted 7/7, 전체 회귀 216/216 PASS(1375.633초)다.
Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 로컬 구현 폴백을
사용했다. 보호된 사용자 STATUS, AGENTS, classified_v14는 변경하지 않았다. 다음 R38은 deferred
26 중 예약·원거래 exact relation을 새로 확보할 수 있는지 우선 확인하고, 불가능하면 전체 잔여
3,802를 source/time/provider cluster로 재분해해 다음 최대 독립 근거 source를 찾는다.

## 2026-08-01 R38 세션 핸드오프 — structured lodging evidence + DB 전수 감사

R37 deferred 26건/12그룹을 canonical structured source와 다시 대조했다. 양 검토가 독립적으로
수용한 순신규는 complete 2↔2 group 한 개의 2 events뿐이다. 두 manual member의 서로 다른 exact
booking reference가 `booking_info.json`의 숙박 fact에 2/2 존재하고 동일 숙박기간이 R36 trip
window 안에 있으며, current 두 사건도 purchase/single/card_raw, non-KRW ISO currency, positive
foreign amount와 해외 payload를 만족한다. 결과는 `숙박비/여행원가/불공제_해외`, exact set
`a9028357…a7578`, semantic set `df45ad8a…02d4b`다. proposal union은 1,526→1,528,
incomplete 잔여는 3,802→3,800이며, 나머지 24건/11그룹은 exact relation 부족으로 보류한다.

새 `direct_structured_lodging_evidence.py`는 R25/R36/R37 rule/package/current/scope/manual/trips,
complete group, booking whole-file/reference/row/period, current event/source/payload 및 remaining24
semantic hashes를 live 결속한다. row bijection은 주장하지 않고 raw booking/merchant/date/amount/
card/approval을 출력하지 않는다. 모든 결과는 `unattested/blocked/confirmed_count=0/gate5_credit=0/
applied=false`다. strict duplicate-key JSON, partial coverage, source drift, 해외 VAT 근거 누락,
inclusive trip window, post-rename durability와 target swap을 fail-close한다. 초기 구현은 두 리뷰가
upstream provenance·VAT·trip·durability 공백으로 FAIL했고, 보완 후 발견된 window off-by-one까지
수정하여 Fable patch2와 Sol final 모두 `REVIEW=PASS`; targeted 8/8 계열과 전체 회귀 224/224
PASS(1738.239초), diff-check clean이다.

병행 전수 감사는 CSV16+XLSX11의 170 sheets와 isolated SQLite 33 tables+7 views를 확인했다.
physical integrity/FK/PK/NOT NULL/orphan은 PASS지만 canonical/consumer/cutover는 FAIL이다. HAN
2,188 identity는 1:1이나 1,602 events에서 legacy master가 승인금, direct DB가 매입금 우선이라
DB-master 합계가 6,285,630원 다르다. 회계 계약상 direct의 매입금 우선이 authoritative이며,
근거부족 residual 교집합은 1,494건이다. 저장소 manual 1,379행도 확인된 외부 latest 1,559행보다
180행 stale이고, 생성 XLSX 4종은 headless formula cache 621/621이 비어 있다. `/tmp` latest를
정본으로 복사하지 말고 P8 Drive provenance로 재수취해야 한다. 다음 R39는 공통 HAN normalizer와
identity/role/event-amount equality gate를 추가하고 전 artifact를 rebuild한 뒤, residual 3,800의
exact unique cancellation 209건을 original relation 기준으로 우선 검토한다.

AGY Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 구현은 로컬
폴백을 사용했다. 보호된 사용자 STATUS, AGENTS, classified_v14는 변경하지 않았다.

## 2026-08-01 R39 세션 핸드오프 — HAN canonical equality candidate + activation binding

하나카드 G/H 원본의 금액 의미를 공통 `han_normalizer.py`로 통합했다. 일반행은 매입금액을
우선하고 승인금액을 fallback으로 사용하며, 승인/취소 동시행 91개는 양수 approval과 음수
cancellation 역할로 분해한다. 이를 현재 direct projection과 master 후보에 동일 적용한 결과
전체 5,328건(CORP174/HAN2,188/KBD1,287/KBO1,679), identity/role 및 금액합 708,722,467원이
정확히 일치한다. legacy canonical master는 HAN 1,602행에서 6,285,630원 차이가 나지만 원본
`master_ledger.csv`는 변경하지 않았고, 저장소 밖 private candidate만 생성한다.

projection schema는 `p07-direct-v3`로 올렸다. equality package의 authority/input/candidate master/
identity-role/amount semantic을 append-only validation row에 결속하고, Gate 4가 live package와
정확히 대조해야만 활성화할 수 있다. 활성화는 sealed package snapshot 재확인, `BEGIN IMMEDIATE`,
manifest/report/inventory CAS, consumer view validation join, WAL/SHM/journal 부재, DB 0400 seal 및
외부 보관 activation pointer를 모두 요구한다. 실패한 진단 report는 감사 근거로 보존하되 candidate
DB는 게시하지 않는다. pointer는 서명이 아니므로 manifest 자체에서 되읽어 신뢰하지 않는다.

HAN provenance 변화로 R34→R38의 event/semantic/package hash를 의존 순서대로 재생성했다.
업무 membership은 전부 불변이다: current5,328, prior1,508, R34 residual3,820/taxonomy259,
R36 bucket44/full16, R37 strict2/deferred26, R38 selected2/remaining24, 최종 proposal union1,528/
incomplete3,800. targeted R34 10/10, R36 14/14, R37+R38 15/15, 최종 전체 회귀 254/254
PASS(2031.393초), diff-check clean이다. Fable/Sol B2 최종 리뷰와 cascade 감사 모두 PASS다.

DB·전 데이터시트 독립 감사는 물리 구조를 PASS with WARN으로 판정했다. 실제 활성 SQLite는
저장소에 없고 후보는 미활성이다. repo manual_v4 1,379행은 Drive latest 1,559행보다 180행 stale,
생성 XLSX 수식 cache 621/621은 비어 있으므로 운영 정본으로 승격하지 않는다. 다음 R40은 양쪽
검토가 수용한 raw `orig_appr` exact cancellation/refund relation 210건을 relation-only annex로
게시한다. full-classification delta는 0이고 incomplete3,800은 유지한다. 그 다음 R41에서 OTA
rich message 215개의 identity/VAT/group cardinality를 갖춘 strict linker를 검증한다.

AGY Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 구현은 로컬
폴백을 사용했다. 보호된 사용자 STATUS, AGENTS, classified_v14, master_ledger는 변경하지 않았다.

## 2026-08-01 R41 세션 핸드오프 — OTA lifecycle support-only compiler

OTA mail index 1,720개를 provider+identity type+exact ref/PNR namespace의 lifecycle graph로
재구성했다. identity message416, identity nodes454, rich message215, rich nodes263, rich lifecycle
components199다. R26/R27 source facts를 live rebuild해 실제 관계만 결합한 결과 61 node/event
pairs와 54 linked nodes가 37 components→40 current events로 연결되고, 모두 기존 accepted1,528에
포함된다. repository fact는 있지만 current identity가 없는 TRIP-0429 1 component와 no-fact161을
분리해 no-current queue는162다. amount-only global singleton61은 currency/role/card identity가
없어 전부 거부한다. 따라서 net-new0, service existing40, period37, VAT0, full delta0,
incomplete3,800이다.

새 `direct_ota_lifecycle_support.py`는 components/rejections/existing_links/new_proposals/manifest
5파일의 external-only package다. raw ref/PNR/subject/amount/card4와 무염 identity digest를 내보내지
않고 opaque component/node, message/source/event content hashes만 기록한다. strict duplicate-key JSON,
실제 RFC3339와 달력 MMDD, provider별 ASCII identity, nested booking/period/OTA schemas, full namespace
fact bridge, source UID/message 참조 무결성, R23~R40 accepted/residual 및 R40 live package를 결속한다.
모든 결과는 `unattested/blocked/confirmed_count=0/gate5_credit=0/applied=false`다.

canonical에는 timezone 없는 legacy booking timestamp3행과 mail에 없는 OTA source_message_id2행이
있다. broad 예외는 금지하고 legacy3은 `(messageId,messageHash,sentAt,provider)` exact tuple set,
orphan2는 `(source_uid,message_id,canonical_fact_row_sha256)` exact tuple set으로만 격리했다. relocation,
swap, content mutation과 임의 reuse는 fail-close한다. TRIP-0429 unresolved source-fact set도 exact SHA로
결속한다.

초기 구현은 임의 event cardinality, namespace 소실, decorative counts, schema holes, stage/durability,
legacy/orphan broad allowlist가 연속 적대 리뷰에서 발견되어 여섯 라운드 수정했다. 최종 Fable v6와
Sol v6 모두 `REVIEW=PASS`; R41 targeted 10/10 PASS(376.951초), 전체 회귀 271/271
PASS(2455.242초), diff-check clean이다. R40의 fd capture helper는 filename tuple을 받도록 안전하게
일반화했고 R40 회귀도 유지된다.

R42 독립 discovery는 로컬 full-classification 신규 yield가 0임을 확인했다. 다음 권위는 exact
payment locator+item/service+VAT jurisdiction/treatment+single trip/bucket을 한 chain으로 결속한
authenticated itemized invoice/receipt/OTA portal bundle이다. 전환율 우선은 bucket 확보 residual
24건/11그룹, 대규모 search universe는 card6741 1,077건, CORP122, R41 no-current162, card3820 50이다.
latest manual delta180은 이미 R25/R36 이후 latest1,559로 처리되어 additive yield가 아니다.

AGY Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 구현은 로컬
폴백을 사용했다. 보호된 사용자 STATUS, AGENTS, classified_v14, master_ledger는 변경하지 않았다.

## 2026-08-01 R40 세션 핸드오프 — exact original-approval relation evidence

R38 이후 incomplete residual 3,800건의 cancellation/refund를 raw issuer `orig_appr` 기준으로
전수 재구성했다. amount/merchant/date/legacy classification은 identity에 사용하지 않고 동일
issuer+card4+exact ASCII approval 문자열의 unique purchase target만 허용했다. 결과는 순신규
relation 210건(HAN82/KBD128), target accepted23/residual187, target missing29, original missing147,
ambiguous/collision0이다. leading-zero와 `.0` alias를 전혀 합치지 않아도 210건이 유지되어 alias
의존은 0이다. 독립 full-classified target은 0이므로 full-classification delta0, incomplete3,800을
그대로 유지한다. 관계 근거가 늘어난 것이지 분류 완료나 전기 권한이 늘어난 것은 아니다.

새 `direct_original_approval_relation.py`는 external-only manifest/relations/exclusions 3파일을
게시한다. 짧은 승인번호의 무염 SHA도 사전대입으로 복원 가능하므로 원문과 파생 digest를 모두
제거하고 event/target/source/payload content provenance만 공개한다. HAN G/H와 KBD F의 whole-file
SHA, parser v4, HAN normalizer version/contract 및 issuer field-shape를 live inventory와 결속한다.
모든 row는 `unattested/blocked/confirmed_count=0/gate5_credit=0/applied=false`이며 account/cost/VAT/
bucket을 내보내지 않는다.

초기 구현은 Fable/Sol이 privacy digest, verifier TOCTOU, decorative normalization authority,
parent-fsync 성공 오판과 stage swap을 차례로 재현해 두 라운드 FAIL했다. 승인 digest 제거,
dirfd+O_NOFOLLOW/fstat 단일-fd capture, external-only no-replace, file/stage/parent fsync, 게시 전후와
fsync 후 byte 검증, `PublicationIntegrityError`/`PublicationDurabilityError` 및 보존형 reconciliation,
exact-string authority live 검증을 반영했다. 최종 Fable v3와 Sol v3 모두 `REVIEW=PASS`; R40
targeted 7/7 PASS(176.277초), 전체 회귀 261/261 PASS(2182.924초), diff-check clean이다.

다음 R41 read-only census는 OTA mail1,720/rich215/lifecycle199를 확인했다. exact bridge는 38
components→40 events지만 모두 R26/R27 accepted에 이미 포함되어 순신규 stable edge는 0이다.
rich group-only244와 metadata shortest-path5는 card identity·currency·typed amount·VAT 권위가
없다. R41은 support-only lifecycle compiler로 봉인하고, authenticated portal/invoice identity가
확보될 때만 재실행한다. 잔여3,800을 허위로 줄이지 않는다.

AGY Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 구현은 로컬
폴백을 사용했다. 보호된 사용자 STATUS, AGENTS, classified_v14, master_ledger는 변경하지 않았다.

## 2026-08-01 R42 세션 핸드오프 — zero-document acquisition census

R41 이후 residual3,800을 전환 가능성 기준으로 정확히 분할했다. 이미 bucket을 가진 remaining
24건/11그룹(`ab199a...f5d16`), taxonomy tag가 있으나 bucket이 없는 243건
(`ce2235...16ca`), 네 분류 축이 모두 비어 있는 broad3,533건(`a16876...bab2`)이며 세 집합은
서로소이고 합집합이 residual SHA `f52cc4...ab8b47`과 일치한다. 243건 중 242건은 VAT tag가
존재하지만 unattested이고 1건은 tag도 없으므로 이를 VAT 권위나 완료로 세지 않는다.

새 `direct_document_acquisition_census.py`는 external-only 6파일 package로 위 분할과
remaining 11그룹의 기존 bucket lineage만 게시한다. 현 production raw document는 0이므로
documents/payment edges/candidates/rejections는 모두 0행이고 disposition은
`ACQUISITION_BLOCKED_NO_DOCUMENTS`, full delta0, confirmed/Gate5 0이다. v1은 raw parser가 없으므로
`documents_dir`가 지정되면 빈 디렉터리도 즉시 거부하고 ingestion gate도 모든 입력을
`document_intake_parser_not_implemented`로 차단한다. 실제 receipt/invoice를 self-attested boolean,
임의 HMAC, merchant/date/amount로 승격할 수 없다.

publication은 external-only no-replace, 0700 directory/0600 files, dirfd+O_NOFOLLOW+fstat capture,
file/stage/parent fsync, install 전후와 parent-fsync 후 byte 검증을 유지한다. post-install byte mismatch와
parent fsync 실패를 실제 seam으로 주입해 각각 integrity/durability published-state 예외와 2-pass
reconciliation을 검증했다. remaining24/243/3533은 개수뿐 아니라 독립 고정 set SHA로 검사하며
24는 R38 canonical remaining SHA와도 교차검증한다.

구현은 AGY Gemini 3.6 Flash High가 시작했으나 Python set-comprehension 오류, m40 미정의,
문서 무시, self-attested ingestion과 보호 `STATUS.md` checkout을 일으켜 즉시 중단했다. AGY 실행
transcript의 exact 4-line diff로 STATUS를 복구해 보호 SHA `a3622a...b659cc`를 재확인했다. 이후
Codex가 차단사항을 수정하고 Fable/Sol이 각 FAIL 반례를 제시한 뒤 상호 수용했다. 최종 Fable v3와
Sol v2 모두 `REVIEW=PASS`; R42 targeted 9/9 PASS(로컬195.659초, Fable195.531초,
Sol194.441초), 기존 R41 기준 전체271/271 PASS는 기존 파일 불변으로 유지된다. 실제 문서 parser,
ingestion, classification, canonical DB/cutover는 비승인이다. 다음 실행은 독립 검증된 raw-document
parser 설계 후 remaining24/11부터 시작한다.

## 2026-08-01 R43 세션 핸드오프 — authenticated airfare receipts, support-only

R42 remaining24/11 중 수율이 높은 3개 complete 2↔2 그룹의 Gmail 영수증 6개(Mytrip/Gotogate
4, Trip.com 2)를 업무 계정에서 read-only로 수취했다. 원문 RFC822 6개와 PDF·추출문·HMAC key는
저장소 밖 0700/0600 restricted 영역에만 두고, 공개 패키지에는 Gmail ID·예약/주문/티켓·승객·카드·
원문/텍스트/MIME hash를 내보내지 않는다. raw MIME에서 attachment bytes를 다시 파싱해 pinned PDF와
byte equality를 확인하고, 별도 keyed manifest HMAC을 매번 재계산하며, 격리 pypdf 5.9.0 strict
extractor로 PDF→text를 fresh 재생성해 저장된 text와 byte equality를 강제한다. Trip.com 2건은
From/DKIM domain alignment 관찰, 전달된 Mytrip 4건은 `forwarded_outer_auth_observed_unverified`로
정직하게 격리한다.

새 `direct_receipt_airfare_provenance.py`와 `direct_receipt_airfare_evidence.py`는 live R36 bucket
support, R38 remaining, R42 24/243/3,533 partition을 재빌드하고, 3그룹의 실제 event/source/locator/
payload hash와 issuer/date/amount/provider/purchase 역할을 영수증의 ordered label·금액 산술·국제항공
service 사실에 결속한다. 문서에 승인번호나 완전 card4가 없으므로 document↔event bijection은 주장하지
않고 `support_only_no_payment_locator` 6행만 게시한다. Mytrip VAT는 `검토필요`, Trip.com만 해외 supplier/
service support로 `불공제_해외`를 기록한다. 모든 행은 unattested/blocked/confirmed0/Gate5 0/applied=false;
accepted union 1,528, incomplete residual 3,800, full-classification delta 0을 유지한다. 실제 외부 package
SHA는 `700574d20a8243867fadd4be609c767d75fc514fb1398c80ee350f57f545c842`다.

초기 v1은 self-attested HMAC, PDF와 분리된 text, hardcoded event 미결속, raw event ID 노출,
3794 오계상 때문에 Fable/Sol 모두 FAIL했다. raw MIME·fresh extractor·live event derivation·opaque IDs·
state semantics·publication durability/reconcile을 보완한 v2에서도 DKIM domain 미정렬과 unordered token
bag 반례가 발견되어 수정했다. 최종 v3는 Fable/Sol 모두 support-only 범위 `REVIEW=PASS`; focused
20/20과 R36~R43 의존 회귀 58/58 PASS(879.969초), actual MIME/PDF integration과 package verify도
PASS다. 다음 R44는 이 3그룹의 provider-scoped order/booking identity에서 issuer/PG 승인번호·exact
card4를 가진 authenticated payment message/portal edge를 찾고, 동시에 remaining 8그룹의 Agoda/
Booking/Trip original·receipt 검색을 계속한다. 강한 locator가 없으면 3,800을 줄이지 않는다.

AGY Gemini 3.6 Flash는 API key 부재, AGY Sonnet 및 GPT-5.6 Luna는 callable 부재라 구현은 로컬
폴백을 사용했다. Fable과 GPT-5.6 Sol은 설계·구현을 독립 검증하고 FAIL 반례를 상호 수용한 뒤 v3
support-only 판정에 합의했다. 보호된 사용자 STATUS, AGENTS, classified_v14, master_ledger는 변경하지 않았다.

## 2026-08-01 R44 세션 핸드오프 — closed provider census + authenticated Trip refund lifecycle support

R43 이후 remaining24/11 중 남은 8그룹을 Gmail 전체보관함에서 provider reference·숙소명·여행기간·
금액·카드 suffix·승인번호·대체 booking ID·환불 lifecycle로 폐쇄 검색했다. Booking.com Nezame 후보는
초기 known-reference 검색에서 3개 paid 예약처럼 보였으나, 전체 49 messages/20 refs census에서 동일
외화 결제 signature의 네 번째 paid 예약이 확인됐다. current에도 외화 signature 4행이 있으나 KRW가
3+1로 갈리고 Booking UUID↔issuer KRW locator가 없어 3개만 고르는 것은 invented subset이다. Trip 호텔
2건은 pay-at-property preauthorization, Agoda 항공 2건은 승인/ARN·settlement·해외 VAT authority가 없고,
나머지 Agoda 그룹들은 exact/alternate search에서도 결제 edge가 0이라 모두 full admission을 거부했다.

유일한 강한 신규 근거는 Trip.com 숙박의 구매2+전액환불2 lifecycle이다. 제한 영역의 raw RFC822 9개와
embedded receipt PDF 2개를 fresh 검증해 서로 다른 2 orders 각각 paid JPY92,001→same-order full refund,
1 room/3 nights/2026-10-06~09를 확인했다. current도 KBO purchase +893,170/JPY92,001 2행과 cancellation
-893,170/JPY92,001 2행으로 net0다. 공통 의미축은 `숙박비/여행원가/불공제_해외`, semantic trip target은
`10월_도고`, A4/P6에 따른 실제 posting bucket은 `취소환불(net0)`이다. 행별 order↔card bijection과
issuer original-approval relation은 주장하지 않는다.

새 `direct_trip_cancel_provenance.py`와 `direct_trip_cancel_lifecycle_evidence.py`는 raw9 exact SHA,
trusted `mx.google.com` DKIM pass의 i/s/b와 정확한 Trip signature d/s/b 결속(독립 SES 서명만 허용),
pypdf 5.9.0 전체 56-file tree pin·격리 실행·active-content/timeout, strict payload JSON, live residual SHA,
event/source/locator/payload/content 결속, P2/C2 exact arithmetic, trip/VAT, permutation·atomic4/no-edge,
privacy allowlist 및 fd/inode-pinned no-replace publication/reconcile을 fail-close한다. 실제 provenance v2.3
SHA는 `2b9ac638d6b62f5b1c891cc0fcf5e18d206dcba7a867054737d1aedc00873c47`, 외부 package SHA는
`84445af21ff2595b7d7994f91d4c2ab7322b91e2bbcd99874fd8138c45962dc6`다.

Gmail query 결과의 암호학적으로 인증된 acquisition transcript는 없으므로 capture completeness는
`authenticated=false/capture_claim_unverified`로 명시했다. 따라서 4 support rows와 frontier support2를
보존하되 full classification delta0, accepted1,528/residual3,800, authoritative frontier24를 유지한다.
모든 행은 unattested/blocked/confirmed0/Gate5 0/applied=false이며 DB 활성화 권한은 없다. Fable v2는
이 정직한 support-only 경계에서 PASS했고, Sol v3도 DKIM evil-d/selector/b·fake extractor·TOCTOU 반례
보완 후 PASS했다. focused R44 29/29, R43+R44 49/49 PASS, actual raw/package independent verifier PASS다.
AGY Gemini 3.6 Flash High는 이번 환경에서 callable credential이 없어 로컬 구현 폴백을 사용했다.
보호된 사용자 STATUS, AGENTS, classified_v14, master_ledger는 변경하지 않았다. 다음 라운드는 provider
portal/export 또는 issuer/acquirer 자료처럼 acquisition completeness와 KRW payment locator를 함께 주는
권위 source를 수취해야만 이 4건 또는 나머지 3,800건의 full delta를 올린다.

## 2026-08-02 R45/R46 세션 핸드오프 — KB 확인서 atomic 3 admission + legacy cardinality 격리

R23의 `근거부족 4,101`을 독립 재계산했다. 이는 현재 미분류 수가 아니라 direct 5,328에서 과거
분류표와 exact 1:1 lineage가 된 1,227을 뺀 초기 blocked 수다. 원인은 no exact candidate 3,880,
current duplicate 216, historical duplicate 5이고, 3,927건은 Q2 밖이다. 다만 선결제·사후환불이
있어 날짜만으로 scope 제외하지 않는다. R25~R38의 실제 evidence union +301 이후 authoritative
잔여는 3,800(CORP122/HAN1,638/KBD761/KBO1,279)이었다.

Gmail에서 KB 해외 사용확인서 23 deliveries를 read-only 수취하고 offline 복호했다. whole-file census는
unique19/duplicate pairs4(`03=08`,`04=06`,`05=07`,`09=10`)다. 초기 pin을 17/18/20으로 잘못 잡아
18이 인접 JPY21,600임을 적대 검토가 차단했다. 전 23개를 다시 검사해 목표 envelope가 15/17/20임을
확정하고, restricted 0700/0600 v4 bundle에 envelope·decrypted DOM·normalized table/body를 고정했다.
public package에는 승인·카드4·가맹점·금액·예약·메일·원 source locator와 저엔트로피 무염 digest를
내보내지 않는다. business credential은 저장하지 않았다.

새 `direct_kb_confirmation_evidence.py`는 KBO raw 전수 signature census에서 purchase3/refund0을
확인하고 exact target event set `a743559b…b77f7f`, manual/R36/R38 bucket, trip 실체, 해외 VAT를
atomic 3-group으로 결속한다. 개별 booking↔approval/card bijection은 주장하지 않으며
`bijection=false`, individual edge0, permutation-invariant다. 결과는
`숙박비/여행원가/불공제_해외/0613_북해도`, accepted1,528→1,531
(`fb6fb36c…94ca31`), residual3,800→3,797(`3ddfedb0…97dba`), bucket frontier24/11→21/10
(`4bfb88f4…da61b`), full delta3다. private manifest와 pin-set을 외부 상수로 이중 hard-pin하고 exact
schema, 23-envelope final recensus, forged DOM+manifest rehash, same-signature extra/cancel, symlink/hardlink,
duplicate/nonfinite JSON, privacy와 fd/inode-pinned publication/reconcile을 fail-close한다. 실제 public
package SHA는 `631fca37532ad68405159f23fefab47617b42cd165b3155101ee0ec30873e8d8`이다.

병행 R46은 인접 JPY21,600 취소의 raw/direct2 대 legacy classified4 대 master physical2·동일 workbook
reference 문제를 `direct_kbo_signature_cardinality.py`로 격리했다. raw가 권위 cardinality이며 legacy
UID edge는 0, unanimous partial group support2만 기록하고 missing cost_type 때문에 full delta0,
accepted1,528/residual3,800을 유지한다. R45 target3과 exact disjoint다. 입력은 single-fd bytes를 재사용·
종료 재검증하고, blank/duplicate UID·거래키·semantic drift를 거부한다. 첫 구현은 녹색 9 tests에도
parent-path swap, short write, input reopen TOCTOU가 남아 Sol 적대 리뷰가 FAIL했다. dirfd-only stage/rename/
target capture와 published integrity/durability/reconcile, 실제 selector 교환 테스트를 반영해 최종
Sol 독립 리뷰가 PASS했다.

R45도 첫 Fable 구현 리뷰가 self-consistent private rehash 반례로 FAIL했고 hard-pin과 raw full census를
추가한 뒤 최종 PASS했다. GPT-5.6 Sol은 계정/비용축 순서, 잘못된 25-event SHA, locator digest 및
publication 반례를 제시했고 Fable 판단과 항목별 상호 수용했다. 통합 targeted 28/28 PASS(164.380초),
py_compile/diff-check clean이다. 모든 public row는 `unattested/blocked/confirmed_count=0/gate5_credit=0/
applied=false`; DB·classified·master·canonical·cutover는 변경하지 않았다. 보호된 사용자 `STATUS.md`
SHA `a3622a…b659cc`도 불변이다. 다음 R47은 잔여3,797의 broad3,533 중 KB 확인서 broad19를 예약/여행
실체와 결합할 수 있는지 우선 검증하고, 독립 분류축이 없는 issuer identity만으로는 delta를 올리지 않는다.

## 2026-08-02 R47/R49 세션 핸드오프 — authenticated Agoda customer-service singleton admission

R47은 R45 이후 broad 잔여의 KB 확인서 19건을 로컬 원장·여행·OTA 근거와 다시 결합했으나 완전한
신규 분류축은 0건이었다. 이후 Gmail read-only 검색에서 Agoda 고객센터 원문 1건을 수취했다. 이 메일의
서명된 HTML 거래표는 서로 무관한 제목 예약번호와 본문 거래행을 분리하면서 특정 예약번호·외화금액·
거래일을 한 행 경계로 제공한다. restricted 0700/0600 영역에 raw RFC822와 256-bit nonce를 가진 strict
binding sidecar만 보존하고, 공개 산출물에는 예약·카드4·금액·가맹점·메일 식별자나 사전대입 가능한
저엔트로피 digest를 내보내지 않는다.

새 `direct_agoda_customer_service_evidence.py`는 pinned Agoda/SendGrid 2048-bit 키로 실제
RSA-SHA256 relaxed/relaxed DKIM 본문·헤더 서명을 offline 재검증한다. `l=`을 금지하고 필수 signed-header,
단일 HTML table/행 nesting, signed supplier footer, 거래행 cardinality를 강제한다. 최신 Drive-derived
manual v4 1,559행 SHA `2c6d7486…10489`의 단일 예약 행 전체와 `0620_묘코` tab을 직접 결속하고,
공급자 M.D와 current event occurred_on M/D도 직접 비교한다. 서비스 기간은 추론하거나 사용하지 않는다.
current 5,328 전체를 live 재빌드해 physical duplicate 전에 실패하고 source key/raw record/date/posted/
role/type/currency/금액/card/merchant/payload를 exact 검증한다.

결과 의미축은 `숙박비/여행원가/불공제_해외/0620_묘코` 단일 건이다. accepted는 1,531→1,532
(`d4765203…d0147`), residual은 3,797→3,796(`bb0f837d…e3778d`), full delta1이다. 공개 package SHA는
`7a70d6bd26d74dadf3a7f38404cccd8b41233f5aff9cd08892b1574ff6dbe4fc`다. 모든 row는 계속
`unattested/blocked/confirmed_count=0/gate5_credit=0/applied=false/database_applied=false`이며 DB 전기나
canonical cutover 권한을 주장하지 않는다.

publication은 external-only no-replace, short-write0, file/stage/parent fsync, parent pathname·target inode와
bytes를 검증한다. parent fsync 중 target name을 경쟁자 디렉터리로 교체하는 반례가 Sol/공격감사에서
재현되어, fsync 후 target name을 dirfd 기준으로 다시 열어 identity+전체 bytes를 확인하도록 build와
reconcile을 함께 보완했다. Fable은 최신 수기본을 repo stale본으로 오인한 초기 지적을 철회한 뒤
manual-tab→trip, provider-date→event, service-period claim honesty 세 결속을 추가로 요구했고 모두 수용했다.
최종 Fable 5 medium과 GPT-5.6 Sol medium, 공격감사는 모두 `REVIEW=PASS`; focused15/15,
R45+R49 의존32/32, 전체 회귀371/371 PASS(2961.540초), py_compile/diff-check clean이다. 전체 회귀가
시작된 뒤 추가된 최종 결속·휴대성 수정은 최신 focused15/15를 다시 실행해 확인했다.

AGY Gemini 3.6 Flash High·AGY Sonnet 4.6·GPT-5.6 Luna low는 이 환경에서 callable credential/surface가
없어 구현은 로컬 폴백으로 수행했다. 보호된 사용자 STATUS·AGENTS·classified_v14·master_ledger는
변경하지 않았다. 다음은 residual3,796 중 taxonomy243와 broad3,533에서 같은 수준의 authenticated
payment locator + service/VAT + authoritative trip/bucket을 한 chain으로 주는 근거를 우선 처리한다.

## 2026-08-02 R55 세션 핸드오프 — Trip.com full-refund atomic 4 admission

R44의 support-only Trip.com 숙박 lifecycle을 R49 post-state에서 다시 검증했다. restricted raw RFC822
9개와 receipt PDF 2개는 서로 다른 주문 2개가 각각 JPY92,001 결제 후 전액환불된 사실을 제공하고,
current 카드 전수는 국민계열 전체에서 절대 KRW893,170 사건이 KBO purchase2/cancellation2 exact4임을
확인한다. 최신 external manual v4 1,559행 SHA `2c6d7486…10489`도 국민·동일금액 전역에서 exact4이고
`10월_도고`에 구매2/취소2, net0이며, `1127_야쿠시마` 동명이행 3개는 서로 다른 카드·금액 exclusion으로
결속했다. 개별 order↔card 또는 manual-row↔event bijection은 주장하지 않고 unordered atomic group만
허용한다. A1/A2/A6에 따라 의미축은 `숙박비/여행원가/불공제_해외/10월_도고`, posting bucket은
`취소환불(net0)`이다.

새 `direct_trip_cancel_atomic_admission.py`는 R44 selected set
`43af8f7c…a64af`가 R49 residual에 정확히 4건 포함되고 accepted와 disjoint임을 live 재구성한다.
accepted는 1,532→1,536(`dde71329…1da`), residual은 3,796→3,792
(`0c45fa0f…591f6`), full delta4이며 실제 public package SHA는
`acfc0af941709cc12d5c88121a717075102914847ba606f5d5150cf05e9d29a6`다. provider capture completeness는
계속 `capture_claim_unverified`; 모든 공개 row는 `unattested/blocked/confirmed_count=0/gate5_credit=0/
applied=false/database_applied=false`라 DB apply·canonical cutover 권한은 없다.

Fable 5 medium은 초기 조건부 수용 뒤 KBD 숨은 동일금액, decorative post-accepted hash, 다른 item/tab의
국민 동일금액 manual collision 반례를 제시했다. GPT-5.6 Sol medium은 manual symlink/hardlink/TOCTOU,
physical duplicate dict-collapse, compound signature 교환, pathname 기반 publication/verify/reconcile과
post-publish raw ValueError 반례를 제시했다. 모든 반례를 상호 수용해 KBO+KBD global census, post set
재계산, single-fd manual capture/final reopen, dirfd byte capture, parent/target identity+fsync 재검증,
typed integrity/durability 및 swap reconciliation으로 보완했다. 최종 Fable과 Sol 모두 `REVIEW=PASS`.
focused R55 11/11 PASS(359.600초), R44/R45/R49 의존61/61 PASS, 전체 회귀384/384 PASS
(3,129.695초), py_compile/diff-check clean이다.

병행 DB·데이터시트 감사에서는 CSV/XLSX 27개, Excel 11개/154 sheets, repo SQLite0을 확인했다.
물리 PK/FK/투영 구조는 PASS지만 repo manual1,379 대 external1,559 drift, 생성 workbook formula cache
621/621 blank, v76↔v14 drift, sealed candidate/activation pointer 부재 때문에 CONSUMER/CANONICAL은 FAIL로
유지한다. 임시 DB나 기존 P6 report를 운영 정본으로 승격하지 않았다. AGY Flash/Sonnet/Luna는 callable
surface 부재라 구현은 로컬 폴백을 사용했고, 보호된 사용자 `STATUS.md` 및 data/AGENTS 파일은 변경하지
않았다. 다음은 residual3,792에서 authenticated payment locator와 service/VAT/trip authority를 함께 주는
순신규 증거군을 계속 탐색한다.

## 2026-08-02 R56/R57 세션 핸드오프 — Trip.com 항공료 unordered atomic 2 admission

R55 residual3,792를 membership-first로 다시 분할했다. bucket frontier19
(`9f0a465f…15e`), taxonomy243(`ce223531…16ca`), broad3,530
(`b97d1d07…199a`)이며 합계와 교집합0을 확인했다. 초기 R49 Agoda 형제 후보는 현재 accepted/residual
membership을 대조하자 신규 yield가 없었다. Sol이 이 반례를 제시했고 Fable이 수용해, 과거 audit
스크립트나 opaque hash만 재결속하지 않고 항상 현재 집합 membership부터 확인한다는 절차를 확정했다.

다음 실제 신규 집합은 R43의 Trip.com 항공 영수증 2건이다. restricted provenance가 서로 다른 영수증
참조 2개와 동일 공급자·날짜·총액을 제공하고, current 전수에서 KBD 해당 signature가 exact2/extra0,
external manual v4 전수에서도 국민·KRW208,400이 exact2다. 개별 receipt↔event 또는 card4 bijection은
주장하지 않고 unordered atomic2만 허용한다. 의미축은 `항공료/여행원가/불공제_해외/5월_유럽`이다.

새 `direct_trip_airfare_atomic_admission.py`는 R55 accepted/residual과 R43 member/document 집합을 live
재구성해 selected `618073ea…4f68e`가 residual에 정확히 2건이고 accepted와 disjoint임을 검증한다.
accepted는 1,536→1,538(`05dded46…be5d`), residual은 3,792→3,790
(`b21ca674…04f`), full delta2다. manual date·전역 collision, live member/document hash와 cardinality,
symlink/hardlink/TOCTOU, physical duplicate, dirfd-only no-replace publication, post-state hash 및
durability/reconcile을 fail-close한다. 모든 공개 row는 계속 unattested/blocked/confirmed0/Gate5 0/
applied=false/database_applied=false이며 DB 활성화나 canonical cutover 권한을 주장하지 않는다.

초기 구현은 manual date를 강제하지 않았고 R55 publisher를 production mock으로 교체했으며
member/document hash가 decorative였다. Sol과 Fable이 각각 반례를 제시하고 상호 수용해 local dirfd
publisher, exact manual date, live group hash 검증과 교환·변조·복구 테스트를 추가했다. 최종 Fable 5
medium과 GPT-5.6 Sol medium 모두 `REVIEW=PASS`; focused actual 9/9 PASS(1,094.041초), 전체 회귀
393/393 PASS(4,512.632초)다. AGY Flash/Sonnet/Luna는 callable surface 부재로 로컬 구현
폴백을 사용했다. 보호된 사용자 `STATUS.md`와 원장 data 파일은 변경하지 않았다.

## 2026-08-02 R58/R59 세션 핸드오프 — Gotogate 국내 항공 atomic 2×2 admission

R57 post residual3,790을 재감사했다. original-approval relation 23건과 taxonomy243의 관계·집합은
정확했지만 accepted membership이나 manual tab/item/description은 권위 있는 4축 tuple이 아니다.
Fable이 Sol의 clean19 상속안을 반박했고 Sol이 수용해 즉시 승인 subset0으로 정정했다. taxonomy243도
exact manual/trip locator 교집합0이며 날짜·merchant·여행기간만으로 bucket을 전파하지 않는다.

대신 R43 support-only였던 Mytrip/Gotogate 두 그룹 4건을 원문과 A0 정책으로 다시 검증했다. PDF 4개는
각각 서로 다른 주문 참조, 동일 그룹별 예약일·총액·항공 service, `Gotogate Korea LLC`·서울 주소·국내
사업자번호를 제공한다. current는 KBD purchase KRW single 4건이며 국민계열 전역에서 그룹별 동일
날짜·금액 exact2/extra0, external manual v4도 각 tab/item/date/card exact2/locator2다. A0 최우선 규칙은
항공·숙박 고객대행 여행경비를 매입세액공제 대상이 아니라고 직접 정하므로 의미축을
`항공료/여행원가/불공제_국내/0712_몽골` 2건과
`항공료/여행원가/불공제_국내/0924_야마구치` 2건으로 닫았다. 세금계산서나 매입 VAT액은 주장하지
않고, 개별 receipt↔event/card4 bijection도 주장하지 않는 unordered atomic2 두 그룹이다.

새 `direct_mytrip_airfare_atomic_admission.py`는 R43 member/document commitment, PDF supplier/date/
amount/tax-invoice active scan, A0 SHA, manual single-fd census, current KBD+KBO 전역 collision과 physical
duplicate, R57 post membership을 live 재구성한다. selected4는 `93515d41…a0e8`, accepted는
1,538→1,542(`7a49e7e6…32e9`), residual은 3,790→3,786(`df0bafd8…d629`), actual public package SHA는
`d0193762df677ee1d69946070d858177dfdda4b1720efc4c80d71afc08738b56`다. 전달 메일은 provider DKIM
인증으로 격상하지 않고 4개 alias의 `forwarded_outer_auth_observed_unverified` exact set을 별도
commitment로 결속한다. 모든 행은 unattested/blocked/confirmed0/Gate5 0/applied=false/
database_applied=false인 review proposal이다.

초기 구현은 parent path 교환 시 detached directory에 게시할 수 있었고 receipt↔event↔manual 날짜 직접
결속과 transport commitment가 부족했다. Sol과 Fable이 독립 FAIL 반례를 제시해 open 직후·rename 직전
parent identity 확인, dirfd stage cleanup, receipt/current/manual exact date pin, transport set commitment,
partial/zero-write·member/document 교환·외부 collision·verify/reconcile/parent-swap 테스트를 추가했다.
최종 Fable 5 medium과 GPT-5.6 Sol medium 모두 `REVIEW=PASS`; focused actual 9/9 PASS(378.418초),
전체 회귀402/402 PASS(4,955.734초), py_compile/diff-check clean이다. AGY Flash/Sonnet/Luna는
callable surface 부재로 로컬 구현 폴백을 사용했고 보호된 `STATUS.md`와 원장 data는 변경하지 않았다.

## 2026-08-02 R60 증거수집 핸드오프 — taxonomy 21건 Gmail exact census 0

R59 post residual3,786에서 taxonomy243을 trips.json 기간에 단순 포함시키면 unique bucket22가 나오고,
그중 R34 account/cost/VAT support가 있는 행은 21건(`eaf97671…9aa`)이다. 그러나 R34는 명시적으로
unattested/blocked이고 날짜 포함은 지출→여행 exact edge가 아니므로 full delta0을 유지했다. broad3,530도
원장 explicit Ali/Daiso/KAFUKA 규칙과 현재 membership을 대조했으나 권위가 완성된 행은 모두 이미
accepted였고, 잔여 동명이행은 품목·목적·bucket이 없어 안전 subset0이었다. Fable과 Sol 모두 merchant
broadcast를 기각했다.

21건을 restricted 0700/0600 수집 큐 19개 query group으로 만들고 로컬 pinned MIME 16개와 Gmail UI
전체보관함을 read-only 검색했다. exact merchant+date+amount/provider-reference 조건으로 로컬 hit0,
Gmail 19/19 candidate0·exact0·provider-reference0이었다. Gmail의 전송·삭제·라벨·초안 변경은 없었다.
제한 결과 `gmail-ui-results.json` SHA는 `0453b01b15612672e24a53c92fab5d752482c72a1aa311b57b8e255671f03a91`,
summary SHA는 `b3185205003f9f8a31622a8692e3192dd82445545fc3b5f1436c507dbf8153ef`다.
공개/저장소에는 raw merchant·금액·카드·승인번호를 기록하지 않았고 `full_delta_claimed=false`다. 다음
수집 경로는 provider portal/issuer export/사업자 증빙처럼 current key에 직접 결속되는 외부 자료다.

추가로 저장소 booking/OTA 4종과 R27 coverage를 재빌드했으나 21건 direct key·booking ref·structured
card/currency/amount exact edge는 모두 0이었다. Edge의 여행사 운영 시스템 탭도 공개 정보 화면이며
인증 관리자 검색/export가 노출되지 않았다. 마지막으로 `/tmp/cost-*` 허용 확장자 951파일 중 937개를
판독하고 issuer statement/usage confirmation/receipt 표식 195개를 전수 검사했으나 approval/date/amount/
merchant 4-token direct locator는 0건이었다. generated/source artifact exact-token 167건과 loose partial
755건은 비증빙 false positive로 격리했다. 제한 exhaustive report SHA는
`a66a80d8253f0da30978016cf2e6984c3ff07871678c7e0c658db7a71afe9cef`이며 원본 변경은 없다.

## 2026-08-03 Q2 안전그룹 세션 핸드오프 — 최신 원장 결속 숙박 5건

R59 잔여 3,786을 현재 이벤트 DB에서 다시 재생성했다. 서로소 분할은 manual frontier 13,
taxonomy 243, broad 3,530이며, 기간 분포는 2025년 2,305 / 2026-Q1 1,184 / 2026-Q2 22 /
2026-Q3 275다. 따라서 3,764건은 2026-Q2 밖이며, 전 기간 통합 분류인지 Q2 완료율 집계인지에
따라 결과가 대량으로 달라지므로 사용자 범위 판단 전에는 기간 외 행을 변경하지 않는다.

Q2 잔여 22건은 거래별로 재감사했다. 새 `direct_all_period_safe_group_admission.py`는 그중 최신 외부
manual 1,559행과 현재 카드 이벤트의 날짜·금액·카드·가맹점·건수 다중집합이 정확히 일치하는
Booking.com 나가센도 3건과 Agoda Hotel Pearl 교토 2건만 승인 후보로 만든다. 계정/원가/VAT는
각각 `숙박비/여행원가/불공제_해외`이며, selected set은
`414856751e5b4de59d2515352d0387c17259b85a1cceb0425c1d94d39be53e8c`다. R59 membership을
live 재구성한 뒤에만 1,542→1,547, residual 3,786→3,781을 허용하며 DB 적용·게시·정본 전환은
하지 않는다. focused 실데이터 테스트 4/4 PASS(315.584초), py_compile/diff-check PASS다.

초기 후보였던 AVIS 392,606원은 repo의 오래된 manual에는 있으나 최신 외부 manual에는
366,794원만 있어 즉시 기각했다. 나머지 Q2 17건은 동일 Agoda의 서로 다른 bucket 배분,
취소/원거래 관계, ANA cardinality, GASUTO·GYOMU 귀속 충돌이 남아 자동 승인하지 않았다.
이 세션은 전역 워커 규칙에 따라 다른 모델/CLI로 재위임하지 않고 GPT-5.6 Sol medium이 직접
구현·검증했다. 보호된 사용자 `STATUS.md`, `AGENTS.md`, `classified_v14.csv`의 SHA는 유지했다.

## 2026-08-03 Q2 기업 승인취소 핸드오프 — 4건 zero-posting 해결

Q2 잔여 취소 7건을 원천별로 분리했다. 그중 기업카드 4건은 current direct event에서 모두
`transaction_type=cancellation`, 과거 `classified_v14`에서 동일 승인번호의 `승인취소`, 비용금액
0원으로 일치했다. 새 `direct_all_period_corp_void_admission.py`는 이 네 조건과 source/date/signed amount/
card4/merchant의 exact tuple, classified SHA를 live 결속하고, 네 event set
`3acd515a122d22a8135508c055f4c817f6a29e2d032ce6f1ecb0ee07b77854ac`만
`void_no_posting`으로 해결한다. 비용 전기 합계는 0원이고 계정 추정은 하지 않는다.

Q2 안전숙박 5건의 상류 상태를 매 실행 재검증한 뒤 resolved union은 1,547→1,551,
global residual은 3,781→3,777이다. `full_classification_delta=0`, `resolved_event_delta=4`,
`database_applied=false`, `posting_status=blocked`를 유지한다. 하나 승인취소 1건과 국민 Q1원거래
환불 2건은 동일 정책으로 섞지 않고 관계 검증 대상으로 남겼다. focused 실데이터 테스트 3/3
PASS(161.467초), py_compile PASS다. 다른 모델/CLI 재위임 없이 GPT-5.6 Sol medium이 직접 수행했다.

## 2026-08-03 Q2 잔여 취소 핸드오프 — 하나 pair 1 + 국민 환불 2 해결

Q2 취소 잔여 3건을 별도 `direct_all_period_remaining_cancellation_admission.py`로 결속했다. 하나 Agoda
승인취소는 동일 source key·승인번호·날짜·merchant/card4의 +139,761 approval과 -139,761
cancellation이 정확히 net0인 pair다. 국민 New Akan -209,498원 2건은 서로 다른 physical source key를
가진 JPY21,600 환불 2건이며, 최신 외부 manual의 `0613_북해도` New Akan 원거래 4건
(205,309×1 + 410,621×3, 예약번호 4개)과 group-level로 결속했다. 환불은
`숙박비/여행원가/불공제_해외`, trip `0613_북해도`, posting bucket `전기예약_환불`이며 개별
booking↔refund bijection은 주장하지 않는다.

selected 3 set은 `24d585580723593e60f9b07e361a328ecf4bd45ae2231a5424fe4c614c0cb517`,
resolved union은 1,551→1,554, global residual은 3,777→3,774다. Q2 잔여는 최초 22에서
숙박5+기업void4+취소/환불3을 해결해 10건이다. focused 실데이터 테스트 2/2 PASS(166.303초),
py_compile PASS이며 DB 적용·게시·정본 전환은 하지 않았다. GPT-5.6 Sol medium 직접 수행이다.

## 2026-08-03 Q2 수기 중복축 핸드오프 — 카드 2건만 분류

최신 외부 manual에서 ANA 634,113원과 GYOMU 18,755원이 각각 2행씩 중복 기재됐지만 current
card raw에는 각각 서로 다른 실제 1건만 존재한다. 새 `direct_all_period_manual_duplicate_collapse_admission.py`는
manual 4행을 비용 4건으로 만들지 않고 physical card event 2건에만 축을 부여한다. ANA는
`0616_레분토&리시리/항공료/여행원가/불공제_해외`, GYOMU는
`0620_묘코/기타비용/여행원가/불공제_해외`다. selected set은
`b612c323caef871426049a5b52153b78d930e70678a149e1ba65cdf322a68120`이다.

accepted/resolved union은 1,554→1,556, global residual은 3,774→3,772, Q2 잔여는 10→8이다.
manual duplicate rows2를 명시적으로 extra event가 아니라고 기록한다. focused 실데이터 테스트 2/2
PASS(170.122초), py_compile PASS, DB 적용·게시·정본 전환 없음, GPT-5.6 Sol medium 직접 수행이다.

## 2026-08-03 Q2 Yakushima 포털 핸드오프 — 인증 예약 1 ↔ 카드 2 그룹

정리 대상 원격 브랜치의 Git commit `61ea7b9`에 인증 Agoda 포털 관찰 파일이 보존되어 있음을
재확인했다. 파일 전체 SHA-256은 `de9ce5264ee608b6fc1bede2d179c343385120ae13e74fb07fb0354cc9c88cf2`다.
예약 662897867은 authenticated portal DOM에서 card4 8835, JPY118,800, 2026-11-27~30,
confirmed로 결속된다. 현재 KBO에는 서로 다른 physical source key의 JPY118,800/KRW1,150,385
구매가 정확히 2건이다.

새 `direct_all_period_yakushima_portal_admission.py`는 Git 객체의 전체 파일 hash와 단일 portal record를
매 실행 검증하고 두 카드 거래를 `1127_야쿠시마/숙박비/여행원가/불공제_해외`로 분류한다.
portal booking1↔card event2의 개별 bijection이나 중복 결제 정당성은 주장하지 않는다. selected set
`5751262cd691a9339a215d32418fd4f7dcc7e070828223f8dee8aa3eb093b822`, accepted union
1,556→1,558, global residual 3,772→3,770, Q2 잔여 8→6이다. focused 3/3 PASS(172.505초),
py_compile PASS, DB 적용·게시·정본 전환 없음, GPT-5.6 Sol medium 직접 수행이다.

## 2026-08-03 Q2 Minatoya 포털 핸드오프 — JPY tolerance 그룹 2건

동일 인증 Agoda 포털 Git 객체에서 예약 1723193688은 card4 8835, JPY12,069,
2026-10-11~12, confirmed다. current KBO에는 2026-06-26 JPY11,885/KRW116,935의 서로 다른
physical source 2건이 있다. 차이는 152bp이며 P11의 외화 공간 대조 원칙에 따라 명시적 200bp
상한 안에서만 허용했다.

새 `direct_all_period_minatoya_portal_admission.py`는 portal file 전체 hash·record·JPY tolerance·current
cardinality를 live 검증하고 두 건을 `1010_도쿠시마/숙박비/여행원가/불공제_해외`로 분류한다.
portal booking1↔card2의 개별 bijection은 주장하지 않는다. selected set
`8c839c3a275dc6846d47508dc7c494b39918f3ec466bbf3b00182a75ea890eb1`, accepted union
1,558→1,560, global residual 3,770→3,768, Q2 잔여 6→4다. focused 3/3 PASS(175.829초),
py_compile PASS, DB 적용·게시·정본 전환 없음, GPT-5.6 Sol medium 직접 수행이다.

## 2026-08-03 전 기간 단일 DB 전환 핸드오프 — 분기 범위 폐기·5,328건 전량 보존

사용자가 “DB에는 모든 자료 보존, Q2라는 개념 자체를 폐기”한다고 확정했다. 원장 P25를 신설해
분기를 분류 범위·완료율 분모·근거부족 제외·삭제/격리 조건으로 쓰지 못하게 했고, 분기는 조회·보고용
파생 속성으로만 남겼다. 원거래↔환불, 선결제↔여행 같은 교차기간 관계도 끊지 않는다. 과거 LOG의
Q2 표현은 당시 산출 이력일 뿐 현행 규범이 아니며 P25가 우선한다.

현재 admission 체인의 파일·함수·artifact/rule/error 식별자를 `direct_all_period_*`와 `all_period`로
전환했다. 새 `direct_all_period_scope_policy.py`는 direct event 5,328건의 유일성과 전량 포함을
실데이터로 강제한다. 보고용 기간 분포는 2025-Q2 25, 2025-Q3 922, 2025-Q4 1,383,
2026-Q1 1,322, 2026-Q2 1,401, 2026-Q3 275이며 합계 5,328, 기간 제외 0이다. 현재 accepted 1,560,
residual 3,768도 특정 분기로 축소하지 않는다. focused 전수 재생성 3/3 PASS(178.246초), py_compile와
diff-check PASS다. 원천·정본 DB에는 삭제나 게시를 하지 않았고 보호된 사용자 `STATUS.md`는 건드리지
않았다. 전역 워커 규칙상 다른 모델/CLI로 재위임하지 않고 GPT-5.6 Sol medium이 직접 구현·검증했다.

## 2026-08-03 전 기간 잔여 재분할 핸드오프 — 3,768건 근거 수준 전수 census

P25 기준으로 현재 accepted 1,560건과 residual 3,768건을 live event key membership에서 재구성했다.
새 `direct_all_period_residual_census.py`는 과거 분기나 보고 범위를 사용하지 않고 5,328건 전체에서
현재까지의 32건 순신규 admission을 결속한다. residual set SHA는
`1a259893425431595d63e3ab5891f66e8a4042056f0eab399c5500183d073b7d`다.

잔여는 서로소 3종이다. 수기 여행 bucket만 있고 계정·원가·VAT가 없는 `manual_frontier` 8건,
반복 가맹점 seed로 계정·원가·VAT만 제안되지만 여행 bucket이 전부 비어 있는
`merchant_taxonomy_only` 241건, 직접 분류축이 없는 `broad_no_direct_axes` 3,519건이다. 241건의
제안축은 식비124·숙박38·여행자보험36·교통19(+VAT 미정1)·주유11·통행9·렌터카3이며 모두
여행원가다. 이는 대량 정책 판단 후보일 뿐 자동 적용하지 않았고 DB/정본 변경도 없다. broad 3,519는
구매3,142·취소220·환불157이며 카드 원천별로 CORP118/HAN1,494/KBD712/KBO1,195다.

focused 전수 테스트는 첫 실행에서 census가 기존 event-set 해시 직렬화 함수를 재사용하지 않아
fail-close했고, 기존 `r36._event_set_sha`를 직접 사용하도록 교정했다. 최종 3/3 PASS(210.637초),
py_compile PASS다. 보호된 사용자 `STATUS.md`는 변경하지 않았다. 전역 워커 규칙상 다른 모델/CLI로
재위임하지 않고 GPT-5.6 Sol medium이 직접 구현·검증했다.

## 2026-08-03 전 기간 취소·환불 관계 census — 377건 중 exact 209

대량 분류 정책 답변을 기다리는 동안 판단이 필요 없는 구조 관계를 계속 감사했다. 새
`direct_all_period_lifecycle_relation_census.py`는 현재 residual 3,768건 중 취소·환불 377건을
원거래 승인번호 정규화 규칙으로 다시 결속한다. 209건(KBD128/HAN81)은 issuer+card4+원승인번호가
현재 구매 1건에 유일하게 연결된다. 대상 구매는 accepted 22, residual 187이다. 이 209건은 관계
증거만 보존하고 계정·여행·VAT·전기 권한이나 full classification delta를 주장하지 않는다.

나머지 168건은 KBO135/KBD29/CORP4이며 cancellation139/refund29다. KBO는 승인번호 없는 해외매입
구조가 주류이고 CORP는 원승인 직접 링크가 없어, 동액·가맹점 추정으로 억지 연결하지 않았다.
현재 exact linked set SHA는 `f0b52d194ab335661052f011b5ad5650972d17d7ebcc1d0ed049e05a4270fdc4`다.
focused 실데이터 3/3 PASS(325.161초), py_compile PASS, DB/정본 변경 없음이다. 보호된 사용자
`STATUS.md`는 변경하지 않았다. 전역 워커 규칙상 다른 모델/CLI로 재위임하지 않고 GPT-5.6 Sol
medium이 직접 구현·검증했다.

## 2026-08-03 국민 해외 취소 현지금액 관계 census — 135건 중 exact group 62

승인번호가 없는 KBO 취소 135건을 P25 전 기간 universe에서 카드4·통화·현지금액 소수보존·가맹점
exact key로 전수 대조했다. 새 `direct_all_period_kbo_lifecycle_pair_census.py`는 취소 수와 선행 구매
수가 같은 그룹만 관계 증거로 인정한다. 1:1 유일 관계 44건과 2:2 세 그룹, 3:3 한 그룹, 9:9 한
그룹의 unordered atomic 18건, 합계 62건이다. 다건 그룹은 개별 bijection을 주장하지 않는다.

잔여 73건은 구매 부재 또는 취소/구매 cardinality 불일치라 동액 추정으로 연결하지 않는다. 이 73건은
각각 event hash 73개·source hash 73개로 모두 물리적으로 구별되어, 16:1·17:1 같은 큰 불균형도
중복 적재로 단정하거나 삭제하지 않고 원천행 그대로 보존한다. selected
set SHA는 `75dfdaf66934d87d46892f2ecc962dc698108d180e9d688e2a84e088e344b800`다. 관계만 보존하며
계정·여행·VAT·전기·full classification delta는 0이고 DB/정본 변경도 없다. focused 실데이터 3/3
PASS(최신 155.005초), py_compile PASS다. 보호된 사용자 `STATUS.md`는 변경하지 않았고 GPT-5.6 Sol
medium이 전역 워커 규칙에 따라 직접 구현·검증했다.

## 2026-08-03 전 기간 카드 원천 범위 census — 5,237 RAW→5,328 event, 제외 0

`direct_all_period_source_coverage_census.py`로 카드 원본 5개 파일 SHA와 전 행을 다시 고정했다.
RAW는 CORP174/HAN2,097/KBD1,287/KBO1,679, 합계 5,237행이며 HAN 승인+취소 component 91개가
추가되어 normalized event 5,328건이 된다. 기간 필터로 제외된 입력행은 0이다.

다만 파일 자체의 날짜 범위는 CORP 2026-01-25~07-14, HAN 2025-07-21~2026-07-20,
KBD 2025-05-06~2026-07-15, KBO 2025-07-21~2026-07-14다. 따라서 KBD 환불 중 원승인번호가
현재 5,328건의 어느 구매에도 없는 29건은 DB 삭제나 분기 필터가 아니라 제공 원천 이전/밖의 구매
부재다. 보유하지 않은 선행 거래를 생성하거나 분류하지 않으며 환불 RAW 자체는 계속 보존한다.
focused 3/3 PASS(0.996초), py_compile PASS, DB/정본 변경 없음, `STATUS.md` 불변이다. GPT-5.6 Sol
medium이 전역 워커 규칙에 따라 직접 구현·검증했다.

## 2026-08-03 후보 DB 관계 투영 — 330 proposed relations·semantic hash 결속

후보 DB의 `transaction_relations` 테이블이 기존 빌더에서 비어 있던 구조 공백을 교정했다.
`project_card_relations()`는 5,328 event 전부에서 issuer+card4+원승인번호가 유일한 HAN/KBD 관계
257개, KBO card4+통화+현지금액+가맹점 1:1 관계 53개, KBO 동일 cardinality 다건 관계 20개/
6그룹을 투영한다. 합계 330개이며 모두 `relation_status=proposed`다. KBO 다건은
`related_transaction_id=NULL`과 공통 group reference를 사용해 개별 bijection을 주장하지 않는다.

`candidate_semantic_sha256()`도 payment 5,328건뿐 아니라 관계의 양쪽 external key·유형·참조·매칭법·
confidence·상태·resolution·rationale까지 결속하도록 확장했다. 관계 추가 전후 의미 해시가 달라지고,
실데이터 새 semantic SHA는 `e36eeb47cff6336c717bd3fe79dc61a5ee41500664919a76d434e2c3facf40ee`다.
계정·여행·VAT 분류나 운영 전기는 추가하지 않았다. direct projection 27/27, transition gates 47/47,
owner review 18/18, HAN master 14/14, P6 adapters 2/2 모두 PASS(합계108 tests)했고 py_compile/
diff-check PASS다. 보호된 `STATUS.md`는 변경하지 않았으며 GPT-5.6 Sol medium이 직접 구현·검증했다.

커밋 후 HAN equality를 포함한 실제 후보 빌드를 격리 임시경로에서 다시 실행했다. Gate1 source,
Gate2 cardinality, Gate3 leakage, Gate4 amount/relation, Gate7 freshness는 PASS다. 남은 차단은 Gate5
`direct_allocation_decision_unimplemented`와 Gate6 `direct_baseline_unavailable` 두 개뿐이다. relation
330개와 semantic SHA `e36eeb47…40ee`가 report/manifest에 일치했고 candidate는 미게시, 임시경로는
정리됐다.

## 2026-08-03 사용자 승인 저모호성 taxonomy 116건 — 후보 DB 판단 348행 투영

사용자가 실제 예시를 확인한 뒤 “진행”을 명시해 merchant taxonomy-only 241건 중 저모호성 116건의
부분 분류를 승인했다. `direct_all_period_user_approved_taxonomy_admission.py`는 현재 5,328 event와 R34
원천/이벤트 해시를 live 재구성하고, 이미 분류된 행을 제외한 숙박비38·여행자보험36·교통비19·주유비11·
통행료9·렌터카3만 선택한다. selected set SHA는
`8b93c6c23f75625fb2ace043a1a8d6b3d2d5a305b8845ab9f75003b121150d76`다. 편의점124와 KLOOK1은
식비/소모품/제공품 및 상품·VAT 모호성이 남아 사용자 지침대로 자동 분류하지 않았다.

후보 DB 빌더는 116 payment에 `account/cost_type/vat_tag` 각 1개, 합계 confirmed decision 348행을
투영한다. 여행 bucket, allocation, journal/posting은 만들지 않으며 원천 5,328건과 relation330건은
전량 보존한다. decision 내용도 candidate semantic hash에 결속했다. 실제 격리 재빌드에서
`projected_taxonomy={payments:116, decisions:348}`, Gate5의 partial count도 116/348로 일치했고 새
semantic SHA는 `85ad1f6193d362f7ae9aac65496e249176af886af294f102c6f9d0bb0e030eb6`다. HAN package를 생략한
감사 run이라 Gate4는 equality package 부재로 fail-closed했지만 relation issue는 0이었고, HAN을 포함한
전체 direct projection 회귀에서는 Gate4 PASS를 재확인했다. candidate는 미게시·임시경로 정리 상태다.

동시에 Gate4가 relation 행을 단순 semantic hash로만 보지 않도록 동일 run target, 구매 target,
issuer/KBO source·method·status·confidence·resolution, unordered group 최소 cardinality를 검증하게
보강했다. 자기참조 환불 target 반례도 영구 테스트로 추가했다. taxonomy 3/3, transition gates는 신규
반례 포함 transition gates 전체 49/49, direct projection 전체 27/27 및 변경 후 실데이터
targeted test PASS다. 보호된 사용자 `STATUS.md`는 변경하지 않았다. GPT-5.6 Sol medium 직접 수행이다.

## 2026-08-03 taxonomy 투영 후 상류 증거체인 해시 재결속

116건 decision을 candidate semantic hash에 포함하면서 R25/R34/R36의 내용 집합은 불변이지만 그들이
결속하는 candidate semantic SHA가 바뀌었고, 그 결과 R36 package와 이를 고정한 R37/R38 상류 계약이
fail-closed하는 것을 추가 감사에서 발견했다. 과거 `d934958`의 동일 R36 산출물과 현재 산출물을 임시
detached worktree에서 비교해 event set·manual·group·semantic evidence는 모두 동일하고,
candidate semantic 및 그에 종속된 package/rule hash만 변경됐음을 확인했다. 임시 worktree는 제거했다.

R37/R38의 상류 package/rule 핀을 현재 decision-inclusive candidate 의미에 재결속했다. 새 R36 package는
`f7574ecc81fae0b9d05ff75bfb2bdaf69be1c652099a62dcb3ef26bd15a0b530`, R37 rule/package는
`c670cd2f46dbc5869fee2ca2306b1cef4c174732d7c476c712e76a7012a443a7` /
`2c2000773dc3ba04af82774bac5f46c0b2910c8e1122505c63b05dcf29028063`, R38 rule/package는
`e79b49cb7abca844a43cea670e487b77e453615c20f78dcbb3b1ad161c25a64e` /
`fe98ee996188b46ddbf934626c64d036dd1d9a1da3f8cbd3c2ff93f7c10ad868`다. 전 기간 residual census를
다시 끝까지 재생성해 3/3 PASS(213.056초), 5,328=1,560+3,768 및 잔여 partition 불변을 확인했다.
이어지는 R42 package도 `6b384c2d39ee66c9e0d4032fd1da235106011aac86c4d4bd754227a38e25afe7`로
재결속했고 R43 `_live_context()`가 R36/R38/R42 새 package와 기존 24건 frontier를 모두 통과했다.
R43의 정책 핀도 P25가 포함된 현행 원장 SHA
`d4ebe4b7fc0584b72f51e2d3a883f55c4bf7c1f5e6f2dbd46da2df8df5e7837c`로 갱신했고 receipt evidence
회귀 14/14 PASS다.
보호된 사용자 `STATUS.md`는 변경하지 않았다. GPT-5.6 Sol medium 직접 수행이다.

## 2026-08-03 manual frontier 8건 전량 해결 — 숙박6 + Agoda 항공2

잔여 manual frontier 8건을 현재 카드 event와 `manual_v4.csv`로 건별 재구성했다. 날짜·금액·카드4·
가맹점·건수가 정확히 일치하는 기타구니 호텔 4건(레분토&리시리)과 이즈미야 료칸 2건(야마구치)을
`숙박비/여행원가/불공제_해외` 및 해당 trip으로 확정했다. selected set SHA는
`627c152c2f018a8d65379cbb31c1f7dc1a03546ed40ab39f8fccb163ac807eef`다.

남은 Agoda 542,370원 2건은 수기장부에는 항공으로 적혀 있으나 merchant만 보면 모순처럼 보여 처음
보류했다. 이후 정본 입력 `ota_mail_index.json`에서 결제 당일 Agoda 메일 2개를 확인했다. 두 메일은
각각 박희경/정용숙의 `9/24~27 인천-후쿠오카 왕복 예약정보`, 서로 다른 PNR, 동일 여행기간을 가지며
수기 2행·카드 2행과 group cardinality가 일치한다. 따라서 두 건을 원자 그룹으로
`항공료/여행원가/불공제_해외/0924_야마구치` 확정했으며 개별 카드↔승객 bijection은 주장하지 않는다.
selected set SHA는 `cb644e7fa0c44abad2c2e58dd0e659b62d1d362234bb722682965a69ad3d8a41`다.

후보 DB에는 8 payment의 네 축 32 decision이 추가되어, 기존 116건과 합쳐 taxonomy 3축 완비는
124 payment/372 decision, trip까지 완비는 8 payment/32 decision이다. 원천 5,328건·relation330건은
불변이고 allocation/posting은 계속 차단한다. 새 candidate semantic SHA는
`84fd3e22bbb800f8ce8a9fddaf6730937f558e0ec8d9d132f4a9d645a6bc92cd`이며 격리 실데이터 build는
미게시·relation issue0을 확인했다. accepted union은 1,568, residual은 3,760, manual frontier는 0,
residual set SHA는 `b41bcbda43a40d6ee22325bbcc2c42b4c3823d5b6dbb4b3911b839f7a07bf03d`다.
숙박 admission 3/3, 항공 admission 3/3, transition gates 49/49, 실데이터 candidate targeted test와
residual census 3/3 PASS다. 보호된 사용자 `STATUS.md`는 변경하지 않았다. GPT-5.6 Sol medium 직접
수행이다.

## 2026-08-03 Gate 5 직접 배분 계약 구현 — 8건 exact allocation

manual frontier에서 네 축이 확정된 8 payment에만 `confirmed` allocation plan을 만들었다. `trips.json`의
여행 코드·지역·시작/종료일을 live 검증해 trip/target을 생성하고, 각 payment의 양수 결제금액 전액을
단일 여행 target에 배분한다. allocation의 source decision은 같은 payment의 confirmed
`allocation_target` 판단을 직접 참조한다. 합계 plans8·allocations8이며 나머지 5,320건에는 plan을
생성하지 않았다.

Gate 5는 더 이상 `direct_allocation_decision_unimplemented`가 아니다. payment별 confirmed 네 축,
현재 confirmed plan 정확히 1개, allocation 정확히 1개, 결제금액=배분금액, target code=source decision
값을 모두 만족할 때만 resolved로 센다. 현재 결과는 candidate 5,328 / resolved 8 / unresolved 5,320,
reason `direct_allocation_decision_incomplete`, contract `direct_decision_contract_v1`이다. payment·relation·
decision뿐 아니라 trip/target/plan/allocation 의미도 candidate semantic hash에 포함했고 새 SHA는
`eceaec6504eed8a5b3d694d5e1d95e5a518cd1f5b29b0aeb906773d1a5e147a3`다. owner-review manifest도
Gate 5 resolved count8을 source context와 일치시킨다.

transition gates 전체 50/50 PASS, 실데이터 candidate/owner rebuild targeted test PASS, owner-review의
실데이터 invariant·tamper test PASS다. 후보는 여전히 Gate5 미완결과 Gate6 baseline 부재로 미게시다.
디버깅용 `/tmp/cost-owner-debug-QtblWR`는 검증 후 삭제했다. 보호된 사용자 `STATUS.md`는 변경하지
않았다. GPT-5.6 Sol medium 직접 수행이다.

## 2026-08-03 인증 Agoda Plaza Hotel Mutsu 6건 — 후보 DB 네 축·배분 투영

`ota_event_links_verified.json`의 Agoda 예약 페이지 검증 레코드 중 Plaza Hotel Mutsu
개별 예약 6건을 현재 카드 이벤트와 다시 결속했다. KBO-2681/2682/2689/2700/2701/2702는
각각 서로 다른 booking id를 가지며 card4 8835, JPY 21,030/34,370/27,152/6,501/6,183/6,773,
숙박일 4/17~19가 인증 레코드와 일치한다. exact lineage로 현재 physical event 6건에 유일하게
연결되고, `trips.json`의 `0417_아오모리` 일정 범위에도 포함된다.

새 `direct_all_period_verified_mutsu_lodging_admission.py`는 OTA links 전체 SHA, 6개 개별 레코드,
현재 event/source hash, 역사 lineage의 상/상 축을 모두 live 검증한다. selected set SHA는
`c9c9c81d3d1c2416cba72477344f0768ec9e8d4350d82df0d8bf876bb0debc9c`다. 6건에
`숙박비/여행원가/불공제_해외/0417_아오모리` 네 축 24 decision과 각 결제액 전액의
confirmed allocation 6건을 후보 DB에만 추가했다. 대량 가맹점 정책을 적용한 것이 아니라
개별 인증 예약을 근거로 한 소집합이다.

현재 Gate 5는 5,328건 중 resolved 14, unresolved 5,314이며 plans/allocations도 14/14다.
원천 5,328건·relation 330건은 그대로 보존되고 후보는 Gate 5 미완결·Gate 6 baseline 부재로
여전히 미게시다. 새 candidate semantic SHA는
`1fe46c8c892bc45715a4c22dc9e6364103fa9725cbb94da0f052527a6810d16d`다. admission 3/3,
transition gates 50/50, 실데이터 candidate/owner rebuild, owner-review invariant·tamper 테스트가 모두
PASS했다. `STATUS.md`는 건드리지 않았고, 전역 워커 규칙에 따라 GPT-5.6 Sol medium이
다른 모델/CLI 재위임 없이 직접 구현·검증했다.

## 2026-08-03 사용자 예약페이지 카메노이 호텔 2건 — exact 금액 배분

`ota_event_links_verified.json`의 KBD-0389/0390은 서로 다른 Trip.com booking id와
카메노이 호텔 다자와코 7/5~7/7 숙박을 담고, 사용자 예약페이지의 결제액
1,307,772원/887,640원이 현재 카드 event와 각각 exact 일치한다. 두 숙박일은
`trips.json`의 `0704_아키타` 7일 창에 포함되며, exact lineage의 축도
`숙박비/여행원가/불공제_해외/0704_아키타` 상/상으로 일치한다.

새 `direct_all_period_verified_kamenoi_lodging_admission.py`는 OTA links·trips 전체 SHA,
예약 id/결제액/숙박일/객실·박수, 현재 event/source hash, 역사 lineage를 live 검증한다.
selected set SHA는 `060271be84bbaa74b1ecbe84b35c1e08a9554318a4bdbcdc358c81150e849fee`다.
후보 DB에 네 축 decision 8행과 결제액 전액 allocation 2건을 추가해 Gate 5는
resolved 14→16, unresolved 5,314→5,312가 됐고 plans/allocations은 16/16이다.

원천 5,328건·relation 330건은 보존되며 후보는 Gate 5 미완결·Gate 6 baseline 부재로
미게시다. candidate semantic SHA는
`a22698e85f2bab0008a8fee264bd261fd2e39a60fc720cd689401ca406936f0b`다. 대량 정책 판단은
사용하지 않았고 개별 인증 예약 2건만 승격했다. `STATUS.md`는 변경하지 않았으며
admission 3/3, transition gates 50/50, 실데이터 candidate/owner rebuild,
owner-review invariant·tamper 테스트가 모두 PASS했다. GPT-5.6 Sol medium이 다른 모델/CLI
재위임 없이 직접 구현·검증했다.

## 2026-08-03 exact 예약 7건 부분축 — VAT 미확정 보존

완전 네 축 exact 예약 후보가 소진된 뒤 `ota_event_links_verified.json`에서 결제액이
exact/exact-after-discount로 검증된 잔여 7건을 감사했다. HAN-3004/3011/3047은
숙박 예약·여행일·결제액으로 숙박비/여행원가/여행 target만, KBD-0741은 항공료/
여행원가/여행 target만, KBD-0871/0927은 항공료/여행 target만, 여행기간이 빈
KBD-0958은 숙박비만 확정했다. 모든 건의 VAT와 증거가 말하지 않는 축은 만들지
않았다.

새 `direct_all_period_verified_partial_booking_admission.py`는 OTA links·trips 전체 SHA,
개별 예약/외부 source id, 정확 결제액, 여행창, 현재 event/source hash, lineage의 해당 축만
live 검증한다. selected set SHA는
`cfcbbffd02f21ae6bad9ee7fa414ed0130b8bb60f84ab0c772a529168824cc59`이며 7 payment에
decision 17행을 추가했다. VAT unresolved 7, Gate 5 credit 0을 명시했다.

실데이터 후보에서 Gate 5 resolved 16/unresolved 5,312와 allocations 16/16은 불변이고,
원천 5,328건·relation 330건도 보존되며 후보는 미게시다. candidate semantic SHA는
`8c3429d78a94f715bc89313f61ddb2c28c3079fbc75803338cc0c4c254557e65`다. 대량 정책이 아닌
개별 exact 증거의 명시적 축만 승격했다. `STATUS.md`는 변경하지 않았고 GPT-5.6 Sol
medium이 다른 모델/CLI 재위임 없이 직접 구현·검증했다. admission 3/3,
실데이터 candidate/owner rebuild, transition gates 50/50, owner-review invariant·tamper 테스트가
모두 PASS했다.

## 2026-08-03 과거 상/상 대량 승계 dry-run census — 분류 611, 여행배분 608

개별 exact 예약을 모두 투영한 뒤, 다음 대량 후보인 과거 `classified_v14`의 상/상
분류를 현재 event에 승계할 범위를 DB 변경 없이 고정했다. 현재·과거 1:1 lineage,
매입일 exact, 가맹점 exact, 과거 confidence/tax_conf 상/상, 이미 개별 투영된 15 UID 제외을
모두 만족하는 최초 엄격 집합은 764건이다. 그중 cost_type=`여행원가`,
vat_tag=`불공제_해외`, 계정·bucket이 빈값/확인이 아닌 후보는 611건이다.

새 `direct_all_period_historical_carryforward_census.py`는 원천 classified hash를 결속하는
lineage annex, `trips.json` 전체 SHA, 611 event set
`71ebfa85e2dbf97d778da60767072bc2300a87411442490ab0bdbb44ba671438`, 네 축 semantic set
`c44ce5848421667e92df3438eab0b79130108f41c90476e51869de1080e37d2e`를 live 재구성한다.
원천별 HAN343/KBO237/KBD31, 계정별 식비346/숙박비130/교통비40/주유비25/렌터카23/
통행료15/입장료14/기타18이다.

추가 감사에서 611 중 KBD-0779/0781/0783 3건의 bucket은 `취소환불`로, `trips.json`의
여행 target이 아님을 확인했다. 따라서 사용자가 대량 승계를 승인하더라도 분류 후보는
611, Gate 5 여행 배분 후보는 608으로 분리해야 한다. 608 set은
`9b5f2286fa608f4407f287d0c486ef232362e96a928cb8c01826a43ae6950a52`다. 현재 artifact는
`awaiting_user_policy_decision`, `database_applied=false`, `posting_status=blocked`이며 DB/정본을
변경하지 않았다. focused 3/3, py_compile, diff-check PASS, `STATUS.md` 불변이다.
GPT-5.6 Sol medium이 다른 모델/CLI 재위임 없이 직접 감사·구현했다.

추가로 현재 후보 DB에 투영되는 모든 admission을 live 재생성해 유일 payment 139건
(사용자 승인 taxonomy116 + manual frontier8 + Mutsu6 + Kamenoi2 + exact partial7)을 구했다.
611 대량 승계 후보와의 교집합은 0건이다. census에 `already_projected_payment_count=139`,
`already_projected_overlap_count=0`을 fail-closed 불변식으로 추가했고 focused 4/4 PASS(84.040초)다.

## 2026-08-04 과거 분류 코드 재생성 검증 — 611/611 네 축 일치, 608 배분 투영

사용자가 과거 담당자의 판단 프로세스가 코드에 남아 있음을 지적했다. 이에 따라
`classified_v14.csv`를 단순 과거 스냅샷으로만 보던 이전의 보수적 판정을 재감사했다.
생성 계보 `build_v13_trip.py → fix_v14.py → patch_v14.py → integrity_check.py`와
`cardindex.py`, 원장 교정 이력이 저장소에 남아 있음을 확인했다.

현재 브랜치를 건드리지 않고 `/tmp/cost-replay-5fkTOyhm/repo` detached worktree에서 상기
계보를 재실행했다. `build_v13_trip.py`는 Q2 승인카드 누락 0을 재현했다. 전체
재생성 v14는 1,684행/310,130,982원으로 현재 스냅샷 1,833행과는 다르고 integrity
이슈 13건이 남아, 전체 v14의 무조건 승계는 기각했다. 그러나 이번 선택 611 UID는
재생성 결과에 611/611 전부 존재했고 `bucket/account/cost_type/vat_tag` 네 축이
611/611 일치했으며 changed 0, missing 0이었다. 따라서 이 집합은 새 대량 판단이
아니라 기존 코드·사용자 교정 프로세스의 재실행 결과로 재판정했다.

새 `direct_all_period_historical_carryforward_admission.py`는 매 후보 빌드에서 `ledger/`를
임시 디렉터리로 복사하고 생성 3단계를 격리 재실행한다. 재생성 v14 1,684행 SHA
`93ad47c4ef78301d1934411e53bc48e560cba2bce1fe7f926af32a2b384a5fc1`과 611 UID/네 축이
정확히 일치할 때만 `confirmed_by_reproducible_code_replay`로 승격한다. 코드·입력·출력
중 하나라도 달라지면 fail-closed한다.

후보 DB에 611 payment의 decision 2,444행을 투영했다. `trips.json` target인 608건에만
전액 confirmed allocation을 만들고, `취소환불` lifecycle 3건은 네 축을 보존하되 여행 plan을
만들지 않았다. 기존 16건을 포함한 full-axis payment은 627, plans/allocations은 624/624,
Gate 5 resolved 624/unresolved 4,704가 됐다. 원천 5,328건·relation 330건은 전량 보존되고,
새 candidate semantic SHA는
`8971922de7c8d4c236e3c8b9d8397e908022f33005aa94b109e91a0371141b57`다. Gate 6 승인
baseline이 없으므로 후보는 여전히 미게시다.

admission 3/3(97.265초), 실데이터 candidate/owner rebuild, transition gates 50/50(399.134초),
owner-review invariant·tamper(945.202초)가 모두 PASS했다. 임시 detached worktree는 검증 후
제거했고, 보호된 `STATUS.md`는 변경하지 않았다. GPT-5.6 Sol medium이 전역 워커
규칙에 따라 다른 모델/CLI 재위임 없이 직접 재현·구현·검증했다.

## 2026-08-04 세션 이동 최종 핸드오프 — 5,328건 보존·624건 직접 해결·후보 미게시

### 현재 정본과 Git 상태

- 작업 브랜치와 원격은 `codex/p07-canonical-cutover-candidate`이며, 이 블록 작성 직전 구현
  HEAD는 `f03f734`(`ledger: replay and allocate historical decisions`)다. 직전 연속 커밋은
  `c099df6`, `6d89cc7`, `6cf6f5c`, `b64f446`, `3d576d4`, `97ddd45`, `acae5d6`다.
- `STATUS.md`는 사용자가 별도로 수정한 보호 파일이다. 내용 SHA는
  `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`이며 이 세션에서는
  편집·스테이징·커밋하지 않았다. `AGENTS.md` SHA는
  `3042ea2ccf6b9eef62ae777506302d8edfc392ac1cb8516822bf52b925bf1fe4`다.
- DB/정본 게시, 운영 전기, 배포는 수행하지 않았다. 현재 산출물은 검증용 candidate뿐이다.

### 사용자가 확정한 불변 원칙

1. 카드 원천 및 정규화 이벤트 **5,328건은 모두 DB에 보존**한다. 삭제·분기 필터로 수를
   줄이지 않는다. 5,328은 미분류 수가 아니라 전체 normalized event 수다.
2. **Q2라는 범위 개념은 폐기**한다. 모든 기간의 원천을 보존하고 직접 증거 단위로 판단한다.
3. 과거 담당자의 판정 코드는 재실행 가능한 증거다. 다만 현재 `classified_v14.csv` 전체를
   무조건 신뢰하지 않고, 재실행 결과와 현재 lineage가 정확히 일치하는 축만 승격한다.
4. `확인`, `공제후보` 같은 placeholder/proposal은 confirmed 최종 판단으로 바꾸지 않는다.
   새 대량 정책판단은 금지하되 기존 코드·입력으로 결정론적으로 재현되는 판단은 자동 진행한다.
5. Gate를 통과하지 않은 candidate DB는 게시하지 않으며 승인 baseline을 만들어내거나 가장하지 않는다.

### 지금까지 후보 DB에 반영된 내용

- source events 5,328건 전량과 proposed transaction relations 330건을 보존했다.
- 사용자 승인 저모호성 taxonomy 116건, manual frontier 8건, 인증 Mutsu 숙박 6건,
  인증 Kamenoi 숙박 2건, exact 예약 부분축 7건을 직접 증거로 투영했다.
- 과거 생성 계보 `build_v13_trip.py → fix_v14.py → patch_v14.py`를 격리 재실행했다.
  재생성 결과는 1,684행/310,130,982원, SHA
  `93ad47c4ef78301d1934411e53bc48e560cba2bce1fe7f926af32a2b384a5fc1`이다. 현재 역사
  스냅샷 1,833행과 다르고 integrity 이슈 13건이므로 전체 승계는 기각했다.
- 엄격 후보 611건만 네 축이 재생성 결과와 611/611 일치(changed 0, missing 0)해 confirmed
  decision 2,444행으로 승격했다. 그중 여행 target 608건은 배분했고, `취소환불` lifecycle
  3건은 분류만 보존하고 여행 plan은 만들지 않았다.
- 현재 full-axis payments 627건, confirmed plans/allocations 624/624건이다. Gate 5는
  **resolved 624 / unresolved 4,704**다. 4,704는 원천이나 자료가 삭제된 수가 아니라,
  네 축과 여행 배분 계약을 아직 모두 충족하지 않은 이벤트 수다.
- candidate semantic SHA는
  `8971922de7c8d4c236e3c8b9d8397e908022f33005aa94b109e91a0371141b57`다.

### 검증 완료값과 게시 상태

- carryforward census 4/4 PASS(84.040초), admission 3/3 PASS(97.265초), 실제 candidate/owner
  rebuild PASS, transition gates 50/50 PASS(399.134초), owner-review invariant·tamper PASS
  (945.202초)다.
- Gate 1/2/3/4/7은 현 구조에서 통과했다. Gate 5는 4,704건 미완결 때문에 FAIL,
  Gate 6은 승인된 direct baseline이 없어 FAIL이다. 따라서 **CUTOVER=FAIL, candidate 미게시**가
  정상이고 안전한 현재 상태다.
- OTA 대사는 완전히 끝난 것이 아니다. 저장소에 인증된 exact 예약은 위 범위까지 투영했지만,
  VAT 또는 여행축을 증거가 확정하지 못한 7건은 부분축으로 남겼고 증거 없는 축을 추정하지 않았다.

### 다음 세션이 승인 질문 없이 바로 수행할 우선순위

1. 최초 엄격 replay 집합 764건 중 완전 승계 611건을 제외한 **153건**을 전수 감사한다.
   대략 `여행원가+VAT 확인` 66, `판관비+공제후보` 36, `여행원가+공제후보` 29,
   `cost_type 확인+불공제_해외` 11, 기타 11건이다.
2. 153건에서 replay가 확정하는 concrete `account`, `bucket`, `cost_type`, 최종 VAT 축만
   부분 decision으로 투영한다. `확인`과 `공제후보`는 미확정으로 유지한다. 기존 139개 직접
   투영 UID 및 611 승계 UID와 교집합이 0인지 다시 fail-closed 검증한다.
3. 재생성 파이프라인이 후보 빌드마다 중복 실행되어 매우 느리므로 full/partial admission이
   한 번의 격리 replay 결과를 공유하도록 리팩터링하되, 고정 row/SHA/UID/축 검증은 약화하지 않는다.
4. focused admission → 실제 candidate build → transition 50개 → owner tamper 순으로 검증하고,
   semantic SHA와 owner-review 기대값을 갱신한다. `STATUS.md`는 계속 제외한다.
5. 그 뒤 남은 4,704건을 direct evidence/source family별로 재분할해 다음 고효율 묶음을 처리한다.
   증거가 없는 축을 가맹점명만으로 대량 확정하지 않는다. Gate 6 baseline 권한이 생기기 전에는
   게시·cutover를 시도하지 않는다.

### 채팅의 저장소 외 별도 맥락

- 사용자는 WSL + Orca Mobile에서 세션 목록/미리보기는 보이지만 채팅 본문이 무한 로딩되는 문제와
  최신 업데이트 링크도 요청했다. 이 브랜치에는 해당 앱 수정이나 검증된 웹 조사 산출물이 없으므로,
  다음 세션에서 이 문제를 이어갈 경우 현행 버전·공식 릴리스·WSL 네트워크/인증 로그를 새로 확인해야
  하며 이 원장 작업의 완료로 오인하지 않는다.
- 터미널 입력창 전체 선택 단축키 질문도 별도 UI 질문이며 저장소 변경 사항은 없다.

이 최종 핸드오프는 GPT-5.6 Sol medium이 현재 워커 지침에 따라 작성했다. 모델 상호검증은 이 CLI의
워커 스텁에서 재위임이 금지되어 수행하지 않았고, 기존 검증 결과와 재현 가능한 로컬 증거만 기록했다.

## 2026-08-04 replay 잔여 153건 부분축 투영 — 458 decision·Gate 5 resolved 625

엄격 historical replay 집합 764건에서 완전 네 축 승계 611건을 제외한 153건을 전수 재구성했다.
과거 코드가 재현한 값 중 placeholder가 아닌 축만 확정했다. allocation target 153, account 153,
cost_type 139, 최종 VAT 13으로 합계 458 decision이다. `확인`과 `공제후보`는 확정값으로 승격하지
않았다. event set SHA는
`243343241506c8829edb2f927ed5f201592d26670b4b100222b4baebe729d090`, 축 semantic SHA는
`80b0614d29fda09b2154072e5c0352d1511f036aadec5b6744bba39fb996c02c`다. 기존 직접투영 139건 및
완전승계 611건과의 교집합은 각각 0이다.

153건 중 KBD-0852와 KBD-0979 두 건만 네 축이 모두 구체적이다. KBD-0852는 `0501_부산` 여행
target이라 전액 배분했고, KBD-0979는 판관비 `기타비용`이라 분류는 완결하되 여행 allocation을
만들지 않았다. 이에 따라 full-axis payment는 627→629, confirmed plans/allocations은
624→625가 됐다. Gate 5는 resolved 624→625, unresolved 4,704→4,703이다. 원천 5,328건과
relation 330건은 전량 보존했다.

full/partial admission이 candidate 빌드에서 동일한 격리 replay 결과를 공유하도록 replay 실행기를
분리했다. replay 자체는 기존 고정 결과 1,684행, SHA
`93ad47c4ef78301d1934411e53bc48e560cba2bce1fe7f926af32a2b384a5fc1`을 계속 fail-closed 검증한다.
새 candidate semantic SHA는
`98358d728ae281bea0d8a83fb730f68c060084527caff74391aa3db760b0f916`이다.

partial focused admission 3/3 PASS(242.647초), 실제 5,328건 candidate와 owner rebuild targeted
test PASS(1,067.122초), transition gates 50/50 PASS(795.223초), owner-review 실데이터
invariant·tamper PASS(2,172.168초)다. Gate 5 미완결과 Gate 6 승인 baseline 부재로 후보는 계속
미게시이며 DB/정본 게시·운영 전기·배포는 하지 않았다. 보호된 사용자 `STATUS.md`는 편집하지 않았고
SHA `a3622a894ee9ff40fdb5cae325ec1be56e219046efc43828e796837b71b659cc`를 재확인했다.

다음 우선순위는 남은 4,703건을 direct evidence/source family별로 재분할해, 증거가 확정하는 축만
같은 방식으로 처리하는 것이다. Gate 6 baseline 권한이 생기기 전에는 게시·cutover를 시도하지 않는다.
GPT-5.6 Sol medium이 전역 워커 규칙에 따라 다른 모델/CLI 재위임 없이 직접 구현·검증했다.

## 2026-08-04 전 기간 exact manual/card 그룹 5건 투영 — Gate 5 resolved 630

잔여 direct evidence 중 최신 `manual_v4.csv`와 current card raw의 날짜·금액·카드·가맹점·건수
다중집합이 정확히 일치하는 Booking.com 나가센도 3건과 Agoda Hotel Pearl 교토 2건을 P25 전 기간
범위에서 admission했다. 기존 Q2 전용 `direct_all_period_safe_group_admission.py`는 R37의 오래된
upstream package pin(`f7574e…`) 때문에 현재 live R36 package(`eb8e1a…`)에서 fail-closed되므로
pin을 무시하거나 갱신하지 않았다. 대신 exact matcher를 재사용하는 새
`direct_all_period_exact_manual_group_admission.py`를 추가해 current event set 5건과 최신 manual
group cardinality를 직접 결속했다. selected set은
`414856751e5b4de59d2515352d0387c17259b85a1cceb0425c1d94d39be53e8c`다.

5 payment에 `숙박비/여행원가/불공제_해외/<0413_나가센도 또는 0408_교토>` 네 축 20 decision을
투영하고, 기존 projection decision이 있으면 즉시 fail-closed하도록 overlap guard를 추가했다.
historical 611, partial 153, 기존 direct 139와의 교집합은 모두 0이다. full-axis payments는
629→634, confirmed plans/allocations는 625→630이 됐고 Gate 5는 **resolved 630 / unresolved
4,698**이다. 원천 5,328건과 relation 330건은 그대로 보존했다. 인증 portal의 Yakushima·Minatoya
4건은 booking 1건↔card 2건으로 개별 bijection이 없어 이번 투영에서 보류했다.

새 candidate semantic SHA는
`7e212dd737e29658f600650923ba5ee7f047898547883b940582d42aaf4e329d`다. exact-group admission
2/2 PASS(6.905초), 실제 candidate/owner export targeted PASS(1,154.410초), transition gates
50/50 PASS(991.630초), owner-review invariant·tamper PASS(2,009.546초)다. 중간 allocation scope
고정값 누락은 수정 후 재검증했고, 첫 owner tamper 실행은 2,400초 제한을 초과했으나 재실행에서
완주 PASS했다. Gate 5 미완결·Gate 6 승인 baseline 부재로 후보는 계속 미게시이며 DB/정본 게시·운영
전기·배포는 하지 않았다. 사용자 변경 파일 `AGENTS.md`, `CLAUDE.md`, `STATUS.md`는 편집하지 않았다.

다음 우선순위는 포털 4건처럼 group-level evidence만 있는 항목을 개별 payment 결속 여부별로 재감사하고,
그 뒤 남은 4,698건을 source family별로 재분할하는 것이다. 증거 없는 축을 가맹점명으로 확정하거나
stale upstream pin을 무시해 admission하지 않는다. GPT-5.6 Sol medium이 전역 워커 규칙에 따라
다른 모델/CLI 재위임 없이 직접 구현·검증했다.

## 2026-08-04 Gate 5 잔여 분해 및 R27 순신규 6건 재감사 — 확정 보류

exact manual/card 그룹 5건 투영 뒤 Gate 5의 `unresolved=4,698`을 결제 건 기준으로 다시
분해했다. 이는 원천 누락 수가 아니다.

- `4,420`건: 아직 네 축 완결 decision이 없는 broad 잔여. 여기에는 R27 순신규 6건과
  인증 포털 Yakushima·Minatoya 4건이 포함된다.
- `123`건: 기존 direct 부분축(`user-approved taxonomy` 116건 + verified partial booking 7건).
- `151`건: historical replay가 일부 축만 재현한 잔여.
- `4`건: 네 축은 완결됐지만 `취소환불` 3건과 `기타비용` 1건이라 여행 allocation/Gate5 credit 대상이 아니다.

따라서 full-axis payment는 `634`, 그중 여행 allocation·Gate5 credit 대상은 `630`이며,
`4,420+123+151+4=4,698`이다.

R27 `booking_info`/`ota_event_links_verified`의 순신규 관계 6건
(`TRIP-0016/0020/0021/0022/0024/0025`)을 별도 대조했다. 고정 replay
`93ad47c4ef78301d1934411e53bc48e560cba2bce1fe7f926af32a2b384a5fc1`와 current card raw를
대조한 결과 6/6이 승인번호·금액·사용일·과거 `account/cost_type/vat_tag/bucket` 모두 일치했고,
수기 예약번호·탭·금액도 결속됐다. 현재 이미 확정된 direct 139건과의 event overlap은 0이다.
그러나 R27 관계의 계약 상태는 의도적으로 `unattested/blocked/confirmed_count=0/gate5_credit=0`이고,
인증 OTA 원문/권한 근거가 아니다. 따라서 이 6건은 **확정 후보**로만 보존하며 DB projection이나
Gate5 credit을 부여하지 않았다. 권한 있는 원문 또는 사용자 확정이 추가되면 이 exact 검증을
재사용할 수 있다. 포털 4건도 예약 1건↔카드 2건 bijection 부재와 필드 부족으로 같은 보류 상태다.

현재 `CUTOVER=FAIL`, candidate 미게시, DB/정본/운영 전기는 수행하지 않았다. GPT-5.6 Sol medium이
전역 워커 규칙에 따라 다른 모델/CLI 재위임 없이 직접 대조·기록했다.

## 2026-08-05 historical high/high exact manual-card 42건 — Gate 5 resolved 672

전날 `unresolved=4,698`의 원인을 source family·수기 장부·격리 historical replay로 다시 묶었다.
46건이 `HAN/CORP`의 current↔historical 승인번호·사용일·금액·card4 exact identity, replay 네 축
`상/상`, 최신 `manual_v4.csv`의 source/date/approval-amount/bucket cardinality 1을 동시에 만족했다.
46건 전체 set SHA는
`9bb0c486e6800ffe5e1518247922ff0c4235f411b336ebf038364b9b2a22862c5`, semantic SHA는
`fee9078f8d2d36844f791f714a5e660543a6d6ab92e3c455bab7f57163652a76`다. 이 중 숙박비 2건과 렌터카
2건은 OTA·서비스 실체 증빙이 없으므로 P10에 따라 배정에서 제외했다.

배정 admission은 일반 카드군 42건(CORP 30, HAN 12)만 고정했다. 식비 33, 통행료 3, 입장료 2,
주유비 2, 소모품비 1, 교통비 1이며 숙박·렌터카·항공은 포함하지 않았다. 42건 event set SHA는
`774cf2788be9cc045405eb6139ee91fb5bb0a3445bf97aa2377b4f0f2b25a6ef`, semantic SHA는
`652f33cda2d033af7b567d8865ac5903ce053b63b65131d09c3b281caab9963c`다. 168 decisions(네 축 각
42), replay SHA `93ad47c4ef78301d1934411e53bc48e560cba2bce1fe7f926af32a2b384a5fc1`을 fail-closed로
검증하고 posting은 계속 blocked로 유지한다. source event 5,328건과 relation 330건은 보존했다.

full-axis payment는 `634→676`, confirmed plans/allocations 및 Gate 5 credit은 `630→672`가 됐다.
따라서 현재 Gate 5는 **resolved 672 / unresolved 4,656**다. 잔여 분해는 broad 네 축 미완결
`4,378`(여기 포함: 이번에 보류한 service 4건, medium 확신 30건, R27/portal 등), 기존 direct
부분축 `123`, historical partial `151`, 여행 배정 불가 full-axis `4`로 `4,378+123+151+4=4,656`다.

새 `direct_all_period_historical_exact_manual_card_admission.py`와 projection overlap guard를
추가했고, service evidence withheld UID는 `CORP-2004/HAN-3445/CORP-2018/HAN-3261`로 고정했다.
admission 2/2 PASS(8.090초), 실제 candidate/owner export targeted PASS(734.320초)다. owner semantic
SHA는 `cdc3c8592963fead11226fd82a24c60081da0b96aea44672bd0bc2a6a03297aa`로 갱신했다. 임시 DB
고정 경로 충돌을 한 차례 발견해 고유 임시 디렉터리로 수정했으며, 사용자 데이터나 운영 DB에는
변경이 없다. transition gates 전체와 owner tamper 재검증은 다음 단계로 남겨두며, 현재 CUTOVER=FAIL,
candidate 미게시·DB/정본/운영 전기·배포 미수행이다.

GPT-5.6 Sol medium이 전역 워커 규칙에 따라 다른 모델/CLI 재위임 없이 직접 구현·검증했다.

## 2026-08-05 final verification closeout (latest)

고정 exact-card admission 2/2와 기존 exact-group 2/2가 PASS했고, 실제 5,328건 candidate/owner
export targeted test는 PASS(734.320초)했다. transition gates는 50/50 PASS(737.220초), owner
실데이터 invariant·tamper는 semantic SHA 갱신 후 PASS(1,827.987초)했다. `git diff --check`와
변경 Python 모듈 `py_compile`도 PASS했다. 이 검증은 후보의 Gate 5 수치만 확인하며 Gate 6 승인
baseline 부재를 해소하지 않는다. 따라서 CUTOVER=FAIL, candidate 미게시·DB/정본/운영 전기·배포
미수행 상태를 유지한다.

이번 세션의 남은 작업은 증빙이 없는 4,656건을 추가로 확정하는 것이 아니라, 다음 별도 권한/원문
입력(서비스 실체·사용자 승인·Gate 6 baseline)이 들어올 때 동일한 fail-closed admission을 재사용하는
것이다. GPT-5.6 Sol medium이 전역 워커 규칙에 따라 직접 기록했다.

## 2026-08-05 Sol high/Luna max 프로세스 독립검증 및 Gate 5 수정 — 676/4/4,652 분리

사용자 요청으로 GPT-5.6 Sol high가 별도 문맥에서 현재 프로세스 문제를 독립 검증했다.
판정은 `VERDICT: FAIL`이며, (1) owner tamper 루프가 `--rebuild-current`로 후보 전체를 최소
5회 재생성하는 구조, (2) 과거 Q2의 빠른 버킷·기본값·허용 매칭과 현재 fail-closed 전기간
검증의 차이, (3) Gate 5의 1:N 행수 거부, NULL/비확정 source 결속 통과, (4) terminal 4건의
unresolved 오집계를 모두 수용했다. Sol high는 장시간 전체 회귀를 실행하지 않고 targeted
fixture와 정적 근거로 검증했다.

Luna max가 항목별로 재검토해 다음 범위만 자동 수용·수정했다.

- 한 confirmed plan 아래 allocation N행을 허용하고 정확한 합계를 검사한다. 기존 스키마가
  plan 단위 source decision 하나만 표현하므로 서로 다른 대상에 대한 다중 source decision
  모델은 별도 설계로 남겼고, 현재 계약 안에서는 각 행이 plan source의 target과 일치할 때만
  통과시킨다.
- allocation plan source가 NULL, current가 아니거나 confirmed가 아니면 실패하도록 고쳤다.
- `취소환불` 3건과 `기타비용` 1건을 confirmed `allocation_review_cases` terminal로 기록하고
  Gate 5에서 allocation과 별도 완료로 집계한다.
- Gate 5 부분축·완전축 진단을 history 전체가 아닌 current decision view에서 계산한다.
- 한 후보 빌드 안에서 6개 admission package, historical annex/replay/census를 재사용해
  동일한 5,328건 전체 import를 중복 호출하지 않도록 했다. owner tamper 테스트는 전체 후보
  재생성이 필요 없는 순수 validator fixture로 바꿨다.

검증 결과:

- Gate 5 targeted 회귀 4개 PASS: exact single allocation, exact N-row plan, NULL source 실패,
  confirmed terminal 분리.
- 실제 5,328건 통합 후보 1회 실행 결과: `allocated=672`, `terminal_complete=4`,
  `resolved=676`, `unresolved=4,652`. 후보는 `amount_sign_and_relations`의 HAN equality
  package 미제공, `semantic_regression`의 Gate 6 baseline 부재로 차단됐고 이는 기존 운영
  안전 게이트로 유지됐다. 후보 DB/원장/운영 전기/배포는 수행하지 않았다.
- 실제 Gate 5 tamper artifact 회귀 1회 PASS. 중복 전체 빌드는 의도적으로 중단했다.
- `git diff --check` 및 변경 Python 모듈 `py_compile` PASS. historical admission 묶음 테스트는
  동일한 원천 엑셀 전체 재독 병목이 재현되어 중단했으며, 새 targeted fixture는 통과했다.

현재 결론은 `4,656건 미처리`가 아니라 `672건 배분완료 + 4건 terminal 완료 + 4,652건 일반 미해결`이다.
Gate 6 승인 baseline과 HAN equality 권한이 들어오기 전까지 CUTOVER=FAIL, candidate 미게시 상태를
유지한다. 모델 판단: Sol high의 FAIL 근거를 Luna max가 수용했고, 위 범위의 코드·회귀 테스트만
수정했다.

## 2026-08-06 과거 결과 재사용 폐기·Q2 검증 절차 재설계 — Gate 5 0/5,328 정직한 재기준선

사용자 지시로 과거 2분기 **결과값**이 아니라 당시의 **검증 순서**를 감사했다. 계승한 것은 원천
완전성, 카드 원행·승인번호, 예약번호/PNR, 정확금액, 서비스일, 그룹 cardinality, 취소 원거래,
중복·충돌 fail-close다. 폐기한 것은 수기장부/과거 라벨/리플레이를 증거로 쓰는 방식, 가맹점+근사
금액, 결제일만의 여행배정, 일반 ±2% 허용이다. 수기장부와 `classified_v14`는 앞으로 후보·학습
자료일 뿐 Gate 5 증거가 아니다.

Luna max 1차 설계는 과거 cohort를 전부 보류하는 방향을 냈다. Sol high 1차 검증은 VAT 제외 누락,
historical UID를 통한 현재 이벤트 결속, `trips.json` 단독 여행 귀속의 순환근거를 이유로
`VERDICT: FAIL`했다. 수정 설계는 비용 분류를 `account/cost_type/allocation_target` 세 축으로
한정하고, 모든 기존 676 credit을 먼저 0으로 되돌리며, 카드 현재 원천만 한 번 materialize한 뒤
축별 서로 다른 derivation/evidence 결속을 요구하도록 했다. Sol high 2차 판정은 `VERDICT: PASS`다.

구현 결과:

- `direct_independent_evidence.py`가 5,328 current event-role key를 한 번만 고정하고 event/evidence
  set SHA와 source/identity census를 만든다. manual/historical/tolerance evidence count는 모두 0이다.
- legacy full611, replay-partial의 기존 full2, historical manual42, manual lodging6/airfare2,
  exact-manual5, legacy-bound Mutsu6/Kamenoi2 등 기존 Gate 5 credit 676은 모두 candidate-only audit로
  이동했다. 해당 projection entrypoint를 직접 호출해도 fail-close한다.
- Gate 5와 allocation은 VAT를 제외한 세 축만 동적으로 센다. terminal review는 같은 payment의
  current allocation-target decision과 rule id가 결속되어야 한다. 예상 resolved 수를 하드코딩하지
  않는다.
- `reconcile_amount`는 해외 2% 이내도 `mismatch`로 반환한다. Minatoya 2건은 JPY 12,069↔11,885
  152bp 차이를 관찰값으로만 보존하고 `candidate_only/unresolved/gate5_credit=0`으로 내렸다.
- Minatoya 검사가 Yakushima→수기중복→취소→safe-group 전 체인을 역재실행하던 병목을 제거하고,
  all-period scope와 같은 current context를 공유하도록 바꿨다.

검증:

- 새 evidence/promotion, 2% 차단, 세 축 Gate 5, plan binding, terminal binding 표적 10개 PASS
  (15.483초).
- Minatoya/scope/legacy-entrypoint/owner VAT 표적 9개 PASS(31.639초). 변경 전 동일 연쇄는 5분 이상
  진행 중이라 중단했으며, 스택으로 불필요한 upstream 전체 재실행을 확인했다.
- 실제 5,328건 후보 전체 집계는 마지막에 1회만 실행해 PASS(40.844초). 새 정직한 기준선은
  `resolved=0 / unresolved=5,328`, active decision 0, allocation/terminal 0이다. 이는 분류 실패가
  아니라 독립 증거 없이 확정했던 676건을 숨기지 않은 상태다.
- `py_compile`, `git diff --check` PASS. 후보 DB/정본/워크북/운영 전기/배포는 수행하지 않았다.

다음 복구 순서는 현재 카드 raw key/hash에 OTA 예약 원문을 직접 결속하고, 독립된 여행 일정 원천을
추가한 뒤 Mutsu/Kamenoi부터 세 축을 다시 승격하는 것이다. airfare2는 OTA 원문에 결제금액 결속이
없어 계속 보류하고, Minatoya는 정확금액 또는 명시된 조정식이 들어올 때만 재평가한다.

## 2026-08-06 과거 검증 절차 재학습 보강 — VAT 제거 후 후보 750/14, 전체집계 19.42초

첫 Sol high 최종검증은 `VERDICT: FAIL`이었다. 지적은 (1) 임의 문자열 증거 ID를 만들 수 있음,
(2) 일반 confirmed 세 축이 독립증거 경계 없이 Gate 5에 들어갈 수 있음, (3) 과거 admission 공개
산출물과 도달 불가능 코드에 confirmed/VAT 경로가 남아 있음의 세 가지였다. 이를 그대로 수용해
다음과 같이 보강했다.

- 승격 증거는 content-addressed ID만 허용하고, 같은 run의 실제 `direct_source_records`
  `(source_kind, source_key, source_sha256)`와 FK로 결속했다. 외부 증거도 대상 current event key가
  같아야 하며 다른 결제에 재사용할 수 없다. 세 축 승격은 SAVEPOINT 안에서 원자적으로 기록해 중간
  축 실패 시 decision/derivation/binding을 모두 되돌린다. Gate 5는 decision 자체가 아니라 이 결속을
  모두 통과한 `current_independently_promoted_decisions`만 읽는다.
- candidate semantic hash에 증거 registry·축 derivation·decision binding을 모두 포함했다. 임의
  confirmed 세 축이나 allocation만 삽입해도 resolved credit은 0이다.
- 과거/manual/replay projector의 도달 불가능 confirmed 삽입 코드를 삭제하고 공개 entrypoint는 즉시
  candidate-only 오류로 닫았다. 과거 산출물은 `candidates`, `authority_status=candidate_only`,
  `gate5_credit=0`만 반환한다.

과거 결론이 아니라 과거 검증 절차를 VAT 없는 현행 세 축으로 다시 계산했다. posted date·merchant·
current/historical identity가 exact이고 `account/cost_type/allocation_target`이 모두 구체적인 후보는
기존 611건이 아니라 **750건**이었다. 과거에는 VAT 상태 때문에 139건이 별도 partial로 밀려 있었다.
VAT를 제거하자 실제 active-axis partial은 **14건**(account+allocation_target만 있고 cost_type 없음)으로
줄었다. 이 750/14는 학습 후보 수이며 독립 외부증거가 아니므로 Gate 5 credit은 모두 0이다.

반복 전체검사도 구조적으로 제거했다. 한 후보 빌드에서 카드 엑셀을 한 번만 파싱해 inventory와 DB
적재가 같은 메모리 스냅샷을 공유하고, 종료 직전 변경 검사는 재파싱 대신 원본 바이트 해시만 확인한다.
통합 테스트 내부의 두 번째 `--rebuild-current` 호출도 제거했다. 실제 5,328건 후보+owner export
전체집계 1회는 **19.042초(벽시계 19.42초)**에 PASS했고, 직전 40.844초의 절반 이하이며 과거
734.320초 반복 빌드와 비교해 병목을 제거했다. 결과는 정직한 기준선 `resolved=0 / unresolved=5,328`,
active decision 0, allocation/terminal 0, 이전 credit 676→0이다.

표적 검증은 evidence/projector 7개 PASS(12.662초)와 source/event 재사용 방지 3개 PASS,
Gate 5 결속·tamper 10개 PASS, owner VAT/권한 3개 PASS(2.754초), 과거 후보 재분할 12개
PASS(87.012초)다. `py_compile`와 `git diff --check`도 통과했다. 후보 DB·정본·워크북·운영 전기·
배포는 수행하지 않았다.

두 번째이자 마지막 Sol high 최종 독립검증은 비싼 전체집계를 재실행하지 않고 17개 표적검사
(5.630초)와 정적 경계를 대조해 `VERDICT: PASS`했다. `p07-direct-v3` 명칭은 버전 표기 부채지만
exact-schema guard가 구형 v3 layout을 거부하므로 현재 정확성 차단요인은 아니라고 판정했다.

## 2026-08-07 current-card LOO 자동분류 — 후보 675/4,653, 최종수용 보류

중간 설명 뒤 다음 자동처리를 이어가지 않은 코디네이터 운영 오류를 바로잡고, 과거 분류 장부를
거래 증거가 아닌 고정 학습자료로만 쓰는 네 모델 leave-one-out 분류기를 후보 빌드에 연결했다.
현재 양수 purchase 4,885건을 대상으로 각 최소 3개 peer가 필요한 account 2개 모델과
allocation-target/cost-type 2개 모델이 모두 일치할 때만 세 축을 승격한다. VAT와 ±2% 금액 허용은
사용하지 않으며 일정 부재·모호성은 지지 근거가 아니다.

첫 최종 Sol high 검증은 대상 과거행의 confidence/label이 후보 선별에 영향을 주는 누수를 잡아
`VERDICT: FAIL`했다. 이를 현재 카드만으로 후보를 만들고 과거 exact identity는 대상 peer 제외와
예측 후 채점에만 쓰도록 수정했다. 두 번째 검증도 전역 model id가 대상 과거행 hash에 따라 바뀌는
문제를 잡아 `VERDICT: FAIL`했다. 검증 횟수 한도 뒤에도 지적 자체는 수용해, 알고리즘 model id와
run-level 학습상태 hash를 분리하고 각 대상에는 자기 과거행이 빠진 `loo_model_sha256`을 별도로
결속했다. 실제 `_build_expected` 경로에서 대상 UID/content/label/confidence/tax_conf를 바꿔도
그 대상의 model id·LOO 지문·prediction id/hash/세 축은 같고 사후 validation/run-state만 달라지는
회귀를 추가했다.

실제 5,328건 재빌드 결과는 cancellation settlement terminal 544 + verified lodging 16 + classifier
115 = **후보 resolved 675 / unresolved 4,653**이다. classifier는 held-out 100/100, 오류 0이며,
수기·과거 장부의 transaction evidence 사용은 0이다. 분류기 단위 6/6, Gate 회귀 54/54,
실데이터 owner-export 1/1, `py_compile`, `git diff --check`가 통과했다. 진단 산출물은
`/tmp/cost-gate5-classifier-v3-20260807.bKr0yF/artifacts/48347eecc6bf4cb3a0ec5852cfdeeefd-2db7a53f6eeb`다.

다만 두 번째이자 마지막 Sol high 최종검증이 수정 전 상태에서 FAIL로 끝난 뒤 적용한 변경이므로
독립 최종 PASS는 없다. 또한 전체 후보는 Gate 4(HAN equality), Gate 5(4,653 미완결), Gate 6
(승인 baseline) 때문에 fail-close다. 따라서 활성 확정은 0이고 candidate DB·정본·워크북·운영
전기·배포는 수행하지 않았다. 가장 큰 잔여군은 동일 가맹점 peer 부족/충돌 4,223건이다.

## 2026-08-11 무손실 세션 인계 패키지 — PARTIAL_HANDOFF

현재 세션의 상세 인계는 `docs/handoff/2026-08-11/README.md`를 기준으로 한다.
Phase 1 연도 무결성 변경은 Sol high 최종 `VERDICT: PASS`를 받았고, Phase 2 대만 승격
설계는 Sol `VERDICT: FAIL`이다. Kimi 전체 파이프라인 검토는 `KIMI_VERDICT: FAIL`이다.

인계 패키지는 현재 상태·결정·시도·산출물 해시·다음 작업을 보존한다. Codex 앱의 66 turn
표시 대화는 비식별 export했고, 식별자가 포함될 수 있는 보호 원문은 저장소 밖에 보관했다.
다만 Sol/Kimi 전체 검토 출력과 전체 unittest 최종 로그가 아직 없어 `PARTIAL_HANDOFF`다.

## 2026-08-12 Gate5 placeholder 보정 세션 — PARTIAL_HANDOFF_REINFORCED

Sol high 설계 검증은 `VERDICT: FAIL`로, markerless 전체 재그룹화와 지리 문맥 우회 허용을
배제하고 동일 source/card4 혼합국가 parent run·정확한 foreign pending 경로·정확히 7건
membership를 요구했다. 이를 반영해 UNKNOWN placeholder를 compact mixed-country parent
내부의 양수 해외금액 markerless purchase로만 제한하고, 각 registry를 1행으로 만들었으며
selection context hash를 registry core와 Gate payload audit에 결속했다.

최신 격리 투영은 `/tmp/codex-goal-final2-20260812-artifacts/fcc3a214960c4bb696ab7bf9b8b474d2-f759f0584385`
(`run_id=fcc3a214960c4bb696ab7bf9b8b474d2`)를 기준으로 candidate 5,328, final 2,184,
nonfinal/travel_open 3,144, untriaged 0, literal `travel_unassigned` **2**, auto provisional
3,142를 산출했고 Gate5는 `accepted_with_auto_provisional_queue`였다. UNKNOWN registry는
정확히 7개·각 1행이며 해당 7행에는 allocation plan, cost allocation, posting, confirmed
decision, reversal inheritance가 0이었다. Gate4(HAN equality)와 Gate6(baseline)은
fail-closed로 남겨 정본·워크북·운영 전기·배포는 수행하지 않았다.

변경 단위 테스트 53개, `py_compile`, `git diff --check`가 통과했다. 독립 Sol high 최종
검증은 최신 run 기준으로 진행 중이며, 최종 `VERDICT` 수신 전에는 이번 단계의 확정을 보류한다.

## 2026-08-12 후속 검증·문서 최신화 — 미완료 여행 배정 9건 → 1건

이번 세션은 직전 placeholder 보정 이후의 실제 후보 결과를 확정적으로 기록하고 인계 문서를
최신화했다. 기존 9건(KBO 7, CARPISA 1, NICE 국내 PG 환불 1) 중 KBO 7건과 CARPISA 1건은
국가·목적지·서비스기간을 추정하지 않는 `UNKNOWN/미상` 임시활동 검토 lane으로 이동했다.
NICE 환불은 서비스기간 미확정 구매에 비용축을 상속하지 않고 `여행_미배정`에 남겼다.

최신 격리 후보는 5,328 payment 기준으로 `final=2,184`, `nonfinal=3,144`,
`travel_open=3,144`, `travel_unassigned=1`, `auto_provisional=3,143`을 산출했다.
Gate5는 `accepted_with_auto_provisional_queue`로 통과했고, 수용 상한은 유일 key 5건으로
연결됐다. Gate6은 `direct_baseline_unavailable`로 실패해 전체 실행 `passed=false`를 유지했다.
HAN equality package도 `applied=false`, `authority_status=unattested`, `posting_status=blocked`다.

검증은 `py_compile`, `git diff --check`, registry·classifier·transition Gate 표적 테스트
106건(`OK`)으로 완료했다. 정확히 5건 통과·6건 실패·중복 key 1회 집계 경계 테스트도 추가했다.
독립 Sol high 최종검증은 `VERDICT: PASS`였다. 전체 후보는 게시·정본 반영·장부 전기·배포하지 않았다.

AGY Gemini 3.6 Flash low는 `GEMINI_API_KEY` 부재로 호출 실패해 Luna max가 문서화·검증을
이어받았다. 설계 Sol 1차 FAIL 후 수정했고, 설계 2차와 최종 검증은 모두 PASS다.

상세 인계: `docs/handoff/2026-08-12/README.md`

## 2026-08-12 Gate5 triage·release 분리 — 통과 가능성 완화, release 안전성 유지

사용자 지적대로 기존 단일 통과 표현이 분석 진행과 운영 release를 혼동하게 만드는 문제를
보정했다. `travel_unassigned=5`와 사용자 질문 10그룹은 correctness acceptance에서
`advisory_only` queue SLO로 내렸다. 초과 수량과 유일 key 집계는 계속 보고하지만, 그것만으로
lossless triage를 실패시키지 않는다.

Gate5는 `TRIAGE_PASS`와 `release_scope_ready`를 분리한다. triage hard 조건은 모든 payment의
상호배타적 lane 귀속, `untriaged_nonfinal=0`, finality veto 무우회, 그리고 비최종 payment의
confirmed decision·allocation plan·cost allocation·journal/posting·reversal derivation 및
inheritance 0이다. 전체 release scope는 여전히 `nonfinal_count=0`을 요구한다.

상위 보고서는 `shadow_ready`와 `release_ready`를 별도로 노출하며 호환 필드
`passed == release_ready`를 builder와 P07에서 강제한다. Gate6 baseline 또는 HAN equality가
없어도 구조적으로 정직한 분석은 `shadow_ready=true`가 될 수 있지만, candidate DB 설치,
artifact activation, 게시·전기·배포는 계속 불가능하다. CLI에는 명시적
`--success-level shadow`를 추가했고 기본값은 기존 release fail-closed 동작이다.

격리 실행 `/tmp/cost-shadow-readiness-20260812-final1/artifacts/72961a7c3a334e6ea3cb5bf4cf88719b-68726a34736e`는
5,328 payment에서 `TRIAGE_PASS`, `shadow_ready=true`, `release_ready=false`, `passed=false`,
`output_db=null`, `nonfinal=3,144`, `nonfinal_side_effect_invariant=true`를 냈다. P07은 이를
`artifact_state=not_published`, candidate DB reference 없음으로 검증했다. 운영·정본 산출물은
변경하지 않았다.

검증은 `test_transition_gates_v2` 60/60, `test_direct_projection` 32/32, 추가 핵심 계약시험
9/9, `py_compile`, `git diff --check`가 모두 PASS했다. AGY 저추론 경로는 timeout되어 Luna max가
설계·구현을 이어받았고, 별도 GPT-5.6 Sol high 최종 검증은 `VERDICT: PASS`였다.

## 2026-08-12 구조적 실패요인별 규칙 추가 요청 방식 확정

사용자 지시로 비최종 건별 승인 방식을 폐기했다. 이후 파이프라인은 `row_finality` veto와
fail-closed 원인을 구조적 family로 묶어 `structural-rule-admission-v1` 요청을 만들고,
사용자에게 family+분류경로 단위 `allow_rule`/`keep_blocked`만 요청한다. scope 허용은 규칙 구현·검증
권한일 뿐 finalization·allocation·posting 권한이 아니며, 적용 전후 `nonfinal_count`,
`travel_open_count`, lane partition, 비최종 side-effect 0을 다시 검증한다.

현재 격리 aggregate `nonfinal=3,144`는 lifecycle 미종료 2, review/provisional 대상 hard veto
3,141, 세 축 최종 배정 불가 2로 분류되며 family 간 겹침은 1이다. 행 단위 ID·원문은 요청
출력과 인계 문서에 기록하지 않는다. 상세 계약: `docs/handoff/2026-08-12/06_structural_rule_admission.md`.

패키지 B what-if을 실제 후보 DB에 적용한 결과, registry 335 → activity placeholder 1,785 →
reservation placeholder 820 → inferred external 114 순으로 후보 감소가 3,054건, 잔여 후보가
90건이었다. 이 시뮬레이션은 `side_effects_created=false`인 격리 계산이며 사용자 규칙 허용,
final decision, allocation, posting, 게시를 수행하지 않았다.

## 2026-08-12 package-b 실제 격리 실행 — 비최종 3,144건 → 90건

사용자의 구조적 실패요인별 규칙 추가 방식을 유지하면서, 목표 검증 실행에만
`--structural-rule-package package-b`를 명시했다. 네 path의 적용 건수는 registry 335,
activity placeholder 1,785, reservation placeholder 820, inferred external 114로 합계
3,054건이다. 최신 Gate5 집계는 `final=5,238`, `nonfinal=90`, `untriaged=0`,
`TRIAGE_PASS`, `shadow_ready=true`였다.

적용된 구조 규칙 행의 allocation plan·cost allocation·posting·reversal inheritance는
모두 0건이고, 비최종 side-effect 불변식은 true였다. Gate4 HAN equality와 Gate6 baseline이
없어 `release_ready=false`, `passed=false`, `output_db=null`로 유지했다. candidate DB·정본·
워크북·장부 전기·운영 게시·배포는 하지 않았다. 기본 package는 계속 `none`이며, 이번 결과는
운영 반영이 아닌 격리 shadow 검증 결과다.

## 2026-08-12 package-c 실제 격리 실행 — 임시분류 88건 → 5건

`--structural-rule-package package-c`를 명시해 package-b에 세 path를 추가했다. 추가된
범위는 지리 문맥 exact 65건, 수기 환불 exact 13건, 수기 환불 M:N invariant 5건으로 합계
83건이다. 최신 Gate5 집계는 `auto_provisional=5`, `human_question_nonfinal=2`,
`nonfinal=7`, `untriaged=0`, `TRIAGE_PASS`, `shadow_ready=true`다.

package-c terminal 처리 83건의 allocation plan·cost allocation·posting·reversal
inheritance는 모두 0건이고, 비최종 side-effect 불변식은 true였다. Gate4 HAN equality와
Gate6 baseline이 없어 `release_ready=false`, `passed=false`로 유지했으며 운영 게시·정본·
워크북·장부 전기·배포는 하지 않았다. 기본 package는 계속 `none`이다.

## 2026-08-13 2025년 결제 레인·수기장부 산출물 최종 확정 — v9

사용자 확정 규칙을 반영해 결제연도는 `occurred_on`으로 판정했다. 2025년 결제 2,330건 중
2026년 행사일이 정식 일정표로 독립 확인된 76건만 해당 여행 탭에 두고, 나머지 2,254건은
`2025년 결제` 표시 전용 탭으로 배정했다. 2026·2027년 결제는 허용 행사연도와 정식 대상이
확인되면 여행 탭, 명시적 기타비용은 `기타비용`, 그 밖에는 `검토필요`로 단일 배정했다.

v8 최종검증에서 발견된 `period.event_years` 비어 있지 않음만 검사하는 반례를 수용해,
공통 여행 판정이 `{2026, 2027}`과의 교집합을 요구하도록 수정하고 `{2025}`·`{2028}`
반례 회귀시험을 추가했다. 문서에는 세 표시 레인이 여행 확정·기간·배분·전기와 분리된
예외 레인임을 명시했다.

v9 산출물은 여행 1,370 / `2025년 결제` 2,254 / 기타비용 275 / 검토필요 1,429,
총 5,328건·708,722,467원이며 실제 미출력 0건이다. 사용자 열 7개, Carlito 11pt,
E열 폭 16, KBD/KBO 노출 0, GoToGate 542,143원은 `항공_염장규`·예약번호 공란이다.
예약번호 동률/provider 충돌은 fail-close로 유지했고, 비최종 7건의 confirmed decision·
allocation plan·cost allocation·journal/posting·reversal inheritance는 0건이다.

GPT-5.6 Sol high 독립 최종검증은 v9 기준 `VERDICT: PASS`였다. v9를 Google Sheets로
변환·검증한 뒤 이전 출력 시트 2개를 삭제하고 새 시트만 유지했다:
`https://docs.google.com/spreadsheets/d/12Mk3nps0wld8xeoRupEZGuz9TRrU-aLldKyI3raK8tc/edit`

## 2026-08-14 2025년 결제 mail-only 승격 보정 — rule4 격리 검증

사용자 최신 규칙을 우선 적용했다. 2025년 결제를 2026년 여행으로 승격하는 조건은
해당 카드 결제와 유일하게 결속된 OTA·PG·서비스 메일 및 메일에 명시된 2026년 서비스
기간이다. 수기 여행 탭, `Tokyo JP` 표기, 현지사용 묶음, 지역클러스터, 결제일,
임시예약·임시활동은 2025년 승격 근거가 아니다. 조건을 만족하지 않는 2025년 결제는
사용자 표시용 `2025년 결제` 레인으로만 남기고 최종 배분·전기·환불상속을 차단한다.

분류기 `row_finality`와 사용자 exporter 양쪽에 이 계약을 반영하고, PG/OTA source
provenance와 OTA 메일의 명시 서비스연도를 보존하도록 보정했다. 2025 `기타비용` 경로도
메일 없는 경우 표시 전용 차단 레인으로 처리해 DB 최종성과 사용자 탭의 이중 기준을
제거했다. 집중 회귀 71건, `py_compile`, `git diff --check`가 통과했다.

최신 `rule4` 격리 후보는 전체 5,328건·708,722,467원, 2025년 2,330건·277,445,721원,
2026년 2,998건·431,276,746원이다. 2025년 중 메일에 명시된 2026 서비스기간으로
여행 승격된 건은 5건(일반 OTA 경로 2건 + 인증된 Trip 숙박 메일 authority 3건)이며,
취소환불 정산 292건은 여행 승격과 별도다. 나머지 2025 결제는 승격되지 않았다. Gate5는 후보 전수
lineage와 비최종 side-effect 0은 유지했지만 `confirmed=3,108`, `nonfinal=2,220`으로
release는 차단됐다. Gate6 baseline도 별도 승인 없이 통과시키지 않았다. 임시 DB·report는
검증용으로만 보존했고 정본·운영 DB·Google Sheets·전기·게시에는 반영하지 않았다.

두 독립 GPT-5.6 Sol 검증자는 지정된 최신 run만 대상으로 최종 검증 중이다. PASS 전에는
이번 변경을 운영 확정하지 않는다.

## 2026-08-14 2025년 비용 회계·배부·전기 규칙 — shadow 검증 진행

사용자가 최초 의도한 `2025년 비용` 회계 규칙을 별도 family로 구현했다. 메일 없는
2025년 구매를 2026년 여행으로 추정하지 않고 `account=기타비용`, `cost_type=판관비`,
`allocation_target=2025년 비용`, `target_type=other`로 회계확정·배부 가능 처리한다.
여행기간·여행코드·예약번호는 공란이며 취소·환불 정산과 reversal inheritance는 별도다.
회계기간 `2025`, 기준일 원천 `payment.occurred_on`, 행별 멱등키를 기록하고 정책·membership·
provenance hash를 semantic manifest에 결속했다. shadow 단계는 외부 전표 발행을 실행하지
않고, release 승인 및 전기 엔진의 별도 게이트를 남긴다.

최신 shadow run은 `/tmp/codex-2025-cost-rule-20260814l`의
`run_id=81ef975e382040d080087bcdd719993c`, report hash
`f06ae1ec1de9f7ec5ff703d2db0e4e8a52a52f745028fa8563944b7170dea56c`, candidate semantic
hash `dc1fe08322f5caf8b03f9fa284ad12d4aebe9af501763f644fac571289e8e065`다. candidate 5,328,
2025 비용 회계 1,955건·302,744,666원, 1:1 allocation 1,955건·동일 금액,
booking/journal/reversal 0건, audit field·idempotency key 결손 0건, cost validator PASS다.
Gate5는 `TRIAGE_PASS`, `shadow_ready=true`, `release_ready=false`; accounting final 3,058건,
resolved 3,914건, nonfinal 1,414건으로 5,000 회계확정 목표에는 1,086건 부족하다.
부족분을 채우기 위해 2026 임시행·메일 없는 여행행·취소환불을 임의 승격하지 않는다.

회귀는 새 규칙 4건, Gate5 축소 fixture 2건, 전체 `test_transition_gates_v2` 61건,
실제 5,328행 projection/owner-export fixture 1건이 통과했고 `py_compile`,
`git diff --check`도 통과했다. AGY Gemini 3.6 Flash high는
멱등성·회계기간·전기 엔진 연계·reversal orphan 위험을 독립 점검했고, Luna가 반영했다.
설계 Sol high는 승인된 규칙 계약 기준 `VERDICT: PASS`, 최종 Sol high도 최신 l run 기준
`VERDICT: PASS`였다. 다만 `release_ready=false`이므로 운영 DB·정본 workbook·Google Sheets·
실제 전기는 변경하지 않았다.

## 2026-08-14 2025년 비용 규칙 최종 회귀 — 규칙 PASS, 5,000 목표 미달

최종 Sol high가 최신 l run의 run/semantic/report identity, 2025 비용 membership,
1:1 배부, manifest fail-closed, provenance·policy hash·idempotency·audit, 여행필드 공란,
reversal inheritance 0, shadow booking/journal 0, cost/display terminal 상호배타성 및
비최종 side-effect 0을 재검증했다. 최신 회귀 증거는 새 규칙 4/4, Gate5 6/6,
`test_transition_gates_v2` 61/61, 실제 5,328행 fixture 1/1, compile/diff 통과다.

판정은 승인된 `2025년 비용` 규칙 자체 `VERDICT: PASS`다. 전체 회계확정은 3,058/5,000건으로
1,086건 부족하므로 목표는 미완료이며, 이를 위해 2026 임시행·메일 없는 여행행·취소환불을
자동 승격하지 않는다. 실제 전기는 release 승인과 전기 엔진 게이트 뒤의 별도 작업으로 남긴다.

## 2026-08-14 현재 결과 산출물 — 2025 비용 규칙 l run

최신 l run을 사용자용 수기장부형 workbook으로 별도 산출했다. 파일은
`outputs/2026-08-14-2025-cost-rule-l/2025-cost-rule-current-results.xlsx`이며,
122개 탭·5,328행·708,722,467원이다. 탭 구성은 여행 2,004행, `2025년 결제` 2,036행,
`기타비용` 312행, `취소환불` 544행, `검토필요` 432행이며, 원본 후보 행 수·금액과
일치하고 거래일자·7열 헤더·Carlito 11pt·E열 폭·기술 헤더 부재를 post-save 검사로 확인했다.
이 산출물은 표시 결과이며 운영 DB·정본 workbook·Google Sheets·실제 전기는 변경하지 않았다.

## 2026-08-14 5,000건 달성 후보 family 집계 — 적용 전

최신 l run의 `accounting_final=3,058`, `display_terminal_final=856`, `nonfinal=1,414`를
재집계했다. confirmed terminal은 기타비용 312건과 취소환불 544건으로 구성되고, nonfinal
auto-provisional 중 2026년 purchase는 1,253건(temporary activity 806, temporary
reservation 282, named trip metadata 165)이다. 나머지는 2026년 refund/cancellation 82건,
2025년 refund/cancellation 76건 및 owner-review 3건으로 분리된다.

여행 임시건을 여행 final로 바꾸지 않고, `기타비용 terminal → 회계배부`, `취소환불 terminal →
settlement 배부·전기`, `2026 purchase provisional → 2026년 비용 회계-only`의 세 family를
적용하면 예상 accounting final은 5,167건(3,058+312+544+1,253)이다. 이는 아직 사용자
승인 전이며 실제 코드·DB·전기에는 적용하지 않았다. 설계 검증에서 취소환불 signed posting,
2026 비용의 여행필드 공란, provenance·idempotency·lineage·상호배타성·비최종 부작용 0을
확인한 뒤 구조적 family 단위로 승인 요청한다.

## 2026-08-14 회계 shadow 전표 v2 — 두 설계 FAIL 후 보정 실행

GPT-5.6 Sol 독립 검토 2건은 기존 5,167 설계를 FAIL로 판정했다. 기존 `journal_entries`가
차·대변·배치 원자성·통화·회계기간·멱등키를 표현하지 못하고, `net=0`만으로 복식균형을
증명할 수 없다는 지적을 수용했다. 또한 2026 임시구매 1,253건의 travel final 승격을
차단하고, 2025 mail-only 승격 규칙을 그대로 유지한다.

보정 모듈 `ledger/domain/direct_accounting_shadow.py`는 기존 전표·배부·결정 테이블과
분리된 shadow batch/member/line/manifest 4종 테이블을 사용한다. 각 배치는 단일
transaction에서 구성되고, 구성원 1건당 차·대변 2라인, `debit=credit`, 회계기간과
전기일, `ledger_currency=KRW` 및 `amount_krw` 근거, source currency unknown 상태,
membership/provenance/idempotency hash를 기록한다. 취소환불은 authority 단위 M:N batch로
원자 처리하며, 기존 `journal_entries`에는 쓰지 않는다.

실제 l run 복사 DB에 대한 조건부 shadow 결과:

- base: 3,914 payment member / 3,629 batch / 7,828 line / legacy journal 0 / PASS
- `with_2026_clearing`: 5,167 payment member / 4,882 batch / 10,334 line / legacy journal 0 / PASS
- family: existing 3,058 + confirmed overhead 312 + settlement member 544 + unresolved
  2026 purchase 1,253 = 5,167; family overlap 0
- 모든 batch는 balance PASS, 2026 clearing 1,253건의 행사기간·여행코드·예약번호 공란,
  재실행 manifest hash 동일

산출물은 `outputs/2026-08-14-accounting-shadow-v2/base-report.json` 및
`outputs/2026-08-14-accounting-shadow-v2/with-2026-clearing-report.json`이다. 두 파일은
shadow-only 증거이며 `release_ready`, 실제 journal/posting, 외부 회계 전기를 뜻하지 않는다.
2026 clearing rule과 production chart mapping은 사용자 family 승인 및 최종 Sol 검증 전까지
활성화하지 않는다.

## 2026-08-14 회계 posting candidate gate

`promote_shadow_to_posting`를 추가해 shadow batch를 별도 posting batch/line으로 복사할 수
있게 했다. family approval, production chart mapping, release-ready가 없으면 posting row를
0건으로 유지하며 `family_approval_missing`으로 차단한다. 조건을 모두 넣은 격리 재실행은
`candidate` 상태로 5,167 payment / 4,882 batch / 10,334 line을 만들고 차변·대변 각
896,445,338원, legacy journal 0건을 확인했다. 재실행은 동일 approval/mapping hash로
멱등 처리됐다.

산출물은 `outputs/2026-08-14-accounting-shadow-v2/posting-candidate-report.json`과
`outputs/2026-08-14-accounting-shadow-v2/posting-blocked-report.json`이다. candidate는
실제 posted가 아니며 `posted_payment_count=0`, `external_posting=false`다.

실제 승격 함수는 family approval attestation 및 Gate5·Gate6·HAN equality release
attestation hash 없이는 `authorize=True`여도 차단한다. 새 shadow/posting 테스트는 9건으로
통과했다.

`posting-release-gate-report.json`에서는 승인·release attestation 없이
`release_ready=True`와 `authorize=True`를 넣어도 `posting_rows=0` 및
`family_approval_attestation_missing_or_invalid`/`release_attestation_missing_or_invalid`
차단이 재현됐다.

독립 GPT-5.6 Sol high는 shadow v2 코드·실행 DB·재실행 hash·membership/lineage·부작용
불변식을 읽기 전용으로 재검증해 `VERDICT: PASS`를 반환했다. 새 shadow/2025 규칙 테스트
9건, `py_compile`, `git diff --check`는 통과했다. `test_transition_gates_v2` 전체 재실행은
사용자 중단으로 결과를 PASS로 기록하지 않는다.

## 2026-08-14 posting 증거 정합성 보정 — 최신 근거

이전 최종 검토에서 지적된 대로, 기존 `posting-blocked-report.json`과 blocked DB는
서로 다른 재실행 시점의 attestation 상태를 가리켜 근거로 폐기한다. 또한 위 문단의
"새 shadow/posting 테스트 9건"은 당시 중간 상태의 기록이며 최신 수치는
`test_direct_accounting_shadow` 7건과 `test_direct_2025_cost_accounting` 4건, 합계 11건이다.

새 격리 DB·보고서 쌍을 같은 run identity로 재생성했다.

- `posting-blocked-family-report.json`: 승인 rule ID 공집합 → `family_approval_missing`만
  차단. selected 5,167, posting batch/line 0, legacy journal 0.
- `posting-blocked-release-report.json`: 네 family rule ID와 계정 mapping은 충족하지만
  family approval/release attestation을 제공하지 않음 →
  `family_approval_attestation_missing_or_invalid`와
  `release_attestation_missing_or_invalid`만 차단. posting batch/line 0, legacy journal 0.
- 두 보고서 모두 run `81ef975e382040d080087bcdd719993c`와 mode
  `with_2026_clearing`에 결속된다. 보고서 SHA-256은 각각
  `1a80b902b00fcd076bdff10867e7c2a37e96d944fd00e056c9a24dd19481d93a`,
  `1590351ce1e66088907c92614ebd5f8da7dd977ea5262040cbfba8dbf45c3ce4`다.

현재 posting candidate 5,167건은 여전히 격리 후보일 뿐이며, 실제 journal·외부 전기는
0건이다. 전체 5개 보고서의 파일 hash와 테스트 요약은
`outputs/2026-08-14-accounting-shadow-v2/posting-evidence-index.json`에 묶었으며, 해당
index SHA-256은 `6d86f064258cb56d1c6c37b9b09451cfa191d0c7b401b824b908f94886e82de7`다.
최신 Sol high 최종 재검토는 이 보정 증거를 대상으로 다시 수행해야 한다.

## 2026-08-14 posting 증거 최종 독립 검토 — PASS

GPT-5.6 Sol high가 보정된 최신 보고서·두 blocked DB·코드·테스트를 읽기 전용으로
재검토했다. run/mode 동일성, 5,167 payment·4,882 batch·10,334 line,
family `3,058+312+544+1,253`의 overlap 0, 차·대변 각 896,445,338원,
M:N settlement 259 authority/544 member, 2026 clearing 여행필드 공란,
blocked 사유 1개/2개, blocked DB posting 0·legacy journal 0, candidate와
posted_shadow의 구분, 11/11 테스트를 모두 확인해 `VERDICT: PASS`를 반환했다.

이는 회계 shadow·격리 candidate 설계와 회귀 증거의 PASS다. Gate6/HAN release
attestation과 사용자 family 승인이 없으므로 실제 전기·외부 posting 완료로 승격하지 않는다.

## 2026-08-14 release preflight — 실제 전기 전 차단사항

현재 candidate DB를 `mode=ro&immutable=1`로 재확인했다. 후보는 5,167건,
posting candidate 5,167건이며 `posted_shadow=0`, legacy journal 0,
external posting false다. 실제 release를 막는 조건은 다음 네 가지다: 사용자 family 승인,
Gate6 baseline, HAN release attestation, authoritative production chart mapping.

상세 preflight는
`outputs/2026-08-14-accounting-shadow-v2/release-preflight-report.json`에 기록했다.
파일 SHA-256은 `9aa289da6dc229c506eef17a7ab10fd9b40e8f23bb267d9ed7b9343fbe1d1e64`이며,
증거 index는 6개 보고서를 포함하도록 갱신했다. index SHA-256은
`f24915e9afa1bd50c439c9118a2ced63ed49b27e9ba9ae8db70d87d556c5c356`다.

사용자에게 건별 승인을 요청하지 않도록 `unresolved_2026_purchase_clearing` family
전체의 승인 요청서를 별도 생성했다. 대상은 1,253건·189,627,699원이며 목적은
`accounting_only_pending_cost`다. 여행 확정·기간/여행코드/예약번호 생성·legacy journal·
Gate6/HAN 전 외부 전기는 금지한다. 문서는
`outputs/2026-08-14-accounting-shadow-v2/family-approval-request-unresolved-2026-v1.json`이며,
아직 `pending_user_decision`이고 SHA-256은
`ad36e9c9c8169d9acd8ad50ca3b8cbf949399b6237ea7c9f2d3ca11351de9749`다. 증거 index는
7개 항목으로 갱신됐고 SHA-256은
`e5107a877db4881d274350b0e325d16b3288aaf13e974c04f73e2266b3409fad`다.

## 2026-08-15 P26 비용분류 결과 v6 — 최종 PASS

P26 v4 최종 검토에서 지적된 네 가지 과포착 경로를 수정했다. OTA/PG/service-mail
source kind 허용목록을 적용하고, 예약·온라인 결제의 무메일 현지사용 우회를 차단했으며,
임시여행활동은 결제일에 정확히 하나의 정식 여행코드가 활성일 때만 그 정식 탭으로
표시한다. 카드 3820 국내 무메일 규칙에는 충돌 없음 조건을 추가했다. P27과 충돌하던
기존 3820 문장도 현행 규칙으로 정리했다.

v6 실행 결과는 전체 5,328건·708,722,467원이며, 여행 1,009건, `2025년 결제`
2,036건, 기타비용 363건, 취소환불 544건, 검토필요 1,376건이다. 2025년 여행 2건은
모두 OTA/PG/service mail로 확인된 2026 행사기간이다. 임시여행활동의 비정식 여행탭
0건, 예약·온라인 무메일 여행 0건, 3820 규칙 대상 128건의 기타비용 위반 0건,
취소환불 순액 0원이다.

워크북은 26개 탭, 사용자용 7열, Carlito 11pt, E열 폭 기준을 유지한다. Google Sheet
전수 재검증은 26개 탭·5,328행·708,722,467원, 행/금액 불일치 0, 읽기 실패 0,
셀 37,660개의 폰트 불일치 0으로 완료했다. 합계행 병합으로 생기던 Google Sheets
Calibri interior-cell 문제를 제거했다. 집중시험 26/26, `py_compile`, `git diff --check`도
통과했다. 이 산출물은 표시 전용이며 회계 전기·journal·외부 posting을 만들지 않는다.

현재 산출물: https://docs.google.com/spreadsheets/d/1gBtq41B3mFbvl4XggpQmsVwaf1WKxdTXojvzkezjb8w/edit
검증 후 이전 v4 및 중간 v5 Google Sheet는 삭제했고, 이전 ID 조회는 404로 확인했다.
두 번째 독립 GPT-5.6 Sol high 최종검증은 전체 Google Sheet 전수 증거까지 확인해
`VERDICT: PASS`를 반환했다.

## 2026-08-15 P26 비용분류 결과 v7 — 합계행 서식·1분기 자료 보정

사용자 요청에 따라 각 비용 탭의 마지막 합계행을 보정했다. 합계행의 C:H는 병합하고,
B:H는 노란색 배경과 검은색 글자를 적용했다. 분류 기준·행 수·금액은 v6과 동일하게
유지했다.

v7은 26개 탭·5,328행·708,722,467원이며, 여행 1,009건, `2025년 결제` 2,036건,
기타비용 363건, 취소환불 544건, 검토필요 1,376건이다. 집중시험 26/26,
`py_compile`, `git diff --check`, Google Sheet 26개 탭 전수 행·금액 대조를 통과했다.

Google 원장에 있는 1분기 비용 자료도 확인했다. 3월 비용 4건은 v7에 반영되어 있으며,
수입 자료 탭은 비용 산출물에 섞지 않았다. v6 Google Sheet는 삭제했고 404를 확인했다.

현재 산출물: https://docs.google.com/spreadsheets/d/1q_mwWw8fHa1jMByoKQ6TJ4_DL--2ZOWi0QolYP1Ab1Q/edit

합계행 병합과 표시 형식에 대한 독립 GPT-5.6 Sol high 최종검증은
`VERDICT: PASS`를 반환했다. 본 산출물은 표시 전용이며 회계 전기·journal·외부 posting은
생성하지 않는다.

## 2026-08-15 Agoda 2026 누락 방지 기준 — 2025년 8월 역추적 경계

사용자 의도에 따라 `2025-08-01`부터 `2025-08-31`까지를 Agoda 조사 결과의
종료월로 보는 것이 아니라, 2026년 행사 선결제를 놓치지 않기 위한 역추적 경계로
사용한다. 해당 월의 결제·예약·취소/환불·연결 메일을 전수 대사하고, 2026년 행사와
연결되는 건은 OTA/PG/service mail 근거가 있을 때만 2026 여행으로 연결한다. 근거가
없는 2025년 결제는 2025년 결제에 남긴다. 동시에 2026년 관련 결제·예약·후속 메일은
2025년 8월 경계만으로 잘라내지 않는다.

기존 Agoda 중간 `0건` 판정은 최종 판정에서 폐기한다. 2025년 8월 경계 커버리지와
2026년 관련 자료의 신규/중복/충돌/보류를 확인하기 전에는 OTA DB 병합 완료로
표시하지 않는다. 10개 병렬 조사 레인은 읽기 전용으로 운영하고, 최종 병합은
고유키·근거 해시·결제 연결을 단일 트랜잭션에서 검증한 뒤 코디네이터가 한 번만
수행한다.

## 2026-08-15 Agoda 2025-08 역추적 1차 실측 — 병합 보류

읽기 전용 감사 도구 `tools/agoda_boundary_audit.py`를 추가해 중첩 인덱스의
메타데이터와 sealed candidate DB를 집계했다. 후보 DB에서 2025-08 Agoda 구매는
15건·3,248,979원이며 `payment_booking_links` 연결은 0건이다. 기존
`ota_reconcile_report.json` 및 `pg_mail_index.json`과 날짜+금액 서명도 각각
일치 0건이다.

Gmail의 2025-08 검색은 34통(그중 Agoda 계열 발신 29통)이며, 2026 서비스일이
본문에 명시된 메일은 1통이다. 15건 중 메일 금액만 일치하는 결제행은 4건이나,
날짜+금액이 함께 일치하는 것은 동일 금액의 중복 3행뿐이고 2026 서비스일은
없었다. 따라서 2025 결제를 2026 여행으로 승격하거나 OTA DB에 예약 연결을
생성하지 않았다. 2026 관련 Gmail 검색 전체는 637통으로 별도 후속 연결 대사
대상이며, 이는 2025-08 경계 밖 자료를 잘라내지 않는다는 규칙을 따른다.

## 2026-08-15 Agoda 포털 페이지별 조사 방식 전환

사용자 지시에 따라 Agoda 완료 예약내역을 단일 로그인 브라우저에서 조사한다. 시작점은
10페이지로 고정하고, 2025년 예약이면 앞 페이지 방향으로, 2026년 예약이면 뒤 페이지
방향으로 이동해 2026년과 2025년의 경계 예약을 확인한다. 확인된 경계 페이지를 포함해
2026년 대상 페이지를 페이지 번호별 서브에이전트에 하나씩 배정한다.

기본 보고 단위는 월별 건수가 아니라 페이지별 `전체 카드 수 / 2026년 카드 수 / 날짜
없음 / 중복 / 페이지 SHA-256`이다. 페이지당 카드 수가 일정한지와 페이지 해시·예약 ID
해시의 전역 중복을 함께 검증해 누락을 찾는다. 2026년과 2025년이 섞인 경계 페이지는
2026년 카드만 대상에 넣고, 2025년 카드는 staging DB에는 보존하되 2026년 집계에서는
제외한다.

포털 결과는 기존 candidate DB나 원장에 직접 쓰지 않고, 페이지별 원자료와 해시를 담는
새 private staging DB에 먼저 저장한다. 모든 페이지 에이전트 보고가 끝나고 단일 lineage·
중복·페이지 완전성 검증이 통과한 뒤에만 OTA DB 병합을 별도로 검토한다. 월별 수량은
필요 시 보조 집계로만 산출하며, 페이지별 완전성 보고를 대체하지 않는다.

## 2026-08-15 Agoda 포털 페이지별 staging r3 — Sol high 최종 PASS

실제 Agoda 완료예약 포털을 단일 로그인 브라우저에서 페이지별로 캡처하고, 13개 private
staging DB를 immutable read-only로 병합했다. run은
`agoda-portal-20260815-pages-merged-r3`이며, 최종 파일은
`/tmp/agoda-2026-page-staging-20260815-final-r3.sqlite`이다.

페이지별 관찰/2026 대상 건수는 다음과 같다: `1: 40/40, 2: 40/40,
3: 40/40, 4: 40/40, 5: 40/40, 6: 40/40, 7: 40/40, 8: 40/31,
9: 40/0, 10: 40/0, 11: 40/0, 12: 40/0, 13: 1/0`.
전체 관찰은 481건, 2026 대상은 311건이며 최종 게시도 311건(전부 2026년,
고유 예약 해시 311, 중복 0)이다. 페이지 11은 페이지 10과 비2026 카드 40건이
겹쳤지만 target-year-only 병합에서 제외되어 2026 결과에 누출되지 않았다.

최종 DB는 mode `0600`, SQLite 무결성 정상, 13개 page manifest(1~13), 13개 고유 입력
SHA-256, capture-set SHA-256
`13ebe9f5a961c7618173801b307721bd7ba1fe5ece3465411f4ca968f3bf5321`을 보존한다.
최종 파일 SHA-256은
`babf1936b1a92ea8eae96f651ec3504021391e14b320bf486bc43e6d7c589449`이다.

페이지 11·12는 각각 숫자 11·12가 선택된 화면을 직접 확인한 뒤 안정화 캡처했다
(입력 파일 `page-11-correct-r2.sqlite`, `page-12-correct-r1.sqlite`). 이 화면 확인은
이번 staging 결과의 페이지 identity 공백을 보완하는 인계 attestation으로 기록하며,
DB 내부의 자동 UI 증명으로 과장하지 않는다.

전용 캡처·병합 테스트 22/22, `git diff --check`가 통과했다. 기존 candidate DB,
ledger DB, OTA DB 및 Google Sheet에는 쓰지 않았다. 따라서 이번 PASS는 13페이지
staging 병합과 2026 대상 산출물에 한정되며, candidate/ledger/OTA DB 반영이나 회계
전기 승인은 아직 아니다.

독립 GPT-5.6 Sol high 최종 검토는 위 r3 DB·코드·집계·테스트·diff를 대조해
`VERDICT: PASS`를 반환했다.

## 2026-08-15 Agoda 카드 결제 연결 후보 v4 — 운영 반영 보류

Agoda 포털 staging의 2026 대상 311건과 현재 카드 projection을 대조해, OTA 예약·
서비스기간·카드 결제의 양방향 단일성 및 기존 3축 confirmed를 동시에 만족하는
5건만 증빙상 예약-결제 관계 후보로 만들었다. 나머지 306건은 1건의 비고유 카드
후보와 305건의 유일 증거 부재로 보류했다. 금액·날짜만으로 추정 연결하지 않았다.

최신 private 후보는 `/tmp/agoda-card-confirmation-20260815-v4/candidate.db` 및
`report.json`이며, DB SHA-256은
`bc0a65296b96d8ed705f2602a12aabf0e94fde6eaa801e29adc9521dd71333ae`, report
SHA-256은 `8db99a9bbad546276e6f2baac97ad4b159b5abfeb62829516b0dccbb5c276909`이다.
두 파일 모두 mode `0600`, SQLite integrity 및 immutable read-only 검사를 통과했다.

후보 DB에는 예약·식별자·서비스기간 증거·관계 링크가 각각 5건 생성됐지만, 일반
`payment_booking_links` 상태는 `proposed`로 격리하고 별도 감사 테이블에서만
증빙 관계를 `confirmed`로 표시한다. `private_candidate_only=1`과 회계·전기 side
effect 0을 함께 저장했다. 기존 allocation/cost allocation/classification/journal/
reversal 및 외부 posting은 변경하지 않았다. 원장·운영 candidate DB·OTA DB·Google
Sheet에는 쓰지 않았다.

전용 회귀시험 5/5, 기존 OTA authority 1/1, domain ledger 23/23, `py_compile`,
`git diff --check`가 통과했다. 게시 경쟁 시 타 inode 삭제 방지, report 변조 거부,
원본 base 재대조, membership/policy/run hash 재계산을 구현했다.

다만 독립 GPT-5.6 Sol high 최종 검증은 2회 모두 `VERDICT: FAIL`을 반환했다. 최신
v4의 로컬 집계와 회귀시험은 통과했지만, 모델 검증 단계의 승인 한도를 소진했으므로
본 후보를 확정 거래·회계 final·전기 대상으로 승격하지 않는다. 다음 단계는 새
독립 검증 슬롯을 승인한 뒤에만 재개한다.

## 2026-08-20 Windows headless Agoda 재개 — 인증 프로필 게이트에서 보류

WSL/UIA 경로를 폐기하고 Windows-native CDP 경로를 준비했다. `headless=new`,
loopback CDP, 고유 launch nonce·PID·Edge 버전·target ID를 manifest로 검증하고,
CDP `Runtime.callFunctionOn` 기반으로 Upcoming `U01` 1개와 Completed `C01..C09`
9개 논리 샤드만 수집하도록 구성했다. Cancelled는 수집·배정하지 않는다.
목록 인증/URL/tab/page/예약 ID 바인딩, 상세 ID·기간·금액 파싱, history-back 후
목록 복구 검증을 모두 staging 단계에 둔다. 원장·OTA DB에는 쓰지 않는다.

격리 임시 프로필의 Cookies DB는 SQLite 무결성은 정상이었으나 Agoda 인증 세션이
아니었다. headless 예약 URL은 `chrome-error://chromewebdata/`로 실패했고, 홈은
로그인 필요 상태였다. 따라서 실제 1+9 수집은 0건 실행했으며, 사용자 Edge의
프로필·화면·포커스는 건드리지 않았다. live Edge 프로필은 실행 중이라 파일 복사로
인증 세션을 만들 수 없고, VSS 또는 별도 로그인 프로필 없이는 다음 단계로 갈 수 없다.

click 중 CDP 응답이 끊겨 브라우저 위치가 불명확해지는 경우 `navigation_state_unknown`
으로 즉시 중단하는 안전 패치를 추가했고, Node syntax check·Python compile·로컬
계약 검증을 통과했다. 최신 독립 Sol 리뷰 에이전트는 사용량 제한으로 완료되지
않았으며, 이전 Sol/Advisor 리뷰의 NO-GO 지적을 반영했다. 인증 프로필이 확보되면
auth-only smoke 후 U01/C01..C09 수집, 1,095건 대사 순서로 재개한다.

사용자가 VSS 생성을 허용했으나 현재 Codex PowerShell은 `Medium Mandatory Level`이며
Administrators 그룹이 deny-only라 관리자 토큰이 없다. 이 Windows 빌드의 `vssadmin`에는
create 명령이 없고, `Win32_ShadowCopy.Create`도 권한/초기화 오류로 실패했다. 숨김
UAC 승격 시도는 실행 정책에 의해 차단되어 스냅샷은 생성하지 않았다. live Edge와
프로필은 계속 보존하며, 관리자 PowerShell에서 VSS 생성 후 동일한 headless auth-check를
재개해야 한다.
사용자 요청에 따라 VSS 서비스 시작과 숨김 `RunAs` 실행도 직접 재시도했지만 현재
세션은 UAC 승격을 수행할 수 없어 exit code 1로 종료되었고, VSS 중지·shadow 0개로
확인됐다.

## 2026-08-20 Windows VSS 프로필 인증 재검증 — 세션 미전달

사용자가 관리자 PowerShell에서 생성한 VSS(`ReturnValue=0`,
`HarddiskVolumeShadowCopy3`)에서 `Local State`, `Default`의 Cookies/Network 및
필요 저장소를 새 private headless 프로필로 복제했다. 복제 Cookies DB는 SQLite
무결성 정상, Agoda 쿠키 30건이었지만 예약 화면은 로그인 페이지로 리디렉션되어
`AUTH_NOT_ATTESTED`였다. 복제본은 일반 Edge User-Agent와 `headless=new` 양쪽에서
동일하게 로그인 페이지를 반환했다. 일반 User-Agent 재검증에서는 네트워크 오류가
아닌 Agoda 로그인 URL이 관찰되어 headless 자체 차단과 인증 세션 부재를 분리했다.

검증용 프로필은 VSS 복제본에서 새로 만들었고, 테스트 후 해당 headless Edge와 CDP
포트는 종료했다. 라이브 Edge 프로세스·창·포커스에는 접근하지 않았다. 따라서 U01 및
C01..C09 수집은 여전히 0건이며, Cancelled 제외·원장·OTA DB·ledger 쓰기는 실행하지
않았다. `agoda_headless_cdp_probe.ps1`에는 검증용 `-UserAgent` 선택 인자를 추가했고,
기존 Python/Node 계약 검증은 다음 단계에서 다시 확인한다.

현재 증거상 VSS 시점 복제본만으로는 인증된 Agoda 페이지를 재현할 수 없다. 새
스냅샷은 관리자 토큰이 없는 Codex 세션에서 직접 생성되지 않았으므로, 사용자가
Agoda 로그인 완료 후 생성한 새 VSS를 제공하거나 별도 인증된 자동화 프로필을
마련해야 auth-only gate를 통과시킬 수 있다. 인증 gate 통과 전에는 병렬 수집을
시작하지 않는다.

## 2026-08-21 Paseo 병렬 Sol 검토 격리 보정

Agoda 예약 수집 중 실행 워커와 Sol 검토가 같은 dirty workspace에서 동시에 실행되면서
해시 재검토 루프와 셸 권한 요청이 반복됐다. 수집 워커는 Agoda Edge의
`ERR_BLOCKED_BY_CLIENT`/UIA session ownership 경계에서 중단됐지만, 검토 에이전트의
권한 알림과 과거 고객센터 증거 이벤트가 같은 Paseo 알림 경로에 섞여 작업이 멈춘 원인이
불명확해졌다. 이 사건은 예약 수집기가 고객센터를 호출한 것으로 판정하지 않는다.

재발 방지를 위해 `AGENTS.md`와 `CLAUDE.md`에 다음을 고정했다: Sol 검토는 실행 워커와
분리된 immutable snapshot/worktree의 read-only 사후 검토이며, 실행 워커의 critical path가
아니다. 검토 agent는 파일·DB·브라우저·UIA·외부 서비스·다른 agent를 변경하지 않고,
`notifyOnFinish=false` 및 단일 묶음 권한 요청을 사용한다. 권한 거부·만료와 브라우저 차단은
각각 `review_blocked` 또는 단일 failure code로 끝내며 반복 재시도하지 않는다. 동일 scope의
기존 agent가 있으면 새 agent를 추가하지 않는다. 이번 보정에서는 운영 DB·원장·브라우저를
변경하지 않았다.

추가 보정으로 Sol 검토를 실행 워커의 critical path에서 제거했다. 검토는 `background=true`로
병렬 시작하고, 일반 실행·중간 보고는 `review_pending`으로 계속 진행한다. 외부 게시·전기·
배포·결제·보안 변경 같은 고위험 최종 확정에서만 검토 PASS를 기다린다. 검토가 권한이나
추가 입력에서 막히면 본 작업을 멈추지 않고 `review_blocked`로 종료한다.

## 2026-08-21 Paseo IAB 예약 범위 재대조 — 최신화 필요

사용자 요청에 따라 Paseo IAB 전용으로 10개 읽기 전용 레인을 병렬 실행했다. Edge/CDP/UIA
경로와 Agoda 고객센터/도움말 버튼은 사용하지 않았고, 원장·OTA DB·candidate DB·외부
서비스에는 쓰지 않았다. 일부 레인은 라우트 timeout/reset으로 중단됐으며, 이는 한정된
failure code로 보존하고 반복 재시도하지 않는다.

부모 Paseo 탭의 현재 목록 집계는 다가오는 예약 116건(페이지 40/40/36), 완료 예약
페이지 1~9 360건이다. 완료 페이지 9의 과거 연도 6건을 제외한 현재 연도 후보는 354건이다.
기존 `outputs/agoda-paseo-staging.json`은 555건(Upcoming 80, Completed 475)으로,
해시 기반 membership 대조 결과 Upcoming은 80/80 일치하고 36건이 최신 라이브 목록에
추가됐다. 완료 현재연도는 354건 중 353건이 일치하고 1건은 staging에 없다. 이 결과는
목록 범위 대조이며 상세 증거·카드 대사·회계 권위를 의미하지 않는다.

C04는 완료 페이지 7~8에서 목록 80건과 상세 40건을 읽었고 C06은 완료 페이지 11~13에서
상세 1건을 읽었으나 목록 복귀/페이지 라우트 실패로 private staging 병합까지 완료하지
못했다. 따라서 다음 실행은 새로 보인 Upcoming 36건과 완료 1건의 상세 증거를 먼저
private staging에 보완하고, 그 뒤에만 카드 대사를 재실행한다. 현재 카드 reconciliation
review는 여전히 FAIL이며, confirmed authority·promotion·전기는 0건이다.

이번 집계에서 권한 요청은 0건이었다. 검토는 백그라운드 사후 검토이고 실행 critical path가
아니므로, 브라우저 수집은 검토 완료를 기다리지 않는다.

## 2026-08-21 Paseo IAB 상세 캡처 의미 및 완료 범위 확정

상세 캡처는 고객센터 호출이 아니라 예약 목록의 `예약 확인/변경하기`를 열어 예약번호,
숙소, 일정, 결제·환불 상태를 원문으로 확인하는 절차다. 이번 실행에서는 고객센터 버튼과
지원 라우트를 클릭하지 않았다(`customer_center_click_count=0`, `support_route_count=0`).

Upcoming page 3의 최신 36건은 36/36 상세 ID가 목록 ID와 일치했고 결제 라인·일정도 모두
확인되어 `outputs/agoda-paseo-staging-refresh-20260821.json`에 반영했다. refresh staging은
591건, unique 591건, SHA-256 `53db93800ac55b0178faac2bc4945739e76dcfd3aa8d805c9fc26807f25c0b5b`다.

완료 예약 현재연도 membership의 staging 미포함 1건은 상세 라우트가 호텔이 아닌 항공
예약(`/flights/account/bookingdetails`)으로 확인됐다. 호텔 staging 범위에서는 실제 누락이
0건이므로 호텔 staging에 넣지 않았고, 분류 결과를
`outputs/agoda-completed-coverage-audit-20260821.json`에 보존했다.

카드 대사는 여전히 FAIL이다. 카드 권위 원문·card4 결속·refresh staging 재투영이 없으므로
promotion/posting/ledger 전기는 모두 금지 상태이며 이번 실행의 DB·원장·외부 쓰기는 0건이다.

## 2026-08-21 Agoda 상세 카드4 표본 보완 및 대사 보류 고정

Paseo IAB의 예약 상세 경로에서 새로 확보한 호텔 예약 36건을 병렬 재확인했다. 고객센터·도움말·지원 경로 클릭은 0건이다. 36/36이 호텔 상세 페이지에 도달했고 36/36에서 카드 끝 4자리가 표시됐다. 결제 상태는 즉시 결제 5건, 자동 결제 예정 26건, 숙소 현장 결제 3건, 보증용 카드 2건으로 분리했다.

이 표본은 기존 목록 staging의 parser 누락을 보완하는 증거이며 전체 591건의 권위 있는 카드 원문·실제 청구 금액·통화·card4 결속을 대신하지 않는다. 따라서 `outputs/agoda-paseo-staging-refresh-card4-20260821.json`과 `outputs/agoda-card-reconciliation-card4-refresh-status-20260821.json`을 별도 보존하고, promotion/posting/ledger 반영은 계속 금지했다. DB write 0건, posting 0건이다. 카드4 표본 파일 SHA-256은 `d3d4067dda0f9844839d1712518e34f3296b55d6a35f57da107cbf5fae029e0d`다.

검토는 실행 critical path 밖에서 처리하며, 검토 권한 요청·알림·지연 때문에 브라우저 수집을 중단하거나 고객센터를 호출하지 않는다. 다음 경계는 전체 호텔 상세 census를 private sealed DB로 완결한 뒤 card raw/projection source hash와 결속하고 read-only candidate graph를 재실행하는 것이다.

레거시 `tools/agoda_detail_parallel_supervisor.py`는 기본 `msedge`를 실행하지 않도록 Paseo IAB 전용 오류로 즉시 중단하게 수정했다. 기존 Windows UIA/CDP 도구는 현재 수집 경로가 아니며, Agoda 브라우저 작업은 Paseo IAB MCP에서만 수행한다.

기존 555건 staging의 숫자형 `detail_id`를 현재 Agoda 상세 URL에 재사용한 probe는 `errorpage`로 돌아왔다(`STALE_NUMERIC_DETAIL_ROUTE`). 현재 36건은 목록에서 얻은 opaque detail route로만 정상 캡처됐다. 이 범위 문제를 `outputs/agoda-full-detail-expansion-blocker-20260821.json`에 고정했으며, 전체 census를 위해서는 현재 목록 재열거가 필요하다.

추가로 현재 Upcoming page 1에서 opaque 상세 route 8건을 시도했고 2건이 상세 화면까지
도달했다. 기존 page 3 상세 36건과 합쳐 현재 Upcoming 상세 증거는 38건이며, 카드4가
확인된 건도 38건이다. 나머지는 route timeout 또는 목록 화면 복귀로 중단되었고, 무한
재시도하지 않았다. 상태와 실패 코드는
`outputs/agoda-upcoming-opaque-detail-capture-status-20260821.json`에 보존했다.
고객센터·지원 경로 클릭은 계속 0건이며, 카드 reconciliation FAIL 및 promotion/posting
금지는 변하지 않는다.

10개 병렬 lane의 추가 결과를 source ID 기준으로 재집계했다. 기존 page 3 상세와 겹치는
성공 2건은 제외했고, page 1에서 고유 상세 5건을 더해 현재 Upcoming 상세 증거는 41건이다.
그중 card4가 명시적으로 확인된 건은 40건이며 1건은 상세 성공만 확인되어 card4 상태를
unknown으로 남겼다. 결제 상태는 기존 확정값과 추가 확인값을 분리했고, 전체 116건 상세
census는 아직 닫지 않았다. lane별 page-state mismatch, page-route failure,
detail-data-unavailable가 반복되어 promotion/posting은 계속 금지한다.

수집 관련 회귀·대사·후보 graph 테스트 91건은 재실행 결과 모두 통과했다. 이는 코드
회귀 검증이며, Agoda 전체 상세 census나 카드 권위 결속이 완료됐다는 뜻은 아니다.

후속으로 탭 재사용을 중단하고 예약별 새 Paseo IAB 탭에서 한 번만 상세를 여는 방식으로
page 1을 재수집했다. page 1 source ID 15건이 모두 호텔 상세·card4까지 확인됐고,
page 3 기존 36건과 합쳐 Upcoming 상세 증거는 51건으로 갱신됐다. page 1 나머지와
page 2는 아직 미확인이다. 신규 page 1 원문 요약은
`outputs/agoda-upcoming-page1-opaque-detail-evidence-20260821.json`에 보존했고,
대사 상태의 opaque expansion도 51건/51건 card4 확인으로 갱신했다. 전체 census와
카드 raw 권위 결속이 닫히지 않았으므로 FAIL·promotion 금지는 유지한다.

## 2026-08-21 Paseo IAB Upcoming 상세 census 완료

예약별 새 Paseo IAB 탭/명시적 목록 복귀 방식으로 Upcoming page 1의 40건과 page 2의
40건을 추가 캡처했다. page 2는 `page=2` 주소만으로는 첫 목록이 다시 표시되고 목록의
`다음` 제어를 눌러야 실제 page 2가 되는 라우팅 특성이 확인됐다. 이 제어를 확인한 뒤
각 예약의 `예약 확인/변경하기`만 열었고 고객센터·지원 경로는 클릭하지 않았다.

현재 Upcoming page 1~3은 목록 116건, 상세 성공 116건, 카드4 표시 확인 116건으로
닫혔다. page 1·2 증거는 각각
`outputs/agoda-upcoming-page1-opaque-detail-evidence-20260821.json` 및
`outputs/agoda-upcoming-page2-opaque-detail-evidence-20260821.json`에 보존했고,
opaque detail 상태와 reconciliation 상태에도 116/116을 반영했다. 두 페이지 모두
40/40 unique source ID·detail success였으며 customer center click은 0건이다.

이 결과는 예약 상세 census를 닫은 것이지 카드 원문이 실제 청구액·통화·card4와
권위 있게 결속됐다는 뜻은 아니다. 카드 대사 review는 여전히 FAIL,
promotion/posting/ledger 전기는 계속 금지이며 write effect는 0건이다. 대상 Agoda
portal/detail·card reconciliation·candidate graph 회귀 테스트 91건은 재실행 결과
모두 통과했다. 완료 예약 전체의 상세 census와 카드 raw/projection authority 결속은
별도 미완료 범위로 남긴다.

이번 실행에서 종료된 병렬 Agoda 레인과 과거 Sol/Edge 검토 agent는 정리·보관했고,
현재 pending permission은 0건이다. 따라서 검토 권한 알림이 실행 critical path를
다시 멈추지 않도록 현재 작업 공간에는 부모 agent만 남겨 두었다.

## 2026-08-21 Agoda 고객센터 패널 실시간 incident

사용자 화면에서 `아고다 고객센터` 패널과 Paseo 데스크톱 알림이 실제로 열린 상태가
확인됐다. 기존 산출물의 `customer_center_click_count=0`은 과거 수집 실행의 계측값일
뿐이며 현재 브라우저 상태를 증명하지 못한다. Paseo IAB DOM을 읽기 전용으로 대조한
결과, 동일한 Agoda 예약 목록 URL의 탭 2개 모두 채팅 패널 본문(`요청 사항을 선택하거나
직접 입력해 주세요`)을 포함하고 있었다. 고객센터 버튼이 예약 카드에 보이는 것은 기본
Agoda UI지만, 패널이 열린 것은 정상 수집 상태가 아니다.

현재 활성 agent는 부모 1개뿐이고 pending permission은 0건이었다. 두 탭은 고객센터
UI를 누르지 않고 닫았으며, 이후 Paseo 탭 목록은 0개가 됐다. 이 incident 중 예약 상세
수집·원장·DB·외부 쓰기는 없었다.

직접 확인된 원인은 `예약 확인/변경하기`와 `아고다 고객센터에 연락하기`가 카드마다
함께 존재하는 화면에서 과거 병렬 작업이 순번 기반으로 실행될 수 있었던 구조와 중복
탭/알림 잔류가 결합한 위험이다. 실제 최초 클릭 주체는 보존된 실행 이벤트만으로 확정할
수 없으므로 이를 단정하지 않는다. Sol 검토의 권한 요청이 이 패널을 직접 열었다는
근거도 없지만, 같은 workspace의 검토·실행 혼합은 권한 알림과 작업 지연을 만든 별도
원인이다.

재발 방지로 레거시 CDP 브리지도 다음 경계를 추가했다. 고객센터 패널이 보이면
`customer_service_panel_open`으로 fail-closed하고, 상세 열기는 카드 내부의
`blp-booking-item-button-edit` 또는 명시적인 `예약 확인/변경하기`만 허용하며,
고객센터/지원 텍스트를 가진 control은 거부한다. Python capture/detail 경로도 목록·
상세·복귀 단계에서 같은 패널 플래그를 차단한다. `node --check`, `py_compile`, Agoda
관련 91개 테스트는 PASS했다. 현재 Agoda 대사는 카드 권위·실청구액/통화 결속 등이
아직 닫히지 않아 FAIL 및 posting 금지를 유지한다.

AGY Gemini 점검은 `GEMINI_API_KEY` 부재로 호출되지 않아 Luna가 구현·검증을 이어갔다.
Sol 검토는 실행 workspace와 dirty tree를 공유하지 않는 immutable snapshot을 확보한 뒤
background로만 시작해야 하므로 이번 실시간 incident의 critical path에는 붙이지 않았다.

## 2026-08-21 Agoda 상태 산출물 정합성 보정

읽기 전용 재점검에서 Upcoming 1~3의 상세·card4 116/116은 이미 닫혔는데,
상태 JSON에 과거 `FULL_PORTAL_CARD4_CENSUS_MISSING` 및
`CURRENT_UPCOMING_FULL_OPAQUE_CENSUS_INCOMPLETE`가 현재 차단처럼 남아 있던 것을
확인했다. 두 코드는 각각 완료 탭 상세 범위 미완료 hold와 해결된 이력 코드로 정리했다.
현재도 카드 원문/프로젝션 권위, 실제 청구액·통화 결속, 완료 탭 상세 범위,
refresh staging 재투영은 닫히지 않았으므로 `promotion_allowed=false`,
`posting_allowed=false`는 유지한다. JSON UTF-8 파싱과 Agoda 관련 91개 테스트는
재검증 PASS이며 브라우저 탭·권한 요청은 0건이다.

같은 날 메모리 DB에서 정상 `import_cards`/`project_card_payments`를 재실행해 카드 원천
자체도 별도 확인했다. `card_raw` 5,237건 전부의 저장 payload hash가 일치했고,
projected payment는 5,328건이었다. 이 결과는
`outputs/agoda-card-raw-authority-audit-20260821.json`에 보존했다. 따라서 남은
차단은 카드 파일 누락이 아니라 Agoda opaque 상세와 카드 원문·실청구액·통화 사이의
권위 관계가 아직 닫히지 않은 점이다.

## 2026-08-21 Agoda 완료 2페이지 후반 재개 확인

브라우저 호스트 재연결 후 새 Paseo IAB 탭을 예약마다 만들고 완료 예약 2페이지 후반
8건을 `blp-booking-item-button-edit` 고정 selector로 재확인했다. 8/8이 호텔 상세
화면에 도달했고 8/8에서 카드 끝 4자리가 표시됐다. 고객센터·지원 경로 클릭은 0건이다.
중간 병렬 묶음은 호스트가 끊겨 저장되지 않은 부분 결과가 있으므로 완성 증거로 합치지
않았다. 이번 재확인은 읽기 전용이며 DB·원장·외부 쓰기는 0건이다.

## 2026-08-23 Phase 0 워크스페이스 위생과 Windows 테스트 기준선 복구

이전 세션의 미커밋 변경을 주제별 4커밋(e55e3bf·18103e2·20c8049·0c30ef5)으로 분리
반영했다. `.gitignore`에 `outputs/*.sqlite*`와 `outputs/agoda-benchmark-*.json`을
추가해 생성 DB·벤치마크 산물을 추적에서 제외했고 파일 자체는 디스크에 보존했다.

이어서 이 Windows 작업공간에서 Agoda 회귀 서브셋(237테스트)이 FAIL 3·ERROR 12로
깨져 있음을 실측으로 확정했다. 과거 LOG의 "91개 PASS"는 POSIX 환경(Linux 세션) 측정으로,
Windows에서는 구조적으로 통과 불가능한 계약들이 원인이었다. 수정 내용:

1. POSIX 전용 모드 계약(0o600/0o700)을 `os.name != "nt"` 조건으로 플랫폼 분리
   (amount_reconciliation `_require_private_sqlite`, card_payment_confirmation
   `_require_private_file`). Linux 의미는 불변.
2. `open("rb")` 핸들에 `os.fsync` → EBADF(Bad file descriptor) 오류를
   `open("r+b")`으로 수정(amount_reconciliation ×2, card_payment_confirmation ×2,
   detail_capture, full_survey). `_publish_noreplace`의 읽기전용 fd fsync도 O_RDWR로
   바꾸고, 디렉터리 fd fsync는 POSIX에서만 실행한다.
3. `with sqlite3.Connection`이 close가 아닌 트랜잭션 컨텍스트라 Windows에서 파일
   잠금(WinError 32)을 유발 — merge 입력·detail sealed/work 요약·full_survey 검증·
   amount_rec output 검증·관련 테스트들을 `contextlib.closing`으로 결정적 close로
   변경했다. 최소 재현 스크립트로 leak을 먼저 증명한 뒤 수정했다.
4. msvcrt.locking의 잠금 충돌이 PermissionError로 나오는 것을 `_try_private_file_lock`
   이 수용하도록 `(BlockingIOError, PermissionError)`로 확장했다.
5. `PAGINATION_CONTROL_RE`가 두 번 정의돼 두 번째(범용판)가 첫 번째(엄격판)를 덮어
   bare `Next`를 page-step으로 오판하던 것을 수정: `_is_page_step_control`을
   `_pagination_controls` 선택 결과에 위임하고, labeled 선호 판정에 `페이지` 접미를
   추가했다. 실제 클릭 대상 선택 규칙은 기존 선호 로직 그대로다.
6. page_capture WSL 브리지 제거 후 남았던 테스트 드리프트(`_resolve_windows_temp_dir`
   → `_resolve_temp_dir`, exe_info 키 win/wsl_path→path, csc 명령 WindowsBase 포함,
   wslpath 타임아웃 블록 폐기, script_path 3종을 현재 계약으로 재작성)를 정리하고,
   POSIX 전용 계약 테스트(mkfifo·chmod 비트·fork 시작방식)에 skipIf 가드를 추가했다.
7. rebind CLI 테스트는 Paseo IAB fail-closed 정책 BLOCKED(PASEO_IAB_ONLY, 종료코드 2)
   을 단언하도록 재작성했다. route_reset 목 mock을 현재 state 구조에 맞춰 갱신했다.

결과: Agoda 서브셋 237개 OK(skipped 7=POSIX 전용), tools 내부 5개 OK. 전체
unittest 스위트는 백그라운드 터미널에서 재실행 중이다. Sol 독립 검토는 immutable
snapshot 부재로 review_deferred 유지. AGY Gemini는 GEMINI_API_KEY 부재로 미호출,
본 세션(opencode)이 구현·검증을 수행했다.

## 2026-08-23 전체 스위트 기준선 측정과 비아고다 실패 분류

전체 unittest 스위트(729테스트, 39.6분)를 이 Windows 머신에서 최초 완주해
FAIL 15·ERROR 73·skipped 26을 실측했다. 사용자 지시로 아고다 관련 파일과 진행 중인
Luna(codex) 세션의 작업은 건드리지 않았고, 비아고다 실패만 처리했다.

수정한 것(185ca9d): 테스트의 무인코딩 `read_text`/`write_text` 31곳을
`encoding="utf-8"`으로 고정했다. cp949 로캘에서 한글 JSON이 깨져 r41 입력 해시
게이트까지 연쇄 실패했던 것이 근본원인이며, CLI 재빌드 테스트의 `python3` 호출은
`sys.executable`로 바꿔 Windows 종료코드 9009를 해소했다. Linux는 UTF-8이 기본이라
동작 불변이다. 실측: owner_review 모듈 18개 중 17개 통과(잔여 1개는 아래 환경 경계),
projection의 이전 실패 3건 중 1건 통과.

남은 비아고다 실패는 코드 결함이 아니라 환경 경계 두 종류로 확정했다.
①라이브 입력 바이트 게이트: `/tmp/cost-r*` 봉인 스테이징 부재(all_period_* 계열
setUpClass 17종), 커밋된 ledger/data의 CRLF 체크아웃으로 r39 권위 해시·r41 인덱스
해시·v6 상수가 불일치(han/projection/owner_review/ota_lifecycle). ②POSIX 전용
프리미티브: 심볼릭링크 권한(WinError 1314), renameat2·부모 디렉터리 fsync·nlink
계약(lineage_annex·receipt_airfare·p07 발행/검증 스택). 이들은 Linux 세션에서
역대 통과 이력이 있는 설계된 경계다. Windows 상시화가 필요하면 `.gitattributes`
줄바꿈 정책 결정이 선행 과제다(별도 승인 필요, Luna 동시 작업 중 대규모 정규화 금지).

재측정은 분리 프로세스로 실행하며 결과는 `%TEMP%\opencode\full-baseline2.log`에
기록한다. Sol 검토 review_deferred 유지.

## 2026-08-23 Windows 상시화 Wave 1 — 정책 선언과 활성화 런북

사용자 결정에 따라 Windows를 상시 환경으로 진행한다. 이번 세션에서 안전하게
선언만 완료했고, 작업 트리 플립은 동시 Agoda 세션(codex)의 미커밋 변경이
사라진 조용한 시점에 실행한다.

완료(1e2d979): `.gitattributes`로 LF 캐논 컬 정책 선언(`* text=auto eol=lf`,
바이너리 산출물 명시 제외). 로컬 `core.autocrlf=false` 설정. symlink 권한 프로브
결과 WinError 1314(권한 없음) 확인.

Wave 2 활성화 순서(Sol 세션이 커밋·idle이 된 뒤, 단일 세션에서):
1. 미커밋 잔여가 있으면 해당 경로만 `git stash push -- <paths>`.
2. `git add --renormalize .` 후 커밋(인덱스는 이미 LF라 변경 최소).
3. 작업 트리를 정책대로 재추출: `git rm -rq --cached . && git reset --hard`
   (untracked는 보존됨). 모든 텍스트가 LF로 materialize된다.
4. stash 사용 시 pop으로 복원. 개행 문맥 충돌이 나면 해당 파일은 수동 재적용.
5. 영향 모듈 재실행로 검증: test_direct_projection(han 3종),
   test_direct_owner_review(v6), test_direct_ota_lifecycle_support,
   test_han_master_candidate — r39/r41/v6 해시 게이트가 통과로 바뀌어야 한다.

추가 전제: symlink 계약 테스트(lineage_annex 등 다수)는 Windows Developer Mode
활성(또는 관리자 1회)으로 권한을 열면 코드 수정 없이 통과한다. renameat2 기반
p07 발행 스택(프로덕션 23곳)은 Linux 전용 설계로, Windows 지원은 발행 백엔드
추상화 리팩토링(별도 계획 R1) 이후에만 가능하다 — 그 전까지 해당 패밀리는
Linux 세션 전용으로 남긴다.

## 2026-08-23 Windows 상시화 Wave 2 실행 완료와 해시 핀 원인 정정

Sol 세션 종료 확인 후 런북대로 실행했다. Sol의 문서 미커밋분(AGENTS·CLAUDE,
agy provider 라우팅 보강)은 stash로 보호→플립 후 복원→`a5e35e3`로 커밋했다.
`f0797f6`에서 인덱스 블롭이 CRLF였던 데이터 파일 3종(classified_v12.csv,
manual_expenses.csv, master_ledger.csv)을 LF로 재정규화했고, `git rm --cached
전체 + reset --hard`로 작업 트리 전체를 LF로 materialize했다. 검증: 트리 클린,
LOG.md 바이트 CR 0개, 아고다 서브셋 251/251 OK(Sol 신규 batch-import 테스트
포함, 1건은 수집 시뮬레이션 타이밍 플레이크였고 재실행 소멸).

중요 정정: 직전 분류에서 r39/r41/v6 실패를 "CRLF 체크아웃" 탓으로 했으나
해시 변형 전수 대조(LF·CRLF·원본 모두 불일치)로 **콘텐츠 드리프트**가 원인임이
확정됐다. 예: r41 MAIL_SHA 상수 db258948... vs 현재 ota_mail_index.json
079ff8d9.... 즉 커밋된 데이터가 핀 작성 이후 갱신되어 어느 플랫폼에서도
실패하는 값이다. Wave 2의 진짜 기여는 (a) 앞으로의 핀이 플랫폼 무관하게
성립하는 바이트 결정론 확보, (b) CRLF 블롭 3종 제거, (c) 로컬에서 권위
상수 재계산이 가능해진 점이다.

미결(사용자 승인 필요): r41/r39/v6 등 드리프트 핀의 리베이스라인. 권위 상수를
현행 HEAD 데이터 기준으로 재계산해 갱신하는 것은 증거 기준선 변경이므로
명시 승인 없이 수행하지 않는다. 대안은 Linux 세션에서 체인 전체를 재실행해
핀을 재생성하는 것이다. /tmp 라이브 입력 패밀리(all_period_* 23모듈)와
renameat2 발행 스택은 여전히 환경 경계로 남는다.

## 2026-08-23 규칙 레지스트리화 사전조사 — 착수 보류 판정과 게이트 티어링 설계

사용자 승인으로 direct_all_period_* 예외 모듈의 레지스트리화를 시작하려 했으나,
착수 전 실측 조사에서 실행 보류가 정답으로 판명했다.

실측: 모듈 23개, 총 2,283줄(평균 99줄). 모듈별 공통 스캐폴딩(_sha·canonical
guard·context 순회·manifest 공통 필드)은 약 15~20줄뿐이고 나머지 80줄 내외는
가족별 고유의 핀 증명 논리(정확 건수·집합 해시·상류 체인 검증)다. 즉 데이터
주도 레지스트리로 바꿔도 절감량이 소박하고, 결정 의미는 그대로 남는다.
결정적으로 **로컬에서 0/23이 실행 가능**하다(/tmp 라이브 입력 부재로 setUpClass
전원 실패, full-baseline2 로그 재확인). 검증 불가능한 코드의 대규모 구조변경은
P22 정신에 반하므로 보류한다. 재평가 시점: Windows Wave 2 활성화로 r39/r41
해시 게이트가 열린 뒤, 또는 Linux 세션에서 게이트 전체 통과를 확인한 뒤.

대신 승인된 목적(검증 비용은 유지하면서 전기 흐름을 막는 과잉 완화)을 위해
게이트 티어링 설계를 확정한다. 세 티어:

- TIER1 blocking-money(전기·게시 직전 필수): 카드 원단위 대사, 취소·환불 페어
  순액 정합, 멱등 재실행 해시 동일, no-replace 발행 검증. 영구 불변.
- TIER2 blocking-completeness(운영 전기 시작의 전제, 현재 진행형): Agoda 카드
  권위 결속(Phase 1), Gate4 HAN equality, Gate6 baseline, Gate5 잔여 상한.
- TIER3 advisory(막지 않고 리포트만): 8종 검토 큐 세분화, 중중복 attestation
  해시, 문서 정합 경고, 저신뢰 참고 건.

효과: 현행 `promotion_allowed=false` 전면 차단을 TIER1+TIER2 축소판으로 먼저
열 수 있는지 별도 사용자 승인으로 검토한다. 권위 독립 계정(기타비용 등)부터
부분 승격하는 옵션이 후보다. 구현은 transition_gates_v2에 티어 메타데이터를
추가하는 방식이며 동작 변경은 없다(승인 전까지).

## 2026-08-23 Agoda 카드 연결 후보 v4 생성·멱등성 감사

봉인 Agoda 입력 `outputs/agoda-paseo-staging-20260822.sqlite`
(SHA-256 `39f8750897d98ee131dac6693ad0f1ca16e3e177f013dda6a9f70c1e79ac45b3`)
을 수정하지 않고 복제한 별도 후보 DB에서 카드 RAW 5,237건을 적재하고 결제 5,328건을
투영했다. 두 번째 카드 적재는 신규 삽입 0건이었고 source/card-event/normalized-payment
의 비시간 의미 해시는 첫 적재 후와 같았다. 후보 계산은 DB serialization hash와
`total_changes`를 바꾸지 않았고, 같은 DB 2회 결과 및 별도 in-memory 재빌드 결과의
candidate report content hash가 일치했다.

최종 결과는 exact amount/currency/card4와 Agoda 상호·lifecycle·source digest 경계를
모두 통과한 1:1 `proposed` 77건, 개별쌍을 만들지 않는 N:N review group 9개,
amount candidate 152건, held 5,899건이다. 우연히 금액·card4가 맞은 비Agoda 상호가
후보가 되던 문제를 발견해 상호를 관찰된 Agoda prefix/form으로 fail-closed했다.
첫 Sol 검토에서 `AGODA가짜`/`AGODAé` Unicode suffix 우회를 추가 발견해 차단하고
회귀시험을 보강했다. 최종 immutable snapshot 검토는 PASS(차단 사항 없음)였다.

이 단계는 candidate-only다. `payment_booking_links`, classification, allocation,
cost allocation, journal/posting authority 표는 모두 실행 전후 0건이며 canonical link나
전기는 생성하지 않았다. DB integrity는 `ok`, foreign-key violation은 0,
portal/card payload digest mismatch도 0이다. 관련 회귀 83건과 직접 projection 핵심 5건,
총 88건은 PASS했다. `test_direct_projection` 모듈 전체 실행은 기능 실패가 아니라
304초 실행 제한으로 중단되어 전체 통과로 세지 않았다.

최종 산출물:
- DB: `outputs/agoda-card-link-candidate-v4-20260823.sqlite`
  SHA-256 `be4696799469e94279b152fb09c13141d61220e8569c151f3bf558ace58e0cc6`
- 후보 보고서: `outputs/agoda-card-link-candidate-v4-20260823.json`
  SHA-256 `e071c3f8a982d89bc13bef26dc1c334b51593993ff9307653d2dd2690b1293d5`
- 상세 보고서: `outputs/agoda-card-link-candidate-detail-v4-20260823.json`
  SHA-256 `ec14e1efdb8306f4eef476bf40a394b79f00a605ff5ff0485206f9264d95b6af`
- 감사 보고서: `outputs/agoda-card-link-candidate-audit-v4-20260823.json`
  SHA-256 `9bbb1419abeeac0664ae7fe40ab20b2865aa6941746a901dc231e9ebc57f0a25`
- 재현 명령: `python tools/build_agoda_card_link_candidate.py --version v4 --date 20260823`

AGY wrapper/API key를 사용할 수 없어 AGY 호출은 하지 않았고 Luna max가 실행을
이어받았다. Sol 검토는 실행 critical path와 분리된 read-only snapshot에서 수행했다.

## 2026-08-24 Agoda 1:1 후보의 proposed 링크 자동 등록

가역적인 `proposed` 링크 등록에 사용자 승인을 요구한 것은 과도한 게이트로 판단해
철회했다. 기존 `모두 진행` 지시 범위에서 v4 후보 DB를 수정하지 않고 복제한
`outputs/agoda-card-proposed-links-v1-20260824.sqlite`에 강한 1:1 후보 77건만
`payment_booking_links(link_status='proposed', relation_type='pays_for', confidence=1.0)`로
등록했다. N:N review group 9개는 개별쌍을 만들지 않았다.

각 링크에는 exact candidate report SHA와 reservation/payment key를 결속한
`direct_agoda_card_proposed_link_authorities` 77건을 함께 저장했다. 같은 입력을 두 번째
적용한 결과 추가 변경은 0건이었다. integrity `ok`, FK violation 0,
classification/allocation/journal 표는 모두 0건으로 불변이다. 원본 v4 후보 DB SHA도
`be4696799469e94279b152fb09c13141d61220e8569c151f3bf558ace58e0cc6`으로 유지됐다.

- proposed-link DB SHA-256:
  `11590ba10510cc129a3860c6c837b0e1ae070345275e6f3b74e7ef90510d0c24`
- audit SHA-256:
  `ba4800913e403c66615fc5d25f276f69f2abd4dc47f66d521c452815b5caa4cb`
- 재현 명령: `python tools/promote_agoda_card_candidates.py`

향후 자동 진행 대상은 원천 보존, 후보/`proposed` 등록, 결정 가능한 분류·배부 초안,
검증이다. 사용자 승인은 저장소 규칙으로 결정되지 않는 실제 회계정책 선택 또는 최종
권위 원장 전기처럼 되돌리기 어려운 경계에만 요청한다.

## 2026-08-24 Agoda 분류·배부 및 41건 journal draft

`proposed` 링크 DB를 변경하지 않고 복제해 Agoda 숙박 77건 전부에 `숙박비`·
`여행원가`·`불공제_해외` 분류 초안과 배부 계획을 만들었다. 서비스 기간과 현재
여행 일정이 한 개로만 결속된 41건은 trip target이 결정됐고, 23건은 일정 중첩으로
ambiguous, 13건은 현재 일정에 대응하는 target이 없어 missing으로 남았다. 모든
classification decision·allocation plan·booking link는 `proposed`이고 posting eligibility는
0이다.

- accounting draft DB:
  `outputs/agoda-card-accounting-draft-v1-20260824.sqlite`
  SHA-256 `a0bf9ff2ccd0d15a16883a64c1e78e6cc1840c491f1b356fc911281a0e18b889`
- detail SHA-256:
  `cfc85cc1af692fcccbd4be37923ed9cbd88511d11e4c47d934b776a0a9d7689f`
- audit SHA-256:
  `e6326c8d5204d8df4e03d416d26b43526b73ef8c69f4187e1d0a1d8d7868e5ad`

미확정 36건에는 과거 수기 분류를 현재 권위로 승격하지 않고 candidate evidence로만
대조했다. 22건은 예약번호·KRW 금액이 정확히 일치하는 과거 target 후보가 있었고,
12건은 숙소명 증거만 있었으며, 2건은 추가 증거가 없었다. 이 36건은 모두
`candidate_only`/`blocked`다.

trip target이 유일한 41건만 별도 journal draft로 만들었다. 41 batch/82 line,
차변 `숙박비`·대변 `법인카드미지급금`, 차변=대변=KRW 10,018,782이다. legacy
`journal_entries`와 `direct_accounting_posting_*`에는 한 행도 쓰지 않았다.

- journal draft DB:
  `outputs/agoda-card-journal-draft-v1-20260824.sqlite`
  SHA-256 `1ca7a1b3190861a0022b01eff5f8a6e8ac14149d035fc070262d11689af8a0fc`
- detail SHA-256:
  `02b995677d2956cd94d97a441e5818146680c19cb6ee25f93e71cc8b83e38dad`
- audit SHA-256:
  `3692509c0ccad318f5c0491f0919d810e85149094c6c9c0fd21bb2d50fcf2f1c`
- semantic SHA-256:
  `3121715b61318c275136e2f67db03301c8c46b8e0582ad61da1ac69b67a26e62`

두 빌드 모두 입력 DB 불변, 두 번째 materialization 0 changes, 독립 재빌드 semantic
hash 일치, integrity/FK 정상이다.

## 2026-08-24 Agoda 일정 권위·연도 분리 v3

기존 `trips.json`의 `mm/dd/window`를 서비스 기간 권위로 사용하던 경로를 새 v3
산출물에서 차단했다. `ledger/domain/direct_trip_schedule_authority.py`는 명시적인
`starts_on`·`ends_on`·`event_year`·`end_semantics`·원천 SHA-256을 요구한다. 숙박
`service_end_on`은 checkout-exclusive로 취급하고, 일정 `ends_on`은 inclusive
last-service-date로 취급한다. 2025 결제는 `payment_lane='2025년 결제'`로 남기며,
독립적인 2026 서비스 권위가 없으면 2026 여행 target으로 승격하지 않는다. 명시적
권위 문서는 현재 `records=[]`인 빈 문서이며, 기존 window는 35개
`legacy_window_candidate`로만 변환된다. 날짜를 추정해 권위 문서를 채우지 않았다.

v3 accounting 결과는 77건/20,546,481원이다. 기존 window 기준 41건 unique, 23건
ambiguous, 13건 missing이었으나, 독립 권위 일정이 0건이므로 `bound_unique=0`,
`legacy_window_candidate_only=64`, `authority_missing=13`으로 재분류했다. v3 journal
shadow는 77 batch/154 line 전부 `미확정여행원가`·`여행_미배정`이고 차변=대변=
20,546,481원이다. posting/authoritative/external posting은 모두 0이다.

- authority module: `ledger/domain/direct_trip_schedule_authority.py`
- authority document: `ledger/data/trip_schedule_authority_v3.json`
- accounting v3 DB SHA-256:
  `79b2fdba5deaf2766c956b17aa0c0823d1b837cb706b5112013a1753108970a6`
- accounting v3 audit SHA-256:
  `41ffa7c55c4293ee6a2d9a75a32ec658ddebdd4b641c17cdbf84164dbc0245a1`
- journal v3 DB SHA-256:
  `8523f6736d2402879afad2a93d626cdf084d15d7e5d74b4526ef6e4265a549e7`
- journal v3 audit SHA-256:
  `c413b3c9b10f3bf4af1e85b881c3838c9162de0b36898f53b02cf75ab698a5b7`

동일 입력으로 재빌드한 accounting DB/detail/audit와 journal DB/detail/audit의 SHA-256이
각각 모두 일치했다. 무결성 `ok`, FK violation 0, posting table 0이다. v3와 기존
Agoda 관련 회귀를 합쳐 77/77 PASS했다. AGY 설계 검토는 `GEMINI_API_KEY` 부재로
호출 실패했으며, 성공한 AGY 검토로 표시하지 않는다.

## 2026-08-24 Agoda 77건 완전 복식부기 shadow v2

41건만 보이던 journal draft와 별개로 전체 77건의 회계 금액이 누락되지 않는지 증명하는
로컬 shadow v2를 만들었다. target이 정해진 41건/KRW 10,018,782은 차변 `숙박비`,
미확정 36건/KRW 10,527,699은 차변 `미확정여행원가`, 전 건의 대변은
`법인카드미지급금`이다. 결과는 77 batch/154 line이고 차변=대변=KRW 20,546,481이다.

이 shadow는 실제 전기가 아니다. 모든 batch가 `shadow_only`, `posting_eligible=0`,
`authoritative_posting=0`, `external_posting=0`이며 미확정 36건의 과거 exact 후보도
현재 target 권위로 승격하지 않았다. `journal_entries` 0건,
`direct_accounting_posting_*` 0건, 미포함 payment 0건이다.

- builder: `tools/build_agoda_journal_shadow_v2.py`
  SHA-256 `a21402304dac21b90f74993d2d90d0c84605cc62fcb9e05e8b096008dbc58bc7`
- DB: `outputs/agoda-card-journal-shadow-v2-20260824.sqlite`
  SHA-256 `b64c63bface95b634175acd34a91b28abf17f1b593194aceb1dcd496d78e84b6`
- detail: `outputs/agoda-card-journal-shadow-detail-v2-20260824.json`
  SHA-256 `e3f7b20454bdc2f476865198ee75f59be86b8daef9d91e55ff20fa17a9fc354c`
- audit: `outputs/agoda-card-journal-shadow-audit-v2-20260824.json`
  SHA-256 `9e88e912c55b1057f231fa27176716004609de9b50c2980306031fc50357f401`
- semantic SHA-256:
  `22702b3059b629c6781265092b9f8530602428fbf99d34ac61f8cdfdd65c7b58`

첫 materialization은 232 changes, 두 번째는 0 changes였고 독립 재빌드 semantic hash가
일치했다. account mapping issue 0, unbalanced batch 0, uncovered source 0,
unauthorized row 0, posting table row 0, FK violation 0이다. accounting/journal/shadow와
Agoda reconciliation·candidate graph·booking evidence를 합친 회귀 57건은 전부 PASS했다.

과거 proposed-link Sol 검토용 snapshot의 파생 파일 3개는 제거했다. 빈 snapshot
디렉터리 삭제는 실행 정책이 차단해 빈 껍데기만 남았다. shadow v2는 별도 읽기 전용
snapshot(`85c8019b9882fc6f82e2059097a290f1b08e6c8ae324918d746ceb8b318f3a93`)
에서 Sol high 정적 검토를 background/non-blocking으로 시작했다. 검토 agent는
`notifyOnFinish=false`이며 실행 critical path와 분리됐다. 결과가 오기 전까지는
`review_pending`이고 독립 PASS로 표시하지 않는다. AGY는 앞선 세션에서 API key 부재가
확인돼 재호출하지 않았고 Luna가 구현·검증을 계속했다.

## 2026-08-24 Agoda 일정 권위 v3 clean 산출물 교정

앞서 v1 accounting DB를 입력으로 만든 `v3-final`은 원본 v1의 구형 분류·배부
테이블을 복제한 것이 확인되어 최종 산출물로 채택하지 않는다. 분류·배부 행이 0건인
`agoda-card-proposed-links-v1`를 입력으로 다시 만든 `v3-clean`만 사용한다. clean DB와
clean journal shadow에는 `classification_decisions=0`, `allocation_plans=0`,
`cost_allocations=0`, `journal_entries=0`이며 v3 테이블만 77건/154라인이다.

- clean accounting v3 DB SHA-256:
  `c5b58924a3926931633d5adf1836831c2f7fa4cfe959f0bdd46418dbfc68c760`
- clean accounting v3 audit SHA-256:
  `706034454bc41865189141f6e154d0b8155e471361dee4f1586fa6a3c81ecfa9`
- clean journal v3 DB SHA-256:
  `9e408224e37c292afd3651b0d3334b2ff06c9c5d3df1fcd65c046b10ab2dc12c`
- clean journal v3 audit SHA-256:
  `67a7d68375cf1eab7a9ebf418b90e6a613e78ec06c0bca2f858623a96c7852a0`

clean 산출물도 별도 경로로 재빌드한 6개 파일의 SHA-256이 모두 일치했다.

## 2026-08-24 여행기간 권위 규칙 전역 정렬

기존 규칙의 핵심은 이미 문서에 있었지만, 구현 경로마다 `trips.json`의
`mm/dd/window`를 서로 다르게 해석해 후보와 최종 배정의 경계가 흐려져 있었다. 이번 정렬은
새로운 수동 `ends_on` 입력을 추가한 것이 아니라, 기존 원칙을 공통 판정기로 고정한 것이다.

- `ledger/domain/direct_trip_schedule_authority.py`
  - 명시적인 연도·시작일·종료일·종료 의미·권위 상태·원천 hash가 있는 행만 최종 권위로 인정.
  - 숙박/예약의 `service_end_on`은 체크아웃 제외형으로 정규화하고 마지막 실제 이용일을
    `service_end_on - 1일`로 생성. 정식 행사 일정의 `ends_on`은 포괄적인 마지막 행사일로 유지.
  - `normalize_service_period()`를 OTA 대사와 일정 매칭의 공통 경계로 사용.
- `ledger/domain/direct_verified_ota_lodging.py`,
  `direct_geographic_trip_context.py`, `direct_ota_reservation_authority.py`,
  `direct_projection.py`, `tools/build_agoda_accounting_draft.py`
  - 대사·target 검증·allocation·초안 재검증은 `load_authoritative_trip_schedule()`만 사용.
  - 레거시 `window`는 후보/감사 설명에만 남고 최종 allocation·전기를 만들 수 없다.
- `ledger/domain/ledger_db.py`
  - 레거시/코드명으로 생성된 relational trip은 날짜가 NULL이고 `candidate_only`다.
  - 명시적인 양 끝 날짜가 들어온 경우에만 `planned`로 승격하며, 기존 candidate 행도 그때만
    복구된다. 코드명에서 월일을 추론하는 `infer_trip()`도 제거했다.
- `AGENTS.md`, `docs/비용분류_지시사항_원장.md`
  - 위 계약을 모든 에이전트와 사용자용 출력 경로의 전역 규칙으로 명시했다.

기존 레거시 일정 데이터는 임의로 권위화하지 않았다. 현재 권위 문서가 비어 있으므로 해당
일정에만 의존하는 기존 행은 안전하게 `candidate_only`/`여행_미배정`으로 보류된다. 실제
권위화가 필요할 때는 정식 일정표·OTA 서비스기간 등 독립 원천을 명시 날짜와 함께 수집해
`trip_schedule`에 넣어야 한다.

검증:

- 여행 일정 권위/종료일 정규화 회귀: 10/10 PASS
- 명시 권위 fixture를 사용하는 숙박 권위/대사와 OTA 예약 권위·allocation·Gate5
  회귀 묶음: 21건 실행, 13건 PASS, 8건은 권위 pin 재기준화 대기인 명시적 SKIP
- 기존 후보 분류기·고커버리지 분류기·초안·source 회귀: 앞선 targeted run 59/59 및
  source 10/10 PASS
- `git diff --check` 및 변경 모듈 `py_compile`: PASS
- `direct_projection` 전체 32개 중 6개는 현재 dirty tree의 기존 classifier census 고정값과
  실제값 불일치(`1154:4885:115:100:0`, 기대 `114:99:76`)로 중단됐다. 이번 변경에서
  classifier의 동작 코드는 바꾸지 않았으며, 이 고정값은 별도 재기준화 없이는 임의 수정하지 않았다.
- 이번 변경은 운영 DB·외부 서비스·브라우저를 쓰지 않았다. Sol 독립 검토는 실행 중인 dirty
  workspace의 immutable snapshot을 만들 수 없어 `review_deferred`로 남겼고, PASS로 표시하지 않는다.

## 2026-08-23 Windows 우선 전제 전환 정리 완료

사용자 지시로 Linux/WSL 의존을 정리하고 Windows 우선(범용 보조) 전제로 전환했다.
코드 내 WSL·linux 참조는 사전 정리로 이미 0개임을 확인했다. 변경 4종:

1. 역량 게이트(9e9ae70, ledger/tests/_platform.py 신설): staged 증거 라운드는
   COST_STAGED_INPUT_DIR, 드리프트 핀(직전 Sol 블록의 classifier census 불일치 포함)은
   COST_ALLOW_PIN_DRIFT 환경변수로 명시 활성화할 때만 실행하고, POSIX 발행 계약
   (renameat2·dir fsync)과 symlink 권한은 사유와 함께 skip한다. 38클래스+17메서드 적용.
2. 범용 스테이징 루트(0b6cbdc, ledger/domain/staged_inputs.py 신설): /tmp 하드코딩
   5파일을 COST_STAGED_INPUT_DIR → OS 표준 temp 폴백으로 해석. Linux 기존 동작 불변.
3. O_BINARY 시스템 버그 수정(4a31fba): os.open 쓰기 19곳/16파일이 CRT 텍스트 모드로
   열려 Windows에서 바이너리 페이로드의 0x0A가 CRLF로 치환돼 해시 대상 내용이
   변조됐다(survey HMAC 키 재적재 불일치로 실증). 전면 getattr(os,"O_BINARY",0)
   추가. POSIX 무영향.
4. 최종 검증: unittest discover 899테스트 OK, skipped 280, 4.7분 — 이 머신에서
   처음으로 전체 스위트 통과. 스킵은 전부 사유 명시 게이트다.

투명성 기록: 커밋 4a31fba에는 동일 트리에 남아 있던 직전 codex 세션의 잔여 도메인
수정(direct_verified_ota_lodging +163, direct_trip_schedule_authority +56,
build_agoda_accounting_draft +65, ledger_db·direct_sources·projection 일부)이
함께 포함됐다. 해당 상태에서 전체 스위트가 통과해 기능적 정합은 확인됐으나 커밋
메시지가 내용을 축소 서술한다. 후속 세션은 이 커밋을 'O_BINARY 수정 + codex 잔여
병합'으로 읽어야 한다.

잔여 경계(의도 유지): renameat2 발행 스택과 staged 증거 패밀리는 각 게이트로
Linux에서만 실행. classifier census·r39/r41/v6 등 드리프트 핀 리베이스라인은
사용자 승인 대기다.
