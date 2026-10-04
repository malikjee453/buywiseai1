"""DuckDuckGo via the `ddgs` package (no API key)."""
from __future__ import annotations

from buywise.providers.base import SearchProvider
from buywise.schemas import RawResult


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"
    env_key = None

    def search(self, query, domain=None, num=10):
        try:
            from ddgs import DDGS
        except ImportError:  # older package name
            from duckduckgo_search import DDGS
        hits = DDGS(timeout=10).text(self.site_query(query, domain), region="pk-en", max_results=num) or []
        return [
            RawResult(title=h.get("title", ""), url=h.get("href", ""), snippet=h.get("body", ""), provider=self.name)
            for h in hits
        ]
