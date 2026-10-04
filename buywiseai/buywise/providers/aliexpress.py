"""Official AliExpress Affiliate API provider (optional).

UNTESTED until you have approved keys from portals.aliexpress.com: verify the response
field names against the current API docs when you first enable it. Without keys this
provider is unavailable and AliExpress is covered by `site:aliexpress.com` searches.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from buywise.config import get_secret
from buywise.providers.base import SearchProvider, http_json
from buywise.schemas import RawResult

_ENDPOINT = "https://api-sg.aliexpress.com/sync"


class AliExpressProvider(SearchProvider):
    name = "aliexpress_api"
    env_key = "ALIEXPRESS_APP_KEY"
    supports_shopping = True

    def __init__(self) -> None:
        super().__init__()
        self.secret = get_secret("ALIEXPRESS_APP_SECRET")
        self.tracking_id = get_secret("ALIEXPRESS_TRACKING_ID", "default")

    def available(self) -> bool:
        return bool(self.key and self.secret)

    def _sign(self, params: dict) -> str:
        base = "".join(f"{k}{params[k]}" for k in sorted(params))
        return hmac.new(self.secret.encode(), base.encode(), hashlib.sha256).hexdigest().upper()

    def search(self, query, domain=None, num=10):
        return self.shopping(query, num) if (domain is None or "aliexpress" in domain) else []

    def shopping(self, query, num=10):
        params = {
            "app_key": self.key, "timestamp": str(int(time.time() * 1000)), "sign_method": "sha256",
            "method": "aliexpress.affiliate.product.query", "keywords": query,
            "ship_to_country": "PK", "target_currency": "USD", "target_language": "EN",
            "page_size": str(min(num, 20)), "tracking_id": self.tracking_id,
        }
        params["sign"] = self._sign(params)
        data = http_json("GET", _ENDPOINT, params=params)
        resp = data.get("aliexpress_affiliate_product_query_response", {}).get("resp_result", {})
        products = resp.get("result", {}).get("products", {}).get("product", [])
        out = []
        for p in products:
            price = p.get("target_sale_price") or p.get("target_original_price")
            out.append(RawResult(
                title=p.get("product_title", ""), url=p.get("product_detail_url", ""),
                price=float(price) if price else None, currency=p.get("target_sale_price_currency", "USD"),
                source="AliExpress", provider=self.name, from_shopping=True,
            ))
        return out
