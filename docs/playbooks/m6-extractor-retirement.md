# OTA 추출기 퇴역 계획 (M6)

- 목적: Python OTA 사건 생성(`build_ota_payment_events` 계열)을 Rust로 옮겨, 기준 대조를 통과한 기능부터 Python을 끈다. 이 문서는 **계획**이며 코드 삭제·이식은 하지 않았다.
- 실행 주체: 구현은 M6 단위 작업(에이전트)이, 운영 전환·기준 재설정은 소유자 결정 뒤 운영 담당이 한다.
- 주기: 1회 계획. 실행 시 단계마다 검증 근거를 [현재 상태](../session_handoff.md)·[운영 기록](../operations.md)에 남긴다.
- 개정 이력: 2026-11-19 최초 작성. 1덩어리 전수 조사(`.local-archive/m6-extractor-retirement-20261118/RESULT-part1.md`, Git 밖) 결과를 요약한다.
- 기준: `origin/main` `40f3bbab`. 아래 줄 번호는 이 SHA의 값이다.

## 0. 현재 사실 (퇴역 전제)

1. **`origin/main`에 Rust 사건 생성은 0건이다.** Rust 크레이트에 `extract` 모듈이 없고, Rust가 이식한 것은 사건 **이후** 단계(사건↔카드 대사 `links/ota/*`·환불 짝·P1 판정·이용기간)뿐이다.
2. 사건 생성 후보 구현은 미병합 브랜치 `m6-rust-extractor-20261117`(base `8db7bbdb`, 커밋 3, main 대비 82커밋 뒤)에만 있고, **그 브랜치도 소스 파서는 Python에 두고** 산림 기간 보강·사건 병합·canonical 쓰기만 Rust로 했다(`tools/core_bridge/extract_sources.py`가 파서 단계 배열을 IPC로 넘긴다).
3. `extract-sources`는 `origin/main`에 없다. 브랜치 diff가 main의 `extract-baseline-compare`를 **삭제**하므로 그대로 병합하면 회귀다(`commands.py`·`cli/src/main.rs`·`docs/session_handoff.md` 충돌 3건).
4. **추출기는 이제 결정적이다**(`3ee31da2` 병합). 캡처 디렉터리 이름이 입력 논리 지문에서 파생하고(`extract_baseline.py:233` `_capture_directory`), `source_lineage_id`는 내용 지문을 쓴다(`app/ota_sources.py:80-99`, `app/ota_payments.py:669-672`). 남은 `uuid4()`는 manifest 임시 파일 이름뿐이다(`extract_baseline.py:215-230`).
5. 다만 **고정 기준 `7,965건 / a26d4465…`는 재검증 불가**다. 결정성 수정 **이전**(python_sha `750e4a65`) 산출물이고 그 입력 사본(`extract-baseline-e2mjubkr`)이 소실됐다. 현재 코드는 `path_`→`content_` 식별자를 써서 같은 입력에서도 다른 바이트를 낸다(합성 재현: 490건·출처식별 필드 4개만 차이 — `docs/agents/artifacts/m3-extractor-repro-20261118.md` §5).
6. `extract`(kind=`sources`)는 운영·테스트 어디서도 호출되지 않는다. `kind=message`는 `tests/test_core_bridge.py:83` 1건뿐이다.
7. **`app/core_writer.py:96,117`이 운영 P1 쓰기 경로에서 `tools.core_bridge.periods`를 직접 import**한다. 브리지 패키지를 지우면 Rust 판정 쓰기가 즉시 깨진다.
8. Rust 다리는 자식에 `WEBLEDGER_LINKS_PRODUCER=python`·`WEBLEDGER_CLASSIFICATION_WRITER=python`을 강제한다(`core/crates/core/src/bridge.rs:36-37`). 재귀 방지 안전장치이며, 다리 자체가 사라질 때만 지운다.

## 1. 퇴역 조건 표

난이도: 낮(합성 입력으로 바이트 대조 가능, 의존 좁음) / 중(양식 다양·실데이터 대조 필요) / 높(입력 전체 구조·쓰기 경로·운영 게이트 결합).

### 1.1 사건 생성 7단계 (생산 순서)

