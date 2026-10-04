"""LangGraph workflow:

understand -> search -> extract -> rag -> enrich -> verify --(coverage ok / max rounds)--> recommend
                ^                                    |
                +------------ another round --------+
"""
from __future__ import annotations

import operator
from dataclasses import asdict
from functools import lru_cache
from typing import Annotated, Iterator, TypedDict

from langgraph.graph import END, StateGraph

from buywise.agents.extract import extract_listings
from buywise.agents.query import understand_query
from buywise.agents.recommend import recommend
from buywise.agents.search import active_platforms, pick_round_domains, prioritised_domains, run_search_round
from buywise.agents.verify import verify_listings
from buywise.config import RunSettings
from buywise.coverage import coverage_status, next_step, select_results
from buywise.llm import LLM
from buywise.providers import get_providers
from buywise.rag.retriever import HybridRetriever
from buywise.schemas import Listing, QueryPlan, RawResult
from buywise.utils.currency import convert
from buywise.utils.meta_fetch import fetch_product_meta
from buywise.utils.url_utils import dedupe, is_product_url


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


def n_rag(state: State) -> dict:
    s, plan = _settings(state), QueryPlan(**state["plan"])
    retriever = HybridRetriever(use_dense=s.use_dense, use_reranker=s.use_reranker)
    ranked = retriever.rank(plan.product, _pool(state))
    return {"pool": [l.model_dump() for l in ranked], "rag_mode": retriever.mode,
            "trace": [f"[RAG agent] hybrid retrieval mode: {retriever.mode} on {len(ranked)} listings"]}


def n_enrich(state: State) -> dict:
    """Last resort: polite JSON-LD/OpenGraph price lookup for relevant listings lacking a price."""
    s = _settings(state)
    done = set(state.get("meta_fetched", []))
    budget = s.max_meta_fetches - len(done)
    pool, fixed = _pool(state), 0
    if budget > 0 and s.require_price:
        for l in pool:      # pool is already sorted best-first by the RAG node
            if budget <= 0:
                break
            if l.price is not None or l.url in done or "shopping_link" in l.flags:
                continue
            if l.relevance < s.rerank_threshold or not is_product_url(l.url):
                continue
            done.add(l.url)
            budget -= 1
            meta = fetch_product_meta(l.url)
            if meta and meta[1] in ("PKR", "USD"):
                l.price, l.currency, l.price_origin = meta[0], meta[1], "page-meta"
                l.price_pkr = convert(meta[0], meta[1], "PKR")
                fixed += 1
    return {"pool": [l.model_dump() for l in pool], "meta_fetched": sorted(done),
            "trace": [f"[Enrichment] page metadata gave {fixed} price(s) ({len(done)} lookups used)"]}


def n_verify(state: State) -> dict:
    s, plan = _settings(state), QueryPlan(**state["plan"])
    valid, drops = verify_listings(_pool(state), s, plan)
    selected = select_results(valid, s.target_results, s.per_platform_cap)
    status = coverage_status(selected, s.target_results, s.min_platforms)
    trace = [f"[Verification agent] {len(valid)} valid; dropped: {drops or 'none'}"]
    final_round = state.get("round", 1) >= s.max_rounds or state.get("no_providers")
    if final_round and not status["ok"] and len(selected) < s.target_results:
        relaxed = select_results(valid, s.target_results, s.per_platform_cap + 1)
        if len(relaxed) > len(selected):
            selected = relaxed
            status = coverage_status(selected, s.target_results, s.min_platforms)
            trace.append(f"   per-platform cap relaxed to {s.per_platform_cap + 1} to reach more results")
    trace.append(f"[Coverage controller] {status['count']}/{s.target_results} results from "
                 f"{status['platforms']}/{s.min_platforms} platforms -> {'OK' if status['ok'] else 'target not met'}")
    return {"selected": [l.model_dump() for l in selected], "status": status, "trace": trace}


def route(state: State) -> str:
    if state.get("no_providers"):
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
    for name, fn in [("understand", n_understand), ("search", n_search), ("extract", n_extract), ("rag", n_rag),
                     ("enrich", n_enrich), ("verify", n_verify), ("recommend", n_recommend)]:
        g.add_node(name, fn)
    g.set_entry_point("understand")
    for a, b in [("understand", "search"), ("search", "extract"), ("extract", "rag"), ("rag", "enrich"),
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
