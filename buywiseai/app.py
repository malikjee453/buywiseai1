"""BuyWiseAI: Streamlit UI."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict

import pandas as pd
import streamlit as st

from buywise.config import CATEGORIES, RunSettings, get_secret, load_platforms
from buywise.graph import stream_pipeline
from buywise.providers import provider_status
from buywise.schemas import Listing
from buywise.utils.currency import convert, format_price

st.set_page_config(page_title="BuyWiseAI", page_icon="🛒", layout="wide")

CACHE_TTL = 30 * 60
AGENT_LABELS = {
    "understand": "🧠 Query understanding", "search": "🔎 Search agents", "extract": "🧾 Extraction",
    "rag": "📚 RAG retrieval + rerank", "enrich": "🌐 Page metadata", "verify": "✅ Verification + coverage",
    "recommend": "💡 Recommendation",
}


@st.cache_resource
def shared_cache() -> dict:
    """Process-wide result cache (30 min TTL) so repeated searches don't burn API quota."""
    return {}


def cache_key(query: str, s: RunSettings) -> str:
    return hashlib.sha1((query.strip().lower() + json.dumps(asdict(s), sort_keys=True)).encode()).hexdigest()


# ------------------------------------------------------------------ sidebar
st.sidebar.title("⚙️ Settings")
status = provider_status()
if not get_secret("GROQ_API_KEY"):
    st.sidebar.error("GROQ_API_KEY missing: AI features fall back to simple heuristics.")
if sum(1 for n, ok in status.items() if ok and n != "aliexpress_api") == 1:
    st.sidebar.info("Only one search engine is active. Add SERPAPI_API_KEY (Google + Bing) or BRAVE_API_KEY for better coverage.")
if not any(status.values()):
    st.sidebar.error("No search provider available. Add at least one API key.")

currency = st.sidebar.radio("Display currency", ["PKR", "USD"], horizontal=True)
c1, c2 = st.sidebar.columns(2)
min_price = c1.number_input(f"Min price ({currency})", min_value=0.0, value=0.0, step=100.0)
max_price = c2.number_input(f"Max price ({currency})", min_value=0.0, value=0.0, step=100.0)

st.sidebar.subheader("Results")
target = st.sidebar.slider("Number of results", 10, 20, 10)
min_platforms = st.sidebar.slider("Min. distinct platforms", 3, 10, 6)
cap = st.sidebar.slider("Max results per platform", 1, 3, 2)
rounds = st.sidebar.slider("Max search rounds", 1, 4, 3)

st.sidebar.subheader("Search providers")
avail = [n for n, ok in status.items() if ok]
chosen_providers = st.sidebar.multiselect("Enabled", avail, default=avail)
st.sidebar.caption("serper = Google · serpapi = Google + Shopping · bing = Bing via SerpApi · brave · tavily")
st.sidebar.caption("Unavailable (no key): " + (", ".join(n for n, ok in status.items() if not ok) or "none"))

st.sidebar.subheader("Platforms")
cats = st.sidebar.multiselect("Categories (empty = auto-detect)", [c for c in CATEGORIES if c != "general"])
names = {p.name: p.domain for p in load_platforms()}
chosen_platforms = st.sidebar.multiselect("Restrict to platforms (empty = all)", list(names))
inc_ali = st.sidebar.toggle("Include AliExpress", value=True)
excl_olx = st.sidebar.toggle("Exclude OLX (used/classifieds)", value=False)

st.sidebar.subheader("AI / RAG")
temperature = st.sidebar.slider("LLM temperature", 0.0, 1.0, 0.2, 0.05)
use_dense = st.sidebar.toggle("Dense embeddings (bge-small)", value=True)
use_rerank = st.sidebar.toggle("Cross-encoder reranker", value=True)
per_store = st.sidebar.slider("Search engines used per store", 1, 3, 2,
                              help="Each engine call uses API credits. Lower = cheaper, higher = more coverage.")
meta_max = st.sidebar.slider("Page price lookups per search", 0, 60, 40,
                             help="Fetches product pages (robots.txt-aware) when search snippets show no price.")
show_trace = st.sidebar.toggle("Show agent trace live", value=True)

settings = RunSettings(
    display_currency=currency, min_price=min_price or None, max_price=max_price or None,
    target_results=target, min_platforms=min_platforms, per_platform_cap=cap, max_rounds=rounds,
    providers=chosen_providers, categories=cats, platform_domains=[names[n] for n in chosen_platforms],
    include_aliexpress=inc_ali, exclude_olx=excl_olx, temperature=temperature,
    use_dense=use_dense, use_reranker=use_rerank, max_meta_fetches=meta_max, providers_per_domain=per_store,
)

# ------------------------------------------------------------------ main
st.title("🛒 BuyWiseAI")
st.caption("AI price comparison across Pakistani stores + AliExpress: multi-agent search, hybrid RAG, verified results only.")

with st.form("search"):
    q_col, b_col = st.columns([6, 1])
    query = q_col.text_input("What do you want to buy?", placeholder="e.g. Samsung Galaxy A55 128GB, Haier 1.5 ton inverter AC")
    submitted = b_col.form_submit_button("Search", type="primary", use_container_width=True)

