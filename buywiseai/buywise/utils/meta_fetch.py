"""Polite product-page metadata fetch (JSON-LD / OpenGraph price) as a LAST RESORT.

Rules: obey robots.txt, identify ourselves, one request at a time per domain with a
delay, tiny timeout, no bypassing of protections. Returns None on any doubt.
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from buywise.utils.url_utils import get_domain

log = logging.getLogger(__name__)
USER_AGENT = "BuyWiseAIBot/0.1 (price comparison; respects robots.txt)"
_robots: dict[str, RobotFileParser | None] = {}
_last_fetch: dict[str, float] = {}


def _allowed(url: str) -> bool:
    domain = get_domain(url)
    if domain not in _robots:
        rp = RobotFileParser()
        try:
            r = requests.get(f"https://{domain}/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=5)
            if r.status_code >= 400:
                rp = None  # no robots.txt => allowed
            else:
                rp.parse(r.text.splitlines())
        except Exception:
            rp = None
        _robots[domain] = rp
    rp = _robots[domain]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def parse_product_meta(html: str) -> tuple[float, str] | None:
    """Extract (price, currency) from JSON-LD Product offers or OpenGraph meta tags."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            offers = node.get("offers") if isinstance(node, dict) else None
            for offer in _walk(offers) if offers else []:
                price = offer.get("price") or offer.get("lowPrice")
                cur = offer.get("priceCurrency")
                try:
                    if price is not None and cur and float(str(price).replace(",", "")) > 0:
                        return float(str(price).replace(",", "")), str(cur).upper()
                except ValueError:
                    continue
    amount = re.search(r'property=["\'](?:product|og):price:amount["\'][^>]*content=["\']([\d.,]+)', html, re.I)
    cur = re.search(r'property=["\'](?:product|og):price:currency["\'][^>]*content=["\']([A-Za-z]{3})', html, re.I)
    if amount and cur:
        try:
            return float(amount.group(1).replace(",", "")), cur.group(1).upper()
        except ValueError:
            return None
    return None


# ------------------------------------------------------------------ Shopify public feeds
# Many Pakistani fashion/home stores run on Shopify. Their public storefront JSON
# (/collections/<handle>/products.json, /products/<handle>.json) lists products WITH prices.
# We use it only where robots.txt allows, at <=1 request/second per domain.
_COLLECTION_RE = re.compile(r"^/collections/([a-z0-9][a-z0-9\-_%]*)/?$", re.I)
_PRODUCT_RE = re.compile(r"^/(?:collections/[^/]+/)?products/([^/?#]+?)(?:\.json|\.js)?/?$", re.I)


def collection_handle(url: str) -> str | None:
    """'/collections/women-shalwar-kameez' -> 'women-shalwar-kameez' (None for products/other pages)."""
    m = _COLLECTION_RE.match(urlparse(url).path)
    return m.group(1).lower() if m else None


def product_handle(url: str) -> str | None:
    m = _PRODUCT_RE.match(urlparse(url).path)
    return m.group(1) if m else None


def _get_json(url: str) -> tuple[dict | None, str]:
    domain = get_domain(url)
    try:
        if not _allowed(url):
            return None, "robots"
        wait = 1.0 - (time.time() - _last_fetch.get(domain, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_fetch[domain] = time.time()
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=10)
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        return r.json(), "ok"
    except ValueError:
        return None, "not_json"
    except Exception as e:
        log.info("json fetch failed for %s: %s", url, e)
        return None, "error"


def _tags(raw) -> list[str]:
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return [str(t) for t in (raw or [])]


def feed_items(domain: str, products: list[dict]) -> list[dict]:
    """Shopify products.json -> [{title, url, price, snippet}] (in-stock, priced products only)."""
    out = []
    for p in products or []:
        variants = p.get("variants") or []
        avail = [v for v in variants if v.get("available", True)]
        prices = []
        for v in avail:
            try:
                prices.append(float(v.get("price")))
            except (TypeError, ValueError):
                continue
        prices = [x for x in prices if x > 0]
        handle, title = p.get("handle"), p.get("title")
        if not prices or not handle or not title:
            continue
        bits = [p.get("product_type") or "", p.get("vendor") or "", ", ".join(_tags(p.get("tags"))[:8])]
        out.append({"title": title, "url": f"https://{domain}/products/{handle}", "price": min(prices),
                    "snippet": " | ".join(b for b in bits if b)[:300]})
    return out


def fetch_collection_products(domain: str, handle: str, limit: int = 50) -> tuple[list[dict], str]:
    data, reason = _get_json(f"https://{domain}/collections/{handle}/products.json?limit={limit}")
    if data is None:
        return [], reason
    return feed_items(domain, data.get("products", [])), "ok"


def price_from_product_json(data: dict) -> float | None:
    items = feed_items("x", [data.get("product", data)] if isinstance(data, dict) else [])
    return items[0]["price"] if items else None


def fetch_product_meta_ex(url: str) -> tuple[tuple[float, str] | None, str]:
    """Returns (meta, reason). reason: ok | robots | http_<code> | no_price_in_page | error."""
    domain = get_domain(url)
    try:
        if not _allowed(url):
            return None, "robots"
        wait = 1.0 - (time.time() - _last_fetch.get(domain, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_fetch[domain] = time.time()
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=8)
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        meta = parse_product_meta(r.text)
        if meta:
            return meta, "ok"
        handle = product_handle(url)
        if handle:                                   # Shopify-style product: try its public JSON
            data, why = _get_json(f"https://{domain}/products/{handle}.json")
            price = price_from_product_json(data) if data else None
            if price:
                return (price, "PKR"), "ok_shopify_json"
        return None, "no_price_in_page"
    except Exception as e:
        log.info("meta fetch failed for %s: %s", url, e)
        return None, "error"


def fetch_product_meta(url: str) -> tuple[float, str] | None:
    return fetch_product_meta_ex(url)[0]
