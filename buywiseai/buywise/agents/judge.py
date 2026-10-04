"""Relevance Judge: one batched LLM call that rejects listings of the wrong product type.

Rules/regex catch accessories, wrong models and wrong gender; this catches the rest
(e.g. a jhumka earring returned for "shalwar kameez"). Fails open: if the LLM is
unavailable or returns garbage, nothing is dropped.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from buywise.llm import LLM, LLMError

log = logging.getLogger(__name__)

SYSTEM = (
    "You check whether shopping listings match what the user wants to buy. Be STRICT about product "
    "type (jewellery is not clothing; a phone case is not a phone; a charger is not a phone) but "
    "LENIENT about wording, brand, store naming and missing details. A listing whose title is vague "
    "but whose URL slug fits the product counts as a match. "
    "Treat 'girls', 'ladies', 'women' and 'female' as the SAME audience (female clothing); only treat the "
    "audience as children if the query says kids/children/toddler/baby or gives an age. Reject listings that are "
    "clearly for the opposite gender. Never reject because of colour, fabric, style, embroidery, brand or price. "
    "Reject a different model or variant than the one named (e.g. Pro/Plus/Max when the base model is asked). "
    'Respond with JSON only: {"items":[{"id":int,"match":true|false}]} covering every id.'
)


def _slug(url: str) -> str:
    return (urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])[:70]


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes"))


def judge_relevance(listings: list, query: str, llm: LLM | None, max_items: int = 40) -> tuple[list, int]:
    """Returns (kept_listings, number_dropped)."""
    judge_relevance.last_dropped = []
    if not listings or llm is None or not llm.available():
        return listings, 0
    ranked = sorted(listings, key=lambda l: l.score, reverse=True)
    head, tail = ranked[:max_items], ranked[max_items:]
    payload = "\n".join(f"{i}. {l.title} | {l.source} | {_slug(l.url)}" for i, l in enumerate(head))
    try:
        data = llm.chat_json(SYSTEM, f"User wants to buy: {query}\n\nListings:\n{payload}",
                             temperature=0.0, reasoning="low", max_tokens=3000)
    except LLMError as e:
        log.warning("Relevance judge skipped: %s", e)
        return listings, 0
    verdict: dict[int, bool] = {}
    for it in data.get("items", []):
        try:
            verdict[int(it["id"])] = _truthy(it.get("match"))
        except (KeyError, ValueError, TypeError):
            continue
    kept_head = [l for i, l in enumerate(head) if verdict.get(i, True)]   # unknown id => keep
    judge_relevance.last_dropped = [f"{l.title[:45]} ({l.source})" for i, l in enumerate(head) if not verdict.get(i, True)]
    return kept_head + tail, len(head) - len(kept_head)
