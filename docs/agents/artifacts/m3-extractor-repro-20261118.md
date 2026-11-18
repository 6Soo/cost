# M3-3 추출 기준 재현 증거 (2026-11-18)

[`SPEC.md`](../../SPEC.md) §11.1 M3-3 계약: 고정 7,965건 기준 출력의 **입력 지문·사본·의존성·출력 지문**을 연결하고, 새 캡처와 다른 490건의 출처 식별 필드를 동일 입력·변환 버전으로 재검증하며, **추출 내용 차이와 출처 식별 차이를 구분**해 기록한다. 기존 입력을 재현할 수 없으면 그 사실과 영향 범위를 남기고, 기준 변경 여부는 별도 결정으로 남긴다.

- 작업 브랜치 `qwen-m3-extractor-repro-20261118`, 베이스 origin/main `259bc187`. 선행 생산 기록은 [`m3-extractor-baseline-20261117.md`](m3-extractor-baseline-20261117.md).
- **경계:** 이 세션은 실제 고정 입력에 대한 추출·비교를 실행하지 않았다. 파일 메타·봉투 JSON·기계적 해시·보존 집계만 확인했고, 고객 원문은 열지 않았으며 운영 DB는 stat만 했다. 검증은 합성 입력으로 했고, 실제 데이터 재현 명령은 §8에 남긴다. 이 문서에는 고객 원문·거래 ID 표본이 없다.

## 1. 고정 기준 출력 — 디스크 재확인 (일치)

| 항목 | 값 |
| --- | --- |
| 경로 | `D:/WebLedgerHost/data/backups/extractor-baseline-main-20261117/events.json` |
| sha256 | `a26d446510faabe4cbdfd5d8cf114b0903e6b87b8453fdb3380d529e605cbaf6` |
| 크기 / 건수 | 28,637,104 bytes / **7,965** |
| mtime | 2026-11-16T17:55:35Z (11-17 02:55 KST) |
| 생산 python_sha | `750e4a65aea5f5603fc04199046d5e64e8a7e45c` (response.json) |
| input_digest | `1e9613ebe30aacde13a647de81d9f662d03939d2909764f9621b273f45539f7b` — **요청 JSON의 지문이지 DB 내용 지문이 아니다** |

디스크 바이트 해시·건수가 생산 기록과 일치(`matches_recorded_baseline=true`). 이 출력은 manifest 이전 시대 산출물이라 **입력 사본·논리 지문 바인딩이 없다**.

## 2. 입력 사본 — 소실된 고정 입력, 생존 사본, 동일 입력 증명

- **고정 생산 입력 소실:** `extract-baseline-e2mjubkr/ota-evidence.sqlite`는 부재(stat `exists=false`). 생산 기록이 "임시 디렉터리 정리"를 예고했고, 독립 검수 기록 `m3-m5-independent-review-20261117.md`(main checkout)의 **F-07**이 지문 미바인딩을 지적했다. 이 사본의 내용 지문(논리 fingerprint)은 **어디에도 기록되지 않았다** → 고정 기준의 동일 입력 재검증은 현재 증거로 **불가**.
- **라이브 무접근:** `D:/WebLedgerHost/data/ota-evidence.sqlite`는 stat만 확인(1,761,828,864 bytes, mtime 2026-11-15T14:20:38Z = 23:20 KST). 열지 않았다. 생산 기록의 "보존 원본 불변" 주장은 **크기·mtime 기반**이며 내용 지문으로 검증된 바 없다.
- **생존 사본·중단 캡처:**

| 사본 | 크기(bytes) | mtime(UTC) | 논리 지문 | 바인딩 |
| --- | --- | --- | --- | --- |
| `m6-extractor-review-20261117/ota-evidence.sqlite` | 1,761,828,864 | 2026-11-16T23:25:26Z | `8171c4b8…` (재계산) | 없음(검수 세션 사본) |
| `extractor-baseline-captures/6f3ab221c0b04924b9aa1e7432965420/inputs/ota-evidence.sqlite` | 1,761,828,864 | 2026-11-17T13:31:50Z | `8171c4b8…` (재계산) | manifest `405eb112…` |
| `extractor-baseline-captures/6af6f9f6b9944d3f8b32eb418b6af3da/inputs/ota-evidence.sqlite` | 1,761,828,864 | 2026-11-17T12:56:39Z | 미측정 | **manifest 없음**(중단; 설계상 완료 시에만 기록) |

