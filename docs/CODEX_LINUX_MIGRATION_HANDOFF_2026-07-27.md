# Codex Linux migration handoff — 2026-07-27

## 0. Freeze point

- This handoff supersedes the missing `docs/CODEX_DESKTOP_MIGRATION_HANDOFF_2026-07-26.md`.
- All Codex subagents and cost-processing workers were stopped before this handoff.
- No cost-processing job was running at the freeze point.
- Existing Goal: none.
- Migration branch: `codex/linux-migration-2026-07-27`.
- Local base before the migration commit: `3bd85a48cda70b6e4d4bdd226c0b971fd794a18d`.
- Observed `origin/main`: `370052e9e1c82eb92b648aab37ecc16857fdcaa3`.
- The local base was 18 commits behind `origin/main`. Do not reset, force-push, or overwrite the working state. Rebase/merge only after inspecting conflicts on Linux.

## 1. Immutable business rules

1. Every card event is immutable and must be retained. Never delete, discard, or net away a purchase, cancellation, or partial refund.
2. A cancellation/refund is a separate event. Link it to an original event only with transaction-level evidence.
3. OTA matching is N:M. Automatic posting is allowed only when the card-event/OTA-email intersection is unique; collisions remain HOLD.
4. Reservation number is a grouping/reference key, not the card-event primary key. Split payments and partial refunds under one reservation remain separate events.
5. Exclude service dates before 2025 from the current OTA reconciliation scope.
6. Keep Agoda priority. For Agoda browser work, use Edge, and persist one verified reservation to SQLite before opening the next.
7. Color is presentation only. Processing state is determined by `card_event_id` and the existence of ledger/posting records.
8. Q2 output must retain all expenses and all income, include the Q2 miscellaneous-expense sheet, periods, reservation numbers, and passenger names for air tickets.
9. Final workbook filenames must be versioned. Do not overwrite an earlier output with a different result under the same name.
10. Do not treat the 4,280,000 KRW `전용진 카드이용대금` transfer as personnel expense.

## 2. Verified completed work

### Card-event engine and cancellation preservation

- `apps-script/Code.gs` contains the redesign for immutable card events, explicit cancellation/refund posting, `card_event_id`-based state, HOLD preservation, and OTA `EXACT/PROBABLE/HOLD` handling.
- Earlier recorded verification: `node tests/test_ota_matching.js` passed 11 scenarios and Apps Script syntax checks passed.
- Recorded deployment: version `@2`, deployment ID
  `AKfycbzK2BQouRaSzmMoj9t59G2r9U3BjKd0XV8zd4ikXMTaof7UF6UR35xQN7hgPkNfLStt`.
- Apps Script project ID:
  `1myWv5UqHslTv13K_bDll7tbvxROpVFvwFUdWddSSqNn0-6iQDk9fROCX`.

### Hana Q1/Q2 issuer-file revalidation

- Five issuer XLS files cover 2026-01-01 through 2026-06-30.
- Input events: 825; normal 821; cancellation 4; billed net 74,540,876 KRW.
- Independent revalidation: 819 already existed, 2 were genuinely new, 3 were central-snapshot conflicts, and 1 blank-approval cancellation remained review-only.
- The two genuine cancellations were merged:
  - `HAN-9111`, 2026-06-24, LOTTE ARAI RESORT, -52,954 KRW.
  - `HAN-9112`, 2026-01-11, HI-YES HOTEL HUA LIAN, -7,021 KRW.
- The earlier report of 645 new rows was false. It compared issuer rows with downstream `classified_v14.csv` instead of the complete `master_ledger` plus RAW snapshots. None of those 645 rows was merged.
- The three amount conflicts are existing `5월_유럽` rental events identified by exact approval numbers:
  - AVIS, approval `107633`, final issuer billed amount 393,383 KRW.
  - SICILY BY CAR, approval `407242`, final issuer billed amount 227,861 KRW.
  - Hertz, approval `305072`, final issuer billed amount 423,524 KRW.
- One cancellation remains HOLD: 2026-02-26, card 6741, KUROSHIONOMORIMANGROVEPAR, -56,666 KRW, blank approval number. Do not infer the original approval number.
- Recorded regression result after the two-row merge:
  `py -3 -m pytest test_cardindex.py test_dedup_card_events.py -q` → 7 passed, 10 subtests.

### Personnel and non-OTA unassigned audit

- Personnel rows are already present in `manual_v4.csv` and `classified_v14.csv`:
  three 450,000 KRW driving-allowance rows for 전용진/염장규, total 1,350,000 KRW.
- The 4,280,000 KRW card-payment transfer was excluded from personnel validation.
- Surface `여행_미배정`: 19 rows / 2,734,540 KRW.
- Ten are duplicate representations of events already linked to another bucket.
- Actual unassigned after existing-link resolution: 9 rows.
- Seven are OTA rows (1,281,717 KRW); two are non-OTA:
  - `KBD-0403`, 모두의주차장, 2,400 KRW.
  - `CORP-2005`, 나이스정보통신 approval cancellation, 0 KRW.

### Latest generated intermediate workbook

- `ledger/data/숲길여행_2분기_비용분류_AI_v76.xlsx` was regenerated after the two Hana additions.
- Recorded result: 36 sheets, 1,835 detail rows, 251,693 bytes.
- `HAN-9112` was present at `취소환불!L45`; `HAN-9111` at `취소환불!L69`.
- Recorded formula-error scan: zero errors.
- This is an intermediate workbook, not the final complete Q2 manual-ledger delivery.

## 3. OTA reconciliation: exact current state

The last Codex audit was a full local inventory count, not a provider-site transaction-by-transaction investigation.

| Provider | Card events | Existing verified | Locally mergeable | Remaining without verified link |
|---|---:|---:|---:|---:|
| Agoda | 212 | 6 | 0 | 206 |
| Trip.com | 240 | 47 | 2 | 191 |
| Booking.com | 33 | 0 | 5 | 28 |
| Mytrip | 34 | 15 | 0 | 19 |
| Travelrover | 27 | 0 | 0 | 27 |
| **Total** | **546** | **68** | **7** | **471** |

- The seven locally verified links were not merged into the central link file at freeze time.
- Agoda SQLite had schema only and zero persisted booking/evidence rows. Earlier browser work was not durably saved.
- Remaining count means “not yet verified”; it does not mean every row needs user judgment.

### Explicit OTA HOLD records (9)

Trip partial refunds:

1. `TRIP-0102`, -310,100 KRW, booking `1400823779576326`, PNR `EL679H`,
   period `0418_0423`, linked original `TRIP-0101`.
2. `TRIP-0107`, -307,139 KRW, order `1112-901-710`, PNR `YD642V`,
   period `0417_0423`, linked original `TRIP-0106`.
3. `TRIP-0113`, -378,300 KRW, booking `1400825183632390`, PNR `BTHRQH`,
   period `0417_0429`, linked original `TRIP-0112`.