| # | 단계 | 현재 상태 | 이식 난이도 | 검증 방법 |
| --- | --- | --- | --- | --- |
| 1 | 메일 로드·DKIM 정렬·본문 정규화 (`ota_mail.load_messages_from:49`·`authenticated_headers:177`·`body_text:349`) | Python 전용 | 중 | 합성 Gmail JSON·통합 저장소 번들(`iter_mail_bundles`)으로 로드 결과 동일. Rust 테스트는 같은 입력에서 메시지 집합·본문·발송일 동일을 검사 |
| 2 | 메일→결제 사실 (`extract_payment_fact:216`·`ota_mail.extract_mail:399`·`_extract_signed_payment_message:286`) | Python 전용 | **높** | 공급자별 골든(현 `tests/card_pipeline/test_*.py` 사례를 합성으로 고정). 비교는 사건 필드가 아니라 **사건 canonical 바이트**로 한다 |
| 3 | 공급자 메일 파서 8종(`toyoko`·`forest`·`forest_payment`·`airbnb`·`mytrip`·`rakuten`·`airline`·`traveloka`) | Python 전용 | 중~높(각 50~280행) | 파서별 합성 사례 골든 + `_parse_mail_events` 출력 배열 대조. `extract-sources`의 `mail_events`와 같은 순서 |
| 4 | 포털 행 읽기·근거역할/충돌 검사·사건 (`ota_portal._read_records:111`·`ota_payments._portal_events:636`) | Python 전용 | **높** | 통합 저장소 합성 사본에서 `portal_events` 배열 동일. `reservation_identity_attestation`·`source_lineage_ids`(content 지문)까지 필드 동일 |
| 5 | 직접 사실(Trip/Booking/산림 `ota_store.direct_facts:274` → `_trip_reservation_events:427`·`_booking_trip_events:466`·`_forest_portal_events:508`) | Python 전용 | 높(zlib·취소 후 재확인·충돌 판정) | 합성 통합 저장소에서 `trip/booking/forest_*_events` 배열 동일. 취소 우선·충돌 사례를 별도 사례로 고정 |
| 6 | 기간 보강·사건 결합·증명 중복 병합 (`_attach_forest_portal_periods:559`·`_event_semantic_conflict:847`·`_combine_evidence:858`·`_merge_proven_duplicate_payments:964`) | **브랜치에 Rust 구현 있음**(`extract/forest.rs`·`extract/merge.rs`) | 낮 | 브랜치 골든 50건(모두 필드·바이트·개별 SHA) + `--stages` 입력 바이트 대조. 병합 후 `cargo test --workspace`에 포함 |
| 7 | canonical 직렬화·사건 ID 정렬·보호 경로 쓰기 (`write_baseline:71`·`commands.canonical:285`) | **브랜치에 Rust 구현 있음**(`extract.rs`·`cli/src/extract.rs`) | 낮 | 동일 입력에서 출력 파일 **바이트 동일**(`sha256`·크기·건수). 레포 내부·덮어쓰기·운영 DB 별칭 거부 사례 |

참고: 단계 7 뒤의 사건↔카드 대사(`match_ota_payment_events:2424`)는 **이미 Rust가 운영에서 계산**한다(`WEBLEDGER_LINKS_PRODUCER=rust`, `docs/playbooks/core-cutover.md`). 퇴역 대상이 아니라 유지 대상이다.

### 1.2 공급자 파서 8종 (단계 3 세부)

| 파서 | 줄 | 난이도 | 비고 |
| --- | --- | --- | --- |
| `traveloka_mail` | 52 | 낮 | 참조만 생성, `airline_payment_mail`이 의존 |
| `airbnb_mail` | 77 | 낮 | `ota_mail`·`ota_payments` 헬퍼 의존 |
| `mytrip_mail` | 81 | 낮 | 동일 |
| `ota_rakuten_mail` | 129 | 중 | `_foreign_decimal` 의존 |
| `airline_payment_mail` | 159 | 중 | 제주 결제·취소 참조, `traveloka` 의존 |
| `forest_payment_mail` | 114 | 중 | 산림 PG 영수증 증명(`authorization_scheme`) |
| `forest_mail` | 191 | 높 | 예약 관측 + `ota_store.index_reservation_observations` |
| `toyoko_mail` | 280 | **높** | `booking_evidence` 의존, 분기별 숙박 계약 |

### 1.3 사건 밖 Python 의존 (같은 시기에 정리해야 하는 결합)

| 항목 | 현재 | 조건 | 난이도 | 검증 |
| --- | --- | --- | --- | --- |
| `core_writer`의 `periods` 브리지 의존 (`app/core_writer.py:96,117`) | 운영 P1 쓰기 경로가 브리지 패키지 import | **`periods`의 키 상수(FACT/EVENT/CARD_KEYS)와 `evidence_from_snapshot`을 브리지 밖 순수 모듈로 옮긴 뒤** 브리지 패키지 삭제 가능 | 낮 | `costcore apply`와 Python `apply`의 대상·값 동일 재확인(기존 `tests/test_core_writer.py`, 사본 7,336건 대조 방식) |
| `PRODUCER`/`WRITER` 강제 (`bridge.rs:36-37`) | Rust 다리 자식 재귀 방지 | **Rust가 Python 다리를 더 이상 부르지 않을 때만** 제거 | 낮 | 다리 호출 지점 0을 `git grep`로 확인, 그림자 실행 1회 PASS |
| 브리지 명령 잔여분 | `plan`·`links`·`snapshot`·`facts`·`classify`·`trips`·`periods`·`ota-input`·`extract`·`extract-baseline(-compare)` | 각 명령의 마지막 호출자가 사라진 순서대로 제거. `snapshot`·`facts`는 테스트만 호출, `extract` kind=sources는 호출 0 | 낮~중 | 명령별 호출 지점 0 + 골든 재생성 무변동 |
| 사건 소비 모듈 | `ota_core_projection`·`ota_queue_projection`·`p2_case`·`webapp/ota_payment_review` | **삭제 대상 아님** — 사건을 입력으로 받는 화면·P2·투영은 Rust 이식 후에도 남는다(입력 생산자만 바뀐다) | — | — |

