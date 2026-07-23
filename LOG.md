# LOG — cost (비용처리 엔진)

세션 핸드오프 로그. 최신 블록이 맨 아래. 새 에이전트는 **맨 아래 블록부터** 읽으세요.

---

## 2026-07-23 세션 핸드오프

### 이번 세션에 한 일
- **다중모델 교차진단 → 엔진 구조수정 6건** (→ **PR #5**, 브랜치 `claude/expense-processing-automation-ivhg7j`, base `main`, **미머지 draft**):
  - Gemini(`gemini-3.6-flash`) + GLM(`glm-4.7-flash`)이 전 리포를 독립 진단 → fable 모델이 코드 대조로 수용/반박(수용 10·반박 4·부분 1, 신규 3건 발견) → 상위 6건 반영. Node VM 스텁 15케이스 통과.
  - `apps-script/Code.gs`: ① `runReconciliation` 중복억제에 **소진추적**(`findDupMatch`) 도입 — 동일카드·동일금액 반복결제(구독료 등)가 첫 건 이후 전부 "이미 기록됨"으로 오판돼 누락되던 구멍 차단. 기타비용 버킷은 날짜/OTA 근거 없는 매칭 불인정. ② `matchEmail` 통화체크·OTA소스게이트·오차허용 1%→±2원·날짜미상 후순위·`_used` 소진 시점 이동. ③ `recordsMatch` OTA추정 티어 날짜 필수화. ④ 항공권(AIR) 여행탭 못 찾으면 기타비용 흡수 대신 **HOLD**. ⑤ `loadEmailIndex`에 currency 로드.
  - `apps-script/GmailIngest.gs`: `endate()` 축약 월명(Jun/Jul) 지원, 이메일 수집 배치 쓰기(쓰기→라벨 순서 유지).
  - `apps-script/WeeklyReport.gs`: `sumLedgerExpenses_()`가 폐기된 `_C` 탭만 합산해 전 투어 지출 0으로 나오던 버그 → 실탭 지출섹션 합산으로 교체.
  - 문서: `docs/design.md`·`docs/setup.md`의 `_C` 서술 → 실탭 직접 전기로 갱신. `docs/비용분류_지시사항_원장.md` §E에 이번 교차검토 이력.
- **모델 정책**: `CLAUDE.md`를 "모델 역할 분담"(Opus 지휘·검증 + Gemini 3.6-flash 수행, GLM 명시 호출 시만, 래퍼 sonnet 최저 effort)으로 갱신. `tools/gemini.mjs` 기본모델 `gemini-3.1-pro-preview`→`gemini-3.6-flash` 고정.
- 위 항목 커밋 중 `main`(c825e07)이 다른 세션 커밋으로 앞서가 CLAUDE.md 충돌 → 머지 커밋으로 해소(내 정책 유지 + 래퍼-effort 세칙 흡수). PR #5 = clean.

### 배포/런타임 상태
- **실행 = Google Apps Script**(script.google.com), 계정 `kkokkohero6@gmail.com` 단일. **git↔실행 자동연결 없음** — PR 머지해도 Apps Script 편집기에 Code.gs/GmailIngest.gs/WeeklyReport.gs를 **사람이 다시 붙여넣어야** 반영.
- 트리거(사람이 Apps Script에서 설정): `ingestPaymentEmails` 6시간·주간리포트 월요일. 대상 시트 5개 ID = STATUS.md 표. 진행장부 `1fhqN…`.
- 브랜치: `main`(기본, c825e07) / 작업·PR = `claude/expense-processing-automation-ivhg7j`(6922146).

### 미결·다음 할 일
1. **PR #5 머지** → 머지 후 Apps Script에 3개 .gs 재붙여넣기(실행 반영).
2. STATUS.md "다음 세션 할 일" 유효: Gmail 필터에 **navercorp.com·kakaocorp.com** 추가(네이버페이·카카오페이 라벨 누락), 설치·검증(복사본에서), 미완 파서 샘플 수급.
3. 낡은 원격 브랜치 정리(아래 §브랜치) — 사람이 UI에서.

### 함정·비자명 사실
- **Apps Script는 git과 자동 동기화 안 됨** — 붙여넣기 수동.
- **main 직접 push·브랜치 삭제가 org 정책으로 403 차단**(이번에 `git push origin --delete` 실측 403). 브랜치 정리·기본브랜치 변경은 **GitHub UI**에서.
- `flushTarget` 삽입 위치는 `=SUM()` 자동확장을 위한 **의도적 설계**(오프바이원 아님) — 건드리지 말 것.
- OTA 추정매칭(60일)은 사업상 유지하되 날짜 필수(이번 수정).

### 브랜치 정리 (모두 미병합 고유커밋 있음 → 자동삭제 안 함, 사람이 검토 후)
`main` 대비 고유커밋: `claude/expense-processing-automation-ivhg7j` 3(=PR #5, **유지**) · `claude/code-review-branch-cleanup-lky6nc` 101 · `claude/r2-engine-hardening` 12 · `claude/r3-weekly-report` 13 · `claude/leader-payment-sync` 1. 뒤 4개는 옛 세션 잔재로 보이나 고유커밋이 있어 확인 필요. 프로덕션(main)에 이미 반영됐는지 확인 후:
```
git push origin --delete claude/r2-engine-hardening claude/r3-weekly-report claude/leader-payment-sync claude/code-review-branch-cleanup-lky6nc
```
(클라우드 세션에선 403 가능 → GitHub UI Branches에서 삭제.)

### 부트스트랩 (git에 없어 새 컨테이너에서 다시 세울 것)
- `.env`(리포 루트, gitignore): `GEMINI_API_KEY`, `GLM_API_KEY`.
- 클라우드 세션 아웃바운드: 명령 앞 `NODE_USE_ENV_PROXY=1`.
- Node(브리지 스크립트 실행용). Apps Script 접근은 브라우저 로그인(kkokkohero6).
