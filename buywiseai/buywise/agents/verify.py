"""Verification Agent: drop invalid listings, flag suspicious ones. Never invents data."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from buywise.config import RunSettings, match_platform
from buywise.schemas import Listing, QueryPlan
from buywise.utils.currency import convert
from buywise.utils.relevance import lexical_match, is_accessory, is_price_outlier_low, is_price_outlier_high, median_price, title_matches_model, gender_conflict
from buywise.utils.url_utils import is_foreign_storefront, is_product_url


def _similar_titles(a: str, b: str, min_jaccard: float = 0.6) -> bool:
    ta, tb = set(re.findall(r"[a-z0-9]+", a.lower())), set(re.findall(r"[a-z0-9]+", b.lower()))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= min_jaccard


def _price_bounds_pkr(settings: RunSettings, plan: QueryPlan) -> tuple[float | None, float | None]:
    lo = convert(settings.min_price, settings.display_currency, "PKR") if settings.min_price else None
    hi = convert(settings.max_price, settings.display_currency, "PKR") if settings.max_price else None
    if hi is None and plan.max_budget_pkr:
        hi = plan.max_budget_pkr * 1.05     # small tolerance for "under 50k"
    return lo, hi


def verify_listings(pool: list[Listing], settings: RunSettings, plan: QueryPlan) -> tuple[list[Listing], dict, dict]:
    """Returns (valid listings, drop-reason counts)."""
    drops: Counter = Counter()
    samples: dict[str, list[str]] = defaultdict(list)

    def _drop(reason: str, l: Listing) -> None:
        drops[reason] += 1
        if len(samples[reason]) < 3:
            samples[reason].append(f"{l.title[:45]} [rel={l.relevance:.1f}]" if reason == "low_relevance" else l.url)

    lo, hi = _price_bounds_pkr(settings, plan)
    valid: list[Listing] = []
    for l in pool:
        l.flags = [f for f in l.flags if f in ("shopping_link",)]
        l.notes = [n for n in l.notes if n == "Link goes via Google Shopping"]
        if not l.url.startswith("http"):
            _drop("invalid_url", l)
        elif "shopping_link" in l.flags and not settings.allow_shopping_links:
            _drop("google_link_not_store_url", l)     # a google.com redirect is not the store's own page
        elif is_foreign_storefront(l.domain):
            _drop("foreign_storefront", l)
        elif "shopping_link" not in l.flags and match_platform(l.domain) is None:
            _drop("not_whitelisted", l)
        elif "shopping_link" not in l.flags and not is_product_url(l.url):
            _drop("not_product_page", l)
        elif settings.require_price and (l.price_pkr is None or l.price_pkr <= 0):
            _drop("no_price", l)
        elif not plan.used_ok and is_accessory(l.title, plan.original, l.url):
            _drop("accessory", l)
        elif gender_conflict(l.title, l.url, plan.original):
            _drop("gender_mismatch", l)
        elif not title_matches_model(l.title, l.url, plan.original):
            _drop("model_mismatch", l)
        elif l.relevance < settings.rerank_threshold and not lexical_match(l.title, l.url, l.snippet, plan.product):
            _drop("low_relevance", l)
        elif lo is not None and l.price_pkr is not None and l.price_pkr < lo:
            _drop("below_min_price", l)
        elif hi is not None and l.price_pkr is not None and l.price_pkr > hi:
            _drop("above_max_price", l)
        else:
            valid.append(l)
    # Same store + same price + same model = the same offer reached via different pages
    # ...but a store's feed lists many DIFFERENT products at the same price (e.g. 92 were merged in one run),
    # so only treat them as one offer when their titles are also near-identical.
    kept: list[Listing] = []
    for l in sorted(valid, key=lambda x: x.score, reverse=True):
        if any(k.domain == l.domain and round(k.price_pkr or 0) == round(l.price_pkr or 0)
               and _similar_titles(k.title, l.title) for k in kept):
            drops["duplicate_offer"] += 1
            continue
        kept.append(l)
    keep_ids = {id(k) for k in kept}
    valid = [l for l in valid if id(l) in keep_ids]
    med = median_price([l.price_pkr for l in valid if l.price_pkr])
    for l in valid:
        if l.price_pkr and is_price_outlier_low(l.price_pkr, med, len(valid)):
            l.flags.append("price_far_below_median")
            l.notes.append("Price far below the median: possibly used, an accessory, or a scam. Double-check.")
        if l.domain.endswith("aliexpress.com") or l.source == "AliExpress":
            l.notes.append("International shipping: customs/delivery time may apply.")
        if l.domain.endswith("olx.com.pk"):
            l.notes.append("Classified listing: may be used / negotiable.")
    # A far-below-median price that came only from a snippet/LLM (never confirmed on the product page) is
    # more likely a parsing slip, placeholder or bait price than a real offer: drop it. Page/API prices keep a warning.
    shaky = {id(l) for l in valid if "price_far_below_median" in l.flags and l.price_origin in ("text", "llm")}
    # Same idea upwards: a snippet price 8x above the median (e.g. "Rs 276,780" for a panty, read from a
    # '$1000' in the text) is a parsing slip. Prices confirmed on the page / API are kept.
    for l in valid:
        if l.price_pkr and l.price_origin in ("text", "llm") and is_price_outlier_high(l.price_pkr, med, len(valid)):
            shaky.add(id(l))
            if len(samples["unverified_price_outlier"]) < 3:
                samples["unverified_price_outlier"].append(l.url)
    if shaky:
        drops["unverified_price_outlier"] = len(shaky)
        valid = [l for l in valid if id(l) not in shaky]
    return valid, dict(drops), dict(samples)
