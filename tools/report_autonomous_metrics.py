"""Summarize autonomous cleanup metrics (JSONL) into exposure-time stats.

Reads the host's append-only metrics file. Counts only; never prints transaction
identifiers or customer text. Output is an aggregate JSON summary for operations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


def summarize(path: Path, since=None):
    events = []
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or '"p2_' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if since and str(event.get('ts', '')) < since:
                continue
            events.append(event)
    calls = [event for event in events if event.get('kind') == 'p2_call']
    blocked = [event for event in events if event.get('kind') == 'p2_blocked']
    durations = [int(event['duration_ms']) for event in calls if event.get('duration_ms') is not None]
    applied = sum(int(event.get('applied') or 0) for event in calls)
    completed = sum(1 for event in calls if str(event.get('outcome', '')).startswith('unavailable'))
    summary = {
        'period': 'since ' + (since or 'file start'),
        'ai_calls': len(calls),
        'ai_applied': applied,
        'ai_unavailable': completed,
        'ai_blocked': len(blocked),
        'ai_retries_estimate': max(0, len(calls) - applied - completed),
        'p50_ms': int(statistics.median(durations)) if durations else None,
        'p95_ms': (sorted(durations)[int(0.95 * (len(durations) - 1))] if durations else None),
        'max_ms': max(durations) if durations else None,
    }
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('metrics', type=Path, help='Path to autonomous-cleanup-metrics.jsonl')
    parser.add_argument('--since', help='ISO timestamp prefix lower bound, e.g. 2026-11-05')
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.metrics, since=args.since), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