These require transaction-level refund evidence; do not remove or net them.

Booking.com:

4. `KBO-2645`, 847,256 KRW / JPY 87,560, ledger reservation `6475326931`;
   no matching local mail record.
5. `KBO-2646`, 278,865 KRW / JPY 28,820, ledger reservation `6635102370`;
   no matching local mail record.
6. `KBO-2648`, 150,970 KRW / JPY 15,510; no reservation number and multiple identical charges.
7. `KBO-2649`, 150,970 KRW / JPY 15,510; same collision.
8. `KBO-2652`, 150,970 KRW / JPY 15,510, ledger reservation `6851343288`;
   ledger reference exists but local mail evidence is absent and identical charges collide.
9. `CORP-2007`, 1,181,775 KRW, approval `816380`, currently `0424_알펜루트`;
   no reservation or matching mail. “Amsterdam” is a Booking billing descriptor, not property evidence.

## 4. Work still required

1. Merge the seven locally verified OTA links without overwriting any existing link; rerun the link guards.
2. Reconcile Trip.com 191, Booking.com 28, Mytrip 19, and Travelrover 27 remaining rows using mail body, reservation/PNR, dates, passengers, and card-event evidence.
3. Rebuild Agoda work from zero durable checkpoints: Edge multi-session, one booking verification → SQLite commit → read-back check → next booking.
4. Report every new HOLD immediately. A worker result with any HOLD must not be summarized as simply “completed.”
5. Resolve the Hana three final-billed-amount snapshots without creating duplicate events. Keep the blank-approval -56,666 KRW cancellation on HOLD.
6. Recalculate unassigned rows after OTA links; preserve and classify the two non-OTA rows explicitly.
7. Regenerate the complete Q2 manual-ledger workbook only after unresolved rows have been reviewed:
   all income + all expenses, Q2 miscellaneous costs, periods, booking numbers, air passenger names, compact card labels, corrected column widths, and a new versioned filename.
8. Validate formulas and totals with LibreOffice/openpyxl and compare every source sheet count/amount to the output.
9. Update the Google master ledger and upload a new Google spreadsheet only after the final workbook passes validation.
10. Update `LOG.md` and standing documentation with the final counts, then merge the Linux branch safely with current `origin/main`.

## 5. Linux first-run order

```bash
git clone https://github.com/6Soo/cost.git
cd cost
git fetch --all --prune
git switch codex/linux-migration-2026-07-27
git status --short --branch
```

Before changing anything, compare the branch with current `origin/main`:

```bash
git log --oneline --decorate --graph --max-count=40 --all
git diff --stat origin/main...HEAD
```

Install/runtime checks:

```bash
python3 --version
node --version
libreoffice --version
python3 -m pip install openpyxl pytest
```

Run focused tests from the repository root:

```bash
python3 -m pytest ledger/test_cardindex.py ledger/test_dedup_card_events.py ledger/test_rev_periods.py -q
node tests/test_ota_matching.js
node tools/audit-ota-reconciliation.mjs
```

Freeze-point validation results:

- `ledger/` CWD:
  `py -3 -m pytest test_cardindex.py test_dedup_card_events.py test_rev_periods.py -q`
  → **19 passed, 10 subtests passed**.
- Repository-root CWD: `node tests/test_ota_matching.js` → **11 passed**.
- Repository-root CWD: `node tools/audit-ota-reconciliation.mjs` → completed successfully and reproduced
  546 OTA events, 68 existing links, 7 mergeable links, 9 HOLD records, and zero persisted Agoda bookings.
- `py -3 -m pytest ledger/tests/test_domain_ledger.py -q -x` → **1 failed, 2 passed**.
  Failure is a stale fixture expectation: the test expects 1,705 `payment_transactions`, while the current
  `classified_v14.csv` imports 1,835. Update hard-coded expected counts only after confirming all current rows;
  do not alter production data to satisfy the old fixture.

Pipeline working directories remain important:

```bash
cd ledger
python3 build_v13_trip.py
python3 fix_v14.py
python3 patch_v14.py
cd data
python3 build_workbook_v76.py
```

Audit scripts for hard-coded Windows paths (`D:\...`) and replace them with repository-relative `pathlib.Path`/`__dirname` paths before a Linux production run. Preserve `/tmp` semantics or replace them with `tempfile`.

## 6. Local-only material requiring secure transfer

Do **not** commit these to Git:

- Repository-root `.env` containing API keys.
- Google OAuth token/session files under the user profile.
- `ledger/data/ota_mail_index.json` (raw Gmail-derived evidence; may contain personal data and booking PINs).
- `ledger/data/ota_checkpoints_agoda.db` until it contains vetted durable checkpoints.
- `outputs/` (about 173 MB at freeze time; intermediate workbooks, previews, raw audit details, and possible personal data).
- Original issuer XLS files under `D:\DownLoad`.

Copy these separately using an encrypted channel, preserve timestamps where possible, and record SHA-256 hashes before and after transfer. The Git branch contains code, central tracked ledger changes, sanitized supporting data, tests, and this handoff; it does not substitute for secure evidence transfer.

## 7. External connections

- GitHub repository: `6Soo/cost`; Windows `gh` was authenticated as `6Soo`.
- Google owner/work account: `kkokkohero6@gmail.com`.
- Google master ledger file ID:
  `1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU`.
- Google Workspace MCP used `@aaronsb/google-workspace-mcp`; OAuth must be repeated or securely migrated on Linux.
- Git does not contain OAuth tokens or `.env`.

## 8. Stop/continue contract

- Nothing continues automatically after this handoff.
- On Linux, read `AGENTS.md`, then this handoff, the bottom of `LOG.md`, `CLAUDE.md`, and
  `docs/비용분류_지시사항_원장.md` before taking action.
- The first execution task is the seven-link guarded merge, followed by provider-specific OTA reconciliation.
- Do not generate or upload the final workbook while the 471 OTA rows are still unverified.

## 9. 전체 채팅 세션 인계 — 사용자 목표와 확정 판단

이 절은 새 Linux 에이전트가 과거 채팅을 보지 못해도 같은 결론과 작업 우선순위를 유지하도록 작성했다.
민감한 PIN, OAuth 비밀값, API 키는 의도적으로 재기록하지 않았다. 해당 값이 필요하면 Git이 아닌 안전한
인증 절차로 다시 획득한다.

### 9.1 최초 목표와 범위

- 대상 저장소는 `6Soo/cost`, 프로젝트명은 cost/ledger다.
- 사용자는 비용처리 엔진 자체의 검토와 권장 구조로의 재설계, 코드 변경, 자동 배포를 요청했다.
- 엔진의 최우선 원칙은 다음 두 가지였다.
  1. OTA 메일과 카드 내역의 교집합이 완벽할 때 가장 확실한 데이터로 기록한다.
  2. 카드 결제 내역은 절대로 삭제하거나 버리지 않고 모두 기록한다.
