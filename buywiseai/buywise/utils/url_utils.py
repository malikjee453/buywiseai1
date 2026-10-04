"""URL canonicalisation, domain helpers, product-page detection, dedup."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from buywise.config import load_app_settings, match_platform

# Domains whose product identity lives entirely in the path
_DROP_ALL_QUERY = ("daraz.pk", "aliexpress.com", "olx.com.pk")
# Strict product-path rules for sites whose URL scheme we're confident about
# Regexes searched in the lowercase path. Daraz also serves legacy product URLs like /i123456-s789.html
_PRODUCT_PATH_RULES = {
    "daraz.pk": r"/products/|/i\d+(?:-s\d+)?\.html$",
    "aliexpress.com": r"/item/",
    "olx.com.pk": r"/item/",
}


def get_domain(url: str) -> str:
    host = urlparse(url if "//" in url else "//" + url).netloc.lower()
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _base_domain(domain: str) -> str:
    for d in _DROP_ALL_QUERY:
        if domain == d or domain.endswith("." + d):
            return d
    return domain


def canonicalize_url(url: str) -> str:
    """Lowercase host, drop www/fragment/tracking params, strip trailing slash."""
    if not url:
        return ""
    p = urlparse(url.strip())
    scheme = "https"
    domain = get_domain(url)
    path = re.sub(r"/+$", "", p.path) or "/"
    if _base_domain(domain) in _DROP_ALL_QUERY:
        query = ""
    else:
        tracking = set(load_app_settings().get("tracking_params", []))
        kept = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in tracking]
        query = urlencode(sorted(kept))
    return urlunparse((scheme, domain, path, "", query, ""))


def is_product_url(url: str) -> bool:
    """Heuristic: True for product pages, False for search/category/home pages."""
    if not url:
        return False
    cfg = load_app_settings()
    p = urlparse(url)
    domain = get_domain(url)
    path = p.path.lower()
    if path in ("", "/"):
        return False
    rule = _PRODUCT_PATH_RULES.get(_base_domain(domain))
    if rule:
        return re.search(rule, path) is not None
    bad_keys = {k.lower() for k in cfg.get("non_product_query_keys", [])}
    if any(k.lower() in bad_keys for k, _ in parse_qsl(p.query)):
        return False
    segments = [s for s in path.split("/") if s]
    bad_segments = set(cfg.get("non_product_segments", []))
    if "products" not in segments and any(s in bad_segments for s in segments):
        return False
    return True


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def dedupe(listings: list) -> list:
    """Drop duplicates: same canonical URL, or same platform + title + price."""
    seen_urls: set[str] = set()
    seen_sig: set[tuple] = set()
    out = []
    for l in listings:
        key = canonicalize_url(l.url)
        sig = (l.domain, _title_key(l.title), round(l.price or 0))
        if key in seen_urls or (sig[1] and sig in seen_sig):
            continue
        seen_urls.add(key)
        seen_sig.add(sig)
        out.append(l)
    return out


_FOREIGN_PREFIXES = {"us", "uk", "uae", "ae", "ca", "au", "eu", "sa", "qa", "kw", "om", "bh", "de", "fr", "in", "global", "int", "intl"}


def is_foreign_storefront(domain: str) -> bool:
    """True for regional shops like us.khaadi.com / uae.gulahmedshop.com (other currency, no PK delivery).

    AliExpress is exempt: its regional subdomains are just language/locale variants.
    """
    plat = match_platform(domain)
    if plat is None or plat.domain == "aliexpress.com":
        return False
    sub = domain[: -len(plat.domain)].rstrip(".")
    return bool(sub) and sub.split(".")[0] in _FOREIGN_PREFIXES


def is_rankable(l) -> bool:
    """Cheap pre-check mirroring verification's structural rules.

    Category pages, blog posts, off-whitelist hits and foreign storefronts can never become results,
    so they must not occupy slots in the (limited) reranker / enrichment budget.
    """
    if "shopping_link" in getattr(l, "flags", []):
        return True
    return (match_platform(l.domain) is not None and not is_foreign_storefront(l.domain)
            and is_product_url(l.url))
