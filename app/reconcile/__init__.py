"""Read-only reconciliation diagnostics and shared generation contracts."""

from __future__ import annotations


def same_generation(*artifacts):
    """Check that result-bearing read artifacts name one non-negative generation.

    Artifacts may be mappings (``generation``) or generation integers. Missing,
    malformed, or mixed generations are deliberately incomplete, never equal.
    This is a read contract only; freshness and authority remain with callers.
    """
    if not artifacts:
        return False
    generations = []
    for artifact in artifacts:
        value = artifact if type(artifact) is int else (
            artifact.get("generation") if isinstance(artifact, dict) else None)
        if type(value) is not int or value < 0:
            return False
        generations.append(value)
    return len(set(generations)) == 1


def index_results(results, *, generation=None):
    """Index canonical solver results by event ID without resolving conflicts.

    Duplicate/missing event IDs invalidate that ID instead of silently letting
    the last row win. An optional expected generation validates envelopes.
    """
    if isinstance(results, dict):
        result_generation = results.get("generation")
        rows = results.get("results")
        if generation is not None and not same_generation(generation, result_generation):
            return {}
        if generation is None and (type(result_generation) is not int or result_generation < 0):
            return {}
    else:
        rows = results
    if not isinstance(rows, (list, tuple)):
        return {}
    indexed, duplicates = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = row.get("ota_event_id")
        if identity is None or str(identity) == "":
            continue
        identity = str(identity)
        if identity in indexed:
            duplicates.add(identity)
        else:
            indexed[identity] = row
    for identity in duplicates:
        indexed.pop(identity, None)
    return indexed
