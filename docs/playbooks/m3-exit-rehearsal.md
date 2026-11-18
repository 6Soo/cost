# M3 종료 조건 예행 — 합성 자료로 저장 판정 누락 보완·재실행 0을 확인하는 절차

- 목적: [통합 명세 §11.5 M3 종료 조건](../SPEC.md#m3--저장-판정-완결성)의 세 가지 — **저장 대상 누락 0**, **같은 입력 재실행 시 추가 보완 0**, **설명되지 않은 원천·투영·기간 차이 0** — 을 실제 운영에서 실행하기 전에 **합성 자료로 예행**하고, 그때 실제로 성공한 명령 순서를 그대로 적는다.
- 실행 주체: 운영 담당 세션(한 세션). 이 절차서 자체는 운영 DB를 열지 않는다. 운영 실행은 [코어 1차 전환 절차](core-cutover.md)의 승인·백업 조건과 함께 별도로 한다.
- 근거: 설계 `docs/design/m3-core.md` §3.3·§7 U11, `docs/SPEC.md:279-287`. 판정 규칙은 [판정 규칙집](../DECISION_POLICY.md)이 정본이다.
- 개정 이력: 2026-11-19 · 합성 자료 예행으로 처음 작성. 명령과 출력은 2026-11-19 `3d8e8791` 기준으로 실제 실행해 확인했다.
- 상태(2026-11-19): **합성 자료 예행 완료.** 아래 자료 준비 1~3단계와 실행 ①~⑤, 저장 보완 1~5단계를 실제로 돌려 성공·실패 출력을 모두 확인했고, 실패했다가 고친 지점들을 "실패와 진단"에 적었다(가장 많이 틀리는 곳은 감사/적용의 digest 조건 불일치다).

## 왜 이 예행이 필요한가

M3 종료 조건은 "**운영의** 저장 대상 누락 0"이다. 그 숫자를 운영에서 처음 재면, 실패했을 때 원인이 (1) 자료 문제, (2) 명령 조건 불일치, (3) 코어 결함 중 무엇인지 구분되지 않는다. 합성 자료로 먼저 돌리면 **명령 자체가 맞는지**를 코어 결함과 분리해 확인할 수 있고, 운영에서는 숫자만 보면 된다.

**운영 DB·`D:/WebLedgerHost`는 이 예행에서 읽지도 쓰지도 않는다.** 경로 위장도 하지 않는다: 코어는 `--host-root`로 "운영 DB면 거부"를 판단하므로(아래 "보호" 절), 예행에서는 **보호 경로와 다른 임시 루트**를 `--host-root`로 준다.

## 예행 자료(합성)를 만드는 법

세 가지를 만든다: (가) 합성 보드 DB, (나) 합성 가맹점 규칙, (다) 빈 `core.sqlite`. 모두 저장소 밖 `.local-archive/`(Git 무시)에 둔다.

```powershell
# 레포 루트에서. $repo는 이 작업 폴더의 절대 경로다.
$repo = 'C:/Users/kkokk/.paseo/worktrees/28lt5mey/m3-exit-rehearsal-20261119'
$a = "$repo/.local-archive/m3-exit-rehearsal-20261119"
$bin = "$repo/core/target/debug/costcore.exe"   # 배포 예행이면 release 빌드
$py  = (Get-Command python).Source                # 절대경로여야 한다(아래 "실패와 진단" 첫 행)
$host = "$a/host"                                 # 보호 경로가 아닌 임시 루트(운영 판정용 host-root)
```

1. **합성 보드 DB.** `transactions` 3,002행(그중 게시된 `ledger_entries`·`board_rows` 40행), 여행 탭 5개(열린 여행 4 + 완료 1). **`quarter:2026:3`(열린 분기)만 쓴다** — `quarter:2026:1|2`는 완료 분기라 `core/crates/core/src/plan/fresh.rs:48`이 Protected로 닫는다. 보호 행(파싱 오류·중복 표시)·완료 기간(2025) 행을 섞어 둔다.

   아래 생성기는 **이 문서에 그대로 들어 있고**, 고객 자료가 없으며 저장소 밖(`.local-archive/`)에만 쓴다. `$a` 폴더에 저장해 실행한다.

   ```python
"""Self-contained synthetic board builder for the M3 exit rehearsal (no customer data, no production DB).

Usage:
  python -I make_synthetic_board.py --out DIR --rows 3000 [--pre-classified N]

Writes DIR/board.sqlite with the full board schema, holding:
  - trip tabs: 4 open trips (2026-10..12) + 1 completed trip (2025-12)
  - transactions: open-trip purchases, quarter:2026:3 rows, completed-period rows (2025),
    protected rows (parse_error, duplicate_of), one refund pair
  - ledger_entries / board_rows for the first 40 already-classified rows
Never uses quarter:2026:1 or :2 (completed quarters -> Protected, plan/fresh.rs:48).
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ARGS = argparse.ArgumentParser()
ARGS.add_argument('--out', required=True)
ARGS.add_argument('--rows', type=int, default=3000)
ARGS.add_argument('--pre-classified', type=int, default=0)
ARGS.add_argument('--repo-root', required=True, help='레포 루트(절대경로). app·webapp 스키마를 읽으려면 필요하다')
ARGS = ARGS.parse_args()
sys.path.insert(0, str(Path(ARGS.repo_root).resolve()))

from app import db as app_db  # noqa: E402
from webapp import ledger_store_schema as board_schema  # noqa: E402

HASH = 'b' * 64
TRIPS = [('T-A', '1020_합성도쿄', '도쿄', '2026-10-20', '2026-10-24'),
         ('T-B', '1105_합성오사카', '오사카', '2026-11-05', '2026-11-08'),
         ('T-C', '1220_합성삿포로', '삿포로', '2026-12-20', '2026-12-24'),
         ('T-Q', '1226_합성제주', '제주', '2026-12-26', '2026-12-28')]
MERCHANTS = [('합성식당', '음식점'), ('합성카페', '음식점'), ('합성호텔', '숙박비'),
             ('합성항공', '항공료'), ('합성마트', '생필품'), ('합성교통', '교통비')]


def insert(conn, table, row):
    conn.execute(f'INSERT INTO {table}({",".join(row)}) VALUES ({",".join("?" * len(row))})', list(row.values()))


def build(out, rows, pre_classified, seed):
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'board.sqlite'
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(app_db.SCHEMA_SQL)
    conn.executescript(board_schema.SCHEMA_SQL)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(trip_tabs)')]
    for tab, key, dest, start, end in TRIPS + [('T-OLD', '1201_옛여행', '부산', '2025-12-01', '2025-12-03')]:
        values = {'tab_id': tab, 'display_key': key, 'destination': dest, 'starts_on': start, 'ends_on': end,
                  'deleted': 0, 'created_at': '2026-09-01', 'updated_at': '2026-09-01'}
        values = {c: v for c, v in values.items() if c in cols}
        conn.execute('INSERT INTO trip_tabs(%s) VALUES (%s)' % (','.join(values), ','.join('?' * len(values))),
                     tuple(values.values()))
    txn_cols = [r[1] for r in conn.execute('PRAGMA table_info(transactions)')]
    base = dict(batch_id='syn-batch', issuer='SYN-BANK', card_tail='1111', card_kind='credit',
                transaction_direction='purchase', transaction_kind='일시불', original_approval_number='',
                posting_date='', description_raw='', raw_row_json='{}', duplicate_of=None, conflict_reason='',
                parse_error='', classification_state='needs_review', classification_source='',
                classification_basis='', item='', description='', display_tab_id='', trip_id='', revision=1,
                decided_at=None, created_at='2026-10-01', merchant_normalized='', foreign_amount='',
                foreign_currency='', source_hash=HASH, row_index=1, approval_number='')

    def txn(tid, **over):
        row = dict(base, transaction_id=tid, merchant_normalized=str(over.get('merchant', '')).lower(), **over)
        insert(conn, 'transactions', {c: row[c] for c in txn_cols if c in row})

    posted = 0
    for i in range(1, rows + 1):
        merchant, item = MERCHANTS[i % len(MERCHANTS)]
        trip = TRIPS[i % 4]
        if i % 997 == 0:
            txn(f'2025-{i:04d}', merchant=merchant, approval_date='2025-06-1%d' % (i % 9),
                amount_krw=-10000 - i, approval_number=f'AP-{i}')
            continue
        day, tab = ('2026-09-1%d' % (i % 9), 'quarter:2026:3') if i % 7 == 0 else (trip[3], trip[0])
        if i % 149 == 0:
            txn(f'bad-{i:04d}', merchant=merchant, approval_date=day, amount_krw=-5000, parse_error='SYNTH-PARSE')
            continue
        if i % 211 == 0:
            txn(f'dup-{i:04d}', merchant=merchant, approval_date=day, amount_krw=-7000,
                duplicate_of=f'2026-{i - 1:04d}')
            continue
        state = ('classified' if i <= pre_classified else 'needs_review') if pre_classified else (
            'needs_review' if i <= rows * 2 // 3 else 'classified')
        done = state == 'classified'
        txn(f'2026-{i:04d}', merchant=merchant, approval_date=day, posting_date=day, amount_krw=-10000 - i % 9000,
            approval_number=f'AP-{i:04d}', classification_state=state,
            classification_source='inference' if done else '', item=item if done else '',
            display_tab_id=tab if done else '', trip_id=trip[0] if done else '')
        if done and posted < 40:
            posted += 1
            amount = -10000 - i % 9000
            insert(conn, 'ledger_entries', dict(transaction_id=f'2026-{i:04d}', batch_id='syn-batch', item=item,
                                                description='', display_tab_id=tab, trip_id=trip[0], amount_krw=amount,
                                                merchant=merchant, occurred_on=day, transaction_direction='purchase',
                                                source_hash=HASH, committed_at='2026-10-05'))
            payload = json.dumps({'item': item, 'description': '', 'display_tab_id': tab, 'trip_id': trip[0],
                                  'amount_krw': amount, 'merchant': '', 'service_period': '',
                                  'revision': 1, 'confirmed_by': 'automatic'}, ensure_ascii=False)
            conn.execute('INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,?,?,1,?)',
                         ('card-' + f'2026-{i:04d}', 'expense', tab, payload))
    txn('rfnd-orig-1', merchant='합성호텔', approval_date='2026-10-22', amount_krw=-200000, approval_number='RF-1')
    txn('rfnd-refund-1', merchant='합성호텔', approval_date='2026-10-23', amount_krw=200000, approval_number='RF-2',
        transaction_direction='refund', original_approval_number='RF-1', transaction_kind='취소')
    conn.commit()
    counts = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
              for t in ('transactions', 'trip_tabs', 'ledger_entries', 'board_rows')}
    conn.close()
    print(json.dumps({'path': str(path), 'counts': counts}, ensure_ascii=False))


if __name__ == '__main__':
    build(Path(ARGS.out), ARGS.rows, ARGS.pre_classified, 20261119)
   ```

   ```powershell
   python -I "$a/make_synthetic_board.py" --out "$a/syn" --rows 3000 --repo-root $repo
   # 기대 출력: {"path": "...syn/board.sqlite", "counts": {"transactions": 3002, "trip_tabs": 5,
   #             "ledger_entries": 40, "board_rows": 40}}
   ```

   - `--pre-classified N`: 앞 N행을 이미 `classified`로 채운다(Python 작성자가 이미 판정한 상태를 흉내 낼 때). 0(기본)이면 앞 2/3은 `needs_review`, 뒤 1/3은 `classified`다.
2. **합성 가맹점 규칙 6개.** 규칙 표가 없으면 항목 추론이 전부 실패해 판정이 `Unattributable`로 닫힌다(그러면 `written`이 0이 된다 — 코어 결함이 아니라 자료 부족이다).

   ```python
"""Add 6 synthetic merchant rules so item inference succeeds (otherwise every row is Unattributable).

  python -I add_synthetic_rules.py --db board.sqlite --repo-root ROOT
"""
import argparse, sqlite3, sys
from pathlib import Path

ARGS = argparse.ArgumentParser()
ARGS.add_argument('--db', required=True)
ARGS.add_argument('--repo-root', required=True)
ARGS = ARGS.parse_args()
sys.path.insert(0, str(Path(ARGS.repo_root).resolve()))
from app import db as app_db, rules  # noqa: E402

store = app_db.Store(sqlite3.connect(Path(ARGS.db).resolve()))
try:
    for merchant in ('합성식당', '합성호텔', '합성항공', '합성마트', '합성교통', '합성카페'):
        rules.save_rule(store, {'conditions': {'merchant_normalized': merchant}, 'effects': {'item': 'x'},
                                'note': 'synthetic', 'origin': 'synthetic', 'rule_id': 'syn-' + merchant})
    store.conn.commit()
finally:
    store.conn.close()
print('rules ok')
   ```

   ```powershell
   Copy-Item "$a/syn/board.sqlite" "$a/work/r5.sqlite"
   python -I "$a/add_synthetic_rules.py" --db "$a/work/r5.sqlite" --repo-root $repo   # 기대 출력: rules ok
   ```

3. **빈 core.sqlite.** 이관은 멱등이고, 없으면 만든다.

   ```powershell
   & $bin migrate --core "$a/work/core5.sqlite"
   # 기대 출력: {"created":true,"from_version":0,"ok":true,"to_version":3}
   ```

## 실행 순서 (복사해서 그대로 쓰는 명령)

아래는 **실제로 성공한 그대로의 순서**다. ①②는 미리보기(쓰기 없음), ③은 쓰기 1회, ④는 같은 입력 재실행(쓰기 0이어야 함), ⑤는 사후 감사다.

```powershell
$ctx = '{"periods":{}}'      # ①과 ③이 반드시 같은 문자열이어야 한다(아래 "digest 규칙")
```

① **쓰기 전 감사(미리보기).** 저장 대상 누락·변경 필요·보호·불일치를 센다. 쓰지 않는다.

```powershell
$ctx | & $bin audit-decisions --db "$a/work/r5.sqlite" --core "$a/work/core5.sqlite" `
        --host-root $host --python $py --repo-root $repo
```

성공 기준: `ok`는 false가 **정상**이고(아직 `decisions`가 비어 있다), `classification_changes_required`가 남는다. **처음 만든 보드는 전부 `needs_review`라 여기서 `missing`은 0이다** — `missing`(저장 대상 누락)은 "화면 열이 이미 계획과 같은데 `decisions`가 없는" 행만 세기 때문이다(`completeness.rs:140-144`). `stored` 0과 `scanned`가 보드 행 수와 같으면 자료가 제대로 읽힌 것이다. 실제 출력(예행):

```json
{"coverage":{"classification_changes_required":2682,"eligible":0,"kept":0,"missing":0,"orphaned":0,
 "period_mismatch":0,"plan_digest":"77a0c063...","projection_mismatch":0,
 "protected_or_preserved":320,"scanned":3002,"source_mismatch":0,"stale":0,"stored":0},"ok":false}
```

② **같은 `$ctx`로 digest 확보.** `plan_digest`를 꺼낸다. **다른 조건으로 다시 재면 안 된다**(아래 "digest 규칙").

```powershell
$digest = ($ctx | & $bin audit-decisions --db "$a/work/r5.sqlite" --core "$a/work/core5.sqlite" `
            --host-root $host --python $py --repo-root $repo |
            ConvertFrom-Json).coverage.plan_digest
```

③ **적용(첫 쓰기).** `$ctx`를 표준 입력으로 그대로 넘기고 `--digest`에 ②의 값을 준다.

```powershell
$ctx | & $bin apply --db "$a/work/r5.sqlite" --core "$a/work/core5.sqlite" --digest $digest `
        --host-root $host --python $py --repo-root $repo
```

성공 기준(예행 실제 출력): `ok:true`, `skipped_mismatch:0`, `written` > 0.

```json
{"backfilled":0,"ok":true,"result":{"policy":"complete-card-inference-v1","protected":37,
 "reconsider":false,"reviewed":2965,"scanned":3002,"to_classify":1978,"valid_trips":5},
 "skipped_mismatch":0,"skipped_unjudged":283,"written":1695}
```

④ **같은 입력 재실행 → 쓰기 0.** ②를 **다시 만들어**(입력이 바뀌었으므로 digest도 바뀐다) ③을 한 번 더 돌린다.

```powershell
$digest2 = ($ctx | & $bin audit-decisions --db "$a/work/r5.sqlite" --core "$a/work/core5.sqlite" `
             --host-root $host --python $py --repo-root $repo |
             ConvertFrom-Json).coverage.plan_digest
$ctx | & $bin apply --db "$a/work/r5.sqlite" --core "$a/work/core5.sqlite" --digest $digest2 `
        --host-root $host --python $py --repo-root $repo
```

성공 기준(예행 실제 출력): `"written":0`, `"backfilled":0`, `"skipped_mismatch":0`. 이것이 M3 종료 조건 "같은 입력 재실행 시 추가 보완 0"의 예행 근거다.

```json
{"backfilled":0,"ok":true,"result":{"policy":"complete-card-inference-v1","protected":37,
 "reconsider":false,"reviewed":2965,"scanned":3002,"to_classify":283,"valid_trips":5},
 "skipped_mismatch":0,"skipped_unjudged":283,"written":0}
```

⑤ **쓰기 후 감사.** `stored`가 ③의 `written`과 같아야 하고, `orphaned`·`source_mismatch`·`period_mismatch`가 0이어야 한다.

```powershell
$ctx | & $bin audit-decisions --db "$a/work/r5.sqlite" --core "$a/work/core5.sqlite" `
        --host-root $host --python $py --repo-root $repo
```

예행 실제 출력: `"stored":1695`, `"missing":0`, `"orphaned":0`, `"source_mismatch":0`, `"period_mismatch":0`. `ok`는 false이고 `classification_changes_required`가 남는 것이 **정상**이다(아래 "읽는 법").

## 이미 Python이 판정한 보드의 저장 보완(종료 조건 2번) 예행

운영 M3 종료 조건의 2번("같은 입력 재실행 시 추가 보완 0")은 실제로는 **이미 `classified`인데 `decisions`가 비어 있는 보드**를 채우는 경로다. 이 경우는 일반 `apply`가 아니라 **decisions-only 보완**을 쓴다.

1. **이미 판정된 보드를 만든다.** Python 작성자(`automatic_classification.plan` → `apply`)로 한 번 판정한다. 실제 운영 보드가 이 상태다. 아래 `$a/py_classify.py`를 `$a`에 저장해 돌리면 Python이 판정한 보드가 새 사본에 생긴다(예행에서는 이 방법으로 만들었고, `b2.sqlite`가 그 보드였다).

   ```python
import sys, sqlite3, json
from pathlib import Path
src, dst = sys.argv[1], sys.argv[2]
Path(dst).write_bytes(Path(src).read_bytes())
sys.path.insert(0, sys.argv[3])
from app import automatic_classification as policy
conn = sqlite3.connect(dst, isolation_level=None)
trips = [dict(zip(['tab_id', 'display_key', 'destination', 'starts_on', 'ends_on'], r), trip_id=r[0])
         for r in conn.execute('SELECT tab_id,display_key,destination,starts_on,ends_on FROM trip_tabs WHERE deleted=0')]
preview = policy.plan(conn, trips)
summary = policy.apply(conn, preview, trips)
conn.close()
print(json.dumps({'digest': preview['digest'], 'targets': len(preview['targets']), 'summary': summary}, ensure_ascii=False))
   ```

   ```powershell
   python -I "$a/py_classify.py" "$a/work/r5.sqlite" "$a/work/b2.sqlite" $repo
   # 기대 출력(예행 실제): {"digest": "8d37d9f7...", "targets": 1978,
   #                       "summary": {"to_classify": 1978, "protected": 37, "scanned": 3002, ...}}
   & $bin migrate --core "$a/work/coreb.sqlite"    # 빈 core(기대: created true, to_version 3)
   ```
2. 감사로 누락을 센다. **`missing` > 0**이 보완 대상의 표지다.

   예행 실제 출력: `"eligible":1695,"missing":1695,"stored":0` — 그리고 `classification_changes_required`는 **0이 아니다**(987이 남는다: 다시 계산한 판정이 화면 열과 다른 행). 보완 대상의 표지는 **`missing` > 0**이고, 보완은 `eligible`행만 채우며 나머지는 일반 판정·교정 경로의 몫으로 남긴다.

3. **보완 모드 적용.** `context`에 `decisions_only: true`를 넣고 `--backfill-decisions`를 함께 준다. 둘 중 하나라도 빠지면 코어는 **core를 열기 전에** `CORE_REPAIR_REQUIRES_BACKFILL_AND_PERIOD_FACTS`로 거부한다(`core/crates/cli/src/main.rs:455-459`, `core/crates/core/src/apply.rs:131-134`).

   ```powershell
   $ctxR = '{"periods":{},"decisions_only":true}'
   $dR = ($ctxR | & $bin audit-decisions --db "$a/work/b2.sqlite" --core "$a/work/coreb.sqlite" `
           --host-root $host --python $py --repo-root $repo | ConvertFrom-Json).coverage.plan_digest
   $ctxR | & $bin apply --db "$a/work/b2.sqlite" --core "$a/work/coreb.sqlite" --digest $dR `
           --backfill-decisions --host-root $host --python $py --repo-root $repo
   ```

   예행 실제 출력: `{"backfilled":1695,"ok":true,...,"written":0,...}` — 화면 열은 건드리지 않고 `decisions`만 채운다.

4. **재실행 0 확인.** 같은 `$ctxR`로 digest를 다시 만들어 한 번 더 돌린다. 예행 실제 출력: `"backfilled":0`.
5. **감사 재확인.** `periods`만 넣은 `$ctx`로 감사하면 `missing:0`, `stored`가 보완한 수와 같다. `classification_changes_required`는 남는다(정상 — 그 행들은 화면 열 자체가 달라 일반 판정 경로의 몫이다).

## digest 규칙 — 이 예행에서 가장 많이 틀리는 곳

`apply`는 계획을 **다시 만들어** digest를 대조하고, 다르면 `CLASSIFICATION_PREVIEW_STALE`로 아무것도 쓰지 않는다(`core/crates/core/src/apply.rs:167-169`). digest는 다음 네 가지에 따라 달라진다. **audit과 apply에서 이 넷을 똑같이 맞춰야 한다.**

| 무엇이 digest를 바꾸는가 | 코드 위치 | 어떻게 맞추는가 |
| --- | --- | --- |
| `context`가 `trips`·`nets`·`evidence`를 덮어쓰는지 여부 | `core/crates/core/src/plan/mod.rs:477` `fingerprint`, `pipeline.rs:203` `overlay_context` | **audit과 apply에 같은 JSON 문자열을 준다.** `{"periods":{}}`만 주면 DB에서 읽은 여행 목록을 쓴다. `"trips"` 키를 넣으면 그 값이 이긴다 |
| `reconsider` | `plan/mod.rs:528`(digest 입력), `main.rs:475`(apply는 `--reconsider` 또는 `context.reconsider`), `completeness.rs:66`(audit은 `context.reconsider`만 본다) | **`context`의 `"reconsider":true`만 쓴다(양쪽 모두).** audit은 `--reconsider` 플래그를 **받아들이지만 무시**한다(실제 확인: 플래그를 붙여도 audit digest가 `2d808f6e…`로 같고, `context.reconsider`를 넣으면 `22d7ac78…`로 바뀐다). 즉 audit에 플래그만 주면 apply와 조건이 어긋나고, 오류 없이 stale로 실패한다. apply에도 플래그를 쓰지 말고 context로 통일한다 |
| `context.periods`(이용기간 근거) | `plan/mod.rs:521-529` `evidence`, `apply.rs:144-155` | 양쪽에 같은 `periods` 객체를 준다. **없으면 audit이 `PERIOD_FACTS_REQUIRED`로 거부한다** |
| `context.transaction_ids`(범위 제한) | `main.rs:449-453`(apply는 `selected`로 넘긴다), `completeness.rs:62-67`(audit은 `overlay_context`에 `None`을 넘긴다) | **audit에 `transaction_ids`를 넣지 않는다.** audit은 이 키를 무시하고 전체를 훑는다(`scanned 3002`). apply에만 넣으면 `selected`가 digest에 들어가 조건이 어긋나 `CLASSIFICATION_PREVIEW_STALE`이 난다(실제로 확인: audit digest가 ids 목록을 바꿔도 `77a0c063…`로 같고, apply에 ids를 넣으면 거부됨) |

핵심: **같은 변수 하나(`$ctx`)를 두 명령에 그대로 파이프한다.** ②와 ③에서 문자열을 손으로 다시 치면 실패한다.

- `reconsider`가 필요한 경우: **양쪽 모두** `context`에 `"reconsider":true`를 넣는다. apply에 `--reconsider` 플래그를 같이 주면 digest는 같지만(둘 다 true), audit에는 플래그가 닿지 않으므로 **플래그를 쓰지 않는 편이 안전하다**. 예행에서 `reconsider:true` 조건으로 `written:2547`, `skipped_mismatch:135`를 실제로 확인했다(이 135건은 `reconsider`의 정상 동작이지 결함이 아니다).

## 출력 읽는 법

| 칸 | 뜻 | 종료 조건에서 |
| --- | --- | --- |
| `scanned` | 훑은 거래 수 | 기준값 |
| `stored` | `decisions`에 있는 판정 수 | ⑤에서 ③의 `written`과 같아야 한다 |
| `eligible` | 다시 계산한 판정이 **화면 열과 이미 같아서**, 저장만 하면 되는 건 | — |
| `missing` | `eligible`인데 `decisions`가 없는 건 | **1차 종료 조건: 0** |
| `stale` | 저장된 근거 digest·판정 함수 버전이 현재와 다른 건 | 0 (다르면 재판정 대상) |
| `classification_changes_required` | 다시 계산한 판정이 화면 열과 **달라** 자동으로 저장할 수 없는 건 | 정책 근거를 남기고 별도 처리. 감사 `ok`가 false인 정상 이유 |
| `projection_mismatch` / `source_mismatch` / `period_mismatch` | 저장 판정·원천·기간이 어긋난 건 | **2차 종료 조건: 모두 0** |
| `orphaned` | `decisions`에 있으나 원천 행이 없는 건 | 0 |
| `protected_or_preserved` / `kept` | 보호·보존·기존 판정 유지 | 0일 필요 없음 |

**감사 `ok`가 false인 것은 실패가 아니다.** `ok`는 `missing`·`stale`·`projection_mismatch`·`source_mismatch`·`period_mismatch`·`classification_changes_required`·`orphaned`가 **모두 0일 때만** true다(`core/crates/cli/src/main.rs:514-520`). 쓰기 전에는 `classification_changes_required`가 반드시 남으므로, 쓰기 전 감사는 `ok:false`가 정상이다. 판단 기준은 **칸별 숫자**다. 종료 코드도 같다: 통과 0, 차이가 있으면 1(`main.rs:522`).

## 실패와 진단 (예행에서 실제로 걸린 것)

| 증상 (출력 코드) | 원인 | 확인·고치기 |
| --- | --- | --- |
| `{"error":{"code":"PYTHON_BRIDGE_FAILED:PYTHON_NOT_STARTED"}}` | `--python`에 `python`(맨 이름)을 줬고 코어가 하위 프로세스를 띄울 때 PATH에서 못 찾았다. 이 예행에서 처음 걸린 지점 | `(Get-Command python).Source`의 **절대경로**를 `--python`에 준다. `--repo-root`도 절대경로 |
| `CLASSIFICATION_PREVIEW_STALE` | ②와 ③의 조건이 다르다. "digest 규칙" 네 가지 중 하나가 어긋났다 | ②와 ③에 **같은 `$ctx` 문자열**을 파이프했는지, `reconsider`를 한쪽만 줬는지, `periods`가 양쪽에 있는지, **`transaction_ids`를 apply에만 넣지 않았는지**(audit은 이 키를 무시한다) 확인한다. 고친 뒤 ②부터 다시 한다 |
| `PERIOD_FACTS_REQUIRED` (audit) | `context`에 `periods` 객체가 없다(`main.rs:501-503`) | `$ctx`에 `"periods":{}`를 넣는다. 운영에서는 `app.core_writer.periods_for`의 실제 근거를 넣는다 |
| `{"error":{"code":"USAGE_INVALID"}}` (apply) | `--digest`를 빠뜨렸다. apply는 digest가 **필수**다(`main.rs:437`) | ②에서 digest를 먼저 얻는다 |
| `{"error":{"code":"IO_ERROR"}}` (audit/apply, context에 `trips`를 넣었을 때) | context 파일을 Windows 기본 인코딩으로 써서 한글 여행 이름이 깨졌다 | context 파일을 **UTF-8**로 쓴다(`open(path,'w',encoding='utf-8')`). PowerShell 7은 기본이 UTF-8이지만, 리다이렉션(`>`)으로 만든 파일은 확인한다 |
| `written:0`인데 `skipped_unjudged`가 거의 전부 | 가맹점 규칙 표가 없어 항목이 추론되지 않았다 → 판정이 `Unattributable` | 2단계 `add_synthetic_rules.py`를 먼저 돌린다. 규칙 6개로 `written`이 0 → 1,695로 바뀐다 |
| `written:0`이고 `to_classify:0` | `context`에 `"trips":[]`를 넣어 여행 목록이 비었다 | `trips` 키를 넣지 않거나 DB에서 읽은 값을 넣는다 |
| 감사 digest가 `quarter:2026:9` 같은 값으로 나옴 | 합성 자료의 분기 표기가 틀렸다(열린 분기는 `3`만) | 이 문서의 `make_synthetic_board.py`는 2026 Q3만 쓴다. 손으로 만든 자료면 `fresh.rs:48`의 허용 목록을 본다 |
| `DB_IS_LIVE` | `--db`가 `--host-root`의 `data/board.sqlite`와 같은 파일이다(`pipeline.rs:69-77`, Windows는 길이·생성 시각·수정 시각이 모두 같으면 같은 파일로 본다 `:81-95`) | 예행은 `--host-root`에 **보호 경로가 아닌 임시 루트**를 준다. 운영 사본은 SQLite backup API로 만든다 — 시각을 보존하는 복사 사본이 거부된다는 것은 [core-cutover.md](core-cutover.md)의 기존 기록이며 이 예행에서 다시 재지는 않았다 |

## 보호 (이 절차가 지키는 것)

- 운영 DB·`D:/WebLedgerHost`의 **읽기·쓰기 모두** 예행에서 하지 않는다. `--allow-live`를 주지 않는다.
- `apply`는 `--allow-live` 없이는 `--host-root/data/board.sqlite` 경로를 거부한다(`core/crates/core/src/pipeline.rs:69-76`). 예행은 `--host-root`를 임시 루트로 두어 이 검사를 통과시킨다 — **운영 경로로 우회하지 않는다**.
- `--private-out` 같은 비공개 파일 경로는 예행에서 쓰지 않는다. audit·apply에는 그런 인자가 없다(그림자 명령 `shadow`·`shadow-links`만 쓴다). 그림자를 돌릴 때 쓰면 `<host-root>/data/backups`가 **이미 존재하는 폴더여야** 하고 그 아래여야 한다(`guard.rs:28-34` — `protected_root`가 `canonicalize`에 실패하면 `PRIVATE_PATH_REJECTED`).
- 예행 자료는 `.local-archive/`(Git 무시)에만 두고 커밋하지 않는다. 합성 자료에는 고객 원문이 없다.
- 운영 포트 8751·8752·8790을 쓰지 않는다. 운영 프로세스를 건드리지 않는다.

## 운영에서 같은 순서로 할 때의 차이

| 예행(합성) | 운영 |
| --- | --- |
| `.local-archive/...` 사본 | 신선 백업·복원 확인 사본(`D:/WebLedgerHost/data/backups/`, [core-cutover.md](core-cutover.md) 2단계) |
| `--host-root`=임시 루트 | `--host-root D:/WebLedgerHost`, `--db`=`data/backups/` 아래 사본. 사본 경로는 운영 `data/board.sqlite`와 다르므로 `--allow-live` 없이도 통과한다. **`--allow-live`를 쓰지 않는 것이 예행과 운영의 공통 규칙이다**(운영 파일에 직접 쓰지 않는다) |
| `"periods":{}` | `app.core_writer.periods_for(...)`가 만든 실제 이용기간 근거(없으면 `PERIOD_FACTS_REQUIRED`) |
| `written` 수천 건이 정상 | 운영 첫 실행은 `backfill` 건수가 매우 클 수 있다(정상) |
| 운영 반영 없음 | decisions-only 보완은 **승인된 창에서만**. [core-cutover.md](core-cutover.md) "실패와 복구"·"판정 함수 버전 변경 배포 뒤 전체 재판정"을 따른다 |

## 이 절차서가 확인한 것과 확인하지 않은 것

- 확인(2026-11-19, `3d8e8791`, debug 빌드): 이 문서에 든 생성기 두 개를 문서에서 그대로 꺼내 실행해 3,002행 합성 보드를 만들고(감사 digest `77a0c063…` 재현), 감사 → digest → 적용(`written:1695`, `skipped_mismatch:0`) → 재실행(`written:0`) → 사후 감사(`stored:1695`·`missing:0`·불일치 0). decisions-only 보완(`missing:1695` → `backfilled:1695` → 감사 `missing:0`·`stored:1695`). 실패 출력 세 가지(`CLASSIFICATION_PREVIEW_STALE`, `PERIOD_FACTS_REQUIRED`, `USAGE_INVALID`)와 `PYTHON_NOT_STARTED`·`IO_ERROR` 진단. `transaction_ids`가 audit digest에 영향을 주지 않으나 apply에는 주는 것도 실제 실행으로 확인했다.
- 하지 않음: 운영 DB 접근, `release` 빌드 실행, 실제 OTA 이용기간 근거 생성(운영 자료 필요), 대규모(1만 행 이상) 성능 측정.
