# 산출물·해시 목록

작성 기준: `2026-08-11`

## 안정 보관 위치

`C:/AX/cost-handoff-archive/2026-08-11/`

이 위치는 저장소 밖의 로컬 보관 위치다. 카드 원장·후보 DB가 포함될 수 있으므로
Git에 커밋하지 않는다.

## Phase 1

| 종류 | 원본 경로 | 안정 보관 경로 | SHA256 |
|---|---|---|---|
| gate report | `/tmp/cost-gate-phase1-20260811-01/artifacts/233396cde3454c2895ce46b90852b7ab-81db04393333/gate_report.json` | `C:/AX/cost-handoff-archive/2026-08-11/artifacts/phase1/gate_report.json` | `2b05c0ac9f50ef677d568a907e900fe735118e1ca7f602645a1f3028dbf150e5` |
| blocker manifest | `/tmp/cost-gate-phase1-20260811-01/artifacts/233396cde3454c2895ce46b90852b7ab-81db04393333/blocker_manifest.json` | `C:/AX/cost-handoff-archive/2026-08-11/artifacts/phase1/blocker_manifest.json` | `37325311ba0b76ad789f0580b8c63a7c272b2d8fbf3b0b7eb0a5bc9b5b4af319` |
| question queue | `/tmp/cost-gate-phase1-20260811-01/artifacts/233396cde3454c2895ce46b90852b7ab-81db04393333/question_queue.json` | `C:/AX/cost-handoff-archive/2026-08-11/artifacts/phase1/question_queue.json` | `e66e3d11d227b058aea27e64d389af5befe37d2ab696f34f2b1c1d58282d4e85` |
| candidate DB | `/tmp/cost-gate-phase1-20260811-01/.candidate.db-candidate-b96p746p.db` | `C:/AX/cost-handoff-archive/2026-08-11/databases/phase1.candidate.db` | `7a3079005fb6c3355cfadf9dc04dd8e6f4535112ba5e627adc107982a26e4f34` |

## Baseline

| 종류 | 원본 경로 | 안정 보관 경로 | SHA256 |
|---|---|---|---|
| gate report | `/tmp/cost-gate-10-20260811d/artifacts/3c683ffcf8da4021ad6bf7e740548d55-f6a8282d0c00/gate_report.json` | `C:/AX/cost-handoff-archive/2026-08-11/artifacts/baseline/gate_report.json` | `77ca7a7c369d8997d7d832c2767ed2d1c9a98e1a627da43b0c1ce5d7f90870e9` |
| blocker manifest | `/tmp/cost-gate-10-20260811d/artifacts/3c683ffcf8da4021ad6bf7e740548d55-f6a8282d0c00/blocker_manifest.json` | `C:/AX/cost-handoff-archive/2026-08-11/artifacts/baseline/blocker_manifest.json` | `936e506b576d1408c1a69a57db85e8fc777b805215583f94b3f551a77f27850d` |
| question queue | `/tmp/cost-gate-10-20260811d/artifacts/3c683ffcf8da4021ad6bf7e740548d55-f6a8282d0c00/question_queue.json` | `C:/AX/cost-handoff-archive/2026-08-11/artifacts/baseline/question_queue.json` | `01e16e80dc8907f9d5a52f71d7642c34a1998a06b3150df4db5ad5dbb19dc0f1` |
| candidate DB | `/tmp/cost-gate-10-20260811d/.candidate.db-candidate-3mzyt51o.db` | `C:/AX/cost-handoff-archive/2026-08-11/databases/baseline.candidate.db` | `112870a4c3f2fe309698b91709b79154caef5d4716d4a2def50b51318f6b8791` |

## 저장소 snapshot

- branch: `codex/p07-canonical-cutover-candidate`
- HEAD: `243fb8240eddbbcd71133c0788f8561064c5a2e4`
- tracked modified: 41
- untracked: 40 (인계 패키지 8개 파일 포함)
- full status: `C:/AX/cost-handoff-archive/2026-08-11/repository/git-status.txt`
- tracked diff: `C:/AX/cost-handoff-archive/2026-08-11/repository/tracked.diff`
- ledger file hash manifest: `C:/AX/cost-handoff-archive/2026-08-11/repository/files.sha256`
- full worktree file hash manifest (handoff folder excluded to avoid recursion): `C:/AX/cost-handoff-archive/2026-08-11/repository/worktree-files.sha256`
- full worktree manifest SHA256: `31c9dc1cd8ad02c32f3844954c24f0dae72080fe58a0305639b75907752701d2`
- all handoff file hashes: `C:/AX/cost-handoff-archive/2026-08-11/repository/handoff-files.sha256`
- archive manifest: `C:/AX/cost-handoff-archive/2026-08-11/manifest.sha256`
- archive manifest SHA256: `e366a72d80520afcdfb3421ead87dc8ac78586c2497d98bf92abafbd93a14bcf`

## 채팅 원문