## 2. 퇴역 순서 (5단계)

각 단계는 **이전 단계 검증 통과가 다음 단계의 전제**다. 어느 단계든 실패하면 그 단계만 되돌린다.

1. **결합 해소(선행, 코드 변경 없이 결정만):** `core_writer`의 `periods` 직접 import를 계획 확정대로 분리할지 결정하고, 분리 단위를 M6 첫 PR로 잡는다. 동시에 `commands.canonical`을 import하는 도구(`tools/compact_ota_evidence.py:186`, `tools/quarter_review/eval_cases.py:355`)의 대체 위치를 정한다. **검증:** 분리 후 `tests/test_core_writer.py`·`tests/test_core_rejudge.py`·`tests/test_core_periods.py` 통과. **롤백:** 변경 PR 되돌리기(브리지는 아직 존재하므로 기능 영향 없음).
2. **고정 기준 재설정(소유자 결정 필요):** §3 결정 1을 받은 뒤, 현재 결정적 코드로 보호 스냅샷을 다시 만들어 **새 고정 기준(건수·sha256·manifest 바인딩·논리 지문)**을 생산한다. 구 기준 `a26d4465…`는 "재검증 불가"로 기록하고 비교의 base로 쓰지 않는다. **검증:** 같은 입력 재실행 바이트 동일(결정성), `verify_capture` 통과. **롤백:** 새 기준 폐기하고 이전 기준을 "근거 보존"으로만 남긴다(운영 영향 없음).
3. **Rust 사건 생성 이식(단위별):** (a) `m6-rust-extractor-20261117`을 최신 main에 **재적용**(충돌 3건 해소·`extract-baseline-compare` 보존·`extract-sources`는 추가 전용) → (b) 난이도 낮은 파서부터 순차 이식(`traveloka`→`airbnb`→`mytrip`→`rakuten`→`airline`→`forest_payment`→`forest`→`toyoko`) → (c) 포털 사건·collapse → (d) 직접 사실 → (e) 메일 핵심(`extract_mail`·`extract_payment_fact`). 각 단위는 자기 슬라이스에서 새 기준과 **바이트 동일**해야 병합한다. **검증:** 단위별 골든 + 새 기준 대조(보호 경로, 해시·건수만) + `cargo fmt/clippy/test` + `python tools/run_quality_checks.py --base origin/main --run`. **롤백:** 단위 PR 되돌리기. 아직 남은 Python 파서는 브리지로 계속 공급되므로 기능 영향 없음.
4. **운영 전환(그림자):** 스위치를 단위별로 켠다(예: `WEBLEDGER_EXTRACT_PRODUCER=rust` 신설은 설계 결정 사항, 기존 producer 스위치와 독립). 켠 뒤 매일 `costcore extract` + `extract-baseline-compare`로 **보호 경로에서 건수·해시만** 대조하고, 목록 밖 차이가 1건이라도 나오면 즉시 스위치를 되돌린다(Python 기본값). 다른 세션·배포 창 조율은 `docs/playbooks/core-cutover.md`와 같은 규칙을 따른다. **검증:** 일일 대조 0차이 창 N일(소유자 결정), 수동 교정·환불 짝·기록 경로 불변. **롤백:** 스위치 제거·재시작. 사건은 저장되지 않으므로 데이터 복구가 필요 없다(연결·판정과 같은 성질).
5. **Python 삭제:** 순서는 ① 브리지 명령 `extract`(kind=sources) → ② 각 공급자 파서·`ota_portal`·`ota_mail` 파싱 → ③ `extract_baseline`·`ota_input`·`period_shadow` 하네스(새 기준·골든이 Rust 쪽에 자리 잡은 뒤) → ④ `PRODUCER`/`WRITER` 강제. **금지:** `ota_payments`의 대사·관계·추론(이미 Rust)과 사건 소비 투영은 이 순서에 넣지 않는다. **검증:** 삭제 전후 `cargo test --workspace`·영향 검사·그림자 PASS, 호출 지점 0 확인. **롤백:** 삭제 커밋 되돌리기(브리지 파일은 Git 이력에 남는다).

