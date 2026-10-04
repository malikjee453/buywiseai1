"""SearchProvider abstract base class + HTTP helper with retries."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

import requests

from buywise.config import get_secret
from buywise.schemas import RawResult
from buywise.utils.redact import redact_secrets

log = logging.getLogger(__name__)


class _Fatal(RuntimeError):
    """Non-retryable HTTP error (4xx)."""


def http_json(method: str, url: str, *, retries: int = 2, timeout: float = 12, **kw) -> dict:
    """HTTP request returning parsed JSON. Retries 429/5xx; 4xx fail immediately with the server's message.

    Error text is redacted so API keys never reach logs or the UI trace.
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise _Fatal(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        except _Fatal as e:
            last = e
            break
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(redact_secrets(f"{url.split('?')[0]} failed: {last}"))


class SearchProvider(ABC):
    """Implement `search` (and optionally `shopping`) to add a new engine."""

    name: str = "base"
    env_key: str | None = None
    supports_shopping: bool = False

    def __init__(self) -> None:
        self.key = get_secret(self.env_key) if self.env_key else None

    def available(self) -> bool:
        return self.env_key is None or bool(self.key)

    @staticmethod
    def site_query(query: str, domain: str | None) -> str:
        return f"site:{domain} {query}" if domain else query

    @abstractmethod
    def search(self, query: str, domain: str | None = None, num: int = 10) -> list[RawResult]:
        """Web search, optionally restricted to one domain."""

    def shopping(self, query: str, num: int = 10) -> list[RawResult]:
        """Shopping-style search (price + merchant). Default: unsupported."""
        return []


def price_text_from(item: dict) -> str | None:
    """Find a price-like string in a search-result dict (rich snippets, attributes)."""
    for k in ("price", "priceRange", "price_text"):
        v = item.get(k)
        if v:
            return str(v)
    for k in ("attributes", "richSnippet", "rich_snippet"):
        v = item.get(k)
        if isinstance(v, dict):
            for kk, vv in v.items():
                if "price" in str(kk).lower() and vv:
                    return str(vv)
    return None
