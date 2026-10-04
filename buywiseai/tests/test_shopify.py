from buywise.utils.meta_fetch import collection_handle, feed_items, price_from_product_json, product_handle
from buywise.utils.redact import redact_secrets
from buywise.utils.url_utils import is_foreign_storefront, is_product_url

FEED = [
    {"title": "Embroidered Lawn 2 Piece", "handle": "emb-lawn-2pc", "product_type": "Girls Shalwar Kameez",
     "vendor": "Alkaram", "tags": ["girls", "lawn", "kids"],
     "variants": [{"price": "5990.00", "available": True}, {"price": "6490.00", "available": True}]},
    {"title": "Sold Out Suit", "handle": "sold-out", "variants": [{"price": "4000.00", "available": False}]},
    {"title": "No Price", "handle": "np", "variants": [{"price": None, "available": True}]},
    {"title": "Tags As String", "handle": "ts", "tags": "a, b, c", "variants": [{"price": "1200", "available": True}]},
]


def test_collection_vs_product_handles():
    assert collection_handle("https://www.gulahmedshop.com/collections/women-shalwar-kameez") == "women-shalwar-kameez"
    assert collection_handle("https://x.pk/collections/kids/?page=2&srsltid=abc") == "kids"
    assert collection_handle("https://x.pk/collections/kids/products/abc") is None
    assert collection_handle("https://x.pk/products/abc") is None
    assert product_handle("https://x.pk/products/embroidered-2pc") == "embroidered-2pc"
    assert product_handle("https://x.pk/collections/kids/products/embroidered-2pc") == "embroidered-2pc"
    assert product_handle("https://x.pk/collections/kids") is None


def test_feed_items_keep_only_priced_in_stock():
    items = feed_items("alkaramstudio.com", FEED)
    assert [i["title"] for i in items] == ["Embroidered Lawn 2 Piece", "Tags As String"]
    assert items[0]["price"] == 5990.0                      # cheapest in-stock variant
    assert items[0]["url"] == "https://alkaramstudio.com/products/emb-lawn-2pc"
    assert "Girls Shalwar Kameez" in items[0]["snippet"]


def test_price_from_product_json():
    assert price_from_product_json({"product": FEED[0]}) == 5990.0
    assert price_from_product_json({"product": FEED[1]}) is None


def test_foreign_storefronts():
    assert is_foreign_storefront("us.khaadi.com")
    assert is_foreign_storefront("uae.gulahmedshop.com")
    assert is_foreign_storefront("uk.khaadi.com")
    assert not is_foreign_storefront("khaadi.com")
    assert not is_foreign_storefront("pk.khaadi.com")
    assert not is_foreign_storefront("pk.aliexpress.com")
    assert not is_foreign_storefront("ar.aliexpress.com")     # locale variant, exempt
    assert not is_foreign_storefront("amazon.com")


def test_real_urls_from_trace():
    # not products (seen in your trace)
    assert not is_product_url("https://www.daraz.pk/womens-shalwar-kameez/")
    assert not is_product_url("https://www.daraz.pk/tag/shalwar-kameez-girls-kids/")
    assert not is_product_url("https://www.alkaramstudio.com/collections/men-rts-core?page=2")
    assert not is_product_url("https://www.gulahmedshop.com/blogs/news/tagged/ideas-pret?page=1")
    # real product
    assert is_product_url("https://www.daraz.pk/products/boys-shalwar-kameez-i471900105.html")


def test_redaction():
    t = "https://serpapi.com/search.json failed: 400 for url ?engine=bing&api_key=abcdef1234567890&q=x"
    assert "abcdef1234567890" not in redact_secrets(t)
    assert "abcdef1234567890" not in redact_secrets("Authorization: Bearer sk_live_1234567890abcd")
    assert redact_secrets("plain text") == "plain text"
