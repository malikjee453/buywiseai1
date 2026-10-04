"""Extraction Agent: raw hits -> strict Listing schema (regex first, LLM only when messy)."""
from __future__ import annotations

import logging
import re

from buywise.config import RunSettings, match_platform, match_platform_by_name
from buywise.llm import LLM, LLMError
from buywise.schemas import Listing, RawResult
from buywise.utils.currency import convert
from buywise.utils.price_parser import count_prices, find_price, parse_price
from buywise.utils.url_utils import get_domain

log = logging.getLogger(__name__)

LLM_SYSTEM = (
    "You extract prices from search-result text. For each item return a price ONLY if a price "
    "literally appears in its text. Never guess or convert. Respond with JSON: "
    '{"items":[{"id":int,"price":number|null,"currency":"PKR"|"USD"|null}]}.'
)


def _clean_title(title: str, platform_name: str, domain: str) -> str:
    """Drop trailing ' | Daraz.pk' style site suffixes."""
    parts = re.split(r"\s+[|\-–—]\s+", title.strip())
    if len(parts) > 1:
        tail = parts[-1].lower()
        key = domain.split(".")[0]
        if key in tail.replace(" ", "") or platform_name.lower() in tail:
            parts = parts[:-1]
    title = " - ".join(parts).strip()
    cut = re.split(r"\s*(?:\.\.\.|…)", title)[0].strip()       # sitelinks glued after an ellipsis
    if len(cut) >= 10:
        title = cut
    return title[:120].rstrip()


def _to_listing(raw: RawResult, platforms) -> Listing | None:
    domain = get_domain(raw.url)
    plat = match_platform(domain, platforms)
    shopping_proxy = False
    if plat is None and raw.from_shopping:           # Google-Shopping link: match by merchant name
        plat = match_platform_by_name(raw.source, platforms)
        shopping_proxy = plat is not None
    if plat is None or not raw.title:
        return None
    price, cur, origin = raw.price, raw.currency, "api"
    if price is None:
        parsed = parse_price(raw.price_text)
        # Text with 3+ prices is a list/category page: any single price would be a guess
        if not parsed and count_prices(f"{raw.title} {raw.snippet}") < 3:
            parsed = find_price(raw.title, raw.snippet)
        if parsed:
            price, cur = parsed.amount, parsed.currency
            origin = "api" if raw.price_text and parse_price(raw.price_text) else "text"
    price_pkr = None
    if price is not None:
        cur = (cur or plat.currency).upper()
        try:
            price_pkr = convert(price, cur, "PKR")
        except ValueError:
            price, price_pkr = None, None
    listing = Listing(
        title=_clean_title(raw.title, plat.name, plat.domain), price=price, currency=cur or plat.currency,
        price_pkr=price_pkr, source=plat.name, domain=plat.domain, url=raw.url, rating=raw.rating,
        snippet=(raw.snippet or "")[:300], trust_score=plat.trust_score, provider=raw.provider, price_origin=origin,
    )
    if shopping_proxy:
        listing.notes.append("Link goes via Google Shopping")
        listing.domain = domain or plat.domain
        listing.flags.append("shopping_link")
    return listing


def extract_listings(raws: list[RawResult], settings: RunSettings, llm: LLM | None = None) -> tuple[list[Listing], list[str]]:
    from buywise.agents.search import active_platforms

    platforms = active_platforms(settings)
    listings, rejected = [], 0
    for r in raws:
        l = _to_listing(r, platforms)
        if l:
            listings.append(l)
        else:
            rejected += 1
    trace = [f"{len(listings)} whitelisted listings ({rejected} off-whitelist hits discarded)"]
    trace += _llm_fill_prices(listings, llm)
    return listings, trace


def _llm_fill_prices(listings: list[Listing], llm: LLM | None) -> list[str]:
    """One batched JSON-mode call for listings with no price but a plausible snippet."""
    llm = llm or LLM(temperature=0.0)
    todo = [l for l in listings if l.price is None and len(l.snippet) > 30][:15]
    if not todo or not llm.available():
        return []
    payload = "\n".join(f'{i}. TITLE: {l.title}\n   TEXT: {l.snippet}' for i, l in enumerate(todo))
    try:
        data = llm.chat_json(LLM_SYSTEM, payload, temperature=0.0, reasoning="low", max_tokens=2500)
    except LLMError as e:
        return [f"LLM price extraction skipped ({e})"]
    filled = 0
    for item in data.get("items", []):
        try:
            l, price = todo[int(item["id"])], item.get("price")
            if price is None:
                continue
            price, cur = float(price), (item.get("currency") or "PKR").upper()
            digits = str(int(price))
            haystack = (l.title + " " + l.snippet).replace(",", "")
            if digits not in haystack:        # anti-hallucination: number must literally appear
                continue
            l.price, l.currency, l.price_origin = price, cur, "llm"
            l.price_pkr = convert(price, cur, "PKR")
            filled += 1
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    return [f"LLM recovered {filled} price(s) from messy snippets"] if filled else []