- **동일 입력 증명:** m6 사본의 논리 지문 == 캡처 manifest 논리 지문 == `8171c4b8cf6dcd7222f52967967b3c9946771e9532c822b3156e96cc6bff1390`. 내 worktree에서 `sqlite_logical_fingerprint`(페이지 배치 무관 typed-row-hash 멀티셋)로 **양쪽 모두 재계산해 일치** 확인. 즉 m6 검수와 보완 캡처는 논리적으로 동일한 입력을 사용했다.
- 캡처 스냅샷 파일 sha256 `1400bfc044c961650e1fe3f4328f967674892ac336ce425946e8f71b5248cc8d` == manifest `input.sha256` (재확인).

## 3. 캡처 바인딩 — 생산 코드 증명 (75/75 일치)

캡처 `6f3ab221c0b04924b9aa1e7432965420`, manifest_sha256 `405eb112b05fe14096b6fa76a35aaaf81dbfb7515ce8f9180a68ff13809cf0c8`, captured 2026-11-17T13:39:23Z.

| 항목 | 값 | 재확인 |
| --- | --- | --- |
| input sha256 / 논리 지문 | `1400bfc0…` / `8171c4b8…` | 파일 해시·논리 지문 모두 일치 |
| output | `885331d6bdcaa8954e58fa28c137cbd5bf2743ed66142b41fad4ebaac7d128dd` @ `m3-manifest-resume-20261117T133118Z/events.json`, 28,637,104 B, 7,965건 | 디스크 해시 일치 |
| producer.runtime | 3.14.7 | — |
| producer.python_source_sha256 | `a48a00d8484fef962d0a5d3cd070463e5d0e2b217920d3f940f97f689134157e` | 019386ac의 extract_baseline.py blob 해시와 일치 |
| producer.production_python_sha256 | `60f0a583d8b1f7c5c9dcd4dc56d3e47e913450fa47841b7a5fd9f15568d2d6e7` | **모듈 해시 목록의 번들 지문**(git 커밋 SHA 아님 — 레포에 객체 없음 확인) |
| dependency_modules | 75개 | **전부 019386ac git blob 해시와 일치 (mismatch 0)** |
| sources | sqlite-backup, external_source_files=false | — |

→ **캡처 생산 코드 = 019386ac 정확히 증명.** 의존성 폐포는 `_DEPENDENCY_ROOTS`(tools.core_bridge.{extract_baseline,ota_input,commands} + app.{ota_sources,ota_payments})의 AST import 전이 폐포다.

## 4. 변환 버전 비교 (750e4a65 → 019386ac)

- 고정 생산 시점 하네스는 **미커밋** 상태였다(750e4a65 트리에 `extract_baseline.py` 부재). 원본 하네스는 이후 main에 커밋됨(blob `bbe6d734fe4e003e22799d3381803eba314d3994` @ 259bc187). 확장 하네스 blob `c879a2921c0200f9b7fa0b5850c0a988d18ac804` @ 019386ac.
- **`write_baseline`: 독스트링 제외 AST 동일 → 출력 직렬화 로직 동일.**
- **`_backup`: 스냅샷 방식 동일**(읽기전용 연결 + `PRAGMA query_only` + backup API). 확장 판은 대상 디렉터리 생성·덮어쓰기 금지 가드만 추가 → 출력 변환과 무관한 입력 쪽 안전 강화.
- **추출 폐포**(app.ota_sources + app.ota_payments 전이 import, 71모듈): **12개 차이** — `ai_classification`, `automatic_classification`, `card_destination`, `classification_correction`, `closed_period`, `core_writer`, `google_authority`, `google_expense_rows`(신규), `ledger`, `manual_google_evidence`(신규), `review`, `trip_selection`. `tools/core_bridge/ota_input.py`는 동일.
- 그러나 **490건 차이 필드 4개를 방출하는 모듈은 바이트 동일**: `app/ota_payments.py`(`f37b6ee7…`), `app/ota_mail_reservation_identity.py`(`1048c97b…`), `app/ota_portal.py`(`be0e7aeb…`).
- 12개 차이 모듈이 이벤트 생성 경로에서 **행동을 바꾸는지는 미검증**(바이트 차이만 증명). 생산 기록의 "canonical" 주장은 생산 시점 PR980의 9파일 대비 직접 import 16모듈 범위였으며, 그 뒤 여러 PR의 누적 변경과 범위가 다르다.

