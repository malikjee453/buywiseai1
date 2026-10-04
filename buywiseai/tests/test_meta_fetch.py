from buywise.utils.meta_fetch import parse_product_meta

JSONLD = '''<html><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"X",
 "offers":{"@type":"Offer","price":"89,999","priceCurrency":"PKR"}}</script></html>'''

AGG = '''<script type="application/ld+json">{"@type":"Product","offers":
{"@type":"AggregateOffer","lowPrice":12.5,"priceCurrency":"USD"}}</script>'''

OG = '<meta property="product:price:amount" content="45,000"><meta property="product:price:currency" content="PKR">'


def test_jsonld_offer():
    assert parse_product_meta(JSONLD) == (89999.0, "PKR")


def test_jsonld_aggregate_offer():
    assert parse_product_meta(AGG) == (12.5, "USD")


def test_opengraph_fallback():
    assert parse_product_meta(OG) == (45000.0, "PKR")


def test_no_price():
    assert parse_product_meta("<html><body>hello</body></html>") is None
