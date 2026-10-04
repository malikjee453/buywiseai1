"""Light, dependency-free relevance helpers (accessory detection, price outliers)."""
from __future__ import annotations

import re
import statistics

from buywise.config import load_app_settings


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])", text.lower()) is not None


def is_accessory(title: str, query: str) -> bool:
    """True if the title looks like an accessory the user did not ask for.

    "... with charger" / "... with case" describe what is in the box, so they are ignored.
    """
    checked = re.sub(r"\bwith\s+(?:a\s+|free\s+|original\s+)?[a-z]+", " ", title.lower())
    for word in load_app_settings().get("accessory_words", []):
        if _has_word(checked, word) and not _has_word(query, word):
            return True
    return False


_SPEC_UNIT = re.compile(r"^\d+(?:gb|tb|mb|mah|w|hz|mp|inch|in|ton|kg|ml|l|cm|mm|v|k|g|pcs|pack|ram|rom)$")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def model_tokens(query: str) -> list[str]:
    """Tokens that identify the exact model: 'a55', 's24', or a short bare number like '15'.

    Spec tokens (128gb, 5000mah, 55inch) are ignored because titles often omit them.
    """
    toks = _tokens(re.sub(r"\d+\.\d+", " ", query))     # drop decimals like "1.5" (a ton rating, not a model)
    mixed = [t for t in toks if re.search(r"\d", t) and re.search(r"[a-z]", t) and not _SPEC_UNIT.match(t)]
    if mixed:
        return mixed
    return [t for t in toks if t.isdigit() and len(t) <= 3]


def title_matches_model(title: str, url: str, query: str) -> bool:
    """True if every model token of the query appears in the title or URL path.

    Stops 'Galaxy A57', 'A54' or a smartwatch from passing as 'Galaxy A55'.
    """
    required = model_tokens(query)
    if not required:
        return True
    path = url.split("?")[0].split("//", 1)[-1]
    hay = set(_tokens(title)) | set(_tokens(path))
    return all(t in hay for t in required)


def median_price(prices: list[float]) -> float | None:
    prices = [p for p in prices if p and p > 0]
    return statistics.median(prices) if prices else None


def is_price_outlier_low(price: float, median: float | None, min_items: int, ratio: float = 0.4) -> bool:
    """Flag prices far below the median (possible used item / accessory / scam)."""
    return bool(median) and min_items >= 4 and price < ratio * median


_FEMALE = {"women", "womens", "woman", "ladies", "lady", "girl", "girls", "female", "her"}
_MALE = {"men", "mens", "man", "boy", "boys", "male", "gents", "gent", "him"}


def gender_conflict(title: str, url: str, query: str) -> bool:
    """True if the query asks for one gender and the listing is clearly for the other.

    "shalwar kameez for girls" must not return "Men's Shalwar Kameez".
    """
    q = set(_tokens(query))
    want_f, want_m = bool(q & _FEMALE), bool(q & _MALE)
    if want_f == want_m:                      # neither, or both: no constraint
        return False
    hay = set(_tokens(title)) | set(_tokens(url.split("?")[0].split("//", 1)[-1]))
    has_f, has_m = bool(hay & _FEMALE), bool(hay & _MALE)
    return (want_f and has_m and not has_f) or (want_m and has_f and not has_m)


_LEX_STOP = {"for", "in", "the", "and", "with", "of", "a", "an", "to", "pakistan", "price", "online", "buy", "best"}


def lexical_match(title: str, url: str, snippet: str, product: str, min_ratio: float = 0.5) -> bool:
    """True if at least `min_ratio` of the product words appear in the listing's title/URL/snippet.

    The cross-encoder knows little South-Asian clothing vocabulary (it scores 'Girls Embroidered Khaddar 2 Piece
    Suit - Farshi Shalwar' at -11 for 'shalwar kameez'), so a plain word overlap rescues obvious matches.
    Model/accessory/gender checks and the LLM judge still run afterwards.
    """
    toks = [t for t in _tokens(product) if t not in _LEX_STOP and len(t) > 1]
    if not toks:
        return False
    hay = set(_tokens(title)) | set(_tokens(url.split("?")[0].split("//", 1)[-1])) | set(_tokens(snippet or ""))
    return sum(t in hay for t in toks) / len(toks) >= min_ratio
