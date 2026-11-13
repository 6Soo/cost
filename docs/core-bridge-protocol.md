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

실패 시 `detail`에는 예외 종류만 담는다(원문이 섞일 수 있어 메시지는 싣지 않는다). 오류 코드: `COMMAND_UNKNOWN`, `REQUEST_NOT_JSON`, `DB_OR_SCENARIO_REQUIRED`, `DB_REQUIRED`, `DB_NOT_FOUND`, `HOST_OR_REPORT_REQUIRED`, `LINKS_KIND_INVALID`, `EXTRACT_KIND_INVALID`, `PLAN_WROTE_DATA`, `COMMAND_FAILED`.

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
| `links` | `kind:"ota"`, `events`, `transactions`, 선택 `existing_links`·`rules`·`frozen_groups` | `results`(`app.ota_payments.match_ota_payment_events`) |
| `plan` | DB 또는 시나리오, 선택 `transaction_ids`·`reconsider`·`evidence`·`nets` | `app.automatic_classification.plan` 결과(`digest`, `targets`, `summary`). 적용하지 않는다 |
| `classify` | `cases`: `transaction`, `rules`, `prior_decision`, `trip_ids`, `residual_policy` | `verdicts`(`app.classify.classify_transaction`) |
| `extract` | `kind:"message"` + `messages`(Gmail 형식) | `facts`(`extract_payment_fact`, 읽지 못하면 null) |
| `extract` | `kind:"sources"` + `sources`(등록 원천) | `events`(`build_ota_payment_events`) |

`extract` 결과(설계 §3.4의 facts 기준 출력)는 고객 자료이므로 보호 경로에만 저장하고 Git에는 올리지 않는다.

## 합성 골든

`core/golden/synthetic/{classify,plan,refund_pairing,ota_links}.jsonl`과 `manifest.json`. 한 줄이 한 사례이며 `{case_id, area, command, note, input, expected}`다. `input`을 위 명령에 그대로 넣으면 `result`가 `expected`와 같아야 한다. 기대값은 Python 출력이며 손으로 고치지 않는다.

- 재생성: `python -m tools.core_bridge.golden write`, 드리프트 확인: `... check`.
- 골든에는 `python_sha`를 넣지 않는다(커밋마다 바뀐다). Python 판정 코드가 바뀐 PR이 골든을 다시 만들고 PR에 차이 유형을 적는다.
- 고객 자료 차단: `tools/core_bridge/golden_guard.py`가 허용 목록 방식으로 검사한다. 입력의 모든 키와 값이 목록에 있어야 하고(가맹점은 `SYN …` 합성명·코드에 이미 있는 공개 상호, 카드 끝자리·발급사·승인번호·ID는 고정 형식), 기대 출력과 메모는 긴 숫자열·메일·링크를 거부한다.