- 이후 작업 범위는 Apps Script 자동전기 엔진, Python 비용분류 파이프라인, OTA 메일 전수대사,
  Google 원장 갱신, Q2 수기장부형 워크북과 완전한 매출확인자료 생성까지 확장됐다.

### 9.2 사용자가 직접 지적한 엔진 결함

- `apps-script/Code.gs`의 취소 처리가 RAW 행 색만 바꾸고 음수 이벤트와 감사 기록을 남기지 않았다.
- 행에 색이 있다는 이유만으로 처리 완료로 간주했다. 색은 표시용이어야 하고, 처리는 `card_event_id`와
  전기 레코드 존재 여부로 판단해야 한다.
- 동일 가맹점·업종의 보류 거래를 한 건으로 합쳐 개별 카드 거래가 유실됐다.
- 같은 브랜드·금액의 양수 거래가 없다는 이유로 취소를 버리면 안 된다. 취소에는 부분환불이 존재한다.
- 예약번호를 거래 PK로 사용하면 분할결제와 부분환불을 구분하지 못한다. 예약번호는 그룹 키이고
  거래 이벤트 PK는 별도여야 한다.
- 동일 금액은 중복의 충분조건이 아니다. 카드번호·승인번호·거래유형·원거래 연결을 우선한다.
- 사용자 확정에 따라 LOONG AGE 숙박비 421,101원 두 건의 현재 여행 배정은 맞다.
- 전용진 카드대금 이체는 이중계상이 아니라 회사 카드대금 정산일 수 있으므로, 단순히 비용에서 빼거나
  인건비로 넣어서는 안 된다. 특히 4,280,000원 이체는 인건비 계산에서 제외한다.

### 9.3 OTA·기간·예약번호 규칙

- 예약번호가 있는 숙박 OTA 거래는 가능한 한 메일/사이트에서 체크인·체크아웃 기간을 채운다.
- 항공 편도는 출발일 하나를 기간으로 기록한다.
- 항공 왕복은 출발일과 귀국일을 `MMDD_MMDD`로 기록한다.
- 렌터카도 인수일과 반납일을 기간으로 기록한다. 한 날짜만 확인된 불완전 값은 추정해서 채우지 않는다.
- 여행자보험도 메일에 여행기간이 있으면 기간을 기록한다.
- 항공권은 내용 열에 탑승객 이름을 병기한다.
- Agoda/Trip.com/Booking.com의 청구 상호는 실제 호텔 위치가 아니라 결제대행 법인·청구지일 수 있다.
  예: `Amsterdam`, `Tokyo` 같은 문자열만으로 여행지를 확정하지 않는다.
- OTA 메일과 카드가 일치해도 한 예약에 카드 거래가 여러 건일 수 있으므로 건수 보존이 우선이다.
- 사용자가 직접 제공한 OTA 상세는 카드·메일과 대조할 강한 근거지만, 금액·기간·예약번호가 다른 예약으로
  섞이지 않도록 거래 단위로 저장한다.

### 9.4 사용자 제공 Agoda 사실

- 예약 `1696942614`: SHONAI HOTEL SUIDEN TERRASSE, 2026-06-25 체크인,
  2026-06-26 체크아웃, JPY 24,548, MasterCard 끝번호 8835.
- Plaza Hotel Mutsu 관련 사용자가 제공한 예약:
  - `1716795279`: 2026-04-17~04-19, JPY 27,152.
  - `1706671692`: 2026-04-17~04-19, JPY 34,370.
  - `1718382019`: 2026-04-18~04-19, JPY 6,501.
  - `1718165811`: 2026-04-17~04-18, JPY 6,183.
  - `1718165346`: 2026-04-18~04-19, JPY 6,773.
- 같은 호텔의 2026-04-17~04-18, JPY 21,030 예약 상세도 제공됐지만 해당 메시지에는 예약번호가
  포함되지 않았다. 다른 예약번호를 추정해서 연결하면 안 된다.
- 사용자는 Agoda 홈페이지의 검색 UX가 매우 불편하다고 반복해서 설명했다. Agoda는 단일 창에서 오래
  탐색하지 말고, Edge 다중 세션을 사용하되 예약 한 건을 확인할 때마다 SQLite에 저장하고 read-back
  검증 후 다음 건으로 넘어가야 한다.
- 사이트 표시통화를 원화로 바꿔 재조회해 보라는 지시 후 다시 엔화로 복원하라고 했다. 최종 사이트
  표시통화 선호는 엔화다.
- Agoda 고객센터 자동응답이 아니라 상담원 연결/메시지 남기기 경로를 사용해 전산상 금액·예약 조회
  불일치를 문의하라는 지시가 있었다. 상담 완료를 증명하는 영속 기록은 현재 저장소에 없다.

### 9.5 사용자 제공 Trip.com·기타 OTA 사실

- Trip.com 예약 `1400823716285910`: Mercure Urabandai Resort & Spa,
  2026-07-02~07-03, 온라인 결제 1,454,306원, 현장 JPY 2,100.
- Trip.com 예약 `1400827051075866`: Kamenoi Hotel Tazawako,
  2026-07-05~07-07, 온라인 결제 1,307,772원, 현장 JPY 1,800.
- 별도 Trip.com 예약 `1400827051083658`: 같은 호텔·같은 기간, 표시금액 887,640원.
  번호가 다르므로 같은 예약으로 병합하지 않는다.
- 항공 예약 `1400826610904891`: 서울–고마쓰 왕복, 2026-08-01~08-05,
  1,293,600원, 탑승객 `JEONG IM OH + 1`.
- 니가타 왕복: 2026-06-20~06-25, 대한항공, PNR `BMSEGA`,
  승객 KIM HEESOON·CHA SEORIN. 제공된 전자항공권 번호는 개인 식별성 때문에 이 인계서에 반복하지 않는다.
- 예약 `1400826934962683`: 서울–삿포로 왕복, 2026-06-16~06-21,
  1,085,000원, `JISOOK KIM + 1`, 카카오페이 4,000원 할인.
- 퇴사자 불변 시트에서 사용자가 제공한 기준 행:
  결제일 4/2, 여행기간 10/10~13, 도쿠시마, 4명, Trip.com, 참고금액 1,248,400원,
  카드 국민2, 탑승객 이인선·이주영·백태성·전형구.
- 퇴사자 시트 URL의 파일 ID는 `1DJpNY1MRG2JNxTWpdbk4Nn4zb51YDyBgtNTy6hsG7u4`.
  이 시트는 불변이며 결제일·탑승날짜·도착지·OTA·탑승객은 신뢰한다. 금액은 대체로 맞지만 ANA 등
  해외원화결제는 부정확할 수 있고 보통 2% 이내 오차를 허용하는 후보 근거일 뿐 최종 카드금액을
  덮어쓰지 않는다.
