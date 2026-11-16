# M3 추출기 기준 출력 생산 기록 (2026-11-17)

설계 [`design/m3-core.md`](../../design/m3-core.md) §3.4 / `SPEC.md:333`의 **facts 기준 출력**을 보존 원본에 대해 생산했다. 이 출력은 M6 Rust 추출기 병합의 **고정 기준값**이며, 고객 자료이므로 보호 경로에만 두고 Git에는 생산 명령·Python SHA·건수·해시만 남긴다.

## 생산 결과 (검증됨)

| 항목 | 값 |
| --- | --- |
| 명령 | `python -I tools/core_bridge/cli.py extract-baseline` (JSON Lines stdin) |
| protocol | `core-bridge/1` |
| ok | `true` |
| python_sha | `750e4a65aea5f5603fc04199046d5e64e8a7e45c` (origin/main, PR980 병합) |
| input_digest | `1e9613ebe30aacde13a647de81d9f662d03939d2909764f9621b273f45539f7b` |
| **events 건수** | **7,965** |
| **baseline sha256** | **`a26d446510faabe4cbdfd5d8cf114b0903e6b87b8453fdb3380d529e605cbaf6`** |
| events.json 크기 | 28,637,104 bytes |
| stderr | 0 bytes (오류 없음) |

- **보호 출력 경로:** `D:/WebLedgerHost/data/backups/extractor-baseline-main-20261117/events.json`
- **요청 파일:** 같은 디렉터리 `request.json`
  ```json
  {"ota_evidence": "D:/WebLedgerHost/data/backups/extract-baseline-e2mjubkr/ota-evidence.sqlite", "host_root": "D:/WebLedgerHost", "out": "D:/WebLedgerHost/data/backups/extractor-baseline-main-20261117/events.json"}
  ```
- **응답 봉투:** 같은 디렉터리 `response.json` (위 표의 원본), `stderr.log`(0B).

## 독립 검증

생산 응답의 해시·건수를 디스크 파일과 대조했다(고객 원문 미출력):

- `sha256(events.json 디스크 바이트)` = `a26d4465…` = 응답 보고 해시 → **일치**
- 최상위 키 `["events"]`, `events.length` = 7,965 → 응답 건수 **일치**
- 파일 크기 28,637,104 bytes, `ok=true`, stderr 0B.

## 입력 원본 (보존 원본 동일성)

- 입력은 **라이브가 아닌 완전 스냅샷 사본** `extract-baseline-e2mjubkr/ota-evidence.sqlite`(1,761,828,864 bytes, 2026-11-17 01:44 KST). `is_live`가 false이므로 라이브 DB에 접근하지 않고 사본을 직접 읽었다(운영 무접근).
- 라이브 `D:/WebLedgerHost/data/ota-evidence.sqlite`는 **같은 크기·2026-11-15 23:20 그대로 불변**(회계 후임이 원본 불변 확인). 따라서 스냅샷 == 현재 보존 원본이며, 기준 출력은 현재 보존 원본에 대한 값이다.
- 이전 시도 디렉터리 `extractor-baseline-20261117/`는 `response.json` 0B(중단·출력 없음)로, 성공 생산은 `extractor-baseline-main-20261117`뿐이다.

## 추출기 canonical 보장

- 생산 checkout은 origin/main `750e4a65` detached worktree `C:/AX/cost-m3-baseline`. `python_sha`가 이 SHA로 고정된다.
- `app/ota_payments.py`(`build_ota_payment_events`)는 root·origin/main·worktree에서 **바이트 동일**. 이 함수가 import하는 16개 app 모듈은 PR980이 바꾼 9개 파일에 **없다** → 전이 의존성까지 canonical.
- 도구 변경은 `tools/core_bridge/cli.py`(usage에 `extract-baseline` 추가)·`commands.py`(명령 등록)·신규 `extract_baseline.py`·신규 테스트뿐이며 origin/main 대비 이 4파일 외 차이 없음.

## 안전 경계

- `extract_baseline.capture`는 출력이 레포 내부면 `OUT_INSIDE_REPO`, `<host>/data/backups/` 밖이거나 backups 루트와 같으면 `OUT_NOT_PROTECTED`, 이미 존재하면 `OUT_EXISTS`(open `'x'`)로 거부한다.
- 고객 원문·금액·부호·ID는 보호 경로에만 기록했다. Git·stdout·보고서에 고객 원문 없음. 읽기 전용 생산이며 운영 DB·금융·Google 장부 쓰기 없음.
- 표적 테스트 `tests/test_core_bridge_extract_baseline.py` **8 passed**(이 worktree, main 기준).

## M3 마감 · M6 인수 기준

- 이 기준 출력 생산으로 **M3의 마지막 산출물(§3.4)이 완료**됐다. M3 판정(1차)·연결(2차) 운영 전환은 이미 완료·검증됐다(C1~C3·첫 창 대조 PASS, OTA 7,965/7,965·환불 486/486).
- **M6 Rust 추출기 병합 수락 기준표** = 위 고정값(7,965건, sha256 `a26d4465…`, python_sha `750e4a65`). Rust 추출기 출력은 이 기준과 대조해 병합을 판정한다.
- 전환 후 **매일 Python 대조는 M3 완료 조건이 아니라 Python 폴백 퇴역(M6)까지의 회귀 안전망**이다. 대조 주기 축소는 소유자 정책 결정 전에는 임의로 줄이지 않는다(2026-11-17 현재 미결정). "Rust 전환 완료"는 Python 폐기가 아니며 Board·Worker는 계속 Python 프로세스다.

## 남은 일 (이 기록 범위 밖)

- 이 변경(도구 4파일 + 테스트 + 기록)은 main 기반 브랜치에 커밋한다. **병합·운영 배포는 별도 검수·승인 게이트**이며 이 생산은 읽기 전용이라 운영 반영이 필요 없다.
- 임시 작업 디렉터리(`extract-baseline-*` 스냅샷 사본, 중단된 `extractor-baseline-20261117`)는 기준 출력·기록 보존 확인 후 정리한다. 영구 기록 디렉터리 `extractor-baseline-main-20261117`는 보존한다.
