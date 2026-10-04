"""Parse Pakistani / AliExpress price strings.

Handles: "Rs. 45,999", "PKR 45999", "Rs 45,999/-", "₨45,999", "Rs. 1,29,999",
"45,999 PKR", "US $129.99", "$12.50", "USD 12.5". Returns the FIRST price found.
Text without an explicit currency marker is NOT treated as a price (so model names
like "A55 8GB 256GB" never produce false prices).
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

_NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # USD first: "US $129.99", "USD 12.5", "$12.50"
    (re.compile(r"(?<![A-Za-z])(?:US\s?\$|USD|\$)\s*" + _NUM, re.I), "USD"),
    (re.compile(r"(?<![A-Za-z0-9,.])" + _NUM + r"\s*USD\b", re.I), "USD"),
    # PKR: "Rs. 1,29,999", "PKR 45999", "₨45,999", "Rupees 500"
    (re.compile(r"(?<![A-Za-z])(?:Rs\.?|PKR|Rupees?)\s*" + _NUM, re.I), "PKR"),
    (re.compile(r"₨\s*" + _NUM), "PKR"),
    (re.compile(r"(?<![A-Za-z0-9,.])" + _NUM + r"\s*(?:/-|PKR\b)", re.I), "PKR"),
]


class ParsedPrice(NamedTuple):
    amount: float
    currency: str


def parse_price(text: Optional[str], default_currency: Optional[str] = None) -> Optional[ParsedPrice]:
    """Return the earliest price in `text`, or None.

    If `text` is a bare number ("45999") and `default_currency` is given, that currency
    is used (useful for API fields that carry a number without a symbol).
    """
    if not text:
        return None
    text = str(text).strip()
    best: Optional[tuple[int, float, str]] = None
    for pattern, cur in _PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            amount = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if amount <= 0:
            continue
        if best is None or m.start() < best[0]:
            best = (m.start(), amount, cur)
    if best:
        return ParsedPrice(best[1], best[2])
    if default_currency and re.fullmatch(_NUM, text):
        amount = float(text.replace(",", ""))
        if amount > 0:
            return ParsedPrice(amount, default_currency)
    return None


def find_price(*texts: Optional[str]) -> Optional[ParsedPrice]:
    """Try several texts (e.g. price field, title, snippet) in order."""
    for t in texts:
        p = parse_price(t)
        if p:
            return p
    return None
