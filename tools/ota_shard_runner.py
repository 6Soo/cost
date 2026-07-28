# -*- coding: utf-8 -*-
"""OTA 판단필요 샤드를 외부 저비용 모델에 병렬 분배하는 실행기 (2026-07-29).

사용자 지시(2026-07-29): "ota 잔여대사를 최대한의 병렬에이전트로. 저추론으로 가능하면
agy gemini flash 3.6 high 과 codex gpt 5.6 luna low 를 쓸 것."

엔진:
  agy   : `agy --print --model gemini-3.6-flash-high --effort high`
  codex : `codex exec --model gpt-5.6-luna -c model_reasoning_effort=low --skip-git-repo-check`

두 엔진에 **같은 샤드를 교차 배정**하지 않고 서로 다른 샤드를 준다(처리량 우선).
다만 `--cross` 를 주면 모든 샤드를 양쪽에 돌려 교차검증한다(정확도 우선).

이 스크립트는 **중앙 링크파일을 읽지도 쓰지도 않는다**. 판정 결과만 파일로 남긴다.
실제 병합은 `ledger/merge_verified_ota_links.py` 의 가드를 통과해야 한다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RULES = """\
너는 여행사 비용장부의 OTA 대사 판정자다. 카드 결제 이벤트 하나하나에 대해, 주어진 Gmail 후보 중
어느 것이 그 결제의 근거인지 판정한다.

절대 규칙:
1. 주어진 데이터에 **없는 예약번호를 만들어내지 마라.** booking_id 는 반드시 후보의
   `booking_refs_in_body` / `mail_booking_refs` 또는 `manual_ledger_matches[].book` 에 실재하는 값이어야 한다.
2. 교집합이 **유일**할 때만 link 로 판정한다. 후보가 둘 이상 똑같이 그럴듯하거나, 같은 금액의
   다른 예약과 구분할 수 없으면 반드시 hold 다.
3. 금액이 같다는 것만으로는 근거가 부족하다. 예약번호·카드끝4자리·날짜·투숙객 중 최소 하나가 더 맞아야 한다.
4. period 는 확실히 읽히는 경우에만 `MMDD` 또는 `MMDD_MMDD` 로 쓴다. 모르면 빈 문자열 "" 로 둔다. 추측 금지.
5. 결제대행 상호(예: Amsterdam, Tokyo, Internet)는 숙소 위치 근거가 아니다.
6. 취소/환불(금액 음수)은 원결제와 별개 이벤트다. 상계하거나 합치지 마라.

