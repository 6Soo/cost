# core (M3)

COST 판정 코어의 Rust 작업공간. 설계: `docs/design/m3-core.md` (§6).

## 게이트

```powershell
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
$env:CARGO_TARGET_DIR = "D:\cargo-target\$((Get-Item ..).Name)"   # 작업 폴더별 빌드 폴더(병렬 worktree가 서로 잠그지 않게). core/target/ 에 쌓지 않는다.
cd core
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```
- `python tools/run_quality_checks.py --base origin/main --run` 이 `core/` 변경 시 위 세 명령을 실행한다. Windows에서 `CARGO_TARGET_DIR` 이 없고 D: 드라이브가 있으면 `D:\cargo-target\<작업 폴더 이름>` 을 쓴다. cargo가 없으면 `CARGO_NOT_FOUND` 로 실패한다.
- 도구 모음은 `rust-toolchain.toml` 로 고정한다. 외부 크레이트는 소유자 승인 7개(rusqlite bundled, serde, serde_json, thiserror, regex, sha2, time)와 개발용 proptest만 쓴다.
- `core.sqlite` 는 `D:/WebLedgerHost/data/core.sqlite` (백업·7일 보존 대상). 이 작업공간은 서버를 띄우지 않고 운영 포트 8751·8752·8790을 쓰지 않는다.

## 구성 (설계 §6.1, D-12)

- `crates/core` (`cost-core`, 라이브러리): 모듈 `domain`(판정 타입·불변식), `dates`(날짜·완료 기간·열린 범위, `OpenScope` 발급), `trips`(여행 귀속 추론, U8), `region`(국가·지역·온라인·후쿠타케 판정, rules·trips 공용), `plan`(P1 계획 조립·보호 순서·이력 복원·digest, U9), `links::refund`(환불 짝 도출·환불 묶음 판정·`RefundGroup` 발급, U12; 골든 `refund_pairing.jsonl`·`refund_groups.jsonl`, 시험은 모듈 안 `tests.rs`), `links::ota`(OTA↔카드 후보 탐색·쌍 검사 U13, M:N 배정·점유·고정 그룹 U14; 골든 `ota_links.jsonl`·`ota_mn.jsonl`, 시험 `tests/ota_links_golden.rs`), `RefundGroupId::for_original`(환불 묶음 ID 조립 한 곳)·`Refunds::plan_links`(U12 연결 → `plan::Links` 어댑터). 운영 코드는 `shadow` 밖에 있다: `guard`(비공개 파일 경로 보호), `known_diffs`(known-diffs.txt 줄 형식), `links::refund` 어댑터(원행 → 짝 입력·짝 결과 JSON). `shadow`는 A·B·C 비교만 한다.
- `crates/cli` (`costcore`, 실행 파일). 명령: `shadow`·`shadow-links`·`links`·`plan`·`apply`·`rejudge`·`periods`·`migrate`. `costcore migrate --core PATH`는 core.sqlite를 없으면 만들고 최신 스키마까지 이관한다(board 미접근, 멱등, 더 높은 버전은 `CORE_SCHEMA_MISMATCH`).
- 봉인 타입(`RefundGroup`·`OpenScope`·`TripId`·`Subject`)은 생성자가 `pub(crate)`이거나 없어 크레이트 밖에서 만들 수 없다(문서 테스트 `compile_fail` 4개).
- 합성 골든: `golden/synthetic/dates.jsonl`(생산기 `tools/core_dates_golden.py`), 시험 `crates/core/tests/dates_golden.rs`. `golden/synthetic/trips.jsonl`(`python -m tools.core_bridge.golden write`), 시험 `crates/core/tests/trips_golden.rs`. `golden/synthetic/plan.jsonl`(같은 도구, 입력의 `links`는 Python 환불 짝 연결 결과), 시험 `crates/core/tests/plan_golden.rs`(알려진 차이는 `known-diffs.txt`).
- OTA 후보 골든: `golden/synthetic/ota_candidates.jsonl`(Python `_eligible_cards`·`pair_check`·`search_card_candidates` 직접 호출, `python -m tools.core_bridge.golden write`), 시험 `crates/core/tests/ota_golden.rs`(`ota_links.jsonl` 중 후보 단계로 결정되는 사례도 함께 비교).
- 이용기간(U9a, 설계 §2.7): `crates/core`의 `period`(순수 규칙, `plan`·`store`를 모른다)·`digest`, `store::decisions`(저장·재판정 선택, 쓰기 호출자는 U11 적용 경로 하나). 골든 `golden/synthetic/period.jsonl`(생산기가 Python `verified_period_for` 직접 호출), 시험 `crates/core/tests/period_golden.rs`. `costcore rejudge --changed`는 근거 digest가 바뀐 거래만 고르고(쓰지 않음), `costcore periods`와 `python -m tools.core_bridge.period_shadow`가 운영 사본 그림자 비교를 한다.
