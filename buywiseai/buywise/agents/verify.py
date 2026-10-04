"""Verification Agent: drop invalid listings, flag suspicious ones. Never invents data."""
from __future__ import annotations

from collections import Counter, defaultdict

from buywise.config import RunSettings, match_platform
from buywise.schemas import Listing, QueryPlan
from buywise.utils.currency import convert
from buywise.utils.relevance import lexical_match, is_accessory, is_price_outlier_low, median_price, title_matches_model, gender_conflict
from buywise.utils.url_utils import is_foreign_storefront, is_product_url


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
        elif is_foreign_storefront(l.domain):
            _drop("foreign_storefront", l)
        elif "shopping_link" not in l.flags and match_platform(l.domain) is None:
            _drop("not_whitelisted", l)
        elif "shopping_link" not in l.flags and not is_product_url(l.url):
            _drop("not_product_page", l)
        elif settings.require_price and (l.price_pkr is None or l.price_pkr <= 0):
            _drop("no_price", l)
        elif not plan.used_ok and is_accessory(l.title, plan.original):
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
    best: dict[tuple, Listing] = {}
    for l in valid:
        k = (l.domain, round(l.price_pkr or 0))
        if k not in best or l.score > best[k].score:
            best[k] = l
    if len(best) < len(valid):
        drops["duplicate_offer"] += len(valid) - len(best)
        valid = [l for l in valid if best[(l.domain, round(l.price_pkr or 0))] is l]
    med = median_price([l.price_pkr for l in valid if l.price_pkr])
    for l in valid:
        if l.price_pkr and is_price_outlier_low(l.price_pkr, med, len(valid)):
            l.flags.append("price_far_below_median")
            l.notes.append("Price far below the median: possibly used, an accessory, or a scam. Double-check.")
        if l.domain.endswith("aliexpress.com") or l.source == "AliExpress":
            l.notes.append("International shipping: customs/delivery time may apply.")
        if l.domain.endswith("olx.com.pk"):
            l.notes.append("Classified listing: may be used / negotiable.")
    return valid, dict(drops), dict(samples)
