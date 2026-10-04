from buywise.utils.meta_fetch import parse_daraz_embedded, parse_product_meta
from buywise.providers.base import price_text_from
from buywise.utils.relevance import drop_broader_variants, is_accessory, lexical_match


def test_drops_generic_variant():
    v = ["lipo battery", "lipo", "3.7v lithium polymer battery", "buy lipo battery online Pakistan"]
    assert drop_broader_variants(v, "lipo battery") == [
        "lipo battery", "3.7v lithium polymer battery", "buy lipo battery online Pakistan"]


def test_single_word_product_keeps_variants():
    assert drop_broader_variants(["kurta", "men kurta"], "kurta") == ["kurta", "men kurta"]


def test_users_own_wording_never_dropped():
    assert drop_broader_variants(["lipo battery", "lipo battery 3.7v"], "lipo battery 3.7v",
                                 keep="lipo battery") == ["lipo battery", "lipo battery 3.7v"]


def test_lexical_rescue_for_low_rerank_titles():
    # the enrichment gate now lets these through even when the cross-encoder score is below the threshold
    assert lexical_match("Lipo Battery 3.7V 1800mAh with USB charging wire",
                         "https://www.daraz.pk/products/lipo-battery-37v-1800ma-i1961941261.html", "", "lipo battery")
    assert not lexical_match("Joyroom PBF15 22.5W LED Fast Charging Power Bank",
                             "https://www.daraz.pk/products/joyroom-pbf15-i1.html", "", "lipo battery")


# Synthetic snippets mimicking Daraz's embedded JSON; replace with a real saved page when you have one.
DARAZ_SALE = '''<script>app.run({"data":{"root":{"fields":{"skuInfos":{"0":{"price":{"salePrice":{"text":"Rs. 1,299","value":1299},"originalPrice":{"value":1999}}}}}}}});</script>'''
DARAZ_TRACK = '''<script>var pdpTrackingData = {"pdt_price":"Rs. 1,499","pdt_name":"x"};</script>'''


def test_daraz_sale_price():
    assert parse_product_meta(DARAZ_SALE) is None            # not in JSON-LD / OG
    assert parse_daraz_embedded(DARAZ_SALE) == (1299.0, "PKR")


def test_daraz_tracking_price_fallback():
    assert parse_daraz_embedded(DARAZ_TRACK) == (1499.0, "PKR")


def test_daraz_no_price():
    assert parse_daraz_embedded("<html>nothing</html>") is None


def test_plural_accessories_caught_without_llm():
    assert is_accessory("ISDT lipo battery chargers 6s and 8s", "lipo battery")
    assert is_accessory("Phone Cases Pack of 3", "samsung a55")
    assert not is_accessory("Lipo Battery 3.7V 1800mAh", "lipo battery")
    assert not is_accessory("Lipo battery chargers", "lipo battery charger")   # user asked for one


def test_enrichment_gate_needs_both_words_for_two_word_product():
    assert not lexical_match("Joyroom 22.5W Power Bank", "https://daraz.pk/products/joyroom-i1.html",
                             "20000mAh lithium battery", "lipo battery", min_ratio=0.6)
    assert lexical_match("Lipo Battery 800mAh", "https://daraz.pk/products/lipo-i2.html", "", "lipo battery", min_ratio=0.6)


def test_nested_rich_snippet_price():
    item = {"title": "x", "richSnippet": {"top": {"extensions": [{"Price": "Rs. 1,299"}]}}}
    assert price_text_from(item) == "Rs. 1,299"
    assert price_text_from({"attributes": {"Price": "Rs 500"}}) == "Rs 500"
    assert price_text_from({"title": "no price here"}) is None