- Mytrip은 메일에 정확한 정보가 없을 수 있어 PNR·항공사·탑승객·여행기간을 결합해야 한다.
- Travelrover 66,710원은 2026-04-13~04-16 여행자보험 메일과 연결된 것으로 과거 확인됐다.

### 9.6 사용자가 직접 지정한 수기·특수 거래

- 2026-07-16 `모인_주식회사`, 3,472,049원, 오제산장 숙박비:
  `0630_오제` 탭, 항목 `오제산장`, 내용 `숙박`, 증빙유형 `이체`.
- 이 거래는 `MAN-OZE-LODGE-3472049`로 분류자료에 반영한 기록이 있다.
- 인건비는 염장규·전용진 등 이름이 있는 운전수당을 채운다. 현재 확인된 것은 450,000원 3건,
  합계 1,350,000원이다.
- `2026-02-28` 및 `2026-03-12` Trip.com 고마가네 숙박 여러 건은 기간 `0414_0415`로 연결됐고,
  동일 62,496원 두 건도 서로 다른 승인 이벤트로 보존해야 한다.

### 9.7 워크북·수기장부 출력 요구

- 수기장부형 결과는 지출만이 아니라 수입까지 포함한 완전한 장부여야 한다.
- Q2 전체 자료에는 `2분기_기타비용` 탭을 반드시 포함한다. 이 탭이 반복 누락돼 사용자가 여러 차례
  문제를 제기했다.
- 하나카드·기업카드 항목명의 과도한 공백을 한 칸으로 줄이고, 불필요한 도시·날짜 꼬리표를 제거한다.
- 내용 열이 과도하게 넓지 않도록 기존 파이프라인의 열 너비 규칙을 복원한다.
- 원본 수기장부의 수입·지출 표 구조, 병합셀, 제목·열 배치와 시각적 형태를 유지한다.
- 내용이 바뀐 결과물은 반드시 새 버전 파일명으로 생성한다. 같은 이름으로 덮어써 버전 비교를
  불가능하게 만들지 않는다.
- 중간 산출물에서 기간과 예약번호가 대량으로 비어 있었던 이유는 최신 OTA 링크가 중앙 분류자료에
  병합되지 않았고, 일부 에이전트 산출물이 과거 통합본을 입력으로 사용했기 때문이다.
- `0424_알펜루트`, `0501_부산`, `5월_유럽` 3개 탭만 뽑은 중간 파일은 로컬
  `outputs/20260727_three_tabs_codex/`에 있다. 최종본이 아니다.
- 과거 “사본” 결과가 원본에서 LOONG AGE, 취소거래, APA HOTEL 반복 거래, 수입 및 기타비용을 누락한
  일이 있었다. 사본/산출물을 권위소스로 삼지 말고 카드 원본·최신 Google 원장·확정 OTA 증거로
  재검산한다.

### 9.8 사용자 보고 방식과 작업 운영 선호

- 추론과 환각 없이 실제 프로세스·파일·DB·Git 상태를 확인한 뒤 보고한다.
- “진행 중”이라고 말하려면 실행 프로세스 또는 갱신 중인 체크포인트가 실제로 있어야 한다.
- 장시간 표시되는 UI 작업카드의 경과시간을 실제 계산시간으로 오해하지 않는다.
- HOLD나 사용자 판단 후보가 한 건이라도 생기면 건수만 요약하지 말고 거래별로 즉시 보고한다.
- 사용자가 판단할 후보는 한 번에 5건씩 보여 주고, 한 건 이상 해결될 때마다 새로운 5건으로 갱신한다.
  다만 OTA 사이트에서 에이전트가 직접 확인할 수 있는 것은 사용자에게 대신 대사해 달라고 요구하지 않는다.
- 사용자가 명시하지 않아도 HOLD 보고를 계속한다. 자동 해결 가능한 항목을 반복해서 사용자에게 묻지 않는다.
- 병렬 작업은 중앙 원장 동시 쓰기를 금지하고, 각 작업자가 독립 체크포인트를 만든 뒤 단일 병합자가
  순차 병합한다.
- 작업 종료 시 “감사 완료”와 “전수 대사 완료”를 구분한다. 현재 OTA 감사는 로컬 상태 집계만 완료된 것이다.
- 브라우저 작업은 인앱 브라우저가 아니라 Edge를 사용하라는 지시가 반복됐다.

### 9.9 썬더킴 기여와 정규화 구조 논의

- 사용자는 개발자 썬더킴이 제안·기여한 브랜치와 PR을 검증하고, 타당한 아이디어를 일부 수용해 구조를
  개선하라고 했다.
- 핵심 논점은 한 결제 행에 결제·여행·승객·기간·예약·환불·증빙·분류가 모두 뭉쳐 있어 규칙 충돌이
  반복된다는 것이었다.
- 합의된 권장 구조:
  - `card_event`: 카드 원본 이벤트. 이벤트 ID, 카드, 승인번호, 거래일, 청구액, 외화액, 상태.
  - `booking`: OTA 예약. 공급자, 예약번호, PNR/참조코드.
  - `service_period`: 숙박 체크인/아웃, 항공 출발/귀국, 렌터카 인수/반납.
  - `traveler`: 예약별 탑승객/투숙객.
  - `evidence`: Gmail 메시지 ID, 영수증, 사이트 확인, 수기 근거.
  - `event_booking_link`: 카드 이벤트와 예약의 N:M 연결, 신뢰도, 근거, 상태.
  - `event_relation`: 원결제·취소·부분환불 관계.
  - `posting`: 어느 여행/계정/증빙유형으로 전기됐는지 기록.
- 예약번호는 `booking`의 자연키 후보지만 `card_event` PK가 아니다.
- 기존 코드가 이 구조를 택하지 않았던 이유는 Google Sheets 수기장부와 카드 RAW를 한 행으로 바로
  출력하는 레거시 파이프라인, Apps Script의 단순 행 처리, 기존 열 형식을 유지해야 하는 요구 때문이었다.
  이론이 틀린 것이 아니라 마이그레이션·호환비용 때문에 지연된 것이다.
- 저장소의 `ledger/domain/schema.sql`, `ledger/domain/ledger_db.py`,
  `ledger/tests/test_domain_ledger.py`는 이 정규화 방향의 시작점이다. 아직 완전한 운영 전환은 아니다.
- 도메인 테스트의 1,705행 고정 기대값이 현재 1,835행과 어긋나는 것은 구조 자체 실패가 아니라
  fixture 최신화가 안 된 상태다. 현재 행의 무손실을 먼저 검증한 뒤 기대값을 갱신한다.

### 9.10 반드시 재검증할 구체적 회귀 사례

