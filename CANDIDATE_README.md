# Web Ledger — fixed integration candidate

`phase6-rules`에서 검증한 웹 장부 후보를 2026-09-27 본 저장소에 반영했습니다.
최신 상태와 남은 작업은 [세션 인계](docs/handoff/2026-09-27/README.md)를 읽습니다.
아래 실행 명령은 저장소 루트에서 사용합니다.

## Run locally

    python run_candidate.py            # serves on 127.0.0.1:8765; upload worker enabled
    python run_candidate.py --port 9000 --db runtime/board.sqlite

A fresh `runtime/board.sqlite` is created and seeded with the synthetic demo
board on first run. Open:

- http://127.0.0.1:8765/board
- http://127.0.0.1:8765/import
- http://127.0.0.1:8765/export
- http://127.0.0.1:8765/income/income-demo-i1/split

`/rules` is not a standalone page: it needs a learning case id, so
`/rules` on its own answers 404 with "대화 사례가 필요해요." Open it from a
row's `규칙 대화 열기` link, or use
`/rules?case=<learning_case_id>` after a `rule_change` save.

## Tests

    python -m pytest webapp/tests -q -p no:cacheprovider

## What is fixed in this candidate

- Rule radios are real 18px circles with 44px tappable labels; question
  groups are spaced (no generic full-width input stretching them).
- Split table uses a shared colgroup and per-cell `data-label`; at 390px it
  becomes a labelled vertical form (배분 ID / 고객 / 여행 / 종류 / 금액).
- Rule screen big heading is just "규칙 대화"; the row id + revision live in
  a small `.meta` detail line at the bottom, not in the heading or top notice.
- Form errors re-render as 4xx HTML with no URL/base64/Referer leakage; local
  file links are sandboxed; archive toggle works without JavaScript.
- XLSX export reuses the same `client_request_id` (no duplicate file) and
  never overwrites an existing snapshot stem (UUID suffix for new requests).

## Design basis

A/Ramp/Pretendard per DESIGN_DIRECTION.md. PretendardVariable.woff2 + OFL.txt
are bundled under `webapp/static/fonts/` and served only via allowlist.

## Scope not included (intentionally)

- Real AI provider calls, API keys, and authentication.
- Production/operational data, deployment, and publishing.
- Direct in-table cell editing (the right-hand edit panel is the supported path).

## Provenance

반영 당시 42개 파일의 원천과 해시는
`docs/handoff/2026-09-27/candidate-manifest.json`에 보존했습니다.
이 안내 문서는 본 저장소 반영 후 링크를 수정했으므로 원래 후보 해시와 다릅니다.
Git의 줄 끝 정규화로 clone한 파일의 바이트 해시도 달라질 수 있습니다.
이후 변경의 기준은 Git 커밋이며 원천 manifest는 당시 후보 기록입니다.