## 5. 출력 해시 3종과 490건 분류

| 출력 | sha256 | 생산자 | 입력 |
| --- | --- | --- | --- |
| 고정 기준 | `a26d4465…` | 750e4a65 + 원본 하네스 | **소실**(지문 미기록) |
| m6 검수 | `9a24257b93a9fe09af7ef4fe3d0dc51b6d665dccb3d6ea09f0007e22c6de73ce` | **미기록** | m6 사본(논리 `8171c4b8…`) |
| 보완 캡처 | `885331d6…` | 019386ac(증명) | 캡처 사본(논리 `8171c4b8…`) |

- m6 `python-events.json` == `rust-events.json` == `9a24257b…` **디스크 해시 확인**(각 28,637,104 B). Rust는 당시 Python과 바이트 일치했으나 고정 기준과는 다르다.
- **m6 입력 ≡ 캡처 입력인데 출력이 다르다** → 변환 버전 차이 또는 비결정성. m6 Python 재실행의 생산 SHA가 기록에 없어(docs 전체 검색 무매치) **귀인 미검증**.
- 보존 집계 `m6-extractor-review-20261117/drift-diff-summary.json`(고정 vs m6): 공통 ID **7,965**, 추가/삭제 **0**, 차이 **490건**, 차이 필드는 정확히 `{_portal_reservation_provenance, observation_ids, reservation_identity_attestation, source_lineage_ids}` 각 490. **전부 출처 식별 필드, 추출 내용 차이 0.**
- 새 `extract-baseline-compare`(`extractor-baseline-compare-v1`)가 이 분류를 코드로 구현: `SOURCE_IDENTITY_FIELDS` 18개, 내용 프로젝션 멀티셋 조인, 정확 식별 일치 우선 짝짓기, 유일 업무키 짝짓기. 합성 회귀 `test_observed_490_shape_is_source_identity_only`가 위 4필드 형태를 그대로 재현해 `source_identity_only`로 분류함을 확인.
- **실제 데이터 재분류는 미실행** — §8 재현 명령으로 보호 세션에서 수행한다.

## 6. 코드 계약 공백 보완 (이 브랜치)

- 019386ac 확장 하네스 채택(manifest/verify/논리 지문/폐포) + **compare 신규 구현**. main 원본 하네스와 호환(기존 8건 통과). `commands.py`에 `extract-baseline-compare` 등록, `cli.py` usage — 배선은 추가 전용.
- 보호: 출력·보고서는 `<host>/data/backups` 아래만, 레포 내부·심링크 거부, `'x'` 배타 생성, 읽기전용, manifest 원자 게시. **응답은 건수·해시만**이고 경로(`out` 키)는 응답에 포함하지 않는다. 상세(필드별 차이·짝짓기)는 보호 보고서에만 기록.
- **검수 보완(2026-11-18 독립 검수 차단점 반영):** ① `_compare_binding`이 자체 checksum만 맞는 잘못된 manifest(fingerprint=None·code hash=None·의존성 목록 부재·건수 불일치)를 수용해 `same_input/same_code=true`(None==None)를 보고하던 회귀를 수정 — `verify_capture`에서 공유 도우미 `_validated_manifest`를 추출해 envelope·64hex 형식·의존성 기술 형태·sources를 검사하고 출력 sha256·크기·건수를 실제 파일과 대조해 `MANIFEST_INVALID`/`OUTPUT_MANIFEST_MISMATCH`로 거절한다. 현재 코드 일치 요구는 `verify_capture` 전용으로 유지해 **교차 생산자 버전 비교는 보존**(합성 고정). ② 신규 명령 응답에서 `out` 절대경로 키 제거(응답 키 집합 = 건수+해시 고정). 보호 보고서 저장은 그대로. ③ 2차 검수: 의존성 해시 하나만 바꾸고 bundle digest(`production_python_sha256`)를 그대로 둔 재봉인 manifest가 `same_production_code=true`를 보고하던 내부 불일치를 수정 — `_validated_manifest`가 bundle digest == canonical 의존성 목록 합산 해시(경로 정렬·유일), `python_source_sha256` == extractor 엔트리 해시를 요구해 `MANIFEST_INVALID`로 거절한다. 교차 버전 positive는 header 위조 대신 modules·root·bundle을 일관되게 달리한 정상 사례로 바로잡았다.
- **표적 테스트 52 passed** (기존 8 + manifest 9 + compare 35), 203.36s — 검수 보완 회귀 12건 포함(1차 8 + 2차 4).
- 예방 실행(브리지 7파일): 259 passed, 266 skipped, **53 failed + 3 errors — 전부 `COSTCORE_TEST_BIN is required` 전제조건**(공식 게이트가 빌드·설정하는 Rust 바이너리). 내 3파일만 stash한 **베이스에서 동일 실패 실증**(53 failed / 3 errors, 2.53s, 전제조건 assert 112매치) 후 stash 복원·상태 일치 확인. **내 변경 관련 실패 0.**
- `graphify update .` 완료(28,778 노드 / 79,396 엣지 / 849 커뮤니티; `graphify-out/`은 미추적이며 커밋하지 않음).

