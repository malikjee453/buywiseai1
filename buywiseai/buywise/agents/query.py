"""Query Understanding Agent: normalise the query, detect categories/budget, make variants."""
from __future__ import annotations

import logging
import re

from buywise.config import CATEGORIES, RunSettings
from buywise.llm import LLM, LLMError
from buywise.schemas import QueryPlan

log = logging.getLogger(__name__)

_KEYWORDS = {
    "electronics": ["phone", "mobile", "iphone", "samsung", "infinix", "tecno", "laptop", "tv", "led", "earbuds",
                    "airpods", "charger", "watch", "camera", "ac", "inverter", "fridge", "refrigerator",
                    "washing", "microwave", "gpu", "ssd", "ram", "monitor", "tablet", "headphone", "speaker"],
    "fashion": ["lawn", "suit", "shirt", "kurta", "shoes", "sneakers", "jeans", "dress", "shalwar", "kameez",
                "unstitched", "khussa", "bag", "jacket", "hoodie"],
    "grocery": ["rice", "oil", "ghee", "milk", "tea", "sugar", "flour", "atta", "biscuit", "juice", "snack"],
    "health": ["medicine", "tablet", "syrup", "vitamin", "supplement", "panadol", "mask", "thermometer"],
    "home": ["sofa", "bed", "mattress", "furniture", "table", "chair", "wardrobe", "curtain", "carpet", "lamp"],
}

SYSTEM = (
    "You are the query-understanding agent of a Pakistani shopping search engine. "
    "Return ONLY a JSON object with keys: product (string), brand (string|null), "
    f"categories (subset of {CATEGORIES}), max_budget_pkr (number|null), used_ok (boolean), "
    "variants (3-5 short search queries: the cleaned English query, model-number-only, brand+model, "
    "and a local-usage variant such as Roman Urdu/common Pakistani naming where it helps). "
    "Do not invent specs the user did not mention."
)


def _heuristic(query: str) -> QueryPlan:
    q = query.strip()
    low = q.lower()
    cats = {"general"}
    for cat, words in _KEYWORDS.items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low) for w in words):
            cats.add(cat)
    budget = None
    m = re.search(r"(?:under|below|less than|within|max|upto|up to)\s*(?:rs\.?|pkr)?\s*([\d,]+(?:\.\d+)?)\s*(k)?", low)
    if m:
        budget = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
    product = re.sub(r"\b(?:under|below|less than|within|max|upto|up to)\b.*$", "", q, flags=re.I).strip() or q
    return QueryPlan(
        original=q, product=product, categories=sorted(cats), max_budget_pkr=budget,
        variants=[product] if product == q else [product, q], used_ok="used" in low,
    )


def understand_query(query: str, settings: RunSettings, llm: LLM | None = None) -> tuple[QueryPlan, str]:
    """Returns (plan, note). Falls back to heuristics if the LLM is unavailable/fails."""
    base = _heuristic(query)
    llm = llm or LLM(temperature=0.0)
    note = "heuristic"
    if llm.available():
        try:
            data = llm.chat_json(SYSTEM, f"User query: {query}", temperature=0.0, reasoning="low")
            cats = [c for c in data.get("categories", []) if c in CATEGORIES] or base.categories
            variants = [v.strip() for v in data.get("variants", []) if isinstance(v, str) and v.strip()]
            budget = data.get("max_budget_pkr")
            base = QueryPlan(
                original=query, product=(data.get("product") or base.product).strip(),
                brand=data.get("brand") or None,
                categories=sorted(set(cats) | {"general"}),
                max_budget_pkr=float(budget) if isinstance(budget, (int, float)) else base.max_budget_pkr,
                variants=variants[:5], used_ok=bool(data.get("used_ok", base.used_ok)),
            )
            note = "llm"
        except (LLMError, ValueError, TypeError) as e:
            log.warning("Query LLM failed (%s); using heuristics", e)
    # Always keep the user's own wording first, then dedupe variants.
    seen, variants = set(), []
    for v in [query.strip(), base.product, *base.variants]:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            variants.append(v)
    base.variants = variants[:6]
    if settings.categories:
        base.categories = sorted(set(settings.categories) | {"general"})
    return base, note
