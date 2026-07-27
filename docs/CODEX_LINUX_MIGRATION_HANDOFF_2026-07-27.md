# Codex Linux migration handoff — 2026-07-27

## 0. Freeze point

- This handoff supersedes the missing `docs/CODEX_DESKTOP_MIGRATION_HANDOFF_2026-07-26.md`.
- All Codex subagents and cost-processing workers were stopped before this handoff.
- No Python or Orca cost job was running at the freeze point.
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
