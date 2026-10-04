"""USD <-> PKR conversion with a 12h cache and a configurable fallback constant."""
from __future__ import annotations

import logging
import time

import requests

from buywise.config import load_app_settings

log = logging.getLogger(__name__)
_cache: dict = {"ts": 0.0, "usd_pkr": None}


def get_usd_pkr() -> float:
    cfg = load_app_settings().get("fx", {})
    ttl = float(cfg.get("cache_hours", 12)) * 3600
    if _cache["usd_pkr"] and time.time() - _cache["ts"] < ttl:
        return _cache["usd_pkr"]
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=6)
        rate = float(r.json()["rates"]["PKR"])
        _cache.update(ts=time.time(), usd_pkr=rate)
        return rate
    except Exception as e:  # network down, API change, etc.
        log.warning("FX lookup failed (%s); using fallback rate", e)
        fallback = float(cfg.get("fallback_usd_pkr", 280.0))
        _cache.update(ts=time.time() - ttl + 300, usd_pkr=fallback)  # retry in 5 min
        return fallback


def convert(amount: float, src: str, dst: str) -> float:
    src, dst = src.upper(), dst.upper()
    if src == dst:
        return amount
    rate = get_usd_pkr()
    if src == "USD" and dst == "PKR":
        return amount * rate
    if src == "PKR" and dst == "USD":
        return amount / rate
    raise ValueError(f"Unsupported conversion {src}->{dst}")


def format_price(amount: float | None, currency: str) -> str:
    if amount is None:
        return "N/A"
    if currency.upper() == "USD":
        return f"${amount:,.2f}"
    return f"Rs {amount:,.0f}"