if submitted and query.strip():
    key, cache = cache_key(query, settings), shared_cache()
    hit = cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        st.session_state["result"] = hit[1]
        st.toast("Loaded from cache (30 min)")
    else:
        final: dict = {}
        with st.status("Agents working...", expanded=show_trace) as box:
            try:
                for node, update, final in stream_pipeline(query.strip(), settings):
                    box.update(label=f"{AGENT_LABELS.get(node, node)} done")
                    if show_trace:
                        st.markdown(f"**{AGENT_LABELS.get(node, node)}**")
                        for line in update.get("trace", []):
                            st.text(line)
                box.update(label="Done", state="complete")
            except Exception as e:  # never show a raw traceback to end users
                box.update(label="Something went wrong", state="error")
                st.error(f"Search failed: {e}")
                final = {}
        if final.get("selected") is not None:
            cache[key] = (time.time(), final)
            st.session_state["result"] = final

result = st.session_state.get("result")
if result:
    selected = [Listing(**d) for d in result.get("selected", [])]
    stat = result.get("status", {})
    tab_res, tab_ai, tab_trace = st.tabs(["Results", "AI Recommendation", "Agent Trace / Debug"])

    with tab_res:
        if not selected:
            st.warning("No verified results found. Try a broader query, more providers, or fewer filters.")
            trace_text = "\n".join(result.get("trace", []))
            if "No search provider available" in trace_text:
                st.error("No search provider is available. Add a search API key (e.g. SERPER_API_KEY) to your secrets.")
            elif "-> 0 raw hits" in trace_text and "-> 0 raw hits" not in trace_text.replace("-> 0 raw hits", "", 1) and "raw hits" in trace_text:
                st.error("The search engines returned nothing at all. Check that your API keys are valid and "
                         "not out of credits, and add another engine key (SERPAPI_API_KEY, BRAVE_API_KEY).")
            if "failed call" in trace_text:
                st.info("Some search calls failed. This is usually an invalid key, an exhausted quota, or a blocked engine.")
            st.caption("Why nothing was found (copy this text if you need help):")
            st.code(trace_text or "No trace available.", language="text")
        else:
            if not stat.get("ok"):
                st.warning(f"Target not met: found {stat.get('count', 0)} verified results from "
                           f"{stat.get('platforms', 0)} platforms. Showing everything that passed verification.")
                with st.expander("Why not more results? (copy this and send it for help)", expanded=True):
                    st.code("\n".join(result.get("trace", [])) or "No trace.", language="text")
            else:
                st.success(f"{stat['count']} verified results from {stat['platforms']} platforms")
            sort = st.radio("Sort by", ["Best match", "Lowest price", "Highest rating"], horizontal=True)
            view = st.radio("View", ["Cards", "Table"], horizontal=True)
            shown = list(selected)
            if sort == "Lowest price":
                shown.sort(key=lambda l: l.price_pkr or float("inf"))
            elif sort == "Highest rating":
                shown.sort(key=lambda l: l.rating or -1, reverse=True)

            def disp(l: Listing) -> str:
                return format_price(convert(l.price_pkr, "PKR", currency), currency)

            if view == "Cards":
                for l in shown:
                    with st.container(border=True):
                        a, b, c, d = st.columns([5, 2, 2, 1.3])
                        a.markdown(f"**{l.title}**")
                        for n in l.notes:
                            a.caption(f"⚠️ {n}")
                        b.markdown(f"### {disp(l)}")
                        if l.currency != currency and l.price:
                            b.caption(f"Listed: {format_price(l.price, l.currency)}")
                        c.markdown(f"**{l.source}**")
                        c.caption("Trust " + "★" * l.trust_score + "☆" * (5 - l.trust_score)
                                  + (f" · Rating {l.rating}" if l.rating else ""))
                        d.link_button("Open ↗", l.url, use_container_width=True)
            else:
                df = pd.DataFrame([{
                    "Title": l.title, f"Price ({currency})": round(convert(l.price_pkr, "PKR", currency), 2),
                    "Source": l.source, "Trust": l.trust_score, "Rating": l.rating, "URL": l.url,
                    "Notes": " | ".join(l.notes),
                } for l in shown])
                st.dataframe(df, use_container_width=True, hide_index=True,
                             column_config={"URL": st.column_config.LinkColumn("URL", display_text="Open")})
            csv = pd.DataFrame([{
                "title": l.title, "price_pkr": l.price_pkr, "original_price": l.price, "original_currency": l.currency,
                "source": l.source, "url": l.url, "rating": l.rating, "notes": " | ".join(l.notes),
            } for l in shown]).to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Download CSV", csv, "buywiseai_results.csv", "text/csv")

    with tab_ai:
        st.markdown(result.get("recommendation") or "No recommendation available.")
        st.caption("Generated only from the verified listings above. Always check the seller page before paying.")

    with tab_trace:
        st.caption(f"Retrieval mode: {result.get('rag_mode', 'n/a')} · Rounds: {result.get('round', 0)}")
        st.code("\n".join(result.get("trace", [])) or "No trace.", language="text")
        with st.expander("Raw plan"):
            st.json(result.get("plan", {}))
else:
    st.info("Enter a product above. Tip: add specs (e.g. '128GB', '1.5 ton inverter') for better matches.")
