"""SerpAPI: Google Shopping."""
from __future__ import annotations

from buywise.providers.base import SearchProvider, http_json
from buywise.schemas import RawResult


def serpapi_get(params: dict) -> dict:
    """Call SerpApi; turn its in-body errors into exceptions ("no results" is not an error)."""
    data = http_json("GET", "https://serpapi.com/search.json", params=params)
    err = data.get("error") if isinstance(data, dict) else None
    if err:
        if "hasn't returned any results" in err.lower() or "no results" in err.lower():
            return {}
        raise RuntimeError(f"SerpApi: {err}")
    return data


class SerpApiProvider(SearchProvider):
    name = "serpapi"
    env_key = "SERPAPI_API_KEY"
    supports_shopping = True
    _shopping_gl: str | None = "pk"

    def _get(self, params: dict) -> dict:
        return serpapi_get({**params, "api_key": self.key})

    def search(self, query, domain=None, num=10):
        data = self._get({"engine": "google", "q": self.site_query(query, domain), "gl": "pk", "hl": "en", "num": num})
        return [
            RawResult(title=it.get("title", ""), url=it.get("link", ""), snippet=it.get("snippet", ""), provider=self.name,
                      image_url=it.get("thumbnail"))
            for it in data.get("organic_results", [])
        ]

    def shopping(self, query, num=10):
        params = {"engine": "google_shopping", "q": query, "hl": "en"}
        if SerpApiProvider._shopping_gl:
            params["gl"] = SerpApiProvider._shopping_gl
        try:
            data = self._get(params)
        except RuntimeError as e:
            if "unsupported" in str(e).lower() and "gl" in params:
                SerpApiProvider._shopping_gl = None      # Google Shopping has no Pakistan edition; remember it
                params.pop("gl")
                data = self._get(params)
            else:
                raise
        out = []
        for it in data.get("shopping_results", [])[:num]:
            out.append(RawResult(
                title=it.get("title", ""), url=it.get("product_link") or it.get("link", ""),
                price_text=it.get("price"), price=it.get("extracted_price"),
                source=it.get("source"), rating=it.get("rating"), provider=self.name, from_shopping=True,
                image_url=it.get("thumbnail"),
            ))
        return out


class SerpApiBingProvider(SearchProvider):
    """Bing results through SerpApi (Microsoft retired the official Bing Search API in Aug 2025).

    Uses the same SERPAPI_API_KEY (and quota) as the Google provider above.
    UNTESTED against the live API: if results look empty, check the `organic_results` field names.
    """

    name = "bing"
    env_key = "SERPAPI_API_KEY"

    def search(self, query, domain=None, num=10):
        q = self.site_query(query, domain)
        try:
            data = serpapi_get({"engine": "bing", "q": q, "cc": "PK", "count": min(num, 50), "api_key": self.key})
        except RuntimeError:
            # Optional params may be rejected; retry once with the bare minimum.
            data = serpapi_get({"engine": "bing", "q": q, "api_key": self.key})
        return [
            RawResult(title=it.get("title", ""), url=it.get("link", ""), snippet=it.get("snippet", ""), provider=self.name,
                      image_url=it.get("thumbnail"))
            for it in data.get("organic_results", [])
        ]
