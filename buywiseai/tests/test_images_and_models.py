import time

from buywise.utils.meta_fetch import feed_items, parse_product_image
from buywise.utils.relevance import is_accessory, title_matches_model as m
from buywise.utils.url_utils import clean_image_url, dedupe


# ---------------------------------------------------------------- pictures
def test_og_image_both_attribute_orders():
    a = '<meta property="og:image" content="https://cdn.shop.pk/p/iphone.jpg">'
    b = '<meta content="https://cdn.shop.pk/p/iphone.jpg" property="og:image">'
    assert parse_product_image(a) == parse_product_image(b) == "https://cdn.shop.pk/p/iphone.jpg"


def test_jsonld_image_list_and_relative_url():
    html = '<script type="application/ld+json">{"@type":"Product","image":["/img/a.jpg","/img/b.jpg"]}</script>'
    assert parse_product_image(html, "https://shop.pk/products/x") == "https://shop.pk/img/a.jpg"


def test_og_image_html_entities_and_http_upgrade():
    html = '<meta property="og:image" content="http://cdn.pk/a.jpg?w=1&amp;h=2">'
    assert parse_product_image(html) == "https://cdn.pk/a.jpg?w=1&h=2"


def test_no_image():
    assert parse_product_image("<html></html>") is None


def test_clean_image_url_rejects_junk():
    assert clean_image_url("data:image/png;base64,AAAA") is None
    assert clean_image_url("javascript:alert(1)") is None
    assert clean_image_url("https://x.pk/static/logo.png") is None
    assert clean_image_url("//cdn.x.pk/a.jpg") == "https://cdn.x.pk/a.jpg"
    assert clean_image_url(None) is None


def test_shopify_feed_carries_image():
    prods = [{"title": "T", "handle": "t", "variants": [{"price": "100", "available": True}],
              "images": [{"src": "https://cdn.shopify.com/a.jpg"}]},
             {"title": "U", "handle": "u", "variants": [{"price": "100", "available": True}],
              "image": {"src": "https://cdn.shopify.com/b.jpg"}}]
    assert [i["image"] for i in feed_items("s.pk", prods)] == ["https://cdn.shopify.com/a.jpg", "https://cdn.shopify.com/b.jpg"]


class _L:
    def __init__(self, url, title, price, image=None):
        self.url, self.title, self.price, self.domain, self.image_url = url, title, price, "daraz.pk", image


def test_dedupe_keeps_a_picture():
    out = dedupe([_L("https://daraz.pk/products/a-i1.html", "A", 10), _L("https://www.daraz.pk/products/a-i1.html?spm=1", "A", 10, "https://i.pk/a.jpg")])
    assert len(out) == 1 and out[0].image_url == "https://i.pk/a.jpg"


# ---------------------------------------------------------------- model / variant checks (iphone 13 log)
def test_iphone13_rejects_siblings_and_other_devices():
    q = "iphone 13"
    assert m("Apple iPhone 13 128GB Midnight", "https://shophive.com/apple-iphone-13-128gb-midnight/", q)
    assert not m("Apple iPhone 13 Pro Max 256GB", "https://telemart.pk/apple-iphone-13-pro-max-256gb", q)
    assert not m("Apple iPhone 13 Pro", "https://priceoye.pk/mobiles/apple/apple-iphone-13-pro", q)
    assert not m("Apple iPhone 13 Mini", "https://priceoye.pk/mobiles/apple/apple-iphone-13-mini", q)
    assert not m("Apple 13 iPad Pro M5 256GB", "https://czone.com.pk/apple-13-ipad-pro-m5-chip-256gb", q)


def test_asked_for_variant_is_allowed():
    assert m("Apple iPhone 13 Pro 256GB", "https://x.pk/apple-iphone-13-pro", "iphone 13 pro")
    assert not m("Samsung Galaxy S24 FE", "https://x.pk/galaxy-s24-fe", "Samsung Galaxy S24")
    assert m("Samsung Galaxy S24 Ultra", "https://x.pk/galaxy-s24-ultra", "Samsung Galaxy S24 Ultra")


def test_other_phone_queries_unchanged():
    assert m("Samsung Galaxy A55 5G 8GB/256GB", "https://shophive.com/x", "Samsung Galaxy A55 128GB")
    assert m("Airpods 2 by Apple", "https://x.pk/apple-air-pods-2", "airpods 2")      # 'Air Pods' spelled apart
    assert m("Anything", "https://x.com/y", "wireless earbuds")


def test_accessory_found_in_url_slug_when_title_is_cut_off():
    url = "https://www.shophive.com/spigen-apple-iphone-13-pro-ultra-hybrid-mag-magsafe-enabled-case-black"
    assert is_accessory("Spigen Apple iPhone 13 Pro Ultra Hybrid Mag", "iphone 13", url)
    assert not is_accessory("Apple iPhone 13 128GB", "iphone 13", "https://shophive.com/apple-iphone-13-128gb-midnight/")
    assert not is_accessory("iPhone 13 with free case", "iphone 13", "https://x.pk/iphone-13-with-free-case")


# ---------------------------------------------------------------- USD price on a rupee store
def test_usd_price_on_pkr_store_is_not_trusted():
    from buywise.agents.extract import _to_listing
    from buywise.config import load_platforms
    from buywise.schemas import RawResult
    plats = load_platforms()
    usd = _to_listing(RawResult(title="Apple iPhone 13 Mini", url="https://x.whatmobile.com.pk/Apple_iPhone-13-Mini",
                                snippet="Launch price $789", image_url="//cdn.x.pk/a.jpg"), plats)
    assert usd.price is None and usd.image_url == "https://cdn.x.pk/a.jpg"
    pkr = _to_listing(RawResult(title="Apple iPhone 13 128GB", url="https://www.shophive.com/apple-iphone-13-128gb-midnight/",
                                snippet="Rs. 219,999"), plats)
    assert pkr.price == 219999.0
    ali = _to_listing(RawResult(title="Lipo battery", url="https://www.aliexpress.com/item/1005012580330936.html",
                                snippet="US $39.10"), plats)
    assert ali.price == 39.1 and ali.currency == "USD"


# ---------------------------------------------------------------- Groq rate limit handling
def test_retry_seconds_parsing():
    from buywise.llm import retry_seconds
    assert retry_seconds("Please try again in 7m33.6s. Need more tokens?") == 7 * 60 + 33.6
    assert retry_seconds("try again in 45.5s") == 45.5
    assert retry_seconds("something else") == 60.0


def test_llm_cooldown_skips_the_api():
    import buywise.llm as llm_mod
    llm_mod._cooldown_until = time.time() + 120
    try:
        try:
            llm_mod.LLM().chat("s", "u")
            raise AssertionError("expected LLMError")
        except llm_mod.LLMError as e:
            assert "rate limit" in str(e).lower()
    finally:
        llm_mod._cooldown_until = 0.0


def test_aliexpress_locale_hosts_collapse_to_main_storefront():
    from buywise.agents.extract import _home_storefront
    from buywise.utils.url_utils import canonicalize_url
    vi = "https://vi.aliexpress.com/item/1005010789592619.html?gps-id=x&pdp_npi=6%40dis%21VND%21462040"
    assert _home_storefront(vi, "vi.aliexpress.com") == "https://www.aliexpress.com/item/1005010789592619.html"
    assert canonicalize_url(vi) == canonicalize_url("https://www.aliexpress.com/item/1005010789592619.html")
    assert _home_storefront("https://www.daraz.pk/products/a-i1.html", "daraz.pk") == "https://www.daraz.pk/products/a-i1.html"