- `0424_알펜루트` 원본과 과거 산출 “사본”의 사용자 제공 비교:
  - 원본 총지출 51,924,588원, 사본 49,990,561원, 차이 1,934,027원.
  - 트립닷컴 취소 -87,100원 누락.
  - 트립닷컴 전용진 351,000원 누락.
  - APA HOTEL 571,962원 4건 중 사본에는 1건만 남아 3건/1,715,886원 누락.
  - Booking.com_Kazeya 1,648,573원이 사본에서 1,648,570원으로 임의 조정된 사례.
  이 숫자는 과거 산출물 결함을 설명하는 회귀 기준이며, 사본을 원본보다 우선하지 않는다.
- `5월_유럽` 원본에는 LOONG AGE 숙박비 421,101원 두 건(2026-05-08, 2026-05-11)이 있다.
  사용자는 이 두 건의 현재 배정이 맞다고 확정했다.
- 2026-04-16 / 388,434원 행이 원본의 `항공_전용진`, 기간 `0625`에서 사본의 `숙박`, 기간 공란으로
  바뀐 사례가 있었다. OTA 가맹점명 기반 재분류가 수기 확정 내용과 기간을 덮어쓰지 않는지 테스트한다.
- 2026-06-13 Agoda 3,568,791원은 사용자가 `0625_아키타` 거래라고 확정했다.
  카드 상호만으로 세부 예약을 확정하지 말되 여행 배정은 유지한다.
- `0417_아오모리`에서 과거 누락 보고된 취소/환불:
  - 2026-01-14 트립닷컴(구)_NICE -310,100원.
  - 2026-02-11 마이트립_아오모리 -307,139원.
  - 2026-04-16 트립닷컴_0417_0429 -378,300원.
  - 2026-04-16 트립닷컴_도쿄 -87,100원.
  삭제하지 말고 각각 독립 환불 이벤트로 보존한다.
- 2026-04-23 HIGASHINIHONKOUSOKUDOURO 9,492원도 과거 누락 사례로 보고됐다.
- 네자메호텔 JPY 15,510 동일 결제가 여러 건 존재한다. 동일금액 한 건만 남기는 회귀를 금지한다.
- 고마가네 62,496원 두 건은 승인번호가 달라 모두 정상 카드 이벤트로 보존한다.

### 9.11 산출물·Google 원장·배포의 실제 완료 경계

- 사용자는 최신 수기장부 갱신, 워크북/Q2 파일 출력, Google Drive에 새 스프레드시트 업로드,
  Google 원장 실제 갱신까지 요청했다.
- 여러 중간 워크북은 만들어졌지만, OTA 471건 미확정 상태를 반영한 완전한 최종본은 아직 없다.
- Google Drive 새 스프레드시트 업로드와 최신 원장 최종 반영이 완료됐다는 검증 기록도 없다.
- 중간 산출 경로 예:
  - `outputs/20260727_three_tabs_codex/`
  - `outputs/hana_q1q2_revalidation/`
  - `outputs/codex_reconcile_20260727/`
  - `outputs/codex_card_personnel_20260727/`
  이들은 Git 제외 로컬 자료이며 Linux에 별도 이전해야 한다.
- Apps Script 엔진의 과거 배포는 §2에 기록했지만, 이후 모든 로컬 코드 변경이 다시 배포됐다고
  가정하면 안 된다. Linux에서 로컬/원격 Apps Script 파일 해시를 비교한 뒤 필요할 때만 배포한다.
- 상담원 문의, Gmail 초안, Drive 업로드 같은 외부 상태는 로컬 로그만으로 완료 처리하지 말고
  실제 계정에서 확인한다.

## 10. 전체 채팅 세션 인계 — 주요 실패와 교훈

1. 색상을 처리 상태로 사용해 장부 존재 검증을 건너뛰었다.
2. 취소·환불을 원거래와 상계하거나 양수 원거래를 못 찾았다는 이유로 삭제했다.
3. 동일 가맹점·금액 보류건을 하나로 합쳐 개별 이벤트를 잃었다.
4. 카드 거래와 수기장부/OTA를 한 행에 과도하게 뭉쳐 수정할 때 다른 사실까지 덮어썼다.
5. `classified_v14.csv` 부재를 신규 원장 이벤트로 오판해 하나카드 645건을 신규라고 잘못 보고했다.
   올바른 비교 기준은 `master_ledger` + 카드 RAW + 승인번호다.
6. 에이전트가 체크포인트를 만들었다고 보고했지만 중앙 파일이나 SQLite에 실제 저장되지 않은 일이 있었다.
   파일 크기·mtime·행 수·read-back으로 영속화를 확인해야 한다.
7. OTA 로컬 재고 546건을 집계한 것을 OTA 사이트 전수조사 완료처럼 표현했다.
8. HOLD 9건을 개별 보고하지 않고 “완료” 건수로만 요약했다.
9. 최종 워크북 전에 미배정 사용자 확인을 거치지 않거나, 반대로 자동 추론 가능한 항목을 불필요하게
   사용자에게 반복 질문했다.
10. 중간 워크북에서 수입과 Q2 기타비용 탭을 누락하고, 기간·예약번호·탑승객 규칙을 잃었다.
11. 동일 파일명으로 결과를 덮어써 버전 비교가 불가능해졌다.
12. Windows 작업카드가 오래 떠 있는 것을 실제 백그라운드 작업으로 잘못 설명했다.

각 실패의 방지 규칙은 다음과 같다.

- 중앙 병합 전 `source event count`, `source net amount`, `new/existing/HOLD count`를 동시에 검산한다.
- 자동 병합은 유일한 교집합만 허용한다.
- 취소·환불·원거래의 이벤트 수는 병합 전후 동일해야 한다.
- 체크포인트는 임시파일 작성 → 원자적 rename → read-back → 해시 기록 순으로 저장한다.
- HOLD가 있으면 완료 상태와 별도 채널로 반드시 노출한다.
- 워크북 생성 전에 완전성 체크리스트를 프로그램으로 검사하고, 생성 후 openpyxl/LibreOffice로
  시각·수식·건수·총액을 검증한다.

## 11. 브랜치·PR·외부 시스템 이력

- 저장소: `https://github.com/6Soo/cost.git`.
- 과거 기여 브랜치/PR 기록: `claude/code-review-branch-cleanup-lky6nc`, PR #4.
  로컬 `main`에 관련 변경이 병합된 기록이 있으나 Linux에서 현재 원격 그래프를 다시 확인한다.
- 현재 이전 브랜치: `codex/linux-migration-2026-07-27`.
- 첫 Linux 인계 커밋: `a143cf26a573089af0c7e1f60739592e8f2ef3ab`.
- 첫 인계 당시 로컬 기준은 원격 `main`보다 18커밋 뒤였다. 강제 push나 hard reset을 금지한다.
- Google Workspace 연결은 업무 계정 `kkokkohero6@gmail.com` 소유 자원에 접근해야 한다.
- 과거 OAuth 테스트에서 403 `access_denied`가 발생했고 테스트 사용자/동의화면 설정을 조정한 뒤
  인증을 재시도했다. Linux에서는 연결이 살아 있다고 가정하지 말고 실제 Gmail/Drive 읽기로 확인한다.
