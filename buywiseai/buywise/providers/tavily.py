"""Tavily search API (supports include_domains natively)."""
from __future__ import annotations

from buywise.providers.base import SearchProvider, http_json
from buywise.schemas import RawResult


class TavilyProvider(SearchProvider):
    name = "tavily"
    env_key = "TAVILY_API_KEY"

    def search(self, query, domain=None, num=10):
        payload = {"query": query, "max_results": min(num, 20), "search_depth": "basic"}
        if domain:
            payload["include_domains"] = [domain]
        data = http_json(
            "POST", "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}, json=payload,
        )
        return [
            RawResult(title=it.get("title", ""), url=it.get("url", ""), snippet=it.get("content", ""), provider=self.name)
            for it in data.get("results", [])
        ]