## 7. 미검증 · 후속

1. **고정 입력 내용 지문 미기록 + 사본 소실** → 고정 기준의 동일 입력 재검증 불가. 영향: 490건의 입력 기인 vs 변환 기인 귀인 불가; M6 고정 해시 수락은 **기준 변경(별도 소유자 결정)** 또는 원본 회복 전까지 보류.
2. m6 Python 재실행의 생산 SHA 미기록.
3. 12개 폐포 차이 모듈의 행동 영향 미검증.
4. 실제 데이터 compare 미실행(§8 명령, 보호 세션).
5. 중단 캡처 `6af6f9f6…` 스냅샷은 미바인딩 — 필요 시 새 캡처로 바인딩해야 한다.
6. 기준 변경 여부는 SPEC에 따라 **별도 결정**이며 이 작업에서 결정하지 않았다.

## 8. 재현 명령 (보호 세션용)

고정 vs 캡처 비교. 고정 쪽은 manifest가 없는 이전 시대 산출물이라 `base_manifest` 생략; `same_input_fingerprint`·`same_production_code`는 **양쪽 manifest가 있을 때만** 판정된다(없으면 null). `out`은 backups 아래 **새 경로**여야 한다(`OUT_EXISTS`는 덮어쓰기 거부).

```
python -I tools/core_bridge/cli.py extract-baseline-compare
{"base":"D:/WebLedgerHost/data/backups/extractor-baseline-main-20261117/events.json","new":"D:/WebLedgerHost/data/backups/m3-manifest-resume-20261117T133118Z/events.json","new_manifest":"D:/WebLedgerHost/data/backups/extractor-baseline-captures/6f3ab221c0b04924b9aa1e7432965420/manifest.json","host_root":"D:/WebLedgerHost","out":"D:/WebLedgerHost/data/backups/<새-디렉터리>/compare-report.json"}
```

동일 입력 짝(m6 vs 캡처)으로 변환 버전 효과만 분리하려면 `base`를 `m6-extractor-review-20261117/python-events.json`으로 바꿔 같은 형식으로 실행한다(역시 base manifest 없음).

- `verify_capture`는 생산자를 **현재 worktree 코드**에 바인딩하므로 SHA가 다른 과거 캡처 검증은 설계상 실패한다. compare의 `_compare_binding`은 공유 도우미 `_validated_manifest`로 envelope·지문/SHA 형식(64hex)·의존성 기술 형태·sources를 검사하고, 출력 sha256·크기·건수를 실제 파일과 대조하므로 **버전 간 비교가 가능**하다(현재 코드 일치 요구는 verify_capture 전용).
- 보고서 상세에는 거래 식별자가 포함될 수 있으므로 **보호 경로 밖으로 내지 않는다**. Git·보고에는 건수·필드명·해시만 남긴다.