- Google 원장 file ID와 Apps Script ID는 §7 및 §2에 기록돼 있다.
- 자동 배포를 요청받았지만, 최종 Linux 이전 시점에 새 변경분의 재배포나 최신 Google 원장 업로드가
  완료됐다고 간주하면 안 된다.

## 12. Linux 에이전트 무프롬프트 재개 절차

새 세션은 사용자에게 배경 설명을 다시 요구하지 않고 아래 순서로 시작한다.

1. `AGENTS.md`와 이 문서를 끝까지 읽는다.
2. `git fetch --all --prune` 후 현재 브랜치 tip, `origin/main`, 이 문서에 기록된 커밋을 비교한다.
   작업트리가 더럽다면 어떤 것도 덮어쓰지 않는다.
3. 활성 Goal이 있는지 확인한다. 이 인계 시점에는 Goal이 없었다. 사용자 명시 없이 새 Goal을 만들지 않는다.
4. Linux 외부 비밀·증거 파일이 별도 이전됐는지 해시로 확인한다. 없으면 Git에 있는 자료로 가능한
   검증만 진행하고, 원문 증거가 필요한 확정은 HOLD로 남긴다.
5. Windows 절대경로를 검색한다:
   `rg -n 'D:\\\\|C:\\\\Users\\\\|DownLoad' ledger tools tests`.
   실행경로를 저장소 상대경로로 이식하되 데이터 의미는 바꾸지 않는다.
6. §5의 테스트를 실행한다. 도메인 테스트 1건의 1,705 고정 기대값은 현재 1,835행과 충돌한다.
   행 수를 먼저 검증한 후 fixture만 고친다.
7. 중앙 파일을 백업하고 로컬 신규 OTA 링크 7건을 가드 병합한다. 기존 링크 overwrite는 0이어야 한다.
8. 공급자별 잔여를 Trip.com → Booking.com → Mytrip/Travelrover 순으로 처리하면서 Agoda는 독립적으로
   Edge 다중 세션에서 SQLite 한 건 단위로 진행한다.
9. 매 병합 후 OTA별 전체/확정/HOLD/미처리 수와 카드 이벤트 총액을 갱신한다.
10. 사용자 판단이 필요한 HOLD는 즉시 5건씩 보고한다. 자동 해결 가능한 건은 계속 처리한다.
11. OTA 대사가 끝난 뒤 실제 미배정을 다시 계산하고 인건비·특수거래·수입·기타비용을 검증한다.
12. 완전한 Q2 수기장부형 워크북을 새 버전명으로 생성하고 수식·시각·건수·금액 검사를 통과시킨다.
13. 사용자가 승인한 최종본만 Google 원장과 새 Google 스프레드시트에 반영한다.
14. 문서와 LOG를 최신화하고, 원격 `main`과의 충돌을 검토한 뒤 일반 push/PR 흐름으로 마무리한다.

## 13. 현재 사용자 판단 대기와 자동 진행 경계

- 명시적 OTA HOLD 9건과 하나카드 승인번호 공란 취소 1건은 증거 보강 전 자동 확정 금지다.
- 하나카드 렌터카 3건은 승인번호로 기존 이벤트가 확인됐으므로 새 이벤트를 만들지 말고 최종 청구액
  스냅숏 갱신안으로 처리한다.
- 비OTA 미배정 2건은 삭제하지 않는다. 모두의주차장 2,400원은 적절한 비용 분류가 필요하고,
  나이스정보통신 0원 승인취소는 감사 이벤트로 보존한다.
- 사용자는 OTA 사이트 조사를 에이전트가 직접 수행하길 원한다. 사용자에게 OTA 대사를 떠넘기지 않는다.
- 최종 워크북 생성 전에 미배정/HOLD 현황을 사용자에게 보고해야 한다.
- 그러나 근거가 충분한 자동 병합은 별도 승인 대기로 멈추지 않는다.

## 14. 인계 완전성 체크

- [x] 실행 중 작업 0건 확인.
- [x] 사용자 확정 불변규칙 기록.
- [x] 사용자 제공 OTA·특수거래 사실 기록.
- [x] 완료·미완료·HOLD 수치 기록.
- [x] 오판과 재발방지 규칙 기록.
- [x] 워크북 출력 형식과 보고 선호 기록.
- [x] 외부 연결과 보안 제외자료 기록.
- [x] Linux 첫 실행 순서 기록.
- [x] Git 브랜치와 기준 커밋 기록.
- [ ] Git 밖의 민감 원문·SQLite·outputs·원본 XLS를 암호화 채널로 Linux에 복사하고 SHA-256 대조.
- [ ] Linux에서 테스트와 원격 브랜치 상태를 재검증.

## 15. 2026-07-29 세션 이동 인계 — v15 확정상태와 Agoda CS 5건

이 절은 §1~14 이후의 실제 변경을 반영한 최신 델타이며, 서로 충돌하는 과거 수치는 이 절과
`LOG.md`의 최신 세션 핸드오프를 우선한다.

### 15.1 Git·정본·감사 상태

- 작업 브랜치는 `codex/resolve-all-pending`이다. 이 인계 갱신 직전 원격과 일치한 tip은
  `61ea7b9638536574d23795ed83d7d570e2f80138`
  (`Complete OTA evidence reconciliation audit`)이다.
- 직전 핵심 커밋은 `be94a0a`(회계/증빙 감사 상태 분리), `1b435e5`(신고 후 OTA 보강),
  `61ea7b9`(잔여 증빙 재검증)이다.
- 승인 정본은 `ledger/data/classified_v15.csv`다:
  **1,834행 / 319,903,284원 / SHA-256
  `65ff2b7e34d820f8bc814ab92876bdbfc55f63dd1f87b009887f4fbff8e080e0`**.
- 최신 결정권위 보고서는 로컬 Git 제외 경로
  `outputs/20260728_decision_authoritative_review_v15/`이다. OTA 545건 중 회계분류 540,
  여행 미배정 5건·1,117,929원, 직접연결 확정 20, 개별 순열 충돌 6, 미입증 519다.
  `미입증 519`는 신고·회계 미처리가 아니라 개별 카드행↔예약 직접증거 감사 상태다.
- 실제 조치 큐는 11건·2,189,399원이다. Booking 6건은 회계 귀속이 끝난 동일금액 N:M
  개별 순열 HOLD이고, 아래 Agoda 5건만 여행 귀속을 위한 외부 증거 보강 대상이다.
- Agoda 포털 직접증거는 234건이다. 마지막 추가 예약은 Lotte Arai Resort,
  예약 `1740166023`, 2026-06-23~06-24, 2객실, JPY 22,734, 카드8835이며
  `KBO-0360` 222,217원·`0620_묘코`와 고유 교차했다. 아래 카드4595/4971 5건과는 무관하다.
