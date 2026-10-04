"""LangGraph workflow:

understand -> search -> extract -> expand -> rag -> enrich -> verify --(coverage ok / max rounds)--> recommend
                ^                                    |
                +------------ another round --------+
"""
from __future__ import annotations

import operator
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import lru_cache
from typing import Annotated, Iterator, TypedDict

from langgraph.graph import END, StateGraph

from buywise.agents.extract import extract_listings
from buywise.agents.judge import judge_relevance
from buywise.agents.query import understand_query
from buywise.agents.recommend import recommend
from buywise.agents.search import active_platforms, pick_round_domains, prioritised_domains, run_search_round
from buywise.agents.verify import verify_listings
from buywise.config import RunSettings, match_platform
from buywise.coverage import coverage_status, next_step, select_results
from buywise.llm import LLM
from buywise.providers import get_providers
from buywise.rag.retriever import HybridRetriever
from buywise.schemas import Listing, QueryPlan, RawResult
from buywise.utils.currency import convert
from buywise.utils.meta_fetch import collection_handle, fetch_collection_products, fetch_product_meta_ex
from buywise.utils.relevance import gender_conflict, is_accessory, title_matches_model
from buywise.utils.url_utils import dedupe, is_foreign_storefront, is_product_url, is_rankable


class State(TypedDict, total=False):
    query: str
    settings: dict
    plan: dict
    round: int
    raw: list
    pool: list
    selected: list
    status: dict
    shortfall: str
    recommendation: str
    rag_mode: str
    meta_fetched: list
    robots_blocked: list
    last_count: int
    stalled: bool
    expanded: list
    no_providers: bool
    trace: Annotated[list, operator.add]


def _settings(state: State) -> RunSettings:
    return RunSettings(**state["settings"])


def _pool(state: State) -> list[Listing]:
    return [Listing(**d) for d in state.get("pool", [])]


# ---------------------------------------------------------------- nodes
def n_understand(state: State) -> dict:
    s = _settings(state)
    plan, how = understand_query(state["query"], s, LLM(temperature=0.0))
    cats = ", ".join(plan.categories)
    return {"plan": plan.model_dump(), "trace": [
        f"[Query agent/{how}] product='{plan.product}', categories=[{cats}], "
        f"budget={plan.max_budget_pkr or 'none'}, {len(plan.variants)} query variants"]}


def n_search(state: State) -> dict:
    s, plan = _settings(state), QueryPlan(**state["plan"])
    rnd = state.get("round", 0) + 1
    providers = get_providers(s.providers)
    if not providers:
        return {"round": rnd, "raw": [], "no_providers": True,
                "trace": ["[Search agents] No search provider available: add at least one API key."]}
    ordered = prioritised_domains(plan, active_platforms(s))
    domains = pick_round_domains(ordered, rnd, s.domains_per_round)
    variant = plan.variants[(rnd - 1) % len(plan.variants)]
    raws, trace = run_search_round(variant, domains, providers, s)
    names = ", ".join(p.name for p in providers)
    return {"round": rnd, "raw": [r.model_dump() for r in raws],
            "trace": [f"[Search agents] round {rnd}, query='{variant}', providers=[{names}]"] + [f"   {t}" for t in trace]}


def n_extract(state: State) -> dict:
    s = _settings(state)
    raws = [RawResult(**d) for d in state.get("raw", [])]
    new, trace = extract_listings(raws, s, LLM(temperature=0.0))
    pool = dedupe(_pool(state) + new)
    return {"pool": [l.model_dump() for l in pool],
            "trace": [f"[Extraction agent] {t}" for t in trace] + [f"   pool: {len(pool)} unique listings"]}


_STOP = {"for", "in", "the", "and", "with", "of", "a", "an", "to", "pakistan", "price", "online", "buy"}


def n_expand(state: State) -> dict:
    """Shopify stores: turn category pages found by search into real, priced product listings
    via the store's public product feed (robots.txt-aware, 1 req/s per domain)."""
    import re

    s, plan = _settings(state), QueryPlan(**state["plan"])
    if not s.use_shopify_feeds:
        return {"trace": ["[Shopify feeds] disabled in settings"]}
    done = set(state.get("expanded", []))
    qtoks = {t for t in re.findall(r"[a-z0-9]+", plan.original.lower()) if t not in _STOP and len(t) > 1}
    cands, seen = [], set()
    for l in _pool(state):
        h = collection_handle(l.url)
        plat = match_platform(l.domain)
        key = f"{l.domain}/{h}"
        if not h or key in done or key in seen or plat is None or plat.country != "PK" or is_foreign_storefront(l.domain):
            continue
        words = h.replace("_", "-").split("-")
        overlap = len(qtoks & set(words))
        if overlap == 0 or gender_conflict(" ".join(words), "", plan.original):
            continue
        seen.add(key)
        cands.append((overlap, key, l.domain, h))
    cands.sort(key=lambda c: -c[0])
    picked = cands[: s.expand_per_round]
    by_domain: dict[str, list] = {}
    for _, key, dom, h in picked:
        by_domain.setdefault(dom, []).append((key, h))

    def work(item):
        dom, handles = item
        return [(key, dom, *fetch_collection_products(dom, h)) for key, h in handles]

    new, reasons = [], Counter()
    if by_domain:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for batch in ex.map(work, by_domain.items()):
                for key, dom, items, reason in batch:
                    done.add(key)
                    reasons[reason] += 1
                    plat = match_platform(dom)
                    for it in items:
                        new.append(Listing(
                            title=it["title"], price=it["price"], currency="PKR", price_pkr=it["price"],
                            source=plat.name, domain=dom, url=it["url"], snippet=it["snippet"],
                            trust_score=plat.trust_score, provider="shopify-feed", price_origin="shopify-feed"))
    pool = dedupe(_pool(state) + new)
    return {"pool": [l.model_dump() for l in pool], "expanded": sorted(done),
            "trace": [f"[Shopify feeds] {len(picked)} category pages (of {len(cands)} candidates) -> "
                      f"{len(new)} priced products; outcomes: {dict(reasons) or 'none'}"]}


