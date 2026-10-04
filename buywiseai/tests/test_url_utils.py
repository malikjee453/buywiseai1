from types import SimpleNamespace as NS

from buywise.config import match_platform
from buywise.utils.url_utils import canonicalize_url, dedupe, get_domain, is_product_url


def test_domain():
    assert get_domain("https://www.daraz.pk/products/x-i1.html?spm=a") == "daraz.pk"
    assert get_domain("https://m.priceoye.pk/mobiles") == "m.priceoye.pk"


def test_canonicalize_strips_tracking_and_www():
    a = canonicalize_url("http://www.Example.com/p/1/?utm_source=x&id=5#frag")
    assert a == "https://example.com/p/1?id=5"


def test_canonicalize_daraz_and_ali_drop_query():
    assert canonicalize_url("https://www.daraz.pk/products/a-i1.html?search=1&spm=2") == "https://daraz.pk/products/a-i1.html"
    assert canonicalize_url("https://www.aliexpress.com/item/100.html?spm=x") == "https://aliexpress.com/item/100.html"


def test_product_url_detection():
    assert is_product_url("https://www.daraz.pk/products/samsung-a55-i123-s456.html")
    assert not is_product_url("https://www.daraz.pk/catalog/?q=samsung")
    assert not is_product_url("https://www.daraz.pk/mobiles/")
    assert is_product_url("https://www.aliexpress.com/item/1005006.html")
    assert not is_product_url("https://www.aliexpress.com/w/wholesale-phone.html")
    assert not is_product_url("https://shophive.com/")
    assert not is_product_url("https://shophive.com/catalogsearch/result/?q=a55")
    assert is_product_url("https://shophive.com/samsung-galaxy-a55")


def test_platform_whitelist_matching():
    assert match_platform("daraz.pk").name == "Daraz"
    assert match_platform("m.daraz.pk").name == "Daraz"
    assert match_platform("pk.aliexpress.com").name == "AliExpress"
    assert match_platform("amazon.com") is None
    assert match_platform("notdaraz.pk") is None


def _l(url, title, price, domain="daraz.pk"):
    return NS(url=url, title=title, price=price, domain=domain)


def test_dedupe_by_url_and_signature():
    items = [
        _l("https://daraz.pk/products/a-i1.html?spm=1", "Samsung A55", 80000),
        _l("https://www.daraz.pk/products/a-i1.html", "Samsung A55 ", 80000),
        _l("https://daraz.pk/products/b-i2.html", "Samsung  A55!", 80000),
        _l("https://daraz.pk/products/c-i3.html", "Samsung A55", 85000),
    ]
    assert len(dedupe(items)) == 2