- 관련 고유 테스트 98건과 P6 멱등 적재·병렬 워크북·회귀 통합 테스트가 통과했다.
  전체 테스트 모음은 중간 실행에서 114건 통과 후 stale fixture 3건을 발견해 중단했고,
  그 3건은 수정 후 개별 통과했다. “전체 suite 완주”로 과장하지 않는다.
- 작업트리의 `CLAUDE.md` 변경은 사용자 소유 변경이다. 이 세션에서도 수정·스테이징하지 않았다.

### 15.2 Agoda 여행 미배정 5건 — 카드 원문

다음 5개 카드 이벤트는 모두 정본에 포함된 숙박비다. 삭제·상계·근사 여행배정을 금지한다.
아고다 전산에서 대응 예약번호, 숙소, 체크인/아웃, 결제 원통화·원금, 결제/환불 상태를 받아야 한다.

| UID | 카드 | 승인/거래일 | 승인번호 | 카드 원천 승인액 | 최종 청구액 | 추가 원천 |
|---|---:|---|---:|---:|---:|---|
| `HAN-3089` | 4595 | 2026-04-20 | `00302021` | 139,761원 | 141,391원 | 최종 매입/결제일 2026-06-05, `AGODA TOKYO`; TOKYO는 청구지이지 숙소가 아님 |
| `CORP-2052` | 4971 | 2026-06-18 | `176061` | 216,927원 | 216,927원 | 카드 원천 외화 JPY 22,737, `AGODA.COM Internet SGP` |
| `HAN-0506` | 4595 | 2026-06-24 | `408304` | 184,212원 | 187,412원 | `AGODA TOKYO` |
| `HAN-0507` | 4595 | 2026-06-24 | `408314` | 92,864원 | 94,477원 | `AGODA TOKYO` |
| `HAN-0508` | 4595 | 2026-06-24 | `408324` | 469,570원 | 477,722원 | `AGODA TOKYO` |

- 카드 승인액과 최종 청구액이 다른 하나카드 4건은 둘 다 상담원에게 제공한다.
- Agoda 계정 이메일은 `kew2000@daum.net`이며 `kew2000@hanmail.net`과 동일 주소다.
  연결된 Gmail 계정은 `kkokkohero6@gmail.com`이고, Agoda 메일 일부는
  `kew2000@daum.net` 수신분이 전달돼 들어온 것이다. 두 계정을 같은 발신 계정으로 오인하지 않는다.
- Gmail 정확 금액/카드 검색, 기존 Agoda 포털 233건 전체 교차, 예약일순 신규 상세조사를
  3회 수행했지만 위 5건의 강한 교집합은 없었다. 카드 원천에는 외화금액이 없거나 사이트 표시통화에
  따라 표시액이 달라져 근사금액으로 예약을 확정할 수 없다.

### 15.3 2026-07-29 Agoda 고객센터 접촉 시도와 정확한 중단점

- 사용자는 위 5건을 Agoda CS에 직접 메시지로 보내 해결하라고 명시했다.
- Agoda 공식 고객센터와 받은 자동응답을 확인한 결과, 신규 이메일은 상담 티켓을 만들지 않으며
  로그인된 웹/앱의 메시징 기능을 사용해야 한다. `customer.service@agoda.com` 자동응답은
  해당 받은편지함이 모니터링되지 않는다고 명시했고, 연결된 Gmail의 보낸편지함에는 회신 가능한
  기존 Agoda 상담 대화가 없었다.
- 실제 메시징 진입을 시도했으나 인앱 Browser는 `No browser is available`, Chrome 확장 연결은
  `Browser is not available: extension`이었다.
- macOS 데스크톱 대체 조작도 `/usr/local/bin/orca computer capabilities --json`에서
  `Orca Computer Use.app was not found`로 지원되지 않았다.
- 따라서 **Agoda 상담 메시지는 아직 전송되지 않았고 티켓/케이스 번호도 없다.**
  모니터링되지 않는 이메일로 보내고 “완료”라고 기록하지 않는다.

### 15.4 다음 세션의 첫 실행 순서

1. `AGENTS.md` → 이 문서 전체 → `LOG.md` 최신 블록 → `CLAUDE.md` →
   `docs/비용분류_지시사항_원장.md` 순서로 읽는다.
2. `git status --short --branch`와 `git log -5 --oneline --decorate`로 이 인계 커밋과
   사용자 소유 `CLAUDE.md` 변경을 확인한다. `CLAUDE.md`를 덮어쓰거나 스테이징하지 않는다.
3. 사용자가 Agoda 로그인된 Edge/Chrome을 열고 Orca Browser/Chrome 연결을 활성화했는지 확인한다.
   로그인·연결이 없으면 정확히 그 한 단계만 요청한다.
4. `https://www.agoda.com/info/contact.html?openChat=true&languageCode=ko`에서 숙박/결제 문의로
   들어가 아래 문안을 전송한다. 예약번호를 요구하는 챗봇이면 “예약번호를 모르는 카드 청구 역추적”과
   계정 이메일을 반복하고 상담원 연결을 요청한다.
5. 전송 후 대화 전문 또는 상담번호, 시각, 상담원 응답, 각 카드건의 예약번호를 영속 저장한다.
   화면만 보고 끝내지 말고 체크포인트에 저장·read-back한다.
6. 답변이 즉시 오지 않으면 5건을 `CS_INQUIRY_SENT`로만 표시하고 여행 귀속은 HOLD로 유지한다.
   실제 예약 상세를 받은 건만 거래 단위 증거로 병합하고 v15 후속 버전을 새 이름으로 만든다.

전송 문안:

> 안녕하세요. Agoda 계정 `kew2000@daum.net`의 2026년 카드 청구 5건이 카드사에서 최종
> 청구되었으나, 예약목록과 보유 이메일에서 대응 예약번호를 식별할 수 없습니다. 아래 각 결제에
> 대응하는 Agoda Booking ID, 숙소명, 체크인/체크아웃, 결제 원통화·원금, 최종 결제/환불 상태를
> 확인하고 영수증 또는 예약확정서를 계정 이메일로 다시 보내 주세요.
>
> 1. 카드 끝 4595 / 승인 2026-04-20 / 승인번호 00302021 /
> 승인 139,761원 / 최종 청구 141,391원(2026-06-05 매입)
> 2. 카드 끝 4971 / 2026-06-18 / 승인번호 176061 /
> JPY 22,737 / 최종 청구 216,927원
> 3. 카드 끝 4595 / 2026-06-24 / 승인번호 408304 /
> 승인 184,212원 / 최종 청구 187,412원
> 4. 카드 끝 4595 / 2026-06-24 / 승인번호 408314 /
> 승인 92,864원 / 최종 청구 94,477원
> 5. 카드 끝 4595 / 2026-06-24 / 승인번호 408324 /
> 승인 469,570원 / 최종 청구 477,722원
>
> 예약번호를 모르는 결제 내역의 역추적 요청입니다. 한 건씩 대응 예약을 확인해 주세요.

