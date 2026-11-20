# 코어 다리(core bridge) 프로토콜

M3 Rust 코어가 현 Python 판정 코드를 읽기 전용으로 부르는 JSON 입출력 규약이다(설계 U4, `docs/design/m3-core.md` §3.3·§3.4·§4.4). 다리는 쓰지 않는다. 운영 DB는 `mode=ro`와 `PRAGMA query_only=ON`으로만 연다.

## 실행

```
python -I tools/core_bridge/cli.py <명령>        # -I에서는 작업 폴더가 경로에 없어 cli.py가 레포 루트를 스스로 추가한다
python -m tools.core_bridge <명령>               # -I 없이 레포 루트에서도 가능
```

표준 입력에 요청을 한 줄에 하나씩(JSON Lines) 주면 요청마다 응답 한 줄을 표준 출력에 낸다. 하나라도 실패하면 종료 코드는 1이다.

## 응답 봉투

```json
{"protocol":"core-bridge/1","command":"plan","python_sha":"<git HEAD>","input_digest":"<요청의 정렬 직렬화 sha256>",
 "ok":true,"result":{...}}
{"protocol":"core-bridge/1","command":"plan","python_sha":"...","input_digest":"...","ok":false,
 "error":{"code":"DB_NOT_FOUND","detail":""}}
```

실패 시 `detail`에는 예외 종류만 담는다(원문이 섞일 수 있어 메시지는 싣지 않는다). `python_sha`를 읽지 못하면(`DEPLOYED_COMMIT`도 `git rev-parse`도 없음) 응답은 `PYTHON_SHA_UNAVAILABLE`이다(호출자가 빈 SHA로 진행하지 않게 한다).

오류 코드는 세 묶음이다.

