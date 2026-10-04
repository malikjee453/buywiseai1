"""Recommendation Agent: writes the comparison using ONLY verified listings."""
from __future__ import annotations

import json
import logging
import re

from buywise.llm import LLM, LLMError
from buywise.schemas import Listing
from buywise.utils.currency import convert, format_price

log = logging.getLogger(__name__)

SYSTEM = (
    "You are a careful shopping assistant for Pakistan. You are given a JSON list of VERIFIED "
    "listings. Use ONLY that data: never invent prices, products, sellers or links, and cite "
    "results by their number like [3]. Write concise Markdown (max ~220 words) with: "
    "**Cheapest**, **Best value**, **Most trusted seller**, and **Caveats** (mention AliExpress "
    "customs/delivery time, OLX used/negotiable items, flagged suspicious prices, and any shortfall "
    "in results). If listings differ in specs, say prices may not be like-for-like. "
    "Never call a listing flagged price_far_below_median the Cheapest or Best value; warn about it instead."
)


def _fallback(listings: list[Listing], currency: str) -> str:
    """Deterministic summary used when the LLM is unavailable."""
    priced = [l for l in listings if l.price_pkr]
    if not priced:
        return "No priced results to compare."
    cheapest = min(priced, key=lambda l: l.price_pkr)
    trusted = max(priced, key=lambda l: (l.trust_score, -l.price_pkr))
    fmt = lambda l: format_price(convert(l.price_pkr, "PKR", currency), currency)
    return (
        f"**Cheapest:** {cheapest.title} at {cheapest.source} for {fmt(cheapest)}.\n\n"
        f"**Most trusted seller:** {trusted.source} ({trusted.trust_score}/5): {trusted.title}, {fmt(trusted)}.\n\n"
        "_AI summary unavailable; this is an automatic summary of the verified results._"
    )


def _strip_unknown_urls(text: str, allowed: set[str]) -> str:
    """Guardrail: remove any URL the model produced that is not in the verified data."""
    return re.sub(r"https?://\S+", lambda m: m.group(0) if m.group(0).rstrip(").,]") in allowed else "", text)


def recommend(listings: list[Listing], query: str, currency: str, llm: LLM, shortfall: str | None = None) -> str:
    if not listings:
        return "No verified results were found, so there is nothing to recommend."
    rows = [{
        "n": i + 1, "title": l.title, "source": l.source, "trust_score_1_to_5": l.trust_score,
        "price": round(convert(l.price_pkr, "PKR", currency), 2) if l.price_pkr else None, "currency": currency,
        "rating": l.rating, "flags": l.flags, "notes": l.notes, "url": l.url,
    } for i, l in enumerate(listings)]
    if not llm.available():
        return _fallback(listings, currency)
    user = f"User query: {query}\nShortfall: {shortfall or 'none'}\nVERIFIED listings:\n{json.dumps(rows, ensure_ascii=False)}"
    try:
        text = llm.chat(SYSTEM, user, reasoning="medium", max_tokens=4000)
    except LLMError as e:
        log.warning("Recommendation LLM failed: %s", e)
        return _fallback(listings, currency)
    return _strip_unknown_urls(text, {l.url for l in listings}) or _fallback(listings, currency)
