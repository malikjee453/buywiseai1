"""Provider registry. Add a new engine: subclass SearchProvider and list it here."""
from __future__ import annotations

from buywise.providers.aliexpress import AliExpressProvider
from buywise.providers.base import SearchProvider
from buywise.providers.brave import BraveProvider
from buywise.providers.ddg import DuckDuckGoProvider
from buywise.providers.serpapi import SerpApiProvider
from buywise.providers.serper import SerperProvider
from buywise.providers.tavily import TavilyProvider

ALL_PROVIDERS: list[type[SearchProvider]] = [
    SerperProvider, SerpApiProvider, TavilyProvider, BraveProvider, DuckDuckGoProvider, AliExpressProvider,
]


def get_providers(enabled: list[str] | None = None) -> list[SearchProvider]:
    """Instantiate providers that have credentials; `enabled` (names) filters them."""
    out = []
    for cls in ALL_PROVIDERS:
        inst = cls()
        if inst.available() and (not enabled or inst.name in enabled):
            out.append(inst)
    return out


def provider_status() -> dict[str, bool]:
    """name -> available (key present). Used by the UI sidebar."""
    return {cls.name: cls().available() for cls in ALL_PROVIDERS}