출력 형식: **JSON 배열만** 출력한다. 설명·인삿말·코드펜스 밖 텍스트 금지.
배열 원소는 입력의 각 uid 마다 정확히 하나씩, 입력과 같은 개수여야 한다.
[
  {"uid":"...", "decision":"link"|"hold", "booking_id":"", "period":"",
   "confidence":"high"|"medium"|"low", "reason":"한국어 한 문장"}
]
decision 이 hold 면 booking_id 는 "" 로 둔다.
"""


def compact(item: dict) -> dict:
    return {
        "uid": item["uid"],
        "provider": item["provider"],
        "use_date": item["use_date"],
        "card4": item["card4"],
        "merchant": item["merchant"][:48],
        "krw": item["krw"],
        "currency": item["currency"],
        "foreign": item["foreign"],
        "bucket": item["bucket"],
        "note": item["note"][:160],
        "manual_ledger_matches": item.get("manual_ledger_matches", [])[:4],
        "candidates": [
            {
                "score": c["score"],
                "sent_at": c["sent_at"][:16],
                "subject": c["subject"][:90],
                "evidence_tags": c["evidence_tags"],
                "booking_refs_in_body": c["booking_refs_in_body"][:4],
                "mail_booking_refs": c["mail_booking_refs"][:4],
                "mail_amounts": c["mail_amounts"][:6],
                "mail_travel_dates": c["mail_travel_dates"][:4],
            }
            for c in item.get("candidates", [])[:4]
        ],
    }


def build_prompt(shard: list[dict]) -> str:
    payload = json.dumps([compact(x) for x in shard], ensure_ascii=False, indent=1)
    return f"{RULES}\n\n입력 ({len(shard)}건):\n{payload}\n\nJSON 배열만 출력하라."


def extract_json(text: str) -> list | None:
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("[")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("[", start + 1)
    return None


def run_agy(prompt: str, timeout: int) -> tuple[str, str]:
    proc = subprocess.run(
        ["agy", "--print", "--model", "gemini-3.6-flash-high", "--effort", "high",
         "--output-format", "text", "--dangerously-skip-permissions", "--prompt", prompt],
        capture_output=True, timeout=timeout,
    )
    return proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def run_codex(prompt: str, timeout: int) -> tuple[str, str]:
    proc = subprocess.run(
        ["codex", "exec", "--model", "gpt-5.6-luna",
         "-c", "model_reasoning_effort=low", "--skip-git-repo-check", prompt],
        capture_output=True, timeout=timeout,
    )
    return proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


ENGINES = {"agy": run_agy, "codex": run_codex}


def process(engine: str, shard_path: Path, out_dir: Path, timeout: int) -> dict:
    shard = json.loads(shard_path.read_text(encoding="utf-8"))
    prompt = build_prompt(shard)
    name = f"{shard_path.stem}.{engine}"
    try:
        stdout, stderr = ENGINES[engine](prompt, timeout)
    except subprocess.TimeoutExpired:
        return {"shard": shard_path.stem, "engine": engine, "status": "timeout", "items": len(shard)}
    except Exception as exc:  # noqa: BLE001
        return {"shard": shard_path.stem, "engine": engine, "status": f"error:{exc}", "items": len(shard)}

    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    (out_dir / "raw" / f"{name}.txt").write_text(stdout + "\n---STDERR---\n" + stderr, encoding="utf-8")

    parsed = extract_json(stdout)
    if parsed is None:
        return {"shard": shard_path.stem, "engine": engine, "status": "unparseable", "items": len(shard)}

    uids = {x["uid"] for x in shard}
    kept = [v for v in parsed if isinstance(v, dict) and v.get("uid") in uids]
    (out_dir / f"{name}.json").write_text(
        json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "shard": shard_path.stem, "engine": engine, "status": "ok",
        "items": len(shard), "returned": len(parsed), "valid_uid": len(kept),
        "link": sum(1 for v in kept if v.get("decision") == "link"),
        "hold": sum(1 for v in kept if v.get("decision") == "hold"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--cross", action="store_true", help="모든 샤드를 두 엔진 모두에 돌린다")
    ap.add_argument("--engines", default="agy,codex",
                    help="사용할 엔진 쉼표구분(예: codex). 한 개면 전 샤드를 그 엔진이 처리한다")
    ap.add_argument("--only", default="", help="쉼표구분 샤드 stem 필터(예: 01,02)")
    args = ap.parse_args()

    shards_dir = Path(args.shards_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shards = sorted(shards_dir.glob("*.json"))
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        shards = [s for s in shards if s.stem in want]
    if not shards:
        print("샤드 없음", file=sys.stderr)
        return 2

    engines = [e.strip() for e in args.engines.split(",") if e.strip() in ENGINES]
    if not engines:
        print(f"사용 가능한 엔진 없음: {args.engines}", file=sys.stderr)
        return 2
    jobs = []
    for i, shard in enumerate(shards):
        if args.cross or len(engines) == 1:
            jobs += [(eng, shard) for eng in engines]
        else:
            jobs.append((engines[i % len(engines)], shard))

    print(f"샤드 {len(shards)}개 · 작업 {len(jobs)}개 · 동시 {args.workers}")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, eng, sh, out_dir, args.timeout): (eng, sh) for eng, sh in jobs}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            print(f"  [{res['status']:>12}] {res['shard']}.{res['engine']} "
                  f"items={res['items']} link={res.get('link','-')} hold={res.get('hold','-')}",
                  flush=True)

    (out_dir / "run_summary.json").write_text(
        json.dumps(sorted(results, key=lambda r: (r["shard"], r["engine"])),
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"완료: 성공 {ok}/{len(results)} · link {sum(r.get('link',0) for r in results)} "
          f"· hold {sum(r.get('hold',0) for r in results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
