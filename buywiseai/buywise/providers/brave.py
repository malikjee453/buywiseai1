"""Brave Search API (free tier is rate-limited to ~1 request/second)."""
from __future__ import annotations

import threading
import time

from buywise.providers.base import SearchProvider, http_json
from buywise.schemas import RawResult

_lock = threading.Lock()
_last_call = [0.0]


class BraveProvider(SearchProvider):
    name = "brave"
    env_key = "BRAVE_API_KEY"

    def search(self, query, domain=None, num=10):
        with _lock:  # serialise calls to respect the free-tier rate limit
            wait = 1.1 - (time.time() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.time()
        data = http_json(
            "GET", "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": self.key, "Accept": "application/json"},
            params={"q": self.site_query(query, domain), "country": "pk", "count": min(num, 20)},
        )
        return [
            RawResult(title=it.get("title", ""), url=it.get("url", ""), snippet=it.get("description", ""), provider=self.name)
            for it in data.get("web", {}).get("results", [])
        ]