- **모든 명령에 공통:** `COMMAND_UNKNOWN`, `REQUEST_NOT_JSON`, `PYTHON_SHA_UNAVAILABLE`, `COMMAND_FAILED`(예외 종류만 `detail`로).
- **명령별 입력 검사:** `DB_OR_SCENARIO_REQUIRED`(DB·시나리오 둘 다 없음), `DB_REQUIRED`(`snapshot`), `DB_NOT_FOUND`, `HOST_OR_REPORT_REQUIRED`(`facts`), `LINKS_KIND_INVALID`, `TRIPS_OP_INVALID`, `PLAN_WROTE_DATA`(`plan`이 읽기 전용 DB를 썼다), `EXTRACT_KIND_INVALID`.
- **보호 경로 파일 캡처(`ota-input`·`extract-baseline`·`extract-baseline-compare`):** `<KEY>_REQUIRED`(누락된 입력 키마다, 예: `OTA_EVIDENCE_REQUIRED`·`OUT_REQUIRED`·`DB_REQUIRED`, `extract-baseline-compare`의 `BASE_REQUIRED`·`NEW_REQUIRED`), `DB_IS_LIVE`, `OUT_INSIDE_REPO`, `OUT_NOT_PROTECTED`, `OUT_EXISTS`, `PATH_INSIDE_REPO`, `PATH_NOT_PROTECTED`, `FILE_NOT_FOUND`, `MANIFEST_NOT_PROTECTED`, `MANIFEST_INVALID`, `FORMAT_INVALID`, `OUTPUT_MANIFEST_MISMATCH`, `MULTI_DATABASE_FINGERPRINT_UNSUPPORTED`(등록된 DB 경로가 캡처한 파일과 다른 파일일 때. 하드 링크·`\\?\` 별칭처럼 같은 파일을 가리키는 표기는 통과한다).

## 입력의 공통 규칙

DB를 읽는 명령(`facts`·`links` 환불·`plan`)은 둘 중 하나를 받는다.

- `"db": "<경로>"` 실제 DB를 읽기 전용으로 연다. 호출자(보호 경로 실행자)가 책임진다.
- `"scenario": {...}` 합성 시나리오로 임시 DB를 만든다(골든·테스트용). 키: `rows`(transactions 열 일부), `holds`, `exclusions`, `decisions`, `overrides`, `ledger`, `boards`.

`"trips"`가 없으면 `trip_tabs`의 삭제되지 않은 행을 쓴다.

## 명령

| 명령 | 요청 | `result` |
| --- | --- | --- |
| `snapshot` | `db`, 선택 `completed_evidence` | `projection`(P2 범위 투영 `tools/p2_batch/scope.read_projection` 결과, `read_seconds` 제외), `counts` |
| `facts` | DB 또는 시나리오, `report`(합성 보고서) 또는 `host`(등록 원천이 있는 운영 폴더) | `evidence`(거래별 예약 이용기간 근거), `summary`(건수) |
| `links` | `kind:"refund"` + DB·시나리오, 선택 `transaction_ids` | `links`, `groups`, `group_exclusions`, `held`, `review_originals` (`app/partial_refund.py`) |
| `links` | `kind:"refund_group"` + DB·시나리오, `entries`(`transaction_id`와 선택 `item`·`description`·`display_tab_id`·`trip_id`·`blocked`), 선택 `batch_id`·`extension`·`valid_trips`·`valid_tabs` | 묶음 판정(`app/ledger.py` `_ready_rows`·`_apply_refund_pairs`·`_check_refund_groups`·`scope_group`): `selected`, `entries`, `group_check`, `links`, `group_exclusions`, `scope`. 적용하지 않는다 |
| `links` | `kind:"ota"`, `events`, `transactions`, 선택 `existing_links`·`rules`·`frozen_groups` | `results`(`app.ota_payments.match_ota_payment_events`) |
| `candidates` | `events`, `transactions`, 선택 `rules`·`existing_links` | `events`별 `ota_event_id`, `eligible`(후보 카드 ID), `pair_check`(카드별 쌍 검사 코드), `search`(`search_card_candidates`). 연결을 만들지 않는다(U13) |
| `plan` | DB 또는 시나리오, 선택 `transaction_ids`·`reconsider`·`evidence`·`nets` | `app.automatic_classification.plan` 결과(`digest`, `targets`, `summary`). 적용하지 않는다 |
| `classify` | `cases`: `transaction`, `rules`, `prior_decision`, `trip_ids`, `residual_policy` | `verdicts`(`app.classify.classify_transaction`) |
| `trips` | `op` 하나 + 그 op의 입력. `infer_trip`(`row`, `trips`, 선택 `nets`·`reconsider`·`completed_evidence`) → `trip_id`·`basis`; `candidates`(`row`, `trips`, 선택 `nets`) → `candidates`; `stay_trip`(`trips`, `check_in`, `check_out`, 선택 `service`·`nets`) → `tab_id`; `booking_trip`(`row`, `trips`, `check_in`, `check_out`, 선택 `service`·`target_code`·`nets`) → `tab_id`; `card3820`(`row`, `trips`) → `policy`; `infer_item`(`row`) → `item`·`basis` | 해당 op의 결과(`app.automatic_classification`·`reconciliation`·`webapp.card_trip_authority`) |
| `periods` | `data`(OTA 대조 결과), `manual`(수동 교정 `row_id`), 선택 `rows`·`inference`·`p2` | `facts`(거래별 후보 목록). `rows`가 있으면 `verified`, `inference`가 있으면 `inferred`·`flights`·(rows가 있으면) `found` |
| `extract` | `kind:"message"` + `messages`(Gmail 형식) | `facts`(`extract_payment_fact`, 읽지 못하면 null) |
| `extract` | `kind:"sources"` + `sources`(등록 원천) | `events`(`build_ota_payment_events`) |
| `ota-input` | `db`·`ota_evidence`·`review_db`·`out`(보호 경로), 선택 `host_root` | 풀이기 입력 파일을 `out`에 쓰고 건수·`sha256`만 돌려준다. 실운영 파일은 `DB_IS_LIVE`로 거부 |
| `extract-baseline` | `ota_evidence`·`out`(보호 경로), 선택 `host_root` | 추출기 기준 출력 파일과 manifest를 `out`에 쓰고 `events`·`sha256`만 돌려준다 |
| `extract-baseline-compare` | `base`·`new`·`out`(보호 경로), 선택 `base_manifest`·`new_manifest`·`host_root` | 두 기준 출력의 내용 차이와 출처 식별 차이를 나눈 보고서를 `out`에 쓰고 건수만 돌려준다 |
| `extract-sources` | `ota_evidence`(명시 SQLite 사본), 선택 `host_root` | 라이브 DB를 거부한다. 사본의 논리 지문으로 출처를 고정하고 중간 파서 결과를 Rust 추출기의 비공개 프로세스 응답으로만 전달한다 |

`trips`의 `trips` 인자는 브리지 DB 경로와 같은 모양(`tab_id`와 `trip_id`를 함께 가진 행)이어야 한다. `stay_trip`·`booking_trip`은 `tab_id`를 읽는다.

`extract` 결과(설계 §3.4의 facts 기준 출력)는 고객 자료이므로 보호 경로에만 저장하고 Git에는 올리지 않는다. `ota-input`·`extract-baseline`·`extract-baseline-compare`도 같은 이유로 `out`이 레포 밖 보호 경로여야 하고, 이미 있는 파일은 덮어쓰지 않는다(`OUT_EXISTS`).

## 합성 골든

`core/golden/synthetic/` 아래 `classify`, `plan`, `refund_pairing`, `refund_groups`, `ota_links`, `ota_mn`, `ota_candidates`, `trips`, `period` 9개 영역의 `.jsonl`과 `manifest.json`(`tools/core_bridge/golden.py`의 `AREAS`). 한 줄이 한 사례이며 `{case_id, area, command, note, input, expected}`다. `input`을 위 명령에 그대로 넣으면 `result`가 `expected`와 같아야 한다. 기대값은 Python 출력이며 손으로 고치지 않는다.

- 재생성: `python -m tools.core_bridge.golden write`, 드리프트 확인: `... check`.
- 골든에는 `python_sha`를 넣지 않는다(커밋마다 바뀐다). Python 판정 코드가 바뀐 PR이 골든을 다시 만들고 PR에 차이 유형을 적는다.
- 고객 자료 차단: `tools/core_bridge/golden_guard.py`가 허용 목록 방식으로 검사한다. 입력의 모든 키와 값이 목록에 있어야 하고(가맹점은 `SYN …` 합성명·코드에 이미 있는 공개 상호, 카드 끝자리·발급사·승인번호·ID는 고정 형식), 기대 출력과 메모는 긴 숫자열·메일·링크를 거부한다.
