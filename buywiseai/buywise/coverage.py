"""Coverage controller: result selection, coverage check, and the next-step decision.

Pure functions on duck-typed listings (need .source, .score) so they are easy to test.
"""
from __future__ import annotations

from collections import Counter


def select_results(valid: list, target: int, cap: int) -> list:
    """Best-scoring listings first, at most `cap` per platform, up to `target`."""
    ordered = sorted(valid, key=lambda l: l.score, reverse=True)
    counts: Counter = Counter()
    out = []
    for l in ordered:
        if counts[l.source] >= cap:
            continue
        counts[l.source] += 1
        out.append(l)
        if len(out) >= target:
            break
    return out


def coverage_status(selected: list, target: int, min_platforms: int) -> dict:
    platforms = {l.source for l in selected}
    return {
        "count": len(selected),
        "platforms": len(platforms),
        "ok": len(selected) >= target and len(platforms) >= min_platforms,
    }


def next_step(status: dict, round_no: int, max_rounds: int) -> str:
    """'search' = run another round; 'recommend' = finish."""
    if status["ok"] or round_no >= max_rounds:
        return "recommend"
    return "search"
