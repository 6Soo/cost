"""Optional bounded P2 rule packet; never a new source of policy authority.

All selected clauses are copied verbatim from docs/policy and DECISION_POLICY.
Unknown rule catalogs fail closed to the existing *full* policy context. P2 can
request more evidence, but cannot silently invent unprovided rules.
This is opt-in while classification and finance regression review is pending.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Domain decisions needed in P2's ordinary trip/item attribution. User-exception
# clauses are included regardless of these pins. OTA/refund domains are still
# selected by p2_case's existing evidence-driven routing.
PINNED = {
    # PROC-010/011 are *보호* clauses the legacy full loader filters out; they are
    # pinned here on purpose so a reduced P2 packet still states the AI-evidence
    # and atomic-apply boundaries. The packet is therefore a reviewed selection,
    # not a strict subset of the full one.
    'process': '001 004 006 008 010 011 014 015 016 021 023 024 025 072',
    'trip': '001 003 021 024 029 030 036 038 039 040 041 042 044 045 047 048 049 051 053 062 063 071 081 089 097 099',
    'item': '001 002 004 005 007 010 017 018 022 023 024 026 027 029 031 033 034 035 040 042 046 050 080 082',
    'date': '001 011 014 017 021 023 029 033 038 041 048 049 054 060 079 100 108 109',
    'link': '001 002 003 004 005 006 007 010 011 012 013 015 017 018 019 021 024 025 028 030 035 038 043 044 058 061 068 090 092 108 109 110 111',
    'refund': '001 003 004 007 011 012 013 014 015 017 018 021 022 023 025 027 029 050 054 055 061 062',
}
PREFIX = {'process': 'PROC', 'trip': 'TRIP', 'item': 'ITEM',
          'date': 'DATE', 'link': 'LINK', 'refund': 'RFND'}
# Fingerprints are derived from the ordered "ID:category" headers, *not*
# financial records or prose. Only 767-catalog snapshots that were reviewed
# are listed; an unmerged documentation PR is never an approved revision.
# A new/deleted/retagged rule automatically falls back to the full packet
# until a reviewer checks whether it belongs in PINNED.
CATALOG_FINGERPRINTS = {
    'process': frozenset({'90ce7738', '6b6ae0a3'}),
    'trip': frozenset({'6b5ef2bc', '07731f3f'}),
    'item': frozenset({'5017ea98', 'e9f9e593', 'd7c12140'}),
    'date': frozenset({'485a9484', '02994727'}),
    'link': frozenset({'8b20f0b9', '9be56e17'}),
    'refund': frozenset({'ebb80d90', '8b7ff394'}),
}
# Exact reviewed Git blob hashes. A changed rule *body* may introduce a new
# requirement without changing its ID/type, so an ID-only signature is not
# enough to authorize compact omission. Any unreviewed snapshot uses full P2.
APPROVED_POLICY_REVISIONS = {
    # PR #1012 head / the 2026-11-19 deployment 3d8e8791.
    'main-20261119': {
        'CORE': '79819f0c9882abedd651a6266f5d330fb31170e4',
        'process': '6d87bfa9a424aa851772e705acc93054ae73c349',
        'trip': 'bd94778bdff021f4f51094e59ee38886d4e159f0',
        'item': 'ad494c89208101de6c9da1d52e4baa14d6242c2d',
        'date': '78eb22eeb41b14bdefb4caba49021fe0cbe119bf',
        'link': '334a3b31f02557f5106a3aa2982bf46c0e59b5fe',
        'refund': 'cc11f105288ecf510cf8aefb2124cef50969208e',
    },
    # Current main after #1016 (a8799ab2) restored the TRIP-043/ITEM-020 wording
    # of the abolished preparation inference. Those two rules are not pinned,
    # and the selected clauses are byte-identical to main-20261119, so the
    # reduced packet is the same text either way.
    'main-20261119b': {
        'CORE': '79819f0c9882abedd651a6266f5d330fb31170e4',
        'process': '6d87bfa9a424aa851772e705acc93054ae73c349',
        'trip': '67eb76e0995517417c7a9c43bdc3e3064982ab7f',
        'item': '7837c56b42dfdcbe6cf67e27146a25d84c0161a0',
        'date': '78eb22eeb41b14bdefb4caba49021fe0cbe119bf',
        'link': '334a3b31f02557f5106a3aa2982bf46c0e59b5fe',
        'refund': 'cc11f105288ecf510cf8aefb2124cef50969208e',
    },
    # b95815e9 recorded the 2026-11-19 owner decision as one line inside
    # PROC-013. PROC-013 is not pinned, so the reduced packet text is unchanged;
    # only the process blob hash moved. Registered so the checked-out snapshot
    # stays an approved revision instead of silently degrading to the full packet.
    'main-20261119c': {
        'CORE': '79819f0c9882abedd651a6266f5d330fb31170e4',
        'process': '20831694fe2d33c76b3a882dac5deb7c16666644',
        'trip': '67eb76e0995517417c7a9c43bdc3e3064982ab7f',
        'item': '7837c56b42dfdcbe6cf67e27146a25d84c0161a0',
        'date': '78eb22eeb41b14bdefb4caba49021fe0cbe119bf',
        'link': '334a3b31f02557f5106a3aa2982bf46c0e59b5fe',
        'refund': 'cc11f105288ecf510cf8aefb2124cef50969208e',
    },
    # 2026-11-19 consolidation (686 active + 81 retired). Every PINNED ID still
    # exists; three are now canonical for a merged pair and the unpinned
    # TRIP-043/DATE-039 bodies are gone, their requirement stated by PROC-004
    # and TRIP-042. The item catalog keeps its pinned set under a new fingerprint.
    'consolidated-20261119': {
        'CORE': 'a17db97863de0090ce8448f9c603ff2c6939095d',
        'process': '9a93886dcb4d0b48da733f0f5aa90d223ddc8e35',
        'trip': '7c7ef870a3f35836dcd0b59691dd1238a71fd842',
        'item': 'ba527ad386e0083107a171717c560f5d76deb75e',
        'date': 'ca95a4cd057ea87748473d9aa8a14c2b1d97269c',
        'link': 'bcf49439f980596107c5c88b767bd31e8f15c041',
        'refund': '266c17a31a4b75d537431ab2986f4454db360c33',
    },
    # OTA policy consolidation retains the pinned safeguards and rule IDs.
    'ota-consolidated-20261120': {
        'CORE': 'a17db97863de0090ce8448f9c603ff2c6939095d',
        'process': '9a93886dcb4d0b48da733f0f5aa90d223ddc8e35',
        'trip': '7c7ef870a3f35836dcd0b59691dd1238a71fd842',
        'item': '9f5e507e6a5ad53526d350c2a1793f3723da1146',
        'date': '91521a175f527530feb4327bbf6a2d61e73bc6a1',
        'link': '883c51ef712f387fdb4b69abfca376f4e4ae0baa',
        'refund': '266c17a31a4b75d537431ab2986f4454db360c33',
    },
}


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()


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

    The packet is a reviewed selection, not a strict subset of
    ``p2_case.policy_context(areas)``: pinned process *보호* clauses (PROC-010/011)
    are absent from the legacy full packet, which filters them out. They are
    included deliberately, and ``ai_classification`` accepts only a packet
    reproduced exactly from an approved revision, never a caller-supplied one.
    """
    area_set = set(areas)
    if area_set - set(PINNED):
        raise ValueError('P2_POLICY_AREA_INVALID')
    enabled = sorted(area_set | {'process', 'trip', 'item', 'date'})
    canonical = root / 'docs/DECISION_POLICY.md'
    if not canonical.is_file():
        return None
    approved_paths = {'CORE': _git_blob_sha(canonical.read_bytes())}
    catalogs = {}
    for area in enabled:
        path = root / 'docs/policy' / (area + '.md')
        if not path.is_file():
            return None
        raw = path.read_bytes()
        approved_paths[area] = _git_blob_sha(raw)
        parts = _sections(raw.decode('utf-8'))
        signature = '|'.join(f'{identity}:{category}' for identity, category, _ in parts)
        if not parts or _fingerprint(signature) not in CATALOG_FINGERPRINTS[area]:
            return None
        selected = {f'{PREFIX[area]}-{n}' for n in PINNED[area].split()}
        selected.update(identity for identity, category, _ in parts
                        if category in ('사용자 예외', '사용자 결정'))
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

    if not any(all(revision.get(area) == stamp for area, stamp in approved_paths.items())
               for revision in APPROVED_POLICY_REVISIONS.values()):
        return None
    text = canonical.read_text(encoding='utf-8')
    try:
        core = text.split('## 2.', 1)[1].split('## 4.', 1)[0]
        exceptions = text.split('## 5.', 1)[1].split('## 6.', 1)[0]
    except IndexError:
        return None
    return {'CORE': '## 2.' + core + '\n## 5.' + exceptions, **catalogs}
