"""Serper.dev: Google web search + Google Shopping."""
from __future__ import annotations

from buywise.providers.base import SearchProvider, http_json, price_text_from
from buywise.schemas import RawResult


class SerperProvider(SearchProvider):
    name = "serper"
    env_key = "SERPER_API_KEY"
    supports_shopping = True

    def _post(self, endpoint: str, payload: dict) -> dict:
        return http_json(
            "POST", f"https://google.serper.dev/{endpoint}",
            headers={"X-API-KEY": self.key, "Content-Type": "application/json"}, json=payload,
        )

    def search(self, query, domain=None, num=10):
        data = self._post("search", {"q": self.site_query(query, domain), "gl": "pk", "hl": "en", "num": num})
        out = []
        for it in data.get("organic", []):
            out.append(RawResult(
                title=it.get("title", ""), url=it.get("link", ""), snippet=it.get("snippet", ""),
                price_text=price_text_from(it), rating=it.get("rating"), provider=self.name,
            ))
        return out

    def shopping(self, query, num=10):
        data = self._post("shopping", {"q": query, "gl": "pk", "hl": "en", "num": num})
        out = []
        for it in data.get("shopping", []):
            out.append(RawResult(
                title=it.get("title", ""), url=it.get("link", ""), price_text=it.get("price"),
                source=it.get("source"), rating=it.get("rating"), provider=self.name, from_shopping=True,
            ))
        return out