## 3. 선행 결정 2건 (소유자 결정)

1. **고정 기준 재설정.** 현 기준 `7,965건 / a26d4465…`는 재검증 불가다. "기준을 새로 생산해 교체"할지, "구 기준은 근거 보존·비교 대상 제외"로 남길지 결정이 필요하다. 결정 없이는 3단계 수락 기준이 없다. (SPEC §11.1 M3-3 말단: 기준 변경은 별도 결정)
2. **`core_writer` 브리지 제거를 1순위로.** 운영 P1 쓰기 경로가 브리지 패키지에 의존하는 한 "브리지 제거"는 불가능하다. `periods` 키 상수·`evidence_from_snapshot`을 브리지 밖으로 옮기는 것을 M6 첫 PR로 확정한다.

## 4. 위험 목록 (퇴역 시 깨질 수 있는 것)

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| `mail-collect` 작업(Worker, `tools/install_webledger_worker.ps1:85`) | `app/mail_collect.py:135-142`가 `OtaStore.import_mail` → `ota_payments.extract_payment_fact`를 부른다. 파서 제거 시 수집이 실패 | 파서별 이식 전까지 수집 경로를 그대로 두고, 제거 단계에서 Worker 테스트(`tests/card_pipeline/test_mail_collect.py`·`test_mail_import_skip.py`)를 게이트로 |
| 운영 6단계 대조 절차(`docs/playbooks/core-cutover.md:145-160`) | `ota-input` 브리지가 사라지면 OTA C1 측정 수단이 없어진다 | 사건 이식 후 `costcore extract`가 같은 입력을 만들도록 바꾸고, 절차서 개정 전에는 `ota-input`을 지우지 않는다 |
| 전환 사전검사 `tools/core_cutover_preflight.py:182` | `shadow-links --ota-input` 입력 파일 의존 | 위와 같음 |
| P2 입력 조립 `app/p2_case.py:475-526` | 메일·포털을 직접 읽고 `extract_payment_fact` 호출 | P2는 사건 생성 뒤 단계다. 메일 파서 제거 시 P2 근거 문맥도 Rust로 옮기거나 P2 범위를 재정의(3단계 이후 별도 단위) |
| 화면 캐시 무효화 `webapp/ota_catalog.py:433` `_LOGIC_FILES` | 파일 목록에 추출기 모듈이 하드코딩 — 경로 변경 시 인덱스 캐시가 옛 코드로 남는다 | 삭제·이동 PR에서 `_LOGIC_FILES`를 함께 고치고 `webapp/tests/test_ota_catalog.py` 확인 |
| 브리지 자식 환경 강제(`bridge.rs:36-37`) | 조기 제거 시 `costcore`↔Python 무한 재귀 | 마지막 단계에서만 제거, 전후 그림자 1회 |
| Rust 의존 추가 | `ota_store`가 zlib 압축(`zlib.compress`) 저장 → Rust 직접 사실 이식 시 압축 해제가 필요(현 크레이트에 zlib·base64 없음) | 단계 5 이식 전에 의존·바이트 호환을 결정(합성 저장소 왕복 검사) |
| 부분 이식의 조용한 차이 | Rust 다수·Python 소수 공존 시 서로 다른 바이트 | 스위치는 단위별, 한 실행 안에서 생산자를 섞지 않는다. 차이는 새 기준 대조로만 판정 |
| 기준 하네스 자체 | `extract_baseline`·`ota_input`이 Python이라 "Python 퇴역"과 별개로 남는다 | 하네스는 마지막(5단계 ③). 그 전까지 `extract-baseline-compare`(main 기능) 보존 |
| CI 결제 한도 | Rust·Python 게이트가 시작 전 차단될 수 있다 | 지침의 독립 검수 예외(다른 Claude 세션) 적용, 실제 실패는 면제하지 않는다 |

## 5. 하지 않는 것

- 이 문서로 코드·테스트·설정을 바꾸지 않는다. 삭제·이식은 단계별 PR에서 한다.
- 사건 소비 모듈(`ota_core_projection`·`ota_queue_projection`·`webapp/ota_payment_review`·`app/p2_case`)을 "추출기"로 묶어 함께 지우지 않는다.
- 사건↔카드 대사·환불 짝·P1 판정·이용기간을 이 계획의 삭제 대상으로 넣지 않는다(이미 Rust가 계산한다).
- 고정 기준을 소유자 결정 없이 교체하지 않는다.
- 운영 DB·보호 경로 원문·운영 포트를 계획·검증에 쓰지 않는다.
