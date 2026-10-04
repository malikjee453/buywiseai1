"""SerpAPI: Google Shopping."""
from __future__ import annotations

from buywise.providers.base import SearchProvider, http_json
from buywise.schemas import RawResult


class SerpApiProvider(SearchProvider):
    name = "serpapi"
    env_key = "SERPAPI_API_KEY"
    supports_shopping = True

    def _get(self, params: dict) -> dict:
        return http_json("GET", "https://serpapi.com/search.json", params={**params, "api_key": self.key})

    def search(self, query, domain=None, num=10):
        data = self._get({"engine": "google", "q": self.site_query(query, domain), "gl": "pk", "hl": "en", "num": num})
        return [
            RawResult(title=it.get("title", ""), url=it.get("link", ""), snippet=it.get("snippet", ""), provider=self.name)
            for it in data.get("organic_results", [])
        ]

    def shopping(self, query, num=10):
        data = self._get({"engine": "google_shopping", "q": query, "gl": "pk", "hl": "en"})
        out = []
        for it in data.get("shopping_results", [])[:num]:
            out.append(RawResult(
                title=it.get("title", ""), url=it.get("product_link") or it.get("link", ""),
                price_text=it.get("price"), price=it.get("extracted_price"),
                source=it.get("source"), rating=it.get("rating"), provider=self.name, from_shopping=True,
            ))
        return out
