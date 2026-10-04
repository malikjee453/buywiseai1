"""Light, dependency-free relevance helpers (accessory detection, price outliers)."""
from __future__ import annotations

import re
import statistics

from buywise.config import load_app_settings


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])", text.lower()) is not None


def is_accessory(title: str, query: str) -> bool:
    """True if the title looks like an accessory the user did not ask for."""
    for word in load_app_settings().get("accessory_words", []):
        if _has_word(title, word) and not _has_word(query, word):
            return True
    return False


def median_price(prices: list[float]) -> float | None:
    prices = [p for p in prices if p and p > 0]
    return statistics.median(prices) if prices else None


def is_price_outlier_low(price: float, median: float | None, min_items: int, ratio: float = 0.4) -> bool:
    """Flag prices far below the median (possible used item / accessory / scam)."""
    return bool(median) and min_items >= 4 and price < ratio * median
