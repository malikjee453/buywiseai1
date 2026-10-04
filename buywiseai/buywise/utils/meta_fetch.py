"""Polite product-page metadata fetch (JSON-LD / OpenGraph price) as a LAST RESORT.

Rules: obey robots.txt, identify ourselves, one request at a time per domain with a
delay, tiny timeout, no bypassing of protections. Returns None on any doubt.
"""
from __future__ import annotations

import json
import logging
import re
import time
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


def fetch_product_meta(url: str) -> tuple[float, str] | None:
    domain = get_domain(url)
    try:
        if not _allowed(url):
            return None
        wait = 1.0 - (time.time() - _last_fetch.get(domain, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_fetch[domain] = time.time()
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=8)
        if r.status_code != 200:
            return None
        return parse_product_meta(r.text)
    except Exception as e:
        log.info("meta fetch failed for %s: %s", url, e)
        return None
