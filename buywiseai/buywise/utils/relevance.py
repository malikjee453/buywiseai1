"""Light, dependency-free relevance helpers (accessory detection, price outliers)."""
from __future__ import annotations

import re
import statistics
from urllib.parse import urlparse

from buywise.config import load_app_settings


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])", text.lower()) is not None


def is_accessory(title: str, query: str, url: str = "") -> bool:
    """True if the title (or URL slug) looks like an accessory the user did not ask for.

    "... with charger" / "... with case" describe what is in the box, so they are ignored.
    The URL slug is checked too because search titles are often truncated before the word 'case'.
    """
    texts = [title.lower()]
    if url:
        texts.append(re.sub(r"[^a-z0-9]+", " ", urlparse(url).path.lower()))
    words = load_app_settings().get("accessory_words", [])
    for text in texts:
        checked = re.sub(r"\bwith\s+(?:a\s+|free\s+|original\s+)?[a-z]+", " ", text)
        for word in words:
            if _has_word_pl(checked, word) and not _has_word_pl(query, word):
                return True
    return False


def _has_word_pl(text: str, word: str) -> bool:
    """Like _has_word but also matches the plural ('chargers', 'cases', 'straps')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?:s|es)?(?![a-z0-9])", text.lower()) is not None


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


_VARIANT_WORDS = {"pro", "max", "plus", "ultra", "mini", "lite", "fe", "se", "air", "fold", "flip"}
_PREV_STOP = {"for", "the", "and", "with", "new", "buy", "best", "pro", "max", "plus"}


def _variant_conflict(t_seq: list[str], p_seq: list[str], required: list[str], query: str) -> bool:
    """'iPhone 13 Pro Max' / 'Galaxy S24 FE' when the user asked for plain 'iPhone 13' / 'Galaxy S24'."""
    asked = set(_tokens(query))
    for seq in (t_seq, p_seq):
        for i in range(len(seq) - 1):
            if seq[i] in required and seq[i + 1] in _VARIANT_WORDS and seq[i + 1] not in asked:
                return True
    return False


def title_matches_model(title: str, url: str, query: str) -> bool:
    """True if the listing is the model the query names (not a sibling model, variant or other device).

    Every model token must appear in the title or URL path; a variant word right after it ('13 Pro', 'S24 Ultra')
    must have been asked for; and for a bare number ('iphone 13') the word before it ('iphone') must appear too,
    so 'iPad Pro 13' cannot pass as 'iPhone 13'.
    """
    required = model_tokens(query)
    if not required:
        return True
    path = url.split("?")[0].split("//", 1)[-1]
    t_seq, p_seq = _tokens(title), _tokens(path)
    hay = set(t_seq) | set(p_seq)
    if not all(t in hay for t in required):
        return False
    if _variant_conflict(t_seq, p_seq, required, query):
        return False
    qtoks = _tokens(re.sub(r"\d+\.\d+", " ", query))
    joined = "".join(t_seq + p_seq)
    for t in required:
        if t.isdigit() and t in qtoks:
            idx = qtoks.index(t)
            prev = qtoks[idx - 1] if idx > 0 else ""
            if prev.isalpha() and len(prev) >= 3 and prev not in _PREV_STOP and prev not in joined:
                return False
    return True


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
    toks = [normalize_word(t) for t in _tokens(product) if t not in _LEX_STOP and len(t) > 1]
    if not toks:
        return False
    hay = {normalize_word(t) for t in
           set(_tokens(title)) | set(_tokens(url.split("?")[0].split("//", 1)[-1])) | set(_tokens(snippet or ""))}
    return sum(t in hay for t in toks) / len(toks) >= min_ratio


_KIDS = {"kid", "kids", "child", "children", "baby", "babies", "toddler", "toddlers", "infant"}


def judge_query(query: str) -> str:
    """Query text for the LLM relevance judge.

    LLMs read 'for girls' as 'children only' and reject women's items. So audience words are removed from the
    product text and restated as an explicit rule: gender is enforced, age is not.
    """
    toks = re.findall(r"[A-Za-z0-9.+\-']+", query)
    low = [t.lower() for t in toks]
    audience = _FEMALE | _MALE | _KIDS
    fem, mal, kid = (any(t in grp for t in low) for grp in (_FEMALE, _MALE, _KIDS))
    kept = [t for t, l in zip(toks, low) if l not in audience]
    while kept and kept[-1].lower() in {"for", "of", "to"}:
        kept.pop()
    base = " ".join(kept) or query
    if kid:
        return f"{base} (audience: children)"
    if fem and not mal:
        return f"{base} (audience: female, any age; reject only clearly male-only items)"
    if mal and not fem:
        return f"{base} (audience: male, any age; reject only clearly female-only items)"
    return base


# Common Pakistani-English spelling variants of the same word -> canonical form
_CANON = {"salwar": "shalwar", "shalwaar": "shalwar", "salwaar": "shalwar", "shalwer": "shalwar",
          "qameez": "kameez", "kameeze": "kameez", "kamiz": "kameez", "qamis": "kameez", "kameezz": "kameez"}
_SWAP = {"salwar": "shalwar", "shalwar": "salwar", "qameez": "kameez", "kameez": "qameez"}


def normalize_word(w: str) -> str:
    return _CANON.get(w, w)


def spelling_swap(query: str) -> str:
    """'salwar suit' -> 'shalwar suit' (search engines treat the spellings as different words)."""
    return " ".join(_SWAP.get(w.lower(), w) for w in query.split())


def drop_broader_variants(variants: list[str], product: str, keep: str | None = None) -> list[str]:
    """Remove search variants that are strictly more generic than the product ('lipo' for 'lipo battery').

    Such variants pull in unrelated items (mice, power banks, chargers) and waste LLM-judge calls.
    Only applies when the product has 2+ content words; a one-word product keeps all its variants.
    `keep` (the user's own wording) is never dropped.
    """
    ptoks = {normalize_word(t) for t in _tokens(product) if t not in _LEX_STOP and len(t) > 1}
    if len(ptoks) < 2:
        return list(variants)
    out = []
    for v in variants:
        vtoks = {normalize_word(t) for t in _tokens(v) if t not in _LEX_STOP and len(t) > 1}
        if vtoks and vtoks < ptoks and not (keep and v.strip().lower() == keep.strip().lower()):   # proper subset => broader
            continue
        out.append(v)
    return out
