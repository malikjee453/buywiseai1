"""Relevance Judge: one batched LLM call that rejects listings of the wrong product type.

Rules/regex catch accessories, wrong models and wrong gender; this catches the rest
(e.g. a jhumka earring returned for "shalwar kameez"). Fails open: if the LLM is
unavailable, rate-limited or returns garbage, nothing extra is dropped (the rule-based checks still apply).

Verdicts are cached per (query, url, title) for the life of the process, so later search rounds and repeated
searches never pay twice for the same listing (this matters on Groq's free daily token cap).
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

_VERDICTS: dict[tuple[str, str, str], bool] = {}


def _slug(url: str) -> str:
    return (urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])[:70]


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes"))


def _key(query: str, l) -> tuple[str, str, str]:
    return (query, l.url, l.title)


def judge_relevance(listings: list, query: str, llm: LLM | None, max_items: int = 40) -> tuple[list, int]:
    """Returns (kept_listings, number_dropped)."""
    judge_relevance.last_dropped = []
    judge_relevance.last_status = "not run"
    if not listings:
        return listings, 0
    ranked = sorted(listings, key=lambda l: l.score, reverse=True)
    head, tail = ranked[:max_items], ranked[max_items:]
    todo = [l for l in head if _key(query, l) not in _VERDICTS]
    cached = len(head) - len(todo)
    status = None
    if todo:
        if llm is None or not llm.available():
            status = "skipped (no GROQ_API_KEY): nothing filtered"
        else:
            payload = "\n".join(f"{i}. {l.title} | {l.source} | {_slug(l.url)}" for i, l in enumerate(todo))
            data, err = None, None
            for max_tok in (3000, 7000):      # reasoning tokens count against the limit: retry once with more headroom
                try:
                    data = llm.chat_json(SYSTEM, f"User wants to buy: {query}\n\nListings:\n{payload}",
                                         temperature=0.0, reasoning="low", max_tokens=max_tok)
                    break
                except LLMError as e:
                    err = e
                    if "rate limit" in str(e).lower():
                        break                 # a bigger request cannot help when the account is capped
            if data is None:
                log.warning("Relevance judge skipped: %s", err)
                status = (f"RATE-LIMITED ({str(err)[:110]}): using rule-based checks only" if err and "rate limit" in str(err).lower()
                          else f"FAILED ({str(err)[:90]}): nothing filtered, so results may include wrong items")
            else:
                for it in data.get("items", []):
                    try:
                        i = int(it["id"])
                        if 0 <= i < len(todo):
                            _VERDICTS[_key(query, todo[i])] = _truthy(it.get("match"))
                    except (KeyError, ValueError, TypeError):
                        continue
    kept_head = [l for l in head if _VERDICTS.get(_key(query, l), True)]   # unknown => keep
    judge_relevance.last_dropped = [f"{l.title[:45]} ({l.source})" for l in head if not _VERDICTS.get(_key(query, l), True)]
    dropped = len(head) - len(kept_head)
    judge_relevance.last_status = status or f"checked {len(head)} listings ({cached} from cache), rejected {dropped}"
    return kept_head + tail, dropped
