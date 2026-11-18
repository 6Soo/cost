"""Optional bounded P2 rule packet; never a new source of policy authority.

All selected clauses are copied verbatim from docs/policy and DECISION_POLICY.
Unknown rule catalogs fail closed to the existing *full* policy context. P2 can
request more evidence, but cannot silently invent unprovided rules.
This is opt-in while classification and finance regression review is pending.
"""
from __future__ import annotations

import re
from pathlib import Path

# Domain decisions needed in P2's ordinary trip/item attribution. User-exception
# clauses are included regardless of these pins. OTA/refund domains are still
# selected by p2_case's existing evidence-driven routing.
PINNED = {
    'process': '001 004 006 008 010 011 014 015 016 021 023 024 025 072',
    'trip': '001 003 021 024 029 030 036 038 039 040 041 042 044 047 051 053 062 063 071 081',
    'item': '001 002 004 005 007 010 017 018 022 023 024 026 027 029 031 033 034 035 040 042 044 046 050 080 082',
    'date': '001 011 014 017 021 023 029 033 038 041 048 049 054 060 079 100 109',
    'link': '001 002 003 004 005 006 007 010 011 012 013 015 017 018 019 021 028 038 044 058 061 068 090 092 108 109 110 111',
    'refund': '001 003 004 007 011 012 013 014 015 017 018 021 022 023 025 027 029 050 055 061',
}
PREFIX = {'process': 'PROC', 'trip': 'TRIP', 'item': 'ITEM',
          'date': 'DATE', 'link': 'LINK', 'refund': 'RFND'}
# Fingerprints are derived from the ordered "ID:category" headers, *not*
# financial records or prose. Support main 767 and pending docs #1011 689.
# A new/deleted/retagged rule automatically falls back to the full packet
# until a reviewer checks whether it belongs in PINNED.
CATALOG_FINGERPRINTS = {
    'process': frozenset({'90ce7738', '6b6ae0a3'}),
    'trip': frozenset({'6b5ef2bc', '07731f3f'}),
    'item': frozenset({'5017ea98', 'e9f9e593'}),
    'date': frozenset({'485a9484', '02994727'}),
    'link': frozenset({'8b20f0b9', '9be56e17'}),
    'refund': frozenset({'ebb80d90', '8b7ff394'}),
}
HEAD = re.compile(r'(?m)^### ([A-Z]{3,6}-\d{3}) · ([^\n]+)$')
KIND = re.compile(r'(?m)^\*([^*\n]+)\*$')


def _fingerprint(s):
    """FNV-1a on Unicode code points; all policy-ID/type chars are BMP."""
    n = 2166136261
    for ch in s:
        n = ((n ^ ord(ch)) * 16777619) & 0xffffffff
    return f'{n:08x}'


def _sections(text):
    markers = list(HEAD.finditer(text))
    result = []
    for i, match in enumerate(markers):
        raw = text[match.start():markers[i + 1].start() if i + 1 < len(markers) else len(text)]
        raw = re.split(r'(?m)^## \d+\.', raw, maxsplit=1)[0]
        label = KIND.search(raw)
        category = label.group(1).split(' · ', 1)[0] if label else '일반'
        result.append((match.group(1), category, raw))
    return result


def compact_policy_context(root: Path, areas=()):
    """Return exact-source compact packet, or None for mandatory full fallback.

    Does not select rules on mutable merchant strings, LLM output, monetary
    guesses, or ambiguous evidence. Caller still controls link/refund domains.
    """
    area_set = set(areas)
    if area_set - set(PINNED):
        raise ValueError('P2_POLICY_AREA_INVALID')
    enabled = sorted(area_set | {'process', 'trip', 'item', 'date'})
    catalogs = {}
    for area in enabled:
        path = root / 'docs/policy' / (area + '.md')
        if not path.is_file():
            return None
        parts = _sections(path.read_text(encoding='utf-8'))
        signature = '|'.join(f'{identity}:{category}' for identity, category, _ in parts)
        if not parts or _fingerprint(signature) not in CATALOG_FINGERPRINTS[area]:
            return None
        selected = {f'{PREFIX[area]}-{n}' for n in PINNED[area].split()}
        selected.update(identity for identity, category, _ in parts if category == '사용자 예외')
        if not selected <= {identity for identity, _, _ in parts}:
            return None
        rules = []
        for identity, _, source in parts:
            if identity not in selected:
                continue
            current = source.split('- 대체된 옛 규칙:', 1)[0].split('- 출처:', 1)[0].strip()
            current = re.sub(r'(?m)^\*[^\n]*\*\n', '', current)
            rules.append(re.sub(r'\n\s*\n', '\n', current))
        catalogs[area] = '\n\n'.join(rules)

    canonical = root / 'docs/DECISION_POLICY.md'
    if not canonical.is_file():
        return None
    text = canonical.read_text(encoding='utf-8')
    try:
        core = text.split('## 2.', 1)[1].split('## 4.', 1)[0]
        exceptions = text.split('## 5.', 1)[1].split('## 6.', 1)[0]
    except IndexError:
        return None
    return {'CORE': '## 2.' + core + '\n## 5.' + exceptions, **catalogs}
