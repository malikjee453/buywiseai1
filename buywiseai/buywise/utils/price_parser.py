"""Parse Pakistani / AliExpress price strings.

Handles: "Rs. 45,999", "PKR 45999", "Rs 45,999/-", "₨45,999", "Rs. 1,29,999",
"45,999 PKR", "US $129.99", "$12.50", "USD 12.5". Returns the FIRST price found.
Text without an explicit currency marker is NOT treated as a price (so model names
like "A55 8GB 256GB" never produce false prices). Range bounds such as
"above 100,000 PKR" or "under Rs 50,000" are NOT prices either.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

_NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?<![A-Za-z])(?:US\s?\$|USD|\$)\s*" + _NUM, re.I), "USD"),
    (re.compile(r"(?<![A-Za-z0-9,.])" + _NUM + r"\s*USD\b", re.I), "USD"),
    (re.compile(r"(?<![A-Za-z])(?:Rs\.?|PKR|Rupees?)\s*" + _NUM, re.I), "PKR"),
    (re.compile(r"₨\s*" + _NUM), "PKR"),
    (re.compile(r"(?<![A-Za-z0-9,.])" + _NUM + r"\s*(?:/-|PKR\b)", re.I), "PKR"),
]

# "Mobile Prices above 100,000 PKR", "under Rs. 50,000": a bound, not a product price
_BOUND_BEFORE = re.compile(r"(?:above|over|under|below|between|upto|up to|less than|more than)\s*$", re.I)


class ParsedPrice(NamedTuple):
    amount: float
    currency: str


def _matches(text: str) -> list[tuple[int, float, str]]:
    """All distinct price mentions as (position, amount, currency), left to right."""
    found: dict[int, tuple[int, float, str]] = {}
    for pattern, cur in _PATTERNS:
        for m in pattern.finditer(text):
            if _BOUND_BEFORE.search(text[max(0, m.start() - 14):m.start()]):
                continue
            try:
                amount = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if amount > 0 and m.start(1) not in found:
                found[m.start(1)] = (m.start(), amount, cur)
    return sorted(found.values())


def parse_price(text: Optional[str], default_currency: Optional[str] = None) -> Optional[ParsedPrice]:
    """Return the earliest price in `text`, or None.

    A bare number ("45999") uses `default_currency` when given.
    """
    if not text:
        return None
    text = str(text).strip()
    hits = _matches(text)
    if hits:
        return ParsedPrice(hits[0][1], hits[0][2])
    if default_currency and re.fullmatch(_NUM, text):
        amount = float(text.replace(",", ""))
        if amount > 0:
            return ParsedPrice(amount, default_currency)
    return None


def count_prices(text: Optional[str]) -> int:
    """Number of distinct prices in text. Many prices => a list/category page, not one product."""
    return len(_matches(str(text))) if text else 0


def find_price(*texts: Optional[str]) -> Optional[ParsedPrice]:
    """Try several texts (e.g. price field, title, snippet) in order."""
    for t in texts:
        p = parse_price(t)
        if p:
            return p
    return None