def n_rag(state: State) -> dict:
    s, plan = _settings(state), QueryPlan(**state["plan"])
    retriever = HybridRetriever(use_dense=s.use_dense, use_reranker=s.use_reranker)
    pool = _pool(state)
    def _rankable(l: Listing) -> bool:     # same cheap rules verification applies, so nothing useful is lost
        return (is_rankable(l) and (plan.used_ok or not is_accessory(l.title, plan.original))
                and not gender_conflict(l.title, l.url, plan.original)
                and title_matches_model(l.title, l.url, plan.original))
    flags = [_rankable(l) for l in pool]
    keep = [l for l, ok in zip(pool, flags) if ok]
    skip = [l for l, ok in zip(pool, flags) if not ok]   # category/blog/off-whitelist/accessory: can never be results
    for l in skip:
        l.relevance, l.score = -99.0, -99.0
    ranked = retriever.rank(plan.product, keep) + skip
    return {"pool": [l.model_dump() for l in ranked], "rag_mode": retriever.mode,
            "trace": [f"[RAG agent] hybrid retrieval mode: {retriever.mode} on {len(keep)} rankable listings "
                      f"({len(skip)} non-product/off-whitelist skipped)"]}


def n_enrich(state: State) -> dict:
    """Last resort: polite JSON-LD/OpenGraph price lookup for listings that would otherwise be
    dropped only for lacking a price. Skips anything verification would reject anyway."""
    s, plan = _settings(state), QueryPlan(**state["plan"])
    done = set(state.get("meta_fetched", []))
    blocked_domains = set(state.get("robots_blocked", []))
    allowance = min(s.max_meta_fetches - len(done), s.meta_fetches_per_round)
    pool, fixed, reasons = _pool(state), 0, Counter()
    if allowance > 0 and s.require_price:
        by_domain: dict[str, list[Listing]] = {}
        picked = 0
        for l in pool:      # pool is sorted best-first by the RAG node
            if picked >= allowance:
                break
            if (l.price is not None or l.url in done or "shopping_link" in l.flags or is_foreign_storefront(l.domain)
                    or l.domain in blocked_domains):
                continue
            if l.relevance < s.rerank_threshold or not is_product_url(l.url):
                continue
            if (is_accessory(l.title, plan.original) or gender_conflict(l.title, l.url, plan.original)
                    or not title_matches_model(l.title, l.url, plan.original)):
                continue
            by_domain.setdefault(l.domain, []).append(l)
            picked += 1

        def work(items: list[Listing]):
            out = []
            blocked = False
            for l in items:                       # one domain per worker => polite 1 req/s per site
                if blocked:                       # robots.txt forbids this site: don't burn budget on its other pages
                    out.append((l, None, "skipped"))
                    continue
                res = fetch_product_meta_ex(l.url)
                out.append((l, *res))
                blocked = res[1] == "robots"
            return out

        with ThreadPoolExecutor(max_workers=6) as ex:
            for batch in ex.map(work, by_domain.values()):
                for l, meta, reason in batch:
                    if reason == "skipped":
                        continue
                    if reason == "robots":
                        blocked_domains.add(l.domain)     # remembered across rounds; costs no lookup budget
                    else:
                        done.add(l.url)
                    reasons[reason] += 1
                    if meta and meta[1] in ("PKR", "USD"):
                        l.price, l.currency, l.price_origin = meta[0], meta[1], "page-meta"
                        l.price_pkr = convert(meta[0], meta[1], "PKR")
                        fixed += 1
    return {"pool": [l.model_dump() for l in pool], "meta_fetched": sorted(done), "robots_blocked": sorted(blocked_domains),
            "trace": [f"[Enrichment] {sum(reasons.values())} page lookups -> {fixed} price(s) found; "
                      f"outcomes: {dict(reasons) or 'none'} ({len(done)}/{s.max_meta_fetches} budget used)"]}