## 16. 2026-07-29 최종 세션 이동 동결점

이 절은 §15 이후의 세션 종료 상태를 고정한다. 다음 세션에서는 §1~14의 과거 동결 수치보다
§15와 이 절을 우선하며, 실제 파일·DB·Git 상태가 다르면 덮어쓰지 말고 차이를 먼저 감사한다.

### 16.1 Git과 작업트리

- `git fetch --all --prune` 직후 작업 브랜치 `codex/resolve-all-pending`의 시작 tip은
  `4d3c2c3b11908fb7dbede0143ea7c25580e14661`
  (`Document Agoda CS handoff for session migration`)이었고
  `origin/codex/resolve-all-pending`과 차이 0/0이었다.
- 같은 시점 이 브랜치는 `origin/main`보다 17커밋 앞, 0커밋 뒤였다. 강제 push, hard reset,
  `main` 직접 덮어쓰기는 금지한다.
- 시작 시 유일한 미커밋 파일은 사용자 소유 `CLAUDE.md`의 2026-07-28 에이전트 라우팅 개정이었다.
  §15.1의 “스테이징하지 않음”은 당시 보존 경계였으나, 사용자가 2026-07-29에
  “모든 사항을 손실 없이 정리하고 문서를 최신화하여 Git에 push”하라고 명시해 이번 문서 커밋
  범위에 포함한다. 개정 내용은 전역 라우팅 정책 준수, agy 우선 저추론 폴백, 기존 GLM 우선 지시
  폐지, 보조 브리지 사용법이다.
- 이 동결에서는 `CLAUDE.md`, 이 인계서, `LOG.md`만 문서 변경 대상으로 삼는다.
  정본 CSV, OTA 증거 JSON, SQLite, 코드, 워크북은 변경하지 않는다.

### 16.2 회계·OTA 권위 상태

- 승인 정본은 계속 `ledger/data/classified_v15.csv`:
  **1,834행 / 319,903,284원 / SHA-256
  `65ff2b7e34d820f8bc814ab92876bdbfc55f63dd1f87b009887f4fbff8e080e0`**이다.
- 최신 결정권위 보고서는 Git 제외 로컬 경로
  `outputs/20260728_decision_authoritative_review_v15/`이며, OTA 545건 중 회계분류 540,
  여행 미배정 5건·1,117,929원, 직접연결 확정 20, 개별 순열 충돌 6, 미입증 519다.
- 실제 조치 큐는 11건·2,189,399원이다. Booking 6건은 회계 귀속이 끝난 동일금액 N:M
  순열 감사 HOLD이고, Agoda 5건은 여행 귀속을 위한 CS 역추적 대상이다.
- Agoda CS 메시지는 여전히 전송되지 않았고 상담번호도 없다. 로그인된 Browser/Chrome 연결이
  활성화된 다음 세션에서 §15.4 문안으로 공식 메시징을 사용한다. 모니터링되지 않는 이메일을
  대체 전송으로 사용하지 않는다.
- Google 원장 최종 갱신, 새 Google 스프레드시트 업로드, 최신 로컬 변경의 Apps Script 재배포는
  완료 검증이 없다. 실제 계정/배포 상태를 읽어 확인하기 전 완료로 표시하지 않는다.

### 16.3 Git 밖 자료의 현재 보존 지문

아래 해시는 파일 내용을 Git에 넣지 않고 동일 파일을 안전하게 이전했는지 확인하기 위한 것이다.
PIN·쿠키·비밀번호·OAuth 토큰·메일 원문은 이 문서에 기록하지 않았다.

| 경로 | 크기 | SHA-256 | Git 상태 |
|---|---:|---|---|
| `ledger/data/ota_mail_index.json` | 874,515 bytes | `db258948ff2240b682d579422c4de3edbc5079e6425a8fd7c0a224f57c40cb11` | 제외, 민감 메일 증거 |
| `ledger/data/ota_checkpoints_agoda.db` | 446,464 bytes | `a61f968d3ed619ec1e3bed17a77c886434a94a1b2136c3d1570e07a5514c1939` | 제외, 로컬 체크포인트 |
| `ledger/data/ota_checkpoints_agoda_pages4_5.db` | 147,456 bytes | `fa86dd3a906febb7d18504207c04f8bfe7e4165a01c77064c6caca6f1bf56ef2` | 제외, 로컬 체크포인트 |
| `ledger/data/agoda_direct_browser_evidence_pages4_5.json` | 62,422 bytes | `af0eec40a5765efd1b07263e02573f112b3d59456e1a1df0da650aab31d616f7` | Git 추적, 68건 |

- `ota_checkpoints_agoda_pages4_5.db`는 WAL checkpoint 후 `integrity_check=ok`,
  `ota_booking_current=68`, JSON도 68건이었다.
- 현재 `outputs/`는 70개 파일 / 1,912,884 bytes이며 `.gitignore` 대상이다. 이 수치는 내용
  완전성을 보장하는 해시가 아니므로, 다음 장치로 옮길 때 디렉터리 전체를 암호화 복사하고 별도
  manifest를 생성한다.
- 저장소 루트 `.env`는 이 동결 시점에 없었다. Google OAuth/session 파일은 사용자 프로필 등
  저장소 밖 위치일 수 있으므로 Git 이전과 별개로 확인한다.

### 16.4 다음 세션 재개와 완료 경계

1. `AGENTS.md` → 이 문서 전체 → `LOG.md` 최신 블록 → `CLAUDE.md` →
   `docs/비용분류_지시사항_원장.md`를 읽는다.
2. `git fetch --all --prune`, `git status -sb`, `git log -5 --oneline --decorate`로
   이 동결 커밋과 원격을 대조한다. 로컬 전용 파일은 위 SHA-256으로 확인한다.
3. 실행 중인 작업은 0건이며 자동으로 이어지는 작업도 없다. 새 Goal은 사용자 명시 없이 만들지 않는다.
4. 첫 외부 작업은 로그인된 Agoda 공식 Help Center 메시징으로 §15.2의 5건을 역추적하는 것이다.
   전송/응답을 영속 저장하고 read-back하기 전 상태를 `CS_INQUIRY_SENT` 이상으로 올리지 않는다.
5. 회계 정본은 이미 승인된 v15를 유지한다. CS의 거래 단위 강한 증거가 생긴 경우에만 새 버전으로
   귀속을 바꾸고 회귀 테스트·보고서 재생성을 수행한다.
6. 최종 수기장부/Google 원장/Drive 업로드는 §1의 무손실 규칙, OTA HOLD 공개, 전체 수입·지출·
   기타비용·기간·예약번호·탑승객 검증을 통과한 뒤 사용자 승인으로 진행한다.
