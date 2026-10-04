"""Configuration: secrets, settings.yaml, platform whitelist, per-run settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ["general", "electronics", "fashion", "grocery", "health", "home"]


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a secret from env vars first, then Streamlit secrets. Never hardcode keys."""
    val = os.environ.get(name)
    if val:
        return val
    try:
        import streamlit as st  # imported lazily so tests/CLI work without Streamlit

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


@dataclass(frozen=True)
class Platform:
    name: str
    domain: str
    category: str
    country: str = "PK"
    currency: str = "PKR"
    trust_score: int = 3


@lru_cache(maxsize=1)
def load_app_settings() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_platforms() -> tuple[Platform, ...]:
    with open(ROOT / "config" / "platforms.yaml", encoding="utf-8") as f:
        rows = yaml.safe_load(f) or []
    return tuple(Platform(**row) for row in rows)


def match_platform(domain: str, platforms=None) -> Platform | None:
    """Return the whitelisted platform whose domain matches (incl. subdomains)."""
    domain = (domain or "").lower()
    for p in platforms or load_platforms():
        if domain == p.domain or domain.endswith("." + p.domain):
            return p
    return None


def match_platform_by_name(name: str | None, platforms=None) -> Platform | None:
    """Match a merchant name (e.g. from Google Shopping) to a whitelisted platform."""
    if not name:
        return None
    n = "".join(ch for ch in name.lower() if ch.isalnum())
    for p in platforms or load_platforms():
        pn = "".join(ch for ch in p.name.lower() if ch.isalnum())
        dn = p.domain.split(".")[0].replace("-", "")
        if n == pn or n == dn or n.startswith(pn) or n.startswith(dn):
            return p
    return None


@dataclass
class RunSettings:
    """Everything the UI can tweak for one search run (JSON-serialisable)."""

    display_currency: str = "PKR"
    min_price: float | None = None          # in display currency
    max_price: float | None = None
    target_results: int = 10
    min_platforms: int = 6
    per_platform_cap: int = 2
    max_rounds: int = 3
    providers: list[str] = field(default_factory=list)   # empty = all available
    categories: list[str] = field(default_factory=list)  # empty = auto-detect
    platform_domains: list[str] = field(default_factory=list)  # empty = whitelist
    include_aliexpress: bool = True
    exclude_olx: bool = False
    temperature: float = 0.2
    use_dense: bool = True
    use_reranker: bool = True
    rerank_threshold: float = -3.0
    require_price: bool = True
    max_meta_fetches: int = 40
    meta_fetches_per_round: int = 20
    use_shopify_feeds: bool = True
    expand_per_round: int = 6
    domains_per_round: int = 10
    providers_per_domain: int = 2