- source thread: `[THREAD_ID_REDACTED]`
- export 범위: 최초 7 pages / 66 turns + 이후 표시 continuation
- 저장소 비식별본: `C:/AX/cost/docs/handoff/2026-08-11/00_chat_transcript.md`
- 비식별본 SHA256: `1fda4ecff6b17646f2e17bebe1aa418d33ae133d21644aa72ea32d6fdf3f686d`
- 최초 보호 원문 snapshot: `C:/AX/cost-handoff-archive/2026-08-11/chat/00_chat_transcript.raw.md`
- 최초 보호 원문 snapshot SHA256: `ef7c69ab5ad74b5ecfddcbab400f5129a7c1a3a8ae79cea91cf5ee86601a11d8`
- continuation 보호 원문: `C:/AX/cost-handoff-archive/2026-08-11/chat/00_chat_transcript.continuation.raw.md`
- continuation 보호 원문 SHA256: `74b259d6ca9da7203fe4cad18f22d17e6dd23512f0860ae415add3c45978de74`
- 두 보호 파일은 각각 생성 시점의 표시 대화를 보존하며, 첫 snapshot과 continuation을 같은 파일인 것처럼 표시하지 않는다.
- 보호 원문 권한: `0600`
- 저장소본은 이메일·장문 숫자 식별자·메시지 ID를 `[..._REDACTED]`로 치환했다.
- 내부 reasoning은 두 파일 모두 보존하지 않는다. 이는 사용자에게 표시되지 않는 정보이기 때문이다.
- 긴 도구 출력은 이 manifest의 별도 로그·산출물 경로로 보존한다.

## 검토 원문·재현본

| 구분 | 보호 경로 | 결과 | SHA256 |
|---|---|---|---|
| Kimi 이전 visible event log | C:/AX/cost-handoff-archive/2026-08-11/reviewers/kimi-session_485d98b6-f3ac-479e-b963-25a37a2c8646-visible.jsonl | Kimi 모델 선택 실패·재시작 포함 | a8b38188ca1b2e2e27c7bee7a7d22c83129e5be8f607dff15a822cc36b134620 |
| Kimi 최종 visible event log | C:/AX/cost-handoff-archive/2026-08-11/reviewers/kimi-session_e441a4af-05d6-4a85-8743-64000580ca81-visible.jsonl | KIMI_VERDICT: FAIL | cab3f9802dac7aed2c83807d2e7c1368cc35f588eb1dad6b6073c80991126807 |
| Sol Phase 1 replay | C:/AX/cost-handoff-archive/2026-08-11/reviewers/sol-phase1-replay-20260811.md | VERDICT: PASS | c1284198894bc5ba8a782f171079ce21f1a0eff5c5c657dc706a9550083a7d13 |
| Sol Phase 1 최초 wait 실패 | C:/AX/cost-handoff-archive/2026-08-11/reviewers/sol-phase1-replay-20260811.timeout.md | TIMEOUT | 4328c7f6757cd786409eaa26536490860130c8df6cf102c040f21d8e31ddfbd0 |
| Sol Phase 2 Taiwan replay | C:/AX/cost-handoff-archive/2026-08-11/reviewers/sol-phase2-taiwan-replay-20260811.md | VERDICT: FAIL | a25996cbe5605da74062ff4ad8435907d35435ad7ce60b665854a28868672cb1 |
| 최종 handoff 복원검사 | C:/AX/cost-handoff-archive/2026-08-11/reviewers/handoff-restoration-final-verification-20260811.md | HANDOFF_RECONSTRUCTION_FINAL: FAIL | 65e512bcd40237fdbff01f80889555a60a4995eb29bb40e75ce52d462ee75c2e |
| 최종 로컬 인계 점검 로그 | C:/AX/cost-handoff-archive/2026-08-11/repository/handoff-final-local-validation-20260811.log | HANDOFF_FINAL_LOCAL_VALIDATION: PASS | 9a2e476e8f88dc17e91f660fffefdc9cff44fe59ccf1a2ae647319c58fef4604 |

Kimi 파일은 `think`/`reasoning`/`systemPrompt` 키와 해당 이벤트를 제거한 보이는
이벤트 로그다. Sol 파일은 역사적 원래 반환값이 아니라 이번 보강에서 새로 실행한 읽기 전용
replay다. 역사적 판정 요약은 `06_reviewer_outputs.md`에 별도로 표시한다.

최종 로컬 점검 로그는 해당 로그 파일을 archive manifest에 추가하기 직전의 점검 snapshot이다.
그 뒤 manifest를 다시 생성했고, 현재 `26/26` 검증 결과는 `03_attempt_log.jsonl`의
최종 로컬 점검 시도와 터미널 재검사로 확인했다.

## 전체 테스트 로그

- 경로: `C:/AX/cost-handoff-archive/2026-08-11/repository/full-unittest-discover-20260811.log`
- 명령: `python3 -m unittest discover -s ledger/tests`
- 상태: `INTERRUPTED` — 50분 04초 후 SIGINT, `exit_code=130`; PASS로 기록하지 않는다.
- SHA256: `f35ef12a2bbb0ae9cbcf80d56b03dc6c72d61da1c58a34a23ada29d8c8b2d27c`

## 정확한 worktree 목록

전체 41개 tracked modified 및 40개 untracked의 정확한 목록은 아래 snapshot에서 확인한다.

- tracked: `C:/AX/cost-handoff-archive/2026-08-11/repository/tracked-name-status.txt`
- untracked: `C:/AX/cost-handoff-archive/2026-08-11/repository/untracked-files.txt`
- 전체 상태: `C:/AX/cost-handoff-archive/2026-08-11/repository/git-status.txt`
- tracked 변경 patch: `C:/AX/cost-handoff-archive/2026-08-11/repository/tracked.diff`

위 파일은 저장소 밖 stable archive에 존재하며 `manifest.sha256`에 포함된다.
