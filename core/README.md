# core (M3)

COST 판정 코어의 Rust 작업공간. 설계: `docs/design/m3-core.md` (§6).

## 게이트

```powershell
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
$env:CARGO_TARGET_DIR = "D:\cargo-target\cost"   # C 드라이브 여유가 적다. core/target/ 에 쌓지 않는다.
cd core
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```n
- `python tools/run_quality_checks.py --base origin/main --run` 이 `core/` 변경 시 위 세 명령을 실행한다. Windows에서 `CARGO_TARGET_DIR` 이 없고 D: 드라이브가 있으면 `D:\cargo-target\cost` 를 쓴다. cargo가 없으면 `CARGO_NOT_FOUND` 로 실패한다.
- 도구 모음은 `rust-toolchain.toml` 로 고정한다. 외부 크레이트는 소유자 승인 7개(rusqlite bundled, serde, serde_json, thiserror, regex, sha2, time)와 개발용 proptest만 쓴다.
- `core.sqlite` 는 `D:/WebLedgerHost/data/core.sqlite` (백업·7일 보존 대상). 이 작업공간은 서버를 띄우지 않고 운영 포트 8751·8752·8790을 쓰지 않는다.
