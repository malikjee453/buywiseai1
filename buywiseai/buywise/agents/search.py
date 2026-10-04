"""Search Agents: parallel fan-out over providers x whitelisted domains."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from buywise.config import Platform, RunSettings, load_platforms
from buywise.providers.base import SearchProvider
from buywise.schemas import QueryPlan, RawResult
from buywise.utils.redact import redact_secrets

log = logging.getLogger(__name__)


def active_platforms(settings: RunSettings) -> list[Platform]:
    """Whitelist after applying the user's UI filters."""
    out = []
    for p in load_platforms():
        if settings.platform_domains and p.domain not in settings.platform_domains:
            continue
        if p.domain == "aliexpress.com" and not settings.include_aliexpress:
            continue
        if p.domain == "olx.com.pk" and settings.exclude_olx:
            continue
        out.append(p)
    return out


def prioritised_domains(plan: QueryPlan, platforms: list[Platform]) -> list[Platform]:
    """General platforms + AliExpress first, then relevant categories, then the rest."""
    def rank(p: Platform) -> tuple:
        if p.category == "general":
            return (0, -p.trust_score)
        if p.category in plan.categories:
            return (1, -p.trust_score)
        return (2, -p.trust_score)
    return sorted(platforms, key=rank)


def pick_round_domains(ordered: list[Platform], round_no: int, per_round: int) -> list[Platform]:
    """Round 1 = top N; later rounds shift the window and always keep general platforms."""
    start = (round_no - 1) * per_round // 2
    window = ordered[start:start + per_round] or ordered[:per_round]
    core = [p for p in ordered if p.category == "general"]
    seen, out = set(), []
    for p in core + window:
        if p.domain not in seen:
            seen.add(p.domain)
            out.append(p)
    return out


def _tasks(domains: list[Platform], providers: list[SearchProvider], per_domain: int, query: str):
    """Rotate providers across domains so each domain is hit by `per_domain` engines."""
    web = [p for p in providers if p.name != "aliexpress_api"]
    tasks = []
    if web:
        for i, plat in enumerate(domains):
            for k in range(min(per_domain, len(web))):
                tasks.append((web[(i + k) % len(web)], "search", query, plat.domain))
    for prov in providers:
        if prov.supports_shopping:
            tasks.append((prov, "shopping", query, None))
    return tasks


def run_search_round(
    query: str, domains: list[Platform], providers: list[SearchProvider], settings: RunSettings, max_workers: int = 12,
) -> tuple[list[RawResult], list[str]]:
    """Execute one round. One failing provider never crashes the run."""
    tasks = _tasks(domains, providers, settings.providers_per_domain, query)
    raws: list[RawResult] = []
    errors: dict[str, int] = {}
    first_err: dict[str, str] = {}
    ok_calls = 0

    def work(prov, kind, q, dom):
        return prov.search(q, dom, 10) if kind == "search" else prov.shopping(q, 10)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(work, *t): t for t in tasks}
        for fut in as_completed(futures):
            prov = futures[fut][0]
            try:
                raws.extend(fut.result(timeout=60))
                ok_calls += 1
            except Exception as e:
                errors[prov.name] = errors.get(prov.name, 0) + 1
                first_err.setdefault(prov.name, redact_secrets(str(e))[:180])
                log.warning("%s failed: %s", prov.name, e)
    trace = [f"{len(tasks)} calls ({ok_calls} ok) on {len(domains)} domains -> {len(raws)} raw hits"]
    for name, n in errors.items():
        trace.append(f"provider '{name}': {n} failed call(s), e.g. {first_err.get(name, '?')}")
    return raws, trace