def n_verify(state: State) -> dict:
    s, plan = _settings(state), QueryPlan(**state["plan"])
    valid, drops, samples = verify_listings(_pool(state), s, plan)
    judged_titles: list = []
    valid, n_judged = judge_relevance(valid, plan.original, LLM(temperature=0.0))
    if n_judged:
        drops["llm_wrong_product_type"] = n_judged
        judged_titles = getattr(judge_relevance, "last_dropped", [])[:4]
    selected = select_results(valid, s.target_results, s.per_platform_cap)
    status = coverage_status(selected, s.target_results, s.min_platforms)
    trace = [f"[Verification agent] {len(valid)} valid; dropped: {drops or 'none'}"]
    for reason in ("not_product_page", "no_price", "model_mismatch", "low_relevance"):
        if samples.get(reason):
            trace.append(f"   e.g. {reason}: " + " | ".join(samples[reason]))
    final_round = state.get("round", 1) >= s.max_rounds or state.get("no_providers")
    if final_round and not status["ok"] and len(selected) < s.target_results:
        relaxed = select_results(valid, s.target_results, s.per_platform_cap + 1)
        if len(relaxed) > len(selected):
            selected = relaxed
            status = coverage_status(selected, s.target_results, s.min_platforms)
            trace.append(f"   per-platform cap relaxed to {s.per_platform_cap + 1} to reach more results")
    if n_judged and judged_titles:
        trace.append("   e.g. llm_wrong_product_type: " + " | ".join(judged_titles))
    for l in selected:
        trace.append(f"   \u2713 {l.source}: Rs {l.price_pkr or 0:,.0f} (listed {l.price} {l.currency}, source={l.price_origin}) {l.url[:90]}")
    trace.append(f"[Coverage controller] {status['count']}/{s.target_results} results from "
                 f"{status['platforms']}/{s.min_platforms} platforms -> {'OK' if status['ok'] else 'target not met'}")
    stalled = state.get("round", 1) >= 2 and status["count"] <= state.get("last_count", -1)
    if stalled and not status["ok"]:
        trace.append("   no new verified results this round: stopping early instead of searching again")
    return {"selected": [l.model_dump() for l in selected], "status": status, "last_count": status["count"],
            "stalled": stalled, "trace": trace}


def route(state: State) -> str:
    if state.get("no_providers") or (state.get("stalled") and not state["status"]["ok"]):
        return "recommend"
    return next_step(state["status"], state.get("round", 1), _settings(state).max_rounds)


def n_recommend(state: State) -> dict:
    s = _settings(state)
    selected = [Listing(**d) for d in state.get("selected", [])]
    st = state.get("status", {})
    shortfall = None
    if not st.get("ok"):
        shortfall = (f"Only {st.get('count', 0)} verified results from {st.get('platforms', 0)} platforms "
                     f"were found (target {s.target_results} from {s.min_platforms}+).")
    text = recommend(selected, state["query"], s.display_currency, LLM(temperature=s.temperature), shortfall)
    return {"recommendation": text, "shortfall": shortfall or "",
            "trace": ["[Recommendation agent] written from verified listings only"]}


# ---------------------------------------------------------------- graph
@lru_cache(maxsize=1)
def get_graph():
    g = StateGraph(State)
    def timed(name, fn):
        def wrapper(state: State) -> dict:
            t0 = time.time()
            out = dict(fn(state))
            out["trace"] = list(out.get("trace", [])) + [f"   ⏱ {name}: {time.time() - t0:.1f}s"]
            return out
        return wrapper

    for name, fn in [("understand", n_understand), ("search", n_search), ("extract", n_extract), ("expand", n_expand), ("rag", n_rag),
                     ("enrich", n_enrich), ("verify", n_verify), ("recommend", n_recommend)]:
        g.add_node(name, timed(name, fn))
    g.set_entry_point("understand")
    for a, b in [("understand", "search"), ("search", "extract"), ("extract", "expand"), ("expand", "rag"), ("rag", "enrich"),
                 ("enrich", "verify")]:
        g.add_edge(a, b)
    g.add_conditional_edges("verify", route, {"search": "search", "recommend": "recommend"})
    g.add_edge("recommend", END)
    return g.compile()


def stream_pipeline(query: str, settings: RunSettings) -> Iterator[tuple[str, dict, dict]]:
    """Yield (node, update, accumulated_state) as each agent finishes."""
    init: State = {"query": query, "settings": asdict(settings), "round": 0, "pool": [], "trace": []}
    final: dict = dict(init)
    for chunk in get_graph().stream(init, stream_mode="updates"):
        for node, update in chunk.items():
            if not update:
                continue
            final["trace"] = list(final.get("trace", [])) + list(update.get("trace", []))
            final.update({k: v for k, v in update.items() if k != "trace"})
            yield node, update, final


def run_pipeline(query: str, settings: RunSettings) -> dict:
    final: dict = {}
    for _, _, final in stream_pipeline(query, settings):
        pass
    return final
