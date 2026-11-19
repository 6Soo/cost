"""Reproducible byte/structure measurement of the selective P2 policy packet.

Read-only: writes no files and changes no policy source. Compares
``app.p2_policy_pack.compact_policy_context`` with the legacy full packet
``app.p2_case.policy_context(areas, compact=False)`` for the four routing
combinations (plain, OTA/link, refund, OTA+refund). Judgment equivalence is
out of scope; this tool only quantifies bytes and rule-ID structure.

Bytes are measured on the canonical P2 wire encoding (``p2_case.encoded``:
sorted keys, no ASCII escaping, compact separators) as UTF-8. When the
catalog fingerprint or blob revision is unapproved, compact fails closed to
the full packet; the record then reports ``compact_is_fallback=True`` with
zero reduction and identical hashes.

Usage: python -I tools/p2_policy_packet_measure.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import p2_case, p2_policy_pack  # noqa: E402  (needs the path bootstrap above)

COMBINATIONS = ((), ('link',), ('refund',), ('link', 'refund'))
RULE_HEAD = re.compile(r'(?m)^### ([A-Z]{3,6}-\d{3}) · ')


def packet_bytes(packet):
    return len(p2_case.encoded(packet).encode('utf-8'))


def rule_ids(packet):
    found = set()
    for area, text in packet.items():
        if area != 'CORE':
            found.update(RULE_HEAD.findall(text))
    return found


def measure_combination(areas):
    areas = tuple(sorted(set(areas)))
    full = p2_case.policy_context(areas, compact=False)
    compact = p2_policy_pack.compact_policy_context(p2_case.ROOT, areas)
    fallback = compact is None
    effective = full if fallback else compact
    full_bytes = packet_bytes(full)
    compact_bytes = packet_bytes(effective)
    full_ids = rule_ids(full)
    compact_ids = rule_ids(effective)
    # only_in_compact is a normal case, not a defect: the PINNED 보호 clauses
    # PROC-010/011 are filtered out by the legacy full loader but deliberately
    # kept in the compact packet (p2_policy_pack.PINNED), so the selection is
    # a reviewed packet, not a strict subset of the full one.
    return {
        'areas': list(areas),
        'compact_bytes': compact_bytes,
        'full_bytes': full_bytes,
        'reduction_pct': round(100.0 * (full_bytes - compact_bytes) / full_bytes, 1),
        'compact_is_fallback': fallback,
        'compact_sha256': hashlib.sha256(p2_case.encoded(effective).encode('utf-8')).hexdigest(),
        'full_sha256': hashlib.sha256(p2_case.encoded(full).encode('utf-8')).hexdigest(),
        'rule_ids': {
            'only_in_compact': sorted(compact_ids - full_ids),
            'only_in_full': sorted(full_ids - compact_ids),
            'common_count': len(compact_ids & full_ids),
        },
    }


def measure_all():
    return [measure_combination(areas) for areas in COMBINATIONS]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Measure compact vs full P2 policy packets (read-only).')
    parser.add_argument('--json', action='store_true',
                        help='print deterministic JSON instead of text lines')
    args = parser.parse_args(argv)
    report = measure_all()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        for row in report:
            label = '+'.join(row['areas']) or 'plain'
            print(f"{label}: compact={row['compact_bytes']}B full={row['full_bytes']}B "
                  f"reduction={row['reduction_pct']}% fallback={row['compact_is_fallback']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
